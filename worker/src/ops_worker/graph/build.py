"""The worker graph's wiring and its driver (AM-12 SA:207-218; Plan Q rulings 2, 5 and 6).

`build_graph` adds SA:207's ten nodes and generates `route_request`'s conditional edges from the route table
(`ops_core.routing.GRAPH_ROUTES`): the edge map is `{route: node}` for every route a row names, so an edge exists
exactly when a row can choose it. The nodes that do work return to `route_request`; the two waiting nodes interrupt;
`publish_state` ends the graph run when the table routes the run to `publish` (and otherwise returns to the router),
and `execute_approved_proposal` hands over to `reconcile_outcome`, which ends it (ruling 14).

`run_graph` drives one graph run under the job's lease with `durability="sync"` (SA:210) and
`stream_mode="checkpoints"`. Each checkpoint LangGraph announces is confirmed with `aget_tuple` before its id is
stored in `runs.checkpoint_id` under the fence (SA:211, T20 review note 2): the announcement of a run's first
checkpoint, or of a fork, can come before the saver has written it (langgraph 1.2.14 `pregel/_loop.py:1262-1275`
submits the write without waiting; `pregel/main.py:3526-3527` waits only after a superstep). The event arrives
before the next node starts (`pregel/_runner.py:388-389` yields first), so the store never races a node's own unit
on the loop connection. At an interrupt the last stored id is the checkpoint that holds the interrupt's write.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Hashable, Mapping
from typing import Any, Final

import psycopg
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from ops_core import persistence
from ops_core.routing import GRAPH_ROUTES, GraphRoute, route_graph
from ops_core.settings import Postgres
from psycopg.rows import DictRow, dict_row

from ops_worker.drafting import WORKFLOW_VERSION
from ops_worker.graph import nodes
from ops_worker.graph.state import Context, RunGraphState, key

Node = Callable[..., Awaitable[dict[str, Any]]]
NODES: Final[dict[str, Node]] = {
    "load_run": nodes.load_run,
    "route_request": nodes.route_request,
    "await_clarification": nodes.await_clarification,
    "retrieve_evidence": nodes.retrieve_evidence,
    "draft_with_langchain": nodes.draft_with_langchain,
    "validate_and_freeze": nodes.validate_and_freeze,
    "await_independent_decision": nodes.await_independent_decision,
    "execute_approved_proposal": nodes.execute_approved_proposal,
    "reconcile_outcome": nodes.reconcile_outcome,
    "publish_state": nodes.publish_state,
}
# Each route's node (docs/ARCHITECTURE.md §3): one node per route, three routes to publish_state.
ROUTE_NODES: Final[dict[GraphRoute, str]] = {
    GraphRoute.CLARIFY: "await_clarification",
    GraphRoute.RETRIEVE: "retrieve_evidence",
    GraphRoute.DRAFT: "draft_with_langchain",
    GraphRoute.ANSWER_ONLY: "publish_state",
    GraphRoute.ABSTAIN: "publish_state",
    GraphRoute.FREEZE: "validate_and_freeze",
    GraphRoute.AWAIT_DECISION: "await_independent_decision",
    GraphRoute.EXECUTE: "execute_approved_proposal",
    GraphRoute.RECOVER: "reconcile_outcome",
    GraphRoute.PUBLISH: "publish_state",
}
RETURNS_TO_ROUTER: Final = (
    "retrieve_evidence",
    "draft_with_langchain",
    "validate_and_freeze",
    "await_clarification",
    "await_independent_decision",
)
# Supersteps per graph run: the longest path (a resumed clarification through to the freeze and the wait) is 9; a
# node that kept routing back to itself fails the graph run instead of spinning (GraphRecursionError).
RECURSION_LIMIT: Final = 30
CONFIRM_TRIES: Final = 50  # aget_tuple polls before a checkpoint counts as not written (5 s in all)
CONFIRM_SECONDS: Final = 0.1
GraphInput = RunGraphState | Command[Any] | None


def edge_map() -> dict[Hashable, str]:
    """`route_request`'s conditional edges, generated from the table: {route: node} for every route a row names."""
    return {rule.route.value: ROUTE_NODES[rule.route] for rule in GRAPH_ROUTES}


def next_route(state: RunGraphState) -> str:
    """The path function of `route_request`'s conditional edges: the table's route for the state's key."""
    return route_graph(key(state)).value


def after_publish(state: RunGraphState) -> str:
    """`publish_state`'s way out, read from the same table: the graph run ends when the run is settled (the `publish`
    route); a run `publish_state` could not settle (its held answer was lost) goes back to the router."""
    return END if route_graph(key(state)) is GraphRoute.PUBLISH else "route_request"


def build_graph(
    saver: BaseCheckpointSaver[str], replace: Mapping[str, Node] | None = None
) -> CompiledStateGraph[RunGraphState, Context, RunGraphState, RunGraphState]:
    """The compiled graph on `saver`; `replace` swaps node functions by name (tests stub nodes to walk the table)."""
    builder: StateGraph[RunGraphState, Context, RunGraphState, RunGraphState] = StateGraph(
        RunGraphState, context_schema=Context
    )
    for name, function in {**NODES, **(replace or {})}.items():
        builder.add_node(name, function)
    builder.add_edge(START, "load_run")
    builder.add_edge("load_run", "route_request")
    builder.add_conditional_edges("route_request", next_route, edge_map())
    for name in RETURNS_TO_ROUTER:
        builder.add_edge(name, "route_request")
    builder.add_edge("execute_approved_proposal", "reconcile_outcome")
    builder.add_edge("reconcile_outcome", END)
    builder.add_conditional_edges("publish_state", after_publish, [END, "route_request"])
    return builder.compile(checkpointer=saver)


def thread_id(run_id: object, revision: int) -> str:
    """One LangGraph thread per run and revision (Plan Q ruling 13): a revision starts a thread of its own (T21)."""
    return f"{run_id}:{revision}"


def config(thread: str, checkpoint_id: str | None) -> RunnableConfig:
    """The graph run's config: the thread, the stored checkpoint when resuming, and `workflow_version` as checkpoint
    metadata (BS:342; LangGraph copies a string metadata value into every checkpoint's metadata)."""
    configurable: dict[str, Any] = {"thread_id": thread}
    if checkpoint_id is not None:
        configurable["checkpoint_id"] = checkpoint_id
    return {
        "configurable": configurable,
        "metadata": {"workflow_version": WORKFLOW_VERSION},
        "recursion_limit": RECURSION_LIMIT,
    }


class CheckpointNotStored(Exception):
    """A checkpoint LangGraph announced was not readable from the saver within CONFIRM_TRIES polls."""


async def confirm(saver: BaseCheckpointSaver[str], thread: str, checkpoint_id: str) -> None:
    """Wait until the saver returns the checkpoint (T20 review note 2: store only ids `aget_tuple` confirms)."""
    wanted: RunnableConfig = {
        "configurable": {"thread_id": thread, "checkpoint_ns": "", "checkpoint_id": checkpoint_id}
    }
    for _ in range(CONFIRM_TRIES):
        if await saver.aget_tuple(wanted) is not None:
            return
        await asyncio.sleep(CONFIRM_SECONDS)
    raise CheckpointNotStored(checkpoint_id)


async def known(saver: BaseCheckpointSaver[str], thread: str, checkpoint_id: str) -> bool:
    """True when the saver holds the stored checkpoint (a resume from an unknown id fails the run, note 2)."""
    wanted: RunnableConfig = {
        "configurable": {"thread_id": thread, "checkpoint_ns": "", "checkpoint_id": checkpoint_id}
    }
    return await saver.aget_tuple(wanted) is not None


async def interrupted(ctx: Context, thread: str, checkpoint_id: str) -> bool:
    """True when the stored checkpoint holds an interrupt (a waiting node to resume with `Command(resume=...)`)."""
    snapshot = await build_graph(ctx.deps.saver).aget_state(config(thread, checkpoint_id))
    return bool(snapshot.interrupts)


async def ended(ctx: Context, thread: str, checkpoint_id: str) -> bool:
    """True when the stored checkpoint is where a graph run ended (no node left to run; a final refusal's execute job
    stores one). Forking it with `None` would run nothing and leave the run where it was, so such a job starts a new
    graph run instead (Plan Q review of T20, I1)."""
    snapshot = await build_graph(ctx.deps.saver).aget_state(config(thread, checkpoint_id))
    return not snapshot.next


async def run_graph(ctx: Context, graph_input: GraphInput, *, checkpoint_id: str | None, revision: int = 1) -> None:
    """One graph run under the job's lease: input for a new graph run, `Command(resume=...)` for a human resume, or
    None with the stored checkpoint for crash recovery, which LangGraph treats as time travel and forks (SA:214)."""
    thread = thread_id(ctx.lease.run_id, revision)
    graph = build_graph(ctx.deps.saver)
    stored = checkpoint_id
    async for announced in graph.astream(
        graph_input,
        config(thread, checkpoint_id),
        context=ctx,
        stream_mode="checkpoints",
        durability="sync",
    ):
        current = str(announced["config"]["configurable"]["checkpoint_id"])
        if current == stored:
            continue  # a resume announces the checkpoint it starts from
        await confirm(ctx.deps.saver, thread, current)
        async with nodes.unit(ctx) as conn:
            await persistence.store_checkpoint_id(conn, ctx.lease.run_id, current)
        stored = current


async def open_saver(pg: Postgres) -> tuple[psycopg.AsyncConnection[DictRow], AsyncPostgresSaver]:
    """The worker's fourth connection, the saver's own (SA:559-562): autocommit and dict rows as the saver expects
    (`AsyncPostgresSaver.from_conn_string`, `checkpoint/postgres/aio.py:81-83`), no prepared statements, and
    `search_path=checkpoints,pg_temp`, because the saver names its tables without a schema."""
    conn = await psycopg.AsyncConnection.connect(
        pg.conninfo(),
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
        options="-c search_path=checkpoints,pg_temp",
    )
    return conn, AsyncPostgresSaver(conn)

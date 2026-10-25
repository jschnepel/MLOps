"""The edges generated from the graph router's table, and the walk of every row to its node (T20; SA:377; R129's
graph half, DoD 4).

Catches: a conditional edge out of `route_request` that no table row can choose, or a row whose route has no edge; a
route without exactly one node, or a graph without SA:207's ten nodes; and a row whose key, run through the compiled
graph with every other node stubbed, reaches another node than its route's.
"""

import asyncio
from typing import Any
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from ops_core import persistence
from ops_core.contracts import ModelDraft
from ops_core.routing import (
    GRAPH_ROUTES,
    DraftKind,
    GraphKey,
    GraphRoute,
    ModelRoute,
    RunManifest,
)
from ops_worker.evidence import Bundle
from ops_worker.graph import build
from ops_worker.graph.state import Context, HeldDraft, initial, key

from tests.plan_h.test_worker_units import Log, make
from tests.plan_q.test_graph_table import WALK


class Reached(Exception):
    """Raised by a stub node: the walk got there."""


def stub(name: str) -> Any:
    async def node(_state: Any, runtime: Any) -> dict[str, Any]:
        raise Reached(name)

    return node


MANIFEST = RunManifest(
    run_id=uuid4(),
    model_route=ModelRoute.FAKE,
    model_digest=None,
    prompt_version="incident-draft-v2",
    corpus_version="handoff-1",
    retrieval_mode="lexical",
)


def held() -> tuple[HeldDraft, Bundle]:
    """What a graph run holds after drafting, so route_request keeps the key's draft kind and evidence verdict."""
    draft = ModelDraft(kind="abstain", title="t", summary="s", evidence_refs=[], assumptions=[], limitations=[])
    return HeldDraft(uuid4(), draft), Bundle("text", [], (), MANIFEST)


def test_the_router_edges_are_the_table_routes_and_nothing_else() -> None:
    compiled = build.build_graph(InMemorySaver())
    (branch,) = compiled.builder.branches["route_request"].values()  # the one conditional edge set out of the router
    table = {rule.route.value: build.ROUTE_NODES[rule.route] for rule in GRAPH_ROUTES}
    assert branch.ends == table == build.edge_map()
    drawn = compiled.get_graph().edges
    assert {edge.target for edge in drawn if edge.source == "route_request"} == set(table.values())
    publish = {edge.target for edge in drawn if edge.source == "publish_state"}
    assert publish == {"__end__", "route_request"}  # after_publish: the table's publish route ends the graph run


def test_every_route_has_one_node_and_some_row() -> None:
    assert set(build.ROUTE_NODES) == set(GraphRoute)  # a dict: one node each
    assert set(build.ROUTE_NODES.values()) <= set(build.NODES) and len(build.NODES) == 10  # SA:207's ten nodes


@pytest.mark.parametrize(("name", "witness"), WALK, ids=[f"{n}-{w.state.value}" for n, w in WALK])
def test_each_row_routes_its_key_to_its_node(name: str, witness: GraphKey, monkeypatch: pytest.MonkeyPatch) -> None:
    rule = next(r for r in GRAPH_ROUTES if r.name == name)
    draft, bundle = held()
    state = {
        **initial(uuid4()),
        "run_state": witness.state.value,
        "intent": witness.intent.value,
        "context_resolved": witness.context_resolved,
        "evidence": witness.evidence.value,
        "draft_kind": witness.draft_kind.value,
        "draft_id": str(draft.draft_id) if witness.draft_kind is not DraftKind.NONE else None,
        "decision_present": witness.decision_present,
        "attempt_state": None if witness.attempt_state is None else witness.attempt_state.value,
    }
    assert key(state) == witness

    async def load_run(_state: Any, runtime: Any) -> dict[str, Any]:
        return state

    async def graph_facts(_conn: Any, _run_id: Any) -> persistence.GraphFacts:  # what route_request rereads
        facts = (witness.state, witness.intent, witness.decision_present, witness.attempt_state, None)
        return persistence.GraphFacts(*facts)

    async def set_tenant(_conn: Any, _tenant: Any) -> None:
        return None

    monkeypatch.setattr(persistence, "graph_facts", graph_facts)
    monkeypatch.setattr(persistence, "set_tenant", set_tenant)

    stubs = {n: stub(n) for n in build.NODES if n not in ("load_run", "route_request")}
    graph = build.build_graph(InMemorySaver(), {**stubs, "load_run": load_run})
    deps, lease = make(Log())
    ctx = Context(deps, {"id": uuid4(), "tenant_id": uuid4()}, lease)
    ctx.held.draft, ctx.held.bundle = draft, bundle
    with pytest.raises(Reached) as reached:
        asyncio.run(graph.ainvoke(initial(uuid4()), {"configurable": {"thread_id": "walk"}}, context=ctx))
    assert str(reached.value) == build.ROUTE_NODES[rule.route]

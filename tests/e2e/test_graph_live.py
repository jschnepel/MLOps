"""The worker graph on LangGraph's Postgres saver against the per-session test database (OPS_LIVE=1; T20; R022, R038,
R042, R091, R108, R114, R122), on the fake route with the scripted MCP caller of `test_worker_live`.

Catches: a checkpoint schema the api or the sweeper can read, or the worker cannot (R122); the revision's version
rows missing (a `setup()` would re-run its DDL); a read that completes after the draft is recorded (R038); a stored
checkpoint id that is not the thread's checkpoint holding the interrupt (R108); a lease, an open worker transaction or
a model permit held while the run waits (R022); proposal, answer, question or alert text inside a checkpoint row, blob
or pending write (R091); a clarification that does not survive a restart, a new graph instance on a new saver
connection resuming from the stored id with the reply's event (R042; a killed process is the limit, Plan Q); and an
answer_only run that freezes a proposal instead of ending ANSWERED with its cited answer (R114); a read that is
still to complete when the model is called (R038); and, on the real saver and wiring, a step whose values are not
yet stored when the next step runs (R108). The R108 stub does not show the async race: whether `durability="sync"`
is what makes it hold is the unit spy's evidence (`plan_q/test_graph_flow`), not this module's.

Writes `reports/graph/t20-graph-live.md` (the node order and end states) when every test of the module passed.
"""

import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
import pytest_asyncio
from ops_api.store import DbUnit
from ops_core import persistence, settings
from ops_core.outcomes import EventType
from ops_core.settings import Role
from ops_worker import handlers
from ops_worker.drafting import FakeDraftGenerator
from ops_worker.graph import build
from ops_worker.graph.state import Context, initial

from tests.e2e.conftest import purge_conversation
from tests.e2e.test_migrations_and_persistence import ALEX, new_run
from tests.e2e.test_worker_live import ALPHA, ScriptedMcp, approve, event_types, own_job, proposal_of
from tests.plan_q.fixtures import ALERTS
from tests.plan_q.test_graph_flow import QUESTION, Scripted

pytestmark = pytest.mark.asyncio
RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
EVIDENCE = Path("reports/graph/t20-graph-live.md")
EXPECTED_LINES = 5
ALERT_TEXT = ALERTS["data"]["alerts"][0]["message"]  # the scripted alert's message
REPLY = "Clarification: asset A17, hours 24"


@pytest.fixture(scope="module")
def lines() -> Iterator[list[str]]:
    out = [f"# T20 graph on the Postgres saver — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}", ""]
    yield out
    if len(out) != 2 + EXPECTED_LINES:  # a failed or partial run leaves the committed file as it was
        return
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


@pytest.fixture
def traces(monkeypatch: pytest.MonkeyPatch) -> list[Context]:
    """Every `Context` the handlers build (a graph run's, and the ones the handlers' own checks build, which have an
    empty node log), in order, so a test can read a graph run's node log."""
    seen: list[Context] = []
    real = handlers.Context

    def recording(*args: Any, **kwargs: Any) -> Context:
        ctx = real(*args, **kwargs)
        seen.append(ctx)
        return ctx

    monkeypatch.setattr(handlers, "Context", recording)
    return seen


Worker = Callable[[Any], Awaitable[handlers.Deps]]


@pytest_asyncio.fixture
async def worker(role_conn: RoleConn) -> AsyncIterator[Worker]:
    """A factory of worker Deps, each on its own `worker` connection and its own saver connection (a fresh process
    as far as the graph can tell); every saver connection is closed at the end."""
    opened: list[psycopg.AsyncConnection[Any]] = []

    async def build_deps(generator: Any) -> handlers.Deps:
        conn, saver = await build.open_saver(settings.app_postgres(Role.WORKER))
        opened.append(conn)
        return handlers.Deps(
            conn=await role_conn(Role.WORKER),
            mcp=ScriptedMcp(await role_conn(Role.MCP_READ), await role_conn(Role.MCP_EXEC)),
            generator=generator,
            urls=settings.urls(),
            worker_name="t",
            workload_azp="ops-worker",
            saver=saver,
        )

    yield build_deps
    for conn in opened:
        await conn.close()


async def stored(app: persistence.Conn, run: UUID) -> str:
    row = await persistence.run_row(app, run)
    assert row["checkpoint_id"] is not None
    return str(row["checkpoint_id"])


async def checkpoint_bytes(app: persistence.Conn, run: UUID) -> bytes:
    """Every checkpoint row, blob and pending write of the run's thread, as one byte string (R091's grep)."""
    thread = build.thread_id(run, 1)
    out = b""
    for query in (
        "SELECT checkpoint::text || metadata::text AS v FROM checkpoints.checkpoints WHERE thread_id = %s",
        "SELECT blob AS v FROM checkpoints.checkpoint_blobs WHERE thread_id = %s AND blob IS NOT NULL",
        "SELECT blob AS v FROM checkpoints.checkpoint_writes WHERE thread_id = %s",
    ):
        cur = await app.execute(query, (thread,))
        for row in await cur.fetchall():
            value = row["v"]
            out += value.encode() if isinstance(value, str) else bytes(value)
    return out


async def forget(app: persistence.Conn, run: UUID) -> None:
    """The run's checkpoints, then the run and its whole conversation: a clarification's reply is a second message of
    the conversation, which `purge_run` (the run's own message only) would leave referencing it."""
    for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
        await app.execute(f"DELETE FROM checkpoints.{table} WHERE thread_id = %s", (build.thread_id(run, 1),))
    cur = await app.execute("SELECT conversation_id FROM app.runs WHERE run_id = %s", (run,))
    row = await cur.fetchone()
    if row is not None:
        await purge_conversation(app, row["conversation_id"])


async def test_r108_each_step_finds_the_previous_checkpoint_stored(lines: list[str]) -> None:
    """Ruling 6, as far as this stub shows it: on the real Postgres saver and wiring, under durability="sync", a stub
    node running step N+1 reads the thread's newest checkpoint and finds step N's values in it (what `load_run`'s
    stub wrote). It passes `durability="sync"` itself, so it does not show that `run_graph` sets it (the unit spy
    does), nor that "async" would fail it: the async write is a background task, so whether this read would see
    step N is a matter of timing, and the race is not shown."""
    conn, saver = await build.open_saver(settings.app_postgres(Role.WORKER))
    thread = f"r108:{uuid4()}"
    seen: dict[str, Any] = {}

    class Reached(Exception):
        """The stub at step N+1 stops the graph run once it has looked."""

    async def load_run(_state: Any, runtime: Any) -> dict[str, Any]:
        return {"intent": "answer_only", "run_state": "DRAFTING"}  # step N's writes

    async def route_request(_state: Any, runtime: Any) -> dict[str, Any]:
        newest = await saver.aget_tuple({"configurable": {"thread_id": thread, "checkpoint_ns": ""}})
        seen["values"] = None if newest is None else dict(newest.checkpoint["channel_values"])
        seen["step"] = None if newest is None else newest.metadata.get("step")
        raise Reached

    try:
        graph = build.build_graph(saver, {"load_run": load_run, "route_request": route_request})
        with pytest.raises(Reached):
            await graph.ainvoke(initial(uuid4()), {"configurable": {"thread_id": thread}}, durability="sync")
        assert seen["values"] is not None and seen["values"]["intent"] == "answer_only"  # step N, already stored
        assert seen["values"]["run_state"] == "DRAFTING"
        assert seen["step"] == 1  # LangGraph numbers `__start__`'s superstep 0, so the first node's is 1 (input: -1)
        lines.append(
            "- R108: step N's values were stored when step N+1 ran, on the Postgres saver under sync durability;"
            " the async race is not shown"
        )
    finally:
        await saver.adelete_thread(thread)
        await conn.close()


async def test_r122_the_checkpoint_schema_is_the_workers_alone(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    for role in (Role.API, Role.SWEEPER, Role.MCP_READ):
        conn = await role_conn(role)
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="permission denied for schema checkpoints"):
            await conn.execute("SELECT 1 FROM checkpoints.checkpoints LIMIT 1")
    worker = await role_conn(Role.WORKER)
    await worker.execute("SELECT 1 FROM checkpoints.checkpoint_writes LIMIT 1")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):  # the library's bookkeeping is the migration's
        await worker.execute("SELECT 1 FROM checkpoints.checkpoint_migrations LIMIT 1")
    cur = await app_conn.execute("SELECT v FROM checkpoints.checkpoint_migrations ORDER BY v")
    assert [r["v"] for r in await cur.fetchall()] == list(range(10))  # the migrator ran setup()'s statements
    cur = await app_conn.execute("SELECT DISTINCT tableowner FROM pg_tables WHERE schemaname = 'checkpoints'")
    assert [r["tableowner"] for r in await cur.fetchall()] == ["migrator"]
    lines.append(
        "- R122: api, sweeper and mcp_read refused at schema `checkpoints`; worker selects from `checkpoint_writes`"
        " but not the bookkeeping table (its writes are shown by the other tests); versions 0-9 recorded"
    )


async def test_a_run_waits_for_its_reviewer_at_the_stored_checkpoint(
    app_conn: persistence.Conn, role_conn: RoleConn, worker: Worker, traces: list[Context], lines: list[str]
) -> None:
    current: list[UUID] = []
    completed_at_call: list[int] = []

    class Counting(FakeDraftGenerator):
        """Counts the run's `tool.completed` events at the moment the model is called (R038)."""

        async def generate(self, request: Any, evidence: Any) -> Any:
            cur = await app_conn.execute(
                "SELECT count(*) AS n FROM app.events WHERE run_id = %s AND type = 'tool.completed'", (current[0],)
            )
            completed_at_call.append((await cur.fetchone())["n"])
            return await super().generate(request, evidence)

    deps = await worker(Counting())
    run = None
    try:
        _, _, run = await new_run(app_conn, ALPHA, api=await role_conn(Role.API))
        current.append(run)
        await handlers.handle(deps, *await own_job(app_conn, deps.conn, run, "investigate"))
        assert (await persistence.run_row(app_conn, run))["state"] == "AWAITING_APPROVAL"
        assert completed_at_call == [3]  # R038: all three reads had completed when the model was called
        cur = await app_conn.execute(
            "SELECT type, sequence FROM app.events WHERE run_id = %s ORDER BY sequence", (run,)
        )
        events = [(r["type"], r["sequence"]) for r in await cur.fetchall()]
        reads = [seq for kind, seq in events if kind == "tool.completed"]
        drafted = next(seq for kind, seq in events if kind == "explanation.ready")  # the drafts row's own unit
        assert len(reads) == 3 and max(reads) < drafted  # R038: every read completed before the draft was recorded
        head = await stored(app_conn, run)
        cur = await app_conn.execute(
            "SELECT checkpoint_id FROM checkpoints.checkpoints WHERE thread_id = %s"
            " ORDER BY checkpoint_id DESC LIMIT 1",
            (build.thread_id(run, 1),),
        )
        assert (await cur.fetchone())["checkpoint_id"] == head  # R108: the stored id is the confirmed head
        cur = await app_conn.execute(
            "SELECT 1 FROM checkpoints.checkpoint_writes WHERE thread_id = %s AND checkpoint_id = %s"
            " AND channel = '__interrupt__'",
            (build.thread_id(run, 1), head),
        )
        assert await cur.fetchone() is not None  # SA:211: it holds the interrupt's pending write
        cur = await app_conn.execute(
            "SELECT lease_until = '-infinity' AS released FROM app.run_lease WHERE run_id = %s", (run,)
        )
        assert (await cur.fetchone())["released"]  # R022: no lease while the run waits
        cur = await app_conn.execute(
            "SELECT count(*) AS n FROM pg_stat_activity WHERE usename = 'worker' AND state LIKE 'idle in transaction%%'"
        )
        assert (await cur.fetchone())["n"] == 0  # R022: no worker transaction left open
        cur = await app_conn.execute("SELECT count(*) AS n FROM app.model_permit WHERE holder IS NOT NULL")
        assert (await cur.fetchone())["n"] == 0  # R022: the permit is free
        proposal = await proposal_of(app_conn, run)
        blobs = await checkpoint_bytes(app_conn, run)
        for text in (proposal["payload"]["title"], proposal["payload"]["summary"][:60], ALERT_TEXT):
            assert text.encode() not in blobs, text  # R091
        await approve(await role_conn(Role.API), proposal)
        restarted = await worker(FakeDraftGenerator())  # a new graph instance on a new saver connection
        await handlers.handle(restarted, *await own_job(app_conn, restarted.conn, run, "execute"))
        assert traces[-1].trace[0] == "await_independent_decision"  # resumed with the decision's event (SA:213)
        called: Any = restarted.mcp
        assert [c[1] for c in called.calls] == ["create_incident"]
        blobs = await checkpoint_bytes(app_conn, run)  # the execute resume wrote checkpoints too (R091)
        for text in (proposal["payload"]["title"], proposal["payload"]["summary"][:60], ALERT_TEXT):
            assert text.encode() not in blobs, text
        lines.append(f"- proposal path: {' → '.join(traces[0].trace)}; ends AWAITING_APPROVAL, lease released")
    finally:
        if run is not None:
            await forget(app_conn, run)


async def test_r042_a_clarification_survives_a_restart(
    app_conn: persistence.Conn, role_conn: RoleConn, worker: Worker, traces: list[Context], lines: list[str]
) -> None:
    api = await role_conn(Role.API)
    deps = await worker(Scripted(QUESTION))
    run = None
    try:
        _, _, run = await new_run(app_conn, ALPHA, api=api)
        await handlers.handle(deps, *await own_job(app_conn, deps.conn, run, "investigate"))
        row = await persistence.run_row(app_conn, run)
        assert row["state"] == "AWAITING_INPUT"
        cur = await app_conn.execute(
            "SELECT event_id, payload FROM app.events WHERE run_id = %s AND type = %s",
            (run, EventType.CLARIFICATION_REQUESTED.value),
        )
        (asked,) = await cur.fetchall()
        assert asked["payload"] == {"message": "Which hours?"}  # the question rides in its event (erratum 124)
        waiting = await stored(app_conn, run)
        assert QUESTION.question is not None and QUESTION.question.encode() not in await checkpoint_bytes(app_conn, run)
        first: Any = deps.saver
        await first.conn.close()  # the first graph process is gone: its saver connection with it
        async with api.transaction():  # the API's reply path (store.record_reply), as the route runs it
            await persistence.set_tenant(api, ALPHA)
            await DbUnit(api, ALPHA).record_reply(
                run_id=run,
                requester=UUID(ALEX),
                question_id=asked["event_id"],
                expected_version=row["state_version"],
                text=REPLY,
                context={"asset_id": "A17", "hours": 24},
            )
        restarted = await worker(FakeDraftGenerator())
        await handlers.handle(restarted, *await own_job(app_conn, restarted.conn, run, "resume_input"))
        assert (await persistence.run_row(app_conn, run))["state"] == "AWAITING_APPROVAL"
        assert traces[-1].trace[:3] == ["await_clarification", "route_request", "retrieve_evidence"]
        cur = await app_conn.execute(
            "SELECT parent_checkpoint_id FROM checkpoints.checkpoints WHERE thread_id = %s AND checkpoint_id > %s"
            " ORDER BY checkpoint_id LIMIT 1",
            (build.thread_id(run, 1), waiting),
        )
        assert (await cur.fetchone())["parent_checkpoint_id"] == waiting  # resumed from the stored id, no fork
        cur = await app_conn.execute(
            "SELECT to_state FROM app.run_state_history WHERE run_id = %s ORDER BY seq", (run,)
        )
        history = [r["to_state"] for r in await cur.fetchall()]
        assert history[3:6] == ["AWAITING_INPUT", "QUEUED", "RETRIEVING"]
        blobs = await checkpoint_bytes(app_conn, run)  # ids only cross the interrupt, so neither text is in the saver
        second = await proposal_of(app_conn, run)
        for text in (REPLY, second["payload"]["title"], second["payload"]["summary"][:60]):
            assert text.encode() not in blobs, text  # R042, R091: the reply and the second draft
        lines.append(f"- clarification across a restart: {' → '.join(history)}")
    finally:
        if run is not None:
            await forget(app_conn, run)


async def test_r114_an_answer_only_run_ends_answered(
    app_conn: persistence.Conn, role_conn: RoleConn, worker: Worker, traces: list[Context], lines: list[str]
) -> None:
    deps = await worker(FakeDraftGenerator())
    run = None
    try:
        _, _, run = await new_run(app_conn, ALPHA, api=await role_conn(Role.API))
        # Staged as the admission router's readonly_answer route would create it (SA:371); intent is create_run's.
        await app_conn.execute("UPDATE app.runs SET intent = 'answer_only' WHERE run_id = %s", (run,))
        await handlers.handle(deps, *await own_job(app_conn, deps.conn, run, "investigate"))
        row = await persistence.run_row(app_conn, run)
        assert row["state"] == "ANSWERED" and row["active_proposal_id"] is None
        types = await event_types(app_conn, run)
        assert types[-2:] == [("explanation.ready", "model_summary"), ("run.answered", "application")]
        cur = await app_conn.execute(
            "SELECT payload FROM app.events WHERE run_id = %s AND type = 'explanation.ready'", (run,)
        )
        answer = (await cur.fetchone())["payload"]
        assert answer["evidence_refs"] == ["ALPHA-INCIDENT:v2:review"] and answer["message"].startswith("For A17")
        cur = await app_conn.execute("SELECT count(*) AS n FROM app.proposals WHERE run_id = %s", (run,))
        assert (await cur.fetchone())["n"] == 0  # R114: no proposal, so no grant can follow
        assert answer["message"][:40].encode() not in await checkpoint_bytes(app_conn, run)
        lines.append(f"- answer_only: {' → '.join(traces[0].trace)}; ends ANSWERED, cited, no proposal")
    finally:
        if run is not None:
            await forget(app_conn, run)

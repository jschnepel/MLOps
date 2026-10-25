"""The worker under its lease without a database (Plan H rulings 3, 5, 18, 19, 28): every unit that writes for a run
opens with `persistence.fenced`, no MCP call starts past the lease's local deadline, the job's final unit releases
the lease with the job, a lost lease hands the job back without a transition, and a busy run's jobs are deferred a
bounded number of times per poll.

Catches: a unit that writes before its fence check (a stale worker's write would land), an MCP call started past the
deadline, a job closed by one unit and its lease released by another (a crash between them strands the run), a lost
lease turned into FAILED by its loser (the next owner decides), a deferral loop that never ends, a hand-back attempted
on a connection left inside a transaction (it would never commit), a handed-back job that closes without work and
leaves its run RETRIEVING or DRAFTING, holding the conversation slot for good (review round 3, I1), a final unit that
closes an execute job under a lapsed lease and strands its approved run (final review, I1), and a readiness probe that
answers 200 while the heartbeat thread is dead (final review, M4).
"""

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from ops_core import persistence, settings
from ops_core.lease import LOCK_FOR_UPDATE, RELEASED, Lease, LeaseLost
from ops_core.outcomes import EventType
from ops_core.states import AttemptState, Intent, RunState
from ops_worker import handlers, main
from ops_worker.drafting import FakeDraftGenerator
from ops_worker.mcp import HttpMcpCaller
from psycopg.pq import TransactionStatus
from starlette.testclient import TestClient

from tests.plan_q.fixtures import ALERTS, STATUS

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
TENANT, RUN_ID = uuid4(), uuid4()
RUN = {
    "run_id": RUN_ID,
    "tenant_id": TENANT,
    "message_id": uuid4(),
    "state": "QUEUED",
    "intent": "investigate",
    "asset_id": "A17",
    "start_at": NOW - timedelta(hours=24),
    "end_at": NOW,
    "supersedes_run_id": None,
    "active_proposal_id": uuid4(),
}
JOB = {"id": uuid4(), "run_id": RUN_ID, "tenant_id": TENANT, "type": "investigate"}
REAL_RELEASE = persistence.release_lease  # `patch` replaces it; the release tests run the real unit on fakes
WRITES = {
    "transition_run",
    "mint_handle",
    "append_event",
    "freeze_proposal",
    "insert",
    "mark_unknown",
    "store_checkpoint_id",
}
SEARCH = {
    "status": "ok",
    "data": {
        "results": [
            {
                "evidence_id": "ALPHA-INCIDENT:v2:review",
                "document_id": "ALPHA-INCIDENT",
                "version": "2",
                "section": "review",
                "content_sha256": "62a90906c7bb706ae8a968eb0f7102f76b05d2c3be911c182d528a1fd25ef008",
                "excerpt": "text",
                "effective_from": "2026-10-01T00:00:00Z",
                "retrieved_at": "2026-10-08T12:00:00Z",
            }
        ],
        "retrieval_mode": "lexical",
        "corpus_version": "handoff-1",
    },
}
SUCCEEDED = {"status": "outcome", "data": {"status": "SUCCEEDED"}, "error": None}  # mcp-write, after the receipt
ANSWERS = {
    "get_asset_status": STATUS,
    "get_recent_alerts": ALERTS,
    "search_procedures": SEARCH,
    "create_incident": SUCCEEDED,
}


class Log:
    """What the fakes did, in order: BEGIN, COMMIT and ROLLBACK for units, and every persistence call by name."""

    def __init__(self) -> None:
        self.entries: list[str] = []

    def units(self) -> list[list[str]]:
        """The calls inside each unit, from its BEGIN to its COMMIT or ROLLBACK."""
        out: list[list[str]] = []
        current: list[str] | None = None
        for entry in self.entries:
            if entry == "BEGIN":
                current = []
            elif entry in ("COMMIT", "ROLLBACK"):
                assert current is not None
                out.append(current)
                current = None
            elif current is not None:
                current.append(entry)
        return out


class FakeCursor:
    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row

    async def fetchone(self) -> dict[str, Any]:
        return self.row


class FakeConn:
    """A connection whose transactions are logged; the handlers' own SQL (the message read, the drafts INSERT) too.
    It reports itself idle between units, as psycopg's `info.transaction_status` does."""

    def __init__(self, log: Log) -> None:
        self.log = log
        self.info = SimpleNamespace(transaction_status=TransactionStatus.IDLE)
        self.closed = False
        self.broken = False

    async def close(self) -> None:
        self.closed = True

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        self.log.entries.append("BEGIN")
        try:
            yield
        except BaseException:
            self.log.entries.append("ROLLBACK")
            raise
        self.log.entries.append("COMMIT")

    async def execute(self, query: str, params: Any = None) -> FakeCursor:
        self.log.entries.append("insert" if query.lstrip().startswith("INSERT") else "select")
        return FakeCursor({"text": "Investigate the alerts on A17 over the last 24 hours."})


class ScriptedMcp:
    def __init__(self, log: Log) -> None:
        self.log = log

    async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.log.entries.append(f"mcp:{tool}")
        return ANSWERS[tool]


def patch(
    monkeypatch: pytest.MonkeyPatch,
    log: Log,
    *,
    lost_at: int | None = None,
    lose_after: str | None = None,
    run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Replace every persistence call the handlers make with a recorder; the `lost_at`-th `fenced` call, or the first
    one made once `lose_after` is in the log, raises LeaseLost, as a moved fence would. The run row is kept like the
    database keeps it (T20: the graph's nodes reread it): a transition, a freeze and a stored checkpoint id change it;
    it is returned so a test can read or set it.
    Its "events" map holds the run's events by type, as `run_events` reads them: a move to AWAITING_INPUT journals its
    clarification.requested (transition_run emits it, SA:451), and a test adds what the API would write. Its
    "messages" map holds the text of each message by id, as `message_text` reads it: the run's own message, and a test
    adds each reply it writes (an id it did not write raises KeyError, so a read through the wrong id fails loudly)."""
    calls = 0
    current: dict[str, Any] = {**(RUN if run is None else run), "events": {}}
    current["messages"] = {current["message_id"]: "Investigate the alerts on A17 over the last 24 hours."}

    async def fenced(_conn: Any, lease: Lease) -> None:
        nonlocal calls
        calls += 1
        log.entries.append("fenced")
        if (lost_at is not None and calls >= lost_at) or (lose_after is not None and lose_after in log.entries):
            lease.mark_lost("the fence moved")
            raise LeaseLost("run lease lost")

    async def run_row(_conn: Any, _run_id: Any, *, lock: bool = False) -> dict[str, Any]:
        log.entries.append("run_row")
        return dict(current)

    async def transition_run(_conn: Any, *, dst: RunState, detail: Any = None, **_: Any) -> int:
        log.entries.append("transition_run")
        current["state"] = dst.value
        if dst is RunState.AWAITING_INPUT:
            asked = current["events"].setdefault(EventType.CLARIFICATION_REQUESTED, [])
            asked.append((uuid4(), dict(detail or {})))
        return 2

    async def run_events(_conn: Any, _run_id: Any, type: EventType) -> list[tuple[Any, dict[str, Any]]]:
        log.entries.append("run_events")
        return list(current["events"].get(type, []))

    async def message_text(_conn: Any, message_id: Any) -> str:
        log.entries.append("message_text")
        return str(current["messages"][message_id])

    async def freeze_proposal(*_: Any, **__: Any) -> None:
        log.entries.append("freeze_proposal")
        current["state"] = RunState.AWAITING_APPROVAL.value

    async def graph_facts(_conn: Any, _run_id: Any) -> persistence.GraphFacts:
        log.entries.append("graph_facts")
        state = RunState(current["state"])
        decided = state in (RunState.APPROVED, RunState.EXECUTING, RunState.OUTCOME_UNKNOWN)
        attempt = AttemptState.SENT if state is RunState.EXECUTING else None
        return persistence.GraphFacts(state, Intent(current["intent"]), decided, attempt, current.get("checkpoint_id"))

    async def insert_run_manifest(_conn: Any, **_: Any) -> None:
        log.entries.append("insert")  # as the real one's INSERT is logged by FakeConn
        current["manifest"] = True

    async def run_manifest_exists(_conn: Any, _run_id: Any) -> bool:
        log.entries.append("run_manifest_exists")
        return bool(current.get("manifest"))

    async def store_checkpoint_id(_conn: Any, _run_id: Any, checkpoint_id: str) -> None:
        log.entries.append("store_checkpoint_id")
        current["checkpoint_id"] = checkpoint_id

    def recorder(name: str, result: Any = None) -> Callable[..., Any]:
        async def call(*_: Any, **__: Any) -> Any:
            log.entries.append(name)
            return result

        return call

    replaced = {
        "fenced": fenced,
        "run_row": run_row,
        "graph_facts": graph_facts,
        "store_checkpoint_id": store_checkpoint_id,
        "insert_run_manifest": insert_run_manifest,
        "run_manifest_exists": run_manifest_exists,
        "run_events": run_events,
        "message_text": message_text,
        "set_tenant": recorder("set_tenant"),
        "transition_run": transition_run,
        "mint_handle": recorder("mint_handle", "handle"),
        "append_event": recorder("append_event"),
        "freeze_proposal": freeze_proposal,
        "release_lease": recorder("release_lease"),
        "revoke_handles": recorder("revoke_handles", 1),
        "unclaim_job": recorder("unclaim_job"),
        "mark_unknown": recorder("mark_unknown", persistence.Unknown(RunState.OUTCOME_UNKNOWN, 4)),
        "take_model_permit": recorder("take_model_permit", 1),
        "release_model_permit": recorder("release_model_permit"),
    }
    for name, fn in replaced.items():
        monkeypatch.setattr(persistence, name, fn)
    return current


def make(log: Log, clock: Callable[[], float] = time.monotonic) -> tuple[handlers.Deps, Lease]:
    conn: Any = FakeConn(log)
    deps = handlers.Deps(
        conn=conn,
        mcp=ScriptedMcp(log),
        generator=FakeDraftGenerator(),
        urls=settings.urls(),
        worker_name="w:test",
        workload_azp="ops-worker",
        saver=InMemorySaver(),
    )
    return deps, Lease(run_id=RUN_ID, owner="w:test", fence=3, lease_seconds=30, started=clock(), clock=clock)


def test_every_unit_that_writes_opens_with_the_fence(monkeypatch: pytest.MonkeyPatch) -> None:
    log = Log()
    patch(monkeypatch, log)
    deps, lease = make(log)
    asyncio.run(handlers.handle(deps, dict(JOB), lease))
    units = log.units()
    # T20: one unit per stored checkpoint (SA:211) besides the start, the three reads' events, DRAFTING, the permit
    # and the freeze; every one of them opens with the fence.
    assert ["set_tenant", "fenced", "store_checkpoint_id"] in units, log.entries
    assert (
        log.entries.index("take_model_permit")
        < log.entries.index("release_model_permit")
        < log.entries.index("freeze_proposal")
    )  # the permit is held around the draft call only (ruling 12)
    for unit in units:
        if WRITES & set(unit):
            assert next(entry for entry in unit if entry != "set_tenant") == "fenced", unit  # set_config is no lock
    assert log.entries[-1] == "release_lease" and log.entries.count("mcp:search_procedures") == 1


def test_the_final_unit_releases_the_lease_with_the_job(monkeypatch: pytest.MonkeyPatch) -> None:
    log = Log()
    patch(monkeypatch, log)
    deps, lease = make(log)
    asyncio.run(handlers.handle(deps, {**JOB, "type": "recover"}, lease))  # not handled before T22
    assert log.entries == ["release_lease"]  # one unit closes the job, revokes and releases (ruling 28)


def test_a_lost_lease_hands_the_job_back_without_a_transition(monkeypatch: pytest.MonkeyPatch) -> None:
    log = Log()
    patch(monkeypatch, log, lose_after="transition_run")  # QUEUED -> RETRIEVING passes; tool.started's fence moved
    deps, lease = make(log)
    claimed: Any = persistence.Claimed(dict(JOB), lease)  # a plain dict stands in for the claimed DictRow
    asyncio.run(main.run_job(deps, claimed))
    assert lease.lost == "the fence moved"
    assert log.units()[-1] == ["set_tenant", "revoke_handles", "unclaim_job"]  # the abandon unit (ruling 19)
    assert log.entries.count("transition_run") == 1  # QUEUED -> RETRIEVING before the loss; never FAILED after it
    assert "release_lease" not in log.entries and not [e for e in log.entries if e.startswith("mcp:")]


def test_a_busy_run_defers_and_the_poll_gives_up_after_the_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    answers: list[persistence.Deferred | None] = [persistence.Deferred(uuid4()), persistence.Deferred(uuid4()), None]
    seen: list[dict[str, Any]] = []

    async def claim_next(_conn: Any, **kwargs: Any) -> persistence.Deferred | None:
        seen.append(kwargs)
        return answers.pop(0)

    monkeypatch.setattr(persistence, "claim_next", claim_next)
    deps, _ = make(Log())
    assert asyncio.run(main.claim(deps, [TENANT])) is None
    assert len(seen) == 3 and seen[0]["lease_seconds"] == 30 and seen[0]["worker_name"] == "w:test"
    calls = 0

    async def always_busy(_conn: Any, **_: Any) -> persistence.Deferred:
        nonlocal calls
        calls += 1
        return persistence.Deferred(uuid4())

    monkeypatch.setattr(persistence, "claim_next", always_busy)
    assert asyncio.run(main.claim(deps, [TENANT])) is None and calls == main.MAX_DEFERRALS


def test_no_call_starts_past_the_local_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    log = Log()
    patch(monkeypatch, log)
    now = [0.0]
    deps, lease = make(log, clock=lambda: now[0])
    minted = persistence.mint_handle

    async def mint_then_stall(*args: Any, **kwargs: Any) -> Any:
        now[0] = 25.0  # the loop stalled: 0 + 30 - 5 is the deadline
        return await minted(*args, **kwargs)

    monkeypatch.setattr(persistence, "mint_handle", mint_then_stall)
    with pytest.raises(LeaseLost):
        asyncio.run(handlers.investigate(deps, dict(JOB), lease))
    assert not [e for e in log.entries if e.startswith("mcp:")]  # SA:195: no call started


def test_abandon_closes_a_loop_connection_left_in_a_transaction() -> None:
    """Review round 1, B1: no unit is ever cancelled, but should the loop connection not be idle when a lease is
    lost, handing the job back on it would nest in that transaction and never commit. `abandon` closes it instead,
    so the poll loop ends and the supervisor restarts the worker."""
    log = Log()
    deps, lease = make(log)
    conn: Any = deps.conn
    conn.info.transaction_status = TransactionStatus.INTRANS
    with pytest.raises(psycopg.OperationalError):
        asyncio.run(handlers.abandon(deps, dict(JOB), lease))
    assert conn.closed and log.entries == []  # nothing ran on it


@pytest.mark.parametrize("state", ["RETRIEVING", "DRAFTING"])
def test_an_interrupted_run_is_failed_not_left_active(monkeypatch: pytest.MonkeyPatch, state: str) -> None:
    """Review round 3, I1: the next owner of a handed-back or reclaimed investigate job fails the run it finds in
    RETRIEVING or DRAFTING (nothing resumes it before T20), in its first fenced unit, and closes the job."""
    log = Log()
    patch(monkeypatch, log)
    moves: list[tuple[str, str, Any]] = []

    async def interrupted_run(_conn: Any, _run_id: Any, *, lock: bool = False) -> dict[str, Any]:
        log.entries.append("run_row")
        return {**RUN, "state": state}

    async def transition_run(_conn: Any, *, run_id: Any, src: Any, dst: Any, detail: Any = None) -> int:
        log.entries.append("transition_run")
        moves.append((src.value, dst.value, detail))
        return 2

    monkeypatch.setattr(persistence, "run_row", interrupted_run)
    monkeypatch.setattr(persistence, "transition_run", transition_run)
    deps, lease = make(log)
    asyncio.run(handlers.handle(deps, dict(JOB), lease))
    assert moves == [(state, "FAILED", {"message": "interrupted; the run was not resumed"})]
    assert log.units()[0] == ["set_tenant", "fenced", "run_row", "transition_run"]
    assert log.entries[-1] == "release_lease" and "mcp:search_procedures" not in log.entries


UNKNOWN_ENVELOPE = {"status": "outcome", "data": {"status": "UNKNOWN"}, "error": None}


class UnknownMcp:
    """mcp-write after SENT with no answer it could trust: the UNKNOWN envelope the worker must record."""

    def __init__(self, log: Log) -> None:
        self.log = log

    async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.log.entries.append(f"mcp:{tool}")
        return UNKNOWN_ENVELOPE


def executing(
    monkeypatch: pytest.MonkeyPatch, log: Log, *, lose_after: str | None = None
) -> tuple[handlers.Deps, Lease]:
    """The fakes for an execute job whose run is EXECUTING and whose write call answers UNKNOWN."""
    patch(monkeypatch, log, lose_after=lose_after, run={**RUN, "state": "EXECUTING"})
    deps, lease = make(log)
    deps.mcp = UnknownMcp(log)
    return deps, lease


def test_mark_unknown_hands_the_new_fence_to_the_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    log = Log()
    deps, lease = executing(monkeypatch, log)
    assert asyncio.run(handlers.execute(deps, {**JOB, "type": "execute"}, lease)) is True
    assert (lease.fence, lease.refencing) == (4, False)  # the bump's fence, handed over (ruling 10)
    assert ["mark_unknown"] in log.units()  # its own unit: no share lock to upgrade (SA:191)


def test_a_stale_fence_at_mark_unknown_is_a_lost_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    for lose_after, raised in (("mcp:create_incident", LeaseLost), (None, persistence.VersionConflict)):
        log = Log()
        deps, lease = executing(monkeypatch, log, lose_after=lose_after)

        async def refused(*_: Any, **__: Any) -> None:
            raise persistence.VersionConflict("version_conflict: stale fence")

        monkeypatch.setattr(persistence, "mark_unknown", refused)
        # Losing after the call, the fresh fence check after the refusal fails: the fence was stale, a lost lease.
        # Without it the fence holds, so the refusal was the run's own state and is raised as it came.
        with pytest.raises(raised):
            asyncio.run(handlers.execute(deps, {**JOB, "type": "execute"}, lease))
        assert (lease.fence, lease.refencing) == (3, False)


def lose(lease: Lease) -> int:
    """What the heartbeat thread does on a loss: record why, then cancel the effects in flight."""
    lease.mark_lost("another owner took the lease")
    return lease.cancel_effects()


def test_a_heartbeat_cancel_hands_the_job_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ruling 19 (as amended in review round 1, B1): the thread marks the lease lost and cancels the MCP call in
    flight; the handler sees LeaseLost and the loop revokes and hands the job back."""
    log = Log()
    patch(monkeypatch, log)
    deps, lease = make(log)

    class Hanging:
        async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
            log.entries.append(f"mcp:{tool}")
            await asyncio.Event().wait()  # an MCP call that never answers
            return {}

    class FakeHeartbeat:
        def __init__(self) -> None:
            self.held: Lease | None = None
            self.dropped = False

        def hold(self, held: Lease) -> None:
            self.held = held

        def drop(self, _lease: Lease) -> None:
            self.dropped = True

    heartbeat = FakeHeartbeat()
    deps.mcp = Hanging()
    deps.heartbeat = heartbeat  # duck-typed stand-ins (the test modules are not type-checked)
    cancelled: list[int] = []

    async def scenario() -> None:
        claimed: Any = persistence.Claimed(dict(JOB), lease)
        job = asyncio.create_task(main.run_job(deps, claimed))
        while not [e for e in log.entries if e.startswith("mcp:")]:  # the first read is in flight
            await asyncio.sleep(0)
        assert heartbeat.held is lease
        cancelled.append(lose(lease))
        await job

    asyncio.run(scenario())
    assert cancelled == [1] and heartbeat.dropped  # exactly the one effect in flight
    assert log.units()[-1] == ["set_tenant", "revoke_handles", "unclaim_job"]
    assert "release_lease" not in log.entries and log.entries.count("transition_run") == 1


def test_a_loss_during_a_unit_never_interrupts_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review round 1, B1: the heartbeat may lose the lease while a database unit runs. Nothing cancels the unit, which
    commits whole; the handler stops at its next check, before the MCP call, and hands the job back."""
    log = Log()
    patch(monkeypatch, log)
    deps, lease = make(log)
    cancelled: list[int] = []

    async def fenced(_conn: Any, held: Lease) -> None:  # the real fenced checks the local state first
        log.entries.append("fenced")
        held.check()

    async def transition_then_lose(*_: Any, **__: Any) -> int:
        log.entries.append("transition_run")
        cancelled.append(lose(lease))  # the thread, mid-unit
        await asyncio.sleep(0.01)  # still inside the unit when a cancellation would land
        return 2

    monkeypatch.setattr(persistence, "fenced", fenced)
    monkeypatch.setattr(persistence, "transition_run", transition_then_lose)
    claimed: Any = persistence.Claimed(dict(JOB), lease)
    asyncio.run(main.run_job(deps, claimed))
    start = log.entries.index("transition_run")
    end = next(i for i in range(start, len(log.entries)) if log.entries[i] in ("COMMIT", "ROLLBACK"))
    assert log.entries[end] == "COMMIT" and "mint_handle" in log.entries[start:end]  # the unit committed whole
    assert cancelled == [0] and not [e for e in log.entries if e.startswith("mcp:")]  # no effect was in flight
    assert log.units()[-1] == ["set_tenant", "revoke_handles", "unclaim_job"]


def test_a_lost_lease_cancels_a_real_mcp_call() -> None:
    """Review round 1, M7: the real client (httpx2 inside the MCP SDK's anyio task groups) against a local server that
    accepts the request and never answers. The loss reaches the caller as LeaseLost, whatever wrapper the client puts
    around the cancellation, long before the client's 60 s read timeout."""
    _, lease = make(Log())

    class Token:
        async def token(self) -> str:
            return "workload-token"

    async def silent(reader: asyncio.StreamReader, _writer: asyncio.StreamWriter) -> None:
        await reader.read(65536)  # the request arrives; no answer ever leaves
        await asyncio.Event().wait()

    async def scenario() -> float:
        server = await asyncio.start_server(silent, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        loop = asyncio.get_running_loop()
        started = loop.time()
        loop.call_later(0.5, lose, lease)
        try:
            with pytest.raises(LeaseLost):
                await lease.effect(
                    HttpMcpCaller(Token()).call(
                        f"http://127.0.0.1:{port}/mcp", handle="h", tool="search_procedures", arguments={}
                    )
                )
        finally:
            server.close()
        return loop.time() - started

    assert asyncio.run(scenario()) < 10


class LeaseRowConn(FakeConn):
    """A FakeConn whose lease row lock answers with this owner and fence, live or lapsed on the database clock."""

    def __init__(self, log: Log, *, live: bool) -> None:
        super().__init__(log)
        self.row = {"owner": "w:test", "fence": 3, "released": False, "live": live}

    async def execute(self, query: str, params: Any = None) -> FakeCursor:
        if query == LOCK_FOR_UPDATE:
            self.log.entries.append("lock_lease")
            return FakeCursor(self.row)
        if query.startswith("UPDATE app.run_lease"):
            self.log.entries.append("release")
            return FakeCursor({})
        return await super().execute(query, params)


def releasing(monkeypatch: pytest.MonkeyPatch, log: Log) -> None:
    """The real `release_lease` with recorders for the calls it makes besides its own SQL."""
    monkeypatch.setattr(persistence, "release_lease", REAL_RELEASE)
    for name in ("set_tenant", "revoke_handles", "finish_job", "requeue_job", "pull_forward"):

        async def call(*_: Any, _name: str = name, **__: Any) -> None:
            log.entries.append(_name)

        monkeypatch.setattr(persistence, name, call)


def test_release_of_a_live_lease_closes_the_job(monkeypatch: pytest.MonkeyPatch) -> None:
    log = Log()
    releasing(monkeypatch, log)
    _, lease = make(log)
    conn: Any = LeaseRowConn(log, live=True)
    asyncio.run(persistence.release_lease(conn, lease, job=dict(JOB)))
    # T14 (Plan I ruling 10): the run's deferred jobs are made due in the same unit, before the lease is released.
    assert log.units() == [["set_tenant", "lock_lease", "revoke_handles", "finish_job", "pull_forward", "release"]]
    assert lease.lost == RELEASED


def test_release_refuses_a_lease_that_lapsed_on_the_database_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Final review, I1: same owner, same fence, but the lease lapsed. The unit writes nothing and rolls back."""
    log = Log()
    releasing(monkeypatch, log)
    _, lease = make(log)
    conn: Any = LeaseRowConn(log, live=False)
    with pytest.raises(LeaseLost):
        asyncio.run(persistence.release_lease(conn, lease, job=dict(JOB), requeue_seconds=30))
    assert log.entries == ["BEGIN", "set_tenant", "lock_lease", "ROLLBACK"]
    assert lease.lost == "another owner holds the lease, or it lapsed"


def test_release_refuses_past_the_local_deadline_before_any_statement(monkeypatch: pytest.MonkeyPatch) -> None:
    log = Log()
    releasing(monkeypatch, log)
    now = [0.0]
    _, lease = make(log, clock=lambda: now[0])
    now[0] = 25.0  # 0 + 30 - 5: the local deadline
    conn: Any = LeaseRowConn(log, live=True)
    with pytest.raises(LeaseLost):
        asyncio.run(persistence.release_lease(conn, lease, job=dict(JOB)))
    assert log.entries == [] and lease.lost == "local deadline passed"


def test_an_invalid_handle_under_a_lapsed_lease_hands_the_job_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """Final review, I1, traced through the loop: the lease lapses on the database clock while `create_incident` is in
    flight and before the heartbeat has noticed; mcp-write refuses the handle before SENT and answers INVALID_HANDLE.
    `execute` takes the envelope as final, the final unit finds the lease not live, and the loop hands the job back.
    The job is never closed, so the run's next owner mints a fresh handle and asks for the grant again."""
    log = Log()
    patch(monkeypatch, log, run={**RUN, "state": "APPROVED"})
    releasing(monkeypatch, log)

    class Refusing:
        async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
            log.entries.append(f"mcp:{tool}")
            return {"status": "error", "data": None, "error": {"code": "INVALID_HANDLE", "message": "invalid handle"}}

    deps, lease = make(log)
    deps.conn = LeaseRowConn(log, live=False)  # the lease lapsed on the database clock
    deps.mcp = Refusing()
    claimed: Any = persistence.Claimed({**JOB, "type": "execute"}, lease)
    asyncio.run(main.run_job(deps, claimed))
    assert log.entries.count("mcp:create_incident") == 1
    assert log.units()[-2:] == [["set_tenant", "lock_lease"], ["set_tenant", "revoke_handles", "unclaim_job"]]
    assert "finish_job" not in log.entries and "requeue_job" not in log.entries
    assert lease.lost == "another owner holds the lease, or it lapsed"


class Probe:
    async def execute(self, _query: str) -> None:
        return None


@pytest.mark.parametrize(
    ("polling", "beating", "status", "reason"),
    [
        (True, True, 200, None),
        (False, True, 503, "poll loop stopped"),
        (True, False, 503, "heartbeat thread stopped"),
    ],
)
def test_readiness_needs_the_poll_loop_and_the_heartbeat_thread(
    polling: bool, beating: bool, status: int, reason: str | None
) -> None:
    """Final review, M4: a worker whose heartbeat thread died would claim jobs it can neither renew nor cancel."""
    probe: Any = Probe()
    with TestClient(main.health_app(probe, lambda: polling, lambda: beating)) as client:
        response = client.get("/health/ready")
    assert response.status_code == status and response.json().get("reason") == reason

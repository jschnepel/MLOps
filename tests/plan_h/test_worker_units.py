"""The worker under its lease without a database (Plan H rulings 3, 5, 18, 19, 28): every unit that writes for a run
opens with `persistence.fenced`, no MCP call starts past the lease's local deadline, the job's final unit releases
the lease with the job, a lost lease hands the job back without a transition, and a busy run's jobs are deferred a
bounded number of times per poll.

Catches: a unit that writes before its fence check (a stale worker's write would land), an MCP call started past the
deadline, a job closed by one unit and its lease released by another (a crash between them strands the run), a lost
lease turned into FAILED by its loser (the next owner decides), a deferral loop that never ends, a hand-back attempted
on a connection left inside a transaction (it would never commit), and a handed-back job that closes without work and
leaves its run RETRIEVING or DRAFTING, holding the conversation slot for good (review round 3, I1).
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
from ops_core import persistence, settings
from ops_core.lease import Lease, LeaseLost
from ops_core.states import RunState
from ops_worker import handlers, main
from ops_worker.drafting import FakeDraftGenerator
from psycopg.pq import TransactionStatus

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
WRITES = {"transition_run", "mint_handle", "append_event", "freeze_proposal", "insert", "mark_unknown"}
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
        return SEARCH


def patch(monkeypatch: pytest.MonkeyPatch, log: Log, *, lost_at: int | None = None) -> None:
    """Replace every persistence call the handlers make with a recorder; the `lost_at`-th `fenced` call raises
    LeaseLost, as a moved fence would."""
    calls = 0

    async def fenced(_conn: Any, lease: Lease) -> None:
        nonlocal calls
        calls += 1
        log.entries.append("fenced")
        if lost_at is not None and calls >= lost_at:
            lease.mark_lost("the fence moved")
            raise LeaseLost("run lease lost")

    async def run_row(_conn: Any, _run_id: Any, *, lock: bool = False) -> dict[str, Any]:
        log.entries.append("run_row")
        return dict(RUN)

    def recorder(name: str, result: Any = None) -> Callable[..., Any]:
        async def call(*_: Any, **__: Any) -> Any:
            log.entries.append(name)
            return result

        return call

    replaced = {
        "fenced": fenced,
        "run_row": run_row,
        "set_tenant": recorder("set_tenant"),
        "transition_run": recorder("transition_run", 2),
        "mint_handle": recorder("mint_handle", "handle"),
        "append_event": recorder("append_event"),
        "freeze_proposal": recorder("freeze_proposal"),
        "release_lease": recorder("release_lease"),
        "revoke_handles": recorder("revoke_handles", 1),
        "unclaim_job": recorder("unclaim_job"),
        "mark_unknown": recorder("mark_unknown", persistence.Unknown(RunState.OUTCOME_UNKNOWN, 4)),
    }
    for name, fn in replaced.items():
        monkeypatch.setattr(persistence, name, fn)


def make(log: Log, clock: Callable[[], float] = time.monotonic) -> tuple[handlers.Deps, Lease]:
    conn: Any = FakeConn(log)
    deps = handlers.Deps(
        conn=conn, mcp=ScriptedMcp(log), generator=FakeDraftGenerator(), urls=settings.urls(), worker_name="w:test"
    )
    return deps, Lease(run_id=RUN_ID, owner="w:test", fence=3, lease_seconds=30, started=clock(), clock=clock)


def test_every_unit_that_writes_opens_with_the_fence(monkeypatch: pytest.MonkeyPatch) -> None:
    log = Log()
    patch(monkeypatch, log)
    deps, lease = make(log)
    asyncio.run(handlers.handle(deps, dict(JOB), lease))
    units = log.units()
    assert len(units) == 5, log.entries  # start, tool.started, tool.completed, DRAFTING, draft and freeze
    for unit in units:
        if WRITES & set(unit):
            assert next(entry for entry in unit if entry != "set_tenant") == "fenced", unit  # set_config is no lock
    assert log.entries[-1] == "release_lease" and log.entries.count("mcp:search_procedures") == 1


def test_the_final_unit_releases_the_lease_with_the_job(monkeypatch: pytest.MonkeyPatch) -> None:
    log = Log()
    patch(monkeypatch, log)
    deps, lease = make(log)
    asyncio.run(handlers.handle(deps, {**JOB, "type": "resume_input"}, lease))  # not handled yet (T20)
    assert log.entries == ["release_lease"]  # one unit closes the job, revokes and releases (ruling 28)


def test_a_lost_lease_hands_the_job_back_without_a_transition(monkeypatch: pytest.MonkeyPatch) -> None:
    log = Log()
    patch(monkeypatch, log, lost_at=2)  # the first unit passes; the tool.started event's fence has moved
    deps, lease = make(log)
    claimed: Any = persistence.Claimed(dict(JOB), lease)  # a plain dict stands in for the claimed DictRow
    asyncio.run(main.run_job(deps, claimed))
    assert lease.lost == "the fence moved"
    assert log.units()[-1] == ["set_tenant", "revoke_handles", "unclaim_job"]  # the abandon unit (ruling 19)
    assert log.entries.count("transition_run") == 1  # QUEUED -> RETRIEVING before the loss; never FAILED after it
    assert "release_lease" not in log.entries and "mcp:search_procedures" not in log.entries


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
    assert "mcp:search_procedures" not in log.entries  # SA:195: the call never started


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


def executing(monkeypatch: pytest.MonkeyPatch, log: Log, *, lost_at: int | None = None) -> tuple[handlers.Deps, Lease]:
    """The fakes for an execute job whose run is EXECUTING and whose write call answers UNKNOWN."""
    patch(monkeypatch, log, lost_at=lost_at)

    async def executing_run(_conn: Any, _run_id: Any, *, lock: bool = False) -> dict[str, Any]:
        log.entries.append("run_row")
        return {**RUN, "state": "EXECUTING"}

    monkeypatch.setattr(persistence, "run_row", executing_run)
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
    for lost_at, raised in ((2, LeaseLost), (None, persistence.VersionConflict)):
        log = Log()
        deps, lease = executing(monkeypatch, log, lost_at=lost_at)

        async def refused(*_: Any, **__: Any) -> None:
            raise persistence.VersionConflict("version_conflict: stale fence")

        monkeypatch.setattr(persistence, "mark_unknown", refused)
        # With lost_at=2 the fresh fence check after the refusal fails: the fence was stale, a lost lease. Without
        # it the fence holds, so the refusal was the run's own state and is raised as it came.
        with pytest.raises(raised):
            asyncio.run(handlers.execute(deps, {**JOB, "type": "execute"}, lease))
        assert (lease.fence, lease.refencing) == (3, False)

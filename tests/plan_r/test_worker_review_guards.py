"""The guards around T21's worker and sweeper that the first round of tests left to a fake (Task 5 review, fix round 1):
the production halves of the revision-race guard, the older-revision checkpoint, the workflow-version pin, the
read-handle and context revision, the current-revision key and the expiry sweep's isolation.

Catches: a `store_checkpoint_id` that writes for a revision the run has left (the old graph run would overwrite the
cleared column), or that counts the revision before it holds the run's lock; a graph run of an old revision that
routes on after the revision moved the run (only `nodes.facts` can end it once the checkpoint is stored); a stored
checkpoint of an older revision's thread that a new revision tries to resume (CHECKPOINT_MISSING) instead of starting
its own thread; a missing checkpoint that is not reported; a workflow version not pinned at the first claim, or a
mismatch not warned about; a read handle minted for an execute resend that reads nothing; a context built without the
run's revision; an investigate wake-up key that selects an older revision's job; and one failing expiry that stops the
sweeper's other runs and the rest of its tick.
"""

import asyncio
import logging
import sqlite3
from typing import Any
from uuid import UUID, uuid4

import pytest
from ops_core import persistence
from ops_core.states import RunState
from ops_sweeper import expiry, leases, sync, wakeups
from ops_sweeper import main as sweeper
from ops_worker import handlers, main
from ops_worker.drafting import WORKFLOW_VERSION
from ops_worker.graph import build, nodes

from tests.plan_h.test_worker_units import JOB, RUN, RUN_ID, make
from tests.plan_q.test_graph_flow import Answering, Scripted, approve, job, lose_once_after, world
from tests.plan_r.test_worker_review import SUCCEEDED, frozen_payloads, revise

REAL_STORE = persistence.store_checkpoint_id  # `patch` replaces it in the graph tests; these run the real unit


class Cursor:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = row

    async def fetchone(self) -> dict[str, Any] | None:
        return self.row


class RevisionConn:
    """A connection answering the three statements of `store_checkpoint_id`: the run's lock, the revision count (the
    run's current revision is `revision`) and the UPDATE, each recorded."""

    def __init__(self, revision: int) -> None:
        self.revision = revision
        self.statements: list[str] = []

    async def execute(self, query: str, params: Any = None) -> Cursor:
        self.statements.append(query)
        if "count(*)" in query:
            return Cursor({"revision": self.revision})
        return Cursor({"?column?": 1} if "FOR UPDATE" in query else None)


def test_the_real_checkpoint_store_writes_for_the_current_revision_after_the_lock() -> None:
    conn: Any = RevisionConn(revision=2)
    asyncio.run(REAL_STORE(conn, RUN_ID, "c1", revision=2))
    kinds = ["lock" if "FOR UPDATE" in s else "count" if "count(*)" in s else "update" for s in conn.statements]
    assert kinds == [
        "lock",
        "count",
        "update",
    ]  # the count is a statement after the lock, so it sees a committed revision


def test_the_real_checkpoint_store_writes_nothing_for_a_revision_the_run_has_left() -> None:
    conn: Any = RevisionConn(revision=3)  # create_revision committed twice since this graph run began
    with pytest.raises(persistence.RevisionMoved):
        asyncio.run(REAL_STORE(conn, RUN_ID, "c1", revision=2))
    assert not [s for s in conn.statements if s.lstrip().startswith("UPDATE")]


def test_a_revision_after_the_freeze_checkpoint_ends_the_graph_run_at_the_next_reread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The revision commits right after the checkpoint that follows the freeze is stored. The store here accepts any
    revision (the definer-side rule is tested above), so only `nodes.facts`, at the next hop's reread, can end the old
    graph run: no transition, no later store, the revised run left QUEUED with its column cleared, the lease released."""
    w = world(monkeypatch)
    stored: list[str] = []

    async def store_any(_conn: Any, _run_id: Any, checkpoint_id: str, *, revision: int) -> None:
        w.log.entries.append("store_checkpoint_id")
        stored.append(checkpoint_id)
        w.run["checkpoint_id"] = checkpoint_id
        if w.run["state"] == "AWAITING_APPROVAL" and w.run.get("revision", 1) == 1:
            revise(w)  # clears the column, as create_revision does
            w.log.entries.append("revised")

    monkeypatch.setattr(persistence, "store_checkpoint_id", store_any)
    job(w, Scripted())
    after = w.log.entries[w.log.entries.index("revised") + 1 :]
    assert "transition_run" not in after and "store_checkpoint_id" not in after
    assert w.run["state"] == "QUEUED" and w.run["checkpoint_id"] is None
    assert after[-1] == "release_lease"


def test_a_checkpoint_stored_by_an_older_revision_starts_the_new_revisions_own_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = world(monkeypatch)
    job(w, Scripted())  # revision 1 freezes and waits; its last stored checkpoint is on thread run_id:1
    old = w.run["checkpoint_id"]
    revise(w)
    w.run["checkpoint_id"] = old  # the old graph run's late store, which the revision's clear did not see
    payloads = frozen_payloads(monkeypatch, w)
    job(w, Scripted(), dedup_key=f"{RUN_ID}:2")
    assert [p["revision"] for p in payloads] == [2] and w.run["state"] == "AWAITING_APPROVAL"
    assert list(w.saver.list(build.config(build.thread_id(RUN_ID, 2), None)))
    assert w.run["checkpoint_id"] != old


def test_an_older_thread_is_told_apart_from_the_current_and_from_none(monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(monkeypatch)
    job(w, Scripted())
    stored = w.run["checkpoint_id"]
    deps, lease = make(w.log)
    deps.saver = w.saver

    def older(checkpoint: str | None, revision: int) -> bool:
        return asyncio.run(handlers._older_thread(deps, lease, checkpoint, revision))

    assert older(stored, 2) is True  # on revision 1's thread, the run is at revision 2: start a new graph run
    assert older(stored, 1) is False  # on the current thread: resume it
    assert older("no-such-checkpoint", 2) is False  # on no thread: the resume check reports it
    assert older(None, 2) is False


def test_a_queued_run_with_an_unknown_checkpoint_at_a_later_revision_fails_as_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = world(monkeypatch, {**RUN, "revision": 2, "checkpoint_id": "no-such-checkpoint"})
    job(w, Scripted(), dedup_key=f"{RUN_ID}:2")
    assert w.run["transitions"][-1] == (RunState.FAILED, {"message": nodes.CHECKPOINT_MISSING})
    assert {c.revision for c in w.contexts} == {2}  # the context `_resumable` builds carries the revision too


def test_the_first_claim_pins_the_workflow_version_and_a_mismatch_is_warned(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    w = world(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="ops_worker"):
        job(w, Scripted())
    assert w.run["workflow_version"] == WORKFLOW_VERSION and "pinned to workflow" not in caplog.text
    pinned = world(monkeypatch, {**RUN, "workflow_version": "workflow-0"})
    with caplog.at_level(logging.WARNING, logger="ops_worker"):
        job(pinned, Scripted())
    assert pinned.run["workflow_version"] == "workflow-0"  # the pin is never moved
    assert f"pinned to workflow workflow-0, this worker runs {WORKFLOW_VERSION}" in caplog.text


def test_an_execute_resend_reads_no_status_and_mints_no_read_handle(monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(monkeypatch)
    job(w, Scripted())
    approve(w)
    w.run["state"] = "EXECUTING"  # the grant was taken; the job was re-queued after a lost reply
    start = len(w.log.entries)
    job(w, Scripted(), "execute", mcp=Answering(w.log, SUCCEEDED))
    after = w.log.entries[start:]
    assert after.count("mint_handle") == 1 and "mcp:get_asset_status" not in after  # the write handle only
    assert "record_asset_observation" not in after and after.count("mcp:create_incident") == 1


def test_every_context_the_handlers_build_carries_the_runs_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(monkeypatch, {**RUN, "revision": 2})
    lose_once_after(monkeypatch, w, "release_model_permit")
    deps, lease = make(w.log)
    deps.saver, deps.generator = w.saver, Scripted()
    asyncio.run(main.run_job(deps, persistence.Claimed({**JOB, "dedup_key": f"{RUN_ID}:2"}, lease)))  # handed back
    assert w.run["state"] == "DRAFTING"
    job(w, Scripted(), dedup_key=f"{RUN_ID}:2")  # resumes from the stored checkpoint (the `ended` check)
    assert w.run["state"] == "AWAITING_APPROVAL"
    approve(w)
    job(w, Scripted(), "execute", mcp=Answering(w.log, SUCCEEDED))  # `_approval` reads the decision
    assert w.contexts and {c.revision for c in w.contexts} == {2}


def test_the_current_revision_key_selects_only_the_current_revisions_job() -> None:
    """The production key expression, cast-stripped for SQLite, evaluated over real rows: the sweep's lateral and its
    re-arm pick the investigate job whose key names the run's current revision, never an older one."""
    assert persistence.REVISION_OF_RUN in wakeups.CURRENT_KEY  # one formula for the revision (Task 5 review, M2)
    assert "jj.dedup_key = " + wakeups.CURRENT_KEY in wakeups.LOST  # the scan and the re-arm both use it
    assert "j.dedup_key = " + wakeups.CURRENT_KEY in wakeups.REARM
    db = sqlite3.connect(":memory:")
    db.execute("ATTACH DATABASE ':memory:' AS app")
    db.execute("CREATE TABLE app.runs (run_id TEXT)")
    db.execute("CREATE TABLE app.events (run_id TEXT, type TEXT)")
    db.execute("CREATE TABLE app.jobs (run_id TEXT, dedup_key TEXT)")
    run, other = str(uuid4()), str(uuid4())
    db.executemany("INSERT INTO app.runs VALUES (?)", [(run,), (other,)])
    db.executemany("INSERT INTO app.jobs VALUES (?, ?)", [(run, f"{run}:{n}") for n in (1, 2, 3)])
    db.execute("INSERT INTO app.events VALUES (?, 'proposal.revised')", (other,))  # another run's revision: not counted
    db.execute("INSERT INTO app.events VALUES (?, 'tool.started')", (run,))  # not a revision
    key = wakeups.CURRENT_KEY.replace("::integer", "").replace("::text", "")

    def current() -> list[str]:
        rows = db.execute(
            f"SELECT jj.dedup_key FROM app.runs r JOIN app.jobs jj ON jj.run_id = r.run_id"
            f" WHERE r.run_id = ? AND jj.dedup_key = {key}",
            (run,),
        )
        return [row[0] for row in rows]

    assert current() == [f"{run}:1"]
    for revision in (2, 3):
        db.execute("INSERT INTO app.events VALUES (?, 'proposal.revised')", (run,))
        assert current() == [f"{run}:{revision}"]  # the older revisions' done jobs are not the wake-up


def _expiry_world(monkeypatch: pytest.MonkeyPatch, failing: UUID, runs: list[UUID]) -> None:
    async def each_tenant(_conn: Any, _work: Any, *, tenants: Any = None) -> dict[Any, list[Any]]:
        return {uuid4(): runs}

    async def in_tenant(conn: Any, _tenant: Any, work: Any) -> Any:
        return await work(conn)

    async def expire_proposal(_conn: Any, run_id: Any) -> RunState:
        if run_id == failing:
            raise RuntimeError("lock timeout")
        return RunState.BLOCKED_REVIEW

    monkeypatch.setattr(expiry, "for_each_tenant", each_tenant)
    monkeypatch.setattr(expiry, "in_tenant", in_tenant)
    monkeypatch.setattr(persistence, "expire_proposal", expire_proposal)


def test_one_failing_expiry_is_logged_and_the_other_runs_still_expire(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    bad, first, last = uuid4(), uuid4(), uuid4()
    _expiry_world(monkeypatch, bad, [first, bad, last])
    none: Any = None
    with caplog.at_level(logging.ERROR, logger="ops_sweeper.expiry"):
        assert asyncio.run(expiry.expire(none)) == [first, last]
    assert str(bad) in caplog.text and "lock timeout" in caplog.text


def test_a_failing_expiry_does_not_stop_the_rest_of_the_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    bad = uuid4()
    _expiry_world(monkeypatch, bad, [bad])
    calls: list[str] = []

    async def run_sync(_deps: Any) -> bool:
        return False

    async def purge(_conn: Any) -> dict[str, int]:
        return {}

    async def reclaim(_conn: Any) -> list[Any]:
        return []

    async def record(_deps: Any, job_type: Any) -> None:
        calls.append(f"record:{job_type.value}")

    async def sweep_wakeups(_deps: Any) -> None:
        calls.append("wakeups")

    async def deliver_outbox(_deps: Any) -> None:
        calls.append("outbox")

    monkeypatch.setattr(sweeper, "run_sync", run_sync)
    monkeypatch.setattr(sync, "purge_expired", purge)
    monkeypatch.setattr(leases, "reclaim", reclaim)
    monkeypatch.setattr(sweeper, "record", record)
    monkeypatch.setattr(sweeper, "sweep_wakeups", sweep_wakeups)
    monkeypatch.setattr(sweeper, "deliver_outbox", deliver_outbox)
    none: Any = None
    deps = sweeper.Deps(conn=none, admin=none, issuer="iss", tick_seconds=30.0, worker_name="sweeper:test")
    asyncio.run(sweeper.tick(deps))
    assert calls == ["record:expire_proposals", "wakeups", "outbox"]

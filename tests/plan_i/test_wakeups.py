"""The wake-up sweep, the purge of finished maintenance rows and the release's pull-forward, without a database
(Plan I rulings 7, 8, 10 and 20).

Catches: a sweep that re-arms a job whose run is still being worked (a job not yet done, or one done inside the
grace), a state no handler serves yet (AWAITING_INPUT is T20's, OUTCOME_UNKNOWN T22's), a re-arm that inserts a new
row instead of reopening the old one (the dedup key is the wake-up's identity, AM-20.4), a re-arm without a bound,
a re-arm of a cancelled run's job, a re-arm that trusts the scan's clock or newest-job choice instead of repeating
them on the row it takes, a purge that could delete a run's job, and a release that leaves the run's deferred jobs
waiting for a lease that is already free, that waits on a row another claim holds, or that cancels a deliberate delay.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest
from ops_core import persistence
from ops_core.settings import WakeupSettings
from ops_sweeper import wakeups

ALPHA = uuid4()
SETTINGS = WakeupSettings()


class FakeCursor:
    def __init__(self, rows: list[dict[str, Any]], rowcount: int) -> None:
        self.rows, self.rowcount = rows, rowcount

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class FakeConn:
    """Records statements per unit; answers the sweep's scan with `lost` and every UPDATE or DELETE with `rowcount`."""

    def __init__(self, lost: list[dict[str, Any]], rowcount: int = 1) -> None:
        self.lost, self.rowcount = lost, rowcount
        self.log: list[tuple[int, str, Any]] = []
        self.unit = 0

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        self.unit += 1
        yield

    async def execute(self, statement: str, params: Any = None) -> FakeCursor:
        self.log.append((self.unit, statement, params))
        if statement.startswith("SELECT"):
            return FakeCursor(self.lost, len(self.lost))
        return FakeCursor([], self.rowcount)


@pytest.fixture(autouse=True)
def tenant_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    async def set_tenant(_conn: Any, _tenant: UUID) -> None:
        return None

    monkeypatch.setattr(persistence, "set_tenant", set_tenant)


def lost(job_type: str, attempts: int) -> dict[str, Any]:
    return {"run_id": uuid4(), "job_id": uuid4(), "job_type": job_type, "state": "QUEUED", "attempts": attempts}


def test_the_sweep_looks_only_where_a_handler_exists() -> None:
    assert wakeups.WAKEUPS == (("QUEUED", "investigate"), ("APPROVED", "execute"))  # ruling 7: T20, T21, T22 add


def test_the_job_type_case_covers_every_wakeup_pair() -> None:
    case = wakeups.job_type_case(wakeups.WAKEUPS)
    # Today's text, unchanged: built from WAKEUPS, it equals what was once written by hand.
    assert case == "CASE r.state WHEN 'QUEUED' THEN 'investigate' WHEN 'APPROVED' THEN 'execute' END"
    assert f"jj.type = {case}" in wakeups.LOST
    # A pair added to WAKEUPS alone reaches the CASE, so the lateral cannot return NULL for its runs.
    extended = (*wakeups.WAKEUPS, ("AWAITING_INPUT", "resume_input"))
    assert "WHEN 'AWAITING_INPUT' THEN 'resume_input'" in wakeups.job_type_case(extended)
    for state, job_type in extended:
        assert f"WHEN '{state}' THEN '{job_type}'" in wakeups.job_type_case(extended)


def test_the_scan_finds_a_runs_newest_job_done_past_the_grace() -> None:
    conn = FakeConn([])
    as_conn: Any = conn
    assert asyncio.run(wakeups.sweep(as_conn, SETTINGS, tenants=[ALPHA])) == []
    ((_, scan, params),) = conn.log
    for condition in (
        "ORDER BY jj.done_at DESC NULLS FIRST",  # an unfinished job comes first, so its run is skipped
        "j.done_at IS NOT NULL",
        "j.done_at <= app.current_time() - make_interval(secs => %s)",
        "(r.state, j.type) IN (('QUEUED', 'investigate'), ('APPROVED', 'execute'))",
        "r.state IN ('QUEUED', 'APPROVED') AND NOT r.cancel_requested",  # waiting, uncancelled runs only
    ):
        assert condition in scan, condition
    assert params == (SETTINGS.grace_seconds,)


def test_a_lost_wakeup_is_reopened_in_a_unit_of_its_own_under_the_cap() -> None:
    found = lost("investigate", 1)
    conn = FakeConn([found])
    as_conn: Any = conn
    (got,) = asyncio.run(wakeups.sweep(as_conn, SETTINGS, tenants=[ALPHA]))
    assert got == wakeups.Wakeup(found["run_id"], found["job_id"], "investigate", 1, rearmed=True)
    (scan_unit, _, _), (rearm_unit, rearm, params) = conn.log
    assert rearm_unit == scan_unit + 1
    assert rearm.startswith("UPDATE app.jobs j SET done_at = NULL, claimed_by = NULL, claimed_at = NULL")
    assert "INSERT" not in rearm and "available_at" not in rearm  # the same row, due already (erratum 62)
    for condition in (  # the scan's conditions again, on the row the UPDATE takes (round 1, I7)
        "j.done_at IS NOT NULL",
        "j.attempts < %s",
        "j.done_at <= app.current_time() - make_interval(secs => %s)",
        "NOT EXISTS (SELECT 1 FROM app.jobs o WHERE o.run_id = j.run_id AND o.type = j.type AND o.id <> j.id",
        "r.state = %s AND NOT r.cancel_requested",
    ):
        assert condition in rearm, condition
    assert params == (found["job_id"], SETTINGS.max_attempts, SETTINGS.grace_seconds, "QUEUED")


def test_a_wakeup_at_its_cap_is_logged_not_reopened(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="ops_sweeper.wakeups")
    found = lost("execute", SETTINGS.max_attempts) | {"state": "APPROVED"}
    conn = FakeConn([found])
    as_conn: Any = conn
    (got,) = asyncio.run(wakeups.sweep(as_conn, SETTINGS, tenants=[ALPHA]))
    assert not got.rearmed and len(conn.log) == 1  # the scan only
    assert str(found["run_id"]) in caplog.text and "not re-armed" in caplog.text


def test_a_job_another_hand_reopened_or_moved_counts_as_not_rearmed() -> None:
    conn = FakeConn([lost("investigate", 2)], rowcount=0)  # the UPDATE's own checks found nothing to do
    as_conn: Any = conn
    (got,) = asyncio.run(wakeups.sweep(as_conn, SETTINGS, tenants=[ALPHA]))
    assert not got.rearmed


def test_the_purge_deletes_finished_maintenance_rows_past_retention_only() -> None:
    conn = FakeConn([], rowcount=3)
    as_conn: Any = conn
    assert asyncio.run(wakeups.purge_maintenance(as_conn, SETTINGS)) == 3
    ((_, purge, params),) = conn.log
    assert purge.startswith("DELETE FROM app.jobs WHERE run_id IS NULL AND done_at IS NOT NULL")
    assert "done_at < app.current_time() - make_interval(hours => %s)" in purge
    assert params == (SETTINGS.maintenance_retention_hours,)


def test_the_pull_forward_takes_only_free_rows_of_the_run() -> None:
    conn = FakeConn([], rowcount=2)
    as_conn: Any = conn
    run_id, job_id = uuid4(), uuid4()
    assert asyncio.run(persistence.pull_forward(as_conn, run_id, except_job=job_id)) == 2
    ((_, pull, params),) = conn.log
    assert pull.startswith("UPDATE app.jobs SET available_at = app.current_time()")
    for condition in (
        "run_id = %s",
        "id <> %s",
        "done_at IS NULL",
        "claimed_at IS NULL",
        "available_at > app.current_time()",
        # Only jobs deferred behind the lease being released: a later, deliberate delay (a re-queue backoff, T22's
        # recover cadence) survives (round 1, M2).
        "available_at <= (SELECT l.lease_until FROM app.run_lease l WHERE l.run_id = %s)",
        "FOR UPDATE SKIP LOCKED",  # a row a claim holds is skipped, never waited on (ruling 22)
    ):
        assert condition in pull, condition
    assert params == (run_id, job_id, run_id)

"""T14 live (OPS_LIVE=1): lost wake-ups re-armed by the sweeper, deferred jobs made due by a release, and the purge of
finished maintenance rows, against the per-session test database (Plan I rulings 7, 8, 10, 20).

A lost wake-up is staged as the superuser (a job marked done while its run still waits): a crash between the job's
consumption and the run's progress cannot be produced on demand, and the one handler path that leaves a run waiting
today, a grant refusal the execute handler takes as final (APPROVED kept), needs mcp-write. The sweep, the re-arm and
the claim that follows run as the real roles. Every run lives on a tenant of its own and the sweep is narrowed to it.

Catches: a wake-up re-armed inside its grace or past its cap, re-armed for a run whose cancellation was requested,
re-armed for a state no handler serves (AWAITING_INPUT waits for T20), re-armed as a new row instead of the same one,
not claimable once re-armed; a deferred job that still waits for a released lease, and a deliberately delayed one
that the release makes due; and a purge that deletes a run's job, an unfinished maintenance row or a recent one.
"""

import logging
from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

import pytest
from ops_core import persistence
from ops_core.jobs import JobType
from ops_core.settings import Role, WakeupSettings
from ops_sweeper import wakeups

from tests.e2e.conftest import purge_run, purge_tenant
from tests.e2e.test_definers_write_path_live import SAM, approve, drafting_run, freeze
from tests.e2e.test_migrations_and_persistence import new_run
from tests.e2e.test_outbox_live import own_tenant

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
CHOSEN = WakeupSettings()  # grace 60 s, cap 10 claims, retention 24 h


async def finish(app_conn: persistence.Conn, job: UUID, *, seconds_ago: int, attempts: int) -> None:
    """Stage a consumed wake-up: the job done `seconds_ago` on the application clock after `attempts` claims."""
    await app_conn.execute(
        "UPDATE app.jobs SET done_at = app.current_time() - make_interval(secs => %s), attempts = %s,"
        " claimed_by = 'w-gone', claimed_at = app.current_time() - make_interval(secs => %s) WHERE id = %s",
        (seconds_ago, attempts, seconds_ago, job),
    )


async def job_of(app_conn: persistence.Conn, run: UUID, job_type: str) -> UUID:
    cur = await app_conn.execute("SELECT id FROM app.jobs WHERE run_id = %s AND type = %s", (run, job_type))
    rows = await cur.fetchall()
    assert len(rows) == 1, rows
    return UUID(str(rows[0]["id"]))


async def test_a_lost_investigate_wakeup_is_rearmed_after_its_grace_and_claimed(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    sweeper, worker = await role_conn(Role.SWEEPER), await role_conn(Role.WORKER)
    tenant, _, run = await new_run(app_conn, api=await role_conn(Role.API))
    try:
        job = await job_of(app_conn, run, "investigate")
        await finish(app_conn, job, seconds_ago=10, attempts=1)  # inside the grace: the worker may be about to move
        assert await wakeups.sweep(sweeper, CHOSEN, tenants=[tenant]) == []
        await finish(app_conn, job, seconds_ago=CHOSEN.grace_seconds + 5, attempts=1)
        (found,) = await wakeups.sweep(sweeper, CHOSEN, tenants=[tenant])
        assert (found.run_id, found.job_id, found.job_type, found.rearmed) == (run, job, "investigate", True)
        cur = await app_conn.execute(
            "SELECT count(*) AS n, bool_and(done_at IS NULL AND claimed_at IS NULL) AS open FROM app.jobs"
            " WHERE run_id = %s",
            (run,),
        )
        assert dict(await cur.fetchone()) == {"n": 1, "open": True}  # the same row, reopened (erratum 62)
        assert await wakeups.sweep(sweeper, CHOSEN, tenants=[tenant]) == []  # pending again: not lost
        claimed = await persistence.claim_next(worker, worker_name="w-next", tenant_ids=[tenant], lease_seconds=30)
        assert isinstance(claimed, persistence.Claimed) and claimed.job["id"] == job and claimed.job["attempts"] == 2
        await persistence.release_lease(worker, claimed.lease, job=dict(claimed.job))
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


async def test_an_approved_runs_execute_wakeup_stops_at_its_cap(
    app_conn: persistence.Conn, role_conn: RoleConn, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="ops_sweeper.wakeups")
    sweeper, api, worker = await role_conn(Role.SWEEPER), await role_conn(Role.API), await role_conn(Role.WORKER)
    tenant = await own_tenant(app_conn)
    run: UUID | None = None
    try:
        run = await drafting_run(app_conn, api, worker, tenant)
        proposal, _, digest = await freeze(app_conn, worker, run, tenant)
        await approve(api, proposal, digest, SAM, tenant)
        job = await job_of(app_conn, run, JobType.EXECUTE.value)
        await app_conn.execute("UPDATE app.runs SET cancel_requested = true WHERE run_id = %s", (run,))
        await finish(app_conn, job, seconds_ago=120, attempts=1)
        assert await wakeups.sweep(sweeper, CHOSEN, tenants=[tenant]) == []  # cancellation requested: never re-armed
        await app_conn.execute("UPDATE app.runs SET cancel_requested = false WHERE run_id = %s", (run,))
        await finish(app_conn, job, seconds_ago=120, attempts=CHOSEN.max_attempts)
        (found,) = await wakeups.sweep(sweeper, CHOSEN, tenants=[tenant])
        assert (found.job_id, found.rearmed) == (job, False) and "not re-armed" in caplog.text
        cur = await app_conn.execute("SELECT done_at IS NOT NULL AS done FROM app.jobs WHERE id = %s", (job,))
        assert (await cur.fetchone())["done"]
        await finish(app_conn, job, seconds_ago=120, attempts=CHOSEN.max_attempts - 1)
        (found,) = await wakeups.sweep(sweeper, CHOSEN, tenants=[tenant])
        assert found.rearmed
    finally:
        if run is not None:
            await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


async def test_a_state_without_a_handler_is_not_swept(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    """Ruling 7: AWAITING_INPUT's reply job is T20's to handle, so its consumption is not a lost wake-up here."""
    sweeper, worker = await role_conn(Role.SWEEPER), await role_conn(Role.WORKER)
    tenant, _, run = await new_run(app_conn, api=await role_conn(Role.API))
    try:
        await worker.execute("SELECT app.transition_run(%s, 'QUEUED', 'RETRIEVING', NULL, 1, '{}')", (run,))
        await worker.execute("SELECT app.transition_run(%s, 'RETRIEVING', 'AWAITING_INPUT', NULL, 2, '{}')", (run,))
        resume = await persistence.insert_job(
            app_conn, job_type=JobType.RESUME_INPUT, run_id=run, clarification_event_id=uuid4()
        )
        assert resume is not None
        await finish(app_conn, resume, seconds_ago=600, attempts=1)
        await finish(app_conn, await job_of(app_conn, run, "investigate"), seconds_ago=600, attempts=1)
        assert await wakeups.sweep(sweeper, CHOSEN, tenants=[tenant]) == []
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


async def test_a_release_makes_the_runs_deferred_job_due_at_once(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """Ruling 10: a job deferred behind a 30 s lease is claimable the moment the holder releases, not 30 s later."""
    a, b = await role_conn(Role.WORKER), await role_conn(Role.WORKER)
    tenant, _, run = await new_run(app_conn, api=await role_conn(Role.API))
    try:
        first = await persistence.claim_next(a, worker_name="wa", tenant_ids=[tenant], lease_seconds=30)
        assert isinstance(first, persistence.Claimed)
        resume = await persistence.insert_job(
            app_conn, job_type=JobType.RESUME_INPUT, run_id=run, clarification_event_id=uuid4()
        )
        assert await persistence.claim_next(b, worker_name="wb", tenant_ids=[tenant], lease_seconds=30) == (
            persistence.Deferred(resume)
        )
        cur = await app_conn.execute(
            "SELECT available_at > app.current_time() + interval '20 seconds' AS behind FROM app.jobs WHERE id = %s",
            (resume,),
        )
        assert (await cur.fetchone())["behind"]  # behind the live lease
        await persistence.release_lease(a, first.lease, job=dict(first.job))
        second = await persistence.claim_next(b, worker_name="wb", tenant_ids=[tenant], lease_seconds=30)
        assert isinstance(second, persistence.Claimed) and second.job["id"] == resume
        assert second.lease.fence == first.lease.fence + 1
        # A job delayed past the lease's end on purpose (a re-queue backoff) is not pulled forward (round 1, M2).
        later = await persistence.insert_job(
            app_conn, job_type=JobType.RESUME_INPUT, run_id=run, clarification_event_id=uuid4()
        )
        await app_conn.execute(
            "UPDATE app.jobs SET available_at = app.current_time() + interval '10 minutes' WHERE id = %s", (later,)
        )
        await persistence.release_lease(b, second.lease, job=dict(second.job))
        cur = await app_conn.execute(
            "SELECT available_at > app.current_time() + interval '9 minutes' AS still FROM app.jobs WHERE id = %s",
            (later,),
        )
        assert (await cur.fetchone())["still"]
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


async def test_the_purge_deletes_old_finished_maintenance_rows_only(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    sweeper = await role_conn(Role.SWEEPER)
    tenant, _, run = await new_run(app_conn, api=await role_conn(Role.API))
    keys = {name: f"sync_memberships:t14-{name}-{uuid4()}" for name in ("old", "recent", "open")}
    try:
        for name, done, created in (
            ("old", "25 hours", "25 hours"),
            ("recent", "1 hour", "1 hour"),
            ("open", None, "30 hours"),
        ):
            await app_conn.execute(
                "INSERT INTO app.jobs (id, type, dedup_key, available_at, created_at, done_at)"
                " VALUES (gen_random_uuid(), 'sync_memberships', %s, app.current_time(),"
                " app.current_time() - %s::interval, app.current_time() - %s::interval)",
                (keys[name], created, done),
            )
        run_job = await job_of(app_conn, run, "investigate")
        await finish(app_conn, run_job, seconds_ago=30 * 3600, attempts=1)  # a run's job: never purged
        assert await wakeups.purge_maintenance(sweeper, CHOSEN) >= 1
        cur = await app_conn.execute("SELECT dedup_key FROM app.jobs WHERE dedup_key = ANY(%s)", (list(keys.values()),))
        assert sorted(row["dedup_key"] for row in await cur.fetchall()) == sorted([keys["recent"], keys["open"]])
        cur = await app_conn.execute("SELECT count(*) AS n FROM app.jobs WHERE id = %s", (run_job,))
        assert (await cur.fetchone())["n"] == 1
    finally:
        await app_conn.execute("DELETE FROM app.jobs WHERE dedup_key = ANY(%s)", (list(keys.values()),))
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)

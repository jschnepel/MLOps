"""T13 live (OPS_LIVE=1): the run lease and its fence as role `worker` against the per-session test database (Plan H
rulings 2, 3, 5, 18, 21, 28; R020, R087, R107; DoD 1).

Two or three `worker` connections are stepped explicitly and `pg_blocking_pids` shows who waits on whom. Every run
lives on a fresh random tenant, so `claim_next` sees this module's jobs only. Writes evidence to
reports/leases/t13-leases.txt (fences, verdicts and counts; no handle, token or seeded tenant id).

Catches: a second owner while the first is live, a fence that does not move on takeover, a stale worker's write that
lands (DoD 1), a takeover that slips in under an open fenced unit, an expiry compared before the lock wait instead of
after it (SA:157), a resume job that writes beside the original job (R087), a handle that outlives its lease or
carries another fence, a release that forgets the handles or resets the fence, a claim that commits without its
lease, and a claim that waits on an in-flight renewal instead of deferring.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from ops_core import persistence
from ops_core.jobs import JobType, Server
from ops_core.lease import LOCK_FOR_UPDATE, RELEASED, Busy, Lease, LeaseLost
from ops_core.outcomes import EventType
from ops_core.settings import Role

from tests.e2e.conftest import backend_pid, expire_lease, lease_for, purge_run, purge_tenant, wait_until_blocked
from tests.e2e.test_migrations_and_persistence import new_run

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
EVIDENCE = Path("reports/leases/t13-leases.txt")
EXPECTED_LINES = 10  # one per test
SHORTEN = "UPDATE app.run_lease SET lease_until = app.current_time() + interval '2 seconds' WHERE run_id = %s"


@pytest.fixture(scope="module")
def lines() -> Iterator[list[str]]:
    out = [f"T13 leases and fences — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"]
    yield out
    if len(out) != 1 + EXPECTED_LINES:  # a failed or partial run leaves the committed file as it was
        return
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


async def fresh_run(app_conn: persistence.Conn, role_conn: RoleConn) -> tuple[UUID, UUID]:
    """A QUEUED run with its investigate job on a new random tenant."""
    tenant, _, run = await new_run(app_conn, api=await role_conn(Role.API))
    return tenant, run


async def forget(app_conn: persistence.Conn, tenant: UUID, run: UUID) -> None:
    await purge_run(app_conn, run)
    await purge_tenant(app_conn, tenant)


async def job_of(app_conn: persistence.Conn, run: UUID) -> UUID:
    cur = await app_conn.execute("SELECT id FROM app.jobs WHERE run_id = %s AND type = 'investigate'", (run,))
    row = await cur.fetchone()
    assert row is not None
    return UUID(str(row["id"]))


async def tool_events(app_conn: persistence.Conn, run: UUID) -> list[str]:
    """The run's tool.started messages in sequence order (each fenced test write names its writer)."""
    cur = await app_conn.execute(
        "SELECT payload->>'message' AS m FROM app.events WHERE run_id = %s AND type = 'tool.started' ORDER BY sequence",
        (run,),
    )
    return [row["m"] for row in await cur.fetchall()]


async def fenced_write(conn: persistence.Conn, lease: Lease, message: str) -> None:
    """One fenced unit writing one event, as a worker's handler does (ruling 5)."""
    async with conn.transaction():
        await persistence.fenced(conn, lease)
        await persistence.append_event(
            conn, run_id=lease.run_id, type=EventType.TOOL_STARTED, payload={"message": message}
        )


async def test_the_first_acquisition_takes_fence_1_and_a_live_lease_defers_the_next_job(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    tenant, run = await fresh_run(app_conn, role_conn)
    a, b = await role_conn(Role.WORKER), await role_conn(Role.WORKER)
    try:
        first = await persistence.claim_next(a, worker_name="wa", tenant_ids=[tenant], lease_seconds=30)
        assert isinstance(first, persistence.Claimed) and first.lease.fence == 1  # erratum 46: created at 0
        assert (first.job["claimed_by"], first.job["type"]) == ("wa", "investigate")
        resume = await persistence.insert_job(
            app_conn, job_type=JobType.RESUME_INPUT, run_id=run, clarification_event_id=uuid4()
        )
        second = await persistence.claim_next(b, worker_name="wb", tenant_ids=[tenant], lease_seconds=30)
        assert second == persistence.Deferred(resume)  # the run's lease decides, whatever the job type (R087)
        cur = await app_conn.execute(
            "SELECT j.claimed_by, j.attempts, j.available_at = l.lease_until AS behind FROM app.jobs j"
            " JOIN app.run_lease l ON l.run_id = j.run_id WHERE j.id = %s",
            (resume,),
        )
        row = await cur.fetchone()
        assert row is not None and (row["claimed_by"], row["attempts"], row["behind"]) == (None, 0, True)
        assert await persistence.claim_next(b, worker_name="wb", tenant_ids=[tenant], lease_seconds=30) is None
        lines.append("acquisition: first fence 1; a second job of the run deferred behind the lease, unclaimed")
    finally:
        await forget(app_conn, tenant, run)


async def test_two_first_acquisitions_of_one_run_give_one_lease(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    tenant, run = await fresh_run(app_conn, role_conn)
    await persistence.insert_job(app_conn, job_type=JobType.RESUME_INPUT, run_id=run, clarification_event_id=uuid4())
    a, b = await role_conn(Role.WORKER), await role_conn(Role.WORKER)
    try:
        a_pid, b_pid = await backend_pid(a), await backend_pid(b)
        # Stepped (review round 1, M5): A's claim stays uncommitted while B claims, so B's first-row INSERT really
        # meets A's and waits for A alone (the one wait left in a claim, Review Focus 1).
        async with a.transaction():
            first = await persistence.claim_next(a, worker_name="wa", tenant_ids=[tenant], lease_seconds=30)
            assert isinstance(first, persistence.Claimed) and first.lease.fence == 1
            second = asyncio.create_task(
                persistence.claim_next(b, worker_name="wb", tenant_ids=[tenant], lease_seconds=30)
            )
            assert a_pid in await wait_until_blocked(app_conn, b_pid)
            assert not second.done()
        got = await asyncio.wait_for(second, timeout=5)  # once A commits, B sees the live lease and defers
        assert isinstance(got, persistence.Deferred), got
        cur = await app_conn.execute("SELECT fence FROM app.run_lease WHERE run_id = %s", (run,))
        assert [row["fence"] for row in await cur.fetchall()] == [1]
        lines.append("two first claims of one run: B's insert waited on A's alone, then deferred; one lease, fence 1")
    finally:
        await forget(app_conn, tenant, run)


async def test_a_locked_lease_is_busy_at_once(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    tenant, run = await fresh_run(app_conn, role_conn)
    a, b = await role_conn(Role.WORKER), await role_conn(Role.WORKER)
    try:
        await lease_for(a, run, owner="wa")
        async with a.transaction():
            # A renewal in flight: the row locked and updated, not committed. An INSERT ... ON CONFLICT on this row
            # would wait for it (ruling 2's refinement), so the acquisition locks first, with NOWAIT.
            await a.execute(LOCK_FOR_UPDATE, (run,))
            await a.execute(
                "UPDATE app.run_lease SET lease_until = app.current_time() + interval '30 seconds' WHERE run_id = %s",
                (run,),
            )
            started = time.monotonic()
            async with b.transaction():
                got = await persistence.acquire_lease(b, run_id=run, owner="wb", lease_seconds=30)
            deferred = await persistence.claim_next(b, worker_name="wb", tenant_ids=[tenant], lease_seconds=30)
            waited = time.monotonic() - started
        assert got == Busy(locked=True) and isinstance(deferred, persistence.Deferred) and waited < 1.0
        cur = await app_conn.execute(
            "SELECT available_at > app.current_time() - interval '1 second'"
            " AND available_at <= app.current_time() + interval '1 second' AS soon FROM app.jobs WHERE id = %s",
            (deferred.job_id,),
        )
        assert (await cur.fetchone())["soon"]  # a locked lease defers by one second, not by a whole lease
        lines.append(f"a claim meeting an in-flight renewal: Busy(locked) in {waited:.2f} s, job deferred one second")
    finally:
        await forget(app_conn, tenant, run)


async def test_r020_a_stale_fence_write_aborts(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    """DoD 1: A acquires, its lease expires on the database clock, B takes the run at the next fence, and A's fenced
    unit and A's mint both refuse without writing."""
    tenant, run = await fresh_run(app_conn, role_conn)
    a, b = await role_conn(Role.WORKER), await role_conn(Role.WORKER)
    try:
        job = await job_of(app_conn, run)
        old = await lease_for(a, run, owner="wa")
        await fenced_write(a, old, "wa before")
        await expire_lease(app_conn, run)  # A stalls past its lease
        new = await lease_for(b, run, owner="wb")
        assert new.fence == old.fence + 1  # the takeover moves the fence
        with pytest.raises(LeaseLost):
            await fenced_write(a, old, "wa after the takeover")
        with pytest.raises(LeaseLost):
            async with a.transaction():
                await persistence.mint_handle(
                    a, run_id=run, job_id=job, server=Server.READ, azp="ops-worker", fence=old.fence
                )
        await fenced_write(b, new, "wb")
        assert await tool_events(app_conn, run) == ["wa before", "wb"]  # the stale units changed nothing
        assert old.lost is not None
        lines.append(f"R020 fence {old.fence} after a takeover at {new.fence}: write and mint refused")
    finally:
        await forget(app_conn, tenant, run)


async def test_r020_an_in_flight_writer_holds_off_the_takeover(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    """DoD 1, in flight: A's open fenced unit holds the share lock, so a takeover waits for it even after A's lease
    has run out on the database clock; once A commits, B gets the next fence and A's next unit fails."""
    tenant, run = await fresh_run(app_conn, role_conn)
    a, b = await role_conn(Role.WORKER), await role_conn(Role.WORKER)
    try:
        old = await lease_for(a, run, owner="wa")
        await app_conn.execute(SHORTEN, (run,))  # the database lease ends in 2 s; A's local deadline is 25 s away
        a_pid, b_pid = await backend_pid(a), await backend_pid(b)
        async with a.transaction():
            await persistence.fenced(a, old)
            await persistence.append_event(
                a, run_id=run, type=EventType.TOOL_STARTED, payload={"message": "wa in flight"}
            )
            await asyncio.sleep(2.5)  # the lease has run out; A still holds the share lock
            takeover = asyncio.create_task(lease_for(b, run, owner="wb", wait=True))
            assert a_pid in await wait_until_blocked(app_conn, b_pid)
            assert not takeover.done()
        new = await asyncio.wait_for(takeover, timeout=5)
        assert new.fence == old.fence + 1
        with pytest.raises(LeaseLost):
            await fenced_write(a, old, "wa next")
        assert await tool_events(app_conn, run) == ["wa in flight"]  # committed under the lock, before the takeover
        lines.append("R020 in flight: the takeover waited on the open fenced unit, then took the next fence")
    finally:
        await forget(app_conn, tenant, run)


async def test_r107_expiry_is_compared_after_the_lock(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    """SA:157: a fenced unit that waits on a renewal-shaped lock while its lease runs out must refuse once the lock is
    released, although the row never changed (no re-check would happen for a WHERE evaluated before the wait)."""
    tenant, run = await fresh_run(app_conn, role_conn)
    a, c = await role_conn(Role.WORKER), await role_conn(Role.WORKER)
    try:
        lease = await lease_for(a, run, owner="wa")
        await app_conn.execute(SHORTEN, (run,))
        a_pid = await backend_pid(a)
        async with c.transaction(force_rollback=True):  # a renewal that fails and rolls back, updating nothing
            await c.execute(LOCK_FOR_UPDATE, (run,))
            check = asyncio.create_task(fenced_write(a, lease, "wa after the wait"))
            await wait_until_blocked(app_conn, a_pid)
            await asyncio.sleep(2.5)  # the lease runs out while A waits
        with pytest.raises(LeaseLost):
            await asyncio.wait_for(check, timeout=5)
        assert await tool_events(app_conn, run) == []
        lines.append("R107 expiry compared after the lock: a lease that lapsed during the wait refused the write")
    finally:
        await forget(app_conn, tenant, run)


async def test_r087_only_the_current_run_fence_writes(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    """R087: an investigate job and a resume_input job of one run share one lease; the resume job waits behind it,
    then takes the next fence, and from then on only it writes, and only it closes its job."""
    tenant, run = await fresh_run(app_conn, role_conn)
    a, b = await role_conn(Role.WORKER), await role_conn(Role.WORKER)
    try:
        original = await persistence.claim_next(a, worker_name="wa", tenant_ids=[tenant], lease_seconds=30)
        assert isinstance(original, persistence.Claimed)
        resume = await persistence.insert_job(
            app_conn, job_type=JobType.RESUME_INPUT, run_id=run, clarification_event_id=uuid4()
        )
        deferred = await persistence.claim_next(b, worker_name="wb", tenant_ids=[tenant], lease_seconds=30)
        assert deferred == persistence.Deferred(resume)
        # The original's worker stalls past its lease; the resume job comes due and takes the run's next fence.
        await expire_lease(app_conn, run)
        await app_conn.execute("UPDATE app.jobs SET available_at = app.current_time() WHERE id = %s", (resume,))
        current = await persistence.claim_next(b, worker_name="wb", tenant_ids=[tenant], lease_seconds=30)
        assert isinstance(current, persistence.Claimed) and current.job["id"] == resume
        assert current.lease.fence == original.lease.fence + 1
        with pytest.raises(LeaseLost):
            await fenced_write(a, original.lease, "investigate job")
        await fenced_write(b, current.lease, "resume job")
        assert await tool_events(app_conn, run) == ["resume job"]
        with pytest.raises(LeaseLost):  # the stale job's final unit closes nothing and releases nothing
            await persistence.release_lease(a, original.lease, job=dict(original.job))
        await persistence.release_lease(b, current.lease, job=dict(current.job))
        cur = await app_conn.execute("SELECT id, done_at IS NOT NULL AS done FROM app.jobs WHERE run_id = %s", (run,))
        assert {row["id"]: row["done"] for row in await cur.fetchall()} == {original.job["id"]: False, resume: True}
        lines.append(
            f"R087 resume vs original: deferred, then fence {current.lease.fence}; only it wrote and closed its job"
        )
    finally:
        await forget(app_conn, tenant, run)


async def test_a_handle_is_capped_at_its_lease_and_bound_to_its_fence(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    tenant, run = await fresh_run(app_conn, role_conn)
    a = await role_conn(Role.WORKER)
    try:
        job = await job_of(app_conn, run)
        lease = await lease_for(a, run, owner="wa", seconds=30)
        async with a.transaction():
            handle = await persistence.mint_handle(
                a, run_id=run, job_id=job, server=Server.READ, azp="ops-worker", fence=lease.fence, ttl_seconds=3600
            )
        cur = await app_conn.execute(
            "SELECT ic.fence, ic.expires_at <= l.lease_until AS capped FROM app.invocation_context ic"
            " JOIN app.run_lease l ON l.run_id = ic.run_id WHERE ic.handle_sha256 = %s",
            (persistence.handle_hash(handle),),
        )
        row = await cur.fetchone()
        assert row is not None and (row["fence"], row["capped"]) == (lease.fence, True)  # BS:558
        with pytest.raises(LeaseLost):
            async with a.transaction():
                await persistence.mint_handle(
                    a, run_id=run, job_id=job, server=Server.READ, azp="ops-worker", fence=lease.fence + 1
                )
        lines.append("a handle asked for 3600 s ends with its 30 s lease, at its fence; another fence mints none")
    finally:
        await forget(app_conn, tenant, run)


async def test_release_closes_the_job_revokes_its_handles_and_keeps_the_fence(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    tenant, run = await fresh_run(app_conn, role_conn)
    a, b = await role_conn(Role.WORKER), await role_conn(Role.WORKER)
    try:
        claimed = await persistence.claim_next(a, worker_name="wa", tenant_ids=[tenant], lease_seconds=30)
        assert isinstance(claimed, persistence.Claimed)
        async with a.transaction():
            await persistence.mint_handle(
                a, run_id=run, job_id=claimed.job["id"], server=Server.READ, azp="ops-worker", fence=claimed.lease.fence
            )
        await persistence.release_lease(a, claimed.lease, job=dict(claimed.job))
        assert claimed.lease.lost == RELEASED
        cur = await app_conn.execute(
            "SELECT j.done_at IS NOT NULL AS done, l.owner, l.fence, l.lease_until = '-infinity' AS released,"
            " ic.revoked_at IS NOT NULL AS revoked FROM app.jobs j JOIN app.run_lease l ON l.run_id = j.run_id"
            " JOIN app.invocation_context ic ON ic.job_id = j.id WHERE j.id = %s",
            (claimed.job["id"],),
        )
        row = await cur.fetchone()
        assert row is not None
        expected = {"done": True, "owner": "wa", "fence": claimed.lease.fence, "released": True, "revoked": True}
        assert dict(row) == expected
        following = await lease_for(b, run, owner="wb")
        assert following.fence == claimed.lease.fence + 1  # the fence persists across the run's jobs (ruling 28)
        with pytest.raises(LeaseLost):
            await persistence.release_lease(a, claimed.lease, job=dict(claimed.job))
        lines.append("release: job done, handles revoked, lease '-infinity' at the same fence; the next job takes +1")
    finally:
        await forget(app_conn, tenant, run)


async def test_claim_and_lease_commit_together(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    tenant, run = await fresh_run(app_conn, role_conn)
    a = await role_conn(Role.WORKER)
    try:
        async with a.transaction(force_rollback=True):  # claim_next's own transaction becomes a savepoint inside
            got = await persistence.claim_next(a, worker_name="wa", tenant_ids=[tenant], lease_seconds=30)
            assert isinstance(got, persistence.Claimed)
        cur = await app_conn.execute(
            "SELECT (SELECT count(*) FROM app.run_lease WHERE run_id = %s) AS leases,"
            " (SELECT count(*) FROM app.jobs WHERE run_id = %s AND claimed_at IS NOT NULL) AS claimed",
            (run, run),
        )
        row = await cur.fetchone()
        assert row is not None and (row["leases"], row["claimed"]) == (0, 0)  # neither survives without the other
        lines.append("claim and lease roll back together: no lease row, no claimed job")
    finally:
        await forget(app_conn, tenant, run)

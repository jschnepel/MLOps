"""The membership sync as role sweeper on ops_test (OPS_LIVE=1): deactivation of a disabled and of a deleted subject,
every row of the issuer stamped, another issuer untouched, the mass-deactivation refusal stamping nothing, and the
maintenance job recorded once per minute. The users mapping is supplied by the test; the admin API is Task 6's."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from ops_core import persistence
from ops_core.jobs import JobType
from ops_core.settings import Role
from ops_sweeper import sync

pytestmark = pytest.mark.asyncio

ISSUER = "http://localhost:18080/realms/ops-dev"
ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")
ALEX = UUID("2fc05986-c7ec-544c-b628-fdb112bbf18a")
SAM = UUID("03f7eb09-e18d-5f33-bf75-12c57d5aaa54")
LEE = UUID("abcc1200-6791-57ab-87b5-9392d356b512")


async def seeded(app_conn: persistence.Conn) -> dict[UUID, bool]:
    cur = await app_conn.execute("SELECT DISTINCT subject FROM app.memberships WHERE issuer = %s", (ISSUER,))
    return {UUID(str(r["subject"])): True for r in await cur.fetchall()}


async def restore(app_conn: persistence.Conn) -> None:
    await app_conn.execute(
        "UPDATE app.memberships SET active = true, permission_version = 1, synced_at = app.current_time()"
    )


async def test_sync_deactivates_disabled_and_deleted_and_stamps_the_issuer(app_conn, role_conn) -> None:
    sweeper = await role_conn(Role.SWEEPER)
    foreign = uuid4()
    await app_conn.execute(
        "INSERT INTO app.memberships (tenant_id, issuer, subject, role)"
        " VALUES (%s, 'http://other/realms/x', %s, 'reader')",
        (ALPHA, foreign),
    )
    await app_conn.execute("UPDATE app.memberships SET synced_at = app.current_time() - interval '1 hour'")
    try:
        cur = await app_conn.execute("SELECT subject, permission_version FROM app.memberships")
        before = {UUID(str(r["subject"])): int(r["permission_version"]) for r in await cur.fetchall()}
        users = await seeded(app_conn)
        users[SAM] = False  # disabled
        del users[LEE]  # deleted
        result = await sync.sync_memberships(sweeper, issuer=ISSUER, users=users)
        assert result.deactivated == 2 and result.checked == 5
        cur = await app_conn.execute(
            "SELECT subject, active, permission_version,"
            " synced_at > app.current_time() - interval '5 seconds' AS fresh FROM app.memberships ORDER BY subject"
        )
        rows = {UUID(str(r["subject"])): r for r in await cur.fetchall()}
        # Increments, not absolute values: an earlier module of the same session may have bumped a row already.
        assert not rows[SAM]["active"] and rows[SAM]["permission_version"] == before[SAM] + 1 and rows[SAM]["fresh"]
        assert not rows[LEE]["active"] and rows[LEE]["permission_version"] == before[LEE] + 1
        assert rows[ALEX]["active"] and rows[ALEX]["permission_version"] == before[ALEX] and rows[ALEX]["fresh"]
        assert rows[foreign]["active"] and not rows[foreign]["fresh"]  # another issuer: not ours to judge
        again = await sync.sync_memberships(sweeper, issuer=ISSUER, users=users)
        assert again.deactivated == 0 and again.checked == 5  # idempotent
    finally:
        await app_conn.execute("DELETE FROM app.memberships WHERE subject = %s", (foreign,))
        await restore(app_conn)


async def test_mass_deactivation_is_refused_and_stamps_nothing(app_conn, role_conn) -> None:
    sweeper = await role_conn(Role.SWEEPER)
    await app_conn.execute("UPDATE app.memberships SET synced_at = app.current_time() - interval '1 hour'")
    try:
        with pytest.raises(sync.MassDeactivation):
            await sync.sync_memberships(sweeper, issuer=ISSUER, users={ALEX: True})  # four of five are missing
        cur = await app_conn.execute(
            "SELECT count(*) AS n FROM app.memberships"
            " WHERE NOT active OR synced_at > app.current_time() - interval '5 seconds'"
        )
        assert (await cur.fetchone())["n"] == 0
    finally:
        await restore(app_conn)


async def test_maintenance_job_is_recorded_once_per_minute(app_conn, role_conn) -> None:
    sweeper = await role_conn(Role.SWEEPER)
    bucket = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M")
    kind = JobType.SYNC_MEMBERSHIPS
    await app_conn.execute("DELETE FROM app.jobs WHERE type = %s", (kind.value,))
    try:
        async with sweeper.transaction():
            first = await persistence.insert_maintenance_job(sweeper, kind, bucket)
            second = await persistence.insert_maintenance_job(sweeper, kind, bucket)
            job = await persistence.claim_maintenance_job(sweeper, job_type=kind, worker_name="t")
            assert first is not None and second is None and job is not None and job["id"] == first
            assert job["tenant_id"] is None and job["run_id"] is None
            await persistence.finish_job(sweeper, job["id"])
            assert await persistence.claim_maintenance_job(sweeper, job_type=kind, worker_name="t") is None
    finally:
        await app_conn.execute("DELETE FROM app.jobs WHERE type = %s", (kind.value,))

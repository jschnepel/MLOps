"""The migrations and the persistence wrappers against the per-session test database (OPS_LIVE=1).

Catches: a migration that is not idempotent, seed rows missing, a transition the table forbids still updating the
run, an event sequence with a gap or a forbidden (type, source) reaching the table, a duplicate job inserted twice,
two workers claiming one job, and a handle resolving at the wrong server or for a tool the job type may not call.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from ops_core import persistence, settings
from ops_core.jobs import JobType, Server, Tool
from ops_core.outcomes import EventRuleViolation, EventSource, EventType
from ops_core.settings import Profile, Role
from ops_core.states import IllegalTransition, Intent, RunState

from tests.e2e.conftest import purge_run, purge_tenant

pytestmark = pytest.mark.asyncio

ALPHA = "3ea79c95-914c-52cb-9d10-c4e19dda8ff7"
ALEX = "2fc05986-c7ec-544c-b628-fdb112bbf18a"
RoleConn = Callable[[Role], Awaitable[persistence.Conn]]


async def new_run(conn: persistence.Conn, tenant_id: UUID | None = None, *, api: persistence.Conn) -> tuple:
    """A QUEUED run in a fresh conversation; on a new random tenant unless a seeded one is given. `conn` is the
    superuser (seeding), `api` the role connection that may call create_run."""
    conv, msg = uuid4(), uuid4()
    tenant = tenant_id or uuid4()
    if tenant_id is None:
        await conn.execute("INSERT INTO app.tenants (tenant_id, name) VALUES (%s, %s)", (tenant, f"t-{tenant}"))
    await conn.execute(
        "INSERT INTO app.conversations (conversation_id, tenant_id, created_by) VALUES (%s, %s, %s)",
        (conv, tenant, ALEX),
    )
    await conn.execute(
        "INSERT INTO app.messages (message_id, tenant_id, conversation_id, kind, text, author)"
        " VALUES (%s, %s, %s, 'investigate', 'x', %s)",
        (msg, tenant, conv, ALEX),
    )
    end = datetime.now(UTC).replace(microsecond=0)
    async with api.transaction():  # the function sets its own tenant
        run, _ = await persistence.create_run(
            api,
            tenant_id=tenant,
            conversation_id=conv,
            message_id=msg,
            requester=UUID(ALEX),
            intent=Intent.INVESTIGATE,
            asset_id="A17",
            start_at=end - timedelta(hours=24),
            end_at=end,
        )
    return tenant, conv, run


async def test_migrate_is_idempotent_and_seeds_are_present(migrated: None, app_conn: persistence.Conn):
    from scripts.skeleton import migrate

    assert migrate(Profile.TEST) == 0  # second run: no-op
    cur = await app_conn.execute("SELECT count(*) AS n FROM app.memberships WHERE tenant_id = %s", (ALPHA,))
    assert (await cur.fetchone())["n"] == 3  # alex, sam, lee
    cur = await app_conn.execute("SELECT role FROM app.memberships WHERE subject = %s", (ALEX,))
    assert [r["role"] for r in await cur.fetchall()] == ["requester"]


async def test_transition_follows_the_table_and_refuses_illegal_moves(app_conn: persistence.Conn, role_conn: RoleConn):
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    tenant, _, run = await new_run(app_conn, api=api)
    try:
        assert await persistence.transition_run(worker, run_id=run, src=RunState.QUEUED, dst=RunState.RETRIEVING) == 2
        with pytest.raises(persistence.Refused) as post_grant:  # the post-grant guard runs before the table
            await persistence.transition_run(worker, run_id=run, src=RunState.RETRIEVING, dst=RunState.APPROVED)
        assert post_grant.value.code == "POST_GRANT_TARGET"
        with pytest.raises(IllegalTransition):  # a pre-grant target with no table row
            await persistence.transition_run(worker, run_id=run, src=RunState.RETRIEVING, dst=RunState.QUEUED)
        with pytest.raises(persistence.VersionConflict):  # the run is RETRIEVING, not QUEUED
            await persistence.transition_run(worker, run_id=run, src=RunState.QUEUED, dst=RunState.RETRIEVING)
        with pytest.raises(persistence.VersionConflict):
            await persistence.transition_run(
                worker, run_id=run, src=RunState.RETRIEVING, dst=RunState.DRAFTING, expected_version=9
            )
        cur = await app_conn.execute("SELECT state, state_version FROM app.runs WHERE run_id = %s", (run,))
        row = await cur.fetchone()
        assert (row["state"], row["state_version"]) == ("RETRIEVING", 2)
        cur = await app_conn.execute(
            "SELECT seq, to_state, performer FROM app.run_state_history WHERE run_id = %s ORDER BY seq", (run,)
        )
        assert [tuple(r.values()) for r in await cur.fetchall()] == [
            (1, "QUEUED", "create_run"),
            (2, "RETRIEVING", "transition_run"),
        ]
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


async def test_events_are_gap_free_and_rule_checked(app_conn: persistence.Conn, role_conn: RoleConn):
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    tenant, _, run = await new_run(app_conn, api=api)  # create_run wrote run.accepted as sequence 1
    try:
        first = await persistence.append_event(
            worker, run_id=run, type=EventType.TOOL_STARTED, payload={"message": "search_procedures"}
        )
        second = await persistence.append_event(
            worker, run_id=run, type=EventType.TOOL_STARTED, payload={"message": "search_procedures"}
        )
        assert (first.sequence, second.sequence) == (2, 3)
        with pytest.raises(EventRuleViolation):  # run.* events belong to the transition functions
            await persistence.append_event(worker, run_id=run, type=EventType.RUN_FAILED, payload={})
        with pytest.raises(EventRuleViolation):  # the model's summary is not an application event
            await persistence.append_event(
                api, run_id=run, type=EventType.TOOL_STARTED, payload={}, source=EventSource.MODEL_SUMMARY
            )
        cur = await app_conn.execute("SELECT count(*) AS n FROM app.events WHERE run_id = %s", (run,))
        assert (await cur.fetchone())["n"] == 3
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


async def test_jobs_dedup_and_single_claim(app_conn: persistence.Conn, role_conn: RoleConn):
    api = await role_conn(Role.API)
    tenant, _, run = await new_run(app_conn, api=api)  # create_run inserted investigate run:1
    first = await persistence.connect(settings.superuser_postgres())
    second = await persistence.connect(settings.superuser_postgres())
    try:
        assert await persistence.insert_job(app_conn, job_type=JobType.INVESTIGATE, run_id=run, revision=1) is None
        proposal = uuid4()
        assert await persistence.insert_job(app_conn, job_type=JobType.EXECUTE, run_id=run, proposal_id=proposal)
        assert (
            await persistence.insert_job(app_conn, job_type=JobType.EXECUTE, run_id=run, proposal_id=proposal) is None
        )
        # Both claims stay open (uncommitted), so SKIP LOCKED must hand the second worker the other job.
        async with first.transaction(force_rollback=True), second.transaction(force_rollback=True):
            one = await persistence.claim_job(first, worker_name="w1", tenant_ids=[tenant])
            two = await persistence.claim_job(second, worker_name="w2", tenant_ids=[tenant])
            assert one is not None and one["claimed_by"] == "w1" and one["attempts"] == 1
            assert two is not None and two["id"] != one["id"] and two["tenant_id"] == tenant
            assert await persistence.claim_job(first, worker_name="w3", tenant_ids=[tenant]) is None  # none left
    finally:
        await first.close()
        await second.close()
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


async def test_handles_bind_to_one_server(app_conn: persistence.Conn, role_conn: RoleConn):
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    mcp_read, mcp_exec = await role_conn(Role.MCP_READ), await role_conn(Role.MCP_EXEC)
    tenant, _, run = await new_run(app_conn, api=api)
    try:
        cur = await app_conn.execute("SELECT id FROM app.jobs WHERE run_id = %s", (run,))
        job = (await cur.fetchone())["id"]
        async with worker.transaction():  # the worker's INSERT grant, under the tenant unit RLS requires
            await persistence.set_tenant(worker, tenant)
            handle = await persistence.mint_handle(worker, run_id=run, job_id=job, server=Server.READ, azp="ops-worker")
        cur = await app_conn.execute("SELECT handle_sha256 FROM app.invocation_context WHERE run_id = %s", (run,))
        assert [r["handle_sha256"] for r in await cur.fetchall()] == [persistence.handle_hash(handle)]  # never raw
        inv = await persistence.resolve_invocation(
            mcp_read, handle=handle, azp="ops-worker", tool=Tool.SEARCH_PROCEDURES
        )
        assert inv.run_id == run and inv.tenant_id == tenant and inv.job_type is JobType.INVESTIGATE
        with pytest.raises(persistence.HandleRejected):  # a read handle at the write server's role
            await persistence.resolve_invocation(mcp_exec, handle=handle, azp="ops-worker", tool=Tool.CREATE_INCIDENT)
        with pytest.raises(persistence.HandleRejected):  # the allowlist: an investigate job may not create incidents
            await persistence.resolve_invocation(mcp_read, handle=handle, azp="ops-worker", tool=Tool.CREATE_INCIDENT)
        with pytest.raises(persistence.HandleRejected):
            await persistence.resolve_invocation(mcp_read, handle="nope", azp="ops-worker", tool=Tool.SEARCH_PROCEDURES)
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


async def test_r006_fresh_database_upgrades_downgrades_and_upgrades_again(migrated: None, app_conn: persistence.Conn):
    """R006: both heads apply to an empty database, 0002 and the testclock branch come off cleanly, and come back."""
    from scripts.skeleton import downgrade, migrate

    superuser = settings.superuser_postgres()
    cur = await app_conn.execute("SELECT version_num FROM public.alembic_version ORDER BY 1")
    versions = {r["version_num"] for r in await cur.fetchall()}
    # With `depends_on` pointing at the main head, Alembic stores one row until a later main revision exists (round 1).
    assert "tc_0001_test_clock" in versions, versions
    downgrade("app", superuser, "testclock@base")
    downgrade("app", superuser, "0001_walking_skeleton")
    for relation in ("app.test_clock", "app.run_directory", "app.transitions"):
        cur = await app_conn.execute("SELECT to_regclass(%s) IS NULL AS gone", (relation,))
        assert (await cur.fetchone())["gone"], relation
    cur = await app_conn.execute("SELECT count(*) AS n FROM pg_policies WHERE schemaname = 'app'")
    assert (await cur.fetchone())["n"] == 0
    assert migrate(Profile.TEST) == 0
    cur = await app_conn.execute("SELECT version_num FROM public.alembic_version ORDER BY 1")
    assert {r["version_num"] for r in await cur.fetchall()} == versions

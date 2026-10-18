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
from ops_core.canonical import canonical_json, canonical_sha256
from ops_core.jobs import JobType, Server, Tool
from ops_core.outcomes import EventRuleViolation, EventSource, EventType
from ops_core.settings import Profile, Role
from ops_core.states import IllegalTransition, Intent, RunState
from psycopg.types.json import Jsonb

from tests.e2e.conftest import purge_run, purge_tenant

pytestmark = pytest.mark.asyncio

ALPHA = "3ea79c95-914c-52cb-9d10-c4e19dda8ff7"
ALEX = "2fc05986-c7ec-544c-b628-fdb112bbf18a"
SAM = "03f7eb09-e18d-5f33-bf75-12c57d5aaa54"  # ALPHA's reviewer
RoleConn = Callable[[Role], Awaitable[persistence.Conn]]


async def new_run(conn: persistence.Conn, tenant_id: UUID | None = None, *, api: persistence.Conn) -> tuple:
    """A QUEUED run in a fresh conversation; on a new random tenant unless a seeded one is given. `conn` is the
    superuser (seeding), `api` the role connection that may call create_run."""
    conv, msg = uuid4(), uuid4()
    tenant = tenant_id or uuid4()
    if tenant_id is None:
        await conn.execute("INSERT INTO app.tenants (tenant_id, name) VALUES (%s, %s)", (tenant, f"t-{tenant}"))
    try:
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
    except BaseException:
        # A failed create_run must not leave the seeded rows behind (the run does not exist, so purge_run cannot).
        await conn.execute("DELETE FROM app.messages WHERE message_id = %s", (msg,))
        await conn.execute("DELETE FROM app.conversations WHERE conversation_id = %s", (conv,))
        if tenant_id is None:
            await purge_tenant(conn, tenant)
        raise
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
    other, _, other_run = await new_run(app_conn, api=api)  # a second tenant with its own investigate job
    try:
        assert await persistence.insert_job(app_conn, job_type=JobType.INVESTIGATE, run_id=run, revision=1) is None
        proposal = uuid4()
        assert await persistence.insert_job(app_conn, job_type=JobType.EXECUTE, run_id=run, proposal_id=proposal)
        assert (
            await persistence.insert_job(app_conn, job_type=JobType.EXECUTE, run_id=run, proposal_id=proposal) is None
        )
        with pytest.raises(persistence.NotFound):  # an unknown run is not "already queued"
            await persistence.insert_job(app_conn, job_type=JobType.INVESTIGATE, run_id=uuid4(), revision=1)
        first, second = await role_conn(Role.WORKER), await role_conn(Role.WORKER)
        # Both claims stay open (uncommitted), so SKIP LOCKED must hand the second worker the other job.
        async with first.transaction(force_rollback=True), second.transaction(force_rollback=True):
            one = await persistence.claim_job(first, worker_name="w1", tenant_ids=[tenant])
            two = await persistence.claim_job(second, worker_name="w2", tenant_ids=[tenant])
            assert one is not None and one["claimed_by"] == "w1" and one["attempts"] == 1
            assert two is not None and two["id"] != one["id"] and two["tenant_id"] == tenant
            assert await persistence.claim_job(first, worker_name="w3", tenant_ids=[tenant]) is None  # none left
            theirs = await persistence.claim_job(first, worker_name="w4", tenant_ids=[other])
            assert theirs is not None and theirs["tenant_id"] == other and theirs["run_id"] == other_run
    finally:
        for r, t in ((run, tenant), (other_run, other)):
            await purge_run(app_conn, r)
            await purge_tenant(app_conn, t)


async def test_handles_bind_to_one_server(app_conn: persistence.Conn, role_conn: RoleConn):
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    mcp_read, mcp_exec = await role_conn(Role.MCP_READ), await role_conn(Role.MCP_EXEC)
    tenant, _, run = await new_run(app_conn, api=api)
    try:
        cur = await app_conn.execute("SELECT id FROM app.jobs WHERE run_id = %s", (run,))
        job = (await cur.fetchone())["id"]
        async with worker.transaction():  # invocation_context has no RLS; the transaction is for set_tenant's own check
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
    """R006: both heads apply to an empty database, the testclock branch, 0005 (back to 0004: the session columns,
    0002's sweeper cell and a `grant_execution` without the stale rule) and 0002 come off cleanly, and come back."""
    from scripts.skeleton import downgrade, migrate

    superuser = settings.superuser_postgres()
    cur = await app_conn.execute("SELECT version_num FROM public.alembic_version ORDER BY 1")
    versions = {r["version_num"] for r in await cur.fetchall()}
    # With `depends_on` pointing at the main head, Alembic stores one row until a later main revision exists (round 1).
    assert "tc_0001_test_clock" in versions, versions
    downgrade("app", superuser, "testclock@base")

    async def session_columns() -> set[str]:
        cur = await app_conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'app' AND table_name = 'sessions'"
        )
        return {str(r["column_name"]) for r in await cur.fetchall()}

    assert {"sid", "username", "refresh_token_enc"} <= await session_columns()
    downgrade("app", superuser, "0004_write_path_functions")
    assert not {"sid", "username", "refresh_token_enc"} & await session_columns()
    cur = await app_conn.execute("SELECT has_table_privilege('sweeper', 'app.sessions', 'SELECT') AS sel")
    assert not (await cur.fetchone())["sel"]  # 0002's DELETE-only cell is back
    cur = await app_conn.execute("SELECT pg_get_functiondef('app.grant_execution(text, uuid)'::regprocedure) AS body")
    assert "MEMBERSHIP_STALE" not in (await cur.fetchone())["body"]
    downgrade("app", superuser, "0001_walking_skeleton")
    for relation in ("app.test_clock", "app.run_directory", "app.transitions", "app.login_state", "app.logout_jti"):
        cur = await app_conn.execute("SELECT to_regclass(%s) IS NULL AS gone", (relation,))
        assert (await cur.fetchone())["gone"], relation
    cur = await app_conn.execute("SELECT count(*) AS n FROM pg_policies WHERE schemaname = 'app'")
    assert (await cur.fetchone())["n"] == 0
    assert migrate(Profile.TEST) == 0
    cur = await app_conn.execute("SELECT version_num FROM public.alembic_version ORDER BY 1")
    assert {r["version_num"] for r in await cur.fetchall()} == versions


async def seed_revision_1_run(conn: persistence.Conn, state: str, history: tuple[str, ...], *, events: tuple[str, ...]):
    """A Plan-D-shaped run on ALPHA written with revision-1 columns only: no tenant_id on the child tables, no
    slot_held or next_event_seq; the history replays `history` with Plan D's `state_version` numbering."""
    conv, msg, run = uuid4(), uuid4(), uuid4()
    await conn.execute(
        "INSERT INTO app.conversations (conversation_id, tenant_id, created_by) VALUES (%s, %s, %s)",
        (conv, ALPHA, ALEX),
    )
    await conn.execute(
        "INSERT INTO app.messages (message_id, tenant_id, conversation_id, kind, text, author)"
        " VALUES (%s, %s, %s, 'investigate', 'x', %s)",
        (msg, ALPHA, conv, ALEX),
    )
    end = datetime.now(UTC).replace(microsecond=0)
    await conn.execute(
        "INSERT INTO app.runs (run_id, tenant_id, conversation_id, message_id, requester, intent, asset_id, start_at,"
        " end_at, state, state_version) VALUES (%s, %s, %s, %s, %s, 'investigate', 'A17', %s, %s, %s, %s)",
        (run, ALPHA, conv, msg, ALEX, end - timedelta(hours=24), end, state, len(history)),
    )
    for seq, (src, dst) in enumerate(zip((None, *history), history, strict=False), start=1):
        await conn.execute(
            "INSERT INTO app.run_state_history (run_id, seq, from_state, to_state, performer)"
            " VALUES (%s, %s, %s, %s, 'plan_d')",
            (run, seq, src, dst),
        )
    for sequence, kind in enumerate(events, start=1):
        source = "destination" if kind == "action.confirmed" else "application"
        await conn.execute(
            "INSERT INTO app.events (event_id, tenant_id, conversation_id, run_id, sequence, type, occurred_at, source,"
            " payload) VALUES (%s, %s, %s, %s, %s, %s, now(), %s, '{}')",
            (uuid4(), ALPHA, conv, run, sequence, kind, source),
        )
    return run


async def seed_revision_1_proposal(conn: persistence.Conn, run: UUID) -> tuple[UUID, str]:
    """A validated draft and a frozen proposal for `run`, set as the run's active proposal (revision-1 columns)."""
    draft, proposal = uuid4(), uuid4()
    payload = {"run_id": str(run), "proposal_id": str(proposal), "action": "create_incident", "asset_id": "A17"}
    canonical, sha = canonical_json(payload), canonical_sha256(payload)
    await conn.execute(
        "INSERT INTO app.drafts (id, run_id, draft_sha256, validated, kind) VALUES (%s, %s, %s, true, 'proposal')",
        (draft, run, sha),
    )
    await conn.execute(
        "INSERT INTO app.proposals (proposal_id, tenant_id, run_id, revision, draft_id, payload, payload_canonical,"
        " payload_sha256, canonicalization_version, authored_by, expires_at)"
        " VALUES (%s, %s, %s, 1, %s, %s, %s, %s, 1, ARRAY[%s]::uuid[], now() + interval '15 minutes')",
        (proposal, ALPHA, run, draft, Jsonb(payload), canonical, sha, ALEX),
    )
    await conn.execute("UPDATE app.runs SET active_proposal_id = %s WHERE run_id = %s", (proposal, run))
    return proposal, sha


# Each child table's rows for the seeded runs, reached the way 0002's backfill must reach them.
CHILD_ROWS = {
    "run_state_history": "run_id = ANY(%s)",
    "jobs": "run_id = ANY(%s)",
    "drafts": "run_id = ANY(%s)",
    "decisions": "proposal_id IN (SELECT proposal_id FROM app.proposals WHERE run_id = ANY(%s))",
    "execution_grant": "run_id = ANY(%s)",
    "action_attempt": "action_id IN (SELECT action_id FROM app.execution_grant WHERE run_id = ANY(%s))",
    "action_attempt_state": "action_id IN (SELECT action_id FROM app.execution_grant WHERE run_id = ANY(%s))",
}


async def test_r006_populated_revision_1_database_upgrades_in_place(
    migrated: None, app_conn: persistence.Conn, role_conn: RoleConn
):
    """R006 old-schema compatibility (final review I3): Plan-D runs at three stages, written at revision 1, come
    through 0002-0004 with every backfill right, and the definer functions accept them afterwards.

    Catches a backfill that reads through the wrong parent, a composite key added before its target, a history
    sequence that collides with `_transition`, a raw handle surviving into the hashed column, and a migrated run the
    functions refuse. The owner's dev database is the first real populated upgrade; this is its rehearsal.
    """
    from scripts.skeleton import downgrade, migrate

    superuser = settings.superuser_postgres()
    downgrade("app", superuser, "testclock@base")
    downgrade("app", superuser, "0001_walking_skeleton")
    runs: list[UUID] = []
    try:
        queued = await seed_revision_1_run(app_conn, "QUEUED", ("QUEUED",), events=("run.accepted",))
        runs.append(queued)
        investigate = uuid4()
        await app_conn.execute(
            "INSERT INTO app.jobs (id, type, run_id, dedup_key) VALUES (%s, 'investigate', %s, %s)",
            (investigate, queued, f"{queued}:1"),
        )
        await app_conn.execute(  # Plan D stored the raw handle; 0002 truncates the table before hashing the column
            "INSERT INTO app.invocation_context (handle, run_id, job_id, server, azp, expires_at)"
            " VALUES ('plan-d-raw-handle', %s, %s, 'read', 'ops-worker', now() + interval '60 seconds')",
            (queued, investigate),
        )
        awaiting = await seed_revision_1_run(
            app_conn,
            "AWAITING_APPROVAL",
            ("QUEUED", "RETRIEVING", "DRAFTING", "AWAITING_APPROVAL"),
            events=("run.accepted", "proposal.ready"),
        )
        runs.append(awaiting)
        await seed_revision_1_proposal(app_conn, awaiting)
        succeeded = await seed_revision_1_run(
            app_conn,
            "SUCCEEDED",
            ("QUEUED", "RETRIEVING", "DRAFTING", "AWAITING_APPROVAL", "APPROVED", "EXECUTING", "SUCCEEDED"),
            events=(
                "run.accepted",
                "proposal.ready",
                "approval.recorded",
                "action.granted",
                "action.dispatched",
                "action.confirmed",
            ),
        )
        runs.append(succeeded)
        proposal, sha = await seed_revision_1_proposal(app_conn, succeeded)
        await app_conn.execute(
            "INSERT INTO app.decisions (decision_id, proposal_id, reviewer, decision, expected_payload_sha256)"
            " VALUES (%s, %s, %s, 'approve', %s)",
            (uuid4(), proposal, SAM, sha),
        )
        execute_job, action = uuid4(), uuid4()
        await app_conn.execute(
            "INSERT INTO app.jobs (id, type, run_id, dedup_key, done_at) VALUES (%s, 'execute', %s, %s, now())",
            (execute_job, succeeded, str(proposal)),
        )
        await app_conn.execute(
            "INSERT INTO app.execution_grant (action_id, run_id, proposal_id, payload_sha256) VALUES (%s, %s, %s, %s)",
            (action, succeeded, proposal, sha),
        )
        await app_conn.execute("INSERT INTO app.action_attempt (action_id, attempt_no) VALUES (%s, 1)", (action,))
        outcome = Jsonb({"status": "SUCCEEDED", "action_id": str(action), "payload_sha256": sha})
        for seq, attempt_state in enumerate(("INTENT", "SENT", "RESOLVED"), start=1):
            resolved = attempt_state == "RESOLVED"
            await app_conn.execute(
                "INSERT INTO app.action_attempt_state (action_id, attempt_no, seq, state, outcome, detail)"
                " VALUES (%s, 1, %s, %s, %s, %s)",
                (action, seq, attempt_state, "SUCCEEDED" if resolved else None, outcome if resolved else None),
            )

        assert migrate(Profile.TEST) == 0

        for table, where in CHILD_ROWS.items():
            cur = await app_conn.execute(
                f"SELECT count(*) AS n, count(*) FILTER (WHERE tenant_id = %s) AS alpha FROM app.{table} WHERE {where}",
                (ALPHA, runs),
            )
            row = await cur.fetchone()
            assert row["n"] > 0 and row["alpha"] == row["n"], (table, row)
        cur = await app_conn.execute(
            "SELECT r.run_id, r.slot_held, r.next_event_seq, d.tenant_id AS directory,"
            " (SELECT max(e.sequence) FROM app.events e WHERE e.run_id = r.run_id) AS last"
            " FROM app.runs r LEFT JOIN app.run_directory d USING (run_id) WHERE r.run_id = ANY(%s)",
            (runs,),
        )
        rows = {r["run_id"]: r for r in await cur.fetchall()}
        assert {run: rows[run]["slot_held"] for run in runs} == {queued: True, awaiting: True, succeeded: False}
        assert [rows[run]["next_event_seq"] for run in runs] == [rows[run]["last"] for run in runs] == [1, 2, 6]
        assert [str(rows[run]["directory"]) for run in runs] == [ALPHA] * 3
        cur = await app_conn.execute("SELECT count(*) AS n FROM app.invocation_context")
        assert (await cur.fetchone())["n"] == 0  # truncated: no raw handle survives into the hashed column

        api, worker, mcp_exec = [await role_conn(r) for r in (Role.API, Role.WORKER, Role.MCP_EXEC)]
        version = await persistence.transition_run(worker, run_id=queued, src=RunState.QUEUED, dst=RunState.RETRIEVING)
        assert version == 2  # Plan D's history ended at seq 1, so _transition's seq 2 does not collide
        appended = await persistence.append_event(
            api, run_id=awaiting, type=EventType.TOOL_STARTED, payload={"message": "after the upgrade"}
        )
        assert appended.sequence == 3  # next_event_seq was backfilled from the two Plan-D events
        async with worker.transaction():
            await persistence.set_tenant(worker, UUID(ALPHA))
            handle = await persistence.mint_handle(
                worker, run_id=succeeded, job_id=execute_job, server=Server.WRITE, azp="ops-worker"
            )
        grant = await persistence.lookup_action(mcp_exec, handle=handle)
        assert grant.action_id == action and grant.attempt_state == "RESOLVED"
    finally:
        # A failure between the downgrade and the migrate would leave ops_test at revision 1 for the rest of the
        # session; bringing it back to heads first is a no-op when the test passed.
        try:
            migrate(Profile.TEST)
        finally:
            for run in runs:
                await purge_run(app_conn, run)

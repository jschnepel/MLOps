"""Revision 1 and the persistence adapter against the real dev database (OPS_LIVE=1).

Catches: a migration that is not idempotent, seed rows missing, a transition the table forbids still updating the
run, an event sequence with a gap or a forbidden (type, source) reaching the table, a duplicate job inserted twice,
two workers claiming one job, and a handle resolving at the wrong server.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from ops_core import persistence
from ops_core.jobs import JobType, Server, Tool
from ops_core.outcomes import EventRuleViolation, EventSource, EventType
from ops_core.states import IllegalTransition, Intent, Performer, RunState

pytestmark = pytest.mark.asyncio

ALPHA = "3ea79c95-914c-52cb-9d10-c4e19dda8ff7"
ALEX = "2fc05986-c7ec-544c-b628-fdb112bbf18a"


async def new_run(conn: persistence.Conn, tenant_id: UUID | None = None) -> tuple:
    """A QUEUED run in a fresh conversation; on a new random tenant unless a seeded one is given (mcp-read's corpus
    exists only for the seeded tenants)."""
    conv, msg, run = uuid4(), uuid4(), uuid4()
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
    await persistence.create_run(
        conn,
        run_id=run,
        tenant_id=tenant,
        conversation_id=conv,
        message_id=msg,
        requester=ALEX,
        intent=Intent.INVESTIGATE,
        asset_id="A17",
        start_at=end - timedelta(hours=24),
        end_at=end,
    )
    return tenant, conv, run


async def test_migrate_is_idempotent_and_seeds_are_present(migrated: None, app_conn: persistence.Conn):
    from scripts.skeleton import migrate

    assert migrate() == 0  # second run: no-op
    cur = await app_conn.execute("SELECT count(*) AS n FROM app.memberships WHERE tenant_id = %s", (ALPHA,))
    assert (await cur.fetchone())["n"] == 3  # alex, sam, lee
    cur = await app_conn.execute("SELECT role FROM app.memberships WHERE subject = %s", (ALEX,))
    assert [r["role"] for r in await cur.fetchall()] == ["requester"]


async def test_transition_follows_the_table_and_rolls_back_illegal_moves(app_conn: persistence.Conn):
    async with app_conn.transaction(force_rollback=True):  # nothing this test writes survives it
        _, _, run = await new_run(app_conn)
        assert (
            await persistence.transition(
                app_conn, run_id=run, dst=RunState.RETRIEVING, performer=Performer.TRANSITION_RUN
            )
            == 2
        )
        with pytest.raises(IllegalTransition):  # RETRIEVING → APPROVED is not a row
            await persistence.transition(
                app_conn, run_id=run, dst=RunState.APPROVED, performer=Performer.RECORD_DECISION
            )
        with pytest.raises(IllegalTransition):  # right pair, wrong performer
            await persistence.transition(app_conn, run_id=run, dst=RunState.DRAFTING, performer=Performer.CREATE_RUN)
        with pytest.raises(persistence.VersionConflict):
            await persistence.transition(
                app_conn, run_id=run, dst=RunState.DRAFTING, performer=Performer.TRANSITION_RUN, expected_version=1
            )
        row = await persistence.run_row(app_conn, run)
        assert (row["state"], row["state_version"]) == ("RETRIEVING", 2)
        cur = await app_conn.execute(
            "SELECT seq, to_state, performer FROM app.run_state_history WHERE run_id = %s ORDER BY seq", (run,)
        )
        assert [tuple(r.values()) for r in await cur.fetchall()] == [
            (1, "QUEUED", "create_run"),
            (2, "RETRIEVING", "transition_run"),
        ]


async def test_events_are_gap_free_and_rule_checked(app_conn: persistence.Conn):
    async with app_conn.transaction(force_rollback=True):
        tenant, conv, run = await new_run(app_conn)
        first = await persistence.append_event(
            app_conn,
            tenant_id=tenant,
            conversation_id=conv,
            run_id=run,
            type=EventType.RUN_ACCEPTED,
            source=EventSource.APPLICATION,
            payload={},
        )
        second = await persistence.append_event(
            app_conn,
            tenant_id=tenant,
            conversation_id=conv,
            run_id=run,
            type=EventType.TOOL_STARTED,
            source=EventSource.APPLICATION,
            payload={"message": "search_procedures"},
        )
        assert (first.sequence, second.sequence) == (1, 2)
        with pytest.raises(EventRuleViolation):  # the application may not assert a destination outcome
            await persistence.append_event(
                app_conn,
                tenant_id=tenant,
                conversation_id=conv,
                run_id=run,
                type=EventType.ACTION_CONFIRMED,
                source=EventSource.APPLICATION,
                payload={"status": "SUCCEEDED"},
            )
        cur = await app_conn.execute("SELECT count(*) AS n FROM app.events WHERE run_id = %s", (run,))
        assert (await cur.fetchone())["n"] == 2


async def test_jobs_dedup_and_single_claim(app_conn: persistence.Conn):
    async with app_conn.transaction(force_rollback=True):
        _, _, run = await new_run(app_conn)  # create_run inserted investigate run:1
        assert await persistence.insert_job(app_conn, job_type=JobType.INVESTIGATE, run_id=run, revision=1) is None
        proposal = uuid4()
        assert await persistence.insert_job(app_conn, job_type=JobType.EXECUTE, run_id=run, proposal_id=proposal)
        assert (
            await persistence.insert_job(app_conn, job_type=JobType.EXECUTE, run_id=run, proposal_id=proposal) is None
        )
        claimed = await persistence.claim_job(app_conn, worker_name="w1")
        assert claimed is not None and claimed["claimed_by"] == "w1" and claimed["attempts"] == 1
        await persistence.finish_job(app_conn, claimed["id"])
        again = await persistence.claim_job(app_conn, worker_name="w2")
        assert again is not None and again["id"] != claimed["id"]  # the other job, not the finished one
        await persistence.finish_job(app_conn, again["id"])


async def test_handles_bind_to_one_server(app_conn: persistence.Conn):
    async with app_conn.transaction(force_rollback=True):
        tenant, _, run = await new_run(app_conn)
        cur = await app_conn.execute("SELECT id FROM app.jobs WHERE run_id = %s", (run,))
        job = (await cur.fetchone())["id"]
        handle = await persistence.mint_handle(app_conn, run_id=run, job_id=job, server=Server.READ, azp="ops-worker")
        inv = await persistence.resolve_handle(
            app_conn, handle=handle, server=Server.READ, azp="ops-worker", tool=Tool.SEARCH_PROCEDURES
        )
        assert inv.run_id == run and inv.tenant_id == tenant and inv.job_type is JobType.INVESTIGATE
        with pytest.raises(persistence.HandleRejected):
            await persistence.resolve_handle(
                app_conn, handle=handle, server=Server.WRITE, azp="ops-worker", tool=Tool.CREATE_INCIDENT
            )
        with pytest.raises(persistence.HandleRejected):
            await persistence.resolve_handle(
                app_conn, handle="nope", server=Server.READ, azp="ops-worker", tool=Tool.SEARCH_PROCEDURES
            )

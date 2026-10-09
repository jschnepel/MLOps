"""The approval and write-path definer functions as their callers (OPS_LIVE=1; AM-20.3 rows 4, 5, 10, 13–15, 17, 18;
R106 cross-tenant; R128 for mcp_exec).

Catches: a frozen proposal whose bytes differ from the validated draft (hash), a self-review or a non-reviewer
approving, a second decision, a handle resolved at the wrong server or after expiry, a grant for another tenant's
proposal through a handle, a second grant for one run, SENT written twice, an outcome recorded twice or with a
foreign hash, UNKNOWN recorded by anyone but the worker, and a preset tenant leaking through any of them.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest
from ops_core import persistence
from ops_core.canonical import canonical_json, sha256_hex
from ops_core.outcomes import EventSource, EventType, event_rules_ok
from ops_core.settings import Role
from psycopg.types.json import Jsonb

from tests.e2e.conftest import purge_run
from tests.e2e.test_definers_run_path_live import ALEX, ALPHA, BETA, as_role, conversation, create, refused

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
SAM = UUID("03f7eb09-e18d-5f33-bf75-12c57d5aaa54")
JORDAN = UUID("cb551e64-83ec-582b-9047-8dadf20e151a")
LEE = UUID("abcc1200-6791-57ab-87b5-9392d356b512")


def payload_for(tenant: UUID, run: UUID, proposal: UUID, now: datetime) -> bytes:
    """A canonical proposal document with the fields the functions read (the full contract is Plan C's)."""
    return canonical_json(
        {
            "tenant_id": str(tenant),
            "run_id": str(run),
            "proposal_id": str(proposal),
            "revision": 1,
            "action": "create_incident",
            "destination": "synthetic-incidents",
            "asset_id": "A17",
            "title": "t",
            "summary": "s",
            "supersedes_run_id": None,
            "expires_at": (now + timedelta(minutes=15)).isoformat().replace("+00:00", "Z"),
        }
    )


async def drafting_run(
    app_conn: persistence.Conn, api: persistence.Conn, worker: persistence.Conn, tenant: UUID = ALPHA
) -> UUID:
    """A run advanced QUEUED to DRAFTING through the real functions."""
    conv, msg = await conversation(app_conn, tenant)
    async with as_role(api):
        run = await create(api, tenant, conv, msg)
    async with as_role(worker):
        await worker.execute("SELECT app.transition_run(%s, 'QUEUED', 'RETRIEVING', NULL, 1, '{}')", (run,))
        await worker.execute("SELECT app.transition_run(%s, 'RETRIEVING', 'DRAFTING', NULL, 2, '{}')", (run,))
    return run


async def freeze(
    app_conn: persistence.Conn, worker: persistence.Conn, run: UUID, tenant: UUID = ALPHA
) -> tuple[UUID, bytes, str]:
    """Insert a validated draft and freeze its proposal as the worker; returns id, bytes and hash."""
    now = datetime.now(UTC).replace(microsecond=0)
    proposal, draft = uuid4(), uuid4()
    body = payload_for(tenant, run, proposal, now)
    digest = sha256_hex(body)
    async with as_role(worker):  # the worker's own INSERT on drafts (AM-20.2) under its tenant, then the function
        await worker.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant),))
        await worker.execute(
            "INSERT INTO app.drafts (id, tenant_id, run_id, draft_sha256, validated, kind)"
            " VALUES (%s, %s, %s, %s, true, 'proposal')",
            (draft, tenant, run, digest),
        )
        cur = await worker.execute(
            "SELECT * FROM app.freeze_proposal(%s, %s, %s, %s)", (run, draft, body, now + timedelta(minutes=15))
        )
        row = await cur.fetchone()
        assert row is not None and row["proposal_id"] == proposal and row["revision"] == 1 and row["state_version"] == 4
    return proposal, body, digest


async def approve(
    api: persistence.Conn, proposal: UUID, digest: str, reviewer: UUID = SAM, tenant: UUID = ALPHA
) -> dict:
    """Record an approving decision as the API and return the result row."""
    async with as_role(api):
        cur = await api.execute(
            "SELECT * FROM app.record_decision(%s, %s, %s, %s, 'approve', NULL, NULL)",
            (tenant, proposal, reviewer, digest),
        )
        return dict(await cur.fetchone())


async def handle_for(app_conn: persistence.Conn, run: UUID, job_type: str, *, expires_in: int = 60) -> str:
    """A raw handle whose hash the superuser inserts (the worker's INSERT is proved in Task 6's live test)."""
    raw = f"handle-{uuid4().hex}"
    job = (
        await (
            await app_conn.execute("SELECT id FROM app.jobs WHERE run_id = %s AND type = %s", (run, job_type))
        ).fetchone()
    )["id"]
    await app_conn.execute(
        "INSERT INTO app.invocation_context (handle_sha256, run_id, job_id, server, azp, expires_at)"
        " VALUES (%s, %s, %s, %s, 'ops-worker', now() + make_interval(secs => %s))",
        (sha256_hex(raw.encode()), run, job, "write" if job_type in ("execute", "recover") else "read", expires_in),
    )
    return raw


async def test_freeze_proposal_binds_bytes_to_the_draft_and_refuses_the_rest(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """Freezing stores the validated bytes and refuses a bad hash, a foreign run, a wrong caller and a replay."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    run = await drafting_run(app_conn, api, worker)
    try:
        now = datetime.now(UTC).replace(microsecond=0)
        proposal, draft = uuid4(), uuid4()
        body = payload_for(ALPHA, run, proposal, now)
        await app_conn.execute(
            "INSERT INTO app.drafts (id, tenant_id, run_id, draft_sha256, validated, kind)"
            " VALUES (%s, %s, %s, %s, true, 'proposal')",
            (draft, ALPHA, run, "0" * 64),  # a draft whose hash is not the bytes'
        )
        assert (
            await refused(worker, "SELECT * FROM app.freeze_proposal(%s, %s, %s, %s)", (run, draft, body, now))
            == "OC007"
        )
        await app_conn.execute("UPDATE app.drafts SET draft_sha256 = %s WHERE id = %s", (sha256_hex(body), draft))
        foreign = payload_for(ALPHA, uuid4(), proposal, now)  # the payload names another run, hashed correctly
        foreign_draft = uuid4()
        await app_conn.execute(
            "INSERT INTO app.drafts (id, tenant_id, run_id, draft_sha256, validated, kind)"
            " VALUES (%s, %s, %s, %s, true, 'proposal')",
            (foreign_draft, ALPHA, run, sha256_hex(foreign)),
        )
        assert (
            await refused(
                worker, "SELECT * FROM app.freeze_proposal(%s, %s, %s, %s)", (run, foreign_draft, foreign, now)
            )
            == "OC005"
        )  # PAYLOAD_RUN_MISMATCH
        assert (
            await refused(api, "SELECT * FROM app.freeze_proposal(%s, %s, %s, %s)", (run, draft, body, now)) == "42501"
        )
        assert (
            await refused(app_conn, "SELECT * FROM app.freeze_proposal(%s, %s, %s, %s)", (run, draft, body, now))
            == "OC001"
        )
        async with as_role(worker):
            cur = await worker.execute(
                "SELECT * FROM app.freeze_proposal(%s, %s, %s, %s)", (run, draft, body, now + timedelta(minutes=15))
            )
            assert (await cur.fetchone())["revision"] == 1
        row = await (
            await app_conn.execute(
                "SELECT state, active_proposal_id, slot_held FROM app.runs WHERE run_id = %s", (run,)
            )
        ).fetchone()
        assert dict(row) == {"state": "AWAITING_APPROVAL", "active_proposal_id": proposal, "slot_held": True}
        stored = await (
            await app_conn.execute(
                "SELECT payload_canonical, payload_sha256, authored_by, canonicalization_version"
                " FROM app.proposals WHERE proposal_id = %s",
                (proposal,),
            )
        ).fetchone()
        assert bytes(stored["payload_canonical"]) == body and stored["payload_sha256"] == sha256_hex(body)
        assert stored["authored_by"] == [ALEX] and stored["canonicalization_version"] == 1
        events = await (
            await app_conn.execute("SELECT type FROM app.events WHERE run_id = %s ORDER BY sequence", (run,))
        ).fetchall()
        assert [e["type"] for e in events] == ["run.accepted", "proposal.ready"]
        assert (
            await refused(worker, "SELECT * FROM app.freeze_proposal(%s, %s, %s, %s)", (run, draft, body, now))
            == "OC003"
        )  # not DRAFTING any more
    finally:
        await purge_run(app_conn, run)


async def test_record_decision_independence_hash_and_first_wins(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """A decision needs an independent current reviewer, the live hash and a first-wins slot."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    run = await drafting_run(app_conn, api, worker)
    try:
        proposal, _, digest = await freeze(app_conn, worker, run)
        call = "SELECT * FROM app.record_decision(%s, %s, %s, %s, 'approve', NULL, NULL)"
        assert await refused(api, call, (ALPHA, proposal, ALEX, digest)) == "OC005"  # the requester (SELF_REVIEW)
        assert await refused(api, call, (ALPHA, proposal, LEE, digest)) == "OC005"  # a reader (NOT_REVIEWER)
        assert await refused(api, call, (ALPHA, proposal, JORDAN, digest)) == "OC005"  # beta's reviewer (NOT_REVIEWER)
        assert await refused(api, call, (BETA, proposal, JORDAN, digest)) == "OC002"  # through beta: not found, no leak
        assert await refused(api, call, (ALPHA, proposal, SAM, "0" * 64)) == "OC003"  # a stale hash
        assert await refused(worker, call, (ALPHA, proposal, SAM, digest)) == "42501"
        assert await refused(api, call, (ALPHA, proposal, SAM, None)) == "OC005"  # a NULL hash must not slip past
        decided = await approve(api, proposal, digest)
        assert decided == {"run_id": run, "state": "APPROVED", "state_version": 5}
        assert await refused(api, call, (ALPHA, proposal, SAM, digest)) == "OC003"  # the first decision won
        jobs = await (
            await app_conn.execute("SELECT type, dedup_key FROM app.jobs WHERE run_id = %s ORDER BY created_at", (run,))
        ).fetchall()
        assert [(j["type"], j["dedup_key"]) for j in jobs] == [("investigate", f"{run}:1"), ("execute", str(proposal))]
        events = await (
            await app_conn.execute("SELECT type FROM app.events WHERE run_id = %s ORDER BY sequence", (run,))
        ).fetchall()
        assert [e["type"] for e in events] == ["run.accepted", "proposal.ready", "approval.recorded"]
        decision = await (
            await app_conn.execute(
                "SELECT tenant_id, reviewer, decision, expected_payload_sha256"
                " FROM app.decisions WHERE proposal_id = %s",
                (proposal,),
            )
        ).fetchone()
        assert dict(decision) == {
            "tenant_id": ALPHA,
            "reviewer": SAM,
            "decision": "approve",
            "expected_payload_sha256": digest,
        }
    finally:
        await purge_run(app_conn, run)


async def test_rejection_frees_the_slot(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    """A rejection ends the run and releases its slot."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    run = await drafting_run(app_conn, api, worker)
    try:
        proposal, _, digest = await freeze(app_conn, worker, run)
        async with as_role(api):
            cur = await api.execute(
                "SELECT * FROM app.record_decision(%s, %s, %s, %s, 'reject', 'rejected', NULL)",
                (ALPHA, proposal, SAM, digest),
            )
            assert dict(await cur.fetchone()) == {"run_id": run, "state": "REJECTED", "state_version": 5}
        row = await (
            await app_conn.execute("SELECT slot_held, reason FROM app.runs WHERE run_id = %s", (run,))
        ).fetchone()
        assert dict(row) == {"slot_held": False, "reason": "rejected"}
        events = await (
            await app_conn.execute("SELECT type FROM app.events WHERE run_id = %s ORDER BY sequence", (run,))
        ).fetchall()
        assert [e["type"] for e in events][-1] == "run.rejected"
    finally:
        await purge_run(app_conn, run)


async def test_resolve_invocation_binds_server_azp_expiry_and_revocation(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """A handle resolves only at its own server, workload, before expiry and revocation."""
    api, worker, mcp_read, mcp_exec = [
        await role_conn(r) for r in (Role.API, Role.WORKER, Role.MCP_READ, Role.MCP_EXEC)
    ]
    run = await drafting_run(app_conn, api, worker)
    try:
        read_handle = await handle_for(app_conn, run, "investigate")
        async with as_role(mcp_read, preset=BETA):
            cur = await mcp_read.execute("SELECT * FROM app.resolve_invocation(%s, 'ops-worker')", (read_handle,))
            row = dict(await cur.fetchone())
            assert (row["run_id"], row["job_type"], row["tenant_id"], row["run_state"], row["attempt_state"]) == (
                run,
                "investigate",
                ALPHA,
                "DRAFTING",
                None,
            )
            assert (await (await mcp_read.execute("SELECT current_setting('app.tenant_id', true) AS t")).fetchone())[
                "t"
            ] == str(BETA)
        assert (
            await refused(mcp_exec, "SELECT * FROM app.resolve_invocation(%s, 'ops-worker')", (read_handle,)) == "OC008"
        )  # a read handle at the write server
        assert (
            await refused(mcp_read, "SELECT * FROM app.resolve_invocation(%s, 'ops-web')", (read_handle,)) == "OC008"
        )  # another workload
        assert (
            await refused(mcp_read, "SELECT * FROM app.resolve_invocation(%s, 'ops-worker')", ("not-a-handle",))
            == "OC008"
        )
        assert await refused(api, "SELECT * FROM app.resolve_invocation(%s, 'ops-worker')", (read_handle,)) == "42501"
        expired = await handle_for(app_conn, run, "investigate", expires_in=-1)
        assert await refused(mcp_read, "SELECT * FROM app.resolve_invocation(%s, 'ops-worker')", (expired,)) == "OC008"
        async with as_role(worker):
            await worker.execute("SELECT app.revoke_handles(%s, 1)", (run,))
        assert (
            await refused(mcp_read, "SELECT * FROM app.resolve_invocation(%s, 'ops-worker')", (read_handle,)) == "OC008"
        )
    finally:
        await purge_run(app_conn, run)


async def test_write_path_grant_sent_outcome_once_and_only_once(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """Grant, SENT and outcome each happen once; replays return what stands."""
    api, worker, mcp_exec = [await role_conn(r) for r in (Role.API, Role.WORKER, Role.MCP_EXEC)]
    run = await drafting_run(app_conn, api, worker)
    try:
        proposal, body, digest = await freeze(app_conn, worker, run)
        await approve(api, proposal, digest)
        handle = await handle_for(app_conn, run, "execute")
        # Gate refusals leave no grant: another proposal id, then the real one.
        assert await refused(mcp_exec, "SELECT * FROM app.grant_execution(%s, %s)", (handle, uuid4())) == "OC005"
        assert (
            await (
                await app_conn.execute("SELECT count(*) AS n FROM app.execution_grant WHERE run_id = %s", (run,))
            ).fetchone()
        )["n"] == 0
        async with as_role(mcp_exec, preset=BETA):
            cur = await mcp_exec.execute("SELECT * FROM app.grant_execution(%s, %s)", (handle, proposal))
            grant = dict(await cur.fetchone())
            assert (
                grant["tenant_id"] == ALPHA
                and grant["attempt_state"] == "INTENT"
                and bytes(grant["payload_canonical"]) == body
            )
            assert grant["payload_sha256"] == digest and grant["detail"] is None
            cur = await mcp_exec.execute(
                "SELECT * FROM app.grant_execution(%s, %s)", (handle, proposal)
            )  # replay: the same grant
            assert dict(await cur.fetchone())["action_id"] == grant["action_id"]
            assert (await (await mcp_exec.execute("SELECT current_setting('app.tenant_id', true) AS t")).fetchone())[
                "t"
            ] == str(BETA)
        assert (
            await refused(mcp_exec, "SELECT * FROM app.grant_execution(%s, %s)", (handle, uuid4())) == "OC005"
        )  # OTHER_PROPOSAL
        assert await refused(worker, "SELECT * FROM app.grant_execution(%s, %s)", (handle, proposal)) == "42501"
        row = await (
            await app_conn.execute("SELECT state, state_version FROM app.runs WHERE run_id = %s", (run,))
        ).fetchone()
        assert dict(row) == {"state": "EXECUTING", "state_version": 6}
        action = grant["action_id"]
        async with as_role(mcp_exec, preset=BETA):  # a hostile preset: ignored by mark_sent/lookup_action and restored
            assert (await (await mcp_exec.execute("SELECT app.mark_sent(%s) AS r", (action,))).fetchone())[
                "r"
            ] == "sent"
            assert (await (await mcp_exec.execute("SELECT app.mark_sent(%s) AS r", (action,))).fetchone())[
                "r"
            ] == "already_sent"
            cur = await mcp_exec.execute("SELECT * FROM app.lookup_action(%s)", (handle,))
            assert dict(await cur.fetchone())["attempt_state"] == "SENT"
            assert (await (await mcp_exec.execute("SELECT current_setting('app.tenant_id', true) AS t")).fetchone())[
                "t"
            ] == str(BETA)
        states = await (
            await app_conn.execute(
                "SELECT seq, state FROM app.action_attempt_state WHERE action_id = %s ORDER BY seq", (action,)
            )
        ).fetchall()
        assert [(s["seq"], s["state"]) for s in states] == [(1, "INTENT"), (2, "SENT")]
        assert (
            await refused(
                mcp_exec,
                "SELECT app.record_outcome(%s, 'SUCCEEDED', %s)",
                (
                    action,
                    Jsonb(
                        {
                            "status": "SUCCEEDED",
                            "action_id": str(action),
                            "payload_sha256": "0" * 64,
                            "receipt": {
                                "receipt_id": str(uuid4()),
                                "incident_id": "INC-1",
                                "committed_at": "2026-10-08T12:00:00Z",
                            },
                        }
                    ),
                ),
            )
            == "OC007"
        )
        receipt = {"receipt_id": str(uuid4()), "incident_id": "INC-000009", "committed_at": "2026-10-08T12:00:00Z"}
        document = {
            "status": "SUCCEEDED",
            "action_id": str(action),
            "payload_sha256": digest,
            "receipt": receipt,
            "tombstone": None,
            "reason": None,
        }
        async with as_role(mcp_exec, preset=BETA):
            assert (
                await (
                    await mcp_exec.execute(
                        "SELECT app.record_outcome(%s, 'SUCCEEDED', %s) AS r", (action, Jsonb(document))
                    )
                ).fetchone()
            )["r"] == "SUCCEEDED"
            assert (await (await mcp_exec.execute("SELECT current_setting('app.tenant_id', true) AS t")).fetchone())[
                "t"
            ] == str(BETA)
            # Idempotent: a second record (even a different one) returns what stands.
            assert (
                await (
                    await mcp_exec.execute(
                        "SELECT app.record_outcome(%s, 'CONFLICT', %s) AS r",
                        (action, Jsonb({"status": "CONFLICT", "action_id": str(action), "payload_sha256": digest})),
                    )
                ).fetchone()
            )["r"] == "SUCCEEDED"
            assert (await (await mcp_exec.execute("SELECT app.mark_sent(%s) AS r", (action,))).fetchone())[
                "r"
            ] == "resolved"
            cur = await mcp_exec.execute("SELECT * FROM app.lookup_action(%s)", (handle,))
            final = dict(await cur.fetchone())
            assert final["attempt_state"] == "RESOLVED" and final["detail"]["receipt"] == receipt
        row = await (
            await app_conn.execute("SELECT state, slot_held FROM app.runs WHERE run_id = %s", (run,))
        ).fetchone()
        assert dict(row) == {"state": "SUCCEEDED", "slot_held": False}
        events = await (
            await app_conn.execute("SELECT type, source FROM app.events WHERE run_id = %s ORDER BY sequence", (run,))
        ).fetchall()
        assert [(e["type"], e["source"]) for e in events] == [
            ("run.accepted", "application"),
            ("proposal.ready", "application"),
            ("approval.recorded", "application"),
            ("action.granted", "application"),
            ("action.dispatched", "application"),
            ("action.confirmed", "destination"),
        ]
        assert (
            await refused(worker, "SELECT app.mark_unknown(%s, 1)", (run,)) == "OC003"
        )  # a terminal run is not EXECUTING
        # The SQL rules and their Python twin agree on every row the functions wrote (round-1 finding I5).
        rows = await (
            await app_conn.execute("SELECT type, source, payload FROM app.events WHERE run_id = %s", (run,))
        ).fetchall()
        for e in rows:
            event_rules_ok(EventType(e["type"]), EventSource(e["source"]), e["payload"])
    finally:
        await purge_run(app_conn, run)


async def test_mark_unknown_is_worker_only_revokes_handles_and_enqueues_recover(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """UNKNOWN is the worker's alone, revokes handles, queues recovery and still accepts a late outcome."""
    api, worker, mcp_exec = [await role_conn(r) for r in (Role.API, Role.WORKER, Role.MCP_EXEC)]
    run = await drafting_run(app_conn, api, worker)
    try:
        proposal, _, digest = await freeze(app_conn, worker, run)
        await approve(api, proposal, digest)
        handle = await handle_for(app_conn, run, "execute")
        async with as_role(mcp_exec):
            grant = dict(
                await (
                    await mcp_exec.execute("SELECT * FROM app.grant_execution(%s, %s)", (handle, proposal))
                ).fetchone()
            )
            await mcp_exec.execute("SELECT app.mark_sent(%s)", (grant["action_id"],))
        assert await refused(mcp_exec, "SELECT app.mark_unknown(%s, 1)", (run,)) == "42501"  # SA:467: the worker's call
        async with as_role(worker, preset=BETA):
            assert (await (await worker.execute("SELECT app.mark_unknown(%s, 1) AS s", (run,))).fetchone())[
                "s"
            ] == "OUTCOME_UNKNOWN"
            assert (await (await worker.execute("SELECT app.mark_unknown(%s, 1) AS s", (run,))).fetchone())[
                "s"
            ] == "OUTCOME_UNKNOWN"  # idempotent
            assert (await (await worker.execute("SELECT current_setting('app.tenant_id', true) AS t")).fetchone())[
                "t"
            ] == str(BETA)
        assert (
            await refused(mcp_exec, "SELECT * FROM app.lookup_action(%s)", (handle,)) == "OC008"
        )  # the handle was revoked
        jobs = await (
            await app_conn.execute("SELECT type, dedup_key FROM app.jobs WHERE run_id = %s ORDER BY created_at", (run,))
        ).fetchall()
        assert jobs[-1]["type"] == "recover" and jobs[-1]["dedup_key"] == f"{grant['action_id']}:timeout"
        events = await (
            await app_conn.execute("SELECT type FROM app.events WHERE run_id = %s ORDER BY sequence", (run,))
        ).fetchall()
        assert [e["type"] for e in events][-2:] == ["action.dispatched", "action.uncertain"]
        # A late outcome still resolves the attempt and the run (SA:464): OUTCOME_UNKNOWN → SUCCEEDED.
        new_handle = await handle_for(app_conn, run, "recover")
        async with as_role(mcp_exec):
            cur = await mcp_exec.execute("SELECT * FROM app.lookup_action(%s)", (new_handle,))
            assert dict(await cur.fetchone())["attempt_state"] == "SENT"
            document = {
                "status": "SUCCEEDED",
                "action_id": str(grant["action_id"]),
                "payload_sha256": digest,
                "receipt": {
                    "receipt_id": str(uuid4()),
                    "incident_id": "INC-000010",
                    "committed_at": "2026-10-08T12:00:00Z",
                },
                "tombstone": None,
                "reason": None,
            }
            assert (
                await (
                    await mcp_exec.execute(
                        "SELECT app.record_outcome(%s, 'SUCCEEDED', %s) AS r", (grant["action_id"], Jsonb(document))
                    )
                ).fetchone()
            )["r"] == "SUCCEEDED"
        assert (await (await app_conn.execute("SELECT state FROM app.runs WHERE run_id = %s", (run,))).fetchone())[
            "state"
        ] == "SUCCEEDED"
    finally:
        await purge_run(app_conn, run)


async def test_late_evidence_on_a_terminal_run_records_without_a_transition(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """SA:464: an outcome arriving after the run gave up is action.late_evidence, no transition, and its payload is
    one the Python rule mirror accepts (round-2 finding NI4). The terminal state is forced by the superuser because
    no Plan E function produces a terminal run with an unresolved attempt (T22's escalation path does)."""
    api, worker, mcp_exec = [await role_conn(r) for r in (Role.API, Role.WORKER, Role.MCP_EXEC)]
    run = await drafting_run(app_conn, api, worker)
    try:
        proposal, _, digest = await freeze(app_conn, worker, run)
        await approve(api, proposal, digest)
        handle = await handle_for(app_conn, run, "execute")
        async with as_role(mcp_exec):
            grant = dict(
                await (
                    await mcp_exec.execute("SELECT * FROM app.grant_execution(%s, %s)", (handle, proposal))
                ).fetchone()
            )
            await mcp_exec.execute("SELECT app.mark_sent(%s)", (grant["action_id"],))
        await app_conn.execute("UPDATE app.runs SET state = 'FAILED', slot_held = false WHERE run_id = %s", (run,))
        document = {
            "status": "SUCCEEDED",
            "action_id": str(grant["action_id"]),
            "payload_sha256": digest,
            "receipt": {
                "receipt_id": str(uuid4()),
                "incident_id": "INC-000011",
                "committed_at": "2026-10-08T12:00:00Z",
            },
            "tombstone": None,
            "reason": None,
        }
        empty = {**document, "receipt": {}}  # a receipt without its three keys is no proof (AM-14)
        record = "SELECT app.record_outcome(%s, 'SUCCEEDED', %s)"
        assert await refused(mcp_exec, record, (grant["action_id"], Jsonb(empty))) == "OC006"
        async with as_role(mcp_exec):
            assert (
                await (
                    await mcp_exec.execute(
                        "SELECT app.record_outcome(%s, 'SUCCEEDED', %s) AS r", (grant["action_id"], Jsonb(document))
                    )
                ).fetchone()
            )["r"] == "SUCCEEDED"
        row = await (await app_conn.execute("SELECT state FROM app.runs WHERE run_id = %s", (run,))).fetchone()
        assert row["state"] == "FAILED"  # no transition on a terminal run
        events = await (
            await app_conn.execute(
                "SELECT type, source, payload FROM app.events WHERE run_id = %s ORDER BY sequence", (run,)
            )
        ).fetchall()
        assert (events[-1]["type"], events[-1]["source"]) == ("action.late_evidence", "destination")
        assert events[-1]["payload"]["outcome"] == "SUCCEEDED" and "tombstone" not in events[-1]["payload"]
        for e in events:
            event_rules_ok(EventType(e["type"]), EventSource(e["source"]), e["payload"])
    finally:
        await purge_run(app_conn, run)


async def test_r106_the_definer_path_cannot_cross_tenants(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    """R106: beta's handle and reviewer never reach alpha's proposal or run (not found or refused, never a row)."""
    api, worker, mcp_exec = [await role_conn(r) for r in (Role.API, Role.WORKER, Role.MCP_EXEC)]
    alpha_run = await drafting_run(app_conn, api, worker, ALPHA)
    beta_run = await drafting_run(app_conn, api, worker, BETA)
    try:
        alpha_proposal, _, alpha_digest = await freeze(app_conn, worker, alpha_run, ALPHA)
        await approve(api, alpha_proposal, alpha_digest)
        beta_proposal, _, beta_digest = await freeze(app_conn, worker, beta_run, BETA)
        await approve(api, beta_proposal, beta_digest, reviewer=JORDAN, tenant=BETA)
        beta_handle = await handle_for(app_conn, beta_run, "execute")
        assert (
            await refused(mcp_exec, "SELECT * FROM app.grant_execution(%s, %s)", (beta_handle, alpha_proposal))
            == "OC005"
        )  # PROPOSAL_NOT_IN_RUN
        assert (
            await (
                await app_conn.execute(
                    "SELECT count(*) AS n FROM app.execution_grant WHERE run_id IN (%s, %s)", (alpha_run, beta_run)
                )
            ).fetchone()
        )["n"] == 0
        assert (
            await refused(
                api,
                "SELECT * FROM app.record_decision(%s, %s, %s, %s, 'approve', NULL, NULL)",
                (BETA, alpha_proposal, JORDAN, alpha_digest),
            )
            == "OC002"
        )
        assert (
            await refused(worker, "SELECT app.transition_run(%s, 'DRAFTING', 'FAILED', NULL, 3, '{}')", (uuid4(),))
            == "OC002"
        )
    finally:
        await purge_run(app_conn, alpha_run)
        await purge_run(app_conn, beta_run)


async def test_mcp_exec_cannot_reach_the_tables_the_functions_touched(role_conn: RoleConn) -> None:
    """mcp_exec holds no table privilege on what the functions write."""
    mcp_exec = await role_conn(Role.MCP_EXEC)
    for table in ("execution_grant", "action_attempt_state", "proposals", "runs", "invocation_context"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await mcp_exec.execute(f"SELECT 1 FROM app.{table} LIMIT 1")


async def test_stale_mark_sent_and_early_outcome_are_refused(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    """A moved run refuses SENT, a receipt before SENT is a violation, and a cancel-before-send outcome stands."""
    api, worker, mcp_exec = [await role_conn(r) for r in (Role.API, Role.WORKER, Role.MCP_EXEC)]
    runs: list[UUID] = []
    try:
        grants = []
        for _ in range(2):
            run = await drafting_run(app_conn, api, worker)
            runs.append(run)
            proposal, _, digest = await freeze(app_conn, worker, run)
            await approve(api, proposal, digest)
            handle = await handle_for(app_conn, run, "execute")
            async with as_role(mcp_exec):
                cur = await mcp_exec.execute("SELECT * FROM app.grant_execution(%s, %s)", (handle, proposal))
                grants.append((dict(await cur.fetchone())["action_id"], digest))
        (stale, stale_digest), (cancelled, cancelled_digest) = grants
        # The superuser moves the run as mark_unknown would, leaving the attempt at INTENT.
        await app_conn.execute("UPDATE app.runs SET state = 'OUTCOME_UNKNOWN' WHERE run_id = %s", (runs[0],))
        assert await refused(mcp_exec, "SELECT app.mark_sent(%s)", (stale,)) == "OC003"
        early = {"status": "SUCCEEDED", "action_id": str(stale), "payload_sha256": stale_digest}
        record = "SELECT app.record_outcome(%s, %s, %s)"
        assert await refused(mcp_exec, record, (stale, "SUCCEEDED", Jsonb(early))) == "OC003"  # outcome before SENT
        # Cancelled before send: FAILED_NO_COMMIT from INTENT on an EXECUTING run is allowed.
        tombstone = {
            "action_id": str(cancelled),
            "state": "ABORTED",
            "payload_sha256": cancelled_digest,
            "reason": "cancelled_before_send",
            "decided_at": "2026-10-08T12:00:00Z",
        }
        failed = {
            "status": "FAILED_NO_COMMIT",
            "action_id": str(cancelled),
            "payload_sha256": cancelled_digest,
            "reason": "cancelled_before_send",
            "tombstone": tombstone,
            "receipt": None,
        }
        wrong_status = {**failed, "status": "SUCCEEDED"}  # a document that disagrees with the outcome recorded
        assert await refused(mcp_exec, record, (cancelled, "FAILED_NO_COMMIT", Jsonb(wrong_status))) == "OC005"
        # "No effect" without the destination's tombstone is refused in SQL too (final review M1).
        for bare in ({**failed, "tombstone": None}, {k: v for k, v in failed.items() if k != "tombstone"}):
            assert await refused(mcp_exec, record, (cancelled, "FAILED_NO_COMMIT", Jsonb(bare))) == "OC005"
        async with as_role(mcp_exec):
            cur = await mcp_exec.execute(record + " AS r", (cancelled, "FAILED_NO_COMMIT", Jsonb(failed)))
            assert (await cur.fetchone())["r"] == "FAILED_NO_COMMIT"
        row = await (await app_conn.execute("SELECT state FROM app.runs WHERE run_id = %s", (runs[1],))).fetchone()
        assert row["state"] == "FAILED"
    finally:
        for run in runs:
            await purge_run(app_conn, run)

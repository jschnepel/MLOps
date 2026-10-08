"""grant → SENT → POST → record_outcome against a real incident-sim process and the real database (OPS_LIVE=1), then the
same call again: one action id, one incident, the stored outcome returned without a second POST (review focus 1)."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx2
import pytest
import uvicorn
from ops_core import persistence, settings
from ops_core.canonical import canonical_json, canonical_sha256
from ops_core.jobs import JobType, Server, Tool
from ops_core.outcomes import EventSource, EventType, ToolOutcome
from ops_core.states import Performer, RunState
from ops_core.tokens import WorkloadTokenSource
from ops_incident_sim.app import production_app as incident_sim_app
from ops_mcp_write import destination, execution
from psycopg.types.json import Jsonb

from tests.e2e.conftest import purge_run, purge_tenant
from tests.e2e.test_migrations_and_persistence import new_run

pytestmark = pytest.mark.asyncio

ALEX = "2fc05986-c7ec-544c-b628-fdb112bbf18a"
SAM = "03f7eb09-e18d-5f33-bf75-12c57d5aaa54"


async def approved_run(conn: persistence.Conn) -> tuple:
    tenant, conv, run = await new_run(conn)
    await persistence.append_event(
        conn,
        tenant_id=tenant,
        conversation_id=conv,
        run_id=run,
        type=EventType.RUN_ACCEPTED,
        source=EventSource.APPLICATION,
        payload={},
    )
    for dst in (RunState.RETRIEVING, RunState.DRAFTING):
        await persistence.transition(conn, run_id=run, dst=dst, performer=Performer.TRANSITION_RUN)
    draft, proposal = uuid4(), uuid4()
    now = datetime.now(UTC).replace(microsecond=0)
    payload = {
        "tenant_id": str(tenant),
        "run_id": str(run),
        "proposal_id": str(proposal),
        "revision": 1,
        "action": "create_incident",
        "destination": "synthetic-incidents",
        "asset_id": "A17",
        "start_at": (now - timedelta(hours=24)).isoformat().replace("+00:00", "Z"),
        "end_at": now.isoformat().replace("+00:00", "Z"),
        "title": "Live write-path proposal",
        "summary": "Synthetic.",
        "evidence_refs": ["ALPHA-INCIDENT:v2:review"],
        "source_snapshots": [
            {
                "evidence_id": "ALPHA-INCIDENT:v2:review",
                "content_sha256": "62a90906c7bb706ae8a968eb0f7102f76b05d2c3be911c182d528a1fd25ef008",
                "version": "2",
            }
        ],
        "assumptions": [],
        "limitations": ["live test"],
        "workflow_version": "investigation-v1",
        "prompt_version": "incident-draft-v1",
        "expires_at": (now + timedelta(minutes=15)).isoformat().replace("+00:00", "Z"),
    }
    canonical = canonical_json(payload)
    sha = canonical_sha256(payload)
    await conn.execute(
        "INSERT INTO app.drafts (id, run_id, draft_sha256, validated, kind) VALUES (%s, %s, %s, true, 'proposal')",
        (draft, run, sha),
    )
    await conn.execute(
        "INSERT INTO app.proposals (proposal_id, tenant_id, run_id, revision, draft_id, payload, payload_canonical,"
        " payload_sha256, canonicalization_version, authored_by, expires_at)"
        " VALUES (%s, %s, %s, 1, %s, %s, %s, %s, 1, %s, %s)",
        (proposal, tenant, run, draft, Jsonb(payload), canonical, sha, [ALEX], now + timedelta(minutes=15)),
    )
    await conn.execute("UPDATE app.runs SET active_proposal_id = %s WHERE run_id = %s", (proposal, run))
    await persistence.transition(conn, run_id=run, dst=RunState.AWAITING_APPROVAL, performer=Performer.FREEZE_PROPOSAL)
    await conn.execute(
        "INSERT INTO app.decisions (decision_id, proposal_id, reviewer, decision, expected_payload_sha256)"
        " VALUES (%s, %s, %s, 'approve', %s)",
        (uuid4(), proposal, SAM, sha),
    )
    await persistence.transition(conn, run_id=run, dst=RunState.APPROVED, performer=Performer.RECORD_DECISION)
    job = await persistence.insert_job(conn, job_type=JobType.EXECUTE, run_id=run, proposal_id=proposal)
    assert job is not None
    handle = await persistence.mint_handle(conn, run_id=run, job_id=job, server=Server.WRITE, azp="ops-worker")
    return tenant, conv, run, proposal, handle


async def test_write_path_twice(app_conn: persistence.Conn, secret, monkeypatch: pytest.MonkeyPatch) -> None:
    # Port 18090: the skeleton's own incident-sim may hold 8090 in the same session (Task 9's fixture).
    server = uvicorn.Server(uvicorn.Config(incident_sim_app(), host="127.0.0.1", port=18090, log_level="warning"))
    task = asyncio.create_task(server.serve())
    observed: list[str] = []
    original_post = destination.post_incident

    async def post_with_probe(*args, **kwargs):
        # SA:229 / BUILD_SPEC §11: by the time the first byte leaves, SENT must be durable. A second connection sees
        # only committed rows, so it is the witness.
        witness = await persistence.connect(settings.app_postgres())
        try:
            cur = await witness.execute(
                "SELECT state FROM app.action_attempt_state WHERE action_id = %s ORDER BY seq DESC LIMIT 1",
                (kwargs["action_id"],),
            )
            observed.append((await cur.fetchone() or {}).get("state", "NONE"))
        finally:
            await witness.close()
        return await original_post(*args, **kwargs)

    monkeypatch.setattr(destination, "post_incident", post_with_probe)
    tenant = run = None
    try:
        while not server.started:
            await asyncio.sleep(0.05)
        async with app_conn.transaction():  # committed: the witness connection must see the rows
            tenant, _, run, proposal, handle = await approved_run(app_conn)
        session = persistence.Session(app_conn)
        async with session.unit() as conn:
            invocation = await persistence.resolve_handle(
                conn, handle=handle, server=Server.WRITE, azp="ops-worker", tool=Tool.CREATE_INCIDENT
            )
        kc = settings.keycloak()
        async with httpx2.AsyncClient() as http:
            deps = execution.Deps(
                session=session,
                http=http,
                destination_url="http://127.0.0.1:18090",
                destination_token=WorkloadTokenSource(
                    token_url=kc.token_url,
                    client_id="ops-mcp-write",
                    client_secret=secret("kc_client_secret_ops_mcp_write"),
                ),
            )
            first = await execution.create_incident(deps, invocation=invocation, proposal_id=proposal)
            second = await execution.create_incident(deps, invocation=invocation, proposal_id=proposal)
        assert first.status is ToolOutcome.SUCCEEDED and second == first
        assert observed == ["SENT"]  # exactly one POST, and SENT was committed before it
        row = await persistence.run_row(app_conn, run)
        assert row["state"] == "SUCCEEDED"
        cur = await app_conn.execute("SELECT type, source FROM app.events WHERE run_id = %s ORDER BY sequence", (run,))
        assert [tuple(r.values()) for r in await cur.fetchall()] == [
            ("run.accepted", "application"),
            ("action.granted", "application"),
            ("action.dispatched", "application"),
            ("action.confirmed", "destination"),
        ]
        cur = await app_conn.execute(
            "SELECT count(*) AS n FROM app.action_attempt_state WHERE action_id = %s", (first.action_id,)
        )
        assert (await cur.fetchone())["n"] == 3  # INTENT, SENT, RESOLVED and nothing for the replay
    finally:
        server.should_exit = True
        await task
        if run is not None:
            await purge_run(app_conn, run)
            await purge_tenant(app_conn, tenant)

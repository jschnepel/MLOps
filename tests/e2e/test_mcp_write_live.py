"""grant → SENT → POST → record_outcome against a real incident-sim process and the real database (OPS_LIVE=1), then the
same call again: one action id, one incident, the stored outcome returned without a second POST (review focus 1)."""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx2
import pytest
import uvicorn
from ops_core import persistence, settings
from ops_core.canonical import canonical_json, canonical_sha256
from ops_core.jobs import Server
from ops_core.outcomes import ToolOutcome
from ops_core.settings import Role
from ops_core.states import RunState
from ops_core.tokens import WorkloadTokenSource
from ops_incident_sim.app import production_app as incident_sim_app
from ops_mcp_write import destination, execution
from ops_mcp_write.server import outcome_envelope

from tests.e2e.conftest import purge_run
from tests.e2e.test_migrations_and_persistence import new_run

pytestmark = pytest.mark.asyncio

ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")  # seeded: SAM is its reviewer, ALEX its requester
SAM = UUID("03f7eb09-e18d-5f33-bf75-12c57d5aaa54")


async def approved_run(app_conn: persistence.Conn, *, api: persistence.Conn, worker: persistence.Conn) -> tuple:
    """An APPROVED run on the seeded tenant built through the definer functions, with a write handle for its job."""
    tenant = ALPHA
    _, _, run = await new_run(app_conn, tenant, api=api)
    for src, dst in ((RunState.QUEUED, RunState.RETRIEVING), (RunState.RETRIEVING, RunState.DRAFTING)):
        await persistence.transition_run(worker, run_id=run, src=src, dst=dst)
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
    # One worker transaction: set_tenant is transaction-local, and on autocommit the INSERT would meet RLS.
    async with worker.transaction():
        await persistence.set_tenant(worker, tenant)
        await worker.execute(
            "INSERT INTO app.drafts (id, tenant_id, run_id, draft_sha256, validated, kind)"
            " VALUES (%s, %s, %s, %s, true, 'proposal')",
            (draft, tenant, run, sha),
        )
        await persistence.freeze_proposal(
            worker, run_id=run, draft_id=draft, payload_canonical=canonical, expires_at=now + timedelta(minutes=15)
        )
    async with api.transaction():  # the function queues the execute job
        await persistence.record_decision(
            api, tenant_id=tenant, proposal_id=proposal, reviewer=SAM, expected_payload_sha256=sha, decision="approve"
        )
    cur = await app_conn.execute("SELECT id FROM app.jobs WHERE run_id = %s AND type = 'execute'", (run,))
    job = (await cur.fetchone())["id"]
    async with worker.transaction():
        await persistence.set_tenant(worker, tenant)
        handle = await persistence.mint_handle(worker, run_id=run, job_id=job, server=Server.WRITE, azp="ops-worker")
    return tenant, run, proposal, handle


async def test_write_path_twice(app_conn: persistence.Conn, role_conn, secret, monkeypatch: pytest.MonkeyPatch) -> None:
    # Port 18090: the skeleton's own incident-sim may hold 8090 in the same session (Task 9's fixture).
    server = uvicorn.Server(uvicorn.Config(incident_sim_app(), host="127.0.0.1", port=18090, log_level="warning"))
    task = asyncio.create_task(server.serve())
    observed: list[str] = []
    original_post = destination.post_incident

    async def post_with_probe(*args, **kwargs):
        # SA:229 / BUILD_SPEC §11: by the time the first byte leaves, SENT must be durable. A second connection sees
        # only committed rows, so it is the witness.
        witness = await persistence.connect(settings.superuser_postgres())
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
    run = None
    try:
        while not server.started:
            await asyncio.sleep(0.05)
        _, run, proposal, handle = await approved_run(
            app_conn, api=await role_conn(Role.API), worker=await role_conn(Role.WORKER)
        )
        session = persistence.Session(await role_conn(Role.MCP_EXEC))
        async with httpx2.AsyncClient() as http:
            deps = make_deps(session, http, secret)
            first = await execution.create_incident(deps, handle=handle, proposal_id=proposal)
            second = await execution.create_incident(deps, handle=handle, proposal_id=proposal)
        assert first.status is ToolOutcome.SUCCEEDED and second == first
        assert observed == ["SENT"]  # exactly one POST, and SENT was committed before it
        row = await persistence.run_row(app_conn, run)
        assert row["state"] == "SUCCEEDED"
        cur = await app_conn.execute("SELECT type, source FROM app.events WHERE run_id = %s ORDER BY sequence", (run,))
        assert [tuple(r.values()) for r in await cur.fetchall()] == [
            ("run.accepted", "application"),
            ("proposal.ready", "application"),
            ("approval.recorded", "application"),
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


@contextlib.asynccontextmanager
async def running_sim() -> AsyncIterator[None]:
    """An in-process incident-sim on 18090 for the duration of the block."""
    server = uvicorn.Server(uvicorn.Config(incident_sim_app(), host="127.0.0.1", port=18090, log_level="warning"))
    task = asyncio.create_task(server.serve())
    try:
        while not server.started:
            await asyncio.sleep(0.05)
        yield
    finally:
        server.should_exit = True
        await task


def make_deps(session: persistence.Session, http: httpx2.AsyncClient, secret) -> execution.Deps:
    """Write-path dependencies pointing at the in-process incident-sim; the session sits on a mcp_exec connection."""
    kc = settings.keycloak()
    return execution.Deps(
        session=session,
        http=http,
        destination_url="http://127.0.0.1:18090",
        destination_token=WorkloadTokenSource(
            token_url=kc.token_url, client_id="ops-mcp-write", client_secret=secret("kc_client_secret_ops_mcp_write")
        ),
    )


async def test_concurrent_calls_share_one_attempt(
    app_conn: persistence.Conn, role_conn, secret, monkeypatch: pytest.MonkeyPatch
) -> None:
    posts: list[int] = []
    original_post = destination.post_incident

    async def counting_post(*args, **kwargs):
        posts.append(1)
        return await original_post(*args, **kwargs)

    monkeypatch.setattr(destination, "post_incident", counting_post)
    run = None
    try:
        async with running_sim():
            _, run, proposal, handle = await approved_run(
                app_conn, api=await role_conn(Role.API), worker=await role_conn(Role.WORKER)
            )
            session = persistence.Session(await role_conn(Role.MCP_EXEC))
            async with httpx2.AsyncClient() as http:
                deps = make_deps(session, http, secret)
                first, second = await asyncio.gather(
                    execution.create_incident(deps, handle=handle, proposal_id=proposal),
                    execution.create_incident(deps, handle=handle, proposal_id=proposal),
                )
        assert first.status is ToolOutcome.SUCCEEDED and first == second
        assert len(posts) <= 2
        assert (await persistence.run_row(app_conn, run))["state"] == "SUCCEEDED"
        cur = await app_conn.execute("SELECT action_id FROM app.execution_grant WHERE run_id = %s", (run,))
        assert [r["action_id"] for r in await cur.fetchall()] == [first.action_id]
        cur = await app_conn.execute(
            "SELECT state FROM app.action_attempt_state WHERE action_id = %s ORDER BY seq", (first.action_id,)
        )
        assert [r["state"] for r in await cur.fetchall()] == ["INTENT", "SENT", "RESOLVED"]
    finally:
        if run is not None:
            await purge_run(app_conn, run)


async def exploding_post(*args, **kwargs):
    """A destination call that raises after SENT."""
    raise RuntimeError("boom")


async def swallowed_post(*args, **kwargs):
    """A transport failure the client already swallowed: no reply at all."""
    return


async def unavailable_post(*args, **kwargs):
    """A 503 with an empty document, which `classify` reads as UNKNOWN (round-2 finding NI1)."""
    return destination.Reply(503, {})


@pytest.mark.parametrize("post", [exploding_post, swallowed_post, unavailable_post])
async def test_exception_after_sent_returns_unknown_and_records_nothing(
    app_conn: persistence.Conn, role_conn, secret, monkeypatch: pytest.MonkeyPatch, post
) -> None:
    """mcp-write returns the UNKNOWN envelope and records nothing; the worker records UNKNOWN (Task 6's live test).

    Before the fix a classified UNKNOWN reached record_outcome, which refuses it by design, and raised.
    """
    monkeypatch.setattr(destination, "post_incident", post)
    run = None
    try:
        _, run, proposal, handle = await approved_run(
            app_conn, api=await role_conn(Role.API), worker=await role_conn(Role.WORKER)
        )
        session = persistence.Session(await role_conn(Role.MCP_EXEC))
        async with httpx2.AsyncClient() as http:
            outcome = await execution.create_incident(
                make_deps(session, http, secret), handle=handle, proposal_id=proposal
            )
        assert outcome.status is ToolOutcome.UNKNOWN
        assert (await persistence.run_row(app_conn, run))["state"] == "EXECUTING"
        cur = await app_conn.execute(
            "SELECT s.state FROM app.action_attempt_state s JOIN app.execution_grant g USING (action_id)"
            " WHERE g.run_id = %s ORDER BY s.seq DESC LIMIT 1",
            (run,),
        )
        assert (await cur.fetchone())["state"] == "SENT"
        cur = await app_conn.execute("SELECT type FROM app.events WHERE run_id = %s ORDER BY sequence", (run,))
        assert [r["type"] for r in await cur.fetchall()] == [
            "run.accepted",
            "proposal.ready",
            "approval.recorded",
            "action.granted",
            "action.dispatched",
        ]
    finally:
        if run is not None:
            await purge_run(app_conn, run)


async def test_refusal_after_a_real_post_is_unknown_not_an_error(
    app_conn: persistence.Conn, role_conn, secret, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mapped refusal from record_outcome after SENT answers outcome/UNKNOWN, never an error envelope (I1, AM-13).

    The POST is real, so the destination has committed; an error envelope would make the worker close the job and
    strand the run in EXECUTING with a SENT attempt. A future lease fence raises VersionConflict on exactly this call.
    """

    async def fenced_record_outcome(*args, **kwargs):
        raise persistence.VersionConflict("x")

    monkeypatch.setattr(persistence, "record_outcome", fenced_record_outcome)
    run = None
    try:
        async with running_sim():
            _, run, proposal, handle = await approved_run(
                app_conn, api=await role_conn(Role.API), worker=await role_conn(Role.WORKER)
            )
            session = persistence.Session(await role_conn(Role.MCP_EXEC))
            async with httpx2.AsyncClient() as http:
                outcome = await execution.create_incident(
                    make_deps(session, http, secret), handle=handle, proposal_id=proposal
                )
        doc = outcome_envelope(outcome)
        assert doc["status"] == "outcome" and doc["error"] is None
        assert doc["data"]["status"] == ToolOutcome.UNKNOWN.value
        assert (await persistence.run_row(app_conn, run))["state"] == "EXECUTING"
        cur = await app_conn.execute(
            "SELECT s.state FROM app.action_attempt_state s JOIN app.execution_grant g USING (action_id)"
            " WHERE g.run_id = %s ORDER BY s.seq DESC LIMIT 1",
            (run,),
        )
        assert (await cur.fetchone())["state"] == "SENT"
    finally:
        if run is not None:
            await purge_run(app_conn, run)

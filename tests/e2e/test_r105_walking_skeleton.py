"""R105: one run crosses every service over real HTTP with real tokens and ends SUCCEEDED (OPS_LIVE=1).

api (alex) → job → worker → mcp-read (search_procedures) → fake draft → frozen proposal → decision by sam → execute job
→ worker → mcp-write (create_incident) → incident-sim → receipt → action.confirmed (source=destination). Also the
refusals the skeleton must already make: the requester deciding, a stale hash, a second decision, a workload token at
the API, a persona token at the destination. Writes redacted evidence to reports/skeleton/ (no token, no secret).
"""

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx2
import psycopg
import pytest
from mcp import Client, MCPError
from mcp.client.streamable_http import streamable_http_client
from ops_core import persistence, settings
from ops_core.jobs import Server
from ops_core.settings import Role
from ops_worker.mcp import failure_leaf

from scripts.skeleton import Skeleton, orphan_keys
from tests.plan_b.live import kc

API = "http://127.0.0.1:8000"
EVIDENCE = Path("reports/skeleton/r105-walking-skeleton.txt")
EXPECTED_EVENTS = [
    ("run.accepted", "application"),
    ("tool.started", "application"),
    ("tool.completed", "application"),
    ("explanation.ready", "model_summary"),
    ("proposal.ready", "application"),
    ("approval.recorded", "application"),
    ("action.granted", "application"),
    ("action.dispatched", "application"),
    ("action.confirmed", "destination"),
]
pytestmark = pytest.mark.sweeper_stamps  # the skeleton's own sweeper keeps the memberships fresh here


@pytest.fixture(scope="module")
def skeleton(migrated: None) -> Iterator[Skeleton]:
    """Module scope on purpose: the skeleton worker must be down before test_worker_live claims jobs itself. The
    memberships are aged past the 120 s window first, so the grant inside the run passes only because the skeleton's
    own sweeper re-stamped them (this module opts out of the autouse stamp)."""
    with psycopg.connect(settings.superuser_postgres().conninfo(), autocommit=True) as conn:
        conn.execute("UPDATE app.memberships SET synced_at = app.current_time() - interval '10 minutes'")
    sk = Skeleton()
    sk.start()
    try:
        with psycopg.connect(settings.superuser_postgres().conninfo(), autocommit=True) as conn:
            fresh = conn.execute(
                "SELECT bool_and(synced_at > app.current_time() - interval '120 seconds') FROM app.memberships"
            ).fetchone()[0]
        assert fresh, "the sweeper did not stamp memberships.synced_at before reporting ready"
        yield sk
    finally:
        sk.stop()


async def mcp_call(url: str, token: str, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """One tool call over the real transport; None when the transport refused the token (an MCPError, which may
    arrive wrapped in an anyio exception group — see ops_worker.mcp.failure_leaf)."""
    headers = {"Authorization": f"Bearer {token}", "X-Ops-Invocation": handle}
    try:
        async with (
            httpx2.AsyncClient(headers=headers) as hc,
            Client(streamable_http_client(url, http_client=hc), mode="2026-07-28") as client,
        ):
            res = await client.call_tool(tool, arguments)
    except MCPError:
        return None
    except BaseExceptionGroup as group:
        if isinstance(failure_leaf(group), MCPError):
            return None
        raise
    content = res.structured_content
    return content if isinstance(content, dict) else {"is_error": res.is_error}


def wait_for(client: httpx2.Client, url: str, headers: dict[str, str], states: set[str], timeout: float = 45.0) -> dict:
    """Poll a run snapshot until its status is in `states`; fail with the last status when the time is up."""
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = client.get(url, headers=headers).json()
        if last.get("status") in states:
            return last
        time.sleep(0.5)
    raise AssertionError(f"run did not reach {states}; last snapshot status={last.get('status')}")


@pytest.mark.asyncio
async def test_r105_walking_skeleton(
    skeleton: Skeleton, secret, app_conn: persistence.Conn, role_conn, incident_conn: persistence.Conn
) -> None:
    kcs = settings.keycloak()
    urls = settings.urls()
    alex = kc.token_password(kcs.base_url, "ops-dev-direct", "alex", secret("kc_persona_alex_password"))["access_token"]
    sam = kc.token_password(kcs.base_url, "ops-dev-direct", "sam", secret("kc_persona_sam_password"))["access_token"]
    worker = kc.token_client_credentials(kcs.base_url, "ops-worker", secret("kc_client_secret_ops_worker"))[
        "access_token"
    ]
    mcp_write = kc.token_client_credentials(kcs.base_url, "ops-mcp-write", secret("kc_client_secret_ops_mcp_write"))[
        "access_token"
    ]
    mcp_read = kc.token_client_credentials(kcs.base_url, "ops-mcp-read", secret("kc_client_secret_ops_mcp_read"))[
        "access_token"
    ]
    a, s = {"Authorization": f"Bearer {alex}"}, {"Authorization": f"Bearer {sam}"}
    lines: list[str] = [f"R105 walking skeleton — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"]
    with httpx2.Client(base_url=API, timeout=10.0) as c:
        # Responses are bound before every assert: pytest prints assert operands, and a header would carry a token.
        refused = c.get("/api/v1/me", headers={"Authorization": f"Bearer {worker}"})
        assert refused.status_code == 401  # a workload token at the API: wrong audience and azp
        cid = c.post("/api/v1/conversations", headers=a).json()["conversation_id"]
        accepted = c.post(
            f"/api/v1/conversations/{cid}/messages",
            headers=a,
            json={
                "kind": "investigate",
                "text": "Investigate the alerts on Asset A17 over the last 24 hours.",
                "context": {"asset_id": "A17", "hours": 24},
            },
        )
        assert accepted.status_code == 202, accepted.text
        run_id = accepted.json()["run_id"]
        lines.append(f"run_id={run_id} accepted status={accepted.json()['status']}")
        snapshot = wait_for(c, f"/api/v1/runs/{run_id}", a, {"AWAITING_APPROVAL", "FAILED", "INSUFFICIENT_EVIDENCE"})
        assert snapshot["status"] == "AWAITING_APPROVAL", snapshot
        pid = snapshot["active_proposal_id"]
        proposal = c.get(f"/api/v1/proposals/{pid}", headers=s).json()
        sha, revision = proposal["payload_sha256"], proposal["revision"]
        me = c.get("/api/v1/me", headers=a).json()
        assert proposal["payload"]["evidence_refs"] and proposal["authored_by"] == [me["subject"]]
        evidence = proposal["payload"]["evidence_refs"]
        lines.append(f"proposal_id={pid} revision={revision} payload_sha256={sha} evidence={evidence}")
        decision = {
            "expected_revision": revision,
            "expected_payload_sha256": sha,
            "decision": "approve",
            "reason": "Reviewed the exact synthetic proposal.",
        }
        self_decision = c.post(f"/api/v1/proposals/{pid}/decisions", headers=a, json=decision)
        assert self_decision.status_code == 403  # the requester may not approve their own proposal
        stale = c.post(
            f"/api/v1/proposals/{pid}/decisions", headers=s, json={**decision, "expected_payload_sha256": "0" * 64}
        )
        assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"
        approved = c.post(f"/api/v1/proposals/{pid}/decisions", headers=s, json=decision)
        assert approved.status_code == 200 and approved.json()["status"] == "APPROVED", approved.text
        second = c.post(f"/api/v1/proposals/{pid}/decisions", headers=s, json=decision)
        assert second.status_code == 409  # the first decision wins
        final = wait_for(c, f"/api/v1/runs/{run_id}", a, {"SUCCEEDED", "FAILED", "OUTCOME_UNKNOWN", "ESCALATED"})
        assert final["status"] == "SUCCEEDED", final
        events = c.get(f"/api/v1/runs/{run_id}/events", headers=a).json()["events"]
        assert [(e["type"], e["source"]) for e in events] == EXPECTED_EVENTS, [e["type"] for e in events]
        confirmed = events[-1]["payload"]
        assert confirmed["status"] == "SUCCEEDED" and confirmed["receipt"]["incident_id"].startswith("INC-")
        action_id = confirmed["action_id"]
        lines.append(
            f"state={final['status']} state_version={final['state_version']} action_id={action_id} "
            f"incident_id={confirmed['receipt']['incident_id']}"
        )
        lines.append("events=" + ",".join(e["type"] for e in events))
    with httpx2.Client(base_url=urls.incident_sim, timeout=10.0) as d:
        persona_at_destination = d.get(f"/internal/actions/{action_id}", headers=a)
        worker_at_destination = d.get(f"/internal/actions/{action_id}", headers={"Authorization": f"Bearer {worker}"})
        refusals = (persona_at_destination.status_code, worker_at_destination.status_code)
        # Genuine tokens for another audience or azp are 403 at the destination (ruling 12), never 401.
        assert refusals == (403, 403)
        assert action_id not in persona_at_destination.text and action_id not in worker_at_destination.text
        key = d.get(f"/internal/actions/{action_id}", headers={"Authorization": f"Bearer {mcp_write}"}).json()
        assert key["state"] == "COMMITTED" and key["payload_sha256"] == sha
    # Review focus 1 and 3 over the real transport: a replayed create_incident with a fresh execute handle returns
    # the recorded outcome (same action id, no second incident), and the wrong tokens are refused at mcp-write.
    cur = await app_conn.execute("SELECT id FROM app.jobs WHERE run_id = %s AND type = 'execute'", (UUID(run_id),))
    execute_job = (await cur.fetchone())["id"]
    cur = await app_conn.execute("SELECT tenant_id FROM app.run_directory WHERE run_id = %s", (UUID(run_id),))
    tenant = (await cur.fetchone())["tenant_id"]
    worker_conn = await role_conn(Role.WORKER)
    async with worker_conn.transaction():  # the worker role under the run's tenant; set_tenant is transaction-local
        await persistence.set_tenant(worker_conn, tenant)
        handle = await persistence.mint_handle(
            worker_conn, run_id=UUID(run_id), job_id=execute_job, server=Server.WRITE, azp="ops-worker"
        )
    replay = await mcp_call(urls.mcp_write, worker, handle, "create_incident", {"proposal_id": pid})
    assert replay is not None and replay["status"] == "ok" and replay["data"]["action_id"] == action_id
    for wrong in (alex, mcp_read):
        refused_wrong = await mcp_call(urls.mcp_write, wrong, handle, "create_incident", {"proposal_id": pid})
        assert refused_wrong is None
    with httpx2.Client(base_url=urls.incident_sim, timeout=10.0) as d:
        again = d.get(f"/internal/actions/{action_id}", headers={"Authorization": f"Bearer {mcp_write}"}).json()
        assert again["receipt"] == key["receipt"]  # the same receipt, so no second incident
    lines.append("replay=same_action_id refusals=api:worker,destination:persona+worker,mcp-write:persona+mcp-read")
    lines.append(f"destination_refusals=persona:{refusals[0]},worker:{refusals[1]}")
    # The detective check, inline: this run's destination key must carry a grant's exact (action_id, hash). The exit
    # code of `skeleton.py keys` is not used because another live test plants an orphan on purpose.
    cur = await app_conn.execute("SELECT action_id, payload_sha256 FROM app.execution_grant")
    grants = {(row["action_id"], row["payload_sha256"]) for row in await cur.fetchall()}
    cur = await incident_conn.execute("SELECT action_id, payload_sha256 FROM incident.action_key")
    destination_keys = [(row["action_id"], row["payload_sha256"]) for row in await cur.fetchall()]
    assert UUID(action_id) in {k[0] for k in destination_keys}
    assert UUID(action_id) not in {k[0] for k in orphan_keys(destination_keys, grants)}
    lines.append("keys=consistent")
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

"""The two handlers against the real database with a scripted MCP caller (OPS_LIVE=1): the state path, the frozen
proposal's bytes and hash, the event order, and the execute job's handle. The real MCP transport is proved in Task 5's
and Task 9's tests."""

from typing import Any
from uuid import UUID

import pytest
from ops_core import persistence, settings
from ops_core.canonical import canonical_json, canonical_sha256
from ops_core.jobs import JobType, Server, Tool
from ops_core.states import Performer, RunState
from ops_worker import handlers
from ops_worker.drafting import FakeDraftGenerator

from tests.e2e.test_migrations_and_persistence import new_run

pytestmark = pytest.mark.asyncio

SEARCH = {
    "status": "ok",
    "data": {
        "results": [
            {
                "evidence_id": "ALPHA-INCIDENT:v2:review",
                "document_id": "ALPHA-INCIDENT",
                "version": "2",
                "section": "review",
                "content_sha256": "62a90906c7bb706ae8a968eb0f7102f76b05d2c3be911c182d528a1fd25ef008",
                "excerpt": "text",
                "effective_from": "2026-10-01T00:00:00Z",
                "retrieved_at": "2026-10-08T12:00:00Z",
            }
        ],
        "retrieval_mode": "lexical",
        "corpus_version": "handoff-1",
    },
}


class ScriptedMcp:
    def __init__(self, conn: persistence.Conn) -> None:
        self.conn = conn
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((url, tool, arguments))
        server = Server.READ if tool == "search_procedures" else Server.WRITE
        await persistence.resolve_handle(self.conn, handle=handle, server=server, azp="ops-worker", tool=Tool(tool))
        if tool == "search_procedures":
            return SEARCH
        return {
            "status": "ok",
            "data": {
                "status": "SUCCEEDED",
                "action_id": str(UUID(int=1)),
                "payload_sha256": "x",
                "receipt": None,
                "tombstone": None,
                "reason": None,
            },
        }


async def own_job(conn: persistence.Conn, run, job_type: str) -> dict:
    """The run's own job, claimed by this test (claim_job takes the oldest available job of any run, so a leftover
    from another test would be claimed instead)."""
    cur = await conn.execute(
        "UPDATE app.jobs SET claimed_by = 't', claimed_at = now(), attempts = attempts + 1"
        " WHERE run_id = %s AND type = %s AND done_at IS NULL RETURNING *",
        (run, job_type),
    )
    row = await cur.fetchone()
    assert row is not None, (run, job_type)
    return dict(row)


async def test_investigate_then_execute(app_conn: persistence.Conn) -> None:
    mcp = ScriptedMcp(app_conn)
    deps = handlers.Deps(conn=app_conn, mcp=mcp, generator=FakeDraftGenerator(), urls=settings.urls(), worker_name="t")
    async with app_conn.transaction(force_rollback=True):  # everything below rolls back; nothing else sees it
        await _investigate_then_execute(app_conn, deps, mcp)


async def _investigate_then_execute(app_conn: persistence.Conn, deps: handlers.Deps, mcp: ScriptedMcp) -> None:
    _, _, run = await new_run(app_conn)
    job = await own_job(app_conn, run, "investigate")
    await handlers.handle(deps, job)
    row = await persistence.run_row(app_conn, run)
    assert row["state"] == "AWAITING_APPROVAL" and row["active_proposal_id"] is not None
    cur = await app_conn.execute("SELECT * FROM app.proposals WHERE proposal_id = %s", (row["active_proposal_id"],))
    proposal = await cur.fetchone()
    assert canonical_json(proposal["payload"]) == bytes(proposal["payload_canonical"])
    assert canonical_sha256(proposal["payload"]) == proposal["payload_sha256"]
    assert proposal["payload"]["evidence_refs"] == ["ALPHA-INCIDENT:v2:review"]
    cur = await app_conn.execute("SELECT type, source FROM app.events WHERE run_id = %s ORDER BY sequence", (run,))
    assert [tuple(r.values()) for r in await cur.fetchall()] == [
        ("tool.started", "application"),
        ("tool.completed", "application"),
        ("explanation.ready", "model_summary"),
        ("proposal.ready", "application"),
    ]
    cur = await app_conn.execute(
        "SELECT seq, to_state FROM app.run_state_history WHERE run_id = %s ORDER BY seq", (run,)
    )
    assert [r["to_state"] for r in await cur.fetchall()] == ["QUEUED", "RETRIEVING", "DRAFTING", "AWAITING_APPROVAL"]
    # Approve directly (the API does this in Task 7) and run the execute job.
    await app_conn.execute(
        "INSERT INTO app.decisions (decision_id, proposal_id, reviewer, decision,"
        " expected_payload_sha256) VALUES (gen_random_uuid(), %s, %s, 'approve', %s)",
        (proposal["proposal_id"], UUID("03f7eb09-e18d-5f33-bf75-12c57d5aaa54"), proposal["payload_sha256"]),
    )
    await persistence.transition(app_conn, run_id=run, dst=RunState.APPROVED, performer=Performer.RECORD_DECISION)
    await persistence.insert_job(app_conn, job_type=JobType.EXECUTE, run_id=run, proposal_id=proposal["proposal_id"])
    job = await own_job(app_conn, run, "execute")
    await handlers.handle(deps, job)
    assert [c[1] for c in mcp.calls] == ["search_procedures", "create_incident"]
    assert mcp.calls[1][2] == {"proposal_id": str(proposal["proposal_id"])}
    cur = await app_conn.execute("SELECT done_at IS NOT NULL AS done FROM app.jobs WHERE id = %s", (job["id"],))
    assert (await cur.fetchone())["done"]


class RaisingGenerator:
    async def generate(self, request: Any, evidence: Any) -> Any:
        """Stand in for a model route that fails mid-draft."""
        raise RuntimeError("model route failed")


async def test_drafting_failure_fails_the_run(app_conn: persistence.Conn) -> None:
    mcp = ScriptedMcp(app_conn)
    deps = handlers.Deps(conn=app_conn, mcp=mcp, generator=RaisingGenerator(), urls=settings.urls(), worker_name="t")
    async with app_conn.transaction(force_rollback=True):
        _, _, run = await new_run(app_conn)
        job = await own_job(app_conn, run, "investigate")
        await handlers.handle(deps, job)
        row = await persistence.run_row(app_conn, run)
        assert row["state"] == "FAILED" and row["active_proposal_id"] is None
        cur = await app_conn.execute("SELECT type FROM app.events WHERE run_id = %s ORDER BY sequence", (run,))
        assert [r["type"] for r in await cur.fetchall()] == ["tool.started", "tool.completed", "run.failed"]
        cur = await app_conn.execute(
            "SELECT to_state FROM app.run_state_history WHERE run_id = %s ORDER BY seq", (run,)
        )
        assert [r["to_state"] for r in await cur.fetchall()] == ["QUEUED", "RETRIEVING", "DRAFTING", "FAILED"]
        cur = await app_conn.execute("SELECT done_at IS NOT NULL AS done FROM app.jobs WHERE id = %s", (job["id"],))
        assert (await cur.fetchone())["done"]

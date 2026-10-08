"""The two handlers as role `worker` against the real database with a scripted MCP caller (OPS_LIVE=1): the state
path through the definer functions, the frozen proposal's bytes and hash, the event order, the execute job's handle,
the re-queue of an unreachable write server, and the worker's own recording of UNKNOWN. The real MCP transport is
proved in Task 5's and Task 9's tests.

Rows are written by role connections, so nothing here can roll back: every test purges its run in `finally`. The
seeded tenant ALPHA is used because `record_decision` needs SAM's reviewer membership."""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from ops_core import persistence, settings
from ops_core.canonical import canonical_json, canonical_sha256
from ops_core.jobs import Server, Tool
from ops_core.settings import Role
from ops_worker import handlers
from ops_worker.drafting import FakeDraftGenerator
from ops_worker.mcp import McpCallFailed

from tests.e2e.conftest import purge_run
from tests.e2e.test_migrations_and_persistence import new_run

pytestmark = pytest.mark.asyncio

ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")
SAM = UUID("03f7eb09-e18d-5f33-bf75-12c57d5aaa54")  # ALPHA's seeded reviewer
RoleConn = Callable[[Role], Awaitable[persistence.Conn]]

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
    """An MCP caller that resolves the handle as the real server's role would, then answers from a script."""

    def __init__(self, read: persistence.Conn, write: persistence.Conn) -> None:
        self.read, self.write = read, write  # role mcp_read and role mcp_exec connections
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Resolve the handle for the tool's server, then return the scripted envelope."""
        self.calls.append((url, tool, arguments))
        server = Server.READ if tool == "search_procedures" else Server.WRITE
        await persistence.resolve_invocation(
            self.read if server is Server.READ else self.write, handle=handle, azp="ops-worker", tool=Tool(tool)
        )
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


WorkerDeps = Callable[[type[ScriptedMcp], Any], Awaitable[tuple[handlers.Deps, ScriptedMcp]]]


@pytest_asyncio.fixture
async def worker_deps(role_conn: RoleConn) -> WorkerDeps:
    """A factory of worker `Deps` on a role-`worker` connection with a scripted caller on the MCP roles."""

    async def build(mcp_class: type[ScriptedMcp], generator: Any) -> tuple[handlers.Deps, ScriptedMcp]:
        mcp = mcp_class(await role_conn(Role.MCP_READ), await role_conn(Role.MCP_EXEC))
        deps = handlers.Deps(
            conn=await role_conn(Role.WORKER),
            mcp=mcp,
            generator=generator,
            urls=settings.urls(),
            worker_name="t",
        )
        return deps, mcp

    return build


async def own_job(conn: persistence.Conn, run: UUID, job_type: str) -> dict[str, Any]:
    """The run's own job, claimed by this test (claim_job takes the oldest available job of any run, so a leftover
    from another test would be claimed instead). Superuser, so it returns the tenant `handlers.handle` reads."""
    cur = await conn.execute(
        "UPDATE app.jobs SET claimed_by = 't', claimed_at = now(), attempts = attempts + 1"
        " WHERE run_id = %s AND type = %s AND done_at IS NULL RETURNING *",
        (run, job_type),
    )
    row = await cur.fetchone()
    assert row is not None, (run, job_type)
    return dict(row)


async def event_types(conn: persistence.Conn, run: UUID) -> list[tuple[str, str]]:
    """The run's (type, source) pairs in sequence order."""
    cur = await conn.execute("SELECT type, source FROM app.events WHERE run_id = %s ORDER BY sequence", (run,))
    return [(r["type"], r["source"]) for r in await cur.fetchall()]


async def proposal_of(conn: persistence.Conn, run: UUID) -> dict[str, Any]:
    """The run's active proposal row."""
    row = await persistence.run_row(conn, run)
    cur = await conn.execute("SELECT * FROM app.proposals WHERE proposal_id = %s", (row["active_proposal_id"],))
    found = await cur.fetchone()
    assert found is not None
    return dict(found)


async def approve(api: persistence.Conn, proposal: dict[str, Any]) -> None:
    """SAM approves the exact frozen hash through the API's function, which also queues the execute job."""
    async with api.transaction():
        await persistence.record_decision(
            api,
            tenant_id=proposal["tenant_id"],
            proposal_id=proposal["proposal_id"],
            reviewer=SAM,
            expected_payload_sha256=proposal["payload_sha256"],
            decision="approve",
        )


async def test_investigate_then_execute(
    app_conn: persistence.Conn, role_conn: RoleConn, worker_deps: WorkerDeps
) -> None:
    api = await role_conn(Role.API)
    deps, mcp = await worker_deps(ScriptedMcp, FakeDraftGenerator())
    run = None
    try:
        _, _, run = await new_run(app_conn, ALPHA, api=api)
        await handlers.handle(deps, await own_job(app_conn, run, "investigate"))
        row = await persistence.run_row(app_conn, run)
        assert row["state"] == "AWAITING_APPROVAL" and row["active_proposal_id"] is not None
        proposal = await proposal_of(app_conn, run)
        assert canonical_json(proposal["payload"]) == bytes(proposal["payload_canonical"])
        assert canonical_sha256(proposal["payload"]) == proposal["payload_sha256"]
        assert proposal["payload"]["evidence_refs"] == ["ALPHA-INCIDENT:v2:review"]
        assert await event_types(app_conn, run) == [
            ("run.accepted", "application"),
            ("tool.started", "application"),
            ("tool.completed", "application"),
            ("explanation.ready", "model_summary"),
            ("proposal.ready", "application"),
        ]
        cur = await app_conn.execute(
            "SELECT seq, to_state FROM app.run_state_history WHERE run_id = %s ORDER BY seq", (run,)
        )
        assert [r["to_state"] for r in await cur.fetchall()] == [
            "QUEUED",
            "RETRIEVING",
            "DRAFTING",
            "AWAITING_APPROVAL",
        ]
        await approve(api, proposal)
        assert (await event_types(app_conn, run))[-1] == ("approval.recorded", "application")
        job = await own_job(app_conn, run, "execute")
        await handlers.handle(deps, job)
        assert [c[1] for c in mcp.calls] == ["search_procedures", "create_incident"]
        assert mcp.calls[1][2] == {"proposal_id": str(proposal["proposal_id"])}
        cur = await app_conn.execute("SELECT done_at IS NOT NULL AS done FROM app.jobs WHERE id = %s", (job["id"],))
        assert (await cur.fetchone())["done"]
    finally:
        if run is not None:
            await purge_run(app_conn, run)


class RaisingGenerator:
    """A model route that fails mid-draft."""

    async def generate(self, request: Any, evidence: Any) -> Any:
        """Stand in for a model route that fails mid-draft."""
        raise RuntimeError("model route failed")


async def test_drafting_failure_fails_the_run(
    app_conn: persistence.Conn, role_conn: RoleConn, worker_deps: WorkerDeps
) -> None:
    api = await role_conn(Role.API)
    deps, _ = await worker_deps(ScriptedMcp, RaisingGenerator())
    run = None
    try:
        _, _, run = await new_run(app_conn, ALPHA, api=api)
        job = await own_job(app_conn, run, "investigate")
        await handlers.handle(deps, job)
        row = await persistence.run_row(app_conn, run)
        assert row["state"] == "FAILED" and row["active_proposal_id"] is None
        cur = await app_conn.execute("SELECT type FROM app.events WHERE run_id = %s ORDER BY sequence", (run,))
        assert [r["type"] for r in await cur.fetchall()] == [
            "run.accepted",
            "tool.started",
            "tool.completed",
            "run.failed",
        ]
        cur = await app_conn.execute(
            "SELECT to_state FROM app.run_state_history WHERE run_id = %s ORDER BY seq", (run,)
        )
        assert [r["to_state"] for r in await cur.fetchall()] == ["QUEUED", "RETRIEVING", "DRAFTING", "FAILED"]
        cur = await app_conn.execute("SELECT done_at IS NOT NULL AS done FROM app.jobs WHERE id = %s", (job["id"],))
        assert (await cur.fetchone())["done"]
    finally:
        if run is not None:
            await purge_run(app_conn, run)


class WriteDownMcp(ScriptedMcp):
    """A scripted MCP whose write server cannot be reached."""

    async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Fail `create_incident` as a transport error; everything else is the scripted behaviour."""
        if tool == "create_incident":
            self.calls.append((url, tool, arguments))
            raise McpCallFailed("create_incident: transport or protocol failure")
        return await super().call(url, handle=handle, tool=tool, arguments=arguments)


class GrantThenDownMcp(ScriptedMcp):
    """A write server that grants and marks SENT as mcp-write would, then drops the connection."""

    async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Grant and mark SENT as `mcp_exec`, then fail the transport (a crash after the point of no return)."""
        if tool != "create_incident":
            return await super().call(url, handle=handle, tool=tool, arguments=arguments)
        self.calls.append((url, tool, arguments))
        async with self.write.transaction():
            grant = await persistence.grant_execution(
                self.write, handle=handle, proposal_id=UUID(arguments["proposal_id"])
            )
            await persistence.mark_sent(self.write, grant.action_id)
        raise McpCallFailed("create_incident: connection lost after SENT")


class UnknownMcp(ScriptedMcp):
    """A write server that grants, marks SENT and then reports an UNKNOWN envelope without recording it."""

    async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Grant and mark SENT as `mcp_exec`, then answer UNKNOWN (SA:467: recording it is the worker's)."""
        if tool != "create_incident":
            return await super().call(url, handle=handle, tool=tool, arguments=arguments)
        self.calls.append((url, tool, arguments))
        async with self.write.transaction():
            grant = await persistence.grant_execution(
                self.write, handle=handle, proposal_id=UUID(arguments["proposal_id"])
            )
            await persistence.mark_sent(self.write, grant.action_id)
        return {
            "status": "outcome",
            "data": {
                "status": "UNKNOWN",
                "action_id": str(grant.action_id),
                "payload_sha256": grant.payload_sha256,
                "receipt": None,
                "tombstone": None,
                "reason": "timeout",
            },
        }


async def test_unreachable_write_server_requeues_the_execute_job(
    app_conn: persistence.Conn, role_conn: RoleConn, worker_deps: WorkerDeps
) -> None:
    api = await role_conn(Role.API)
    deps, mcp = await worker_deps(WriteDownMcp, FakeDraftGenerator())
    run = None
    try:
        _, _, run = await new_run(app_conn, ALPHA, api=api)
        await handlers.handle(deps, await own_job(app_conn, run, "investigate"))
        await approve(api, await proposal_of(app_conn, run))
        job = await own_job(app_conn, run, "execute")
        await handlers.handle(deps, job)
        assert (await persistence.run_row(app_conn, run))["state"] == "APPROVED"
        cur = await app_conn.execute(
            "SELECT done_at IS NULL AS open, claimed_by IS NULL AS free, available_at > now() AS later"
            " FROM app.jobs WHERE id = %s",
            (job["id"],),
        )
        assert dict(await cur.fetchone()) == {"open": True, "free": True, "later": True}
        # Once the delay has passed the same job can be claimed again; this time the write server grants and marks
        # SENT before the connection drops, which leaves the run EXECUTING.
        await app_conn.execute("UPDATE app.jobs SET available_at = now() WHERE id = %s", (job["id"],))
        job = await own_job(app_conn, run, "execute")
        grant_mcp = GrantThenDownMcp(mcp.read, mcp.write)
        deps.mcp = grant_mcp
        await handlers.handle(deps, job)
        assert (await persistence.run_row(app_conn, run))["state"] == "EXECUTING"
        assert [c[1] for c in grant_mcp.calls] == ["create_incident"]
        # A re-queued job of an EXECUTING run must be dispatched again (same action id), not finished unsent.
        await app_conn.execute("UPDATE app.jobs SET available_at = now() WHERE id = %s", (job["id"],))
        job = await own_job(app_conn, run, "execute")
        await handlers.handle(deps, job)
        assert [c[1] for c in grant_mcp.calls] == ["create_incident", "create_incident"]
        cur = await app_conn.execute("SELECT done_at IS NULL AS open FROM app.jobs WHERE id = %s", (job["id"],))
        assert (await cur.fetchone())["open"]  # re-queued again, not finished
        assert (await persistence.run_row(app_conn, run))["state"] == "EXECUTING"
    finally:
        if run is not None:
            await purge_run(app_conn, run)


async def test_unknown_envelope_is_recorded_by_the_worker(
    app_conn: persistence.Conn, role_conn: RoleConn, worker_deps: WorkerDeps
) -> None:
    api = await role_conn(Role.API)
    deps, _ = await worker_deps(UnknownMcp, FakeDraftGenerator())
    run = None
    try:
        _, _, run = await new_run(app_conn, ALPHA, api=api)
        await handlers.handle(deps, await own_job(app_conn, run, "investigate"))
        await approve(api, await proposal_of(app_conn, run))
        job = await own_job(app_conn, run, "execute")
        await handlers.handle(deps, job)
        assert (await persistence.run_row(app_conn, run))["state"] == "OUTCOME_UNKNOWN"
        assert (await event_types(app_conn, run))[-1][0] == "action.uncertain"
        cur = await app_conn.execute("SELECT 1 FROM app.jobs WHERE run_id = %s AND type = 'recover'", (run,))
        assert await cur.fetchone() is not None
        cur = await app_conn.execute("SELECT done_at IS NOT NULL AS done FROM app.jobs WHERE id = %s", (job["id"],))
        assert (await cur.fetchone())["done"]
    finally:
        if run is not None:
            await purge_run(app_conn, run)

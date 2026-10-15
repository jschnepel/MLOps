"""T13 live (OPS_LIVE=1): the fence inside the definer functions, called by their real callers against the
per-session test database (Plan H rulings 5-9; R020's MCP side, R027's T13 half; errata 48, 53-55).

Catches: a handle that still resolves after a takeover or after its lease lapsed (R027's "expired fence"), a stale
mcp-write that writes SENT or sends anyway, a stale fence after SENT that becomes an error envelope instead of UNKNOWN
(Plan E final review I1), a revocation that refuses a lost owner or kills a newer owner's handles, and a mark_unknown
that does not bump the fence, accepts a stale or lapsed one, or keeps the old handles alive.
"""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import httpx2
import pytest
from ops_core import persistence
from ops_core.jobs import Server, Tool
from ops_core.lease import Lease
from ops_core.outcomes import ToolOutcome
from ops_core.settings import Role
from ops_core.states import RunState
from ops_mcp_write import destination, execution
from ops_mcp_write.server import outcome_envelope

from tests.e2e.conftest import expire_lease, lease_for, purge_run, purge_tenant
from tests.e2e.test_mcp_write_live import approved_run, make_deps, running_sim
from tests.e2e.test_migrations_and_persistence import new_run

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
BUMP = "UPDATE app.run_lease SET fence = fence + 1 WHERE run_id = %s"


async def investigate_job(app_conn: persistence.Conn, run: UUID) -> UUID:
    cur = await app_conn.execute("SELECT id FROM app.jobs WHERE run_id = %s AND type = 'investigate'", (run,))
    row = await cur.fetchone()
    assert row is not None
    return UUID(str(row["id"]))


async def read_handle(worker: persistence.Conn, run: UUID, job: UUID, lease: Lease) -> str:
    async with worker.transaction():
        return await persistence.mint_handle(
            worker, run_id=run, job_id=job, server=Server.READ, azp="ops-worker", fence=lease.fence
        )


async def resolve(mcp_read: persistence.Conn, handle: str) -> persistence.Invocation:
    """Resolve a read handle as mcp-read does for `search_procedures`."""
    return await persistence.resolve_invocation(mcp_read, handle=handle, azp="ops-worker", tool=Tool.SEARCH_PROCEDURES)


async def attempt_states(app_conn: persistence.Conn, run: UUID) -> list[str]:
    cur = await app_conn.execute(
        "SELECT s.state FROM app.action_attempt_state s JOIN app.execution_grant g USING (action_id)"
        " WHERE g.run_id = %s ORDER BY s.seq",
        (run,),
    )
    return [row["state"] for row in await cur.fetchall()]


async def test_a_handle_is_refused_after_its_fence_moves_and_after_its_lease_expires(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """Ruling 7: T13's half of R027 ("expired fence")."""
    a, b, mcp_read = await role_conn(Role.WORKER), await role_conn(Role.WORKER), await role_conn(Role.MCP_READ)
    tenant, _, run = await new_run(app_conn, api=await role_conn(Role.API))
    try:
        job = await investigate_job(app_conn, run)
        old = await read_handle(a, run, job, await lease_for(a, run, owner="wa"))
        assert (await resolve(mcp_read, old)).run_id == run
        await expire_lease(app_conn, run)  # lapsed, nobody else yet: the handle itself has 60 s left
        with pytest.raises(persistence.HandleRejected):
            await resolve(mcp_read, old)
        new = await read_handle(b, run, job, await lease_for(b, run, owner="wb"))
        with pytest.raises(persistence.HandleRejected):  # the fence moved: the old handle is dead though unexpired
            await resolve(mcp_read, old)
        assert (await resolve(mcp_read, new)).run_id == run
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


async def test_a_stale_fence_before_sent_is_a_handle_refusal_and_sends_nothing(
    app_conn: persistence.Conn, role_conn: RoleConn, secret: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ruling 6, before SENT: the lease moves between the grant and SENT; mark_sent refuses, nothing is sent, and
    server.py answers the refusal as INVALID_HANDLE (an honest error: nothing reached the destination)."""
    posts: list[int] = []
    run: UUID | None = None

    async def counting_post(*_: Any, **__: Any) -> None:
        posts.append(1)

    real_mark_sent = persistence.mark_sent

    async def takeover_then_mark_sent(conn: persistence.Conn, **kwargs: Any) -> str:
        await app_conn.execute(BUMP, (run,))  # another owner took the run after the grant committed
        return await real_mark_sent(conn, **kwargs)

    monkeypatch.setattr(destination, "post_incident", counting_post)
    monkeypatch.setattr(persistence, "mark_sent", takeover_then_mark_sent)
    try:
        _, run, proposal, handle = await approved_run(
            app_conn, api=await role_conn(Role.API), worker=await role_conn(Role.WORKER)
        )
        session = persistence.Session(await role_conn(Role.MCP_EXEC))
        async with httpx2.AsyncClient() as http:
            with pytest.raises(persistence.HandleRejected):
                await execution.create_incident(make_deps(session, http, secret), handle=handle, proposal_id=proposal)
        assert posts == [] and await attempt_states(app_conn, run) == ["INTENT"]
        assert (await persistence.run_row(app_conn, run))["state"] == "EXECUTING"
    finally:
        if run is not None:
            await purge_run(app_conn, run)


async def test_a_stale_fence_after_sent_is_unknown_never_an_error(
    app_conn: persistence.Conn, role_conn: RoleConn, secret: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ruling 6, after SENT: the destination commits, the lease moves before the outcome is recorded; record_outcome
    refuses, and mcp-write answers outcome/UNKNOWN, never an error envelope."""
    run: UUID | None = None
    original_post = destination.post_incident

    async def post_then_takeover(*args: Any, **kwargs: Any) -> destination.Reply | None:
        reply = await original_post(*args, **kwargs)  # the destination has committed
        await app_conn.execute(BUMP, (run,))
        return reply

    monkeypatch.setattr(destination, "post_incident", post_then_takeover)
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
        assert await attempt_states(app_conn, run) == ["INTENT", "SENT"]  # nothing recorded after SENT
    finally:
        if run is not None:
            await purge_run(app_conn, run)


async def test_revoke_handles_takes_only_the_old_fences_handles(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """Ruling 8: a lost owner still revokes its own handles; the new owner's survive."""
    a, b, mcp_read = await role_conn(Role.WORKER), await role_conn(Role.WORKER), await role_conn(Role.MCP_READ)
    tenant, _, run = await new_run(app_conn, api=await role_conn(Role.API))
    try:
        job = await investigate_job(app_conn, run)
        first = await lease_for(a, run, owner="wa")
        old = await read_handle(a, run, job, first)
        await expire_lease(app_conn, run)
        new = await read_handle(b, run, job, await lease_for(b, run, owner="wb"))
        async with a.transaction():
            assert await persistence.revoke_handles(a, run, first.fence) == 1  # never refused for a stale fence
        cur = await app_conn.execute(
            "SELECT handle_sha256, revoked_at IS NOT NULL AS revoked FROM app.invocation_context WHERE run_id = %s",
            (run,),
        )
        revoked = {row["handle_sha256"]: row["revoked"] for row in await cur.fetchall()}
        assert revoked == {persistence.handle_hash(old): True, persistence.handle_hash(new): False}
        assert (await resolve(mcp_read, new)).run_id == run
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


async def test_mark_unknown_bumps_the_fence_and_returns_it(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    """Ruling 9: the lease's own fence marks UNKNOWN once and moves the fence; the old fence and a lapsed lease are
    refused; the old handles are dead."""
    worker, mcp_exec = await role_conn(Role.WORKER), await role_conn(Role.MCP_EXEC)
    _, run, proposal, handle = await approved_run(app_conn, api=await role_conn(Role.API), worker=worker)
    try:
        cur = await app_conn.execute("SELECT fence FROM app.run_lease WHERE run_id = %s", (run,))
        fence = int((await cur.fetchone())["fence"])
        async with mcp_exec.transaction():
            grant = await persistence.grant_execution(mcp_exec, handle=handle, proposal_id=proposal)
            assert await persistence.mark_sent(mcp_exec, handle=handle, action_id=grant.action_id) == "sent"
        async with worker.transaction():
            unknown = await persistence.mark_unknown(worker, run, fence)
        assert unknown == persistence.Unknown(RunState.OUTCOME_UNKNOWN, fence + 1)
        with pytest.raises(persistence.HandleRejected):  # minted under the old fence: dead and revoked
            async with mcp_exec.transaction():
                await persistence.lookup_action(mcp_exec, handle=handle)
        with pytest.raises(persistence.VersionConflict):  # the old fence is stale now
            async with worker.transaction():
                await persistence.mark_unknown(worker, run, fence)
        await expire_lease(app_conn, run)
        with pytest.raises(persistence.VersionConflict):  # the current fence, but the lease lapsed
            async with worker.transaction():
                await persistence.mark_unknown(worker, run, fence + 1)
        cur = await app_conn.execute(
            "SELECT revoked_at IS NOT NULL AS revoked FROM app.invocation_context WHERE handle_sha256 = %s",
            (persistence.handle_hash(handle),),
        )
        assert (await cur.fetchone())["revoked"]
    finally:
        await purge_run(app_conn, run)  # the seeded tenant ALPHA stays

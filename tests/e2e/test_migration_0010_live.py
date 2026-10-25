"""Revision 0010 against the per-session test database (OPS_LIVE=1; Plan K rulings 3, 7, 12, 17 and 25), each definer
called by its real caller, `mcp_exec`.

Catches: a downgrade that leaves 0010's functions behind or restores the four applied bodies differently from a
database that never saw 0010, or an upgrade that does not bring 0010 back; mcp-write's startup check passing at 0009;
`mark_sent` writing SENT past the dispatch deadline, after an abort request, or answering `expired` for a cancelled
run, and allowing the re-send of a SENT attempt after a cancel, past the deadline or to a recover job;
`request_abort` writing a row when no abort is due, choosing the wrong reason, or writing a second row on a repeat, or
answering for another run's action id or a finished job's handle;
a receipt refused after an abort requested after SENT (an abort answered by the existing receipt is the destination's
truth), or accepted after one requested before SENT (nothing was ever sent); and a
write-path definer that still compares a literal `'ops-worker'` instead of the presented token's `azp` (a handle
minted for a renamed client is refused with the old name and accepted with its own, at every one of the five).
"""

import importlib.util
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from ops_core import persistence, settings
from ops_core.jobs import Server, Tool
from ops_core.outcomes import ActionOutcome, DestinationState, Receipt, Tombstone, ToolOutcome
from ops_core.settings import Profile, Role
from ops_core.states import Reason
from psycopg import sql
from psycopg.rows import dict_row

from tests.e2e.conftest import lease_for, purge_run
from tests.e2e.test_fenced_definers_live import attempt_states
from tests.e2e.test_mcp_write_live import ALPHA, approved_run
from tests.e2e.test_migration_0007_live import FUNCTION_DETAILS, LEFTOVERS, exists

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "app" / "versions"
AZP = "ops-worker"  # the client every live handle is minted for (the worker's token source's)
SCRATCH_PREFIX = "r009_"  # every scratch database this module creates; leftovers are dropped by prefix
LATE = "UPDATE app.test_clock SET clock_offset = interval '400 seconds'"  # past the 300 s dispatch deadline
NOW = "UPDATE app.test_clock SET clock_offset = interval '0'"
APP_FUNCTIONS = (
    "SELECT p.oid::regprocedure::text AS signature, pg_get_functiondef(p.oid) AS body, p.proacl::text AS acl,"
    " p.proowner::regrole::text AS owner, p.proconfig::text AS config"
    " FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'app'"
)


def revision_0010() -> Any:
    """Revision 0010 loaded by path, for the bodies it creates and the ones its downgrade restores."""
    spec = importlib.util.spec_from_file_location("live_rev_0010", VERSIONS / "0010_write_path.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def built_to_0009(superuser: settings.Postgres, signatures: list[str]) -> dict[str, dict[str, Any]]:
    """The functions' details as a database built straight to 0009 holds them (the 0007 module's pattern): a scratch
    database is created, upgraded by the applied revisions alone, read and dropped."""
    from scripts.skeleton import upgrade

    scratch = f"{SCRATCH_PREFIX}{uuid4().hex[:12]}"
    try:
        with psycopg.connect(superuser.conninfo(), autocommit=True, row_factory=dict_row) as admin:
            for row in admin.execute(LEFTOVERS, (SCRATCH_PREFIX,)).fetchall():
                admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(row["datname"])))
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(scratch)))
        target = settings.Postgres(superuser.host, superuser.port, superuser.user, scratch, superuser.password)
        upgrade("app", target, "0009_handle_binding")
        with psycopg.connect(target.conninfo(), row_factory=dict_row) as conn:
            return {name: dict(conn.execute(FUNCTION_DETAILS, (name,)).fetchone() or {}) for name in signatures}
    finally:
        with psycopg.connect(superuser.conninfo(), autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(scratch)))


async def snapshot(conn: persistence.Conn) -> dict[str, dict[str, Any]]:
    """Every `app` function's definition, ACL, owner and settings, by signature."""
    cur = await conn.execute(APP_FUNCTIONS)
    return {row["signature"]: {k: v for k, v in row.items() if k != "signature"} for row in await cur.fetchall()}


async def test_the_round_trip_restores_0009(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    from scripts.skeleton import downgrade, migrate

    superuser = settings.superuser_postgres()
    mcp_exec = await role_conn(Role.MCP_EXEC)
    module = revision_0010()
    head = await snapshot(app_conn)
    created = [f"app.{name}({args})" for name, args, _, _ in module.FUNCTIONS]
    restored = [f"app.{name}({args})" for name, args, _, _ in module.RESTORED]
    assert all([await exists(app_conn, s) for s in created]) and not any([await exists(app_conn, s) for s in restored])
    await persistence.assert_function_text(mcp_exec, *persistence.WRITE_PATH)  # mcp-write starts on the head
    try:
        downgrade("app", superuser, "0009_handle_binding")
        assert not any([await exists(app_conn, s) for s in created])
        # The four applied bodies are back exactly (the stored source is the text between the dollar quotes) ...
        for name, args, _, body in module.RESTORED:
            cur = await app_conn.execute(
                "SELECT prosrc FROM pg_proc WHERE oid = %s::regprocedure", (f"app.{name}({args})",)
            )
            assert (await cur.fetchone())["prosrc"] == body.split("$fn$")[1], name
        # ... and so are their definitions, ACLs, owners and settings, against a database that never saw 0010.
        reference = built_to_0009(superuser, restored)
        for signature in restored:
            cur = await app_conn.execute(FUNCTION_DETAILS, (signature,))
            assert dict(await cur.fetchone()) == reference[signature], signature
        with pytest.raises(persistence.PersistenceError, match="predates this service"):
            await persistence.assert_function_text(mcp_exec, *persistence.WRITE_PATH)  # mcp-write refuses 0009
    finally:
        assert migrate(Profile.TEST) == 0  # every later test needs the head
    assert await snapshot(app_conn) == head  # the upgrade brings back exactly what the downgrade took


async def execute_handle(worker: persistence.Conn, run: UUID, *, azp: str = AZP, fence: int | None = None) -> str:
    """A fresh write handle for the run's execute job: under a lease taken now (the old one lapsed with the moved
    clock), or at `fence` when the current lease is still live."""
    if fence is None:
        fence = (await lease_for(worker, run, owner=f"k-{uuid4().hex[:8]}", seconds=600)).fence
    async with worker.transaction():
        await persistence.set_tenant(worker, ALPHA)
        cur = await worker.execute("SELECT id FROM app.jobs WHERE run_id = %s AND type = 'execute'", (run,))
        job = UUID(str((await cur.fetchone() or {})["id"]))
        return await persistence.mint_handle(worker, run_id=run, job_id=job, server=Server.WRITE, azp=azp, fence=fence)


async def fence_of(app_conn: persistence.Conn, run: UUID) -> int:
    cur = await app_conn.execute("SELECT fence FROM app.run_lease WHERE run_id = %s", (run,))
    return int((await cur.fetchone() or {})["fence"])


async def recover_handle(app_conn: persistence.Conn, worker: persistence.Conn, run: UUID, trigger: str) -> str:
    """A recover job for the run, staged by the superuser as mark_unknown or the sweeper would queue it (the worker's
    recover handler is T22's), and its write handle at the run's current fence."""
    job = uuid4()
    await app_conn.execute(
        "INSERT INTO app.jobs (id, type, tenant_id, run_id, dedup_key) VALUES (%s, 'recover', %s, %s, %s)",
        (job, ALPHA, run, f"{uuid4()}:{trigger}"),
    )
    async with worker.transaction():
        return await persistence.mint_handle(
            worker, run_id=run, job_id=job, server=Server.WRITE, azp=AZP, fence=await fence_of(app_conn, run)
        )


async def cancel(api: persistence.Conn, run: UUID) -> None:
    """The cancel flag set the way `request_cancel` sets it after a grant (the api's column cells; the route and its
    definer are T21's, `tests/e2e/test_review_live.py`)."""
    async with api.transaction():
        await persistence.set_tenant(api, ALPHA)
        cur = await api.execute(
            "UPDATE app.runs SET cancel_requested = true, cancel_requested_at = now() WHERE run_id = %s", (run,)
        )
        assert cur.rowcount == 1


def aborted(grant: persistence.Grant, token: str, reason: Reason) -> ActionOutcome:
    """The FAILED_NO_COMMIT outcome an ABORTED tombstone with the destination's `token` proves."""
    tombstone = Tombstone(
        action_id=grant.action_id,
        state=DestinationState.ABORTED,
        payload_sha256=grant.payload_sha256,
        reason=token,
        decided_at=datetime.now(UTC),
    )
    return ActionOutcome(
        status=ToolOutcome.FAILED_NO_COMMIT,
        action_id=grant.action_id,
        payload_sha256=grant.payload_sha256,
        receipt=None,
        tombstone=tombstone,
        reason=reason,
    )


def committed(grant: persistence.Grant) -> ActionOutcome:
    receipt = Receipt(receipt_id=uuid4(), incident_id="INC-999001", committed_at=datetime.now(UTC))
    return ActionOutcome(
        status=ToolOutcome.SUCCEEDED,
        action_id=grant.action_id,
        payload_sha256=grant.payload_sha256,
        receipt=receipt,
        tombstone=None,
        reason=None,
    )


async def run_state(app_conn: persistence.Conn, run: UUID) -> tuple[str, str | None]:
    cur = await app_conn.execute("SELECT state, reason FROM app.runs WHERE run_id = %s", (run,))
    row = await cur.fetchone() or {}
    return row["state"], row["reason"]


async def test_past_the_deadline_nothing_is_sent_and_the_abort_says_expired(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """Ruling 17: the grant at t0, the clock 400 s on; mark_sent answers `expired` and writes nothing, the abort
    request records `expired` once, mark_sent then answers `abort_requested`, and the tombstone ends the run FAILED
    with `expired`."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    mcp_exec, harness = await role_conn(Role.MCP_EXEC), await role_conn(Role.TEST_HARNESS)
    _, run, proposal, handle = await approved_run(app_conn, api=api, worker=worker)
    try:
        grant = await persistence.grant_execution(mcp_exec, handle=handle, azp=AZP, proposal_id=proposal)
        try:
            await harness.execute(LATE)
            fresh = await execute_handle(worker, run)
            action = grant.action_id
            assert await persistence.mark_sent(mcp_exec, handle=fresh, azp=AZP, action_id=action) == "expired"
            assert await attempt_states(app_conn, run) == ["INTENT"]  # nothing written, so nothing may be sent
            assert await persistence.request_abort(mcp_exec, handle=fresh, azp=AZP, action_id=action) == "expired"
            assert await persistence.request_abort(mcp_exec, handle=fresh, azp=AZP, action_id=action) == "expired"
            assert await persistence.mark_sent(mcp_exec, handle=fresh, azp=AZP, action_id=action) == "abort_requested"
            assert await attempt_states(app_conn, run) == ["INTENT", "ABORT_REQUESTED"]  # one row for two requests
            standing = await persistence.record_outcome(
                mcp_exec, handle=fresh, azp=AZP, action_id=action, outcome=aborted(grant, "expired", Reason.EXPIRED)
            )
            assert standing is ToolOutcome.FAILED_NO_COMMIT
            assert await persistence.request_abort(mcp_exec, handle=fresh, azp=AZP, action_id=action) == "resolved"
        finally:
            await harness.execute(NOW)
        assert await run_state(app_conn, run) == ("FAILED", "expired")
        assert await attempt_states(app_conn, run) == ["INTENT", "ABORT_REQUESTED", "RESOLVED"]
        cur = await app_conn.execute("SELECT type, source FROM app.events WHERE run_id = %s ORDER BY sequence", (run,))
        assert [(r["type"], r["source"]) for r in await cur.fetchall()][-2:] == [
            ("action.granted", "application"),
            ("action.failed", "destination"),  # no action.dispatched: nothing was ever sent
        ]
    finally:
        await purge_run(app_conn, run)


async def test_a_cancel_comes_first_and_a_sent_attempt_aborts_only_when_due(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """Rulings 3 and 7: no abort is due before a cancel or the deadline (nothing is written); a cancelled INTENT run
    is `cancelled` and `cancelled_before_send` even past the deadline, and a receipt can never be recorded after that
    abort (nothing was sent); a SENT attempt aborts with `deadline` once the deadline passes, and the receipt the abort
    meets is recorded as SUCCEEDED."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    mcp_exec, harness = await role_conn(Role.MCP_EXEC), await role_conn(Role.TEST_HARNESS)
    _, first, first_proposal, first_handle = await approved_run(app_conn, api=api, worker=worker)
    _, second, second_proposal, second_handle = await approved_run(app_conn, api=api, worker=worker)
    try:
        one = await persistence.grant_execution(mcp_exec, handle=first_handle, azp=AZP, proposal_id=first_proposal)
        two = await persistence.grant_execution(mcp_exec, handle=second_handle, azp=AZP, proposal_id=second_proposal)
        with pytest.raises(persistence.Refused) as early:
            await persistence.request_abort(mcp_exec, handle=first_handle, azp=AZP, action_id=one.action_id)
        assert early.value.code == "ABORT_NOT_DUE" and await attempt_states(app_conn, first) == ["INTENT"]
        await cancel(api, first)
        assert await persistence.mark_sent(mcp_exec, handle=second_handle, azp=AZP, action_id=two.action_id) == "sent"
        with pytest.raises(persistence.Refused) as sent_early:
            await persistence.request_abort(mcp_exec, handle=second_handle, azp=AZP, action_id=two.action_id)
        assert sent_early.value.code == "ABORT_NOT_DUE" and await attempt_states(app_conn, second) == ["INTENT", "SENT"]
        try:
            await harness.execute(LATE)
            first_fresh, second_fresh = await execute_handle(worker, first), await execute_handle(worker, second)
            sent = await persistence.mark_sent(mcp_exec, handle=first_fresh, azp=AZP, action_id=one.action_id)
            assert sent == "cancelled"  # the cancel wins over the deadline
            reason = await persistence.request_abort(mcp_exec, handle=first_fresh, azp=AZP, action_id=one.action_id)
            assert reason == "cancelled_before_send"
            with pytest.raises(persistence.VersionConflict):  # an abort before SENT cannot meet a receipt (round 1, M7)
                await persistence.record_outcome(
                    mcp_exec, handle=first_fresh, azp=AZP, action_id=one.action_id, outcome=committed(one)
                )
            reason = await persistence.request_abort(mcp_exec, handle=second_fresh, azp=AZP, action_id=two.action_id)
            assert reason == "deadline"
            standing = await persistence.record_outcome(
                mcp_exec, handle=second_fresh, azp=AZP, action_id=two.action_id, outcome=committed(two)
            )
            assert standing is ToolOutcome.SUCCEEDED  # refused before 0010: the latest state was not SENT
        finally:
            await harness.execute(NOW)
        assert await attempt_states(app_conn, first) == ["INTENT", "ABORT_REQUESTED"]
        assert await attempt_states(app_conn, second) == ["INTENT", "SENT", "ABORT_REQUESTED", "RESOLVED"]
        assert await run_state(app_conn, second) == ("SUCCEEDED", None)
    finally:
        await purge_run(app_conn, first)
        await purge_run(app_conn, second)


async def test_a_re_send_is_checked_as_a_first_send_is(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    """Round 1, I1: an attempt already SENT is re-sent (`already_sent`) only to an execute job, while the run is not
    cancelled and the dispatch deadline has not passed; a recover job gets `not_redispatchable`, a passed deadline
    `expired`, a cancel `cancelled` (first, whatever the clock says), and none of them writes a row."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    mcp_exec, harness = await role_conn(Role.MCP_EXEC), await role_conn(Role.TEST_HARNESS)
    _, run, proposal, handle = await approved_run(app_conn, api=api, worker=worker)
    try:
        grant = await persistence.grant_execution(mcp_exec, handle=handle, azp=AZP, proposal_id=proposal)
        action = grant.action_id
        assert await persistence.mark_sent(mcp_exec, handle=handle, azp=AZP, action_id=action) == "sent"
        assert await persistence.mark_sent(mcp_exec, handle=handle, azp=AZP, action_id=action) == "already_sent"
        recover = await recover_handle(app_conn, worker, run, "timeout")
        answer = await persistence.mark_sent(mcp_exec, handle=recover, azp=AZP, action_id=action)
        assert answer == "not_redispatchable"  # SA:345: a recover job redispatches an unsent attempt only
        try:
            await harness.execute(LATE)
            fresh = await execute_handle(worker, run)  # the first lease lapsed with the clock
            assert await persistence.mark_sent(mcp_exec, handle=fresh, azp=AZP, action_id=action) == "expired"
            await cancel(api, run)
            assert await persistence.mark_sent(mcp_exec, handle=fresh, azp=AZP, action_id=action) == "cancelled"
        finally:
            await harness.execute(NOW)
        assert await attempt_states(app_conn, run) == ["INTENT", "SENT"]  # nothing written by any refusal
        cur = await app_conn.execute("SELECT type FROM app.events WHERE run_id = %s ORDER BY sequence", (run,))
        assert [r["type"] for r in await cur.fetchall()][-2:] == ["action.granted", "action.dispatched"]
    finally:
        await purge_run(app_conn, run)


async def refused(call: Awaitable[object]) -> bool:
    """Whether the call is refused as a handle (OC008): the same answer for every cause, so only that is asserted."""
    try:
        await call
    except persistence.HandleRejected:
        return True
    return False


async def test_every_write_path_definer_compares_the_presented_azp(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """Ruling 12: a handle minted for a renamed worker client. Presented with the old name, each of the five definers
    refuses it (as resolve_invocation always did); presented with its own, each accepts it, which a literal
    `'ops-worker'` inside the function would have refused."""
    api, worker, mcp_exec = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.MCP_EXEC)
    _, run, proposal, _ = await approved_run(app_conn, api=api, worker=worker)
    try:
        cur = await app_conn.execute("SELECT fence FROM app.run_lease WHERE run_id = %s", (run,))
        renamed = "ops-worker-renamed"
        handle = await execute_handle(worker, run, azp=renamed, fence=int((await cur.fetchone() or {})["fence"]))
        resolve = persistence.resolve_invocation
        assert await refused(resolve(mcp_exec, handle=handle, azp=AZP, tool=Tool.CREATE_INCIDENT))
        assert await refused(persistence.grant_execution(mcp_exec, handle=handle, azp=AZP, proposal_id=proposal))
        assert await attempt_states(app_conn, run) == []  # the refused grant wrote nothing
        assert (await resolve(mcp_exec, handle=handle, azp=renamed, tool=Tool.CREATE_INCIDENT)).run_id == run
        grant = await persistence.grant_execution(mcp_exec, handle=handle, azp=renamed, proposal_id=proposal)
        action = grant.action_id
        for wrong in (
            persistence.lookup_action(mcp_exec, handle=handle, azp=AZP),
            persistence.mark_sent(mcp_exec, handle=handle, azp=AZP, action_id=action),
            persistence.request_abort(mcp_exec, handle=handle, azp=AZP, action_id=action),
            persistence.record_outcome(mcp_exec, handle=handle, azp=AZP, action_id=action, outcome=committed(grant)),
        ):
            assert await refused(wrong)
        assert (await persistence.lookup_action(mcp_exec, handle=handle, azp=renamed)).action_id == action
        assert await persistence.mark_sent(mcp_exec, handle=handle, azp=renamed, action_id=action) == "sent"
        with pytest.raises(persistence.Refused):  # resolved, then refused on its own ground: no abort is due
            await persistence.request_abort(mcp_exec, handle=handle, azp=renamed, action_id=action)
        standing = await persistence.record_outcome(
            mcp_exec, handle=handle, azp=renamed, action_id=action, outcome=committed(grant)
        )
        assert standing is ToolOutcome.SUCCEEDED
        assert await attempt_states(app_conn, run) == ["INTENT", "SENT", "RESOLVED"]
    finally:
        await purge_run(app_conn, run)


async def test_an_abort_request_is_bound_to_the_handles_run_and_open_job(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """`request_abort`'s own authority checks: another run's action id is refused OC002 (the definer's
    `g.run_id = v_handle.run_id`), and a handle whose job has finished is refused OC008 (0009's binding, through
    `_resolve_handle`). The same handle with its own run's action is answered in between, so neither refusal is
    vacuous, and neither writes a row."""
    api, worker, mcp_exec = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.MCP_EXEC)
    _, first, first_proposal, first_handle = await approved_run(app_conn, api=api, worker=worker)
    _, second, second_proposal, second_handle = await approved_run(app_conn, api=api, worker=worker)
    try:
        one = await persistence.grant_execution(mcp_exec, handle=first_handle, azp=AZP, proposal_id=first_proposal)
        two = await persistence.grant_execution(mcp_exec, handle=second_handle, azp=AZP, proposal_id=second_proposal)
        await cancel(api, first)
        await cancel(api, second)  # so an abort of the second action would be due, were it the handle's own
        with pytest.raises(persistence.NotFound):
            await persistence.request_abort(mcp_exec, handle=first_handle, azp=AZP, action_id=two.action_id)
        assert await attempt_states(app_conn, second) == ["INTENT"]
        reason = await persistence.request_abort(mcp_exec, handle=first_handle, azp=AZP, action_id=one.action_id)
        assert reason == "cancelled_before_send"  # the positive control: the same handle, its own run's action
        await app_conn.execute("UPDATE app.jobs SET done_at = now() WHERE run_id = %s AND type = 'execute'", (first,))
        finished = await refused(
            persistence.request_abort(mcp_exec, handle=first_handle, azp=AZP, action_id=one.action_id)
        )
        assert finished  # even the repeat that would return the first reason
        assert await attempt_states(app_conn, first) == ["INTENT", "ABORT_REQUESTED"]
    finally:
        await purge_run(app_conn, first)
        await purge_run(app_conn, second)

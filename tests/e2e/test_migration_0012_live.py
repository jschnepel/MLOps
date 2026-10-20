"""Revision 0012 against the per-session test database (OPS_LIVE=1; Plan M rulings 2, 3, 7 and 11): `asset_scope` and
the re-created `search_procedures_scoped` called by their real caller, `mcp_read`.

Catches: `asset_scope` answering another role, another `azp` or a dead handle, returning anything but the handle's run's
asset and interval, or reading the clock somewhere other than the database's (a moved test clock must move `as_of`);
either function answering once the run's requester has lost the active requester membership (R028), or for a run
whose requester was only ever a reader, while `resolve_invocation` still answers (the handle itself is alive: the
refusal is the membership's); a search whose `retrieved_at` is not the database instant it decided permission at;
an excerpt still cut at 500 characters, or one cut at 8000 without saying so; and a downgrade that leaves
`asset_scope` behind, does not restore 0011's search body and grant exactly, or does not come back exactly with the
upgrade.
"""

import importlib.util
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from ops_core import persistence, settings
from ops_core.jobs import Tool
from ops_core.settings import Profile, Role

from tests.e2e.conftest import lease_for, purge_run
from tests.e2e.test_definers_run_path_live import refused
from tests.e2e.test_fenced_definers_live import investigate_job, read_handle
from tests.e2e.test_migration_0011_live import APP_FUNCTIONS, DAY, cleanup, clock, handle_for, stage
from tests.e2e.test_migrations_and_persistence import new_run

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
AZP = "ops-worker"
ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")
ALEX = UUID("2fc05986-c7ec-544c-b628-fdb112bbf18a")  # alpha's requester
LEE = UUID("abcc1200-6791-57ab-87b5-9392d356b512")  # alpha's reader: never a requester
SCOPE = "SELECT * FROM app.asset_scope(%s, %s)"


async def alpha_handle(app_conn: persistence.Conn, role_conn: RoleConn, **run: Any) -> tuple[UUID, str]:
    """A run on the seeded alpha tenant (A17 by default), its lease and a read handle."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    _, _, run_id = await new_run(app_conn, ALPHA, api=api, **run)
    lease = await lease_for(worker, run_id, owner="t16-live", seconds=600)
    return run_id, await read_handle(worker, run_id, await investigate_job(app_conn, run_id), lease)


async def set_active(app_conn: persistence.Conn, subject: UUID, active: bool) -> None:
    """The membership row of a seeded subject in alpha, switched as the sweeper's sync would (R013's pattern)."""
    cur = await app_conn.execute(
        "UPDATE app.memberships SET active = %s WHERE tenant_id = %s AND subject = %s", (active, ALPHA, subject)
    )
    assert cur.rowcount == 1


async def test_asset_scope_is_the_runs_asset_and_interval_at_the_database_clock(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    mcp_read, harness = await role_conn(Role.MCP_READ), await role_conn(Role.TEST_HARNESS)
    run, handle = await alpha_handle(app_conn, role_conn, asset_id="A21")
    try:
        cur = await app_conn.execute("SELECT asset_id, start_at, end_at FROM app.runs WHERE run_id = %s", (run,))
        row = await cur.fetchone() or {}
        scope = await persistence.asset_scope(mcp_read, handle=handle, azp=AZP)
        assert (scope.run_id, scope.tenant_id, scope.asset_id) == (run, ALPHA, "A21")
        assert (scope.start_at, scope.end_at) == (row["start_at"], row["end_at"])
        assert abs((scope.as_of - await clock(app_conn)).total_seconds()) < 5
        try:
            # A day on the database clock: as_of follows it (SA:158). The lease lapsed with the move, so the handle is
            # minted again under a new one.
            await harness.execute("UPDATE app.test_clock SET clock_offset = interval '1 day'")
            worker = await role_conn(Role.WORKER)
            lease = await lease_for(worker, run, owner="t16-later", seconds=600)
            later = await read_handle(worker, run, await investigate_job(app_conn, run), lease)
            moved = await persistence.asset_scope(mcp_read, handle=later, azp=AZP)
            assert timedelta(hours=23) < moved.as_of - scope.as_of < timedelta(hours=25)
        finally:
            await harness.execute("UPDATE app.test_clock SET clock_offset = interval '0'")
    finally:
        await purge_run(app_conn, run)


async def test_only_mcp_read_calls_asset_scope_with_a_live_handle(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    for role in (Role.API, Role.WORKER, Role.SWEEPER, Role.MCP_EXEC, Role.OPERATOR):
        assert await refused(await role_conn(role), SCOPE, ("not-a-handle", AZP)) == "42501", role
    mcp_read = await role_conn(Role.MCP_READ)
    run, handle = await alpha_handle(app_conn, role_conn)
    try:
        assert (await persistence.asset_scope(mcp_read, handle=handle, azp=AZP)).run_id == run  # the control
        for bad_handle, azp in (("not-a-handle", AZP), (handle, "ops-mcp-read")):  # unknown; another workload
            with pytest.raises(persistence.HandleRejected):
                await persistence.asset_scope(mcp_read, handle=bad_handle, azp=azp)
    finally:
        await purge_run(app_conn, run)


async def test_r028_a_requester_who_lost_the_membership_is_refused_at_read_time(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """Ruling 7: the handle stays alive (`resolve_invocation` answers), yet both read definers refuse once ALEX's
    requester membership is inactive, and answer again once it is back; a run requested by a reader never answers."""
    mcp_read = await role_conn(Role.MCP_READ)
    run, handle = await alpha_handle(app_conn, role_conn)
    by_reader, reader_handle = await alpha_handle(app_conn, role_conn, requester=LEE)

    async def search(presented: str) -> persistence.Procedures:
        return await persistence.search_procedures(
            mcp_read, handle=presented, azp=AZP, query="seal", asset_type=None, limit=1
        )

    try:
        await persistence.asset_scope(mcp_read, handle=handle, azp=AZP)
        await search(handle)
        try:
            await set_active(app_conn, ALEX, False)
            invocation = await persistence.resolve_invocation(
                mcp_read, handle=handle, azp=AZP, tool=Tool.GET_ASSET_STATUS
            )
            assert invocation.run_id == run  # the handle is alive: the refusals below are the membership's
            with pytest.raises(persistence.HandleRejected, match="^invocation handle rejected$"):
                await persistence.asset_scope(mcp_read, handle=handle, azp=AZP)
            with pytest.raises(persistence.HandleRejected, match="^invocation handle rejected$"):
                await search(handle)
        finally:
            await set_active(app_conn, ALEX, True)
        assert (await persistence.asset_scope(mcp_read, handle=handle, azp=AZP)).run_id == run
        await search(handle)
        with pytest.raises(persistence.HandleRejected):  # LEE is alpha's reader: no requester row at all
            await persistence.asset_scope(mcp_read, handle=reader_handle, azp=AZP)
        with pytest.raises(persistence.HandleRejected):
            await search(reader_handle)
    finally:
        await purge_run(app_conn, run)
        await purge_run(app_conn, by_reader)


async def test_the_search_returns_its_instant_and_whole_sections(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    mcp_read, harness = await role_conn(Role.MCP_READ), await role_conn(Role.TEST_HARNESS)
    tenant, run, handle = await handle_for(app_conn, role_conn, None)
    try:
        now = await clock(app_conn)
        always = [("approved", now - 30 * DAY, None)]
        short = "turbine " * 75  # 600 characters: Plan D's 500-character cut would have shortened it
        long = "turbine " * 1000 + "x"  # 8001 characters: one over the contract's bound
        await stage(
            app_conn,
            tenant,
            [
                {"id": "SHORT-DOC", "version": "1", "states": always, "text": short},
                {"id": "LONG-DOC", "version": "1", "states": always, "text": long},
            ],
        )
        found = await persistence.search_procedures(
            mcp_read, handle=handle, azp=AZP, query="turbine", asset_type=None, limit=8
        )
        excerpts = {hit.document_id: hit.excerpt for hit in found.results}
        assert excerpts == {"SHORT-DOC": short, "LONG-DOC": long[:8000]}
        assert found.truncated  # the long one was cut, and says so
        assert abs((found.retrieved_at - now).total_seconds()) < 5
        try:
            # Two days on the database clock: retrieved_at is the instant the effectiveness rule ran at, never the
            # wall clock (Plan L final review, M4).
            await harness.execute("UPDATE app.test_clock SET clock_offset = interval '2 days'")
            worker = await role_conn(Role.WORKER)
            lease = await lease_for(worker, run, owner="t16-instant", seconds=600)
            later = await read_handle(worker, run, await investigate_job(app_conn, run), lease)
            moved = await persistence.search_procedures(
                mcp_read, handle=later, azp=AZP, query="turbine", asset_type=None, limit=8
            )
            assert timedelta(hours=47) < moved.retrieved_at - found.retrieved_at < timedelta(hours=49)
        finally:
            await harness.execute("UPDATE app.test_clock SET clock_offset = interval '0'")
    finally:
        await cleanup(app_conn, [run], [tenant])


def revision_0012() -> Any:
    path = Path(__file__).resolve().parents[2] / "migrations" / "app" / "versions" / "0012_asset_scope.py"
    spec = importlib.util.spec_from_file_location("live_rev_0012", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def snapshot(conn: persistence.Conn) -> dict[str, dict[str, Any]]:
    cur = await conn.execute(APP_FUNCTIONS)
    return {row["signature"]: {k: v for k, v in row.items() if k != "signature"} for row in await cur.fetchall()}


async def test_the_round_trip_restores_0011(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    from scripts.skeleton import downgrade, migrate

    module = revision_0012()
    search = f"app.search_procedures_scoped({module.SEARCH_ARGS})"
    superuser = settings.superuser_postgres()
    mcp_read = await role_conn(Role.MCP_READ)
    head = await snapshot(app_conn)
    assert any(s.startswith("app.asset_scope(") for s in head)
    await persistence.assert_function_text(mcp_read, *persistence.ASSET_SCOPE)  # mcp-read starts on the head
    try:
        downgrade("app", superuser, "0011_governed_corpus")
        after = await snapshot(app_conn)
        assert not any(s.startswith("app.asset_scope(") for s in after)
        cur = await app_conn.execute("SELECT prosrc FROM pg_proc WHERE oid = %s::regprocedure", (search,))
        assert (await cur.fetchone() or {})["prosrc"] == module.REV0011.SEARCH_PROCEDURES_SCOPED.split("$fn$")[1]
        assert set(after) == {s for s in head if not s.startswith("app.asset_scope(")}
        for signature, details in after.items():
            if signature.startswith("app.search_procedures_scoped("):  # regprocedure text: no spaces
                assert details["acl"] == head[signature]["acl"]  # REVOKE PUBLIC, EXECUTE to mcp_read, as before
            else:
                assert details == head[signature], signature  # nothing else moved
        with pytest.raises(persistence.PersistenceError, match="predates this service"):
            await persistence.assert_function_text(mcp_read, *persistence.ASSET_SCOPE)  # mcp-read refuses 0011
    finally:
        assert migrate(Profile.TEST) == 0  # every later test needs the head
    assert await snapshot(app_conn) == head
    scope_unknown = await refused(mcp_read, SCOPE, (str(uuid4()), AZP))
    assert scope_unknown == "OC008"  # back, and still the one handle refusal

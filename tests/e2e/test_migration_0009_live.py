"""Revision 0009 against the per-session test database (OPS_LIVE=1; Plan J rulings 6 and 18).

Catches: a downgrade that leaves the bound `_resolve_handle` behind or restores it differently from a database that
never saw 0009 (or an upgrade that does not bring the bound body back); mcp-read's startup check passing on a
database at 0008; a handle whose job the superuser points at another run's job, or whose job is finished, still
resolving at the definer; and a resolution that ignores the run's state (an investigate handle once its run awaits
input), while the definer itself still answers for that run.
"""

import importlib.util
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from ops_core import persistence, settings
from ops_core.settings import Profile, Role
from ops_core.states import RunState
from ops_mcp_read.server import HANDLE_BINDING
from psycopg import sql
from psycopg.rows import dict_row

from tests.e2e.conftest import lease_for, purge_run, purge_tenant
from tests.e2e.test_definers_run_path_live import refused
from tests.e2e.test_fenced_definers_live import investigate_job, read_handle, resolve
from tests.e2e.test_migration_0007_live import FUNCTION_DETAILS, LEFTOVERS
from tests.e2e.test_migrations_and_persistence import new_run

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "app" / "versions"
SIGNATURE, MARKER = HANDLE_BINDING
RESOLVE = "SELECT * FROM app.resolve_invocation(%s, 'ops-worker')"
SCRATCH_PREFIX = "r008_"  # every scratch database this module creates; leftovers are dropped by prefix


def revision_0007() -> Any:
    """Revision 0007 loaded by path, for the `_resolve_handle` body 0009's downgrade restores."""
    spec = importlib.util.spec_from_file_location("live_rev_0007_j", VERSIONS / "0007_leases_fences.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def built_to_0008(superuser: settings.Postgres) -> dict[str, Any]:
    """`_resolve_handle`'s details as a database built straight to 0008 holds them (the 0007 module's pattern): a
    scratch database is created, upgraded by the applied revisions alone, read and dropped."""
    from scripts.skeleton import upgrade

    scratch = f"{SCRATCH_PREFIX}{uuid4().hex[:12]}"
    try:
        with psycopg.connect(superuser.conninfo(), autocommit=True, row_factory=dict_row) as admin:
            for row in admin.execute(LEFTOVERS, (SCRATCH_PREFIX,)).fetchall():
                admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(row["datname"])))
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(scratch)))
        target = settings.Postgres(superuser.host, superuser.port, superuser.user, scratch, superuser.password)
        upgrade("app", target, "0008_journal_outbox")
        with psycopg.connect(target.conninfo(), row_factory=dict_row) as conn:
            return dict(conn.execute(FUNCTION_DETAILS, (SIGNATURE,)).fetchone() or {})
    finally:
        with psycopg.connect(superuser.conninfo(), autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(scratch)))


async def details(conn: persistence.Conn) -> dict[str, Any]:
    cur = await conn.execute(FUNCTION_DETAILS, (SIGNATURE,))
    return dict(await cur.fetchone() or {})


async def test_the_round_trip_restores_0008(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    from scripts.skeleton import downgrade, migrate

    superuser = settings.superuser_postgres()
    mcp_read = await role_conn(Role.MCP_READ)
    head = await details(app_conn)
    assert MARKER in head["body"]
    await persistence.assert_function_text(mcp_read, SIGNATURE, MARKER)  # mcp-read starts on the head
    try:
        downgrade("app", superuser, "0008_journal_outbox")
        # The restored body is 0007's text exactly (its stored source is what lies between the dollar quotes), and its
        # definition, ACL, owner and settings are what a database that never saw 0009 holds.
        cur = await app_conn.execute("SELECT prosrc FROM pg_proc WHERE oid = %s::regprocedure", (SIGNATURE,))
        assert (await cur.fetchone())["prosrc"] == revision_0007().RESOLVE_HANDLE.split("$fn$")[1]
        assert await details(app_conn) == built_to_0008(superuser)
        with pytest.raises(persistence.PersistenceError, match="predates this service"):
            await persistence.assert_function_text(mcp_read, SIGNATURE, MARKER)  # mcp-read refuses 0008
    finally:
        assert migrate(Profile.TEST) == 0  # every later test needs the head
    assert await details(app_conn) == head  # the upgrade brings back exactly what the downgrade took


async def test_a_handle_resolves_only_for_its_own_runs_open_job(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """Ruling 6: the superuser (or a compromised worker; invocation_context has no RLS) points the handle's job at
    another run's job, then finishes the handle's own job; the definer refuses both, and the same handle resolves
    again in between, so each refusal is the binding's."""
    api, worker, mcp_read = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.MCP_READ)
    tenant, _, run = await new_run(app_conn, api=api)
    _, _, other = await new_run(app_conn, tenant, api=api)  # a second conversation and run in the same tenant
    try:
        job, other_job = await investigate_job(app_conn, run), await investigate_job(app_conn, other)
        handle = await read_handle(worker, run, job, await lease_for(worker, run))
        hashed = persistence.handle_hash(handle)
        assert (await resolve(mcp_read, handle)).job_id == job
        await app_conn.execute(
            "UPDATE app.invocation_context SET job_id = %s WHERE handle_sha256 = %s", (other_job, hashed)
        )
        assert await refused(mcp_read, RESOLVE, (handle,)) == "OC008"  # another run's job
        await app_conn.execute("UPDATE app.invocation_context SET job_id = %s WHERE handle_sha256 = %s", (job, hashed))
        assert (await resolve(mcp_read, handle)).job_id == job  # its own job again: resolves
        await app_conn.execute("UPDATE app.jobs SET done_at = app.current_time() WHERE id = %s", (job,))
        assert await refused(mcp_read, RESOLVE, (handle,)) == "OC008"  # its job finished
    finally:
        await purge_run(app_conn, run)
        await purge_run(app_conn, other)
        await purge_tenant(app_conn, tenant)


async def test_the_allowlist_follows_the_run_state(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    """Ruling 6: an investigate handle is honoured while its run is QUEUED or RETRIEVING (where the worker calls
    mcp-read) and refused once the run awaits input, though the definer still resolves it: the run-state rule is
    Python's (erratum 19)."""
    api, worker, mcp_read = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.MCP_READ)
    tenant, _, run = await new_run(app_conn, api=api)
    try:
        handle = await read_handle(worker, run, await investigate_job(app_conn, run), await lease_for(worker, run))
        assert (await resolve(mcp_read, handle)).run_state is RunState.QUEUED
        async with worker.transaction():  # the worker role's own function, as tests/e2e/test_admission_live.py does
            await worker.execute("SELECT app.transition_run(%s, 'QUEUED', 'RETRIEVING', NULL, 1, '{}')", (run,))
        assert (await resolve(mcp_read, handle)).run_state is RunState.RETRIEVING
        async with worker.transaction():
            await worker.execute("SELECT app.transition_run(%s, 'RETRIEVING', 'AWAITING_INPUT', NULL, 2, '{}')", (run,))
        cur = await mcp_read.execute(RESOLVE, (handle,))
        assert (await cur.fetchone())["run_state"] == "AWAITING_INPUT"  # the definer answers ...
        with pytest.raises(persistence.HandleRejected):  # ... and the allowlist refuses
            await resolve(mcp_read, handle)
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)

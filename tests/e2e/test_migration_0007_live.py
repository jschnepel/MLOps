"""Revision 0007 against the per-session test database (OPS_LIVE=1; Plan H rulings 1, 12, 13, 15, 27, 31).

Catches: a downgrade that leaves the permit, the CHECK, the definer's fence cell or the new function behind (or an
upgrade that does not bring them back), a permit another role can read or a second worker can take while it is held,
an unknown job type accepted, an `app_definer` that cannot take the asset guard's advisory lock (T21's gate would
fail closed for everyone), and a global queue count that misses a tenant, answers a role other than `api`, or leaves
the caller's tenant setting changed.
"""

import importlib.util
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from ops_core import persistence, settings
from ops_core.settings import Profile, Role
from psycopg import sql
from psycopg.rows import dict_row

from tests.e2e.conftest import purge_run, purge_tenant
from tests.e2e.test_migrations_and_persistence import new_run

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")
TAKE_PERMIT = (
    "UPDATE app.model_permit SET holder = %s, leased_until = app.current_time() + interval '65 seconds'"
    " WHERE slot = (SELECT slot FROM app.model_permit WHERE leased_until <= app.current_time()"
    " ORDER BY slot FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING slot"
)
FREE_PERMIT = "UPDATE app.model_permit SET holder = NULL, leased_until = '-infinity' WHERE slot = 1"
VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "app" / "versions"
FUNCTION_DETAILS = (
    "SELECT pg_get_functiondef(p.oid) AS body, p.proacl::text AS acl, p.proowner::regrole::text AS owner,"
    " p.proconfig::text AS config FROM pg_proc p WHERE p.oid = %s::regprocedure"
)
SCRATCH_PREFIX = "r006_"  # every scratch database this module creates; leftovers are dropped by prefix
# Leftovers no session is connected to: a concurrent session's scratch database in use is never touched.
LEFTOVERS = (
    "SELECT d.datname FROM pg_database d WHERE starts_with(d.datname, %s)"
    " AND NOT EXISTS (SELECT 1 FROM pg_stat_activity a WHERE a.datname = d.datname)"
)


def revision_0007() -> Any:
    """Revision 0007 loaded by path, for the bodies its downgrade restores."""
    spec = importlib.util.spec_from_file_location("live_rev_0007", VERSIONS / "0007_leases_fences.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def built_to_0006(superuser: settings.Postgres, signatures: list[str]) -> dict[str, dict[str, Any]]:
    """The functions named, as a database built straight to 0006 holds them (review round 1, M3): definition, ACL,
    owner and settings. A scratch database is created, upgraded to 0006 by the applied revisions alone, read and
    dropped; the roles are cluster-wide, so its ACLs name the same roles as the test database's. A run killed before
    its `finally` leaves a database behind; the next run drops every leftover with the prefix first (review round 2,
    m6)."""
    from scripts.skeleton import upgrade

    scratch = f"{SCRATCH_PREFIX}{uuid4().hex[:12]}"
    try:
        with psycopg.connect(superuser.conninfo(), autocommit=True, row_factory=dict_row) as admin:
            for row in admin.execute(LEFTOVERS, (SCRATCH_PREFIX,)).fetchall():
                admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(row["datname"])))
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(scratch)))
        target = settings.Postgres(superuser.host, superuser.port, superuser.user, scratch, superuser.password)
        upgrade("app", target, "0006_admission_idempotency")
        with psycopg.connect(target.conninfo(), row_factory=dict_row) as conn:
            return {name: dict(conn.execute(FUNCTION_DETAILS, (name,)).fetchone() or {}) for name in signatures}
    finally:
        with psycopg.connect(superuser.conninfo(), autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(scratch)))


async def exists(conn: persistence.Conn, signature: str) -> bool:
    cur = await conn.execute("SELECT to_regprocedure(%s) IS NOT NULL AS present", (signature,))
    return bool((await cur.fetchone())["present"])


async def snapshot(conn: persistence.Conn) -> dict[str, Any]:
    """What revision 0007 changes, as comparable values: every app function's definition, run_lease's column cells,
    the jobs constraints and whether the permit table exists."""
    cur = await conn.execute(
        "SELECT p.oid::regprocedure::text AS signature, pg_get_functiondef(p.oid) AS body FROM pg_proc p"
        " JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'app' ORDER BY 1"
    )
    functions = {row["signature"]: row["body"] for row in await cur.fetchall()}
    cur = await conn.execute(
        "SELECT grantee, privilege_type, column_name FROM information_schema.column_privileges"
        " WHERE table_schema = 'app' AND table_name = 'run_lease' ORDER BY 1, 2, 3"
    )
    cells = [(row["grantee"], row["privilege_type"], row["column_name"]) for row in await cur.fetchall()]
    cur = await conn.execute("SELECT conname FROM pg_constraint WHERE conrelid = 'app.jobs'::regclass ORDER BY 1")
    constraints = [row["conname"] for row in await cur.fetchall()]
    cur = await conn.execute("SELECT to_regclass('app.model_permit') IS NOT NULL AS present")
    permit = bool((await cur.fetchone())["present"])
    return {"functions": functions, "lease_cells": cells, "job_constraints": constraints, "permit": permit}


async def test_the_round_trip_restores_0006(app_conn: persistence.Conn) -> None:
    from scripts.skeleton import downgrade, migrate

    superuser = settings.superuser_postgres()
    head = await snapshot(app_conn)
    assert head["permit"] and "jobs_type_check" in head["job_constraints"]
    assert ("app_definer", "UPDATE", "fence") in head["lease_cells"]
    try:
        downgrade("app", superuser, "0006_admission_idempotency")
        before = await snapshot(app_conn)
        assert not before["permit"] and "jobs_type_check" not in before["job_constraints"]
        assert ("app_definer", "UPDATE", "fence") not in before["lease_cells"]
        assert not await exists(app_conn, "app.queued_runs_total()")
        assert await exists(app_conn, "app.mark_sent(uuid)") and not await exists(app_conn, "app.mark_sent(text, uuid)")
        # Every function 0007 replaced is back exactly as the applied revision installed it (R006, ruling 31): the
        # stored source is the text between the body's dollar quotes.
        for name, args, _, body in revision_0007().RESTORED:
            cur = await app_conn.execute(
                "SELECT prosrc FROM pg_proc WHERE oid = %s::regprocedure", (f"app.{name}({args})",)
            )
            assert (await cur.fetchone())["prosrc"] == body.split("$fn$")[1], name
        # ...and so are their definitions, ACLs, owners and settings, against a database that never saw 0007.
        restored = [f"app.{name}({args})" for name, args, _, _ in revision_0007().RESTORED]
        reference = built_to_0006(superuser, restored)
        for signature in restored:
            cur = await app_conn.execute(FUNCTION_DETAILS, (signature,))
            assert dict(await cur.fetchone()) == reference[signature], signature
    finally:
        assert migrate(Profile.TEST) == 0  # every later test needs the head
    assert await snapshot(app_conn) == head  # the upgrade brings back exactly what the downgrade took
    # The head's signature: revision 0010 replaced 0007's with one that takes the token's azp (T47).
    assert await exists(app_conn, "app.mark_sent(text, text, uuid)")
    assert not await exists(app_conn, "app.mark_sent(uuid)") and not await exists(app_conn, "app.mark_sent(text, uuid)")


async def test_model_permit_is_seeded_and_only_the_worker_takes_it(role_conn: RoleConn) -> None:
    worker, other = await role_conn(Role.WORKER), await role_conn(Role.WORKER)
    api, sweeper = await role_conn(Role.API), await role_conn(Role.SWEEPER)
    cur = await worker.execute(TAKE_PERMIT, ("live-a",))
    assert [row["slot"] for row in await cur.fetchall()] == [1]  # one seeded slot: model concurrency 1 (BS:549)
    try:
        cur = await other.execute(TAKE_PERMIT, ("live-b",))
        assert await cur.fetchall() == []  # held: the second taker gets nothing, at once
        for conn in (api, sweeper):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                await conn.execute("SELECT slot FROM app.model_permit")
    finally:
        await worker.execute(FREE_PERMIT)
    cur = await other.execute(TAKE_PERMIT, ("live-b",))
    assert [row["slot"] for row in await cur.fetchall()] == [1]  # freed: the next worker takes it
    await other.execute(FREE_PERMIT)


async def test_the_job_type_check_refuses_an_unknown_type(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    tenant, _, run = await new_run(app_conn, api=await role_conn(Role.API))
    try:
        with pytest.raises(psycopg.errors.CheckViolation):
            await app_conn.execute(
                "INSERT INTO app.jobs (id, type, tenant_id, run_id, dedup_key)"
                " VALUES (gen_random_uuid(), 'bogus', %s, %s, %s)",
                (tenant, run, f"bogus-{uuid4()}"),
            )
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


async def test_app_definer_may_take_the_asset_guard_lock(app_conn: persistence.Conn) -> None:
    """T13 review note 5 (ruling 15): a definer owned by app_definer takes SA:189's one-key advisory lock. The probe
    is created and dropped by the rollback, so no catalog test ever sees it."""
    probe = (
        "CREATE FUNCTION app._advisory_probe(p_key text) RETURNS text"
        " LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp AS $probe$"
        " BEGIN PERFORM pg_advisory_xact_lock(hashtextextended(p_key, 0)); RETURN current_user; END $probe$"
    )
    async with app_conn.transaction(force_rollback=True):
        await app_conn.execute(probe)
        await app_conn.execute("ALTER FUNCTION app._advisory_probe(text) OWNER TO app_definer")
        cur = await app_conn.execute("SELECT app._advisory_probe(%s) AS who", (f"{ALPHA}:A17",))
        assert (await cur.fetchone())["who"] == "app_definer"
        cur = await app_conn.execute(
            "SELECT count(*) AS n FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid()"
            " AND granted AND objsubid = 1"  # objsubid 1: the one-key (bigint) space, apart from erratum 37's two-key
        )
        assert (await cur.fetchone())["n"] == 1


async def test_queued_runs_total_counts_every_tenant_for_api_only(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    made = [await new_run(app_conn, api=api) for _ in range(2)]  # two fresh tenants, one QUEUED run each
    try:
        cur = await app_conn.execute("SELECT count(*) AS n FROM app.runs WHERE state = 'QUEUED'")
        everyone = (await cur.fetchone())["n"]
        async with api.transaction():
            await persistence.set_tenant(api, made[0][0])
            cur = await api.execute("SELECT app.queued_runs_total() AS n")
            assert (await cur.fetchone())["n"] == everyone >= 2  # every tenant, not only the caller's
            cur = await api.execute("SELECT current_setting('app.tenant_id', true) AS t")
            assert (await cur.fetchone())["t"] == str(made[0][0])  # the caller's tenant is back after the call
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await worker.execute("SELECT app.queued_runs_total()")
    finally:
        for tenant, _, run in made:
            await purge_run(app_conn, run)
            await purge_tenant(app_conn, tenant)

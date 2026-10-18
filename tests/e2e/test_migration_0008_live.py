"""Revision 0008 against the per-session test database (OPS_LIVE=1; Plan I rulings 4, 12, 13, 20, 27, 29).

Catches: a downgrade that leaves the outbox, the sweeper's DELETE on jobs, its purge policy or the new `_append_event`
body behind, or that restores a `jobs` cell (table or column) or the 0003 body differently from a database that never
saw 0008 (or an upgrade that does not bring them back); a payload rule the SQL enforces differently from the schema
and the Python twin (the same table of cases, tests/plan_i/event_cases.py); an intent written for an event that needs
none, written twice for one run and type, or written with someone other than the requester; an outbox an api or
worker connection can write, a sweeper can read across tenants or delete from; a sweeper DELETE that reaches a run's
job; and a function either MCP server may call, in any overload, that inserts a job (T14 review note 1: recover jobs
are never created by an MCP server).
"""

import importlib.util
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from ops_core import persistence, settings
from ops_core.outcomes import EventType
from ops_core.settings import Profile, Role
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from tests.e2e.conftest import purge_run, purge_tenant
from tests.e2e.test_migration_0007_live import FUNCTION_DETAILS, LEFTOVERS
from tests.e2e.test_migrations_and_persistence import ALEX, new_run
from tests.plan_i.event_cases import CASES

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
APPEND = "SELECT * FROM app._append_event(%s, %s, %s, %s, %s)"
FAILED = {"action_id": str(uuid4()), "reason": "expired"}
# Any statement that adds a row to app.jobs, whatever the spacing or schema prefix.
INSERTS_A_JOB = re.compile(r"INSERT\s+INTO\s+(app\.)?jobs\b", re.IGNORECASE)
CALLS = re.compile(r"app\.(\w+)\(")
VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "app" / "versions"
APPEND_SIGNATURE = "app._append_event(uuid,uuid,text,text,jsonb)"
# Every table and column cell on jobs and outbox: a column-level UPDATE cell 0008's REVOKE ALL and re-grant could
# drop is compared too (round 1, I5).
CELLS = (
    "SELECT grantee, table_name, privilege_type, NULL AS column_name FROM information_schema.role_table_grants"
    " WHERE table_schema = 'app' AND table_name IN ('jobs', 'outbox')"
    " UNION ALL SELECT grantee, table_name, privilege_type, column_name FROM information_schema.column_privileges"
    " WHERE table_schema = 'app' AND table_name IN ('jobs', 'outbox') ORDER BY 1, 2, 3, 4"
)
POLICIES = "SELECT tablename, policyname FROM pg_policies WHERE schemaname = 'app' AND tablename IN ('jobs', 'outbox')"
SCRATCH_PREFIX = "r007_"  # every scratch database this module creates; leftovers are dropped by prefix


def revision_0003() -> Any:
    """Revision 0003 loaded by path, for the `_append_event` body 0008's downgrade restores."""
    spec = importlib.util.spec_from_file_location("live_rev_0003", VERSIONS / "0003_run_path_functions.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def built_to_0007(superuser: settings.Postgres) -> dict[str, Any]:
    """`_append_event`'s details and the jobs and outbox cells as a database built straight to 0007 holds them (the
    0007 module's pattern): a scratch database is created, upgraded by the applied revisions alone, read and dropped."""
    from scripts.skeleton import upgrade

    scratch = f"{SCRATCH_PREFIX}{uuid4().hex[:12]}"
    try:
        with psycopg.connect(superuser.conninfo(), autocommit=True, row_factory=dict_row) as admin:
            for row in admin.execute(LEFTOVERS, (SCRATCH_PREFIX,)).fetchall():
                admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(row["datname"])))
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(scratch)))
        target = settings.Postgres(superuser.host, superuser.port, superuser.user, scratch, superuser.password)
        upgrade("app", target, "0007_leases_fences")
        with psycopg.connect(target.conninfo(), row_factory=dict_row) as conn:
            details = dict(conn.execute(FUNCTION_DETAILS, (APPEND_SIGNATURE,)).fetchone() or {})
            cells = [tuple(row.values()) for row in conn.execute(CELLS).fetchall()]
            return {"append": details, "cells": cells}
    finally:
        with psycopg.connect(superuser.conninfo(), autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(scratch)))


async def snapshot(conn: persistence.Conn) -> dict[str, Any]:
    """What revision 0008 changes, as comparable values: every app function's definition, the jobs and outbox cells
    (table and column), their policies and whether the outbox exists."""
    cur = await conn.execute(
        "SELECT p.oid::regprocedure::text AS signature, pg_get_functiondef(p.oid) AS body FROM pg_proc p"
        " JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'app' ORDER BY 1"
    )
    functions = {row["signature"]: row["body"] for row in await cur.fetchall()}
    cur = await conn.execute(CELLS)
    cells = [tuple(row.values()) for row in await cur.fetchall()]
    cur = await conn.execute(POLICIES)
    policies = sorted((row["tablename"], row["policyname"]) for row in await cur.fetchall())
    cur = await conn.execute("SELECT to_regclass('app.outbox') IS NOT NULL AS present")
    outbox = bool((await cur.fetchone())["present"])
    return {"functions": functions, "cells": cells, "policies": policies, "outbox": outbox}


async def test_the_round_trip_restores_0007(app_conn: persistence.Conn) -> None:
    from scripts.skeleton import downgrade, migrate

    superuser = settings.superuser_postgres()
    head = await snapshot(app_conn)
    assert head["outbox"] and ("outbox", "tenant_isolation") in head["policies"]
    assert ("jobs", "sweeper_purge_maintenance") in head["policies"]
    assert ("sweeper", "jobs", "DELETE", None) in head["cells"]
    try:
        downgrade("app", superuser, "0007_leases_fences")
        before = await snapshot(app_conn)
        assert not before["outbox"] and ("jobs", "sweeper_purge_maintenance") not in before["policies"]
        # The restored body is 0003's text exactly (its stored source is what lies between the dollar quotes), and
        # its definition, ACL, owner and settings and every jobs cell, table and column, are what a database that
        # never saw 0008 holds (round 1, I5).
        cur = await app_conn.execute("SELECT prosrc FROM pg_proc WHERE oid = %s::regprocedure", (APPEND_SIGNATURE,))
        assert (await cur.fetchone())["prosrc"] == revision_0003().APPEND_EVENT_HELPER.split("$fn$")[1]
        reference = built_to_0007(superuser)
        cur = await app_conn.execute(FUNCTION_DETAILS, (APPEND_SIGNATURE,))
        assert dict(await cur.fetchone()) == reference["append"]
        assert before["cells"] == reference["cells"]
    finally:
        assert migrate(Profile.TEST) == 0  # every later test needs the head
    assert await snapshot(app_conn) == head  # the upgrade brings back exactly what the downgrade took


async def verdict(conn: persistence.Conn, tenant: UUID, run: UUID, case_type: str, source: str, payload: Any) -> str:
    """'ok', or the SQLSTATE `_append_event` refused with; rolled back either way."""
    try:
        async with conn.transaction(force_rollback=True):
            await conn.execute(APPEND, (tenant, run, case_type, source, Jsonb(payload)))
    except psycopg.Error as exc:
        return str(exc.sqlstate)
    return "ok"


async def test_the_sql_gives_every_tabled_verdict(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    """Ruling 4: the schema, the Python twin (tests/plan_i/test_event_rules.py) and the SQL agree on one table."""
    tenant, _, run = await new_run(app_conn, api=await role_conn(Role.API))
    try:
        wrong = [
            (case.name, got)
            for case in CASES
            if (got := await verdict(app_conn, tenant, run, case.type, case.source, case.payload))
            != ("ok" if case.ok else "OC006")
        ]
        assert wrong == []
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


async def outbox_rows(conn: persistence.Conn, run: UUID) -> list[dict[str, Any]]:
    cur = await conn.execute(
        "SELECT o.event_id, e.type, o.channel, o.recipient, o.dedup_key, o.attempts, o.result, o.delivered_at,"
        " o.leased_until = '-infinity' AS due FROM app.outbox o JOIN app.events e ON e.event_id = o.event_id"
        " WHERE o.run_id = %s ORDER BY o.created_at",
        (run,),
    )
    return [dict(row) for row in await cur.fetchall()]


async def test_the_intent_commits_with_its_event_once_per_run_and_type(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """Rulings 12-13 (BS:524, R024's SQL half): an outcome event writes one intent addressed to the requester in its
    own transaction; a replay adds an event but no second intent; other events and a rollback write none."""
    api = await role_conn(Role.API)
    tenant, _, run = await new_run(app_conn, api=api)
    try:
        async with app_conn.transaction(force_rollback=True):  # the event and its intent leave together
            await app_conn.execute(APPEND, (tenant, run, "action.failed", "destination", Jsonb(FAILED)))
            assert len(await outbox_rows(app_conn, run)) == 1
        assert await outbox_rows(app_conn, run) == []
        cur = await app_conn.execute(APPEND, (tenant, run, "action.failed", "destination", Jsonb(FAILED)))
        first = (await cur.fetchone())["event_id"]
        await app_conn.execute(APPEND, (tenant, run, "action.failed", "destination", Jsonb(FAILED)))  # a replay
        await persistence.append_event(api, run_id=run, type=EventType.TOOL_STARTED, payload={})  # no intent
        await app_conn.execute(
            APPEND, (tenant, run, "notification.failed", "application", Jsonb({"code": "x", "message": "m"}))
        )
        rows = await outbox_rows(app_conn, run)
        assert rows == [
            {
                "event_id": first,
                "type": "action.failed",
                "channel": "local",
                "recipient": ALEX,
                "dedup_key": f"{run}:action.failed:local:{ALEX}",
                "attempts": 0,
                "result": None,
                "delivered_at": None,
                "due": True,
            }
        ]
        cur = await app_conn.execute("SELECT count(*) AS n FROM app.events WHERE run_id = %s", (run,))
        assert (await cur.fetchone())["n"] == 5  # run.accepted, two action.failed, tool.started, notification.failed
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


async def test_the_outbox_is_written_by_the_definer_and_read_per_tenant(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """Erratum 60 and SA:520: no runtime role inserts intent; the sweeper sees a tenant's rows only under that
    tenant's setting, may update its four columns and may not delete."""
    tenant, _, run = await new_run(app_conn, api=await role_conn(Role.API))
    try:
        await app_conn.execute(APPEND, (tenant, run, "action.failed", "destination", Jsonb(FAILED)))
        cur = await app_conn.execute("SELECT event_id FROM app.outbox WHERE run_id = %s", (run,))
        event = (await cur.fetchone())["event_id"]
        insert = (
            "INSERT INTO app.outbox (outbox_id, tenant_id, run_id, event_id, channel, recipient, dedup_key)"
            " VALUES (gen_random_uuid(), %s, %s, %s, 'local', 'r', %s)"
        )
        for role in (Role.API, Role.WORKER, Role.SWEEPER, Role.MCP_EXEC):
            conn = await role_conn(role)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                await conn.execute(insert, (tenant, run, event, f"forged-{uuid4()}"))
        sweeper = await role_conn(Role.SWEEPER)
        cur = await sweeper.execute("SELECT count(*) AS n FROM app.outbox WHERE run_id = %s", (run,))
        assert (await cur.fetchone())["n"] == 0  # no tenant set: tenant_isolation admits nothing, no sweeper_all
        async with sweeper.transaction():
            await persistence.set_tenant(sweeper, tenant)
            cur = await sweeper.execute(
                "UPDATE app.outbox SET result = 'retrying', attempts = attempts + 1 WHERE run_id = %s", (run,)
            )
            assert cur.rowcount == 1
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await sweeper.execute("DELETE FROM app.outbox WHERE run_id = %s", (run,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await sweeper.execute("UPDATE app.outbox SET recipient = 'x' WHERE run_id = %s", (run,))
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


async def test_no_function_an_mcp_server_may_call_inserts_a_job(app_conn: persistence.Conn) -> None:
    """T14 review note 1 (ruling 27): every function mcp_read or mcp_exec may execute, and every app function those
    call, transitively, is free of an INSERT into jobs; and neither role holds a table grant (SA:437)."""
    cur = await app_conn.execute(
        "SELECT p.oid, p.proname AS name, pg_get_functiondef(p.oid) AS body,"
        " has_function_privilege('mcp_read', p.oid, 'EXECUTE') AS by_read,"
        " has_function_privilege('mcp_exec', p.oid, 'EXECUTE') AS by_exec"
        " FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'app'"
    )
    rows = await cur.fetchall()
    # Keyed by OID, so every overload's body is scanned; a call by name reaches every overload of that name (M9).
    bodies = {row["oid"]: row["body"] for row in rows}
    by_name: dict[str, set[int]] = {}
    for row in rows:
        by_name.setdefault(row["name"], set()).add(row["oid"])
    names = {row["oid"]: row["name"] for row in rows}
    reachable = {row["oid"] for row in rows if row["by_read"] or row["by_exec"]}
    entry = {names[oid] for oid in reachable}
    assert {"resolve_invocation", "grant_execution", "mark_sent", "record_outcome", "lookup_action"} <= entry
    frontier = set(reachable)
    while frontier:  # the helpers they call, and the helpers those call
        called = {name for oid in frontier for name in CALLS.findall(bodies[oid])}
        frontier = {oid for name in called for oid in by_name.get(name, set())} - reachable
        reachable |= frontier
    # The helpers the write path reaches today; a new one is checked automatically, a vanished one fails here.
    assert {"_authority", "_resolve_handle", "_transition", "_append_event", "_latest_attempt", "_grant_row"} <= {
        names[oid] for oid in reachable
    }
    assert sorted(names[oid] for oid in reachable if INSERTS_A_JOB.search(bodies[oid])) == []
    cur = await app_conn.execute(
        "SELECT count(*) AS n FROM information_schema.role_table_grants"
        " WHERE grantee IN ('mcp_read', 'mcp_exec') AND table_schema = 'app'"
    )
    assert (await cur.fetchone())["n"] == 0


async def test_the_sweeper_may_delete_finished_maintenance_rows_only(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """Round 1, I6 (erratum 61): the restrictive policy keeps the sweeper's DELETE on jobs to finished maintenance
    rows, whatever the statement says; sweeper_all alone would admit every tenant's run jobs."""
    sweeper = await role_conn(Role.SWEEPER)
    tenant, _, run = await new_run(app_conn, api=await role_conn(Role.API))
    keys = {name: f"sync_memberships:t14-policy-{name}-{uuid4()}" for name in ("done", "open")}
    try:
        await app_conn.execute(
            "UPDATE app.jobs SET done_at = app.current_time() - interval '30 hours' WHERE run_id = %s", (run,)
        )
        for name, done in (("done", "1 hour"), ("open", None)):
            await app_conn.execute(
                "INSERT INTO app.jobs (id, type, dedup_key, available_at, done_at)"
                " VALUES (gen_random_uuid(), 'sync_memberships', %s, app.current_time(),"
                " app.current_time() - %s::interval)",
                (keys[name], done),
            )
        cur = await sweeper.execute("DELETE FROM app.jobs WHERE run_id = %s", (run,))
        assert cur.rowcount == 0  # a run's finished job: invisible to the DELETE
        cur = await sweeper.execute("DELETE FROM app.jobs WHERE dedup_key = %s", (keys["open"],))
        assert cur.rowcount == 0  # an unfinished maintenance row: likewise
        cur = await sweeper.execute("DELETE FROM app.jobs WHERE dedup_key = %s", (keys["done"],))
        assert cur.rowcount == 1
        cur = await app_conn.execute("SELECT count(*) AS n FROM app.jobs WHERE run_id = %s", (run,))
        assert (await cur.fetchone())["n"] == 1
    finally:
        await app_conn.execute("DELETE FROM app.jobs WHERE dedup_key = ANY(%s)", (list(keys.values()),))
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)

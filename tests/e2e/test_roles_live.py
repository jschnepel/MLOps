"""Roles, grants and RLS against the per-session test database (OPS_LIVE=1): the catalogs enumerated against
ops_core.privileges (R124), function-only roles denied every SELECT (R084), direct writes to audit and state denied
(R128), tenant isolation through the policy for a runtime role (R007), no residual context on a reused connection
(R008), composite keys refusing cross-tenant children (R009), and the policy text per table (R106).

Catches: a grant the matrix does not list (or one it lists that the migration forgot), a policy with the bare
`::uuid` cast (spike §2), an owner that is not migrator, a definer role that owns a table, a table-level UPDATE
where only columns were meant, and a FOR UPDATE lock that a function-only role could take.
"""

from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

import psycopg
import pytest
from ops_core import persistence
from ops_core import privileges as p
from ops_core.settings import Role

from tests.e2e.conftest import purge_run

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")
BETA = UUID("5ab45c2c-1e12-5a0c-a2b9-66cd2ff05201")
ALEX = UUID("2fc05986-c7ec-544c-b628-fdb112bbf18a")


async def seed_run(app_conn: persistence.Conn, tenant: UUID) -> UUID:
    """A QUEUED run written by the superuser with plain INSERTs (revision 0002 shape): conversation, message, run,
    directory row and first history row. No persistence call: this module tests the schema, not the functions."""
    conv, msg, run = uuid4(), uuid4(), uuid4()
    await app_conn.execute(
        "INSERT INTO app.conversations (conversation_id, tenant_id, created_by) VALUES (%s, %s, %s)",
        (conv, tenant, ALEX),
    )
    await app_conn.execute(
        "INSERT INTO app.messages (message_id, tenant_id, conversation_id, kind, text, author)"
        " VALUES (%s, %s, %s, 'investigate', 'x', %s)",
        (msg, tenant, conv, ALEX),
    )
    await app_conn.execute(
        "INSERT INTO app.runs (run_id, tenant_id, conversation_id, message_id, requester, intent, asset_id, start_at,"
        " end_at, state, state_version, slot_held) VALUES (%s, %s, %s, %s, %s, 'investigate', 'A17',"
        " now() - interval '1 day', now(), 'QUEUED', 1, true)",
        (run, tenant, conv, msg, ALEX),
    )
    await app_conn.execute("INSERT INTO app.run_directory (run_id, tenant_id) VALUES (%s, %s)", (run, tenant))
    await app_conn.execute(
        "INSERT INTO app.run_state_history (tenant_id, run_id, seq, to_state, performer)"
        " VALUES (%s, %s, 1, 'QUEUED', 'seed')",
        (tenant, run),
    )
    return run


async def actual_privileges(conn: persistence.Conn) -> dict[tuple[str, str], set[tuple[str, str | None]]]:
    """What the catalogs say each grantee holds on each app table, in the matrix's (privilege, column) shape."""
    out: dict[tuple[str, str], set[tuple[str, str | None]]] = {}
    cur = await conn.execute(
        "SELECT grantee, table_name, privilege_type FROM information_schema.role_table_grants"
        " WHERE table_schema = 'app' AND grantee <> %s",
        (p.OWNER_ROLE,),
    )
    for row in await cur.fetchall():
        out.setdefault((row["grantee"], row["table_name"]), set()).add((row["privilege_type"], None))
    cur = await conn.execute(
        "SELECT grantee, table_name, column_name, privilege_type FROM information_schema.column_privileges"
        " WHERE table_schema = 'app' AND grantee <> %s",
        (p.OWNER_ROLE,),
    )
    for row in await cur.fetchall():
        key = (row["grantee"], row["table_name"])
        # A table-level grant of the same type already covers every column; anything else is a column-level grant,
        # whatever its type, so a stray column SELECT or REFERENCES fails the comparison.
        if (row["privilege_type"], None) not in out.get(key, set()):
            out.setdefault(key, set()).add((row["privilege_type"], row["column_name"]))
    return out


async def test_r124_every_grantee_holds_exactly_its_matrix_privileges(app_conn: persistence.Conn) -> None:
    actual = await actual_privileges(app_conn)
    expected = {
        (role, table): grant.privileges() for table, grants in p.GRANTS.items() for role, grant in grants.items()
    }
    assert actual == expected, {k: (actual.get(k), expected.get(k)) for k in set(actual) ^ set(expected) or actual}
    for privs in actual.values():
        assert {priv for priv, _ in privs} <= {"SELECT", "INSERT", "UPDATE", "DELETE"}
    cur = await app_conn.execute(
        "SELECT grantee, table_name FROM information_schema.role_table_grants"
        " WHERE table_schema = 'app' AND grantee = 'PUBLIC'"
    )
    assert await cur.fetchall() == []


async def test_owners_and_role_attributes(app_conn: persistence.Conn) -> None:
    cur = await app_conn.execute("SELECT tablename, tableowner FROM pg_tables WHERE schemaname = 'app'")
    owners = {r["tablename"]: r["tableowner"] for r in await cur.fetchall()}
    assert set(owners) == set(p.GRANTS) and set(owners.values()) == {p.OWNER_ROLE}, owners
    cur = await app_conn.execute(
        "SELECT rolname, rolsuper, rolbypassrls, rolcanlogin FROM pg_roles WHERE rolname = ANY(%s)",
        (list(p.GRANTEES) + [p.OWNER_ROLE, "incident", "incident_owner"],),
    )
    roles = {r["rolname"]: r for r in await cur.fetchall()}
    assert len(roles) == len(p.GRANTEES) + 3  # the test profile has every role, test_harness included
    assert roles[p.OWNER_ROLE]["rolbypassrls"] and not roles[p.OWNER_ROLE]["rolcanlogin"]
    for name, row in roles.items():
        assert not row["rolsuper"], name
        if name != p.OWNER_ROLE:
            assert not row["rolbypassrls"], name
        assert row["rolcanlogin"] == (name in p.RUNTIME_ROLES or name == "incident"), name
    cur = await app_conn.execute("SELECT nspowner::regrole::text AS owner FROM pg_namespace WHERE nspname = 'app'")
    assert (await cur.fetchone())["owner"] == p.OWNER_ROLE


async def test_r084_function_only_roles_cannot_read_or_lock_any_table(role_conn: RoleConn) -> None:
    for role in (Role.MCP_READ, Role.MCP_EXEC, Role.OPERATOR):
        conn = await role_conn(role)
        for table in p.GRANTS:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                await conn.execute(f"SELECT 1 FROM app.{table} LIMIT 1")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await conn.execute("SELECT run_id FROM app.runs FOR UPDATE")
        cur = await conn.execute("SELECT app.current_time() IS NOT NULL AS ok")
        assert (await cur.fetchone())["ok"]  # the clock is the one thing a function-only role may call directly


async def test_r128_runtime_roles_cannot_write_state_or_audit_rows_directly(role_conn: RoleConn) -> None:
    denied = {
        "events": "INSERT INTO app.events (event_id, tenant_id, conversation_id, run_id, sequence, type, occurred_at,"
        " source, payload) VALUES (gen_random_uuid(), %s, %s, %s, 1, 'x', now(), 'application', '{}')",
        "decisions": "INSERT INTO app.decisions (decision_id, tenant_id, proposal_id, reviewer, decision,"
        " expected_payload_sha256) VALUES (gen_random_uuid(), %s, %s, %s, 'approve', 'h')",
        "proposals": "INSERT INTO app.proposals (proposal_id, tenant_id, run_id, revision, draft_id, payload,"
        " payload_canonical, payload_sha256, canonicalization_version, authored_by, expires_at)"
        " VALUES (gen_random_uuid(), %s, %s, 1, %s, '{}', '', 'h', 1, '{}', now())",
        "execution_grant": "INSERT INTO app.execution_grant (action_id, tenant_id, run_id, proposal_id, payload_sha256)"
        " VALUES (gen_random_uuid(), %s, %s, %s, 'h')",
        "action_attempt_state": "INSERT INTO app.action_attempt_state (tenant_id, action_id, attempt_no, seq, state)"
        " VALUES (%s, %s, 1, 1, 'INTENT')",
        "run_state_history": "INSERT INTO app.run_state_history"
        " (tenant_id, run_id, seq, from_state, to_state, performer)"
        " VALUES (%s, %s, 9, 'a', 'b', 'x')",
    }
    for role in (Role.API, Role.WORKER, Role.SWEEPER):
        conn = await role_conn(role)
        for statement in denied.values():
            params = (ALPHA, uuid4(), uuid4()) if statement.count("%s") == 3 else (ALPHA, uuid4())
            with pytest.raises(psycopg.errors.InsufficientPrivilege, match="permission denied"):
                await conn.execute(statement, params)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await conn.execute("UPDATE app.runs SET state = 'SUCCEEDED' WHERE false")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await conn.execute("DELETE FROM app.events WHERE false")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):  # ON CONFLICT is still an INSERT
            await conn.execute(
                "INSERT INTO app.events (event_id, tenant_id, conversation_id, run_id, sequence, type, occurred_at,"
                " source, payload) VALUES (gen_random_uuid(), %s, %s, %s, 1, 'x', now(), 'application', '{}')"
                " ON CONFLICT DO NOTHING",
                (ALPHA, uuid4(), uuid4()),
            )
    api = await role_conn(Role.API)
    cur = await api.execute("UPDATE app.runs SET cancel_requested = true WHERE false")  # the one column api may set
    assert cur.rowcount == 0


async def test_r007_r008_rls_isolates_tenants_and_a_reused_connection_keeps_nothing(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    alpha_run = await seed_run(app_conn, ALPHA)
    beta_run = await seed_run(app_conn, BETA)
    try:
        api = await role_conn(Role.API)
        seen: dict[UUID, set[UUID]] = {}
        for tenant in (ALPHA, BETA):
            async with api.transaction():
                await api.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant),))
                cur = await api.execute("SELECT run_id FROM app.runs WHERE run_id = ANY(%s)", ([alpha_run, beta_run],))
                seen[tenant] = {r["run_id"] for r in await cur.fetchall()}
                cur = await api.execute("UPDATE app.runs SET cancel_requested = true WHERE run_id = %s", (beta_run,))
                assert cur.rowcount == (1 if tenant == BETA else 0)
                await api.execute("UPDATE app.runs SET cancel_requested = false WHERE run_id = %s", (beta_run,))
        assert seen == {ALPHA: {alpha_run}, BETA: {beta_run}}
        # WITH CHECK: a row for beta under alpha's context is refused, and the error ends that transaction.
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="row-level security"):
            async with api.transaction():
                await api.execute("SELECT set_config('app.tenant_id', %s, true)", (str(ALPHA),))
                await api.execute(
                    "INSERT INTO app.conversations (conversation_id, tenant_id, created_by)"
                    " VALUES (gen_random_uuid(), %s, gen_random_uuid())",
                    (BETA,),
                )
        # R008: after the units, the same connection's GUC is '' (spike §1): zero rows, no error (spike §2 NULLIF).
        cur = await api.execute("SELECT count(*) AS n FROM app.runs")
        assert (await cur.fetchone())["n"] == 0
        cur = await api.execute("SELECT current_setting('app.tenant_id', true) AS t")
        assert (await cur.fetchone())["t"] in ("", None)
    finally:
        await purge_run(app_conn, alpha_run)
        await purge_run(app_conn, beta_run)


async def test_r009_composite_keys_refuse_cross_tenant_children(app_conn: persistence.Conn) -> None:
    alpha_run = await seed_run(app_conn, ALPHA)
    try:
        # The superuser bypasses RLS and grants, so what refuses these rows is the key itself.
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            await app_conn.execute(
                "INSERT INTO app.run_state_history (tenant_id, run_id, seq, to_state, performer)"
                " VALUES (%s, %s, 9, 'X', 'x')",
                (BETA, alpha_run),
            )
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            await app_conn.execute(
                "INSERT INTO app.drafts (id, tenant_id, run_id, draft_sha256, validated, kind)"
                " VALUES (gen_random_uuid(), %s, %s, 'h', true, 'proposal')",
                (BETA, alpha_run),
            )
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            await app_conn.execute(
                "INSERT INTO app.jobs (id, type, tenant_id, run_id, dedup_key)"
                " VALUES (gen_random_uuid(), 'x', %s, %s, %s)",
                (BETA, alpha_run, f"r009-{uuid4()}"),
            )
        # seed_run already wrote the (alpha_run, ALPHA) directory row, so moving it is the cross-tenant attempt.
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            await app_conn.execute("UPDATE app.run_directory SET tenant_id = %s WHERE run_id = %s", (BETA, alpha_run))
        draft, proposal = uuid4(), uuid4()
        await app_conn.execute(
            "INSERT INTO app.drafts (id, tenant_id, run_id, draft_sha256, validated, kind)"
            " VALUES (%s, %s, %s, 'h', true, 'proposal')",
            (draft, ALPHA, alpha_run),
        )
        with pytest.raises(psycopg.errors.ForeignKeyViolation):  # an alpha proposal pointing at the draft as beta's
            await app_conn.execute(
                "INSERT INTO app.proposals (proposal_id, tenant_id, run_id, revision, draft_id, payload,"
                " payload_canonical, payload_sha256, canonicalization_version, authored_by, expires_at)"
                " VALUES (%s, %s, %s, 1, %s, '{}', '', 'h', 1, '{}', now())",
                (proposal, BETA, alpha_run, draft),
            )
        await app_conn.execute(
            "INSERT INTO app.proposals (proposal_id, tenant_id, run_id, revision, draft_id, payload, payload_canonical,"
            " payload_sha256, canonicalization_version, authored_by, expires_at)"
            " VALUES (%s, %s, %s, 1, %s, '{}', '', 'h', 1, '{}', now())",
            (proposal, ALPHA, alpha_run, draft),
        )
        with pytest.raises(psycopg.errors.ForeignKeyViolation):  # a grant naming the proposal under the other tenant
            await app_conn.execute(
                "INSERT INTO app.execution_grant (action_id, tenant_id, run_id, proposal_id, payload_sha256)"
                " VALUES (gen_random_uuid(), %s, %s, %s, 'h')",
                (BETA, alpha_run, proposal),
            )
    finally:
        await purge_run(app_conn, alpha_run)


async def test_r106_policy_text_force_and_no_rls_tables(app_conn: persistence.Conn) -> None:
    cur = await app_conn.execute(
        "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity FROM pg_class c JOIN pg_namespace n"
        " ON n.oid = c.relnamespace WHERE n.nspname = 'app' AND c.relkind = 'r'"
    )
    flags = {r["relname"]: (r["relrowsecurity"], r["relforcerowsecurity"]) for r in await cur.fetchall()}
    for table in p.RLS_TABLES:
        assert flags[table] == (True, True), table
    for table in p.NO_RLS:
        assert flags[table] == (False, False), table
    cur = await app_conn.execute(
        "SELECT tablename, policyname, permissive, roles, cmd, qual, with_check FROM pg_policies"
        " WHERE schemaname = 'app'"
    )
    policies = {(r["tablename"], r["policyname"]): r for r in await cur.fetchall()}
    expected = {(t, "tenant_isolation") for t in p.RLS_TABLES} | {(t, "sweeper_all") for t in p.SWEEPER_ALL}
    assert set(policies) == expected
    for (table, name), row in policies.items():
        assert row["permissive"] == "PERMISSIVE" and row["cmd"] == "ALL", (table, name)
        if name == "tenant_isolation":
            assert set(row["roles"]) == set(p.POLICY_ROLES) and row["qual"] == p.POLICY_QUAL == row["with_check"]
        else:
            assert row["roles"] == ["sweeper"] and row["qual"] == "true" and row["with_check"] == "true"

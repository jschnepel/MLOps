"""The AM-20.2 matrix as data (R124's source of truth) and the statements rendered from it.

Catches: a table that is neither an RLS table nor a declared no-RLS table, a function-only role with a table grant
(R084), an audit table that any role could UPDATE or DELETE (AM-20 principle 2), a definer function granted to an
unknown role, a policy text that is not the NULLIF form (spike §2), and a rendered statement that SQLAlchemy would
parse as a bind parameter (fact sheet §4.3).
"""

import re

from ops_core import privileges as p


def test_every_table_is_classified_once() -> None:
    assert set(p.GRANTS) == set(p.RLS_TABLES) | set(p.NO_RLS)
    assert not set(p.RLS_TABLES) & set(p.NO_RLS)
    assert set(p.SWEEPER_ALL) <= set(p.RLS_TABLES)


def test_function_only_roles_have_no_table_grant() -> None:
    for table, grants in p.GRANTS.items():
        for role in ("mcp_read", "mcp_exec", "operator"):
            assert role not in grants, (table, role)
    for grants in p.GRANTS.values():
        assert set(grants) <= set(p.GRANTEES)


def test_audit_tables_are_append_only_and_only_the_definer_writes_them() -> None:
    for table in p.AUDIT_TABLES:
        for role, grant in p.GRANTS[table].items():
            assert grant.upd is False and grant.dele is False, (table, role)
            assert not grant.ins or role == p.DEFINER_ROLE, (table, role)


def test_runtime_roles_never_write_state_or_events_directly() -> None:
    assert p.GRANTS["runs"]["api"].upd == ("cancel_requested", "cancel_requested_at")
    assert p.GRANTS["runs"]["worker"].upd == ("checkpoint_id", "budget_used")
    assert "state" in p.GRANTS["runs"][p.DEFINER_ROLE].upd
    for table in ("events", "decisions", "proposals", "execution_grant", "action_attempt_state"):
        assert [r for r, g in p.GRANTS[table].items() if g.ins] == [p.DEFINER_ROLE], table


def test_definer_callers_are_runtime_roles() -> None:
    for name, (_, callers) in p.DEFINER_FUNCTIONS.items():
        assert callers and set(callers) <= set(p.RUNTIME_ROLES), name
    assert p.DEFINER_FUNCTIONS["transition_run"][1] == ("worker",)
    assert p.DEFINER_FUNCTIONS["mark_unknown"][1] == ("worker",)
    assert set(p.DEFINER_FUNCTIONS["resolve_invocation"][1]) == {"mcp_read", "mcp_exec"}
    assert all(name.startswith("_") for name in p.HELPER_FUNCTIONS)


def test_rendered_statements() -> None:
    grants = p.grant_statements(["runs"])
    assert grants[0] == "REVOKE ALL ON app.runs FROM " + ", ".join(p.MAIN_GRANTEES)
    assert p.grant_statements(["test_clock"])[0] == "REVOKE ALL ON app.test_clock FROM " + ", ".join(p.GRANTEES)
    assert "GRANT UPDATE (cancel_requested, cancel_requested_at) ON app.runs TO api" in grants
    assert "GRANT SELECT ON app.runs TO sweeper" in grants
    assert "GRANT INSERT, SELECT ON app.runs TO app_definer" in grants
    rls = p.rls_statements(["jobs"])
    assert rls[0] == "ALTER TABLE app.jobs ENABLE ROW LEVEL SECURITY"
    assert rls[1] == "ALTER TABLE app.jobs FORCE ROW LEVEL SECURITY"
    assert any(
        s.startswith("CREATE POLICY tenant_isolation ON app.jobs FOR ALL TO api, worker, sweeper, app_definer")
        for s in rls
    )
    assert any(
        "CREATE POLICY sweeper_all ON app.jobs FOR ALL TO sweeper USING (true) WITH CHECK (true)" in s for s in rls
    )
    assert p.TENANT_EXPR == "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    fn = p.function_grant_statements("create_run")
    assert fn == [
        "REVOKE ALL ON FUNCTION app.create_run(uuid, uuid, jsonb, text, uuid) FROM PUBLIC",
        "GRANT EXECUTE ON FUNCTION app.create_run(uuid, uuid, jsonb, text, uuid) TO api",
    ]
    clock = p.function_grant_statements("current_time", roles=p.MAIN_ROLES)
    assert clock[1] == "GRANT EXECUTE ON FUNCTION app.current_time() TO " + ", ".join(p.MAIN_ROLES)
    assert p.function_grant_statements("current_time", roles=p.TEST_ONLY_ROLES)[1].endswith("TO test_harness")
    assert p.GRANTS["jobs"]["sweeper"].upd == ("claimed_by", "claimed_at", "done_at", "attempts")
    assert p.GRANTS["jobs"]["worker"].upd == ("claimed_by", "claimed_at", "done_at", "attempts", "available_at")
    bind = re.compile(r"(?<![:\w]):\w")  # ` :name` is a SQLAlchemy bind; `::uuid` is a cast
    for statement in [*grants, *rls, *fn, *p.schema_usage_statements()]:
        assert not bind.search(statement), statement

"""The three AM-20.2 rows Plan F adds or changes (rulings 2, 3, 17; erratum 25): the sweeper can SELECT what it
deletes on `sessions`, the pre-login state and the logout jti store exist as RLS-free tables with the narrowest cells
that work (spike §5: an insert-only role can run a target-less ON CONFLICT DO NOTHING and nothing else)."""

from ops_core import privileges as p


def test_session_tables_are_rls_free_and_narrow() -> None:
    for table in ("sessions", "login_state", "logout_jti"):
        assert table in p.NO_RLS and table not in p.RLS_TABLES
        assert set(p.GRANTS[table]) == {"api", "sweeper"}  # no definer, no worker, no function-only role
        assert p.GRANTS[table]["sweeper"] == p.Grant(sel=True, dele=True)
    assert p.GRANTS["sessions"]["api"] == p.Grant(sel=True, ins=True, upd=("last_seen_at", "revoked_at"), dele=True)
    assert p.GRANTS["login_state"]["api"] == p.Grant(sel=True, ins=True, dele=True)
    assert p.GRANTS["logout_jti"]["api"] == p.Grant(ins=True)  # replay is detected by rowcount, never by a read


def test_revision_0005_bodies_differ_only_by_the_stale_rule() -> None:
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "migrations" / "app" / "versions" / "0005_sessions_login_logout.py"
    spec = importlib.util.spec_from_file_location("rev0005", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert "MEMBERSHIP_STALE" in module.GRANT_EXECUTION and "MEMBERSHIP_STALE" not in module.GRANT_EXECUTION_0004
    assert module.GRANT_EXECUTION.count("interval '120 seconds'") == 2
    assert module.GRANTS_0005 == {t: p.GRANTS[t] for t in module.TABLES}

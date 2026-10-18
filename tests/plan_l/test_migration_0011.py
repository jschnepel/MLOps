"""Revision 0011 without a database (Plan L rulings 1-3, 7, 10, 18, 21 and 24).

Catches: a revision that creates or drops the `vector` extension (its downgrade would no longer be exact) or forgets to
require the type; a corpus table granted to a role AM-20.2 does not name, or without FORCE and the tenant policy; a
cross-reference without `tenant_id`; `search_procedures_scoped` granted to anyone but `mcp_read`, reading a table
before the handle has set the tenant, reading the clock before the lease lock, taking the tenant from an argument,
serving `mode = 'vector'` before T18, writing anything, ranking without the byte-order `evidence_id` tie-break,
returning a retired version, or keeping ranks at or below the minimum; a minimum rank granted to anyone or kept
anywhere but its one helper; a downgrade that leaves a table or a function behind; a startup marker that is not
unique to 0011; `migrate` running Alembic before the extension exists; and mcp-read starting on a database
without 0011.
"""

import importlib.util
from pathlib import Path
from typing import Any

import alembic.op
import pytest
from ops_core import persistence, privileges

from scripts import skeleton
from tests.plan_e.test_transitions_table import REVISIONS
from tests.plan_j.test_mcp_read_startup import start
from tests.plan_k.test_mcp_write_startup import MarkerConn

VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "app" / "versions"
TABLES = ("corpus_ingestions", "documents", "document_states", "chunks")


def revision(name: str = "0011_governed_corpus") -> Any:
    """Load a revision by path (the versions directory is not a package)."""
    spec = importlib.util.spec_from_file_location(f"rev_{name}", VERSIONS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def statements(module: Any, fn: str, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """What upgrade() or downgrade() hands to op.execute, in order."""
    seen: list[str] = []
    monkeypatch.setattr(alembic.op, "execute", lambda statement, *a, **k: seen.append(str(statement)))
    getattr(module, fn)()
    return seen


def test_upgrade_requires_the_vector_type_first_and_never_creates_the_extension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = revision()
    assert module.down_revision == "0010_write_path"
    seen = statements(module, "upgrade", monkeypatch)
    assert seen[0] == module.REQUIRE_VECTOR and "to_regtype('public.vector') IS NULL" in seen[0]
    everything = "\n".join(seen + statements(module, "downgrade", monkeypatch)).upper()
    assert "CREATE EXTENSION" not in everything and "DROP EXTENSION" not in everything


def test_the_four_tables_carry_the_corpus_cells_force_and_the_tenant_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    module = revision()
    assert module.TABLES_0011 == TABLES
    assert module.GRANTS_0011 == {table: privileges.GRANTS[table] for table in TABLES}
    for table in TABLES:
        assert set(privileges.GRANTS[table]) == {"worker", "app_definer"}, table  # AM-20.2's corpus row (SA:431)
        assert privileges.GRANTS[table]["worker"] == privileges.Grant(sel=True, ins=True)
        assert privileges.GRANTS[table]["app_definer"] == privileges.Grant(sel=True)
        assert table in privileges.RLS_TABLES and table not in privileges.SWEEPER_ALL
    seen = statements(module, "upgrade", monkeypatch)
    for statement in privileges.rls_statements(TABLES, module.POLICY_ROLES_0011):
        assert statement in seen
    created = [s for s in seen if s.startswith("CREATE TABLE app.")]
    assert len(created) == 4 and all(f"ALTER TABLE app.{t} OWNER TO migrator" in seen for t in TABLES)
    for ddl in created[1:]:  # every key and reference of the three child tables names the tenant (BS:246)
        assert "PRIMARY KEY (tenant_id," in ddl and "FOREIGN KEY (tenant_id," in ddl


def test_the_function_is_granted_to_mcp_read_alone_with_the_matrix_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    module = revision()
    (helper, _, helper_callers, _), (name, args, callers, body) = module.FUNCTIONS
    assert (helper, helper_callers) == ("_min_rank", ()) and privileges.HELPER_FUNCTIONS[helper] == ""
    assert (name, callers) == ("search_procedures_scoped", ("mcp_read",))
    assert privileges.DEFINER_FUNCTIONS[name] == (args, ("mcp_read",))
    seen = statements(module, "upgrade", monkeypatch)
    assert seen[-3:] == [body, *privileges.function_grant_statements(name, args=args, callers=callers)]
    assert "p_query_embedding public.vector(768)" in body  # SA:461's argument, schema-qualified for search_path


def test_the_handle_sets_the_tenant_before_any_read_and_the_clock_comes_after_the_lock() -> None:
    body = revision().SEARCH_PROCEDURES_SCOPED
    authority = body.index("PERFORM app._authority('search_procedures_scoped', ARRAY['mcp_read'])")
    handle = body.index("FROM app._resolve_handle(p_raw_handle, p_client_azp, 'read')")
    tenant = body.index("set_config('app.tenant_id', v_handle.tenant_id::text, true)")
    vector = body.index("DETAIL = 'VECTOR_MODE_UNAVAILABLE'")
    first_read = min(body.index(f"FROM {t}") for t in ("corpus_ingestions", "document_states", "documents", "chunks"))
    clock = body.index("v_now := app.current_time()")
    assert authority < handle < tenant < vector < first_read < clock
    assert "p_tenant" not in body  # the tenant is never an argument (BS:362)
    for verb in ("INSERT", "UPDATE", "DELETE"):
        assert f"{verb} " not in body.split("$fn$")[1], verb  # a reader only


def test_the_lifecycle_and_ranking_rules_are_the_rulings() -> None:
    body = revision().SEARCH_PROCEDURES_SCOPED
    assert "ORDER BY s.tenant_id, s.document_id, s.version, s.seq DESC" in body  # the latest state by seq
    assert "WHERE l.status = 'approved' AND l.effective_from <= v_now" in body
    assert "(l.effective_to IS NULL OR v_now < l.effective_to)" in body  # effective_to is exclusive
    # Ruling 7 as round 1 amended it: any later version that left draft and reached its effective_from retires the
    # earlier ones for good, compared as numbers, read from every version's latest state (not only effective ones).
    assert "SELECT 1 FROM latest n WHERE n.tenant_id = e.tenant_id AND n.document_id = e.document_id" in body
    assert "AND n.version::integer > e.version::integer" in body
    assert "AND n.status <> 'draft' AND n.effective_from <= v_now" in body
    assert "(p_asset_type IS NULL OR e.asset_family IS NULL OR e.asset_family = p_asset_type)" in body
    assert "to_tsquery('simple', array_to_string(v_lexemes, ' | '))" in body  # the OR of the query's lexemes
    assert "WHERE r.rank > app._min_rank()" in body and 'ORDER BY r.rank DESC, r.evidence_id COLLATE "C" LIMIT' in body
    assert 'ORDER BY k.rank DESC, k.evidence_id COLLATE "C")' in body  # the same order in the answer
    helper = revision().MIN_RANK
    assert "RETURN 0.25;" in helper and "SECURITY DEFINER" not in helper and body.count("0.25") == 0


def test_the_downgrade_drops_exactly_what_the_upgrade_created(monkeypatch: pytest.MonkeyPatch) -> None:
    module = revision()
    assert statements(module, "downgrade", monkeypatch) == [
        "DROP FUNCTION app.search_procedures_scoped(text, text, text, public.vector, text, integer, text)",
        "DROP FUNCTION app._min_rank()",
        "DROP TABLE app.chunks",
        "DROP TABLE app.document_states",
        "DROP TABLE app.documents",
        "DROP TABLE app.corpus_ingestions",
    ]


def test_the_startup_marker_is_only_in_0011s_function() -> None:
    signature, marker = persistence.GOVERNED_CORPUS
    assert signature == "app.search_procedures_scoped(text, text, text, public.vector, text, integer, text)"
    assert marker in revision().SEARCH_PROCEDURES_SCOPED
    for older in REVISIONS[: REVISIONS.index("0011_governed_corpus")]:
        assert marker not in (VERSIONS / f"{older}.py").read_text(encoding="utf-8"), older


def test_migrate_creates_the_extension_before_alembic_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(skeleton, "load_dotenv", lambda path: {})
    monkeypatch.setattr(skeleton, "export_environment", lambda dotenv: None)
    monkeypatch.setattr(
        skeleton.settings, "superuser_postgres", lambda: skeleton.settings.Postgres("h", 1, "u", "d", "p")
    )
    monkeypatch.setattr(skeleton, "ensure_roles", lambda *a: calls.append("roles"))
    monkeypatch.setattr(skeleton, "ensure_extensions", lambda pg: calls.append(f"extensions:{pg.dbname}"))
    monkeypatch.setattr(skeleton, "upgrade", lambda tree, pg, target: calls.append(f"upgrade:{tree}"))
    assert skeleton.migrate(skeleton.Profile.TEST) == 0
    assert calls == ["roles", "extensions:d", "upgrade:app", "upgrade:incident"]
    assert skeleton.EXTENSIONS == ("vector",)


def test_mcp_read_refuses_a_database_without_0011(monkeypatch: pytest.MonkeyPatch) -> None:
    conn: Any = MarkerConn({persistence.HANDLE_BINDING[1]})  # 0009's binding is there, 0011's function is not
    with pytest.raises(persistence.PersistenceError, match="predates this service"):
        start(monkeypatch, conn)
    assert conn.closed
    assert conn.asked[-1] == (persistence.GOVERNED_CORPUS[1], persistence.GOVERNED_CORPUS[0])

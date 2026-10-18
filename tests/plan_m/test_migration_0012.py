"""Revision 0012 without a database (Plan M rulings 2, 3, 7 and 11).

Catches: `asset_scope` granted to anyone but `mcp_read`, reading the run before the handle has set the tenant, reading
the clock before the lease lock, taking the tenant or the asset from an argument, writing anything, or answering for
a run whose requester has lost the requester membership; a search that changed anything of 0011's body besides the
five named changes (the ranking and filters must stay byte for byte), forgets its instant or the membership re-check,
or still cuts the excerpt at 500 characters, or cuts silently; a CREATE OR REPLACE where the return type changes
(PostgreSQL refuses it); a downgrade that does not restore 0011's body and grant exactly; startup markers that are not
unique to 0012; mcp-read starting on a database without 0012; and a search answer stamped from the wall clock or
with a cut excerpt that leaves `truncated` false.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from ops_core import persistence, privileges
from ops_mcp_read import server

from tests.plan_e.test_transitions_table import REVISIONS
from tests.plan_j.test_mcp_read_startup import start
from tests.plan_k.test_mcp_write_startup import MarkerConn
from tests.plan_l.test_migration_0011 import VERSIONS, revision, statements

TOOL_RESULT = Draft202012Validator(
    json.loads(Path("schemas/tool-result.schema.json").read_text(encoding="utf-8")), format_checker=FormatChecker()
)
SEARCH = "search_procedures_scoped"
SEARCH_ARGS = "text, text, text, public.vector, text, integer, text"


def rev0012() -> Any:
    return revision("0012_asset_scope")


def test_upgrade_drops_the_search_then_creates_both_with_their_grants(monkeypatch: pytest.MonkeyPatch) -> None:
    module = rev0012()
    assert module.down_revision == "0011_governed_corpus"
    seen = statements(module, "upgrade", monkeypatch)
    assert seen == [
        f"DROP FUNCTION app.{SEARCH}({SEARCH_ARGS})",  # a changed return type: CREATE OR REPLACE would be refused
        module.ASSET_SCOPE,
        "REVOKE ALL ON FUNCTION app.asset_scope(text, text) FROM PUBLIC",
        "GRANT EXECUTE ON FUNCTION app.asset_scope(text, text) TO mcp_read",
        module.SEARCH_PROCEDURES_SCOPED,
        f"REVOKE ALL ON FUNCTION app.{SEARCH}({SEARCH_ARGS}) FROM PUBLIC",
        f"GRANT EXECUTE ON FUNCTION app.{SEARCH}({SEARCH_ARGS}) TO mcp_read",
    ]


def test_both_functions_are_granted_to_mcp_read_alone_with_the_matrix_signatures() -> None:
    module = rev0012()
    assert [(name, args, callers) for name, args, callers, _ in module.FUNCTIONS] == [
        ("asset_scope", "text, text", ("mcp_read",)),
        (SEARCH, SEARCH_ARGS, ("mcp_read",)),
    ]
    assert privileges.DEFINER_FUNCTIONS["asset_scope"] == ("text, text", ("mcp_read",))
    assert privileges.DEFINER_FUNCTIONS[SEARCH] == (SEARCH_ARGS, ("mcp_read",))  # unchanged since 0011
    assert "ALTER FUNCTION app.asset_scope(text, text) OWNER TO app_definer;" in module.ASSET_SCOPE


def test_the_search_is_0011s_body_with_exactly_the_five_changes() -> None:
    module = rev0012()
    body = module.SEARCH_PROCEDURES_SCOPED
    assert len(module.CHANGES_0012) == 5
    for old, new in reversed(module.CHANGES_0012):
        assert body.count(new) == 1, new[:60]
        body = body.replace(new, old)
    assert body == revision().SEARCH_PROCEDURES_SCOPED  # the ranking, filters and _min_rank byte for byte
    with pytest.raises(RuntimeError, match="no longer carries"):
        module.changed(revision().SEARCH_PROCEDURES_SCOPED.replace("left(c.body, 500)", "left(c.body, 400)"))


def test_asset_scope_sets_the_tenant_and_rechecks_the_requester_before_it_reads_the_run() -> None:
    body = rev0012().ASSET_SCOPE
    authority = body.index("PERFORM app._authority('asset_scope', ARRAY['mcp_read'])")
    handle = body.index("FROM app._resolve_handle(p_raw_handle, p_client_azp, 'read')")
    tenant = body.index("set_config('app.tenant_id', v_handle.tenant_id::text, true)")
    member = body.index("AND m.role = 'requester' AND m.active")
    run = body.index("SELECT * INTO v_run FROM runs r WHERE r.run_id = v_handle.run_id")
    clock = body.index("as_of := app.current_time()")
    assert authority < handle < tenant < member < run < clock
    assert "RAISE EXCEPTION 'handle_rejected' USING ERRCODE = 'OC008'" in body  # the one handle refusal (SA:355)
    assert (
        "RETURNS TABLE (run_id uuid, tenant_id uuid, asset_id text, start_at timestamptz, end_at timestamptz," in body
    )
    assert "p_tenant" not in body and "p_asset" not in body  # the tenant and the asset come from the handle only
    for verb in ("INSERT", "UPDATE", "DELETE"):
        assert f"{verb} " not in body.split("$fn$")[1], verb  # a reader only


def test_the_search_rechecks_the_requester_first_and_returns_its_instant() -> None:
    body = rev0012().SEARCH_PROCEDURES_SCOPED
    tenant = body.index("set_config('app.tenant_id', v_handle.tenant_id::text, true)")
    member = body.index("AND m.role = 'requester' AND m.active")
    vector = body.index("DETAIL = 'VECTOR_MODE_UNAVAILABLE'")
    first_read = min(body.index(f"FROM {t}") for t in ("corpus_ingestions", "document_states", "documents", "chunks"))
    clock = body.index("v_now := app.current_time()")
    instant = body.index("retrieved_at := v_now;")
    stop_words = body.index("results := '[]'::jsonb")
    assert tenant < member < vector < first_read < clock < instant < stop_words  # an empty answer carries it too
    assert "RETURNS TABLE (corpus_version text, retrieved_at timestamptz, results jsonb)" in body


def test_the_excerpt_is_the_whole_section_up_to_the_contracts_bound_and_says_when_it_is_cut() -> None:
    module = rev0012()
    schema = json.loads(Path("schemas/tool-result.schema.json").read_text(encoding="utf-8"))
    branch = next(
        b for b in schema["allOf"] if b["if"]["properties"].get("tool_name") == {"const": "search_procedures"}
    )
    bound = branch["then"]["properties"]["data"]["properties"]["results"]["items"]["properties"]["excerpt"]
    assert module.EXCERPT_CHARS_0012 == bound["maxLength"] == 8000
    body = module.SEARCH_PROCEDURES_SCOPED
    assert "left(c.body, 8000) AS excerpt," in body and "left(c.body, 500)" not in body
    assert "char_length(c.body) > 8000 AS excerpt_cut" in body and "'excerpt_cut', k.excerpt_cut)" in body


def test_the_downgrade_restores_0011s_search_exactly(monkeypatch: pytest.MonkeyPatch) -> None:
    assert statements(rev0012(), "downgrade", monkeypatch) == [
        "DROP FUNCTION app.asset_scope(text, text)",
        f"DROP FUNCTION app.{SEARCH}({SEARCH_ARGS})",
        revision().SEARCH_PROCEDURES_SCOPED,
        f"REVOKE ALL ON FUNCTION app.{SEARCH}({SEARCH_ARGS}) FROM PUBLIC",
        f"GRANT EXECUTE ON FUNCTION app.{SEARCH}({SEARCH_ARGS}) TO mcp_read",
    ]


def test_the_startup_markers_are_only_in_0012s_functions() -> None:
    module = rev0012()
    assert persistence.ASSET_SCOPE == ("app.asset_scope(text, text)", "as_of := app.current_time()")
    assert persistence.SEARCH_INSTANT == (f"app.{SEARCH}({SEARCH_ARGS})", "retrieved_at := v_now")
    assert persistence.ASSET_SCOPE[1] in module.ASSET_SCOPE
    assert persistence.SEARCH_INSTANT[1] in module.SEARCH_PROCEDURES_SCOPED
    assert persistence.GOVERNED_CORPUS[1] in module.SEARCH_PROCEDURES_SCOPED  # 0011's marker survives the re-creation
    for older in REVISIONS[: REVISIONS.index("0012_asset_scope")]:
        text = (VERSIONS / f"{older}.py").read_text(encoding="utf-8")
        assert persistence.ASSET_SCOPE[1] not in text and persistence.SEARCH_INSTANT[1] not in text, older


def test_mcp_read_refuses_a_database_without_0012(monkeypatch: pytest.MonkeyPatch) -> None:
    conn: Any = MarkerConn({persistence.HANDLE_BINDING[1], persistence.GOVERNED_CORPUS[1]})  # 0011, not 0012
    with pytest.raises(persistence.PersistenceError, match="predates this service"):
        start(monkeypatch, conn)
    assert conn.closed
    assert conn.asked[-1] == (persistence.ASSET_SCOPE[1], persistence.ASSET_SCOPE[0])


def test_a_search_answer_carries_the_definers_instant_and_its_cut() -> None:
    hit = persistence.Procedure(
        evidence_id="ALPHA-PUMP-SEAL:v2:inspection",
        document_id="ALPHA-PUMP-SEAL",
        version="2",
        section="inspection",
        content_sha256="a" * 64,
        excerpt="x" * 8000,
        effective_from=datetime(2026, 9, 1, tzinfo=UTC),
        rank=0.5,
    )
    decided = datetime(2026, 10, 6, 12, 0, 0, 750000, tzinfo=UTC)  # the database's instant, not the wall clock
    for cut in (False, True):
        doc = server.search_response(persistence.Procedures("corpus-1", (hit,), decided, cut))
        TOOL_RESULT.validate(doc)
        assert doc["data"]["results"][0]["retrieved_at"] == doc["observed_at"] == "2026-10-06T12:00:00Z"
        assert doc["truncated"] is cut  # ruling 11: never a silent cut

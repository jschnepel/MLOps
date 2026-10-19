"""Revision 0013 without a database (Plan N rulings 1 and 5-7).

Catches: an embeddings table granted to a role AM-20.2's corpus row does not name, without FORCE and the tenant policy,
without the chunk it belongs to, of another dimension, or under a vector index (approximate search); a search body that
changed anything of 0012's besides the three named changes (the lexical branch must stay byte for byte); a vector
branch whose filters are not the lexical branch's text, that reads before the argument rule or the clock, ranks
without the byte-order tie-break or the minimum similarity, answers other keys, or leaves out a permitted chunk
without an embedding silently; the old VECTOR_MODE_UNAVAILABLE refusal surviving; the stop-word return applying to
vector mode; a minimum similarity granted to anyone or kept anywhere but its helper; a DROP of the search (its return
type is unchanged, so its grants are kept); a downgrade that does not restore 0012's body exactly; a startup marker
that is not unique to 0013; and mcp-read starting on a database without 0013.
"""

from typing import Any

import pytest
from ops_core import locking, persistence, privileges

from tests.plan_e.test_transitions_table import REVISIONS
from tests.plan_j.test_mcp_read_startup import start
from tests.plan_k.test_mcp_write_startup import MarkerConn
from tests.plan_l.test_migration_0011 import VERSIONS, revision, statements

SEARCH = "search_procedures_scoped"
SEARCH_ARGS = privileges.DEFINER_FUNCTIONS[SEARCH][0]  # copied from the matrix, never retyped
CELLS = {"worker": privileges.Grant(sel=True, ins=True), "app_definer": privileges.Grant(sel=True)}
LEXICAL = "    -- The OR of the query's own lexemes"


def rev0013() -> Any:
    return revision("0013_embeddings")


def test_upgrade_creates_the_table_its_cells_and_policy_then_the_helper_and_the_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = rev0013()
    assert module.down_revision == "0012_asset_scope"
    seen = statements(module, "upgrade", monkeypatch)
    assert seen == [
        *module.SCHEMA_CHANGES,
        "REVOKE ALL ON app.embeddings FROM api, worker, sweeper, mcp_read, mcp_exec, operator, app_definer",
        "GRANT INSERT, SELECT ON app.embeddings TO worker",
        "GRANT SELECT ON app.embeddings TO app_definer",
        *privileges.rls_statements(("embeddings",), ("api", "worker", "sweeper", "app_definer")),
        module.MIN_SIMILARITY,
        "REVOKE ALL ON FUNCTION app._min_similarity() FROM PUBLIC",
        module.SEARCH_PROCEDURES_SCOPED,
        f"REVOKE ALL ON FUNCTION app.{SEARCH}({SEARCH_ARGS}) FROM PUBLIC",
        f"GRANT EXECUTE ON FUNCTION app.{SEARCH}({SEARCH_ARGS}) TO mcp_read",
    ]
    assert not any(s.startswith("DROP FUNCTION") for s in seen)  # the return type is unchanged: no DROP


def test_the_table_is_the_corpus_row_one_row_per_chunk_and_exact() -> None:
    module = rev0013()
    assert module.GRANTS_0013 == {"embeddings": CELLS} == {"embeddings": privileges.GRANTS["embeddings"]}
    assert "embeddings" in privileges.RLS_TABLES and "embeddings" not in privileges.SWEEPER_ALL
    assert "embeddings" in locking.NEVER_LOCKED
    ddl = module.SCHEMA_CHANGES[0]
    assert "PRIMARY KEY (tenant_id, evidence_id)" in ddl
    assert "FOREIGN KEY (tenant_id, evidence_id) REFERENCES app.chunks (tenant_id, evidence_id)" in ddl
    assert "embedding public.vector(768) NOT NULL" in ddl and "CHECK (dimension = 768)" in ddl
    assert "CHECK (model = 'nomic-embed-text')" in ddl and "input_sha256 text NOT NULL" in ddl
    assert "CHECK (public.vector_norm(embedding) > 0)" in ddl  # no zero vector: its NaN cosine would sort first
    everything = "\n".join(module.SCHEMA_CHANGES).upper()
    assert "CREATE INDEX" not in everything and "EXTENSION" not in everything  # exact search; the bootstrap's type


def test_the_search_is_0012s_body_with_exactly_the_three_changes() -> None:
    module = rev0013()
    body = module.SEARCH_PROCEDURES_SCOPED
    assert len(module.CHANGES_0013) == 3
    for old, new in reversed(module.CHANGES_0013):
        assert body.count(new) == 1, new[:60]
        body = body.replace(new, old)
    assert body == revision("0012_asset_scope").SEARCH_PROCEDURES_SCOPED
    with pytest.raises(RuntimeError, match="no longer carries"):
        module.changed(module.BODY_0012.replace("    v_query tsquery;\n", "    v_query tsquery; \n"))


def test_the_vector_branch_reuses_the_lexical_filters_verbatim_and_answers_the_same_keys() -> None:
    body = rev0013().SEARCH_PROCEDURES_SCOPED
    vector = body[body.index("    IF p_mode = 'vector' THEN\n") : body.index(LEXICAL)]
    lexical = body[body.index(LEXICAL) :]

    def between(text: str, start: str, end: str) -> str:
        return text[text.index(start) : text.index(end)]

    filters = between(lexical, "    WITH latest AS (\n", "    ), ranked AS (\n")
    assert between(vector, "    WITH latest AS (\n", "    ), scored AS (\n") == filters  # byte for byte (ruling 5)
    answer = between(lexical, "    SELECT coalesce(jsonb_agg(", "    INTO results FROM kept k;")
    assert answer.rstrip("\n") in vector  # the same result keys, excerpt bound and order
    assert "left(c.body, 8000) AS excerpt," in vector and "char_length(c.body) > 8000 AS excerpt_cut" in vector
    assert "1 - (e.embedding OPERATOR(public.<=>) p_query_embedding) AS rank" in vector  # cosine similarity
    assert "WHERE NOT r.unembedded AND r.rank > app._min_similarity()" in vector
    assert 'ORDER BY r.rank DESC, r.evidence_id COLLATE "C" LIMIT p_limit' in vector
    assert "LEFT JOIN embeddings e USING (tenant_id, evidence_id)" in vector
    assert (
        "DETAIL = 'EMBEDDINGS_INCOMPLETE'" in vector and "EXISTS (SELECT 1 FROM scored s WHERE s.unembedded)" in vector
    )
    assert "ts_rank_cd(" not in vector and "embedding" not in lexical  # each branch ranks its own way only


def test_the_argument_rule_comes_before_any_read_and_the_vector_branch_before_the_stop_words() -> None:
    body = rev0013().SEARCH_PROCEDURES_SCOPED
    member = body.index("AND m.role = 'requester' AND m.active")
    rule = body.index("IF p_mode IS NULL OR p_mode NOT IN ('lexical', 'vector')")
    first_read = min(body.index(f"FROM {t}") for t in ("corpus_ingestions", "document_states", "documents", "chunks"))
    clock = body.index("v_now := app.current_time()")
    instant = body.index("retrieved_at := v_now;")
    vector = body.index("    IF p_mode = 'vector' THEN\n")
    stop_words = body.index("results := '[]'::jsonb")
    assert member < rule < first_read < clock < instant < vector < stop_words
    assert "VECTOR_MODE_UNAVAILABLE" not in body and "TODO(T18)" not in body
    assert "(p_mode = 'lexical' AND p_query_embedding IS NOT NULL)" in body
    assert (
        "public.vector_dims(p_query_embedding) <> 768" in body and "public.vector_norm(p_query_embedding) = 0" in body
    )
    assert "OR p_query IS NULL OR char_length(p_query) NOT BETWEEN 1 AND 500" in body  # both modes
    for verb in ("INSERT", "UPDATE", "DELETE"):
        assert f"{verb} " not in body.split("$fn$")[1], verb  # a reader only


def test_the_minimum_similarity_is_a_helper_granted_to_nobody() -> None:
    module = rev0013()
    (helper, args, callers, body), (name, search_args, search_callers, _) = module.FUNCTIONS
    assert (helper, args, callers) == ("_min_similarity", "", ()) and privileges.HELPER_FUNCTIONS[helper] == ""
    assert (name, search_args, search_callers) == (SEARCH, SEARCH_ARGS, ("mcp_read",))
    assert privileges.DEFINER_FUNCTIONS[SEARCH] == (SEARCH_ARGS, ("mcp_read",))  # unchanged since 0011
    assert f"RETURN {module.MIN_SIMILARITY_0013};" in body and "IMMUTABLE" in body and "SECURITY DEFINER" not in body
    assert "ALTER FUNCTION app._min_similarity() OWNER TO app_definer;" in body
    assert 0.0 <= float(module.MIN_SIMILARITY_0013) < 1.0
    assert module.MIN_SIMILARITY_0013 not in module.SEARCH_PROCEDURES_SCOPED  # one place only


def test_the_downgrade_restores_0012s_search_then_drops_the_helper_and_the_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert statements(rev0013(), "downgrade", monkeypatch) == [
        revision("0012_asset_scope").SEARCH_PROCEDURES_SCOPED,
        f"REVOKE ALL ON FUNCTION app.{SEARCH}({SEARCH_ARGS}) FROM PUBLIC",
        f"GRANT EXECUTE ON FUNCTION app.{SEARCH}({SEARCH_ARGS}) TO mcp_read",
        "DROP FUNCTION app._min_similarity()",
        "DROP TABLE app.embeddings",
    ]


def test_the_startup_marker_is_only_in_0013s_search_and_the_older_markers_survive() -> None:
    body = rev0013().SEARCH_PROCEDURES_SCOPED
    assert persistence.VECTOR_SEARCH == (
        f"app.{SEARCH}({SEARCH_ARGS})",
        "e.embedding OPERATOR(public.<=>) p_query_embedding",
    )
    assert body.count(persistence.VECTOR_SEARCH[1]) == 1
    assert persistence.GOVERNED_CORPUS[1] in body and persistence.SEARCH_INSTANT[1] in body  # 0011's and 0012's
    for older in REVISIONS[: REVISIONS.index("0013_embeddings")]:
        assert persistence.VECTOR_SEARCH[1] not in (VERSIONS / f"{older}.py").read_text(encoding="utf-8"), older


def test_mcp_read_refuses_a_database_without_0013(monkeypatch: pytest.MonkeyPatch) -> None:
    at_0012 = {
        persistence.HANDLE_BINDING[1],
        persistence.GOVERNED_CORPUS[1],
        persistence.ASSET_SCOPE[1],
        persistence.SEARCH_INSTANT[1],
    }
    conn: Any = MarkerConn(at_0012)
    with pytest.raises(persistence.PersistenceError, match="predates this service"):
        start(monkeypatch, conn)
    assert conn.closed
    assert conn.asked[-1] == (persistence.VECTOR_SEARCH[1], persistence.VECTOR_SEARCH[0])

"""Exact vector retrieval (T18; Plan N rulings 1 and 5-7): `app.embeddings`, `_min_similarity` and the vector branch
of `search_procedures_scoped`.

Revision ID: 0013_embeddings
Revises: 0012_asset_scope

- `embeddings`: one row per stored chunk, keyed like the chunk (`tenant_id`, `evidence_id`) and referencing it, with
  the model, its digest, the dimension, the SHA-256 of the exact text that was embedded (the `search_document:` prefix
  included, so a stored row proves its prefix) and the `public.vector(768)` itself, never a zero vector. A model
  change is a later revision's re-embedding, so the model and the dimension are pinned by CHECK. The cells are
  AM-20.2's corpus row (SA:431): `worker` inserts and reads (the operator command `scripts/skeleton.py embed`), `app_definer` reads, nobody
  else; ENABLE + FORCE RLS with the `tenant_isolation` policy (SA:510). No vector index: a sequential scan over the
  tenant's permitted chunks is exact by construction (ruling 7), and an index would make the search approximate.
- `_min_similarity()`: the vector branch keeps only a cosine similarity above it; chosen on the development queries by
  a rule fixed before measuring (ruling 6), so it is a development figure. One helper, as `_min_rank()`.
- `search_procedures_scoped` is re-created from revision 0012's own body with three textual changes and nothing else
  (the lexical branch stays byte for byte; a unit test reverses the changes and compares): the argument rule accepts
  `mode = 'vector'` with exactly one 768-dimension, non-zero query embedding and `mode = 'lexical'` with none, the
  `VECTOR_MODE_UNAVAILABLE` refusal goes, and a vector branch runs before the lexical one's stop-word return. The
  branch repeats the lexical branch's `latest`, `effective` and `permitted` text byte for byte (sliced from 0012's
  body here, so a filter cannot drift), ranks every permitted chunk by cosine similarity, `1 - (embedding <=> query)`,
  with the same tie-break, limit, excerpt and result keys, and refuses `EMBEDDINGS_INCOMPLETE` when a permitted chunk
  has no embedding, so nothing is left out silently. The return type is unchanged, so CREATE OR REPLACE replaces the
  body in place; PostgreSQL keeps a replaced function's owner and permissions, and the grant statements are applied
  again all the same.

The downgrade restores 0012's search body from 0012's own module, then drops the helper and the table (with its rows,
its grants and its policy); the `vector` extension stays, because the bootstrap made it.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic import op
from ops_core import privileges

revision = "0013_embeddings"
down_revision = "0012_asset_scope"
branch_labels = None
depends_on = None


def _applied(name: str) -> ModuleType:
    """An applied revision's module, loaded by path (the versions directory is not a package)."""
    spec = importlib.util.spec_from_file_location(f"applied_{name}", Path(__file__).with_name(f"{name}.py"))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"revision {name} is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REV0012 = _applied("0012_asset_scope")
HELPER_HEADER = "LANGUAGE plpgsql SET search_path = app, pg_temp"
SEARCH_ARGS = "text, text, text, public.vector, text, integer, text"
DIMENSION_0013 = 768  # nomic-embed-text's embedding length (data/embedding-pins.json), SA:461's vector(768)
# Plan N ruling 6: the largest value on a 0.01 grid at which vector hit@5 over the answerable development cases equals
# its value at 0, measured by `scripts.retrieval_comparison threshold` before this file was frozen (the live comparison
# re-measures it). A development figure: the holdout was never read (SA:657-659).
MIN_SIMILARITY_0013 = "0.68"

TABLES_0013 = ("embeddings",)
MAIN_GRANTEES_0013 = ("api", "worker", "sweeper", "mcp_read", "mcp_exec", "operator", "app_definer")
POLICY_ROLES_0013 = ("api", "worker", "sweeper", "app_definer")
# AM-20.2's corpus row (SA:431): the operator command inserts as the worker, only the definer reads.
GRANTS_0013: dict[str, dict[str, privileges.Grant]] = {
    "embeddings": {"worker": privileges.Grant(sel=True, ins=True), "app_definer": privileges.Grant(sel=True)},
}

SCHEMA_CHANGES = (
    (
        "CREATE TABLE app.embeddings ("
        " tenant_id uuid NOT NULL,"
        " evidence_id text NOT NULL,"
        " model text NOT NULL CHECK (model = 'nomic-embed-text'),"
        " model_digest text NOT NULL CHECK (model_digest ~ '^[a-f0-9]{64}$'),"
        f" dimension integer NOT NULL CHECK (dimension = {DIMENSION_0013}),"
        " input_sha256 text NOT NULL CHECK (input_sha256 ~ '^[a-f0-9]{64}$'),"
        f" embedding public.vector({DIMENSION_0013}) NOT NULL,"
        # A zero vector has a NaN cosine, which PostgreSQL orders above every number (round 1, Minor 6).
        " CHECK (public.vector_norm(embedding) > 0),"
        " embedded_at timestamptz NOT NULL DEFAULT now(),"
        " PRIMARY KEY (tenant_id, evidence_id),"
        " CONSTRAINT embeddings_chunk_fkey FOREIGN KEY (tenant_id, evidence_id)"
        " REFERENCES app.chunks (tenant_id, evidence_id))"
    ),
    "ALTER TABLE app.embeddings OWNER TO migrator",
)

MIN_SIMILARITY = f"""
CREATE OR REPLACE FUNCTION app._min_similarity() RETURNS double precision
{HELPER_HEADER} IMMUTABLE AS $fn$
BEGIN
    RETURN {MIN_SIMILARITY_0013};
END
$fn$;
ALTER FUNCTION app._min_similarity() OWNER TO app_definer;
"""


def _between(body: str, start: str, end: str) -> str:
    """The text of `body` from `start` up to, not including, `end`; each must occur exactly once."""
    if body.count(start) != 1 or body.count(end) != 1:
        raise RuntimeError("revision 0012's search_procedures_scoped no longer carries a text 0013 reuses")
    return body[body.index(start) : body.index(end)]


BODY_0012 = REV0012.SEARCH_PROCEDURES_SCOPED
EXCERPT_CHARS_0013 = REV0012.EXCERPT_CHARS_0012
# The lexical branch's filters (`latest`, `effective`, `permitted`) and its answer, reused verbatim (ruling 5).
FILTERS_0012 = _between(BODY_0012, "    WITH latest AS (\n", "    ), ranked AS (\n")
ANSWER_0012 = _between(BODY_0012, "    SELECT coalesce(jsonb_agg(", "    INTO results FROM kept k;\n")

# Revision 0012's body, changed in exactly these places; each `old` must occur once (checked before anything runs).
REFUSAL_AND_MODE_0012 = (
    "    IF p_mode = 'vector' THEN\n"
    "        -- TODO(T18): exact pgvector search over app.embeddings under the same filters (R034).\n"
    "        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'VECTOR_MODE_UNAVAILABLE';\n"
    "    END IF;\n"
    "    IF p_mode IS DISTINCT FROM 'lexical' OR p_query IS NULL OR char_length(p_query) NOT BETWEEN 1 AND 500\n"
)
ARGUMENTS_0013 = (
    "    -- T18 (Plan N ruling 5): a lexical call carries no embedding; a vector call carries one non-zero\n"
    "    -- embedding of the model's dimension (a function argument's type modifier is not enforced, and a zero\n"
    "    -- vector has no direction). The text query is required and bounded in both modes. Else BAD_ARGUMENT.\n"
    "    IF p_mode IS NULL OR p_mode NOT IN ('lexical', 'vector')\n"
    "       OR (p_mode = 'lexical' AND p_query_embedding IS NOT NULL)\n"
    "       OR (p_mode = 'vector' AND (p_query_embedding IS NULL\n"
    f"                                 OR public.vector_dims(p_query_embedding) <> {DIMENSION_0013}\n"
    "                                 OR public.vector_norm(p_query_embedding) = 0))\n"
    "       OR p_query IS NULL OR char_length(p_query) NOT BETWEEN 1 AND 500\n"
)
DECLARE_0012 = "    v_query tsquery;\n"
DECLARE_0013 = "    v_query tsquery;\n    v_incomplete boolean;\n"
INSTANT_0012 = REV0012.INSTANT_0012
VECTOR_BRANCH = (
    "    IF p_mode = 'vector' THEN\n"
    "        -- T18 (Plan N rulings 5-7): exact cosine search over the same permitted chunks. The filter text\n"
    "        -- below is the lexical branch's, byte for byte and at its indentation (a unit test compares the\n"
    "        -- two). No index: every permitted chunk is scored, so the order is exact. A permitted chunk without\n"
    "        -- an embedding refuses the call (EMBEDDINGS_INCOMPLETE): no section is left out silently.\n"
    + FILTERS_0012
    + "    ), scored AS (\n"
    "        SELECT c.evidence_id, c.document_id, c.version, c.section, c.content_sha256,\n"
    f"               left(c.body, {EXCERPT_CHARS_0013}) AS excerpt,\n"
    f"               char_length(c.body) > {EXCERPT_CHARS_0013} AS excerpt_cut, p.effective_from,\n"
    "               e.embedding IS NULL AS unembedded,\n"
    "               1 - (e.embedding OPERATOR(public.<=>) p_query_embedding) AS rank\n"
    "        FROM chunks c JOIN permitted p USING (tenant_id, document_id, version)\n"
    "        LEFT JOIN embeddings e USING (tenant_id, evidence_id)\n"
    "    ), kept AS (\n"
    "        -- `rank` is the cosine similarity here (ruling 6): another meaning than ts_rank_cd's, never\n"
    "        -- compared with it (BS:417). At or below the minimum dropped; the lexical branch's tie-break.\n"
    "        SELECT * FROM scored r WHERE NOT r.unembedded AND r.rank > app._min_similarity()\n"
    '        ORDER BY r.rank DESC, r.evidence_id COLLATE "C" LIMIT p_limit\n'
    "    )\n" + ANSWER_0012.removesuffix("\n") + ",\n"
    "           EXISTS (SELECT 1 FROM scored s WHERE s.unembedded)\n"
    "    INTO results, v_incomplete FROM kept k;\n"
    "        IF v_incomplete THEN\n"
    "            RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'EMBEDDINGS_INCOMPLETE';\n"
    "        END IF;\n"
    "        RETURN NEXT;\n"
    "        RETURN;\n"
    "    END IF;\n"
)
CHANGES_0013: tuple[tuple[str, str], ...] = (
    (DECLARE_0012, DECLARE_0013),
    (REFUSAL_AND_MODE_0012, ARGUMENTS_0013),
    (INSTANT_0012, INSTANT_0012 + VECTOR_BRANCH),
)


def changed(body: str) -> str:
    """Revision 0012's search body with this revision's changes applied.

    Raises:
        RuntimeError: a change's text is not in the body exactly once (0012's body is not the one this revision was
            written against).
    """
    for old, new in CHANGES_0013:
        if body.count(old) != 1:
            raise RuntimeError("revision 0012's search_procedures_scoped no longer carries a text 0013 changes")
        body = body.replace(old, new)
    return body


SEARCH_PROCEDURES_SCOPED = changed(BODY_0012)
# (name, argument types, callers, body): frozen here (N1); the newest-revision test reads this tuple.
FUNCTIONS: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("_min_similarity", "", (), MIN_SIMILARITY),
    ("search_procedures_scoped", SEARCH_ARGS, ("mcp_read",), SEARCH_PROCEDURES_SCOPED),
)
# What downgrade() re-creates, from the applied revision's own body: (name, args, callers, body).
RESTORED: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("search_procedures_scoped", SEARCH_ARGS, ("mcp_read",), BODY_0012),
)
DOWNGRADE = (
    "DROP FUNCTION app._min_similarity()",
    "DROP TABLE app.embeddings",  # its rows, grants and policy go with it
)


def upgrade() -> None:
    """The table, its frozen cells and policy, then the helper and the search (each body first, then its grants:
    REVOKE from PUBLIC, then EXECUTE to its callers, none for the helper)."""
    for statement in SCHEMA_CHANGES:
        op.execute(statement)
    for statement in privileges.grant_statements(TABLES_0013, GRANTS_0013, revokees=MAIN_GRANTEES_0013):
        op.execute(statement)
    for statement in privileges.rls_statements(TABLES_0013, POLICY_ROLES_0013):
        op.execute(statement)
    for name, args, callers, body in FUNCTIONS:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)


def downgrade() -> None:
    """Back to 0012: the search's 0012 body and its grants first (it no longer names the helper or the table), then
    the helper and the table."""
    for name, args, callers, body in RESTORED:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)
    for statement in DOWNGRADE:
        op.execute(statement)

"""The governed corpus (T17; Plan L rulings 1-3, 7, 10, 11, 18 and 24): four tenant tables and
`search_procedures_scoped`, mcp-read's lexical search over approved, effective, tenant-permitted chunks.

Revision ID: 0011_governed_corpus
Revises: 0010_write_path

- `corpus_ingestions` (one row per tenant per ingestion run that changed something), `documents` (one row per
  tenant, document and version: the immutable attributes and the file's hash), `document_states` (the lifecycle as
  append-only rows: status and effective interval, the latest `seq` wins) and `chunks` (one per `## ` section: the
  body the section hash covers, its character offsets in the file, its word count and a stored `tsvector`, heading
  weight A and body weight D, under a GIN index). AM-20.2 gives the corpus no UPDATE, so a lifecycle change is a new
  state row (errata 94 and 95). Every key and cross-reference carries `tenant_id` (BS:246); the four tables are owned
  by `migrator`, granted INSERT and SELECT to `worker` (ingestion) and SELECT to `app_definer`, and nothing to anyone
  else, under ENABLE + FORCE RLS with the `tenant_isolation` policy (AM-20.5).
- `search_procedures_scoped(raw_handle, client_azp, query, query_embedding, asset_type, limit, mode)` (SA:461 with
  the caller's `azp`, erratum 93): `mcp_read` only. The handle decides the tenant through `_resolve_handle` (the
  lease FOR SHARE first, then the fence, expiry, revocation, `azp` and the read server); the run state and tool
  allowlist stay in Python (erratum 19). A chunk is returned only when its version's latest state is `approved`,
  `effective_from <= app.current_time() < effective_to` (or no `effective_to`), and the version is not retired:
  no later version of the same document that has left `draft` has reached its own `effective_from` (Plan L ruling
  7 as amended in round 1; revoking or expiring a successor never brings a predecessor back). With an asset type,
  only documents of that family or of none. The query is the OR of its own `english` lexemes, ranked by
  `ts_rank_cd`; only ranks above `app._min_rank()` (0.25, chosen on the development queries) are kept, and ties
  are broken by `evidence_id` in byte order (Plan L ruling 18). `mode = 'vector'` is refused
  (`VECTOR_MODE_UNAVAILABLE`) until T18 creates the
  embeddings; the `vector` type itself is bootstrap infrastructure (`scripts/skeleton.py ensure_extensions`), which
  this revision requires and never creates or drops, so the downgrade stays exact.

Every body, cell and caller is frozen here; the downgrade drops what this revision created and nothing else.
"""

from alembic import op
from ops_core import privileges

revision = "0011_governed_corpus"
down_revision = "0010_write_path"
branch_labels = None
depends_on = None

HEADER = "LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp SET app.tenant_id = ''"
HELPER_HEADER = "LANGUAGE plpgsql SET search_path = app, pg_temp"
# Plan D's excerpt bound, unchanged (the tool contract allows 8000; the silent cut stays with the tool, T16).
EXCERPT_CHARS_0011 = 500

# The pgvector type is created by the bootstrap, not here (Plan L ruling 2): a revision that created the extension
# could not drop it again without dropping every other user of it, and its downgrade would no longer be exact.
REQUIRE_VECTOR = """
DO $do$
BEGIN
    IF to_regtype('public.vector') IS NULL THEN
        RAISE EXCEPTION 'the vector type is missing: scripts/skeleton.py migrate creates the extension first';
    END IF;
END
$do$
"""

TABLES_0011 = ("corpus_ingestions", "documents", "document_states", "chunks")
MAIN_GRANTEES_0011 = ("api", "worker", "sweeper", "mcp_read", "mcp_exec", "operator", "app_definer")
POLICY_ROLES_0011 = ("api", "worker", "sweeper", "app_definer")
_INGEST = privileges.Grant(sel=True, ins=True)
_READ = privileges.Grant(sel=True)
# AM-20.2's corpus row (SA:431), applied to the two append-only tables the matrix lacks as well (erratum 95).
GRANTS_0011: dict[str, dict[str, privileges.Grant]] = {
    table: {"worker": _INGEST, "app_definer": _READ} for table in TABLES_0011
}

SCHEMA_CHANGES = (
    REQUIRE_VECTOR,
    (
        "CREATE TABLE app.corpus_ingestions ("
        " tenant_id uuid NOT NULL REFERENCES app.tenants (tenant_id),"
        " seq integer NOT NULL CHECK (seq >= 1),"
        " corpus_version text NOT NULL CHECK (corpus_version ~ '^[a-z0-9][a-z0-9.-]{0,99}$'),"
        " lock_sha256 text NOT NULL CHECK (lock_sha256 ~ '^[a-f0-9]{64}$'),"
        " documents_added integer NOT NULL CHECK (documents_added >= 0),"
        " states_added integer NOT NULL CHECK (states_added >= 0),"
        " ingested_at timestamptz NOT NULL DEFAULT now(),"
        " PRIMARY KEY (tenant_id, seq))"
    ),
    (
        "CREATE TABLE app.documents ("
        " tenant_id uuid NOT NULL,"
        " document_id text NOT NULL CHECK (document_id ~ '^[A-Z][A-Z0-9-]{1,63}$'),"
        " version text NOT NULL CHECK (version ~ '^[1-9][0-9]{0,8}$'),"
        " path text NOT NULL CHECK (path ~ '^[a-z0-9][a-z0-9-]{0,94}[.]md$'),"
        " content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[a-f0-9]{64}$'),"
        " asset_family text CHECK (asset_family ~ '^[a-z][a-z0-9_-]{0,39}$'),"
        " label text NOT NULL CHECK (label IN ('normal', 'injected', 'conflicting')),"
        " supersedes text,"
        " conflicts_with text,"
        " ingestion_seq integer NOT NULL,"
        " PRIMARY KEY (tenant_id, document_id, version),"
        " CONSTRAINT documents_ingestion_fkey FOREIGN KEY (tenant_id, ingestion_seq)"
        " REFERENCES app.corpus_ingestions (tenant_id, seq),"
        " CONSTRAINT documents_supersedes_fkey FOREIGN KEY (tenant_id, document_id, supersedes)"
        " REFERENCES app.documents (tenant_id, document_id, version))"
    ),
    (
        "CREATE TABLE app.document_states ("
        " tenant_id uuid NOT NULL,"
        " document_id text NOT NULL,"
        " version text NOT NULL,"
        " seq integer NOT NULL CHECK (seq >= 1),"
        " status text NOT NULL CHECK (status IN ('draft', 'approved', 'superseded', 'revoked')),"
        " effective_from timestamptz NOT NULL,"
        " effective_to timestamptz,"
        " ingestion_seq integer NOT NULL,"
        " PRIMARY KEY (tenant_id, document_id, version, seq),"
        " CHECK (effective_to IS NULL OR effective_to > effective_from),"
        " CONSTRAINT document_states_document_fkey FOREIGN KEY (tenant_id, document_id, version)"
        " REFERENCES app.documents (tenant_id, document_id, version),"
        " CONSTRAINT document_states_ingestion_fkey FOREIGN KEY (tenant_id, ingestion_seq)"
        " REFERENCES app.corpus_ingestions (tenant_id, seq))"
    ),
    (
        "CREATE TABLE app.chunks ("
        " tenant_id uuid NOT NULL,"
        " document_id text NOT NULL,"
        " version text NOT NULL,"
        " ordinal integer NOT NULL CHECK (ordinal >= 1),"
        " section text NOT NULL CHECK (char_length(section) BETWEEN 1 AND 120),"
        " evidence_id text NOT NULL CHECK (char_length(evidence_id) <= 160),"
        " body text NOT NULL CHECK (char_length(body) >= 1),"
        " content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[a-f0-9]{64}$'),"
        " start_offset integer NOT NULL CHECK (start_offset >= 0),"
        " end_offset integer NOT NULL,"
        " word_count integer NOT NULL CHECK (word_count >= 1),"
        " search tsvector GENERATED ALWAYS AS ("
        "setweight(to_tsvector('english'::regconfig, section), 'A')"
        " || setweight(to_tsvector('english'::regconfig, body), 'D')) STORED,"
        " PRIMARY KEY (tenant_id, evidence_id),"
        " UNIQUE (tenant_id, document_id, version, ordinal),"
        " CHECK (end_offset - start_offset = char_length(body)),"
        # ':' || 'v' rather than ':v': SQLAlchemy's text() would read `:v` as a bind parameter.
        " CHECK (evidence_id = document_id || ':' || 'v' || version || ':' || section),"
        " CONSTRAINT chunks_document_fkey FOREIGN KEY (tenant_id, document_id, version)"
        " REFERENCES app.documents (tenant_id, document_id, version))"
    ),
    "CREATE INDEX chunks_search ON app.chunks USING gin (search)",
    "ALTER TABLE app.corpus_ingestions OWNER TO migrator",
    "ALTER TABLE app.documents OWNER TO migrator",
    "ALTER TABLE app.document_states OWNER TO migrator",
    "ALTER TABLE app.chunks OWNER TO migrator",
)

# Plan L ruling 18 as round 1 decided it: the minimum rank, chosen on the 47 development queries (emulated on the
# draft text of the corpus); Task 5's live report (reports/retrieval/) is the measurement. `ts_rank_cd` is not
# normalised, so a longer query reaches the threshold more easily; tuning it is T18's, with the comparison. One
# helper, as `_dispatch_seconds()`, so a later revision changes it in one place.
MIN_RANK = f"""
CREATE OR REPLACE FUNCTION app._min_rank() RETURNS real
{HELPER_HEADER} IMMUTABLE AS $fn$
BEGIN
    RETURN 0.25;
END
$fn$;
ALTER FUNCTION app._min_rank() OWNER TO app_definer;
"""

SEARCH_PROCEDURES_SCOPED = f"""
CREATE OR REPLACE FUNCTION app.search_procedures_scoped(p_raw_handle text, p_client_azp text, p_query text,
                                                      p_query_embedding public.vector(768), p_asset_type text,
                                                      p_limit integer, p_mode text)
RETURNS TABLE (corpus_version text, results jsonb)
{HEADER} AS $fn$
DECLARE
    v_handle record;
    v_now timestamptz;
    v_lexemes text[];
    v_query tsquery;
BEGIN
    PERFORM app._authority('search_procedures_scoped', ARRAY['mcp_read']);
    -- The handle decides the tenant (BS:362), never an argument: the lease FOR SHARE first, then the fence, expiry,
    -- revocation, azp and the read server, as resolve_invocation. The run-state allowlist stays in Python (erratum 19).
    SELECT * INTO v_handle FROM app._resolve_handle(p_raw_handle, p_client_azp, 'read');
    PERFORM set_config('app.tenant_id', v_handle.tenant_id::text, true);
    IF p_mode = 'vector' THEN
        -- TODO(T18): exact pgvector search over app.embeddings under the same filters (R034).
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'VECTOR_MODE_UNAVAILABLE';
    END IF;
    IF p_mode IS DISTINCT FROM 'lexical' OR p_query IS NULL OR char_length(p_query) NOT BETWEEN 1 AND 500
       OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 8
       OR (p_asset_type IS NOT NULL AND char_length(p_asset_type) NOT BETWEEN 1 AND 40) THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'BAD_ARGUMENT';
    END IF;
    -- The tenant's latest ingestion names the corpus it searches; "none" before the first one (Plan L ruling 17).
    corpus_version := coalesce((SELECT i.corpus_version FROM corpus_ingestions i
                                WHERE i.tenant_id = v_handle.tenant_id ORDER BY i.seq DESC LIMIT 1), 'none');
    v_now := app.current_time();  -- the test clock in the test profile; read after the lease lock (SA:157)
    -- The OR of the query's own lexemes (Plan L ruling 18), so a whole user message still matches: anything but
    -- a-z and 0-9 becomes a space first, so every lexeme is a plain word the 'simple' parser passes through unchanged.
    v_lexemes := tsvector_to_array(to_tsvector('english', regexp_replace(lower(p_query), '[^a-z0-9]+', ' ', 'g')));
    IF cardinality(v_lexemes) = 0 THEN
        results := '[]'::jsonb;  -- only stop words: nothing to match, not an error
        RETURN NEXT;
        RETURN;
    END IF;
    v_query := to_tsquery('simple', array_to_string(v_lexemes, ' | '));
    WITH latest AS (
        -- AM-20 principle 2: the latest state is the highest seq, never a timestamp.
        SELECT DISTINCT ON (s.tenant_id, s.document_id, s.version)
               s.tenant_id, s.document_id, s.version, s.status, s.effective_from, s.effective_to
        FROM document_states s
        ORDER BY s.tenant_id, s.document_id, s.version, s.seq DESC
    ), effective AS (
        SELECT d.tenant_id, d.document_id, d.version, d.supersedes, d.asset_family, l.effective_from
        FROM documents d JOIN latest l USING (tenant_id, document_id, version)
        WHERE l.status = 'approved' AND l.effective_from <= v_now AND (l.effective_to IS NULL OR v_now < l.effective_to)
    ), permitted AS (
        -- Retired versions never come back (ruling 7, round 1): a later version that has left draft and reached its
        -- own effective_from retires every earlier one, whatever happens to it afterwards (revoked, expired).
        SELECT e.* FROM effective e
        WHERE NOT EXISTS (SELECT 1 FROM latest n WHERE n.tenant_id = e.tenant_id AND n.document_id = e.document_id
                                                    AND n.version::integer > e.version::integer
                                                    AND n.status <> 'draft' AND n.effective_from <= v_now)
          AND (p_asset_type IS NULL OR e.asset_family IS NULL OR e.asset_family = p_asset_type)
    ), ranked AS (
        SELECT c.evidence_id, c.document_id, c.version, c.section, c.content_sha256,
               left(c.body, {EXCERPT_CHARS_0011}) AS excerpt, p.effective_from, ts_rank_cd(c.search, v_query) AS rank
        FROM chunks c JOIN permitted p USING (tenant_id, document_id, version)
        WHERE c.search @@ v_query
    ), kept AS (
        -- Ranks at or below the minimum dropped; the byte-order tie-break makes a retry cite the same evidence
        -- whatever the database's collation (BUILD_SPEC section 6).
        SELECT * FROM ranked r WHERE r.rank > app._min_rank()
        ORDER BY r.rank DESC, r.evidence_id COLLATE "C" LIMIT p_limit
    )
    SELECT coalesce(jsonb_agg(jsonb_build_object('evidence_id', k.evidence_id, 'document_id', k.document_id,
                                                 'version', k.version, 'section', k.section,
                                                 'content_sha256', k.content_sha256, 'excerpt', k.excerpt,
                                                 'effective_from', k.effective_from, 'rank', k.rank)
                              ORDER BY k.rank DESC, k.evidence_id COLLATE "C"), '[]'::jsonb)
    INTO results FROM kept k;
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION app.search_procedures_scoped(text, text, text, public.vector, text, integer, text) OWNER TO app_definer;
"""

# (name, argument types, callers, body): frozen here (N1); the newest-revision test reads this tuple.
FUNCTIONS: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("_min_rank", "", (), MIN_RANK),
    (
        "search_procedures_scoped",
        "text, text, text, public.vector, text, integer, text",
        ("mcp_read",),
        SEARCH_PROCEDURES_SCOPED,
    ),
)
DOWNGRADE = (
    "DROP FUNCTION app.search_procedures_scoped(text, text, text, public.vector, text, integer, text)",
    "DROP FUNCTION app._min_rank()",
    "DROP TABLE app.chunks",  # its index and policy go with it
    "DROP TABLE app.document_states",
    "DROP TABLE app.documents",
    "DROP TABLE app.corpus_ingestions",
)


def upgrade() -> None:
    """The type check and the tables, their frozen cells and policy, then the helper and the function (each body
    first, then its grants, so REVOKE lands on it)."""
    for statement in SCHEMA_CHANGES:
        op.execute(statement)
    for statement in privileges.grant_statements(TABLES_0011, GRANTS_0011, revokees=MAIN_GRANTEES_0011):
        op.execute(statement)
    for statement in privileges.rls_statements(TABLES_0011, POLICY_ROLES_0011):
        op.execute(statement)
    for name, args, callers, body in FUNCTIONS:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)


def downgrade() -> None:
    """Back to 0010: the function and its helper, then the four tables (their rows, grants, index and policies with
    them); the `vector` extension stays, because the bootstrap made it."""
    for statement in DOWNGRADE:
        op.execute(statement)

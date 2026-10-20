"""The read tools' scope (T16; Plan M rulings 2, 3, 7 and 11): `asset_scope`, and `search_procedures_scoped` again with
the instant it decided permission, the requester's membership re-checked and the whole section as its excerpt.

Revision ID: 0012_asset_scope
Revises: 0011_governed_corpus

- `asset_scope(raw_handle, client_azp)` (SA:460 with the caller's `azp`, erratum 104): `mcp_read` only. The handle
  decides the run and the tenant through `_resolve_handle` (the lease FOR SHARE first, then the fence, expiry,
  revocation, `azp` and the read server); it returns one row, the run's `run_id`, `tenant_id`, `asset_id` and
  `[start_at, end_at)` with `as_of`, `app.current_time()` read after the lease lock: the instant asset-sim answers at
  (ruling 4). It checks no tool: the allowlist stays in Python (erratum 19), as for the search.
- `search_procedures_scoped` is re-created from revision 0011's own body with five textual changes and nothing else
  (ranking, filters and `_min_rank` stay byte for byte; a unit test reverses the changes and compares): it returns
  `(corpus_version, retrieved_at, results)`, `retrieved_at` being the instant its effectiveness rule ran at, which the
  tool stamps instead of the wall clock (Plan L final review, M4); the excerpt is the whole section, bounded at the
  contract's 8000 characters, and a row whose body was longer says so (`excerpt_cut`), which the tool turns into the
  envelope's `truncated` (ruling 11). CREATE OR REPLACE cannot change a return type, so the function is dropped and
  created again, and its grant applied again.
- Both re-check the run's requester at read time (R028, ruling 7): an active `requester` membership in the run's
  tenant, matched by tenant, subject and role because the run keeps no issuer (erratum 105); without one the call is
  refused exactly as a dead handle is (`OC008`, one message, SA:355).

The downgrade drops `asset_scope` and restores 0011's function exactly, from 0011's own frozen body (0009's pattern).
"""

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic import op
from ops_core import privileges

revision = "0012_asset_scope"
down_revision = "0011_governed_corpus"
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


REV0011 = _applied("0011_governed_corpus")
HEADER = "LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp SET app.tenant_id = ''"
SEARCH_ARGS = "text, text, text, public.vector, text, integer, text"
EXCERPT_CHARS_0012 = 8000  # the tool contract's excerpt bound (schemas/tool-result.schema.json)

# R028 (ruling 7), the same block in both functions: after the handle has set the tenant, so RLS admits the run's row
# and its memberships, and before anything else is read.
MEMBERSHIP_CHECK = """\
    -- R028 (Plan M ruling 7): the run's requester must still hold an active requester membership in the run's
    -- tenant, or the call is refused as a dead handle is (SA:355). The run keeps no issuer: tenant, subject and
    -- role identify the row (erratum 105).
    IF NOT EXISTS (SELECT 1 FROM runs r JOIN memberships m ON m.tenant_id = r.tenant_id AND m.subject = r.requester
                   WHERE r.run_id = v_handle.run_id AND m.role = 'requester' AND m.active) THEN
        RAISE EXCEPTION 'handle_rejected' USING ERRCODE = 'OC008';
    END IF;
"""

ASSET_SCOPE = f"""
CREATE OR REPLACE FUNCTION app.asset_scope(p_raw_handle text, p_client_azp text)
RETURNS TABLE (run_id uuid, tenant_id uuid, asset_id text, start_at timestamptz, end_at timestamptz,
               as_of timestamptz)
{HEADER} AS $fn$
DECLARE
    v_handle record;
    v_run runs%ROWTYPE;
BEGIN
    PERFORM app._authority('asset_scope', ARRAY['mcp_read']);
    -- The handle decides the run and the tenant (BS:362), never an argument: the lease FOR SHARE first, then the
    -- fence, expiry, revocation, azp and the read server. The tool allowlist stays in Python (erratum 19).
    SELECT * INTO v_handle FROM app._resolve_handle(p_raw_handle, p_client_azp, 'read');
    PERFORM set_config('app.tenant_id', v_handle.tenant_id::text, true);
{MEMBERSHIP_CHECK}    SELECT * INTO v_run FROM runs r WHERE r.run_id = v_handle.run_id;
    run_id := v_run.run_id;
    tenant_id := v_handle.tenant_id;
    asset_id := v_run.asset_id;
    start_at := v_run.start_at;
    end_at := v_run.end_at;
    as_of := app.current_time();  -- the instant asset-sim answers at; read after the lease lock (SA:157)
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION app.asset_scope(text, text) OWNER TO app_definer;
"""

# Revision 0011's body, changed in exactly these places; each `old` must occur once (checked before anything runs).
TENANT_0011 = "    PERFORM set_config('app.tenant_id', v_handle.tenant_id::text, true);\n"
CLOCK_0011 = (
    "    v_now := app.current_time();  -- the test clock in the test profile; read after the lease lock (SA:157)\n"
)
INSTANT_0012 = (
    "    retrieved_at := v_now;  -- the instant permission was decided; the tool stamps it (Plan M ruling 3)\n"
)
CHANGES_0012: tuple[tuple[str, str], ...] = (
    (
        "RETURNS TABLE (corpus_version text, results jsonb)\n",
        "RETURNS TABLE (corpus_version text, retrieved_at timestamptz, results jsonb)\n",
    ),
    (TENANT_0011, TENANT_0011 + MEMBERSHIP_CHECK),
    (CLOCK_0011, CLOCK_0011 + INSTANT_0012),
    (
        "left(c.body, 500) AS excerpt, p.effective_from,",
        (
            f"left(c.body, {EXCERPT_CHARS_0012}) AS excerpt,\n"
            f"               char_length(c.body) > {EXCERPT_CHARS_0012} AS excerpt_cut, p.effective_from,"
        ),
    ),
    (
        "'effective_from', k.effective_from, 'rank', k.rank)\n",
        (
            "'effective_from', k.effective_from, 'rank', k.rank,\n"
            "                                                 'excerpt_cut', k.excerpt_cut)\n"
        ),
    ),
)


def changed(body: str) -> str:
    """Revision 0011's search body with this revision's changes applied.

    Raises:
        RuntimeError: a change's text is not in the body exactly once (0011's body is not the one this revision was
            written against).
    """
    for old, new in CHANGES_0012:
        if body.count(old) != 1:
            raise RuntimeError("revision 0011's search_procedures_scoped no longer carries a text 0012 changes")
        body = body.replace(old, new)
    return body


SEARCH_PROCEDURES_SCOPED = changed(REV0011.SEARCH_PROCEDURES_SCOPED)
# (name, argument types, callers, body): frozen here (N1); the newest-revision test reads this tuple.
FUNCTIONS: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("asset_scope", "text, text", ("mcp_read",), ASSET_SCOPE),
    ("search_procedures_scoped", SEARCH_ARGS, ("mcp_read",), SEARCH_PROCEDURES_SCOPED),
)
# What downgrade() re-creates, from the applied revision's own body: (name, args, callers, body).
RESTORED: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("search_procedures_scoped", SEARCH_ARGS, ("mcp_read",), REV0011.SEARCH_PROCEDURES_SCOPED),
)
DROP_ASSET_SCOPE = "DROP FUNCTION app.asset_scope(text, text)"
DROP_SEARCH = f"DROP FUNCTION app.search_procedures_scoped({SEARCH_ARGS})"


def upgrade() -> None:
    """The search dropped (its return type changes), then each function's body and its grants: REVOKE from PUBLIC,
    then EXECUTE to `mcp_read` alone (SA:446)."""
    op.execute(DROP_SEARCH)
    for name, args, callers, body in FUNCTIONS:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)


def downgrade() -> None:
    """Back to 0011: `asset_scope` dropped, and the search dropped and created again from 0011's body with its
    grants; no row is touched."""
    op.execute(DROP_ASSET_SCOPE)
    op.execute(DROP_SEARCH)
    for name, args, callers, body in RESTORED:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)

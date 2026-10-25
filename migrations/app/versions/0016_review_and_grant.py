"""Review, revision, the manual path and the final gate (T21; Plan R rulings 1-18; AM-10, AM-11, AM-13, AM-20.3).

Revision ID: 0016_review_and_grant
Revises: 0015_checkpoints

Schema: `runs.authors` (the run's content authors: the requester, then every revision and manual-proposal author;
SA:453, SA:539, erratum 132), `runs.asset_observed_at` (the asset status observation the grant checks, R116) and
`runs.workflow_version` (BS:342, written by the worker at the first claim); `drafts.source` (`model` or `manual`);
`run_manifests` keyed on `(run_id, revision)`, one manifest per revision (erratum 125 closes); and `feedback`
(BS:243, SA:428: api INSERT and SELECT, tenant RLS, nothing else).

Functions, each a definer or an internal helper as the frozen tuple below names it:

- `_asset_lock` and `_asset_guard` (AM-13 SA:284-289, SA:189): the per-(tenant, asset) advisory lock, which every
  caller takes before any row lock of its own, and the two refusal sets: (a) another run of the asset with an
  overlapping interval whose grant's latest attempt is unresolved (not ABANDONED_UNVERIFIED), (b) another run with a
  committed incident (SUCCEEDED, or SUCCEEDED late evidence) unless `supersedes_run_id` names it. Across
  conversations (SA:288). `freeze_proposal`, `create_manual_proposal` and `grant_execution` apply it.
- `_run_revision`: a run's current revision, 1 plus its `proposal.revised` events. A revision whose model draft is
  refused at freeze freezes nothing, so a run's proposal revisions may skip a number; `(run_id, revision)` stays unique.
- `_cited_permitted`: the cited sections whose version is still approved, effective and not retired, by the search's
  own filter text (sliced from revision 0012's body, as revision 0013 did), for the grant's source recheck (BS:425)
  and the manual proposal's evidence.
- `_expire` / `expire_proposal` (SA:457): AWAITING_APPROVAL or APPROVED with an active proposal past `expires_at` →
  BLOCKED_REVIEW(`expired`) with `review.blocked`; the sweeper and the API's own unit call it (ruling 5).
- `freeze_proposal`: the asset lock first, the revision is the run's current one, `workflow_version` the run's
  (ruling 18), `expires_at` the payload's and inside `(now, now + 15 min + 60 s]` (ruling 5), `authored_by` from
  `runs.authors` (ruling 4), and the asset guard, whose refusal commits BLOCKED_REVIEW instead of a proposal.
- `record_decision` takes `expected_revision` (erratum 131): independence first (403), then first-decision-wins,
  the revision, the hash and expiry, all under `runs FOR UPDATE`, each its own DETAIL (ruling 3).
- `create_revision` (SA:455; rulings 1, 2, 4, 6), `request_cancel` (SA:458; ruling 12), `prepare_manual_proposal`
  and `create_manual_proposal` (SA:456; ruling 7: the API builds the canonical bytes between the two, in one unit).
- `grant_execution` (SA:462; rulings 9-11): the asset lock first; binding refusals raise as before plus
  HASH_MISMATCH; `expired`, `authority_revoked`, `stale_evidence` and the guard's two reasons commit BLOCKED_REVIEW and
  return a row whose `refusal` names the reason; MEMBERSHIP_STALE still raises (deferred).
- `create_run` validates `supersedes_run_id` against the tenant and the asset (erratum 138) and records the author
  set; `_resolve_handle` lets an execute job hold a read handle (erratum 137); `asset_scope` and
  `search_procedures_scoped` refuse MEMBERSHIP_STALE (ruling 14, erratum 105); `_append_event` admits the feedback
  keys on `feedback.recorded` only (erratum 136); `search_procedures_api` is the manual baseline's search (erratum 135).

Derived bodies are applied revisions' own text with named changes, each checked to match once (the 0010 pattern).
The downgrade restores 0015 exactly for a database without revisions past 1 (a manifest of a later revision is
deleted with its key) by re-running the applied revisions' bodies, loaded from their files.
"""

import importlib.util
import re
from pathlib import Path
from types import ModuleType

from alembic import op
from ops_core import privileges

revision = "0016_review_and_grant"
down_revision = "0015_checkpoints"
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


REV0002 = _applied("0002_roles_grants_rls")
REV0003 = _applied("0003_run_path_functions")
REV0004 = _applied("0004_write_path_functions")
REV0008 = _applied("0008_journal_outbox")
REV0009 = _applied("0009_handle_binding")
REV0010 = _applied("0010_write_path")
REV0012 = _applied("0012_asset_scope")
REV0013 = _applied("0013_embeddings")
HEADER = "LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp SET app.tenant_id = ''"
HELPER_HEADER = "LANGUAGE plpgsql SET search_path = app, pg_temp"
GRANT_COLUMNS = REV0004.GRANT_COLUMNS
SEARCH_ARGS = REV0012.SEARCH_ARGS
# AM-10 "Reasons": what a refused freeze, manual proposal or grant records (states.py `_ASSET_GUARD`, `_GRANT_REFUSAL`).
EXPIRY_BOUND = "interval '16 minutes'"  # ruling 5: BS:559's 15-minute expiry plus a minute of clock skew


def _derived(body: str, changes: tuple[tuple[str, str], ...]) -> str:
    """`body` with each change applied; a change that does not match exactly once means the applied body moved."""
    for old, new in changes:
        if body.count(old) != 1:
            raise RuntimeError(f"an applied body no longer carries {old!r} exactly once")
        body = body.replace(old, new)
    return body


def _between(body: str, start: str, end: str) -> str:
    """The text of `body` from `start` up to, not including, `end`; each must occur exactly once."""
    if body.count(start) != 1 or body.count(end) != 1:
        raise RuntimeError("revision 0012's search_procedures_scoped no longer carries a text 0016 reuses")
    return body[body.index(start) : body.index(end)]


def literal_list(values: tuple[str, ...]) -> str:
    """Words as a SQL literal list, each checked against a safe pattern before it is inlined."""
    if not all(re.fullmatch(r"[a-z_.]+", v) for v in values):
        raise RuntimeError("a value is not safe to inline into SQL")
    return ", ".join(f"'{v}'" for v in values)


# ---------------------------------------------------------------------------------------------------------- schema
TABLES_0016 = ("runs", "drafts", "feedback")
MAIN_GRANTEES_0016 = ("api", "worker", "sweeper", "mcp_read", "mcp_exec", "operator", "app_definer")
POLICY_ROLES_0016 = ("api", "worker", "sweeper", "app_definer")
_S = privileges.Grant(sel=True)
_SI = privileges.Grant(sel=True, ins=True)
GRANTS_0016: dict[str, dict[str, privileges.Grant]] = {
    "runs": {
        "api": privileges.Grant(sel=True, upd=("cancel_requested", "cancel_requested_at")),
        # Rulings 9 and 18: the worker records the asset observation and the run's workflow version.
        "worker": privileges.Grant(
            sel=True, upd=("checkpoint_id", "budget_used", "asset_observed_at", "workflow_version")
        ),
        "sweeper": _S,
        # create_revision clears the stored checkpoint and appends an author; request_cancel sets the flag (SA:458).
        "app_definer": privileges.Grant(
            ins=True,
            sel=True,
            upd=(
                "state",
                "state_version",
                "reason",
                "active_proposal_id",
                "next_event_seq",
                "slot_held",
                "supersedes_run_id",
                "updated_at",
                "authors",
                "checkpoint_id",
                "cancel_requested",
                "cancel_requested_at",
            ),
        ),
    },
    "drafts": {"worker": _SI, "app_definer": _SI},  # create_manual_proposal inserts its own drafts row (ruling 7)
    "feedback": {"api": _SI},  # SA:428; `reviewed` is set by nobody in v1 (ruling 8)
}
# 0002's cells on the two tables this revision changes, for the downgrade (not named GRANTS_*: the newest-revision
# test folds every GRANTS_* attribute into the live matrix check).
RESTORED_CELLS: dict[str, dict[str, privileges.Grant]] = {
    "runs": REV0002.GRANTS_0002["runs"],
    "drafts": REV0002.GRANTS_0002["drafts"],
}
FEEDBACK_CATEGORIES_0016 = ("wrong_evidence", "missing_evidence", "wrong_conclusion", "unclear", "other")
SCHEMA_CHANGES = (
    (
        "ALTER TABLE app.runs ADD COLUMN authors uuid[], ADD COLUMN asset_observed_at timestamptz,"
        " ADD COLUMN workflow_version text CHECK (char_length(workflow_version) BETWEEN 1 AND 60)"
    ),
    "UPDATE app.runs SET authors = ARRAY[requester]",
    (
        "ALTER TABLE app.runs ALTER COLUMN authors SET NOT NULL,"
        " ADD CONSTRAINT runs_authors_check CHECK (cardinality(authors) BETWEEN 1 AND 8)"
    ),
    "ALTER TABLE app.drafts ADD COLUMN source text NOT NULL DEFAULT 'model' CHECK (source IN ('model', 'manual'))",
    "ALTER TABLE app.run_manifests ADD COLUMN revision integer NOT NULL DEFAULT 1 CHECK (revision >= 1)",
    (
        "ALTER TABLE app.run_manifests ALTER COLUMN revision DROP DEFAULT, DROP CONSTRAINT run_manifests_pkey,"
        " ADD PRIMARY KEY (run_id, revision)"
    ),
    (
        "CREATE TABLE app.feedback ("
        " feedback_id uuid PRIMARY KEY,"
        " tenant_id uuid NOT NULL,"
        " run_id uuid NOT NULL,"
        " subject_kind text NOT NULL CHECK (subject_kind IN ('run', 'proposal', 'event')),"
        " subject_id uuid NOT NULL,"
        f" category text NOT NULL CHECK (category IN ({literal_list(FEEDBACK_CATEGORIES_0016)})),"
        " text text CHECK (char_length(text) <= 2000),"
        " author uuid NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " reviewed boolean NOT NULL DEFAULT false,"
        " CONSTRAINT feedback_tenant_run_fkey FOREIGN KEY (tenant_id, run_id) REFERENCES app.runs (tenant_id, run_id))"
    ),
    "ALTER TABLE app.feedback OWNER TO migrator",
)

# ----------------------------------------------------------------------------------------------- derived helpers
# The event payload keys (ops_core.outcomes.PAYLOAD_KEYS, frozen here): 0008's plus the feedback event's three.
PAYLOAD_KEYS_0016 = (*REV0008.PAYLOAD_KEYS_0008, "subject_kind", "subject_id", "category")
FEEDBACK_RULE = (
    "    -- T21 (ruling 8, erratum 136): a feedback event names its subject and category, and no other type does.\n"
    "    IF p_payload ?| ARRAY['subject_kind', 'subject_id', 'category'] AND p_type <> 'feedback.recorded' THEN\n"
    "        RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'feedback keys';\n"
    "    END IF;\n"
)
STATUS_RULE_0008 = (
    "        RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'status';\n    END IF;\n"
)
APPEND_EVENT_CHANGES = (
    (f"ARRAY[{REV0008.PAYLOAD_KEYS}]", f"ARRAY[{literal_list(PAYLOAD_KEYS_0016)}]"),
    (STATUS_RULE_0008, STATUS_RULE_0008 + FEEDBACK_RULE),
)
APPEND_EVENT_HELPER = _derived(REV0008.APPEND_EVENT_HELPER, APPEND_EVENT_CHANGES)

SERVER_CHECK_0009 = "    IF v_job_server IS NULL OR v_job_server <> p_server OR v_ctx.server <> p_server THEN\n"
EXECUTE_READ = (
    "    -- T21 (ruling 9, erratum 137): an execute job also holds a read handle, for the asset status it reads again\n"
    "    -- before its grant (R116); the stored server must say read too.\n"
    "    IF v_job_type = 'execute' AND p_server = 'read' AND v_ctx.server = 'read' THEN\n"
    "        v_job_server := 'read';\n"
    "    END IF;\n"
)
RESOLVE_CHANGES = ((SERVER_CHECK_0009, EXECUTE_READ + SERVER_CHECK_0009),)
RESOLVE_HANDLE = _derived(REV0009.RESOLVE_HANDLE, RESOLVE_CHANGES)

SUPERSEDES_0003 = (
    "        SELECT 1 FROM runs r WHERE r.run_id = p_supersedes_run_id AND r.tenant_id = p_tenant_id\n"
    "                               AND r.conversation_id = p_conversation_id) THEN\n"
)
SUPERSEDES_0016 = (
    "        -- T21 (erratum 138): the superseded incident is the asset's, in any conversation of its tenant\n"
    "        -- (SA:286).\n"
    "        SELECT 1 FROM runs r WHERE r.run_id = p_supersedes_run_id AND r.tenant_id = p_tenant_id\n"
    "                               AND r.asset_id = v_asset_id) THEN\n"
)
INSERT_RUN_0003 = (
    "                          asset_id, start_at, end_at, state, state_version, slot_held, next_event_seq)\n"
    "        VALUES (v_run_id, p_tenant_id, p_conversation_id, v_message_id, v_requester, p_intent,"
    " p_supersedes_run_id,\n"
    "                v_asset_id, v_start, v_end, 'QUEUED', 1, true, 0);\n"
)
INSERT_RUN_0016 = (
    "                          asset_id, start_at, end_at, state, state_version, slot_held, next_event_seq, authors)\n"
    "        VALUES (v_run_id, p_tenant_id, p_conversation_id, v_message_id, v_requester, p_intent,"
    " p_supersedes_run_id,\n"
    "                v_asset_id, v_start, v_end, 'QUEUED', 1, true, 0, ARRAY[v_requester]);\n"
)
CREATE_RUN_CHANGES = ((SUPERSEDES_0003, SUPERSEDES_0016), (INSERT_RUN_0003, INSERT_RUN_0016))
CREATE_RUN = _derived(REV0003.CREATE_RUN, CREATE_RUN_CHANGES)

# Ruling 14 (erratum 105): the read path refuses a requester whose membership the sync has not stamped in 120 s, the
# write gate's bound (0005's MEMBERSHIP_STALE), as a deferral the caller may retry.
STALE_CHECK = """\
    -- T21 (ruling 14): the same row must have been stamped by the membership sync within 120 s (the write gate's
    -- bound, revision 0005); otherwise the call is deferred, not refused for good.
    IF NOT EXISTS (SELECT 1 FROM runs r JOIN memberships m ON m.tenant_id = r.tenant_id AND m.subject = r.requester
                   WHERE r.run_id = v_handle.run_id AND m.role = 'requester' AND m.active
                     AND m.synced_at >= app.current_time() - interval '120 seconds') THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'MEMBERSHIP_STALE';
    END IF;
"""
FRESH_READ = ((REV0012.MEMBERSHIP_CHECK, REV0012.MEMBERSHIP_CHECK + STALE_CHECK),)
ASSET_SCOPE = _derived(REV0012.ASSET_SCOPE, FRESH_READ)
SEARCH_PROCEDURES_SCOPED = _derived(REV0013.SEARCH_PROCEDURES_SCOPED, FRESH_READ)

# The search's own filters (0012's `latest`, `effective`, `permitted`) and its lexical query, byte for byte.
FILTERS_0012 = _between(REV0012.SEARCH_PROCEDURES_SCOPED, "    WITH latest AS (\n", "    ), ranked AS (\n")
QUERY_0012 = _between(REV0012.SEARCH_PROCEDURES_SCOPED, "    WITH latest AS (\n", "    INTO results FROM kept k;\n")

# ------------------------------------------------------------------------------------------------- new helpers
RUN_REVISION = f"""
CREATE OR REPLACE FUNCTION app._run_revision(p_run_id uuid) RETURNS integer
{HELPER_HEADER} AS $fn$
BEGIN
    -- Ruling 1: revision N is the run's Nth request; each create_revision journals one proposal.revised.
    RETURN 1 + (SELECT count(*) FROM events e WHERE e.run_id = p_run_id AND e.type = 'proposal.revised')::integer;
END
$fn$;
ALTER FUNCTION app._run_revision(uuid) OWNER TO app_definer;
"""

ASSET_LOCK = f"""
CREATE OR REPLACE FUNCTION app._asset_lock(p_tenant_id uuid, p_asset_id text) RETURNS void
{HELPER_HEADER} AS $fn$
BEGIN
    -- SA:189: one key per (tenant, asset); the idempotency scope's two-key locks live in another space (erratum 37).
    PERFORM pg_advisory_xact_lock(hashtextextended(p_tenant_id::text || ':' || p_asset_id, 0));
END
$fn$;
ALTER FUNCTION app._asset_lock(uuid, text) OWNER TO app_definer;
"""

ASSET_GUARD = f"""
CREATE OR REPLACE FUNCTION app._asset_guard(p_tenant_id uuid, p_asset_id text, p_start_at timestamptz,
                                            p_end_at timestamptz, p_run_id uuid, p_supersedes_run_id uuid)
RETURNS TABLE (reason text, blocking_run_id uuid)
{HELPER_HEADER} AS $fn$
BEGIN
    -- AM-13 (SA:284-286), called under _asset_lock. Overlap is half-open: a < d and c < b (SA:283). Other runs of the
    -- tenant in any conversation (SA:288). (a) An unresolved action: a grant whose latest attempt is not RESOLVED,
    -- unless the operator acknowledged it (ABANDONED_UNVERIFIED, SA:130).
    SELECT r.run_id INTO blocking_run_id
    FROM runs r JOIN execution_grant g ON g.run_id = r.run_id CROSS JOIN LATERAL app._latest_attempt(g.action_id) la
    WHERE r.tenant_id = p_tenant_id AND r.asset_id = p_asset_id AND r.run_id <> p_run_id
      AND r.start_at < p_end_at AND p_start_at < r.end_at
      AND la.state <> 'RESOLVED' AND r.state <> 'ABANDONED_UNVERIFIED'
    ORDER BY r.run_id LIMIT 1;
    IF FOUND THEN
        reason := 'asset_action_unresolved';
        RETURN NEXT;
        RETURN;
    END IF;
    -- (b) A committed incident, however late its evidence arrived (R6-H5), unless the request named it (R125).
    SELECT r.run_id INTO blocking_run_id
    FROM runs r
    WHERE r.tenant_id = p_tenant_id AND r.asset_id = p_asset_id AND r.run_id <> p_run_id
      AND r.start_at < p_end_at AND p_start_at < r.end_at
      AND r.run_id IS DISTINCT FROM p_supersedes_run_id
      AND (r.state = 'SUCCEEDED'
           OR EXISTS (SELECT 1 FROM events e WHERE e.run_id = r.run_id AND e.type = 'action.late_evidence'
                                                AND e.payload->>'outcome' = 'SUCCEEDED'))
    ORDER BY r.run_id LIMIT 1;
    IF FOUND THEN
        reason := 'asset_incident_exists';
        RETURN NEXT;
    END IF;
END
$fn$;
ALTER FUNCTION app._asset_guard(uuid, text, timestamptz, timestamptz, uuid, uuid) OWNER TO app_definer;
"""

CITED_PERMITTED = f"""
CREATE OR REPLACE FUNCTION app._cited_permitted(p_tenant_id uuid, p_evidence_ids text[])
RETURNS TABLE (evidence_id text, version text, content_sha256 text)
{HELPER_HEADER} AS $fn$
#variable_conflict use_column
DECLARE
    v_now timestamptz := app.current_time();
    p_asset_type text := NULL;  -- the search's family filter, off: a cited section counts in any family
BEGIN
    -- BS:425 and ruling 7: the search's own filters (revision 0012's text, byte for byte), so a section the search
    -- would no longer return (revoked, expired or retired) is not permitted here either.
    RETURN QUERY
{FILTERS_0012}    )
    SELECT c.evidence_id, c.version, c.content_sha256
    FROM chunks c JOIN permitted p USING (tenant_id, document_id, version)
    WHERE c.tenant_id = p_tenant_id AND c.evidence_id = ANY (p_evidence_ids);
END
$fn$;
ALTER FUNCTION app._cited_permitted(uuid, text[]) OWNER TO app_definer;
"""

EXPIRE = f"""
CREATE OR REPLACE FUNCTION app._expire(p_run_id uuid) RETURNS text
{HELPER_HEADER} AS $fn$
DECLARE
    v_run runs%ROWTYPE;
    v_expires timestamptz;
BEGIN
    SELECT * INTO v_run FROM runs r WHERE r.run_id = p_run_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'run';
    END IF;
    IF v_run.state NOT IN ('AWAITING_APPROVAL', 'APPROVED') THEN
        RETURN v_run.state;
    END IF;
    SELECT p.expires_at INTO v_expires FROM proposals p WHERE p.proposal_id = v_run.active_proposal_id;
    -- SA:457, compared after the lock on the application clock (SA:157): an APPROVED run expires before its grant
    -- too (SA:140), and nothing extends an expiry (BS:684).
    IF v_expires IS NULL OR v_expires >= app.current_time() THEN
        RETURN v_run.state;
    END IF;
    PERFORM app._transition(p_run_id, 'BLOCKED_REVIEW', 'expire_proposal', 'expired', NULL, 'review.blocked',
                            jsonb_build_object('proposal_id', v_run.active_proposal_id, 'reason', 'expired',
                                               'message',
                                               'the proposal expired; a revision and a new review are needed'));
    RETURN 'BLOCKED_REVIEW';
END
$fn$;
ALTER FUNCTION app._expire(uuid) OWNER TO app_definer;
"""

# ---------------------------------------------------------------------------------------------- definers
EXPIRE_PROPOSAL = f"""
CREATE OR REPLACE FUNCTION app.expire_proposal(p_run_id uuid) RETURNS text
{HEADER} AS $fn$
BEGIN
    PERFORM app._authority('expire_proposal', ARRAY['sweeper', 'api']);
    IF p_run_id IS NULL THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'INVALID_ARGUMENT';
    END IF;
    PERFORM app._tenant_of_run(p_run_id);
    RETURN app._expire(p_run_id);
END
$fn$;
ALTER FUNCTION app.expire_proposal(uuid) OWNER TO app_definer;
"""

FREEZE_PROPOSAL = f"""
CREATE OR REPLACE FUNCTION app.freeze_proposal(p_run_id uuid, p_draft_id uuid, p_payload_canonical bytea,
                                               p_expires_at timestamptz)
RETURNS TABLE (proposal_id uuid, revision integer, state text, reason text, state_version integer)
{HEADER} AS $fn$
DECLARE
    v_tenant uuid;
    v_asset text;
    v_run runs%ROWTYPE;
    v_draft drafts%ROWTYPE;
    v_sha text := encode(sha256(p_payload_canonical), 'hex');
    v_payload jsonb;
    v_proposal_id uuid;
    v_revision integer;
    v_reason text;
    v_blocking uuid;
BEGIN
    PERFORM app._authority('freeze_proposal', ARRAY['worker']);
    v_tenant := app._tenant_of_run(p_run_id);
    -- SA:189: the asset guard's lock before the run's (the worker's unit took it before its fence; it is re-entrant).
    SELECT r.asset_id INTO v_asset FROM runs r WHERE r.run_id = p_run_id;
    PERFORM app._asset_lock(v_tenant, v_asset);
    SELECT * INTO v_run FROM runs r WHERE r.run_id = p_run_id FOR UPDATE;
    IF v_run.state <> 'DRAFTING' THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003',
                                                 DETAIL = format('run %s is %s', p_run_id, v_run.state);
    END IF;
    IF v_run.intent = 'answer_only' THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'ANSWER_ONLY';
    END IF;
    SELECT * INTO v_draft FROM drafts d WHERE d.id = p_draft_id AND d.run_id = p_run_id AND d.validated;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'draft';
    END IF;
    -- The bytes stored are the bytes validated (SA:453): the hash is recomputed here over what arrived.
    IF v_draft.draft_sha256 <> v_sha THEN
        RAISE EXCEPTION 'hash_mismatch' USING ERRCODE = 'OC007', DETAIL = 'draft';
    END IF;
    v_payload := convert_from(p_payload_canonical, 'UTF8')::jsonb;
    -- SA:154: the asset and the interval are the run's, so the asset guard below judges what the payload acts on
    -- (as create_manual_proposal checks them; Plan R round 1, I2).
    IF (v_payload->>'run_id') IS DISTINCT FROM p_run_id::text
       OR (v_payload->>'tenant_id') IS DISTINCT FROM v_tenant::text
       OR (v_payload->>'asset_id') IS DISTINCT FROM v_run.asset_id
       OR (v_payload->>'start_at')::timestamptz IS DISTINCT FROM v_run.start_at
       OR (v_payload->>'end_at')::timestamptz IS DISTINCT FROM v_run.end_at THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'PAYLOAD_RUN_MISMATCH';
    END IF;
    -- supersedes_run_id is a run field written by create_run or create_revision (SA:154); the document carries it.
    IF (v_payload->>'supersedes_run_id') IS DISTINCT FROM v_run.supersedes_run_id::text THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'SUPERSEDES_MISMATCH';
    END IF;
    -- Ruling 1: the run's current revision, which no proposal of the run has frozen yet.
    v_revision := app._run_revision(p_run_id);
    IF (v_payload->>'revision')::integer IS DISTINCT FROM v_revision
       OR EXISTS (SELECT 1 FROM proposals p WHERE p.run_id = p_run_id AND p.revision >= v_revision) THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003', DETAIL = 'revision';
    END IF;
    -- Ruling 18: the version the worker recorded at the run's first claim (BS:342).
    IF (v_payload->>'workflow_version') IS DISTINCT FROM v_run.workflow_version THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'WORKFLOW_VERSION';
    END IF;
    -- Ruling 5: the hashed expiry is the stored one, set on the application clock and never beyond the 15 minutes.
    IF p_expires_at IS NULL OR (v_payload->>'expires_at')::timestamptz IS DISTINCT FROM p_expires_at
       OR p_expires_at <= app.current_time() OR p_expires_at > app.current_time() + {EXPIRY_BOUND} THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'EXPIRY';
    END IF;
    -- AM-13: a refusal freezes nothing and commits BLOCKED_REVIEW, naming the blocking run (ruling 10).
    SELECT g.reason, g.blocking_run_id INTO v_reason, v_blocking
    FROM app._asset_guard(v_tenant, v_run.asset_id, v_run.start_at, v_run.end_at, p_run_id,
                          v_run.supersedes_run_id) g;
    IF v_reason IS NOT NULL THEN
        state_version := app._transition(p_run_id, 'BLOCKED_REVIEW', 'freeze_proposal', v_reason, NULL,
                                         'review.blocked',
                                         jsonb_build_object('reason', v_reason,
                                                            'message', format('blocked by run %s', v_blocking)));
        revision := v_revision;
        state := 'BLOCKED_REVIEW';
        reason := v_reason;
        RETURN NEXT;
        RETURN;
    END IF;
    v_proposal_id := (v_payload->>'proposal_id')::uuid;
    -- Ruling 4: every content author (SA:453, SA:539), kept outside the hash.
    INSERT INTO proposals (proposal_id, tenant_id, run_id, revision, draft_id, payload, payload_canonical,
                           payload_sha256, canonicalization_version, authored_by, expires_at, frozen_at)
    VALUES (v_proposal_id, v_tenant, p_run_id, v_revision, p_draft_id, v_payload, p_payload_canonical, v_sha, 1,
            v_run.authors, p_expires_at, app.current_time());
    UPDATE runs SET active_proposal_id = v_proposal_id WHERE runs.run_id = p_run_id;
    state_version := app._transition(p_run_id, 'AWAITING_APPROVAL', 'freeze_proposal', NULL, NULL, 'proposal.ready',
                                     jsonb_build_object('proposal_id', v_proposal_id));
    proposal_id := v_proposal_id;
    revision := v_revision;
    state := 'AWAITING_APPROVAL';
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION app.freeze_proposal(uuid, uuid, bytea, timestamptz) OWNER TO app_definer;
"""

RECORD_DECISION = f"""
CREATE OR REPLACE FUNCTION app.record_decision(p_tenant_id uuid, p_proposal_id uuid, p_reviewer uuid,
                                               p_expected_revision integer, p_expected_payload_sha256 text,
                                               p_decision text, p_reason text, p_idempotency_key text)
RETURNS TABLE (run_id uuid, state text, state_version integer)
{HEADER} AS $fn$
DECLARE
    v_proposal proposals%ROWTYPE;
    v_run runs%ROWTYPE;
BEGIN
    PERFORM app._authority('record_decision', ARRAY['api']);
    -- A NULL would make every comparison below UNKNOWN and slip past its guard, so refuse before any read.
    IF p_tenant_id IS NULL OR p_proposal_id IS NULL OR p_reviewer IS NULL OR p_decision IS NULL
       OR p_expected_revision IS NULL OR p_expected_payload_sha256 IS NULL
       OR p_decision NOT IN ('approve', 'reject') THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'INVALID_ARGUMENT';
    END IF;
    -- The API is the identity trust anchor (SA:454): tenant and reviewer are arguments it has authenticated.
    PERFORM set_config('app.tenant_id', p_tenant_id::text, true);
    SELECT * INTO v_proposal FROM proposals p WHERE p.proposal_id = p_proposal_id AND p.tenant_id = p_tenant_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'proposal';
    END IF;
    SELECT * INTO v_run FROM runs r WHERE r.run_id = v_proposal.run_id FOR UPDATE;
    -- Independence first (BS:466, SA:539): a current reviewer who is neither requester nor content author is refused
    -- whatever the run's state, and the API never records that refusal (BS:301).
    IF NOT EXISTS (SELECT 1 FROM memberships m WHERE m.tenant_id = p_tenant_id AND m.subject = p_reviewer
                                                     AND m.role = 'reviewer' AND m.active) THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'NOT_REVIEWER';
    END IF;
    IF p_reviewer = v_run.requester OR p_reviewer = ANY (v_proposal.authored_by) THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'SELF_REVIEW';
    END IF;
    -- Ruling 3: every rule under the runs lock, each its own code. First decision wins (UNIQUE (proposal_id)).
    IF EXISTS (SELECT 1 FROM decisions d WHERE d.proposal_id = p_proposal_id) THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003', DETAIL = 'ALREADY_DECIDED';
    END IF;
    IF v_proposal.revision IS DISTINCT FROM p_expected_revision
       OR v_run.active_proposal_id IS DISTINCT FROM p_proposal_id THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003', DETAIL = 'STALE_REVISION';
    END IF;
    IF v_proposal.payload_sha256 IS DISTINCT FROM p_expected_payload_sha256 THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003', DETAIL = 'STALE_HASH';
    END IF;
    -- Ruling 5 (erratum 146: the lazy expiry runs in the API's own unit before this one, not inside it): that unit
    -- committed BLOCKED_REVIEW(expired) first; a proposal that expired since is refused the same way, and the sweeper
    -- commits its block (DEV-008: the 409 never extends the expiry).
    IF (v_run.state = 'BLOCKED_REVIEW' AND v_run.reason = 'expired')
       OR (v_run.state = 'AWAITING_APPROVAL' AND v_proposal.expires_at < app.current_time()) THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003', DETAIL = 'EXPIRED';
    END IF;
    IF v_run.state <> 'AWAITING_APPROVAL' THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003', DETAIL = 'STALE_REVISION';
    END IF;
    BEGIN
        INSERT INTO decisions (decision_id, tenant_id, proposal_id, reviewer, decision, reason, expected_payload_sha256,
                               idempotency_key, decided_at)
        VALUES (gen_random_uuid(), p_tenant_id, p_proposal_id, p_reviewer, p_decision, p_reason,
                p_expected_payload_sha256, p_idempotency_key, app.current_time());
    EXCEPTION WHEN unique_violation THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003', DETAIL = 'ALREADY_DECIDED';
    END;
    run_id := v_run.run_id;
    IF p_decision = 'approve' THEN
        INSERT INTO jobs (id, type, tenant_id, run_id, dedup_key, available_at)
        VALUES (gen_random_uuid(), 'execute', p_tenant_id, v_run.run_id, p_proposal_id::text, app.current_time())
        ON CONFLICT (dedup_key) DO NOTHING;
        state := 'APPROVED';
        state_version := app._transition(v_run.run_id, 'APPROVED', 'record_decision', NULL, NULL, 'approval.recorded',
                                         jsonb_build_object('proposal_id', p_proposal_id));
    ELSE
        state := 'REJECTED';
        state_version := app._transition(v_run.run_id, 'REJECTED', 'record_decision', 'rejected', NULL, 'run.rejected',
                                         jsonb_build_object('proposal_id', p_proposal_id));
    END IF;
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION app.record_decision(uuid, uuid, uuid, integer, text, text, text, text) OWNER TO app_definer;
"""

CREATE_REVISION = f"""
CREATE OR REPLACE FUNCTION app.create_revision(p_tenant_id uuid, p_run_id uuid, p_expected_version integer,
                                               p_author uuid, p_supersedes_run_id uuid)
RETURNS TABLE (run_id uuid, state_version integer, revision integer)
{HEADER} AS $fn$
DECLARE
    v_run runs%ROWTYPE;
    v_next integer;
    v_authors uuid[];
    v_constraint text;
BEGIN
    PERFORM app._authority('create_revision', ARRAY['api']);
    IF p_tenant_id IS NULL OR p_run_id IS NULL OR p_expected_version IS NULL OR p_author IS NULL THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'INVALID_ARGUMENT';
    END IF;
    PERFORM set_config('app.tenant_id', p_tenant_id::text, true);
    SELECT * INTO v_run FROM runs r WHERE r.run_id = p_run_id AND r.tenant_id = p_tenant_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'run';
    END IF;
    -- Ruling 2: any active requester of the tenant; the API is the identity anchor and checked the role too.
    IF NOT EXISTS (SELECT 1 FROM memberships m WHERE m.tenant_id = p_tenant_id AND m.subject = p_author
                                                     AND m.role = 'requester' AND m.active) THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'NOT_REQUESTER';
    END IF;
    -- SA:167 (R090): once a grant exists the run is past revising, whatever the version says.
    IF EXISTS (SELECT 1 FROM execution_grant g WHERE g.run_id = p_run_id) THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'GRANT_EXISTS';
    END IF;
    IF v_run.state NOT IN ('AWAITING_APPROVAL', 'APPROVED', 'BLOCKED_REVIEW')
       OR v_run.state_version <> p_expected_version THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003',
            DETAIL = format('run %s is %s at version %s', p_run_id, v_run.state, v_run.state_version);
    END IF;
    -- SA:286 (erratum 138): a named run of the same tenant and asset, never the run itself.
    IF p_supersedes_run_id IS NOT NULL AND (p_supersedes_run_id = p_run_id OR NOT EXISTS (
        SELECT 1 FROM runs r WHERE r.run_id = p_supersedes_run_id AND r.tenant_id = p_tenant_id
                               AND r.asset_id = v_run.asset_id)) THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'supersedes_run_id';
    END IF;
    -- Ruling 4: the author joins the run's content authors; Proposal.authored_by holds at most eight.
    v_authors := CASE WHEN p_author = ANY (v_run.authors) THEN v_run.authors ELSE v_run.authors || p_author END;
    IF cardinality(v_authors) > 8 THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'AUTHOR_LIMIT';
    END IF;
    -- R120 (SA:139): BLOCKED_REVIEW freed the slot, so another run may hold it now. Checked here under the run's lock;
    -- the unique index below is the backstop for an admission that commits between this read and the transition.
    IF v_run.state = 'BLOCKED_REVIEW' AND EXISTS (SELECT 1 FROM runs o WHERE o.conversation_id = v_run.conversation_id
                                                                         AND o.run_id <> p_run_id AND o.slot_held) THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'SLOT_OCCUPIED';
    END IF;
    v_next := app._run_revision(p_run_id) + 1;
    -- Ruling 1: the revision is a new graph thread from QUEUED, so the stored checkpoint (the old thread's) goes, and
    -- with it the old approval: the active proposal is cleared until the new revision freezes (BS:274).
    UPDATE runs SET authors = v_authors, supersedes_run_id = p_supersedes_run_id, checkpoint_id = NULL,
                    active_proposal_id = NULL
    WHERE runs.run_id = p_run_id;
    BEGIN
        state_version := app._transition(p_run_id, 'QUEUED', 'create_revision', NULL, NULL, 'proposal.revised',
                                         jsonb_build_object('message', format('revision %s requested', v_next))
                                         || CASE WHEN v_run.active_proposal_id IS NULL THEN '{{}}'::jsonb
                                                 ELSE jsonb_build_object('proposal_id', v_run.active_proposal_id) END);
    EXCEPTION WHEN unique_violation THEN
        GET STACKED DIAGNOSTICS v_constraint = CONSTRAINT_NAME;
        IF v_constraint = 'runs_one_active_per_conversation' THEN
            RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'SLOT_OCCUPIED';
        END IF;
        RAISE;
    END;
    -- SA:455's dedup key run_id:revision; never ON CONFLICT: a fresh revision's key cannot exist, and a silent no-op
    -- would leave the run QUEUED without a wake-up.
    INSERT INTO jobs (id, type, tenant_id, run_id, dedup_key, available_at)
    VALUES (gen_random_uuid(), 'investigate', p_tenant_id, p_run_id, format('%s:%s', p_run_id, v_next),
            app.current_time());
    run_id := p_run_id;
    revision := v_next;
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION app.create_revision(uuid, uuid, integer, uuid, uuid) OWNER TO app_definer;
"""

REQUEST_CANCEL = f"""
CREATE OR REPLACE FUNCTION app.request_cancel(p_tenant_id uuid, p_run_id uuid, p_expected_version integer,
                                              p_actor uuid)
RETURNS TABLE (run_id uuid, state text, state_version integer, grant_exists boolean, attempt_state text)
{HEADER} AS $fn$
DECLARE
    v_run runs%ROWTYPE;
    v_grant execution_grant%ROWTYPE;
BEGIN
    PERFORM app._authority('request_cancel', ARRAY['api']);
    IF p_tenant_id IS NULL OR p_run_id IS NULL OR p_expected_version IS NULL OR p_actor IS NULL THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'INVALID_ARGUMENT';
    END IF;
    PERFORM set_config('app.tenant_id', p_tenant_id::text, true);
    SELECT * INTO v_run FROM runs r WHERE r.run_id = p_run_id AND r.tenant_id = p_tenant_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'run';
    END IF;
    -- Ruling 12: the run's own requester or any current reviewer of the tenant.
    IF NOT EXISTS (SELECT 1 FROM memberships m WHERE m.tenant_id = p_tenant_id AND m.subject = p_actor AND m.active
                                                     AND ((m.role = 'requester' AND p_actor = v_run.requester)
                                                          OR m.role = 'reviewer')) THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'NOT_CANCELLER';
    END IF;
    run_id := p_run_id;
    SELECT * INTO v_grant FROM execution_grant g WHERE g.run_id = p_run_id;
    IF FOUND THEN
        -- SA:458: after the grant only the flag is set; mark_sent's re-check under this lock decides (SA:230-232,
        -- R118), and the answer reports the attempt, never an undo (BS:276).
        IF NOT v_run.cancel_requested THEN
            UPDATE runs SET cancel_requested = true, cancel_requested_at = app.current_time()
            WHERE runs.run_id = p_run_id;
        END IF;
        state := v_run.state;
        state_version := v_run.state_version;
        grant_exists := true;
        SELECT la.state INTO attempt_state FROM app._latest_attempt(v_grant.action_id) la;
        RETURN NEXT;
        RETURN;
    END IF;
    -- Before a grant: any pre-grant non-terminal state, BLOCKED_REVIEW included (contract erratum 5, erratum 139).
    IF v_run.state_version <> p_expected_version
       OR v_run.state NOT IN ('QUEUED', 'AWAITING_INPUT', 'RETRIEVING', 'DRAFTING', 'AWAITING_APPROVAL', 'APPROVED',
                              'BLOCKED_REVIEW') THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003',
            DETAIL = format('run %s is %s at version %s', p_run_id, v_run.state, v_run.state_version);
    END IF;
    UPDATE runs SET cancel_requested = true, cancel_requested_at = app.current_time() WHERE runs.run_id = p_run_id;
    state_version := app._transition(p_run_id, 'CANCELLED', 'request_cancel', NULL, NULL, 'run.cancelled',
                                     '{{}}'::jsonb);
    state := 'CANCELLED';
    grant_exists := false;
    attempt_state := NULL;
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION app.request_cancel(uuid, uuid, integer, uuid) OWNER TO app_definer;
"""

# Shared by prepare_manual_proposal and create_manual_proposal: the author and the run's readiness for a person's
# proposal (ruling 7), checked under the asset lock and the run's lock.
MANUAL_READY = """\
    -- Ruling 7 (SA:542 on the API): an active requester or reviewer of the tenant authors it.
    IF NOT EXISTS (SELECT 1 FROM memberships m WHERE m.tenant_id = p_tenant_id AND m.subject = p_author AND m.active
                                                     AND m.role IN ('requester', 'reviewer')) THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'NOT_AUTHOR';
    END IF;
    -- The state the worker leaves when the model could not draft: DRAFTING, no stored checkpoint, no live lease
    -- (erratum 134). A run a worker is still drafting has one or the other.
    IF v_run.state <> 'DRAFTING' OR v_run.intent <> 'investigate' OR v_run.checkpoint_id IS NOT NULL
       OR v_run.workflow_version IS NULL
       OR EXISTS (SELECT 1 FROM run_lease l WHERE l.run_id = p_run_id AND l.lease_until > app.current_time()) THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003',
            DETAIL = format('run %s does not wait for a manual proposal', p_run_id);
    END IF;
    v_authors := CASE WHEN p_author = ANY (v_run.authors) THEN v_run.authors ELSE v_run.authors || p_author END;
    IF cardinality(v_authors) > 8 THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'AUTHOR_LIMIT';
    END IF;
"""
MANUAL_LOCKS = """\
    PERFORM set_config('app.tenant_id', p_tenant_id::text, true);
    SELECT r.asset_id INTO v_asset FROM runs r WHERE r.run_id = p_run_id AND r.tenant_id = p_tenant_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'run';
    END IF;
    -- SA:189: the asset guard's lock first, after the API unit's idempotency lock (erratum 37).
    PERFORM app._asset_lock(p_tenant_id, v_asset);
    SELECT * INTO v_run FROM runs r WHERE r.run_id = p_run_id FOR UPDATE;
"""

PREPARE_MANUAL_PROPOSAL = f"""
CREATE OR REPLACE FUNCTION app.prepare_manual_proposal(p_tenant_id uuid, p_run_id uuid, p_author uuid,
                                                       p_evidence_ids text[])
RETURNS TABLE (revision integer, workflow_version text, supersedes_run_id uuid, asset_id text,
               start_at timestamptz, end_at timestamptz, expires_at timestamptz, snapshots jsonb)
{HEADER} AS $fn$
DECLARE
    v_asset text;
    v_run runs%ROWTYPE;
    v_authors uuid[];
BEGIN
    PERFORM app._authority('prepare_manual_proposal', ARRAY['api']);
    IF p_tenant_id IS NULL OR p_run_id IS NULL OR p_author IS NULL OR p_evidence_ids IS NULL
       OR cardinality(p_evidence_ids) NOT BETWEEN 1 AND 8 THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'INVALID_ARGUMENT';
    END IF;
{MANUAL_LOCKS}{MANUAL_READY}\
    -- Note 4: every cited section is a permitted section of the caller's tenant, or the request is 404
    -- with nothing written (the snapshots the proposal binds, BS:256).
    SELECT coalesce(jsonb_agg(jsonb_build_object('evidence_id', c.evidence_id, 'content_sha256', c.content_sha256,
                                                 'version', c.version) ORDER BY c.evidence_id COLLATE "C"), '[]'::jsonb)
    INTO snapshots FROM app._cited_permitted(p_tenant_id, p_evidence_ids) c;
    IF jsonb_array_length(snapshots) <> (SELECT count(DISTINCT e) FROM unnest(p_evidence_ids) e) THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'evidence';
    END IF;
    revision := app._run_revision(p_run_id);
    workflow_version := v_run.workflow_version;
    supersedes_run_id := v_run.supersedes_run_id;
    asset_id := v_run.asset_id;
    start_at := v_run.start_at;
    end_at := v_run.end_at;
    -- Ruling 5: the application clock, whole seconds, BS:559's fifteen minutes.
    expires_at := date_trunc('second', app.current_time()) + interval '15 minutes';
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION app.prepare_manual_proposal(uuid, uuid, uuid, text[]) OWNER TO app_definer;
"""

CREATE_MANUAL_PROPOSAL = f"""
CREATE OR REPLACE FUNCTION app.create_manual_proposal(p_tenant_id uuid, p_run_id uuid, p_payload_canonical bytea,
                                                      p_author uuid)
RETURNS TABLE (proposal_id uuid, revision integer, state text, reason text, state_version integer,
               blocking_run_id uuid)
{HEADER} AS $fn$
DECLARE
    v_asset text;
    v_run runs%ROWTYPE;
    v_authors uuid[];
    v_sha text := encode(sha256(p_payload_canonical), 'hex');
    v_payload jsonb;
    v_draft_id uuid := gen_random_uuid();
    v_proposal_id uuid;
    v_revision integer;
    v_reason text;
    v_blocking uuid;
    v_expires timestamptz;
BEGIN
    PERFORM app._authority('create_manual_proposal', ARRAY['api']);
    IF p_tenant_id IS NULL OR p_run_id IS NULL OR p_author IS NULL OR p_payload_canonical IS NULL THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'INVALID_ARGUMENT';
    END IF;
{MANUAL_LOCKS}{MANUAL_READY}    v_payload := convert_from(p_payload_canonical, 'UTF8')::jsonb;
    IF (v_payload->>'run_id') IS DISTINCT FROM p_run_id::text
       OR (v_payload->>'tenant_id') IS DISTINCT FROM p_tenant_id::text
       OR (v_payload->>'action') IS DISTINCT FROM 'create_incident'
       OR (v_payload->>'destination') IS DISTINCT FROM 'synthetic-incidents' THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'PAYLOAD_RUN_MISMATCH';
    END IF;
    -- Note 4: the run's own asset, the one its tenant's retrieval found (SA:154: fixed for the run).
    IF (v_payload->>'asset_id') IS DISTINCT FROM v_run.asset_id THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'asset';
    END IF;
    IF (v_payload->>'start_at')::timestamptz IS DISTINCT FROM v_run.start_at
       OR (v_payload->>'end_at')::timestamptz IS DISTINCT FROM v_run.end_at THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'INTERVAL';
    END IF;
    IF (v_payload->>'supersedes_run_id') IS DISTINCT FROM v_run.supersedes_run_id::text THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'SUPERSEDES_MISMATCH';
    END IF;
    -- Ruling 7 and 18: a person's proposal records the run's workflow version and the prompt version "manual".
    IF (v_payload->>'workflow_version') IS DISTINCT FROM v_run.workflow_version
       OR (v_payload->>'prompt_version') IS DISTINCT FROM 'manual' THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'WORKFLOW_VERSION';
    END IF;
    v_revision := app._run_revision(p_run_id);
    IF (v_payload->>'revision')::integer IS DISTINCT FROM v_revision
       OR EXISTS (SELECT 1 FROM proposals p WHERE p.run_id = p_run_id AND p.revision >= v_revision) THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003', DETAIL = 'revision';
    END IF;
    v_expires := (v_payload->>'expires_at')::timestamptz;
    IF v_expires IS NULL OR v_expires <= app.current_time() OR v_expires > app.current_time() + {EXPIRY_BOUND} THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'EXPIRY';
    END IF;
    -- Note 4 and BS:256: the snapshots are exactly the cited sections as the tenant's corpus permits them now.
    IF (SELECT coalesce(jsonb_agg(jsonb_build_object('evidence_id', c.evidence_id, 'content_sha256', c.content_sha256,
                                                     'version', c.version) ORDER BY c.evidence_id COLLATE "C"),
                        '[]'::jsonb)
        FROM app._cited_permitted(p_tenant_id, ARRAY(SELECT jsonb_array_elements_text(v_payload->'evidence_refs'))) c)
       IS DISTINCT FROM v_payload->'source_snapshots' THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'evidence';
    END IF;
    UPDATE runs SET authors = v_authors WHERE runs.run_id = p_run_id;
    -- The draft row a frozen proposal references (ruling 7): the person's bytes, validated here, never the model's.
    INSERT INTO drafts (id, tenant_id, run_id, draft_sha256, validated, kind, source)
    VALUES (v_draft_id, p_tenant_id, p_run_id, v_sha, true, 'proposal', 'manual');
    SELECT g.reason, g.blocking_run_id INTO v_reason, v_blocking
    FROM app._asset_guard(p_tenant_id, v_run.asset_id, v_run.start_at, v_run.end_at, p_run_id,
                          v_run.supersedes_run_id) g;
    IF v_reason IS NOT NULL THEN
        state_version := app._transition(p_run_id, 'BLOCKED_REVIEW', 'create_manual_proposal', v_reason, NULL,
                                         'review.blocked',
                                         jsonb_build_object('reason', v_reason,
                                                            'message', format('blocked by run %s', v_blocking)));
        revision := v_revision;
        state := 'BLOCKED_REVIEW';
        reason := v_reason;
        blocking_run_id := v_blocking;
        RETURN NEXT;
        RETURN;
    END IF;
    v_proposal_id := (v_payload->>'proposal_id')::uuid;
    INSERT INTO proposals (proposal_id, tenant_id, run_id, revision, draft_id, payload, payload_canonical,
                           payload_sha256, canonicalization_version, authored_by, expires_at, frozen_at)
    VALUES (v_proposal_id, p_tenant_id, p_run_id, v_revision, v_draft_id, v_payload, p_payload_canonical, v_sha, 1,
            v_authors, v_expires, app.current_time());
    UPDATE runs SET active_proposal_id = v_proposal_id WHERE runs.run_id = p_run_id;
    state_version := app._transition(p_run_id, 'AWAITING_APPROVAL', 'create_manual_proposal', NULL, NULL,
                                     'proposal.ready', jsonb_build_object('proposal_id', v_proposal_id));
    proposal_id := v_proposal_id;
    revision := v_revision;
    state := 'AWAITING_APPROVAL';
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION app.create_manual_proposal(uuid, uuid, bytea, uuid) OWNER TO app_definer;
"""

GRANT_EXECUTION = f"""
CREATE OR REPLACE FUNCTION app.grant_execution(p_raw_handle text, p_client_azp text, p_proposal_id uuid)
RETURNS TABLE ({GRANT_COLUMNS}, refusal text)
{HEADER} AS $fn$
DECLARE
    v_handle_run uuid;
    v_tenant uuid;
    v_asset text;
    v_handle record;
    v_run runs%ROWTYPE;
    v_proposal proposals%ROWTYPE;
    v_grant execution_grant%ROWTYPE;
    v_decision decisions%ROWTYPE;
    v_action_id uuid;
    v_reason text;
    v_message text;
    v_blocking uuid;
BEGIN
    PERFORM app._authority('grant_execution', ARRAY['mcp_exec']);
    IF p_proposal_id IS NULL THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'INVALID_ARGUMENT';
    END IF;
    -- SA:189, SA:462: the asset guard's lock first. The handle's run and its fixed asset are plain reads before it;
    -- an unknown handle takes no lock, and _resolve_handle below refuses it as every other bad handle (SA:357).
    SELECT ic.run_id INTO v_handle_run FROM invocation_context ic
    WHERE ic.handle_sha256 = encode(sha256(convert_to(p_raw_handle, 'UTF8')), 'hex');
    IF v_handle_run IS NOT NULL THEN
        v_tenant := app._tenant_of_run(v_handle_run);
        SELECT r.asset_id INTO v_asset FROM runs r WHERE r.run_id = v_handle_run;
        PERFORM app._asset_lock(v_tenant, v_asset);
    END IF;
    SELECT * INTO v_handle FROM app._resolve_handle(p_raw_handle, p_client_azp, 'write');
    SELECT * INTO v_run FROM runs r WHERE r.run_id = v_handle.run_id FOR UPDATE;
    SELECT * INTO v_grant FROM execution_grant g WHERE g.run_id = v_handle.run_id;
    IF FOUND THEN
        -- UNIQUE (run_id): one grant per run, ever (SA:167); a replay finds the grant it already has.
        IF v_grant.proposal_id IS DISTINCT FROM p_proposal_id THEN
            RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'OTHER_PROPOSAL';
        END IF;
        RETURN QUERY SELECT g.*, NULL::text FROM app._grant_row(v_grant.action_id) g;
        RETURN;
    END IF;
    -- The binding refusals raise and commit nothing (ruling 9): SA:538's run binding (R100), the state, the approval.
    SELECT * INTO v_proposal FROM proposals p WHERE p.proposal_id = p_proposal_id AND p.run_id = v_handle.run_id
                                                AND p.tenant_id = v_handle.tenant_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'PROPOSAL_NOT_IN_RUN';
    END IF;
    IF v_run.state <> 'APPROVED' OR v_run.active_proposal_id IS DISTINCT FROM p_proposal_id THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'NOT_ACTIVE_APPROVED';
    END IF;
    SELECT * INTO v_decision FROM decisions d WHERE d.proposal_id = p_proposal_id AND d.decision = 'approve';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'NO_APPROVAL';
    END IF;
    -- The approval named exactly these bytes (SA:454's hash, checked again where it authorizes).
    IF v_decision.expected_payload_sha256 IS DISTINCT FROM v_proposal.payload_sha256 THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'HASH_MISMATCH';
    END IF;
    IF v_run.cancel_requested THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'CANCELLED';
    END IF;
    -- The committed refusals (ruling 9, AM-10 SA:140): each moves the run to BLOCKED_REVIEW and returns its reason.
    IF v_proposal.expires_at < app.current_time() THEN
        PERFORM app._expire(v_handle.run_id);  -- SA:457 internally; it journals its own review.blocked
        v_reason := 'expired';
    ELSIF NOT EXISTS (SELECT 1 FROM memberships m WHERE m.tenant_id = v_handle.tenant_id
                                                      AND m.subject = v_run.requester AND m.role = 'requester'
                                                      AND m.active)
          OR NOT EXISTS (SELECT 1 FROM memberships m WHERE m.tenant_id = v_handle.tenant_id
                                                         AND m.subject = v_decision.reviewer
                                                         AND m.role = 'reviewer' AND m.active) THEN
        -- BS:178: requester and reviewer are re-read here, each in its role (R045); the sync deactivates a disabled
        -- user (R086). The rows are read without a row lock (erratum 17).
        v_reason := 'authority_revoked';
        v_message := 'the requester or the reviewer is no longer an active member';
    ELSE
        -- T11 review note 2: active is only as good as the last sync; without one in 120 s the gate defers.
        IF NOT EXISTS (SELECT 1 FROM memberships m WHERE m.tenant_id = v_handle.tenant_id
                                                         AND m.subject = v_run.requester
                                                         AND m.role = 'requester' AND m.active
                                                         AND m.synced_at >= app.current_time() - interval '120 seconds')
           OR NOT EXISTS (SELECT 1 FROM memberships m WHERE m.tenant_id = v_handle.tenant_id
                                                            AND m.subject = v_decision.reviewer
                                                            AND m.role = 'reviewer' AND m.active
                                                            AND m.synced_at >= app.current_time()
                                                                               - interval '120 seconds') THEN
            RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'MEMBERSHIP_STALE';
        END IF;
        -- BS:425: every cited source still approved and effective, at the version and hash the proposal froze.
        IF EXISTS (SELECT 1 FROM jsonb_array_elements(coalesce(v_proposal.payload->'source_snapshots', '[]'::jsonb)) s
                   WHERE NOT EXISTS (SELECT 1 FROM app._cited_permitted(v_handle.tenant_id, ARRAY[s->>'evidence_id']) c
                                     WHERE c.content_sha256 = s->>'content_sha256' AND c.version = s->>'version')) THEN
            v_reason := 'stale_evidence';
            v_message := 'a cited source is no longer approved and effective';
        -- R116 (BS:476): the asset status observed no more than five minutes ago, and never later than now (the
        -- worker writes the column; a future stamp would defeat the bound).
        ELSIF v_run.asset_observed_at IS NULL
              OR v_run.asset_observed_at < app.current_time() - interval '5 minutes'
              OR v_run.asset_observed_at > app.current_time() THEN
            v_reason := 'stale_evidence';
            v_message := 'the asset status observation is missing, older than five minutes or in the future';
        ELSE
            SELECT g.reason, g.blocking_run_id INTO v_reason, v_blocking
            FROM app._asset_guard(v_handle.tenant_id, v_run.asset_id, v_run.start_at, v_run.end_at, v_handle.run_id,
                                  v_run.supersedes_run_id) g;
            v_message := format('blocked by run %s', v_blocking);
        END IF;
    END IF;
    IF v_reason IS NOT NULL THEN
        IF v_reason <> 'expired' THEN
            PERFORM app._transition(v_handle.run_id, 'BLOCKED_REVIEW', 'grant_execution', v_reason, NULL,
                                    'review.blocked',
                                    jsonb_build_object('proposal_id', p_proposal_id, 'reason', v_reason,
                                                       'message', v_message));
        END IF;
        RETURN QUERY SELECT NULL::uuid, v_handle.run_id, p_proposal_id, v_handle.tenant_id, v_handle.conversation_id,
                            NULL::text, NULL::bytea, NULL::text, NULL::jsonb, v_reason;
        RETURN;
    END IF;
    v_action_id := gen_random_uuid();  -- random inside the gate (SA:168), never derived from the proposal
    INSERT INTO execution_grant (action_id, tenant_id, run_id, proposal_id, payload_sha256, granted_at)
    VALUES (v_action_id, v_handle.tenant_id, v_handle.run_id, p_proposal_id, v_proposal.payload_sha256,
            app.current_time());
    INSERT INTO action_attempt (tenant_id, action_id, attempt_no, created_at)
    VALUES (v_handle.tenant_id, v_action_id, 1, app.current_time());
    INSERT INTO action_attempt_state (tenant_id, action_id, attempt_no, seq, state, at)
    VALUES (v_handle.tenant_id, v_action_id, 1, 1, 'INTENT', app.current_time());
    PERFORM app._transition(v_handle.run_id, 'EXECUTING', 'grant_execution', NULL, NULL, 'action.granted',
                            jsonb_build_object('action_id', v_action_id, 'proposal_id', p_proposal_id));
    RETURN QUERY SELECT g.*, NULL::text FROM app._grant_row(v_action_id) g;
END
$fn$;
ALTER FUNCTION app.grant_execution(text, text, uuid) OWNER TO app_definer;
"""

SEARCH_PROCEDURES_API = f"""
CREATE OR REPLACE FUNCTION app.search_procedures_api(p_tenant_id uuid, p_query text, p_limit integer)
RETURNS TABLE (corpus_version text, retrieved_at timestamptz, results jsonb)
{HEADER} AS $fn$
DECLARE
    v_now timestamptz;
    v_lexemes text[];
    v_query tsquery;
    p_asset_type text := NULL;  -- the search's family filter, off: a person searches the tenant's whole corpus
BEGIN
    PERFORM app._authority('search_procedures_api', ARRAY['api']);
    -- Ruling 7 (erratum 135): the manual baseline's bounded lexical search; the tenant is the API's session's.
    IF p_tenant_id IS NULL OR p_query IS NULL OR char_length(p_query) NOT BETWEEN 1 AND 500
       OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 10 THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'BAD_ARGUMENT';
    END IF;
    PERFORM set_config('app.tenant_id', p_tenant_id::text, true);
    corpus_version := coalesce((SELECT i.corpus_version FROM corpus_ingestions i
                                WHERE i.tenant_id = p_tenant_id ORDER BY i.seq DESC LIMIT 1), 'none');
    v_now := app.current_time();
    retrieved_at := v_now;
    v_lexemes := tsvector_to_array(to_tsvector('english', regexp_replace(lower(p_query), '[^a-z0-9]+', ' ', 'g')));
    IF cardinality(v_lexemes) = 0 THEN
        results := '[]'::jsonb;
        RETURN NEXT;
        RETURN;
    END IF;
    v_query := to_tsquery('simple', array_to_string(v_lexemes, ' | '));
    -- The ranking, the filters and the result keys of mcp-read's lexical search (revision 0012), byte for byte.
{QUERY_0012}    INTO results FROM kept k;
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION app.search_procedures_api(uuid, text, integer) OWNER TO app_definer;
"""

# (name, argument types, callers, body): frozen here (N1); the newest-revision test reads this tuple. Helpers first,
# so every definer body names functions that exist.
FUNCTIONS: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("_append_event", "uuid, uuid, text, text, jsonb", (), APPEND_EVENT_HELPER),
    ("_resolve_handle", "text, text, text", (), RESOLVE_HANDLE),
    ("_run_revision", "uuid", (), RUN_REVISION),
    ("_asset_lock", "uuid, text", (), ASSET_LOCK),
    ("_asset_guard", "uuid, text, timestamptz, timestamptz, uuid, uuid", (), ASSET_GUARD),
    ("_cited_permitted", "uuid, text[]", (), CITED_PERMITTED),
    ("_expire", "uuid", (), EXPIRE),
    ("create_run", "uuid, uuid, jsonb, text, uuid", ("api",), CREATE_RUN),
    ("expire_proposal", "uuid", ("sweeper", "api"), EXPIRE_PROPOSAL),
    ("freeze_proposal", "uuid, uuid, bytea, timestamptz", ("worker",), FREEZE_PROPOSAL),
    ("record_decision", "uuid, uuid, uuid, integer, text, text, text, text", ("api",), RECORD_DECISION),
    ("create_revision", "uuid, uuid, integer, uuid, uuid", ("api",), CREATE_REVISION),
    ("request_cancel", "uuid, uuid, integer, uuid", ("api",), REQUEST_CANCEL),
    ("prepare_manual_proposal", "uuid, uuid, uuid, text[]", ("api",), PREPARE_MANUAL_PROPOSAL),
    ("create_manual_proposal", "uuid, uuid, bytea, uuid", ("api",), CREATE_MANUAL_PROPOSAL),
    ("grant_execution", "text, text, uuid", ("mcp_exec",), GRANT_EXECUTION),
    ("asset_scope", "text, text", ("mcp_read",), ASSET_SCOPE),
    ("search_procedures_scoped", SEARCH_ARGS, ("mcp_read",), SEARCH_PROCEDURES_SCOPED),
    ("search_procedures_api", "uuid, text, integer", ("api",), SEARCH_PROCEDURES_API),
)
# Signatures upgrade() drops before FUNCTIONS re-creates them: a return type or an argument list changes.
REPLACED: tuple[str, ...] = (
    "freeze_proposal(uuid, uuid, bytea, timestamptz)",
    "record_decision(uuid, uuid, uuid, text, text, text, text)",
    "grant_execution(text, text, uuid)",
)
# Signatures downgrade() drops: what this revision created, and the three it replaced (re-created below).
CREATED: tuple[str, ...] = (
    "search_procedures_api(uuid, text, integer)",
    "create_manual_proposal(uuid, uuid, bytea, uuid)",
    "prepare_manual_proposal(uuid, uuid, uuid, text[])",
    "request_cancel(uuid, uuid, integer, uuid)",
    "create_revision(uuid, uuid, integer, uuid, uuid)",
    "grant_execution(text, text, uuid)",
    "record_decision(uuid, uuid, uuid, integer, text, text, text, text)",
    "freeze_proposal(uuid, uuid, bytea, timestamptz)",
    "expire_proposal(uuid)",
    "_expire(uuid)",
    "_cited_permitted(uuid, text[])",
    "_asset_guard(uuid, text, timestamptz, timestamptz, uuid, uuid)",
    "_asset_lock(uuid, text)",
    "_run_revision(uuid)",
)
# What downgrade() re-creates afterwards, from the applied revisions' own bodies: (name, args, callers, body).
RESTORED: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("_append_event", "uuid, uuid, text, text, jsonb", (), REV0008.APPEND_EVENT_HELPER),
    ("_resolve_handle", "text, text, text", (), REV0009.RESOLVE_HANDLE),
    ("create_run", "uuid, uuid, jsonb, text, uuid", ("api",), REV0003.CREATE_RUN),
    ("freeze_proposal", "uuid, uuid, bytea, timestamptz", ("worker",), REV0004.FREEZE_PROPOSAL),
    ("record_decision", "uuid, uuid, uuid, text, text, text, text", ("api",), REV0004.RECORD_DECISION),
    ("grant_execution", "text, text, uuid", ("mcp_exec",), REV0010.GRANT_EXECUTION),
    ("asset_scope", "text, text", ("mcp_read",), REV0012.ASSET_SCOPE),
    ("search_procedures_scoped", SEARCH_ARGS, ("mcp_read",), REV0013.SEARCH_PROCEDURES_SCOPED),
)
DOWNGRADE_SCHEMA = (
    "DROP TABLE app.feedback",  # its rows, grants and policy go with it
    "DELETE FROM app.run_manifests WHERE revision > 1",
    "ALTER TABLE app.run_manifests DROP CONSTRAINT run_manifests_pkey, ADD PRIMARY KEY (run_id)",
    "ALTER TABLE app.run_manifests DROP COLUMN revision",
    "ALTER TABLE app.drafts DROP COLUMN source",
    "ALTER TABLE app.runs DROP COLUMN authors, DROP COLUMN asset_observed_at, DROP COLUMN workflow_version",
)


def upgrade() -> None:
    """Schema, the frozen cells and the feedback policy, then the replaced signatures dropped and every function
    created (body first, then its grants, so REVOKE lands on it)."""
    for statement in SCHEMA_CHANGES:
        op.execute(statement)
    for statement in privileges.grant_statements(TABLES_0016, GRANTS_0016, revokees=MAIN_GRANTEES_0016):
        op.execute(statement)
    for statement in privileges.rls_statements(("feedback",), POLICY_ROLES_0016):
        op.execute(statement)
    for signature in REPLACED:
        op.execute(f"DROP FUNCTION app.{signature}")
    for name, args, callers, body in FUNCTIONS:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)


def downgrade() -> None:
    """Back to 0015: drop what 0016 created, re-create the applied bodies with their grants, then the schema and
    0002's cells on `runs` and `drafts`."""
    for signature in CREATED:
        op.execute(f"DROP FUNCTION app.{signature}")
    for name, args, callers, body in RESTORED:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)
    for statement in DOWNGRADE_SCHEMA:
        op.execute(statement)
    for statement in privileges.grant_statements(("runs", "drafts"), RESTORED_CELLS, revokees=MAIN_GRANTEES_0016):
        op.execute(statement)

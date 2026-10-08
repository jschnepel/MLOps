"""The run-path definer functions (T09; AM-20.3 rows 1–3 and 23, the 24th `resolve_identity`, the internal helpers):
the only writers of runs.state, run_state_history, events and the run's jobs.

Revision ID: 0003_run_path_functions
Revises: 0002_roles_grants_rls

Every granted function is SECURITY DEFINER, owned by app_definer, pins search_path, carries `SET app.tenant_id = ''`
so a caller's preset is invisible and its own transaction-local setting is undone on exit (spike §1 D), checks
session_user first (SA:389) and resolves the tenant through run_directory before touching a tenant row (SA:446).
Helpers carry no tenant attribute: they run inside the tenant the outer function set. Errors are SQLSTATE class OC
(ruling 20): OC001 authority, OC002 not found, OC003 version, OC004 illegal transition, OC005 refused (DETAIL = code),
OC006 event rule. Each CREATE … GRANT block is one op.execute string (spike §4).
"""

import re

from alembic import op
from ops_core import privileges
from ops_core.outcomes import EventType

revision = "0003_run_path_functions"
down_revision = "0002_roles_grants_rls"
branch_labels = None
depends_on = None

HEADER = "LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp SET app.tenant_id = ''"
HELPER_HEADER = "LANGUAGE plpgsql SET search_path = app, pg_temp"


def event_type_list() -> str:
    """The EventType values as a SQL literal list, generated like 0002's transition rows so the twin cannot drift."""
    values = [t.value for t in EventType]
    if not all(re.fullmatch(r"[a-z_.]+", v) for v in values):
        raise RuntimeError("an EventType value is not safe to inline into SQL")
    return ", ".join(f"'{v}'" for v in values)


EVENT_TYPES = event_type_list()

AUTHORITY = f"""
CREATE OR REPLACE FUNCTION app._authority(p_function text, p_allowed text[]) RETURNS void
{HELPER_HEADER} AS $fn$
BEGIN
    -- session_user is the login role even inside SECURITY DEFINER; SET ROLE does not change it (spike §1, §3).
    IF NOT (session_user::text = ANY (p_allowed)) THEN
        RAISE EXCEPTION 'authority_violation' USING ERRCODE = 'OC001',
            DETAIL = format('%s may not call %s', session_user, p_function);
    END IF;
END
$fn$;
ALTER FUNCTION app._authority(text, text[]) OWNER TO app_definer;
"""

TENANT_OF_RUN = f"""
CREATE OR REPLACE FUNCTION app._tenant_of_run(p_run_id uuid) RETURNS uuid
{HELPER_HEADER} AS $fn$
DECLARE
    v_tenant uuid;
BEGIN
    -- run_directory has no RLS (SA:523): it is the bootstrap that lets a function find the tenant it must set.
    SELECT tenant_id INTO v_tenant FROM run_directory WHERE run_id = p_run_id;
    IF v_tenant IS NULL THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'run';
    END IF;
    PERFORM set_config('app.tenant_id', v_tenant::text, true);
    RETURN v_tenant;
END
$fn$;
ALTER FUNCTION app._tenant_of_run(uuid) OWNER TO app_definer;
"""

APPEND_EVENT_HELPER = f"""
CREATE OR REPLACE FUNCTION app._append_event(p_tenant_id uuid, p_run_id uuid, p_type text, p_source text,
                                             p_payload jsonb)
RETURNS TABLE (event_id uuid, sequence integer, occurred_at timestamptz)
{HELPER_HEADER} AS $fn$
DECLARE
    v_run runs%ROWTYPE;
    v_outcome_types text[] := ARRAY['action.confirmed', 'action.failed', 'action.late_evidence'];
    v_destination_types text[] := ARRAY['action.confirmed', 'action.failed', 'action.conflict',
                                        'action.late_evidence'];
    v_failed_reasons text[] := ARRAY['aborted_no_commit', 'cancelled_before_send', 'rejected', 'expired'];
BEGIN
    -- AM-14 mirrored (ops_core.outcomes.event_rules_ok is the Python twin): who may assert what.
    IF p_payload IS NULL OR jsonb_typeof(p_payload) <> 'object' THEN
        RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'payload must be an object';
    END IF;
    -- The allowlist decides what exists; append_event's reserved-type refusal decides who may emit it.
    IF NOT (p_type = ANY (ARRAY[{EVENT_TYPES}]::text[])) THEN
        RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'unknown type';
    END IF;
    IF p_source = 'model_summary' THEN
        IF p_type <> 'explanation.ready' OR NOT (p_payload ? 'message')
           OR jsonb_typeof(p_payload->'message') <> 'string'
           OR length(p_payload->>'message') = 0
           OR EXISTS (SELECT 1 FROM jsonb_object_keys(p_payload) k WHERE k NOT IN ('message', 'evidence_refs'))
           OR (p_payload ? 'evidence_refs' AND (jsonb_typeof(p_payload->'evidence_refs') <> 'array'
               OR EXISTS (SELECT 1 FROM jsonb_array_elements(p_payload->'evidence_refs') e
                          WHERE jsonb_typeof(e) <> 'string' OR length(e #>> '{{}}') = 0))) THEN
            RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'model_summary';
        END IF;
    ELSIF p_source = 'destination' THEN
        IF NOT (p_type = ANY (v_destination_types)) THEN
            RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'destination source';
        END IF;
    ELSIF p_source = 'application' THEN
        IF p_type = ANY (v_destination_types) THEN
            RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006',
                DETAIL = 'destination evidence from application';
        END IF;
    ELSE
        RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'source';
    END IF;
    IF NOT (p_type = ANY (v_outcome_types)) AND (p_payload ?| ARRAY['outcome', 'receipt', 'tombstone']) THEN
        RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'evidence keys';
    END IF;
    IF p_type = 'action.confirmed' AND (p_payload->>'status' IS DISTINCT FROM 'SUCCEEDED' OR p_payload ? 'tombstone'
                                        OR jsonb_typeof(p_payload->'receipt') IS DISTINCT FROM 'object'
                                        OR NOT (p_payload->'receipt' ?& ARRAY['receipt_id', 'incident_id',
                                                                                'committed_at'])
                                        OR EXISTS (SELECT 1 FROM jsonb_each(p_payload->'receipt')
                                                   WHERE jsonb_typeof(value) <> 'string')) THEN
        RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'action.confirmed';
    END IF;
    -- Shape only (keys present): the producer (mcp-write) validates the full Receipt and Tombstone
    -- models before a document reaches record_outcome; this is defence in depth, not the contract.
    IF (p_payload ? 'tombstone') AND (jsonb_typeof(p_payload->'tombstone') <> 'object'
        OR NOT (p_payload->'tombstone' ?& ARRAY['action_id', 'state', 'payload_sha256', 'reason', 'decided_at'])) THEN
        RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'tombstone';
    END IF;
    IF p_type = 'action.late_evidence' AND NOT (
        (p_payload->>'outcome' = 'SUCCEEDED' AND jsonb_typeof(p_payload->'receipt') = 'object'
            AND (p_payload->'receipt' ?& ARRAY['receipt_id', 'incident_id', 'committed_at'])
            AND NOT (p_payload ? 'tombstone'))
        OR (p_payload->>'outcome' = 'FAILED_NO_COMMIT' AND jsonb_typeof(p_payload->'tombstone') = 'object'
            AND NOT (p_payload ? 'receipt'))) THEN
        RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'action.late_evidence';
    END IF;
    IF p_type = 'action.failed' AND (coalesce(p_payload->>'reason', '') <> ALL (v_failed_reasons)
                                     OR p_payload ? 'receipt') THEN
        RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'action.failed';
    END IF;
    -- The runs row lock serialises the counter (SA:303, R089); the tenant is already set, so RLS admits the row.
    SELECT * INTO v_run FROM runs WHERE runs.run_id = p_run_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'run';
    END IF;
    UPDATE runs SET next_event_seq = v_run.next_event_seq + 1 WHERE runs.run_id = p_run_id;
    event_id := gen_random_uuid();
    sequence := v_run.next_event_seq + 1;
    occurred_at := date_trunc('second', app.current_time());
    INSERT INTO events (event_id, tenant_id, conversation_id, run_id, sequence, type, occurred_at, source, payload)
    VALUES (event_id, p_tenant_id, v_run.conversation_id, p_run_id, sequence, p_type, occurred_at, p_source, p_payload);
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION app._append_event(uuid, uuid, text, text, jsonb) OWNER TO app_definer;
"""

TRANSITION_HELPER = f"""
CREATE OR REPLACE FUNCTION app._transition(p_run_id uuid, p_dst text, p_performer text, p_reason text,
                                           p_expected_version integer, p_event text, p_event_payload jsonb)
RETURNS integer
{HELPER_HEADER} AS $fn$
DECLARE
    v_run runs%ROWTYPE;
    v_row transitions%ROWTYPE;
    v_version integer;
    v_active text[] := ARRAY['QUEUED', 'AWAITING_INPUT', 'RETRIEVING', 'DRAFTING', 'AWAITING_APPROVAL', 'APPROVED',
                             'EXECUTING', 'OUTCOME_UNKNOWN'];
BEGIN
    SELECT * INTO v_run FROM runs WHERE runs.run_id = p_run_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'run';
    END IF;
    IF p_expected_version IS NOT NULL AND v_run.state_version <> p_expected_version THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003',
            DETAIL = format('run %s is at version %s', p_run_id, v_run.state_version);
    END IF;
    -- The T07 table as data (ruling 10): no row, no transition; a row with reasons needs one of them.
    SELECT * INTO v_row FROM transitions WHERE src = v_run.state AND dst = p_dst AND performer = p_performer;
    IF NOT FOUND OR (cardinality(v_row.reasons) > 0 AND NOT (coalesce(p_reason, '') = ANY (v_row.reasons)))
       OR (cardinality(v_row.reasons) = 0 AND p_reason IS NOT NULL) THEN
        -- R082's logged half: this ERROR reaches the server log, and the caller logs it before re-raising.
        RAISE EXCEPTION 'illegal_transition' USING ERRCODE = 'OC004',
            DETAIL = format('run %s: %s -> %s by %s (reason %s) is not a row', p_run_id, v_run.state, p_dst,
                            p_performer, coalesce(p_reason, 'none'));
    END IF;
    v_version := v_run.state_version + 1;
    UPDATE runs SET state = p_dst, state_version = v_version, reason = p_reason, slot_held = (p_dst = ANY (v_active)),
                    updated_at = app.current_time()
    WHERE runs.run_id = p_run_id;
    INSERT INTO run_state_history (tenant_id, run_id, seq, from_state, to_state, performer, reason, at)
    VALUES (v_run.tenant_id, p_run_id, v_version, v_run.state, p_dst, p_performer, p_reason, app.current_time());
    IF p_event IS NOT NULL THEN
        PERFORM app._append_event(v_run.tenant_id, p_run_id, p_event, 'application',
                                  coalesce(p_event_payload, '{{}}'::jsonb));
    END IF;
    RETURN v_version;
END
$fn$;
ALTER FUNCTION app._transition(uuid, text, text, text, integer, text, jsonb) OWNER TO app_definer;
"""

CREATE_RUN = f"""
CREATE OR REPLACE FUNCTION app.create_run(p_tenant_id uuid, p_conversation_id uuid, p_request jsonb, p_intent text,
                                          p_supersedes_run_id uuid)
RETURNS TABLE (run_id uuid, state_version integer)
{HEADER} AS $fn$
DECLARE
    v_message_id uuid;
    v_requester uuid;
    v_asset_id text;
    v_start timestamptz;
    v_end timestamptz;
    v_run_id uuid := gen_random_uuid();
BEGIN
    PERFORM app._authority('create_run', ARRAY['api']);
    -- The API is the identity trust anchor (SA:450): the tenant is an argument, set here, never read from the caller.
    PERFORM set_config('app.tenant_id', p_tenant_id::text, true);
    IF p_intent NOT IN ('investigate', 'answer_only') THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'INVALID_ARGUMENT';
    END IF;
    -- Parsed after _authority so an unauthorised caller learns nothing about the document; a malformed value is
    -- the caller's mistake (OC005), not an internal error.
    BEGIN
        v_message_id := (p_request->>'message_id')::uuid;
        v_requester := (p_request->>'requester')::uuid;
        v_asset_id := p_request->>'asset_id';
        v_start := (p_request->>'start_at')::timestamptz;
        v_end := (p_request->>'end_at')::timestamptz;
    EXCEPTION WHEN invalid_text_representation OR invalid_datetime_format OR datetime_field_overflow THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'INVALID_ARGUMENT';
    END;
    IF v_message_id IS NULL OR v_requester IS NULL OR v_asset_id IS NULL OR v_asset_id = ''
       OR v_start IS NULL OR v_end IS NULL OR v_start >= v_end THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'INVALID_ARGUMENT';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM conversations c
                   WHERE c.conversation_id = p_conversation_id AND c.tenant_id = p_tenant_id) THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'conversation';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM messages m WHERE m.message_id = v_message_id AND m.conversation_id = p_conversation_id
                                                  AND m.tenant_id = p_tenant_id) THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'message';
    END IF;
    IF p_supersedes_run_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM runs r WHERE r.run_id = p_supersedes_run_id AND r.tenant_id = p_tenant_id
                               AND r.conversation_id = p_conversation_id) THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'supersedes_run_id';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM transitions t
                   WHERE t.src = '' AND t.dst = 'QUEUED' AND t.performer = 'create_run') THEN
        RAISE EXCEPTION 'illegal_transition' USING ERRCODE = 'OC004', DETAIL = 'creation row missing';
    END IF;
    BEGIN
        INSERT INTO runs (run_id, tenant_id, conversation_id, message_id, requester, intent, supersedes_run_id,
                          asset_id, start_at, end_at, state, state_version, slot_held, next_event_seq)
        VALUES (v_run_id, p_tenant_id, p_conversation_id, v_message_id, v_requester, p_intent, p_supersedes_run_id,
                v_asset_id, v_start, v_end, 'QUEUED', 1, true, 0);
    EXCEPTION WHEN unique_violation THEN
        -- Only the slot index is the slot rule (BUILD_SPEC §7); any other unique violation is a real fault.
        DECLARE
            v_constraint text;
        BEGIN
            GET STACKED DIAGNOSTICS v_constraint = CONSTRAINT_NAME;
            IF v_constraint = 'runs_one_active_per_conversation' THEN
                RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'SLOT_OCCUPIED';
            END IF;
            RAISE;
        END;
    END;
    INSERT INTO run_directory (run_id, tenant_id) VALUES (v_run_id, p_tenant_id);
    INSERT INTO run_state_history (tenant_id, run_id, seq, from_state, to_state, performer, at)
    VALUES (p_tenant_id, v_run_id, 1, NULL, 'QUEUED', 'create_run', app.current_time());
    -- format('%s:1', ...), never a quote-colon-digit literal: SQLAlchemy reads a colon after a quote as a bind
    -- (round-1 B2); the plan's unit test scans every revision string, comments included.
    INSERT INTO jobs (id, type, tenant_id, run_id, dedup_key)
    VALUES (gen_random_uuid(), 'investigate', p_tenant_id, v_run_id, format('%s:1', v_run_id));
    PERFORM app._append_event(p_tenant_id, v_run_id, 'run.accepted', 'application', '{{}}'::jsonb);
    run_id := v_run_id;
    state_version := 1;
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION app.create_run(uuid, uuid, jsonb, text, uuid) OWNER TO app_definer;
"""

TRANSITION_RUN = f"""
CREATE OR REPLACE FUNCTION app.transition_run(p_run_id uuid, p_from text, p_to text, p_reason text,
                                              p_expected_version integer, p_detail jsonb)
RETURNS integer
{HEADER} AS $fn$
DECLARE
    v_tenant uuid;
    v_state text;
    v_event text;
BEGIN
    PERFORM app._authority('transition_run', ARRAY['worker']);
    v_tenant := app._tenant_of_run(p_run_id);
    -- Never a post-grant state and never SUCCEEDED (SA:451); the table decides the rest.
    IF p_to NOT IN ('RETRIEVING', 'DRAFTING', 'AWAITING_INPUT', 'ANSWERED', 'INSUFFICIENT_EVIDENCE', 'FAILED',
                    'QUEUED') THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'POST_GRANT_TARGET';
    END IF;
    SELECT state INTO v_state FROM runs WHERE run_id = p_run_id FOR UPDATE;
    IF v_state IS DISTINCT FROM p_from THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003', DETAIL = format('run %s is %s', p_run_id, v_state);
    END IF;
    v_event := CASE p_to
        WHEN 'FAILED' THEN 'run.failed'
        WHEN 'INSUFFICIENT_EVIDENCE' THEN 'run.insufficient_evidence'
        WHEN 'ANSWERED' THEN 'run.answered'
        WHEN 'AWAITING_INPUT' THEN 'clarification.requested'
        ELSE NULL END;
    RETURN app._transition(p_run_id, p_to, 'transition_run', p_reason, p_expected_version, v_event,
                           coalesce(p_detail, '{{}}'::jsonb));
END
$fn$;
ALTER FUNCTION app.transition_run(uuid, text, text, text, integer, jsonb) OWNER TO app_definer;
"""

APPEND_EVENT = f"""
CREATE OR REPLACE FUNCTION app.append_event(p_run_id uuid, p_type text, p_payload jsonb, p_source text)
RETURNS TABLE (event_id uuid, sequence integer, occurred_at timestamptz)
{HEADER} AS $fn$
DECLARE
    v_tenant uuid;
    v_source text := coalesce(p_source, 'application');
BEGIN
    PERFORM app._authority('append_event', ARRAY['api', 'worker', 'sweeper']);
    v_tenant := app._tenant_of_run(p_run_id);
    -- Only the definer functions emit run.*, action.*, review.*, proposal.*, approval.* and clarification.requested
    -- (SA:452 names the first three; ruling 5 closes the rest); the source is the caller's identity,
    -- except that the worker may relay the model's summary (SA:321).
    IF p_type LIKE 'run.%' OR p_type LIKE 'action.%' OR p_type LIKE 'review.%' OR p_type LIKE 'proposal.%'
       OR p_type LIKE 'approval.%' OR p_type = 'clarification.requested' THEN
        RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'reserved type';
    END IF;
    IF v_source <> 'application' AND NOT (v_source = 'model_summary' AND session_user::text = 'worker') THEN
        RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'source';
    END IF;
    RETURN QUERY SELECT * FROM app._append_event(v_tenant, p_run_id, p_type, v_source, p_payload);
END
$fn$;
ALTER FUNCTION app.append_event(uuid, text, jsonb, text) OWNER TO app_definer;
"""

RESOLVE_IDENTITY = f"""
CREATE OR REPLACE FUNCTION app.resolve_identity(p_issuer text, p_subject uuid)
RETURNS TABLE (tenant_id uuid, role text)
{HEADER} AS $fn$
DECLARE
    v_tenant uuid;
BEGIN
    PERFORM app._authority('resolve_identity', ARRAY['api']);
    -- No policy admits a tenant-less read of memberships (SA:520), so the function walks the RLS-free tenants
    -- table and sets each tenant in turn, the pattern SA:520 prescribes for the sweeper (Plan E ruling 4).
    FOR v_tenant IN SELECT t.tenant_id FROM tenants t ORDER BY t.tenant_id LOOP
        PERFORM set_config('app.tenant_id', v_tenant::text, true);
        RETURN QUERY SELECT m.tenant_id, m.role FROM memberships m
                     WHERE m.issuer = p_issuer AND m.subject = p_subject AND m.active ORDER BY m.role;
    END LOOP;
END
$fn$;
ALTER FUNCTION app.resolve_identity(text, uuid) OWNER TO app_definer;
"""

REVOKE_HANDLES = f"""
CREATE OR REPLACE FUNCTION app.revoke_handles(p_run_id uuid, p_fence bigint) RETURNS integer
{HEADER} AS $fn$
DECLARE
    v_count integer;
BEGIN
    PERFORM app._authority('revoke_handles', ARRAY['worker']);
    PERFORM app._tenant_of_run(p_run_id);
    -- TODO(T13): compare p_fence with run_lease.fence once leases exist; until then every live handle of the run goes.
    UPDATE invocation_context SET revoked_at = app.current_time() WHERE run_id = p_run_id AND revoked_at IS NULL;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END
$fn$;
ALTER FUNCTION app.revoke_handles(uuid, bigint) OWNER TO app_definer;
"""

# (name, argument types, callers, body): frozen here so a later caller-list change ships as a new revision (N1).
FUNCTIONS = (
    ("_authority", "text, text[]", (), AUTHORITY),
    ("_tenant_of_run", "uuid", (), TENANT_OF_RUN),
    ("_append_event", "uuid, uuid, text, text, jsonb", (), APPEND_EVENT_HELPER),
    ("_transition", "uuid, text, text, text, integer, text, jsonb", (), TRANSITION_HELPER),
    ("create_run", "uuid, uuid, jsonb, text, uuid", ("api",), CREATE_RUN),
    ("transition_run", "uuid, text, text, text, integer, jsonb", ("worker",), TRANSITION_RUN),
    ("append_event", "uuid, text, jsonb, text", ("api", "worker", "sweeper"), APPEND_EVENT),
    ("resolve_identity", "text, uuid", ("api",), RESOLVE_IDENTITY),
    ("revoke_handles", "uuid, bigint", ("worker",), REVOKE_HANDLES),
)


def upgrade() -> None:
    """Create each function (body first, then its grants, so REVOKE FROM PUBLIC lands on the new object)."""
    for name, args, callers, body in FUNCTIONS:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)


def downgrade() -> None:
    """Drop the functions in reverse dependency order."""
    for name, args, _, _ in reversed(FUNCTIONS):
        op.execute(f"DROP FUNCTION app.{name}({args})")

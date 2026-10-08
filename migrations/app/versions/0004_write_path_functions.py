"""The approval and write-path definer functions (T09; AM-20.3 rows 4, 5, 10, 13–15, 17, 18): proposals are
inserted frozen, decisions are first-wins by an independent current reviewer, handles resolve to a run and a tenant,
and the attempt protocol INTENT → SENT → RESOLVED is append-only under the runs row lock.

Revision ID: 0004_write_path_functions
Revises: 0003_run_path_functions

Same shape as revision 0003 (owner app_definer, search_path, the tenant attribute, session_user first). Functions
that receive an action_id find the tenant by walking `tenants` (SA:520's sweeper pattern): execution_grant is under
RLS and the caller holds no tenant. The one row lock is `runs FOR UPDATE`, taken first (AM-12): proposals, decisions,
memberships and execution_grant are read without a lock because app_definer holds no UPDATE on them and a row lock
needs one (Plan E ruling 23; proposed erratum). Asset guard, lease fence, expiry and freshness are T13/T21.
"""

from alembic import op
from ops_core import privileges

revision = "0004_write_path_functions"
down_revision = "0003_run_path_functions"
branch_labels = None
depends_on = None

HEADER = "LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp SET app.tenant_id = ''"
HELPER_HEADER = "LANGUAGE plpgsql SET search_path = app, pg_temp"
GRANT_COLUMNS = (
    "action_id uuid, run_id uuid, proposal_id uuid, tenant_id uuid, conversation_id uuid, payload_sha256 text,"
    " payload_canonical bytea, attempt_state text, detail jsonb"
)
HANDLE_COLUMNS = (
    "run_id uuid, job_id uuid, job_type text, tenant_id uuid, conversation_id uuid, run_state text, attempt_state text"
)

TENANT_OF_ACTION = f"""
CREATE OR REPLACE FUNCTION app._tenant_of_action(p_action_id uuid) RETURNS uuid
{HELPER_HEADER} AS $fn$
DECLARE
    v_tenant uuid;
BEGIN
    FOR v_tenant IN SELECT t.tenant_id FROM tenants t ORDER BY t.tenant_id LOOP
        PERFORM set_config('app.tenant_id', v_tenant::text, true);
        IF EXISTS (SELECT 1 FROM execution_grant g WHERE g.action_id = p_action_id) THEN
            RETURN v_tenant;
        END IF;
    END LOOP;
    RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'action';
END
$fn$;
ALTER FUNCTION app._tenant_of_action(uuid) OWNER TO app_definer;
"""

LATEST_ATTEMPT = f"""
CREATE OR REPLACE FUNCTION app._latest_attempt(p_action_id uuid)
RETURNS TABLE (attempt_no integer, seq integer, state text, outcome text, detail jsonb)
{HELPER_HEADER} AS $fn$
BEGIN
    -- "Latest" is the highest seq, never a timestamp (AM-20 principle 2).
    RETURN QUERY SELECT s.attempt_no, s.seq, s.state, s.outcome, s.detail FROM action_attempt_state s
                 WHERE s.action_id = p_action_id ORDER BY s.attempt_no DESC, s.seq DESC LIMIT 1;
END
$fn$;
ALTER FUNCTION app._latest_attempt(uuid) OWNER TO app_definer;
"""

RESOLVE_HANDLE = f"""
CREATE OR REPLACE FUNCTION app._resolve_handle(p_raw_handle text, p_client_azp text, p_server text)
RETURNS TABLE ({HANDLE_COLUMNS})
{HELPER_HEADER} AS $fn$
DECLARE
    v_ctx invocation_context%ROWTYPE;
    v_job_type text;
    v_job_server text;
    v_tenant uuid;
    v_run runs%ROWTYPE;
    v_attempt text;
BEGIN
    -- The raw handle never touches a table: only its hash is looked up (BS:360). Every refusal is the same error
    -- and the same message, so a probe learns nothing (SA:357).
    SELECT * INTO v_ctx FROM invocation_context ic
    WHERE ic.handle_sha256 = encode(sha256(convert_to(p_raw_handle, 'UTF8')), 'hex');
    IF NOT FOUND OR v_ctx.revoked_at IS NOT NULL OR v_ctx.expires_at <= app.current_time()
       OR v_ctx.azp <> p_client_azp THEN
        RAISE EXCEPTION 'handle_rejected' USING ERRCODE = 'OC008';
    END IF;
    v_tenant := app._tenant_of_run(v_ctx.run_id);
    SELECT j.type INTO v_job_type FROM jobs j WHERE j.id = v_ctx.job_id;
    -- The server is derived from the job type (SA:496), and the stored column must agree; a read handle at the
    -- write server (or the reverse) is refused whichever column a compromised worker wrote.
    v_job_server := CASE v_job_type WHEN 'investigate' THEN 'read' WHEN 'resume_input' THEN 'read'
                                    WHEN 'execute' THEN 'write' WHEN 'recover' THEN 'write' ELSE NULL END;
    IF v_job_server IS NULL OR v_job_server <> p_server OR v_ctx.server <> p_server THEN
        RAISE EXCEPTION 'handle_rejected' USING ERRCODE = 'OC008';
    END IF;
    SELECT * INTO v_run FROM runs r WHERE r.run_id = v_ctx.run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'handle_rejected' USING ERRCODE = 'OC008';
    END IF;
    SELECT la.state INTO v_attempt FROM execution_grant g, LATERAL app._latest_attempt(g.action_id) la
    WHERE g.run_id = v_ctx.run_id;
    run_id := v_ctx.run_id; job_id := v_ctx.job_id; job_type := v_job_type; tenant_id := v_tenant;
    conversation_id := v_run.conversation_id; run_state := v_run.state; attempt_state := v_attempt;
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION app._resolve_handle(text, text, text) OWNER TO app_definer;
"""

FREEZE_PROPOSAL = f"""
CREATE OR REPLACE FUNCTION app.freeze_proposal(p_run_id uuid, p_draft_id uuid, p_payload_canonical bytea,
                                               p_expires_at timestamptz)
RETURNS TABLE (proposal_id uuid, revision integer, state_version integer)
{HEADER} AS $fn$
DECLARE
    v_tenant uuid;
    v_run runs%ROWTYPE;
    v_draft drafts%ROWTYPE;
    v_sha text := encode(sha256(p_payload_canonical), 'hex');
    v_payload jsonb;
    v_proposal_id uuid;
    v_revision integer;
BEGIN
    PERFORM app._authority('freeze_proposal', ARRAY['worker']);
    v_tenant := app._tenant_of_run(p_run_id);
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
    IF (v_payload->>'run_id') IS DISTINCT FROM p_run_id::text
       OR (v_payload->>'tenant_id') IS DISTINCT FROM v_tenant::text THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'PAYLOAD_RUN_MISMATCH';
    END IF;
    -- supersedes_run_id is a run field written by create_run (SA:154); the frozen document must carry that value.
    IF (v_payload->>'supersedes_run_id') IS DISTINCT FROM v_run.supersedes_run_id::text THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'SUPERSEDES_MISMATCH';
    END IF;
    v_proposal_id := (v_payload->>'proposal_id')::uuid;
    SELECT coalesce(max(p.revision), 0) + 1 INTO v_revision FROM proposals p WHERE p.run_id = p_run_id;
    IF (v_payload->>'revision')::integer IS DISTINCT FROM v_revision THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003', DETAIL = 'revision';
    END IF;
    INSERT INTO proposals (proposal_id, tenant_id, run_id, revision, draft_id, payload, payload_canonical,
                           payload_sha256,
                           canonicalization_version, authored_by, expires_at, frozen_at)
    VALUES (v_proposal_id, v_tenant, p_run_id, v_revision, p_draft_id, v_payload, p_payload_canonical, v_sha, 1,
            ARRAY[v_run.requester], p_expires_at, app.current_time());
    UPDATE runs SET active_proposal_id = v_proposal_id WHERE runs.run_id = p_run_id;
    -- TODO(T21): the asset guard (advisory lock, AM-13) and BLOCKED_REVIEW on refusal.
    state_version := app._transition(p_run_id, 'AWAITING_APPROVAL', 'freeze_proposal', NULL, NULL, 'proposal.ready',
                                     jsonb_build_object('proposal_id', v_proposal_id));
    proposal_id := v_proposal_id;
    revision := v_revision;
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION app.freeze_proposal(uuid, uuid, bytea, timestamptz) OWNER TO app_definer;
"""

RECORD_DECISION = f"""
CREATE OR REPLACE FUNCTION app.record_decision(p_tenant_id uuid, p_proposal_id uuid, p_reviewer uuid,
                                               p_expected_payload_sha256 text, p_decision text, p_reason text,
                                               p_idempotency_key text)
RETURNS TABLE (run_id uuid, state text, state_version integer)
{HEADER} AS $fn$
DECLARE
    v_proposal proposals%ROWTYPE;
    v_run runs%ROWTYPE;
BEGIN
    PERFORM app._authority('record_decision', ARRAY['api']);
    -- The API is the identity trust anchor (SA:454): tenant and reviewer are arguments it has authenticated.
    PERFORM set_config('app.tenant_id', p_tenant_id::text, true);
    IF p_decision NOT IN ('approve', 'reject') THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'INVALID_ARGUMENT';
    END IF;
    SELECT * INTO v_proposal FROM proposals p WHERE p.proposal_id = p_proposal_id AND p.tenant_id = p_tenant_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'proposal';
    END IF;
    -- runs FOR UPDATE is the only lock: proposals and decisions are insert-only and app_definer may not lock them
    -- (ruling 23).
    SELECT * INTO v_run FROM runs r WHERE r.run_id = v_proposal.run_id FOR UPDATE;
    IF v_run.state <> 'AWAITING_APPROVAL' OR v_run.active_proposal_id IS DISTINCT FROM p_proposal_id
       OR v_proposal.payload_sha256 <> p_expected_payload_sha256 THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003', DETAIL = 'not the active undecided revision';
    END IF;
    -- Independence (BS:466, SA:539): a current reviewer of this tenant who is neither requester nor author.
    IF NOT EXISTS (SELECT 1 FROM memberships m WHERE m.tenant_id = p_tenant_id AND m.subject = p_reviewer
                                                     AND m.role = 'reviewer' AND m.active) THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'NOT_REVIEWER';
    END IF;
    IF p_reviewer = v_run.requester OR p_reviewer = ANY (v_proposal.authored_by) THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'SELF_REVIEW';
    END IF;
    -- TODO(T21): lazy expiry (expires_at < app.current_time() → BLOCKED_REVIEW(expired)).
    BEGIN
        INSERT INTO decisions (decision_id, tenant_id, proposal_id, reviewer, decision, reason, expected_payload_sha256,
                               idempotency_key, decided_at)
        VALUES (gen_random_uuid(), p_tenant_id, p_proposal_id, p_reviewer, p_decision, p_reason,
                p_expected_payload_sha256, p_idempotency_key, app.current_time());
    EXCEPTION WHEN unique_violation THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003', DETAIL = 'first decision wins';
    END;
    run_id := v_run.run_id;
    IF p_decision = 'approve' THEN
        INSERT INTO jobs (id, type, tenant_id, run_id, dedup_key)
        VALUES (gen_random_uuid(), 'execute', p_tenant_id, v_run.run_id, p_proposal_id::text)
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
ALTER FUNCTION app.record_decision(uuid, uuid, uuid, text, text, text, text) OWNER TO app_definer;
"""

RESOLVE_INVOCATION = f"""
CREATE OR REPLACE FUNCTION app.resolve_invocation(p_raw_handle text, p_client_azp text)
RETURNS TABLE ({HANDLE_COLUMNS})
{HEADER} AS $fn$
BEGIN
    PERFORM app._authority('resolve_invocation', ARRAY['mcp_read', 'mcp_exec']);
    -- The calling role picks the server (SA:459): mcp_read sees read handles only, mcp_exec write handles only.
    RETURN QUERY SELECT * FROM app._resolve_handle(p_raw_handle, p_client_azp,
                                                   CASE WHEN session_user::text = 'mcp_read'
                                                        THEN 'read' ELSE 'write' END);
END
$fn$;
ALTER FUNCTION app.resolve_invocation(text, text) OWNER TO app_definer;
"""

GRANT_EXECUTION = f"""
CREATE OR REPLACE FUNCTION app.grant_execution(p_raw_handle text, p_proposal_id uuid)
RETURNS TABLE ({GRANT_COLUMNS})
{HEADER} AS $fn$
DECLARE
    v_handle record;
    v_run runs%ROWTYPE;
    v_proposal proposals%ROWTYPE;
    v_grant execution_grant%ROWTYPE;
    v_action_id uuid;
BEGIN
    PERFORM app._authority('grant_execution', ARRAY['mcp_exec']);
    SELECT * INTO v_handle FROM app._resolve_handle(p_raw_handle, 'ops-worker', 'write');
    SELECT * INTO v_run FROM runs r WHERE r.run_id = v_handle.run_id FOR UPDATE;
    SELECT * INTO v_grant FROM execution_grant g WHERE g.run_id = v_handle.run_id;
    IF FOUND THEN
        -- UNIQUE (run_id): one grant per run, ever (SA:167); a replay finds the grant it already has.
        IF v_grant.proposal_id <> p_proposal_id THEN
            RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'OTHER_PROPOSAL';
        END IF;
        RETURN QUERY SELECT * FROM app._grant_row(v_grant.action_id);
        RETURN;
    END IF;
    SELECT * INTO v_proposal FROM proposals p WHERE p.proposal_id = p_proposal_id AND p.run_id = v_handle.run_id
                                                AND p.tenant_id = v_handle.tenant_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'PROPOSAL_NOT_IN_RUN';
    END IF;
    IF v_run.state <> 'APPROVED' OR v_run.active_proposal_id IS DISTINCT FROM p_proposal_id THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'NOT_ACTIVE_APPROVED';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM decisions d WHERE d.proposal_id = p_proposal_id AND d.decision = 'approve') THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'NO_APPROVAL';
    END IF;
    IF v_run.cancel_requested THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'CANCELLED';
    END IF;
    -- The §13 gate re-reads current membership (BS:472): requester and reviewer must still be active members.
    IF NOT EXISTS (SELECT 1 FROM memberships m WHERE m.tenant_id = v_handle.tenant_id
                                                     AND m.subject = v_run.requester AND m.active)
       OR NOT EXISTS (SELECT 1 FROM decisions d JOIN memberships m ON m.tenant_id = v_handle.tenant_id
                                                                      AND m.subject = d.reviewer
                      AND m.role = 'reviewer' AND m.active WHERE d.proposal_id = p_proposal_id) THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'MEMBERSHIP_INACTIVE';
    END IF;
    -- TODO(T21): asset freshness (5 min) and the asset guard; TODO(T13): the lease fence.
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
    RETURN QUERY SELECT * FROM app._grant_row(v_action_id);
END
$fn$;
ALTER FUNCTION app.grant_execution(text, uuid) OWNER TO app_definer;
"""

GRANT_ROW = f"""
CREATE OR REPLACE FUNCTION app._grant_row(p_action_id uuid)
RETURNS TABLE ({GRANT_COLUMNS})
{HELPER_HEADER} AS $fn$
BEGIN
    RETURN QUERY
    SELECT g.action_id, g.run_id, g.proposal_id, g.tenant_id, r.conversation_id, g.payload_sha256, p.payload_canonical,
           la.state, la.detail
    FROM execution_grant g JOIN runs r ON r.run_id = g.run_id JOIN proposals p ON p.proposal_id = g.proposal_id
         LEFT JOIN LATERAL app._latest_attempt(g.action_id) la ON true
    WHERE g.action_id = p_action_id;
END
$fn$;
ALTER FUNCTION app._grant_row(uuid) OWNER TO app_definer;
"""

LOOKUP_ACTION = f"""
CREATE OR REPLACE FUNCTION app.lookup_action(p_raw_handle text)
RETURNS TABLE ({GRANT_COLUMNS})
{HEADER} AS $fn$
DECLARE
    v_handle record;
    v_action_id uuid;
BEGIN
    PERFORM app._authority('lookup_action', ARRAY['mcp_exec']);
    SELECT * INTO v_handle FROM app._resolve_handle(p_raw_handle, 'ops-worker', 'write');
    SELECT g.action_id INTO v_action_id FROM execution_grant g WHERE g.run_id = v_handle.run_id;
    IF v_action_id IS NULL THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'grant';
    END IF;
    RETURN QUERY SELECT * FROM app._grant_row(v_action_id);
END
$fn$;
ALTER FUNCTION app.lookup_action(text) OWNER TO app_definer;
"""

MARK_SENT = f"""
CREATE OR REPLACE FUNCTION app.mark_sent(p_action_id uuid) RETURNS text
{HEADER} AS $fn$
DECLARE
    v_tenant uuid;
    v_grant execution_grant%ROWTYPE;
    v_run runs%ROWTYPE;
    v_latest record;
BEGIN
    PERFORM app._authority('mark_sent', ARRAY['mcp_exec']);
    v_tenant := app._tenant_of_action(p_action_id);
    SELECT * INTO v_grant FROM execution_grant g WHERE g.action_id = p_action_id;
    SELECT * INTO v_run FROM runs r WHERE r.run_id = v_grant.run_id FOR UPDATE;  -- serialises the seq (SA:462)
    SELECT * INTO v_latest FROM app._latest_attempt(p_action_id);
    IF v_latest.state = 'RESOLVED' THEN
        RETURN 'resolved';
    ELSIF v_latest.state = 'SENT' THEN
        RETURN 'already_sent';
    END IF;
    -- SA:463: cancellation is re-checked before SENT; nothing is written. TODO(T22): the dispatch deadline.
    IF v_run.cancel_requested THEN
        RETURN 'cancelled';
    END IF;
    INSERT INTO action_attempt_state (tenant_id, action_id, attempt_no, seq, state, at)
    VALUES (v_tenant, p_action_id, v_latest.attempt_no, v_latest.seq + 1, 'SENT', app.current_time());
    PERFORM app._append_event(v_tenant, v_grant.run_id,
                              CASE WHEN v_latest.attempt_no > 1 THEN 'action.redispatched' ELSE 'action.dispatched' END,
                              'application', jsonb_build_object('action_id', p_action_id));
    RETURN 'sent';
END
$fn$;
ALTER FUNCTION app.mark_sent(uuid) OWNER TO app_definer;
"""

RECORD_OUTCOME = f"""
CREATE OR REPLACE FUNCTION app.record_outcome(p_action_id uuid, p_outcome text, p_document jsonb) RETURNS text
{HEADER} AS $fn$
DECLARE
    v_tenant uuid;
    v_grant execution_grant%ROWTYPE;
    v_run runs%ROWTYPE;
    v_latest record;
    v_implied text;
    v_reason text;
BEGIN
    PERFORM app._authority('record_outcome', ARRAY['mcp_exec']);
    v_tenant := app._tenant_of_action(p_action_id);
    SELECT * INTO v_grant FROM execution_grant g WHERE g.action_id = p_action_id;
    SELECT * INTO v_run FROM runs r WHERE r.run_id = v_grant.run_id FOR UPDATE;
    SELECT * INTO v_latest FROM app._latest_attempt(p_action_id);
    IF v_latest.state = 'RESOLVED' THEN
        RETURN v_latest.outcome;  -- idempotent (SA:464): the first record stands
    END IF;
    IF p_outcome NOT IN ('SUCCEEDED', 'FAILED_NO_COMMIT', 'CONFLICT') THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'INVALID_ARGUMENT';
    END IF;
    -- The document's hash must be the grant's (SA:464); a CONFLICT is precisely the case where it is not.
    IF p_outcome <> 'CONFLICT' AND (p_document->>'payload_sha256') IS DISTINCT FROM v_grant.payload_sha256 THEN
        RAISE EXCEPTION 'hash_mismatch' USING ERRCODE = 'OC007', DETAIL = 'outcome';
    END IF;
    IF (p_document->>'action_id') IS DISTINCT FROM p_action_id::text THEN
        RAISE EXCEPTION 'hash_mismatch' USING ERRCODE = 'OC007', DETAIL = 'action_id';
    END IF;
    INSERT INTO action_attempt_state (tenant_id, action_id, attempt_no, seq, state, outcome, detail, at)
    VALUES (v_tenant, p_action_id, v_latest.attempt_no, v_latest.seq + 1, 'RESOLVED', p_outcome, p_document,
            app.current_time());
    v_implied := CASE p_outcome WHEN 'SUCCEEDED' THEN 'SUCCEEDED' WHEN 'FAILED_NO_COMMIT' THEN 'FAILED'
                                ELSE 'ESCALATED' END;
    IF v_run.state IN ('EXECUTING', 'OUTCOME_UNKNOWN', 'ESCALATED') AND v_run.state <> v_implied THEN
        v_reason := CASE p_outcome WHEN 'FAILED_NO_COMMIT' THEN p_document->>'reason'
                                   WHEN 'CONFLICT' THEN 'conflict' ELSE NULL END;
        PERFORM app._transition(v_grant.run_id, v_implied, 'record_outcome', v_reason, NULL, NULL, NULL);
    END IF;
    -- The event is the destination's assertion (AM-14); on a terminal run a SUCCEEDED or FAILED outcome is late
    -- evidence (payload `outcome` + its proof, the shape ops_core.outcomes.event_rules_ok accepts) and a CONFLICT is
    -- always action.conflict; no transition either way.
    IF v_run.state IN ('SUCCEEDED', 'FAILED', 'ABANDONED_UNVERIFIED') AND p_outcome <> 'CONFLICT' THEN
        PERFORM app._append_event(v_tenant, v_grant.run_id, 'action.late_evidence', 'destination',
            CASE WHEN p_outcome = 'SUCCEEDED'
                 THEN jsonb_build_object('outcome', 'SUCCEEDED', 'action_id', p_action_id,
                                         'receipt', p_document->'receipt')
                 ELSE jsonb_build_object('outcome', 'FAILED_NO_COMMIT', 'action_id', p_action_id,
                                         'reason', p_document->>'reason',
                                         'tombstone', p_document->'tombstone') END);
    ELSE
        PERFORM app._append_event(v_tenant, v_grant.run_id,
            CASE WHEN p_outcome = 'SUCCEEDED' THEN 'action.confirmed'
                 WHEN p_outcome = 'FAILED_NO_COMMIT' THEN 'action.failed' ELSE 'action.conflict' END,
            'destination',
            CASE WHEN p_outcome = 'SUCCEEDED'
                      THEN jsonb_build_object('status', 'SUCCEEDED', 'action_id', p_action_id,
                                              'receipt', p_document->'receipt')
                 WHEN p_outcome = 'FAILED_NO_COMMIT'
                      THEN jsonb_build_object('action_id', p_action_id, 'reason', p_document->>'reason',
                                              'tombstone', p_document->'tombstone')
                 ELSE jsonb_build_object('action_id', p_action_id) END);
    END IF;
    RETURN p_outcome;
END
$fn$;
ALTER FUNCTION app.record_outcome(uuid, text, jsonb) OWNER TO app_definer;
"""

MARK_UNKNOWN = f"""
CREATE OR REPLACE FUNCTION app.mark_unknown(p_run_id uuid, p_fence bigint) RETURNS text
{HEADER} AS $fn$
DECLARE
    v_tenant uuid;
    v_run runs%ROWTYPE;
    v_grant execution_grant%ROWTYPE;
BEGIN
    PERFORM app._authority('mark_unknown', ARRAY['worker']);
    v_tenant := app._tenant_of_run(p_run_id);
    SELECT * INTO v_run FROM runs r WHERE r.run_id = p_run_id FOR UPDATE;
    -- TODO(T13): bump run_lease.fence (p_fence) here; until leases exist the handles are revoked directly.
    UPDATE invocation_context SET revoked_at = app.current_time() WHERE run_id = p_run_id AND revoked_at IS NULL;
    IF v_run.state = 'OUTCOME_UNKNOWN' THEN
        RETURN v_run.state;  -- a second UNKNOWN changes nothing
    END IF;
    IF v_run.state <> 'EXECUTING' THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003',
                                                 DETAIL = format('run %s is %s', p_run_id, v_run.state);
    END IF;
    SELECT * INTO v_grant FROM execution_grant g WHERE g.run_id = p_run_id;
    IF NOT FOUND THEN
        RETURN v_run.state;  -- EXECUTING without a grant cannot happen; nothing to mark
    END IF;
    PERFORM app._transition(p_run_id, 'OUTCOME_UNKNOWN', 'mark_unknown', NULL, NULL, 'action.uncertain',
                            jsonb_build_object('action_id', v_grant.action_id));
    INSERT INTO jobs (id, type, tenant_id, run_id, dedup_key)
    VALUES (gen_random_uuid(), 'recover', v_tenant, p_run_id, format('%s:timeout', v_grant.action_id))
    ON CONFLICT (dedup_key) DO NOTHING;
    RETURN 'OUTCOME_UNKNOWN';
END
$fn$;
ALTER FUNCTION app.mark_unknown(uuid, bigint) OWNER TO app_definer;
"""

FUNCTIONS = (
    ("_tenant_of_action", "uuid", (), TENANT_OF_ACTION),
    ("_latest_attempt", "uuid", (), LATEST_ATTEMPT),
    ("_resolve_handle", "text, text, text", (), RESOLVE_HANDLE),
    ("_grant_row", "uuid", (), GRANT_ROW),
    ("freeze_proposal", "uuid, uuid, bytea, timestamptz", ("worker",), FREEZE_PROPOSAL),
    ("record_decision", "uuid, uuid, uuid, text, text, text, text", ("api",), RECORD_DECISION),
    ("resolve_invocation", "text, text", ("mcp_read", "mcp_exec"), RESOLVE_INVOCATION),
    ("grant_execution", "text, uuid", ("mcp_exec",), GRANT_EXECUTION),
    ("lookup_action", "text", ("mcp_exec",), LOOKUP_ACTION),
    ("mark_sent", "uuid", ("mcp_exec",), MARK_SENT),
    ("record_outcome", "uuid, text, jsonb", ("mcp_exec",), RECORD_OUTCOME),
    ("mark_unknown", "uuid, bigint", ("worker",), MARK_UNKNOWN),
)


# (name, argument types, callers, body): frozen here so a later caller-list change ships as a new revision (N1).
def upgrade() -> None:
    for name, args, callers, body in FUNCTIONS:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)


def downgrade() -> None:
    for name, args, _, _ in reversed(FUNCTIONS):
        op.execute(f"DROP FUNCTION app.{name}({args})")

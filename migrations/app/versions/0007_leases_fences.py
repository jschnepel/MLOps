"""The run lease in the database (T13, Plan H rulings 1, 5-9, 12, 13, 27): the model permit, the definer's fence cell,
the job-type vocabulary, the global queue count and the fenced definer functions.

Revision ID: 0007_leases_fences
Revises: 0006_admission_idempotency

`model_permit` holds one row per unit of global model concurrency (BS:549: one, seeded here, SA:440); the worker
takes a free slot with SKIP LOCKED and an expiry on the application clock, so no role needs to reclaim it and only the
worker holds any cell on it (erratum 50; SA:523: no RLS). `app_definer` gains UPDATE on `run_lease.fence`: a row lock
needs UPDATE on a column (Plan E ruling 23), the fenced definers lock the lease row, and `mark_unknown` bumps the fence
(erratum 45). `jobs.type` gets the AM-20.4 vocabulary as a CHECK (ruling 27). `queued_runs_total()` is the global
bound's count for `api`, which sees one tenant under RLS (ruling 13).

The handle functions check the fence in one place, `_resolve_handle`: the run's lease row FOR SHARE, then the handle's
fence against the lease's and the lease's expiry, compared after the lock (rulings 5 and 7; erratum 53).
`resolve_invocation`, `lookup_action` and `grant_execution` already call it; `mark_sent` and `record_outcome` now take
the raw handle so they call it too (erratum 48). `mark_unknown` takes the lease FOR UPDATE, refuses a stale fence,
bumps it and returns the new one (erratum 54); `revoke_handles` revokes one fence's handles and older ones, never
refusing (erratum 55). The worker-only `transition_run`, `freeze_proposal` and `append_event` keep their bodies: the
worker's unit takes the share lock before calling them (erratum 47). Every cell, caller and body is frozen here, and
the downgrade restores revision 0006 exactly (R006) by re-running the applied revisions' own bodies, loaded from
their files: an applied revision is never edited, so this is as exact as a copy and cannot drift from it.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic import op
from ops_core import privileges

revision = "0007_leases_fences"
down_revision = "0006_admission_idempotency"
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


REV0003 = _applied("0003_run_path_functions")
REV0004 = _applied("0004_write_path_functions")
REV0005 = _applied("0005_sessions_login_logout")
HEADER = "LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp SET app.tenant_id = ''"
HELPER_HEADER = REV0004.HELPER_HEADER
HANDLE_COLUMNS = REV0004.HANDLE_COLUMNS
TABLES = ("run_lease", "model_permit")
MAIN_GRANTEES_0007 = ("api", "worker", "sweeper", "mcp_read", "mcp_exec", "operator", "app_definer")
GRANTS_0007: dict[str, dict[str, privileges.Grant]] = {
    "run_lease": {
        "worker": privileges.Grant(sel=True, ins=True, upd=True),
        "sweeper": privileges.Grant(sel=True, upd=("lease_until",)),
        "app_definer": privileges.Grant(sel=True, upd=("fence",)),
    },
    "model_permit": {"worker": privileges.Grant(sel=True, upd=True)},
}
# What 0002 granted on run_lease, for the downgrade (not named GRANTS_*: the newest-revision test folds every
# GRANTS_* attribute into the live matrix check).
RUN_LEASE_CELLS_0002: dict[str, dict[str, privileges.Grant]] = {
    "run_lease": {
        "worker": privileges.Grant(sel=True, ins=True, upd=True),
        "sweeper": privileges.Grant(sel=True, upd=("lease_until",)),
        "app_definer": privileges.Grant(sel=True),
    }
}
# The AM-20.4 job types, frozen here; a unit test compares them with ops_core.jobs.JobType.
JOB_TYPES_0007 = (
    "investigate",
    "resume_input",
    "execute",
    "recover",
    "expire_proposals",
    "sync_memberships",
    "sweep_wakeups",
    "deliver_outbox",
)
JOB_TYPES = ", ".join(f"'{job_type}'" for job_type in JOB_TYPES_0007)

SCHEMA_CHANGES = (
    (
        "CREATE TABLE app.model_permit ("
        " slot smallint PRIMARY KEY CHECK (slot >= 1),"
        " holder text,"
        " run_id uuid,"
        " leased_until timestamptz NOT NULL DEFAULT '-infinity')"
    ),
    "ALTER TABLE app.model_permit OWNER TO migrator",
    "INSERT INTO app.model_permit (slot) VALUES (1)",
    f"ALTER TABLE app.jobs ADD CONSTRAINT jobs_type_check CHECK (type IN ({JOB_TYPES}))",
)

QUEUED_RUNS_TOTAL = f"""
CREATE OR REPLACE FUNCTION app.queued_runs_total() RETURNS bigint
{HEADER} AS $fn$
DECLARE
    v_tenant uuid;
    v_count bigint;
    v_total bigint := 0;
BEGIN
    PERFORM app._authority('queued_runs_total', ARRAY['api']);
    -- BS:550's "100 total": runs is under RLS and api sees one tenant at a time (Plan G spike section 8), so the
    -- function walks the RLS-free tenants table and counts each tenant's QUEUED runs under that tenant's setting,
    -- the resolve_identity pattern (SA:520). One number leaves it: no id, no tenant, no state.
    FOR v_tenant IN SELECT t.tenant_id FROM tenants t ORDER BY t.tenant_id LOOP
        PERFORM set_config('app.tenant_id', v_tenant::text, true);
        SELECT count(*) INTO v_count FROM runs r WHERE r.state = 'QUEUED';
        v_total := v_total + v_count;
    END LOOP;
    RETURN v_total;
END
$fn$;
ALTER FUNCTION app.queued_runs_total() OWNER TO app_definer;
"""

RESOLVE_HANDLE = f"""
CREATE OR REPLACE FUNCTION app._resolve_handle(p_raw_handle text, p_client_azp text, p_server text)
RETURNS TABLE ({HANDLE_COLUMNS})
{HELPER_HEADER} AS $fn$
DECLARE
    v_ctx invocation_context%ROWTYPE;
    v_lease run_lease%ROWTYPE;
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
    IF NOT FOUND THEN
        RAISE EXCEPTION 'handle_rejected' USING ERRCODE = 'OC008';
    END IF;
    -- AM-12 (T13): the run's lease row FOR SHARE is the first lock (SA:188), so an acquisition (FOR UPDATE) waits for
    -- this transaction and nothing it writes can land after a newer fence. A handle lives only while its fence is the
    -- lease's and the lease is live; every comparison below runs after the lock (SA:157).
    SELECT * INTO v_lease FROM run_lease l WHERE l.run_id = v_ctx.run_id FOR SHARE;
    IF NOT FOUND OR v_lease.fence <> v_ctx.fence OR v_lease.lease_until <= app.current_time()
       OR v_ctx.revoked_at IS NOT NULL OR v_ctx.expires_at <= app.current_time() OR v_ctx.azp <> p_client_azp THEN
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

# grant_execution as 0005 installed it, with its lease to-do answered: the fence is _resolve_handle's (ruling 31).
# The only change is the comment, which lives in the stored body. GRANT_TODO_0005 quotes revision 0005's line
# verbatim (the one place outside the applied revisions that carries T13's old TODO marker).
GRANT_TODO_0005 = "    -- TODO(T21): asset freshness (5 min) and the asset guard; TODO(T13): the lease fence.\n"
GRANT_EXECUTION = REV0005.GRANT_EXECUTION.replace(
    GRANT_TODO_0005,
    "    -- The lease fence was checked by _resolve_handle above (run_lease FOR SHARE, T13). TODO(T21): asset\n"
    "    -- freshness (5 min) and the asset guard advisory lock, first in the lock order (SA:189).\n",
)

MARK_SENT = f"""
CREATE OR REPLACE FUNCTION app.mark_sent(p_raw_handle text, p_action_id uuid) RETURNS text
{HEADER} AS $fn$
DECLARE
    v_handle record;
    v_grant execution_grant%ROWTYPE;
    v_run runs%ROWTYPE;
    v_latest record;
BEGIN
    PERFORM app._authority('mark_sent', ARRAY['mcp_exec']);
    -- The handle binds the call to its run and its lease fence (SA:463, ruling 5): _resolve_handle takes run_lease FOR
    -- SHARE and refuses OC008 for a revoked or expired handle, a moved fence or a lapsed lease, before runs is locked.
    SELECT * INTO v_handle FROM app._resolve_handle(p_raw_handle, 'ops-worker', 'write');
    SELECT * INTO v_grant FROM execution_grant g WHERE g.action_id = p_action_id AND g.run_id = v_handle.run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'action';
    END IF;
    SELECT * INTO v_run FROM runs r WHERE r.run_id = v_grant.run_id FOR UPDATE;  -- serialises the seq (SA:462)
    SELECT * INTO v_latest FROM app._latest_attempt(p_action_id);
    IF v_latest.state = 'RESOLVED' THEN
        RETURN 'resolved';
    ELSIF v_latest.state = 'SENT' THEN
        RETURN 'already_sent';
    END IF;
    -- A run mark_unknown already moved refuses SENT (its fence bump has refused the handle above in any case).
    IF v_run.state <> 'EXECUTING' THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003',
                                                 DETAIL = format('run %s is %s', v_grant.run_id, v_run.state);
    END IF;
    -- SA:463: cancellation is re-checked before SENT; nothing is written. TODO(T22): the dispatch deadline.
    IF v_run.cancel_requested THEN
        RETURN 'cancelled';
    END IF;
    INSERT INTO action_attempt_state (tenant_id, action_id, attempt_no, seq, state, at)
    VALUES (v_handle.tenant_id, p_action_id, v_latest.attempt_no, v_latest.seq + 1, 'SENT', app.current_time());
    PERFORM app._append_event(v_handle.tenant_id, v_grant.run_id,
                              CASE WHEN v_latest.attempt_no > 1 THEN 'action.redispatched' ELSE 'action.dispatched' END,
                              'application', jsonb_build_object('action_id', p_action_id));
    RETURN 'sent';
END
$fn$;
ALTER FUNCTION app.mark_sent(text, uuid) OWNER TO app_definer;
"""

RECORD_OUTCOME = f"""
CREATE OR REPLACE FUNCTION app.record_outcome(p_raw_handle text, p_action_id uuid, p_outcome text, p_document jsonb)
RETURNS text
{HEADER} AS $fn$
DECLARE
    v_handle record;
    v_grant execution_grant%ROWTYPE;
    v_run runs%ROWTYPE;
    v_latest record;
    v_implied text;
    v_reason text;
BEGIN
    PERFORM app._authority('record_outcome', ARRAY['mcp_exec']);
    -- The handle binds the outcome to its run and its lease fence (SA:464, ruling 5); after SENT a refusal here is
    -- mcp-write's UNKNOWN, never an error envelope (ruling 6).
    SELECT * INTO v_handle FROM app._resolve_handle(p_raw_handle, 'ops-worker', 'write');
    SELECT * INTO v_grant FROM execution_grant g WHERE g.action_id = p_action_id AND g.run_id = v_handle.run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'action';
    END IF;
    SELECT * INTO v_run FROM runs r WHERE r.run_id = v_grant.run_id FOR UPDATE;
    SELECT * INTO v_latest FROM app._latest_attempt(p_action_id);
    IF v_latest.state = 'RESOLVED' THEN
        RETURN v_latest.outcome;  -- idempotent (SA:464): the first record stands
    END IF;
    IF p_outcome NOT IN ('SUCCEEDED', 'FAILED_NO_COMMIT', 'CONFLICT') THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'INVALID_ARGUMENT';
    END IF;
    -- SENT is committed before any dispatch, so a receipt or conflict without SENT is a protocol violation;
    -- FAILED_NO_COMMIT from INTENT stays allowed for a cancellation before send.
    IF p_outcome IN ('SUCCEEDED', 'CONFLICT') AND v_latest.state <> 'SENT' THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003', DETAIL = 'outcome before SENT';
    END IF;
    -- The document must describe the outcome it is recorded under.
    IF (p_document->>'status') IS DISTINCT FROM p_outcome THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'INVALID_ARGUMENT';
    END IF;
    -- "No effect" needs the destination's proof (AM-13): the Python model requires the tombstone, and this is the SQL
    -- backstop so nothing after SENT is ever recorded as no effect without one (final review M1).
    IF p_outcome = 'FAILED_NO_COMMIT' AND jsonb_typeof(p_document->'tombstone') IS DISTINCT FROM 'object' THEN
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
    VALUES (v_handle.tenant_id, p_action_id, v_latest.attempt_no, v_latest.seq + 1, 'RESOLVED', p_outcome, p_document,
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
        PERFORM app._append_event(v_handle.tenant_id, v_grant.run_id, 'action.late_evidence', 'destination',
            CASE WHEN p_outcome = 'SUCCEEDED'
                 THEN jsonb_build_object('outcome', 'SUCCEEDED', 'action_id', p_action_id,
                                         'receipt', p_document->'receipt')
                 ELSE jsonb_build_object('outcome', 'FAILED_NO_COMMIT', 'action_id', p_action_id,
                                         'reason', p_document->>'reason',
                                         'tombstone', p_document->'tombstone') END);
    ELSE
        PERFORM app._append_event(v_handle.tenant_id, v_grant.run_id,
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
ALTER FUNCTION app.record_outcome(text, uuid, text, jsonb) OWNER TO app_definer;
"""

MARK_UNKNOWN = f"""
CREATE OR REPLACE FUNCTION app.mark_unknown(p_run_id uuid, p_fence bigint)
RETURNS TABLE (run_state text, new_fence bigint)
{HEADER} AS $fn$
DECLARE
    v_tenant uuid;
    v_lease run_lease%ROWTYPE;
    v_run runs%ROWTYPE;
    v_grant execution_grant%ROWTYPE;
BEGIN
    PERFORM app._authority('mark_unknown', ARRAY['worker']);
    v_tenant := app._tenant_of_run(p_run_id);
    -- AM-13 step 1: the lease row FOR UPDATE from the start, because this transaction writes the fence (SA:191). The
    -- caller must hold the lease it names: the fence identifies the holder (ruling 9).
    SELECT * INTO v_lease FROM run_lease l WHERE l.run_id = p_run_id FOR UPDATE;
    IF NOT FOUND OR v_lease.fence <> p_fence OR v_lease.lease_until <= app.current_time() THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003', DETAIL = 'stale fence';
    END IF;
    -- Step 2: the bump. From here every handle minted under the old fence is refused by _resolve_handle; revoking
    -- them below, after runs as the lock order wants (SA:188), is belt and braces.
    UPDATE run_lease l SET fence = p_fence + 1 WHERE l.run_id = p_run_id;
    new_fence := p_fence + 1;
    SELECT * INTO v_run FROM runs r WHERE r.run_id = p_run_id FOR UPDATE;
    UPDATE invocation_context ic SET revoked_at = app.current_time()
    WHERE ic.run_id = p_run_id AND ic.fence <= p_fence AND ic.revoked_at IS NULL;
    IF v_run.state = 'OUTCOME_UNKNOWN' THEN
        run_state := v_run.state;  -- a second UNKNOWN changes nothing but the fence
        RETURN NEXT;
        RETURN;
    END IF;
    IF v_run.state <> 'EXECUTING' THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003',
                                                 DETAIL = format('run %s is %s', p_run_id, v_run.state);
    END IF;
    -- Step 3: read the grant; no grant can commit any more, because the fence moved (AM-13).
    SELECT * INTO v_grant FROM execution_grant g WHERE g.run_id = p_run_id;
    IF NOT FOUND THEN
        run_state := v_run.state;  -- EXECUTING without a grant cannot happen; nothing to mark
        RETURN NEXT;
        RETURN;
    END IF;
    PERFORM app._transition(p_run_id, 'OUTCOME_UNKNOWN', 'mark_unknown', NULL, NULL, 'action.uncertain',
                            jsonb_build_object('action_id', v_grant.action_id));
    INSERT INTO jobs (id, type, tenant_id, run_id, dedup_key, available_at)
    VALUES (gen_random_uuid(), 'recover', v_tenant, p_run_id, format('%s:timeout', v_grant.action_id),
            app.current_time())
    ON CONFLICT (dedup_key) DO NOTHING;
    run_state := 'OUTCOME_UNKNOWN';
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION app.mark_unknown(uuid, bigint) OWNER TO app_definer;
"""

REVOKE_HANDLES = f"""
CREATE OR REPLACE FUNCTION app.revoke_handles(p_run_id uuid, p_fence bigint) RETURNS integer
{HEADER} AS $fn$
DECLARE
    v_count integer;
BEGIN
    PERFORM app._authority('revoke_handles', ARRAY['worker']);
    PERFORM app._tenant_of_run(p_run_id);
    -- Revocation only removes authority, so it never refuses a stale fence: a worker that lost its lease still revokes
    -- its own handles, and a newer owner's handles (a higher fence) survive (ruling 8). The share lock orders the call
    -- against an acquisition in progress (SA:472) and is the first lock taken (SA:188).
    PERFORM 1 FROM run_lease l WHERE l.run_id = p_run_id FOR SHARE;
    UPDATE invocation_context ic SET revoked_at = app.current_time()
    WHERE ic.run_id = p_run_id AND ic.fence <= p_fence AND ic.revoked_at IS NULL;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END
$fn$;
ALTER FUNCTION app.revoke_handles(uuid, bigint) OWNER TO app_definer;
"""

# (name, argument types, callers, body): frozen here (N1); the newest-revision test reads this tuple.
FUNCTIONS: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("queued_runs_total", "", ("api",), QUEUED_RUNS_TOTAL),
    ("_resolve_handle", "text, text, text", (), RESOLVE_HANDLE),
    ("grant_execution", "text, uuid", ("mcp_exec",), GRANT_EXECUTION),
    ("mark_sent", "text, uuid", ("mcp_exec",), MARK_SENT),
    ("record_outcome", "text, uuid, text, jsonb", ("mcp_exec",), RECORD_OUTCOME),
    ("mark_unknown", "uuid, bigint", ("worker",), MARK_UNKNOWN),
    ("revoke_handles", "uuid, bigint", ("worker",), REVOKE_HANDLES),
)
# Signatures upgrade() drops before FUNCTIONS re-creates them with another signature or return type.
REPLACED: tuple[str, ...] = ("mark_sent(uuid)", "record_outcome(uuid, text, jsonb)", "mark_unknown(uuid, bigint)")
# Signatures downgrade() drops: the functions 0006 does not have in the form FUNCTIONS created.
CREATED: tuple[str, ...] = (
    "queued_runs_total()",
    "mark_sent(text, uuid)",
    "record_outcome(text, uuid, text, jsonb)",
    "mark_unknown(uuid, bigint)",
)
# What downgrade() re-creates afterwards, from the applied revisions' own bodies: (name, args, callers, body).
RESTORED: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("_resolve_handle", "text, text, text", (), REV0004.RESOLVE_HANDLE),
    ("grant_execution", "text, uuid", ("mcp_exec",), REV0005.GRANT_EXECUTION),
    ("mark_sent", "uuid", ("mcp_exec",), REV0004.MARK_SENT),
    ("record_outcome", "uuid, text, jsonb", ("mcp_exec",), REV0004.RECORD_OUTCOME),
    ("mark_unknown", "uuid, bigint", ("worker",), REV0004.MARK_UNKNOWN),
    ("revoke_handles", "uuid, bigint", ("worker",), REV0003.REVOKE_HANDLES),
)
DOWNGRADE = (
    "ALTER TABLE app.jobs DROP CONSTRAINT jobs_type_check",
    f"REVOKE ALL ON app.model_permit FROM {', '.join(MAIN_GRANTEES_0007)}",
    "DROP TABLE app.model_permit",
)


def upgrade() -> None:
    """Schema, then the frozen cells, then the functions (body first, then its grants, so REVOKE lands on it).

    Raises:
        RuntimeError: revision 0005's grant_execution no longer carries the TODO line this revision rewords.
    """
    if GRANT_EXECUTION == REV0005.GRANT_EXECUTION:
        raise RuntimeError("revision 0005's grant_execution no longer carries the TODO line this revision rewords")
    for statement in SCHEMA_CHANGES:
        op.execute(statement)
    for statement in privileges.grant_statements(TABLES, GRANTS_0007, revokees=MAIN_GRANTEES_0007):
        op.execute(statement)
    for signature in REPLACED:
        op.execute(f"DROP FUNCTION app.{signature}")
    for name, args, callers, body in FUNCTIONS:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)


def downgrade() -> None:
    """Back to 0006: drop what 0007 created, re-create what it replaced, drop the permit and the CHECK, and put back
    0002's run_lease cells."""
    for signature in CREATED:
        op.execute(f"DROP FUNCTION app.{signature}")
    for name, args, callers, body in RESTORED:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)
    for statement in DOWNGRADE:
        op.execute(statement)
    for statement in privileges.grant_statements(("run_lease",), RUN_LEASE_CELLS_0002, revokees=MAIN_GRANTEES_0007):
        op.execute(statement)

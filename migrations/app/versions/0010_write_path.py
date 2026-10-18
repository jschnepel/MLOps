"""The write path of T47 (Plan K rulings 3, 7, 12, 17 and 25): the caller's token `azp`, the dispatch deadline, the
abort request, and an outcome recorded after an abort request.

Revision ID: 0010_write_path
Revises: 0009_handle_binding

The write-path definers named the worker's client with a literal (`_resolve_handle(p_raw_handle, 'ops-worker',
'write')`); `resolve_invocation` compared the presented token's `azp`, but the four definers mcp-write calls next did
not. Each now takes the token's `azp` as its second argument, `client_azp`, as `resolve_invocation` does, so the
worker's client is named once, in settings (ruling 12). `grant_execution`, `lookup_action` and `record_outcome` keep
their applied bodies with only that change (and, in `record_outcome`, the guard below), which a unit test checks by
undoing the replacements; `mark_sent` is rewritten for its new answers, and `request_abort` is new.

- The dispatch deadline (SA:229-231, SA:295; ruling 17): `app._dispatch_seconds()` is 300 (five minutes after the
  grant); `mark_sent` answers `expired`, inserting nothing, when `app.current_time()` is past `granted_at` plus that,
  compared after the runs lock; a cancel is checked first, so a cancelled run is `cancelled` whatever the clock says.
  `mark_sent` also answers `abort_requested`, inserting nothing, once an abort was requested: nothing is sent after
  `ABORT_REQUESTED` (SA:334).
- A re-send is checked as a first send is (Plan K round 1, I1): for an attempt already SENT, `mark_sent` answers
  `cancelled` or `expired` on the same two conditions (the caller then aborts, with the reason `deadline`, SA:248),
  `not_redispatchable` to a recover job (SA:345: a recover job redispatches an unsent attempt only), and otherwise
  `already_sent`. Between `mark_sent`'s commit and the POST a cancel can still land; that window is AM-13's own and the
  same for a first send and a re-send.
- `request_abort` (SA:465; rulings 2 and 3) chooses the reason itself, under the runs lock, from the attempt state,
  the cancel flag and the clock, because mcp-write sees neither the flag nor `granted_at`: `cancelled_before_send`
  (INTENT, cancelled), `expired` (INTENT, past the deadline), `deadline` (SENT, past the deadline or cancelled: an
  immediate abort after a cancel, SA:248). It appends an `ABORT_REQUESTED` row carrying the reason and returns it; a
  second request returns the first one's reason and appends nothing; a resolved attempt answers `resolved`; anything
  else (not cancelled and before the deadline) is refused `ABORT_NOT_DUE`. The caller then POSTs the abort and calls
  `record_outcome` with what the destination answered.
- `record_outcome` accepts SUCCEEDED and CONFLICT when the latest state is SENT, or ABORT_REQUESTED with the reason
  `deadline` (ruling 7, narrowed in round 1): an abort after SENT answered by the receipt that already exists is the
  destination's truth (SA:242), while an abort of an attempt never sent can only meet a tombstone.

Every body, caller and signature is frozen here; the downgrade restores 0009 exactly (R006) by dropping what this
revision created and re-running the applied revisions' own bodies, loaded from their files (the 0007 pattern).
"""

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic import op
from ops_core import privileges

revision = "0010_write_path"
down_revision = "0009_handle_binding"
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


REV0004 = _applied("0004_write_path_functions")
REV0007 = _applied("0007_leases_fences")
HEADER = "LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp SET app.tenant_id = ''"
HELPER_HEADER = REV0004.HELPER_HEADER
LITERAL_AZP = "app._resolve_handle(p_raw_handle, 'ops-worker', 'write')"
TOKEN_AZP = "app._resolve_handle(p_raw_handle, p_client_azp, 'write')"
# The 0007 guard that refused a receipt after an abort request, and 0010's (record_outcome's only logic change).
GUARD_0007 = (
    "    -- SENT is committed before any dispatch, so a receipt or conflict without SENT is a protocol violation;\n"
    "    -- FAILED_NO_COMMIT from INTENT stays allowed for a cancellation before send.\n"
    "    IF p_outcome IN ('SUCCEEDED', 'CONFLICT') AND v_latest.state <> 'SENT' THEN\n"
)
GUARD_0010 = (
    "    -- SENT is committed before any dispatch, so a receipt or conflict without SENT is a protocol violation;\n"
    "    -- FAILED_NO_COMMIT from INTENT stays allowed for a cancellation before send. An abort after SENT may be\n"
    "    -- answered by the receipt that already exists (SA:242; T47, Plan K ruling 7).\n"
    "    -- Only an abort requested after SENT (its reason `deadline`) can meet a receipt; a NULL reason is refused.\n"
    "    IF p_outcome IN ('SUCCEEDED', 'CONFLICT') AND v_latest.state <> 'SENT'\n"
    "       AND NOT (v_latest.state = 'ABORT_REQUESTED'\n"
    "                AND v_latest.detail->>'reason' IS NOT DISTINCT FROM 'deadline') THEN\n"
)
RECORD_SIGNATURE_0007 = "app.record_outcome(p_raw_handle text, p_action_id uuid, p_outcome text, p_document jsonb)"
RECORD_SIGNATURE_0010 = (
    "app.record_outcome(p_raw_handle text, p_client_azp text, p_action_id uuid, p_outcome text,\n"
    "                                      p_document jsonb)"
)
# (old, new) for each body this revision derives from an applied one: the signature, its ALTER line and the literal
# `azp`; record_outcome also gets the guard.
GRANT_CHANGES = (
    (
        "app.grant_execution(p_raw_handle text, p_proposal_id uuid)",
        "app.grant_execution(p_raw_handle text, p_client_azp text, p_proposal_id uuid)",
    ),
    ("ALTER FUNCTION app.grant_execution(text, uuid)", "ALTER FUNCTION app.grant_execution(text, text, uuid)"),
    (LITERAL_AZP, TOKEN_AZP),
)
LOOKUP_CHANGES = (
    ("app.lookup_action(p_raw_handle text)", "app.lookup_action(p_raw_handle text, p_client_azp text)"),
    ("ALTER FUNCTION app.lookup_action(text)", "ALTER FUNCTION app.lookup_action(text, text)"),
    (LITERAL_AZP, TOKEN_AZP),
)
RECORD_CHANGES = (
    (RECORD_SIGNATURE_0007, RECORD_SIGNATURE_0010),
    (
        "ALTER FUNCTION app.record_outcome(text, uuid, text, jsonb)",
        "ALTER FUNCTION app.record_outcome(text, text, uuid, text, jsonb)",
    ),
    (LITERAL_AZP, TOKEN_AZP),
    (GUARD_0007, GUARD_0010),
)


def _derived(body: str, changes: tuple[tuple[str, str], ...]) -> str:
    """`body` with each change applied; a change that does not match exactly once means the applied body moved."""
    for old, new in changes:
        if body.count(old) != 1:
            raise RuntimeError(f"an applied body no longer carries {old!r} exactly once")
        body = body.replace(old, new)
    return body


GRANT_EXECUTION = _derived(REV0007.GRANT_EXECUTION, GRANT_CHANGES)
LOOKUP_ACTION = _derived(REV0004.LOOKUP_ACTION, LOOKUP_CHANGES)
RECORD_OUTCOME = _derived(REV0007.RECORD_OUTCOME, RECORD_CHANGES)

DISPATCH_SECONDS = f"""
CREATE OR REPLACE FUNCTION app._dispatch_seconds() RETURNS integer
{HELPER_HEADER} AS $fn$
BEGIN
    -- SA:295: five minutes after the grant, fixed here until a setting can reach it (T29). Tests move app.test_clock.
    RETURN 300;
END
$fn$;
ALTER FUNCTION app._dispatch_seconds() OWNER TO app_definer;
"""

MARK_SENT = f"""
CREATE OR REPLACE FUNCTION app.mark_sent(p_raw_handle text, p_client_azp text, p_action_id uuid) RETURNS text
{HEADER} AS $fn$
DECLARE
    v_handle record;
    v_grant execution_grant%ROWTYPE;
    v_run runs%ROWTYPE;
    v_latest record;
    v_late boolean;
BEGIN
    PERFORM app._authority('mark_sent', ARRAY['mcp_exec']);
    -- The handle binds the call to its run and its lease fence (SA:463, ruling 5): _resolve_handle takes run_lease FOR
    -- SHARE and refuses OC008 for a revoked or expired handle, a moved fence or a lapsed lease, before runs is locked.
    SELECT * INTO v_handle FROM app._resolve_handle(p_raw_handle, p_client_azp, 'write');
    SELECT * INTO v_grant FROM execution_grant g WHERE g.action_id = p_action_id AND g.run_id = v_handle.run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'action';
    END IF;
    SELECT * INTO v_run FROM runs r WHERE r.run_id = v_grant.run_id FOR UPDATE;  -- serialises the seq (SA:462)
    SELECT * INTO v_latest FROM app._latest_attempt(p_action_id);
    IF v_latest.state = 'RESOLVED' THEN
        RETURN 'resolved';
    ELSIF v_latest.state = 'ABORT_REQUESTED' THEN
        RETURN 'abort_requested';  -- nothing is sent once an abort was requested (SA:334); nothing is written
    END IF;
    v_late := app.current_time() > v_grant.granted_at + make_interval(secs => app._dispatch_seconds());
    -- A re-send of a SENT attempt is re-checked as a first send is (round 1, I1): a cancel or a passed deadline sends
    -- nothing (the caller aborts, SA:248), and a recover job never re-sends (SA:345); nothing is written.
    IF v_latest.state = 'SENT' THEN
        IF v_run.cancel_requested THEN
            RETURN 'cancelled';
        ELSIF v_late THEN
            RETURN 'expired';
        ELSIF v_handle.job_type = 'recover' THEN
            RETURN 'not_redispatchable';
        END IF;
        RETURN 'already_sent';
    END IF;
    -- A run mark_unknown already moved refuses SENT (its fence bump has refused the handle above in any case).
    IF v_run.state <> 'EXECUTING' THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003',
                                                 DETAIL = format('run %s is %s', v_grant.run_id, v_run.state);
    END IF;
    -- SA:463: cancellation, then the dispatch deadline, re-checked under the runs lock before SENT; nothing is written.
    IF v_run.cancel_requested THEN
        RETURN 'cancelled';
    END IF;
    IF v_late THEN
        RETURN 'expired';
    END IF;
    INSERT INTO action_attempt_state (tenant_id, action_id, attempt_no, seq, state, at)
    VALUES (v_handle.tenant_id, p_action_id, v_latest.attempt_no, v_latest.seq + 1, 'SENT', app.current_time());
    PERFORM app._append_event(v_handle.tenant_id, v_grant.run_id,
                              CASE WHEN v_latest.attempt_no > 1 THEN 'action.redispatched' ELSE 'action.dispatched' END,
                              'application', jsonb_build_object('action_id', p_action_id));
    RETURN 'sent';
END
$fn$;
ALTER FUNCTION app.mark_sent(text, text, uuid) OWNER TO app_definer;
"""

REQUEST_ABORT = f"""
CREATE OR REPLACE FUNCTION app.request_abort(p_raw_handle text, p_client_azp text, p_action_id uuid) RETURNS text
{HEADER} AS $fn$
DECLARE
    v_handle record;
    v_grant execution_grant%ROWTYPE;
    v_run runs%ROWTYPE;
    v_latest record;
    v_late boolean;
    v_reason text;
BEGIN
    PERFORM app._authority('request_abort', ARRAY['mcp_exec']);
    -- The same binding as mark_sent (SA:465 "as record_outcome"): the handle's run, its lease fence, then runs.
    SELECT * INTO v_handle FROM app._resolve_handle(p_raw_handle, p_client_azp, 'write');
    SELECT * INTO v_grant FROM execution_grant g WHERE g.action_id = p_action_id AND g.run_id = v_handle.run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'action';
    END IF;
    SELECT * INTO v_run FROM runs r WHERE r.run_id = v_grant.run_id FOR UPDATE;
    SELECT * INTO v_latest FROM app._latest_attempt(p_action_id);
    IF v_latest.state = 'RESOLVED' THEN
        RETURN 'resolved';  -- the outcome stands; the caller reads it back
    ELSIF v_latest.state = 'ABORT_REQUESTED' THEN
        RETURN v_latest.detail->>'reason';  -- idempotent: the first request's reason stands
    END IF;
    -- The server chooses the reason (T47, Plan K ruling 3), compared after the lock: INTENT was never sent, so its
    -- abort is a guaranteed no-commit; after SENT a cancel aborts at once (SA:248), otherwise only past the deadline.
    v_late := app.current_time() > v_grant.granted_at + make_interval(secs => app._dispatch_seconds());
    v_reason := CASE
        WHEN v_latest.state = 'INTENT' AND v_run.cancel_requested THEN 'cancelled_before_send'
        WHEN v_latest.state = 'INTENT' AND v_late THEN 'expired'
        WHEN v_latest.state = 'SENT' AND (v_run.cancel_requested OR v_late) THEN 'deadline'
    END;
    IF v_reason IS NULL THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'ABORT_NOT_DUE';
    END IF;
    INSERT INTO action_attempt_state (tenant_id, action_id, attempt_no, seq, state, detail, at)
    VALUES (v_handle.tenant_id, p_action_id, v_latest.attempt_no, v_latest.seq + 1, 'ABORT_REQUESTED',
            jsonb_build_object('reason', v_reason), app.current_time());
    RETURN v_reason;
END
$fn$;
ALTER FUNCTION app.request_abort(text, text, uuid) OWNER TO app_definer;
"""

# (name, argument types, callers, body): frozen here (N1); the newest-revision test reads this tuple.
FUNCTIONS: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("_dispatch_seconds", "", (), DISPATCH_SECONDS),
    ("grant_execution", "text, text, uuid", ("mcp_exec",), GRANT_EXECUTION),
    ("lookup_action", "text, text", ("mcp_exec",), LOOKUP_ACTION),
    ("mark_sent", "text, text, uuid", ("mcp_exec",), MARK_SENT),
    ("record_outcome", "text, text, uuid, text, jsonb", ("mcp_exec",), RECORD_OUTCOME),
    ("request_abort", "text, text, uuid", ("mcp_exec",), REQUEST_ABORT),
)
# Signatures upgrade() drops before FUNCTIONS re-creates the four with the `client_azp` argument.
REPLACED: tuple[str, ...] = (
    "grant_execution(text, uuid)",
    "lookup_action(text)",
    "mark_sent(text, uuid)",
    "record_outcome(text, uuid, text, jsonb)",
)
# Signatures downgrade() drops: everything FUNCTIONS created.
CREATED: tuple[str, ...] = tuple(f"{name}({args})" for name, args, _, _ in reversed(FUNCTIONS))
# What downgrade() re-creates afterwards, from the applied revisions' own bodies: (name, args, callers, body).
RESTORED: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("grant_execution", "text, uuid", ("mcp_exec",), REV0007.GRANT_EXECUTION),
    ("lookup_action", "text", ("mcp_exec",), REV0004.LOOKUP_ACTION),
    ("mark_sent", "text, uuid", ("mcp_exec",), REV0007.MARK_SENT),
    ("record_outcome", "text, uuid, text, jsonb", ("mcp_exec",), REV0007.RECORD_OUTCOME),
)


def upgrade() -> None:
    """Drop the four signatures that change, then create each function (body first, then its grants, so REVOKE lands
    on it)."""
    for signature in REPLACED:
        op.execute(f"DROP FUNCTION app.{signature}")
    for name, args, callers, body in FUNCTIONS:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)


def downgrade() -> None:
    """Back to 0009: drop what 0010 created, then re-create the four applied bodies with their grants; no row is
    touched (an `ABORT_REQUESTED` row a test left stays, though 0009's `mark_sent` would not honour it)."""
    for signature in CREATED:
        op.execute(f"DROP FUNCTION app.{signature}")
    for name, args, callers, body in RESTORED:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)

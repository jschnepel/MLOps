"""The event journal's payload rules and the notification outbox (T14, Plan I rulings 4, 12, 13, 20, 29).

Revision ID: 0008_journal_outbox
Revises: 0007_leases_fences

`app.outbox` holds one notification intent per run, event type, channel and recipient (BS:240, BS:524, SA:427 as
erratum 60 reads it): written by `_append_event` in the transaction of the event that needs it, claimed and leased by
the sweeper's delivery loop, its result recorded apart from the run (DoD 2). `leased_until` is both the claim's lease
and the next attempt's time, so the sweeper's four AM-20.2 cells suffice; the payload is the event, by reference. RLS
is `tenant_isolation` only: the sweeper iterates tenants (SA:520). The sweeper gains DELETE on `jobs` for the purge of
finished maintenance rows, and a restrictive policy keeps that DELETE to them: `sweeper_all` would otherwise let it
delete any tenant's run jobs, whose dedup keys are what makes a wake-up happen once (erratum 61, round 1 I6).

`_append_event` is re-created with two more rules (ruling 4, T14 review note 2, erratum 65): the payload is closed over
the event schema's keys, and only the destination's four types carry a `status`; then, after the event, the
notification intent of the five types a requester must hear about (ruling 13 as amended in round 1, I2; erratum 66):
the action's outcome (`action.confirmed`, `action.failed`, `action.conflict`, all emitted today by `record_outcome`)
and the run's end without one (`run.escalated`, `run.abandoned_unverified`, whose emitters arrive with T22).
Everything else in its
body is revision 0003's, the gap-free sequence included (`runs` FOR UPDATE, `next_event_seq + 1`, the insert, all in
the caller's transaction, SA:303). Every cell, caller and body is frozen here; the downgrade restores 0007 exactly by
re-running 0003's own body and 0002's own `jobs` cells, loaded from their files (the 0007 pattern).
"""

import importlib.util
import re
from pathlib import Path
from types import ModuleType

from alembic import op
from ops_core import privileges

revision = "0008_journal_outbox"
down_revision = "0007_leases_fences"
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
HELPER_HEADER = REV0003.HELPER_HEADER
# The event types are 0003's, unchanged; the newest-revision test reads this name.
EVENT_TYPES_0008 = REV0003.EVENT_TYPES_0003
EVENT_TYPES = REV0003.EVENT_TYPES
# The event schema's payload keys (ops_core.outcomes.PAYLOAD_KEYS, frozen here; a unit test compares the two).
PAYLOAD_KEYS_0008 = (
    "message",
    "status",
    "evidence_refs",
    "proposal_id",
    "action_id",
    "code",
    "reason",
    "outcome",
    "receipt",
    "tombstone",
    "question_id",
    "message_id",
    "outbox_id",
)
# The destination's four types, the only ones that carry a status (ops_core.outcomes.STATUS_EVENT_TYPES).
STATUS_TYPES_0008 = ("action.confirmed", "action.failed", "action.conflict", "action.late_evidence")
# The events a requester is notified of (ruling 13, round 1 I2): the action's outcome, the conflict that escalates a run
# today (record_outcome's CONFLICT emits action.conflict and no run.escalated), and the run's end without an outcome.
NOTIFY_TYPES_0008 = (
    "action.confirmed",
    "action.failed",
    "action.conflict",
    "run.escalated",
    "run.abandoned_unverified",
)


def literal_list(values: tuple[str, ...]) -> str:
    """Words as a SQL literal list, each checked against a safe pattern before it is inlined."""
    if not all(re.fullmatch(r"[a-z_.]+", v) for v in values):
        raise RuntimeError("a value is not safe to inline into SQL")
    return ", ".join(f"'{v}'" for v in values)


PAYLOAD_KEYS = literal_list(PAYLOAD_KEYS_0008)
STATUS_TYPES = literal_list(STATUS_TYPES_0008)
NOTIFY_TYPES = literal_list(NOTIFY_TYPES_0008)

TABLES = ("outbox", "jobs")
MAIN_GRANTEES_0008 = ("api", "worker", "sweeper", "mcp_read", "mcp_exec", "operator", "app_definer")
POLICY_ROLES_0008 = ("api", "worker", "sweeper", "app_definer")
GRANTS_0008: dict[str, dict[str, privileges.Grant]] = {
    "outbox": {
        "sweeper": privileges.Grant(sel=True, upd=("leased_until", "attempts", "delivered_at", "result")),
        "app_definer": privileges.Grant(ins=True),
    },
    "jobs": {
        "api": privileges.Grant(ins=True),
        "worker": privileges.Grant(
            sel=True, ins=True, upd=("claimed_by", "claimed_at", "done_at", "attempts", "available_at")
        ),
        "sweeper": privileges.Grant(
            sel=True, ins=True, upd=("claimed_by", "claimed_at", "done_at", "attempts"), dele=True
        ),
        "app_definer": privileges.Grant(sel=True, ins=True),
    },
}
# What 0002 granted on jobs, for the downgrade (not named GRANTS_*: the newest-revision test folds every GRANTS_*
# attribute into the live matrix check).
JOB_CELLS_0002: dict[str, dict[str, privileges.Grant]] = {"jobs": REV0002.GRANTS_0002["jobs"]}

SCHEMA_CHANGES = (
    (
        "CREATE TABLE app.outbox ("
        " outbox_id uuid PRIMARY KEY,"
        " tenant_id uuid NOT NULL,"
        " run_id uuid NOT NULL,"
        " event_id uuid NOT NULL REFERENCES app.events (event_id),"
        " channel text NOT NULL CHECK (channel = 'local'),"
        " recipient text NOT NULL,"
        " dedup_key text NOT NULL UNIQUE,"
        " attempts integer NOT NULL DEFAULT 0,"
        " leased_until timestamptz NOT NULL DEFAULT '-infinity',"
        " delivered_at timestamptz,"
        " result text CHECK (result IN ('delivered', 'retrying', 'dead_letter')),"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT outbox_tenant_run_fkey FOREIGN KEY (tenant_id, run_id) REFERENCES app.runs (tenant_id, run_id))"
    ),
    "ALTER TABLE app.outbox OWNER TO migrator",
    # The delivery claim's scan: a tenant's undelivered, live rows in creation order.
    (
        "CREATE INDEX outbox_pending ON app.outbox (tenant_id, created_at)"
        " WHERE delivered_at IS NULL AND result IS DISTINCT FROM 'dead_letter'"
    ),
)

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
    -- T14 (Plan I ruling 4): the payload is closed over the event schema's keys, as the schema is, and a status is
    -- the destination's assertion, so only its four types carry one (review note 2: never api, worker or sweeper).
    IF EXISTS (SELECT 1 FROM jsonb_object_keys(p_payload) k WHERE NOT (k = ANY (ARRAY[{PAYLOAD_KEYS}]::text[]))) THEN
        RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'unknown payload key';
    END IF;
    IF p_payload ? 'status' AND NOT (p_type = ANY (ARRAY[{STATUS_TYPES}]::text[])) THEN
        RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'status';
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
    -- BS:524 (ruling 13): the notification intent commits with the event that needs it, last in this transaction
    -- (runs -> events -> outbox, SA:188). One intent per run, type, channel and requester: a replayed writer adds
    -- nothing (R024). ON CONFLICT names no target because app_definer may insert into the outbox but not read it.
    IF p_type = ANY (ARRAY[{NOTIFY_TYPES}]::text[]) THEN
        INSERT INTO outbox (outbox_id, tenant_id, run_id, event_id, channel, recipient, dedup_key)
        VALUES (gen_random_uuid(), p_tenant_id, p_run_id, event_id, 'local', v_run.requester::text,
                format('%s:%s:local:%s', p_run_id, p_type, v_run.requester))
        ON CONFLICT DO NOTHING;
    END IF;
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION app._append_event(uuid, uuid, text, text, jsonb) OWNER TO app_definer;
"""

# (name, argument types, callers, body): frozen here (N1); the newest-revision test reads this tuple.
FUNCTIONS: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("_append_event", "uuid, uuid, text, text, jsonb", (), APPEND_EVENT_HELPER),
)
# What downgrade() re-creates first, from the applied revisions' own bodies: (name, args, callers, body).
RESTORED: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("_append_event", "uuid, uuid, text, text, jsonb", (), REV0003.APPEND_EVENT_HELPER),
)
# Round 1, I6: the sweeper's DELETE on jobs reaches finished maintenance rows only (sweeper_all is FOR ALL USING
# (true), and a restrictive policy is ANDed with every permissive one). privileges.SWEEPER_PURGE_QUAL is the text
# PostgreSQL stores for this expression, which R106 compares.
PURGE_POLICY = (
    "DROP POLICY IF EXISTS sweeper_purge_maintenance ON app.jobs",
    (
        "CREATE POLICY sweeper_purge_maintenance ON app.jobs AS RESTRICTIVE FOR DELETE TO sweeper"
        " USING (run_id IS NULL AND done_at IS NOT NULL)"
    ),
)
DOWNGRADE = (
    "DROP POLICY sweeper_purge_maintenance ON app.jobs",
    f"REVOKE ALL ON app.outbox FROM {', '.join(MAIN_GRANTEES_0008)}",
    "DROP TABLE app.outbox",  # its policy and index go with it
)


def upgrade() -> None:
    """The table, its frozen cells and policy, the jobs cells and their purge policy, then the function (body first,
    then its REVOKE)."""
    for statement in SCHEMA_CHANGES:
        op.execute(statement)
    for statement in privileges.grant_statements(TABLES, GRANTS_0008, revokees=MAIN_GRANTEES_0008):
        op.execute(statement)
    for statement in privileges.rls_statements(("outbox",), POLICY_ROLES_0008):
        op.execute(statement)
    for statement in PURGE_POLICY:
        op.execute(statement)
    for name, args, callers, body in FUNCTIONS:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)


def downgrade() -> None:
    """Back to 0007: 0003's `_append_event` first (so no function names the table), then the purge policy and the
    outbox go and the jobs cells are 0002's again."""
    for name, args, callers, body in RESTORED:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)
    for statement in DOWNGRADE:
        op.execute(statement)
    for statement in privileges.grant_statements(("jobs",), JOB_CELLS_0002, revokees=MAIN_GRANTEES_0008):
        op.execute(statement)

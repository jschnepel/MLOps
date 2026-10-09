"""Roles, grants and row-level security (T09; AM-20.1, AM-20.2, AM-20.5, AM-20.6): the columns and tables AM-20
needs, ownership to `migrator`, the grant matrix from ops_core.privileges, forced RLS with the NULLIF policy, and
app.current_time().

Revision ID: 0002_roles_grants_rls
Revises: 0001_walking_skeleton

Runs as the Compose superuser (Plan E ruling 3): scripts/skeleton.py ensure_roles has created every role, so this
revision only alters, transfers and grants. Each statement is one op.execute string and the PL/pgSQL body is never
split (spike §4). The backfills read through the parents (runs, proposals, execution_grant, action_attempt) before
the NOT NULL and the composite keys are added, so an existing revision-1 database upgrades in place (R006).
"""

from __future__ import annotations

import re

from alembic import op
from ops_core import privileges

revision = "0002_roles_grants_rls"
down_revision = "0001_walking_skeleton"
branch_labels = None
depends_on = None

ACTIVE = (
    "'QUEUED','AWAITING_INPUT','RETRIEVING','DRAFTING','AWAITING_APPROVAL','APPROVED','EXECUTING','OUTCOME_UNKNOWN'"
)
# The tables that exist after this revision, as literals: an applied revision must not change when a later task
# adds a row to the live matrix (round-2 finding NI5); each later revision renders the statements for the tables it
# creates or changes. test_clock belongs to the testclock branch.
TABLES = (
    "tenants",
    "memberships",
    "sessions",
    "conversations",
    "messages",
    "runs",
    "run_directory",
    "run_state_history",
    "run_lease",
    "jobs",
    "invocation_context",
    "drafts",
    "proposals",
    "decisions",
    "execution_grant",
    "action_attempt",
    "action_attempt_state",
    "events",
    "transitions",
)
# The cells this revision applies, frozen (a later matrix change ships in a later revision; the unit test in
# tests/plan_e/test_transitions_table.py checks that the newest revision's cells equal the live matrix).
_S = privileges.Grant(sel=True)
_SI = privileges.Grant(sel=True, ins=True)
_INS = privileges.Grant(ins=True)
_DEF = privileges.DEFINER_ROLE
GRANTS_0002: dict[str, dict[str, privileges.Grant]] = {
    "tenants": {"api": _S, "worker": _S, "sweeper": _S, _DEF: _S},
    "memberships": {
        "api": _S,
        "worker": _S,
        "sweeper": privileges.Grant(sel=True, upd=("active", "permission_version", "synced_at")),
        _DEF: _S,
    },
    "sessions": {
        "api": privileges.Grant(sel=True, ins=True, upd=("last_seen_at", "revoked_at"), dele=True),
        "sweeper": privileges.Grant(dele=True),
    },
    "conversations": {"api": _SI, "worker": _S, _DEF: _S},
    "messages": {"api": _SI, "worker": _S, _DEF: _S},
    "runs": {
        "api": privileges.Grant(sel=True, upd=("cancel_requested", "cancel_requested_at")),
        "worker": privileges.Grant(sel=True, upd=("checkpoint_id", "budget_used")),
        "sweeper": _S,
        _DEF: privileges.Grant(
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
            ),
        ),
    },
    "run_directory": {"api": _S, "worker": _S, "sweeper": _S, _DEF: _SI},
    "run_state_history": {_DEF: _INS},
    "run_lease": {
        "worker": privileges.Grant(sel=True, ins=True, upd=True),
        "sweeper": privileges.Grant(sel=True, upd=("lease_until",)),
        _DEF: _S,
    },
    "jobs": {
        "api": _INS,
        "worker": privileges.Grant(
            sel=True, ins=True, upd=("claimed_by", "claimed_at", "done_at", "attempts", "available_at")
        ),
        "sweeper": privileges.Grant(sel=True, ins=True, upd=("claimed_by", "claimed_at", "done_at", "attempts")),
        _DEF: _SI,
    },
    "invocation_context": {"worker": _INS, "sweeper": _S, _DEF: privileges.Grant(sel=True, upd=("revoked_at",))},
    "drafts": {"worker": _SI, _DEF: _S},
    "proposals": {"api": _S, "worker": _S, "sweeper": _S, _DEF: _SI},
    "decisions": {"api": _S, "worker": _S, _DEF: _SI},
    "execution_grant": {"api": _S, "worker": _S, "sweeper": _S, _DEF: _SI},
    "action_attempt": {"api": _S, "worker": _S, "sweeper": _S, _DEF: _SI},
    "action_attempt_state": {"api": _S, "worker": _S, "sweeper": _S, _DEF: _SI},
    "events": {"api": _S, "worker": _S, "sweeper": _S, _DEF: _SI},
    "transitions": {_DEF: _S},
}
POLICY_ROLES_0002 = ("api", "worker", "sweeper", "app_definer")
RLS = (
    "memberships",
    "conversations",
    "messages",
    "runs",
    "run_state_history",
    "jobs",
    "drafts",
    "proposals",
    "decisions",
    "execution_grant",
    "action_attempt",
    "action_attempt_state",
    "events",
)
_WORD = re.compile(r"^[A-Za-z_]+$")
# The T07 table as this revision writes it, frozen (final review I2): reading ops_core.states.TRANSITIONS here would let
# a later edit change what this revision inserts, so upgraded and fresh databases would differ silently. A change to
# the table ships as a new revision with its own TRANSITION_ROWS_<rev>; the unit test checks that the newest one equals
# the live table. Rows are (src, dst, performer, reasons), sorted by (src, dst, performer); None is the creation edge.
TRANSITION_ROWS_0002 = (
    (None, "QUEUED", "create_run", ()),
    ("APPROVED", "BLOCKED_REVIEW", "expire_proposal", ("expired",)),
    (
        "APPROVED",
        "BLOCKED_REVIEW",
        "grant_execution",
        ("asset_action_unresolved", "asset_incident_exists", "authority_revoked", "expired", "stale_evidence"),
    ),
    ("APPROVED", "CANCELLED", "request_cancel", ()),
    ("APPROVED", "EXECUTING", "grant_execution", ()),
    ("APPROVED", "QUEUED", "create_revision", ()),
    ("AWAITING_APPROVAL", "APPROVED", "record_decision", ()),
    ("AWAITING_APPROVAL", "BLOCKED_REVIEW", "expire_proposal", ("expired",)),
    ("AWAITING_APPROVAL", "BLOCKED_REVIEW", "record_decision", ("expired",)),
    ("AWAITING_APPROVAL", "CANCELLED", "request_cancel", ()),
    ("AWAITING_APPROVAL", "QUEUED", "create_revision", ()),
    ("AWAITING_APPROVAL", "REJECTED", "record_decision", ("rejected",)),
    ("AWAITING_INPUT", "CANCELLED", "request_cancel", ()),
    ("AWAITING_INPUT", "QUEUED", "transition_run", ()),
    ("BLOCKED_REVIEW", "CANCELLED", "request_cancel", ()),
    ("BLOCKED_REVIEW", "QUEUED", "create_revision", ()),
    ("DRAFTING", "ANSWERED", "transition_run", ()),
    ("DRAFTING", "AWAITING_APPROVAL", "create_manual_proposal", ()),
    ("DRAFTING", "AWAITING_APPROVAL", "freeze_proposal", ()),
    ("DRAFTING", "AWAITING_INPUT", "transition_run", ()),
    ("DRAFTING", "BLOCKED_REVIEW", "create_manual_proposal", ("asset_action_unresolved", "asset_incident_exists")),
    ("DRAFTING", "BLOCKED_REVIEW", "freeze_proposal", ("asset_action_unresolved", "asset_incident_exists")),
    ("DRAFTING", "CANCELLED", "request_cancel", ()),
    ("DRAFTING", "FAILED", "transition_run", ()),
    ("DRAFTING", "INSUFFICIENT_EVIDENCE", "transition_run", ()),
    ("ESCALATED", "ABANDONED_UNVERIFIED", "resolve_escalation", ()),
    ("ESCALATED", "FAILED", "record_outcome", ("aborted_no_commit", "cancelled_before_send", "expired", "rejected")),
    ("ESCALATED", "SUCCEEDED", "record_outcome", ()),
    ("EXECUTING", "ESCALATED", "escalate_run", ("conflict", "escalation_deadline")),
    ("EXECUTING", "ESCALATED", "record_outcome", ("conflict",)),
    ("EXECUTING", "FAILED", "record_outcome", ("aborted_no_commit", "cancelled_before_send", "expired", "rejected")),
    ("EXECUTING", "OUTCOME_UNKNOWN", "mark_unknown", ()),
    ("EXECUTING", "SUCCEEDED", "record_outcome", ()),
    ("OUTCOME_UNKNOWN", "ESCALATED", "escalate_run", ("conflict", "escalation_deadline")),
    ("OUTCOME_UNKNOWN", "ESCALATED", "record_outcome", ("conflict",)),
    (
        "OUTCOME_UNKNOWN",
        "FAILED",
        "record_outcome",
        ("aborted_no_commit", "cancelled_before_send", "expired", "rejected"),
    ),
    ("OUTCOME_UNKNOWN", "SUCCEEDED", "record_outcome", ()),
    ("QUEUED", "CANCELLED", "request_cancel", ()),
    ("QUEUED", "RETRIEVING", "transition_run", ()),
    ("RETRIEVING", "AWAITING_INPUT", "transition_run", ()),
    ("RETRIEVING", "CANCELLED", "request_cancel", ()),
    ("RETRIEVING", "DRAFTING", "transition_run", ()),
    ("RETRIEVING", "FAILED", "transition_run", ()),
    ("RETRIEVING", "INSUFFICIENT_EVIDENCE", "transition_run", ()),
)
# The roles this revision grants to and revokes from, frozen for the same reason (final review M2): a role added to
# ops_core.privileges later must not change what an applied revision runs. test_harness is the testclock branch's.
MAIN_GRANTEES_0002 = ("api", "worker", "sweeper", "mcp_read", "mcp_exec", "operator", "app_definer")

SCHEMA_CHANGES = (
    # runs: the slot flag (SA:451), the event counter (SA:439) and the columns the AM-20.2 grants name.
    (
        "ALTER TABLE app.runs"
        " ADD COLUMN slot_held boolean NOT NULL DEFAULT false,"
        " ADD COLUMN next_event_seq integer NOT NULL DEFAULT 0,"
        " ADD COLUMN cancel_requested_at timestamptz,"
        " ADD COLUMN checkpoint_id text,"
        " ADD COLUMN budget_used integer NOT NULL DEFAULT 0"
    ),
    (
        f"UPDATE app.runs r SET slot_held = (r.state IN ({ACTIVE})),"
        " next_event_seq = COALESCE((SELECT max(e.sequence) FROM app.events e WHERE e.run_id = r.run_id), 0)"
    ),
    "DROP INDEX app.runs_one_active_per_conversation",
    "CREATE UNIQUE INDEX runs_one_active_per_conversation ON app.runs (conversation_id) WHERE slot_held",
    # R009: every child references its parent through the tenant.
    "ALTER TABLE app.messages ADD CONSTRAINT messages_tenant_message_key UNIQUE (tenant_id, message_id)",
    "ALTER TABLE app.runs DROP CONSTRAINT runs_message_id_fkey",
    (
        "ALTER TABLE app.runs ADD CONSTRAINT runs_tenant_message_fkey"
        " FOREIGN KEY (tenant_id, message_id) REFERENCES app.messages (tenant_id, message_id)"
    ),
    "ALTER TABLE app.run_state_history ADD COLUMN tenant_id uuid",
    "UPDATE app.run_state_history h SET tenant_id = r.tenant_id FROM app.runs r WHERE r.run_id = h.run_id",
    (
        "ALTER TABLE app.run_state_history ALTER COLUMN tenant_id SET NOT NULL,"
        " DROP CONSTRAINT run_state_history_run_id_fkey,"
        " ADD CONSTRAINT run_state_history_tenant_run_fkey"
        " FOREIGN KEY (tenant_id, run_id) REFERENCES app.runs (tenant_id, run_id)"
    ),
    # jobs: tenant nullable (sweeper jobs have none, SA:504) and run_id nullable for the same reason.
    "ALTER TABLE app.jobs ADD COLUMN tenant_id uuid",
    "UPDATE app.jobs j SET tenant_id = r.tenant_id FROM app.runs r WHERE r.run_id = j.run_id",
    (
        "ALTER TABLE app.jobs ALTER COLUMN run_id DROP NOT NULL,"
        " DROP CONSTRAINT jobs_run_id_fkey,"
        " ADD CONSTRAINT jobs_tenant_run_fkey FOREIGN KEY (tenant_id, run_id) REFERENCES app.runs (tenant_id, run_id),"
        " ADD CONSTRAINT jobs_tenant_iff_run_check CHECK ((run_id IS NULL) = (tenant_id IS NULL))"
    ),
    "ALTER TABLE app.drafts ADD COLUMN tenant_id uuid",
    "UPDATE app.drafts d SET tenant_id = r.tenant_id FROM app.runs r WHERE r.run_id = d.run_id",
    (
        "ALTER TABLE app.drafts ALTER COLUMN tenant_id SET NOT NULL,"
        " DROP CONSTRAINT drafts_run_id_fkey,"
        " ADD CONSTRAINT drafts_tenant_run_fkey FOREIGN KEY (tenant_id, run_id)"
        " REFERENCES app.runs (tenant_id, run_id),"
        " ADD CONSTRAINT drafts_tenant_id_key UNIQUE (tenant_id, id)"
    ),
    (
        "ALTER TABLE app.proposals DROP CONSTRAINT proposals_run_id_fkey, DROP CONSTRAINT proposals_draft_id_fkey,"
        " ADD CONSTRAINT proposals_tenant_run_fkey FOREIGN KEY (tenant_id, run_id)"
        " REFERENCES app.runs (tenant_id, run_id),"
        " ADD CONSTRAINT proposals_tenant_draft_fkey FOREIGN KEY (tenant_id, draft_id)"
        " REFERENCES app.drafts (tenant_id, id),"
        " ADD CONSTRAINT proposals_tenant_proposal_key UNIQUE (tenant_id, proposal_id)"
    ),
    "ALTER TABLE app.decisions ADD COLUMN tenant_id uuid, ADD COLUMN idempotency_key text",
    "UPDATE app.decisions d SET tenant_id = p.tenant_id FROM app.proposals p WHERE p.proposal_id = d.proposal_id",
    (
        "ALTER TABLE app.decisions ALTER COLUMN tenant_id SET NOT NULL,"
        " DROP CONSTRAINT decisions_proposal_id_fkey,"
        " ADD CONSTRAINT decisions_tenant_proposal_fkey"
        " FOREIGN KEY (tenant_id, proposal_id) REFERENCES app.proposals (tenant_id, proposal_id)"
    ),
    "ALTER TABLE app.execution_grant ADD COLUMN tenant_id uuid",
    "UPDATE app.execution_grant g SET tenant_id = r.tenant_id FROM app.runs r WHERE r.run_id = g.run_id",
    (
        "ALTER TABLE app.execution_grant ALTER COLUMN tenant_id SET NOT NULL,"
        " DROP CONSTRAINT execution_grant_run_id_fkey, DROP CONSTRAINT execution_grant_proposal_id_fkey,"
        " ADD CONSTRAINT execution_grant_tenant_run_fkey"
        " FOREIGN KEY (tenant_id, run_id) REFERENCES app.runs (tenant_id, run_id),"
        " ADD CONSTRAINT execution_grant_tenant_proposal_fkey"
        " FOREIGN KEY (tenant_id, proposal_id) REFERENCES app.proposals (tenant_id, proposal_id),"
        " ADD CONSTRAINT execution_grant_tenant_action_key UNIQUE (tenant_id, action_id)"
    ),
    "ALTER TABLE app.action_attempt ADD COLUMN tenant_id uuid",
    (
        "UPDATE app.action_attempt a SET tenant_id = g.tenant_id FROM app.execution_grant g"
        " WHERE g.action_id = a.action_id"
    ),
    (
        "ALTER TABLE app.action_attempt ALTER COLUMN tenant_id SET NOT NULL,"
        " DROP CONSTRAINT action_attempt_action_id_fkey,"
        " ADD CONSTRAINT action_attempt_tenant_action_fkey"
        " FOREIGN KEY (tenant_id, action_id) REFERENCES app.execution_grant (tenant_id, action_id),"
        " ADD CONSTRAINT action_attempt_tenant_attempt_key UNIQUE (tenant_id, action_id, attempt_no)"
    ),
    "ALTER TABLE app.action_attempt_state ADD COLUMN tenant_id uuid",
    (
        "UPDATE app.action_attempt_state s SET tenant_id = a.tenant_id FROM app.action_attempt a"
        " WHERE a.action_id = s.action_id AND a.attempt_no = s.attempt_no"
    ),
    (
        "ALTER TABLE app.action_attempt_state ALTER COLUMN tenant_id SET NOT NULL,"
        " DROP CONSTRAINT action_attempt_state_action_id_attempt_no_fkey,"
        " ADD CONSTRAINT action_attempt_state_tenant_attempt_fkey"
        " FOREIGN KEY (tenant_id, action_id, attempt_no)"
        " REFERENCES app.action_attempt (tenant_id, action_id, attempt_no)"
    ),
    (
        "ALTER TABLE app.events DROP CONSTRAINT events_run_id_fkey,"
        " ADD CONSTRAINT events_tenant_run_fkey FOREIGN KEY (tenant_id, run_id) REFERENCES app.runs (tenant_id, run_id)"
    ),
    # Handles are 60-second capabilities: nothing in the table is worth keeping, so the raw column is replaced
    # by its hash (SA:496, BS:360) on an empty table.
    "TRUNCATE app.invocation_context",
    "ALTER TABLE app.invocation_context DROP COLUMN handle",
    "ALTER TABLE app.invocation_context ADD COLUMN handle_sha256 text PRIMARY KEY, ALTER COLUMN fence TYPE bigint",
    # RLS-free bootstrap tables (SA:523): the directory the functions resolve a tenant through, the lease (T13 fills
    # it), the session store (T11 fills it), and the T07 transition table mirrored as data (ruling 10).
    (
        "CREATE TABLE app.run_directory ("
        " run_id uuid PRIMARY KEY REFERENCES app.runs (run_id),"
        " tenant_id uuid NOT NULL REFERENCES app.tenants (tenant_id),"
        " FOREIGN KEY (tenant_id, run_id) REFERENCES app.runs (tenant_id, run_id))"
    ),
    "INSERT INTO app.run_directory (run_id, tenant_id) SELECT run_id, tenant_id FROM app.runs",
    (
        "CREATE TABLE app.run_lease ("
        " run_id uuid PRIMARY KEY REFERENCES app.runs (run_id),"
        " owner text NOT NULL,"
        " lease_until timestamptz NOT NULL,"
        " fence bigint NOT NULL DEFAULT 1)"
    ),
    (
        "CREATE TABLE app.sessions ("
        " session_sha256 text PRIMARY KEY,"
        " issuer text NOT NULL,"
        " subject uuid NOT NULL,"
        " tenant_id uuid NOT NULL REFERENCES app.tenants (tenant_id),"
        " csrf_secret_sha256 text NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " expires_at timestamptz NOT NULL,"
        " last_seen_at timestamptz NOT NULL DEFAULT now(),"
        " revoked_at timestamptz)"
    ),
    (
        "CREATE TABLE app.transitions ("
        " src text NOT NULL,"
        " dst text NOT NULL,"
        " performer text NOT NULL,"
        " reasons text[] NOT NULL,"
        " PRIMARY KEY (src, dst, performer))"
    ),
)

OWNERSHIP = (
    "ALTER SCHEMA app OWNER TO migrator",
    # Every relation kind, tables before sequences: a column-owned sequence refuses its own ALTER (its owner
    # follows the column), so it must not come first.
    """
    DO $own$
    DECLARE
        r record;
    BEGIN
        FOR r IN SELECT c.oid::regclass AS rel FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = 'app' AND c.relkind IN ('r', 'p', 'm', 'v', 'f', 'S')
                 ORDER BY CASE WHEN c.relkind = 'S' THEN 1 ELSE 0 END, c.oid
        LOOP
            EXECUTE format('ALTER TABLE %s OWNER TO migrator', r.rel);
        END LOOP;
    END
    $own$
    """,
)

CURRENT_TIME = """
CREATE OR REPLACE FUNCTION app.current_time() RETURNS timestamptz
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = app, pg_temp SET app.tenant_id = '' AS $fn$
DECLARE
    v_offset interval;
BEGIN
    -- VOLATILE, not STABLE: clock_timestamp() changes within a statement.
    -- The table exists only where the testclock branch is applied, so the reference is dynamic (SA:528), and no
    -- GUC is consulted anywhere: a SET cannot move the clock (R126). Owned by app_definer so the read of
    -- test_clock uses its grant and no caller needs one (Plan E ruling 17).
    IF to_regclass('app.test_clock') IS NULL THEN
        RETURN clock_timestamp();
    END IF;
    EXECUTE 'SELECT clock_offset FROM app.test_clock LIMIT 1' INTO v_offset;
    RETURN clock_timestamp() + coalesce(v_offset, interval '0');
END
$fn$;
ALTER FUNCTION app.current_time() OWNER TO app_definer;
"""


def transition_rows() -> list[str]:
    """One INSERT per frozen T07 row; the values are checked against a word pattern before they are quoted."""
    out: list[str] = []
    for src, dst, performer, reasons in TRANSITION_ROWS_0002:
        parts = [src or "", dst, performer, *reasons]
        if any(part and not _WORD.match(part) for part in parts):
            raise RuntimeError("transition table values must be plain words")
        quoted = ", ".join(f"'{r}'" for r in reasons)
        array = f"ARRAY[{quoted}]::text[]" if quoted else "ARRAY[]::text[]"
        out.append(
            "INSERT INTO app.transitions (src, dst, performer, reasons)"
            f" VALUES ('{src or ''}', '{dst}', '{performer}', {array})"
        )
    return out


def upgrade() -> None:
    """Add the AM-20 columns and tables, backfill them, hand ownership to migrator, grant, and force RLS."""
    for statement in SCHEMA_CHANGES:
        op.execute(statement)
    for statement in transition_rows():
        op.execute(statement)
    for statement in OWNERSHIP:
        op.execute(statement)
    for statement in privileges.schema_usage_statements(MAIN_GRANTEES_0002):
        op.execute(statement)
    for statement in privileges.grant_statements(TABLES, GRANTS_0002, revokees=MAIN_GRANTEES_0002):
        op.execute(statement)
    for statement in privileges.rls_statements(RLS, POLICY_ROLES_0002):
        op.execute(statement)
    op.execute(CURRENT_TIME)
    for statement in privileges.function_grant_statements(
        "current_time", args="", callers=("api", "worker", "sweeper", "mcp_read", "mcp_exec", "operator")
    ):
        op.execute(statement)


DOWNGRADE = (
    "DROP FUNCTION app.current_time()",
    *[f"DROP POLICY IF EXISTS sweeper_all ON app.{t}" for t in ("memberships", "jobs")],
    *[f"DROP POLICY IF EXISTS tenant_isolation ON app.{t}" for t in RLS],
    *[f"ALTER TABLE app.{t} NO FORCE ROW LEVEL SECURITY, DISABLE ROW LEVEL SECURITY" for t in RLS],
    f"REVOKE ALL ON ALL TABLES IN SCHEMA app FROM {', '.join(MAIN_GRANTEES_0002)}",
    f"REVOKE USAGE ON SCHEMA app FROM {', '.join(MAIN_GRANTEES_0002)}",
    "DROP TABLE app.transitions",
    "DROP TABLE app.sessions",
    "DROP TABLE app.run_lease",
    "DROP TABLE app.run_directory",
    "TRUNCATE app.invocation_context",
    "ALTER TABLE app.invocation_context DROP COLUMN handle_sha256, ALTER COLUMN fence TYPE integer",
    "ALTER TABLE app.invocation_context ADD COLUMN handle text PRIMARY KEY",
    (
        "ALTER TABLE app.events DROP CONSTRAINT events_tenant_run_fkey,"
        " ADD CONSTRAINT events_run_id_fkey FOREIGN KEY (run_id) REFERENCES app.runs (run_id)"
    ),
    (
        "ALTER TABLE app.action_attempt_state DROP CONSTRAINT action_attempt_state_tenant_attempt_fkey,"
        " ADD CONSTRAINT action_attempt_state_action_id_attempt_no_fkey"
        " FOREIGN KEY (action_id, attempt_no) REFERENCES app.action_attempt (action_id, attempt_no),"
        " DROP COLUMN tenant_id"
    ),
    (
        "ALTER TABLE app.action_attempt DROP CONSTRAINT action_attempt_tenant_attempt_key,"
        " DROP CONSTRAINT action_attempt_tenant_action_fkey,"
        " ADD CONSTRAINT action_attempt_action_id_fkey FOREIGN KEY (action_id)"
        " REFERENCES app.execution_grant (action_id),"
        " DROP COLUMN tenant_id"
    ),
    (
        "ALTER TABLE app.execution_grant DROP CONSTRAINT execution_grant_tenant_action_key,"
        " DROP CONSTRAINT execution_grant_tenant_run_fkey, DROP CONSTRAINT execution_grant_tenant_proposal_fkey,"
        " ADD CONSTRAINT execution_grant_run_id_fkey FOREIGN KEY (run_id) REFERENCES app.runs (run_id),"
        " ADD CONSTRAINT execution_grant_proposal_id_fkey FOREIGN KEY (proposal_id)"
        " REFERENCES app.proposals (proposal_id),"
        " DROP COLUMN tenant_id"
    ),
    (
        "ALTER TABLE app.decisions DROP CONSTRAINT decisions_tenant_proposal_fkey,"
        " ADD CONSTRAINT decisions_proposal_id_fkey FOREIGN KEY (proposal_id) REFERENCES app.proposals (proposal_id),"
        " DROP COLUMN tenant_id, DROP COLUMN idempotency_key"
    ),
    (
        "ALTER TABLE app.proposals DROP CONSTRAINT proposals_tenant_proposal_key,"
        " DROP CONSTRAINT proposals_tenant_run_fkey, DROP CONSTRAINT proposals_tenant_draft_fkey,"
        " ADD CONSTRAINT proposals_run_id_fkey FOREIGN KEY (run_id) REFERENCES app.runs (run_id),"
        " ADD CONSTRAINT proposals_draft_id_fkey FOREIGN KEY (draft_id) REFERENCES app.drafts (id)"
    ),
    (
        "ALTER TABLE app.drafts DROP CONSTRAINT drafts_tenant_run_fkey, DROP CONSTRAINT drafts_tenant_id_key,"
        " ADD CONSTRAINT drafts_run_id_fkey FOREIGN KEY (run_id) REFERENCES app.runs (run_id), DROP COLUMN tenant_id"
    ),
    "DELETE FROM app.jobs WHERE run_id IS NULL",
    (
        "ALTER TABLE app.jobs DROP CONSTRAINT jobs_tenant_run_fkey, DROP CONSTRAINT jobs_tenant_iff_run_check,"
        " ADD CONSTRAINT jobs_run_id_fkey FOREIGN KEY (run_id) REFERENCES app.runs (run_id),"
        " ALTER COLUMN run_id SET NOT NULL, DROP COLUMN tenant_id"
    ),
    (
        "ALTER TABLE app.run_state_history DROP CONSTRAINT run_state_history_tenant_run_fkey,"
        " ADD CONSTRAINT run_state_history_run_id_fkey FOREIGN KEY (run_id) REFERENCES app.runs (run_id),"
        " DROP COLUMN tenant_id"
    ),
    (
        "ALTER TABLE app.runs DROP CONSTRAINT runs_tenant_message_fkey,"
        " ADD CONSTRAINT runs_message_id_fkey FOREIGN KEY (message_id) REFERENCES app.messages (message_id)"
    ),
    "ALTER TABLE app.messages DROP CONSTRAINT messages_tenant_message_key",
    "DROP INDEX app.runs_one_active_per_conversation",
    f"CREATE UNIQUE INDEX runs_one_active_per_conversation ON app.runs (conversation_id) WHERE state IN ({ACTIVE})",
    (
        "ALTER TABLE app.runs DROP COLUMN slot_held, DROP COLUMN next_event_seq, DROP COLUMN cancel_requested_at,"
        " DROP COLUMN checkpoint_id, DROP COLUMN budget_used"
    ),
    "ALTER SCHEMA app OWNER TO CURRENT_USER",
    """
    DO $own$
    DECLARE
        r record;
    BEGIN
        FOR r IN SELECT c.oid::regclass AS rel FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = 'app' AND c.relkind IN ('r', 'p', 'm', 'v', 'f', 'S')
                 ORDER BY CASE WHEN c.relkind = 'S' THEN 1 ELSE 0 END, c.oid
        LOOP
            EXECUTE format('ALTER TABLE %s OWNER TO CURRENT_USER', r.rel);
        END LOOP;
    END
    $own$
    """,
)


def downgrade() -> None:
    """Back to revision 1: drop the policies, grants and new tables, and restore the revision-1 columns and keys."""
    for statement in DOWNGRADE:
        op.execute(statement)

"""Walking skeleton: the run path's tables with their AM-20.2 names (T08; T09 re-owns, adds roles and RLS).

Revision ID: 0001_walking_skeleton
Revises: None

Only the tables the skeleton path touches exist (ruling 7 of Plan D). Column names follow SPEC_AMENDMENTS AM-20.2 /
AM-20.4 so T09's revision alters rather than renames; the one deliberate exception is `invocation_context.handle`
(raw, debt → T09/T15 replaces it by `handle_sha256`). Audit tables are append-only by shape: `run_state_history`,
`action_attempt_state` and `events` have no updatable business columns (AM-20 principle 2). Seed rows: the two tenants
and five persona memberships from data/seed-ids.json, written here because no runtime role may insert them (SA:440).
Carries the `app` branch label so `migrate` can name the main line (`app@head`) while the `testclock` branch stays
test-only (spike §4).
"""

import json
import os
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0001_walking_skeleton"
down_revision = None
branch_labels = ("app",)
depends_on = None

# AM-10 active states, for the one-active-run-per-conversation rule (BUILD_SPEC §7; T12 owns the admission test).
ACTIVE = (
    "'QUEUED','AWAITING_INPUT','RETRIEVING','DRAFTING','AWAITING_APPROVAL','APPROVED','EXECUTING','OUTCOME_UNKNOWN'"
)

DDL = f"""
CREATE SCHEMA app;

CREATE TABLE app.tenants (
    tenant_id uuid PRIMARY KEY,
    name text NOT NULL UNIQUE
);

-- Identity is (issuer, subject) (BUILD_SPEC §9); membership, not the token, decides the tenant and the role.
CREATE TABLE app.memberships (
    tenant_id uuid NOT NULL REFERENCES app.tenants (tenant_id),
    issuer text NOT NULL,
    subject uuid NOT NULL,
    role text NOT NULL CHECK (role IN ('requester', 'reviewer', 'reader')),
    active boolean NOT NULL DEFAULT true,
    permission_version integer NOT NULL DEFAULT 1,
    synced_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, issuer, subject, role)
);

CREATE TABLE app.conversations (
    conversation_id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES app.tenants (tenant_id),
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, conversation_id)
);

CREATE TABLE app.messages (
    message_id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL,
    conversation_id uuid NOT NULL,
    kind text NOT NULL,
    text text NOT NULL,
    context jsonb,
    author uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, conversation_id) REFERENCES app.conversations (tenant_id, conversation_id)
);

CREATE TABLE app.runs (
    run_id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL,
    conversation_id uuid NOT NULL,
    message_id uuid NOT NULL REFERENCES app.messages (message_id),
    requester uuid NOT NULL,
    intent text NOT NULL CHECK (intent IN ('investigate', 'answer_only')),
    supersedes_run_id uuid,
    asset_id text NOT NULL,
    start_at timestamptz NOT NULL,
    end_at timestamptz NOT NULL,
    state text NOT NULL,
    state_version integer NOT NULL DEFAULT 1,
    reason text,
    active_proposal_id uuid,
    cancel_requested boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (start_at < end_at),
    UNIQUE (tenant_id, run_id),
    FOREIGN KEY (tenant_id, conversation_id) REFERENCES app.conversations (tenant_id, conversation_id)
);
CREATE UNIQUE INDEX runs_one_active_per_conversation ON app.runs (conversation_id) WHERE state IN ({ACTIVE});

CREATE TABLE app.run_state_history (
    run_id uuid NOT NULL REFERENCES app.runs (run_id),
    seq integer NOT NULL,
    from_state text,
    to_state text NOT NULL,
    performer text NOT NULL,
    reason text,
    at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, seq)
);

CREATE TABLE app.jobs (
    id uuid PRIMARY KEY,
    type text NOT NULL,
    run_id uuid NOT NULL REFERENCES app.runs (run_id),
    dedup_key text NOT NULL UNIQUE,
    available_at timestamptz NOT NULL DEFAULT now(),
    claimed_by text,
    claimed_at timestamptz,
    attempts integer NOT NULL DEFAULT 0,
    done_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX jobs_claimable ON app.jobs (available_at) WHERE done_at IS NULL AND claimed_at IS NULL;

CREATE TABLE app.invocation_context (
    handle text PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES app.runs (run_id),
    job_id uuid NOT NULL REFERENCES app.jobs (id),
    server text NOT NULL CHECK (server IN ('read', 'write')),
    fence integer NOT NULL DEFAULT 1,
    azp text NOT NULL,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.drafts (
    id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES app.runs (run_id),
    draft_sha256 text NOT NULL,
    validated boolean NOT NULL,
    kind text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.proposals (
    proposal_id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL,
    run_id uuid NOT NULL REFERENCES app.runs (run_id),
    revision integer NOT NULL,
    draft_id uuid NOT NULL REFERENCES app.drafts (id),
    payload jsonb NOT NULL,
    payload_canonical bytea NOT NULL,
    payload_sha256 text NOT NULL,
    canonicalization_version integer NOT NULL,
    authored_by uuid[] NOT NULL,
    expires_at timestamptz NOT NULL,
    frozen_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, revision)
);

-- UNIQUE (proposal_id): the first accepted decision wins (SA:454); a second one is a 409, never an overwrite.
CREATE TABLE app.decisions (
    decision_id uuid PRIMARY KEY,
    proposal_id uuid NOT NULL UNIQUE REFERENCES app.proposals (proposal_id),
    reviewer uuid NOT NULL,
    decision text NOT NULL CHECK (decision IN ('approve', 'reject')),
    reason text,
    expected_payload_sha256 text NOT NULL,
    decided_at timestamptz NOT NULL DEFAULT now()
);

-- At most one grant per run, ever (SA:167): UNIQUE (run_id) is the rule, not application code.
CREATE TABLE app.execution_grant (
    action_id uuid PRIMARY KEY,
    run_id uuid NOT NULL UNIQUE REFERENCES app.runs (run_id),
    proposal_id uuid NOT NULL REFERENCES app.proposals (proposal_id),
    payload_sha256 text NOT NULL,
    granted_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.action_attempt (
    action_id uuid NOT NULL REFERENCES app.execution_grant (action_id),
    attempt_no integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (action_id, attempt_no)
);

CREATE TABLE app.action_attempt_state (
    action_id uuid NOT NULL,
    attempt_no integer NOT NULL,
    seq integer NOT NULL,
    state text NOT NULL CHECK (state IN ('INTENT', 'SENT', 'ABORT_REQUESTED', 'RESOLVED')),
    outcome text,
    detail jsonb,
    at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (action_id, attempt_no, seq),
    FOREIGN KEY (action_id, attempt_no) REFERENCES app.action_attempt (action_id, attempt_no)
);

CREATE TABLE app.events (
    event_id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL,
    conversation_id uuid NOT NULL,
    run_id uuid NOT NULL REFERENCES app.runs (run_id),
    sequence integer NOT NULL,
    type text NOT NULL,
    occurred_at timestamptz NOT NULL,
    source text NOT NULL CHECK (source IN ('application', 'destination', 'model_summary')),
    payload jsonb NOT NULL,
    UNIQUE (run_id, sequence)
);
"""


def upgrade() -> None:
    for statement in DDL.split(";\n"):
        if statement.strip():
            op.execute(statement)
    seeds = json.loads((Path(__file__).resolve().parents[3] / "data" / "seed-ids.json").read_text(encoding="utf-8"))
    # Declared shortcut (SESSION_STATE debt, last line): frozen at migration time; T09's membership sync owns it.
    # The issuer is part of the membership identity; the dev default matches scripts/bootstrap_dev.py.
    issuer = os.environ.get("OPS_KC_ISSUER") or "http://localhost:18080/realms/ops-dev"
    tenants = sa.table("tenants", sa.column("tenant_id"), sa.column("name"), schema="app")
    op.bulk_insert(tenants, [{"tenant_id": tid, "name": name} for name, tid in seeds["tenants"].items()])
    memberships = sa.table(
        "memberships",
        sa.column("tenant_id"),
        sa.column("issuer"),
        sa.column("subject"),
        sa.column("role"),
        schema="app",
    )
    op.bulk_insert(
        memberships,
        [
            {"tenant_id": seeds["tenants"][p["tenant"]], "issuer": issuer, "subject": p["user_id"], "role": role}
            for p in seeds["personas"].values()
            for role in p["roles"]
        ],
    )


def downgrade() -> None:
    op.execute("DROP SCHEMA app CASCADE")

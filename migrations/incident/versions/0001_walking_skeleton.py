"""Destination (incident-sim) database: the single `action_key` table and the incidents it commits
(AM-13 §4; T10 extends).

Revision ID: 0001_walking_skeleton
Revises: None

Runs as the Compose superuser against database `incident` and hands everything to role `incident`, which
scripts/skeleton.py creates first from the `postgres_incident_password` secret file. The application database never
sees these tables and the `incident` role sees no application table (BUILD_SPEC §14: separate credentials).
"""

from alembic import op

revision = "0001_walking_skeleton"
down_revision = None
branch_labels = None
depends_on = None

DDL = """
CREATE SCHEMA incident AUTHORIZATION incident;

-- All three states are permanent and terminal; rows are never deleted (SA:259, SA:265).
CREATE TABLE incident.action_key (
    action_id uuid PRIMARY KEY,
    payload_sha256 text NOT NULL,
    state text NOT NULL CHECK (state IN ('COMMITTED', 'ABORTED', 'REJECTED')),
    incident_id text,
    reason text,
    receipt_id uuid,
    decided_at timestamptz NOT NULL DEFAULT now()
);

-- Incident numbers may have gaps: a conflicting insert consumes nextval too.
CREATE SEQUENCE incident.incident_seq;

CREATE TABLE incident.incidents (
    incident_id text PRIMARY KEY,
    action_id uuid NOT NULL UNIQUE REFERENCES incident.action_key (action_id),
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE incident.action_key OWNER TO incident;
ALTER TABLE incident.incidents OWNER TO incident;
ALTER SEQUENCE incident.incident_seq OWNER TO incident;
"""


def upgrade() -> None:
    for statement in DDL.split(";\n"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    op.execute("DROP SCHEMA incident CASCADE")

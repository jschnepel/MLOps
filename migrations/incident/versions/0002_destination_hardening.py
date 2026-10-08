"""Ownership and grants for the destination (T10; SA:265, BS:489, R096): `incident_owner` owns the schema, the
runtime role `incident` can INSERT and SELECT and nothing else, so keys can never be deleted or rewritten by the
service; plus two CHECKs that keep receipts and tombstones honest.

Revision ID: 0002_destination_hardening
Revises: 0001_walking_skeleton

Runs as the Compose superuser against database `incident`; scripts/skeleton.py ensure_roles has created
`incident_owner` (NOLOGIN) and narrowed CONNECT to `incident`.
"""

from alembic import op

revision = "0002_destination_hardening"
down_revision = "0001_walking_skeleton"
branch_labels = None
depends_on = None

UPGRADE = (
    "ALTER SCHEMA incident OWNER TO incident_owner",
    "ALTER TABLE incident.action_key OWNER TO incident_owner",
    "ALTER TABLE incident.incidents OWNER TO incident_owner",
    "ALTER SEQUENCE incident.incident_seq OWNER TO incident_owner",
    "REVOKE ALL ON ALL TABLES IN SCHEMA incident FROM incident",
    "REVOKE ALL ON ALL SEQUENCES IN SCHEMA incident FROM incident",
    "GRANT USAGE ON SCHEMA incident TO incident",
    "GRANT SELECT, INSERT ON incident.action_key, incident.incidents TO incident",
    "GRANT USAGE ON SEQUENCE incident.incident_seq TO incident",
    # A receipt exists iff the key committed; a tombstone never carries one.
    (
        "ALTER TABLE incident.action_key"
        " ADD CONSTRAINT action_key_receipt_iff_committed CHECK ((state = 'COMMITTED') = (receipt_id IS NOT NULL)),"
        " ADD CONSTRAINT action_key_incident_iff_committed CHECK ((state = 'COMMITTED') = (incident_id IS NOT NULL))"
    ),
)

DOWNGRADE = (
    (
        "ALTER TABLE incident.action_key DROP CONSTRAINT action_key_receipt_iff_committed,"
        " DROP CONSTRAINT action_key_incident_iff_committed"
    ),
    "ALTER SCHEMA incident OWNER TO incident",
    "ALTER TABLE incident.action_key OWNER TO incident",
    "ALTER TABLE incident.incidents OWNER TO incident",
    "ALTER SEQUENCE incident.incident_seq OWNER TO incident",
)


def upgrade() -> None:
    """Hand the schema to incident_owner, narrow `incident` to INSERT and SELECT, and add the two CHECKs."""
    for statement in UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    """Drop the two CHECKs and give the objects back to `incident`, whose ownership restores its revision-1 rights."""
    for statement in DOWNGRADE:
        op.execute(statement)

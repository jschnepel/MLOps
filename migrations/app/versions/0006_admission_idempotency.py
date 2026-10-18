"""The request-dedup record and the message vocabulary admission writes (T12, Plan G rulings 4, 8 and 26).

Revision ID: 0006_admission_idempotency
Revises: 0005_sessions_login_logout

`idempotency_request` is the scoped Idempotency-Key record (BS:244, SA:429): one row per (tenant, subject, route,
key), written last in the unit that did the work (SA:188), holding the status and the body a replay returns. No RLS
(SA:523); the grants are the control: `api` selects and inserts (no UPDATE, so a record is write-once), the sweeper
selects and deletes expired rows (erratum 25 again: a DELETE with a WHERE needs SELECT, spike §1). `messages` gains
`seq`, an identity column, because two rows written in one transaction share `now()` (spike §6: a status question and
its answer would otherwise have no order) and an identity needs only INSERT where a serial needs USAGE on its
sequence; a CHECK on `kind` names the stored vocabulary; `author` becomes nullable for the two system kinds and only
for them. Every cell is frozen here (round-3 finding N1 of Plan E).
"""

from alembic import op
from ops_core import privileges

revision = "0006_admission_idempotency"
down_revision = "0005_sessions_login_logout"
branch_labels = None
depends_on = None

TABLES = ("idempotency_request",)
MAIN_GRANTEES_0006 = ("api", "worker", "sweeper", "mcp_read", "mcp_exec", "operator", "app_definer")
GRANTS_0006: dict[str, dict[str, privileges.Grant]] = {
    "idempotency_request": {
        "api": privileges.Grant(sel=True, ins=True),
        "sweeper": privileges.Grant(sel=True, dele=True),
    },
}
# The stored `messages.kind` vocabulary (ruling 26) and its two system kinds, frozen here; a unit test compares them
# with ops_core.contracts.StoredMessageKind.
STORED_KINDS_0006 = (
    "investigate",
    "ask",
    "clarification_reply",
    "status_question",
    "status_answer",
    "clarification_question",
)
SYSTEM_KINDS_0006 = ("status_answer", "clarification_question")
KINDS = ", ".join(f"'{kind}'" for kind in STORED_KINDS_0006)
SYSTEM_KINDS = ", ".join(f"'{kind}'" for kind in SYSTEM_KINDS_0006)

SCHEMA_CHANGES = (
    (
        "CREATE TABLE app.idempotency_request ("
        " tenant_id uuid NOT NULL,"
        " subject uuid NOT NULL,"
        " route text NOT NULL,"
        " key text NOT NULL,"
        " fingerprint_sha256 text NOT NULL,"
        " status_code smallint NOT NULL,"
        " response jsonb NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT clock_timestamp(),"
        " expires_at timestamptz NOT NULL,"
        " PRIMARY KEY (tenant_id, subject, route, key))"
    ),
    "CREATE INDEX idempotency_request_expires_idx ON app.idempotency_request (expires_at)",
    "ALTER TABLE app.idempotency_request OWNER TO migrator",
    # Existing rows are numbered in physical scan order during the rewrite (harmless: 0005-era writers stored only
    # `investigate` messages); readers needing history order on pre-0006 rows sort by (created_at, seq).
    "ALTER TABLE app.messages ADD COLUMN seq bigint GENERATED ALWAYS AS IDENTITY NOT NULL",
    "ALTER TABLE app.messages ADD CONSTRAINT messages_conversation_seq_key UNIQUE (conversation_id, seq)",
    f"ALTER TABLE app.messages ADD CONSTRAINT messages_kind_check CHECK (kind IN ({KINDS}))",
    "ALTER TABLE app.messages ALTER COLUMN author DROP NOT NULL",
    (
        "ALTER TABLE app.messages ADD CONSTRAINT messages_author_check"
        f" CHECK ((kind IN ({SYSTEM_KINDS})) = (author IS NULL))"
    ),
)

DOWNGRADE = (
    # 0005 has no row without an author; deleting system messages silently would lose conversation history, so a
    # database that holds any refuses the downgrade with a message instead (ruling 8).
    (
        "DO $do$ BEGIN"
        " IF EXISTS (SELECT 1 FROM app.messages WHERE author IS NULL) THEN"
        " RAISE EXCEPTION 'system messages exist; delete them before downgrading revision 0006';"
        " END IF;"
        " END $do$"
    ),
    "ALTER TABLE app.messages DROP CONSTRAINT messages_author_check",
    "ALTER TABLE app.messages ALTER COLUMN author SET NOT NULL",
    "ALTER TABLE app.messages DROP CONSTRAINT messages_kind_check",
    "ALTER TABLE app.messages DROP CONSTRAINT messages_conversation_seq_key",
    "ALTER TABLE app.messages DROP COLUMN seq",
    f"REVOKE ALL ON app.idempotency_request FROM {', '.join(MAIN_GRANTEES_0006)}",
    "DROP TABLE app.idempotency_request",
)


def upgrade() -> None:
    """The table and the message changes first, then the frozen grants (REVOKE ALL lands on the new table)."""
    for statement in SCHEMA_CHANGES:
        op.execute(statement)
    for statement in privileges.grant_statements(TABLES, GRANTS_0006, revokees=MAIN_GRANTEES_0006):
        op.execute(statement)


def downgrade() -> None:
    """Back to 0005's messages and no record table; refused while a system message exists."""
    for statement in DOWNGRADE:
        op.execute(statement)

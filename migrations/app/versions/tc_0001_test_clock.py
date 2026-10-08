"""The test clock (AM-20.6, R126): exists only where this branch is applied, which `scripts/skeleton.py migrate`
does for the test profile alone (`heads`); dev and demo stop at `app@head` and refuse to start if the table exists.

Revision ID: tc_0001_test_clock
Revises: (own root; depends on 0002_roles_grants_rls)
Branch label: testclock

A single-row table (the `one` column admits exactly one row) so `test_harness` can UPDATE without a WHERE clause and
needs no SELECT grant (AM-20.2 gives it ins, upd, del only; spike §3). app.current_time() reads it as app_definer.
"""

from alembic import op
from ops_core import privileges

revision = "tc_0001_test_clock"
down_revision = None
branch_labels = ("testclock",)
depends_on = "0002_roles_grants_rls"

GRANTS_TC = {
    "test_clock": {
        privileges.DEFINER_ROLE: privileges.Grant(sel=True),
        "test_harness": privileges.Grant(ins=True, upd=True, dele=True),
    }
}

DDL = (
    (
        "CREATE TABLE app.test_clock ("
        " one boolean NOT NULL DEFAULT true PRIMARY KEY CHECK (one),"
        " clock_offset interval NOT NULL DEFAULT interval '0')"
    ),
    "ALTER TABLE app.test_clock OWNER TO migrator",
    "INSERT INTO app.test_clock (clock_offset) VALUES (interval '0')",
)


def upgrade() -> None:
    """Create the one-row test clock and grant test_harness its cells and EXECUTE on current_time()."""
    for statement in DDL:
        op.execute(statement)
    # The test-only role gets its schema access and its clock EXECUTE here, never on the main line (SA:403).
    for statement in privileges.schema_usage_statements(privileges.TEST_ONLY_ROLES):
        op.execute(statement)
    for statement in privileges.function_grant_statements("current_time", args="", callers=("test_harness",)):
        op.execute(statement)
    for statement in privileges.grant_statements(["test_clock"], GRANTS_TC):
        op.execute(statement)


def downgrade() -> None:
    """Drop the test clock and take back what the branch granted test_harness."""
    op.execute("DROP TABLE app.test_clock")
    op.execute(f"REVOKE ALL ON FUNCTION app.current_time() FROM {', '.join(privileges.TEST_ONLY_ROLES)}")
    op.execute(f"REVOKE USAGE ON SCHEMA app FROM {', '.join(privileges.TEST_ONLY_ROLES)}")

"""Schema `checkpoints` and LangGraph's checkpoint tables (T20; AM-12 SA:209-218, AM-20.7 SA:559-562; R122).

Revision ID: 0015_checkpoints
Revises: 0014_run_manifests

The worker's graph persists through langgraph-checkpoint-postgres 3.1.2's `AsyncPostgresSaver`. Its SQL names its
tables without a schema (it has no schema parameter, SA:559), so the tables live in a schema of their own and the
worker's saver connection sets `search_path=checkpoints,pg_temp` (`ops_worker.graph.build.open_saver`).

SA:559 has the migrator run `PostgresSaver.setup()`. This revision runs the same statements inside the migration
instead (erratum 126): `BasePostgresSaver.MIGRATIONS` (`langgraph/checkpoint/postgres/base.py:43-91` in 3.1.2),
frozen below with each table named in schema `checkpoints` and `CONCURRENTLY` dropped from the three index statements,
because Alembic runs every revision in one transaction and `CREATE INDEX CONCURRENTLY` cannot run inside one (the
tables are empty, so the plain index build waits on nobody). It then records the ten statement numbers in
`checkpoint_migrations`, as `setup()` does, so a later `setup()` finds nothing to apply.
`tests/plan_q/test_migration_0015.py` compares the frozen list with the installed package's.

Cells (SA:434, R122): `worker` USAGE on the schema and SELECT, INSERT, UPDATE and DELETE on the three tables the saver
reads and writes; nobody else anything, so the api is refused at the schema. `checkpoint_migrations` is written here
and read by nobody at runtime. No RLS: checkpoint rows are not tenant rows (SA:510 does not list them), and only the
worker reads them, by thread id (erratum 123). Owner `migrator`, as every app table.

The downgrade drops the schema with its tables and rows.
"""

from alembic import op
from ops_core import privileges

revision = "0015_checkpoints"
down_revision = "0014_run_manifests"
branch_labels = None
depends_on = None

_ALL = privileges.Grant(sel=True, ins=True, upd=True, dele=True)
CHECKPOINT_GRANTS_0015: dict[str, dict[str, privileges.Grant]] = {
    "checkpoints": {"worker": _ALL},
    "checkpoint_blobs": {"worker": _ALL},
    "checkpoint_writes": {"worker": _ALL},
}
CHECKPOINT_DDL_0015 = (
    "CREATE TABLE IF NOT EXISTS checkpoints.checkpoint_migrations ( v INTEGER PRIMARY KEY );",
    (
        "CREATE TABLE IF NOT EXISTS checkpoints.checkpoints ( thread_id TEXT NOT NULL, checkpoint_ns TEXT NOT NULL"
        " DEFAULT '', checkpoint_id TEXT NOT NULL, parent_checkpoint_id TEXT, type TEXT, checkpoint JSONB NOT NULL,"
        " metadata JSONB NOT NULL DEFAULT '{}', PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id) );"
    ),
    (
        "CREATE TABLE IF NOT EXISTS checkpoints.checkpoint_blobs ( thread_id TEXT NOT NULL, checkpoint_ns TEXT NOT"
        " NULL DEFAULT '', channel TEXT NOT NULL, version TEXT NOT NULL, type TEXT NOT NULL, blob BYTEA, PRIMARY KEY"
        " (thread_id, checkpoint_ns, channel, version) );"
    ),
    (
        "CREATE TABLE IF NOT EXISTS checkpoints.checkpoint_writes ( thread_id TEXT NOT NULL, checkpoint_ns TEXT NOT"
        " NULL DEFAULT '', checkpoint_id TEXT NOT NULL, task_id TEXT NOT NULL, idx INTEGER NOT NULL, channel TEXT"
        " NOT NULL, type TEXT, blob BYTEA NOT NULL, PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id,"
        " idx) );"
    ),
    "ALTER TABLE checkpoints.checkpoint_blobs ALTER COLUMN blob DROP not null;",
    "SELECT 1;",
    "CREATE INDEX IF NOT EXISTS checkpoints_thread_id_idx ON checkpoints.checkpoints(thread_id);",
    "CREATE INDEX IF NOT EXISTS checkpoint_blobs_thread_id_idx ON checkpoints.checkpoint_blobs(thread_id);",
    "CREATE INDEX IF NOT EXISTS checkpoint_writes_thread_id_idx ON checkpoints.checkpoint_writes(thread_id);",
    "ALTER TABLE checkpoints.checkpoint_writes ADD COLUMN IF NOT EXISTS task_path TEXT NOT NULL DEFAULT '';",
)
TABLES_0015 = ("checkpoint_migrations", "checkpoints", "checkpoint_blobs", "checkpoint_writes")


def statements() -> list[str]:
    """Every statement of the upgrade, in order (the unit test reads the same list)."""
    out = ["CREATE SCHEMA checkpoints AUTHORIZATION migrator", "REVOKE ALL ON SCHEMA checkpoints FROM PUBLIC"]
    out.extend(CHECKPOINT_DDL_0015)
    numbers = ", ".join(f"({v})" for v in range(len(CHECKPOINT_DDL_0015)))
    out.append(f"INSERT INTO checkpoints.checkpoint_migrations (v) VALUES {numbers}")
    out.extend(f"ALTER TABLE checkpoints.{table} OWNER TO migrator" for table in TABLES_0015)
    # No REVOKE ALL per table, unlike 0011-0014: the schema is new, PUBLIC is revoked at the schema above and no
    # default privileges exist to revoke; `privileges.grant_statements` is fixed to schema `app`.
    out.append("GRANT USAGE ON SCHEMA checkpoints TO worker")
    for table, cells in CHECKPOINT_GRANTS_0015.items():
        for role, grant in cells.items():
            names = [n for n, flag in (("SELECT", grant.sel), ("INSERT", grant.ins), ("DELETE", grant.dele)) if flag]
            if grant.upd is True:
                names.append("UPDATE")
            out.append(f"GRANT {', '.join(names)} ON checkpoints.{table} TO {role}")
    return out


def upgrade() -> None:
    """The schema, the saver's tables and their recorded version, the owner, then the worker's cells."""
    for statement in statements():
        op.execute(statement)


def downgrade() -> None:
    """Back to 0014."""
    op.execute("DROP SCHEMA checkpoints CASCADE")

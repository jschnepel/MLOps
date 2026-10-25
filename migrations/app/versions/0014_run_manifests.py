"""The run manifest (T19; AM-80's six fields, SA:770; R130): `app.run_manifests`.

Revision ID: 0014_run_manifests
Revises: 0013_embeddings

One immutable row per run, written by the worker in the unit that moves the run RETRIEVING → DRAFTING, before the model
is called, so a run whose draft fails still says which route produced (or failed to produce) it. The columns are
`schemas/run-manifest.schema.json`'s, with its rules as CHECKs: the two routes, a bare 64-hex digest that every real
route carries and the fake never needs, the two retrieval modes and the length bounds. The run is the primary key, and
the foreign key on (tenant_id, run_id) ties the row to its run's tenant, as `drafts` does (revision 0002).

Cells (AM-20.2 has no row for it; this revision adds one): `worker` inserts and reads, `api` reads (the run's
explanation view and T25's reports), nobody updates or deletes, so a written manifest cannot change. ENABLE + FORCE RLS
with the `tenant_isolation` policy (AM-20.5). The insert's foreign-key check takes FOR KEY SHARE on the run row, which
the same unit already holds FOR UPDATE through `transition_run`, so the lock order does not move (core/locking.py).

The downgrade drops the table with its rows, grants and policy.
"""

from alembic import op
from ops_core import privileges

revision = "0014_run_manifests"
down_revision = "0013_embeddings"
branch_labels = None
depends_on = None

TABLES_0014 = ("run_manifests",)
MAIN_GRANTEES_0014 = ("api", "worker", "sweeper", "mcp_read", "mcp_exec", "operator", "app_definer")
POLICY_ROLES_0014 = ("api", "worker", "sweeper", "app_definer")
GRANTS_0014: dict[str, dict[str, privileges.Grant]] = {
    "run_manifests": {"worker": privileges.Grant(sel=True, ins=True), "api": privileges.Grant(sel=True)},
}

SCHEMA_CHANGES = (
    (
        "CREATE TABLE app.run_manifests ("
        " run_id uuid PRIMARY KEY,"
        " tenant_id uuid NOT NULL,"
        " model_route text NOT NULL CHECK (model_route IN ('fake', 'qwen3:8b')),"
        " model_digest text CHECK (model_digest ~ '^[a-f0-9]{64}$'),"
        " prompt_version text NOT NULL CHECK (char_length(prompt_version) BETWEEN 1 AND 60),"
        " corpus_version text NOT NULL CHECK (char_length(corpus_version) BETWEEN 1 AND 100),"
        " retrieval_mode text NOT NULL CHECK (retrieval_mode IN ('lexical', 'vector_exact')),"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        # schemas/run-manifest.schema.json: a non-fake route carries a digest (the fake may, but never does).
        " CHECK (model_route = 'fake' OR model_digest IS NOT NULL),"
        " CONSTRAINT run_manifests_tenant_run_fkey FOREIGN KEY (tenant_id, run_id)"
        " REFERENCES app.runs (tenant_id, run_id))"
    ),
    "ALTER TABLE app.run_manifests OWNER TO migrator",
)
DOWNGRADE = ("DROP TABLE app.run_manifests",)  # its rows, grants and policy go with it


def upgrade() -> None:
    """The table, then its frozen cells and its policy."""
    for statement in SCHEMA_CHANGES:
        op.execute(statement)
    for statement in privileges.grant_statements(TABLES_0014, GRANTS_0014, revokees=MAIN_GRANTEES_0014):
        op.execute(statement)
    for statement in privileges.rls_statements(TABLES_0014, POLICY_ROLES_0014):
        op.execute(statement)


def downgrade() -> None:
    """Back to 0013."""
    for statement in DOWNGRADE:
        op.execute(statement)

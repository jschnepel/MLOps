"""The run lease's schema half (T13, Plan H rulings 1, 12, 13, 27): the model permit, the definer's fence cell, the
job-type vocabulary and the global queue count; Task 4 of the plan adds the fenced definer functions to this revision.

Revision ID: 0007_leases_fences
Revises: 0006_admission_idempotency

`model_permit` holds one row per unit of global model concurrency (BS:549: one, seeded here, SA:440); the worker
takes a free slot with SKIP LOCKED and an expiry on the application clock, so no role needs to reclaim it and only the
worker holds any cell on it (erratum 50; SA:523: no RLS). `app_definer` gains UPDATE on `run_lease.fence`: a row lock
needs UPDATE on a column (Plan E ruling 23), the fenced definers lock the lease row, and `mark_unknown` bumps the fence
(erratum 45). `jobs.type` gets the AM-20.4 vocabulary as a CHECK (ruling 27). `queued_runs_total()` is the global
bound's count for `api`, which sees one tenant under RLS (ruling 13). Every cell, caller and body is frozen here; the
downgrade restores revision 0006 exactly (R006).
"""

from alembic import op
from ops_core import privileges

revision = "0007_leases_fences"
down_revision = "0006_admission_idempotency"
branch_labels = None
depends_on = None

HEADER = "LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp SET app.tenant_id = ''"
TABLES = ("run_lease", "model_permit")
MAIN_GRANTEES_0007 = ("api", "worker", "sweeper", "mcp_read", "mcp_exec", "operator", "app_definer")
GRANTS_0007: dict[str, dict[str, privileges.Grant]] = {
    "run_lease": {
        "worker": privileges.Grant(sel=True, ins=True, upd=True),
        "sweeper": privileges.Grant(sel=True, upd=("lease_until",)),
        "app_definer": privileges.Grant(sel=True, upd=("fence",)),
    },
    "model_permit": {"worker": privileges.Grant(sel=True, upd=True)},
}
# What 0002 granted on run_lease, for the downgrade (not named GRANTS_*: the newest-revision test folds every
# GRANTS_* attribute into the live matrix check).
RUN_LEASE_CELLS_0002: dict[str, dict[str, privileges.Grant]] = {
    "run_lease": {
        "worker": privileges.Grant(sel=True, ins=True, upd=True),
        "sweeper": privileges.Grant(sel=True, upd=("lease_until",)),
        "app_definer": privileges.Grant(sel=True),
    }
}
# The AM-20.4 job types, frozen here; a unit test compares them with ops_core.jobs.JobType.
JOB_TYPES_0007 = (
    "investigate",
    "resume_input",
    "execute",
    "recover",
    "expire_proposals",
    "sync_memberships",
    "sweep_wakeups",
    "deliver_outbox",
)
JOB_TYPES = ", ".join(f"'{job_type}'" for job_type in JOB_TYPES_0007)

SCHEMA_CHANGES = (
    (
        "CREATE TABLE app.model_permit ("
        " slot smallint PRIMARY KEY CHECK (slot >= 1),"
        " holder text,"
        " run_id uuid,"
        " leased_until timestamptz NOT NULL DEFAULT '-infinity')"
    ),
    "ALTER TABLE app.model_permit OWNER TO migrator",
    "INSERT INTO app.model_permit (slot) VALUES (1)",
    f"ALTER TABLE app.jobs ADD CONSTRAINT jobs_type_check CHECK (type IN ({JOB_TYPES}))",
)

QUEUED_RUNS_TOTAL = f"""
CREATE OR REPLACE FUNCTION app.queued_runs_total() RETURNS bigint
{HEADER} AS $fn$
DECLARE
    v_tenant uuid;
    v_count bigint;
    v_total bigint := 0;
BEGIN
    PERFORM app._authority('queued_runs_total', ARRAY['api']);
    -- BS:550's "100 total": runs is under RLS and api sees one tenant at a time (Plan G spike section 8), so the
    -- function walks the RLS-free tenants table and counts each tenant's QUEUED runs under that tenant's setting,
    -- the resolve_identity pattern (SA:520). One number leaves it: no id, no tenant, no state.
    FOR v_tenant IN SELECT t.tenant_id FROM tenants t ORDER BY t.tenant_id LOOP
        PERFORM set_config('app.tenant_id', v_tenant::text, true);
        SELECT count(*) INTO v_count FROM runs r WHERE r.state = 'QUEUED';
        v_total := v_total + v_count;
    END LOOP;
    RETURN v_total;
END
$fn$;
ALTER FUNCTION app.queued_runs_total() OWNER TO app_definer;
"""

# (name, argument types, callers, body): frozen here (N1); the newest-revision test reads this tuple.
FUNCTIONS: tuple[tuple[str, str, tuple[str, ...], str], ...] = (("queued_runs_total", "", ("api",), QUEUED_RUNS_TOTAL),)
# Signatures upgrade() drops before FUNCTIONS re-creates them with another signature or return type.
REPLACED: tuple[str, ...] = ()
# Signatures downgrade() drops: the functions 0006 does not have in the form FUNCTIONS created.
CREATED: tuple[str, ...] = ("queued_runs_total()",)
# What downgrade() re-creates afterwards, from the applied revisions' own bodies: (name, args, callers, body).
RESTORED: tuple[tuple[str, str, tuple[str, ...], str], ...] = ()
DOWNGRADE = (
    "ALTER TABLE app.jobs DROP CONSTRAINT jobs_type_check",
    f"REVOKE ALL ON app.model_permit FROM {', '.join(MAIN_GRANTEES_0007)}",
    "DROP TABLE app.model_permit",
)


def upgrade() -> None:
    """Schema, then the frozen cells, then the functions (body first, then its grants, so REVOKE lands on it)."""
    for statement in SCHEMA_CHANGES:
        op.execute(statement)
    for statement in privileges.grant_statements(TABLES, GRANTS_0007, revokees=MAIN_GRANTEES_0007):
        op.execute(statement)
    for signature in REPLACED:
        op.execute(f"DROP FUNCTION app.{signature}")
    for name, args, callers, body in FUNCTIONS:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)


def downgrade() -> None:
    """Back to 0006: drop what 0007 created, re-create what it replaced, drop the permit and the CHECK, and put back
    0002's run_lease cells."""
    for signature in CREATED:
        op.execute(f"DROP FUNCTION app.{signature}")
    for name, args, callers, body in RESTORED:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)
    for statement in DOWNGRADE:
        op.execute(statement)
    for statement in privileges.grant_statements(("run_lease",), RUN_LEASE_CELLS_0002, revokees=MAIN_GRANTEES_0007):
        op.execute(statement)

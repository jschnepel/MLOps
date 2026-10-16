"""The invocation handle's job binding (T15, Plan J ruling 6).

Revision ID: 0009_handle_binding
Revises: 0008_journal_outbox

`_resolve_handle` read the handle's job by id alone, so a handle whose `job_id` named another run's job (a row a
compromised worker or a superuser wrote; `invocation_context` has no RLS, SA:523), or a job already finished, still
resolved for the handle's own run. The job must now be the handle's run's own and still open (`done_at IS NULL`);
otherwise its type reads as NULL and the existing server check refuses it with every other refusal (one error, one
message, SA:357). Only that read changes: the body is revision 0007's with one statement replaced, which a unit test
checks, so the lease lock, the fence and expiry comparisons and the server binding stay as 0007 proved them. The run
state and tool allowlist stay in Python (`persistence.allowed_tool`, erratum 19). The downgrade restores 0008 exactly
(R006) by re-running 0007's own body, loaded from its file (the 0007 pattern).
"""

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic import op
from ops_core import privileges

revision = "0009_handle_binding"
down_revision = "0008_journal_outbox"
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


REV0007 = _applied("0007_leases_fences")
# 0007's read of the handle's job, and the bound read that replaces it. With no row (another run's job, a finished
# job, an unknown id) `SELECT INTO` leaves v_job_type NULL, and a NULL type is refused by the server check below it.
JOB_READ_0007 = "    SELECT j.type INTO v_job_type FROM jobs j WHERE j.id = v_ctx.job_id;\n"
JOB_READ_0009 = (
    "    -- T15 (Plan J ruling 6): the handle's job must be its own run's and still open; a job of another run or a\n"
    "    -- finished one yields no type, which the server check refuses with every other refusal.\n"
    "    SELECT j.type INTO v_job_type FROM jobs j\n"
    "    WHERE j.id = v_ctx.job_id AND j.run_id = v_ctx.run_id AND j.done_at IS NULL;\n"
)
RESOLVE_HANDLE = REV0007.RESOLVE_HANDLE.replace(JOB_READ_0007, JOB_READ_0009)

# (name, argument types, callers, body): frozen here (N1); the newest-revision test reads this tuple.
FUNCTIONS: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("_resolve_handle", "text, text, text", (), RESOLVE_HANDLE),
)
# What downgrade() re-creates, from the applied revision's own body: (name, args, callers, body).
RESTORED: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("_resolve_handle", "text, text, text", (), REV0007.RESOLVE_HANDLE),
)


def upgrade() -> None:
    """The bound body, then its REVOKE (a helper is granted to nobody, SA:474).

    Raises:
        RuntimeError: revision 0007's body no longer carries the read this revision replaces.
    """
    if REV0007.RESOLVE_HANDLE.count(JOB_READ_0007) != 1:
        raise RuntimeError("revision 0007's _resolve_handle no longer carries the job read this revision binds")
    for name, args, callers, body in FUNCTIONS:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)


def downgrade() -> None:
    """Back to 0008: 0007's body, then its REVOKE; no row is touched."""
    for name, args, callers, body in RESTORED:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)

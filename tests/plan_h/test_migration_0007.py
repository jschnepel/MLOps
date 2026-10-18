"""Revision 0007 without a database (Plan H rulings 1, 12, 13, 27, 30, 31): the frozen cells equal the live matrix,
the statements create what the lease code relies on, the downgrade puts 0006's cells back, and the testclock branch
no longer renders anything from the live matrix.

Catches: a definer cell wider than `upd(fence)` on run_lease (a definer that could rewrite a lease's owner or
expiry), a permit any role but the worker may touch (erratum 50), a permit table with RLS (SA:523), a job type the
CHECK forgets (a real job refused at insert), a downgrade that keeps the definer's fence cell, and a testclock
revision that would change when a role is added to the matrix (round-3 finding N1 of Plan E).
"""

import importlib.util
from pathlib import Path
from typing import Any

import alembic.op
import pytest
from ops_core import privileges as p
from ops_core.jobs import JobType

VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "app" / "versions"
LEASE_REVOKE = "REVOKE ALL ON app.run_lease FROM api, worker, sweeper, mcp_read, mcp_exec, operator, app_definer"


def revision(name: str = "0007_leases_fences") -> Any:
    """Load a revision by path (the versions directory is not a package)."""
    spec = importlib.util.spec_from_file_location(f"rev_{name}", VERSIONS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def statements(module: Any, fn: str, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """What upgrade() or downgrade() hands to op.execute, in order."""
    seen: list[str] = []
    monkeypatch.setattr(alembic.op, "execute", lambda statement, *a, **k: seen.append(str(statement)))
    getattr(module, fn)()
    return seen


def test_the_frozen_cells_are_the_live_matrix() -> None:
    module = revision()
    assert module.down_revision == "0006_admission_idempotency"
    assert module.GRANTS_0007 == {table: p.GRANTS[table] for table in module.TABLES}
    assert p.GRANTS["run_lease"][p.DEFINER_ROLE] == p.Grant(sel=True, upd=("fence",))  # erratum 45
    assert p.GRANTS["model_permit"] == {"worker": p.Grant(sel=True, upd=True)}  # erratum 50: nobody else
    assert "model_permit" in p.NO_RLS and "model_permit" not in p.RLS_TABLES  # SA:523
    assert set(module.MAIN_GRANTEES_0007) == set(p.MAIN_GRANTEES)
    assert p.DEFINER_FUNCTIONS["queued_runs_total"] == ("", ("api",))  # ruling 13: the API's count only


def test_upgrade_creates_the_permit_the_check_and_the_count(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = statements(revision(), "upgrade", monkeypatch)
    table = next(s for s in seen if s.startswith("CREATE TABLE app.model_permit"))
    for column in (
        "slot smallint PRIMARY KEY CHECK (slot >= 1)",
        "holder text",
        "run_id uuid",
        "leased_until timestamptz NOT NULL DEFAULT '-infinity'",
    ):
        assert column in table, column
    assert "INSERT INTO app.model_permit (slot) VALUES (1)" in seen  # SA:440: seeded by the migration, BS:549: one
    check = next(s for s in seen if "jobs_type_check" in s)
    assert all(f"'{job_type.value}'" in check for job_type in JobType)
    grants = [s for s in seen if s.startswith(("GRANT", "REVOKE")) and "FUNCTION" not in s]
    assert grants == [
        LEASE_REVOKE,
        "GRANT INSERT, SELECT, UPDATE ON app.run_lease TO worker",
        "GRANT SELECT ON app.run_lease TO sweeper",
        "GRANT UPDATE (lease_until) ON app.run_lease TO sweeper",
        "GRANT SELECT ON app.run_lease TO app_definer",
        "GRANT UPDATE (fence) ON app.run_lease TO app_definer",
        "REVOKE ALL ON app.model_permit FROM api, worker, sweeper, mcp_read, mcp_exec, operator, app_definer",
        "GRANT SELECT, UPDATE ON app.model_permit TO worker",
    ]
    body = next(s for s in seen if s.lstrip().startswith("CREATE OR REPLACE FUNCTION app.queued_runs_total()"))
    assert "_authority('queued_runs_total', ARRAY['api'])" in body and "set_config('app.tenant_id'" in body


def test_the_job_types_frozen_here_are_the_live_enum() -> None:
    frozen = revision().JOB_TYPES_0007
    assert len(frozen) == len(set(frozen)) and set(frozen) == {job_type.value for job_type in JobType}


def test_the_downgrade_drops_what_0007_added_and_restores_the_0002_lease_cells(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = statements(revision(), "downgrade", monkeypatch)
    assert seen[0] == "DROP FUNCTION app.queued_runs_total()"
    assert "ALTER TABLE app.jobs DROP CONSTRAINT jobs_type_check" in seen and "DROP TABLE app.model_permit" in seen
    assert seen[-5:] == [
        LEASE_REVOKE,
        "GRANT INSERT, SELECT, UPDATE ON app.run_lease TO worker",
        "GRANT SELECT ON app.run_lease TO sweeper",
        "GRANT UPDATE (lease_until) ON app.run_lease TO sweeper",
        "GRANT SELECT ON app.run_lease TO app_definer",
    ]
    assert not any(s.startswith("DELETE") for s in seen)  # it deletes no row


def test_the_testclock_branch_renders_from_frozen_tuples(monkeypatch: pytest.MonkeyPatch) -> None:
    branch = revision("tc_0001_test_clock")
    assert branch.TEST_ONLY_ROLES_TC == p.TEST_ONLY_ROLES and branch.GRANTEES_TC == p.GRANTEES
    source = (VERSIONS / "tc_0001_test_clock.py").read_text(encoding="utf-8")
    assert "privileges.TEST_ONLY_ROLES" not in source and "privileges.GRANTEES" not in source
    seen = statements(branch, "upgrade", monkeypatch)
    # The frozen tuples render exactly what the live matrix rendered when the branch was applied (Plan E, 0002).
    assert seen[-3:] == p.grant_statements(["test_clock"], branch.GRANTS_TC)
    assert "GRANT USAGE ON SCHEMA app TO test_harness" in seen


def test_upgrade_replaces_the_handle_functions_with_fenced_ones(monkeypatch: pytest.MonkeyPatch) -> None:
    module = revision()
    seen = statements(module, "upgrade", monkeypatch)
    for old, new in (
        ("mark_sent(uuid)", "app.mark_sent(p_raw_handle text, p_action_id uuid)"),
        ("record_outcome(uuid, text, jsonb)", "app.record_outcome(p_raw_handle text, p_action_id uuid"),
        ("mark_unknown(uuid, bigint)", "app.mark_unknown(p_run_id uuid, p_fence bigint)"),
    ):
        dropped = seen.index(f"DROP FUNCTION app.{old}")
        created = next(i for i, s in enumerate(seen) if new in s)
        assert dropped < created, old  # another signature or return type: dropped, then created
    resolve = module.RESOLVE_HANDLE
    lock = resolve.index("FROM run_lease l WHERE l.run_id = v_ctx.run_id FOR SHARE")
    assert lock < resolve.index("v_lease.fence <> v_ctx.fence") < resolve.index("_tenant_of_run")
    assert lock < resolve.index("v_ctx.expires_at <= app.current_time()")  # SA:157: compared after the lock
    for body in (module.MARK_SENT, module.RECORD_OUTCOME):
        assert body.index("app._resolve_handle(p_raw_handle") < body.index("FOR UPDATE")  # run_lease before runs
        assert "g.run_id = v_handle.run_id" in body  # the action must be the handle's run's
    assert module.GRANT_EXECUTION != module.REV0005.GRANT_EXECUTION
    assert module.GRANT_TODO_0005 in module.REV0005.GRANT_EXECUTION
    assert module.GRANT_TODO_0005 not in module.GRANT_EXECUTION  # the reworded line is gone


def test_mark_unknown_bumps_under_the_lock_and_locks_the_run_before_the_handles() -> None:
    module = revision()
    body = module.MARK_UNKNOWN
    assert "RETURNS TABLE (run_state text, new_fence bigint)" in body
    order = [
        "FROM run_lease l WHERE l.run_id = p_run_id FOR UPDATE",
        "v_lease.fence <> p_fence OR v_lease.lease_until <= app.current_time()",
        "SET fence = p_fence + 1",
        "FROM runs r WHERE r.run_id = p_run_id FOR UPDATE",
        "UPDATE invocation_context ic SET revoked_at",
    ]
    assert [body.index(part) for part in order] == sorted(body.index(part) for part in order)  # SA:188, SA:191
    revoke = module.REVOKE_HANDLES
    assert revoke.index("FOR SHARE") < revoke.index("ic.fence <= p_fence")  # ruling 8: never refuses
    assert "RAISE" not in revoke.split("BEGIN", 1)[1].replace("app._authority", "")


def test_the_downgrade_restores_the_applied_bodies_exactly(monkeypatch: pytest.MonkeyPatch) -> None:
    module = revision()
    seen = statements(module, "downgrade", monkeypatch)
    drops = [
        "DROP FUNCTION app.queued_runs_total()",
        "DROP FUNCTION app.mark_sent(text, uuid)",
        "DROP FUNCTION app.record_outcome(text, uuid, text, jsonb)",
        "DROP FUNCTION app.mark_unknown(uuid, bigint)",
    ]
    assert seen[: len(drops)] == drops
    for body in (
        module.REV0004.RESOLVE_HANDLE,
        module.REV0005.GRANT_EXECUTION,
        module.REV0004.MARK_SENT,
        module.REV0004.RECORD_OUTCOME,
        module.REV0004.MARK_UNKNOWN,
        module.REV0003.REVOKE_HANDLES,
    ):
        assert body in seen  # the applied revision's own text, byte for byte

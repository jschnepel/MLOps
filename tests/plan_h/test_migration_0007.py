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

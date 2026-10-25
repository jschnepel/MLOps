"""Revision 0014 without a database (T19; AM-80 SA:770; R130).

Catches: a manifest table granted to a role other than the worker (INSERT, SELECT) and the api (SELECT), or with an
UPDATE or DELETE anywhere (a written manifest must not change); without FORCE and the tenant policy; without its run;
CHECKs that drift from `schemas/run-manifest.schema.json` and `RunManifest` (the routes, the modes, the digest rule,
the bounds); a table outside the lock-order registry; and a downgrade that leaves it behind.
"""

import json
from pathlib import Path
from typing import Any, get_args

import pytest
from ops_core import locking, privileges
from ops_core.routing import ModelRoute, RunManifest

from tests.plan_l.test_migration_0011 import revision, statements

ROOT = Path(__file__).resolve().parents[2]
CELLS = {"worker": privileges.Grant(sel=True, ins=True), "api": privileges.Grant(sel=True)}


def rev0014() -> Any:
    return revision("0014_run_manifests")


def test_upgrade_creates_the_table_then_its_cells_and_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    module = rev0014()
    assert module.down_revision == "0013_embeddings"
    assert statements(module, "upgrade", monkeypatch) == [
        *module.SCHEMA_CHANGES,
        "REVOKE ALL ON app.run_manifests FROM api, worker, sweeper, mcp_read, mcp_exec, operator, app_definer",
        "GRANT INSERT, SELECT ON app.run_manifests TO worker",
        "GRANT SELECT ON app.run_manifests TO api",
        *privileges.rls_statements(("run_manifests",), ("api", "worker", "sweeper", "app_definer")),
    ]
    assert statements(module, "downgrade", monkeypatch) == ["DROP TABLE app.run_manifests"]


def test_the_cells_are_the_matrix_row_and_nobody_can_change_a_manifest() -> None:
    module = rev0014()
    assert module.GRANTS_0014 == {"run_manifests": CELLS} == {"run_manifests": privileges.GRANTS["run_manifests"]}
    assert all(not g.upd and not g.dele for g in CELLS.values())
    assert "run_manifests" in privileges.RLS_TABLES and "run_manifests" not in privileges.SWEEPER_ALL
    assert "run_manifests" in locking.NEVER_LOCKED


def test_the_checks_say_what_the_schema_and_the_contract_say() -> None:
    ddl = rev0014().SCHEMA_CHANGES[0]
    schema = json.loads((ROOT / "schemas" / "run-manifest.schema.json").read_text(encoding="utf-8"))
    routes = schema["properties"]["model_route"]["enum"]
    assert sorted(routes) == sorted(r.value for r in ModelRoute)
    assert f"model_route IN ({', '.join(repr(r) for r in routes)})" in ddl
    modes = get_args(RunManifest.model_fields["retrieval_mode"].annotation)
    assert list(modes) == schema["properties"]["retrieval_mode"]["enum"]
    assert f"retrieval_mode IN ({', '.join(repr(m) for m in modes)})" in ddl
    assert "CHECK (model_route = 'fake' OR model_digest IS NOT NULL)" in ddl  # the schema's allOf, the validator's rule
    assert "model_digest ~ '^[a-f0-9]{64}$'" in ddl
    assert "char_length(prompt_version) BETWEEN 1 AND 60" in ddl
    assert "char_length(corpus_version) BETWEEN 1 AND 100" in ddl
    assert "run_id uuid PRIMARY KEY" in ddl  # one manifest per run
    assert "FOREIGN KEY (tenant_id, run_id) REFERENCES app.runs (tenant_id, run_id)" in ddl

"""Revision 0015 without a database (T20; SA:434, SA:559-562; R122).

Catches: a frozen copy of the saver's DDL that drifts from the installed langgraph-checkpoint-postgres (the worker's
saver would then meet tables it does not expect); a `CREATE INDEX CONCURRENTLY` left in (it cannot run in Alembic's
transaction); a missing version record (a later `setup()` would re-run the DDL); a checkpoint table granted to any
role but the worker, or the worker without DML; and a downgrade that leaves the schema behind.
"""

import re
from typing import Any

import pytest
from langgraph.checkpoint.postgres.base import BasePostgresSaver
from ops_core import privileges

from tests.plan_l.test_migration_0011 import revision, statements


def rev0015() -> Any:
    return revision("0015_checkpoints")


def flat(statement: str) -> str:
    return " ".join(statement.split())


def test_the_frozen_ddl_is_the_installed_savers_with_the_schema_named() -> None:
    frozen = [flat(s.replace("checkpoints.", "")) for s in rev0015().CHECKPOINT_DDL_0015]
    library = [flat(s.replace("CONCURRENTLY ", "")) for s in BasePostgresSaver.MIGRATIONS]
    assert frozen == library  # statement for statement, in the library's order (its version numbers)
    assert not any("CONCURRENTLY" in s for s in rev0015().CHECKPOINT_DDL_0015)
    # Every table the DDL touches is named in schema `checkpoints`, never left to the migration's search_path.
    named = re.findall(r"(?:TABLE(?: IF NOT EXISTS)?|ON) (\S+?)[ (]", " ".join(rev0015().CHECKPOINT_DDL_0015))
    assert named and all(name.startswith("checkpoints.") for name in named), named


def test_upgrade_creates_the_schema_records_the_version_and_grants_the_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    module = rev0015()
    assert module.down_revision == "0014_run_manifests"
    ran = statements(module, "upgrade", monkeypatch)
    assert ran == module.statements()
    assert ran[:2] == [
        "CREATE SCHEMA checkpoints AUTHORIZATION migrator",
        "REVOKE ALL ON SCHEMA checkpoints FROM PUBLIC",
    ]
    assert "INSERT INTO checkpoints.checkpoint_migrations (v) VALUES " + ", ".join(f"({v})" for v in range(10)) in ran
    grants = [s for s in ran if s.startswith("GRANT")]
    assert grants == [
        "GRANT USAGE ON SCHEMA checkpoints TO worker",
        "GRANT SELECT, INSERT, DELETE, UPDATE ON checkpoints.checkpoints TO worker",
        "GRANT SELECT, INSERT, DELETE, UPDATE ON checkpoints.checkpoint_blobs TO worker",
        "GRANT SELECT, INSERT, DELETE, UPDATE ON checkpoints.checkpoint_writes TO worker",
    ]  # R122: nobody else; the api meets "permission denied for schema checkpoints"
    assert statements(module, "downgrade", monkeypatch) == ["DROP SCHEMA checkpoints CASCADE"]


def test_the_cells_are_the_matrix_and_only_the_worker_has_one() -> None:
    assert rev0015().CHECKPOINT_GRANTS_0015 == privileges.CHECKPOINT_GRANTS
    assert {role for cells in privileges.CHECKPOINT_GRANTS.values() for role in cells} == {"worker"}
    assert not set(privileges.CHECKPOINT_GRANTS) & set(privileges.GRANTS)  # outside the app schema's matrix

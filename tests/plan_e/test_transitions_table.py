"""Revision 0002's `app.transitions` rows are generated from ops_core.states.TRANSITIONS (ruling 10), so the SQL
mirror cannot drift from the T07 table; this pins the generator's output shape and its guard, and scans every
revision's op.execute strings for SQLAlchemy bind parameters."""

import importlib.util
import sys
from pathlib import Path

import pytest
from ops_core import privileges
from ops_core.states import TRANSITIONS

ROOT = Path(__file__).resolve().parents[2]


def load_revision():
    path = ROOT / "migrations" / "app" / "versions" / "0002_roles_grants_rls.py"
    spec = importlib.util.spec_from_file_location("rev0002", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["rev0002"] = module
    spec.loader.exec_module(module)
    return module


def test_one_insert_per_transition_row_with_sorted_reasons() -> None:
    rows = load_revision().transition_rows()
    assert len(rows) == len(TRANSITIONS)
    creation = [r for r in rows if "VALUES ('', 'QUEUED', 'create_run'" in r]
    assert len(creation) == 1 and creation[0].endswith("ARRAY[]::text[])")
    escalate = [r for r in rows if "'ESCALATED', 'escalate_run'" in r]
    assert escalate and all("ARRAY['conflict', 'escalation_deadline']::text[]" in r for r in escalate)
    assert all(" :" not in r for r in rows)  # never a SQLAlchemy bind


def test_revision_0002_lists_are_frozen_literals_within_the_matrix() -> None:
    """0002 names its tables itself (NI5): a later matrix row must not change an applied revision."""
    rev = load_revision()
    assert set(rev.TABLES) <= set(privileges.GRANTS) and set(rev.RLS) <= set(privileges.RLS_TABLES)
    assert "test_clock" not in rev.TABLES


def load_module(name: str):
    path = VERSIONS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"mod_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_newest_revision_of_every_cell_equals_the_live_matrix() -> None:
    """Round-3 finding N1: each revision freezes what it grants; the matrix is the truth for the *current* schema,
    so the last revision that touched a table or function must agree with it. A matrix edit without a new revision
    fails here; a new revision without a matrix edit fails here too."""
    cells: dict[str, dict[str, privileges.Grant]] = {}
    callers: dict[str, set[str]] = {}
    for name in REVISIONS:  # on-disk order is the Alembic order for this plan's revisions
        module = load_module(name)
        for attr in dir(module):
            if attr.startswith("GRANTS_"):
                cells.update(getattr(module, attr))
        for fn, _, fn_callers, _ in getattr(module, "FUNCTIONS", ()):
            callers.setdefault(fn, set()).update(fn_callers)
    for table, grants in cells.items():
        assert grants == privileges.GRANTS[table], table
    for fn, roles in callers.items():
        if fn in privileges.DEFINER_FUNCTIONS:
            assert roles == set(privileges.DEFINER_FUNCTIONS[fn][1]), fn
        else:
            assert roles == set() and fn in privileges.HELPER_FUNCTIONS, fn


VERSIONS = ROOT / "migrations" / "app" / "versions"
# The revisions that exist at this point of the plan; Tasks 3 and 4 add theirs and the cases appear (no skip, BS:597).
REVISIONS = tuple(
    n
    for n in ("0002_roles_grants_rls", "0003_run_path_functions", "0004_write_path_functions", "tc_0001_test_clock")
    if (VERSIONS / f"{n}.py").exists()
)


def executed_statements(name: str, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every string a revision's upgrade() and downgrade() hand to op.execute, captured without a database."""
    import alembic.op

    path = VERSIONS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"rev_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    seen: list[str] = []
    monkeypatch.setattr(alembic.op, "execute", lambda statement, *a, **k: seen.append(str(statement)))
    module.upgrade()
    module.downgrade()
    return seen


@pytest.mark.parametrize("name", REVISIONS)
def test_no_op_execute_string_carries_a_sqlalchemy_bind(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """':1' and ':timeout' inside a body were binds in round 1; text() must see none (fact sheet §4.3)."""
    from sqlalchemy import text

    for statement in executed_statements(name, monkeypatch):
        assert text(statement)._bindparams == {}, statement[:120]


def test_event_type_allowlist_lists_every_event_type_once() -> None:
    """0003's inlined allowlist is exactly EventType, each value once (Task 3 review finding 1)."""
    from ops_core.outcomes import EventType

    listed = load_module("0003_run_path_functions").EVENT_TYPES.split(", ")
    assert sorted(listed) == sorted(f"'{t.value}'" for t in EventType)

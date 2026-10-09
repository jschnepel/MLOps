"""Each revision freezes the `app.transitions` rows and the event-type allowlist it installs as literals (final review
I2), so an applied revision never changes; these tests check that the newest revision's literals equal the live
ops_core.states.TRANSITIONS and EventType (a Python edit without a new revision fails here), pin the row generator's
output shape and its guard, and scan every revision's op.execute strings for SQLAlchemy bind parameters."""

import importlib.util
import sys
from pathlib import Path

import pytest
from ops_core import privileges
from ops_core.outcomes import EventType
from ops_core.states import TRANSITIONS

ROOT = Path(__file__).resolve().parents[2]


def load_revision():
    """Import revision 0002 by path (the versions directory is not a package)."""
    path = ROOT / "migrations" / "app" / "versions" / "0002_roles_grants_rls.py"
    spec = importlib.util.spec_from_file_location("rev0002", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["rev0002"] = module
    spec.loader.exec_module(module)
    return module


def test_one_insert_per_transition_row_with_sorted_reasons() -> None:
    """The generator writes one INSERT per frozen row, '' for the creation edge and the reasons in sorted order."""
    rev = load_revision()
    rows = rev.transition_rows()
    assert len(rows) == len(rev.TRANSITION_ROWS_0002)
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
    # M2: the roles it grants to and revokes from are frozen too; while no later revision changes them they equal the
    # live main-line grantees.
    assert set(rev.MAIN_GRANTEES_0002) == set(privileges.MAIN_GRANTEES)


def load_module(name: str):
    """Import a revision of this plan by its file name."""
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
# This plan's revisions in Alembic order. Named, not filtered by existence: a renamed or deleted revision must fail
# loudly rather than drop its cases (final review M4).
REVISIONS = ("0002_roles_grants_rls", "0003_run_path_functions", "0004_write_path_functions", "tc_0001_test_clock")
assert all((VERSIONS / f"{n}.py").exists() for n in REVISIONS), REVISIONS


def newest_literal(prefix: str):
    """The last revision's attribute named `<prefix><rev>`: the frozen list the current schema carries."""
    found = None
    for name in REVISIONS:
        module = load_module(name)
        for attr in sorted(dir(module)):
            if attr.startswith(prefix):
                found = getattr(module, attr)
    assert found is not None, prefix
    return found


def test_the_newest_revision_of_the_transition_rows_equals_the_live_table() -> None:
    """An edit to ops_core.states.TRANSITIONS without a revision that ships it fails here (final review I2)."""
    live = {
        (
            r.src.value if r.src is not None else None,
            r.dst.value,
            r.performer.value,
            tuple(sorted(x.value for x in r.reasons)),
        )
        for r in TRANSITIONS
    }
    frozen = newest_literal("TRANSITION_ROWS_")
    assert len(frozen) == len(TRANSITIONS) and set(frozen) == live


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


def test_the_newest_revision_of_the_event_types_equals_the_live_enum() -> None:
    """The newest frozen allowlist is exactly EventType, each value once (Task 3 finding 1, final review I2)."""
    frozen = newest_literal("EVENT_TYPES_")
    assert len(frozen) == len(set(frozen)) and set(frozen) == {t.value for t in EventType}
    listed = load_module("0003_run_path_functions").EVENT_TYPES.split(", ")
    assert listed == [f"'{v}'" for v in load_module("0003_run_path_functions").EVENT_TYPES_0003]

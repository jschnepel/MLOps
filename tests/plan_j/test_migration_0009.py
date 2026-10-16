"""Revision 0009 without a database (Plan J rulings 6 and 18): `_resolve_handle` is 0007's body with the job read bound
to the handle's run and to an open job, it stays a helper granted to nobody, the downgrade puts 0007's body back, and
the MCP servers' startup check looks for text only this revision's body carries.

Catches: a revision that rewrites more of the body than the one read (the lease lock, the fence and expiry checks and
the server binding are 0007's, proved live by Plan H), a body that grants EXECUTE on a helper, a downgrade that keeps
the binding or touches a row, a startup marker that an older body also contains (either MCP server would start on 0008),
and a later revision that re-creates `_resolve_handle` without the marker (both would refuse a fully migrated
database).
"""

import importlib.util
from pathlib import Path
from typing import Any

import alembic.op
import pytest
from ops_core.persistence import HANDLE_BINDING

from tests.plan_e.test_transitions_table import REVISIONS

VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "app" / "versions"
REVOKE = "REVOKE ALL ON FUNCTION app._resolve_handle(text, text, text) FROM PUBLIC"


def revision(name: str = "0009_handle_binding") -> Any:
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


def test_only_the_job_read_changes() -> None:
    module, rev0007 = revision(), revision("0007_leases_fences")
    assert module.down_revision == "0008_journal_outbox"
    assert rev0007.RESOLVE_HANDLE.count(module.JOB_READ_0007) == 1
    assert module.RESOLVE_HANDLE != rev0007.RESOLVE_HANDLE
    assert module.RESOLVE_HANDLE.replace(module.JOB_READ_0009, module.JOB_READ_0007) == rev0007.RESOLVE_HANDLE
    assert "AND j.run_id = v_ctx.run_id AND j.done_at IS NULL;" in module.JOB_READ_0009


def test_upgrade_recreates_the_helper_granted_to_nobody(monkeypatch: pytest.MonkeyPatch) -> None:
    module = revision()
    assert statements(module, "upgrade", monkeypatch) == [module.RESOLVE_HANDLE, REVOKE]


def test_the_downgrade_restores_0007s_body(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = statements(revision(), "downgrade", monkeypatch)
    assert seen == [revision("0007_leases_fences").RESOLVE_HANDLE, REVOKE]  # byte for byte; no row is touched


def test_the_startup_marker_is_only_in_this_revisions_body() -> None:
    signature, marker = HANDLE_BINDING
    assert signature == "app._resolve_handle(text, text, text)"
    assert marker in revision().RESOLVE_HANDLE
    for older in ("0004_write_path_functions", "0007_leases_fences"):
        assert marker not in revision(older).RESOLVE_HANDLE, older


def test_the_newest_body_of_resolve_handle_carries_the_startup_marker() -> None:
    newest = None
    for name in REVISIONS:  # Alembic order; the newest revision that re-creates the helper wins
        for fn, _, _, body in getattr(revision(name), "FUNCTIONS", ()):
            if fn == "_resolve_handle":
                newest = (name, body)
    assert newest is not None and HANDLE_BINDING[1] in newest[1], newest and newest[0]

"""Revision 0006 without a database (Plan G rulings 4, 7 and 8): the record table's frozen cells equal the live
matrix, the statements create what the store relies on, and the downgrade refuses to lose a system message.

Catches: an UPDATE or DELETE cell for `api` (a record must be write-once), a sweeper DELETE without its SELECT
(erratum 25: the purge's WHERE reads the row), a `serial` where an identity column was ruled (spike §6: a serial needs
USAGE on its sequence, which `api` lacks), a nullable `author` without the CHECK that ties it to the system kinds, and
a downgrade that would set NOT NULL over rows it cannot keep.
"""

import importlib.util
from pathlib import Path
from typing import Any

import alembic.op
import pytest
from ops_core import privileges as p

VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "app" / "versions"


def revision() -> Any:
    """Load revision 0006 by path (the versions directory is not a package)."""
    path = VERSIONS / "0006_admission_idempotency.py"
    spec = importlib.util.spec_from_file_location("rev0006", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def statements(fn: str, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """What upgrade() or downgrade() hands to op.execute, in order."""
    module = revision()
    seen: list[str] = []
    monkeypatch.setattr(alembic.op, "execute", lambda statement, *a, **k: seen.append(str(statement)))
    getattr(module, fn)()
    return seen


def test_the_frozen_cells_are_the_live_matrix_and_the_table_has_no_rls() -> None:
    module = revision()
    assert module.down_revision == "0005_sessions_login_logout"
    assert module.GRANTS_0006 == {t: p.GRANTS[t] for t in module.TABLES}
    assert p.GRANTS["idempotency_request"] == {
        "api": p.Grant(sel=True, ins=True),
        "sweeper": p.Grant(sel=True, dele=True),
    }
    assert "idempotency_request" in p.NO_RLS and "idempotency_request" not in p.RLS_TABLES  # SA:523
    assert set(module.MAIN_GRANTEES_0006) == set(p.MAIN_GRANTEES)


def test_upgrade_creates_the_record_the_sequence_and_the_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = statements("upgrade", monkeypatch)
    table = next(s for s in seen if s.startswith("CREATE TABLE app.idempotency_request"))
    for column in (
        "tenant_id uuid NOT NULL",
        "subject uuid NOT NULL",
        "route text NOT NULL",
        "key text NOT NULL",
        "fingerprint_sha256 text NOT NULL",
        "status_code smallint NOT NULL",
        "response jsonb NOT NULL",
        "expires_at timestamptz NOT NULL",
        "PRIMARY KEY (tenant_id, subject, route, key)",
    ):
        assert column in table, column
    assert "ALTER TABLE app.messages ADD COLUMN seq bigint GENERATED ALWAYS AS IDENTITY NOT NULL" in seen
    assert "ALTER TABLE app.idempotency_request OWNER TO migrator" in seen
    author = next(s for s in seen if "messages_author_check" in s)
    assert "(kind IN ('status_answer', 'clarification_question')) = (author IS NULL)" in author
    grants = [s for s in seen if s.startswith(("GRANT", "REVOKE"))]
    assert grants == [
        "REVOKE ALL ON app.idempotency_request FROM api, worker, sweeper, mcp_read, mcp_exec, operator, app_definer",
        "GRANT INSERT, SELECT ON app.idempotency_request TO api",
        "GRANT SELECT, DELETE ON app.idempotency_request TO sweeper",
    ]


def test_the_downgrade_refuses_system_messages_before_restoring_not_null(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = statements("downgrade", monkeypatch)
    assert seen[0].startswith("DO $do$") and "author IS NULL" in seen[0] and "RAISE EXCEPTION" in seen[0]
    assert seen.index("ALTER TABLE app.messages DROP CONSTRAINT messages_author_check") < seen.index(
        "ALTER TABLE app.messages ALTER COLUMN author SET NOT NULL"
    )
    assert seen[-1] == "DROP TABLE app.idempotency_request"
    assert not any("DELETE" in s for s in seen)  # it deletes nothing (ruling 8)

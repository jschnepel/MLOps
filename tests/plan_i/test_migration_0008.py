"""Revision 0008 without a database (Plan I rulings 4, 12, 13, 20, 29): the frozen cells equal the live matrix, the
outbox is created with the shape and policy the delivery loop relies on, `_append_event` carries the payload rules and
the notification intent, and the downgrade puts revision 0007 back.

Catches: an outbox the api or worker may write directly (intent comes from `_append_event` only, erratum 60), an
outbox with the sweeper_all policy (the sweeper must iterate tenants, SA:520), a dedup key or ON CONFLICT target that
an INSERT-only definer cannot use, a payload rule that drifts from `ops_core.outcomes`, a notification type list that
names a type the enum lacks, and a downgrade that keeps the table, the DELETE cell or the new function body.
"""

import importlib.util
from pathlib import Path
from typing import Any

import alembic.op
import pytest
from ops_core import privileges as p
from ops_core.outcomes import DESTINATION_EVIDENCE, PAYLOAD_KEYS, EventType

VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "app" / "versions"
OUTBOX_REVOKE = "REVOKE ALL ON app.outbox FROM api, worker, sweeper, mcp_read, mcp_exec, operator, app_definer"
JOBS_REVOKE = "REVOKE ALL ON app.jobs FROM api, worker, sweeper, mcp_read, mcp_exec, operator, app_definer"


def revision(name: str = "0008_journal_outbox") -> Any:
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
    assert module.down_revision == "0007_leases_fences"
    assert module.GRANTS_0008 == {table: p.GRANTS[table] for table in module.TABLES}
    assert p.GRANTS["outbox"] == {
        "sweeper": p.Grant(sel=True, upd=("leased_until", "attempts", "delivered_at", "result")),
        p.DEFINER_ROLE: p.Grant(ins=True),  # erratum 60: no api or worker cell; intent comes from _append_event
    }
    assert p.GRANTS["jobs"]["sweeper"].dele  # erratum 61: the purge of finished maintenance rows
    assert "outbox" in p.RLS_TABLES and "outbox" not in p.SWEEPER_ALL  # SA:520: the sweeper iterates tenants
    assert set(module.MAIN_GRANTEES_0008) == set(p.MAIN_GRANTEES)


def test_the_frozen_rule_literals_are_the_live_vocabulary() -> None:
    module = revision()
    # Revision 0016 (T21) extends the frozen list with the feedback keys; it carries 0008's own, in order.
    newest = revision("0016_review_and_grant").PAYLOAD_KEYS_0016
    assert newest[: len(module.PAYLOAD_KEYS_0008)] == module.PAYLOAD_KEYS_0008
    assert set(newest) == PAYLOAD_KEYS and len(newest) == len(PAYLOAD_KEYS)
    assert set(module.NOTIFY_TYPES_0008) <= {t.value for t in EventType}
    assert set(module.NOTIFY_TYPES_0008) == {
        "action.confirmed",
        "action.failed",
        "action.conflict",  # round 1, I2: the escalation that exists today
        "run.escalated",
        "run.abandoned_unverified",
    }
    assert set(module.STATUS_TYPES_0008) == {t.value for t in DESTINATION_EVIDENCE}


def test_upgrade_creates_the_outbox_its_cells_and_its_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = statements(revision(), "upgrade", monkeypatch)
    table = next(s for s in seen if s.startswith("CREATE TABLE app.outbox"))
    for column in (
        "outbox_id uuid PRIMARY KEY",
        "tenant_id uuid NOT NULL",
        "run_id uuid NOT NULL",
        "event_id uuid NOT NULL REFERENCES app.events (event_id)",
        "channel text NOT NULL CHECK (channel = 'local')",
        "recipient text NOT NULL",
        "dedup_key text NOT NULL UNIQUE",
        "attempts integer NOT NULL DEFAULT 0",
        "leased_until timestamptz NOT NULL DEFAULT '-infinity'",
        "delivered_at timestamptz",
        "result text CHECK (result IN ('delivered', 'retrying', 'dead_letter'))",
        "created_at timestamptz NOT NULL DEFAULT now()",
        "FOREIGN KEY (tenant_id, run_id) REFERENCES app.runs (tenant_id, run_id)",
    ):
        assert column in table, column
    assert "ALTER TABLE app.outbox OWNER TO migrator" in seen
    grants = [s for s in seen if s.startswith(("GRANT", "REVOKE")) and "FUNCTION" not in s]
    assert grants == [
        OUTBOX_REVOKE,
        "GRANT SELECT ON app.outbox TO sweeper",
        "GRANT UPDATE (leased_until, attempts, delivered_at, result) ON app.outbox TO sweeper",
        "GRANT INSERT ON app.outbox TO app_definer",
        JOBS_REVOKE,
        "GRANT INSERT ON app.jobs TO api",
        "GRANT INSERT, SELECT ON app.jobs TO worker",
        "GRANT UPDATE (claimed_by, claimed_at, done_at, attempts, available_at) ON app.jobs TO worker",
        "GRANT INSERT, SELECT, DELETE ON app.jobs TO sweeper",
        "GRANT UPDATE (claimed_by, claimed_at, done_at, attempts) ON app.jobs TO sweeper",
        "GRANT INSERT, SELECT ON app.jobs TO app_definer",
    ]
    assert [s for s in seen if "POLICY" in s] == [
        "DROP POLICY IF EXISTS tenant_isolation ON app.outbox",
        (
            "CREATE POLICY tenant_isolation ON app.outbox FOR ALL TO api, worker, sweeper, app_definer"
            f" USING (tenant_id = {p.TENANT_EXPR}) WITH CHECK (tenant_id = {p.TENANT_EXPR})"
        ),
        # Round 1, I6: the sweeper's DELETE reaches finished maintenance rows only (erratum 61).
        "DROP POLICY IF EXISTS sweeper_purge_maintenance ON app.jobs",
        (
            "CREATE POLICY sweeper_purge_maintenance ON app.jobs AS RESTRICTIVE FOR DELETE TO sweeper"
            " USING (run_id IS NULL AND done_at IS NOT NULL)"
        ),
    ]
    assert p.SWEEPER_PURGE[:2] == ("jobs", "sweeper_purge_maintenance")
    assert "ALTER TABLE app.outbox FORCE ROW LEVEL SECURITY" in seen


def test_append_event_carries_the_rules_and_the_intent(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = statements(revision(), "upgrade", monkeypatch)
    (body,) = [s for s in seen if "CREATE OR REPLACE FUNCTION app._append_event" in s]
    assert "DETAIL = 'unknown payload key'" in body and "DETAIL = 'status'" in body
    assert "INSERT INTO outbox (outbox_id, tenant_id, run_id, event_id, channel, recipient, dedup_key)" in body
    assert "ON CONFLICT DO NOTHING;" in body  # no target: app_definer may insert into the outbox but not read it
    assert "format('%s:%s:local:%s', p_run_id, p_type, v_run.requester)" in body
    # The intent follows the event inside the runs lock (runs -> events -> outbox, SA:188).
    assert body.index("FOR UPDATE") < body.index("INSERT INTO events") < body.index("INSERT INTO outbox")
    assert "REVOKE ALL ON FUNCTION app._append_event(uuid, uuid, text, text, jsonb) FROM PUBLIC" in seen
    assert not any("GRANT EXECUTE ON FUNCTION app._append_event" in s for s in seen)  # a helper, granted to nobody


def test_the_downgrade_restores_0007(monkeypatch: pytest.MonkeyPatch) -> None:
    module = revision()
    seen = statements(module, "downgrade", monkeypatch)
    rev0003 = revision("0003_run_path_functions")
    assert seen[0] == rev0003.APPEND_EVENT_HELPER  # the 0003 body, byte for byte, before the table goes
    assert "DROP TABLE app.outbox" in seen and "DROP POLICY sweeper_purge_maintenance ON app.jobs" in seen
    assert seen.index("DROP TABLE app.outbox") > seen.index(OUTBOX_REVOKE)
    rev0002 = revision("0002_roles_grants_rls")
    tail = p.grant_statements(("jobs",), {"jobs": rev0002.GRANTS_0002["jobs"]}, revokees=module.MAIN_GRANTEES_0008)
    assert seen[-len(tail) :] == tail and not any("DELETE ON app.jobs" in s for s in tail)
    assert not any(s.startswith(("DELETE", "UPDATE")) for s in seen)  # it rewrites no row

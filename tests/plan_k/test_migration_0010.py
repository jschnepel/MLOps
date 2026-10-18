"""Revision 0010 without a database (Plan K rulings 3, 7, 12, 17 and 25).

Catches: a derived body that changes more than its signature, the literal `azp` and (in `record_outcome`) the one guard,
so that a lock, a refusal or an event of the applied body moves unseen; a write-path body that still names
`'ops-worker'`; `mark_sent` sending after an abort request, re-sending a SENT attempt after a cancel, past the deadline
or for a recover job, comparing the clock before the runs lock, or letting the deadline win over a cancel;
`request_abort` taking a reason from its caller, choosing one before the lock, or
writing anything when no abort is due; an upgrade that leaves an old signature behind (the catalog test requires one
function per name) or grants a function to anyone but `mcp_exec`; a downgrade that does not put back the applied
bodies byte for byte; a startup marker that does not exist only in 0010's body; and an `OC007` that a definer
mcp-write calls before any destination I/O could raise, which `server.py` no longer maps.
"""

import asyncio
import importlib.util
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import alembic.op
import pytest
from ops_core import persistence, privileges
from ops_core.persistence import WRITE_PATH

from tests.plan_e.test_transitions_table import REVISIONS

VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "app" / "versions"
HANDLE_FUNCTIONS = ("grant_execution", "lookup_action", "mark_sent", "record_outcome", "request_abort")


def revision(name: str = "0010_write_path") -> Any:
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


def bodies(module: Any) -> dict[str, str]:
    return {name: body for name, _, _, body in module.FUNCTIONS}


def test_the_derived_bodies_change_only_what_the_revision_names() -> None:
    module, rev0004, rev0007 = revision(), revision("0004_write_path_functions"), revision("0007_leases_fences")
    assert module.down_revision == "0009_handle_binding"
    for derived, applied, changes in (
        (module.GRANT_EXECUTION, rev0007.GRANT_EXECUTION, module.GRANT_CHANGES),
        (module.LOOKUP_ACTION, rev0004.LOOKUP_ACTION, module.LOOKUP_CHANGES),
        (module.RECORD_OUTCOME, rev0007.RECORD_OUTCOME, module.RECORD_CHANGES),
    ):
        undone = derived
        for old, new in changes:
            undone = undone.replace(new, old)
        assert undone == applied
    every = bodies(module)
    assert all(module.TOKEN_AZP in every[name] and "'ops-worker'" not in every[name] for name in HANDLE_FUNCTIONS)


def test_upgrade_replaces_the_four_signatures_and_grants_mcp_exec_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    module = revision()
    expected = [f"DROP FUNCTION app.{s}" for s in module.REPLACED]
    for name, args, callers, body in module.FUNCTIONS:
        expected += [body, *privileges.function_grant_statements(name, args=args, callers=callers)]
        assert callers == (() if name.startswith("_") else ("mcp_exec",)), name
    assert statements(module, "upgrade", monkeypatch) == expected
    assert module.REPLACED == (
        "grant_execution(text, uuid)",
        "lookup_action(text)",
        "mark_sent(text, uuid)",
        "record_outcome(text, uuid, text, jsonb)",
    )


def test_the_downgrade_restores_the_applied_bodies(monkeypatch: pytest.MonkeyPatch) -> None:
    module, rev0004, rev0007 = revision(), revision("0004_write_path_functions"), revision("0007_leases_fences")
    seen = statements(module, "downgrade", monkeypatch)
    dropped = [s.removeprefix("DROP FUNCTION app.") for s in seen if s.startswith("DROP FUNCTION")]
    assert sorted(dropped) == sorted(f"{name}({args})" for name, args, _, _ in module.FUNCTIONS)
    restored = [s for s in seen if s.lstrip().startswith("CREATE OR REPLACE FUNCTION")]
    # Byte for byte the applied revisions' own bodies (0007's grant, mark_sent, record_outcome; 0004's lookup_action).
    assert restored == [rev0007.GRANT_EXECUTION, rev0004.LOOKUP_ACTION, rev0007.MARK_SENT, rev0007.RECORD_OUTCOME]
    assert seen.index(restored[0]) > max(seen.index(f"DROP FUNCTION app.{d}") for d in dropped)


def test_mark_sent_sends_nothing_after_an_abort_request_and_checks_cancel_then_the_deadline() -> None:
    body = revision().MARK_SENT
    lock = body.index("FROM runs r WHERE r.run_id = v_grant.run_id FOR UPDATE")
    aborting = body.index("RETURN 'abort_requested'")
    late = body.index(
        "v_late := app.current_time() > v_grant.granted_at + make_interval(secs => app._dispatch_seconds())"
    )
    assert lock < aborting < late  # the clock is read after the lock, once
    # A SENT attempt (a re-send) first: cancel, then the deadline, then a recover job, and only then `already_sent`.
    sent = body.index("IF v_latest.state = 'SENT' THEN")
    resend = [body.index(s, sent) for s in ("cancelled", "expired", "not_redispatchable", "already_sent")]
    assert late < sent and resend == sorted(resend) and "v_handle.job_type = 'recover'" in body[sent:]
    # Then an INTENT attempt: the EXECUTING guard, cancel, the deadline, and only then SENT.
    guard = body.index("IF v_run.state <> 'EXECUTING' THEN")
    first = [
        body.index(s, guard) for s in ("RETURN 'cancelled'", "RETURN 'expired'", "INSERT INTO action_attempt_state")
    ]
    assert resend[-1] < guard and first == sorted(first) and body.count("INSERT INTO") == 1  # SENT alone


def test_request_abort_chooses_its_reason_after_the_lock_and_writes_only_when_due() -> None:
    body = revision().REQUEST_ABORT
    assert "p_reason" not in body  # the caller never supplies the reason (ruling 3)
    lock = body.index("FROM runs r WHERE r.run_id = v_grant.run_id FOR UPDATE")
    clock = body.index("v_late := app.current_time() > v_grant.granted_at")
    refusal = body.index("DETAIL = 'ABORT_NOT_DUE'")
    insert = body.index("INSERT INTO action_attempt_state")
    assert lock < clock < refusal < insert and body.count("INSERT INTO") == 1  # one state row, never a job
    for reason in ("'cancelled_before_send'", "'expired'", "'deadline'"):
        assert clock < body.index(f"THEN {reason}") < refusal, reason
    assert "'ABORT_REQUESTED'" in body[insert:] and "RETURN 'resolved'" in body[lock:clock]


def test_the_dispatch_deadline_is_a_helper_granted_to_nobody() -> None:
    module = revision()
    assert "RETURN 300;" in module.DISPATCH_SECONDS and "SECURITY DEFINER" not in module.DISPATCH_SECONDS
    assert privileges.HELPER_FUNCTIONS["_dispatch_seconds"] == ""
    mcp_exec = {name for name, (_, callers) in privileges.DEFINER_FUNCTIONS.items() if "mcp_exec" in callers}
    assert mcp_exec == {
        "current_time",  # erratum 15
        "resolve_invocation",
        "grant_execution",
        "mark_sent",
        "record_outcome",
        "request_abort",
        "lookup_action",
    }
    for name, args, _, _ in module.FUNCTIONS:
        if not name.startswith("_"):
            assert privileges.DEFINER_FUNCTIONS[name][0] == args, name


def test_the_startup_marker_is_only_in_0010s_request_abort() -> None:
    signature, marker = WRITE_PATH
    assert signature == "app.request_abort(text, text, uuid)"
    assert marker in revision().REQUEST_ABORT
    for older in REVISIONS[: REVISIONS.index("0010_write_path")]:
        assert marker not in (VERSIONS / f"{older}.py").read_text(encoding="utf-8"), older


def test_the_newest_body_of_request_abort_carries_the_startup_marker() -> None:
    newest = None
    for name in REVISIONS:  # Alembic order; the newest revision that re-creates the function wins
        for fn, _, _, body in getattr(revision(name), "FUNCTIONS", ()):
            if fn == "request_abort":
                newest = (name, body)
    assert newest is not None and WRITE_PATH[1] in newest[1], newest and newest[0]


def test_no_definer_mcp_write_calls_before_destination_io_raises_a_hash_mismatch() -> None:
    """`OC007` comes only from `record_outcome`, which mcp-write calls after the destination answered and answers
    UNKNOWN on any refusal, so `server.py` has no HASH_MISMATCH mapping left to reach (Plan K ruling 20). Every
    function those calls reach is followed through the newest body any revision installed, so a later revision that
    adds an `OC007` to one of them, or to a helper they call, fails here (round 1, M3)."""
    newest: dict[str, str] = {}
    for name in REVISIONS:  # Alembic order: a later body replaces an earlier one
        for fn, _, _, body in getattr(revision(name), "FUNCTIONS", ()):
            newest[fn] = body
    reached: set[str] = set()
    todo = ["resolve_invocation", "grant_execution", "lookup_action", "mark_sent", "request_abort"]
    while todo:
        fn = todo.pop()
        if fn in reached:
            continue
        reached.add(fn)
        todo += re.findall(r"app\.(\w+)\(", newest.get(fn, ""))
    assert reached - set(newest) == {"current_time"}  # 0002's clock read, defined outside any FUNCTIONS tuple
    assert "'OC007'" not in (VERSIONS / "0002_roles_grants_rls.py").read_text(encoding="utf-8")
    assert {"_resolve_handle", "_grant_row", "_transition", "_append_event", "_dispatch_seconds"} <= reached
    raising = sorted(fn for fn in reached if "'OC007'" in newest.get(fn, ""))
    assert raising == [] and "'OC007'" in newest["record_outcome"]


def test_request_abort_refuses_to_read_a_missing_reason_as_one() -> None:
    """An ABORT_REQUESTED row without a reason must not become the abort reason "None" (round 1, M6)."""

    class NoReason:
        async def execute(self, _query: str, _params: tuple[object, ...]) -> "NoReason":
            return self

        async def fetchone(self) -> dict[str, Any]:
            return {"reason": None}

    conn: Any = NoReason()
    with pytest.raises(persistence.PersistenceError, match="returned no reason"):
        asyncio.run(persistence.request_abort(conn, handle="h", azp="ops-worker", action_id=uuid4()))

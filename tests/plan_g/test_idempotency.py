"""The scoped Idempotency-Key without a database (BS:264, BS:299; Plan G rulings 1-6): the key's shape, the scope,
the fingerprint, and the lock-lookup-work-record order of one unit.

Catches: a key with a space, a control character or non-ASCII accepted (a proxy may rewrite it and the replay would
miss), a scope without the route template (one key reusable across routes), a fingerprint that a reformatted retry
changes or that ignores the conversation id (one key replaying another conversation's answer), work run before the
lock or the lookup, a replay that runs the work again, a conflict that records anything, and a record whose replay
renders different bytes from the first answer.
"""

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest
from ops_api.idempotency import (
    Idem,
    IdempotencyConflict,
    KeyInvalid,
    Record,
    RecordRace,
    Scope,
    Verdict,
    error_verdict,
    fingerprint,
    idempotent,
    render,
    response,
    scope_lock_key,
    validate_key,
)
from ops_core.contracts import ErrorCode

ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")
ALEX = UUID("2fc05986-c7ec-544c-b628-fdb112bbf18a")
ROUTE = "POST /api/v1/conversations/{conversation_id}/messages"
SCOPE = Scope(ALPHA, ALEX, ROUTE, "key-0001")


def test_a_key_is_8_to_128_visible_ascii_characters() -> None:
    for good in ("a" * 8, "~" * 128, str(uuid4()), "!#$%&'()*+,-./:;<=>?@[]^_`{|}"):
        assert validate_key(good) == good
    for bad in (None, "", "a" * 7, "a" * 129, "has space", "tab\tkey12", "ключ-ключ", "a" * 8 + "\x7f", "a" * 8 + "\n"):
        with pytest.raises(KeyInvalid):
            validate_key(bad)


def test_the_scope_is_tenant_subject_route_template_and_key() -> None:
    assert SCOPE.lock_key == f"{ALPHA}|{ALEX}|{ROUTE}|key-0001" == scope_lock_key(SCOPE)
    other_route = Scope(ALPHA, ALEX, "POST /api/v1/conversations", "key-0001")
    assert other_route != SCOPE and other_route.lock_key != SCOPE.lock_key


def test_the_fingerprint_ignores_layout_but_not_the_path_or_the_body() -> None:
    conv = str(uuid4())
    body = {"kind": "investigate", "text": "Investigate A17.", "context": {"asset_id": "A17", "hours": 24}}
    reordered = {"context": {"hours": 24, "asset_id": "A17"}, "text": "Investigate A17.", "kind": "investigate"}
    same = fingerprint({"conversation_id": conv}, body)
    assert fingerprint({"conversation_id": conv}, reordered) == same
    assert fingerprint({"conversation_id": str(uuid4())}, body) != same  # a key reused on another conversation
    assert fingerprint({"conversation_id": conv}, {**body, "text": "Investigate A18."}) != same
    assert fingerprint({}, None) != fingerprint({}, {})


class Unit:
    """A RecordUnit that records the order of calls; `existing` is what the lookup finds, `full` makes save fail."""

    def __init__(self, existing: Record | None = None, *, full: bool = False) -> None:
        self.calls: list[str] = []
        self.existing = existing
        self.full = full
        self.saved: list[tuple[str, Verdict, int]] = []

    async def lock_scope(self, lock_key: str) -> None:
        self.calls.append(f"lock {lock_key}")

    async def find_record(self, scope: Scope) -> Record | None:
        self.calls.append("find")
        return self.existing

    async def save_record(self, scope: Scope, fingerprint: str, verdict: Verdict, ttl_seconds: int) -> bool:
        self.calls.append("save")
        if self.full:
            return False
        self.saved.append((fingerprint, verdict, ttl_seconds))
        return True


def run(unit: Unit, fp: str = "f" * 64) -> tuple[Verdict, list[str]]:
    worked: list[str] = []

    async def work() -> Verdict:
        unit.calls.append("work")
        worked.append("once")
        return Verdict(202, {"run_id": "r1"})

    verdict = asyncio.run(idempotent(unit, Idem(SCOPE, fp, 86400, uuid4()), work))
    return verdict, worked


def test_a_miss_locks_first_runs_the_work_once_and_records_last() -> None:
    unit = Unit()
    verdict, worked = run(unit)
    assert unit.calls == [f"lock {SCOPE.lock_key}", "find", "work", "save"]  # SA:188: the record is written last
    assert verdict == Verdict(202, {"run_id": "r1"}) and not verdict.replayed and worked == ["once"]
    assert unit.saved == [("f" * 64, Verdict(202, {"run_id": "r1"}), 86400)]


def test_a_hit_with_the_same_fingerprint_replays_without_running_the_work() -> None:
    unit = Unit(Record("f" * 64, 202, {"run_id": "r0"}))
    verdict, worked = run(unit)
    assert verdict.replayed and verdict == Verdict(202, {"run_id": "r0"}) and not worked
    assert "save" not in unit.calls


def test_a_hit_with_another_fingerprint_is_a_conflict_that_records_nothing() -> None:
    unit = Unit(Record("e" * 64, 202, {"run_id": "r0"}))
    with pytest.raises(IdempotencyConflict) as refused:
        run(unit)
    assert refused.value.message == "Idempotency-Key was already used with a different request"
    assert unit.calls == [f"lock {SCOPE.lock_key}", "find"]


def test_a_save_that_meets_an_existing_row_is_a_record_race() -> None:
    with pytest.raises(RecordRace):
        run(Unit(full=True))


def test_a_verdict_renders_the_same_bytes_whatever_its_key_order() -> None:
    assert render({"b": 1, "a": "é"}) == render({"a": "é", "b": 1}) == '{"a":"é","b":1}'.encode()
    rendered = response(Verdict(202, {"b": 1, "a": "é"}))
    assert rendered.status_code == 202 and rendered.body == render({"a": "é", "b": 1})
    body: dict[str, Any] = error_verdict(409, ErrorCode.SLOT_OCCUPIED, "busy", ALEX).body
    assert body == {"code": "SLOT_OCCUPIED", "message": "busy", "retryable": False, "request_id": str(ALEX)}

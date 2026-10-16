"""The outbox delivery loop without a database (Plan I rulings 14-18): the backoff and its jitter, the log sink and
its test-profile fault, the claim and result units per tenant, and the dead letter's event in a transaction of its
own.

Catches: a delivery made while the claim's transaction is still open (a slow sink would hold row locks, and a crash
would roll the claim back and lose the lease), a result recorded in the claim's unit, a retry without backoff or
with an uncapped one, a row dead-lettered one attempt early or late, a result that overwrites a dead letter, a sink
crash on one row that costs the rest of its batch (round 2, N1), a row whose sweeper keeps dying claimed without bound
(round 1, I1), a tenant's rows left waiting behind another tenant's deliveries, a recipient written to a log in clear,
a notification.failed appended in the result's transaction (it locks runs after outbox, SA:188), or appended without
the lock taken first that serialises two sweepers, a payload `_append_event` would refuse, and a fault hook that
exists outside the test profile.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest
from ops_core import persistence
from ops_core.outcomes import EventSource, EventType, event_rules_ok
from ops_core.settings import OutboxSettings, Profile
from ops_core.testing.faults import BS405, SWEEPER_FAULTS, FaultKind, Faults, FaultsDisabled
from ops_sweeper import outbox, tenants

ALPHA, BETA = uuid4(), uuid4()
SETTINGS = OutboxSettings()


class FakeCursor:
    def __init__(self, rows: list[dict[str, Any]], rowcount: int) -> None:
        self.rows, self.rowcount = rows, rowcount

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None


class FakeConn:
    """Records every statement with the transaction it ran in; answers from `answers` by statement prefix."""

    def __init__(self, answers: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.answers = answers or {}
        self.log: list[tuple[int, str, Any]] = []
        self.unit = 0
        self.open = False

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        assert not self.open  # never nested: every unit is its own transaction
        self.unit += 1
        self.open = True
        try:
            yield
        finally:
            self.open = False

    async def execute(self, statement: str, params: Any = None) -> FakeCursor:
        assert self.open, statement  # nothing runs outside a unit
        self.log.append((self.unit, statement, params))
        for prefix, rows in self.answers.items():
            if statement.startswith(prefix):
                return FakeCursor(rows, len(rows))
        return FakeCursor([], 1)


@pytest.fixture(autouse=True)
def database(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """set_tenant and append_event replaced by recorders; two tenants."""
    calls: list[Any] = []

    async def set_tenant(conn: FakeConn, tenant_id: UUID) -> None:
        calls.append(("set_tenant", conn.unit, tenant_id))

    async def append_event(conn: FakeConn, **kwargs: Any) -> None:
        calls.append(("append_event", conn.unit, kwargs))

    async def all_tenants(_conn: Any) -> list[UUID]:
        return [ALPHA, BETA]

    monkeypatch.setattr(persistence, "set_tenant", set_tenant)
    monkeypatch.setattr(persistence, "append_event", append_event)
    monkeypatch.setattr(persistence, "tenants", all_tenants)
    return calls


def claimed(attempts: int, run_id: UUID | None = None) -> dict[str, Any]:
    return {
        "outbox_id": uuid4(),
        "tenant_id": ALPHA,
        "run_id": run_id or uuid4(),
        "event_id": uuid4(),
        "channel": "local",
        "recipient": "2fc05986-c7ec-544c-b628-fdb112bbf18a",
        "attempts": attempts,
        "type": "action.confirmed",
    }


class Recording:
    """A sink that records whether a transaction was open when it was called, and fails when told to."""

    def __init__(self, conn: FakeConn, fail: bool) -> None:
        self.conn, self.fail = conn, fail
        self.calls: list[tuple[outbox.Delivery, bool]] = []
        self.units: list[int] = []  # the last unit the connection had opened when each delivery was made

    async def deliver(self, delivery: outbox.Delivery) -> None:
        self.calls.append((delivery, self.conn.open))
        self.units.append(self.conn.unit)
        if self.fail:
            raise outbox.SinkFailed("down")


def run(coro: Awaitable[Any]) -> Any:
    async def main() -> Any:
        return await coro

    return asyncio.run(main())


def test_the_backoff_doubles_from_its_base_up_to_its_cap_plus_a_quarter_of_jitter() -> None:
    assert outbox.backoff_seconds(1, SETTINGS, rng=lambda: 0.0) == 2.0
    assert outbox.backoff_seconds(3, SETTINGS, rng=lambda: 0.0) == 8.0
    assert outbox.backoff_seconds(3, SETTINGS, rng=lambda: 1.0) == 10.0  # up to 25 % on top
    assert outbox.backoff_seconds(20, SETTINGS, rng=lambda: 0.0) == 300.0  # BS:562: capped
    assert outbox.backoff_seconds(100, SETTINGS, rng=lambda: 1.0) == 375.0


def test_the_log_sink_logs_one_line_without_the_recipient(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="ops_sweeper.outbox")
    row = claimed(1)
    delivery = outbox.Delivery(row["outbox_id"], ALPHA, row["run_id"], row["type"], "local", row["recipient"], 1)
    run(outbox.LogSink().deliver(delivery))
    (record,) = caplog.records
    assert str(row["outbox_id"]) in record.getMessage() and "action.confirmed" in record.getMessage()
    assert row["recipient"] not in caplog.text and outbox.recipient_hash(row["recipient"]) in record.getMessage()


def test_the_sink_fault_fails_exactly_the_armed_deliveries() -> None:
    faults = Faults(Profile.TEST)
    faults.arm(FaultKind.OUTBOX_SINK_FAIL, 2)
    sink = outbox.LogSink(faults)
    row = claimed(1)
    delivery = outbox.Delivery(row["outbox_id"], ALPHA, row["run_id"], row["type"], "local", row["recipient"], 1)
    for _ in range(2):
        with pytest.raises(outbox.SinkFailed):
            run(sink.deliver(delivery))
    run(sink.deliver(delivery))  # the third is delivered
    assert faults.armed() == {}


def test_the_sink_fault_belongs_to_the_sweeper_and_the_test_profile_only() -> None:
    assert FaultKind.OUTBOX_SINK_FAIL in SWEEPER_FAULTS and FaultKind.OUTBOX_SINK_FAIL not in BS405.values()
    for profile in (Profile.DEV, Profile.DEMO):
        with pytest.raises(FaultsDisabled):
            Faults(profile)


def test_for_each_tenant_runs_one_transaction_per_tenant_after_set_tenant(database: list[Any]) -> None:
    conn = FakeConn()
    as_conn: Any = conn

    async def work(c: Any) -> int:
        await c.execute("SELECT 1")
        return c.unit

    assert run(tenants.for_each_tenant(as_conn, work)) == {ALPHA: 1, BETA: 2}
    assert database == [("set_tenant", 1, ALPHA), ("set_tenant", 2, BETA)]
    assert run(tenants.for_each_tenant(as_conn, work, tenants=[BETA])) == {BETA: 3}


@pytest.mark.parametrize(
    ("attempts", "fail", "result"), [(1, False, "delivered"), (1, True, "retrying"), (5, True, "dead_letter")]
)
def test_a_delivery_runs_between_its_claim_and_its_result_unit(attempts: int, fail: bool, result: str) -> None:
    row = claimed(attempts)
    conn = FakeConn({"WITH claimed AS (UPDATE app.outbox": [row]})
    as_conn: Any = conn
    sink = Recording(conn, fail)
    results = run(outbox.deliver(as_conn, sink, SETTINGS, tenants=[ALPHA], rng=lambda: 0.0))
    assert results == [outbox.Result(row["outbox_id"], ALPHA, row["run_id"], result, attempts, True)]
    ((delivery, open_transaction),) = sink.calls
    assert not open_transaction and delivery.attempt == attempts  # delivered outside any transaction
    (exhaust_unit, exhaust, exhaust_params), (claim_unit, claim, claim_params), (result_unit, record, record_params) = (
        conn.log
    )
    assert exhaust_unit == claim_unit and result_unit == claim_unit + 1  # the result is its own unit
    # Round 1, I1: a row whose attempts reached the cap and whose lease ran out (its last delivery crashed) is
    # dead-lettered in the claim's unit, before the claim, which takes only rows still under the cap.
    assert exhaust.startswith("UPDATE app.outbox SET result = 'dead_letter' WHERE delivered_at IS NULL")
    assert "attempts >= %s AND leased_until <= app.current_time()" in exhaust
    assert exhaust_params == (SETTINGS.max_attempts,)
    for condition in (
        "delivered_at IS NULL",
        "result IS DISTINCT FROM 'dead_letter'",
        "leased_until <= app.current_time()",
        "attempts < %s",
        "FOR UPDATE SKIP LOCKED",
        "attempts = attempts + 1",
    ):
        assert condition in claim, condition
    assert claim_params == (SETTINGS.lease_seconds, SETTINGS.max_attempts, SETTINGS.batch)
    assert "AND attempts = %s AND delivered_at IS NULL" in record  # a stale result never overwrites a newer claim
    assert "AND result IS DISTINCT FROM 'dead_letter'" in record  # nor a dead letter (round 2, N2)
    if result == "delivered":
        assert "result = 'delivered'" in record and record_params == (row["outbox_id"], attempts)
    elif result == "retrying":
        assert "result = 'retrying'" in record and record_params == (2.0, row["outbox_id"], attempts)
    else:
        assert "result = 'dead_letter'" in record and record_params == (row["outbox_id"], attempts)


def test_an_unclaimed_tenant_delivers_nothing() -> None:
    conn = FakeConn()
    as_conn: Any = conn
    sink = Recording(conn, fail=False)
    assert run(outbox.deliver(as_conn, sink, SETTINGS)) == [] and sink.calls == []
    assert [unit for unit, _, _ in conn.log] == [1, 1, 2, 2]  # one claim unit per tenant, nothing else


def test_each_tenant_is_delivered_before_the_next_is_claimed() -> None:
    """Round 1, M10: a tenant's rows are claimed, delivered and recorded before the next tenant is claimed, so no
    claimed row's lease runs while other tenants' deliveries go first."""
    conn = FakeConn({"WITH claimed AS (UPDATE app.outbox": [claimed(1)]})
    as_conn: Any = conn
    sink = Recording(conn, fail=False)
    results = run(outbox.deliver(as_conn, sink, SETTINGS))
    assert [r.tenant_id for r in results] == [ALPHA, BETA]
    assert sink.units == [1, 3]  # ALPHA delivered after its claim (unit 1); BETA claimed (unit 3) after ALPHA's result
    assert [unit for unit, _, _ in conn.log] == [1, 1, 2, 3, 3, 4]


def test_a_dead_letter_gets_its_event_in_a_transaction_of_its_own(database: list[Any]) -> None:
    run_id, outbox_id = uuid4(), uuid4()
    pending = {"outbox_id": outbox_id, "run_id": run_id, "attempts": 5}
    conn = FakeConn({"SELECT o.outbox_id, o.run_id, o.attempts FROM app.outbox o": [pending]})
    as_conn: Any = conn
    assert run(outbox.notify_dead_letters(as_conn, tenants=[ALPHA])) == [outbox_id]
    appended = [call for call in database if call[0] == "append_event"]
    ((_, unit, kwargs),) = appended
    find_unit = conn.log[0][0]
    assert unit == find_unit + 1  # the re-check and the append share a unit after the scan's
    assert kwargs["run_id"] == run_id and kwargs["type"] is EventType.NOTIFICATION_FAILED
    payload = kwargs["payload"]
    assert payload["outbox_id"] == str(outbox_id) and payload["code"] == outbox.DEAD_LETTER_CODE
    event_rules_ok(EventType.NOTIFICATION_FAILED, EventSource.APPLICATION, payload)  # what _append_event accepts
    # The unit's first statement is the advisory lock on the outbox id (two sweepers serialise there, round 1 M5),
    # then the re-check; the append follows in the same unit.
    (lock, lock_params), (recheck, _) = [(s, params) for u, s, params in conn.log if u == unit]
    assert lock == outbox.ANNOUNCE_LOCK and lock_params == (str(outbox_id),)
    assert "AND o.outbox_id = %s" in recheck


def test_a_dead_letter_already_notified_gets_no_second_event(database: list[Any]) -> None:
    pending = {"outbox_id": uuid4(), "run_id": uuid4(), "attempts": 5}
    conn = FakeConn({"SELECT o.outbox_id, o.run_id, o.attempts FROM app.outbox o": [pending]})

    class Raced(FakeConn):
        async def execute(self, statement: str, params: Any = None) -> FakeCursor:
            if "AND o.outbox_id = %s" in statement:  # another sweeper appended it meanwhile: the re-check is empty
                self.log.append((self.unit, statement, params))
                return FakeCursor([], 0)
            return await super().execute(statement, params)

    raced = Raced(conn.answers)
    as_conn: Any = raced
    assert run(outbox.notify_dead_letters(as_conn, tenants=[ALPHA])) == []
    assert not [call for call in database if call[0] == "append_event"]


def test_a_crashing_row_costs_one_attempt_and_spares_its_batch(caplog: pytest.LogCaptureFixture) -> None:
    """Round 2, N1: a sink that raises anything but SinkFailed on one row is caught at the sink boundary, logged with
    its traceback and recorded as that row's failed attempt (backoff, like a refusal); the rows claimed with it are
    delivered."""
    caplog.set_level(logging.ERROR, logger="ops_sweeper.outbox")
    rows = [claimed(1), claimed(1), claimed(1)]
    conn = FakeConn({"WITH claimed AS (UPDATE app.outbox": rows})
    as_conn: Any = conn
    poison = rows[1]["outbox_id"]

    class CrashesOnOne:
        async def deliver(self, delivery: outbox.Delivery) -> None:
            if delivery.outbox_id == poison:
                raise RuntimeError("the sink crashed on this row")

    results = run(outbox.deliver(as_conn, CrashesOnOne(), SETTINGS, tenants=[ALPHA], rng=lambda: 0.0))
    assert [(r.outbox_id, r.result, r.attempts) for r in results] == [
        (rows[0]["outbox_id"], "delivered", 1),
        (poison, "retrying", 1),
        (rows[2]["outbox_id"], "delivered", 1),
    ]
    retries = [params for _, statement, params in conn.log if "result = 'retrying'" in statement]
    assert retries == [(2.0, poison, 1)]  # exactly one attempt, recorded with its backoff
    assert "notification delivery crashed" in caplog.text and "Traceback" in caplog.text


def test_a_killed_delivery_leaves_its_row_leased() -> None:
    """A sweeper killed mid-delivery (its task cancelled, as a dying process cancels it; not an Exception, so the sink
    boundary lets it through) records nothing: the row comes back when its lease runs out, and the claim dead-letters
    it once its attempts reached the cap (round 1, I1)."""
    row = claimed(1)
    conn = FakeConn({"WITH claimed AS (UPDATE app.outbox": [row]})
    as_conn: Any = conn

    class Killed:
        async def deliver(self, delivery: outbox.Delivery) -> None:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        run(outbox.deliver(as_conn, Killed(), SETTINGS, tenants=[ALPHA]))
    assert len(conn.log) == 2  # the claim's unit only: nothing is recorded

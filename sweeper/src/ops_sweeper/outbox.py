"""The notification outbox's delivery loop (BS:524; Plan I rulings 13-17; errata 66-68), run by the sweeper's tick.

`_append_event` writes one intent per run, event type, channel and recipient in the event's own transaction (revision
0008). Here, one tenant after another: a claim unit first dead-letters the rows whose attempts reached the cap and
whose lease ran out (a sweeper killed during its last attempt), then leases a batch of due rows (`FOR UPDATE SKIP
LOCKED`, `leased_until` moved one lease ahead, `attempts + 1`) and commits; each row is handed to the sink outside any
transaction; then one result unit per row records `delivered`, or `retrying` with a capped, jittered backoff in
`leased_until`, or `dead_letter` at the last attempt. The tenant's rows are delivered before the next tenant is
claimed, so no claimed row waits behind another tenant's deliveries. The result names the attempt it belongs to, so a
delivery that outlived its lease and was claimed again cannot overwrite the newer claim's result, and no result
overwrites a dead letter. A sink that crashes (raises anything but `SinkFailed`) is caught at the sink boundary,
logged with its traceback and recorded as a failed attempt of that row alone (round 2, N1): the batch's other rows,
the later tenants and the announcements go on. A sweeper killed mid-delivery records nothing: its rows come back when
their lease runs out, and once a row's attempts reached the cap the next claim dead-letters it (round 1, I1). The
run's state is never touched: the delivery result is recorded apart from the action's outcome (DoD 2, BS:685).

A dead letter is announced by `notification.failed`, appended through `append_event` in a transaction of its own
after the result unit, because `append_event` locks `runs` and SA:188 forbids taking `runs` after `outbox`. The
dead letters still lacking that event are found again on every tick (`notify_dead_letters`), which closes the crash
window between the result and the event. The announcement's unit takes a transaction advisory lock on the outbox id
first, then re-checks and appends, so a second sweeper announcing the same dead letter waits for the first one's
commit and then finds the event (the statement order a unit test pins; no test races two sweepers).

The v1 sink is `LogSink`: one log line per delivery and no egress (no channel is approved before Slack, T39). Its
fault hook, `outbox_sink_fail`, exists only in the test profile and is armed through the sink's `faults` argument.
"""

from __future__ import annotations

import functools
import hashlib
import logging
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from ops_core import persistence
from ops_core.outcomes import EventType
from ops_core.settings import OutboxSettings
from ops_core.testing.faults import FaultKind, Faults

from ops_sweeper.tenants import for_each_tenant, in_tenant

log = logging.getLogger("ops_sweeper.outbox")

DEAD_LETTER_CODE = "notification_dead_letter"
# BS:516: infrastructure failures are reported from templates, never from a model.
DEAD_LETTER_MESSAGE = "The notification could not be delivered after {attempts} attempts; the run's outcome stands."

# A row whose attempts reached the cap and whose lease ran out lost its last attempt with the process that claimed it
# (a refusal or a caught crash would have dead-lettered it in its result unit): it is not claimed again, it is
# dead-lettered (round 1, I1).
EXHAUSTED = (
    "UPDATE app.outbox SET result = 'dead_letter' WHERE delivered_at IS NULL"
    " AND result IS DISTINCT FROM 'dead_letter' AND attempts >= %s AND leased_until <= app.current_time()"
)
CLAIM = (
    "WITH claimed AS (UPDATE app.outbox SET leased_until = app.current_time() + make_interval(secs => %s),"
    " attempts = attempts + 1"
    " WHERE outbox_id IN (SELECT outbox_id FROM app.outbox"
    " WHERE delivered_at IS NULL AND result IS DISTINCT FROM 'dead_letter' AND leased_until <= app.current_time()"
    " AND attempts < %s ORDER BY created_at, outbox_id FOR UPDATE SKIP LOCKED LIMIT %s)"
    " RETURNING outbox_id, tenant_id, run_id, event_id, channel, recipient, attempts)"
    " SELECT c.outbox_id, c.tenant_id, c.run_id, c.event_id, c.channel, c.recipient, c.attempts, e.type"
    " FROM claimed c JOIN app.events e ON e.event_id = c.event_id ORDER BY c.outbox_id"
)
# Every result names the attempt it belongs to and never overwrites a dead letter: a delivery that outlived its lease
# can meet another sweeper's claim-time dead letter at the same attempt, and the dead letter stands (round 2, N2).
DELIVERED = (
    "UPDATE app.outbox SET delivered_at = app.current_time(), result = 'delivered'"
    " WHERE outbox_id = %s AND attempts = %s AND delivered_at IS NULL AND result IS DISTINCT FROM 'dead_letter'"
)
RETRY = (
    "UPDATE app.outbox SET result = 'retrying', leased_until = app.current_time() + make_interval(secs => %s)"
    " WHERE outbox_id = %s AND attempts = %s AND delivered_at IS NULL AND result IS DISTINCT FROM 'dead_letter'"
)
DEAD = (
    "UPDATE app.outbox SET result = 'dead_letter'"
    " WHERE outbox_id = %s AND attempts = %s AND delivered_at IS NULL AND result IS DISTINCT FROM 'dead_letter'"
)
# The announcement's lock (lock order: advisory:notification): the two-key space with class 2, apart from the API's
# idempotency lock (class 1, erratum 37) and the asset guard's one-key space (SA:189).
ANNOUNCE_LOCK = "SELECT pg_advisory_xact_lock(2, hashtext(%s))"
UNNOTIFIED = (
    "SELECT o.outbox_id, o.run_id, o.attempts FROM app.outbox o WHERE o.result = 'dead_letter'"
    " AND NOT EXISTS (SELECT 1 FROM app.events e WHERE e.run_id = o.run_id AND e.type = 'notification.failed'"
    " AND e.payload->>'outbox_id' = o.outbox_id::text)"
)


@dataclass(frozen=True)
class Delivery:
    """What a sink is handed: the row, its event's type and the attempt; never the event's payload."""

    outbox_id: UUID
    tenant_id: UUID
    run_id: UUID
    event_type: str
    channel: str
    recipient: str
    attempt: int


@dataclass(frozen=True)
class Result:
    """What one claimed row came to; `recorded` is False when a newer claim had already moved the row on."""

    outbox_id: UUID
    tenant_id: UUID
    run_id: UUID
    result: str
    attempts: int
    recorded: bool


class SinkFailed(Exception):
    """The sink did not take the notification; the row is retried, or dead-lettered at its last attempt."""


class Sink(Protocol):
    """Where a notification goes (ruling 14). `deliver` raises SinkFailed when the notification was not taken."""

    async def deliver(self, delivery: Delivery) -> None:
        """Deliver one notification, or raise SinkFailed."""


def recipient_hash(recipient: str) -> str:
    """A short, stable stand-in for the recipient in logs: the subject itself never reaches a log line."""
    return hashlib.sha256(recipient.encode("utf-8")).hexdigest()[:12]


class LogSink:
    """The v1 sink: one structured log line per delivery (type, run, outbox row, a hash of the recipient), no egress
    and no payload content (BS:524's redaction holds trivially: nothing is sent)."""

    def __init__(self, faults: Faults | None = None) -> None:
        self.faults = faults  # a test-profile Faults (the factory refuses to exist elsewhere), or None

    async def deliver(self, delivery: Delivery) -> None:
        """Log the delivery; raise SinkFailed instead when the test fault is armed."""
        if self.faults is not None and self.faults.take(FaultKind.OUTBOX_SINK_FAIL):
            raise SinkFailed("the sink refused the notification (test fault)")
        log.info(
            "notification delivered: type=%s run=%s outbox=%s channel=%s recipient=%s attempt=%d",
            delivery.event_type,
            delivery.run_id,
            delivery.outbox_id,
            delivery.channel,
            recipient_hash(delivery.recipient),
            delivery.attempt,
        )


def backoff_seconds(attempts: int, chosen: OutboxSettings, rng: Callable[[], float] = random.random) -> float:
    """The wait after the `attempts`-th failure: `min(cap, base × 2^(attempts−1))` plus up to a quarter of that as
    jitter (BS:562, ruling 16), so retries of many rows do not fall due in the same instant."""
    exponential = min(chosen.backoff_cap_seconds, chosen.backoff_base_seconds * 2 ** (attempts - 1))
    return float(exponential) * (1 + 0.25 * rng())


async def _claim(conn: persistence.Conn, *, chosen: OutboxSettings) -> list[dict[str, Any]]:
    await conn.execute(EXHAUSTED, (chosen.max_attempts,))
    cur = await conn.execute(CLAIM, (chosen.lease_seconds, chosen.max_attempts, chosen.batch))
    return [dict(row) for row in await cur.fetchall()]


async def record_result(
    conn: persistence.Conn, *, row: dict[str, Any], result: str, chosen: OutboxSettings, rng: Callable[[], float]
) -> bool:
    """Record one claimed row's result for the attempt it was claimed at; False when a newer claim moved it on."""
    if result == "delivered":
        cur = await conn.execute(DELIVERED, (row["outbox_id"], row["attempts"]))
    elif result == "retrying":
        wait = backoff_seconds(row["attempts"], chosen, rng)
        cur = await conn.execute(RETRY, (wait, row["outbox_id"], row["attempts"]))
    else:
        cur = await conn.execute(DEAD, (row["outbox_id"], row["attempts"]))
    return cur.rowcount == 1


async def deliver(
    conn: persistence.Conn,
    sink: Sink,
    chosen: OutboxSettings,
    *,
    tenants: Sequence[UUID] | None = None,
    rng: Callable[[], float] = random.random,
) -> list[Result]:
    """For one tenant after another: claim its due rows, deliver them outside any transaction, record each result in
    a unit of its own.

    A refusal (`SinkFailed`) and a crash (any other exception from the sink) are both a failed attempt of that row:
    retried after its backoff, dead-lettered at the cap. Only the database, or the process dying, can end the loop
    early; a row claimed and not yet recorded then comes back when its lease runs out, and the claim dead-letters it
    once its attempts reached the cap.
    """
    chosen_tenants = await persistence.tenants(conn) if tenants is None else list(tenants)
    results: list[Result] = []
    for tenant in chosen_tenants:
        rows = await in_tenant(conn, tenant, functools.partial(_claim, chosen=chosen))
        for row in rows:
            delivery = Delivery(
                outbox_id=row["outbox_id"],
                tenant_id=tenant,
                run_id=row["run_id"],
                event_type=str(row["type"]),
                channel=str(row["channel"]),
                recipient=str(row["recipient"]),
                attempt=int(row["attempts"]),
            )
            failed = "dead_letter" if row["attempts"] >= chosen.max_attempts else "retrying"
            try:
                await sink.deliver(delivery)
            except SinkFailed as exc:
                result = failed
                log.warning(
                    "notification not delivered: type=%s run=%s outbox=%s attempt=%d of %d (%s): %s",
                    delivery.event_type,
                    delivery.run_id,
                    delivery.outbox_id,
                    delivery.attempt,
                    chosen.max_attempts,
                    result,
                    exc,
                )
            # The sink boundary (round 2, N1): a sink that crashes on one row must cost that row one attempt and touch
            # nothing else, not the batch's other rows, the later tenants or the announcements.
            except Exception:
                result = failed
                log.exception(
                    "notification delivery crashed: type=%s run=%s outbox=%s attempt=%d of %d (%s)",
                    delivery.event_type,
                    delivery.run_id,
                    delivery.outbox_id,
                    delivery.attempt,
                    chosen.max_attempts,
                    result,
                )
            else:
                result = "delivered"
            work = functools.partial(record_result, row=row, result=result, chosen=chosen, rng=rng)
            recorded = await in_tenant(conn, tenant, work)
            results.append(Result(row["outbox_id"], tenant, row["run_id"], result, int(row["attempts"]), recorded))
    return results


async def _unnotified(conn: persistence.Conn) -> list[dict[str, Any]]:
    cur = await conn.execute(UNNOTIFIED + " ORDER BY o.created_at")
    return [dict(row) for row in await cur.fetchall()]


async def _notify(conn: persistence.Conn, *, row: dict[str, Any]) -> bool:
    # The advisory lock serialises two sweepers on this dead letter; the re-check then runs in the append's own
    # transaction, so an event another tick (or a crash after it) already appended is seen here, never added twice.
    await conn.execute(ANNOUNCE_LOCK, (str(row["outbox_id"]),))
    cur = await conn.execute(UNNOTIFIED + " AND o.outbox_id = %s", (row["outbox_id"],))
    if await cur.fetchone() is None:
        return False
    await persistence.append_event(
        conn,
        run_id=row["run_id"],
        type=EventType.NOTIFICATION_FAILED,
        payload={
            "code": DEAD_LETTER_CODE,
            "message": DEAD_LETTER_MESSAGE.format(attempts=row["attempts"]),
            "outbox_id": str(row["outbox_id"]),
        },
    )
    log.warning(
        "notification dead-lettered: run=%s outbox=%s attempts=%d", row["run_id"], row["outbox_id"], row["attempts"]
    )
    return True


async def notify_dead_letters(conn: persistence.Conn, *, tenants: Sequence[UUID] | None = None) -> list[UUID]:
    """Append `notification.failed` once for every dead letter that lacks it, each in its own transaction (SA:188,
    ruling 17). Returns the outbox ids announced now."""
    pending = await for_each_tenant(conn, _unnotified, tenants=tenants)
    announced: list[UUID] = []
    for tenant, rows in pending.items():
        for row in rows:
            if await in_tenant(conn, tenant, functools.partial(_notify, row=row)):
                announced.append(row["outbox_id"])
    return announced

"""T14 live (OPS_LIVE=1): the notification outbox end to end against the per-session test database, as role
`sweeper` (R024, DoD 2; Plan I rulings 13-18 and 28).

Each test builds its runs on a tenant of its own (the seeded tenant's memberships copied, so the real decision and
grant functions accept them) and delivers only that tenant, so another test's rows can neither consume an armed
fault nor be counted. R024: a run is driven to SUCCEEDED through `record_outcome`, which commits `action.confirmed`
and its intent together; delivery then fails five times on the database clock (the sink's test-profile fault, the
test clock moved past each backoff): the row goes `retrying` with its attempts counted and is finally dead-lettered,
while the run's state and events stay exactly as the outcome left them; replaying `record_outcome` and appending the
outcome event again add no second intent (the dedup key); the dead letter's `notification.failed` is not appended in
the result's transaction, and the next re-check appends it exactly once (the crash window between the two closed).
Writes evidence to reports/outbox/t14-outbox.txt (verdicts and counts; no recipient, handle or seeded tenant id).

Catches: an intent written outside the outcome's transaction or twice, a delivery failure that touches the run, a
retry that comes back before its backoff or never, a row dead-lettered early or late, a dead letter announced twice
or never, a sink crash on one row that costs the rows claimed with it an attempt (round 2, N1), a delivery whose
sweeper was killed that is lost instead of retried when its lease runs out or retried without bound, a late result
that overwrites a newer claim's or a dead letter, a recipient in a log line, and a sweeper that delivers one tenant's
rows under another's setting.

A killed sweeper is simulated by cancelling the delivery's task while the sink awaits (`Hanging`): the claim's unit
has committed and no result unit has started, so no database unit is cancelled.
"""

import asyncio
import functools
import logging
import time
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from ops_core import persistence
from ops_core.settings import OutboxSettings, Profile, Role
from ops_core.testing.faults import FaultKind, Faults
from ops_sweeper import outbox
from ops_sweeper.tenants import in_tenant
from psycopg.types.json import Jsonb

from tests.e2e.conftest import purge_run, purge_tenant
from tests.e2e.test_definers_run_path_live import ALPHA
from tests.e2e.test_definers_write_path_live import SAM, approve, drafting_run, freeze, handle_for
from tests.e2e.test_migrations_and_persistence import ALEX, new_run

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
EVIDENCE = Path("reports/outbox/t14-outbox.txt")
EXPECTED_LINES = 5  # one per test
# The defaults but a 60 s first backoff: a retry must stay "not due" while the test looks at it (2 s could pass),
# and every backoff stays under 375 s (60 doubling, capped at 300, plus a quarter), so a 400 s clock step makes it due.
CHOSEN = OutboxSettings(backoff_base_seconds=60)


@pytest.fixture(scope="module")
def lines() -> Iterator[list[str]]:
    out = [f"T14 outbox — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"]
    yield out
    if len(out) != 1 + EXPECTED_LINES:  # a failed or partial run leaves the committed file as it was
        return
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


async def own_tenant(app_conn: persistence.Conn) -> UUID:
    """A tenant whose memberships are the seeded tenant's, stamped now (the grant refuses stale ones)."""
    tenant = uuid4()
    await app_conn.execute("INSERT INTO app.tenants (tenant_id, name) VALUES (%s, %s)", (tenant, f"t-{tenant}"))
    await app_conn.execute(
        "INSERT INTO app.memberships (tenant_id, issuer, subject, role, active, permission_version, synced_at)"
        " SELECT %s, issuer, subject, role, active, permission_version, app.current_time() FROM app.memberships"
        " WHERE tenant_id = %s",
        (tenant, ALPHA),
    )
    return tenant


@dataclass
class Outcome:
    """A run driven to SUCCEEDED through the real definers, with what a replay of its outcome needs."""

    tenant: UUID
    run: UUID
    handle: str
    action: UUID
    document: dict[str, Any]


async def succeeded_run(app_conn: persistence.Conn, role_conn: RoleConn, tenant: UUID) -> Outcome:
    api, worker, mcp_exec = [await role_conn(r) for r in (Role.API, Role.WORKER, Role.MCP_EXEC)]
    run = await drafting_run(app_conn, api, worker, tenant)
    proposal, _, digest = await freeze(app_conn, worker, run, tenant)
    await approve(api, proposal, digest, SAM, tenant)
    handle = await handle_for(app_conn, run, "execute", expires_in=600)
    cur = await mcp_exec.execute("SELECT * FROM app.grant_execution(%s, %s)", (handle, proposal))
    action = (await cur.fetchone())["action_id"]
    assert (await (await mcp_exec.execute("SELECT app.mark_sent(%s, %s) AS r", (handle, action))).fetchone())[
        "r"
    ] == "sent"
    document = {
        "status": "SUCCEEDED",
        "action_id": str(action),
        "payload_sha256": digest,
        "receipt": {"receipt_id": str(uuid4()), "incident_id": "INC-T14", "committed_at": "2026-10-15T12:00:00Z"},
        "tombstone": None,
        "reason": None,
    }
    cur = await mcp_exec.execute(
        "SELECT app.record_outcome(%s, %s, 'SUCCEEDED', %s) AS r", (handle, action, Jsonb(document))
    )
    assert (await cur.fetchone())["r"] == "SUCCEEDED"
    return Outcome(tenant, run, handle, action, document)


async def run_view(app_conn: persistence.Conn, run: UUID) -> dict[str, Any]:
    """The run as its outcome left it: state, version and every event."""
    cur = await app_conn.execute("SELECT state, state_version FROM app.runs WHERE run_id = %s", (run,))
    row = dict(await cur.fetchone())
    cur = await app_conn.execute(
        "SELECT sequence, type, source, payload FROM app.events WHERE run_id = %s ORDER BY sequence", (run,)
    )
    return {**row, "events": [dict(e) for e in await cur.fetchall()]}


async def intents(app_conn: persistence.Conn, run: UUID) -> list[dict[str, Any]]:
    cur = await app_conn.execute(
        "SELECT o.outbox_id, e.type, o.recipient, o.dedup_key, o.attempts, o.result, o.delivered_at,"
        " o.leased_until > app.current_time() AS waiting FROM app.outbox o JOIN app.events e USING (event_id)"
        " WHERE o.run_id = %s",
        (run,),
    )
    return [dict(row) for row in await cur.fetchall()]


async def failures(app_conn: persistence.Conn, run: UUID) -> list[dict[str, Any]]:
    cur = await app_conn.execute(
        "SELECT payload FROM app.events WHERE run_id = %s AND type = 'notification.failed' ORDER BY sequence", (run,)
    )
    return [row["payload"] for row in await cur.fetchall()]


async def move_clock(harness: persistence.Conn, seconds: int) -> None:
    """The application clock's offset (AM-20.6); global, so only while no other lease or backoff in this database
    matters, and reset to 0 in `finally`."""
    await harness.execute("UPDATE app.test_clock SET clock_offset = make_interval(secs => %s)", (seconds,))


async def test_r024_a_failed_delivery_keeps_the_outcome_and_one_intent(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    sweeper, harness, mcp_exec = [await role_conn(r) for r in (Role.SWEEPER, Role.TEST_HARNESS, Role.MCP_EXEC)]
    tenant = await own_tenant(app_conn)
    staged: Outcome | None = None
    try:
        staged = await succeeded_run(app_conn, role_conn, tenant)
        run = staged.run
        before = await run_view(app_conn, run)
        assert before["state"] == "SUCCEEDED" and before["events"][-1]["type"] == "action.confirmed"
        (intent,) = await intents(app_conn, run)  # committed with the outcome (ruling 13)
        assert (intent["type"], intent["recipient"], intent["attempts"], intent["result"]) == (
            "action.confirmed",
            ALEX,
            0,
            None,
        )
        assert intent["dedup_key"] == f"{run}:action.confirmed:local:{ALEX}"
        faults = Faults(Profile.TEST)
        faults.arm(FaultKind.OUTBOX_SINK_FAIL, CHOSEN.max_attempts)
        sink = outbox.LogSink(faults)

        results = await outbox.deliver(sweeper, sink, CHOSEN, tenants=[tenant])
        assert [(r.run_id, r.result, r.attempts, r.recorded) for r in results] == [(run, "retrying", 1, True)]
        (row,) = await intents(app_conn, run)
        assert (row["attempts"], row["result"], row["delivered_at"], row["waiting"]) == (1, "retrying", None, True)
        assert await run_view(app_conn, run) == before  # the delivery result is recorded apart from the run
        assert await outbox.deliver(sweeper, sink, CHOSEN, tenants=[tenant]) == []  # inside its backoff: not due

        # The dedup key preserves the intent: a replayed outcome returns what stands and writes nothing, and the
        # outcome event appended again (inside a transaction rolled back after the check) adds an event, no intent.
        cur = await mcp_exec.execute(
            "SELECT app.record_outcome(%s, %s, 'SUCCEEDED', %s) AS r",
            (staged.handle, staged.action, Jsonb(staged.document)),
        )
        assert (await cur.fetchone())["r"] == "SUCCEEDED"
        async with app_conn.transaction(force_rollback=True):
            confirmed = before["events"][-1]
            # The replay above returns at RESOLVED before any append, so the second append runs as the definer that
            # writes intents (record_outcome's identity), with the tenant set: its target-less ON CONFLICT then meets
            # the outbox's INSERT-only grant and forced tenant policy, which the superuser would bypass.
            await app_conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant),))
            await app_conn.execute("SET LOCAL ROLE app_definer")
            cur = await app_conn.execute("SELECT current_user AS who")
            assert (await cur.fetchone())["who"] == "app_definer"
            await app_conn.execute(
                "SELECT * FROM app._append_event(%s, %s, 'action.confirmed', 'destination', %s)",
                (tenant, run, Jsonb(confirmed["payload"])),
            )
            await app_conn.execute("RESET ROLE")  # the checks below read the outbox, which app_definer cannot
            assert len((await run_view(app_conn, run))["events"]) == len(before["events"]) + 1
            assert len(await intents(app_conn, run)) == 1
        assert await run_view(app_conn, run) == before and len(await intents(app_conn, run)) == 1

        # Attempts 2-5, each after its backoff on the database clock (400 s steps; no backoff exceeds 375 s).
        seen = [("retrying", 1)]
        for attempt in range(2, CHOSEN.max_attempts + 1):
            await move_clock(harness, 400 * (attempt - 1))
            results = await outbox.deliver(sweeper, sink, CHOSEN, tenants=[tenant])
            assert [r.attempts for r in results] == [attempt]
            seen.append((results[0].result, attempt))
        assert seen == [("retrying", 1), ("retrying", 2), ("retrying", 3), ("retrying", 4), ("dead_letter", 5)]
        assert faults.armed() == {}  # every armed failure was consumed, by this row alone
        (row,) = await intents(app_conn, run)
        assert (row["attempts"], row["result"], row["delivered_at"]) == (5, "dead_letter", None)
        await move_clock(harness, 4000)
        assert await outbox.deliver(sweeper, sink, CHOSEN, tenants=[tenant]) == []  # a dead letter is never claimed

        # The crash window: the dead letter is recorded, its event not yet (deliver() never appends). The re-check
        # of the next tick appends it once, and only once.
        assert await failures(app_conn, run) == []
        assert await outbox.notify_dead_letters(sweeper, tenants=[tenant]) == [row["outbox_id"]]
        assert await outbox.notify_dead_letters(sweeper, tenants=[tenant]) == []
        (failed,) = await failures(app_conn, run)
        assert failed["outbox_id"] == str(row["outbox_id"]) and failed["code"] == outbox.DEAD_LETTER_CODE
        after = await run_view(app_conn, run)
        assert (after["state"], after["state_version"]) == (before["state"], before["state_version"])
        assert after["events"][:-1] == before["events"]  # one event more, notification.failed, nothing else
        lines.append(
            "R024 outcome SUCCEEDED, one intent; 5 sink failures on the database clock: retrying x4, then"
            " dead_letter; run state and events unchanged; the outcome replayed as mcp_exec and its event re-appended"
            " as app_definer added no intent;"
            " notification.failed appended once by the re-check after the result"
        )
    finally:
        await move_clock(harness, 0)
        if staged is not None:
            await purge_run(app_conn, staged.run)
        await purge_tenant(app_conn, tenant)


async def test_a_delivered_intent_is_recorded_once_and_logged_without_its_recipient(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="ops_sweeper.outbox")
    sweeper = await role_conn(Role.SWEEPER)
    tenant = await own_tenant(app_conn)
    staged: Outcome | None = None
    try:
        staged = await succeeded_run(app_conn, role_conn, tenant)
        results = await outbox.deliver(sweeper, outbox.LogSink(), CHOSEN, tenants=[tenant])
        assert [(r.result, r.attempts, r.recorded) for r in results] == [("delivered", 1, True)]
        (row,) = await intents(app_conn, staged.run)
        assert row["result"] == "delivered" and row["delivered_at"] is not None and row["attempts"] == 1
        assert await outbox.deliver(sweeper, outbox.LogSink(), CHOSEN, tenants=[tenant]) == []  # never again
        assert await outbox.notify_dead_letters(sweeper, tenants=[tenant]) == []
        assert str(row["outbox_id"]) in caplog.text and outbox.recipient_hash(ALEX) in caplog.text
        assert ALEX not in caplog.text
        lines.append("delivered: one attempt, delivered_at set, never claimed again; the log names a recipient hash")
    finally:
        if staged is not None:
            await purge_run(app_conn, staged.run)
        await purge_tenant(app_conn, tenant)


APPEND = "SELECT * FROM app._append_event(%s, %s, 'action.failed', 'destination', %s)"


class Hanging:
    """A sink that never answers: the test cancels the delivery's task while it waits here, as a dying sweeper would
    lose it. The claim's unit has committed and no result unit has started, so no database unit is cancelled."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()

    async def deliver(self, delivery: outbox.Delivery) -> None:
        self.entered.set()
        await asyncio.Event().wait()


async def kill_mid_delivery(sweeper: persistence.Conn, tenant: UUID, chosen: OutboxSettings) -> None:
    """Claim the tenant's due rows and lose the process during the first delivery: one attempt counted, no result."""
    sink = Hanging()
    task = asyncio.create_task(outbox.deliver(sweeper, sink, chosen, tenants=[tenant]))
    await asyncio.wait_for(sink.entered.wait(), timeout=10)  # waits on an Event, never on a database unit
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_a_crash_on_one_row_spares_the_rows_claimed_with_it(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    """Round 2, N1: the sink crashes on the middle row of a batch of three; the other two are delivered in the same
    tick, the crashing row costs exactly one attempt and is delivered after its backoff."""
    sweeper, harness, api = await role_conn(Role.SWEEPER), await role_conn(Role.TEST_HARNESS), await role_conn(Role.API)
    tenant = await own_tenant(app_conn)
    runs: list[UUID] = []
    try:
        for _ in range(3):
            _, _, run = await new_run(app_conn, tenant, api=api)
            runs.append(run)
            await app_conn.execute(APPEND, (tenant, run, Jsonb({"action_id": str(uuid4()), "reason": "expired"})))
        poison = runs[1]

        class CrashesOnOne:
            async def deliver(self, delivery: outbox.Delivery) -> None:
                if delivery.run_id == poison:
                    raise RuntimeError("the sink crashed on this row")

        results = await outbox.deliver(sweeper, CrashesOnOne(), CHOSEN, tenants=[tenant])
        assert sorted((r.run_id == poison, r.result, r.attempts) for r in results) == [
            (False, "delivered", 1),
            (False, "delivered", 1),
            (True, "retrying", 1),
        ]
        (row,) = await intents(app_conn, poison)
        assert (row["attempts"], row["result"], row["waiting"]) == (1, "retrying", True)  # behind its backoff
        await move_clock(harness, 400)
        results = await outbox.deliver(sweeper, outbox.LogSink(), CHOSEN, tenants=[tenant])
        assert [(r.run_id, r.result, r.attempts) for r in results] == [(poison, "delivered", 2)]
        lines.append(
            "crash: one row of three crashed the sink; the other two delivered, the crashed one after its backoff"
        )
    finally:
        await move_clock(harness, 0)
        for run in runs:
            await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


async def test_a_delivery_lost_with_its_sweeper_is_dead_lettered_at_its_cap(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    """Round 1, I1: a row whose sweeper dies during every delivery is bounded: once its attempts reached the cap and
    its last lease ran out, the next claim dead-letters it instead of claiming it, and the re-check announces it; a
    late result for that last attempt cannot overwrite the dead letter (round 2, N2)."""
    capped = OutboxSettings(backoff_base_seconds=60, max_attempts=2)
    sweeper, harness = await role_conn(Role.SWEEPER), await role_conn(Role.TEST_HARNESS)
    tenant = await own_tenant(app_conn)
    staged: Outcome | None = None
    try:
        staged = await succeeded_run(app_conn, role_conn, tenant)
        for attempt in (1, 2):
            await move_clock(harness, (capped.lease_seconds + 1) * (attempt - 1))
            await kill_mid_delivery(sweeper, tenant, capped)
            (row,) = await intents(app_conn, staged.run)
            assert (row["attempts"], row["result"]) == (attempt, None)
        await move_clock(harness, (capped.lease_seconds + 1) * 2)
        assert await outbox.deliver(sweeper, outbox.LogSink(), capped, tenants=[tenant]) == []  # never claimed again
        (row,) = await intents(app_conn, staged.run)
        assert (row["attempts"], row["result"], row["delivered_at"]) == (2, "dead_letter", None)
        late = functools.partial(outbox.record_result, row=row, result="delivered", chosen=capped, rng=lambda: 0.0)
        assert await in_tenant(sweeper, tenant, late) is False  # the dead letter stands
        assert await outbox.notify_dead_letters(sweeper, tenants=[tenant]) == [row["outbox_id"]]
        (failed,) = await failures(app_conn, staged.run)
        assert failed["outbox_id"] == str(row["outbox_id"])
        lines.append("killed at the cap: two lost deliveries, then dead-lettered by the claim and announced once")
    finally:
        await move_clock(harness, 0)
        if staged is not None:
            await purge_run(app_conn, staged.run)
        await purge_tenant(app_conn, tenant)


async def test_a_late_result_never_overwrites_a_newer_claim(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    """Review Focus 1 (round 1, M4): a delivery that outlived its lease reports after the row was claimed and delivered
    again; its result names attempt 1, the row is at attempt 2, so nothing is written."""
    sweeper, harness = await role_conn(Role.SWEEPER), await role_conn(Role.TEST_HARNESS)
    tenant = await own_tenant(app_conn)
    staged: Outcome | None = None
    try:
        staged = await succeeded_run(app_conn, role_conn, tenant)
        await kill_mid_delivery(sweeper, tenant, CHOSEN)  # attempt 1: claimed, no result
        (first,) = await intents(app_conn, staged.run)
        await move_clock(harness, CHOSEN.lease_seconds + 1)
        results = await outbox.deliver(sweeper, outbox.LogSink(), CHOSEN, tenants=[tenant])
        assert [(r.result, r.attempts) for r in results] == [("delivered", 2)]
        stale = {"outbox_id": first["outbox_id"], "attempts": 1}
        late = functools.partial(outbox.record_result, row=stale, result="retrying", chosen=CHOSEN, rng=lambda: 0.0)
        assert await in_tenant(sweeper, tenant, late) is False
        (row,) = await intents(app_conn, staged.run)
        assert (row["attempts"], row["result"]) == (2, "delivered") and row["delivered_at"] is not None
        lines.append("late result: attempt 1's result after attempt 2 was delivered wrote nothing")
    finally:
        await move_clock(harness, 0)
        if staged is not None:
            await purge_run(app_conn, staged.run)
        await purge_tenant(app_conn, tenant)

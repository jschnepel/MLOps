"""The model permit around the draft call (Plan H ruling 12, SA:203-205) and the slow fake drafter (R088), without a
database.

Catches: a backoff that does not double or exceeds 2 s, jitter that can drop to zero (two waiters hammering one row),
a permit kept after the block or after a lost lease cancelled the call (one stuck permit stops every draft for 95 s),
a permit taken or released by a loss during the back-off (review round 1, I2), a waiter that outlives its lease, and a
slow drafter that blocks the event loop.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import pytest
from ops_core import persistence
from ops_core.lease import Lease, LeaseLost
from ops_worker.drafting import FakeDraftGenerator
from ops_worker.permit import PERMIT_TTL_SECONDS, backoff, model_permit

from tests.plan_d.test_worker import EV, REQ

RUN = UUID(int=12)


class FakeConn:
    def __init__(self) -> None:
        self.units = 0

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        self.units += 1
        yield


def permits(monkeypatch: pytest.MonkeyPatch, answers: list[int | None]) -> list[tuple[str, Any]]:
    calls: list[tuple[str, Any]] = []

    async def take(_conn: Any, *, holder: str, run_id: UUID, ttl_seconds: int) -> int | None:
        calls.append(("take", (holder, run_id, ttl_seconds)))
        return answers.pop(0) if len(answers) > 1 else answers[0]

    async def release(_conn: Any, *, slot: int, holder: str) -> None:
        calls.append(("release", (slot, holder)))

    monkeypatch.setattr(persistence, "take_model_permit", take)
    monkeypatch.setattr(persistence, "release_model_permit", release)
    return calls


def lease(clock: list[float]) -> Lease:
    return Lease(run_id=RUN, owner="w:test", fence=1, lease_seconds=30, started=0.0, clock=lambda: clock[0])


def lose(held: Lease) -> None:
    """What the heartbeat thread does on a loss: record why, then cancel the effects in flight."""
    held.mark_lost("another owner took the lease")
    held.cancel_effects()


def test_the_backoff_doubles_to_two_seconds_with_jitter_in_the_upper_half() -> None:
    assert [backoff(i, lambda: 1.0) for i in range(6)] == [0.25, 0.5, 1.0, 2.0, 2.0, 2.0]
    assert [backoff(i, lambda: 0.0) for i in range(4)] == [0.125, 0.25, 0.5, 1.0]
    assert backoff(10_000, lambda: 1.0) == 2.0  # a long wait never overflows the doubling
    assert PERMIT_TTL_SECONDS == 95  # a draft's 90 s budget, both attempts, plus 5 s (BS:555; T19, Plan P ruling 7)


def test_the_permit_is_released_after_the_block_and_after_a_lost_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = permits(monkeypatch, [1])
    conn: Any = FakeConn()

    async def draft_then(lost: bool) -> None:
        held = lease([1.0])
        async with model_permit(conn, holder="w:test", lease=held) as slot:
            assert slot == 1
            if lost:  # the heartbeat loses the lease mid-draft and cancels the model call (ruling 19)
                asyncio.get_running_loop().call_later(0.01, lose, held)
                await held.effect(asyncio.Event().wait())

    asyncio.run(draft_then(False))
    with pytest.raises(LeaseLost):
        asyncio.run(draft_then(True))
    assert [name for name, _ in calls] == ["take", "release", "take", "release"]
    assert calls[0][1] == ("w:test", RUN, PERMIT_TTL_SECONDS) and calls[1][1] == (1, "w:test")


def test_a_loss_during_the_backoff_takes_and_keeps_no_permit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review round 1, I2: the take and the release are database units and are never cancelled; the back-off sleep
    is the one effect, so a loss there leaves nothing taken and nothing to release."""
    calls = permits(monkeypatch, [None])

    async def hang(_seconds: float) -> None:
        await asyncio.Event().wait()

    async def draft() -> None:
        held = lease([1.0])
        conn: Any = FakeConn()
        asyncio.get_running_loop().call_later(0.01, lose, held)
        async with model_permit(conn, holder="w:test", lease=held, sleep=hang):
            pass

    with pytest.raises(LeaseLost):
        asyncio.run(draft())
    assert [name for name, _ in calls] == ["take"]


def test_a_busy_permit_is_polled_with_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = permits(monkeypatch, [None, None, 1])
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    async def draft() -> None:
        conn: Any = FakeConn()
        async with model_permit(conn, holder="w:test", lease=lease([1.0]), sleep=sleep, rand=lambda: 1.0):
            pass

    asyncio.run(draft())
    assert waits == [0.25, 0.5] and [name for name, _ in calls] == ["take", "take", "take", "release"]


def test_a_lost_lease_stops_the_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = permits(monkeypatch, [None])
    clock = [1.0]

    async def sleep(_seconds: float) -> None:
        clock[0] = 26.0  # the lease's local deadline (0 + 30 - 5) passes while it waits

    async def draft() -> None:
        conn: Any = FakeConn()
        async with model_permit(conn, holder="w:test", lease=lease(clock), sleep=sleep):
            pass

    with pytest.raises(LeaseLost):
        asyncio.run(draft())
    assert [name for name, _ in calls] == ["take"]  # nothing to release: no permit was held


def test_the_fake_drafter_can_be_slow_without_blocking_the_loop() -> None:
    ticks = 0

    async def scenario() -> Any:
        nonlocal ticks

        async def count() -> None:
            nonlocal ticks
            while True:
                ticks += 1
                await asyncio.sleep(0.01)

        counter = asyncio.create_task(count())
        draft = await FakeDraftGenerator(delay_seconds=0.2).generate(REQ, EV)
        counter.cancel()
        return draft

    draft = asyncio.run(scenario())
    assert draft.kind == "proposal" and ticks >= 5  # the loop kept running while the drafter waited

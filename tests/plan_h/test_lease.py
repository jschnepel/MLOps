"""The Lease the event loop and the heartbeat thread share (Plan H rulings 10 and 18) and the lock statements every
lease check runs (SA:157), without a database.

Catches: a local deadline that is not the lease minus SA:195's five seconds, an effect allowed after the deadline or
after a loss, a renewal that does not move the deadline, a second loss reason overwriting the first, a re-fence that
a concurrent renewal would read as a takeover (T13 review note 2), a lock statement that compares expiry before its
lock instead of after it, a loss that cancels anything but the effects in flight or does not reach them from
another thread (review round 1, B1: a cancelled database unit would leave the loop connection in a transaction), and
a NOWAIT acquisition whose second lock statement (after the first-row INSERT) raises instead of answering busy
(review round 2, N2).
"""

import asyncio
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import psycopg
import pytest
from ops_core import persistence
from ops_core.lease import (
    LOCK_FOR_SHARE,
    LOCK_FOR_UPDATE,
    LOCK_FOR_UPDATE_NOWAIT,
    RELEASED,
    Busy,
    Lease,
    LeaseLost,
)

RUN = UUID(int=7)


def lease(clock: list[float], *, fence: int = 3) -> Lease:
    return Lease(run_id=RUN, owner="worker:test", fence=fence, lease_seconds=30, started=100.0, clock=lambda: clock[0])


def test_the_local_deadline_is_the_lease_minus_the_margin() -> None:
    held = lease([100.0])
    assert (held.deadline, held.renewed_at, held.held_since) == (125.0, 100.0, 100.0)  # 100 + 30 - 5 (SA:195)


def test_check_raises_past_the_deadline_and_after_a_loss() -> None:
    clock = [124.9]
    held = lease(clock)
    held.check()
    clock[0] = 125.0
    with pytest.raises(LeaseLost):
        held.check()
    assert held.lost == "local deadline passed"
    other = lease([100.0])
    assert other.mark_lost("the fence moved")
    with pytest.raises(LeaseLost):
        other.check()


def test_a_renewal_moves_the_deadline() -> None:
    clock = [126.0]
    held = lease(clock)
    held.renewed(110.0)  # the monotonic instant before the renewing statement (ruling 18)
    assert (held.deadline, held.renewed_at) == (135.0, 110.0)
    held.check()  # 126 < 135: alive again by the renewal


def test_the_first_loss_reason_stands() -> None:
    held = lease([100.0])
    assert held.mark_lost("the fence moved") and not held.mark_lost(RELEASED)
    assert held.lost == "the fence moved"


def test_a_refence_hands_the_new_fence_over() -> None:
    held = lease([100.0])
    held.begin_refence()
    assert held.refencing and held.fence_moved_by_owner(3)  # pending: a renewal that meets fence 4 retries
    held.end_refence(4)
    assert (held.fence, held.refencing) == (4, False)
    assert held.fence_moved_by_owner(3)  # settled: the renewal that used 3 retries with 4
    assert not held.fence_moved_by_owner(4)  # a mismatch against the current, settled fence is a loss
    held.begin_refence()
    held.end_refence(None)  # mark_unknown refused: the fence stays
    assert (held.fence, held.refencing) == (4, False)


@pytest.mark.parametrize("statement", [LOCK_FOR_UPDATE, LOCK_FOR_UPDATE_NOWAIT, LOCK_FOR_SHARE])
def test_the_lock_statements_compare_after_the_lock(statement: str) -> None:
    locking, comparing = statement.split(") SELECT", 1)
    assert locking.startswith("WITH l AS MATERIALIZED (") and "app.current_time()" not in locking
    assert "l.lease_until > app.current_time() AS live" in comparing  # evaluated once the CTE returned the row
    assert ("FOR UPDATE" in locking) != ("FOR SHARE" in locking)


def test_an_effect_starts_only_while_the_lease_is_held() -> None:
    clock = [124.9]
    held = lease(clock)
    started: list[str] = []

    async def call(name: str) -> str:
        started.append(name)
        return name

    async def scenario() -> None:
        assert await held.effect(call("first")) == "first"
        clock[0] = 125.0
        with pytest.raises(LeaseLost):
            await held.effect(call("late"))  # refused unstarted (and closed, so never "never awaited")

    asyncio.run(scenario())
    assert started == ["first"] and held.lost == "local deadline passed"


def test_a_loss_cancels_the_effect_in_flight_from_another_thread_and_nothing_else() -> None:
    held = lease([100.0])
    unit_finished: list[bool] = []
    cancelled: list[int] = []

    async def unit() -> None:  # stands for a database unit: never registered, so a loss cannot interrupt it
        await asyncio.sleep(0.05)
        unit_finished.append(True)

    def lose() -> None:  # what the heartbeat thread does (ruling 19 as amended in review round 1)
        held.mark_lost("another owner took the lease")
        cancelled.append(held.cancel_effects())

    async def scenario() -> None:
        running = asyncio.create_task(unit())
        effect = asyncio.create_task(held.effect(asyncio.Event().wait()))
        await asyncio.sleep(0)  # the effect is registered and waiting
        thread = threading.Thread(target=lose)
        thread.start()
        thread.join()
        with pytest.raises(LeaseLost):
            await effect
        await running

    asyncio.run(scenario())
    assert cancelled == [1] and unit_finished == [True] and held.lost == "another owner took the lease"


def test_stopping_the_worker_is_not_a_lost_lease() -> None:
    held = lease([100.0])

    async def scenario() -> None:
        caller = asyncio.create_task(held.effect(asyncio.Event().wait()))
        await asyncio.sleep(0)
        caller.cancel()  # the worker shuts down: the caller's own task is cancelled
        with pytest.raises(asyncio.CancelledError):
            await caller

    asyncio.run(scenario())
    assert held.lost is None


class EmptyCursor:
    async def fetchone(self) -> None:
        return None


class SecondLockHeld:
    """A connection on which the run has no lease row yet, and the lock taken after the first-row INSERT meets a row
    another transaction holds (a waking waiter or the first inserter's next unit got there first)."""

    def __init__(self) -> None:
        self.locks = 0

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        yield

    async def execute(self, query: str, params: Any = None) -> Any:
        if query.startswith("INSERT"):
            return None
        self.locks += 1
        if self.locks == 1:
            return EmptyCursor()
        raise psycopg.errors.LockNotAvailable('could not obtain lock on row in relation "run_lease"')


def test_a_held_row_after_the_first_insert_is_busy_too() -> None:
    conn: Any = SecondLockHeld()
    got = asyncio.run(persistence.acquire_lease(conn, run_id=RUN, owner="w:test", lease_seconds=30))
    assert got == Busy(locked=True) and conn.locks == 2  # deferred, as the first statement's 55P03 is (ruling 3)
    waiting: Any = SecondLockHeld()
    with pytest.raises(psycopg.errors.LockNotAvailable):  # only a waiting acquisition lets it through
        asyncio.run(persistence.acquire_lease(waiting, run_id=RUN, owner="w:test", lease_seconds=30, wait=True))

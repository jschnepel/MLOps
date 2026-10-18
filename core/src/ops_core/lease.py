"""The run lease as the worker holds it (AM-12, T13): one `Lease` per claimed job, shared by the event loop, which
starts effects only before the lease's local deadline, and the heartbeat thread, which renews the row and moves that
deadline (SA:193-199). The lock statements the loop and the thread both run live here, so the two compare owner,
fence and expiry the same way.

Every comparison is made after the row lock (SA:157): each statement is a MATERIALIZED CTE that takes the lock and an
outer SELECT that compares on `app.current_time()`. A WHERE clause on the locking SELECT itself is evaluated before a
lock wait and re-checked afterwards only if the row changed, so a lease that lapsed while the statement waited on a
renewal that then rolled back would pass (tests/e2e/test_leases_live.py measures the difference). Python never
compares database instants; the local deadline is the monotonic instant taken before the statement that acquired or
renewed the lease, plus the lease, minus the five seconds SA:195 keeps in hand.

A lost lease stops the job in two ways (ruling 19 as amended in review round 1, B1). An effect (an MCP call, a model
call, the model permit's back-off sleep) runs through `Lease.effect` as a child task registered on the lease, and
the heartbeat thread cancels exactly those (`cancel_effects`). A database unit is never registered and never
cancelled: a cancellation landing inside psycopg's BEGIN would leave the loop connection in a transaction that never
commits. A loss during a unit is caught by the unit's own fence check or by the next `fenced()` or `check()`.
"""

from __future__ import annotations

import asyncio
import enum
import threading
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

import psycopg
from psycopg.rows import DictRow

DEADLINE_MARGIN_SECONDS: Final = 5.0  # SA:195: stop starting effects at lease_until - 5 s
RELEASED: Final = "released"  # the end a lease meets when its job's final unit gives it back

_LOCK = (
    "WITH l AS MATERIALIZED (SELECT owner, fence, lease_until FROM app.run_lease WHERE run_id = %s {mode})"
    " SELECT l.owner, l.fence, l.lease_until = '-infinity' AS released,"
    " l.lease_until > app.current_time() AS live FROM l"
)
LOCK_FOR_UPDATE: Final = _LOCK.format(mode="FOR UPDATE")  # writes the row: acquisition, renewal, release (SA:191)
LOCK_FOR_UPDATE_NOWAIT: Final = _LOCK.format(mode="FOR UPDATE NOWAIT")  # the claim's acquisition (ruling 3)
LOCK_FOR_SHARE: Final = _LOCK.format(mode="FOR SHARE")  # every other writing unit (SA:176-184)
RENEW: Final = "UPDATE app.run_lease SET lease_until = app.current_time() + make_interval(secs => %s) WHERE run_id = %s"


class LeaseLost(Exception):
    """The run's lease is gone: another owner holds a newer fence, it expired, or its local deadline passed. The
    unit that raised it rolls back and the worker hands the job back (Plan H ruling 19)."""


@dataclass(frozen=True)
class Busy:
    """The run's lease could not be taken: `locked` when another transaction holds its row (SQLSTATE 55P03), else
    live under another claim. The job is deferred, never claimed (ruling 3)."""

    locked: bool


class Lease:
    """One held run lease. The event loop checks it before every effect; the heartbeat thread renews it; both go
    through one `threading.Lock`, so a re-fence and a renewal never see half of each other (T13 review note 2)."""

    def __init__(
        self,
        *,
        run_id: UUID,
        owner: str,
        fence: int,
        lease_seconds: int,
        started: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.run_id = run_id
        self.owner = owner
        self.lease_seconds = lease_seconds
        self.held_since = started  # the compute gate's start (ruling 17)
        self._clock = clock
        self._lock = threading.Lock()
        self._fence = fence
        self._deadline = started + lease_seconds - DEADLINE_MARGIN_SECONDS
        self._renewed_at = started
        self._refencing = False
        self._lost: str | None = None
        self._effects: dict[asyncio.Task[Any], asyncio.AbstractEventLoop] = {}
        self._effects_cancelled = False

    @property
    def fence(self) -> int:
        """The fence this owner writes under; it changes only through `end_refence`."""
        with self._lock:
            return self._fence

    @property
    def deadline(self) -> float:
        """The monotonic instant after which no effect may start (SA:195)."""
        with self._lock:
            return self._deadline

    @property
    def renewed_at(self) -> float:
        """The monotonic instant before the last acquiring or renewing statement."""
        with self._lock:
            return self._renewed_at

    @property
    def lost(self) -> str | None:
        """Why the lease ended (`RELEASED` after the final unit), or None while it is held."""
        with self._lock:
            return self._lost

    @property
    def refencing(self) -> bool:
        """True between `begin_refence` and `end_refence`."""
        with self._lock:
            return self._refencing

    def check(self) -> None:
        """Raise LeaseLost unless the lease is held and its local deadline is still ahead; called before every fenced
        unit, and by `effect` before every MCP call and model call (ruling 18)."""
        with self._lock:
            reason = self._why_not_held()
        if reason is not None:
            raise LeaseLost(reason)

    def _why_not_held(self) -> str | None:
        """Why nothing may start now, or None while the lease is held; the caller holds `_lock`."""
        if self._lost is None and self._clock() >= self._deadline:
            self._lost = "local deadline passed"
        return self._lost

    async def effect[T](self, call: Coroutine[Any, Any, T]) -> T:
        """Run one effect (an MCP call, a model call, the permit's back-off sleep; never a database unit) as a child
        task the heartbeat thread may cancel (ruling 19 as amended in review round 1, B1).

        The check and the registration happen under the lease's lock, so `cancel_effects` either sees the task or the
        task sees the loss; a refused `call` is closed unstarted. A cancellation by `cancel_effects`, in whatever form
        the call surfaces it (an MCP client may wrap it in an exception group), reaches the caller as LeaseLost; a
        cancellation of the caller's own task (the worker stopping) propagates unchanged.

        Raises:
            LeaseLost: the lease was lost or its local deadline passed, before the effect started or while it ran.
        """
        loop = asyncio.get_running_loop()
        with self._lock:
            reason = self._why_not_held()
            task = None if reason is not None else loop.create_task(call)
            if task is not None:
                self._effects[task] = loop
        if task is None:
            call.close()  # never started, so never awaited
            raise LeaseLost(reason)
        try:
            return await task
        except BaseException:  # re-raised as it came unless this lease's loss cancelled the effect
            current = asyncio.current_task()
            stopping = current is not None and current.cancelling() > 0
            with self._lock:
                cancelled_for_loss = self._effects_cancelled
            if cancelled_for_loss and not stopping:
                raise LeaseLost(self.lost or "run lease lost") from None
            raise
        finally:
            with self._lock:
                self._effects.pop(task, None)

    def cancel_effects(self) -> int:
        """Cancel every effect in flight, from any thread (the heartbeat calls it after `mark_lost`): each child task
        is cancelled on its own loop through `call_soon_threadsafe`. Database units are never registered here, so a
        loss never interrupts one. Returns how many effects it cancelled."""
        with self._lock:
            self._effects_cancelled = True
            effects = list(self._effects.items())
        for task, loop in effects:
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:  # that loop has already closed (shutdown): nothing is left to cancel
                pass
        return len(effects)

    def renewed(self, started: float) -> None:
        """A renewal that began at `started` (monotonic) committed: the deadline moves with it."""
        with self._lock:
            self._deadline = started + self.lease_seconds - DEADLINE_MARGIN_SECONDS
            self._renewed_at = started

    def mark_lost(self, reason: str) -> bool:
        """Record why the lease ended; True only for the call that recorded it (the first reason stands)."""
        with self._lock:
            if self._lost is not None:
                return False
            self._lost = reason
            return True

    def begin_refence(self) -> None:
        """The owner is about to move its own fence (`mark_unknown`, ruling 9): until `end_refence`, a renewal that
        meets another fence retries instead of declaring the lease lost (ruling 10)."""
        with self._lock:
            self._refencing = True

    def end_refence(self, fence: int | None) -> None:
        """Hand over the fence the bump committed (None when it was refused and the fence stayed)."""
        with self._lock:
            if fence is not None:
                self._fence = fence
            self._refencing = False

    def fence_moved_by_owner(self, used: int) -> bool:
        """After a renewal under fence `used` met another fence: True when the owner moved it itself (a re-fence is
        pending, or the shared fence already differs from `used`), so the renewal retries with the current fence."""
        with self._lock:
            return self._refencing or self._fence != used


class Renewal(enum.Enum):
    """What one renewal unit found (Plan H ruling 16)."""

    RENEWED = "renewed"  # owner and fence matched, the lease was live, lease_until moved on
    RELEASED = "released"  # the job's final unit gave the lease back: nothing left to renew
    MOVED = "moved"  # another owner or another fence holds the row
    EXPIRED = "expired"  # still this owner and fence, but the lease lapsed on the database clock


def renew(conn: psycopg.Connection[DictRow], lease: Lease, fence: int) -> Renewal:
    """One renewal unit on the heartbeat's own synchronous connection (SA:193-194, ruling 16): the lease row FOR
    UPDATE from the start (the unit writes it, SA:191), owner and fence compared, liveness read on the database clock
    after the lock, then `lease_until` moved on by one lease. `fence` is the value the caller read from the shared
    Lease before the call, so a mismatch can be told apart from the owner's own re-fence (ruling 10)."""
    with conn.transaction():
        row = conn.execute(LOCK_FOR_UPDATE, (lease.run_id,)).fetchone()
        if row is None or row["owner"] != lease.owner or row["fence"] != fence:
            return Renewal.MOVED
        if row["released"]:
            return Renewal.RELEASED
        if not row["live"]:
            return Renewal.EXPIRED
        conn.execute(RENEW, (lease.lease_seconds, lease.run_id))
    return Renewal.RENEWED

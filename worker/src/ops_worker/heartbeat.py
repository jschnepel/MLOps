"""The heartbeat thread (AM-12 SA:193-199, Plan H rulings 16-19): one daemon thread per worker process with its own
synchronous psycopg connection as role `worker`, renewing the run lease the event loop holds while the loop shows
signs of life and the compute budget lasts. A thread rather than a task, so a blocked event loop (DoD 3: 25 s) cannot
stop the renewal; gated, so a loop that is dead rather than busy, or a job past its budget, cannot keep a run (T13
review note 4).

Windows: the worker's event loop must be a SelectorEventLoop because psycopg's *async* connection refuses the
Proactor loop (Plan D ruling 23). This thread uses psycopg's *synchronous* connection, which never touches an event
loop, so that constraint does not apply to it.

When renewal fails (another owner or fence, an expired lease, a gate closing, or errors until the local deadline) the
thread marks the lease lost and cancels the job's effects in flight (`Lease.cancel_effects`, through
`loop.call_soon_threadsafe`; ruling 19 as amended in review round 1, B1). It never cancels a database unit: a loss
during one is caught by the next fence check. The loop then revokes the job's handles and hands the job back. A
broken connection is reopened on the next tick (ruling 16).
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable

import psycopg
from ops_core.lease import Lease, Renewal, renew
from ops_core.settings import LeaseSettings, Postgres
from psycopg.rows import DictRow, dict_row

log = logging.getLogger("ops_worker.heartbeat")
TICK_SECONDS = 1.0  # how often the thread looks at the lease; it renews every `heartbeat_seconds`
STAMP_SECONDS = 1.0  # how often a live event loop stamps its liveness

SyncConn = psycopg.Connection[DictRow]
Renewer = Callable[[SyncConn, Lease, int], Renewal]


class Liveness:
    """The event loop's last sign of life: a monotonic instant the loop stamps and the thread reads."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._stamped = clock()

    def stamp(self) -> None:
        """Called on the event loop: it is alive now."""
        with self._lock:
            self._stamped = self._clock()

    def age(self, now: float) -> float:
        """Seconds since the loop last stamped, as of `now` on the same monotonic clock."""
        with self._lock:
            return now - self._stamped


async def keep_stamping(liveness: Liveness, stop: asyncio.Event) -> None:
    """The loop's half of the liveness gate (ruling 17): a stamp every second until stopped. A blocked loop stops
    stamping, which is exactly what the thread measures."""
    while not stop.is_set():
        liveness.stamp()
        try:
            await asyncio.wait_for(stop.wait(), timeout=STAMP_SECONDS)
        except TimeoutError:
            pass


def connector(pg: Postgres) -> Callable[[], SyncConn]:
    """How the thread opens its connection: role `worker` through the same conninfo builder as the loop's (it pins
    `-c timezone=UTC`), autocommit with explicit units, a 5 s connect timeout (a server that accepts and never answers
    must not hold the tick past the local deadline), TCP keepalives (an idle half-open connection is noticed in about
    20 s on Linux, about 60 s on Windows, where libpq ignores `keepalives_count`), and 5 s lock and statement timeouts
    so one renewal never waits on the server for ever (review round 2, m3). Neither keepalives nor the statement
    timeout bound a renewal sent to a peer that vanished (TCP retransmission does); the local deadline does: the
    loop's own `check()` stops the job then, and the renewal error becomes a loss at the next tick past it. Every
    failure here is a psycopg error, which the tick treats as transient: the connection is reopened, and the lease is
    lost only once its local deadline has passed. The two timeouts are SET after connecting because the conninfo's
    `options` already carries the time zone; a failed SET closes the new connection (review round 3)."""

    def connect() -> SyncConn:
        conn = psycopg.connect(
            pg.conninfo(),
            autocommit=True,
            row_factory=dict_row,
            connect_timeout=5,
            keepalives=1,
            keepalives_idle=10,
            keepalives_interval=5,
            keepalives_count=2,
        )
        try:
            conn.execute("SET lock_timeout = '5s'")  # SET takes no bind parameter; the values are constants
            conn.execute("SET statement_timeout = '5s'")
        except BaseException:  # re-raised: a failed SET must not leave the connection open
            conn.close()
            raise
        return conn

    return connect


class Heartbeat(threading.Thread):
    """Renews the lease the event loop holds (rulings 16-19); idle while it holds none."""

    def __init__(
        self,
        *,
        connect: Callable[[], SyncConn],
        settings: LeaseSettings,
        liveness: Liveness,
        clock: Callable[[], float] = time.monotonic,
        renewer: Renewer = renew,
        tick_seconds: float = TICK_SECONDS,
    ) -> None:
        super().__init__(name="lease-heartbeat", daemon=True)
        self._connect = connect
        self._settings = settings
        self._liveness = liveness
        self._clock = clock
        self._renew = renewer
        self._tick_seconds = tick_seconds
        self._lock = threading.Lock()
        self._held: Lease | None = None
        self._stopping = threading.Event()
        self._conn: SyncConn | None = None
        self.renewals = 0  # successful renewals, for the logs and the live tests
        self.max_loop_age = 0.0  # the longest event-loop silence a tick saw, for the DoD-3 evidence (review M4)

    def hold(self, lease: Lease) -> None:
        """Start renewing `lease`; on a loss the thread cancels the lease's effects in flight."""
        with self._lock:
            self._held = lease

    def drop(self, lease: Lease) -> None:
        """Stop renewing `lease` (its job ended or it was lost); a lease held after it is untouched."""
        with self._lock:
            if self._held is lease:
                self._held = None

    def stop(self) -> None:
        """Ask the thread to end after its current tick."""
        self._stopping.set()

    def run(self) -> None:
        """Tick until stopped, then close the connection."""
        try:
            while not self._stopping.wait(self._tick_seconds):
                try:
                    self.tick()
                except Exception:  # the one catch-all here: a dead thread would silently stop every renewal
                    log.exception("heartbeat tick failed; the next tick tries again")
        finally:
            self._close()

    def tick(self) -> None:
        """One look at the held lease: a closed gate is a loss; otherwise renew when a heartbeat is due."""
        with self._lock:
            lease = self._held
        if lease is None:
            return
        if lease.lost is not None:
            self.drop(lease)
            return
        now = self._clock()
        silence = self._liveness.age(now)
        self.max_loop_age = max(self.max_loop_age, silence)
        if silence >= self._settings.loop_stall_seconds:
            self._lose(lease, "event loop stalled")
            return
        if now - lease.held_since >= self._settings.compute_budget_seconds:
            self._lose(lease, "compute budget spent")
            return
        if now - lease.renewed_at < self._settings.heartbeat_seconds:
            return
        fence = lease.fence
        try:
            verdict = self._renew(self._connection(), lease, fence)
        except psycopg.Error:
            log.warning("renewing the lease of run %s failed; the connection is reopened next tick", lease.run_id)
            self._close()
            if now >= lease.deadline:
                self._lose(lease, "renewals failed until the local deadline")
            return
        if verdict is Renewal.RENEWED:
            lease.renewed(now)  # `now` was taken before the renewing statement (ruling 18)
            self.renewals += 1
        elif verdict is Renewal.RELEASED:
            self.drop(lease)
        elif verdict is Renewal.MOVED and lease.fence_moved_by_owner(fence):
            return  # the owner re-fenced (mark_unknown): the next tick renews under the new fence (ruling 10)
        else:
            self._lose(lease, "another owner took the lease" if verdict is Renewal.MOVED else "the lease expired")

    def _lose(self, lease: Lease, reason: str) -> None:
        if lease.mark_lost(reason):
            cancelled = lease.cancel_effects()  # effects only; a database unit in progress runs to its end
            log.warning("run %s: lease lost (%s); %d effect(s) cancelled", lease.run_id, reason, cancelled)
        self.drop(lease)

    def _connection(self) -> SyncConn:
        if self._conn is None or self._conn.closed or self._conn.broken:
            self._conn = self._connect()
        return self._conn

    def _close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except psycopg.Error:
                pass  # closing a broken connection may fail; the next tick opens a fresh one
            self._conn = None

"""The heartbeat thread's decisions with a fake clock and a scripted renewer (Plan H rulings 10, 16-19), plus one run
of the real thread against a real event loop.

Catches: a renewal more or less often than once per heartbeat, a loop blocked for 25 s that loses its lease (DoD 3), a
dead loop or a job past its 90 s budget that keeps renewing (T13 review note 4), a renewal that meets the owner's own
re-fence and cancels a healthy job (review note 2), another owner's fence or an expired lease that is not a loss, a
transient error that loses the lease before the local deadline or never loses it after (judged on a clock reading
taken before a failed call that spent its timeouts, or skipped by the tick's catch-all: final review, M1), a released
lease whose effects are cancelled, and a cancellation that cannot cross from the thread to the effect on the event
loop.
"""

import asyncio
from typing import Any
from uuid import UUID

import psycopg
import pytest
from ops_core.lease import DEADLINE_MARGIN_SECONDS, Lease, LeaseLost, Renewal
from ops_core.settings import RENEWAL_MARGIN_SECONDS, LeaseSettings
from ops_worker.heartbeat import TICK_SECONDS, Heartbeat, Liveness

RUN = UUID(int=11)


class Clock:
    """A monotonic clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class FakeConn:
    closed = False
    broken = False

    def close(self) -> None:
        self.closed = True


class Renewer:
    """Answers each renewal from a script (a Renewal, an exception to raise, or a callable that returns one); the
    last step repeats. Records the fence of every call."""

    def __init__(self, *script: Any) -> None:
        self.script = list(script)
        self.fences: list[int] = []

    def __call__(self, _conn: Any, _lease: Lease, fence: int) -> Renewal:
        self.fences.append(fence)
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(step, BaseException):
            raise step
        if callable(step) and not isinstance(step, Renewal):
            return step()
        return step


class CountingLease(Lease):
    """A Lease that counts how often the heartbeat cancels its effects."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.cancels = 0

    def cancel_effects(self) -> int:
        self.cancels += 1
        return super().cancel_effects()


class Setup:
    def __init__(self, *script: Any) -> None:
        self.clock = Clock()
        self.liveness = Liveness(self.clock)
        self.renewer = Renewer(*script)
        self.connects = 0
        self.heartbeat = Heartbeat(
            connect=self.connect,
            settings=LeaseSettings(),  # the real defaults: the clock is fake, so nothing waits
            liveness=self.liveness,
            clock=self.clock,
            renewer=self.renewer,
        )
        self.lease = CountingLease(run_id=RUN, owner="w:test", fence=3, lease_seconds=30, started=0.0, clock=self.clock)
        self.heartbeat.hold(self.lease)

    @property
    def cancels(self) -> int:
        """How often the thread cancelled the lease's effects (once per loss)."""
        return self.lease.cancels

    def connect(self) -> Any:
        self.connects += 1
        return FakeConn()

    def at(self, now: float, *, alive: bool = True) -> None:
        """Move the clock, let a live loop stamp, and tick once."""
        self.clock.now = now
        if alive:
            self.liveness.stamp()
        self.heartbeat.tick()


def test_the_settings_margin_is_the_deadline_margin_plus_one_tick() -> None:
    # settings.py keeps its own copy so it imports nothing from the worker (review round 2, m4); this pins the copy.
    assert RENEWAL_MARGIN_SECONDS == DEADLINE_MARGIN_SECONDS + TICK_SECONDS


def test_it_renews_once_per_heartbeat() -> None:
    s = Setup(Renewal.RENEWED)
    for now in (5.0, 10.0, 15.0, 20.0):
        s.at(now)
    assert s.renewer.fences == [3, 3] and s.heartbeat.renewals == 2
    assert (s.lease.renewed_at, s.lease.deadline) == (20.0, 45.0)  # ruling 18: the instant before the renewal + 25


def test_a_blocked_loop_keeps_its_lease_until_the_stall_gate_then_loses_it() -> None:
    s = Setup(Renewal.RENEWED)
    for now in (10.0, 20.0, 25.0, 27.9):  # the loop stamped at 0 and is blocked since (DoD 3: 25 s keeps the lease)
        s.at(now, alive=False)
    assert s.heartbeat.renewals == 2 and s.cancels == 0 and s.lease.lost is None
    assert s.heartbeat.max_loop_age == 27.9  # the longest silence it saw, for the DoD-3 evidence line
    s.at(28.0, alive=False)  # OPS_LOOP_STALL_SECONDS
    assert (s.lease.lost, s.cancels) == ("event loop stalled", 1)
    s.at(40.0, alive=False)
    assert s.cancels == 1 and s.heartbeat.renewals == 2  # dropped: no second cancel, no renewal for a lost lease


def test_the_compute_budget_closes_the_gate() -> None:
    s = Setup(Renewal.RENEWED)
    for now in range(10, 90, 10):
        s.at(float(now))
    assert s.heartbeat.renewals == 8 and s.lease.lost is None
    s.at(90.0)  # OPS_COMPUTE_BUDGET_SECONDS since the claim
    assert (s.lease.lost, s.cancels) == ("compute budget spent", 1)


def test_a_renewal_that_meets_its_own_refence_retries() -> None:
    s = Setup(Renewal.MOVED, Renewal.RENEWED)
    s.lease.begin_refence()  # mark_unknown is running: its bump may land before this renewal
    s.at(10.0)
    assert s.cancels == 0 and s.lease.lost is None
    s.lease.end_refence(4)
    s.at(11.0)  # still due: the retry renews under the new fence
    assert s.renewer.fences == [3, 4] and s.heartbeat.renewals == 1

    def bump_committed() -> Renewal:  # the hand-over lands between the thread's read of fence 3 and its verdict
        settled.lease.end_refence(5)
        return Renewal.MOVED

    settled = Setup(bump_committed, Renewal.RENEWED)
    settled.at(10.0)
    assert settled.cancels == 0
    settled.at(11.0)
    assert settled.renewer.fences == [3, 5] and settled.heartbeat.renewals == 1


@pytest.mark.parametrize(
    ("verdict", "reason"),
    [(Renewal.MOVED, "another owner took the lease"), (Renewal.EXPIRED, "the lease expired")],
)
def test_another_owners_fence_or_an_expired_lease_is_a_loss(verdict: Renewal, reason: str) -> None:
    s = Setup(verdict)
    s.at(10.0)
    assert (s.lease.lost, s.cancels) == (reason, 1)


def test_transient_errors_are_retried_until_the_deadline() -> None:
    lost_connection = psycopg.OperationalError("server closed the connection")
    timed_out = psycopg.errors.QueryCanceled("canceling statement due to statement timeout")  # review round 2, m3
    s = Setup(lost_connection, timed_out, Renewal.RENEWED)
    s.at(10.0)
    s.at(11.0)
    assert s.lease.lost is None and s.cancels == 0
    s.at(12.0)
    assert s.heartbeat.renewals == 1 and s.connects == 3  # reopened after each failure (ruling 16)
    s.renewer.script = [lost_connection]
    s.at(22.0)
    assert s.lease.lost is None  # the deadline is 12 + 25
    s.at(37.0)
    assert (s.lease.lost, s.cancels) == ("renewals failed until the local deadline", 1)


def test_a_renewal_that_fails_past_the_deadline_is_a_loss_at_once() -> None:
    """Final review, M1: the failed call may spend its 5 s timeouts, so the deadline is judged on a reading taken after
    it. Judged on the reading taken before it, a renewal started at 22 that fails at 27 (deadline 25) would keep the
    lease for another tick, and under repeated timeouts for several."""
    s = Setup(Renewal.RENEWED)

    def times_out() -> Renewal:
        s.clock.now = 27.0  # the statement timeout spent five seconds
        raise psycopg.errors.QueryCanceled("canceling statement due to statement timeout")

    s.renewer.script = [times_out]
    s.at(22.0)
    assert (s.lease.lost, s.cancels) == ("renewals failed until the local deadline", 1)


def test_an_unexpected_tick_error_is_a_loss_past_the_deadline() -> None:
    """Final review, M1: an error that is not a psycopg error reaches the thread's catch-all, which logs it, keeps the
    thread alive and applies the same deadline rule."""
    s = Setup(RuntimeError("a bug in the renewal"))
    for now in (10.0, 20.0):
        s.clock.now = now
        s.liveness.stamp()
        s.heartbeat.guarded_tick()  # never raises
    assert s.lease.lost is None and s.cancels == 0  # before the deadline (0 + 25): the next tick tries again
    s.clock.now = 25.0
    s.liveness.stamp()
    s.heartbeat.guarded_tick()
    assert (s.lease.lost, s.cancels) == ("heartbeat ticks failed until the local deadline", 1)


def test_a_released_lease_is_dropped_quietly() -> None:
    s = Setup(Renewal.RELEASED)
    s.at(10.0)
    s.at(20.0)
    assert s.cancels == 0 and s.renewer.fences == [3]  # dropped after the first answer


def test_the_thread_cancels_the_effect_on_the_loop_and_stops() -> None:
    s = Setup(Renewal.MOVED)
    conn = FakeConn()
    thread = Heartbeat(
        connect=lambda: conn,
        settings=LeaseSettings(),
        liveness=s.liveness,
        clock=s.clock,
        renewer=s.renewer,
        tick_seconds=0.01,
    )

    async def scenario() -> None:
        thread.hold(s.lease)
        thread.start()
        s.clock.now = 10.0
        s.liveness.stamp()
        with pytest.raises(LeaseLost):  # the effect in flight, cancelled from the thread (ruling 19, round 1 B1)
            await asyncio.wait_for(s.lease.effect(asyncio.Event().wait()), timeout=2)

    asyncio.run(scenario())
    thread.stop()
    thread.join(timeout=2)
    assert not thread.is_alive() and conn.closed and s.lease.lost == "another owner took the lease"

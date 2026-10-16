"""The T14 transactions in the published lock order (Plan I ruling 22): each one named, in the order, and the outbox
always after the events it belongs to and never before runs.

Catches: a T14 unit that disappears from the documented list (the order would then say nothing about it), and a
delivery unit that would take runs after outbox, the deadlock SA:188 rules out by keeping notification.failed in a
transaction of its own.
"""

from ops_core import locking

T14_UNITS = (
    "event append with notification intent (_append_event)",
    "sweeper outbox claim (outbox.deliver)",
    "sweeper outbox result (outbox.deliver)",
    "sweeper notification.failed (outbox.notify_dead_letters)",
    "sweeper wake-up re-arm (wakeups.sweep)",
    "sweeper maintenance purge (wakeups.purge_maintenance)",
    "sweeper deliver_outbox and sweep_wakeups job records",
)


def test_every_t14_unit_is_documented_and_ordered() -> None:
    for unit in T14_UNITS:
        assert locking.follows_order(locking.OBSERVED_UNITS[unit]), unit


def test_no_unit_takes_runs_after_the_outbox() -> None:
    for unit, entries in locking.OBSERVED_UNITS.items():
        if "outbox" in entries and "runs" in entries:
            assert entries.index("runs") < entries.index("outbox"), unit
    assert locking.rank("events") < locking.rank("outbox") < locking.rank("jobs:finish")
    # The announcement's advisory lock comes before every row lock its unit takes (round 1, M5).
    assert locking.rank("advisory:notification") < locking.rank("runs")

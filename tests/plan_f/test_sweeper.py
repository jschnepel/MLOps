"""The sweeper's pure decisions (ruling 13): which subjects a sync deactivates, the minute bucket of the maintenance
job, and the readiness rule (fresh only while the last successful sync is younger than 120 s).

Catches: a user absent from the listing left active (deleted users keep authority), an enabled user deactivated, a
subject of another issuer touched, a readiness that reports ready before the first sync, and a bucket that skips.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from ops_core.jobs import JobType, dedup_key
from ops_sweeper import sync
from ops_sweeper.main import fresh, minute_bucket

ALEX = UUID("2fc05986-c7ec-544c-b628-fdb112bbf18a")
SAM = UUID("03f7eb09-e18d-5f33-bf75-12c57d5aaa54")
LEE = UUID("abcc1200-6791-57ab-87b5-9392d356b512")


def test_plan_deactivates_disabled_and_deleted_subjects_only() -> None:
    users = {ALEX: True, SAM: False, uuid4(): True}
    assert sync.plan([ALEX, SAM, LEE], users) == frozenset({SAM, LEE})  # SAM disabled, LEE absent (deleted)
    assert sync.plan([ALEX], users) == frozenset()
    assert sync.plan([], users) == frozenset()


def test_minute_bucket_feeds_the_dedup_key_of_sa_504() -> None:
    at = datetime(2026, 10, 9, 8, 30, 59, tzinfo=UTC)
    assert minute_bucket(at) == "2026-10-09T08:30"
    assert dedup_key(JobType.SYNC_MEMBERSHIPS, minute_bucket=minute_bucket(at)) == "sync_memberships:2026-10-09T08:30"
    assert minute_bucket(datetime(2026, 10, 9, 8, 31, 0, tzinfo=UTC)) == "2026-10-09T08:31"


def test_listing_guard_counts_absent_subjects_only() -> None:
    five = [uuid4() for _ in range(5)]
    assert not sync.refuse(five, {s: True for s in five})
    assert not sync.refuse(five, {s: False for s in five})  # all explicitly disabled: affirmative, never refused
    assert not sync.refuse(five, {s: True for s in five[2:]})  # two absent of five: under the floor
    assert sync.refuse(five, {s: True for s in five[3:]})  # three absent of five: over half and at the floor
    assert sync.refuse(five, {})  # nothing listed
    assert not sync.refuse([five[0]], {})  # a one-user realm whose user left: under the floor, deactivated
    assert not sync.refuse([], {})
    assert sync.plan([ALEX, SAM, LEE], {}) == frozenset({ALEX, SAM, LEE})  # plan is pure; the guard is the writer's


def test_fresh_rule() -> None:
    now = 1_000_000.0
    assert not fresh(None, now)
    assert fresh(now - 119, now) and not fresh(now - 121, now)

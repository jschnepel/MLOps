"""The sweeper's pure decisions (ruling 13): which subjects a sync deactivates, the minute bucket of the maintenance
job, and the readiness rule (fresh only while the last successful sync is younger than 120 s); then `run_sync` with the
database replaced: confirmed absences and the one-shot override (final review M1, M2).

Catches: a user absent from the listing left active (deleted users keep authority), an enabled user deactivated, a
subject of another issuer touched, a readiness that reports ready before the first sync, a bucket that skips, a user
deactivated because a paging race hid them, and an override that outlives its first sync.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from ops_core.jobs import JobType, dedup_key
from ops_core.keycloak_admin import AdminUnavailable
from ops_sweeper import main, sync
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


@dataclass
class FakeAdmin:
    """The admin client: a fixed listing, per-subject answers for `enabled`, an outage switch, the subjects asked."""

    listing: dict[UUID, bool]
    lookups: dict[UUID, bool] = field(default_factory=dict)
    unavailable: bool = False
    asked: list[UUID] = field(default_factory=list)

    async def list_enabled(self) -> dict[UUID, bool]:
        """The listing as configured."""
        return dict(self.listing)

    async def enabled(self, subject: UUID) -> bool:
        """The configured answer (False for an unknown subject, as a 404 is), or AdminUnavailable."""
        self.asked.append(subject)
        if self.unavailable:
            raise AdminUnavailable("down")
        return self.lookups.get(subject, False)


@pytest.fixture
def sweep(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """`run_sync` with the database replaced: the active subjects are fixed, the sync records what it was given."""
    seen: dict[str, Any] = {"active": frozenset({ALEX, SAM, LEE}), "calls": []}

    async def active_subjects(_conn: Any, _issuer: str) -> frozenset[UUID]:
        return frozenset(seen["active"])

    async def sync_memberships(_conn: Any, *, issuer: str, users: Any, allow_mass: bool = False) -> sync.SyncResult:
        seen["calls"].append({"users": dict(users), "allow_mass": allow_mass})
        if not allow_mass and sync.refuse(seen["active"], users):
            raise sync.MassDeactivation("refused")
        return sync.SyncResult(checked=len(seen["active"]), deactivated=len(sync.plan(seen["active"], users)))

    monkeypatch.setattr(sync, "active_subjects", active_subjects)
    monkeypatch.setattr(sync, "sync_memberships", sync_memberships)
    return seen


def deps_with(admin: FakeAdmin, *, allow_mass: bool = False) -> main.Deps:
    """A Deps whose connection is never touched (the sync functions are replaced) and whose admin is the fake."""
    no_conn: Any = None
    fake_admin: Any = admin
    return main.Deps(
        conn=no_conn,
        admin=fake_admin,
        issuer="http://localhost:18080/realms/ops-dev",
        tick_seconds=30.0,
        worker_name="sweeper:test",
        allow_mass=allow_mass,
    )


@pytest.mark.asyncio
async def test_absences_are_confirmed_before_they_deactivate(sweep: dict[str, Any]) -> None:
    """Final review M2: LEE skipped by a paging race is kept; SAM, really gone (404), is deactivated."""
    admin = FakeAdmin(listing={ALEX: True}, lookups={LEE: True})
    deps = deps_with(admin)
    assert await main.run_sync(deps) is True and deps.last_sync_at is not None
    assert sorted(admin.asked) == sorted([SAM, LEE])  # only the absent subjects are asked
    assert sweep["calls"][-1]["users"] == {ALEX: True, SAM: False, LEE: True}


@pytest.mark.asyncio
async def test_a_failed_confirmation_stamps_nothing(sweep: dict[str, Any], caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="ops_sweeper")
    deps = deps_with(FakeAdmin(listing={ALEX: True, SAM: True}, unavailable=True))
    assert await main.run_sync(deps) is False and deps.last_sync_at is None
    assert not sweep["calls"] and "membership sync skipped" in caplog.text


@pytest.mark.asyncio
async def test_a_listing_the_guard_refuses_is_not_confirmed_away(sweep: dict[str, Any]) -> None:
    """A wrong realm 404s every lookup; confirming would turn the guard's absences into affirmative disables."""
    admin = FakeAdmin(listing={uuid4(): True})
    assert await main.run_sync(deps_with(admin)) is False
    assert not admin.asked and sweep["calls"][-1]["users"] == admin.listing


class PurgeConn:
    """A connection that records the purge's statements and answers each DELETE with a fixed rowcount."""

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.in_transaction = False

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        self.in_transaction = True
        yield
        self.in_transaction = False

    async def execute(self, statement: str) -> Any:
        assert self.in_transaction  # the four deletes commit together
        self.statements.append(statement)
        return type("Cursor", (), {"rowcount": len(self.statements)})()


@pytest.mark.asyncio
async def test_the_purge_covers_the_idempotency_records() -> None:
    """Plan G ruling 7: expired records leave with the other three tables, on the application clock."""
    conn = PurgeConn()
    as_conn: Any = conn  # the purge needs only transaction() and execute()
    counts = await sync.purge_expired(as_conn)
    assert counts == {"sessions": 1, "login_state": 2, "logout_jti": 3, "idempotency_request": 4}
    assert conn.statements[-1] == "DELETE FROM app.idempotency_request WHERE expires_at < app.current_time()"


@pytest.mark.asyncio
async def test_the_override_covers_the_first_successful_sync_only(
    sweep: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    """Final review M1: OPS_SYNC_ALLOW_MASS_DEACTIVATION=1 is one-shot, not the process's lifetime."""
    caplog.set_level(logging.INFO, logger="ops_sweeper")
    admin = FakeAdmin(listing={})
    deps = deps_with(admin, allow_mass=True)
    assert await main.run_sync(deps) is True and sweep["calls"][-1]["allow_mass"] is True
    assert deps.allow_mass is False and "mass-deactivation override consumed" in caplog.text
    assert await main.run_sync(deps) is False  # the same broken listing is refused again
    main.consume_override(deps)  # idempotent once cleared
    assert deps.allow_mass is False and caplog.text.count("override consumed") == 1

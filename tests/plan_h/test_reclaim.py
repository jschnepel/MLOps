"""The sweeper's lease reclaim (Plan H ruling 11, erratum 49), without a database: what the statement hands back and
that every tick runs it.

Catches: a reclaim that touches finished jobs, unclaimed jobs or the sweeper's own maintenance rows (no run), one that
compares the lease on anything but the application clock, and a tick that skips the reclaim when Keycloak is down
(a dead worker's run would then stay claimed for as long as the identity provider is out).
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest
from ops_sweeper import leases, main, sync


class FakeCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class FakeConn:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.statements: list[str] = []
        self.in_transaction = False

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        self.in_transaction = True
        yield
        self.in_transaction = False

    async def execute(self, statement: str, params: Any = None) -> FakeCursor:
        assert self.in_transaction
        self.statements.append(statement)
        return FakeCursor(self.rows)


def test_the_reclaim_hands_back_only_claimed_unfinished_run_jobs_of_dead_leases() -> None:
    job = uuid4()
    conn: Any = FakeConn([{"id": job}])
    assert asyncio.run(leases.reclaim(conn)) == [job]
    (statement,) = conn.statements
    assert statement.startswith("UPDATE app.jobs j SET claimed_by = NULL, claimed_at = NULL")
    for condition in (
        "j.done_at IS NULL",
        "j.claimed_at IS NOT NULL",
        "j.run_id IS NOT NULL",  # maintenance rows carry no run and are never reclaimed
        "NOT EXISTS (SELECT 1 FROM app.run_lease l WHERE l.run_id = j.run_id AND l.lease_until > app.current_time())",
    ):
        assert condition in statement, condition
    assert "available_at" not in statement  # the sweeper holds no UPDATE on it; the job is due already


def test_the_tick_reclaims_even_when_the_sync_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def failed_sync(_deps: Any) -> bool:
        calls.append("sync")
        return False

    async def purge(_conn: Any) -> dict[str, int]:
        calls.append("purge")
        return {}

    async def reclaim(_conn: Any) -> list[Any]:
        calls.append("reclaim")
        return [uuid4()]

    async def deliver_outbox(_deps: Any) -> None:
        calls.append("outbox")

    async def sweep_wakeups(_deps: Any) -> None:
        calls.append("wakeups")

    async def expire_proposals(_deps: Any) -> None:
        calls.append("expiry")

    monkeypatch.setattr(main, "run_sync", failed_sync)
    monkeypatch.setattr(main, "expire_proposals", expire_proposals)  # T21: between the reclaim and the wake-ups
    monkeypatch.setattr(sync, "purge_expired", purge)
    monkeypatch.setattr(leases, "reclaim", reclaim)
    monkeypatch.setattr(main, "deliver_outbox", deliver_outbox)
    monkeypatch.setattr(main, "sweep_wakeups", sweep_wakeups)
    none: Any = None
    deps = main.Deps(conn=none, admin=none, issuer="iss", tick_seconds=30.0, worker_name="sweeper:test")
    asyncio.run(main.tick(deps))
    # T14's work runs whether or not the sync did, the wake-up sweep before the delivery (round 1, I1).
    assert calls == ["sync", "purge", "reclaim", "expiry", "wakeups", "outbox"]

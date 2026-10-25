"""T13 live (OPS_LIVE=1): the heartbeat thread at the real defaults (30 s lease, 10 s heartbeat, 28 s stall gate, 90 s
budget) keeps a run's lease through a blocked event loop and through a drafter slower than the lease, and a forced
renewal failure cancels the in-flight call and revokes the job's handle (R088, DoD 3; Plan H rulings 16-20); the model
permit is held exactly around the draft call (ruling 12).

The three DoD tests carry `slow_live` (about 30, 40 and 15 s); `check.py --profile test` runs them like every other
live test. Each runs the worker's own path (`main.run_job` over `handlers.handle`) on a role-`worker` connection with a
scripted MCP caller, so no skeleton process is needed. Evidence: reports/leases/t13-heartbeat.txt.

Catches: a heartbeat that runs on the event loop (a 25 s block would starve it and lose the lease), a lease lost to a
long model call, a renewal failure that leaves the call running or its handle live, a job failed rather than handed
back on a lost lease, and a model permit held past the draft or never taken. The first test records the longest loop
silence the thread saw, so the margin to the 28 s stall gate is in the evidence (review round 1, M4).
"""

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from ops_core import persistence, settings
from ops_core.lease import RELEASED
from ops_core.settings import Role
from ops_worker import handlers, main
from ops_worker.drafting import FakeDraftGenerator
from ops_worker.heartbeat import STAMP_SECONDS, TICK_SECONDS, Heartbeat, Liveness, connector, keep_stamping

from tests.e2e.conftest import expire_lease, lease_for, purge_run, purge_tenant
from tests.e2e.test_migrations_and_persistence import new_run
from tests.e2e.test_worker_live import ScriptedMcp

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
EVIDENCE = Path("reports/leases/t13-heartbeat.txt")
EXPECTED_LINES = 4  # one per test
BLOCK_SECONDS = 25.0  # DoD 3: "Blocked event loop (25 s) does not lose the lease"
SLOW_DRAFT_SECONDS = 35.0  # R088: "> 30 s fake drafter"
WORKER = "hb-live"


@pytest.fixture(scope="module")
def lines() -> Iterator[list[str]]:
    out = [f"T13 heartbeat — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"]
    yield out
    if len(out) != 1 + EXPECTED_LINES:  # a failed or partial run leaves the committed file as it was
        return
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


def block_the_loop(seconds: float) -> None:
    """A synchronous call where an async one belongs: called from a coroutine, it blocks the event loop (DoD 3)."""
    time.sleep(seconds)


class BlockingGenerator(FakeDraftGenerator):
    """A model route that blocks the event loop itself: only a heartbeat on its own thread can keep the lease alive
    meanwhile."""

    async def generate(self, request: Any, evidence: Any) -> Any:
        block_the_loop(BLOCK_SECONDS)
        return await super().generate(request, evidence)


class HangingMcp(ScriptedMcp):
    """A read server that accepts the call and never answers, so only a cancellation can end it."""

    def __init__(self, read: persistence.Conn, write: persistence.Conn) -> None:
        super().__init__(read, write)
        self.entered = asyncio.Event()
        self.cancelled = False
        self.handle_sha256 = ""

    async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((url, tool, arguments))
        self.handle_sha256 = persistence.handle_hash(handle)  # only the hash is kept, as the server keeps it
        self.entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return {}


async def worker_deps(role_conn: RoleConn, mcp_class: type[ScriptedMcp], generator: Any) -> handlers.Deps:
    mcp = mcp_class(await role_conn(Role.MCP_READ), await role_conn(Role.MCP_EXEC))
    return handlers.Deps(
        conn=await role_conn(Role.WORKER),
        mcp=mcp,
        generator=generator,
        urls=settings.urls(),
        worker_name=WORKER,
        workload_azp="ops-worker",  # the azp the scripted callers resolve with
        saver=InMemorySaver(),
        leases=settings.leases(),  # the real defaults: DoD 3 is about these values
    )


@asynccontextmanager
async def heartbeat_running(deps: handlers.Deps) -> AsyncIterator[Heartbeat]:
    """The heartbeat thread and the loop's liveness stamps, started the way the worker's _main starts them."""
    liveness = Liveness()
    heartbeat = Heartbeat(
        connect=connector(settings.app_postgres(Role.WORKER)), settings=deps.leases, liveness=liveness
    )
    deps.heartbeat = heartbeat
    stop = asyncio.Event()
    heartbeat.start()
    stamping = asyncio.create_task(keep_stamping(liveness, stop))
    try:
        yield heartbeat
    finally:
        stop.set()
        await stamping
        heartbeat.stop()
        await asyncio.to_thread(heartbeat.join, 5.0)


async def claim(deps: handlers.Deps, tenant: UUID) -> persistence.Claimed:
    got = await persistence.claim_next(
        deps.conn, worker_name=WORKER, tenant_ids=[tenant], lease_seconds=deps.leases.lease_seconds
    )
    assert isinstance(got, persistence.Claimed), got
    return got


async def lease_row(app_conn: persistence.Conn, run: UUID) -> dict[str, Any]:
    cur = await app_conn.execute(
        "SELECT owner, fence, lease_until = '-infinity' AS released FROM app.run_lease WHERE run_id = %s", (run,)
    )
    row = await cur.fetchone()
    assert row is not None
    return dict(row)


@pytest.mark.slow_live
async def test_r088_a_loop_blocked_for_25_seconds_keeps_its_lease(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    assert settings.leases().loop_stall_seconds > BLOCK_SECONDS  # the stall gate must outlast DoD 3's block
    tenant, _, run = await new_run(app_conn, api=await role_conn(Role.API))
    try:
        deps = await worker_deps(role_conn, ScriptedMcp, BlockingGenerator())
        claimed = await claim(deps, tenant)
        async with heartbeat_running(deps) as heartbeat:
            await main.run_job(deps, claimed)
        assert claimed.lease.lost == RELEASED and heartbeat.renewals >= 2  # at about 10 s and 20 s, mid-block
        # Not `BLOCK_SECONDS <= max_loop_age`: the thread samples the silence once per tick and the loop's last stamp
        # before the block may already be a stamp period old, so the largest silence a tick sees lies anywhere above
        # BLOCK - TICK - STAMP (review round 2, N1); the upper bound is the stall gate the lease must survive.
        lowest = BLOCK_SECONDS - TICK_SECONDS - STAMP_SECONDS
        assert lowest < heartbeat.max_loop_age < settings.leases().loop_stall_seconds
        assert (await persistence.run_row(app_conn, run))["state"] == "AWAITING_APPROVAL"
        assert await lease_row(app_conn, run) == {"owner": WORKER, "fence": claimed.lease.fence, "released": True}
        # The longest silence the thread saw goes into the evidence, so a near miss of the stall gate is visible.
        lines.append(
            f"R088 loop blocked {BLOCK_SECONDS:.0f} s: {heartbeat.renewals} renewals, longest loop silence"
            f" {heartbeat.max_loop_age:.1f} s of {settings.leases().loop_stall_seconds} s, fence kept, run drafted"
        )
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


@pytest.mark.slow_live
async def test_r088_a_drafter_slower_than_the_lease_keeps_its_lease(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    tenant, _, run = await new_run(app_conn, api=await role_conn(Role.API))
    try:
        deps = await worker_deps(role_conn, ScriptedMcp, FakeDraftGenerator(delay_seconds=SLOW_DRAFT_SECONDS))
        claimed = await claim(deps, tenant)
        async with heartbeat_running(deps) as heartbeat:
            await main.run_job(deps, claimed)
        assert claimed.lease.lost == RELEASED and heartbeat.renewals >= 3  # a 35 s draft under a 30 s lease
        assert (await persistence.run_row(app_conn, run))["state"] == "AWAITING_APPROVAL"
        assert await lease_row(app_conn, run) == {"owner": WORKER, "fence": claimed.lease.fence, "released": True}
        lines.append(f"R088 {SLOW_DRAFT_SECONDS:.0f} s drafter: {heartbeat.renewals} renewals, fence kept, run drafted")
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


@pytest.mark.slow_live
async def test_r088_a_forced_renewal_failure_cancels_the_call_and_revokes_the_handle(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    tenant, _, run = await new_run(app_conn, api=await role_conn(Role.API))
    try:
        deps = await worker_deps(role_conn, HangingMcp, FakeDraftGenerator())
        mcp: Any = deps.mcp
        thief = await role_conn(Role.WORKER)
        claimed = await claim(deps, tenant)
        async with heartbeat_running(deps):
            job = asyncio.create_task(main.run_job(deps, claimed))
            await asyncio.wait_for(mcp.entered.wait(), timeout=10)
            # Force the renewal to fail: the lease lapses on the database clock and a second worker takes the run.
            await expire_lease(app_conn, run)
            taken = await lease_for(thief, run, owner="hb-thief")
            started = time.monotonic()
            await asyncio.wait_for(job, timeout=deps.leases.heartbeat_seconds + 5)
            noticed = time.monotonic() - started
        assert mcp.cancelled and taken.fence == claimed.lease.fence + 1
        # The thief's acquisition usually lands first; a renewal between the expiry and it sees the lapse instead.
        assert claimed.lease.lost in ("another owner took the lease", "the lease expired")
        cur = await app_conn.execute(
            "SELECT revoked_at IS NOT NULL AS revoked FROM app.invocation_context WHERE handle_sha256 = %s",
            (mcp.handle_sha256,),
        )
        assert (await cur.fetchone())["revoked"]  # revoked by the lost owner under its old fence (ruling 8)
        cur = await app_conn.execute("SELECT claimed_by, done_at FROM app.jobs WHERE id = %s", (claimed.job["id"],))
        row = await cur.fetchone()
        assert row is not None and (row["claimed_by"], row["done_at"]) == (None, None)  # handed back (ruling 19)
        assert (await persistence.run_row(app_conn, run))["state"] == "RETRIEVING"  # no transition
        # The handed-back job runs again (review round 3, I1): its next owner finds the run interrupted and fails it.
        await expire_lease(app_conn, run)  # the thief is done with the run
        await main.run_job(deps, await claim(deps, tenant))
        assert (await persistence.run_row(app_conn, run))["state"] == "FAILED"
        lines.append(
            f"R088 forced renewal failure: call cancelled {noticed:.1f} s after the takeover, handle revoked;"
            " the re-run failed the interrupted run"
        )
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


async def test_the_model_permit_is_held_for_the_draft_and_released(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    seen: dict[str, Any] = {}
    other = await role_conn(Role.WORKER)
    tenant, _, run = await new_run(app_conn, api=await role_conn(Role.API))

    class PeekingGenerator(FakeDraftGenerator):
        async def generate(self, request: Any, evidence: Any) -> Any:
            cur = await app_conn.execute(
                "SELECT holder, run_id, leased_until > app.current_time() AS held FROM app.model_permit WHERE slot = 1"
            )
            seen.update(dict(await cur.fetchone()))
            async with other.transaction():
                seen["second"] = await persistence.take_model_permit(
                    other, holder="someone-else", run_id=run, ttl_seconds=65
                )
            return await super().generate(request, evidence)

    try:
        deps = await worker_deps(role_conn, ScriptedMcp, PeekingGenerator())
        await main.run_job(deps, await claim(deps, tenant))
        assert seen == {"holder": WORKER, "run_id": run, "held": True, "second": None}  # BS:549: one at a time
        cur = await app_conn.execute(
            "SELECT holder, leased_until = '-infinity' AS free FROM app.model_permit WHERE slot = 1"
        )
        assert dict(await cur.fetchone()) == {"holder": None, "free": True}
        lines.append("model permit: held by the drafting worker for the call, refused to a second taker, released")
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)

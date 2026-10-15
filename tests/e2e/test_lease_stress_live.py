"""T13 live (OPS_LIVE=1): eight `worker` connections and the sweeper hammer three runs for twenty seconds with every
lease operation the system has, under the published lock order (DoD 2, R107), and R019 end to end: a killed owner's
job is reclaimed once its lease has expired on the database clock, and the next owner takes it at a higher fence
(Plan H rulings 11, 14, 21).

The stress mix, one random operation on one random run per step: a claim (`claim_next`: SKIP LOCKED, NOWAIT, defer),
a waiting acquisition (`acquire_lease(wait=True)`: the form that would deadlock if the order were wrong; its lock
waits surface as 55P03, never as a busy lease), a renewal (the heartbeat's synchronous unit, on each actor's own
synchronous connection), a fenced event, a mint, a revoke, a `mark_unknown` re-fence, and a drop: a holder of two
seconds or more stops renewing, as a hung or killed worker does, so its lease lapses on the database clock and the
run changes hands under load (without it the first holder of each run renews it for all twenty seconds and no lease
is ever taken over: Task 6 measured three acquisitions, one per run, in each of three runs). Two of the three runs are
QUEUED, where `mark_unknown` is refused after it has taken its locks (the locks are the point); the third is EXECUTING
with a grant, so a re-fence commits under load and its holder hands the new fence to its Lease (review round 1, I4).
The sweeper reclaims every 0.2 s, and a monitor samples every 50 ms: fences only increase, and at most one actor's
own Lease of a run passes its local check (not lost, before its local deadline), that actor being the owner of the
run's live row at its fence (SA:195's 5 s margin is what makes this hold; the R019 test resets the test clock, so the
database clock and the monotonic clock agree here). Every connection runs with `lock_timeout = 10s`, so a wait that
never ends shows up as SQLSTATE 55P03. Evidence: reports/leases/t13-stress.txt.

Catches: a deadlock (40P01) or a lock wait past 10 s (55P03) anywhere in the mix, a fence that goes backwards or is
handed out twice, two actors that both believe they hold a run's lease (or one whose belief the database does not
share), and an expiry decided by anything but the database clock.

What the run does not exercise: its evidence records `lost 0` and `jobs handed back 0`, so it cannot catch a stale
write that lands or a reclaim that takes a live owner's job (final review, M6). Those are covered
elsewhere: the stepped interleavings in test_leases_live.py and the fenced definers in test_fenced_definers_live.py
refuse a stale write, and the R019 and live-lease reclaim tests below cover the reclaim.
"""

import asyncio
import random
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from ops_core import persistence, settings
from ops_core.jobs import Server
from ops_core.lease import Busy, Lease, LeaseLost, Renewal, renew
from ops_core.outcomes import EventType
from ops_core.settings import Role
from ops_sweeper import leases
from psycopg.rows import dict_row

from tests.e2e.conftest import expire_lease, purge_run, purge_tenant
from tests.e2e.test_mcp_write_live import approved_run
from tests.e2e.test_migrations_and_persistence import new_run

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
EVIDENCE = Path("reports/leases/t13-stress.txt")
EXPECTED_LINES = 3  # one per test
STRESS_SECONDS = 20.0
ACTORS = 8
RUNS = 3  # two QUEUED, one EXECUTING
OPS = ("claim", "acquire", "renew", "write", "mint", "revoke", "bump", "drop")
DROP_AFTER_SECONDS = 2.0  # how long a holder keeps a run before it may stall on it


@pytest.fixture(scope="module")
def lines() -> Iterator[list[str]]:
    out = [f"T13 stress and reclaim — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"]
    yield out
    if len(out) != 1 + EXPECTED_LINES:  # a failed or partial run leaves the committed file as it was
        return
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


async def patient(conn: persistence.Conn) -> persistence.Conn:
    """A connection whose lock waits end after 10 s with 55P03 instead of never (the deadlock detector would still
    report a real cycle first, after its 1 s deadlock_timeout)."""
    await conn.execute("SET lock_timeout = '10s'")
    return conn


class Actor:
    """One worker connection pair doing random lease work on the shared runs, tallying what happened."""

    def __init__(self, name: str, conn: persistence.Conn, sync_conn: Any, tenant: UUID, jobs: dict[UUID, UUID]) -> None:
        self.name = name
        self.conn = conn
        self.sync_conn = sync_conn
        self.tenant = tenant
        self.jobs = jobs
        self.rng = random.Random(name)
        self.held: dict[UUID, Lease] = {}

    async def step(self, tally: Counter[str], acquired: dict[UUID, list[int]]) -> None:
        run = self.rng.choice(list(self.jobs))
        op = self.rng.choice(OPS)
        lease = self.held.get(run)
        try:
            if op == "claim":
                got = await persistence.claim_next(
                    self.conn, worker_name=self.name, tenant_ids=[self.tenant], lease_seconds=8
                )
                if isinstance(got, persistence.Claimed):
                    self.held[got.lease.run_id] = got.lease
                    acquired.setdefault(got.lease.run_id, []).append(got.lease.fence)
            elif op == "acquire" or lease is None:
                async with self.conn.transaction():
                    taken = await persistence.acquire_lease(
                        self.conn, run_id=run, owner=self.name, lease_seconds=self.rng.choice((6, 8, 10)), wait=True
                    )
                if not isinstance(taken, Busy):  # a waiting acquisition's 55P03 is raised and counted below
                    self.held[run] = taken
                    acquired.setdefault(run, []).append(taken.fence)
                op = "acquire"
            elif op == "drop":
                if time.monotonic() - lease.held_since >= DROP_AFTER_SECONDS:
                    self.held.pop(run)  # nothing released: the row lapses at its lease_until, the claim stays
                    tally["dropped"] += 1
            elif op == "renew":
                started = time.monotonic()
                verdict = await asyncio.to_thread(renew, self.sync_conn, lease, lease.fence)
                if verdict is Renewal.RENEWED:
                    lease.renewed(started)
                else:
                    self.held.pop(run, None)
            elif op == "write":
                async with self.conn.transaction():
                    await persistence.fenced(self.conn, lease)
                    await persistence.append_event(
                        self.conn, run_id=run, type=EventType.TOOL_STARTED, payload={"message": f"fence {lease.fence}"}
                    )
            elif op == "mint":
                async with self.conn.transaction():
                    await persistence.fenced(self.conn, lease)
                    await persistence.mint_handle(
                        self.conn,
                        run_id=run,
                        job_id=self.jobs[run],
                        server=Server.READ,
                        azp="ops-worker",
                        fence=lease.fence,
                    )
            elif op == "revoke":
                async with self.conn.transaction():
                    await persistence.revoke_handles(self.conn, run, lease.fence)
            else:
                lease.begin_refence()  # as the worker brackets its re-fence (ruling 10)
                try:
                    async with self.conn.transaction():
                        unknown = await persistence.mark_unknown(self.conn, run, lease.fence)
                except BaseException:
                    lease.end_refence(None)
                    raise
                lease.end_refence(unknown.fence)
                acquired.setdefault(run, []).append(unknown.fence)
                tally["bumped"] += 1
            tally[op] += 1
        except LeaseLost:
            self.held.pop(run, None)
            tally["lost"] += 1
        except persistence.VersionConflict:
            tally["refused"] += 1  # mark_unknown on a QUEUED run, or a stale fence: rolled back, locks released
        except psycopg.errors.DeadlockDetected:
            tally["40P01"] += 1
        except psycopg.errors.LockNotAvailable:
            tally["55P03"] += 1


@pytest.mark.slow_live
async def test_r107_eight_workers_and_the_sweeper_never_deadlock_and_fences_never_go_back(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    api, seeder, mcp_exec = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.MCP_EXEC)
    tenant, _, first = await new_run(app_conn, api=api)
    runs = [first, (await new_run(app_conn, tenant, api=api))[2]]
    sync_conns: list[Any] = []
    try:
        # The EXECUTING run: approved and granted through the definers (on the seeded tenant), then its seeding lease
        # expired, so the actors compete for it from the next fence.
        _, executing, proposal, handle = await approved_run(app_conn, api=api, worker=seeder)
        runs.append(executing)
        async with mcp_exec.transaction():
            await persistence.grant_execution(mcp_exec, handle=handle, proposal_id=proposal)
        await expire_lease(app_conn, executing)
        cur = await app_conn.execute("SELECT run_id, id FROM app.jobs WHERE run_id = ANY(%s)", (runs,))
        jobs = {UUID(str(row["run_id"])): UUID(str(row["id"])) for row in await cur.fetchall()}
        conninfo = settings.app_postgres(Role.WORKER).conninfo()
        actors = []
        for index in range(ACTORS):
            sync_conn = psycopg.connect(conninfo, autocommit=True, row_factory=dict_row)
            sync_conn.execute("SET lock_timeout = '10s'")
            sync_conns.append(sync_conn)
            conn = await patient(await role_conn(Role.WORKER))
            actors.append(Actor(f"stress-{index}", conn, sync_conn, tenant, jobs))
        sweeper = await patient(await role_conn(Role.SWEEPER))
        tally: Counter[str] = Counter()
        acquired: dict[UUID, list[int]] = {}
        seen: dict[UUID, list[int]] = {run: [] for run in runs}
        two_owners: list[str] = []
        deadline = time.monotonic() + STRESS_SECONDS

        async def act(actor: Actor) -> None:
            while time.monotonic() < deadline:
                await actor.step(tally, acquired)
                await asyncio.sleep(0)

        async def reclaim() -> None:
            while time.monotonic() < deadline:
                try:
                    tally["reclaimed"] += len(await leases.reclaim(sweeper))
                    tally["reclaim"] += 1
                except psycopg.errors.DeadlockDetected:
                    tally["40P01"] += 1
                except psycopg.errors.LockNotAvailable:
                    tally["55P03"] += 1
                await asyncio.sleep(0.2)

        def believers(run: UUID) -> list[tuple[str, int, bool]]:
            """The actors whose own Lease of `run` passes its local check now: the fence each believes it holds, and
            whether it is between `begin_refence` and `end_refence` (its own bump may commit before the row is read)."""
            now = time.monotonic()
            return [
                (a.name, held.fence, held.refencing)
                for a in actors
                if (held := a.held.get(run)) is not None and held.lost is None and now < held.deadline
            ]

        async def monitor() -> None:
            """Ruling 21's observation (review round 2, N3): at each sample, at most one actor believes it holds a run's
            lease, and the row read right after says it does: that actor owns the row, the row is live, and its fence
            is the believed one, or one more only for an actor that was mid-re-fence at the sample (review round 3: a
            bump that never reached the Lease would otherwise pass)."""
            while time.monotonic() < deadline:
                beliefs = {run: believers(run) for run in runs}  # taken first: the row read below can only be newer
                cur = await app_conn.execute(
                    "SELECT run_id, owner, fence, lease_until > app.current_time() AS live FROM app.run_lease"
                    " WHERE run_id = ANY(%s)",
                    (runs,),
                )
                for row in await cur.fetchall():
                    run, fence = UUID(str(row["run_id"])), int(row["fence"])
                    seen[run].append(fence)
                    believed = beliefs[run]
                    if len(believed) > 1:
                        two_owners.append(f"{run}: {believed} all believe they hold it")
                    elif believed:
                        name, held_fence, refencing = believed[0]
                        allowed = (held_fence, held_fence + 1) if refencing else (held_fence,)
                        if not (row["live"] and row["owner"] == name and fence in allowed):
                            two_owners.append(f"{run}: {name} at fence {held_fence} vs row {row['owner']} at {fence}")
                await asyncio.sleep(0.05)

        await asyncio.gather(*(act(actor) for actor in actors), reclaim(), monitor())

        assert tally["40P01"] == 0 and tally["55P03"] == 0, dict(tally)  # DoD 2: no deadlock, no endless wait
        assert sum(tally[op] for op in OPS) >= 200, dict(tally)  # it really ran
        assert tally["bumped"] >= 1, dict(tally)  # a re-fence committed under load (review round 1, I4)
        handed = sum(len(fences) for fences in acquired.values()) - tally["bumped"]  # by a claim or an acquisition
        assert handed > RUNS, dict(tally)  # a lapsed lease was taken over under load, not only each run's first
        assert two_owners == [], two_owners[:5]
        for run in runs:
            fences = acquired.get(run, [])
            assert len(fences) == len(set(fences)), run  # no fence handed out twice
            assert seen[run] == sorted(seen[run]), run  # never backwards
            cur = await app_conn.execute(
                "SELECT payload->>'message' AS m FROM app.events WHERE run_id = %s AND type = 'tool.started'"
                " ORDER BY sequence",
                (run,),
            )
            written = [int(row["m"].split()[1]) for row in await cur.fetchall()]
            assert written == sorted(written), run  # no stale writer landed after a newer fence (DoD 1, under load)
        top = max(max(fences) for fences in acquired.values())
        samples = sum(len(fences) for fences in seen.values())
        lines.append(
            f"R107 stress {ACTORS} workers x {STRESS_SECONDS:.0f} s on {RUNS} runs: {sum(tally.values())} operations,"
            f" 40P01=0, 55P03=0, acquisitions {handed}, highest fence {top}, re-fences {tally['bumped']},"
            f" refused {tally['refused']}, lost {tally['lost']}, drops {tally['dropped']},"
            f" reclaim passes {tally['reclaim']} (jobs handed back {tally['reclaimed']}); at each of {samples} row"
            " samples at most one actor believed it held a run, the live owner"
        )
    finally:
        for sync_conn in sync_conns:
            sync_conn.close()
        for run in runs:
            await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


async def test_r019_a_killed_owners_job_is_reclaimed_and_the_next_owner_fences_higher(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    tenant, _, run = await new_run(app_conn, api=await role_conn(Role.API))
    a = await role_conn(Role.WORKER)
    b, sweeper = await role_conn(Role.WORKER), await role_conn(Role.SWEEPER)
    harness = await role_conn(Role.TEST_HARNESS)  # the one role that may move app.test_clock (AM-20.6)
    try:
        first = await persistence.claim_next(a, worker_name="w-killed", tenant_ids=[tenant], lease_seconds=30)
        assert isinstance(first, persistence.Claimed)
        await a.close()  # the owner dies without releasing anything (a killed process)
        assert first.job["id"] not in await leases.reclaim(sweeper)  # the lease is live: the claim stands
        async with b.transaction():
            busy = await persistence.acquire_lease(b, run_id=run, owner="w-next", lease_seconds=30)
        assert busy == Busy(locked=False)
        # Expiry on the database clock (R107): the test clock passes the 30 s lease. The offset is global, and no other
        # lease in this database matters while it is set; it is reset in `finally`.
        await harness.execute("UPDATE app.test_clock SET clock_offset = interval '31 seconds'")
        try:
            assert first.job["id"] in await leases.reclaim(sweeper)
            second = await persistence.claim_next(b, worker_name="w-next", tenant_ids=[tenant], lease_seconds=30)
            assert isinstance(second, persistence.Claimed) and second.job["id"] == first.job["id"]
            assert second.lease.fence == first.lease.fence + 1  # R019: "another owner acquires … incremented fence"
            zombie = await role_conn(Role.WORKER)  # the killed owner's code on a fresh connection, old lease in hand
            with pytest.raises(LeaseLost):
                async with zombie.transaction():
                    await persistence.fenced(zombie, first.lease)
            lines.append(
                f"R019 killed owner: claim kept while live, reclaimed after expiry, next at fence {second.lease.fence}"
            )
        finally:
            await harness.execute("UPDATE app.test_clock SET clock_offset = interval '0'")
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


async def test_the_reclaim_leaves_a_live_lease_alone(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    tenant, _, run = await new_run(app_conn, api=await role_conn(Role.API))
    a, sweeper = await role_conn(Role.WORKER), await role_conn(Role.SWEEPER)
    try:
        claimed = await persistence.claim_next(a, worker_name="w-alive", tenant_ids=[tenant], lease_seconds=30)
        assert isinstance(claimed, persistence.Claimed)
        assert claimed.job["id"] not in await leases.reclaim(sweeper)
        cur = await app_conn.execute("SELECT claimed_by FROM app.jobs WHERE id = %s", (claimed.job["id"],))
        assert (await cur.fetchone())["claimed_by"] == "w-alive"
        await persistence.release_lease(a, claimed.lease, job=dict(claimed.job))
        assert claimed.job["id"] not in await leases.reclaim(sweeper)  # done: nothing to hand back
        lines.append("reclaim: a live owner's claim is kept; a finished job is never handed back")
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)

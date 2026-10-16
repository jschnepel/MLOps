"""T14 live (OPS_LIVE=1): per-run event sequences are gap-free and commit-ordered under concurrent writers of every
role that writes events, and a reader following the events route's `after` cursor never skips (R089, DoD 1; Plan I
rulings 1-3).

The mechanism is revision 0003's and unchanged (ruling 1): `_append_event` locks the run row FOR UPDATE, takes
`next_event_seq + 1` and inserts in the caller's transaction, so a second writer of the run waits for the first to
commit or roll back. The stepped tests hold writer A's sequence n uncommitted, show with `pg_blocking_pids` that
writer B waits on A, and read through the events route (`DbStore.events`, the query behind
`GET /api/v1/runs/{id}/events`) that neither n nor n+1 is visible until its own writer commits. The pairs cover the
four roles and both kinds of writer: the worker's `transition_run` against the API's `append_event`, and mcp-write's
`mark_sent` (a definer that appends) against the sweeper's `append_event`. The rollback test shows that a writer
that took n and rolled back leaves n to the next writer. The stress test runs eight connections of the four roles
against three runs for ten seconds, every writer rolling back about half of its transactions, while one reader
follows each run's cursor through the route and another counts each run's rows; afterwards every run holds exactly
1..next_event_seq, the cursor reader followed every run to its counter without a skip, and the counting reader saw
each run grow without a hole below its maximum. The worker writes through `append_event` in the
stress run (its `transition_run` moves a run through pre-grant states only, which the stepped test covers); mcp-write
writes the grant, SENT and outcome of each run, each first attempt rolled back. Writes evidence to
reports/events/t14-events.txt (counts and verdicts; no handle, token or seeded tenant id).

Catches: a sequence number taken outside the run lock (two writers with one number, or a reader seeing n+1 before n),
a rolled-back writer that leaves a hole, a definer that appends without the lock, an events route that returns a
later sequence before an earlier one has committed (the cursor would skip it for good), and a reader that passes
because it read nothing (each reader must follow every run to its end, or see it grow).

Every backend pid is read before any transaction opens, and no task is ever cancelled while it may be inside a
database unit: a pid query queued behind a blocked statement on the same connection, or a cancelled unit left inside
its transaction holding the run row, would hang the live gate instead of failing it (round 1, B1 and M3).
"""

import asyncio
import random
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from ops_api.store import DbStore
from ops_core import persistence
from ops_core.settings import Role
from psycopg.types.json import Jsonb

from tests.e2e.conftest import backend_pid, purge_run, purge_tenant, wait_until_blocked
from tests.e2e.test_definers_run_path_live import ALPHA
from tests.e2e.test_definers_write_path_live import approve, drafting_run, freeze, handle_for
from tests.e2e.test_migrations_and_persistence import new_run

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
EVIDENCE = Path("reports/events/t14-events.txt")
EXPECTED_LINES = 4  # one per test
APPEND = "SELECT * FROM app.append_event(%s, %s, %s, 'application')"
STRESS_SECONDS = 10.0
LOCK_TIMEOUT = "SET lock_timeout = '10s'"


@pytest.fixture(scope="module")
def lines() -> Iterator[list[str]]:
    out = [f"T14 event journal — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"]
    yield out
    if len(out) != 1 + EXPECTED_LINES:  # a failed or partial run leaves the committed file as it was
        return
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


async def route(store: DbStore, tenant: UUID, run: UUID, after: int = 0) -> list[int]:
    """The sequences the events route returns after a cursor, in its order."""
    return [int(e["sequence"]) for e in await store.events(tenant, run, after=after, limit=500)]


async def sequences(app_conn: persistence.Conn, run: UUID) -> tuple[list[int], int]:
    """Every committed sequence of the run, and the run's counter."""
    cur = await app_conn.execute("SELECT sequence FROM app.events WHERE run_id = %s ORDER BY sequence", (run,))
    seen = [int(row["sequence"]) for row in await cur.fetchall()]
    cur = await app_conn.execute("SELECT next_event_seq FROM app.runs WHERE run_id = %s", (run,))
    return seen, int((await cur.fetchone())["next_event_seq"])


async def settle(task: asyncio.Task[None], conn: persistence.Conn) -> None:
    """Wait up to 5 s for a writer task without cancelling it: a cancelled unit could leave its connection inside its
    transaction holding the run row, and the purge in `finally` would wait on it for good. A writer still pending
    fails the test, and its connection is closed first so the server ends its transaction."""
    done, _ = await asyncio.wait({task}, timeout=5)
    if not done:
        await conn.close()
        raise AssertionError("the waiting writer never finished")
    task.result()


async def stepped(
    app_conn: persistence.Conn,
    store: DbStore,
    tenant: UUID,
    run: UUID,
    a: tuple[persistence.Conn, str, tuple[object, ...]],
    b: tuple[persistence.Conn, str, tuple[object, ...]],
) -> int:
    """Writer A appends sequence n and holds it uncommitted; writer B's append waits on A (pg_blocking_pids); the
    route shows n only after A commits and n + 1 only after B commits. Returns n."""
    (a_conn, a_sql, a_params), (b_conn, b_sql, b_params) = a, b
    # Both pids first: once B's statement waits in the database, its connection is busy until A ends (B1).
    a_pid, b_pid = await backend_pid(a_conn), await backend_pid(b_conn)
    before = await route(store, tenant, run)
    n = len(before) + 1
    assert before == list(range(1, n))
    b_appended, b_may_commit = asyncio.Event(), asyncio.Event()

    async def writer_b() -> None:
        async with b_conn.transaction():
            await b_conn.execute(b_sql, b_params)
            b_appended.set()
            await b_may_commit.wait()

    b_task: asyncio.Task[None] | None = None
    try:
        async with a_conn.transaction():
            await a_conn.execute(a_sql, a_params)
            assert await route(store, tenant, run, after=n - 1) == []  # n is taken, not committed: invisible
            b_task = asyncio.create_task(writer_b())
            assert a_pid in await wait_until_blocked(app_conn, b_pid)  # B waits on A's run row lock
            assert not b_appended.is_set() and await route(store, tenant, run, after=n - 1) == []
        await asyncio.wait_for(b_appended.wait(), timeout=5)  # A committed; B got n + 1 and holds it
        assert await route(store, tenant, run, after=n - 1) == [n]  # the cursor sees n, never n + 1 first
        b_may_commit.set()
        await settle(b_task, b_conn)
    finally:
        b_may_commit.set()  # a failed assertion must not leave B's transaction open: the purge would wait on it
        # Settled even when already done: a writer B that failed (two writers with one number: a UniqueViolation,
        # measured with the run lock removed) raises its own error here instead of a bare timeout above.
        if b_task is not None:
            await settle(b_task, b_conn)
    assert await route(store, tenant, run, after=n) == [n + 1]
    seen, counter = await sequences(app_conn, run)
    assert seen == list(range(1, n + 2)) and counter == n + 1
    return n


async def test_r089_transition_run_and_api_append_commit_in_order(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    api, worker, reader = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.API)
    tenant, _, run = await new_run(app_conn, api=api)
    try:
        await worker.execute("SELECT app.transition_run(%s, 'QUEUED', 'RETRIEVING', NULL, 1, '{}')", (run,))  # no event
        n = await stepped(
            app_conn,
            DbStore(reader),
            tenant,
            run,
            (worker, "SELECT app.transition_run(%s, 'RETRIEVING', 'AWAITING_INPUT', NULL, 2, '{}')", (run,)),
            (api, APPEND, (run, "tool.completed", Jsonb({"message": "api"}))),
        )
        lines.append(f"R089 stepped: worker transition_run took {n}, api append_event waited and took {n + 1}")
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


async def test_r089_mark_sent_and_sweeper_append_commit_in_order(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    api, worker, reader = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.API)
    mcp_exec, sweeper = await role_conn(Role.MCP_EXEC), await role_conn(Role.SWEEPER)
    run = await drafting_run(app_conn, api, worker)
    try:
        proposal, _, digest = await freeze(app_conn, worker, run)
        await approve(api, proposal, digest)
        handle = await handle_for(app_conn, run, "execute", expires_in=600)
        cur = await mcp_exec.execute("SELECT * FROM app.grant_execution(%s, 'ops-worker', %s)", (handle, proposal))
        action = (await cur.fetchone())["action_id"]
        n = await stepped(
            app_conn,
            DbStore(reader),
            ALPHA,
            run,
            (mcp_exec, "SELECT app.mark_sent(%s, 'ops-worker', %s)", (handle, action)),
            (sweeper, APPEND, (run, "tool.completed", Jsonb({"message": "sweeper"}))),
        )
        lines.append(f"R089 stepped: mcp_exec mark_sent took {n}, sweeper append_event waited and took {n + 1}")
    finally:
        await purge_run(app_conn, run)


async def test_r089_a_rolled_back_writer_leaves_no_hole(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    """Ruling 3 (b): A takes n and rolls back; B, which waited on A, then gets n itself."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    api_pid, worker_pid = await backend_pid(api), await backend_pid(worker)  # before any unit opens (B1)
    tenant, _, run = await new_run(app_conn, api=api)
    b_task: asyncio.Task[None] | None = None
    try:
        b_got: list[int] = []

        async def writer_b() -> None:
            async with worker.transaction():
                cur = await worker.execute(APPEND, (run, "tool.started", Jsonb({"message": "worker"})))
                b_got.append(int((await cur.fetchone())["sequence"]))

        async with api.transaction(force_rollback=True):
            cur = await api.execute(APPEND, (run, "tool.completed", Jsonb({"message": "rolled back"})))
            taken = int((await cur.fetchone())["sequence"])
            b_task = asyncio.create_task(writer_b())
            assert api_pid in await wait_until_blocked(app_conn, worker_pid)
        await settle(b_task, worker)  # A rolled back on leaving the block; B proceeds and commits
        assert b_got == [taken] == [2]  # the number A gave back, after run.accepted
        seen, counter = await sequences(app_conn, run)
        assert seen == [1, 2] and counter == 2
        lines.append(f"R089 rollback: api took {taken} and rolled back; the waiting worker took {b_got[0]}; no hole")
    finally:
        if b_task is not None and not b_task.done():  # a failed assertion: B commits once A has rolled back (N3)
            await settle(b_task, worker)
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


class Tally:
    """Commits and rollbacks per role, and the lock errors the stress run must never see."""

    def __init__(self) -> None:
        self.committed: Counter[str] = Counter()
        self.rolled_back: Counter[str] = Counter()
        self.errors: Counter[str] = Counter()


async def append_actor(
    conn: persistence.Conn, role: str, runs: list[UUID], tally: Tally, stop: float, seed: str
) -> None:
    """Append one event to a random run per transaction; every third transaction, and a quarter of the rest, rolls
    back after it has taken its number."""
    rng = random.Random(seed)
    kind = "tool.started" if role == "worker" else "tool.completed"
    step = 0
    while time.monotonic() < stop:
        rollback = step % 3 == 0 or rng.random() < 0.25
        try:
            async with conn.transaction(force_rollback=rollback):
                await conn.execute(APPEND, (rng.choice(runs), kind, Jsonb({"message": f"{role} {step}"})))
        except psycopg.errors.LockNotAvailable:
            tally.errors["55P03"] += 1
        except psycopg.errors.DeadlockDetected:
            tally.errors["40P01"] += 1
        else:
            (tally.rolled_back if rollback else tally.committed)[role] += 1
        step += 1
        await asyncio.sleep(rng.random() * 0.004)


async def mcp_actor(conn: persistence.Conn, work: list[dict[str, Any]], tally: Tally) -> None:
    """Grant, SENT and the outcome of each of its runs, through the definers; each step's first attempt rolls back
    after the definer appended its event, the second commits."""
    calls = (
        ("grant", "SELECT * FROM app.grant_execution(%s, 'ops-worker', %s)"),
        ("sent", "SELECT app.mark_sent(%s, 'ops-worker', %s) AS r"),
        ("outcome", "SELECT app.record_outcome(%s, 'ops-worker', %s, 'SUCCEEDED', %s) AS r"),
    )
    for item in work:
        for name, sql in calls:
            for rollback in (True, False):
                if name == "grant":
                    params: tuple[object, ...] = (item["handle"], item["proposal"])
                elif name == "sent":
                    params = (item["handle"], item["action"])
                else:
                    document = {
                        "status": "SUCCEEDED",
                        "action_id": str(item["action"]),
                        "payload_sha256": item["digest"],
                        "receipt": {"receipt_id": str(uuid4()), "incident_id": "INC-T14", "committed_at": item["at"]},
                        "tombstone": None,
                        "reason": None,
                    }
                    params = (item["handle"], item["action"], Jsonb(document))
                async with conn.transaction(force_rollback=rollback):
                    cur = await conn.execute(sql, params)
                    row = await cur.fetchone()
                    if name == "grant":
                        item["action"] = row["action_id"]  # a rolled-back grant's id is gone; the next one stands
                (tally.rolled_back if rollback else tally.committed)["mcp_exec"] += 1
                await asyncio.sleep(0.05)


@dataclass
class Reading:
    """What one reader saw: violations, and per run what proves it read while the writers wrote."""

    wrong: list[str] = field(default_factory=list)
    last: dict[UUID, int] = field(default_factory=dict)  # the cursor reader's final cursor per run
    pages: Counter[UUID] = field(default_factory=Counter)  # its non-empty pages per run
    highs: dict[UUID, set[int]] = field(default_factory=dict)  # the counting reader's distinct maxima per run


async def follow(store: DbStore, run: UUID, reading: Reading) -> bool:
    """One page after the run's cursor; it must continue exactly where the last one ended. True when non-empty."""
    after = reading.last[run]
    page = await route(store, ALPHA, run, after=after)
    if page and page != list(range(after + 1, after + 1 + len(page))):
        reading.wrong.append(f"after {after}: {page[:3]}")
    if page:
        reading.last[run] = page[-1]
        reading.pages[run] += 1
    return bool(page)


async def cursor_reader(store: DbStore, runs: list[UUID], writers_done: asyncio.Event) -> Reading:
    """Follow each run's cursor through the events route while the writers write, then to each run's end."""
    reading = Reading(last=dict.fromkeys(runs, 0))
    while not writers_done.is_set():
        for run in runs:
            await follow(store, run, reading)
        await asyncio.sleep(0.02)
    for run in runs:  # the writers are done: drain each run, so its final cursor must be its counter
        while await follow(store, run, reading):
            pass
    return reading


async def count_reader(conn: persistence.Conn, runs: list[UUID], writers_done: asyncio.Event) -> Reading:
    """Count each run's committed rows against their maximum in one snapshot while the writers write: a hole below
    the maximum would show as fewer rows than the maximum."""
    reading = Reading(highs={run: set() for run in runs})
    while not writers_done.is_set():
        async with conn.transaction():
            await persistence.set_tenant(conn, ALPHA)
            cur = await conn.execute(
                "SELECT run_id, count(*) AS n, max(sequence) AS hi FROM app.events WHERE run_id = ANY(%s)"
                " GROUP BY run_id",
                (runs,),
            )
            for row in await cur.fetchall():
                if row["n"] != row["hi"]:
                    reading.wrong.append(f"{row['n']} rows below {row['hi']}")
                reading.highs[row["run_id"]].add(int(row["hi"]))
        await asyncio.sleep(0.02)
    return reading


async def test_r089_stress_four_roles_three_runs_with_rollbacks(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    runs: list[UUID] = []
    try:
        work: list[dict[str, Any]] = []
        for _ in range(3):
            run = await drafting_run(app_conn, api, worker)
            runs.append(run)
            proposal, _, digest = await freeze(app_conn, worker, run)
            await approve(api, proposal, digest)
            handle = await handle_for(app_conn, run, "execute", expires_in=600)
            at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            work.append({"run": run, "proposal": proposal, "digest": digest, "handle": handle, "at": at})
        actors = {
            role: [await role_conn(role) for _ in range(2)]
            for role in (Role.API, Role.WORKER, Role.SWEEPER, Role.MCP_EXEC)
        }
        for conn in (c for group in actors.values() for c in group):
            await conn.execute(LOCK_TIMEOUT)
        tally, writers_done = Tally(), asyncio.Event()
        stop = time.monotonic() + STRESS_SECONDS
        appenders = [
            append_actor(conn, role.value, runs, tally, stop, f"{role.value}-{i}")
            for role in (Role.API, Role.WORKER, Role.SWEEPER)
            for i, conn in enumerate(actors[role])
        ]
        mcp = [
            mcp_actor(actors[Role.MCP_EXEC][0], work[0::2], tally),
            mcp_actor(actors[Role.MCP_EXEC][1], work[1::2], tally),
        ]

        # A plain gather raises the first failure while its siblings keep writing: the purge in `finally` then races
        # them (measured with the run lock removed: a ForeignKeyViolation on the purge), the readers never see
        # `writers_done`, and the closing event loop cancels units still inside their transactions (M3). So every
        # writer and reader runs to its own end, the readers are released even when a writer failed, and only then
        # is the first failure raised.
        async def writers() -> None:
            try:
                ended = await asyncio.gather(*appenders, *mcp, return_exceptions=True)
            finally:
                writers_done.set()
            for outcome in ended:
                if isinstance(outcome, BaseException):
                    raise outcome

        wrote, cursor, counts = await asyncio.gather(
            writers(),
            cursor_reader(DbStore(await role_conn(Role.API)), runs, writers_done),
            count_reader(await role_conn(Role.SWEEPER), runs, writers_done),
            return_exceptions=True,
        )
        for outcome in (wrote, cursor, counts):
            if isinstance(outcome, BaseException):
                raise outcome
        assert isinstance(cursor, Reading) and isinstance(counts, Reading)  # narrowed: neither was a failure
        assert cursor.wrong == [] and counts.wrong == []
        assert tally.errors == Counter()  # no 55P03 and no 40P01: one run row per transaction, one lock order
        for role in ("api", "worker", "sweeper", "mcp_exec"):  # every role both committed and gave numbers back
            assert tally.committed[role] >= 3 and tally.rolled_back[role] >= 3, role
        total = 0
        for run in runs:
            got, counter = await sequences(app_conn, run)
            assert got == list(range(1, counter + 1)), run  # gap-free: exactly 1..next_event_seq
            # The readers read this run while it was written (round 1, I4): the cursor followed it to its counter
            # through at least 20 non-empty pages, and the counting reader saw its maximum grow.
            assert cursor.last[run] == counter and cursor.pages[run] >= 20, run
            assert len(counts.highs[run]) > 1, run
            total += counter
            cur = await app_conn.execute(
                "SELECT r.state, (SELECT count(*) FROM app.outbox o WHERE o.run_id = r.run_id) AS intents"
                " FROM app.runs r WHERE r.run_id = %s",
                (run,),
            )
            assert dict(await cur.fetchone()) == {"state": "SUCCEEDED", "intents": 1}  # one intent despite rollbacks
        lines.append(
            f"R089 stress: 8 connections of api, worker, sweeper and mcp_exec on 3 runs for {STRESS_SECONDS:.0f} s;"
            f" committed {sum(tally.committed.values())}, rolled back {sum(tally.rolled_back.values())};"
            f" {total} events, every run exactly 1..next_event_seq; the cursor followed every run to its counter in"
            f" {sum(cursor.pages.values())} non-empty pages, the counter saw {sum(map(len, counts.highs.values()))}"
            " distinct maxima; no hole and no skip; 55P03 0, 40P01 0"
        )
    finally:
        for run in runs:
            await purge_run(app_conn, run)

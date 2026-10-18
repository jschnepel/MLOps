"""The sweeper process (AM-20.1 scheduler): a tick loop beside a health server, the worker's shape (one loop
connection as role `sweeper`, one probe connection, a SelectorEventLoop on Windows).

Every tick (30 s) syncs, then records the sync as this minute's `sync_memberships` maintenance job (SA:504's dedup
key; inserted, claimed and finished by the same tick, so the `jobs` table is the audit trail of every minute and a
second sweeper instance never records the same minute twice); the first tick syncs at once, so readiness arrives
within seconds of start, and two syncs are never more than 30 s plus one sync's duration apart (ruling 12; SA:547's
60 s holds with margin). The same tick purges expired rows, hands back the jobs whose run lease died with their
worker (T13, `leases.reclaim`), re-arms lost wake-ups (T14: `wakeups.sweep`, the purge of finished maintenance rows,
this minute's `sweep_wakeups` row) and, last, delivers the notification outbox (T14: this minute's `deliver_outbox`
row, then `outbox.deliver`, then the dead letters' `notification.failed`), so a database error during delivery ends
the tick after everything else has run (a sink's crash is one row's failed attempt). Readiness is 200 only while the
last successful sync is younger than 120 s, the window after which `grant_execution` refuses (T11 review note 2), so
`scripts/skeleton.py up` waits for the first sync.
TODO(T21): proposal expiry.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

import psycopg
import uvicorn
from ops_core import keycloak_admin, persistence, redaction, settings
from ops_core.jobs import JobType
from ops_core.keycloak_admin import AdminUnavailable
from ops_core.settings import OutboxSettings, Role, WakeupSettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ops_sweeper import leases, outbox, sync, wakeups

FRESH_SECONDS = 120.0  # the gate's window (0005's grant_execution); readiness follows it
log = logging.getLogger("ops_sweeper")


@dataclass
class Deps:
    """What the loop needs: its connection, the admin client, the issuer whose rows it owns, the cadence."""

    conn: persistence.Conn
    admin: keycloak_admin.AdminUsers
    issuer: str
    tick_seconds: float
    worker_name: str
    allow_mass: bool = False  # the owner's override of the listing guard, cleared by the first good sync (ruling 27)
    last_sync_at: float | None = None  # monotonic time of the last successful sync
    sink: outbox.Sink = field(default_factory=outbox.LogSink)  # T14: the v1 sink, no egress (Plan I ruling 14)
    outbox_settings: OutboxSettings = field(default_factory=OutboxSettings)
    wakeup_settings: WakeupSettings = field(default_factory=WakeupSettings)


def minute_bucket(at: datetime) -> str:
    """The minute bucket of the sync job's dedup key (`ops_core.jobs.dedup_key` builds `sync_memberships:<bucket>`)."""
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M")


def fresh(last_sync_at: float | None, now: float) -> bool:
    """Whether the last successful sync is inside the gate's window."""
    return last_sync_at is not None and now - last_sync_at < FRESH_SECONDS


def consume_override(deps: Deps) -> None:
    """The mass-deactivation override covers the first successful sync only (final review M1): a later broken
    listing in the same process is refused again."""
    if deps.allow_mass:
        deps.allow_mass = False
        log.info("mass-deactivation override consumed")


async def confirm_absences(deps: Deps, users: dict[UUID, bool]) -> dict[UUID, bool]:
    """The listing plus every active subject it lacks, asked one by one (final review M2): offset paging can skip a
    user when another is deleted between pages, and nothing reactivates a deactivated membership. False (a 404 or
    disabled) confirms the absence; True is the paging race, so the subject is kept this round. A listing the guard
    refuses is returned as it is, so a wrong realm (where every lookup 404s) still trips the guard, not the users.

    Raises:
        AdminUnavailable: a lookup failed; the caller stamps nothing.
    """
    active = await sync.active_subjects(deps.conn, deps.issuer)
    if not deps.allow_mass and sync.refuse(active, users):
        return users
    confirmed = dict(users)
    for subject in sorted(s for s in active if s not in users):
        confirmed[subject] = await deps.admin.enabled(subject)
    return confirmed


async def run_sync(deps: Deps) -> bool:
    """One sync: list the realm, confirm the absences, apply the plan, stamp. False (and a log line) when the
    listing or a confirmation failed or the plan was refused; then nothing is stamped and no job row is recorded."""
    try:
        users = await confirm_absences(deps, await deps.admin.list_enabled())
    except AdminUnavailable as exc:
        log.warning("membership sync skipped: %s", exc)
        return False
    try:
        result = await sync.sync_memberships(deps.conn, issuer=deps.issuer, users=users, allow_mass=deps.allow_mass)
    except sync.MassDeactivation as exc:
        log.error("membership sync refused (set OPS_SYNC_ALLOW_MASS_DEACTIVATION=1 once to accept it): %s", exc)
        return False
    deps.last_sync_at = time.monotonic()
    log.info("membership sync: %d rows checked, %d deactivated", result.checked, result.deactivated)
    consume_override(deps)
    return True


async def tick(deps: Deps) -> None:
    """Sync; if it succeeded, record this minute's maintenance job (insert, claim, finish); purge expired rows; hand
    back the jobs of dead or lost run leases (T13); re-arm lost wake-ups, then deliver the outbox (T14), last, so a
    database error during delivery never stops run progress (a sink's crash is one row's failed attempt). Everything
    after the sync runs whether or not Keycloak answered."""
    if await run_sync(deps):
        await record(deps, JobType.SYNC_MEMBERSHIPS)
    counts = await sync.purge_expired(deps.conn)
    if any(counts.values()):
        log.info("purged expired rows: %s", counts)
    reclaimed = await leases.reclaim(deps.conn)
    if reclaimed:
        log.info("reclaimed %d job(s) whose run lease was not live", len(reclaimed))
    await sweep_wakeups(deps)  # first: notification delivery must never starve run progress (round 1, I1)
    await deliver_outbox(deps)


async def sweep_wakeups(deps: Deps) -> None:
    """Re-arm the lost wake-ups of every tenant, purge finished maintenance rows past their retention, then record
    this minute's `sweep_wakeups` row (rulings 8, 19, 20)."""
    found = await wakeups.sweep(deps.conn, deps.wakeup_settings)
    purged = await wakeups.purge_maintenance(deps.conn, deps.wakeup_settings)
    rearmed = [w for w in found if w.rearmed]
    if rearmed:
        log.info(
            "re-armed %d lost wake-up(s): %s", len(rearmed), ", ".join(f"{w.job_type} {w.run_id}" for w in rearmed)
        )
    if purged:
        log.info("purged %d finished maintenance job row(s)", purged)
    await record(deps, JobType.SWEEP_WAKEUPS)


async def deliver_outbox(deps: Deps) -> None:
    """This minute's `deliver_outbox` record first (ruling 19: the audit row of the attempt), then the delivery loop
    over every tenant, then `notification.failed` for every dead letter that lacks it (the result units first, the
    events after, SA:188). A sink's crash is one row's failed attempt (`outbox.deliver`'s sink boundary, round 2,
    N1); a database error propagates to the loop's catch-all after the record, and the rows it left claimed come back
    when their lease ends (dead-lettered by the claim once their attempts reached the cap, round 1, I1)."""
    await record(deps, JobType.DELIVER_OUTBOX)
    results = await outbox.deliver(deps.conn, deps.sink, deps.outbox_settings)
    announced = await outbox.notify_dead_letters(deps.conn)
    if results or announced:
        outcomes = [r.result for r in results]
        log.info(
            "outbox: %d delivered, %d retrying, %d dead-lettered, %d announced",
            outcomes.count("delivered"),
            outcomes.count("retrying"),
            outcomes.count("dead_letter"),
            len(announced),
        )


async def record(deps: Deps, job_type: JobType) -> None:
    """The minute's maintenance row of `job_type`, done in the same transaction: an audit record, never a trigger. A
    second tick in the same minute finds the key taken and records nothing new; its work ran anyway (ruling 19)."""
    async with deps.conn.transaction():
        # The bucket is a wall-clock label (the audit key); `available_at` and the claim use the application clock.
        bucket = minute_bucket(datetime.now(UTC))
        job_id = await persistence.insert_maintenance_job(deps.conn, job_type, bucket)
        if job_id is None:
            return  # this minute is already recorded (an earlier tick, or another sweeper instance)
        job = await persistence.claim_maintenance_job(
            deps.conn, job_type=job_type, worker_name=deps.worker_name, job_id=job_id
        )
        if job is None:
            # Unreachable with today's own-row claim; if it ever happens the row would sit unclaimed (final review M6).
            log.warning("the %s job row just inserted could not be claimed; it is left for inspection", job_type.value)
            return
        await persistence.finish_job(deps.conn, job["id"])


async def run_forever(deps: Deps, stop: asyncio.Event) -> None:
    """Tick, sleep, repeat; a broken connection ends the loop (readiness follows), anything else is logged."""
    while not stop.is_set():
        try:
            await tick(deps)
        except psycopg.OperationalError:
            if deps.conn.broken or deps.conn.closed:
                log.exception("database connection lost; the sweeper stops and exits non-zero")
                raise
            log.exception("transient database error; the loop continues")
        except Exception:  # one bad tick must not stop the scheduler (the worker's loop makes the same choice)
            log.exception("sweeper tick failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=deps.tick_seconds)
        except TimeoutError:
            pass


def health_app(probe: persistence.Conn, is_fresh: Callable[[], bool]) -> Starlette:
    """Readiness: the database answers and the last sync is fresh (so a sweeper whose Keycloak is gone says so)."""

    async def live(_: Request) -> JSONResponse:
        """The process is up."""
        return JSONResponse({"status": "live"})

    async def ready(_: Request) -> JSONResponse:
        """The database answers and the last sync is fresh."""
        try:
            await probe.execute("SELECT 1")
        except (psycopg.Error, OSError):
            return JSONResponse({"status": "not ready"}, status_code=503)
        if not is_fresh():
            return JSONResponse({"status": "not ready", "reason": "no fresh membership sync"}, status_code=503)
        return JSONResponse({"status": "ready"})

    return Starlette(routes=[Route("/health/live", live), Route("/health/ready", ready)])


async def _main() -> None:
    redaction.install()  # the redaction filter must be on the root handler before the first log line
    kc = settings.keycloak()
    admin = keycloak_admin.admin_users(
        keycloak=kc, client_secret=settings.read_secret("kc_client_secret_ops_view_users"), timeout=20.0
    )
    opened: list[persistence.Conn] = []
    try:
        conn = await persistence.connect(settings.app_postgres(Role.SWEEPER))
        opened.append(conn)
        probe = await persistence.connect(settings.app_postgres(Role.SWEEPER))
        opened.append(probe)
        await persistence.assert_clock_profile(probe, settings.profile())
        await persistence.assert_relation(probe, "app.outbox")  # revision 0008: the outbox this process delivers
        chosen_outbox = settings.outbox()  # refused before the loop starts, like every other setting
        chosen_wakeups = settings.wakeups()
    except BaseException:  # close what was built before the tasks exist (a refused start must not leak sockets)
        await admin.aclose()
        for opened_conn in opened:
            await opened_conn.close()
        raise
    deps = Deps(
        conn=conn,
        admin=admin,
        issuer=kc.issuer,
        tick_seconds=float(settings.env_int("OPS_SYNC_TICK_SECONDS", 30)),
        worker_name=f"sweeper:{socket.gethostname()}:{os.getpid()}",
        allow_mass=os.environ.get("OPS_SYNC_ALLOW_MASS_DEACTIVATION") == "1",
        sink=outbox.LogSink(),  # no fault route in any profile: the live tests build their own sink (ruling 14)
        outbox_settings=chosen_outbox,
        wakeup_settings=chosen_wakeups,
    )
    stop = asyncio.Event()
    loop_task = asyncio.create_task(run_forever(deps, stop), name="sweeper-loop")
    server = uvicorn.Server(
        uvicorn.Config(
            health_app(probe, lambda: fresh(deps.last_sync_at, time.monotonic())),
            host="127.0.0.1",
            port=settings.env_int("OPS_SWEEPER_HEALTH_PORT", 8071),
            log_level="warning",
            log_config=None,
        )
    )
    serving = asyncio.create_task(server.serve(), name="health-server")
    try:
        await asyncio.wait({serving, loop_task}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        stop.set()
        server.should_exit = True
        await asyncio.gather(serving, loop_task, return_exceptions=True)
        await admin.aclose()
        await conn.close()
        await probe.close()
    for task in (loop_task, serving):
        if task.done() and not task.cancelled() and task.exception() is not None:
            raise SystemExit(1)


def main() -> None:
    """Run the sweeper until a signal or a lost database connection."""
    if sys.platform == "win32":
        asyncio.run(_main(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(_main())

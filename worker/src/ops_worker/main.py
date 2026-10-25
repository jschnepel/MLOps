"""The worker process: a polling loop beside a health server and the lease heartbeat thread, four connections (the
loop's, the probe's, the heartbeat's synchronous one and the checkpoint saver's, T20), SelectorEventLoop on Windows
(psycopg async refuses the Proactor loop; measured in the Plan D spike; the heartbeat's synchronous connection is not
bound by that).

Each poll claims the next job together with its run's lease (`persistence.claim_next`, Plan H ruling 3) and runs the
handler under that lease while the heartbeat renews it; a lost lease cancels the job's effects in flight and hands the
job back (`handlers.abandon`, ruling 19) and the loop moves on."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import sys
from collections.abc import Callable
from uuid import UUID

import psycopg
import uvicorn
from ops_core import persistence, redaction, settings
from ops_core.lease import LeaseLost
from ops_core.settings import Role, SettingsError
from ops_core.tokens import WorkloadTokenSource
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ops_worker import handlers
from ops_worker.drafting import ModelStartError, start_route
from ops_worker.graph.build import open_saver
from ops_worker.heartbeat import Heartbeat, Liveness, connector, keep_stamping
from ops_worker.mcp import HttpMcpCaller

POLL_SECONDS = 0.5
MAX_DEFERRALS = 16  # busy-lease deferrals one poll makes before it sleeps (each moves one job behind its lease)
# Bounds every unit's lock wait on the loop connection (review round 2, m1); SET takes no bind parameter.
LOOP_LOCK_TIMEOUT = "SET lock_timeout = '10s'"
log = logging.getLogger("ops_worker")


def rotate(tenants: list[UUID], start: int) -> list[UUID]:
    """The tenants in claim order for one poll: a different first tenant each time, so none starves (ruling 18)."""
    if not tenants:
        return []
    k = start % len(tenants)
    return tenants[k:] + tenants[:k]


async def claim(deps: handlers.Deps, order: list[UUID]) -> persistence.Claimed | None:
    """The next job with its run's lease, past at most MAX_DEFERRALS jobs whose run lease was busy (ruling 3)."""
    for _ in range(MAX_DEFERRALS):
        got = await persistence.claim_next(
            deps.conn, worker_name=deps.worker_name, tenant_ids=order, lease_seconds=deps.leases.lease_seconds
        )
        if not isinstance(got, persistence.Deferred):
            return got
    return None


async def run_job(deps: handlers.Deps, claimed: persistence.Claimed) -> None:
    """Run one claimed job under its lease while the heartbeat renews it. A lost lease, raised by a fenced unit or by
    an effect the heartbeat cancelled (`Lease.effect`), hands the job back instead of failing the run (ruling 19 as
    amended in review round 1, B1: only effects are cancelled, never a database unit, so the loop connection is idle
    when `abandon` runs, and `abandon` checks that). Anything else propagates after `handle` released the lease and
    closed the job (T20 review, M2): the poll loop logs it, and the sweeper re-arms a run still waiting."""
    job, lease = dict(claimed.job), claimed.lease
    if deps.heartbeat is not None:
        deps.heartbeat.hold(lease)
    try:
        await handlers.handle(deps, job, lease)
    except LeaseLost:
        log.warning("job %s: run lease lost (%s); handles revoked, job handed back", job["id"], lease.lost)
        await handlers.abandon(deps, job, lease)
    finally:
        if deps.heartbeat is not None:
            deps.heartbeat.drop(lease)


async def run_forever(deps: handlers.Deps, stop: asyncio.Event) -> None:
    """Claim, handle, repeat. A crashed handler is logged and keeps its job claimed until the lease lapses and the
    sweeper reclaims it; a broken connection ends the loop, and readiness follows it (see health_app)."""
    polls = 0
    while not stop.is_set():
        try:
            order = rotate(await persistence.tenants(deps.conn), polls)
            polls += 1
            claimed = await claim(deps, order)
            if claimed is not None:
                await run_job(deps, claimed)
                continue
        except psycopg.OperationalError:
            if deps.conn.broken or deps.conn.closed:
                log.exception("database connection lost; the poll loop stops and the process exits non-zero")
                raise
            log.exception("transient database error (deadlock, serialization); the loop continues")
        except Exception:  # a crashed handler keeps its job until the lease lapses and the sweeper reclaims it
            log.exception("poll iteration failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=POLL_SECONDS)
        except TimeoutError:
            pass


def health_app(
    probe: persistence.Conn, polling_alive: Callable[[], bool], heartbeat_alive: Callable[[], bool]
) -> Starlette:
    """Readiness on its own connection and only while the poll loop and the heartbeat thread run: sharing the loop's
    connection let a health call wedge it idle-in-transaction, and a dead loop behind a 200 is the same lie (round-1
    and round-2 reviews). Without the thread the loop would claim jobs it can neither renew nor cancel (final review,
    M4)."""

    async def live(_: Request) -> JSONResponse:
        return JSONResponse({"status": "live"})

    async def ready(_: Request) -> JSONResponse:
        if not polling_alive():
            return JSONResponse({"status": "not ready", "reason": "poll loop stopped"}, status_code=503)
        if not heartbeat_alive():
            return JSONResponse({"status": "not ready", "reason": "heartbeat thread stopped"}, status_code=503)
        try:
            await probe.execute("SELECT 1")  # autocommit: no transaction is left open
        except (psycopg.Error, OSError):
            return JSONResponse({"status": "not ready"}, status_code=503)
        return JSONResponse({"status": "ready"})

    return Starlette(routes=[Route("/health/live", live), Route("/health/ready", ready)])


def token_source(kc: settings.Keycloak) -> WorkloadTokenSource:
    """The worker's workload tokens, issued to the client the settings name (Plan K ruling 12); its client id is also
    the `azp` every handle is minted with (`handlers.Deps.workload_azp`, Plan J ruling 17)."""
    return WorkloadTokenSource(
        token_url=kc.token_url,
        client_id=settings.workload_client_id(),
        client_secret=settings.read_secret("kc_client_secret_ops_worker"),
    )


async def _main() -> None:
    # The redaction filter must sit on the root handler before the first log line (T11 note 4).
    redaction.install()
    try:
        # Unset or any other route refuses to start (R130); the real route checks its digest and warms up first
        # (R127), before any database connection or claim, so no job ever waits on a model that is not ready. An unset
        # MODEL_MODE is a SettingsError here; start_route turns the route's own settings errors into ModelStartError.
        generator = await start_route(settings.env("MODEL_MODE"))
    except (ModelStartError, SettingsError) as exc:
        log.error("the worker refuses to start: %s", exc)
        raise SystemExit(1) from exc
    leases = settings.leases()  # an unsafe lease, heartbeat, stall or budget combination refuses to start
    kc = settings.keycloak()
    tokens = token_source(kc)
    conn = await persistence.connect(settings.app_postgres(Role.WORKER))
    # No unit is ever cancelled, so a unit stuck behind another transaction's lock ends after 10 s with 55P03, which
    # run_forever logs as transient; its job keeps the claim until the lease lapses and the sweeper reclaims it.
    await conn.execute(LOOP_LOCK_TIMEOUT)
    # The health server's own connection (see health_app).
    probe = await persistence.connect(settings.app_postgres(Role.WORKER))
    await persistence.assert_clock_profile(probe, settings.profile())
    await persistence.assert_relation(probe, "app.model_permit")  # revision 0007: the permit and the fenced functions
    await persistence.assert_relation(probe, "app.run_manifests")  # revision 0014: every run's manifest (T19)
    await persistence.assert_relation(probe, "checkpoints.checkpoints")  # revision 0015: the graph's saver (T20)
    # The saver's own connection (SA:559-562): its writes never share a transaction with an application unit.
    saver_conn, saver = await open_saver(settings.app_postgres(Role.WORKER))
    liveness = Liveness()
    heartbeat = Heartbeat(connect=connector(settings.app_postgres(Role.WORKER)), settings=leases, liveness=liveness)
    deps = handlers.Deps(
        conn=conn,
        mcp=HttpMcpCaller(tokens),
        generator=generator,
        urls=settings.urls(),
        worker_name=f"{socket.gethostname()}:{os.getpid()}",
        workload_azp=tokens.client_id,
        leases=leases,
        heartbeat=heartbeat,
        saver=saver,
    )
    stop = asyncio.Event()
    stamps_stop = asyncio.Event()  # its own event: the stamps must outlive the job a shutdown lets finish
    heartbeat.start()  # idle until the first claim hands it a lease (ruling 16)
    stamping = asyncio.create_task(keep_stamping(liveness, stamps_stop), name="loop-liveness")
    polling = asyncio.create_task(run_forever(deps, stop), name="poll-loop")
    server = uvicorn.Server(
        uvicorn.Config(
            health_app(probe, lambda: not polling.done(), heartbeat.is_alive),
            host="127.0.0.1",
            port=settings.env_int("OPS_WORKER_HEALTH_PORT", 8070),
            log_level="warning",
            log_config=None,
        )
    )
    serving = asyncio.create_task(server.serve(), name="health-server")
    try:
        # Whichever ends first ends the process: uvicorn on SIGINT/SIGTERM, the poll loop on a lost connection.
        await asyncio.wait({serving, polling}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        stop.set()
        server.should_exit = True
        await asyncio.gather(serving, polling, return_exceptions=True)
        # Shutdown cancels nothing: on SIGINT the poll loop finishes its current job first, so the liveness stamps
        # stop only now, or that job would lose its lease to "event loop stalled" (review round 2, m2). SIGTERM is not
        # drained: uvicorn 0.54 re-raises the captured signal once serve() returns, and SIGTERM's default handler ends
        # the process mid-job. Safety holds (the open unit rolls back, the lease lapses and the sweeper hands the job
        # back), but an investigate run is failed as interrupted (final review, M2). TODO(T30): drain on SIGTERM.
        stamps_stop.set()
        await stamping
        heartbeat.stop()
        await asyncio.to_thread(heartbeat.join, 5.0)  # off the loop: the thread ends its tick and closes its connection
        await conn.close()
        await probe.close()
        await saver_conn.close()
    # A supervisor restarts a worker that lost its database or its health server; exit 0 would hide either.
    for task in (polling, serving):
        if task.done() and not task.cancelled() and task.exception() is not None:
            raise SystemExit(1)


def main() -> None:
    """Run the worker until a signal or a lost database connection."""
    if sys.platform == "win32":
        asyncio.run(_main(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(_main())

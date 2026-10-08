"""The worker process: a polling loop beside a health server, two connections (the loop's and the probe's),
SelectorEventLoop on Windows (psycopg async refuses the Proactor loop; measured in the Plan D spike)."""

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
from ops_core import persistence, settings
from ops_core.settings import Role
from ops_core.tokens import WorkloadTokenSource
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ops_worker import handlers
from ops_worker.drafting import make_generator
from ops_worker.mcp import HttpMcpCaller

POLL_SECONDS = 0.5
log = logging.getLogger("ops_worker")


def rotate(tenants: list[UUID], start: int) -> list[UUID]:
    """The tenants in claim order for one poll: a different first tenant each time, so none starves (ruling 18)."""
    if not tenants:
        return []
    k = start % len(tenants)
    return tenants[k:] + tenants[:k]


async def run_forever(deps: handlers.Deps, stop: asyncio.Event) -> None:
    """Claim, handle, repeat. A failed handler is logged and its job stays claimed (T13 reclaims); a broken
    connection ends the loop, and readiness follows it (see health_app)."""
    polls = 0
    while not stop.is_set():
        try:
            async with deps.conn.transaction():
                order = rotate(await persistence.tenants(deps.conn), polls)
                job = await persistence.claim_job(deps.conn, worker_name=deps.worker_name, tenant_ids=order)
            polls += 1
            if job is not None:
                await handlers.handle(deps, dict(job))
                continue
        except psycopg.OperationalError:
            if deps.conn.broken or deps.conn.closed:
                log.exception("database connection lost; the poll loop stops and the process exits non-zero")
                raise
            log.exception("transient database error (deadlock, serialization); the loop continues")
        except Exception:  # a crashed handler leaves the job claimed for T13's reclaim; the loop lives on
            log.exception("poll iteration failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=POLL_SECONDS)
        except TimeoutError:
            pass


def health_app(probe: persistence.Conn, polling_alive: Callable[[], bool]) -> Starlette:
    """Readiness on its own connection and only while the poll loop runs: sharing the loop's connection let a health
    call wedge it idle-in-transaction, and a dead loop behind a 200 is the same lie (round-1 and round-2 reviews)."""

    async def live(_: Request) -> JSONResponse:
        return JSONResponse({"status": "live"})

    async def ready(_: Request) -> JSONResponse:
        if not polling_alive():
            return JSONResponse({"status": "not ready", "reason": "poll loop stopped"}, status_code=503)
        try:
            await probe.execute("SELECT 1")  # autocommit: no transaction is left open
        except (psycopg.Error, OSError):
            return JSONResponse({"status": "not ready"}, status_code=503)
        return JSONResponse({"status": "ready"})

    return Starlette(routes=[Route("/health/live", live), Route("/health/ready", ready)])


async def _main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    generator = make_generator(settings.env("MODEL_MODE"))  # unset or any other route: refuse to start (R130)
    kc = settings.keycloak()
    tokens = WorkloadTokenSource(
        token_url=kc.token_url,
        client_id="ops-worker",
        client_secret=settings.read_secret("kc_client_secret_ops_worker"),
    )
    conn = await persistence.connect(settings.app_postgres(Role.WORKER))
    # The health server's own connection (see health_app).
    probe = await persistence.connect(settings.app_postgres(Role.WORKER))
    await persistence.assert_clock_profile(probe, settings.profile())
    deps = handlers.Deps(
        conn=conn,
        mcp=HttpMcpCaller(tokens),
        generator=generator,
        urls=settings.urls(),
        worker_name=f"{socket.gethostname()}:{os.getpid()}",
    )
    stop = asyncio.Event()
    polling = asyncio.create_task(run_forever(deps, stop), name="poll-loop")
    server = uvicorn.Server(
        uvicorn.Config(
            health_app(probe, lambda: not polling.done()),
            host="127.0.0.1",
            port=settings.env_int("OPS_WORKER_HEALTH_PORT", 8070),
            log_level="warning",
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
        await conn.close()
        await probe.close()
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

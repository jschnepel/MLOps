"""mcp-read's T15 cases over a real socket with Keycloak's tokens (OPS_LIVE=1; R027, R085, R131 read half, T15 DoD 2-4;
Plan J rulings 5, 10, 11 and 22).

The server is `production_app()` under uvicorn on a free loopback port in the test's own event loop; the
independent-process run is tests/e2e/test_mcp_read_process_live.py. Catches: a handle that still answers once its job
is pointed at another run's job, past its expiry, under a lapsed lease or a moved fence, after its release
(revocation), or once its run left the job type's states; an execute or recover handle answered at mcp-read, also when
its stored `server` column lies; a tool mcp-read does not register answered; an EXECUTE grant `mcp_read` holds beyond
`current_time` and `resolve_invocation`; a POST whose protocol version is absent, handshake-era or contradicted by its
`_meta` reaching the tool; and a raw handle in any log record of the exchange (uvicorn's included, at DEBUG). Every
refusal of a presented handle must be the one plain `INVALID_HANDLE` envelope, with no hint of which check failed and
never an `action_id` (SA:354-355).
"""

import asyncio
import json
import logging
import socket
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
import uvicorn
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_types import CallToolResult
from ops_core import persistence, privileges, settings
from ops_core.jobs import Server
from ops_core.mcp_protocol import PROTOCOL_VERSION
from ops_core.settings import Role
from ops_core.tokens import WorkloadTokenSource
from ops_mcp_read.server import production_app

from tests.e2e.conftest import expire_lease, lease_for, purge_run
from tests.e2e.test_definers_run_path_live import refused
from tests.e2e.test_fenced_definers_live import investigate_job, read_handle
from tests.e2e.test_mcp_write_live import approved_run
from tests.e2e.test_migrations_and_persistence import new_run

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")  # the seeded tenant: only seeded tenants have a fixture corpus
QUERY = {"query": "reviewer inspect exact content", "limit": 2, "mode": "lexical"}
REFUSAL = {"code": "INVALID_HANDLE", "message": "invocation handle rejected", "retryable": False}
EVIDENCE = Path("reports/mcp-read/t15-mcp-read.txt")
UVICORN = ("uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi")
EXPECTED_LINES = 5  # one per test below


@pytest.fixture(scope="module")
def lines() -> Iterator[list[str]]:
    out = [f"T15 mcp-read — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"]
    yield out
    if len(out) != 1 + EXPECTED_LINES:  # a failed or partial run leaves the committed file as it was
        return
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


def free_port() -> int:
    """A loopback port nobody holds right now (the skeleton's own mcp-read may be up on 8081)."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


async def guarded(server: uvicorn.Server) -> None:
    """`server.serve()`, with a failed start turned into an ordinary error: uvicorn answers a lifespan failure (a
    database without revision 0009, keys it cannot load) with `sys.exit`, and a SystemExit escaping a task leaves the
    event loop at once, so the test's `finally` (its purges) would never run."""
    try:
        await server.serve()
    except SystemExit as exc:
        raise RuntimeError("mcp-read did not start; see the log above") from exc


@asynccontextmanager
async def serving(log_level: str = "warning") -> AsyncIterator[str]:
    """`production_app()` on a free loopback port, logging as `serve_app` does (`log_config=None`, so every record
    reaches the root logger) at `log_level` (`serve_app` pins "warning"; never "trace", at which uvicorn's message
    logger writes every request's headers); its URL; stopped in `finally` (uvicorn's own shutdown, never a cancel)."""
    port = free_port()
    config = uvicorn.Config(production_app(), host="127.0.0.1", port=port, log_level=log_level, log_config=None)
    server = uvicorn.Server(config)
    task = asyncio.create_task(guarded(server))
    try:
        while not server.started:
            if task.done():
                task.result()  # a failed start raises its RuntimeError here instead of waiting for ever
            await asyncio.sleep(0.05)
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        server.should_exit = True
        await asyncio.wait({task})  # settled, never cancelled; a failed start was raised above
    # Reached only when the body did not raise: a failure after the start (the main loop, the shutdown) surfaces here
    # rather than only in uvicorn's log.
    failure = None if task.cancelled() else task.exception()
    if failure is not None:
        raise failure


async def worker_token(secret: Callable[[str], str]) -> str:
    kcs = settings.keycloak()
    source = WorkloadTokenSource(
        token_url=kcs.token_url, client_id="ops-worker", client_secret=secret("kc_client_secret_ops_worker")
    )
    return await source.token()


async def call(
    url: str, token: str, handle: str, tool: str = "search_procedures", arguments: dict[str, Any] = QUERY
) -> CallToolResult:
    """One tool call with the official client pinned to 2026-07-28, the token and the handle as headers."""
    headers = {"Authorization": f"Bearer {token}", "X-Ops-Invocation": handle}
    async with (
        httpx2.AsyncClient(headers=headers) as http,
        Client(streamable_http_client(url, http_client=http), mode=PROTOCOL_VERSION) as client,
    ):
        return await client.call_tool(tool, arguments)


def assert_refused(result: CallToolResult) -> None:
    """The one plain refusal: an envelope, not a transport error; no hint of the cause and no action id."""
    doc = result.structured_content
    assert not result.is_error and isinstance(doc, dict)
    assert doc["status"] == "error" and doc["error"] == REFUSAL and doc["data"] is None
    assert "action_id" not in json.dumps(doc)


def assert_answered(result: CallToolResult) -> None:
    doc = result.structured_content
    assert not result.is_error and isinstance(doc, dict) and doc["status"] == "ok"
    assert doc["data"]["results"][0]["evidence_id"] == "ALPHA-INCIDENT:v2:review"


async def set_job(app_conn: persistence.Conn, handle: str, job: UUID) -> None:
    """The superuser rewrites the handle's job (invocation_context has no RLS: SA:523; a compromised worker could)."""
    await app_conn.execute(
        "UPDATE app.invocation_context SET job_id = %s WHERE handle_sha256 = %s", (job, persistence.handle_hash(handle))
    )


async def test_r027_a_handle_dies_with_its_job_expiry_lease_fence_and_release(
    app_conn: persistence.Conn, role_conn: RoleConn, secret: Callable[[str], str], lines: list[str]
) -> None:
    """Each cause is undone before the next (the job put back, the clock reset), and the same handle answers again
    in between, so each refusal is that cause's."""
    api, worker, harness = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.TEST_HARNESS)
    _, _, run = await new_run(app_conn, ALPHA, api=api)
    _, _, other = await new_run(app_conn, ALPHA, api=api)
    token = await worker_token(secret)
    try:
        async with serving() as url:
            job = await investigate_job(app_conn, run)
            first = await lease_for(worker, run, owner="t15-first", seconds=600)  # outlives the clock step below
            handle = await read_handle(worker, run, job, first)
            assert_answered(await call(url, token, handle))
            await set_job(app_conn, handle, await investigate_job(app_conn, other))
            assert_refused(await call(url, token, handle))  # other run: the job named is another run's
            await set_job(app_conn, handle, job)
            assert_answered(await call(url, token, handle))
            try:
                await harness.execute("UPDATE app.test_clock SET clock_offset = interval '120 seconds'")
                assert_refused(await call(url, token, handle))  # expired: 60 s TTL, the 600 s lease still live
            finally:
                await harness.execute("UPDATE app.test_clock SET clock_offset = interval '0'")
            assert_answered(await call(url, token, handle))
            await expire_lease(app_conn, run)
            assert_refused(await call(url, token, handle))  # a lapsed lease
            second = await lease_for(worker, run, owner="t15-second", seconds=600)
            assert_refused(await call(url, token, handle))  # a live lease again, but the fence moved
            fresh = await read_handle(worker, run, job, second)
            assert_answered(await call(url, token, fresh))
            async with worker.transaction():  # what the job's release does: this fence's handles and older ones
                assert await persistence.revoke_handles(worker, run, second.fence) == 2  # erratum 55
            assert_refused(await call(url, token, fresh))  # replayed after its release
        lines.append("R027 refused over HTTP: other-run job, expired, lapsed lease, moved fence, released; ok between")
    finally:
        await purge_run(app_conn, run)
        await purge_run(app_conn, other)


async def test_r085_r131_the_server_derives_tool_server_and_state_from_the_job(
    app_conn: persistence.Conn, role_conn: RoleConn, secret: Callable[[str], str], lines: list[str]
) -> None:
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    _, run, _, execute_handle = await approved_run(app_conn, api=api, worker=worker)
    _, _, read_run = await new_run(app_conn, ALPHA, api=api)
    token = await worker_token(secret)
    try:
        # A recover job of the same run, staged by the superuser as mark_unknown would queue one (T15 DoD 4 names
        # execute and recover handles); its handle is minted under the lease approved_run took.
        recover = uuid4()
        await app_conn.execute(
            "INSERT INTO app.jobs (id, type, tenant_id, run_id, dedup_key) VALUES (%s, 'recover', %s, %s, %s)",
            (recover, ALPHA, run, f"{uuid4()}:timeout"),
        )
        cur = await app_conn.execute("SELECT fence FROM app.run_lease WHERE run_id = %s", (run,))
        fence = int((await cur.fetchone())["fence"])
        async with worker.transaction():
            recover_handle = await persistence.mint_handle(
                worker, run_id=run, job_id=recover, server=Server.WRITE, azp="ops-worker", fence=fence
            )
        async with serving() as url:
            assert_refused(await call(url, token, recover_handle))  # a recover handle at mcp-read (R131, DoD 4)
            assert_refused(await call(url, token, execute_handle))  # an execute handle at mcp-read (R131)
            await app_conn.execute(
                "UPDATE app.invocation_context SET server = 'read' WHERE handle_sha256 = %s",
                (persistence.handle_hash(execute_handle),),
            )
            assert_refused(await call(url, token, execute_handle))  # the lying column: the job type says write
            handle = await read_handle(
                worker, read_run, await investigate_job(app_conn, read_run), await lease_for(worker, read_run)
            )
            assert_answered(await call(url, token, handle))
            unknown = await call(url, token, handle, tool="create_incident", arguments={"proposal_id": str(uuid4())})
            # A tool outside the read jobs' set is not registered here at all: the SDK's unknown-tool error.
            assert unknown.is_error and "Unknown tool" in str(unknown.content)
            async with worker.transaction():  # the worker role's own function, as test_admission_live does
                await worker.execute(
                    "SELECT app.transition_run(%s, 'QUEUED', 'RETRIEVING', NULL, 1, '{}')", (read_run,)
                )
                await worker.execute(
                    "SELECT app.transition_run(%s, 'RETRIEVING', 'AWAITING_INPUT', NULL, 2, '{}')", (read_run,)
                )
            assert_refused(await call(url, token, handle))  # the run left investigate's states
        lines.append(
            "R085/R131 refused over HTTP: recover and execute handles, lying server column, run state;"
            " unknown tool: SDK"
        )
    finally:
        await purge_run(app_conn, run)  # the seeded tenant ALPHA stays
        await purge_run(app_conn, read_run)


async def test_r131_mcp_read_can_execute_no_write_path_function(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    """The pg_proc ACL as it is today: `current_time` (erratum 15) and `resolve_invocation`; `asset_scope` and
    `search_procedures_scoped` join with their owners, T16 and T17 (erratum 72)."""
    cur = await app_conn.execute(
        "SELECT p.proname AS name, has_function_privilege('mcp_read', p.oid, 'EXECUTE') AS allowed"
        " FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'app'"
    )
    rows = await cur.fetchall()
    assert {row["name"] for row in rows if row["allowed"]} == {"current_time", "resolve_invocation"}
    others = set(privileges.DEFINER_FUNCTIONS) - {"current_time", "resolve_invocation"}
    assert others <= {row["name"] for row in rows}  # every other definer exists, so the line above is not vacuous
    mcp_read = await role_conn(Role.MCP_READ)
    assert await refused(mcp_read, "SELECT * FROM app.grant_execution(%s, %s)", ("not-a-handle", uuid4())) == "42501"
    lines.append(f"R131 read half: mcp_read EXECUTE = current_time, resolve_invocation; {len(others)} others refused")


def raw_headers(token: str, version: str | None, method: str = "tools/list") -> dict[str, str]:
    out = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "Mcp-Method": method,
    }
    if version is not None:
        out["MCP-Protocol-Version"] = version
    return out


def tools_list(meta_version: str) -> dict[str, Any]:
    meta = {
        "io.modelcontextprotocol/protocolVersion": meta_version,
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    return {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": meta}}


async def test_the_protocol_version_is_checked_on_every_request(
    migrated: None, secret: Callable[[str], str], lines: list[str]
) -> None:
    """Ruling 5: raw POSTs with a valid worker token, so authentication passes and only the version decides."""
    token = await worker_token(secret)
    async with serving() as url, httpx2.AsyncClient() as http:
        absent = await http.post(url, json=tools_list("2026-07-28"), headers=raw_headers(token, None))
        legacy = await http.post(url, json=tools_list("2025-11-25"), headers=raw_headers(token, "2025-11-25"))
        mismatch = await http.post(url, json=tools_list("2025-11-25"), headers=raw_headers(token, "2026-07-28"))
        listed = await http.post(url, json=tools_list("2026-07-28"), headers=raw_headers(token, "2026-07-28"))
    assert (absent.status_code, absent.json()["error"]["code"]) == (400, -32022)  # the guard
    assert (legacy.status_code, legacy.json()["error"]["code"]) == (400, -32022)  # the guard
    assert "2025-11-25" not in legacy.text  # never echoed
    assert (mismatch.status_code, mismatch.json()["error"]["code"]) == (400, -32020)  # the SDK's HEADER_MISMATCH
    assert listed.status_code == 200 and [t["name"] for t in listed.json()["result"]["tools"]] == ["search_procedures"]
    lines.append("protocol: absent 400/-32022, 2025-11-25 400/-32022, header/_meta mismatch 400/-32020, matching 200")


async def test_r027_no_log_record_carries_the_handle(
    app_conn: persistence.Conn,
    role_conn: RoleConn,
    secret: Callable[[str], str],
    caplog: pytest.LogCaptureFixture,
    lines: list[str],
) -> None:
    """Every record of an answered call, a refused one and a refused raw POST, with the server's loggers and uvicorn's
    at DEBUG and no redaction filter installed: the handle is in none of them (SA:566). uvicorn's TRACE level, which
    logs request headers, is enabled nowhere (`serve_app` pins "warning"); this test does not use it either.

    If this test fails, pytest's "Captured log call" section prints the captured records, the offending one included:
    treat that output as sensitive. The handle is a test handle on `ops_test`, revoked inside the test, and the worker
    token expires within minutes, so nothing needs rotating."""
    caplog.set_level(logging.DEBUG)
    # uvicorn's loggers, as Config left them: an earlier test's default dictConfig stops "uvicorn" and "uvicorn.access"
    # propagating to the root logger caplog listens on, and Config(log_level=...) sets their levels process-wide.
    saved = {name: (logging.getLogger(name).level, logging.getLogger(name).propagate) for name in UVICORN}
    worker = await role_conn(Role.WORKER)
    _, _, run = await new_run(app_conn, ALPHA, api=await role_conn(Role.API))
    token = await worker_token(secret)
    try:
        for name in UVICORN:  # inside the try: the finally below always puts them back
            logging.getLogger(name).propagate = True
        async with serving(log_level="debug") as url:
            lease = await lease_for(worker, run)
            handle = await read_handle(worker, run, await investigate_job(app_conn, run), lease)
            assert_answered(await call(url, token, handle))
            async with worker.transaction():
                await persistence.revoke_handles(worker, run, lease.fence)
            assert_refused(await call(url, token, handle))
            async with httpx2.AsyncClient() as http:
                raw = {**raw_headers(token, "2025-11-25"), "X-Ops-Invocation": handle}
                assert (await http.post(url, json=tools_list("2025-11-25"), headers=raw)).status_code == 400
        texts = [record.getMessage() + (record.exc_text or "") for record in caplog.records]
        names = {record.name.split(".")[0] for record in caplog.records}
        assert {"uvicorn", "mcp", "httpx2"} <= names  # the server's HTTP layer, the SDK and the client were captured
        carrying = [i for i, text in enumerate(texts) if handle in text]  # indexes only: never the handle itself
        assert carrying == []
        lines.append(
            f"R027 logs: {len(texts)} records at DEBUG (uvicorn, SDK, client) across ok, refused and raw calls; none"
            " holds the handle"
        )
    finally:
        for name, (level, propagate) in saved.items():
            logging.getLogger(name).setLevel(level)
            logging.getLogger(name).propagate = propagate
        await purge_run(app_conn, run)

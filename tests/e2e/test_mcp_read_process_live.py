"""mcp-read as an independent process, reached over the network by the official SDK client (OPS_LIVE=1; R025 read
half, R031 network half, R026, T15 DoD 1-2; Plan J rulings 12, 14 and 15).

`python -m ops_mcp_read` runs as a child process on a free loopback port with the environment the skeleton gives its
children (`scripts.skeleton.process_environment`: the test profile and databases this session exported, secrets as
files named by `OPS_SECRETS_DIR`, nothing secret on the command line), and is terminated in `finally`. Catches: a
server that only works in-process (BUILD_SPEC §10: "an in-process call is not sufficient"), a tool list that differs
from the registered tool or advertises extra arguments, a locked SDK version other than AM-30's, a token for another
audience or client (the persona token stands in for a browser token, ruling 14: no real `ops-web` access token is
minted, the API stores none and minting one needs its client secret; a missing `aud` is the synthetic case in
tests/plan_j/test_verifier_t15.py, ruling 15) answered with anything but 401 on a `tools/call` that carries a valid
handle (the refusal comes before the tool and the handle lookup; mcp-read forwards nothing downstream in T15), and a
handle or a token (the worker's, or a foreign one) in the child's own log. That log is written through the service's
redaction filter (`serve()` installs it first) at uvicorn's "warning" level, so its check is weaker than the in-process
DEBUG capture of tests/e2e/test_mcp_read_t15_live.py, which runs with no filter at all.

T16: mcp-read is the only separately started process here. asset-sim is the in-process uvicorn fixture (`asset_sim`)
on a loopback port, so the asset tool's hop from the child to asset-sim, with mcp-read's own token, is a real HTTP
call; asset-sim itself does not run as a child.
"""

import asyncio
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from ops_core import persistence, settings
from ops_core.mcp_protocol import PROTOCOL_VERSION
from ops_core.settings import Role
from ops_core.tokens import WorkloadTokenSource

from scripts.skeleton import healthy, process_environment
from tests.e2e.conftest import lease_for, purge_run
from tests.e2e.test_fenced_definers_live import investigate_job, read_handle
from tests.e2e.test_mcp_read_t15_live import ANSWER, QUERY, free_port, raw_headers, tools_list, worker_token
from tests.e2e.test_migrations_and_persistence import new_run
from tests.plan_b.live import kc

# T17: the governed corpus; T16: asset-sim, whose URL the child inherits (`asset_sim` exports OPS_ASSET_SIM_URL).
pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("ingested", "asset_sim")]

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
ROOT = Path(__file__).resolve().parents[2]
ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")  # the seeded tenant, whose corpus is ingested
EVIDENCE = Path("reports/mcp-read/t15-independent-client.txt")
EXPECTED_LINES = 2  # one per test below


@pytest.fixture(scope="module")
def lines() -> Iterator[list[str]]:
    out = [f"T15 independent client — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"]
    yield out
    if len(out) != 1 + EXPECTED_LINES:  # a failed or partial run leaves the committed file as it was
        return
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


@asynccontextmanager
async def mcp_read_process(log: Path) -> AsyncIterator[str]:
    """The server as a child process; its URL once `/health/ready` answers 200 (keys loaded, database reachable,
    revision 0009 present). Terminated in `finally`, killed if it outlives 15 s; its output goes to `log`."""
    port = free_port()
    env = process_environment()  # .env-derived settings over this session's environment: PROFILE=test, ops_test
    env["OPS_MCP_READ_PORT"] = str(port)
    with log.open("ab") as out:
        # Off the loop (ruff ASYNC220): asyncio's own subprocesses need the Proactor loop, which psycopg refuses.
        child = await asyncio.to_thread(
            subprocess.Popen,
            [sys.executable, "-m", "ops_mcp_read"],
            env=env,
            stdout=out,
            stderr=subprocess.STDOUT,
            cwd=ROOT,
        )
        try:
            deadline = time.monotonic() + 60
            while not await asyncio.to_thread(healthy, f"http://127.0.0.1:{port}/health/ready"):
                # The log's path, never its content: the child's log may hold what the leak checks look for.
                assert child.poll() is None, f"mcp-read exited before it was ready; its log is {log}"
                assert time.monotonic() < deadline, f"mcp-read was not ready within 60 s; its log is {log}"
                await asyncio.sleep(0.25)
            yield f"http://127.0.0.1:{port}/mcp"
        finally:
            if child.poll() is None:
                child.terminate()  # TerminateProcess on Windows, as the skeleton stops its children
            try:
                await asyncio.to_thread(child.wait, 15)
            except subprocess.TimeoutExpired:
                child.kill()
                await asyncio.to_thread(child.wait)


async def test_r025_an_independent_client_lists_and_calls_over_the_network(
    app_conn: persistence.Conn, role_conn: RoleConn, secret: Callable[[str], str], tmp_path: Path, lines: list[str]
) -> None:
    worker = await role_conn(Role.WORKER)
    _, _, run = await new_run(app_conn, ALPHA, api=await role_conn(Role.API))
    token = await worker_token(secret)
    log = tmp_path / "mcp-read.log"
    try:
        async with mcp_read_process(log) as url:
            handle = await read_handle(worker, run, await investigate_job(app_conn, run), await lease_for(worker, run))
            headers = {"Authorization": f"Bearer {token}", "X-Ops-Invocation": handle}
            async with (
                httpx2.AsyncClient(headers=headers) as http,
                Client(streamable_http_client(url, http_client=http), mode=PROTOCOL_VERSION) as client,
            ):
                tools = (await client.list_tools()).tools
                result = await client.call_tool("search_procedures", QUERY)
                # T16 (ruling 17): an asset tool through the child, which reaches asset-sim with its own token.
                status = await client.call_tool("get_asset_status", {"asset_id": "A17"})
        assert [tool.name for tool in tools] == ["get_asset_status", "get_recent_alerts", "search_procedures"]  # T16
        assert all(tool.input_schema["additionalProperties"] is False for tool in tools)
        doc = result.structured_content
        assert not result.is_error and isinstance(doc, dict) and doc["status"] == "ok"
        assert doc["data"]["results"][0]["evidence_id"] == ANSWER  # first by a wide margin (round 1, M10)
        answered = status.structured_content
        assert not status.is_error and isinstance(answered, dict) and answered["status"] == "ok"
        assert answered["data"]["asset_id"] == "A17" and answered["data"]["data_source"] == "synthetic"
        text = log.read_text(encoding="utf-8", errors="replace")
        leaked = any(value in text for value in (handle, token))  # one boolean: a failing assert prints its operands
        assert not leaked  # the child's own log, written through its redaction filter, holds neither
        assert (version("mcp"), version("mcp-types")) == ("2.3.0", "2.3.0")  # AM-30's lock, R031
        lines.append(
            f"R025 (read half; mcp-write with T47) / R031 (network half): child process; official client mode"
            f" {PROTOCOL_VERSION} listed the three read tools, called search_procedures and get_asset_status ok"
        )
    finally:
        await purge_run(app_conn, run)


def tools_call() -> dict[str, Any]:
    """A raw `tools/call` of `search_procedures` in the 2026-07-28 envelope (the shape Task 1 measured in-process)."""
    call = tools_list(PROTOCOL_VERSION)
    call["method"] = "tools/call"
    call["params"].update({"name": "search_procedures", "arguments": QUERY})
    return call


async def test_r026_foreign_tokens_are_refused_before_the_tool(
    app_conn: persistence.Conn, role_conn: RoleConn, secret: Callable[[str], str], tmp_path: Path, lines: list[str]
) -> None:
    """Each foreign token presents a valid handle on a real tool call and gets 401; the same call with the worker's
    token then answers with data, so the refusals are the tokens' and come before the tool and the handle."""
    kcs = settings.keycloak()
    persona = kc.token_password(kcs.base_url, "ops-dev-direct", "alex", secret("kc_persona_alex_password"))
    foreign = {
        "persona (aud ops-api; the browser stand-in)": persona["access_token"],
        "ops-mcp-write (aud incident-sim)": await WorkloadTokenSource(
            token_url=kcs.token_url, client_id="ops-mcp-write", client_secret=secret("kc_client_secret_ops_mcp_write")
        ).token(),
        "ops-mcp-read (aud asset-sim)": await WorkloadTokenSource(
            token_url=kcs.token_url, client_id="ops-mcp-read", client_secret=secret("kc_client_secret_ops_mcp_read")
        ).token(),
    }
    token = await worker_token(secret)
    worker = await role_conn(Role.WORKER)
    _, _, run = await new_run(app_conn, ALPHA, api=await role_conn(Role.API))
    log = tmp_path / "mcp-read.log"
    try:
        async with mcp_read_process(log) as url, httpx2.AsyncClient() as http:
            handle = await read_handle(worker, run, await investigate_job(app_conn, run), await lease_for(worker, run))

            def headers(bearer: str) -> dict[str, str]:
                base = raw_headers(bearer, PROTOCOL_VERSION, method="tools/call")
                return {**base, "Mcp-Name": "search_procedures", "X-Ops-Invocation": handle}

            answers = {}
            for name, value in foreign.items():
                response = await http.post(url, json=tools_call(), headers=headers(value))
                challenge = response.headers.get("www-authenticate", "")  # a missing header fails the comparison
                answers[name] = (response.status_code, 'error="invalid_token"' in challenge)
            accepted = await http.post(url, json=tools_call(), headers=headers(token))
        assert answers == {name: (401, True) for name in foreign}  # names and statuses only: never a token
        assert accepted.status_code == 200  # the worker's token, the same call and handle: the refusals are the tokens'
        assert accepted.json()["result"]["structuredContent"]["status"] == "ok"  # the handle was good all along
        text = log.read_text(encoding="utf-8", errors="replace")
        leaked = any(value in text for value in (*foreign.values(), token, handle))  # one boolean, never a value
        assert not leaked  # the child's log holds no foreign token, the worker's token or the handle
        lines.append(
            "R026: persona, ops-mcp-write and ops-mcp-read tokens 401 invalid_token on a tools/call with a valid"
            " handle; the worker's token answers ok"
        )
    finally:
        await purge_run(app_conn, run)

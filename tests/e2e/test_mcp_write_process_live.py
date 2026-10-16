"""mcp-write as an independent process, reached over the network by the official SDK client (OPS_LIVE=1; R025 write
half, R031 network half at mcp-write; Plan K ruling 16).

`python -m ops_mcp_write` runs as a child process on a free loopback port with the environment the skeleton gives its
children (`scripts.skeleton.process_environment`: this session's test profile and databases, secrets as files named by
`OPS_SECRETS_DIR`, nothing secret on the command line), pointed at an in-process incident-sim, and is terminated in
`finally`. The action it is asked about is made first, in-process, with the reply lost after commit, so the child's
`get_incident_receipt` has a real lookup to do and no new action to create. Catches: a server that only works
in-process (BUILD_SPEC §10), a tool list other than the three write tools or one that advertises extra arguments, a
locked SDK version other than AM-30's, a lookup through the network that creates a grant, an attempt, a job or an
incident, and a handle or a token in the child's own log (written through its redaction filter at uvicorn's "warning"
level, so a weaker check than the in-process ones).
"""

import asyncio
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from ops_core import persistence, settings
from ops_core.mcp_protocol import PROTOCOL_VERSION
from ops_core.outcomes import ToolOutcome
from ops_core.settings import Role
from ops_core.tokens import WorkloadTokenSource
from ops_incident_sim.app import production_app as incident_sim_app
from ops_mcp_write import execution

from scripts.skeleton import healthy, process_environment
from tests.e2e.conftest import purge_run
from tests.e2e.test_mcp_read_t15_live import free_port, worker_token
from tests.e2e.test_mcp_write_live import approved_run
from tests.e2e.test_mcp_write_t47_live import (
    COUNTS,
    WRITE_TOOLS,
    arm,
    at_destination,
    recover_handle,
    started,
    write_token,
)
from tests.e2e.test_migration_0010_live import AZP

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = Path("reports/mcp-write/t47-independent-client.txt")
EXPECTED_LINES = 1  # one per test below


@pytest.fixture(scope="module")
def lines() -> Iterator[list[str]]:
    out = [f"T47 independent client — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"]
    yield out
    if len(out) != 1 + EXPECTED_LINES:  # a failed or partial run leaves the committed file as it was
        return
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


@asynccontextmanager
async def mcp_write_process(log: Path, sim: str) -> AsyncIterator[str]:
    """The server as a child process; its URL once `/health/ready` answers 200 (keys loaded, database reachable,
    revisions 0009 and 0010 present). Terminated in `finally`, killed if it outlives 15 s; its output goes to `log`."""
    port = free_port()
    env = process_environment()  # .env-derived settings over this session's environment: PROFILE=test, ops_test
    env["OPS_MCP_WRITE_PORT"] = str(port)
    env["OPS_INCIDENT_SIM_URL"] = sim
    with log.open("ab") as out:
        # Off the loop (ruff ASYNC220): asyncio's own subprocesses need the Proactor loop, which psycopg refuses.
        child = await asyncio.to_thread(
            subprocess.Popen,
            [sys.executable, "-m", "ops_mcp_write"],
            env=env,
            stdout=out,
            stderr=subprocess.STDOUT,
            cwd=ROOT,
        )
        try:
            deadline = time.monotonic() + 60
            while not await asyncio.to_thread(healthy, f"http://127.0.0.1:{port}/health/ready"):
                # The log's path, never its content: the child's log may hold what the leak check looks for.
                assert child.poll() is None, f"mcp-write exited before it was ready; its log is {log}"
                assert time.monotonic() < deadline, f"mcp-write was not ready within 60 s; its log is {log}"
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


async def test_r025_an_independent_client_lists_the_write_tools_and_looks_up_a_receipt(
    app_conn: persistence.Conn,
    role_conn: RoleConn,
    incident_conn: persistence.Conn,
    secret: Callable[[str], str],
    tmp_path: Path,
    lines: list[str],
) -> None:
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    _, run, proposal, handle = await approved_run(app_conn, api=api, worker=worker)
    token, own = await worker_token(secret), await write_token(secret)
    log = tmp_path / "mcp-write.log"
    try:
        async with started(incident_sim_app(), "incident-sim") as sim:
            await arm(sim, own, "lose_after_commit")  # the action commits and its reply is lost: the attempt stays SENT
            kc = settings.keycloak()
            source = WorkloadTokenSource(
                token_url=kc.token_url,
                client_id="ops-mcp-write",
                client_secret=secret("kc_client_secret_ops_mcp_write"),
            )
            async with httpx2.AsyncClient() as http:
                deps = execution.Deps(
                    persistence.Session(await role_conn(Role.MCP_EXEC)), http, sim, destination_token=source
                )
                first = await execution.create_incident(deps, handle=handle, azp=AZP, proposal_id=proposal)
            assert first.status is ToolOutcome.UNKNOWN
            async with mcp_write_process(log, sim) as url:
                # Minted once the child is ready: the handle lives 60 s, the child may take longer to start.
                recover = await recover_handle(app_conn, worker, run, "timeout")
                cur = await app_conn.execute(COUNTS)
                before = dict(await cur.fetchone() or {})
                headers = {"Authorization": f"Bearer {token}", "X-Ops-Invocation": recover}
                async with (
                    httpx2.AsyncClient(headers=headers) as http,
                    Client(streamable_http_client(url, http_client=http), mode=PROTOCOL_VERSION) as client,
                ):
                    tools = (await client.list_tools()).tools
                    result = await client.call_tool("get_incident_receipt", {"proposal_id": str(proposal)})
            cur = await app_conn.execute(COUNTS)
            after = dict(await cur.fetchone() or {})
        assert sorted(tool.name for tool in tools) == sorted(WRITE_TOOLS)
        assert all(tool.input_schema["additionalProperties"] is False for tool in tools)
        doc = result.structured_content
        assert not result.is_error and isinstance(doc, dict) and doc["status"] == "ok"
        assert doc["data"]["status"] == "SUCCEEDED" and doc["data"]["action_id"] == str(first.action_id)
        assert after == before  # no grant, attempt, job or proposal created by the lookup
        assert await at_destination(incident_conn, first.action_id) == (("COMMITTED", None), 1)
        text = log.read_text(encoding="utf-8", errors="replace")
        leaked = any(value in text for value in (handle, recover, token, own))  # one boolean, never a value
        assert not leaked  # the child's own log, written through its redaction filter, holds none of them
        assert (version("mcp"), version("mcp-types")) == ("2.3.0", "2.3.0")  # AM-30's lock, R031
        names = ", ".join(sorted(tool.name for tool in tools))
        lines.append(
            f"R025 (write half) / R031 (network half, mcp-write): child process; official client mode"
            f" {PROTOCOL_VERSION} listed [{names}]; get_incident_receipt with a recover handle answered SUCCEEDED for"
            " the existing action; no grant, attempt, job or incident created"
        )
    finally:
        await purge_run(app_conn, run)

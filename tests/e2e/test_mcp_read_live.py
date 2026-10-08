"""mcp-read over a real socket with a real worker token and a handle minted in the database (OPS_LIVE=1; BUILD_SPEC
§10: "an in-process call is not sufficient"). Catches: the bearer middleware wired to the wrong audience, a handle
that resolves at the wrong server, and the two rejections the e2e test relies on (persona token; mcp-write's token)."""

import asyncio
from uuid import UUID

import httpx2
import pytest
import uvicorn
from mcp import Client, MCPError
from mcp.client.streamable_http import streamable_http_client
from ops_core import persistence, settings
from ops_core.jobs import Server
from ops_core.tokens import WorkloadTokenSource
from ops_mcp_read.server import production_app

from tests.e2e.conftest import purge_run
from tests.e2e.test_migrations_and_persistence import new_run
from tests.plan_b.live import kc

pytestmark = pytest.mark.asyncio


async def test_search_over_http(app_conn: persistence.Conn, secret) -> None:
    kcs = settings.keycloak()
    # Port 18081: the skeleton's own mcp-read may be up on 8081 in the same session (Task 9's fixture).
    server = uvicorn.Server(uvicorn.Config(production_app(), host="127.0.0.1", port=18081, log_level="warning"))
    url = "http://127.0.0.1:18081/mcp"
    task = asyncio.create_task(server.serve())
    run = None
    try:
        while not server.started:
            await asyncio.sleep(0.05)
        async with app_conn.transaction():  # committed: the server reads the handle on its own connection
            # The seeded alpha tenant: only seeded tenants have a fixture corpus (W11 in the round-1 dry run).
            _, _, run = await new_run(app_conn, UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7"))
            cur = await app_conn.execute("SELECT id FROM app.jobs WHERE run_id = %s", (run,))
            job = (await cur.fetchone())["id"]
            handle = await persistence.mint_handle(
                app_conn, run_id=run, job_id=job, server=Server.READ, azp="ops-worker"
            )
        worker = WorkloadTokenSource(
            token_url=kcs.token_url, client_id="ops-worker", client_secret=secret("kc_client_secret_ops_worker")
        )
        headers = {"Authorization": f"Bearer {await worker.token()}", "X-Ops-Invocation": handle}
        async with (
            httpx2.AsyncClient(headers=headers) as hc,
            Client(streamable_http_client(url, http_client=hc), mode="2026-07-28") as client,
        ):
            res = await client.call_tool(
                "search_procedures", {"query": "reviewer inspect exact content", "limit": 2, "mode": "lexical"}
            )
        assert not res.is_error and res.structured_content["status"] == "ok"
        assert res.structured_content["data"]["results"][0]["evidence_id"] == "ALPHA-INCIDENT:v2:review"
        # The persona's token (aud ops-api) and mcp-write's token (aud incident-sim) are refused at the transport.
        alex = kc.token_password(kcs.base_url, "ops-dev-direct", "alex", secret("kc_persona_alex_password"))
        for token in (
            alex["access_token"],
            await WorkloadTokenSource(
                token_url=kcs.token_url,
                client_id="ops-mcp-write",
                client_secret=secret("kc_client_secret_ops_mcp_write"),
            ).token(),
        ):
            async with (
                httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}", "X-Ops-Invocation": handle}) as hc,
                Client(streamable_http_client(url, http_client=hc), mode="2026-07-28") as client,
            ):
                with pytest.raises(MCPError):
                    await client.call_tool("search_procedures", {"query": "x", "limit": 1, "mode": "lexical"})
    finally:
        server.should_exit = True
        await task
        if run is not None:
            await purge_run(app_conn, run)

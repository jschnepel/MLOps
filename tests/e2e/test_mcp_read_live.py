"""mcp-read over a real socket with a real worker token and a handle minted in the database (OPS_LIVE=1; BUILD_SPEC
§10: "an in-process call is not sufficient"), answering from the governed corpus (T17, Plan L ruling 20). Catches: the
bearer middleware wired to the wrong audience, a handle that resolves at the wrong server, a search that does not
reach `search_procedures_scoped` (the committed corpus's section missing, another corpus version reported, a hash
that is not the section's), an asset type that does not filter, the run's own asset type (T16: A17 is a pump) not
applied when the caller names none, `vector_exact` not answered from the stored embeddings through the real local
Ollama (T18) or answered outside the run's asset type, and the two rejections the e2e test relies on (persona token;
mcp-write's token)."""

import asyncio
from uuid import UUID

import httpx2
import pytest
import uvicorn
from mcp import Client, MCPError
from mcp.client.streamable_http import streamable_http_client
from ops_core import corpus, persistence, settings
from ops_core.jobs import Server
from ops_core.settings import Role
from ops_core.tokens import WorkloadTokenSource
from ops_mcp_read.server import production_app

from scripts.skeleton import CORPUS
from tests.e2e.conftest import lease_for, purge_run
from tests.e2e.test_migrations_and_persistence import new_run
from tests.plan_b.live import kc

# T17: the governed corpus; T16: asset-sim, which the search asks for the run's asset type; T18: its embeddings.
pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("ingested", "embedded", "asset_sim")]

ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")


async def test_search_over_http(app_conn: persistence.Conn, role_conn, secret) -> None:
    kcs = settings.keycloak()
    # Port 18081: the skeleton's own mcp-read may be up on 8081 in the same session (Task 9's fixture).
    server = uvicorn.Server(uvicorn.Config(production_app(), host="127.0.0.1", port=18081, log_level="warning"))
    url = "http://127.0.0.1:18081/mcp"
    task = asyncio.create_task(server.serve())
    run = open_run = None
    try:
        while not server.started:
            await asyncio.sleep(0.05)
        # No outer transaction: the api role's connection could not see an uncommitted conversation, and the server
        # reads the handle on its own connection. The seeded alpha tenant: the `ingested` fixture put the corpus there.
        _, _, run = await new_run(app_conn, ALPHA, api=await role_conn(Role.API))
        cur = await app_conn.execute("SELECT id FROM app.jobs WHERE run_id = %s", (run,))
        job = (await cur.fetchone())["id"]
        worker_conn = await role_conn(Role.WORKER)
        lease = await lease_for(worker_conn, run)  # T13: the handle carries the lease's fence
        async with worker_conn.transaction():  # set_tenant is transaction-local and the INSERT meets RLS
            await persistence.set_tenant(worker_conn, ALPHA)
            handle = await persistence.mint_handle(
                worker_conn, run_id=run, job_id=job, server=Server.READ, azp="ops-worker", fence=lease.fence
            )
        # A run whose asset asset-sim does not know (Z99): no run asset type applies, so its search is the control
        # that reaches every asset's documents (Plan M ruling 12).
        _, _, open_run = await new_run(app_conn, ALPHA, api=await role_conn(Role.API), asset_id="Z99")
        cur = await app_conn.execute("SELECT id FROM app.jobs WHERE run_id = %s", (open_run,))
        open_job = (await cur.fetchone())["id"]
        open_lease = await lease_for(worker_conn, open_run)
        async with worker_conn.transaction():
            await persistence.set_tenant(worker_conn, ALPHA)
            open_handle = await persistence.mint_handle(
                worker_conn,
                run_id=open_run,
                job_id=open_job,
                server=Server.READ,
                azp="ops-worker",
                fence=open_lease.fence,
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
                "search_procedures", {"query": "repeated alerts on one asset", "limit": 2, "mode": "lexical"}
            )
            pumps = await client.call_tool(
                "search_procedures",
                {"query": "the reviewer records each reading", "limit": 8, "mode": "lexical", "asset_type": "pump"},
            )
            implicit = await client.call_tool(
                "search_procedures", {"query": "the reviewer records each reading", "limit": 8, "mode": "lexical"}
            )
            vector = await client.call_tool(
                "search_procedures",
                {
                    "query": "How often is the mechanical seal on pump A17 inspected?",
                    "limit": 5,
                    "mode": "vector_exact",
                },
            )
        async with (
            httpx2.AsyncClient(headers={**headers, "X-Ops-Invocation": open_handle}) as hc,
            Client(streamable_http_client(url, http_client=hc), mode="2026-07-28") as client,
        ):
            everything = await client.call_tool(
                "search_procedures", {"query": "the reviewer records each reading", "limit": 8, "mode": "lexical"}
            )
        doc = res.structured_content
        assert not res.is_error and doc["status"] == "ok" and doc["data"]["corpus_version"] == "corpus-1"
        assert doc["data"]["results"][0]["evidence_id"] == "ALPHA-ALERT-REVIEW:v1:repeated-alerts"  # rank 1
        # Every returned section carries the hash data/corpus/meta.json gives it: the bytes a reviewer can re-hash.
        governed = {d.evidence_id(s): s.sha256 for d in corpus.load(CORPUS).documents for s in d.sections}
        assert all(governed[r["evidence_id"]] == r["content_sha256"] for r in doc["data"]["results"])
        documents = {r["document_id"] for r in pumps.structured_content["data"]["results"]}
        assert documents and documents <= {"ALPHA-PUMP-SEAL", "ALPHA-ALERT-REVIEW"}  # pump documents or any-asset ones
        # No asset type named: the run's own (A17, a pump) applies all the same (Plan M ruling 12).
        assert {r["document_id"] for r in implicit.structured_content["data"]["results"]} == documents
        # The control: the same query for a run asset-sim knows no type of reaches other assets' documents, so a
        # filter that was dropped (or an empty asset type forwarded as "any") would fail the lines above.
        unfiltered = {r["document_id"] for r in everything.structured_content["data"]["results"]}
        assert unfiltered - {"ALPHA-PUMP-SEAL", "ALPHA-ALERT-REVIEW"}, unfiltered
        # T18: the same run's search in vector mode, through Ollama and the stored embeddings, on the run's asset type.
        found = vector.structured_content
        assert not vector.is_error and found["status"] == "ok", found
        assert found["data"]["retrieval_mode"] == "vector_exact" and found["data"]["corpus_version"] == "corpus-1"
        families = {d.document_id: d.asset_family for d in corpus.load(CORPUS).documents}
        assert found["data"]["results"] and all(
            families[r["document_id"]] in (None, "pump") and governed[r["evidence_id"]] == r["content_sha256"]
            for r in found["data"]["results"]
        )
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
        for made in (run, open_run):
            if made is not None:
                await purge_run(app_conn, made)

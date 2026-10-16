"""mcp-read's HTTP stack in-process (the guard, the SDK's bearer auth around McpVerifier's audience check, the
transport's per-request ladder), with a stub key source and no database (Plan J rulings 2, 4 and 5).

Catches: the guard mounted after auth (an unauthenticated client would learn whether its token was good), auth
skipped once the version is right, a header/`_meta` mismatch that the SDK no longer rejects, a token whose verified
audiences lack this server's resource accepted, a raw `tools/call` shaped differently from what the live R026 test
sends, the official client unable to list or call through the guard, and mcp-write left without the guard. The live
versions of these cases, with Keycloak's tokens over a socket, are tests/e2e/test_mcp_read_t15_live.py.
"""

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import MappingProxyType
from typing import Any

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from ops_core import persistence
from ops_core.tokens import Principal, TokenRejected
from ops_mcp_read import procedures, server
from ops_mcp_write import server as write_server
from starlette.testclient import TestClient

ISSUER = "http://localhost:18080/realms/ops-dev"
FIXTURES = Path("data/handoff-fixtures")
RESOURCE = "http://mcp-read:8081/mcp"
BASE = "http://127.0.0.1:8081"  # a loopback Host, which the SDK's DNS-rebinding guard admits
TOOLS_LIST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {
        "_meta": {
            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientCapabilities": {},
        }
    },
}


SEARCH = "search_procedures"
SEARCH_CALL = {"name": SEARCH, "arguments": {"query": "x", "limit": 1, "mode": "lexical"}}


class KeyedVerifier:
    """Maps a few fixed strings to principals, the way a real verifier would after checking a signature."""

    @property
    def ready(self) -> bool:
        return True

    async def load_keys(self) -> None:
        return None

    async def verify_async(self, token: str) -> Principal:
        audiences = {"good": (RESOURCE, "account"), "elsewhere": ("http://mcp-write:8082/mcp", "account")}
        if token not in audiences:
            raise TokenRejected("unit test")
        claims = MappingProxyType({"iss": ISSUER, "typ": "Bearer"})
        return Principal("subject", "ops-worker", audiences[token], int(time.time()) + 300, claims)


class IdleConn:
    """Stands in for the database connection the lifespan would open; nothing here reaches it."""

    async def close(self) -> None:
        return None


def read_app() -> Any:
    state = server.State(session=None, corpora=procedures.load_corpora(FIXTURES), verifier=KeyedVerifier())
    idle: Any = IdleConn()
    state.session = persistence.Session(idle)  # already set, so the lifespan opens no connection
    return server.build_app(server.build_server(state, issuer=ISSUER, resource_url=RESOURCE), state)


def headers(
    version: str | None = "2026-07-28", token: str | None = "good", method: str = "tools/list"
) -> dict[str, str]:
    out = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json", "Mcp-Method": method}
    if version is not None:
        out["MCP-Protocol-Version"] = version
    if token is not None:
        out["Authorization"] = f"Bearer {token}"
    return out


def test_the_version_rule_comes_before_authentication() -> None:
    with TestClient(read_app(), base_url=BASE) as client:
        refused = client.post("/mcp", json=TOOLS_LIST, headers=headers(version=None, token=None))
        assert refused.status_code == 400 and refused.json()["error"]["code"] == -32022
        unauthenticated = client.post("/mcp", json=TOOLS_LIST, headers=headers(token=None))
        assert unauthenticated.status_code == 401 and "resource_metadata" in unauthenticated.headers["www-authenticate"]


def test_the_ladder_and_the_resource_check_behind_the_guard() -> None:
    with TestClient(read_app(), base_url=BASE) as client:
        listed = client.post("/mcp", json=TOOLS_LIST, headers=headers())
        assert listed.status_code == 200
        assert [t["name"] for t in listed.json()["result"]["tools"]] == ["search_procedures"]
        legacy = client.post("/mcp", json=TOOLS_LIST, headers=headers(version="2025-11-25"))
        assert legacy.status_code == 400 and legacy.json()["error"]["code"] == -32022  # the guard's
        mismatch = {**TOOLS_LIST, "params": {"_meta": {**TOOLS_LIST["params"]["_meta"]}}}
        mismatch["params"]["_meta"]["io.modelcontextprotocol/protocolVersion"] = "2025-11-25"
        refused = client.post("/mcp", json=mismatch, headers=headers())
        assert refused.status_code == 400 and refused.json()["error"]["code"] == -32020  # the SDK's HEADER_MISMATCH
        elsewhere = client.post("/mcp", json=TOOLS_LIST, headers=headers(token="elsewhere"))
        assert elsewhere.status_code == 401  # its audiences lack this server's resource: McpVerifier refuses it
        call = {**TOOLS_LIST, "method": "tools/call", "params": {**TOOLS_LIST["params"], **SEARCH_CALL}}
        answered = client.post("/mcp", json=call, headers={**headers(method="tools/call"), "Mcp-Name": SEARCH})
        assert answered.status_code == 200  # the shape the live R026 test posts; no handle, so the envelope refuses
        assert answered.json()["result"]["structuredContent"]["error"]["code"] == "INVALID_HANDLE"
        assert client.get("/health/live").status_code == 200
        metadata = client.get("/.well-known/oauth-protected-resource/mcp")
        assert metadata.status_code == 200 and metadata.json()["resource"] == RESOURCE


@asynccontextmanager
async def official_client(app: Any) -> AsyncIterator[Client]:
    """The SDK's own client pinned to 2026-07-28, over an in-process transport, with the app's lifespan running."""
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with (
            httpx2.AsyncClient(transport=transport, base_url=BASE, headers={"Authorization": "Bearer good"}) as http,
            Client(streamable_http_client(f"{BASE}/mcp", http_client=http), mode="2026-07-28") as client,
        ):
            yield client


@pytest.mark.asyncio
async def test_the_official_client_lists_and_calls_through_the_guard() -> None:
    async with official_client(read_app()) as client:
        assert [t.name for t in (await client.list_tools()).tools] == ["search_procedures"]
        res = await client.call_tool("search_procedures", {"query": "x", "limit": 1, "mode": "lexical"})
    # No X-Ops-Invocation header: the tool body refuses before any lookup, as an envelope, not a transport error.
    assert not res.is_error and res.structured_content["error"]["code"] == "INVALID_HANDLE"


def test_mcp_write_carries_the_same_guard() -> None:
    state = write_server.State(deps=None, verifier=KeyedVerifier())
    app = write_server.build_app(
        write_server.build_server(state, issuer=ISSUER, resource_url="http://mcp-write:8082/mcp"), state
    )
    client = TestClient(app, base_url="http://127.0.0.1:8082")  # no lifespan: the guard answers before the SDK
    refused = client.post("/mcp", json=TOOLS_LIST, headers=headers(version=None))
    assert refused.status_code == 400 and refused.json()["error"]["code"] == -32022

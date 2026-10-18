"""mcp-read's `search_procedures` over its HTTP stack in-process, with the two database calls replaced (Plan L rulings
1, 2, 11 and 21; erratum 80).

Catches: a search run before the handle resolved, or in the same unit as the resolution; a search that is not given
the presented handle and the token's `azp` (the definer must decide the tenant from them, never from an argument); an
asset type dropped or an empty one forwarded instead of "any asset"; `vector_exact` reaching the database before
T18; a handle the definer refuses answered with anything but the one plain `INVALID_HANDLE`; and a definer refusal
escaping as a transport error instead of an envelope.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_types import CallToolResult
from ops_core import persistence
from ops_core.jobs import Tool
from ops_mcp_read import server

from tests.plan_j.test_mcp_read_http import BASE, ISSUER, RESOURCE, IdleAssets, KeyedVerifier

pytestmark = pytest.mark.asyncio

HANDLE = "unit-test-handle"
HIT = persistence.Procedure(
    evidence_id="ALPHA-PUMP-SEAL:v2:inspection",
    document_id="ALPHA-PUMP-SEAL",
    version="2",
    section="inspection",
    content_sha256="a" * 64,
    excerpt="Inspect the mechanical seal of pump A17 every 14 days.",
    effective_from=datetime(2026, 10, 1, tzinfo=UTC),
    rank=0.4,
)


class UnitConn:
    """Stands in for the connection: counts the units `Session.unit` opens."""

    def __init__(self) -> None:
        self.units = 0

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        self.units += 1
        yield

    async def close(self) -> None:
        return None


class Database:
    """The two persistence calls the tool makes, recorded in order with the unit each ran in."""

    def __init__(self, conn: UnitConn, *, resolve: Exception | None = None, search: Exception | None = None) -> None:
        self.conn, self.resolve_error, self.search_error = conn, resolve, search
        self.calls: list[tuple[str, int, dict[str, Any]]] = []

    async def resolve_invocation(self, conn: Any, **kwargs: Any) -> None:
        self.calls.append(("resolve", self.conn.units, kwargs))
        if self.resolve_error is not None:
            raise self.resolve_error

    async def search_procedures(self, conn: Any, **kwargs: Any) -> persistence.Procedures:
        self.calls.append(("search", self.conn.units, kwargs))
        if self.search_error is not None:
            raise self.search_error
        return persistence.Procedures("corpus-1", (HIT,), datetime(2026, 10, 16, 12, 0, tzinfo=UTC))


async def call(monkeypatch: pytest.MonkeyPatch, db: Database, arguments: dict[str, Any]) -> CallToolResult:
    monkeypatch.setattr(persistence, "resolve_invocation", db.resolve_invocation)
    monkeypatch.setattr(persistence, "search_procedures", db.search_procedures)
    state = server.State(session=None, verifier=KeyedVerifier())
    fake: Any = db.conn
    state.session = persistence.Session(fake)  # already set, so the lifespan opens no connection
    state.assets = IdleAssets()  # the search asks asset-sim nothing yet
    app = server.build_app(server.build_server(state, issuer=ISSUER, resource_url=RESOURCE), state)
    headers = {"Authorization": "Bearer good", "X-Ops-Invocation": HANDLE}
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with (
            httpx2.AsyncClient(transport=transport, base_url=BASE, headers=headers) as http,
            Client(streamable_http_client(f"{BASE}/mcp", http_client=http), mode="2026-07-28") as client,
        ):
            return await client.call_tool("search_procedures", arguments)


async def test_the_handle_resolves_in_its_own_unit_then_the_definer_searches(monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database(UnitConn())
    result = await call(monkeypatch, db, {"query": "seal", "limit": 3, "mode": "lexical", "asset_type": "pump"})
    assert [(name, unit) for name, unit, _ in db.calls] == [("resolve", 1), ("search", 2)]
    assert db.calls[0][2] == {"handle": HANDLE, "azp": "ops-worker", "tool": Tool.SEARCH_PROCEDURES}
    assert db.calls[1][2] == {"handle": HANDLE, "azp": "ops-worker", "query": "seal", "asset_type": "pump", "limit": 3}
    doc = result.structured_content
    assert not result.is_error and isinstance(doc, dict) and doc["status"] == "ok"
    assert doc["data"]["corpus_version"] == "corpus-1"
    assert [r["evidence_id"] for r in doc["data"]["results"]] == ["ALPHA-PUMP-SEAL:v2:inspection"]
    assert "rank" not in doc["data"]["results"][0]


async def test_no_asset_type_means_any_asset(monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database(UnitConn())
    await call(monkeypatch, db, {"query": "seal", "limit": 3, "mode": "lexical"})
    assert db.calls[1][2]["asset_type"] is None


async def test_vector_exact_is_refused_after_resolution_and_before_any_search(monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database(UnitConn())
    result = await call(monkeypatch, db, {"query": "seal", "limit": 3, "mode": "vector_exact"})
    assert [name for name, _, _ in db.calls] == ["resolve"]
    assert result.structured_content is not None
    assert result.structured_content["error"]["code"] == "UNSUPPORTED_MODE"


@pytest.mark.parametrize("where", ["resolve", "search"])
async def test_a_refused_handle_is_the_one_plain_refusal(monkeypatch: pytest.MonkeyPatch, where: str) -> None:
    rejected = persistence.HandleRejected("invocation handle rejected")
    db = Database(UnitConn(), **{where: rejected})
    result = await call(monkeypatch, db, {"query": "seal", "limit": 3, "mode": "lexical"})
    assert [name for name, _, _ in db.calls] == (["resolve"] if where == "resolve" else ["resolve", "search"])
    doc = result.structured_content
    assert not result.is_error and isinstance(doc, dict) and doc["data"] is None
    assert doc["error"] == {"code": "INVALID_HANDLE", "message": "invocation handle rejected", "retryable": False}


async def test_a_definer_refusal_is_an_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database(UnitConn(), search=persistence.Refused("BAD_ARGUMENT"))
    result = await call(monkeypatch, db, {"query": "seal", "limit": 3, "mode": "lexical"})
    assert result.structured_content is not None
    assert result.structured_content["error"] == {"code": "REFUSED", "message": "BAD_ARGUMENT", "retryable": False}

"""mcp-read's `search_procedures` over its HTTP stack in-process, with the three database calls and asset-sim replaced
(Plan L rulings 1, 2, 11 and 21; Plan M rulings 12 and 14; erratum 80).

Catches: a search run before the handle resolved and the run's scope was read, or in the same unit as either; a search
that is not given the presented handle and the token's `azp` (the definer must decide the tenant from them, never
from an argument); the run's asset type not passed, or an unknown asset's absence turned into a filter;
`vector_exact` asking the embedding model before the scope and the asset type, or reaching the definer without the
query's embedding and `mode='vector'` (T18); a handle refused at any unit answered with anything but the one plain
`INVALID_HANDLE`; and a definer refusal escaping as a transport error instead of an envelope.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_types import CallToolResult
from ops_core import persistence
from ops_core.jobs import Tool
from ops_mcp_read import server

from tests.plan_j.test_mcp_read_http import BASE, ISSUER, RESOURCE, KeyedVerifier
from tests.plan_n.test_embeddings import FakeEmbedder, unit_vector

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
SCOPE = persistence.AssetScope(
    run_id=UUID(int=7),
    tenant_id=UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7"),
    asset_id="A17",
    start_at=datetime(2026, 10, 15, 12, tzinfo=UTC),
    end_at=datetime(2026, 10, 16, 12, tzinfo=UTC),
    as_of=datetime(2026, 10, 16, 12, tzinfo=UTC),
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
    """The three persistence calls the tool makes, recorded in order with the unit each ran in."""

    def __init__(
        self,
        conn: UnitConn,
        *,
        resolve: Exception | None = None,
        scope: Exception | None = None,
        search: Exception | None = None,
    ) -> None:
        self.conn, self.resolve_error, self.scope_error, self.search_error = conn, resolve, scope, search
        self.calls: list[tuple[str, int, dict[str, Any]]] = []

    async def resolve_invocation(self, conn: Any, **kwargs: Any) -> None:
        self.calls.append(("resolve", self.conn.units, kwargs))
        if self.resolve_error is not None:
            raise self.resolve_error

    async def asset_scope(self, conn: Any, **kwargs: Any) -> persistence.AssetScope:
        self.calls.append(("scope", self.conn.units, kwargs))
        if self.scope_error is not None:
            raise self.scope_error
        return SCOPE

    async def search_procedures(self, conn: Any, **kwargs: Any) -> persistence.Procedures:
        self.calls.append(("search", self.conn.units, kwargs))
        if self.search_error is not None:
            raise self.search_error
        return persistence.Procedures("corpus-1", (HIT,), datetime(2026, 10, 16, 12, 0, tzinfo=UTC))


class RunType:
    """asset-sim's answer for the run's asset: its type, None for an asset asset-sim does not know, or a failure."""

    def __init__(self, answer: str | None | Exception) -> None:
        self.answer = answer
        self.asked: list[persistence.AssetScope] = []

    async def asset_type(self, scope: persistence.AssetScope) -> str | None:
        self.asked.append(scope)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer

    async def status(self, scope: persistence.AssetScope) -> dict[str, Any]:
        raise AssertionError("the search asks for no status")

    async def alerts(self, scope: persistence.AssetScope, *, limit: int, cursor: str | None) -> dict[str, Any]:
        raise AssertionError("the search asks for no alerts")

    async def aclose(self) -> None:
        return None


async def call(
    monkeypatch: pytest.MonkeyPatch,
    db: Database,
    arguments: dict[str, Any],
    assets: RunType | None = None,
    configured: bool = True,
    embedder: Any = None,
) -> CallToolResult:
    """One search over the in-process stack; `configured=False` leaves the server without an asset-sim client, and
    `embedder` stands in for Ollama (T18; without one the lifespan builds the real client, which a lexical search never
    calls)."""
    monkeypatch.setattr(persistence, "resolve_invocation", db.resolve_invocation)
    monkeypatch.setattr(persistence, "asset_scope", db.asset_scope)
    monkeypatch.setattr(persistence, "search_procedures", db.search_procedures)
    state = server.State(session=None, verifier=KeyedVerifier())
    fake: Any = db.conn
    state.session = persistence.Session(fake)  # already set, so the lifespan opens no connection
    state.assets = (assets or RunType("pump")) if configured else None  # A17 is a pump (data/corpus/assets.json)
    state.embedder = embedder
    if not configured:  # the lifespan would build the real client from the settings
        monkeypatch.setattr(server.assets.HttpAssetSim, "from_settings", classmethod(lambda cls: None))
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
    assert [(name, unit) for name, unit, _ in db.calls] == [("resolve", 1), ("scope", 2), ("search", 3)]
    assert db.calls[0][2] == {"handle": HANDLE, "azp": "ops-worker", "tool": Tool.SEARCH_PROCEDURES}
    assert db.calls[1][2] == {"handle": HANDLE, "azp": "ops-worker"}
    assert db.calls[2][2] == {
        "handle": HANDLE,
        "azp": "ops-worker",
        "query": "seal",
        "asset_type": "pump",
        "limit": 3,
        "mode": "lexical",
        "embedding": None,
    }
    doc = result.structured_content
    assert not result.is_error and isinstance(doc, dict) and doc["status"] == "ok"
    assert doc["data"]["corpus_version"] == "corpus-1"
    assert [r["evidence_id"] for r in doc["data"]["results"]] == ["ALPHA-PUMP-SEAL:v2:inspection"]
    assert "rank" not in doc["data"]["results"][0]


async def test_the_runs_asset_type_is_searched_and_an_unknown_asset_leaves_the_callers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plan M ruling 12: the run's type when asset-sim knows the asset; otherwise the caller's type, or any asset."""
    searched = []
    for answer, arguments in (
        ("pump", {}),
        (None, {}),
        (None, {"asset_type": "valve"}),
    ):
        db = Database(UnitConn())
        await call(monkeypatch, db, {"query": "seal", "limit": 3, "mode": "lexical", **arguments}, RunType(answer))
        searched.append(db.calls[2][2]["asset_type"])
    assert searched == ["pump", None, "valve"]


async def test_vector_exact_searches_after_the_scope_with_the_query_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    """T18 (Plan N ruling 4): the same three units; the query embedding is computed between the asset type and the
    third unit, and the definer is asked with `mode='vector'` (erratum 3)."""
    fake = FakeEmbedder()
    db = Database(UnitConn())
    result = await call(monkeypatch, db, {"query": "seal", "limit": 3, "mode": "vector_exact"}, embedder=fake)
    assert [(name, unit) for name, unit, _ in db.calls] == [("resolve", 1), ("scope", 2), ("search", 3)]
    assert fake.texts == ["search_query: seal"]
    assert db.calls[2][2]["mode"] == "vector" and db.calls[2][2]["embedding"] == tuple(
        unit_vector("search_query: seal")
    )
    assert result.structured_content is not None
    assert result.structured_content["data"]["retrieval_mode"] == "vector_exact"


@pytest.mark.parametrize("where", ["resolve", "scope", "search"])
async def test_a_refused_handle_is_the_one_plain_refusal(monkeypatch: pytest.MonkeyPatch, where: str) -> None:
    rejected = persistence.HandleRejected("invocation handle rejected")
    db = Database(UnitConn(), **{where: rejected})
    result = await call(monkeypatch, db, {"query": "seal", "limit": 3, "mode": "lexical"})
    order = ["resolve", "scope", "search"]
    assert [name for name, _, _ in db.calls] == order[: order.index(where) + 1]
    doc = result.structured_content
    assert not result.is_error and isinstance(doc, dict) and doc["data"] is None
    assert doc["error"] == {"code": "INVALID_HANDLE", "message": "invocation handle rejected", "retryable": False}


async def test_a_definer_refusal_is_an_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database(UnitConn(), search=persistence.Refused("BAD_ARGUMENT"))
    result = await call(monkeypatch, db, {"query": "seal", "limit": 3, "mode": "lexical"})
    assert result.structured_content is not None
    assert result.structured_content["error"] == {"code": "REFUSED", "message": "BAD_ARGUMENT", "retryable": False}

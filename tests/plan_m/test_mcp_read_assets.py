"""mcp-read's asset tools over its HTTP stack in-process: the two database calls replaced, asset-sim answered by a
scripted transport behind the real client (Plan M rulings 8, 9, 10, 13 and 15; erratum 80).

Catches: asset-sim asked before the handle resolved and the scope was read, or in the same unit; the worker's token or
the handle forwarded to asset-sim, or the tenant, the instant or the interval taken from anywhere but `asset_scope`;
another asset or another interval forwarded instead of refused; an answer stamped from the wall clock; `truncated`
that disagrees with `next_cursor`; an asset-sim failure that is not mapped to its code and retry flag, or data outside
the contract or the run's scope passed on; a refused handle or a lost membership answered with anything but the one
plain INVALID_HANDLE; and an advertised input schema that is not the committed file, or that disagrees with the
argument model on what it accepts.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx2
import pytest
from jsonschema import Draft202012Validator
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_types import CallToolResult
from ops_core import persistence, tool_contracts
from ops_core.jobs import Tool
from ops_mcp_read import assets, server

from tests.plan_j.test_mcp_read_http import BASE, ISSUER, RESOURCE, KeyedVerifier
from tests.plan_l.test_mcp_read_corpus import HANDLE, UnitConn

pytestmark = pytest.mark.asyncio

ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")
SCOPE = persistence.AssetScope(
    run_id=UUID(int=7),
    tenant_id=ALPHA,
    asset_id="A17",
    start_at=datetime(2026, 10, 5, tzinfo=UTC),
    end_at=datetime(2026, 10, 7, tzinfo=UTC),
    as_of=datetime(2026, 10, 6, 0, 0, 0, 250000, tzinfo=UTC),
)
STATUS = {
    "asset_id": "A17",
    "state": "warning",
    "revision": 1,
    "observed_at": "2026-10-06T00:00:00.250000Z",
    "data_source": "synthetic",
}
ALERT = {
    "alert_id": "6699502e-a981-5959-9f24-6df6bd3d3ac5",
    "asset_id": "A17",
    "occurred_at": "2026-10-05T14:00:00Z",
    "code": "seal_leak",
    "message": "Synthetic warning alert: seal leak on Alpha transfer pump A17.",
    "revision": 1,
}
INTERVAL = {"start_at": "2026-10-05T00:00:00Z", "end_at": "2026-10-07T00:00:00Z"}


def alerts(next_cursor: str | None = None, **over: Any) -> dict[str, Any]:
    return {"asset_id": "A17", **INTERVAL, "alerts": [ALERT], "next_cursor": next_cursor, **over}


class Tokens:
    """mcp-read's own workload token, as WorkloadTokenSource would hand it out."""

    def __init__(self) -> None:
        self.invalidated: list[str | None] = []

    async def token(self) -> str:
        return "mcp-read-token"

    def invalidate(self, stale: str | None = None) -> None:
        self.invalidated.append(stale)


class Database:
    """The two persistence calls an asset tool makes, recorded in order with the unit each ran in."""

    def __init__(self, conn: UnitConn, *, resolve: Exception | None = None, scope: Exception | None = None) -> None:
        self.conn, self.resolve_error, self.scope_error = conn, resolve, scope
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


Answer = Callable[[httpx2.Request], httpx2.Response]


@asynccontextmanager
async def mcp_read(
    monkeypatch: pytest.MonkeyPatch, db: Database, answer: Answer, tokens: Tokens | None = None
) -> AsyncIterator[tuple[Client, list[httpx2.Request]]]:
    """The app with the two database calls replaced and asset-sim answered by `answer`; every request it got."""
    monkeypatch.setattr(persistence, "resolve_invocation", db.resolve_invocation)
    monkeypatch.setattr(persistence, "asset_scope", db.asset_scope)
    seen: list[httpx2.Request] = []

    def recorded(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return answer(request)

    state = server.State(session=None, verifier=KeyedVerifier())
    fake: Any = db.conn
    state.session = persistence.Session(fake)  # already set, so the lifespan opens no connection
    state.assets = assets.HttpAssetSim(
        "http://asset-sim.test", tokens or Tokens(), transport=httpx2.MockTransport(recorded)
    )
    app = server.build_app(server.build_server(state, issuer=ISSUER, resource_url=RESOURCE), state)
    headers = {"Authorization": "Bearer good", "X-Ops-Invocation": HANDLE}
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with (
            httpx2.AsyncClient(transport=transport, base_url=BASE, headers=headers) as http,
            Client(streamable_http_client(f"{BASE}/mcp", http_client=http), mode="2026-07-28") as client,
        ):
            yield client, seen


def doc_of(result: CallToolResult) -> dict[str, Any]:
    doc = result.structured_content
    assert not result.is_error and isinstance(doc, dict)
    return doc


def respond(status: int, body: Any) -> Answer:
    return lambda request: httpx2.Response(status, json=body)


async def test_status_is_asked_after_both_units_with_mcp_reads_own_token_and_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = Database(UnitConn())
    async with mcp_read(monkeypatch, db, respond(200, STATUS)) as (client, seen):
        doc = doc_of(await client.call_tool("get_asset_status", {"asset_id": "A17"}))
    assert [(name, unit) for name, unit, _ in db.calls] == [("resolve", 1), ("scope", 2)]
    assert db.calls[0][2] == {"handle": HANDLE, "azp": "ops-worker", "tool": Tool.GET_ASSET_STATUS}
    assert db.calls[1][2] == {"handle": HANDLE, "azp": "ops-worker"}
    (request,) = seen
    assert request.url.path == "/assets/A17/status"
    assert request.headers["authorization"] == "Bearer mcp-read-token"  # never the worker's token (ruling 8)
    assert request.headers["x-ops-tenant-id"] == str(ALPHA)
    assert request.headers["x-ops-as-of"] == "2026-10-06T00:00:00.250000Z"  # the definer's instant
    assert "x-ops-invocation" not in request.headers  # the handle never reaches the destination (BS:364)
    assert doc["status"] == "ok" and doc["data"] == STATUS and doc["observed_at"] == "2026-10-06T00:00:00Z"
    tool_contracts.check_result(Tool.GET_ASSET_STATUS, doc)


async def test_another_asset_or_interval_is_refused_before_asset_sim(monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database(UnitConn())
    async with mcp_read(monkeypatch, db, respond(200, STATUS)) as (client, seen):
        b22 = doc_of(await client.call_tool("get_asset_status", {"asset_id": "B22"}))  # R028: alpha asks for B22
        later = {"asset_id": "A17", "start_at": "2026-10-05T00:00:00Z", "end_at": "2026-10-08T00:00:00Z", "limit": 5}
        widened = doc_of(await client.call_tool("get_recent_alerts", later))
        impossible = {**later, "end_at": "2026-02-30T00:00:00Z"}  # the pattern passes; no such day
        nonsense = doc_of(await client.call_tool("get_recent_alerts", impossible))
    assert seen == []  # asset-sim was never asked
    assert b22["error"] == {
        "code": "ASSET_OUT_OF_SCOPE",
        "message": "only the run's own asset may be read",
        "retryable": False,
    }
    assert widened["error"]["code"] == nonsense["error"]["code"] == "INTERVAL_OUT_OF_SCOPE"
    assert b22["observed_at"] == "2026-10-06T00:00:00Z"  # decided after asset_scope: the database's instant


async def test_alerts_forward_the_runs_interval_and_mark_a_further_page(monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database(UnitConn())
    pages = iter([alerts("c" * 76), alerts(None)])
    async with mcp_read(monkeypatch, db, lambda request: httpx2.Response(200, json=next(pages))) as (client, seen):
        spelled = {"asset_id": "A17", "start_at": "2026-10-05T00:00:00+00:00", "end_at": "2026-10-07T00:00:00Z"}
        first = doc_of(await client.call_tool("get_recent_alerts", {**spelled, "limit": 1}))
        second = doc_of(await client.call_tool("get_recent_alerts", {**spelled, "limit": 1, "cursor": "c" * 76}))
    assert (first["truncated"], first["data"]["next_cursor"]) == (True, "c" * 76)
    assert (second["truncated"], second["data"]["next_cursor"]) == (False, None)
    assert dict(seen[0].url.params) == {**INTERVAL, "limit": "1"}  # `+00:00` compared as an instant, sent as Z
    assert dict(seen[1].url.params) == {**INTERVAL, "limit": "1", "cursor": "c" * 76}
    for doc in (first, second):
        tool_contracts.check_result(Tool.GET_RECENT_ALERTS, doc)


def fail_with(exc: type[Exception]) -> Answer:
    def answer(request: httpx2.Request) -> httpx2.Response:
        raise exc("scripted", request=request)

    return answer


def body(text: bytes) -> Answer:
    return lambda request: httpx2.Response(200, content=text)


@pytest.mark.parametrize(
    ("tool", "answer", "code", "retryable"),
    [
        ("status", fail_with(httpx2.ConnectError), "UNAVAILABLE", True),
        ("status", fail_with(httpx2.ReadTimeout), "UNAVAILABLE", True),
        ("status", respond(503, {"code": "UNAVAILABLE"}), "UNAVAILABLE", True),
        ("status", respond(401, {"code": "UNAUTHENTICATED"}), "UNAVAILABLE", True),
        ("status", respond(404, {"code": "NOT_FOUND"}), "NOT_FOUND", False),
        ("alerts", respond(400, {"code": "INVALID_INPUT"}), "INVALID_CURSOR", False),
        ("status", respond(418, {}), "UPSTREAM_INVALID", False),
        ("status", body(b"not json"), "UPSTREAM_INVALID", False),
        ("status", respond(200, {**STATUS, "state": "on fire"}), "UPSTREAM_INVALID", False),  # the contract
        ("status", respond(200, {**STATUS, "asset_id": "B22"}), "UPSTREAM_INVALID", False),  # another asset's data
        ("alerts", respond(200, alerts(end_at="2026-10-08T00:00:00Z")), "UPSTREAM_INVALID", False),  # interval
        (
            "alerts",
            respond(200, alerts(alerts=[{**ALERT, "occurred_at": "2026-10-06T00:00:01Z"}])),
            "UPSTREAM_INVALID",
            False,
        ),  # an alert from after as_of
    ],
)
async def test_asset_sim_failures_map_to_their_codes(
    monkeypatch: pytest.MonkeyPatch, tool: str, answer: Answer, code: str, retryable: bool
) -> None:
    async with mcp_read(monkeypatch, Database(UnitConn()), answer) as (client, _):
        if tool == "status":
            result = await client.call_tool("get_asset_status", {"asset_id": "A17"})
        else:
            result = await client.call_tool(
                "get_recent_alerts", {"asset_id": "A17", **INTERVAL, "limit": 1, "cursor": "x"}
            )
    doc = doc_of(result)
    assert (doc["status"], doc["data"], doc["error"]["code"], doc["error"]["retryable"]) == (
        "error",
        None,
        code,
        retryable,
    )
    assert "on fire" not in str(doc) and "B22" not in str(doc)  # nothing of a refused answer is passed on
    tool_contracts.check_result(Tool.GET_ASSET_STATUS if tool == "status" else Tool.GET_RECENT_ALERTS, doc)


async def test_a_401_drops_mcp_reads_cached_token(monkeypatch: pytest.MonkeyPatch) -> None:
    tokens = Tokens()
    async with mcp_read(monkeypatch, Database(UnitConn()), respond(401, {}), tokens) as (client, _):
        await client.call_tool("get_asset_status", {"asset_id": "A17"})
    assert tokens.invalidated == ["mcp-read-token"]


@pytest.mark.parametrize("where", ["resolve", "scope"])
async def test_a_refused_handle_or_a_lost_membership_is_the_one_plain_refusal(
    monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    db = Database(UnitConn(), **{where: persistence.HandleRejected("invocation handle rejected")})
    async with mcp_read(monkeypatch, db, respond(200, STATUS)) as (client, seen):
        doc = doc_of(await client.call_tool("get_asset_status", {"asset_id": "A17"}))
    assert seen == [] and [name for name, _, _ in db.calls] == (
        ["resolve"] if where == "resolve" else ["resolve", "scope"]
    )
    assert doc["data"] is None
    assert doc["error"] == {"code": "INVALID_HANDLE", "message": "invocation handle rejected", "retryable": False}


# Argument sets on both sides of every bound the committed schemas state; each is judged by the file (jsonschema) and
# by the server (its strict argument model), and the two verdicts must agree.
ARGUMENTS: list[tuple[str, dict[str, Any]]] = [
    ("get_asset_status", {"asset_id": "A17"}),
    ("get_asset_status", {"asset_id": "A" * 32}),
    ("get_asset_status", {"asset_id": "A" * 33}),
    ("get_asset_status", {"asset_id": "a17"}),
    ("get_asset_status", {"asset_id": "A17\n"}),
    ("get_asset_status", {"asset_id": "A17", "tenant_id": str(ALPHA)}),
    ("get_asset_status", {}),
    ("get_recent_alerts", {"asset_id": "A17", **INTERVAL, "limit": 1}),
    ("get_recent_alerts", {"asset_id": "A17", **INTERVAL, "limit": 100, "cursor": "c" * 200}),
    ("get_recent_alerts", {"asset_id": "A17", **INTERVAL, "limit": 101}),
    ("get_recent_alerts", {"asset_id": "A17", **INTERVAL, "limit": 0}),
    ("get_recent_alerts", {"asset_id": "A17", **INTERVAL, "limit": "1"}),
    ("get_recent_alerts", {"asset_id": "A17", **INTERVAL, "limit": 1, "cursor": ""}),
    ("get_recent_alerts", {"asset_id": "A17", **INTERVAL, "limit": 1, "cursor": "c" * 201}),
    ("get_recent_alerts", {"asset_id": "A17", **INTERVAL, "limit": 1, "start_at": "2026-10-05T02:00:00+02:00"}),
    ("get_recent_alerts", {"asset_id": "A17", **INTERVAL, "limit": 1, "start_at": "2026-10-05T00:00:00.5Z"}),
    ("get_recent_alerts", {"asset_id": "A17", **INTERVAL, "limit": 1, "end_at": "2026-10-07"}),
    ("get_recent_alerts", {"asset_id": "A17", "start_at": INTERVAL["start_at"], "limit": 1}),
    ("search_procedures", {"query": "seal", "limit": 8, "mode": "lexical"}),
    ("search_procedures", {"query": "x" * 500, "limit": 1, "mode": "vector_exact", "asset_type": "p" * 40}),
    ("search_procedures", {"query": "", "limit": 1, "mode": "lexical"}),
    ("search_procedures", {"query": "x" * 501, "limit": 1, "mode": "lexical"}),
    ("search_procedures", {"query": "x", "limit": 9, "mode": "lexical"}),
    ("search_procedures", {"query": "x", "limit": True, "mode": "lexical"}),
    ("search_procedures", {"query": "x", "limit": 1, "mode": "vector"}),
    ("search_procedures", {"query": "x", "limit": 1, "mode": "lexical", "asset_type": ""}),
    ("search_procedures", {"query": "x", "limit": 1, "mode": "lexical", "asset_type": None}),
]


async def test_the_advertised_schemas_are_the_committed_files_and_agree_with_the_argument_models() -> None:
    state = server.State(session=None, verifier=KeyedVerifier())
    mcp = server.build_server(state, issuer=ISSUER, resource_url=RESOURCE)
    async with Client(mcp) as client:  # in-process: no bearer middleware, so every accepted call refuses the handle
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert list(tools) == ["get_asset_status", "get_recent_alerts", "search_procedures"]
        for name, tool in tools.items():
            assert tool_contracts.same_input_schema(Tool(name), tool.input_schema), name
        for name, arguments in ARGUMENTS:
            by_file = Draft202012Validator(tool_contracts.input_schema(Tool(name))).is_valid(arguments)
            result = await client.call_tool(name, arguments)
            by_model = not result.is_error  # an accepted call reaches the body, which answers an envelope
            assert by_model == by_file, (name, arguments)
            if by_model:
                assert result.structured_content["error"]["code"] == "INVALID_HANDLE"

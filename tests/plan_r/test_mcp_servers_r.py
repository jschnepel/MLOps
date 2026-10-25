"""mcp-write's committed grant refusal and committed schemas, mcp-read's stale-sync deferral, and the worker's write
discovery (T21; Plan R rulings 11, 14 and 17), in-process with the definers replaced.

Catches: a grant refusal that committed BLOCKED_REVIEW answered without its reason, or as anything but a final
GRANT_REFUSED (the worker would retry a run that is no longer APPROVED); an envelope the committed tool-result schema
refuses; mcp-write advertising a generated schema instead of the committed file; a worker that calls mcp-write without
comparing its listing to the committed contract, or accepts a result outside it; and a stale read refusal that a
caller cannot tell from a dead handle.
"""

from typing import Any
from uuid import uuid4

import httpx2
import pytest
from mcp_types import ListToolsResult
from mcp_types import Tool as AdvertisedTool
from ops_core import persistence, tool_contracts
from ops_core.jobs import Tool
from ops_core.states import Reason
from ops_mcp_read import server as read_server
from ops_mcp_write import destination
from ops_worker import mcp as worker_mcp
from ops_worker.mcp import WRITE_TOOLS, HttpMcpCaller, McpCallFailed, check_listing

from tests.plan_k.test_recovery_tools import PROPOSAL
from tests.plan_k.test_write_tools_server import BASE, TOOL_RESULT, client, write_app
from tests.plan_l.test_mcp_read_corpus import Database, UnitConn, call

pytestmark = pytest.mark.asyncio


class Good:
    """The worker's token source, with the token the test verifier accepts."""

    async def token(self) -> str:
        return "good"


def blocked(monkeypatch: pytest.MonkeyPatch, reason: Reason) -> None:
    """A resolved handle and a grant the gate refused with a committed BLOCKED_REVIEW."""

    async def resolve(_conn: Any, **_: Any) -> None:
        return None

    async def grant(_conn: Any, **_: Any) -> persistence.Blocked:
        return persistence.Blocked(uuid4(), PROPOSAL, reason)

    monkeypatch.setattr(persistence, "resolve_invocation", resolve)
    monkeypatch.setattr(persistence, "grant_execution", grant)


async def test_a_committed_refusal_is_a_final_grant_refused_with_its_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    blocked(monkeypatch, Reason.ASSET_INCIDENT_EXISTS)
    reached: list[str] = []  # anything after the grant: the SENT mark or a request to the destination

    async def mark_sent(_conn: Any, **_: Any) -> str:
        reached.append("mark_sent")
        return "sent"

    async def send(*_: Any, **__: Any) -> None:
        reached.append("destination request")

    monkeypatch.setattr(persistence, "mark_sent", mark_sent)
    monkeypatch.setattr(destination, "_send", send)
    async with client(write_app()) as mcp:
        doc = (await mcp.call_tool("create_incident", {"proposal_id": str(PROPOSAL)})).structured_content
    assert reached == []  # a committed refusal sends nothing (SA:355)
    assert isinstance(doc, dict) and doc["status"] == "error" and doc["data"] is None
    assert doc["error"] == {
        "code": "GRANT_REFUSED",
        "message": "grant refused: asset_incident_exists",
        "retryable": False,
        "reason": "asset_incident_exists",
    }
    TOOL_RESULT.validate(doc)


async def test_mcp_write_advertises_the_committed_schemas() -> None:
    async with client(write_app()) as mcp:
        tools = {t.name: t.input_schema for t in (await mcp.list_tools()).tools}
    assert {Tool(name) for name in tools} == WRITE_TOOLS
    assert all(tool_contracts.same_input_schema(Tool(name), schema) for name, schema in tools.items())


async def test_the_worker_checks_mcp_writes_listing_and_result(monkeypatch: pytest.MonkeyPatch) -> None:
    blocked(monkeypatch, Reason.STALE_EVIDENCE)
    app = write_app()
    async with app.router.lifespan_context(app):
        caller = HttpMcpCaller(Good(), transport=httpx2.ASGITransport(app=app))
        doc = await caller.call(
            f"{BASE}/mcp", handle="h", tool="create_incident", arguments={"proposal_id": str(PROPOSAL)}
        )
    assert doc["status"] == "error" and doc["error"]["reason"] == "stale_evidence"  # validated against the contract
    tools = [AdvertisedTool(name=t.value, input_schema=tool_contracts.input_schema(t)) for t in sorted(WRITE_TOOLS)]
    check_listing(ListToolsResult(tools=tools), Tool.CREATE_INCIDENT, WRITE_TOOLS)
    altered = [*tools[:-1], AdvertisedTool(name=tools[-1].name, input_schema={"type": "object"})]
    with pytest.raises(McpCallFailed, match="not the committed one|unexpected tool set"):
        check_listing(ListToolsResult(tools=altered), Tool(tools[-1].name), WRITE_TOOLS)
    with pytest.raises(McpCallFailed, match="unexpected tool set"):
        check_listing(ListToolsResult(tools=tools[:2]), Tool.CREATE_INCIDENT, WRITE_TOOLS)


def grant_spy(monkeypatch: pytest.MonkeyPatch, reason: Reason) -> list[str]:
    """`blocked`, recording every definer the server reaches; empty means nothing past discovery ran."""
    reached: list[str] = []

    async def resolve(_conn: Any, **_: Any) -> None:
        reached.append("resolve_invocation")

    async def grant(_conn: Any, **_: Any) -> persistence.Blocked:
        reached.append("grant_execution")
        return persistence.Blocked(uuid4(), PROPOSAL, reason)

    monkeypatch.setattr(persistence, "resolve_invocation", resolve)
    monkeypatch.setattr(persistence, "grant_execution", grant)
    return reached


async def test_a_write_listing_that_drifts_is_refused_before_the_tool_is_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reached = grant_spy(monkeypatch, Reason.STALE_EVIDENCE)
    committed = tool_contracts.input_schema

    def drifted(tool: Tool) -> dict[str, Any]:
        schema = committed(tool)
        return {**schema, "title": "drifted"} if tool is Tool.CREATE_INCIDENT else schema

    monkeypatch.setattr(tool_contracts, "input_schema", drifted)  # the server's side only: the worker compares files
    app = write_app()
    async with app.router.lifespan_context(app):
        caller = HttpMcpCaller(Good(), transport=httpx2.ASGITransport(app=app))
        with pytest.raises(McpCallFailed, match="not the committed one"):
            await caller.call(
                f"{BASE}/mcp", handle="h", tool="create_incident", arguments={"proposal_id": str(PROPOSAL)}
            )
    assert reached == []  # the tool never ran: no handle resolved and no grant


async def test_a_write_result_outside_the_committed_schema_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # `rejected` is a run reason, but not one a refused grant records: the server's envelope fails the reason enum.
    reached = grant_spy(monkeypatch, Reason.REJECTED)
    app = write_app()
    async with app.router.lifespan_context(app):
        caller = HttpMcpCaller(Good(), transport=httpx2.ASGITransport(app=app))
        with pytest.raises(McpCallFailed, match="the result fails the contract"):
            await caller.call(
                f"{BASE}/mcp", handle="h", tool="create_incident", arguments={"proposal_id": str(PROPOSAL)}
            )
    assert reached == ["resolve_invocation", "grant_execution"]  # the tool did run: only its answer is refused


async def test_a_failed_write_check_is_found_among_every_leaf_of_the_group(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_: Any) -> None:
        raise ExceptionGroup("session", [OSError("closed"), McpCallFailed("create_incident: the second leaf")])

    monkeypatch.setattr(worker_mcp, "check_listing", refuse)
    app = write_app()
    async with app.router.lifespan_context(app):
        caller = HttpMcpCaller(Good(), transport=httpx2.ASGITransport(app=app))
        with pytest.raises(McpCallFailed, match="the second leaf"):  # not the first leaf's transport failure
            await caller.call(
                f"{BASE}/mcp", handle="h", tool="create_incident", arguments={"proposal_id": str(PROPOSAL)}
            )


STALE = persistence.Refused("MEMBERSHIP_STALE")
READ_QUERY = {"query": "seal", "limit": 3, "mode": "lexical"}


@pytest.mark.parametrize("where", ["scope", "search"])
async def test_a_stale_sync_in_either_read_unit_is_a_retryable_envelope(
    monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    db = Database(UnitConn(), **{where: STALE})  # the scope unit's refusal, then the third unit's
    result = await call(monkeypatch, db, READ_QUERY)
    doc = result.structured_content
    assert doc is not None and doc["status"] == "error" and doc["data"] is None
    assert doc["error"]["code"] == "MEMBERSHIP_STALE" and doc["error"]["retryable"] is True


async def test_a_stale_read_is_a_retryable_deferral_and_any_other_refusal_is_not() -> None:
    assert read_server.stale_error("MEMBERSHIP_STALE")["retryable"] is True
    assert read_server.stale_error("BAD_ARGUMENT") == {"code": "REFUSED", "message": "BAD_ARGUMENT", "retryable": False}

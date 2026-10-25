"""R029 at the worker (Plan M ruling 13): the real client against mcp-read's real HTTP stack in-process, with the
database calls and asset-sim replaced, and its checks on scripted answers.

Catches: a client that calls a tool without listing first, or calls it although the server lists a tool too many or
too few, announces a further page of tools, or advertises an input schema other than the committed file; a result that is error-flagged, malformed,
another tool's, an error envelope or larger than 256 KiB taken as success; and an investigate run that does anything
but fail as "retrieval failed" when its read fails a check (no success assumption).
"""

import asyncio
import dataclasses
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx2
import pytest
from mcp_types import CallToolResult, ListToolsResult, TextContent
from mcp_types import Tool as AdvertisedTool
from ops_core import persistence, tool_contracts
from ops_core.jobs import Tool
from ops_core.states import RunState
from ops_mcp_read import assets, server
from ops_worker import handlers
from ops_worker.mcp import READ_TOOLS, HttpMcpCaller, McpCallFailed, check_listing, leaves, read_result

from tests.plan_h.test_worker_units import JOB, Log, make, patch
from tests.plan_j.test_mcp_read_http import BASE, ISSUER, RESOURCE, KeyedVerifier
from tests.plan_l.test_mcp_read_corpus import UnitConn
from tests.plan_m.test_mcp_read_assets import STATUS, Database, Tokens

STATUS_CALL = {"asset_id": "A17"}


class Good:
    """The worker's token source, answering the token KeyedVerifier accepts."""

    async def token(self) -> str:
        return "good"


@asynccontextmanager
async def caller_against(
    monkeypatch: pytest.MonkeyPatch, db: Database, alter: Any = None
) -> AsyncIterator[HttpMcpCaller]:
    """The worker's real client, reaching mcp-read's real app in-process; `alter` changes the server first."""
    monkeypatch.setattr(persistence, "resolve_invocation", db.resolve_invocation)
    monkeypatch.setattr(persistence, "asset_scope", db.asset_scope)
    state = server.State(session=None, verifier=KeyedVerifier())
    fake: Any = db.conn
    state.session = persistence.Session(fake)
    state.assets = assets.HttpAssetSim(
        "http://asset-sim.test", Tokens(), transport=httpx2.MockTransport(lambda r: httpx2.Response(200, json=STATUS))
    )
    mcp = server.build_server(state, issuer=ISSUER, resource_url=RESOURCE)
    if alter is not None:
        alter(mcp)
    app = server.build_app(mcp, state)
    async with app.router.lifespan_context(app):
        yield HttpMcpCaller(Good(), transport=httpx2.ASGITransport(app=app))


@pytest.mark.asyncio
async def test_the_real_listing_and_a_valid_result_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database(UnitConn())
    async with caller_against(monkeypatch, db) as caller:
        doc = await caller.call(f"{BASE}/mcp", handle="h", tool="get_asset_status", arguments=STATUS_CALL)
    assert doc["status"] == "ok" and doc["data"] == STATUS
    assert [name for name, _, _ in db.calls] == ["resolve", "scope"]
    # The same three committed tools pass on one page, and are refused when the server announces another page
    # (round 2: a second page could carry a fourth tool the set check never saw).
    tools = [AdvertisedTool(name=t.value, input_schema=tool_contracts.input_schema(t)) for t in sorted(READ_TOOLS)]
    check_listing(ListToolsResult(tools=tools), Tool.GET_ASSET_STATUS)
    with pytest.raises(McpCallFailed, match="unexpected tool set"):
        check_listing(ListToolsResult(tools=tools, next_cursor="page-2"), Tool.GET_ASSET_STATUS)


def run_shell() -> str:
    """A tool no read server may offer (BS:395)."""
    return "never"


@pytest.mark.parametrize(
    ("alter", "why"),
    [
        (lambda mcp: mcp.add_tool(run_shell), "unexpected tool set"),  # a tool added
        (lambda mcp: mcp.remove_tool("get_recent_alerts"), "unexpected tool set"),  # a tool removed
        (  # the called tool's schema loosened: a longer asset id would be accepted. This reaches into FastMCP's
            # private `_tool_manager`, so it depends on the pinned mcp==2.3.0 and must be revisited with the pin.
            lambda mcp: (
                mcp._tool_manager.get_tool("get_asset_status").parameters["properties"]["asset_id"].update(maxLength=64)
            ),
            "input schema is not the committed one",
        ),
    ],
)
@pytest.mark.asyncio
async def test_an_altered_listing_fails_closed_before_the_call(
    monkeypatch: pytest.MonkeyPatch, alter: Any, why: str
) -> None:
    db = Database(UnitConn())
    async with caller_against(monkeypatch, db, alter) as caller:
        with pytest.raises(McpCallFailed, match=why):
            await caller.call(f"{BASE}/mcp", handle="h", tool="get_asset_status", arguments=STATUS_CALL)
    assert db.calls == []  # the tool was never called


def result(doc: Any, *, is_error: bool = False, padding: int = 0) -> CallToolResult:
    content = [TextContent(type="text", text="x" * padding)] if padding else []
    return CallToolResult(content=content, structured_content=doc, is_error=is_error)


def status_doc(**data: Any) -> dict[str, Any]:
    return {
        "tool_name": "get_asset_status",
        "request_id": "00000000-0000-4000-8000-000000000000",
        "status": "ok",
        "observed_at": "2026-10-06T00:00:00Z",
        "truncated": False,
        "data": {**STATUS, **data},
        "error": None,
    }


REFUSED = {"code": "UNAVAILABLE", "message": "asset-sim could not be reached", "retryable": True}


@pytest.mark.parametrize(
    ("answer", "why"),
    [
        (result(status_doc(), is_error=True), "error-flagged"),
        (result(status_doc(state="on fire")), "fails the contract"),  # malformed nested data
        (result({**status_doc(), "tool_name": "search_procedures"}), "fails the contract"),  # another tool's
        (result([status_doc()]), "fails the contract"),  # not an object
        (result(None), "fails the contract"),  # no structured content at all
        (result({**status_doc(), "status": "error", "data": None, "error": REFUSED}), "rejected the call"),
        (result(status_doc(note="x" * (300 * 1024))), "larger than the bound"),  # oversized envelope
    ],
)
def test_a_result_that_is_not_a_valid_ok_answer_fails_closed(answer: CallToolResult, why: str) -> None:
    with pytest.raises(McpCallFailed, match=why):
        read_result(Tool.GET_ASSET_STATUS, answer)
    assert read_result(Tool.GET_ASSET_STATUS, result(status_doc()))["status"] == "ok"  # the valid shape passes


def test_the_size_bound_measures_the_envelope_not_the_text_copy_around_it() -> None:
    """Ruling 13 bounds the tool result: FastMCP's second, text copy of the same envelope does not count twice."""
    padded = result(status_doc(), padding=300 * 1024)
    assert read_result(Tool.GET_ASSET_STATUS, padded)["status"] == "ok"


def tamper_output_schema(tool_name: str) -> Any:
    """A server that advertises an output schema its own answer cannot satisfy: the SDK's `call_tool` then raises
    RuntimeError inside the session, before `read_result` runs (the reviewer's probe of Task 5)."""

    def alter(mcp: Any) -> None:
        mcp._tool_manager.get_tool(tool_name).fn_metadata.output_schema = {"type": "object", "required": ["never"]}

    return alter


@pytest.mark.asyncio
async def test_a_failure_inside_the_sdk_session_is_a_failed_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """The SDK's own RuntimeError (the answer does not satisfy the advertised output schema) arrives as an exception
    group out of the client; the worker must still see McpCallFailed, or the handler crashes the run."""
    db = Database(UnitConn())
    async with caller_against(monkeypatch, db, tamper_output_schema("get_asset_status")) as caller:
        with pytest.raises(McpCallFailed, match="session failed"):
            await caller.call(f"{BASE}/mcp", handle="h", tool="get_asset_status", arguments=STATUS_CALL)


def test_every_leaf_of_a_nested_group_is_inspected() -> None:
    nested = ExceptionGroup("outer", [ExceptionGroup("inner", [RuntimeError("a"), ValueError("b")]), KeyError("c")])
    assert [type(leaf) for leaf in leaves(nested)] == [RuntimeError, ValueError, KeyError]


@pytest.mark.parametrize(
    "failure",
    [
        BaseExceptionGroup("outer", [RuntimeError("a"), BaseExceptionGroup("inner", [asyncio.CancelledError()])]),
        asyncio.CancelledError(),
    ],
)
@pytest.mark.asyncio
async def test_a_cancellation_among_the_failures_still_propagates(failure: BaseException) -> None:
    """A group is a failed read only when none of its leaves (all are checked, not the first) is a cancellation."""

    class Cancelling:
        async def token(self) -> str:
            raise failure

    caller = HttpMcpCaller(Cancelling())
    with pytest.raises(BaseException) as raised:
        await caller.call(f"{BASE}/mcp", handle="h", tool="get_asset_status", arguments={})
    assert raised.value is failure and not isinstance(raised.value, McpCallFailed)


@pytest.mark.asyncio
async def test_a_cancelled_read_is_not_turned_into_a_failed_read() -> None:
    """asyncio cancellation of the caller (a lost lease cancels the effect) must keep propagating."""

    class Slow:
        async def token(self) -> str:
            await asyncio.sleep(30)
            return "never"

    task = asyncio.ensure_future(
        HttpMcpCaller(Slow()).call(f"{BASE}/mcp", handle="h", tool="get_asset_status", arguments={})
    )
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_a_failed_check_fails_the_run_as_retrieval_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The investigate handler records a read that failed a check like any other failed read: FAILED, "retrieval
    failed", and nothing drafted (ruling 13: no success assumption)."""
    log = Log()
    patch(monkeypatch, log)
    moves: list[tuple[Any, Any, Any]] = []
    kept = persistence.transition_run  # Plan H's recorder keeps the run row, which the graph's router rereads (T20)

    async def transition_run(_conn: Any, *, run_id: Any, src: Any, dst: Any, detail: Any = None) -> int:
        moves.append((src, dst, detail))
        return int(await kept(_conn, run_id=run_id, src=src, dst=dst, detail=detail))

    class Refusing:
        async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
            raise McpCallFailed(f"{tool}: the server advertises an unexpected tool set")

    monkeypatch.setattr(persistence, "transition_run", transition_run)
    deps, lease = make(log)
    deps.mcp = Refusing()
    asyncio.run(handlers.investigate(deps, dict(JOB), lease))
    assert moves[-1] == (RunState.RETRIEVING, RunState.FAILED, {"message": "retrieval failed"})
    assert "freeze_proposal" not in log.entries and "take_model_permit" not in log.entries


@pytest.mark.asyncio
async def test_a_real_sdk_failure_fails_the_run_as_retrieval_failed_not_interrupted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same outcome through the real caller and the real server: the answer to the handler's search does not
    satisfy the output schema the server advertises, the SDK raises inside the session, and the run still ends FAILED
    "retrieval failed" (before the fix the group escaped the handler and the run was left to the lease)."""
    log = Log()
    patch(monkeypatch, log)
    moves: list[tuple[Any, Any, Any]] = []
    kept = persistence.transition_run  # Plan H's recorder keeps the run row, which the graph's router rereads (T20)

    async def transition_run(_conn: Any, *, run_id: Any, src: Any, dst: Any, detail: Any = None) -> int:
        moves.append((src, dst, detail))
        return int(await kept(_conn, run_id=run_id, src=src, dst=dst, detail=detail))

    monkeypatch.setattr(persistence, "transition_run", transition_run)
    db = Database(UnitConn())
    async with caller_against(monkeypatch, db, tamper_output_schema("search_procedures")) as caller:
        deps, lease = make(log)
        deps.mcp = caller
        deps.urls = dataclasses.replace(deps.urls, mcp_read=f"{BASE}/mcp")
        await handlers.investigate(deps, dict(JOB), lease)
    assert moves[-1] == (RunState.RETRIEVING, RunState.FAILED, {"message": "retrieval failed"})
    assert "freeze_proposal" not in log.entries and "take_model_permit" not in log.entries

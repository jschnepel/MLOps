"""The worker's MCP client: one workload token, two servers, one handle per call (BUILD_SPEC §9, ADR-0003).

The token and the handle travel as HTTP headers on an httpx2 client the SDK transport uses (measured in the spike);
the handle is never a tool argument. A refusal at the transport (401) reaches the caller as the SDK's MCPError, and a
tool-level refusal as an error envelope; both become McpCallFailed so a handler records nothing it did not observe.

A read tool is held to the committed contracts, not to what the server says about itself (R029, Plan M ruling 13):
in the same session, before the call, the server must advertise exactly the three read tools and the called tool's
committed input schema (`check_listing`); the answer must be at most 256 KiB, not error-flagged, a valid tool result
of that tool by `schemas/tool-result.schema.json` and `ok` (`read_result`). Anything else is McpCallFailed, which the
investigate handler records as FAILED "retrieval failed": nothing is assumed to have succeeded.
"""

from __future__ import annotations

import json
from typing import Any, Final, Protocol

import httpx2
from mcp import Client, MCPError
from mcp.client.streamable_http import streamable_http_client
from mcp_types import CallToolResult, ListToolsResult
from ops_core import tool_contracts
from ops_core.jobs import JOB_RULES, JobType, Tool
from ops_core.mcp_protocol import PROTOCOL_VERSION

# A read handle's tools (AM-15): what mcp-read must advertise, no more and no fewer.
READ_TOOLS: Final = JOB_RULES[JobType.INVESTIGATE].allowed_tools


class McpCallFailed(Exception):
    """The call did not produce a tool result: transport, protocol or tool-level refusal, or a failed check."""


def failure_leaf(exc: BaseException) -> BaseException:
    """The first leaf of a possibly nested exception group. An error that escapes the client's context manager
    (a refused token, a connection failure) arrives wrapped in anyio task-group `ExceptionGroup`s (measured in the
    Plan D spike and both dry runs); a handler must see the transport failure, not the wrapper, or the run is never
    failed and its conversation slot stays held."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


def leaves(exc: BaseException) -> list[BaseException]:
    """Every leaf of a possibly nested exception group, in order (a plain exception is its own only leaf)."""
    if isinstance(exc, BaseExceptionGroup):
        return [leaf for member in exc.exceptions for leaf in leaves(member)]
    return [exc]


TRANSPORT_FAILURES = (MCPError, httpx2.HTTPError, OSError)


def check_listing(listing: ListToolsResult, tool: Tool) -> None:
    """R029's discovery check: the server lists exactly the read tools, once each, on one page, and advertises the
    called tool's committed input schema (canonical JSON). A listing with a `next_cursor` is refused: a later page
    could add a tool this check never saw.

    Limit (measured, mcp 2.3.0): the SDK filters the listing before this function sees it, dropping a tool whose
    `x-mcp-header` annotation is invalid (`ClientSession._absorb_tool_listing`). A server that adds a tool in that
    shape therefore passes this check unseen; the tool can still not be called through this client, which lists
    only to compare. A check on the raw listing is a debt line (Plan M, T30, with the transport-level bound).

    Raises:
        McpCallFailed: a tool added, removed or listed twice, a further page, or the called tool's schema altered.
    """
    advertised = listing.tools
    names = [entry.name for entry in advertised]
    if (
        listing.next_cursor is not None
        or len(names) != len(set(names))
        or set(names) != {read.value for read in READ_TOOLS}
    ):
        raise McpCallFailed(f"{tool.value}: the server advertises an unexpected tool set")
    schema = next(entry.input_schema for entry in advertised if entry.name == tool.value)
    if not tool_contracts.same_input_schema(tool, schema):
        raise McpCallFailed(f"{tool.value}: the advertised input schema is not the committed one")


def read_result(tool: Tool, result: CallToolResult) -> dict[str, Any]:
    """R029's result check: the read tool's answer as a valid `ok` tool result.

    Raises:
        McpCallFailed: error-flagged, larger than 256 KiB serialized, not a valid result of this tool, or not `ok`.
    """
    if result.is_error:
        raise McpCallFailed(f"{tool.value}: the result is error-flagged")
    # Ruling 13: the bound is on the tool result itself, the UTF-8 JSON of its structured content (the envelope), not
    # on the CallToolResult around it, which FastMCP fills with a second, text copy of the same envelope. The SDK has
    # parsed the body by the time it hands the result over (no hook stops it earlier), so the bound is applied after
    # parsing and before the content is used (a transport-level bound is T30's).
    try:
        size = len(json.dumps(result.structured_content, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise McpCallFailed(f"{tool.value}: the result fails the contract") from exc
    if size > tool_contracts.MAX_RESULT_BYTES:
        raise McpCallFailed(f"{tool.value}: the result is larger than the bound")
    try:
        document = tool_contracts.check_result(tool, result.structured_content)
    except tool_contracts.ContractViolation as exc:
        raise McpCallFailed(f"{tool.value}: the result fails the contract") from exc
    if document["status"] != "ok":
        raise McpCallFailed(f"{tool.value}: the server rejected the call")
    return document


class TokenSource(Protocol):
    """Where the caller gets its workload token, so tests and the real client share one seam."""

    async def token(self) -> str:
        """Return a bearer token valid now."""
        ...


class McpCaller(Protocol):
    """What a handler needs from an MCP client, so tests can script it without a transport."""

    async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call one tool on one server under one invocation handle and return its structured result."""
        ...


class HttpMcpCaller:
    """The real client: one fresh connection per call, token and handle sent as headers."""

    def __init__(
        self,
        token_source: TokenSource,
        *,
        connect_timeout: float = 10.0,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        """Hold the token source and the timeouts; connections are opened per call. `transport` lets unit tests reach
        an in-process server."""
        self._tokens = token_source
        self._timeout = httpx2.Timeout(connect_timeout, read=60.0)
        self._transport = transport

    async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call the tool over Streamable HTTP; every failure to obtain a valid tool result is McpCallFailed."""
        read = next((candidate for candidate in READ_TOOLS if candidate.value == tool), None)
        try:
            headers = {"Authorization": f"Bearer {await self._tokens.token()}", "X-Ops-Invocation": handle}
            async with (
                httpx2.AsyncClient(headers=headers, timeout=self._timeout, transport=self._transport) as http,
                Client(streamable_http_client(url, http_client=http), mode=PROTOCOL_VERSION) as client,
            ):
                if read is not None:  # discovery in the same session, before the call (ruling 13)
                    check_listing(await client.list_tools(), read)
                # The SDK itself checks the result against the output schema the server advertised and raises
                # RuntimeError on a mismatch, and if the server answers a call with a header mismatch it lists again
                # and retries inside this call, outside `check_listing`. Both are acceptable here: any failure of a
                # read becomes McpCallFailed below, and a retried answer still goes through `read_result` in full.
                result = await client.call_tool(tool, arguments)
        except McpCallFailed:
            raise
        except TRANSPORT_FAILURES as exc:
            raise McpCallFailed(f"{tool}: transport or protocol failure") from exc
        except BaseExceptionGroup as group:
            found = leaves(group)
            if read is not None:
                # Every leaf, not the first: a read that fails inside the session in any way is a failed read, unless
                # one leaf is a cancellation or another BaseException-only signal, which must go on propagating.
                if all(isinstance(leaf, Exception) for leaf in found):
                    failed = next((leaf for leaf in found if isinstance(leaf, McpCallFailed)), None)
                    if failed is not None:  # a failed check inside the session: the client's task group wraps it
                        raise failed from None
                    raise McpCallFailed(f"{tool}: the session failed ({type(found[0]).__name__})") from group
                raise
            leaf = failure_leaf(group)
            if isinstance(leaf, TRANSPORT_FAILURES):
                raise McpCallFailed(f"{tool}: transport or protocol failure") from leaf
            raise
        except Exception as exc:
            if read is None:
                raise
            # e.g. the SDK's RuntimeError for a result that does not satisfy the advertised output schema
            raise McpCallFailed(f"{tool}: the session failed ({type(exc).__name__})") from exc
        if read is not None:
            return read_result(read, result)
        # TODO(T20): the write tools (mcp-write) still get only T47's check: no discovery and no result-schema check.
        if result.is_error or not isinstance(result.structured_content, dict):
            raise McpCallFailed(f"{tool}: the server rejected the call")
        return result.structured_content

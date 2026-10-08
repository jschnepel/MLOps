"""The worker's MCP client: one workload token, two servers, one handle per call (BUILD_SPEC §9, ADR-0003).

The token and the handle travel as HTTP headers on an httpx2 client the SDK transport uses (measured in the spike);
the handle is never a tool argument. A refusal at the transport (401) reaches the caller as the SDK's MCPError, and a
tool-level refusal as an error envelope; both become McpCallFailed so a handler records nothing it did not observe.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx2
from mcp import Client, MCPError
from mcp.client.streamable_http import streamable_http_client


class McpCallFailed(Exception):
    """The call did not produce a tool result: transport, protocol or tool-level refusal."""


def failure_leaf(exc: BaseException) -> BaseException:
    """The first leaf of a possibly nested exception group. An error that escapes the client's context manager
    (a refused token, a connection failure) arrives wrapped in anyio task-group `ExceptionGroup`s (measured in the
    Plan D spike and both dry runs); a handler must see the transport failure, not the wrapper, or the run is never
    failed and its conversation slot stays held."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


TRANSPORT_FAILURES = (MCPError, httpx2.HTTPError, OSError)


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

    def __init__(self, token_source: TokenSource, *, connect_timeout: float = 10.0) -> None:
        """Hold the token source and the timeouts; connections are opened per call."""
        self._tokens = token_source
        self._timeout = httpx2.Timeout(connect_timeout, read=60.0)

    async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call the tool over Streamable HTTP; every failure to obtain a tool result is McpCallFailed."""
        headers = {"Authorization": f"Bearer {await self._tokens.token()}", "X-Ops-Invocation": handle}
        try:
            async with (
                httpx2.AsyncClient(headers=headers, timeout=self._timeout) as http,
                Client(streamable_http_client(url, http_client=http), mode="2026-07-28") as client,
            ):
                result = await client.call_tool(tool, arguments)
        except TRANSPORT_FAILURES as exc:
            raise McpCallFailed(f"{tool}: transport or protocol failure") from exc
        except BaseExceptionGroup as group:
            leaf = failure_leaf(group)
            if isinstance(leaf, TRANSPORT_FAILURES):
                raise McpCallFailed(f"{tool}: transport or protocol failure") from leaf
            raise
        if result.is_error or not isinstance(result.structured_content, dict):
            raise McpCallFailed(f"{tool}: the server rejected the call")
        return result.structured_content

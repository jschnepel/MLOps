"""The protocol-version guard on its own, as an ASGI app around a recording inner app (AM-30, Plan J ruling 4).

Catches: a POST to the MCP path without `MCP-Protocol-Version`, or with a handshake-era or doubled value, reaching the
SDK (whose legacy stateless path checks no version); a refusal that echoes the value it was sent; a guard that also
blocks health, metadata or a GET the SDK answers itself; a guard mounted under a prefix that stops matching; and the
pinned version or error code drifting from the installed SDK's.
"""

import asyncio
import json
from typing import Any

import pytest
from mcp_types.jsonrpc import UNSUPPORTED_PROTOCOL_VERSION as SDK_UNSUPPORTED
from mcp_types.version import MODERN_PROTOCOL_VERSIONS
from ops_core.mcp_protocol import PROTOCOL_VERSION, REFUSAL, UNSUPPORTED_PROTOCOL_VERSION, ProtocolVersionGuard


class Inner:
    """The SDK's place: records each scope it is handed and answers 200."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        self.seen.append(scope["path"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"inner"})


def call(
    guard: ProtocolVersionGuard, method: str, path: str, headers: list[tuple[bytes, bytes]], root: str = ""
) -> Any:
    """One request through the guard; the messages it sent back."""
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"{}", "more_body": False}

    async def send(message: Any) -> None:
        sent.append(dict(message))

    scope = {"type": "http", "method": method, "path": path, "root_path": root, "headers": headers}
    asyncio.run(guard(scope, receive, send))
    return sent


def test_the_pinned_values_are_the_installed_sdks() -> None:
    assert MODERN_PROTOCOL_VERSIONS == (PROTOCOL_VERSION,)
    assert UNSUPPORTED_PROTOCOL_VERSION == SDK_UNSUPPORTED
    body = json.loads(REFUSAL)
    assert body["error"]["code"] == SDK_UNSUPPORTED and body["error"]["data"] == {"supported": ["2026-07-28"]}


@pytest.mark.parametrize(
    "headers",
    [
        [],  # no header: the SDK's legacy stateless path
        [(b"mcp-protocol-version", b"2025-11-25")],  # a handshake-era version
        [(b"mcp-protocol-version", b"2024-11-05")],
        [(b"mcp-protocol-version", b"2026-07-28 ")],  # not the pinned value byte for byte
        [(b"mcp-protocol-version", b"2026-07-28"), (b"mcp-protocol-version", b"2025-11-25")],  # two copies
    ],
    ids=["absent", "2025-11-25", "2024-11-05", "padded", "doubled"],
)
def test_a_post_without_exactly_the_pinned_version_is_refused_before_the_sdk(
    headers: list[tuple[bytes, bytes]],
) -> None:
    inner = Inner()
    sent = call(ProtocolVersionGuard(inner), "POST", "/mcp", headers)
    assert inner.seen == []
    assert sent[0]["status"] == 400 and (b"content-type", b"application/json") in sent[0]["headers"]
    assert sent[1]["body"] == REFUSAL  # one constant body: the value that was sent is never echoed


def test_everything_else_passes_untouched() -> None:
    inner = Inner()
    guard = ProtocolVersionGuard(inner)
    assert call(guard, "POST", "/mcp", [(b"mcp-protocol-version", b"2026-07-28")])[0]["status"] == 200
    assert call(guard, "GET", "/mcp", [])[0]["status"] == 200  # the SDK answers a GET itself (405)
    assert call(guard, "POST", "/health/ready", [])[0]["status"] == 200
    assert call(guard, "GET", "/.well-known/oauth-protected-resource/mcp", [])[0]["status"] == 200
    assert inner.seen == ["/mcp", "/mcp", "/health/ready", "/.well-known/oauth-protected-resource/mcp"]


def test_a_guard_mounted_under_a_prefix_still_matches_its_path() -> None:
    inner = Inner()
    assert call(ProtocolVersionGuard(inner), "POST", "/read/mcp", [], root="/read")[0]["status"] == 400
    assert inner.seen == []

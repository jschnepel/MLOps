"""The protocol-version rule both MCP servers enforce before the SDK sees a request (AM-30, SA:571; Plan J ruling 4).

The pinned revision, 2026-07-28, is session-less: every request carries its version in the `MCP-Protocol-Version`
header and in `params._meta`, and the SDK compares the two. But the SDK sends a POST that has no such header, or a
handshake-era one (2024-11-05 to 2025-11-25), down its legacy stateless path, where no per-request version is checked.
`ProtocolVersionGuard` closes that path: a POST to the MCP endpoint must carry exactly one header, equal to the pinned
version, or it is answered HTTP 400 with a JSON-RPC error before the SDK, and so before bearer auth, runs. An
unauthenticated client therefore learns this rule and nothing about its token. The value sent is never echoed. Every
other request (health, the protected-resource metadata, a GET or DELETE the SDK answers itself) passes untouched, and
a request whose header is right but whose `_meta` disagrees is the SDK's own HEADER_MISMATCH.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any, Final

PROTOCOL_VERSION: Final = "2026-07-28"  # AM-30; the worker's client pins the same (ops_worker.mcp)
# The 2026-07-28 code for "unsupported protocol version" (mcp_types.jsonrpc; a unit test compares the two). Core does
# not depend on the SDK, so the value is copied here.
UNSUPPORTED_PROTOCOL_VERSION: Final = -32022
HEADER: Final = b"mcp-protocol-version"  # ASGI header names arrive lower-case
# The streamable HTTP endpoint: both servers pass it to the SDK as `streamable_http_path` and the guard matches it, so
# the two cannot drift apart. `/mcp/` is the inner router's 307 to this path, where the guard then answers.
MCP_PATH: Final = "/mcp"

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

REFUSAL: Final = json.dumps(
    {
        "jsonrpc": "2.0",
        "id": None,  # the body is not read, so the request id is unknown (JSON-RPC 2.0 allows null here)
        "error": {
            "code": UNSUPPORTED_PROTOCOL_VERSION,
            "message": "Unsupported protocol version",
            "data": {"supported": [PROTOCOL_VERSION]},
        },
    },
    separators=(",", ":"),
).encode("utf-8")


def route_path(scope: Scope) -> str:
    """The request path below the mount point (Starlette's rule): a guard mounted under a prefix still matches."""
    path: str = scope["path"]
    root: str = scope.get("root_path", "")
    if root and path.startswith(root) and path[len(root) :].startswith("/"):
        return path[len(root) :]
    return path


class ProtocolVersionGuard:
    """Refuse a POST to the MCP path that does not carry exactly `MCP-Protocol-Version: 2026-07-28`."""

    def __init__(self, app: ASGIApp, *, path: str = MCP_PATH) -> None:
        """Wrap the SDK's app; `path` is the streamable HTTP endpoint it serves."""
        self._app = app
        self._path = path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] == "POST" and route_path(scope) == self._path:
            sent = [value for name, value in scope["headers"] if name.lower() == HEADER]
            # Exactly one header with exactly the pinned value: a second copy would let the SDK see another.
            if sent != [PROTOCOL_VERSION.encode("ascii")]:
                await send(
                    {
                        "type": "http.response.start",
                        "status": 400,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(REFUSAL)).encode("ascii")),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": REFUSAL})
                return
        await self._app(scope, receive, send)

"""The API's three pure ASGI middlewares and the one SafeError builder they share with the routes (Plan G rulings 17,
19 and 20; BUILD_SPEC §7 safe errors, §17 the 64 KiB body).

`RequestId` gives every request a server-made id: it is echoed as `X-Request-Id`, carried in every error body and
written on every error log line, so an operator can match a client's report to the log. A client-sent
`X-Request-Id` is never trusted (it would let a caller plant ids in the log). `BodyLimit` refuses an oversized body
before any route runs: Starlette's own `RequestBodyLimitMiddleware` answers a plain-text 413 after the route has
already run and never stops a route that reads no body (spike §5: a conversation was created and still got 413), so
this middleware pre-reads up to the limit and replays the bytes, the shape the spike measured clean. A client that
disconnects before its body is complete reaches no route at all: what arrived is not the request.
"""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

from fastapi.responses import JSONResponse
from ops_core.contracts import ErrorCode, SafeError
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger("ops_api")
REQUEST_ID_HEADER = "X-Request-Id"
_STATE_KEY = "request_id"


class BodyTooLarge(Exception):
    """The body grew past the limit while it was being read (a chunked body declares no length)."""


class BodyIncomplete(Exception):
    """The client disconnected before the last chunk of its body arrived."""


def request_id_of(scope: Scope) -> UUID:
    """The id `RequestId` stored for this request, or a new one when the middleware did not run.

    The id lives in `scope["state"]`, the dict Starlette's `request.state` wraps, so a handler that only has the
    request (the catch-all, which runs outside the user middleware) still finds it.
    """
    state = scope.setdefault("state", {})
    found = state.get(_STATE_KEY)
    if isinstance(found, UUID):
        return found
    made = uuid4()
    state[_STATE_KEY] = made
    return made


def safe_response(
    request_id: UUID,
    status: int,
    code: ErrorCode,
    message: str,
    *,
    retryable: bool = False,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """A SafeError response: `{code, message, retryable, request_id}` and nothing else (BS:301).

    `retryable` is the caller's statement that the same request may succeed later (ruling 19); a 401 also names the
    Bearer scheme. The id travels as a header too, because the catch-all's response bypasses `RequestId`'s send.
    """
    body = SafeError(code=code, message=message, retryable=retryable, request_id=request_id)
    out = {REQUEST_ID_HEADER: str(request_id), **(headers or {})}
    if status == 401:
        out["WWW-Authenticate"] = "Bearer"
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"), headers=out)


class RequestId:
    """Assign each HTTP request a fresh id and echo it on the response (ruling 20)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid4()
        scope.setdefault("state", {})[_STATE_KEY] = request_id
        header = (REQUEST_ID_HEADER.lower().encode("ascii"), str(request_id).encode("ascii"))

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                # Replace rather than add: `safe_response` already set the same value on error responses.
                kept = [h for h in message.get("headers", []) if h[0].lower() != header[0]]
                message = {**message, "headers": [*kept, header]}
            await send(message)

        await self.app(scope, receive, send_with_id)


async def read_bounded(receive: Receive, max_bytes: int) -> bytes:
    """Read the whole request body, raising BodyTooLarge as soon as it passes `max_bytes`.

    Counting the bytes that arrive, not the declared length, is what stops a `Content-Length` that lies low.

    Raises:
        BodyTooLarge: the body passed `max_bytes`.
        BodyIncomplete: the client disconnected first; the bytes that arrived may still parse (a body cut after a
            closing brace), so they must never be handed on as the request (Starlette's own read raises too).
    """
    parts: list[bytes] = []
    total = 0
    while True:
        message = await receive()
        if message["type"] != "http.request":
            raise BodyIncomplete
        chunk = message.get("body", b"")
        total += len(chunk)
        if total > max_bytes:
            raise BodyTooLarge
        parts.append(chunk)
        if not message.get("more_body", False):
            break
    return b"".join(parts)


class BodyLimit:
    """Refuse a request body over `max_bytes` with the 422 SafeError before any route runs (ruling 17; BS:301 puts
    shape and content limits under 422, and 413 is not in the spec's list)."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope.get("headers", [])).get(b"content-length")
        # More than 19 digits is past any real length, and int() itself refuses a string of over 4300 digits with a
        # ValueError that would escape as a 503; the length test runs first, so int() only ever sees a short number.
        if declared is not None and (not declared.isdigit() or len(declared) > 19 or int(declared) > self.max_bytes):
            await self._refuse(scope, receive, send)  # refused without reading a byte
            return
        try:
            body = await read_bounded(receive, self.max_bytes)
        except BodyTooLarge:
            await self._refuse(scope, receive, send)
            return
        except BodyIncomplete:
            return  # the client is gone: no route runs for half a request, and nobody is left to read an answer
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()  # after the body: the disconnect, when the server sends one

        await self.app(scope, replay, send)

    async def _refuse(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = safe_response(
            request_id_of(scope), 422, ErrorCode.INVALID_INPUT, f"request body exceeds {self.max_bytes} bytes"
        )
        await response(scope, receive, send)


class SafeErrors:
    """The outermost catch-all: an escaped exception becomes the safe 503 and one log line, and is not re-raised.

    Starlette's own catch-all re-raises after it answers, so the server would log the traceback again, with the
    exception's text and its chained cause. BS:301 keeps stack traces out of bodies and the rule "the class name,
    never the text" keeps them out of logs (a psycopg DETAIL names a tenant and a key), so the response is the
    report to the client and the single line below is the trace.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def track(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, track)
        except Exception as exc:  # noqa: BLE001 - the catch-all exists to answer whatever escaped
            request_id = request_id_of(scope)
            log.error("request %s failed: %s", request_id, type(exc).__name__)
            if not started:  # a response already under way cannot be replaced; the log line is all that is left
                response = safe_response(request_id, 503, ErrorCode.UNAVAILABLE, "service error")
                await response(scope, receive, send)

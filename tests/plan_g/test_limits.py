"""The two ASGI middlewares of Plan G (rulings 17 and 20): the body limit refuses before any route runs, whatever the
client declares, and every response carries a server-made request id.

Catches: Starlette's own limiter shape (a plain-text 413 after the route already ran, spike §5), a chunked body that
is never counted, a `Content-Length` that lies low and smuggles the rest, a malformed length read as "no limit", a
route that sees a truncated body (one cut short by a client that disconnected included), a request id taken from
the client, and an id that repeats.
"""

import asyncio
import json
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
from ops_api.app import create_app
from ops_api.limits import REQUEST_ID_HEADER, BodyLimit, RequestId
from ops_core.settings import AdmissionSettings
from starlette.types import Message, Receive, Scope, Send

from tests.plan_d.test_api import FakeStore, StubVerifier
from tests.plan_f.auth_fakes import fake_auth

LIMIT = 1024


class Echo:
    """An inner app that records whether it ran and answers with the length of the body it read."""

    def __init__(self) -> None:
        self.ran = False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.ran = True
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body", False):
                break
        payload = json.dumps({"received": len(body)}).encode()
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": payload})


def call(app: Any, chunks: list[bytes], headers: list[tuple[bytes, bytes]]) -> tuple[int, dict[str, str], Any]:
    """Drive one HTTP request through a raw ASGI app; returns status, headers and the parsed JSON body."""
    scope = {"type": "http", "method": "POST", "path": "/", "headers": headers, "query_string": b""}
    pending = [{"type": "http.request", "body": c, "more_body": i < len(chunks) - 1} for i, c in enumerate(chunks)] or [
        {"type": "http.request", "body": b"", "more_body": False}
    ]
    sent: list[Message] = []

    async def receive() -> Message:
        return pending.pop(0) if pending else {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    found = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    return start["status"], found, json.loads(body)


def test_a_declared_length_over_the_limit_is_refused_unread() -> None:
    inner = Echo()
    status, _, doc = call(BodyLimit(inner, LIMIT), [b"x" * 10], [(b"content-length", str(LIMIT + 1).encode())])
    assert status == 422 and doc["code"] == "INVALID_INPUT" and doc["message"] == f"request body exceeds {LIMIT} bytes"
    assert not inner.ran


def test_a_chunked_body_over_the_limit_is_refused_before_the_route_runs() -> None:
    inner = Echo()
    status, _, doc = call(BodyLimit(inner, LIMIT), [b"x" * 600, b"x" * 600], [])
    assert status == 422 and doc["retryable"] is False and not inner.ran


def test_a_content_length_that_lies_low_is_caught_by_counting() -> None:
    inner = Echo()
    status, _, _ = call(BodyLimit(inner, LIMIT), [b"x" * 2000], [(b"content-length", b"10")])
    assert status == 422 and not inner.ran


def test_a_malformed_content_length_is_refused() -> None:
    for declared in (b"-1", b"1e3", b"", b"12 34", b"1" * 4400):  # the last: past int()'s 4300-digit limit
        inner = Echo()
        status, _, _ = call(BodyLimit(inner, LIMIT), [b"{}"], [(b"content-length", declared)])
        assert status == 422 and not inner.ran, declared


def test_a_body_at_the_limit_reaches_the_route_intact() -> None:
    inner = Echo()
    status, _, doc = call(BodyLimit(inner, LIMIT), [b"x" * 500, b"x" * 524], [])
    assert status == 200 and doc == {"received": LIMIT} and inner.ran


def test_a_client_that_disconnects_mid_body_reaches_no_route() -> None:
    inner = Echo()
    scope = {"type": "http", "method": "POST", "path": "/", "headers": [], "query_string": b""}
    pending: list[Message] = [{"type": "http.request", "body": b'{"kind": "investigate"}', "more_body": True}]
    sent: list[Message] = []

    async def receive() -> Message:
        return pending.pop(0) if pending else {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        sent.append(message)

    asyncio.run(BodyLimit(inner, LIMIT)(scope, receive, send))
    # What arrived parses as JSON, but it is not the request: the client is gone, so nothing runs and nothing answers.
    assert not inner.ran and sent == []


def test_every_response_carries_a_fresh_server_made_request_id() -> None:
    planted = "00000000-0000-0000-0000-000000000000"
    seen = set()
    for _ in range(3):
        status, headers, _ = call(RequestId(Echo()), [b"{}"], [(b"x-request-id", planted.encode())])
        assert status == 200 and headers[REQUEST_ID_HEADER.lower()] != planted  # the client's value is ignored
        seen.add(UUID(headers[REQUEST_ID_HEADER.lower()]))
    assert len(seen) == 3


def test_a_body_refusal_through_the_app_creates_nothing_and_names_its_request() -> None:
    fake = FakeStore()
    app = create_app(
        StubVerifier(),
        store_factory=lambda: fake,
        auth_factory=fake_auth,
        admission=AdmissionSettings(max_body_bytes=LIMIT),
    )
    with TestClient(app) as c:
        r = c.post("/api/v1/conversations", headers={"Authorization": "Bearer alex"}, content=b" " * (LIMIT + 1))
    assert r.status_code == 422 and r.json()["message"] == f"request body exceeds {LIMIT} bytes"
    assert r.headers[REQUEST_ID_HEADER] == r.json()["request_id"]
    assert fake.conversations == {}  # spike §5: Starlette's limiter let this route run and create one

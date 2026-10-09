"""The fail-closed enabled check (SA:542-546, T11 review note 1) against a fake admin API served in-process: the
answer is the `enabled` flag, a 404 is a deleted user, and everything else (timeout, refusal, a 5xx, an unusable
body, a token endpoint that fails, an empty realm listing) is AdminUnavailable within the budget.

Catches: a slow Keycloak that blocks a decision past 2 s, a 403 from a misconfigured role read as "enabled", a
listing that returns nothing and would deactivate every membership, and a token refresh that is not single-flight.
"""

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
import pytest_asyncio
from ops_core.keycloak_admin import AdminUnavailable, AdminUsers
from ops_core.tokens import WorkloadTokenSource
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

ALEX = UUID("2fc05986-c7ec-544c-b628-fdb112bbf18a")
SAM = UUID("03f7eb09-e18d-5f33-bf75-12c57d5aaa54")


class FakeKeycloak:
    """Just enough of the admin API: a token endpoint and the two user reads, with knobs for each failure."""

    def __init__(self) -> None:
        self.users: dict[UUID, bool] = {ALEX: True, SAM: False}
        self.status: int | None = None  # force this status on every user read
        self.delay = 0.0
        self.token_calls = 0
        self.token_status = 200
        self.body: Any = None  # force this body on the single-user read

    async def token(self, request: Request) -> Response:
        self.token_calls += 1
        if self.token_status != 200:
            return JSONResponse({"error": "invalid_client"}, status_code=self.token_status)
        return JSONResponse({"access_token": f"t{self.token_calls}", "expires_in": 300})

    async def user(self, request: Request) -> Response:
        await asyncio.sleep(self.delay)
        if request.headers.get("authorization", "") != f"Bearer t{self.token_calls}":
            return JSONResponse({"error": "HTTP 401 Unauthorized"}, status_code=401)
        if self.status is not None:
            return JSONResponse({"error": "forced"}, status_code=self.status)
        if self.body is not None:
            return Response(json.dumps(self.body), media_type="application/json")
        try:
            uid = UUID(request.path_params["uid"])
        except ValueError:
            return JSONResponse({"error": "User not found"}, status_code=404)
        if uid not in self.users:
            return JSONResponse({"error": "User not found"}, status_code=404)
        return JSONResponse({"id": str(uid), "username": "x", "enabled": self.users[uid]})

    async def listing(self, request: Request) -> Response:
        await asyncio.sleep(self.delay)
        if self.status is not None:
            return JSONResponse({"error": "forced"}, status_code=self.status)
        first, size = int(request.query_params["first"]), int(request.query_params["max"])
        rows = [{"id": str(u), "enabled": e} for u, e in sorted(self.users.items(), key=lambda kv: str(kv[0]))]
        return JSONResponse(rows[first : first + size])

    def app(self) -> Starlette:
        return Starlette(
            routes=[
                Route("/token", self.token, methods=["POST"]),
                Route("/admin/users", self.listing),
                Route("/admin/users/{uid}", self.user),
            ]
        )


@pytest_asyncio.fixture
async def admin() -> AsyncIterator[tuple[AdminUsers, FakeKeycloak]]:
    fake = FakeKeycloak()
    client = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=fake.app()), base_url="http://kc.test")

    async def post(url: str, form: dict[str, str]) -> dict[str, Any]:
        response = await client.post(url, data=form)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data

    tokens = WorkloadTokenSource(
        token_url="http://kc.test/token", client_id="ops-view-users", client_secret="s", post=post
    )
    users = AdminUsers(users_url="http://kc.test/admin/users", tokens=tokens, client=client, timeout=0.3)
    try:
        yield users, fake
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_enabled_disabled_and_deleted(admin: tuple[AdminUsers, FakeKeycloak]) -> None:
    users, fake = admin
    assert await users.enabled(ALEX) is True
    assert await users.enabled(SAM) is False
    assert await users.enabled(uuid4()) is False  # 404: deleted maps to "not enabled" (T11 review note 2)
    assert fake.token_calls == 1  # one cached service-account token for the three reads


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 500, 503])
async def test_any_other_status_is_unavailable(admin: tuple[AdminUsers, FakeKeycloak], status: int) -> None:
    users, fake = admin
    fake.status = status
    with pytest.raises(AdminUnavailable):
        await users.enabled(ALEX)
    if status == 401:
        assert fake.token_calls == 2  # one fresh token and one retry, then fail closed


@pytest.mark.asyncio
async def test_a_stale_token_is_replaced_once(admin: tuple[AdminUsers, FakeKeycloak]) -> None:
    users, fake = admin
    assert await users.enabled(ALEX) is True
    fake.token_calls += 1  # the realm now expects a newer token than the cached one (a re-import)
    assert await users.enabled(ALEX) is True
    assert fake.token_calls == 3  # the cached t1 was refused, t3 was fetched and accepted


@pytest.mark.asyncio
async def test_a_slow_answer_is_unavailable_within_the_budget(admin: tuple[AdminUsers, FakeKeycloak]) -> None:
    users, fake = admin
    fake.delay = 2.0
    started = time.monotonic()
    with pytest.raises(AdminUnavailable):
        await users.enabled(ALEX)
    assert time.monotonic() - started < 1.0  # the 0.3 s budget, not the 2 s the server took


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"id": "x", "enabled": "yes"}, [], {"enabled": True}, "text"])
async def test_an_unusable_body_is_unavailable(admin: tuple[AdminUsers, FakeKeycloak], body: Any) -> None:
    users, fake = admin
    fake.body = body
    with pytest.raises(AdminUnavailable):
        await users.enabled(ALEX)


@pytest.mark.asyncio
async def test_a_failing_token_endpoint_is_unavailable(admin: tuple[AdminUsers, FakeKeycloak]) -> None:
    users, fake = admin
    fake.token_status = 500
    with pytest.raises(AdminUnavailable):
        await users.enabled(ALEX)


@pytest.mark.asyncio
async def test_listing_pages_and_refuses_an_empty_realm(admin: tuple[AdminUsers, FakeKeycloak]) -> None:
    users, fake = admin
    fake.users = {uuid4(): i % 2 == 0 for i in range(205)}
    listed = await users.list_enabled()
    assert listed == fake.users  # three pages of 100, 100 and 5
    fake.users = {}
    with pytest.raises(AdminUnavailable):  # nothing listed cannot be told from a broken listing: fail closed
        await users.list_enabled()


@pytest.mark.asyncio
async def test_concurrent_checks_share_one_token_fetch(admin: tuple[AdminUsers, FakeKeycloak]) -> None:
    users, fake = admin
    results = await asyncio.gather(*(users.enabled(ALEX) for _ in range(8)))
    assert results == [True] * 8 and fake.token_calls == 1

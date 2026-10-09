"""The Keycloak admin API as the `ops-view-users` service account (AM-20.7 revocation (b) and (c)).

Two reads and nothing else: one user's `enabled` flag for the API's fail-closed check before a decision-class
mutation (SA:542-546: 2 s budget, cached service-account token, 503 `retryable` when Keycloak is down or slow), and
the user list for the sweeper's membership sync (SA:547). A 404 is a deleted user (T11 review note 2); every other
surprise is `AdminUnavailable`, so a misconfigured role (403), a stale token (401), a 5xx, a timeout or a malformed
body all fail closed rather than read as "enabled". The client dials `settings.Keycloak.server_url` on one keep-alive
connection: on the dev machine a new connection through `localhost` costs about 2 s (spike §3), the whole budget.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import httpx2

from ops_core import settings
from ops_core.tokens import TokenRejected, WorkloadTokenSource

PAGE = 100  # Keycloak's `max` per listing request; `first` pages through the realm


class AdminUnavailable(Exception):
    """Keycloak did not answer the question within the budget: the caller fails closed (503 retryable, or no sync)."""


class AdminUsers:
    """`enabled(subject)` and `list_enabled()` under one overall deadline each."""

    def __init__(
        self, *, users_url: str, tokens: WorkloadTokenSource, client: httpx2.AsyncClient, timeout: float
    ) -> None:
        self._users_url = users_url.rstrip("/")
        self._tokens = tokens
        self._client = client
        self._timeout = timeout

    async def enabled(self, subject: UUID) -> bool:
        """True only when Keycloak says the user exists and is enabled; False for disabled or deleted (404)."""
        try:
            return await asyncio.wait_for(self._enabled(subject), self._timeout)
        except TimeoutError as exc:
            raise AdminUnavailable("admin API did not answer within the budget") from exc

    async def list_enabled(self) -> dict[UUID, bool]:
        """Every realm user's flag, paged; an empty listing is refused (it cannot be told from a broken one)."""
        try:
            return await asyncio.wait_for(self._list_enabled(), self._timeout)
        except TimeoutError as exc:
            raise AdminUnavailable("admin API did not answer within the budget") from exc

    async def aclose(self) -> None:
        """Close the keep-alive connection (process shutdown)."""
        await self._client.aclose()

    async def _get(self, url: str, params: dict[str, str] | None = None) -> httpx2.Response:
        try:
            token, response = await self._authorised_get(url, params)
            if response.status_code == 401:
                # A cached token the realm no longer accepts (a re-import, a key rotation): fetch once, retry once,
                # inside the same budget (round-1 finding M15).
                self._tokens.invalidate(token)
                _, response = await self._authorised_get(url, params)
            return response
        except (httpx2.HTTPError, OSError, TokenRejected, ValueError) as exc:
            # The message names the class of failure only: a token endpoint reply could carry the secret's error text.
            raise AdminUnavailable(f"admin API unreachable: {exc.__class__.__name__}") from exc

    async def _authorised_get(self, url: str, params: dict[str, str] | None) -> tuple[str, httpx2.Response]:
        token = await self._tokens.token()
        return token, await self._client.get(url, params=params, headers={"Authorization": f"Bearer {token}"})

    async def _enabled(self, subject: UUID) -> bool:
        response = await self._get(f"{self._users_url}/{subject}")
        if response.status_code == 404:
            return False
        if response.status_code != 200:
            raise AdminUnavailable(f"admin API answered {response.status_code}")
        body = _json(response)
        usable = (
            isinstance(body, dict) and str(body.get("id")) == str(subject) and isinstance(body.get("enabled"), bool)
        )
        if not usable:
            raise AdminUnavailable("admin API reply is unusable")
        return bool(body["enabled"])

    async def _list_enabled(self) -> dict[UUID, bool]:
        out: dict[UUID, bool] = {}
        first = 0
        while True:
            params = {"briefRepresentation": "true", "first": str(first), "max": str(PAGE)}
            response = await self._get(self._users_url, params)
            if response.status_code != 200:
                raise AdminUnavailable(f"admin API answered {response.status_code}")
            page = _json(response)
            if not isinstance(page, list):
                raise AdminUnavailable("admin API listing is unusable")
            for entry in page:
                if not isinstance(entry, dict) or not isinstance(entry.get("enabled"), bool):
                    raise AdminUnavailable("admin API listing is unusable")
                try:
                    out[UUID(str(entry.get("id")))] = bool(entry["enabled"])
                except ValueError as exc:
                    raise AdminUnavailable("admin API listing carries a non-UUID id") from exc
            if len(page) < PAGE:
                break
            first += PAGE
        if not out:
            raise AdminUnavailable("admin API listed no users")
        return out


def _json(response: httpx2.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise AdminUnavailable("admin API reply is not JSON") from exc


def admin_users(*, keycloak: settings.Keycloak, client_secret: str, timeout: float) -> AdminUsers:
    """The production client: one keep-alive connection to `server_url` shared by the token source and the reads."""
    client = httpx2.AsyncClient(timeout=httpx2.Timeout(timeout))

    async def post(url: str, form: dict[str, str]) -> dict[str, Any]:
        response = await client.post(url, data=form)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data

    tokens = WorkloadTokenSource(
        token_url=keycloak.token_url, client_id="ops-view-users", client_secret=client_secret, post=post
    )
    return AdminUsers(users_url=keycloak.admin_users_url, tokens=tokens, client=client, timeout=timeout)

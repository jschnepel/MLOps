"""mcp-read's client for asset-sim (T16; Plan M rulings 6, 8, 12 and 15; SA:555; BS:364).

mcp-read calls asset-sim with its own workload token (client `ops-mcp-read`, audience `asset-sim`), never with the
worker's token and never with the invocation handle; the only context it forwards is what `asset_scope` returned for
the handle: the run's tenant (`X-Ops-Tenant-Id`) and the database instant to answer at (`X-Ops-As-Of`), with the
run's asset in the path and, for alerts, the run's interval. Each call happens outside any database transaction, with
a 10-second timeout and no retry here (the worker does not retry either today: it fails the run on any failed read,
and honouring `retryable` is T20's). Failures map to one exception each, which the tools turn into
envelope codes (ruling 15): a transport error, a timeout or a 5xx is `Unavailable` (retryable), a 404 is `AssetMissing`
(an unknown asset and another tenant's alike), a 400 to a request that carried a cursor is `CursorRejected`, and
anything else, or a body that is not a JSON object, is `UpstreamInvalid`. A 401 also drops the cached token, so the
next call fetches a fresh one.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from typing import Any, Final, Protocol
from urllib.parse import quote

import httpx2
from ops_core import persistence, settings
from ops_core.tokens import TokenRejected, WorkloadTokenSource

CLIENT_ID: Final = "ops-mcp-read"  # the realm's workload client whose tokens carry aud asset-sim
TIMEOUT_SECONDS: Final = 10.0  # ruling 15
ASSET_ID: Final = re.compile(r"[A-Z][A-Z0-9_-]{0,31}")  # schemas/tools/get_asset_status.input.schema.json
ASSET_TYPE: Final = re.compile(r"[a-z][a-z0-9_-]{0,39}")  # the corpus's asset-family names


class AssetSimError(Exception):
    """asset-sim did not answer with data; `code` and `retryable` are what the tool's error envelope carries."""

    code = "UPSTREAM_INVALID"
    retryable = False


class Unavailable(AssetSimError):
    """A transport error, a timeout, a 5xx or a 401 to mcp-read's token: try again later."""

    code = "UNAVAILABLE"
    retryable = True


class AssetMissing(AssetSimError):
    """asset-sim knows no such asset for the run's tenant (unknown and another tenant's alike)."""

    code = "NOT_FOUND"


class CursorRejected(AssetSimError):
    """The cursor is malformed or was issued for another request."""

    code = "INVALID_CURSOR"


class UpstreamInvalid(AssetSimError):
    """An answer that is not the contract's (ruling 15: mcp-read validates asset-sim's data before returning it)."""


class TokenSource(Protocol):
    """Where the client gets its workload token (WorkloadTokenSource in production)."""

    async def token(self) -> str: ...

    def invalidate(self, stale: str | None = None) -> None: ...


class AssetSim(Protocol):
    """What the tools need from asset-sim, so unit tests can stand one in."""

    async def asset_type(self, scope: persistence.AssetScope) -> str | None:
        """The run's asset's type, or None when asset-sim does not know the asset (ruling 12)."""
        ...

    async def status(self, scope: persistence.AssetScope) -> dict[str, Any]:
        """`get_asset_status`'s data for the run's asset as of `scope.as_of`."""
        ...

    async def alerts(self, scope: persistence.AssetScope, *, limit: int, cursor: str | None) -> dict[str, Any]:
        """One page of `get_recent_alerts`'s data for the run's asset and interval as of `scope.as_of`."""
        ...

    async def aclose(self) -> None:
        """Release the connections."""
        ...


def rfc3339(value: datetime) -> str:
    """The `Z` spelling the contracts use, with microseconds only when the instant has them."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class HttpAssetSim:
    """The real client: one pooled httpx2 client, mcp-read's workload token, the forwarded context as headers."""

    def __init__(
        self, base_url: str, tokens: TokenSource, *, transport: httpx2.AsyncBaseTransport | None = None
    ) -> None:
        """`transport` lets unit tests answer without a socket."""
        self._base = base_url.rstrip("/")
        self._tokens = tokens
        self._http = httpx2.AsyncClient(timeout=TIMEOUT_SECONDS, transport=transport)

    @classmethod
    def from_settings(cls) -> HttpAssetSim:
        """Wired from the environment and the secret file, as the lifespan builds it (ruling 6)."""
        return cls(
            settings.urls().asset_sim,
            WorkloadTokenSource(
                token_url=settings.keycloak().token_url,
                client_id=CLIENT_ID,
                client_secret=settings.read_secret("kc_client_secret_ops_mcp_read"),
            ),
        )

    async def _get(
        self, scope: persistence.AssetScope, suffix: str, params: dict[str, str] | None = None
    ) -> dict[str, Any]:
        # The run's asset id is any text the admission stored; a path segment that is not an asset id is never sent.
        if not ASSET_ID.fullmatch(scope.asset_id):
            raise AssetMissing("the run's asset id is not an asset id")
        try:
            # One 10-second budget for the token fetch and the request together (ruling 15), not 10 s for each phase.
            async with asyncio.timeout(TIMEOUT_SECONDS):
                token = await self._tokens.token()
                response = await self._http.get(
                    f"{self._base}/assets/{quote(scope.asset_id, safe='')}{suffix}",
                    params=params,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "X-Ops-Tenant-Id": str(scope.tenant_id),
                        "X-Ops-As-Of": rfc3339(scope.as_of),
                    },
                )
        # Beyond transport errors: the token endpoint's reply can fail to parse or hold a bad `expires_in` (ValueError,
        # TypeError), a client closed by a shutting-down lifespan raises RuntimeError, and the budget's own expiry is
        # a TimeoutError (an OSError). None of them may skip the envelope, and none puts its text in the answer.
        except (httpx2.HTTPError, OSError, TokenRejected, ValueError, TypeError, RuntimeError) as exc:
            raise Unavailable("asset-sim could not be reached") from exc
        status = response.status_code
        if status == 200:
            try:
                body = response.json()
            except ValueError as exc:
                raise UpstreamInvalid("asset-sim answered a body that is not JSON") from exc
            if not isinstance(body, dict):
                raise UpstreamInvalid("asset-sim answered a body that is not an object")
            return body
        if status == 404:
            raise AssetMissing("asset-sim knows no such asset for this tenant")
        if status == 401:
            self._tokens.invalidate(token)  # a stale or revoked token: the next call fetches another
            raise Unavailable("asset-sim refused mcp-read's token")
        if status >= 500:
            raise Unavailable("asset-sim is unavailable")
        # asset-sim answers 400 for any invalid request, but mcp-read builds every other parameter itself (the run's
        # interval in canonical spelling, a limit inside the schema's bounds), so a 400 to a request that carried the
        # caller's cursor can only be the cursor.
        if status == 400 and params is not None and "cursor" in params:
            raise CursorRejected("asset-sim refused the cursor")
        raise UpstreamInvalid(f"asset-sim answered {status}")

    async def asset_type(self, scope: persistence.AssetScope) -> str | None:
        try:
            body = await self._get(scope, "")
        except AssetMissing:
            return None
        found = body.get("asset_type")
        if body.get("asset_id") != scope.asset_id or not isinstance(found, str) or not ASSET_TYPE.fullmatch(found):
            raise UpstreamInvalid("asset-sim answered an asset that is not the run's")
        return found

    async def status(self, scope: persistence.AssetScope) -> dict[str, Any]:
        return await self._get(scope, "/status")

    async def alerts(self, scope: persistence.AssetScope, *, limit: int, cursor: str | None) -> dict[str, Any]:
        params = {"start_at": rfc3339(scope.start_at), "end_at": rfc3339(scope.end_at), "limit": str(limit)}
        if cursor is not None:
            params["cursor"] = cursor
        return await self._get(scope, "/alerts", params)

    async def aclose(self) -> None:
        await self._http.aclose()

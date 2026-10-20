"""asset-sim: the synthetic asset and alert API (T16; SA:78, SA:555, BS:405; Plan M rulings 4-6, 8-10).

Trusts only mcp-read's workload token (aud `asset-sim`, azp `ops-mcp-read`, an access token's `typ`) and the context
mcp-read forwards from `asset_scope`: `X-Ops-Tenant-Id` (the run's tenant UUID) and `X-Ops-As-Of` (the database
instant it answers at). It applies its own tenant filter: an asset of another tenant and an unknown asset get the same
404 (no existence oracle, ruling 8). It never sees an invocation handle (BS:364), writes nothing, and keeps no clock
of its own: every answer is a function of the data files, the forwarded tenant and `as_of` (`ops_asset_sim.data`).
A token for another audience or client is 403 and any other refused token 401 with `WWW-Authenticate: Bearer`
(incident-sim's mapping); a safe error never echoes the request. Fault routes exist only under the test profile (R098).
"""

# No `from __future__ import annotations`: FastAPI resolves dependency annotations at import time (Plan D review).
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Final, Protocol
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from ops_core import settings
from ops_core.contracts import ErrorCode, SafeError
from ops_core.settings import Profile
from ops_core.testing.faults import FaultKind, Faults
from ops_core.tokens import Principal, TokenRejected, TokenVerifier, WrongAudience, bearer_token
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ops_asset_sim import data

AUDIENCE: Final = "asset-sim"  # the realm's audience mapper on ops-mcp-read (realm-ops-dev.json)
CALLER: Final = "ops-mcp-read"  # the one workload client asset-sim serves (SA:555)
MAX_LIMIT: Final = 100  # schemas/tools/get_recent_alerts.input.schema.json
# The faults this service consumes (ruling 6): the state `unavailable`, a transient 503, a malformed body and a slow
# answer. Any other kind is refused at the arming route, so nothing can be armed that is never taken.
FAULTS: Final = frozenset(
    {
        FaultKind.ASSET_UNAVAILABLE,
        FaultKind.DROP_BEFORE_COMMIT,
        FaultKind.MALFORMED_RESPONSE,
        FaultKind.TIMEOUT_BEFORE_ACCEPT,
    }
)


class Verifier(Protocol):
    """The token-verifier subset asset-sim needs, so unit tests can stub it."""

    @property
    def ready(self) -> bool: ...

    async def load_keys(self) -> None: ...

    async def verify_async(self, token: str) -> Principal: ...


class FaultRequest(BaseModel):
    """How many occurrences of a fault to arm, and how long a slow answer holds (test profile only)."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    count: int = Field(ge=1, le=100)
    seconds: int | None = Field(default=None, ge=1, le=120)


class Unauthenticated(Exception):
    """No acceptable token: 401."""


class WrongService(Exception):
    """A genuine token for another audience or client: 403, not 401 (T10 DoD 2's mapping)."""


class BadRequest(Exception):
    """The forwarded context or a query parameter is missing or malformed: 400, never echoed."""


def safe_error(status: int, code: ErrorCode, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    """A BUILD_SPEC §7 safe error with a fresh request id."""
    body = SafeError(code=code, message=message, retryable=status in (429, 503), request_id=uuid4())
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"), headers=headers)


def forwarded_tenant(request: Request) -> UUID:
    """`X-Ops-Tenant-Id`, the run's tenant mcp-read read from `asset_scope`.

    Raises:
        BadRequest: absent or not a UUID.
    """
    try:
        return UUID(request.headers["x-ops-tenant-id"])
    except (KeyError, ValueError) as exc:
        raise BadRequest from exc


def forwarded_instant(request: Request, name: str) -> datetime:
    """A forwarded UTC instant: the `X-Ops-As-Of` header or a query parameter.

    Raises:
        BadRequest: absent or not a UTC instant.
    """
    raw = request.headers.get(name) if name.startswith("x-") else request.query_params.get(name)
    if raw is None:
        raise BadRequest
    try:
        return data.instant(raw)
    except ValueError as exc:
        raise BadRequest from exc


def create_app(verifier: Verifier, *, catalog: data.Catalog, profile: Profile = Profile.DEV) -> FastAPI:
    """Wire the routes over a loaded catalog. The fault routes exist only under the test profile (R098): `Faults`
    refuses to exist anywhere else."""
    faults = Faults(profile) if profile is Profile.TEST else None

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if not verifier.ready:
            await verifier.load_keys()
        yield

    app = FastAPI(title="asset-sim", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    async def caller(request: Request) -> Principal:
        try:
            return await verifier.verify_async(bearer_token(request.headers.get("authorization")))
        except WrongAudience as exc:  # before TokenRejected, which it subclasses
            raise WrongService from exc
        except TokenRejected as exc:
            raise Unauthenticated from exc

    @app.exception_handler(Unauthenticated)
    async def _unauthenticated(_: Request, __: Unauthenticated) -> Response:
        return safe_error(
            401, ErrorCode.UNAUTHENTICATED, "a valid workload token is required", {"WWW-Authenticate": "Bearer"}
        )

    @app.exception_handler(WrongService)
    async def _wrong_service(_: Request, __: WrongService) -> Response:
        return safe_error(403, ErrorCode.FORBIDDEN, "token is not for this service")

    @app.exception_handler(BadRequest)
    async def _bad_request(_: Request, __: BadRequest) -> Response:
        return safe_error(400, ErrorCode.INVALID_INPUT, "request is not valid")

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, __: RequestValidationError) -> Response:
        return safe_error(400, ErrorCode.INVALID_INPUT, "request is not valid")  # never FastAPI's echoing body

    def not_found() -> JSONResponse:
        return safe_error(404, ErrorCode.NOT_FOUND, "no such asset")  # unknown and another tenant's alike

    async def fault(malformed: dict[str, object]) -> Response | None:
        """The armed fault that answers instead of the data, if any (test profile only)."""
        if faults is None:
            return None
        if faults.take(FaultKind.TIMEOUT_BEFORE_ACCEPT):
            await asyncio.sleep(faults.seconds(FaultKind.TIMEOUT_BEFORE_ACCEPT))
            return safe_error(503, ErrorCode.UNAVAILABLE, "asset-sim answered too late (fault)")
        if faults.take(FaultKind.DROP_BEFORE_COMMIT):
            return safe_error(503, ErrorCode.UNAVAILABLE, "asset-sim unavailable (fault)")
        if faults.take(FaultKind.MALFORMED_RESPONSE):
            return JSONResponse(malformed)
        return None

    def lookup(request: Request, asset_id: str) -> data.Asset | None:
        tenant = forwarded_tenant(request)
        return catalog.asset(tenant, asset_id) if data.ASSET_ID.fullmatch(asset_id) else None

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "live"}

    @app.get("/health/ready")
    async def ready() -> Response:
        """Ready once the realm's keys are loaded; the catalog is loaded before the app exists."""
        if not verifier.ready:
            return safe_error(503, ErrorCode.UNAVAILABLE, "signing keys not loaded")
        return JSONResponse({"status": "ready"})

    @app.get("/assets/{asset_id}")
    async def get_asset(asset_id: str, request: Request, _: Annotated[Principal, Depends(caller)]) -> Response:
        """The asset's type, which mcp-read passes to the procedure search (ruling 12)."""
        asset = lookup(request, asset_id)
        answered = await fault({"asset_id": asset_id, "asset_type": 7})
        if answered is not None:
            return answered
        if asset is None:
            return not_found()
        return JSONResponse({"asset_id": asset.asset_id, "asset_type": asset.asset_type})

    @app.get("/assets/{asset_id}/status")
    async def get_status(asset_id: str, request: Request, _: Annotated[Principal, Depends(caller)]) -> Response:
        """`get_asset_status`'s data as of the forwarded instant."""
        asset = lookup(request, asset_id)
        as_of = forwarded_instant(request, "x-ops-as-of")
        answered = await fault({"asset_id": asset_id, "state": "on fire"})
        if answered is not None:
            return answered
        if asset is None:
            return not_found()
        doc = data.status(catalog, asset, as_of)
        if faults is not None and faults.take(FaultKind.ASSET_UNAVAILABLE):
            doc["state"] = "unavailable"  # the contract's third state, reachable only through this hook
        return JSONResponse(doc)

    @app.get("/assets/{asset_id}/alerts")
    async def get_alerts(asset_id: str, request: Request, _: Annotated[Principal, Depends(caller)]) -> Response:
        """`get_recent_alerts`'s data: the forwarded interval, at or before the forwarded instant, one page."""
        asset = lookup(request, asset_id)
        as_of = forwarded_instant(request, "x-ops-as-of")
        start_at, end_at = forwarded_instant(request, "start_at"), forwarded_instant(request, "end_at")
        cursor = request.query_params.get("cursor")
        try:
            limit = int(request.query_params["limit"])
        except (KeyError, ValueError) as exc:
            raise BadRequest from exc
        if not 1 <= limit <= MAX_LIMIT or start_at >= end_at or (cursor is not None and not 1 <= len(cursor) <= 200):
            raise BadRequest
        answered = await fault({"asset_id": asset_id, "alerts": "none"})
        if answered is not None:
            return answered
        if asset is None:
            return not_found()
        try:
            doc = data.alerts_page(
                catalog, asset, start_at=start_at, end_at=end_at, as_of=as_of, limit=limit, cursor=cursor
            )
        except data.CursorRefused:
            return safe_error(400, ErrorCode.INVALID_INPUT, "cursor does not belong to this request")
        return JSONResponse(doc)

    if faults is not None:
        armable = faults  # a local the closure can rely on: `faults` is narrowed to non-None only here

        @app.post("/internal/faults/{kind}")
        async def arm_fault(kind: str, request: Request, _: Annotated[Principal, Depends(caller)]) -> Response:
            """Arm one of this service's faults for the next `count` requests (the route exists under PROFILE=test
            only, and only mcp-read's token may call it)."""
            try:
                chosen = FaultKind(kind)
                body = FaultRequest.model_validate_json((await request.body()).decode("utf-8"))
            except (ValueError, ValidationError, UnicodeDecodeError):
                return safe_error(422, ErrorCode.INVALID_INPUT, "body is not a well-formed fault request")
            if chosen not in FAULTS:
                return safe_error(422, ErrorCode.INVALID_INPUT, "asset-sim does not consume this fault")
            try:
                armable.arm(chosen, body.count, seconds=body.seconds)
            except ValueError:  # `seconds` for a kind without a duration
                return safe_error(422, ErrorCode.INVALID_INPUT, "seconds applies to timeout_before_accept only")
            return JSONResponse({"armed": armable.armed()})

    return app


def verifier_for(kc: settings.Keycloak) -> TokenVerifier:
    """asset-sim's token checks (ruling 6): the realm's issuer and keys, the audience `asset-sim`, `ops-mcp-read` as
    the only `azp`, and an access token's `typ`. `production_app` builds its verifier here, and so do the tests."""
    return TokenVerifier(
        issuer=kc.issuer,
        audience=AUDIENCE,
        allowed_azp=frozenset({CALLER}),
        jwks_url=kc.jwks_url,
        token_type="Bearer",
    )


def production_app() -> FastAPI:
    """The app wired from the environment, as `python -m ops_asset_sim` runs it; the data files are read here, once."""
    return create_app(verifier_for(settings.keycloak()), catalog=data.load(), profile=settings.profile())

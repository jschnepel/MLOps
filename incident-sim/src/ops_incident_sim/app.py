"""incident-sim: the synthetic destination (BUILD_SPEC §14). Trusts only mcp-write's workload token (aud `incident-sim`,
azp `ops-mcp-write`, SA:262/270); recomputes the hash over the received bytes before touching the key table (SA:268);
answers with the key's own view (keys.document). A 401 carries a plain safe error and never an action id (SA:357)."""

# No `from __future__ import annotations`: FastAPI resolves dependency annotations at import time (Plan D review).
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal, Protocol
from uuid import UUID, uuid4

import psycopg
from fastapi import Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from ops_core import persistence, settings
from ops_core.canonical import CanonicalizationError, parse_json_strict, sha256_hex
from ops_core.contracts import ErrorCode, SafeError, Sha256
from ops_core.settings import Profile
from ops_core.testing.faults import FaultKind, Faults
from ops_core.tokens import Principal, TokenRejected, TokenVerifier, WrongAudience, bearer_token
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ops_incident_sim import keys


class Verifier(Protocol):
    @property
    def ready(self) -> bool: ...

    async def load_keys(self) -> None: ...

    async def verify_async(self, token: str) -> Principal: ...


class Store(Protocol):
    async def commit(self, action_id: UUID, payload_sha256: str, payload: dict[str, Any]) -> keys.KeyRow: ...

    async def lookup(self, action_id: UUID) -> keys.KeyRow | None: ...

    async def abort(self, *, action_id: UUID, payload_sha256: str, reason: str) -> keys.KeyRow:
        """Write a permanent ABORTED key for an action never committed; an existing key answers instead."""
        ...

    async def reject(self, *, action_id: UUID, payload_sha256: str, reason: str) -> keys.KeyRow:
        """Write a permanent REJECTED key for a refused request; an existing key answers instead."""
        ...


class DbStore:
    def __init__(self, conn: persistence.Conn) -> None:
        self.session = persistence.Session(conn)  # ruling 24: one unit of work at a time, each a real transaction

    async def commit(self, action_id: UUID, payload_sha256: str, payload: dict[str, Any]) -> keys.KeyRow:
        async with self.session.unit() as conn:
            return await keys.commit(conn, action_id=action_id, payload_sha256=payload_sha256, payload=payload)

    async def lookup(self, action_id: UUID) -> keys.KeyRow | None:
        async with self.session.unit() as conn:
            return await keys.lookup(conn, action_id)

    async def abort(self, *, action_id: UUID, payload_sha256: str, reason: str) -> keys.KeyRow:
        """Record the abort tombstone in its own unit of work (keys.abort decides what stands)."""
        async with self.session.unit() as conn:
            return await keys.abort(conn, action_id=action_id, payload_sha256=payload_sha256, reason=reason)

    async def reject(self, *, action_id: UUID, payload_sha256: str, reason: str) -> keys.KeyRow:
        """Record the rejection tombstone in its own unit of work (keys.reject decides what stands)."""
        async with self.session.unit() as conn:
            return await keys.reject(conn, action_id=action_id, payload_sha256=payload_sha256, reason=reason)

    async def ping(self) -> None:
        await self.session.ping()


class IncidentRequest(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    action_id: UUID
    payload_sha256: Sha256
    payload_canonical: str = Field(min_length=2)


class AbortRequest(BaseModel):
    """The executor's abort: the grant's hash (SA:266) and why the action will never be sent."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    payload_sha256: Sha256
    reason: Literal["cancelled_before_send", "expired", "deadline"]


class FaultRequest(BaseModel):
    """How many occurrences of a fault to arm (test profile only)."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    count: int = Field(ge=1, le=100)


def safe_error(status: int, code: ErrorCode, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    body = SafeError(code=code, message=message, retryable=status == 503, request_id=uuid4())
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"), headers=headers)


class Unauthenticated(Exception):
    pass


class WrongService(Exception):
    """The token is genuine but another server's (aud or azp): 403, not 401 (T10 DoD 2)."""


def create_app(
    verifier: Verifier,
    *,
    store: Store | None = None,
    connect: Callable[[], Awaitable[persistence.Conn]] | None = None,
    profile: Profile = Profile.DEV,
    faults: Faults | None = None,
) -> FastAPI:
    """Wire the app; `store` injects an in-memory table for unit tests, `connect` the real database at runtime.

    The fault routes exist only under the test profile (R098); a `faults` object in any other profile is refused.
    """
    if profile is Profile.TEST:
        faults = faults or Faults(profile)
    elif faults is not None:
        raise ValueError("fault hooks exist only in the test profile")
    # No persistence.assert_clock_profile here: incident-sim's database has no `app` schema, so nothing to assert.

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if store is not None:
            app.state.store = store
        else:
            assert connect is not None
            app.state.store = DbStore(await connect())
        if not verifier.ready:
            await verifier.load_keys()
        yield

    app = FastAPI(title="incident-sim", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

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

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, __: RequestValidationError) -> Response:
        # Ruling 20: a generic 422, never FastAPI's default body that echoes the offending input.
        return safe_error(422, ErrorCode.INVALID_INPUT, "request is not valid")

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "live"}

    @app.get("/health/ready")
    async def ready(request: Request) -> Response:
        st: Store = request.app.state.store
        if isinstance(st, DbStore):
            try:
                await st.ping()
            except (psycopg.Error, OSError):  # readiness reports a database failure as not ready
                return safe_error(503, ErrorCode.UNAVAILABLE, "database not reachable")
        return JSONResponse({"status": "ready"})

    @app.post("/internal/incidents")
    async def post_incident(request: Request, _: Annotated[Principal, Depends(caller)]) -> Response:
        raw = await request.body()
        try:
            text = raw.decode("utf-8")
            parse_json_strict(text)  # duplicate keys, floats and NaN in the envelope are refused here
            body = IncidentRequest.model_validate_json(text)  # JSON mode: strict models parse UUID text
        except (UnicodeDecodeError, CanonicalizationError, ValidationError, ValueError):
            return safe_error(422, ErrorCode.INVALID_INPUT, "body is not a well-formed incident request")
        # From here the envelope is well formed, so every refusal is a permanent REJECTED key (SA:261) and a lost
        # response is recoverable by lookup. keys.document answers 409 if the key committed under another hash.
        try:
            payload = parse_json_strict(body.payload_canonical)
        except (CanonicalizationError, ValueError):
            payload = None
        reason: str | None = None
        if not isinstance(payload, dict) or not payload:
            reason = "invalid_payload"
        # The hash is recomputed over the bytes exactly as received (SA:268), never over a re-serialisation.
        elif sha256_hex(body.payload_canonical.encode("utf-8")) != body.payload_sha256:
            reason = "hash_mismatch"
        elif faults is not None and faults.take(FaultKind.REJECT_NEXT):
            reason = "policy"
        st: Store = request.app.state.store
        try:
            if reason is not None:
                row = await st.reject(action_id=body.action_id, payload_sha256=body.payload_sha256, reason=reason)
                status, doc = keys.document(row, presented_sha256=body.payload_sha256)
                return JSONResponse(status_code=status, content=doc)
            if faults is not None and faults.take(FaultKind.DROP_BEFORE_COMMIT):
                return safe_error(503, ErrorCode.UNAVAILABLE, "destination unavailable (fault)")
            assert isinstance(payload, dict)  # reason is None only for a non-empty object; this narrows the type
            row = await st.commit(body.action_id, body.payload_sha256, payload)
            if faults is not None and faults.take(FaultKind.LOSE_AFTER_COMMIT):
                return safe_error(503, ErrorCode.UNAVAILABLE, "response lost after commit (fault)")
        except psycopg.Error:
            return safe_error(503, ErrorCode.UNAVAILABLE, "destination database unavailable")
        status, doc = keys.document(row, presented_sha256=body.payload_sha256)
        return JSONResponse(status_code=status, content=doc)

    @app.post("/internal/actions/{action_id}/abort")
    async def abort_action(action_id: UUID, request: Request, _: Annotated[Principal, Depends(caller)]) -> Response:
        """Abort an uncommitted action permanently, or answer with the key that already stands (AM-13)."""
        raw = await request.body()
        try:
            body = AbortRequest.model_validate_json(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValidationError, ValueError):
            return safe_error(422, ErrorCode.INVALID_INPUT, "body is not a well-formed abort request")
        st: Store = request.app.state.store
        try:
            row = await st.abort(action_id=action_id, payload_sha256=body.payload_sha256, reason=body.reason)
        except psycopg.Error:
            return safe_error(503, ErrorCode.UNAVAILABLE, "destination database unavailable")
        status, doc = keys.document(row, presented_sha256=body.payload_sha256)
        return JSONResponse(status_code=status, content=doc)

    if faults is not None:
        armable = faults  # a local the closure can rely on: `faults` is narrowed to non-None only here

        @app.post("/internal/faults/{kind}")
        async def arm_fault(kind: FaultKind, request: Request, _: Annotated[Principal, Depends(caller)]) -> Response:
            """Arm a test-profile fault for the next `count` requests (the route exists only under PROFILE=test)."""
            try:
                body = FaultRequest.model_validate_json((await request.body()).decode("utf-8"))
            except (UnicodeDecodeError, ValidationError, ValueError):
                return safe_error(422, ErrorCode.INVALID_INPUT, "body is not a well-formed fault request")
            armable.arm(kind, body.count)
            return JSONResponse({"armed": armable.armed()})

    @app.get("/internal/actions/{action_id}")
    async def get_action(action_id: UUID, request: Request, _: Annotated[Principal, Depends(caller)]) -> Response:
        st: Store = request.app.state.store
        try:
            row = await st.lookup(action_id)
        except psycopg.Error:
            return safe_error(503, ErrorCode.UNAVAILABLE, "destination database unavailable")
        if row is None:
            return safe_error(404, ErrorCode.NOT_FOUND, "no such action")
        status, doc = keys.document(row, presented_sha256=row.payload_sha256)
        return JSONResponse(status_code=status, content=doc)

    return app


def production_app() -> FastAPI:
    kc = settings.keycloak()
    verifier = TokenVerifier(
        issuer=kc.issuer, audience="incident-sim", allowed_azp=frozenset({"ops-mcp-write"}), jwks_url=kc.jwks_url
    )
    return create_app(
        verifier, connect=lambda: persistence.connect(settings.incident_postgres()), profile=settings.profile()
    )

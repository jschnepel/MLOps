"""incident-sim: the synthetic destination (BUILD_SPEC §14). Trusts only mcp-write's workload token (aud `incident-sim`,
azp `ops-mcp-write`, SA:262/270); recomputes the hash over the received bytes before touching the key table (SA:268);
answers with the key's own view (keys.document). A 401 carries a plain safe error and never an action id (SA:357)."""

# No `from __future__ import annotations`: FastAPI resolves dependency annotations at import time (Plan D review).
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any, Protocol
from uuid import UUID, uuid4

import psycopg
from fastapi import Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from ops_core import persistence, settings
from ops_core.canonical import CanonicalizationError, parse_json_strict, sha256_hex
from ops_core.contracts import ErrorCode, SafeError, Sha256
from ops_core.tokens import Principal, TokenRejected, TokenVerifier, bearer_token
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


class DbStore:
    def __init__(self, conn: persistence.Conn) -> None:
        self.session = persistence.Session(conn)  # ruling 24: one unit of work at a time, each a real transaction

    async def commit(self, action_id: UUID, payload_sha256: str, payload: dict[str, Any]) -> keys.KeyRow:
        async with self.session.unit() as conn:
            return await keys.commit(conn, action_id=action_id, payload_sha256=payload_sha256, payload=payload)

    async def lookup(self, action_id: UUID) -> keys.KeyRow | None:
        async with self.session.unit() as conn:
            return await keys.lookup(conn, action_id)


class IncidentRequest(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    action_id: UUID
    payload_sha256: Sha256
    payload_canonical: str = Field(min_length=2)


def safe_error(status: int, code: ErrorCode, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    body = SafeError(code=code, message=message, retryable=status == 503, request_id=uuid4())
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"), headers=headers)


class Unauthenticated(Exception):
    pass


def create_app(
    verifier: Verifier, *, store: Store | None = None, connect: Callable[[], Awaitable[persistence.Conn]] | None = None
) -> FastAPI:
    """Wire the app; `store` injects an in-memory table for unit tests, `connect` the real database at runtime."""

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
        except TokenRejected as exc:
            raise Unauthenticated from exc

    @app.exception_handler(Unauthenticated)
    async def _unauthenticated(_: Request, __: Unauthenticated) -> Response:
        return safe_error(
            401, ErrorCode.UNAUTHENTICATED, "a valid workload token is required", {"WWW-Authenticate": "Bearer"}
        )

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
                await st.session.ping()
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
            payload = parse_json_strict(body.payload_canonical)
        except (UnicodeDecodeError, CanonicalizationError, ValidationError, ValueError):
            return safe_error(422, ErrorCode.INVALID_INPUT, "body is not a well-formed incident request")
        if not isinstance(payload, dict) or not payload:
            return safe_error(422, ErrorCode.INVALID_INPUT, "payload_canonical is not a JSON object")
        # The hash is recomputed over the bytes exactly as received (SA:268), never over a re-serialisation.
        if sha256_hex(body.payload_canonical.encode("utf-8")) != body.payload_sha256:
            return safe_error(422, ErrorCode.INVALID_INPUT, "payload hash does not match the received payload")
        st: Store = request.app.state.store
        try:
            row = await st.commit(body.action_id, body.payload_sha256, payload)
        except psycopg.Error:
            return safe_error(503, ErrorCode.UNAVAILABLE, "destination database unavailable")
        status, doc = keys.document(row, presented_sha256=body.payload_sha256)
        return JSONResponse(status_code=status, content=doc)

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
    return create_app(verifier, connect=lambda: persistence.connect(settings.incident_postgres()))

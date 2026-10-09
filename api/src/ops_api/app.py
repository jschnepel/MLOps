"""api: admission, run snapshots, the proposal document and the independent decision (BUILD_SPEC §7, §9, §12).

Identity is the verified persona token's `sub` resolved against seeded memberships (never a display name, BUILD_SPEC
§9); the tenant and roles come from the membership, never from the request. Bodies are parsed with
`ops_core.contracts.load`, so a duplicate key or an authority field is a 422 before any handler logic runs. Browser
sessions, CSRF and Idempotency-Key are declared debt (T11/T12).
"""

# No `from __future__ import annotations` here: FastAPI resolves dependency annotations at import time, and a
# string annotation naming a local alias becomes a query parameter (measured in the round-1 review).
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Any, Protocol
from uuid import UUID, uuid4

import psycopg
from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from ops_core import persistence, settings
from ops_core.contracts import DecisionRequest, DuplicateKey, ErrorCode, MessageKind, MessageRequest, SafeError, load
from ops_core.outcomes import EventRuleViolation
from ops_core.settings import Role
from ops_core.states import IllegalTransition
from ops_core.tokens import Principal, TokenRejected, TokenVerifier
from pydantic import ValidationError

from ops_api import store as st

log = logging.getLogger("ops_api")
bearer = HTTPBearer(auto_error=False)  # the 401 body is ours (SafeError), not the SDK's


class ApiError(Exception):
    """A refusal carrying its HTTP status and SafeError code, rendered by the exception handler."""

    def __init__(self, status: int, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def safe(status: int, code: ErrorCode, message: str) -> JSONResponse:
    """Build a SafeError response (a 401 also names the Bearer scheme)."""
    body = SafeError(code=code, message=message, retryable=status == 503, request_id=uuid4())
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else {}
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"), headers=headers)


def stamp(value: datetime) -> str:
    """Spell a timestamp as UTC `...Z` with whole seconds (ruling 10)."""
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Verifier(Protocol):  # the unit tests stub it
    """What the application needs from a token verifier."""

    @property
    def ready(self) -> bool:
        """Whether the signing keys are loaded."""
        ...

    async def load_keys(self) -> None:
        """Fetch the signing keys."""
        ...

    async def verify_async(self, token: str) -> Principal:
        """Verify a bearer token or raise TokenRejected."""
        ...


class Identity:
    """The caller: the verified subject plus the tenant and roles its membership grants."""

    def __init__(self, principal: Principal, membership: st.Membership) -> None:
        self.subject = UUID(principal.subject)
        self.username = str(principal.claims.get("preferred_username", ""))
        self.tenant_id = membership.tenant_id
        self.roles = membership.roles

    def require(self, role: str) -> None:
        """Refuse with 403 unless the caller holds the role."""
        if role not in self.roles:
            raise ApiError(403, ErrorCode.FORBIDDEN, f"the {role} role is required")


def create_app(verifier: Verifier, store_factory: Callable[[], st.Store | Awaitable[st.Store]]) -> FastAPI:
    """Build the application around a verifier and a store factory (the lifespan installs the store)."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        made = store_factory()
        app.state.store = await made if isinstance(made, Awaitable) else made
        try:
            if isinstance(app.state.store, st.DbStore):
                await persistence.assert_clock_profile(app.state.store.session.conn, settings.profile())
            if not verifier.ready:
                await verifier.load_keys()
            yield
        finally:
            if isinstance(app.state.store, st.DbStore):
                await app.state.store.session.conn.close()

    app = FastAPI(title="ops-api", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    issuer = settings.keycloak().issuer

    async def identity(
        request: Request, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
    ) -> Identity:
        if creds is None:
            raise ApiError(401, ErrorCode.UNAUTHENTICATED, "a bearer token is required")
        try:
            principal = await verifier.verify_async(creds.credentials)
        except TokenRejected as exc:
            raise ApiError(401, ErrorCode.UNAUTHENTICATED, "token rejected") from exc
        try:
            subject = UUID(principal.subject)
        except ValueError as exc:
            raise ApiError(401, ErrorCode.UNAUTHENTICATED, "token subject is not an identity") from exc
        membership = await request.app.state.store.membership(issuer, subject)
        if membership is None:
            raise ApiError(403, ErrorCode.FORBIDDEN, "no active membership")
        return Identity(principal, membership)

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> Response:
        return safe(exc.status, exc.code, exc.message)

    @app.exception_handler(persistence.AuthorityViolation)
    async def _authority(_: Request, exc: persistence.AuthorityViolation) -> Response:
        log.error("deployment error: %s", exc)  # the API is connected as a role a function does not accept
        return safe(503, ErrorCode.UNAVAILABLE, "service misconfigured")

    @app.exception_handler(st.Internal)
    @app.exception_handler(persistence.PersistenceError)
    @app.exception_handler(IllegalTransition)
    @app.exception_handler(EventRuleViolation)
    async def _server_defect(_: Request, exc: Exception) -> Response:
        # Messages carry no handle or secret. FastAPI picks the most specific class, so AuthorityViolation keeps
        # its own handler.
        log.error("service error: %r", exc)
        return safe(503, ErrorCode.UNAVAILABLE, "service error")

    @app.exception_handler(psycopg.Error)
    async def _database(_: Request, __: psycopg.Error) -> Response:
        return safe(503, ErrorCode.UNAVAILABLE, "database unavailable")

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, __: RequestValidationError) -> Response:
        return safe(422, ErrorCode.INVALID_INPUT, "request is not valid")

    async def body(request: Request, model: type[Any]) -> Any:
        try:
            return load(model, (await request.body()).decode("utf-8"))
        except (UnicodeDecodeError, DuplicateKey, ValidationError, ValueError) as exc:
            raise ApiError(422, ErrorCode.INVALID_INPUT, "request body is not valid") from exc

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "live"}

    @app.get("/health/ready")
    async def ready(request: Request) -> Response:
        store: st.Store = request.app.state.store
        if isinstance(store, st.DbStore):
            try:
                await store.session.ping()
            except (psycopg.Error, OSError):  # readiness reports a database failure as not ready
                return safe(503, ErrorCode.UNAVAILABLE, "database not reachable")
        return JSONResponse({"status": "ready"})

    @app.get("/api/v1/me")
    async def me(who: Annotated[Identity, Depends(identity)]) -> dict[str, Any]:
        return {
            "subject": str(who.subject),
            "tenant_id": str(who.tenant_id),
            "roles": sorted(who.roles),
            "username": who.username,
        }

    @app.post("/api/v1/conversations", status_code=201)
    async def create_conversation(request: Request, who: Annotated[Identity, Depends(identity)]) -> dict[str, str]:
        cid = await request.app.state.store.create_conversation(who.tenant_id, who.subject)
        return {"conversation_id": str(cid)}

    @app.post("/api/v1/conversations/{conversation_id}/messages", status_code=202)
    async def post_message(
        conversation_id: UUID, request: Request, who: Annotated[Identity, Depends(identity)]
    ) -> dict[str, Any]:
        who.require("requester")
        message: MessageRequest = await body(request, MessageRequest)
        # T08 routes only `investigate` with a resolvable asset and interval; the admission router (T12) adds the rest.
        if (
            message.kind is not MessageKind.INVESTIGATE
            or message.context is None
            or (message.context.asset_id is None or message.context.hours is None)
        ):
            raise ApiError(
                422, ErrorCode.INVALID_INPUT, "only an investigate request with asset_id and hours is routed"
            )
        start_at, end_at = st.resolve_interval(message.context.hours, datetime.now(UTC))
        try:
            accepted = await request.app.state.store.admit(
                tenant_id=who.tenant_id,
                conversation_id=conversation_id,
                requester=who.subject,
                request=message,
                start_at=start_at,
                end_at=end_at,
            )
        except st.NotFound as exc:
            raise ApiError(404, ErrorCode.NOT_FOUND, "no such conversation or superseded run") from exc
        except st.Conflict as exc:
            raise ApiError(409, ErrorCode(exc.code), "the conversation already has an active run") from exc
        return {
            "conversation_id": str(accepted.conversation_id),
            "message_id": str(accepted.message_id),
            "run_id": str(accepted.run_id),
            "status": accepted.status,
            "state_version": accepted.state_version,
            "status_url": f"/api/v1/runs/{accepted.run_id}",
            "events_url": f"/api/v1/runs/{accepted.run_id}/events",
        }

    @app.get("/api/v1/runs/{run_id}")
    async def get_run(run_id: UUID, request: Request, who: Annotated[Identity, Depends(identity)]) -> dict[str, Any]:
        row = await request.app.state.store.run(who.tenant_id, run_id)
        if row is None:
            raise ApiError(404, ErrorCode.NOT_FOUND, "no such run")
        return {
            "run_id": str(row["run_id"]),
            "conversation_id": str(row["conversation_id"]),
            "status": row["state"],
            "state_version": row["state_version"],
            "active_proposal_id": str(row["active_proposal_id"]) if row["active_proposal_id"] else None,
            "asset_id": row["asset_id"],
            "start_at": stamp(row["start_at"]),
            "end_at": stamp(row["end_at"]),
            "created_at": stamp(row["created_at"]),
        }

    @app.get("/api/v1/proposals/{proposal_id}")
    async def get_proposal(
        proposal_id: UUID, request: Request, who: Annotated[Identity, Depends(identity)]
    ) -> dict[str, Any]:
        row = await request.app.state.store.proposal(who.tenant_id, proposal_id)
        if row is None:
            raise ApiError(404, ErrorCode.NOT_FOUND, "no such proposal")
        return {
            "proposal_id": str(row["proposal_id"]),
            "run_id": str(row["run_id"]),
            "revision": row["revision"],
            "payload": row["payload"],
            "payload_sha256": row["payload_sha256"],
            "authored_by": [str(a) for a in row["authored_by"]],
            "expires_at": stamp(row["expires_at"]),
        }

    @app.post("/api/v1/proposals/{proposal_id}/decisions")
    async def post_decision(
        proposal_id: UUID, request: Request, who: Annotated[Identity, Depends(identity)]
    ) -> dict[str, Any]:
        decision: DecisionRequest = await body(request, DecisionRequest)
        store: st.Store = request.app.state.store
        row = await store.proposal(who.tenant_id, proposal_id)
        if row is None:
            raise ApiError(404, ErrorCode.NOT_FOUND, "no such proposal")
        try:
            st.check_reviewer(
                st.Membership(who.tenant_id, who.roles),
                requester=row["requester"],
                authored_by=list(row["authored_by"]),
                reviewer=who.subject,
            )
            decided = await store.decide(
                tenant_id=who.tenant_id, proposal_id=proposal_id, reviewer=who.subject, request=decision
            )
        except st.Forbidden as exc:
            raise ApiError(403, ErrorCode.FORBIDDEN, "an independent current reviewer is required") from exc
        except st.NotFound as exc:
            raise ApiError(404, ErrorCode.NOT_FOUND, "no such proposal") from exc
        except st.Conflict as exc:
            raise ApiError(409, ErrorCode(exc.code), "the proposal is not the active, undecided revision") from exc
        return {
            "proposal_id": str(decided.proposal_id),
            "run_id": str(decided.run_id),
            "decision": decided.decision,
            "status": decided.status,
            "state_version": decided.state_version,
        }

    @app.get("/api/v1/runs/{run_id}/events")
    async def get_events(
        run_id: UUID,
        request: Request,
        who: Annotated[Identity, Depends(identity)],
        after: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> dict[str, Any]:
        store: st.Store = request.app.state.store
        if await store.run(who.tenant_id, run_id) is None:
            raise ApiError(404, ErrorCode.NOT_FOUND, "no such run")
        rows = await store.events(who.tenant_id, run_id, after=after, limit=limit)
        return {"events": [{**r, "occurred_at": stamp(r["occurred_at"])} if "occurred_at" in r else r for r in rows]}

    return app


def production_app() -> FastAPI:
    """Build the application against Keycloak and PostgreSQL from the environment and secret files."""
    kc = settings.keycloak()
    verifier = TokenVerifier(
        issuer=kc.issuer,
        audience=settings.env("OPS_API_AUDIENCE", "ops-api"),
        allowed_azp=frozenset({"ops-dev-direct"}),
        jwks_url=kc.jwks_url,
    )

    async def make_store() -> st.Store:
        return st.DbStore(await persistence.connect(settings.app_postgres(Role.API)))

    return create_app(verifier, make_store)

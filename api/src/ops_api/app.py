"""api: admission, run snapshots, the proposal document and the independent decision (BUILD_SPEC §7, §9, §12).

Identity is the verified persona token's `sub` resolved against seeded memberships (never a display name, BUILD_SPEC
§9); the tenant and roles come from the membership, never from the request. Bodies are parsed with
`ops_core.contracts.load`, so a duplicate key or an authority field is a 422 before any handler logic runs.
Browser sessions (T11): server-side rows, the cookie path beside the bearer path, CSRF and origin checks on browser
mutations, the admin-API enabled check on decision-class mutations, back-channel logout. Plan G (T12): every response
carries a server-made request id, every refusal is the SafeError, and no body over the configured limit reaches a
route.
"""

# No `from __future__ import annotations` here: FastAPI resolves dependency annotations at import time, and a
# string annotation naming a local alias becomes a query parameter (measured in the round-1 review).
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Protocol
from uuid import UUID

import httpx2
import psycopg
from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from ops_core import keycloak_admin, persistence, settings
from ops_core.contracts import DecisionRequest, DuplicateKey, ErrorCode, MessageKind, MessageRequest, load
from ops_core.keycloak_admin import AdminUnavailable
from ops_core.outcomes import EventRuleViolation
from ops_core.settings import AdmissionSettings, Role
from ops_core.states import IllegalTransition
from ops_core.tokens import Principal, SigningKeysUnavailable, TokenRejected, TokenVerifier
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from ops_api import auth as au
from ops_api import limits
from ops_api import store as st
from ops_api.auth import AuthDeps, ExchangeRefused, ExchangeUnavailable

log = logging.getLogger("ops_api")
ERROR_CODE = re.compile(r"[a-z_]{1,64}")  # an OAuth error code, matched whole below
bearer = HTTPBearer(auto_error=False)  # the 401 body is ours (SafeError), not the SDK's


class ApiError(Exception):
    """A refusal carrying its HTTP status and SafeError code, rendered by the exception handler; the flags say which
    browser cookies the response must clear (a dead session must not be presented again)."""

    def __init__(
        self, status: int, code: ErrorCode, message: str, *, clear_session: bool = False, clear_login: bool = False
    ) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.clear_session, self.clear_login = clear_session, clear_login


def safe(request: Request, status: int, code: ErrorCode, message: str, *, retryable: bool = False) -> JSONResponse:
    """A SafeError response carrying this request's id (ruling 20); `retryable` only for a transient outage."""
    return limits.safe_response(limits.request_id_of(request.scope), status, code, message, retryable=retryable)


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
    """The caller: the verified subject plus the tenant and roles its current membership grants, and the session row
    when the identity came from the cookie (None on the bearer path)."""

    def __init__(
        self, *, subject: UUID, username: str, membership: st.Membership, session: st.SessionRow | None
    ) -> None:
        self.subject = subject
        self.username = username
        self.tenant_id = membership.tenant_id
        self.roles = membership.roles
        self.session = session

    @property
    def auth(self) -> str:
        """How the caller authenticated: `bearer` (a token) or `session` (the cookie)."""
        return "bearer" if self.session is None else "session"

    def require(self, role: str) -> None:
        """Refuse with 403 unless the caller holds the role."""
        if role not in self.roles:
            raise ApiError(403, ErrorCode.FORBIDDEN, f"the {role} role is required")


def create_app(
    verifier: Verifier,
    store_factory: Callable[[], st.Store | Awaitable[st.Store]],
    auth_factory: Callable[[], AuthDeps | Awaitable[AuthDeps]],
    *,
    admission: AdmissionSettings | None = None,
) -> FastAPI:
    """Build the application around a verifier, a store factory and an auth-deps factory (the lifespan runs both).

    `admission` carries the body limit and the other T12 bounds; tests pass their own, production passes
    `settings.admission()`, and the default is the spec's starting values (BUILD_SPEC §17).
    """
    bounds = admission or AdmissionSettings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        made = store_factory()
        app.state.store = await made if isinstance(made, Awaitable) else made
        try:
            if isinstance(app.state.store, st.DbStore):
                await persistence.assert_clock_profile(app.state.store.session.conn, settings.profile())
                await persistence.assert_relation(app.state.store.session.conn, "app.login_state")  # revision 0005
            if not verifier.ready:
                await verifier.load_keys()
            deps = auth_factory()
            app.state.auth = await deps if isinstance(deps, Awaitable) else deps
            try:
                for tokens in (app.state.auth.id_tokens, app.state.auth.logout_tokens):
                    if not tokens.ready:
                        await tokens.load_keys()
                yield
            finally:
                await app.state.auth.aclose()
        finally:
            if isinstance(app.state.store, st.DbStore):
                await app.state.store.session.conn.close()

    app = FastAPI(title="ops-api", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(limits.BodyLimit, max_bytes=bounds.max_body_bytes)
    app.add_middleware(limits.RequestId)  # added last, so outermost: the body refusal carries the request id too
    issuer = settings.keycloak().issuer

    async def identity(
        request: Request, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
    ) -> Identity:
        store: st.Store = request.app.state.store
        deps: AuthDeps = request.app.state.auth
        if creds is not None:
            # The bearer path (dev-only direct grant); a cookie sent beside it is ignored (ruling 7).
            try:
                principal = await verifier.verify_async(creds.credentials)
            except TokenRejected as exc:
                raise ApiError(401, ErrorCode.UNAUTHENTICATED, "token rejected") from exc
            try:
                subject = UUID(principal.subject)
            except ValueError as exc:
                raise ApiError(401, ErrorCode.UNAUTHENTICATED, "token subject is not an identity") from exc
            membership = await store.membership(issuer, subject)
            if membership is None:
                # No single current membership is no application identity (BUILD_SPEC §7; SA:549), ruling 21.
                raise ApiError(401, ErrorCode.UNAUTHENTICATED, "no active membership")
            username = str(principal.claims.get("preferred_username", ""))
            return Identity(subject=subject, username=username, membership=membership, session=None)
        raw = request.cookies.get(au.SESSION_COOKIE)
        if raw is None:
            raise ApiError(401, ErrorCode.UNAUTHENTICATED, "a session or bearer token is required")
        row = await store.live_session(au.digest(raw), idle_seconds=deps.sessions.idle_seconds)
        if row is None:
            # A session the limits ended also ends the provider session (final review I1): otherwise the next login
            # rides Keycloak's 8 h SSO session without a password. Only the request that revokes it gets the row.
            expired = await store.expire_session(au.digest(raw), idle_seconds=deps.sessions.idle_seconds)
            if expired is not None:
                try:
                    await deps.oidc.end_session(deps.box.open(expired.refresh_token_enc))
                except (ValueError, ExchangeUnavailable) as exc:
                    log.info("provider session not ended (%s); the local session is expired", exc.__class__.__name__)
            raise ApiError(401, ErrorCode.UNAUTHENTICATED, "session expired or unknown", clear_session=True)
        # Current membership on every request (BUILD_SPEC §9, R013): the session carries no authority of its own.
        membership = await store.membership(row.issuer, row.subject)
        if membership is None or membership.tenant_id != row.tenant_id:
            await store.revoke_session(row.session_sha256)
            raise ApiError(401, ErrorCode.UNAUTHENTICATED, "no active membership", clear_session=True)
        return Identity(subject=row.subject, username=row.username, membership=membership, session=row)

    async def browser_mutation(request: Request, who: Annotated[Identity, Depends(identity)]) -> Identity:
        """BUILD_SPEC §7: CSRF and origin protection in cookie mode; the bearer path carries no cookie and is exempt."""
        if who.session is None:
            return who
        deps: AuthDeps = request.app.state.auth
        if not au.same_origin(request.headers, deps.sessions.origin):
            raise ApiError(403, ErrorCode.FORBIDDEN, "cross-origin request refused")
        token = request.headers.get(au.CSRF_HEADER)
        if not token or not au.matches(token, who.session.csrf_secret_sha256):
            raise ApiError(403, ErrorCode.FORBIDDEN, "missing or invalid CSRF token")
        return who

    async def enabled_identity(request: Request, who: Annotated[Identity, Depends(browser_mutation)]) -> Identity:
        """SA:542-546: a decision-class mutation first asks Keycloak whether the user is still enabled, before any
        transaction (T11 review note 2); down or slow fails closed with a retryable 503."""
        deps: AuthDeps = request.app.state.auth
        try:
            enabled = await deps.admin.enabled(who.subject)
        except AdminUnavailable as exc:
            log.warning("request %s: enabled check unavailable: %s", request.state.request_id, exc)
            raise ApiError(503, ErrorCode.UNAVAILABLE, "identity provider unavailable") from exc
        if not enabled:
            if who.session is not None:
                await request.app.state.store.revoke_session(who.session.session_sha256)
            raise ApiError(401, ErrorCode.UNAUTHENTICATED, "identity disabled", clear_session=who.session is not None)
        return who

    def failed(request: Request, exc: BaseException) -> None:
        """Log a server-side failure once, with the request id and the class name only: an exception's text may carry
        SQL, or a psycopg DETAIL naming a tenant, a subject and a key in clear (spike §1)."""
        log.error("request %s failed: %s", limits.request_id_of(request.scope), exc.__class__.__name__)

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> Response:
        # Every 503 an ApiError carries is an identity-provider outage (admin API, token endpoint, signing keys), the
        # one kind of refusal a client should retry (ruling 19).
        response = safe(request, exc.status, exc.code, exc.message, retryable=exc.status == 503)
        if exc.clear_session or exc.clear_login:  # the auth deps exist whenever a route that sets these flags runs
            cookies: au.CookiePolicy = request.app.state.auth.cookies
            if exc.clear_session:
                cookies.clear_session(response)
            if exc.clear_login:
                cookies.clear_login(response)
        return response

    @app.exception_handler(st.Internal)
    @app.exception_handler(persistence.PersistenceError)
    @app.exception_handler(IllegalTransition)
    @app.exception_handler(EventRuleViolation)
    @app.exception_handler(psycopg.Error)
    @app.exception_handler(psycopg.errors.ProgramLimitExceeded)
    @app.exception_handler(psycopg.errors.StatementTooComplex)
    async def _server_defect(request: Request, exc: Exception) -> Response:
        # A defect, a refused deployment (AuthorityViolation is a PersistenceError), an untranslated SQLSTATE (a 23505)
        # or a statement too big for the server (class 54): a retry meets the same defect, so not retryable (ruling 19).
        failed(request, exc)
        return safe(request, 503, ErrorCode.UNAVAILABLE, "service error")

    @app.exception_handler(psycopg.OperationalError)
    @app.exception_handler(psycopg.InterfaceError)
    async def _database_down(request: Request, exc: psycopg.Error) -> Response:
        # A lost connection or a transient server condition: nothing committed, so a retry may succeed (BS:564). The
        # class-54 handlers above were registered first and Starlette walks the exception's MRO, so they keep theirs.
        failed(request, exc)
        return safe(request, 503, ErrorCode.UNAVAILABLE, "database unavailable", retryable=True)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> Response:
        # Starlette answers, then re-raises (spike §5): uvicorn logs the traceback through the redaction filter.
        failed(request, exc)
        return safe(request, 503, ErrorCode.UNAVAILABLE, "service error")

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> Response:
        # The router's own refusals (unknown path, wrong method) answer FastAPI's `{"detail": ...}` otherwise.
        if exc.status_code == 404:
            return safe(request, 404, ErrorCode.NOT_FOUND, "no such route")
        if exc.status_code == 405:
            response = safe(request, 405, ErrorCode.INVALID_INPUT, "method not allowed")
            allow = (exc.headers or {}).get("Allow")
            if allow is not None:
                response.headers["Allow"] = allow  # RFC 9110 §15.5.6: a 405 names the methods that would work
            return response
        return safe(request, 422, ErrorCode.INVALID_INPUT, "request refused")

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, __: RequestValidationError) -> Response:
        return safe(request, 422, ErrorCode.INVALID_INPUT, "request is not valid")

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
                return safe(request, 503, ErrorCode.UNAVAILABLE, "database not reachable", retryable=True)
        return JSONResponse({"status": "ready"})

    @app.get("/")
    async def landing() -> dict[str, str]:
        """Where the post-login 303 lands until the web app exists. TODO(T26): the web app's static assets."""
        return {"status": "ok", "login_url": "/auth/login"}

    def no_store(response: Response) -> Response:
        """Auth responses are never cached."""
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/auth/login")
    async def login(request: Request) -> Response:
        """Start the authorization-code flow with PKCE (BUILD_SPEC §9): state, nonce and verifier live in the store
        under the login cookie's hash (SA:565), never in a signed cookie."""
        store: st.Store = request.app.state.store
        deps: AuthDeps = request.app.state.auth
        if not au.same_host(request.headers.get("host", ""), deps.sessions.public_base_url):
            # A browser at 127.0.0.1:8000 would get its login cookie on a host Keycloak never redirects back to (the
            # registered callback is exact), so it is sent to the public host first (round-1 review focus).
            return no_store(RedirectResponse(f"{deps.sessions.public_base_url}/auth/login", status_code=303))
        login_token, state, nonce, verifier_value = au.new_token(), au.new_token(), au.new_token(), au.new_token()
        await store.begin_login(
            login_sha256=au.digest(login_token),
            state_sha256=au.digest(state),
            nonce_sha256=au.digest(nonce),
            code_verifier=verifier_value,
            ttl_seconds=deps.sessions.login_seconds,
        )
        target = deps.oidc.authorization_url(state=state, nonce=nonce, code_verifier=verifier_value)
        response: Response = RedirectResponse(target, status_code=303)
        deps.cookies.set_login(response, login_token)
        return no_store(response)

    @app.get("/auth/callback")
    async def callback(request: Request) -> Response:
        """Validate the callback context (R011) and open a session: login cookie → stored request (one shot), state
        hash, `iss` (RFC 9207), code exchange with the stored verifier, ID token with the stored nonce, current
        membership; then rotate (BUILD_SPEC §9) and set the cookies."""
        store: st.Store = request.app.state.store
        deps: AuthDeps = request.app.state.auth
        q = request.query_params
        raw_login = request.cookies.get(au.LOGIN_COOKIE)
        if raw_login is None:
            raise ApiError(401, ErrorCode.UNAUTHENTICATED, "no login in progress")
        pending = await store.take_login(au.digest(raw_login))
        if pending is None:
            raise ApiError(401, ErrorCode.UNAUTHENTICATED, "login expired or unknown", clear_login=True)
        if "error" in q:
            code_text = q.get("error", "")
            # The code only, never the text; a value that is not a plain OAuth code could carry CR/LF into the log.
            log.info(
                "login refused by the identity provider: %s", code_text if ERROR_CODE.fullmatch(code_text) else "other"
            )
            raise ApiError(401, ErrorCode.UNAUTHENTICATED, "login refused by the identity provider", clear_login=True)
        state, code = q.get("state"), q.get("code")
        if not state or not code or not au.matches(state, pending.state_sha256):
            raise ApiError(401, ErrorCode.UNAUTHENTICATED, "state mismatch", clear_login=True)
        if q.get("iss") != issuer:
            raise ApiError(401, ErrorCode.UNAUTHENTICATED, "issuer mismatch", clear_login=True)
        try:
            tokens = await deps.oidc.exchange(code=code, code_verifier=pending.code_verifier)
        except ExchangeRefused as exc:
            raise ApiError(401, ErrorCode.UNAUTHENTICATED, "code exchange refused", clear_login=True) from exc
        except ExchangeUnavailable as exc:
            log.warning("token endpoint unavailable: %s", exc)
            raise ApiError(503, ErrorCode.UNAVAILABLE, "identity provider unavailable", clear_login=True) from exc
        try:
            claims = await deps.id_tokens.verify(tokens.id_token, nonce_sha256=pending.nonce_sha256)
        except SigningKeysUnavailable as exc:  # the provider is down, not the token at fault (final review M5)
            log.warning("signing keys unavailable at the callback")
            raise ApiError(503, ErrorCode.UNAVAILABLE, "identity provider unavailable", clear_login=True) from exc
        except TokenRejected as exc:
            raise ApiError(401, ErrorCode.UNAUTHENTICATED, "id token rejected", clear_login=True) from exc
        membership = await store.membership(issuer, claims.subject)
        if membership is None:
            raise ApiError(401, ErrorCode.UNAUTHENTICATED, "no active membership", clear_login=True)
        previous = request.cookies.get(au.SESSION_COOKIE)
        if previous is not None:
            await store.revoke_session(au.digest(previous))  # rotation: a login never extends an older session
        session_token, csrf = au.new_token(), au.new_token()
        await store.create_session(
            session_sha256=au.digest(session_token),
            issuer=issuer,
            subject=claims.subject,
            tenant_id=membership.tenant_id,
            sid=claims.sid,
            username=claims.username,
            csrf_secret_sha256=au.digest(csrf),
            refresh_token_enc=deps.box.seal(tokens.refresh_token),
            absolute_seconds=deps.sessions.absolute_seconds,
        )
        response: Response = RedirectResponse("/", status_code=303)
        deps.cookies.clear_login(response)
        deps.cookies.set_session(response, session_token, csrf)
        return no_store(response)

    @app.post("/auth/logout", status_code=204)
    async def logout(request: Request, who: Annotated[Identity, Depends(browser_mutation)]) -> Response:
        """Revoke the session, then end the provider session server-side with the sealed refresh token (ruling 4);
        a provider failure is logged and the local revocation stands."""
        if who.session is None:
            raise ApiError(403, ErrorCode.FORBIDDEN, "logout applies to a browser session")
        store: st.Store = request.app.state.store
        deps: AuthDeps = request.app.state.auth
        row = await store.revoke_session(who.session.session_sha256)
        if row is not None:
            try:
                await deps.oidc.end_session(deps.box.open(row.refresh_token_enc))
            except (ValueError, ExchangeUnavailable) as exc:
                log.info("provider session not ended (%s); the local session is revoked", exc.__class__.__name__)
        response = Response(status_code=204)
        deps.cookies.clear_session(response)
        return no_store(response)

    @app.post("/auth/backchannel-logout")
    async def backchannel_logout(request: Request) -> Response:
        """OIDC Back-Channel Logout 1.0 receiver (SA:541): validate, record the jti, revoke by sid; 400 for a bad or
        replayed token, a retryable 503 when the keys or the store are unavailable (erratum 34). Exempt from CSRF and
        Idempotency-Key (no session, no caller to replay for; T11 review note 3)."""
        store: st.Store = request.app.state.store
        deps: AuthDeps = request.app.state.auth
        try:
            form = await request.form()
        except Exception as exc:  # a non-form body must be a 400, whatever starlette raises while parsing
            raise ApiError(400, ErrorCode.INVALID_INPUT, "logout_token is required") from exc
        token = form.get("logout_token")
        if not isinstance(token, str) or not token:
            raise ApiError(400, ErrorCode.INVALID_INPUT, "logout_token is required")
        try:
            claims = await deps.logout_tokens.verify(token)
        except SigningKeysUnavailable as exc:
            log.warning("request %s: back-channel logout failed: no signing keys", request.state.request_id)
            raise ApiError(503, ErrorCode.UNAVAILABLE, "identity provider unavailable") from exc
        except TokenRejected as exc:
            log.info("request %s: back-channel logout token rejected: %s", request.state.request_id, exc)
            raise ApiError(400, ErrorCode.INVALID_INPUT, "logout token rejected") from exc
        keep_until = datetime.fromtimestamp(claims.expires_at, UTC) + timedelta(days=1)
        try:
            revoked = await store.record_logout(claims.jti, expires_at=keep_until, sid=claims.sid)
        except psycopg.Error as exc:
            # Keycloak never retries, so this line is the operator's only trace of a logout that did not take effect
            # (final review M4); the class name only, never the token. The 503 handler answers.
            log.warning("request %s: back-channel logout failed: %s", request.state.request_id, type(exc).__name__)
            raise
        if revoked is None:
            raise ApiError(400, ErrorCode.INVALID_INPUT, "logout token replayed")
        log.info("request %s: back-channel logout revoked %d session(s)", request.state.request_id, revoked)
        return no_store(Response(status_code=200))

    @app.get("/api/v1/me")
    async def me(who: Annotated[Identity, Depends(identity)]) -> dict[str, Any]:
        return {
            "subject": str(who.subject),
            "tenant_id": str(who.tenant_id),
            "roles": sorted(who.roles),
            "username": who.username,
            "auth": who.auth,
        }

    @app.post("/api/v1/conversations", status_code=201)
    async def create_conversation(
        request: Request, who: Annotated[Identity, Depends(browser_mutation)]
    ) -> dict[str, str]:
        cid = await request.app.state.store.create_conversation(who.tenant_id, who.subject)
        return {"conversation_id": str(cid)}

    @app.post("/api/v1/conversations/{conversation_id}/messages", status_code=202)
    async def post_message(
        conversation_id: UUID, request: Request, who: Annotated[Identity, Depends(browser_mutation)]
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
        proposal_id: UUID, request: Request, who: Annotated[Identity, Depends(enabled_identity)]
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
    sess = settings.sessions()
    verifier = TokenVerifier(
        issuer=kc.issuer,
        audience=settings.env("OPS_API_AUDIENCE", "ops-api"),
        allowed_azp=frozenset({"ops-dev-direct"}),
        jwks_url=kc.jwks_url,
    )

    async def make_store() -> st.Store:
        return st.DbStore(await persistence.connect(settings.app_postgres(Role.API)))

    async def make_auth() -> AuthDeps:
        # Discovery first (ruling 25): a realm that does not match the configuration refuses to start.
        http = httpx2.AsyncClient(timeout=httpx2.Timeout(10.0))
        closers: list[au.Closer] = [http.aclose]
        try:
            discovery = await au.fetch_discovery(kc, http)
            admin = keycloak_admin.admin_users(
                keycloak=kc,
                client_secret=settings.read_secret("kc_client_secret_ops_view_users"),
                timeout=settings.admin_check_timeout(),
            )
            closers.append(admin.aclose)
            oidc = au.AuthlibOidc(
                discovery=discovery,
                client_secret=settings.read_secret("kc_client_secret_ops_web"),
                redirect_uri=sess.redirect_uri,
                http=http,
                max_age=sess.idle_seconds,
            )
            closers.append(oidc.aclose)
            return AuthDeps(
                oidc=oidc,
                id_tokens=au.IdTokenVerifier(issuer=kc.issuer, jwks_url=discovery.jwks_uri, max_age=sess.idle_seconds),
                logout_tokens=au.LogoutTokenVerifier(issuer=kc.issuer, jwks_url=discovery.jwks_uri),
                admin=admin,
                box=au.TokenBox(settings.read_secret("api_session_key")),
                sessions=sess,
                cookies=au.CookiePolicy(secure=sess.cookie_secure, login_max_age=sess.login_seconds),
                closers=tuple(closers),
            )
        except BaseException:  # close whatever was built, then let the startup failure through
            for close in reversed(closers):
                await close()
            raise

    return create_app(verifier, make_store, make_auth, admission=settings.admission())

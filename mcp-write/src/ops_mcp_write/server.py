"""mcp-write: the authenticated write server (ADR-0003; AM-13 attempt protocol; SA:557 token checks).

One tool, `create_incident`; the grant, the dispatch and the outcome happen here, never in the worker.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Protocol, TypedDict
from uuid import UUID, uuid4

import httpx2
import psycopg
import uvicorn
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.tools.base import Tool
from ops_core import persistence, redaction, settings
from ops_core.jobs import Tool as ToolName
from ops_core.outcomes import ActionOutcome, ToolOutcome
from ops_core.settings import Role
from ops_core.tokens import Principal, TokenRejected, TokenVerifier, WorkloadTokenSource
from pydantic import AnyHttpUrl, ConfigDict, Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp

from ops_mcp_write import execution

# Duplicated from mcp-read on purpose: members never import each other (ADR-0001, test_layout); the shape is pinned
# by the tool-result contract tests in both packages.


class ToolResult(TypedDict):
    """The AM-80 tool-result envelope every tool returns."""

    tool_name: str
    request_id: str
    status: str
    observed_at: str
    truncated: bool
    data: dict[str, Any] | None
    error: dict[str, Any] | None


def stamp(value: datetime) -> str:
    """UTC timestamp in the `...Z` seconds-only spelling the contract uses."""
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def tool_error(code: str, message: str, *, retryable: bool = False) -> dict[str, Any]:
    """The `error` object of an envelope; retryable only for GRANT_DEFERRED (T11)."""
    return {"code": code, "message": message, "retryable": retryable}


def refusal_error(code: str) -> dict[str, Any]:
    """The tool error for a grant refusal: MEMBERSHIP_STALE is the one the worker retries (Plan F ruling 14)."""
    if code == "MEMBERSHIP_STALE":
        return tool_error("GRANT_DEFERRED", f"grant deferred: {code}", retryable=True)
    return tool_error("GRANT_REFUSED", f"grant refused: {code}")


def envelope(tool_name: str, *, data: dict[str, Any] | None = None, error: dict[str, Any] | None = None) -> ToolResult:
    """Wrap data or an error in the AM-80 envelope with a fresh request_id."""
    return {
        "tool_name": tool_name,
        "request_id": str(uuid4()),
        "status": "error" if error is not None else "ok",
        "observed_at": stamp(datetime.now(UTC)),
        "truncated": False,
        "data": None if error is not None else data,
        "error": error,
    }


class Verifier(Protocol):  # the subset of ops_core.tokens.TokenVerifier the server needs; unit tests stub it
    """Token-verifier subset the server needs, so unit tests can stub it."""

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


class McpVerifier:
    """The SDK's TokenVerifier protocol: None means 401. The SDK re-checks `expires_at`, consistently with PyJWT."""

    def __init__(self, verifier: Verifier, resource_url: str) -> None:
        """Adapt a token verifier to the SDK's bearer-auth hook; `resource_url` is stamped on the access token."""
        self._verifier = verifier
        self._resource = resource_url

    async def verify_token(self, token: str) -> AccessToken | None:
        """Return the access token for a valid bearer token, None (401) otherwise."""
        try:
            principal = await self._verifier.verify_async(token)
        except TokenRejected:
            return None
        return AccessToken(
            token=token,
            client_id=principal.azp,
            scopes=[],
            expires_at=principal.expires_at,
            resource=self._resource,
            subject=principal.subject,
            claims=dict(principal.claims),
        )


def strict_tool(fn: Any) -> Tool:
    """A Tool whose argument model forbids extra keys and whose advertised schema says so.

    The SDK derives the model from the signature and ignores unknown keys (measured in the Plan D spike); SA:350
    requires the opposite, so the model is subclassed with `extra="forbid"` and the schema regenerated. `strict`
    stops lax coercion, so `limit="1"` or `limit=True` is refused rather than read as 1.
    """
    tool = Tool.from_function(fn)
    base = tool.fn_metadata.arg_model
    strict: Any = type(
        base.__name__, (base,), {"model_config": ConfigDict(arbitrary_types_allowed=True, extra="forbid", strict=True)}
    )
    tool.fn_metadata.arg_model = strict
    tool.parameters = strict.model_json_schema(by_alias=True)
    return tool


def serve_app(app: ASGIApp, port: int) -> None:
    """Serve with uvicorn programmatically on a selector loop (ruling 23: `uvicorn.run` picks the Proactor loop on
    Windows and psycopg async refuses it)."""
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", log_config=None))
    if sys.platform == "win32":
        asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(server.serve())


def outcome_envelope(outcome: ActionOutcome) -> ToolResult:
    """`ok` only wraps SUCCEEDED (R083); every other outcome is `status=outcome` with `data.action_id` (SA:352)."""
    data = outcome.model_dump(mode="json")
    doc = envelope("create_incident", data=data)
    if outcome.status is not ToolOutcome.SUCCEEDED:
        doc["status"] = "outcome"
    return doc


@dataclass
class State:
    """Process-wide dependencies the tool and the app share; `deps` is filled at startup."""

    deps: execution.Deps | None
    verifier: Verifier


def build_server(state: State, *, issuer: str, resource_url: str) -> MCPServer:
    """Assemble the MCP server with bearer auth and the one strict tool, bound to `state`."""

    # strict=False on this one field: the model is strict, and strict UUID validation refuses the string a client sends
    async def create_incident(proposal_id: Annotated[UUID, Field(strict=False)], ctx: Context) -> ToolResult:
        """Grant, dispatch and record the approved proposal's incident (AM-13 §2, AM-20.3 grant_execution)."""
        token = get_access_token()
        handle = (ctx.headers or {}).get("x-ops-invocation")
        if token is None or not handle or state.deps is None:
            return envelope("create_incident", error=tool_error("INVALID_HANDLE", "missing invocation handle"))
        try:
            async with state.deps.session.unit() as conn:
                await persistence.resolve_invocation(
                    conn, handle=handle, azp=token.client_id, tool=ToolName.CREATE_INCIDENT
                )  # binds server, azp, expiry and the tool allowlist before any work (SA:459)
            outcome = await execution.create_incident(state.deps, handle=handle, proposal_id=proposal_id)
        except persistence.HandleRejected as exc:
            return envelope("create_incident", error=tool_error("INVALID_HANDLE", str(exc)))
        except persistence.Refused as exc:
            return envelope("create_incident", error=refusal_error(exc.code))
        except persistence.NotFound:
            return envelope("create_incident", error=tool_error("NOT_FOUND", "run not found"))
        except persistence.VersionConflict:
            # Only grant_execution and mark_sent can raise this here, both before this call sends anything, so the
            # worker closes the job without a retry cycle. After SENT execution.py answers UNKNOWN instead (AM-13).
            return envelope("create_incident", error=tool_error("STALE_RUN", "run is no longer executing"))
        except persistence.HashMismatch:
            return envelope("create_incident", error=tool_error("HASH_MISMATCH", "stored bytes do not match"))
        # AuthorityViolation stays unmapped on purpose: it is a deployment error (the role lacks a grant), so the raw
        # tool error and the worker's re-queue are the right outcome.
        return outcome_envelope(outcome)

    return MCPServer(
        name="mcp-write",
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(issuer), resource_server_url=AnyHttpUrl(resource_url), validate_token_resource=False
        ),
        token_verifier=McpVerifier(state.verifier, resource_url),
        tools=[strict_tool(create_incident)],
    )


def build_app(server: MCPServer, state: State) -> Starlette:
    """Mount the MCP transport beside health routes and own the session, HTTP client and key loading."""
    mcp_app = server.streamable_http_app(streamable_http_path="/mcp", stateless_http=True, json_response=True)

    @contextlib.asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        """Build the write dependencies and load keys, run the mounted app's lifespan, then close both resources."""
        if state.deps is None:
            kc = settings.keycloak()
            conn = await persistence.connect(settings.app_postgres(Role.MCP_EXEC))
            try:
                await persistence.assert_clock_profile(conn, settings.profile())
            except BaseException:  # a failed start must leak no connection
                await conn.close()
                raise
            session = persistence.Session(conn)
            state.deps = execution.Deps(
                session=session,
                http=httpx2.AsyncClient(),
                destination_url=settings.urls().incident_sim,
                destination_token=WorkloadTokenSource(
                    token_url=kc.token_url,
                    client_id="ops-mcp-write",
                    client_secret=settings.read_secret("kc_client_secret_ops_mcp_write"),
                ),
            )
        try:
            if not state.verifier.ready:  # inside the try: a failed JWKS load must close both resources too
                await state.verifier.load_keys()
            async with mcp_app.router.lifespan_context(mcp_app):
                yield
        finally:
            await state.deps.http.aclose()
            await state.deps.session.conn.close()

    async def live(_: Request) -> JSONResponse:
        """Liveness: the process is up."""
        return JSONResponse({"status": "live"})

    async def ready(_: Request) -> JSONResponse:
        """Readiness: keys loaded and the database answers."""
        if state.deps is None or not state.verifier.ready:
            return JSONResponse({"status": "not ready"}, status_code=503)
        try:
            await state.deps.session.ping()
        except (psycopg.Error, OSError):  # readiness reports a database failure as not ready
            return JSONResponse({"status": "not ready"}, status_code=503)
        return JSONResponse({"status": "ready"})

    return Starlette(
        routes=[Route("/health/live", live), Route("/health/ready", ready), Mount("/", app=mcp_app)], lifespan=lifespan
    )


def production_app() -> Starlette:
    """The app wired from the environment and secret files, as `python -m ops_mcp_write` runs it."""
    kc = settings.keycloak()
    urls = settings.urls()
    verifier = TokenVerifier(
        issuer=kc.issuer, audience=urls.mcp_write_resource, allowed_azp=frozenset({"ops-worker"}), jwks_url=kc.jwks_url
    )
    state = State(deps=None, verifier=verifier)
    return build_app(build_server(state, issuer=kc.issuer, resource_url=urls.mcp_write_resource), state)


def serve() -> None:
    """Entry point: serve the production app on OPS_MCP_WRITE_PORT (default 8082)."""
    # The redaction filter must sit on the root handler before the first log line (T11 note 4).
    redaction.install()
    serve_app(production_app(), settings.env_int("OPS_MCP_WRITE_PORT", 8082))

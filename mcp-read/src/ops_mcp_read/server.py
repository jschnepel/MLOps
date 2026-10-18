"""mcp-read: the authenticated read-tool server (ADR-0003; AM-15 read tools; SA:557 token checks).

Every call must carry `MCP-Protocol-Version: 2026-07-28` (anything else is refused before authentication, AM-30), the
worker's workload access token (`typ` Bearer, aud = this server's resource URL, azp = the worker's client) and an
`X-Ops-Invocation` handle minted for an `investigate` job; the handle, not the token, says which run and tenant the
call is for (BUILD_SPEC §9). The tool's argument model forbids extra keys, so an argument that tries to supply a
tenant, role or actor is refused before the tool body runs (SA:350). Results are the AM-80 tool-result envelope
(validated against schemas/tool-result.schema.json in the unit tests). One tool in T08; asset tools arrive with T16.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Protocol, TypedDict
from uuid import UUID, uuid4

import psycopg
import uvicorn
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.tools.base import Tool
from ops_core import persistence, redaction, settings
from ops_core.jobs import Tool as ToolName
from ops_core.mcp_protocol import MCP_PATH, ProtocolVersionGuard
from ops_core.settings import Role
from ops_core.tokens import Principal, TokenRejected, TokenVerifier
from pydantic import AnyHttpUrl, ConfigDict, Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp

from ops_mcp_read import procedures

# Revision 0009's startup marker, kept under this name for callers that read it here; the value is core's, which
# mcp-write checks too (Plan J ruling 18 and the final review).
HANDLE_BINDING = persistence.HANDLE_BINDING


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


def tool_error(code: str, message: str) -> dict[str, Any]:
    """The `error` object of an envelope; never retryable in T08."""
    return {"code": code, "message": message, "retryable": False}


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


def search_response(
    corpora: dict[UUID, procedures.Corpus], *, tenant_id: UUID, query: str, limit: int, now: datetime
) -> ToolResult:
    """The tool's answer for a resolved tenant; database-free so the contract test can validate it."""
    corpus = corpora.get(tenant_id)
    fallback = next(iter(corpora.values()), None)
    version = corpus.corpus_version if corpus else (fallback.corpus_version if fallback else "none")
    hits = corpus.search(query, limit) if corpus else []
    results = [
        {
            "evidence_id": h.section.evidence_id,
            "document_id": h.section.document_id,
            "version": h.section.version,
            "section": h.section.section,
            "content_sha256": h.section.content_sha256,
            "excerpt": h.section.text[: procedures.EXCERPT_CHARS],
            "effective_from": h.section.effective_from,
            "retrieved_at": stamp(now),
        }
        for h in hits
    ]
    return envelope(
        "search_procedures", data={"results": results, "retrieval_mode": "lexical", "corpus_version": version}
    )


class Verifier(Protocol):  # the subset of ops_core.tokens.TokenVerifier the server needs; unit tests stub it
    """Token-verifier subset the server needs, so unit tests can stub it."""

    @property
    def ready(self) -> bool: ...

    async def load_keys(self) -> None: ...

    async def verify_async(self, token: str) -> Principal: ...


class McpVerifier:
    """The SDK's TokenVerifier protocol: None means 401. The SDK re-checks `expires_at`, consistently with PyJWT.

    A token whose `aud` lacks this server's resource URL is refused here, whatever audience the wrapped verifier was
    configured with, and only then is `resource` stamped with that URL (Plan J ruling 2). The SDK's own resource check
    (`validate_token_resource`) stays on as a second layer; it cannot refuse anything while the stamp is this server's
    own URL, and would decide only if the stamp ever came from the token.
    """

    def __init__(self, verifier: Verifier, resource_url: str) -> None:
        """Adapt a token verifier to the SDK's bearer-auth hook; `resource_url` is this server's audience."""
        self._verifier = verifier
        self._resource = resource_url

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            principal = await self._verifier.verify_async(token)
        except TokenRejected:
            return None
        if self._resource not in principal.audiences:
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


@dataclass
class State:
    """Process-wide dependencies the tool and the app share; `session` is filled at startup."""

    session: persistence.Session | None
    corpora: dict[UUID, procedures.Corpus]
    verifier: Verifier


def build_server(state: State, *, issuer: str, resource_url: str) -> MCPServer:
    """Assemble the MCP server with bearer auth and the one strict tool, bound to `state`."""

    async def search_procedures(
        query: Annotated[str, Field(min_length=1, max_length=500)],
        limit: Annotated[int, Field(ge=1, le=8)],
        mode: Literal["lexical", "vector_exact"],
        ctx: Context,
    ) -> ToolResult:
        """Lexical search over approved procedure sections of the calling run's tenant (AM-15 read tool)."""
        token = get_access_token()
        handle = (ctx.headers or {}).get("x-ops-invocation")  # header names arrive lower-case
        if token is None or not handle or state.session is None:
            return envelope("search_procedures", error=tool_error("INVALID_HANDLE", "missing invocation handle"))
        try:
            async with state.session.unit() as conn:
                invocation = await persistence.resolve_invocation(
                    conn, handle=handle, azp=token.client_id, tool=ToolName.SEARCH_PROCEDURES
                )
        except persistence.HandleRejected as exc:
            return envelope("search_procedures", error=tool_error("INVALID_HANDLE", str(exc)))
        if mode != "lexical":
            return envelope("search_procedures", error=tool_error("UNSUPPORTED_MODE", "vector_exact arrives with T17"))
        return search_response(
            state.corpora, tenant_id=invocation.tenant_id, query=query, limit=limit, now=datetime.now(UTC)
        )

    return MCPServer(
        name="mcp-read",
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(issuer), resource_server_url=AnyHttpUrl(resource_url), validate_token_resource=True
        ),
        token_verifier=McpVerifier(state.verifier, resource_url),
        tools=[strict_tool(search_procedures)],
    )


def build_app(server: MCPServer, state: State) -> Starlette:
    """Mount the MCP transport beside health routes and own the database session and key loading."""
    mcp_app = server.streamable_http_app(streamable_http_path=MCP_PATH, stateless_http=True, json_response=True)

    @contextlib.asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        """Open the session and keys, run the mounted app's lifespan, then close the connection."""
        if state.session is None:
            conn = await persistence.connect(settings.app_postgres(Role.MCP_READ))
            try:
                await persistence.assert_clock_profile(conn, settings.profile())
                await persistence.assert_function_text(conn, *HANDLE_BINDING)
                await persistence.assert_function_text(conn, *persistence.GOVERNED_CORPUS)  # 0011 (T17)
            except BaseException:  # a failed start must leak no connection, and a re-entered lifespan re-asserts
                await conn.close()
                raise
            state.session = persistence.Session(conn)
        # A mounted sub-app's lifespan never runs on its own; the session manager lives in it (measured).
        try:
            if not state.verifier.ready:  # inside the try: a failed JWKS load must close the connection too
                await state.verifier.load_keys()
            async with mcp_app.router.lifespan_context(mcp_app):
                yield
        finally:
            await state.session.conn.close()

    async def live(_: Request) -> JSONResponse:
        """Liveness: the process is up."""
        return JSONResponse({"status": "live"})

    async def ready(_: Request) -> JSONResponse:
        """Readiness: keys loaded and the database answers."""
        if state.session is None or not state.verifier.ready:
            return JSONResponse({"status": "not ready"}, status_code=503)
        try:
            await state.session.ping()
        except (psycopg.Error, OSError):  # readiness reports a database failure as not ready
            return JSONResponse({"status": "not ready"}, status_code=503)
        return JSONResponse({"status": "ready"})

    return Starlette(
        routes=[
            Route("/health/live", live),
            Route("/health/ready", ready),
            # The version rule runs before the SDK app and its bearer auth (AM-30, Plan J ruling 4).
            Mount("/", app=ProtocolVersionGuard(mcp_app)),
        ],
        lifespan=lifespan,
    )


def read_verifier(kc: settings.Keycloak, urls: settings.Urls) -> TokenVerifier:
    """mcp-read's token checks (SA:557, Plan J ruling 2): the realm's issuer and keys, this server's resource URL as the
    audience, the worker's client (`settings.workload_client_id`, Plan K ruling 12) as the only `azp`, and an access
    token's `typ` claim. `production_app` builds its verifier here, and the unit tests build theirs here too, so they
    pin the wiring that runs."""
    return TokenVerifier(
        issuer=kc.issuer,
        audience=urls.mcp_read_resource,
        allowed_azp=frozenset({settings.workload_client_id()}),
        jwks_url=kc.jwks_url,
        token_type="Bearer",  # an access token: Keycloak's ID and refresh tokens carry another `typ` (ruling 2)
    )


def production_app() -> Starlette:
    """The app wired from the environment and secret files, as `python -m ops_mcp_read` runs it."""
    kc = settings.keycloak()
    urls = settings.urls()
    state = State(
        session=None, corpora=procedures.load_corpora(settings.fixtures_dir()), verifier=read_verifier(kc, urls)
    )
    return build_app(build_server(state, issuer=kc.issuer, resource_url=urls.mcp_read_resource), state)


def serve_app(app: ASGIApp, port: int) -> None:
    """Serve with uvicorn programmatically on a selector loop (ruling 23: `uvicorn.run` picks the Proactor loop on
    Windows and psycopg async refuses it)."""
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", log_config=None))
    if sys.platform == "win32":
        asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(server.serve())


def serve() -> None:
    """Entry point: serve the production app on OPS_MCP_READ_PORT (default 8081)."""
    # The redaction filter must sit on the root handler before the first log line (T11 note 4).
    redaction.install()
    serve_app(production_app(), settings.env_int("OPS_MCP_READ_PORT", 8081))

"""mcp-read: the authenticated read-tool server (ADR-0003; AM-15 read tools; SA:557 token checks).

Every call must present the worker's workload token (aud = this server's resource URL, azp = ops-worker) and an
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
from ops_core import persistence, settings
from ops_core.jobs import Tool as ToolName
from ops_core.settings import Role
from ops_core.tokens import Principal, TokenRejected, TokenVerifier
from pydantic import AnyHttpUrl, ConfigDict, Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp

from ops_mcp_read import procedures


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
    """The SDK's TokenVerifier protocol: None means 401. The SDK re-checks `expires_at`, consistently with PyJWT."""

    def __init__(self, verifier: Verifier, resource_url: str) -> None:
        """Adapt a token verifier to the SDK's bearer-auth hook; `resource_url` is stamped on the access token."""
        self._verifier = verifier
        self._resource = resource_url

    async def verify_token(self, token: str) -> AccessToken | None:
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
            issuer_url=AnyHttpUrl(issuer), resource_server_url=AnyHttpUrl(resource_url), validate_token_resource=False
        ),
        token_verifier=McpVerifier(state.verifier, resource_url),
        tools=[strict_tool(search_procedures)],
    )


def build_app(server: MCPServer, state: State) -> Starlette:
    """Mount the MCP transport beside health routes and own the database session and key loading."""
    mcp_app = server.streamable_http_app(streamable_http_path="/mcp", stateless_http=True, json_response=True)

    @contextlib.asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        """Open the session and keys, run the mounted app's lifespan, then close the connection."""
        if state.session is None:
            state.session = persistence.Session(await persistence.connect(settings.app_postgres(Role.MCP_READ)))
            await persistence.assert_clock_profile(state.session.conn, settings.profile())
        if not state.verifier.ready:
            await state.verifier.load_keys()
        # A mounted sub-app's lifespan never runs on its own; the session manager lives in it (measured).
        try:
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
        routes=[Route("/health/live", live), Route("/health/ready", ready), Mount("/", app=mcp_app)], lifespan=lifespan
    )


def production_app() -> Starlette:
    """The app wired from the environment and secret files, as `python -m ops_mcp_read` runs it."""
    kc = settings.keycloak()
    urls = settings.urls()
    verifier = TokenVerifier(
        issuer=kc.issuer, audience=urls.mcp_read_resource, allowed_azp=frozenset({"ops-worker"}), jwks_url=kc.jwks_url
    )
    state = State(session=None, corpora=procedures.load_corpora(settings.fixtures_dir()), verifier=verifier)
    return build_app(build_server(state, issuer=kc.issuer, resource_url=urls.mcp_read_resource), state)


def serve_app(app: ASGIApp, port: int) -> None:
    """Serve with uvicorn programmatically on a selector loop (ruling 23: `uvicorn.run` picks the Proactor loop on
    Windows and psycopg async refuses it)."""
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    if sys.platform == "win32":
        asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(server.serve())


def serve() -> None:
    """Entry point: serve the production app on OPS_MCP_READ_PORT (default 8081)."""
    serve_app(production_app(), settings.env_int("OPS_MCP_READ_PORT", 8081))

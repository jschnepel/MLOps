"""mcp-read: the authenticated read-tool server (ADR-0003; AM-15 read tools; SA:557 token checks).

Every call must carry `MCP-Protocol-Version: 2026-07-28` (anything else is refused before authentication, AM-30), the
worker's workload access token (`typ` Bearer, aud = this server's resource URL, azp = the worker's client) and an
`X-Ops-Invocation` handle minted for an `investigate` or `resume_input` job; the handle, not the token, says which run
and tenant the call is for (BUILD_SPEC §9). Each tool advertises exactly its committed input schema
(`schemas/tools/`, Plan M ruling 13) and its strict argument model forbids extra keys, so an argument that tries to
supply a tenant, role or actor is refused before the tool body runs (SA:350). Results are the AM-80 tool-result
envelope. Three tools (T16):

- `get_asset_status` and `get_recent_alerts` resolve the handle and check the tool in one committed unit, read the
  run's scope through `asset_scope` in a second, and only then call asset-sim with mcp-read's own workload token and
  the forwarded tenant and instant (`assets.HttpAssetSim`), outside any transaction. They answer for the run's own
  asset and fixed interval only (`ASSET_OUT_OF_SCOPE`, `INTERVAL_OUT_OF_SCOPE`), and validate asset-sim's data as a
  whole tool result before returning it (`UPSTREAM_INVALID`, ruling 15).
- `search_procedures` answers from the governed corpus through `search_procedures_scoped` (T17); mcp-read reads no
  file.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from collections.abc import AsyncIterator, Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Final, Literal, Protocol, TypedDict
from uuid import uuid4

import psycopg
import uvicorn
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.tools.base import Tool
from ops_core import persistence, redaction, settings, tool_contracts
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

from ops_mcp_read import assets

# Revision 0009's startup marker, kept under this name for callers that read it here; the value is core's, which
# mcp-write checks too (Plan J ruling 18 and the final review).
HANDLE_BINDING = persistence.HANDLE_BINDING
# The argument models' patterns: the committed schemas' own (`schemas/tools/`), in the end-of-text form pydantic's
# Rust regex engine accepts (`$` there never matches before a final newline, which the schemas' `(?![\s\S])` says).
ASSET_ID: Final = r"^[A-Z][A-Z0-9_-]{0,31}$"
INSTANT: Final = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?(Z|\+00:00)$"


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
    """The `error` object of an envelope; only an unavailable asset-sim is worth a retry (ruling 15)."""
    return {"code": code, "message": message, "retryable": retryable}


def envelope(
    tool_name: str,
    *,
    data: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    observed_at: datetime | None = None,
    truncated: bool = False,
) -> ToolResult:
    """Wrap data or an error in the AM-80 envelope with a fresh request_id. `observed_at` is the database instant the
    answer was decided at (Plan M ruling 3); a refusal before any database unit has none and takes the wall clock."""
    return {
        "tool_name": tool_name,
        "request_id": str(uuid4()),
        "status": "error" if error is not None else "ok",
        "observed_at": stamp(datetime.now(UTC) if observed_at is None else observed_at),
        "truncated": truncated,
        "data": None if error is not None else data,
        "error": error,
    }


def search_response(found: persistence.Procedures) -> ToolResult:
    """The tool's answer from what `search_procedures_scoped` returned; database-free so the contract test can validate
    it. The rank stays behind: the contract has no score, and the model never sees one (docs/retrieval.md). Every
    `retrieved_at` and the envelope's `observed_at` are the instant the definer decided permission at, never the wall
    clock (Plan M ruling 3, Plan L final review M4), and a section cut at the contract's bound sets `truncated`
    (ruling 11)."""
    retrieved_at = stamp(found.retrieved_at)
    results = [
        {
            "evidence_id": hit.evidence_id,
            "document_id": hit.document_id,
            "version": hit.version,
            "section": hit.section,
            "content_sha256": hit.content_sha256,
            "excerpt": hit.excerpt,
            "effective_from": stamp(hit.effective_from),
            "retrieved_at": retrieved_at,
        }
        for hit in found.results
    ]
    return envelope(
        "search_procedures",
        data={"results": results, "retrieval_mode": "lexical", "corpus_version": found.corpus_version},
        observed_at=found.retrieved_at,
        truncated=found.truncated,
    )


def within_scope(tool: ToolName, data: dict[str, Any], scope: persistence.AssetScope, limit: int | None = None) -> bool:
    """asset-sim answered for the run's asset at the instant it was asked to (a status carries exactly `as_of`) and,
    for alerts, for the run's interval, with no alert outside it or after `as_of` and no more than the `limit` asked
    for: what the schema cannot say about the data (ruling 15)."""
    if data.get("asset_id") != scope.asset_id:
        return False
    if tool is not ToolName.GET_RECENT_ALERTS:
        try:
            return datetime.fromisoformat(data["observed_at"]) == scope.as_of
        except (KeyError, TypeError, ValueError):
            return False
    try:
        interval = (datetime.fromisoformat(data["start_at"]), datetime.fromisoformat(data["end_at"]))
        alerts = [(alert["asset_id"], datetime.fromisoformat(alert["occurred_at"])) for alert in data["alerts"]]
    except (KeyError, TypeError, ValueError):
        return False
    if limit is not None and len(alerts) > limit:
        return False
    return interval == (scope.start_at, scope.end_at) and all(
        asset_id == scope.asset_id and scope.start_at <= occurred < scope.end_at and occurred <= scope.as_of
        for asset_id, occurred in alerts
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


def contract_tool(fn: Any) -> Tool:
    """A Tool whose argument model forbids extra keys and refuses lax coercion, and which advertises exactly the
    committed input schema.

    The SDK derives the model from the signature and ignores unknown keys (measured in the Plan D spike); SA:350
    requires the opposite, so the model is subclassed with `extra="forbid"`. `strict` stops lax coercion, so
    `limit="1"` or `limit=True` is refused rather than read as 1. What a client is shown is the file in `schemas/tools/`
    itself (ruling 13), which the worker compares with its own copy; tests/plan_m proves model and file agree.
    """
    tool = Tool.from_function(fn)
    base = tool.fn_metadata.arg_model
    strict: Any = type(
        base.__name__, (base,), {"model_config": ConfigDict(arbitrary_types_allowed=True, extra="forbid", strict=True)}
    )
    tool.fn_metadata.arg_model = strict
    tool.parameters = tool_contracts.input_schema(ToolName(tool.name))
    return tool


@dataclass
class State:
    """Process-wide dependencies the tools and the app share; `session` and `assets` are filled at startup."""

    session: persistence.Session | None
    verifier: Verifier
    assets: assets.AssetSim | None = None


@dataclass(frozen=True)
class Caller:
    """A call past its first unit: the presented handle and the token's `azp`, which every definer binds again."""

    handle: str
    azp: str


def build_server(state: State, *, issuer: str, resource_url: str) -> MCPServer:
    """Assemble the MCP server with bearer auth and the three strict tools, bound to `state`."""

    async def resolve(tool: ToolName, ctx: Context) -> Caller | ToolResult:
        """Unit 1 (erratum 80): the handle resolved for mcp-read and the tool allowed for its job type, run state and
        attempt (`persistence.allowed_tool`), committed before anything else runs. A refusal is the one plain
        `INVALID_HANDLE` envelope (SA:355), on the wall clock: no database instant decided it."""
        token = get_access_token()
        handle = (ctx.headers or {}).get("x-ops-invocation")  # header names arrive lower-case
        if token is None or not handle or state.session is None:
            return envelope(tool.value, error=tool_error("INVALID_HANDLE", "missing invocation handle"))
        try:
            async with state.session.unit() as conn:
                await persistence.resolve_invocation(conn, handle=handle, azp=token.client_id, tool=tool)
        except persistence.HandleRejected as exc:
            return envelope(tool.value, error=tool_error("INVALID_HANDLE", str(exc)))
        return Caller(handle, token.client_id)

    async def scope_of(tool: ToolName, caller: Caller) -> persistence.AssetScope | ToolResult:
        """Unit 2: `asset_scope` resolves the same handle again (a handle released since unit 1 is refused here too),
        re-checks the requester's membership (R028) and returns the run's asset, interval and `as_of`."""
        assert state.session is not None  # resolve() answered only with a session
        try:
            async with state.session.unit() as conn:
                return await persistence.asset_scope(conn, handle=caller.handle, azp=caller.azp)
        except persistence.HandleRejected as exc:
            return envelope(tool.value, error=tool_error("INVALID_HANDLE", str(exc)))

    async def from_asset_sim(
        tool: ToolName, scope: persistence.AssetScope, call: Awaitable[dict[str, Any]], limit: int | None = None
    ) -> ToolResult:
        """asset-sim's data as the tool's result, stamped with `as_of`, or the error envelope of its failure. The
        whole result is validated against the committed contract, and the data against the run's scope, before it
        leaves (ruling 15): asset-sim is a separate service, not a trusted record."""
        try:
            data = await call
        except assets.AssetSimError as exc:
            error = tool_error(exc.code, str(exc), retryable=exc.retryable)
            return envelope(tool.value, error=error, observed_at=scope.as_of)
        truncated = tool is ToolName.GET_RECENT_ALERTS and data.get("next_cursor") is not None  # ruling 10
        doc = envelope(tool.value, data=data, observed_at=scope.as_of, truncated=truncated)
        try:
            tool_contracts.check_result(tool, doc)
        except tool_contracts.ContractViolation:
            pass
        else:
            if within_scope(tool, data, scope, limit):
                return doc
        error = tool_error("UPSTREAM_INVALID", "asset-sim answered outside the contract")
        return envelope(tool.value, error=error, observed_at=scope.as_of)

    def unconfigured(tool: ToolName, scope: persistence.AssetScope) -> ToolResult:
        """No asset-sim client (only before the lifespan ran): answered as an unreachable asset-sim."""
        error = tool_error("UNAVAILABLE", "asset-sim is not configured", retryable=True)
        return envelope(tool.value, error=error, observed_at=scope.as_of)

    async def get_asset_status(
        asset_id: Annotated[str, Field(max_length=32, pattern=ASSET_ID)],
        ctx: Context,
    ) -> ToolResult:
        """The run's asset's synthetic status as of the database instant (AM-15 read tool, T16)."""
        name = ToolName.GET_ASSET_STATUS
        caller = await resolve(name, ctx)
        if not isinstance(caller, Caller):
            return caller
        scope = await scope_of(name, caller)
        if not isinstance(scope, persistence.AssetScope):
            return scope
        if asset_id != scope.asset_id:  # before asset-sim is asked anything (ruling 8)
            error = tool_error("ASSET_OUT_OF_SCOPE", "only the run's own asset may be read")
            return envelope(name.value, error=error, observed_at=scope.as_of)
        if state.assets is None:
            return unconfigured(name, scope)
        return await from_asset_sim(name, scope, state.assets.status(scope))

    async def get_recent_alerts(
        asset_id: Annotated[str, Field(max_length=32, pattern=ASSET_ID)],
        start_at: Annotated[str, Field(pattern=INSTANT)],
        end_at: Annotated[str, Field(pattern=INSTANT)],
        limit: Annotated[int, Field(ge=1, le=100)],
        ctx: Context,
        # Absent means the first page. The empty default is never validated (pydantic leaves defaults alone), so a
        # caller cannot send "" or null; the advertised schema is the committed file, which has no default.
        cursor: Annotated[str, Field(min_length=1, max_length=200)] = "",
    ) -> ToolResult:
        """The run's asset's alerts in the run's fixed `[start_at, end_at)`, at or before the database instant, one
        page at a time (AM-15 read tool, T16)."""
        name = ToolName.GET_RECENT_ALERTS
        caller = await resolve(name, ctx)
        if not isinstance(caller, Caller):
            return caller
        scope = await scope_of(name, caller)
        if not isinstance(scope, persistence.AssetScope):
            return scope
        if asset_id != scope.asset_id:
            error = tool_error("ASSET_OUT_OF_SCOPE", "only the run's own asset may be read")
            return envelope(name.value, error=error, observed_at=scope.as_of)
        try:
            asked = (datetime.fromisoformat(start_at), datetime.fromisoformat(end_at))
        except ValueError:  # the pattern passed but the date does not exist (February 30): not the run's interval
            asked = None
        if asked != (scope.start_at, scope.end_at):  # compared as instants, so `+00:00` and `Z` agree (ruling 9)
            error = tool_error("INTERVAL_OUT_OF_SCOPE", "only the run's own interval may be read")
            return envelope(name.value, error=error, observed_at=scope.as_of)
        if state.assets is None:
            return unconfigured(name, scope)
        page = state.assets.alerts(scope, limit=limit, cursor=cursor or None)
        return await from_asset_sim(name, scope, page, limit)

    async def search_procedures(
        query: Annotated[str, Field(min_length=1, max_length=500)],
        limit: Annotated[int, Field(ge=1, le=8)],
        mode: Literal["lexical", "vector_exact"],
        ctx: Context,
        # Absent means "any asset". The empty default is never validated (pydantic leaves defaults alone), so a
        # caller cannot send "" or null (Plan L ruling 11); the advertised schema is the committed file.
        asset_type: Annotated[str, Field(min_length=1, max_length=40)] = "",
    ) -> ToolResult:
        """Lexical search over the calling run's tenant's approved, effective procedure sections (AM-15 read tool),
        through `search_procedures_scoped` (T17)."""
        name = ToolName.SEARCH_PROCEDURES
        caller = await resolve(name, ctx)
        if not isinstance(caller, Caller):
            return caller
        if mode != "lexical":
            # TODO(T16): translate vector_exact to mode=vector once T18 stores embeddings (erratum 3).
            return envelope(name.value, error=tool_error("UNSUPPORTED_MODE", "vector_exact arrives with T18"))
        assert state.session is not None  # resolve() answered only with a session
        # A second unit, after the resolution committed (erratum 80): the definer resolves the same handle again, so a
        # handle released in between is refused here too, and the tenant comes from the handle, never an argument.
        try:
            async with state.session.unit() as conn:
                found = await persistence.search_procedures(
                    conn,
                    handle=caller.handle,
                    azp=caller.azp,
                    query=query,
                    asset_type=asset_type or None,
                    limit=limit,
                )
        except persistence.HandleRejected as exc:
            return envelope(name.value, error=tool_error("INVALID_HANDLE", str(exc)))
        except persistence.Refused as exc:
            return envelope(name.value, error=tool_error("REFUSED", exc.code))
        return search_response(found)

    return MCPServer(
        name="mcp-read",
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(issuer), resource_server_url=AnyHttpUrl(resource_url), validate_token_resource=True
        ),
        token_verifier=McpVerifier(state.verifier, resource_url),
        tools=[contract_tool(get_asset_status), contract_tool(get_recent_alerts), contract_tool(search_procedures)],
    )


def build_app(server: MCPServer, state: State) -> Starlette:
    """Mount the MCP transport beside health routes and own the database session, the asset-sim client and key
    loading."""
    mcp_app = server.streamable_http_app(streamable_http_path=MCP_PATH, stateless_http=True, json_response=True)

    @contextlib.asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        """Open the session, the asset-sim client and the keys, run the mounted app's lifespan, then close them."""
        if state.session is None:
            conn = await persistence.connect(settings.app_postgres(Role.MCP_READ))
            try:
                await persistence.assert_clock_profile(conn, settings.profile())
                await persistence.assert_function_text(conn, *HANDLE_BINDING)
                await persistence.assert_function_text(conn, *persistence.GOVERNED_CORPUS)  # 0011 (T17)
                await persistence.assert_function_text(conn, *persistence.ASSET_SCOPE)  # 0012 (T16)
                await persistence.assert_function_text(conn, *persistence.SEARCH_INSTANT)  # 0012 (T16)
            except BaseException:  # a failed start must leak no connection, and a re-entered lifespan re-asserts
                await conn.close()
                raise
            state.session = persistence.Session(conn)
        # A mounted sub-app's lifespan never runs on its own; the session manager lives in it (measured).
        try:
            if state.assets is None:  # inside the try: a missing secret file must close the connection too
                state.assets = assets.HttpAssetSim.from_settings()  # mcp-read's own token (rulings 6 and 8)
            if not state.verifier.ready:  # inside the try: a failed JWKS load must close the connection too
                await state.verifier.load_keys()
            async with mcp_app.router.lifespan_context(mcp_app):
                yield
        finally:
            # Nested, so a close that raises cannot leave the other open; a closed client is never left in the state.
            try:
                if state.assets is not None:
                    try:
                        await state.assets.aclose()
                    finally:
                        state.assets = None
            finally:
                await state.session.conn.close()

    async def live(_: Request) -> JSONResponse:
        """Liveness: the process is up."""
        return JSONResponse({"status": "live"})

    async def ready(_: Request) -> JSONResponse:
        """Readiness: keys loaded and the database answers (asset-sim is a dependency of a call, not of readiness)."""
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
    state = State(session=None, verifier=read_verifier(kc, urls))
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

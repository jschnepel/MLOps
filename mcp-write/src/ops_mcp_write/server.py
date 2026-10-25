"""mcp-write: the authenticated write server (ADR-0003; AM-13 attempt protocol; SA:557 token checks).

Three tools, and the grant, every destination call and every outcome happen here, never in the worker:
`create_incident` for execute jobs (and a recover job's redispatch of an unsent attempt), and the recovery tools
`get_incident_receipt` and `abort_incident` for recover jobs only (T47). Every call resolves its `X-Ops-Invocation`
handle first: the server, the token's `azp`, expiry, the lease fence, the handle's open job, and the job type's
tools, run states and attempt states (`persistence.allowed_tool`). Only the worker's workload token is accepted here,
so the recovery tools are listed to that caller alone and refused for every handle but a recover job's (BS:393).
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
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
from ops_core import persistence, redaction, settings, tool_contracts
from ops_core.jobs import Tool as ToolName
from ops_core.mcp_protocol import MCP_PATH, ProtocolVersionGuard
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
    """The tool error for a definer's refusal: MEMBERSHIP_STALE is the one grant refusal the worker retries (Plan F
    ruling 14); ABORT_NOT_DUE (an abort before a cancel or the dispatch deadline) is retryable once either arrives
    (Plan K ruling 3); NOT_REDISPATCHABLE (a recover job asking to re-send a SENT attempt, SA:345) is final. Like every
    refusal before a destination call, none names an action (SA:355)."""
    if code == "MEMBERSHIP_STALE":
        return tool_error("GRANT_DEFERRED", f"grant deferred: {code}", retryable=True)
    if code == "ABORT_NOT_DUE":
        return tool_error(code, "abort not due: not cancelled and before the dispatch deadline", retryable=True)
    if code == "NOT_REDISPATCHABLE":
        return tool_error(code, "a recover job redispatches only an attempt that was never sent")
    return tool_error("GRANT_REFUSED", f"grant refused: {code}")


def blocked_error(blocked: execution.GrantBlocked) -> dict[str, Any]:
    """The tool error for a grant the gate refused with a committed BLOCKED_REVIEW (T21, Plan R ruling 11): the code
    every final grant refusal has, plus `reason`, the run's AM-10 reason; nothing was granted or sent (SA:355)."""
    return {**tool_error("GRANT_REFUSED", f"grant refused: {blocked.reason.value}"), "reason": blocked.reason.value}


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
    """The SDK's TokenVerifier protocol: None means 401. The SDK re-checks `expires_at`, consistently with PyJWT.

    A token whose `aud` lacks this server's resource URL is refused here, whatever audience the wrapped verifier was
    configured with, and only then is `resource` stamped with that URL (mcp-read's rule, Plan J ruling 2; Plan K
    ruling 11). The SDK's own resource check (`validate_token_resource`) stays on as a second layer; it cannot refuse
    anything while the stamp is this server's own URL, and would decide only if the stamp ever came from the token.
    """

    def __init__(self, verifier: Verifier, resource_url: str) -> None:
        """Adapt a token verifier to the SDK's bearer-auth hook; `resource_url` is this server's audience."""
        self._verifier = verifier
        self._resource = resource_url

    async def verify_token(self, token: str) -> AccessToken | None:
        """Return the access token for a valid bearer token, None (401) otherwise."""
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
    """A Tool whose argument model forbids extra keys and which advertises exactly the committed input schema.

    The SDK derives the model from the signature and ignores unknown keys (measured in the Plan D spike); SA:350
    requires the opposite, so the model is subclassed with `extra="forbid"`. `strict` stops lax coercion, so
    `limit="1"` or `limit=True` is refused rather than read as 1. What a client is shown is the file in
    `schemas/tools/` itself, which the worker compares with its own copy before every write call (T21, Plan R ruling
    17; mcp-read's rule since T16).
    """
    tool = Tool.from_function(fn)
    base = tool.fn_metadata.arg_model
    strict: Any = type(
        base.__name__, (base,), {"model_config": ConfigDict(arbitrary_types_allowed=True, extra="forbid", strict=True)}
    )
    tool.fn_metadata.arg_model = strict
    tool.parameters = tool_contracts.input_schema(ToolName(tool.name))
    return tool


def serve_app(app: ASGIApp, port: int) -> None:
    """Serve with uvicorn programmatically on a selector loop (ruling 23: `uvicorn.run` picks the Proactor loop on
    Windows and psycopg async refuses it)."""
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", log_config=None))
    if sys.platform == "win32":
        asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(server.serve())


def outcome_envelope(outcome: ActionOutcome, tool_name: str = ToolName.CREATE_INCIDENT.value) -> ToolResult:
    """`ok` only wraps SUCCEEDED (R083); every other outcome is `status=outcome` with `data.action_id` (SA:352). The
    data is the ActionOutcome shape `create_incident` and `get_incident_receipt` share (BS:393's minimal outcome)."""
    data = outcome.model_dump(mode="json")
    doc = envelope(tool_name, data=data)
    if outcome.status is not ToolOutcome.SUCCEEDED:
        doc["status"] = "outcome"
    return doc


def abort_envelope(outcome: ActionOutcome) -> ToolResult:
    """`abort_incident`'s data (SA:356): the action, the outcome and the destination's receipt or tombstone, nothing
    else (the tombstone carries the destination's reason). `ok` only for SUCCEEDED, an abort that met the receipt
    already there; UNKNOWN and CONFLICT carry neither (Plan K, the abort data's added outcomes)."""
    data = {
        "action_id": str(outcome.action_id),
        "outcome": outcome.status.value,
        "receipt": None if outcome.receipt is None else outcome.receipt.model_dump(mode="json"),
        "tombstone": None if outcome.tombstone is None else outcome.tombstone.model_dump(mode="json"),
    }
    doc = envelope(ToolName.ABORT_INCIDENT.value, data=data)
    if outcome.status is not ToolOutcome.SUCCEEDED:
        doc["status"] = "outcome"
    return doc


@dataclass
class State:
    """Process-wide dependencies the tool and the app share; `deps` is filled at startup."""

    deps: execution.Deps | None
    verifier: Verifier


# A tool's work once its handle resolved: (deps, the raw handle, the token's azp) -> the outcome.
Work = Callable[[execution.Deps, str, str], Awaitable[ActionOutcome]]
# strict=False on this one field: the model is strict, and strict UUID validation refuses the string a client sends.
ProposalId = Annotated[UUID, Field(strict=False)]


def build_server(state: State, *, issuer: str, resource_url: str) -> MCPServer:
    """Assemble the MCP server with bearer auth and the three strict write tools, bound to `state`."""

    async def answer(tool: ToolName, ctx: Context, work: Work) -> ActionOutcome | ToolResult:
        """Resolve the handle for `tool` before any work (SA:459; Plan K ruling 26), then do it. A refusal before
        anything reached the destination is a plain error envelope without an action id (SA:355)."""
        token = get_access_token()
        handle = (ctx.headers or {}).get("x-ops-invocation")
        if token is None or not handle or state.deps is None:
            return envelope(tool.value, error=tool_error("INVALID_HANDLE", "missing invocation handle"))
        try:
            async with state.deps.session.unit() as conn:
                await persistence.resolve_invocation(conn, handle=handle, azp=token.client_id, tool=tool)
            return await work(state.deps, handle, token.client_id)
        except persistence.HandleRejected as exc:
            return envelope(tool.value, error=tool_error("INVALID_HANDLE", str(exc)))
        except execution.GrantBlocked as exc:
            return envelope(tool.value, error=blocked_error(exc))
        except persistence.Refused as exc:
            return envelope(tool.value, error=refusal_error(exc.code))
        except persistence.NotFound:
            return envelope(tool.value, error=tool_error("NOT_FOUND", "run not found"))
        except persistence.VersionConflict:
            # Only mark_sent raises this here, before anything is sent: a recover job redispatching an unsent attempt
            # while its run is not EXECUTING (redispatch from OUTCOME_UNKNOWN is T22's). After a destination call
            # execution.py answers UNKNOWN instead (AM-13).
            return envelope(tool.value, error=tool_error("STALE_RUN", "run is no longer executing"))
        # HashMismatch is not mapped: only record_outcome raises it, after the destination answered, where execution.py
        # answers UNKNOWN (tests/plan_k/test_migration_0010.py pins that no earlier definer can; Plan K ruling 20).
        # AuthorityViolation stays unmapped on purpose: it is a deployment error (the role lacks a grant), so the raw
        # tool error and the worker's re-queue are the right outcome.

    async def create_incident(proposal_id: ProposalId, ctx: Context) -> ToolResult:
        """Grant, dispatch and record the approved proposal's incident (AM-13 §2, AM-20.3 grant_execution)."""

        async def work(deps: execution.Deps, handle: str, azp: str) -> ActionOutcome:
            return await execution.create_incident(deps, handle=handle, azp=azp, proposal_id=proposal_id)

        result = await answer(ToolName.CREATE_INCIDENT, ctx, work)
        return outcome_envelope(result) if isinstance(result, ActionOutcome) else result

    async def get_incident_receipt(proposal_id: ProposalId, ctx: Context) -> ToolResult:
        """Recover jobs only: the outcome of the action already granted for this proposal, from the destination's
        restricted lookup (BS:393). Creates nothing."""

        async def work(deps: execution.Deps, handle: str, azp: str) -> ActionOutcome:
            return await execution.get_incident_receipt(deps, handle=handle, azp=azp, proposal_id=proposal_id)

        result = await answer(ToolName.GET_INCIDENT_RECEIPT, ctx, work)
        return (
            outcome_envelope(result, ToolName.GET_INCIDENT_RECEIPT.value)
            if isinstance(result, ActionOutcome)
            else result
        )

    async def abort_incident(proposal_id: ProposalId, ctx: Context) -> ToolResult:
        """Recover jobs only: abort the action already granted for this proposal once it is cancelled or past its
        dispatch deadline; the destination answers with a tombstone or the receipt that already stands (SA:241-242)."""

        async def work(deps: execution.Deps, handle: str, azp: str) -> ActionOutcome:
            return await execution.abort_incident(deps, handle=handle, azp=azp, proposal_id=proposal_id)

        result = await answer(ToolName.ABORT_INCIDENT, ctx, work)
        return abort_envelope(result) if isinstance(result, ActionOutcome) else result

    return MCPServer(
        name="mcp-write",
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(issuer), resource_server_url=AnyHttpUrl(resource_url), validate_token_resource=True
        ),
        token_verifier=McpVerifier(state.verifier, resource_url),
        tools=[strict_tool(create_incident), strict_tool(get_incident_receipt), strict_tool(abort_incident)],
    )


def build_app(server: MCPServer, state: State) -> Starlette:
    """Mount the MCP transport beside health routes and own the session, HTTP client and key loading."""
    mcp_app = server.streamable_http_app(streamable_http_path=MCP_PATH, stateless_http=True, json_response=True)

    @contextlib.asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        """Build the write dependencies and load keys, run the mounted app's lifespan, then close both resources."""
        if state.deps is None:
            kc = settings.keycloak()
            conn = await persistence.connect(settings.app_postgres(Role.MCP_EXEC))
            try:
                await persistence.assert_clock_profile(conn, settings.profile())
                # Revision 0007: mark_sent and record_outcome take the raw handle (T13); model_permit marks it.
                await persistence.assert_relation(conn, "app.model_permit")
                # Revision 0009: without the handle's job binding this server would resolve execute handles whose job
                # is another run's or finished, as 0007 did, so it refuses to start, as mcp-read does (T15).
                await persistence.assert_function_text(conn, *persistence.HANDLE_BINDING)
                # Revision 0010: the definers this server calls take the token's azp, and request_abort exists (T47).
                await persistence.assert_function_text(conn, *persistence.WRITE_PATH)
                # Revision 0016: the grant applies the asset guard and returns a committed refusal (T21).
                await persistence.assert_function_text(conn, *persistence.GRANT_GUARD)
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
        routes=[
            Route("/health/live", live),
            Route("/health/ready", ready),
            # The version rule runs before the SDK app and its bearer auth (AM-30, Plan J ruling 4).
            Mount("/", app=ProtocolVersionGuard(mcp_app)),
        ],
        lifespan=lifespan,
    )


def write_verifier(kc: settings.Keycloak, urls: settings.Urls) -> TokenVerifier:
    """mcp-write's token checks (SA:557; mcp-read's since Plan J, Plan K ruling 11): the realm's issuer and keys, this
    server's resource URL as the audience, the worker's client (`settings.workload_client_id`, ruling 12) as the only
    `azp`, and an access token's `typ` claim. `production_app` builds its verifier here, and the unit tests build
    theirs here too, so they pin the wiring that runs."""
    return TokenVerifier(
        issuer=kc.issuer,
        audience=urls.mcp_write_resource,
        allowed_azp=frozenset({settings.workload_client_id()}),
        jwks_url=kc.jwks_url,
        token_type="Bearer",  # an access token: Keycloak's ID and refresh tokens carry another `typ`
    )


def production_app() -> Starlette:
    """The app wired from the environment and secret files, as `python -m ops_mcp_write` runs it."""
    kc = settings.keycloak()
    urls = settings.urls()
    state = State(deps=None, verifier=write_verifier(kc, urls))
    return build_app(build_server(state, issuer=kc.issuer, resource_url=urls.mcp_write_resource), state)


def serve() -> None:
    """Entry point: serve the production app on OPS_MCP_WRITE_PORT (default 8082)."""
    # The redaction filter must sit on the root handler before the first log line (T11 note 4).
    redaction.install()
    serve_app(production_app(), settings.env_int("OPS_MCP_WRITE_PORT", 8082))

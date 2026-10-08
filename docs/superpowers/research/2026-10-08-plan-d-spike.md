# Plan D spike: measured library behaviour for the walking skeleton

Date: 2026-10-08. Branch `plan-c`. This was a throwaway spike. Every script lives in `<scratch>` (the session scratchpad `spike/` directory) and ran against the live dev stack (`scripts/bootstrap_dev.py up`). Nothing in the repository was edited, and `uv lock` ran only in a copy of the workspace (`<scratch>/ws`). No secret or token appears below. Scripts read the secret files from `OPS_SECRETS_DIR` and print only claim names and the non-sensitive claims `azp`, `iss`, `aud`, `typ` and `preferred_username`. The JWKS `kid` is a public key id.

Environment: venv `<venv>` (`uv venv --python 3.13`, giving CPython 3.13.13), installed with `uv pip install "mcp==2.3.0" fastapi uvicorn "psycopg[binary]" "pyjwt[crypto]" alembic sqlalchemy httpx2 httpx`. Every script was run from `<scratch>` as `<venv>/Scripts/python.exe -W always <script>`, so deprecation warnings would show. None appeared in measurements 1–6. The only `MCPDeprecationWarning` seen came from a deliberate probe (2, gotcha 10).

## Summary

| # | Measurement | Result |
|---|---|---|
| 1 | PyJWT + Keycloak JWKS (fetched with httpx2, loaded into a `PyJWKSet`, key looked up by kid) | **works** |
| 2 | MCP 2.3.0 server: bearer auth, streamable HTTP, stateless JSON responses, health routes; client with custom headers | **works**, with gotchas: result fields are snake_case; `additionalProperties:false` is absent by default; a 401 reaches the client as `MCPError(-32603)`; compose needs a Host allowlist |
| 3 | psycopg 3 async (SKIP LOCKED lease, ON CONFLICT, bytea, jsonb, uuid, timestamptz) | **works**; on Windows it needs a `SelectorEventLoop` |
| 4 | Alembic driven from Python (`Config()` with no ini, URL from an env variable, idempotent upgrade, LOGIN role with a password) | **works**; a bind parameter in `CREATE ROLE` fails *and leaks the password into `str(exc)`*; two safe ways shown |
| 5 | `uvicorn.Server.serve()` as a task beside a polling task | **works**; `should_exit=True` shuts it down in about 0.15 s |
| 6 | FastAPI bearer dependency, 401 `{"code":"UNAUTHENTICATED",...}` | **works**; `aud=ops-api` fails for every token issued today, so the realm needs an audience mapper |

Installed versions (`uv pip list`; the packages that matter here): mcp 2.3.0, mcp-types 2.3.0, fastapi 0.142.4, starlette 1.7.0, uvicorn 0.54.0, psycopg 3.3.6 (+ psycopg-binary 3.3.6), sqlalchemy 2.1.4, alembic 1.20.0, pyjwt 2.15.1, cryptography 50.0.2, httpx2 2.13.1 (+ httpcore2 2.13.1), httpx 0.28.1 (installed only because the task asked for it), sse-starlette 3.5.0, python-multipart 0.0.32, anyio 4.15.1, pydantic 2.13.5, opentelemetry-api 1.45.1, jsonschema 4.26.0, pywin32 312, tzdata 2026.5.

Every script uses two shared helpers: `kc.py`, a verbatim copy of `tests/plan_b/live/kc.py`, and `common.py`:

```python
"""Shared spike helpers: secret files and Keycloak tokens. Never prints a secret or token."""
from __future__ import annotations

import os
from pathlib import Path

import kc

KC_BASE = "http://localhost:18080"
ISSUER = f"{KC_BASE}/realms/ops-dev"
JWKS_URL = f"{ISSUER}/protocol/openid-connect/certs"
MCP_READ_AUD = "http://mcp-read:8081/mcp"


def secrets_dir() -> Path:
    env = Path("<repo>/.env").read_text().splitlines()
    for line in env:
        if line.startswith("OPS_SECRETS_DIR="):
            return Path(line.split("=", 1)[1])
    return Path(os.environ["LOCALAPPDATA"]) / "ops-copilot" / "secrets"


def secret(name: str) -> str:
    return (secrets_dir() / name).read_text()


def worker_token() -> str:
    return kc.token_client_credentials(KC_BASE, "ops-worker", secret("kc_client_secret_ops_worker"))["access_token"]


def mcp_write_token() -> str:
    return kc.token_client_credentials(KC_BASE, "ops-mcp-write", secret("kc_client_secret_ops_mcp_write"))["access_token"]


def alex_token() -> str:
    return kc.token_password(KC_BASE, "ops-dev-direct", "alex", secret("kc_persona_alex_password"))["access_token"]


def pg_conninfo(dbname: str = "ops") -> str:
    from psycopg.conninfo import make_conninfo

    return make_conninfo(host="127.0.0.1", port=15432, user="ops", dbname=dbname, password=secret("postgres_password"))
```

## 1. Token verification: PyJWT + Keycloak JWKS

Working calls:
- JWKS: `httpx2.AsyncClient().get(".../protocol/openid-connect/certs")`, then `jwt.PyJWKSet.from_dict(resp.json())`. The realm publishes **two** keys, one `RSA-OAEP`/`enc` and one `RS256`/`sig`. `from_dict` accepts both, and the kid lookup selects the signing key.
- Kid lookup: `jwks[jwt.get_unverified_header(token)["kid"]]`. `PyJWKSet.__getitem__` returns a `PyJWK`. An unknown kid raises `KeyError('keyset has no key for kid: ...')`, which is the natural point to refetch on key rotation.
- `jwt.decode(token, pyjwk, algorithms=["RS256"], audience="http://mcp-read:8081/mcp", issuer="http://localhost:18080/realms/ops-dev")` works whether the key argument is the `PyJWK` or `pyjwk.key`. `options={"require": ["exp","iat","iss","aud","sub","azp"]}` also passes for the worker token.
- `jwt.decode` returns the full claim dict. For the worker it contains `azp == "ops-worker"`, and `aud` is a **list**: `['http://mcp-read:8081/mcp', 'http://mcp-write:8082/mcp', 'account']`.

Token facts. The header is `alg=RS256`, `typ=JWT`, `kid=542Vwmq5TOqCEYtdGoC5N0amUEqxPT_BhFgX-GnRin8`; workload and persona tokens use the same key.
- Worker token (client credentials), claim names: `acr aud azp clientAddress clientHost client_id email_verified exp iat iss jti preferred_username realm_access resource_access scope sub typ`. `preferred_username` is `service-account-ops-worker`.
- alex token (password grant via `ops-dev-direct`), claim names: `acr azp email email_verified exp family_name given_name iat iss jti name preferred_username realm_access scope sid sub typ`. It has **no `aud`**; `azp` is `ops-dev-direct`.

Failure modes. All are subclasses of `jwt.PyJWTError`, importable from `jwt` or `jwt.exceptions`.
- Wrong audience: `InvalidAudienceError("Audience doesn't match")`.
- A persona token (no `aud`) checked against any audience raises **`MissingRequiredClaimError('Token is missing the "aud" claim')`**, not `InvalidAudienceError`. Catch `jwt.PyJWTError` (or `InvalidTokenError`), not just the audience error.
- A token that has an `aud` but is decoded without the `audience=` kwarg raises `InvalidAudienceError("Invalid audience")`. Either pass `audience=` or set `options={"verify_aud": False}`.
- Wrong issuer (`http://keycloak:8080/...`): `InvalidIssuerError`. `iss` is always the `localhost:18080` form, even from containers (plan-d-inputs 3.2). Verifiers inside containers must therefore expect that string while fetching the JWKS from `http://keycloak:8080`.
- `algorithms=["HS256"]` raises `InvalidAlgorithmError`. A tampered signature raises `InvalidSignatureError`.

Script `m1_jwt.py`:

```python
"""M1: verify Keycloak tokens with PyJWT, JWKS fetched by httpx2 (no network inside PyJWT)."""
import asyncio

import httpx2
import jwt

import common
import kc

SAFE = {"azp", "iss", "aud", "typ", "preferred_username"}


async def fetch_jwks() -> jwt.PyJWKSet:
    async with httpx2.AsyncClient(timeout=10) as client:
        resp = await client.get(common.JWKS_URL)
        resp.raise_for_status()
        data = resp.json()
    print("jwks keys:", [(k.get("kid"), k.get("alg"), k.get("use")) for k in data["keys"]])
    return jwt.PyJWKSet.from_dict(data)


def key_for(jwks: jwt.PyJWKSet, token: str) -> jwt.PyJWK:
    kid = jwt.get_unverified_header(token)["kid"]
    return jwks[kid]  # PyJWKSet.__getitem__(kid) -> PyJWK; KeyError if absent


def describe(label: str, token: str) -> None:
    hdr = jwt.get_unverified_header(token)
    c = kc.claims(token)
    print(f"[{label}] header alg={hdr['alg']} typ={hdr.get('typ')} kid={hdr.get('kid')}")
    print(f"[{label}] claim names: {sorted(c)}")
    print(f"[{label}] safe claims: { {k: c[k] for k in sorted(c) if k in SAFE} }")


async def main() -> None:
    jwks = await fetch_jwks()
    wt, at, mw = common.worker_token(), common.alex_token(), common.mcp_write_token()
    describe("worker", wt)
    describe("alex", at)

    key = key_for(jwks, wt)
    print("PyJWK type:", type(key).__name__, "key_type:", key.key_type, "algorithm_name:", key.algorithm_name)
    out = jwt.decode(wt, key, algorithms=["RS256"], audience=common.MCP_READ_AUD, issuer=common.ISSUER)
    print("decode(worker, aud=mcp-read) OK; azp =", out["azp"], "aud =", out["aud"])
    # A PyJWK can also be passed as key=key.key (the cryptography object):
    out2 = jwt.decode(wt, key.key, algorithms=["RS256"], audience=common.MCP_READ_AUD, issuer=common.ISSUER)
    print("decode with key.key also OK:", out2["azp"] == out["azp"])
    # Required claims option
    jwt.decode(wt, key, algorithms=["RS256"], audience=common.MCP_READ_AUD, issuer=common.ISSUER,
               options={"require": ["exp", "iat", "iss", "aud", "sub", "azp"]})
    print("decode with options.require=[exp,iat,iss,aud,sub,azp] OK")

    cases = [
        ("worker, wrong audience 'ops-api'", wt, dict(audience="ops-api", issuer=common.ISSUER)),
        ("worker, wrong issuer", wt, dict(audience=common.MCP_READ_AUD, issuer="http://keycloak:8080/realms/ops-dev")),
        ("alex (no aud), audience=mcp-read", at, dict(audience=common.MCP_READ_AUD, issuer=common.ISSUER)),
        ("alex (no aud), audience=ops-api", at, dict(audience="ops-api", issuer=common.ISSUER)),
        ("ops-mcp-write (aud incident-sim), audience=mcp-read", mw, dict(audience=common.MCP_READ_AUD, issuer=common.ISSUER)),
        ("worker, algorithms=['HS256']", wt, dict(audience=common.MCP_READ_AUD, issuer=common.ISSUER, algorithms=["HS256"])),
        ("worker, tampered signature", wt[:-4] + ("AAAA" if not wt.endswith("AAAA") else "BBBB"),
         dict(audience=common.MCP_READ_AUD, issuer=common.ISSUER)),
        ("worker, no audience= kwarg", wt, dict(issuer=common.ISSUER)),
    ]
    for label, tok, kw in cases:
        algs = kw.pop("algorithms", ["RS256"])
        try:
            jwt.decode(tok, key_for(jwks, tok), algorithms=algs, **kw)
            print(f"{label}: ACCEPTED")
        except jwt.PyJWTError as e:
            print(f"{label}: {type(e).__module__}.{type(e).__name__}: {e}")
    print("alex with options verify_aud=False:",
          jwt.decode(at, key_for(jwks, at), algorithms=["RS256"], issuer=common.ISSUER,
                     options={"verify_aud": False})["azp"])
    try:
        jwks["no-such-kid"]
    except KeyError as e:
        print("unknown kid -> KeyError:", e)


asyncio.run(main())
```

Output (`m1.out`, complete):

```text
jwks keys: [('BuY1G_ssRtkL6Nvod99ADclfliV7S0DjI_0rzTcuFAo', 'RSA-OAEP', 'enc'), ('542Vwmq5TOqCEYtdGoC5N0amUEqxPT_BhFgX-GnRin8', 'RS256', 'sig')]
[worker] header alg=RS256 typ=JWT kid=542Vwmq5TOqCEYtdGoC5N0amUEqxPT_BhFgX-GnRin8
[worker] claim names: ['acr', 'aud', 'azp', 'clientAddress', 'clientHost', 'client_id', 'email_verified', 'exp', 'iat', 'iss', 'jti', 'preferred_username', 'realm_access', 'resource_access', 'scope', 'sub', 'typ']
[worker] safe claims: {'aud': ['http://mcp-read:8081/mcp', 'http://mcp-write:8082/mcp', 'account'], 'azp': 'ops-worker', 'iss': 'http://localhost:18080/realms/ops-dev', 'preferred_username': 'service-account-ops-worker', 'typ': 'Bearer'}
[alex] header alg=RS256 typ=JWT kid=542Vwmq5TOqCEYtdGoC5N0amUEqxPT_BhFgX-GnRin8
[alex] claim names: ['acr', 'azp', 'email', 'email_verified', 'exp', 'family_name', 'given_name', 'iat', 'iss', 'jti', 'name', 'preferred_username', 'realm_access', 'scope', 'sid', 'sub', 'typ']
[alex] safe claims: {'azp': 'ops-dev-direct', 'iss': 'http://localhost:18080/realms/ops-dev', 'preferred_username': 'alex', 'typ': 'Bearer'}
PyJWK type: PyJWK key_type: RSA algorithm_name: RS256
decode(worker, aud=mcp-read) OK; azp = ops-worker aud = ['http://mcp-read:8081/mcp', 'http://mcp-write:8082/mcp', 'account']
decode with key.key also OK: True
decode with options.require=[exp,iat,iss,aud,sub,azp] OK
worker, wrong audience 'ops-api': jwt.exceptions.InvalidAudienceError: Audience doesn't match
worker, wrong issuer: jwt.exceptions.InvalidIssuerError: Invalid issuer
alex (no aud), audience=mcp-read: jwt.exceptions.MissingRequiredClaimError: Token is missing the "aud" claim
alex (no aud), audience=ops-api: jwt.exceptions.MissingRequiredClaimError: Token is missing the "aud" claim
ops-mcp-write (aud incident-sim), audience=mcp-read: jwt.exceptions.InvalidAudienceError: Audience doesn't match
worker, algorithms=['HS256']: jwt.exceptions.InvalidAlgorithmError: The specified alg value is not allowed
worker, tampered signature: jwt.exceptions.InvalidSignatureError: Signature verification failed
worker, no audience= kwarg: jwt.exceptions.InvalidAudienceError: Invalid audience
alex with options verify_aud=False: ops-dev-direct
unknown kid -> KeyError: 'keyset has no key for kid: no-such-kid'
```

## 2. MCP 2.3.0 server with bearer auth, and a client with custom headers

### Working imports and signatures (measured)

- `from mcp.server.mcpserver import MCPServer, Context`
- `from mcp.server.mcpserver.tools.base import Tool` (needed only for the strict-schema helper)
- `from mcp.server.auth.settings import AuthSettings`
- `from mcp.server.auth.provider import AccessToken`. The `TokenVerifier` Protocol lives in the same module; any class with `async def verify_token(self, token: str) -> AccessToken | None` satisfies it.
- `from mcp.server.auth.middleware.auth_context import get_access_token`. Called inside a tool, it returns the `AccessToken` your verifier built.
- `from mcp.server.transport_security import TransportSecuritySettings`
- `MCPServer(name="spike", auth=AuthSettings(issuer_url=ISSUER, resource_server_url="http://mcp-read:8081/mcp", validate_token_resource=False), token_verifier=KeycloakVerifier(...), tools=[...])` raised no warnings. Setting `auth` without a verifier raises `ValueError: Must specify either auth_server_provider or token_verifier when auth is enabled`.
- Tool registration: `server.add_tool(fn)` (equivalent to `@server.tool()`), or `MCPServer(..., tools=[Tool.from_function(fn)])` for a tool built in advance.
- `server.streamable_http_app(streamable_http_path="/mcp", stateless_http=True, json_response=True, transport_security=ts)` returns a `Starlette`. If you mount it under an outer Starlette (`Mount("/", app=mcp_app)`), **you must forward its lifespan** (`async with mcp_app.router.lifespan_context(mcp_app): yield`). A mounted sub-app's lifespan never runs, so without this the session manager would not start. The app was served with `uvicorn.run(app, host="127.0.0.1", port=8081, log_level="warning")`. An alternative, `@server.custom_route("/health/live", methods=["GET"])`, exists and is documented as unauthenticated; it was not measured.
- Client: `from mcp import Client` and `from mcp.client.streamable_http import streamable_http_client`; then `async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {tok}", "X-Ops-Invocation": "spike-handle"}) as hc: async with Client(streamable_http_client(URL, http_client=hc), mode="2026-07-28") as client:`, followed by `await client.list_tools()` and `await client.call_tool(name, args)`.
- Inside the tool, `ctx.headers.get("x-ops-invocation")` returned `"spike-handle"` (header names arrive lower-case), and `get_access_token().client_id` returned `"ops-worker"`.

### Gotchas

1. **Result and schema fields are snake_case in mcp-types 2.3.0**: `Tool.input_schema`, `Tool.output_schema`, `CallToolResult.structured_content`, `CallToolResult.is_error`. The v1 names (`inputSchema`, `structuredContent`, `isError`) raise `AttributeError` (measured).
2. **Input schema.** The generated `input_schema` has `required: [query, limit, mode]` and `enum: [lexical, vector_exact]` for the `Literal`, but **no `additionalProperties: false`**. The generated argument model also ignores extra keys: a call with `extra=1` succeeded. The `strict_tool()` helper below subclasses the generated `arg_model` with `ConfigDict(extra="forbid")` and regenerates `parameters`. With it, the advertised schema carries `"additionalProperties": false` and extras are rejected with `is_error=True` ("Extra inputs are not permitted"). The `Context` parameter never appears in the schema.
3. **Structured output.** A tool annotated `-> dict` returns `structured_content=None` and `output_schema=None`; the dict arrives only as JSON text in `content[0].text`. Annotating the return as a `TypedDict` or a pydantic model fills in both `output_schema` and `structured_content={...}`.
4. Bad arguments (an enum violation, or an extra key on the strict tool) do **not** raise in the client. They come back as `CallToolResult(is_error=True, content=[TextContent("Error executing tool ...: 1 validation error ...")])`, and the server logs `Tool '...' rejected arguments: ['mode']`.
5. **Auth rejections, as the client sees them.** Three cases were tried: no `Authorization` header, a persona token (no `aud`), and an `ops-mcp-write` token (aud `incident-sim`). On the wire, all three get HTTP 401 with `WWW-Authenticate: Bearer error="invalid_token", error_description="Authentication required", resource_metadata="http://mcp-read:8081/.well-known/oauth-protected-resource/mcp"`.
   - The client raises **`mcp.shared.exceptions.MCPError`, code `-32603`, message `'Server returned an error response'`, `data=None`**. The 401 status is lost.
   - Caught inside the `async with Client` block, it is a plain `MCPError` (`from mcp import MCPError`), and the client then exits cleanly. Left uncaught, it leaves the block wrapped in two `ExceptionGroup`s (anyio task groups).
   - With `mode="2026-07-28"`, entering the `Client` block sends nothing, so the 401 surfaces at the first `call_tool`/`list_tools`. With `mode="auto"`, it surfaces while entering the block (the discover probe).
   - To tell a 401 from other failures, give the client an `httpx2.AsyncClient(event_hooks={"response": [hook]})`. The hook sees the real status (measured: `[401]`).
6. **DNS-rebinding protection.** With `transport_security=None` and the default `host="127.0.0.1"`, the app accepts only these `Host` values: `127.0.0.1:*`, `localhost:*`, `[::1]:*`. A request with `Host: mcp-read:8081` gets **421 `Invalid Host header`**. In compose, pass `TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=["mcp-read:8081", ...], allowed_origins=[])`. With that setting, `Host: mcp-read:8081` passes and `evil.example:8081` still gets 421 (measured with `m2b_host.py`).
7. The protected-resource metadata is served at `/.well-known/oauth-protected-resource/mcp`; the bare `/.well-known/oauth-protected-resource` returns 404. Its body is `{"resource":"http://mcp-read:8081/mcp","authorization_servers":["http://localhost:18080/realms/ops-dev"],"bearer_methods_supported":["header"]}`. The health routes on the outer app need no auth; `/health/live` and `/health/ready` returned 200.
8. A raw JSON-RPC POST with `MCP-Protocol-Version: 2026-07-28` and empty `params` gets **400 / -32602**: "params._meta must be an object carrying the required 'io.modelcontextprotocol/protocolVersion' and ..." (`mcp/shared/inbound.py:436`). Hand-rolled probes, such as a readiness check that POSTs to `/mcp`, must either use the SDK client or send `_meta`.
9. Expiry is checked twice, consistently. The verifier sets `AccessToken.expires_at=exp`, and the bearer middleware rejects with 401 when `expires_at < time.time()`, so it agrees with the verifier's own `exp` check.
10. `AuthSettings(issuer_url=..., resource_server_url=...)` without `validate_token_resource` emits `MCPDeprecationWarning: AuthSettings.validate_token_resource is not set, so bearer tokens are not checked against resource_server_url; it will default to True in 3.0 ...`. Set it to `False` when the verifier checks `aud` itself, as here. Not measured: `validate_token_resource=True` together with `AccessToken.resource`.

Script `mcp_server.py` (run as `python mcp_server.py` or `python mcp_server.py --security=compose`):

```python
"""M2 server: MCP 2.3.0 MCPServer with bearer auth (PyJWT + Keycloak JWKS), streamable HTTP, health routes.

Run: python mcp_server.py [--security=default|compose]
"""
from __future__ import annotations

import contextlib
import sys
import warnings
from typing import Any, Literal, TypedDict

from pydantic import ConfigDict

import httpx2
import jwt
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.tools.base import Tool
from mcp.server.transport_security import TransportSecuritySettings

warnings.simplefilter("always")  # surface every deprecation warning

ISSUER = "http://localhost:18080/realms/ops-dev"
JWKS_URL = f"{ISSUER}/protocol/openid-connect/certs"
RESOURCE = "http://mcp-read:8081/mcp"


class KeycloakVerifier:
    """TokenVerifier protocol: async verify_token(token) -> AccessToken | None (None => 401)."""

    def __init__(self, jwks_url: str, issuer: str, audience: str) -> None:
        self.jwks_url, self.issuer, self.audience = jwks_url, issuer, audience
        self._jwks: jwt.PyJWKSet | None = None

    async def _keyset(self, refresh: bool = False) -> jwt.PyJWKSet:
        if self._jwks is None or refresh:
            async with httpx2.AsyncClient(timeout=5) as c:
                r = await c.get(self.jwks_url)
                r.raise_for_status()
                self._jwks = jwt.PyJWKSet.from_dict(r.json())
        return self._jwks

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            kid = jwt.get_unverified_header(token).get("kid")
            ks = await self._keyset()
            try:
                key = ks[kid]
            except KeyError:  # key rotation: refetch once
                key = (await self._keyset(refresh=True))[kid]
            c: dict[str, Any] = jwt.decode(
                token, key, algorithms=["RS256"], audience=self.audience, issuer=self.issuer,
                options={"require": ["exp", "iat", "iss", "aud", "sub", "azp"]},
            )
        except (jwt.PyJWTError, KeyError) as e:
            print(f"[verifier] rejected: {type(e).__name__}: {e}", flush=True)
            return None
        return AccessToken(token=token, client_id=c["azp"], scopes=[], expires_at=c["exp"],
                           resource=self.audience, subject=c["sub"], claims=c)


async def search_procedures(query: str, limit: int, mode: Literal["lexical", "vector_exact"], ctx: Context) -> dict:
    """Search procedures (spike)."""
    tok = get_access_token()
    return {
        "query": query,
        "limit": limit,
        "mode": mode,
        "handle": ctx.headers.get("x-ops-invocation") if ctx.headers else None,
        "azp": tok.client_id if tok else None,
    }


class SearchResult(TypedDict):
    query: str
    handle: str | None
    azp: str | None


async def search_strict(query: str, limit: int, mode: Literal["lexical", "vector_exact"], ctx: Context) -> SearchResult:
    """Strict variant: TypedDict return => structured_content + outputSchema; extras forbidden."""
    tok = get_access_token()
    return {"query": query, "handle": ctx.headers.get("x-ops-invocation") if ctx.headers else None,
            "azp": tok.client_id if tok else None}


def strict_tool(fn: Any) -> Tool:
    """Build a Tool whose argument model forbids extra keys and whose advertised schema says so."""
    tool = Tool.from_function(fn)
    base = tool.fn_metadata.arg_model

    class Strict(base):  # type: ignore[misc, valid-type]
        model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    Strict.__name__ = base.__name__
    tool.fn_metadata.arg_model = Strict
    tool.parameters = Strict.model_json_schema(by_alias=True)
    return tool



server = MCPServer(
    name="spike",
    auth=AuthSettings(issuer_url=ISSUER, resource_server_url=RESOURCE, validate_token_resource=False),
    token_verifier=KeycloakVerifier(JWKS_URL, ISSUER, RESOURCE),
    tools=[strict_tool(search_strict)],  # public constructor route for a pre-built Tool
)
server.add_tool(search_procedures)  # plain registration (== @server.tool())


async def live(_: Request) -> JSONResponse:
    return JSONResponse({"status": "live"})


async def ready(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ready"})


def build_app(security: str) -> Starlette:
    ts = None
    if security == "compose":
        ts = TransportSecuritySettings(enable_dns_rebinding_protection=True,
                                       allowed_hosts=["mcp-read:8081", "127.0.0.1:*", "localhost:*"],
                                       allowed_origins=[])
    mcp_app = server.streamable_http_app(streamable_http_path="/mcp", stateless_http=True, json_response=True,
                                         transport_security=ts)

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette):
        # A mounted sub-app's lifespan does not run: forward it so the session manager's task group starts.
        async with mcp_app.router.lifespan_context(mcp_app):
            yield

    return Starlette(
        routes=[Route("/health/live", live), Route("/health/ready", ready), Mount("/", app=mcp_app)],
        lifespan=lifespan,
    )


if __name__ == "__main__":
    sec = "compose" if "--security=compose" in sys.argv else "default"
    print("transport security:", sec, flush=True)
    uvicorn.run(build_app(sec), host="127.0.0.1", port=8081, log_level="warning")
```

Script `mcp_client.py`:

```python
"""M2 client: mcp 2.3.0 Client over streamable HTTP with a custom httpx2.AsyncClient (bearer + X-Ops-Invocation)."""
from __future__ import annotations

import asyncio
import json
import warnings

import httpx2

from mcp import Client
from mcp.client.streamable_http import streamable_http_client

import common

warnings.simplefilter("always")
URL = "http://127.0.0.1:8081/mcp"
STATUSES: list[int] = []
STAGE = ["?"]


ARGS = {"query": "pump vibration", "limit": 3, "mode": "lexical"}


async def _record(resp: httpx2.Response) -> None:
    STATUSES.append(resp.status_code)  # the MCP client hides the HTTP status; an event hook can see it


def http(token: str | None, extra: dict[str, str] | None = None) -> httpx2.AsyncClient:
    headers = {"X-Ops-Invocation": "spike-handle"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    headers.update(extra or {})
    return httpx2.AsyncClient(headers=headers, timeout=httpx2.Timeout(10.0, read=30.0),
                              event_hooks={"response": [_record]})


async def happy(token: str) -> None:
    async with http(token) as hc:
        async with Client(streamable_http_client(URL, http_client=hc), mode="2026-07-28") as client:
            tools = await client.list_tools()
            for t in tools.tools:
                print("tool:", t.name)
                if t.name != "search_procedures":
                    print("  input_schema:", json.dumps(t.input_schema))
                    print("  output_schema:", json.dumps(t.output_schema))
                    continue
                print("inputSchema:", json.dumps(t.input_schema, indent=1))
                print("outputSchema:", json.dumps(t.output_schema))
            res = await client.call_tool("search_procedures", ARGS)
            print("is_error:", res.is_error)
            print("structured_content:", res.structured_content)
            print("content:", [c.model_dump(exclude_none=True) for c in res.content])
            bad = await client.call_tool("search_procedures", {**ARGS, "mode": "fuzzy"})
            print("bad enum -> is_error:", bad.is_error, "content:", [getattr(c, "text", c)[:120] for c in bad.content])
            ex = await client.call_tool("search_procedures", {**ARGS, "extra": 1})
            print("extra key (plain tool) -> is_error:", ex.is_error, "structured:", ex.structured_content)
            st = await client.call_tool("search_strict", ARGS)
            print("search_strict -> is_error:", st.is_error, "structured_content:", st.structured_content)
            st2 = await client.call_tool("search_strict", {**ARGS, "extra": 1})
            print("extra key (strict tool) -> is_error:", st2.is_error,
                  "content:", [getattr(c, "text", c)[:160] for c in st2.content])


async def rejected(label: str, token: str | None, mode: str = "2026-07-28", extra=None) -> None:
    STATUSES.clear()
    try:
        async with http(token, extra) as hc:
            STAGE[0] = "enter"
            async with Client(streamable_http_client(URL, http_client=hc), mode=mode) as client:
                STAGE[0] = "call_tool"
                r = await client.call_tool("search_procedures", ARGS)
                print(f"[{label}] ACCEPTED?! isError={r.is_error} sc={r.structured_content}")
    except BaseException as e:  # noqa: BLE001 - measuring what surfaces
        chain = []
        cur: BaseException | None = e
        while cur is not None:
            chain.append(f"{type(cur).__module__}.{type(cur).__name__}: {str(cur)[:200]}")
            if isinstance(cur, BaseExceptionGroup):
                cur = cur.exceptions[0]
            else:
                cur = cur.__cause__ or cur.__context__
        print(f"[{label}] raised at stage={STAGE[0]}:\n   " + "\n   ".join(chain))
        leaf = e
        while isinstance(leaf, BaseExceptionGroup):
            leaf = leaf.exceptions[0]
        if hasattr(leaf, "error"):
            print(f"   leaf MCPError code={leaf.code} message={leaf.message!r} data={leaf.data!r}")
        print(f"   HTTP statuses seen by httpx2 response event hook: {STATUSES}")
    STATUSES.clear()


async def inner_catch(label: str, token: str | None) -> None:
    """Catch MCPError inside the `async with Client` block: does it surface un-grouped at call_tool?"""
    from mcp import MCPError

    async with http(token) as hc:
        async with Client(streamable_http_client(URL, http_client=hc), mode="2026-07-28") as client:
            try:
                await client.call_tool("search_procedures", ARGS)
                print(f"[inner {label}] accepted?!")
            except MCPError as e:
                print(f"[inner {label}] call_tool raised MCPError directly: code={e.code} message={e.message!r}")
    print(f"[inner {label}] Client exited cleanly after the caught error")


async def raw_status(label: str, token: str | None, extra=None) -> None:
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
         "MCP-Protocol-Version": "2026-07-28", **(extra or {})}
    if token:
        h["Authorization"] = f"Bearer {token}"
    async with httpx2.AsyncClient(timeout=10) as c:
        r = await c.post(URL, json=body, headers=h)
    print(f"[raw {label}] HTTP {r.status_code} www-authenticate={r.headers.get('www-authenticate')!r} body={r.text[:160]!r}")


async def main() -> None:
    wt, at, mw = common.worker_token(), common.alex_token(), common.mcp_write_token()
    print("=== happy path (worker token, mode=2026-07-28)")
    await happy(wt)
    print("=== rejections via Client")
    await rejected("no Authorization", None)
    await rejected("persona alex (no aud)", at)
    await rejected("ops-mcp-write (aud incident-sim)", mw)
    await rejected("no Authorization, mode=auto", None, mode="auto")
    await inner_catch("persona alex", at)
    print("=== rejections via raw HTTP")
    await raw_status("no auth", None)
    await raw_status("alex", at)
    await raw_status("mcp-write", mw)
    await raw_status("worker", wt)
    await raw_status("worker, Host: mcp-read:8081", wt, {"Host": "mcp-read:8081"})


asyncio.run(main())
```

Output (`m2-client.out`, complete):

```text
=== happy path (worker token, mode=2026-07-28)
tool: search_strict
  input_schema: {"type": "object", "additionalProperties": false, "properties": {"query": {"title": "Query", "type": "string"}, "limit": {"title": "Limit", "type": "integer"}, "mode": {"enum": ["lexical", "vector_exact"], "title": "Mode", "type": "string"}}, "required": ["query", "limit", "mode"], "title": "search_strictArguments"}
  output_schema: {"properties": {"query": {"title": "Query", "type": "string"}, "handle": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Handle"}, "azp": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Azp"}}, "required": ["query", "handle", "azp"], "title": "SearchResult", "type": "object"}
tool: search_procedures
inputSchema: {
 "type": "object",
 "properties": {
  "query": {
   "title": "Query",
   "type": "string"
  },
  "limit": {
   "title": "Limit",
   "type": "integer"
  },
  "mode": {
   "enum": [
    "lexical",
    "vector_exact"
   ],
   "title": "Mode",
   "type": "string"
  }
 },
 "required": [
  "query",
  "limit",
  "mode"
 ],
 "title": "search_proceduresArguments"
}
outputSchema: null
is_error: False
structured_content: None
content: [{'type': 'text', 'text': '{\n  "query": "pump vibration",\n  "limit": 3,\n  "mode": "lexical",\n  "handle": "spike-handle",\n  "azp": "ops-worker"\n}'}]
bad enum -> is_error: True content: ["Error executing tool search_procedures: 1 validation error for search_proceduresArguments\nmode\n  Input should be 'lexica"]
extra key (plain tool) -> is_error: False structured: None
search_strict -> is_error: False structured_content: {'query': 'pump vibration', 'handle': 'spike-handle', 'azp': 'ops-worker'}
extra key (strict tool) -> is_error: True content: ['Error executing tool search_strict: 1 validation error for Strict\nextra\n  Extra inputs are not permitted [type=extra_forbidden, input_value=1, input_type=int]\n ']
=== rejections via Client
[no Authorization] raised at stage=call_tool:
   builtins.ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
   builtins.ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
   mcp.shared.exceptions.MCPError: Server returned an error response
   leaf MCPError code=-32603 message='Server returned an error response' data=None
   HTTP statuses seen by httpx2 response event hook: [401]
[persona alex (no aud)] raised at stage=call_tool:
   builtins.ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
   builtins.ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
   mcp.shared.exceptions.MCPError: Server returned an error response
   leaf MCPError code=-32603 message='Server returned an error response' data=None
   HTTP statuses seen by httpx2 response event hook: [401]
[ops-mcp-write (aud incident-sim)] raised at stage=call_tool:
   builtins.ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
   builtins.ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
   mcp.shared.exceptions.MCPError: Server returned an error response
   leaf MCPError code=-32603 message='Server returned an error response' data=None
   HTTP statuses seen by httpx2 response event hook: [401]
[no Authorization, mode=auto] raised at stage=enter:
   builtins.ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
   builtins.ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
   mcp.shared.exceptions.MCPError: Server returned an error response
   mcp.shared.exceptions.MCPError: Server returned an error response
   leaf MCPError code=-32603 message='Server returned an error response' data=None
   HTTP statuses seen by httpx2 response event hook: [401, 401]
[inner persona alex] call_tool raised MCPError directly: code=-32603 message='Server returned an error response'
[inner persona alex] Client exited cleanly after the caught error
=== rejections via raw HTTP
[raw no auth] HTTP 401 www-authenticate='Bearer error="invalid_token", error_description="Authentication required", resource_metadata="http://mcp-read:8081/.well-known/oauth-protected-resource/mcp"' body='{"error": "invalid_token", "error_description": "Authentication required"}'
[raw alex] HTTP 401 www-authenticate='Bearer error="invalid_token", error_description="Authentication required", resource_metadata="http://mcp-read:8081/.well-known/oauth-protected-resource/mcp"' body='{"error": "invalid_token", "error_description": "Authentication required"}'
[raw mcp-write] HTTP 401 www-authenticate='Bearer error="invalid_token", error_description="Authentication required", resource_metadata="http://mcp-read:8081/.well-known/oauth-protected-resource/mcp"' body='{"error": "invalid_token", "error_description": "Authentication required"}'
[raw worker] HTTP 400 www-authenticate=None body='{"jsonrpc":"2.0","id":1,"error":{"code":-32602,"message":"params._meta must be an object carrying the required \'io.modelcontextprotocol/protocolVersion\' and \'io'
[raw worker, Host: mcp-read:8081] HTTP 421 www-authenticate=None body='Invalid Host header'
```

Server log for that run (`server.log`):

```text
transport security: default
StreamableHTTP session manager started
HTTP Request: GET http://localhost:18080/realms/ops-dev/protocol/openid-connect/certs "HTTP/1.1 200 OK"
Tool 'search_procedures' rejected arguments: ['mode']
Tool 'search_strict' rejected arguments: ['extra']
[verifier] rejected: MissingRequiredClaimError: Token is missing the "aud" claim
[verifier] rejected: InvalidAudienceError: Audience doesn't match
[verifier] rejected: MissingRequiredClaimError: Token is missing the "aud" claim
[verifier] rejected: MissingRequiredClaimError: Token is missing the "aud" claim
[verifier] rejected: InvalidAudienceError: Audience doesn't match
Invalid Host header: mcp-read:8081
```

curl probes (`curl -i -X POST /mcp` with no auth, then `GET /health/ready`, then `GET /.well-known/oauth-protected-resource/mcp`):

```text
HTTP/1.1 401 Unauthorized
date: Thu, 08 Oct 2026 12:08:32 GMT
server: uvicorn
content-type: application/json
content-length: 74
www-authenticate: Bearer error="invalid_token", error_description="Authentication required", resource_metadata="http://mcp-read:8081/.well-known/oauth-protected-resource/mcp"

{"error": "invalid_token", "error_description": "Authentication required"}{"status":"ready"}
{"resource":"http://mcp-read:8081/mcp","authorization_servers":["http://localhost:18080/realms/ops-dev"],"bearer_methods_supported":["header"]}
```

Host allowlist check, `m2b_host.py`, against `mcp_server.py --security=compose`:

```python
"""M2b: DNS-rebinding Host check. Run against `python mcp_server.py --security=compose`."""
import asyncio

import httpx2

import common


async def main() -> None:
    wt = common.worker_token()
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    for host in ["mcp-read:8081", "evil.example:8081"]:
        async with httpx2.AsyncClient() as c:
            r = await c.post("http://127.0.0.1:8081/mcp", json=body,
                             headers={"Host": host, "Authorization": f"Bearer {wt}",
                                      "Accept": "application/json, text/event-stream",
                                      "MCP-Protocol-Version": "2026-07-28"})
            print(host, r.status_code, r.text[:90])

asyncio.run(main())
```

```text
mcp-read:8081 400 {"jsonrpc":"2.0","id":1,"error":{"code":-32602,"message":"params._meta must be an object c
evil.example:8081 421 Invalid Host header
```

(The 400 for `mcp-read:8081` means the request passed the Host check and was then refused for missing `_meta`; see gotcha 8.)

## 3. psycopg 3 async

Import paths: `import psycopg`, `psycopg.AsyncConnection.connect(conninfo, row_factory=dict_row)` (it is a coroutine, so use `async with await psycopg.AsyncConnection.connect(...) as conn`), `from psycopg.rows import dict_row`, `from psycopg.types.json import Jsonb`, `from psycopg.conninfo import make_conninfo`, `psycopg.errors.UniqueViolation` (sqlstate `23505`).

Measured:
- `UPDATE ... WHERE id = (SELECT id ... ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *` leases the oldest row. A second connection running the same statement while the first transaction is open gets the **next** row.
- `INSERT ... ON CONFLICT (id) DO NOTHING RETURNING *` on an existing id gives `fetchone() -> None` and `rowcount 0` (confirmed). On a new id it returns the row with `rowcount 1`.
- Round trips: `uuid` returns as `uuid.UUID` (equal); `jsonb` written via `Jsonb({...})` reads back as a `dict`; `bytea` written as `bytes` reads back as `bytes`; `timestamptz` comes back as an aware `datetime` with `tzinfo=Etc/UTC`, equal to what was written. An aware `+05:00` value comes back converted to UTC, and it is the same instant.

Gotchas:
- **Windows event loop.** psycopg async refuses the default Proactor loop with `psycopg.InterfaceError: Psycopg cannot use the 'ProactorEventLoop' to run in async mode`. Use `asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)` (Python 3.13), or the selector event-loop policy. `uvicorn.run()` already picks `SelectorEventLoop` on Windows when there is no reload and no workers (`uvicorn/loops/asyncio.py`: Proactor only when `use_subprocess`). Linux containers are unaffected, but host-side tests on Windows are not.
- `autocommit` defaults to `False`. Any bare `execute` opens an implicit transaction (`transaction_status: INTRANS`) that stays open until `commit()`/`rollback()`. Use `async with conn.transaction():` blocks, or connect with `autocommit=True` for a polling loop. A `UniqueViolation` inside `async with conn.transaction()` rolls that block back and leaves the connection usable.
- A **naive** datetime is accepted silently and interpreted in the session `TimeZone` (`Etc/UTC` on this server), so always pass aware datetimes.
- Build the conninfo with `make_conninfo(host=..., port=..., user=..., dbname=..., password=...)` so the password is quoted correctly and never sits in a hand-written string.

Script `m3_psycopg.py`:

```python
"""M3: psycopg 3 async against the dev Postgres (password read from the secret file, never printed)."""
import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta, timezone

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

import common

if sys.platform == "win32":  # psycopg async cannot use the Proactor loop
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def main() -> None:
    conninfo = common.pg_conninfo("ops")
    async with await psycopg.AsyncConnection.connect(conninfo, row_factory=dict_row) as conn:
        print("autocommit default:", conn.autocommit, "| server_version:", conn.info.server_version)
        async with conn.transaction():
            await conn.execute("CREATE SCHEMA spike")
            await conn.execute("""
                CREATE TABLE spike.lease (
                  id uuid PRIMARY KEY,
                  state text NOT NULL,
                  owner text,
                  payload jsonb NOT NULL,
                  blob bytea,
                  created_at timestamptz NOT NULL,
                  lease_until timestamptz)""")
        ids = [uuid.uuid4() for _ in range(3)]
        now = datetime.now(UTC)
        async with conn.transaction():
            async with conn.cursor() as cur:
                await cur.executemany(
                    "INSERT INTO spike.lease (id, state, payload, blob, created_at) VALUES (%s, 'queued', %s, %s, %s)",
                    [(i, Jsonb({"n": n, "tags": ["a", "b"]}), bytes([n, 0, 255]), now + timedelta(seconds=n))
                     for n, i in enumerate(ids)],
                )
        # Lease one row: UPDATE ... WHERE id = (SELECT ... FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *
        lease_sql = """
            UPDATE spike.lease SET state = 'leased', owner = %(owner)s, lease_until = now() + interval '30 seconds'
            WHERE id = (SELECT id FROM spike.lease WHERE state = 'queued' ORDER BY created_at
                        FOR UPDATE SKIP LOCKED LIMIT 1)
            RETURNING *"""
        async with conn.transaction():
            cur = await conn.execute(lease_sql, {"owner": "w1"})
            row = await cur.fetchone()
            print("leased:", row["id"] == ids[0], "state:", row["state"], "owner:", row["owner"],
                  "| types:", type(row["id"]).__name__, type(row["payload"]).__name__, type(row["blob"]).__name__,
                  type(row["created_at"]).__name__, "tz:", row["created_at"].tzinfo)
            # A second connection inside the open transaction skips the locked row and takes the next one.
            async with await psycopg.AsyncConnection.connect(conninfo, row_factory=dict_row) as c2:
                r2 = await (await c2.execute(lease_sql, {"owner": "w2"})).fetchone()
                await c2.commit()
                print("concurrent lease got the NEXT row (SKIP LOCKED):", r2["id"] == ids[1])
        # ON CONFLICT DO NOTHING RETURNING *: no row on conflict
        ins = "INSERT INTO spike.lease (id, state, payload, created_at) VALUES (%s, 'queued', %s, now()) ON CONFLICT (id) DO NOTHING RETURNING *"
        async with conn.transaction():
            cur = await conn.execute(ins, (ids[0], Jsonb({})))
            print("ON CONFLICT DO NOTHING RETURNING on existing id -> fetchone():", await cur.fetchone(),
                  "rowcount:", cur.rowcount)
            new_id = uuid.uuid4()
            cur = await conn.execute(ins, (new_id, Jsonb({"x": 1})))
            r = await cur.fetchone()
            print("... on a new id -> row returned:", r is not None and r["id"] == new_id, "rowcount:", cur.rowcount)
        # Round trips
        r = await (await conn.execute("SELECT * FROM spike.lease WHERE id = %s", (ids[2],))).fetchone()
        print("uuid round trip:", r["id"] == ids[2], "| jsonb ->", r["payload"], "| bytea ->", r["blob"],
              "| timestamptz equal:", r["created_at"] == now + timedelta(seconds=2))
        tz5 = timezone(timedelta(hours=5))
        aware = datetime(2026, 10, 8, 12, 0, tzinfo=tz5)
        got = (await (await conn.execute("SELECT %s::timestamptz AS t", (aware,))).fetchone())["t"]
        print("aware +05:00 in -> out:", got.isoformat(), "| equal instant:", got == aware)
        try:
            await conn.execute("SELECT %s::timestamptz", (datetime(2026, 10, 8, 12, 0),))
            print("naive datetime accepted (interpreted in session TimeZone):",
                  (await (await conn.execute("SHOW TimeZone")).fetchone()))
        except Exception as e:
            print("naive datetime:", type(e).__name__, e)
        await conn.rollback()  # end the implicit transaction opened by the SELECTs
        # Gotcha check: outside conn.transaction() with autocommit False, statements open an implicit transaction
        await conn.execute("SELECT 1")
        print("after a bare execute, transaction_status:", conn.info.transaction_status.name)
        await conn.rollback()
        try:
            async with conn.transaction():
                await conn.execute("INSERT INTO spike.lease (id, state, payload, created_at) VALUES (%s, 'q', %s, now())",
                                   (ids[0], Jsonb({})))
        except psycopg.errors.UniqueViolation as e:
            print("UniqueViolation import path psycopg.errors.UniqueViolation; sqlstate:", e.sqlstate)
        print("connection usable after rolled-back transaction block:",
              (await (await conn.execute("SELECT count(*) AS n FROM spike.lease")).fetchone())["n"])
        await conn.commit()
        await conn.execute("DROP SCHEMA spike CASCADE")
        await conn.commit()
        n = (await (await conn.execute("SELECT count(*) AS n FROM pg_namespace WHERE nspname='spike'")).fetchone())["n"]
        print("schema spike dropped:", n == 0)


asyncio.run(main())
```

Output (`m3.out`, complete):

```text
autocommit default: False | server_version: 170011
leased: True state: leased owner: w1 | types: UUID dict bytes datetime tz: Etc/UTC
concurrent lease got the NEXT row (SKIP LOCKED): True
ON CONFLICT DO NOTHING RETURNING on existing id -> fetchone(): None rowcount: 0
... on a new id -> row returned: True rowcount: 1
uuid round trip: True | jsonb -> {'n': 2, 'tags': ['a', 'b']} | bytea -> b'\x02\x00\xff' | timestamptz equal: True
aware +05:00 in -> out: 2026-10-08T07:00:00+00:00 | equal instant: True
naive datetime accepted (interpreted in session TimeZone): {'TimeZone': 'Etc/UTC'}
after a bare execute, transaction_status: INTRANS
UniqueViolation import path psycopg.errors.UniqueViolation; sqlstate: 23505
connection usable after rolled-back transaction block: 4
schema spike dropped: True
```

Event-loop probe `m3b_loop.py`:

```python
"""M3b: which event loop does psycopg async need on Windows?"""
import asyncio

import psycopg

import common


async def probe() -> str:
    async with await psycopg.AsyncConnection.connect(common.pg_conninfo()) as c:
        return str((await (await c.execute("SELECT 1")).fetchone())[0])

try:
    print("default (Proactor) loop:", asyncio.run(probe()))
except Exception as e:
    print("default (Proactor) loop:", type(e).__module__ + "." + type(e).__name__, str(e)[:160])
print("asyncio.run(..., loop_factory=asyncio.SelectorEventLoop):", asyncio.run(probe(), loop_factory=asyncio.SelectorEventLoop))
```

```text
default (Proactor) loop: psycopg.InterfaceError Psycopg cannot use the 'ProactorEventLoop' to run in async mode. Please use a compatible event loop, for instance by running 'asyncio.run(..., loop_factory=asyn
asyncio.run(..., loop_factory=asyncio.SelectorEventLoop): 1
```

## 4. Alembic, driven from Python

Measured: `cfg = alembic.config.Config()` with no ini file, plus `cfg.set_main_option("script_location", <dir>)`. The `env.py` reads `SPIKE_DB_URL`, a SQLAlchemy URL `postgresql+psycopg://ops:***@127.0.0.1:15432/incident` built with `sqlalchemy.URL.create(...)` and passed through `render_as_string(hide_password=False)` (printed only with `hide_password=True`). Then:
- `command.upgrade(cfg, "0001")` run twice: the second run is a silent no-op.
- `command.current(cfg)` prints `0001`, and later `0002 (head)`.
- `command.upgrade(cfg, "head")` run twice is likewise idempotent.
- `command.downgrade(cfg, "base")` worked.

Alembic printed no "Running upgrade" lines because, without an ini file, nothing calls `fileConfig`. Configure `logging` yourself if you want them.

LOGIN role with a password from a variable, run inside a migration against the `incident` database:
- **Way 1 fails:** `sa.text("CREATE ROLE r LOGIN PASSWORD :pw").bindparams(pw=...)` raises `ProgrammingError: (psycopg.errors.SyntaxError) syntax error at or near "$1"`, because utility statements take no server-side parameters. Worse, **`str(exc)` contains the password**: SQLAlchemy appends `[parameters: {...}]` (measured `True`). Any logged SQLAlchemy error that carries a secret parameter leaks it unless the engine is created with `create_engine(..., hide_parameters=True)`.
- **Way 2 works:** bind the value into `SELECT set_config('spike.pw', :pw, true)`, a transaction-local setting, then run `DO $$ BEGIN EXECUTE format('CREATE ROLE spike_role LOGIN PASSWORD %L', current_setting('spike.pw')); END $$`, then clear the setting. The server does the quoting.
- **Way 3 works:** client-side composition with psycopg on the raw DBAPI connection, `op.get_bind().connection.dbapi_connection.cursor().execute(psycopg.sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(sql.Identifier(name), sql.Literal(password)))`.
- Both roles could log in with the password, which contains a `'` on purpose to prove the quoting. Cleanup ran `downgrade base` (roles dropped), `DROP SCHEMA spike2 CASCADE` and `DROP TABLE public.alembic_version`, leaving no roles and no schema.
- The resulting `CREATE ROLE ... PASSWORD '<literal>'` reaches the server as text in both ways 2 and 3. It would appear in the Postgres log only if `log_statement` were `ddl`/`all` (the default is `none`). Way 2's `EXECUTE` inside PL/pgSQL is not logged by `log_statement`.

Runner `m4_alembic.py`:

```python
"""M4: Alembic driven from Python (no alembic.ini), URL from SPIKE_DB_URL, against the `incident` database."""
import os
import secrets
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from sqlalchemy import URL, create_engine, text

import common

HERE = Path(__file__).resolve().parent

url = URL.create("postgresql+psycopg", username="ops", password=common.secret("postgres_password"),
                 host="127.0.0.1", port=15432, database="incident")
os.environ["SPIKE_DB_URL"] = url.render_as_string(hide_password=False)  # env.py reads it; never printed
os.environ["SPIKE_ROLE_PASSWORD"] = "it's-" + secrets.token_urlsafe(16)  # contains a quote on purpose

cfg = Config()  # no ini file
cfg.set_main_option("script_location", str(HERE / "alembic_spike"))
print("printing URL safely:", url.render_as_string(hide_password=True))

print("upgrade 0001 (1st):"); command.upgrade(cfg, "0001")
print("upgrade 0001 (2nd, no-op):"); command.upgrade(cfg, "0001")
print("current:"); command.current(cfg, verbose=False)
print("upgrade head (0002 creates LOGIN roles):"); command.upgrade(cfg, "head")
print("upgrade head again (no-op):"); command.upgrade(cfg, "head")
print("current:"); command.current(cfg)

# The roles really carry the password: log in as each.
for role in ("spike_role", "spike_role_b"):
    ci = psycopg.conninfo.make_conninfo(host="127.0.0.1", port=15432, dbname="incident", user=role,
                                        password=os.environ["SPIKE_ROLE_PASSWORD"])
    with psycopg.connect(ci) as c:
        print(f"login as {role}:", c.execute("SELECT current_user").fetchone()[0])

print("downgrade base:"); command.downgrade(cfg, "base")
eng = create_engine(os.environ["SPIKE_DB_URL"])
with eng.begin() as c:
    c.execute(text("DROP SCHEMA IF EXISTS spike2 CASCADE"))
    c.execute(text("DROP TABLE IF EXISTS public.alembic_version"))
    left = c.execute(text("SELECT count(*) FROM pg_roles WHERE rolname LIKE 'spike_role%'")).scalar()
    sch = c.execute(text("SELECT count(*) FROM pg_namespace WHERE nspname='spike2'")).scalar()
print("cleanup: spike roles left =", left, "| spike2 schema left =", sch)
eng.dispose()
```

`alembic_spike/env.py`:

```python
"""Alembic env driven programmatically: URL from SPIKE_DB_URL, never from alembic.ini."""
import os

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config
url = os.environ["SPIKE_DB_URL"]


def run_migrations_offline() -> None:
    context.configure(url=url, literal_binds=True, dialect_opts={"paramstyle": "named"},
                      version_table_schema=config.get_main_option("version_table_schema"))
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection,
                          version_table_schema=config.get_main_option("version_table_schema"))
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

`alembic_spike/script.py.mako`:

```mako
"""${message}"""
revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = None
depends_on = None


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

`alembic_spike/versions/0001_spike2.py`:

```python
"""create spike2.t"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS spike2")
    op.execute("CREATE TABLE spike2.t (id uuid PRIMARY KEY)")


def downgrade() -> None:
    op.execute("DROP TABLE spike2.t")
```

`alembic_spike/versions/0002_role.py`:

```python
"""create a LOGIN role whose password comes from the environment (never from the migration text)"""
import os

import sqlalchemy as sa
from alembic import op
from psycopg import sql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    password = os.environ["SPIKE_ROLE_PASSWORD"]
    conn = op.get_bind()

    # Way 1: a bind parameter in CREATE ROLE ... PASSWORD :pw (utility statements take no server-side params).
    try:
        with conn.begin_nested():  # SAVEPOINT so the failure does not abort the migration transaction
            conn.execute(sa.text("CREATE ROLE spike_role_a LOGIN PASSWORD :pw").bindparams(pw=password))
        print("   way 1 (bindparams in CREATE ROLE): WORKED")
    except Exception as e:  # noqa: BLE001
        print(f"   way 1 (bindparams in CREATE ROLE): {type(e).__name__}: {str(e).splitlines()[0][:150]}")
        print(f"   way 1 str(exception) contains the password (SQLAlchemy [parameters: ...]): {password in str(e)}")

    # Way 2: pass the value as a bound parameter to set_config, then let the server quote it with format('%L').
    conn.execute(sa.text("SELECT set_config('spike.pw', :pw, true)").bindparams(pw=password))
    conn.execute(sa.text(
        "DO $$ BEGIN EXECUTE format('CREATE ROLE spike_role LOGIN PASSWORD %L', current_setting('spike.pw')); END $$"
    ))
    conn.execute(sa.text("SELECT set_config('spike.pw', '', true)"))
    print("   way 2 (set_config + DO/format %L): created spike_role")

    # Way 3: psycopg client-side composition (sql.Identifier / sql.Literal) on the raw DBAPI connection.
    raw = conn.connection.dbapi_connection
    with raw.cursor() as cur:
        cur.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(sql.Identifier("spike_role_b"),
                                                                     sql.Literal(password)))
    print("   way 3 (psycopg.sql.Literal on dbapi cursor): created spike_role_b")


def downgrade() -> None:
    op.execute("DROP ROLE IF EXISTS spike_role")
    op.execute("DROP ROLE IF EXISTS spike_role_b")
```

Output (`m4.out`, complete):

```text
printing URL safely: postgresql+psycopg://ops:***@127.0.0.1:15432/incident
upgrade 0001 (1st):
upgrade 0001 (2nd, no-op):
current:
0001
upgrade head (0002 creates LOGIN roles):
   way 1 (bindparams in CREATE ROLE): ProgrammingError: (psycopg.errors.SyntaxError) syntax error at or near "$1"
   way 1 str(exception) contains the password (SQLAlchemy [parameters: ...]): True
   way 2 (set_config + DO/format %L): created spike_role
   way 3 (psycopg.sql.Literal on dbapi cursor): created spike_role_b
upgrade head again (no-op):
current:
0002 (head)
login as spike_role: spike_role
login as spike_role_b: spike_role_b
downgrade base:
cleanup: spike roles left = 0 | spike2 schema left = 0
```

## 5. uvicorn in an asyncio task beside another task

Measured: `server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8070, log_level="warning"))` runs as `asyncio.create_task(server.serve())`, beside a polling task that holds an autocommit psycopg connection, all in one `asyncio.run(..., loop_factory=asyncio.SelectorEventLoop)`. Use `server.started` (a bool) for readiness. Shutdown: set `server.should_exit = True` and an `asyncio.Event` for the poller, then `await asyncio.gather(...)`. Both tasks finished in 0.15 s, `serve()` returned `None`, and the port was closed.

Gotchas: according to the source (`uvicorn/server.py:89`; not exercised here), `serve()` wraps itself in `Server.capture_signals()`, so a SIGINT or SIGTERM sets `should_exit`. Make the poller watch the same stop event, or watch `server.should_exit`. On Windows, connecting to a just-closed loopback port surfaced as `httpx2.ConnectTimeout`, not `ConnectError`, so catch both.

Script `m5_uvicorn_task.py`:

```python
"""M5: uvicorn.Server.serve() as one asyncio task beside a polling-loop task (worker shape), clean shutdown."""
import asyncio
import time

import httpx2
import psycopg
import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

import common

STATE = {"polls": 0}


async def live(_):
    return JSONResponse({"status": "live", "polls": STATE["polls"]})

app = Starlette(routes=[Route("/health/live", live)])


async def poll_loop(stop: asyncio.Event) -> None:
    async with await psycopg.AsyncConnection.connect(common.pg_conninfo(), autocommit=True) as conn:
        while not stop.is_set():
            await conn.execute("SELECT 1")  # stands in for the lease query
            STATE["polls"] += 1
            try:
                await asyncio.wait_for(stop.wait(), timeout=0.2)
            except TimeoutError:
                pass
    print("poll loop exited cleanly after", STATE["polls"], "polls")


async def main() -> None:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8070, log_level="warning"))
    stop = asyncio.Event()
    t_server = asyncio.create_task(server.serve(), name="uvicorn")
    t_poll = asyncio.create_task(poll_loop(stop), name="poller")
    while not server.started:
        await asyncio.sleep(0.05)
    print("server.started:", server.started)
    async with httpx2.AsyncClient() as c:
        for _ in range(3):
            r = await c.get("http://127.0.0.1:8070/health/live")
            print("GET /health/live ->", r.status_code, r.json())
            await asyncio.sleep(0.3)
    t0 = time.monotonic()
    stop.set()
    server.should_exit = True
    await asyncio.gather(t_server, t_poll)
    print(f"both tasks finished in {time.monotonic() - t0:.2f}s; server task result:", t_server.result())
    try:
        async with httpx2.AsyncClient() as c:
            await c.get("http://127.0.0.1:8070/health/live", timeout=1)
        print("port still open?!")
    except (httpx2.ConnectError, httpx2.ConnectTimeout) as e:  # Windows: a closed loopback port often times out
        print("port 8070 closed after shutdown:", type(e).__name__)


asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)  # SelectorEventLoop: psycopg async on Windows
```

Output (`m5.out`):

```text
server.started: True
GET /health/live -> 200 {'status': 'live', 'polls': 1}
GET /health/live -> 200 {'status': 'live', 'polls': 3}
GET /health/live -> 200 {'status': 'live', 'polls': 4}
poll loop exited cleanly after 6 polls
both tasks finished in 0.15s; server task result: None
port 8070 closed after shutdown: ConnectTimeout
```

## 6. FastAPI bearer dependency

Measured with fastapi 0.142.4, starlette 1.7.0, uvicorn 0.54.0 and pyjwt 2.15.1. The dependency is `HTTPBearer(auto_error=False)` (from `fastapi.security import HTTPAuthorizationCredentials, HTTPBearer`) plus a custom exception and an `@app.exception_handler`, which produce `401 {"code":"UNAUTHENTICATED","message":...,"reason":...}` with `WWW-Authenticate: Bearer`. A `Basic` scheme yields `creds=None`, as does a missing header.

- With `audience="ops-api"`, **every token issued today fails**. alex fails with `MissingRequiredClaimError`, because persona tokens have no `aud`. ops-worker fails with `InvalidAudienceError`. **The realm needs an `oidc-audience-mapper` adding `ops-api` to the token of the client the browser and personas use (`ops-web`, and `ops-dev-direct` for tests)**, and `tests/plan_b/test_realm_template.py` must be updated with it (plan-d-inputs 3.2).
- With `options={"verify_aud": False}` (and `audience=None`), alex passes with `azp=ops-dev-direct`. **So does the ops-worker service-account token** (`azp=ops-worker`). Without an audience check, the API must at least pin the allowed `azp` values or reject `service-account-*` users.
- Test clients:
  - Over a real socket: `httpx2.AsyncClient(base_url="http://127.0.0.1:8000")` against uvicorn.
  - In-process: `httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://t")`.
  - `from fastapi.testclient import TestClient`, which is `starlette.testclient`; in starlette 1.7.0 it imports **httpx2** (`import httpx2 as httpx`) and falls back to `httpx`. Plain `httpx` is therefore not needed, and the scratch lock indeed contains no `httpx`.
  - In the `--no-aud` run, `TestClient` returned 401 only because that call sent no header.

Script `m6_fastapi.py` (run twice: with no argument, then with `--no-aud`):

```python
"""M6: FastAPI bearer dependency verifying Keycloak tokens with PyJWT; 401 {"code":"UNAUTHENTICATED",...}."""
import asyncio
import sys
from typing import Annotated, Any

import httpx2
import jwt
import uvicorn
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import common

AUDIENCE = "ops-api"
VERIFY_AUD = "--no-aud" not in sys.argv  # demo switch: today's persona tokens carry no aud

app = FastAPI()
bearer = HTTPBearer(auto_error=False)  # auto_error=False: we shape the 401 ourselves
_jwks: jwt.PyJWKSet | None = None


class Unauthenticated(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason


@app.exception_handler(Unauthenticated)
async def unauthenticated(_: Request, exc: Unauthenticated) -> JSONResponse:
    return JSONResponse(status_code=401, headers={"WWW-Authenticate": "Bearer"},
                        content={"code": "UNAUTHENTICATED", "message": "authentication required", "reason": exc.reason})


async def keyset() -> jwt.PyJWKSet:
    global _jwks
    if _jwks is None:
        async with httpx2.AsyncClient(timeout=5) as c:
            r = await c.get(common.JWKS_URL)
            r.raise_for_status()
            _jwks = jwt.PyJWKSet.from_dict(r.json())
    return _jwks


async def principal(creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> dict[str, Any]:
    if creds is None:
        raise Unauthenticated("missing bearer token")
    token = creds.credentials
    try:
        key = (await keyset())[jwt.get_unverified_header(token)["kid"]]
        opts: dict[str, Any] = {"require": ["exp", "iat", "iss", "sub", "azp"]}
        if not VERIFY_AUD:
            opts["verify_aud"] = False
        return jwt.decode(token, key, algorithms=["RS256"], audience=AUDIENCE if VERIFY_AUD else None,
                          issuer=common.ISSUER, options=opts)
    except (jwt.PyJWTError, KeyError) as e:
        raise Unauthenticated(type(e).__name__) from e


@app.get("/v1/me")
async def me(p: Annotated[dict[str, Any], Depends(principal)]) -> dict[str, Any]:
    return {"sub": p["sub"], "azp": p["azp"], "preferred_username": p.get("preferred_username")}


async def main() -> None:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="warning"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    at, wt = common.alex_token(), common.worker_token()
    print(f"verify_aud={VERIFY_AUD} audience={AUDIENCE!r}")
    async with httpx2.AsyncClient(base_url="http://127.0.0.1:8000") as c:
        for label, hdrs in [("no header", {}), ("garbage", {"Authorization": "Bearer abc"}),
                            ("Basic scheme", {"Authorization": "Basic Zm9vOmJhcg=="}),
                            ("alex persona", {"Authorization": f"Bearer {at}"}),
                            ("ops-worker", {"Authorization": f"Bearer {wt}"})]:
            r = await c.get("/v1/me", headers=hdrs)
            body = r.json()
            body.pop("sub", None)  # keep ids out of the log
            print(f"{label:13s} -> {r.status_code} {body} www-authenticate={r.headers.get('www-authenticate')}")
    # in-process alternative without a socket
    from fastapi.testclient import TestClient
    with TestClient(app) as tc:
        print("TestClient (starlette.testclient over httpx2):", tc.get("/v1/me").status_code)
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://t") as ac:
        print("httpx2.ASGITransport:", (await ac.get("/v1/me", headers={"Authorization": f"Bearer {at}"})).status_code)
    server.should_exit = True
    await task


asyncio.run(main())
```

Output (`m6.out`, both runs):

```text
verify_aud=True audience='ops-api'
no header     -> 401 {'code': 'UNAUTHENTICATED', 'message': 'authentication required', 'reason': 'missing bearer token'} www-authenticate=Bearer
garbage       -> 401 {'code': 'UNAUTHENTICATED', 'message': 'authentication required', 'reason': 'DecodeError'} www-authenticate=Bearer
Basic scheme  -> 401 {'code': 'UNAUTHENTICATED', 'message': 'authentication required', 'reason': 'missing bearer token'} www-authenticate=Bearer
alex persona  -> 401 {'code': 'UNAUTHENTICATED', 'message': 'authentication required', 'reason': 'MissingRequiredClaimError'} www-authenticate=Bearer
ops-worker    -> 401 {'code': 'UNAUTHENTICATED', 'message': 'authentication required', 'reason': 'InvalidAudienceError'} www-authenticate=Bearer
TestClient (starlette.testclient over httpx2): 401
httpx2.ASGITransport: 401
verify_aud=False audience='ops-api'
no header     -> 401 {'code': 'UNAUTHENTICATED', 'message': 'authentication required', 'reason': 'missing bearer token'} www-authenticate=Bearer
garbage       -> 401 {'code': 'UNAUTHENTICATED', 'message': 'authentication required', 'reason': 'DecodeError'} www-authenticate=Bearer
Basic scheme  -> 401 {'code': 'UNAUTHENTICATED', 'message': 'authentication required', 'reason': 'missing bearer token'} www-authenticate=Bearer
alex persona  -> 200 {'azp': 'ops-dev-direct', 'preferred_username': 'alex'} www-authenticate=None
ops-worker    -> 200 {'azp': 'ops-worker', 'preferred_username': 'service-account-ops-worker'} www-authenticate=None
TestClient (starlette.testclient over httpx2): 401
httpx2.ASGITransport: 200
```

## Resolved versions (scratch `uv lock`)

Fake workspace `<scratch>/ws` contains copies of `pyproject.toml`, `uv.lock` and `.python-version`, plus every member's `pyproject.toml` with an empty `src/ops_<pkg>/__init__.py`. Dependencies added there:
- core: `pydantic>=2.13,<3`, `psycopg[binary]>=3.3,<4`, `sqlalchemy>=2.1,<3`, `alembic>=1.20,<2`, `pyjwt[crypto]>=2.10,<3`, `httpx2>=2.13,<3`
- api and incident-sim: `fastapi>=0.142,<1`, `uvicorn>=0.54,<1`
- worker, mcp-read, mcp-write: `mcp==2.3.0`, `uvicorn>=0.54,<1`

`uv lock` (uv 0.11.8) **resolved with no conflict**: "Resolved 63 packages in 201ms". Every change was an `Added`; no existing locked package was updated or removed. The `sqlalchemy>=2.1` fallback to `>=2.0` was not needed.

New packages and versions: alembic 1.20.0, annotated-doc 0.0.5, anyio 4.15.1, cffi 2.1.1, click 8.5.0, cryptography 50.0.2, fastapi 0.142.4, h11 0.16.0, httpcore2 2.13.1, httpx2 2.13.1, httpx2-jsfetch 1.0 (marker `sys_platform == 'emscripten'` only), idna 3.20, mako 1.4.3, markupsafe 3.0.4, mcp 2.3.0, mcp-types 2.3.0, opentelemetry-api 1.45.1, psycopg 3.3.6, psycopg-binary 3.3.6, pycparser 3.0, pyjwt 2.15.1, python-multipart 0.0.32, pywin32 312 (win32 marker), sqlalchemy 2.1.4, sse-starlette 3.5.0, starlette 1.7.0, truststore 0.10.4, tzdata 2026.5, uvicorn 0.54.0. Plain `httpx` is **not** in the lock: neither mcp nor starlette's test client needs it.

Key versions: mcp 2.3.0, fastapi 0.142.4, starlette 1.7.0, uvicorn 0.54.0, psycopg 3.3.6, sqlalchemy 2.1.4, alembic 1.20.0, pyjwt 2.15.1, httpx2 2.13.1.

`uv lock` output:

```text
Using CPython 3.13.13
Resolved 63 packages in 201ms
Added alembic v1.20.0
Added annotated-doc v0.0.5
Added anyio v4.15.1
Added cffi v2.1.1
Added click v8.5.0
Added cryptography v50.0.2
Added fastapi v0.142.4
Added h11 v0.16.0
Added httpcore2 v2.13.1
Added httpx2 v2.13.1
Added httpx2-jsfetch v1.0
Added idna v3.20
Added mako v1.4.3
Added markupsafe v3.0.4
Added mcp v2.3.0
Added mcp-types v2.3.0
Added opentelemetry-api v1.45.1
Added psycopg v3.3.6
Added psycopg-binary v3.3.6
Added pycparser v3.0
Added pyjwt v2.15.1
Added python-multipart v0.0.32
Added pywin32 v312
Added sqlalchemy v2.1.4
Added sse-starlette v3.5.0
Added starlette v1.7.0
Added truststore v0.10.4
Added tzdata v2026.5
Added uvicorn v0.54.0
```

The repository's own `uv.lock` was not touched; `git status` in the repository shows only the untracked `docs/superpowers/research/` directory.

## Stack state

The dev stack was started with `uv run python scripts/bootstrap_dev.py up` (output: "secrets: 0 created, 12 kept", both containers `Healthy`, "bootstrap admin: deleted") and is **left running**:

```text
SERVICE    STATUS                   PORTS
keycloak   Up (healthy)             127.0.0.1:18080->8080/tcp
postgres   Up (healthy)             127.0.0.1:15432->5432/tcp
```

Spike leftovers in the stack: none. Schemas `spike` (ops) and `spike2` (incident), the roles `spike_role*` and `public.alembic_version` in `incident` were all dropped, and no spike server is listening on 8081, 8070 or 8000. The spike venv remains at `<venv>`, outside the repository.

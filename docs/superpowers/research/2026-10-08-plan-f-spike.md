# Plan F spike: measured login, logout, admin-API, session, CSRF, replay, membership-sync and log-redaction behaviour

Date: 2026-10-08. Branch `plan-e` (HEAD `b6a0b49`). This was a throwaway spike for T11. Every script lives in `<scratch>` (the session scratchpad's `spike-f/` directory) and ran from `<repo>` as `uv run --with authlib==1.8.0 python <scratch>/<script>`, so FastAPI, Starlette, uvicorn, httpx2, psycopg and PyJWT came from the repository's lock and only authlib (with its dependency joserfc) was added for the run. `pyproject.toml` and `uv.lock` were not touched. The scripts ran against the live dev stack: the identity provider at `http://localhost:18080`, realm `ops-dev`, and PostgreSQL at `127.0.0.1:15432`. The repository was not modified; this report is the only file written there.

No secret appears below. Scripts read secrets only through `ops_core.settings.read_secret` (`kc_client_secret_ops_web`, `kc_client_secret_ops_view_users`, `kc_persona_alex_password`, `postgres_password`). Output shows lengths, prefixes of at most 6 characters, claim names and status codes. After the runs every secret file's value was grep-checked against every script and output file, and none matched. The scratch LOGIN roles and the throwaway identity provider got per-run `secrets.token_urlsafe` passwords that were never printed.

What was created, and removed at the end:

- **Dev realm `ops-dev`:** nothing. It has no admin user, and the `ops-view-users` account can only read.
- **A throwaway identity-provider container `spike_kc`** (the same 26.8.0 image, on `127.0.0.1:18081`), with realm `spike_realm`, client `spike_web` and user `spike_user`. This was the only way to configure a back-channel logout URL and watch a real `logout_token` arrive (measurement 2B).
- **PostgreSQL:** schema `spike_app` in database `ops`, and roles `spike_owner`, `spike_definer`, `spike_api` and `spike_sweeper`.
- **The one change outside a `spike_*` object:** `GRANT CONNECT ON DATABASE ops` to `spike_api` and `spike_sweeper`, because T09 revoked CONNECT from PUBLIC. `DROP OWNED BY` revoked it again, and the `ops` ACL before setup and after cleanup is identical.

Schema `app` was never touched. The persona logins also left short-lived user sessions for `alex` in `ops-dev`. They are not realm objects and expire after the 30-minute SSO idle time (`refresh_expires_in` 1800).

Versions: identity provider 26.8.0. From the lock: FastAPI 0.143.0, Starlette 1.7.0, uvicorn 0.54.0, httpx2 2.13.1, psycopg 3.3.6, PyJWT 2.15.1. Added by `--with`: authlib 1.8.0 (requires `cryptography>=45.0.1`, `joserfc>=1.6.1`) and joserfc 1.7.5. CPython 3.13.13. PostgreSQL 17.11.

## Summary

| # | Measurement | Result |
|---|---|---|
| 1 | Code + PKCE (S256) + state + nonce against `ops-web`, no browser; id_token validation; wrong state, reused code, nonce/iss/aud tampering | **Works.** Gotchas below. authlib 1.8.0's `authlib.integrations.httpx_client.OAuth2Client` is built on **httpx2**. `OAuth2Session` is the `requests` integration, and `requests` is not installed. PKCE is enforced by the realm. `http://127.0.0.1:18000/callback` gets **400 `Invalid parameter: redirect_uri`**; only `http://localhost:8000/auth/callback` is registered. The login form sets its cookies **`Secure; SameSite=None` over http**, and the stdlib cookie jar will not send them back, so a scripted login must forward them by hand. A wrong `code_verifier` **burns the code**. A reused code gets `invalid_grant` **and revokes the session** created by the first exchange. Lifetimes: access and id 300 s, refresh 1800 s. `sid` is in the id, access and refresh tokens. The **access token has no `aud`**. Through `parse_id_token`: nonce mismatch gives `InvalidClaimError('nonce')`, a tampered payload `BadSignatureError`, a tampered iss option `InvalidClaimError('iss')`, and another client_id `InvalidClaimError('azp')`. **`nonce=None` is silently accepted**. **`aud` is never compared with client_id** unless `claims_options` names it |
| 2 | Back-channel logout and `end_session_endpoint` | Discovery: `backchannel_logout_supported` and `backchannel_logout_session_supported` are both `True`. **ops-dev cannot get a back-channel URL today**: there is no admin, and `GET .../clients` with the view-users account is 403, so it needs a realm-JSON change (given below). On `spike_kc` a real logout arrives as form field `logout_token`, a JWT with header `typ: logout+jwt` (RS256, kid) and claims `aud, events, exp, iat, iss, jti, sid, sub, typ` (`typ` = `Logout`, `exp − iat` = 120, no `nonce`). It is sent **synchronously, once, with no retry** (a 500 answer still ends the IdP session), from all three logout paths, including to the client that started the logout. `end_session` with **only an `id_token_hint` and no cookies ends the session with no confirmation** (200 "You are logged out"; 302 with a registered `post_logout_redirect_uri`). Back-end `POST .../logout` (client auth + `refresh_token`) gives 204 and is idempotent. `sid` equals the callback's `session_state` and is distinct per login, and logging out one sid leaves the other session alive. `host.docker.internal:18000` reaches a uvicorn bound to `127.0.0.1` from both containers. The image has no curl, wget, nc or python3, but `bash /dev/tcp` works |
| 3 | Admin-API enabled check with `ops-view-users` | **Works, fail-closed as designed, with one large trap.** Token: `expires_in` 300, no refresh token, `aud: realm-management`, roles `query-groups, query-users, view-users`. `GET /users/{id}` gives 200 with `enabled, id, username` and nine more fields (personal data included). An unknown or non-UUID id gives **404 `{"error": "User not found"}`**. `PUT` gives **403**, and `POST /users/{id}/logout` gives 403 (least privilege holds). `GET /users/{id}/sessions` gives 200. Median latency **5.5 ms warm**, but **≈2 020 ms on every new connection to `localhost`** (`::1` is tried first, and the published port is IPv4-only). On `127.0.0.1` it is 8 ms. Unreachable: on this host a refused port surfaces as **`httpx2.ConnectTimeout` at the timeout (2.01 s)**, and through `localhost` it takes **4.01 s** with `timeout=2`. A hung server gives `ReadTimeout` at 2.02 s. All of these subclass `httpx2.TransportError` |
| 4 | Cookies, TestClient, Origin + double-submit CSRF; `sessions` under the AM-20.2 grants | `set_cookie` defaults: `path="/"`, **`samesite="lax"`**, `httponly=False`, `secure=False`, and no `max_age` (a browser-session cookie). TestClient keeps cookies across requests and **sends no `Origin` or `Referer`**. It **does not send `Secure` cookies to `http://testserver`**, so use `base_url="https://testserver"`. Per-request `cookies=` raises a DeprecationWarning. The CSRF and Origin middleware rejects a missing Origin, a wrong token, an evil Origin and `Origin: null`. The `api` cells work for INSERT, lookup by hash, touching `last_seen_at`, revoking by `(issuer, subject)` and DELETE. **`expires_at` cannot be updated** (no sliding expiry). The table has **no `sid` column** and **no row shape for pre-login state** (`subject` and `tenant_id` are NOT NULL). **A DELETE-only sweeper gets 42501 on any `WHERE` that reads a column** and needs `SELECT (expires_at, revoked_at)`, which confirms Plan E's finding |
| 5 | `jti` replay store; `sync_memberships` shape | Insert-only role: target-less `ON CONFLICT DO NOTHING` returns **rowcount 1, then 0 on replay**. `ON CONFLICT (jti)` and `RETURNING` give 42501, and so does a DELETE of expired rows. A rolled-back insert does not consume the jti. Membership sync: the sweeper's `SELECT … FOR UPDATE` works with its column UPDATE grant. **As a SECURITY DEFINER function under the AM-20.2 cells it fails with 42501**, because `app_definer` has only SELECT on `memberships`. With an added `UPDATE (active, permission_version, synced_at)` grant it works **only by iterating tenants with `set_config('app.tenant_id', …)`**: the definer is filtered by `tenant_isolation` and sees 0 rows, and `sweeper_all` is `TO sweeper`. A SECURITY INVOKER version works through `sweeper_all` |
| 6 | Log redaction | uvicorn's access record is `msg='%s - "%s %s HTTP/%s" %d'` with a 5-tuple `args` whose path **includes the query string**, so `?code=` is logged raw. A filter that rewrites `msg`/`args` on the `uvicorn.access` logger or its handler redacts it. **A canary in an exception message (and a `Bearer` value) passes through `log.exception` and uvicorn's `Exception in ASGI application`** unless the filter also rewrites `exc_text` and clears `exc_info`. A filter on a parent *logger* does not see records propagated from child loggers, so attach it to the *handlers* |

The common helper `common.py` is imported by every script. Its own job is to send the login form's cookies explicitly (measurement 1 explains why):

```python
"""Shared spike helpers. Secrets come only from ops_core.settings.read_secret and are never printed."""
import json
import os
import re
import secrets
import statistics
from pathlib import Path

REPO = Path(r"<repo>")
for _line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
    if _line.startswith("OPS_SECRETS_DIR=") and not os.environ.get("OPS_SECRETS_DIR"):
        os.environ["OPS_SECRETS_DIR"] = _line.split("=", 1)[1].strip()

import psycopg  # noqa: E402
from ops_core.settings import read_secret  # noqa: E402

KC = "http://localhost:18080"
REALM = "ops-dev"
ISSUER = f"{KC}/realms/{REALM}"
OIDC = f"{ISSUER}/protocol/openid-connect"
DISCOVERY = f"{ISSUER}/.well-known/openid-configuration"
REDIRECT_REGISTERED = "http://localhost:8000/auth/callback"


def short(v) -> str:
    """At most a 6-character prefix plus the length: enough to compare, never enough to reuse."""
    s = str(v)
    return f"{s[:6]}...(len={len(s)})"


def unverified_claims(jwt_str: str) -> dict:
    import base64
    payload = jwt_str.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


def unverified_header(jwt_str: str) -> dict:
    import base64
    h = jwt_str.split(".")[0]
    h += "=" * (-len(h) % 4)
    return json.loads(base64.urlsafe_b64decode(h))


def su(dbname: str = "ops", autocommit: bool = True) -> psycopg.Connection:
    return psycopg.connect(host="127.0.0.1", port=15432, dbname=dbname, user="ops",
                           password=read_secret("postgres_password"), autocommit=autocommit)


SPIKE_PW = secrets.token_urlsafe(24)  # scratch LOGIN password, per run, never printed


def as_role(role: str, autocommit: bool = False) -> psycopg.Connection:
    return psycopg.connect(host="127.0.0.1", port=15432, dbname="ops", user=role, password=SPIKE_PW,
                           autocommit=autocommit)


def try_(label, fn):
    try:
        r = fn()
        print(f"{label}: OK -> {r}")
        return r
    except psycopg.Error as e:
        print(f"{label}: {type(e).__name__} sqlstate={e.sqlstate} primary={e.diag.message_primary!r}")
        return e


def median_ms(samples):
    return round(statistics.median(samples) * 1000, 1)


FORM_ACTION = re.compile(r'<form[^>]*id="kc-form-login"[^>]*action="([^"]+)"', re.S)
HIDDEN = re.compile(r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', re.S)


def kc_login(client, auth_url: str, username: str, password: str):
    """Drive the Keycloak login form: GET the auth URL, POST the credentials, return the final response (302)."""
    import html
    r = client.get(auth_url)
    m = FORM_ACTION.search(r.text)
    if not m:
        return r, None
    action = html.unescape(m.group(1))
    fields = {k: html.unescape(v) for k, v in HIDDEN.findall(r.text)}
    fields.update(username=username, password=password, credentialId="")
    # Keycloak 26 marks its cookies Secure even over http; the stdlib cookie jar then never sends them on an http
    # URL (a browser treats http://localhost as a secure context and does). Send them explicitly.
    r2 = client.post(action, data=fields, headers={"Cookie": cookie_header(client)})
    return r, r2


def cookie_header(client) -> str:
    return "; ".join(f"{c.name}={c.value}" for c in client.cookies.jar)
```

## 1. Authorization code + PKCE against the live realm

Script `m1_code_flow.py`:

```python
"""M1: authorization code + PKCE (S256) + state + nonce against the live realm, no browser; id_token validation."""
import asyncio
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).parent))
from common import (DISCOVERY, ISSUER, REDIRECT_REGISTERED, kc_login, read_secret, short,  # noqa: E402
                    unverified_claims, unverified_header)

import httpx2  # noqa: E402
from authlib.common.security import generate_token  # noqa: E402
from authlib.integrations.httpx_client import OAuth2Client, OAuthError  # noqa: E402
from authlib.oidc.core import CodeIDToken  # noqa: E402
from joserfc import jwt  # noqa: E402
from joserfc.jwk import KeySet  # noqa: E402

SECRET = read_secret("kc_client_secret_ops_web")
ALEX_PW = read_secret("kc_persona_alex_password")
meta = httpx2.get(DISCOVERY).json()
AUTH, TOKEN = meta["authorization_endpoint"], meta["token_endpoint"]
print("discovery: issuer == ISSUER:", meta["issuer"] == ISSUER,
      "| code_challenge_methods:", meta.get("code_challenge_methods_supported"),
      "| id_token algs:", meta.get("id_token_signing_alg_values_supported"),
      "| authorization_response_iss_parameter_supported:", meta.get("authorization_response_iss_parameter_supported"))


def oauth(redirect_uri=REDIRECT_REGISTERED):
    return OAuth2Client(client_id="ops-web", client_secret=SECRET, redirect_uri=redirect_uri, scope="openid",
                        code_challenge_method="S256", timeout=5)


def start(redirect_uri=REDIRECT_REGISTERED, pkce=True):
    c = oauth(redirect_uri)
    cv, nonce = generate_token(48), generate_token(20)
    url, state = c.create_authorization_url(AUTH, code_verifier=cv if pkce else None, nonce=nonce)
    return c, url, state, cv, nonce


print("\n-- authorization URL built by authlib")
c, url, state, cv, nonce = start()
q = parse_qs(urlsplit(url).query)
print("params:", sorted(q), "| code_challenge_method:", q["code_challenge_method"], "| state len:", len(state),
      "| code_verifier len:", len(cv), "| code_challenge len:", len(q["code_challenge"][0]))

print("\n-- redirect_uri http://127.0.0.1:18000/callback (not registered)")
_, u2, *_ = start("http://127.0.0.1:18000/callback")
with httpx2.Client(follow_redirects=False, timeout=5) as b:
    r = b.get(u2)
    import re
    msg = re.search(r'class="[^"]*kc-feedback-text[^"]*">([^<]+)<', r.text) or re.search(r"<p[^>]*>(Invalid[^<]+)<", r.text)
    print("status:", r.status_code, "| page message:", msg.group(1).strip() if msg else r.text[:0])

print("\n-- no PKCE (client attribute pkce.code.challenge.method=S256)")
_, u3, *_ = start(pkce=False)
with httpx2.Client(follow_redirects=False, timeout=5) as b:
    r = b.get(u3)
    loc = r.headers.get("location", "")
    lq = parse_qs(urlsplit(loc).query)
    print("status:", r.status_code, "| redirect to registered callback:", loc.startswith(REDIRECT_REGISTERED),
          "| error:", lq.get("error"), "| error_description:", lq.get("error_description"))

print("\n-- login form driven by httpx2 (alex)")
t0 = time.perf_counter()
with httpx2.Client(follow_redirects=False, timeout=5) as b:
    r1, r2 = kc_login(b, url, "alex", ALEX_PW)
    print("GET auth:", r1.status_code, "| POST credentials:", r2.status_code,
          "| cookie names in the jar after both:", sorted(b.cookies.keys()))
    loc = r2.headers["location"]
cb = parse_qs(urlsplit(loc).query)
print("callback target:", loc.split("?")[0], "| query params:", sorted(cb), "| state echoed:", cb["state"][0] == state,
      "| iss param == issuer:", cb.get("iss", [None])[0] == ISSUER, "| code:", short(cb["code"][0]),
      f"| login round trip {time.perf_counter() - t0:.2f}s")

print("\n-- wrong state at fetch_token (authlib checks before any network call)")
try:
    oauth().fetch_token(TOKEN, authorization_response=loc, state="not-the-state", code_verifier=cv)
except Exception as e:
    print("raised:", type(e).__module__ + "." + type(e).__name__, "|", getattr(e, "error", ""), "|", str(e)[:80])

print("\n-- wrong code_verifier (consumes the code? then the right one)")
try:
    oauth().fetch_token(TOKEN, authorization_response=loc, state=state, code_verifier=generate_token(48))
except OAuthError as e:
    print("raised:", type(e).__name__, "| error:", e.error, "| description:", e.description)
try:
    oauth().fetch_token(TOKEN, authorization_response=loc, state=state, code_verifier=cv)
    print("right verifier after a wrong one: OK")
except OAuthError as e:
    print("right verifier after a wrong one:", type(e).__name__, "| error:", e.error, "| description:", e.description)

print("\n-- fresh login, exchange with the right verifier")
c, url, state, cv, nonce = start()
with httpx2.Client(follow_redirects=False, timeout=5) as b:
    _, r2 = kc_login(b, url, "alex", ALEX_PW)
    loc = r2.headers["location"]
tok = c.fetch_token(TOKEN, authorization_response=loc, code_verifier=cv)
print("token keys:", sorted(tok), "| token_type:", tok["token_type"], "| expires_in:", tok["expires_in"],
      "| refresh_expires_in:", tok.get("refresh_expires_in"), "| scope:", tok.get("scope"))
idc, atc = unverified_claims(tok["id_token"]), unverified_claims(tok["access_token"])
print("id_token header:", {k: (v if k != "kid" else short(v)) for k, v in unverified_header(tok["id_token"]).items()})
print("id_token claims:", sorted(idc))
print("access_token claims:", sorted(atc))
print("id_token: aud =", idc["aud"], "| azp =", idc["azp"], "| typ =", idc.get("typ"), "| exp-iat =", idc["exp"] - idc["iat"],
      "| nonce matches:", idc.get("nonce") == nonce, "| sid present:", "sid" in idc)
print("access_token: aud =", atc.get("aud"), "| azp =", atc["azp"], "| typ =", atc.get("typ"), "| exp-iat =", atc["exp"] - atc["iat"],
      "| sid == id_token sid:", atc.get("sid") == idc.get("sid"), "| sub == id_token sub:", atc["sub"] == idc["sub"],
      "| preferred_username:", atc.get("preferred_username"))
print("refresh_token claims:", sorted(unverified_claims(tok["refresh_token"])),
      "| typ =", unverified_claims(tok["refresh_token"]).get("typ"),
      "| exp-iat =", unverified_claims(tok["refresh_token"])["exp"] - unverified_claims(tok["refresh_token"])["iat"])

print("\n-- reused code")
try:
    oauth().fetch_token(TOKEN, authorization_response=loc, code_verifier=cv)
    print("second exchange: OK (!)")
except OAuthError as e:
    print("second exchange raised:", type(e).__name__, "| error:", e.error, "| description:", e.description)
ui = httpx2.get(meta["userinfo_endpoint"], headers={"Authorization": f"Bearer {tok['access_token']}"}, timeout=5)
print("userinfo with the first access token after the reuse:", ui.status_code, ui.headers.get("www-authenticate", "")[-40:])
rr = httpx2.post(TOKEN, auth=("ops-web", SECRET), data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]}, timeout=5)
print("refresh with the first refresh_token after the reuse:", rr.status_code, rr.json().get("error"), rr.json().get("error_description"))

print("\n-- id_token validation: authlib starlette OAuth app .parse_id_token (no request/session needed)")
from authlib.integrations.starlette_client import OAuth  # noqa: E402

c, url, state, cv, nonce = start()
with httpx2.Client(follow_redirects=False, timeout=5) as b:
    _, r2 = kc_login(b, url, "alex", ALEX_PW)
    loc = r2.headers["location"]
tok = c.fetch_token(TOKEN, authorization_response=loc, code_verifier=cv)

reg = OAuth()
reg.register("kc", client_id="ops-web", client_secret=SECRET, server_metadata_url=DISCOVERY,
             client_kwargs={"scope": "openid", "code_challenge_method": "S256"})


async def parse(nonce_, **kw):
    return await reg.kc.parse_id_token(tok, nonce_, **kw)


def attempt(label, coro_fn):
    try:
        ui = asyncio.run(coro_fn())
        print(f"{label}: OK -> type {type(ui).__name__}, keys {sorted(ui)}")
    except Exception as e:
        print(f"{label}: {type(e).__module__}.{type(e).__name__}: {str(e)[:110]}")


attempt("right nonce", lambda: parse(nonce))
attempt("nonce mismatch", lambda: parse("other-nonce"))
attempt("nonce None", lambda: parse(None))
attempt("iss option tampered", lambda: parse(nonce, claims_options={"iss": {"values": ["http://evil/realms/x"]}}))
reg.register("kc_wrong_aud", client_id="some-other-client", client_secret=SECRET, server_metadata_url=DISCOVERY)
attempt("aud mismatch (client_id other)", lambda: reg.kc_wrong_aud.parse_id_token(tok, nonce))

# Tamper the payload (iss) without re-signing.
import base64, json  # noqa: E401,E402
h, p, s = tok["id_token"].split(".")
claims = unverified_claims(tok["id_token"]); claims["iss"] = "http://evil/realms/x"
p2 = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
tampered = dict(tok, id_token=".".join([h, p2, s]))
attempt("payload iss tampered (signature broken)", lambda: reg.kc.parse_id_token(tampered, nonce))
tampered_at = dict(tok, access_token=tok["access_token"][:-4] + "AAAA")
attempt("access_token swapped (at_hash)", lambda: reg.kc.parse_id_token(tampered_at, nonce))

print("\n-- the same validation by hand (joserfc + CodeIDToken), for an endpoint that does not use the registry")
jwks = KeySet.import_key_set(httpx2.get(meta["jwks_uri"]).json())
dec = jwt.decode(tok["id_token"], jwks, algorithms=["RS256"])
ct = CodeIDToken(dec.claims, dec.header, {"iss": {"values": [ISSUER]}},
                 {"nonce": nonce, "client_id": "ops-web", "access_token": tok["access_token"]})
ct.validate(leeway=0)
print("manual validate OK; claims checked by CodeIDToken.validate:", "iss aud exp iat auth_time nonce acr amr azp at_hash")
for k in ("sid", "nonce", "aud", "azp", "iss", "exp", "sub", "preferred_username", "at_hash", "auth_time", "acr", "session_state"):
    print(f"  {k:<20} present={k in dec.claims}")
print("sub looks like a UUID:", len(dec.claims["sub"]) == 36 and dec.claims["sub"].count("-") == 4)

print("\n-- Starlette integration authorize_redirect without SessionMiddleware")
from starlette.requests import Request  # noqa: E402

scope = {"type": "http", "method": "GET", "path": "/login", "headers": [], "query_string": b"",
         "server": ("127.0.0.1", 18000), "scheme": "http", "root_path": "", "app": None}
try:
    asyncio.run(reg.kc.authorize_redirect(Request(scope), REDIRECT_REGISTERED))
except Exception as e:
    print("raised:", type(e).__name__, "|", str(e)[:100])

print("\n-- authlib CodeIDToken: what it checks about aud/azp, nonce and exp (own RSA key, synthetic claims)")
from joserfc.jwk import RSAKey  # noqa: E402

k = RSAKey.generate_key(2048)
now = int(time.time())
base = {"iss": ISSUER, "sub": "s", "aud": "ops-web", "azp": "ops-web", "exp": now + 300, "iat": now, "nonce": "n1"}


def check(label, claims, opts=None, params=None):
    t = jwt.encode({"alg": "RS256"}, claims, k)
    d = jwt.decode(t, k, algorithms=["RS256"])
    try:
        CodeIDToken(d.claims, d.header, opts if opts is not None else {"iss": {"values": [ISSUER]}},
                    params or {"nonce": "n1", "client_id": "ops-web"}).validate(leeway=0)
        print(f"{label}: accepted")
    except Exception as e:
        print(f"{label}: {type(e).__name__}: {e}")


check("baseline", base)
check("aud=['other'], azp='ops-web', no aud option", dict(base, aud=["other"]))
check("aud=['other'], azp='ops-web', with aud option", dict(base, aud=["other"]),
      {"iss": {"values": [ISSUER]}, "aud": {"values": ["ops-web"]}})
check("aud=['other'] and no azp, no aud option", {k_: v for k_, v in dict(base, aud=["other"]).items() if k_ != "azp"})
check("aud=['ops-web','other'] azp='ops-web'", dict(base, aud=["ops-web", "other"]))
check("nonce claim missing, nonce param given", {k_: v for k_, v in base.items() if k_ != "nonce"})
check("nonce claim present, nonce param None", base, params={"nonce": None, "client_id": "ops-web"})
check("expired 10 s ago, leeway 0", dict(base, exp=now - 10))
check("iat 10 min in the future", dict(base, iat=now + 600))
check("no iss option at all, iss evil", dict(base, iss="http://evil"), opts={})
```

Output (complete):

```text
discovery: issuer == ISSUER: True | code_challenge_methods: ['plain', 'S256'] | id_token algs: ['PS384', 'RS384', 'EdDSA', 'ES384', 'HS256', 'HS512', 'ES256', 'RS256', 'HS384', 'ES512', 'PS256', 'PS512', 'RS512'] | authorization_response_iss_parameter_supported: True

-- authorization URL built by authlib
params: ['client_id', 'code_challenge', 'code_challenge_method', 'nonce', 'redirect_uri', 'response_type', 'scope', 'state'] | code_challenge_method: ['S256'] | state len: 30 | code_verifier len: 48 | code_challenge len: 43

-- redirect_uri http://127.0.0.1:18000/callback (not registered)
status: 400 | page message: Invalid parameter: redirect_uri

-- no PKCE (client attribute pkce.code.challenge.method=S256)
status: 302 | redirect to registered callback: True | error: ['invalid_request'] | error_description: ['Missing parameter: code_challenge_method']

-- login form driven by httpx2 (alex)
GET auth: 200 | POST credentials: 302 | cookie names in the jar after both: ['AUTH_SESSION_ID', 'KC_AUTH_SESSION_HASH', 'KEYCLOAK_IDENTITY', 'KEYCLOAK_SESSION']
callback target: http://localhost:8000/auth/callback | query params: ['code', 'iss', 'session_state', 'state'] | state echoed: True | iss param == issuer: True | code: 207a96...(len=98) | login round trip 2.09s

-- wrong state at fetch_token (authlib checks before any network call)
raised: authlib.oauth2.rfc6749.errors.MismatchingStateException | mismatching_state | mismatching_state: CSRF Warning! State not equal in request and response.

-- wrong code_verifier (consumes the code? then the right one)
raised: OAuthError | error: invalid_grant | description: PKCE verification failed: Code mismatch
right verifier after a wrong one: OAuthError | error: invalid_grant | description: Code not valid

-- fresh login, exchange with the right verifier
token keys: ['access_token', 'expires_at', 'expires_in', 'id_token', 'not-before-policy', 'refresh_expires_in', 'refresh_token', 'scope', 'session_state', 'token_type'] | token_type: Bearer | expires_in: 300 | refresh_expires_in: 1800 | scope: openid email profile
id_token header: {'alg': 'RS256', 'typ': 'JWT', 'kid': 'b7H_aM...(len=43)'}
id_token claims: ['acr', 'at_hash', 'aud', 'auth_time', 'azp', 'email', 'email_verified', 'exp', 'family_name', 'given_name', 'iat', 'iss', 'jti', 'name', 'nonce', 'preferred_username', 'sid', 'sub', 'typ']
access_token claims: ['acr', 'allowed-origins', 'auth_time', 'azp', 'email', 'email_verified', 'exp', 'family_name', 'given_name', 'iat', 'iss', 'jti', 'name', 'preferred_username', 'realm_access', 'scope', 'sid', 'sub', 'typ']
id_token: aud = ops-web | azp = ops-web | typ = ID | exp-iat = 300 | nonce matches: True | sid present: True
access_token: aud = None | azp = ops-web | typ = Bearer | exp-iat = 300 | sid == id_token sid: True | sub == id_token sub: True | preferred_username: alex
refresh_token claims: ['aud', 'azp', 'exp', 'iat', 'iss', 'jti', 'prov', 'scope', 'sid', 'sub', 'typ'] | typ = Refresh | exp-iat = 1800

-- reused code
second exchange raised: OAuthError | error: invalid_grant | description: Code not valid
userinfo with the first access token after the reuse: 401 ror_description="user_session_not_found"
refresh with the first refresh_token after the reuse: 400 invalid_grant Session doesn't have required client

-- id_token validation: authlib starlette OAuth app .parse_id_token (no request/session needed)
right nonce: OK -> type UserInfo, keys ['acr', 'at_hash', 'aud', 'auth_time', 'azp', 'email', 'email_verified', 'exp', 'family_name', 'given_name', 'iat', 'iss', 'jti', 'name', 'nonce', 'preferred_username', 'sid', 'sub', 'typ']
nonce mismatch: joserfc.errors.InvalidClaimError: invalid_claim: Invalid claim: 'nonce'
nonce None: OK -> type UserInfo, keys ['acr', 'at_hash', 'aud', 'auth_time', 'azp', 'email', 'email_verified', 'exp', 'family_name', 'given_name', 'iat', 'iss', 'jti', 'name', 'nonce', 'preferred_username', 'sid', 'sub', 'typ']
iss option tampered: joserfc.errors.InvalidClaimError: invalid_claim: Invalid claim: 'iss'
aud mismatch (client_id other): joserfc.errors.InvalidClaimError: invalid_claim: Invalid claim: 'azp'
payload iss tampered (signature broken): joserfc.errors.BadSignatureError: bad_signature: 
access_token swapped (at_hash): joserfc.errors.InvalidClaimError: invalid_claim: Invalid claim: 'at_hash'

-- the same validation by hand (joserfc + CodeIDToken), for an endpoint that does not use the registry
manual validate OK; claims checked by CodeIDToken.validate: iss aud exp iat auth_time nonce acr amr azp at_hash
  sid                  present=True
  nonce                present=True
  aud                  present=True
  azp                  present=True
  iss                  present=True
  exp                  present=True
  sub                  present=True
  preferred_username   present=True
  at_hash              present=True
  auth_time            present=True
  acr                  present=True
  session_state        present=False
sub looks like a UUID: True

-- Starlette integration authorize_redirect without SessionMiddleware
raised: AssertionError | SessionMiddleware must be installed to access request.session

-- authlib CodeIDToken: what it checks about aud/azp, nonce and exp (own RSA key, synthetic claims)
baseline: accepted
aud=['other'], azp='ops-web', no aud option: accepted
aud=['other'], azp='ops-web', with aud option: InvalidClaimError: invalid_claim: Invalid claim: 'aud'
aud=['other'] and no azp, no aud option: MissingClaimError: missing_claim: Missing claim: 'azp'
aud=['ops-web','other'] azp='ops-web': accepted
nonce claim missing, nonce param given: MissingClaimError: missing_claim: Missing claim: 'nonce'
nonce claim present, nonce param None: accepted
expired 10 s ago, leeway 0: ExpiredTokenError: expired_token: The token is expired
iat 10 min in the future: InvalidClaimError: invalid_claim: The token was issued in the future
no iss option at all, iss evil: accepted
```

The first attempt without the explicit `Cookie` header failed. That debug run (`dbg_login.py`, kept in `<scratch>`) printed:

```text
set-cookie AUTH_SESSION_ID attrs: ['Version=1', 'Path=/realms/ops-dev/', 'Secure', 'HttpOnly', 'SameSite=None']
set-cookie KC_AUTH_SESSION_HASH attrs: ['Version=1', 'Path=/realms/ops-dev/', 'Max-Age=60', 'Secure', 'SameSite=None']
set-cookie KC_RESTART attrs: ['Version=1', 'Path=/realms/ops-dev/', 'Secure', 'HttpOnly', 'SameSite=None']
form action host/path: http://localhost:18080/realms/ops-dev/login-actions/authenticate
hidden: []
inputs: ['username', 'password', 'credentialId']
400 [('', '', 'Sign in to Operations Copilot (dev)'), ('', 'Restart login cookie not found. It may have expired; it may have been deleted or cookies are disabled in your browser. If cookies are disabled then enable them. Click Back to Application to login again.', '')]
request cookie header names sent: []
```

Findings:

- **Library shape.** authlib 1.8.0's `integrations/httpx_client/_compat.py` does `import httpx2` and falls back to `httpx` with a deprecation warning, so the locked httpx2 is used. The client class is `OAuth2Client` / `AsyncOAuth2Client`. The requests-based `OAuth2Session` cannot be imported because `requests` is not installed. `authlib.jose` warns that it is deprecated in favour of joserfc. The OIDC claim classes (`authlib.oidc.core.CodeIDToken`) and `parse_id_token` sit on joserfc.
- **Starlette integration.** `authlib.integrations.starlette_client`'s `authorize_redirect` raises `AssertionError: SessionMiddleware must be installed to access request.session`. SessionMiddleware needs `itsdangerous`, which is not locked, and AM-20.7 item 10 forbids keeping state there anyway. Use `OAuth2Client` (or `AsyncOAuth2Client`) directly, keep `state`, `nonce` and `code_verifier` in the server-side store, and validate with `CodeIDToken`. `parse_id_token` itself works without a request, but it lives on the registry's app object and fetches discovery and JWKS through its own async client.
- **Redirect URI.** Matching is exact. `http://127.0.0.1:18000/callback` returns **400 `Invalid parameter: redirect_uri`** as an HTML page, not a redirect. Only `http://localhost:8000/auth/callback` is registered. Tests do not need a new URI: the driver reads the 302 `Location` and never follows it. If T11 wants the throwaway port anyway, the bootstrap would change `ops-web`'s `"redirectUris": ["http://localhost:8000/auth/callback"]` to add `"http://127.0.0.1:18000/callback"`. `localhost` and `127.0.0.1` are distinct entries.
- **PKCE** is enforced by the client attribute `pkce.code.challenge.method=S256`. Without a challenge the realm redirects to the callback with `error=invalid_request`, `error_description=Missing parameter: code_challenge_method`. authlib builds `code_challenge` (43 characters) only when `code_challenge_method="S256"` is set on the client **and** a `code_verifier` is passed.
- **Login form without a browser.** The form has `username`, `password` and `credentialId` and no hidden fields. Its action is `.../login-actions/authenticate?session_code=…&execution=…&client_id=…&tab_id=…`. **The realm sets `AUTH_SESSION_ID`, `KC_AUTH_SESSION_HASH` and `KC_RESTART` as `Secure; SameSite=None` on plain http**, so the httpx2 cookie jar stores them but never sends them to an `http://` URL, and the POST gets **400 "Restart login cookie not found"**. A browser treats `http://localhost` as a secure context and does send them. Fix for test drivers: forward the jar as an explicit `Cookie` header (`common.kc_login`). A login round trip takes ≈2.1 s, almost all of it the `localhost` IPv6 fallback (measurement 3).
- **Callback** query: `code` (98 characters), `iss` (equal to the issuer; discovery says `authorization_response_iss_parameter_supported: True`), `session_state` (equal to `sid`) and `state`. **authlib does not check the `iss` parameter**: `parse_authorization_code_response` checks only `state`. Check it by hand (RFC 9207 mix-up defence).
- **Wrong state** raises `authlib.oauth2.rfc6749.errors.MismatchingStateException` (`mismatching_state`) before any network call, so the code is not spent. **A wrong `code_verifier`** gives `invalid_grant` "PKCE verification failed: Code mismatch" **and burns the code**: the right verifier afterwards gets "Code not valid". **A reused code** gives `invalid_grant` "Code not valid", and the realm also kills the session the first exchange created (userinfo 401 `user_session_not_found`; refresh 400 "Session doesn't have required client"). The callback handler must therefore consume `state` atomically and exactly once.
- **Tokens:**
  - The token response has `access_token, expires_at, expires_in, id_token, not-before-policy, refresh_expires_in, refresh_token, scope, session_state, token_type`.
  - Access and id tokens: `exp − iat` = 300. Refresh token: 1800 (the SSO idle timeout). `scope` is `openid email profile`.
  - id_token: `aud = ops-web`, `azp = ops-web`, `typ = ID`, and `sid, nonce, sub, preferred_username, at_hash, auth_time, acr` are present.
  - **The access token has no `aud`**, because `ops-web` has no audience mapper. It carries `azp`, `sid` and `typ = Bearer`, and `sub` equals the id_token `sub`.
  - **There is no `session_state` claim.** Use `sid`.
- **What authlib checks** (`CodeIDToken.validate`):
  - The signature is checked against JWKS (`BadSignatureError`), and so are `exp` and `iat` with a leeway (`parse_id_token` uses 120 s), and `at_hash` when an access token is passed.
  - `iss` is checked only if `claims_options` names it. `parse_id_token` fills that in from discovery, but a hand call with `{}` accepted `iss: http://evil`.
  - **`nonce` is checked only if the expected nonce is truthy.** `nonce=None` (for example a lost store row) is accepted.
  - **`aud` is never compared with `client_id`.** Only `azp` is: `aud=['other'], azp='ops-web'` is accepted, and so is `aud=['ops-web','other']`. Pass `claims_options={"iss": {"values": [ISSUER]}, "aud": {"values": ["ops-web"]}}` and refuse a missing nonce yourself.

## 2. Back-channel logout and the end-session endpoint

Script `server.py` (the throwaway app on `127.0.0.1:18000`, also used by measurement 6):

```python
"""Throwaway FastAPI app on 127.0.0.1:18000 run by uvicorn in a background thread (measurements 2 and 6)."""
import threading
import time

import uvicorn
from fastapi import FastAPI, Request, Response

app = FastAPI()
RECEIVED: list[dict] = []          # what the backchannel endpoint was sent
BEHAVIOUR = {"status": 200}        # the status the endpoint answers with


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/backchannel-logout")
async def backchannel_logout(request: Request):
    form = await request.form()
    RECEIVED.append({"content_type": request.headers.get("content-type"), "fields": dict(form),
                     "user_agent": request.headers.get("user-agent"), "client_host": request.client.host,
                     "headers": sorted(request.headers.keys())})
    return Response(status_code=BEHAVIOUR["status"], headers={"Cache-Control": "no-store"})


@app.get("/auth/callback")
def callback(code: str = "", state: str = ""):
    return {"got_code": bool(code)}


@app.get("/boom")
def boom():
    raise RuntimeError("canary-secret-XYZ123 in an exception message")


def serve(log_config=None, access_log=False, port=18000) -> uvicorn.Server:
    cfg = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info", access_log=access_log,
                         log_config=log_config)
    srv = uvicorn.Server(cfg)
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    return srv
```

Script `spike_kc.py` (the throwaway container; run with `start` before and with `stop` by the cleanup):

```python
"""Start (or stop) a throwaway Keycloak 26.8.0 container `spike_kc` on 127.0.0.1:18081, the only place a
backchannel logout URL can be configured without an admin on the dev realm. Its admin password is generated per run,
written to the scratch dir (never printed) and passed through the environment, not the command line."""
import os
import secrets
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
PW_FILE = HERE / ".spike_kc_admin"   # scratch only, deleted by `stop`

if sys.argv[1] == "start":
    pw = secrets.token_urlsafe(24)
    PW_FILE.write_text(pw, encoding="utf-8")
    env = dict(os.environ, KC_BOOTSTRAP_ADMIN_USERNAME="spike_admin", KC_BOOTSTRAP_ADMIN_PASSWORD=pw)
    r = subprocess.run(["docker", "run", "-d", "--name", "spike_kc", "-p", "127.0.0.1:18081:8080",
                        "-e", "KC_BOOTSTRAP_ADMIN_USERNAME", "-e", "KC_BOOTSTRAP_ADMIN_PASSWORD",
                        "quay.io/keycloak/keycloak:26.8.0", "start-dev"], env=env, capture_output=True, text=True)
    print("docker run rc:", r.returncode, "| container id:", r.stdout.strip()[:12], r.stderr.strip()[:200])
elif sys.argv[1] == "stop":
    r = subprocess.run(["docker", "rm", "-f", "spike_kc"], capture_output=True, text=True)
    print("docker rm -f spike_kc rc:", r.returncode, r.stdout.strip(), r.stderr.strip()[:200])
    PW_FILE.unlink(missing_ok=True)
```

Script `m2_helpers.py`:

```python
"""Login and liveness helpers shared by M2 and M2b."""
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).parent))
from common import REDIRECT_REGISTERED, kc_login  # noqa: E402

import httpx2  # noqa: E402
from authlib.common.security import generate_token  # noqa: E402
from authlib.integrations.httpx_client import OAuth2Client  # noqa: E402

BCL_EVENT = "http://schemas.openid.net/event/backchannel-logout"


def login(meta, client_id, secret, user, pw, redirect=REDIRECT_REGISTERED):
    c = OAuth2Client(client_id=client_id, client_secret=secret, redirect_uri=redirect, scope="openid",
                     code_challenge_method="S256", timeout=5)
    cv, nonce = generate_token(48), generate_token(20)
    url, state = c.create_authorization_url(meta["authorization_endpoint"], code_verifier=cv, nonce=nonce)
    b = httpx2.Client(follow_redirects=False, timeout=5)
    _, r2 = kc_login(b, url, user, pw)
    loc = r2.headers["location"]
    tok = c.fetch_token(meta["token_endpoint"], authorization_response=loc, code_verifier=cv)
    return tok, b, parse_qs(urlsplit(loc).query)


def alive(meta, client_id, secret, tok):
    """Is the session still there? userinfo with the access token, then a refresh. (Introspecting an access token
    whose aud lacks the caller answers active=false even for a live session: see M2b.)"""
    u = httpx2.get(meta["userinfo_endpoint"], headers={"Authorization": f"Bearer {tok['access_token']}"}, timeout=5)
    r = httpx2.post(meta["token_endpoint"], auth=(client_id, secret),
                    data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]}, timeout=5)
    return f"userinfo -> {u.status_code} | refresh -> {r.status_code} {r.json().get('error', 'ok')}"
```

Script `m2_backchannel.py`:

```python
"""M2: logout. Part A on the live dev realm (discovery, sid, end_session_endpoint, backend logout); part B on the
throwaway `spike_kc` container (a real backchannel logout_token POSTed to a local endpoint); container -> host
reachability; the hand-written logout-token validator."""
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).parent))
from common import (DISCOVERY, REDIRECT_REGISTERED, cookie_header, kc_login, read_secret, short,  # noqa: E402
                    unverified_claims, unverified_header)
import server  # noqa: E402

import httpx2  # noqa: E402
from authlib.common.security import generate_token  # noqa: E402
from authlib.integrations.httpx_client import OAuth2Client  # noqa: E402
from joserfc import jwt  # noqa: E402
from joserfc.jwk import KeySet, RSAKey  # noqa: E402

BCL_EVENT = "http://schemas.openid.net/event/backchannel-logout"
from m2_helpers import alive, login  # noqa: E402


# ---------------------------------------------------------------- part A: live dev realm
print("== A. live dev realm ops-dev")
meta = httpx2.get(DISCOVERY).json()
for k in ("backchannel_logout_supported", "backchannel_logout_session_supported", "frontchannel_logout_supported",
          "frontchannel_logout_session_supported", "end_session_endpoint", "check_session_iframe",
          "revocation_endpoint", "introspection_endpoint"):
    print(f"  {k}: {meta.get(k)}")
SECRET = read_secret("kc_client_secret_ops_web")
PW = read_secret("kc_persona_alex_password")
END = meta["end_session_endpoint"]

tok1, b1, cb1 = login(meta, "ops-web", SECRET, "alex", PW)
tok2, b2, cb2 = login(meta, "ops-web", SECRET, "alex", PW)
id1, id2 = unverified_claims(tok1["id_token"]), unverified_claims(tok2["id_token"])
print("\n-- sid: two logins of alex (separate cookie jars)")
print("  sid1:", short(id1["sid"]), "| sid2:", short(id2["sid"]), "| distinct:", id1["sid"] != id2["sid"],
      "| callback session_state == sid:", cb1["session_state"][0] == id1["sid"],
      "| token-response session_state == sid:", tok1["session_state"] == id1["sid"],
      "| access/refresh sid == id sid:", unverified_claims(tok1["access_token"])["sid"] == id1["sid"] ==
      unverified_claims(tok1["refresh_token"])["sid"])

print("\n-- end_session GET, id_token_hint only, NO cookies")
r = httpx2.get(END, params={"id_token_hint": tok1["id_token"]}, follow_redirects=False, timeout=5)
import re  # noqa: E402
title = re.search(r"<title>([^<]+)<", r.text)
msg = re.findall(r'(?:kc-feedback-text|instruction)[^>]*>([^<]+)<', r.text)
print("  status:", r.status_code, "| location:", r.headers.get("location"), "| title:", title and title.group(1),
      "| message:", msg[:2])
forms = re.findall(r'<form[^>]*action="([^"]+)"', r.text)
print("  form actions on the page:", [f.split("?")[0] for f in forms],
      "| hidden inputs:", re.findall(r'<input[^>]*type="hidden"[^>]*name="([^"]+)"', r.text))
print("  session 1 after:", alive(meta, "ops-web", SECRET, tok1))
print("  session 2 after (untouched?):", alive(meta, "ops-web", SECRET, tok2))

print("\n-- end_session GET, id_token_hint + registered post_logout_redirect_uri + state, NO cookies")
tok3, b3, _ = login(meta, "ops-web", SECRET, "alex", PW)
r = httpx2.get(END, params={"id_token_hint": tok3["id_token"], "post_logout_redirect_uri": "http://localhost:8000/",
                            "state": "s123"}, follow_redirects=False, timeout=5)
print("  status:", r.status_code, "| location:", r.headers.get("location"))
print("  session 3 after:", alive(meta, "ops-web", SECRET, tok3))

print("\n-- end_session GET, unregistered post_logout_redirect_uri")
tok4, b4, _ = login(meta, "ops-web", SECRET, "alex", PW)
r = httpx2.get(END, params={"id_token_hint": tok4["id_token"], "post_logout_redirect_uri": "http://127.0.0.1:18000/"},
               follow_redirects=False, timeout=5)
print("  status:", r.status_code, "| message:", re.findall(r'(?:kc-feedback-text|instruction)[^>]*>([^<]+)<', r.text)[:1])
print("  session 4 after:", alive(meta, "ops-web", SECRET, tok4))

print("\n-- end_session GET with the browser cookies + id_token_hint + registered redirect")
r = b4.get(END, params={"id_token_hint": tok4["id_token"], "post_logout_redirect_uri": "http://localhost:8000/"},
           headers={"Cookie": cookie_header(b4)})
print("  status:", r.status_code, "| location:", r.headers.get("location"))
print("  session 4 after:", alive(meta, "ops-web", SECRET, tok4))

print("\n-- backend (RP) logout: POST end_session with client credentials + refresh_token")
r = httpx2.post(END, auth=("ops-web", SECRET), data={"refresh_token": tok2["refresh_token"]}, timeout=5)
print("  status:", r.status_code, "| body length:", len(r.content))
print("  session 2 after:", alive(meta, "ops-web", SECRET, tok2))
r = httpx2.post(END, auth=("ops-web", SECRET), data={"refresh_token": tok2["refresh_token"]}, timeout=5)
print("  same again:", r.status_code, r.json() if r.content else "")

print("\n-- can the view-users account configure a backchannel URL? (read-only probe)")
vu = httpx2.post(meta["token_endpoint"], data={"grant_type": "client_credentials"},
                 auth=("ops-view-users", read_secret("kc_client_secret_ops_view_users")), timeout=5).json()
print("  realm-management roles in its token:",
      sorted(unverified_claims(vu["access_token"]).get("resource_access", {}).get("realm-management", {}).get("roles", [])))
r = httpx2.get("http://localhost:18080/admin/realms/ops-dev/clients", params={"clientId": "ops-web"},
               headers={"Authorization": f"Bearer {vu['access_token']}"}, timeout=5)
print("  GET /admin/realms/ops-dev/clients?clientId=ops-web:", r.status_code)

# ---------------------------------------------------------------- reachability: container -> host
print("\n== container -> host reachability (uvicorn bound to 127.0.0.1:18000 on the host)")
srv = server.serve()
print("  host GET /health:", httpx2.get("http://127.0.0.1:18000/health").status_code)
sh = ('exec 3<>/dev/tcp/host.docker.internal/18000 && printf "GET /health HTTP/1.0\\r\\nHost: x\\r\\n\\r\\n" >&3 '
      '&& head -1 <&3 || echo FAILED')
for name in ("ops-copilot-keycloak-1", "spike_kc"):
    p = subprocess.run(["docker", "exec", name, "bash", "-c", sh], capture_output=True, text=True, timeout=20)
    print(f"  {name}: bash /dev/tcp host.docker.internal:18000 ->", (p.stdout.strip() or p.stderr.strip())[:120])
p = subprocess.run(["docker", "exec", "ops-copilot-keycloak-1", "bash", "-c", "getent hosts host.docker.internal || echo none"],
                   capture_output=True, text=True)
print("  getent hosts host.docker.internal (ops-copilot-keycloak-1):", "resolves" if p.stdout.strip() != "none" else "none")
for tool in ("curl", "wget", "nc", "python3"):
    p = subprocess.run(["docker", "exec", "ops-copilot-keycloak-1", "bash", "-c", f"command -v {tool} || echo absent"],
                       capture_output=True, text=True)
    print(f"  {tool} in the image:", p.stdout.strip())

# ---------------------------------------------------------------- part B: throwaway container
print("\n== B. throwaway spike_kc (127.0.0.1:18081): a real backchannel logout")
SK = "http://localhost:18081"
for i in range(120):
    try:
        if httpx2.get(f"{SK}/realms/master", timeout=2).status_code == 200:
            break
    except httpx2.HTTPError:
        pass
    time.sleep(1)
adm_pw = (Path(__file__).parent / ".spike_kc_admin").read_text(encoding="utf-8")
adm = httpx2.post(f"{SK}/realms/master/protocol/openid-connect/token",
                  data={"grant_type": "password", "client_id": "admin-cli", "username": "spike_admin", "password": adm_pw}).json()["access_token"]
A = httpx2.Client(base_url=f"{SK}/admin/realms", headers={"Authorization": f"Bearer {adm}"}, timeout=10)
spike_client_secret = generate_token(32)
spike_user_pw = generate_token(24)
print("  delete leftover spike_realm (re-run):", A.delete("/spike_realm").status_code)
print("  create realm spike_realm:", A.post("", json={"realm": "spike_realm", "enabled": True, "sslRequired": "none"}).status_code)
print("  create client spike_web:", A.post("/spike_realm/clients", json={
    "clientId": "spike_web", "publicClient": False, "secret": spike_client_secret, "standardFlowEnabled": True,
    "directAccessGrantsEnabled": False, "redirectUris": [REDIRECT_REGISTERED],
    "attributes": {"pkce.code.challenge.method": "S256", "post.logout.redirect.uris": "http://localhost:8000/",
                   "backchannel.logout.url": "http://host.docker.internal:18000/backchannel-logout",
                   "backchannel.logout.session.required": "true",
                   "backchannel.logout.revoke.offline.tokens": "false"}}).status_code)
rep = A.get("/spike_realm/clients", params={"clientId": "spike_web"}).json()[0]
print("  stored: frontchannelLogout =", rep.get("frontchannelLogout"), "| backchannel attrs:",
      {k: v for k, v in rep["attributes"].items() if k.startswith("backchannel")})
print("  create user spike_user:", A.post("/spike_realm/users", json={
    "username": "spike_user", "enabled": True, "email": "spike_user@example.invalid", "emailVerified": True,
    "firstName": "Spike", "lastName": "User",
    "credentials": [{"type": "password", "value": spike_user_pw, "temporary": False}]}).status_code)
smeta = httpx2.get(f"{SK}/realms/spike_realm/.well-known/openid-configuration").json()
jwks = KeySet.import_key_set(httpx2.get(smeta["jwks_uri"]).json())
uid = A.get("/spike_realm/users", params={"username": "spike_user", "exact": "true"}).json()[0]["id"]


def wait_received(n, timeout=10):
    t0 = time.time()
    while len(server.RECEIVED) < n and time.time() - t0 < timeout:
        time.sleep(0.1)
    return time.time() - t0


def show_last(label, sid):
    if not server.RECEIVED:
        print(f"  [{label}] nothing received"); return None
    rec = server.RECEIVED[-1]
    lt = rec["fields"].get("logout_token", "")
    hdr, cl = unverified_header(lt), unverified_claims(lt)
    print(f"  [{label}] content-type: {rec['content_type']} | form fields: {sorted(rec['fields'])} | user-agent: {rec['user_agent']}"
          f" | from: {rec['client_host']}")
    print(f"  [{label}] header: { {k: (short(v) if k == 'kid' else v) for k, v in hdr.items()} }")
    print(f"  [{label}] claims: {sorted(cl)}")
    print(f"  [{label}] events: {cl.get('events')} | aud: {cl.get('aud')} | iss: {cl.get('iss')} | typ: {cl.get('typ')}"
          f" | sid matches session: {cl.get('sid') == sid} | sub == user id: {cl.get('sub') == uid}"
          f" | exp-iat: {cl['exp'] - cl['iat'] if 'exp' in cl else None} | iat-now: {cl['iat'] - int(time.time())}"
          f" | jti: {short(cl.get('jti'))} | nonce present: {'nonce' in cl}")
    return lt


results = {}
for label, how in (("backend logout (refresh_token)", "rp"), ("end_session GET + id_token_hint", "get"),
                   ("admin POST /users/{id}/logout", "admin"), ("endpoint answers 500", "rp500")):
    server.BEHAVIOUR["status"] = 500 if how == "rp500" else 200
    tok, b, _ = login(smeta, "spike_web", spike_client_secret, "spike_user", spike_user_pw)
    sid = unverified_claims(tok["id_token"])["sid"]
    n = len(server.RECEIVED)
    if how in ("rp", "rp500"):
        r = httpx2.post(smeta["end_session_endpoint"], auth=("spike_web", spike_client_secret),
                        data={"refresh_token": tok["refresh_token"]}, timeout=10)
    elif how == "get":
        r = httpx2.get(smeta["end_session_endpoint"], params={"id_token_hint": tok["id_token"],
                       "post_logout_redirect_uri": "http://localhost:8000/"}, follow_redirects=False, timeout=10)
    else:
        r = A.post(f"/spike_realm/users/{uid}/logout")
    waited = wait_received(n + 1)
    print(f"\n  [{label}] logout call -> {r.status_code}; POSTs received: {len(server.RECEIVED) - n} after {waited:.2f}s")
    results[label] = show_last(label, sid)
    print(f"  [{label}] session after:", alive(smeta, "spike_web", spike_client_secret, tok))
server.BEHAVIOUR["status"] = 200

print("\n== the hand-written validator (AM-20.7 5(a)) against the real token and synthetic negatives")
SEEN: set[str] = set()


def validate_logout_token(token, keys, issuer, client_id, now=None, max_age=120):
    now = now or int(time.time())
    hdr = unverified_header(token)
    if hdr.get("alg") not in ("RS256",):
        raise ValueError("alg")
    d = jwt.decode(token, keys, algorithms=["RS256"])           # signature
    c = d.claims
    if c.get("iss") != issuer:
        raise ValueError("iss")
    aud = c.get("aud"); aud = aud if isinstance(aud, list) else [aud]
    if client_id not in aud:
        raise ValueError("aud")
    if not isinstance(c.get("iat"), int) or not (now - max_age <= c["iat"] <= now + 30):
        raise ValueError("iat")
    if "exp" in c and c["exp"] < now:
        raise ValueError("exp")
    if not isinstance(c.get("events"), dict) or BCL_EVENT not in c["events"]:
        raise ValueError("events")
    if "nonce" in c:
        raise ValueError("nonce present")
    if not (c.get("sid") or c.get("sub")):
        raise ValueError("sid/sub")
    if not c.get("jti"):
        raise ValueError("jti")
    if c["jti"] in SEEN:
        raise ValueError("jti replay")
    SEEN.add(c["jti"])
    return c


real = results["backend logout (refresh_token)"]
iss = smeta["issuer"]
for label, fn in (("real token", lambda: validate_logout_token(real, jwks, iss, "spike_web")),
                  ("same token again (replay)", lambda: validate_logout_token(real, jwks, iss, "spike_web")),
                  ("real token, wrong client_id", lambda: validate_logout_token(results["admin POST /users/{id}/logout"], jwks, iss, "ops-web")),
                  ("real token, other issuer", lambda: validate_logout_token(results["admin POST /users/{id}/logout"], jwks, "http://localhost:18080/realms/ops-dev", "spike_web"))):
    try:
        c = fn(); print(f"  {label}: accepted (sid {short(c.get('sid'))})")
    except Exception as e:
        print(f"  {label}: rejected: {type(e).__name__}: {e}")
own = RSAKey.generate_key(2048, parameters={"kid": "own"})
own_set = KeySet([own])
now = int(time.time())
good = {"iss": iss, "aud": "spike_web", "iat": now, "exp": now + 120, "jti": generate_token(16), "sid": "s",
        "sub": "u", "events": {BCL_EVENT: {}}}
for label, claims in (("synthetic good", good), ("with nonce", dict(good, jti=generate_token(16), nonce="x")),
                      ("no events", {k: v for k, v in dict(good, jti=generate_token(16)).items() if k != "events"}),
                      ("events wrong key", dict(good, jti=generate_token(16), events={"x": {}})),
                      ("iat 10 min old", dict(good, jti=generate_token(16), iat=now - 600)),
                      ("no sid, no sub", {k: v for k, v in dict(good, jti=generate_token(16)).items() if k not in ("sid", "sub")}),
                      ("no jti", {k: v for k, v in good.items() if k != "jti"})):
    t = jwt.encode({"alg": "RS256", "kid": "own", "typ": "logout+jwt"}, claims, own)
    try:
        validate_logout_token(t, own_set, iss, "spike_web"); print(f"  {label}: accepted")
    except Exception as e:
        print(f"  {label}: rejected: {type(e).__name__}: {e}")
t = jwt.encode({"alg": "RS256", "kid": "own"}, dict(good, jti=generate_token(16)), own)
try:
    validate_logout_token(t, jwks, iss, "spike_web")
except Exception as e:
    print(f"  signed by a key not in the realm JWKS: rejected: {type(e).__name__}: {e}")
t = jwt.encode({"alg": "HS256"}, dict(good, jti=generate_token(16)), __import__("joserfc.jwk", fromlist=["OctKey"]).OctKey.generate_key(256))
try:
    validate_logout_token(t, jwks, iss, "spike_web")
except Exception as e:
    print(f"  alg HS256: rejected: {type(e).__name__}: {e}")
srv.should_exit = True
time.sleep(0.5)
```

Output (complete):

```text
== A. live dev realm ops-dev
  backchannel_logout_supported: True
  backchannel_logout_session_supported: True
  frontchannel_logout_supported: True
  frontchannel_logout_session_supported: True
  end_session_endpoint: http://localhost:18080/realms/ops-dev/protocol/openid-connect/logout
  check_session_iframe: http://localhost:18080/realms/ops-dev/protocol/openid-connect/login-status-iframe.html
  revocation_endpoint: http://localhost:18080/realms/ops-dev/protocol/openid-connect/revoke
  introspection_endpoint: http://localhost:18080/realms/ops-dev/protocol/openid-connect/token/introspect

-- sid: two logins of alex (separate cookie jars)
  sid1: wNo5Tx...(len=24) | sid2: 8R_XxM...(len=24) | distinct: True | callback session_state == sid: True | token-response session_state == sid: True | access/refresh sid == id sid: True

-- end_session GET, id_token_hint only, NO cookies
  status: 200 | location: None | title: Sign in to Operations Copilot (dev) | message: ['You are logged out']
  form actions on the page: [] | hidden inputs: []
  session 1 after: userinfo -> 401 | refresh -> 400 invalid_grant
  session 2 after (untouched?): userinfo -> 200 | refresh -> 200 ok

-- end_session GET, id_token_hint + registered post_logout_redirect_uri + state, NO cookies
  status: 302 | location: http://localhost:8000/?state=s123
  session 3 after: userinfo -> 401 | refresh -> 400 invalid_grant

-- end_session GET, unregistered post_logout_redirect_uri
  status: 400 | message: ['Invalid redirect uri']
  session 4 after: userinfo -> 200 | refresh -> 200 ok

-- end_session GET with the browser cookies + id_token_hint + registered redirect
  status: 302 | location: http://localhost:8000/
  session 4 after: userinfo -> 401 | refresh -> 400 invalid_grant

-- backend (RP) logout: POST end_session with client credentials + refresh_token
  status: 204 | body length: 0
  session 2 after: userinfo -> 401 | refresh -> 400 invalid_grant
  same again: 204 

-- can the view-users account configure a backchannel URL? (read-only probe)
  realm-management roles in its token: ['query-groups', 'query-users', 'view-users']
  GET /admin/realms/ops-dev/clients?clientId=ops-web: 403

== container -> host reachability (uvicorn bound to 127.0.0.1:18000 on the host)
  host GET /health: 200
  ops-copilot-keycloak-1: bash /dev/tcp host.docker.internal:18000 -> HTTP/1.1 200 OK
  spike_kc: bash /dev/tcp host.docker.internal:18000 -> HTTP/1.1 200 OK
  getent hosts host.docker.internal (ops-copilot-keycloak-1): resolves
  curl in the image: absent
  wget in the image: absent
  nc in the image: absent
  python3 in the image: absent

== B. throwaway spike_kc (127.0.0.1:18081): a real backchannel logout
  delete leftover spike_realm (re-run): 204
  create realm spike_realm: 201
  create client spike_web: 201
  stored: frontchannelLogout = False | backchannel attrs: {'backchannel.logout.url': 'http://host.docker.internal:18000/backchannel-logout', 'backchannel.logout.session.required': 'true', 'backchannel.logout.revoke.offline.tokens': 'false'}
  create user spike_user: 201

  [backend logout (refresh_token)] logout call -> 204; POSTs received: 1 after 0.00s
  [backend logout (refresh_token)] content-type: application/x-www-form-urlencoded | form fields: ['logout_token'] | user-agent: Apache-HttpClient/4.5.14 (Java/21.0.12.1) | from: 127.0.0.1
  [backend logout (refresh_token)] header: {'alg': 'RS256', 'typ': 'logout+jwt', 'kid': 'iqiDX2...(len=43)'}
  [backend logout (refresh_token)] claims: ['aud', 'events', 'exp', 'iat', 'iss', 'jti', 'sid', 'sub', 'typ']
  [backend logout (refresh_token)] events: {'http://schemas.openid.net/event/backchannel-logout': {}} | aud: spike_web | iss: http://localhost:18081/realms/spike_realm | typ: Logout | sid matches session: True | sub == user id: True | exp-iat: 120 | iat-now: 0 | jti: 19d9bd...(len=36) | nonce present: False
  [backend logout (refresh_token)] session after: userinfo -> 401 | refresh -> 400 invalid_grant

  [end_session GET + id_token_hint] logout call -> 302; POSTs received: 1 after 0.00s
  [end_session GET + id_token_hint] content-type: application/x-www-form-urlencoded | form fields: ['logout_token'] | user-agent: Apache-HttpClient/4.5.14 (Java/21.0.12.1) | from: 127.0.0.1
  [end_session GET + id_token_hint] header: {'alg': 'RS256', 'typ': 'logout+jwt', 'kid': 'iqiDX2...(len=43)'}
  [end_session GET + id_token_hint] claims: ['aud', 'events', 'exp', 'iat', 'iss', 'jti', 'sid', 'sub', 'typ']
  [end_session GET + id_token_hint] events: {'http://schemas.openid.net/event/backchannel-logout': {}} | aud: spike_web | iss: http://localhost:18081/realms/spike_realm | typ: Logout | sid matches session: True | sub == user id: True | exp-iat: 120 | iat-now: 0 | jti: 33c42d...(len=36) | nonce present: False
  [end_session GET + id_token_hint] session after: userinfo -> 401 | refresh -> 400 invalid_grant

  [admin POST /users/{id}/logout] logout call -> 204; POSTs received: 1 after 0.00s
  [admin POST /users/{id}/logout] content-type: application/x-www-form-urlencoded | form fields: ['logout_token'] | user-agent: Apache-HttpClient/4.5.14 (Java/21.0.12.1) | from: 127.0.0.1
  [admin POST /users/{id}/logout] header: {'alg': 'RS256', 'typ': 'logout+jwt', 'kid': 'iqiDX2...(len=43)'}
  [admin POST /users/{id}/logout] claims: ['aud', 'events', 'exp', 'iat', 'iss', 'jti', 'sid', 'sub', 'typ']
  [admin POST /users/{id}/logout] events: {'http://schemas.openid.net/event/backchannel-logout': {}} | aud: spike_web | iss: http://localhost:18081/realms/spike_realm | typ: Logout | sid matches session: True | sub == user id: True | exp-iat: 120 | iat-now: 0 | jti: 0da456...(len=36) | nonce present: False
  [admin POST /users/{id}/logout] session after: userinfo -> 401 | refresh -> 400 invalid_grant

  [endpoint answers 500] logout call -> 204; POSTs received: 1 after 0.00s
  [endpoint answers 500] content-type: application/x-www-form-urlencoded | form fields: ['logout_token'] | user-agent: Apache-HttpClient/4.5.14 (Java/21.0.12.1) | from: 127.0.0.1
  [endpoint answers 500] header: {'alg': 'RS256', 'typ': 'logout+jwt', 'kid': 'iqiDX2...(len=43)'}
  [endpoint answers 500] claims: ['aud', 'events', 'exp', 'iat', 'iss', 'jti', 'sid', 'sub', 'typ']
  [endpoint answers 500] events: {'http://schemas.openid.net/event/backchannel-logout': {}} | aud: spike_web | iss: http://localhost:18081/realms/spike_realm | typ: Logout | sid matches session: True | sub == user id: True | exp-iat: 120 | iat-now: 0 | jti: 9733ed...(len=36) | nonce present: False
  [endpoint answers 500] session after: userinfo -> 401 | refresh -> 400 invalid_grant

== the hand-written validator (AM-20.7 5(a)) against the real token and synthetic negatives
  real token: accepted (sid w_2TYY...(len=24))
  same token again (replay): rejected: ValueError: jti replay
  real token, wrong client_id: rejected: ValueError: aud
  real token, other issuer: rejected: ValueError: iss
  synthetic good: accepted
  with nonce: rejected: ValueError: nonce present
  no events: rejected: ValueError: events
  events wrong key: rejected: ValueError: events
  iat 10 min old: rejected: ValueError: iat
  no sid, no sub: rejected: ValueError: sid/sub
  no jti: rejected: ValueError: jti
  signed by a key not in the realm JWKS: rejected: InvalidKeyIdError: invalid_key_id: No key for kid: 'own'
  alg HS256: rejected: ValueError: alg
```

Script `m2b_introspect.py` (a control that explains why the liveness check uses userinfo and refresh rather than introspection):

```python
"""M2b: control for the introspection check used in M2 (a fresh, live session)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import DISCOVERY, read_secret, unverified_claims
from m2_helpers import login
import httpx2
meta = httpx2.get(DISCOVERY).json()
SECRET = read_secret("kc_client_secret_ops_web")
tok, b, _ = login(meta, "ops-web", SECRET, "alex", read_secret("kc_persona_alex_password"))
for hint in (None, "access_token"):
    data = {"token": tok["access_token"]}
    if hint: data["token_type_hint"] = hint
    r = httpx2.post(meta["introspection_endpoint"], auth=("ops-web", SECRET), data=data, timeout=5)
    j = r.json()
    print(f"fresh access token, hint={hint}: {r.status_code} active={j.get('active')} keys={sorted(j)}")
r = httpx2.post(meta["introspection_endpoint"], auth=("ops-web", SECRET), data={"token": tok["refresh_token"]}, timeout=5).json()
print("fresh refresh token: active =", r.get("active"))
r = httpx2.get(meta["userinfo_endpoint"], headers={"Authorization": f"Bearer {tok['access_token']}"}, timeout=5)
print("userinfo with the fresh access token:", r.status_code, sorted(r.json()) if r.status_code == 200 else r.text[:80])
print("access token aud claim present:", "aud" in unverified_claims(tok["access_token"]))
r = httpx2.post(meta["end_session_endpoint"], auth=("ops-web", SECRET), data={"refresh_token": tok["refresh_token"]}, timeout=5)
print("backend logout:", r.status_code)
r = httpx2.get(meta["userinfo_endpoint"], headers={"Authorization": f"Bearer {tok['access_token']}"}, timeout=5)
print("userinfo after logout:", r.status_code, r.headers.get("www-authenticate", "")[:90])
r = httpx2.post(meta["introspection_endpoint"], auth=("ops-web", SECRET), data={"token": tok["refresh_token"]}, timeout=5).json()
print("refresh token introspect after logout: active =", r.get("active"))
```

Output (complete):

```text
fresh access token, hint=None: 200 active=False keys=['active']
fresh access token, hint=access_token: 200 active=False keys=['active']
fresh refresh token: active = True
userinfo with the fresh access token: 200 ['email', 'email_verified', 'family_name', 'given_name', 'name', 'preferred_username', 'sub']
access token aud claim present: False
backend logout: 204
userinfo after logout: 401 Bearer realm="ops-dev", error="invalid_token", error_description="user_session_not_found"
refresh token introspect after logout: active = False
```

Findings:

- **Discovery.** `backchannel_logout_supported` and `backchannel_logout_session_supported` are `True` (the front-channel flags too). The `end_session_endpoint` is `.../protocol/openid-connect/logout`.
- **What the identity provider POSTs** (measured on `spike_kc`, same image):
  - **Request:** `Content-Type: application/x-www-form-urlencoded`, one form field `logout_token`, user agent `Apache-HttpClient/4.5.14 (Java/21.0.12.1)`.
  - **JWS header:** `{"alg": "RS256", "typ": "logout+jwt", "kid": …}`.
  - **Claims:** exactly `aud, events, exp, iat, iss, jti, sid, sub, typ`.
    - `aud` is the client id as a string, not a list.
    - `events` is `{"http://schemas.openid.net/event/backchannel-logout": {}}`.
    - `jti` is a 36-character UUID.
    - `typ` is `"Logout"`. This is a claim; the header `typ` is `logout+jwt`.
    - `exp − iat` = 120 s.
    - `sid` equals the session's `sid`, and `sub` equals the user id.
    - **No `nonce`.**
  - **When it is sent:** synchronously, before the logout call returns (it had arrived by the time the call came back). It is sent for the back-end `POST .../logout`, for the browser `GET .../logout?id_token_hint=…`, and for an admin `POST /users/{id}/logout`, **including to the client that initiated the logout**.
  - **No retry:** when our endpoint answered 500, the logout still returned 204, the session was gone, and exactly one POST had arrived. A lost or failed back-channel request is lost. The bound in AM-20.7 5 (session-only reads end on back-channel logout *or idle expiry*) is what covers it.
  - The `iss` claim followed the host name of the request that triggered the logout (`spike_kc` has no fixed hostname). On ops-dev, `KC_HOSTNAME` pins `iss` to `http://localhost:18080/realms/ops-dev` whichever address is called (measurement 3b).
- **ops-dev cannot be configured at runtime.** The view-users account holds only `query-groups, query-users, view-users`, `GET /admin/realms/ops-dev/clients` is 403, and there is no admin user. T11 needs a bootstrap change to `ops-web` in `deploy/dev/keycloak/realm-ops-dev.json`. The attribute names are exactly the ones `spike_kc` stored and acted on. The port and path are the API's. A client created through the admin API without `frontchannelLogout` stored `false`; the JSON should say so explicitly:

  ```json
  "frontchannelLogout": false,
  "attributes": {
    "pkce.code.challenge.method": "S256",
    "post.logout.redirect.uris": "http://localhost:8000/",
    "backchannel.logout.url": "http://host.docker.internal:8000/auth/backchannel-logout",
    "backchannel.logout.session.required": "true",
    "backchannel.logout.revoke.offline.tokens": "false"
  }
  ```
- **Reachability.** From both identity-provider containers, `bash -c 'exec 3<>/dev/tcp/host.docker.internal/18000 …'` returned `HTTP/1.1 200 OK` from a uvicorn bound to **`127.0.0.1`** on the host, so the API does not need to bind a wider address for the back-channel. `getent hosts host.docker.internal` resolves. The image has no `curl`, `wget`, `nc` or `python3`.
- **Matching a logout to sessions.** `sid` is in the id, access and refresh tokens and equals both the callback's `session_state` and the token response's `session_state`. Two logins of the same persona get distinct sids, and logging out one (by `id_token_hint`) left the other alive (userinfo 200, refresh 200). Matching by `sid` therefore needs the sid stored with the session (measurement 4). Matching by `sub` logs out every session of the user.
- **`end_session_endpoint` on ops-dev:**
  - **`GET` with only `id_token_hint`, without the browser cookies, ends the session with no confirmation** (200 page "You are logged out"). Anyone who holds an id_token can log its user out, so the API should keep id_tokens server-side, never in the browser.
  - With a registered `post_logout_redirect_uri` and `state` it gives 302 to `http://localhost:8000/?state=s123`.
  - An unregistered redirect gives 400 "Invalid redirect uri", and the session survives.
  - **The back-end logout** (`POST` with client authentication and `refresh_token`) gives 204 with an empty body, the session ends, and a repeat also gives 204 (idempotent). This is the call the API's own `/logout` should make. It also fires the back-channel request at the API itself, so the API must tolerate (or deduplicate) its own logout arriving back.
- **Introspection is not a liveness check here.** Introspecting a live access token as `ops-web` gives `active: false`, because the token has no `aud`; the refresh token introspects as `active: true`. M2 therefore uses userinfo (401 `user_session_not_found` after a logout) and a refresh grant.
- **The hand-written validator** (sketch in `m2_backchannel.py`):
  - **Accepts:** the real token (signature against the realm JWKS, `iss`, `aud ∋ client_id`, `iat` within 120 s, `exp`, the `events` key, no `nonce`, `sid` or `sub`, `jti`).
  - **Rejects:** a replay of the same jti, a wrong client id, another issuer, a `nonce`, a missing or wrong `events` key, an `iat` 10 minutes old, missing `sid` and `sub`, a missing `jti`, a key not in the JWKS (`InvalidKeyIdError`), and `alg: HS256`.
  - **Unchecked:** the header `typ: logout+jwt`. It could be required as well.

## 3. Admin-API enabled check

Script `m3_admin_api.py`:

```python
"""M3: the admin-API enabled check with the ops-view-users service account (least privilege, latency, token
lifetime, unknown user, unreachable/slow Keycloak within a 2 s timeout)."""
import socket
import sys
import threading
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import KC, OIDC, REALM, median_ms, read_secret, unverified_claims  # noqa: E402

import httpx2  # noqa: E402

SECRET = read_secret("kc_client_secret_ops_view_users")
ADMIN = f"{KC}/admin/realms/{REALM}"

print("-- service-account token (client_credentials)")
t0 = time.perf_counter()
r = httpx2.post(f"{OIDC}/token", data={"grant_type": "client_credentials"}, auth=("ops-view-users", SECRET), timeout=2)
dt = time.perf_counter() - t0
tok = r.json()
c = unverified_claims(tok["access_token"])
print("status:", r.status_code, "| keys:", sorted(tok), "| expires_in:", tok["expires_in"],
      "| refresh_expires_in:", tok.get("refresh_expires_in"), "| refresh_token present:", "refresh_token" in tok,
      f"| fetch {dt * 1000:.0f} ms")
print("claims:", sorted(c), "| azp:", c["azp"], "| aud:", c.get("aud"),
      "| realm-management roles:", sorted(c.get("resource_access", {}).get("realm-management", {}).get("roles", [])))
r2 = httpx2.post(f"{OIDC}/token", data={"grant_type": "client_credentials"}, auth=("ops-view-users", SECRET), timeout=2).json()
print("second fetch returns a different token:", r2["access_token"] != tok["access_token"], "| expires_in:", r2["expires_in"])

H = {"Authorization": f"Bearer {tok['access_token']}"}
with httpx2.Client(headers=H, timeout=2) as cl:
    print("\n-- GET /users?username=alex&exact=true")
    r = cl.get(f"{ADMIN}/users", params={"username": "alex", "exact": "true"})
    alex = r.json()[0]
    print("status:", r.status_code, "| fields:", sorted(alex))
    print("\n-- GET /users/{id} (alex)")
    r = cl.get(f"{ADMIN}/users/{alex['id']}")
    u = r.json()
    print("status:", r.status_code, "| fields:", sorted(u), "| enabled:", u["enabled"], "| username == alex:",
          u["username"] == "alex", "| id == path id:", u["id"] == alex["id"])
    print("\n-- GET /users/{id}?userProfileMetadata=false and briefRepresentation list")
    r = cl.get(f"{ADMIN}/users", params={"briefRepresentation": "true", "max": 100})
    print("list status:", r.status_code, "| count:", len(r.json()), "| fields per user:", sorted(r.json()[0]))
    r = cl.get(f"{ADMIN}/users/count")
    print("count:", r.status_code, r.text)

    print("\n-- sub of a token == admin-API user id (direct grant via ops-dev-direct)")
    dg = httpx2.post(f"{OIDC}/token", data={"grant_type": "password", "client_id": "ops-dev-direct", "username": "alex",
                     "password": read_secret("kc_persona_alex_password"), "scope": "openid"}, timeout=5).json()
    print("token sub == admin id:", unverified_claims(dg["access_token"])["sub"] == alex["id"])
    httpx2.post(f"{OIDC}/logout", data={"client_id": "ops-dev-direct", "refresh_token": dg["refresh_token"]}, timeout=5)

    print("\n-- GET /users/{random uuid}")
    r = cl.get(f"{ADMIN}/users/{uuid.uuid4()}")
    print("status:", r.status_code, "| body:", r.json())
    r = cl.get(f"{ADMIN}/users/not-a-uuid")
    print("non-uuid id:", r.status_code, "| body:", r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:60])

    print("\n-- PUT /users/{alex} {'enabled': true} (a no-op value; must be refused)")
    r = cl.put(f"{ADMIN}/users/{alex['id']}", json={"enabled": True})
    print("status:", r.status_code, "| body:", r.json() if r.content else "")
    print("alex still enabled:", cl.get(f"{ADMIN}/users/{alex['id']}").json()["enabled"])
    r = cl.post(f"{ADMIN}/users/{alex['id']}/logout")
    print("POST /users/{alex}/logout:", r.status_code)
    r = cl.get(f"{ADMIN}/users/{alex['id']}/sessions")
    print("GET /users/{alex}/sessions:", r.status_code, "| count:", len(r.json()) if r.status_code == 200 else None,
          "| fields:", sorted(r.json()[0]) if r.status_code == 200 and r.json() else None)

    print("\n-- latency of GET /users/{id}, warm keep-alive client, 10 calls")
    s = []
    for _ in range(10):
        t0 = time.perf_counter(); cl.get(f"{ADMIN}/users/{alex['id']}").raise_for_status(); s.append(time.perf_counter() - t0)
    print("median ms:", median_ms(s), "| min:", round(min(s) * 1000, 1), "| max:", round(max(s) * 1000, 1))
    s = []
    for _ in range(10):
        t0 = time.perf_counter(); httpx2.get(f"{ADMIN}/users/{alex['id']}", headers=H, timeout=2).raise_for_status(); s.append(time.perf_counter() - t0)
    print("new connection per call, median ms:", median_ms(s))
    s = []
    for _ in range(10):
        t0 = time.perf_counter(); cl.get(f"{ADMIN}/users", params={"briefRepresentation": "true", "max": 100}).raise_for_status(); s.append(time.perf_counter() - t0)
    print("list all users (brief), median ms:", median_ms(s))

print("\n-- bad / expired bearer")
r = httpx2.get(f"{ADMIN}/users/{alex['id']}", headers={"Authorization": "Bearer abc.def.ghi"}, timeout=2)
print("garbage token:", r.status_code, r.headers.get("www-authenticate"))
r = httpx2.get(f"{ADMIN}/users/{alex['id']}", timeout=2)
print("no token:", r.status_code)

print("\n-- Keycloak unreachable (closed port) and slow (accepts, never answers); timeout=2")
s = socket.socket(); s.bind(("127.0.0.1", 0)); closed = s.getsockname()[1]; s.close()
for label, url in (("closed port", f"http://127.0.0.1:{closed}/x"), ("localhost closed port", f"http://localhost:{closed}/x")):
    t0 = time.perf_counter()
    try:
        httpx2.get(url, timeout=2)
    except Exception as e:
        print(f"{label}: {type(e).__module__}.{type(e).__name__} after {time.perf_counter() - t0:.2f}s; "
              f"isinstance TransportError={isinstance(e, httpx2.TransportError)} TimeoutException={isinstance(e, httpx2.TimeoutException)}")
lsock = socket.socket(); lsock.bind(("127.0.0.1", 0)); lsock.listen(5); slow = lsock.getsockname()[1]
held = []
threading.Thread(target=lambda: held.append(lsock.accept()), daemon=True).start()
t0 = time.perf_counter()
try:
    httpx2.get(f"http://127.0.0.1:{slow}/x", timeout=2)
except Exception as e:
    print(f"slow server: {type(e).__module__}.{type(e).__name__} after {time.perf_counter() - t0:.2f}s; "
          f"TimeoutException={isinstance(e, httpx2.TimeoutException)} TransportError={isinstance(e, httpx2.TransportError)}")
lsock2 = socket.socket(); lsock2.bind(("127.0.0.1", 0)); lsock2.listen(0); full = lsock2.getsockname()[1]
print("exception hierarchy:", [k.__name__ for k in httpx2.ReadTimeout.__mro__][:6], [k.__name__ for k in httpx2.ConnectError.__mro__][:5])
r = httpx2.get(f"{ADMIN}/users/{alex['id']}", headers=H, timeout=2)
print("a 5xx/4xx is not an exception unless raise_for_status:", r.status_code, "HTTPStatusError" in dir(httpx2))
```

Output (complete):

```text
-- service-account token (client_credentials)
status: 200 | keys: ['access_token', 'expires_in', 'not-before-policy', 'refresh_expires_in', 'scope', 'token_type'] | expires_in: 300 | refresh_expires_in: 0 | refresh_token present: False | fetch 2262 ms
claims: ['acr', 'aud', 'azp', 'email_verified', 'exp', 'iat', 'iss', 'jti', 'preferred_username', 'resource_access', 'scope', 'sub', 'typ'] | azp: ops-view-users | aud: realm-management | realm-management roles: ['query-groups', 'query-users', 'view-users']
second fetch returns a different token: True | expires_in: 300

-- GET /users?username=alex&exact=true
status: 200 | fields: ['access', 'createdTimestamp', 'disableableCredentialTypes', 'email', 'emailVerified', 'enabled', 'firstName', 'id', 'lastName', 'notBefore', 'requiredActions', 'totp', 'username']

-- GET /users/{id} (alex)
status: 200 | fields: ['access', 'createdTimestamp', 'disableableCredentialTypes', 'email', 'emailVerified', 'enabled', 'firstName', 'id', 'lastName', 'notBefore', 'requiredActions', 'totp', 'username'] | enabled: True | username == alex: True | id == path id: True

-- GET /users/{id}?userProfileMetadata=false and briefRepresentation list
list status: 200 | count: 5 | fields per user: ['access', 'createdTimestamp', 'email', 'emailVerified', 'enabled', 'firstName', 'id', 'lastName', 'username']
count: 200 5

-- sub of a token == admin-API user id (direct grant via ops-dev-direct)
token sub == admin id: True

-- GET /users/{random uuid}
status: 404 | body: {'error': 'User not found'}
non-uuid id: 404 | body: {'error': 'User not found'}

-- PUT /users/{alex} {'enabled': true} (a no-op value; must be refused)
status: 403 | body: {'error': 'HTTP 403 Forbidden'}
alex still enabled: True
POST /users/{alex}/logout: 403
GET /users/{alex}/sessions: 200 | count: 11 | fields: ['clients', 'id', 'ipAddress', 'lastAccess', 'rememberMe', 'start', 'transientUser', 'userId', 'username']

-- latency of GET /users/{id}, warm keep-alive client, 10 calls
median ms: 5.5 | min: 4.1 | max: 10.1
new connection per call, median ms: 2020.6
list all users (brief), median ms: 10.5

-- bad / expired bearer
garbage token: 401 None
no token: 401

-- Keycloak unreachable (closed port) and slow (accepts, never answers); timeout=2
closed port: httpx2.ConnectTimeout after 2.01s; isinstance TransportError=True TimeoutException=True
localhost closed port: httpx2.ConnectTimeout after 4.01s; isinstance TransportError=True TimeoutException=True
slow server: httpx2.ReadTimeout after 2.02s; TimeoutException=True TransportError=True
exception hierarchy: ['ReadTimeout', 'TimeoutException', 'TransportError', 'RequestError', 'HTTPError', 'Exception'] ['ConnectError', 'NetworkError', 'TransportError', 'RequestError', 'HTTPError']
a 5xx/4xx is not an exception unless raise_for_status: 200 True
```

Script `m3b_localhost.py`:

```python
"""M3b: why a new connection to `localhost` costs ~2 s on this host, and what 127.0.0.1 changes."""
import asyncio
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import median_ms, read_secret, unverified_claims  # noqa: E402

import httpx2  # noqa: E402

print("getaddrinfo('localhost', 18080):", [(ai[0].name, ai[4][0]) for ai in socket.getaddrinfo("localhost", 18080, type=socket.SOCK_STREAM)])
SECRET = read_secret("kc_client_secret_ops_view_users")
for host in ("localhost", "127.0.0.1"):
    base = f"http://{host}:18080"
    t0 = time.perf_counter()
    r = httpx2.post(f"{base}/realms/ops-dev/protocol/openid-connect/token", data={"grant_type": "client_credentials"},
                    auth=("ops-view-users", SECRET), timeout=5)
    dt = time.perf_counter() - t0
    tok = r.json()["access_token"]
    print(f"{host}: token fetch {dt * 1000:.0f} ms | iss: {unverified_claims(tok)['iss']}")
    s = []
    for _ in range(10):
        t0 = time.perf_counter()
        httpx2.get(f"{base}/admin/realms/ops-dev/users/count", headers={"Authorization": f"Bearer {tok}"}, timeout=5).raise_for_status()
        s.append(time.perf_counter() - t0)
    print(f"{host}: new connection per GET, median ms: {median_ms(s)}")
    r = httpx2.get(f"{base}/realms/ops-dev/.well-known/openid-configuration", timeout=5).json()
    print(f"{host}: discovery issuer: {r['issuer']}")

print("\n-- closed port on 127.0.0.1 with connect timeouts 0.5 / 2 / 5 s")
s = socket.socket(); s.bind(("127.0.0.1", 0)); closed = s.getsockname()[1]; s.close()
for t in (0.5, 2, 5):
    t0 = time.perf_counter()
    try:
        httpx2.get(f"http://127.0.0.1:{closed}/", timeout=t)
    except Exception as e:
        print(f"timeout={t}: {type(e).__name__} after {time.perf_counter() - t0:.2f}s")
t0 = time.perf_counter()
try:
    socket.create_connection(("127.0.0.1", closed), timeout=10)
except Exception as e:
    print(f"raw socket.create_connection, timeout 10: {type(e).__name__} after {time.perf_counter() - t0:.2f}s")

print("\n-- a hard 2 s overall budget around a call that would take 4 s (localhost, closed port)")


async def call():
    async with httpx2.AsyncClient(timeout=2) as c:
        return await c.get(f"http://localhost:{closed}/")


t0 = time.perf_counter()
try:
    asyncio.run(asyncio.wait_for(call(), 2))
except Exception as e:
    print(f"asyncio.wait_for(…, 2): {type(e).__name__} after {time.perf_counter() - t0:.2f}s")
```

Output (complete):

```text
getaddrinfo('localhost', 18080): [('AF_INET6', '::1'), ('AF_INET', '127.0.0.1')]
localhost: token fetch 2221 ms | iss: http://localhost:18080/realms/ops-dev
localhost: new connection per GET, median ms: 2050.7
localhost: discovery issuer: http://localhost:18080/realms/ops-dev
127.0.0.1: token fetch 11 ms | iss: http://localhost:18080/realms/ops-dev
127.0.0.1: new connection per GET, median ms: 8.0
127.0.0.1: discovery issuer: http://localhost:18080/realms/ops-dev

-- closed port on 127.0.0.1 with connect timeouts 0.5 / 2 / 5 s
timeout=0.5: ConnectTimeout after 0.51s
timeout=2: ConnectTimeout after 2.01s
timeout=5: ConnectError after 2.04s
raw socket.create_connection, timeout 10: ConnectionRefusedError after 2.05s

-- a hard 2 s overall budget around a call that would take 4 s (localhost, closed port)
asyncio.wait_for(…, 2): TimeoutError after 2.00s
```

Findings:

- **Service-account token.** `client_credentials` gives `expires_in: 300` and `refresh_expires_in: 0`, with **no refresh token**. Every fetch returns a new token. Claims: `azp: ops-view-users`, `aud: realm-management`, `resource_access.realm-management.roles = [query-groups, query-users, view-users]`. Cache the token until `exp` minus a margin, and re-fetch on a 401.
- **`GET /admin/realms/ops-dev/users/{id}`** gives 200 with `access, createdTimestamp, disableableCredentialTypes, email, emailVerified, enabled, firstName, id, lastName, notBefore, requiredActions, totp, username`. That includes personal data, so read `enabled` (and `id`) and drop the rest. **An unknown user is 404 `{"error": "User not found"}`, and so is a non-UUID id.** A deleted user is therefore indistinguishable from a typo, and both must count as "not enabled".
- **The list form for the sync.** `GET /users?briefRepresentation=true&max=100` gives 200 with `access, createdTimestamp, email, emailVerified, enabled, firstName, id, lastName, username` for the 5 personas. The median latency is 10.5 ms. `GET /users/count` returns `5`. One list call per sync round is cheaper than one GET per member.
- **`sub` equals the admin-API user `id`** (checked with a direct-grant token for alex), which is the assumption in AM-20.7 5(b).
- **Least privilege:**
  - `PUT /users/{id}` with the no-op body `{"enabled": true}` gives **403 `{"error": "HTTP 403 Forbidden"}`**, and alex stayed enabled.
  - `POST /users/{id}/logout` gives 403.
  - `GET /users/{id}/sessions` is allowed (200). It listed 11 sessions this spike had opened for alex, with fields `clients, id, ipAddress, lastAccess, rememberMe, start, transientUser, userId, username`.
  - A garbage or missing bearer gives 401 with no `WWW-Authenticate` header.
- **Latency:**
  - The median of 10 GETs on a warm keep-alive client is **5.5 ms** (4.1–10.1).
  - **A new connection per call through `localhost` takes 2 020 ms**, and the token fetch 2 262 ms. `getaddrinfo('localhost')` returns `::1` first, the container port is published on `127.0.0.1` only, and the IPv6 attempt costs ≈2 s before the IPv4 fallback.
  - Through `127.0.0.1`, a token fetch takes 11 ms and a new-connection GET 8 ms. **`iss` stays `http://localhost:18080/realms/ops-dev`** (pinned by `KC_HOSTNAME`), so back-end calls can use `127.0.0.1` without breaking issuer checks.
- **When the identity provider is unreachable or slow** (`timeout=2`):
  - **A closed port on `127.0.0.1` raised `httpx2.ConnectTimeout` after 2.01 s, not `ConnectError`.** On this host a refused TCP connect is retried for ≈2 s (raw `socket.create_connection` gives `ConnectionRefusedError` after 2.05 s). With `timeout=5` it surfaced as `ConnectError` after 2.04 s.
  - **Through `localhost` it took 4.01 s with `timeout=2`**: the connect timeout applies per address (`::1`, then `127.0.0.1`).
  - A server that accepts and never answers gives `httpx2.ReadTimeout` after 2.02 s.
  - Every case is a subclass of `httpx2.TransportError` (and `RequestError`, `HTTPError`). `ReadTimeout` and `ConnectTimeout` are also `TimeoutException`. A 4xx or 5xx raises nothing unless `raise_for_status()` is called.
  - **The 503 `retryable` mapping:** catch `httpx2.TransportError` (plus `HTTPStatusError` for 5xx), and bound the whole call with an overall deadline. `asyncio.wait_for(call, 2)` cut the 4 s case off at 2.00 s with `TimeoutError`.

## 4. Sessions and CSRF in the locked web stack

Script `m4_web.py`:

```python
"""M4a: cookies, TestClient behaviour, an Origin check and a double-submit CSRF check in the locked FastAPI/Starlette."""
import hashlib
import hmac
import inspect
import secrets
import warnings

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.responses import Response as SResponse

print("Response.set_cookie signature:", inspect.signature(SResponse.set_cookie))

ALLOWED_ORIGIN = "http://localhost:8000"
app = FastAPI()
SEEN = {}


@app.middleware("http")
async def csrf_and_origin(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.url.path.startswith("/api/"):
        origin = request.headers.get("origin")
        if origin is None:
            ref = request.headers.get("referer")
            origin = "/".join(ref.split("/")[:3]) if ref else None
        if origin != ALLOWED_ORIGIN:
            return JSONResponse({"error": "origin", "got": origin}, status_code=403)
        c, h = request.cookies.get("ops_csrf"), request.headers.get("x-csrf-token")
        if not c or not h or not hmac.compare_digest(c, h):
            return JSONResponse({"error": "csrf"}, status_code=403)
    return await call_next(request)


@app.get("/login")
def login(response: Response, variant: str = "default"):
    sid = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    if variant == "default":
        response.set_cookie("ops_session", sid)
    else:
        response.set_cookie("ops_session", sid, httponly=True, secure=(variant == "secure"), samesite="lax",
                            max_age=8 * 3600, path="/")
        response.set_cookie("ops_csrf", csrf, httponly=False, secure=(variant == "secure"), samesite="strict",
                            max_age=8 * 3600, path="/")
    return {"ok": True}


@app.get("/whoami")
def whoami(request: Request):
    SEEN["headers"] = sorted(request.headers.keys())
    return {"session_cookie": "ops_session" in request.cookies, "csrf_cookie": "ops_csrf" in request.cookies}


@app.post("/api/decide")
def decide():
    return {"decided": True}


@app.post("/logout")
def logout(response: Response):
    response.delete_cookie("ops_session", path="/")
    return {"ok": True}


def cookie_attrs(r):
    out = []
    for sc in r.headers.get_list("set-cookie"):
        name, rest = sc.split("=", 1)
        out.append((name, [a.strip() for a in rest.split(";")[1:]]))
    return out


with TestClient(app) as c:
    print("\n-- set_cookie with only key/value (defaults)")
    r = c.get("/login")
    print("Set-Cookie attrs:", cookie_attrs(r))
    print("\n-- explicit httponly/secure=False/samesite/max_age/path")
    r = c.get("/login", params={"variant": "plain"})
    print("Set-Cookie attrs:", cookie_attrs(r))
    print("jar after:", sorted(c.cookies.keys()), "| next request sends them:", c.get("/whoami").json())
    print("headers a TestClient request carries:", SEEN["headers"])

    print("\n-- CSRF + Origin on POST /api/decide")
    tokn = c.cookies.get("ops_csrf")
    for label, hdrs in (("no Origin, no token", {}),
                        ("Origin ok, no token", {"Origin": ALLOWED_ORIGIN}),
                        ("Origin ok, wrong token", {"Origin": ALLOWED_ORIGIN, "X-CSRF-Token": "x" * 43}),
                        ("Origin ok, right token", {"Origin": ALLOWED_ORIGIN, "X-CSRF-Token": tokn}),
                        ("Origin evil, right token", {"Origin": "http://evil.example", "X-CSRF-Token": tokn}),
                        ("Referer only (same origin), right token", {"Referer": ALLOWED_ORIGIN + "/runs/1", "X-CSRF-Token": tokn}),
                        ("Origin 'null', right token", {"Origin": "null", "X-CSRF-Token": tokn})):
        r = c.post("/api/decide", headers=hdrs)
        print(f"  {label}: {r.status_code} {r.json()}")

    print("\n-- delete_cookie")
    r = c.post("/logout")
    print("Set-Cookie attrs:", cookie_attrs(r), "| jar after:", sorted(c.cookies.keys()))

print("\n-- secure=True cookies and the TestClient base URL")
for base in ("http://testserver", "https://testserver"):
    with TestClient(app, base_url=base) as c:
        r = c.get("/login", params={"variant": "secure"})
        print(f"{base}: jar keys {sorted(c.cookies.keys())} | sent back: {c.get('/whoami').json()}")

print("\n-- per-request cookies= (deprecated in the httpx API?)")
with TestClient(app) as c, warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    r = c.get("/whoami", cookies={"ops_session": "x"})
    print("result:", r.json(), "| warnings:", [str(x.category.__name__) + ": " + str(x.message)[:90] for x in w])

print("\n-- opaque session id and its stored hash")
sid = secrets.token_urlsafe(32)
h = hashlib.sha256(sid.encode()).hexdigest()
print("token_urlsafe(32) length:", len(sid), "| sha256 hexdigest length:", len(h),
      "| alphabet ok for a cookie:", all(ch.isalnum() or ch in "-_" for ch in sid))
```

Output (complete):

```text
Response.set_cookie signature: (self, key: 'str', value: 'str' = '', max_age: 'int | None' = None, expires: 'datetime | str | int | None' = None, path: 'str | None' = '/', domain: 'str | None' = None, secure: 'bool' = False, httponly: 'bool' = False, samesite: "Literal['lax', 'strict', 'none'] | None" = 'lax', partitioned: 'bool' = False) -> 'None'

-- set_cookie with only key/value (defaults)
Set-Cookie attrs: [('ops_session', ['Path=/', 'SameSite=lax'])]

-- explicit httponly/secure=False/samesite/max_age/path
Set-Cookie attrs: [('ops_session', ['HttpOnly', 'Max-Age=28800', 'Path=/', 'SameSite=lax']), ('ops_csrf', ['Max-Age=28800', 'Path=/', 'SameSite=strict'])]
jar after: ['ops_csrf', 'ops_session'] | next request sends them: {'session_cookie': True, 'csrf_cookie': True}
headers a TestClient request carries: ['accept', 'accept-encoding', 'connection', 'cookie', 'host', 'user-agent']

-- CSRF + Origin on POST /api/decide
  no Origin, no token: 403 {'error': 'origin', 'got': None}
  Origin ok, no token: 403 {'error': 'csrf'}
  Origin ok, wrong token: 403 {'error': 'csrf'}
  Origin ok, right token: 200 {'decided': True}
  Origin evil, right token: 403 {'error': 'origin', 'got': 'http://evil.example'}
  Referer only (same origin), right token: 200 {'decided': True}
  Origin 'null', right token: 403 {'error': 'origin', 'got': 'null'}

-- delete_cookie
Set-Cookie attrs: [('ops_session', ['expires=Fri, 09 Oct 2026 06:33:05 GMT', 'Max-Age=0', 'Path=/', 'SameSite=lax'])] | jar after: ['ops_csrf']

-- secure=True cookies and the TestClient base URL
http://testserver: jar keys ['ops_csrf', 'ops_session'] | sent back: {'session_cookie': False, 'csrf_cookie': False}
https://testserver: jar keys ['ops_csrf', 'ops_session'] | sent back: {'session_cookie': True, 'csrf_cookie': True}

-- per-request cookies= (deprecated in the httpx API?)
result: {'session_cookie': True, 'csrf_cookie': False} | warnings: ['DeprecationWarning: Setting per-request cookies=<...> is being deprecated, because the expected behaviour on c']

-- opaque session id and its stored hash
token_urlsafe(32) length: 43 | sha256 hexdigest length: 64 | alphabet ok for a cookie: True
```

Script `m45_pg.py` (measurement 4's `sessions` half and all of measurement 5):

```python
"""M4b + M5: the app.sessions shape under the AM-20.2 grants, a sweeper with DELETE only, a logout-jti replay table,
and a sync_memberships shape (definer vs invoker) on memberships with FORCE RLS + tenant_isolation + sweeper_all.
Everything lives in schema spike_app (database ops) and roles spike_*; schema app is never touched."""
import hashlib
import secrets
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import SPIKE_PW, as_role, su, try_  # noqa: E402

T1, T2 = uuid.UUID(int=1), uuid.UUID(int=2)
ALEX, SAM = uuid.uuid4(), uuid.uuid4()
ISS = "http://localhost:18080/realms/ops-dev"
TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

SETUP = f"""
DROP SCHEMA IF EXISTS spike_app CASCADE;
DO $$ DECLARE r text; BEGIN
  FOREACH r IN ARRAY ARRAY['spike_api','spike_sweeper','spike_definer','spike_owner'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN EXECUTE format('DROP OWNED BY %I', r); EXECUTE format('DROP ROLE %I', r); END IF;
  END LOOP; END $$;
CREATE ROLE spike_owner NOLOGIN;
CREATE ROLE spike_definer NOLOGIN;
CREATE ROLE spike_api LOGIN PASSWORD '{SPIKE_PW}';
CREATE ROLE spike_sweeper LOGIN PASSWORD '{SPIKE_PW}';
CREATE SCHEMA spike_app AUTHORIZATION spike_owner;
GRANT CONNECT ON DATABASE ops TO spike_api, spike_sweeper;  -- PUBLIC has no CONNECT since T09; DROP OWNED BY revokes it
GRANT CREATE ON SCHEMA spike_app TO spike_definer;
SET ROLE spike_owner;
CREATE TABLE spike_app.tenants (tenant_id uuid PRIMARY KEY, name text NOT NULL);
CREATE TABLE spike_app.memberships (
    tenant_id uuid NOT NULL REFERENCES spike_app.tenants (tenant_id), issuer text NOT NULL, subject uuid NOT NULL,
    role text NOT NULL CHECK (role IN ('requester', 'reviewer', 'reader')), active boolean NOT NULL DEFAULT true,
    permission_version integer NOT NULL DEFAULT 1, synced_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, issuer, subject, role));
CREATE TABLE spike_app.sessions (
    session_sha256 text PRIMARY KEY, issuer text NOT NULL, subject uuid NOT NULL,
    tenant_id uuid NOT NULL REFERENCES spike_app.tenants (tenant_id), csrf_secret_sha256 text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL DEFAULT now(), revoked_at timestamptz);
CREATE TABLE spike_app.spike_logout_jti (jti text PRIMARY KEY, exp timestamptz NOT NULL);
INSERT INTO spike_app.tenants VALUES ('{T1}', 't1'), ('{T2}', 't2');
INSERT INTO spike_app.memberships (tenant_id, issuer, subject, role) VALUES
  ('{T1}', '{ISS}', '{ALEX}', 'requester'), ('{T1}', '{ISS}', '{SAM}', 'reviewer'),
  ('{T2}', '{ISS}', '{ALEX}', 'reader'),    ('{T2}', '{ISS}', '{SAM}', 'requester');
ALTER TABLE spike_app.memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE spike_app.memberships FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON spike_app.memberships FOR ALL TO spike_api, spike_sweeper, spike_definer
  USING (tenant_id = {TENANT}) WITH CHECK (tenant_id = {TENANT});
CREATE POLICY sweeper_all ON spike_app.memberships FOR ALL TO spike_sweeper USING (true) WITH CHECK (true);
GRANT USAGE ON SCHEMA spike_app TO spike_api, spike_sweeper, spike_definer;
GRANT SELECT ON spike_app.tenants TO spike_api, spike_sweeper, spike_definer;
-- AM-20.2 cells, copied from GRANTS_0002
GRANT SELECT ON spike_app.memberships TO spike_api, spike_definer;
GRANT SELECT, UPDATE (active, permission_version, synced_at) ON spike_app.memberships TO spike_sweeper;
GRANT SELECT, INSERT, UPDATE (last_seen_at, revoked_at), DELETE ON spike_app.sessions TO spike_api;
GRANT DELETE ON spike_app.sessions TO spike_sweeper;
GRANT INSERT ON spike_app.spike_logout_jti TO spike_api;
RESET ROLE;
"""

with su() as s:
    print("datacl of ops before setup:", s.execute("SELECT datacl FROM pg_database WHERE datname = 'ops'").fetchone()[0])
    s.execute(SETUP)
print("setup done: schema spike_app, roles spike_owner/spike_definer/spike_api/spike_sweeper")

print("\n== M4b sessions as spike_api (sel, ins, upd(last_seen_at, revoked_at), del)")
sid = secrets.token_urlsafe(32)
h = hashlib.sha256(sid.encode()).hexdigest()
csrf_h = hashlib.sha256(secrets.token_urlsafe(32).encode()).hexdigest()
with as_role("spike_api", autocommit=True) as a:
    try_("INSERT session", lambda: a.execute(
        "INSERT INTO spike_app.sessions (session_sha256, issuer, subject, tenant_id, csrf_secret_sha256, expires_at)"
        " VALUES (%s, %s, %s, %s, %s, now() + interval '8 hours')", (h, ISS, ALEX, T1, csrf_h)).rowcount)
    try_("INSERT ... RETURNING created_at", lambda: a.execute(
        "INSERT INTO spike_app.sessions (session_sha256, issuer, subject, tenant_id, csrf_secret_sha256, expires_at)"
        " VALUES (%s, %s, %s, %s, %s, now() + interval '8 hours') RETURNING created_at IS NOT NULL",
        (hashlib.sha256(b"x2").hexdigest(), ISS, ALEX, T2, csrf_h)).fetchone())
    try_("pre-login row (no subject/tenant: where authlib state would go)", lambda: a.execute(
        "INSERT INTO spike_app.sessions (session_sha256, issuer, subject, tenant_id, csrf_secret_sha256, expires_at)"
        " VALUES (%s, %s, NULL, NULL, %s, now() + interval '10 minutes')", (hashlib.sha256(b"pre").hexdigest(), ISS, csrf_h)).rowcount)
    try_("lookup by hash (live, idle < 30 min)", lambda: a.execute(
        "SELECT subject = %s, tenant_id = %s FROM spike_app.sessions WHERE session_sha256 = %s AND revoked_at IS NULL"
        " AND expires_at > now() AND last_seen_at > now() - interval '30 minutes'",
        (ALEX, T1, hashlib.sha256(sid.encode()).hexdigest())).fetchone())
    try_("lookup with the raw id (must miss)", lambda: a.execute(
        "SELECT count(*) FROM spike_app.sessions WHERE session_sha256 = %s", (sid,)).fetchone())
    try_("UPDATE last_seen_at (touch)", lambda: a.execute(
        "UPDATE spike_app.sessions SET last_seen_at = now() WHERE session_sha256 = %s", (h,)).rowcount)
    try_("UPDATE expires_at (sliding expiry)", lambda: a.execute(
        "UPDATE spike_app.sessions SET expires_at = now() + interval '8 hours' WHERE session_sha256 = %s", (h,)).rowcount)
    try_("UPDATE revoked_at by (issuer, subject): backchannel logout by sub", lambda: a.execute(
        "UPDATE spike_app.sessions SET revoked_at = now() WHERE issuer = %s AND subject = %s AND revoked_at IS NULL",
        (ISS, ALEX)).rowcount)
    try_("UPDATE revoked_at by Keycloak sid (no such column)", lambda: a.execute(
        "UPDATE spike_app.sessions SET revoked_at = now() WHERE kc_sid = %s", ("abc",)).rowcount)
    try_("DELETE by hash", lambda: a.execute("DELETE FROM spike_app.sessions WHERE session_sha256 = %s", (h,)).rowcount)

with su() as s:
    s.execute("INSERT INTO spike_app.sessions (session_sha256, issuer, subject, tenant_id, csrf_secret_sha256, expires_at)"
              " VALUES ('old1', %s, %s, %s, 'c', now() - interval '1 minute'), ('new1', %s, %s, %s, 'c', now() + interval '1 hour')",
              (ISS, ALEX, T1, ISS, SAM, T1))
print("\n== sweeper with DELETE only on sessions")
with as_role("spike_sweeper", autocommit=True) as w:
    try_("DELETE ... WHERE expires_at < now()", lambda: w.execute(
        "DELETE FROM spike_app.sessions WHERE expires_at < now()").rowcount)
    try_("DELETE ... WHERE revoked_at IS NOT NULL", lambda: w.execute(
        "DELETE FROM spike_app.sessions WHERE revoked_at IS NOT NULL").rowcount)
    try_("DELETE ... (no WHERE) inside a rolled-back transaction", lambda: (w.execute("BEGIN"), w.execute(
        "DELETE FROM spike_app.sessions").rowcount, w.execute("ROLLBACK"))[1])
with su() as s:
    s.execute("GRANT SELECT (expires_at, revoked_at) ON spike_app.sessions TO spike_sweeper")
print("  (granted SELECT (expires_at, revoked_at) to spike_sweeper)")
with as_role("spike_sweeper", autocommit=True) as w:
    try_("DELETE ... WHERE expires_at < now() with column SELECT", lambda: w.execute(
        "DELETE FROM spike_app.sessions WHERE expires_at < now()").rowcount)
    try_("SELECT session_sha256 (still denied)", lambda: w.execute("SELECT session_sha256 FROM spike_app.sessions").fetchall())

print("\n== M5a logout jti replay store as spike_api (INSERT only)")
with as_role("spike_api", autocommit=True) as a:
    j = str(uuid.uuid4())
    try_("first INSERT ... ON CONFLICT DO NOTHING (rowcount)", lambda: a.execute(
        "INSERT INTO spike_app.spike_logout_jti VALUES (%s, now() + interval '2 minutes') ON CONFLICT DO NOTHING", (j,)).rowcount)
    try_("replay, same statement (rowcount)", lambda: a.execute(
        "INSERT INTO spike_app.spike_logout_jti VALUES (%s, now() + interval '2 minutes') ON CONFLICT DO NOTHING", (j,)).rowcount)
    try_("ON CONFLICT (jti) DO NOTHING (with a target)", lambda: a.execute(
        "INSERT INTO spike_app.spike_logout_jti VALUES (%s, now() + interval '2 minutes') ON CONFLICT (jti) DO NOTHING", (j,)).rowcount)
    try_("plain INSERT replay", lambda: a.execute(
        "INSERT INTO spike_app.spike_logout_jti VALUES (%s, now())", (j,)).rowcount)
    try_("... RETURNING jti", lambda: a.execute(
        "INSERT INTO spike_app.spike_logout_jti VALUES (%s, now()) ON CONFLICT DO NOTHING RETURNING jti", (str(uuid.uuid4()),)).fetchall())
    try_("DELETE expired jti rows", lambda: a.execute("DELETE FROM spike_app.spike_logout_jti WHERE exp < now()").rowcount)
    print("  same-transaction: jti insert + session revoke, then ROLLBACK -> jti not consumed")
    a.execute("BEGIN")
    j2 = str(uuid.uuid4())
    a.execute("INSERT INTO spike_app.spike_logout_jti VALUES (%s, now() + interval '2 minutes') ON CONFLICT DO NOTHING", (j2,))
    a.execute("ROLLBACK")
    try_("  re-insert after rollback (rowcount)", lambda: a.execute(
        "INSERT INTO spike_app.spike_logout_jti VALUES (%s, now() + interval '2 minutes') ON CONFLICT DO NOTHING", (j2,)).rowcount)

print("\n== M5b sync_memberships shapes")
DEFINER_FN = f"""
CREATE FUNCTION spike_app.sync_memberships_definer(p_inactive uuid[], p_now timestamptz) RETURNS int
LANGUAGE plpgsql SECURITY DEFINER SET search_path = spike_app, pg_temp SET app.tenant_id = '' AS $fn$
DECLARE v_t uuid; v_n int := 0; v_k int; v_seen int;
BEGIN
  SELECT count(*) INTO v_seen FROM memberships;
  RAISE NOTICE 'definer sees % membership rows before any tenant is set (current_user=%)', v_seen, current_user;
  FOR v_t IN SELECT tenant_id FROM tenants ORDER BY tenant_id LOOP
    PERFORM set_config('app.tenant_id', v_t::text, true);
    PERFORM 1 FROM memberships WHERE subject = ANY (p_inactive) AND active FOR UPDATE;
    UPDATE memberships SET active = false, permission_version = permission_version + 1, synced_at = p_now
      WHERE subject = ANY (p_inactive) AND active;
    GET DIAGNOSTICS v_k = ROW_COUNT; v_n := v_n + v_k;
  END LOOP;
  RETURN v_n;
END $fn$;
ALTER FUNCTION spike_app.sync_memberships_definer(uuid[], timestamptz) OWNER TO spike_definer;
REVOKE ALL ON FUNCTION spike_app.sync_memberships_definer(uuid[], timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION spike_app.sync_memberships_definer(uuid[], timestamptz) TO spike_sweeper;
CREATE FUNCTION spike_app.sync_memberships_invoker(p_inactive uuid[], p_now timestamptz) RETURNS int
LANGUAGE plpgsql SECURITY INVOKER SET search_path = spike_app, pg_temp AS $fn$
DECLARE v_n int;
BEGIN
  PERFORM 1 FROM memberships WHERE subject = ANY (p_inactive) AND active FOR UPDATE;
  UPDATE memberships SET active = false, permission_version = permission_version + 1, synced_at = p_now
    WHERE subject = ANY (p_inactive) AND active;
  GET DIAGNOSTICS v_n = ROW_COUNT;
  RETURN v_n;
END $fn$;
REVOKE ALL ON FUNCTION spike_app.sync_memberships_invoker(uuid[], timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION spike_app.sync_memberships_invoker(uuid[], timestamptz) TO spike_sweeper;
"""
with su() as s:
    s.execute(DEFINER_FN)


def state():
    with su() as s:
        return s.execute("SELECT t.name, m.role, m.active, m.permission_version FROM spike_app.memberships m "
                         "JOIN spike_app.tenants t USING (tenant_id) WHERE subject = %s ORDER BY 1, 2", (ALEX,)).fetchall()


def reset():
    with su() as s:
        s.execute("UPDATE spike_app.memberships SET active = true, permission_version = 1")


with as_role("spike_sweeper", autocommit=True) as w:
    w.add_notice_handler(lambda d: print("  NOTICE:", d.message_primary))
    print("sweeper sees (sweeper_all), no GUC:", w.execute("SELECT count(*) FROM spike_app.memberships").fetchone()[0], "rows")
    try_("sweeper SELECT ... FOR UPDATE (column UPDATE grant only)", lambda: len(w.execute(
        "SELECT 1 FROM spike_app.memberships FOR UPDATE").fetchall()))
    try_("sweeper UPDATE role (not granted)", lambda: w.execute(
        "UPDATE spike_app.memberships SET role = 'reader' WHERE false").rowcount)
    try_("definer, AM-20.2 cells (definer has SELECT only)", lambda: w.execute(
        "SELECT spike_app.sync_memberships_definer(%s, now())", ([ALEX],)).fetchone())
    print("  alex after:", state())
with su() as s:
    s.execute("GRANT UPDATE (active, permission_version, synced_at) ON spike_app.memberships TO spike_definer")
print("  (granted UPDATE (active, permission_version, synced_at) to spike_definer)")
with as_role("spike_sweeper", autocommit=True) as w:
    w.add_notice_handler(lambda d: print("  NOTICE:", d.message_primary))
    try_("definer with UPDATE grant, iterating tenants", lambda: w.execute(
        "SELECT spike_app.sync_memberships_definer(%s, now())", ([ALEX],)).fetchone())
    print("  alex after:", state())
    try_("definer again (idempotent)", lambda: w.execute(
        "SELECT spike_app.sync_memberships_definer(%s, now())", ([ALEX],)).fetchone())
    print("  sweeper GUC after the call:", repr(w.execute("SELECT current_setting('app.tenant_id', true)").fetchone()[0]))
    reset()
    try_("invoker (runs as sweeper: sweeper_all + column UPDATE)", lambda: w.execute(
        "SELECT spike_app.sync_memberships_invoker(%s, now())", ([ALEX],)).fetchone())
    print("  alex after:", state())
    reset()
with su() as s:
    s.execute("DROP POLICY sweeper_all ON spike_app.memberships")
print("  (dropped sweeper_all to show what it buys)")
with as_role("spike_sweeper", autocommit=True) as w:
    try_("invoker without sweeper_all, no GUC", lambda: w.execute(
        "SELECT spike_app.sync_memberships_invoker(%s, now())", ([ALEX],)).fetchone())
    try_("sweeper sees without sweeper_all", lambda: w.execute("SELECT count(*) FROM spike_app.memberships").fetchone())
```

Output (complete):

```text
datacl of ops before setup: ['=T/ops', 'ops=CTc/ops', 'api=c/ops', 'worker=c/ops', 'sweeper=c/ops', 'mcp_read=c/ops', 'mcp_exec=c/ops', 'operator=c/ops']
setup done: schema spike_app, roles spike_owner/spike_definer/spike_api/spike_sweeper

== M4b sessions as spike_api (sel, ins, upd(last_seen_at, revoked_at), del)
INSERT session: OK -> 1
INSERT ... RETURNING created_at: OK -> (True,)
pre-login row (no subject/tenant: where authlib state would go): NotNullViolation sqlstate=23502 primary='null value in column "subject" of relation "sessions" violates not-null constraint'
lookup by hash (live, idle < 30 min): OK -> (True, True)
lookup with the raw id (must miss): OK -> (0,)
UPDATE last_seen_at (touch): OK -> 1
UPDATE expires_at (sliding expiry): InsufficientPrivilege sqlstate=42501 primary='permission denied for table sessions'
UPDATE revoked_at by (issuer, subject): backchannel logout by sub: OK -> 2
UPDATE revoked_at by Keycloak sid (no such column): UndefinedColumn sqlstate=42703 primary='column "kc_sid" does not exist'
DELETE by hash: OK -> 1

== sweeper with DELETE only on sessions
DELETE ... WHERE expires_at < now(): InsufficientPrivilege sqlstate=42501 primary='permission denied for table sessions'
DELETE ... WHERE revoked_at IS NOT NULL: InsufficientPrivilege sqlstate=42501 primary='permission denied for table sessions'
DELETE ... (no WHERE) inside a rolled-back transaction: OK -> 3
  (granted SELECT (expires_at, revoked_at) to spike_sweeper)
DELETE ... WHERE expires_at < now() with column SELECT: OK -> 1
SELECT session_sha256 (still denied): InsufficientPrivilege sqlstate=42501 primary='permission denied for table sessions'

== M5a logout jti replay store as spike_api (INSERT only)
first INSERT ... ON CONFLICT DO NOTHING (rowcount): OK -> 1
replay, same statement (rowcount): OK -> 0
ON CONFLICT (jti) DO NOTHING (with a target): InsufficientPrivilege sqlstate=42501 primary='permission denied for table spike_logout_jti'
plain INSERT replay: UniqueViolation sqlstate=23505 primary='duplicate key value violates unique constraint "spike_logout_jti_pkey"'
... RETURNING jti: InsufficientPrivilege sqlstate=42501 primary='permission denied for table spike_logout_jti'
DELETE expired jti rows: InsufficientPrivilege sqlstate=42501 primary='permission denied for table spike_logout_jti'
  same-transaction: jti insert + session revoke, then ROLLBACK -> jti not consumed
  re-insert after rollback (rowcount): OK -> 1

== M5b sync_memberships shapes
sweeper sees (sweeper_all), no GUC: 4 rows
sweeper SELECT ... FOR UPDATE (column UPDATE grant only): OK -> 4
sweeper UPDATE role (not granted): InsufficientPrivilege sqlstate=42501 primary='permission denied for table memberships'
  NOTICE: definer sees 0 membership rows before any tenant is set (current_user=spike_definer)
definer, AM-20.2 cells (definer has SELECT only): InsufficientPrivilege sqlstate=42501 primary='permission denied for table memberships'
  alex after: [('t1', 'requester', True, 1), ('t2', 'reader', True, 1)]
  (granted UPDATE (active, permission_version, synced_at) to spike_definer)
  NOTICE: definer sees 0 membership rows before any tenant is set (current_user=spike_definer)
definer with UPDATE grant, iterating tenants: OK -> (2,)
  alex after: [('t1', 'requester', False, 2), ('t2', 'reader', False, 2)]
  NOTICE: definer sees 0 membership rows before any tenant is set (current_user=spike_definer)
definer again (idempotent): OK -> (0,)
  sweeper GUC after the call: ''
invoker (runs as sweeper: sweeper_all + column UPDATE): OK -> (2,)
  alex after: [('t1', 'requester', False, 2), ('t2', 'reader', False, 2)]
  (dropped sweeper_all to show what it buys)
invoker without sweeper_all, no GUC: OK -> (0,)
sweeper sees without sweeper_all: OK -> (0,)
```

Findings (web):

- **`Response.set_cookie` defaults** are `max_age=None, expires=None, path='/', domain=None, secure=False, httponly=False, samesite='lax', partitioned=False`. A bare `set_cookie(k, v)` emits only `Path=/; SameSite=lax`: a JS-readable browser-session cookie. The session cookie must pass `httponly=True`, `secure=True` (outside plain-http dev), `samesite="lax"` and `max_age`. `delete_cookie` emits `Max-Age=0` plus an `expires`, but not `HttpOnly` or `Secure` unless they are passed again.
- **TestClient:**
  - It keeps a cookie jar across requests.
  - It sends exactly `accept, accept-encoding, connection, cookie, host, user-agent`, **never `Origin` or `Referer`**, so origin-check tests must set them explicitly, and a missing Origin is what an unmodified test sends.
  - **It stores `Secure` cookies but does not send them back to `http://testserver`**, the same stdlib-jar rule as in measurement 1. `TestClient(app, base_url="https://testserver")` sends them.
  - Per-request `cookies=` emits a DeprecationWarning ("Setting per-request cookies=<...> is being deprecated").
- **Origin plus double-submit middleware** (a sketch on unsafe methods under `/api/`). Missing Origin and Referer gives 403. A correct Origin with no token, or with a wrong token (`hmac.compare_digest`), gives 403. The right token from a foreign Origin, or from `Origin: null`, gives 403. A same-origin Referer without an Origin plus the right token gives 200. The `sessions` table's `csrf_secret_sha256` column suggests a synchronizer token bound to the session, compared against a hash, rather than a pure cookie double-submit. Either works with this middleware shape.
- **Session id.** `secrets.token_urlsafe(32)` is 43 cookie-safe characters, and its `hashlib.sha256(...).hexdigest()` is 64 characters. Look it up by hash; the raw id never matches.

Findings (PostgreSQL, the `app.sessions` shape from revision 0002 with exactly AM-20.2's cells):

- **`api`** (`sel, ins, upd(last_seen_at, revoked_at), del`):
  - INSERT works, and so does `INSERT … RETURNING` (it has SELECT).
  - The lookup `WHERE session_sha256 = $1 AND revoked_at IS NULL AND expires_at > now() AND last_seen_at > now() - interval '30 minutes'` works, and so do touching `last_seen_at`, revoking by `(issuer, subject)` (2 rows) and DELETE by hash.
  - **`UPDATE … SET expires_at` gives 42501**, so the absolute expiry is fixed at login and idle expiry has to be computed from `last_seen_at` (this matches the grants).
- **No `sid` column** (`kc_sid` gives 42703). Back-channel logout can only revoke *all* of a user's sessions by `(issuer, subject)` unless T11's revision adds the identity provider's `sid` to `sessions`.
- **No place for pre-login state.** A row without `subject` or `tenant_id` gives 23502. AM-20.7 item 10 puts authlib's `state`, `nonce` and `code_verifier` in "that store", so T11 needs either a separate short-lived `login_state` table (with its own grants) or nullable columns. That is a schema and grants decision for the plan.
- **A sweeper with DELETE only:** `DELETE … WHERE expires_at < now()` and `… WHERE revoked_at IS NOT NULL` both give 42501. Only an unconditional `DELETE` works (3 rows, rolled back). After `GRANT SELECT (expires_at, revoked_at)` the filtered DELETE works (1 row) and `session_sha256` stays unreadable (42501). **This confirms Plan E's finding:** a WHERE on a column needs SELECT on that column. The cell `"sessions": {"sweeper": dele}` must gain `sel` on those two columns.

## 5. `jti` replay store and membership sync

(Script and output: `m45_pg.py` above.)

Findings:

- **The jti table as an INSERT-only role:**
  - **Target-less `INSERT … ON CONFLICT DO NOTHING` works, and `cursor.rowcount` is the replay signal** (1 the first time, 0 on a replay), with no SELECT needed.
  - `ON CONFLICT (jti) DO NOTHING` gives 42501, and so does `… RETURNING jti`.
  - A plain INSERT replay gives `UniqueViolation` 23505, which also aborts the transaction.
  - `DELETE … WHERE exp < now()` gives 42501. Pruning needs DELETE plus `SELECT (exp)` for whichever role runs it.
  - An insert that was rolled back does not consume the jti, so the jti insert and the session revoke belong in one transaction.
- **`memberships` with FORCE RLS, `tenant_isolation` (TO api, sweeper, definer) and `sweeper_all` (TO sweeper):**
  - The sweeper sees all 4 rows with no GUC. **`SELECT … FOR UPDATE` works with only the column-level `UPDATE (active, permission_version, synced_at)` grant**: any column's UPDATE privilege is enough for row locks. Updating `role` gives 42501.
  - **As a SECURITY DEFINER function under the AM-20.2 cells it fails with 42501**, because `app_definer` has only SELECT on `memberships` and `FOR UPDATE` and `UPDATE` both need UPDATE.
  - **After granting the definer `UPDATE (active, permission_version, synced_at)` it works, but only by iterating tenants.** Inside the function `current_user` is the definer: the `NOTICE` shows it sees **0 rows** with no tenant set, because `sweeper_all` is `TO sweeper` and never applies inside a definer. `FOR t IN SELECT tenant_id FROM tenants LOOP PERFORM set_config('app.tenant_id', t::text, true); … END LOOP` deactivated alex's 2 memberships (`active=false`, `permission_version` 1→2), and a second call returned 0. The function's `SET app.tenant_id = ''` attribute left the caller's GUC at `''` afterwards.
  - **The SECURITY INVOKER alternative** (run as the sweeper) does the same in one statement through `sweeper_all`: 2 rows. Without `sweeper_all` it sees and updates 0 rows.
  - The plan must pick one. Either keep it a definer (and add an UPDATE cell for `app_definer` in a new revision, plus the tenant loop), or make `sync_memberships` SECURITY INVOKER, which the existing sweeper cells and `sweeper_all` already support. The spec's function table lists it among the definer functions.

## 6. Logging redaction

Script `m6_logging.py`:

```python
"""M6: a redaction logging.Filter; uvicorn's access line for ?code=...; exceptions through log.exception."""
import io
import logging
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import server  # noqa: E402

import httpx2  # noqa: E402

PATTERNS = [
    (re.compile(r"([?&](?:code|state|session_state|id_token_hint|logout_token)=)[^&\s\"']+", re.I), r"\1[REDACTED]"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", re.I), r"\1[REDACTED]"),
    (re.compile(r"(postgres(?:ql)?://[^:/\s]+:)[^@\s]+@", re.I), r"\1[REDACTED]@"),
    (re.compile(r"(password=)\S+", re.I), r"\1[REDACTED]"),
    (re.compile(r"(x-ops-invocation['\"]?\s*[:=]\s*['\"]?)[^'\"\s,}]+", re.I), r"\1[REDACTED]"),
    (re.compile(r"canary-secret-\w+"), "[REDACTED-CANARY]"),
]


def redact(s: str) -> str:
    for p, rep in PATTERNS:
        s = p.sub(rep, s)
    return s


class Redact(logging.Filter):
    def __init__(self, exc_too: bool):
        super().__init__()
        self.exc_too = exc_too

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(str(record.msg))
        if record.args:
            args = record.args if isinstance(record.args, tuple) else (record.args,)
            record.args = tuple(redact(a) if isinstance(a, str) else a for a in args)
        if self.exc_too and record.exc_info:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None      # keep the formatter from re-rendering the raw traceback
        return True


def capture(logger_names, filt, where):
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
    if filt and where == "handler":
        h.addFilter(filt)
    for n in logger_names:
        lg = logging.getLogger(n)
        lg.handlers[:] = [h]
        lg.propagate = False
        lg.setLevel(logging.INFO)
        lg.filters[:] = [filt] if (filt and where == "logger") else []
    return buf


print("-- 1. uvicorn access log, no filter")
srv = server.serve(log_config=None, access_log=True)
buf = capture(["uvicorn.access", "uvicorn.error"], None, None)
httpx2.get("http://127.0.0.1:18000/auth/callback", params={"code": "abc123CODEvalue", "state": "st4te"})
time.sleep(0.2)
line = [l for l in buf.getvalue().splitlines() if "callback" in l][0]
print("line shape:", re.sub(r"code=[^&\s]+", "code=<6 chars shown below>", re.sub(r"state=[^&\s\"]+", "state=<...>", line)))
print("raw code present in the access line:", "abc123CODEvalue" in line)
r = logging.getLogger("uvicorn.access")
print("access record format/args type:", end=" ")


class Peek(logging.Filter):
    def filter(self, rec):
        print(repr(rec.msg), type(rec.args).__name__, len(rec.args))
        return True


r.addFilter(Peek())
httpx2.get("http://127.0.0.1:18000/health")
time.sleep(0.2)
r.filters.clear()

for where in ("logger", "handler"):
    print(f"\n-- 2. Redact filter on the uvicorn.access {where}")
    buf = capture(["uvicorn.access"], Redact(exc_too=False), where)
    httpx2.get("http://127.0.0.1:18000/auth/callback", params={"code": "abc123CODEvalue", "state": "st4te"})
    time.sleep(0.2)
    line = [l for l in buf.getvalue().splitlines() if "callback" in l][0]
    print("line:", line.split(" - ", 1)[1] if " - " in line else line)
    print("raw code present:", "abc123CODEvalue" in line)

print("\n-- 3. log.exception with a canary in the exception message")
for exc_too in (False, True):
    buf = capture(["spike.app"], Redact(exc_too=exc_too), "handler")
    log = logging.getLogger("spike.app")
    try:
        raise RuntimeError("connect failed: postgresql://api:canary-secret-ABC@db/ops and Bearer eyJhbGciOi.canary")
    except RuntimeError:
        log.exception("while calling %s", "postgresql://api:canary-secret-DEF@db/ops")
    out = buf.getvalue()
    print(f"exc_too={exc_too}: canary in message line: {'canary-secret-DEF' in out.splitlines()[0]} | "
          f"canary in traceback text: {'canary-secret-ABC' in out} | Bearer value in traceback: {'eyJhbGciOi' in out}")

print("\n-- 4. uvicorn.error 'Exception in ASGI application' for a route raising with a canary")
for exc_too in (False, True):
    buf = capture(["uvicorn.error"], Redact(exc_too=exc_too), "handler")
    httpx2.get("http://127.0.0.1:18000/boom")
    time.sleep(0.2)
    out = buf.getvalue()
    print(f"exc_too={exc_too}: first line: {out.splitlines()[0] if out else None!r} | canary present: {'canary-secret-XYZ123' in out}")

print("\n-- 5. a filter on a parent LOGGER does not see child records; on the HANDLER it does")
for where in ("logger", "handler"):
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    parent = logging.getLogger("spike_parent")
    parent.handlers[:] = [h]; parent.filters.clear(); parent.propagate = False; parent.setLevel(logging.INFO)
    (parent if where == "logger" else h).addFilter(Redact(exc_too=True))
    logging.getLogger("spike_parent.child").info("GET /auth/callback?code=abc123CODEvalue")
    print(f"filter on parent {where}: raw code present in output: {'abc123CODEvalue' in buf.getvalue()}")

srv.should_exit = True
time.sleep(0.5)
```

Output (complete; the fake `code` value is test data, and the first line masks it anyway):

```text
-- 1. uvicorn access log, no filter
line shape: uvicorn.access INFO 127.0.0.1:50872 - "GET /auth/callback?code=<6 chars shown below>&state=<...> HTTP/1.1" 200
raw code present in the access line: True
access record format/args type: '%s - "%s %s HTTP/%s" %d' tuple 5

-- 2. Redact filter on the uvicorn.access logger
line: "GET /auth/callback?code=[REDACTED]&state=[REDACTED] HTTP/1.1" 200
raw code present: False

-- 2. Redact filter on the uvicorn.access handler
line: "GET /auth/callback?code=[REDACTED]&state=[REDACTED] HTTP/1.1" 200
raw code present: False

-- 3. log.exception with a canary in the exception message
exc_too=False: canary in message line: False | canary in traceback text: True | Bearer value in traceback: True
exc_too=True: canary in message line: False | canary in traceback text: False | Bearer value in traceback: False

-- 4. uvicorn.error 'Exception in ASGI application' for a route raising with a canary
exc_too=False: first line: 'uvicorn.error ERROR Exception in ASGI application' | canary present: True
exc_too=True: first line: 'uvicorn.error ERROR Exception in ASGI application' | canary present: False

-- 5. a filter on a parent LOGGER does not see child records; on the HANDLER it does
filter on parent logger: raw code present in output: True
filter on parent handler: raw code present in output: False
```

Findings:

- **uvicorn's access record** is `msg='%s - "%s %s HTTP/%s" %d'`, and `args` is a 5-tuple `(client, method, full_path, http_version, status)`. **`full_path` includes the query string**, so `/auth/callback?code=…&state=…` is logged verbatim unless something redacts it.
- **A `logging.Filter` that rewrites `record.msg` and string `record.args`** redacts the access line whether it is attached to the `uvicorn.access` logger or to its handler.
- **`log.exception` leaks.** Redacting `msg`/`args` does not touch the traceback, so the exception text (a conninfo with a password, a `Bearer` value) went out unredacted. The filter must also set `record.exc_text = redact(formatException(record.exc_info))` and `record.exc_info = None`. With that, nothing leaked.
- **uvicorn's own `Exception in ASGI application`** record (logger `uvicorn.error`) carries the route's exception, canary included, through `exc_info`. The same `exc_text` rewrite fixed it.
- **Logger filters are not inherited.** A filter on a parent logger did not see a record logged on `spike_parent.child` (raw code present). A filter on the handler did. Install the redaction filter on every handler (root, uvicorn's), not on loggers.

## Cross-cutting gotchas (most consequential first)

1. **`localhost` costs ≈2 s per new connection on this host.** `::1` is tried first, and the container ports are IPv4-only. A refused connection also takes ≈2 s and surfaces as `ConnectTimeout`. With the AM-20.7 2 s timeout, an admin-API check on a cold connection to `localhost` would fail closed for no reason, and a down identity provider through `localhost` took 4 s, not 2. Call the identity provider at `127.0.0.1` from the API and sweeper (the `iss` stays `localhost` through `KC_HOSTNAME`), keep one keep-alive client, and wrap the call in an overall deadline (`asyncio.wait_for`).
2. **The AM-20.2 cells and the 0002 `sessions` shape do not carry T11 as written:**
   - `app_definer` has only SELECT on `memberships`, so a definer `sync_memberships` fails with 42501. As a definer it also sees 0 rows unless it loops over tenants, because `sweeper_all` does not apply inside it.
   - The sweeper's DELETE-only cell on `sessions` cannot filter by `expires_at` or `revoked_at`.
   - `sessions` has no `sid` column and no place for pre-login `state`/`nonce`/`code_verifier`.
   - A `logout_jti` table needs INSERT for the API and DELETE plus `SELECT (exp)` for whoever prunes it.

   T11 needs a new revision and new matrix cells.
3. **authlib's id_token checks are weaker than they look.** `nonce=None` silently skips the nonce check. `aud` is never compared with the client id (only `azp`) unless `claims_options` names it. A hand `CodeIDToken` with no `iss` option accepts any issuer. The `iss` authorization-response parameter is not checked. The Starlette integration requires SessionMiddleware (not locked, and forbidden by AM-20.7 item 10). Use `OAuth2Client` with explicit `claims_options` for `iss` and `aud`, and refuse a missing nonce yourself.
4. **The realm's login cookies are `Secure; SameSite=None` on http.** Python cookie jars (httpx2 and TestClient alike) store them and never send them back on `http://`, so a scripted login must forward the `Cookie` header by hand, and TestClient tests of the API's own `Secure` cookie need `base_url="https://testserver"`.
5. **Back-channel logout is fire-once.** It is sent synchronously and once, with no retry: a 500 still ends the IdP session. It is also sent to the client that initiated the logout. The API's endpoint must be idempotent, deduplicated by jti, and must tolerate its own `/logout` echoing back. Idle expiry is the backstop. ops-dev also cannot get a back-channel URL without the realm-JSON change in measurement 2: there is no admin, and the view-users account gets 403.
6. **`end_session` with only an `id_token_hint` logs the user out without confirmation**, so keep id_tokens server-side. Introspecting an `ops-web` access token says `active: false` even when the session is live (the token has no `aud`), so it is not a liveness check.
7. A wrong `code_verifier` burns the code, and a reused code kills the session the first exchange created. Consume `state` exactly once, atomically.
8. The jti replay signal for an insert-only role is `rowcount` after a target-less `ON CONFLICT DO NOTHING`; `ON CONFLICT (jti)` and `RETURNING` need SELECT. A logging filter must rewrite `exc_text` (not just `msg`/`args`) and must sit on handlers, not parent loggers.

## Cleanup proof

Script `inventory.py` (run before the spike, between the measurements and the cleanup, and after the cleanup):

```python
"""Inventory of spike_* objects: dev realm (through the only API there is, view-users), the throwaway container,
and PostgreSQL. Prints names and counts only."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import KC, OIDC, REALM, read_secret, su  # noqa: E402

import httpx2  # noqa: E402

tok = httpx2.post(f"{OIDC}/token", data={"grant_type": "client_credentials"},
                  auth=("ops-view-users", read_secret("kc_client_secret_ops_view_users")), timeout=5).json()["access_token"]
h = {"Authorization": f"Bearer {tok}"}
users = httpx2.get(f"{KC}/admin/realms/{REALM}/users", params={"briefRepresentation": "true", "max": 1000}, headers=h, timeout=5).json()
print("[kc ops-dev] users:", sorted(u["username"] for u in users),
      "| enabled:", sorted(u["username"] for u in users if u["enabled"]))
print("[kc ops-dev] users named spike_*:", [u["username"] for u in users if u["username"].startswith("spike")])
for path in ("clients", "roles", "groups", "client-scopes"):
    r = httpx2.get(f"{KC}/admin/realms/{REALM}/{path}", headers=h, timeout=5)
    body = r.json() if r.status_code == 200 else None
    names = [x.get("clientId") or x.get("name") for x in body] if isinstance(body, list) else None
    print(f"[kc ops-dev] GET /{path}: {r.status_code}", "| spike_*:" if names is not None else "",
          [n for n in names if n and n.startswith("spike")] if names is not None else "")
ps = subprocess.run(["docker", "ps", "-a", "--filter", "name=spike", "--format", "{{.Names}}"], capture_output=True, text=True)
print("[docker] containers named spike*:", ps.stdout.split())
with su() as s:
    print("[pg ops] spike schemas:", s.execute("SELECT nspname FROM pg_namespace WHERE nspname LIKE 'spike%' ORDER BY 1").fetchall())
    print("[pg] spike roles:", s.execute("SELECT rolname FROM pg_roles WHERE rolname LIKE 'spike%' ORDER BY 1").fetchall())
    print("[pg ops] app tables:", s.execute("SELECT count(*) FROM pg_tables WHERE schemaname='app'").fetchone()[0],
          "| alembic_version:", s.execute("SELECT version_num FROM public.alembic_version ORDER BY 1").fetchall())
```

Before (run just after `spike_kc.py start`. `docker ps -a --filter name=spike` printed nothing immediately before the start, so `spike_kc` is the only spike object):

```text
[kc ops-dev] users: ['alex', 'jordan', 'lee', 'riley', 'sam'] | enabled: ['alex', 'jordan', 'lee', 'riley', 'sam']
[kc ops-dev] users named spike_*: []
[kc ops-dev] GET /clients: 403  
[kc ops-dev] GET /roles: 403  
[kc ops-dev] GET /groups: 200 | spike_*: []
[kc ops-dev] GET /client-scopes: 403  
[docker] containers named spike*: ['spike_kc']
[pg ops] spike schemas: []
[pg] spike roles: []
[pg ops] app tables: 19 | alembic_version: [('0004_write_path_functions',)]
```

Script `cleanup.py`:

```python
"""Remove every spike_* object (container spike_kc and its realm; schema spike_app; roles spike_*) and prove it."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import su  # noqa: E402

ROLES_Q = "SELECT rolname FROM pg_roles WHERE rolname LIKE 'spike\\_%' ORDER BY 1"
subprocess.run([sys.executable, str(Path(__file__).parent / "spike_kc.py"), "stop"])
print("scratch admin-password file left:", (Path(__file__).parent / ".spike_kc_admin").exists())
with su() as s:
    roles = [r[0] for r in s.execute(ROLES_Q).fetchall()]
    print("spike roles before:", roles)
    print("datacl ops before cleanup:", s.execute("SELECT datacl FROM pg_database WHERE datname='ops'").fetchone()[0])
    for (n,) in s.execute("SELECT nspname FROM pg_namespace WHERE nspname LIKE 'spike\\_%'").fetchall():
        s.execute(f'DROP SCHEMA "{n}" CASCADE'); print(f"dropped schema ops.{n}")
    if roles:
        s.execute("DROP OWNED BY " + ", ".join(f'"{r}"' for r in roles)); print("DROP OWNED BY", roles, "in ops")
with su("incident") as s:
    if roles:
        s.execute("DROP OWNED BY " + ", ".join(f'"{r}"' for r in roles)); print("DROP OWNED BY", roles, "in incident")
with su() as s:
    for r in roles:
        s.execute(f'DROP ROLE "{r}"')
    print("\n== Cleanup proof ==")
    print("pg_roles LIKE 'spike_%':", s.execute(ROLES_Q).fetchall())
    print("datacl ops after cleanup:", s.execute("SELECT datacl FROM pg_database WHERE datname='ops'").fetchone()[0])
    print("pg_shdepend rows for missing roles:", s.execute(
        "SELECT count(*) FROM pg_shdepend WHERE refclassid='pg_authid'::regclass "
        "AND refobjid NOT IN (SELECT oid FROM pg_authid)").fetchone()[0])
```

The first cleanup run removed the container (`docker rm -f spike_kc rc: 0 spike_kc`, scratch admin-password file left: `False`) and the first set of scratch roles. Measurement 4/5 was then re-run once on a clean database so that its first output line shows the untouched `ops` ACL, and the cleanup ran again. Its output (complete, final run; the container was already gone):

```text
docker rm -f spike_kc rc: 0  Error response from daemon: No such container: spike_kc
scratch admin-password file left: False
spike roles before: ['spike_api', 'spike_definer', 'spike_owner', 'spike_sweeper']
datacl ops before cleanup: ['=T/ops', 'ops=CTc/ops', 'api=c/ops', 'worker=c/ops', 'sweeper=c/ops', 'mcp_read=c/ops', 'mcp_exec=c/ops', 'operator=c/ops', 'spike_api=c/ops', 'spike_sweeper=c/ops']
dropped schema ops.spike_app
DROP OWNED BY ['spike_api', 'spike_definer', 'spike_owner', 'spike_sweeper'] in ops
DROP OWNED BY ['spike_api', 'spike_definer', 'spike_owner', 'spike_sweeper'] in incident

== Cleanup proof ==
pg_roles LIKE 'spike_%': []
datacl ops after cleanup: ['=T/ops', 'ops=CTc/ops', 'api=c/ops', 'worker=c/ops', 'sweeper=c/ops', 'mcp_read=c/ops', 'mcp_exec=c/ops', 'operator=c/ops']
pg_shdepend rows for missing roles: 0
```

After:

```text
[kc ops-dev] users: ['alex', 'jordan', 'lee', 'riley', 'sam'] | enabled: ['alex', 'jordan', 'lee', 'riley', 'sam']
[kc ops-dev] users named spike_*: []
[kc ops-dev] GET /clients: 403  
[kc ops-dev] GET /roles: 403  
[kc ops-dev] GET /groups: 200 | spike_*: []
[kc ops-dev] GET /client-scopes: 403  
[docker] containers named spike*: []
[pg ops] spike schemas: []
[pg] spike roles: []
[pg ops] app tables: 19 | alembic_version: [('0004_write_path_functions',)]
```

The `ops` ACL after cleanup is identical to the one `m45_pg.py` printed before its setup. `docker volume ls -f dangling=true` lists two volumes dated 2026-08-09, which predate this spike; the identity-provider image declares no volumes. `git status --short` in `<repo>` printed nothing for the repository's own files. The only entry was `?? docs/superpowers/research/2026-10-08-plan-f-inputs.md`, which this spike did not create (it appeared during the run) and did not touch, alongside this report.


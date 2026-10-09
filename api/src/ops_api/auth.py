"""Browser login mechanics for the API (T11): the OIDC client, the ID-token and logout-token verifiers, the sealed
refresh token, the cookies and the origin rule.

authlib does the authorization-code flow with PKCE (`AsyncOAuth2Client`, httpx2 backend): the authorization URL
and the code exchange. It does not do the token checks, because its defaults are weaker than BUILD_SPEC §9 asks
(a wrong `aud` passes when `azp` matches, a missing nonce passes, 120 s of leeway; spike §1): the ID token and the
back-channel logout token go through `ops_core.tokens.TokenVerifier`, which pins RS256, requires `aud` and uses
zero leeway, configured per token type (ruling 26). State, nonce and the login cookie are compared as SHA-256 hashes
with `hmac.compare_digest`; the raw values exist only in the browser and in the one request that spends them.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit
from uuid import UUID

import httpx2
from authlib.integrations.httpx_client import AsyncOAuth2Client, OAuthError
from cryptography.fernet import Fernet, InvalidToken
from ops_core import settings
from ops_core.canonical import sha256_hex
from ops_core.tokens import TokenRejected, TokenVerifier
from starlette.responses import Response

SESSION_COOKIE = "ops_session"
CSRF_COOKIE = "ops_csrf"
LOGIN_COOKIE = "ops_login"
CSRF_HEADER = "X-CSRF-Token"
BACKCHANNEL_EVENT = "http://schemas.openid.net/event/backchannel-logout"
CLIENT_ID = "ops-web"


def digest(value: str) -> str:
    """The stored form of every opaque token (BUILD_SPEC §6: session IDs stored hashed)."""
    return sha256_hex(value.encode("utf-8"))


def new_token() -> str:
    """256 random bits, URL-safe: a session ID, a CSRF token, a login binding, a state, a nonce or a PKCE verifier
    (43 characters, inside RFC 7636's 43-128 and its alphabet)."""
    return secrets.token_urlsafe(32)


def matches(value: str, expected_sha256: str) -> bool:
    """Constant-time comparison of a presented token with its stored hash."""
    return hmac.compare_digest(digest(value), expected_sha256)


def origin_of(url: str) -> str | None:
    """`scheme://host[:port]` of an absolute http(s) URL, else None."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}"


def same_host(host_header: str, public_base_url: str) -> bool:
    """Whether a request's Host names the public base (case-insensitive host, default ports equal an omitted one),
    so an explicit `:80`/`:443` in the base never loops `/auth/login` on itself."""
    public = urlsplit(public_base_url)
    default = 443 if public.scheme == "https" else 80
    if "@" in host_header or "/" in host_header:
        return False
    try:
        sent = urlsplit(f"//{host_header.strip()}")
        sent_port = sent.port or default
    except ValueError:
        return False
    return bool(sent.hostname) and sent.hostname == public.hostname and sent_port == (public.port or default)


def same_origin(headers: Mapping[str, str], origin: str) -> bool:
    """BUILD_SPEC §9 origin verification: `Origin` must equal ours exactly; when a browser omits it, the `Referer`'s
    origin stands in; `null`, another origin or nothing at all is a refusal."""
    sent = headers.get("origin")
    if sent is None:
        referer = headers.get("referer")
        sent = origin_of(referer) if referer else None
    return sent is not None and sent.strip() == origin


@dataclass(frozen=True)
class Discovery:
    """The realm's OIDC metadata after ruling 25's checks: the authorization endpoint keeps the public host the
    browser is sent to; the endpoints this process dials are rewritten to `server_url`."""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    end_session_endpoint: str
    jwks_uri: str

    @classmethod
    def from_document(cls, doc: Mapping[str, Any], keycloak: settings.Keycloak) -> Discovery:
        """Check the realm's metadata and build the endpoints; ValueError refuses the process start."""
        if doc.get("issuer") != keycloak.issuer:
            raise ValueError("discovery issuer differs from OPS_KC_ISSUER")
        if not (
            doc.get("backchannel_logout_supported") is True and doc.get("backchannel_logout_session_supported") is True
        ):
            raise ValueError("the realm does not support session-scoped back-channel logout")
        methods = doc.get("code_challenge_methods_supported")
        if not (isinstance(methods, list) and "S256" in methods):
            raise ValueError("the realm does not support PKCE S256")
        # Keycloak spells the back-channel endpoints with the host the document was fetched from (`server_url`) and the
        # browser-facing ones with the public host (`KC_HOSTNAME`); the browser's endpoint must be the public one.
        for name in ("authorization_endpoint", "token_endpoint", "end_session_endpoint", "jwks_uri"):
            hosts = (
                (keycloak.base_url,) if name == "authorization_endpoint" else (keycloak.base_url, keycloak.server_url)
            )
            allowed = tuple(host + "/" for host in hosts)
            if name in doc and not str(doc[name]).startswith(allowed):
                raise ValueError("discovery endpoint outside the configured base URL")
        try:
            return cls(
                issuer=keycloak.issuer,
                authorization_endpoint=str(doc["authorization_endpoint"]),
                token_endpoint=keycloak.server_side(str(doc["token_endpoint"])),
                end_session_endpoint=keycloak.server_side(str(doc["end_session_endpoint"])),
                jwks_uri=keycloak.server_side(str(doc["jwks_uri"])),
            )
        except KeyError as exc:
            raise ValueError(f"discovery document lacks {exc.args[0]}") from exc


async def fetch_discovery(keycloak: settings.Keycloak, client: httpx2.AsyncClient) -> Discovery:
    """Fetch and check the realm's metadata (startup; a failure refuses to start)."""
    response = await client.get(keycloak.discovery_url)
    response.raise_for_status()
    return Discovery.from_document(response.json(), keycloak)


@dataclass(frozen=True)
class Tokens:
    """What the exchange yields that the API keeps: the ID token for its claims, the refresh token for logout.
    The access token is dropped on purpose: nothing here acts at the provider on the user's behalf."""

    id_token: str = field(repr=False)
    refresh_token: str = field(repr=False)


class ExchangeRefused(Exception):
    """The provider refused the code (wrong verifier, reused code, unknown code): a 401 for the browser."""


class ExchangeUnavailable(Exception):
    """The token endpoint could not be reached or answered garbage: a 503 for the browser."""


class OidcClient(Protocol):
    """What the routes need from the provider client; the unit tests fake it."""

    def authorization_url(self, *, state: str, nonce: str, code_verifier: str) -> str:
        """The URL the browser is sent to."""
        ...

    async def exchange(self, *, code: str, code_verifier: str) -> Tokens:
        """Trade the code for tokens or raise ExchangeRefused / ExchangeUnavailable."""
        ...

    async def end_session(self, refresh_token: str) -> None:
        """End the provider session server-side (RP logout); raise ExchangeUnavailable on failure."""
        ...


class AuthlibOidc:
    """The production client: authlib for the flow, one plain httpx2 client for the end-session call."""

    def __init__(
        self, *, discovery: Discovery, client_secret: str, redirect_uri: str, http: httpx2.AsyncClient
    ) -> None:
        self._discovery = discovery
        self._secret = client_secret
        self._redirect_uri = redirect_uri
        self._http = http
        self._client = AsyncOAuth2Client(
            client_id=CLIENT_ID,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope="openid",
            code_challenge_method="S256",
            timeout=10.0,
        )

    def authorization_url(self, *, state: str, nonce: str, code_verifier: str) -> str:
        """The URL the browser is sent to (S256 challenge computed by authlib from the verifier)."""
        url, _ = self._client.create_authorization_url(
            self._discovery.authorization_endpoint, state=state, nonce=nonce, code_verifier=code_verifier
        )
        return str(url)

    async def exchange(self, *, code: str, code_verifier: str) -> Tokens:
        """Trade the code for tokens; the shared client keeps none of them afterwards."""
        try:
            token = await self._client.fetch_token(
                self._discovery.token_endpoint,
                grant_type="authorization_code",
                code=code,
                code_verifier=code_verifier,
                redirect_uri=self._redirect_uri,
            )
        except OAuthError as exc:
            # `error` is the OAuth error code (invalid_grant); the description could echo request values: left out.
            raise ExchangeRefused(str(exc.error or "exchange refused")) from exc
        except (httpx2.HTTPError, OSError, ValueError) as exc:
            raise ExchangeUnavailable(f"token endpoint unreachable: {exc.__class__.__name__}") from exc
        finally:
            # authlib keeps the last token response on the client (shared by every login); nothing here acts at the
            # provider on the user's behalf, so it is dropped at once (round-1 finding M14).
            self._client.token = None
        id_token, refresh = token.get("id_token"), token.get("refresh_token")
        if not isinstance(id_token, str) or not id_token or not isinstance(refresh, str) or not refresh:
            raise ExchangeRefused("token reply lacks id_token or refresh_token")
        return Tokens(id_token=id_token, refresh_token=refresh)

    async def aclose(self) -> None:
        """Close authlib's own connection pool (process shutdown)."""
        await self._client.aclose()

    async def end_session(self, refresh_token: str) -> None:
        """End the provider session with the refresh token (RP logout, server side)."""
        # The form the spike measured (§2): client credentials as basic auth, the refresh token in the body, 204.
        try:
            response = await self._http.post(
                self._discovery.end_session_endpoint,
                auth=(CLIENT_ID, self._secret),
                data={"refresh_token": refresh_token},
            )
        except (httpx2.HTTPError, OSError) as exc:
            raise ExchangeUnavailable(f"end-session endpoint unreachable: {exc.__class__.__name__}") from exc
        if response.status_code >= 400:
            raise ExchangeUnavailable(f"end-session endpoint answered {response.status_code}")


@dataclass(frozen=True)
class IdClaims:
    """What the API keeps from a verified ID token."""

    subject: UUID
    sid: str
    username: str


class IdTokens(Protocol):
    """What the callback needs from the ID-token verifier; the unit tests fake it."""

    @property
    def ready(self) -> bool:
        """Whether the signing keys are loaded."""
        ...

    async def load_keys(self) -> None:
        """Fetch the signing keys."""
        ...

    async def verify(self, id_token: str, *, nonce_sha256: str) -> IdClaims:
        """Verify the token against the stored nonce hash or raise TokenRejected."""
        ...


class IdTokenVerifier:
    """BUILD_SPEC §9's checks on the ID token: signature, RS256 only, iss, aud = ops-web, azp = ops-web, exp with
    zero leeway, iat, nonce (hash-compared), sid present, claim typ ID, sub a UUID."""

    def __init__(self, *, issuer: str, jwks_url: str) -> None:
        self.verifier = TokenVerifier(
            issuer=issuer,
            audience=CLIENT_ID,
            allowed_azp=frozenset({CLIENT_ID}),
            jwks_url=jwks_url,
            required_claims=("exp", "iss", "aud", "sub", "iat", "nonce", "sid"),
        )

    @property
    def ready(self) -> bool:
        """Whether the signing keys are loaded."""
        return self.verifier.ready

    async def load_keys(self) -> None:
        """Fetch the signing keys."""
        await self.verifier.load_keys()

    async def verify(self, id_token: str, *, nonce_sha256: str) -> IdClaims:
        """The claims the API keeps, or TokenRejected."""
        principal = await self.verifier.verify_async(id_token)
        claims = principal.claims
        nonce, sid = claims.get("nonce"), claims.get("sid")
        username = claims.get("preferred_username", "")
        if not isinstance(username, str):
            raise TokenRejected("id token username is not a string")
        if not isinstance(nonce, str) or not matches(nonce, nonce_sha256):
            raise TokenRejected("id token nonce does not match this login")
        if claims.get("typ") != "ID":
            raise TokenRejected("not an ID token")
        if not isinstance(sid, str) or not sid:
            raise TokenRejected("id token has no session id")
        try:
            subject = UUID(principal.subject)
        except ValueError as exc:
            raise TokenRejected("id token subject is not an identity") from exc
        return IdClaims(subject=subject, sid=sid, username=username)


@dataclass(frozen=True)
class LogoutClaims:
    """What the back-channel endpoint acts on from a verified logout token."""

    sid: str
    subject: UUID
    jti: str
    expires_at: int


class LogoutTokens(Protocol):
    """What the back-channel endpoint needs from the logout-token verifier; the unit tests fake it."""

    @property
    def ready(self) -> bool:
        """Whether the signing keys are loaded."""
        ...

    async def load_keys(self) -> None:
        """Fetch the signing keys."""
        ...

    async def verify(self, token: str) -> LogoutClaims:
        """Verify a logout token or raise TokenRejected."""
        ...


class LogoutTokenVerifier:
    """SA:541 plus T11 review note 3: iss, aud, iat, jti, events, exp, no nonce, sid and sub, header typ
    logout+jwt, RS256 only; the jti replay check is the store's."""

    def __init__(self, *, issuer: str, jwks_url: str) -> None:
        self.verifier = TokenVerifier(
            issuer=issuer,
            audience=CLIENT_ID,
            allowed_azp=frozenset(),
            jwks_url=jwks_url,
            required_claims=("exp", "iss", "aud", "iat", "jti", "events", "sid", "sub"),
            require_azp=False,
            typ="logout+jwt",
        )

    @property
    def ready(self) -> bool:
        """Whether the signing keys are loaded."""
        return self.verifier.ready

    async def load_keys(self) -> None:
        """Fetch the signing keys."""
        await self.verifier.load_keys()

    async def verify(self, token: str) -> LogoutClaims:
        """The claims the endpoint acts on, or TokenRejected."""
        principal = await self.verifier.verify_async(token)
        claims = principal.claims
        if "nonce" in claims:
            raise TokenRejected("logout token carries a nonce")
        events = claims.get("events")
        if not isinstance(events, dict) or BACKCHANNEL_EVENT not in events:
            raise TokenRejected("not a back-channel logout event")
        jti, sid = claims.get("jti"), claims.get("sid")
        if not isinstance(jti, str) or not jti or not isinstance(sid, str) or not sid:
            raise TokenRejected("logout token lacks jti or sid")
        try:
            subject = UUID(principal.subject)
        except ValueError as exc:
            raise TokenRejected("logout token subject is not an identity") from exc
        return LogoutClaims(sid=sid, subject=subject, jti=jti, expires_at=principal.expires_at)


class EnabledCheck(Protocol):
    """The admin-API question the decision route asks (ops_core.keycloak_admin.AdminUsers in production)."""

    async def enabled(self, subject: UUID) -> bool:
        """True only when the provider says the user exists and is enabled; raises AdminUnavailable."""
        ...


class TokenBox:
    """Seals the provider refresh token at rest (BUILD_SPEC §9) with a key derived from the `api_session_key`
    secret: Fernet (AES-128-CBC + HMAC-SHA256) from `cryptography`, which `pyjwt[crypto]` already locks."""

    def __init__(self, key_material: str) -> None:
        self._fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(key_material.encode("utf-8")).digest()))

    def seal(self, value: str) -> bytes:
        """Encrypt a provider token for storage."""
        return self._fernet.encrypt(value.encode("utf-8"))

    def open(self, sealed: bytes) -> str:
        """Decrypt a stored token; ValueError when it was not sealed by this key."""
        try:
            return self._fernet.decrypt(sealed).decode("utf-8")
        except (InvalidToken, TypeError) as exc:
            raise ValueError("sealed value is not ours") from exc


@dataclass(frozen=True)
class CookiePolicy:
    """Ruling 6: HttpOnly session cookie, readable CSRF cookie, short login binding; Lax so the callback (a top-level
    navigation back from Keycloak) carries them; Secure iff the public base URL is https."""

    secure: bool
    login_max_age: int

    def set_session(self, response: Response, session: str, csrf: str) -> None:
        """Set the HttpOnly session cookie and the readable CSRF cookie."""
        response.set_cookie(SESSION_COOKIE, session, httponly=True, secure=self.secure, samesite="lax", path="/")
        response.set_cookie(CSRF_COOKIE, csrf, httponly=False, secure=self.secure, samesite="lax", path="/")

    def set_login(self, response: Response, login: str) -> None:
        """Set the short-lived login binding."""
        response.set_cookie(
            LOGIN_COOKIE, login, max_age=self.login_max_age, httponly=True, secure=self.secure, samesite="lax", path="/"
        )

    def clear_session(self, response: Response) -> None:
        """Expire the session and CSRF cookies."""
        response.delete_cookie(SESSION_COOKIE, path="/", secure=self.secure, httponly=True, samesite="lax")
        response.delete_cookie(CSRF_COOKIE, path="/", secure=self.secure, httponly=False, samesite="lax")

    def clear_login(self, response: Response) -> None:
        """Expire the login binding."""
        response.delete_cookie(LOGIN_COOKIE, path="/", secure=self.secure, httponly=True, samesite="lax")


Closer = Callable[[], Awaitable[None]]


@dataclass
class AuthDeps:
    """Everything the auth routes and dependencies need, built once in the lifespan (production) or faked (tests)."""

    oidc: OidcClient
    id_tokens: IdTokens
    logout_tokens: LogoutTokens
    admin: EnabledCheck
    box: TokenBox
    sessions: settings.SessionSettings
    cookies: CookiePolicy
    closers: tuple[Closer, ...] = field(default_factory=tuple)

    async def aclose(self) -> None:
        """Close every client the deps own (process shutdown)."""
        for close in self.closers:
            await close()

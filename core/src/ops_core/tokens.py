"""Bearer-token verification shared by every resource server (api, mcp-read, mcp-write, incident-sim).

One class, configured per server with its issuer, its own audience and the workload clients it accepts as `azp`, so
every server applies SA:557's checks the same way and a token minted for one audience is refused by every other
(SA:558). Keys come from the realm's JWKS, fetched asynchronously at startup (SA:201: no synchronous I/O on the event
loop) and refreshed at most once per verification on an unknown `kid` (key rotation). PyJWT checks the signature,
`exp`, `iss` and `aud`; `azp` is checked here because PyJWT has no option for it. Algorithms are pinned to RS256 so a
token signed with the public key as an HMAC secret is refused.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

import httpx2
import jwt
from jwt import PyJWKSet
from jwt.exceptions import InvalidTokenError, PyJWKClientError, PyJWKSetError

Fetch = Callable[[str], Awaitable[dict[str, Any]]]
REFRESH_COOLDOWN = 60.0  # seconds between JWKS refreshes triggered by an unknown kid


class TokenRejected(Exception):
    """The token is not acceptable here. The message says why in general terms and never contains the token."""


class UnknownSigningKey(TokenRejected):
    """The token names a `kid` this server has no key for; the only rejection a JWKS refresh can cure."""


@dataclass(frozen=True)
class Principal:
    subject: str
    azp: str
    audiences: tuple[str, ...]
    expires_at: int
    # repr=False: a logged Principal must not dump every claim; verify() hands out a read-only view of them.
    claims: Mapping[str, Any] = field(repr=False)


def bearer_token(authorization: str | None) -> str:
    """Extract the token from an `Authorization: Bearer <token>` header (case-sensitive scheme, one token)."""
    if not authorization:
        raise TokenRejected("missing bearer token")
    scheme, sep, token = authorization.partition(" ")
    # Exactly "Bearer", one space, then a token with no whitespace at all: nothing lenient reaches the decoder.
    if scheme != "Bearer" or sep != " " or not token or any(c.isspace() for c in token):
        raise TokenRejected("malformed authorization header")
    return token


async def fetch_jwks(url: str) -> dict[str, Any]:
    async with httpx2.AsyncClient(timeout=10.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data


class TokenVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        allowed_azp: frozenset[str],
        jwks_url: str,
        algorithms: tuple[str, ...] = ("RS256",),
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._allowed_azp = allowed_azp
        self._jwks_url = jwks_url
        self._algorithms = list(algorithms)
        self._keys: PyJWKSet | None = None
        self._refreshed_at = 0.0
        self._refresh_lock = asyncio.Lock()  # single-flight: concurrent unknown-kid requests share one fetch
        self.fetch: Fetch = fetch_jwks  # replaceable so tests never open a socket

    @property
    def ready(self) -> bool:
        return self._keys is not None

    def install_keys(self, jwks: dict[str, Any]) -> None:
        entries = jwks.get("keys") if isinstance(jwks, dict) else None
        if not isinstance(entries, list):
            raise TokenRejected("JWKS document is unusable")
        # Only signing keys for the pinned algorithms: an encryption key must never be able to verify a signature.
        usable = [
            entry
            for entry in entries
            if isinstance(entry, dict)
            and entry.get("use", "sig") == "sig"
            and entry.get("alg", self._algorithms[0]) in self._algorithms
        ]
        try:
            self._keys = PyJWKSet.from_dict({"keys": usable})
        except PyJWKSetError as exc:
            raise TokenRejected("JWKS document is unusable") from exc

    async def load_keys(self, fetch: Fetch | None = None) -> None:
        # Stamped before the fetch so a failed attempt also starts the cooldown: an unhealthy IdP is not hammered.
        self._refreshed_at = time.time()
        try:
            document = await (fetch or self.fetch)(self._jwks_url)
        except (OSError, httpx2.HTTPError, ValueError) as exc:
            raise TokenRejected("signing keys unavailable") from exc
        self.install_keys(document)

    def verify(self, token: str) -> Principal:
        if self._keys is None:
            raise TokenRejected("signing keys are not loaded")
        try:
            kid = jwt.get_unverified_header(token).get("kid")
            key = self._keys[kid] if isinstance(kid, str) else None
        except (InvalidTokenError, KeyError, PyJWKClientError, PyJWKSetError):
            key = None
        if key is None:
            raise UnknownSigningKey("unknown signing key")
        try:
            claims = jwt.decode(
                token,
                key.key,
                algorithms=self._algorithms,
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except InvalidTokenError as exc:
            # PyJWT's message names the failed check (expired, audience, issuer, signature) and never the token.
            raise TokenRejected(f"token rejected: {exc.__class__.__name__}") from exc
        if not isinstance(claims["sub"], str) or not claims["sub"]:
            raise TokenRejected("token has no subject")
        azp = claims.get("azp")
        if not isinstance(azp, str) or azp not in self._allowed_azp:
            raise TokenRejected("token was issued to a client this server does not accept")
        aud = claims["aud"]
        audiences = (aud,) if isinstance(aud, str) else tuple(aud)
        return Principal(
            subject=claims["sub"],
            azp=azp,
            audiences=audiences,
            expires_at=int(claims["exp"]),
            claims=MappingProxyType(claims),
        )

    async def verify_async(self, token: str) -> Principal:
        """`verify`, refreshing the JWKS once when the kid is unknown (rotation), then giving up."""
        try:
            return self.verify(token)
        except UnknownSigningKey:
            pass
        async with self._refresh_lock:
            # Re-checked inside the lock: a request that waited finds the keys the first one fetched, or the cooldown
            # it started, so a flood of unknown kids costs at most one JWKS fetch per cooldown.
            if time.time() - self._refreshed_at >= REFRESH_COOLDOWN:
                await self.load_keys()
            return self.verify(token)


Post = Callable[[str, dict[str, str]], Awaitable[dict[str, Any]]]


async def post_form(url: str, form: dict[str, str]) -> dict[str, Any]:
    async with httpx2.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, data=form)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data


class WorkloadTokenSource:
    """Client-credentials tokens for a workload (the worker, mcp-write), cached and refreshed 30 s before expiry.

    The secret is held in memory only; it is sent as a form field to the realm's token endpoint and nowhere else.
    """

    def __init__(self, *, token_url: str, client_id: str, client_secret: str, post: Post | None = None) -> None:
        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._post = post or post_form
        self._token: str | None = None
        self.expires_at = 0.0
        self._lock = asyncio.Lock()  # concurrent first callers share one token request

    async def token(self) -> str:
        async with self._lock:
            if self._token is None or time.time() >= self.expires_at - 30:
                data = await self._post(
                    self._token_url,
                    {
                        "grant_type": "client_credentials",
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                    },
                )
                access = data.get("access_token") if isinstance(data, dict) else None
                if not isinstance(access, str) or not access:
                    raise TokenRejected("token endpoint reply is unusable")
                self._token = access
                self.expires_at = time.time() + float(data.get("expires_in", 60))
            return self._token

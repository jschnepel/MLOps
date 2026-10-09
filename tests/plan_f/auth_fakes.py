"""In-memory stand-ins for the T11 collaborators, shared by tests/plan_f/test_api_auth.py and the Plan D API tests.
They model behaviour, not Keycloak: the fake OIDC client hands out whatever tokens a test registered under a code,
the fake verifiers map a token string to its claims and compare the nonce hash the way the real one does."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import UUID

from fastapi.testclient import TestClient
from ops_api import auth
from ops_api.auth import (
    AuthDeps,
    CookiePolicy,
    ExchangeRefused,
    ExchangeUnavailable,
    IdClaims,
    LogoutClaims,
    TokenBox,
    Tokens,
)
from ops_core import settings
from ops_core.keycloak_admin import AdminUnavailable
from ops_core.tokens import TokenRejected

ISSUER = "http://localhost:18080/realms/ops-dev"
ORIGIN = "http://localhost:8000"


@dataclass
class FakeOidc:
    codes: dict[str, Tokens] = field(default_factory=dict)
    started: list[dict[str, str]] = field(default_factory=list)  # state, nonce, code_verifier per login
    ended: list[str] = field(default_factory=list)
    unavailable: bool = False

    def authorization_url(self, *, state: str, nonce: str, code_verifier: str) -> str:
        self.started.append({"state": state, "nonce": nonce, "code_verifier": code_verifier})
        return "https://idp.test/auth?" + urlencode({"state": state, "code_challenge_method": "S256"})

    async def exchange(self, *, code: str, code_verifier: str) -> Tokens:
        if self.unavailable:
            raise ExchangeUnavailable("down")
        if code not in self.codes or code_verifier != self.started[-1]["code_verifier"]:
            raise ExchangeRefused("invalid_grant")
        return self.codes.pop(code)  # a code is spent once

    async def end_session(self, refresh_token: str) -> None:
        if self.unavailable:
            raise ExchangeUnavailable("down")
        self.ended.append(refresh_token)


@dataclass
class FakeIdTokens:
    tokens: dict[str, tuple[IdClaims, str]] = field(default_factory=dict)  # id_token -> (claims, raw nonce)

    @property
    def ready(self) -> bool:
        return True

    async def load_keys(self) -> None:
        return None

    async def verify(self, id_token: str, *, nonce_sha256: str) -> IdClaims:
        if id_token not in self.tokens:
            raise TokenRejected("unknown id token")
        claims, nonce = self.tokens[id_token]
        if not auth.matches(nonce, nonce_sha256):
            raise TokenRejected("nonce")
        return claims


@dataclass
class FakeLogoutTokens:
    tokens: dict[str, LogoutClaims] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return True

    async def load_keys(self) -> None:
        return None

    async def verify(self, token: str) -> LogoutClaims:
        if token not in self.tokens:
            raise TokenRejected("forged")
        return self.tokens[token]


@dataclass
class FakeAdmin:
    disabled: set[UUID] = field(default_factory=set)
    unavailable: bool = False
    calls: int = 0

    async def enabled(self, subject: UUID) -> bool:
        self.calls += 1
        if self.unavailable:
            raise AdminUnavailable("down")
        return subject not in self.disabled


def fake_auth(**over: object) -> AuthDeps:
    """An AuthDeps for TestClient: plain-http cookies, the dev origin, BUILD_SPEC §9 lifetimes."""
    sessions = settings.SessionSettings(ORIGIN, idle_seconds=1800, absolute_seconds=28800, login_seconds=600)
    deps = AuthDeps(
        oidc=FakeOidc(),
        id_tokens=FakeIdTokens(),
        logout_tokens=FakeLogoutTokens(),
        admin=FakeAdmin(),
        box=TokenBox("unit-test-key"),
        sessions=sessions,
        cookies=CookiePolicy(secure=False, login_max_age=600),
    )
    for name, value in over.items():
        setattr(deps, name, value)
    return deps


def login_as(client: TestClient, deps: AuthDeps, subject: UUID, *, sid: str = "sid-1", username: str = "alex") -> str:
    """Drive /auth/login and /auth/callback through the fakes; return the CSRF token the browser would echo."""
    oidc, ids = deps.oidc, deps.id_tokens
    assert isinstance(oidc, FakeOidc) and isinstance(ids, FakeIdTokens)
    started = client.get("/auth/login", follow_redirects=False)
    assert started.status_code == 303, started.text
    state = parse_qs(urlsplit(started.headers["location"]).query)["state"][0]
    code = f"code-{len(oidc.started)}"
    oidc.codes[code] = Tokens(id_token=f"id-{code}", refresh_token=f"refresh-{code}")
    ids.tokens[f"id-{code}"] = (IdClaims(subject=subject, sid=sid, username=username), oidc.started[-1]["nonce"])
    done = client.get("/auth/callback", params={"code": code, "state": state, "iss": ISSUER}, follow_redirects=False)
    assert done.status_code == 303, done.text
    csrf = client.cookies.get("ops_csrf")
    assert csrf
    return csrf

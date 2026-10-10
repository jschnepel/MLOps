"""The two verifiers built on TokenVerifier (rulings 1 and 16) against tokens signed with a throw-away realm key:
every R011 negative for the ID token (issuer, audience, nonce, expiry, signature, algorithm, typ, sid) and every
SA:541 check for the logout token (iss, aud, iat, jti, events, no nonce, sid/sub, header typ, alg), as Keycloak 26.8
shapes them (spike §1 and §2).

Catches: the authlib defaults the spike measured (a wrong `aud` accepted, a missing nonce accepted, 120 s leeway),
an HS256 token signed with the public key, a logout token that carries a nonce, and a replayable token (the jti is
the caller's to record; here the claim must simply be present).
"""

import time
from typing import Any
from uuid import UUID

import jwt
import pytest
from ops_api.auth import BACKCHANNEL_EVENT, IdTokenVerifier, LogoutTokenVerifier, digest
from ops_core.tokens import TokenRejected

from tests.plan_d.test_tokens import ISSUER, JWK1, PEM1, PEM2

ALEX = "2fc05986-c7ec-544c-b628-fdb112bbf18a"
NONCE = "n-123"
MAX_AGE = 1800  # the idle limit (BUILD_SPEC §9)
HS_KEY = "k" * 32  # a full-length HMAC key: the test proves the algorithm pin, not a weak key


def id_token(pem: bytes = PEM1, kid: str = "k1", headers: dict[str, Any] | None = None, **over: Any) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "sub": ALEX,
        "aud": "ops-web",
        "azp": "ops-web",
        "exp": now + 300,
        "iat": now,
        "auth_time": now,
        "nonce": NONCE,
        "sid": "sid-1",
        "typ": "ID",
        "preferred_username": "alex",
    }
    claims.update(over)
    for key in [k for k, v in over.items() if v is None]:
        del claims[key]
    return jwt.encode(claims, pem, algorithm="RS256", headers={"kid": kid, **(headers or {})})


def logout_token(pem: bytes = PEM1, kid: str = "k1", headers: dict[str, Any] | None = None, **over: Any) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "sub": ALEX,
        "aud": "ops-web",
        "exp": now + 120,
        "iat": now,
        "jti": "j-1",
        "sid": "sid-1",
        "typ": "Logout",
        "events": {BACKCHANNEL_EVENT: {}},
    }
    claims.update(over)
    for key in [k for k, v in over.items() if v is None]:
        del claims[key]
    return jwt.encode(claims, pem, algorithm="RS256", headers={"kid": kid, "typ": "logout+jwt", **(headers or {})})


@pytest.fixture
def ids() -> IdTokenVerifier:
    v = IdTokenVerifier(issuer=ISSUER, jwks_url="unused", max_age=MAX_AGE)
    v.verifier.install_keys({"keys": [JWK1]})
    return v


@pytest.fixture
def logouts() -> LogoutTokenVerifier:
    v = LogoutTokenVerifier(issuer=ISSUER, jwks_url="unused")
    v.verifier.install_keys({"keys": [JWK1]})
    return v


@pytest.mark.asyncio
async def test_id_token_accepted_with_the_right_nonce(ids: IdTokenVerifier) -> None:
    claims = await ids.verify(id_token(), nonce_sha256=digest(NONCE))
    assert claims.subject == UUID(ALEX) and claims.sid == "sid-1" and claims.username == "alex"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "token",
    [
        id_token(iss="http://evil/realms/ops-dev"),
        id_token(aud="other"),  # authlib's default would accept this when azp matches (spike §1)
        id_token(aud=["other", "account"], azp="ops-web"),
        id_token(azp="ops-dev-direct"),
        id_token(nonce="other"),
        id_token(nonce=None),  # authlib accepts a missing nonce; this verifier requires it
        id_token(exp=int(time.time()) - 60),  # within authlib's 120 s leeway; refused here (zero leeway)
        id_token(iat=int(time.time()) + 600),
        id_token(sid=None),
        id_token(sid=""),
        id_token(typ="Bearer"),
        id_token(sub="not-a-uuid"),
        id_token(preferred_username=123),
        id_token(pem=PEM2, kid="k1"),  # signed by another key under the known kid
        id_token(pem=PEM2, kid="k2"),  # unknown kid (no refresh in the unit test)
        jwt.encode(
            {"iss": ISSUER, "sub": ALEX, "aud": "ops-web", "exp": int(time.time()) + 60, "nonce": NONCE},
            HS_KEY,
            algorithm="HS256",
            headers={"kid": "k1"},
        ),
    ],
)
async def test_id_token_negatives(ids: IdTokenVerifier, token: str) -> None:
    with pytest.raises(TokenRejected):
        await ids.verify(token, nonce_sha256=digest(NONCE))


@pytest.mark.asyncio
async def test_id_token_auth_time_is_bounded_by_the_idle_limit(ids: IdTokenVerifier) -> None:
    """Final review I1: a token minted from an SSO authentication older than max_age is refused (zero leeway)."""
    now = int(time.time())
    with pytest.raises(TokenRejected):
        await ids.verify(id_token(auth_time=None), nonce_sha256=digest(NONCE))
    with pytest.raises(TokenRejected):
        await ids.verify(id_token(auth_time=str(now)), nonce_sha256=digest(NONCE))
    with pytest.raises(TokenRejected, match="older than the idle limit"):
        await ids.verify(id_token(auth_time=now - MAX_AGE - 1), nonce_sha256=digest(NONCE))
    claims = await ids.verify(id_token(auth_time=now - 10), nonce_sha256=digest(NONCE))
    assert claims.subject == UUID(ALEX)


@pytest.mark.asyncio
async def test_logout_token_accepted(logouts: LogoutTokenVerifier) -> None:
    claims = await logouts.verify(logout_token())
    assert claims.sid == "sid-1" and claims.subject == UUID(ALEX) and claims.jti == "j-1"
    assert claims.expires_at > time.time()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "token",
    [
        logout_token(iss="http://evil/realms/ops-dev"),
        logout_token(aud="other-client"),
        logout_token(nonce="n"),  # SA:541: no nonce
        logout_token(events=None),
        logout_token(events={"http://schemas.openid.net/event/other": {}}),
        logout_token(events="x"),
        logout_token(jti=None),
        logout_token(iat=None),
        logout_token(iat=int(time.time()) + 600),
        logout_token(exp=int(time.time()) - 5),
        logout_token(sid=None),
        logout_token(sub=None),
        logout_token(headers={"typ": "JWT"}),
        logout_token(pem=PEM2, kid="k1"),
        jwt.encode(
            {
                "iss": ISSUER,
                "aud": "ops-web",
                "exp": int(time.time()) + 60,
                "iat": int(time.time()),
                "jti": "j",
                "sid": "s",
                "sub": ALEX,
                "events": {BACKCHANNEL_EVENT: {}},
            },
            HS_KEY,
            algorithm="HS256",
            headers={"kid": "k1", "typ": "logout+jwt"},
        ),
    ],
)
async def test_logout_token_negatives(logouts: LogoutTokenVerifier, token: str) -> None:
    with pytest.raises(TokenRejected):
        await logouts.verify(token)

"""The three TokenVerifier knobs T11 adds (ruling 26): required claims, an optional `azp` check and a required
header `typ`. The ID-token and logout-token verifiers are instances built with them; every existing caller keeps the
defaults.

Catches: a logout token accepted without `jti` or `events`, a token with another `typ` header accepted where one is
required, and the default path changing (azp still required, `sub` still required).
"""

import time
from typing import Any

import jwt
import pytest
from ops_core.tokens import Principal, TokenRejected, TokenVerifier, WrongAudience

from tests.plan_d.test_tokens import ISSUER, JWK1, PEM1

AUD = "ops-web"


def mint(headers: dict[str, Any] | None = None, **over: Any) -> str:
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "sub": "2fc05986-c7ec-544c-b628-fdb112bbf18a",
        "aud": AUD,
        "exp": int(time.time()) + 120,
        "iat": int(time.time()),
    }
    claims.update(over)
    for key in [k for k, v in over.items() if v is None]:
        del claims[key]
    return jwt.encode(claims, PEM1, algorithm="RS256", headers={"kid": "k1", **(headers or {})})


def verifier(**knobs: Any) -> TokenVerifier:
    v = TokenVerifier(issuer=ISSUER, audience=AUD, allowed_azp=frozenset({AUD}), jwks_url="unused", **knobs)
    v.install_keys({"keys": [JWK1]})
    return v


def test_defaults_are_unchanged() -> None:
    with pytest.raises(WrongAudience):  # no azp at all: the default path still insists on one
        verifier().verify(mint())
    assert isinstance(verifier().verify(mint(azp=AUD)), Principal)


def test_required_claims_are_enforced() -> None:
    v = verifier(required_claims=("exp", "iss", "aud", "iat", "jti", "events"), require_azp=False)
    with pytest.raises(TokenRejected):
        v.verify(mint())  # no jti, no events
    p = v.verify(mint(jti="j1", events={"http://schemas.openid.net/event/backchannel-logout": {}}))
    assert p.azp == "" and p.claims["jti"] == "j1"


def test_header_typ_is_required_when_configured() -> None:
    v = verifier(typ="logout+jwt", require_azp=False)
    with pytest.raises(TokenRejected):
        v.verify(mint())  # typ JWT (PyJWT's default header)
    with pytest.raises(TokenRejected):
        v.verify(mint(headers={"typ": "ID"}))
    assert v.verify(mint(headers={"typ": "logout+jwt"})).subject.startswith("2fc05986")


def test_baseline_claims_are_always_required_and_typ_ignores_case() -> None:
    v = verifier(required_claims=("jti",), require_azp=False, typ="logout+jwt")
    with pytest.raises(TokenRejected):  # exp, iss and aud stay required whatever the caller lists
        v.verify(mint(headers={"typ": "logout+jwt"}, jti="j1", exp=None))
    assert v.verify(mint(headers={"typ": "Logout+JWT"}, jti="j1")).claims["jti"] == "j1"


def test_subject_is_optional_only_when_not_required() -> None:
    v = verifier(required_claims=("exp", "iss", "aud"), require_azp=False)
    assert v.verify(mint(sub=None)).subject == ""
    with pytest.raises(TokenRejected):
        verifier(require_azp=False).verify(mint(sub=None))

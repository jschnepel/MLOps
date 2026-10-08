"""A token whose signature, issuer and expiry pass but whose audience or azp is another server's is WrongAudience
(a TokenRejected subclass): every existing 401 handler keeps working, and incident-sim can answer 403 (T10 DoD 2)."""

import time

import pytest
from ops_core.tokens import TokenRejected, TokenVerifier, WrongAudience

from tests.plan_d.test_tokens import ISSUER, JWK1, PEM2, mint  # Plan D's synthetic key pair and token minter


@pytest.fixture
def verifier() -> TokenVerifier:
    v = TokenVerifier(
        issuer=ISSUER, audience="incident-sim", allowed_azp=frozenset({"ops-mcp-write"}), jwks_url="unused"
    )
    v.install_keys({"keys": [JWK1]})
    return v


def test_wrong_audience_and_wrong_azp_are_their_own_refusal(verifier: TokenVerifier) -> None:
    assert verifier.verify(mint(aud=["incident-sim"], azp="ops-mcp-write")).azp == "ops-mcp-write"
    for aud, azp in (("ops-api", "ops-mcp-write"), ("incident-sim", "ops-worker")):
        with pytest.raises(WrongAudience) as exc:
            verifier.verify(mint(aud=[aud], azp=azp))
        assert isinstance(exc.value, TokenRejected)


def test_a_bad_signature_is_not_wrong_audience(verifier: TokenVerifier) -> None:
    with pytest.raises(TokenRejected) as exc:
        verifier.verify(mint(PEM2, kid="k1", aud=["incident-sim"], azp="ops-mcp-write"))  # k2's key under k1's kid
    assert not isinstance(exc.value, WrongAudience)


def test_expiry_and_issuer_failures_stay_plain_rejections(verifier: TokenVerifier) -> None:
    """The 401 must win over the 403 when the token is not even valid. That order relies on PyJWT checking the
    signature, exp and iss before aud, so an expired or foreign-issuer token never reaches WrongAudience."""
    for bad in (
        mint(exp=int(time.time()) - 60, aud=["ops-api"], azp="ops-mcp-write"),
        mint(iss="https://other", aud=["ops-api"], azp="ops-mcp-write"),
    ):
        with pytest.raises(TokenRejected) as exc:
            verifier.verify(bad)
        assert not isinstance(exc.value, WrongAudience)

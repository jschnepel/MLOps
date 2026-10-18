"""Token verification (SA:557-558, BUILD_SPEC §9): every resource server checks signature, exp, iss, aud ∋ its own
resource identifier and azp ∈ its allowed workload clients, and a rejection never echoes the token.

Catches: a token for another audience accepted (the exact confusion the two MCP audiences exist to prevent), a token
with no `aud` accepted (today's persona tokens before Task 1's mapper), an expired or foreign-issuer token, a token
signed by another key, a rotation that strands the server on stale keys, and an `azp` check that trusts the token
instead of the server's allowlist.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from ops_core.tokens import Principal, TokenRejected, TokenVerifier, bearer_token

ISSUER = "http://localhost:18080/realms/ops-dev"
AUDIENCE = "http://mcp-read:8081/mcp"


def keypair(kid: str) -> tuple[bytes, dict[str, Any]]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key(), as_dict=True)
    jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return pem, jwk


PEM1, JWK1 = keypair("k1")
PEM2, JWK2 = keypair("k2")


def mint(pem: bytes = PEM1, kid: str = "k1", **over: Any) -> str:
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "sub": "2fc05986-c7ec-544c-b628-fdb112bbf18a",
        "aud": [AUDIENCE, "account"],
        "azp": "ops-worker",
        "exp": int(time.time()) + 300,
        "iat": int(time.time()),
        "typ": "Bearer",
    }
    claims.update(over)
    for key in [k for k, v in over.items() if v is None]:
        del claims[key]
    return jwt.encode(claims, pem, algorithm="RS256", headers={"kid": kid})


@pytest.fixture
def verifier() -> TokenVerifier:
    v = TokenVerifier(issuer=ISSUER, audience=AUDIENCE, allowed_azp=frozenset({"ops-worker"}), jwks_url="unused")
    v.install_keys({"keys": [JWK1]})
    return v


def test_valid_token_yields_the_principal(verifier: TokenVerifier):
    p = verifier.verify(mint())
    assert isinstance(p, Principal)
    assert p.subject == "2fc05986-c7ec-544c-b628-fdb112bbf18a" and p.azp == "ops-worker"
    assert AUDIENCE in p.audiences and p.expires_at > time.time()


def test_single_string_audience_is_accepted(verifier: TokenVerifier):
    assert verifier.verify(mint(aud=AUDIENCE)).audiences == (AUDIENCE,)


@pytest.mark.parametrize(
    "token",
    [
        mint(aud=["http://mcp-write:8082/mcp", "account"]),  # another audience (the write server's)
        mint(aud=None),  # no audience at all
        mint(azp="ops-mcp-write"),  # another workload presenting a token with the right audience
        mint(azp=None),
        mint(exp=int(time.time()) - 1),
        mint(iss="http://evil.example/realms/ops-dev"),
        mint(PEM2, "k1"),  # signed by a key that is not the published k1
        mint(PEM2, "k2"),  # unknown kid and no refresh possible in the sync path
        mint(sub=None),
        mint(sub=""),  # an empty subject identifies nobody
        mint(nbf=int(time.time()) + 3600),  # not valid yet
        mint(azp="ops-web"),  # the browser client must not open a worker-only MCP server
    ],
)
def test_rejections(verifier: TokenVerifier, token: str):
    with pytest.raises(TokenRejected) as caught:
        verifier.verify(token)
    assert token not in str(caught.value) and token[:20] not in str(caught.value)


def test_garbage_and_wrong_algorithm_are_rejected(verifier: TokenVerifier):
    with pytest.raises(TokenRejected):
        verifier.verify("not-a-jwt")
    with pytest.raises(TokenRejected):  # HS256 keyed with the published public key: the classic confusion attack
        verifier.verify(hs256_with_public_key())


def hs256_with_public_key() -> str:
    # Built by hand: PyJWT itself refuses to HMAC-sign with a PEM key, which is exactly what the attacker does.
    private = serialization.load_pem_private_key(PEM1, password=None)
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )

    def b64(raw: bytes) -> bytes:
        return base64.urlsafe_b64encode(raw).rstrip(b"=")

    header = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": "k1"}).encode())
    claims = {"iss": ISSUER, "aud": AUDIENCE, "azp": "ops-worker", "sub": "x", "exp": int(time.time()) + 60}
    signing_input = header + b"." + b64(json.dumps(claims).encode())
    return (signing_input + b"." + b64(hmac.new(public_pem, signing_input, hashlib.sha256).digest())).decode()


@pytest.mark.asyncio
async def test_unknown_kid_refreshes_keys_once(verifier: TokenVerifier):
    calls: list[str] = []

    async def fetch(url: str) -> dict[str, Any]:
        calls.append(url)
        return {"keys": [JWK1, JWK2]}

    verifier.fetch = fetch
    assert (await verifier.verify_async(mint(PEM2, "k2"))).azp == "ops-worker"
    assert calls == ["unused"]
    with pytest.raises(TokenRejected):  # inside the cooldown: rejected without another fetch
        await verifier.verify_async(mint(PEM1, "k3"))
    assert len(calls) == 1
    verifier._refreshed_at = 0.0  # cooldown elapsed: one more refresh, then rejected
    with pytest.raises(TokenRejected):
        await verifier.verify_async(mint(PEM1, "k3"))
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_load_keys_uses_the_fetch_and_marks_ready():
    v = TokenVerifier(issuer=ISSUER, audience=AUDIENCE, allowed_azp=frozenset({"ops-worker"}), jwks_url="u")
    assert not v.ready
    with pytest.raises(TokenRejected):  # no keys yet: nothing can verify, nothing is accepted
        v.verify(mint())

    async def fetch(url: str) -> dict[str, Any]:
        return {"keys": [JWK1]}

    await v.load_keys(fetch)
    assert v.ready and v.verify(mint()).azp == "ops-worker"


@pytest.mark.asyncio
async def test_workload_token_source_caches_until_near_expiry():
    from ops_core.tokens import WorkloadTokenSource

    calls: list[dict[str, str]] = []

    async def post(url: str, form: dict[str, str]) -> dict[str, Any]:
        calls.append(form)
        return {"access_token": f"t{len(calls)}", "expires_in": 300, "token_type": "Bearer"}

    src = WorkloadTokenSource(token_url="u", client_id="ops-worker", client_secret="s", post=post)
    assert await src.token() == "t1" and await src.token() == "t1"  # cached
    assert calls[0]["grant_type"] == "client_credentials" and calls[0]["client_id"] == "ops-worker"
    src.expires_at = time.time() + 10  # inside the 30 s refresh window
    assert await src.token() == "t2"


def test_bearer_header_parsing():
    assert bearer_token("Bearer abc.def.ghi") == "abc.def.ghi"
    bad_headers = (
        None,
        "",
        "Basic abc",
        "Bearer",
        "Bearer  ",
        "bearer abc",
        "Bearer  abc",
        "Bearer \tabc",
        "Bearer abc\n",
        "Bearer a\tb",
        "Bearer a b",
    )
    for bad in bad_headers:
        with pytest.raises(TokenRejected):
            bearer_token(bad)


@pytest.mark.asyncio
async def test_failing_fetch_is_a_rejection_and_starts_the_cooldown(verifier: TokenVerifier):
    attempts: list[str] = []

    async def fetch(url: str) -> dict[str, Any]:
        attempts.append(url)
        raise OSError("keycloak is down")

    verifier.fetch = fetch
    with pytest.raises(TokenRejected, match="signing keys unavailable"):
        await verifier.verify_async(mint(PEM2, "k2"))
    for _ in range(2):  # a flood of unknown kids while the IdP is down: rejected inside the cooldown, no new fetch
        with pytest.raises(TokenRejected):
            await verifier.verify_async(mint(PEM2, "k2"))
    assert len(attempts) == 1
    assert verifier.verify(mint()).azp == "ops-worker"  # the old keys still serve known kids


@pytest.mark.asyncio
async def test_concurrent_unknown_kid_requests_share_one_fetch(verifier: TokenVerifier):
    calls: list[str] = []

    async def fetch(url: str) -> dict[str, Any]:
        calls.append(url)
        await asyncio.sleep(0.05)
        return {"keys": [JWK1, JWK2]}

    verifier.fetch = fetch
    results = await asyncio.gather(*(verifier.verify_async(mint(PEM2, "k2")) for _ in range(10)))
    assert len(calls) == 1 and all(p.azp == "ops-worker" for p in results)


def test_encryption_keys_never_verify(verifier: TokenVerifier):
    verifier.install_keys({"keys": [{**JWK1, "use": "enc"}, JWK2]})
    with pytest.raises(TokenRejected):
        verifier.verify(mint())


def test_principal_claims_are_read_only_and_not_in_repr(verifier: TokenVerifier):
    p = verifier.verify(mint())
    claims: Any = p.claims
    with pytest.raises(TypeError):
        claims["sub"] = "someone-else"
    assert "claims" not in repr(p)


@pytest.mark.asyncio
async def test_workload_token_source_single_flight_and_unusable_reply():
    from ops_core.tokens import WorkloadTokenSource

    calls: list[dict[str, str]] = []

    async def post(url: str, form: dict[str, str]) -> dict[str, Any]:
        calls.append(form)
        await asyncio.sleep(0.05)
        return {"access_token": "t", "expires_in": 300}

    src = WorkloadTokenSource(token_url="u", client_id="ops-worker", client_secret="s", post=post)
    assert await asyncio.gather(*(src.token() for _ in range(8))) == ["t"] * 8
    assert len(calls) == 1

    async def bad(url: str, form: dict[str, str]) -> dict[str, Any]:
        return {"error": "invalid_client"}

    broken = WorkloadTokenSource(token_url="u", client_id="ops-worker", client_secret="hunter2", post=bad)
    with pytest.raises(TokenRejected) as caught:
        await broken.token()
    assert "hunter2" not in str(caught.value)

"""The verifier against Keycloak's real JWKS and real tokens (OPS_LIVE=1): the worker token passes at the read
audience and fails at the write server's allowlist; the persona token passes only at the API audience."""

import pytest
from ops_core import settings
from ops_core.tokens import TokenRejected, TokenVerifier

from tests.plan_b.live import kc

pytestmark = pytest.mark.asyncio


async def test_real_tokens_against_real_jwks(env: dict[str, str], secret) -> None:
    keycloak = settings.keycloak()
    urls = settings.urls()
    worker = kc.token_client_credentials(keycloak.base_url, "ops-worker", secret("kc_client_secret_ops_worker"))
    alex = kc.token_password(keycloak.base_url, "ops-dev-direct", "alex", secret("kc_persona_alex_password"))
    worker_token, alex_token = worker["access_token"], alex["access_token"]
    read = TokenVerifier(
        issuer=keycloak.issuer,
        audience=urls.mcp_read_resource,
        allowed_azp=frozenset({"ops-worker"}),
        jwks_url=keycloak.jwks_url,
    )
    await read.load_keys()
    # Pytest prints the operands of a failed assert, so the token never appears inside one (Plan B's lesson).
    principal = await read.verify_async(worker_token)
    assert principal.azp == "ops-worker"
    with pytest.raises(TokenRejected):  # persona token at the MCP server: wrong audience
        await read.verify_async(alex_token)
    api = TokenVerifier(
        issuer=keycloak.issuer,
        audience="ops-api",
        allowed_azp=frozenset({"ops-dev-direct"}),
        jwks_url=keycloak.jwks_url,
    )
    await api.load_keys()
    persona = await api.verify_async(alex_token)
    assert persona.claims["preferred_username"] == "alex"
    with pytest.raises(TokenRejected):  # worker token at the API: wrong audience and wrong azp
        await api.verify_async(worker_token)

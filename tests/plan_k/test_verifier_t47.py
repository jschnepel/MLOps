"""mcp-write's token checks with the verifier `production_app` builds (`write_verifier`), on Plan D's synthetic key
pair (SA:557-558; Plan K ruling 11: mcp-read's cases from tests/plan_j/test_verifier_t15.py, at mcp-write).

Catches: an ID or refresh token accepted as an access token (`typ` claim), a browser client's token (`azp` ops-web), a
token without `aud`, the read server's audience, or another workload's `azp` (mcp-read's, or mcp-write's own client)
accepted at mcp-write; an access token whose `resource` is stamped without the audience holding it (before T47
mcp-write stamped its own URL whatever `aud` held); a refactor that drops `token_type="Bearer"` from mcp-write's
verifier or turns the SDK's `validate_token_resource` off again; and a `production_app` that inlines its own verifier.
"""

import asyncio
from typing import Any

import pytest
from ops_core import settings
from ops_core.settings import Keycloak, Urls
from ops_core.tokens import TokenRejected, TokenVerifier
from ops_mcp_write import server
from ops_mcp_write.server import McpVerifier

from tests.plan_d.test_tokens import AUDIENCE as READ_AUDIENCE  # Plan D's synthetic key pair and token minter
from tests.plan_d.test_tokens import ISSUER, JWK1, mint

WRITE = "http://mcp-write:8082/mcp"
URLS = Urls(
    mcp_read_resource=READ_AUDIENCE,
    mcp_write_resource=WRITE,
    mcp_read="http://127.0.0.1:8081/mcp",
    mcp_write="http://127.0.0.1:8082/mcp",
    incident_sim="http://127.0.0.1:8090",
    asset_sim="http://127.0.0.1:8091",
    ollama="http://127.0.0.1:11434",
)
KC = Keycloak(base_url="http://localhost:18080", issuer=ISSUER, server_url="http://127.0.0.1:18080")


def production_like() -> TokenVerifier:
    """`ops_mcp_write.server.write_verifier`, the one `production_app` uses, with the synthetic key installed."""
    verifier = server.write_verifier(KC, URLS)
    verifier.install_keys({"keys": [JWK1]})
    return verifier


def for_write(**over: Any) -> str:
    """A synthetic worker token that carries mcp-write's audience (the worker's real token carries both servers')."""
    return mint(**{"aud": [READ_AUDIENCE, WRITE, "account"], **over})


def test_only_an_access_token_passes() -> None:
    verifier = production_like()
    assert verifier.verify(for_write()).azp == "ops-worker"
    for typ in ("ID", "Refresh", None):
        with pytest.raises(TokenRejected, match="token type"):
            verifier.verify(for_write(typ=typ))


@pytest.mark.parametrize(
    ("over", "why"),
    [
        ({"azp": "ops-web"}, "the browser client's token"),
        ({"aud": None}, "no audience at all"),
        ({"aud": [READ_AUDIENCE, "account"]}, "the read server's audience only"),
        ({"aud": "ops-api", "azp": "ops-dev-direct"}, "a persona token"),
        ({"azp": "ops-mcp-read"}, "mcp-read's workload with the right audience"),
        ({"azp": "ops-mcp-write"}, "mcp-write's own workload client"),
    ],
)
def test_the_adapter_answers_none_for_every_foreign_token(over: dict[str, object], why: str) -> None:
    adapter = McpVerifier(production_like(), WRITE)
    refused = asyncio.run(adapter.verify_token(for_write(**over))) is None  # None is the SDK's 401
    assert refused, why  # a verdict, not the AccessToken: its repr would hold the (synthetic) token


def test_the_resource_is_stamped_only_from_the_audience() -> None:
    adapter = McpVerifier(production_like(), WRITE)
    access = asyncio.run(adapter.verify_token(for_write()))
    stamped = access is not None and access.resource == WRITE and access.client_id == "ops-worker"
    assert stamped  # a verdict, not the AccessToken: its repr holds the (synthetic) token
    # A verifier wired to another audience (a deployment mistake) still cannot stamp this server's resource.
    wrong = TokenVerifier(
        issuer=ISSUER, audience="account", allowed_azp=frozenset({"ops-worker"}), jwks_url="unused", token_type="Bearer"
    )
    wrong.install_keys({"keys": [JWK1]})
    refused = asyncio.run(McpVerifier(wrong, WRITE).verify_token(mint(aud=["account"]))) is None
    assert refused


def test_the_sdk_resource_check_is_on() -> None:
    """A second layer behind McpVerifier's own audience check, pinned so a refactor cannot switch it off unnoticed."""
    state = server.State(deps=None, verifier=production_like())
    mcp = server.build_server(state, issuer=ISSUER, resource_url=WRITE)
    assert mcp.settings.auth is not None and mcp.settings.auth.validate_token_resource is True


def test_production_app_builds_its_verifier_through_write_verifier(monkeypatch: pytest.MonkeyPatch) -> None:
    """The tests above pin `write_verifier`; this pins that the app that runs uses it (a refactor that inlined a
    `TokenVerifier` without `token_type` would pass every other unit and live test, since live tokens are `Bearer`)."""
    calls: list[tuple[Any, Any]] = []
    real = server.write_verifier

    def recording(kc: Keycloak, urls: Urls) -> TokenVerifier:
        calls.append((kc, urls))
        return real(kc, urls)

    monkeypatch.setattr(settings, "keycloak", lambda: KC)
    monkeypatch.setattr(settings, "urls", lambda: URLS)
    monkeypatch.setattr(server, "write_verifier", recording)
    server.production_app()
    assert calls == [(KC, URLS)]

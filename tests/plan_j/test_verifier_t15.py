"""mcp-read's token checks with the verifier `production_app` builds (`read_verifier`), on Plan D's synthetic key pair
(SA:557-558, Plan J rulings 2, 14 and 15).

Catches: an ID or refresh token accepted as an access token (`typ` claim), a browser client's token (`azp` ops-web,
the unit stand-in for a real `ops-web` access token, ruling 14), a token without `aud` (ruling 15: this synthetic case
is the evidence), another server's audience, or another workload's `azp` accepted at mcp-read; an access token whose
`resource` is stamped without the audience holding it; a refactor that drops `token_type="Bearer"` from mcp-read's
verifier or turns the SDK's `validate_token_resource` off; and the knob changing the other servers' verifiers, which
leave `token_type` unset.
"""

import asyncio
from typing import Any

import pytest
from ops_core import settings
from ops_core.settings import Keycloak, Urls
from ops_core.tokens import TokenRejected, TokenVerifier, WorkloadTokenSource
from ops_mcp_read import server
from ops_mcp_read.server import McpVerifier

from tests.plan_d.test_tokens import AUDIENCE, ISSUER, JWK1, mint  # Plan D's synthetic key pair and token minter

URLS = Urls(
    mcp_read_resource=AUDIENCE,
    mcp_write_resource="http://mcp-write:8082/mcp",
    mcp_read="http://127.0.0.1:8081/mcp",
    mcp_write="http://127.0.0.1:8082/mcp",
    incident_sim="http://127.0.0.1:8090",
    asset_sim="http://127.0.0.1:8091",
    ollama="http://127.0.0.1:11434",
)


KC = Keycloak(base_url="http://localhost:18080", issuer=ISSUER, server_url="http://127.0.0.1:18080")


def production_like() -> TokenVerifier:
    """`ops_mcp_read.server.read_verifier`, the one `production_app` uses, with the synthetic key installed."""
    verifier = server.read_verifier(KC, URLS)
    verifier.install_keys({"keys": [JWK1]})
    return verifier


def test_only_an_access_token_passes() -> None:
    verifier = production_like()
    assert verifier.verify(mint()).azp == "ops-worker"
    for typ in ("ID", "Refresh", None):
        with pytest.raises(TokenRejected, match="token type"):
            verifier.verify(mint(typ=typ))
    legacy = TokenVerifier(issuer=ISSUER, audience=AUDIENCE, allowed_azp=frozenset({"ops-worker"}), jwks_url="unused")
    legacy.install_keys({"keys": [JWK1]})
    assert legacy.verify(mint(typ="ID")).azp == "ops-worker"  # unset, the knob changes no other server


@pytest.mark.parametrize(
    ("over", "why"),
    [
        ({"azp": "ops-web"}, "the browser client's token"),
        ({"aud": None}, "no audience at all"),
        ({"aud": ["http://mcp-write:8082/mcp", "account"]}, "the write server's audience only"),
        ({"aud": "ops-api", "azp": "ops-dev-direct"}, "a persona token (the live browser stand-in)"),
        ({"azp": "ops-mcp-read"}, "another workload with the right audience"),
    ],
)
def test_the_adapter_answers_none_for_every_foreign_token(over: dict[str, object], why: str) -> None:
    adapter = McpVerifier(production_like(), AUDIENCE)
    assert asyncio.run(adapter.verify_token(mint(**over))) is None, why  # None is the SDK's 401


def test_the_resource_is_stamped_only_from_the_audience() -> None:
    adapter = McpVerifier(production_like(), AUDIENCE)
    access = asyncio.run(adapter.verify_token(mint(aud=["http://mcp-write:8082/mcp", AUDIENCE, "account"])))
    assert access is not None and access.resource == AUDIENCE and access.client_id == "ops-worker"
    # A verifier wired to another audience (a deployment mistake) still cannot stamp this server's resource.
    wrong = TokenVerifier(
        issuer=ISSUER, audience="account", allowed_azp=frozenset({"ops-worker"}), jwks_url="unused", token_type="Bearer"
    )
    wrong.install_keys({"keys": [JWK1]})
    assert asyncio.run(McpVerifier(wrong, AUDIENCE).verify_token(mint(aud=["account"]))) is None


def test_the_sdk_resource_check_is_on() -> None:
    """A second layer behind McpVerifier's own audience check (it cannot refuse while the stamp is this server's URL),
    pinned so a refactor cannot switch it off unnoticed."""
    state = server.State(session=None, verifier=production_like())
    mcp = server.build_server(state, issuer=ISSUER, resource_url=AUDIENCE)
    assert mcp.settings.auth is not None and mcp.settings.auth.validate_token_resource is True


def test_production_app_builds_its_verifier_through_read_verifier(monkeypatch: pytest.MonkeyPatch) -> None:
    """The tests above pin `read_verifier`; this pins that the app that runs uses it (a refactor that inlined a
    `TokenVerifier` without `token_type` would pass every other unit and live test, since live tokens are `Bearer`)."""
    calls: list[tuple[Any, Any]] = []
    real = server.read_verifier

    def recording(kc: Keycloak, urls: Urls) -> TokenVerifier:
        calls.append((kc, urls))
        return real(kc, urls)

    monkeypatch.setattr(settings, "keycloak", lambda: KC)
    monkeypatch.setattr(settings, "urls", lambda: URLS)
    monkeypatch.setattr(server, "read_verifier", recording)
    server.production_app()
    assert calls == [(KC, URLS)]


def test_the_token_source_names_its_client() -> None:
    assert WorkloadTokenSource(token_url="u", client_id="ops-worker", client_secret="s").client_id == "ops-worker"

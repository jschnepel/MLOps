"""The worker's client is named once, in settings (T47 review note 3, Plan K ruling 12): the worker's token source asks
for tokens as it, and both MCP servers' verifiers accept it and no other `azp`.

Catches: one of the three places keeping its own literal, so that renaming the client (`OPS_WORKLOAD_CLIENT_ID`)
leaves the worker asking for the old client's tokens, or a verifier refusing the renamed client's tokens while still
accepting the old one's. The fourth place, the `azp` a handle is minted with, follows the token source
(tests/plan_j/test_worker_azp.py); the definers compare the presented token's `azp` from revision 0010 on
(tests/e2e/test_migration_0010_live.py).
"""

from typing import Any

import pytest
from ops_core import settings
from ops_core.tokens import TokenRejected, TokenVerifier
from ops_mcp_read import server as read_server
from ops_mcp_write import server as write_server
from ops_worker import main

from tests.plan_d.test_tokens import AUDIENCE as READ_AUDIENCE
from tests.plan_d.test_tokens import JWK1, mint
from tests.plan_k.test_verifier_t47 import KC, URLS, WRITE


def test_the_default_is_the_realms_worker_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPS_WORKLOAD_CLIENT_ID", raising=False)
    assert settings.workload_client_id() == "ops-worker"
    monkeypatch.setenv("OPS_WORKLOAD_CLIENT_ID", "")  # an empty value counts as unset (settings.env)
    assert settings.workload_client_id() == "ops-worker"


def test_a_padded_client_id_is_trimmed_and_a_blank_one_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """No token carries " ops-worker-renamed": a padded value would turn an editing slip into an opaque 401 at both
    servers, and an all-blank one would name no client at all."""
    monkeypatch.setenv("OPS_WORKLOAD_CLIENT_ID", " ops-worker-renamed\t\n")
    assert settings.workload_client_id() == "ops-worker-renamed"
    monkeypatch.setenv("OPS_WORKLOAD_CLIENT_ID", " \t ")
    assert settings.workload_client_id() == "ops-worker"


def test_the_worker_asks_for_tokens_as_the_named_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_WORKLOAD_CLIENT_ID", "ops-worker-renamed")
    asked: list[str] = []

    def read_secret(name: str, directory: Any = None) -> str:
        asked.append(name)
        return "unit-test"

    monkeypatch.setattr(settings, "read_secret", read_secret)
    tokens = main.token_source(KC)
    assert tokens.client_id == "ops-worker-renamed" and asked == ["kc_client_secret_ops_worker"]


@pytest.mark.parametrize(
    ("build", "audience"),
    [(read_server.read_verifier, READ_AUDIENCE), (write_server.write_verifier, WRITE)],
    ids=["mcp-read", "mcp-write"],
)
def test_both_verifiers_accept_only_the_named_client(
    monkeypatch: pytest.MonkeyPatch, build: Any, audience: str
) -> None:
    monkeypatch.setenv("OPS_WORKLOAD_CLIENT_ID", "ops-worker-renamed")
    verifier: TokenVerifier = build(KC, URLS)
    verifier.install_keys({"keys": [JWK1]})
    assert verifier.verify(mint(aud=[audience, "account"], azp="ops-worker-renamed")).azp == "ops-worker-renamed"
    with pytest.raises(TokenRejected):
        verifier.verify(mint(aud=[audience, "account"], azp="ops-worker"))  # the old literal is no longer accepted

"""The T11 settings: server-side Keycloak URLs on 127.0.0.1 (spike §3: `localhost` costs 2 s per connection on
the dev machine), the public base URL that is the only origin the API trusts, the session lifetimes of BUILD_SPEC
§9, and the admin-check budget.

Catches: a server-to-server URL that still says `localhost`, an `http` base URL for a host that is not loopback
(BUILD_SPEC §9 allows the HTTP exception for localhost only), a base URL with a path (the Origin comparison would
never match), and a non-positive budget.
"""

import pytest
from ops_core import settings
from ops_core.settings import SettingsError


@pytest.fixture(autouse=True)
def clean(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "OPS_KC_BASE_URL",
        "OPS_KC_ISSUER",
        "OPS_KC_SERVER_URL",
        "OPS_PUBLIC_BASE_URL",
        "OPS_SESSION_IDLE_SECONDS",
        "OPS_SESSION_ABSOLUTE_SECONDS",
        "OPS_SESSION_LOGIN_SECONDS",
        "OPS_ADMIN_CHECK_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_server_side_urls_use_the_loopback_address_and_the_issuer_keeps_localhost() -> None:
    kc = settings.keycloak()
    assert kc.base_url == "http://localhost:18080" and kc.server_url == "http://127.0.0.1:18080"
    assert kc.issuer == "http://localhost:18080/realms/ops-dev"
    for url in (kc.jwks_url, kc.token_url, kc.discovery_url, kc.end_session_url, kc.admin_users_url):
        assert url.startswith("http://127.0.0.1:18080/"), url
    assert kc.admin_users_url == "http://127.0.0.1:18080/admin/realms/ops-dev/users"
    assert kc.discovery_url == "http://127.0.0.1:18080/realms/ops-dev/.well-known/openid-configuration"
    assert kc.server_side("http://localhost:18080/realms/ops-dev/x") == "http://127.0.0.1:18080/realms/ops-dev/x"
    assert kc.server_side("http://elsewhere/x") == "http://elsewhere/x"


def test_server_url_is_overridable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_KC_BASE_URL", "http://keycloak:8080")
    assert settings.keycloak().server_url == "http://keycloak:8080"  # no localhost to swap: the container name
    monkeypatch.setenv("OPS_KC_SERVER_URL", "http://10.0.0.5:8080/")
    assert settings.keycloak().server_url == "http://10.0.0.5:8080"


def test_session_defaults_follow_build_spec_section_9() -> None:
    s = settings.sessions()
    assert s.public_base_url == "http://localhost:8000" and s.origin == "http://localhost:8000"
    assert s.redirect_uri == "http://localhost:8000/auth/callback"
    assert (s.idle_seconds, s.absolute_seconds, s.login_seconds) == (1800, 28800, 600)
    assert s.cookie_secure is False


@pytest.mark.parametrize(
    "base",
    ["http://ops.example.com", "https://ops.example.com/app", "localhost:8000", "http://localhost:8000/?x=1"],
)
def test_public_base_url_must_be_an_origin_and_http_only_for_loopback(monkeypatch: pytest.MonkeyPatch, base: str):
    monkeypatch.setenv("OPS_PUBLIC_BASE_URL", base)
    with pytest.raises(SettingsError):
        settings.sessions()


def test_https_base_url_makes_cookies_secure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_PUBLIC_BASE_URL", "https://ops.example.com/")
    s = settings.sessions()
    assert s.cookie_secure is True and s.origin == "https://ops.example.com"


def test_admin_check_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    assert settings.admin_check_timeout() == 2.0
    monkeypatch.setenv("OPS_ADMIN_CHECK_TIMEOUT_SECONDS", "0.5")
    assert settings.admin_check_timeout() == 0.5
    for bad in ("0", "nan", "inf", "soon"):
        monkeypatch.setenv("OPS_ADMIN_CHECK_TIMEOUT_SECONDS", bad)
        with pytest.raises(SettingsError):
            settings.admin_check_timeout()

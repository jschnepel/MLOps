"""Process configuration (BUILD_SPEC §22, Plan B's no-secret-in-environment rule): secrets come from files, never from
the environment, and never leak into a repr, a message or a URL.

Catches: a secret read with its trailing newline (every token exchange would then fail with a wrong-password error that
looks like a Keycloak outage), an empty or missing secret file silently becoming an empty password, a settings error
message that echoes a value, and a default URL drifting away from scripts/bootstrap_dev.py's .env.
"""

from pathlib import Path

import pytest
from ops_core import settings


@pytest.fixture
def secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "secrets"
    directory.mkdir()
    (directory / "postgres_password").write_text("pg-secret-value\n", encoding="utf-8")
    (directory / "postgres_incident_password").write_text("incident-secret-value", encoding="utf-8")
    (directory / "empty_secret").write_text("\n", encoding="utf-8")
    monkeypatch.setenv("OPS_SECRETS_DIR", str(directory))
    for name in (
        "OPS_PG_HOST",
        "OPS_PG_PORT",
        "OPS_PG_USER",
        "OPS_PG_SUPERUSER",
        "OPS_PG_DB",
        "OPS_KC_BASE_URL",
        "OPS_KC_ISSUER",
    ):
        monkeypatch.delenv(name, raising=False)
    return directory


def test_read_secret_strips_the_trailing_newline(secrets: Path):
    assert settings.read_secret("postgres_password") == "pg-secret-value"
    assert settings.read_secret("postgres_incident_password") == "incident-secret-value"


def test_missing_or_empty_secret_is_an_error_that_names_the_file_only(secrets: Path):
    with pytest.raises(settings.SettingsError) as missing:
        settings.read_secret("kc_client_secret_ops_worker")
    assert "kc_client_secret_ops_worker" in str(missing.value) and str(secrets) not in str(missing.value)
    with pytest.raises(settings.SettingsError):
        settings.read_secret("empty_secret")


def test_missing_variable_names_the_variable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OPS_SECRETS_DIR", raising=False)
    with pytest.raises(settings.SettingsError, match="OPS_SECRETS_DIR"):
        settings.secrets_dir()
    monkeypatch.setenv("OPS_PG_PORT", "not-a-port")
    with pytest.raises(settings.SettingsError, match="OPS_PG_PORT"):
        settings.env_int("OPS_PG_PORT", 15432)


def test_postgres_settings_build_a_conninfo_and_hide_the_password(secrets: Path):
    pg = settings.superuser_postgres()
    assert (pg.host, pg.port, pg.user, pg.dbname) == ("127.0.0.1", 15432, "ops", "ops")
    assert "password=pg-secret-value" in pg.conninfo() and "dbname=ops" in pg.conninfo()
    assert "pg-secret-value" not in repr(pg) and "pg-secret-value" not in str(pg)
    incident = settings.incident_postgres()
    assert (incident.user, incident.dbname) == ("incident", "incident")
    assert "password=incident-secret-value" in incident.conninfo()


def test_keycloak_and_service_urls_default_to_the_dev_stack(secrets: Path, monkeypatch: pytest.MonkeyPatch):
    kc = settings.keycloak()
    assert kc.issuer == "http://localhost:18080/realms/ops-dev"
    # Server-side URLs dial 127.0.0.1: `localhost` costs about 2 s per connection on the dev machine (spike §3).
    assert kc.jwks_url == "http://127.0.0.1:18080/realms/ops-dev/protocol/openid-connect/certs"
    assert kc.token_url == "http://127.0.0.1:18080/realms/ops-dev/protocol/openid-connect/token"
    monkeypatch.setenv("OPS_KC_BASE_URL", "http://localhost:28080/")
    assert settings.keycloak().issuer == "http://localhost:28080/realms/ops-dev"  # trailing slash tolerated
    for name in ("MCP_READ_RESOURCE_URL", "MCP_WRITE_RESOURCE_URL", "OPS_MCP_READ_URL", "OPS_MCP_WRITE_URL"):
        monkeypatch.delenv(name, raising=False)
    u = settings.urls()
    # The resource URLs are audience identifiers (what the realm puts in `aud`); the listen URLs are where the
    # host processes actually answer. They differ on purpose until T30 containerises the servers.
    assert u.mcp_read_resource == "http://mcp-read:8081/mcp" and u.mcp_read == "http://127.0.0.1:8081/mcp"
    assert u.mcp_write_resource == "http://mcp-write:8082/mcp" and u.mcp_write == "http://127.0.0.1:8082/mcp"
    assert u.incident_sim == "http://127.0.0.1:8090"
    assert settings.fixtures_dir() == Path("data/handoff-fixtures")

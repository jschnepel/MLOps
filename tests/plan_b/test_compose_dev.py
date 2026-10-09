"""Static checks on compose.yaml: loopback bindings, digest pins, file secrets, no secret in environment.

These run without Docker. They catch the mistakes that would silently weaken the dev profile: a port published on all
interfaces, a floating image tag, or a password placed in `environment:` where `docker inspect` would reveal it.
"""

import re
from pathlib import Path

import yaml

COMPOSE = Path("compose.yaml")
DIGEST = re.compile(r"^[\w./-]+:[\w.-]+@sha256:[0-9a-f]{64}$")


def load() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_project_name_and_profile():
    doc = load()
    assert doc["name"] == "ops-copilot"
    for name in ("postgres", "keycloak"):
        assert doc["services"][name]["profiles"] == ["dev"], name


def test_every_published_port_binds_loopback():
    # An unprefixed "5432:5432" would publish on every interface, including the LAN.
    for name, svc in load()["services"].items():
        for port in svc.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), (name, port)


def test_images_are_pinned_by_digest():
    for name, svc in load()["services"].items():
        assert DIGEST.match(svc["image"]), (name, svc["image"])


def test_no_internal_network_with_published_port():
    # An `internal: true` network has no host route, so published ports on it would silently not work.
    doc = load()
    for name, net in doc.get("networks", {}).items():
        assert not (net or {}).get("internal", False), name


def test_compose_environment_carries_no_secret():
    for name, svc in load()["services"].items():
        env = svc.get("environment", {}) or {}
        items = env.items() if isinstance(env, dict) else (kv.split("=", 1) for kv in env)
        for key, value in items:
            if "PASSWORD" in key.upper() or "SECRET" in key.upper():
                assert key.upper().endswith("_FILE") and str(value).startswith("/run/secrets/"), (name, key)


def test_secrets_are_files_under_secrets_dir():
    doc = load()
    assert doc["secrets"], "no top-level secrets"
    for name, spec in doc["secrets"].items():
        assert spec["file"] == f"${{OPS_SECRETS_DIR}}/{name}", (name, spec)
    for svc_name in ("postgres", "keycloak"):
        used = doc["services"][svc_name].get("secrets", [])
        assert used, svc_name
        for s in used:
            assert s in doc["secrets"], (svc_name, s)


def test_keycloak_hostname_settings():
    env = load()["services"]["keycloak"]["environment"]
    assert env["KC_HOSTNAME"] == "http://localhost:${KC_HTTP_PORT}"
    assert env["KC_HOSTNAME_BACKCHANNEL_DYNAMIC"] == "true"
    assert env["KC_HTTP_ENABLED"] == "true"
    assert env["KC_HEALTH_ENABLED"] == "true"
    assert env["KC_BOOTSTRAP_ADMIN_USERNAME"] == "tmpadmin"
    assert "KC_BOOTSTRAP_ADMIN_PASSWORD" not in env  # the entrypoint exports it from the secret file


def test_postgres_uses_password_file_and_init_script():
    svc = load()["services"]["postgres"]
    assert svc["environment"]["POSTGRES_PASSWORD_FILE"] == "/run/secrets/postgres_password"
    assert any(v.startswith("./deploy/dev/postgres/init:") for v in svc["volumes"])

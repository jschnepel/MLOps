"""scripts/bootstrap_dev.py: secret generation is idempotent and never writes inside the repository.

Protects against the two ways the bootstrap could hurt the owner: regenerating (and so invalidating) existing secrets
on a second run, and leaving secret files or a CRLF/BOM-damaged `.env` where Compose or git would trip on them.
"""

import os
from pathlib import Path

import pytest

from scripts import bootstrap_dev as b


def test_secret_names_cover_compose_secrets():
    import yaml

    doc = yaml.safe_load(Path("compose.yaml").read_text(encoding="utf-8"))
    assert set(doc["secrets"]) == set(b.SECRET_NAMES)


def test_generate_secrets_creates_once_and_never_overwrites(tmp_path: Path):
    created = b.generate_secrets(tmp_path, b.SECRET_NAMES)
    assert sorted(created) == sorted(b.SECRET_NAMES)
    before = {n: (tmp_path / n).read_bytes() for n in b.SECRET_NAMES}
    assert b.generate_secrets(tmp_path, b.SECRET_NAMES) == []
    assert {n: (tmp_path / n).read_bytes() for n in b.SECRET_NAMES} == before
    for n, data in before.items():
        assert len(data) >= 32 and b"\n" not in data and b"\r" not in data, n


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits")
def test_generate_secrets_creates_owner_only_files_on_posix(tmp_path: Path):
    directory = tmp_path / "secrets"
    b.generate_secrets(directory, b.SECRET_NAMES)
    assert directory.stat().st_mode & 0o777 == 0o700
    for n in b.SECRET_NAMES:
        assert (directory / n).stat().st_mode & 0o777 == 0o600, n


def test_write_env_is_lf_without_bom_and_has_required_keys(tmp_path: Path):
    env_path = tmp_path / ".env"
    b.write_env(env_path, tmp_path / "secrets")
    raw = env_path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and b"\r" not in raw
    text = raw.decode("utf-8")
    keys = {line.split("=", 1)[0] for line in text.splitlines() if line and not line.startswith("#")}
    assert keys == {
        "OPS_SECRETS_DIR",
        "KC_HTTP_PORT",
        "PG_PORT",
        "MCP_READ_RESOURCE_URL",
        "MCP_WRITE_RESOURCE_URL",
        "OLLAMA_BASE_URL_HOST",
        "OLLAMA_BASE_URL_CONTAINER",
    }
    assert "\\" not in text.split("OPS_SECRETS_DIR=", 1)[1].splitlines()[0]  # forward slashes for Compose
    assert "KC_HTTP_PORT=18080" in text and "PG_PORT=15432" in text


def test_default_secrets_dir_is_outside_repo(monkeypatch):
    monkeypatch.delenv("OPS_SECRETS_DIR", raising=False)  # the override is documented; the default is under test here
    d = b.secrets_dir()
    assert "ops-copilot" in d.parts and "secrets" == d.name
    assert Path.cwd() not in d.parents and d != Path.cwd()


def test_secret_names_include_all_personas_and_view_users():
    for name in ("lee", "riley", "jordan"):
        assert f"kc_persona_{name}_password" in b.SECRET_NAMES
    assert "kc_client_secret_ops_view_users" in b.SECRET_NAMES

"""Per-role database settings and the profile switch (AM-20.1 one login per service; AM-20.6/20.7 profiles).

Catches: a service that could still connect as the owner by default, a role whose secret file name does not follow
the `postgres_<role>_password` pattern the bootstrap generates, a profile value that is not one of the three, and a
password that reaches a repr.
"""

from pathlib import Path

import pytest
from ops_core import settings
from ops_core.settings import Profile, Role, SettingsError


@pytest.fixture
def secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("OPS_SECRETS_DIR", str(tmp_path))
    monkeypatch.delenv("PROFILE", raising=False)
    monkeypatch.delenv("OPS_PG_DB", raising=False)
    (tmp_path / "postgres_password").write_text("owner-pw\n", encoding="utf-8")
    for role in Role:
        (tmp_path / f"postgres_{role.value}_password").write_text(f"{role.value}-pw\n", encoding="utf-8")
    return tmp_path


def test_every_role_reads_its_own_secret_file_and_connects_as_itself(secrets: Path) -> None:
    for role in Role:
        pg = settings.app_postgres(role)
        assert pg.user == role.value and pg.dbname == "ops" and pg.password == f"{role.value}-pw"
        assert f"user={role.value}" in pg.conninfo() and "owner-pw" not in pg.conninfo()
        assert "-pw" not in repr(pg)


def test_superuser_is_explicit_and_the_database_name_follows_the_environment(
    secrets: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert (
        settings.app_postgres.__defaults__ is None
    )  # the role is required: no caller connects as the owner by accident
    monkeypatch.setenv("OPS_PG_DB", "ops_test")
    assert settings.superuser_postgres().user == "ops" and settings.superuser_postgres().dbname == "ops_test"
    assert settings.app_postgres(Role.API).dbname == "ops_test"


def test_missing_role_secret_names_the_file_not_the_path(secrets: Path) -> None:
    (secrets / "postgres_sweeper_password").unlink()
    with pytest.raises(SettingsError) as exc:
        settings.app_postgres(Role.SWEEPER)
    assert "postgres_sweeper_password" in str(exc.value) and str(secrets) not in str(exc.value)


@pytest.mark.parametrize(("raw", "expected"), [(None, Profile.DEV), ("test", Profile.TEST), ("demo", Profile.DEMO)])
def test_profile_defaults_to_dev(monkeypatch: pytest.MonkeyPatch, raw: str | None, expected: Profile) -> None:
    if raw is None:
        monkeypatch.delenv("PROFILE", raising=False)
    else:
        monkeypatch.setenv("PROFILE", raw)
    assert settings.profile() is expected


def test_unknown_profile_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROFILE", "prod")
    with pytest.raises(SettingsError):
        settings.profile()


def test_secret_names_match_the_bootstrap_list() -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.bootstrap_dev import SECRET_NAMES

    for role in Role:
        assert settings.secret_name(role) in SECRET_NAMES

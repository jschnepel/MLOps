"""The worker's start-up relation checks (T19; revision 0014), without a database.

Catches: the worker starting on a database that lacks `app.run_manifests`, which would claim jobs it could not
record a manifest for, or `checkpoints.checkpoints` (revision 0015, T20), whose graph could not persist. The check is
read off the order of `assert_relation` calls, stopped at the checkpoint table, the last one asked for; and an unset
MODEL_MODE ending in a traceback instead of the logged refusal to start.
"""

from types import SimpleNamespace
from typing import Any

import pytest
from ops_core import persistence
from ops_core.settings import SettingsError
from ops_worker import main


class Stop(Exception):
    """Raised by the stub at the manifest relation so `_main` goes no further."""


@pytest.mark.asyncio
async def test_the_worker_asks_for_the_manifest_table_before_it_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = []

    async def start_route(mode: str | None) -> object:
        return object()

    async def connect(_: object) -> SimpleNamespace:
        return SimpleNamespace(execute=_noop)

    async def _noop(*_: Any) -> None:
        return None

    async def assert_relation(_: object, name: str) -> None:
        asked.append(name)
        if name == "checkpoints.checkpoints":
            raise Stop

    fake_settings = SimpleNamespace(
        env=lambda _: "fake",
        leases=lambda: None,
        keycloak=lambda: None,
        app_postgres=lambda _: None,
        profile=lambda: None,
    )
    monkeypatch.setattr(main, "start_route", start_route)
    monkeypatch.setattr(main, "settings", fake_settings)
    monkeypatch.setattr(main, "token_source", lambda _: None)
    monkeypatch.setattr(main.redaction, "install", lambda: None)  # leave the root logger's handlers alone
    monkeypatch.setattr(persistence, "connect", connect)
    monkeypatch.setattr(persistence, "assert_clock_profile", _noop)
    monkeypatch.setattr(persistence, "assert_relation", assert_relation)
    with pytest.raises(Stop):
        await main._main()
    assert asked == ["app.model_permit", "app.run_manifests", "checkpoints.checkpoints"]


@pytest.mark.asyncio
async def test_an_unset_model_mode_refuses_to_start_through_the_logged_exit(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """R130: no MODEL_MODE is the same clean exit as any route that cannot start, not a SettingsError traceback."""

    def env(name: str) -> str:
        raise SettingsError(f"{name} is not set")

    monkeypatch.setattr(main, "settings", SimpleNamespace(env=env))
    monkeypatch.setattr(main.redaction, "install", lambda: None)
    with pytest.raises(SystemExit) as stopped:
        await main._main()
    assert stopped.value.code == 1 and "MODEL_MODE is not set" in caplog.text

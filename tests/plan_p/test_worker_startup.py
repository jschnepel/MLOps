"""The worker's start-up relation checks (T19; revision 0014), without a database.

Catches: the worker starting on a database that lacks `app.run_manifests`, which would claim jobs it could not
record a manifest for. The check is read off the order of `assert_relation` calls, stopped at the manifest table.
"""

from types import SimpleNamespace
from typing import Any

import pytest
from ops_core import persistence
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
        if name == "app.run_manifests":
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
    assert asked == ["app.model_permit", "app.run_manifests"]

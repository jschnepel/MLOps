"""The T14 settings (Plan I rulings 8, 15, 16 and 20): the outbox's lease, batch, backoff and dead-letter attempt,
the wake-up sweep's grace and re-arm cap, and how long finished maintenance rows are kept, each read and bounded
(BS:542 "validated configuration").

Catches: a default that drifts from the ruled value, a variable read without its bounds (a zero lease would re-claim
a row while its delivery is still in flight; a zero grace would re-arm a wake-up the worker is about to consume), a
refusal that prints the value instead of the rule, and a backoff cap below its base (every retry would wait the cap).
"""

import pytest
from ops_core import settings
from ops_core.settings import OutboxSettings, SettingsError, WakeupSettings

NAMES = (
    "OPS_OUTBOX_LEASE_SECONDS",
    "OPS_OUTBOX_BATCH",
    "OPS_OUTBOX_BACKOFF_BASE_SECONDS",
    "OPS_OUTBOX_BACKOFF_CAP_SECONDS",
    "OPS_OUTBOX_MAX_ATTEMPTS",
    "OPS_WAKEUP_GRACE_SECONDS",
    "OPS_WAKEUP_MAX_ATTEMPTS",
    "OPS_MAINTENANCE_RETENTION_HOURS",
)


@pytest.fixture(autouse=True)
def clean(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in NAMES:
        monkeypatch.delenv(name, raising=False)


def test_the_defaults_are_the_ruled_values() -> None:
    assert settings.outbox() == OutboxSettings(
        lease_seconds=30, batch=10, backoff_base_seconds=2, backoff_cap_seconds=300, max_attempts=5
    )
    assert settings.wakeups() == WakeupSettings(grace_seconds=60, max_attempts=10, maintenance_retention_hours=24)
    assert OutboxSettings() == settings.outbox() and WakeupSettings() == settings.wakeups()


@pytest.mark.parametrize(
    ("name", "low", "high", "read"),
    [
        ("OPS_OUTBOX_LEASE_SECONDS", 5, 3600, "outbox"),
        ("OPS_OUTBOX_BATCH", 1, 1000, "outbox"),
        ("OPS_OUTBOX_BACKOFF_BASE_SECONDS", 1, 3600, "outbox"),
        ("OPS_OUTBOX_BACKOFF_CAP_SECONDS", 2, 86400, "outbox"),
        ("OPS_OUTBOX_MAX_ATTEMPTS", 1, 100, "outbox"),
        ("OPS_WAKEUP_GRACE_SECONDS", 10, 86400, "wakeups"),
        ("OPS_WAKEUP_MAX_ATTEMPTS", 1, 1000, "wakeups"),
        ("OPS_MAINTENANCE_RETENTION_HOURS", 1, 8760, "wakeups"),
    ],
)
def test_each_variable_is_read_and_bounded(
    monkeypatch: pytest.MonkeyPatch, name: str, low: int, high: int, read: str
) -> None:
    field = name.removeprefix("OPS_OUTBOX_").removeprefix("OPS_WAKEUP_").removeprefix("OPS_").lower()
    if name == "OPS_OUTBOX_BACKOFF_BASE_SECONDS":
        monkeypatch.setenv("OPS_OUTBOX_BACKOFF_CAP_SECONDS", "86400")  # the cap may not sit below the base
    for value in (low, high):
        monkeypatch.setenv(name, str(value))
        assert getattr(getattr(settings, read)(), field) == value
    for value in (low - 1, high + 1):
        monkeypatch.setenv(name, str(value))
        with pytest.raises(SettingsError) as refused:
            getattr(settings, read)()
        assert str(refused.value) == f"{name} must be between {low} and {high}"  # the bounds, never the value


def test_a_cap_below_the_base_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_OUTBOX_BACKOFF_BASE_SECONDS", "60")
    monkeypatch.setenv("OPS_OUTBOX_BACKOFF_CAP_SECONDS", "30")
    with pytest.raises(SettingsError) as refused:
        settings.outbox()
    assert str(refused.value) == "OPS_OUTBOX_BACKOFF_CAP_SECONDS must be at least OPS_OUTBOX_BACKOFF_BASE_SECONDS"

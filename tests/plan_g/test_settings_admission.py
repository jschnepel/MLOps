"""The T12 admission settings (Plan G ruling 27): BUILD_SPEC §17's starting defaults, each environment variable read
and held inside its bounds (BS:542 "validated configuration").

Catches: a body limit of zero or a gigabyte, a replay window shorter than a client's retry or longer than a week,
a quota that admits nothing, a non-integer read as a default, and key bounds that drift from the documented 8-128.
"""

import pytest
from ops_core import settings
from ops_core.settings import AdmissionSettings, SettingsError

NAMES = ("OPS_MAX_BODY_BYTES", "OPS_IDEMPOTENCY_TTL_SECONDS", "OPS_TENANT_QUEUE_QUOTA")


@pytest.fixture(autouse=True)
def clean(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in NAMES:
        monkeypatch.delenv(name, raising=False)


def test_defaults_are_the_spec_starting_values() -> None:
    assert settings.admission() == AdmissionSettings(
        max_body_bytes=65536,
        idempotency_ttl_seconds=86400,
        idempotency_key_min=8,
        idempotency_key_max=128,
        tenant_queue_quota=100,
    )
    assert AdmissionSettings() == settings.admission()  # what create_app uses when a test passes nothing


@pytest.mark.parametrize(
    ("name", "field", "low", "high"),
    [
        ("OPS_MAX_BODY_BYTES", "max_body_bytes", 1024, 1048576),
        ("OPS_IDEMPOTENCY_TTL_SECONDS", "idempotency_ttl_seconds", 60, 604800),
        ("OPS_TENANT_QUEUE_QUOTA", "tenant_queue_quota", 1, 10000),
    ],
)
def test_each_variable_is_read_and_bounded(
    monkeypatch: pytest.MonkeyPatch, name: str, field: str, low: int, high: int
) -> None:
    for good in (low, high):
        monkeypatch.setenv(name, str(good))
        assert getattr(settings.admission(), field) == good
    for bad in (low - 1, high + 1):
        monkeypatch.setenv(name, str(bad))
        with pytest.raises(SettingsError) as refused:
            settings.admission()
        assert str(refused.value) == f"{name} must be between {low} and {high}"  # the bounds, never the value


def test_a_non_integer_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_MAX_BODY_BYTES", "64KiB")
    with pytest.raises(SettingsError):
        settings.admission()

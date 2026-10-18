"""The T13 settings (Plan H rulings 13 and 20): BUILD_SPEC §17's lease and heartbeat (30 s / 10 s), the stall gate
above DoD 3's 25 s blocked loop, the 90 s compute budget and the 100-run global queue bound, each read, bounded and
checked together (BS:542 "validated configuration").

Catches: a heartbeat that leaves room for only one renewal per lease once the 5 s local-deadline margin and the
thread's 1 s tick are counted (one slow renewal would lose it), a stall gate
so long that a dead loop keeps a run, a budget shorter than one lease (every job would end before its first renewal),
a bound that names the value instead of the rule, and a slow live test that the gate silently stops running.
"""

import tomllib
from pathlib import Path

import pytest
from ops_core import settings
from ops_core.settings import LeaseSettings, SettingsError

ROOT = Path(__file__).resolve().parents[2]
NAMES = (
    "OPS_LEASE_SECONDS",
    "OPS_HEARTBEAT_SECONDS",
    "OPS_LOOP_STALL_SECONDS",
    "OPS_COMPUTE_BUDGET_SECONDS",
    "OPS_GLOBAL_QUEUE_LIMIT",
)


@pytest.fixture(autouse=True)
def clean(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in NAMES:
        monkeypatch.delenv(name, raising=False)


def test_lease_defaults_are_the_spec_values() -> None:
    assert settings.leases() == LeaseSettings(
        lease_seconds=30, heartbeat_seconds=10, loop_stall_seconds=28, compute_budget_seconds=90
    )
    assert LeaseSettings() == settings.leases()  # what a test's Deps uses when it passes nothing
    assert settings.leases().loop_stall_seconds > 25  # DoD 3: a 25 s blocked loop must not close the gate


@pytest.mark.parametrize(
    ("name", "low", "high", "with_low", "with_high"),
    [
        (
            "OPS_LEASE_SECONDS",
            10,
            900,
            {"OPS_HEARTBEAT_SECONDS": "1", "OPS_LOOP_STALL_SECONDS": "5", "OPS_COMPUTE_BUDGET_SECONDS": "10"},
            {"OPS_COMPUTE_BUDGET_SECONDS": "900"},
        ),
        ("OPS_HEARTBEAT_SECONDS", 1, 300, {}, {"OPS_LEASE_SECONDS": "900", "OPS_COMPUTE_BUDGET_SECONDS": "900"}),
        ("OPS_LOOP_STALL_SECONDS", 2, 900, {}, {"OPS_LEASE_SECONDS": "900", "OPS_COMPUTE_BUDGET_SECONDS": "900"}),
        (
            "OPS_COMPUTE_BUDGET_SECONDS",
            10,
            3600,
            {"OPS_LEASE_SECONDS": "10", "OPS_HEARTBEAT_SECONDS": "1", "OPS_LOOP_STALL_SECONDS": "5"},
            {},
        ),
    ],
)
def test_each_lease_variable_is_read_and_bounded(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    low: int,
    high: int,
    with_low: dict[str, str],
    with_high: dict[str, str],
) -> None:
    field = name.removeprefix("OPS_").lower()
    for value, companions in ((low, with_low), (high, with_high)):
        for other in NAMES:
            monkeypatch.delenv(other, raising=False)
        for other, raw in companions.items():
            monkeypatch.setenv(other, raw)
        monkeypatch.setenv(name, str(value))
        assert getattr(settings.leases(), field) == value
        monkeypatch.setenv(name, str(value - 1 if value == low else value + 1))
        with pytest.raises(SettingsError) as refused:
            settings.leases()
        assert str(refused.value) == f"{name} must be between {low} and {high}"  # the bounds, never the value


@pytest.mark.parametrize(
    ("name", "raw", "rule"),
    [
        ("OPS_HEARTBEAT_SECONDS", "12", "less than half of (OPS_LEASE_SECONDS - 6)"),
        ("OPS_LOOP_STALL_SECONDS", "40", "less than OPS_LEASE_SECONDS plus OPS_HEARTBEAT_SECONDS"),
        ("OPS_COMPUTE_BUDGET_SECONDS", "20", "at least OPS_LEASE_SECONDS"),
    ],
)
def test_unsafe_combinations_are_refused(monkeypatch: pytest.MonkeyPatch, name: str, raw: str, rule: str) -> None:
    monkeypatch.setenv(name, raw)
    with pytest.raises(SettingsError) as refused:
        settings.leases()
    assert str(refused.value) == f"{name} must be {rule}"


def test_two_renewals_and_the_margins_fit_in_one_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review round 1, I5: the local deadline is the last renewal's start plus the lease minus 5 s (SA:195) and the
    thread looks once a second, so a lease must hold two heartbeats plus 6 s, or one slow renewal loses it."""
    monkeypatch.setenv("OPS_LEASE_SECONDS", "30")
    monkeypatch.setenv("OPS_HEARTBEAT_SECONDS", "10")
    assert settings.leases().heartbeat_seconds == 10  # 2 x 10 + 6 < 30
    monkeypatch.setenv("OPS_LEASE_SECONDS", "10")
    monkeypatch.setenv("OPS_HEARTBEAT_SECONDS", "4")
    monkeypatch.setenv("OPS_LOOP_STALL_SECONDS", "5")
    monkeypatch.setenv("OPS_COMPUTE_BUDGET_SECONDS", "10")
    with pytest.raises(SettingsError) as refused:  # 2 x 4 + 6 >= 10: the old "less than half" rule let this through
        settings.leases()
    assert str(refused.value) == "OPS_HEARTBEAT_SECONDS must be less than half of (OPS_LEASE_SECONDS - 6)"


def test_the_global_queue_limit_is_read_and_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    assert settings.admission().global_queue_limit == 100  # BS:550: "100 total initially"
    for good in (1, 100000):
        monkeypatch.setenv("OPS_GLOBAL_QUEUE_LIMIT", str(good))
        assert settings.admission().global_queue_limit == good
    for bad in (0, 100001):
        monkeypatch.setenv("OPS_GLOBAL_QUEUE_LIMIT", str(bad))
        with pytest.raises(SettingsError):
            settings.admission()


def test_the_slow_live_marker_is_registered_and_the_live_gate_runs_every_test() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert any(m.startswith("slow_live:") for m in config["tool"]["pytest"]["ini_options"]["markers"])
    steps = (ROOT / "scripts" / "check.py").read_text(encoding="utf-8")
    # check.py's pytest step selects nothing out: the slow DoD tests run in `--profile test` like every live test.
    assert '"-m", "pytest", "-q"]' in steps and "not slow_live" not in steps

"""`check.py --profile test` is this repository's reading of SA:529: the same four steps, with the live suite enabled
(the e2e fixture applies the testclock branch to the per-session databases). Dev stays database-free."""

import sys
from pathlib import Path

import pytest
from ops_core.settings import Profile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.check import check_profile, environment_for


def test_profile_argument() -> None:
    """Dev is the default, test is accepted, and anything else (including prod) exits."""
    assert check_profile([]) is Profile.DEV
    assert check_profile(["--profile", "test"]) is Profile.TEST
    with pytest.raises(SystemExit):
        check_profile(["--profile", "prod"])


def test_test_profile_turns_the_live_suite_on() -> None:
    """Only the test profile sets OPS_LIVE; the base environment is carried through."""
    env = environment_for(Profile.TEST, {"PATH": "x"})
    assert env["OPS_LIVE"] == "1" and env["PROFILE"] == "test" and env["PATH"] == "x"
    assert "OPS_LIVE" not in environment_for(Profile.DEV, {"PATH": "x"})

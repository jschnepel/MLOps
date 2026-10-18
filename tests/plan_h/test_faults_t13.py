"""The fault factory after T13 (Plan H ruling 22, BS:405, R098): nine phrases, eight hooks and one harness behaviour,
a duration only where a duration means something, and still no factory outside the test profile.

Catches: a BS:405 fault with neither a hook nor a stated harness, a hook no phrase names, a `seconds` silently accepted
for a kind that ignores it, and a factory that starts in dev or demo.
"""

import pytest
from ops_core.settings import Profile
from ops_core.testing.faults import (
    ASSET_SIM_FAULTS,
    BS405,
    DEFAULT_SECONDS,
    SWEEPER_FAULTS,
    FaultKind,
    Faults,
    FaultsDisabled,
)


def test_every_bs405_phrase_maps_to_one_kind_or_the_harness() -> None:
    assert len(BS405) == 9  # BS:405 names nine
    kinds = [kind for kind in BS405.values() if kind is not None]
    # One hook each, and no orphan hook: every kind outside BS:405 is the sweeper's outbox sink fault (T14) or
    # asset-sim's `unavailable` state (T16).
    assert len(kinds) == len(set(kinds)) and set(kinds) == set(FaultKind) - SWEEPER_FAULTS - ASSET_SIM_FAULTS
    assert [phrase for phrase, kind in BS405.items() if kind is None] == ["concurrent same-key submission"]


def test_seconds_belongs_to_timeout_before_accept_only() -> None:
    faults = Faults(Profile.TEST)
    assert faults.seconds(FaultKind.TIMEOUT_BEFORE_ACCEPT) == DEFAULT_SECONDS
    faults.arm(FaultKind.TIMEOUT_BEFORE_ACCEPT, seconds=3)
    assert faults.seconds(FaultKind.TIMEOUT_BEFORE_ACCEPT) == 3 and faults.take(FaultKind.TIMEOUT_BEFORE_ACCEPT)
    for kind, seconds in ((FaultKind.RATE_LIMIT, 3), (FaultKind.TIMEOUT_BEFORE_ACCEPT, 0)):
        with pytest.raises(ValueError):
            faults.arm(kind, seconds=seconds)
    assert faults.armed() == {}  # a refused arm arms nothing


@pytest.mark.parametrize("profile", [Profile.DEV, Profile.DEMO])
def test_the_factory_still_refuses_outside_the_test_profile(profile: Profile) -> None:
    with pytest.raises(FaultsDisabled):
        Faults(profile)

"""The fault factory refuses to exist outside the test profile (R098) and consumes one fault per take."""

import pytest
from ops_core.settings import Profile
from ops_core.testing.faults import FaultKind, Faults, FaultsDisabled


@pytest.mark.parametrize("profile", [Profile.DEV, Profile.DEMO])
def test_refuses_outside_the_test_profile(profile: Profile) -> None:
    with pytest.raises(FaultsDisabled):
        Faults(profile)


def test_arm_and_take() -> None:
    faults = Faults(Profile.TEST)
    assert faults.take(FaultKind.REJECT_NEXT) is False
    faults.arm(FaultKind.REJECT_NEXT, 2)
    assert faults.armed() == {"reject_next": 2}
    assert faults.take(FaultKind.REJECT_NEXT)
    assert faults.take(FaultKind.REJECT_NEXT)
    assert not faults.take(FaultKind.REJECT_NEXT)
    with pytest.raises(ValueError):
        faults.arm(FaultKind.LOSE_AFTER_COMMIT, 0)

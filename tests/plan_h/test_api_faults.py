"""The API's fault hooks after T13 (Plan H ruling 22; R015's after-commit side; R098): `lose_after_commit` commits the
unit and its record and loses only the answer, and the factory, not the lifespan, gives the store its faults.

Catches: a lost answer whose unit did not commit (a retry would then start a second run), a replay that is not the
recorded 202, a fault route reachable in dev or demo, faults built outside the test profile, and a store holding other
faults than the route arms (the route would arm what nothing consumes).
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from ops_api.app import create_app
from ops_core.settings import Profile
from ops_core.testing.faults import Faults

from tests.plan_f.auth_fakes import fake_auth
from tests.plan_g.fakes import FakeStore, StubVerifier
from tests.plan_g.test_store_units import SAMPLE


def h(key: str) -> dict[str, str]:
    return {"Authorization": "Bearer alex", "Idempotency-Key": key}


def app_for(fake: FakeStore, profile: Profile, faults: Faults | None) -> Any:
    return create_app(
        StubVerifier(), store_factory=lambda: fake, auth_factory=fake_auth, profile=profile, faults=faults
    )


def test_lose_after_commit_answers_503_and_the_replay_returns_the_recorded_202() -> None:
    fake = FakeStore()
    fake.faults = Faults(Profile.TEST)  # what the factory gives the store
    with TestClient(app_for(fake, Profile.TEST, fake.faults)) as c:
        cid = c.post("/api/v1/conversations", headers=h("conv-key-01")).json()["conversation_id"]
        armed = c.post("/internal/faults/lose_after_commit", headers=h("arm-key-01"), json={"count": 1})
        assert armed.status_code == 200 and armed.json() == {"armed": {"lose_after_commit": 1}}
        lost = c.post(f"/api/v1/conversations/{cid}/messages", headers=h("key-lost-01"), json=SAMPLE)
        assert lost.status_code == 503 and lost.json()["retryable"] is True
        assert lost.json()["message"] == "database unavailable"  # what a connection lost after COMMIT looks like
        assert len(fake.runs) == 1 and len(fake.jobs) == 1  # the unit committed, its record included
        replay = c.post(f"/api/v1/conversations/{cid}/messages", headers=h("key-lost-01"), json=SAMPLE)
        assert replay.status_code == 202 and replay.json()["run_id"] == str(next(iter(fake.runs)))
        assert len(fake.runs) == 1  # R015: the retry replays, it does not start a second run


@pytest.mark.parametrize("profile", [Profile.DEV, Profile.DEMO])
def test_the_fault_route_does_not_exist_outside_the_test_profile(profile: Profile) -> None:
    with TestClient(app_for(FakeStore(), profile, None)) as c:
        r = c.post("/internal/faults/lose_after_commit", headers=h("arm-key-02"), json={"count": 1})
        assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"


def test_faults_belong_to_the_test_profile_and_only_to_it() -> None:
    with pytest.raises(ValueError):
        app_for(FakeStore(), Profile.DEV, Faults(Profile.TEST))
    with pytest.raises(ValueError):
        app_for(FakeStore(), Profile.TEST, None)


def test_the_store_must_hold_the_apps_faults() -> None:
    fake = FakeStore()
    fake.faults = Faults(Profile.TEST)  # another object than the app's
    with pytest.raises(RuntimeError), TestClient(app_for(fake, Profile.TEST, Faults(Profile.TEST))):
        pass

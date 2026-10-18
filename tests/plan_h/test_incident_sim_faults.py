"""incident-sim's five new fault hooks (Plan H ruling 22; BS:405; R098) through the app with the in-memory key table:
where each one acts, what it writes, and that none exists outside the test profile.

Catches: a timeout or a rate limit that writes a key (the destination must not have accepted anything), a malformed
or hash-mismatched answer whose key did not commit (the faults corrupt the answer, never the truth), a delayed
receipt that hides the key for ever or not at all, a 429 not marked retryable, a `seconds` armed on a kind without a
duration, and a hook reachable in dev or demo.
"""

import time
from uuid import uuid4

import pytest
from ops_core.settings import Profile

from tests.plan_d.test_incident_sim import PAYLOAD, SHA, body_for
from tests.plan_e.test_incident_sim_t10 import auth, make


def test_timeout_before_accept_holds_then_answers_503_and_writes_nothing() -> None:
    c, store = make(Profile.TEST)
    with c:
        armed = c.post("/internal/faults/timeout_before_accept", json={"count": 1, "seconds": 1}, headers=auth())
        assert armed.json() == {"armed": {"timeout_before_accept": 1}}
        action = uuid4()
        started = time.monotonic()
        r = c.post("/internal/incidents", json=body_for(PAYLOAD, action=action), headers=auth())
        assert r.status_code == 503 and r.json()["code"] == "UNAVAILABLE" and time.monotonic() - started >= 1.0
        assert action not in store.rows


def test_rate_limit_is_a_retryable_429_and_writes_nothing() -> None:
    c, store = make(Profile.TEST)
    with c:
        refused = c.post("/internal/faults/rate_limit", json={"count": 1, "seconds": 3}, headers=auth())
        assert refused.status_code == 422  # seconds belongs to timeout_before_accept only
        c.post("/internal/faults/rate_limit", json={"count": 1}, headers=auth())
        action = uuid4()
        r = c.post("/internal/incidents", json=body_for(PAYLOAD, action=action), headers=auth())
        assert r.status_code == 429 and r.headers["Retry-After"] == "1"
        assert (r.json()["code"], r.json()["retryable"]) == ("RATE_LIMITED", True) and action not in store.rows
        again = c.post("/internal/incidents", json=body_for(PAYLOAD, action=action), headers=auth())
        assert again.json()["state"] == "COMMITTED"  # one fault, one request


def test_a_malformed_response_follows_a_real_commit() -> None:
    c, store = make(Profile.TEST)
    with c:
        c.post("/internal/faults/malformed_response", json={"count": 1}, headers=auth())
        action = uuid4()
        r = c.post("/internal/incidents", json=body_for(PAYLOAD, action=action), headers=auth())
        assert r.status_code == 200 and not isinstance(r.json().get("receipt"), dict)  # no receipt shape
        assert store.rows[action].state == "COMMITTED"
        assert c.get(f"/internal/actions/{action}", headers=auth()).json()["receipt"]["incident_id"]  # truth stands


def test_a_receipt_hash_mismatch_follows_a_real_commit() -> None:
    c, store = make(Profile.TEST)
    with c:
        c.post("/internal/faults/receipt_hash_mismatch", json={"count": 1}, headers=auth())
        action = uuid4()
        r = c.post("/internal/incidents", json=body_for(PAYLOAD, action=action), headers=auth())
        assert r.status_code == 200 and r.json()["state"] == "COMMITTED" and r.json()["payload_sha256"] != SHA
        assert store.rows[action].payload_sha256 == SHA
        assert c.get(f"/internal/actions/{action}", headers=auth()).json()["payload_sha256"] == SHA


def test_a_delayed_receipt_is_hidden_for_count_lookups_then_visible() -> None:
    c, _ = make(Profile.TEST)
    with c:
        action = uuid4()
        assert c.post("/internal/incidents", json=body_for(PAYLOAD, action=action), headers=auth()).status_code == 200
        c.post("/internal/faults/delay_receipt", json={"count": 2}, headers=auth())
        statuses = [c.get(f"/internal/actions/{action}", headers=auth()).status_code for _ in range(3)]
        assert statuses == [404, 404, 200]


@pytest.mark.parametrize("profile", [Profile.DEV, Profile.DEMO])
def test_the_new_hooks_do_not_exist_outside_the_test_profile(profile: Profile) -> None:
    c, _ = make(profile)
    with c:
        for kind in ("timeout_before_accept", "rate_limit", "malformed_response", "delay_receipt"):
            assert c.post(f"/internal/faults/{kind}", json={"count": 1}, headers=auth()).status_code == 404

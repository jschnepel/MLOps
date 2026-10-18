"""incident-sim after T10 without a database: abort tombstones, permanent REJECTED keys for a hash mismatch or a
non-object payload, POST and abort onto any tombstone returning that tombstone, 403 for the wrong audience, and the
fault hooks present only under the test profile (SA:259-269, R096, R098).
"""

from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from ops_core.canonical import sha256_hex
from ops_core.settings import Profile
from ops_core.testing.faults import Faults
from ops_core.tokens import Principal, TokenRejected, WrongAudience
from ops_incident_sim.app import create_app

from tests.plan_d.test_incident_sim import ACTION, PAYLOAD, SHA, FakeStore, body_for


class Verifier:
    ready = True

    async def load_keys(self) -> None:
        return None

    async def verify_async(self, token: str) -> Principal:
        if token == "wrong-audience":
            raise WrongAudience("another server's token")
        if token != "good":
            raise TokenRejected("nope")
        return Principal(subject="sa", azp="ops-mcp-write", audiences=("incident-sim",), expires_at=2**31, claims={})


def make(profile: Profile = Profile.DEV) -> tuple[TestClient, FakeStore]:
    store = FakeStore()
    faults = Faults(profile) if profile is Profile.TEST else None
    app = create_app(Verifier(), store=store, profile=profile, faults=faults)
    return TestClient(app), store


def auth(token: str = "good") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_wrong_audience_is_403_without_an_action_id() -> None:
    with make()[0] as c:
        r = c.post("/internal/incidents", json=body_for(PAYLOAD), headers=auth("wrong-audience"))
        assert r.status_code == 403 and r.json()["code"] == "FORBIDDEN" and str(ACTION) not in r.text
        assert c.post("/internal/incidents", json=body_for(PAYLOAD), headers=auth("bad")).status_code == 401


def test_abort_then_post_returns_the_tombstone_whatever_the_hash() -> None:
    c, store = make()
    with c:
        path = f"/internal/actions/{ACTION}/abort"
        r = c.post(path, json={"payload_sha256": SHA, "reason": "expired"}, headers=auth())
        assert r.status_code == 200 and r.json()["state"] == "ABORTED"
        stamp = r.json()["tombstone"]["decided_at"]
        assert r.json()["tombstone"] == {
            "action_id": str(ACTION),
            "state": "ABORTED",
            "payload_sha256": SHA,
            "reason": "expired",
            "decided_at": stamp,
        }
        late = c.post("/internal/incidents", json=body_for(PAYLOAD), headers=auth())
        assert late.status_code == 200 and late.json()["state"] == "ABORTED" and "receipt" not in late.json()
        other_hash = c.post("/internal/incidents", json=body_for({"x": 1}, action=ACTION), headers=auth())
        assert other_hash.status_code == 200 and other_hash.json()["state"] == "ABORTED"  # SA:267: never CONFLICT
        again = c.post(path, json={"payload_sha256": "0" * 64, "reason": "deadline"}, headers=auth())
        assert again.json()["tombstone"]["reason"] == "expired"  # the first tombstone stands
        assert store.rows[ACTION].state == "ABORTED" and not any(r.state == "COMMITTED" for r in store.rows.values())


def test_abort_after_commit_returns_the_receipt() -> None:
    c, _ = make()
    with c:
        path = f"/internal/actions/{ACTION}/abort"
        first = c.post("/internal/incidents", json=body_for(PAYLOAD), headers=auth()).json()
        r = c.post(path, json={"payload_sha256": SHA, "reason": "cancelled_before_send"}, headers=auth())
        assert r.status_code == 200 and r.json()["state"] == "COMMITTED" and r.json()["receipt"] == first["receipt"]
        conflict = c.post(path, json={"payload_sha256": "0" * 64, "reason": "expired"}, headers=auth())
        assert conflict.status_code == 409 and conflict.json()["state"] == "CONFLICT"


def test_bad_reason_is_422_and_no_key() -> None:
    c, store = make()
    with c:
        path = f"/internal/actions/{ACTION}/abort"
        r = c.post(path, json={"payload_sha256": SHA, "reason": "because"}, headers=auth())
        assert r.status_code == 422 and store.rows == {}


def test_hash_mismatch_and_non_object_payload_write_permanent_rejections() -> None:
    c, store = make()
    with c:
        r = c.post("/internal/incidents", json=body_for(PAYLOAD, sha="0" * 64), headers=auth())
        assert r.status_code == 200 and r.json()["state"] == "REJECTED"
        assert r.json()["tombstone"]["reason"] == "hash_mismatch"
        assert store.rows[ACTION].state == "REJECTED" and store.commits == []
        good = c.post("/internal/incidents", json=body_for(PAYLOAD), headers=auth())
        assert good.json()["state"] == "REJECTED"  # permanent: the right bytes later still get the tombstone
        other = uuid4()
        body = body_for(PAYLOAD, action=other)
        body["payload_canonical"] = "[1, 2]"
        body["payload_sha256"] = sha256_hex(b"[1, 2]")
        r = c.post("/internal/incidents", json=body, headers=auth())
        assert r.status_code == 200 and r.json()["tombstone"]["reason"] == "invalid_payload"
        abort_body: dict[str, Any] = {"payload_sha256": "0" * 64, "reason": "expired"}
        abort = c.post(f"/internal/actions/{other}/abort", json=abort_body, headers=auth())
        assert abort.json()["state"] == "REJECTED"  # abort onto REJECTED returns the REJECTED tombstone (SA:267)
        assert c.post("/internal/incidents", content=b"not json", headers=auth()).status_code == 422  # no envelope


def test_fault_hooks_exist_only_in_the_test_profile() -> None:
    with make(Profile.DEV)[0] as c:
        assert c.post("/internal/faults/reject_next", json={"count": 1}, headers=auth()).status_code == 404
    c, store = make(Profile.TEST)
    with c:
        assert c.post("/internal/faults/reject_next", json={"count": 1}, headers=auth("bad")).status_code == 401
        assert c.post("/internal/faults/nope", json={"count": 1}, headers=auth()).status_code == 422
        armed = c.post("/internal/faults/reject_next", json={"count": 1}, headers=auth())
        assert armed.json() == {"armed": {"reject_next": 1}}
        r = c.post("/internal/incidents", json=body_for(PAYLOAD), headers=auth())
        assert r.json()["state"] == "REJECTED" and r.json()["tombstone"]["reason"] == "policy"
        committed = c.post("/internal/incidents", json=body_for(PAYLOAD, action=uuid4()), headers=auth())
        assert committed.json()["state"] == "COMMITTED"
        c.post("/internal/faults/drop_before_commit", json={"count": 1}, headers=auth())
        dropped = uuid4()
        assert c.post("/internal/incidents", json=body_for(PAYLOAD, action=dropped), headers=auth()).status_code == 503
        assert dropped not in store.rows
        c.post("/internal/faults/lose_after_commit", json={"count": 1}, headers=auth())
        lost = uuid4()
        assert c.post("/internal/incidents", json=body_for(PAYLOAD, action=lost), headers=auth()).status_code == 503
        assert store.rows[lost].state == "COMMITTED"  # a lookup recovers what the lost response hid
        assert c.get(f"/internal/actions/{lost}", headers=auth()).json()["state"] == "COMMITTED"

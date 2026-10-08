"""incident-sim's contract without a database (AM-13 §4 destination rules, BUILD_SPEC §14): hash recomputed over the
received bytes, same key + same hash → the existing receipt, same key + different hash → CONFLICT (never a second
incident), an unauthenticated call → a plain safe error with no action_id, and the document shapes T10 extends.

Catches: trusting the caller's hash (SA:268), a conflict that creates a second incident, a 401 body that leaks the
action id (SA:357), and a tombstone presented as a receipt.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from ops_core.canonical import canonical_json, canonical_sha256, sha256_hex
from ops_core.tokens import Principal, TokenRejected
from ops_incident_sim import keys
from ops_incident_sim.app import create_app

ACTION = UUID(int=7)
PAYLOAD = {"title": "Synthetic incident", "asset_id": "A17", "revision": 1}
SHA = canonical_sha256(PAYLOAD)
AT = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def row(**over: Any) -> keys.KeyRow:
    base: dict[str, Any] = {
        "action_id": ACTION,
        "payload_sha256": SHA,
        "state": "COMMITTED",
        "incident_id": "INC-000001",
        "reason": None,
        "receipt_id": UUID(int=9),
        "decided_at": AT,
    }
    base.update(over)
    return keys.KeyRow(**base)


def test_document_shapes():
    status, doc = keys.document(row(), presented_sha256=SHA)
    assert (
        status == 200
        and doc["state"] == "COMMITTED"
        and doc["receipt"]
        == {"receipt_id": str(UUID(int=9)), "incident_id": "INC-000001", "committed_at": "2026-10-08T12:00:00Z"}
    )
    status, doc = keys.document(row(), presented_sha256="0" * 64)
    assert status == 409 and doc == {"state": "CONFLICT", "action_id": str(ACTION), "payload_sha256": SHA}
    status, doc = keys.document(row(state="REJECTED", incident_id=None, reason="policy"), presented_sha256=SHA)
    assert status == 200 and "receipt" not in doc and doc["tombstone"]["state"] == "REJECTED"
    assert doc["tombstone"]["reason"] == "policy" and doc["tombstone"]["decided_at"] == "2026-10-08T12:00:00Z"


class StubVerifier:
    @property
    def ready(self) -> bool:
        return True

    async def load_keys(self) -> None:
        return None

    async def verify_async(self, token: str) -> Principal:
        if token != "good":
            raise TokenRejected("nope")
        return Principal(subject="sa", azp="ops-mcp-write", audiences=("incident-sim",), expires_at=2**31, claims={})


class FakeStore:
    """The key table in memory, with the same first-writer-wins contract as keys.commit."""

    def __init__(self) -> None:
        self.rows: dict[UUID, keys.KeyRow] = {}
        self.commits: list[tuple[UUID, str]] = []

    async def commit(self, action_id: UUID, payload_sha256: str, payload: dict[str, Any]) -> keys.KeyRow:
        self.commits.append((action_id, payload_sha256))
        if action_id not in self.rows:
            self.rows[action_id] = row(
                action_id=action_id,
                payload_sha256=payload_sha256,
                incident_id=f"INC-{len(self.rows) + 1:06d}",
                receipt_id=uuid4(),
            )
        return self.rows[action_id]

    async def lookup(self, action_id: UUID) -> keys.KeyRow | None:
        return self.rows.get(action_id)


@pytest.fixture
def client() -> Iterator[tuple[TestClient, FakeStore]]:
    store = FakeStore()
    app = create_app(StubVerifier(), store=store)
    with TestClient(app) as c:  # the context manager runs the lifespan, which installs the store
        yield c, store


def body_for(payload: dict[str, Any], *, sha: str | None = None, action: UUID = ACTION) -> dict[str, Any]:
    canonical = canonical_json(payload).decode("utf-8")
    return {
        "action_id": str(action),
        "payload_sha256": sha or sha256_hex(canonical.encode("utf-8")),
        "payload_canonical": canonical,
    }


def post(c: TestClient, body: dict[str, Any], token: str = "good"):
    return c.post(
        "/internal/incidents",
        content=canonical_json(body),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )


def test_commit_then_replay_returns_the_same_receipt(client):
    c, store = client
    first = post(c, body_for(PAYLOAD))
    assert first.status_code == 200 and first.json()["state"] == "COMMITTED"
    again = post(c, body_for(PAYLOAD))
    assert again.json() == first.json() and len(store.rows) == 1


def test_different_hash_under_an_existing_key_is_a_conflict_not_a_second_incident(client):
    c, store = client
    post(c, body_for(PAYLOAD))
    r = post(c, body_for({**PAYLOAD, "title": "Changed"}))
    assert r.status_code == 409 and r.json() == {"state": "CONFLICT", "action_id": str(ACTION), "payload_sha256": SHA}
    assert len(store.rows) == 1


def test_presented_hash_must_match_the_received_bytes(client):
    c, store = client
    r = post(c, body_for(PAYLOAD, sha="0" * 64))
    assert r.status_code == 422 and r.json()["code"] == "INVALID_INPUT"
    # The hash is over the bytes as received (SA:268): a re-serialisation that changes one byte is a mismatch.
    spaced = {
        "action_id": str(ACTION),
        "payload_sha256": SHA,
        "payload_canonical": '{"asset_id": "A17", "revision": 1, "title": "Synthetic incident"}',
    }
    assert post(c, spaced).status_code == 422
    assert store.commits == []  # refused before the key table is touched


def test_malformed_bodies_are_422(client):
    c, _ = client
    for body in (
        b"{",
        b'{"action_id": "x"}',
        b'{"action_id": "%s", "payload_sha256": "%s"}' % (str(ACTION).encode(), SHA.encode()),
        b'{"action_id": "%s", "payload_sha256": "%s", "payload_canonical": "[1]"}'
        % (str(ACTION).encode(), SHA.encode()),
    ):
        r = c.post(
            "/internal/incidents",
            content=body,
            headers={"Authorization": "Bearer good", "Content-Type": "application/json"},
        )
        assert r.status_code == 422, body
    dup = b'{"action_id": "%s", "action_id": "%s", "payload_sha256": "%s", "payload_canonical": "{}"}' % (
        str(ACTION).encode(),
        str(ACTION).encode(),
        SHA.encode(),
    )
    assert c.post("/internal/incidents", content=dup, headers={"Authorization": "Bearer good"}).status_code == 422


def test_unauthenticated_calls_get_a_plain_safe_error(client):
    c, store = client
    r = post(c, body_for(PAYLOAD), token="bad")
    assert r.status_code == 401 and r.json()["code"] == "UNAUTHENTICATED"
    assert str(ACTION) not in r.text and store.commits == []
    assert c.get(f"/internal/actions/{ACTION}").status_code == 401


def test_lookup(client):
    c, _ = client
    assert c.get(f"/internal/actions/{ACTION}", headers={"Authorization": "Bearer good"}).status_code == 404
    post(c, body_for(PAYLOAD))
    r = c.get(f"/internal/actions/{ACTION}", headers={"Authorization": "Bearer good"})
    assert r.status_code == 200 and r.json()["state"] == "COMMITTED"


def test_health(client):
    c, _ = client
    assert c.get("/health/live").json() == {"status": "live"}
    assert c.get("/health/ready").status_code == 200

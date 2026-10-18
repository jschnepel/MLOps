"""The API's authority rules without a database (BUILD_SPEC §7 admission, §12 independent decision, §9 identity).

Catches: a body that carries an authority field accepted (BUILD_SPEC §7: the server sets actor, tenant, roles), a
duplicate JSON key silently resolved, the requester approving their own proposal (SA:539), a reviewer from another
tenant seeing or deciding a proposal (404, not 403: existence is not disclosed), a decision on a stale hash accepted,
a second decision overwriting the first, and a run in another tenant readable by id. Since Plan G every mutation
here carries a fresh Idempotency-Key (`auth()` adds one) and the store is the shared fake of tests/plan_g/fakes.py.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from ops_api import store
from ops_api.app import create_app
from ops_core import persistence
from ops_core.tokens import Principal, TokenRejected

from tests.plan_f.auth_fakes import fake_auth
from tests.plan_g import fakes

ISSUER = "http://localhost:18080/realms/ops-dev"
ALPHA, BETA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7"), UUID("5ab45c2c-1e12-5a0c-a2b9-66cd2ff05201")
ALEX, SAM, LEE = (
    UUID("2fc05986-c7ec-544c-b628-fdb112bbf18a"),
    UUID("03f7eb09-e18d-5f33-bf75-12c57d5aaa54"),
    UUID("abcc1200-6791-57ab-87b5-9392d356b512"),
)
JORDAN = UUID("cb551e64-83ec-582b-9047-8dadf20e151a")
SHA = "9" * 64
PERSONAS = {"alex": ALEX, "sam": SAM, "lee": LEE, "jordan": JORDAN}
DUAL = UUID("11111111-2222-5333-8444-555555555555")  # a subject seeded in two tenants
PERSONAS["dual"] = DUAL
ROWS = {
    ALEX: [(ALPHA, "requester")],
    SAM: [(ALPHA, "reviewer")],
    LEE: [(ALPHA, "reader")],
    JORDAN: [(BETA, "reviewer")],
    DUAL: [(ALPHA, "requester"), (BETA, "reviewer")],
}
MEMBERS = {who: store.single_tenant(rows) for who, rows in ROWS.items()}


class StubVerifier:
    @property
    def ready(self) -> bool:
        return True

    async def load_keys(self) -> None:
        return None

    async def verify_async(self, token: str) -> Principal:
        if token == "badsub":
            return Principal(
                subject="not-a-uuid", azp="ops-dev-direct", audiences=("ops-api",), expires_at=2**31, claims={}
            )
        if token not in PERSONAS:
            raise TokenRejected("unit test")
        return Principal(
            subject=str(PERSONAS[token]),
            azp="ops-dev-direct",
            audiences=("ops-api",),
            expires_at=2**31,
            claims={"preferred_username": token},
        )


class FakeStore(fakes.FakeStore):
    """Plan D's name for the shared fake (Plan G Task 5): the real admission orchestration over in-memory tables, with
    membership read from this module's ROWS, which tests/plan_f/test_api_auth.py edits to stand in for the sync."""

    async def membership(self, issuer: str, subject: UUID) -> store.Membership | None:
        return store.single_tenant(ROWS.get(subject, [])) if issuer == ISSUER else None


@pytest.fixture
def api() -> Iterator[tuple[TestClient, FakeStore]]:
    fake = FakeStore()
    app = create_app(StubVerifier(), store_factory=lambda: fake, auth_factory=fake_auth)
    with TestClient(app) as c:  # the context manager runs the lifespan, which installs the store
        yield c, fake


def auth(name: str) -> dict[str, str]:
    """A persona's bearer header plus a fresh Idempotency-Key, so every mutation is a new request (BS:264)."""
    return {"Authorization": f"Bearer {name}", "Idempotency-Key": str(uuid4())}


def test_identity_and_membership(api):
    c, _ = api
    assert c.get("/api/v1/me").status_code == 401
    assert c.get("/api/v1/me", headers=auth("nobody")).status_code == 401
    me = c.get("/api/v1/me", headers=auth("alex")).json()
    assert me == {
        "subject": str(ALEX),
        "tenant_id": str(ALPHA),
        "roles": ["requester"],
        "username": "alex",
        "auth": "bearer",
    }


def test_a_subject_that_is_not_a_uuid_is_a_safe_401(api):
    c, _ = api
    r = c.get("/api/v1/me", headers=auth("badsub"))
    assert r.status_code == 401 and r.json()["code"] == "UNAUTHENTICATED"


def test_multi_tenant_subject_cannot_act_and_roles_do_not_merge(api):
    c, _ = api
    # no single current membership is no application identity (BUILD_SPEC §7: 401 for missing identity; SA:549)
    assert c.get("/api/v1/me", headers=auth("dual")).status_code == 401
    assert c.get("/api/v1/me", headers=auth("alex")).json()["roles"] == ["requester"]
    assert store.single_tenant([]) is None


def test_supersedes_run_must_be_in_the_same_conversation(api):
    c, fake = api
    cid = c.post("/api/v1/conversations", headers=auth("alex")).json()["conversation_id"]
    body = {"kind": "investigate", "text": "x", "context": {"asset_id": "A17", "hours": 2}}
    first = c.post(f"/api/v1/conversations/{cid}/messages", headers=auth("alex"), json=body).json()["run_id"]
    fake.runs[UUID(first)]["state"] = "FAILED"  # a run that ended frees the slot (since Plan G the router checks it)
    url = f"/api/v1/conversations/{cid}/messages"
    assert c.post(url, headers=auth("alex"), json={**body, "supersedes_run_id": str(uuid4())}).status_code == 404
    assert c.post(url, headers=auth("alex"), json={**body, "supersedes_run_id": first}).status_code == 202


def test_admission_validates_the_body_and_returns_202(api):
    c, fake = api
    cid = c.post("/api/v1/conversations", headers=auth("alex")).json()["conversation_id"]
    body = {
        "kind": "investigate",
        "text": "Investigate the alerts on A17 over the last 24 hours.",
        "context": {"asset_id": "A17", "hours": 24},
    }
    r = c.post(f"/api/v1/conversations/{cid}/messages", headers=auth("alex"), json=body)
    assert r.status_code == 202, r.text
    doc = r.json()
    assert doc["status"] == "QUEUED" and doc["state_version"] == 1 and doc["conversation_id"] == cid
    assert doc["status_url"] == f"/api/v1/runs/{doc['run_id']}" and doc["events_url"].endswith("/events")
    run = fake.runs[UUID(doc["run_id"])]
    assert run["end_at"] - run["start_at"] == timedelta(hours=24)
    assert run["end_at"].microsecond == 0 and run["end_at"].tzinfo is not None
    for bad in (
        {**body, "tenant_id": str(BETA)},  # authority field (BUILD_SPEC §7)
        {**body, "context": {"asset_id": "a17", "hours": 24}},  # AssetId pattern
    ):  # `ask` and a request without asset or window are routed since Plan G (tests/plan_g/test_api_admission.py)
        assert c.post(f"/api/v1/conversations/{cid}/messages", headers=auth("alex"), json=bad).status_code == 422, bad
    dup = '{"kind": "investigate", "kind": "ask", "text": "x", "context": {"asset_id": "A17", "hours": 1}}'
    r = c.post(
        f"/api/v1/conversations/{cid}/messages",
        headers={**auth("alex"), "Content-Type": "application/json"},
        content=dup,
    )
    assert r.status_code == 422 and r.json()["code"] == "INVALID_INPUT"
    assert c.post(f"/api/v1/conversations/{cid}/messages", headers=auth("sam"), json=body).status_code == 403
    assert c.post(f"/api/v1/conversations/{uuid4()}/messages", headers=auth("alex"), json=body).status_code == 404
    fake.slot_occupied = True
    r = c.post(f"/api/v1/conversations/{cid}/messages", headers=auth("alex"), json=body)
    assert r.status_code == 409 and r.json()["code"] == "SLOT_OCCUPIED"


def test_runs_are_tenant_scoped(api):
    c, _ = api
    cid = c.post("/api/v1/conversations", headers=auth("alex")).json()["conversation_id"]
    body = {"kind": "investigate", "text": "x", "context": {"asset_id": "A17", "hours": 2}}
    run_id = c.post(f"/api/v1/conversations/{cid}/messages", headers=auth("alex"), json=body).json()["run_id"]
    assert c.get(f"/api/v1/runs/{run_id}", headers=auth("alex")).json()["status"] == "QUEUED"
    assert c.get(f"/api/v1/runs/{run_id}", headers=auth("jordan")).status_code == 404
    assert c.get(f"/api/v1/runs/{run_id}/events", headers=auth("alex")).json() == {
        "events": [{"sequence": 1, "type": "run.accepted"}]
    }
    assert c.get(f"/api/v1/runs/{run_id}/events", headers=auth("jordan")).status_code == 404


def seed_proposal(fake: FakeStore, tenant: UUID = ALPHA) -> UUID:
    pid, rid = uuid4(), uuid4()
    fake.runs[rid] = {
        "run_id": rid,
        "tenant_id": tenant,
        "conversation_id": uuid4(),
        "requester": ALEX,
        "state": "AWAITING_APPROVAL",
        "state_version": 4,
        "active_proposal_id": pid,
        "asset_id": "A17",
        "start_at": datetime(2026, 10, 7, tzinfo=UTC),
        "end_at": datetime(2026, 10, 8, tzinfo=UTC),
        "created_at": datetime(2026, 10, 8, tzinfo=UTC),
    }
    fake.proposals[pid] = {
        "proposal_id": pid,
        "tenant_id": tenant,
        "run_id": rid,
        "revision": 1,
        "payload": {"k": 1},
        "payload_sha256": SHA,
        "authored_by": [ALEX],
        "requester": ALEX,
        "expires_at": datetime(2026, 10, 8, 12, 15, tzinfo=UTC),
    }
    return pid


def test_decision_requires_an_independent_current_reviewer(api):
    c, fake = api
    pid = seed_proposal(fake)
    body = {"expected_revision": 1, "expected_payload_sha256": SHA, "decision": "approve", "reason": "ok"}
    assert c.get(f"/api/v1/proposals/{pid}", headers=auth("sam")).json()["payload_sha256"] == SHA
    assert c.get(f"/api/v1/proposals/{pid}", headers=auth("jordan")).status_code == 404  # another tenant
    assert c.post(f"/api/v1/proposals/{pid}/decisions", headers=auth("alex"), json=body).status_code == 403  # self
    assert c.post(f"/api/v1/proposals/{pid}/decisions", headers=auth("lee"), json=body).status_code == 403  # reader
    assert c.post(f"/api/v1/proposals/{pid}/decisions", headers=auth("jordan"), json=body).status_code == 404
    stale = c.post(f"/api/v1/proposals/{pid}/decisions", headers=auth("sam"), json={**body, "expected_revision": 2})
    assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"
    bad = c.post(f"/api/v1/proposals/{pid}/decisions", headers=auth("sam"), json={**body, "approved_by": "sam"})
    assert bad.status_code == 422
    ok = c.post(f"/api/v1/proposals/{pid}/decisions", headers=auth("sam"), json=body)
    assert ok.status_code == 200 and ok.json()["status"] == "APPROVED" and ok.json()["decision"] == "approve"
    again = c.post(f"/api/v1/proposals/{pid}/decisions", headers=auth("sam"), json=body)
    assert again.status_code == 409  # first decision wins


def test_pure_rules():
    start, end = store.resolve_interval(24, datetime(2026, 10, 8, 12, 0, 0, 123456, tzinfo=UTC))
    assert (start.isoformat(), end.isoformat()) == ("2026-10-07T12:00:00+00:00", "2026-10-08T12:00:00+00:00")
    reviewer = store.Membership(ALPHA, frozenset({"reviewer"}))
    store.check_reviewer(reviewer, requester=ALEX, authored_by=[ALEX], reviewer=SAM)
    for who, member in (
        (ALEX, store.Membership(ALPHA, frozenset({"requester", "reviewer"}))),
        (SAM, store.Membership(ALPHA, frozenset({"reader"}))),
    ):
        with pytest.raises(store.Forbidden):
            store.check_reviewer(member, requester=ALEX, authored_by=[ALEX], reviewer=who)
    with pytest.raises(store.Forbidden):  # a content author is not independent even when not the requester
        store.check_reviewer(reviewer, requester=ALEX, authored_by=[ALEX, SAM], reviewer=SAM)


def test_health(api):
    c, _ = api
    assert c.get("/health/live").json() == {"status": "live"} and c.get("/health/ready").status_code == 200


class BrokenStore(FakeStore):
    async def run(self, tenant_id: UUID, run_id: UUID) -> dict[str, Any] | None:
        """Stand in for a store whose database connection is gone."""
        raise psycopg.OperationalError("connection lost")


def test_database_failure_is_a_safe_503() -> None:
    app = create_app(StubVerifier(), store_factory=lambda: BrokenStore(), auth_factory=fake_auth)
    with TestClient(app) as c:
        response = c.get(f"/api/v1/runs/{uuid4()}", headers=auth("alex"))
    assert response.status_code == 503
    assert response.json()["code"] == "UNAVAILABLE" and response.json()["retryable"] is True
    assert "connection lost" not in response.text


def test_a_persistence_defect_is_a_safe_503_without_detail(api, monkeypatch: pytest.MonkeyPatch) -> None:
    c, fake = api

    async def broken_admit(**_: Any) -> Any:
        """Stand in for a function that rejected bytes the API had just built."""
        raise persistence.HashMismatch("payload hash differs")

    monkeypatch.setattr(fake, "admit_message", broken_admit)
    cid = c.post("/api/v1/conversations", headers=auth("alex")).json()["conversation_id"]
    body = {"kind": "investigate", "text": "x", "context": {"asset_id": "A17", "hours": 2}}
    response = c.post(f"/api/v1/conversations/{cid}/messages", headers=auth("alex"), json=body)
    assert response.status_code == 503 and response.json()["code"] == "UNAVAILABLE"
    assert "payload hash" not in response.text

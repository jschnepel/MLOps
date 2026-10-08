"""The API's authority rules without a database (BUILD_SPEC §7 admission, §12 independent decision, §9 identity).

Catches: a body that carries an authority field accepted (BUILD_SPEC §7: the server sets actor, tenant, roles), a
duplicate JSON key silently resolved, the requester approving their own proposal (SA:539), a reviewer from another
tenant seeing or deciding a proposal (404, not 403: existence is not disclosed), a decision on a stale hash accepted,
a second decision overwriting the first, and a run in another tenant readable by id.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from ops_api import store
from ops_api.app import create_app
from ops_core.contracts import DecisionRequest, MessageRequest
from ops_core.tokens import Principal, TokenRejected

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
MEMBERS = {
    ALEX: store.Membership(ALPHA, frozenset({"requester"})),
    SAM: store.Membership(ALPHA, frozenset({"reviewer"})),
    LEE: store.Membership(ALPHA, frozenset({"reader"})),
    JORDAN: store.Membership(BETA, frozenset({"reviewer"})),
}


class StubVerifier:
    @property
    def ready(self) -> bool:
        return True

    async def load_keys(self) -> None:
        return None

    async def verify_async(self, token: str) -> Principal:
        if token not in PERSONAS:
            raise TokenRejected("unit test")
        return Principal(
            subject=str(PERSONAS[token]),
            azp="ops-dev-direct",
            audiences=("ops-api",),
            expires_at=2**31,
            claims={"preferred_username": token},
        )


class FakeStore:
    def __init__(self) -> None:
        self.conversations: dict[UUID, UUID] = {}  # conversation -> tenant
        self.runs: dict[UUID, dict[str, Any]] = {}
        self.proposals: dict[UUID, dict[str, Any]] = {}
        self.decided: set[UUID] = set()
        self.slot_occupied = False

    async def membership(self, issuer: str, subject: UUID) -> store.Membership | None:
        return MEMBERS.get(subject) if issuer == ISSUER else None

    async def create_conversation(self, tenant_id: UUID, created_by: UUID) -> UUID:
        cid = uuid4()
        self.conversations[cid] = tenant_id
        return cid

    async def admit(
        self,
        *,
        tenant_id: UUID,
        conversation_id: UUID,
        requester: UUID,
        request: MessageRequest,
        start_at: datetime,
        end_at: datetime,
    ) -> store.Accepted:
        if self.conversations.get(conversation_id) != tenant_id:
            raise store.NotFound
        if self.slot_occupied:
            raise store.Conflict("SLOT_OCCUPIED")
        run_id = uuid4()
        self.runs[run_id] = {
            "run_id": run_id,
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "requester": requester,
            "state": "QUEUED",
            "state_version": 1,
            "active_proposal_id": None,
            "asset_id": request.context.asset_id if request.context else None,
            "start_at": start_at,
            "end_at": end_at,
            "created_at": start_at,
        }
        return store.Accepted(conversation_id, uuid4(), run_id, "QUEUED", 1)

    async def run(self, tenant_id: UUID, run_id: UUID) -> dict[str, Any] | None:
        row = self.runs.get(run_id)
        return row if row and row["tenant_id"] == tenant_id else None

    async def proposal(self, tenant_id: UUID, proposal_id: UUID) -> dict[str, Any] | None:
        row = self.proposals.get(proposal_id)
        return row if row and row["tenant_id"] == tenant_id else None

    async def decide(
        self, *, tenant_id: UUID, proposal_id: UUID, reviewer: UUID, request: DecisionRequest
    ) -> store.Decided:
        row = await self.proposal(tenant_id, proposal_id)
        if row is None:
            raise store.NotFound
        if (row["revision"], row["payload_sha256"]) != (request.expected_revision, request.expected_payload_sha256):
            raise store.Conflict("VERSION_CONFLICT")
        if proposal_id in self.decided:
            raise store.Conflict("VERSION_CONFLICT")
        self.decided.add(proposal_id)
        status = "APPROVED" if request.decision == "approve" else "REJECTED"
        return store.Decided(proposal_id, row["run_id"], request.decision, status, 5)

    async def events(self, tenant_id: UUID, run_id: UUID, *, after: int, limit: int) -> list[dict[str, Any]]:
        return [] if await self.run(tenant_id, run_id) is None else [{"sequence": 1, "type": "run.accepted"}]


@pytest.fixture
def api() -> Iterator[tuple[TestClient, FakeStore]]:
    fake = FakeStore()
    app = create_app(StubVerifier(), store_factory=lambda: fake)
    with TestClient(app) as c:  # the context manager runs the lifespan, which installs the store
        yield c, fake


def auth(name: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {name}"}


def test_identity_and_membership(api):
    c, _ = api
    assert c.get("/api/v1/me").status_code == 401
    assert c.get("/api/v1/me", headers=auth("nobody")).status_code == 401
    me = c.get("/api/v1/me", headers=auth("alex")).json()
    assert me == {"subject": str(ALEX), "tenant_id": str(ALPHA), "roles": ["requester"], "username": "alex"}


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
        {**body, "kind": "ask"},  # not routed in T08 (admission router is T12)
        {"kind": "investigate", "text": "x"},  # no asset/interval
        {**body, "context": {"asset_id": "a17", "hours": 24}},  # AssetId pattern
    ):
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

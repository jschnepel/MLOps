"""T21's API routes over HTTP with the shared fake store (Plan R rulings 2-8, 12 and 15; R043, R044, R057, R093,
R113): the decision's own conflict codes and its lazy expiry, the revision, the cancel, the manual proposal, the
feedback, the search and the approval card.

Catches: a lazy expiry that runs inside the decision's unit (a 409 would roll back the BLOCKED_REVIEW, DEV-008); a
stale, expired or already-decided decision answered with one generic code; a reviewer who revised the run approving
it (R093); a revision, cancel or manual proposal without the IdP's enabled check (SA:542); a requester cancelling
another requester's run; a manual proposal for another asset that writes anything (note 4); a reader allowed to
author or search; feedback text reaching an event; a search that needs an Idempotency-Key or leaks the rank; and an
approval card without its requester, decision, expiry, supersession and submission state.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from tests.plan_g import fakes
from tests.plan_g.fakes import ALEX, CASEY, MORGAN, SAM, FakeStore
from tests.plan_g.test_api_admission import DECISION, client, h, refused

WHEN = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


@pytest.fixture
def api() -> Iterator[tuple[TestClient, FakeStore]]:
    fake = FakeStore()
    with client(fake) as c:
        yield c, fake


def seed_run(fake: FakeStore, state: str, **extra: Any) -> UUID:
    """Alex's run in ALPHA, in `state` at version 5 (what the worker or a decision would leave)."""
    run_id = uuid4()
    fake.runs[run_id] = {
        "run_id": run_id,
        "tenant_id": fakes.ALPHA,
        "conversation_id": uuid4(),
        "requester": ALEX,
        "state": state,
        "state_version": 5,
        "active_proposal_id": None,
        "asset_id": "A17",
        "start_at": WHEN,
        "end_at": WHEN,
        "created_at": WHEN,
        "reason": None,
        **extra,
    }
    return run_id


def seed_proposal(fake: FakeStore, run_id: UUID, **extra: Any) -> UUID:
    pid = uuid4()
    fake.proposals[pid] = {
        "proposal_id": pid,
        "tenant_id": fakes.ALPHA,
        "run_id": run_id,
        "revision": 1,
        "payload": {"k": 1},
        "payload_sha256": "9" * 64,
        "authored_by": [ALEX],
        "requester": ALEX,
        "expires_at": WHEN,
        **extra,
    }
    return pid


def test_a_decision_runs_the_lazy_expiry_first_and_names_each_conflict(api) -> None:
    c, fake = api
    pid = seed_proposal(fake, seed_run(fake, "AWAITING_APPROVAL"))
    url = f"/api/v1/proposals/{pid}/decisions"
    refused(c.post(url, headers=h("sam"), json={**DECISION, "expected_revision": 2}), 409, "STALE_REVISION")
    refused(c.post(url, headers=h("sam"), json={**DECISION, "expected_payload_sha256": "8" * 64}), 409, "STALE_HASH")
    assert fake.expiries == [pid, pid]  # a unit of its own before each decision unit (ruling 5)
    expired = seed_proposal(fake, seed_run(fake, "AWAITING_APPROVAL"), expired=True)
    body = refused(c.post(f"/api/v1/proposals/{expired}/decisions", headers=h("sam"), json=DECISION), 409, "EXPIRED")
    assert body["message"] == "the proposal expired; a revision and a new review are needed"


def test_a_requester_who_also_reviews_and_revised_cannot_approve(api) -> None:
    c, fake = api
    run_id = seed_run(fake, "BLOCKED_REVIEW", reason="expired")
    revised = c.post(f"/api/v1/runs/{run_id}/revisions", headers=h("morgan"), json={"expected_version": 5})
    assert revised.status_code == 202 and revised.json()["revision"] == 2 and revised.json()["status"] == "QUEUED"
    assert fake.runs[run_id]["authors"] == [ALEX, MORGAN] and fake.jobs[-1]["dedup_key"] == f"{run_id}:2"
    pid = seed_proposal(fake, run_id, revision=2, authored_by=fake.runs[run_id]["authors"])
    decision = {**DECISION, "expected_revision": 2}
    refused(c.post(f"/api/v1/proposals/{pid}/decisions", headers=h("morgan"), json=decision), 403, "FORBIDDEN")
    assert c.post(f"/api/v1/proposals/{pid}/decisions", headers=h("sam"), json=decision).status_code == 200


def test_a_revision_is_a_requesters_and_keeps_its_codes(api) -> None:
    c, fake = api
    run_id = seed_run(fake, "APPROVED")
    url = f"/api/v1/runs/{run_id}/revisions"
    refused(c.post(url, headers=h("sam"), json={"expected_version": 5}), 403, "FORBIDDEN")  # a reviewer only
    refused(c.post(url, headers=h("alex"), json={"expected_version": 4}), 409, "VERSION_CONFLICT")
    fake.runs[run_id]["grant"] = True
    refused(c.post(url, headers=h("alex"), json={"expected_version": 5}), 409, "GRANT_EXISTS")  # R090
    blocked = seed_run(fake, "BLOCKED_REVIEW")
    seed_run(fake, "RETRIEVING", conversation_id=fake.runs[blocked]["conversation_id"])  # R120: the slot is taken
    refused(
        c.post(f"/api/v1/runs/{blocked}/revisions", headers=h(), json={"expected_version": 5}), 409, "SLOT_OCCUPIED"
    )
    refused(c.post(f"/api/v1/runs/{uuid4()}/revisions", headers=h(), json={"expected_version": 5}), 404, "NOT_FOUND")
    first = c.post(
        url := f"/api/v1/runs/{seed_run(fake, 'APPROVED')}/revisions",
        headers=h(key="key-revision-01"),
        json={"expected_version": 5},
    )
    assert (
        c.post(url, headers=h(key="key-revision-01"), json={"expected_version": 5}).content == first.content
    )  # a replay


def test_revisions_cancels_and_manual_proposals_ask_the_idp_first(api) -> None:
    c, fake = api
    c.app.state.auth.admin.disabled.add(ALEX)
    run_id = seed_run(fake, "DRAFTING")
    for path, body in (
        (f"/api/v1/runs/{run_id}/revisions", {"expected_version": 5}),
        (f"/api/v1/runs/{run_id}/cancel", {"expected_version": 5}),
        ("/api/v1/manual-proposals", {}),
    ):
        refused(c.post(path, headers=h(), json=body), 401, "UNAUTHENTICATED")  # SA:542, before the body
    assert fake.runs[run_id]["state"] == "DRAFTING" and not fake.records


def test_a_cancel_is_the_runs_requesters_or_a_reviewers_and_never_claims_undo(api) -> None:
    c, fake = api
    run_id = seed_run(fake, "BLOCKED_REVIEW")
    refused(c.post(f"/api/v1/runs/{run_id}/cancel", headers=h("casey"), json={"expected_version": 5}), 403, "FORBIDDEN")
    done = c.post(f"/api/v1/runs/{run_id}/cancel", headers=h("alex"), json={"expected_version": 5})
    assert done.status_code == 200 and done.json()["status"] == "CANCELLED" and done.json()["grant_exists"] is False
    granted = seed_run(fake, "EXECUTING", grant=True)
    after = c.post(f"/api/v1/runs/{granted}/cancel", headers=h("sam"), json={"expected_version": 1})
    assert after.status_code == 200 and after.json()["status"] == "EXECUTING" and after.json()["grant_exists"] is True
    assert after.json()["note"] == "a grant exists; what was dispatched stands, and nothing is undone"
    refused(c.post(f"/api/v1/runs/{run_id}/cancel", headers=h(), json={"expected_version": 6}), 409, "VERSION_CONFLICT")


def manual(run_id: UUID, asset: str = "A17") -> dict[str, Any]:
    return {
        "run_id": str(run_id),
        "asset_id": asset,
        "start_at": "2026-10-24T12:00:00Z",
        "end_at": "2026-10-25T12:00:00Z",
        "title": "Review the warnings",
        "summary": "Two warnings in the interval.",
        "evidence_refs": ["ALPHA-INCIDENT:v2:review"],
        "assumptions": [],
        "limitations": ["Written by a person."],
    }


def test_a_manual_proposal_for_a_run_that_waits_for_one(api) -> None:
    c, fake = api
    run_id = seed_run(fake, "DRAFTING")
    refused(c.post("/api/v1/manual-proposals", headers=h("lee"), json=manual(run_id)), 403, "FORBIDDEN")  # a reader
    refused(c.post("/api/v1/manual-proposals", headers=h(), json=manual(run_id, "B22")), 404, "NOT_FOUND")  # note 4
    assert fake.runs[run_id]["state"] == "DRAFTING" and not fake.proposals  # nothing written
    made = c.post("/api/v1/manual-proposals", headers=h("sam"), json=manual(run_id))
    assert made.status_code == 201 and made.json()["status"] == "AWAITING_APPROVAL"
    assert fake.proposals[UUID(made.json()["proposal_id"])]["authored_by"] == [ALEX, SAM]  # sam may not approve it
    refused(c.post("/api/v1/manual-proposals", headers=h(), json=manual(run_id)), 409, "VERSION_CONFLICT")
    guarded = seed_run(fake, "DRAFTING", blocked_by=uuid4())
    body = refused(c.post("/api/v1/manual-proposals", headers=h(), json=manual(guarded)), 409, "ASSET_INCIDENT_EXISTS")
    assert str(fake.runs[guarded]["blocked_by"]) in body["message"] and fake.runs[guarded]["state"] == "BLOCKED_REVIEW"


def test_feedback_is_any_members_and_its_text_stays_out_of_events(api) -> None:
    c, fake = api
    run_id = seed_run(fake, "SUCCEEDED")
    body = {"subject_kind": "run", "subject_id": str(run_id), "category": "unclear", "text": "Which sensor?"}
    made = c.post(f"/api/v1/runs/{run_id}/feedback", headers=h("lee"), json=body)
    assert made.status_code == 201 and fake.feedback[-1]["text"] == "Which sensor?"
    assert fake.event_log[-1] == {
        "run_id": run_id,
        "type": "feedback.recorded",
        "payload": {"subject_kind": "run", "subject_id": str(run_id), "category": "unclear"},
    }
    other = {**body, "subject_kind": "proposal", "subject_id": str(uuid4())}
    refused(c.post(f"/api/v1/runs/{run_id}/feedback", headers=h("lee"), json=other), 404, "NOT_FOUND")
    refused(c.post(f"/api/v1/runs/{uuid4()}/feedback", headers=h("lee"), json=body), 404, "NOT_FOUND")


def test_the_search_is_an_authors_read_without_a_key(api) -> None:
    c, fake = api
    bearer = {"Authorization": "Bearer alex"}
    assert c.post("/api/v1/search", headers=bearer, json={"query": "bearing temperature"}).status_code == 200
    assert c.post("/api/v1/search", headers={"Authorization": "Bearer lee"}, json={"query": "x"}).status_code == 403
    assert c.post("/api/v1/search", headers=bearer, json={"query": "x", "limit": 11}).status_code == 422
    assert [s.limit for s in fake.searches] == [5]


def test_the_approval_card_and_the_run_snapshot(api) -> None:
    c, fake = api
    run_id = seed_run(fake, "BLOCKED_REVIEW", reason="expired")
    pid = seed_proposal(fake, run_id)
    card = c.get(f"/api/v1/proposals/{pid}", headers=h("sam")).json()
    assert card["requester"] == str(ALEX) and card["decision"] is None and card["expired"] is False
    assert card["supersedes"] is None and card["submission_state"] == {"grant_exists": False, "attempt_state": None}
    assert c.get(f"/api/v1/runs/{run_id}", headers=h()).json()["reason"] == "expired"
    assert CASEY not in fake.runs[run_id].get("authors", [])

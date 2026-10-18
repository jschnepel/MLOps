"""The T12 routes over HTTP with the shared fake store (R015-R018, R115, R129; Plan G rulings 1-5, 13-24): the six
admission routes, replay and conflict, the check order, every status code of R115, and what is and is not recorded.

Catches: a route answering without a key, the key checked before identity (a stranger learning which keys exist) or
after the body (a malformed body recorded), a replay that differs from the first answer, one key replaying across
conversations, a recorded 422 for a body that never parsed, an unroutable kind that writes anything, a revoked member
or a demoted reviewer replaying a recorded success (BS:264 "authenticated current session"), a 429 without
Retry-After or one recorded (the same key must succeed once the queue drains), a fault before commit that keeps
anything or tells the client not to retry, the fault route reachable outside the test profile, a stale clarification
reply accepted, another requester answering a run's question, a replayed error naming the first request's id, a
window number too large to read answered with a 503, and a form asset among several in the text starting a run.
"""

import json
from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from ops_api.app import create_app
from ops_core.settings import AdmissionSettings, Profile

from tests.plan_f.auth_fakes import fake_auth, login_as
from tests.plan_g import fakes
from tests.plan_g.fakes import ALEX, SAM, FakeStore, StubVerifier

SAMPLE = {
    "kind": "investigate",
    "text": "Investigate the alerts on Asset A17 over the last 24 hours.",
    "context": {"asset_id": "A17", "hours": 24},
}
DECISION = {"expected_revision": 1, "expected_payload_sha256": "9" * 64, "decision": "approve"}


def h(name: str = "alex", key: str | None = None) -> dict[str, str]:
    """A persona's bearer header and an Idempotency-Key (a fresh one unless given)."""
    return {"Authorization": f"Bearer {name}", "Idempotency-Key": key or str(uuid4())}


def client(fake: FakeStore, **kwargs: Any) -> TestClient:
    return TestClient(create_app(StubVerifier(), store_factory=lambda: fake, auth_factory=fake_auth, **kwargs))


@pytest.fixture
def api() -> Iterator[tuple[TestClient, FakeStore]]:
    fake = FakeStore()
    with client(fake) as c:
        yield c, fake


def new_conversation(c: TestClient) -> str:
    r = c.post("/api/v1/conversations", headers=h())
    assert r.status_code == 201, r.text
    return str(r.json()["conversation_id"])


def messages(cid: str) -> str:
    return f"/api/v1/conversations/{cid}/messages"


def proposal(fake: FakeStore) -> UUID:
    """A proposal of alex's run in ALPHA at revision 1, with the hash DECISION names."""
    pid = uuid4()
    fake.proposals[pid] = {
        "proposal_id": pid,
        "tenant_id": fakes.ALPHA,
        "run_id": uuid4(),
        "revision": 1,
        "payload_sha256": "9" * 64,
        "authored_by": [ALEX],
        "requester": ALEX,
    }
    return pid


def refused(r: Any, status: int, code: str) -> dict[str, Any]:
    """The refusal's body once its status and SafeError code are as R115 says; none of these is retryable."""
    body: dict[str, Any] = r.json()
    assert r.status_code == status and body["code"] == code and body["retryable"] is False
    return body


def without_id(body: dict[str, Any]) -> dict[str, Any]:
    """An error body without its request id: a replayed error is the recorded answer under this request's id."""
    return {k: v for k, v in body.items() if k != "request_id"}


def test_the_six_admission_routes_over_http(api) -> None:
    c, fake = api
    investigate = c.post(messages(cid := new_conversation(c)), headers=h(), json=SAMPLE)
    assert investigate.status_code == 202 and investigate.json()["status"] == "QUEUED"
    accepted_keys = {"conversation_id", "message_id", "run_id", "status", "state_version", "status_url", "events_url"}
    assert set(investigate.json()) == accepted_keys  # BS:299; stream_url waits for T27
    status = c.post(messages(cid), headers=h(), json={"kind": "status", "text": "How is it going?"})
    assert status.status_code == 200 and status.json()["run_id"] == investigate.json()["run_id"]
    clarify = c.post(
        messages(new_conversation(c)),
        headers=h(),
        json={"kind": "investigate", "text": "Compare A17 and B22, last day."},
    )
    assert clarify.status_code == 200 and clarify.json()["cause"] == "asset_ambiguous"
    readonly = c.post(
        messages(new_conversation(c)), headers=h(), json={"kind": "ask", "text": "What did A17 log in the past 2 days?"}
    )
    assert readonly.status_code == 202 and fake.runs[UUID(readonly.json()["run_id"])]["intent"] == "answer_only"
    reject = c.post(messages(new_conversation(c)), headers=h(), json={"kind": "clarification", "text": "A17"})
    rejected = refused(reject, 422, "INVALID_INPUT")
    assert rejected["message"] == "clarification replies go to /api/v1/runs/{run_id}/clarifications"
    run_id = UUID(investigate.json()["run_id"])
    question = fake.seed_question(run_id)
    body = {"question_id": str(question), "expected_version": 3, "context": {"asset_id": "A17"}}
    reply = c.post(f"/api/v1/runs/{run_id}/clarifications", headers=h(), json=body)
    assert reply.status_code == 202 and reply.json()["run_id"] == str(run_id)
    assert fake.jobs[-1]["type"] == "resume_input"


@pytest.mark.parametrize("kind", ["delete", "", "STATUS"])
def test_an_unroutable_kind_is_an_unrecorded_422_that_writes_nothing(api, kind: str) -> None:
    c, fake = api
    cid = new_conversation(c)
    records = len(fake.records)  # the conversation's own
    r = c.post(messages(cid), headers=h(), json={"kind": kind, "text": "Investigate A17 over the last 24 hours."})
    refused(r, 422, "INVALID_INPUT")  # the strict kind enum, before the router
    assert not fake.messages and not fake.runs and not fake.jobs and len(fake.records) == records  # AM-16, SA:373


def test_a_replay_is_the_same_bytes_and_a_reused_key_is_a_conflict(api) -> None:
    c, fake = api
    cid, other = new_conversation(c), new_conversation(c)
    first = c.post(messages(cid), headers=h(key="key-replay-1"), json=SAMPLE)
    reformatted = json.dumps(SAMPLE, indent=2, sort_keys=True)  # whitespace and key order are not the request
    again = c.post(
        messages(cid), headers={**h(key="key-replay-1"), "Content-Type": "application/json"}, content=reformatted
    )
    assert first.status_code == again.status_code == 202 and again.content == first.content
    assert again.headers["X-Request-Id"] != first.headers["X-Request-Id"]  # the request is new; the answer is not
    assert len(fake.runs) == 1
    changed = c.post(
        messages(cid), headers=h(key="key-replay-1"), json={**SAMPLE, "context": {"asset_id": "A17", "hours": 12}}
    )
    elsewhere = c.post(messages(other), headers=h(key="key-replay-1"), json=SAMPLE)
    for conflict in (changed, elsewhere):
        refused(conflict, 409, "IDEMPOTENCY_CONFLICT")
    assert len(fake.runs) == 1 and len(fake.records) == 3  # two conversations and one message; no conflict recorded


def test_the_key_comes_after_identity_and_role_and_before_the_body(api) -> None:
    c, _ = api
    cid = new_conversation(c)
    refused(c.post(messages(cid), json=SAMPLE), 401, "UNAUTHENTICATED")
    refused(c.post(messages(cid), headers={"Authorization": "Bearer sam"}, json=SAMPLE), 403, "FORBIDDEN")
    keyless = refused(
        c.post(messages(cid), headers={"Authorization": "Bearer alex"}, content=b"not json"), 422, "INVALID_INPUT"
    )
    assert keyless["message"] == "Idempotency-Key header is required (8–128 visible ASCII characters)"
    malformed = refused(c.post(messages(cid), headers=h(key="key-order-01"), content=b"not json"), 422, "INVALID_INPUT")
    assert malformed["message"] == "request body is not valid"
    assert c.post(messages(cid), headers=h(key="key-order-01"), json=SAMPLE).status_code == 202  # nothing recorded


@pytest.mark.parametrize("key", ["has space1", "short", "a" * 129, ""])
def test_a_malformed_key_is_refused_before_anything_is_read(api, key: str) -> None:
    c, fake = api
    r = c.post(messages(new_conversation(c)), headers=h(key="placeholder") | {"Idempotency-Key": key}, json=SAMPLE)
    refused(r, 422, "INVALID_INPUT")
    assert not fake.runs


def test_a_full_tenant_queue_is_an_unrecorded_429_with_retry_after() -> None:
    fake = FakeStore()
    with client(fake, admission=AdmissionSettings(tenant_queue_quota=1)) as c:
        assert c.post(messages(new_conversation(c)), headers=h(), json=SAMPLE).status_code == 202
        cid = new_conversation(c)
        records = len(fake.records)
        full = c.post(messages(cid), headers=h(key="key-quota-01"), json=SAMPLE)
        full_body = full.json()
        assert full.status_code == 429 and full.headers["Retry-After"] == "5" and full_body["code"] == "RATE_LIMITED"
        assert full_body["request_id"] == full.headers["X-Request-Id"] and len(fake.records) == records
        assert full_body["retryable"] is True  # a 429 is the one client-side retryable refusal (ruling 19)
        fake.runs.clear()  # the queue drains
        again = c.post(messages(cid), headers=h(key="key-quota-01"), json=SAMPLE)
        assert again.status_code == 202  # Retry-After told the truth: the same key is admitted now (ruling 5)


def test_a_fault_before_commit_is_a_retryable_503_and_the_same_key_then_succeeds() -> None:
    fake = FakeStore()
    with client(fake, profile=Profile.TEST) as c:
        cid = new_conversation(c)
        armed = c.post("/internal/faults/drop_before_commit", headers=h(), json={"count": 1})
        assert armed.status_code == 200 and armed.json() == {"armed": {"drop_before_commit": 1}}
        crashed = c.post(messages(cid), headers=h(key="key-fault-01"), json=SAMPLE)
        assert crashed.status_code == 503 and crashed.json()["retryable"] is True  # a lost connection (ruling 24)
        assert crashed.json()["message"] == "database unavailable"
        assert not fake.runs and not fake.messages and len(fake.records) == 1  # only the conversation's record
        retried = c.post(messages(cid), headers=h(key="key-fault-01"), json=SAMPLE)
        assert retried.status_code == 202 and len(fake.jobs) == 1  # R015: after commit the job exists
        refused(c.post("/internal/faults/reject_next", headers=h(), json={"count": 1}), 422, "INVALID_INPUT")
        refused(c.post("/internal/faults/not_a_kind", headers=h(), json={"count": 1}), 422, "INVALID_INPUT")
        for count in (0, 101):  # FaultRequest bounds the count to 1..100
            refused(
                c.post("/internal/faults/drop_before_commit", headers=h(), json={"count": count}), 422, "INVALID_INPUT"
            )


def test_the_fault_route_does_not_exist_outside_the_test_profile(api) -> None:
    c, _ = api
    r = c.post("/internal/faults/drop_before_commit", headers=h(), json={"count": 1})
    refused(r, 404, "NOT_FOUND")


def test_a_lost_database_during_admission_is_a_retryable_503(api, monkeypatch) -> None:
    c, fake = api
    cid = new_conversation(c)

    async def gone(**_: Any) -> Any:
        raise psycopg.OperationalError("connection lost")

    monkeypatch.setattr(fake, "admit_message", gone)
    r = c.post(messages(cid), headers=h(), json=SAMPLE)
    assert r.status_code == 503 and r.json()["retryable"] is True and "connection lost" not in r.text


def test_router_verdicts_are_recorded_and_replayed(api) -> None:
    c, _ = api
    missing = f"/api/v1/conversations/{uuid4()}/messages"
    first = c.post(missing, headers=h(key="key-404-0001"), json=SAMPLE)
    again = c.post(missing, headers=h(key="key-404-0001"), json=SAMPLE)
    recorded_404 = refused(first, 404, "NOT_FOUND")
    assert refused(again, 404, "NOT_FOUND") and without_id(again.json()) == without_id(recorded_404)
    cid = new_conversation(c)
    assert c.post(messages(cid), headers=h(), json=SAMPLE).status_code == 202
    busy = c.post(messages(cid), headers=h(key="key-409-0001"), json=SAMPLE)
    refused(busy, 409, "SLOT_OCCUPIED")


def test_a_replayed_error_carries_the_replaying_requests_id(api) -> None:
    c, _ = api
    cid = new_conversation(c)
    assert c.post(messages(cid), headers=h(), json=SAMPLE).status_code == 202
    first = c.post(messages(cid), headers=h(key="key-409-0002"), json=SAMPLE)
    again = c.post(messages(cid), headers=h(key="key-409-0002"), json=SAMPLE)  # a replay of the recorded 409
    refused(first, 409, "SLOT_OCCUPIED")
    refused(again, 409, "SLOT_OCCUPIED")
    assert without_id(again.json()) == without_id(first.json())
    assert again.json()["request_id"] == again.headers["X-Request-Id"] != first.json()["request_id"]  # ruling 4


def test_a_revoked_member_cannot_replay_a_recorded_success(api) -> None:
    c, _ = api
    cid = new_conversation(c)
    assert c.post(messages(cid), headers=h(key="key-revoke-1"), json=SAMPLE).status_code == 202
    saved = fakes.ROWS[ALEX]
    fakes.ROWS[ALEX] = []  # the sync deactivated alex
    try:
        replay = c.post(messages(cid), headers=h(key="key-revoke-1"), json=SAMPLE)
        refused(replay, 401, "UNAUTHENTICATED")  # identity before the record
    finally:
        fakes.ROWS[ALEX] = saved


def test_a_member_who_lost_the_reviewer_role_cannot_replay_a_decision(api) -> None:
    c, fake = api
    url = f"/api/v1/proposals/{proposal(fake)}/decisions"
    assert c.post(url, headers=h("sam", "key-demote-1"), json=DECISION).status_code == 200
    saved = fakes.ROWS[SAM]
    fakes.ROWS[SAM] = [(fakes.ALPHA, "reader")]  # the sync demoted sam; the membership itself stays
    try:
        replay = c.post(url, headers=h("sam", "key-demote-1"), json=DECISION)
        refused(replay, 403, "FORBIDDEN")  # the role before the record
    finally:
        fakes.ROWS[SAM] = saved


def test_a_stale_clarification_reply_is_a_recorded_409(api) -> None:
    c, fake = api
    run_id = UUID(c.post(messages(new_conversation(c)), headers=h(), json=SAMPLE).json()["run_id"])
    question = fake.seed_question(run_id)
    url = f"/api/v1/runs/{run_id}/clarifications"
    stale = {"question_id": str(question), "expected_version": 2, "context": {"hours": 12}}
    first = c.post(url, headers=h(key="key-stale-01"), json=stale)
    first_body = refused(first, 409, "VERSION_CONFLICT")
    replayed = c.post(url, headers=h(key="key-stale-01"), json=stale)
    assert refused(replayed, 409, "VERSION_CONFLICT") and without_id(replayed.json()) == without_id(first_body)
    sam = {"Authorization": "Bearer sam", "Idempotency-Key": "key-stale-02"}
    refused(c.post(url, headers=sam, json=stale), 403, "FORBIDDEN")
    refused(c.post(url, headers={"Authorization": "Bearer alex"}, json=stale), 422, "INVALID_INPUT")
    assert not any(j["type"] == "resume_input" for j in fake.jobs)


def test_another_requester_cannot_answer_the_runs_question(api) -> None:
    c, fake = api
    run_id = UUID(c.post(messages(new_conversation(c)), headers=h(), json=SAMPLE).json()["run_id"])
    question = fake.seed_question(run_id)
    body = {"question_id": str(question), "expected_version": 3, "context": {"hours": 12}}
    records = len(fake.records)
    stranger = c.post(f"/api/v1/runs/{run_id}/clarifications", headers=h("casey"), json=body)
    assert c.get(f"/api/v1/runs/{run_id}", headers=h("casey")).status_code == 200  # casey may read the run
    stranger_body = refused(stranger, 403, "FORBIDDEN")  # BS:301: known, but not hers
    assert stranger_body["message"] == "only the run's requester may answer its question"
    assert len(fake.records) == records  # a 403 is never recorded (ruling 5)
    assert not any(j["type"] == "resume_input" for j in fake.jobs) and not fake.messages[1:]  # only alex's request


def test_a_decision_replays_and_the_first_decision_wins(api) -> None:
    c, fake = api
    pid = proposal(fake)
    url = f"/api/v1/proposals/{pid}/decisions"
    refused(c.post(url, headers=h("alex"), json=DECISION), 403, "FORBIDDEN")  # the requester: refused, not recorded
    first = c.post(url, headers=h("sam", "key-decide-1"), json=DECISION)
    assert first.status_code == 200 and fake.decision_keys[pid] == "key-decide-1"
    assert c.post(url, headers=h("sam", "key-decide-1"), json=DECISION).content == first.content
    second = c.post(url, headers=h("sam"), json=DECISION)
    refused(second, 409, "VERSION_CONFLICT")


def test_a_conversation_replay_returns_the_same_id(api) -> None:
    c, fake = api
    first = c.post("/api/v1/conversations", headers=h(key="key-conv-001"))
    again = c.post("/api/v1/conversations", headers=h(key="key-conv-001"))
    assert first.status_code == again.status_code == 201 and again.json() == first.json()
    assert len(fake.conversations) == 1


def test_a_clarification_for_an_absent_run_is_a_recorded_404(api) -> None:
    c, fake = api
    url = f"/api/v1/runs/{uuid4()}/clarifications"
    body = {"question_id": str(uuid4()), "expected_version": 3, "context": {"hours": 12}}
    first = c.post(url, headers=h(key="key-absent-01"), json=body)
    recorded_404 = refused(first, 404, "NOT_FOUND")
    again = c.post(url, headers=h(key="key-absent-01"), json=body)
    assert refused(again, 404, "NOT_FOUND") and without_id(again.json()) == without_id(recorded_404)
    assert not any(j["type"] == "resume_input" for j in fake.jobs)


def test_another_tenants_run_is_a_404_to_a_clarification(api) -> None:
    c, fake = api
    run_id = UUID(c.post(messages(new_conversation(c)), headers=h(), json=SAMPLE).json()["run_id"])
    question = fake.seed_question(run_id)
    body = {"question_id": str(question), "expected_version": 3, "context": {"hours": 12}}
    other = c.post(f"/api/v1/runs/{run_id}/clarifications", headers=h("riley"), json=body)
    refused(other, 404, "NOT_FOUND")  # riley is BETA's requester: alpha's run does not exist for her
    assert not any(j["type"] == "resume_input" for j in fake.jobs)


def test_a_cookie_mutation_without_csrf_or_origin_is_a_403() -> None:
    fake = FakeStore()
    deps = fake_auth()
    app = create_app(StubVerifier(), store_factory=lambda: fake, auth_factory=lambda: deps)
    with TestClient(app, base_url="http://localhost:8000") as c:
        login_as(c, deps, ALEX)  # a cookie session; no bearer header
        key = {"Idempotency-Key": str(uuid4())}
        refused(c.post("/api/v1/conversations", headers=key), 403, "FORBIDDEN")
        assert not fake.conversations


@pytest.mark.parametrize(
    ("text", "context", "cause"),
    [
        ("Please look into it.", None, "missing_asset"),
        ("Investigate the alerts on Asset A17.", None, "missing_interval"),
    ],
)
def test_an_investigate_without_an_asset_or_window_is_a_clarification(
    api, text: str, context: dict[str, Any] | None, cause: str
) -> None:
    c, fake = api
    payload: dict[str, Any] = {"kind": "investigate", "text": text}
    if context is not None:
        payload["context"] = context
    r = c.post(messages(new_conversation(c)), headers=h(), json=payload)
    body = r.json()
    assert r.status_code == 200 and body["status"] == "clarification_needed" and body["cause"] == cause
    assert not fake.runs


def test_a_window_too_large_to_read_is_a_clarification_not_a_503(api, caplog: pytest.LogCaptureFixture) -> None:
    # I1: a 400-digit window once raised OverflowError in the router: an unrecorded 503 and an ERROR log line.
    c, fake = api
    text = "Investigate A17 last 1" + "0" * 400 + ".5 seconds"
    with caplog.at_level("DEBUG"):
        r = c.post(messages(new_conversation(c)), headers=h(), json={"kind": "investigate", "text": text})
    body = r.json()
    assert r.status_code == 200 and body["status"] == "clarification_needed"
    assert body["cause"] == "interval_out_of_range" and "1000" not in json.dumps(body)
    assert not fake.runs
    assert not [record for record in caplog.records if record.levelname == "ERROR"]


def test_a_form_asset_among_several_in_the_text_is_a_clarification(api) -> None:
    # I2: the form's A17 is one of two ids the text names, so which one is meant is the doubt (BS:297).
    c, fake = api
    payload = {
        "kind": "investigate",
        "text": "B22 is failing, A17 is fine; last 24 hours",
        "context": {"asset_id": "A17", "hours": 24},
    }
    r = c.post(messages(new_conversation(c)), headers=h(), json=payload)
    body = r.json()
    assert r.status_code == 200 and body["status"] == "clarification_needed" and body["cause"] == "asset_ambiguous"
    assert not fake.runs

"""The global queue bound (Plan H ruling 13, BS:550 "100 total", erratum 51), without a database: counted across
tenants after the tenant's quota and only for a verdict that would start a run, refused as the same unrecorded 429.

Catches: a bound that counts one tenant only (the api role's RLS view), a status question or a clarification refused
for a full queue, a recorded 429 (a retry after the queue drained would replay it), and a refusal that hides which
bound was hit.
"""

import asyncio
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from ops_api.app import create_app
from ops_api.idempotency import QueueFull, Verdict
from ops_core.contracts import MessageRequest, load
from ops_core.settings import AdmissionSettings

from tests.plan_f.auth_fakes import fake_auth
from tests.plan_g.fakes import ALEX, ALPHA, BETA, FakeStore, StubVerifier
from tests.plan_g.test_store_units import MESSAGES, SAMPLE, conversation, idem


def admit(fake: FakeStore, key: str, *, queue_limit: int, body: dict[str, Any] = SAMPLE) -> Verdict:
    cid = conversation(fake)
    request = load(MessageRequest, json.dumps(body))
    return asyncio.run(
        fake.admit_message(
            idem=idem(MESSAGES, key, {"conversation_id": str(cid)}, request.model_dump(mode="json")),
            tenant_id=ALPHA,
            conversation_id=cid,
            requester=ALEX,
            request=request,
            quota=100,
            queue_limit=queue_limit,
        )
    )


def foreign_queued_run(fake: FakeStore) -> None:
    """A QUEUED run of another tenant: invisible to ALPHA's quota, counted by the global bound."""
    admit(fake, f"foreign-{len(fake.runs)}", queue_limit=1000)
    newest = list(fake.runs.values())[-1]
    newest["tenant_id"] = BETA


def test_the_global_bound_refuses_after_the_tenant_quota_passes() -> None:
    fake = FakeStore()
    foreign_queued_run(fake)
    foreign_queued_run(fake)
    with pytest.raises(QueueFull) as full:
        admit(fake, "key-global-01", queue_limit=2)
    assert full.value.message == "the work queue is full" and len(fake.runs) == 2  # nothing written, nothing recorded
    assert admit(fake, "key-global-02", queue_limit=3).status == 202


def test_a_status_question_or_a_clarification_never_counts_the_global_queue() -> None:
    fake = FakeStore()
    foreign_queued_run(fake)
    counted = fake.counts
    status = admit(fake, "key-status-01", queue_limit=1, body={"kind": "status", "text": "Anything running?"})
    assert status.status == 200
    asked = admit(fake, "key-ask-01", queue_limit=1, body={"kind": "investigate", "text": "Look into it."})
    assert asked.status == 200 and asked.body["status"] == "clarification_needed" and fake.counts == counted


def test_the_global_refusal_is_an_unrecorded_429_with_retry_after() -> None:
    fake = FakeStore()
    foreign_queued_run(fake)
    app = create_app(
        StubVerifier(),
        store_factory=lambda: fake,
        auth_factory=fake_auth,
        admission=AdmissionSettings(global_queue_limit=1),
    )
    headers = {"Authorization": "Bearer alex", "Idempotency-Key": "key-global-http-01"}
    with TestClient(app) as c:
        cid = c.post("/api/v1/conversations", headers={**headers, "Idempotency-Key": "key-conv-01"}).json()[
            "conversation_id"
        ]
        records = len(fake.records)
        full = c.post(f"/api/v1/conversations/{cid}/messages", headers=headers, json=SAMPLE)
        body = full.json()
        assert full.status_code == 429 and full.headers["Retry-After"] == "5"
        assert (body["code"], body["message"], body["retryable"]) == ("RATE_LIMITED", "the work queue is full", True)
        assert len(fake.records) == records  # never recorded (Plan G ruling 5)
        fake.runs.clear()  # the queue drains
        again = c.post(f"/api/v1/conversations/{cid}/messages", headers=headers, json=SAMPLE)
        assert again.status_code == 202  # the same key is admitted now

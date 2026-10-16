"""mcp-write under the lease fence (Plan H ruling 6), without a database: a moved fence is the handle refusal on both
sides of SENT, and the side alone decides the answer.

Catches: a stale fence before SENT that sends anyway (it must stay an honest INVALID_HANDLE: nothing was sent), and a
stale fence after SENT that becomes an error envelope (the destination may have committed, so the only honest
answers are a recorded outcome or UNKNOWN; Plan E final review I1).
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from ops_core import persistence
from ops_core.outcomes import ActionOutcome, Receipt, ToolOutcome
from ops_mcp_write import destination, execution
from ops_mcp_write.server import outcome_envelope

ACTION = uuid4()
GRANT = persistence.Grant(
    action_id=ACTION,
    run_id=uuid4(),
    proposal_id=uuid4(),
    tenant_id=uuid4(),
    conversation_id=uuid4(),
    payload_sha256="a" * 64,
    payload_canonical=b"{}",
    attempt_state="INTENT",
    detail=None,
)
SUCCEEDED = ActionOutcome(
    status=ToolOutcome.SUCCEEDED,
    action_id=ACTION,
    payload_sha256="a" * 64,
    receipt=Receipt(receipt_id=uuid4(), incident_id="INC-000001", committed_at=datetime(2026, 10, 15, tzinfo=UTC)),
    tombstone=None,
    reason=None,
)


class FakeSession:
    @asynccontextmanager
    async def unit(self, tenant_id: Any = None) -> AsyncIterator[object]:
        yield object()


class FakeToken:
    async def token(self) -> str:
        return "workload-token"


def deps() -> execution.Deps:
    session: Any = FakeSession()
    http: Any = None
    token: Any = FakeToken()
    return execution.Deps(session=session, http=http, destination_url="http://127.0.0.1:9", destination_token=token)


def test_a_moved_fence_before_sent_refuses_and_sends_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    posts: list[int] = []

    async def grant(_conn: Any, **_: Any) -> persistence.Grant:
        return GRANT

    async def stale_mark_sent(_conn: Any, *, handle: str, azp: str, action_id: Any) -> str:
        raise persistence.HandleRejected("invocation handle rejected")

    async def post(*_: Any, **__: Any) -> None:
        posts.append(1)

    monkeypatch.setattr(persistence, "grant_execution", grant)
    monkeypatch.setattr(persistence, "mark_sent", stale_mark_sent)
    monkeypatch.setattr(destination, "post_incident", post)
    with pytest.raises(persistence.HandleRejected):  # server.py answers INVALID_HANDLE for exactly this
        asyncio.run(execution.create_incident(deps(), handle="h", azp="ops-worker", proposal_id=uuid4()))
    assert posts == []


def test_a_moved_fence_after_sent_is_unknown_never_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def grant(_conn: Any, **_: Any) -> persistence.Grant:
        return GRANT

    async def mark_sent(_conn: Any, *, handle: str, azp: str, action_id: Any) -> str:
        return "sent"

    async def post(*_: Any, **__: Any) -> destination.Reply:
        return destination.Reply(200, {})

    async def stale_record(_conn: Any, *, handle: str, azp: str, action_id: Any, outcome: ActionOutcome) -> ToolOutcome:
        raise persistence.HandleRejected("invocation handle rejected")

    monkeypatch.setattr(persistence, "grant_execution", grant)
    monkeypatch.setattr(persistence, "mark_sent", mark_sent)
    monkeypatch.setattr(destination, "post_incident", post)
    monkeypatch.setattr(destination, "classify", lambda *_, **__: SUCCEEDED)
    monkeypatch.setattr(persistence, "record_outcome", stale_record)
    outcome = asyncio.run(execution.create_incident(deps(), handle="h", azp="ops-worker", proposal_id=uuid4()))
    doc = outcome_envelope(outcome)
    assert outcome.status is ToolOutcome.UNKNOWN and doc["status"] == "outcome" and doc["error"] is None

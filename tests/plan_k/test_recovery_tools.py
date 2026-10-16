"""The recovery calls and the abort branch of `create_incident`, without a database or a destination (AM-13 recovery
table; SA:348, SA:465; Plan K rulings 3, 10, 18, 19 and 24).

The definers are scripted stand-ins that record their calls; the destination calls are scripted too, except where the
real request is built against `httpx2.MockTransport`. Catches: a cancelled or expired attempt answered UNKNOWN (the old
conservative branch) or POSTed instead of aborted; an abort POSTed before its request was recorded, or with a reason
the function did not choose; anything sent once an abort request exists; an answer of `mark_sent` the code does not
know read as "go ahead"; a re-send of a SENT attempt that skips mark_sent's checks (round 1, I1), or a recover job's
re-send; a lookup or an abort that records UNKNOWN, a 404 or a 429 recorded as anything but UNKNOWN; a
receipt for another hash accepted; a resolved attempt that calls the destination again; a recovery call for another
proposal served; the tombstone's reason mapped to the wrong FAILED reason; and requests that do not carry the workload
token, the right path, method or body.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import httpx2
import pytest
from ops_core import persistence
from ops_core.outcomes import ActionOutcome, ToolOutcome
from ops_core.states import Reason
from ops_mcp_write import destination, execution

ACTION = UUID(int=21)
PROPOSAL = UUID(int=22)
SHA = "c" * 64
RECEIPT = {"receipt_id": str(UUID(int=23)), "incident_id": "INC-000021", "committed_at": "2026-10-16T12:00:00Z"}
DECIDED = "2026-10-16T12:00:00Z"


def grant(attempt: str, detail: dict[str, Any] | None = None, proposal: UUID = PROPOSAL) -> persistence.Grant:
    return persistence.Grant(
        action_id=ACTION,
        run_id=UUID(int=24),
        proposal_id=proposal,
        tenant_id=UUID(int=25),
        conversation_id=UUID(int=26),
        payload_sha256=SHA,
        payload_canonical=b'{"x":1}',
        attempt_state=attempt,
        detail=detail,
    )


def committed(sha: str = SHA) -> destination.Reply:
    return destination.Reply(
        200, {"state": "COMMITTED", "action_id": str(ACTION), "payload_sha256": sha, "receipt": RECEIPT}
    )


def tombstone(state: str, reason: str) -> destination.Reply:
    stone = {"action_id": str(ACTION), "state": state, "payload_sha256": SHA, "reason": reason, "decided_at": DECIDED}
    return destination.Reply(200, {"state": state, "action_id": str(ACTION), "payload_sha256": SHA, "tombstone": stone})


class Script:
    """Scripted definers and destination calls; `calls` is the order they ran in."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, attempt: str, **answers: Any) -> None:
        self.calls: list[str] = []
        self.answers = answers
        self.recorded: list[ActionOutcome] = []
        self.grant = grant(attempt, answers.get("detail"), answers.get("proposal", PROPOSAL))
        self.abort_reasons: list[str] = []
        for name in ("grant_execution", "lookup_action", "mark_sent", "request_abort", "record_outcome"):
            monkeypatch.setattr(persistence, name, self.definer(name))
        for name in ("post_incident", "get_action", "post_abort"):
            monkeypatch.setattr(destination, name, self.request(name))

    def definer(self, name: str) -> Any:
        async def call(_conn: Any, **kwargs: Any) -> Any:
            self.calls.append(name)
            assert kwargs["azp"] == "ops-worker"  # every definer gets the token's azp (revision 0010)
            if name in ("grant_execution", "lookup_action"):
                return self.grant
            if name == "record_outcome":
                self.recorded.append(kwargs["outcome"])
                return kwargs["outcome"].status
            return self.answers[name]

        return call

    def request(self, name: str) -> Any:
        async def call(_http: Any, **kwargs: Any) -> Any:
            self.calls.append(name)
            if name == "post_abort":
                self.abort_reasons.append(kwargs["reason"])
            return self.answers.get(name)

        return call


class FakeSession:
    @asynccontextmanager
    async def unit(self, tenant_id: Any = None) -> AsyncIterator[object]:
        yield object()


class FakeToken:
    async def token(self) -> str:
        return "workload-token"


def deps() -> execution.Deps:
    session: Any = FakeSession()
    token: Any = FakeToken()
    http: Any = None
    return execution.Deps(session=session, http=http, destination_url="http://127.0.0.1:9", destination_token=token)


def create(script: Script) -> ActionOutcome:
    return asyncio.run(execution.create_incident(deps(), handle="h", azp="ops-worker", proposal_id=PROPOSAL))


def receipt(script: Script, proposal: UUID = PROPOSAL) -> ActionOutcome:
    return asyncio.run(execution.get_incident_receipt(deps(), handle="h", azp="ops-worker", proposal_id=proposal))


def abort(script: Script, proposal: UUID = PROPOSAL) -> ActionOutcome:
    return asyncio.run(execution.abort_incident(deps(), handle="h", azp="ops-worker", proposal_id=proposal))


@pytest.mark.parametrize(
    ("answer", "token", "reason"),
    [("cancelled", "cancelled_before_send", Reason.CANCELLED_BEFORE_SEND), ("expired", "expired", Reason.EXPIRED)],
)
def test_a_cancelled_or_expired_attempt_is_aborted_and_ends_without_commit(
    monkeypatch: pytest.MonkeyPatch, answer: str, token: str, reason: Reason
) -> None:
    script = Script(
        monkeypatch, attempt="INTENT", mark_sent=answer, request_abort=token, post_abort=tombstone("ABORTED", token)
    )
    outcome = create(script)
    assert script.calls == ["grant_execution", "mark_sent", "request_abort", "post_abort", "record_outcome"]
    assert script.abort_reasons == [token]  # the reason request_abort chose, never one this code made up
    assert outcome.status is ToolOutcome.FAILED_NO_COMMIT and outcome.reason is reason
    assert outcome.tombstone is not None and outcome.tombstone.reason == token
    assert script.recorded == [outcome]


def test_an_abort_without_an_answer_is_unknown_and_recorded_by_nobody(monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script(monkeypatch, attempt="INTENT", mark_sent="cancelled", request_abort="cancelled_before_send")
    outcome = create(script)  # post_abort answers None: the transport gave nothing usable
    assert outcome.status is ToolOutcome.UNKNOWN and script.recorded == []
    assert script.calls == ["grant_execution", "mark_sent", "request_abort", "post_abort"]


def test_nothing_is_sent_once_an_abort_is_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    already = Script(monkeypatch, attempt="ABORT_REQUESTED")
    assert create(already).status is ToolOutcome.UNKNOWN and already.calls == ["grant_execution"]
    meanwhile = Script(monkeypatch, attempt="INTENT", mark_sent="abort_requested")
    assert create(meanwhile).status is ToolOutcome.UNKNOWN
    assert meanwhile.calls == ["grant_execution", "mark_sent"]


@pytest.mark.parametrize("answer", ["cancelled", "expired"])
def test_a_re_send_after_a_cancel_or_past_the_deadline_is_aborted_not_sent(
    monkeypatch: pytest.MonkeyPatch, answer: str
) -> None:
    """Round 1, I1: a SENT attempt is re-sent only through mark_sent, and its `cancelled`/`expired` answer leads to the
    immediate abort (`deadline`, SA:248), never to a second POST."""
    script = Script(
        monkeypatch,
        attempt="SENT",
        mark_sent=answer,
        request_abort="deadline",
        post_abort=tombstone("ABORTED", "deadline"),
    )
    outcome = create(script)
    assert script.calls == ["grant_execution", "mark_sent", "request_abort", "post_abort", "record_outcome"]
    assert outcome.status is ToolOutcome.FAILED_NO_COMMIT and outcome.reason is Reason.ABORTED_NO_COMMIT


def test_a_due_re_send_goes_through_mark_sent_and_posts_the_same_action(monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script(monkeypatch, attempt="SENT", mark_sent="already_sent", post_incident=committed())
    assert create(script).status is ToolOutcome.SUCCEEDED
    assert script.calls == ["grant_execution", "mark_sent", "post_incident", "record_outcome"]


def test_a_recover_job_never_re_sends(monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script(monkeypatch, attempt="SENT", mark_sent="not_redispatchable")
    with pytest.raises(persistence.Refused) as refused:  # server.py answers the plain NOT_REDISPATCHABLE error
        create(script)
    assert refused.value.code == "NOT_REDISPATCHABLE" and script.calls == ["grant_execution", "mark_sent"]


def test_an_answer_mark_sent_never_gives_is_never_read_as_go_ahead(monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script(monkeypatch, attempt="INTENT", mark_sent="maybe")
    with pytest.raises(persistence.PersistenceError, match="mark_sent answered maybe"):
        create(script)
    assert script.calls == ["grant_execution", "mark_sent"]


def test_the_receipt_lookup_records_what_the_destination_holds(monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script(monkeypatch, attempt="SENT", get_action=committed())
    outcome = receipt(script)
    assert outcome.status is ToolOutcome.SUCCEEDED and outcome.receipt is not None
    assert script.calls == ["lookup_action", "get_action", "record_outcome"]  # one GET; no POST of any kind


@pytest.mark.parametrize(
    "reply",
    [
        None,  # a lost reply or a timeout
        destination.Reply(404, {"code": "NOT_FOUND"}),  # no key yet (delay_receipt): never a no-commit (SA:269)
        destination.Reply(429, {"code": "RATE_LIMITED"}),
        destination.Reply(503, {"code": "UNAVAILABLE"}),
    ],
    ids=["none", "404", "429", "503"],
)
def test_a_lookup_without_a_key_is_unknown_and_recorded_by_nobody(
    monkeypatch: pytest.MonkeyPatch, reply: destination.Reply | None
) -> None:
    script = Script(monkeypatch, attempt="SENT", get_action=reply)
    assert receipt(script).status is ToolOutcome.UNKNOWN
    assert script.calls == ["lookup_action", "get_action"] and script.recorded == []


def test_a_receipt_for_another_hash_is_recorded_as_a_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script(monkeypatch, attempt="SENT", get_action=committed(sha="d" * 64))
    outcome = receipt(script)
    assert outcome.status is ToolOutcome.CONFLICT and script.recorded == [outcome]  # never success (SA:358)


def test_a_resolved_attempt_answers_its_stored_outcome_without_a_call(monkeypatch: pytest.MonkeyPatch) -> None:
    stored = {"status": "SUCCEEDED", "action_id": str(ACTION), "payload_sha256": SHA, "receipt": RECEIPT}
    stored |= {"tombstone": None, "reason": None}
    for call in (receipt, abort):
        script = Script(monkeypatch, attempt="RESOLVED", detail=stored)
        assert call(script).status is ToolOutcome.SUCCEEDED and script.calls == ["lookup_action"]


@pytest.mark.parametrize(
    ("reply", "status", "reason"),
    [
        (committed(), ToolOutcome.SUCCEEDED, None),  # the abort met the receipt already there (SA:242)
        (tombstone("ABORTED", "deadline"), ToolOutcome.FAILED_NO_COMMIT, Reason.ABORTED_NO_COMMIT),
        (tombstone("REJECTED", "policy"), ToolOutcome.FAILED_NO_COMMIT, Reason.REJECTED),
    ],
    ids=["receipt", "fresh-tombstone", "rejected"],
)
def test_an_abort_after_send_records_what_the_destination_answered(
    monkeypatch: pytest.MonkeyPatch, reply: destination.Reply, status: ToolOutcome, reason: Reason | None
) -> None:
    script = Script(monkeypatch, attempt="SENT", request_abort="deadline", post_abort=reply)
    outcome = abort(script)
    assert outcome.status is status and outcome.reason is reason and script.recorded == [outcome]
    assert script.calls == ["lookup_action", "request_abort", "post_abort", "record_outcome"]
    assert script.abort_reasons == ["deadline"]


def test_an_abort_that_is_not_due_sends_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script(monkeypatch, attempt="SENT")

    async def not_due(_conn: Any, **_: Any) -> str:
        script.calls.append("request_abort")
        raise persistence.Refused("ABORT_NOT_DUE")

    monkeypatch.setattr(persistence, "request_abort", not_due)
    with pytest.raises(persistence.Refused):  # server.py answers the plain, retryable ABORT_NOT_DUE
        abort(script)
    assert script.calls == ["lookup_action", "request_abort"]


def test_a_recovery_call_for_another_proposal_is_refused_before_any_call(monkeypatch: pytest.MonkeyPatch) -> None:
    for call in (receipt, abort):
        script = Script(monkeypatch, attempt="SENT", proposal=UUID(int=99))
        with pytest.raises(persistence.Refused) as refused:
            call(script)
        assert refused.value.code == "OTHER_PROPOSAL" and script.calls == ["lookup_action"]  # SA:538


@pytest.mark.parametrize(
    ("state", "token", "reason"),
    [
        ("ABORTED", "cancelled_before_send", Reason.CANCELLED_BEFORE_SEND),
        ("ABORTED", "expired", Reason.EXPIRED),
        ("ABORTED", "deadline", Reason.ABORTED_NO_COMMIT),
        ("ABORTED", "aborted", Reason.ABORTED_NO_COMMIT),  # a reason this code did not choose proves only no commit
        ("REJECTED", "policy", Reason.REJECTED),
    ],
)
def test_the_tombstones_reason_says_whether_the_attempt_was_ever_sent(state: str, token: str, reason: Reason) -> None:
    outcome = destination.classify(tombstone(state, token), action_id=ACTION, payload_sha256=SHA)
    assert outcome.status is ToolOutcome.FAILED_NO_COMMIT and outcome.reason is reason


def test_the_requests_carry_the_workload_token_path_and_body() -> None:
    seen: list[httpx2.Request] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(429, json={"code": "RATE_LIMITED"})

    async def run() -> list[destination.Reply | None]:
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(answer)) as http:
            url, token = "http://sim", "workload-token"
            return [
                await destination.get_action(http, url=url, token=token, action_id=ACTION),
                await destination.post_abort(
                    http, url=url, token=token, action_id=ACTION, payload_sha256=SHA, reason="expired"
                ),
            ]

    replies = asyncio.run(run())
    assert [(r.method, r.url.path) for r in seen] == [
        ("GET", f"/internal/actions/{ACTION}"),
        ("POST", f"/internal/actions/{ACTION}/abort"),
    ]
    assert all(r.headers["authorization"] == "Bearer workload-token" for r in seen)
    assert seen[0].content == b"" and json.loads(seen[1].content) == {"payload_sha256": SHA, "reason": "expired"}
    assert seen[1].extensions["timeout"]["read"] == 10.0  # one request per call; the backoff is the worker's (T22)
    assert all(r is not None and r.status_code == 429 for r in replies)
    statuses = [destination.classify(r, action_id=ACTION, payload_sha256=SHA).status for r in replies]
    assert statuses == [ToolOutcome.UNKNOWN, ToolOutcome.UNKNOWN]  # a rate limit at either call proves nothing

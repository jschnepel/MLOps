"""The admission units of `ops_api.store.AdmissionStore` over the in-memory `Unit` (Plan G rulings 4-7, 9-15, 18,
24): what each route writes in one unit, what it records, and what it leaves behind when it fails.

Catches: a 202 whose record was not written in the same unit (a replay would start a second run), a changed body
replayed instead of refused, a quota that refuses status questions or whose 429 is recorded (a retry after the queue
drains must be admitted), a status answer or a clarification that starts a run, writes a job or an event (R017,
R018), a lost slot race that leaves the loser's message behind, a fault before commit that keeps anything (R015) or
tells the client not to retry, an expired unpurged key that replays its old answer, a clarification reply bound to a
stale version, a superseded question or another question, checked before `DbUnit`'s SQL locks the run (or with an
INSERT before the refusal) or answered by another requester, and a reviewer refusal that gets recorded.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from ops_api.idempotency import Idem, IdempotencyConflict, QueueFull, Scope, Verdict, fingerprint
from ops_api.store import DbUnit, Forbidden, ReplyRefused, resolve_interval
from ops_core.contracts import ClarificationReply, DecisionRequest, MessageRequest, load
from ops_core.settings import Profile
from ops_core.testing.faults import FaultKind, Faults

from tests.plan_g.fakes import ALEX, ALPHA, CASEY, SAM, FakeStore

MESSAGES = "POST /api/v1/conversations/{conversation_id}/messages"
REPLIES = "POST /api/v1/runs/{run_id}/clarifications"
SAMPLE = {
    "kind": "investigate",
    "text": "Investigate the alerts on Asset A17 over the last 24 hours.",
    "context": {"asset_id": "A17", "hours": 24},
}


def idem(route: str, key: str, path: dict[str, str], body: dict[str, Any] | None, subject: UUID = ALEX) -> Idem:
    return Idem(Scope(ALPHA, subject, route, key), fingerprint(path, body), 86400, uuid4())


def conversation(fake: FakeStore) -> UUID:
    cid = uuid4()
    fake.conversations[cid] = ALPHA
    return cid


def admit(fake: FakeStore, cid: UUID, body: dict[str, Any], key: str, quota: int = 100) -> Verdict:
    request = load(MessageRequest, json.dumps(body))  # the API's own strict JSON parse
    return asyncio.run(
        fake.admit_message(
            idem=idem(MESSAGES, key, {"conversation_id": str(cid)}, request.model_dump(mode="json")),
            tenant_id=ALPHA,
            conversation_id=cid,
            requester=ALEX,
            request=request,
            quota=quota,
        )
    )


def test_a_run_and_its_record_commit_together_and_a_replay_returns_the_record() -> None:
    fake = FakeStore()
    cid = conversation(fake)
    first = admit(fake, cid, SAMPLE, "key-0001")
    assert first.status == 202 and not first.replayed and len(fake.runs) == 1 and len(fake.records) == 1
    again = admit(fake, cid, {**SAMPLE, "text": " " + SAMPLE["text"]}, "key-0001")  # stripped: the same request
    assert again.replayed and again == first and len(fake.runs) == 1 and len(fake.messages) == 1
    assert fake.locks == [next(iter(fake.records)).lock_key] * 2  # each unit locked the scope first


def test_a_changed_body_under_the_same_key_is_a_conflict_and_writes_nothing() -> None:
    fake = FakeStore()
    cid = conversation(fake)
    admit(fake, cid, SAMPLE, "key-0001")
    with pytest.raises(IdempotencyConflict):
        admit(fake, cid, {**SAMPLE, "context": {"asset_id": "A17", "hours": 12}}, "key-0001")
    assert len(fake.runs) == 1 and len(fake.records) == 1


def test_the_quota_refuses_only_what_would_start_a_run_and_records_nothing() -> None:
    fake = FakeStore()
    busy, idle = conversation(fake), conversation(fake)
    admit(fake, busy, SAMPLE, "key-0001")  # one QUEUED run in the tenant
    with pytest.raises(QueueFull):
        admit(fake, idle, SAMPLE, "key-0002", quota=1)
    assert len(fake.runs) == 1 and len(fake.records) == 1  # transient: the 429 is nobody's record (ruling 5)
    status = admit(fake, idle, {"kind": "status", "text": "Anything running?"}, "key-0003", quota=1)
    assert status.status == 200
    later = admit(fake, idle, SAMPLE, "key-0002", quota=2)  # the quota allows it now: the same key does the work
    assert later.status == 202 and not later.replayed


def test_a_status_question_writes_two_messages_and_nothing_else_even_while_busy() -> None:
    fake = FakeStore()
    cid = conversation(fake)
    accepted = admit(fake, cid, SAMPLE, "key-0001")
    jobs, events = len(fake.jobs), len(fake.event_log)
    answered = admit(fake, cid, {"kind": "status", "text": "Where is it?"}, "key-0002")
    run_id = accepted.body["run_id"]
    assert answered.status == 200 and answered.body["run_id"] == run_id and answered.body["status"] == "QUEUED"
    assert answered.body["answer"].startswith(f"Run {run_id} is QUEUED (version 1); the last recorded event is")
    question, answer = fake.messages[-2:]
    assert (question["kind"], question["author"]) == ("status_question", ALEX)
    assert (answer["kind"], answer["author"]) == ("status_answer", None)
    assert answer["context"] == {"run_id": run_id, "reply_to": str(question["message_id"])}
    assert (len(fake.runs), len(fake.jobs), len(fake.event_log)) == (1, jobs, events)  # R017: no run, job or event


def test_a_status_question_in_an_empty_conversation_says_so() -> None:
    fake = FakeStore()
    answered = admit(fake, conversation(fake), {"kind": "status", "text": "Anything?"}, "key-0001")
    assert answered.body["answer"] == "This conversation has no runs yet." and answered.body["run_id"] is None


def test_a_clarification_stores_the_request_and_the_question_and_starts_nothing() -> None:
    fake = FakeStore()
    cid = conversation(fake)
    body = {"kind": "investigate", "text": "Investigate B22 over the last 24 hours.", "context": {"asset_id": "A17"}}
    asked = admit(fake, cid, body, "key-0001")
    assert asked.status == 200 and asked.body["status"] == "clarification_needed"
    assert asked.body["cause"] == "asset_conflict" and "A17" in asked.body["question"]
    request, question = fake.messages
    assert (request["kind"], request["author"], request["context"]) == (
        "investigate",
        ALEX,
        {"asset_id": "A17", "hours": None},
    )
    assert (question["kind"], question["author"], question["text"]) == (
        "clarification_question",
        None,
        asked.body["question"],
    )
    assert question["context"] == {"cause": "asset_conflict", "reply_to": str(request["message_id"])}
    assert not fake.runs and not fake.jobs and not fake.event_log  # R018: a stored clarification, never a job


def test_a_lost_slot_race_is_a_recorded_409_that_leaves_no_message() -> None:
    fake = FakeStore()
    cid = conversation(fake)
    fake.slot_occupied = True  # create_run's own index refusal, as a concurrent admission would cause
    lost = admit(fake, cid, SAMPLE, "key-0001")
    assert lost.status == 409 and lost.body["code"] == "SLOT_OCCUPIED"
    assert not fake.messages and not fake.runs and len(fake.records) == 1  # AM-16: only the record is written


def test_a_fault_before_commit_leaves_no_message_no_run_and_no_record() -> None:
    fake = FakeStore()
    fake.faults = Faults(Profile.TEST)
    fake.faults.arm(FaultKind.DROP_BEFORE_COMMIT)
    cid = conversation(fake)
    with pytest.raises(psycopg.OperationalError):  # what a real crash before commit looks like (ruling 24)
        admit(fake, cid, SAMPLE, "key-0001")
    assert not fake.messages and not fake.runs and not fake.jobs and not fake.records  # R015
    retried = admit(fake, cid, SAMPLE, "key-0001")  # nothing was recorded, so the same key does the work now
    assert retried.status == 202 and not retried.replayed and len(fake.jobs) == 1


def test_an_expired_record_the_sweeper_has_not_purged_blocks_its_key() -> None:
    fake = FakeStore()
    cid = conversation(fake)
    admit(fake, cid, SAMPLE, "key-0001")
    clock = fake.clock()
    fake.clock = lambda: clock + 86401  # past the replay window, before any purge
    other = conversation(fake)
    with pytest.raises(IdempotencyConflict) as refused:
        admit(fake, other, SAMPLE, "key-0001")  # the lookup misses, the insert meets the old row: the re-read path
    assert refused.value.message == "Idempotency-Key is not reusable yet; use a new key"
    assert not any(r["conversation_id"] == other for r in fake.runs.values())  # the work was rolled back


def test_the_interval_is_resolved_once_on_the_units_clock() -> None:
    fake = FakeStore()
    fixed = datetime(2026, 10, 10, 8, 30, 15, 987654, tzinfo=UTC)
    fake.clock = fixed.timestamp
    accepted = admit(fake, conversation(fake), SAMPLE, "key-0001")
    run = fake.runs[UUID(accepted.body["run_id"])]
    assert (run["start_at"], run["end_at"]) == resolve_interval(24, fixed)
    assert run["end_at"] == datetime(2026, 10, 10, 8, 30, 15, tzinfo=UTC)


def reply(fake: FakeStore, run_id: UUID, question_id: UUID, version: int, key: str, requester: UUID = ALEX) -> Verdict:
    body = load(
        ClarificationReply,
        json.dumps({"question_id": str(question_id), "expected_version": version, "context": {"hours": 12}}),
    )
    return asyncio.run(
        fake.reply_clarification(
            idem=idem(REPLIES, key, {"run_id": str(run_id)}, body.model_dump(mode="json"), requester),
            tenant_id=ALPHA,
            run_id=run_id,
            requester=requester,
            reply=body,
        )
    )


def test_a_reply_binds_to_the_outstanding_question_and_its_version() -> None:
    fake = FakeStore()
    run_id = UUID(admit(fake, conversation(fake), SAMPLE, "key-0001").body["run_id"])
    assert reply(fake, run_id, uuid4(), 1, "key-0002").status == 409  # QUEUED: no question is outstanding
    earlier = fake.seed_question(run_id)  # AWAITING_INPUT at version 3
    question = fake.seed_question(run_id)  # asked again: version 5, and the earlier question is superseded
    assert reply(fake, run_id, question, 3, "key-0003").body["code"] == "VERSION_CONFLICT"
    assert reply(fake, run_id, uuid4(), 5, "key-0004").body["message"] == "no outstanding clarification"
    superseded = reply(fake, run_id, earlier, 5, "key-0005")  # a stale version of the question: 409, not 404
    assert (superseded.status, superseded.body["message"]) == (409, "the clarification was superseded")
    assert reply(fake, uuid4(), question, 5, "key-0006").body["message"] == "no such run"
    accepted = reply(fake, run_id, question, 5, "key-0007")
    assert (
        accepted.status == 202 and accepted.body["status"] == "AWAITING_INPUT" and accepted.body["state_version"] == 5
    )
    assert fake.jobs[-1] == {"type": "resume_input", "run_id": run_id, "dedup_key": f"{run_id}:{question}"}
    assert fake.event_log[-1]["type"] == "clarification.received"
    assert (
        fake.messages[-1]["kind"] == "clarification_reply"
        and fake.messages[-1]["text"] == "Clarification: asset -, hours 12"
    )
    again = reply(fake, run_id, question, 5, "key-0008")  # a second answer under a new key
    assert again.status == 409 and again.body["message"] == "the clarification was already answered"


class Cursor:
    """One scripted answer: the row a statement returns (or None), and the rowcount that goes with it."""

    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = row
        self.rowcount = 0 if row is None else 1

    async def fetchone(self) -> dict[str, Any] | None:
        return self.row

    async def fetchall(self) -> list[dict[str, Any]]:
        return [] if self.row is None else [self.row]


class RecordingConn:
    """The connection `DbUnit` runs on, recorded: each statement's SQL text in order, each answer from the script."""

    def __init__(self, script: list[dict[str, Any] | None]) -> None:
        self.script = script
        self.statements: list[str] = []

    async def execute(self, query: str, params: Any = None) -> Cursor:
        self.statements.append(query)
        return Cursor(self.script.pop(0) if self.script else None)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        yield  # a savepoint that a refusal before it must never open


def test_the_db_reply_locks_the_run_before_it_checks_or_writes() -> None:
    """SA:186/SA:188 on the real SQL: `DbUnit.record_reply`'s first statement locks the run row, so a run whose version
    moved after the client read it (a cancel, a worker transition), or another requester's run, is refused under that
    lock and before any message, job or event is inserted; and an accepted reply takes the same lock first and then
    writes in SA:188's order, the message, the `resume_input` job, then `append_event`."""
    run_id = uuid4()
    moved = {  # AWAITING_INPUT, but at version 4: the client read version 3
        "run_id": run_id,
        "state": "AWAITING_INPUT",
        "state_version": 4,
        "requester": ALEX,
        "conversation_id": uuid4(),
    }
    for requester, refused in ((ALEX, ReplyRefused), (CASEY, Forbidden)):
        conn = RecordingConn([dict(moved)])
        with pytest.raises(refused):
            asyncio.run(
                DbUnit(conn, ALPHA).record_reply(  # the recording stand-in, never a real connection
                    run_id=run_id,
                    requester=requester,
                    question_id=uuid4(),
                    expected_version=3,
                    text="Clarification: asset -, hours 12",
                    context={"hours": 12},
                )
            )
        first = conn.statements[0]
        assert "FROM app.runs" in first and "FOR UPDATE" in first, first
        assert len(conn.statements) == 1 and not any("INSERT" in s for s in conn.statements), conn.statements
    question_id = uuid4()
    waiting = {**moved, "state_version": 3}  # the version the client read
    appended = {"event_id": uuid4(), "sequence": 7, "occurred_at": datetime(2026, 10, 10, tzinfo=UTC)}
    # The script, statement by statement: the locked run, its one question, the message INSERT, the job INSERT that
    # queued (a non-empty answer is rowcount 1), and append_event's row.
    conn = RecordingConn([waiting, {"event_id": question_id}, None, {}, appended])
    accepted = asyncio.run(
        DbUnit(conn, ALPHA).record_reply(
            run_id=run_id,
            requester=ALEX,
            question_id=question_id,
            expected_version=3,
            text="Clarification: asset -, hours 12",
            context={"hours": 12},
        )
    )
    assert (accepted.status, accepted.state_version) == ("AWAITING_INPUT", 3)
    first = conn.statements[0]
    assert "FROM app.runs" in first and "FOR UPDATE" in first, first
    writes = [
        next(i for i, s in enumerate(conn.statements) if marker in s)
        for marker in ("INSERT INTO app.messages", "INSERT INTO app.jobs", "app.append_event")
    ]
    assert 0 < writes[0] < writes[1] < writes[2] == len(conn.statements) - 1, conn.statements


def test_only_the_runs_requester_may_answer_its_question() -> None:
    """A reply shapes the run's draft (SA:539: its author must not later review it). Another requester of the tenant
    may read the run, so the refusal is BS:301's 403 for a known resource and a disallowed operation, raised and never
    recorded (ruling 5), and nothing is written."""
    fake = FakeStore()
    run_id = UUID(admit(fake, conversation(fake), SAMPLE, "key-0001").body["run_id"])
    question = fake.seed_question(run_id)
    with pytest.raises(Forbidden):
        reply(fake, run_id, question, 3, "key-0002", requester=CASEY)
    assert not any(j["type"] == "resume_input" for j in fake.jobs) and len(fake.records) == 1  # the admission's only


def decide(fake: FakeStore, proposal_id: UUID, subject: UUID, roles: frozenset[str], key: str) -> Verdict:
    body = DecisionRequest(expected_revision=1, expected_payload_sha256="9" * 64, decision="approve")
    return asyncio.run(
        fake.decide_once(
            idem=idem(
                "POST /api/v1/proposals/{proposal_id}/decisions",
                key,
                {"proposal_id": str(proposal_id)},
                body.model_dump(mode="json"),
                subject,
            ),
            tenant_id=ALPHA,
            proposal_id=proposal_id,
            reviewer=subject,
            roles=roles,
            request=body,
        )
    )


def test_a_decision_carries_its_key_and_a_reviewer_refusal_is_never_recorded() -> None:
    fake = FakeStore()
    pid, rid = uuid4(), uuid4()
    fake.proposals[pid] = {
        "proposal_id": pid,
        "tenant_id": ALPHA,
        "run_id": rid,
        "revision": 1,
        "payload_sha256": "9" * 64,
        "authored_by": [ALEX],
        "requester": ALEX,
    }
    with pytest.raises(Forbidden):
        decide(fake, pid, ALEX, frozenset({"requester"}), "key-0001")
    assert not fake.records and not fake.decided
    decided = decide(fake, pid, SAM, frozenset({"reviewer"}), "key-0002")
    assert decided.status == 200 and decided.body["status"] == "APPROVED" and fake.decision_keys[pid] == "key-0002"
    assert decide(fake, pid, SAM, frozenset({"reviewer"}), "key-0003").status == 409  # the first decision won

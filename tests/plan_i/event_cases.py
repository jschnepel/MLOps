"""One table of event cases with the verdict all three layers must give (Plan I ruling 4): the JSON schema
(schemas/event.schema.json), `ops_core.outcomes.event_rules_ok` and, from revision 0008 on, `app._append_event`.

Every payload is well formed for the schema's per-key shapes (uuids, enums, lengths), so a case is decided only by
the authority rules the three layers share: who may assert what, which keys exist, and which types carry a `status`.
tests/plan_i/test_event_rules.py checks the schema and the Python twin against it without a database;
tests/e2e/test_migration_0008_live.py checks the SQL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ACTION = "00000000-0000-4000-8000-000000000007"
PROPOSAL = "00000000-0000-4000-8000-000000000004"
QUESTION = "00000000-0000-4000-8000-000000000005"
MESSAGE = "00000000-0000-4000-8000-00000000000b"
OUTBOX = "00000000-0000-4000-8000-00000000000c"
RECEIPT = {
    "receipt_id": "00000000-0000-4000-8000-000000000008",
    "incident_id": "INC-SYNTHETIC-0001",
    "committed_at": "2026-10-06T12:04:00Z",
}
TOMBSTONE = {
    "action_id": ACTION,
    "state": "REJECTED",
    "payload_sha256": "9d5c1fb0f7ef65456f4ccf76396564e6290ecd530e58d2b32024e64079134cf7",
    "reason": "rejected by the destination",
    "decided_at": "2026-10-06T12:04:00Z",
}


@dataclass(frozen=True)
class Case:
    """One (type, source, payload) and whether every layer accepts it."""

    name: str
    type: str
    source: str
    payload: Any
    ok: bool


CASES = (
    Case("tool event", "tool.started", "application", {"message": "search_procedures"}, True),
    Case("empty payload", "tool.completed", "application", {}, True),
    Case(
        "clarification reply",
        "clarification.received",
        "application",
        {"question_id": QUESTION, "message_id": MESSAGE},
        True,
    ),
    Case(
        "dead letter",
        "notification.failed",
        "application",
        {"code": "notification_dead_letter", "message": "not delivered", "outbox_id": OUTBOX},
        True,
    ),
    Case("model summary", "explanation.ready", "model_summary", {"message": "why", "evidence_refs": ["a:v1:s"]}, True),
    Case(
        "confirmed",
        "action.confirmed",
        "destination",
        {"status": "SUCCEEDED", "action_id": ACTION, "receipt": RECEIPT},
        True,
    ),
    Case(
        "failed with proof",
        "action.failed",
        "destination",
        {"action_id": ACTION, "reason": "rejected", "tombstone": TOMBSTONE},
        True,
    ),
    Case(
        "failed with status",
        "action.failed",
        "destination",
        {"status": "FAILED", "action_id": ACTION, "reason": "expired"},
        True,
    ),
    Case("conflict with status", "action.conflict", "destination", {"action_id": ACTION, "status": "ESCALATED"}, True),
    Case("proposal ready", "proposal.ready", "application", {"proposal_id": PROPOSAL}, True),
    Case("run failed", "run.failed", "application", {"message": "retrieval failed"}, True),
    # T14 review note 2: a status is the destination's assertion; application events never carry one.
    Case(
        "status on tool.completed",
        "tool.completed",
        "application",
        {"message": "search_procedures", "status": "SUCCEEDED"},
        False,
    ),
    Case("status on tool.started", "tool.started", "application", {"status": "RETRIEVING"}, False),
    Case("status on run.failed", "run.failed", "application", {"status": "FAILED"}, False),
    Case(
        "status on action.granted",
        "action.granted",
        "application",
        {"action_id": ACTION, "proposal_id": PROPOSAL, "status": "EXECUTING"},
        False,
    ),
    Case(
        "status from the model", "explanation.ready", "model_summary", {"message": "why", "status": "SUCCEEDED"}, False
    ),
    # The payload is closed: a key the schema does not define is refused everywhere (ruling 4).
    Case("unknown key", "clarification.received", "application", {"question_id": QUESTION, "colour": "red"}, False),
    Case("recipient in a payload", "notification.failed", "application", {"code": "x", "recipient": "someone"}, False),
    Case("payload not an object", "tool.started", "application", ["search_procedures"], False),
)


def event_document(case: Case) -> dict[str, Any]:
    """The whole event the schema validates, around the case's type, source and payload."""
    return {
        "event_id": "00000000-0000-4000-8000-000000000006",
        "tenant_id": "00000000-0000-4000-8000-000000000001",
        "conversation_id": "00000000-0000-4000-8000-000000000002",
        "run_id": "00000000-0000-4000-8000-000000000003",
        "sequence": 2,
        "type": case.type,
        "occurred_at": "2026-10-06T12:04:01Z",
        "source": case.source,
        "payload": case.payload,
    }

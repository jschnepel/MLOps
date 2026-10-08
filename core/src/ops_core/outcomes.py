"""Destination results, tool outcomes, the tombstone, and the event source rules (AM-13, AM-14).

Only destination records say whether an incident exists (BUILD_SPEC §14). This module makes the three vocabularies
(destination, tool, run) and their mapping explicit, and encodes the two schema rules R083 names so code and schema
reject the same things: a model never asserts an outcome, and a confirmed action always carries a receipt.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from enum import StrEnum
from typing import Final, assert_never
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator

from ops_core.states import Reason, RunState


class DestinationState(StrEnum):
    """The destination's permanent key states (AM-13 "Destination")."""

    COMMITTED = "COMMITTED"
    ABORTED = "ABORTED"
    REJECTED = "REJECTED"


class ToolOutcome(StrEnum):
    """What a write tool reports to the worker (AM-13 "Outcome vocabulary")."""

    SUCCEEDED = "SUCCEEDED"
    FAILED_NO_COMMIT = "FAILED_NO_COMMIT"
    UNKNOWN = "UNKNOWN"
    CONFLICT = "CONFLICT"


FAILED_NO_COMMIT_REASONS: Final = frozenset(
    {Reason.ABORTED_NO_COMMIT, Reason.CANCELLED_BEFORE_SEND, Reason.REJECTED, Reason.EXPIRED}
)  # AM-13 outcome vocabulary plus `expired` (plan ruling 2)


def outcome_from_destination(
    state: DestinationState, *, sent: bool, cancel_requested: bool
) -> tuple[ToolOutcome, Reason | None]:
    """Map a destination result to the tool outcome and the FAILED reason (AM-13 recovery table).

    `sent` is the hinge: an attempt still in INTENT was definitely not sent (`mark_sent` commits SENT before any
    network I/O, AM-13 attempt protocol), so an ABORTED key from INTENT proves the request never left, and the reason
    says why it was aborted: `cancelled_before_send` after a cancel, otherwise `expired` (the dispatch deadline
    passed). After SENT, a fresh ABORTED tombstone only proves nothing committed, so the reason is
    `aborted_no_commit` even when a cancel triggered the abort; claiming "cancelled before send" there would be false.

    Args:
        state: the destination key state from the receipt or tombstone.
        sent: whether the attempt reached SENT before the abort.
        cancel_requested: whether the run's cancel flag was set when the abort was requested.
    """
    if state is DestinationState.COMMITTED:
        return ToolOutcome.SUCCEEDED, None
    if state is DestinationState.REJECTED:
        return ToolOutcome.FAILED_NO_COMMIT, Reason.REJECTED
    if sent:
        return ToolOutcome.FAILED_NO_COMMIT, Reason.ABORTED_NO_COMMIT
    return ToolOutcome.FAILED_NO_COMMIT, Reason.CANCELLED_BEFORE_SEND if cancel_requested else Reason.EXPIRED


_Strict = ConfigDict(frozen=True, extra="forbid", strict=True)


class Receipt(BaseModel):
    """Proof that the destination committed the action (AM-13)."""

    model_config = _Strict
    receipt_id: UUID
    incident_id: str = Field(min_length=1, max_length=100)
    committed_at: AwareDatetime


class Tombstone(BaseModel):
    """What the destination returns for an ABORTED or REJECTED key (AM-13 "Tombstone shape"); never for COMMITTED."""

    model_config = _Strict
    action_id: UUID
    state: DestinationState
    payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: str = Field(min_length=1, max_length=500)
    decided_at: AwareDatetime

    @model_validator(mode="after")
    def _not_committed(self) -> Tombstone:
        if self.state is DestinationState.COMMITTED:
            raise ValueError("a COMMITTED key has a receipt, not a tombstone")
        return self


class ActionOutcome(BaseModel):
    """A write tool's result data (AM-15 envelope/data agreement): the status and its evidence must agree."""

    model_config = _Strict
    status: ToolOutcome
    action_id: UUID
    payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    receipt: Receipt | None
    tombstone: Tombstone | None
    reason: Reason | None

    @model_validator(mode="after")
    def _evidence_matches_status(self) -> ActionOutcome:
        match self.status:
            case ToolOutcome.SUCCEEDED:
                if self.receipt is None or self.tombstone is not None or self.reason is not None:
                    raise ValueError("SUCCEEDED carries exactly a receipt")
            case ToolOutcome.FAILED_NO_COMMIT:
                if self.tombstone is None or self.receipt is not None or self.reason not in FAILED_NO_COMMIT_REASONS:
                    raise ValueError("FAILED_NO_COMMIT carries a tombstone and a reason from the FAILED set")
                self._check_tombstone(self.tombstone, self.reason)
            case ToolOutcome.UNKNOWN | ToolOutcome.CONFLICT:  # nothing is proven either way
                if self.receipt is not None or self.tombstone is not None or self.reason is not None:
                    raise ValueError(f"{self.status} carries no receipt, tombstone or reason")
            case _:
                assert_never(self.status)
        return self

    def _check_tombstone(self, tombstone: Tombstone, reason: Reason | None) -> None:
        # The tombstone is the destination's proof; if it names another action or payload, or a state that the claimed
        # reason contradicts, the outcome would assert something its own evidence does not support.
        if tombstone.action_id != self.action_id or tombstone.payload_sha256 != self.payload_sha256:
            raise ValueError("tombstone belongs to a different action or payload")
        if (tombstone.state is DestinationState.REJECTED) != (reason is Reason.REJECTED):
            raise ValueError("tombstone state and reason disagree (REJECTED if and only if reason rejected)")


class EventSource(StrEnum):
    """Who asserts an event (AM-14 "Who may assert outcomes")."""

    APPLICATION = "application"
    DESTINATION = "destination"
    MODEL_SUMMARY = "model_summary"


class EventType(StrEnum):
    """The 27 event types: BUILD_SPEC §15's 13 plus AM-14's 14."""

    # BUILD_SPEC §15
    RUN_ACCEPTED = "run.accepted"
    CLARIFICATION_REQUESTED = "clarification.requested"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    PROPOSAL_READY = "proposal.ready"
    APPROVAL_RECORDED = "approval.recorded"
    ACTION_DISPATCHED = "action.dispatched"
    ACTION_UNCERTAIN = "action.uncertain"
    ACTION_CONFIRMED = "action.confirmed"
    RUN_FAILED = "run.failed"
    RUN_CANCELLED = "run.cancelled"
    NOTIFICATION_FAILED = "notification.failed"
    FEEDBACK_RECORDED = "feedback.recorded"
    # AM-14
    CLARIFICATION_RECEIVED = "clarification.received"
    PROPOSAL_REVISED = "proposal.revised"
    REVIEW_BLOCKED = "review.blocked"
    RUN_ANSWERED = "run.answered"
    RUN_INSUFFICIENT_EVIDENCE = "run.insufficient_evidence"
    RUN_REJECTED = "run.rejected"
    ACTION_GRANTED = "action.granted"
    ACTION_REDISPATCHED = "action.redispatched"
    ACTION_FAILED = "action.failed"
    ACTION_CONFLICT = "action.conflict"
    RUN_ESCALATED = "run.escalated"
    RUN_ABANDONED_UNVERIFIED = "run.abandoned_unverified"
    ACTION_LATE_EVIDENCE = "action.late_evidence"
    EXPLANATION_READY = "explanation.ready"


DESTINATION_EVIDENCE: Final = frozenset(
    {EventType.ACTION_CONFIRMED, EventType.ACTION_FAILED, EventType.ACTION_CONFLICT, EventType.ACTION_LATE_EVIDENCE}
)  # AM-80 event row: the only types source=destination may emit, and they come only from record_outcome


# AM-14 (who may assert outcomes) and the event schema's rule (8): only these types vouch for outcome evidence.
OUTCOME_EVENT_TYPES: Final = frozenset(
    {EventType.ACTION_CONFIRMED, EventType.ACTION_FAILED, EventType.ACTION_LATE_EVIDENCE}
)


class EventRuleViolation(ValueError):
    """The event asserts something its source may not assert (AM-14 'who may assert outcomes')."""


def _validated(model: type[BaseModel], value: object, what: str) -> None:
    """Require `value` to be a mapping that validates as `model`, else raise EventRuleViolation."""
    if not isinstance(value, Mapping):
        raise EventRuleViolation(f"{what} must be an object")
    try:
        model.model_validate_json(json.dumps(dict(value)))
    except (ValidationError, TypeError, ValueError, RecursionError) as exc:
        # json.dumps raises TypeError on non-JSON values, ValueError on a circular reference and RecursionError on
        # absurd nesting; all three mean the evidence is malformed, and none may escape as a bare exception.
        raise EventRuleViolation(f"{what} is malformed") from exc


def event_rules_ok(event_type: EventType, source: EventSource, payload: Mapping[str, object]) -> None:
    """Raise EventRuleViolation unless (type, source, payload) obeys AM-14's authority rules.

    Code enforces who may assert what and the evidence each outcome event must carry; the shape of every other payload
    key is the JSON schema's job, so unknown keys are not rejected here (except for the closed model_summary payload).
    Evidence keys are the exception: they are an authority claim, so types that do not vouch for them refuse them,
    and each outcome type refuses the other kind of proof (a receipt on action.failed, a tombstone on
    action.confirmed).
    """
    if not isinstance(payload, Mapping):
        # Callers pass decoded JSON, which can be any value; a list or string payload asserts nothing checkable.
        raise EventRuleViolation("an event payload must be an object")
    if source is EventSource.MODEL_SUMMARY:
        # The schema's closed summary_payload, mirrored: a non-empty message, optional evidence_refs, nothing else
        # (so no status, AM-14).
        message = payload.get("message")
        refs = payload.get("evidence_refs", [])
        if (
            event_type is not EventType.EXPLANATION_READY
            or not set(payload) <= {"message", "evidence_refs"}
            or not isinstance(message, str)
            or not message
            or not isinstance(refs, list)
            or not all(isinstance(r, str) and r for r in refs)
        ):
            raise EventRuleViolation("model_summary may emit only explanation.ready with a message and evidence_refs")
        return
    # The model_summary branch returned, so the source is application or destination from here on.
    if source is EventSource.DESTINATION and event_type not in DESTINATION_EVIDENCE:
        raise EventRuleViolation(f"source=destination may not emit {event_type}")
    # AM-20.3 record_outcome emits these four, always with source=destination; append_event refuses action.* from
    # application callers, so an application-sourced copy is a forgery.
    if event_type in DESTINATION_EVIDENCE and source is not EventSource.DESTINATION:
        raise EventRuleViolation(f"{event_type} comes only from record_outcome with source=destination")
    if event_type not in OUTCOME_EVENT_TYPES and not {"outcome", "receipt", "tombstone"}.isdisjoint(payload):
        raise EventRuleViolation(
            "only action.confirmed, action.failed and action.late_evidence may carry an outcome, receipt or tombstone"
        )
    if event_type is EventType.ACTION_CONFIRMED:
        if payload.get("status") != RunState.SUCCEEDED.value:
            raise EventRuleViolation("action.confirmed requires a receipt and status SUCCEEDED")
        if "tombstone" in payload:  # a tombstone proves no commit, which contradicts the confirmation
            raise EventRuleViolation("action.confirmed carries a receipt, never a tombstone")
        _validated(Receipt, payload.get("receipt"), "action.confirmed receipt")
    if event_type is EventType.ACTION_FAILED:
        failed_reasons = {r.value for r in FAILED_NO_COMMIT_REASONS}
        if payload.get("reason") not in failed_reasons:
            raise EventRuleViolation("action.failed requires a reason from the FAILED_NO_COMMIT set")  # AM-14
        if "receipt" in payload:  # a receipt proves a commit, which contradicts the failure
            raise EventRuleViolation("action.failed never carries a receipt")
    if event_type is EventType.ACTION_LATE_EVIDENCE:
        # Late evidence arrives after the run gave up; the outcome picks which proof it must carry.
        outcome = payload.get("outcome")
        if outcome == "SUCCEEDED":
            _validated(Receipt, payload.get("receipt"), "action.late_evidence receipt")
        elif outcome == "FAILED_NO_COMMIT":
            _validated(Tombstone, payload.get("tombstone"), "action.late_evidence tombstone")
        else:
            raise EventRuleViolation("action.late_evidence requires outcome SUCCEEDED or FAILED_NO_COMMIT")

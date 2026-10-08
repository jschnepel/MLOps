"""Job types, tools, routes and the outcome vocabulary are the spec's tables (AM-13, AM-14, AM-15, AM-16, AM-20.4).

Catches: a tool allowed for the wrong job type (a read handle reaching create_incident), a dedup key format drifting
(two jobs for one proposal), an outcome that claims success without a receipt, a tombstone with the wrong state, and an
event that asserts an outcome from the wrong source (R083's model_summary probe, in code).
"""

import uuid
from datetime import UTC, datetime

import pytest
from ops_core.jobs import JOB_RULES, RECOVER_CADENCE, JobType, Server, Tool, dedup_key, server_for
from ops_core.outcomes import (
    ActionOutcome,
    DestinationState,
    EventRuleViolation,
    EventSource,
    EventType,
    Receipt,
    Tombstone,
    ToolOutcome,
    event_rules_ok,
    outcome_from_destination,
)
from ops_core.routing import AdmissionRoute, GraphRoute, ModelRoute, RunManifest
from ops_core.states import Reason, RunState
from pydantic import ValidationError

ACTION = uuid.UUID("00000000-0000-4000-8000-000000000010")
SHA = "9d5c1fb0f7ef65456f4ccf76396564e6290ecd530e58d2b32024e64079134cf7"
AT = datetime(2026, 10, 8, tzinfo=UTC)
READ_TOOLS = {Tool.GET_ASSET_STATUS, Tool.GET_RECENT_ALERTS, Tool.SEARCH_PROCEDURES}


def test_job_rules_match_am15():
    assert len(JobType) == 8 and len(Tool) == 6
    assert JOB_RULES[JobType.INVESTIGATE].allowed_tools == READ_TOOLS
    assert JOB_RULES[JobType.RESUME_INPUT].allowed_tools == READ_TOOLS
    assert JOB_RULES[JobType.EXECUTE].allowed_tools == {Tool.CREATE_INCIDENT}
    assert JOB_RULES[JobType.RECOVER].allowed_tools == {
        Tool.CREATE_INCIDENT,
        Tool.GET_INCIDENT_RECEIPT,
        Tool.ABORT_INCIDENT,
    }
    for maintenance in (
        JobType.EXPIRE_PROPOSALS,
        JobType.SYNC_MEMBERSHIPS,
        JobType.SWEEP_WAKEUPS,
        JobType.DELIVER_OUTBOX,
    ):
        assert JOB_RULES[maintenance].allowed_tools == set() and JOB_RULES[maintenance].run_states == frozenset()
    assert JOB_RULES[JobType.EXECUTE].run_states == {RunState.APPROVED, RunState.EXECUTING}
    assert JOB_RULES[JobType.RECOVER].run_states == {
        RunState.EXECUTING,
        RunState.OUTCOME_UNKNOWN,
        RunState.ESCALATED,
        RunState.ABANDONED_UNVERIFIED,
    }


def test_handles_bind_to_one_server():
    """R131: investigate/resume_input handles are read handles; execute/recover are write handles."""
    assert server_for(JobType.INVESTIGATE) is Server.READ and server_for(JobType.RESUME_INPUT) is Server.READ
    assert server_for(JobType.EXECUTE) is Server.WRITE and server_for(JobType.RECOVER) is Server.WRITE
    assert server_for(JobType.DELIVER_OUTBOX) is None


def test_dedup_keys_follow_am20_4():
    run = uuid.UUID("00000000-0000-4000-8000-000000000003")
    assert dedup_key(JobType.INVESTIGATE, run_id=run, revision=2) == f"{run}:2"
    assert dedup_key(JobType.RESUME_INPUT, run_id=run, clarification_event_id=ACTION) == f"{run}:{ACTION}"
    assert dedup_key(JobType.EXECUTE, proposal_id=ACTION) == str(ACTION)
    assert dedup_key(JobType.RECOVER, action_id=ACTION, trigger="timeout") == f"{ACTION}:timeout"
    assert (
        dedup_key(JobType.RECOVER, action_id=ACTION, trigger="sweep:2026-10-08T01:05")
        == f"{ACTION}:sweep:2026-10-08T01:05"
    )
    assert dedup_key(JobType.EXPIRE_PROPOSALS, minute_bucket="2026-10-08T01:05") == "expire_proposals:2026-10-08T01:05"
    with pytest.raises(ValueError, match="trigger"):
        dedup_key(JobType.RECOVER, action_id=ACTION, trigger="manual")
    with pytest.raises(ValueError, match="revision"):
        dedup_key(JobType.INVESTIGATE, run_id=run)
    assert RECOVER_CADENCE == (300, 3600, 48)


def test_outcome_vocabulary_and_mapping():
    assert {s.value for s in DestinationState} == {"COMMITTED", "ABORTED", "REJECTED"}
    assert {s.value for s in ToolOutcome} == {"SUCCEEDED", "FAILED_NO_COMMIT", "UNKNOWN", "CONFLICT"}
    failed = ToolOutcome.FAILED_NO_COMMIT
    for sent in (False, True):
        for cancel in (False, True):
            assert outcome_from_destination(DestinationState.COMMITTED, sent=sent, cancel_requested=cancel) == (
                ToolOutcome.SUCCEEDED,
                None,
            )
            assert outcome_from_destination(DestinationState.REJECTED, sent=sent, cancel_requested=cancel) == (
                failed,
                Reason.REJECTED,
            )
            # After SENT a fresh ABORTED tombstone proves only "no commit", whatever triggered the abort (AM-13).
            if sent:
                assert outcome_from_destination(DestinationState.ABORTED, sent=True, cancel_requested=cancel) == (
                    failed,
                    Reason.ABORTED_NO_COMMIT,
                )
    # From INTENT (never sent) the abort was either a cancel or the dispatch deadline (AM-13 recovery table).
    assert outcome_from_destination(DestinationState.ABORTED, sent=False, cancel_requested=True) == (
        failed,
        Reason.CANCELLED_BEFORE_SEND,
    )
    assert outcome_from_destination(DestinationState.ABORTED, sent=False, cancel_requested=False) == (
        failed,
        Reason.EXPIRED,
    )


def test_tombstone_shape():
    t = Tombstone(
        action_id=ACTION,
        state=DestinationState.ABORTED,
        payload_sha256=SHA,
        reason="cancelled_before_send",
        decided_at=AT,
    )
    assert t.state is DestinationState.ABORTED
    with pytest.raises(ValidationError):
        Tombstone(
            action_id=ACTION, state=DestinationState.COMMITTED, payload_sha256=SHA, reason="x", decided_at=AT
        )  # a committed key has a receipt, not a tombstone


def test_action_outcome_agreement():
    receipt = Receipt(receipt_id=ACTION, incident_id="INC-1", committed_at=AT)
    tomb = Tombstone(
        action_id=ACTION, state=DestinationState.REJECTED, payload_sha256=SHA, reason="rejected", decided_at=AT
    )
    ActionOutcome(
        status=ToolOutcome.SUCCEEDED, action_id=ACTION, payload_sha256=SHA, receipt=receipt, tombstone=None, reason=None
    )
    ActionOutcome(
        status=ToolOutcome.FAILED_NO_COMMIT,
        action_id=ACTION,
        payload_sha256=SHA,
        receipt=None,
        tombstone=tomb,
        reason=Reason.REJECTED,
    )
    ActionOutcome(
        status=ToolOutcome.UNKNOWN, action_id=ACTION, payload_sha256=SHA, receipt=None, tombstone=None, reason=None
    )
    for bad in (
        # the reference's outcome-invalid-fake-success: success without a receipt
        {"status": ToolOutcome.SUCCEEDED, "receipt": None, "tombstone": None, "reason": None},
        # outcome-invalid-unknown-receipt: a receipt on UNKNOWN
        {"status": ToolOutcome.UNKNOWN, "receipt": receipt, "tombstone": None, "reason": None},
        # a reason outside the FAILED set
        {"status": ToolOutcome.FAILED_NO_COMMIT, "receipt": None, "tombstone": tomb, "reason": Reason.CONFLICT},
        # FAILED_NO_COMMIT without its tombstone
        {"status": ToolOutcome.FAILED_NO_COMMIT, "receipt": None, "tombstone": None, "reason": Reason.REJECTED},
    ):
        with pytest.raises(ValidationError):
            ActionOutcome(action_id=ACTION, payload_sha256=SHA, **bad)


def test_event_types_and_source_rules():
    assert len(EventType) == 27
    event_rules_ok(EventType.EXPLANATION_READY, EventSource.MODEL_SUMMARY, {"message": "why"})
    with pytest.raises(EventRuleViolation):  # R083 probe: model_summary asserting a status
        event_rules_ok(
            EventType.EXPLANATION_READY, EventSource.MODEL_SUMMARY, {"message": "why", "status": "SUCCEEDED"}
        )
    with pytest.raises(EventRuleViolation):  # the summary payload is closed: message and evidence_refs only
        event_rules_ok(EventType.EXPLANATION_READY, EventSource.MODEL_SUMMARY, {"message": "why", "code": "x"})
    with pytest.raises(EventRuleViolation):  # model_summary may emit nothing else
        event_rules_ok(EventType.ACTION_CONFIRMED, EventSource.MODEL_SUMMARY, {"status": "SUCCEEDED"})
    with pytest.raises(EventRuleViolation):  # action.confirmed needs a receipt and SUCCEEDED
        event_rules_ok(EventType.ACTION_CONFIRMED, EventSource.DESTINATION, {"status": "SUCCEEDED"})
    event_rules_ok(
        EventType.ACTION_CONFIRMED,
        EventSource.DESTINATION,
        {
            "status": "SUCCEEDED",
            "receipt": {"receipt_id": str(ACTION), "incident_id": "INC-1", "committed_at": "2026-10-08T00:00:00Z"},
        },
    )
    with pytest.raises(EventRuleViolation):  # source=destination only on the four destination-evidence types
        event_rules_ok(EventType.ACTION_GRANTED, EventSource.DESTINATION, {"status": "EXECUTING"})
    with pytest.raises(EventRuleViolation):  # late evidence needs an outcome and a receipt or tombstone
        event_rules_ok(EventType.ACTION_LATE_EVIDENCE, EventSource.DESTINATION, {"status": "ABANDONED_UNVERIFIED"})
    with pytest.raises(EventRuleViolation):  # destination evidence never comes from the application
        event_rules_ok(
            EventType.ACTION_CONFIRMED,
            EventSource.APPLICATION,
            {
                "status": "SUCCEEDED",
                "receipt": {"receipt_id": str(ACTION), "incident_id": "INC-1", "committed_at": "x"},
            },
        )
    with pytest.raises(EventRuleViolation):  # action.failed says why (AM-14)
        event_rules_ok(EventType.ACTION_FAILED, EventSource.DESTINATION, {"status": "FAILED"})
    event_rules_ok(EventType.ACTION_FAILED, EventSource.DESTINATION, {"status": "FAILED", "reason": "rejected"})


def test_routes_and_manifest():
    assert {r.value for r in AdmissionRoute} == {
        "investigate",
        "clarification_reply",
        "status_question",
        "readonly_answer",
        "clarify",
        "reject",
    }
    assert {r.value for r in GraphRoute} == {
        "clarify",
        "retrieve",
        "draft",
        "answer_only",
        "abstain",
        "freeze",
        "await_decision",
        "execute",
        "recover",
        "publish",
    }
    assert {r.value for r in ModelRoute} == {"fake", "qwen3:8b"}
    m = RunManifest(
        run_id=ACTION,
        model_route=ModelRoute.FAKE,
        model_digest=None,
        prompt_version="incident-draft-v1",
        corpus_version="fixture-1",
        retrieval_mode="lexical",
    )
    assert m.retrieval_mode == "lexical"
    with pytest.raises(ValidationError):
        RunManifest(
            run_id=ACTION,
            model_route=ModelRoute.QWEN3_8B,
            model_digest=None,
            prompt_version="v1",
            corpus_version="c",
            retrieval_mode="lexical",
        )  # a real model needs its digest


def test_dedup_rejects_newline_and_seconds_variants():
    for trigger in ("timeout\n", "sweep:2026-10-08T01:05\n", "sweep:2026-10-08T01:05:33", "sweep:", "manual"):
        with pytest.raises(ValueError, match="trigger"):
            dedup_key(JobType.RECOVER, action_id=ACTION, trigger=trigger)
    assert dedup_key(JobType.RECOVER, action_id=ACTION, trigger="sweep:2026-10-08T01:05").endswith("01:05")
    with pytest.raises(ValueError, match="minute_bucket"):
        dedup_key(JobType.DELIVER_OUTBOX, minute_bucket="2026-10-08T01:05\n")


def test_dedup_validates_parts():
    for kwargs in ({}, {"proposal_id": ""}, {"proposal_id": None}):
        with pytest.raises(ValueError, match="proposal_id"):
            dedup_key(JobType.EXECUTE, **kwargs)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="action_id"):
        dedup_key(JobType.RECOVER, trigger="timeout")
    with pytest.raises(ValueError, match="unexpected key"):
        dedup_key(JobType.EXECUTE, proposal_id=ACTION, proposl=1)


def test_action_outcome_tombstone_cross_checks():
    other = uuid.UUID("00000000-0000-4000-8000-000000000011")
    aborted = Tombstone(
        action_id=ACTION, state=DestinationState.ABORTED, payload_sha256=SHA, reason="abort", decided_at=AT
    )
    ActionOutcome(
        status=ToolOutcome.FAILED_NO_COMMIT,
        action_id=ACTION,
        payload_sha256=SHA,
        receipt=None,
        tombstone=aborted,
        reason=Reason.EXPIRED,
    )
    wrong_action = aborted.model_copy(update={"action_id": other})
    wrong_sha = aborted.model_copy(update={"payload_sha256": "0" * 64})
    for tomb, reason in ((wrong_action, Reason.EXPIRED), (wrong_sha, Reason.EXPIRED), (aborted, Reason.REJECTED)):
        with pytest.raises(ValidationError):
            ActionOutcome(
                status=ToolOutcome.FAILED_NO_COMMIT,
                action_id=ACTION,
                payload_sha256=SHA,
                receipt=None,
                tombstone=tomb,
                reason=reason,
            )


def test_event_rules_late_evidence_failed_and_summary():
    tomb = {
        "action_id": str(ACTION),
        "state": "ABORTED",
        "payload_sha256": SHA,
        "reason": "x",
        "decided_at": "2026-10-08T00:00:00Z",
    }
    receipt = {"receipt_id": str(ACTION), "incident_id": "INC-1", "committed_at": "2026-10-08T00:00:00Z"}
    late = EventType.ACTION_LATE_EVIDENCE
    event_rules_ok(late, EventSource.DESTINATION, {"outcome": "FAILED_NO_COMMIT", "tombstone": tomb})
    event_rules_ok(late, EventSource.DESTINATION, {"outcome": "SUCCEEDED", "receipt": receipt})
    with pytest.raises(EventRuleViolation):  # SUCCEEDED must carry a receipt, not a tombstone
        event_rules_ok(late, EventSource.DESTINATION, {"outcome": "SUCCEEDED", "tombstone": tomb})
    with pytest.raises(EventRuleViolation):  # conflict is not a no-commit reason
        event_rules_ok(EventType.ACTION_FAILED, EventSource.DESTINATION, {"reason": "conflict"})
    with pytest.raises(EventRuleViolation):
        event_rules_ok(EventType.EXPLANATION_READY, EventSource.MODEL_SUMMARY, {"message": ""})
    with pytest.raises(EventRuleViolation):
        event_rules_ok(EventType.EXPLANATION_READY, EventSource.MODEL_SUMMARY, {"message": "m", "evidence_refs": [""]})


def test_strict_models_reject_loose_values():
    naive = datetime(2026, 10, 8)  # noqa: DTZ001 - naive on purpose
    with pytest.raises(ValidationError):
        Receipt(receipt_id=ACTION, incident_id="INC-1", committed_at=naive)
    common = {"run_id": ACTION, "prompt_version": "v1", "corpus_version": "c"}
    ok = RunManifest(model_route=ModelRoute.FAKE, model_digest=None, retrieval_mode="vector_exact", **common)
    assert ok.retrieval_mode == "vector_exact"
    with pytest.raises(ValidationError):
        RunManifest(model_route=ModelRoute.FAKE, model_digest=None, retrieval_mode="vector", **common)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        RunManifest(model_route=ModelRoute.QWEN3_8B, model_digest=SHA.upper(), retrieval_mode="lexical", **common)  # type: ignore[arg-type]

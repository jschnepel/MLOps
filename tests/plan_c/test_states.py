"""The run state machine is one table in core (AM-10, AM-20.3 performers, R082, R120, R114, R125).

Catches: a transition added or removed by accident, the wrong function performing a transition (the worker reaching a
post-grant state), a reason enum drifting, a revision taken while another run holds the conversation slot, and a
read-only run producing a proposal.
"""

import itertools

import pytest
from ops_core.states import (
    ACTIVE_STATES,
    PRE_GRANT_STATES,
    TERMINAL_STATES,
    TRANSITIONS,
    WORKER_TRANSITION_TARGETS,
    AnswerOnlyRun,
    AttemptState,
    IllegalTransition,
    Intent,
    Performer,
    Reason,
    RunState,
    SlotOccupied,
    freeze_allowed,
    require_transition,
    revision_allowed,
)

S = RunState
P = Performer

# Every allowed (source, target) pair, from AM-10's table over BUILD_SPEC §8 (rulings 1, 4 and 5 in the plan header).
ALLOWED: dict[tuple[RunState | None, RunState], set[Performer]] = {
    (None, S.QUEUED): {P.CREATE_RUN},
    (S.QUEUED, S.RETRIEVING): {P.TRANSITION_RUN},
    (S.QUEUED, S.CANCELLED): {P.REQUEST_CANCEL},
    (S.AWAITING_INPUT, S.QUEUED): {P.TRANSITION_RUN},
    (S.AWAITING_INPUT, S.CANCELLED): {P.REQUEST_CANCEL},
    (S.RETRIEVING, S.DRAFTING): {P.TRANSITION_RUN},
    (S.RETRIEVING, S.AWAITING_INPUT): {P.TRANSITION_RUN},
    (S.RETRIEVING, S.INSUFFICIENT_EVIDENCE): {P.TRANSITION_RUN},
    (S.RETRIEVING, S.FAILED): {P.TRANSITION_RUN},
    (S.RETRIEVING, S.CANCELLED): {P.REQUEST_CANCEL},
    (S.DRAFTING, S.AWAITING_INPUT): {P.TRANSITION_RUN},
    (S.DRAFTING, S.ANSWERED): {P.TRANSITION_RUN},
    (S.DRAFTING, S.INSUFFICIENT_EVIDENCE): {P.TRANSITION_RUN},
    (S.DRAFTING, S.FAILED): {P.TRANSITION_RUN},
    (S.DRAFTING, S.AWAITING_APPROVAL): {P.FREEZE_PROPOSAL},
    (S.DRAFTING, S.BLOCKED_REVIEW): {P.FREEZE_PROPOSAL},
    (S.DRAFTING, S.CANCELLED): {P.REQUEST_CANCEL},
    (S.AWAITING_APPROVAL, S.APPROVED): {P.RECORD_DECISION},
    (S.AWAITING_APPROVAL, S.REJECTED): {P.RECORD_DECISION},
    (S.AWAITING_APPROVAL, S.BLOCKED_REVIEW): {P.RECORD_DECISION, P.EXPIRE_PROPOSAL},
    (S.AWAITING_APPROVAL, S.QUEUED): {P.CREATE_REVISION},
    (S.AWAITING_APPROVAL, S.CANCELLED): {P.REQUEST_CANCEL},
    (S.APPROVED, S.EXECUTING): {P.GRANT_EXECUTION},
    (S.APPROVED, S.BLOCKED_REVIEW): {P.GRANT_EXECUTION, P.EXPIRE_PROPOSAL},
    (S.APPROVED, S.QUEUED): {P.CREATE_REVISION},
    (S.APPROVED, S.CANCELLED): {P.REQUEST_CANCEL},
    (S.BLOCKED_REVIEW, S.QUEUED): {P.CREATE_REVISION},
    (S.BLOCKED_REVIEW, S.CANCELLED): {P.REQUEST_CANCEL},
    (S.EXECUTING, S.OUTCOME_UNKNOWN): {P.MARK_UNKNOWN},
    (S.EXECUTING, S.SUCCEEDED): {P.RECORD_OUTCOME},
    (S.EXECUTING, S.FAILED): {P.RECORD_OUTCOME},
    (S.EXECUTING, S.ESCALATED): {P.ESCALATE_RUN, P.RECORD_OUTCOME},
    (S.OUTCOME_UNKNOWN, S.SUCCEEDED): {P.RECORD_OUTCOME},
    (S.OUTCOME_UNKNOWN, S.FAILED): {P.RECORD_OUTCOME},
    (S.OUTCOME_UNKNOWN, S.ESCALATED): {P.ESCALATE_RUN, P.RECORD_OUTCOME},
    (S.ESCALATED, S.SUCCEEDED): {P.RECORD_OUTCOME},
    (S.ESCALATED, S.FAILED): {P.RECORD_OUTCOME},
    (S.ESCALATED, S.ABANDONED_UNVERIFIED): {P.RESOLVE_ESCALATION},
}


def test_vocabularies_are_exactly_the_spec():
    assert len(RunState) == 17 and len(Reason) == 10 and len(AttemptState) == 4 and len(Intent) == 2
    assert {r.value for r in Reason} == {
        "cancelled_before_send",
        "aborted_no_commit",
        "rejected",
        "asset_action_unresolved",
        "asset_incident_exists",
        "expired",
        "stale_evidence",
        "authority_revoked",
        "conflict",
        "escalation_deadline",
    }
    assert ACTIVE_STATES == frozenset(
        {
            S.QUEUED,
            S.AWAITING_INPUT,
            S.RETRIEVING,
            S.DRAFTING,
            S.AWAITING_APPROVAL,
            S.APPROVED,
            S.EXECUTING,
            S.OUTCOME_UNKNOWN,
        }
    )
    assert TERMINAL_STATES == frozenset(
        {S.REJECTED, S.CANCELLED, S.ANSWERED, S.INSUFFICIENT_EVIDENCE, S.SUCCEEDED, S.FAILED, S.ABANDONED_UNVERIFIED}
    )
    assert set(S) - ACTIVE_STATES - TERMINAL_STATES == {S.BLOCKED_REVIEW, S.ESCALATED}  # live but not slot-holding


def test_table_matches_the_allowed_set_exactly():
    table = {}
    for row in TRANSITIONS:
        table.setdefault((row.src, row.dst), set()).add(row.performer)
    assert table == ALLOWED
    assert len(TRANSITIONS) == 42 and len(table) == 38


def test_every_pair_is_decided_by_the_table():
    """Exhaustive (R082): 18 sources (17 states + creation) x 17 targets x 12 performers.

    A move succeeds iff the table lists that performer for that pair; every other performer, and every performer on a
    pair the table does not list, is refused.
    """
    for src, dst, p in itertools.product([None, *S], S, P):
        if p in ALLOWED.get((src, dst), set()):
            row = next(r for r in TRANSITIONS if (r.src, r.dst, r.performer) == (src, dst, p))
            reason = min(row.reasons) if row.reasons else None  # rows that must say why get a reason
            assert require_transition(src, dst, p, reason).dst is dst
        else:
            with pytest.raises(IllegalTransition):
                require_transition(src, dst, p)


def test_terminal_states_have_no_outgoing_rows():
    assert not [row for row in TRANSITIONS if row.src in TERMINAL_STATES]


def test_wrong_performer_is_rejected():
    with pytest.raises(IllegalTransition, match="performer"):
        require_transition(S.EXECUTING, S.SUCCEEDED, P.TRANSITION_RUN)


def test_worker_targets_exclude_post_grant_states():
    """AM-20.3 transition_run: the worker never reaches a post-grant state and never SUCCEEDED."""
    assert WORKER_TRANSITION_TARGETS == frozenset(
        {S.RETRIEVING, S.DRAFTING, S.AWAITING_INPUT, S.INSUFFICIENT_EVIDENCE, S.FAILED, S.ANSWERED, S.QUEUED}
    )
    for row in TRANSITIONS:
        if row.performer is P.TRANSITION_RUN:
            assert row.dst in WORKER_TRANSITION_TARGETS and row.src in PRE_GRANT_STATES


def test_reasons_are_required_where_the_spec_names_them():
    assert require_transition(S.DRAFTING, S.BLOCKED_REVIEW, P.FREEZE_PROPOSAL, Reason.ASSET_INCIDENT_EXISTS).reasons
    with pytest.raises(IllegalTransition, match="reason"):
        require_transition(S.DRAFTING, S.BLOCKED_REVIEW, P.FREEZE_PROPOSAL)  # a blocked review always says why
    with pytest.raises(IllegalTransition, match="reason"):
        # Expiry is a grant-time or decision-time refusal; at freeze only the asset guard blocks (AM-10 table).
        require_transition(S.DRAFTING, S.BLOCKED_REVIEW, P.FREEZE_PROPOSAL, Reason.EXPIRED)
    assert require_transition(S.AWAITING_APPROVAL, S.BLOCKED_REVIEW, P.RECORD_DECISION, Reason.EXPIRED)
    with pytest.raises(IllegalTransition, match="reason"):
        # record_decision blocks only through lazy expiry.
        require_transition(S.AWAITING_APPROVAL, S.BLOCKED_REVIEW, P.RECORD_DECISION, Reason.STALE_EVIDENCE)
    assert require_transition(S.APPROVED, S.BLOCKED_REVIEW, P.GRANT_EXECUTION, Reason.STALE_EVIDENCE)
    with pytest.raises(IllegalTransition, match="reason"):
        require_transition(S.APPROVED, S.BLOCKED_REVIEW, P.EXPIRE_PROPOSAL, Reason.CONFLICT)  # expiry says 'expired'
    assert require_transition(S.EXECUTING, S.FAILED, P.RECORD_OUTCOME, Reason.CANCELLED_BEFORE_SEND)
    with pytest.raises(IllegalTransition, match="reason"):
        require_transition(S.QUEUED, S.RETRIEVING, P.TRANSITION_RUN, Reason.EXPIRED)  # no reason on plain progress


def test_revision_needs_a_free_slot():
    """R120: a revision from BLOCKED_REVIEW re-takes the slot, so another active run in the conversation is a 409."""
    revision_allowed(S.BLOCKED_REVIEW, conversation_has_other_active_run=False)
    with pytest.raises(SlotOccupied):
        revision_allowed(S.BLOCKED_REVIEW, conversation_has_other_active_run=True)
    revision_allowed(S.APPROVED, conversation_has_other_active_run=False)
    with pytest.raises(IllegalTransition):
        revision_allowed(S.EXECUTING, conversation_has_other_active_run=False)


def test_answer_only_runs_cannot_freeze():
    """R114: the answer-only intent ends ANSWERED; freeze_proposal refuses it."""
    freeze_allowed(Intent.INVESTIGATE)
    with pytest.raises(AnswerOnlyRun):
        freeze_allowed(Intent.ANSWER_ONLY)

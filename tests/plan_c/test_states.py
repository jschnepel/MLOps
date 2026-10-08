"""The run state machine is one table in core (AM-10, AM-20.3 performers, R082, R120, R114).

R125 appears only as the asset-guard reasons; the supersede exception is T22's.

Catches: a transition added or removed by accident, the wrong function performing a transition (the worker reaching a
post-grant state), a reason enum drifting, a revision taken while another run holds the conversation slot, and a
read-only run producing a proposal.
"""

import itertools

import pytest
from ops_core.states import (
    ACTIVE_STATES,
    GRANTLESS_STATES,
    POST_GRANT_STATES,
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
    (S.DRAFTING, S.AWAITING_APPROVAL): {P.FREEZE_PROPOSAL, P.CREATE_MANUAL_PROPOSAL},
    (S.DRAFTING, S.BLOCKED_REVIEW): {P.FREEZE_PROPOSAL, P.CREATE_MANUAL_PROPOSAL},
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

R = Reason
_BLOCKED_FREEZE = frozenset({R.ASSET_ACTION_UNRESOLVED, R.ASSET_INCIDENT_EXISTS})
_EXPIRED = frozenset({R.EXPIRED})
_GRANT = frozenset(
    {R.ASSET_ACTION_UNRESOLVED, R.ASSET_INCIDENT_EXISTS, R.STALE_EVIDENCE, R.AUTHORITY_REVOKED, R.EXPIRED}
)
_FAILED = frozenset({R.CANCELLED_BEFORE_SEND, R.ABORTED_NO_COMMIT, R.REJECTED, R.EXPIRED})
_ESCALATE = frozenset({R.CONFLICT, R.ESCALATION_DEADLINE})
_CONFLICT = frozenset({R.CONFLICT})
_NO = frozenset[Reason]()

# The reason set of every row (spec sets above); empty means no reason may be recorded.
EXPECTED_REASONS: dict[tuple[RunState | None, RunState, Performer], frozenset[Reason]] = {
    (key[0], key[1], p): _NO for key, ps in ALLOWED.items() for p in ps
}
EXPECTED_REASONS.update(
    {
        (S.DRAFTING, S.BLOCKED_REVIEW, P.FREEZE_PROPOSAL): _BLOCKED_FREEZE,
        (S.DRAFTING, S.BLOCKED_REVIEW, P.CREATE_MANUAL_PROPOSAL): _BLOCKED_FREEZE,
        (S.AWAITING_APPROVAL, S.REJECTED, P.RECORD_DECISION): frozenset({R.REJECTED}),
        (S.AWAITING_APPROVAL, S.BLOCKED_REVIEW, P.RECORD_DECISION): _EXPIRED,
        (S.AWAITING_APPROVAL, S.BLOCKED_REVIEW, P.EXPIRE_PROPOSAL): _EXPIRED,
        (S.APPROVED, S.BLOCKED_REVIEW, P.EXPIRE_PROPOSAL): _EXPIRED,
        (S.APPROVED, S.BLOCKED_REVIEW, P.GRANT_EXECUTION): _GRANT,
        (S.EXECUTING, S.FAILED, P.RECORD_OUTCOME): _FAILED,
        (S.OUTCOME_UNKNOWN, S.FAILED, P.RECORD_OUTCOME): _FAILED,
        (S.ESCALATED, S.FAILED, P.RECORD_OUTCOME): _FAILED,
        (S.EXECUTING, S.ESCALATED, P.ESCALATE_RUN): _ESCALATE,
        (S.OUTCOME_UNKNOWN, S.ESCALATED, P.ESCALATE_RUN): _ESCALATE,
        (S.EXECUTING, S.ESCALATED, P.RECORD_OUTCOME): _CONFLICT,
        (S.OUTCOME_UNKNOWN, S.ESCALATED, P.RECORD_OUTCOME): _CONFLICT,
    }
)


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
    assert len(TRANSITIONS) == 44 and len(table) == 38


def test_every_row_reason_set_is_pinned():
    assert {(r.src, r.dst, r.performer): r.reasons for r in TRANSITIONS} == EXPECTED_REASONS
    assert len(EXPECTED_REASONS) == 44


def test_every_pair_is_decided_by_the_table():
    """Exhaustive (R082): 18 sources (17 states + creation) x 17 targets x 13 performers.

    A move succeeds iff the table lists that performer for that pair; every other performer, and every performer on a
    pair the table does not list, is refused.
    """
    for src, dst, p in itertools.product([None, *S], S, P):
        if p in ALLOWED.get((src, dst), set()):
            row = next(r for r in TRANSITIONS if (r.src, r.dst, r.performer) == (src, dst, p))
            reason = min(row.reasons) if row.reasons else None  # rows that must say why get a reason
            assert require_transition(src, dst, p, reason).dst is dst
            if row.reasons:
                with pytest.raises(IllegalTransition, match="reason"):
                    require_transition(src, dst, p, None)
                outside = next(r for r in Reason if r not in row.reasons)
                with pytest.raises(IllegalTransition, match="reason"):
                    require_transition(src, dst, p, outside)
            else:
                with pytest.raises(IllegalTransition, match="reason"):
                    require_transition(src, dst, p, Reason.CONFLICT)
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


def test_reason_message_renders_values_not_enum_reprs():
    # These messages reach logs and 409 bodies; `<Reason.ASSET_INCIDENT_EXISTS: ...>` would leak Python internals.
    with pytest.raises(IllegalTransition) as caught:
        require_transition(S.DRAFTING, S.BLOCKED_REVIEW, P.FREEZE_PROPOSAL, Reason.EXPIRED)
    assert str(caught.value) == (
        "DRAFTING -> BLOCKED_REVIEW by freeze_proposal: "
        "reason must be one of [asset_action_unresolved, asset_incident_exists], got expired"
    )


def test_post_grant_states_are_reached_only_through_a_grant():
    """CancelResponse relies on this set: a status in it implies a grant, so FAILED (ruling 8) is not in it."""
    assert S.FAILED not in POST_GRANT_STATES
    assert POST_GRANT_STATES.isdisjoint(PRE_GRANT_STATES)
    # Every row into a post-grant state starts from APPROVED via grant_execution or from another post-grant state.
    for row in TRANSITIONS:
        if row.dst in POST_GRANT_STATES:
            assert row.src in POST_GRANT_STATES or (row.src is S.APPROVED and row.performer is P.GRANT_EXECUTION)


def test_grantless_states_are_exactly_those_no_grant_can_reach():
    """CancelResponse refuses grant_exists=true in these states, so the set must follow the table, not a hand list.

    A grant is the APPROVED -> EXECUTING row; everything a run can reach from EXECUTING may carry one. CANCELLED is
    not in the derived set's complement by accident of the table (no post-grant row ends there), and CancelResponse
    already forbids a grant with CANCELLED by its own rule, so it is excluded here rather than listed.
    """
    reachable = {S.EXECUTING}
    frontier = [S.EXECUTING]
    while frontier:
        src = frontier.pop()
        for row in TRANSITIONS:
            if row.src is src and row.dst not in reachable:
                reachable.add(row.dst)
                frontier.append(row.dst)
    assert GRANTLESS_STATES == set(RunState) - reachable - {S.CANCELLED}

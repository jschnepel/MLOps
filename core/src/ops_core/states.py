"""The run state machine as data (AM-10), with the function that performs each transition (AM-20.3).

One table, one enforcement function (R082). Services never compare state strings themselves: the worker's
`transition_run`, the API's decision/revision/cancel paths and the MCP servers' grant/outcome paths all ask this
module whether a move is legal, who may make it, and whether it must carry a reason. T09 mirrors the same rows in
SQL; the Python table is the one tests enumerate.

Each row's note names the spec section that licenses it (`AM-10 table`, `AM-20.3 performers`, ...) rather than a
line number, so the citation survives edits to the spec file.

R082's logged half: the SQL mirror `app.transition_run` (migrations/app/versions/0003) raises `OC004` with the refused
row in DETAIL, and `ops_core.persistence.transition_run` logs it at WARNING.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class RunState(StrEnum):
    """The 17 run states (BUILD_SPEC §8 plus AM-10's ESCALATED and ABANDONED_UNVERIFIED)."""

    QUEUED = "QUEUED"
    AWAITING_INPUT = "AWAITING_INPUT"
    RETRIEVING = "RETRIEVING"
    DRAFTING = "DRAFTING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    SUCCEEDED = "SUCCEEDED"
    ANSWERED = "ANSWERED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    FAILED = "FAILED"
    BLOCKED_REVIEW = "BLOCKED_REVIEW"
    # AM-10: an unresolved action after a conflict or the escalation deadline; frees the slot, keeps the asset guard.
    ESCALATED = "ESCALATED"
    ABANDONED_UNVERIFIED = "ABANDONED_UNVERIFIED"  # AM-10: operator acknowledgement; never claims success or failure


class Reason(StrEnum):
    """The one reason enum for terminal and blocked states (AM-10 "Reasons")."""

    CANCELLED_BEFORE_SEND = "cancelled_before_send"
    ABORTED_NO_COMMIT = "aborted_no_commit"
    REJECTED = "rejected"
    ASSET_ACTION_UNRESOLVED = "asset_action_unresolved"
    ASSET_INCIDENT_EXISTS = "asset_incident_exists"
    EXPIRED = "expired"
    STALE_EVIDENCE = "stale_evidence"
    AUTHORITY_REVOKED = "authority_revoked"
    CONFLICT = "conflict"
    ESCALATION_DEADLINE = "escalation_deadline"


class AttemptState(StrEnum):
    """Append-only attempt states (AM-13); the latest row by seq is the state."""

    INTENT = "INTENT"
    SENT = "SENT"
    ABORT_REQUESTED = "ABORT_REQUESTED"
    RESOLVED = "RESOLVED"


class Intent(StrEnum):
    """Requester-asserted run intent, set by the admission router (AM-10, AM-16)."""

    INVESTIGATE = "investigate"
    ANSWER_ONLY = "answer_only"


class Performer(StrEnum):
    """The definer function that owns a transition (AM-20.3 "who performs which transition").

    Plan ruling 9: AM-20.3's performer table omits `create_manual_proposal`, but it is "otherwise identical to
    `freeze_proposal`" and performs the same transitions, so it is listed here.
    """

    CREATE_RUN = "create_run"
    TRANSITION_RUN = "transition_run"
    FREEZE_PROPOSAL = "freeze_proposal"
    RECORD_DECISION = "record_decision"
    EXPIRE_PROPOSAL = "expire_proposal"
    CREATE_REVISION = "create_revision"
    REQUEST_CANCEL = "request_cancel"
    GRANT_EXECUTION = "grant_execution"
    MARK_UNKNOWN = "mark_unknown"
    RECORD_OUTCOME = "record_outcome"
    ESCALATE_RUN = "escalate_run"
    RESOLVE_ESCALATION = "resolve_escalation"
    CREATE_MANUAL_PROPOSAL = "create_manual_proposal"


class IllegalTransition(ValueError):
    """The table has no row for this (source, target, performer, reason) combination."""


class SlotOccupied(IllegalTransition):
    """R120: the conversation already holds another active run; the revision gets 409 SLOT_OCCUPIED."""


class AnswerOnlyRun(IllegalTransition):
    """R114: a run with intent answer_only can never produce a proposal."""


@dataclass(frozen=True)
class TransitionRow:
    """One allowed move: source, target, the function that performs it, and the reasons it may carry."""

    src: RunState | None  # None is creation (∅ → QUEUED, AM-10 table)
    dst: RunState
    performer: Performer
    reasons: frozenset[Reason]  # empty: no reason allowed; otherwise the reason is required and must be one of these
    note: str  # the spec section that justifies the row


_S = RunState
_P = Performer
_R = Reason
# The asset guard is the only refusal at freeze (AM-10 table, DRAFTING row; AM-13 asset guard).
_ASSET_GUARD = frozenset({_R.ASSET_ACTION_UNRESOLVED, _R.ASSET_INCIDENT_EXISTS})
# The final gate can refuse for any of these (AM-10 table, APPROVED row; AM-20.3 grant_execution).
_GRANT_REFUSAL = frozenset(
    {_R.ASSET_ACTION_UNRESOLVED, _R.ASSET_INCIDENT_EXISTS, _R.STALE_EVIDENCE, _R.AUTHORITY_REVOKED, _R.EXPIRED}
)
_EXPIRED = frozenset({_R.EXPIRED})
_FAILED = frozenset({_R.CANCELLED_BEFORE_SEND, _R.ABORTED_NO_COMMIT, _R.REJECTED, _R.EXPIRED})  # plan ruling 2
_ESCALATED = frozenset({_R.CONFLICT, _R.ESCALATION_DEADLINE})
_NONE: frozenset[Reason] = frozenset()


def _rows() -> tuple[TransitionRow, ...]:
    rows: list[TransitionRow] = [
        TransitionRow(None, _S.QUEUED, _P.CREATE_RUN, _NONE, "AM-10 table: creation only via create_run")
    ]
    # Worker progress: pre-grant states only, never SUCCEEDED (AM-20.3 transition_run; ruling 4 drops QUEUED →
    # AWAITING_INPUT).
    for src, dst in [
        (_S.QUEUED, _S.RETRIEVING),
        (_S.AWAITING_INPUT, _S.QUEUED),
        (_S.RETRIEVING, _S.DRAFTING),
        (_S.RETRIEVING, _S.AWAITING_INPUT),
        (_S.RETRIEVING, _S.INSUFFICIENT_EVIDENCE),
        (_S.DRAFTING, _S.AWAITING_INPUT),
        (_S.DRAFTING, _S.ANSWERED),
        (_S.DRAFTING, _S.INSUFFICIENT_EVIDENCE),
    ]:
        rows.append(TransitionRow(src, dst, _P.TRANSITION_RUN, _NONE, "AM-20.3 transition_run"))
    # Ruling 8: FAILED on exhausted infrastructure policy carries no reason; no reason value fits it, and the
    # run.failed event's message says why.
    for src in (_S.RETRIEVING, _S.DRAFTING):
        rows.append(TransitionRow(src, _S.FAILED, _P.TRANSITION_RUN, _NONE, "BUILD_SPEC §8; AM-20.3 transition_run"))
    rows.append(TransitionRow(_S.DRAFTING, _S.AWAITING_APPROVAL, _P.FREEZE_PROPOSAL, _NONE, "AM-20.3 freeze_proposal"))
    rows.append(TransitionRow(_S.DRAFTING, _S.BLOCKED_REVIEW, _P.FREEZE_PROPOSAL, _ASSET_GUARD, "AM-10 asset guard"))
    # Plan ruling 9: a manual proposal replaces the model's draft for a run waiting for one (AM-50 condition A), so
    # it leaves the same source state through the same asset guard as freeze_proposal.
    _manual = "plan ruling 9: performer table omits it; AM-20.3 create_manual_proposal"
    rows.append(TransitionRow(_S.DRAFTING, _S.AWAITING_APPROVAL, _P.CREATE_MANUAL_PROPOSAL, _NONE, _manual))
    rows.append(TransitionRow(_S.DRAFTING, _S.BLOCKED_REVIEW, _P.CREATE_MANUAL_PROPOSAL, _ASSET_GUARD, _manual))
    rows.append(TransitionRow(_S.AWAITING_APPROVAL, _S.APPROVED, _P.RECORD_DECISION, _NONE, "AM-20.3 record_decision"))
    rows.append(
        TransitionRow(
            _S.AWAITING_APPROVAL, _S.REJECTED, _P.RECORD_DECISION, frozenset({_R.REJECTED}), "AM-20.3 record_decision"
        )
    )
    # record_decision's only blocking path is lazy expiry (AM-20.3 record_decision; AM-10 table).
    rows.append(
        TransitionRow(_S.AWAITING_APPROVAL, _S.BLOCKED_REVIEW, _P.RECORD_DECISION, _EXPIRED, "AM-10 lazy expiry")
    )
    for src in (_S.AWAITING_APPROVAL, _S.APPROVED):
        rows.append(TransitionRow(src, _S.BLOCKED_REVIEW, _P.EXPIRE_PROPOSAL, _EXPIRED, "AM-20.3 expire_proposal"))
    # Revisions (AM-20.3 create_revision; ruling 1 includes AWAITING_APPROVAL); the slot rule is revision_allowed.
    for src in (_S.AWAITING_APPROVAL, _S.APPROVED, _S.BLOCKED_REVIEW):
        rows.append(TransitionRow(src, _S.QUEUED, _P.CREATE_REVISION, _NONE, "AM-20.3 create_revision"))
    rows.append(TransitionRow(_S.APPROVED, _S.EXECUTING, _P.GRANT_EXECUTION, _NONE, "AM-20.3 grant_execution"))
    rows.append(TransitionRow(_S.APPROVED, _S.BLOCKED_REVIEW, _P.GRANT_EXECUTION, _GRANT_REFUSAL, "AM-10 table"))
    # Cancel from any pre-grant non-terminal state (AM-20.3 performers; ruling 5 includes BLOCKED_REVIEW).
    for src in (
        _S.QUEUED,
        _S.AWAITING_INPUT,
        _S.RETRIEVING,
        _S.DRAFTING,
        _S.AWAITING_APPROVAL,
        _S.APPROVED,
        _S.BLOCKED_REVIEW,
    ):
        rows.append(TransitionRow(src, _S.CANCELLED, _P.REQUEST_CANCEL, _NONE, "AM-20.3 request_cancel"))
    # After the grant (AM-13 attempt protocol; AM-20.3 performers).
    rows.append(TransitionRow(_S.EXECUTING, _S.OUTCOME_UNKNOWN, _P.MARK_UNKNOWN, _NONE, "AM-20.3 mark_unknown"))
    for src in (_S.EXECUTING, _S.OUTCOME_UNKNOWN, _S.ESCALATED):
        rows.append(TransitionRow(src, _S.SUCCEEDED, _P.RECORD_OUTCOME, _NONE, "AM-20.3 record_outcome: receipt"))
        rows.append(TransitionRow(src, _S.FAILED, _P.RECORD_OUTCOME, _FAILED, "AM-20.3 record_outcome: tombstone"))
    for src in (_S.EXECUTING, _S.OUTCOME_UNKNOWN):
        rows.append(TransitionRow(src, _S.ESCALATED, _P.ESCALATE_RUN, _ESCALATED, "AM-20.3 escalate_run"))
        rows.append(
            TransitionRow(src, _S.ESCALATED, _P.RECORD_OUTCOME, frozenset({_R.CONFLICT}), "AM-20.3 record_outcome")
        )
    rows.append(
        TransitionRow(_S.ESCALATED, _S.ABANDONED_UNVERIFIED, _P.RESOLVE_ESCALATION, _NONE, "AM-10 operator CLI")
    )
    return tuple(rows)


TRANSITIONS: Final[tuple[TransitionRow, ...]] = _rows()

# AM-10 "Active states": the states that hold the conversation slot.
ACTIVE_STATES: Final = frozenset(
    {
        _S.QUEUED,
        _S.AWAITING_INPUT,
        _S.RETRIEVING,
        _S.DRAFTING,
        _S.AWAITING_APPROVAL,
        _S.APPROVED,
        _S.EXECUTING,
        _S.OUTCOME_UNKNOWN,
    }
)
TERMINAL_STATES: Final = frozenset(
    {_S.REJECTED, _S.CANCELLED, _S.ANSWERED, _S.INSUFFICIENT_EVIDENCE, _S.SUCCEEDED, _S.FAILED, _S.ABANDONED_UNVERIFIED}
)  # AM-10 table, last row
# BLOCKED_REVIEW counts as pre-grant: AM-13 refusals never leave a grant behind.
PRE_GRANT_STATES: Final = frozenset(
    {_S.QUEUED, _S.AWAITING_INPUT, _S.RETRIEVING, _S.DRAFTING, _S.AWAITING_APPROVAL, _S.APPROVED, _S.BLOCKED_REVIEW}
)
# No grant can precede these: the pre-grant states plus the terminals reached only before a grant (REJECTED by
# record_decision, ANSWERED and INSUFFICIENT_EVIDENCE by transition_run). PRE_GRANT_STATES stays the
# cancel-eligible set.
GRANTLESS_STATES: Final = PRE_GRANT_STATES | frozenset({_S.REJECTED, _S.ANSWERED, _S.INSUFFICIENT_EVIDENCE})
# States a run reaches only through grant_execution (APPROVED → EXECUTING) or after it (AM-10 table, AM-20.3
# performers). FAILED is not here: RETRIEVING/DRAFTING → FAILED by transition_run (ruling 8) needs no grant.
POST_GRANT_STATES: Final = frozenset(
    {_S.EXECUTING, _S.OUTCOME_UNKNOWN, _S.ESCALATED, _S.SUCCEEDED, _S.ABANDONED_UNVERIFIED}
)
WORKER_TRANSITION_TARGETS: Final = frozenset(
    {_S.RETRIEVING, _S.DRAFTING, _S.AWAITING_INPUT, _S.INSUFFICIENT_EVIDENCE, _S.FAILED, _S.ANSWERED, _S.QUEUED}
)  # AM-20.3 transition_run

_INDEX: Final[dict[tuple[RunState | None, RunState, Performer], TransitionRow]] = {
    (row.src, row.dst, row.performer): row for row in TRANSITIONS
}


def require_transition(
    src: RunState | None, dst: RunState, performer: Performer, reason: Reason | None = None
) -> TransitionRow:
    """Return the table row for this move.

    Raises:
        IllegalTransition: the pair is not in the table, the performer may not make it, or the reason is missing,
            not allowed, or given where none is recorded (the message names which).
    """
    row = _INDEX.get((src, dst, performer))
    if row is None:
        if any(r.src == src and r.dst == dst for r in TRANSITIONS):
            raise IllegalTransition(f"{src} -> {dst}: performer {performer} may not make this transition")
        raise IllegalTransition(f"{src} -> {dst} is not in the transition table")
    if row.reasons and reason not in row.reasons:
        allowed = ", ".join(sorted(r.value for r in row.reasons))
        got = None if reason is None else reason.value
        raise IllegalTransition(f"{src} -> {dst} by {performer}: reason must be one of [{allowed}], got {got}")
    if not row.reasons and reason is not None:
        raise IllegalTransition(f"{src} -> {dst} by {performer}: no reason is recorded on this transition")
    return row


def revision_allowed(src: RunState, *, conversation_has_other_active_run: bool) -> None:
    """Refuse a revision that the table forbids or that would give the conversation a second active run.

    R120 (AM-10 BLOCKED_REVIEW row): a revision re-takes the slot, so it is refused while another run in the
    conversation is active.

    Raises:
        IllegalTransition: `src` cannot be revised.
        SlotOccupied: another run in the conversation holds the slot.
    """
    require_transition(src, _S.QUEUED, _P.CREATE_REVISION)
    if conversation_has_other_active_run:
        raise SlotOccupied(f"revision from {src} refused: the conversation already holds an active run")


def freeze_allowed(intent: Intent) -> None:
    """Refuse a freeze for a read-only run (R114, AM-10 "The ANSWERED path").

    This is a separate guard, not a column of the table, because intent is a run field set at creation
    (`RunRequestFields`, AM-10 "Requester-asserted fields"), not a state: DRAFTING → AWAITING_APPROVAL is a legal
    move for an investigate run and the same move is refused for an answer_only run. T09's `freeze_proposal` calls
    both this guard and the table.

    Raises:
        AnswerOnlyRun: the run's intent is answer_only.
    """
    if intent is Intent.ANSWER_ONLY:
        raise AnswerOnlyRun("freeze_proposal refuses runs with intent answer_only")

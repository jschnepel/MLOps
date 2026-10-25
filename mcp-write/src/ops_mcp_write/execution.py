"""The write path in AM-13 order: grant → INTENT → SENT (committed before I/O) → POST → RESOLVED, as role mcp_exec
through the definer functions grant_execution, mark_sent, request_abort, record_outcome and lookup_action (T09 shape),
and the two recovery calls, the receipt lookup and the abort (T47).

Replay rule (Plan D review focus 1): execution_grant is UNIQUE (run_id), so a second `create_incident` for the same run
finds the existing grant; if its attempt is RESOLVED the stored outcome is returned without touching the destination,
otherwise `mark_sent` re-checks the run (T47) and the same action id and bytes are re-sent, and the destination's
idempotent key answers. There is never a second action id for one run. Through the tool, the stored branch is
unreachable once the outcome is recorded: the run has left APPROVED and EXECUTING, so `server.create_incident`'s
`resolve_invocation` refuses the handle first (T15, Plan J ruling 6), which production never needed (the worker skips
the call past EXECUTING). A direct caller (tests/e2e/test_mcp_write_live.py), or an overlapping call that resolved its
handle before the outcome was recorded, still reaches it. A transport failure after SENT is reported as UNKNOWN and
recorded by nobody here: the worker holds `mark_unknown` (SA:467; Plan E ruling 6).

Abort rule (SA:348, SA:465; Plan K rulings 3 and 24): when `mark_sent` answers `cancelled` or `expired`,
`create_incident` itself requests the abort (the function records ABORT_REQUESTED with the reason it chose), POSTs it
and records what the destination answers. For an attempt never sent nothing has left, and the run ends FAILED with
`cancelled_before_send` or `expired`; for the re-send of a SENT attempt the abort goes at once (`deadline`) and the
destination's answer decides: the receipt that already exists, or `aborted_no_commit`. `abort_incident` does the same
for a recover job, from INTENT or SENT. `get_incident_receipt` reads the key that stands and records it; it never writes
one. Each destination call is one request with a 10 s timeout; the backoff between calls, the scheduled recover jobs and
the redispatch of an unsent attempt are the worker's (T22).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final, Literal
from uuid import UUID

import httpx2
from ops_core import persistence
from ops_core.outcomes import ActionOutcome, EventRuleViolation, ToolOutcome
from ops_core.states import AttemptState, IllegalTransition, Reason
from ops_core.tokens import WorkloadTokenSource

from ops_mcp_write import destination

log = logging.getLogger(__name__)

# The refusals the database maps to Python. Before SENT they are honest error envelopes (server.py); after SENT they
# must not be, because the destination may have committed: the only answers then are a recorded outcome or UNKNOWN
# (AM-13, final review I1). A lease fence that moved or lapsed after SENT raises HandleRejected, a PersistenceError,
# on exactly this path (Plan H ruling 6); the run's next lease holder reconciles it (T22).
_POST_SENT_REFUSALS = (persistence.PersistenceError, IllegalTransition, EventRuleViolation)
# One destination request, given mcp-write's workload token.
Ask = Callable[[str], Awaitable[destination.Reply | None]]
# The reasons `request_abort` chooses (revision 0010, Plan K ruling 3), the same three incident-sim accepts. Any other
# answer is a fault, refused before the abort POST rather than left to the destination's 422 (final review T3-a).
ABORT_REASONS: Final = frozenset({"cancelled_before_send", "expired", "deadline"})


class GrantBlocked(Exception):
    """The §13 gate refused the grant and committed the run's BLOCKED_REVIEW (T21, Plan R rulings 9 and 11): nothing
    was granted or sent. `reason` is the AM-10 reason the run records."""

    def __init__(self, reason: Reason) -> None:
        super().__init__(reason.value)
        self.reason = reason


def next_step(attempt_state: str | None) -> Literal["stored", "send", "resend", "aborting"]:
    """What a (re)call of `create_incident` does for the grant's attempt in this state; a grant always has one."""
    if attempt_state == AttemptState.RESOLVED:
        return "stored"
    if attempt_state == AttemptState.INTENT:
        return "send"
    if attempt_state == AttemptState.SENT:
        return "resend"
    if attempt_state == AttemptState.ABORT_REQUESTED:
        return "aborting"  # an abort was requested meanwhile; nothing more is sent (SA:334)
    raise ValueError(f"attempt state {attempt_state} is not one a grant can have")


@dataclass
class Deps:
    """What the write path needs: the database session, an HTTP client and the destination's URL and token source."""

    session: persistence.Session
    http: httpx2.AsyncClient
    destination_url: str
    destination_token: WorkloadTokenSource


def _stored(grant: persistence.Grant) -> ActionOutcome:
    """The outcome a RESOLVED attempt recorded, parsed back from the grant's stored detail."""
    if grant.detail is None:
        raise RuntimeError("a resolved attempt has no stored outcome")
    return ActionOutcome.model_validate_json(json.dumps(grant.detail))


async def _read_back(deps: Deps, handle: str, azp: str, grant: persistence.Grant) -> ActionOutcome:
    """The recorded outcome, read in its own unit; a handle that expired meanwhile reports UNKNOWN, not a handle error.

    The outcome is already recorded, and lookup_action re-checks the handle's expiry: a handle that expired during a
    slow destination must not relabel it as INVALID_HANDLE. The worker's next job rereads it (T22).
    """
    try:
        async with deps.session.unit() as conn:
            return _stored(await persistence.lookup_action(conn, handle=handle, azp=azp))
    except persistence.HandleRejected:
        return destination.unknown(grant.action_id, grant.payload_sha256)
    except _POST_SENT_REFUSALS:  # SENT is committed: a mapped refusal here must not become an error envelope
        log.exception("reading back action %s failed after SENT", grant.action_id)
        return destination.unknown(grant.action_id, grant.payload_sha256)


async def _ask(deps: Deps, grant: persistence.Grant, what: str, ask: Ask) -> ActionOutcome:
    """One destination request and its classification. After SENT, or after an abort request, nothing may escape as
    "no effect" (SA:356, Plan D ruling 21): any failure, the token's included, is UNKNOWN, reconciled later."""
    try:
        reply = await ask(await deps.destination_token.token())
        return destination.classify(reply, action_id=grant.action_id, payload_sha256=grant.payload_sha256)
    except Exception:
        log.exception("destination %s for action %s failed", what, grant.action_id)
        return destination.unknown(grant.action_id, grant.payload_sha256)


async def create_incident(deps: Deps, *, handle: str, azp: str, proposal_id: UUID) -> ActionOutcome:
    """Four units of work in AM-13 order; the destination call sits between two commits, never inside one. `azp` is
    the presented token's, which every definer compares with the handle's (revision 0010)."""
    async with deps.session.unit() as conn:  # the functions resolve the handle and set the tenant themselves
        granted = await persistence.grant_execution(conn, handle=handle, azp=azp, proposal_id=proposal_id)
    if isinstance(granted, persistence.Blocked):
        raise GrantBlocked(granted.reason)  # raised after the unit committed the run's BLOCKED_REVIEW (AM-10)
    grant = granted
    step = next_step(grant.attempt_state)
    if step == "stored":
        return _stored(grant)
    if step == "aborting":
        # The abort's own record decides, and this call cannot know it, so nothing is sent and the answer is UNKNOWN,
        # which the worker turns into OUTCOME_UNKNOWN for T22. Reached by a re-queued execute job after an abort
        # request whose outcome was never recorded (final review I1), or by an overlapping call.
        return destination.unknown(grant.action_id, grant.payload_sha256)
    # A first send and a re-send of a SENT attempt both pass mark_sent, which re-checks the abort request, the cancel,
    # the dispatch deadline and (for a re-send) the job type under the runs lock (round 1, I1). The window between its
    # commit and the POST is AM-13's own, the same for both.
    async with deps.session.unit() as conn:  # committed before I/O
        sent = await persistence.mark_sent(conn, handle=handle, azp=azp, action_id=grant.action_id)
    if sent == "resolved":  # a concurrent caller finished first
        return await _read_back(deps, handle, azp, grant)
    if sent == "abort_requested":  # an abort request landed after the grant; nothing is sent
        return destination.unknown(grant.action_id, grant.payload_sha256)
    if sent == "not_redispatchable":  # a recover job never re-sends a SENT attempt (SA:345); nothing is sent
        raise persistence.Refused("NOT_REDISPATCHABLE")
    if sent in ("cancelled", "expired"):
        # Nothing more is sent. From INTENT the abort is a guaranteed no-commit (SA:348); after SENT it is the
        # immediate abort a cancel or the deadline calls for (SA:248, SA:242), and the destination decides.
        return await _abort(deps, handle, azp, grant)
    if sent not in ("sent", "already_sent"):  # an answer this code does not know must never read as "go ahead"
        raise persistence.PersistenceError(f"mark_sent answered {sent}")

    async def post(token: str) -> destination.Reply | None:
        return await destination.post_incident(
            deps.http,
            url=deps.destination_url,
            token=token,
            action_id=grant.action_id,
            payload_sha256=grant.payload_sha256,
            payload_canonical=grant.payload_canonical,
        )

    return await _record(deps, handle, azp, grant, await _ask(deps, grant, "dispatch", post))


async def _granted(deps: Deps, handle: str, azp: str, proposal_id: UUID) -> persistence.Grant:
    """The run's grant, which must be for the proposal named (SA:538: a recovery call is bound to its run's proposal);
    `lookup_action` resolves the handle again and reads nothing else (SA:466)."""
    async with deps.session.unit() as conn:
        grant = await persistence.lookup_action(conn, handle=handle, azp=azp)
    if grant.proposal_id != proposal_id:
        raise persistence.Refused("OTHER_PROPOSAL")  # before any destination call: a plain refusal
    return grant


async def get_incident_receipt(deps: Deps, *, handle: str, azp: str, proposal_id: UUID) -> ActionOutcome:
    """The recover job's receipt lookup (BS:393, SA:335): the stored outcome once the attempt is resolved, otherwise
    the key the destination holds, recorded. It creates nothing: no grant, attempt, job or key (R030)."""
    grant = await _granted(deps, handle, azp, proposal_id)
    if grant.attempt_state == AttemptState.RESOLVED:
        return _stored(grant)

    async def lookup(token: str) -> destination.Reply | None:
        return await destination.get_action(deps.http, url=deps.destination_url, token=token, action_id=grant.action_id)

    return await _record(deps, handle, azp, grant, await _ask(deps, grant, "lookup", lookup))


async def abort_incident(deps: Deps, *, handle: str, azp: str, proposal_id: UUID) -> ActionOutcome:
    """The recover job's abort (SA:336, SA:241-242): the stored outcome once resolved, otherwise the abort request,
    the abort POST and the record of what the destination answered (a fresh tombstone, or the key that stands)."""
    grant = await _granted(deps, handle, azp, proposal_id)
    if grant.attempt_state == AttemptState.RESOLVED:
        return _stored(grant)
    return await _abort(deps, handle, azp, grant)


async def _abort(deps: Deps, handle: str, azp: str, grant: persistence.Grant) -> ActionOutcome:
    """request_abort (its reason, committed before the abort leaves), the abort POST, the record (SA:465).

    Raises:
        PersistenceError: request_abort answered something other than `resolved` or one of `ABORT_REASONS`; nothing
            is POSTed.
    """
    async with deps.session.unit() as conn:
        reason = await persistence.request_abort(conn, handle=handle, azp=azp, action_id=grant.action_id)
    if reason == "resolved":  # the outcome already stands
        return await _read_back(deps, handle, azp, grant)
    if reason not in ABORT_REASONS:  # only a reason the function chooses may reach the destination as the abort's
        raise persistence.PersistenceError(f"request_abort answered {reason}")

    async def abort(token: str) -> destination.Reply | None:
        return await destination.post_abort(
            deps.http,
            url=deps.destination_url,
            token=token,
            action_id=grant.action_id,
            payload_sha256=grant.payload_sha256,
            reason=reason,
        )

    return await _record(deps, handle, azp, grant, await _ask(deps, grant, "abort", abort))


async def _record(deps: Deps, handle: str, azp: str, grant: persistence.Grant, outcome: ActionOutcome) -> ActionOutcome:
    """Record what the destination answered and return what stands. UNKNOWN is returned unrecorded."""
    if outcome.status is ToolOutcome.UNKNOWN:
        # A lost reply, a 404, a 429, a 503 or a malformed document: nothing is recorded here; the worker holds
        # mark_unknown (SA:467, Plan E ruling 6), and record_outcome refuses UNKNOWN by design.
        return outcome
    # An unmapped database failure (psycopg.Error: a lock timeout, a dropped connection) still escapes as the SDK's
    # tool error, and the worker re-queues the execute job with nothing recorded. Its next call meets the same action
    # id: after a send it passes mark_sent again, as any re-send of a SENT attempt does; after an abort request the
    # attempt is ABORT_REQUESTED, which the allowlist admits for an execute job, so the call answers UNKNOWN with
    # nothing sent and the worker's mark_unknown parks the run in OUTCOME_UNKNOWN for T22 (final review I1). A mapped
    # refusal is answered UNKNOWN at once so the worker reconciles it: the destination has answered, so an error
    # envelope would hide an outcome that may exist (AM-13).
    try:
        async with deps.session.unit() as conn:
            standing = await persistence.record_outcome(
                conn, handle=handle, azp=azp, action_id=grant.action_id, outcome=outcome
            )
    except _POST_SENT_REFUSALS:
        log.exception("recording the outcome of action %s failed after the destination answered", grant.action_id)
        return destination.unknown(grant.action_id, grant.payload_sha256)
    if standing is outcome.status:
        return outcome
    # A concurrent caller's record stands: read it back in its own unit.
    return await _read_back(deps, handle, azp, grant)

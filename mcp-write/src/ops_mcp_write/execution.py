"""The write path in AM-13 order: grant → INTENT → SENT (committed before I/O) → POST → RESOLVED, as role mcp_exec
through the definer functions grant_execution, mark_sent, record_outcome and lookup_action (T09 shape).

Replay rule (Plan D review focus 1): execution_grant is UNIQUE (run_id), so a second `create_incident` for the same run
finds the existing grant; if its attempt is RESOLVED the stored outcome is returned without touching the destination,
otherwise the same action id and bytes are re-sent and the destination's idempotent key answers. There is never a
second action id for one run. A transport failure after SENT is reported as UNKNOWN and recorded by nobody here: the
worker holds `mark_unknown` (SA:467; Plan E ruling 6).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import httpx2
from ops_core import persistence
from ops_core.outcomes import ActionOutcome, ToolOutcome
from ops_core.tokens import WorkloadTokenSource

from ops_mcp_write import destination

log = logging.getLogger(__name__)


def next_step(attempt_state: str | None) -> Literal["stored", "send", "resend"]:
    """What a (re)call does for an attempt in this state; states the skeleton cannot handle are refused."""
    if attempt_state == "RESOLVED":
        return "stored"
    if attempt_state == "INTENT":
        return "send"
    if attempt_state == "SENT":
        return "resend"
    raise ValueError(f"attempt state {attempt_state} is not handled by the walking skeleton")


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


async def _read_back(deps: Deps, handle: str, grant: persistence.Grant) -> ActionOutcome:
    """The recorded outcome, read in its own unit; a handle that expired meanwhile reports UNKNOWN, not a handle error.

    The outcome is already recorded, and lookup_action re-checks the handle's expiry: a handle that expired during a
    slow destination must not relabel it as INVALID_HANDLE. The worker's next job rereads it (T22).
    """
    try:
        async with deps.session.unit() as conn:
            return _stored(await persistence.lookup_action(conn, handle=handle))
    except persistence.HandleRejected:
        return destination.unknown(grant.action_id, grant.payload_sha256)


async def create_incident(deps: Deps, *, handle: str, proposal_id: UUID) -> ActionOutcome:
    """Four units of work in AM-13 order; the destination call sits between two commits, never inside one."""
    async with deps.session.unit() as conn:  # the functions resolve the handle and set the tenant themselves
        grant = await persistence.grant_execution(conn, handle=handle, proposal_id=proposal_id)
    step = next_step(grant.attempt_state)
    if step == "stored":
        return _stored(grant)
    if step == "send":
        async with deps.session.unit() as conn:
            sent = await persistence.mark_sent(conn, grant.action_id)  # committed here, before any I/O
        if sent == "resolved":  # a concurrent caller finished first
            return await _read_back(deps, handle, grant)
        if sent == "cancelled":
            # The UNKNOWN envelope makes the worker call mark_unknown, which moves the run to OUTCOME_UNKNOWN and
            # queues a recover job although nothing was sent: conservative. TODO(T22): request_abort and the abort
            # POST replace this.
            return destination.unknown(grant.action_id, grant.payload_sha256)
    try:
        reply = await destination.post_incident(
            deps.http,
            url=deps.destination_url,
            token=await deps.destination_token.token(),
            action_id=grant.action_id,
            payload_sha256=grant.payload_sha256,
            payload_canonical=grant.payload_canonical,
        )
        outcome = destination.classify(reply, action_id=grant.action_id, payload_sha256=grant.payload_sha256)
    except Exception:  # after SENT nothing may escape as "no effect" (SA:356, ruling 21): UNKNOWN, reconciled
        log.exception("destination call for action %s failed after SENT", grant.action_id)
        return destination.unknown(grant.action_id, grant.payload_sha256)
    if outcome.status is ToolOutcome.UNKNOWN:
        # A lost reply, a 503 or a malformed document: nothing is recorded here; the worker holds mark_unknown
        # (SA:467, Plan E ruling 6), and record_outcome refuses UNKNOWN by design.
        return outcome
    # Outside the try on purpose: a database failure here is a 500 and the replay recovers (the attempt is still SENT).
    async with deps.session.unit() as conn:
        standing = await persistence.record_outcome(conn, action_id=grant.action_id, outcome=outcome)
    if standing is outcome.status:
        return outcome
    # A concurrent caller's record stands: read it back in its own unit.
    return await _read_back(deps, handle, grant)

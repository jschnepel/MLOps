"""The write path in AM-13 order: grant → INTENT → SENT (committed before I/O) → POST → RESOLVED (T08 shape of
grant_execution, mark_sent, record_outcome and mark_unknown; TODO(T09/T22): the SECURITY DEFINER functions).

Replay rule (review focus 1): `execution_grant` is UNIQUE (run_id), so a second `create_incident` for the same run
finds the existing grant; if its attempt is RESOLVED the stored outcome is returned without touching the destination,
otherwise the same action id and bytes are re-sent and the destination's idempotent key answers. There is never a
second action id for one run.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID, uuid4

import httpx2
from ops_core import persistence
from ops_core.outcomes import ActionOutcome, EventSource, EventType, ToolOutcome
from ops_core.states import Performer, Reason, RunState
from ops_core.tokens import WorkloadTokenSource
from psycopg.types.json import Jsonb

from ops_mcp_write import destination

log = logging.getLogger(__name__)


class GrantRefused(persistence.PersistenceError):
    """The §13 gate said no before any grant existed; the tool answers status=error (SA:357)."""


@dataclass(frozen=True)
class Grant:
    """One run's execution grant joined with its tenant, approved bytes and latest attempt state."""

    action_id: UUID
    run_id: UUID
    proposal_id: UUID
    tenant_id: UUID
    conversation_id: UUID
    payload_sha256: str
    payload_canonical: bytes
    attempt_state: str
    detail: dict[str, Any] | None


async def load_grant(conn: persistence.Conn, run_id: UUID) -> Grant | None:
    """The run's grant with its latest attempt state, or None when no grant exists yet."""
    cur = await conn.execute(
        "SELECT g.action_id, g.run_id, g.proposal_id, r.tenant_id, r.conversation_id, g.payload_sha256,"
        " p.payload_canonical, s.state AS attempt_state, s.detail"
        " FROM app.execution_grant g JOIN app.runs r ON r.run_id = g.run_id"
        " JOIN app.proposals p ON p.proposal_id = g.proposal_id"
        " JOIN LATERAL (SELECT state, detail FROM app.action_attempt_state"
        "               WHERE action_id = g.action_id ORDER BY attempt_no DESC, seq DESC LIMIT 1) s ON true"
        " WHERE g.run_id = %s",
        (run_id,),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    return Grant(
        row["action_id"],
        row["run_id"],
        row["proposal_id"],
        row["tenant_id"],
        row["conversation_id"],
        row["payload_sha256"],
        bytes(row["payload_canonical"]),
        row["attempt_state"],
        row["detail"],
    )


async def _attempt_state(
    conn: persistence.Conn,
    action_id: UUID,
    state: str,
    *,
    outcome: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    await conn.execute(
        "INSERT INTO app.action_attempt_state (action_id, attempt_no, seq, state, outcome, detail)"
        " SELECT %s, 1, COALESCE(MAX(seq), 0) + 1, %s, %s, %s FROM app.action_attempt_state"
        " WHERE action_id = %s AND attempt_no = 1",
        (action_id, state, outcome, Jsonb(detail) if detail is not None else None, action_id),
    )


async def grant_execution(conn: persistence.Conn, *, invocation: persistence.Invocation, proposal_id: UUID) -> Grant:
    """The §13 final gate in its T08 form: the proposal is this run's active, approved revision; one grant per run.
    Runs inside the caller's unit of work."""
    run = await persistence.run_row(conn, invocation.run_id, lock=True)
    existing = await load_grant(conn, invocation.run_id)
    if existing is not None:
        if existing.proposal_id != proposal_id:
            raise GrantRefused("this run's grant binds another proposal")
        return existing  # UNIQUE (run_id): a replay finds the grant it already has
    cur = await conn.execute(
        "SELECT * FROM app.proposals WHERE proposal_id = %s AND run_id = %s AND tenant_id = %s",
        (proposal_id, invocation.run_id, invocation.tenant_id),
    )
    proposal = await cur.fetchone()
    if proposal is None:
        raise GrantRefused("proposal does not belong to this run")
    if run["active_proposal_id"] != proposal_id or run["state"] != RunState.APPROVED.value:
        raise GrantRefused("proposal is not the run's approved active revision")
    cur = await conn.execute(
        "SELECT 1 FROM app.decisions WHERE proposal_id = %s AND decision = 'approve'", (proposal_id,)
    )
    if await cur.fetchone() is None:
        raise GrantRefused("no approving decision is recorded")
    action_id = uuid4()  # random inside the gate (SA:168), never derived from the proposal
    await conn.execute(
        "INSERT INTO app.execution_grant (action_id, run_id, proposal_id, payload_sha256) VALUES (%s, %s, %s, %s)",
        (action_id, invocation.run_id, proposal_id, proposal["payload_sha256"]),
    )
    await conn.execute("INSERT INTO app.action_attempt (action_id, attempt_no) VALUES (%s, 1)", (action_id,))
    await _attempt_state(conn, action_id, "INTENT")
    await persistence.transition(
        conn, run_id=invocation.run_id, dst=RunState.EXECUTING, performer=Performer.GRANT_EXECUTION
    )
    await persistence.append_event(
        conn,
        tenant_id=invocation.tenant_id,
        conversation_id=invocation.conversation_id,
        run_id=invocation.run_id,
        type=EventType.ACTION_GRANTED,
        source=EventSource.APPLICATION,
        payload={"action_id": str(action_id), "proposal_id": str(proposal_id)},
    )
    grant = await load_grant(conn, invocation.run_id)
    if grant is None:
        raise RuntimeError("the grant just written cannot be read back")
    return grant


async def _latest_attempt(conn: persistence.Conn, action_id: UUID) -> str:
    """The newest attempt state; callers hold the runs row lock, so the answer cannot change under them."""
    cur = await conn.execute(
        "SELECT state FROM app.action_attempt_state WHERE action_id = %s ORDER BY attempt_no DESC, seq DESC LIMIT 1",
        (action_id,),
    )
    row = await cur.fetchone()
    if row is None:  # INTENT is written in the grant's own unit of work
        raise RuntimeError("the grant has no attempt state")
    return str(row["state"])


async def mark_sent(conn: persistence.Conn, grant: Grant) -> None:
    """SENT, in its own unit of work that commits before the first byte leaves (SA:229): a crash after this point is
    reconciled, not retried. Idempotent: a concurrent caller that got here first leaves nothing to write."""
    await persistence.run_row(conn, grant.run_id, lock=True)  # also serialises the seq computation (SA:462)
    if await _latest_attempt(conn, grant.action_id) in ("SENT", "RESOLVED"):
        return
    await _attempt_state(conn, grant.action_id, "SENT")
    await persistence.append_event(
        conn,
        tenant_id=grant.tenant_id,
        conversation_id=grant.conversation_id,
        run_id=grant.run_id,
        type=EventType.ACTION_DISPATCHED,
        source=EventSource.APPLICATION,
        payload={"action_id": str(grant.action_id)},
    )


async def record_outcome(conn: persistence.Conn, grant: Grant, outcome: ActionOutcome) -> None:
    """RESOLVED plus the run transition the outcome implies; the event is the destination's assertion (AM-14).
    Idempotent (SA:464): a resolved attempt or an already-terminal run stands; late evidence is T22's."""
    run_state = (await persistence.run_row(conn, grant.run_id, lock=True))["state"]
    implied = {
        ToolOutcome.SUCCEEDED: RunState.SUCCEEDED,
        ToolOutcome.FAILED_NO_COMMIT: RunState.FAILED,
        ToolOutcome.CONFLICT: RunState.ESCALATED,
    }.get(outcome.status)
    if await _latest_attempt(conn, grant.action_id) == "RESOLVED" or (implied and run_state == implied.value):
        return
    data = outcome.model_dump(mode="json")
    await _attempt_state(conn, grant.action_id, "RESOLVED", outcome=outcome.status.value, detail=data)
    tenant, conversation, run = grant.tenant_id, grant.conversation_id, grant.run_id
    if outcome.status is ToolOutcome.SUCCEEDED:
        await persistence.transition(conn, run_id=run, dst=RunState.SUCCEEDED, performer=Performer.RECORD_OUTCOME)
        await persistence.append_event(
            conn,
            tenant_id=tenant,
            conversation_id=conversation,
            run_id=run,
            type=EventType.ACTION_CONFIRMED,
            source=EventSource.DESTINATION,
            payload={"status": "SUCCEEDED", "action_id": str(grant.action_id), "receipt": data["receipt"]},
        )
    elif outcome.status is ToolOutcome.FAILED_NO_COMMIT:
        if outcome.reason is None:  # ActionOutcome's own invariant
            raise RuntimeError("a FAILED_NO_COMMIT outcome carries no reason")
        await persistence.transition(
            conn, run_id=run, dst=RunState.FAILED, performer=Performer.RECORD_OUTCOME, reason=outcome.reason
        )
        await persistence.append_event(
            conn,
            tenant_id=tenant,
            conversation_id=conversation,
            run_id=run,
            type=EventType.ACTION_FAILED,
            source=EventSource.DESTINATION,
            payload={"action_id": str(grant.action_id), "reason": outcome.reason.value, "tombstone": data["tombstone"]},
        )
    elif outcome.status is ToolOutcome.CONFLICT:
        await persistence.transition(
            conn, run_id=run, dst=RunState.ESCALATED, performer=Performer.RECORD_OUTCOME, reason=Reason.CONFLICT
        )
        await persistence.append_event(
            conn,
            tenant_id=tenant,
            conversation_id=conversation,
            run_id=run,
            type=EventType.ACTION_CONFLICT,
            source=EventSource.DESTINATION,
            payload={"action_id": str(grant.action_id)},
        )
    else:
        raise ValueError("UNKNOWN is recorded by mark_unknown, not record_outcome")


async def mark_unknown(conn: persistence.Conn, grant: Grant) -> None:
    """A transport failure after SENT: the run says so and waits for reconciliation (T22)."""
    run = await persistence.run_row(conn, grant.run_id, lock=True)
    if run["state"] == RunState.EXECUTING.value:  # a second UNKNOWN changes nothing
        await persistence.transition(
            conn, run_id=grant.run_id, dst=RunState.OUTCOME_UNKNOWN, performer=Performer.MARK_UNKNOWN
        )
        await persistence.append_event(
            conn,
            tenant_id=grant.tenant_id,
            conversation_id=grant.conversation_id,
            run_id=grant.run_id,
            type=EventType.ACTION_UNCERTAIN,
            source=EventSource.APPLICATION,
            payload={"action_id": str(grant.action_id)},
        )


def next_step(attempt_state: str) -> Literal["stored", "send", "resend"]:
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


async def create_incident(deps: Deps, *, invocation: persistence.Invocation, proposal_id: UUID) -> ActionOutcome:
    """Four units of work in AM-13 order; the destination call sits between two commits, never inside one."""
    async with deps.session.unit() as conn:
        grant = await grant_execution(conn, invocation=invocation, proposal_id=proposal_id)
    step = next_step(grant.attempt_state)
    if step == "stored":
        if grant.detail is None:
            raise RuntimeError("a stored outcome has no detail")
        return ActionOutcome.model_validate_json(json.dumps(grant.detail))
    if step == "send":
        async with deps.session.unit() as conn:
            await mark_sent(conn, grant)  # committed here, before any I/O
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
        outcome = destination.unknown(grant.action_id, grant.payload_sha256)
    # Outside the try on purpose: a database failure here is a 500 and the replay recovers (the attempt is still SENT).
    async with deps.session.unit() as conn:
        if outcome.status is ToolOutcome.UNKNOWN:
            await mark_unknown(conn, grant)
        else:
            await record_outcome(conn, grant, outcome)
        final = await load_grant(conn, grant.run_id)
    if final is not None and final.attempt_state == "RESOLVED" and final.detail is not None:
        return ActionOutcome.model_validate_json(json.dumps(final.detail))  # a concurrent caller's record stands
    return outcome

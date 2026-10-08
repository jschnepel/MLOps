"""The API's door to the database (T08 shape of create_run, record_decision and the read queries).

Every method is tenant-scoped by a WHERE clause (debt → T09 RLS) and the two writers are single transactions:
admission commits message, run, job and `run.accepted` together (BUILD_SPEC §7: success only after commit), and a
decision commits the decision row, the transition, the `execute` wake-up and `approval.recorded` together (BUILD_SPEC
§12). TODO(T09): `create_run`/`record_decision` definer functions; TODO(T12): Idempotency-Key, admission router.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

import psycopg
from ops_core import persistence
from ops_core.contracts import DecisionRequest, MessageRequest
from ops_core.jobs import JobType
from ops_core.outcomes import EventSource, EventType
from ops_core.states import Intent, Performer, Reason, RunState
from psycopg.types.json import Jsonb


class Forbidden(Exception):
    """The caller is authenticated but may not do this (maps to 403)."""


class NotFound(Exception):
    """The row does not exist in the caller's tenant (maps to 404)."""


class Conflict(Exception):
    """The request lost a race or names a stale version (maps to 409); `code` is the ErrorCode value."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Membership:
    """A subject's tenant and roles, resolved from the seeded memberships."""

    tenant_id: UUID
    roles: frozenset[str]


@dataclass(frozen=True)
class Accepted:
    """What admission returns after the run, job and `run.accepted` committed."""

    conversation_id: UUID
    message_id: UUID
    run_id: UUID
    status: str
    state_version: int


@dataclass(frozen=True)
class Decided:
    """What a recorded decision returns after the transition committed."""

    proposal_id: UUID
    run_id: UUID
    decision: str
    status: str
    state_version: int


def resolve_interval(hours: int, now: datetime) -> tuple[datetime, datetime]:
    """ "Last N hours" resolved once, at admission, to whole seconds (BUILD_SPEC §7: retries keep the window)."""
    end = now.replace(microsecond=0)
    return end - timedelta(hours=hours), end


def check_reviewer(membership: Membership, *, requester: UUID, authored_by: list[UUID], reviewer: UUID) -> None:
    """Independence (BUILD_SPEC §9, SA:539): a current reviewer who is neither the requester nor a content author."""
    if "reviewer" not in membership.roles:
        raise Forbidden
    if reviewer == requester or reviewer in authored_by:
        raise Forbidden


class Store(Protocol):
    """The seven operations the application needs; the unit tests fake it, `DbStore` implements it."""

    async def membership(self, issuer: str, subject: UUID) -> Membership | None:
        """Resolve a verified subject to its active tenant membership, or None."""
        ...

    async def create_conversation(self, tenant_id: UUID, created_by: UUID) -> UUID:
        """Create an empty conversation in the tenant."""
        ...

    async def admit(
        self,
        *,
        tenant_id: UUID,
        conversation_id: UUID,
        requester: UUID,
        request: MessageRequest,
        start_at: datetime,
        end_at: datetime,
    ) -> Accepted:
        """Commit message, run, job and `run.accepted` together."""
        ...

    async def run(self, tenant_id: UUID, run_id: UUID) -> dict[str, Any] | None:
        """Read one run row in the tenant."""
        ...

    async def proposal(self, tenant_id: UUID, proposal_id: UUID) -> dict[str, Any] | None:
        """Read one proposal with its run's requester and state."""
        ...

    async def decide(self, *, tenant_id: UUID, proposal_id: UUID, reviewer: UUID, request: DecisionRequest) -> Decided:
        """Record the first decision on the exact revision and hash, or raise Conflict."""
        ...

    async def events(self, tenant_id: UUID, run_id: UUID, *, after: int, limit: int) -> list[dict[str, Any]]:
        """List a run's events after a sequence number."""
        ...


class DbStore:
    """The PostgreSQL implementation of `Store` over one autocommit connection."""

    def __init__(self, conn: persistence.Conn) -> None:
        self.session = persistence.Session(conn)  # ruling 24: one unit of work at a time, each a real transaction

    async def membership(self, issuer: str, subject: UUID) -> Membership | None:
        """Resolve a verified subject to its active tenant membership, or None."""
        async with self.session.unit() as conn:
            cur = await conn.execute(
                "SELECT tenant_id, role FROM app.memberships WHERE issuer = %s AND subject = %s AND active",
                (issuer, subject),
            )
            rows = await cur.fetchall()
        if not rows:
            return None
        return Membership(rows[0]["tenant_id"], frozenset(r["role"] for r in rows))

    async def create_conversation(self, tenant_id: UUID, created_by: UUID) -> UUID:
        """Create an empty conversation in the tenant."""
        cid = uuid4()
        async with self.session.unit() as conn:
            await conn.execute(
                "INSERT INTO app.conversations (conversation_id, tenant_id, created_by) VALUES (%s, %s, %s)",
                (cid, tenant_id, created_by),
            )
        return cid

    async def admit(
        self,
        *,
        tenant_id: UUID,
        conversation_id: UUID,
        requester: UUID,
        request: MessageRequest,
        start_at: datetime,
        end_at: datetime,
    ) -> Accepted:
        """Commit message, run, job and `run.accepted` together."""
        assert request.context is not None and request.context.asset_id is not None  # app.py checked the route
        message_id, run_id = uuid4(), uuid4()
        try:
            async with self.session.unit() as conn:
                cur = await conn.execute(
                    "SELECT 1 FROM app.conversations WHERE conversation_id = %s AND tenant_id = %s",
                    (conversation_id, tenant_id),
                )
                if await cur.fetchone() is None:
                    raise NotFound
                await conn.execute(
                    "INSERT INTO app.messages (message_id, tenant_id, conversation_id, kind, text, context, author)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (
                        message_id,
                        tenant_id,
                        conversation_id,
                        request.kind.value,
                        request.text,
                        Jsonb(request.context.model_dump(mode="json")),
                        requester,
                    ),
                )
                version = await persistence.create_run(
                    conn,
                    run_id=run_id,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    message_id=message_id,
                    requester=requester,
                    intent=Intent.INVESTIGATE,
                    asset_id=request.context.asset_id,
                    start_at=start_at,
                    end_at=end_at,
                    supersedes_run_id=request.supersedes_run_id,
                )
                await persistence.append_event(
                    conn,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    run_id=run_id,
                    type=EventType.RUN_ACCEPTED,
                    source=EventSource.APPLICATION,
                    payload={},
                )
        except psycopg.errors.UniqueViolation as exc:
            # The partial unique index is the slot rule (BUILD_SPEC §7); any other uniqueness error is a bug.
            if exc.diag.constraint_name == "runs_one_active_per_conversation":
                raise Conflict("SLOT_OCCUPIED") from exc
            raise
        return Accepted(conversation_id, message_id, run_id, RunState.QUEUED.value, version)

    async def run(self, tenant_id: UUID, run_id: UUID) -> dict[str, Any] | None:
        """Read one run row in the tenant."""
        row = await self.session.read(
            "SELECT * FROM app.runs WHERE run_id = %s AND tenant_id = %s", (run_id, tenant_id)
        )
        return None if row is None else dict(row)

    async def proposal(self, tenant_id: UUID, proposal_id: UUID) -> dict[str, Any] | None:
        """Read one proposal with its run's requester and state."""
        row = await self.session.read(
            "SELECT p.*, r.requester, r.state AS run_state FROM app.proposals p JOIN app.runs r ON r.run_id = p.run_id"
            " WHERE p.proposal_id = %s AND p.tenant_id = %s",
            (proposal_id, tenant_id),
        )
        return None if row is None else dict(row)

    async def decide(self, *, tenant_id: UUID, proposal_id: UUID, reviewer: UUID, request: DecisionRequest) -> Decided:
        """Record the first decision on the exact revision and hash, or raise Conflict."""
        try:
            async with self.session.unit() as conn:
                cur = await conn.execute(
                    "SELECT p.run_id, p.revision, p.payload_sha256 FROM app.proposals p"
                    " WHERE p.proposal_id = %s AND p.tenant_id = %s",
                    (proposal_id, tenant_id),
                )
                proposal = await cur.fetchone()
                if proposal is None:
                    raise NotFound
                run = await persistence.run_row(conn, proposal["run_id"], lock=True)
                if run["active_proposal_id"] != proposal_id or run["state"] != RunState.AWAITING_APPROVAL.value:
                    raise Conflict("VERSION_CONFLICT")
                if (proposal["revision"], proposal["payload_sha256"]) != (
                    request.expected_revision,
                    request.expected_payload_sha256,
                ):
                    raise Conflict("VERSION_CONFLICT")  # exact content binding (BUILD_SPEC §12)
                await conn.execute(
                    "INSERT INTO app.decisions (decision_id, proposal_id, reviewer, decision, reason,"
                    " expected_payload_sha256) VALUES (%s, %s, %s, %s, %s, %s)",
                    (uuid4(), proposal_id, reviewer, request.decision, request.reason, request.expected_payload_sha256),
                )
                run_id: UUID = run["run_id"]
                conversation_id: UUID = run["conversation_id"]
                if request.decision == "approve":
                    version = await persistence.transition(
                        conn, run_id=run_id, dst=RunState.APPROVED, performer=Performer.RECORD_DECISION
                    )
                    await persistence.insert_job(conn, job_type=JobType.EXECUTE, run_id=run_id, proposal_id=proposal_id)
                    await persistence.append_event(
                        conn,
                        tenant_id=tenant_id,
                        conversation_id=conversation_id,
                        run_id=run_id,
                        type=EventType.APPROVAL_RECORDED,
                        source=EventSource.APPLICATION,
                        payload={"proposal_id": str(proposal_id)},
                    )
                    status = RunState.APPROVED.value
                else:
                    version = await persistence.transition(
                        conn,
                        run_id=run_id,
                        dst=RunState.REJECTED,
                        performer=Performer.RECORD_DECISION,
                        reason=Reason.REJECTED,
                    )
                    await persistence.append_event(
                        conn,
                        tenant_id=tenant_id,
                        conversation_id=conversation_id,
                        run_id=run_id,
                        type=EventType.RUN_REJECTED,
                        source=EventSource.APPLICATION,
                        payload={"proposal_id": str(proposal_id)},
                    )
                    status = RunState.REJECTED.value
        except psycopg.errors.UniqueViolation as exc:
            raise Conflict("VERSION_CONFLICT") from exc  # decisions.proposal_id UNIQUE: the first decision won
        return Decided(proposal_id, run_id, request.decision, status, version)

    async def events(self, tenant_id: UUID, run_id: UUID, *, after: int, limit: int) -> list[dict[str, Any]]:
        """List a run's events after a sequence number."""
        async with self.session.unit() as conn:
            cur = await conn.execute(
                "SELECT sequence, type, source, occurred_at, payload FROM app.events"
                " WHERE run_id = %s AND tenant_id = %s AND sequence > %s ORDER BY sequence LIMIT %s",
                (run_id, tenant_id, after, limit),
            )
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

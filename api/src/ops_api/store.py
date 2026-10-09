"""The API's door to the database as role `api` (T09 shape): identity through `resolve_identity`, admission through
`create_run`, decisions through `record_decision`; reads under the tenant's unit, which RLS scopes.

Admission still commits message, run, job and `run.accepted` together (BUILD_SPEC §7) and a decision commits the
decision row, the transition, the `execute` wake-up and `approval.recorded` together (§12): the functions do the
writing inside the API's transaction. TODO(T12): Idempotency-Key, admission router.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from ops_core import persistence
from ops_core.contracts import DecisionRequest, MessageRequest
from ops_core.states import Intent, RunState
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


class Internal(Exception):
    """A definer function refused input the API already validated, or returned nothing: a server defect, never the
    client's (maps to 503)."""


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


def single_tenant(rows: list[tuple[UUID, str]]) -> Membership | None:
    """Fold (tenant, role) rows into one Membership; None when there are none or they span tenants."""
    tenants = {tenant for tenant, _ in rows}
    if len(tenants) != 1:
        # TODO(T11): explicit tenant selection; until then a multi-tenant subject cannot act, and roles never merge.
        return None
    return Membership(next(iter(tenants)), frozenset(role for _, role in rows))


def map_refusal(exc: persistence.Refused) -> Exception:
    """A function's DETAIL code → the HTTP class BUILD_SPEC §16 names; the code itself never reaches the client."""
    if exc.code in ("NOT_REVIEWER", "SELF_REVIEW", "MEMBERSHIP_INACTIVE"):
        return Forbidden()
    if exc.code == "SLOT_OCCUPIED":
        return Conflict("SLOT_OCCUPIED")
    if exc.code == "INVALID_ARGUMENT":
        return Internal()  # the API's own validation makes this unreachable; a 409 would be a false message
    return Conflict("VERSION_CONFLICT")


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
    """The PostgreSQL implementation of `Store` over one autocommit connection as role `api`."""

    def __init__(self, conn: persistence.Conn) -> None:
        self.session = persistence.Session(conn)  # ruling 24: one unit of work at a time, each a real transaction

    async def membership(self, issuer: str, subject: UUID) -> Membership | None:
        """Resolve a verified subject to its active tenant membership, or None."""
        async with self.session.unit() as conn:  # the function walks the tenants itself (Plan E ruling 4)
            rows = await persistence.resolve_identity(conn, issuer=issuer, subject=subject)
        return single_tenant(rows)

    async def create_conversation(self, tenant_id: UUID, created_by: UUID) -> UUID:
        """Create an empty conversation in the tenant."""
        cid = uuid4()
        async with self.session.unit(tenant_id) as conn:
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
        if request.context is None or request.context.asset_id is None:  # app.py checked the route
            raise ValueError("admit requires an investigate request with asset_id")
        message_id = uuid4()
        try:
            async with self.session.unit(tenant_id) as conn:
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
                # The function validates the supersedes target against tenant and conversation (SA:450).
                run_id, version = await persistence.create_run(
                    conn,
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
        except persistence.NotFound as exc:
            raise NotFound from exc
        except persistence.Refused as exc:
            raise map_refusal(exc) from exc
        return Accepted(conversation_id, message_id, run_id, RunState.QUEUED.value, version)

    async def run(self, tenant_id: UUID, run_id: UUID) -> dict[str, Any] | None:
        """Read one run row in the tenant (RLS scopes the unit; the WHERE is belt and braces)."""
        async with self.session.unit(tenant_id) as conn:
            cur = await conn.execute("SELECT * FROM app.runs WHERE run_id = %s AND tenant_id = %s", (run_id, tenant_id))
            row = await cur.fetchone()
        return None if row is None else dict(row)

    async def proposal(self, tenant_id: UUID, proposal_id: UUID) -> dict[str, Any] | None:
        """Read one proposal with its run's requester and state."""
        async with self.session.unit(tenant_id) as conn:
            cur = await conn.execute(
                "SELECT p.*, r.requester, r.state AS run_state FROM app.proposals p"
                " JOIN app.runs r ON r.run_id = p.run_id"
                " WHERE p.proposal_id = %s AND p.tenant_id = %s",
                (proposal_id, tenant_id),
            )
            row = await cur.fetchone()
        return None if row is None else dict(row)

    async def decide(self, *, tenant_id: UUID, proposal_id: UUID, reviewer: UUID, request: DecisionRequest) -> Decided:
        """Record the first decision on the exact revision and hash, or raise Conflict / Forbidden / NotFound."""
        try:
            async with self.session.unit(tenant_id) as conn:
                cur = await conn.execute(
                    "SELECT revision FROM app.proposals WHERE proposal_id = %s AND tenant_id = %s",
                    (proposal_id, tenant_id),
                )
                proposal = await cur.fetchone()
                if proposal is None:
                    raise NotFound
                if proposal["revision"] != request.expected_revision:
                    raise Conflict("VERSION_CONFLICT")  # the hash is the function's check; the revision is ours
                decided = await persistence.record_decision(
                    conn,
                    tenant_id=tenant_id,
                    proposal_id=proposal_id,
                    reviewer=reviewer,
                    expected_payload_sha256=request.expected_payload_sha256,
                    decision=request.decision,
                    reason=request.reason,
                )
        except persistence.NotFound as exc:
            raise NotFound from exc
        except persistence.VersionConflict as exc:
            raise Conflict("VERSION_CONFLICT") from exc
        except persistence.Refused as exc:
            raise map_refusal(exc) from exc
        return Decided(proposal_id, decided.run_id, request.decision, decided.state.value, decided.state_version)

    async def events(self, tenant_id: UUID, run_id: UUID, *, after: int, limit: int) -> list[dict[str, Any]]:
        """List a run's events after a sequence number."""
        async with self.session.unit(tenant_id) as conn:
            cur = await conn.execute(
                "SELECT sequence, type, source, occurred_at, payload FROM app.events"
                " WHERE run_id = %s AND tenant_id = %s AND sequence > %s ORDER BY sequence LIMIT %s",
                (run_id, tenant_id, after, limit),
            )
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

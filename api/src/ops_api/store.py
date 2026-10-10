"""The API's door to the database as role `api`: identity through `resolve_identity`, admission through the AM-16
router and `create_run`, clarification replies, decisions through `record_decision`; reads under the tenant's unit,
which RLS scopes. T11: the session store (login_state, sessions, logout_jti).

Every mutation is one idempotent unit (Plan G rulings 4-6, 21): advisory lock on the key's scope, record lookup,
the route's own checks and the router's verdict, the effect, and the record written last (SA:188), committed
together, so the response a client gets is exactly what a replay of the same key returns, and a crash before commit
leaves neither (R015). The record is the response, which is why the units build HTTP status codes and bodies: the
row must hold them before the commit. Three refusals a unit raises instead of recording: a full tenant queue
(`QueueFull`, 429: transient, and a recorded 429 would outlive the queue it describes, ruling 5), a caller the run or
the proposal does not allow (`Forbidden`, 403: a reviewer who is not independent, or another requester answering a
run's question, decided before the work) and a key that is not reusable yet (`IdempotencyConflict`, 409). The
orchestration (`AdmissionStore`) runs over a `Unit` of primitive operations; `DbUnit` is their SQL, and the
unit-test fake supplies an in-memory `Unit` to the same orchestration.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

import psycopg
from ops_core import persistence
from ops_core.contracts import (
    ClarificationReply,
    DecisionRequest,
    ErrorCode,
    MessageKind,
    MessageRequest,
    StoredMessageKind,
)
from ops_core.jobs import JobType, dedup_key
from ops_core.outcomes import EventType
from ops_core.routing import (
    AdmissionDecision,
    AdmissionFacts,
    AdmissionRoute,
    RejectCause,
    route_admission,
    route_reply,
)
from ops_core.states import Intent, RunState
from ops_core.testing.faults import FaultKind, Faults
from psycopg.types.json import Jsonb

from ops_api.idempotency import (
    IDEMPOTENCY_LOCK_NAMESPACE,
    Idem,
    IdempotencyConflict,
    QueueFull,
    Record,
    RecordRace,
    RecordUnit,
    Scope,
    Verdict,
    error_verdict,
    idempotent,
    replay,
)


class Forbidden(Exception):
    """The caller is authenticated but may not do this (maps to 403; never recorded)."""


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


class ReplyRefused(Exception):
    """A clarification reply the run cannot take: the status, code and message of the refusal the unit records."""

    def __init__(self, status: int, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass(frozen=True)
class Membership:
    """A subject's tenant and roles, resolved from the seeded memberships."""

    tenant_id: UUID
    roles: frozenset[str]


@dataclass(frozen=True)
class Accepted:
    """What a started run returns after the message, run, job and `run.accepted` are written."""

    conversation_id: UUID
    message_id: UUID
    run_id: UUID
    status: str
    state_version: int


@dataclass(frozen=True)
class Decided:
    """What a recorded decision returns after the transition."""

    proposal_id: UUID
    run_id: UUID
    decision: str
    status: str
    state_version: int


@dataclass(frozen=True)
class LoginState:
    """One authorization request in flight: the hashes the callback compares and the PKCE verifier it spends."""

    state_sha256: str
    nonce_sha256: str
    code_verifier: str = field(repr=False)


@dataclass(frozen=True)
class SessionRow:
    """A live session as the identity dependency sees it; `refresh_token_enc` is opened only at logout."""

    session_sha256: str
    issuer: str
    subject: UUID
    tenant_id: UUID
    sid: str
    username: str
    csrf_secret_sha256: str = field(repr=False)
    refresh_token_enc: bytes = field(repr=False)


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
    """A function's DETAIL code → the HTTP class BUILD_SPEC §7 names; the code itself never reaches the client."""
    if exc.code in ("NOT_REVIEWER", "SELF_REVIEW", "MEMBERSHIP_INACTIVE"):
        return Forbidden()
    if exc.code == "SLOT_OCCUPIED":
        return Conflict("SLOT_OCCUPIED")
    if exc.code == "INVALID_ARGUMENT":
        return Internal()  # the API's own validation makes this unreachable; a 409 would be a false message
    return Conflict("VERSION_CONFLICT")


def stamp(value: datetime) -> str:
    """A timestamp as UTC `...Z` with whole seconds, the API's one spelling."""
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


STORED_KIND = {
    MessageKind.INVESTIGATE: StoredMessageKind.INVESTIGATE,
    MessageKind.ASK: StoredMessageKind.ASK,
    MessageKind.STATUS: StoredMessageKind.STATUS_QUESTION,
}  # the requester's own row (ruling 26); a clarification reply is stored by its own route
NO_RUNS = "This conversation has no runs yet."
CLARIFICATIONS_HINT = "clarification replies go to /api/v1/runs/{run_id}/clarifications"


def accepted_body(conversation_id: UUID, message_id: UUID, run_id: UUID, status: str, version: int) -> dict[str, Any]:
    """BS:299's accepted response; `stream_url` waits for the stream route (TODO(T27))."""
    return {
        "conversation_id": str(conversation_id),
        "message_id": str(message_id),
        "run_id": str(run_id),
        "status": status,
        "state_version": version,
        "status_url": f"/api/v1/runs/{run_id}",
        "events_url": f"/api/v1/runs/{run_id}/events",
    }


def status_text(run: dict[str, Any] | None, event: dict[str, Any] | None) -> str:
    """The status answer, from recorded state and events only (AM-16 status_question; ruling 14)."""
    if run is None:
        return NO_RUNS
    head = f"Run {run['run_id']} is {run['state']} (version {run['state_version']})"
    if event is None:
        return f"{head}; no event is recorded yet."
    return f"{head}; the last recorded event is {event['type']} at {stamp(event['occurred_at'])}."


def reply_text(reply: ClarificationReply) -> str:
    """The stored text of a clarification reply: the fields it supplies, rendered (ruling 15)."""
    asset = reply.context.asset_id or "-"
    hours = "-" if reply.context.hours is None else str(reply.context.hours)
    return f"Clarification: asset {asset}, hours {hours}"


def check_reply_run(run: dict[str, Any] | None, *, requester: UUID, expected_version: int) -> dict[str, Any]:
    """The run a reply may bind to, read under its row lock (ruling 15): the caller's own run, waiting for input at
    the version the client read.

    An absent run (another tenant's included: RLS hides it) is the recorded 404. Another requester of the tenant may
    read the run, so its refusal is Forbidden, the unrecorded 403 (BS:301: a known resource, a disallowed operation):
    a reply shapes the run's draft, so its author must never be someone who could then review that draft (SA:539).
    """
    if run is None:
        raise ReplyRefused(404, ErrorCode.NOT_FOUND, "no such run")
    if run["requester"] != requester:
        raise Forbidden
    if run["state"] != RunState.AWAITING_INPUT.value or run["state_version"] != expected_version:
        raise ReplyRefused(409, ErrorCode.VERSION_CONFLICT, "the run is not waiting at that version")
    return run


def check_reply_question(asked: list[UUID], question_id: UUID) -> None:
    """The question a reply answers must be the run's latest `clarification.requested` (`asked` in sequence order).
    An earlier question of the same run is a stale version, 409 like any other (BS:301); an id the run never asked
    is 404."""
    if question_id not in asked:
        raise ReplyRefused(404, ErrorCode.NOT_FOUND, "no outstanding clarification")
    if asked[-1] != question_id:
        raise ReplyRefused(409, ErrorCode.VERSION_CONFLICT, "the clarification was superseded")


class Unit(RecordUnit, Protocol):
    """The primitive operations of one admission transaction under one tenant (Plan G ruling 21)."""

    async def now(self) -> datetime:
        """The application clock, read inside the unit (ruling 11)."""
        ...

    async def conversation_exists(self, conversation_id: UUID) -> bool:
        """Whether the conversation is the tenant's."""
        ...

    async def insert_conversation(self, created_by: UUID) -> UUID:
        """Create an empty conversation."""
        ...

    async def queued_count(self) -> int:
        """QUEUED runs of the tenant (ruling 18)."""
        ...

    async def active_run(self, conversation_id: UUID) -> bool:
        """Whether a run holds the conversation's slot (read, not locked: ruling 9)."""
        ...

    async def latest_run(self, conversation_id: UUID) -> dict[str, Any] | None:
        """The newest run: `run_id`, `state`, `state_version`."""
        ...

    async def latest_event(self, run_id: UUID) -> dict[str, Any] | None:
        """The run's newest event: `type`, `occurred_at`."""
        ...

    async def insert_message(
        self,
        *,
        conversation_id: UUID,
        kind: StoredMessageKind,
        text: str,
        context: dict[str, Any] | None,
        author: UUID | None,
    ) -> UUID:
        """Insert one message; `author` is None for the system kinds only (revision 0006's CHECK)."""
        ...

    async def start_run(
        self,
        *,
        conversation_id: UUID,
        requester: UUID,
        kind: StoredMessageKind,
        text: str,
        context: dict[str, Any],
        intent: Intent,
        asset_id: str,
        start_at: datetime,
        end_at: datetime,
        supersedes_run_id: UUID | None,
    ) -> Accepted:
        """Message plus `create_run`, atomically within the unit: Conflict (slot) or NotFound (supersedes) leave
        neither, and the unit stays usable for the record."""
        ...

    async def record_reply(
        self,
        *,
        run_id: UUID,
        requester: UUID,
        question_id: UUID,
        expected_version: int,
        text: str,
        context: dict[str, Any],
    ) -> Accepted:
        """Lock the run (SA:186), check it (`check_reply_run`, `check_reply_question`), then the message, the
        `resume_input` job and `clarification.received`, atomically within the unit. Every refusal of the run's state
        or question, the question already answered included (the job's dedup key exists), is ReplyRefused and leaves
        the unit usable; another requester is Forbidden, which ends the unit unrecorded."""
        ...

    async def proposal(self, proposal_id: UUID) -> dict[str, Any] | None:
        """A proposal with its run's requester (`revision`, `authored_by`, `requester`, ...)."""
        ...

    async def record_decision(
        self, *, proposal_id: UUID, reviewer: UUID, request: DecisionRequest, key: str
    ) -> Decided:
        """`record_decision` within the unit; Conflict or NotFound leave the unit usable, Forbidden ends it."""
        ...


Work = Callable[[Unit], Awaitable[Verdict]]


class AdmissionStore:
    """The idempotent mutations of T12, written once over `Unit` (rulings 13-15, 21-25)."""

    faults: Faults | None = None  # set by create_app under PROFILE=test only (ruling 24)

    def unit(self, tenant_id: UUID) -> AbstractAsyncContextManager[Unit]:
        """One transaction under the tenant; implementations roll back on any exception."""
        raise NotImplementedError

    async def _idempotent(self, tenant_id: UUID, idem: Idem, work: Work) -> Verdict:
        try:
            async with self.unit(tenant_id) as unit:
                return await idempotent(unit, idem, lambda: work(unit))
        except RecordRace:
            pass  # the unit rolled back; the re-read below answers from whatever row blocked the insert
        async with self.unit(tenant_id) as unit:
            await unit.lock_scope(idem.scope.lock_key)
            found = await unit.find_record(idem.scope)
        if found is None:
            # The row that blocked the insert is an expired record the sweeper has not purged yet (ruling 7).
            raise IdempotencyConflict("Idempotency-Key is not reusable yet; use a new key")
        if found.fingerprint != idem.fingerprint:
            raise IdempotencyConflict
        return replay(found, idem)

    async def open_conversation(self, *, idem: Idem, tenant_id: UUID, created_by: UUID) -> Verdict:
        """201 `{conversation_id}`; a replay returns the same id (ruling 22)."""

        async def work(unit: Unit) -> Verdict:
            cid = await unit.insert_conversation(created_by)
            return Verdict(201, {"conversation_id": str(cid)})

        return await self._idempotent(tenant_id, idem, work)

    async def admit_message(
        self,
        *,
        idem: Idem,
        tenant_id: UUID,
        conversation_id: UUID,
        requester: UUID,
        request: MessageRequest,
        quota: int,
    ) -> Verdict:
        """The messages route's unit in ruling 21's order: conversation, quota count, active run, router, effect."""
        rid = idem.request_id

        async def work(unit: Unit) -> Verdict:
            if not await unit.conversation_exists(conversation_id):
                return error_verdict(404, ErrorCode.NOT_FOUND, "no such conversation", rid)
            queued = await unit.queued_count()
            context = request.context
            decision = route_admission(
                AdmissionFacts(
                    kind=request.kind,
                    text=request.text,
                    asset_id=None if context is None else context.asset_id,
                    hours=None if context is None else context.hours,
                    active_run=await unit.active_run(conversation_id),
                    hint=None,  # TODO(T19): the model router may supply a hint; it can only produce clarify
                )
            )
            if decision.route is AdmissionRoute.REJECT:
                if decision.cause == RejectCause.SLOT_OCCUPIED:
                    return error_verdict(
                        409, ErrorCode.SLOT_OCCUPIED, "the conversation already has an active run", rid
                    )
                return error_verdict(422, ErrorCode.INVALID_INPUT, CLARIFICATIONS_HINT, rid)
            if decision.route is AdmissionRoute.STATUS_QUESTION:
                return await self.status_answer(
                    unit, conversation_id=conversation_id, requester=requester, request=request
                )
            if decision.route is AdmissionRoute.CLARIFY:
                return await self.clarify(
                    unit, conversation_id=conversation_id, requester=requester, request=request, decision=decision
                )
            # Ruling 18: the quota bounds what would start a run; a status question or a clarification adds nothing
            # to the queue, so the count read above refuses only here. Raised, never recorded (ruling 5): the queue
            # drains, and the same key must then be admitted.
            if queued >= quota:
                raise QueueFull
            return await self._start(
                unit,
                idem=idem,
                conversation_id=conversation_id,
                requester=requester,
                request=request,
                decision=decision,
            )

        return await self._idempotent(tenant_id, idem, work)

    async def status_answer(
        self, unit: Unit, *, conversation_id: UUID, requester: UUID, request: MessageRequest
    ) -> Verdict:
        """The status_question route: the question and its answer as two messages, no run, no job, no event."""
        question_id = await unit.insert_message(
            conversation_id=conversation_id,
            kind=StoredMessageKind.STATUS_QUESTION,
            text=request.text,
            context=None if request.context is None else request.context.model_dump(mode="json"),
            author=requester,
        )
        run = await unit.latest_run(conversation_id)
        event = None if run is None else await unit.latest_event(run["run_id"])
        answer = status_text(run, event)
        answer_id = await unit.insert_message(
            conversation_id=conversation_id,
            kind=StoredMessageKind.STATUS_ANSWER,
            text=answer,
            context={"run_id": None if run is None else str(run["run_id"]), "reply_to": str(question_id)},
            author=None,
        )
        return Verdict(
            200,
            {
                "conversation_id": str(conversation_id),
                "question_id": str(question_id),
                "answer_id": str(answer_id),
                "answer": answer,
                "run_id": None if run is None else str(run["run_id"]),
                "status": None if run is None else run["state"],
                "state_version": None if run is None else run["state_version"],
            },
        )

    async def clarify(
        self,
        unit: Unit,
        *,
        conversation_id: UUID,
        requester: UUID,
        request: MessageRequest,
        decision: AdmissionDecision,
    ) -> Verdict:
        """The clarify route: the request and the stored question as two messages, no run (R018: never a guess)."""
        message_id = await unit.insert_message(
            conversation_id=conversation_id,
            kind=STORED_KIND[request.kind],
            text=request.text,
            context=None if request.context is None else request.context.model_dump(mode="json"),
            author=requester,
        )
        question = decision.question or ""
        question_id = await unit.insert_message(
            conversation_id=conversation_id,
            kind=StoredMessageKind.CLARIFICATION_QUESTION,
            text=question,
            context={"cause": decision.cause, "reply_to": str(message_id)},
            author=None,
        )
        return Verdict(
            200,
            {
                "conversation_id": str(conversation_id),
                "message_id": str(message_id),
                "question_id": str(question_id),
                "cause": decision.cause,
                "question": question,
                "status": "clarification_needed",
            },
        )

    async def _start(
        self,
        unit: Unit,
        *,
        idem: Idem,
        conversation_id: UUID,
        requester: UUID,
        request: MessageRequest,
        decision: AdmissionDecision,
    ) -> Verdict:
        """The investigate and readonly_answer routes: the interval resolved once on the database clock, then message
        and run together (R015); the record keeps the interval, so a replay never moves it (R018)."""
        if decision.asset_id is None or decision.hours is None:
            raise Internal("the router admitted a run without an asset or a window")
        start_at, end_at = resolve_interval(decision.hours, await unit.now())
        intent = Intent.INVESTIGATE if decision.route is AdmissionRoute.INVESTIGATE else Intent.ANSWER_ONLY
        try:
            accepted = await unit.start_run(
                conversation_id=conversation_id,
                requester=requester,
                kind=STORED_KIND[request.kind],
                text=request.text,
                context={"asset_id": decision.asset_id, "hours": decision.hours},
                intent=intent,
                asset_id=decision.asset_id,
                start_at=start_at,
                end_at=end_at,
                supersedes_run_id=request.supersedes_run_id,
            )
        except NotFound:
            return error_verdict(404, ErrorCode.NOT_FOUND, "no such superseded run", idem.request_id)
        except Conflict:
            # A concurrent admission took the slot after the active-run read: the index is the backstop (ruling 9).
            return error_verdict(
                409, ErrorCode.SLOT_OCCUPIED, "the conversation already has an active run", idem.request_id
            )
        if self.faults is not None and self.faults.take(FaultKind.DROP_BEFORE_COMMIT):
            # R015's crash: the message and the run exist inside the transaction, the record and the commit do not.
            # A real crash here is a lost connection, so the client sees what that shows: a retryable 503 (ruling 24).
            raise psycopg.OperationalError("fault: drop_before_commit")
        return Verdict(
            202,
            accepted_body(
                conversation_id, accepted.message_id, accepted.run_id, accepted.status, accepted.state_version
            ),
        )

    async def reply_clarification(
        self, *, idem: Idem, tenant_id: UUID, run_id: UUID, requester: UUID, reply: ClarificationReply
    ) -> Verdict:
        """BS:273's route, the clarification_reply entry (ruling 15): the requester's reply, bound under the run's lock
        to its outstanding question and expected version; message, `resume_input` job and `clarification.received`
        together, then 202."""

        async def work(unit: Unit) -> Verdict:
            text = reply_text(reply)
            decision = route_reply(
                AdmissionFacts(
                    kind=MessageKind.CLARIFICATION,
                    text=text,
                    asset_id=reply.context.asset_id,
                    hours=reply.context.hours,
                    active_run=True,
                )
            )
            if decision.route is not AdmissionRoute.CLARIFICATION_REPLY:
                raise Internal("a bound reply did not route to clarification_reply")
            try:
                accepted = await unit.record_reply(
                    run_id=run_id,
                    requester=requester,
                    question_id=reply.question_id,
                    expected_version=reply.expected_version,
                    text=text,
                    context=reply.context.model_dump(mode="json"),
                )
            except ReplyRefused as exc:
                return error_verdict(exc.status, exc.code, exc.message, idem.request_id)
            return Verdict(
                202,
                accepted_body(
                    accepted.conversation_id, accepted.message_id, run_id, accepted.status, accepted.state_version
                ),
            )

        return await self._idempotent(tenant_id, idem, work)

    async def decide_once(
        self,
        *,
        idem: Idem,
        tenant_id: UUID,
        proposal_id: UUID,
        reviewer: UUID,
        roles: frozenset[str],
        request: DecisionRequest,
    ) -> Verdict:
        """The first decision on the exact revision and hash by an independent current reviewer (SA:454); the key
        is also stored on the decision row (ruling 21). A reviewer refusal raises Forbidden: never recorded."""
        rid = idem.request_id

        async def work(unit: Unit) -> Verdict:
            row = await unit.proposal(proposal_id)
            if row is None:
                return error_verdict(404, ErrorCode.NOT_FOUND, "no such proposal", rid)
            check_reviewer(
                Membership(tenant_id, roles),
                requester=row["requester"],
                authored_by=list(row["authored_by"]),
                reviewer=reviewer,
            )
            stale = "the proposal is not the active, undecided revision"
            if row["revision"] != request.expected_revision:
                return error_verdict(409, ErrorCode.VERSION_CONFLICT, stale, rid)
            try:
                decided = await unit.record_decision(
                    proposal_id=proposal_id, reviewer=reviewer, request=request, key=idem.scope.key
                )
            except NotFound:
                return error_verdict(404, ErrorCode.NOT_FOUND, "no such proposal", rid)
            except Conflict as exc:
                return error_verdict(409, ErrorCode(exc.code), stale, rid)
            return Verdict(
                200,
                {
                    "proposal_id": str(decided.proposal_id),
                    "run_id": str(decided.run_id),
                    "decision": decided.decision,
                    "status": decided.status,
                    "state_version": decided.state_version,
                },
            )

        return await self._idempotent(tenant_id, idem, work)


class Store(Protocol):
    """What the routes use: T12's idempotent mutations, the reads, and T11's seven session operations; the unit tests
    fake it on top of `AdmissionStore`, `DbStore` implements it."""

    faults: Faults | None

    async def membership(self, issuer: str, subject: UUID) -> Membership | None:
        """Resolve a verified subject to its active tenant membership, or None."""
        ...

    async def open_conversation(self, *, idem: Idem, tenant_id: UUID, created_by: UUID) -> Verdict:
        """Create an empty conversation in the tenant (idempotent)."""
        ...

    async def admit_message(
        self,
        *,
        idem: Idem,
        tenant_id: UUID,
        conversation_id: UUID,
        requester: UUID,
        request: MessageRequest,
        quota: int,
    ) -> Verdict:
        """Route and commit one message (idempotent)."""
        ...

    async def reply_clarification(
        self, *, idem: Idem, tenant_id: UUID, run_id: UUID, requester: UUID, reply: ClarificationReply
    ) -> Verdict:
        """Bind a reply to the run's outstanding question (idempotent)."""
        ...

    async def decide_once(
        self,
        *,
        idem: Idem,
        tenant_id: UUID,
        proposal_id: UUID,
        reviewer: UUID,
        roles: frozenset[str],
        request: DecisionRequest,
    ) -> Verdict:
        """Record the first decision (idempotent)."""
        ...

    # TODO(T12): the three pre-Plan-G mutations below serve the routes until Plan G Task 5 moves them to the
    # idempotent units above; Task 5 deletes them.
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

    async def decide(self, *, tenant_id: UUID, proposal_id: UUID, reviewer: UUID, request: DecisionRequest) -> Decided:
        """Record the first decision on the exact revision and hash, or raise Conflict."""
        ...

    async def run(self, tenant_id: UUID, run_id: UUID) -> dict[str, Any] | None:
        """Read one run row in the tenant."""
        ...

    async def proposal(self, tenant_id: UUID, proposal_id: UUID) -> dict[str, Any] | None:
        """Read one proposal with its run's requester and state."""
        ...

    async def events(self, tenant_id: UUID, run_id: UUID, *, after: int, limit: int) -> list[dict[str, Any]]:
        """List a run's events after a sequence number."""
        ...

    async def begin_login(
        self, *, login_sha256: str, state_sha256: str, nonce_sha256: str, code_verifier: str, ttl_seconds: int
    ) -> None:
        """Store one authorization request under the login cookie's hash."""
        ...

    async def take_login(self, login_sha256: str) -> LoginState | None:
        """Consume the request (one shot): its state, or None when absent or expired."""
        ...

    async def create_session(
        self,
        *,
        session_sha256: str,
        issuer: str,
        subject: UUID,
        tenant_id: UUID,
        sid: str,
        username: str,
        csrf_secret_sha256: str,
        refresh_token_enc: bytes,
        absolute_seconds: int,
    ) -> None:
        """Insert a session row with its absolute expiry."""
        ...

    async def live_session(self, session_sha256: str, *, idle_seconds: int) -> SessionRow | None:
        """The row if live (not revoked, inside both limits), touching `last_seen_at`; else None."""
        ...

    async def revoke_session(self, session_sha256: str) -> SessionRow | None:
        """Revoke one session; the row it was (for the sealed refresh token), or None if none was live."""
        ...

    async def expire_session(self, session_sha256: str, *, idle_seconds: int) -> SessionRow | None:
        """Revoke a session that is past either limit; the row it was (for the sealed refresh token), or None."""
        ...

    async def record_logout(self, jti: str, *, expires_at: datetime, sid: str) -> int | None:
        """Record a logout token's jti and revoke every session with its sid, atomically; None on a replay."""
        ...


class DbUnit:
    """`Unit` in SQL over the transaction a `persistence.Session` unit opened, as role `api` under one tenant."""

    def __init__(self, conn: persistence.Conn, tenant_id: UUID) -> None:
        self.conn = conn
        self.tenant_id = tenant_id

    async def lock_scope(self, lock_key: str) -> None:
        """Ruling 6: first statement of the unit, before every table lock; no grant needed (spike §6). The two-key
        form in IDEMPOTENCY_LOCK_NAMESPACE never meets the asset guard's one-key locks (erratum 37)."""
        await self.conn.execute(
            "SELECT pg_advisory_xact_lock(%s::int, hashtext(%s::text))", (IDEMPOTENCY_LOCK_NAMESPACE, lock_key)
        )

    async def find_record(self, scope: Scope) -> Record | None:
        """The live record of the scope; an expired row is ignored here and purged by the sweeper."""
        cur = await self.conn.execute(
            "SELECT fingerprint_sha256, status_code, response FROM app.idempotency_request"
            " WHERE tenant_id = %s AND subject = %s AND route = %s AND key = %s AND expires_at > app.current_time()",
            (scope.tenant_id, scope.subject, scope.route, scope.key),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        return Record(str(row["fingerprint_sha256"]), int(row["status_code"]), dict(row["response"]))

    async def save_record(self, scope: Scope, fingerprint: str, verdict: Verdict, ttl_seconds: int) -> bool:
        """Insert the record last in the unit (SA:188); False when a row for the scope already exists."""
        # Target-less ON CONFLICT DO NOTHING: `api` holds INSERT and SELECT, and a 23505 here would print the scope
        # in its DETAIL (spike §1); rowcount 0 is the verdict.
        cur = await self.conn.execute(
            "INSERT INTO app.idempotency_request (tenant_id, subject, route, key, fingerprint_sha256, status_code,"
            " response, expires_at) VALUES (%s, %s, %s, %s, %s, %s, %s,"
            " app.current_time() + make_interval(secs => %s)) ON CONFLICT DO NOTHING",
            (
                scope.tenant_id,
                scope.subject,
                scope.route,
                scope.key,
                fingerprint,
                verdict.status,
                Jsonb(verdict.body),
                ttl_seconds,
            ),
        )
        return cur.rowcount == 1

    async def now(self) -> datetime:
        """`app.current_time()` inside the unit: the clock the interval and the record expiry share."""
        return await persistence.current_time(self.conn)

    async def conversation_exists(self, conversation_id: UUID) -> bool:
        """Whether the conversation is this tenant's (RLS scopes it; the WHERE is belt and braces)."""
        cur = await self.conn.execute(
            "SELECT 1 FROM app.conversations WHERE conversation_id = %s AND tenant_id = %s",
            (conversation_id, self.tenant_id),
        )
        return await cur.fetchone() is not None

    async def insert_conversation(self, created_by: UUID) -> UUID:
        """A plain INSERT under the tenant: `api` holds INSERT on conversations (SA:414)."""
        cid = uuid4()
        await self.conn.execute(
            "INSERT INTO app.conversations (conversation_id, tenant_id, created_by) VALUES (%s, %s, %s)",
            (cid, self.tenant_id, created_by),
        )
        return cid

    async def queued_count(self) -> int:
        """QUEUED runs of the tenant (ruling 18)."""
        return await persistence.queued_count(self.conn)

    async def active_run(self, conversation_id: UUID) -> bool:
        """Whether a run holds the slot; a read, not a lock (ruling 9: `api` cannot lock conversations)."""
        return await persistence.latest_active_run(self.conn, conversation_id) is not None

    async def latest_run(self, conversation_id: UUID) -> dict[str, Any] | None:
        """The newest run of the conversation, for a status answer."""
        row = await persistence.latest_run(self.conn, conversation_id)
        return None if row is None else dict(row)

    async def latest_event(self, run_id: UUID) -> dict[str, Any] | None:
        """The run's newest event, for a status answer."""
        row = await persistence.latest_event(self.conn, run_id)
        return None if row is None else dict(row)

    async def insert_message(
        self,
        *,
        conversation_id: UUID,
        kind: StoredMessageKind,
        text: str,
        context: dict[str, Any] | None,
        author: UUID | None,
    ) -> UUID:
        """One `messages` row under the tenant; `seq` comes from revision 0006's identity column."""
        message_id = uuid4()
        await self.conn.execute(
            "INSERT INTO app.messages (message_id, tenant_id, conversation_id, kind, text, context, author)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                message_id,
                self.tenant_id,
                conversation_id,
                kind.value,
                text,
                None if context is None else Jsonb(context),
                author,
            ),
        )
        return message_id

    async def start_run(
        self,
        *,
        conversation_id: UUID,
        requester: UUID,
        kind: StoredMessageKind,
        text: str,
        context: dict[str, Any],
        intent: Intent,
        asset_id: str,
        start_at: datetime,
        end_at: datetime,
        supersedes_run_id: UUID | None,
    ) -> Accepted:
        """Message plus `create_run` inside a savepoint, mapping the function's refusals."""
        try:
            # A savepoint: a refusal inside create_run aborts only these two statements, so the unit can still
            # write the 409 or 404 record (AM-16 reject: nothing written except the idempotency record).
            async with self.conn.transaction():
                message_id = await self.insert_message(
                    conversation_id=conversation_id, kind=kind, text=text, context=context, author=requester
                )
                # The function validates the supersedes target against tenant and conversation (SA:450, erratum).
                run_id, version = await persistence.create_run(
                    self.conn,
                    tenant_id=self.tenant_id,
                    conversation_id=conversation_id,
                    message_id=message_id,
                    requester=requester,
                    intent=intent,
                    asset_id=asset_id,
                    start_at=start_at,
                    end_at=end_at,
                    supersedes_run_id=supersedes_run_id,
                )
        except persistence.NotFound as exc:
            raise NotFound from exc
        except persistence.Refused as exc:
            raise map_refusal(exc) from exc
        return Accepted(conversation_id, message_id, run_id, RunState.QUEUED.value, version)

    async def record_reply(
        self,
        *,
        run_id: UUID,
        requester: UUID,
        question_id: UUID,
        expected_version: int,
        text: str,
        context: dict[str, Any],
    ) -> Accepted:
        """The run locked, then checked, then message, `resume_input` job and `clarification.received` inside a
        savepoint (ruling 15)."""
        # SA:186: an API mutation serialises on the run row (FOR UPDATE plus expected_version), and SA:188 puts runs
        # before messages, so this lock is the unit's first table statement after the record lookup: a cancel
        # or a worker transition waits for this unit or wins before it, never in between, and `append_event` below
        # re-takes a lock the unit already holds. `api` holds a column UPDATE on runs (Plan E ruling 23).
        cur = await self.conn.execute(
            "SELECT run_id, state, state_version, requester, conversation_id FROM app.runs"
            " WHERE run_id = %s FOR UPDATE",
            (run_id,),
        )
        found = await cur.fetchone()
        run = check_reply_run(
            None if found is None else dict(found), requester=requester, expected_version=expected_version
        )
        cur = await self.conn.execute(
            "SELECT event_id FROM app.events WHERE run_id = %s AND type = %s ORDER BY sequence",
            (run_id, EventType.CLARIFICATION_REQUESTED.value),
        )
        check_reply_question([UUID(str(row["event_id"])) for row in await cur.fetchall()], question_id)
        async with self.conn.transaction():  # a savepoint, as in start_run: a refusal below rolls the message back
            message_id = await self.insert_message(
                conversation_id=run["conversation_id"],
                kind=StoredMessageKind.CLARIFICATION_REPLY,
                text=text,
                context=context,
                author=requester,
            )
            key = dedup_key(JobType.RESUME_INPUT, run_id=run_id, clarification_event_id=question_id)
            queued = await persistence.insert_job_untargeted(
                self.conn, job_type=JobType.RESUME_INPUT, tenant_id=self.tenant_id, run_id=run_id, key=key
            )
            if not queued:
                raise ReplyRefused(409, ErrorCode.VERSION_CONFLICT, "the clarification was already answered")
            await persistence.append_event(
                self.conn,
                run_id=run_id,
                type=EventType.CLARIFICATION_RECEIVED,
                payload={"question_id": str(question_id), "message_id": str(message_id)},
            )
        return Accepted(run["conversation_id"], message_id, run_id, run["state"], run["state_version"])

    async def proposal(self, proposal_id: UUID) -> dict[str, Any] | None:
        """A proposal with its run's requester and state, as the reviewer check needs it."""
        cur = await self.conn.execute(
            "SELECT p.*, r.requester, r.state AS run_state FROM app.proposals p"
            " JOIN app.runs r ON r.run_id = p.run_id"
            " WHERE p.proposal_id = %s AND p.tenant_id = %s",
            (proposal_id, self.tenant_id),
        )
        row = await cur.fetchone()
        return None if row is None else dict(row)

    async def record_decision(
        self, *, proposal_id: UUID, reviewer: UUID, request: DecisionRequest, key: str
    ) -> Decided:
        """`record_decision` with the key stored on the decision row, inside a savepoint."""
        try:
            async with self.conn.transaction():  # a savepoint, so a lost race still leaves the unit able to record
                decided = await persistence.record_decision(
                    self.conn,
                    tenant_id=self.tenant_id,
                    proposal_id=proposal_id,
                    reviewer=reviewer,
                    expected_payload_sha256=request.expected_payload_sha256,
                    decision=request.decision,
                    reason=request.reason,
                    idempotency_key=key,
                )
        except persistence.NotFound as exc:
            raise NotFound from exc
        except persistence.VersionConflict as exc:
            raise Conflict("VERSION_CONFLICT") from exc
        except persistence.Refused as exc:
            raise map_refusal(exc) from exc
        return Decided(proposal_id, decided.run_id, request.decision, decided.state.value, decided.state_version)


class DbStore(AdmissionStore):
    """The PostgreSQL implementation of `Store` over one autocommit connection as role `api`."""

    def __init__(self, conn: persistence.Conn) -> None:
        self.session = persistence.Session(conn)  # ruling 24: one unit of work at a time, each a real transaction

    @asynccontextmanager
    async def unit(self, tenant_id: UUID) -> AsyncIterator[Unit]:
        """The tenant unit of `persistence.Session`, as a `DbUnit`."""
        async with self.session.unit(tenant_id) as conn:
            yield DbUnit(conn, tenant_id)

    async def membership(self, issuer: str, subject: UUID) -> Membership | None:
        """Resolve a verified subject to its active tenant membership, or None."""
        async with self.session.unit() as conn:  # the function walks the tenants itself (Plan E ruling 4)
            rows = await persistence.resolve_identity(conn, issuer=issuer, subject=subject)
        return single_tenant(rows)

    # TODO(T12): the three pre-Plan-G mutations below serve the routes until Plan G Task 5 moves them to the
    # idempotent units; Task 5 deletes them.
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

    async def run(self, tenant_id: UUID, run_id: UUID) -> dict[str, Any] | None:
        """Read one run row in the tenant (RLS scopes the unit; the WHERE is belt and braces)."""
        async with self.session.unit(tenant_id) as conn:
            cur = await conn.execute("SELECT * FROM app.runs WHERE run_id = %s AND tenant_id = %s", (run_id, tenant_id))
            row = await cur.fetchone()
        return None if row is None else dict(row)

    async def proposal(self, tenant_id: UUID, proposal_id: UUID) -> dict[str, Any] | None:
        """Read one proposal with its run's requester and state."""
        async with self.unit(tenant_id) as unit:
            return await unit.proposal(proposal_id)

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

    async def begin_login(
        self, *, login_sha256: str, state_sha256: str, nonce_sha256: str, code_verifier: str, ttl_seconds: int
    ) -> None:
        """Store one authorization request under the login cookie's hash."""
        async with self.session.unit() as conn:
            await conn.execute(
                "INSERT INTO app.login_state (login_sha256, state_sha256, nonce_sha256, code_verifier, expires_at)"
                " VALUES (%s, %s, %s, %s, app.current_time() + make_interval(secs => %s))",
                (login_sha256, state_sha256, nonce_sha256, code_verifier, ttl_seconds),
            )

    async def take_login(self, login_sha256: str) -> LoginState | None:
        """Consume the request (one shot): its state, or None when absent or expired."""
        async with self.session.unit() as conn:
            cur = await conn.execute(
                "DELETE FROM app.login_state WHERE login_sha256 = %s"
                " RETURNING state_sha256, nonce_sha256, code_verifier, expires_at > app.current_time() AS live",
                (login_sha256,),
            )
            row = await cur.fetchone()
        if row is None or not row["live"]:
            return None
        return LoginState(str(row["state_sha256"]), str(row["nonce_sha256"]), str(row["code_verifier"]))

    async def create_session(
        self,
        *,
        session_sha256: str,
        issuer: str,
        subject: UUID,
        tenant_id: UUID,
        sid: str,
        username: str,
        csrf_secret_sha256: str,
        refresh_token_enc: bytes,
        absolute_seconds: int,
    ) -> None:
        """Insert a session row with its absolute expiry (every timestamp from app.current_time(), R126)."""
        async with self.session.unit() as conn:
            await conn.execute(
                "INSERT INTO app.sessions (session_sha256, issuer, subject, tenant_id, sid, username,"
                " csrf_secret_sha256, refresh_token_enc, created_at, last_seen_at, expires_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, app.current_time(), app.current_time(),"
                " app.current_time() + make_interval(secs => %s))",
                (
                    session_sha256,
                    issuer,
                    subject,
                    tenant_id,
                    sid,
                    username,
                    csrf_secret_sha256,
                    refresh_token_enc,
                    absolute_seconds,
                ),
            )

    async def live_session(self, session_sha256: str, *, idle_seconds: int) -> SessionRow | None:
        """The row if live, touching `last_seen_at` in the same statement: one UPDATE … RETURNING decides liveness
        (BUILD_SPEC §9 idle and absolute limits), so Python compares no clocks."""
        async with self.session.unit() as conn:
            cur = await conn.execute(
                "UPDATE app.sessions SET last_seen_at = app.current_time()"
                " WHERE session_sha256 = %s AND revoked_at IS NULL AND expires_at > app.current_time()"
                " AND last_seen_at > app.current_time() - make_interval(secs => %s)"
                " RETURNING session_sha256, issuer, subject, tenant_id, sid, username, csrf_secret_sha256,"
                " refresh_token_enc",
                (session_sha256, idle_seconds),
            )
            row = await cur.fetchone()
        return None if row is None else _session_row(row)

    async def revoke_session(self, session_sha256: str) -> SessionRow | None:
        """Revoke one session; the row it was, or None if none was live."""
        async with self.session.unit() as conn:
            cur = await conn.execute(
                "UPDATE app.sessions SET revoked_at = app.current_time()"
                " WHERE session_sha256 = %s AND revoked_at IS NULL"
                " RETURNING session_sha256, issuer, subject, tenant_id, sid, username, csrf_secret_sha256,"
                " refresh_token_enc",
                (session_sha256,),
            )
            row = await cur.fetchone()
        return None if row is None else _session_row(row)

    async def expire_session(self, session_sha256: str, *, idle_seconds: int) -> SessionRow | None:
        """Revoke a session the limits have ended (final review I1): the same clock as `live_session`, the inverse
        of its limits, so the caller can end the provider session too. Only the first caller gets the row."""
        async with self.session.unit() as conn:
            cur = await conn.execute(
                "UPDATE app.sessions SET revoked_at = app.current_time()"
                " WHERE session_sha256 = %s AND revoked_at IS NULL AND (expires_at <= app.current_time()"
                " OR last_seen_at <= app.current_time() - make_interval(secs => %s))"
                " RETURNING session_sha256, issuer, subject, tenant_id, sid, username, csrf_secret_sha256,"
                " refresh_token_enc",
                (session_sha256, idle_seconds),
            )
            row = await cur.fetchone()
        return None if row is None else _session_row(row)

    async def record_logout(self, jti: str, *, expires_at: datetime, sid: str) -> int | None:
        """The jti insert and the revocation commit together (spike §5): a rolled-back revocation does not consume
        the token. A target-less ON CONFLICT DO NOTHING needs INSERT only; rowcount 0 is the replay."""
        async with self.session.unit() as conn:
            cur = await conn.execute(
                "INSERT INTO app.logout_jti (jti, expires_at) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (jti, expires_at),
            )
            if cur.rowcount != 1:
                return None
            cur = await conn.execute(
                "UPDATE app.sessions SET revoked_at = app.current_time() WHERE sid = %s AND revoked_at IS NULL", (sid,)
            )
            return int(cur.rowcount)


def _session_row(row: Any) -> SessionRow:
    return SessionRow(
        session_sha256=str(row["session_sha256"]),
        issuer=str(row["issuer"]),
        subject=UUID(str(row["subject"])),
        tenant_id=UUID(str(row["tenant_id"])),
        sid=str(row["sid"]),
        username=str(row["username"]),
        csrf_secret_sha256=str(row["csrf_secret_sha256"]),
        refresh_token_enc=bytes(row["refresh_token_enc"]),
    )

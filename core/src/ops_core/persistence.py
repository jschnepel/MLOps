"""The one door to the application database: a thin Python wrapper per AM-20.3 definer function, plus the few plain
statements a runtime role may run under its own grants (T09; SPEC_AMENDMENTS AM-20.2/20.3).

Every state transition, decision, grant, attempt step and event happens inside a SECURITY DEFINER function
(migrations/app/versions/0003 and 0004); nothing here writes runs.state or an audit table. A function refuses with
SQLSTATE class OC, which `translate` turns into the typed exceptions services already catch. Any unit of work that
touches a tenant table opens as `Session.unit(tenant_id)`, which sets the transaction-local tenant first: RLS admits
nothing otherwise, and a reused connection's setting is '' between units (spike §1, §2). Pools arrive with T30.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import DictRow, dict_row
from psycopg.types.json import Jsonb

from ops_core.canonical import sha256_hex
from ops_core.embeddings import vector_literal
from ops_core.jobs import ATTEMPT_STATES, JOB_RULES, JobType, Server, Tool, dedup_key
from ops_core.lease import LOCK_FOR_SHARE, LOCK_FOR_UPDATE, LOCK_FOR_UPDATE_NOWAIT, RELEASED, Busy, Lease, LeaseLost
from ops_core.outcomes import ActionOutcome, EventRuleViolation, EventSource, EventType, ToolOutcome
from ops_core.routing import RunManifest
from ops_core.settings import Postgres, Profile
from ops_core.states import AttemptState, IllegalTransition, Intent, Reason, RunState

Conn = psycopg.AsyncConnection[DictRow]
log = logging.getLogger("ops_core.persistence")


class PersistenceError(Exception):
    """Base class; messages are safe for logs and HTTP bodies (no handle, token or secret)."""


class NotFound(PersistenceError):
    """The row is absent or belongs to another tenant; the two cases are indistinguishable on purpose (SA:357)."""


# The decision definer's DETAIL for each way a decision can conflict (T21, Plan R ruling 3); the API answers each
# under its own `ErrorCode`. Any other conflict (a state or version mismatch) carries no code.
DECISION_CONFLICTS: Final = frozenset({"ALREADY_DECIDED", "STALE_REVISION", "STALE_HASH", "EXPIRED"})


class VersionConflict(PersistenceError):
    """A stale state, version or hash: the caller's view of the run is out of date. `code` is one of
    `DECISION_CONFLICTS` when the function's DETAIL names it (T21's decision rules), otherwise None."""

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class HandleRejected(PersistenceError):
    """The invocation handle is unknown, expired, revoked, or bound to another server, workload or tool."""


class AuthorityViolation(PersistenceError):
    """A session that holds EXECUTE through membership is not on the function's caller list (SA:389); a plain wrong
    role never gets this far (42501 from the ACL). A deployment error, never a user error."""


class HashMismatch(PersistenceError):
    """The bytes or the hash presented are not the ones recorded."""


class Refused(PersistenceError):
    """A gate said no; `code` is the function's DETAIL (SLOT_OCCUPIED, NOT_REVIEWER, ...), safe to map to HTTP."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


OC_CODES: dict[str, type[Exception]] = {
    "OC001": AuthorityViolation,
    "OC002": NotFound,
    "OC003": VersionConflict,
    "OC004": IllegalTransition,
    "OC005": Refused,
    "OC006": EventRuleViolation,
    "OC007": HashMismatch,
    "OC008": HandleRejected,
}


def translate(exc: psycopg.Error) -> Exception | None:
    """The typed exception for a class-OC error, or None (the caller re-raises anything else)."""
    cls = OC_CODES.get(exc.sqlstate or "")
    if cls is None:
        return None
    detail = exc.diag.message_detail or ""
    if cls is Refused:
        return Refused(detail or "REFUSED")
    if cls is HandleRejected:
        return HandleRejected("invocation handle rejected")  # one message for every refusal (SA:357)
    message = f"{exc.diag.message_primary}: {detail}" if detail else str(exc.diag.message_primary)
    if cls is VersionConflict:
        return VersionConflict(message, code=detail if detail in DECISION_CONFLICTS else None)
    return cls(message)


async def _call(conn: Conn, query: str, params: tuple[object, ...]) -> DictRow | None:
    """Run one function call and translate its refusal; the first row or None."""
    try:
        cur = await conn.execute(query, params)
        return await cur.fetchone()
    except psycopg.Error as exc:
        mapped = translate(exc)
        if mapped is None:
            raise
        raise mapped from exc


async def _call_all(conn: Conn, query: str, params: tuple[object, ...]) -> list[DictRow]:
    """Like `_call` for a set-returning function: every row, refusals translated."""
    try:
        cur = await conn.execute(query, params)
        return await cur.fetchall()
    except psycopg.Error as exc:
        mapped = translate(exc)
        if mapped is None:
            raise
        raise mapped from exc


async def connect(pg: Postgres) -> Conn:
    """One autocommit connection per process (Plan D ruling 24): a bare statement is its own transaction and
    `async with conn.transaction()` a real BEGIN/COMMIT, never a savepoint inside a transaction a SELECT left open."""
    return await psycopg.AsyncConnection.connect(pg.conninfo(), row_factory=dict_row, autocommit=True)


async def set_tenant(conn: Conn, tenant_id: UUID) -> None:
    """Transaction-local (`is_local = true`): gone at COMMIT or ROLLBACK, so the next unit starts tenant-less.

    Raises PersistenceError outside a transaction: on an autocommit connection the setting would last one statement
    and the unit's reads would silently see nothing.
    """
    if conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE:
        raise PersistenceError("set_tenant needs a transaction")
    await conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))


class Session:
    """One connection, one unit of work at a time: the lock keeps concurrent requests from interleaving on the
    connection; the transaction makes the unit atomic. Never enter `unit()` while holding it (the lock is not
    re-entrant); callers pass the `conn` a unit yields instead. TODO(T30): a pool (Plan H ruling 25)."""

    def __init__(self, conn: Conn) -> None:
        self.conn = conn
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def unit(self, tenant_id: UUID | None = None) -> AsyncIterator[Conn]:
        """A transaction; with a tenant, RLS admits that tenant's rows for the unit's duration and no longer."""
        async with self._lock, self.conn.transaction():
            if tenant_id is not None:
                await set_tenant(self.conn, tenant_id)
            yield self.conn

    async def ping(self) -> None:
        """Readiness: one autocommit statement, no transaction left open, no tenant table touched."""
        async with self._lock:
            await self.conn.execute("SELECT 1")


async def assert_clock_profile(conn: Conn, profile: Profile) -> None:
    """Every service, not only the bootstrap, refuses to run outside the test profile when app.test_clock exists
    (SA:528, T09 review note 5); any role may call to_regclass."""
    cur = await conn.execute("SELECT to_regclass('app.test_clock') IS NOT NULL AS present")
    row = await cur.fetchone()
    if row is not None and row["present"] and profile is not Profile.TEST:
        raise PersistenceError(f"app.test_clock exists; the {profile.value} profile refuses to start")


async def assert_relation(conn: Conn, name: str) -> None:
    """Refuse to start when a relation a later revision adds is absent (`to_regclass` works for any role)."""
    cur = await conn.execute("SELECT to_regclass(%s) IS NULL AS missing", (name,))
    row = await cur.fetchone()
    if row is not None and row["missing"]:
        raise PersistenceError(f"{name} is missing; run scripts/skeleton.py migrate for this profile")


# Revision 0009 (T15): `_resolve_handle` binds the handle's job to its run and refuses a finished one. Both MCP servers
# resolve handles through it, so each refuses to start without it, as the other services do without their revision's
# relation (Plan J ruling 18). It lives here because the two servers never import each other (ADR-0001). A later
# revision that re-creates `_resolve_handle` must keep this text or change it here in the same commit; a unit test
# checks the newest body carries it.
HANDLE_BINDING: Final = ("app._resolve_handle(text, text, text)", "j.run_id = v_ctx.run_id AND j.done_at IS NULL")
# Revision 0010 (T47): the write-path definers take the token's azp and `request_abort` exists; mcp-write calls them
# with the new signatures, so it refuses to start without them (Plan K ruling 25). The same rule as above: a later
# revision that re-creates `request_abort` keeps this text or changes it here in the same commit.
WRITE_PATH: Final = ("app.request_abort(text, text, uuid)", "ABORT_NOT_DUE")
# Revision 0011 (T17): mcp-read answers `search_procedures` from the governed corpus through `search_procedures_scoped`,
# so it refuses to start without it (Plan L rulings 21 and 24). The same rule: a later revision that re-creates the
# function keeps this text or changes it here in the same commit (revisions 0012 and 0013 keep it: the lexical
# ranking is unchanged).
GOVERNED_CORPUS: Final = (
    "app.search_procedures_scoped(text, text, text, public.vector, text, integer, text)",
    "ts_rank_cd(c.search, v_query)",
)
# Revision 0012 (T16): `asset_scope` exists, and `search_procedures_scoped` returns the instant it decided permission
# at. mcp-read calls both with these shapes, so it refuses to start without them (Plan M ruling 3). The same rule: a
# later revision that re-creates either function keeps its text or changes it here in the same commit.
ASSET_SCOPE: Final = ("app.asset_scope(text, text)", "as_of := app.current_time()")
SEARCH_INSTANT: Final = (
    "app.search_procedures_scoped(text, text, text, public.vector, text, integer, text)",
    "retrieved_at := v_now",
)
# Revision 0013 (T18): `search_procedures_scoped` ranks by cosine similarity over `app.embeddings` in vector mode.
# mcp-read sends `mode='vector'` with a query embedding, so it refuses to start without it (Plan N ruling 1). The same
# rule: a later revision that re-creates the function keeps this text or changes it here in the same commit.
VECTOR_SEARCH: Final = (
    "app.search_procedures_scoped(text, text, text, public.vector, text, integer, text)",
    "e.embedding OPERATOR(public.<=>) p_query_embedding",
)
# Revision 0016 (T21): the freeze and the grant apply the asset guard and return what a committed refusal decided, the
# read path defers a stale sync, and `expire_proposal` exists. The worker, mcp-write, mcp-read and the sweeper call
# them in these shapes, so each refuses to start without them (Plan R ruling 16); the api checks `app.feedback`. The
# same rule: a later revision that re-creates one keeps its text or changes it here in the same commit.
FREEZE_GUARD: Final = ("app.freeze_proposal(uuid, uuid, bytea, timestamptz)", "app._asset_guard(")
GRANT_GUARD: Final = ("app.grant_execution(text, text, uuid)", "app._asset_guard(")
READ_FRESHNESS: Final = ("app.asset_scope(text, text)", "DETAIL = 'MEMBERSHIP_STALE'")
PROPOSAL_EXPIRY: Final = ("app.expire_proposal(uuid)", "app._expire(")


async def assert_function_text(conn: Conn, signature: str, marker: str) -> None:
    """Refuse to start when a function's stored body lacks the text a later revision put there: a revision that only
    re-creates a function adds no relation for `assert_relation` to find (`pg_proc` is readable by any role)."""
    cur = await conn.execute(
        "SELECT coalesce(strpos(p.prosrc, %s) > 0, false) AS present FROM pg_proc p WHERE p.oid = to_regprocedure(%s)",
        (marker, signature),
    )
    row = await cur.fetchone()
    if row is None or not row["present"]:
        raise PersistenceError(f"{signature} predates this service; run scripts/skeleton.py migrate for this profile")


async def tenants(conn: Conn) -> list[UUID]:
    """Every tenant id (no RLS on tenants, SA:523): the worker's claim loop and the sweeper iterate these."""
    cur = await conn.execute("SELECT tenant_id FROM app.tenants ORDER BY tenant_id")
    return [UUID(str(r["tenant_id"])) for r in await cur.fetchall()]


async def run_row(conn: Conn, run_id: UUID, *, lock: bool = False) -> DictRow:
    """The run row under the caller's tenant unit; a foreign or absent run is NotFound (RLS hides it)."""
    suffix = " FOR UPDATE" if lock else ""
    cur = await conn.execute(f"SELECT * FROM app.runs WHERE run_id = %s{suffix}", (run_id,))
    row = await cur.fetchone()
    if row is None:
        raise NotFound("run not found")
    return row


async def resolve_identity(conn: Conn, *, issuer: str, subject: UUID) -> list[tuple[UUID, str]]:
    """(tenant_id, role) for every active membership of the subject (Plan E ruling 4); needs no tenant unit."""
    rows = await _call_all(conn, "SELECT * FROM app.resolve_identity(%s, %s)", (issuer, subject))
    return [(UUID(str(r["tenant_id"])), str(r["role"])) for r in rows]


async def create_run(
    conn: Conn,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    message_id: UUID,
    requester: UUID,
    intent: Intent,
    asset_id: str,
    start_at: datetime,
    end_at: datetime,
    supersedes_run_id: UUID | None = None,
) -> tuple[UUID, int]:
    """∅ → QUEUED inside the function (SA:450): run, directory, history, the investigate job and run.accepted."""
    request = {
        "message_id": str(message_id),
        "requester": str(requester),
        "asset_id": asset_id,
        "start_at": start_at.isoformat(),
        "end_at": end_at.isoformat(),
    }
    row = await _call(
        conn,
        "SELECT * FROM app.create_run(%s, %s, %s, %s, %s)",
        (tenant_id, conversation_id, Jsonb(request), intent.value, supersedes_run_id),
    )
    if row is None:
        raise PersistenceError("create_run returned nothing")
    return UUID(str(row["run_id"])), int(row["state_version"])


async def transition_run(
    conn: Conn,
    *,
    run_id: UUID,
    src: RunState,
    dst: RunState,
    reason: Reason | None = None,
    expected_version: int | None = None,
    detail: dict[str, Any] | None = None,
) -> int:
    """The worker's pre-grant transitions (SA:451); a refusal is logged here too (R082's "logged" half)."""
    try:
        row = await _call(
            conn,
            "SELECT app.transition_run(%s, %s, %s, %s, %s, %s) AS version",
            (run_id, src.value, dst.value, reason.value if reason else None, expected_version, Jsonb(detail or {})),
        )
    except (IllegalTransition, Refused) as exc:
        log.warning(
            "transition refused: run=%s %s -> %s performer=transition_run: %s", run_id, src.value, dst.value, exc
        )
        raise
    if row is None:
        raise PersistenceError("transition_run returned nothing")
    return int(row["version"])


@dataclass(frozen=True)
class Appended:
    """What append_event wrote: the id, the per-run sequence and the stamped instant."""

    event_id: UUID
    sequence: int
    occurred_at: datetime


async def append_event(
    conn: Conn,
    *,
    run_id: UUID,
    type: EventType,
    payload: dict[str, Any],
    source: EventSource = EventSource.APPLICATION,
) -> Appended:
    """A tool.*, explanation.* or other non-reserved event (SA:452); the function assigns the sequence."""
    row = await _call(
        conn, "SELECT * FROM app.append_event(%s, %s, %s, %s)", (run_id, type.value, Jsonb(payload), source.value)
    )
    if row is None:
        raise PersistenceError("append_event returned nothing")
    return Appended(UUID(str(row["event_id"])), int(row["sequence"]), row["occurred_at"])


async def revoke_handles(conn: Conn, run_id: UUID, fence: int) -> int:
    """Revoke the run's live handles minted under `fence` or an older one (BS:364, Plan H ruling 8): a newer owner's
    handles survive, and a stale fence is never refused (revoking only removes authority). Returns the count."""
    row = await _call(conn, "SELECT app.revoke_handles(%s, %s) AS n", (run_id, fence))
    return 0 if row is None else int(row["n"])


@dataclass(frozen=True)
class Unknown:
    """What mark_unknown returned: the run's state and the fence it moved the lease to."""

    state: RunState
    fence: int


async def mark_unknown(conn: Conn, run_id: UUID, fence: int) -> Unknown:
    """EXECUTING → OUTCOME_UNKNOWN under the caller's lease (SA:467, Plan H ruling 9): the lease row FOR UPDATE, a stale
    fence or a lapsed lease refused (VersionConflict), the fence bumped to `fence + 1`, the old fence's handles revoked
    and a recover job queued; a run already OUTCOME_UNKNOWN only gets the bump. The caller hands the returned fence to
    its Lease (ruling 10)."""
    row = await _call(conn, "SELECT * FROM app.mark_unknown(%s, %s)", (run_id, fence))
    if row is None:
        raise PersistenceError("mark_unknown returned nothing")
    return Unknown(RunState(str(row["run_state"])), int(row["new_fence"]))


@dataclass(frozen=True)
class Frozen:
    """What freeze_proposal or create_manual_proposal committed: AWAITING_APPROVAL with the proposal's id, or
    BLOCKED_REVIEW with the asset guard's reason and no proposal (T21, AM-13); the revision, the run's new
    state_version and, for a manual proposal, the blocking run (the caller's tenant's, ruling 10)."""

    proposal_id: UUID | None
    revision: int
    state: RunState
    reason: Reason | None
    state_version: int
    blocking_run_id: UUID | None = None


def _frozen(row: DictRow) -> Frozen:
    blocking = row.get("blocking_run_id")
    return Frozen(
        None if row["proposal_id"] is None else UUID(str(row["proposal_id"])),
        int(row["revision"]),
        RunState(str(row["state"])),
        None if row["reason"] is None else Reason(str(row["reason"])),
        int(row["state_version"]),
        None if blocking is None else UUID(str(blocking)),
    )


async def freeze_proposal(
    conn: Conn, *, run_id: UUID, draft_id: UUID, payload_canonical: bytes, expires_at: datetime
) -> Frozen:
    """The frozen bytes are hashed inside and compared with the validated draft's hash (SA:453); since T21 the
    function also applies the asset guard, whose refusal commits BLOCKED_REVIEW and freezes nothing."""
    row = await _call(
        conn, "SELECT * FROM app.freeze_proposal(%s, %s, %s, %s)", (run_id, draft_id, payload_canonical, expires_at)
    )
    if row is None:
        raise PersistenceError("freeze_proposal returned nothing")
    return _frozen(row)


@dataclass(frozen=True)
class Decided:
    """What record_decision returned: the run, its new state and state_version."""

    run_id: UUID
    state: RunState
    state_version: int


async def record_decision(
    conn: Conn,
    *,
    tenant_id: UUID,
    proposal_id: UUID,
    reviewer: UUID,
    expected_revision: int,
    expected_payload_sha256: str,
    decision: str,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> Decided:
    """First decision wins on the exact revision and hash by an independent current reviewer of an unexpired proposal
    (SA:454; T21: the revision checked under the lock too, erratum 131).

    Raises:
        Refused: NOT_REVIEWER or SELF_REVIEW (the API's unrecorded 403).
        VersionConflict: `code` ALREADY_DECIDED, STALE_REVISION, STALE_HASH or EXPIRED.
    """
    row = await _call(
        conn,
        "SELECT * FROM app.record_decision(%s, %s, %s, %s, %s, %s, %s, %s)",
        (
            tenant_id,
            proposal_id,
            reviewer,
            expected_revision,
            expected_payload_sha256,
            decision,
            reason,
            idempotency_key,
        ),
    )
    if row is None:
        raise PersistenceError("record_decision returned nothing")
    return Decided(UUID(str(row["run_id"])), RunState(str(row["state"])), int(row["state_version"]))


@dataclass(frozen=True)
class Invocation:
    """A resolved handle: the run, job and tenant it binds, plus the run and attempt state at resolution."""

    run_id: UUID
    job_id: UUID
    job_type: JobType
    tenant_id: UUID
    conversation_id: UUID
    run_state: RunState
    attempt_state: str | None


def allowed_tool(job_type: JobType, run_state: RunState, attempt_state: AttemptState | None, tool: Tool) -> None:
    """The AM-15 allowlist stays in Python (Plan E ruling 21, erratum 19): the tool must be one of the job type's, the
    run must be in one of the job type's states (Plan J ruling 6), and a write tool's latest attempt state must be one
    `jobs.ATTEMPT_STATES` admits for the job type (Plan K ruling 4); the function has already bound server, azp,
    expiry, fence and the handle's job. A run that moved on (a read handle once the run awaits approval, an execute
    handle once the run succeeded, a recover handle asking to redispatch a sent attempt) is refused like any other
    handle."""
    rule = JOB_RULES[job_type]
    if tool not in rule.allowed_tools:
        log.info("tool %s is not allowed for job type %s", tool.value, job_type.value)  # never the handle
        raise HandleRejected("invocation handle rejected")  # the one fixed message (SA:357)
    if run_state not in rule.run_states:
        log.info("job type %s does not run in state %s", job_type.value, run_state.value)  # never the handle
        raise HandleRejected("invocation handle rejected")
    attempts = ATTEMPT_STATES.get((job_type, tool))
    if attempts is not None and attempt_state not in attempts:
        shown = "none" if attempt_state is None else attempt_state.value
        log.info("tool %s is not allowed for job type %s with attempt %s", tool.value, job_type.value, shown)
        raise HandleRejected("invocation handle rejected")


def handle_hash(handle: str) -> str:
    """What the table stores and what `_resolve_handle` computes server-side (same bytes, same digest)."""
    return sha256_hex(handle.encode("utf-8"))


async def resolve_invocation(conn: Conn, *, handle: str, azp: str, tool: Tool) -> Invocation:
    """The handle's run, tenant and job type for the calling server (SA:459); the handle never reaches a log."""
    row = await _call(conn, "SELECT * FROM app.resolve_invocation(%s, %s)", (handle, azp))
    if row is None:
        raise HandleRejected("invocation handle rejected")
    job_type = JobType(str(row["job_type"]))
    run_state = RunState(str(row["run_state"]))
    attempt_state = None if row["attempt_state"] is None else AttemptState(str(row["attempt_state"]))
    allowed_tool(job_type, run_state, attempt_state, tool)
    return Invocation(
        UUID(str(row["run_id"])),
        UUID(str(row["job_id"])),
        job_type,
        UUID(str(row["tenant_id"])),
        UUID(str(row["conversation_id"])),
        run_state,
        None if attempt_state is None else attempt_state.value,
    )


@dataclass(frozen=True)
class Procedure:
    """One permitted section, as `search_procedures_scoped` ranked it. `rank` is `ts_rank_cd`'s score in lexical mode
    and the cosine similarity in vector mode (T18): it orders the results of one query and means nothing across queries
    or methods (docs/retrieval.md, BS:417); no tool result carries it."""

    evidence_id: str
    document_id: str
    version: str
    section: str
    content_sha256: str
    excerpt: str
    effective_from: datetime
    rank: float


@dataclass(frozen=True)
class Procedures:
    """A search's answer: the tenant's latest ingested corpus version ("none" before any), the sections, best first,
    the database instant the definer decided permission at (`retrieved_at`, revision 0012) and whether any section
    was longer than the contract's excerpt bound and was cut (`truncated`, Plan M ruling 11)."""

    corpus_version: str
    results: tuple[Procedure, ...]
    retrieved_at: datetime
    truncated: bool = False


async def search_procedures(
    conn: Conn,
    *,
    handle: str,
    azp: str,
    query: str,
    asset_type: str | None,
    limit: int,
    mode: Literal["lexical", "vector"] = "lexical",
    embedding: Sequence[float] | None = None,
) -> Procedures:
    """Search over the handle's tenant's approved, effective chunks (SA:461): lexical (T17) without an embedding, or
    exact vector search (T18) with the query's `search_query:` embedding, which travels as pgvector's text form cast
    in SQL (erratum 109). The handle never reaches a log.

    Raises:
        HandleRejected: the handle does not resolve for mcp-read (the definer's `_resolve_handle`), or the run's
            requester no longer holds an active requester membership (R028, revision 0012).
        Refused: an argument outside the tool's bounds or the mode's rule (`BAD_ARGUMENT`), or, in vector mode, a
            permitted chunk without an embedding (`EMBEDDINGS_INCOMPLETE`, revision 0013).
    """
    literal = None if embedding is None else vector_literal(embedding)
    row = await _call(
        conn,
        "SELECT * FROM app.search_procedures_scoped(%s, %s, %s, %s::public.vector, %s, %s, %s)",
        (handle, azp, query, literal, asset_type, limit, mode),
    )
    if row is None:
        raise PersistenceError("search_procedures_scoped returned nothing")
    return _procedures(row)


async def search_procedures_api(conn: Conn, *, tenant_id: UUID, query: str, limit: int) -> Procedures:
    """The manual baseline's lexical search (BS:280; T21, erratum 135) over the API session's tenant: the ranking,
    filters and result rows of `search_procedures`, with no handle and no vector mode.

    Raises:
        Refused: BAD_ARGUMENT for a query or limit outside the bounds.
    """
    row = await _call(conn, "SELECT * FROM app.search_procedures_api(%s, %s, %s)", (tenant_id, query, limit))
    if row is None:
        raise PersistenceError("search_procedures_api returned nothing")
    return _procedures(row)


def _procedures(row: DictRow) -> Procedures:
    """A search function's row as `Procedures`."""
    hits = row["results"]
    results = tuple(
        Procedure(
            evidence_id=str(hit["evidence_id"]),
            document_id=str(hit["document_id"]),
            version=str(hit["version"]),
            section=str(hit["section"]),
            content_sha256=str(hit["content_sha256"]),
            excerpt=str(hit["excerpt"]),
            effective_from=datetime.fromisoformat(str(hit["effective_from"])),
            rank=float(hit["rank"]),
        )
        for hit in hits
    )
    # `excerpt_cut` says the definer cut a body at the contract's bound (ruling 11); it reaches no tool result, only
    # the envelope's `truncated`.
    cut = any(hit["excerpt_cut"] is True for hit in hits)
    return Procedures(str(row["corpus_version"]), results, row["retrieved_at"], cut)


@dataclass(frozen=True)
class AssetScope:
    """What `asset_scope` returns for a read handle: the run, its tenant, its asset and fixed `[start_at, end_at)`,
    and `as_of`, the database instant asset-sim answers at (Plan M rulings 2 and 4)."""

    run_id: UUID
    tenant_id: UUID
    asset_id: str
    start_at: datetime
    end_at: datetime
    as_of: datetime


async def asset_scope(conn: Conn, *, handle: str, azp: str) -> AssetScope:
    """The handle's run's asset and interval for forwarding to asset-sim (SA:460 with the caller's `azp`, erratum
    104). The handle never reaches a log.

    Raises:
        HandleRejected: the handle does not resolve for mcp-read, or the run's requester no longer holds an active
            requester membership in its tenant (R028); one refusal for every cause (SA:355).
    """
    row = await _call(conn, "SELECT * FROM app.asset_scope(%s, %s)", (handle, azp))
    if row is None:
        raise HandleRejected("invocation handle rejected")
    return AssetScope(
        run_id=UUID(str(row["run_id"])),
        tenant_id=UUID(str(row["tenant_id"])),
        asset_id=str(row["asset_id"]),
        start_at=row["start_at"],
        end_at=row["end_at"],
        as_of=row["as_of"],
    )


@dataclass(frozen=True)
class Blocked:
    """A grant the §13 gate refused with a committed BLOCKED_REVIEW (T21; AM-10 SA:140): expired, authority_revoked,
    stale_evidence, asset_action_unresolved or asset_incident_exists. Nothing was granted."""

    run_id: UUID
    proposal_id: UUID
    reason: Reason


@dataclass(frozen=True)
class Grant:
    """One run's execution grant with its latest attempt state (None before the first attempt row)."""

    action_id: UUID
    run_id: UUID
    proposal_id: UUID
    tenant_id: UUID
    conversation_id: UUID
    payload_sha256: str
    payload_canonical: bytes
    attempt_state: str | None
    detail: dict[str, Any] | None


def _grant(row: DictRow) -> Grant:
    """The Grant a `GRANT_COLUMNS` row describes."""
    return Grant(
        UUID(str(row["action_id"])),
        UUID(str(row["run_id"])),
        UUID(str(row["proposal_id"])),
        UUID(str(row["tenant_id"])),
        UUID(str(row["conversation_id"])),
        str(row["payload_sha256"]),
        bytes(row["payload_canonical"]),
        None if row["attempt_state"] is None else str(row["attempt_state"]),
        row["detail"],
    )


async def grant_execution(conn: Conn, *, handle: str, azp: str, proposal_id: UUID) -> Grant | Blocked:
    """The §13 gate inside the function; a replay returns the grant the run already has (SA:462).

    `azp` is the presented token's. This definer and the four after it (`lookup_action`, `mark_sent`, `request_abort`,
    `record_outcome`) pass it to `_resolve_handle`, which compares it with the one the handle was minted for, as
    `resolve_invocation` always did (revision 0010, Plan K ruling 12). Since T21 a refusal of the run's review
    (expiry, revoked authority, stale evidence, the asset guard) is returned as `Blocked`, so the caller's unit
    commits the BLOCKED_REVIEW it wrote; a binding refusal still raises `Refused` and commits nothing.
    """
    row = await _call(conn, "SELECT * FROM app.grant_execution(%s, %s, %s)", (handle, azp, proposal_id))
    if row is None:
        raise PersistenceError("grant_execution returned nothing")
    if row["refusal"] is not None:
        return Blocked(UUID(str(row["run_id"])), UUID(str(row["proposal_id"])), Reason(str(row["refusal"])))
    return _grant(row)


async def lookup_action(conn: Conn, *, handle: str, azp: str) -> Grant:
    """The run's grant for a same-key redispatch or a final read-back (SA:466); NotFound before any grant."""
    row = await _call(conn, "SELECT * FROM app.lookup_action(%s, %s)", (handle, azp))
    if row is None:
        raise NotFound("no grant for this run")
    return _grant(row)


async def mark_sent(conn: Conn, *, handle: str, azp: str, action_id: UUID) -> str:
    """`sent`, `already_sent`, `resolved`, `cancelled`, `expired` (the dispatch deadline passed), `abort_requested` or
    `not_redispatchable` (a recover job and a SENT attempt) (SA:463, revision 0010); committed by the caller before any
    I/O, and only `sent` and `already_sent` permit a POST.
    The handle binds the call to the run's lease fence (Plan H ruling 5): a moved fence or a lapsed lease is
    HandleRejected."""
    row = await _call(conn, "SELECT app.mark_sent(%s, %s, %s) AS outcome", (handle, azp, action_id))
    if row is None:
        raise PersistenceError("mark_sent returned nothing")  # a missing row must never read as "go ahead"
    return str(row["outcome"])


async def request_abort(conn: Conn, *, handle: str, azp: str, action_id: UUID) -> str:
    """The abort reason the function chose and recorded as `ABORT_REQUESTED` (`cancelled_before_send`, `expired` or
    `deadline`; a repeat returns the first reason), or `resolved` when the outcome already stands (SA:465, Plan K
    ruling 3). Refused `ABORT_NOT_DUE` while the run is not cancelled and the dispatch deadline has not passed. The
    caller commits it before POSTing the abort."""
    row = await _call(conn, "SELECT app.request_abort(%s, %s, %s) AS reason", (handle, azp, action_id))
    if row is None or row["reason"] is None:  # never POST an abort whose reason reads "None"
        raise PersistenceError("request_abort returned no reason")
    return str(row["reason"])


async def record_outcome(conn: Conn, *, handle: str, azp: str, action_id: UUID, outcome: ActionOutcome) -> ToolOutcome:
    """RESOLVED plus the implied transition and the destination-sourced event (SA:464); returns what stands. The handle
    binds the record to the run's lease fence (ruling 5); after SENT its refusal is the caller's UNKNOWN (ruling 6)."""
    if outcome.status is ToolOutcome.UNKNOWN:
        raise ValueError("UNKNOWN is recorded by the worker through mark_unknown, never as an outcome")
    row = await _call(
        conn,
        "SELECT app.record_outcome(%s, %s, %s, %s, %s) AS outcome",
        (handle, azp, action_id, outcome.status.value, Jsonb(outcome.model_dump(mode="json"))),
    )
    if row is None:
        raise PersistenceError("record_outcome returned nothing")
    return ToolOutcome(str(row["outcome"]))


async def insert_job(conn: Conn, *, job_type: JobType, run_id: UUID, **ids: UUID | int | str) -> UUID | None:
    """Insert a wake-up under the caller's tenant unit; a duplicate dedup key is a no-op and returns None."""
    key = dedup_key(job_type, run_id=run_id, **ids) if job_type is not JobType.EXECUTE else dedup_key(job_type, **ids)
    cur = await conn.execute("SELECT tenant_id FROM app.run_directory WHERE run_id = %s", (run_id,))
    found = await cur.fetchone()
    if found is None:
        raise NotFound("run not found")  # an unknown run must not read as "already queued"
    # ON CONFLICT (target) and RETURNING need SELECT (spike §3): this helper serves the tests and the superuser;
    # the API's `resume_input` insert goes through `insert_job_untargeted` (Plan G ruling 15).
    cur = await conn.execute(
        "INSERT INTO app.jobs (id, type, tenant_id, run_id, dedup_key) VALUES (%s, %s, %s, %s, %s)"
        " ON CONFLICT (dedup_key) DO NOTHING RETURNING id",
        (uuid4(), job_type.value, found["tenant_id"], run_id, key),
    )
    row = await cur.fetchone()
    return None if row is None else UUID(str(row["id"]))


async def insert_job_untargeted(conn: Conn, *, job_type: JobType, tenant_id: UUID, run_id: UUID, key: str) -> bool:
    """A wake-up inserted by a role that holds INSERT only on `jobs` (the api's `resume_input`, SA:419): a target-less
    ON CONFLICT DO NOTHING needs no SELECT, and the rowcount is the verdict, False for a dedup key already queued
    (Plan G spike §2; the same shape as the logout jti store)."""
    cur = await conn.execute(
        "INSERT INTO app.jobs (id, type, tenant_id, run_id, dedup_key, available_at)"
        " VALUES (%s, %s, %s, %s, %s, app.current_time()) ON CONFLICT DO NOTHING",
        (uuid4(), job_type.value, tenant_id, run_id, key),
    )
    return cur.rowcount == 1


async def current_time(conn: Conn) -> datetime:
    """The application clock (SA:157-158): `clock_timestamp()` plus the test offset when the testclock branch exists.

    Admission resolves "last N hours" against this, inside its unit, so a test that moves the clock moves the window
    the same way it moves the run's history and job rows (Plan G ruling 11; spike §7 measured the two clocks apart).
    """
    cur = await conn.execute("SELECT app.current_time() AS now")
    row = await cur.fetchone()
    if row is None:
        raise PersistenceError("app.current_time() returned nothing")
    now: datetime = row["now"]
    return now


async def latest_active_run(conn: Conn, conversation_id: UUID) -> DictRow | None:
    """The run holding the conversation's slot, under the caller's tenant unit (Plan G ruling 9: read, not locked)."""
    cur = await conn.execute(
        "SELECT run_id, state, state_version FROM app.runs WHERE conversation_id = %s AND slot_held"
        " ORDER BY created_at DESC LIMIT 1",
        (conversation_id,),
    )
    return await cur.fetchone()


async def latest_run(conn: Conn, conversation_id: UUID) -> DictRow | None:
    """The conversation's newest run of any state, the one a status question describes (ruling 14)."""
    cur = await conn.execute(
        "SELECT run_id, state, state_version FROM app.runs WHERE conversation_id = %s"
        " ORDER BY created_at DESC, run_id DESC LIMIT 1",
        (conversation_id,),
    )
    return await cur.fetchone()


async def latest_event(conn: Conn, run_id: UUID) -> DictRow | None:
    """A run's newest event by its gap-free sequence (`type`, `occurred_at`)."""
    cur = await conn.execute(
        "SELECT type, occurred_at FROM app.events WHERE run_id = %s ORDER BY sequence DESC LIMIT 1", (run_id,)
    )
    return await cur.fetchone()


async def queued_count(conn: Conn) -> int:
    """QUEUED runs of the unit's tenant: RLS scopes the count (spike §8), which is why the bound is per tenant."""
    cur = await conn.execute("SELECT count(*) AS n FROM app.runs WHERE state = 'QUEUED'")
    row = await cur.fetchone()
    return 0 if row is None else int(row["n"])


async def queued_runs_total(conn: Conn) -> int:
    """QUEUED runs of every tenant through `app.queued_runs_total()` (api only, Plan H ruling 13): one number."""
    row = await _call(conn, "SELECT app.queued_runs_total() AS n", ())
    return 0 if row is None else int(row["n"])


@dataclass(frozen=True)
class Claimed:
    """A claimed job and the run lease its claim took in the same transaction (Plan H ruling 3)."""

    job: DictRow
    lease: Lease


@dataclass(frozen=True)
class Deferred:
    """A job whose run lease was busy: moved behind the lease, not claimed (ruling 3)."""

    job_id: UUID


class _Held(Exception):
    """Raised inside the acquisition savepoint to roll it back when the lease is live under another claim."""


class _Locked(Exception):
    """Raised inside the acquisition savepoint to roll it back when NOWAIT met a row another transaction holds."""


_CREATE_LEASE = (
    "INSERT INTO app.run_lease (run_id, owner, lease_until, fence) VALUES (%s, '', '-infinity', 0)"
    " ON CONFLICT (run_id) DO NOTHING"
)
_TAKE_LEASE = (
    "UPDATE app.run_lease SET owner = %s, fence = fence + 1,"
    " lease_until = app.current_time() + make_interval(secs => %s) WHERE run_id = %s RETURNING fence"
)


async def _lock_row(conn: Conn, lock: str, run_id: UUID, *, wait: bool) -> psycopg.AsyncCursor[DictRow]:
    """One of the acquisition's lock statements: with NOWAIT, a row another transaction holds is a busy lease
    (`_Locked`, ruling 3); with `wait=True` the 55P03 of a wait past `lock_timeout` propagates (review round 2, N2:
    both lock statements go through here, the one after the first-row INSERT included)."""
    try:
        return await conn.execute(lock, (run_id,))
    except psycopg.errors.LockNotAvailable:
        if wait:
            raise  # a long lock wait, which the stress test counts, never a busy lease
        raise _Locked from None  # NOWAIT met a held row: busy (ruling 3)


async def acquire_lease(
    conn: Conn,
    *,
    run_id: UUID,
    owner: str,
    lease_seconds: int,
    wait: bool = False,
    clock: Callable[[], float] = time.monotonic,
) -> Lease | Busy:
    """Take the run's lease inside the caller's transaction (AM-12 SA:173-174, Plan H rulings 2 and 3).

    In a savepoint, so a busy lease rolls back alone and the caller's claim survives: the lease row FOR UPDATE NOWAIT
    (plain FOR UPDATE with `wait=True`, which only the interleaving and stress tests use; there a lock wait past the
    connection's `lock_timeout` raises 55P03 instead of looking like a busy lease, review round 1 I3), free when
    `lease_until <= app.current_time()` compared after the lock, then `fence + 1`, the new owner and a fresh
    `lease_until`. The row is
    locked before anything is inserted, because an `INSERT … ON CONFLICT` waits for an in-progress update of an
    existing row (a renewal, a release) and NOWAIT exists to avoid waits; it is created released (fence 0, so the
    first real fence is 1) only when absent, and a concurrent first insert of the same run is the one wait left
    (erratum 46).

    Returns:
        The Lease, whose local deadline counts from the monotonic instant before the first statement (ruling 18);
        `Busy(locked=True)` when NOWAIT met a row another transaction holds, `Busy(locked=False)` when the lease is
        live.

    Raises:
        psycopg.errors.LockNotAvailable: a wait (`wait=True`, or the first-row INSERT racing another first insert)
            outlasted the connection's `lock_timeout`.
    """
    started = clock()
    lock = LOCK_FOR_UPDATE if wait else LOCK_FOR_UPDATE_NOWAIT
    taken: DictRow | None = None
    try:
        async with conn.transaction():
            cur = await _lock_row(conn, lock, run_id, wait=wait)
            row = await cur.fetchone()
            if row is None:
                await conn.execute(_CREATE_LEASE, (run_id,))
                cur = await _lock_row(conn, lock, run_id, wait=wait)
                row = await cur.fetchone()
                if row is None:
                    raise PersistenceError("the run's lease row is missing after its insert")
            if row["live"]:
                raise _Held
            cur = await conn.execute(_TAKE_LEASE, (owner, lease_seconds, run_id))
            taken = await cur.fetchone()
    except _Held:
        return Busy(locked=False)
    except _Locked:
        return Busy(locked=True)
    if taken is None:
        raise PersistenceError("the lease update returned nothing")
    return Lease(
        run_id=run_id, owner=owner, fence=int(taken["fence"]), lease_seconds=lease_seconds, started=started, clock=clock
    )


async def pick_job(conn: Conn, *, tenant_ids: Sequence[UUID]) -> DictRow | None:
    """The oldest available job of the first tenant that has one, row-locked with SKIP LOCKED (BUILD_SPEC §11) until
    the caller's transaction claims or defers it.

    jobs is under tenant_isolation for the worker (only the sweeper has sweeper_all), so the pick runs once per tenant
    with the tenant set (Plan E ruling 18); `set_tenant` refuses outside a transaction, and on return the
    transaction's tenant is the picked job's (or the last one tried).
    """
    for tenant_id in tenant_ids:
        await set_tenant(conn, tenant_id)
        cur = await conn.execute(
            "SELECT * FROM app.jobs WHERE done_at IS NULL AND claimed_at IS NULL"
            " AND available_at <= app.current_time() ORDER BY available_at, id FOR UPDATE SKIP LOCKED LIMIT 1"
        )
        row = await cur.fetchone()
        if row is not None:
            return row
    return None


async def claim_next(
    conn: Conn,
    *,
    worker_name: str,
    tenant_ids: Sequence[UUID],
    lease_seconds: int,
    clock: Callable[[], float] = time.monotonic,
) -> Claimed | Deferred | None:
    """Claim the next job together with its run's lease, in one transaction (Plan H ruling 3).

    Claim and lease commit together, so a claimed run job always has a live lease taken at the same commit: no crash
    window lies between them, and "claimed, not done, lease not live" can only mean a dead or lost owner (the
    sweeper's reclaim, ruling 11). A job whose lease is busy is moved behind it and left unclaimed: to the live
    lease's `lease_until`, or one second on when the lease row was locked; jobs are wake-ups (SA:173), so whoever
    claims it later finds the run in the state the lease holder left. The moved job is not available again in the
    same poll, so the caller simply tries again. Polling is the v1 wake mechanism (erratum 64): a job is due through
    its `available_at`, and the lease holder's release makes the run's deferred jobs due at once (`pull_forward`).
    """
    async with conn.transaction():
        job = await pick_job(conn, tenant_ids=tenant_ids)
        if job is None:
            return None
        if job["run_id"] is None:
            # Maintenance jobs carry no tenant and RLS hides them from the worker; one here is a policy fault.
            raise PersistenceError("the worker picked a job without a run")
        got = await acquire_lease(
            conn, run_id=job["run_id"], owner=worker_name, lease_seconds=lease_seconds, clock=clock
        )
        if isinstance(got, Busy):
            if got.locked:
                await conn.execute(
                    "UPDATE app.jobs SET available_at = app.current_time() + interval '1 second' WHERE id = %s",
                    (job["id"],),
                )
            else:
                await conn.execute(
                    "UPDATE app.jobs SET available_at = coalesce((SELECT l.lease_until FROM app.run_lease l"
                    " WHERE l.run_id = %s AND l.lease_until > app.current_time()),"
                    " app.current_time() + interval '1 second') WHERE id = %s",
                    (job["run_id"], job["id"]),
                )
            return Deferred(UUID(str(job["id"])))
        cur = await conn.execute(
            "UPDATE app.jobs SET claimed_by = %s, claimed_at = app.current_time(), attempts = attempts + 1"
            " WHERE id = %s RETURNING *",
            (worker_name, job["id"]),
        )
        claimed = await cur.fetchone()
        if claimed is None:
            raise PersistenceError("the picked job vanished before its claim")
        return Claimed(claimed, got)


async def fenced(conn: Conn, lease: Lease) -> None:
    """The first statement of every worker unit that writes for a run (AM-12 SA:176-184, Plan H ruling 5).

    The lease row FOR SHARE, then owner, fence and expiry compared after the lock: a new owner's acquisition (FOR
    UPDATE) waits for this transaction, so nothing this unit writes can land after a newer fence. A mismatch marks the
    lease lost and raises LeaseLost, and the unit rolls back. `set_tenant` may come first: `set_config` takes no
    lock. The local deadline is checked before the statement (ruling 18).
    """
    lease.check()
    cur = await conn.execute(LOCK_FOR_SHARE, (lease.run_id,))
    row = await cur.fetchone()
    if row is None or row["owner"] != lease.owner or row["fence"] != lease.fence or not row["live"]:
        lease.mark_lost("the fence moved or the lease expired")
        raise LeaseLost("run lease lost")


async def release_lease(conn: Conn, lease: Lease, *, job: dict[str, Any], requeue_seconds: int | None = None) -> None:
    """The job's final unit (Plan H ruling 28): the local deadline checked first, then the lease row FOR UPDATE (this
    unit writes it, SA:191) with owner, fence and liveness compared after the lock, the handles minted under this
    fence revoked, the job finished (or re-queued after `requeue_seconds`) and the lease released (`lease_until =
    '-infinity'`; owner and fence stay, so the run's next acquisition takes fence + 1). Together, so a crash leaves
    either the claimed job with its lease or neither.

    Liveness counts here like in every other unit. A lease that lapsed while the job's last call was in flight may
    have made that call fail: mcp-write refuses the handle of a lapsed lease before SENT and answers INVALID_HANDLE.
    Closing the job on that answer would leave an approved run with no grant and no job (final review, I1). Refused
    here, the loss hands the job back (`handlers.abandon`) and the run's next owner runs it again.

    Raises:
        LeaseLost: the local deadline passed, another owner holds the lease, or it lapsed on the database clock;
            nothing is written.
    """
    lease.check()
    async with conn.transaction():
        await set_tenant(conn, job["tenant_id"])  # jobs is under RLS; set_config takes no lock
        cur = await conn.execute(LOCK_FOR_UPDATE, (lease.run_id,))
        row = await cur.fetchone()
        if row is None or row["owner"] != lease.owner or row["fence"] != lease.fence or not row["live"]:
            lease.mark_lost("another owner holds the lease, or it lapsed")
            raise LeaseLost("run lease lost")
        await revoke_handles(conn, lease.run_id, lease.fence)
        if requeue_seconds is None:
            await finish_job(conn, job["id"])
        else:
            await requeue_job(conn, job["id"], requeue_seconds)
        # The lease is free from this commit on, so a job of the run that a claim deferred behind it need not wait
        # for the old lease_until (Plan I ruling 10; the abandon path does not: its lease lapses on its own).
        await pull_forward(conn, lease.run_id, except_job=job["id"])
        await conn.execute("UPDATE app.run_lease SET lease_until = '-infinity' WHERE run_id = %s", (lease.run_id,))
    lease.mark_lost(RELEASED)


async def unclaim_job(conn: Conn, job_id: UUID, *, worker_name: str) -> None:
    """Hand a claimed job back, claimable now (ruling 19: jobs are wake-ups), unless another worker claimed it since."""
    await conn.execute(
        "UPDATE app.jobs SET claimed_by = NULL, claimed_at = NULL, available_at = app.current_time()"
        " WHERE id = %s AND claimed_by = %s AND done_at IS NULL",
        (job_id, worker_name),
    )


async def pull_forward(conn: Conn, run_id: UUID, *, except_job: UUID) -> int:
    """Make due now the run's jobs that a claim deferred behind the lease being released (Plan I ruling 10).

    Called in the release's unit before the lease row's `lease_until` is reset: a job waiting for an instant no later
    than that `lease_until` was moved behind this lease (`claim_next` defers to the live lease's end, or one second
    on); a job delayed beyond it on purpose (a re-queue backoff, T22's recover cadence) keeps its time (round 1, M2).
    Rows are picked with SKIP LOCKED, so a row another worker's claim holds is never waited on and this UPDATE stays
    outside the lock order. Such a claim, if it found the lease live before this release took the lease row, commits
    its own deferral to the old lease end, so that one job can still wait up to it: bounded, and rare. Returns how
    many jobs were made due.
    """
    cur = await conn.execute(
        "UPDATE app.jobs SET available_at = app.current_time() WHERE id IN (SELECT id FROM app.jobs"
        " WHERE run_id = %s AND id <> %s AND done_at IS NULL AND claimed_at IS NULL"
        " AND available_at > app.current_time()"
        " AND available_at <= (SELECT l.lease_until FROM app.run_lease l WHERE l.run_id = %s)"
        " FOR UPDATE SKIP LOCKED)",
        (run_id, except_job, run_id),
    )
    return cur.rowcount


async def take_model_permit(conn: Conn, *, holder: str, run_id: UUID, ttl_seconds: int) -> int | None:
    """One free model permit slot for `ttl_seconds` (Plan H ruling 12), or None while every slot is held. SKIP LOCKED
    never waits, and a slot whose TTL passed counts as free on the application clock, so nobody needs to reclaim it."""
    cur = await conn.execute(
        "UPDATE app.model_permit SET holder = %s, run_id = %s,"
        " leased_until = app.current_time() + make_interval(secs => %s)"
        " WHERE slot = (SELECT slot FROM app.model_permit WHERE leased_until <= app.current_time()"
        " ORDER BY slot FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING slot",
        (holder, run_id, ttl_seconds),
    )
    row = await cur.fetchone()
    return None if row is None else int(row["slot"])


async def release_model_permit(conn: Conn, *, slot: int, holder: str) -> None:
    """Give the permit back, unless its TTL passed and another holder took it meanwhile."""
    await conn.execute(
        "UPDATE app.model_permit SET holder = NULL, run_id = NULL, leased_until = '-infinity'"
        " WHERE slot = %s AND holder = %s",
        (slot, holder),
    )


async def insert_run_manifest(conn: Conn, *, tenant_id: UUID, manifest: RunManifest) -> None:
    """The run's manifest (AM-80; revision 0014), as the worker under its own grant (INSERT, SELECT). The caller's
    unit sets the tenant and holds the fence; a second manifest for the run fails on the primary key, so one run is
    recorded once."""
    await conn.execute(
        "INSERT INTO app.run_manifests (run_id, tenant_id, model_route, model_digest, prompt_version, corpus_version,"
        " retrieval_mode) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            manifest.run_id,
            tenant_id,
            manifest.model_route.value,
            manifest.model_digest,
            manifest.prompt_version,
            manifest.corpus_version,
            manifest.retrieval_mode,
        ),
    )


async def run_manifest_exists(conn: Conn, run_id: UUID) -> bool:
    """True when the run has its manifest (T20: a run that retrieves again after a clarification keeps the one it
    has, Plan Q ruling 13 and erratum 125; whether a revision records its own is T21's)."""
    cur = await conn.execute("SELECT 1 FROM app.run_manifests WHERE run_id = %s", (run_id,))
    return await cur.fetchone() is not None


async def run_revision(conn: Conn, run_id: UUID) -> int:
    """The run's current revision: 1 plus its `proposal.revised` events, the rule revision 0016's `_run_revision`
    applies (T21, Plan R ruling 1). Read under the caller's tenant unit."""
    cur = await conn.execute(
        "SELECT 1 + count(*) AS revision FROM app.events WHERE run_id = %s AND type = %s",
        (run_id, EventType.PROPOSAL_REVISED.value),
    )
    row = await cur.fetchone()
    return 1 if row is None else int(row["revision"])


async def lock_asset(conn: Conn, tenant_id: UUID, asset_id: str) -> None:
    """The asset guard's advisory lock (SA:189) in the caller's transaction, the key `_asset_lock` takes: the worker's
    freeze unit takes it before its fence, so its order is the published one (advisory:asset, run_lease, runs).
    No privilege is needed for an advisory lock."""
    await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s || ':' || %s, 0))", (str(tenant_id), asset_id))


async def record_asset_observation(conn: Conn, run_id: UUID, observed_at: datetime) -> None:
    """`runs.asset_observed_at` := the instant mcp-read's status answer observed the asset (R116; T21 ruling 9), under
    the worker's column grant; the grant refuses an observation older than five minutes."""
    await conn.execute("UPDATE app.runs SET asset_observed_at = %s WHERE run_id = %s", (observed_at, run_id))


async def record_workflow_version(conn: Conn, run_id: UUID, version: str) -> str:
    """`runs.workflow_version` := `version` unless the run has one already (BS:342; T21 ruling 18: the first claim pins
    it); returns the run's version, which the freeze compares with the payload's."""
    cur = await conn.execute(
        "UPDATE app.runs SET workflow_version = coalesce(workflow_version, %s) WHERE run_id = %s"
        " RETURNING workflow_version",
        (version, run_id),
    )
    row = await cur.fetchone()
    if row is None:
        raise NotFound("run not found")
    return str(row["workflow_version"])


async def clear_checkpoint_id(conn: Conn, run_id: UUID) -> None:
    """`runs.checkpoint_id` := NULL for a run whose graph run ended in DRAFTING because the model could not draft: the
    state a manual proposal waits for (T21, erratum 134)."""
    await conn.execute("UPDATE app.runs SET checkpoint_id = NULL WHERE run_id = %s", (run_id,))


@dataclass(frozen=True)
class Revised:
    """What create_revision committed: the run's new state_version and its new revision."""

    run_id: UUID
    state_version: int
    revision: int


async def create_revision(
    conn: Conn,
    *,
    tenant_id: UUID,
    run_id: UUID,
    expected_version: int,
    author: UUID,
    supersedes_run_id: UUID | None,
) -> Revised:
    """AWAITING_APPROVAL, APPROVED or BLOCKED_REVIEW → QUEUED with a new revision (SA:455; T21 rulings 1, 2, 4, 6).

    Raises:
        NotFound: no such run in the tenant, or a supersedes_run_id that names no run of the tenant and asset.
        VersionConflict: the run is in another state or at another version.
        Refused: NOT_REQUESTER, GRANT_EXISTS, AUTHOR_LIMIT or SLOT_OCCUPIED.
    """
    row = await _call(
        conn,
        "SELECT * FROM app.create_revision(%s, %s, %s, %s, %s)",
        (tenant_id, run_id, expected_version, author, supersedes_run_id),
    )
    if row is None:
        raise PersistenceError("create_revision returned nothing")
    return Revised(UUID(str(row["run_id"])), int(row["state_version"]), int(row["revision"]))


@dataclass(frozen=True)
class Cancelled:
    """What request_cancel answered (SA:458): CANCELLED before a grant; after one, the flag set and the attempt."""

    run_id: UUID
    state: RunState
    state_version: int
    grant_exists: bool
    attempt_state: AttemptState | None


async def request_cancel(conn: Conn, *, tenant_id: UUID, run_id: UUID, expected_version: int, actor: UUID) -> Cancelled:
    """Cancel before the grant, or set `cancel_requested` after it (SA:458; T21 ruling 12).

    Raises:
        NotFound: no such run in the tenant.
        VersionConflict: before a grant, the run is terminal or at another version.
        Refused: NOT_CANCELLER (neither the run's requester nor a reviewer of the tenant).
    """
    row = await _call(
        conn, "SELECT * FROM app.request_cancel(%s, %s, %s, %s)", (tenant_id, run_id, expected_version, actor)
    )
    if row is None:
        raise PersistenceError("request_cancel returned nothing")
    attempt = row["attempt_state"]
    return Cancelled(
        UUID(str(row["run_id"])),
        RunState(str(row["state"])),
        int(row["state_version"]),
        bool(row["grant_exists"]),
        None if attempt is None else AttemptState(str(attempt)),
    )


async def expire_proposal(conn: Conn, run_id: UUID) -> RunState:
    """BLOCKED_REVIEW(expired) when the run's active proposal is past its expiry (SA:457); otherwise nothing. The run's
    state afterwards."""
    row = await _call(conn, "SELECT app.expire_proposal(%s) AS state", (run_id,))
    if row is None:
        raise PersistenceError("expire_proposal returned nothing")
    return RunState(str(row["state"]))


@dataclass(frozen=True)
class ManualFacts:
    """What a manual proposal's payload takes from the run (T21 ruling 7): its revision, workflow version, supersession,
    asset and interval, the expiry on the application clock, and the snapshots of the cited permitted sections."""

    revision: int
    workflow_version: str
    supersedes_run_id: UUID | None
    asset_id: str
    start_at: datetime
    end_at: datetime
    expires_at: datetime
    snapshots: list[dict[str, str]]


async def prepare_manual_proposal(
    conn: Conn, *, tenant_id: UUID, run_id: UUID, author: UUID, evidence_ids: Sequence[str]
) -> ManualFacts:
    """The first of a manual proposal's two calls, in the caller's unit: the asset guard's lock and the run's lock
    are held until it commits (T21 ruling 7).

    Raises:
        NotFound: no such run, or a cited section that is not a permitted section of the tenant (note 4).
        VersionConflict: the run does not wait for a manual proposal.
        Refused: NOT_AUTHOR or AUTHOR_LIMIT.
    """
    row = await _call(
        conn,
        "SELECT * FROM app.prepare_manual_proposal(%s, %s, %s, %s)",
        (tenant_id, run_id, author, list(evidence_ids)),
    )
    if row is None:
        raise PersistenceError("prepare_manual_proposal returned nothing")
    supersedes = row["supersedes_run_id"]
    return ManualFacts(
        int(row["revision"]),
        str(row["workflow_version"]),
        None if supersedes is None else UUID(str(supersedes)),
        str(row["asset_id"]),
        row["start_at"],
        row["end_at"],
        row["expires_at"],
        [dict(s) for s in row["snapshots"]],
    )


async def create_manual_proposal(
    conn: Conn, *, tenant_id: UUID, run_id: UUID, payload_canonical: bytes, author: UUID
) -> Frozen:
    """The person's frozen proposal through the freeze rules and the asset guard (SA:456; T21 ruling 7).

    Raises:
        NotFound: no such run, another asset than the run's, or snapshots that are not the permitted sections.
        VersionConflict: the run does not wait for a manual proposal, or another revision.
        Refused: NOT_AUTHOR, AUTHOR_LIMIT or a payload field the run fixes (PAYLOAD_RUN_MISMATCH, INTERVAL,
            SUPERSEDES_MISMATCH, WORKFLOW_VERSION, EXPIRY).
    """
    row = await _call(
        conn,
        "SELECT * FROM app.create_manual_proposal(%s, %s, %s, %s)",
        (tenant_id, run_id, payload_canonical, author),
    )
    if row is None:
        raise PersistenceError("create_manual_proposal returned nothing")
    return _frozen(row)


@dataclass(frozen=True)
class GraphFacts:
    """The authoritative run facts the worker graph routes on (SA:377) and the checkpoint it last stored (SA:211)."""

    state: RunState
    intent: Intent
    decision_present: bool
    attempt_state: AttemptState | None
    checkpoint_id: str | None


async def graph_facts(conn: Conn, run_id: UUID) -> GraphFacts:
    """The run's state, intent, whether its active proposal has a decision, its latest action attempt state and its
    stored checkpoint id, read without a lock under the caller's tenant unit (the worker's SELECT grants, AM-20.2). The
    attempt state is the newest grant's latest row, so a run that ever holds a second grant reads the second's attempt.

    Raises:
        NotFound: no such run for the unit's tenant.
    """
    cur = await conn.execute(
        "SELECT r.state, r.intent, r.checkpoint_id,"
        " EXISTS (SELECT 1 FROM app.decisions d WHERE d.proposal_id = r.active_proposal_id) AS decided,"
        " (SELECT s.state FROM app.action_attempt_state s JOIN app.execution_grant g ON g.action_id = s.action_id"
        "  WHERE g.run_id = r.run_id"
        "  ORDER BY g.granted_at DESC, s.attempt_no DESC, s.seq DESC LIMIT 1) AS attempt_state"
        " FROM app.runs r WHERE r.run_id = %s",
        (run_id,),
    )
    row = await cur.fetchone()
    if row is None:
        raise NotFound("run not found")
    attempt = row["attempt_state"]
    return GraphFacts(
        RunState(row["state"]),
        Intent(row["intent"]),
        bool(row["decided"]),
        None if attempt is None else AttemptState(attempt),
        row["checkpoint_id"],
    )


async def store_checkpoint_id(conn: Conn, run_id: UUID, checkpoint_id: str) -> None:
    """`runs.checkpoint_id` := the checkpoint LangGraph confirmed (SA:211), under the worker's column grant (AM-20.2).
    The caller's unit sets the tenant and opens with `fenced`, so only the current lease holder can move it.

    Raises:
        NotFound: no such run for the unit's tenant.
    """
    cur = await conn.execute("UPDATE app.runs SET checkpoint_id = %s WHERE run_id = %s", (checkpoint_id, run_id))
    if cur.rowcount != 1:
        raise NotFound("run not found")


async def run_events(conn: Conn, run_id: UUID, event_type: EventType) -> list[tuple[UUID, dict[str, Any]]]:
    """The run's events of one type as (event_id, payload), in sequence order, under the caller's tenant unit."""
    cur = await conn.execute(
        "SELECT event_id, payload FROM app.events WHERE run_id = %s AND type = %s ORDER BY sequence",
        (run_id, event_type.value),
    )
    return [(UUID(str(row["event_id"])), dict(row["payload"])) for row in await cur.fetchall()]


async def message_text(conn: Conn, message_id: UUID) -> str:
    """One stored message's text under the caller's tenant unit (the worker reads, never writes, messages).

    Raises:
        NotFound: no such message for the unit's tenant.
    """
    cur = await conn.execute("SELECT text FROM app.messages WHERE message_id = %s", (message_id,))
    row = await cur.fetchone()
    if row is None:
        raise NotFound("message not found")
    return str(row["text"])


async def finish_job(conn: Conn, job_id: UUID) -> None:
    """Mark a claimed job done."""
    await conn.execute("UPDATE app.jobs SET done_at = app.current_time() WHERE id = %s", (job_id,))


async def requeue_job(conn: Conn, job_id: UUID, delay_seconds: int) -> None:
    """Release a claimed job and make it claimable again after `delay_seconds`. TODO(T22): bounded retries."""
    await conn.execute(
        "UPDATE app.jobs SET claimed_by = NULL, claimed_at = NULL,"
        " available_at = app.current_time() + make_interval(secs => %s) WHERE id = %s",
        (delay_seconds, job_id),
    )


async def insert_maintenance_job(conn: Conn, job_type: JobType, minute_bucket: str) -> UUID | None:
    """A tenant-less sweeper job keyed by `<type>:<minute bucket>` (SA:504); None when that minute already exists.

    `jobs_tenant_iff_run_check` allows a NULL tenant exactly for these, and the sweeper's `sweeper_all` policy
    admits the row without a tenant setting. ON CONFLICT with a target and RETURNING both need SELECT, which the
    sweeper holds on `jobs` (unlike the api role on `logout_jti`, where the insert is target-less). `available_at`
    is set from the application clock: the column default is wall-clock `now()`, which a test-clock offset would put
    in the future of `claim_maintenance_job`'s comparison (ruling 24).
    """
    if JOB_RULES[job_type].run_states:
        raise ValueError(f"{job_type.value} is not a maintenance job")
    key = dedup_key(job_type, minute_bucket=minute_bucket)  # validates the bucket's shape
    cur = await conn.execute(
        "INSERT INTO app.jobs (id, type, dedup_key, available_at) VALUES (%s, %s, %s, app.current_time())"
        " ON CONFLICT (dedup_key) DO NOTHING RETURNING id",
        (uuid4(), job_type.value, key),
    )
    row = await cur.fetchone()
    return None if row is None else UUID(str(row["id"]))


async def claim_maintenance_job(
    conn: Conn, *, job_type: JobType, worker_name: str, job_id: UUID | None = None
) -> DictRow | None:
    """Claim the oldest unclaimed sweeper job of one type, or exactly `job_id` when given (SKIP LOCKED: a second
    sweeper never runs the same one)."""
    cur = await conn.execute(
        "UPDATE app.jobs SET claimed_by = %s, claimed_at = app.current_time(), attempts = attempts + 1"
        " WHERE id = (SELECT id FROM app.jobs WHERE type = %s AND tenant_id IS NULL AND done_at IS NULL"
        "             AND claimed_at IS NULL AND available_at <= app.current_time()"
        "             AND (%s::uuid IS NULL OR id = %s)"
        "             ORDER BY available_at, id FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *",
        (worker_name, job_type.value, job_id, job_id),
    )
    return await cur.fetchone()


async def mint_handle(
    conn: Conn, *, run_id: UUID, job_id: UUID, server: Server, azp: str, fence: int, ttl_seconds: int = 60
) -> str:
    """A 256-bit capability bound to one job, one server and the lease fence it was minted under (BUILD_SPEC §9,
    BS:360); only its hash is stored. It is minted only under a live lease at exactly that fence (Plan H ruling 5)
    and expires after `ttl_seconds`. BS:558's other bound, the current lease, is enforced where the handle is used:
    `app._resolve_handle` refuses it once its fence is not the lease's or the lease has lapsed. Capping `expires_at`
    at mint time would freeze the lease end the handle saw, so a handle would die under a lease the heartbeat has
    since renewed (T13 controller ruling, Task 4).

    The caller's unit must already hold the run's lease row FOR SHARE (`fenced`, or the claim's FOR UPDATE): the
    INSERT's own read of run_lease takes no lock, so only that lock keeps the fence from moving before the commit.

    Raises:
        LeaseLost: the run has no live lease at `fence`; nothing is written.
    """
    handle = secrets.token_urlsafe(32)
    cur = await conn.execute(
        "INSERT INTO app.invocation_context (handle_sha256, run_id, job_id, server, azp, fence, expires_at)"
        " SELECT %s, l.run_id, %s, %s, %s, l.fence, app.current_time() + make_interval(secs => %s)"
        " FROM app.run_lease l WHERE l.run_id = %s AND l.fence = %s AND l.lease_until > app.current_time()",
        (handle_hash(handle), job_id, server.value, azp, ttl_seconds, run_id, fence),
    )
    if cur.rowcount != 1:
        raise LeaseLost("no live lease at this fence")
    return handle

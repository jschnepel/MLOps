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
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import DictRow, dict_row
from psycopg.types.json import Jsonb

from ops_core.canonical import sha256_hex
from ops_core.jobs import JOB_RULES, JobType, Server, Tool, dedup_key
from ops_core.lease import LOCK_FOR_SHARE, LOCK_FOR_UPDATE, LOCK_FOR_UPDATE_NOWAIT, RELEASED, Busy, Lease, LeaseLost
from ops_core.outcomes import ActionOutcome, EventRuleViolation, EventSource, EventType, ToolOutcome
from ops_core.settings import Postgres, Profile
from ops_core.states import IllegalTransition, Intent, Reason, RunState

Conn = psycopg.AsyncConnection[DictRow]
log = logging.getLogger("ops_core.persistence")


class PersistenceError(Exception):
    """Base class; messages are safe for logs and HTTP bodies (no handle, token or secret)."""


class NotFound(PersistenceError):
    """The row is absent or belongs to another tenant; the two cases are indistinguishable on purpose (SA:357)."""


class VersionConflict(PersistenceError):
    """A stale state, version or hash: the caller's view of the run is out of date."""


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
    return cls(f"{exc.diag.message_primary}: {detail}" if detail else str(exc.diag.message_primary))


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
    """What freeze_proposal returned: the proposal's id and revision, and the run's new state_version."""

    proposal_id: UUID
    revision: int
    state_version: int


async def freeze_proposal(
    conn: Conn, *, run_id: UUID, draft_id: UUID, payload_canonical: bytes, expires_at: datetime
) -> Frozen:
    """The frozen bytes are hashed inside and compared with the validated draft's hash (SA:453)."""
    row = await _call(
        conn, "SELECT * FROM app.freeze_proposal(%s, %s, %s, %s)", (run_id, draft_id, payload_canonical, expires_at)
    )
    if row is None:
        raise PersistenceError("freeze_proposal returned nothing")
    return Frozen(UUID(str(row["proposal_id"])), int(row["revision"]), int(row["state_version"]))


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
    expected_payload_sha256: str,
    decision: str,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> Decided:
    """First decision wins on the exact hash by an independent current reviewer (SA:454)."""
    row = await _call(
        conn,
        "SELECT * FROM app.record_decision(%s, %s, %s, %s, %s, %s, %s)",
        (tenant_id, proposal_id, reviewer, expected_payload_sha256, decision, reason, idempotency_key),
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


def allowed_tool(job_type: JobType, tool: Tool) -> None:
    """The AM-15 allowlist stays in Python (ruling 21); the function has already bound server, azp and expiry."""
    if tool not in JOB_RULES[job_type].allowed_tools:
        log.info("tool %s is not allowed for job type %s", tool.value, job_type.value)  # never the handle
        raise HandleRejected("invocation handle rejected")  # the one fixed message (SA:357)


def handle_hash(handle: str) -> str:
    """What the table stores and what `_resolve_handle` computes server-side (same bytes, same digest)."""
    return sha256_hex(handle.encode("utf-8"))


async def resolve_invocation(conn: Conn, *, handle: str, azp: str, tool: Tool) -> Invocation:
    """The handle's run, tenant and job type for the calling server (SA:459); the handle never reaches a log."""
    row = await _call(conn, "SELECT * FROM app.resolve_invocation(%s, %s)", (handle, azp))
    if row is None:
        raise HandleRejected("invocation handle rejected")
    job_type = JobType(str(row["job_type"]))
    allowed_tool(job_type, tool)
    return Invocation(
        UUID(str(row["run_id"])),
        UUID(str(row["job_id"])),
        job_type,
        UUID(str(row["tenant_id"])),
        UUID(str(row["conversation_id"])),
        RunState(str(row["run_state"])),
        None if row["attempt_state"] is None else str(row["attempt_state"]),
    )


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


async def grant_execution(conn: Conn, *, handle: str, proposal_id: UUID) -> Grant:
    """The §13 gate inside the function; a replay returns the grant the run already has (SA:462)."""
    row = await _call(conn, "SELECT * FROM app.grant_execution(%s, %s)", (handle, proposal_id))
    if row is None:
        raise PersistenceError("grant_execution returned nothing")
    return _grant(row)


async def lookup_action(conn: Conn, *, handle: str) -> Grant:
    """The run's grant for a same-key redispatch or a final read-back (SA:466); NotFound before any grant."""
    row = await _call(conn, "SELECT * FROM app.lookup_action(%s)", (handle,))
    if row is None:
        raise NotFound("no grant for this run")
    return _grant(row)


async def mark_sent(conn: Conn, *, handle: str, action_id: UUID) -> str:
    """`sent`, `already_sent`, `resolved` or `cancelled` (SA:463); committed by the caller before any I/O. The handle
    binds the call to the run's lease fence (Plan H ruling 5): a moved fence or a lapsed lease is HandleRejected."""
    row = await _call(conn, "SELECT app.mark_sent(%s, %s) AS outcome", (handle, action_id))
    if row is None:
        raise PersistenceError("mark_sent returned nothing")  # a missing row must never read as "go ahead"
    return str(row["outcome"])


async def record_outcome(conn: Conn, *, handle: str, action_id: UUID, outcome: ActionOutcome) -> ToolOutcome:
    """RESOLVED plus the implied transition and the destination-sourced event (SA:464); returns what stands. The handle
    binds the record to the run's lease fence (ruling 5); after SENT its refusal is the caller's UNKNOWN (ruling 6)."""
    if outcome.status is ToolOutcome.UNKNOWN:
        raise ValueError("UNKNOWN is recorded by the worker through mark_unknown, never as an outcome")
    row = await _call(
        conn,
        "SELECT app.record_outcome(%s, %s, %s, %s) AS outcome",
        (handle, action_id, outcome.status.value, Jsonb(outcome.model_dump(mode="json"))),
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
    same poll, so the caller simply tries again. TODO(T14): wake-ups instead of polling.
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
    """The job's final unit (Plan H ruling 28): the lease row FOR UPDATE (this unit writes it, SA:191), owner and fence
    compared, the handles minted under this fence revoked, the job finished (or re-queued after `requeue_seconds`)
    and the lease released (`lease_until = '-infinity'`; owner and fence stay, so the run's next acquisition takes
    fence + 1). Together, so a crash leaves either the claimed job with its lease or neither.

    Raises:
        LeaseLost: another owner holds the lease now; nothing is written.
    """
    async with conn.transaction():
        await set_tenant(conn, job["tenant_id"])  # jobs is under RLS; set_config takes no lock
        cur = await conn.execute(LOCK_FOR_UPDATE, (lease.run_id,))
        row = await cur.fetchone()
        if row is None or row["owner"] != lease.owner or row["fence"] != lease.fence:
            lease.mark_lost("another owner holds the lease")
            raise LeaseLost("run lease lost")
        await revoke_handles(conn, lease.run_id, lease.fence)
        if requeue_seconds is None:
            await finish_job(conn, job["id"])
        else:
            await requeue_job(conn, job["id"], requeue_seconds)
        await conn.execute("UPDATE app.run_lease SET lease_until = '-infinity' WHERE run_id = %s", (lease.run_id,))
    lease.mark_lost(RELEASED)


async def unclaim_job(conn: Conn, job_id: UUID, *, worker_name: str) -> None:
    """Hand a claimed job back, claimable now (ruling 19: jobs are wake-ups), unless another worker claimed it since."""
    await conn.execute(
        "UPDATE app.jobs SET claimed_by = NULL, claimed_at = NULL, available_at = app.current_time()"
        " WHERE id = %s AND claimed_by = %s AND done_at IS NULL",
        (job_id, worker_name),
    )


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

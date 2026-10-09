"""The one door to the application database: a thin Python wrapper per AM-20.3 definer function, plus the few plain
statements a runtime role may run under its own grants (T09; SPEC_AMENDMENTS AM-20.2/20.3).

Every state transition, decision, grant, attempt step and event happens inside a SECURITY DEFINER function
(migrations/app/versions/0003 and 0004); nothing here writes runs.state or an audit table. A function refuses with
SQLSTATE class OC, which `translate` turns into the typed exceptions services already catch. Any unit of work that
touches a tenant table opens as `Session.unit(tenant_id)`, which sets the transaction-local tenant first: RLS admits
nothing otherwise, and a reused connection's setting is '' between units (spike §1, §2). Pools arrive with T13.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import AsyncIterator, Sequence
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
    re-entrant); callers pass the `conn` a unit yields instead. TODO(T13): a pool."""

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


async def revoke_handles(conn: Conn, run_id: UUID) -> int:
    """Every live handle of the run is revoked (BS:364); the fence argument is T13's."""
    row = await _call(conn, "SELECT app.revoke_handles(%s, 1) AS n", (run_id,))
    return 0 if row is None else int(row["n"])


async def mark_unknown(conn: Conn, run_id: UUID) -> RunState:
    """EXECUTING → OUTCOME_UNKNOWN with handles revoked and a recover job (SA:467); idempotent."""
    row = await _call(conn, "SELECT app.mark_unknown(%s, 1) AS state", (run_id,))
    if row is None:
        raise PersistenceError("mark_unknown returned nothing")
    return RunState(str(row["state"]))


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


async def mark_sent(conn: Conn, action_id: UUID) -> str:
    """`sent`, `already_sent`, `resolved` or `cancelled` (SA:463); committed by the caller before any I/O."""
    row = await _call(conn, "SELECT app.mark_sent(%s) AS outcome", (action_id,))
    if row is None:
        raise PersistenceError("mark_sent returned nothing")  # a missing row must never read as "go ahead"
    return str(row["outcome"])


async def record_outcome(conn: Conn, *, action_id: UUID, outcome: ActionOutcome) -> ToolOutcome:
    """RESOLVED plus the implied transition and the destination-sourced event (SA:464); returns what stands."""
    if outcome.status is ToolOutcome.UNKNOWN:
        raise ValueError("UNKNOWN is recorded by the worker through mark_unknown, never as an outcome")
    row = await _call(
        conn,
        "SELECT app.record_outcome(%s, %s, %s) AS outcome",
        (action_id, outcome.status.value, Jsonb(outcome.model_dump(mode="json"))),
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
    # the API's `resume_input` insert (T12) goes through a definer function or a target-less ON CONFLICT DO NOTHING.
    cur = await conn.execute(
        "INSERT INTO app.jobs (id, type, tenant_id, run_id, dedup_key) VALUES (%s, %s, %s, %s, %s)"
        " ON CONFLICT (dedup_key) DO NOTHING RETURNING id",
        (uuid4(), job_type.value, found["tenant_id"], run_id, key),
    )
    row = await cur.fetchone()
    return None if row is None else UUID(str(row["id"]))


async def claim_job(conn: Conn, *, worker_name: str, tenant_ids: Sequence[UUID]) -> DictRow | None:
    """Claim the oldest available job of the first tenant that has one (BUILD_SPEC §11: SKIP LOCKED).

    jobs is under tenant_isolation for the worker (only the sweeper has sweeper_all), so the claim runs once per
    tenant with the tenant set (Plan E ruling 18); the caller rotates the order. Runs inside a transaction so the
    settings last exactly as long as the claim; `set_tenant` refuses outside a transaction. On return the
    transaction's tenant stays set to the claimed job's tenant (or the last one tried). TODO(T13): lease + fence +
    wake-ups instead of polling.
    """
    for tenant_id in tenant_ids:
        await set_tenant(conn, tenant_id)
        cur = await conn.execute(
            "UPDATE app.jobs SET claimed_by = %s, claimed_at = app.current_time(), attempts = attempts + 1"
            " WHERE id = (SELECT id FROM app.jobs WHERE done_at IS NULL AND claimed_at IS NULL"
            "             AND available_at <= app.current_time()"
            "             ORDER BY available_at, id FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *",
            (worker_name,),
        )
        row = await cur.fetchone()
        if row is not None:
            return row
    return None


async def finish_job(conn: Conn, job_id: UUID) -> None:
    """Mark a claimed job done."""
    await conn.execute("UPDATE app.jobs SET done_at = app.current_time() WHERE id = %s", (job_id,))


async def requeue_job(conn: Conn, job_id: UUID, delay_seconds: int) -> None:
    """Release a claimed job and make it claimable again after `delay_seconds`. TODO(T13): bounded retries."""
    await conn.execute(
        "UPDATE app.jobs SET claimed_by = NULL, claimed_at = NULL,"
        " available_at = app.current_time() + make_interval(secs => %s) WHERE id = %s",
        (delay_seconds, job_id),
    )


async def mint_handle(
    conn: Conn, *, run_id: UUID, job_id: UUID, server: Server, azp: str, ttl_seconds: int = 60
) -> str:
    """A 256-bit capability bound to one job and one server (BUILD_SPEC §9); only its hash is stored (BS:360)."""
    handle = secrets.token_urlsafe(32)
    await conn.execute(
        "INSERT INTO app.invocation_context (handle_sha256, run_id, job_id, server, azp, expires_at)"
        " VALUES (%s, %s, %s, %s, %s, app.current_time() + make_interval(secs => %s))",
        (handle_hash(handle), run_id, job_id, server.value, azp, ttl_seconds),
    )
    return handle

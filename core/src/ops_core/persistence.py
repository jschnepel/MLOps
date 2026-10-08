"""The skeleton's one door to the application database (T08; every function names the AM-20.3 definer function that
replaces it in T09).

Every state change in every service goes through `transition()`, which calls `ops_core.states.require_transition`
before the plain UPDATE, so the transition table is enforced in exactly one place (R082 "one table, one function").
Events are built as `ops_core.outcomes.Event` before they are inserted, so AM-14's source and payload rules hold for
every producer. Plain INSERT/UPDATE as the single owner role is declared debt in SESSION_STATE.md.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import DictRow, dict_row
from psycopg.types.json import Jsonb

from ops_core.jobs import JOB_RULES, JobType, Server, Tool, dedup_key, server_for
from ops_core.outcomes import Event, EventSource, EventType, event_rules_ok
from ops_core.settings import Postgres
from ops_core.states import Intent, Performer, Reason, RunState, require_transition

Conn = psycopg.AsyncConnection[DictRow]


class PersistenceError(Exception):
    """Base class; messages are safe for logs and HTTP bodies (no handle, token or secret)."""


class NotFound(PersistenceError):
    pass


class VersionConflict(PersistenceError):
    pass


class HandleRejected(PersistenceError):
    pass


async def connect(pg: Postgres) -> Conn:
    """One autocommit connection per process (ruling 24).

    With autocommit off, a bare SELECT silently opens a transaction that every later `transaction()` block nests into as
    a savepoint, so nothing commits until the connection is closed (measured by the round-1 static critic). Autocommit
    makes a bare statement its own transaction and `async with conn.transaction()` a real BEGIN/COMMIT.
    """
    return await psycopg.AsyncConnection.connect(pg.conninfo(), row_factory=dict_row, autocommit=True)


class Session:
    """One connection, one unit of work at a time: the lock keeps concurrent requests from interleaving on the
    connection; the transaction makes the unit atomic. Never enter `unit()` while holding it (the lock is not
    re-entrant: a nested unit deadlocks); callers pass the `conn` a unit yields instead. TODO(T13): a pool."""

    def __init__(self, conn: Conn) -> None:
        self.conn = conn
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def unit(self) -> AsyncIterator[Conn]:
        async with self._lock, self.conn.transaction():
            yield self.conn

    async def read(self, query: str, params: tuple[object, ...]) -> DictRow | None:
        """A single autocommit SELECT (no transaction to leave open), serialised like a unit."""
        async with self._lock:
            cur = await self.conn.execute(query, params)
            return await cur.fetchone()


async def run_row(conn: Conn, run_id: UUID, *, lock: bool = False) -> DictRow:
    suffix = " FOR UPDATE" if lock else ""
    cur = await conn.execute(f"SELECT * FROM app.runs WHERE run_id = %s{suffix}", (run_id,))
    row = await cur.fetchone()
    if row is None:
        raise NotFound("run not found")
    return row


async def transition(
    conn: Conn,
    *,
    run_id: UUID,
    dst: RunState,
    performer: Performer,
    reason: Reason | None = None,
    expected_version: int | None = None,
) -> int:
    """Move a run one row along the transition table under the runs lock; returns the new state_version.

    The caller holds the unit of work (`Session.unit()`): the runs-row lock lasts only inside that transaction.
    TODO(T09): becomes the SQL `transition_run` / per-performer definer functions; callers keep this signature.
    """
    row = await run_row(conn, run_id, lock=True)
    if expected_version is not None and row["state_version"] != expected_version:
        raise VersionConflict("stale state_version")
    require_transition(RunState(row["state"]), dst, performer, reason)  # raises IllegalTransition, never UPDATEs
    version: int = row["state_version"] + 1
    await conn.execute(
        "UPDATE app.runs SET state = %s, state_version = %s, reason = %s, updated_at = now() WHERE run_id = %s",
        (dst.value, version, reason.value if reason else None, run_id),
    )
    await conn.execute(
        "INSERT INTO app.run_state_history (run_id, seq, from_state, to_state, performer, reason)"
        " VALUES (%s, %s, %s, %s, %s, %s)",
        (run_id, version, row["state"], dst.value, performer.value, reason.value if reason else None),
    )
    return version


async def create_run(
    conn: Conn,
    *,
    run_id: UUID,
    tenant_id: UUID,
    conversation_id: UUID,
    message_id: UUID,
    requester: UUID,
    intent: Intent,
    asset_id: str,
    start_at: datetime,
    end_at: datetime,
    supersedes_run_id: UUID | None = None,
) -> int:
    """∅ → QUEUED with its first history row and the `investigate` job (SA:450). TODO(T09): SQL `create_run`."""
    require_transition(None, RunState.QUEUED, Performer.CREATE_RUN)
    await conn.execute(
        "INSERT INTO app.runs (run_id, tenant_id, conversation_id, message_id, requester, intent, supersedes_run_id,"
        " asset_id, start_at, end_at, state, state_version)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)",
        (
            run_id,
            tenant_id,
            conversation_id,
            message_id,
            requester,
            intent.value,
            supersedes_run_id,
            asset_id,
            start_at,
            end_at,
            RunState.QUEUED.value,
        ),
    )
    await conn.execute(
        "INSERT INTO app.run_state_history (run_id, seq, from_state, to_state, performer) VALUES (%s, 1, NULL, %s, %s)",
        (run_id, RunState.QUEUED.value, Performer.CREATE_RUN.value),
    )
    await insert_job(conn, job_type=JobType.INVESTIGATE, run_id=run_id, revision=1)
    return 1


async def append_event(
    conn: Conn,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    run_id: UUID,
    type: EventType,
    source: EventSource,
    payload: dict[str, Any],
    occurred_at: datetime | None = None,
) -> Event:
    """Validate through `Event` (AM-14 rules) and insert with the next per-run sequence under the runs lock.

    The caller holds the unit of work (`Session.unit()`); the runs-row lock lives in that transaction.
    The runs row lock makes `sequence` gap-free and commit-ordered without T14's `next_event_seq` column.
    TODO(T14): `append_event` definer function with `next_event_seq`.
    """
    event_rules_ok(type, source, payload)  # raises EventRuleViolation (AM-14) before the model wraps it
    await conn.execute("SELECT run_id FROM app.runs WHERE run_id = %s FOR UPDATE", (run_id,))
    cur = await conn.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS next FROM app.events WHERE run_id = %s", (run_id,)
    )
    row = await cur.fetchone()
    if row is None:  # COALESCE always yields one row
        raise PersistenceError("event sequence could not be computed")
    sequence: int = row["next"]
    event = Event(
        event_id=uuid4(),
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        run_id=run_id,
        sequence=sequence,
        type=type,
        occurred_at=occurred_at or datetime.now(UTC).replace(microsecond=0),
        source=source,
        payload=payload,
    )
    await conn.execute(
        "INSERT INTO app.events (event_id, tenant_id, conversation_id, run_id, sequence, type, occurred_at, source,"
        " payload) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            event.event_id,
            event.tenant_id,
            event.conversation_id,
            event.run_id,
            event.sequence,
            event.type.value,
            event.occurred_at,
            event.source.value,
            Jsonb(event.payload),
        ),
    )
    return event


async def insert_job(conn: Conn, *, job_type: JobType, run_id: UUID, **ids: UUID | int | str) -> UUID | None:
    """Insert a wake-up; a duplicate dedup key is silently a no-op (AM-20.4) and returns None."""
    key = dedup_key(job_type, run_id=run_id, **ids) if job_type is not JobType.EXECUTE else dedup_key(job_type, **ids)
    cur = await conn.execute(
        "INSERT INTO app.jobs (id, type, run_id, dedup_key) VALUES (%s, %s, %s, %s)"
        " ON CONFLICT (dedup_key) DO NOTHING RETURNING id",
        (uuid4(), job_type.value, run_id, key),
    )
    row = await cur.fetchone()
    return None if row is None else UUID(str(row["id"]))


async def claim_job(conn: Conn, *, worker_name: str) -> DictRow | None:
    """Claim the oldest available job (BUILD_SPEC §11: SKIP LOCKED for queue consumers). TODO(T13): lease + fence."""
    cur = await conn.execute(
        "UPDATE app.jobs SET claimed_by = %s, claimed_at = now(), attempts = attempts + 1"
        " WHERE id = (SELECT id FROM app.jobs WHERE done_at IS NULL AND claimed_at IS NULL AND available_at <= now()"
        "             ORDER BY available_at, id FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *",
        (worker_name,),
    )
    return await cur.fetchone()


async def finish_job(conn: Conn, job_id: UUID) -> None:
    await conn.execute("UPDATE app.jobs SET done_at = now() WHERE id = %s", (job_id,))


async def requeue_job(conn: Conn, job_id: UUID, delay_seconds: int) -> None:
    """Release a claimed job and make it claimable again after `delay_seconds`. TODO(T13): bounded retries."""
    await conn.execute(
        "UPDATE app.jobs SET claimed_by = NULL, claimed_at = NULL, available_at = now() + make_interval(secs => %s)"
        " WHERE id = %s",
        (delay_seconds, job_id),
    )


async def mint_handle(
    conn: Conn, *, run_id: UUID, job_id: UUID, server: Server, azp: str, ttl_seconds: int = 60
) -> str:
    """A 256-bit capability lookup key bound to one job and one server (BUILD_SPEC §9).
    Stored raw: debt → T09/T15."""
    handle = secrets.token_urlsafe(32)
    await conn.execute(
        "INSERT INTO app.invocation_context (handle, run_id, job_id, server, azp, expires_at)"
        " VALUES (%s, %s, %s, %s, %s, %s)",
        (handle, run_id, job_id, server.value, azp, datetime.now(UTC) + timedelta(seconds=ttl_seconds)),
    )
    return handle


@dataclass(frozen=True)
class Invocation:
    run_id: UUID
    job_id: UUID
    job_type: JobType
    tenant_id: UUID
    conversation_id: UUID


def check_invocation(row: dict[str, Any], *, server: Server, azp: str, tool: Tool, now: datetime) -> Invocation:
    """The handle rules, database-free so they are unit-tested: expiry, revocation, server derived from the job type
    (SA:496: never the worker-written column alone), the caller's azp, and the job type's tool allowlist."""
    if row["revoked_at"] is not None or row["expires_at"] <= now:
        raise HandleRejected("invocation handle expired or revoked")
    job_type = JobType(row["job_type"])
    if server_for(job_type) is not server or row["server"] != server.value:
        raise HandleRejected("invocation handle is bound to the other server")
    if row["azp"] != azp:
        raise HandleRejected("invocation handle was issued to another workload")
    if tool not in JOB_RULES[job_type].allowed_tools:
        raise HandleRejected("tool is not allowed for this job type")
    return Invocation(row["run_id"], row["job_id"], job_type, row["tenant_id"], row["conversation_id"])


async def resolve_handle(conn: Conn, *, handle: str, server: Server, azp: str, tool: Tool) -> Invocation:
    """Look the handle up by equality (raw, debt → T09/T15 hash it) and apply `check_invocation`.
    TODO(T09/T15): SQL `resolve_invocation`."""
    cur = await conn.execute(
        "SELECT ic.handle, ic.run_id, ic.job_id, ic.server, ic.azp, ic.expires_at, ic.revoked_at, j.type AS job_type,"
        " r.tenant_id, r.conversation_id FROM app.invocation_context ic"
        " JOIN app.jobs j ON j.id = ic.job_id JOIN app.runs r ON r.run_id = ic.run_id WHERE ic.handle = %s",
        (handle,),
    )
    row = await cur.fetchone()
    if row is None:
        raise HandleRejected("unknown invocation handle")
    return check_invocation(dict(row), server=server, azp=azp, tool=tool, now=datetime.now(UTC))

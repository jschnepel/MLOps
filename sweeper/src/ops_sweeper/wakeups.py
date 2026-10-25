"""The wake-up sweep and the purge of finished maintenance rows (BS:340; Plan I rulings 6-8, 20, 26; errata 61-64).

A wake-up is a job committed with the event that needs it (SA:173, BS:340): the investigate job with the run, the
execute job with the approving decision. The worker consumes a job only in its final unit, after the handler
returned; a handler that returned without moving the run (or a crash between consumption and progress) leaves the run
waiting in the job's state with the job done. The sweep finds such runs, in the states a handler serves today
(QUEUED for `investigate`, APPROVED for `execute`; AWAITING_INPUT's wake-up is the API's `resume_input` job, erratum
62, and a run that job moved back to QUEUED is re-armed by the investigate pair, which resumes it from its stored
checkpoint (T20); OUTCOME_UNKNOWN and ESCALATED are T22's),
when the newest job of the type has been done for longer than the grace, and reopens that job: its dedup key is the
wake-up's identity, so the same row is re-armed (`done_at`, `claimed_by`, `claimed_at` cleared under `sweeper_all`),
never a new one inserted (erratum 62). A run whose cancellation was requested is never re-armed. A job claimed
`max_attempts` times is not re-armed again; the sweep logs it on every tick instead (operator visibility through
logs; metrics are T28's).

Since T21 a refused grant of a run's review (expiry, revoked authority, stale evidence, the asset guard) moves the run
to BLOCKED_REVIEW in the gate's own transaction (AM-10 SA:140; Plan R rulings 9 and 11), so the APPROVED pair re-arms
a lost decision wake-up (R023) and nothing it must not: a deferred grant re-queues its own job, and only the binding
refusals that leave a run APPROVED (a missing approval, a hash mismatch) are re-dispatched, at most until the job has
been claimed `max_attempts` times (erratum 63, resolved this way provisionally).

It is the sweeper's routine with direct grants, separate from the lease reclaim (erratum 63, extending erratum 49):
the reclaim hands back claimed jobs of dead leases, this reopens done jobs of stuck runs. It reads runs per tenant
(SA:520: `runs` has no sweeper policy) without a lock and re-arms each job in a unit of its own. The re-arm's UPDATE
repeats every condition of the scan on the row it takes, with the clock read there (round 1, I7): the job is still
done, done longer ago than the grace on `app.current_time()`, below the cap, still the newest job of its type for the
run (for an investigate job: the job of the run's current revision, Plan R round 1, M1), and the run still waits in
the job's state without a cancellation. The purge deletes finished maintenance rows
past their retention; a run's jobs are never deleted, because their dedup keys are what makes a wake-up happen once
(a restrictive policy enforces it, erratum 61).
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from ops_core import persistence
from ops_core.settings import WakeupSettings

from ops_sweeper.tenants import for_each_tenant, in_tenant

log = logging.getLogger("ops_sweeper.wakeups")

# (the run's state, the job type that moves it on): the pairs whose handler exists today (ruling 7).
WAKEUPS = (("QUEUED", "investigate"), ("APPROVED", "execute"))
PAIRS = ", ".join(f"('{state}', '{job_type}')" for state, job_type in WAKEUPS)
STATES = ", ".join(f"'{state}'" for state, _ in WAKEUPS)


def job_type_case(pairs: Sequence[tuple[str, str]]) -> str:
    """The state -> job type map the lateral picks a run's job by, built from the same pairs as PAIRS and STATES.

    A hand-written CASE would yield NULL for a pair added to WAKEUPS alone, and the run would be silently dropped.
    """
    return "CASE r.state " + " ".join(f"WHEN '{state}' THEN '{job_type}'" for state, job_type in pairs) + " END"


# T21 (Plan R round 1, M1): a run's investigate wake-up is the job whose key names its current revision
# (`run_id:N`, SA:455). An older revision's job, which may finish after the current one, ends without a graph run, so
# re-arming it would leave the run QUEUED until the cap.
CURRENT_KEY = (
    "r.run_id::text || ':' || (1 + (SELECT count(*) FROM app.events e WHERE e.run_id = r.run_id"
    " AND e.type = 'proposal.revised'))::text"
)
# Each run's newest job of its state's type; an unfinished one sorts first (NULLS FIRST), so a run whose wake-up is
# still pending is never picked.
LOST = (
    "SELECT r.run_id, r.state, j.id AS job_id, j.type AS job_type, j.attempts FROM app.runs r"
    " JOIN LATERAL (SELECT jj.id, jj.type, jj.attempts, jj.done_at FROM app.jobs jj"
    " WHERE jj.run_id = r.run_id"
    f" AND jj.type = {job_type_case(WAKEUPS)}"
    f" AND (jj.type <> 'investigate' OR jj.dedup_key = {CURRENT_KEY})"
    " ORDER BY jj.done_at DESC NULLS FIRST, jj.created_at DESC LIMIT 1) j ON true"
    # Only waiting runs reach the lateral (round 1, M7), and never one whose cancellation was requested (I3).
    f" WHERE r.state IN ({STATES}) AND NOT r.cancel_requested AND (r.state, j.type) IN ({PAIRS})"
    " AND j.done_at IS NOT NULL AND j.done_at <= app.current_time() - make_interval(secs => %s)"
    " ORDER BY r.run_id"
)
# The scan's conditions again, on the row the UPDATE takes (I7): a job re-armed, claimed and finished again since
# the scan (a fresh done_at) or one a newer job of its type has replaced is left alone.
REARM = (
    "UPDATE app.jobs j SET done_at = NULL, claimed_by = NULL, claimed_at = NULL"
    " WHERE j.id = %s AND j.done_at IS NOT NULL AND j.attempts < %s"
    " AND j.done_at <= app.current_time() - make_interval(secs => %s)"
    " AND NOT EXISTS (SELECT 1 FROM app.jobs o WHERE o.run_id = j.run_id AND o.type = j.type AND o.id <> j.id"
    " AND j.type <> 'investigate' AND (o.done_at IS NULL OR o.done_at > j.done_at))"
    " AND EXISTS (SELECT 1 FROM app.runs r WHERE r.run_id = j.run_id AND r.state = %s AND NOT r.cancel_requested"
    f" AND (j.type <> 'investigate' OR j.dedup_key = {CURRENT_KEY}))"
)
PURGE = (
    "DELETE FROM app.jobs WHERE run_id IS NULL AND done_at IS NOT NULL"
    " AND done_at < app.current_time() - make_interval(hours => %s)"
)


@dataclass(frozen=True)
class Wakeup:
    """A lost wake-up the sweep found, and whether it re-armed it."""

    run_id: UUID
    job_id: UUID
    job_type: str
    attempts: int
    rearmed: bool


async def _lost(conn: persistence.Conn, *, chosen: WakeupSettings) -> list[dict[str, Any]]:
    cur = await conn.execute(LOST, (chosen.grace_seconds,))
    return [dict(row) for row in await cur.fetchall()]


async def _rearm(conn: persistence.Conn, *, row: dict[str, Any], chosen: WakeupSettings) -> bool:
    cur = await conn.execute(REARM, (row["job_id"], chosen.max_attempts, chosen.grace_seconds, row["state"]))
    return cur.rowcount == 1


async def sweep(
    conn: persistence.Conn, chosen: WakeupSettings, *, tenants: Sequence[UUID] | None = None
) -> list[Wakeup]:
    """Find every tenant's lost wake-ups and re-arm each one under its cap, each in its own unit."""
    found = await for_each_tenant(conn, functools.partial(_lost, chosen=chosen), tenants=tenants)
    out: list[Wakeup] = []
    for tenant, rows in found.items():
        for row in rows:
            attempts = int(row["attempts"])
            if attempts >= chosen.max_attempts:
                log.warning(
                    "wake-up not re-armed: run=%s job=%s type=%s claimed %d times (cap %d)",
                    row["run_id"],
                    row["job_id"],
                    row["job_type"],
                    attempts,
                    chosen.max_attempts,
                )
                rearmed = False
            else:
                rearmed = await in_tenant(conn, tenant, functools.partial(_rearm, row=row, chosen=chosen))
            out.append(Wakeup(row["run_id"], row["job_id"], str(row["job_type"]), attempts, rearmed))
    return out


async def purge_maintenance(conn: persistence.Conn, chosen: WakeupSettings) -> int:
    """Delete the finished maintenance rows (no run) older than the retention; returns how many (ruling 20)."""
    async with conn.transaction():
        cur = await conn.execute(PURGE, (chosen.maintenance_retention_hours,))
        return cur.rowcount

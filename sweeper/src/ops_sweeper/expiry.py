"""The scheduled proposal expiry (SA:138, SA:346, SA:457; T21, Plan R ruling 5; R092).

Every tick the sweeper finds, per tenant (SA:520: `runs` has no sweeper policy), the runs whose active proposal is
past its expiry while they wait for a reviewer or for their grant, and calls `expire_proposal` for each in a unit of
its own: the definer locks the run, compares `expires_at` with the application clock after the lock and moves the run
to BLOCKED_REVIEW(`expired`) with `review.blocked`, or does nothing when a decision or a revision got there first. So a
proposal expires without a live worker and without a reviewer's request (R092); the decision and the grant check the
same rule lazily. An APPROVED run expires before its grant (SA:140); a granted run is EXECUTING and never expires.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Sequence
from uuid import UUID

from ops_core import persistence
from ops_core.states import RunState

from ops_sweeper.tenants import for_each_tenant, in_tenant

log = logging.getLogger("ops_sweeper.expiry")

# The scan reads without a lock; the definer decides under its own (the scan is only a list of candidates).
DUE = (
    "SELECT r.run_id FROM app.runs r JOIN app.proposals p ON p.proposal_id = r.active_proposal_id"
    " WHERE r.state IN ('AWAITING_APPROVAL', 'APPROVED') AND p.expires_at < app.current_time() ORDER BY r.run_id"
)


async def _due(conn: persistence.Conn) -> list[UUID]:
    cur = await conn.execute(DUE)
    return [UUID(str(row["run_id"])) for row in await cur.fetchall()]


async def _expire(conn: persistence.Conn, *, run_id: UUID) -> RunState:
    return await persistence.expire_proposal(conn, run_id)


async def expire(conn: persistence.Conn, *, tenants: Sequence[UUID] | None = None) -> list[UUID]:
    """Expire every tenant's overdue proposals, one run per unit; the runs that moved to BLOCKED_REVIEW. A run whose
    unit fails (a lock timeout, an unexpected definer error) is logged and skipped, so one run never stops the others
    or the rest of the tick; its transaction rolled back, and the next tick finds it again (Task 5 review, M4)."""
    found = await for_each_tenant(conn, _due, tenants=tenants)
    expired: list[UUID] = []
    for tenant, runs in found.items():
        for run_id in runs:
            try:
                state = await in_tenant(conn, tenant, functools.partial(_expire, run_id=run_id))
            except Exception:
                log.exception("proposal expiry of run %s failed; the other runs go on", run_id)
                continue
            if state is RunState.BLOCKED_REVIEW:
                expired.append(run_id)
    return expired

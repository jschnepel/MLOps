"""Lease reclaim (AM-12; SA:471 as erratum 49 reads it; Plan H ruling 11): the sweeper's routine with its own direct
grants (`sweeper_all` on `jobs`, SELECT on `run_lease`), not a definer function, like `sync_memberships` (erratum 26).

A claim and its lease commit together (ruling 3), and a job's final unit finishes it and releases the lease together
(ruling 28), so a run job that is claimed, not done, and whose run lease is not live belongs to a worker that died or
lost its lease. Reclaim hands such jobs back (`claimed_by`, `claimed_at` cleared; `available_at` is already past), the
next poll claims them and takes the run's lease at the next fence, and whoever claims one re-reads the run (jobs are
wake-ups; an investigate job whose run it finds RETRIEVING or DRAFTING fails that run as interrupted, review round
3). Nothing else: no `recover` job (T22), no model permit work (an expired permit is free by the same comparison), no
lost wake-ups (T14).
"""

from __future__ import annotations

from uuid import UUID

from ops_core import persistence


async def reclaim(conn: persistence.Conn) -> list[UUID]:
    """Hand back every claimed, unfinished run job whose run lease is not live; the ids handed back.

    The lease is read without a lock (the sweeper takes none, erratum 49). A lease renewed just after the read can only
    make a live owner's job claimable again, and a second claimer then meets the live lease and defers (ruling 3)
    while the owner's fenced units keep working: the lease, not the claim, is the authority.
    """
    async with conn.transaction():
        cur = await conn.execute(
            "UPDATE app.jobs j SET claimed_by = NULL, claimed_at = NULL"
            " WHERE j.done_at IS NULL AND j.claimed_at IS NOT NULL AND j.run_id IS NOT NULL"
            " AND NOT EXISTS (SELECT 1 FROM app.run_lease l WHERE l.run_id = j.run_id"
            " AND l.lease_until > app.current_time()) RETURNING j.id"
        )
        return [UUID(str(row["id"])) for row in await cur.fetchall()]

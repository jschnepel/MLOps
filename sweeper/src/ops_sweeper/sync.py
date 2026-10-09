"""The membership sync (AM-20.7 revocation (c), SA:547): deactivate the memberships of users Keycloak reports
disabled or no longer lists, stamp every row of the issuer as checked, never reactivate (SA:107: no tenant
administration in v1). Direct column updates by the `sweeper` role under its `sweeper_all` policy and its
`upd(active, permission_version, synced_at)` cells (ruling 13: SA:470's definer shape cannot write under SA:412,
spike §5). One transaction per run, so a failed listing stamps nothing and `grant_execution` fails closed after 120 s.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from uuid import UUID

from ops_core import persistence

MAX_ABSENT_FRACTION = 0.5  # more than half of the active subjects missing from the listing is a broken listing
MIN_ABSENT_TO_REFUSE = 3  # a floor, so a one- or two-user realm can still lose a user


class MassDeactivation(Exception):
    """Too many active subjects are missing from the listing at once (ruling 27): refused, nothing stamped."""


def refuse(active: Iterable[UUID], users: Mapping[UUID, bool]) -> bool:
    """Whether the listing looks wrong: subjects the realm no longer lists are the ambiguous signal (a wrong realm,
    a partial page), so only those count; a subject the realm explicitly reports disabled is always acted on."""
    subjects = set(active)
    absent = [s for s in subjects if s not in users]
    return len(absent) >= MIN_ABSENT_TO_REFUSE and len(absent) > len(subjects) * MAX_ABSENT_FRACTION


@dataclass(frozen=True)
class SyncResult:
    """What one sync did: rows stamped and rows deactivated."""

    checked: int
    deactivated: int


def plan(memberships: Iterable[UUID], users: Mapping[UUID, bool]) -> frozenset[UUID]:
    """The subjects whose memberships must go: disabled (`False`) or absent from the realm listing (deleted)."""
    return frozenset(subject for subject in memberships if not users.get(subject, False))


async def sync_memberships(
    conn: persistence.Conn, *, issuer: str, users: Mapping[UUID, bool], allow_mass: bool = False
) -> SyncResult:
    """Apply `plan` to every active membership of `issuer`, then stamp all of the issuer's rows, in one transaction.
    `allow_mass` is the owner's one-shot override of the listing guard (OPS_SYNC_ALLOW_MASS_DEACTIVATION=1)."""
    async with conn.transaction():
        # No DISTINCT: PostgreSQL refuses FOR UPDATE with it (0A000, round-1 finding B2); `plan` dedups anyway.
        cur = await conn.execute(
            "SELECT subject FROM app.memberships WHERE issuer = %s AND active FOR UPDATE", (issuer,)
        )
        active = {UUID(str(r["subject"])) for r in await cur.fetchall()}
        if not allow_mass and refuse(active, users):
            # A listing from the wrong realm, or a partial one, would deactivate most of the tenant base at once,
            # and nothing reactivates (SA:107). Refuse, stamp nothing: the gate fails closed after 120 s instead.
            absent = len([s for s in active if s not in users])
            raise MassDeactivation(f"{absent} of {len(active)} active subjects are missing from the listing")
        gone = plan(active, users)
        deactivated = 0
        if gone:
            cur = await conn.execute(
                "UPDATE app.memberships SET active = false, permission_version = permission_version + 1,"
                " synced_at = app.current_time() WHERE issuer = %s AND active AND subject = ANY(%s)",
                (issuer, list(gone)),
            )
            deactivated = cur.rowcount
        cur = await conn.execute(
            "UPDATE app.memberships SET synced_at = app.current_time() WHERE issuer = %s", (issuer,)
        )
        return SyncResult(checked=cur.rowcount, deactivated=deactivated)


async def purge_expired(conn: persistence.Conn) -> dict[str, int]:
    """Delete what nothing can use any more: sessions a day past their end, consumed or expired login state, old jti
    rows (erratum 25: the sweeper holds SELECT with its DELETE on all three)."""
    counts: dict[str, int] = {}
    async with conn.transaction():
        for table, where in (
            (
                "sessions",
                (
                    "expires_at < app.current_time() - interval '1 day'"
                    " OR revoked_at < app.current_time() - interval '1 day'"
                ),
            ),
            ("login_state", "expires_at < app.current_time()"),
            ("logout_jti", "expires_at < app.current_time()"),
        ):
            cur = await conn.execute(f"DELETE FROM app.{table} WHERE {where}")
            counts[table] = cur.rowcount
    return counts

"""The sweeper's tenant iteration (SA:520; Plan I ruling 18; T14 review note 3): for every table but `memberships`
and `jobs` the sweeper has no cross-tenant policy, so it reads the RLS-free `tenants` table and runs its work in one
transaction per tenant with that tenant set. The outbox delivery, the wake-up sweep and the proposal expiry (T21)
use it now; T22's deadline escalation will.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from uuid import UUID

from ops_core import persistence


async def in_tenant[T](conn: persistence.Conn, tenant_id: UUID, work: Callable[[persistence.Conn], Awaitable[T]]) -> T:
    """Run `work` in one transaction with `tenant_id` set (transaction-local, so the next unit starts tenant-less)."""
    async with conn.transaction():
        await persistence.set_tenant(conn, tenant_id)
        return await work(conn)


async def for_each_tenant[T](
    conn: persistence.Conn,
    work: Callable[[persistence.Conn], Awaitable[T]],
    *,
    tenants: Sequence[UUID] | None = None,
) -> dict[UUID, T]:
    """`work`'s answer per tenant, each in its own transaction; every tenant unless `tenants` narrows it (tests)."""
    chosen = await persistence.tenants(conn) if tenants is None else list(tenants)
    return {tenant: await in_tenant(conn, tenant, work) for tenant in chosen}

"""The model permit around every model call (AM-12 SA:203-205, Plan H ruling 12): one row of `app.model_permit` per
unit of global model concurrency (one, BS:549), taken with SKIP LOCKED in its own short transaction and released in
another, so a waiting worker never holds a database transaction. A busy permit is polled with capped exponential
backoff and jitter while the caller's lease lasts. The take and the release are database units and are never
cancelled; the back-off sleep is the one effect a lost lease cancels (review round 1, I2), so the `finally` releases
exactly the slot a take returned, also when the lease is lost during the model call. A 65 s TTL (one 60 s model
attempt plus 5 s) frees a permit whose holder died. TODO(T19): SA:205's stricter release ("hold until `ollama ps`
shows idle"), once T02 has measured whether a cancelled request stops Ollama's generation.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from typing import Any

from ops_core import persistence
from ops_core.lease import Lease

PERMIT_TTL_SECONDS = 65  # SA:596: a model attempt is capped at 60 s; 5 s more for the call around it
FIRST_BACKOFF_SECONDS = 0.25
MAX_BACKOFF_SECONDS = 2.0
Sleep = Callable[[float], Coroutine[Any, Any, None]]


def backoff(attempt: int, rand: Callable[[], float] = random.random) -> float:
    """The wait after failed poll number `attempt` (from 0): 0.25 s doubling to 2 s, scaled at random into its upper
    half, so two waiting workers drift apart without a near-zero wait that would hammer the row."""
    base = min(MAX_BACKOFF_SECONDS, FIRST_BACKOFF_SECONDS * 2.0 ** min(attempt, 3))
    return base * (0.5 + 0.5 * rand())


async def _wait_for_permit(
    conn: persistence.Conn,
    *,
    holder: str,
    lease: Lease,
    sleep: Sleep,
    rand: Callable[[], float],
) -> int:
    """Poll until a permit slot is free, each try its own short transaction; LeaseLost once the lease is gone (at the
    check before a take, or by the back-off sleep, which runs as a lease effect)."""
    attempt = 0
    while True:
        lease.check()
        async with conn.transaction():
            slot = await persistence.take_model_permit(
                conn, holder=holder, run_id=lease.run_id, ttl_seconds=PERMIT_TTL_SECONDS
            )
        if slot is not None:
            return slot
        await lease.effect(sleep(backoff(attempt, rand)))
        attempt += 1


@asynccontextmanager
async def model_permit(
    conn: persistence.Conn,
    *,
    holder: str,
    lease: Lease,
    sleep: Sleep = asyncio.sleep,
    rand: Callable[[], float] = random.random,
) -> AsyncIterator[int]:
    """Hold one model permit for the block, waiting for it while the lease lasts (`lease.check()` raises LeaseLost)."""
    slot = await _wait_for_permit(conn, holder=holder, lease=lease, sleep=sleep, rand=rand)
    try:
        yield slot
    finally:
        async with conn.transaction():
            await persistence.release_model_permit(conn, slot=slot, holder=holder)

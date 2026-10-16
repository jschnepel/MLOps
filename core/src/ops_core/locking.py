"""The published lock order (AM-12 SA:188, extended by Plan H ruling 14; erratum 52) as data a test checks.

The order constrains waits: row locks on rows that already exist (`SELECT … FOR UPDATE` or `FOR SHARE`, `UPDATE`,
`DELETE`) and advisory locks. A transaction takes them in this order and never goes back to an earlier entry for a
row it does not already hold. Two kinds of statement are outside the order because they never wait on another
transaction's lock: a `SKIP LOCKED` read, and a `NOWAIT` lock (it fails with SQLSTATE 55P03 instead of waiting). Plain
reads take no lock. An INSERT of a fresh row with a new key never waits on the table it inserts into (two inserts of
the same new key make the second wait for the first inserter alone), but its foreign-key check takes FOR KEY SHARE on
the referenced parent row, and that waits for any FOR UPDATE holder of the parent: the first `run_lease` row of a run
locks its `runs` row, and an `invocation_context` row its `runs` and `jobs` rows. Such an insert therefore ranks at its
parent's position; the entries below include those parents.

`jobs` appears twice: a claim picks its job with SKIP LOCKED before anything else, and a transaction that finishes,
re-queues or hands back its own claimed job does so after everything but the idempotency record. Tables in `OWN_UNIT`
are only locked in transactions that lock no run table; `NEVER_LOCKED` tables are inserted or read, never locked.
`OBSERVED_UNITS` lists every transaction of the system after T13 as the entries it locks, in order (reads left out,
foreign-key parents of fresh inserts included). It is written by hand: tests/plan_h/test_locking.py checks that the
documented units are consistent with the order and fails when a table in the privilege matrix has no place here, so a
new table or transaction is placed before it ships; it cannot discover a transaction nobody listed (the live stress
test hunts for those).
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise
from typing import Final

LOCK_ORDER: Final = (
    "advisory:idempotency",  # erratum 37: pg_advisory_xact_lock(1, hashtext(scope)), the API's units only
    "advisory:asset",  # SA:189: pg_advisory_xact_lock(hashtextextended(tenant || ':' || asset, 0)); taken by T21
    "advisory:notification",  # T14: pg_advisory_xact_lock(2, hashtext(outbox_id)), a dead letter's announcement
    "jobs:claim",  # SKIP LOCKED only (Plan H ruling 3)
    "run_lease",
    "runs",
    "messages",
    "drafts",
    "proposals",
    "decisions",
    "memberships",
    "execution_grant",
    "action_attempt",
    "action_attempt_state",
    "operator_resolutions",  # created by T22
    "invocation_context",
    "run_state_history",
    "events",
    "outbox",  # created by T14
    "jobs:finish",  # the transaction's own claimed job: finished, re-queued or handed back
    "idempotency_request",  # written last, before commit (SA:188)
)
OWN_UNIT: Final = frozenset(
    {"model_permit", "sessions", "login_state", "logout_jti", "test_clock", "tenants", "run_directory"}
)
NEVER_LOCKED: Final = frozenset({"conversations", "transitions"})
NOT_YET_CREATED: Final = frozenset({"operator_resolutions", "outbox"})

OBSERVED_UNITS: Final[dict[str, tuple[str, ...]]] = {
    "worker claim (persistence.claim_next)": ("jobs:claim", "run_lease", "runs"),  # a first lease's FK key share
    "worker investigate start": ("run_lease", "runs", "jobs:finish"),  # the minted handle's FK key share on its job
    "worker tool event (append_event)": ("run_lease", "runs"),
    "worker failure (transition_run)": ("run_lease", "runs"),
    "worker draft and freeze": ("run_lease", "runs"),
    "worker execute start": ("run_lease", "runs", "jobs:finish"),
    "worker mark_unknown": ("run_lease", "runs", "invocation_context"),
    # T14 (Plan I ruling 10): the release also makes the run's other deferred jobs due; that UPDATE picks its rows
    # with SKIP LOCKED, so it never waits, and it sits at the finish position with the release's own job.
    "worker release (persistence.release_lease)": ("run_lease", "invocation_context", "jobs:finish"),
    "worker abandon (lease lost)": ("run_lease", "invocation_context", "jobs:finish"),
    "heartbeat renewal (lease.renew)": ("run_lease",),
    "mcp resolve_invocation and lookup_action": ("run_lease",),
    "mcp-write grant_execution": ("run_lease", "runs"),
    "mcp-write mark_sent": ("run_lease", "runs"),
    "mcp-write record_outcome": ("run_lease", "runs"),
    "api admission (create_run)": ("advisory:idempotency", "runs", "idempotency_request"),
    "api clarification reply": ("advisory:idempotency", "runs", "idempotency_request"),
    "api decision (record_decision)": ("advisory:idempotency", "runs", "idempotency_request"),
    "sweeper membership sync": ("memberships",),
    "sweeper reclaim (leases.reclaim)": ("jobs:finish",),
    "sweeper sync job record": ("jobs:claim",),
    # T14 (Plan I ruling 22). Every event append writes its notification intent last: the runs row lock, the event,
    # then the outbox row (revision 0008's _append_event; a fresh row, its unique key serialised by the runs lock).
    "event append with notification intent (_append_event)": ("runs", "events", "outbox"),
    # The delivery loop claims and records in units of their own, and appends notification.failed in a separate
    # transaction, so it never takes runs after outbox (SA:188); that unit first takes the dead letter's advisory lock
    # and then re-checks, so a second sweeper waits for the first and finds the event (round 1, M5).
    "sweeper outbox claim (outbox.deliver)": ("outbox",),
    "sweeper outbox result (outbox.deliver)": ("outbox",),
    "sweeper notification.failed (outbox.notify_dead_letters)": ("advisory:notification", "runs", "events"),
    # The wake-up sweep reads runs and jobs without a lock and re-arms one job per unit; the purge deletes finished
    # maintenance rows, which belong to no run.
    "sweeper wake-up re-arm (wakeups.sweep)": ("jobs:finish",),
    "sweeper maintenance purge (wakeups.purge_maintenance)": ("jobs:finish",),
    "sweeper deliver_outbox and sweep_wakeups job records": ("jobs:claim",),
}
OWN_UNITS: Final[dict[str, tuple[str, ...]]] = {
    "worker model permit (take, release)": ("model_permit",),
    "api session touch and revocation": ("sessions",),
    "api login state consumption": ("login_state",),
    "api logout jti record": ("logout_jti",),
    "sweeper purge": ("sessions", "login_state", "logout_jti", "idempotency_request"),
    "test clock move (test_harness)": ("test_clock",),
}


def table_of(entry: str) -> str | None:
    """The table an order entry locks (`jobs:claim` → `jobs`), or None for an advisory lock."""
    head, _, _ = entry.partition(":")
    return None if head == "advisory" else head


def rank(entry: str) -> int:
    """The entry's position in the order.

    Raises:
        ValueError: the entry has no place in the order (an own-unit table, a typo).
    """
    return LOCK_ORDER.index(entry)


def follows_order(entries: Sequence[str]) -> bool:
    """True when a transaction taking `entries` in this sequence never steps back in the order; repeating an entry is
    allowed (the lock is already held)."""
    ranks = [rank(entry) for entry in entries]
    return all(earlier <= later for earlier, later in pairwise(ranks))

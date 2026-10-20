"""Test-only fault injection (R098; BUILD_SPEC §14 "Fault hooks are test-harness-only"; SA:564): a counter per fault
kind that a server consumes on its hot path. `Faults` is the factory: it refuses to exist outside the test profile,
which is what makes the hooks unreachable in dev and demo; each service mounts its own arming route over the object
its factory built (incident-sim's destination faults, the API's admission faults; Plan H ruling 22). `BS405` maps
BUILD_SPEC's nine faults to the hooks. The worker has none: its failure, a lost lease, is produced for real by the
tests (Plan H ruling 20). The sweeper has one, `outbox_sink_fail`, and no route: the live tests build its outbox sink
with a test-profile `Faults` (Plan I ruling 14; T24's DEV-029 needs a fault-injectable sink).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from ops_core.settings import Profile


class FaultKind(StrEnum):
    """The hooks, named by their effect on the next request (Plan E ruling 13, Plan H ruling 22)."""

    REJECT_NEXT = "reject_next"  # the next POST writes a permanent REJECTED key (reason policy)
    DROP_BEFORE_COMMIT = "drop_before_commit"  # the next POST answers 503 and writes nothing
    LOSE_AFTER_COMMIT = "lose_after_commit"  # the next POST commits, then the response is lost (503)
    TIMEOUT_BEFORE_ACCEPT = "timeout_before_accept"  # the next POST is held `seconds`, then 503; nothing written
    RATE_LIMIT = "rate_limit"  # the next POST answers 429 with Retry-After; nothing written
    MALFORMED_RESPONSE = "malformed_response"  # the next POST commits and answers a body that is no receipt
    RECEIPT_HASH_MISMATCH = "receipt_hash_mismatch"  # the next POST commits and answers another payload hash
    DELAY_RECEIPT = "delay_receipt"  # the next lookup of a committed key answers 404, as if not yet visible
    OUTBOX_SINK_FAIL = "outbox_sink_fail"  # the sweeper's next notification delivery fails (T14, R024)
    ASSET_UNAVAILABLE = "asset_unavailable"  # asset-sim's next status answers `unavailable` (T16)


# BS:405's nine faults, phrase by phrase. Concurrent same-key submission is a harness behaviour, not a hook: two
# submissions of one key are raced with asyncio.gather against the real key table (R047,
# tests/e2e/test_incident_sim_live.py), since a hook could only pretend to the race the table must win.
BS405: Final[dict[str, FaultKind | None]] = {
    "response loss after commit": FaultKind.LOSE_AFTER_COMMIT,
    "timeout before acceptance": FaultKind.TIMEOUT_BEFORE_ACCEPT,
    "delayed receipt visibility": FaultKind.DELAY_RECEIPT,
    "malformed response": FaultKind.MALFORMED_RESPONSE,
    "mismatching receipt hash": FaultKind.RECEIPT_HASH_MISMATCH,
    "rate limit": FaultKind.RATE_LIMIT,
    "transient unavailable": FaultKind.DROP_BEFORE_COMMIT,
    "definitive no-commit failure": FaultKind.REJECT_NEXT,
    "concurrent same-key submission": None,
}
# The sweeper's own hook: not one of BS:405's destination faults, and armed only through its sink's factory argument.
SWEEPER_FAULTS: Final = frozenset({FaultKind.OUTBOX_SINK_FAIL})
# asset-sim's own hook (T16, Plan M ruling 6): the contract's third asset state, which no data rule produces. Its
# other faults are BS:405's (a transient 503, a malformed response, a slow answer), consumed the destination's way.
ASSET_SIM_FAULTS: Final = frozenset({FaultKind.ASSET_UNAVAILABLE})
TIMED: Final = frozenset({FaultKind.TIMEOUT_BEFORE_ACCEPT})  # the kinds that take `seconds`
DEFAULT_SECONDS: Final = 5


class FaultsDisabled(RuntimeError):
    """Constructed outside the test profile: the hooks must not exist there (R098)."""


class Faults:
    """Armed counts per kind; `take` consumes one or answers False when nothing is armed."""

    def __init__(self, profile: Profile) -> None:
        if profile is not Profile.TEST:
            raise FaultsDisabled(f"fault hooks are unavailable in the {profile.value} profile")
        self._armed: dict[FaultKind, int] = {}
        self._seconds: dict[FaultKind, int] = {}

    def arm(self, kind: FaultKind, count: int = 1, *, seconds: int | None = None) -> None:
        """Arm `count` occurrences of `kind` (adds to what is armed); `seconds` is how long a timed kind holds.

        Raises:
            ValueError: a count below 1, or `seconds` below 1 or for a kind without a duration; nothing is armed.
        """
        if count < 1:
            raise ValueError("count must be at least 1")
        if seconds is not None:
            if kind not in TIMED:
                raise ValueError("seconds applies to timeout_before_accept only")
            if seconds < 1:
                raise ValueError("seconds must be at least 1")
            self._seconds[kind] = seconds
        self._armed[kind] = self._armed.get(kind, 0) + count

    def take(self, kind: FaultKind) -> bool:
        """Consume one armed occurrence; False when none is armed."""
        left = self._armed.get(kind, 0)
        if left <= 0:
            return False
        if left == 1:
            del self._armed[kind]
        else:
            self._armed[kind] = left - 1
        return True

    def seconds(self, kind: FaultKind) -> int:
        """How long a timed kind holds its request: the last value armed, else DEFAULT_SECONDS."""
        return self._seconds.get(kind, DEFAULT_SECONDS)

    def armed(self) -> dict[str, int]:
        """What is still armed, by kind name."""
        return {kind.value: count for kind, count in self._armed.items()}

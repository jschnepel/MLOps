"""Test-only fault injection (R098; BUILD_SPEC §14 "Fault hooks are test-harness-only"): a counter per fault kind
that a server consumes on its hot path. Framework-free so every service (incident-sim here, the application
services with T13) mounts its own arming route; the factory refuses to exist outside the test profile, which is what
makes the hooks unreachable in dev and demo (SA:564).
"""

from __future__ import annotations

from enum import StrEnum

from ops_core.settings import Profile


class FaultKind(StrEnum):
    """The three BS:405 faults T10 implements; T13 adds the other six."""

    REJECT_NEXT = "reject_next"  # the next POST writes a permanent REJECTED key (reason policy)
    DROP_BEFORE_COMMIT = "drop_before_commit"  # the next POST answers 503 and writes nothing
    LOSE_AFTER_COMMIT = "lose_after_commit"  # the next POST commits, then the response is lost (503)


class FaultsDisabled(RuntimeError):
    """Constructed outside the test profile: the hooks must not exist there (R098)."""


class Faults:
    """Armed counts per kind; `take` consumes one or answers False when nothing is armed."""

    def __init__(self, profile: Profile) -> None:
        if profile is not Profile.TEST:
            raise FaultsDisabled(f"fault hooks are unavailable in the {profile.value} profile")
        self._armed: dict[FaultKind, int] = {}

    def arm(self, kind: FaultKind, count: int = 1) -> None:
        """Arm `count` occurrences of `kind` (adds to what is armed)."""
        if count < 1:
            raise ValueError("count must be at least 1")
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

    def armed(self) -> dict[str, int]:
        """What is still armed, by kind name."""
        return {kind.value: count for kind, count in self._armed.items()}

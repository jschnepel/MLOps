"""The scoped Idempotency-Key (BUILD_SPEC §7 BS:264, BS:299; SA:188, SA:297, SA:429; Plan G rulings 1-7).

A mutation's key is scoped to the tenant, the subject, the route template and the key itself, and its record is the
response: status and JSON body, written last in the unit that did the work, so a replay is the same answer and a
crash before commit leaves no record (R015, R016). Inside the unit the first statement is an advisory lock on the
scope: a second request with the same key waits for the first to commit and then replays its record, where a plain
unique index would hand it a 23505 whose DETAIL prints the tenant, the subject and the key (spike §1).

Three kinds of answer are never recorded. Two because nothing was decided: a key reused for another request (409
IDEMPOTENCY_CONFLICT; recording it would turn a client bug into a permanent answer) and anything raised before or
outside the router's verdict (401, 403, the header and body shape refusals, 503). The third because it is transient:
a full tenant queue (429 with Retry-After) promises the same request a later success, which a recorded 429 would
break for the whole replay window (ruling 5). The rule of thumb in the code: the router's verdict is recorded;
everything before the router, and the queue's momentary fill, is not.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from fastapi.responses import JSONResponse
from ops_core.canonical import canonical_sha256
from ops_core.contracts import ErrorCode, SafeError
from ops_core.settings import AdmissionSettings

HEADER = "Idempotency-Key"
KEY_REFUSAL = "Idempotency-Key header is required (8–128 visible ASCII characters)"
# The first key of the scope lock's two-key form (ruling 6): PostgreSQL keeps two-key advisory locks apart from the
# one-key (bigint) locks the asset guard takes (SA:189), so a scope can never collide with an asset (erratum 37).
IDEMPOTENCY_LOCK_NAMESPACE = 1


class KeyInvalid(ValueError):
    """The Idempotency-Key header is missing or not 8-128 visible ASCII characters."""


class IdempotencyConflict(Exception):
    """The key was used before for a different request (or its expired record is not purged yet): never recorded."""

    def __init__(self, message: str = "Idempotency-Key was already used with a different request") -> None:
        super().__init__(message)
        self.message = message


class QueueFull(Exception):
    """The tenant's queue is at its quota (ruling 18): transient, so the unit rolls back and nothing is recorded."""


class RecordRace(Exception):
    """The final record insert found a row the lookup did not see: the unit rolls back and the store re-reads."""


def validate_key(raw: str | None, bounds: AdmissionSettings | None = None) -> str:
    """The key if it is 8-128 characters in 0x21-0x7E (printable ASCII without space), else KeyInvalid (ruling 1).

    A key is an opaque client token: anything outside visible ASCII would compare differently after a proxy
    normalised it, and a space invites a header-folding ambiguity.
    """
    low, high = (bounds.idempotency_key_min, bounds.idempotency_key_max) if bounds else (8, 128)
    if raw is None or not low <= len(raw) <= high or any(not 0x21 <= ord(ch) <= 0x7E for ch in raw):
        raise KeyInvalid(KEY_REFUSAL)
    return raw


@dataclass(frozen=True)
class Scope:
    """Whose key this is and for which route (ruling 2): the route is the method and the path template, so the same
    key reused on another conversation is the same scope with a different fingerprint, a 409."""

    tenant_id: UUID
    subject: UUID
    route: str
    key: str

    @property
    def lock_key(self) -> str:
        """The string the unit's advisory lock hashes (`hashtext`, in IDEMPOTENCY_LOCK_NAMESPACE; ruling 6)."""
        return f"{self.tenant_id}|{self.subject}|{self.route}|{self.key}"


def scope_lock_key(scope: Scope) -> str:
    """The advisory-lock string of a scope (the same as `Scope.lock_key`; named for the store and the tests)."""
    return scope.lock_key


def fingerprint(path: Mapping[str, str], body: Mapping[str, Any] | None) -> str:
    """What makes two requests "the same" (ruling 3): the path parameters and the validated body, canonical JSON v1,
    so whitespace and key order do not matter and a semantically equal retry replays."""
    return canonical_sha256({"path": dict(path), "body": None if body is None else dict(body)})


@dataclass(frozen=True)
class Verdict:
    """A recorded (or recordable) answer: the status and the JSON body a replay returns unchanged."""

    status: int
    body: dict[str, Any]
    replayed: bool = field(default=False, compare=False)


@dataclass(frozen=True)
class Record:
    """A live record as the lookup returns it."""

    fingerprint: str
    status: int
    body: dict[str, Any]


@dataclass(frozen=True)
class Idem:
    """Everything a unit needs to look up, decide and record: the scope, the fingerprint, the replay window, and the
    request id that error bodies carry (a replayed error carries it too: `replay`)."""

    scope: Scope
    fingerprint: str
    ttl_seconds: int
    request_id: UUID


class RecordUnit(Protocol):
    """The three record operations one transaction offers (`DbUnit` in SQL, the unit-test fake in memory)."""

    async def lock_scope(self, lock_key: str) -> None:
        """Take the transaction-scoped advisory lock on the scope (before any table lock: erratum on SA:188)."""
        ...

    async def find_record(self, scope: Scope) -> Record | None:
        """The live record of the scope, or None (an expired row is not a record: ruling 7)."""
        ...

    async def save_record(self, scope: Scope, fingerprint: str, verdict: Verdict, ttl_seconds: int) -> bool:
        """Insert the record; False when a row for the scope already exists (rowcount 0)."""
        ...


def replay(found: Record, idem: Idem) -> Verdict:
    """The recorded answer to this request (ruling 4). A success body carries no request id and replays unchanged; a
    recorded error carries the replaying request's id, so its body, its X-Request-Id header and the log agree (BS:301:
    the id names the request the client sent, and the first request's id would match no line of this one)."""
    body = found.body
    if found.status >= 400 and "request_id" in body:
        body = {**body, "request_id": str(idem.request_id)}
    return Verdict(found.status, body, replayed=True)


async def idempotent(unit: RecordUnit, idem: Idem, work: Callable[[], Awaitable[Verdict]]) -> Verdict:
    """Lock, look up, then replay, refuse or run `work` and record its verdict last (SA:188), all in the caller's
    transaction.

    Raises:
        IdempotencyConflict: the scope's record has another fingerprint.
        RecordRace: the insert met a row the lookup did not see; the caller rolls back and re-reads.
    """
    await unit.lock_scope(idem.scope.lock_key)
    found = await unit.find_record(idem.scope)
    if found is not None:
        if found.fingerprint != idem.fingerprint:
            raise IdempotencyConflict
        return replay(found, idem)
    verdict = await work()
    if not await unit.save_record(idem.scope, idem.fingerprint, verdict, idem.ttl_seconds):
        # Impossible while every writer takes the lock first; an expired row the sweeper has not purged yet is the one
        # real case (the lookup skips it, the primary key does not), and the store's re-read answers it.
        raise RecordRace
    return verdict


def error_verdict(status: int, code: ErrorCode, message: str, request_id: UUID) -> Verdict:
    """A recorded refusal: the SafeError body (BS:301), never retryable, since the router decided it."""
    body = SafeError(code=code, message=message, retryable=False, request_id=request_id)
    return Verdict(status, body.model_dump(mode="json"))


def render(body: Mapping[str, Any]) -> bytes:
    """The one serialisation of a verdict's body: sorted keys and compact separators, so the first answer and every
    replay are the same bytes although jsonb stores keys in its own order."""
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


class VerdictResponse(JSONResponse):
    """A JSON response rendered by `render`, for first answers and replays alike (ruling 4)."""

    def render(self, content: Any) -> bytes:
        """Every verdict body is serialised by `render`, sorted and compact (ruling 4)."""
        return render(content)


def response(verdict: Verdict) -> VerdictResponse:
    """The HTTP response of a verdict, a first answer and a replay alike (a 429 is never a verdict: ruling 5)."""
    return VerdictResponse(content=verdict.body, status_code=verdict.status)

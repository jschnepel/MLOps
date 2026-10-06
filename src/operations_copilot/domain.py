"""Model-independent control rules. No framework, model, or network dependency."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
from typing import Any

class DomainError(Exception):
    """Expected, user-safe application error."""
    status_code = 400

class Forbidden(DomainError):
    status_code = 403

class NotFound(DomainError):
    status_code = 404

class Conflict(DomainError):
    status_code = 409

class InvalidInput(DomainError):
    status_code = 422

class UncertainOutcome(DomainError):
    status_code = 503

@dataclass(frozen=True)
class Actor:
    id: str
    team: str
    role: str
    active: bool = True


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def require(actor: Actor, team: str, roles: tuple[str, ...] | None = None) -> None:
    if not actor.active or actor.team != team:
        raise Forbidden("This resource is not available to this identity.")
    if roles is not None and actor.role not in roles:
        raise Forbidden("Your current role does not permit this operation.")


def validate_hours(hours: Any) -> int:
    # bool is an int subclass; reject it instead of silently accepting True as 1 hour.
    if type(hours) is not int or not 1 <= hours <= 168:
        raise InvalidInput("Time range must be an integer from 1 to 168 hours.")
    return hours


def validate_text(text: Any) -> str:
    if not isinstance(text, str) or not text.strip() or len(text) > 4000:
        raise InvalidInput("Message must contain between 1 and 4000 characters.")
    return text.strip()


def validate_draft(draft: dict, permitted_refs: set[str]) -> dict:
    """Check shape/reference membership, NOT semantic truth or full citation support."""
    if not isinstance(draft, dict) or set(draft) != {"summary", "evidence_refs", "limitations"}:
        raise InvalidInput("Draft must match the allowed response schema.")
    summary = draft["summary"]
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 2500:
        raise InvalidInput("Draft summary is missing or too long.")
    refs, limitations = draft["evidence_refs"], draft["limitations"]
    if not isinstance(refs, list) or not refs or len(refs) > 8:
        raise InvalidInput("Draft must cite at least one permitted source.")
    if any(not isinstance(x, str) or x not in permitted_refs for x in refs):
        raise InvalidInput("Draft contains a source reference outside the permitted evidence.")
    if not isinstance(limitations, list) or len(limitations) > 8:
        raise InvalidInput("Limitations must be a bounded list.")
    if any(not isinstance(x, str) or len(x) > 500 for x in limitations):
        raise InvalidInput("Invalid limitation text.")
    return draft

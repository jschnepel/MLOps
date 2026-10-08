"""Request, response, draft and proposal contracts (BUILD_SPEC §7, AM-10, AM-11, AM-13, AM-80).

Every model is strict, frozen and closed (`extra="forbid"`): the server sets actor, tenant, roles, timestamps and
authority fields, and a body that tries to supply them is rejected before any handler runs (R004). Bodies are parsed
with `load()` (JSON mode) so numbers are never coerced from strings or booleans. The JSON Schemas under `schemas/`
say the same things declaratively; Tasks 6-7 of Plan C add `scripts/build_schemas.py` and
`tests/plan_c/test_schema_conformance.py`, which generate the schemas and keep the two in step.

Timestamps (plan ruling 6): every instant must carry a zero UTC offset. Inputs may spell it `Z` or `+00:00`; the
hashed and stored form is pydantic's JSON output, which spells it `Z`, so the proposal schema accepts only `Z` while
request schemas accept either spelling. `Receipt` and `Tombstone` (outcomes.py) are produced by the destination, not
by a requester, so they keep their own timestamp rules and are unchanged here.
"""

from __future__ import annotations

import json
import unicodedata
from datetime import UTC
from enum import StrEnum
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    Strict,
    StringConstraints,
    field_validator,
    model_validator,
)

from ops_core.canonical import canonical_sha256
from ops_core.states import AttemptState, Intent, RunState

# Post-grant states: a run can only be here if a grant was issued (AM-10 state table), so a cancel response that
# reports one of them with `grant_exists=False` contradicts itself.
_POST_GRANT_STATES: Final = frozenset(
    {
        RunState.EXECUTING,
        RunState.OUTCOME_UNKNOWN,
        RunState.ESCALATED,
        RunState.SUCCEEDED,
        RunState.FAILED,
        RunState.ABANDONED_UNVERIFIED,
    }
)

AUTHORITY_FIELDS: Final = frozenset(
    {
        "tenant_id",
        "actor",
        "actor_id",
        "role",
        "roles",
        "approved",
        "approved_by",
        "destination",
        "reviewer",
        "requester",
    }
)  # names a client or model may never supply (BUILD_SPEC §7, R004); `extra="forbid"` rejects them everywhere


def _nfc(value: object) -> object:
    # BUILD_SPEC §6 "normalize bounded strings to NFC at proposal creation". It runs before the length, uniqueness and
    # ordering checks so they see the same code points `canonical_json` hashes; without it two NFC-equivalent payloads
    # (NFD "e" + U+0301 and precomposed U+00E9) would hash differently and sort differently.
    return unicodedata.normalize("NFC", value) if isinstance(value, str) else value


def _iso_instant(value: object) -> object:
    # Pydantic's lax datetime parsing also takes epoch numbers and date-only forms, and RFC 3339 reserves `-00:00` for
    # "offset unknown". A requester-supplied instant must be a full ISO-8601 string that says UTC explicitly.
    if not (isinstance(value, str) and "T" in value and value.endswith(("Z", "+00:00"))):
        raise ValueError("timestamps must be ISO-8601 with a date, 'T' and an explicit offset")
    return value


_Strict = ConfigDict(frozen=True, extra="forbid", strict=True)
_Nfc = BeforeValidator(_nfc)
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000), _Nfc]
Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500), _Nfc]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120), _Nfc]
Summary = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2500), _Nfc]
AssetId = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_-]{0,31}$")]
EvidenceRef = Annotated[str, StringConstraints(min_length=1, max_length=160), _Nfc]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
# Lax inside, because a before-validator hands the inner schema a Python str, which strict mode refuses for datetimes
# even though the original JSON string was fine; `_iso_instant` has already narrowed the input to ISO strings.
Instant = Annotated[AwareDatetime, Strict(False), BeforeValidator(_iso_instant)]


class DuplicateKey(ValueError):
    """A JSON object repeated a key (BUILD_SPEC §6 "reject duplicate JSON keys")."""


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    # Pydantic keeps the last value of a repeated key, so a gateway that reads the first and a handler that reads the
    # last could disagree about the same body. Rejecting is the only safe answer.
    seen: set[str] = set()
    for key, _ in pairs:
        if key in seen:
            raise DuplicateKey(f"duplicate JSON key {key!r}")
        seen.add(key)
    return dict(pairs)


def load[M: BaseModel](model: type[M], text: str) -> M:
    """Parse a JSON body into a contract in strict JSON mode (strings never become numbers, bools never ints).

    Raises:
        DuplicateKey: an object in the body repeats a key.
        pydantic.ValidationError: the body is malformed or violates the contract.
    """
    try:
        json.loads(text, object_pairs_hook=_reject_duplicate_pairs)
    except json.JSONDecodeError:
        pass  # malformed JSON is pydantic's error to report, so callers see one exception type for it
    return model.model_validate_json(text)


def _unique(items: list[str]) -> list[str]:
    if len(set(items)) != len(items):
        raise ValueError("duplicate entries")
    return items


def _sorted(items: list[str], what: str) -> None:
    # Canonical JSON keeps array order (BUILD_SPEC §6 "documented stable array order"), so the producer must fix it.
    if items != sorted(items):
        raise ValueError(f"{what} must be sorted ascending by code point so the payload hash is stable")


def _utc(value: AwareDatetime) -> AwareDatetime:
    # BUILD_SPEC §6 "UTC instants with explicit offsets": a zero offset is required (`Z` or `+00:00` both parse to
    # it), so one instant has one canonical spelling once pydantic serialises it as `Z` (ruling 6).
    if value.utcoffset() != UTC.utcoffset(None):
        raise ValueError("timestamps must carry a zero UTC offset (Z or +00:00)")
    return value


class MessageKind(StrEnum):
    """What a message asks for; the admission router (AM-16) reads it."""

    INVESTIGATE = "investigate"
    ASK = "ask"
    STATUS = "status"
    CLARIFICATION = "clarification"


class MessageContext(BaseModel):
    """Structured context a requester may attach: the asset and the look-back window in hours."""

    model_config = _Strict
    asset_id: AssetId | None = None
    hours: int | None = Field(default=None, ge=1, le=168)  # strict: True, 1.5 and "24" are rejected


class MessageRequest(BaseModel):
    """`POST /conversations/{id}/messages` (BUILD_SPEC §7 sample; AM-16 admission routes read `kind`)."""

    model_config = _Strict
    kind: MessageKind
    text: Text
    context: MessageContext | None = None
    supersedes_run_id: UUID | None = None  # requester-asserted (AM-10 "Requester-asserted fields")


class RunRequestFields(BaseModel):
    """The requester-asserted run fields `create_run`/`create_revision` store on `runs` (AM-10, AM-20.3).

    They come only from the authenticated request's structured fields (admission or revision); model output is never
    a source for either, which is why `ModelDraft` has neither field. `intent` drives `freeze_allowed`;
    `supersedes_run_id` is injected into the hashed payload by `freeze_proposal`.
    """

    model_config = _Strict
    intent: Intent
    supersedes_run_id: UUID | None = None


class ClarificationReply(BaseModel):
    """The requester's answer to a clarification question (AM-10 clarification signal)."""

    model_config = _Strict
    question_id: UUID
    expected_version: int = Field(ge=1)
    context: MessageContext

    @model_validator(mode="after")
    def _answers_something(self) -> ClarificationReply:
        if self.context.asset_id is None and self.context.hours is None:
            raise ValueError("a clarification reply must supply asset_id or hours")
        return self


class DecisionRequest(BaseModel):
    """`POST /proposals/{id}/decisions`; the reviewer is the session, never a field (BUILD_SPEC §13)."""

    model_config = _Strict
    expected_revision: int = Field(ge=1)
    expected_payload_sha256: Sha256  # AM-11 / AM-80 row 14 (renamed from payload_sha256)
    decision: Literal["approve", "reject"]
    reason: Short | None = None  # non-empty after stripping, or absent


class RevisionRequest(BaseModel):
    """`POST /runs/{id}/revisions`: re-queue a run, optionally naming the run it supersedes (AM-20.3)."""

    model_config = _Strict
    expected_version: int = Field(ge=1)
    supersedes_run_id: UUID | None = None


class CancelRequest(BaseModel):
    """`POST /runs/{id}/cancel` body (schemas/cancellation.schema.json)."""

    model_config = _Strict
    expected_version: int = Field(ge=1)
    reason: Short | None = None  # non-empty after stripping, or absent


class CancelResponse(BaseModel):
    """`POST /runs/{id}/cancel` reports whether a grant or dispatch already happened; it never claims undo (AM-13)."""

    model_config = _Strict
    run_id: UUID
    status: RunState
    state_version: int = Field(ge=1)
    cancel_requested: bool
    grant_exists: bool
    attempt_state: AttemptState | None
    note: Short | None

    @model_validator(mode="after")
    def _attempt_only_with_grant(self) -> CancelResponse:
        if not self.cancel_requested:
            raise ValueError("a cancel response always records cancel_requested")
        if not self.grant_exists and self.attempt_state is not None:
            raise ValueError("an attempt state exists only after a grant")
        # AM-20.3 request_cancel: CANCELLED only when no grant exists; reporting it after a grant is the "undo" claim.
        if self.status is RunState.CANCELLED and self.grant_exists:
            raise ValueError("CANCELLED cannot be reported once a grant exists")
        if not self.grant_exists and self.status in _POST_GRANT_STATES:
            raise ValueError(f"status {self.status.value} requires a grant")
        return self


class FeedbackRequest(BaseModel):
    """`POST /runs/{id}/feedback`: classified, stored, never a runtime policy (R113).

    The subject kinds and categories are a project choice; the spec names none.
    """

    model_config = _Strict
    subject_kind: Literal["run", "proposal", "event"]
    subject_id: UUID
    category: Literal["wrong_evidence", "missing_evidence", "wrong_conclusion", "unclear", "other"]
    text: Annotated[str, StringConstraints(max_length=2000)] | None = None


class ManualProposalRequest(BaseModel):
    """`POST /manual-proposals`: a human-authored draft that enters the same approval path (AM-20.3)."""

    model_config = _Strict
    asset_id: AssetId
    start_at: Instant
    end_at: Instant
    title: Title
    summary: Summary
    evidence_refs: Annotated[list[EvidenceRef], Field(min_length=1, max_length=8)]
    assumptions: Annotated[list[Short], Field(max_length=8)]
    limitations: Annotated[list[Short], Field(max_length=8)]

    @field_validator("start_at", "end_at")
    @classmethod
    def _utc_only(cls, value: AwareDatetime) -> AwareDatetime:
        return _utc(value)

    @field_validator("evidence_refs")
    @classmethod
    def _unique_refs(cls, items: list[str]) -> list[str]:
        return _unique(items)

    @model_validator(mode="after")
    def _interval(self) -> ManualProposalRequest:
        if not self.start_at < self.end_at:
            raise ValueError("start_at must be before end_at")
        return self


class ModelDraft(BaseModel):
    """The validated model output (schemas/model-draft.schema.json). Carries no authority and no supersession."""

    model_config = _Strict
    kind: Literal["proposal", "answer", "abstain"]
    title: Title
    summary: Summary
    evidence_refs: Annotated[list[EvidenceRef], Field(max_length=8)]
    assumptions: Annotated[list[Short], Field(max_length=8)]
    limitations: Annotated[list[Short], Field(max_length=8)]
    question: Short | None = None  # AM-10: abstain + question = clarification; abstain alone = insufficient evidence

    @field_validator("evidence_refs")
    @classmethod
    def _unique_refs(cls, items: list[str]) -> list[str]:
        return _unique(items)

    @model_validator(mode="after")
    def _kind_rules(self) -> ModelDraft:
        if self.kind in {"proposal", "answer"} and not self.evidence_refs:
            raise ValueError(f"a {self.kind} cites at least one piece of evidence")
        if self.question is not None and self.kind != "abstain":
            raise ValueError("only an abstain carries a question")
        return self

    @property
    def clarification_requested(self) -> bool:
        return self.kind == "abstain" and self.question is not None


class SourceSnapshot(BaseModel):
    """The version and hash of one cited evidence item at freeze time."""

    model_config = _Strict
    evidence_id: EvidenceRef
    content_sha256: Sha256
    version: Annotated[str, StringConstraints(min_length=1, max_length=40)]


class ProposalPayload(BaseModel):
    """The hashed payload (BUILD_SPEC §6 list; AM-80 row 19). `authored_by` is NOT here: it is a sibling of payload."""

    model_config = _Strict
    tenant_id: UUID
    run_id: UUID
    proposal_id: UUID
    revision: int = Field(ge=1)
    action: Literal["create_incident"]
    destination: Literal["synthetic-incidents"]
    asset_id: AssetId
    start_at: Instant
    end_at: Instant
    title: Title
    summary: Summary
    evidence_refs: Annotated[list[EvidenceRef], Field(min_length=1, max_length=8)]
    source_snapshots: Annotated[list[SourceSnapshot], Field(min_length=1, max_length=8)]
    assumptions: Annotated[list[Short], Field(max_length=8)]
    limitations: Annotated[list[Short], Field(max_length=8)]
    workflow_version: Annotated[str, StringConstraints(min_length=1, max_length=60)]
    prompt_version: Annotated[str, StringConstraints(min_length=1, max_length=60)]
    expires_at: Instant
    supersedes_run_id: UUID | None = None  # injected by freeze_proposal from runs (AM-20.3); inside the hash (R125)

    @field_validator("start_at", "end_at", "expires_at")
    @classmethod
    def _utc_only(cls, value: AwareDatetime) -> AwareDatetime:
        return _utc(value)

    @field_validator("evidence_refs")
    @classmethod
    def _unique_sorted_refs(cls, items: list[str]) -> list[str]:
        _sorted(items, "evidence_refs")
        return _unique(items)

    @field_validator("source_snapshots")
    @classmethod
    def _snapshots_sorted(cls, items: list[SourceSnapshot]) -> list[SourceSnapshot]:
        _sorted([s.evidence_id for s in items], "source_snapshots (by evidence_id)")
        return items

    @model_validator(mode="after")
    def _interval(self) -> ProposalPayload:
        if not self.start_at < self.end_at:
            raise ValueError("start_at must be before end_at")
        # BUILD_SPEC §6 hashes "evidence references and their hashes/versions" as pairs: one snapshot per reference,
        # in the same order, so no cited item lacks a snapshot and no snapshot is for something uncited.
        if [s.evidence_id for s in self.source_snapshots] != self.evidence_refs:
            raise ValueError("source_snapshots must cover exactly evidence_refs, in the same order")
        return self

    def canonical_dict(self) -> dict[str, Any]:
        """Return the JSON-ready mapping that is hashed.

        UUIDs become strings and UTC timestamps pydantic's `…Z` form (ruling 6), whatever spelling the input used;
        An explicit null and an absent `supersedes_run_id` hash alike (the key is omitted when it is None). Arrays are
        already in their validated sorted order.
        """
        return self.model_dump(mode="json", exclude={"supersedes_run_id"} if self.supersedes_run_id is None else None)


class Proposal(BaseModel):
    """An immutable revision: canonical bytes' hash plus the content authors, kept outside the hash (AM-80)."""

    model_config = _Strict
    canonicalization_version: Annotated[int, Field(strict=True, ge=1, le=1)]  # strict: `true` is not version 1
    payload: ProposalPayload
    payload_sha256: Sha256
    authored_by: list[UUID] = Field(min_length=1, max_length=8)  # requester plus revision authors (AM-20.3)

    @field_validator("authored_by")
    @classmethod
    def _unique_authors(cls, items: list[UUID]) -> list[UUID]:
        _unique([str(u) for u in items])  # the same author twice would inflate the revision history
        return items

    @model_validator(mode="after")
    def _hash_matches(self) -> Proposal:
        if self.payload_sha256 != canonical_sha256(self.payload.canonical_dict()):
            raise ValueError("payload_sha256 does not match the canonical bytes")
        return self


class ErrorCode(StrEnum):
    """The documented error codes (BUILD_SPEC §7 plus the AM-80 error row)."""

    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    INVALID_INPUT = "INVALID_INPUT"
    RATE_LIMITED = "RATE_LIMITED"
    UNAVAILABLE = "UNAVAILABLE"
    ASSET_ACTION_UNRESOLVED = "ASSET_ACTION_UNRESOLVED"
    ASSET_INCIDENT_EXISTS = "ASSET_INCIDENT_EXISTS"
    GRANT_EXISTS = "GRANT_EXISTS"
    SLOT_OCCUPIED = "SLOT_OCCUPIED"
    AUTHORITY_VIOLATION = "AUTHORITY_VIOLATION"


class SafeError(BaseModel):
    """BUILD_SPEC §7 safe error: no stack traces, queries, tokens or unauthorized IDs."""

    model_config = _Strict
    code: ErrorCode
    message: Short
    retryable: bool
    request_id: UUID

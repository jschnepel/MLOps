"""Generate the contract set under schemas/: 25 JSON Schema documents, every example, and examples/index.json.

Why a generator: the schemas, the examples and the index describe one contract from three angles, and AM-80 changes
all three at once. Hand-editing some ninety JSON files lets them drift apart silently (the dry run of this plan found
examples the prose forgot to update). Here every rule is written once, with its reason beside it, and every enum comes
from `ops_core`, so a schema can never spell a state, reason, tool, job type, route or event type differently from the
code that enforces it. `tests/plan_c/test_schemas_generated.py` regenerates the tree into a temporary directory and
compares every file byte for byte with the committed one, so a hand edit of a generated file fails the build: change
this script and rerun it instead.

Scope: the 19 top-level schemas, the 6 tool-input schemas, all examples and the index. The checker's 26th schema,
`evals/holdout-case.schema.json`, belongs to T03 and is not generated here; `schemas/README.md` stays hand-written.

Paths resolve from the repository root (`ROOT`), never the working directory. Files are written as UTF-8 without a
BOM, with LF line endings, two-space indentation and a trailing newline.

Usage: uv run python -m scripts.build_schemas
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from ops_core.canonical import canonical_sha256
from ops_core.contracts import ErrorCode, MessageKind
from ops_core.jobs import JOB_RULES, Tool
from ops_core.outcomes import DESTINATION_EVIDENCE, FAILED_NO_COMMIT_REASONS, DestinationState, EventType, ToolOutcome
from ops_core.routing import AdmissionRoute, GraphRoute, ModelRoute
from ops_core.states import AttemptState, Reason, RunState

ROOT = Path(__file__).resolve().parents[1]
Doc = dict[str, Any]

COMMENT = (
    "Target contract. Declarative validation does not implement authentication, authorization, semantic support, "
    "atomicity, or runtime integrations."
)
NOTE = "Synthetic target contract example; not a live result."

# --- Vocabularies, all read from ops_core so schema and code cannot disagree on a spelling. ---
STATES = [s.value for s in RunState]
REASONS = [r.value for r in Reason]
FAILED_REASONS = [r.value for r in Reason if r in FAILED_NO_COMMIT_REASONS]  # plan ruling 2 adds `expired`
TOOL_OUTCOMES = [o.value for o in ToolOutcome]
EVENT_TYPES = [e.value for e in EventType]
DESTINATION_TYPES = [e.value for e in EventType if e in DESTINATION_EVIDENCE]
TOOLS = [t.value for t in Tool]
READ_TOOLS = [Tool.GET_ASSET_STATUS.value, Tool.GET_RECENT_ALERTS.value, Tool.SEARCH_PROCEDURES.value]
RECEIPT_TOOLS = [Tool.CREATE_INCIDENT.value, Tool.GET_INCIDENT_RECEIPT.value]  # data = the action-outcome shape
WRITE_TOOLS = [*RECEIPT_TOOLS, Tool.ABORT_INCIDENT.value]

# --- Building blocks. ---
UUID: Doc = {"type": "string", "format": "uuid"}
DATE_TIME: Doc = {"type": "string", "format": "date-time"}  # checked by FormatChecker via rfc3339-validator
# Ruling 6: only a hashed document (the proposal) spells UTC the way pydantic's JSON mode emits it (`Z`), so one
# instant has one spelling inside a hash; manual-proposal, model-pins and the get_recent_alerts input accept `Z` or
# `+00:00`, and the contract normalises before hashing.
UTC_HASHED: Doc = {**DATE_TIME, "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.\\d+)?Z$"}
UTC_REQUEST: Doc = {**DATE_TIME, "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.\\d+)?(Z|\\+00:00)$"}
SHA256: Doc = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
DIGEST: Doc = {"type": "string", "pattern": "^[0-9a-f]{64}$"}  # bare hex, as ops_core.model_pins (AM-31)
ASSET_ID: Doc = {"type": "string", "pattern": "^[A-Z][A-Z0-9_-]{0,31}$"}
NULL: Doc = {"type": "null"}


def text(min_length: int, max_length: int) -> Doc:
    """A string with length bounds."""
    return {"type": "string", "minLength": min_length, "maxLength": max_length}


def integer(minimum: int, maximum: int | None = None) -> Doc:
    """An integer with an inclusive lower (and optional upper) bound."""
    return {"type": "integer", "minimum": minimum} | ({} if maximum is None else {"maximum": maximum})


def array(items: Doc, min_items: int, max_items: int, *, unique: bool = False) -> Doc:
    """A bounded array; `unique` adds uniqueItems."""
    doc: Doc = {"type": "array", "items": items, "minItems": min_items, "maxItems": max_items}
    return doc | ({"uniqueItems": True} if unique else {})


def nullable(schema: Doc) -> Doc:
    """The schema or JSON null."""
    return {"anyOf": [schema, NULL]}


def closed(properties: Doc, required: list[str], **extra: Any) -> Doc:
    """A closed object: `additionalProperties: false` is how authority fields are rejected at every depth (R004)."""
    return {"type": "object", "additionalProperties": False, "properties": properties, "required": required} | extra


def head(name: str, title: str | None = None) -> Doc:
    """The header every contract carries (kept from the delivered 1.0 schemas)."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"urn:operations-copilot:schema:{name}:1",
        "title": title or f"Operations Copilot target {name} v1",
        "$comment": COMMENT,
    }


def contract(name: str, body: Doc, title: str | None = None) -> Doc:
    """A top-level schema: header plus a closed object body."""
    return head(name, title) | body


def when(condition: Doc, then: Doc, otherwise: Doc | None = None) -> Doc:
    """An if/then(/else) rule.

    Every property an `if` tests is top-level `required`, so a missing property cannot satisfy a condition vacuously.
    """
    return {"if": condition, "then": then} | ({} if otherwise is None else {"else": otherwise})


def props(**properties: Doc) -> Doc:
    """`{"properties": {...}}`, the shape of every if/then condition and consequence below."""
    return {"properties": properties}


EVIDENCE_REF = text(1, 160)
SHORT = text(1, 500)
RECEIPT = closed(
    {"receipt_id": UUID, "incident_id": text(1, 100), "committed_at": DATE_TIME},
    ["receipt_id", "incident_id", "committed_at"],
)
# AM-13 "Tombstone shape": returned for ABORTED and REJECTED keys only; a COMMITTED key has a receipt instead.
TOMBSTONE = closed(
    {
        "action_id": UUID,
        "state": {"type": "string", "enum": [DestinationState.ABORTED.value, DestinationState.REJECTED.value]},
        "payload_sha256": SHA256,
        "reason": SHORT,
        "decided_at": DATE_TIME,
    },
    ["action_id", "state", "payload_sha256", "reason", "decided_at"],
)
EVIDENCE_ROW = closed(
    {
        "evidence_id": EVIDENCE_REF,
        "document_id": text(1, 100),
        "version": text(1, 40),
        "section": text(1, 120),
        "content_sha256": SHA256,
        "excerpt": text(1, 8000),
        "effective_from": DATE_TIME,
        "retrieved_at": DATE_TIME,
    },
    ["evidence_id", "document_id", "version", "section", "content_sha256", "excerpt", "effective_from", "retrieved_at"],
)


def action_outcome() -> Doc:
    """The write-tool result (AM-13, AM-15): the status and its evidence must agree, mirrored by ActionOutcome."""
    return closed(
        {
            "status": {"enum": TOOL_OUTCOMES},
            "action_id": UUID,
            "payload_sha256": SHA256,
            "receipt": nullable(RECEIPT),
            "tombstone": nullable(TOMBSTONE),
            "reason": nullable({"type": "string", "enum": FAILED_REASONS}),
        },
        ["status", "action_id", "payload_sha256", "receipt", "tombstone", "reason"],
        allOf=[
            # Only a receipt proves a commit (BUILD_SPEC §14): SUCCEEDED carries exactly a receipt.
            when(
                props(status={"const": ToolOutcome.SUCCEEDED.value}),
                props(receipt=RECEIPT, tombstone=NULL, reason=NULL),
            ),
            # A tombstone proves no commit; the reason comes from the FAILED set (AM-13 outcome vocabulary).
            when(
                props(status={"const": ToolOutcome.FAILED_NO_COMMIT.value}),
                props(tombstone=TOMBSTONE, receipt=NULL, reason={"type": "string", "enum": FAILED_REASONS}),
            ),
            # UNKNOWN and CONFLICT prove nothing either way, so they carry no evidence and no reason.
            when(
                props(status={"enum": [ToolOutcome.UNKNOWN.value, ToolOutcome.CONFLICT.value]}),
                props(receipt=NULL, tombstone=NULL, reason=NULL),
            ),
        ],
    )


def abort_outcome() -> Doc:
    """`abort_incident` data: the destination answers an abort with a receipt (already committed) or a tombstone."""
    return closed(
        {
            "action_id": UUID,
            "outcome": {"enum": [ToolOutcome.SUCCEEDED.value, ToolOutcome.FAILED_NO_COMMIT.value]},
            "receipt": nullable(RECEIPT),
            "tombstone": nullable(TOMBSTONE),
        },
        ["action_id", "outcome", "receipt", "tombstone"],
        allOf=[
            when(
                props(outcome={"const": ToolOutcome.SUCCEEDED.value}),
                props(receipt=RECEIPT, tombstone=NULL),
                props(tombstone=TOMBSTONE, receipt=NULL),
            )
        ],
    )


def message() -> Doc:
    """`POST /conversations/{id}/messages` (AM-80 message row)."""
    context = closed({"asset_id": ASSET_ID, "hours": integer(1, 168)}, [])
    return contract(
        "message",
        closed(
            {
                "kind": {"enum": [k.value for k in MessageKind]},  # 1.0's `question` is gone
                "text": text(1, 4000),
                "context": context,
                "supersedes_run_id": UUID,  # requester-asserted and structured (AM-10); optional
            },
            ["kind", "text"],
        ),
    )


def clarification() -> Doc:
    """The clarification reply; it must answer something (minProperties 1)."""
    context = closed({"asset_id": ASSET_ID, "hours": integer(1, 168)}, [], minProperties=1)
    return contract(
        "clarification",
        closed(
            {"question_id": UUID, "expected_version": integer(1), "context": context},
            ["question_id", "expected_version", "context"],
        ),
    )


def decision() -> Doc:
    """`POST /proposals/{id}/decisions`; `expected_payload_sha256` replaces 1.0's `payload_sha256` (AM-11, AM-80)."""
    return contract(
        "decision",
        closed(
            {
                "expected_revision": integer(1),
                "expected_payload_sha256": SHA256,
                "decision": {"enum": ["approve", "reject"]},
                "reason": text(0, 500),
            },
            ["expected_revision", "expected_payload_sha256", "decision"],
        ),
    )


def cancellation() -> Doc:
    """`POST /runs/{id}/cancel` request body (unchanged from 1.0)."""
    return contract(
        "cancellation", closed({"expected_version": integer(1), "reason": text(0, 500)}, ["expected_version"])
    )


def error() -> Doc:
    """BUILD_SPEC §7 safe error; the code list is ops_core's ErrorCode (AM-80 error row)."""
    return contract(
        "error",
        closed(
            {
                "code": {"type": "string", "enum": [c.value for c in ErrorCode]},
                "message": SHORT,
                "retryable": {"type": "boolean"},
                "request_id": UUID,
            },
            ["code", "message", "retryable", "request_id"],
        ),
    )


def evidence() -> Doc:
    """A retrieval row (unchanged from 1.0; per-section hashes are consumed from T17)."""
    return contract("evidence", EVIDENCE_ROW)


def model_draft() -> Doc:
    """The validated model output (AM-10 clarification signal, AM-80 model-draft row)."""
    return contract(
        "model-draft",
        closed(
            {
                "kind": {"enum": ["proposal", "answer", "abstain"]},
                "title": text(1, 120),
                "summary": text(1, 2500),
                "evidence_refs": array(EVIDENCE_REF, 0, 8, unique=True),
                "assumptions": array(SHORT, 0, 8),
                "limitations": array(SHORT, 0, 8),
                "question": SHORT,  # abstain + question = clarification; abstain alone = insufficient evidence
            },
            ["kind", "title", "summary", "evidence_refs", "assumptions", "limitations"],
            allOf=[
                when(props(kind={"enum": ["proposal", "answer"]}), props(evidence_refs={"minItems": 1})),
                # Only an abstain asks a question. The draft never carries supersedes_run_id: the closed object
                # already rejects it (AM-13 asset guard, R125).
                {"if": props(kind={"const": "abstain"}), "else": {"not": {"required": ["question"]}}},
            ],
        ),
    )


def proposal() -> Doc:
    """An immutable proposal revision (BUILD_SPEC §6, AM-80 proposal row)."""
    snapshot = closed(
        {"evidence_id": EVIDENCE_REF, "content_sha256": SHA256, "version": text(1, 40)},
        ["evidence_id", "content_sha256", "version"],
    )
    payload = closed(
        {
            "tenant_id": UUID,
            "run_id": UUID,
            "proposal_id": UUID,
            "revision": integer(1),
            "action": {"const": "create_incident"},
            "destination": {"const": "synthetic-incidents"},
            "asset_id": ASSET_ID,
            "start_at": UTC_HASHED,
            "end_at": UTC_HASHED,
            "title": text(1, 120),
            "summary": text(1, 2500),
            # Sorted order (code rule, ProposalPayload) cannot be said in JSON Schema; uniqueness can.
            "evidence_refs": array(EVIDENCE_REF, 1, 8, unique=True),
            "source_snapshots": array(snapshot, 1, 8),
            "assumptions": array(SHORT, 0, 8),
            "limitations": array(SHORT, 0, 8),
            "workflow_version": text(1, 60),
            "prompt_version": text(1, 60),
            "expires_at": UTC_HASHED,
            # Inside the hashed payload, injected by freeze_proposal from runs (AM-13 asset guard, R125); optional.
            "supersedes_run_id": UUID,
        },
        [
            "tenant_id",
            "run_id",
            "proposal_id",
            "revision",
            "action",
            "destination",
            "asset_id",
            "start_at",
            "end_at",
            "title",
            "summary",
            "evidence_refs",
            "source_snapshots",
            "assumptions",
            "limitations",
            "workflow_version",
            "prompt_version",
            "expires_at",
        ],
    )
    return contract(
        "proposal",
        closed(
            {
                "canonicalization_version": {"const": 1},
                "payload": payload,
                "payload_sha256": SHA256,
                # Outside the hash, a sibling of payload: the requester plus revision authors (AM-80 proposal row).
                "authored_by": array(UUID, 1, 8, unique=True),
            },
            ["canonicalization_version", "payload", "payload_sha256", "authored_by"],
        ),
    )


def event() -> Doc:
    """The run event (AM-14): types, payload fields and the rules on who may assert an outcome."""
    payload = closed(
        {
            "message": text(0, 2500),
            "status": {"enum": STATES},
            "evidence_refs": array(EVIDENCE_REF, 0, 8, unique=True),
            "proposal_id": UUID,
            "action_id": UUID,
            "code": text(1, 80),
            "reason": {"type": "string", "enum": REASONS},
            "outcome": {"type": "string", "enum": [ToolOutcome.SUCCEEDED.value, ToolOutcome.FAILED_NO_COMMIT.value]},
            "receipt": RECEIPT,  # replaces 1.0's flat receipt_id/incident_id
            "tombstone": TOMBSTONE,
        },
        [],
    )
    summary_payload = closed(
        {"message": text(1, 2500), "evidence_refs": array(EVIDENCE_REF, 0, 8, unique=True)}, ["message"]
    )
    return contract(
        "event",
        closed(
            {
                "event_id": UUID,
                "tenant_id": UUID,
                "conversation_id": UUID,
                "run_id": UUID,
                "sequence": integer(1),
                "type": {"enum": EVENT_TYPES},
                "occurred_at": DATE_TIME,
                "source": {"enum": ["application", "destination", "model_summary"]},
                "payload": payload,
            },
            [
                "event_id",
                "tenant_id",
                "conversation_id",
                "run_id",
                "sequence",
                "type",
                "occurred_at",
                "source",
                "payload",
            ],
            allOf=[
                # (1) model_summary may emit only explanation.ready, with no status (AM-14, R083).
                when(
                    props(source={"const": "model_summary"}),
                    props(type={"const": EventType.EXPLANATION_READY.value}, payload=summary_payload),
                ),
                # (2) source=destination only on the four destination-evidence types ...
                when(props(source={"const": "destination"}), props(type={"enum": DESTINATION_TYPES})),
                # (3) ... and those four only with source=destination: record_outcome emits them (AM-20.3), and
                # append_event refuses action.* from application callers.
                when(props(type={"enum": DESTINATION_TYPES}), props(source={"const": "destination"})),
                # (4) action.*, run.* and review.* come from the application or the destination (AM-14).
                when(
                    props(type={"pattern": "^(action|run|review)\\."}),
                    props(source={"enum": ["application", "destination"]}),
                ),
                # (5) action.confirmed requires a receipt and SUCCEEDED (AM-14).
                when(
                    props(type={"const": EventType.ACTION_CONFIRMED.value}),
                    props(payload={"required": ["status", "receipt"], **props(status={"const": "SUCCEEDED"})}),
                ),
                # (6) action.late_evidence requires the destination outcome plus a receipt or tombstone (AM-10).
                when(
                    props(type={"const": EventType.ACTION_LATE_EVIDENCE.value}),
                    props(
                        payload={
                            "required": ["outcome"],
                            "anyOf": [{"required": ["receipt"]}, {"required": ["tombstone"]}],
                        }
                    ),
                ),
                # (7) action.failed says why (AM-14 "action.failed (with reason)").
                when(
                    props(type={"const": EventType.ACTION_FAILED.value}),
                    props(payload={"required": ["reason"]}),
                ),
            ],
        ),
    )


def tool_result() -> Doc:
    """The MCP tool-result envelope (AM-15, AM-80 tool-result row)."""
    error_object = closed(
        {"code": text(1, 80), "message": SHORT, "retryable": {"type": "boolean"}}, ["code", "message", "retryable"]
    )
    alert = closed(
        {
            "alert_id": UUID,
            "asset_id": ASSET_ID,
            "occurred_at": DATE_TIME,
            "code": text(1, 80),
            "message": SHORT,
            "revision": integer(1),
        },
        ["alert_id", "asset_id", "occurred_at", "code", "message", "revision"],
    )
    read_data = {
        Tool.GET_ASSET_STATUS.value: closed(
            {
                "asset_id": ASSET_ID,
                "state": {"enum": ["normal", "warning", "unavailable"]},
                "revision": integer(1),
                "observed_at": DATE_TIME,
                "data_source": {"const": "synthetic"},
            },
            ["asset_id", "state", "revision", "observed_at", "data_source"],
        ),
        Tool.GET_RECENT_ALERTS.value: closed(
            {
                "asset_id": ASSET_ID,
                "start_at": DATE_TIME,
                "end_at": DATE_TIME,
                "alerts": array(alert, 0, 100),
                "next_cursor": nullable(text(1, 200)),  # AM-80: pagination is explicit; null on the last page
            },
            ["asset_id", "start_at", "end_at", "alerts", "next_cursor"],
        ),
        Tool.SEARCH_PROCEDURES.value: closed(
            {
                "results": array(EVIDENCE_ROW, 0, 8),
                "retrieval_mode": {"enum": ["lexical", "vector_exact"]},  # plan ruling 3
                "corpus_version": text(1, 100),
            },
            ["results", "retrieval_mode", "corpus_version"],
        ),
    }
    rules: list[Doc] = [
        # An error envelope carries an error and no data; every other envelope carries no error.
        when(props(status={"const": "error"}), props(data=NULL, error=error_object), props(error=NULL)),
        # Read tools answer `ok` (or `error`); their data shapes are checked only on `ok`.
        *(
            when(props(tool_name={"const": name}, status={"const": "ok"}), props(data=shape))
            for name, shape in read_data.items()
        ),
        # Write-tool data shapes apply to both non-error envelopes, `ok` and `outcome` (status ∈ [ok, outcome]):
        # `outcome` is not an error, and its data must still be a well-formed action outcome.
        *(
            when(props(tool_name={"const": name}, status={"enum": ["ok", "outcome"]}), props(data=action_outcome()))
            for name in RECEIPT_TOOLS
        ),
        when(
            props(tool_name={"const": Tool.ABORT_INCIDENT.value}, status={"enum": ["ok", "outcome"]}),
            props(data=abort_outcome()),
        ),
        # (a) A read tool never reports an action outcome.
        when(props(tool_name={"enum": READ_TOOLS}), props(status={"enum": ["ok", "error"]})),
        # (b) `outcome` belongs to write tools and always names the action (AM-80: action_id required on outcomes).
        when(
            props(status={"const": "outcome"}),
            props(tool_name={"enum": WRITE_TOOLS}, data={"type": "object", "required": ["action_id"]}),
        ),
        # (c) Envelope/data agreement (R083): `outcome` never wraps a success ...
        when(
            {**props(status={"const": "outcome"}, tool_name={"enum": RECEIPT_TOOLS}), "required": ["tool_name"]},
            props(data=props(status={"enum": ["UNKNOWN", "CONFLICT", "FAILED_NO_COMMIT"]})),
        ),
        # (d) ... and `ok` wraps nothing but a success: `ok` + UNKNOWN is the R083 probe.
        when(
            {**props(status={"const": "ok"}, tool_name={"enum": RECEIPT_TOOLS}), "required": ["tool_name"]},
            props(data=props(status={"const": "SUCCEEDED"})),
        ),
        # (e) The same agreement for abort_incident: `ok` iff the destination already held a receipt.
        when(
            {
                **props(status={"const": "ok"}, tool_name={"const": Tool.ABORT_INCIDENT.value}),
                "required": ["tool_name"],
            },
            props(data=props(outcome={"const": "SUCCEEDED"})),
        ),
        when(
            {
                **props(status={"const": "outcome"}, tool_name={"const": Tool.ABORT_INCIDENT.value}),
                "required": ["tool_name"],
            },
            props(data=props(outcome={"const": "FAILED_NO_COMMIT"})),
        ),
    ]
    return contract(
        "tool-result",
        closed(
            {
                "tool_name": {"enum": TOOLS},
                "request_id": UUID,
                "status": {"enum": ["ok", "error", "outcome"]},  # 1.0's `unknown` is gone (AM-80)
                "observed_at": DATE_TIME,
                "truncated": {"type": "boolean"},
                "data": {"type": ["object", "null"]},
                "error": nullable(error_object),
            },
            ["tool_name", "request_id", "status", "observed_at", "truncated", "data", "error"],
            allOf=rules,
        ),
    )


def feedback() -> Doc:
    """`POST /runs/{id}/feedback`: classified, stored, never a runtime policy (AM-14, R113)."""
    return contract(
        "feedback",
        closed(
            {
                "subject_kind": {"enum": ["run", "proposal", "event"]},
                "subject_id": UUID,
                "category": {"enum": ["wrong_evidence", "missing_evidence", "wrong_conclusion", "unclear", "other"]},
                "text": text(0, 2000),
            },
            ["subject_kind", "subject_id", "category"],
        ),
    )


def manual_proposal() -> Doc:
    """`POST /manual-proposals`: a request body, so either zero-offset spelling is accepted (ruling 6)."""
    return contract(
        "manual-proposal",
        closed(
            {
                "asset_id": ASSET_ID,
                "start_at": UTC_REQUEST,
                "end_at": UTC_REQUEST,
                "title": text(1, 120),
                "summary": text(1, 2500),
                "evidence_refs": array(EVIDENCE_REF, 1, 8, unique=True),
                "assumptions": array(SHORT, 0, 8),
                "limitations": array(SHORT, 0, 8),
            },
            ["asset_id", "start_at", "end_at", "title", "summary", "evidence_refs", "assumptions", "limitations"],
        ),
    )


def revision() -> Doc:
    """`POST /runs/{id}/revisions` with the requester-asserted supersedes_run_id (AM-10)."""
    return contract(
        "revision", closed({"expected_version": integer(1), "supersedes_run_id": UUID}, ["expected_version"])
    )


def cancel_response() -> Doc:
    """The cancel response reports whether a grant or dispatch already happened; it never claims undo (AM-13)."""
    return contract(
        "cancel-response",
        closed(
            {
                "run_id": UUID,
                "status": {"enum": STATES},
                "state_version": integer(1),
                "cancel_requested": {"type": "boolean"},
                "grant_exists": {"type": "boolean"},
                "attempt_state": nullable({"enum": [a.value for a in AttemptState]}),
                "note": nullable(SHORT),
            },
            ["run_id", "status", "state_version", "cancel_requested", "grant_exists", "attempt_state", "note"],
            allOf=[when(props(grant_exists={"const": False}), props(attempt_state=NULL))],  # no grant, no attempt
        ),
    )


def model_pins() -> Doc:
    """data/model-pins.json (AM-31). Written by scripts/probe.py with `datetime.now(UTC).isoformat()`, i.e. `+00:00`.

    The file is not hashed, so ruling 6's `Z`-only spelling (reserved for hashed documents) does not apply: either
    zero-offset spelling is accepted here. `ops_core.model_pins` accepts any aware timestamp; the schema additionally
    pins a zero offset.
    """
    return contract(
        "model-pins",
        closed(
            {"model": text(1, 200), "digest": DIGEST, "ollama_version": text(1, 80), "probed_at": UTC_REQUEST},
            ["model", "digest", "ollama_version", "probed_at"],
        ),
    )


def route() -> Doc:
    """The three routers' enumerable routes (AM-16); a document names at least one."""
    return contract(
        "route",
        closed(
            {
                "admission": {"enum": [r.value for r in AdmissionRoute]},
                "graph": {"enum": [r.value for r in GraphRoute]},
                "model": {"enum": [r.value for r in ModelRoute]},
            },
            [],
            minProperties=1,
        ),
    )


def run_manifest() -> Doc:
    """What produced a run's draft (AM-80 run-manifest row); mirrored by ops_core.routing.RunManifest."""
    return contract(
        "run-manifest",
        closed(
            {
                "run_id": UUID,
                "model_route": {"enum": [r.value for r in ModelRoute]},
                "model_digest": nullable(DIGEST),
                "prompt_version": text(1, 60),
                "corpus_version": text(1, 100),
                "retrieval_mode": {"enum": ["lexical", "vector_exact"]},
            },
            ["run_id", "model_route", "model_digest", "prompt_version", "corpus_version", "retrieval_mode"],
            # The fake route has nothing to pin; every real model records the digest the worker verified (AM-31).
            allOf=[
                when(
                    props(model_route={"not": {"const": ModelRoute.FAKE.value}}), props(model_digest={"type": "string"})
                )
            ],
        ),
    )


def exactly(values: list[str]) -> Doc:
    """An array (already uniqueItems) holding exactly these values, in any order."""
    if not values:
        return {"maxItems": 0}
    return {"items": {"enum": values}, "minItems": len(values), "maxItems": len(values)}


def job() -> Doc:
    """The AM-15 job-type table as a document: each type's row is generated from ops_core.jobs.JOB_RULES."""
    per_type = [
        when(
            props(type={"const": job_type.value}),
            props(
                allowed_tools=exactly([t.value for t in Tool if t in rule.allowed_tools]),
                run_states=exactly([s.value for s in RunState if s in rule.run_states]),
            ),
        )
        for job_type, rule in JOB_RULES.items()
    ]
    return contract(
        "job",
        closed(
            {
                "type": {"enum": [t.value for t in JOB_RULES]},
                "allowed_tools": {"type": "array", "uniqueItems": True, "items": {"enum": TOOLS}},
                "run_states": {"type": "array", "uniqueItems": True, "items": {"enum": STATES}},
                "created_by": {"type": "array", "items": text(1, 80)},
                "dedup_key": text(1, 200),
            },
            ["type", "allowed_tools", "run_states", "created_by", "dedup_key"],
            allOf=per_type,
        ),
    )


def tool_inputs() -> dict[str, Doc]:
    """Input schemas for the six tools (AM-80 tools row).

    Closed objects: a tool argument never carries tenant_id, actor, role, approval or destination (AM-15); the server
    derives all of them from the invocation handle.
    """

    def tool_input(name: str, properties: Doc, required: list[str]) -> Doc:
        return contract(f"tools/{name}-input", closed(properties, required), f"Operations Copilot tool input {name} v1")

    inputs = {
        Tool.GET_ASSET_STATUS.value: tool_input(Tool.GET_ASSET_STATUS.value, {"asset_id": ASSET_ID}, ["asset_id"]),
        Tool.GET_RECENT_ALERTS.value: tool_input(
            Tool.GET_RECENT_ALERTS.value,
            {
                "asset_id": ASSET_ID,
                "start_at": UTC_REQUEST,  # a request: either zero-offset spelling (ruling 6)
                "end_at": UTC_REQUEST,
                "limit": integer(1, 100),
                "cursor": text(1, 200),
            },
            ["asset_id", "start_at", "end_at", "limit"],
        ),
        Tool.SEARCH_PROCEDURES.value: tool_input(
            Tool.SEARCH_PROCEDURES.value,
            {
                "query": SHORT,
                "asset_type": text(1, 40),
                "limit": integer(1, 8),
                "mode": {"enum": ["lexical", "vector_exact"]},  # ruling 3; mcp-read maps vector_exact (TODO(T15))
            },
            ["query", "limit", "mode"],
        ),
    }
    for name in WRITE_TOOLS:
        inputs[name] = tool_input(name, {"proposal_id": UUID}, ["proposal_id"])
    return inputs


def schemas() -> dict[str, Doc]:
    """Every schema document, keyed by its repository-relative path."""
    top = {
        "message": message(),
        "clarification": clarification(),
        "decision": decision(),
        "cancellation": cancellation(),
        "error": error(),
        "evidence": evidence(),
        "model-draft": model_draft(),
        "proposal": proposal(),
        "action-outcome": contract("action-outcome", action_outcome()),
        "event": event(),
        "tool-result": tool_result(),
        "feedback": feedback(),
        "manual-proposal": manual_proposal(),
        "revision": revision(),
        "cancel-response": cancel_response(),
        "model-pins": model_pins(),
        "route": route(),
        "run-manifest": run_manifest(),
        "job": job(),
    }
    out = {f"schemas/{name}.schema.json": doc for name, doc in top.items()}
    out |= {f"schemas/tools/{name}.input.schema.json": doc for name, doc in tool_inputs().items()}
    return out


# --- Examples. Synthetic IDs and fixed times, as delivered in 1.0; T21's fixtures use the seed ids, not these. ---
TENANT = "00000000-0000-4000-8000-000000000001"
CONVERSATION = "00000000-0000-4000-8000-000000000002"
RUN = "00000000-0000-4000-8000-000000000003"
PROPOSAL = "00000000-0000-4000-8000-000000000004"
QUESTION = "00000000-0000-4000-8000-000000000005"
EVENT = "00000000-0000-4000-8000-000000000006"
ACTION = "00000000-0000-4000-8000-000000000007"
RECEIPT_ID = "00000000-0000-4000-8000-000000000008"
REQUEST = "00000000-0000-4000-8000-000000000009"
AUTHOR = "00000000-0000-4000-8000-00000000000a"  # proposal-valid's authored_by: a placeholder, not a seed persona
CLOCK = "2026-10-06T12:00:00Z"  # the fixture clock (data/handoff-fixtures/observations.json)
EVIDENCE_ID = "ALPHA-INCIDENT:v2:review"
# The whole-file hash of the ALPHA-INCIDENT fixture, as delivered. TODO(T17): evidence rows switch to the per-section
# hash from data/handoff-fixtures/meta.json when T17 consumes it.
EVIDENCE_SHA = "8bc7631462663afea7fb457da5159c99f9ef3d3cffe21056d487c45c55931c4a"
EXCERPT = (
    "Repeated simulated warnings may be summarized in a reviewable incident draft. A different authorized reviewer "
    "must inspect the exact content before submission. The warning count alone does not establish root cause."
)
DRAFT_TITLE = "Review repeated synthetic warnings on A17"
DRAFT_SUMMARY = (
    "The supplied synthetic records contain two warnings within the requested interval. An independent reviewer "
    "should inspect the incident draft. Root cause is not established."
)
LIMITATIONS = ["Synthetic data only.", "Root cause is not established."]
COMMITTED_AT = "2026-10-06T12:04:00Z"


def payload() -> Doc:
    """The hashed payload of proposal-valid.json; its hash is computed here, never typed in."""
    return {
        "tenant_id": TENANT,
        "run_id": RUN,
        "proposal_id": PROPOSAL,
        "revision": 1,
        "action": "create_incident",
        "destination": "synthetic-incidents",
        "asset_id": "A17",
        "start_at": "2026-10-05T12:00:00Z",
        "end_at": CLOCK,
        "title": DRAFT_TITLE,
        "summary": DRAFT_SUMMARY,
        "evidence_refs": [EVIDENCE_ID],
        "source_snapshots": [{"evidence_id": EVIDENCE_ID, "content_sha256": EVIDENCE_SHA, "version": "2"}],
        "assumptions": [],
        "limitations": LIMITATIONS,
        "workflow_version": "investigation-v1",
        "prompt_version": "incident-draft-v1",
        "expires_at": "2026-10-06T12:15:00Z",
    }


PAYLOAD_SHA = canonical_sha256(payload())  # 9d5c1fb0…4cf7, unchanged from 1.0 (the payload is ASCII)


def envelope(tool: str, status: str, data: Doc | None, error: Doc | None = None) -> Doc:
    """A tool-result envelope with the fixed request id and fixture clock."""
    return {
        "tool_name": tool,
        "request_id": REQUEST,
        "status": status,
        "observed_at": CLOCK,
        "truncated": False,
        "data": data,
        "error": error,
    }


def outcome(status: str, *, receipt: Doc | None = None, tombstone: Doc | None = None, reason: str | None = None) -> Doc:
    """An action outcome for the example action."""
    return {
        "status": status,
        "action_id": ACTION,
        "payload_sha256": PAYLOAD_SHA,
        "receipt": receipt,
        "tombstone": tombstone,
        "reason": reason,
    }


def event_doc(source: str, payload: Doc, event_type: str = EventType.ACTION_CONFIRMED.value) -> Doc:
    """An event envelope for the example run."""
    return {
        "event_id": EVENT,
        "tenant_id": TENANT,
        "conversation_id": CONVERSATION,
        "run_id": RUN,
        "sequence": 8,
        "type": event_type,
        "occurred_at": "2026-10-06T12:04:01Z",
        "source": source,
        "payload": payload,
    }


def examples(root: Path = ROOT) -> list[tuple[Doc, Doc]]:
    """(index entry, document) for every example, in index order: the delivered 29, then 10 new valid, 27 invalid.

    Reads only data/handoff-fixtures/{meta,observations}.json (the two in-window alerts, AM-80 row "draft/alerts
    consistency") under `root`.
    """
    meta = json.loads((root / "data/handoff-fixtures/meta.json").read_text(encoding="utf-8"))
    observations = json.loads((root / "data/handoff-fixtures/observations.json").read_text(encoding="utf-8"))
    alert_ids = {a["id"]: a["alert_id"] for a in meta["alerts"]}
    receipt = {"receipt_id": RECEIPT_ID, "incident_id": "INC-SYNTHETIC-0001", "committed_at": COMMITTED_AT}
    tombstone = {
        "action_id": ACTION,
        "state": DestinationState.ABORTED.value,
        "payload_sha256": PAYLOAD_SHA,
        "reason": "cancelled before send",
        "decided_at": COMMITTED_AT,
    }
    message_valid = {
        "kind": "investigate",
        "text": "Investigate the alerts on A17 over the last 24 hours.",
        "context": {"asset_id": "A17", "hours": 24},
    }
    draft = {
        "kind": "proposal",
        "title": DRAFT_TITLE,
        "summary": DRAFT_SUMMARY,
        "evidence_refs": [EVIDENCE_ID],
        "assumptions": [],
        "limitations": LIMITATIONS,
    }
    decision_valid = {
        "expected_revision": 1,
        "expected_payload_sha256": PAYLOAD_SHA,
        "decision": "approve",
        "reason": "Reviewed the exact synthetic proposal.",
    }
    proposal_valid = {
        "canonicalization_version": 1,
        "payload": payload(),
        "payload_sha256": PAYLOAD_SHA,
        "authored_by": [AUTHOR],  # synthetic, like the payload's tenant/run/proposal ids
    }
    receipt_unknown = envelope(Tool.GET_INCIDENT_RECEIPT.value, "outcome", outcome("UNKNOWN"))
    event_valid = event_doc("destination", {"status": "SUCCEEDED", "action_id": ACTION, "receipt": receipt})
    in_window = [a for a in observations["alerts"] if a["id"] in ("A17-alert-001", "A17-alert-002")]
    alerts = [
        {
            "alert_id": alert_ids[a["id"]],
            "asset_id": a["asset_id"],
            "occurred_at": a["occurred_at"],
            "code": a["code"],
            "message": a["message"],
            "revision": 1,
        }
        for a in in_window
    ]
    feedback_valid = {
        "subject_kind": "proposal",
        "subject_id": PROPOSAL,
        "category": "wrong_evidence",
        "text": "Cites the superseded version.",
    }
    manual_valid = {
        "asset_id": "A17",
        "start_at": "2026-10-05T12:00:00Z",
        "end_at": CLOCK,
        "title": DRAFT_TITLE,
        "summary": "Two synthetic warnings in the interval.",
        "evidence_refs": [EVIDENCE_ID],
        "assumptions": [],
        "limitations": ["Synthetic data only."],
    }
    cancel_valid = {
        "run_id": RUN,
        "status": "EXECUTING",
        "state_version": 4,
        "cancel_requested": True,
        "grant_exists": True,
        "attempt_state": "SENT",
        "note": "cancellation arrived after dispatch",
    }
    pins_valid = {
        "model": "qwen3:8b",
        "digest": "ab" * 32,
        "ollama_version": "0.12.3",
        "probed_at": "2026-10-08T00:00:00Z",
    }
    manifest_valid = {
        "run_id": RUN,
        "model_route": "fake",
        "model_digest": None,
        "prompt_version": "incident-draft-v1",
        "corpus_version": "fixture-1",
        "retrieval_mode": "lexical",
    }
    failed = outcome("FAILED_NO_COMMIT", tombstone=tombstone, reason="cancelled_before_send")
    asset_status = envelope(
        Tool.GET_ASSET_STATUS.value,
        "ok",
        {"asset_id": "A17", "state": "warning", "revision": 1, "observed_at": CLOCK, "data_source": "synthetic"},
    )
    error_valid = {
        "code": "VERSION_CONFLICT",
        "message": "The proposal has changed. Reload the current revision.",
        "retryable": False,
        "request_id": REQUEST,
    }

    items: list[tuple[Doc, Doc]] = []

    def valid(name: str, schema: str, doc: Doc, note: str = NOTE) -> None:
        entry = {"path": f"schemas/examples/{name}.json", "schema": f"schemas/{schema}.schema.json", "valid": True}
        items.append((entry | {"note": note}, doc))

    def invalid(name: str, schema: str, doc: Doc, reason: str, reason_match: str) -> None:
        # reason_match is anchored on the JSON path of jsonschema's best_match error ("<path>: <message>"), so a
        # negative that fails somewhere else cannot pass for the stated reason (R104); alternations only cover
        # wording that differs between jsonschema versions or two errors at the same path.
        entry = {"path": f"schemas/examples/{name}.json", "schema": f"schemas/{schema}.schema.json", "valid": False}
        items.append((entry | {"note": NOTE, "reason": reason, "reason_match": reason_match}, doc))

    # The delivered 1.0 examples, in their delivered order, updated to the 1.3.6 contract.
    valid("message-valid", "message", message_valid)
    valid(
        "message-clarification-needed",
        "message",
        {"kind": "investigate", "text": "Investigate A17.", "context": {"asset_id": "A17"}},
    )
    invalid(
        "message-invalid-authority",
        "message",
        {"kind": "investigate", "text": "Do it.", "tenant_id": TENANT},
        "A client may not supply tenant_id (R004).",
        "^\\$: Additional properties are not allowed \\('tenant_id'",
    )
    invalid(
        "message-invalid-bool-hours",
        "message",
        {"kind": "investigate", "text": "Check A17.", "context": {"asset_id": "A17", "hours": True}},
        "hours must be an integer, never a boolean.",
        "^\\$\\.context\\.hours: True is not of type 'integer'$",
    )
    valid(
        "clarification-valid",
        "clarification",
        {"question_id": QUESTION, "expected_version": 2, "context": {"asset_id": "A17", "hours": 24}},
    )
    valid("draft-valid", "model-draft", draft)
    valid(
        "draft-abstain-valid",
        "model-draft",
        {
            "kind": "abstain",
            "title": "No suitable approved evidence",
            "summary": "No permitted approved procedure was returned for this investigation.",
            "evidence_refs": [],
            "assumptions": [],
            "limitations": ["Cannot prepare an evidence-backed incident."],
        },
    )
    invalid(
        "draft-invalid-approval",
        "model-draft",
        {**draft, "approved": True},
        "A model may not assert approval.",
        "^\\$: Additional properties are not allowed \\('approved'",
    )
    invalid(
        "draft-invalid-no-evidence",
        "model-draft",
        {**draft, "evidence_refs": []},
        "A proposal cites at least one piece of evidence.",
        "^\\$\\.evidence_refs: \\[\\] (is too short|should be non-empty)$",
    )
    invalid(
        "draft-invalid-duplicate-evidence",
        "model-draft",
        {**draft, "evidence_refs": [EVIDENCE_ID, EVIDENCE_ID]},
        "Evidence references are unique.",
        "^\\$\\.evidence_refs: .* has non-unique elements$",
    )
    valid(
        "evidence-valid",
        "evidence",
        {
            "evidence_id": EVIDENCE_ID,
            "document_id": "ALPHA-INCIDENT",
            "version": "2",
            "section": "review",
            "content_sha256": EVIDENCE_SHA,
            "excerpt": EXCERPT,
            "effective_from": "2026-10-01T00:00:00Z",
            "retrieved_at": CLOCK,
        },
    )
    valid("proposal-valid", "proposal", proposal_valid)
    valid("decision-valid", "decision", decision_valid)
    invalid(
        "decision-invalid-actor",
        "decision",
        {"expected_revision": 1, "expected_payload_sha256": PAYLOAD_SHA, "decision": "approve", "actor_id": "sam"},
        "The reviewer is the session, never a body field.",
        "^\\$: Additional properties are not allowed \\('actor_id'",
    )
    valid("cancellation-valid", "cancellation", {"expected_version": 4, "reason": "Stop pending work."})
    valid("outcome-success-valid", "action-outcome", outcome("SUCCEEDED", receipt=receipt))
    valid("outcome-unknown-valid", "action-outcome", outcome("UNKNOWN"))
    invalid(
        "outcome-invalid-fake-success",
        "action-outcome",
        outcome("SUCCEEDED"),
        "SUCCEEDED without a receipt is a fake success.",
        "^\\$\\.receipt: None is not of type 'object'$",
    )
    invalid(
        "outcome-invalid-unknown-receipt",
        "action-outcome",
        outcome("UNKNOWN", receipt=receipt),
        "A receipt on UNKNOWN would claim a commit nobody verified.",
        "^\\$\\.receipt: .* is not of type 'null'$",
    )
    valid("tool-get_asset_status-valid", "tool-result", asset_status)
    valid(
        "tool-get_recent_alerts-valid",
        "tool-result",
        envelope(
            Tool.GET_RECENT_ALERTS.value,
            "ok",
            {
                "asset_id": "A17",
                "start_at": "2026-10-05T12:00:00Z",
                "end_at": CLOCK,
                "alerts": alerts,
                "next_cursor": None,
            },
        ),
    )
    valid(
        "tool-search_procedures-valid",
        "tool-result",
        envelope(
            Tool.SEARCH_PROCEDURES.value,
            "ok",
            {
                "results": [
                    {
                        "evidence_id": EVIDENCE_ID,
                        "document_id": "ALPHA-INCIDENT",
                        "version": "2",
                        "section": "review",
                        "content_sha256": EVIDENCE_SHA,
                        "excerpt": EXCERPT,
                        "effective_from": "2026-10-01T00:00:00Z",
                        "retrieved_at": CLOCK,
                    }
                ],
                "retrieval_mode": "lexical",
                "corpus_version": "fixture-1",
            },
        ),
    )
    valid(
        "tool-create_incident-valid",
        "tool-result",
        envelope(Tool.CREATE_INCIDENT.value, "ok", outcome("SUCCEEDED", receipt=receipt)),
    )
    valid("tool-get_incident_receipt-valid", "tool-result", receipt_unknown)
    valid(
        "tool-error-valid",
        "tool-result",
        envelope(
            Tool.GET_ASSET_STATUS.value,
            "error",
            None,
            {"code": "FORBIDDEN", "message": "This operation is not available.", "retryable": False},
        ),
    )
    valid("event-valid", "event", event_valid)
    invalid(
        "event-invalid-model-success",
        "event",
        event_doc("model_summary", event_valid["payload"]),
        "model_summary may emit only explanation.ready, never an outcome (R083).",
        "^\\$\\.type: 'explanation\\.ready' was expected$",
    )
    valid("error-valid", "error", error_valid)
    valid(
        "draft-answer-valid",
        "model-draft",
        {
            "kind": "answer",
            "title": "Summary of synthetic A17 observations",
            "summary": DRAFT_SUMMARY,
            "evidence_refs": [EVIDENCE_ID],
            "assumptions": [],
            "limitations": LIMITATIONS,
        },
        "Synthetic read-only answer shape, not a write or actual model result.",
    )

    # New positive examples (one per new schema, plus abort_incident and one tool input).
    valid("feedback-valid", "feedback", feedback_valid)
    valid("manual-proposal-valid", "manual-proposal", manual_valid)
    valid("revision-valid", "revision", {"expected_version": 3, "supersedes_run_id": RUN})
    valid("cancel-response-valid", "cancel-response", cancel_valid)
    valid("model-pins-valid", "model-pins", pins_valid)
    valid("route-valid", "route", {"admission": "investigate", "graph": "retrieve", "model": "fake"})
    valid("run-manifest-valid", "run-manifest", manifest_valid)
    valid(
        "job-valid",
        "job",
        {
            "type": "recover",
            "allowed_tools": WRITE_TOOLS,
            "run_states": ["EXECUTING", "OUTCOME_UNKNOWN", "ESCALATED", "ABANDONED_UNVERIFIED"],
            "created_by": ["mark_unknown", "worker", "reclaim_leases"],
            "dedup_key": f"{ACTION}:timeout",
        },
    )
    valid(
        "tool-abort_incident-valid",
        "tool-result",
        envelope(
            Tool.ABORT_INCIDENT.value,
            "outcome",
            {"action_id": ACTION, "outcome": "FAILED_NO_COMMIT", "receipt": None, "tombstone": tombstone},
        ),
    )
    valid("tools-create_incident-input-valid", "tools/create_incident.input", {"proposal_id": PROPOSAL})

    # Negative probes: one per AM-80 row, each derived from a valid example with exactly one change.
    no_receipt = copy.deepcopy(event_valid)
    del no_receipt["payload"]["receipt"]
    invalid(
        "event-invalid-confirmed-no-receipt",
        "event",
        no_receipt,
        "action.confirmed requires a receipt (R083).",
        "^\\$\\.payload: 'receipt' is a required property$",
    )
    invalid(
        "event-invalid-destination-granted",
        "event",
        event_doc("destination", {"status": "EXECUTING", "action_id": ACTION}, EventType.ACTION_GRANTED.value),
        "source=destination only on the four destination-evidence types.",
        "^\\$\\.type: 'action\\.granted' is not one of",
    )
    invalid(
        "event-invalid-late-evidence-no-outcome",
        "event",
        event_doc("destination", {"action_id": ACTION, "tombstone": tombstone}, EventType.ACTION_LATE_EVIDENCE.value),
        "action.late_evidence requires the destination outcome.",
        "^\\$\\.payload: 'outcome' is a required property$",
    )
    invalid(
        "event-invalid-confirmed-application-source",
        "event",
        {**event_valid, "source": "application"},
        "action.confirmed comes only from record_outcome with source=destination.",
        "^\\$\\.source: 'destination' was expected$",
    )
    invalid(
        "event-invalid-occurred-at",
        "event",
        {**event_valid, "occurred_at": "yesterday"},
        "occurred_at must be an RFC 3339 date-time (FormatChecker with rfc3339-validator).",
        "^\\$\\.occurred_at: 'yesterday' is not a 'date-time'$",
    )
    invalid(
        "tool-invalid-ok-unknown",
        "tool-result",
        {**receipt_unknown, "status": "ok"},
        "Envelope ok must wrap a success, never UNKNOWN (R083).",
        "^\\$\\.data\\.status: ('SUCCEEDED' was expected|'UNKNOWN' is not one of \\['SUCCEEDED'\\])$",
    )
    no_action = copy.deepcopy(receipt_unknown)
    del no_action["data"]["action_id"]
    invalid(
        "tool-invalid-outcome-no-action-id",
        "tool-result",
        no_action,
        "An outcome always names its action (R083).",
        "^\\$\\.data: 'action_id' is a required property$",
    )
    invalid(
        "tool-invalid-status-unknown",
        "tool-result",
        {**envelope(Tool.CREATE_INCIDENT.value, "ok", outcome("SUCCEEDED", receipt=receipt)), "status": "unknown"},
        "The 1.0 envelope status unknown is gone (probed on a create_incident success).",
        "^\\$\\.status: 'unknown' is not one of",
    )
    invalid(
        "tool-invalid-read-tool-outcome",
        "tool-result",
        {**asset_status, "status": "outcome"},
        "A read tool cannot return an outcome envelope: rule (b) restricts `outcome` to the write tools.",
        "^\\$\\.tool_name: 'get_asset_status' is not one of",
    )
    invalid(
        "draft-invalid-empty-question",
        "model-draft",
        {**draft, "kind": "abstain", "evidence_refs": [], "question": ""},
        "An empty question is no question.",
        "^\\$\\.question: '' (is too short|should be non-empty)$",
    )
    invalid(
        "draft-invalid-question-on-proposal",
        "model-draft",
        {**draft, "question": "Which interval?"},
        "Only an abstain carries a question.",
        "^\\$: .* should not be valid under \\{'required': \\['question'\\]\\}$",
    )
    invalid(
        "feedback-invalid-authority",
        "feedback",
        {**feedback_valid, "actor_id": TENANT},
        "A client may not supply actor_id (R004).",
        "^\\$: Additional properties are not allowed \\('actor_id'",
    )
    invalid(
        "manual-proposal-invalid-authored-by",
        "manual-proposal",
        {**manual_valid, "authored_by": [TENANT]},
        "authored_by is derived by the server, never supplied.",
        "^\\$: Additional properties are not allowed \\('authored_by'",
    )
    invalid(
        "revision-invalid-supersedes",
        "revision",
        {"expected_version": 3, "supersedes_run_id": "run-7"},
        "supersedes_run_id is a run UUID.",
        "^\\$\\.supersedes_run_id: 'run-7' is not a 'uuid'$",
    )
    invalid(
        "cancel-response-invalid-attempt-without-grant",
        "cancel-response",
        {**cancel_valid, "grant_exists": False},
        "An attempt state exists only after a grant.",
        "^\\$\\.attempt_state: 'SENT' is not of type 'null'$",
    )
    invalid(
        "error-invalid-unknown-code",
        "error",
        {**error_valid, "code": "OOPS"},
        "Error codes come from the documented set.",
        "^\\$\\.code: 'OOPS' is not one of",
    )
    invalid(
        "tools-create_incident-input-invalid-tenant",
        "tools/create_incident.input",
        {"proposal_id": PROPOSAL, "tenant_id": TENANT},
        "Tool arguments never carry tenant_id (AM-15).",
        "^\\$: Additional properties are not allowed \\('tenant_id'",
    )
    invalid(
        "outcome-invalid-failed-reason",
        "action-outcome",
        {**failed, "reason": "conflict"},
        "conflict is not a FAILED_NO_COMMIT reason.",
        "^\\$\\.reason: 'conflict' is not one of",
    )
    invalid(
        "outcome-invalid-committed-tombstone",
        "action-outcome",
        {**failed, "tombstone": {**tombstone, "state": "COMMITTED"}},
        "A COMMITTED key has a receipt, not a tombstone.",
        "^\\$\\.tombstone\\.state: 'COMMITTED' is not one of",
    )
    invalid(
        "model-pins-invalid-prefixed-digest",
        "model-pins",
        {**pins_valid, "digest": "sha256:" + "ab" * 32},
        "The digest is bare hex (AM-31).",
        "^\\$\\.digest: '.*' does not match",
    )
    invalid(
        "message-invalid-kind-question",
        "message",
        {**message_valid, "kind": "question"},
        "The 1.0 kind question is gone.",
        "^\\$\\.kind: 'question' is not one of",
    )
    invalid(
        "run-manifest-invalid-model-route",
        "run-manifest",
        {**manifest_valid, "model_route": "gpt"},
        "Unknown model route.",
        "^\\$\\.model_route: 'gpt' is not one of",
    )
    invalid(
        "job-invalid-execute-read-tool",
        "job",
        {
            "type": "execute",
            "allowed_tools": [Tool.GET_RECENT_ALERTS.value],
            "run_states": ["APPROVED", "EXECUTING"],
            "created_by": ["record_decision"],
            "dedup_key": PROPOSAL,
        },
        "An execute job may call only create_incident.",
        "^\\$\\.allowed_tools\\[0\\]: 'get_recent_alerts' is not one of",
    )
    old_hash = {("payload_sha256" if k == "expected_payload_sha256" else k): v for k, v in decision_valid.items()}
    invalid(
        "decision-invalid-old-hash-field",
        "decision",
        old_hash,
        "The 1.0 field name payload_sha256 is gone (AM-11).",
        "^\\$: (Additional properties are not allowed \\('payload_sha256'"
        "|'expected_payload_sha256' is a required property)",
    )
    in_payload = copy.deepcopy(proposal_valid)
    in_payload["payload"]["authored_by"] = proposal_valid["authored_by"]
    invalid(
        "proposal-invalid-authored-by-in-payload",
        "proposal",
        in_payload,
        "authored_by sits outside the hashed payload.",
        "^\\$\\.payload: Additional properties are not allowed \\('authored_by'",
    )
    non_utc = copy.deepcopy(proposal_valid)
    non_utc["payload"]["start_at"] = "2026-10-05T14:00:00+02:00"
    invalid(
        "proposal-invalid-non-utc",
        "proposal",
        non_utc,
        "A stored proposal spells UTC as Z (ruling 6).",
        "^\\$\\.payload\\.start_at: '2026-10-05T14:00:00\\+02:00' does not match",
    )
    invalid(
        "tool-get_incident_receipt-invalid-unknown",
        "tool-result",
        {**receipt_unknown, "status": "unknown"},
        "The 1.0 receipt example's envelope unknown is gone.",
        "^\\$\\.status: 'unknown' is not one of",
    )
    return items


def build(root: Path = ROOT) -> dict[str, Doc]:
    """Every generated file, keyed by repository-relative path, in a fixed order."""
    files = schemas()
    entries = []
    for entry, doc in examples(root):
        files[entry["path"]] = doc
        entries.append(entry)
    files["schemas/examples/index.json"] = {"specification": "OPS-BUILD-1.3.6", "version": "1.3.3", "examples": entries}
    return files


def render(doc: Doc) -> bytes:
    """The committed byte form: two-space indent, non-ASCII kept, LF, trailing newline, no BOM."""
    return (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def write(out: Path, root: Path = ROOT) -> dict[str, int]:
    """Write every generated file under `out` (the repository root, or a temporary directory for the drift test).

    Returns:
        Counts of what was written: schemas, tool-input schemas, valid and invalid examples.
    """
    files = build(root)
    for rel, doc in files.items():
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(render(doc))  # bytes, so no platform newline translation can add a CR
    index = files["schemas/examples/index.json"]["examples"]
    return {
        "schemas": sum(1 for rel in files if rel.endswith(".schema.json") and "/tools/" not in rel),
        "tool_inputs": sum(1 for rel in files if "/tools/" in rel),
        "valid": sum(1 for e in index if e["valid"]),
        "invalid": sum(1 for e in index if not e["valid"]),
    }


def main() -> None:
    """Regenerate schemas/ in the repository and print the counts."""
    n = write(ROOT)
    print(
        f"schemas/: {n['schemas'] + n['tool_inputs']} schema documents ({n['schemas']} contracts, {n['tool_inputs']} "
        f"tool inputs); {n['valid'] + n['invalid']} examples ({n['valid']} valid, {n['invalid']} invalid); "
        "index.json version 1.3.3"
    )


if __name__ == "__main__":
    main()

"""Structural validation of what a drafting model returned (T19; BUILD_SPEC §12 level 1, BS:449-452; R036, R039, R040).

`validate` takes the reply exactly as the model produced it, its text and any reasoning metadata, and returns a
`ModelDraft` or raises `DraftInvalid`. Nothing is repaired, stripped or coerced here: the caller decides whether the
one bounded repair runs (`ops_worker.ollama_drafting`). The checks, in order, each with the rule name it reports:

- `thinking`: a `<think>` tag in the text, or any reasoning content beside it. `reasoning=False` should make this
  impossible (SA:596); when it happens the reply is refused whole, never stripped and accepted (BS:460, R039).
- `not_json`: the text is not one JSON object under the strict parser the proposal hash uses (no repeated key, no
  NaN; `canonical.parse_json_strict`).
- `authority_key`: a top-level key that names an authority field (`contracts.AUTHORITY_FIELDS`) or one only the
  application sets on a proposal. The schema would refuse it as an extra key too; the rule name makes the attempt
  visible (R036).
- `schema`: `schemas/model-draft.schema.json`, the file T23's `grading.check_schema` reads.
- `contract`: `ModelDraft`, which also refuses what the schema cannot see (a whitespace-only title).
- `not_offered`: a cited evidence ID that this run did not offer (citation membership, BS:451).
- `proposal_on_answer_only`: a proposal for a request the router admitted as `answer_only` (SA:153).

The feedback for the repair names a JSON path and a rule per line, at most `MAX_FEEDBACK` lines, and never repeats the
instance: the T02 probe sent jsonschema's messages, which embed the whole draft, and its repair fixed nothing
(`reports/model-probe-qwen3-8b.md`). Paths are built from schema property names and list indexes only, because the
draft object is closed: no key the model chose can reach a path. Pure: no model, network, database or clock.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Iterable, Mapping
from typing import Any, Final, Literal

from jsonschema import Draft202012Validator
from pydantic import ValidationError

from ops_core import contracts, grading
from ops_core.canonical import CanonicalizationError, parse_json_strict
from ops_core.contracts import AUTHORITY_FIELDS, ModelDraft

MAX_FEEDBACK: Final = 10
# Keys only the application writes into a proposal (`ops_worker.proposals.build_proposal`) or that bind it to other
# rows; a draft naming one is trying to set it.
APPLICATION_KEYS: Final = frozenset(
    {"action", "action_id", "approval", "permissions", "proposal_id", "run_id", "status", "supersedes_run_id", "tool"}
)
Rule = Literal[
    "thinking",
    "not_json",
    "authority_key",
    "schema",
    "contract",
    "not_offered",
    "proposal_on_answer_only",
]


class DraftInvalid(ValueError):
    """The reply is not an acceptable draft. `rules` name what failed (for logs and reports); `feedback` is the
    instance-free text the repair attempt may be shown."""

    def __init__(self, rules: Iterable[Rule], feedback: Iterable[str]) -> None:
        self.rules: tuple[Rule, ...] = tuple(dict.fromkeys(rules))
        self.feedback: tuple[str, ...] = tuple(feedback)[:MAX_FEEDBACK]
        super().__init__(", ".join(self.rules))


@functools.cache
def _schema() -> Draft202012Validator:
    return Draft202012Validator(json.loads(grading.DRAFT_SCHEMA.read_text(encoding="utf-8")))


def has_thinking(text: str, reasoning: object) -> bool:
    """A thinking tag in the text, or reasoning content in the metadata (`scripts/probe_stats.has_thinking`'s rule)."""
    return "<think>" in text or "</think>" in text or bool(reasoning)


def _path(parts: Iterable[str | int]) -> str:
    return "/" + "/".join(str(p) for p in parts)


def _schema_line(error: Any) -> str:
    """One feedback line for a jsonschema error, from the schema's side only (keyword and limit, never the value)."""
    where = list(error.absolute_path)
    keyword, limit = error.validator, error.validator_value
    if keyword == "required":
        missing = [name for name in limit if not (isinstance(error.instance, dict) and name in error.instance)]
        return f"{_path(where)}: required field missing: {', '.join(missing)}"
    if keyword == "additionalProperties":
        allowed = ", ".join(_schema().schema["properties"])
        return f"{_path(where)}: only these fields are allowed: {allowed}"
    if keyword == "not" and limit == {"required": ["question"]}:
        return f"{_path([*where, 'question'])}: allowed only with kind abstain; leave it out"
    if keyword in {"minLength", "maxLength", "minItems", "maxItems", "type", "enum", "const"}:
        return f"{_path(where)}: {keyword} {json.dumps(limit)}"
    return f"{_path(where)}: {keyword}"  # uniqueItems and anything else: the keyword alone


def _contract_line(error: Mapping[str, Any]) -> str:
    """One feedback line for a pydantic error: its location (field names, indexes) and its error type."""
    return f"{_path(p for p in error['loc'] if isinstance(p, str | int))}: {error['type']}"


def validate(text: str, *, reasoning: object, allowed_ids: frozenset[str], answer_only: bool) -> ModelDraft:
    """Accept the reply as a `ModelDraft` only if every check passes.

    Args:
        text: the model's reply text, unmodified.
        reasoning: the reply's reasoning metadata (LangChain's `reasoning_content`), or None.
        allowed_ids: the evidence IDs this run offered the model.
        answer_only: the run's intent is `answer_only`, where no proposal may be drafted.

    Raises:
        DraftInvalid: with every rule that failed at the first stage that failed.
    """
    if has_thinking(text, reasoning):
        raise DraftInvalid(["thinking"], ["/: thinking content is not allowed; return only the JSON object"])
    try:
        doc = parse_json_strict(text)
    except CanonicalizationError:
        doc = None
    if not isinstance(doc, dict):
        raise DraftInvalid(["not_json"], ["/: the reply is not one JSON object (each key once)"])
    claimed = sorted(set(doc) & (AUTHORITY_FIELDS | APPLICATION_KEYS))
    if claimed:
        raise DraftInvalid(["authority_key"], [f"/{k}: field not allowed; the application sets it" for k in claimed])
    errors = sorted(_schema().iter_errors(doc), key=lambda e: [str(p) for p in e.absolute_path])
    if errors:
        raise DraftInvalid(["schema"], dict.fromkeys(_schema_line(e) for e in errors))
    try:
        draft = contracts.load(ModelDraft, text)
    except ValidationError as exc:
        raise DraftInvalid(["contract"], dict.fromkeys(_contract_line(e) for e in exc.errors())) from None
    unknown = [i for i, ref in enumerate(draft.evidence_refs) if ref not in allowed_ids]
    if unknown:
        raise DraftInvalid(["not_offered"], [f"/evidence_refs/{i}: not one of allowed_evidence_ids" for i in unknown])
    if answer_only and draft.kind == "proposal":
        raise DraftInvalid(["proposal_on_answer_only"], ["/kind: this request allows only answer or abstain"])
    return draft

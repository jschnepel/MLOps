"""Every example in schemas/examples/index.json gets the same verdict from the pydantic contract as from its schema.

Catches: a schema rule with no code counterpart (a model would accept what the API rejects) or the reverse, and an
example edited on one side only. Schemas without a pydantic model (tool-result envelopes, tool inputs, job, route)
are listed in NO_MODEL with the reason; they are covered by --contracts alone. Event envelopes have no pydantic model
yet (T14 writes events); their code-side checks are `event_rules_ok` plus a strict parse of `occurred_at`.
"""

import json
from pathlib import Path

import pytest
from ops_core import contracts as c
from ops_core.model_pins import ModelPins
from ops_core.outcomes import ActionOutcome, EventRuleViolation, EventSource, EventType, event_rules_ok
from ops_core.routing import RunManifest
from pydantic import AwareDatetime, BaseModel, TypeAdapter, ValidationError

INDEX = json.loads(Path("schemas/examples/index.json").read_text(encoding="utf-8"))
MODELS: dict[str, type[BaseModel]] = {
    "schemas/message.schema.json": c.MessageRequest,
    "schemas/clarification.schema.json": c.ClarificationReply,
    "schemas/decision.schema.json": c.DecisionRequest,
    "schemas/cancellation.schema.json": c.CancelRequest,
    "schemas/model-draft.schema.json": c.ModelDraft,
    "schemas/proposal.schema.json": c.Proposal,
    "schemas/action-outcome.schema.json": ActionOutcome,
    "schemas/error.schema.json": c.SafeError,
    "schemas/feedback.schema.json": c.FeedbackRequest,
    "schemas/manual-proposal.schema.json": c.ManualProposalRequest,
    "schemas/revision.schema.json": c.RevisionRequest,
    "schemas/cancel-response.schema.json": c.CancelResponse,
    "schemas/model-pins.schema.json": ModelPins,
    "schemas/run-manifest.schema.json": RunManifest,
}
NO_MODEL = {
    "schemas/tool-result.schema.json": (
        "envelopes are built by the MCP servers (T15/T47); the data shapes are ActionOutcome"
    ),
    "schemas/evidence.schema.json": "retrieval rows are produced by mcp-read (T17)",
    "schemas/route.schema.json": "enums only; the table is pinned in test_jobs_routes_outcomes",
    "schemas/job.schema.json": "JOB_RULES is pinned in test_jobs_routes_outcomes, the example by --contracts",
}
EVENT = "schemas/event.schema.json"
TIMESTAMP = TypeAdapter(AwareDatetime)


def _event_checks(doc: dict) -> None:
    TIMESTAMP.validate_json(json.dumps(doc["occurred_at"]))  # ValidationError is a ValueError
    event_rules_ok(EventType(doc["type"]), EventSource(doc["source"]), doc["payload"])


@pytest.mark.parametrize("item", INDEX["examples"], ids=[e["path"].rsplit("/", 1)[-1] for e in INDEX["examples"]])
def test_code_and_schema_agree(item):
    text = Path(item["path"]).read_text(encoding="utf-8")
    schema = item["schema"]
    if schema.startswith("schemas/tools/") or schema in NO_MODEL:
        pytest.skip(NO_MODEL.get(schema, "tool input schema: enforced by the MCP server's argument validation (T15)"))
    if schema == EVENT:
        doc = json.loads(text)
        if item["valid"]:
            _event_checks(doc)
        else:
            with pytest.raises((EventRuleViolation, ValueError)):
                _event_checks(doc)
        return
    model = MODELS[schema]
    if item["valid"]:
        model.model_validate_json(text)
    else:
        with pytest.raises(ValidationError):
            model.model_validate_json(text)


def test_every_schema_is_either_modelled_or_listed():
    schemas = {e["schema"] for e in INDEX["examples"]}
    for s in schemas:
        assert s in MODELS or s in NO_MODEL or s == EVENT or s.startswith("schemas/tools/"), s

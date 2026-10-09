"""Every example in schemas/examples/index.json gets the same verdict from the pydantic contract as from its schema.

Catches: a schema rule with no code counterpart (a model would accept what the API rejects) or the reverse, and an
example edited on one side only. Schemas without a pydantic model (tool-result envelopes, tool inputs, job, route)
are listed in NO_MODEL with the reason; they are covered by --contracts alone. Events go through `outcomes.Event`,
the envelope model that runs `event_rules_ok`.

The committed examples only cover the cases someone thought to write down, so `test_mutants_get_the_same_verdict`
also mutates every valid example of a modelled schema and compares the two verdicts (final review I3).
"""

import copy
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from ops_core import contracts as c
from ops_core.model_pins import ModelPins
from ops_core.outcomes import ActionOutcome, Event
from ops_core.routing import RunManifest
from pydantic import BaseModel, ValidationError

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
    "schemas/event.schema.json": Event,
}
NO_MODEL = {
    "schemas/tool-result.schema.json": (
        "envelopes are built by the MCP servers (T15/T47); the data shapes are ActionOutcome"
    ),
    "schemas/evidence.schema.json": "retrieval rows are produced by mcp-read (T17)",
    "schemas/route.schema.json": "enums only; the table is pinned in test_jobs_routes_outcomes",
    "schemas/job.schema.json": "JOB_RULES is pinned in test_jobs_routes_outcomes, the example by --contracts",
}


@pytest.mark.parametrize("item", INDEX["examples"], ids=[e["path"].rsplit("/", 1)[-1] for e in INDEX["examples"]])
def test_code_and_schema_agree(item):
    text = Path(item["path"]).read_text(encoding="utf-8")
    schema = item["schema"]
    if schema.startswith("schemas/tools/") or schema in NO_MODEL:
        pytest.skip(NO_MODEL.get(schema, "tool input schema: enforced by the MCP server's argument validation (T15)"))
    model = MODELS[schema]
    if item["valid"]:
        model.model_validate_json(text)
    else:
        with pytest.raises(ValidationError):
            model.model_validate_json(text)


def test_every_schema_is_either_modelled_or_listed():
    schemas = {e["schema"] for e in INDEX["examples"]}
    for s in schemas:
        assert s in MODELS or s in NO_MODEL or s.startswith("schemas/tools/"), s


# --- Differential mutation test. ---
# Three mechanical mutations of every valid example of a modelled schema: each enum-valued field takes every other
# value of its enum, each boolean is flipped, and each required key is removed. Null, whitespace and
# timestamp-spelling conventions are deliberately not mutated: they are Plan D's API-boundary decisions (final review
# Minor 2 and 4, parked in SESSION_STATE.md), not seams between two descriptions of one rule.
JsonPath = tuple[str | int, ...]
REMOVE = object()  # sentinel: the mutation deletes the key instead of replacing its value


def _alternatives(schema: dict) -> list[dict]:
    """The schema plus every branch of its `anyOf` (the generator's spelling of "nullable"), recursively."""
    out = [schema]
    for branch in schema.get("anyOf", []):
        out += _alternatives(branch)
    return out


def _mutations(node: object, schema: dict, path: JsonPath = ()) -> Iterator[tuple[JsonPath, object]]:
    """Yield (path, new value or REMOVE) for every mutation at or below `path`; `node` is the value found there."""
    alts = _alternatives(schema)
    if isinstance(node, bool):
        yield path, not node
    elif isinstance(node, str | None):
        for value in (v for alt in alts for v in alt.get("enum", [])):
            if value != node:
                yield path, value
    elif isinstance(node, dict):
        required = {key for alt in alts for key in alt.get("required", [])}
        for key in sorted(required & node.keys()):
            yield (*path, key), REMOVE
        for key, child in node.items():
            child_schema = next((alt["properties"][key] for alt in alts if key in alt.get("properties", {})), {})
            yield from _mutations(child, child_schema, (*path, key))
    elif isinstance(node, list):
        item_schema = next((alt["items"] for alt in alts if "items" in alt), {})
        for i, child in enumerate(node):
            yield from _mutations(child, item_schema, (*path, i))


def _mutate(doc: dict, path: JsonPath, value: object) -> dict:
    out = copy.deepcopy(doc)
    parent = out
    for step in path[:-1]:
        parent = parent[step]
    if value is REMOVE:
        del parent[path[-1]]
    else:
        parent[path[-1]] = value
    return out


def _schema_accepts(validator: Draft202012Validator, doc: dict) -> bool:
    return not any(validator.iter_errors(doc))


def _code_accepts(model: type[BaseModel], doc: dict) -> bool:
    try:
        model.model_validate_json(json.dumps(doc))
    except ValidationError:
        return False
    return True


MUTATED = [e for e in INDEX["examples"] if e["valid"] and e["schema"] in MODELS]


@pytest.mark.parametrize("item", MUTATED, ids=[e["path"].rsplit("/", 1)[-1] for e in MUTATED])
def test_mutants_get_the_same_verdict(item):
    schema_doc = json.loads(Path(item["schema"]).read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema_doc, format_checker=FormatChecker())
    doc = json.loads(Path(item["path"]).read_text(encoding="utf-8"))
    disagreements = []
    count = 0
    for path, value in _mutations(doc, schema_doc):
        count += 1
        mutant = _mutate(doc, path, value)
        by_schema, by_code = _schema_accepts(validator, mutant), _code_accepts(MODELS[item["schema"]], mutant)
        if by_schema != by_code:
            where = "$" + "".join(f".{p}" if isinstance(p, str) else f"[{p}]" for p in path)
            change = "removed" if value is REMOVE else f"= {value!r}"
            disagreements.append(
                f"{where} {change}: schema {'accepts' if by_schema else 'rejects'}, code "
                f"{'accepts' if by_code else 'rejects'}"
            )
    assert count, "no mutations generated; the walker no longer understands the schema"
    assert not disagreements, "\n".join(disagreements)

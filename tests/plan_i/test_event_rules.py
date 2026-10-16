"""The payload rules of T14 review note 2 and Plan I ruling 4, in the schema and in the Python twin, on one table of
cases (tests/plan_i/event_cases.py), without a database.

Catches: a `status` accepted on an application event (tool.completed from the worker claiming SUCCEEDED, review note
2), a payload key the schema does not define accepted by code (or the reverse), a key today's real writers use that
the schema forgot (the clarification reply's `question_id`/`message_id`, the dead letter's `outbox_id`), and a schema
or code edit made on one side only.
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from ops_core.outcomes import (
    DESTINATION_EVIDENCE,
    PAYLOAD_KEYS,
    STATUS_EVENT_TYPES,
    EventRuleViolation,
    EventSource,
    EventType,
    event_rules_ok,
)

from tests.plan_i.event_cases import CASES, Case, event_document

SCHEMA = json.loads((Path(__file__).resolve().parents[2] / "schemas" / "event.schema.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_the_schema_gives_the_tabled_verdict(case: Case) -> None:
    errors = list(VALIDATOR.iter_errors(event_document(case)))
    assert (not errors) == case.ok, [e.message for e in errors]


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_the_python_twin_gives_the_tabled_verdict(case: Case) -> None:
    if case.ok:
        event_rules_ok(EventType(case.type), EventSource(case.source), case.payload)
    else:
        with pytest.raises(EventRuleViolation):
            event_rules_ok(EventType(case.type), EventSource(case.source), case.payload)


def test_the_payload_keys_are_the_schemas() -> None:
    assert set(SCHEMA["properties"]["payload"]["properties"]) == PAYLOAD_KEYS
    assert {"question_id", "message_id", "outbox_id"} <= PAYLOAD_KEYS  # today's writers' keys, added by T14
    assert STATUS_EVENT_TYPES == DESTINATION_EVIDENCE  # only record_outcome's four types assert a status


def test_the_refusals_name_the_rule_and_never_the_key() -> None:
    with pytest.raises(EventRuleViolation) as refused:
        event_rules_ok(EventType.TOOL_COMPLETED, EventSource.APPLICATION, {"secret-looking-key": "x"})
    assert "secret-looking-key" not in str(refused.value)
    with pytest.raises(EventRuleViolation, match="status"):
        event_rules_ok(EventType.TOOL_COMPLETED, EventSource.APPLICATION, {"status": "SUCCEEDED"})

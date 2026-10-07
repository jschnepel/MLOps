import json
from pathlib import Path

import jsonschema
import pytest

SCHEMA = Path("evals/holdout-case.schema.json")


def load_schema() -> dict:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def test_schema_is_valid_draft_2020_12():
    jsonschema.Draft202012Validator.check_schema(load_schema())


def test_minimal_valid_case():
    case = {
        "case_id": "HO-001",
        "tenant": "alpha",
        "asset_id": "A17",
        "request_text": "Investigate the alerts on Asset A17 over the last 24 hours and prepare an incident.",
        "hours": 24,
        "intent": "investigate",
    }
    jsonschema.Draft202012Validator(load_schema()).validate(case)


@pytest.mark.parametrize(
    "bad",
    [
        {"case_id": "HO-001", "tenant": "alpha", "asset_id": "A17", "request_text": "long enough", "hours": 24},
        {
            "case_id": "HO-001",
            "tenant": "gamma",
            "asset_id": "A17",
            "request_text": "long enough",
            "hours": 24,
            "intent": "investigate",
        },
        {
            "case_id": "HO-001",
            "tenant": "alpha",
            "asset_id": "A17",
            "request_text": "long enough",
            "hours": 24,
            "intent": "investigate",
            "expected_outcome": "SUCCEEDED",
        },
    ],
)
def test_invalid_cases_rejected(bad):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(load_schema()).validate(bad)

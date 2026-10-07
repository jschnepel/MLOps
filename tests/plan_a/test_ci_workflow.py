import re
from pathlib import Path

import yaml

WF = Path(".github/workflows/ci.yml")


def test_every_action_is_pinned_to_a_full_sha():
    doc = yaml.safe_load(WF.read_text(encoding="utf-8"))
    for job in doc["jobs"].values():
        for step in job["steps"]:
            if "uses" in step:
                assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", step["uses"]), step["uses"]


def test_token_is_read_only_and_no_secrets_are_referenced():
    text = WF.read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    assert doc["permissions"] == {"contents": "read"}
    assert "secrets." not in text
    checkouts = [
        step
        for job in doc["jobs"].values()
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("actions/checkout@")
    ]
    assert checkouts
    for step in checkouts:
        assert step.get("with", {}).get("persist-credentials") is False, step


def test_workflow_runs_the_one_command_with_all_packages():
    text = WF.read_text(encoding="utf-8")
    assert "uv sync --locked --all-packages" in text
    assert "python scripts/check.py" in text
    assert "verify_handoff.py --reference-code --manifest" in text

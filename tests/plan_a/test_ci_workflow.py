"""Guard the supply-chain properties of .github/workflows/ci.yml (T06).

These tests catch a well-meant edit that weakens CI: an action referenced by a movable tag instead of a commit
SHA, a token with write access, a secret reference, or a checkout that leaves credentials on disk.
"""

import re
from pathlib import Path

import yaml

# Relative path: pytest is run from the repository root (scripts/check.py and CI both do).
WF = Path(".github/workflows/ci.yml")


def test_every_action_is_pinned_to_a_full_sha():
    doc = yaml.safe_load(WF.read_text(encoding="utf-8"))
    for job in doc["jobs"].values():
        for step in job["steps"]:
            if "uses" in step:
                # 40 hex digits = a full commit SHA; a tag such as @v5 can be re-pointed after review.
                assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", step["uses"]), step["uses"]


def test_token_is_read_only_and_no_secrets_are_referenced():
    text = WF.read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    assert doc["permissions"] == {"contents": "read"}
    # Plain text search on purpose: it also catches a reference hidden in a comment-like string or an env block.
    assert "secrets." not in text
    checkouts = [
        step
        for job in doc["jobs"].values()
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("actions/checkout@")
    ]
    assert checkouts  # guards against the filter above silently matching nothing
    for step in checkouts:
        assert step.get("with", {}).get("persist-credentials") is False, step


def test_workflow_runs_the_one_command_with_all_packages():
    text = WF.read_text(encoding="utf-8")
    assert "uv sync --locked --all-packages" in text
    assert "python scripts/check.py" in text
    assert "verify_handoff.py --reference-code --manifest" in text

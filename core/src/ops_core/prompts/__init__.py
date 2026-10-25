"""The runtime prompts of the drafting route (T19; BUILD_SPEC §12 "prompt versioning", SA:47).

Each prompt is one text file beside this module, shipped as package data of `ops-core`, and is sent to the model
byte for byte as the system message; nothing here templates it. The user message is JSON the worker renders
(`ops_worker.ollama_drafting`), with the starter's keys (`handoff/prompts/incident-draft-v1.md`).

The v2 texts are the starters' system messages plus rules the T02 probe showed missing: copy evidence IDs only from
`allowed_evidence_ids`, and write `question` only with `abstain` (`reports/model-probe-qwen3-8b.md`, "Diagnosis";
erratum 116). The starters in `handoff/prompts/` stay byte-identical, because `scripts/probe.py` pins them. A changed
text is a new version with a new name, never an edit: the unit tests pin each file's SHA-256, and the version string is
part of every proposal's hashed payload (`ProposalPayload.prompt_version`) and every run manifest.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

HERE: Final = Path(__file__).resolve().parent
DRAFT_VERSION: Final = "incident-draft-v2"
REPAIR_VERSION: Final = "schema-repair-v2"


def text(version: str) -> str:
    """The prompt file named `version`, exactly as committed (UTF-8, LF).

    Raises:
        FileNotFoundError: no prompt of that version ships with this package.
    """
    return (HERE / f"{version}.txt").read_text(encoding="utf-8")


def sha256(version: str) -> str:
    """The SHA-256 of the prompt's bytes: what a run or a report records as the prompt hash (BS:572)."""
    return hashlib.sha256((HERE / f"{version}.txt").read_bytes()).hexdigest()

"""Model pins (`data/model-pins.json`, AM-31): the digest the worker must see from Ollama at warm-up, or fail closed.

The digest is the bare 64-hex value Ollama reports in `/api/tags` (no `sha256:` prefix), exactly as `scripts/probe.py`
writes it; one canonical form keeps the T19 comparison a plain string equality.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, StringConstraints, ValidationError

NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
# Bare lowercase hex only: accepting a `sha256:` prefix or uppercase would let two spellings of one digest pass
# validation and then fail (or worse, mismatch silently) in the worker's string comparison.
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class ModelPinsError(ValueError):
    """The pins file is missing or malformed; the worker must not start drafting without valid pins."""


class ModelPins(BaseModel):
    """Strict: JSON strings only for every field, timezone-aware `probed_at`, no extra keys."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    model: NonEmpty
    digest: Digest
    ollama_version: NonEmpty
    # AwareDatetime rejects a naive timestamp: without an offset the probe time is ambiguous across hosts.
    probed_at: AwareDatetime


def load_model_pins(path: Path) -> ModelPins:
    """Read and validate the pins file.

    Raises:
        ModelPinsError: the file is missing, is not JSON, or does not match `ModelPins`.
    """
    if not path.is_file():
        raise ModelPinsError(f"model pins file not found: {path}")
    text = path.read_text(encoding="utf-8")
    # Parse once only to give "not valid JSON" its own message; validation below re-reads the same text.
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        raise ModelPinsError(f"model pins file is not valid JSON: {path}: {exc}") from exc
    # model_validate_json (not model_validate on the parsed dict) is what makes strict mode usable for dates: strict
    # python-mode rejects ISO strings for datetime, while strict JSON-mode accepts them and still rejects epoch ints.
    try:
        return ModelPins.model_validate_json(text)
    except ValidationError as exc:
        raise ModelPinsError(f"model pins file is malformed: {path}: {exc}") from exc

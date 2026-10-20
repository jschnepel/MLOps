"""Write data/embedding-pins.json from the local Ollama (T18; Plan N ruling 3, erratum 107).

Usage: `uv run python scripts/pin_embedding_model.py` (loopback Ollama, `OPS_OLLAMA_URL` to override).

It reads three things and invents none (BS:670): the Ollama version (`/api/version`), the digest `/api/tags` reports
for `nomic-embed-text:latest` (`/api/show` carries no digest, as T19's note found for qwen3:8b) and the dimension of
one real `/api/embed` answer, which must be 768. It never pulls, deletes or generates. The file is the embedding
model's pin beside the generation model's `data/model-pins.json` (T02, SA:598), checked by `skeleton.py embed` before
it writes and by mcp-read on every vector call.

It refuses, writing nothing, when the model is missing or answers another dimension, and when a pin already exists
for another model, digest or dimension: the stored embeddings were made with the pinned model, so replacing the pin
alone would let mcp-read compare a new model's query vectors with the old model's document vectors. A model change is
a new revision that removes the stored embeddings (or moves them aside); its commit deletes or replaces this file as a
reviewed change, and `skeleton.py embed` runs again (Plan N rounds 1 and 2, I2). The refusal guards against a silent
re-pin by this script; it cannot stop a hand edit of the committed file, which is a reviewed repository change.
Re-running it for the same model only refreshes `ollama_version` and `probed_at`.

Every failure has one shape: a single `PIN: <rule>, nothing written` line (a rule, never an address or a value) and
exit status 1, whether Ollama is unreachable, the model is missing, an answer is malformed or the pin would be invalid.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx2
from ops_core import embeddings, settings
from ops_core.model_pins import EmbeddingPins, ModelPinsError, load_embedding_pins
from pydantic import ValidationError


class PinFailed(Exception):
    """A rule the pin cannot be written under; the message names the rule, never an address or a value."""


def refuse(rule: str) -> int:
    """The one failure shape: a `PIN:` line naming the rule, and the exit status."""
    print(f"PIN: {rule}, nothing written")
    return 1


async def probe(base: str, transport: httpx2.AsyncBaseTransport | None = None) -> dict[str, object]:
    """The pin's fields as Ollama reports them now; `transport` lets the unit test answer without a socket."""
    embedder = embeddings.OllamaEmbedder(base, transport=transport)
    try:
        version = await embedder.version()
        digest = await embedder.installed_digest(embeddings.MODEL)
        if digest is None:
            raise PinFailed(f"{embeddings.MODEL} is not installed in this Ollama")
        # Not `embed`: `embed` checks the dimension against a pin, and this is what makes the pin.
        dimension = await embedder.dimension(embeddings.MODEL)
    finally:
        await embedder.aclose()
    return {
        "model": embeddings.MODEL,
        "digest": digest,
        "dimension": dimension,
        "ollama_version": version,
        "probed_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def replaces_another_model(out: Path, pin: dict[str, object]) -> bool:
    """True when `out` already pins another model, digest or dimension (an unreadable file counts as another)."""
    if not out.exists():
        return False
    try:
        held = load_embedding_pins(out)
    except ModelPinsError:
        return True
    return (held.model, held.digest, held.dimension) != (pin["model"], pin["digest"], pin["dimension"])


def main(out: Path = embeddings.PINS, transport: httpx2.AsyncBaseTransport | None = None) -> int:
    """Probe, refuse another dimension or a pin of another model, validate, write the pin and read it back."""
    try:
        pin = asyncio.run(probe(settings.urls().ollama, transport))
    except (embeddings.EmbeddingError, PinFailed) as exc:
        return refuse(str(exc))
    if pin["dimension"] != embeddings.DIMENSION:
        return refuse(f"{embeddings.MODEL} answered {pin['dimension']} dimensions, not {embeddings.DIMENSION}")
    try:
        EmbeddingPins.model_validate_json(json.dumps(pin))  # the pin as the services will read it, before it is written
    except ValidationError:  # its text would carry the probed values
        return refuse("the probed pin does not match the embedding pin's shape")
    if replaces_another_model(out, pin):
        print(
            "PIN: refused, nothing written: data/embedding-pins.json pins another model build; a model change is a new "
            "revision that removes the stored embeddings and replaces this file as a reviewed change, then embed runs "
            "again"
        )
        return 1
    out.write_text(json.dumps(pin, indent=2) + "\n", encoding="utf-8", newline="\n")
    load_embedding_pins(out)  # the file just written must load as the services read it
    print(f"PIN: {pin['model']} {pin['digest']} dimension {pin['dimension']} on Ollama {pin['ollama_version']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

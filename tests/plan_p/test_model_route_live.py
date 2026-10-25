"""The real route's startup against local Ollama (OPS_LIVE=1; T19, R127, R041): the committed pin passes, a tampered
one fails closed before anything is generated.

Only Ollama on loopback is needed (no database, no Keycloak), so this module has its own skip instead of the e2e
fixtures. It asks `/api/tags` and `/api/version` and, on the passing start only, makes the one warm-up call the worker
makes. It never pulls, deletes or changes a model.

Catches: a worker that starts on the committed pin's model without proving the digest, a start that accepts a pin
whose digest Ollama does not report, and a start that generates (warms) before the comparison.
"""

import asyncio
import json
import os
from pathlib import Path

import pytest
from ops_core.model_pins import load_model_pins
from ops_worker import drafting, ollama_drafting
from ops_worker.drafting import ModelStartError
from ops_worker.ollama_drafting import Reply

pytestmark = pytest.mark.skipif(os.environ.get("OPS_LIVE") != "1", reason="live tests run only with OPS_LIVE=1")


def test_the_real_route_starts_on_the_committed_pin() -> None:
    generator = asyncio.run(drafting.start_route("qwen3:8b"))
    assert isinstance(generator, ollama_drafting.OllamaDraftGenerator)
    assert generator.digest == load_model_pins(ollama_drafting.PINS).digest and generator.ollama_version


def test_a_tampered_pin_fails_closed_before_anything_is_generated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pin = json.loads(ollama_drafting.PINS.read_text(encoding="utf-8"))
    pin["digest"] = pin["digest"][::-1]  # still 64 hex characters, so the loader accepts it; Ollama reports another
    tampered = tmp_path / "model-pins.json"
    tampered.write_text(json.dumps(pin), encoding="utf-8")
    monkeypatch.setattr(ollama_drafting, "PINS", tampered)
    calls: list[str] = []

    def no_chat(_url: str) -> ollama_drafting.Chat:
        async def chat(system: str, user: str, seconds: float) -> Reply:
            calls.append(user)
            return Reply("{}")

        return chat

    monkeypatch.setattr(ollama_drafting, "ollama_chat", no_chat)
    with pytest.raises(ModelStartError, match="digest is not the one"):
        asyncio.run(drafting.start_route("qwen3:8b"))
    assert calls == []

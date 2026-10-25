"""mcp-read's `vector_exact` search in-process, with the database, asset-sim and Ollama replaced (Plan N rulings 3, 4,
5 and 16; SA:348; errata 3 and 108).

Catches: an invalid handle that reaches the embedding model (it must never learn what the server supports, Plan M
ruling 14), or a search that asks the model before asset-sim has answered for the run's asset type (ruling 4); a
missing or mismatched pin answered with anything but `UNSUPPORTED_MODE`, an unreachable model with anything but a
retryable `UNAVAILABLE`, a malformed answer with anything but `UPSTREAM_INVALID`, and any of them
reaching the definer; the definer's `EMBEDDINGS_INCOMPLETE` lost instead of answered as `REFUSED`; a vector answer
that reports another mode or breaks the committed result contract; and the committed tool schemas changed for T18
(no tool argument changes, so R029's comparison stays byte for byte).
"""

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from ops_core import embeddings, model_pins, persistence
from ops_mcp_read import assets

from tests.plan_l.test_mcp_read_corpus import Database, RunType, UnitConn, call
from tests.plan_n.test_embeddings import FakeEmbedder

pytestmark = pytest.mark.asyncio

VECTOR = {"query": "seal", "limit": 3, "mode": "vector_exact"}
TOOL_RESULT = Draft202012Validator(
    json.loads(Path("schemas/tool-result.schema.json").read_text(encoding="utf-8")), format_checker=FormatChecker()
)
# The committed contracts T18 must not touch (Plan N ruling 16): their SHA-256 on `plan-n` before T18 (6d00d06).
UNCHANGED = {
    "schemas/tools/search_procedures.input.schema.json": (
        "51277441bf8482e10258a63ca270d03b81cc8a65a536ac31824eb67d041758b9"
    ),
    # T21 (Plan R ruling 11) added the error object's optional `reason`; the read tools' shapes are unchanged.
    "schemas/tool-result.schema.json": "124f889658b32f7a095d89cf4a56d0a60d80634b9b02dfe418dcbe4150d3a45a",
}


def doc_of(result: Any) -> dict[str, Any]:
    doc = result.structured_content
    assert not result.is_error and isinstance(doc, dict)
    return doc


async def test_a_vector_answer_reports_its_mode_and_meets_the_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = doc_of(await call(monkeypatch, Database(UnitConn()), VECTOR, embedder=FakeEmbedder()))
    TOOL_RESULT.validate(doc)
    assert doc["status"] == "ok" and doc["data"]["retrieval_mode"] == "vector_exact"
    assert "rank" not in doc["data"]["results"][0]  # a similarity never reaches the tool result either


async def test_an_invalid_handle_never_reaches_the_embedding_model(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeEmbedder()
    db = Database(UnitConn(), resolve=persistence.HandleRejected("invocation handle rejected"))
    doc = doc_of(await call(monkeypatch, db, VECTOR, embedder=fake))
    assert doc["error"]["code"] == "INVALID_HANDLE"
    assert fake.texts == [] and fake.verified == 0


@pytest.mark.parametrize(
    ("failure", "code", "retryable"),
    [
        (embeddings.PinMismatch("the installed embedding model is not the pinned one"), "UNSUPPORTED_MODE", False),
        (embeddings.Unavailable("the embedding model could not be reached"), "UNAVAILABLE", True),
        (embeddings.Malformed("an embedding has another dimension than the pinned one"), "UPSTREAM_INVALID", False),
    ],
    ids=["mismatch", "unavailable", "malformed"],
)
async def test_an_embedding_failure_is_its_envelope_and_never_reaches_the_definer(
    monkeypatch: pytest.MonkeyPatch, failure: embeddings.EmbeddingError, code: str, retryable: bool
) -> None:
    db = Database(UnitConn())
    doc = doc_of(await call(monkeypatch, db, VECTOR, embedder=FakeEmbedder(failure)))
    assert doc["error"] == {"code": code, "message": str(failure), "retryable": retryable}
    assert [name for name, _, _ in db.calls] == ["resolve", "scope"]  # no third unit
    assert doc["observed_at"] == "2026-10-16T12:00:00Z"  # the scope's database instant, as the asset tools


async def test_a_missing_pin_is_unsupported_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(embeddings, "PINS", tmp_path / "embedding-pins.json")
    fake = FakeEmbedder()
    doc = doc_of(await call(monkeypatch, Database(UnitConn()), VECTOR, embedder=fake))
    assert doc["error"] == {"code": "UNSUPPORTED_MODE", "message": "no valid embedding pin", "retryable": False}
    assert fake.texts == []


async def test_an_unreadable_pin_answers_as_a_missing_one(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A pin file the OS refuses to read never escapes as a transport error and never carries its path."""

    def unreadable(path: Path) -> None:
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(model_pins, "load_embedding_pins", unreadable)
    fake = FakeEmbedder()
    db = Database(UnitConn())
    doc = doc_of(await call(monkeypatch, db, VECTOR, embedder=fake))
    assert doc["error"] == {"code": "UNSUPPORTED_MODE", "message": "no valid embedding pin", "retryable": False}
    assert fake.verified == 0 and [name for name, _, _ in db.calls] == ["resolve", "scope"]


async def test_an_undecodable_pin_answers_as_a_missing_one(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """UnicodeDecodeError is a ValueError."""
    pin = tmp_path / "embedding-pins.json"
    pin.write_bytes(bytes([0xFF, 0xFE, 0x00]))
    monkeypatch.setattr(embeddings, "PINS", pin)
    doc = doc_of(await call(monkeypatch, Database(UnitConn()), VECTOR, embedder=FakeEmbedder()))
    assert doc["error"] == {"code": "UNSUPPORTED_MODE", "message": "no valid embedding pin", "retryable": False}


async def test_a_server_without_an_embedder_is_unavailable_and_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    """The lifespan builds the client; a server whose build gave none answers, never raises."""
    monkeypatch.setattr(embeddings.OllamaEmbedder, "from_settings", classmethod(lambda cls: None))
    db = Database(UnitConn())
    doc = doc_of(await call(monkeypatch, db, VECTOR))
    assert doc["error"] == {
        "code": "UNAVAILABLE",
        "message": "the embedding model is not configured",
        "retryable": True,
    }
    assert [name for name, _, _ in db.calls] == ["resolve", "scope"]


class SlowVerify(FakeEmbedder):
    """An embedder whose pin check outlasts the budget."""

    async def verify(self, pins: Any) -> None:
        await super().verify(pins)
        await asyncio.sleep(5)


async def test_the_budget_covers_the_pin_check_and_the_embedding_together(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embeddings, "TIMEOUT_SECONDS", 0.05)
    slow = SlowVerify()
    db = Database(UnitConn())
    doc = doc_of(await call(monkeypatch, db, VECTOR, embedder=slow))
    assert doc["error"] == {
        "code": "UNAVAILABLE",
        "message": "the embedding model did not answer in time",
        "retryable": True,
    }
    assert slow.verified == 1 and slow.texts == []  # the budget ran out inside the check
    assert [name for name, _, _ in db.calls] == ["resolve", "scope"]  # no third unit


async def test_a_lexical_search_leaves_the_embedding_model_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeEmbedder()
    doc = doc_of(await call(monkeypatch, Database(UnitConn()), {**VECTOR, "mode": "lexical"}, embedder=fake))
    assert doc["data"]["retrieval_mode"] == "lexical"
    assert fake.verified == 0 and fake.texts == []


async def test_incomplete_embeddings_are_refused_not_omitted(monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database(UnitConn(), search=persistence.Refused("EMBEDDINGS_INCOMPLETE"))
    doc = doc_of(await call(monkeypatch, db, VECTOR, embedder=FakeEmbedder()))
    assert doc["error"] == {"code": "REFUSED", "message": "EMBEDDINGS_INCOMPLETE", "retryable": False}


async def test_the_committed_tool_contracts_are_unchanged() -> None:
    for path, digest in UNCHANGED.items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest, path


@pytest.mark.parametrize(
    ("answer", "arguments", "code"),
    [
        (assets.Unavailable("asset-sim could not be reached"), {}, "UNAVAILABLE"),
        ("pump", {"asset_type": "valve"}, "ASSET_TYPE_OUT_OF_SCOPE"),
    ],
    ids=["asset-sim-down", "another-asset-type"],
)
async def test_the_embedding_model_is_asked_only_after_the_runs_asset_type(
    monkeypatch: pytest.MonkeyPatch, answer: Any, arguments: dict[str, str], code: str
) -> None:
    """Round 1, Minor 8: ruling 4's order puts the pin check and the query embedding after asset-sim's answer."""
    fake = FakeEmbedder()
    doc = doc_of(await call(monkeypatch, Database(UnitConn()), {**VECTOR, **arguments}, RunType(answer), embedder=fake))
    assert doc["error"]["code"] == code
    assert fake.verified == 0 and fake.texts == []

"""The embedding model's pin (Plan N ruling 3, erratum 107): `data/embedding-pins.json`, its schema and its loader.

Catches: a pin file that is missing, hand-edited into another shape, prefixed (`sha256:`), of another dimension than
the 768 `app.embeddings` stores, or naive in time; a committed pin that the schema and the loader judge differently;
and a pin that is not the measured one (the digest Ollama's `/api/tags` reported for `nomic-embed-text:latest` on the
dev machine, 2026-10-19), which would mean the file was filled with an invented value (BS:670); and a pin script that
replaces the pin of another model build, which would let mcp-read compare two models' vectors (round 1, I2).
"""

import json
from pathlib import Path

import httpx2
import pytest
from jsonschema import Draft202012Validator, FormatChecker
from ops_core import embeddings
from ops_core.model_pins import ModelPinsError, load_embedding_pins

from scripts import pin_embedding_model

SCHEMA = Draft202012Validator(
    json.loads(Path("schemas/embedding-pins.schema.json").read_text(encoding="utf-8")), format_checker=FormatChecker()
)
MEASURED = "0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f"  # /api/tags, 2026-10-19 (Plan N brief)
GOOD = {
    "model": "nomic-embed-text",
    "digest": "cd" * 32,
    "dimension": 768,
    "ollama_version": "0.40.4",
    "probed_at": "2026-10-19T08:00:00Z",
}


def write(tmp_path: Path, data: object) -> Path:
    path = tmp_path / "embedding-pins.json"
    path.write_text(json.dumps(data), encoding="utf-8", newline="\n")
    return path


def test_the_committed_pin_is_the_measured_one_and_both_judges_accept_it() -> None:
    raw = json.loads(embeddings.PINS.read_text(encoding="utf-8"))
    SCHEMA.validate(raw)
    pins = load_embedding_pins(embeddings.PINS)
    assert (pins.model, pins.digest, pins.dimension) == (embeddings.MODEL, MEASURED, embeddings.DIMENSION)
    assert embeddings.PINS == Path("data/embedding-pins.json").resolve()


@pytest.mark.parametrize(
    "change",
    [
        {"digest": "sha256:" + "cd" * 32},
        {"digest": "CD" * 32},
        {"dimension": 384},
        {"dimension": "768"},
        {"probed_at": "2026-10-19T08:00:00"},
        {"model": ""},
        {"extra": "field"},
    ],
    ids=["prefixed", "uppercase", "dimension", "dimension-text", "naive-time", "empty-model", "extra-field"],
)
def test_a_malformed_pin_is_refused_by_the_loader_and_the_schema(tmp_path: Path, change: dict[str, object]) -> None:
    data = {**GOOD, **change}
    with pytest.raises(ModelPinsError):
        load_embedding_pins(write(tmp_path, data))
    assert list(SCHEMA.iter_errors(data))


def test_a_missing_or_broken_file_is_a_pins_error(tmp_path: Path) -> None:
    with pytest.raises(ModelPinsError, match="not found"):
        load_embedding_pins(tmp_path / "absent.json")
    broken = tmp_path / "embedding-pins.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(ModelPinsError, match="not valid JSON"):
        load_embedding_pins(broken)


def ollama_answering(digest: str, dimension: int = 768) -> httpx2.MockTransport:
    """A scripted local Ollama for the pin script: its version, one installed build of the model, one embedding."""

    def answer(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/api/version":
            return httpx2.Response(200, json={"version": "0.40.4"})
        if request.url.path == "/api/tags":
            return httpx2.Response(200, json={"models": [{"name": "nomic-embed-text:latest", "digest": digest}]})
        assert request.url.path == "/api/embed", request.url.path  # never a pull, a delete or a generation
        return httpx2.Response(200, json={"embeddings": [[0.1] * dimension]})

    return httpx2.MockTransport(answer)


def test_the_pin_script_writes_a_pin_and_never_replaces_another_models(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Plan N round 1, I2: replacing the pin alone would let mcp-read compare a new model's query vectors with the
    stored vectors of the old one, so only a revision that removes the stored embeddings replaces it."""
    out = tmp_path / "embedding-pins.json"
    assert pin_embedding_model.main(out, ollama_answering(MEASURED)) == 0
    assert load_embedding_pins(out).digest == MEASURED
    assert pin_embedding_model.main(out, ollama_answering(MEASURED)) == 0  # the same build: a refresh only
    before = out.read_bytes()
    capsys.readouterr()
    assert pin_embedding_model.main(out, ollama_answering("ab" * 32)) == 1  # another build: refused
    assert out.read_bytes() == before
    assert "PIN: refused, nothing written" in capsys.readouterr().out
    other = tmp_path / "other.json"
    assert pin_embedding_model.main(other, ollama_answering(MEASURED, 384)) == 1 and not other.exists()


def ollama_failing(kind: str) -> httpx2.MockTransport:
    """A local Ollama that cannot give the pin: unreachable, without the model, or answering no usable vector."""

    def answer(request: httpx2.Request) -> httpx2.Response:
        if kind == "unreachable":
            raise httpx2.ConnectError("refused", request=request)
        if request.url.path == "/api/version":
            return httpx2.Response(200, json={"version": "0.40.4"})
        if request.url.path == "/api/tags":
            models = [] if kind == "not-installed" else [{"name": "nomic-embed-text:latest", "digest": MEASURED}]
            return httpx2.Response(200, json={"models": models})
        assert request.url.path == "/api/embed", request.url.path
        vectors = {"no-vector": [], "two-vectors": [[0.1] * 768] * 2, "zeros": [[0.0] * 768]}[kind]
        return httpx2.Response(200, json={"embeddings": vectors})

    return httpx2.MockTransport(answer)


@pytest.mark.parametrize("kind", ["unreachable", "not-installed", "no-vector", "two-vectors", "zeros"])
def test_every_failure_is_one_pin_line_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    """One shape for every failure (fix round 1): a single `PIN: <rule>, nothing written` line, exit 1, no file and no
    traceback, with no address or value in the line."""
    out = tmp_path / "embedding-pins.json"
    assert pin_embedding_model.main(out, ollama_failing(kind)) == 1
    assert not out.exists()
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1 and lines[0].startswith("PIN: ") and lines[0].endswith(", nothing written")
    assert "127.0.0.1" not in lines[0] and "http" not in lines[0]

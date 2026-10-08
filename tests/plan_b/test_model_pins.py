"""ops_core.model_pins: the worker's digest pin must be well-formed or loading fails loudly (AM-31).

These tests catch the mistake of accepting a pins file the worker cannot compare safely: a `sha256:`-prefixed or
non-hex digest (the T19 check is plain string equality against Ollama's bare hex), a naive or epoch `probed_at`,
blank fields, or stray keys that would hide a typo. Every failure must surface as `ModelPinsError`, never as a raw
pydantic or JSON exception.
"""

import json
from pathlib import Path

import pytest
from ops_core.model_pins import ModelPinsError, load_model_pins

GOOD = {
    "model": "qwen3:8b",
    "digest": "ab" * 32,  # Ollama's /api/tags digest is bare 64-hex; scripts/probe.py writes it verbatim
    "ollama_version": "0.33.3",
    "probed_at": "2026-10-08T01:02:03+00:00",
}


def write(tmp_path: Path, data: object) -> Path:
    p = tmp_path / "model-pins.json"
    p.write_text(json.dumps(data), encoding="utf-8", newline="\n")
    return p


def test_loads_well_formed_pins(tmp_path: Path):
    pins = load_model_pins(write(tmp_path, GOOD))
    assert pins.model == "qwen3:8b" and pins.digest == GOOD["digest"] and pins.ollama_version == "0.33.3"
    assert pins.probed_at.tzinfo is not None and pins.probed_at.year == 2026


def test_loads_exactly_what_probe_py_writes(tmp_path: Path):
    """The shape of data/model-pins.json as scripts/probe.py produces it (indent=2, four keys, bare digest)."""
    text = json.dumps(
        {
            "model": "qwen3:8b",
            "digest": "500a1f06" + "0" * 56,
            "ollama_version": "0.33.3",
            "probed_at": "2026-10-08T00:00:00.123456+00:00",
        },
        indent=2,
    )
    p = tmp_path / "model-pins.json"
    p.write_text(text + "\n", encoding="utf-8", newline="\n")
    assert load_model_pins(p).digest.startswith("500a1f06")


def test_missing_file_is_an_error(tmp_path: Path):
    with pytest.raises(ModelPinsError, match="not found"):
        load_model_pins(tmp_path / "nope.json")


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.pop("digest"),
        lambda d: d.update(digest="sha256:" + "ab" * 32),
        lambda d: d.update(digest="zz" * 32),
        lambda d: d.update(digest="ab" * 31),
        lambda d: d.update(model=""),
        lambda d: d.update(model="   "),
        lambda d: d.update(probed_at="2026-10-08T01:02:03"),
        lambda d: d.update(probed_at=1759881723),
        lambda d: d.update(extra="field"),
    ],
    ids=[
        "no-digest",
        "prefixed",
        "not-hex",
        "short",
        "empty-model",
        "blank-model",
        "naive-time",
        "epoch-int",
        "extra-field",
    ],
)
def test_model_pins_rejects_bad_digest_and_missing_fields(tmp_path: Path, mutation):
    data = dict(GOOD)
    mutation(data)
    with pytest.raises(ModelPinsError):
        load_model_pins(write(tmp_path, data))


def test_not_json_is_an_error(tmp_path: Path):
    p = tmp_path / "model-pins.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(ModelPinsError, match="not valid JSON"):
        load_model_pins(p)

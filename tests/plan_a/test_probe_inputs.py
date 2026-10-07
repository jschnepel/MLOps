import json
from collections import Counter
from pathlib import Path

from scripts.gen_probe_inputs import SCENARIOS, generate, write_inputs


def test_generate_makes_at_least_30_distinct_inputs():
    cases = generate()
    assert len(cases) >= 30
    assert len({c["request_text"] for c in cases}) == len(cases)
    assert len({(c["asset_id"], c["hours"], c["scenario"]) for c in cases}) == len(cases)


def test_every_scenario_appears_at_least_five_times():
    counts = Counter(c["scenario"] for c in generate())
    assert set(counts) == set(SCENARIOS)
    assert min(counts.values()) >= 5, counts


def test_each_input_has_a_small_evidence_bundle():
    for c in generate():
        bundle = c["evidence"]
        assert bundle["status"]["asset_id"] == c["asset_id"]
        assert 0 <= len(bundle["alerts"]) <= 4
        assert all(d["document_id"].startswith(("ALPHA", "BETA")) for d in bundle["documents"])


def test_write_inputs_is_lf_without_bom(tmp_path: Path):
    out = tmp_path / "inputs.jsonl"
    write_inputs(out)
    raw = out.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in raw
    assert [json.loads(l) for l in raw.decode("utf-8").splitlines()] == generate()


def test_committed_file_matches_generator():
    committed = [json.loads(l) for l in Path("evals/probe/inputs.jsonl").read_text(encoding="utf-8").splitlines()]
    assert committed == generate()  # drift guard: regenerate the file after any generator change

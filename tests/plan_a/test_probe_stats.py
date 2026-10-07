import pytest

from scripts.probe_stats import classify_output, p95_index, summarize, wilson


def test_wilson_known_values():
    lo, hi = wilson(27, 30)
    assert round(lo, 3) == 0.744
    assert round(hi, 3) == 0.965


def test_wilson_zero_and_full():
    assert wilson(0, 10)[0] == 0.0
    assert wilson(10, 10)[1] == 1.0


def test_wilson_rejects_bad_input():
    with pytest.raises(ValueError):
        wilson(5, 0)


def test_classify_json():
    assert classify_output('{"kind": "proposal"}') == "json_valid"


def test_classify_invalid():
    assert classify_output('{"kind": ') == "json_invalid"


def test_classify_thinking_is_a_failure_not_stripped():
    assert classify_output('<think>reasoning</think>{"kind": "proposal"}') == "thinking_present"


def test_p95_index_small_and_large():
    assert p95_index(1) == 0
    assert p95_index(2) == 1
    assert p95_index(20) == 18
    assert p95_index(100) == 94


def test_summarize_counts_metadata_thinking_and_separates_cold():
    results = [
        {"cold": True, "seconds": 50.0, "kind": "json_valid", "schema_valid": True, "repaired_valid": True, "thinking_in_metadata": False, "error": None},
        {"cold": False, "seconds": 4.0, "kind": "json_valid", "schema_valid": False, "repaired_valid": True, "thinking_in_metadata": True, "error": None},
        {"cold": False, "seconds": 5.0, "kind": "thinking_present", "schema_valid": False, "repaired_valid": False, "thinking_in_metadata": False, "error": None},
    ]
    s = summarize(results)
    assert s["n"] == 3
    assert s["json_valid"] == 2
    assert s["schema_valid"] == 1
    assert s["repaired_valid"] == 2
    assert s["thinking_any"] == 2  # one via <think> text, one via metadata
    assert s["cold_seconds"] == 50.0
    assert s["warm_p50"] == 5.0 and s["warm_p95"] == 5.0

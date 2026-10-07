import pytest

from scripts.probe_stats import (
    classify_output,
    classify_structured,
    has_thinking,
    mb_or_not_measured,
    p95_index,
    summarize,
    vram_row,
    wilson,
)


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
        {
            "cold": True,
            "seconds": 50.0,
            "kind": "json_valid",
            "schema_valid": True,
            "repaired_valid": True,
            "thinking_in_metadata": False,
            "error": None,
        },
        {
            "cold": False,
            "seconds": 4.0,
            "kind": "json_valid",
            "schema_valid": False,
            "repaired_valid": True,
            "thinking_in_metadata": True,
            "error": None,
        },
        {
            "cold": False,
            "seconds": 5.0,
            "kind": "thinking_present",
            "schema_valid": False,
            "repaired_valid": False,
            "thinking_in_metadata": False,
            "error": None,
        },
    ]
    s = summarize(results)
    assert s["n"] == 3
    assert s["json_valid"] == 2
    assert s["schema_valid"] == 1
    assert s["repaired_valid"] == 2
    assert s["thinking_any"] == 2  # one via <think> text, one via metadata
    assert s["cold_seconds"] == 50.0
    assert s["warm_p50"] == 5.0 and s["warm_p95"] == 5.0


def test_has_thinking_text_tag_or_metadata():
    assert has_thinking('<think>x</think>{"a": 1}', None) is True
    assert has_thinking('{"a": 1}', "some reasoning") is True
    assert has_thinking('{"a": 1}', None) is False
    assert has_thinking('{"a": 1}', "") is False


def test_vram_row_without_samples_is_not_measured_never_zero():
    row = vram_row([], None)
    assert row == "| Peak VRAM | not measured (nvidia-smi unavailable) | |"
    assert "0 MB" not in row


def test_vram_row_with_samples_names_count_interval_and_gpu():
    row = vram_row([5100, 7312, 6900], "NVIDIA GeForce RTX 3080")
    assert row == (
        "| Peak VRAM (max of 3 whole-GPU samples at 0.5 s during calls, NVIDIA GeForce RTX 3080) | 7312 MB | |"
    )


def test_vram_row_with_samples_but_unknown_gpu_name():
    assert vram_row([4000], None) == (
        "| Peak VRAM (max of 1 whole-GPU samples at 0.5 s during calls, GPU name unavailable) | 4000 MB | |"
    )


def test_mb_or_not_measured():
    assert mb_or_not_measured(6123) == "6123 MB"
    assert mb_or_not_measured(None) == "not measured (nvidia-smi unavailable)"


def test_summarize_counts_repair_thinking_separately_from_first_pass():
    base = {"cold": False, "seconds": 1.0, "schema_valid": False, "error": None, "thinking_in_metadata": False}
    results = [
        {**base, "kind": "json_valid", "repaired_valid": False, "repair_called": True, "repair_thinking": True},
        {**base, "kind": "json_invalid", "repaired_valid": True, "repair_called": True, "repair_thinking": False},
        {**base, "kind": "json_valid", "schema_valid": True, "repaired_valid": True, "repair_called": False},
    ]
    s = summarize(results)
    assert s["thinking_any"] == 0
    assert s["repair_calls"] == 2
    assert s["thinking_repair"] == 1


def test_classify_structured_uses_wrapper_parse_and_raw_text_for_thinking():
    assert classify_structured('{"a": 1}', {"a": 1}, None) == "json_valid"
    assert classify_structured('{"a": ', None, ValueError("bad json")) == "json_invalid"
    assert classify_structured("", None, None) == "json_invalid"
    # Thinking in the raw text is a failure even when the wrapper managed to parse an object.
    assert classify_structured('<think>x</think>{"a": 1}', {"a": 1}, None) == "thinking_present"

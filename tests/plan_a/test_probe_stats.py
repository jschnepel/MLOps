"""Protect the probe's pure measurement logic in scripts/probe_stats.py (T02, AM-31).

The probe's report decides whether the model is acceptable, so a wrong statistic or a swallowed failure would
mislead the owner. These tests catch: a changed confidence interval, thinking output being stripped or counted as
valid, a cold-start timeout shown as latency, VRAM shown as 0 MB when it was not measured, a wrong percentile
index, and a malformed holdout seal being accepted. No model or GPU is needed.
"""

import pytest

from scripts.probe_stats import (
    classify_output,
    classify_structured,
    cold_cell,
    has_thinking,
    mb_or_not_measured,
    p95_index,
    seal_problem,
    summarize,
    vram_row,
    wilson,
)


def test_wilson_known_values():
    # 27 of 30 at 95%: pins the formula and z so an "improvement" to the interval is noticed.
    lo, hi = wilson(27, 30)
    assert round(lo, 3) == 0.744
    assert round(hi, 3) == 0.965


def test_wilson_zero_and_full():
    # The interval must stay inside [0, 1] at the extremes, where the normal approximation would not.
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
    # Nearest-rank: ceil(0.95 * n) - 1, so n=20 gives index 18 and a single item gives index 0.
    assert p95_index(1) == 0
    assert p95_index(2) == 1
    assert p95_index(20) == 18
    assert p95_index(100) == 94


def test_summarize_counts_metadata_thinking_and_separates_cold():
    # Row 1 is the cold call, row 2 has thinking only in message metadata, row 3 has a <think> tag in the text.
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
    # The 50 s cold call is excluded; of the warm [4.0, 5.0] the median picks the upper value.
    assert s["warm_p50"] == 5.0 and s["warm_p95"] == 5.0


def test_has_thinking_text_tag_or_metadata():
    assert has_thinking('<think>x</think>{"a": 1}', None) is True
    assert has_thinking('{"a": 1}', "some reasoning") is True
    assert has_thinking('{"a": 1}', None) is False
    assert has_thinking('{"a": 1}', "") is False  # an empty reasoning field is not thinking


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
    # Thinking in a repair call must be counted on its own: it fails the no-thinking setting even when the
    # first pass was clean (AM-31).
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


def _row(cold: bool, seconds: float, error: str | None) -> dict:
    """Build one probe result row, with all-passing fields unless `error` is set."""
    return {
        "cold": cold,
        "seconds": seconds,
        "kind": "error" if error else "json_valid",
        "schema_valid": error is None,
        "repaired_valid": error is None,
        "thinking_in_metadata": False,
        "error": error,
    }


def test_cold_row_uses_first_row_only_without_error():
    ok = summarize([_row(True, 53.2, None), _row(False, 4.0, None)])
    assert ok["cold_seconds"] == 53.2 and ok["cold_error"] is None
    assert cold_cell(ok) == "53.2 s"


def test_cold_row_renders_the_error_not_a_timeout_as_latency():
    # A call that hit the 60 s cap took "60.01 s" only because we gave up; reporting that as a cold-start latency
    # would understate a real failure (final review M4, fix F5).
    s = summarize([_row(True, 60.01, "TimeoutError: "), _row(False, 4.0, None)])
    assert s["cold_seconds"] is None
    assert s["cold_error"] == "TimeoutError: "
    assert cold_cell(s) == "not measured (cold call failed: TimeoutError: )"
    assert "60.01" not in cold_cell(s)


# Stand-in hashes: one repeated hex digit per name keeps the seal examples readable. "c" is the holdout cases file.
EXPECTED_PROMPTS = {"incident-draft-v1.md": "a" * 64, "schema-repair-v1.md": "b" * 64}
GOOD_SEAL = f"{'c' * 64}  holdout-cases.jsonl\n{'a' * 64}  incident-draft-v1.md\n{'b' * 64}  schema-repair-v1.md\n"


def test_seal_problem_accepts_well_formed_seal():
    assert seal_problem(GOOD_SEAL, EXPECTED_PROMPTS) is None


def test_seal_problem_names_the_failing_line():
    # Each variant breaks exactly one line, and the message must point at that line so the owner can fix it.
    assert "3 lines" in (seal_problem("", EXPECTED_PROMPTS) or "")
    two = "\n".join(GOOD_SEAL.splitlines()[:2]) + "\n"
    assert "3 lines" in (seal_problem(two, EXPECTED_PROMPTS) or "")
    bad1 = GOOD_SEAL.replace("c" * 64, "C" * 64)  # uppercase hex is rejected
    assert (seal_problem(bad1, EXPECTED_PROMPTS) or "").startswith("line 1")
    bad2 = GOOD_SEAL.replace("a" * 64, "d" * 64)  # well formed but not the pinned draft-prompt hash
    assert (seal_problem(bad2, EXPECTED_PROMPTS) or "").startswith("line 2")
    bad3 = GOOD_SEAL.replace("  schema-repair-v1.md", " schema-repair-v1.md")  # one space instead of two
    assert (seal_problem(bad3, EXPECTED_PROMPTS) or "").startswith("line 3")


def test_probe_main_refuses_malformed_or_missing_seal(tmp_path, monkeypatch, capsys):
    from scripts import probe

    seal = tmp_path / "holdout.sha256"
    seal.write_text("not a seal\n", encoding="utf-8")
    monkeypatch.setattr(probe, "SEAL", seal)
    # model_digest is the first call that touches Ollama; reaching it means the seal gate did not stop the run.
    monkeypatch.setattr(probe, "model_digest", lambda: pytest.fail("network reached past the seal gate"))
    assert probe.main() == 2
    assert "line" in capsys.readouterr().err
    monkeypatch.setattr(probe, "SEAL", tmp_path / "missing.sha256")
    assert probe.main() == 2
    assert "missing" in capsys.readouterr().err

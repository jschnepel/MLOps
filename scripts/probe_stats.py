"""Pure functions used by the probe and its tests. Stdlib only.

Everything that can be computed without a model lives here, away from scripts/probe.py, so it is unit-tested
(tests/plan_a/test_probe_stats.py) without Ollama or a GPU. The recurring rule (AM-31): thinking output is a
failure of the no-thinking setting; it is counted and reported, never stripped to make a result pass.
"""

from __future__ import annotations

import json
import math
import re


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for k successes in n trials, at 95% confidence by default.

    Wilson is used instead of the normal approximation because the probe has few inputs (AM-31 requires at least 30) and
    pass rates near 0% or 100%, where the normal interval is too narrow and can leave [0, 1].

    Raises:
        ValueError: if n is not positive or k is outside 0..n.
    """
    if n <= 0 or k < 0 or k > n:
        raise ValueError("need 0 <= k <= n and n > 0")
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def classify_output(text: str) -> str:
    """Classify raw model text as "thinking_present", "json_invalid" or "json_valid".

    Thinking content is a failure of the no-thinking setting, never stripped: removing the tag and parsing the
    rest would report a pass for output that violates the configuration under test.
    """
    if "<think>" in text or "</think>" in text:
        return "thinking_present"
    try:
        json.loads(text)
    except json.JSONDecodeError:
        return "json_invalid"
    return "json_valid"


def classify_structured(raw_text: str, parsed: object, parsing_error: object) -> str:
    """Classify a with_structured_output(include_raw=True) result.

    Validity comes from the wrapper's own parse (parsed / parsing_error); thinking is checked on the raw
    text and counts as invalid even when the wrapper produced an object (never stripped).
    """
    if classify_output(raw_text) == "thinking_present":
        return "thinking_present"
    if parsing_error is not None or parsed is None:
        return "json_invalid"
    return "json_valid"


def has_thinking(text: str, reasoning_content: object) -> bool:
    """Thinking in the output text (a <think> tag) or in the message metadata; counted, never stripped."""
    return classify_output(text) == "thinking_present" or bool(reasoning_content)


# Shown instead of a number whenever VRAM could not be read; reporting 0 MB would claim a measurement we did not make.
NOT_MEASURED_VRAM = "not measured (nvidia-smi unavailable)"
# Seconds between VRAM samples while a call is pending; short enough to catch a peak, long enough not to load the GPU.
VRAM_INTERVAL_S = 0.5


def mb_or_not_measured(mb: int | None) -> str:
    """Format a megabyte reading, or the not-measured text for None."""
    return NOT_MEASURED_VRAM if mb is None else f"{mb} MB"


def vram_row(samples: list[int], gpu_name: str | None) -> str:
    """Markdown row for peak VRAM; no samples renders 'not measured', never 0 MB."""
    if not samples:
        return f"| Peak VRAM | {NOT_MEASURED_VRAM} | |"
    gpu = gpu_name or "GPU name unavailable"
    return (
        f"| Peak VRAM (max of {len(samples)} whole-GPU samples at {VRAM_INTERVAL_S} s during calls, {gpu}) "
        f"| {max(samples)} MB | |"
    )


def p95_index(n: int) -> int:
    """Index of the 95th percentile in a sorted list of n items (nearest-rank, clamped)."""
    if n <= 0:
        raise ValueError("n must be positive")
    return min(n - 1, max(0, math.ceil(0.95 * n) - 1))


def summarize(results: list[dict]) -> dict:
    """Aggregate per-input result rows into the counts and latencies the report shows.

    Cold and errored calls are left out of the warm latency percentiles: the first call measures a model load,
    and a timeout is a failure, not a latency.
    """
    n = len(results)
    warm = sorted(r["seconds"] for r in results if not r["cold"] and r["error"] is None)
    cold_row = next((r for r in results if r["cold"]), None)
    return {
        "n": n,
        "json_valid": sum(r["kind"] == "json_valid" for r in results),
        "schema_valid": sum(bool(r["schema_valid"]) for r in results),
        "repaired_valid": sum(bool(r["repaired_valid"]) for r in results),
        "thinking_any": sum(r["kind"] == "thinking_present" or bool(r["thinking_in_metadata"]) for r in results),
        "repair_calls": sum(bool(r.get("repair_called")) for r in results),
        "thinking_repair": sum(bool(r.get("repair_thinking")) for r in results),
        "errors": [r for r in results if r["error"]],
        "cold_seconds": cold_row["seconds"] if cold_row is not None and cold_row["error"] is None else None,
        "cold_error": cold_row["error"] if cold_row is not None else None,
        "warm_p50": warm[len(warm) // 2] if warm else None,  # upper median when the count is even
        "warm_p95": warm[p95_index(len(warm))] if warm else None,
    }


def cold_cell(summary: dict) -> str:
    """Cold-start cell: a latency only when the cold call succeeded; otherwise its error, never a timeout as latency."""
    if summary["cold_seconds"] is not None:
        return f"{summary['cold_seconds']} s"
    if summary.get("cold_error"):
        return f"not measured (cold call failed: {summary['cold_error']})"
    return "not measured (no cold call)"


# One seal line in `sha256sum` text format: 64 lowercase hex digits, two spaces, then a file name.
SEAL_LINE = re.compile(r"[0-9a-f]{64}  \S+")


def seal_problem(text: str, expected: dict[str, str]) -> str | None:
    """None if evals/holdout.sha256 is well formed, else a message naming the failing line.

    Exactly 3 lines of `<sha256>  <name>`; lines 2-3 must be `<expected hash>  <name>` for the two prompts,
    in the order of `expected`.
    """
    lines = text.splitlines()
    if len(lines) != 3:
        return f"seal must have exactly 3 lines, found {len(lines)}"
    for number, line in enumerate(lines, start=1):
        if not SEAL_LINE.fullmatch(line):
            return f"line {number} is not '<64 lowercase hex>  <name>': {line!r}"
    for number, (name, digest) in enumerate(expected.items(), start=2):
        if lines[number - 1] != f"{digest}  {name}":
            return f"line {number} must be '{digest}  {name}', found {lines[number - 1]!r}"
    return None

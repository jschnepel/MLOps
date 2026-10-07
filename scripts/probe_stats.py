"""Pure functions used by the probe and its tests. Stdlib only."""

from __future__ import annotations

import json
import math


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for k successes in n trials."""
    if n <= 0 or k < 0 or k > n:
        raise ValueError("need 0 <= k <= n and n > 0")
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def classify_output(text: str) -> str:
    """Thinking content is a failure of the no-thinking setting, never stripped."""
    if "<think>" in text or "</think>" in text:
        return "thinking_present"
    try:
        json.loads(text)
    except json.JSONDecodeError:
        return "json_invalid"
    return "json_valid"


def has_thinking(text: str, reasoning_content: object) -> bool:
    """Thinking in the output text (a <think> tag) or in the message metadata; counted, never stripped."""
    return classify_output(text) == "thinking_present" or bool(reasoning_content)


NOT_MEASURED_VRAM = "not measured (nvidia-smi unavailable)"
VRAM_INTERVAL_S = 0.5


def mb_or_not_measured(mb: int | None) -> str:
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
    n = len(results)
    warm = sorted(r["seconds"] for r in results if not r["cold"] and r["error"] is None)
    cold = next((r["seconds"] for r in results if r["cold"]), None)
    return {
        "n": n,
        "json_valid": sum(r["kind"] == "json_valid" for r in results),
        "schema_valid": sum(bool(r["schema_valid"]) for r in results),
        "repaired_valid": sum(bool(r["repaired_valid"]) for r in results),
        "thinking_any": sum(r["kind"] == "thinking_present" or bool(r["thinking_in_metadata"]) for r in results),
        "repair_calls": sum(bool(r.get("repair_called")) for r in results),
        "thinking_repair": sum(bool(r.get("repair_thinking")) for r in results),
        "errors": [r for r in results if r["error"]],
        "cold_seconds": cold,
        "warm_p50": warm[len(warm) // 2] if warm else None,
        "warm_p95": warm[p95_index(len(warm))] if warm else None,
    }

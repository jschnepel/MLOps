"""Measure qwen3:8b in the AM-31 drafting profile. Run in an ISOLATED environment:

uv run --isolated --no-project --python 3.13 --with "langchain-ollama==1.1.0" --with "jsonschema" python -I scripts/probe.py

T02 / R081: the owner runs this once, by hand, against a local Ollama, and decides from the report whether the
model and prompts are acceptable. It is never run in CI. The isolated environment (`--isolated --no-project`)
keeps the measured package versions independent of the workspace lockfile, and `-I` stops stray environment
variables or a working-directory module from changing what is imported; the pinned versions are recorded in
reports/model-probe-freeze.txt.

Preconditions: evals/holdout.sha256 exists (T03 sealed), Ollama is running. Writes
reports/model-probe-qwen3-8b.md, reports/model-probe-freeze.txt, data/model-pins.json.
This is measurement, not prompt tuning: the prompts are the sealed starters, unchanged.
The model is unloaded first so the first call is a true cold start.

Measured configuration (AM-31): ChatOllama(reasoning=False, num_ctx=16384, num_predict=1000, temperature=0)
wrapped in with_structured_output(<model-draft schema>, method="json_schema", include_raw=True), plus
application-side jsonschema validation of the parsed object. First-pass, repair and repeat calls use
that wrapper; the mid-generation cancel and the following `ok` call use the same ChatOllama unwrapped.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.metadata
import json
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# `python -I` drops the script directory from sys.path, so put the repository root on it explicitly; without this
# the `scripts.*` imports below fail when the probe is run the documented way.
sys.path.insert(0, str(ROOT))
from scripts.probe_stats import (
    VRAM_INTERVAL_S,
    classify_structured,
    cold_cell,
    has_thinking,
    mb_or_not_measured,
    seal_problem,
    summarize,
    vram_row,
    wilson,
)
from scripts.seal import sha256_of

MODEL = "qwen3:8b"
# Loopback only: the probe must never send evidence or prompts to a remote host.
OLLAMA = "http://127.0.0.1:11434"
# Hard cap per model call so one stuck generation cannot stall the run (T02 "bound every probe call"). It is the
# same 60 s cap the model_permit release rule refers to (AM-12), so a call that exceeds it counts as a failure.
TIMEOUT_S = 60
PROMPT_DRAFT = ROOT / "handoff/prompts/incident-draft-v1.md"
PROMPT_REPAIR = ROOT / "handoff/prompts/schema-repair-v1.md"
SCHEMA = ROOT / "schemas/model-draft.schema.json"
SEAL = ROOT / "evals/holdout.sha256"
# sha256 of the two sealed starter prompts. They duplicate lines 2-3 of evals/holdout.sha256 on purpose: main()
# refuses to run unless the seal file AND the prompt files on disk both match, so the probe can never measure a
# prompt that was edited after sealing (AM-50).
EXPECTED = {
    PROMPT_DRAFT.name: "e3c26da349dcb0a9bfafb6c786a06f15fece389c21fa63b1b64fef7659b6a942",
    PROMPT_REPAIR.name: "8b6658eb0f08136699b78e7ab1d76972f88f4399db720e92e5be5335b0c7c343",
}


def ollama_json(path: str, payload: dict | None = None) -> dict:
    """GET `path` from the local Ollama (POST with `payload` as JSON when one is given) and return the JSON reply."""
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        OLLAMA + path, data=data, headers={"Content-Type": "application/json"}, method="POST" if data else "GET"
    )
    # Socket-level backstop only. It is longer than TIMEOUT_S because unloading and listing models are not bounded
    # by the per-call asyncio timeout used for generation.
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def model_digest() -> str:
    """/api/tags lists installed models with their digests; /api/show does not carry one."""
    for m in ollama_json("/api/tags").get("models", []):
        if m.get("name") == MODEL or m.get("model") == MODEL:
            return m["digest"]
    raise SystemExit(f"{MODEL} not found in /api/tags")


def unload_model() -> None:
    """keep_alive=0 on a generate request unloads the model so the next call is cold."""
    ollama_json("/api/generate", {"model": MODEL, "keep_alive": 0})


def _nvidia_smi(query: str) -> str | None:
    """First line of an nvidia-smi query, or None when nvidia-smi is missing or fails.

    Only the first GPU is reported on a multi-GPU machine; the report labels the figure with that GPU's name.
    """
    try:
        out = subprocess.run(
            ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if out.returncode != 0:
            return None
        return out.stdout.strip().splitlines()[0].strip()
    except Exception:  # noqa: BLE001 - no driver, no GPU or a hung query all mean "not measured", never a crash
        return None


def vram_mb() -> int | None:
    """Whole-GPU memory.used in MB, or None (never 0) when it cannot be read."""
    value = _nvidia_smi("memory.used")
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def gpu_name() -> str | None:
    """Name of the first GPU, or None when nvidia-smi is unavailable."""
    return _nvidia_smi("name")


class VramSampler:
    """Samples whole-GPU memory.used every VRAM_INTERVAL_S seconds while a model call is pending."""

    def __init__(self) -> None:
        self.samples: list[int] = []

    async def during(self, awaitable):
        """Await `awaitable` while a background task samples VRAM; return its result and stop sampling."""
        stop = asyncio.Event()

        async def sample() -> None:
            while not stop.is_set():
                value = await asyncio.to_thread(vram_mb)
                if value is not None:
                    self.samples.append(value)
                # Sleep until the next tick or until `stop` is set. The timeout firing is the normal tick, not an error.
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), VRAM_INTERVAL_S)

        sampler = asyncio.create_task(sample())
        try:
            return await awaitable
        finally:
            stop.set()
            await sampler


async def run_probe(cases: list[dict]) -> dict:
    """Run every measurement against the live model and return the raw data that render_report() formats.

    Order matters: first-pass and repair calls over all cases (the first is the cold start), then three repeats
    of five cases to test determinism, then a mid-generation cancel followed by a normal call to see whether the
    model recovers promptly. Nothing is retried or tuned; failures are recorded as results, not raised.
    """
    # Imported here so the stdlib-only helpers above stay importable (and testable) without the probe's packages.
    import jsonschema
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_ollama import ChatOllama

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    llm = ChatOllama(model=MODEL, base_url=OLLAMA, reasoning=False, num_ctx=16384, num_predict=1000, temperature=0)
    # AM-31: constrained output (Ollama `format` = the JSON schema) plus application-side validation.
    drafter = llm.with_structured_output(schema, method="json_schema", include_raw=True)

    # The wrapper returns {"raw": AIMessage, "parsed": ..., "parsing_error": ...}; these helpers read the raw message
    # because validity and thinking are judged on what the model actually emitted.
    def raw_text(out: dict) -> str:
        content = out["raw"].content
        return content if isinstance(content, str) else json.dumps(content)

    def raw_reasoning(out: dict) -> object:
        return out["raw"].additional_kwargs.get("reasoning_content")

    def schema_errors(parsed: object) -> list[str]:
        return [e.message for e in validator.iter_errors(parsed)]

    system = PROMPT_DRAFT.read_text(encoding="utf-8")
    repair_system = PROMPT_REPAIR.read_text(encoding="utf-8")
    results: list[dict] = []
    vram = VramSampler()
    # Unload first so the first call pays the full model-load cost; otherwise a model left warm by an earlier
    # session would make the reported cold-start latency look far better than a real first request.
    unload_model()
    for i, c in enumerate(cases):
        user = json.dumps({"request": c["request_text"], "evidence": c["evidence"]}, ensure_ascii=False)
        t0 = time.perf_counter()
        text, err, meta_thinking = "", None, False
        kind = "error"  # stays "error" if the call raises or times out, so the result row is still written
        parsed: object = None
        try:
            out = await vram.during(
                asyncio.wait_for(
                    drafter.ainvoke([SystemMessage(content=system), HumanMessage(content=user)]), timeout=TIMEOUT_S
                )
            )
            text = raw_text(out)
            meta_thinking = bool(raw_reasoning(out))
            parsed = out["parsed"]
            kind = classify_structured(text, parsed, out["parsing_error"])
        except Exception as e:  # noqa: BLE001 - a timeout or connection error is a measured outcome, so record it
            err = f"{type(e).__name__}: {e}"
        dt = time.perf_counter() - t0
        errors: list[str] = []
        schema_ok = False
        if kind == "json_valid":
            errors = schema_errors(parsed)
            schema_ok = not errors
        repaired_ok = schema_ok
        repair_called = repair_thinking = False
        # One repair attempt per failed first pass (AM-31). A call that errored or timed out is not repaired: there
        # is no output to repair, and retrying would hide the failure.
        if not schema_ok and err is None:
            repair_called = True
            repair_user = json.dumps(
                # Cap at 10 messages to keep the repair prompt small; with no schema errors (unparseable or
                # thinking output) the failure kind is the only reason there is to give.
                {"invalid_output": text, "validation_errors": errors[:10] or [kind], "evidence": c["evidence"]},
                ensure_ascii=False,
            )
            try:
                fix = await vram.during(
                    asyncio.wait_for(
                        drafter.ainvoke([SystemMessage(content=repair_system), HumanMessage(content=repair_user)]),
                        timeout=TIMEOUT_S,
                    )
                )
                ftext = raw_text(fix)
                repair_thinking = has_thinking(ftext, raw_reasoning(fix))
                fkind = classify_structured(ftext, fix["parsed"], fix["parsing_error"])
                repaired_ok = fkind == "json_valid" and not schema_errors(fix["parsed"])
            except Exception:  # noqa: BLE001 - a repair that errors or times out simply counts as not repaired
                repaired_ok = False
        results.append(
            {
                "probe_id": c["probe_id"],
                "cold": i == 0,
                "seconds": round(dt, 2),
                "kind": kind,
                "schema_valid": schema_ok,
                "repaired_valid": repaired_ok,
                "thinking_in_metadata": meta_thinking,
                "repair_called": repair_called,
                "repair_thinking": repair_thinking,
                "error": err,
            }
        )
    # Determinism check: with temperature=0 the same input should give byte-identical output. Five inputs times
    # three calls is enough to expose nondeterminism without lengthening the run much. These calls also count
    # toward the thinking totals, because thinking on any call breaks the no-thinking setting.
    repeats = []
    repeat_errors: list[str] = []
    extra_thinking = extra_calls = 0
    for c in cases[:5]:
        user = json.dumps({"request": c["request_text"], "evidence": c["evidence"]}, ensure_ascii=False)
        outs = []
        try:
            for _ in range(3):
                rep_out = await vram.during(
                    asyncio.wait_for(
                        drafter.ainvoke([SystemMessage(content=system), HumanMessage(content=user)]),
                        timeout=TIMEOUT_S,
                    )
                )
                rtext = raw_text(rep_out)
                extra_calls += 1
                extra_thinking += has_thinking(rtext, raw_reasoning(rep_out))
                outs.append(rtext)
            repeats.append(len(set(outs)) == 1)
        except Exception as e:  # noqa: BLE001 - one failed repeat must not abort the remaining measurements
            repeats.append(False)
            repeat_errors.append(f"{c['probe_id']}: {type(e).__name__}: {e}")
    # Cancellation check (feeds the model_permit release rule, AM-12): start a deliberately long generation, cancel
    # it after 3 s (long enough for generation to be under way), then see how fast the next ordinary call is and
    # whether Ollama still reports the model busy. The plain ChatOllama is used, not the structured wrapper, because
    # the prompt asks for prose rather than a draft.
    cancel_error = None
    task = asyncio.create_task(
        llm.ainvoke(
            [
                SystemMessage(content=system),
                HumanMessage(content="Write a very long incident narrative with 40 numbered sections."),
            ]
        )
    )
    await vram.during(asyncio.sleep(3))
    task.cancel()
    # Wait for the cancelled task to unwind; the CancelledError (or any late error) is expected and not a failure.
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await asyncio.wait_for(task, timeout=TIMEOUT_S)
    vram_after_cancel = vram_mb()
    next_start: float | None = None
    ps_after_cancel: dict = {}
    t1 = time.perf_counter()
    try:
        ps_after_cancel = ollama_json("/api/ps")
        ok = await vram.during(
            asyncio.wait_for(llm.ainvoke([HumanMessage(content="Reply with the single word ok.")]), timeout=TIMEOUT_S)
        )
        otext = ok.content if isinstance(ok.content, str) else json.dumps(ok.content)
        extra_calls += 1
        extra_thinking += has_thinking(otext, ok.additional_kwargs.get("reasoning_content"))
        next_start = round(time.perf_counter() - t1, 2)
    except Exception as e:  # noqa: BLE001 - report the failure in the cancel row instead of losing the other data
        cancel_error = f"{type(e).__name__}: {e}"
    return {
        "results": results,
        "vram_samples": vram.samples,
        "gpu_name": gpu_name(),
        "vram_after_cancel_mb": vram_after_cancel,
        "repeat_identical": repeats,
        "ps_after_cancel": ps_after_cancel,
        "next_call_seconds_after_cancel": next_start,
        "repeat_errors": repeat_errors,
        "cancel_error": cancel_error,
        "extra_thinking_calls": extra_thinking,
        "extra_calls": extra_calls,
    }


def render_report(data: dict, digest: str, version: str, probed_at: str) -> str:
    """Format the measurements as the markdown report the owner reads to decide (R081).

    The two bracketed "Owner decision" lines at the end are deliberately left unfilled: the probe measures, the
    owner chooses whether to proceed and which permit release rule to adopt.
    """
    s = summarize(data["results"])
    n = s["n"]
    lo1, hi1 = wilson(s["json_valid"], n)
    lo2, hi2 = wilson(s["schema_valid"], n)
    lo3, hi3 = wilson(s["repaired_valid"], n)
    return f"""# Model probe: {MODEL} (AM-31, T02)

Measurement only; prompts unchanged (sha256 verified against the hashes pinned in probe.py; evals/holdout.sha256 present). Distinct inputs: {n}. Date: {probed_at}.
Configuration measured (AM-31): model `{MODEL}`, digest `{digest}`, Ollama {version}, `ChatOllama(reasoning=False, num_ctx=16384, num_predict=1000, temperature=0)` wrapped in `with_structured_output(schemas/model-draft.schema.json, method="json_schema", include_raw=True)`, plus application-side jsonschema validation of the parsed object. First-pass, repair and repeat calls use the wrapper; JSON-valid means the wrapper parsed an object (`parsing_error` is None) and the raw text has no thinking. The mid-generation cancel and the following `ok` call use the same ChatOllama unwrapped. {TIMEOUT_S}s cap per call. Interpreter: {sys.version.split()[0]}. Model unloaded before the first call.

| Metric | Value | Wilson 95% CI |
|---|---|---|
| JSON-valid (first pass) | {s["json_valid"]}/{n} | [{lo1:.3f}, {hi1:.3f}] |
| Schema-valid (first pass) | {s["schema_valid"]}/{n} | [{lo2:.3f}, {hi2:.3f}] |
| Schema-valid after one repair | {s["repaired_valid"]}/{n} | [{lo3:.3f}, {hi3:.3f}] |
| Thinking present in first-pass outputs (text tag or metadata) | {s["thinking_any"]}/{n} inputs | any > 0 fails the no-thinking setting |
| Thinking present in repair outputs (text tag or metadata) | {s["thinking_repair"]}/{s["repair_calls"]} repair calls | any > 0 fails the no-thinking setting |
| Cold-start latency (after unload) | {cold_cell(s)} | |
| Warm latency p50 / p95 | {s["warm_p50"]} s / {s["warm_p95"]} s | |
{vram_row(data["vram_samples"], data["gpu_name"])}
| Thinking present in repeat and post-cancel outputs (text tag or metadata) | {data["extra_thinking_calls"]}/{data["extra_calls"]} calls | any > 0 fails the no-thinking setting |
| Identical outputs on 3 repeats (5 inputs) | {sum(data["repeat_identical"])}/5 | |
| Full `ok` call after mid-generation cancel, incl. /api/ps | {data["next_call_seconds_after_cancel"]} s | |

Whole-GPU memory.used immediately after cancel (nvidia-smi): {mb_or_not_measured(data["vram_after_cancel_mb"])}.
`/api/ps` immediately after cancel: `{json.dumps(data["ps_after_cancel"])[:300]}`

Errors: {[(e["probe_id"], e["error"]) for e in s["errors"]]}
Repeat errors: {data["repeat_errors"]}
Cancel/post-cancel error: {data["cancel_error"]}

Owner decision (R081): [proceed | change model | adjust prompts]
model_permit release rule (AM-12, chosen from the cancel row above): [release on cancel | hold until /api/ps idle or the 60 s cap]
"""


def main() -> int:
    """Check the seal and prompts, run the probe and write the report, pins and freeze file; return an exit code.

    Returns 2 without calling the model when a precondition fails (seal missing or malformed, prompt hash mismatch,
    fewer than 30 inputs), so a sealing mistake can never produce a report that looks valid.
    """
    if not SEAL.is_file():
        print(
            "evals/holdout.sha256 is missing: T03 must seal the holdout before the probe runs (AM-50)", file=sys.stderr
        )
        return 2
    problem = seal_problem(SEAL.read_text(encoding="utf-8"), EXPECTED)
    if problem is not None:
        print(f"evals/holdout.sha256 is malformed: {problem}; refusing to run (AM-50)", file=sys.stderr)
        return 2
    # The seal file only records hashes; this confirms the prompt files on disk still match them.
    for name, h in EXPECTED.items():
        actual = sha256_of(ROOT / "handoff/prompts" / name)
        if actual != h:
            print(f"prompt {name} hash {actual} != sealed/pinned {h}; refusing to run", file=sys.stderr)
            return 2
    # TODO(T46): rename the comprehension variable `l` (easily misread as 1) to `line`.
    cases = [json.loads(l) for l in (ROOT / "evals/probe/inputs.jsonl").read_text(encoding="utf-8").splitlines()]
    # AM-31 asks for at least 30 distinct inputs so the Wilson intervals in the report are meaningful.
    if len(cases) < 30:
        print("need >= 30 distinct inputs", file=sys.stderr)
        return 2
    digest = model_digest()
    version = ollama_json("/api/version").get("version", "unknown")
    probed_at = datetime.now(UTC).isoformat()
    data = asyncio.run(run_probe(cases))
    # data/model-pins.json records which exact model build and Ollama version were measured, so a later model
    # change is detectable.
    (ROOT / "reports/model-probe-qwen3-8b.md").write_text(
        render_report(data, digest, version, probed_at), encoding="utf-8", newline="\n"
    )
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data/model-pins.json").write_text(
        json.dumps({"model": MODEL, "digest": digest, "ollama_version": version, "probed_at": probed_at}, indent=2)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    # A pip-freeze-style record of the isolated environment, since it is not covered by the workspace lockfile.
    freeze = [f"python=={sys.version.split()[0]}"] + sorted(
        f"{d.metadata['Name']}=={d.version}" for d in importlib.metadata.distributions()
    )
    (ROOT / "reports/model-probe-freeze.txt").write_text("\n".join(freeze) + "\n", encoding="utf-8", newline="\n")
    print("wrote reports/model-probe-qwen3-8b.md, reports/model-probe-freeze.txt and data/model-pins.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

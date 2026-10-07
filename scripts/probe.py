"""Measure qwen3:8b in the AM-31 drafting profile. Run in an ISOLATED environment:

uv run --isolated --no-project --python 3.13 --with "langchain-ollama==1.1.0" --with "jsonschema" python -I scripts/probe.py

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
sys.path.insert(0, str(ROOT))
from scripts.probe_stats import (
    VRAM_INTERVAL_S,
    classify_structured,
    has_thinking,
    mb_or_not_measured,
    summarize,
    vram_row,
    wilson,
)
from scripts.seal import sha256_of

MODEL = "qwen3:8b"
OLLAMA = "http://127.0.0.1:11434"
TIMEOUT_S = 60
PROMPT_DRAFT = ROOT / "handoff/prompts/incident-draft-v1.md"
PROMPT_REPAIR = ROOT / "handoff/prompts/schema-repair-v1.md"
SCHEMA = ROOT / "schemas/model-draft.schema.json"
SEAL = ROOT / "evals/holdout.sha256"
EXPECTED = {
    PROMPT_DRAFT.name: "e3c26da349dcb0a9bfafb6c786a06f15fece389c21fa63b1b64fef7659b6a942",
    PROMPT_REPAIR.name: "8b6658eb0f08136699b78e7ab1d76972f88f4399db720e92e5be5335b0c7c343",
}


def ollama_json(path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        OLLAMA + path, data=data, headers={"Content-Type": "application/json"}, method="POST" if data else "GET"
    )
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
    """First line of an nvidia-smi query, or None when nvidia-smi is missing or fails."""
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
    except Exception:  # noqa: BLE001 - measurement only
        return None


def vram_mb() -> int | None:
    """Whole-GPU memory.used in MB, or None (never 0) when it cannot be read."""
    value = _nvidia_smi("memory.used")
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def gpu_name() -> str | None:
    return _nvidia_smi("name")


class VramSampler:
    """Samples whole-GPU memory.used every VRAM_INTERVAL_S seconds while a model call is pending."""

    def __init__(self) -> None:
        self.samples: list[int] = []

    async def during(self, awaitable):
        stop = asyncio.Event()

        async def sample() -> None:
            while not stop.is_set():
                value = await asyncio.to_thread(vram_mb)
                if value is not None:
                    self.samples.append(value)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), VRAM_INTERVAL_S)

        sampler = asyncio.create_task(sample())
        try:
            return await awaitable
        finally:
            stop.set()
            await sampler


async def run_probe(cases: list[dict]) -> dict:
    import jsonschema
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_ollama import ChatOllama

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    llm = ChatOllama(model=MODEL, base_url=OLLAMA, reasoning=False, num_ctx=16384, num_predict=1000, temperature=0)
    # AM-31: constrained output (Ollama `format` = the JSON schema) plus application-side validation.
    drafter = llm.with_structured_output(schema, method="json_schema", include_raw=True)

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
    unload_model()
    for i, c in enumerate(cases):
        user = json.dumps({"request": c["request_text"], "evidence": c["evidence"]}, ensure_ascii=False)
        t0 = time.perf_counter()
        text, err, meta_thinking = "", None, False
        kind = "error"
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
        except Exception as e:  # noqa: BLE001 - record, never hide
            err = f"{type(e).__name__}: {e}"
        dt = time.perf_counter() - t0
        errors: list[str] = []
        schema_ok = False
        if kind == "json_valid":
            errors = schema_errors(parsed)
            schema_ok = not errors
        repaired_ok = schema_ok
        repair_called = repair_thinking = False
        if not schema_ok and err is None:
            repair_called = True
            repair_user = json.dumps(
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
            except Exception:  # noqa: BLE001 - a failed repair is a measured failure
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
        except Exception as e:  # noqa: BLE001 - record, never abort the run
            repeats.append(False)
            repeat_errors.append(f"{c['probe_id']}: {type(e).__name__}: {e}")
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
    except Exception as e:  # noqa: BLE001 - record, still return
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
| Cold-start latency (after unload) | {s["cold_seconds"]} s | |
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
    if not SEAL.is_file():
        print(
            "evals/holdout.sha256 is missing: T03 must seal the holdout before the probe runs (AM-50)", file=sys.stderr
        )
        return 2
    for name, h in EXPECTED.items():
        actual = sha256_of(ROOT / "handoff/prompts" / name)
        if actual != h:
            print(f"prompt {name} hash {actual} != sealed {h}; refusing to run", file=sys.stderr)
            return 2
    cases = [json.loads(l) for l in (ROOT / "evals/probe/inputs.jsonl").read_text(encoding="utf-8").splitlines()]
    if len(cases) < 30:
        print("need >= 30 distinct inputs", file=sys.stderr)
        return 2
    digest = model_digest()
    version = ollama_json("/api/version").get("version", "unknown")
    probed_at = datetime.now(UTC).isoformat()
    data = asyncio.run(run_probe(cases))
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
    freeze = [f"python=={sys.version.split()[0]}"] + sorted(
        f"{d.metadata['Name']}=={d.version}" for d in importlib.metadata.distributions()
    )
    (ROOT / "reports/model-probe-freeze.txt").write_text("\n".join(freeze) + "\n", encoding="utf-8", newline="\n")
    print("wrote reports/model-probe-qwen3-8b.md, reports/model-probe-freeze.txt and data/model-pins.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

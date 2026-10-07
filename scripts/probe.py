"""Measure qwen3:8b for the drafting profile (AM-31). Run in an ISOLATED environment:

uv run --isolated --no-project --python 3.13 --with "langchain-ollama==1.1.0" --with "jsonschema" python -I scripts/probe.py

Preconditions: evals/holdout.sha256 exists (T03 sealed), Ollama is running. Writes
reports/model-probe-qwen3-8b.md, reports/model-probe-freeze.txt, data/model-pins.json.
This is measurement, not prompt tuning: the prompts are the sealed starters, unchanged.
The model is unloaded first so the first call is a true cold start.
"""
from __future__ import annotations

import asyncio
import importlib.metadata
import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.probe_stats import classify_output, summarize, wilson  # noqa: E402
from scripts.seal import sha256_of  # noqa: E402

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
    req = urllib.request.Request(OLLAMA + path, data=data, headers={"Content-Type": "application/json"}, method="POST" if data else "GET")
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


def vram_mb() -> int | None:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10, check=False)
        return int(out.stdout.strip().splitlines()[0])
    except Exception:  # noqa: BLE001 - measurement only
        return None


async def run_probe(cases: list[dict]) -> dict:
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_ollama import ChatOllama

    import jsonschema

    validator = jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
    llm = ChatOllama(model=MODEL, base_url=OLLAMA, reasoning=False, num_ctx=16384, num_predict=1000, temperature=0)
    system = PROMPT_DRAFT.read_text(encoding="utf-8")
    repair_system = PROMPT_REPAIR.read_text(encoding="utf-8")
    results: list[dict] = []
    peak = 0
    unload_model()
    for i, c in enumerate(cases):
        user = json.dumps({"request": c["request_text"], "evidence": c["evidence"]}, ensure_ascii=False)
        t0 = time.perf_counter()
        text, err, meta_thinking = "", None, False
        try:
            msg = await asyncio.wait_for(llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)]), timeout=TIMEOUT_S)
            text = msg.content if isinstance(msg.content, str) else json.dumps(msg.content)
            meta_thinking = bool(msg.additional_kwargs.get("reasoning_content"))
        except Exception as e:  # noqa: BLE001 - record, never hide
            err = f"{type(e).__name__}: {e}"
        dt = time.perf_counter() - t0
        kind = classify_output(text) if err is None else "error"
        errors: list[str] = []
        schema_ok = False
        if kind == "json_valid":
            errors = [e.message for e in validator.iter_errors(json.loads(text))]
            schema_ok = not errors
        repaired_ok = schema_ok
        if not schema_ok and err is None:
            repair_user = json.dumps({"invalid_output": text, "validation_errors": errors[:10] or [kind], "evidence": c["evidence"]}, ensure_ascii=False)
            try:
                fix = await asyncio.wait_for(llm.ainvoke([SystemMessage(content=repair_system), HumanMessage(content=repair_user)]), timeout=TIMEOUT_S)
                ftext = fix.content if isinstance(fix.content, str) else json.dumps(fix.content)
                repaired_ok = classify_output(ftext) == "json_valid" and not list(validator.iter_errors(json.loads(ftext)))
            except Exception:  # noqa: BLE001 - a failed repair is a measured failure
                repaired_ok = False
        peak = max(peak, vram_mb() or 0)
        results.append({"probe_id": c["probe_id"], "cold": i == 0, "seconds": round(dt, 2), "kind": kind, "schema_valid": schema_ok,
                        "repaired_valid": repaired_ok, "thinking_in_metadata": meta_thinking, "error": err})
    repeats = []
    for c in cases[:5]:
        user = json.dumps({"request": c["request_text"], "evidence": c["evidence"]}, ensure_ascii=False)
        outs = []
        for _ in range(3):
            msg = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
            outs.append(msg.content)
        repeats.append(len(set(outs)) == 1)
    task = asyncio.create_task(llm.ainvoke([SystemMessage(content=system), HumanMessage(content="Write a very long incident narrative with 40 numbered sections.")]))
    await asyncio.sleep(3)
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):  # noqa: BLE001
        pass
    t1 = time.perf_counter()
    ps_after_cancel = ollama_json("/api/ps")
    await llm.ainvoke([HumanMessage(content="Reply with the single word ok.")])
    next_start = time.perf_counter() - t1
    return {"results": results, "peak_vram_mb": peak, "repeat_identical": repeats, "ps_after_cancel": ps_after_cancel, "next_call_seconds_after_cancel": round(next_start, 2)}


def render_report(data: dict, digest: str, version: str, probed_at: str) -> str:
    s = summarize(data["results"])
    n = s["n"]
    lo1, hi1 = wilson(s["json_valid"], n)
    lo2, hi2 = wilson(s["schema_valid"], n)
    lo3, hi3 = wilson(s["repaired_valid"], n)
    return f"""# Model probe: {MODEL} (AM-31, T02)

Measurement only; prompts unchanged (sha256 verified against evals/holdout.sha256). Distinct inputs: {n}. Date: {probed_at}.
Ollama version: {version}. Model digest: `{digest}`. Interpreter: {sys.version.split()[0]}. Settings: reasoning=False, num_ctx=16384, num_predict=1000, temperature=0, {TIMEOUT_S}s cap per call. Model unloaded before the first call.

| Metric | Value | Wilson 95% CI |
|---|---|---|
| JSON-valid (first pass) | {s['json_valid']}/{n} | [{lo1:.3f}, {hi1:.3f}] |
| Schema-valid (first pass) | {s['schema_valid']}/{n} | [{lo2:.3f}, {hi2:.3f}] |
| Schema-valid after one repair | {s['repaired_valid']}/{n} | [{lo3:.3f}, {hi3:.3f}] |
| Thinking present (text tag or metadata) | {s['thinking_any']}/{n} | any > 0 fails the no-thinking setting |
| Cold-start latency (after unload) | {s['cold_seconds']} s | |
| Warm latency p50 / p95 | {s['warm_p50']} s / {s['warm_p95']} s | |
| Peak VRAM (nvidia-smi) | {data['peak_vram_mb']} MB | |
| Identical outputs on 3 repeats (5 inputs) | {sum(data['repeat_identical'])}/5 | |
| Next call start after mid-generation cancel | {data['next_call_seconds_after_cancel']} s | |

`/api/ps` immediately after cancel: `{json.dumps(data['ps_after_cancel'])[:300]}`

Errors: {[(e['probe_id'], e['error']) for e in s['errors']]}

Owner decision (R081): [proceed | change model | adjust prompts]
model_permit release rule (AM-12, chosen from the cancel row above): [release on cancel | hold until /api/ps idle or the 60 s cap]
"""


def main() -> int:
    if not SEAL.is_file():
        print("evals/holdout.sha256 is missing: T03 must seal the holdout before the probe runs (AM-50)", file=sys.stderr)
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
    probed_at = datetime.now(timezone.utc).isoformat()
    data = asyncio.run(run_probe(cases))
    (ROOT / "reports/model-probe-qwen3-8b.md").write_text(render_report(data, digest, version, probed_at), encoding="utf-8", newline="\n")
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data/model-pins.json").write_text(json.dumps({"model": MODEL, "digest": digest, "ollama_version": version, "probed_at": probed_at}, indent=2) + "\n", encoding="utf-8", newline="\n")
    freeze = [f"python=={sys.version.split()[0]}"] + sorted(f"{d.metadata['Name']}=={d.version}" for d in importlib.metadata.distributions())
    (ROOT / "reports/model-probe-freeze.txt").write_text("\n".join(freeze) + "\n", encoding="utf-8", newline="\n")
    print("wrote reports/model-probe-qwen3-8b.md, reports/model-probe-freeze.txt and data/model-pins.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

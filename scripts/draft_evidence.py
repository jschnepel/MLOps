"""Record real-model drafting evidence for T19 (DoD 1; R037, R036): the worker's own qwen3:8b route over the 60 probe
inputs. Run once, by hand, against local Ollama; never part of a gate (BS:593):

    uv run python -I scripts/draft_evidence.py

It drives `ops_worker.ollama_drafting.OllamaDraftGenerator` exactly as the worker builds it (`from_settings`: the
committed pin, `OPS_OLLAMA_URL`, loopback by default): `start()` verifies the digest and warms the model, then each
input is drafted with the v2 prompt and payload, validated, and repaired at most once. Every attempt is recorded
(seconds, rule names, kind), and the report gives first-pass and post-repair validity with Wilson 95% intervals, the
failure rules, the kinds accepted, latency, versions and hardware, and sample outputs.

Each probe input becomes the worker's request: its text, asset and an interval of its `hours` ending at its status
observation, with its one procedure section as the only evidence, cited as `<DOCUMENT_ID>:v<version>:<section>`. The
probe's status and alert records are not sent: the worker passes no asset data to the model until T20 (R028's note).
So that the twelve `injected` inputs still carry injected text, each also gets the tenant's injected corpus-1 section
(`ALPHA-VENDOR-PORTAL:v1:portal-note` for an A asset, `BETA-CONTRACTOR-MEMO:v1:memo-note` for a B asset), where the
worker would meet it: in the retrieved evidence (R036). Writes `reports/model/t19-real-run.md` and `.json`.

Thinking is counted, never stored or shown (BS:460): the text of an attempt whose rules include `thinking` is replaced
by a placeholder in the samples, so neither report file carries a model's reasoning.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import platform
import statistics
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ops_core import corpus, prompts
from ops_worker import ollama_drafting
from ops_worker.drafting import DraftRequest, EvidenceItem, ModelOutputInvalid, ModelUnavailable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # `python -I` leaves the repository root off the path, as in scripts/probe.py
from scripts.probe_stats import wilson

INPUTS = ROOT / "evals" / "probe" / "inputs.jsonl"
CORPUS = ROOT / "data" / "corpus"
OUT = ROOT / "reports" / "model"
WITHHELD = "<withheld: thinking>"  # stands in for the text of an attempt that showed thinking (BS:460)
INJECTED = {  # tenant prefix of the asset -> (corpus file, document id, version, section)
    "A": ("alpha-vendor-portal.md", "ALPHA-VENDOR-PORTAL", "1", "portal-note"),
    "B": ("beta-contractor-memo.md", "BETA-CONTRACTOR-MEMO", "1", "memo-note"),
}


def injected_section(asset_id: str) -> EvidenceItem:
    """The tenant's injected corpus-1 section as the worker's search would return it."""
    path, document_id, version, name = INJECTED[asset_id[0]]
    text = (CORPUS / path).read_text(encoding="utf-8")
    section = next(s for s in corpus.sections(text) if s.name == name)
    return EvidenceItem(f"{document_id}:v{version}:{name}", document_id, version, name, section.sha256, section.body)


def probe_case(row: Mapping[str, Any]) -> tuple[DraftRequest, list[EvidenceItem]]:
    """One probe input as the worker's request and evidence (see the module docstring)."""
    end = datetime.fromisoformat(row["evidence"]["status"]["observed_at"])
    request = DraftRequest(row["asset_id"], row["request_text"], end - timedelta(hours=row["hours"]), end)
    evidence = [
        EvidenceItem(
            f"{d['document_id']}:v{d['version']}:{d['section']}",
            d["document_id"],
            str(d["version"]),
            d["section"],
            hashlib.sha256(d["excerpt"].encode("utf-8")).hexdigest(),
            d["excerpt"],
        )
        for d in row["evidence"]["documents"]
    ]
    if row["scenario"] == "injected":
        evidence.append(injected_section(row["asset_id"]))
    return request, evidence


def shown_text(rules: Sequence[str], text: str) -> str:
    """The attempt's text as a report may carry it: a placeholder when the attempt showed thinking (BS:460)."""
    return WITHHELD if "thinking" in rules else text


def outcome(attempts: Sequence[Mapping[str, Any]], error: str | None) -> str:
    """`first_pass`, `repaired`, `invalid` (the repair failed too) or `unavailable` (an attempt got no reply)."""
    if error == "unavailable":
        return "unavailable"
    if attempts and attempts[-1]["kind"] is not None:
        return "first_pass" if len(attempts) == 1 else "repaired"
    return "invalid"


def summarize(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The report's figures from the per-input records."""
    n = len(cases)
    outcomes = Counter(c["outcome"] for c in cases)
    first = outcomes["first_pass"]
    after = first + outcomes["repaired"]
    first_seconds = sorted(c["attempts"][0]["seconds"] for c in cases if c["attempts"])
    by_scenario: dict[str, Counter[str]] = {}
    for c in cases:
        by_scenario.setdefault(c["scenario"], Counter())[c["outcome"]] += 1
    return {
        "n": n,
        "outcomes": dict(outcomes),
        "first_pass_valid": first,
        "first_pass_wilson": wilson(first, n),
        "post_repair_valid": after,
        "post_repair_wilson": wilson(after, n),
        "kinds_accepted": dict(Counter(c["kind"] for c in cases if c["kind"] is not None)),
        "clarifying_questions": sum(bool(c["clarify"]) for c in cases),
        "first_pass_rules": dict(Counter(r for c in cases if c["attempts"] for r in c["attempts"][0]["rules"])),
        "repair_rules": dict(Counter(r for c in cases if len(c["attempts"]) > 1 for r in c["attempts"][1]["rules"])),
        "repairs": sum(len(c["attempts"]) > 1 for c in cases),
        "thinking": sum("thinking" in a["rules"] for c in cases for a in c["attempts"]),
        "authority_key": sum("authority_key" in a["rules"] for c in cases for a in c["attempts"]),
        "first_pass_p50": statistics.median(first_seconds) if first_seconds else None,
        "first_pass_p95": first_seconds[int(0.95 * (len(first_seconds) - 1))] if first_seconds else None,
        "by_scenario": {k: dict(v) for k, v in sorted(by_scenario.items())},
    }


def gpu_name() -> str:
    """The first GPU's name, or `not measured` (nvidia-smi absent or failing)."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except OSError:
        return "not measured"
    return out.stdout.strip().splitlines()[0] if out.returncode == 0 and out.stdout.strip() else "not measured"


def render(meta: Mapping[str, Any], s: Mapping[str, Any], samples: Sequence[Mapping[str, Any]]) -> str:
    """The Markdown report."""
    lo1, hi1 = s["first_pass_wilson"]
    lo2, hi2 = s["post_repair_wilson"]
    lines = [
        "# T19 real-model drafting run (R037)",
        "",
        f"Recorded {meta['recorded_at']} by `scripts/draft_evidence.py`, once, by hand; not a gate (BS:593). The worker's",
        "own route (`OllamaDraftGenerator.from_settings`) over the 60 probe inputs, with the v2 prompts and payload.",
        "",
        "| Setting | Value |",
        "|---|---|",
        f"| Model, digest (pin = installed) | `{meta['model']}`, `{meta['digest']}` |",
        f"| Ollama | {meta['ollama_version']} (pin probed on {meta['pinned_ollama_version']}) |",
        f"| Packages | {meta['packages']} |",
        f"| Python, platform, GPU | {meta['python']}, {meta['platform']}, {meta['gpu']} |",
        f"| Parameters | {meta['parameters']} |",
        f"| Prompts | {meta['prompts']} |",
        f"| Warm-up (digest check and first call) | {meta['warm_up_seconds']} s |",
        "",
        "| Metric | Value | Wilson 95% CI |",
        "|---|---|---|",
        f"| Valid first pass | {s['first_pass_valid']}/{s['n']} | [{lo1:.3f}, {hi1:.3f}] |",
        f"| Valid after at most one repair | {s['post_repair_valid']}/{s['n']} | [{lo2:.3f}, {hi2:.3f}] |",
        f"| Outcomes | {s['outcomes']} | |",
        f"| Repairs asked | {s['repairs']} | |",
        f"| Kinds accepted | {s['kinds_accepted']} | |",
        f"| Abstentions asking a clarifying question | {s['clarifying_questions']} | |",
        f"| First-pass failure rules | {s['first_pass_rules']} | |",
        f"| Repair failure rules | {s['repair_rules']} | |",
        f"| Attempts showing thinking | {s['thinking']} | |",
        f"| Attempts naming an authority key (R036) | {s['authority_key']} | |",
        f"| First attempt p50 / p95 | {s['first_pass_p50']} s / {s['first_pass_p95']} s | |",
        f"| By scenario | {s['by_scenario']} | |",
        "",
        "Valid means `ops_core.draft_validation.validate` accepted the reply: the draft schema, `ModelDraft`, every",
        "evidence ID one this input offered, no thinking, no authority key. Validity is not support: whether a draft's",
        "claims follow from its evidence is T25's to grade (BS:452). No accepted draft can carry a field outside the",
        "schema, so none can name a tool, a grant, a role or a destination. Validity is judged by the application;",
        "whether Ollama's `format` grammar enforces the schema's `allOf`/`if`/`then`/`else` is not established and",
        "does not change this record.",
        "",
        "What was sent: each input's request text, asset, interval and its one procedure section, with the v2 payload.",
        "No asset status or alert records are sent (the worker passes none to the model until T20), so many drafts",
        "abstain for want of alert data. Each `injected` input also carries its tenant's injected corpus-1 section as",
        "retrieved evidence (`ALPHA-VENDOR-PORTAL:v1:portal-note` or `BETA-CONTRACTOR-MEMO:v1:memo-note`).",
        "One machine; not a capacity claim (BS:566).",
        "",
        "## Samples",
        "",
    ]
    for sample in samples:
        lines += [f"`{sample['probe_id']}` ({sample['scenario']}), {sample['label']}:", "", "```json", sample["text"]]
        lines += ["```", ""]
    return "\n".join(lines)


async def run() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Start the route, draft every input, and return the metadata, the per-input records and the samples."""
    records: list[ollama_drafting.Attempt] = []
    generator = ollama_drafting.OllamaDraftGenerator.from_settings(on_attempt=records.append)
    began = time.perf_counter()
    await generator.start()
    warm_up = round(time.perf_counter() - began, 2)
    rows = [json.loads(line) for line in INPUTS.read_text(encoding="utf-8").splitlines()]
    cases: list[dict[str, Any]] = []
    texts: list[tuple[dict[str, Any], list[ollama_drafting.Attempt]]] = []
    for row in rows:
        request, evidence = probe_case(row)
        records.clear()
        error = kind = None
        clarify = False
        try:
            draft = await generator.generate(request, evidence)
            kind, clarify = draft.kind, draft.clarification_requested
        except ModelUnavailable:
            error = "unavailable"
        except ModelOutputInvalid:
            error = "invalid"
        attempts = [{"number": a.number, "seconds": a.seconds, "rules": list(a.rules), "kind": a.kind} for a in records]
        case = {"probe_id": row["probe_id"], "scenario": row["scenario"], "kind": kind, "clarify": clarify}
        case.update(attempts=attempts, outcome=outcome(attempts, error))
        cases.append(case)
        texts.append((case, list(records)))
    samples: list[dict[str, Any]] = []
    for c, a in texts:  # the first accepted draft of each kind, a clarifying question counted as its own kind
        label = "accepted abstain with a question" if c["clarify"] else f"accepted {c['kind']}"
        if c["kind"] is not None and label not in {s["label"] for s in samples}:
            text = shown_text(a[-1].rules, a[-1].text)
            samples.append({"probe_id": c["probe_id"], "scenario": c["scenario"], "label": label, "text": text})
    failed = next(((c, a) for c, a in texts if a and a[0].rules), None)
    if failed is not None:
        c, a = failed
        label = f"failed first pass ({', '.join(a[0].rules)})"
        text = shown_text(a[0].rules, a[0].text)
        samples.append({"probe_id": c["probe_id"], "scenario": c["scenario"], "label": label, "text": text})
    meta = {
        "recorded_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "model": ollama_drafting.MODEL,
        "digest": generator.digest,
        "ollama_version": generator.ollama_version,
        "pinned_ollama_version": generator.pins.ollama_version,
        "packages": ", ".join(
            f"{p} {importlib.metadata.version(p)}" for p in ("langchain-ollama", "langchain-core", "ollama")
        ),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "gpu": gpu_name(),
        "parameters": (
            f"reasoning=False, num_ctx={ollama_drafting.NUM_CTX}, num_predict={ollama_drafting.NUM_PREDICT},"
            f" temperature=0, keep_alive={ollama_drafting.KEEP_ALIVE}, format=model-draft schema (json_schema),"
            f" {ollama_drafting.ATTEMPT_SECONDS:.0f} s per attempt, {ollama_drafting.BUDGET_SECONDS:.0f} s per draft"
        ),
        "prompts": ", ".join(
            f"{v} `{prompts.sha256(v)[:12]}…`" for v in (prompts.DRAFT_VERSION, prompts.REPAIR_VERSION)
        ),
        "warm_up_seconds": warm_up,
    }
    return meta, cases, samples


def main() -> int:
    """Run the evidence and write both report files."""
    meta, cases, samples = asyncio.run(run())
    summary = summarize(cases)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "t19-real-run.md").write_text(render(meta, summary, samples), encoding="utf-8", newline="\n")
    doc = {"meta": meta, "summary": summary, "cases": cases, "samples": samples}
    (OUT / "t19-real-run.json").write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"valid first pass {summary['first_pass_valid']}/{summary['n']}, after repair {summary['post_repair_valid']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

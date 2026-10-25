"""The real-run evidence script's pure parts, without a model (T19 DoD 1; R036, R037).

Catches: a probe input turned into another request or interval than the worker would build, an evidence ID the model
could not copy, an injected input without its tenant's injected corpus-1 section (R036 would then be untested on the
real model), a repaired or failed draft counted as a first-pass success, a report without its Wilson intervals or
without saying what was sent and that it is one machine, and an attempt that showed thinking having its raw text
written into the report (BS:460: thinking is counted, never stored or shown).
"""

import json
from pathlib import Path

from scripts import draft_evidence

ROOT = Path(__file__).resolve().parents[2]
ROWS = [
    json.loads(line) for line in (ROOT / "evals" / "probe" / "inputs.jsonl").read_text(encoding="utf-8").splitlines()
]


def test_a_probe_input_becomes_the_workers_request_and_evidence() -> None:
    row = ROWS[0]
    request, evidence = draft_evidence.probe_case(row)
    assert (request.asset_id, request.text, request.answer_only) == (row["asset_id"], row["request_text"], False)
    assert request.end_at.isoformat() == "2026-10-07T08:00:00+00:00"
    assert (request.end_at - request.start_at).total_seconds() == row["hours"] * 3600
    assert [e.evidence_id for e in evidence] == ["ALPHA-INCIDENT:v2:review"]
    assert evidence[0].excerpt == row["evidence"]["documents"][0]["excerpt"]


def test_every_injected_input_also_carries_its_tenants_injected_section() -> None:
    injected = [row for row in ROWS if row["scenario"] == "injected"]
    assert len(injected) == 12
    for row in injected:
        _, evidence = draft_evidence.probe_case(row)
        extra = evidence[-1]
        tenant = {"A": "ALPHA-VENDOR-PORTAL:v1:portal-note", "B": "BETA-CONTRACTOR-MEMO:v1:memo-note"}
        assert len(evidence) == 2 and extra.evidence_id == tenant[row["asset_id"][0]]
        assert "ASSISTANT" in extra.excerpt.upper() and extra.content_sha256 != "0" * 64


def test_outcomes_count_a_repair_and_a_failure_apart_from_a_first_pass() -> None:
    ok = {"kind": "proposal", "rules": []}
    bad = {"kind": None, "rules": ["schema"]}
    assert draft_evidence.outcome([ok], None) == "first_pass"
    assert draft_evidence.outcome([bad, ok], None) == "repaired"
    assert draft_evidence.outcome([bad, bad], "invalid") == "invalid"
    assert draft_evidence.outcome([], "unavailable") == "unavailable"


def test_the_summary_and_the_report_carry_the_rates_and_their_intervals() -> None:
    def case(outcome: str, kind: str | None, rules: list[list[str]], clarify: bool = False) -> dict[str, object]:
        attempts = [{"number": i + 1, "seconds": 2.0 + i, "rules": r, "kind": None} for i, r in enumerate(rules)]
        return {
            "probe_id": "PR-x",
            "scenario": "s",
            "kind": kind,
            "clarify": clarify,
            "attempts": attempts,
            "outcome": outcome,
        }

    cases = [
        case("first_pass", "proposal", [[]]),
        case("repaired", "abstain", [["schema"], []], clarify=True),
        case("invalid", None, [["not_offered"], ["thinking"]]),
    ]
    s = draft_evidence.summarize(cases)
    assert (s["first_pass_valid"], s["post_repair_valid"], s["n"], s["repairs"]) == (1, 2, 3, 2)
    assert s["first_pass_rules"] == {"schema": 1, "not_offered": 1} and s["repair_rules"] == {"thinking": 1}
    assert s["kinds_accepted"] == {"proposal": 1, "abstain": 1} and s["clarifying_questions"] == 1
    meta = dict.fromkeys(
        (
            "recorded_at",
            "model",
            "digest",
            "ollama_version",
            "pinned_ollama_version",
            "packages",
            "python",
            "platform",
            "gpu",
            "parameters",
            "prompts",
            "warm_up_seconds",
        ),
        "x",
    )
    report = draft_evidence.render(meta, s, [{"probe_id": "PR-x", "scenario": "s", "label": "accepted", "text": "{}"}])
    assert "| Valid first pass | 1/3 | [0.061, 0.792] |" in report
    assert "| Valid after at most one repair | 2/3 | [0.208, 0.939] |" in report
    assert "No asset status or alert records are sent" in report and "One machine; not a capacity claim" in report


def test_an_attempt_that_showed_thinking_has_its_text_withheld() -> None:
    secret = "<think>the model's private reasoning</think>"
    assert draft_evidence.shown_text(("schema", "thinking"), secret) == "<withheld: thinking>"
    assert draft_evidence.shown_text(("thinking",), secret) == "<withheld: thinking>"
    assert draft_evidence.shown_text(("schema",), "{bad}") == "{bad}"
    assert draft_evidence.shown_text((), '{"kind": "abstain"}') == '{"kind": "abstain"}'

"""The real-run evidence script's pure parts, without a model (T19 DoD 1; R036, R037).

Catches: a probe input turned into another request or interval than the worker would build, an evidence ID the model
could not copy, an injected input without its tenant's injected corpus-1 section (R036 would then be untested on the
real model), a repaired or failed draft counted as a first-pass success, a report without its Wilson intervals or
without saying what was sent and that it is one machine, and an attempt that showed thinking having its raw text
written into the report (BS:460: thinking is counted, never stored or shown).
"""

import json
import subprocess
from pathlib import Path

import pytest
from ops_worker import ollama_drafting

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


def _case(scenario: str, kind: str | None, clarify: bool, rules: list[list[str]], outcome: str) -> dict[str, object]:
    attempts = [{"number": i + 1, "seconds": 2.0, "rules": r, "kind": None} for i, r in enumerate(rules)]
    return {
        "probe_id": f"PR-{scenario}-{kind}-{clarify}",
        "scenario": scenario,
        "kind": kind,
        "clarify": clarify,
        "attempts": attempts,
        "outcome": outcome,
    }


CASES = [
    _case("injected", "proposal", False, [[]], "first_pass"),
    _case("injected", "abstain", True, [[]], "first_pass"),
    _case("injected", "abstain", False, [["schema"], []], "repaired"),
    _case("no_alerts", "abstain", True, [[]], "first_pass"),
    _case("no_alerts", None, False, [["not_json"], ["thinking"]], "invalid"),
]


def test_the_summary_gives_each_scenarios_kinds_with_questions_counted_within_abstentions() -> None:
    by = draft_evidence.summarize(CASES)["by_scenario"]
    assert by["injected"] == {
        "outcomes": {"first_pass": 2, "repaired": 1},
        "kinds": {"proposal": 1, "abstain": 2, "question": 1},
    }
    assert by["no_alerts"] == {"outcomes": {"first_pass": 1, "invalid": 1}, "kinds": {"abstain": 1, "question": 1}}


def _meta() -> dict[str, str]:
    keys = (
        "recorded_at model digest ollama_version pinned_ollama_version packages python platform gpu parameters prompts"
    )
    return dict.fromkeys([*keys.split(), "warm_up_seconds"], "x")


def test_the_report_tabulates_scenarios_and_says_what_injected_does_and_does_not_show() -> None:
    cited = {"probe_id": "PR-i", "scenario": "injected", "label": "accepted proposal", "text": INJECTED_ID_TEXT}
    plain = {"probe_id": "PR-p", "scenario": "no_alerts", "label": "accepted abstain", "text": "{}"}
    report = draft_evidence.render(_meta(), draft_evidence.summarize(CASES), [cited, plain])
    assert "| `injected` | 3 | {'first_pass': 2, 'repaired': 1} | 1 | 2 | 1 |" in report
    assert "The `injected` rows show validity, not resistance" in report
    assert "In the samples below, `PR-i` cites the injected note" in report
    assert "counts inline `<think>` tags in the reply text only" in report
    assert "(`not_json`)" in report and "destination field" in report
    quiet = draft_evidence.render(_meta(), draft_evidence.summarize(CASES), [plain])
    assert "No sample below cites the injected note." in quiet


INJECTED_ID_TEXT = '{"evidence_refs": ["ALPHA-VENDOR-PORTAL:v1:portal-note"]}'


def _attempt(number: int, rules: tuple[str, ...], kind: str | None, text: str) -> ollama_drafting.Attempt:
    return ollama_drafting.Attempt(number, 1.0, rules, kind, text)


def test_a_failed_first_pass_that_showed_thinking_reaches_the_samples_withheld() -> None:
    secret = "<think>private reasoning A</think>"
    case = _case("s", "abstain", False, [["thinking"], []], "repaired")
    attempts = [_attempt(1, ("thinking",), None, secret), _attempt(2, (), "abstain", '{"kind": "abstain"}')]
    samples = draft_evidence.choose_samples([(case, attempts)])
    assert [s["label"] for s in samples] == ["accepted abstain", "failed first pass (thinking)"]
    assert samples[1]["text"] == draft_evidence.WITHHELD and samples[0]["text"] == '{"kind": "abstain"}'
    assert "private reasoning" not in json.dumps(samples)


def test_an_accepted_sample_goes_through_the_same_guard() -> None:
    # An accepted attempt cannot show thinking in the real route; the guard is on the path regardless of that.
    secret = "<think>private reasoning B</think>"
    case = _case("s", "proposal", False, [["thinking"]], "first_pass")
    samples = draft_evidence.choose_samples([(case, [_attempt(1, ("thinking",), "proposal", secret)])])
    assert samples[0]["label"] == "accepted proposal" and samples[0]["text"] == draft_evidence.WITHHELD
    assert "private reasoning" not in json.dumps(samples)


def test_samples_take_the_first_of_each_kind_and_a_question_is_its_own_kind() -> None:
    texts = [
        (_case("s", "abstain", False, [[]], "first_pass"), [_attempt(1, (), "abstain", "a1")]),
        (_case("s", "abstain", True, [[]], "first_pass"), [_attempt(1, (), "abstain", "a2")]),
        (_case("s", "abstain", True, [[]], "first_pass"), [_attempt(1, (), "abstain", "a3")]),
        (_case("s", "proposal", False, [[]], "first_pass"), [_attempt(1, (), "proposal", "p1")]),
    ]
    got = [(s["label"], s["text"]) for s in draft_evidence.choose_samples(texts)]
    assert got == [
        ("accepted abstain", "a1"),
        ("accepted abstain with a question", "a2"),
        ("accepted proposal", "p1"),
    ]


def test_the_markdown_is_a_pure_function_of_the_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    samples = [{"probe_id": "PR-p", "scenario": "no_alerts", "label": "accepted abstain", "text": "{}"}]
    draft_evidence.write_reports({"meta": _meta(), "cases": CASES, "samples": samples}, tmp_path)
    first = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    doc = json.loads((tmp_path / "t19-real-run.json").read_text(encoding="utf-8"))
    assert doc["summary"] == json.loads(json.dumps(draft_evidence.summarize(CASES)))
    assert first["t19-real-run.md"].decode("utf-8") == draft_evidence.render(
        doc["meta"], draft_evidence.summarize(doc["cases"]), doc["samples"]
    )

    async def no_model() -> None:
        raise AssertionError("--from-json must not call the model")

    monkeypatch.setattr(draft_evidence, "run", no_model)
    monkeypatch.setattr(draft_evidence, "OUT", tmp_path)
    assert draft_evidence.main(["--from-json"]) == 0
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == first


def test_a_hung_nvidia_smi_is_not_measured_rather_than_a_lost_run(monkeypatch: pytest.MonkeyPatch) -> None:
    def hung(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired("nvidia-smi", 10)

    monkeypatch.setattr(draft_evidence.subprocess, "run", hung)
    assert draft_evidence.gpu_name() == "not measured"

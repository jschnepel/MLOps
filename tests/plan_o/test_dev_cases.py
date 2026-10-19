"""The development cases and their gold labels as committed (T23 DoD 1, R111; Plan O rulings 1-3).

Catches:
- a case the schema refuses, a schema the meta-schema refuses, or a schema rule no test refuses;
- a category mix other than ruling 2's (60 cases, 30 per tenant, every category in both tenants except `conflicting`,
  which is alpha's);
- a label citing a section that is not returnable for the case's tenant at its `as_of`, outside the asset's family, or
  of an injected document outside an injected case's allowed references;
- a returnable set that is no longer the hand-written anchor (the oracle alone would restate the SQL's rule);
- an asset of the other tenant outside a cross-tenant case, or a cross-tenant case that does not abstain;
- a proposal case whose interval holds no alert of its asset;
- a case outside the development split, without one, a row that is not an object, or a missing case file, that
  `scripts/verify_handoff.py` lets through or crashes on;
- a loader that accepts a row the schema refuses or a repeated id, or crashes on a malformed line;
- an edit to the file or its schema that was not made a reviewed new dev-set version (both hashes are pinned).
"""

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from ops_core import corpus, grading

from tests.plan_a.test_verify_handoff import _run_contracts, _tracked_copy
from tests.plan_l.test_corpus_files import RETURNABLE_AT_AS_OF

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "evals" / "dev" / "cases.jsonl"
CORPUS = ROOT / "data" / "corpus"
FIXTURE_CLOCK = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)  # the cards' fixture_clock (Plan O ruling 1)
# Pinned: a change to either file is a reviewed new dev-set version, like T18's query file (Plan O ruling 1).
CASES_SHA256 = "d5223686e93dbf33bf60caf4053e2bad9dd945c1bf2a52dfebee6f605edbe70e"
SCHEMA_SHA256 = "294bbd56ad0e5c44e77d9600b61aacead2d6710cd99c570a9f52fc42c313d5d2"
MIX = {
    "investigate_supported": 14,
    "answer_only": 8,
    "missing_source": 8,
    "retired_source": 8,
    "clarification": 6,
    "cross_tenant": 4,
    "injected": 4,
    "conflicting": 4,
    "numeric": 4,
}


def test_the_schema_is_a_2020_12_schema_and_every_row_satisfies_it() -> None:
    Draft202012Validator.check_schema(json.loads(grading.CASE_SCHEMA.read_text(encoding="utf-8")))
    cases = grading.load_cases(CASES)
    assert len(cases) == 60 and all(c.split == "development" for c in cases)
    assert [c.case_id for c in cases] == [f"DV-{n:03d}" for n in range(1, 61)]
    assert {c.as_of for c in cases} == {FIXTURE_CLOCK}


def test_the_file_is_lf_only_without_a_bom_and_both_hashes_are_pinned() -> None:
    raw = CASES.read_bytes()
    assert b"\r" not in raw and not raw.startswith(b"\xef\xbb\xbf") and raw.endswith(b"\n")
    assert hashlib.sha256(raw).hexdigest() == CASES_SHA256
    assert hashlib.sha256(grading.CASE_SCHEMA.read_bytes()).hexdigest() == SCHEMA_SHA256


def test_the_mix_is_ruling_2s() -> None:
    cases = grading.load_cases(CASES)
    assert Counter(c.category for c in cases) == MIX
    assert Counter(c.tenant for c in cases) == {"alpha": 30, "beta": 30}
    for tenant in ("alpha", "beta"):
        present = {c.category for c in cases if c.tenant == tenant}
        assert present == (set(MIX) if tenant == "alpha" else set(MIX) - {"conflicting"}), tenant
    assert all(c.intent == "answer_only" and c.expected_kind == "answer" for c in cases if c.category == "answer_only")
    assert all(c.expected_kind == "proposal" for c in cases if c.category == "investigate_supported")
    abstaining = {"missing_source", "cross_tenant", "clarification", "conflicting"}
    assert all(c.expected_kind == "abstain" for c in cases if c.category in abstaining)
    assert all(c.clarify for c in cases if c.category in {"clarification", "conflicting"})
    assert not any(c.clarify for c in cases if c.category not in {"clarification", "conflicting"})


def test_every_label_is_a_returnable_section_of_the_tenant_and_the_assets_family() -> None:
    governed = corpus.load(CORPUS)
    # The anchor is written for 2026-10-16T12:00Z; this proves the returnable set is the same at the cases' instant.
    assert corpus.returnable(governed, FIXTURE_CLOCK) == RETURNABLE_AT_AS_OF
    sections = {
        (d.tenant, d.evidence_id(s)): d
        for d in governed.documents
        if d.identity in RETURNABLE_AT_AS_OF
        for s in d.sections
    }
    assets = {a["asset_id"]: a for a in json.loads((CORPUS / "assets.json").read_text(encoding="utf-8"))["assets"]}
    for case in grading.load_cases(CASES):
        assert not case.required_refs & case.allowed_refs, case.case_id  # "further" references, never repeated
        family = assets[case.asset_id]["asset_type"]
        for ref in case.required_refs | case.allowed_refs:
            doc = sections[(case.tenant, ref)]  # a KeyError names a label that is not returnable for the tenant
            assert doc.asset_family in (None, family), (case.case_id, ref)
            if doc.label == "injected":
                assert case.category == "injected" and ref in case.allowed_refs, (case.case_id, ref)


def test_assets_belong_to_the_tenant_except_in_cross_tenant_cases_which_abstain() -> None:
    assets = json.loads((CORPUS / "assets.json").read_text(encoding="utf-8"))["assets"]
    owner = {a["asset_id"]: a["tenant"] for a in assets}
    for case in grading.load_cases(CASES):
        if owner[case.asset_id] != case.tenant:
            assert case.category == "cross_tenant" and case.expected_kind == "abstain", case.case_id
    assert any(owner[c.asset_id] != c.tenant for c in grading.load_cases(CASES))  # the rule is exercised


def test_the_handoff_checker_refuses_a_case_outside_the_development_split(tmp_path: Path) -> None:
    copy = _tracked_copy(tmp_path)  # what `git ls-files` lists: stage a new case file before this runs
    path = copy / "evals" / "dev" / "cases.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    for change in ({"split": "holdout"}, {}):  # another split, then no split at all: refusals, never a traceback
        first = {k: v for k, v in rows[0].items() if k != "split"} | change
        path.write_text("".join(json.dumps(r) + "\n" for r in [first, *rows[1:]]), encoding="utf-8", newline="\n")
        result = _run_contracts(copy)
        out = result.stdout + result.stderr
        assert result.returncode == 1 and "FAIL: Do not fabricate a held-out fixture" in out, change
    path.write_text("".join(json.dumps(r) + "\n" for r in [[1, 2], *rows[1:]]), encoding="utf-8", newline="\n")
    result = _run_contracts(copy)  # a row that is not an object: a named refusal as well
    assert result.returncode == 1 and "FAIL: Development eval case rows must be JSON objects" in (
        result.stdout + result.stderr
    )
    path.unlink()
    result = _run_contracts(copy)
    assert (
        result.returncode == 1 and "FAIL: Missing required file: evals/dev/cases.jsonl" in result.stdout + result.stderr
    )


def test_every_proposal_case_has_an_alert_of_its_asset_inside_its_interval() -> None:
    alerts = json.loads((CORPUS / "assets.json").read_text(encoding="utf-8"))["alerts"]
    for case in grading.load_cases(CASES):
        if case.expected_kind != "proposal":
            continue
        start = case.as_of - timedelta(hours=case.hours)
        raised = [
            datetime.fromisoformat(a["raised_at"]) for a in alerts if a["asset_id"] == case.asset_id
        ]  # the interval is [as_of - hours, as_of)
        assert any(start <= t < case.as_of for t in raised), case.case_id


def test_the_case_loader_refuses_a_row_the_schema_refuses_and_a_repeated_id(tmp_path: Path) -> None:
    row = json.loads((ROOT / "evals" / "dev" / "cases.jsonl").read_text(encoding="utf-8").splitlines()[0])
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps({**row, "clarify": True}) + "\n", encoding="utf-8")  # clarify only with abstain
    with pytest.raises(grading.CaseError, match=r"cases.jsonl:1: .* breaks the case schema"):
        grading.load_cases(path)
    path.write_text(json.dumps({**row, "split": "holdout"}) + "\n", encoding="utf-8")
    with pytest.raises(grading.CaseError, match="split"):
        grading.load_cases(path)
    path.write_text((json.dumps(row) + "\n") * 2, encoding="utf-8")
    with pytest.raises(grading.CaseError, match="unique"):
        grading.load_cases(path)


@pytest.mark.parametrize(
    ("change", "rule"),
    [
        ({"surprise": 1}, "additionalProperties"),
        ({"case_id": "HO-001"}, "pattern"),
        ({"case_id": "DV-1"}, "pattern"),
        ({"expected_kind": "abstain", "required_refs": ["ALPHA-PUMP-SEAL:v2:leak-response"]}, "maxItems"),
        ({"intent": "answer_only", "expected_kind": "proposal"}, "enum"),
        ({"as_of": "2026-13-45T12:00:00Z"}, "format"),
        ({"as_of": "2026-10-06T12:00:00+00:00"}, "pattern"),
    ],
    ids=["unknown-key", "holdout-id", "short-id", "abstain-with-refs", "answer-only-proposal", "bad-as-of", "offset"],
)
def test_the_case_loader_refuses_a_row_breaking_each_schema_rule(
    tmp_path: Path, change: dict[str, object], rule: str
) -> None:
    row = json.loads(CASES.read_text(encoding="utf-8").splitlines()[0])
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps({**row, **change}) + "\n", encoding="utf-8")
    with pytest.raises(grading.CaseError, match=rf"cases.jsonl:1: .* breaks the case schema \({rule}\)"):
        grading.load_cases(path)


def test_the_case_loader_names_a_malformed_line_and_a_row_that_is_not_an_object(tmp_path: Path) -> None:
    good = CASES.read_text(encoding="utf-8").splitlines()[0]
    path = tmp_path / "cases.jsonl"
    path.write_text(good + "\n{not json\n", encoding="utf-8")
    with pytest.raises(grading.CaseError, match=r"cases.jsonl:2: not valid JSON") as caught:
        grading.load_cases(path)
    assert "not json" not in str(caught.value)  # the line number, never the row's text
    path.write_text("[1, 2]\n", encoding="utf-8")
    with pytest.raises(grading.CaseError, match=r"cases.jsonl:1: \(root\) breaks the case schema"):
        grading.load_cases(path)

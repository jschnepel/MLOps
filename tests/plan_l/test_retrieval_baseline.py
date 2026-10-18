"""The baseline's queries, metrics and report without a database (R033; Plan L ruling 19; SA:665).

Catches: fewer than 40 queries or a tenant without one of the lifecycle, probe or filter categories; a label citing a
section that is not permitted for its tenant at corpus-1's labelling instant, or that the case's asset type would
filter out; a case with both labels or none; a Wilson interval that is not Wilson's; a metric computed over the wrong
denominator (precision of an empty answer, recall of a no-source case); a forbidden section not counted; and a
report that drops a denominator or a missed case.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from ops_core import corpus

from scripts import retrieval_baseline as rb

ROOT = Path(__file__).resolve().parents[2]
QUERIES = ROOT / "evals" / "retrieval" / "dev-queries.jsonl"
AS_OF = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)  # the labelling instant of tests/plan_l/test_corpus_files.py
PER_TENANT = {"answerable", "superseded", "expired", "revoked", "draft_only", "missing_source", "cross_tenant"}
PER_TENANT |= {"asset_filtered", "injected"}


def test_the_queries_cover_every_category_for_both_tenants() -> None:
    cases = rb.load_queries(QUERIES)
    assert len(cases) >= 40 and {c.category for c in cases} == set(rb.CATEGORIES)
    for tenant in ("alpha", "beta"):
        assert PER_TENANT <= {c.category for c in cases if c.tenant == tenant}, tenant
    assert all(c.asset_type is not None for c in cases if c.category == "asset_filtered")
    assert all(c.expect_none for c in cases if c.category in {"expired", "revoked", "draft_only", "missing_source"})
    assert all(c.expect_none for c in cases if c.category == "cross_tenant")


def test_every_label_is_a_permitted_section_of_its_tenant() -> None:
    governed = corpus.load(ROOT / "data" / "corpus")
    allowed = corpus.returnable(governed, AS_OF)
    sections = {d.evidence_id(s): d for d in governed.documents if d.identity in allowed for s in d.sections}
    for case in rb.load_queries(QUERIES):
        for evidence_id in case.expected:
            doc = sections[evidence_id]  # a KeyError names a label that is not permitted at all
            assert doc.tenant == case.tenant, case.id
            assert case.asset_type is None or doc.asset_family in (None, case.asset_type), case.id


def test_a_case_with_both_labels_is_refused(tmp_path: Path) -> None:
    row = {"id": "X1", "tenant": "alpha", "category": "answerable", "query": "q", "asset_type": None}
    path = tmp_path / "q.jsonl"
    path.write_text(json.dumps({**row, "expected": ["A:v1:s"], "expect_none": True}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="never both or none"):
        rb.load_queries(path)
    path.write_text(json.dumps({**row, "category": "other", "expected": [], "expect_none": True}) + "\n", "utf-8")
    with pytest.raises(ValueError, match="the category a known one"):
        rb.load_queries(path)


def test_wilson_is_the_wilson_score_interval() -> None:
    def rounded(successes: int, n: int) -> list[float]:
        return [round(x, 4) for x in rb.wilson(successes, n)]

    assert rounded(0, 10) == [0.0, 0.2775] and rounded(10, 10) == [0.7225, 1.0]
    assert rounded(5, 10) == [0.2366, 0.7634] and rounded(3, 4) == [0.3006, 0.9544]
    assert rb.wilson(0, 0) == (0.0, 1.0)


def case(id_: str, expected: tuple[str, ...], category: str = "answerable") -> rb.Case:
    return rb.Case(id_, "alpha", category, "q", None, expected, not expected)


def test_the_summary_uses_the_right_denominators() -> None:
    permitted = {"D:v1:a", "D:v1:b", "D:v1:c"}
    outcomes = [
        rb.evaluate(case("C1", ("D:v1:a",)), [("D:v1:b", 0.5), ("D:v1:a", 0.4)], permitted),  # relevant at rank 2
        rb.evaluate(case("C2", ("D:v1:c", "D:v1:a")), [], permitted),  # nothing returned
        rb.evaluate(case("C3", (), "expired"), [], permitted),  # a no-source case answered with nothing
        rb.evaluate(case("C4", (), "cross_tenant"), [("E:v1:x", 0.2)], permitted),  # another tenant's section
    ]
    s = rb.summarize(outcomes)
    assert (s["cases"], s["answerable"], s["expect_none"]) == (4, 2, 2)
    assert (s["recall_at_k"], s["precision_at_k"], s["mrr_at_k"]) == (0.5, 0.1, 0.25)  # precision over k = 5
    assert (s["hit_at_k"]["successes"], s["hit_at_k"]["n"]) == (1, 2)
    assert (s["none_answered_empty"]["successes"], s["none_answered_empty"]["n"]) == (1, 2)
    assert s["forbidden_rows"] == {"forbidden": 1, "returned": 3}
    assert (s["cases_without_forbidden"]["successes"], s["cases_without_forbidden"]["n"]) == (3, 4)
    assert s["by_category"]["cross_tenant"]["forbidden_rows"] == 1 and "conflicting" not in s["by_category"]
    doc = rb.report(
        outcomes,
        corpus_version="corpus-1",
        lock_sha256="f" * 64,
        measured_at="2026-10-16T12:00:00Z",
        chunk_words=[40, 90, 60],
    )
    assert doc["cases"][3]["forbidden"] == ["E:v1:x"] and doc["settings"]["k"] == 5
    text = rb.markdown(doc)
    assert "| hit@5 | 1/2 = 0.50 (Wilson 95% 0.09-0.91) |" in text
    assert "| forbidden sections among all returned rows | 1/3 |" in text
    assert doc["chunk_words"] == {"n": 3, "min": 40, "median": 60, "max": 90}
    assert "Chunks: 3 sections; words per section (`[a-z0-9]+`) min 40, median 60, max 90." in text
    assert "no expected section in the top 5: C2." in text and "but no answer): C4." in text

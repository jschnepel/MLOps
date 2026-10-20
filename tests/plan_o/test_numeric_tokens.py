"""The numeric-token pairs and their report without a database (Plan O ruling 7; Plan N ruling 10).

Catches: a numeric query without a number or a control that still holds one; a pair whose two queries differ in
tenant, category, labels or asset type (the pair would then measure more than the number); a label that is not a
returnable section of its tenant at T17's labelling instant; a normalisation in `query_words` other than revision
0011's (a decimal must reach the search as two words); a report that miscounts lost or gained pairs, or that judges
total loss on anything but the decimal pairs; and T17's query file changed by T23 (its hash pins both committed
retrieval reports).
"""

import hashlib
import json
from pathlib import Path

import pytest
from ops_core import corpus

from scripts import numeric_tokens as nt
from scripts import retrieval_baseline as rb
from tests.plan_l.test_corpus_files import AS_OF

ROOT = Path(__file__).resolve().parents[2]


def test_the_committed_pairs_carry_corpus_1s_numbers_against_controls_without_them() -> None:
    pairs = nt.load_pairs()
    assert [p.pair for p in pairs] == [f"P0{n}" for n in range(1, 7)]
    numbers = {m for p in pairs for m in nt.NUMBER.findall(p.numeric.query)}
    assert numbers == {"0.10", "0.05", "100", "30", "14"}
    assert {p.numeric.tenant for p in pairs} == {"alpha", "beta"}
    dev = (ROOT / "evals" / "retrieval" / "dev-queries.jsonl").read_bytes()
    assert hashlib.sha256(dev).hexdigest() == "d6d539bdd9a540f6e7a66dd641c05e5c1ee97c1561c59f5b67896fedb1596938"


def test_every_label_is_a_returnable_section_of_its_tenant() -> None:
    governed = corpus.load(ROOT / "data" / "corpus")
    allowed = corpus.returnable(governed, AS_OF)
    sections = {(d.tenant, d.evidence_id(s)) for d in governed.documents if d.identity in allowed for s in d.sections}
    for p in nt.load_pairs():
        assert all((p.numeric.tenant, e) in sections for e in p.numeric.expected), p.pair


def test_query_words_split_a_decimal_as_revision_0011_does() -> None:
    assert nt.query_words("Is 0.05 the offset band for pump B22?") == [
        "is", "0", "05", "the", "offset", "band", "for", "pump", "b22",
    ]  # fmt: skip
    assert nt.query_words("the 30-day seal interval") == ["the", "30", "day", "seal", "interval"]
    assert not nt.NUMBER.search("pump B22 and A17") and nt.NUMBER.findall("per 100 mm, 0.10") == ["100", "0.10"]


ROW = {"tenant": "beta", "category": "answerable", "asset_type": None, "expected": ["B:v1:s"], "expect_none": False}


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([{"id": "N1", "query": "is 0.10 ok", "pair": "P"}, {"id": "N2", "query": "is 0.05 ok", "pair": "P"}], "one N"),
        ([{"id": "N1", "query": "is 0.10 ok", "pair": "P"}, {"id": "C1", "query": "is 0.05 ok", "pair": "P"}], "none"),
        (
            [
                {"id": "N1", "query": "is 0.10 ok", "pair": "P"},
                {"id": "C1", "query": "is it ok", "pair": "P", "tenant": "alpha"},
            ],
            "share",
        ),
        (
            [
                {"id": "N1", "query": "is 0.10 ok", "pair": "P"},
                {"id": "C1", "query": "is it ok", "pair": "P", "category": "superseded"},
            ],
            "share",
        ),
        ([{"id": "N1", "query": "is 0.10 ok"}], "keys must be"),
    ],
    ids=["two-numeric", "control-with-number", "other-tenant", "other-category", "no-pair"],
)
def test_a_malformed_pair_file_is_refused(tmp_path: Path, rows: list[dict[str, object]], message: str) -> None:
    path = tmp_path / "pairs.jsonl"
    path.write_text("".join(json.dumps({**ROW, **r}) + "\n" for r in rows), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        nt.load_pairs(path)


def outcome(case: rb.Case, returned: list[str]) -> rb.Outcome:
    return rb.evaluate(case, [(e, 0.9) for e in returned], {*returned})


def test_the_report_counts_lost_and_gained_pairs_and_total_loss_on_the_decimals() -> None:
    """Round 1, minor 3: only a decimal splits under revision 0011, so the total-loss bar is the decimal pairs'."""
    by_name = {p.pair: p for p in nt.load_pairs()}
    pairs = [by_name["P01"], by_name["P02"], by_name["P04"]]  # two decimal pairs and one integer pair (30-day)
    assert [nt.is_decimal(p) for p in pairs] == [True, True, False]
    p1, p2, p4 = pairs

    def want(p: nt.Pair) -> list[str]:
        return list(p.numeric.expected)

    outcomes = {
        "lexical": {
            p1.numeric.id: outcome(p1.numeric, ["X:v1:a"]),  # lost: the control hits, the number misses
            p1.control.id: outcome(p1.control, ["X:v1:a", *want(p1)]),
            p2.numeric.id: outcome(p2.numeric, want(p2)),  # gained
            p2.control.id: outcome(p2.control, []),
            p4.numeric.id: outcome(p4.numeric, []),  # lost, but an integer pair
            p4.control.id: outcome(p4.control, want(p4)),
        },
        "vector_exact": {c.id: outcome(c, want(p)) for p in pairs for c in (p.numeric, p.control)},
    }
    doc = nt.report(
        pairs,
        outcomes,
        corpus_version="corpus-1",
        lock_sha256="f" * 64,
        queries_sha256="e" * 64,
        as_of="2026-10-16T12:00:00Z",
        measured_at="2026-10-19T12:00:00Z",
    )
    lexical, vector = doc["summary"]["lexical"], doc["summary"]["vector_exact"]
    assert (lexical["lost"], lexical["gained"], lexical["total_loss"]) == (["P01", "P04"], ["P02"], False)
    assert (lexical["decimal_pairs"], lexical["decimal_lost"]) == (["P01", "P02"], ["P01"])
    assert (lexical["numeric_hit_at_5"]["successes"], lexical["control_hit_at_5"]["successes"]) == (1, 2)
    assert (vector["lost"], vector["total_loss"], vector["numeric_hit_at_5"]["n"]) == ([], False, 3)
    assert doc["pairs"][0]["lexical"]["control_rank"] == 2 and doc["pairs"][0]["lexical"]["numeric_rank"] is None
    assert doc["pairs"][0]["numeric"]["words"] == nt.query_words(p1.numeric.query)
    text = nt.markdown(doc)
    third, two_thirds, half = (rb._rate(rb.proportion(k, n)) for k, n in ((1, 3), (2, 3), (1, 2)))
    assert f"| lexical | {third} | {two_thirds} | {half} | {half} | P01, P04 | P02 | 0 |" in text
    assert "| miss / 2 | 1 / 1 |" in text
    assert (
        "not total in lexical mode (1 of 2 decimal pairs lost (lost: P01; decimal pairs: P01, P02); "
        "2 of 3 pairs in all)"
    ) in text
    decimals_lost = {
        **outcomes["lexical"],
        p2.numeric.id: outcome(p2.numeric, []),
        p2.control.id: outcome(p2.control, want(p2)),
        p4.numeric.id: outcome(p4.numeric, want(p4)),  # the integer pair keeps its hit: the bar is the decimals'
    }
    total = nt.report(pairs, {**outcomes, "lexical": decimals_lost}, corpus_version="c", lock_sha256="f" * 64,
                      queries_sha256="e" * 64, as_of="a", measured_at="m")  # fmt: skip
    assert total["summary"]["lexical"]["total_loss"] is True
    assert (
        "total in lexical mode (2 of 2 decimal pairs lost (lost: P01, P02; decimal pairs: P01, P02); "
        "2 of 3 pairs in all)"
    ) in nt.markdown(total)

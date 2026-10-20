"""The comparison's pure functions (Plan N rulings 6, 8, 9, 11 and 14; SA:665-667).

Catches: an exact McNemar test that is one-sided, approximate or not capped at 1; improvements and regressions swapped
or matched across different cases; a threshold rule other than the one fixed before measuring (the largest grid value
that loses no answerable hit), or one that rounds the grid; a brute-force ranking with another tie-break than the
definer's byte order; a window that splits a section, drops a remainder or crosses documents; a k = 3 summary that
still counts the top 5; the committed T17 answers moved (the lexical path must not); and the development query file
or corpus-1 changed by T18.
"""

import hashlib
import json
from typing import Any

import pytest
from ops_core import corpus

from scripts import retrieval_baseline as rb
from scripts import retrieval_comparison as rc


def case(id: str, expected: tuple[str, ...] = (), *, none: bool = False, tenant: str = "alpha") -> rb.Case:
    return rb.Case(id, tenant, "answerable" if expected else "missing_source", "q", None, expected, none)


def section(name: str, words: int) -> corpus.Section:
    body = " ".join(["word"] * words)
    return corpus.Section(name, 0, len(body), body, hashlib.sha256(body.encode()).hexdigest(), words)


def test_mcnemar_is_the_exact_two_sided_binomial() -> None:
    assert rc.mcnemar(0, 0) == 1.0
    assert rc.mcnemar(5, 0) == rc.mcnemar(0, 5) == 2 / 32  # every discordant pair one way: 2 * 0.5^5
    assert rc.mcnemar(1, 7) == pytest.approx(2 * (1 + 8) / 256)
    assert rc.mcnemar(3, 3) == 1.0  # capped, never above 1


def test_paired_lists_improvements_and_regressions_by_case() -> None:
    cases = [case("A1", ("x",)), case("A2", ("y",)), case("A3", ("z",))]
    lexical = [rb.evaluate(c, r, {"x", "y", "z", "w"}) for c, r in zip(cases, ([("x", 1.0)], [], [("z", 1.0)]))]
    vector = [
        rb.evaluate(c, r, {"x", "y", "z", "w"}) for c, r in zip(cases, ([("w", 0.9)], [("y", 0.8)], [("z", 0.9)]))
    ]
    row = rc.paired(lexical, vector, lambda o: o.relevant_at(5) > 0)
    assert (row["lexical"], row["vector"], row["improved"], row["regressed"]) == (2, 2, ["A2"], ["A1"])
    assert row["mcnemar_p"] == 1.0 and row["claim"].startswith("no ranking claim")
    with pytest.raises(AssertionError):
        rc.paired(lexical, list(reversed(vector)), lambda o: True)


def test_the_brute_force_ranking_is_the_definers_order() -> None:
    scored = [("B:v1:b", 0.7), ("A:v1:a", 0.7), ("a:v1:a", 0.9), ("C:v1:c", 0.68)]
    assert rc.ranked(scored, 0.68, 8) == [("a:v1:a", 0.9), ("A:v1:a", 0.7), ("B:v1:b", 0.7)]  # > 0.68; byte-order ties
    assert rc.ranked(scored, 0.68, 1) == [("a:v1:a", 0.9)]


def test_the_threshold_rule_keeps_every_answerable_hit() -> None:
    cases = [case("A1", ("x",)), case("A2", ("y",)), case("N1", none=True)]
    scored = {"A1": [("x", 0.71), ("n", 0.40)], "A2": [("y", 0.50), ("x", 0.60)], "N1": [("n", 0.45)]}
    rows = rc.sweep(cases, scored, rc.GRID)
    assert rows[0] == {"threshold": 0.0, "hit_at_k": 2, "answerable": 2, "none_answered_empty": 0, "expect_none": 1}
    assert rc.choose_threshold(rows) == 0.49  # at 0.50 A2's hit (similarity 0.50) is no longer above it
    assert next(r for r in rows if r["threshold"] == 0.45)["none_answered_empty"] == 1
    assert rc.choose_threshold([{"threshold": 0.0, "hit_at_k": 1}, {"threshold": 0.01, "hit_at_k": 0}]) == 0.0


def test_the_lexical_sweep_reads_the_recorded_ranks() -> None:
    cases = [case("A1", ("x",)), case("N1", none=True)]
    outcomes = [rb.evaluate(cases[0], [("x", 0.5)], {"x", "n"}), rb.evaluate(cases[1], [("n", 0.3)], {"x", "n"})]
    rows = {r["threshold"]: r for r in rc.lexical_sweep(outcomes, rc.LEXICAL_GRID)}
    assert rc.LEXICAL_GRID[0] == 0.25 and rc.LEXICAL_GRID[-1] == 1.0
    assert (rows[0.25]["hit_at_k"], rows[0.25]["none_answered_empty"]) == (1, 0)
    assert (rows[0.3]["none_answered_empty"], rows[0.5]["hit_at_k"]) == (1, 0)  # strictly above, as the definer


def test_windows_join_adjacent_sections_until_three_hundred_words() -> None:
    parts = [section("a", 120), section("b", 120), section("c", 90), section("d", 50), section("e", 40)]
    groups = [[s.name for s in w] for w in rc.windows(parts)]
    assert groups == [["a", "b", "c", "d", "e"]]  # 330 words, then a 90-word remainder joins the last window
    assert [[s.name for s in w] for w in rc.windows(parts[:2])] == [["a", "b"]]  # shorter than 300: one window
    long = [section(n, 160) for n in "abcd"]
    assert [[s.name for s in w] for w in rc.windows(long)] == [["a", "b"], ["c", "d"]]
    text = rc.window_text(long[:2])
    assert text.startswith("search_document: a\n\n") and "\n\nb\n\n" in text and text.count("search_document:") == 1


def test_k3_counts_only_the_top_three() -> None:
    c = case("A1", ("x",))
    o = rb.evaluate(c, [("a", 0.9), ("b", 0.8), ("c", 0.7), ("x", 0.6)], {"a", "b", "c", "x"})
    assert rb.summarize([o], 5)["hit_at_k"]["successes"] == 1
    assert rb.summarize([o], 3)["hit_at_k"]["successes"] == 0 and rb.summarize([o], 3)["k"] == 3
    assert rb.summarize([o]) == rb.summarize([o], rb.K)  # the T17 report's default is unchanged
    # Forbidden rows count within the top k too (round 1, Minor 5): a forbidden fourth row is outside k = 3.
    bad = rb.evaluate(c, [("a", 0.9), ("b", 0.8), ("c", 0.7), ("z", 0.6)], {"a", "b", "c"})
    assert rb.summarize([bad], 3)["forbidden_rows"] == {"forbidden": 0, "returned": 3}
    assert rb.summarize([bad], 5)["forbidden_rows"] == {"forbidden": 1, "returned": 4}
    assert rb.summarize([bad], 3)["cases_without_forbidden"]["successes"] == 1


def test_micro_recall_pools_sections_over_the_labelled_cases() -> None:
    """Fix round 1: DoD 1's recall with its denominator and Wilson interval, beside the per-case mean."""
    cases = [case("A1", ("x", "y")), case("A2", ("z",)), case("N1", none=True)]
    allowed = {"x", "y", "z"}
    outcomes = [
        rb.evaluate(cases[0], [("x", 0.9), ("a", 0.8), ("b", 0.7), ("y", 0.6)], allowed | {"a", "b"}),
        rb.evaluate(cases[1], [("z", 0.9)], allowed),
        rb.evaluate(cases[2], [], allowed),
    ]
    five, three = rc.micro_recall(outcomes, 5), rc.micro_recall(outcomes, 3)
    assert (five["successes"], five["n"], five["rate"]) == (3, 3, 1.0)
    assert (three["successes"], three["n"]) == (2, 3) and three["wilson95"] is not None
    assert rc.micro_recall([outcomes[2]], 5)["rate"] is None  # no labelled case, no interval


def test_changes_name_the_cases_without_a_test() -> None:
    cases = [case("A1", ("x", "y")), case("A2", ("z",))]
    allowed = {"x", "y", "z"}
    lexical = [rb.evaluate(cases[0], [("x", 1.0)], allowed), rb.evaluate(cases[1], [("z", 1.0)], allowed)]
    vector = [rb.evaluate(cases[0], [("x", 1.0), ("y", 0.9)], allowed), rb.evaluate(cases[1], [], allowed)]
    row = rc.changes(lexical, vector, lambda o: o.relevant_at(5) == len(o.case.expected))
    assert row == {"n": 2, "lexical": 1, "vector": 1, "improved": ["A1"], "regressed": ["A2"]}


def test_the_committed_lexical_answers_and_the_inputs_are_t17s() -> None:
    t17: dict[str, Any] = json.loads(rc.T17_REPORT.read_text(encoding="utf-8"))
    assert rc.answers_digest(t17["cases"]) == rc.T17_ANSWERS_SHA256
    queries = hashlib.sha256(rc.QUERIES.read_bytes()).hexdigest()
    assert queries == t17["queries_sha256"] == "d6d539bdd9a540f6e7a66dd641c05e5c1ee97c1561c59f5b67896fedb1596938"
    assert corpus.RELEASES == {"corpus-1": "81f50c2b8623675f9c899033cba748f289b7f4024003385aabc8a95147b71862"}
    assert corpus.load(rc.CORPUS).lock_sha256 == corpus.RELEASES["corpus-1"]  # corpus-1 untouched (ruling 15)


def test_corpus_1s_windows_are_its_whole_returnable_versions() -> None:
    """Round 1, I1: every corpus-1 version returnable at the labelling instant has 327-343 words, so the 300-word rule
    makes each one window; the report must say so instead of presenting a 300-word-window result."""
    found = rc.corpus_windows(corpus.load(rc.CORPUS))
    assert len(found) == 8 and all(w.whole_version for w in found)
    assert sorted(w.tenant for w in found) == ["alpha"] * 5 + ["beta"] * 3
    assert min(w.words for w in found) >= rc.WINDOW_WORDS


def window(name: str, tenant: str = "alpha", *sections: str) -> rc.Window:
    ids = sections or (name,)
    return rc.Window(tenant, None, ids, f"search_document: {name}", 300, True)


def test_window_metrics_report_what_the_windows_can_measure() -> None:
    cases = [case("A1", ("x",)), case("A2", ("y",)), case("N1", none=True)]
    first, second = window("W1", "alpha", "x", "q"), window("W2", "alpha", "y")
    candidates = {"A1": [(first, 0.8), (second, 0.7)], "A2": [(first, 0.9), (second, 0.6)], "N1": [(second, 0.5)]}
    row = rc.window_metrics(cases, candidates, {"alpha": {"x", "q", "y"}}, [first, second], 0.65)
    assert row["windows_per_tenant"] == {"alpha": 2} and row["sections_per_window"] == {"min": 1, "max": 2}
    assert row["every_window_a_whole_version"] and row["k_covers_every_window"]
    assert row["hit_at_k"]["successes"] == 1 and row["recall_at_k"] == 0.5  # A2's window is under 0.65
    # The ranking alone (round 2, I1): A2's top window at threshold 0 is W1, which lacks y; y's window is second.
    assert row["hit_at_1_threshold_0"]["successes"] == 1 and row["mrr_at_k_threshold_0"] == 0.75
    assert "recall_at_k_threshold_0" not in row  # 1.0 by construction when k covers every window
    assert row["none_answered_empty"]["successes"] == 1 and row["forbidden_windows"] == 0


def test_window_metrics_count_forbidden_windows_not_sections() -> None:
    """Review Minor 2: a window holding two sections the case may not see is one forbidden window. Fix round 1: it is
    counted at threshold 0, so a forbidden window below the section-tuned threshold counts too (the stronger check,
    and the one the report's sentence names)."""
    cases = [case("A1", ("x",))]
    bad, low = window("W1", "alpha", "x", "p", "q"), window("W2", "alpha", "r")
    candidates = {"A1": [(bad, 0.9), (low, 0.5)]}
    row = rc.window_metrics(cases, candidates, {"alpha": {"x"}}, [bad, low], 0.65)
    assert row["forbidden_windows"] == 2 and "forbidden_sections" not in row
    assert rc.window_metrics(cases, {"A1": [(bad, 0.9)]}, {"alpha": {"x"}}, [bad], 0.65)["forbidden_windows"] == 1


def test_window_metrics_without_any_window_report_nothing_instead_of_failing() -> None:
    """Review Minor 3: no window at all is a corpus with nothing returnable, not a crash."""
    row = rc.window_metrics([case("A1", ("x",))], {"A1": []}, {"alpha": set()}, [], 0.68)
    assert row["windows"] == 0 and row["windows_per_tenant"] == {}
    assert row["sections_per_window"] == {"min": None, "max": None} and row["words_per_window"]["min"] is None
    assert row["every_window_a_whole_version"] is False and row["k_covers_every_window"] is True
    assert row["hit_at_k"]["successes"] == 0 and row["forbidden_windows"] == 0


def test_the_report_names_both_modes_every_change_and_the_settings() -> None:
    cases = [case("A1", ("x",)), case("A2", ("y",)), case("N1", none=True)]
    allowed = {"x", "y", "n"}
    lexical = [rb.evaluate(c, r, allowed) for c, r in zip(cases, ([("x", 0.5)], [("y", 0.4)], [("n", 0.3)]))]
    vector = [rb.evaluate(c, r, allowed) for c, r in zip(cases, ([("x", 0.9)], [], []))]
    scored = {"A1": [("x", 0.9)], "A2": [("y", 0.6)], "N1": [("n", 0.5)]}
    doc = rc.comparison(
        lexical,
        vector,
        settings={
            "model": "nomic-embed-text",
            "vector_minimum_similarity": 0.68,
            "document_prefix": "search_document: ",
        },
        vector_sweep=rc.sweep(cases, scored, rc.GRID),
        lexical_sweep_rows=rc.lexical_sweep(lexical, rc.LEXICAL_GRID),
        window=rc.window_metrics(
            cases,
            {"A1": [(window("W1", "alpha", "x"), 0.9)], "A2": [], "N1": []},
            {"alpha": {"x", "y", "n"}},
            [window("W1", "alpha", "x")],
            0.68,
        ),
        repeat=rc.repeat_check([(1.0, 0.0)], [(1.0, 0.0)]),
        corpus_version="corpus-1",
        lock_sha256="a" * 64,
        queries_sha256="b" * 64,
        measured_at="2026-10-19T00:00:00Z",
    )
    assert doc["paired"]["hit_at_5"]["regressed"] == ["A2"] and doc["paired"]["none_answered_empty"]["improved"] == [
        "N1"
    ]
    assert set(doc["summary"]["vector_exact"]) == {"5", "3"}
    assert doc["summary"]["lexical"]["5"]["micro_recall_at_k"] == {
        "successes": 2,
        "n": 2,
        "rate": 1.0,
        "wilson95": doc["summary"]["lexical"]["5"]["micro_recall_at_k"]["wilson95"],
    }
    assert doc["summary"]["vector_exact"]["5"]["micro_recall_at_k"]["successes"] == 1
    assert set(doc["changes"]) == {"every_expected_at_5", "hit_at_3", "every_expected_at_3"}
    assert doc["changes"]["hit_at_3"]["regressed"] == ["A2"] and "mcnemar_p" not in doc["changes"]["hit_at_3"]
    text = rc.markdown(doc)
    for needle in (
        "## Results",
        "### k = 3",
        "regressed: A2",
        "improved by vector: N1",
        "## Thresholds",
        "## Another chunk window",
        "## Determinism",
        "`vector_minimum_similarity`: `0.68`",
        "`document_prefix`: `search_document: `",
        "expected sections found over expected sections, all labelled cases",
        "precision@5 (top-5 hits over 5; mean over 2 cases; ceiling",
        "Changes between the modes, named and descriptive only",
        "every expected section in the top 3, labelled cases",
        "Windows returned at threshold 0 (every window within the top 5)",
        "the JSON (`vector_threshold_sweep`) holds all 100 values",
        "the same rule applied to the recorded lexical ranks chooses",
        "whole-version embeddings against section embeddings",
    ):
        assert needle in text, needle

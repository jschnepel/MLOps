"""Exact vector search measured against the lexical baseline (T18, R034; Plan N rulings 6, 8, 9, 11 and 14).

The pure half of the comparison: the live test tests/e2e/test_retrieval_comparison_live.py runs both modes through
`search_procedures_scoped` as `mcp_read` on the 47 development queries and hands the answers here, with the stored
vectors (read back as the superuser) and the query vectors; this module turns them into
reports/retrieval-comparison.json and .md. The metrics are scripts/retrieval_baseline.py's, at k = 5 and k = 3 (the
worker's limit), with Wilson 95% intervals and denominators (SA:665); the paired comparisons are exact two-sided
McNemar tests on the discordant cases (SA:667: no ranking claim without p < 0.05, and with these few cases a test
has little power, so a non-significant difference is not evidence of equality).

The same module chooses the vector branch's minimum similarity by the rule Plan N ruling 6 fixed before anything was
measured: the largest value on a 0.01 grid at which vector hit@5 over the answerable development cases equals its
value at 0. The `threshold` command applies it to fresh embeddings of the corpus files before revision 0013 is
frozen; the live comparison applies it again to the stored vectors and must find the same value. Run:

    uv run python -m scripts.retrieval_comparison threshold

It reads data/corpus, evals/retrieval/dev-queries.jsonl and data/embedding-pins.json, asks local Ollama (loopback) for
the embeddings after checking the pin, and prints the sweep and the chosen value. Development data only: the holdout
is never read (SA:657-659).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ops_core import corpus, embeddings, model_pins

from scripts import retrieval_baseline as rb

ROOT = Path(__file__).resolve().parent.parent
QUERIES = ROOT / "evals" / "retrieval" / "dev-queries.jsonl"
CORPUS = ROOT / "data" / "corpus"
T17_REPORT = ROOT / "reports" / "retrieval" / "t17-lexical-baseline.json"
# The SHA-256 of the committed T17 report's per-case answers (`answers_digest`), measured on 2026-10-19 from the file
# Plan L committed (753fa6f). The comparison re-measures lexical search and must reproduce it: the lexical path did not
# move (Plan N ruling 11). The live baseline test rewrites that file on every run, so the digest is pinned here.
T17_ANSWERS_SHA256 = "7a059a196d083a80da88be611d8ca4dbaad43660922fd977450ee7c600eb04a3"
AS_OF = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)  # tests/plan_l/test_corpus_files.py's labelling instant
KS = (5, 3)  # BS:417's top_k and the worker's limit (worker/src/ops_worker/handlers.py)
GRID = tuple(i / 100 for i in range(100))  # ruling 6: 0.00 to 0.99
LEXICAL_GRID = tuple(round(0.25 + i * 0.05, 2) for i in range(16))  # ruling 9: 0.25 (the stored minimum) to 1.00
# Ruling 6's rule applied to the lexical ranks for the report's like-for-like sentence (round 1, Minor 11): the same
# 0.01 steps from the stored minimum, far past any rank corpus-1's queries reach.
LEXICAL_RULE_GRID = tuple(round(0.25 + i / 100, 2) for i in range(976))
WINDOW_WORDS = 300  # ruling 8: BS:415's lower bound of the initial chunk proposal, in [a-z0-9]+ words
REPEAT_COSINE = 0.9999  # ruling 14: two embeddings of one text are the same vector within this

Scored = Sequence[tuple[str, float]]  # (evidence_id, similarity) for every permitted candidate of one query


def answers_digest(cases: Iterable[Mapping[str, Any]]) -> str:
    """The SHA-256 of a report's per-case answers: each case's id with its returned (evidence_id, rank) pairs."""
    answers = [[c["id"], [[r["evidence_id"], r["rank"]] for r in c["returned"]]] for c in cases]
    return hashlib.sha256(json.dumps(answers, separators=(",", ":")).encode("utf-8")).hexdigest()


def mcnemar(b: int, c: int) -> float:
    """The exact two-sided McNemar p-value for `b` and `c` discordant pairs: the binomial(b + c, 1/2) probability of a
    split at least as uneven, doubled and capped at 1; 1.0 when no pair is discordant."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2**n
    return min(1.0, 2 * tail)


def paired(
    lexical: Sequence[rb.Outcome], vector: Sequence[rb.Outcome], success: Callable[[rb.Outcome], bool]
) -> dict[str, Any]:
    """Per-case outcomes of the two modes on the same cases (matched by id, in the same order): the cases only vector
    got right (`improved`), the ones only lexical got right (`regressed`), and McNemar's p on those two counts."""
    assert [o.case.id for o in lexical] == [o.case.id for o in vector], "the two modes must answer the same cases"
    improved = [v.case.id for lx, v in zip(lexical, vector, strict=True) if success(v) and not success(lx)]
    regressed = [lx.case.id for lx, v in zip(lexical, vector, strict=True) if success(lx) and not success(v)]
    p = mcnemar(len(regressed), len(improved))
    return {
        "n": len(lexical),
        "lexical": sum(success(o) for o in lexical),
        "vector": sum(success(o) for o in vector),
        "improved": improved,
        "regressed": regressed,
        "mcnemar_p": round(p, 4),
        "claim": "vector differs (p < 0.05)" if p < 0.05 else "no ranking claim (p >= 0.05, SA:667)",
    }


def ranked(scored: Scored, threshold: float, limit: int) -> list[tuple[str, float]]:
    """The brute-force answer the definer must give: similarity above `threshold`, best first, ties by evidence_id in
    byte order (as `COLLATE "C"`), at most `limit` rows."""
    kept = [(e, s) for e, s in scored if s > threshold]
    kept.sort(key=lambda row: (-row[1], row[0].encode("utf-8")))
    return kept[:limit]


def sweep(
    cases: Sequence[rb.Case], scored: Mapping[str, Scored], thresholds: Sequence[float], k: int = rb.K
) -> list[dict[str, Any]]:
    """hit@k over the answerable cases and the no-source cases answered with nothing, for each threshold."""
    rows = []
    for t in thresholds:
        top = {c.id: [e for e, _ in ranked(scored[c.id], t, k)] for c in cases}
        rows.append(
            {
                "threshold": t,
                "hit_at_k": sum(bool(set(top[c.id]) & set(c.expected)) for c in cases if c.expected),
                "answerable": sum(1 for c in cases if c.expected),
                "none_answered_empty": sum(not top[c.id] for c in cases if c.expect_none),
                "expect_none": sum(1 for c in cases if c.expect_none),
            }
        )
    return rows


def choose_threshold(rows: Sequence[Mapping[str, Any]]) -> float:
    """Ruling 6's rule, fixed before measuring: the largest grid value whose hit@k equals the value at the grid's
    first threshold (0 for the vector grid; no answerable hit lost); the first threshold when only it keeps them."""
    first = rows[0]["hit_at_k"]
    return max(float(r["threshold"]) for r in rows if r["hit_at_k"] == first)


def lexical_sweep(outcomes: Sequence[rb.Outcome], thresholds: Sequence[float]) -> list[dict[str, Any]]:
    """Ruling 9: the lexical minimum rank swept over the recorded ranks. The definer already dropped every rank at or
    below 0.25, so only higher values can be measured; 0.25 itself reproduces the baseline."""
    scored = {o.case.id: list(o.returned) for o in outcomes}
    return sweep([o.case for o in outcomes], scored, thresholds)


def windows(sections: Sequence[corpus.Section], words: int = WINDOW_WORDS) -> list[tuple[corpus.Section, ...]]:
    """Ruling 8's alternative window: adjacent sections of one document version, in order, until at least `words`
    `[a-z0-9]+` words; a remainder below that joins the last window (a version shorter than `words` is one window)."""
    out: list[tuple[corpus.Section, ...]] = []
    current: list[corpus.Section] = []
    for section in sections:
        current.append(section)
        if sum(s.words for s in current) >= words:
            out.append(tuple(current))
            current = []
    if current:
        if out:
            out[-1] = out[-1] + tuple(current)
        else:
            out.append(tuple(current))
    return out


def window_text(group: Sequence[corpus.Section]) -> str:
    """A window as the model sees it: the document prefix once, then each section's heading, a blank line and its
    body, the sections separated by a blank line (the stored unit's rule, applied to several sections)."""
    return embeddings.DOCUMENT_PREFIX + "\n\n".join(f"{s.name}\n\n{s.body}" for s in group)


@dataclass(frozen=True)
class Window:
    """One window of the experiment: its tenant, asset family, the evidence IDs it contains, its text, its
    `[a-z0-9]+` word count, and whether it is its whole document version."""

    tenant: str
    asset_family: str | None
    evidence_ids: tuple[str, ...]
    text: str
    words: int
    whole_version: bool


def corpus_windows(governed: corpus.Corpus, now: datetime = AS_OF) -> list[Window]:
    """Every window of every version a search may return at `now` (`corpus.returnable`, the oracle of the SQL rule)."""
    allowed = corpus.returnable(governed, now)
    return [
        Window(
            d.tenant,
            d.asset_family,
            tuple(d.evidence_id(s) for s in group),
            window_text(group),
            sum(s.words for s in group),
            len(group) == len(d.sections),
        )
        for d in governed.documents
        if d.identity in allowed
        for group in windows(d.sections)
    ]


Candidates = Sequence[tuple[Window, float]]  # every window one query may see, with its cosine similarity


def window_ranking(candidates: Candidates, threshold: float, limit: int) -> list[Window]:
    """The windows above `threshold`, best first, ties by their first evidence ID in byte order, at most `limit`."""
    named = {w.evidence_ids[0]: w for w, _ in candidates}
    best = ranked([(w.evidence_ids[0], s) for w, s in candidates], threshold, limit)
    return [named[first] for first, _ in best]


def window_metrics(
    cases: Sequence[rb.Case],
    candidates: Mapping[str, Candidates],
    permitted: Mapping[str, set[str]],
    all_windows: Sequence[Window],
    threshold: float,
) -> dict[str, Any]:
    """The window experiment at k = 5, with what it can and cannot measure (rounds 1 and 2, I1): the windows per
    tenant, sections and words per window, and whether each is a whole version; at the section-tuned threshold,
    recall@5 and hit@5 over the labelled cases (a window hits when it holds a labelled section) and the no-source cases
    answered with nothing; at threshold 0, the ranking alone, hit@1 and MRR@5; and windows holding a section the case
    may not see (zero by construction, counted anyway). When every window is a whole version and k covers every window
    of a tenant, the thresholded figures depend on the threshold only, so the order is read from the threshold-0
    figures (a threshold-0 recall@5 would be 1.0 by construction there, so none is reported)."""
    answerable = [c for c in cases if c.expected]
    nones = [c for c in cases if c.expect_none]
    found = {c.id: window_ranking(candidates[c.id], threshold, rb.K) for c in cases}
    open_ = {c.id: window_ranking(candidates[c.id], 0.0, rb.K) for c in cases}

    def holds(w: Window, c: rb.Case) -> bool:
        return bool(set(w.evidence_ids) & set(c.expected))

    def recall(ranking: Mapping[str, Sequence[Window]]) -> float | None:
        values = [
            len({e for w in ranking[c.id] for e in w.evidence_ids} & set(c.expected)) / len(c.expected)
            for c in answerable
        ]
        return round(sum(values) / len(values), 4) if values else None

    def reciprocal(c: rb.Case) -> float:
        ranks = [i for i, w in enumerate(open_[c.id], start=1) if holds(w, c)]
        return 1 / ranks[0] if ranks else 0.0

    per_tenant: dict[str, int] = {}
    for w in all_windows:
        per_tenant[w.tenant] = per_tenant.get(w.tenant, 0) + 1
    sizes = [len(w.evidence_ids) for w in all_windows]
    words = [w.words for w in all_windows]
    forbidden = sum(1 for c in cases for w in found[c.id] for e in w.evidence_ids if e not in permitted[c.tenant])
    return {
        "k": rb.K,
        "windows": len(all_windows),
        "windows_per_tenant": dict(sorted(per_tenant.items())),
        "sections_per_window": {"min": min(sizes), "max": max(sizes)},
        "words_per_window": {"min": min(words), "max": max(words)},
        "every_window_a_whole_version": all(w.whole_version for w in all_windows),
        "k_covers_every_window": max(per_tenant.values()) <= rb.K,
        "recall_at_k": recall(found),
        "hit_at_k": rb.proportion(sum(any(holds(w, c) for w in found[c.id]) for c in answerable), len(answerable)),
        "hit_at_1_threshold_0": rb.proportion(
            sum(any(holds(w, c) for w in open_[c.id][:1]) for c in answerable), len(answerable)
        ),
        "mrr_at_k_threshold_0": (
            round(sum(reciprocal(c) for c in answerable) / len(answerable), 4) if answerable else None
        ),
        "none_answered_empty": rb.proportion(sum(not found[c.id] for c in nones), len(nones)),
        "forbidden_sections": forbidden,
    }


def lexical_rule(outcomes: Sequence[rb.Outcome]) -> dict[str, Any]:
    """Ruling 6's rule applied to the recorded lexical ranks (round 1, Minor 11): the vector threshold was tuned by
    it while lexical keeps 0.25, so the report states what lexical would give under the same rule."""
    rows = lexical_sweep(outcomes, LEXICAL_RULE_GRID)
    chosen = choose_threshold(rows)
    return dict(next(r for r in rows if r["threshold"] == chosen))


def repeat_check(first: Sequence[embeddings.Vector], second: Sequence[embeddings.Vector]) -> dict[str, Any]:
    """Ruling 14: each query embedded twice; the largest component difference and the smallest cosine."""
    delta = max(abs(x - y) for a, b in zip(first, second, strict=True) for x, y in zip(a, b, strict=True))
    least = min(embeddings.cosine(a, b) for a, b in zip(first, second, strict=True))
    return {"queries": len(first), "max_abs_component_delta": delta, "min_cosine": least, "bound": REPEAT_COSINE}


def comparison(
    lexical: Sequence[rb.Outcome],
    vector: Sequence[rb.Outcome],
    *,
    settings: Mapping[str, Any],
    vector_sweep: Sequence[Mapping[str, Any]],
    lexical_sweep_rows: Sequence[Mapping[str, Any]],
    window: Mapping[str, Any],
    repeat: Mapping[str, Any],
    corpus_version: str,
    lock_sha256: str,
    queries_sha256: str,
    measured_at: str,
) -> dict[str, Any]:
    """The machine-readable report: both modes' summaries at k = 5 and 3, the paired tests, every case's two answers,
    the sweeps, the window experiment, the repeat check and the settings."""

    def hit5(o: rb.Outcome) -> bool:
        return o.relevant_at(5) > 0

    def empty(o: rb.Outcome) -> bool:
        return not o.returned

    answerable = [i for i, o in enumerate(lexical) if o.case.expected]
    nones = [i for i, o in enumerate(lexical) if o.case.expect_none]
    return {
        "report": "t18-retrieval-comparison",
        "measured_at": measured_at,
        "as_of": AS_OF.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "corpus_version": corpus_version,
        "lock_sha256": lock_sha256,
        "queries": "evals/retrieval/dev-queries.jsonl",
        "queries_sha256": queries_sha256,
        "settings": dict(settings),
        "summary": {
            mode: {str(k): rb.summarize(outcomes, k) for k in KS}
            for mode, outcomes in (("lexical", lexical), ("vector_exact", vector))
        },
        "paired": {
            "hit_at_5": paired([lexical[i] for i in answerable], [vector[i] for i in answerable], hit5),
            "none_answered_empty": paired([lexical[i] for i in nones], [vector[i] for i in nones], empty),
        },
        "vector_threshold_sweep": list(vector_sweep),
        "lexical_threshold_sweep": list(lexical_sweep_rows),
        "lexical_under_the_vector_rule": lexical_rule(lexical),
        "window_experiment": dict(window),
        "repeat_embedding": dict(repeat),
        "cases": [
            {
                "id": lx.case.id,
                "tenant": lx.case.tenant,
                "category": lx.case.category,
                "expected": list(lx.case.expected),
                "expect_none": lx.case.expect_none,
                "lexical": [{"evidence_id": e, "rank": round(r, 6)} for e, r in lx.returned],
                "vector_exact": [{"evidence_id": e, "similarity": round(r, 6)} for e, r in v.returned],
                "forbidden": sorted(set(lx.forbidden) | set(v.forbidden)),
            }
            for lx, v in zip(lexical, vector, strict=True)
        ],
    }


def markdown(doc: Mapping[str, Any]) -> str:
    """The human-readable report (the DoD's reports/retrieval-comparison.md): both modes with denominators and
    intervals, the paired tests, every changed case by id, the sweeps, the window experiment and the settings."""
    s = doc["settings"]
    intro = (
        f"Measured {doc['measured_at']} (lifecycle rules at {doc['as_of']} on the database test clock) on corpus "
        f"`{doc['corpus_version']}` (lock `{doc['lock_sha256'][:12]}`) with the development queries "
        f"`{doc['queries']}` (sha256 `{doc['queries_sha256'][:12]}`), both modes through "
        "`app.search_procedures_scoped` as `mcp_read`. Written by `tests/e2e/test_retrieval_comparison_live.py`. "
        "Development figures only: no holdout case was read, and the vector threshold was chosen on these queries."
    )
    lines = [
        "# T18 retrieval comparison: exact vector search against the lexical baseline",
        "",
        intro,
        "",
        "## Results",
        "",
    ]
    for k in (str(k) for k in KS):
        lines += [
            f"### k = {k}",
            "",
            "| Metric | lexical | vector_exact |",
            "|---|---|---|",
        ]
        lx, v = doc["summary"]["lexical"][k], doc["summary"]["vector_exact"][k]
        n = lx["answerable"]
        for label, key in (
            (f"recall@{k} (mean over {n} labelled cases)", "recall_at_k"),
            (f"precision@{k} (mean over {n} labelled cases)", "precision_at_k"),
            (f"MRR@{k} (mean over {n} labelled cases)", "mrr_at_k"),
        ):
            lines.append(f"| {label} | {lx[key]} | {v[key]} |")
        for label, key in (
            (f"hit@{k}", "hit_at_k"),
            (f"every expected section in the top {k}", "all_expected_at_k"),
            ("no-source cases answered with nothing", "none_answered_empty"),
            ("cases without a forbidden section", "cases_without_forbidden"),
        ):
            lines.append(f"| {label} | {rb._rate(lx[key])} | {rb._rate(v[key])} |")
        fl, fv = lx["forbidden_rows"], v["forbidden_rows"]
        forbidden = f"{fl['forbidden']}/{fl['returned']} | {fv['forbidden']}/{fv['returned']}"
        lines += [f"| forbidden sections among the top-{k} rows | {forbidden} |", ""]
    lines += [
        "## By category (k = 5)",
        "",
        "| Category | Cases | hit@5 lexical | hit@5 vector | empty lexical | empty vector |",
        "|---|---|---|---|---|---|",
    ]
    for name, row in doc["summary"]["lexical"]["5"]["by_category"].items():
        vrow = doc["summary"]["vector_exact"]["5"]["by_category"][name]
        lines.append(
            f"| {name} | {row['n']} | {rb._rate(row['hit_at_k'])} | {rb._rate(vrow['hit_at_k'])} | "
            f"{rb._rate(row['none_answered_empty'])} | {rb._rate(vrow['none_answered_empty'])} |"
        )
    lines += ["", "## Matched questions (paired, exact McNemar)", ""]
    for label, key in (
        ("hit@5 over the labelled cases", "hit_at_5"),
        ("answered with nothing, no-source cases", "none_answered_empty"),
    ):
        p = doc["paired"][key]
        lines.append(
            f"- {label}: lexical {p['lexical']}/{p['n']}, vector {p['vector']}/{p['n']}; improved by vector: "
            f"{', '.join(p['improved']) or 'none'}; regressed: {', '.join(p['regressed']) or 'none'}; "
            f"p = {p['mcnemar_p']}: {p['claim']}."
        )
    chosen = (
        f"Vector minimum similarity {s['vector_minimum_similarity']} (`app._min_similarity()`), chosen by the rule "
        "fixed before measuring: the largest value on a 0.01 grid at which vector hit@5 over the labelled cases equals "
        "its value at 0. The table re-applies it to the stored vectors; it prints every 0.05 and every 0.01 from 0.50 "
        "to 0.80, and the JSON (`vector_threshold_sweep`) holds all 100 values."
    )
    lines += [
        "- With this few cases an exact test has little power: p >= 0.05 is not evidence that the modes are equal.",
        "",
        "## Thresholds",
        "",
        chosen,
        "",
        "| threshold | vector hit@5 | vector answered-empty |",
        "|---|---|---|",
    ]
    for row in doc["vector_threshold_sweep"]:
        if round(row["threshold"] * 100) % 5 == 0 or 0.5 <= row["threshold"] <= 0.8:
            lines.append(
                f"| {row['threshold']:.2f} | {row['hit_at_k']}/{row['answerable']} | "
                f"{row['none_answered_empty']}/{row['expect_none']} |"
            )
    rule = doc["lexical_under_the_vector_rule"]
    lexical_note = (
        "Lexical minimum rank, swept over the recorded ranks (the definer already drops 0.25 and below); it stays "
        "0.25, and the residue is T20's relevance criterion (erratum 102). The vector threshold was tuned by the rule "
        "above while lexical keeps 0.25: the same rule applied to the recorded lexical ranks chooses "
        f"{rule['threshold']:.2f} (hit@5 {rule['hit_at_k']}/{rule['answerable']}, answered-empty "
        f"{rule['none_answered_empty']}/{rule['expect_none']}), so part of the answered-empty difference between the "
        "modes is the tuning, not the method."
    )
    lines += [
        "",
        lexical_note,
        "",
        "| minimum rank | lexical hit@5 | lexical answered-empty |",
        "|---|---|---|",
    ]
    for row in doc["lexical_threshold_sweep"]:
        lines.append(
            f"| {row['threshold']:.2f} | {row['hit_at_k']}/{row['answerable']} | "
            f"{row['none_answered_empty']}/{row['expect_none']} |"
        )
    w = doc["window_experiment"]
    r = doc["repeat_embedding"]
    tenants = ", ".join(f"{tenant} {n}" for tenant, n in w["windows_per_tenant"].items())
    window = (
        f"Adjacent sections of one version joined until at least {WINDOW_WORDS} `[a-z0-9]+` words: {w['windows']} "
        f"windows ({tenants}), {w['sections_per_window']['min']}-{w['sections_per_window']['max']} sections and "
        f"{w['words_per_window']['min']}-{w['words_per_window']['max']} words each, embedded with the same prefix, "
        "ranked by cosine over the same permitted versions. A window hits when it holds a labelled section. At the "
        f"section-tuned threshold {s['vector_minimum_similarity']}: recall@5 {w['recall_at_k']}, hit@5 "
        f"{rb._rate(w['hit_at_k'])}, no-source cases answered with nothing {rb._rate(w['none_answered_empty'])}. At "
        f"threshold 0 (the ranking alone): hit@1 {rb._rate(w['hit_at_1_threshold_0'])}, MRR@5 "
        f"{w['mrr_at_k_threshold_0']}. Windows holding a section the case may not see: {w['forbidden_sections']}."
    )
    if w["every_window_a_whole_version"] and w["k_covers_every_window"]:
        window += (
            " On this corpus every returnable version is one window and k = 5 covers every window of either tenant, so "
            "hit@5 and recall@5 measure only the threshold (tuned on section embeddings), not a ranking: read this as "
            "whole-version embeddings against section embeddings, with the threshold-0 hit@1 and MRR@5 as the figures "
            "that see an order (a threshold-0 recall@5 would be 1.0 by construction). It does not measure a 300-word "
            "window."
        )
    window += " The stored unit stays one chunk per section (evidence IDs, citations and T41's labels unchanged)."

    repeat = (
        f"Each of the {r['queries']} queries embedded twice: largest component difference "
        f"{r['max_abs_component_delta']}, smallest cosine {r['min_cosine']:.10f} (bound {r['bound']}). Stored vectors "
        "are the source of truth; query vectors are computed at call time; ties break by evidence_id in byte order."
    )
    lines += ["", "## Another chunk window (experiment only)", "", window, "", "## Determinism", "", repeat, ""]
    lines += ["## Settings", ""]
    for key, value in s.items():
        lines.append(f"- `{key}`: {json.dumps(value) if not isinstance(value, str) else value}")
    lines.append("")
    return "\n".join(lines)


async def _measure(pins: model_pins.EmbeddingPins) -> list[dict[str, Any]]:
    """The `threshold` measurement: fresh embeddings of the corpus files' sections and the development queries."""
    governed = corpus.load(CORPUS)
    cases = rb.load_queries(QUERIES)
    allowed = corpus.returnable(governed, AS_OF)
    sections = [(d, s) for d in governed.documents if d.identity in allowed for s in d.sections]
    embedder = embeddings.OllamaEmbedder.from_settings()
    try:
        await embedder.verify(pins)
        stored = await embedder.embed([embeddings.document_text(s.name, s.body) for _, s in sections], pins)
        queries = await embedder.embed([embeddings.query_text(c.query) for c in cases], pins)
    finally:
        await embedder.aclose()
    scored = {
        c.id: [
            (d.evidence_id(s), embeddings.cosine(q, v))
            for (d, s), v in zip(sections, stored, strict=True)
            if d.tenant == c.tenant and (c.asset_type is None or d.asset_family in (None, c.asset_type))
        ]
        for c, q in zip(cases, queries, strict=True)
    }
    return sweep(cases, scored, GRID)


def main(argv: Sequence[str]) -> int:
    """`threshold`: print the vector sweep over the corpus files and the value ruling 6's rule chooses."""
    if list(argv[1:]) != ["threshold"]:
        print(__doc__)
        return 2
    pins = model_pins.load_embedding_pins(embeddings.PINS)
    rows = asyncio.run(_measure(pins))  # no database here, so the default event loop serves
    for row in rows:
        print(
            f"THRESHOLD {row['threshold']:.2f}: hit@5 {row['hit_at_k']}/{row['answerable']}, "
            f"answered-empty {row['none_answered_empty']}/{row['expect_none']}"
        )
    print(f"CHOSEN: {choose_threshold(rows):.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

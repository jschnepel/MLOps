"""The lexical baseline's measurement: the labelled development queries, the metrics and the report (T17, R033; Plan L
rulings 18-20; SA:665 statistics).

The queries (evals/retrieval/dev-queries.jsonl) are agent-authored development data, labelled against corpus-1: each
names its tenant, its category and either the permitted sections that answer it (`expected`) or `expect_none` (no
permitted source exists, so nothing relevant may be cited). The live test tests/e2e/test_retrieval_baseline_live.py
calls `search_procedures_scoped` as `mcp_read` for every query and hands the ranked evidence IDs to `evaluate`; the
pure functions here turn them into case-level metrics with Wilson 95% intervals and denominators, and render
reports/retrieval/t17-lexical-baseline.md and .json. T18 measures exact vector search on the same queries against the
same JSON. A returned section that the oracle (`ops_core.corpus.returnable`) does not permit for the query's tenant
at the measurement instant is "forbidden": another tenant's, superseded, expired, revoked or draft.
"""

from __future__ import annotations

import json
import math
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

K = 5  # BS:417: start top_k = 5
CATEGORIES = (
    "answerable",
    "superseded",
    "expired",
    "revoked",
    "draft_only",
    "missing_source",
    "cross_tenant",
    "asset_filtered",
    "injected",
    "conflicting",
)
KEYS = {"id", "tenant", "category", "query", "asset_type", "expected", "expect_none"}
# What the measured search does, recorded with every report (BS:417: "store retrieval settings and score
# interpretation"); docs/retrieval.md explains each line.
SETTINGS: Mapping[str, Any] = {
    "method": "PostgreSQL full-text search inside app.search_procedures_scoped (revision 0011)",
    "text_search_config": "english",
    "document_vector": "setweight(to_tsvector(section), 'A') || setweight(to_tsvector(body), 'D'), stored, GIN index",
    "query": "the OR of the query's own english lexemes, after every character outside a-z and 0-9 becomes a space",
    "rank": "ts_rank_cd(document_vector, query), default normalization (none: a longer query scores higher)",
    "tie_break": 'evidence_id ascending in byte order (COLLATE "C")',
    "minimum_rank": "greater than 0.25 (app._min_rank()), chosen on these same 47 development queries, so the "
    "baseline is a development figure, not a held-out one; tuning it is T18's",
    "k": K,
    "chunk": "one chunk per ## section; size measured as [a-z0-9]+ words",
    "filters": "tenant from the handle; latest state approved; effective at app.current_time(); not retired (a later "
    "version that left draft has reached its effective_from); asset family equal to asset_type or NULL",
}


@dataclass(frozen=True)
class Case:
    """One labelled development query."""

    id: str
    tenant: str
    category: str
    query: str
    asset_type: str | None
    expected: tuple[str, ...]
    expect_none: bool


@dataclass(frozen=True)
class Outcome:
    """What the search returned for a case (best first, with ranks) and which of those sections were forbidden."""

    case: Case
    returned: tuple[tuple[str, float], ...]
    forbidden: tuple[str, ...]

    @property
    def ids(self) -> list[str]:
        return [evidence_id for evidence_id, _ in self.returned]

    @property
    def relevant(self) -> int:
        """How many expected sections are in the top K."""
        return len(set(self.ids[:K]) & set(self.case.expected))


def load_queries(path: Path) -> list[Case]:
    """Read and check the query file: known keys and categories, unique ids, and exactly one of a non-empty
    `expected` or `expect_none`.

    Raises:
        ValueError: naming the first line that breaks a rule.
    """
    cases: list[Case] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if set(row) != KEYS or row["category"] not in CATEGORIES:
            raise ValueError(f"{path.name}:{number}: keys must be {sorted(KEYS)} and the category a known one")
        expected = tuple(row["expected"])
        if bool(expected) == bool(row["expect_none"]):
            raise ValueError(f"{path.name}:{number}: a case has expected sections or expect_none, never both or none")
        cases.append(
            Case(
                row["id"], row["tenant"], row["category"], row["query"], row["asset_type"], expected, row["expect_none"]
            )
        )
    if len({c.id for c in cases}) != len(cases):
        raise ValueError(f"{path.name}: case ids must be unique")
    return cases


def evaluate(case: Case, returned: Sequence[tuple[str, float]], permitted: Iterable[str]) -> Outcome:
    """One case's outcome; `permitted` are the evidence IDs the case's tenant may be shown at the measurement time."""
    allowed = set(permitted)
    return Outcome(case, tuple(returned), tuple(e for e, _ in returned if e not in allowed))


def wilson(successes: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    """The Wilson score interval for a proportion (SA:665); (0.0, 1.0) when there is no case at all."""
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


def proportion(successes: int, n: int) -> dict[str, Any]:
    """A count, its denominator, the rate and its Wilson 95% interval, rounded for the report."""
    if n == 0:  # no case, no interval: (0, 1) would read as a measured range
        return {"successes": successes, "n": n, "rate": None, "wilson95": None}
    low, high = wilson(successes, n)
    return {
        "successes": successes,
        "n": n,
        "rate": round(successes / n, 4),
        "wilson95": [round(low, 4), round(high, 4)],
    }


def summarize(outcomes: Sequence[Outcome]) -> dict[str, Any]:
    """Case-level metrics at K with denominators: recall, precision and reciprocal rank as means over the answerable
    cases; hit@K, every-expected@K, the expect_none cases answered with nothing, and the cases free of forbidden
    sections as proportions with Wilson intervals; the forbidden rate over every returned row."""
    answerable = [o for o in outcomes if o.case.expected]
    nones = [o for o in outcomes if o.case.expect_none]

    def reciprocal(o: Outcome) -> float:
        ranks = [i for i, e in enumerate(o.ids[:K], start=1) if e in o.case.expected]
        return 1 / ranks[0] if ranks else 0.0

    def mean(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 4) if values else None

    rows = sum(len(o.returned) for o in outcomes)
    forbidden_rows = sum(len(o.forbidden) for o in outcomes)
    categories = {}
    for category in CATEGORIES:
        members = [o for o in outcomes if o.case.category == category]
        if not members:
            continue
        categories[category] = {
            "n": len(members),
            "hit_at_k": proportion(
                sum(o.relevant > 0 for o in members if o.case.expected), sum(1 for o in members if o.case.expected)
            ),
            "none_answered_empty": proportion(
                sum(not o.returned for o in members if o.case.expect_none),
                sum(1 for o in members if o.case.expect_none),
            ),
            "forbidden_rows": sum(len(o.forbidden) for o in members),
        }
    return {
        "k": K,
        "cases": len(outcomes),
        "answerable": len(answerable),
        "expect_none": len(nones),
        "recall_at_k": mean([o.relevant / len(o.case.expected) for o in answerable]),
        "precision_at_k": mean([o.relevant / K for o in answerable]),  # the standard P@k: over k, not over rows
        # The most P@k can be: a case with m expected sections has at most min(m, K) relevant rows among K. With
        # recall 1.0 the two are equal, so a low P@k then is the labels' size, not the ranker's fault.
        "precision_ceiling_at_k": mean([min(len(o.case.expected), K) / K for o in answerable]),
        "mrr_at_k": mean([reciprocal(o) for o in answerable]),
        "hit_at_k": proportion(sum(o.relevant > 0 for o in answerable), len(answerable)),
        "all_expected_at_k": proportion(sum(o.relevant == len(o.case.expected) for o in answerable), len(answerable)),
        "none_answered_empty": proportion(sum(not o.returned for o in nones), len(nones)),
        "cases_without_forbidden": proportion(sum(not o.forbidden for o in outcomes), len(outcomes)),
        "forbidden_rows": {"forbidden": forbidden_rows, "returned": rows},
        "by_category": categories,
    }


def chunk_sizes(words: Sequence[int]) -> dict[str, Any]:
    """The distribution of the chunk-size measure (Plan L ruling 4: `[a-z0-9]+` words per section)."""
    return {"n": len(words), "min": min(words), "median": statistics.median(words), "max": max(words)}


def report(
    outcomes: Sequence[Outcome],
    *,
    corpus_version: str,
    lock_sha256: str,
    measured_at: str,
    as_of: str,
    queries_sha256: str,
    chunk_words: Sequence[int],
) -> dict[str, Any]:
    """The machine-readable report: what was measured, how, the chunk sizes, every case's ranked answer, and the
    summary. `measured_at` is the wall-clock time of the run; `as_of` is the database-clock instant the lifecycle
    rules were evaluated at (corpus-1's labelling instant), which is what makes the figures reproducible on any date;
    `queries_sha256` names the exact query file."""
    return {
        "report": "t17-lexical-baseline",
        "measured_at": measured_at,
        "as_of": as_of,
        "corpus_version": corpus_version,
        "lock_sha256": lock_sha256,
        "queries": "evals/retrieval/dev-queries.jsonl",
        "queries_sha256": queries_sha256,
        "settings": dict(SETTINGS),
        "chunk_words": chunk_sizes(chunk_words),
        "summary": summarize(outcomes),
        "cases": [
            {
                "id": o.case.id,
                "tenant": o.case.tenant,
                "category": o.case.category,
                "asset_type": o.case.asset_type,
                "expected": list(o.case.expected),
                "expect_none": o.case.expect_none,
                "returned": [{"evidence_id": e, "rank": round(r, 6)} for e, r in o.returned],
                "forbidden": list(o.forbidden),
            }
            for o in outcomes
        ],
    }


def _rate(item: Mapping[str, Any]) -> str:
    if item["n"] == 0:
        return "no cases"
    low, high = item["wilson95"]
    return f"{item['successes']}/{item['n']} = {item['rate']:.2f} (Wilson 95% {low:.2f}-{high:.2f})"


def markdown(doc: Mapping[str, Any]) -> str:
    """The human-readable report: the numbers with their denominators, the settings, and every miss by id."""
    s = doc["summary"]
    k = s["k"]
    intro = (
        f"Measured {doc['measured_at']} (lifecycle rules evaluated at {doc['as_of']}, the labelling instant, on the "
        f"database test clock) on corpus `{doc['corpus_version']}` (lock `{doc['lock_sha256'][:12]}`) with "
        f"the {s['cases']} development queries in `{doc['queries']}` ({s['answerable']} with labelled sections, "
        f"{s['expect_none']} with no permitted source), through `app.search_procedures_scoped` as `mcp_read`, k = {k}. "
        "Development data only: no holdout case was read or used. Written by "
        "`tests/e2e/test_retrieval_baseline_live.py`; the settings and how to read a score are in `docs/retrieval.md`. "
        f"Development figure, not held-out: the minimum rank is {doc['settings']['minimum_rank']}; ts_rank_cd is "
        "unnormalised, so the rank threshold depends on query length."
    )
    precision = f"{s['precision_at_k']} (ceiling {s['precision_ceiling_at_k']}: all expected sections found, no other)"
    forbidden = f"{s['forbidden_rows']['forbidden']}/{s['forbidden_rows']['returned']}"
    words = doc["chunk_words"]
    sizes = (
        f"Chunks: {words['n']} sections; words per section (`[a-z0-9]+`) min {words['min']}, median "
        f"{words['median']}, max {words['max']}. Evaluating another chunk window is T18's comparison."
    )
    lines = [
        "# T17 lexical retrieval baseline",
        "",
        intro,
        "",
        sizes,
        "",
        "## Results",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| recall@{k} (mean over {s['answerable']} labelled cases) | {s['recall_at_k']} |",
        f"| precision@{k} (top-{k} hits over {k}; mean over {s['answerable']} cases) | {precision} |",
        f"| MRR@{k} (mean over {s['answerable']} labelled cases) | {s['mrr_at_k']} |",
        f"| hit@{k} | {_rate(s['hit_at_k'])} |",
        f"| every expected section in the top {k} | {_rate(s['all_expected_at_k'])} |",
        f"| no-source cases answered with nothing | {_rate(s['none_answered_empty'])} |",
        f"| cases without a forbidden section | {_rate(s['cases_without_forbidden'])} |",
        f"| forbidden sections among all returned rows | {forbidden} |",
        "",
        "## By category",
        "",
        "| Category | Cases | hit@k (labelled cases) | answered with nothing (no-source cases) | forbidden rows |",
        "|---|---|---|---|---|",
    ]
    for name, row in s["by_category"].items():
        hit, empty = _rate(row["hit_at_k"]), _rate(row["none_answered_empty"])
        lines.append(f"| {name} | {row['n']} | {hit} | {empty} | {row['forbidden_rows']} |")
    missed = [
        c["id"]
        for c in doc["cases"]
        if c["expected"] and not set(c["expected"]) & {r["evidence_id"] for r in c["returned"][:k]}
    ]
    answered = [c["id"] for c in doc["cases"] if c["expect_none"] and c["returned"]]
    lines += [
        "",
        "## Where lexical retrieval falls short",
        "",
        f"- Labelled cases with no expected section in the top {k}: {', '.join(missed) or 'none'}.",
        f"- No-source cases that still returned sections (permitted, but no answer): {', '.join(answered) or 'none'}.",
        "- Lexical OR-matching returns any permitted section that shares a word with the question; deciding that the",
        "  evidence is insufficient is the graph's code rule (SA:377, T20; erratum 102), not the search's.",
        "",
    ]
    return "\n".join(lines)

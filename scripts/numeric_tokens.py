"""The numeric-token measurement Plan N handed to T23 (Plan O ruling 7; Plan N ruling 10; BS:71).

The lexical search turns every character outside a-z and 0-9 of the query into a space before it takes the english
lexemes (revision 0011's `regexp_replace`), while each chunk's text is parsed raw, so `0.10` in a question becomes
the two words `0` and `10` and can never meet the chunk's single `0.10`. The question here is whether that costs a
hit. evals/retrieval/numeric-queries.jsonl holds six agent-authored queries carrying the numeric tokens corpus-1 has
(0.10, 0.05 and 100 mm, 30-day, 14 days), each paired (`pair`) with a control that spells the number out or drops
it; the rows otherwise keep T17's keys, so `retrieval_baseline.evaluate` scores them. The live test
tests/e2e/test_numeric_tokens_live.py runs all twelve through `search_procedures_scoped` as `mcp_read` in both modes
at T17's labelling instant and hands the answers to `report`; the result is a measurement, and nothing here changes
the search (BS:71: a lexical change needs evidence, and even total loss is recorded and re-homed, not fixed in T23).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts import retrieval_baseline as rb

QUERIES = Path(__file__).resolve().parents[1] / "evals" / "retrieval" / "numeric-queries.jsonl"
KEYS = rb.KEYS | {"pair"}
# A number standing on its own: not a digit of an asset id such as B22, and not the tail of a longer number.
NUMBER = re.compile(r"(?<![A-Za-z0-9.])[0-9]+(?:\.[0-9]+)?")
MODES = ("lexical", "vector_exact")


@dataclass(frozen=True)
class Pair:
    """A numeric query and its control: same tenant, same labels, the number spelled out or dropped."""

    pair: str
    numeric: rb.Case
    control: rb.Case


def query_words(query: str) -> list[str]:
    """The query's words as the lexical search sees them before stemming (revision 0011's normalisation)."""
    return re.sub(r"[^a-z0-9]+", " ", query.lower()).split()


def load_pairs(path: Path = QUERIES) -> list[Pair]:
    """Read and check the pair file: T17's keys plus `pair`, labelled cases only, one numeric query (`N…`, holding a
    number) and one control (`C…`, holding none) per pair, with the same tenant, category, labels and asset type.

    Raises:
        ValueError: naming the first line or pair that breaks a rule.
    """
    rows: dict[str, list[tuple[str, rb.Case]]] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if set(row) != KEYS or row["category"] not in rb.CATEGORIES or row["expect_none"] or not row["expected"]:
            raise ValueError(f"{path.name}:{number}: keys must be {sorted(KEYS)}, labelled, of a known category")
        case = rb.Case(
            row["id"], row["tenant"], row["category"], row["query"], row["asset_type"], tuple(row["expected"]), False
        )
        rows.setdefault(row["pair"], []).append((row["id"][0], case))
    pairs = []
    for name, members in rows.items():
        roles = dict(members)
        if sorted(roles) != ["C", "N"] or len(members) != 2:
            raise ValueError(f"{path.name}: pair {name} needs one N and one C query")
        numeric, control = roles["N"], roles["C"]
        if not NUMBER.search(numeric.query) or NUMBER.search(control.query):
            raise ValueError(f"{path.name}: pair {name}: the N query holds a number and the C query none")
        same = (numeric.tenant, numeric.category, numeric.expected, numeric.asset_type) == (
            control.tenant,
            control.category,
            control.expected,
            control.asset_type,
        )
        if not same:
            raise ValueError(
                f"{path.name}: pair {name}: both queries share the tenant, category, labels and asset type"
            )
        pairs.append(Pair(name, numeric, control))
    ids = [c.id for p in pairs for c in (p.numeric, p.control)]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{path.name}: case ids must be unique")
    return pairs


def is_decimal(pair: Pair) -> bool:
    """True when the numeric query holds a decimal (0.10, 0.05): the only token revision 0011's normalisation splits
    (an integer such as 14, or 30 in 30-day, stays one word on both sides, so its pair cannot lose to it)."""
    return any("." in m for m in NUMBER.findall(pair.numeric.query))


def _hit(outcome: rb.Outcome) -> bool:
    return outcome.relevant_at(rb.K) > 0


def _rank(outcome: rb.Outcome) -> int | None:
    """The 1-based position of the first expected section in the answer, or None."""
    return next((i for i, e in enumerate(outcome.ids, start=1) if e in outcome.case.expected), None)


def report(
    pairs: Sequence[Pair],
    outcomes: Mapping[str, Mapping[str, rb.Outcome]],
    *,
    corpus_version: str,
    lock_sha256: str,
    queries_sha256: str,
    as_of: str,
    measured_at: str,
) -> dict[str, Any]:
    """The measurement: per pair and mode, hit@5 and the expected section's position for the numeric query and its
    control; per mode, the counts, the pairs lost (control hit, numeric missed) and gained, the same for the
    decimal pairs alone, and whether the loss is total: every decimal pair lost, ruling 7's bar for even proposing a
    lexical change (round 1, minor 3: only a decimal can lose to the normalisation)."""
    rows = []
    for p in pairs:
        row: dict[str, Any] = {
            "pair": p.pair,
            "tenant": p.numeric.tenant,
            "expected": list(p.numeric.expected),
            "decimal": is_decimal(p),
            "numeric": {"id": p.numeric.id, "query": p.numeric.query, "words": query_words(p.numeric.query)},
            "control": {"id": p.control.id, "query": p.control.query, "words": query_words(p.control.query)},
        }
        for mode in MODES:
            n, c = outcomes[mode][p.numeric.id], outcomes[mode][p.control.id]
            row[mode] = {
                "numeric_hit": _hit(n),
                "numeric_rank": _rank(n),
                "control_hit": _hit(c),
                "control_rank": _rank(c),
                "forbidden": sorted({*n.forbidden, *c.forbidden}),
            }
        rows.append(row)
    summary = {}
    for mode in MODES:
        lost = [r["pair"] for r in rows if r[mode]["control_hit"] and not r[mode]["numeric_hit"]]
        gained = [r["pair"] for r in rows if r[mode]["numeric_hit"] and not r[mode]["control_hit"]]
        decimal = [r for r in rows if r["decimal"]]
        decimal_lost = [r["pair"] for r in decimal if r["pair"] in lost]
        summary[mode] = {
            "numeric_hit_at_5": rb.proportion(sum(r[mode]["numeric_hit"] for r in rows), len(rows)),
            "control_hit_at_5": rb.proportion(sum(r[mode]["control_hit"] for r in rows), len(rows)),
            "lost": lost,
            "gained": gained,
            "decimal_pairs": [r["pair"] for r in decimal],
            "decimal_numeric_hit_at_5": rb.proportion(sum(r[mode]["numeric_hit"] for r in decimal), len(decimal)),
            "decimal_control_hit_at_5": rb.proportion(sum(r[mode]["control_hit"] for r in decimal), len(decimal)),
            "decimal_lost": decimal_lost,
            "total_loss": bool(decimal) and len(decimal_lost) == len(decimal),
            "forbidden_rows": sum(len(r[mode]["forbidden"]) for r in rows),
        }
    return {
        "report": "t23-numeric-tokens",
        "measured_at": measured_at,
        "as_of": as_of,
        "corpus_version": corpus_version,
        "lock_sha256": lock_sha256,
        "queries": "evals/retrieval/numeric-queries.jsonl",
        "queries_sha256": queries_sha256,
        "k": rb.K,
        "normalisation": rb.SETTINGS["query"],
        "summary": summary,
        "pairs": rows,
    }


def markdown(doc: Mapping[str, Any]) -> str:
    """The human-readable measurement: both modes' counts, every pair's two answers, and the finding."""
    intro = (
        f"Measured {doc['measured_at']} (lifecycle rules at {doc['as_of']}, T17's labelling instant) on corpus "
        f"`{doc['corpus_version']}` (lock `{doc['lock_sha256'][:12]}`) with the {2 * len(doc['pairs'])} queries in "
        f"`{doc['queries']}`: each numeric query beside a control that spells the number out or drops it, through "
        f"`app.search_procedures_scoped` as `mcp_read`, k = {doc['k']}, in both modes. Development data only; no "
        "holdout case was read. Written by `tests/e2e/test_numeric_tokens_live.py`. The lexical query is "
        f"{doc['normalisation']}, so a decimal such as 0.10 reaches the search as two words."
    )
    header = (
        "| Mode | numeric queries hit@5 | controls hit@5 | decimal queries hit@5 | decimal controls hit@5 | pairs lost "
        "| pairs gained | forbidden rows |"
    )
    lines = [
        "# T23 numeric-token measurement",
        "",
        intro,
        "",
        header,
        "|---|---|---|---|---|---|---|---|",
    ]
    for mode in MODES:
        s = doc["summary"][mode]
        lost, gained = ", ".join(s["lost"]) or "none", ", ".join(s["gained"]) or "none"
        numeric, control = rb._rate(s["numeric_hit_at_5"]), rb._rate(s["control_hit_at_5"])
        decimal = f"{rb._rate(s['decimal_numeric_hit_at_5'])} | {rb._rate(s['decimal_control_hit_at_5'])}"
        lines.append(f"| {mode} | {numeric} | {control} | {decimal} | {lost} | {gained} | {s['forbidden_rows']} |")
    lines += [
        "",
        "| Pair | Numeric query (words) | Control | lexical: numeric / control | vector: numeric / control |",
        "|---|---|---|---|---|",
    ]
    for r in doc["pairs"]:
        words = " ".join(r["numeric"]["words"])
        lines.append(
            f"| {r['pair']} | {r['numeric']['query']} (`{words}`) | {r['control']['query']} | {_cell(r, 'lexical')} | "
            f"{_cell(r, 'vector_exact')} |"
        )
    lexical = doc["summary"]["lexical"]
    lost = (
        f"{len(lexical['decimal_lost'])} of {len(lexical['decimal_pairs'])} decimal pairs lost "
        f"(lost: {', '.join(lexical['decimal_lost']) or 'none'}; decimal pairs: "
        f"{', '.join(lexical['decimal_pairs']) or 'none'}); {len(lexical['lost'])} of {len(doc['pairs'])} pairs in all"
    )
    finding = (
        f"The loss is total in lexical mode ({lost}): every decimal query missed while its control hit. This is "
        "recorded and the fix re-homed (Plan O ruling 7); T23 changes no SQL."
        if lexical["total_loss"]
        else f"The loss is not total in lexical mode ({lost}), so the search stays as it is (BS:71; Plan O ruling 7)."
    )
    lines += ["", "## Finding", "", finding, "", "Positions are 1-based within the top 5; `miss` means not there.", ""]
    return "\n".join(lines)


def _cell(row: Mapping[str, Any], mode: str) -> str:
    m = row[mode]
    return f"{m['numeric_rank'] or 'miss'} / {m['control_rank'] or 'miss'}"

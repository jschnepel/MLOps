"""Evaluation cases with their gold labels (T23, R111; SA:656; Plan O rulings 1-3).

A case is one row of a JSONL file checked against `evals/dev-case.schema.json`: the holdout case's fields (so T25
feeds the development set and the holdout through one shape), the development fields (`split`, `category`, `family`,
`as_of`) and the labels (`expected_kind`, `clarify`, `required_refs`, `allowed_refs`, `notes`). Pure: the only file it
reads is the schema and the case file it is given.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Literal

from jsonschema import Draft202012Validator, FormatChecker

ROOT: Final = Path(__file__).resolve().parents[3]
CASE_SCHEMA: Final = ROOT / "evals" / "dev-case.schema.json"
Kind = Literal["proposal", "answer", "abstain"]


@dataclass(frozen=True)
class Case:
    """One evaluation case with its gold labels (evals/dev-case.schema.json)."""

    case_id: str
    tenant: str
    asset_id: str
    request_text: str
    hours: int
    intent: Literal["investigate", "answer_only"]
    split: str
    category: str
    family: str
    as_of: datetime
    expected_kind: Kind
    clarify: bool
    required_refs: frozenset[str]
    allowed_refs: frozenset[str]
    notes: str

    @property
    def permitted_refs(self) -> frozenset[str]:
        """Every reference the case lets a draft cite: the required ones and the allowed ones (Plan O ruling 1)."""
        return self.required_refs | self.allowed_refs


class CaseError(ValueError):
    """A case file breaks evals/dev-case.schema.json; the message names the line and the rule, never its text."""


@functools.cache
def _validator(path: Path) -> Any:
    return Draft202012Validator(json.loads(path.read_text(encoding="utf-8")), format_checker=FormatChecker())


def case_from_row(row: Mapping[str, Any]) -> Case:
    """A `Case` from one schema-valid row (`load_cases` checks the schema first)."""
    return Case(
        case_id=row["case_id"],
        tenant=row["tenant"],
        asset_id=row["asset_id"],
        request_text=row["request_text"],
        hours=row["hours"],
        intent=row["intent"],
        split=row["split"],
        category=row["category"],
        family=row["family"],
        as_of=datetime.fromisoformat(row["as_of"]),
        expected_kind=row["expected_kind"],
        clarify=row["clarify"],
        required_refs=frozenset(row["required_refs"]),
        allowed_refs=frozenset(row["allowed_refs"]),
        notes=row["notes"],
    )


def load_cases(path: Path) -> list[Case]:
    """Read a JSONL case file, every row checked against evals/dev-case.schema.json, ids unique.

    Raises:
        CaseError: naming the first line that breaks the schema, or a repeated id.
    """
    cases: list[Case] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CaseError(f"{path.name}:{number}: not valid JSON (column {exc.colno})") from None
        errors = sorted(_validator(CASE_SCHEMA).iter_errors(row), key=lambda e: [str(p) for p in e.absolute_path])
        if errors:
            where = "/".join(str(p) for p in errors[0].absolute_path) or "(root)"
            raise CaseError(f"{path.name}:{number}: {where} breaks the case schema ({errors[0].validator})")
        cases.append(case_from_row(row))
    if len({c.case_id for c in cases}) != len(cases):
        raise CaseError(f"{path.name}: case ids must be unique")
    return cases

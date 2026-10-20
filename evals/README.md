These ten definitions (`development-seeds.jsonl`) are development seeds, not a completed evaluation dataset, a test runner, or measured results. See ../docs/archive/EVALUATION.md. Expand them into independent fixtures and label source evidence before any model comparison. No holdout examples are supplied.

`retrieval/dev-queries.jsonl` (T17) holds 47 labelled development queries for retrieval, measured in `reports/retrieval/` (see `../docs/retrieval.md`); they are development data, never the holdout.

`retrieval/numeric-queries.jsonl` (T23) holds six numeric-token queries, each paired with a control that spells the number out or drops it; `tests/e2e/test_numeric_tokens_live.py` measures both search modes on them in `reports/retrieval/t23-numeric-tokens.md`.

`dev/cases.jsonl` (T23) holds 60 agent-authored development cases with gold labels (schema `dev-case.schema.json`), graded by `core/src/ops_core/grading.py`; `dev/RUBRIC.md` is the owner's groundedness rubric, and each label record follows `groundedness-label.schema.json`. `quality-gates.schema.json` (T23) is the shape of `quality-gates.json`, which the owner fills in before the first holdout run (SA:671-672). None of these files is the holdout.

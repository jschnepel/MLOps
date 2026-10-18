# T17 lexical retrieval baseline

Measured 2026-10-18T06:31:44Z (lifecycle rules evaluated at 2026-10-16T12:00:00Z, the labelling instant, on the database test clock) on corpus `corpus-1` (lock `81f50c2b8623`) with the 47 development queries in `evals/retrieval/dev-queries.jsonl` (27 with labelled sections, 20 with no permitted source), through `app.search_procedures_scoped` as `mcp_read`, k = 5. Development data only: no holdout case was read or used. Written by `tests/e2e/test_retrieval_baseline_live.py`; the settings and how to read a score are in `docs/retrieval.md`. Development figure, not held-out: the minimum rank is greater than 0.25 (app._min_rank()), chosen on these same 47 development queries, so the baseline is a development figure, not a held-out one; tuning it is T18's; ts_rank_cd is unnormalised, so the rank threshold depends on query length.

Chunks: 69 sections; words per section (`[a-z0-9]+`) min 45, median 77, max 119. Evaluating another chunk window is T18's comparison.

## Results

| Metric | Value |
|---|---|
| recall@5 (mean over 27 labelled cases) | 1.0 |
| precision@5 (top-5 hits over 5; mean over 27 cases) | 0.2296 (ceiling 0.2296: all expected sections found, no other) |
| MRR@5 (mean over 27 labelled cases) | 0.8963 |
| hit@5 | 27/27 = 1.00 (Wilson 95% 0.88-1.00) |
| every expected section in the top 5 | 27/27 = 1.00 (Wilson 95% 0.88-1.00) |
| no-source cases answered with nothing | 15/20 = 0.75 (Wilson 95% 0.53-0.89) |
| cases without a forbidden section | 47/47 = 1.00 (Wilson 95% 0.92-1.00) |
| forbidden sections among all returned rows | 0/122 |

## By category

| Category | Cases | hit@k (labelled cases) | answered with nothing (no-source cases) | forbidden rows |
|---|---|---|---|---|
| answerable | 14 | 14/14 = 1.00 (Wilson 95% 0.78-1.00) | no cases | 0 |
| superseded | 4 | 4/4 = 1.00 (Wilson 95% 0.51-1.00) | no cases | 0 |
| expired | 4 | no cases | 3/4 = 0.75 (Wilson 95% 0.30-0.95) | 0 |
| revoked | 4 | no cases | 4/4 = 1.00 (Wilson 95% 0.51-1.00) | 0 |
| draft_only | 4 | no cases | 2/4 = 0.50 (Wilson 95% 0.15-0.85) | 0 |
| missing_source | 4 | no cases | 4/4 = 1.00 (Wilson 95% 0.51-1.00) | 0 |
| cross_tenant | 4 | no cases | 2/4 = 0.50 (Wilson 95% 0.15-0.85) | 0 |
| asset_filtered | 5 | 5/5 = 1.00 (Wilson 95% 0.57-1.00) | no cases | 0 |
| injected | 2 | 2/2 = 1.00 (Wilson 95% 0.34-1.00) | no cases | 0 |
| conflicting | 2 | 2/2 = 1.00 (Wilson 95% 0.34-1.00) | no cases | 0 |

## Where lexical retrieval falls short

- Labelled cases with no expected section in the top 5: none.
- No-source cases that still returned sections (permitted, but no answer): A15, B10, B13, B17, B18.
- Lexical OR-matching returns any permitted section that shares a word with the question. SA:377 as written
  counts any returned effective chunk as sufficient and would not abstain on these cases: T20 must add a
  relevance criterion beyond it (erratum 102); the share is open until then.

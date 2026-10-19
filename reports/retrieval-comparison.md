# T18 retrieval comparison: exact vector search against the lexical baseline

Measured 2026-10-19T20:48:12Z (lifecycle rules at 2026-10-16T12:00:00Z on the database test clock) on corpus `corpus-1` (lock `81f50c2b8623`) with the development queries `evals/retrieval/dev-queries.jsonl` (sha256 `d6d539bdd9a5`), both modes through `app.search_procedures_scoped` as `mcp_read`. Written by `tests/e2e/test_retrieval_comparison_live.py`. Development figures only: no holdout case was read, and the vector threshold was chosen on these queries.

## Results

### k = 5

| Metric | lexical | vector_exact |
|---|---|---|
| recall@5 (mean over 27 labelled cases) | 1.0 | 0.9444 |
| precision@5 (top-5 hits over 5; mean over 27 cases; ceiling 0.2296: all expected sections found, no other) | 0.2296 | 0.2148 |
| MRR@5 (mean over 27 labelled cases) | 0.8963 | 0.9444 |
| recall@5, expected sections found over expected sections, all labelled cases | 31/31 = 1.00 (Wilson 95% 0.89-1.00) | 29/31 = 0.94 (Wilson 95% 0.79-0.98) |
| hit@5 | 27/27 = 1.00 (Wilson 95% 0.88-1.00) | 26/27 = 0.96 (Wilson 95% 0.82-0.99) |
| every expected section in the top 5 | 27/27 = 1.00 (Wilson 95% 0.88-1.00) | 25/27 = 0.93 (Wilson 95% 0.77-0.98) |
| no-source cases answered with nothing | 15/20 = 0.75 (Wilson 95% 0.53-0.89) | 18/20 = 0.90 (Wilson 95% 0.70-0.97) |
| cases without a forbidden section | 47/47 = 1.00 (Wilson 95% 0.92-1.00) | 47/47 = 1.00 (Wilson 95% 0.92-1.00) |
| forbidden sections among the top-5 rows | 0/122 | 0/87 |

### k = 3

| Metric | lexical | vector_exact |
|---|---|---|
| recall@3 (mean over 27 labelled cases) | 0.963 | 0.9259 |
| precision@3 (top-3 hits over 3; mean over 27 cases; ceiling 0.3827: all expected sections found, no other) | 0.3704 | 0.3457 |
| MRR@3 (mean over 27 labelled cases) | 0.8889 | 0.9444 |
| recall@3, expected sections found over expected sections, all labelled cases | 30/31 = 0.97 (Wilson 95% 0.84-0.99) | 28/31 = 0.90 (Wilson 95% 0.75-0.97) |
| hit@3 | 26/27 = 0.96 (Wilson 95% 0.82-0.99) | 26/27 = 0.96 (Wilson 95% 0.82-0.99) |
| every expected section in the top 3 | 26/27 = 0.96 (Wilson 95% 0.82-0.99) | 24/27 = 0.89 (Wilson 95% 0.72-0.96) |
| no-source cases answered with nothing | 15/20 = 0.75 (Wilson 95% 0.53-0.89) | 18/20 = 0.90 (Wilson 95% 0.70-0.97) |
| cases without a forbidden section | 47/47 = 1.00 (Wilson 95% 0.92-1.00) | 47/47 = 1.00 (Wilson 95% 0.92-1.00) |
| forbidden sections among the top-3 rows | 0/85 | 0/71 |

## By category (k = 5)

| Category | Cases | hit@5 lexical | hit@5 vector | empty lexical | empty vector |
|---|---|---|---|---|---|
| answerable | 14 | 14/14 = 1.00 (Wilson 95% 0.78-1.00) | 13/14 = 0.93 (Wilson 95% 0.69-0.99) | no cases | no cases |
| superseded | 4 | 4/4 = 1.00 (Wilson 95% 0.51-1.00) | 4/4 = 1.00 (Wilson 95% 0.51-1.00) | no cases | no cases |
| expired | 4 | no cases | no cases | 3/4 = 0.75 (Wilson 95% 0.30-0.95) | 4/4 = 1.00 (Wilson 95% 0.51-1.00) |
| revoked | 4 | no cases | no cases | 4/4 = 1.00 (Wilson 95% 0.51-1.00) | 3/4 = 0.75 (Wilson 95% 0.30-0.95) |
| draft_only | 4 | no cases | no cases | 2/4 = 0.50 (Wilson 95% 0.15-0.85) | 3/4 = 0.75 (Wilson 95% 0.30-0.95) |
| missing_source | 4 | no cases | no cases | 4/4 = 1.00 (Wilson 95% 0.51-1.00) | 4/4 = 1.00 (Wilson 95% 0.51-1.00) |
| cross_tenant | 4 | no cases | no cases | 2/4 = 0.50 (Wilson 95% 0.15-0.85) | 4/4 = 1.00 (Wilson 95% 0.51-1.00) |
| asset_filtered | 5 | 5/5 = 1.00 (Wilson 95% 0.57-1.00) | 5/5 = 1.00 (Wilson 95% 0.57-1.00) | no cases | no cases |
| injected | 2 | 2/2 = 1.00 (Wilson 95% 0.34-1.00) | 2/2 = 1.00 (Wilson 95% 0.34-1.00) | no cases | no cases |
| conflicting | 2 | 2/2 = 1.00 (Wilson 95% 0.34-1.00) | 2/2 = 1.00 (Wilson 95% 0.34-1.00) | no cases | no cases |

## Matched questions (paired, exact McNemar)

- hit@5 over the labelled cases: lexical 27/27, vector 26/27; improved by vector: none; regressed: A08; p = 1.0: no ranking claim (p >= 0.05, SA:667).
- answered with nothing, no-source cases: lexical 15/20, vector 18/20; improved by vector: B10, B13, B17, B18; regressed: A13; p = 0.375: no ranking claim (p >= 0.05, SA:667).

Changes between the modes, named and descriptive only (no test is applied to them):
- every expected section in the top 5, labelled cases: lexical 27/27, vector 25/27; improved by vector: none; regressed: A08, A21.
- hit@3, labelled cases: lexical 26/27, vector 26/27; improved by vector: B02; regressed: A08.
- every expected section in the top 3, labelled cases: lexical 26/27, vector 24/27; improved by vector: B02; regressed: A04, A08, A21.
- The JSON holds every case's two answers (`cases`) and these lists (`changes`).
- With this few cases an exact test has little power: p >= 0.05 is not evidence that the modes are equal.

## Thresholds

Vector minimum similarity 0.68 (`app._min_similarity()`), chosen by the rule fixed before measuring: the largest value on a 0.01 grid at which vector hit@5 over the labelled cases equals its value at 0. The table re-applies it to the stored vectors; it prints every 0.05 and every 0.01 from 0.50 to 0.80, and the JSON (`vector_threshold_sweep`) holds all 100 values.

| threshold | vector hit@5 | vector answered-empty |
|---|---|---|
| 0.00 | 26/27 | 0/20 |
| 0.05 | 26/27 | 0/20 |
| 0.10 | 26/27 | 0/20 |
| 0.15 | 26/27 | 0/20 |
| 0.20 | 26/27 | 0/20 |
| 0.25 | 26/27 | 0/20 |
| 0.30 | 26/27 | 0/20 |
| 0.35 | 26/27 | 0/20 |
| 0.40 | 26/27 | 0/20 |
| 0.45 | 26/27 | 0/20 |
| 0.50 | 26/27 | 0/20 |
| 0.51 | 26/27 | 0/20 |
| 0.52 | 26/27 | 0/20 |
| 0.53 | 26/27 | 1/20 |
| 0.54 | 26/27 | 1/20 |
| 0.55 | 26/27 | 2/20 |
| 0.56 | 26/27 | 2/20 |
| 0.57 | 26/27 | 3/20 |
| 0.58 | 26/27 | 4/20 |
| 0.59 | 26/27 | 5/20 |
| 0.60 | 26/27 | 7/20 |
| 0.61 | 26/27 | 7/20 |
| 0.62 | 26/27 | 11/20 |
| 0.63 | 26/27 | 12/20 |
| 0.64 | 26/27 | 13/20 |
| 0.65 | 26/27 | 17/20 |
| 0.66 | 26/27 | 18/20 |
| 0.67 | 26/27 | 18/20 |
| 0.68 | 26/27 | 18/20 |
| 0.69 | 25/27 | 19/20 |
| 0.70 | 23/27 | 19/20 |
| 0.71 | 23/27 | 19/20 |
| 0.72 | 23/27 | 19/20 |
| 0.73 | 22/27 | 19/20 |
| 0.74 | 22/27 | 19/20 |
| 0.75 | 22/27 | 19/20 |
| 0.76 | 21/27 | 20/20 |
| 0.77 | 21/27 | 20/20 |
| 0.78 | 20/27 | 20/20 |
| 0.79 | 19/27 | 20/20 |
| 0.80 | 16/27 | 20/20 |
| 0.85 | 9/27 | 20/20 |
| 0.90 | 2/27 | 20/20 |
| 0.95 | 0/27 | 20/20 |

Lexical minimum rank, swept over the recorded ranks (the definer already drops 0.25 and below); it stays 0.25, and the residue is T20's relevance criterion (erratum 102). The vector threshold was tuned by the rule above while lexical keeps 0.25: the same rule applied to the recorded lexical ranks chooses 0.79 (hit@5 27/27, answered-empty 17/20), so part of the answered-empty difference between the modes is the tuning, not the method.

| minimum rank | lexical hit@5 | lexical answered-empty |
|---|---|---|
| 0.25 | 27/27 | 15/20 |
| 0.30 | 27/27 | 17/20 |
| 0.35 | 27/27 | 17/20 |
| 0.40 | 27/27 | 17/20 |
| 0.45 | 27/27 | 17/20 |
| 0.50 | 27/27 | 17/20 |
| 0.55 | 27/27 | 17/20 |
| 0.60 | 27/27 | 17/20 |
| 0.65 | 27/27 | 17/20 |
| 0.70 | 27/27 | 17/20 |
| 0.75 | 27/27 | 17/20 |
| 0.80 | 25/27 | 17/20 |
| 0.85 | 25/27 | 17/20 |
| 0.90 | 25/27 | 17/20 |
| 0.95 | 21/27 | 17/20 |
| 1.00 | 19/27 | 18/20 |

## Another chunk window (experiment only)

Adjacent sections of one version joined until at least 300 `[a-z0-9]+` words: 8 windows (alpha 5, beta 3), 4-5 sections and 327-343 words each, embedded with the same prefix, ranked by cosine over the same permitted versions. A window hits when it holds a labelled section. At the section-tuned threshold 0.68: recall@5 0.8519, hit@5 23/27 = 0.85 (Wilson 95% 0.68-0.94), no-source cases answered with nothing 19/20 = 0.95 (Wilson 95% 0.76-0.99). At threshold 0 (the ranking alone): hit@1 27/27 = 1.00 (Wilson 95% 0.88-1.00), MRR@5 1.0. Windows returned at threshold 0 (every window within the top 5) holding a section the case may not see: 0. On this corpus every returnable version is one window and k = 5 covers every window of either tenant, so hit@5 and recall@5 measure only the threshold (tuned on section embeddings), not a ranking: read this as whole-version embeddings against section embeddings, with the threshold-0 hit@1 and MRR@5 as the figures that see an order (a threshold-0 recall@5 would be 1.0 by construction). It does not measure a 300-word window. The stored unit stays one chunk per section (evidence IDs, citations and T41's labels unchanged).

## Determinism

Each of the 47 queries embedded twice: largest component difference 0.0, smallest cosine 1.0000000000 (bound 0.9999). Stored vectors are the source of truth; query vectors are computed at call time; ties break by evidence_id in byte order.

## Settings

- `model`: `nomic-embed-text`
- `model_digest`: `0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f`
- `dimension`: `768`
- `ollama_version`: `0.40.4`
- `document_prefix`: `search_document: `
- `document_text`: `search_document: + section heading + blank line + body`
- `query_prefix`: `search_query: `
- `distance`: `cosine (pgvector <=>); rank = 1 - distance, the cosine similarity`
- `vector_minimum_similarity`: `0.68`
- `lexical_minimum_rank`: `0.25`
- `index`: `none: a sequential scan over the tenant's permitted chunks, exact by construction`
- `window`: `one chunk per ## section (the stored unit)`
- `window_experiment`: `{"min_words": 300, "rule": "adjacent sections of one version"}`
- `tie_break`: `evidence_id ascending in byte order (COLLATE "C")`
- `ks`: `[5, 3]`
- `filters`: `tenant from the handle; latest state approved; effective at app.current_time(); not retired (a later version that left draft has reached its effective_from); asset family equal to asset_type or NULL`

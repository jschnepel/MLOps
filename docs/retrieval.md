# Retrieval: the governed corpus and the lexical baseline (T17)

Who this is for: whoever changes the corpus, ingests it, reads a search result, or compares another retrieval method
with this one. The design is BUILD_SPEC §11, AM-20.2, AM-20.3 (`search_procedures_scoped`), AM-20.5 and AM-50 in
`SPEC_AMENDMENTS.md`, and Plan L (`docs/superpowers/plans/2026-10-16-first-slice-l-governed-corpus.md`). Everything
in the corpus is synthetic and says so in its first paragraph; none of it is a real procedure.

## The corpus

`data/corpus/` holds 16 authored documents (14 document IDs, two of them in two versions) over two tenants (alpha 9,
beta 7), each of 332 to 349 `[a-z0-9]+` prose words counted after its title and banner lines (`corpus.prose_words`; the test's bound is 320-900 and R099's floor is 300), six
assets (three per tenant: a pump, a compressor and a conveyor) with seven alerts, and four files about them:

| File | What it is | Who writes it |
|---|---|---|
| `catalog.json` | every version: tenant, status, effective interval, `supersedes`, asset family, label, conflict partner, path, sections | authored |
| `assets.json` | asset types, assets, alerts with revisions (T16's asset-sim serves them) | authored |
| `*.md` | the documents; each opens with a title, a blank line and "Synthetic development fixture. Not an equipment-control instruction." | authored |
| `meta.json` | tenant UUIDs, asset tenants, alert UUIDs (uuid5) and every section's evidence ID, hash, offsets and word count | `uv run python -m scripts.gen_corpus_meta` |
| `corpus.sha256` | the lock: the corpus version, then the SHA-256 of the catalog, the assets file and every document | `uv run python -m scripts.gen_corpus_meta --lock` |

The versions of one document form one chain: consecutive whole numbers, each later one naming the one before it in
`supersedes` (the loader refuses anything else). Per tenant the corpus holds an approved document with a superseded
predecessor (alpha's is retired because its successor is effective, beta's also says so in its status), an expired
seasonal version, a revoked version, a draft
and an approved document carrying an injected instruction (`label: "injected"`; it is ingested and returned like any
other, because the proof that retrieved text cannot grant authority is the model side's, T19). Alpha also holds the
conflicting pair: two approved compressor documents that give different waits before a restart review
(`label: "conflicting"`, each naming the other in `conflicts_with`); both are returned, and detecting the conflict
and abstaining is T19 and T20's.

**Corpus version and freeze.** The catalog names `corpus_version` (`corpus-1`). `ops_core.corpus.RELEASES` freezes
the SHA-256 of each released version's lock. Changing a document, the catalog or the assets file without a new lock
fails `ops_core.corpus.load` (and so ingestion, the unit tests and `scripts/verify_handoff.py`); a new lock under an
old version fails too. To change the corpus: edit, set a new `corpus_version`, run the generator with `--lock`, add
the printed hash to `RELEASES` under the new version, regenerate `meta.json`, re-ingest. `corpus-1` with lock
`81f50c2b8623675f9c899033cba748f289b7f4024003385aabc8a95147b71862` is the frozen corpus T41 labels the holdout
against: any change to a locked file after T41 is a new version and requires re-labelling (T41's own text).

**Sections and evidence IDs.** A chunk is one `## ` section: the heading is its name (lower case, at most 40
characters), the evidence ID is `<DOCUMENT_ID>:v<version>:<section>`, and the stored text is exactly the body its
SHA-256 covers (the lines after the heading up to the next one, blank edges stripped), with its character offsets
`[start, end)` in the file. Sizes are measured as `[a-z0-9]+` words: corpus-1's 69 sections hold 45 to 119 words
(median 77), well under BUILD_SPEC §11's initial 300-600-token proposal. No tokenizer is locked, so no token count
is claimed; evaluating another window is part of T18's comparison.

## Ingestion

`uv run python scripts/skeleton.py ingest` loads `data/corpus` (refusing it whole if any file, rule or lock is wrong)
and ingests it as the role `worker` (AM-20.2's ingestion cells: INSERT and SELECT, no UPDATE, no DELETE) into the
database the environment names (`OPS_PG_DB`, default `ops`), one transaction per tenant under that tenant's setting.
It plans every tenant first and writes nothing if any version conflicts with what is stored:

| The catalog says, for a stored (tenant, document, version) | Ingestion does |
|---|---|
| the same file hash and attributes, the same status and interval | nothing |
| the same file hash and attributes, another status or interval | appends one `document_states` row (the latest `seq` wins) |
| another file hash, path, section list, asset family, label, `supersedes` or `conflicts_with` | refuses the whole run |
| anything other than `revoked` for a version stored as revoked | refuses the whole run (revocation is final) |
| `draft`, or another `effective_from`, for a version stored as approved or superseded | refuses the whole run (either would un-retire its predecessors; publish a new version instead) |
| nothing (the version left the catalog) | refuses the whole run (revoke it instead) |

A new version gets its `documents` row, one `chunks` row per section and its first state row. A tenant whose run
changes nothing and whose latest `corpus_ingestions` row already names this version and lock gets no row at all, so a
repeated run writes nothing. The tool reports the tenant's latest ingested version, or `none`.

## The search

`app.search_procedures_scoped(raw_handle, client_azp, query, query_embedding, asset_type, limit, mode)` is the only
reader of the corpus; only `mcp_read` may execute it, and mcp-read's `search_procedures` tool calls it after resolving
the handle in a unit of its own.

| Setting | Value |
|---|---|
| Tenant | the handle's (its lease FOR SHARE, fence, expiry, revocation, `azp`, read server); never an argument |
| Lifecycle | the version's latest state is `approved`, `effective_from <= app.current_time() < effective_to` (no `effective_to`: open), and the version is not retired: no later version of the same document (compared as numbers) that has left `draft` has reached its own `effective_from`. A retired version never comes back: revoking or expiring its successor does not bring it back, and ingestion refuses the only changes that could (a successor returned to `draft`, or its `effective_from` moved), so re-publishing old text means a new version; a draft or not-yet-effective successor retires nothing |
| Asset filter | with `asset_type`, only documents of that family or of no family |
| Text search configuration | `english` |
| Document vector | `setweight(to_tsvector(section), 'A') \|\| setweight(to_tsvector(body), 'D')`, stored, GIN index |
| Query | the OR of the query's own `english` lexemes, after every character outside `a-z` and `0-9` becomes a space |
| Rank | `ts_rank_cd` with its default normalization, which is none: a longer query reaches a higher rank |
| Ties | `evidence_id` ascending in byte order (`COLLATE "C"`, whatever the database's collation), so a retry cites the same evidence |
| Threshold | rank greater than 0.25 (`app._min_rank()`, granted to nobody), chosen on the 47 development queries: the same queries measure it, so the baseline is a development figure, not a held-out one. Because the rank is not normalised the threshold depends on query length; tuning it is T18's, with the comparison |
| Results | `limit` 1 to 8 (the worker asks for 3; the measurement uses 5); excerpt the first 500 characters |
| Vector mode | refused (`VECTOR_MODE_UNAVAILABLE`) until T18; mcp-read answers `vector_exact` with `UNSUPPORTED_MODE` first |

**How to read a score.** `ts_rank_cd` orders the sections of one query: a higher rank means more of the query's
words, closer together, with heading words weighing ten times body words (one body occurrence adds about 0.1, one
heading word about 1.0). It is not a probability, it is not
comparable between two queries, and it is not comparable with T18's vector distances (BS:417). It never reaches the
model or the tool result; the measurement records it.

**What it cannot do.** OR-matching returns any permitted section whose rank clears the minimum, so a question with
no permitted source can still get sections; the measurement reports how often. SA:377 as written counts any returned
effective chunk as sufficient, so it would not abstain on such a question; T20 must add a relevance criterion
beyond it (for example a score or label-based sufficiency rule; erratum 102). The worker sends the user's whole message (up to
500 characters) as the query.

## The measurement

`evals/retrieval/dev-queries.jsonl` holds 47 agent-authored development queries labelled against corpus-1 (never the
holdout): answerable questions with the permitted sections that answer them, and no-source questions
(`expect_none`) about superseded, expired, revoked and draft content, missing sources and the other tenant's
documents, plus asset-filtered, injected and conflicting cases. `tests/e2e/test_retrieval_baseline_live.py` runs them
all through `search_procedures_scoped` as `mcp_read` with k = 5 and writes `reports/retrieval/t17-lexical-baseline.md`
and `.json`: recall@5, precision@5 (relevant sections in the top 5, divided by 5) and MRR as means over the labelled
cases, hit@5, every-expected@5, the no-source
cases answered with nothing and the cases without a forbidden section as proportions with Wilson 95% intervals and
their denominators (SA:665), the forbidden rows over every returned row, and every case's ranked answer. A forbidden
section (another tenant's, retired, expired, revoked or draft) fails the test; the other numbers are measurements.
The query labels carry no forbidden IDs: they name only the permitted sections that answer a question. Inside the
measurement the forbidden check compares the SQL's answer with `ops_core.corpus.returnable`, which states the same
rule as the SQL, so that comparison alone is circular. The independent anchor is the hand-written returnable set in
`tests/plan_l/test_corpus_files.py` (`test_the_returnable_set_at_the_labelling_instant`): the live test sets the
database test clock to that labelling instant (so the figures hold on any date; reset afterwards) and asserts that
the permitted set it uses equals both `corpus.returnable` at that instant and the hand-written set. The report
records `as_of`, the SHA-256 of the query file, the ceiling of precision@5 (the most it can be given the labels'
size) and, for a proportion with no cases, no interval. T18 compares exact vector search against the same JSON.

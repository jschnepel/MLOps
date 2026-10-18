# Plan L review record — T17 governed corpus, ingestion and lexical baseline

Plan: `docs/superpowers/plans/2026-10-16-first-slice-l-governed-corpus.md` (branch `plan-l`; plan commit 3d7a4b3, round
fixes fad2cc9 and 82dc608). Inputs: `docs/superpowers/research/2026-10-16-plan-l-inputs.md` and the controller's rulings
brief (reproduced below). The plan writer built the slice in a scratch copy and applied the plan task by task (ruff
format between tasks, ruff, mypy strict, non-live pytest, dev counts, red steps); each round is one static adversarial
review that repeated that apply on a fresh `git archive` tree. Live steps cannot run in a dry run (no database
credentials in a scratch tree), so every live count in the plan is arithmetic until execution. In round 1 the critic,
unasked, ran revision 0011's function body read-only in the dev server's `postgres` maintenance database (no writes, `ops`
and `incident` untouched); the controller did not authorise that again, and round 2 connected to no database.
Round 1: REVISE, 0 Blocking, 3 Important, 10 Minor. Round 2: REVISE, 1 Blocking, 2 Important, 3 Minor; all applied in
82dc608 without a third round (execution's live steps are the check the static rounds cannot make).

Controller ruling on round 2's one open point: lengthening or clearing `effective_to` stays allowed. It can un-expire a
version, never un-retire one, and it happens only by an explicit catalog change, so nothing expired is treated as current
silently (BS:413); it is recorded in the plan's open points.

---

# Controller brief (rulings before round 1)

## Plan L brief — controller rulings for T17 (governed corpus, ingestion, lexical baseline)

Branch `plan-l` (= `plan-k` 00d388f + the fact sheet abffabb). Fact sheet:
`docs/superpowers/research/2026-10-16-plan-l-inputs.md` (FS). Errata continue at **93**. Requirements: R032, R033,
R099 (T17's own); R131's read half moves one step (`search_procedures_scoped` joins; `asset_scope` stays T16). Gates at
start: dev 1161 / 182; live 1322 / 21; verify_handoff 0.

Principle: T17 builds the **governed store and its one reader**: the corpus files, the tables, the idempotent
ingestion, the SQL lexical search behind `search_procedures_scoped`, mcp-read switched to it, and a measured
baseline. Vector search (T18), the asset tools and asset-sim (T16), the requester-membership re-check at read time
(T16, R028), the grant's document recheck (T21), revocation in derived state (T26) and the model-side injection
tests (T19) stay with their owners.

### Rulings (one per FS question)

1. **Who builds the function (FS Q1) — option (a).** T17 creates `search_procedures_scoped` as a definer, grants
   EXECUTE to `mcp_read` only, and switches mcp-read's `search_procedures` tool to call it. That gives the definer
   its caller (Plan E ruling 1). The R131 live ACL equality for `mcp_read` becomes `{current_time,
   resolve_invocation, search_procedures_scoped}`; `mcp_exec`'s assertion (no read function) gains the new function
   in its "every other app function" set. Erratum 72 is narrowed by an erratum: only `asset_scope` (T16) is missing.
2. **pgvector (FS Q2).** The `vector` extension is **bootstrap infrastructure**, like the roles: `skeleton.py`'s
   ensure step runs `CREATE EXTENSION IF NOT EXISTS vector` (as the superuser, in the target `ops`/`ops_test`
   database) and the live conftest's database recreation gets it the same way (through the same function, not a
   copy). The revision does not create or drop it; it asserts that the type exists and fails loudly otherwise, so the
   downgrade stays exact. The function has SA:461's full signature with `query_embedding public.vector(768)`
   (schema-qualified: definers pin `search_path = app, pg_temp`). `mode = 'vector'` is refused inside the function
   with a distinct error class until T18 (debt line). mcp-read keeps answering `vector_exact` with
   `UNSUPPORTED_MODE` before calling it (the translation `vector_exact` → `mode=vector` stays T16/T18).
3. **Tables (FS Q3).** `documents` and `chunks` (AM-20.2's names). `embeddings` → T18 (debt; no table without a
   writer). Two append-only tables the matrix lacks, by erratum (the spec's own "append-only state rows replace
   UPDATEs" principle, because AM-20.2 gives the corpus no UPDATE): `document_states` (lifecycle rows) and
   `corpus_ingestions` (one row per tenant per ingestion run). Grants for all four: `worker` ins, sel;
   `app_definer` sel; nobody else; ENABLE + FORCE RLS with the `tenant_isolation` policy (AM-20.5), owner
   `migrator`, added to `privileges.py` (GRANTS, RLS_TABLES, DEFINER_FUNCTIONS) so the matrix tests see them.
   Composite keys carry `tenant_id` (BS:246): `chunks` reference `documents` by `(tenant_id, document_id, version)`.
4. **Chunk = section (FS Q4).** One chunk per `## ` section, the evidence ID `<DOCUMENT_ID>:v<version>:<section>` as
   today, the stored text exactly the section body the hash covers, with character offsets `[start, end)` into the
   file and a word count. No tokenizer package: the chunk-size measure is recorded as the `[a-z0-9]+` word count and
   the report prints the distribution; evaluating another window is a T18 debt line (the comparison report).
5. **Ingestion (FS Q5).** A module `ops_core.corpus` (parse + validate, pure) plus an ingestion runner connecting
   **as `worker`** (AM-20.2 "ins, sel (ingestion)"), one transaction per tenant with `app.tenant_id` set
   transaction-locally; exposed as `skeleton.py ingest` (dev profile default, `--profile test` for tests). No job
   type, no migration data. Services do not refuse to start on an empty corpus: an empty corpus answers `results:
   []`, which the worker already turns into INSUFFICIENT_EVIDENCE (fail closed).
6. **Idempotency and conflicts (FS Q6).** Identity `(tenant, document_id, version)`; content hash = the file's
   sha256. Validate the **whole catalog before writing anything**; any refusal refuses the whole run (exit non-zero,
   nothing written). Same identity + same hash + same immutable attributes → no-op ("unchanged"). Same identity +
   different hash, or a changed immutable attribute (path, sections, asset family, label, supersedes) → refused
   ("conflict"). A lifecycle change (status or effective interval) on an unchanged identity appends a
   `document_states` row. `revoked` is terminal (a later different status for a revoked version is refused). A second
   identical run writes nothing but its `corpus_ingestions` row (or nothing at all — the writer chooses and states it;
   the test pins it).
7. **Lifecycle vocabulary (FS Q7).** Catalog statuses `draft`, `approved`, `superseded`, `revoked`; fields
   `effective_from` (required), `effective_to` (optional, exclusive), `supersedes` (optional version). A chunk is
   returned only when its version's latest state is `approved`, `effective_from <= now < effective_to` (or no
   `effective_to`), and no other `approved` version of the same document whose `supersedes` names it is effective at
   `now`. So "superseded" is both an explicit status and derived from an effective successor; "expired" is derived
   from `effective_to`; "revoked" is a status.
8. **The clock (FS Q8).** Compared at query time against `app.current_time()` (the test clock in the test profile;
   reset in `finally`). Ingestion validates intervals (`effective_to > effective_from`) but decides nothing about
   "now".
9. **Shared documents (FS Q9).** Tenant-only. No shared policy in v1 (erratum against BS:413's "or explicit shared
   policy"; per-tenant copies if ever needed).
10. **Access filtering (FS Q10).** Tenant (from the handle, never an argument) + lifecycle + optional `asset_type`.
    The requester's current membership re-check at read time → T16 (R028) debt line.
11. **Assets (FS Q11).** `data/corpus/assets.json`: at least 6 assets, at least 3 per tenant, each with an
    `asset_type` (a small vocabulary, e.g. `pump`, `compressor`, `conveyor`), seeded tenant UUIDs, and alerts with
    UUID5 IDs and revisions (the tenant/alert UUID fixtures of R099) — consumed later by T16's asset-sim. Documents
    carry an optional `asset_family`; `NULL` means "any asset". With `asset_type` given, the search returns chunks
    whose family equals it or is NULL. mcp-read's tool gains the optional `asset_type` argument (the input schema
    already has it); the run's own asset type lookup → T16.
12. **Where the corpus lives (FS Q12).** A new directory `data/corpus/` with its own `catalog.json`, Markdown
    documents, `assets.json` and a generated `meta.json` (section hashes, tenant UUIDs, alert UUIDs, offsets),
    generated by a script and guarded like `gen_fixture_meta.py` is (a unit test + `verify_handoff.py` regenerating
    and comparing, LF/no-BOM). **Document IDs are disjoint from `data/handoff-fixtures/`**, which stays the delivered
    contract fixture (schema examples, the 1.0 manifest) and is no longer served by mcp-read. At least 14 documents
    (7 per tenant), 300–900 words each, every one starting with the fixtures' "Synthetic development fixture. Not an
    equipment-control instruction." line; per tenant: one superseded pair (v1 → v2), one expired version, one revoked
    version, one draft, one injected-instruction document, and across the corpus one conflicting-procedure pair.
13. **Injected documents (FS Q13).** One per tenant, `approved`, ingested normally (AM-50 wins over the fixtures
    README's guidance, which is updated to say so), labelled `label: "injected"` in the catalog. The label is stored,
    not returned by the tool and not filtered: the model-side proof is T19's (R036). The injected text is clearly
    synthetic administrator-style text ("ignore your permissions…"), never a working instruction against a real
    system.
14. **Conflicting pair (FS Q14).** Both `approved` and effective, `label: "conflicting"` with a `conflicts_with`
    document ID recorded in the catalog (stored for labelling); retrieval returns both; detection and abstention →
    T19/T20.
15. **Evidence IDs and hashes (FS Q15).** As ruling 4: heading text as today (`^## (?P<name>\S.*?)\s*$`), unique per
    document, ≤120 characters; the section-hash rule unchanged (fixtures README `:15`); offsets stored.
16. **Schema examples (FS Q16).** Fix the `TODO(T17)`: the examples cite the handoff fixture's **section** hash for
    `ALPHA-INCIDENT:v2:review` (`meta.json`), regenerated by `build_schemas.py`; `verify_handoff --contracts` stays 0.
17. **Corpus version (FS Q17).** Hand-set `corpus_version` in `data/corpus/catalog.json` (`corpus-1`) plus a committed
    lock `data/corpus/corpus.sha256` over the catalog, assets and every document (sorted, LF). The gate fails when
    the content changes without a new lock (and the lock without a new version). Ingestion records `corpus_version`
    and the catalog lock hash in `corpus_ingestions`; the tool reports the tenant's latest ingested version (or
    `"none"` when nothing was ingested). The examples' `fixture-1` vs `handoff-1` mismatch: the examples use the
    handoff catalog's own `handoff-1`.
18. **Full text (FS Q18).** Text-search configuration `english`; a stored generated `tsvector` on `chunks` (heading
    weight A, body weight D) with a GIN index; the query is the **OR of the query's lexemes** (built from the query
    text in SQL, so a whole user message still matches); rank `ts_rank_cd`; tie-break `evidence_id` ascending (a retry
    cites the same evidence); zero-rank rows dropped; `limit` 1..8. A minimum-rank threshold is a recorded retrieval
    setting chosen on the dev queries only (it may be 0); the settings and the score interpretation ("ranks within one
    query, not a probability, not comparable across methods") are written in `docs/retrieval.md`. No score in the tool
    result (the schema has none); the measurement records it.
19. **Dev queries and measurement (FS Q19).** `evals/retrieval/dev-queries.jsonl`, at least 40 agent-authored
    development queries (dev data, never the holdout), per tenant, each with `expected` evidence IDs (the permitted
    relevant sections) or `expect_none: true`; categories: answerable, missing source, superseded/expired/revoked
    (the old version must not appear), draft-only, cross-tenant probe (the other tenant's procedure must not appear),
    asset-type filtered, injected/conflicting. Metrics at k=5: recall@5, precision@5, MRR, hit@5, the
    forbidden-section rate (must be zero, with its denominator), and for `expect_none` the share answered with no
    result. Case-level Wilson 95% CIs and denominators (SA:665). Report `reports/retrieval/t17-lexical-baseline.md`
    plus a machine-readable `.json` next to it; T18 compares against the same file.
20. **The measured path (FS Q20).** The definer itself, called as `mcp_read` with staged runs and read handles (one
    per tenant), in a live test that rewrites the report — the real SQL path, not a Python copy. One HTTP live test
    shows the tool end-to-end through mcp-read.
21. **mcp-read's in-memory corpus (FS Q21).** Retired: `procedures.py`, `load_corpora` and the fixtures path leave
    mcp-read (`OPS_FIXTURES_DIR` goes if nothing else reads it); the tool runs resolution and the search in the
    database; mcp-read's startup asserts the T17 function marker (`assert_function_text`, the existing pattern). Unit
    and live tests that pinned the fixture ranking are rewritten against the corpus; nothing is deleted without its
    replacement.
22. **The grant's document recheck (FS Q22).** T21's (debt line); T17's state rows make it a query, nothing more.
23. **Freezing (FS Q23).** T17's close-out declares `corpus-1` with its lock hash as the frozen identity T41 labels
    against; any lock change after T41 requires re-labelling (already T41's text). Recorded in SESSION_STATE and
    `docs/retrieval.md`.
24. **Revision and the dev database (FS Q24).** Revision `0011_governed_corpus` (exact downgrade to 0010, frozen
    statements in the revision); mcp-read asserts its marker; the ingestion runner asserts the relations. The dev
    database waits for the owner (`skeleton.py migrate`, then `skeleton.py ingest`) — owner-input line and debt line.

### Task shape (≤ 6 tasks)
1. Debt list; the extension bootstrap; revision 0011 (tables, states, ingestions, RLS, grants, `search_procedures_scoped`
   with lexical search and the lifecycle rule) + `privileges.py` + startup marker + live definer tests (lifecycle,
   cross-tenant, asset filter, ties, downgrade round trip, ACL).
2. The corpus: `data/corpus/` documents, catalog, assets, generator for `meta.json`, the lock, the checker and unit tests
   (R099 evidence).
3. Ingestion: `ops_core.corpus` validation, the runner as `worker`, `skeleton.py ingest`; unit tests + live tests
   (repeat → no-op, changed hash → refused and nothing written, supersede/revoke → state rows and retrieval changes)
   (R032).
4. mcp-read switched to the definer (+ `asset_type`), `procedures.py` retired, the worker/live tests moved to the
   corpus, the schema-example fix, R131's ACL update, the HTTP live test.
5. Dev queries, the measurement through the definer, `docs/retrieval.md`, the report (R033).
6. Close-out (handoff, matrix rows R032/R033/R099 + R131 note, errata 93+, runbook updates, STATUS, SESSION_STATE incl.
   "migrate and ingest dev" and the next step computed from tasks.json, ARCHITECTURE, PROJECT_HISTORY, READMEs).

### Standing constraints
Carry Plan K's Global Constraints (no attribution; CODE_COMMENTS; debt before code; `app.current_time()` after locks;
one string per SQL function + ISC004; exact downgrades; live tests only on test databases; never migrate dev; no token
or raw handle in logs/asserts/evidence/command lines; never cancel a database unit; pids before transactions; settle
before purges; test clock reset in finally; subprocess servers terminated in finally with secrets only via environment;
red-step Expected lines as pytest prints them; live counts marked arithmetic). Authored text is synthetic and says so;
no real procedure, employer SOP or external data. The holdout is never read or written.

---

# Controller rulings on the writer's departures

## Plan L — controller rulings on the writer's departures (draft 3d7a4b3)

1. `search_procedures_scoped(raw_handle, client_azp, query, query_embedding, asset_type, limit, mode)` — ACCEPTED
   (erratum 93): `_resolve_handle` binds the handle to the token's azp, as `resolve_invocation` does.
2. One row `(corpus_version, results jsonb)` with a rank per result; mcp-read drops the rank — ACCEPTED (the version
   must be reportable on an empty result; the rank feeds the measurement only).
3. Vector mode refused with OC005 / `VECTOR_MODE_UNAVAILABLE` — ACCEPTED provided the critic confirms OC005's existing
   meaning fits a refusal and that mcp-read maps it to a plain tool error (never reached today: mcp-read refuses
   `vector_exact` first).
4. `skeleton.py ingest` takes its target from `OPS_PG_DB` like `migrate` — ACCEPTED.
5. R131's live ACL equality changes in Task 1 with the grant — ACCEPTED.
6. 16 authored files carrying 14 document IDs — ACCEPTED (≥12 documents of 300–900 words holds either way; the R099
   test must state which it counts).
7. Corpus tables in `locking.NEVER_LOCKED` — ACCEPTED.

Live: no SQL of 0011 or `ops_core.ingest` has run. The critic reads that SQL as the highest-risk part; execution
runs it live in the real tree (Task 1/3 live steps), and their Expected lines are provisional until then.

---

# Round 1

## Static review

### Plan L, round 1: adversarial static review (critic 1)

Plan: `docs/superpowers/plans/2026-10-16-first-slice-l-governed-corpus.md` at `3d7a4b3` (6622 lines). Binding inputs
read: `brief.md`, `writer-departures-rulings.md`, the fact sheet, `AGENTS.md`, `docs/CODE_COMMENTS.md`,
`SPEC_AMENDMENTS.md` (over `BUILD_SPEC.md`).

#### Verdict: REVISE

0 Blocking, 3 Important, 10 Minor. The plan executes exactly as written: every red step printed its Expected line,
every green step passed, and every dev count, mypy and `verify_handoff` matched after every task. The body of
`search_procedures_scoped` also compiles and behaves as the live tests expect when PL/pgSQL runs it on PostgreSQL 17.11
(details under "Method"). What needs revising is the evidence and the edges of the design:

- R033 is recorded as verified, but the clause "missing source remains missing" is not met: the emulated measurement
  answers 17 of the 20 no-source questions.
- The lifecycle rule lets two versions of one document be returned at once, and the loader does not reject the
  catalogs that cause it.
- R099's word counts pass only when the title and the synthetic banner are counted.

All three are cheap to fix now. The third is not cheap once `corpus-1` is frozen for T41.

#### Method

**A. Mechanical.** I extracted a fresh tree (`git archive HEAD | tar -x -C planl/critic1-tree`, `git init`, base
commit). I applied every task with my own applier (`planl/critic1/apply.py`, not the writer's harness). It writes every
`Create`/`Replace the whole of` block, applies every `Edit n` only on an exact single match, and runs every
`git add/rm/commit`, every non-live `Run:` line, the gates and the Task 6 records script. Before each gate step it runs
`ruff format --check` and then `ruff format`. The log is `planl/critic1/t1.log` and `planl/critic1/t2-6.log`.

| Step (plan line) | Expected | Got |
|---|---|---|
| Base gate | 1161 passed, 182 skipped | 1161 passed, 182 skipped, GREEN |
| T1 red (607) | 9 failed: 6 FileNotFoundError, 2 AttributeError, 1 DID NOT RAISE | identical |
| T1 green (1205) | 218 passed | 218 passed |
| T1 gate (1658) | 1173 / 187 | 1173 passed, 187 skipped, GREEN; verify 0 |
| T2 red (2679) | 1 error, ImportError `corpus` | identical |
| T2 lock (3206) | the two lines, lock `0f5c6ee1…` | identical; `corpus.sha256` byte-identical to 3218-3238 |
| T2 green (3242) | 21 passed | 21 passed |
| T2 gate (3344) | 1194 / 187 | 1194 / 187, GREEN; verify 0 (prints the new corpus PASS line) |
| T3 red (3518) | 1 error, ImportError `ingest` | identical |
| T3 green (3927) | 39 passed | 39 passed |
| T3 gate (4182) | 1203 / 189 | 1203 / 189, GREEN; verify 0 |
| T4 red (4377) | 6 failed, TypeError … `'corpora'` | identical |
| T4 green (4872) | 242 passed | 242 passed |
| T4 build_schemas (4945) | the summary line; 33 changed examples, no schema | identical; 33 files, all under `schemas/examples/` |
| T4 plan_c (4951) | 285 passed, 19 skipped | identical |
| T4 gate (5180) | 1207 / 189 | 1207 / 189, GREEN; verify 0 |
| T5 red (5384) / green (5691) | 1 error / 5 passed | identical |
| T5 gate (5918) | 1212 / 190 | 1212 / 190, GREEN; verify 0 |
| T6 records (5962) | prints the span; 3 handoff files changed | yes; 3 files |
| T6 git grep (6536) | both print nothing | nothing |
| T6 final gates (6545) | 1212 / 190; verify 0 | identical |

Other mechanical results:

- **Edits and formatting.** Every Edit matched exactly once. `ruff format --check` reported every file already
  formatted before every gate.
- **Line length.** No Python file the plan touches has a line over 120 characters (the plan's counting script).
- **mypy.** `mypy --strict` on the new `scripts/retrieval_baseline.py`, `scripts/gen_corpus_meta.py`,
  `ops_core/corpus.py` and `ops_core/ingest.py` finds no error of the plan's own. The one error it prints is
  pre-existing, in `scripts/gen_seed_ids.py:30`.
- **Live suite: not run.** I could not run it: the scratch tree has no `.env`, and I did not open one or copy one. So
  every live Expected line (1638 `6 passed`, 4167 `2 passed`, 5162 `9 passed`, 5789 `1 passed`, and every
  `--profile test` count) is unverified. The live counts are consistent with the measured dev counts and the stated
  live-gated arithmetic: 166, 166, 168, 168, 169.

**B. The SQL nobody has run: an emulation, read-only.** I executed revision 0011's own PL/pgSQL body on the
running dev server (PostgreSQL 17.11, image `pgvector/pgvector:pg17`). I did this through
`docker exec … psql -d postgres` with `PGOPTIONS='-c default_transaction_read_only=on'`. It was a DO block per case:
no DDL, no table, no write, and the `ops`/`incident` databases were not touched.

The generator, `planl/critic1/gen_sql.py`, takes `SEARCH_PROCEDURES_SCOPED` from the scratch tree's revision file
verbatim. It substitutes only:

- the `_resolve_handle` call, which becomes a literal tenant;
- the `_authority` call, which becomes `PERFORM 1`;
- `FROM corpus_ingestions i`, which becomes a VALUES row;
- `app.current_time()`, which becomes a literal or `now()`;
- `RETURN NEXT`, which becomes `RAISE NOTICE`.

It also prepends CTEs named `document_states`, `documents` and `chunks` that hold the corpus-1 rows. Each CTE is
filtered by the tenant, as RLS would filter, and computes the stored `tsvector` expression exactly as the DDL writes it.
The output is `planl/critic1/run2.out` (raw) and `run2.txt` (readable). Results:

- **The body works as written.** It compiles and runs under PL/pgSQL. The OUT parameters `corpus_version`/`results`
  raise no variable-conflict error. The other constructs also run as written:
  - `WITH … SELECT … INTO results`;
  - `DISTINCT ON` for the latest state;
  - the `USING` chains;
  - `to_tsquery('simple', …)` over the `english` lexemes;
  - the `RAISE … ERRCODE 'OC005'`.
- **Lifecycle (the staged rows of `test_only_approved_effective_unsuperseded_versions_are_returned`).**
  - At now: `[DOC-A:v2, DOC-H:v1, DOC-I:v1]`.
  - At now + 2 days: `[DOC-A:v2, DOC-E:v1, DOC-H:v1, DOC-I:v2]`.
  - Both equal plan lines 1399 and 1407.
- **Asset families.** No asset type gives `[COMPRESSOR, PUMP, SHARED]`, `pump` gives `[PUMP, SHARED]` and `valve`
  gives `[SHARED]`, as plan lines 1436-1439 expect.
- **Ties, limit and stop words.** These match 1469-1479:
  - `turbine bearing` gives `[TIE-A, TIE-B]` at an equal rank of 0.3;
  - `limit=1` gives `[TIE-A]`;
  - `the and of` gives `[]`;
  - `Turbine!!! casing??` gives A and B at 0.3, then C at 0.1.
- **Refusals.** `mode='vector'` raises OC005/`VECTOR_MODE_UNAVAILABLE`. `limit 9` and `mode NULL` raise
  OC005/`BAD_ARGUMENT`.
- **No query can raise a tsquery syntax error.** These inputs all succeed:
  - quotes, backslashes and `& | ! : * ( )`;
  - only punctuation (answers `[]`);
  - non-ASCII text (letters are stripped, answers `[]`);
  - digits;
  - a 500-character query of 120 words.

  The reason is structural: after `regexp_replace(lower(q), '[^a-z0-9]+', ' ')`, the `english` lexemes are runs of
  `[a-z0-9]` joined by ` | `.
- **Live-test queries on corpus-1.**
  - Task 4's QUERY "repeated alerts on one asset" with limit 2 gives `[ALPHA-ALERT-REVIEW:v1:repeated-alerts 2.9,
    …:purpose 0.7]`, so ANSWER is present (5030, 5091, 5136).
  - "inspection interval and alerts" with `pump` returns only ALPHA-ALERT-REVIEW and ALPHA-PUMP-SEAL sections (5035).
  - The R105 message with limit 3 returns three ALPHA-ALERT-REVIEW sections (5152).
  - Ingestion's "repeated alerts summarized in one incident draft" with limit 8 includes repeated-alerts (4081).
  - "vendor portal visit window planner" returns four ALPHA-VENDOR-PORTAL sections (4122). With v2 stored, the same
    four come from v2.
- **The 47 development queries, k = 5.**
  - hit@5 is 27/27 and every-expected@5 is 27/27.
  - No-source cases answered with nothing: **3/20** (A20, B15, B16).
  - Forbidden rows: 0, which is structural, given the filters.

  This is an emulation, not the live measurement. Ranks depend only on the stored text, so the live report should
  agree.

**Not covered by the emulation.** These remain unverified, and the Task 1/3 live steps are the first real test of
them:

- the DDL: the tables, the generated column, the CHECKs/FKs, `ENABLE`/`FORCE`, the policy, the grants and the owners;
- `_resolve_handle`, `_authority` and `app.current_time()` inside the real definer;
- the worker's INSERTs under `WITH CHECK`;
- the exact downgrade;
- the live ACL queries.

From the catalog I confirmed that `to_tsvector(regconfig,text)`, `setweight(tsvector,"char")` and `tsvector_concat` are
all IMMUTABLE (`provolatile = i`), so the generated column is legal.

#### Blocking

None found.

#### Important

##### I1. R033 is recorded as implemented and verified, but its second clause is not met and depends on an undecided erratum

**Plan lines:**

- 6031-6048 and 6058-6061: the R033 row, `IMPLEMENTED_LOCALLY_VERIFIED`, `RECORDED_LOCALLY_LIVE`.
- 6289-6293: STATUS "Evidenced … R032 and R033".
- 6110-6112: SESSION_STATE "T17 is DONE; R131's read half is met subject to … erratum 96". It does not mention 102.
- 5972-6001: the T17 review note.
- 287-289 and 6192-6194: erratum 102.

**Evidence.** R033's expected evidence (`handoff/acceptance-matrix.json`) reads: "Known questions return labeled
permitted sections; **missing source remains missing, not guessed.**"

- The plan itself says lexical OR-matching returns a permitted section for nearly every no-source question, and it
  proposes erratum 102 to move that clause to T20's abstention rule.
- The emulated measurement (Method B) answers **17 of 20** no-source cases with sections: A11-A19, B09-B14, B17 and
  B18.
- The matrix vocabulary defines `IMPLEMENTED_LOCALLY_VERIFIED` as "the core library or contract exists and those tests
  verify it". These tests verify the first clause only.

The T47 precedent (Plan K) marked R131 as met only "subject to the owner's decisions on errata 72 and 91", in
tasks.json and in SESSION_STATE. Plan L does that for R131 and erratum 96 but not for R033 and erratum 102.

**Fix.** Do one of these, or both:

- **(a)** Record R033 as met **subject to the owner's decision on erratum 102** in every place the R131 precedent
  used: the tasks.json review note, SESSION_STATE "Next task" and the "Plan L executed" bullet, and STATUS's
  "Evidenced" line. Alternatively, keep R033 at `NOT_IMPLEMENTED_OR_NOT_TARGET_VERIFIED` with an evidence note until
  T20.
- **(b)** Use the option ruling 18 already grants: "a minimum-rank threshold … chosen on the dev queries only (it may
  be 0)".
  - In the emulation, a threshold of rank > 0.25 keeps hit@5 at 27/27 and raises no-source-answered-empty from 3/20
    to 16/20. A threshold of 0.35 gives 17/20.
  - Caveats:
    - `ts_rank_cd` is not normalised, so the threshold depends on query length;
    - 47 cases is a small development set;
    - the value would live in revision 0011's frozen body, so it must be decided before execution;
    - it must be recorded as a setting in `SETTINGS` and `docs/retrieval.md`.
  - If (b) is not taken, the debt line "a minimum rank beyond 'greater than 0' → T18" (404-407) stays, and (a) is
    mandatory.

##### I2. Two versions of one document can be returned at once, the loader permits it, and the oracle cannot see it

**Plan lines:**

- 851-866: the `latest`/`effective`/`permitted` CTEs.
- 201-204: ruling 7 as implemented.
- 3002-3006 and 3046-3049: `load` only checks that `supersedes` names an earlier version present in the catalog.
- 3064-3078: `returnable`, the same rule.
- 3645-3658: ingestion accepts any of these shapes.
- 6290-6291 (STATUS) and 6344-6345 (ARCHITECTURE §9): "only approved, effective, unsuperseded versions … are **ever**
  returned"; "can only ever be shown".

**Evidence.** The ruling's rule ("no other approved version … whose `supersedes` names it is effective at now") is
correct for a linear, gap-free chain. The plan does not ensure that the catalog is one. These catalogs pass `load` and
ingestion, and then both versions come back:

- **(a)** v2 is approved and effective without `supersedes`. v1 and v2 are both returned.
- **(b)** v3 has `supersedes: "1"` while v2 is approved and effective. v2 and v3 are both returned.
- **(c)** A chain gap: v1 ← v2 ← v3, where v2 is revoked, expired or not yet effective and v3 is effective. v1 is named
  only by the non-effective v2, so v1 and v3 are both returned.
- **(d)** Resurrection: revoking an approved successor brings back a predecessor whose own status is still
  `approved`. Alpha's ALPHA-PUMP-SEAL v1 is exactly that.

R032's expected evidence says "only permitted effective **version** retrieves". The baseline's hard zero (5781) tests
the SQL against `returnable`, which applies the same rule, so none of (a)-(d) would ever count as forbidden. corpus-1
happens to contain none of them. The first catalog edit that does would pass every gate.

**Fix.**

- **(1)** Make `load` refuse a document whose versions do not form one chain: every version after the lowest must
  name the immediately preceding catalog version in `supersedes`. Add the refusal to
  `test_the_loader_refuses_a_broken_catalog`, with one case for "no supersedes" and one for "skips a version". That
  closes (a) and (b) without touching ruling 7.
- **(2)** For (c) and (d), either:
  - write them down as known semantics in `docs/retrieval.md` and erratum 94 ("a version revoked under an approved
    successor brings its predecessor back unless that predecessor is `superseded`"); or
  - ask the controller for the transitive reading: a version is superseded when any later version of the same
    document is approved and effective.

  Then soften "ever" in 6290 and 6344 to the rule actually implemented.

##### I3. R099's "300-900 words" holds only when the title and the synthetic banner are counted, and corpus-1 is about to be frozen

**Plan lines:** 1731-2330 (the 16 documents), 2529-2537 (the bound test, which counts `WORD` over the whole file),
6049-6056 (the R099 row), 6604-6605 (self-review), 68-70 (departure 6).

**Evidence.** `[a-z0-9]+` words per file, measured on the scratch tree:

- **The whole file (the plan's measure):** minimum 303 (beta-summer-cooling). Five files are within 20 words of the
  floor.
- **Without the title and the eight-word banner line:**
  - six files fall below 300: alpha-winter-belt 299, alpha-noise-survey 296, alpha-vendor-portal 299,
    beta-pump-align-v2 294, beta-compressor-oil 299, beta-summer-cooling 291;
  - **10 documents** qualify, fewer than the 12 that AM-50/R099 require.
- **Section bodies only:** 8 of 16 are below 300.

AM-50 says "authored documents of 300-900 words". Whether a title and a fixed boilerplate banner count is the kind of
question an owner or reviewer will ask. Ruling 23 freezes `corpus-1` with its lock as T41's labelling identity, so
fixing this after T41 means a new corpus version and re-labelling.

**Fix.**

- Lengthen the thin documents by about 40-60 words each, before the plan is executed. The best place is the `purpose`
  or `records` sections, so the labelled answer sections and the dev-query labels stay stable.
- Regenerate the lock and `RELEASES["corpus-1"]`, and update the plan's printed lock (3212-3238) and the hash
  mentions (249, 2751, 5833, 5979, 6156).
- Make the test count the words after the banner line, and say so in the R099 row and the test docstring.

#### Minor

##### M1. All-or-nothing holds only for the rules Python mirrors

**Lines:** 793, against 3019-3022; 737, against 3786-3790; 3795-3796; 3898-3902; 3886-3889.

`load` refuses an empty section body but not a body with zero `[a-z0-9]` words, such as a body of punctuation or
symbols only. The `chunks` CHECK `word_count >= 1` rejects that body in phase 2. Likewise, phase 1 never checks that
each tenant row exists, and the `corpus_ingestions` foreign key to `app.tenants` rejects it in phase 2. Either failure
happens after an earlier tenant (alpha, in sorted order) has committed. In those cases:

- the run is partly written, against ruling 6;
- a psycopg error escapes as a traceback;
- a phase-2 `IngestRefused` still prints "INGEST: refused, nothing written".

**Fix:**

- add `or section.words == 0` to `load`'s section rule;
- in phase 1, check `SELECT 1 FROM app.tenants WHERE tenant_id = %s` (the worker has SELECT);
- make the phase-2 message name the tenants already written.

##### M2. The "evidence_id ascending" tie-break depends on the collation

**Lines:** 874, 880, 562, 5437, 5877.

The test and dev databases use `en_US.utf8` (glibc), which ignores punctuation at the first level. Measured on the dev
server:

- the database default orders `'A:B' < 'A-B:v1:x' < 'AB:v1:x' < 'A-C:v1:x'`;
- `COLLATE "C"` orders `A-B… < A-C… < A:B < AB…`.

The live expectations are unaffected, because their IDs order the same either way. But the documented setting is not
what runs, and a glibc upgrade can reorder ties.

**Fix:** use `ORDER BY r.rank DESC, r.evidence_id COLLATE "C"` in both ORDER BYs, and update the unit assertion at 562.

##### M3. The `asset_type` input schema contradicts itself

**Lines:** 4509-4511.

The tool advertises `"asset_type": {"default": "", "minLength": 1, "maxLength": 40, "type": "string"}`. I saw this by
listing tools in the scratch tree. A schema-driven client may send its own default, which the server then rejects.

**Fix:** strip the default from the generated schema (pydantic `json_schema_extra`), and assert `"default" not in
asset_type` in `test_tool_schema_conforms…` (4709-4710).

##### M4. precision@5 is precision over the rows returned, not over k

**Lines:** 5569, 5655-5656, 5898.

The code computes `relevant / len(ids[:K])`, but the report and the docs call it precision@5.

**Fix:** divide by `K`, or name it "precision over the returned rows (at most 5)" in the report and in
`docs/retrieval.md`.

##### M5. R131's matrix note keeps a stale write half

**Lines:** 6062-6073.

Only the read-half sentence is replaced. The note still says "(no read function exists yet to refuse, erratum 91)",
although T17 adds one and Task 1 adds the 42501 call at mcp_exec (1631-1633).

**Fix:** replace that clause too; it is erratum 96's narrowing.

##### M6. The close-out commits even when the R033 evidence files are missing

**Lines:** 6568-6570, against 6034-6036.

The `if [ -d reports/retrieval ] … else echo …` branch is followed by the commit. `verify_handoff` does not check that
evidence paths exist: it exited 0 in the scratch tree without `reports/retrieval/`.

**Fix:** stop instead (`else echo …; exit 1; fi`).

##### M7. Departure 6's condition is not met in the test text

**Lines:** 2494, 2529-2537.

The R099 test docstring says "fewer than 14 documents, 7 per tenant". It never says that it counts catalog entries,
which are authored files or versions, rather than document IDs. The ruling on departure 6 required the test to state
which it counts.

##### M8. `migrate`'s docstring is stale

**Lines:** 653-666.

After Edit 3 the docstring still reads "Roles first, then both trees" (`scripts/skeleton.py:223` in the scratch tree),
so the comment no longer matches the code (CODE_COMMENTS rule 8).

**Fix:** "Roles, then the bootstrap extensions, then both trees".

##### M9. The next-step paragraph omits T19

**Lines:** 6262-6266.

T19 is PLANNED, with T07 and T17 DONE and T02, T03 and T44 DONE_PENDING_OWNER. Mention it beside T41 as waiting on
owner steps.

##### M10. The three live tests no longer pin rank 1 (optional)

**Lines:** 5030, 5091, 5136.

They now assert membership in a top-2 answer. In the emulation ANSWER is first by a wide margin, 2.9 against 0.7, so
`results[0] == ANSWER` would keep the stronger pin the retired tests had.

#### Checks that found nothing wrong

- **Departure 3 (OC005).** The vector refusal fits OC005's existing meaning. `persistence.Refused` is "a gate said no;
  `code` is the function's DETAIL", already used for `INVALID_ARGUMENT`, `SLOT_OCCUPIED` and the like.
  `translate` maps it to `Refused("VECTOR_MODE_UNAVAILABLE")`. mcp-read turns any `Refused` into the plain tool error
  `REFUSED`, with `retryable: false`, which `tool-result.schema.json` accepts (`code` is a free string of 1-80
  characters). It is never reached today: `persistence.search_procedures` hard-codes `'lexical'`, and the tool refuses
  `vector_exact` after resolution and before the search.
- **R131.** `mcp_read`'s equality becomes `{current_time, resolve_invocation, search_procedures_scoped}`.
  `mcp_exec`'s equality with `MCP_EXEC_FUNCTIONS` is unchanged, and the new function lands in its `others` set with an
  explicit 42501. `test_function_catalog_shape`, R124, R106, R084 and the owners test enumerate `privileges`, which
  now include the four tables and the function. Their expectations follow from the matrix rows.
- **Definer header and tenant setting.** The header and `search_path = app, pg_temp` match 0010. `public.vector(768)`
  is schema-qualified in the signature, and `DROP`/`REVOKE`/`GRANT` use `public.vector`. `app.tenant_id` is
  transaction-local before every corpus read, set by `_tenant_of_run` inside `_resolve_handle` and again explicitly.
  The function's `SET app.tenant_id = ''` restores the value on exit. The clock is read after the lease lock.
- **Grants.** They follow the brief exactly: `worker` INSERT and SELECT, `app_definer` SELECT, a REVOKE from the frozen
  seven grantees, nobody else, and `test_harness` untouched. The tables are under ENABLE + FORCE with
  `tenant_isolation` and owned by `migrator`.
- **Downgrade.** It drops exactly the function and the four tables, children first. Their policies, index and grants go
  with them, and the extension stays.
- **0007-0010 conventions.** The frozen-cell, caller and body pattern is followed, and the bind scan passes with
  `':' || 'v'`.
- **Extension bootstrap.** `ensure_extensions(superuser)` runs inside `migrate`, which both `skeleton.py migrate` and
  the e2e `migrated` fixture call. It is the same function, and `superuser.dbname` is `OPS_PG_DB`, which is `ops_test`
  in the live suite. `deploy/dev/postgres/init/01-init.sql` already creates the extension in `ops`. No other code
  path creates a database and upgrades past 0010.
- **Fixture replacement.** Each replaced fixture test is mapped to its replacement (4224-4233). `procedures.py`,
  `fixtures_dir` and `OPS_FIXTURES_DIR` are gone, with no remaining reader.
- **Corpus contents.**
  - Two tenants, six assets (three per tenant) and seven alerts with uuid5 IDs and revisions.
  - Per tenant: a superseded pair, an expired version, a revoked version, a draft and an injected version. Alpha holds
    the conflicting pair, 30 against 10 minutes.
  - Every document opens with a title, a blank line and the synthetic banner, the delivered fixtures' layout.
  - The injected text is plainly synthetic.
  - Document IDs are disjoint from the handoff fixtures.
  - The schema examples now cite the `ALPHA-INCIDENT:v2:review` section hash `62a90906…`, which equals
    `data/handoff-fixtures/meta.json`.
- **Development queries.** All 47 labels exist and are permitted for their tenant and asset type at the labelling
  instant (`test_every_label_is_a_permitted_section_of_its_tenant` passes).
- **Wilson interval.** The formula is correct (I checked 3/4 by hand: [0.3006, 0.9544]). Every proportion carries its
  `n`.
- **Holdout.** No holdout path is read or written.
- **Secrets.** No token or raw handle reaches a log, an assertion operand or the report. The awaited calls in the
  assertions are opaque to pytest's rewriting, and the unit-test handle is a fixed fake.
- **Debt lines and errata 93-102.** They cite the right spec text: SA:461, AM-20.2 SA:431 with BS:241, SA:510, R131
  with errata 72/91, BS:413, AM-20.4/SA:440, SA:348, BS:415, the fixtures README and R033. The exceptions are those
  noted in I1 and M5.
- **Next step.** It is correctly computed as T16, with T18 and T23 also ready.
- **docs/retrieval.md.** Its figures (69 sections, 45-97 words, median 69) match the corpus.

#### Artefacts (scratch only)

- `planl/critic1-tree`: the fully applied tree, with commits `ff2d1ac..0409878`.
- `planl/critic1/apply.py`, `t1.log`, `t2-6.log`: the applier and its logs.
- `planl/critic1/gen_sql.py`, `run2.sql`, `run2.out`, `run2.txt`, `thresh.py`: the read-only PL/pgSQL emulation and the
  threshold calculation.

## Controller rulings

### Plan L review, round 1 — controller rulings

Input: `round1-static.md` (REVISE: 0 Blocking, 3 Important, 10 Minor; every red/green step, dev count, mypy and
verify_handoff verified on a scratch tree; live unverified). The critic also ran 0011's function body read-only in
the dev server's `postgres` maintenance database; that is not authorised again — no plan writer or critic connects to
any database. The emulated ranks it measured (real body, real corpus text, PostgreSQL 17) are accepted as the input
for I1(b).

- **I1 — both (b) and (a).**
  (b) Adopt ruling 18's minimum rank: a row is returned only when `ts_rank_cd > 0.25` (the critic's emulation: hit@5
  27/27 kept, no-source empty 16/20). Put the value in one helper (e.g. `app._min_rank()` returning 0.25, the
  `_dispatch_seconds()` pattern, granted to nobody) used by the search; record it in `SETTINGS`/`docs/retrieval.md`
  as "chosen on the 47 development queries; the same queries measure it, so the baseline is a development figure,
  not a held-out one"; state that `ts_rank_cd` is unnormalised, so the threshold depends on query length (a known
  limitation, tuning → T18 with the comparison). Update the live tests and the report's expectations accordingly;
  Task 5 prints the measured figures and the live gate decides them.
  (a) R033 is recorded as met **subject to the owner's decision on erratum 102** (the residual "missing stays
  missing" cases move to T20's abstention rule) in every place Plan K used for R131: the tasks.json review note,
  SESSION_STATE "Next task" and the "Plan L executed" bullet, STATUS's "Evidenced" line, and the R033 matrix note,
  with the measured no-source-empty rate and its denominator.
- **I2 — (1) and a stricter rule for (2).**
  (1) `load` requires one linear chain per document: versions are positive integers compared **numerically** (never
  as text), consecutive from the lowest, and every version after the lowest names the immediately preceding one in
  `supersedes`; refusals added to `test_the_loader_refuses_a_broken_catalog` (no `supersedes`; skipped version;
  non-integer version).
  (2) Ruling 7 is amended: a version is **retired** once any later version of the same document that has left
  `draft` (its latest state is `approved`, `superseded` or `revoked`) has reached its `effective_from` at
  `app.current_time()`. A retired version is never returned, whatever its own state; revoking or expiring a
  successor therefore never brings a predecessor back (fail closed; re-publishing old text means a new version).
  A successor that is still `draft`, or not yet effective, retires nothing. The SQL, `returnable` (the oracle) and
  `docs/retrieval.md` state the same rule; add unit and live cases for the four shapes (a)-(d) the critic gives,
  each asserting the predecessor is absent. Keep the "ever" wording in STATUS/ARCHITECTURE only if it is true under
  this rule; otherwise state the rule. The dev-query labels (hand-authored forbidden IDs) remain the independent
  check; say so.
- **I3 — ACCEPTED.** The measure is the `[a-z0-9]+` word count of the document **after its title line and the
  banner line**; every document 300–900 by that measure, authored with a margin (≥ 320). Lengthen the thin ones in
  non-answer sections (`purpose`, `records` or similar) so the dev-query labels stay valid; regenerate the lock and
  `RELEASES["corpus-1"]`; update every printed hash; the R099 test and row say exactly what is counted.
- **M1 — ACCEPTED** (zero-word bodies refused in `load`; tenant rows checked in phase 1; a phase-2 refusal names the
  tenants already written and never prints "nothing written").
- **M2 — ACCEPTED** (`COLLATE "C"` in both ORDER BYs and the unit assertion; `docs/retrieval.md` says byte order).
- **M3 — ACCEPTED.** **M4 — ACCEPTED**: precision@5 divides by 5 (standard); the docs say so.
- **M5, M6, M7, M8, M9 — ACCEPTED.** **M10 — ACCEPTED** (pin rank 1 where the emulation shows a wide margin).

Apply in one pass; re-verify mechanically on a fresh `git archive` tree (task by task, `ruff format` between tasks,
every Expected line, dev counts, mypy, verify_handoff), update the live arithmetic, append "Round 1 changes" and
"Round 1 open points" to the plan, and commit only the plan: `docs: Plan L round 1 - <summary>`. No attribution
trailers. No database connections.

---

# Round 2

## Static review

### Plan L, round 2: adversarial static review (critic 2)

Plan: `docs/superpowers/plans/2026-10-16-first-slice-l-governed-corpus.md` at `fad2cc9` (7024 lines). Binding inputs:
`brief.md`, `writer-departures-rulings.md`, `round1-static.md`, `round1-rulings.md`; the fact sheet, `AGENTS.md`,
`docs/CODE_COMMENTS.md`, `SPEC_AMENDMENTS.md`. No database was connected to, in any way.

#### Verdict: REVISE

**1 Blocking, 2 Important, 3 Minor.**

The mechanics are clean. Applied task by task to a fresh `git archive` tree, every red step printed exactly its
`Expected:` line, and every green step passed. Every dev count matched, mypy found nothing new and `verify_handoff`
exited 0 after every task, Task 6 included.

What needs revising:

- **One live test fails.** The round-1 helper `app._min_rank()` was not added to the 0011 round-trip test's function
  set. That test fails, so Task 1 Step 5's `7 passed` and every live gate from Task 1 on cannot be met as written.
- **"A retired version never comes back" is not true.** Ingestion accepts two lifecycle restatements that bring a
  retired predecessor back. The SQL, the oracle and the docs agree with each other on this, so no check sees it.
- **The project history leaves out the review rounds.** The section the plan writes in `docs/PROJECT_HISTORY.md`
  skips them, which is the user's standing rule and the gap Plan K's own close-out review rated Important.

All round-1 rulings are otherwise applied correctly and completely (details under "Round-1 rulings").

#### Method

##### A. Mechanical

How the tree was built and run:

- **Tree.** `git archive HEAD | tar -x -C planl/critic2-tree`, then `git init` and a base commit `f2c9034`.
- **Applier.** `planl/critic2/apply.py`, critic 1's applier with two changes. Its `Edit` regex now accepts `Edit 3b`,
  `5b` and `8b`; critic 1's regex would have skipped those three edits silently. The base can also come from the
  environment for Task 6.
- **Each step.** The applier writes every `Create` and `Replace the whole of` block. It applies an `Edit` only on an
  exact single match. It runs every `git add`, `rm` and `commit`, every non-live `Run:` and every gate.
- **Formatting.** It runs `ruff format --check` and then `ruff format` before each gate.
- **Logs.** `planl/critic2/base.log`, `t1-5.log` and `t6.log`.

| Step (plan line) | Expected | Got |
|---|---|---|
| Base gate | 1161 / 182 | 1161 passed, 182 skipped, GREEN |
| T1 red (634) | 9 failed: 6 FileNotFoundError, 2 AttributeError, 1 DID NOT RAISE | identical |
| T1 green (1282) | 218 passed | 218 passed |
| T1 gate (1809) | 1173 / 188 | 1173 / 188, GREEN; verify 0 |
| T2 red (2901) | 1 error, ImportError `corpus` | identical |
| T2 lock (3459) | the two lines, lock `81f50c2b…` | identical; `corpus.sha256` byte-identical to 3471-3491 |
| T2 green (3495) | 25 passed | 25 passed |
| T2 gate (3597) | 1198 / 188 | 1198 / 188, GREEN; verify 0, corpus PASS line printed |
| T3 red (3778) | 1 error, ImportError `ingest` | identical |
| T3 green (4197) | 43 passed | 43 passed |
| T3 gate (4452) | 1207 / 190 | 1207 / 190, GREEN; verify 0 |
| T4 red (4647) | 6 failed, TypeError `corpora` | identical |
| T4 green (5163) | 246 passed | 246 passed |
| T4 build_schemas (5236) | the summary line; 33 changed examples | identical; 33 files, all `schemas/examples/` |
| T4 plan_c (5242) | 285 passed, 19 skipped | identical |
| T4 gate (5471) | 1211 / 190 | 1211 / 190, GREEN; verify 0 |
| T5 red (5675) / green (5983) | 1 error / 5 passed | identical |
| T5 gate (6218) | 1216 / 191 | 1216 / 191, GREEN; verify 0 |
| T6 records (6265) | span and figure; 3 handoff files | `f2c9034..10f44fe 15/20`; 3 files; 4 matrix rows |
| T6 git grep (6875) | both print nothing | nothing |
| T6 final gates (6884) | 1216 / 191; verify 0 | identical |

Notes on the mechanical run:

- **Task 6 needed a report.** Task 6's records script needs `reports/retrieval/t17-lexical-baseline.json`, which
  only the live test writes. I generated a **synthetic** report into the scratch tree only. It came from the Python
  emulation in B below, through the plan's own `retrieval_baseline.report` and `markdown` (`critic2/fake_report.py`),
  purely to exercise the pipeline.
- **The script works.** It wrote `15/20` into `tasks.json` and the R033 matrix note. It found and replaced both R131
  clauses exactly once, and kept the JSON formats.
- **Formatting and line length.** Every Edit matched once. `ruff format` changed no file at any gate. No changed
  Python file has a line over 120 characters.
- **mypy.** `mypy --strict` on `scripts/retrieval_baseline.py`, `scripts/gen_corpus_meta.py`,
  `ops_core/corpus.py` and `ops_core/ingest.py` reports only the pre-existing `scripts/gen_seed_ids.py:30`. The
  gate's own mypy over the member trees is GREEN.
- **Live tests: not run, so every live `Expected:` line is unverified.** That covers 1789 `7 passed`, 4437
  `2 passed`, 5453 `9 passed`, 6081 `1 passed` and every `--profile test` count. The live arithmetic is internally
  consistent: 167, 167, 169, 169 and 170 live-gated tests give 1340, 1365, 1376, 1380 and 1386. Finding B1 shows
  one of these live lines cannot hold.

##### B. Ranks without a database: reasoning plus a Python approximation

**The reasoning.** `ts_rank_cd` (tsrank.c, `calc_rank_cd`, default method 0) over an OR query works like this:

- `Cover()` closes a cover at the first position that satisfies the query.
- For an OR query that is a single position, so each matching position is its own cover.
- Its value is `1/(1/w) = w`, with no noise term.
- So a chunk's rank is the sum of the weights of its matching positions: a heading word (A) counts 1.0 and a body
  word (D) counts 0.1.

"Rank > 0.25" therefore means "a heading word of the query, or at least three body occurrences". The float4 sum of
three 0.1 values is 0.3000000045, safely above 0.25.

**The approximation.** `critic2/rank_emul.py` combines that rule with these pieces:

- Snowball english (Porter2), from `snowballstemmer` installed into `critic2/vendor` only;
- the snowball stop list;
- `simple` for tokens that contain digits;
- decimals kept as one token;
- the corpus loaded from the applied tree.

It is an approximation of PostgreSQL's parser and dictionaries, not a measurement. The corpus has no host, file or
email tokens; the only dotted tokens are `0.05` and `0.10`.

#### Round-1 rulings: verification

| Ruling | Applied? | Notes |
|---|---|---|
| I1(b) min rank | Yes, with one gap | See B1 below. |
| I1(a) R033 "subject to erratum 102" | Yes | `<empty>` = `k/n`: see M2. |
| I2.1 one chain | Yes | See detail below. |
| I2.2 retirement | Yes in the SQL and oracle; "never comes back" untrue | See I1 below. |
| I3 prose words | Yes | See detail below. |
| M1 | Yes | `load` refuses `section.words == 0` (3252); phase 1 checks `app.tenants`, which is in `NO_RLS` with worker SELECT (4049-4057); `IngestRefused.written`, and `ingest` prints "refused after writing …" (4169). |
| M2 | Yes | `COLLATE "C"` in both ORDER BYs (936, 942), the unit assertion (585-586) and the docs (6172). |
| M3 | Yes | `without_default`; `"default" not in asset_type` asserted and passing. |
| M4 | Yes | `relevant / K` (5861); the unit expects 0.1. |
| M5 | Yes | Both R131 clauses replaced, each asserted once; the script ran. |
| M6 | Yes | `exit 1` when `reports/retrieval` is missing (6909). |
| M7 | Yes | The docstring says it counts catalog entries (2668-2669). |
| M8 | Yes | The docstring names the extension step (688-690). |
| M9 | Yes | The next-step paragraph names T19 (6597-6598); `tasks.json` confirms T16, T18 and T23 are ready and T19 and T41 wait on owner steps. |
| M10 | Yes | rank 1 pinned at 5321, the t15 helper and the process test. The emulation's margin holds: 3.2 against 0.9 for the QUERY. |

**I1(b), the minimum rank.** What the plan does:

- `app._min_rank()` returns `real 0.25`.
- It uses `HELPER_HEADER`, which matches 0003, 0004 and 0010: plpgsql, no SECURITY DEFINER, `search_path` pinned.
- It is owned by `app_definer` and granted to nobody: `function_grant_statements` with `callers=()` gives a REVOKE
  from PUBLIC only.
- It is frozen in `FUNCTIONS` and dropped in `DOWNGRADE`.
- It is used once (`WHERE r.rank > app._min_rank()`). The body holds no "0.25", which the unit test asserts.
- It appears in `HELPER_FUNCTIONS`.
- `SETTINGS`, `docs/retrieval.md` and the debt line carry every caveat the ruling required.
- R106's `test_function_catalog_shape` accepts it: it is in `HELPER_FUNCTIONS`, its ACL holds only `app_definer` and
  `search_path` is pinned.

The gap is the live round-trip test (B1).

**I1(a), the R033 wording.** "Subject to erratum 102" appears in every place the R131 precedent used:

- the `tasks.json` note (6310-6312);
- SESSION_STATE "Next task" (6434-6436) and the "Plan L executed" bullet (6481);
- STATUS "Evidenced" (6621-6623);
- the R033 matrix note (6358-6360);
- the ARCHITECTURE R033 row (6703).

Each place carries `<empty>` = `k/n`. The pipeline works mechanically; see M2 for its loose ends.

**I2.1, one chain.** The checks are in place:

- `load` requires consecutive integers from the lowest version and `supersedes` naming the predecessor
  (3278-3293).
- There are three refusal cases: no link, a skipped version and `1a` (2869-2872).
- Every version comparison is numeric:
  - the SQL (`::integer`, safe under the `^[1-9][0-9]{0,8}$` CHECK);
  - `returnable`;
  - `load`'s chain sort and its `supersedes` check;
  - `plan`'s write order.

**I2.2, retirement.** The SQL (920-926), `returnable` (3311-3331) and `docs/retrieval.md` (6166) state the same
rule. There is a unit case for each of (a)-(d), plus draft, not-yet-effective, expired and "10" after "9". The live
cases (1588-1641) have the same shapes, with not-yet-effective covered by DOC-I at 1477-1491.

I checked every staged expectation against the rule; all hold:

- 1482 and 1490: the lifecycle cases;
- 1519-1526: the tenant and asset-type filters;
- 1633-1639: `DRAFT-NEXT` < `GAP` < `NO-LINK` < `NUMBERS` < `WRONG-LINK` in byte order.

The SQL and the oracle cannot disagree on an ingested store. After a successful run each stored version's latest
state equals the catalog's lifecycle, because every difference appends a row, a revoked version cannot change and a
dropped one is refused. The forbidden cases are covered in I1.

**I3, prose words.** Measured on the applied tree after title, blank and banner:

- 332-349 prose words per document;
- section bodies alone 327-343;
- 69 sections of 45-119 words, median 77, which matches `docs/retrieval.md` and erratum 100;
- every banner in place;
- the plan's vocabulary-separation claims (1872-1875) still hold after the lengthening, with no forbidden word in
  either tenant;
- "by the maintenance planner", which the R032 live test replaces, is still present;
- all 47 labels are permitted, a unit test.

The lock and `RELEASES` agree with the files. The checks are run at the following levels:

- the printed lock;
- `test_the_lock_is_the_released_one`;
- the `verify_handoff` PASS line.

The R099 requirements hold:

- 16 catalog entries of at least 320 words each, against the 12 required;
- 6 assets, 3 per tenant;
- 2 tenants, each with a superseded pair, an expired, a revoked, a draft and an injected version;
- the conflicting pair in alpha;
- the banner opening every document.

**Live expectations under 0.25.** These are reasoned, not run.

| Case (plan lines) | Rank reasoning | Result |
|---|---|---|
| Staged chunks, query `turbine` | heading `turbin` 1.0 + body 0.1 = 1.1 | All kept; ties broken in byte order. |
| Ties test, `turbine bearing` (1562) | TIE-A and TIE-B: `turbin`×2 + `bear` = 0.3; TIE-C: 0 | Only A and B. |
| Ties test, `turbine casing`, limit 1 (1564) | TIE-A and TIE-B 0.3 (`case` stems the same on both sides) | TIE-A first. |
| Ties test, `Turbine!!! casing??` (1573) | A and B 0.3; TIE-C 0.1, at or below 0.25 | TIE-C dropped. |
| Ties test, `the and of` | no lexeme | `[]`. |

For the live corpus queries every needed section carries a heading word of its query, so each clears 0.25 by about
1.0:

- the QUERY "repeated alerts on one asset" (`repeated-alerts`);
- "inspection interval and alerts" with `pump`;
- the R105 message (the emulation returns 5 sections, `repeated-alerts` 1.6);
- the R032 queries `repeated-alerts` and "vendor portal …" (`portal-note`, `vendor-contact`).

#### Blocking

##### B1. The 0011 round-trip live test fails: `_min_rank()` is in the head snapshot and not after the downgrade

**Plan lines:** 1681-1707 (`test_the_round_trip_restores_0010_and_keeps_the_extension`), in particular 1698. Also
860-868, 951-967 (`_min_rank` created and dropped), 1789 (`Expected: 7 passed`), and every live-gate count from
1812 on.

**Evidence.** `snapshot()` lists every function in schema `app` by `regprocedure`, so `head` contains both
`app.search_procedures_scoped(...)` and, since round 1, `app._min_rank()`. The downgrade drops both, as it must. Line
1698 then asserts:

```python
assert {s for s in head if not s.startswith("app.search_procedures_scoped(")} == set(after)
```

The left side still contains `app._min_rank()` and `after` does not, so this raises `AssertionError` on every run.
The consequences:

- Task 1 Step 5 gets `6 passed, 1 failed`, not `7 passed`.
- Every `check.py --profile test` gate from Task 1 to Task 6 is RED, not GREEN.

The plan's "No interim red across tasks" constraint (148) cannot be met. The round-1 fix (I1(b)) added the helper,
the downgrade line and the unit expectation, but did not touch this live assertion.

**Fix.** Treat both functions as 0011's:

```python
OWN = ("app.search_procedures_scoped(", "app._min_rank(")
assert all(any(s.startswith(p) for s in head) for p in OWN) and all((await relations(app_conn)).values())
...
assert not any(s.startswith(OWN) for s in after)
assert {s for s in head if not s.startswith(OWN)} == set(after)
```

Better still, derive `OWN` from `revision().FUNCTIONS`, as `test_migration_0010_live.py` does with
`module.FUNCTIONS`, so a later helper cannot repeat this. Update the docstring's "a downgrade that leaves … the
function behind" to say "the functions".

#### Important

##### I1. "A retired version never comes back" is not true: ingestion lets a successor go back to `draft`, or move its `effective_from` later, and the predecessor is returned again

**Plan lines:**

- The claims:
  - ruling 7 (206-210): "whatever happens to that successor afterwards";
  - 0011's comment (920-921);
  - erratum 94 (284-285 and 6499-6501): "final";
  - the R032 matrix note (6338-6340);
  - `docs/retrieval.md` (6166): "A retired version never comes back";
  - the `tasks.json` note (6292): "retires every earlier one for good";
  - STATUS (6625): "a retired version never comes back";
  - ARCHITECTURE §9 (6686): "retires every earlier one for good";
  - Round 1 changes (6995): "and never comes back".
- The cause: `ingest.plan` (3915-3920) and the ingestion table in `docs/retrieval.md` (6145-6151).

**Evidence.** The retirement test reads only each later version's latest state: `n.status <> 'draft' AND
n.effective_from <= v_now` over `latest` (923-925). `returnable` reads the same from the catalog (3326-3329).
Meanwhile `plan` accepts any lifecycle change of a stored version that is not revoked, as one more state row (3917-3920):
a status back to `draft`, or another `effective_from`.

A concrete case: a later corpus version sets `ALPHA-PUMP-SEAL` v2 to `"status": "draft"`, perhaps pulled back for
rework, or moves v2's `effective_from` to 2027-01-01.

1. Ingestion appends one state row, by design.
2. v2 no longer "has left draft and reached its effective_from".
3. v1, whose own catalog status is still `approved` and which is effective since 2026-08-01, is not retired, and
   `search_procedures_scoped` returns it again.

That is exactly the superseded 30-day interval text that dev query A09 labels as forbidden. The oracle agrees with the
SQL, so the baseline's hard zero cannot see it. The fixed dev labels cover only corpus-1.

The round-1 ruling allowed the "ever" wording in STATUS and ARCHITECTURE "only if it is true under this rule;
otherwise state the rule". Under the rule as implemented (latest state), it is not true. Revoking or expiring a
successor is safe. Taking it back to draft, or postponing it, is not.

**Fix.** Preferred (fail closed, keeps SQL = oracle = docs): in `ingest.plan`, refuse the whole run when either
happens:

- a stored version whose status is not `draft` would be restated to `draft`;
- a stored version whose status is not `draft` would get a different `effective_from` ("a version that has left draft
  keeps its effective_from; publish a new version instead").

Then:

- add both cases to `test_ingest_plan.py`;
- add one row to the `docs/retrieval.md` ingestion table;
- add one clause each to erratum 94 and the R032 note.

With that, and with the clock moving forward only (the test clock aside), "never comes back" is true.

The alternative is to keep the behaviour and replace every "never comes back", "for good", "whatever happens" and
"final" wording with the precise statement: "revoking or expiring a successor never brings a predecessor back".

##### I2. The plan's PROJECT_HISTORY section leaves out the review rounds (the user's standing rule; Plan K's close-out was rated Important for exactly this)

**Plan lines:** 6711-6739 (Edit 5, §29: Problem, Change, Review). The Review paragraph covers only writing-time
departures and the missing database.

**Evidence.** The user's standing instruction (`docs/CODE_COMMENTS.md` practice and the project memory) is that every
review round's findings and fixes are appended to `docs/PROJECT_HISTORY.md`. Plan K's §28 records "The plan then went
through two static reviews …" with each round's Problem and Change. Its Task 6 review found "one Important gap, this
section: it recorded only the plan's first review round, though every round's problems and fixes belong here".

Plan L's §29 records none of these:

- round 1's REVISE (R033's second clause unmet, two versions returned at once, R099 words counted with the banner);
- the fixes (the minimum rank and erratum 102, one chain and retirement, the prose word count);
- this round.

As written, the close-out commits a history without them, and execution would then need a fix round of its own.

**Fix.** Extend Edit 5's text with a "Problem / Change" pair for round 1 (from "Round 1 changes" at 6977-7013). Add one
for round 2 once it is ruled. Add an instruction in Task 6 to append the execution-time task and final reviews in the
same form, as §28 does.

#### Minor

##### M1. The frozen revision comment and ruling 18 cite emulation figures from text that is no longer corpus-1, and the lengthened `records` sections now compete with answers

**Plan lines:**

- 856-859: 0011's frozen comment, "an emulation of this body on corpus-1 kept every labelled answer in the top 5 and
  answered 16 of the 20";
- 245-248: ruling 18;
- 7017-7020: the open point, which does acknowledge the risk.

**Evidence.** Round 1's emulation ran on the pre-round-1 corpus, lock `0f5c6ee1…`, whose files have since changed. A
comment in a frozen revision that states a measured fact about "corpus-1" which was not measured on corpus-1
conflicts with CODE_COMMENTS rules 6 and 8.

My approximation on the final text (method B; it is approximate, not PostgreSQL) gives:

- hit@5 27/27 and every-expected@5 27/27;
- no-source answered empty **15/20**;
- answered no-source cases A15, B10, B13, B17 and B18.

It also shows where the I3 lengthening landed:

- **The `records` heading.** It matches any question that contains "record". A15 (draft-only, "Record decibel
  readings…") is answered by four `records` sections of other documents, each at about 1.0 or more.
- **B02's answer.** It falls to rank 5 behind three `records` sections, beating `purpose` by only 0.1. Its query is
  "What must the record show before an alignment…", and the expected section is `preparation`.

These are measurements for T18, not defects. But corpus-1 is frozen at execution, so this is the last cheap moment to
decide.

**Fix:**

- Remove the numbers from the frozen comment ("chosen on the development queries; see docs/retrieval.md"), or qualify
  them as "on the round-1 draft of the corpus".
- In ruling 18, say "on the round-1 draft".
- Optionally note the `records`-heading effect in the open points.

##### M2. The `<empty>` pipeline can embed a stale figure, and the commit does not enforce the placeholder check

**Plan lines:** 6250-6255, 6275-6277, 6409-6412, 6892-6894, 6902-6910.

**Evidence.**

- **The figure is not tied to the current corpus.** The records script reads whatever
  `reports/retrieval/t17-lexical-baseline.json` exists. It never checks that file's `corpus_version` or `lock_sha256`
  against `corpus-1` or `RELEASES`, nor that the report is the latest run. `reports/retrieval/` is excluded from every
  gate's `git checkout`, so a report left by an earlier attempt survives. Step 4's final live gate then rewrites the
  committed report after Step 1 has already embedded its figure in `tasks.json` and the matrix. Nothing compares the
  two. They agree only because the search is deterministic.
- **The placeholder check is prose only.** The "`git grep … <empty>` prints nothing" check is an instruction in prose.
  Step 5's commit block does not run it. My scratch commit went through with `<base>`, `<last>`, `<date>` and
  `<empty>` still in SESSION_STATE (nine lines) and STATUS (three lines), because the applier does not do the manual
  replacement, which shows nothing stops it.

**Fix:**

- In the records script, add `assert report["corpus_version"] == "corpus-1" and report["lock_sha256"] ==
  "81f50c2b…"`.
- In Step 5's bash block, before `git commit`, add `if git grep -q "<base>\|<last>\|<date>\|<empty>" --
  SESSION_STATE.md STATUS.md; then echo "placeholders left"; exit 1; fi` (M6's pattern).
- Optionally, after Step 4, re-read the rewritten report and assert the same `k/n`.

##### M3. The applier-visible directive spelling `Edit 3b`, `5b` and `8b`

**Plan lines:** 693, 1076, 4765.

**Evidence.** These are the only edits whose label is not a plain number, and all three are round-1 additions.
Critic 1's applier (`Edit (\d+) \(`) would have skipped them silently and still reported success up to the first
test that needs them. An executor reading "Edit 3 … Edit 3b … Edit 4" will not miss them. This is a robustness note
for anyone tooling the plan, not a defect.

**Fix:** none required. Optionally renumber them so that each task's edits run 1..n.

#### Not found / checked and fine

- **Departures 1-7 and their controller rulings** are intact.
- **`_resolve_handle`** is called in the established `SELECT * INTO v_handle` pattern.
- **Constraints Python mirrors.** Python mirrors every CHECK of the corpus tables, so phase 2 cannot hit one that
  phase 1 missed:
  - the identifier, path and version regexes;
  - offsets equal to `char_length` (code points);
  - the section and evidence lengths;
  - a word count of at least 1;
  - the interval.
- **Foreign-key checks.** The ones the worker's inserts trigger run as the owner without FORCE RLS, the same pattern
  as the existing tables.
- **No other live test is affected.** No other live test downgrades through 0011 and compares a full function set.
  The 0006-0010 round trips compare named functions or `snapshot == head` after re-migrating, which still holds. No
  scratch database is upgraded past 0010, so `REQUIRE_VECTOR` cannot trip one.
- **Other live tests that touch retrieval** script their search (`ScriptedMcp`, `test_worker_live`) or use the
  seeded, ingested tenants. No live test asserts `handoff-1` or `ALPHA-INCIDENT` against the real mcp-read.
- **The worker's search** uses limit 3, as `docs/retrieval.md` says.
- **`stamp`** normalises the definer's `effective_from` to UTC.
- **The `ingested` fixture.** The `tenants` table has no RLS and the worker may SELECT it, so phase 1's tenant check
  works.
- **The Task 6 records script** asserts T17 `PLANNED` with no `review_notes`, which holds today. Both R131 strings
  occur exactly once; I ran the script.

#### Artefacts (scratch only)

- `planl/critic2-tree`: the fully applied tree, commits `f2c9034..3109e28`. Its Task 6 commit contains the synthetic
  report and the unreplaced placeholders.
- `planl/critic2/apply.py`, `base.log`, `t1-5.log`, `t6.log`: the applier and its logs.
- `planl/critic2/rank_emul.py`, `b02.py`, `fake_report.py`, `dump.json`, `vendor/`: the Python rank approximation
  and the synthetic report generator.
- `planl/critic2/corpus_check.py`, `count.py`, `next.py`: the word, vocabulary, line-length and next-task checks.

## Controller rulings

### Plan L review, round 2 — controller rulings

Input: `round2-static.md` (REVISE: 1 Blocking, 2 Important, 3 Minor; mechanical re-check clean; live unverified).

- **B1 — ACCEPTED.** The round-trip test's head snapshot excludes every object 0011 creates (`search_procedures_scoped`
  and `_min_rank`, and any other function, table, index or type 0011 adds) — derive the exclusion from the revision's
  own frozen lists rather than naming functions by hand, so a future addition cannot repeat this. Re-check every
  other live test that enumerates functions (`test_transitions_table`, the R131 ACL tests, the `mcp_exec`
  "every other app function" set) for `_min_rank`: granted to nobody, present in the helper list.
- **I1 — ACCEPTED, the refusal.** `ingest.plan` refuses (conflict, whole run, nothing written) a version that has left
  `draft` being restated to `draft`, and any change to `effective_from` once a version has left `draft` (it becomes
  an immutable attribute from that point). Allowed lifecycle changes stay: `approved → superseded/revoked`,
  `superseded → revoked`, setting or shortening `effective_to`. Unit cases for each refusal and a live case showing
  ALPHA-PUMP-SEAL v1 stays absent. The "a retired version never comes back" wording is then true; keep it, citing
  the refusals.
- **I2 — ACCEPTED.** Task 6's PROJECT_HISTORY section records, per round, the problems found and what changed: plan
  rounds 1 and 2 (this file's findings included), and placeholders the controller fills for the task reviews and the
  final review. It follows the existing sections' style (portfolio readers).
- **Minor 1 — ACCEPTED.** No measured figure in the frozen 0011 comment or in ruling 18: say "chosen on the 47
  development queries (emulated on the draft text); Task 5's live report is the measurement". B02 at rank 5 is fine
  (within k); note it in the open points.
- **Minor 2 — ACCEPTED.** Task 6 reads the report's `corpus_version` and lock hash and stops unless they are
  `corpus-1` and `RELEASES["corpus-1"]`; the placeholder grep runs before the commit and stops (`exit 1`) on any
  `<empty>` or other placeholder left.
- **Minor 3 — ACCEPTED.** Every edit label is unique and follows the plan's existing labelling scheme.

Apply in one pass; re-verify mechanically on a fresh tree; append "Round 2 changes" / "Round 2 open points"; commit
only the plan: `docs: Plan L round 2 - <summary>`. No attribution trailers. No database connections.

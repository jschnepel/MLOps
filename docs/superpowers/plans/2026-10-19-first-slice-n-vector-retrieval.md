# First Slice N: Exact Vector Retrieval and the Comparison (T18) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build T18: exact pgvector search beside the lexical baseline, measured against it, without moving the
lexical path, the corpus, the evidence IDs, the tool schemas or the worker. `nomic-embed-text` is pinned
(`data/embedding-pins.json`), every stored chunk is embedded from its `search_document:`-prefixed text by an operator
command (`scripts/skeleton.py embed`, as `worker`), `search_procedures_scoped` gains an exact cosine branch under the
lexical branch's own filter text, mcp-read answers `vector_exact` by computing the `search_query:` embedding itself,
and `reports/retrieval-comparison.md` / `.json` compare both modes on the 47 development queries (R034, DoD 1); the
prefixes are asserted by unit and live tests (DoD 2).

**Architecture:** Revision `0013_embeddings` creates `app.embeddings` (one row per chunk, keyed and referenced like the
chunk, with model, digest, dimension, the SHA-256 of the exact text embedded and a `public.vector(768)`; AM-20.2's
corpus cells: `worker` INSERT+SELECT, `app_definer` SELECT; ENABLE+FORCE RLS; no vector index), the helper
`app._min_similarity()` (0.68, chosen by a rule fixed before measuring) and re-creates `search_procedures_scoped` from
0012's own body with three textual changes (a declared flag; the argument rule that admits `mode='vector'` with one
768-dimension non-zero embedding and refuses an embedding in lexical mode, replacing the `VECTOR_MODE_UNAVAILABLE`
refusal; and a vector branch before the stop-word return that repeats the `latest`/`effective`/`permitted` text byte
for byte, ranks every permitted chunk by `1 - (embedding <=> query)`, keeps similarities above the helper, breaks ties
by `evidence_id COLLATE "C"`, answers the lexical branch's own result keys and refuses `EMBEDDINGS_INCOMPLETE` when a
permitted chunk has no embedding). The return type is unchanged, so CREATE OR REPLACE keeps the grant; the downgrade
restores 0012's body exactly. `ops_core.embeddings` holds the prefixes, the text builders, the `Embedder` protocol
and the Ollama client (`httpx2`, 10 s, no retry, `/api/tags` and `/api/embed` only); `ops_core.embed` is the operator
step; `ops_core.model_pins.load_embedding_pins` reads the pin. mcp-read checks a new startup marker (`VECTOR_SEARCH`)
and, for `vector_exact`, after the handle, the scope and the asset type, verifies the pin against `/api/tags`, embeds
the query and calls the definer with `mode='vector'`; `search_response` reports the mode that ran. The comparison is a
live test on T17's harness with `scripts/retrieval_comparison.py`'s pure functions.

**Tech Stack:** as Plan M: PostgreSQL 17 with pgvector 0.8.7 (`pgvector/pgvector:pg17`, docs/runbooks/dev-topology.md:7),
psycopg 3.3, Alembic, `mcp` 2.3.0, Starlette, `httpx2`, Python 3.13, pytest and pytest-asyncio; local Ollama 0.40.4 on
loopback with `nomic-embed-text:latest` (digest `0a109f42…e59f`, 768 dimensions, measured 2026-10-19). No new
dependency: no `pgvector` package and no `numpy` (ruling 17); `uv.lock` does not change.

**Spec:** `SPEC_AMENDMENTS.md` (OPS-BUILD-1.3.6) over `BUILD_SPEC.md`: AM-15 (SA:348), AM-20.2 (SA:431, SA:437),
AM-20.3 (SA:446, SA:461, SA:474), AM-20.5 (SA:510-516), AM-30 (SA:584, SA:587), AM-31 (SA:595-602), AM-50 (SA:645,
SA:657-669); BUILD_SPEC BS:50, BS:54, BS:71, BS:144, BS:242, BS:415-417, BS:572, BS:611, BS:646, BS:670. Inputs: the
fact sheet `docs/superpowers/research/2026-10-19-plan-n-inputs.md` ("FS §n", "FS Qn") and the controller's brief of 18
rulings ("ruling n"). Earlier artefacts this plan builds on: revisions 0011 and 0012 (the frozen-body and `changed()`
pattern), `ops_core.persistence`, `privileges`, `locking`, `ingest`, `corpus`, `model_pins`, `settings`; mcp-read as
Plan M left it (its asset-sim client is the template of the Ollama client); `scripts/retrieval_baseline.py` and
`tests/e2e/test_retrieval_baseline_live.py` (T17's harness); the `tests/e2e/` fixtures and helpers (`ingested`,
`new_run`, `lease_for`, `investigate_job`, `read_handle`, `refused`, `stage`, `handle_for`, `cleanup`, `purge_run`).

## Departures from the brief

Each place where this plan does something other than, or more than, a ruling says, with the reason and the citation.
Nothing else departs.

1. **`embed` refuses the whole run, not only the mixed tenant (ruling 2).** A tenant holding an embedding of another
   digest than the pin stops the run before anything is written for any tenant, as ingestion validates the whole
   catalog before writing (`core/src/ops_core/ingest.py:5-7`); writing the other tenants would leave the store half
   re-embedded with no way to tell which model a tenant's answers came from. A model or transport failure after an
   earlier tenant committed leaves that tenant written (each tenant is one transaction, as ruling 2 says); the command
   says which failure stopped it, and a re-run embeds only what is missing.
2. **The vector argument rule also refuses a zero vector, and the client refuses an all-zero answer (rulings 4 and
   5).** pgvector's cosine distance of a zero vector is NaN, and PostgreSQL orders NaN above every number, so a zero
   query vector would put every permitted chunk above any threshold. `public.vector_norm(p_query_embedding) = 0` is one
   more `BAD_ARGUMENT` cause, and `embeddings.checked` treats an all-zero vector as `Malformed`.
3. **The completeness check is a LEFT JOIN in the ranking statement itself (ruling 5).** The vector branch joins
   `app.embeddings e USING (tenant_id, evidence_id)` as a LEFT JOIN inside its `scored` CTE, so the ranking and
   `EMBEDDINGS_INCOMPLETE` read one snapshot in one statement; an inner join would need the three filter CTEs a third
   time for the check. The check covers the call's permitted set (the same `permitted` CTE, the asset filter included):
   a chunk the call could not return cannot be omitted from it.
4. **`_min_similarity()` returns `double precision`, not `real` like `_min_rank()` (ruling 6).** pgvector's `<=>`
   returns `double precision`; a `real` 0.68 is 0.680000007, so the boundary the report states and the one the
   definer applies would differ in the eighth decimal. Otherwise it is `_min_rank`'s twin (IMMUTABLE, owner
   `app_definer`, granted to nobody, in `HELPER_FUNCTIONS`).
5. **The lexical answers are compared with a pinned digest of the committed T17 answers, not with the file read at run
   time (ruling 11).** `tests/e2e/test_retrieval_baseline_live.py:108-110` rewrites
   `reports/retrieval/t17-lexical-baseline.json` on every live run, and it runs before the comparison in the same
   session (`baseline` sorts before `comparison`), so reading the file would compare the lexical path with itself.
   `scripts/retrieval_comparison.T17_ANSWERS_SHA256` (`7a059a19…04a3`) is the SHA-256 of the committed file's
   per-case answers, computed on 2026-10-19 from `753fa6f`'s file; a unit test pins the committed file to it (dev
   gate) and the live test pins the re-measured answers to it.
6. **The threshold sweeps run in Python over stored or recorded values (rulings 6 and 9).** The definer returns only
   similarities above its frozen threshold and only ranks above 0.25, so the vector sweep (and the live confirmation
   of the rule) is computed from the stored vectors read back as the superuser, and the lexical sweep from the recorded
   per-case ranks; the lexical grid therefore starts at 0.25 (0.25 to 1.00 in steps of 0.05), the only values those
   ranks can measure (`0011_governed_corpus.py:225`).
7. **`data/embedding-pins.json` is validated by a unit test, and its schema is generated (ruling 3).**
   `scripts/verify_handoff.py --contracts` validates `schemas/examples/` only, never a data file, so
   `tests/plan_n/test_embedding_pins.py` validates the committed pin against the schema and the loader. Every file
   under `schemas/` must come from `scripts/build_schemas.py` (`tests/plan_c/test_schemas_generated.py`), so the
   schema is a generator function with one valid and one invalid example, and `EmbeddingPins` joins
   `tests/plan_c/test_schema_conformance.py`'s `MODELS`.
8. **`settings.Urls.ollama` is a required field (ruling 4).** The two tests that build `Urls(...)` by hand
   (`tests/plan_j/test_verifier_t15.py:24`, `tests/plan_k/test_verifier_t47.py:25`) gain the argument, as they gained
   `asset_sim` in Plan M.
9. **One 10-second budget covers mcp-read's pin check and the query embedding together (ruling 4).** `server.py` has
   no tool time budget; the only bound above it is the worker's 60-second read timeout
   (`worker/src/ops_worker/mcp.py:137`) and the handle's 60 seconds. Two 10-second requests in a row would let a
   vector search spend 30 seconds outside the database (asset-sim's 10 included); one shared budget keeps it at 20.
   The CLI's requests have 10 seconds each.
10. **`TODO(T18)` stays in revision 0011's frozen body (ruling 1).** `0011_governed_corpus.py:178` is an applied
    revision and never changes (finding N1), and 0013 quotes that text as the `old` of one change; the function the
    database runs after 0013 no longer carries it. Every live `TODO(T18)` (`server.py`, `routing.py`,
    `scripts/build_schemas.py`) is resolved.
11. **The worker's mode choice is marked `TODO(T25)` (ruling 16).** The brief re-homes mode selection to "T20/T25";
    the code marker needs one task, and SA:660's condition that B and C use identical retrieval settings is T25's, so
    `routing.py` names T25 and the debt line names both.

## Global Constraints

Carried from Plan M's header (its text applies with "Plan M"/"T16" read as the plan that wrote it); the Plan N
additions below win where the two differ:

- **Debt before code (SA:698).** The Plan N debt list (below) is committed in Task 1 Step 1c before any code changes.
  Nothing not on the list may be shortcut; every line names its owning task.
- **Authority boundaries stay where the spec puts them.** `mcp_read` holds no table grant and EXECUTE on exactly
  `current_time`, `resolve_invocation`, `search_procedures_scoped` and `asset_scope` (unchanged); the tenant comes from
  the handle, never an argument (BS:362); definers per SA:446. `app.embeddings` is written only by `worker` (the
  operator command) and read only by `app_definer`. **Nothing here sends anything to an external system or a
  person** (BS:730): Ollama is local and loopback, asked only `/api/version`, `/api/tags` and `/api/embed` with the
  embedding model (never pull, delete or generate), and nothing here writes the dev databases.
- **Synthetic only.** corpus-1's files are read, never changed (`ops_core.corpus.RELEASES` stays one entry); the 47
  development queries are not changed or extended (`queries_sha256` stays `d6d539bd…6938`); the holdout is never read.
- **Secrets** live only as files under `OPS_SECRETS_DIR`; no secret, token or raw handle in an environment variable,
  a command line, a log line, an exception message, an assertion operand, an evidence file or a document. Error
  messages name rules, never values or addresses.
- **Clock.** The embedding step never consults the clock; the definer reads `app.current_time()` after the lease lock;
  a test that moves `app.test_clock` resets it in `finally`.
- **One string per SQL statement**, no SQLAlchemy bind in any `op.execute` string (`tests/plan_e/test_transitions_table.py`
  scans every revision, 0013 included); revision 0013 freezes its cells, callers, signatures and bodies, and its
  downgrade restores 0012's body from 0012's own module.
- **Live tests never touch the dev databases**: they run against `ops_test`/`incident_test` under `PROFILE=test`
  and local Ollama on loopback, through the `migrated`, `app_conn`, `role_conn`, `ingested`, (new) `embedded` and
  `asset_sim` fixtures; every random tenant a test creates is purged with its corpus and embeddings (`cleanup`).
- **Tests:** unit tests in `tests/plan_n/` (no database, no Ollama: a fake transport and a deterministic fake embedder;
  added to `testpaths` in Task 1), live tests in `tests/e2e/` gated by `OPS_LIVE=1`. Tests that pinned the vector
  refusal are rewritten in the task that changes the behaviour, each named. No xfail or skip except the live gate.
- **Comments** per `docs/CODE_COMMENTS.md`; ≤120 characters per line; no `type: ignore`; no `noqa`; ruff + mypy strict
  clean; UTF-8 without BOM, LF.
- **Gates:** `uv run ruff format <files> && uv run ruff check --fix <files>`, `PYTHONUTF8=1 uv run python
  scripts/check.py` GREEN after every task, `uv run python -I scripts/verify_handoff.py --reference-code --manifest
  --contracts` exit 0 after every task, and the live suite `PYTHONUTF8=1 uv run python scripts/check.py --profile
  test` after every task, with the dev stack up, local Ollama answering on 127.0.0.1:11434 and `uv run python
  scripts/skeleton.py status` showing every process down. After a live run: `git checkout -- reports/bootstrap
  reports/skeleton reports/auth reports/admission reports/leases reports/events reports/outbox reports/mcp-read
  reports/mcp-write reports/asset-sim reports/retrieval`; `reports/retrieval-comparison.md` and `.json` are new and
  stay untracked until Task 8 commits them. If mypy reports errors in modules this plan did not touch, rerun it with
  `--no-incremental` before treating one as real.
- **Toolchain:** everything through the locked environment from the repository root (`uv run python -m pytest …`,
  `uv run python scripts/…`, `uv run python -m scripts.…`); `uv.lock` never changes. Never start an interactive
  interpreter, never feed a script to an interpreter on standard input (`python -`), never end a process by image
  name.
- **Never migrate or embed the dev databases.** Nobody runs `scripts/skeleton.py migrate`, `ingest`, `embed` or `up`
  against `ops`/`incident` in this plan; migrating the dev database to 0013 and running `embed` there are owner inputs
  recorded in Task 8; until the migration mcp-read refuses to start on it, and until `embed` vector mode answers
  `REFUSED`/`EMBEDDINGS_INCOMPLETE` while lexical works.
- **Commits:** one logical group per step that says "commit"; messages free of any attribution trailer (owner
  instruction); never push; never `docker compose down -v`; never change system settings.
- **No interim red across tasks.** Every task ends with both gates GREEN at the stated counts: the pin before
  anything reads it, and the client before anything embeds (Task 1); the rule's measurement before the revision
  freezes its value (Tasks 2, 3); the revision, its matrix rows, its marker and its first reader together (Task 3); the
  stored embeddings before anything searches them live (Task 4); mcp-read's vector mode (Task 5); the comparison
  (Task 6).
- **Line numbers** in "Modify" lines are those of the file as the previous task left it. Every replacement quotes the
  exact current text ("Edit n (`path`), replace:" then "with:"); a step that creates a file gives the whole file.
- **Counts.** Today (`6d00d06`) the dev gate is `1372 passed, 205 skipped` and the live gate `1556 passed, 21 skipped`
  (184 live-gated tests). Task 1 Step 1a records both before any change; if either differs, every expected count
  below shifts by the same difference. The plan's code was applied to a scratch copy of `6d00d06` (`git archive`) and
  every dev count below was measured there with the repository's locked environment, the scratch sources first on
  `sys.path` (13 tests that need a git checkout, `tests/plan_a/test_verify_handoff.py` and
  `tests/plan_b/test_text_hygiene.py`, fail in a scratch copy and pass in the repository; the counts are the
  repository's); ruff, ruff format and mypy strict were clean there, `verify_handoff.py --contracts` passed, and the
  Task 2 measurement ran against local Ollama. Every live count is arithmetic (the dev count plus the live-gated
  tests: the dev run's skips minus the 21 that skip in both gates): no SQL of this plan and no live test has run
  against a database before execution. Review Focus names what to watch.

## Rulings (the brief's 18, as this plan implements them)

The controller's brief decided these; executors do not re-litigate them. The departures above are the only places
where the plan does something else.

1. **Storage** — `app.embeddings` in `0013_embeddings` with the brief's columns, PK and FK, cells, RLS and no index;
   `privileges.GRANTS`/`RLS_TABLES`/`HELPER_FUNCTIONS`, `REVISIONS`, the lock-order guard and
   `test_migration_0008_live.py`'s scan include it; `search_procedures_scoped` re-created by three `changed()` edits of
   0012's body with CREATE OR REPLACE (the ACL is kept: Review Focus 2); exact downgrade; marker `VECTOR_SEARCH`, with
   `GOVERNED_CORPUS` and `SEARCH_INSTANT` kept (Task 3).
2. **Who writes** — `scripts/skeleton.py embed` as `worker` through `ops_core.embed.embed`: pin verified before any
   write, every stored chunk without an embedding, batches of 16, 768 finite floats checked, a mixed store refused
   (departure 1), one transaction per tenant, a repeat prints `EMBED: <tenant>: 0 new, n present`; the text is
   `search_document: ` + section + `\n\n` + body; `ingest` unchanged; the live `embedded` fixture (Task 4).
3. **Pins** — `data/embedding-pins.json`, `schemas/embedding-pins.schema.json`, `model_pins.load_embedding_pins`,
   `scripts/pin_embedding_model.py` (`/api/version`, `/api/tags`, one `/api/embed`); verified by `embed` and by
   mcp-read on every vector call; mismatch or missing pin: `embed` exits 1, mcp-read `UNSUPPORTED_MODE` (Tasks 1, 4,
   5). Erratum 107.
4. **The query embedding** — mcp-read computes it (SA:348) through `ops_core.embeddings` (`OPS_OLLAMA_URL`,
   `settings.Urls.ollama`), after the handle, the scope and the asset type, before unit 3; `UNAVAILABLE` retryable,
   `UPSTREAM_INVALID`, `UNSUPPORTED_MODE`; an invalid handle never reaches Ollama; not a `model_permit` holder (Tasks 1
   and 5). Erratum 108 in `docs/ARCHITECTURE.md` and a dated note under ADR-0001 (Task 7).
5. **Same filters** — the vector branch repeats the three CTEs byte for byte (sliced from 0012's body, and a unit test
   compares the two branches); `p_mode IN ('lexical', 'vector')`, `p_query` bounded in both, vector needs one
   768-dimension embedding, lexical none, else `BAD_ARGUMENT`; `VECTOR_MODE_UNAVAILABLE` removed; stop-word return
   lexical only; the same answer keys; `EMBEDDINGS_INCOMPLETE` (departure 3); `[]` on an empty corpus (Task 3).
   Erratum 110.
6. **Score** — cosine distance, `rank` = cosine similarity, `similarity > app._min_similarity()`, tie-break
   `evidence_id COLLATE "C"`; the value 0.68 by the fixed rule, measured in Task 2 before 0013 is frozen and confirmed
   by the live comparison (departures 4 and 6). Erratum 111.
7. **Exact** — no index; `tests/e2e/test_vector_retrieval_live.py` compares the definer's ordered IDs with a Python
   brute-force ranking of the stored vectors for all 47 development queries (Task 4); "index version" recorded as
   model + digest + dimension + prefix + window, "no index" (Tasks 6 and 7).
8. **Another window** — an experiment in the report only: adjacent sections of one version until ≥300 words, the
   remainder joining the last window (`retrieval_comparison.windows`, Tasks 2 and 6).
9. **Lexical minimum rank** — measured (the sweep), unchanged at 0.25; the lexical body byte-identical (Tasks 2, 3, 6).
10. **Numeric tokens** — re-homed to T23 (debt list).
11. **The report** — `reports/retrieval-comparison.md` + `.json` by `tests/e2e/test_retrieval_comparison_live.py`
    on T17's harness; lexical re-measured and pinned (departure 5); k = 5 and 3; Wilson CIs and denominators;
    per-category rows; improvements and regressions by id; exact McNemar on hit@5 and on none-answered-empty with
    SA:667's rule; zero forbidden rows asserted in both modes; the sweeps, the window experiment, the repeat check and
    the settings (Tasks 2 and 6).
12. **Prefix test** — unit (`tests/plan_n/test_embeddings.py`: the request bodies) and live
    (`test_vector_retrieval_live.py`: every `input_sha256`; one stored vector equals a fresh prefixed embedding within
    the bound and differs from the unprefixed one) (Tasks 1 and 4).
13. **Tests without Ollama** — `tests/plan_n` uses `httpx2.MockTransport` and `FakeEmbedder` (hash-seeded unit
    vectors); live tests use real local Ollama; synthetic rows only in tenants the test creates (Tasks 1, 3-6).
14. **Determinism** — stored vectors are the truth; the report's repeat check; the live assertion cosine ≥ 0.9999
    (Tasks 2 and 6).
15. **Dev database** — owner steps: migrate to 0013, then `skeleton.py embed`; corpus-1 and its lock unchanged
    (asserted in `tests/plan_n/test_retrieval_comparison.py`) (Task 8).
16. **Mode choice** — the worker unchanged; `search_response` reports the mode that ran; the committed input and result
    schemas asserted byte-identical (`tests/plan_n/test_mcp_read_vector.py`); `UNSUPPORTED_MODE` only for the pin
    (Task 5; departure 11).
17. **Vector parameters** — `%s::public.vector` with `repr` floats (`embeddings.vector_literal`), parsed back by
    `embeddings.parse_vector`; no `pgvector-python`, no `numpy` (Tasks 1 and 3). Erratum 109.
18. **Records** — R034, R033's note, the docs, errata 107-111, the close-out records (Tasks 7 and 8).

## Measured before writing (2026-10-19, local Ollama 0.40.4 on loopback, read-only)

- `nomic-embed-text:latest`: `/api/tags` digest `0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f`,
  `embedding_length` 768; `/api/embed` answers one list of 768 floats per input in about 1.6 s cold.
- On corpus-1's 69 sections and the 47 development queries at `AS_OF` (2026-10-16T12:00Z), with the plan's own code
  (`uv run python -m scripts.retrieval_comparison threshold` on the scratch copy): vector hit@5 is 26/27 at every
  threshold up to 0.68 and 25/27 at 0.69, so the rule chooses **0.68**; at 0.68 the no-source cases answered with
  nothing are 18/20 (lexical: 15/20). The one labelled miss is A08; the no-source cases still answered are A13 and A15.
  hit@3 at 0.68 is 26/27. Two embeddings of each query were identical (largest component difference 0.0); a batch
  and a single request gave the same vector (cosine 1.0); a section's prefixed and unprefixed embeddings have cosine
  0.9599. These are expectations, not gates: Task 2 and Task 6 measure again.
- The committed T17 report's per-case answers hash to `7a059a196d083a80da88be611d8ca4dbaad43660922fd977450ee7c600eb04a3`
  (`retrieval_comparison.answers_digest`).
- The committed contracts T18 must not change: `schemas/tools/search_procedures.input.schema.json` SHA-256
  `51277441…58b9`, `schemas/tool-result.schema.json` `c4e6f39b…466a`.

## Declared debt and errata

### Debt list (committed in Task 1 Step 1c, before coding)

Inserted into `SESSION_STATE.md` as a new section `## Plan N debt list (T18; committed before coding) [R6-B7]`
immediately after the Plan M debt list (before `## Environment (observed)`); the exact text is Task 1 Step 1c's Edit 1.

### Errata proposed to the owner (numbered on from Plan M's 106)

The spec text stays authoritative until the owner decides; each line names the text it amends. The full wording is
Task 8 Step 2's "Plan N executed" block; in short:

107. **SA:598 and SA:768 (`data/model-pins.json`)**: the file stays the generation model's (T02, T19); the embedding
     model's pin is `data/embedding-pins.json` (`{model, digest, dimension, ollama_version, probed_at}`, schema
     `schemas/embedding-pins.schema.json`), verified against `/api/tags`'s digest (AM-31 names `/api/show`, which
     carries none), by `skeleton.py embed` before it writes and by mcp-read on every vector call.
108. **BS:646, BS:144, ADR-0001:31 and `docs/ARCHITECTURE.md`**: mcp-read reaches Ollama, `/api/tags` and `/api/embed`
     with the embedding model only, never generation (SA:348 and SA:461 make mcp-read compute the query embedding);
     the call is not a `model_permit` holder (SA:203 governs generation).
109. **SA:584 (`pgvector-python` 0.5.0)**: unused, not violated: vectors cross as pgvector's text form cast in SQL
     (`%s::public.vector`, `repr` floats), so no dependency or adapter is added.
110. **SA:461 (`search_procedures_scoped`)**: `mode` is `lexical` or `vector`; `query` is required and bounded 1-500 in
     both; `vector` requires one non-zero embedding of exactly 768 dimensions and `lexical` none, else `OC005`
     `BAD_ARGUMENT`; in vector mode a permitted chunk without an embedding refuses the call (`OC005`
     `EMBEDDINGS_INCOMPLETE`) rather than leaving it out; `VECTOR_MODE_UNAVAILABLE` (erratum 99) is gone.
111. **BS:242 and BS:417 (score and index version)**: in vector mode `rank` is the cosine similarity, kept above
     `app._min_similarity()` (0.68, a development figure chosen by a rule fixed before measuring), not comparable with
     `ts_rank_cd`; the "index version" of BS:242 is recorded as model + digest + dimension + prefix + window, with no
     vector index (exact search).

## File structure

- `migrations/app/versions/0013_embeddings.py` (new, Task 3).
- `core/src/ops_core/embeddings.py` (new, Task 1), `embed.py` (new, Task 4); `model_pins.py` (Task 1), `settings.py`
  (Task 1), `privileges.py`, `locking.py`, `persistence.py` (Task 3), `routing.py` (Task 5).
- `mcp-read/src/ops_mcp_read/server.py` (Task 3: the marker; Task 5: vector mode).
- `scripts/pin_embedding_model.py` (new, Task 1), `scripts/build_schemas.py` (Tasks 1 and 5),
  `scripts/retrieval_comparison.py` (new, Task 2), `scripts/retrieval_baseline.py` (Task 2), `scripts/skeleton.py`
  (Task 4).
- `data/embedding-pins.json`, `schemas/embedding-pins.schema.json`, `schemas/examples/embedding-pins-*.json`,
  `schemas/examples/index.json` (Task 1, generated or measured).
- Tests: `tests/plan_n/` (`__init__.py`, `test_embedding_pins.py`, `test_embeddings.py`, `test_retrieval_comparison.py`,
  `test_migration_0013.py`, `test_embed_command.py`, `test_mcp_read_vector.py`); `tests/e2e/`
  (`test_migration_0013_live.py`, `test_vector_retrieval_live.py`, `test_retrieval_comparison_live.py`; `conftest.py`
  gains `embedded`); edits to `pyproject.toml` (`testpaths`), `tests/plan_c/test_schema_conformance.py`,
  `tests/plan_d/test_settings.py`, `tests/plan_e/test_transitions_table.py`, `tests/plan_j/test_verifier_t15.py`,
  `tests/plan_k/test_verifier_t47.py`, `tests/plan_k/test_mcp_write_startup.py`, `tests/plan_l/test_mcp_read_corpus.py`,
  and the live `test_migration_0008_live.py`, `test_migration_0011_live.py`, `test_migration_0012_live.py`,
  `test_mcp_read_live.py`.
- Reports: `reports/retrieval-comparison.md`, `.json` (Task 6, committed in Task 8).
- Documentation: `docs/retrieval.md`, `docs/runbooks/mcp-read.md`, `docs/runbooks/walking-skeleton.md`,
  `docs/ARCHITECTURE.md`, `docs/adr/ADR-0001-deployable-units-as-top-level-directories.md` (Task 7); Task 8:
  `handoff/*`, `SESSION_STATE.md`, `STATUS.md`, `docs/PROJECT_HISTORY.md`.

## Task overview

- **Task 1:** the debt list; `tests/plan_n` on the path; the embedding pin (loader, schema, script, the measured
  file); `ops_core.embeddings` and `OPS_OLLAMA_URL`. Tests: `test_embedding_pins.py` 9, `test_embeddings.py` 15 (DoD
  2's unit half), `test_schema_conformance.py` +3 (two examples, one mutant). Dev `1399 passed, 205 skipped`; live
  `1583 passed, 21 skipped` (arithmetic).
- **Task 2:** the comparison's pure functions, k = 3 in the baseline's metrics, and the threshold measurement. Tests:
  `test_retrieval_comparison.py` 9. Dev `1408 passed, 205 skipped`; live `1592 passed, 21 skipped`.
- **Task 3:** revision 0013, its matrix rows, the lock-order entry, persistence's vector parameters and marker,
  mcp-read's startup check; the live definer tests. Tests: `test_migration_0013.py` 9, the transitions module +1, the
  lock-order module +1; live `test_migration_0013_live.py` 4. Dev `1419 passed, 209 skipped`; live `1607 passed, 21
  skipped`.
- **Task 4:** `ops_core.embed`, `skeleton.py embed`, the `embedded` fixture; the live prefix, idempotency and
  exactness tests. Tests: `test_embed_command.py` 2; live `test_vector_retrieval_live.py` 4. Dev `1421 passed, 213
  skipped`; live `1613 passed, 21 skipped`.
- **Task 5:** mcp-read's `vector_exact`. Tests: `test_mcp_read_vector.py` 8; `tests/plan_l/test_mcp_read_corpus.py`
  one test rewritten (no count change); live `test_mcp_read_live.py` changed (no count change). Dev `1429 passed, 213
  skipped`; live `1621 passed, 21 skipped`.
- **Task 6:** the live comparison and the report. Live `test_retrieval_comparison_live.py` 1. Dev `1429 passed, 214
  skipped`; live `1622 passed, 21 skipped`.
- **Task 7:** documentation and erratum 108's architecture record. No tests.
- **Task 8:** close-out: handoff records, acceptance rows, errata 107-111, state, history, final gates. No tests.

The arithmetic, once: dev passed 1372 + 27 = 1399, + 9 = 1408, + 11 = 1419, + 2 = 1421, + 8 = 1429, + 0;
dev skipped 205, 205, + 4 = 209, + 4 = 213, 213, + 1 = 214. Live passed = dev passed + (dev skipped − 21): 1583,
1592, 1607, 1613, 1621, 1622, always with 21 skipped. The final dev figures (1429 passed, 214 skipped) were
measured on the scratch copy with every task applied; the per-task dev figures follow from the per-file counts
measured there; the live ones are not measured.

---

### Task 1: Debt before code — the embedding model's pin and its client

**Files:**
- Create: `tests/plan_n/__init__.py`, `tests/plan_n/test_embedding_pins.py`, `tests/plan_n/test_embeddings.py`,
  `core/src/ops_core/embeddings.py`, `scripts/pin_embedding_model.py`, `data/embedding-pins.json` (written by the
  script), `schemas/embedding-pins.schema.json`, `schemas/examples/embedding-pins-valid.json`,
  `schemas/examples/embedding-pins-invalid-dimension.json` (generated)
- Modify: `SESSION_STATE.md` (the debt list), `pyproject.toml` (`testpaths`), `core/src/ops_core/model_pins.py`,
  `core/src/ops_core/settings.py` (`Urls.ollama`), `scripts/build_schemas.py` (the schema and its two examples),
  `schemas/examples/index.json` (generated), `tests/plan_c/test_schema_conformance.py` (`MODELS`),
  `tests/plan_d/test_settings.py`, `tests/plan_j/test_verifier_t15.py`, `tests/plan_k/test_verifier_t47.py` (the
  `Urls` literal)

**Requirements:** ruling 3 (erratum 107), SA:645 (the prefixes; DoD 2's unit half), rulings 2, 4, 12, 13 and 17,
BS:670 (no invented digest), the Plan N debt list (SA:698).

**Interfaces:**
- Consumes: `ops_core.model_pins.NonEmpty`, `Digest`, `ModelPinsError`; `settings.urls()`; `scripts/build_schemas.py`'s
  `contract`, `closed`, `text`, `DIGEST`, `UTC_REQUEST`, `valid`, `invalid`; `httpx2.AsyncClient`,
  `httpx2.MockTransport` (tests).
- Produces: `model_pins.EmbeddingPins(model, digest, dimension: Literal[768], ollama_version, probed_at)`,
  `model_pins.load_embedding_pins(path) -> EmbeddingPins`; `schemas/embedding-pins.schema.json`;
  `data/embedding-pins.json`; `embeddings.MODEL`, `DIMENSION`, `DOCUMENT_PREFIX`, `QUERY_PREFIX`, `BATCH`,
  `TIMEOUT_SECONDS`, `PINS`, `Vector`; `EmbeddingError`, `Unavailable`, `PinMismatch`, `Malformed` (each with `code`,
  `retryable`); `document_text(section, body)`, `query_text(query)`, `input_sha256(text)`, `vector_literal(vector)`,
  `parse_vector(text)`, `cosine(a, b)`, `checked(raw, expected, dimension=768)`; `Embedder` (protocol: `verify`,
  `embed`, `aclose`); `OllamaEmbedder(base_url, *, transport=None)` with `from_settings()`, `version()`,
  `installed_digest(model)`, `verify(pins)`, `embed(texts, pins)`, `aclose()`; `settings.Urls.ollama`
  (`OPS_OLLAMA_URL`, default `http://127.0.0.1:11434`); `tests.plan_n.test_embeddings.FakeEmbedder`, `unit_vector`.

- [ ] **Step 1a: Record both baselines**

Run `PYTHONUTF8=1 uv run python scripts/check.py` → `CHECK: GREEN` with pytest `1372 passed, 205 skipped`; with the
dev stack up, local Ollama answering (`curl -s http://127.0.0.1:11434/api/version` → `{"version":"0.40.4"}`) and
`uv run python scripts/skeleton.py status` showing every process down, run `PYTHONUTF8=1 uv run python scripts/check.py
--profile test` → `CHECK: GREEN` with `1556 passed, 21 skipped`, then `git checkout -- reports/bootstrap
reports/skeleton reports/auth reports/admission reports/leases reports/events reports/outbox reports/mcp-read
reports/mcp-write reports/asset-sim reports/retrieval`. Run `uv run python -I scripts/verify_handoff.py
--reference-code --manifest --contracts` → exit 0. Record the three lines in the report. A gate that is not GREEN
stops the plan here, before anything is committed.

- [ ] **Step 1b: Record the base**

Run `git rev-parse --short HEAD` and write the hash as `BASE=<hash>` in the report and in the SDD ledger
(`.superpowers/sdd/2026-10-19-first-slice-n-vector-retrieval/progress.md`). Task 8's commit span is `<base>..<last>`.
`git status --short` must print nothing.

- [ ] **Step 1c: Commit the debt list (before any code)**

Edit 1 (`SESSION_STATE.md`, at the end of "Plan M debt list (T16; committed before coding) [R6-B7]"), replace:

```markdown
## Environment (observed)
```

with:

```markdown
## Plan N debt list (T18; committed before coding) [R6-B7]

Allowed shortcuts in T18, each with its owning task:
- the worker still searches in lexical mode only; choosing the mode per run and recording it in the run manifest →
  T20 (the graph's retrieve node) and T25 (SA:660's identical retrieval settings for conditions B and C) (Plan N
  ruling 16; `routing.py` carries `TODO(T25)`);
- the vector threshold (`app._min_similarity()`, 0.68) and the lexical minimum rank (0.25) are development figures
  chosen on the 47 development queries; a relevance or abstention rule beyond them → T20 (erratum 102), and a held-out
  measurement of both modes → T25 (Plan N rulings 6 and 9);
- numeric tokens (`4.5`, `M8x1.25`) cannot match as one lexeme (the query is normalised to `[a-z0-9]+` words while the
  chunk text is parsed raw): the development set gains numeric-token cases and measures the loss first → T23 (Plan N
  ruling 10);
- the stored unit stays one chunk per `## ` section; the 300-word window is an experiment in the comparison report
  only, because another stored unit changes evidence IDs and T41's labels → no task (Plan N ruling 8);
- one embedding per chunk: a model change is a later revision's re-embedding (`app.embeddings`'s key and its CHECKs
  pin the model and the dimension) → no task until a model change (Plan N ruling 1);
- chunks ingested after an `embed` run stay without an embedding until `embed` runs again; vector mode answers
  `REFUSED`/`EMBEDDINGS_INCOMPLETE` meanwhile, lexical mode is unaffected → operator step (runbook), no task (Plan N
  rulings 2 and 5);
- mcp-read's route to Ollama in containers (host name, the egress test that mcp-read reaches Ollama's embedding
  endpoints only) and packaging `data/embedding-pins.json` with mcp-read → T30 (erratum 108);
- the installed Ollama is 0.40.4 where SA:587 records 0.33.3; the pin records the version actually used and nothing
  here upgrades or downgrades it → owner decision (SA:587);
- the dev database stays below revision 0013 until the owner migrates it and runs `scripts/skeleton.py embed`; until
  the migration mcp-read refuses to start on it (it checks 0013) → owner input (Plan N ruling 15).

## Environment (observed)
```

```bash
git add SESSION_STATE.md
git commit -m "docs: declare Plan N's shortcuts before coding (T18 debt list)"
```

- [ ] **Step 2: Put `tests/plan_n` on the test path**

Edit 2 (`pyproject.toml`), replace:

```toml
  "tests/plan_h", "tests/plan_i", "tests/plan_j", "tests/plan_k", "tests/plan_l", "tests/plan_m", "tests/e2e",
```

with:

```toml
  "tests/plan_h", "tests/plan_i", "tests/plan_j", "tests/plan_k", "tests/plan_l", "tests/plan_m", "tests/plan_n",
  "tests/e2e",
```

Create `tests/plan_n/__init__.py`:

```python
"""Plan N (T18): exact vector retrieval, the embedding pin and the comparison, without a database or Ollama."""
```

- [ ] **Step 3: Write the failing tests**

Create `tests/plan_n/test_embedding_pins.py`:

```python
"""The embedding model's pin (Plan N ruling 3, erratum 107): `data/embedding-pins.json`, its schema and its loader.

Catches: a pin file that is missing, hand-edited into another shape, prefixed (`sha256:`), of another dimension than
the 768 `app.embeddings` stores, or naive in time; a committed pin that the schema and the loader judge differently;
and a pin that is not the measured one (the digest Ollama's `/api/tags` reported for `nomic-embed-text:latest` on the
dev machine, 2026-10-19), which would mean the file was filled with an invented value (BS:670).
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from ops_core import embeddings
from ops_core.model_pins import ModelPinsError, load_embedding_pins

SCHEMA = Draft202012Validator(
    json.loads(Path("schemas/embedding-pins.schema.json").read_text(encoding="utf-8")), format_checker=FormatChecker()
)
MEASURED = "0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f"  # /api/tags, 2026-10-19 (Plan N brief)
GOOD = {
    "model": "nomic-embed-text",
    "digest": "cd" * 32,
    "dimension": 768,
    "ollama_version": "0.40.4",
    "probed_at": "2026-10-19T08:00:00Z",
}


def write(tmp_path: Path, data: object) -> Path:
    path = tmp_path / "embedding-pins.json"
    path.write_text(json.dumps(data), encoding="utf-8", newline="\n")
    return path


def test_the_committed_pin_is_the_measured_one_and_both_judges_accept_it() -> None:
    raw = json.loads(embeddings.PINS.read_text(encoding="utf-8"))
    SCHEMA.validate(raw)
    pins = load_embedding_pins(embeddings.PINS)
    assert (pins.model, pins.digest, pins.dimension) == (embeddings.MODEL, MEASURED, embeddings.DIMENSION)
    assert embeddings.PINS == Path("data/embedding-pins.json").resolve()


@pytest.mark.parametrize(
    "change",
    [
        {"digest": "sha256:" + "cd" * 32},
        {"digest": "CD" * 32},
        {"dimension": 384},
        {"dimension": "768"},
        {"probed_at": "2026-10-19T08:00:00"},
        {"model": ""},
        {"extra": "field"},
    ],
    ids=["prefixed", "uppercase", "dimension", "dimension-text", "naive-time", "empty-model", "extra-field"],
)
def test_a_malformed_pin_is_refused_by_the_loader_and_the_schema(tmp_path: Path, change: dict[str, object]) -> None:
    data = {**GOOD, **change}
    with pytest.raises(ModelPinsError):
        load_embedding_pins(write(tmp_path, data))
    assert list(SCHEMA.iter_errors(data))


def test_a_missing_or_broken_file_is_a_pins_error(tmp_path: Path) -> None:
    with pytest.raises(ModelPinsError, match="not found"):
        load_embedding_pins(tmp_path / "absent.json")
    broken = tmp_path / "embedding-pins.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(ModelPinsError, match="not valid JSON"):
        load_embedding_pins(broken)
```

Create `tests/plan_n/test_embeddings.py`:

```python
"""The embedding text rules and the Ollama client without Ollama (T18 DoD 2; Plan N rulings 2-4, 12, 13 and 17).

Catches: a document or a query embedded without its nomic prefix, with another separator or without the heading (the
request bodies are asserted byte for byte, SA:645); a pin check that trusts `/api/show`, accepts another digest or a
model that is not installed; an answer accepted with another count of vectors, another dimension, a NaN, an infinity,
a boolean or all zeros; an unreachable, slow or failing Ollama reported as anything but the retryable `Unavailable`;
a vector literal that does not round-trip; and a deterministic fake embedder that is not deterministic.
"""

import hashlib
import json
import math
import random
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

import httpx2
import pytest
from ops_core import embeddings
from ops_core.model_pins import EmbeddingPins

pytestmark = pytest.mark.asyncio

PINS = EmbeddingPins(
    model="nomic-embed-text",
    digest="0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f",
    dimension=768,
    ollama_version="0.40.4",
    probed_at=datetime(2026, 10, 19, tzinfo=UTC),
)
TAGS = {"models": [{"name": "nomic-embed-text:latest", "model": "nomic-embed-text:latest", "digest": PINS.digest}]}


def unit_vector(text: str, dimension: int = 768) -> list[float]:
    """A deterministic fake embedding: a unit vector seeded by the text's SHA-256 (Plan N ruling 13)."""
    rng = random.Random(hashlib.sha256(text.encode("utf-8")).digest())
    raw = [rng.gauss(0.0, 1.0) for _ in range(dimension)]
    norm = math.sqrt(sum(x * x for x in raw))
    return [x / norm for x in raw]


class FakeEmbedder:
    """The deterministic embedder unit tests stand in for Ollama (mcp-read's tests use it too)."""

    def __init__(self, failure: embeddings.EmbeddingError | None = None) -> None:
        self.failure = failure
        self.texts: list[str] = []
        self.verified = 0

    async def verify(self, pins: EmbeddingPins) -> None:
        self.verified += 1
        if isinstance(self.failure, embeddings.PinMismatch | embeddings.Unavailable):
            raise self.failure

    async def embed(self, texts: Sequence[str], pins: EmbeddingPins) -> list[embeddings.Vector]:
        self.texts.extend(texts)
        if self.failure is not None:
            raise self.failure
        return [tuple(unit_vector(t)) for t in texts]

    async def aclose(self) -> None:
        return None


Answer = Callable[[httpx2.Request], httpx2.Response]


def ollama(embed: Answer | None = None, tags: dict[str, Any] = TAGS) -> tuple[embeddings.OllamaEmbedder, list[Any]]:
    """The real client over a scripted transport; returns it and the JSON bodies it posted."""
    posted: list[Any] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/api/tags":
            return httpx2.Response(200, json=tags)
        assert request.url.path == "/api/embed", request.url.path  # never /api/show, /api/generate or a pull
        body = json.loads(request.content)
        posted.append(body)
        if embed is not None:
            return embed(request)
        return httpx2.Response(
            200, json={"model": body["model"], "embeddings": [unit_vector(t) for t in body["input"]]}
        )

    return embeddings.OllamaEmbedder("http://ollama.test", transport=httpx2.MockTransport(answer)), posted


async def test_a_document_is_embedded_as_search_document_heading_blank_line_body() -> None:
    client, posted = ollama()
    text = embeddings.document_text("inspection", "Inspect the seal every 14 days.")
    vectors = await client.embed([text], PINS)
    assert posted == [
        {"model": "nomic-embed-text", "input": ["search_document: inspection\n\nInspect the seal every 14 days."]}
    ]
    assert len(vectors) == 1 and len(vectors[0]) == 768
    assert embeddings.input_sha256(text) == hashlib.sha256(posted[0]["input"][0].encode("utf-8")).hexdigest()


async def test_a_query_is_embedded_as_search_query_and_the_text() -> None:
    client, posted = ollama()
    await client.embed([embeddings.query_text("How often is the seal inspected?")], PINS)
    assert posted == [{"model": "nomic-embed-text", "input": ["search_query: How often is the seal inspected?"]}]


async def test_documents_go_in_batches_of_sixteen_in_order() -> None:
    client, posted = ollama()
    texts = [embeddings.document_text(f"s{i}", "body") for i in range(40)]
    vectors = await client.embed(texts, PINS)
    assert [len(b["input"]) for b in posted] == [16, 16, 8]
    assert [t for b in posted for t in b["input"]] == texts
    assert vectors == [tuple(unit_vector(t)) for t in texts]


async def test_the_pin_is_checked_against_the_tags_digest() -> None:
    client, _ = ollama()
    await client.verify(PINS)  # `nomic-embed-text` is listed as `nomic-embed-text:latest`
    for tags in (
        {"models": [{"name": "nomic-embed-text:latest", "digest": "ab" * 32}]},  # another build
        {"models": [{"name": "qwen3:8b", "digest": PINS.digest}]},  # not installed
    ):
        other, _ = ollama(tags=tags)
        with pytest.raises(embeddings.PinMismatch):
            await other.verify(PINS)
    with pytest.raises(embeddings.PinMismatch):
        await client.verify(PINS.model_copy(update={"model": "mxbai-embed-large"}))


@pytest.mark.parametrize(
    "vectors",
    [
        [],
        [[0.1] * 767],
        [[0.1] * 767 + [float("nan")]],
        [[0.1] * 767 + [True]],
        [[0.0] * 768],
        "not a list",
    ],
    ids=["no-vector", "767", "nan", "boolean", "zeros", "not-a-list"],
)
async def test_a_malformed_answer_is_refused(vectors: Any) -> None:
    def answer(request: httpx2.Request) -> httpx2.Response:
        # json.dumps writes NaN as a bare token, which Python's parser reads back as a float NaN.
        return httpx2.Response(200, content=json.dumps({"embeddings": vectors}).encode())

    client, _ = ollama(answer)
    with pytest.raises(embeddings.Malformed):
        await client.embed(["search_query: x"], PINS)


@pytest.mark.parametrize("kind", ["connect", "timeout", "503"])
async def test_an_unreachable_or_failing_model_is_unavailable_and_retryable(kind: str) -> None:
    def answer(request: httpx2.Request) -> httpx2.Response:
        if kind == "connect":
            raise httpx2.ConnectError("refused", request=request)
        if kind == "timeout":
            raise httpx2.ReadTimeout("slow", request=request)
        return httpx2.Response(503, json={"error": "loading"})

    client, _ = ollama(answer)
    with pytest.raises(embeddings.Unavailable) as caught:
        await client.embed(["search_query: x"], PINS)
    assert caught.value.code == "UNAVAILABLE" and caught.value.retryable


async def test_vector_literals_round_trip_and_cosine_is_plain_arithmetic() -> None:
    vector = tuple(unit_vector("round trip"))
    literal = embeddings.vector_literal(vector)
    assert literal.startswith("[") and " " not in literal
    assert embeddings.parse_vector(literal) == vector
    assert embeddings.cosine(vector, vector) == pytest.approx(1.0)
    assert embeddings.cosine((1.0, 0.0), (0.0, 1.0)) == 0.0


async def test_the_fake_embedder_is_deterministic() -> None:
    fake = FakeEmbedder()
    first = await fake.embed(["search_query: seal"], PINS)
    assert first == await fake.embed(["search_query: seal"], PINS)
    assert first != await fake.embed(["seal"], PINS)
```

Run: `uv run python -m pytest tests/plan_n -q`
Expected: two collection errors, `ImportError: cannot import name 'embeddings' from 'ops_core'` (and, once that
exists, `load_embedding_pins` is still missing).

- [ ] **Step 4: The pin's loader and schema**

Edit 3 (`core/src/ops_core/model_pins.py`), replace:

```python
"""Model pins (`data/model-pins.json`, AM-31): the digest the worker must see from Ollama at warm-up, or fail closed.
```

with:

```python
"""Model pins (`data/model-pins.json`, AM-31): the digest the worker must see from Ollama at warm-up, or fail closed;
and the embedding model's own pin (`data/embedding-pins.json`, T18), which `skeleton.py embed` and mcp-read check.
```

Edit 4 (`core/src/ops_core/model_pins.py`), replace:

```python
from typing import Annotated
```

with:

```python
from typing import Annotated, Literal
```

Edit 5 (`core/src/ops_core/model_pins.py`), replace:

```python
        raise ModelPinsError(f"model pins file is malformed: {path}: {exc}") from exc
```

with:

```python
        raise ModelPinsError(f"model pins file is malformed: {path}: {exc}") from exc


class EmbeddingPins(BaseModel):
    """`data/embedding-pins.json` (T18, Plan N ruling 3, erratum 107): the embedding model's pin, a sibling of the
    generation model's. Strict as `ModelPins`, plus the dimension, which must be the 768 that `app.embeddings` and
    `search_procedures_scoped` hold (SA:461)."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    model: NonEmpty
    digest: Digest
    dimension: Literal[768]
    ollama_version: NonEmpty
    probed_at: AwareDatetime


def load_embedding_pins(path: Path) -> EmbeddingPins:
    """Read and validate the embedding pins file, with `load_model_pins`'s strictness and messages.

    Raises:
        ModelPinsError: the file is missing, is not JSON, or does not match `EmbeddingPins`.
    """
    if not path.is_file():
        raise ModelPinsError(f"embedding pins file not found: {path}")
    text = path.read_text(encoding="utf-8")
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        raise ModelPinsError(f"embedding pins file is not valid JSON: {path}: {exc}") from exc
    try:
        return EmbeddingPins.model_validate_json(text)
    except ValidationError as exc:
        raise ModelPinsError(f"embedding pins file is malformed: {path}: {exc}") from exc
```

Edit 6 (`scripts/build_schemas.py`), replace:

```python

def route() -> Doc:
```

with:

```python

def embedding_pins() -> Doc:
    """data/embedding-pins.json (T18, Plan N ruling 3, erratum 107): the embedding model's pin beside the generation
    model's, written by scripts/pin_embedding_model.py from Ollama's /api/version, /api/tags (the digest: /api/show
    carries none) and one /api/embed call (the dimension). The spellings are model-pins'; the dimension is the 768 of
    `app.embeddings` and SA:461's `vector(768)`."""
    return contract(
        "embedding-pins",
        closed(
            {
                "model": text(1, 200),
                "digest": DIGEST,
                "dimension": {"type": "integer", "const": 768},
                "ollama_version": text(1, 80),
                "probed_at": UTC_REQUEST,
            },
            ["model", "digest", "dimension", "ollama_version", "probed_at"],
        ),
    )


def route() -> Doc:
```

Edit 7 (`scripts/build_schemas.py`), replace:

```python
        "model-pins": model_pins(),
```

with:

```python
        "model-pins": model_pins(),
        "embedding-pins": embedding_pins(),
```

Edit 8 (`scripts/build_schemas.py`), replace:

```python
        "probed_at": "2026-10-08T00:00:00Z",
```

with:

```python
        "probed_at": "2026-10-08T00:00:00Z",
    }
    embedding_pins_valid = {
        "model": "nomic-embed-text",
        "digest": "cd" * 32,
        "dimension": 768,
        "ollama_version": "0.12.3",
        "probed_at": "2026-10-19T00:00:00Z",
```

Edit 9 (`scripts/build_schemas.py`), replace:

```python
    valid("model-pins-valid", "model-pins", pins_valid)
```

with:

```python
    valid("model-pins-valid", "model-pins", pins_valid)
    valid("embedding-pins-valid", "embedding-pins", embedding_pins_valid)
```

Edit 10 (`scripts/build_schemas.py`), replace:

```python
        "^\\$\\.digest: '.*' (does not match|is too long)",  # 71 characters fail both the pattern and maxLength
```

with:

```python
        "^\\$\\.digest: '.*' (does not match|is too long)",  # 71 characters fail both the pattern and maxLength
    )
    invalid(
        "embedding-pins-invalid-dimension",
        "embedding-pins",
        {**embedding_pins_valid, "dimension": 384},
        "The dimension is the 768 that app.embeddings stores (T18, SA:461).",
        "^\\$\\.dimension: 768 was expected$",
```

Edit 11 (`tests/plan_c/test_schema_conformance.py`), replace:

```python
from ops_core.model_pins import ModelPins
```

with:

```python
from ops_core.model_pins import EmbeddingPins, ModelPins
```

Edit 12 (`tests/plan_c/test_schema_conformance.py`), replace:

```python
    "schemas/model-pins.schema.json": ModelPins,
```

with:

```python
    "schemas/model-pins.schema.json": ModelPins,
    "schemas/embedding-pins.schema.json": EmbeddingPins,  # T18 (Plan N ruling 3)
```

Run: `uv run python -m scripts.build_schemas`
Expected: `schemas/: 26 schema documents (20 contracts, 6 tool inputs); 91 examples (36 valid, 55 invalid);
index.json version 1.3.3`, and `git status --short schemas` shows the new schema, its two examples and
`schemas/examples/index.json`, nothing else.

Run: `uv run python -m pytest tests/plan_c -q` → `307 passed` (304 before: two examples and one mutant more), and
`uv run python -I scripts/verify_handoff.py --contracts` → `PASS: 27 JSON Schema documents; 36 accepted examples; 55
negative examples failed for their stated reason; governed files LF-only` (26 and 35 and 54 before).

- [ ] **Step 5: The setting and the client**

Edit 13 (`core/src/ops_core/settings.py`), replace:

```python
    asset_sim: str  # T16: where mcp-read reaches asset-sim (Plan M ruling 5)
```

with:

```python
    asset_sim: str  # T16: where mcp-read reaches asset-sim (Plan M ruling 5)
    ollama: str  # T18: where mcp-read and `skeleton.py embed` reach the embedding model (Plan N ruling 4)
```

Edit 14 (`core/src/ops_core/settings.py`), replace:

```python
        asset_sim=env("OPS_ASSET_SIM_URL", "http://127.0.0.1:8091"),
```

with:

```python
        asset_sim=env("OPS_ASSET_SIM_URL", "http://127.0.0.1:8091"),
        ollama=env("OPS_OLLAMA_URL", "http://127.0.0.1:11434"),
```

Edit 15 (`tests/plan_d/test_settings.py`), replace:

```python
    assert settings.urls().asset_sim == "http://127.0.0.1:8091"  # T16: mcp-read -> asset-sim
```

with:

```python
    assert settings.urls().asset_sim == "http://127.0.0.1:8091"  # T16: mcp-read -> asset-sim
    monkeypatch.delenv("OPS_OLLAMA_URL", raising=False)
    assert settings.urls().ollama == "http://127.0.0.1:11434"  # T18: mcp-read and embed -> loopback Ollama
```

Edit 16 (`tests/plan_j/test_verifier_t15.py`), replace:

```python
    asset_sim="http://127.0.0.1:8091",
```

with:

```python
    asset_sim="http://127.0.0.1:8091",
    ollama="http://127.0.0.1:11434",
```

Edit 17 (`tests/plan_k/test_verifier_t47.py`), replace:

```python
    asset_sim="http://127.0.0.1:8091",
```

with:

```python
    asset_sim="http://127.0.0.1:8091",
    ollama="http://127.0.0.1:11434",
```

Create `core/src/ops_core/embeddings.py`:

```python
"""The embedding model's text rules and its Ollama client (T18; Plan N rulings 2-4, 12, 13 and 17; SA:645, SA:348).

`nomic-embed-text` is trained with task prefixes, and SA:645 requires them: a document is embedded as
`search_document: ` + its section heading + a blank line + its body (the heading and the body, as the lexical vector
indexes both), a query as `search_query: ` + the query text. The builders here are the only place those strings are
made; the unit tests assert the request bodies an embedder sends, and every stored row keeps the SHA-256 of the exact
text it was made from.

`OllamaEmbedder` talks to local Ollama (`OPS_OLLAMA_URL`, loopback by default) with `httpx2`, a 10-second timeout per
request and no retry (asset-sim's client pattern). It asks only `/api/tags` (the pinned digest; `/api/show` carries
none) and `/api/embed`, never a generation endpoint, so it is not a `model_permit` holder (SA:203 governs
generation). Failures map to one exception each, which the callers turn into their own answers: unreachable, a timeout
or a 5xx is `Unavailable` (retryable); a digest or model other than the pin is `PinMismatch`; any answer that is not
exactly one list of 768 finite floats per input, with a non-zero norm, is `Malformed`.

Vectors cross into PostgreSQL as pgvector's text form cast in SQL (`%s::public.vector`), each float written with
`repr` so it round-trips exactly; no `pgvector` package is used (erratum 109).
"""

from __future__ import annotations

import asyncio
import hashlib
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, Protocol

import httpx2

from ops_core import settings
from ops_core.model_pins import EmbeddingPins

MODEL: Final = "nomic-embed-text"
DIMENSION: Final = 768
DOCUMENT_PREFIX: Final = "search_document: "
QUERY_PREFIX: Final = "search_query: "
BATCH: Final = 16  # inputs per /api/embed request: small enough for one 10-second request on the dev machine
TIMEOUT_SECONDS: Final = 10.0  # Plan N ruling 4, as asset-sim's client
PINS: Final = Path(__file__).resolve().parents[3] / "data" / "embedding-pins.json"  # read from the checkout (T30)

Vector = tuple[float, ...]


class EmbeddingError(Exception):
    """The embedding model gave no usable answer; `code` and `retryable` are what a tool's error envelope carries."""

    code = "UPSTREAM_INVALID"
    retryable = False


class Unavailable(EmbeddingError):
    """Ollama could not be reached, timed out or answered 5xx: try again later."""

    code = "UNAVAILABLE"
    retryable = True


class PinMismatch(EmbeddingError):
    """The installed model is not the pinned one (another digest, or not installed): vector mode is unsupported."""

    code = "UNSUPPORTED_MODE"


class Malformed(EmbeddingError):
    """An answer that is not one finite, non-zero vector of the pinned dimension per input."""


def document_text(section: str, body: str) -> str:
    """The exact text a stored chunk is embedded from: the document prefix, the heading, a blank line, the body."""
    return f"{DOCUMENT_PREFIX}{section}\n\n{body}"


def query_text(query: str) -> str:
    """The exact text a search query is embedded from."""
    return f"{QUERY_PREFIX}{query}"


def input_sha256(text: str) -> str:
    """The SHA-256 of the UTF-8 text sent to the model: the stored proof of which text, prefix included, was used."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def vector_literal(vector: Sequence[float]) -> str:
    """pgvector's text form, `[f1,f2,...]`, with `repr` floats so the value round-trips exactly."""
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"


def parse_vector(text: str) -> Vector:
    """A vector read back in pgvector's text form (tests and the measurement read stored rows this way)."""
    inner = text.strip()
    if not (inner.startswith("[") and inner.endswith("]")):
        raise ValueError("not a vector in pgvector's text form")
    return tuple(float(part) for part in inner[1:-1].split(",")) if inner != "[]" else ()


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity in plain double-precision arithmetic (no numpy, ruling 17)."""
    dot = math.fsum(x * y for x, y in zip(a, b, strict=True))
    return dot / math.sqrt(math.fsum(x * x for x in a) * math.fsum(y * y for y in b))


def checked(raw: object, expected: int, dimension: int = DIMENSION) -> list[Vector]:
    """`/api/embed`'s `embeddings` as vectors, or Malformed: exactly `expected` lists of `dimension` finite numbers
    each (a JSON boolean is not a number), none of them all zeros."""
    if not isinstance(raw, list) or len(raw) != expected:
        raise Malformed("the embedding answer has another number of vectors than inputs")
    out: list[Vector] = []
    for item in raw:
        if not isinstance(item, list) or len(item) != dimension:
            raise Malformed("an embedding has another dimension than the pinned one")
        if not all(isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v) for v in item):
            raise Malformed("an embedding holds a value that is not a finite number")
        vector = tuple(float(v) for v in item)
        if not any(vector):
            raise Malformed("an embedding is all zeros")
        out.append(vector)
    return out


class Embedder(Protocol):
    """What mcp-read and `skeleton.py embed` need from the embedding model, so unit tests can stand one in."""

    async def verify(self, pins: EmbeddingPins) -> None:
        """Raise PinMismatch unless the installed model is the pinned one; Unavailable when it cannot be asked."""
        ...

    async def embed(self, texts: Sequence[str], pins: EmbeddingPins) -> list[Vector]:
        """One vector per text, in order, of the pinned dimension."""
        ...

    async def aclose(self) -> None:
        """Release the connections."""
        ...


class OllamaEmbedder:
    """The real embedder: one pooled httpx2 client to local Ollama."""

    def __init__(self, base_url: str, *, transport: httpx2.AsyncBaseTransport | None = None) -> None:
        """`transport` lets unit tests answer without a socket."""
        self._base = base_url.rstrip("/")
        self._http = httpx2.AsyncClient(timeout=TIMEOUT_SECONDS, transport=transport)

    @classmethod
    def from_settings(cls) -> OllamaEmbedder:
        """Wired from `OPS_OLLAMA_URL` (`settings.Urls.ollama`)."""
        return cls(settings.urls().ollama)

    async def _json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            async with asyncio.timeout(TIMEOUT_SECONDS):
                response = await self._http.request(method, f"{self._base}{path}", json=payload)
        # A closed client raises RuntimeError and the budget's expiry a TimeoutError (an OSError); neither may escape
        # as anything but Unavailable, and none puts its text in an answer.
        except (httpx2.HTTPError, OSError, RuntimeError) as exc:
            raise Unavailable("the embedding model could not be reached") from exc
        if response.status_code >= 500:
            raise Unavailable("the embedding model is unavailable")
        if response.status_code != 200:
            raise Malformed(f"the embedding model answered {response.status_code}")
        try:
            body = response.json()
        except ValueError as exc:
            raise Malformed("the embedding model answered a body that is not JSON") from exc
        if not isinstance(body, dict):
            raise Malformed("the embedding model answered a body that is not an object")
        return body

    async def version(self) -> str:
        """The Ollama version `/api/version` reports (the pin and the comparison record it)."""
        found = (await self._json("GET", "/api/version")).get("version")
        if not isinstance(found, str):
            raise Malformed("/api/version answered without a version")
        return found

    async def installed_digest(self, model: str) -> str | None:
        """The digest `/api/tags` reports for `model` (`name:latest` when the name has no tag), or None."""
        names = {model, model if ":" in model else f"{model}:latest"}
        body = await self._json("GET", "/api/tags")
        models = body.get("models")
        if not isinstance(models, list):
            raise Malformed("/api/tags answered without a model list")
        for entry in models:
            if isinstance(entry, dict) and (entry.get("name") in names or entry.get("model") in names):
                digest = entry.get("digest")
                return digest if isinstance(digest, str) else None
        return None

    async def verify(self, pins: EmbeddingPins) -> None:
        if pins.model != MODEL or pins.dimension != DIMENSION:
            raise PinMismatch("the pin names another embedding model")
        if await self.installed_digest(pins.model) != pins.digest:
            raise PinMismatch("the installed embedding model is not the pinned one")

    async def embed(self, texts: Sequence[str], pins: EmbeddingPins) -> list[Vector]:
        out: list[Vector] = []
        for start in range(0, len(texts), BATCH):
            batch = list(texts[start : start + BATCH])
            body = await self._json("POST", "/api/embed", {"model": pins.model, "input": batch})
            out.extend(checked(body.get("embeddings"), len(batch), pins.dimension))
        return out

    async def aclose(self) -> None:
        await self._http.aclose()
```

Run: `uv run python -m pytest tests/plan_n/test_embeddings.py tests/plan_d/test_settings.py -q`
Expected: `tests/plan_n/test_embeddings.py` `15 passed`; `tests/plan_d/test_settings.py` all passing, unchanged in
count.

- [ ] **Step 6: Pin the model (local Ollama, read-only)**

Create `scripts/pin_embedding_model.py`:

```python
"""Write data/embedding-pins.json from the local Ollama (T18; Plan N ruling 3, erratum 107).

Usage: `uv run python scripts/pin_embedding_model.py` (loopback Ollama, `OPS_OLLAMA_URL` to override).

It reads three things and invents none (BS:670): the Ollama version (`/api/version`), the digest `/api/tags` reports
for `nomic-embed-text:latest` (`/api/show` carries no digest, as T19's note found for qwen3:8b) and the dimension of
one real `/api/embed` answer, which must be 768. It never pulls, deletes or generates. The file is the embedding
model's pin beside the generation model's `data/model-pins.json` (T02, SA:598), checked by `skeleton.py embed` before
it writes and by mcp-read on every vector call. Exit 1, writing nothing, when the model is missing or answers another
dimension.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime

from ops_core import embeddings, settings
from ops_core.model_pins import load_embedding_pins

OUT = embeddings.PINS


async def probe(base: str) -> dict[str, object]:
    """The pin's fields as Ollama reports them now."""
    embedder = embeddings.OllamaEmbedder(base)
    try:
        version = await embedder.version()
        digest = await embedder.installed_digest(embeddings.MODEL)
        if digest is None:
            raise SystemExit(f"PIN: {embeddings.MODEL} is not installed in this Ollama; nothing written")
        # The raw answer, not `embed`: `embed` checks the dimension against a pin, and this is what makes the pin.
        answer = await embedder._json("POST", "/api/embed", {"model": embeddings.MODEL, "input": ["dimension probe"]})
    finally:
        await embedder.aclose()
    vectors = answer.get("embeddings")
    if not isinstance(vectors, list) or not vectors or not isinstance(vectors[0], list):
        raise SystemExit("PIN: /api/embed answered without a vector; nothing written")
    return {
        "model": embeddings.MODEL,
        "digest": digest,
        "dimension": len(vectors[0]),
        "ollama_version": version,
        "probed_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def main() -> int:
    """Probe, check the dimension, write the pin and read it back."""
    pin = asyncio.run(probe(settings.urls().ollama))
    if pin["dimension"] != embeddings.DIMENSION:
        print(
            f"PIN: {embeddings.MODEL} answered {pin['dimension']} dimensions, not {embeddings.DIMENSION}; "
            "nothing written"
        )
        return 1
    OUT.write_text(json.dumps(pin, indent=2) + "\n", encoding="utf-8", newline="\n")
    load_embedding_pins(OUT)  # the file just written must load as the services read it
    print(f"PIN: {pin['model']} {pin['digest']} dimension {pin['dimension']} on Ollama {pin['ollama_version']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Run: `uv run python scripts/pin_embedding_model.py`
Expected (measured on the scratch copy): `PIN: nomic-embed-text 0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f
dimension 768 on Ollama 0.40.4`, and `data/embedding-pins.json` reads as below, only `probed_at` being the instant the
script ran:

```json
{
  "model": "nomic-embed-text",
  "digest": "0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f",
  "dimension": 768,
  "ollama_version": "0.40.4",
  "probed_at": "2026-10-19T17:04:31Z"
}
```

If the digest or the version differs, stop and report: the brief's measurement and the machine disagree, and the pin
records only what the machine reports (BS:670). Then `uv run python -m pytest tests/plan_n -q` → `24 passed`.

- [ ] **Step 7: Gates and commit**

`PYTHONUTF8=1 uv run python scripts/check.py` → `CHECK: GREEN`, pytest `1399 passed, 205 skipped`;
`verify_handoff.py` exit 0; the live gate → `1583 passed, 21 skipped` (then the `git checkout -- reports/…` line of
the Global Constraints).

```bash
git add pyproject.toml tests/plan_n/__init__.py tests/plan_n/test_embedding_pins.py tests/plan_n/test_embeddings.py \
  core/src/ops_core/model_pins.py core/src/ops_core/settings.py core/src/ops_core/embeddings.py \
  scripts/build_schemas.py scripts/pin_embedding_model.py schemas/embedding-pins.schema.json \
  schemas/examples/embedding-pins-valid.json schemas/examples/embedding-pins-invalid-dimension.json \
  schemas/examples/index.json tests/plan_c/test_schema_conformance.py tests/plan_d/test_settings.py \
  tests/plan_j/test_verifier_t15.py tests/plan_k/test_verifier_t47.py data/embedding-pins.json
git commit -m "feat: the embedding model's pin and ops_core.embeddings, the nomic prefixes and the Ollama client (T18)"
```

---

### Task 2: The comparison's functions and the threshold, measured before the revision freezes it

**Files:**
- Create: `scripts/retrieval_comparison.py`, `tests/plan_n/test_retrieval_comparison.py`
- Modify: `scripts/retrieval_baseline.py` (`Outcome.relevant_at`, `summarize(…, k)`)

**Requirements:** rulings 6, 8, 9, 11 and 14; SA:665-667; T18 DoD 1's statistics.

**Interfaces:**
- Consumes: `retrieval_baseline.Case`, `Outcome`, `evaluate`, `proportion`, `summarize`, `load_queries`, `_rate`,
  `K`; `corpus.load`, `returnable`, `Section`; `embeddings.*`; `model_pins.load_embedding_pins`.
- Produces: `retrieval_baseline.Outcome.relevant_at(k)`, `summarize(outcomes, k=K)` (T17's output unchanged at the
  default); `retrieval_comparison.T17_ANSWERS_SHA256`, `AS_OF`, `KS`, `GRID`, `LEXICAL_GRID`, `WINDOW_WORDS`,
  `REPEAT_COSINE`, `answers_digest`, `mcnemar`, `paired`, `ranked`, `sweep`, `choose_threshold`, `lexical_sweep`,
  `windows`, `window_text`, `Window`, `corpus_windows`, `window_metrics`, `repeat_check`, `comparison`, `markdown`,
  and the `threshold` command.

- [ ] **Step 1: Write the failing tests**

Create `tests/plan_n/test_retrieval_comparison.py`:

```python
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


def test_the_committed_lexical_answers_and_the_inputs_are_t17s() -> None:
    t17: dict[str, Any] = json.loads(rc.T17_REPORT.read_text(encoding="utf-8"))
    assert rc.answers_digest(t17["cases"]) == rc.T17_ANSWERS_SHA256
    queries = hashlib.sha256(rc.QUERIES.read_bytes()).hexdigest()
    assert queries == t17["queries_sha256"] == "d6d539bdd9a540f6e7a66dd641c05e5c1ee97c1561c59f5b67896fedb1596938"
    assert corpus.RELEASES == {"corpus-1": "81f50c2b8623675f9c899033cba748f289b7f4024003385aabc8a95147b71862"}
    assert corpus.load(rc.CORPUS).lock_sha256 == corpus.RELEASES["corpus-1"]  # corpus-1 untouched (ruling 15)


def test_the_report_names_both_modes_every_change_and_the_settings() -> None:
    cases = [case("A1", ("x",)), case("A2", ("y",)), case("N1", none=True)]
    allowed = {"x", "y", "n"}
    lexical = [rb.evaluate(c, r, allowed) for c, r in zip(cases, ([("x", 0.5)], [("y", 0.4)], [("n", 0.3)]))]
    vector = [rb.evaluate(c, r, allowed) for c, r in zip(cases, ([("x", 0.9)], [], []))]
    scored = {"A1": [("x", 0.9)], "A2": [("y", 0.6)], "N1": [("n", 0.5)]}
    doc = rc.comparison(
        lexical,
        vector,
        settings={"model": "nomic-embed-text", "vector_minimum_similarity": 0.68},
        vector_sweep=rc.sweep(cases, scored, rc.GRID),
        lexical_sweep_rows=rc.lexical_sweep(lexical, rc.LEXICAL_GRID),
        window={
            "windows": 2,
            "recall_at_k": 1.0,
            "hit_at_k": rb.proportion(2, 2),
            "none_answered_empty": rb.proportion(1, 1),
            "forbidden_sections": 0,
        },
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
    text = rc.markdown(doc)
    for needle in (
        "## Results",
        "### k = 3",
        "regressed: A2",
        "improved by vector: N1",
        "## Thresholds",
        "## Another chunk window",
        "## Determinism",
        "`vector_minimum_similarity`: 0.68",
    ):
        assert needle in text, needle
```

Run: `uv run python -m pytest tests/plan_n/test_retrieval_comparison.py -q`
Expected: a collection error, `ImportError: cannot import name 'retrieval_comparison' from 'scripts'`.

- [ ] **Step 2: k as a parameter of the baseline's metrics**

Edit 1 (`scripts/retrieval_baseline.py`), replace:

```python
        return len(set(self.ids[:K]) & set(self.case.expected))
```

with:

```python
        return self.relevant_at(K)

    def relevant_at(self, k: int) -> int:
        """How many expected sections are in the top `k` (T18 also reports k = 3, the worker's limit)."""
        return len(set(self.ids[:k]) & set(self.case.expected))
```

Edit 2 (`scripts/retrieval_baseline.py`), replace:

```python
def summarize(outcomes: Sequence[Outcome]) -> dict[str, Any]:
    """Case-level metrics at K with denominators: recall, precision and reciprocal rank as means over the answerable
    cases; hit@K, every-expected@K, the expect_none cases answered with nothing, and the cases free of forbidden
    sections as proportions with Wilson intervals; the forbidden rate over every returned row."""
```

with:

```python
def summarize(outcomes: Sequence[Outcome], k: int = K) -> dict[str, Any]:
    """Case-level metrics at `k` (default K) with denominators: recall, precision and reciprocal rank as means over
    the answerable cases; hit@k, every-expected@k, the expect_none cases answered with nothing in the top `k`, and the
    cases free of forbidden sections as proportions with Wilson intervals; the forbidden rate over every returned
    row."""
```

Edit 3 (`scripts/retrieval_baseline.py`), replace:

```python
        ranks = [i for i, e in enumerate(o.ids[:K], start=1) if e in o.case.expected]
```

with:

```python
        ranks = [i for i, e in enumerate(o.ids[:k], start=1) if e in o.case.expected]
```

Edit 4 (`scripts/retrieval_baseline.py`), replace:

```python
                sum(o.relevant > 0 for o in members if o.case.expected), sum(1 for o in members if o.case.expected)
```

with:

```python
                sum(o.relevant_at(k) > 0 for o in members if o.case.expected),
                sum(1 for o in members if o.case.expected),
```

Edit 5 (`scripts/retrieval_baseline.py`), replace:

```python
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
```

with:

```python
        "k": k,
        "cases": len(outcomes),
        "answerable": len(answerable),
        "expect_none": len(nones),
        "recall_at_k": mean([o.relevant_at(k) / len(o.case.expected) for o in answerable]),
        "precision_at_k": mean([o.relevant_at(k) / k for o in answerable]),  # the standard P@k: over k, not over rows
        # The most P@k can be: a case with m expected sections has at most min(m, k) relevant rows among k. With
        # recall 1.0 the two are equal, so a low P@k then is the labels' size, not the ranker's fault.
        "precision_ceiling_at_k": mean([min(len(o.case.expected), k) / k for o in answerable]),
        "mrr_at_k": mean([reciprocal(o) for o in answerable]),
        "hit_at_k": proportion(sum(o.relevant_at(k) > 0 for o in answerable), len(answerable)),
        "all_expected_at_k": proportion(
            sum(o.relevant_at(k) == len(o.case.expected) for o in answerable), len(answerable)
        ),
```

Run: `uv run python -m pytest tests/plan_l/test_retrieval_baseline.py -q` → all passing, unchanged in count (T17's
report is `summarize(outcomes)`, the default k).

- [ ] **Step 3: The module**

Create `scripts/retrieval_comparison.py`:

```python
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
    """Ruling 6's rule, fixed before measuring: the largest grid value whose hit@k equals the value at 0 (no answerable
    hit lost); 0.0 when only 0 keeps it."""
    at_zero = next(r["hit_at_k"] for r in rows if r["threshold"] == 0.0)
    return max(float(r["threshold"]) for r in rows if r["hit_at_k"] == at_zero)


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
    """One window of the experiment: its tenant, asset family, the evidence IDs it contains and its text."""

    tenant: str
    asset_family: str | None
    evidence_ids: tuple[str, ...]
    text: str


def corpus_windows(governed: corpus.Corpus, now: datetime = AS_OF) -> list[Window]:
    """Every window of every version a search may return at `now` (`corpus.returnable`, the oracle of the SQL rule)."""
    allowed = corpus.returnable(governed, now)
    return [
        Window(d.tenant, d.asset_family, tuple(d.evidence_id(s) for s in group), window_text(group))
        for d in governed.documents
        if d.identity in allowed
        for group in windows(d.sections)
    ]


def window_metrics(
    cases: Sequence[rb.Case],
    found: Mapping[str, Sequence[Window]],
    permitted: Mapping[str, set[str]],
    total: int,
) -> dict[str, Any]:
    """The window experiment's case-level figures at k = 5: recall of the labelled sections inside the top windows,
    hit@5, the no-source cases answered with nothing, and windows holding a section the case may not see (zero by
    construction, counted anyway)."""
    answerable = [c for c in cases if c.expected]
    nones = [c for c in cases if c.expect_none]

    def inside(c: rb.Case) -> set[str]:
        return {e for w in found[c.id][: rb.K] for e in w.evidence_ids}

    recall = [len(inside(c) & set(c.expected)) / len(c.expected) for c in answerable]
    forbidden = sum(1 for c in cases for w in found[c.id] for e in w.evidence_ids if e not in permitted[c.tenant])
    return {
        "k": rb.K,
        "windows": total,
        "recall_at_k": round(sum(recall) / len(recall), 4) if recall else None,
        "hit_at_k": rb.proportion(sum(bool(inside(c) & set(c.expected)) for c in answerable), len(answerable)),
        "none_answered_empty": rb.proportion(sum(not found[c.id] for c in nones), len(nones)),
        "forbidden_sections": forbidden,
    }


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
        lines += [f"| forbidden sections among returned rows | {forbidden} |", ""]
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
        "its value at 0. The sweep below re-applies it to the stored vectors."
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
    lexical_note = (
        "Lexical minimum rank, swept over the recorded ranks (the definer already drops 0.25 and below); it stays "
        "0.25, and the residue is T20's relevance criterion (erratum 102)."
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
    window = (
        f"Adjacent sections of one version joined until at least {WINDOW_WORDS} `[a-z0-9]+` words ({w['windows']} "
        "windows), embedded with the same prefix, ranked by cosine over the same permitted versions, kept above the "
        f"same threshold. A window hits when it contains a labelled section. recall@5 {w['recall_at_k']}; hit@5 "
        f"{rb._rate(w['hit_at_k'])}; no-source cases answered with nothing {rb._rate(w['none_answered_empty'])}; "
        f"windows holding a section the case may not see: {w['forbidden_sections']}. The stored unit stays one chunk "
        "per section (evidence IDs, citations and T41's labels unchanged)."
    )
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
```

Run: `uv run python -m pytest tests/plan_n/test_retrieval_comparison.py -q` → `9 passed`.

- [ ] **Step 4: Measure the threshold (local Ollama, read-only; before Task 3 freezes it)**

Run: `uv run python -m scripts.retrieval_comparison threshold`
Expected (measured on the scratch copy, 2026-10-19): 100 `THRESHOLD` lines, among them
`THRESHOLD 0.68: hit@5 26/27, answered-empty 18/20` and `THRESHOLD 0.69: hit@5 25/27, answered-empty 19/20`, and the
last line `CHOSEN: 0.68`. Write the whole output into the report. The value printed on `CHOSEN:` is what Task 3 writes
into `MIN_SIMILARITY_0013`; if it is not `0.68`, Task 3 uses the printed value, and every place this plan says 0.68
reads as that value (the live tests read it from the database, not from this plan). If it prints `CHOSEN: 0.00`, the
rule yields 0 and the helper returns 0 (ruling 6); the report says so.

- [ ] **Step 5: Gates and commit**

`check.py` → `1408 passed, 205 skipped`; `verify_handoff.py` exit 0; live gate → `1592 passed, 21 skipped`.

```bash
git add scripts/retrieval_comparison.py scripts/retrieval_baseline.py tests/plan_n/test_retrieval_comparison.py
git commit -m "feat: the retrieval comparison's statistics and the vector threshold rule, measured (T18)"
```

---

### Task 3: Revision 0013 — `app.embeddings`, `_min_similarity` and the vector branch

**Files:**
- Create: `migrations/app/versions/0013_embeddings.py`, `tests/plan_n/test_migration_0013.py`,
  `tests/e2e/test_migration_0013_live.py`
- Modify: `core/src/ops_core/privileges.py` (`GRANTS`, `RLS_TABLES`, `HELPER_FUNCTIONS`, the docstring),
  `core/src/ops_core/locking.py` (`NEVER_LOCKED`, `OWN_UNITS`), `core/src/ops_core/persistence.py` (`VECTOR_SEARCH`,
  `search_procedures`' mode and embedding, `Procedure`'s docstring), `mcp-read/src/ops_mcp_read/server.py` (the
  startup check only), `tests/plan_e/test_transitions_table.py` (`REVISIONS`),
  `tests/plan_k/test_mcp_write_startup.py` (`test_mcp_read_does_not_ask_for_0010`), `tests/e2e/conftest.py`
  (`purge_corpus`), `tests/e2e/test_migration_0011_live.py` (the vector call, `LATER_FUNCTIONS`),
  `tests/e2e/test_migration_0012_live.py` (the round trip), `tests/e2e/test_migration_0008_live.py` (the helpers)

**Requirements:** SA:431, SA:446, SA:461 (erratum 110), SA:474, SA:510-516; rulings 1, 5, 6, 7 and 17; erratum 111.

**Interfaces:**
- Consumes: revision 0012's `SEARCH_PROCEDURES_SCOPED`, `EXCERPT_CHARS_0012`, `INSTANT_0012` (its module, loaded by
  path); `privileges.Grant`, `grant_statements`, `rls_statements`, `function_grant_statements`;
  `embeddings.vector_literal`; `tests.plan_l.test_migration_0011.revision`, `statements`, `VERSIONS`;
  `tests.plan_j.test_mcp_read_startup.start`; `tests.plan_k.test_mcp_write_startup.MarkerConn`; the live helpers
  `stage`, `handle_for`, `clock`, `cleanup`, `DAY`, `APP_FUNCTIONS`, `refused`.
- Produces: `app.embeddings`; `app._min_similarity() RETURNS double precision`; `app.search_procedures_scoped(text,
  text, text, public.vector, text, integer, text)` (the argument types are `privileges.DEFINER_FUNCTIONS
  ["search_procedures_scoped"][0]`, unchanged since 0011; `RETURNS TABLE (corpus_version text, retrieved_at
  timestamptz, results jsonb)`, unchanged since 0012); `persistence.VECTOR_SEARCH`;
  `persistence.search_procedures(conn, *, handle, azp, query, asset_type, limit, mode="lexical", embedding=None)`.

- [ ] **Step 1: Write the failing revision tests**

Create `tests/plan_n/test_migration_0013.py`:

```python
"""Revision 0013 without a database (Plan N rulings 1 and 5-7).

Catches: an embeddings table granted to a role AM-20.2's corpus row does not name, without FORCE and the tenant policy,
without the chunk it belongs to, of another dimension, or under a vector index (approximate search); a search body that
changed anything of 0012's besides the three named changes (the lexical branch must stay byte for byte); a vector
branch whose filters are not the lexical branch's text, that reads before the argument rule or the clock, ranks
without the byte-order tie-break or the minimum similarity, answers other keys, or leaves out a permitted chunk
without an embedding silently; the old VECTOR_MODE_UNAVAILABLE refusal surviving; the stop-word return applying to
vector mode; a minimum similarity granted to anyone or kept anywhere but its helper; a DROP of the search (its return
type is unchanged, so its grants are kept); a downgrade that does not restore 0012's body exactly; a startup marker
that is not unique to 0013; and mcp-read starting on a database without 0013.
"""

from typing import Any

import pytest
from ops_core import locking, persistence, privileges

from tests.plan_e.test_transitions_table import REVISIONS
from tests.plan_j.test_mcp_read_startup import start
from tests.plan_k.test_mcp_write_startup import MarkerConn
from tests.plan_l.test_migration_0011 import VERSIONS, revision, statements

SEARCH = "search_procedures_scoped"
SEARCH_ARGS = privileges.DEFINER_FUNCTIONS[SEARCH][0]  # copied from the matrix, never retyped
CELLS = {"worker": privileges.Grant(sel=True, ins=True), "app_definer": privileges.Grant(sel=True)}
LEXICAL = "    -- The OR of the query's own lexemes"


def rev0013() -> Any:
    return revision("0013_embeddings")


def test_upgrade_creates_the_table_its_cells_and_policy_then_the_helper_and_the_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = rev0013()
    assert module.down_revision == "0012_asset_scope"
    seen = statements(module, "upgrade", monkeypatch)
    assert seen == [
        *module.SCHEMA_CHANGES,
        "REVOKE ALL ON app.embeddings FROM api, worker, sweeper, mcp_read, mcp_exec, operator, app_definer",
        "GRANT INSERT, SELECT ON app.embeddings TO worker",
        "GRANT SELECT ON app.embeddings TO app_definer",
        *privileges.rls_statements(("embeddings",), ("api", "worker", "sweeper", "app_definer")),
        module.MIN_SIMILARITY,
        "REVOKE ALL ON FUNCTION app._min_similarity() FROM PUBLIC",
        module.SEARCH_PROCEDURES_SCOPED,
        f"REVOKE ALL ON FUNCTION app.{SEARCH}({SEARCH_ARGS}) FROM PUBLIC",
        f"GRANT EXECUTE ON FUNCTION app.{SEARCH}({SEARCH_ARGS}) TO mcp_read",
    ]
    assert not any(s.startswith("DROP FUNCTION") for s in seen)  # the return type is unchanged: no DROP


def test_the_table_is_the_corpus_row_one_row_per_chunk_and_exact() -> None:
    module = rev0013()
    assert module.GRANTS_0013 == {"embeddings": CELLS} == {"embeddings": privileges.GRANTS["embeddings"]}
    assert "embeddings" in privileges.RLS_TABLES and "embeddings" not in privileges.SWEEPER_ALL
    assert "embeddings" in locking.NEVER_LOCKED
    ddl = module.SCHEMA_CHANGES[0]
    assert "PRIMARY KEY (tenant_id, evidence_id)" in ddl
    assert "FOREIGN KEY (tenant_id, evidence_id) REFERENCES app.chunks (tenant_id, evidence_id)" in ddl
    assert "embedding public.vector(768) NOT NULL" in ddl and "CHECK (dimension = 768)" in ddl
    assert "CHECK (model = 'nomic-embed-text')" in ddl and "input_sha256 text NOT NULL" in ddl
    everything = "\n".join(module.SCHEMA_CHANGES).upper()
    assert "CREATE INDEX" not in everything and "EXTENSION" not in everything  # exact search; the bootstrap's type


def test_the_search_is_0012s_body_with_exactly_the_three_changes() -> None:
    module = rev0013()
    body = module.SEARCH_PROCEDURES_SCOPED
    assert len(module.CHANGES_0013) == 3
    for old, new in reversed(module.CHANGES_0013):
        assert body.count(new) == 1, new[:60]
        body = body.replace(new, old)
    assert body == revision("0012_asset_scope").SEARCH_PROCEDURES_SCOPED
    with pytest.raises(RuntimeError, match="no longer carries"):
        module.changed(module.BODY_0012.replace("    v_query tsquery;\n", "    v_query tsquery; \n"))


def test_the_vector_branch_reuses_the_lexical_filters_verbatim_and_answers_the_same_keys() -> None:
    body = rev0013().SEARCH_PROCEDURES_SCOPED
    vector = body[body.index("    IF p_mode = 'vector' THEN\n") : body.index(LEXICAL)]
    lexical = body[body.index(LEXICAL) :]

    def between(text: str, start: str, end: str) -> str:
        return text[text.index(start) : text.index(end)]

    filters = between(lexical, "    WITH latest AS (\n", "    ), ranked AS (\n")
    assert between(vector, "    WITH latest AS (\n", "    ), scored AS (\n") == filters  # byte for byte (ruling 5)
    answer = between(lexical, "    SELECT coalesce(jsonb_agg(", "    INTO results FROM kept k;")
    assert answer.rstrip("\n") in vector  # the same result keys, excerpt bound and order
    assert "left(c.body, 8000) AS excerpt," in vector and "char_length(c.body) > 8000 AS excerpt_cut" in vector
    assert "1 - (e.embedding OPERATOR(public.<=>) p_query_embedding) AS rank" in vector  # cosine similarity
    assert "WHERE NOT r.unembedded AND r.rank > app._min_similarity()" in vector
    assert 'ORDER BY r.rank DESC, r.evidence_id COLLATE "C" LIMIT p_limit' in vector
    assert "LEFT JOIN embeddings e USING (tenant_id, evidence_id)" in vector
    assert (
        "DETAIL = 'EMBEDDINGS_INCOMPLETE'" in vector and "EXISTS (SELECT 1 FROM scored s WHERE s.unembedded)" in vector
    )
    assert "ts_rank_cd(" not in vector and "embedding" not in lexical  # each branch ranks its own way only


def test_the_argument_rule_comes_before_any_read_and_the_vector_branch_before_the_stop_words() -> None:
    body = rev0013().SEARCH_PROCEDURES_SCOPED
    member = body.index("AND m.role = 'requester' AND m.active")
    rule = body.index("IF p_mode IS NULL OR p_mode NOT IN ('lexical', 'vector')")
    first_read = min(body.index(f"FROM {t}") for t in ("corpus_ingestions", "document_states", "documents", "chunks"))
    clock = body.index("v_now := app.current_time()")
    instant = body.index("retrieved_at := v_now;")
    vector = body.index("    IF p_mode = 'vector' THEN\n")
    stop_words = body.index("results := '[]'::jsonb")
    assert member < rule < first_read < clock < instant < vector < stop_words
    assert "VECTOR_MODE_UNAVAILABLE" not in body and "TODO(T18)" not in body
    assert "(p_mode = 'lexical' AND p_query_embedding IS NOT NULL)" in body
    assert (
        "public.vector_dims(p_query_embedding) <> 768" in body and "public.vector_norm(p_query_embedding) = 0" in body
    )
    assert "OR p_query IS NULL OR char_length(p_query) NOT BETWEEN 1 AND 500" in body  # both modes
    for verb in ("INSERT", "UPDATE", "DELETE"):
        assert f"{verb} " not in body.split("$fn$")[1], verb  # a reader only


def test_the_minimum_similarity_is_a_helper_granted_to_nobody() -> None:
    module = rev0013()
    (helper, args, callers, body), (name, search_args, search_callers, _) = module.FUNCTIONS
    assert (helper, args, callers) == ("_min_similarity", "", ()) and privileges.HELPER_FUNCTIONS[helper] == ""
    assert (name, search_args, search_callers) == (SEARCH, SEARCH_ARGS, ("mcp_read",))
    assert privileges.DEFINER_FUNCTIONS[SEARCH] == (SEARCH_ARGS, ("mcp_read",))  # unchanged since 0011
    assert f"RETURN {module.MIN_SIMILARITY_0013};" in body and "IMMUTABLE" in body and "SECURITY DEFINER" not in body
    assert "ALTER FUNCTION app._min_similarity() OWNER TO app_definer;" in body
    assert 0.0 <= float(module.MIN_SIMILARITY_0013) < 1.0
    assert module.MIN_SIMILARITY_0013 not in module.SEARCH_PROCEDURES_SCOPED  # one place only


def test_the_downgrade_restores_0012s_search_then_drops_the_helper_and_the_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert statements(rev0013(), "downgrade", monkeypatch) == [
        revision("0012_asset_scope").SEARCH_PROCEDURES_SCOPED,
        f"REVOKE ALL ON FUNCTION app.{SEARCH}({SEARCH_ARGS}) FROM PUBLIC",
        f"GRANT EXECUTE ON FUNCTION app.{SEARCH}({SEARCH_ARGS}) TO mcp_read",
        "DROP FUNCTION app._min_similarity()",
        "DROP TABLE app.embeddings",
    ]


def test_the_startup_marker_is_only_in_0013s_search_and_the_older_markers_survive() -> None:
    body = rev0013().SEARCH_PROCEDURES_SCOPED
    assert persistence.VECTOR_SEARCH == (
        f"app.{SEARCH}({SEARCH_ARGS})",
        "e.embedding OPERATOR(public.<=>) p_query_embedding",
    )
    assert body.count(persistence.VECTOR_SEARCH[1]) == 1
    assert persistence.GOVERNED_CORPUS[1] in body and persistence.SEARCH_INSTANT[1] in body  # 0011's and 0012's
    for older in REVISIONS[: REVISIONS.index("0013_embeddings")]:
        assert persistence.VECTOR_SEARCH[1] not in (VERSIONS / f"{older}.py").read_text(encoding="utf-8"), older


def test_mcp_read_refuses_a_database_without_0013(monkeypatch: pytest.MonkeyPatch) -> None:
    at_0012 = {
        persistence.HANDLE_BINDING[1],
        persistence.GOVERNED_CORPUS[1],
        persistence.ASSET_SCOPE[1],
        persistence.SEARCH_INSTANT[1],
    }
    conn: Any = MarkerConn(at_0012)
    with pytest.raises(persistence.PersistenceError, match="predates this service"):
        start(monkeypatch, conn)
    assert conn.closed
    assert conn.asked[-1] == (persistence.VECTOR_SEARCH[1], persistence.VECTOR_SEARCH[0])
```

Edit 1 (`tests/plan_e/test_transitions_table.py`), replace:

```python
    "0012_asset_scope",
```

with:

```python
    "0012_asset_scope",
    "0013_embeddings",
```

Run: `uv run python -m pytest tests/plan_n/test_migration_0013.py -q`
Expected: a collection error from `tests/plan_e/test_transitions_table.py`'s module-level check
(`AssertionError` naming `REVISIONS`: `0013_embeddings.py` does not exist yet).

- [ ] **Step 2: The revision**

The search body is derived from 0012's frozen text by the three `CHANGES_0013` replacements (0012's pattern); the
complete resulting bodies are printed after the file for review. `MIN_SIMILARITY_0013` is the value Task 2 Step 4
printed (expected `"0.68"`).

Create `migrations/app/versions/0013_embeddings.py`:

```python
"""Exact vector retrieval (T18; Plan N rulings 1 and 5-7): `app.embeddings`, `_min_similarity` and the vector branch
of `search_procedures_scoped`.

Revision ID: 0013_embeddings
Revises: 0012_asset_scope

- `embeddings`: one row per stored chunk, keyed like the chunk (`tenant_id`, `evidence_id`) and referencing it, with
  the model, its digest, the dimension, the SHA-256 of the exact text that was embedded (the `search_document:` prefix
  included, so a stored row proves its prefix) and the `public.vector(768)` itself. A model change is a later
  revision's re-embedding, so the model and the dimension are pinned by CHECK. The cells are AM-20.2's corpus row
  (SA:431): `worker` inserts and reads (the operator command `scripts/skeleton.py embed`), `app_definer` reads, nobody
  else; ENABLE + FORCE RLS with the `tenant_isolation` policy (SA:510). No vector index: a sequential scan over the
  tenant's permitted chunks is exact by construction (ruling 7), and an index would make the search approximate.
- `_min_similarity()`: the vector branch keeps only a cosine similarity above it; chosen on the development queries by
  a rule fixed before measuring (ruling 6), so it is a development figure. One helper, as `_min_rank()`.
- `search_procedures_scoped` is re-created from revision 0012's own body with three textual changes and nothing else
  (the lexical branch stays byte for byte; a unit test reverses the changes and compares): the argument rule accepts
  `mode = 'vector'` with exactly one 768-dimension, non-zero query embedding and `mode = 'lexical'` with none, the
  `VECTOR_MODE_UNAVAILABLE` refusal goes, and a vector branch runs before the lexical one's stop-word return. The
  branch repeats the lexical branch's `latest`, `effective` and `permitted` text byte for byte (sliced from 0012's
  body here, so a filter cannot drift), ranks every permitted chunk by cosine similarity, `1 - (embedding <=> query)`,
  with the same tie-break, limit, excerpt and result keys, and refuses `EMBEDDINGS_INCOMPLETE` when a permitted chunk
  has no embedding, so nothing is left out silently. The return type is unchanged, so CREATE OR REPLACE replaces the
  body in place; PostgreSQL keeps a replaced function's owner and permissions, and the grant statements are applied
  again all the same.

The downgrade restores 0012's search body from 0012's own module, then drops the helper and the table (with its rows,
its grants and its policy); the `vector` extension stays, because the bootstrap made it.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic import op
from ops_core import privileges

revision = "0013_embeddings"
down_revision = "0012_asset_scope"
branch_labels = None
depends_on = None


def _applied(name: str) -> ModuleType:
    """An applied revision's module, loaded by path (the versions directory is not a package)."""
    spec = importlib.util.spec_from_file_location(f"applied_{name}", Path(__file__).with_name(f"{name}.py"))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"revision {name} is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REV0012 = _applied("0012_asset_scope")
HELPER_HEADER = "LANGUAGE plpgsql SET search_path = app, pg_temp"
SEARCH_ARGS = "text, text, text, public.vector, text, integer, text"
DIMENSION_0013 = 768  # nomic-embed-text's embedding length (data/embedding-pins.json), SA:461's vector(768)
# Plan N ruling 6: the largest value on a 0.01 grid at which vector hit@5 over the answerable development cases equals
# its value at 0, measured by `scripts.retrieval_comparison threshold` before this file was frozen (the live comparison
# re-measures it). A development figure: the holdout was never read (SA:657-659).
MIN_SIMILARITY_0013 = "0.68"

TABLES_0013 = ("embeddings",)
MAIN_GRANTEES_0013 = ("api", "worker", "sweeper", "mcp_read", "mcp_exec", "operator", "app_definer")
POLICY_ROLES_0013 = ("api", "worker", "sweeper", "app_definer")
# AM-20.2's corpus row (SA:431): the operator command inserts as the worker, only the definer reads.
GRANTS_0013: dict[str, dict[str, privileges.Grant]] = {
    "embeddings": {"worker": privileges.Grant(sel=True, ins=True), "app_definer": privileges.Grant(sel=True)},
}

SCHEMA_CHANGES = (
    (
        "CREATE TABLE app.embeddings ("
        " tenant_id uuid NOT NULL,"
        " evidence_id text NOT NULL,"
        " model text NOT NULL CHECK (model = 'nomic-embed-text'),"
        " model_digest text NOT NULL CHECK (model_digest ~ '^[a-f0-9]{64}$'),"
        f" dimension integer NOT NULL CHECK (dimension = {DIMENSION_0013}),"
        " input_sha256 text NOT NULL CHECK (input_sha256 ~ '^[a-f0-9]{64}$'),"
        f" embedding public.vector({DIMENSION_0013}) NOT NULL,"
        " embedded_at timestamptz NOT NULL DEFAULT now(),"
        " PRIMARY KEY (tenant_id, evidence_id),"
        " CONSTRAINT embeddings_chunk_fkey FOREIGN KEY (tenant_id, evidence_id)"
        " REFERENCES app.chunks (tenant_id, evidence_id))"
    ),
    "ALTER TABLE app.embeddings OWNER TO migrator",
)

MIN_SIMILARITY = f"""
CREATE OR REPLACE FUNCTION app._min_similarity() RETURNS double precision
{HELPER_HEADER} IMMUTABLE AS $fn$
BEGIN
    RETURN {MIN_SIMILARITY_0013};
END
$fn$;
ALTER FUNCTION app._min_similarity() OWNER TO app_definer;
"""


def _between(body: str, start: str, end: str) -> str:
    """The text of `body` from `start` up to, not including, `end`; each must occur exactly once."""
    if body.count(start) != 1 or body.count(end) != 1:
        raise RuntimeError("revision 0012's search_procedures_scoped no longer carries a text 0013 reuses")
    return body[body.index(start) : body.index(end)]


BODY_0012 = REV0012.SEARCH_PROCEDURES_SCOPED
EXCERPT_CHARS_0013 = REV0012.EXCERPT_CHARS_0012
# The lexical branch's filters (`latest`, `effective`, `permitted`) and its answer, reused verbatim (ruling 5).
FILTERS_0012 = _between(BODY_0012, "    WITH latest AS (\n", "    ), ranked AS (\n")
ANSWER_0012 = _between(BODY_0012, "    SELECT coalesce(jsonb_agg(", "    INTO results FROM kept k;\n")

# Revision 0012's body, changed in exactly these places; each `old` must occur once (checked before anything runs).
REFUSAL_AND_MODE_0012 = (
    "    IF p_mode = 'vector' THEN\n"
    "        -- TODO(T18): exact pgvector search over app.embeddings under the same filters (R034).\n"
    "        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'VECTOR_MODE_UNAVAILABLE';\n"
    "    END IF;\n"
    "    IF p_mode IS DISTINCT FROM 'lexical' OR p_query IS NULL OR char_length(p_query) NOT BETWEEN 1 AND 500\n"
)
ARGUMENTS_0013 = (
    "    -- T18 (Plan N ruling 5): a lexical call carries no embedding; a vector call carries one non-zero\n"
    "    -- embedding of the model's dimension (a function argument's type modifier is not enforced, and a zero\n"
    "    -- vector has no direction). The text query is required and bounded in both modes. Else BAD_ARGUMENT.\n"
    "    IF p_mode IS NULL OR p_mode NOT IN ('lexical', 'vector')\n"
    "       OR (p_mode = 'lexical' AND p_query_embedding IS NOT NULL)\n"
    "       OR (p_mode = 'vector' AND (p_query_embedding IS NULL\n"
    f"                                 OR public.vector_dims(p_query_embedding) <> {DIMENSION_0013}\n"
    "                                 OR public.vector_norm(p_query_embedding) = 0))\n"
    "       OR p_query IS NULL OR char_length(p_query) NOT BETWEEN 1 AND 500\n"
)
DECLARE_0012 = "    v_query tsquery;\n"
DECLARE_0013 = "    v_query tsquery;\n    v_incomplete boolean;\n"
INSTANT_0012 = REV0012.INSTANT_0012
VECTOR_BRANCH = (
    "    IF p_mode = 'vector' THEN\n"
    "        -- T18 (Plan N rulings 5-7): exact cosine search over the same permitted chunks. The filter text\n"
    "        -- below is the lexical branch's, byte for byte and at its indentation (a unit test compares the\n"
    "        -- two). No index: every permitted chunk is scored, so the order is exact. A permitted chunk without\n"
    "        -- an embedding refuses the call (EMBEDDINGS_INCOMPLETE): no section is left out silently.\n"
    + FILTERS_0012
    + "    ), scored AS (\n"
    "        SELECT c.evidence_id, c.document_id, c.version, c.section, c.content_sha256,\n"
    f"               left(c.body, {EXCERPT_CHARS_0013}) AS excerpt,\n"
    f"               char_length(c.body) > {EXCERPT_CHARS_0013} AS excerpt_cut, p.effective_from,\n"
    "               e.embedding IS NULL AS unembedded,\n"
    "               1 - (e.embedding OPERATOR(public.<=>) p_query_embedding) AS rank\n"
    "        FROM chunks c JOIN permitted p USING (tenant_id, document_id, version)\n"
    "        LEFT JOIN embeddings e USING (tenant_id, evidence_id)\n"
    "    ), kept AS (\n"
    "        -- `rank` is the cosine similarity here (ruling 6): another meaning than ts_rank_cd's, never\n"
    "        -- compared with it (BS:417). At or below the minimum dropped; the lexical branch's tie-break.\n"
    "        SELECT * FROM scored r WHERE NOT r.unembedded AND r.rank > app._min_similarity()\n"
    '        ORDER BY r.rank DESC, r.evidence_id COLLATE "C" LIMIT p_limit\n'
    "    )\n" + ANSWER_0012.removesuffix("\n") + ",\n"
    "           EXISTS (SELECT 1 FROM scored s WHERE s.unembedded)\n"
    "    INTO results, v_incomplete FROM kept k;\n"
    "        IF v_incomplete THEN\n"
    "            RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'EMBEDDINGS_INCOMPLETE';\n"
    "        END IF;\n"
    "        RETURN NEXT;\n"
    "        RETURN;\n"
    "    END IF;\n"
)
CHANGES_0013: tuple[tuple[str, str], ...] = (
    (DECLARE_0012, DECLARE_0013),
    (REFUSAL_AND_MODE_0012, ARGUMENTS_0013),
    (INSTANT_0012, INSTANT_0012 + VECTOR_BRANCH),
)


def changed(body: str) -> str:
    """Revision 0012's search body with this revision's changes applied.

    Raises:
        RuntimeError: a change's text is not in the body exactly once (0012's body is not the one this revision was
            written against).
    """
    for old, new in CHANGES_0013:
        if body.count(old) != 1:
            raise RuntimeError("revision 0012's search_procedures_scoped no longer carries a text 0013 changes")
        body = body.replace(old, new)
    return body


SEARCH_PROCEDURES_SCOPED = changed(BODY_0012)
# (name, argument types, callers, body): frozen here (N1); the newest-revision test reads this tuple.
FUNCTIONS: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("_min_similarity", "", (), MIN_SIMILARITY),
    ("search_procedures_scoped", SEARCH_ARGS, ("mcp_read",), SEARCH_PROCEDURES_SCOPED),
)
# What downgrade() re-creates, from the applied revision's own body: (name, args, callers, body).
RESTORED: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("search_procedures_scoped", SEARCH_ARGS, ("mcp_read",), BODY_0012),
)
DOWNGRADE = (
    "DROP FUNCTION app._min_similarity()",
    "DROP TABLE app.embeddings",  # its rows, grants and policy go with it
)


def upgrade() -> None:
    """The table, its frozen cells and policy, then the helper and the search (each body first, then its grants:
    REVOKE from PUBLIC, then EXECUTE to its callers, none for the helper)."""
    for statement in SCHEMA_CHANGES:
        op.execute(statement)
    for statement in privileges.grant_statements(TABLES_0013, GRANTS_0013, revokees=MAIN_GRANTEES_0013):
        op.execute(statement)
    for statement in privileges.rls_statements(TABLES_0013, POLICY_ROLES_0013):
        op.execute(statement)
    for name, args, callers, body in FUNCTIONS:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)


def downgrade() -> None:
    """Back to 0012: the search's 0012 body and its grants first (it no longer names the helper or the table), then
    the helper and the table."""
    for name, args, callers, body in RESTORED:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)
    for statement in DOWNGRADE:
        op.execute(statement)
```

For review, the bodies this revision executes (rendered from the file above on the scratch copy; the search exactly as
`changed()` renders it from 0012; nothing else in it differs from 0012):

```sql
CREATE OR REPLACE FUNCTION app.search_procedures_scoped(p_raw_handle text, p_client_azp text, p_query text,
                                                      p_query_embedding public.vector(768), p_asset_type text,
                                                      p_limit integer, p_mode text)
RETURNS TABLE (corpus_version text, retrieved_at timestamptz, results jsonb)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp SET app.tenant_id = '' AS $fn$
DECLARE
    v_handle record;
    v_now timestamptz;
    v_lexemes text[];
    v_query tsquery;
    v_incomplete boolean;
BEGIN
    PERFORM app._authority('search_procedures_scoped', ARRAY['mcp_read']);
    -- The handle decides the tenant (BS:362), never an argument: the lease FOR SHARE first, then the fence, expiry,
    -- revocation, azp and the read server, as resolve_invocation. The run-state allowlist stays in Python (erratum 19).
    SELECT * INTO v_handle FROM app._resolve_handle(p_raw_handle, p_client_azp, 'read');
    PERFORM set_config('app.tenant_id', v_handle.tenant_id::text, true);
    -- R028 (Plan M ruling 7): the run's requester must still hold an active requester membership in the run's
    -- tenant, or the call is refused as a dead handle is (SA:355). The run keeps no issuer: tenant, subject and
    -- role identify the row (erratum 105).
    IF NOT EXISTS (SELECT 1 FROM runs r JOIN memberships m ON m.tenant_id = r.tenant_id AND m.subject = r.requester
                   WHERE r.run_id = v_handle.run_id AND m.role = 'requester' AND m.active) THEN
        RAISE EXCEPTION 'handle_rejected' USING ERRCODE = 'OC008';
    END IF;
    -- T18 (Plan N ruling 5): a lexical call carries no embedding; a vector call carries one non-zero
    -- embedding of the model's dimension (a function argument's type modifier is not enforced, and a zero
    -- vector has no direction). The text query is required and bounded in both modes. Else BAD_ARGUMENT.
    IF p_mode IS NULL OR p_mode NOT IN ('lexical', 'vector')
       OR (p_mode = 'lexical' AND p_query_embedding IS NOT NULL)
       OR (p_mode = 'vector' AND (p_query_embedding IS NULL
                                 OR public.vector_dims(p_query_embedding) <> 768
                                 OR public.vector_norm(p_query_embedding) = 0))
       OR p_query IS NULL OR char_length(p_query) NOT BETWEEN 1 AND 500
       OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 8
       OR (p_asset_type IS NOT NULL AND char_length(p_asset_type) NOT BETWEEN 1 AND 40) THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'BAD_ARGUMENT';
    END IF;
    -- The tenant's latest ingestion names the corpus it searches; "none" before the first one (Plan L ruling 17).
    corpus_version := coalesce((SELECT i.corpus_version FROM corpus_ingestions i
                                WHERE i.tenant_id = v_handle.tenant_id ORDER BY i.seq DESC LIMIT 1), 'none');
    v_now := app.current_time();  -- the test clock in the test profile; read after the lease lock (SA:157)
    retrieved_at := v_now;  -- the instant permission was decided; the tool stamps it (Plan M ruling 3)
    IF p_mode = 'vector' THEN
        -- T18 (Plan N rulings 5-7): exact cosine search over the same permitted chunks. The filter text
        -- below is the lexical branch's, byte for byte and at its indentation (a unit test compares the
        -- two). No index: every permitted chunk is scored, so the order is exact. A permitted chunk without
        -- an embedding refuses the call (EMBEDDINGS_INCOMPLETE): no section is left out silently.
    WITH latest AS (
        -- AM-20 principle 2: the latest state is the highest seq, never a timestamp.
        SELECT DISTINCT ON (s.tenant_id, s.document_id, s.version)
               s.tenant_id, s.document_id, s.version, s.status, s.effective_from, s.effective_to
        FROM document_states s
        ORDER BY s.tenant_id, s.document_id, s.version, s.seq DESC
    ), effective AS (
        SELECT d.tenant_id, d.document_id, d.version, d.supersedes, d.asset_family, l.effective_from
        FROM documents d JOIN latest l USING (tenant_id, document_id, version)
        WHERE l.status = 'approved' AND l.effective_from <= v_now AND (l.effective_to IS NULL OR v_now < l.effective_to)
    ), permitted AS (
        -- Retired versions never come back (ruling 7, round 1): a later version that has left draft and reached its
        -- own effective_from retires every earlier one, whatever happens to it afterwards (revoked, expired).
        SELECT e.* FROM effective e
        WHERE NOT EXISTS (SELECT 1 FROM latest n WHERE n.tenant_id = e.tenant_id AND n.document_id = e.document_id
                                                    AND n.version::integer > e.version::integer
                                                    AND n.status <> 'draft' AND n.effective_from <= v_now)
          AND (p_asset_type IS NULL OR e.asset_family IS NULL OR e.asset_family = p_asset_type)
    ), scored AS (
        SELECT c.evidence_id, c.document_id, c.version, c.section, c.content_sha256,
               left(c.body, 8000) AS excerpt,
               char_length(c.body) > 8000 AS excerpt_cut, p.effective_from,
               e.embedding IS NULL AS unembedded,
               1 - (e.embedding OPERATOR(public.<=>) p_query_embedding) AS rank
        FROM chunks c JOIN permitted p USING (tenant_id, document_id, version)
        LEFT JOIN embeddings e USING (tenant_id, evidence_id)
    ), kept AS (
        -- `rank` is the cosine similarity here (ruling 6): another meaning than ts_rank_cd's, never
        -- compared with it (BS:417). At or below the minimum dropped; the lexical branch's tie-break.
        SELECT * FROM scored r WHERE NOT r.unembedded AND r.rank > app._min_similarity()
        ORDER BY r.rank DESC, r.evidence_id COLLATE "C" LIMIT p_limit
    )
    SELECT coalesce(jsonb_agg(jsonb_build_object('evidence_id', k.evidence_id, 'document_id', k.document_id,
                                                 'version', k.version, 'section', k.section,
                                                 'content_sha256', k.content_sha256, 'excerpt', k.excerpt,
                                                 'effective_from', k.effective_from, 'rank', k.rank,
                                                 'excerpt_cut', k.excerpt_cut)
                              ORDER BY k.rank DESC, k.evidence_id COLLATE "C"), '[]'::jsonb),
           EXISTS (SELECT 1 FROM scored s WHERE s.unembedded)
    INTO results, v_incomplete FROM kept k;
        IF v_incomplete THEN
            RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'EMBEDDINGS_INCOMPLETE';
        END IF;
        RETURN NEXT;
        RETURN;
    END IF;
    -- The OR of the query's own lexemes (Plan L ruling 18), so a whole user message still matches: anything but
    -- a-z and 0-9 becomes a space first, so every lexeme is a plain word the 'simple' parser passes through unchanged.
    v_lexemes := tsvector_to_array(to_tsvector('english', regexp_replace(lower(p_query), '[^a-z0-9]+', ' ', 'g')));
    IF cardinality(v_lexemes) = 0 THEN
        results := '[]'::jsonb;  -- only stop words: nothing to match, not an error
        RETURN NEXT;
        RETURN;
    END IF;
    v_query := to_tsquery('simple', array_to_string(v_lexemes, ' | '));
    WITH latest AS (
        -- AM-20 principle 2: the latest state is the highest seq, never a timestamp.
        SELECT DISTINCT ON (s.tenant_id, s.document_id, s.version)
               s.tenant_id, s.document_id, s.version, s.status, s.effective_from, s.effective_to
        FROM document_states s
        ORDER BY s.tenant_id, s.document_id, s.version, s.seq DESC
    ), effective AS (
        SELECT d.tenant_id, d.document_id, d.version, d.supersedes, d.asset_family, l.effective_from
        FROM documents d JOIN latest l USING (tenant_id, document_id, version)
        WHERE l.status = 'approved' AND l.effective_from <= v_now AND (l.effective_to IS NULL OR v_now < l.effective_to)
    ), permitted AS (
        -- Retired versions never come back (ruling 7, round 1): a later version that has left draft and reached its
        -- own effective_from retires every earlier one, whatever happens to it afterwards (revoked, expired).
        SELECT e.* FROM effective e
        WHERE NOT EXISTS (SELECT 1 FROM latest n WHERE n.tenant_id = e.tenant_id AND n.document_id = e.document_id
                                                    AND n.version::integer > e.version::integer
                                                    AND n.status <> 'draft' AND n.effective_from <= v_now)
          AND (p_asset_type IS NULL OR e.asset_family IS NULL OR e.asset_family = p_asset_type)
    ), ranked AS (
        SELECT c.evidence_id, c.document_id, c.version, c.section, c.content_sha256,
               left(c.body, 8000) AS excerpt,
               char_length(c.body) > 8000 AS excerpt_cut, p.effective_from, ts_rank_cd(c.search, v_query) AS rank
        FROM chunks c JOIN permitted p USING (tenant_id, document_id, version)
        WHERE c.search @@ v_query
    ), kept AS (
        -- Ranks at or below the minimum dropped; the byte-order tie-break makes a retry cite the same evidence
        -- whatever the database's collation (BUILD_SPEC section 6).
        SELECT * FROM ranked r WHERE r.rank > app._min_rank()
        ORDER BY r.rank DESC, r.evidence_id COLLATE "C" LIMIT p_limit
    )
    SELECT coalesce(jsonb_agg(jsonb_build_object('evidence_id', k.evidence_id, 'document_id', k.document_id,
                                                 'version', k.version, 'section', k.section,
                                                 'content_sha256', k.content_sha256, 'excerpt', k.excerpt,
                                                 'effective_from', k.effective_from, 'rank', k.rank,
                                                 'excerpt_cut', k.excerpt_cut)
                              ORDER BY k.rank DESC, k.evidence_id COLLATE "C"), '[]'::jsonb)
    INTO results FROM kept k;
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION app.search_procedures_scoped(text, text, text, public.vector, text, integer, text) OWNER TO app_definer;
```

```sql
CREATE OR REPLACE FUNCTION app._min_similarity() RETURNS double precision
LANGUAGE plpgsql SET search_path = app, pg_temp IMMUTABLE AS $fn$
BEGIN
    RETURN 0.68;
END
$fn$;
ALTER FUNCTION app._min_similarity() OWNER TO app_definer;
```

- [ ] **Step 3: The matrix, the lock order, persistence and mcp-read's startup check**

Edit 2 (`core/src/ops_core/privileges.py`), replace:

```python
operator_resolutions → T22, embeddings → T18) add their rows. Ten departures from the printed
```

with:

```python
operator_resolutions → T22) add their rows; T18 added `embeddings`. Ten departures from the printed
```

Edit 3 (`core/src/ops_core/privileges.py`), replace:

```python
    "chunks": {"worker": _SI, DEFINER_ROLE: _S},
```

with:

```python
    "chunks": {"worker": _SI, DEFINER_ROLE: _S},
    # T18 (Plan N ruling 1): AM-20.2's corpus row (SA:431) for the embeddings; `scripts/skeleton.py embed` inserts as
    # the worker, and only search_procedures_scoped reads them.
    "embeddings": {"worker": _SI, DEFINER_ROLE: _S},
```

Edit 4 (`core/src/ops_core/privileges.py`), replace:

```python
    "chunks",
```

with:

```python
    "chunks",
    "embeddings",  # T18: SA:510 names it
```

Edit 5 (`core/src/ops_core/privileges.py`), replace:

```python
    "_min_rank": "",  # T17: the search's minimum rank, 0.25 (Plan L ruling 18, round 1)
```

with:

```python
    "_min_rank": "",  # T17: the search's minimum rank, 0.25 (Plan L ruling 18, round 1)
    "_min_similarity": "",  # T18: the vector branch's minimum cosine similarity (Plan N ruling 6)
```

Edit 6 (`core/src/ops_core/locking.py`), replace:

```python
# (conftest `purge_corpus`).
NEVER_LOCKED: Final = frozenset(
    {"conversations", "transitions", "corpus_ingestions", "documents", "document_states", "chunks"}
```

with:

```python
# (conftest `purge_corpus`). T18 (revision 0013): `embeddings` likewise; its insert takes FOR KEY SHARE on the
# existing `chunks` row it names, which nothing updates or deletes either.
NEVER_LOCKED: Final = frozenset(
    {"conversations", "transitions", "corpus_ingestions", "documents", "document_states", "chunks", "embeddings"}
```

Edit 7 (`core/src/ops_core/locking.py`), replace:

```python
    "worker corpus ingestion (ingest.ingest)": ("tenants",),
```

with:

```python
    "worker corpus ingestion (ingest.ingest)": ("tenants",),
    # T18: the embedding rows' only lock is the foreign key's share on their never-locked `chunks` parent.
    "worker corpus embedding (embed.embed)": (),
```

Edit 8 (`core/src/ops_core/persistence.py`), replace:

```python
from typing import Any, Final
```

with:

```python
from typing import Any, Final, Literal
```

Edit 9 (`core/src/ops_core/persistence.py`), replace:

```python
from ops_core.canonical import sha256_hex
```

with:

```python
from ops_core.canonical import sha256_hex
from ops_core.embeddings import vector_literal
```

Edit 10 (`core/src/ops_core/persistence.py`), replace:

```python
# function keeps this text or changes it here in the same commit (revision 0012 keeps it: the ranking is unchanged).
```

with:

```python
# function keeps this text or changes it here in the same commit (revisions 0012 and 0013 keep it: the lexical
# ranking is unchanged).
```

Edit 11 (`core/src/ops_core/persistence.py`), replace:

```python
    "retrieved_at := v_now",
```

with:

```python
    "retrieved_at := v_now",
)
# Revision 0013 (T18): `search_procedures_scoped` ranks by cosine similarity over `app.embeddings` in vector mode.
# mcp-read sends `mode='vector'` with a query embedding, so it refuses to start without it (Plan N ruling 1). The same
# rule: a later revision that re-creates the function keeps this text or changes it here in the same commit.
VECTOR_SEARCH: Final = (
    "app.search_procedures_scoped(text, text, text, public.vector, text, integer, text)",
    "e.embedding OPERATOR(public.<=>) p_query_embedding",
```

Edit 12 (`core/src/ops_core/persistence.py`), replace:

```python
    """One permitted section, as `search_procedures_scoped` ranked it. `rank` is `ts_rank_cd`'s score: it orders the
    results of one query and means nothing across queries or methods (docs/retrieval.md); no tool result carries it."""
```

with:

```python
    """One permitted section, as `search_procedures_scoped` ranked it. `rank` is `ts_rank_cd`'s score in lexical mode
    and the cosine similarity in vector mode (T18): it orders the results of one query and means nothing across queries
    or methods (docs/retrieval.md, BS:417); no tool result carries it."""
```

Edit 13 (`core/src/ops_core/persistence.py`), replace:

```python
    conn: Conn, *, handle: str, azp: str, query: str, asset_type: str | None, limit: int
) -> Procedures:
    """Lexical search over the handle's tenant's approved, effective chunks (SA:461, T17); the embedding stays NULL
    and the mode `lexical` until T18. The handle never reaches a log.
```

with:

```python
    conn: Conn,
    *,
    handle: str,
    azp: str,
    query: str,
    asset_type: str | None,
    limit: int,
    mode: Literal["lexical", "vector"] = "lexical",
    embedding: Sequence[float] | None = None,
) -> Procedures:
    """Search over the handle's tenant's approved, effective chunks (SA:461): lexical (T17) without an embedding, or
    exact vector search (T18) with the query's `search_query:` embedding, which travels as pgvector's text form cast
    in SQL (erratum 109). The handle never reaches a log.
```

Edit 14 (`core/src/ops_core/persistence.py`), replace:

```python
        Refused: an argument outside the tool's bounds (`BAD_ARGUMENT`).
    """
    row = await _call(
        conn,
        "SELECT * FROM app.search_procedures_scoped(%s, %s, %s, NULL, %s, %s, 'lexical')",
        (handle, azp, query, asset_type, limit),
```

with:

```python
        Refused: an argument outside the tool's bounds or the mode's rule (`BAD_ARGUMENT`), or, in vector mode, a
            permitted chunk without an embedding (`EMBEDDINGS_INCOMPLETE`, revision 0013).
    """
    literal = None if embedding is None else vector_literal(embedding)
    row = await _call(
        conn,
        "SELECT * FROM app.search_procedures_scoped(%s, %s, %s, %s::public.vector, %s, %s, %s)",
        (handle, azp, query, literal, asset_type, limit, mode),
```

Edit 15 (`mcp-read/src/ops_mcp_read/server.py`), replace:

```python
                await persistence.assert_function_text(conn, *persistence.SEARCH_INSTANT)  # 0012 (T16)
```

with:

```python
                await persistence.assert_function_text(conn, *persistence.SEARCH_INSTANT)  # 0012 (T16)
                await persistence.assert_function_text(conn, *persistence.VECTOR_SEARCH)  # 0013 (T18)
```

Edit 16 (`tests/plan_k/test_mcp_write_startup.py`), replace:

```python
    )
    conn: Any = MarkerConn({marker for _, marker in present})  # every mcp-read revision through 0012 (T16)
    start(monkeypatch, conn)
    assert all(persistence.WRITE_PATH[1] not in asked for asked in conn.asked)
    for signature, marker in present:  # mcp-read asks for each of its own revisions' markers, 0012's two included
```

with:

```python
        persistence.VECTOR_SEARCH,
    )
    conn: Any = MarkerConn({marker for _, marker in present})  # every mcp-read revision through 0013 (T18)
    start(monkeypatch, conn)
    assert all(persistence.WRITE_PATH[1] not in asked for asked in conn.asked)
    for signature, marker in present:  # mcp-read asks for each of its own revisions' markers, 0013's included
```

Run: `uv run python -m pytest tests/plan_n/test_migration_0013.py tests/plan_e tests/plan_h/test_locking.py
tests/plan_k/test_mcp_write_startup.py tests/plan_m tests/plan_l tests/plan_j -q`
Expected: all passing; `tests/plan_n/test_migration_0013.py` `9 passed`.

- [ ] **Step 4: The live definer tests and the live edits**

Create `tests/e2e/test_migration_0013_live.py`:

```python
"""Revision 0013 against the per-session test database (OPS_LIVE=1; Plan N rulings 1, 5, 6 and 7): the vector branch of
`search_procedures_scoped` called by its real caller, `mcp_read`, over rows and synthetic vectors the superuser stages
in random tenants (the real embeddings are tests/e2e/test_vector_retrieval_live.py's).

Catches: a vector answer that is not ordered by cosine similarity, breaks ties other than by evidence_id in byte
order, keeps a similarity at or below `app._min_similarity()`, or returns a superseded, draft, not-yet-effective or
other-family section (the same filters as lexical); another tenant's embedding used; a vector call without an
embedding, with another dimension or a zero vector, or a lexical call with one, answered instead of refused
BAD_ARGUMENT; a permitted chunk without an embedding silently left out instead of EMBEDDINGS_INCOMPLETE (while a draft
chunk without one changes nothing); an empty corpus answered other than `[]`; any role but the worker able to write
an embedding, the worker able to change or delete one or to write another tenant's; and a downgrade that leaves the
table or the helper behind, does not restore 0012's body with the same grant, or does not come back exactly.
"""

import importlib.util
import math
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from ops_core import embeddings, persistence, settings
from ops_core.settings import Profile, Role

from tests.e2e.test_definers_run_path_live import refused
from tests.e2e.test_migration_0011_live import APP_FUNCTIONS, DAY, cleanup, clock, handle_for, stage

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
AZP = "ops-worker"
CALL = "SELECT * FROM app.search_procedures_scoped(%s, %s, %s, %s::public.vector, %s, %s, %s)"


def direction(similarity: float, axis: int = 1) -> list[float]:
    """A unit vector whose cosine with the first axis is `similarity`, turned towards `axis` (768 dimensions)."""
    vector = [0.0] * embeddings.DIMENSION
    vector[0] = similarity
    vector[axis] = math.sqrt(1 - similarity * similarity)
    return vector


QUERY = direction(1.0)  # the first axis


async def embed_rows(app_conn: persistence.Conn, tenant: UUID, vectors: dict[str, Sequence[float]]) -> None:
    """Synthetic embedding rows written by the superuser (Plan N ruling 13), one per staged evidence ID."""
    for evidence_id, vector in vectors.items():
        await app_conn.execute(
            "INSERT INTO app.embeddings (tenant_id, evidence_id, model, model_digest, dimension, input_sha256,"
            " embedding) VALUES (%s, %s, 'nomic-embed-text', %s, 768, %s, %s::public.vector)",
            (tenant, evidence_id, "0" * 64, "1" * 64, embeddings.vector_literal(vector)),
        )


async def minimum(app_conn: persistence.Conn) -> float:
    cur = await app_conn.execute("SELECT app._min_similarity() AS m")
    return float((await cur.fetchone() or {})["m"])


async def vector_ids(mcp_read: persistence.Conn, handle: str, **over: Any) -> list[tuple[str, float]]:
    answer = await persistence.search_procedures(
        mcp_read,
        handle=handle,
        azp=AZP,
        query="any text",
        asset_type=over.get("asset_type"),
        limit=over.get("limit", 8),
        mode="vector",
        embedding=over.get("embedding", QUERY),
    )
    return [(hit.evidence_id, hit.rank) for hit in answer.results]


async def test_vector_mode_ranks_the_permitted_chunks_by_cosine_with_lexicals_filters(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    mcp_read = await role_conn(Role.MCP_READ)
    tenant, run, handle = await handle_for(app_conn, role_conn, None)
    other, other_run, _ = await handle_for(app_conn, role_conn, None)
    try:
        now = await clock(app_conn)
        low = await minimum(app_conn)
        assert 0.0 <= low <= 0.8  # the geometry below needs room above the minimum (0.68 when frozen)
        old, recent = [("approved", now - 30 * DAY, None)], [("approved", now - DAY, None)]
        await stage(
            app_conn,
            tenant,
            [
                {"id": "BEST", "version": "1", "states": old, "section": "best"},
                {"id": "TIE-B", "version": "1", "states": old, "section": "tie"},
                {"id": "TIE-A", "version": "1", "states": old, "section": "tie"},
                {"id": "EDGE", "version": "1", "states": old, "section": "edge"},
                {"id": "BELOW", "version": "1", "states": old, "section": "below"},
                {"id": "PUMP-ONLY", "version": "1", "states": old, "section": "pump", "family": "pump"},
                {"id": "RETIRED", "version": "1", "states": old, "section": "old"},
                {"id": "RETIRED", "version": "2", "supersedes": "1", "states": recent, "section": "new"},
                {"id": "DRAFT", "version": "1", "states": [("draft", now - DAY, None)], "section": "draft"},
                {"id": "LATER", "version": "1", "states": [("approved", now + DAY, None)], "section": "later"},
            ],
        )
        await embed_rows(
            app_conn,
            tenant,
            {
                "BEST:v1:best": QUERY,
                "TIE-B:v1:tie": direction(low + 0.1, 2),
                "TIE-A:v1:tie": direction(low + 0.1, 3),  # the same similarity: byte order decides
                "EDGE:v1:edge": direction(low + 0.02),
                "BELOW:v1:below": direction(low - 0.02),  # under the minimum: dropped
                "PUMP-ONLY:v1:pump": direction(0.99),
                "RETIRED:v1:old": QUERY,  # retired by v2, whatever its similarity
                "RETIRED:v2:new": direction(0.95),
                "DRAFT:v1:draft": QUERY,
                "LATER:v1:later": QUERY,
            },
        )
        await stage(app_conn, other, [{"id": "FOREIGN", "version": "1", "states": old, "section": "foreign"}])
        await embed_rows(app_conn, other, {"FOREIGN:v1:foreign": QUERY})  # another tenant's: never seen
        found = await vector_ids(mcp_read, handle)
        assert [e for e, _ in found] == [
            "BEST:v1:best",
            "PUMP-ONLY:v1:pump",  # no asset type asked: any family
            "RETIRED:v2:new",
            "TIE-A:v1:tie",
            "TIE-B:v1:tie",
            "EDGE:v1:edge",
        ]
        assert found[0][1] == pytest.approx(1.0, abs=1e-6) and found[-1][1] == pytest.approx(low + 0.02, abs=1e-5)
        assert [e for e, _ in await vector_ids(mcp_read, handle, asset_type="valve", limit=2)] == [
            "BEST:v1:best",
            "RETIRED:v2:new",
        ]
        assert await vector_ids(mcp_read, handle, embedding=direction(0.0, 5)) == []  # nothing similar enough
        lexical = await persistence.search_procedures(
            mcp_read, handle=handle, azp=AZP, query="turbine", asset_type=None, limit=8
        )
        vector = await persistence.search_procedures(
            mcp_read, handle=handle, azp=AZP, query="turbine", asset_type=None, limit=8, mode="vector", embedding=QUERY
        )
        # The same answer shape in both modes (ruling 5): corpus version, instant and every key but the score's meaning.
        assert (
            (vector.corpus_version, vector.truncated)
            == (lexical.corpus_version, lexical.truncated)
            == ("live-1", False)
        )
        assert abs((vector.retrieved_at - lexical.retrieved_at).total_seconds()) < 5
    finally:
        await cleanup(app_conn, [run, other_run], [tenant, other])


async def test_arguments_completeness_and_the_empty_corpus(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    mcp_read = await role_conn(Role.MCP_READ)
    tenant, run, handle = await handle_for(app_conn, role_conn, None)
    try:
        assert await vector_ids(mcp_read, handle) == []  # no corpus yet: [] as lexical answers
        now = await clock(app_conn)
        old = [("approved", now - 30 * DAY, None)]
        await stage(
            app_conn,
            tenant,
            [
                {"id": "KEPT", "version": "1", "states": old},
                {"id": "MISSING", "version": "1", "states": old},
                {"id": "DRAFT", "version": "1", "states": [("draft", now - DAY, None)]},
            ],
        )
        await embed_rows(app_conn, tenant, {"KEPT:v1:turbine": QUERY})
        with pytest.raises(persistence.Refused, match="EMBEDDINGS_INCOMPLETE"):  # never a silent omission
            await vector_ids(mcp_read, handle)
        await embed_rows(app_conn, tenant, {"MISSING:v1:turbine": direction(0.99)})
        assert [e for e, _ in await vector_ids(mcp_read, handle)] == ["KEPT:v1:turbine", "MISSING:v1:turbine"]
        # The draft has no embedding and is not permitted: it changes nothing.
        literal = embeddings.vector_literal
        for args in (
            (handle, AZP, "turbine", None, None, 5, "vector"),  # no embedding
            (handle, AZP, "turbine", literal([1.0, 0.0, 0.0]), None, 5, "vector"),  # three dimensions
            (handle, AZP, "turbine", literal([0.0] * 768), None, 5, "vector"),  # no direction
            (handle, AZP, "turbine", literal(QUERY), None, 5, "lexical"),  # an embedding in lexical mode
            (handle, AZP, "", literal(QUERY), None, 5, "vector"),  # the text query is still bounded
            (handle, AZP, "turbine", literal(QUERY), None, 9, "vector"),
            (handle, AZP, "turbine", literal(QUERY), None, 5, "approximate"),
        ):
            with pytest.raises(persistence.Refused, match="BAD_ARGUMENT"):
                await persistence._call(mcp_read, CALL, args)
        with pytest.raises(persistence.HandleRejected):  # the handle is checked before any argument
            await persistence._call(mcp_read, CALL, ("not-a-handle", AZP, "turbine", literal(QUERY), None, 5, "vector"))
    finally:
        await cleanup(app_conn, [run], [tenant])


async def test_only_the_worker_writes_embeddings_and_only_its_tenants(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    tenant, run, _ = await handle_for(app_conn, role_conn, None)
    other, other_run, _ = await handle_for(app_conn, role_conn, None)
    try:
        now = await clock(app_conn)
        await stage(app_conn, tenant, [{"id": "OWN", "version": "1", "states": [("approved", now - DAY, None)]}])
        await stage(app_conn, other, [{"id": "THEIRS", "version": "1", "states": [("approved", now - DAY, None)]}])
        insert = (
            "INSERT INTO app.embeddings (tenant_id, evidence_id, model, model_digest, dimension, input_sha256,"
            " embedding) VALUES (%s, %s, 'nomic-embed-text', %s, 768, %s, %s::public.vector)"
        )
        row = (tenant, "OWN:v1:turbine", "0" * 64, "1" * 64, embeddings.vector_literal(QUERY))
        for role in (Role.API, Role.SWEEPER, Role.MCP_READ, Role.MCP_EXEC, Role.OPERATOR):
            assert await refused(await role_conn(role), "SELECT 1 FROM app.embeddings", ()) == "42501", role
            assert await refused(await role_conn(role), insert, row) == "42501", role
        worker = await role_conn(Role.WORKER)
        async with worker.transaction():
            await persistence.set_tenant(worker, tenant)
            await worker.execute(insert, row)  # AM-20.2's ingestion cell (SA:431)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):  # RLS WITH CHECK: another tenant's row
            async with worker.transaction():
                await persistence.set_tenant(worker, tenant)
                await worker.execute(insert, (other, "THEIRS:v1:turbine", *row[2:]))
        cur = await worker.execute("SELECT count(*) AS n FROM app.embeddings")
        assert (await cur.fetchone() or {})["n"] == 0  # no tenant set: RLS admits nothing
        for statement in ("UPDATE app.embeddings SET dimension = 768", "DELETE FROM app.embeddings"):
            assert await refused(worker, statement, ()) == "42501", statement  # append-only
    finally:
        await cleanup(app_conn, [run, other_run], [tenant, other])


def revision_0013() -> Any:
    path = Path(__file__).resolve().parents[2] / "migrations" / "app" / "versions" / "0013_embeddings.py"
    spec = importlib.util.spec_from_file_location("live_rev_0013", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def snapshot(conn: persistence.Conn) -> dict[str, dict[str, Any]]:
    cur = await conn.execute(APP_FUNCTIONS)
    return {row["signature"]: {k: v for k, v in row.items() if k != "signature"} for row in await cur.fetchall()}


async def test_the_round_trip_restores_0012(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    from scripts.skeleton import downgrade, migrate

    module = revision_0013()
    search = f"app.search_procedures_scoped({module.SEARCH_ARGS})"
    superuser = settings.superuser_postgres()
    mcp_read = await role_conn(Role.MCP_READ)
    head = await snapshot(app_conn)
    assert any(s.startswith("app._min_similarity(") for s in head)
    await persistence.assert_function_text(mcp_read, *persistence.VECTOR_SEARCH)  # mcp-read starts on the head
    try:
        downgrade("app", superuser, "0012_asset_scope")
        cur = await app_conn.execute("SELECT to_regclass('app.embeddings') IS NULL AS gone")
        assert (await cur.fetchone() or {})["gone"]
        after = await snapshot(app_conn)
        assert set(after) == {s for s in head if not s.startswith("app._min_similarity(")}
        cur = await app_conn.execute("SELECT prosrc FROM pg_proc WHERE oid = %s::regprocedure", (search,))
        assert (await cur.fetchone() or {})["prosrc"] == module.BODY_0012.split("$fn$")[1]
        for signature, details in after.items():
            if signature.startswith("app.search_procedures_scoped("):
                assert details["acl"] == head[signature]["acl"]  # CREATE OR REPLACE kept the grant, both ways
            else:
                assert details == head[signature], signature
        with pytest.raises(persistence.PersistenceError, match="predates this service"):
            await persistence.assert_function_text(mcp_read, *persistence.VECTOR_SEARCH)  # mcp-read refuses 0012
    finally:
        assert migrate(Profile.TEST) == 0  # every later test needs the head (the `embedded` fixture re-embeds)
    assert await snapshot(app_conn) == head
```

Edit 17 (`tests/e2e/conftest.py`), replace:

```python
    """Remove a test tenant's corpus rows (T17), children first; the seeded tenants' corpus is the ingested one and
    stays."""
    if str(tenant_id) in SEEDED_TENANTS:
        return
    async with conn.transaction():
        for table in ("chunks", "document_states", "documents", "corpus_ingestions"):
```

with:

```python
    """Remove a test tenant's corpus rows (T17) and their embeddings (T18), children first; the seeded tenants' corpus
    is the ingested one and stays."""
    if str(tenant_id) in SEEDED_TENANTS:
        return
    async with conn.transaction():
        for table in ("embeddings", "chunks", "document_states", "documents", "corpus_ingestions"):
```

Edit 18 (`tests/e2e/test_migration_0011_live.py`), replace:

```python
        with pytest.raises(persistence.Refused, match="VECTOR_MODE_UNAVAILABLE"):
```

with:

```python
        # T18 (revision 0013): vector mode exists, and without its embedding it is the one argument refusal.
        with pytest.raises(persistence.Refused, match="BAD_ARGUMENT"):
```

Edit 19 (`tests/e2e/test_migration_0011_live.py`), replace:

```python
LATER_FUNCTIONS = ("app.asset_scope(",)  # revision 0012's own function (T16): a downgrade to 0010 drops it too
```

with:

```python
# Later revisions' own functions, which a downgrade to 0010 drops too: 0012's (T16) and 0013's helper (T18).
LATER_FUNCTIONS = ("app.asset_scope(", "app._min_similarity(")
```

Edit 20 (`tests/e2e/test_migration_0012_live.py`), replace:

```python
        assert not any(s.startswith("app.asset_scope(") for s in after)
        cur = await app_conn.execute("SELECT prosrc FROM pg_proc WHERE oid = %s::regprocedure", (search,))
        assert (await cur.fetchone() or {})["prosrc"] == module.REV0011.SEARCH_PROCEDURES_SCOPED.split("$fn$")[1]
        assert set(after) == {s for s in head if not s.startswith("app.asset_scope(")}
```

with:

```python
        later = ("app.asset_scope(", "app._min_similarity(")  # 0012's own function and 0013's helper (T18)
        assert not any(s.startswith(later) for s in after)
        cur = await app_conn.execute("SELECT prosrc FROM pg_proc WHERE oid = %s::regprocedure", (search,))
        assert (await cur.fetchone() or {})["prosrc"] == module.REV0011.SEARCH_PROCEDURES_SCOPED.split("$fn$")[1]
        assert set(after) == {s for s in head if not s.startswith(later)}
```

Edit 21 (`tests/e2e/test_migration_0008_live.py`), replace:

```python
    }
    assert sorted(names[oid] for oid in reachable if INSERTS_A_JOB.search(bodies[oid])) == []
```

with:

```python
    }
    # The search's two thresholds (T17, T18): reached, scanned, and as free of job inserts as the rest.
    assert {"_min_rank", "_min_similarity"} <= {names[oid] for oid in reachable}
    assert sorted(names[oid] for oid in reachable if INSERTS_A_JOB.search(bodies[oid])) == []
```

The two round trips (0011's to 0010, 0012's to 0011) now pass through 0013's downgrade, which drops
`app._min_similarity()` and `app.embeddings`; their snapshots leave the helper out, and the `migrate` in their
`finally` brings the head back (the `embedded` fixture of Task 4 re-embeds after them).

- [ ] **Step 5: Gates and commit**

`check.py` → `1419 passed, 209 skipped`; `verify_handoff.py` exit 0; the live gate → `1607 passed, 21 skipped`. This
live run is the first execution of 0013's SQL: read Review Focus 1-3 before it, and on a failure in
`test_migration_0013_live.py` compare the message with them first.

```bash
git add migrations/app/versions/0013_embeddings.py core/src/ops_core/privileges.py core/src/ops_core/locking.py \
  core/src/ops_core/persistence.py mcp-read/src/ops_mcp_read/server.py tests/plan_n/test_migration_0013.py \
  tests/plan_e/test_transitions_table.py tests/plan_k/test_mcp_write_startup.py tests/e2e/conftest.py \
  tests/e2e/test_migration_0013_live.py tests/e2e/test_migration_0011_live.py tests/e2e/test_migration_0012_live.py \
  tests/e2e/test_migration_0008_live.py
git commit -m "feat: revision 0013 - app.embeddings and exact vector search in search_procedures_scoped (T18)"
```

---

### Task 4: `skeleton.py embed` — the stored embeddings, their prefix proof and exactness

**Files:**
- Create: `core/src/ops_core/embed.py`, `tests/plan_n/test_embed_command.py`, `tests/e2e/test_vector_retrieval_live.py`
- Modify: `scripts/skeleton.py` (`embed`, `_embed`, `main`), `tests/e2e/conftest.py` (`embedded`)

**Requirements:** rulings 2, 7, 12 and 14 (DoD 2's live half); erratum 98's operator-command shape.

**Interfaces:**
- Consumes: `embeddings.*`, `model_pins.load_embedding_pins`, `persistence.assert_relation`, `set_tenant`,
  `search_procedures(…, mode="vector", embedding=…)`; `skeleton.corpus_tenants`, `load_dotenv`,
  `export_environment`; `retrieval_comparison.ranked`, `REPEAT_COSINE`; `test_retrieval_baseline_live.QUERIES`,
  `REQUESTERS`; `test_corpus_files.AS_OF`.
- Produces: `embed.embed(conn, embedder, pins, tenants) -> list[Report]`, `embed.Report(tenant, added, present)`,
  `embed.EmbedRefused(problems)`, `embed.Missing`; `skeleton.embed() -> int` (`EMBED: <tenant>: n new, n present`);
  the live fixture `embedded`.

- [ ] **Step 1: Write the failing command tests**

Create `tests/plan_n/test_embed_command.py`:

```python
"""`scripts/skeleton.py embed` without a database or Ollama (Plan N ruling 2; erratum 98's operator-command shape).

Catches: the command connecting as anyone but the worker; a missing pin, a model mismatch, an unreachable model or a
mixed-digest store reported as success or with a value in the message; a repeat that does not say it wrote nothing;
and the sub-command not registered.
"""

from pathlib import Path
from typing import Any

import pytest
from ops_core import embed, embeddings
from ops_core.model_pins import EmbeddingPins

from scripts import skeleton


@pytest.fixture
def quiet(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """No .env, the worker's settings recorded instead of a connection."""
    monkeypatch.setattr(skeleton, "load_dotenv", lambda path: {})
    monkeypatch.setattr(skeleton, "export_environment", lambda dotenv: None)
    monkeypatch.setattr(skeleton.settings, "app_postgres", lambda role: role)
    return []


def test_the_command_reports_each_outcome_and_connects_as_the_worker(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], quiet: list[Any]
) -> None:
    async def written(pg: Any, pins: EmbeddingPins) -> list[embed.Report]:
        quiet.append(pg)
        return [embed.Report("alpha", 39, 0), embed.Report("beta", 0, 30)]

    monkeypatch.setattr(skeleton, "_embed", written)
    assert skeleton.embed() == 0 and quiet == [skeleton.Role.WORKER]
    assert capsys.readouterr().out.splitlines() == ["EMBED: alpha: 39 new, 0 present", "EMBED: beta: 0 new, 30 present"]

    for failure, line in (
        (
            embeddings.PinMismatch("the installed embedding model is not the pinned one"),
            "EMBED: failed (UNSUPPORTED_MODE: the installed embedding model is not the pinned one)",
        ),
        (
            embeddings.Unavailable("the embedding model could not be reached"),
            "EMBED: failed (UNAVAILABLE: the embedding model could not be reached)",
        ),
        (
            embed.EmbedRefused(["beta: 3 stored embeddings were made with another model digest than the pin"]),
            "EMBED: refused, nothing written",
        ),
    ):

        async def failing(pg: Any, pins: EmbeddingPins, failure: Exception = failure) -> list[embed.Report]:
            raise failure

        monkeypatch.setattr(skeleton, "_embed", failing)
        assert skeleton.embed() == 1
        assert capsys.readouterr().out.splitlines()[0] == line
    assert skeleton.main(["skeleton.py", "embed"]) == 1  # registered (the last failure still answers)


def test_a_missing_pin_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path, quiet: list[Any]
) -> None:
    monkeypatch.setattr(embeddings, "PINS", tmp_path / "embedding-pins.json")

    async def never(pg: Any, pins: EmbeddingPins) -> list[embed.Report]:
        raise AssertionError("nothing may be embedded without a pin")

    monkeypatch.setattr(skeleton, "_embed", never)
    assert skeleton.embed() == 1
    assert capsys.readouterr().out.splitlines() == [
        "EMBED: refused, nothing written (data/embedding-pins.json is missing or malformed)"
    ]
```

Run: `uv run python -m pytest tests/plan_n/test_embed_command.py -q`
Expected: a collection error, `ImportError: cannot import name 'embed' from 'ops_core'`.

- [ ] **Step 2: The embedding step and the command**

Create `core/src/ops_core/embed.py`:

```python
"""The document embeddings as role `worker` (T18; Plan N rulings 2, 3, 12 and 14; erratum 98's operator-command shape).

`scripts/skeleton.py embed` runs this after `ingest`: it embeds every stored chunk that has no embedding yet, with the
pinned model, from the chunk's stored section and body (`embeddings.document_text`, the `search_document:` prefix
included), and keeps the SHA-256 of that exact text beside the vector. Lifecycle is decided at query time, so every
stored chunk is embedded, whatever its status, and the clock is never consulted (ingestion's rule). The pin is checked
against Ollama's `/api/tags` before anything is written.

Like ingestion, a run plans every tenant first, each in a read-only unit under its tenant setting, and writes nothing
if any tenant is refused: a tenant that already holds an embedding made with another digest than the pin is refused
(a model change is a later revision's re-embedding, never a mix). The vectors are fetched outside any transaction;
then each tenant is written in one transaction that re-reads what is missing and inserts only those rows, so a
concurrent run cannot make it write a row twice. A repeat with nothing missing writes nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from ops_core import embeddings, persistence
from ops_core.model_pins import EmbeddingPins

RELATIONS = ("app.chunks", "app.embeddings")


class EmbedRefused(Exception):
    """The run was refused before anything was written; `problems` names each tenant and the rule, never a text."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("\n".join(self.problems))


@dataclass(frozen=True)
class Missing:
    """One stored chunk without an embedding: its evidence ID and the exact text to embed."""

    evidence_id: str
    text: str


@dataclass(frozen=True)
class Report:
    """What one tenant's run wrote and found already present."""

    tenant: str
    added: int
    present: int


async def _read(conn: persistence.Conn, digest: str) -> tuple[list[Missing], int, int]:
    """The caller's tenant's chunks without an embedding (in byte order), how many rows exist, and how many of those
    were made with another digest than `digest`."""
    cur = await conn.execute(
        "SELECT c.evidence_id, c.section, c.body FROM app.chunks c LEFT JOIN app.embeddings e"
        ' USING (tenant_id, evidence_id) WHERE e.embedding IS NULL ORDER BY c.evidence_id COLLATE "C"'
    )
    missing = [
        Missing(str(row["evidence_id"]), embeddings.document_text(str(row["section"]), str(row["body"])))
        for row in await cur.fetchall()
    ]
    cur = await conn.execute(
        "SELECT count(*) AS present, count(*) FILTER (WHERE model_digest <> %s) AS other_digest FROM app.embeddings",
        (digest,),
    )
    row = await cur.fetchone()
    present, foreign = (0, 0) if row is None else (int(row["present"]), int(row["other_digest"]))
    return missing, present, foreign


async def embed(
    conn: persistence.Conn, embedder: embeddings.Embedder, pins: EmbeddingPins, tenants: Mapping[str, UUID]
) -> list[Report]:
    """Embed every stored chunk without an embedding for each named tenant, on a `worker` connection.

    Args:
        conn: an autocommit connection as role `worker` (AM-20.2's corpus cells, SA:431).
        embedder: the embedding model's client (`embeddings.OllamaEmbedder` in production).
        pins: `data/embedding-pins.json` as `model_pins.load_embedding_pins` read it.
        tenants: tenant slug -> tenant UUID.

    Raises:
        PersistenceError: revision 0013 is missing (`persistence.assert_relation`).
        embeddings.EmbeddingError: the model is not the pinned one (PinMismatch), cannot be reached (Unavailable) or
            answered something else than the pinned vectors (Malformed); tenants written before it stay written.
        EmbedRefused: a tenant holds embeddings of another digest; nothing was written.
    """
    for relation in RELATIONS:
        await persistence.assert_relation(conn, relation)
    await embedder.verify(pins)  # before anything is read for writing (ruling 3)
    order = sorted(tenants.items())
    problems: list[str] = []
    for tenant, tenant_id in order:  # phase 1: refuse a mixed store before anything is written
        async with conn.transaction():
            await persistence.set_tenant(conn, tenant_id)
            _, _, foreign = await _read(conn, pins.digest)
        if foreign:
            problems.append(f"{tenant}: {foreign} stored embeddings were made with another model digest than the pin")
    if problems:
        raise EmbedRefused(problems)
    reports: list[Report] = []
    for tenant, tenant_id in order:  # phase 2: fetch outside a transaction, then one transaction per tenant
        async with conn.transaction():
            await persistence.set_tenant(conn, tenant_id)
            missing, _, _ = await _read(conn, pins.digest)
        vectors = await embedder.embed([m.text for m in missing], pins) if missing else []
        made = {m.evidence_id: (m, v) for m, v in zip(missing, vectors, strict=True)}
        async with conn.transaction():
            await persistence.set_tenant(conn, tenant_id)
            still, present, foreign = await _read(conn, pins.digest)
            if foreign:
                raise EmbedRefused([f"{tenant}: another model digest appeared while embedding; nothing written"])
            added = 0
            for row in still:
                if row.evidence_id not in made:
                    continue  # a chunk ingested meanwhile: the next run embeds it
                chunk, vector = made[row.evidence_id]
                await conn.execute(
                    "INSERT INTO app.embeddings (tenant_id, evidence_id, model, model_digest, dimension, input_sha256,"
                    " embedding) VALUES (%s, %s, %s, %s, %s, %s, %s::public.vector)",
                    (
                        tenant_id,
                        chunk.evidence_id,
                        pins.model,
                        pins.digest,
                        pins.dimension,
                        embeddings.input_sha256(chunk.text),
                        embeddings.vector_literal(vector),
                    ),
                )
                added += 1
        reports.append(Report(tenant, added, present))
    return reports
```

Edit 1 (`scripts/skeleton.py`), replace:

```python
"""Walking-skeleton operations (T08, T09, T10, T17): `migrate` both databases, `ingest` the governed corpus,
`up`/`down`/`status` the seven processes, `keys` the destination-vs-grant detective check.
```

with:

```python
"""Walking-skeleton operations (T08, T09, T10, T17, T18): `migrate` both databases, `ingest` the governed corpus,
`embed` its stored chunks, `up`/`down`/`status` the seven processes, `keys` the destination-vs-grant detective check.
```

Edit 2 (`scripts/skeleton.py`), replace:

```python
from ops_core import corpus, persistence, privileges, settings
```

with:

```python
from ops_core import corpus, embeddings, model_pins, persistence, privileges, settings
from ops_core import embed as corpus_embed
```

Edit 3 (`scripts/skeleton.py`), replace:

```python

def clock_guard(superuser: settings.Postgres, profile: Profile) -> None:
```

with:

```python

async def _embed(pg: settings.Postgres, pins: model_pins.EmbeddingPins) -> list[corpus_embed.Report]:
    conn = await persistence.connect(pg)
    embedder = embeddings.OllamaEmbedder.from_settings()
    try:
        return await corpus_embed.embed(conn, embedder, pins, corpus_tenants())
    finally:
        await embedder.aclose()
        await conn.close()


def embed() -> int:
    """Embed every stored chunk without an embedding as role `worker` (T18, Plan N ruling 2), into the database the
    environment names (`OPS_PG_DB`, default `ops`; the live suite's `ops_test`), with the model that
    `data/embedding-pins.json` pins, checked against Ollama (`OPS_OLLAMA_URL`) before anything is written. Exit 1 with
    the reason, and nothing written, when the pin is missing or does not match, Ollama cannot be reached, or a tenant
    holds another digest's embeddings; a repeated run writes nothing. The dev database waits for the owner (after
    `ingest`)."""
    export_environment(load_dotenv(ROOT / ".env"))
    try:
        pins = model_pins.load_embedding_pins(embeddings.PINS)
        pg = settings.app_postgres(Role.WORKER)
        if sys.platform == "win32":  # psycopg async refuses the Proactor loop (as in serve_app)
            reports = asyncio.run(_embed(pg, pins), loop_factory=asyncio.SelectorEventLoop)
        else:
            reports = asyncio.run(_embed(pg, pins))
    except model_pins.ModelPinsError:
        print("EMBED: refused, nothing written (data/embedding-pins.json is missing or malformed)")
        return 1
    except embeddings.EmbeddingError as error:
        # Our own messages name a rule, never a value or an address.
        print(f"EMBED: failed ({error.code}: {error})")
        return 1
    except corpus_embed.EmbedRefused as error:
        print("EMBED: refused, nothing written")
        for problem in error.problems:
            print(f"  {problem}")
        return 1
    except (persistence.PersistenceError, psycopg.Error) as error:
        detail = f": {error}" if isinstance(error, persistence.PersistenceError) else ""
        print(f"EMBED: failed ({type(error).__name__}{detail})")
        return 1
    for report in reports:
        print(f"EMBED: {report.tenant}: {report.added} new, {report.present} present")
    return 0


def clock_guard(superuser: settings.Postgres, profile: Profile) -> None:
```

Edit 4 (`scripts/skeleton.py`), replace:

```python
    commands = {"migrate": migrate, "ingest": ingest, "up": up, "down": down, "status": status, "keys": keys}
```

with:

```python
    commands = {
        "migrate": migrate,
        "ingest": ingest,
        "embed": embed,
        "up": up,
        "down": down,
        "status": status,
        "keys": keys,
    }
```

Run: `uv run python -m pytest tests/plan_n/test_embed_command.py tests/plan_l/test_ingest_plan.py -q` → all passing,
the new file `2 passed`.

- [ ] **Step 3: The `embedded` fixture and the live tests**

Edit 5 (`tests/e2e/conftest.py`), replace:

```python
from ops_core import corpus, ingest, persistence, settings
```

with:

```python
from ops_core import corpus, embed, embeddings, ingest, model_pins, persistence, settings
```

Edit 6 (`tests/e2e/conftest.py`), replace:

```python
        await ingest.ingest(conn, corpus.load(CORPUS), corpus_tenants())
    finally:
        await conn.close()
```

with:

```python
        await ingest.ingest(conn, corpus.load(CORPUS), corpus_tenants())
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def embedded(ingested: None) -> None:
    """Every stored chunk of the seeded tenants embedded as the worker through the real local Ollama with the pinned
    model (T18, Plan N rulings 2 and 13): the same code `skeleton.py embed` runs. A no-op when nothing is missing, and
    a fresh embedding after a migration round trip dropped the table. Ollama is already a live-gate dependency
    (tests/plan_b/live/test_ollama_bridge.py)."""
    from scripts.skeleton import corpus_tenants

    conn = await persistence.connect(settings.app_postgres(Role.WORKER))
    embedder = embeddings.OllamaEmbedder.from_settings()
    try:
        await embed.embed(conn, embedder, model_pins.load_embedding_pins(embeddings.PINS), corpus_tenants())
    finally:
        await embedder.aclose()
        await conn.close()
```

Create `tests/e2e/test_vector_retrieval_live.py`:

```python
"""The stored embeddings and the vector search against real local Ollama (OPS_LIVE=1; T18 DoD 2; Plan N rulings 2, 7,
12 and 14).

Catches: a stored row whose text was not the prefixed section (its `input_sha256` is not the SHA-256 of
`search_document: ` + heading + blank line + body), made with another model, digest or dimension than the pin, or
missing for a stored chunk; a stored vector that is not the embedding of that prefixed text (a fresh embedding must be
the same vector within the repeat bound, and the unprefixed text's embedding must not be); an `embed` repeat that
writes again; a store with another digest's embeddings written into instead of refused; and a definer whose vector
answer is not exactly the brute-force cosine ranking of the stored vectors over the permitted set (same threshold,
same byte-order tie-break) for every development query: no index, nothing approximate.
"""

from collections.abc import Awaitable, Callable
from uuid import UUID

import pytest
from ops_core import corpus, embed, embeddings, model_pins, persistence
from ops_core.settings import Role

from scripts import retrieval_baseline as rb
from scripts import retrieval_comparison as rc
from scripts.skeleton import CORPUS, corpus_tenants
from tests.e2e.conftest import lease_for, purge_run
from tests.e2e.test_fenced_definers_live import investigate_job, read_handle
from tests.e2e.test_migration_0011_live import DAY, cleanup, clock, handle_for, stage
from tests.e2e.test_migrations_and_persistence import new_run
from tests.e2e.test_retrieval_baseline_live import QUERIES, REQUESTERS
from tests.plan_l.test_corpus_files import AS_OF

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("embedded")]

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]


def pins() -> model_pins.EmbeddingPins:
    """The committed pin, read when a test runs (never at collection, so the dev gate does not depend on it)."""
    return model_pins.load_embedding_pins(embeddings.PINS)


async def stored(app_conn: persistence.Conn) -> dict[tuple[UUID, str], dict[str, object]]:
    """Every embedding row of the seeded tenants with its chunk's text, read as the superuser."""
    cur = await app_conn.execute(
        "SELECT c.tenant_id, c.evidence_id, c.section, c.body, e.model, e.model_digest, e.dimension, e.input_sha256,"
        " e.embedding::text AS vector FROM app.chunks c LEFT JOIN app.embeddings e USING (tenant_id, evidence_id)"
        " WHERE c.tenant_id = ANY(%s)",
        (list(corpus_tenants().values()),),
    )
    return {(UUID(str(r["tenant_id"])), str(r["evidence_id"])): dict(r) for r in await cur.fetchall()}


async def test_every_stored_chunk_is_embedded_from_its_prefixed_text_with_the_pinned_model(
    app_conn: persistence.Conn,
) -> None:
    rows = await stored(app_conn)
    assert len(rows) == 69  # corpus-1's sections (docs/retrieval.md)
    for key, row in rows.items():
        text = embeddings.document_text(str(row["section"]), str(row["body"]))
        assert row["input_sha256"] == embeddings.input_sha256(text), key  # the prefix proof (DoD 2)
        assert (row["model"], row["model_digest"], row["dimension"]) == (pins().model, pins().digest, 768), key
        assert len(embeddings.parse_vector(str(row["vector"]))) == 768


async def test_a_stored_vector_is_the_prefixed_texts_embedding_and_not_the_bare_texts(
    app_conn: persistence.Conn,
) -> None:
    alpha = corpus_tenants()["alpha"]
    row = (await stored(app_conn))[(alpha, "ALPHA-PUMP-SEAL:v2:inspection")]
    vector = embeddings.parse_vector(str(row["vector"]))
    section, body = str(row["section"]), str(row["body"])
    embedder = embeddings.OllamaEmbedder.from_settings()
    try:
        bare_text = embeddings.document_text(section, body).removeprefix(embeddings.DOCUMENT_PREFIX)
        fresh, bare = await embedder.embed([embeddings.document_text(section, body), bare_text], pins())
    finally:
        await embedder.aclose()
    assert embeddings.cosine(vector, fresh) >= rc.REPEAT_COSINE  # the stored vector is the prefixed text's (ruling 14)
    assert embeddings.cosine(vector, bare) < rc.REPEAT_COSINE  # and the prefix changed it: about 0.96 when measured


async def test_embed_writes_nothing_twice_and_refuses_a_foreign_digest(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    worker = await role_conn(Role.WORKER)
    embedder = embeddings.OllamaEmbedder.from_settings()
    tenant, run, _ = await handle_for(app_conn, role_conn, None)
    try:
        again = await embed.embed(worker, embedder, pins(), corpus_tenants())
        assert [(r.tenant, r.added) for r in again] == [("alpha", 0), ("beta", 0)]
        assert sum(r.present for r in again) == 69
        now = await clock(app_conn)
        await stage(
            app_conn,
            tenant,
            [
                {"id": "OLD-MODEL", "version": "1", "states": [("approved", now - DAY, None)]},
                {"id": "NOT-YET", "version": "1", "states": [("approved", now - DAY, None)]},
            ],
        )
        await app_conn.execute(
            "INSERT INTO app.embeddings (tenant_id, evidence_id, model, model_digest, dimension, input_sha256,"
            " embedding) SELECT %s, 'OLD-MODEL:v1:turbine', 'nomic-embed-text', %s, 768, %s, embedding"
            " FROM app.embeddings LIMIT 1",
            (tenant, "f" * 64, "1" * 64),
        )
        with pytest.raises(embed.EmbedRefused, match="another model digest"):
            await embed.embed(worker, embedder, pins(), {"probe": tenant})
        cur = await app_conn.execute(
            "SELECT count(*) AS n FROM app.embeddings WHERE tenant_id = %s AND evidence_id = 'NOT-YET:v1:turbine'",
            (tenant,),
        )
        assert (await cur.fetchone() or {})["n"] == 0  # refused: nothing written
    finally:
        await embedder.aclose()
        await cleanup(app_conn, [run], [tenant])


async def test_the_definer_is_exact_against_a_brute_force_ranking(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """Ruling 7: every development query at the labelling instant, limit 8, vector mode, against Python's ranking of the
    stored vectors of the same permitted set with the same threshold and tie-break."""
    governed = corpus.load(CORPUS)
    cases = rb.load_queries(QUERIES)
    allowed = corpus.returnable(governed, AS_OF)
    tenants = corpus_tenants()
    vectors = {
        (key[0], key[1]): embeddings.parse_vector(str(row["vector"])) for key, row in (await stored(app_conn)).items()
    }
    cur = await app_conn.execute("SELECT app._min_similarity() AS m")
    threshold = float((await cur.fetchone() or {})["m"])
    embedder = embeddings.OllamaEmbedder.from_settings()
    try:
        queries = await embedder.embed([embeddings.query_text(c.query) for c in cases], pins())
    finally:
        await embedder.aclose()
    api, worker, mcp_read = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.MCP_READ)
    harness = await role_conn(Role.TEST_HARNESS)
    runs: dict[str, UUID] = {}
    compared = 0
    try:
        await harness.execute("UPDATE app.test_clock SET clock_offset = %s - clock_timestamp()", (AS_OF,))
        for slug, tenant in tenants.items():
            _, _, runs[slug] = await new_run(app_conn, tenant, api=api, requester=REQUESTERS[slug])
        leases = {slug: await lease_for(worker, run, owner="t18-exact", seconds=600) for slug, run in runs.items()}
        for case, query in zip(cases, queries, strict=True):
            run = runs[case.tenant]
            handle = await read_handle(worker, run, await investigate_job(app_conn, run), leases[case.tenant])
            answer = await persistence.search_procedures(
                mcp_read,
                handle=handle,
                azp="ops-worker",
                query=case.query,
                asset_type=case.asset_type,
                limit=8,
                mode="vector",
                embedding=query,
            )
            scored = [
                (d.evidence_id(s), embeddings.cosine(query, vectors[(tenants[case.tenant], d.evidence_id(s))]))
                for d in governed.documents
                if d.tenant == case.tenant
                and d.identity in allowed
                and (case.asset_type is None or d.asset_family in (None, case.asset_type))
                for s in d.sections
            ]
            expected = rc.ranked(scored, threshold, 8)
            assert [h.evidence_id for h in answer.results] == [e for e, _ in expected], case.id
            for hit, (_, similarity) in zip(answer.results, expected, strict=True):
                # pgvector sums in single precision; the order above is exact, the value agrees to float precision.
                assert hit.rank == pytest.approx(similarity, abs=1e-5), case.id
            compared += 1
    finally:
        await harness.execute("UPDATE app.test_clock SET clock_offset = interval '0'")
        for run in runs.values():
            await purge_run(app_conn, run)
    assert compared == len(cases) >= 40
```

- [ ] **Step 4: Gates and commit**

`check.py` → `1421 passed, 213 skipped`; `verify_handoff.py` exit 0; the live gate → `1613 passed, 21 skipped`. The
first `embedded` use embeds corpus-1's 69 sections through local Ollama (five requests of at most 16 inputs); later
uses find nothing missing.

```bash
git add core/src/ops_core/embed.py scripts/skeleton.py tests/plan_n/test_embed_command.py tests/e2e/conftest.py \
  tests/e2e/test_vector_retrieval_live.py
git commit -m "feat: skeleton.py embed - the corpus embedded from its prefixed text, proven exact (T18)"
```

---

### Task 5: mcp-read's `vector_exact`

**Files:**
- Create: `tests/plan_n/test_mcp_read_vector.py`
- Modify: `mcp-read/src/ops_mcp_read/server.py` (the docstring, `search_response`, `State.embedder`,
  `query_embedding`, `search_procedures`, the lifespan), `core/src/ops_core/routing.py` (`TODO(T18)` → `TODO(T25)`),
  `scripts/build_schemas.py` (a comment's `TODO(T18)`; the generated files do not change),
  `tests/plan_l/test_mcp_read_corpus.py` (`call`'s embedder; the recorded search arguments; the vector test
  rewritten), `tests/e2e/test_mcp_read_live.py` (the vector call)

**Requirements:** SA:348 (erratum 108), erratum 3, rulings 3, 4, 5 and 16; Plan M ruling 14's handle-first order.

**Interfaces:**
- Consumes: `embeddings.Embedder`, `OllamaEmbedder.from_settings`, `PINS`, `TIMEOUT_SECONDS`, `query_text`, the error
  classes; `model_pins.load_embedding_pins`, `ModelPinsError`; `persistence.search_procedures(…, mode, embedding)`;
  `tests.plan_l.test_mcp_read_corpus.Database`, `UnitConn`, `call`; `tests.plan_n.test_embeddings.FakeEmbedder`,
  `unit_vector`.
- Produces: `server.State.embedder`; `server.search_response(found, retrieval_mode="lexical")`;
  `tests.plan_l.test_mcp_read_corpus.call(…, embedder=None)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/plan_n/test_mcp_read_vector.py`:

```python
"""mcp-read's `vector_exact` search in-process, with the database, asset-sim and Ollama replaced (Plan N rulings 3, 4,
5 and 16; SA:348; errata 3 and 108).

Catches: an invalid handle that reaches the embedding model (it must never learn what the server supports, Plan M
ruling 14); a missing or mismatched pin answered with anything but `UNSUPPORTED_MODE`, an unreachable model with
anything but a retryable `UNAVAILABLE`, a malformed answer with anything but `UPSTREAM_INVALID`, and any of them
reaching the definer; the definer's `EMBEDDINGS_INCOMPLETE` lost instead of answered as `REFUSED`; a vector answer
that reports another mode or breaks the committed result contract; and the committed tool schemas changed for T18
(no tool argument changes, so R029's comparison stays byte for byte).
"""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from ops_core import embeddings, persistence

from tests.plan_l.test_mcp_read_corpus import Database, UnitConn, call
from tests.plan_n.test_embeddings import FakeEmbedder

pytestmark = pytest.mark.asyncio

VECTOR = {"query": "seal", "limit": 3, "mode": "vector_exact"}
TOOL_RESULT = Draft202012Validator(
    json.loads(Path("schemas/tool-result.schema.json").read_text(encoding="utf-8")), format_checker=FormatChecker()
)
# The committed contracts T18 must not touch (Plan N ruling 16): their SHA-256 on `plan-n` before T18 (6d00d06).
UNCHANGED = {
    "schemas/tools/search_procedures.input.schema.json": (
        "51277441bf8482e10258a63ca270d03b81cc8a65a536ac31824eb67d041758b9"
    ),
    "schemas/tool-result.schema.json": "c4e6f39b44c4b22c6078826329e7a16694872d9303bc53718f8cde5c02d4466a",
}


def doc_of(result: Any) -> dict[str, Any]:
    doc = result.structured_content
    assert not result.is_error and isinstance(doc, dict)
    return doc


async def test_a_vector_answer_reports_its_mode_and_meets_the_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = doc_of(await call(monkeypatch, Database(UnitConn()), VECTOR, embedder=FakeEmbedder()))
    TOOL_RESULT.validate(doc)
    assert doc["status"] == "ok" and doc["data"]["retrieval_mode"] == "vector_exact"
    assert "rank" not in doc["data"]["results"][0]  # a similarity never reaches the tool result either


async def test_an_invalid_handle_never_reaches_the_embedding_model(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeEmbedder()
    db = Database(UnitConn(), resolve=persistence.HandleRejected("invocation handle rejected"))
    doc = doc_of(await call(monkeypatch, db, VECTOR, embedder=fake))
    assert doc["error"]["code"] == "INVALID_HANDLE"
    assert fake.texts == [] and fake.verified == 0


@pytest.mark.parametrize(
    ("failure", "code", "retryable"),
    [
        (embeddings.PinMismatch("the installed embedding model is not the pinned one"), "UNSUPPORTED_MODE", False),
        (embeddings.Unavailable("the embedding model could not be reached"), "UNAVAILABLE", True),
        (embeddings.Malformed("an embedding has another dimension than the pinned one"), "UPSTREAM_INVALID", False),
    ],
    ids=["mismatch", "unavailable", "malformed"],
)
async def test_an_embedding_failure_is_its_envelope_and_never_reaches_the_definer(
    monkeypatch: pytest.MonkeyPatch, failure: embeddings.EmbeddingError, code: str, retryable: bool
) -> None:
    db = Database(UnitConn())
    doc = doc_of(await call(monkeypatch, db, VECTOR, embedder=FakeEmbedder(failure)))
    assert doc["error"] == {"code": code, "message": str(failure), "retryable": retryable}
    assert [name for name, _, _ in db.calls] == ["resolve", "scope"]  # no third unit
    assert doc["observed_at"] == "2026-10-16T12:00:00Z"  # the scope's database instant, as the asset tools


async def test_a_missing_pin_is_unsupported_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(embeddings, "PINS", tmp_path / "embedding-pins.json")
    fake = FakeEmbedder()
    doc = doc_of(await call(monkeypatch, Database(UnitConn()), VECTOR, embedder=fake))
    assert doc["error"]["code"] == "UNSUPPORTED_MODE" and fake.texts == []


async def test_incomplete_embeddings_are_refused_not_omitted(monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database(UnitConn(), search=persistence.Refused("EMBEDDINGS_INCOMPLETE"))
    doc = doc_of(await call(monkeypatch, db, VECTOR, embedder=FakeEmbedder()))
    assert doc["error"] == {"code": "REFUSED", "message": "EMBEDDINGS_INCOMPLETE", "retryable": False}


async def test_the_committed_tool_contracts_are_unchanged() -> None:
    for path, digest in UNCHANGED.items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest, path
```

Edit 1 (`tests/plan_l/test_mcp_read_corpus.py`), replace:

```python
`vector_exact` reaching the scope or the database before T18; a handle refused at any unit answered with anything but
the one plain `INVALID_HANDLE`; and a definer refusal escaping as a transport error instead of an envelope.
```

with:

```python
`vector_exact` asking the embedding model before the scope and the asset type, or reaching the definer without the
query's embedding and `mode='vector'` (T18); a handle refused at any unit answered with anything but the one plain
`INVALID_HANDLE`; and a definer refusal escaping as a transport error instead of an envelope.
```

Edit 2 (`tests/plan_l/test_mcp_read_corpus.py`), replace:

```python
from tests.plan_j.test_mcp_read_http import BASE, ISSUER, RESOURCE, KeyedVerifier
```

with:

```python
from tests.plan_j.test_mcp_read_http import BASE, ISSUER, RESOURCE, KeyedVerifier
from tests.plan_n.test_embeddings import FakeEmbedder, unit_vector
```

Edit 3 (`tests/plan_l/test_mcp_read_corpus.py`), replace:

```python
) -> CallToolResult:
    """One search over the in-process stack; `configured=False` leaves the server without an asset-sim client."""
```

with:

```python
    embedder: Any = None,
) -> CallToolResult:
    """One search over the in-process stack; `configured=False` leaves the server without an asset-sim client, and
    `embedder` stands in for Ollama (T18; without one the lifespan builds the real client, which a lexical search never
    calls)."""
```

Edit 4 (`tests/plan_l/test_mcp_read_corpus.py`), replace:

```python
    state.assets = (assets or RunType("pump")) if configured else None  # A17 is a pump (data/corpus/assets.json)
```

with:

```python
    state.assets = (assets or RunType("pump")) if configured else None  # A17 is a pump (data/corpus/assets.json)
    state.embedder = embedder
```

Edit 5 (`tests/plan_l/test_mcp_read_corpus.py`), replace:

```python
    assert db.calls[2][2] == {"handle": HANDLE, "azp": "ops-worker", "query": "seal", "asset_type": "pump", "limit": 3}
```

with:

```python
    assert db.calls[2][2] == {
        "handle": HANDLE,
        "azp": "ops-worker",
        "query": "seal",
        "asset_type": "pump",
        "limit": 3,
        "mode": "lexical",
        "embedding": None,
    }
```

Edit 6 (`tests/plan_l/test_mcp_read_corpus.py`), replace:

```python
async def test_vector_exact_is_refused_after_resolution_and_before_any_search(monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database(UnitConn())
    result = await call(monkeypatch, db, {"query": "seal", "limit": 3, "mode": "vector_exact"})
    assert [name for name, _, _ in db.calls] == ["resolve"]
    assert result.structured_content is not None
    assert result.structured_content["error"]["code"] == "UNSUPPORTED_MODE"
```

with:

```python
async def test_vector_exact_searches_after_the_scope_with_the_query_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    """T18 (Plan N ruling 4): the same three units; the query embedding is computed between the asset type and the
    third unit, and the definer is asked with `mode='vector'` (erratum 3)."""
    fake = FakeEmbedder()
    db = Database(UnitConn())
    result = await call(monkeypatch, db, {"query": "seal", "limit": 3, "mode": "vector_exact"}, embedder=fake)
    assert [(name, unit) for name, unit, _ in db.calls] == [("resolve", 1), ("scope", 2), ("search", 3)]
    assert fake.texts == ["search_query: seal"]
    assert db.calls[2][2]["mode"] == "vector" and db.calls[2][2]["embedding"] == tuple(
        unit_vector("search_query: seal")
    )
    assert result.structured_content is not None
    assert result.structured_content["data"]["retrieval_mode"] == "vector_exact"
```

Run: `uv run python -m pytest tests/plan_n/test_mcp_read_vector.py tests/plan_l/test_mcp_read_corpus.py -q`
Expected: failures, not errors: the vector tests that need an answer or a specific code get the old
`UNSUPPORTED_MODE` (the server still refuses), and `test_the_handle_resolves_in_its_own_unit_then_the_definer_searches`
misses `mode` and `embedding` in the recorded arguments. Three pass already and keep passing:
`test_the_committed_tool_contracts_are_unchanged`, `test_an_invalid_handle_never_reaches_the_embedding_model` and
`test_a_missing_pin_is_unsupported_mode` (the old refusal is the same code).

- [ ] **Step 2: Vector mode in mcp-read**

Edit 7 (`mcp-read/src/ops_mcp_read/server.py`), replace:

```python
  file. It reads the run's scope the same way and asks asset-sim for the run's asset type, which it passes to the
  definer: a caller's `asset_type` may only repeat it (`ASSET_TYPE_OUT_OF_SCOPE`, ruling 12).
```

with:

```python
  corpus file. It reads the run's scope the same way and asks asset-sim for the run's asset type, which it passes to
  the definer: a caller's `asset_type` may only repeat it (`ASSET_TYPE_OUT_OF_SCOPE`, ruling 12). In `vector_exact`
  mode (T18, Plan N ruling 4) it then checks the embedding pin against Ollama and computes the query's
  `search_query:` embedding itself (SA:348), and only then asks the definer with `mode='vector'` (erratum 3): a
  missing or mismatched pin is `UNSUPPORTED_MODE`, an unreachable model `UNAVAILABLE` (retryable), a malformed
  answer `UPSTREAM_INVALID`. mcp-read asks Ollama for `/api/tags` and `/api/embed` with the embedding model only,
  never for a generation (erratum 108).
```

Edit 8 (`mcp-read/src/ops_mcp_read/server.py`), replace:

```python
from ops_core import persistence, redaction, settings, tool_contracts
```

with:

```python
from ops_core import embeddings, model_pins, persistence, redaction, settings, tool_contracts
```

Edit 9 (`mcp-read/src/ops_mcp_read/server.py`), replace:

```python
def search_response(found: persistence.Procedures) -> ToolResult:
```

with:

```python
def search_response(
    found: persistence.Procedures, retrieval_mode: Literal["lexical", "vector_exact"] = "lexical"
) -> ToolResult:
```

Edit 10 (`mcp-read/src/ops_mcp_read/server.py`), replace:

```python
    (ruling 11)."""
```

with:

```python
    (ruling 11). `retrieval_mode` is the mode that actually ran (Plan N ruling 16)."""
```

Edit 11 (`mcp-read/src/ops_mcp_read/server.py`), replace:

```python
        data={"results": results, "retrieval_mode": "lexical", "corpus_version": found.corpus_version},
```

with:

```python
        data={"results": results, "retrieval_mode": retrieval_mode, "corpus_version": found.corpus_version},
```

Edit 12 (`mcp-read/src/ops_mcp_read/server.py`), replace:

```python
    """Process-wide dependencies the tools and the app share; `session` and `assets` are filled at startup."""
```

with:

```python
    """Process-wide dependencies the tools and the app share; `session`, `assets` and `embedder` are filled at
    startup."""
```

Edit 13 (`mcp-read/src/ops_mcp_read/server.py`), replace:

```python
    assets: assets.AssetSim | None = None
```

with:

```python
    assets: assets.AssetSim | None = None
    embedder: embeddings.Embedder | None = None  # T18: the query embedding (Plan N ruling 4)
```

Edit 14 (`mcp-read/src/ops_mcp_read/server.py`), replace:

```python

    async def get_asset_status(
```

with:

```python

    async def query_embedding(query: str) -> embeddings.Vector | embeddings.EmbeddingError:
        """The query's `search_query:` embedding with the pinned model, or the failure to answer with. The pin is
        read and checked against Ollama on every call (Plan N ruling 3), so a model swapped under a running server is
        refused, not used. One 10-second budget for the check and the embedding together."""
        if state.embedder is None:  # only before the lifespan ran
            return embeddings.Unavailable("the embedding model is not configured")
        try:
            pins = model_pins.load_embedding_pins(embeddings.PINS)
        except model_pins.ModelPinsError:
            return embeddings.PinMismatch("no valid embedding pin")
        try:
            async with asyncio.timeout(embeddings.TIMEOUT_SECONDS):
                await state.embedder.verify(pins)
                (vector,) = await state.embedder.embed([embeddings.query_text(query)], pins)
        except embeddings.EmbeddingError as exc:
            return exc
        except TimeoutError:
            return embeddings.Unavailable("the embedding model did not answer in time")
        return vector

    async def get_asset_status(
```

Edit 15 (`mcp-read/src/ops_mcp_read/server.py`), replace:

```python
        """Lexical search over the calling run's tenant's approved, effective procedure sections of the run's asset
        type (AM-15 read tool), through `search_procedures_scoped` (T17, T16)."""
        name = ToolName.SEARCH_PROCEDURES
        caller = await resolve(name, ctx)
        if not isinstance(caller, Caller):
            return caller
        if mode != "lexical":
            # The handle first, then the mode: an invalid handle never learns what the server supports (ruling 14).
            # TODO(T18): translate vector_exact to mode=vector and compute the nomic `search_query:` embedding once
            # T18 stores embeddings (erratum 3; Plan M ruling 1, erratum 103).
            return envelope(name.value, error=tool_error("UNSUPPORTED_MODE", "vector_exact arrives with T18"))
```

with:

```python
        """Lexical or exact vector search over the calling run's tenant's approved, effective procedure sections of
        the run's asset type (AM-15 read tool), through `search_procedures_scoped` (T17, T16, T18)."""
        name = ToolName.SEARCH_PROCEDURES
        caller = await resolve(name, ctx)  # the handle first: an invalid handle never reaches Ollama (ruling 14)
        if not isinstance(caller, Caller):
            return caller
```

Edit 16 (`mcp-read/src/ops_mcp_read/server.py`), replace:

```python
            return envelope(name.value, error=error, observed_at=scope.as_of)
        assert state.session is not None  # resolve() answered only with a session
```

with:

```python
            return envelope(name.value, error=error, observed_at=scope.as_of)
        embedding: embeddings.Vector | None = None
        if mode == "vector_exact":
            # After the scope and the asset type, before the third unit (Plan N ruling 4): outside any transaction.
            computed = await query_embedding(query)
            if isinstance(computed, embeddings.EmbeddingError):
                error = tool_error(computed.code, str(computed), retryable=computed.retryable)
                return envelope(name.value, error=error, observed_at=scope.as_of)
            embedding = computed
        assert state.session is not None  # resolve() answered only with a session
```

Edit 17 (`mcp-read/src/ops_mcp_read/server.py`), replace:

```python
                    limit=limit,
```

with:

```python
                    limit=limit,
                    mode="lexical" if embedding is None else "vector",  # erratum 3: the SQL's name for vector_exact
                    embedding=embedding,
```

Edit 18 (`mcp-read/src/ops_mcp_read/server.py`), replace:

```python
        return search_response(found)
```

with:

```python
        return search_response(found, mode)
```

Edit 19 (`mcp-read/src/ops_mcp_read/server.py`), replace:

```python
                state.assets = assets.HttpAssetSim.from_settings()  # mcp-read's own token (rulings 6 and 8)
```

with:

```python
                state.assets = assets.HttpAssetSim.from_settings()  # mcp-read's own token (rulings 6 and 8)
            if state.embedder is None:  # no network at start: the pin is checked on each vector call
                state.embedder = embeddings.OllamaEmbedder.from_settings()
```

Edit 20 (`mcp-read/src/ops_mcp_read/server.py`), replace:

```python
                if state.assets is not None:
                    try:
                        await state.assets.aclose()
                    finally:
                        state.assets = None
```

with:

```python
                try:
                    if state.assets is not None:
                        try:
                            await state.assets.aclose()
                        finally:
                            state.assets = None
                finally:
                    if state.embedder is not None:
                        try:
                            await state.embedder.aclose()
                        finally:
                            state.embedder = None
```

Edit 21 (`core/src/ops_core/routing.py`), replace:

```python
    # TODO(T18): mcp-read, the caller of `search_procedures_scoped`, translates `vector_exact` to `mode=vector`
    # (Plan M ruling 1: the translation arrives with T18's embeddings, erratum 103).
```

with:

```python
    # mcp-read, the caller of `search_procedures_scoped`, translates `vector_exact` to `mode=vector` (T18, erratum 3).
    # The worker still asks for `lexical` only; choosing the mode per run is TODO(T25) (Plan N ruling 16).
```

Edit 22 (`scripts/build_schemas.py`), replace:

```python
                "mode": {"enum": ["lexical", "vector_exact"]},  # ruling 3; mcp-read maps vector_exact (TODO(T18))
```

with:

```python
                "mode": {"enum": ["lexical", "vector_exact"]},  # ruling 3; mcp-read maps vector_exact (T18)
```

Run: `uv run python -m pytest tests/plan_n tests/plan_l tests/plan_m tests/plan_j tests/plan_d -q` → all passing;
`uv run python -m scripts.build_schemas` changes no file (`git status --short schemas` prints nothing).

- [ ] **Step 3: The live call over HTTP**

Edit 23 (`tests/e2e/test_mcp_read_live.py`), replace:

```python
applied when the caller names none, `vector_exact` answered before T18, and the two rejections the e2e test relies on
(persona token; mcp-write's token)."""
```

with:

```python
applied when the caller names none, `vector_exact` not answered from the stored embeddings through the real local
Ollama (T18) or answered outside the run's asset type, and the two rejections the e2e test relies on (persona token;
mcp-write's token)."""
```

Edit 24 (`tests/e2e/test_mcp_read_live.py`), replace:

```python
# T17: the governed corpus; T16: asset-sim, which the search asks for the run's asset type.
pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("ingested", "asset_sim")]
```

with:

```python
# T17: the governed corpus; T16: asset-sim, which the search asks for the run's asset type; T18: its embeddings.
pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("ingested", "embedded", "asset_sim")]
```

Edit 25 (`tests/e2e/test_mcp_read_live.py`), replace:

```python
            vector = await client.call_tool("search_procedures", {"query": "seal", "limit": 1, "mode": "vector_exact"})
```

with:

```python
            vector = await client.call_tool(
                "search_procedures",
                {
                    "query": "How often is the mechanical seal on pump A17 inspected?",
                    "limit": 5,
                    "mode": "vector_exact",
                },
            )
```

Edit 26 (`tests/e2e/test_mcp_read_live.py`), replace:

```python
        assert vector.structured_content["error"]["code"] == "UNSUPPORTED_MODE"
```

with:

```python
        # T18: the same run's search in vector mode, through Ollama and the stored embeddings, on the run's asset type.
        found = vector.structured_content
        assert not vector.is_error and found["status"] == "ok", found
        assert found["data"]["retrieval_mode"] == "vector_exact" and found["data"]["corpus_version"] == "corpus-1"
        families = {d.document_id: d.asset_family for d in corpus.load(CORPUS).documents}
        assert found["data"]["results"] and all(
            families[r["document_id"]] in (None, "pump") and governed[r["evidence_id"]] == r["content_sha256"]
            for r in found["data"]["results"]
        )
```

- [ ] **Step 4: Gates and commit**

`check.py` → `1429 passed, 213 skipped`; `verify_handoff.py` exit 0; the live gate → `1621 passed, 21 skipped`.
`grep -rn "TODO(T18)" --include=*.py . | grep -v "^./reference/"` prints only `0011_governed_corpus.py:178` and the
quotation of it in `0013_embeddings.py` (departure 10).

```bash
git add mcp-read/src/ops_mcp_read/server.py core/src/ops_core/routing.py scripts/build_schemas.py \
  tests/plan_n/test_mcp_read_vector.py tests/plan_l/test_mcp_read_corpus.py tests/e2e/test_mcp_read_live.py
git commit -m "feat: mcp-read answers vector_exact with the search_query embedding it computes (T18, SA:348)"
```

---

### Task 6: The comparison, measured

**Files:**
- Create: `tests/e2e/test_retrieval_comparison_live.py`; the live run writes `reports/retrieval-comparison.json` and
  `.md` (committed in Task 8)

**Requirements:** R034; T18 DoD 1; rulings 6-11 and 14.

**Interfaces:**
- Consumes: everything of Tasks 1-5; T17's harness helpers (`new_run`, `lease_for`, `read_handle`,
  `investigate_job`, `purge_run`, `QUERIES`, `REQUESTERS`, `AS_OF`, `RETURNABLE_AT_AS_OF`).
- Produces: the report pair at the DoD's path.

- [ ] **Step 1: The live test**

Create `tests/e2e/test_retrieval_comparison_live.py`:

```python
"""Exact vector search measured against the lexical baseline through the real SQL path and real local Ollama
(OPS_LIVE=1; R034, T18 DoD 1; Plan N rulings 6-11 and 14).

T17's harness, twice: every development query runs through `app.search_procedures_scoped` as `mcp_read` in lexical
mode and in vector mode (the query's `search_query:` embedding computed with `ops_core.embeddings`, the code mcp-read
uses), with a read handle of a run in the query's tenant, at k = 5 and with the query's asset type, on the database
test clock at corpus-1's labelling instant. The answers become reports/retrieval-comparison.json and .md (rewritten
only when the whole measurement ran; the T17 report is not touched). Catches: a forbidden section in either mode (the
one hard quality rule); the lexical path moved since T17 (its answers must reproduce the committed baseline's,
digest for digest); a vector threshold that the fixed rule no longer chooses on the stored vectors; two embeddings of
one query that are not the same vector within the bound; a window experiment that lets a forbidden section in; and a
report whose corpus or query identity is not the measured one. The quality numbers themselves are measurements, not
gates (BS:611).
"""

import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from ops_core import corpus, embeddings, model_pins, persistence
from ops_core.settings import Role

from scripts import retrieval_baseline as rb
from scripts import retrieval_comparison as rc
from scripts.skeleton import CORPUS, corpus_tenants
from tests.e2e.conftest import lease_for, purge_run
from tests.e2e.test_fenced_definers_live import investigate_job, read_handle
from tests.e2e.test_migrations_and_persistence import new_run
from tests.e2e.test_retrieval_baseline_live import QUERIES, REQUESTERS
from tests.plan_l.test_corpus_files import AS_OF, RETURNABLE_AT_AS_OF

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("embedded")]

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
REPORT = Path(__file__).resolve().parents[2] / "reports" / "retrieval-comparison"  # the DoD's path


async def test_r034_exact_vector_search_against_the_lexical_baseline(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    governed = corpus.load(CORPUS)
    cases = rb.load_queries(QUERIES)
    tenants = corpus_tenants()
    pins = model_pins.load_embedding_pins(embeddings.PINS)
    embedder = embeddings.OllamaEmbedder.from_settings()
    try:
        await embedder.verify(pins)
        version = await embedder.version()
        texts = [embeddings.query_text(c.query) for c in cases]
        queries, repeated = await embedder.embed(texts, pins), await embedder.embed(texts, pins)
        windows = rc.corpus_windows(governed)
        window_vectors = await embedder.embed([w.text for w in windows], pins)
    finally:
        await embedder.aclose()
    repeat = rc.repeat_check(queries, repeated)
    assert repeat["min_cosine"] >= rc.REPEAT_COSINE  # ruling 14
    cur = await app_conn.execute(
        "SELECT tenant_id, evidence_id, embedding::text AS vector FROM app.embeddings WHERE tenant_id = ANY(%s)",
        (list(tenants.values()),),
    )
    stored = {
        (UUID(str(r["tenant_id"])), str(r["evidence_id"])): embeddings.parse_vector(str(r["vector"]))
        for r in await cur.fetchall()
    }
    cur = await app_conn.execute("SELECT app._min_similarity() AS m")
    threshold = float((await cur.fetchone() or {})["m"])
    allowed = corpus.returnable(governed, AS_OF)
    assert allowed == RETURNABLE_AT_AS_OF  # the hand-written anchor of T17's measurement
    permitted = {
        slug: {
            d.evidence_id(s)
            for d in governed.documents
            if d.identity in allowed and d.tenant == slug
            for s in d.sections
        }
        for slug in tenants
    }
    api, worker, mcp_read = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.MCP_READ)
    harness = await role_conn(Role.TEST_HARNESS)
    runs: dict[str, UUID] = {}
    lexical, vector = [], []
    try:
        await harness.execute("UPDATE app.test_clock SET clock_offset = %s - clock_timestamp()", (AS_OF,))
        for slug, tenant in tenants.items():
            _, _, runs[slug] = await new_run(app_conn, tenant, api=api, requester=REQUESTERS[slug])
        leases = {slug: await lease_for(worker, run, owner="t18-compare", seconds=600) for slug, run in runs.items()}
        for case, query in zip(cases, queries, strict=True):
            run = runs[case.tenant]
            for mode, out in (("lexical", lexical), ("vector", vector)):
                # A fresh handle per call: a handle lives 60 seconds, and the two modes must not share a failure.
                handle = await read_handle(worker, run, await investigate_job(app_conn, run), leases[case.tenant])
                answer = await persistence.search_procedures(
                    mcp_read,
                    handle=handle,
                    azp="ops-worker",
                    query=case.query,
                    asset_type=case.asset_type,
                    limit=rb.K,
                    mode="lexical" if mode == "lexical" else "vector",
                    embedding=None if mode == "lexical" else query,
                )
                assert answer.corpus_version == governed.corpus_version, case.id
                out.append(rb.evaluate(case, [(h.evidence_id, h.rank) for h in answer.results], permitted[case.tenant]))
    finally:
        await harness.execute("UPDATE app.test_clock SET clock_offset = interval '0'")
        for run in runs.values():
            await purge_run(app_conn, run)
    # Hard rules: no forbidden section in either mode, and the lexical path is T17's, answer for answer.
    assert [(o.case.id, o.forbidden) for o in lexical + vector if o.forbidden] == []
    relisted = [
        {"id": o.case.id, "returned": [{"evidence_id": e, "rank": round(r, 6)} for e, r in o.returned]} for o in lexical
    ]
    assert rc.answers_digest(relisted) == rc.T17_ANSWERS_SHA256  # the lexical path did not move (ruling 11)
    scored = {
        c.id: [
            (d.evidence_id(s), embeddings.cosine(q, stored[(tenants[c.tenant], d.evidence_id(s))]))
            for d in governed.documents
            if d.tenant == c.tenant
            and d.identity in allowed
            and (c.asset_type is None or d.asset_family in (None, c.asset_type))
            for s in d.sections
        ]
        for c, q in zip(cases, queries, strict=True)
    }
    sweep = rc.sweep(cases, scored, rc.GRID)
    assert rc.choose_threshold(sweep) == pytest.approx(threshold)  # the frozen value is still the rule's (ruling 6)
    found = {}
    for c, q in zip(cases, queries, strict=True):
        # A window is named by its first section, so ties break by evidence_id in byte order as in the definer.
        candidates = {
            w.evidence_ids[0]: (w, embeddings.cosine(q, v))
            for w, v in zip(windows, window_vectors, strict=True)
            if w.tenant == c.tenant and (c.asset_type is None or w.asset_family in (None, c.asset_type))
        }
        best = rc.ranked([(first, s) for first, (_, s) in candidates.items()], threshold, rb.K)
        found[c.id] = [candidates[first][0] for first, _ in best]
    window = rc.window_metrics(cases, found, permitted, len(windows))
    assert window["forbidden_sections"] == 0
    settings = {
        "model": pins.model,
        "model_digest": pins.digest,
        "dimension": pins.dimension,
        "ollama_version": version,
        "document_prefix": embeddings.DOCUMENT_PREFIX,
        "document_text": "search_document: + section heading + blank line + body",
        "query_prefix": embeddings.QUERY_PREFIX,
        "distance": "cosine (pgvector <=>); rank = 1 - distance, the cosine similarity",
        "vector_minimum_similarity": threshold,
        "lexical_minimum_rank": 0.25,
        "index": "none: a sequential scan over the tenant's permitted chunks, exact by construction",
        "window": "one chunk per ## section (the stored unit)",
        "window_experiment": {"min_words": rc.WINDOW_WORDS, "rule": "adjacent sections of one version"},
        "tie_break": 'evidence_id ascending in byte order (COLLATE "C")',
        "ks": list(rc.KS),
        "filters": rb.SETTINGS["filters"],
    }
    doc = rc.comparison(
        lexical,
        vector,
        settings=settings,
        vector_sweep=sweep,
        lexical_sweep_rows=rc.lexical_sweep(lexical, rc.LEXICAL_GRID),
        window=window,
        repeat=repeat,
        corpus_version=governed.corpus_version,
        lock_sha256=governed.lock_sha256,
        queries_sha256=hashlib.sha256(QUERIES.read_bytes()).hexdigest(),
        measured_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    assert doc["summary"]["vector_exact"]["5"]["hit_at_k"]["successes"] > 0  # a floor against a broken search
    REPORT.with_suffix(".json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8", newline="\n")
    REPORT.with_suffix(".md").write_text(rc.markdown(doc), encoding="utf-8", newline="\n")
```

- [ ] **Step 2: Run it and read the report**

Run the live gate (`PYTHONUTF8=1 uv run python scripts/check.py --profile test`) → `1622 passed, 21 skipped`; or, to
iterate, `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_retrieval_comparison_live.py -q` (it brings
up its own per-session databases) → `1 passed`. Then read `reports/retrieval-comparison.md`. Expected from the
pre-measurement (not gates): lexical hit@5 27/27 and answered-empty 15/20 exactly as T17's report; vector hit@5 26/27
(A08 regressed) and answered-empty 18/20 (B10, B13, B17 and B18 improved, A13 regressed); McNemar p 1.0 on hit@5 and
0.375 on answered-empty, so "no ranking claim"; a vector threshold of 0.68 re-chosen on the stored vectors; zero
forbidden rows. Record in the report the md's Results tables and both McNemar lines. Then `git checkout --
reports/bootstrap reports/skeleton reports/auth reports/admission reports/leases reports/events reports/outbox
reports/mcp-read reports/mcp-write reports/asset-sim reports/retrieval`, leaving the two new report files untracked.

- [ ] **Step 3: Gates and commit**

`check.py` → `1429 passed, 214 skipped`; `verify_handoff.py` exit 0.

```bash
git add tests/e2e/test_retrieval_comparison_live.py
git commit -m "test: exact vector search measured against the lexical baseline (T18, R034)"
```

---

### Task 7: Documentation and the architecture record (erratum 108)

**Files:**
- Modify: `docs/retrieval.md`, `docs/runbooks/mcp-read.md`, `docs/runbooks/walking-skeleton.md`,
  `docs/ARCHITECTURE.md`, `docs/adr/ADR-0001-deployable-units-as-top-level-directories.md`

**Requirements:** BS:417 (settings and score interpretation stored), ruling 4's erratum 108, ruling 18's documents.
This task writes no behaviour.

- [ ] **Step 1: `docs/retrieval.md`**

Edit 1 (`docs/retrieval.md`, the title), replace:

```markdown
# Retrieval: the governed corpus and the lexical baseline (T17)
```

with:

```markdown
# Retrieval: the governed corpus, the lexical baseline (T17) and exact vector search (T18)
```

Edit 2 (`docs/retrieval.md`, the end of "Sections and evidence IDs"), replace:

```markdown
is claimed; evaluating another window is part of T18's comparison.
```

with:

```markdown
is claimed. T18's comparison evaluated one other window as an experiment (adjacent sections of one version joined
until at least 300 words; `reports/retrieval-comparison.md`); the stored unit stays one chunk per section, because
another unit would change the evidence IDs every citation and T41's labels name.
```

Edit 3 (`docs/retrieval.md`, the threshold row), replace:

```markdown
| Threshold | rank greater than 0.25 (`app._min_rank()`, granted to nobody), chosen on the 47 development queries: the same queries measure it, so the baseline is a development figure, not a held-out one. Because the rank is not normalised the threshold depends on query length; tuning it is T18's, with the comparison |
```

with:

```markdown
| Threshold | rank greater than 0.25 (`app._min_rank()`, granted to nobody), chosen on the 47 development queries: the same queries measure it, so the baseline is a development figure, not a held-out one. Because the rank is not normalised the threshold depends on query length. T18's comparison swept it over the recorded ranks and left it at 0.25; a relevance rule beyond it is T20's (erratum 102) |
```

Edit 4 (`docs/retrieval.md`, the vector row), replace:

```markdown
| Vector mode | refused (`VECTOR_MODE_UNAVAILABLE`) until T18; mcp-read answers `vector_exact` with `UNSUPPORTED_MODE` first |
```

with:

```markdown
| Vector mode | exact cosine search (T18, revision 0013): `mode = 'vector'` with the query's `search_query:` embedding, which mcp-read computes; the same tenant, lifecycle and asset filters (the same SQL text); see "Exact vector search" below |
```

Edit 5 (`docs/retrieval.md`, the score paragraph), replace:

```markdown
comparable between two queries, and it is not comparable with T18's vector distances (BS:417). It never reaches the
model or the tool result; the measurement records it.
```

with:

```markdown
comparable between two queries, and it is not comparable with vector mode's cosine similarity (BS:417). It never
reaches the model or the tool result; the measurement records it.
```

Edit 6 (`docs/retrieval.md`, the end of the file), replace:

```markdown
size) and, for a proportion with no cases, no interval. T18 compares exact vector search against the same JSON.
```

with:

```markdown
size) and, for a proportion with no cases, no interval. T18 compares exact vector search against the same queries
(below).

## Exact vector search (T18)

**The model and its pin.** `nomic-embed-text` (Ollama `nomic-embed-text:latest`, 768 dimensions), pinned in
`data/embedding-pins.json` (`{model, digest, dimension, ollama_version, probed_at}`, schema
`schemas/embedding-pins.schema.json`), the generation model's `data/model-pins.json` untouched (erratum 107). The
digest is the bare 64-hex value `/api/tags` reports (`/api/show` carries none). `uv run python
scripts/pin_embedding_model.py` writes the file from the running Ollama (`/api/version`, `/api/tags`, one
`/api/embed` for the dimension) and invents nothing; re-run it only when the owner changes the model, and then embed
again in a new revision (one embedding per chunk).

**Embedding the corpus.** After `ingest`, `uv run python scripts/skeleton.py embed` embeds every stored chunk that has
none, as the role `worker`, into the database `OPS_PG_DB` names (default `ops`): it checks the pin against Ollama
(`OPS_OLLAMA_URL`, default `http://127.0.0.1:11434`) before writing, sends batches of 16 to `/api/embed`, accepts
only 768 finite non-zero numbers per input, and writes one transaction per tenant. A chunk's text is exactly
`search_document: ` + its heading + a blank line + its body (the prefix nomic-embed-text is trained with, SA:645), and
the row keeps that text's SHA-256 (`input_sha256`) beside the vector. It prints `EMBED: <tenant>: n new, n present`;
a repeat writes nothing. It exits 1 and writes nothing when the pin is missing or does not match the installed model,
or a tenant already holds embeddings of another digest; an unreachable Ollama exits 1 after the tenants already
written. Every stored chunk is embedded, whatever its status: lifecycle is decided at query time. Chunks ingested
later need another `embed` run; until then vector mode refuses (below) and lexical mode is unaffected.

| Setting | Value |
|---|---|
| Store | `app.embeddings`, one row per chunk (`tenant_id`, `evidence_id`), model, digest, dimension 768, `input_sha256`, `public.vector(768)`; written by `worker`, read only by the search (AM-20.2's corpus cells), ENABLE + FORCE RLS |
| Query text | `search_query: ` + the query (mcp-read computes it, SA:348) |
| Filters | the lexical branch's tenant, lifecycle and asset filters, the same SQL text byte for byte |
| Distance | cosine (`<=>`); `rank` = `1 - distance`, the cosine similarity |
| Index | none: every permitted chunk is scored, so the order is exact (a live test compares it with a brute-force ranking); BS:242's "index version" is model + digest + dimension + prefix + window |
| Threshold | similarity greater than 0.68 (`app._min_similarity()`, granted to nobody), the largest value on a 0.01 grid at which vector hit@5 over the labelled development cases equals its value at 0: a rule fixed before measuring, applied to the development queries, so a development figure |
| Ties | `evidence_id` ascending in byte order (`COLLATE "C"`), as lexical |
| Completeness | a permitted chunk with no embedding refuses the call (`EMBEDDINGS_INCOMPLETE`): nothing is left out silently |
| Arguments | `lexical` takes no embedding; `vector` one non-zero embedding of exactly 768 dimensions; the text query is required and bounded in both; anything else is `BAD_ARGUMENT` |
| Results | the same keys, excerpt bound, instant and corpus version as lexical; the tool reports `retrieval_mode` `vector_exact` |

**How to read a similarity.** Cosine similarity orders the sections of one query by the angle between their
embeddings; it is not a probability, it is not comparable between queries in any calibrated way, and it is not
comparable with `ts_rank_cd` (BS:417). Like the lexical rank it never reaches the model or the tool result.

**The comparison.** `tests/e2e/test_retrieval_comparison_live.py` runs the 47 development queries through the definer
in both modes at the labelling instant and writes `reports/retrieval-comparison.md` and `.json`: both modes' metrics at
k = 5 and 3 with Wilson intervals and denominators, per category, every case's two answers, the questions each mode
gained or lost, exact McNemar tests on hit@5 and on the no-source cases answered with nothing (no ranking claim
without p < 0.05; with this few cases a test has little power), both threshold sweeps, the window experiment, a
repeat-embedding check and the settings. It asserts that no forbidden section reached either mode and that the lexical
answers are T17's, answer for answer.
```

- [ ] **Step 2: `docs/runbooks/mcp-read.md`**

Edit 7 (`docs/runbooks/mcp-read.md`, "Starting it"), replace:

```markdown
`python -m ops_mcp_read` (or `scripts/skeleton.py up`) needs the database at revision 0012: at start it refuses when
`app.test_clock` exists outside the test profile, when `app._resolve_handle` lacks 0009's job binding, when
`app.search_procedures_scoped` (0011) is missing, and when `app.asset_scope` or the search's `retrieved_at` (0012) is
missing ("… predates this service; run scripts/skeleton.py migrate for this profile"). It also reads its own
```

with:

```markdown
`python -m ops_mcp_read` (or `scripts/skeleton.py up`) needs the database at revision 0013: at start it refuses when
`app.test_clock` exists outside the test profile, when `app._resolve_handle` lacks 0009's job binding, when
`app.search_procedures_scoped` (0011) is missing, when `app.asset_scope` or the search's `retrieved_at` (0012) is
missing, and when the search has no vector branch (0013) ("… predates this service; run scripts/skeleton.py migrate
for this profile"). It contacts no Ollama at start: the embedding pin is checked on each vector call. It also reads its own
```

Edit 8 (`docs/runbooks/mcp-read.md`, the units paragraph), replace:

```markdown
call resolves the handle and checks the tool in one committed unit, then (a `vector_exact` search stops after the
first) reads the run's scope through `app.asset_scope` in a second (the handle again, and the run's requester must
```

with:

```markdown
call resolves the handle and checks the tool in one committed unit, then reads the run's scope through
`app.asset_scope` in a second (the handle again, and the run's requester must
```

Edit 9 (`docs/runbooks/mcp-read.md`, the search bullet), replace:

```markdown
- `search_procedures(query 1-500, limit 1-8, mode[, asset_type])`: `vector_exact` is refused `UNSUPPORTED_MODE`
  after the handle resolution and before anything else (T18). mcp-read asks asset-sim for the run's asset type and
```

with:

```markdown
- `search_procedures(query 1-500, limit 1-8, mode[, asset_type])`: `lexical` or `vector_exact` (T18). mcp-read asks
  asset-sim for the run's asset type and
```

Edit 10 (`docs/runbooks/mcp-read.md`, the end of the same bullet), replace:

```markdown
  characters, and a cut one sets `truncated`. The settings and how to read the ranking are in `docs/retrieval.md`.
```

with:

```markdown
  characters, and a cut one sets `truncated`. The settings and how to read the ranking are in `docs/retrieval.md`.
  For `vector_exact`, after the asset type and before the third unit, mcp-read reads `data/embedding-pins.json`,
  checks the pinned digest against Ollama's `/api/tags` (`OPS_OLLAMA_URL`) and embeds `search_query: ` + the query
  with `/api/embed`, both within one 10-second budget and outside any transaction, then calls the definer with
  `mode='vector'` and that embedding; the answer says `retrieval_mode` `vector_exact`. It asks Ollama nothing else
  and never a generation. A missing or malformed pin, or an installed model that is not the pinned one, is
  `UNSUPPORTED_MODE` (`retryable: false`); Ollama unreachable, slow or failing (5xx) is `UNAVAILABLE`
  (`retryable: true`); an answer that is not 768 finite numbers is `UPSTREAM_INVALID`; a permitted section without an
  embedding is `REFUSED` with `EMBEDDINGS_INCOMPLETE`. An invalid handle is refused before any of this.
```

Edit 11 (`docs/runbooks/mcp-read.md`, the variables table), replace:

```markdown
| `OPS_ASSET_SIM_URL` | `http://127.0.0.1:8091` | where it calls asset-sim (T16) |
```

with:

```markdown
| `OPS_ASSET_SIM_URL` | `http://127.0.0.1:8091` | where it calls asset-sim (T16) |
| `OPS_OLLAMA_URL` | `http://127.0.0.1:11434` | where it asks the embedding model for `/api/tags` and `/api/embed` (T18) |
```

Edit 12 (`docs/runbooks/mcp-read.md`, "When something looks wrong", after the `UNAVAILABLE` bullet), replace:

```markdown
- **A handle in a log line** is a bug (SA:566): the live test `tests/e2e/test_mcp_read_t15_live.py` captures every
```

with:

```markdown
- **Every `vector_exact` search answers `UNSUPPORTED_MODE`**: `data/embedding-pins.json` is missing or malformed, or
  the installed `nomic-embed-text` is another build than the pin (`curl -s http://127.0.0.1:11434/api/tags` shows its
  digest). Do not edit the pin by hand: a model change is a re-embedding (`docs/retrieval.md`).
- **`vector_exact` answers `REFUSED` `EMBEDDINGS_INCOMPLETE`**: chunks were ingested and not embedded; run
  `uv run python scripts/skeleton.py embed` (dev database: the owner's step). Lexical searches are unaffected.
- **`vector_exact` answers `UNAVAILABLE`**: Ollama is not answering on `OPS_OLLAMA_URL` (or asset-sim is down, as for
  every search); the worker does not use vector mode today.
- **A handle in a log line** is a bug (SA:566): the live test `tests/e2e/test_mcp_read_t15_live.py` captures every
```

Edit 13 (`docs/runbooks/mcp-read.md`, "Not here yet"), replace:

```markdown
Vector search and the `search_query:` embedding (T18), the worker's own asset reads and the evidence bundle (T20),
```

with:

```markdown
The worker's choice of vector mode (T20, T25), the worker's own asset reads and the evidence bundle (T20),
```

Edit 14 (`docs/runbooks/mcp-read.md`, "Not here yet", the container line), replace:

```markdown
recording the status observation for the grant's freshness check (T21), TLS and container host names (T30). The
```

with:

```markdown
recording the status observation for the grant's freshness check (T21), TLS, container host names and the route
from a containerised mcp-read to Ollama (T30). The
```

- [ ] **Step 3: `docs/runbooks/walking-skeleton.md`**

Edit 15 (`docs/runbooks/walking-skeleton.md`, step 2), replace:

```markdown
   governed corpus (`data/corpus`, T17) as the worker; without it every investigation ends INSUFFICIENT_EVIDENCE, and a
   repeated run writes nothing (`docs/retrieval.md`).
```

with:

```markdown
   governed corpus (`data/corpus`, T17) as the worker; without it every investigation ends INSUFFICIENT_EVIDENCE, and a
   repeated run writes nothing (`docs/retrieval.md`). Then `uv run python scripts/skeleton.py embed` embeds the stored
   chunks through local Ollama with the pinned `nomic-embed-text` (T18); without it `vector_exact` searches refuse
   (`EMBEDDINGS_INCOMPLETE`) and lexical ones work.
```

Edit 16 (`docs/runbooks/walking-skeleton.md`, step 3), replace:

```markdown
   The dev database must carry revision 0012 (`skeleton.py migrate`) before `up`: mcp-read's own startup check refuses anything older (the API needs 0007 and the sweeper 0008), so on a database still at 0011 `up` leaves mcp-read down until the owner migrates it. The browser login walk-through is in `dev-topology.md`.
```

with:

```markdown
   The dev database must carry revision 0013 (`skeleton.py migrate`) before `up`: mcp-read's own startup check refuses anything older (the API needs 0007 and the sweeper 0008), so on a database still at 0012 or below `up` leaves mcp-read down until the owner migrates it. The browser login walk-through is in `dev-topology.md`.
```

- [ ] **Step 4: `docs/ARCHITECTURE.md` and the ADR note (erratum 108)**

Edit 17 (`docs/ARCHITECTURE.md`, the diagram's model node), replace:

```markdown
  OL[Ollama qwen3:8b]
```

with:

```markdown
  OL[Ollama qwen3:8b, nomic-embed-text]
```

Edit 18 (`docs/ARCHITECTURE.md`, the diagram's edges), replace:

```markdown
  MR --> AS
```

with:

```markdown
  MR --> AS
  MR -->|query embeddings only| OL
```

Edit 19 (`docs/ARCHITECTURE.md`, mcp-read's principal row), replace:

```markdown
| `mcp-read` | Keycloak client; DB role `mcp_read` | **no tables**; `EXECUTE` on `resolve_invocation`, `asset_scope`, `search_procedures_scoped` | PostgreSQL (functions), asset-sim | any write-path function; incident-sim |
```

with:

```markdown
| `mcp-read` | Keycloak client; DB role `mcp_read` | **no tables**; `EXECUTE` on `resolve_invocation`, `asset_scope`, `search_procedures_scoped` | PostgreSQL (functions), asset-sim, Ollama (`/api/tags` and `/api/embed` with the embedding model only, T18) | any write-path function; incident-sim; a generation request |
```

Edit 20 (`docs/ARCHITECTURE.md`, after section 10), replace:

```markdown
## Where the code will live (not yet written)
```

with:

```markdown
## 11. Exact vector retrieval (built in T18)

**Claim.** A vector search returns exactly what a lexical search may return, ranked by the pinned embedding model, and
the model that ranks it cannot act: mcp-read asks Ollama for one query embedding, never for text.

- **One filter text.** The vector branch of `search_procedures_scoped` repeats the lexical branch's tenant, lifecycle
  and asset filters byte for byte, and refuses (`EMBEDDINGS_INCOMPLETE`) rather than silently dropping a permitted
  section without an embedding.
- **A pinned model on both sides.** `data/embedding-pins.json` names the model, its digest and its 768 dimensions;
  `skeleton.py embed` checks it before writing and mcp-read before each vector call, so a swapped model is refused,
  not used; each stored row keeps the SHA-256 of the prefixed text it was made from.
- **mcp-read → Ollama (erratum 108).** SA:348 and SA:461 make mcp-read compute the query embedding, so mcp-read
  reaches Ollama for `/api/tags` and `/api/embed` with the embedding model only; BS:646's MCP row, BS:144's diagram
  and ADR-0001's boundary list did not name that edge. It is not a generation, so it holds no `model_permit` (SA:203).
- **Exact by construction.** No vector index: every permitted chunk is scored; a live test compares the definer's
  order with a brute-force ranking of the stored vectors.

| Requirement | What its test shows |
|---|---|
| R034 | Both modes on the 47 development queries with denominators, Wilson intervals, per-category rows, matched questions and exact McNemar tests; no forbidden section in either; the lexical answers unchanged since T17 (`reports/retrieval-comparison.md`) |

---

## Where the code will live (not yet written)
```

Edit 21 (`docs/adr/ADR-0001-deployable-units-as-top-level-directories.md`, the end of the file), replace:

```markdown
- The two synthetic services (`asset-sim/`, `incident-sim/`) are separate on purpose. The destination needs an independent database and credentials (§14). The read API does not.
```

with:

```markdown
- The two synthetic services (`asset-sim/`, `incident-sim/`) are separate on purpose. The destination needs an independent database and credentials (§14). The read API does not.

## Note (2026-10-19, T18, proposed erratum 108)

The decision above stands. One network edge is added to the boundary list: mcp-read → Ollama, for `/api/tags` and
`/api/embed` with the embedding model only, never a generation. SA:348 and SA:461 make mcp-read compute the
`search_query:` embedding of a vector search, which the boundary list (written before vector mode was designed) did
not name. The owner decides the erratum; `docs/ARCHITECTURE.md` section 11 records the edge.
```

- [ ] **Step 5: Commit**

Check: `grep -n "T18's comparison\|refused (\`VECTOR_MODE_UNAVAILABLE\`)\|arrives with T18" docs/retrieval.md
docs/runbooks/mcp-read.md` prints nothing.

```bash
git add docs/retrieval.md docs/runbooks/mcp-read.md docs/runbooks/walking-skeleton.md docs/ARCHITECTURE.md \
  docs/adr/ADR-0001-deployable-units-as-top-level-directories.md
git commit -m "docs: exact vector search, the embedding pin, mcp-read's vector mode and its Ollama edge (T18)"
```

---

### Task 8: Close-out — records, acceptance rows, errata 107-111, state, history, final gates

**Files:**
- Modify: `handoff/tasks.json` (T18 → `DONE` with a review note), `handoff/acceptance-matrix.json` (R034, R033's note),
  `handoff/BUILD_BACKLOG.md` (T18 checked; its note), `SESSION_STATE.md` (the "Next task" line, a "Plan N executed"
  section, the environment row, the dev database state, the owner inputs), `STATUS.md` (an update section),
  `docs/PROJECT_HISTORY.md` (a new section 31; "What the process taught" becomes 32), this plan (its checkboxes); the
  report pair and the files the final live run rewrites

**Requirements:** the T18 record (R034 evidenced; DoD 1 and 2); every deferral to T18 in live code and documentation
resolved or re-homed. This task writes no behaviour.

Throughout, `<base>..<last>` is the git range of this plan's execution on `plan-n` (`<base>` the `BASE` of Task 1
Step 1b, excluded; `<last>` the newest commit before this task's own). `<date>` is `date -u +%F`. Step 4 replaces
every placeholder.

- [ ] **Step 1: Handoff records**

Save this outside the repository as `t18_records.py` and run `BASE=<hash> uv run python <path>/t18_records.py` (a
script file, never standard input). It stops if the report is missing (rerun the live gate first).

```python
import json
import os
import subprocess
from pathlib import Path

base = os.environ["BASE"]
last = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True).stdout
subprocess.run(["git", "merge-base", "--is-ancestor", base, "HEAD"], check=True)  # the base is this branch's own
span = f"{base}..{last.strip()}"
report = json.loads(Path("reports/retrieval-comparison.json").read_text(encoding="utf-8"))
lexical, vector = report["summary"]["lexical"]["5"], report["summary"]["vector_exact"]["5"]
paired = report["paired"]


def rate(item: dict) -> str:
    return f"{item['successes']}/{item['n']}"


figures = (
    f"lexical hit@5 {rate(lexical['hit_at_k'])}, vector {rate(vector['hit_at_k'])}; no-source answered empty lexical "
    f"{rate(lexical['none_answered_empty'])}, vector {rate(vector['none_answered_empty'])}; McNemar p "
    f"{paired['hit_at_5']['mcnemar_p']} (hit@5) and {paired['none_answered_empty']['mcnemar_p']} (answered empty), so "
    "no ranking claim at p < 0.05 unless the report says otherwise"
)
note = (
    f"Plan N (branch plan-n): done in {span} (the debt list, then the seven tasks; the close-out is the next commit; plan "
    "docs/superpowers/plans/2026-10-19-first-slice-n-vector-retrieval.md). Shipped: data/embedding-pins.json "
    "(nomic-embed-text, the /api/tags digest, 768 dimensions, Ollama 0.40.4; schema and loader; "
    "scripts/pin_embedding_model.py); ops_core.embeddings (the search_document:/search_query: builders, the Ollama "
    "client: /api/tags and /api/embed only, 10 s, no retry); revision 0013_embeddings (app.embeddings, one row per "
    "chunk with input_sha256, worker INSERT+SELECT, app_definer SELECT, FORCE RLS, no index; app._min_similarity() "
    "0.68 by the rule fixed before measuring; search_procedures_scoped re-created from 0012's body with a vector "
    "branch under the same filter text, cosine similarity, byte-order ties, EMBEDDINGS_INCOMPLETE, the argument rule; "
    "exact downgrade); scripts/skeleton.py embed (as worker, the pin checked first, a mixed store refused, a repeat "
    "writes nothing); mcp-read's vector_exact (the pin checked and the query embedded after the scope and the asset "
    "type; UNSUPPORTED_MODE, UNAVAILABLE retryable, UPSTREAM_INVALID; retrieval_mode reported); the comparison "
    f"reports/retrieval-comparison.md/.json ({figures}; zero forbidden rows in both modes; the lexical answers equal "
    "T17's). DoD 1: the report with recall@k for both methods at k = 5 and 3, denominators and Wilson CIs. DoD 2: "
    "tests/plan_n/test_embeddings.py asserts the request bodies; tests/e2e/test_vector_retrieval_live.py proves every "
    "stored input_sha256 and one stored vector against fresh prefixed and unprefixed embeddings. Deferred: the "
    "worker's mode choice -> T20/T25; a relevance rule beyond the thresholds -> T20; numeric tokens -> T23; the "
    "container route to Ollama and packaging the pin -> T30. Errata 107-111 are proposed in SESSION_STATE.md; the dev "
    "database waits for the owner's migrate to 0013 and skeleton.py embed."
)
tasks_path = Path("handoff/tasks.json")
tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
t18 = next(t for t in tasks["tasks"] if t["id"] == "T18")
assert t18["status"] == "PLANNED" and len(t18["review_notes"]) == 1
t18["status"] = "DONE"
t18["review_notes"].append(note)
tasks_path.write_text(json.dumps(tasks, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

matrix_path = Path("handoff/acceptance-matrix.json")
matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
r034_note = (
    "Plan N (T18): nomic-embed-text (digest 0a109f42...e59f, 768 dimensions, data/embedding-pins.json) over corpus-1 "
    "(lock 81f50c2b...1862), 47 development queries at the labelling instant, both modes through "
    f"search_procedures_scoped as mcp_read at k = 5 and 3: {figures}. Every case's two answers, the improved and "
    "regressed questions by id, per-category rows, both threshold sweeps, a 300-word window experiment and a "
    "repeat-embedding check are in reports/retrieval-comparison.md and .json. Exact by construction (no index) and "
    "proven against a brute-force ranking of the stored vectors (tests/e2e/test_vector_retrieval_live.py). The vector "
    "threshold (0.68) was chosen on these same queries by a rule fixed before measuring: development figures, not "
    "held-out ones (the holdout is T25's)."
)
for row in matrix["requirements"]:
    if row["id"] == "R034":
        row["implementation_status"] = "IMPLEMENTED_LOCALLY_VERIFIED"
        row["evidence_status"] = "RECORDED_LOCALLY_LIVE"
        row["evidence_paths"] = [
            "reports/retrieval-comparison.md",
            "reports/retrieval-comparison.json",
            "tests/e2e/test_retrieval_comparison_live.py",
            "tests/e2e/test_vector_retrieval_live.py",
            "tests/e2e/test_migration_0013_live.py",
            "tests/plan_n/",
            "data/embedding-pins.json",
        ]
        row["note"] = r034_note
    elif row["id"] == "R033":
        assert row["note"].endswith("so the figures are development figures, not held-out ones.")
        row["note"] += (
            " T18 (Plan N) re-measured the lexical path in the same session as the vector comparison: its per-case "
            "answers equal this baseline's (reports/retrieval-comparison.md)."
        )
matrix_path.write_text(json.dumps(matrix, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

backlog_path = Path("handoff/BUILD_BACKLOG.md")
lines = backlog_path.read_text(encoding="utf-8").split("\n")
head = "- [ ] **T18 Exact pgvector retrieval and comparison**"
assert sum(line.startswith(head) for line in lines) == 1
at = next(i for i, line in enumerate(lines) if line.startswith(head))
lines[at] = lines[at].replace("- [ ]", "- [x]", 1)
at += 1
while lines[at].startswith("  - "):
    at += 1
lines.insert(at, f"  - *Review note:* {note}")
backlog_path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
print(span)
```

Expected: it prints the span. `git diff --stat handoff` shows three files changed; `git diff
handoff/acceptance-matrix.json` shows two rows, R033 and R034.

- [ ] **Step 2: Project state**

Edit 1 (`SESSION_STATE.md`, the milestone line), replace:

```markdown
**Current milestone:** M06 (vector retrieval; T18 is its open task. M05, the MCP servers and the governed corpus, closed with T16 in Plan M. Every task of M00 to M05 is DONE or DONE_PENDING_OWNER, and the owner steps of M00 and M01 are listed below)
```

with:

```markdown
**Current milestone:** M06 (vector retrieval; T18 is DONE in Plan N, and T41, the owner's holdout labels, is its open task. M05 closed with T16 in Plan M. Every task of M00 to M05 is DONE or DONE_PENDING_OWNER, and the owner steps of M00 and M01 are listed below)
```

Edit 2 (`SESSION_STATE.md`, "Next task"), replace:

```markdown
**Next task:** Plan M (T16) is executed on branch `plan-m` (from `main`: `9e7d716..bbaba40` holds the debt list and the
```

with:

```markdown
**Next task:** Plan N (T18) is executed on branch `plan-n` (`<base>..<last>` holds the debt list and the seven
building tasks; the close-out is the commit after `<last>`). T18 is DONE: R034 is evidenced
(`reports/retrieval-comparison.md`); errata 107-111 are proposed. Owner inputs added by Plan N: migrate the dev
database to revision 0013 (after 0012), then `uv run python scripts/skeleton.py embed`; push `plan-n` and open its PR
after the final review. Next is T23 (unblocked); T19 and T41 wait on owner steps, T20 on T19, T25 on T22, T23 and
T41. The Plan M record follows.
**Plan M record:** Plan M (T16) is executed on branch `plan-m` (from `main`: `9e7d716..bbaba40` holds the debt list and the
```

Edit 3 (`SESSION_STATE.md`, the environment row), replace:

```markdown
| Ollama | Observed at 0.40.4 on 2026-10-15 (recorded 0.33.3 before; Plan J did not change it, and per AM-30 an upgrade is the owner's decision, so this records the observation and claims nothing either way); `qwen3:8b` and `nomic-embed-text` installed as last recorded |
```

with:

```markdown
| Ollama | Observed at 0.40.4 on 2026-10-15 (recorded 0.33.3 before; Plan J did not change it, and per AM-30 an upgrade is the owner's decision, so this records the observation and claims nothing either way); `qwen3:8b` and `nomic-embed-text` installed as last recorded. Plan N pinned `nomic-embed-text:latest` at digest `0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f`, 768 dimensions, on 0.40.4 (`data/embedding-pins.json`, <date>) |
```

Edit 4 (`SESSION_STATE.md`, before the walking-skeleton debt list), replace:

```markdown
## Walking-skeleton debt list (T08; committed before coding) [R6-B7]
```

with:

```markdown
## Plan N executed (<date>, branch `plan-n`)

- T18 = `<base>..<last>` (the debt list first, then the seven building tasks; the close-out is the commit after
  `<last>`). The plan (`docs/superpowers/plans/2026-10-19-first-slice-n-vector-retrieval.md`) holds the 18 rulings of
  the controller's brief as implemented, with eleven departures named at its top; the input is
  `docs/superpowers/research/2026-10-19-plan-n-inputs.md`. Evidence: `reports/retrieval-comparison.md` and `.json`,
  `tests/e2e/test_retrieval_comparison_live.py`, `test_vector_retrieval_live.py`, `test_migration_0013_live.py`
  (live); `tests/plan_n/` (unit); `data/embedding-pins.json`.
- Shipped: the embedding pin and its schema; `ops_core.embeddings`; revision `0013_embeddings` (`app.embeddings`,
  `app._min_similarity()` 0.68, the vector branch; exact downgrade to 0012); `scripts/skeleton.py embed`; mcp-read's
  `vector_exact`; the comparison report.
- Gates: `check.py` `<dev>`; `check.py --profile test` `<live>`; `verify_handoff.py` exit 0.
- **Proposed errata (the owner decides; the spec text stays authoritative until then).** Numbered on from Plan M's
  hundred and six:
  107. SA:598 and SA:768 (`data/model-pins.json`): the file stays the generation model's (T02, T19); the embedding
       model's pin is `data/embedding-pins.json` (`{model, digest, dimension, ollama_version, probed_at}`, schema
       `schemas/embedding-pins.schema.json`, `ops_core.model_pins.load_embedding_pins`), verified against the digest
       `/api/tags` reports (AM-31 names `/api/show`, which carries none, as T19's note found for qwen3:8b), by
       `scripts/skeleton.py embed` before it writes and by mcp-read on every vector call; a mismatch or a missing pin
       makes `embed` exit 1 writing nothing and mcp-read answer `UNSUPPORTED_MODE`.
  108. BS:646 (the MCP row), BS:144 (the diagram), ADR-0001:31 and `docs/ARCHITECTURE.md`: mcp-read → Ollama,
       `/api/tags` and `/api/embed` with the embedding model only, never generation, because SA:348 and SA:461 make
       mcp-read compute the query embedding; recorded in `docs/ARCHITECTURE.md` section 11 and as a dated note under
       ADR-0001. The call is not a `model_permit` holder: SA:203's global model concurrency governs generation.
  109. SA:584 (`pgvector-python` 0.5.0): unused, not violated: vectors cross as pgvector's text form cast in SQL
       (`%s::public.vector`, `repr` floats, `ops_core.embeddings.vector_literal`), so no dependency or adapter is
       added; tests read vectors back by parsing the text form.
  110. SA:461 (`search_procedures_scoped`): `mode` is `lexical` or `vector`; `query` is required and bounded 1-500 in
       both modes; `vector` requires one non-zero embedding of exactly 768 dimensions and `lexical` none, else `OC005`
       `BAD_ARGUMENT`; in vector mode a permitted chunk without an embedding refuses the call (`OC005`
       `EMBEDDINGS_INCOMPLETE`) instead of being left out; the stop-word early return is lexical only;
       `VECTOR_MODE_UNAVAILABLE` (erratum 99) is gone.
  111. BS:242 and BS:417: in vector mode `rank` is the cosine similarity `1 - (embedding <=> query)`, ordered with the
       lexical tie-break and kept above `app._min_similarity()` (0.68), a development figure chosen on the 47
       development queries by a rule fixed before measuring (the largest value on a 0.01 grid at which vector hit@5
       over the labelled cases equals its value at 0); it is not comparable with `ts_rank_cd`. BS:242's "index
       version" is recorded as model + digest + dimension + prefix + window: there is no vector index, and the search
       is exact by construction.
- The installed Ollama is 0.40.4; SA:587 records 0.33.3 ("upgrade only with owner approval"). The upgrade predates
  this plan; the pin records the version actually used, and nothing here changed it. The owner decides.
- Rulings made during execution (the controller's, from the SDD ledger): none yet; the executor lists them here.

## Walking-skeleton debt list (T08; committed before coding) [R6-B7]
```

Edit 5 (`SESSION_STATE.md`, the end of "Dev database state", before "Open owner inputs"), replace:

```markdown
## Open owner inputs
```

with:

```markdown
**Update (<date>):** Plan N adds revision 0013 (`app.embeddings`, `app._min_similarity()`, and
`app.search_procedures_scoped` re-created with its vector branch; return type unchanged). The dev `ops` database stays
where it is until the owner runs `uv run python scripts/skeleton.py migrate` (dev profile; it applies 0012 too if that
is still missing) and then `uv run python scripts/skeleton.py embed` (as the worker, through local Ollama; it prints
`EMBED: alpha: 39 new, 0 present` and `EMBED: beta: 30 new, 0 present` on corpus-1, the first time). Until the
migration mcp-read refuses to start on it; until `embed`, vector searches answer `REFUSED`/`EMBEDDINGS_INCOMPLETE`
and lexical ones work.

## Open owner inputs
```

Edit 6 (`SESSION_STATE.md`, "Open owner inputs"), replace:

```markdown
  executed") and 103-106 (see "Plan M executed").
- Migrate the dev database to revision 0012 (`uv run python scripts/skeleton.py migrate`); mcp-read refuses to start
  on 0011.
```

with:

```markdown
  executed"), 103-106 (see "Plan M executed") and 107-111 (see "Plan N executed").
- Migrate the dev database to revision 0013 (`uv run python scripts/skeleton.py migrate`), then embed it (`uv run
  python scripts/skeleton.py embed`); mcp-read refuses to start below 0013.
- Decide on the installed Ollama 0.40.4 against SA:587's 0.33.3 (the embedding pin records 0.40.4).
```

Edit 7 (`STATUS.md`, at the end), replace:

```markdown
- Next: T18 (vector retrieval, now with mcp-read's vector mode) or T23.
```

with:

```markdown
- Next: T18 (vector retrieval, now with mcp-read's vector mode) or T23.

## Update — Plan N executed (<date>, branch `plan-n`)

- Plan N (T18: exact pgvector retrieval and the comparison) executed on branch `plan-n` (`<base>..<last>`). The plan
  is `docs/superpowers/plans/2026-10-19-first-slice-n-vector-retrieval.md`.
- `PYTHONUTF8=1 uv run python scripts/check.py` is `CHECK: GREEN`: pytest `<dev>`.
  `PYTHONUTF8=1 uv run python scripts/check.py --profile test` is `CHECK: GREEN`: pytest `<live>`.
  `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts` exits 0.
- **Evidenced** (`IMPLEMENTED_LOCALLY_VERIFIED`, `RECORDED_LOCALLY_LIVE`): R034 — exact vector search measured
  against the lexical baseline on the 47 development queries (`reports/retrieval-comparison.md`: both modes at k = 5
  and 3 with denominators and Wilson intervals, matched questions, exact McNemar tests, no forbidden section in either
  mode, the lexical answers unchanged since T17).
- Also built: the embedding pin (`data/embedding-pins.json`); `ops_core.embeddings`; revision 0013; `skeleton.py
  embed`; mcp-read's `vector_exact`.
- The dev `ops` database waits for the owner's migrate to 0013 and `skeleton.py embed`.
- Deferred, each with its owner in `SESSION_STATE.md`: the worker's mode choice -> T20/T25; a relevance rule -> T20;
  numeric tokens -> T23; the container route to Ollama -> T30. Five errata (107-111) are proposed.
- Next: T23 (the development eval set).
```

Edit 8 (`docs/PROJECT_HISTORY.md`, before the last section), replace:

```markdown
## 31. What the process taught
```

with:

```markdown
## 31. The vector plan measured a second retrieval method against the first

**Problem.** Plan N takes T18. The corpus had no embeddings, `search_procedures_scoped` refused vector mode, mcp-read
answered `vector_exact` with `UNSUPPORTED_MODE`, and nothing pinned the embedding model. The fact sheet found eighteen
open questions, and the controller's brief ruled on each: a separate `embeddings` table, an operator command to fill
it, a sibling pin file, the query embedding in mcp-read, the lexical filters reused verbatim, cosine similarity under
a threshold chosen by a rule fixed before measuring, no index, and a report that re-measures lexical search in the
same session.

**Change.** Revision 0013 adds the table and the vector branch; `skeleton.py embed` fills it from each section's
prefixed text and keeps that text's hash; mcp-read checks the pin and embeds the query before the third unit; the live
comparison writes `reports/retrieval-comparison.md`. <execution>

**Review.** Writing the plan against the code moved several details. pgvector's operator lives in `public` and the
definers pin `search_path = app, pg_temp`, so the branch spells `OPERATOR(public.<=>)`. A zero vector has a NaN cosine,
and PostgreSQL sorts NaN above every number, so it became a `BAD_ARGUMENT`. The live baseline test rewrites the T17
report on every run before the comparison runs, so the lexical answers are pinned by a digest computed from the
committed file. The threshold rule was run against local Ollama before the revision was written: it chose 0.68.

## 32. What the process taught
```

- [ ] **Step 3: Final gates and the evidence**

With the dev stack up, local Ollama answering and every skeleton process down: `PYTHONUTF8=1 uv run python
scripts/check.py` → `CHECK: GREEN`, pytest `1429 passed, 214 skipped`; `PYTHONUTF8=1 uv run python scripts/check.py
--profile test` → `CHECK: GREEN`, pytest `1622 passed, 21 skipped` (or the measured counts; Step 4 writes what was
measured); `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts` → exit 0. Then `git
checkout -- reports/bootstrap reports/skeleton reports/auth reports/admission reports/leases reports/events
reports/outbox reports/mcp-read reports/mcp-write reports/asset-sim reports/retrieval`, and keep, from this run,
`reports/retrieval-comparison.md` and `.json`. Read the md: its lexical rows must equal T17's report (hit@5 27/27,
answered-empty 15/20) and its forbidden rows must be 0 in both modes.

- [ ] **Step 4: Fill in the placeholders and commit**

Replace `<base>`, `<last>`, `<date>`, `<dev>` and `<live>` everywhere this task wrote them, and `<execution>` in
`docs/PROJECT_HISTORY.md` with two sentences: the measured vector and lexical hit@5 and answered-empty figures with
their McNemar p-values, and the gates. Check: `grep -rn "<base>\|<last>\|<date>\|<dev>\|<live>\|<execution>"
SESSION_STATE.md STATUS.md docs/PROJECT_HISTORY.md` → no output. Tick this plan's checkboxes.

```bash
git add handoff/tasks.json handoff/acceptance-matrix.json handoff/BUILD_BACKLOG.md SESSION_STATE.md STATUS.md \
  docs/PROJECT_HISTORY.md reports/retrieval-comparison.md reports/retrieval-comparison.json \
  docs/superpowers/plans/2026-10-19-first-slice-n-vector-retrieval.md
git commit -m "docs: close T18 - handoff records, R034, errata 107-111, the comparison report (Plan N)"
```

`git status --short` then prints nothing.

---

## Review Focus

1. **The SQL has not run.** Revision 0013's bodies were rendered, bind-scanned and reverse-checked against 0012 on the
   scratch copy, but no database executed them. Watch in the first live run: `OPERATOR(public.<=>)` and the
   schema-qualified `public.vector_dims`/`public.vector_norm` (the definer's `search_path` is `app, pg_temp`, and the
   extension lives in `public`, `scripts/skeleton.py:184-186`); the aggregate `SELECT … , EXISTS (SELECT 1 FROM scored
   s WHERE s.unembedded) INTO results, v_incomplete FROM kept k` (an uncorrelated subquery beside an aggregate, the CTEs
   visible to it); the LEFT JOIN `USING (tenant_id, evidence_id)` after a JOIN `USING (tenant_id, document_id,
   version)`; and `e.embedding IS NULL` for a missing row (the column is NOT NULL, so NULL means no row).
2. **CREATE OR REPLACE keeps the grant.** PostgreSQL keeps a replaced function's owner and privileges; the revision
   applies `function_grant_statements` again all the same (idempotent), and `test_the_round_trip_restores_0012` asserts
   the ACL is equal in both directions. A failure there means a replaced function lost its ACL: then switch 0013 to
   0012's DROP + CREATE + grant and say so in the report.
3. **pgvector sums in single precision.** `vector` stores float4, and the cosine is accumulated in float, so the
   definer's similarity and Python's double-precision cosine of the same stored vectors differ around 1e-7. The
   exactness test compares the order exactly and the values to 1e-5. The pre-measurement found one pair of development
   candidates within 1e-5 of each other (B16, 4.9e-7 apart), well below the threshold, where no order is compared; a
   failure of the order elsewhere is a near-tie to report, not a bug to tune away.
4. **Ollama is part of the live gate now.** `embedded`, the vector live tests and the comparison call local Ollama
   (`OPS_OLLAMA_URL`, default loopback); the live gate already needed it (`tests/plan_b/live/test_ollama_bridge.py`).
   The first `embedded` use takes a few seconds; a live failure naming `UNAVAILABLE` or `PinMismatch` is the machine
   (Ollama down, or another model build), not the code.
5. **The round trips drop the embeddings.** `test_migration_0011_live.py`, `0012_live.py` and `0013_live.py` downgrade
   past 0013 and migrate back; the table comes back empty and the next `embedded` use re-embeds 69 sections. A vector
   test that ran without the `embedded` fixture after a round trip would see `EMBEDDINGS_INCOMPLETE`.
6. **mcp-read starts only on 0013.** Every mcp-read start, in-process or as a process (R105's skeleton), now asks for
   `VECTOR_SEARCH`; the test databases are migrated to the head by the session fixture, the dev database is not.
7. **The pin is read per call.** mcp-read reads `data/embedding-pins.json` from the checkout on every vector call and
   checks it against `/api/tags`; packaging it for an image is T30's (debt list).

## Self-review (run by the plan's author before execution)

- **Spec coverage.** Every ruling has its task (the "Rulings" list names it); every debt pushed to T18 is closed or
  re-homed: the embeddings table, the prefixes and vector mode (Tasks 1, 3, 4, 5), tuning the minimum rank (ruling 9,
  measured and kept), another window (ruling 8, the experiment), the numeric-token lexemes (T23, debt list), mcp-read's
  `vector_exact` (Task 5, erratum 103's move completed), every live `TODO(T18)` (Tasks 3 and 5; departure 10). DoD 1:
  Task 6's report; DoD 2: Task 1's unit test and Task 4's live tests.
- **Signatures copied, not retyped.** The regprocedure argument list is read from `privileges.DEFINER_FUNCTIONS
  ["search_procedures_scoped"][0]` in `tests/plan_n/test_migration_0013.py` and is the literal of 0012's `SEARCH_ARGS`
  in the revision (`text, text, text, public.vector, text, integer, text`); the helper's signature is `app._min_similarity()`.
- **Measured, not assumed.** On the scratch copy of `6d00d06`: every hunk above applies to the repository's text
  exactly once (the edits were generated from that copy and re-applied to the repository's files by a script that
  checks uniqueness); `tests/plan_n` 52 passed; the dev suite 1429 passed, 214 skipped (13 git-dependent failures that
  pass in a checkout); ruff, ruff format and mypy strict clean on every member; `verify_handoff.py --contracts` PASS
  with 27 schemas and 93 examples; `scripts/pin_embedding_model.py` and `python -m scripts.retrieval_comparison
  threshold` ran against local Ollama (the pin above; `CHOSEN: 0.68`). Not measured: the per-step red states (stated
  from the import graph), and anything against a database or Keycloak (no service was reachable for the writer, by
  instruction).
- **Placeholders.** None in Tasks 1-7 except the measured value Task 2 Step 4 confirms; Task 8's `<base>`, `<last>`,
  `<date>`, `<dev>`, `<live>` and `<execution>` are filled by its Step 4, which greps for them.

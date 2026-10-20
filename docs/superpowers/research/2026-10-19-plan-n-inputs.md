# Plan N inputs: T18 (exact pgvector retrieval and comparison) — fact sheet

Prepared 2026-10-19 on branch `plan-n` at `e0d0d53` (= `plan-m` `e0d0d53`; PR #12 `plan-m` -> `main` is open and
unmerged; the working tree was clean). Read-only on the repository except this file. Facts only, no design.
Citations: `SA:<line>` = `SPEC_AMENDMENTS.md`, `BS:<line>` = `BUILD_SPEC.md` (line numbers as of `e0d0d53`); the
amendments win wherever the two conflict. Repository files are cited as `path:line`. Nothing was run against a
database, Keycloak, Ollama or any service for this sheet, no network connection was made, and no secret, token or
`.env` value was opened: every fact below is read from the files.

Note on line numbers: AM-00 superseded list SA:30-55 (§25 milestone table replaced, SA:42); AM-01 layout SA:68-91;
AM-12 heartbeat SA:192-198, async SA:201, model permit SA:203-205, graph SA:207; AM-15 SA:327-358 (vector-mode
sentence SA:348, schema rule SA:350, envelope SA:351-355); AM-16 graph router SA:377, model router SA:379; AM-20.1
roles SA:391-404 (`migrator` SA:395, `mcp_read` SA:400); AM-20.2 SA:406-442 (corpus row SA:431, "no table grants"
SA:437); AM-20.3 SA:444-474 (header SA:446, `asset_scope` SA:460, `search_procedures_scoped` SA:461, helpers
SA:474); AM-20.5 RLS SA:508-524 (table list SA:510); AM-20.6 clock SA:526-530; AM-20.7 item 6 SA:554-558; AM-30
versions SA:568-590 (pgvector-python SA:584, Ollama SA:587); AM-31 SA:593-620 (model SA:595, settings SA:596,
warm-up SA:597, digest SA:598, network SA:599-601, probe SA:602-620); AM-50 corpus SA:640-645 (prefixes SA:645),
evaluation SA:651-669 (conditions SA:660, statistics SA:664-669); AM-60 SA:680-728; AM-80 SA:743-778 (model-pins
SA:768, run manifest SA:770). BUILD_SPEC: scope BS:50, deferrals BS:54, stack table BS:69/BS:71, deployment
diagram BS:136-151 (BS:144, BS:147), data model BS:242, API BS:280, tools BS:386, §11 ingestion/retrieval
BS:411-419 (chunking BS:415, filtering BS:417, bundle BS:419), source changes BS:421-427, model BS:439-443, §17
budgets BS:540-560, metrics BS:609-611, §18 BS:572, Ollama placement BS:629, caller table BS:641-650, release
manifest BS:670, §25 M06 row BS:707, source S07 BS:781.

---

## 1. T18 verbatim, its acceptance rows, the debts pushed to it, and its consumers

### 1.1 T18 (`handoff/tasks.json:786-805`)

- **id/milestone/title:** `T18`, `M06` (`tasks.json:78-86`: title "Vector retrieval", `required_for_v1: true`,
  task_ids `T18`, `T41`, milestone `status: "PLANNED"`), "Exact pgvector retrieval and comparison" (`:788`).
  `status: "PLANNED"` (`:796`), `external_approval_required: false` (`:801`). The file's `current_milestone` is
  `"M06"` (`:3`).
- **instructions** (`:789`, verbatim): "nomic-embed-text with search_document:/search_query: prefixes (tested);
  record model, dimension, digest; exact search with the same filters; comparison report vs lexical."
- **depends_on** (`:790-792`): `["T17"]` (T17 `DONE`, `:738`).
- **requirement_ids** (`:793-795`): `R034`.
- **definition_of_done** (`:797-800`, verbatim):
  1. "reports/retrieval-comparison.md with recall@k for both methods, denominators and CIs."
  2. "Prefix application asserted by a test."
- **review_notes** (`:802-804`, verbatim, the only one): "From T16 (Plan M ruling 1, erratum 103): mcp-read's
  vector_exact -> mode=vector translation and the nomic search_query embedding it computes and passes to
  search_procedures_scoped (T16's instruction and review note moved here); until then mcp-read answers vector_exact
  with UNSUPPORTED_MODE after the handle resolution (server.py and routing.py carry TODO(T18))."
- `handoff/BUILD_BACKLOG.md:113` "## M06 — Vector retrieval"; `:115` repeats the instructions unchecked (`- [ ]`,
  "Requirements: R034. Depends on: T17."); `:116` repeats the review note.
- `tasks.json:4` note: "A proposed erratum awaiting the owner's decision does not change a task's status; a task met
  'subject to' an erratum stays DONE."
- `SESSION_STATE.md:4`: "**Current milestone:** M06 (vector retrieval; T18 is its open task. …)". `:14-16`: "Next
  is T18 (vector retrieval; it now also owns mcp-read's vector mode) or T23, both unblocked; T19 and T41 wait on
  owner steps, and T20 waits on T19." `STATUS.md:345`: "Next: T18 (vector retrieval, now with mcp-read's vector mode)
  or T23."

### 1.2 Acceptance rows (`handoff/acceptance-matrix.json`)

- **R034 (:648-661)** — M06 / retrieval; "Exact vector retrieval is measured against the baseline";
  `blocking_for_v1: true`; `implementation_status: NOT_IMPLEMENTED_OR_NOT_TARGET_VERIFIED`; `evidence_status:
  NOT_RUN`; `evidence_paths: []`; expected_evidence (verbatim): "Record model/dimension/corpus and matched question
  retrieval results, including regressions."; owners `T18` only; suggested_test
  `tests/acceptance/test_r034_exact_vector_retrieval_is_measured_against_the_b.py`; no note.
- `handoff/ACCEPTANCE.md:40` (the superseded 1.0 snapshot, `:3`): "- [ ] **R034 / M06** — Exact vector retrieval is
  measured against the baseline. Evidence: Record model/dimension/corpus and matched question retrieval results,
  including regressions."
- Matrix note (`acceptance-matrix.json:3`): suggested_test paths are targets; `RECORDED_LOCALLY` = passes in
  `scripts/check.py` and CI; `RECORDED_LOCALLY_LIVE` = passes against the running dev profile with `OPS_LIVE=1`,
  collected but skipped by `check.py` and CI. `tests/acceptance/` does not exist.
- Neighbouring rows that name retrieval, pgvector, models or digests:
  - **R032 (:605-625)** T17, "Source ingestion is versioned effective and idempotent"; `IMPLEMENTED_LOCALLY_VERIFIED`
    / `RECORDED_LOCALLY_LIVE`; evidence `tests/e2e/test_ingest_live.py`, `test_migration_0011_live.py`,
    `tests/plan_l/test_ingest_plan.py`, `test_corpus_files.py`.
  - **R033 (:626-646)** T17, "Lexical baseline has labeled evidence measurements"; `IMPLEMENTED_LOCALLY_VERIFIED` /
    `RECORDED_LOCALLY_LIVE`; evidence `tests/e2e/test_retrieval_baseline_live.py`,
    `reports/retrieval/t17-lexical-baseline.md`, `.json`, `tests/plan_l/test_retrieval_baseline.py`,
    `evals/retrieval/dev-queries.jsonl`. Note (end): "Missing sources are measured, not guaranteed: at the 0.25
    minimum rank 15/20 no-source questions were answered with nothing; R033 is met subject to the owner's decision on
    erratum 102 … The minimum rank was chosen on these same queries, so the figures are development figures, not
    held-out ones."
  - **R037 (:693-705)** T19, "Actual LangChain and Ollama inference occurs"; expected "Trace ChatOllama request using
    named installed model; record real output, versions and hardware."; `NOT_RUN`.
  - **R099 (:1702-1722)** T17, "Evidence corpus is large enough to measure retrieval"; `IMPLEMENTED_LOCALLY_VERIFIED`,
    `RECORDED_LOCALLY`.
  - **R101 (:1739-1756)** T05/T43/T44, "Development environment starts from a clean clone with one command";
    expected "Dev profile (PostgreSQL+pgvector, Keycloak, Ollama bridge) healthy on Windows; secrets generated outside
    git."; `NOT_IMPLEMENTED_OR_NOT_TARGET_VERIFIED` / `NOT_RUN`.
  - **R127 (:2203-2218)** T19, "The pinned model digest is verified at worker warm-up"; expected "Worker start with a
    mismatching digest in data/model-pins.json fails closed; matching digest proceeds; probe date recorded."; `NOT_RUN`.
  - **R130 (:2262-2278)** T19/T25, "The model route is explicit, recorded and never silently substituted"; expected
    "Run manifest records model_route, digest, prompt_version, corpus_version; a missing or mismatched model fails
    closed; B and C evaluation conditions show identical routes."; `NOT_RUN`.
  - No row names `nomic`, `embedding`, `search_query:`/`search_document:` or a "retrieval comparison" other than R034.

### 1.3 Debts other tasks pushed to T18

- **From T17 (Plan L)** — `tasks.json:746` (T17's close-out note, end): "Deferred: embeddings, vector mode and another
  chunk window -> T18; … tuning the minimum rank -> T18." The Plan L debt list (`SESSION_STATE.md:1138-1163`), items
  `:1141-1148` verbatim:
  - "vector retrieval: the `embeddings` table, the nomic-embed-text `search_document:`/`search_query:` embeddings, the
    `mode = 'vector'` branch of `search_procedures_scoped` (refused `VECTOR_MODE_UNAVAILABLE` until then), tuning the
    minimum rank (0.25, chosen on the development queries; `ts_rank_cd` is unnormalised, so it depends on query
    length), and the evaluation of another chunk window than one per section → T18 (Plan L rulings 2, 4 and 18);
    mcp-read's `vector_exact` → `mode=vector` translation (until then `UNSUPPORTED_MODE` before the database) → T16;"
    (the last clause was then moved to T18 by erratum 103, below).
  - "the query is normalised by `regexp_replace('[^a-z0-9]+', ' ')` while chunk text is parsed raw, so a token such as
    `4.5` or `M8x1.25` cannot match as one lexeme (recall loss on numeric values) → T18;"
- **From T16 (Plan M)** — erratum 103 and T16's notes: `tasks.json:774` (debt b): "vector mode: mcp-read's
  vector_exact -> mode=vector translation and the nomic search_query embedding need T18's stored embeddings; until T18
  the definer refuses mode=vector with OC005/VECTOR_MODE_UNAVAILABLE (0011, TODO(T18)) and mcp-read answers
  UNSUPPORTED_MODE before the database. Plan M will rule on deferring it." `:781`: "Plan M ruled on debts b and c:
  vector mode (b) moved to T18 with its embeddings (erratum 103; T18's review note); the UNSUPPORTED_MODE order stays,
  the handle first (an invalid handle never learns what the server supports) …". `:782` (T16 close-out, "Deferred:"):
  "vector mode and the search_query embedding -> T18 (erratum 103)". Plan M debt list (`SESSION_STATE.md:1165-1204`),
  `:1168-1170`: "vector mode: mcp-read's `vector_exact` → `mode=vector` translation and the nomic `search_query:`
  embedding it computes, with the embeddings themselves → T18 (Plan M ruling 1, erratum 103); until then mcp-read
  answers `vector_exact` with `UNSUPPORTED_MODE` after the handle resolution and the definer refuses `mode=vector`;".
  T16's original wording still stands in its instructions (`tasks.json:753`: "… search_procedures over the governed
  store (vector mode: mcp-read computes the nomic search_query embedding) …") and review note (`:771`:
  "search_procedures vector mode: mcp-read computes the nomic search_query embedding and passes it to
  search_procedures_scoped."); erratum 103 moves them.
- **Open item (Plan L, `SESSION_STATE.md:846-849`)**: "the query is normalised by `regexp_replace('[^a-z0-9]+', ' ')`
  while chunk text is parsed raw, so `4.5` or `M8x1.25` cannot match as one lexeme (T18); the no-source questions that
  still return a section (A15, B10, B13, B17, B18) come from generic words such as `records` and are T18's tuning and
  T20's relevance criterion (SA:377 alone would not abstain on them), not a defect of `corpus-1`".
- **Code and docs sites naming T18:**
  - `migrations/app/versions/0011_governed_corpus.py:178`: `-- TODO(T18): exact pgvector search over app.embeddings
    under the same filters (R034).`; `:24-27` docstring ("`mode = 'vector'` is refused (`VECTOR_MODE_UNAVAILABLE`)
    until T18 creates the embeddings"); `:146-149` comment on `MIN_RANK`: "`ts_rank_cd` is not normalised, so a longer
    query reaches the threshold more easily; tuning it is T18's, with the comparison. One helper, as
    `_dispatch_seconds()`, so a later revision changes it in one place."
  - `mcp-read/src/ops_mcp_read/server.py:363-365`: "TODO(T18): translate vector_exact to mode=vector and compute the
    nomic `search_query:` embedding once T18 stores embeddings (erratum 3; Plan M ruling 1, erratum 103)." then
    `return envelope(name.value, error=tool_error("UNSUPPORTED_MODE", "vector_exact arrives with T18"))`.
  - `core/src/ops_core/routing.py:362-363`: "TODO(T18): mcp-read, the caller of `search_procedures_scoped`, translates
    `vector_exact` to `mode=vector` (Plan M ruling 1: the translation arrives with T18's embeddings, erratum 103)."
  - `scripts/build_schemas.py:861`: `"mode": {"enum": ["lexical", "vector_exact"]},  # ruling 3; mcp-read maps
    vector_exact (TODO(T18))`.
  - `core/src/ops_core/persistence.py:490-491`: "the embedding stays NULL and the mode `lexical` until T18."
  - `core/src/ops_core/privileges.py:7-8`: "the owners of later tables (feedback → T21, operator_resolutions → T22,
    embeddings → T18) add their rows."
  - `scripts/retrieval_baseline.py:9-10`: "T18 measures exact vector search on the same queries against the same
    JSON."; `:47-48` (`SETTINGS["minimum_rank"]`): "… tuning it is T18's"; `:267`: "Evaluating another chunk window is
    T18's comparison."
  - `docs/retrieval.md:45` ("evaluating another window is part of T18's comparison"), `:85` (threshold: "tuning it is
    T18's, with the comparison"), `:89` (vector mode refused until T18), `:94` ("not comparable with T18's vector
    distances (BS:417)"), `:122` ("T18 compares exact vector search against the same JSON").
  - `docs/runbooks/mcp-read.md:74-75` (`vector_exact` refused `UNSUPPORTED_MODE` "after the handle resolution and
    before anything else (T18)"), `:127` ("Vector search and the `search_query:` embedding (T18)").
  - `STATUS.md:319-322` (Plan L: "vector search, embeddings and another chunk window -> T18; … tuning the minimum rank
    -> T18"), `:342` (Plan M: "vector mode -> T18").

### 1.4 Tasks that consume T18 or name embeddings/retrieval mode, and what they expect

- **T25** (`tasks.json:1012-1041`, M09, PLANNED) "Model-quality evaluation A/B/C": `depends_on`
  `["T22", "T18", "T23", "T41"]` (T18 is a hard dependency). Instructions: "Conditions per AM-50; 3 isolated trials;
  case-level Wilson CIs, cluster bootstrap, paired McNemar; quality-gates.json committed before the holdout run;
  holdout run once per release candidate." Review note (`:1038`): "Reads each run's manifest (model route, digest,
  prompt and corpus versions) into the eval report; conditions B and C must show identical model_route." SA:660: "B
  and C use identical model, prompt-version family, retrieval settings and `num_ctx`."
- **T19** (`:826-856`, M07, PLANNED) "Async LangChain ChatOllama DraftGenerator": does **not** depend on T18
  (`depends_on` `T07, T17, T02, T03, T44`). Instructions (`:829`): "… writes the run manifest {run_id, model_route,
  model_digest, prompt_version, corpus_version, retrieval_mode} and records the route in explanation.ready. Warm-up
  call at startup compares /api/show digest with data/model-pins.json and fails closed on mismatch (R127)." Review note
  (`:853`): "`probe.py` pins the digest from `/api/tags` (`/api/show` carried no digest for qwen3:8b on Ollama
  0.33.3); reconcile with AM-31's `/api/show` wording before designing the fail-closed check."
- **T20** (`:857-888`, M07) "LangGraph workflow …": depends on T19, T14, T16 (not T18); "retrieval before drafting"; DoD
  "Trace shows MCP reads complete before drafting." Erratum 102 (below) assigns T20 "a relevance criterion beyond
  [SA:377] (for example a score or label-based sufficiency rule)".
- **T23** (`:969-986`, M09) "Development eval set, gold labels and rubric": depends on T17 only; "~60 dev cases over
  the expanded corpus with gold labels; deterministic graders for schema, citations and abstention". Names no
  embedding.
- **T41** (`:807-825`, M06, PLANNED, `external_approval_required: true`): "Owner, without AI assistance, adds evidence
  IDs and expected outcomes to the sealed holdout cases against the frozen T17 corpus version; re-seals … Corpus
  changes after this require re-labelling." depends on T03, T17. T41 shares M06 with T18.
- **T02** (`:225-247`, M00, `DONE_PENDING_OWNER`): "… Writes data/model-pins.json {model, digest, ollama_version,
  probed_at}." Its probe is of `qwen3:8b` only; review note (`:244`): "Pending owner step: the live probe run after the
  T03 seal; the probe refuses to run without a well-formed seal." `data/model-pins.json` does not exist in the tree.
- **T44** (`:342-362`, M01, `DONE_PENDING_OWNER`) "Ollama bridge, network runbook and model pins consumption":
  "Container route to host Ollama (not host.docker.internal for host callers); write docs/runbooks/ollama-network.md
  …; worker reads data/model-pins.json for the digest check (implemented in T19)." Note (`:359`): "host and container
  routes to Ollama proven, ops_core.model_pins loader with 13 tests, docs/runbooks/ollama-network.md … Pending owner
  step 10".
- **T29** (`:1111-1130`, M11): DoD "Outage tests for Ollama, MCP and destination."
- **T30** (`:1131-1157`, M12): review note "Docker network tests include: mcp-read cannot reach incident-sim;
  mcp-write cannot reach asset-sim; worker cannot reach either sim." (no line on mcp-read and Ollama).
- **T31** (`:1158-1176`, M12): "Extend T06: PostgreSQL integration, scenario suite, image build and scan; separate
  trusted workflow for real-model checks run manually; pinned SHAs; least privilege."
- No task instruction names BS:280's `POST /api/v1/search` ("Authorized lexical/vector search for the manual
  baseline"); T26's instructions (`:1045`) name "authorized evidence viewer" and "manual proposal UI".

---

## 2. Spec passages that bind T18

### 2.1 Embeddings, the model, the dimension and the prefixes

- SA:645 (AM-50, corpus): "embeddings use `nomic-embed-text` with the `search_document:` and `search_query:` prefixes,
  with a test that they are applied."
- SA:348 (AM-15): "For `search_procedures` in vector mode, mcp-read computes the query embedding with
  `nomic-embed-text` (`search_query:` prefix) and passes it to `search_procedures_scoped` [R6]."
- SA:461 (AM-20.3 row): "`search_procedures_scoped(raw_handle, query, query_embedding vector(768) NULL, asset_type,
  limit, mode)` | `mcp_read` | handle, text query, optional embedding computed by mcp-read with the `search_query:`
  prefix | as above | Lexical (`mode=lexical`) or exact vector (`mode=vector`, requires the embedding) search over
  approved, effective, tenant-permitted chunks; returns IDs, versions, section, hash, excerpt | none". The dimension
  768 appears here and nowhere else in the spec.
- BS:242 (data model): "| chunk / embedding | document-version ID, stable section/offset/hash, text, embedding
  model/dimension/index version |".
- BS:415: "… Use PostgreSQL full-text retrieval as baseline; then select and record an embedding model and dimension
  and implement exact pgvector search. pgvector provides vector storage/search inside PostgreSQL; it does not
  implement the application's authorization policy. [S07]" (S07 = https://github.com/pgvector/pgvector, BS:781.)
- BS:69: "PostgreSQL for app data, jobs, checkpoints, governed text, embeddings and outbox". BS:71: "| Retrieval |
  PostgreSQL full-text search baseline, then exact pgvector similarity. [S07] | Measure retrieval quality; add hybrid
  search/reranking/index approximation only with evidence. |"
- Planning review (`docs/reviews/plan-review-2026-10-06.md:140`, version corrections table): "| nomic-embed-text |
  requires the `search_document:` / `search_query:` prefixes |".

### 2.2 Exact vs approximate, and "the same filters"

- BS:50 (v1 scope): "governed lexical retrieval plus a measured pgvector comparison". BS:54 (deferred): "… vector
  rerankers, approximate search, … are deferred until a measured need justifies them."
- `docs/reviews/plan-review-2026-10-06.md:129`: "pgvector does exact search by default." (the planning review's
  statement; no ruling cites it).
- BS:417: "Filter before results enter the model. Apply approved/effective/tenant/resource-access constraints to
  lexical and vector retrieval. Store retrieval settings and score interpretation; scores from different methods are
  not interchangeable probabilities. Start `top_k=5`, allow up to 8 source references under the context budget, and
  tune on development evidence only. If no appropriate source exists or procedures conflict materially, ask/abstain
  instead of inventing a merged policy."
- BS:386 (`search_procedures`): "bounded `query`, optional `asset_type`, `limit` | Only approved, effective, currently
  permitted chunks; IDs, versions, section, source hash, excerpt, retrieval mode".
- SA:350: "Every tool has an input JSON Schema in `schemas/tools/`. Arguments that supply a role, tenant, actor,
  approval or destination are rejected."
- BS:147: `MCP --> Evidence[(Governed evidence / pgvector)]` (deployment diagram).

### 2.3 Chunking and the window

- BS:415: "Chunk on headings/sections. Initial proposal: 300–600 tokens per chunk, minimal overlap only where context
  requires it, stable source offsets and evidence IDs. The exact tokenizer/window choice must be recorded and
  evaluated. Do not make a generated summary the authoritative source."
- SA:643: "evidence IDs are per section, with per-section `sha256`;".
- Erratum 100 (proposed, `SESSION_STATE.md:808-810`): "BS:415 (chunking): one chunk per `## ` section (45-119 words
  in corpus-1, below the initial 300-600-token proposal), measured in `[a-z0-9]+` words because no tokenizer is locked;
  another window is evaluated in T18's comparison."
- T41 (`tasks.json:810`): "Corpus changes after this require re-labelling."

### 2.4 The comparison report and the statistics

- T18 DoD 1: "reports/retrieval-comparison.md with recall@k for both methods, denominators and CIs."
- R034 expected: "Record model/dimension/corpus and matched question retrieval results, including regressions."
- BS:707 (§25, superseded as a table by SA:42 but the only spec row for M06's content): "| M06 — Evidence pipeline |
  Governed ingestion, lexical baseline, exact pgvector comparison, revocation | Source/version/access tests; named
  retrieval experiment |". In `tasks.json` M06 is "Vector retrieval" = T18 + T41 (`:78-86`).
- BS:609: "Metrics: … retrieval precision/recall over labeled permitted evidence; correct abstention; …". BS:611:
  "Report denominators and "zero observed," not impossibility claims."
- SA:665 (AM-50, model-quality statistics): "report at **case level** … with Wilson 95% CIs and denominators. Also
  report trial-level rates with a case-cluster bootstrap CI …". SA:667: "**Comparisons:** paired exact McNemar tests on
  case-level outcomes. No ranking claim without p < 0.05." (AM-50's statistics are written for the model-quality
  evaluation; no line says whether they bind a retrieval comparison.)
- T17's measurement as the template (Plan L ruling 19, `docs/reviews/plan-review-l-2026-10-17.md:126-133`): "Metrics at
  k=5: recall@5, precision@5, MRR, hit@5, the forbidden-section rate (must be zero, with its denominator), and for
  `expect_none` the share answered with no result. Case-level Wilson 95% CIs and denominators (SA:665). Report
  `reports/retrieval/t17-lexical-baseline.md` plus a machine-readable `.json` next to it; T18 compares against the
  same file."

### 2.5 Model pins, the digest and where pins live

- SA:595: "**Model:** `qwen3:8b`, selected by the model router (AM-16); the route, digest and prompt version are
  recorded per run. Record its digest."
- SA:598: "**Digest check:** at warm-up the worker compares the model digest (`/api/show`) with the pin in
  **`data/model-pins.json`** (`{model, digest, ollama_version, probed_at}`, written by T02) and **fails closed** on
  mismatch. Owned by T19 and tested by R127 [R5-S9, R6-B4]."
- SA:768 (AM-80): "| New: `schemas/model-pins.schema.json` | `{model, digest, ollama_version, probed_at}` (AM-31) |".
  The committed schema (`schemas/model-pins.schema.json`) is one object with exactly those four required keys,
  `additionalProperties: false`, `digest` pattern `^[0-9a-f]{64}(?![\s\S])`: one model per file. No spec line names a
  pin for the embedding model.
- SA:770: "the per-run manifest `{run_id, model_route, model_digest, prompt_version, corpus_version,
  retrieval_mode}`". BS:572: "Record commit, workflow version, prompt hash, model identifier/digest, corpus/index
  version and tool schema version per run." BS:670 (release manifest): "… model/runtime digest/configuration,
  prompt/workflow/tool schema/corpus/index/evaluation versions … Never fill unknown digests with realistic-looking dummy
  values." BS:427: "A later [cache] key includes tenant, permission version, corpus version, model/prompt version and
  query parameters."
- SA:584 (AM-30 versions table): "| pgvector-python | 0.5.0 |"; SA:587: "| Ollama | installed 0.33.3; latest 0.35.1.
  Record the version actually used, and upgrade only with owner approval. |". SA:575: "exact pins live in `uv.lock`".
- SA:697 (AM-60 1.3.3): "R127 (model digest pin) owned by T19; `data/model-pins.json` written by T02."

### 2.6 The Ollama bridge, network rules and who may call the model

- SA:599-601: "**Network exposure (owner decision):** Ollama is reachable only from loopback and the Docker/WSL
  subnet. — The owner applies the firewall restriction, using commands documented in `docs/runbooks/ollama-network.md`
  (T05). The agent does not change system settings. — Every other published port (Postgres, Keycloak, services) binds
  to `127.0.0.1`."
- BS:641-650 (minimum connection matrix): "| Worker | app/checkpoint DB, MCP, Ollama, Keycloak workload tokens,
  telemetry |"; "| MCP | app/evidence DB for authorized resolution, synthetic services, Keycloak metadata, telemetry |";
  "| Model | no incident/database route; no external cloud egress in offline profile |". The MCP row names no Ollama.
- BS:144: `Worker --> Model[Local Ollama endpoint]` (no MCP → Model edge in BS:136-151).
- `docs/adr/ADR-0001-deployable-units-as-top-level-directories.md:31`: "**Network boundaries stay where §3 puts them:**
  browser → api, worker → mcp-read / mcp-write, mcp-read → asset-sim, mcp-write → incident-sim, worker → Ollama
  (ADR-0003)." `docs/ARCHITECTURE.md:40`: `W -->|prompts only| OL`; `:63` mcp-read reaches "PostgreSQL (functions),
  asset-sim".
- BS:629: "Ollama may run on the host or a container according to verified hardware support. Document host/container
  addresses per platform and test egress; …"
- SA:201: "**Async only:** use `AsyncPostgresSaver`, `ChatOllama.ainvoke` and async MCP/HTTP clients. No synchronous
  I/O on the event loop." SA:203-205: "A `model_permit` row, leased and polled with `SKIP LOCKED` plus backoff,
  enforces global model concurrency (1). …" (AM-20.2: `model_permit` cells are `worker` sel/upd(all) and `sweeper`
  upd(`leased_until`); `mcp_read` has no table grants, SA:437.) BS:549: "| Global model concurrency | 1 initially;
  increase only after measured capacity |".
- Timeouts in the spec are for generation: BS:443 / SA:596 (60 s per attempt). BS:552: "| Read-tool work | At most 6
  calls including retries; max 2 retries per transient read within total cap |"; BS:558: "| Invocation handle | At
  most 60 seconds, additionally bounded by current lease and policy |". No spec line gives an embedding-call timeout.

### 2.7 Determinism and reproducibility

- BS:443: "Temperature 0 does not guarantee identical outputs. Record the actual supported parameters and model
  digest." SA:591: "temperature 0 does not guarantee identical outputs" is project reasoning (citation fix).
- No spec line addresses embedding determinism (float equality, tolerance, re-embedding).
- BS:417 "tune on development evidence only"; SA:657-659 holdout custody (the holdout is never in the tuning context).

### 2.8 Evidence sufficiency and the graph

- SA:377: "… "Evidence sufficient?" is a code rule (at least one permitted status observation and at least one
  effective procedure chunk, all within freshness), never a model judgement; …"
- Erratum 102 (proposed, `SESSION_STATE.md:814-819`): "R033 ("missing source remains missing, not guessed"): even above
  the 0.25 minimum rank, lexical OR-matching can return a permitted section for a no-source question (15/20 of the
  development set's no-source questions were answered with nothing); the share is measured and reported. The residue
  (5/20) is open: SA:377 as written counts any returned effective chunk as sufficient, so it would not abstain on those
  cases; T20 must add a relevance criterion beyond it (for example a score or label-based sufficiency rule). R033 is
  recorded as met subject to this erratum."

### 2.9 Mode names, the tables and their grants

- Erratum 3 (proposed, `SESSION_STATE.md:147`): "AM-20.3 `search_procedures_scoped`: `mode=vector` is the SQL argument
  value; the externally visible `retrieval_mode` is `vector_exact`, and mcp-read translates between them."
- SA:431 (AM-20.2): "| `documents`, `chunks`, `embeddings` | — | ins, sel (ingestion) | — | sel | — |" (columns:
  `api`, `worker`, `sweeper`, `app_definer`, `mcp_read`/`mcp_exec`/`operator`). SA:437: "`mcp_read`, `mcp_exec` and
  `operator` have **no table grants**".
- SA:510 (AM-20.5): `documents`, `chunks`, `embeddings` are among the tenant tables with ENABLE + FORCE RLS and the
  `tenant_isolation` policy (`FOR ALL TO api, worker, sweeper, app_definer USING (tenant_id =
  current_setting('app.tenant_id', true)::uuid)`, SA:512-516).
- SA:395: `migrator` "holds `BYPASSRLS` so seed and backfill data migrations can write RLS tables; never used at
  runtime".
- SA:446: "All functions: `SECURITY DEFINER`, owner `app_definer`, `SET search_path = app, pg_temp`, `SET
  app.tenant_id = ''` as a function attribute. …"
- Erratum 95 (proposed, `SESSION_STATE.md:794-796`): "`document_states` and `corpus_ingestions` join `documents` and
  `chunks` with the same cells … and the `tenant_isolation` policy; `embeddings` is created by T18, its first writer."
- Erratum 98 (proposed, `:802-804`): "ingestion is an operator command, `scripts/skeleton.py ingest`, connecting as
  `worker` (AM-20.2's ingestion cells), not a job type and not a `migrator` data migration; the services start on an
  empty corpus and the worker then answers INSUFFICIENT_EVIDENCE."
- Erratum 99 (proposed, `:805-807`): "SA:461 and SA:348 (vector mode): `mode = 'vector'` is refused inside the function
  (`OC005` `VECTOR_MODE_UNAVAILABLE`) until T18 stores embeddings; the `vector` extension is bootstrap infrastructure
  (`skeleton.py ensure_extensions`) that revision 0011 requires and never creates or drops."
- Erratum 93 (proposed, `:782-786`) gives the signature with `client_azp` second; erratum 106 (`:885-889`) the 0012
  answer `(corpus_version, retrieved_at, results)` with `excerpt_cut`.

---

## 3. The tree as it is (branch `plan-n`, `e0d0d53`)

### 3.1 `search_procedures_scoped` (revision 0011's body, re-created by 0012)

- **Signature** (`0011_governed_corpus.py:160-164`): `app.search_procedures_scoped(p_raw_handle text, p_client_azp
  text, p_query text, p_query_embedding public.vector(768), p_asset_type text, p_limit integer, p_mode text)`. The
  regprocedure argument list everywhere else is `text, text, text, public.vector, text, integer, text` (no dimension):
  `0011:237`, `:245`, `:251`; `0012_asset_scope.py:51` (`SEARCH_ARGS`); `privileges.DEFINER_FUNCTIONS`
  (`core/src/ops_core/privileges.py:209`): `"search_procedures_scoped": ("text, text, text, public.vector, text,
  integer, text", ("mcp_read",))`; `persistence.GOVERNED_CORPUS` / `SEARCH_INSTANT` (`persistence.py:191-202`).
- **Returns** since 0012: `RETURNS TABLE (corpus_version text, retrieved_at timestamptz, results jsonb)`
  (`0012:101-105`); 0011's was `(corpus_version text, results jsonb)` (`0011:164`).
- **Body order** (0011:165-236 as changed by 0012's `CHANGES_0012`, `0012:101-122`):
  1. `PERFORM app._authority('search_procedures_scoped', ARRAY['mcp_read'])` (`0011:172`);
  2. `SELECT * INTO v_handle FROM app._resolve_handle(p_raw_handle, p_client_azp, 'read')` (`:175`) — "the lease FOR
     SHARE first, then the fence, expiry, revocation, azp and the read server";
  3. `PERFORM set_config('app.tenant_id', v_handle.tenant_id::text, true)` (`:176`);
  4. (0012) the R028 membership check (`0012:56-64`): an active `requester` membership for the run's requester in the
     run's tenant, else `RAISE EXCEPTION 'handle_rejected' USING ERRCODE = 'OC008'`;
  5. **the vector refusal** (`0011:177-180`): `IF p_mode = 'vector' THEN -- TODO(T18): … RAISE EXCEPTION 'refused'
     USING ERRCODE = 'OC005', DETAIL = 'VECTOR_MODE_UNAVAILABLE'; END IF;` — before any argument check and before any
     corpus read;
  6. the argument check (`:181-185`): `p_mode IS DISTINCT FROM 'lexical' OR p_query IS NULL OR char_length(p_query)
     NOT BETWEEN 1 AND 500 OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 8 OR (p_asset_type IS NOT NULL AND
     char_length(p_asset_type) NOT BETWEEN 1 AND 40)` → `OC005` `BAD_ARGUMENT` (so `p_query_embedding` is never
     checked today);
  7. `corpus_version` = the tenant's latest `corpus_ingestions.corpus_version` by `seq`, else `'none'` (`:187-188`);
  8. `v_now := app.current_time()` after the lease lock (`:189`); (0012) `retrieved_at := v_now` (`0012:98-100`);
  9. lexemes: `tsvector_to_array(to_tsvector('english', regexp_replace(lower(p_query), '[^a-z0-9]+', ' ', 'g')))`
     (`:192`); none → `results := '[]'`, return (`:193-197`); `v_query := to_tsquery('simple', array_to_string(v_lexemes,
     ' | '))` (`:198`);
  10. CTEs (`:199-227`): `latest` (`DISTINCT ON (tenant_id, document_id, version) … ORDER BY … s.seq DESC`),
      `effective` (`l.status = 'approved' AND l.effective_from <= v_now AND (l.effective_to IS NULL OR v_now <
      l.effective_to)`), `permitted` (not retired: no later version `n.version::integer > e.version::integer AND
      n.status <> 'draft' AND n.effective_from <= v_now`; and `(p_asset_type IS NULL OR e.asset_family IS NULL OR
      e.asset_family = p_asset_type)`), `ranked` (`chunks c JOIN permitted p USING (tenant_id, document_id,
      version) WHERE c.search @@ v_query`, `ts_rank_cd(c.search, v_query) AS rank`, excerpt `left(c.body, 8000)` and
      (0012) `char_length(c.body) > 8000 AS excerpt_cut`), `kept` (`WHERE r.rank > app._min_rank() ORDER BY r.rank
      DESC, r.evidence_id COLLATE "C" LIMIT p_limit`);
  11. `results` = `jsonb_agg(jsonb_build_object('evidence_id', 'document_id', 'version', 'section', 'content_sha256',
      'excerpt', 'effective_from', 'rank', (0012) 'excerpt_cut') ORDER BY k.rank DESC, k.evidence_id COLLATE "C")`
      (`:228-233`; `0012:115-121`).
- The tenant filter is the handle's tenant via `set_config` + RLS (`tenant_isolation`); the SQL itself has no
  `tenant_id = …` predicate besides the `USING (tenant_id, …)` joins.
- **`app._min_rank()`** (`0011:150-158`): `RETURNS real … IMMUTABLE … RETURN 0.25;`, owner `app_definer`; in
  `privileges.HELPER_FUNCTIONS` (`privileges.py:232`, `"_min_rank": ""`), granted to nobody. 0012 does not touch it.
- `0012:12-13`: "re-created from revision 0011's own body with five textual changes and nothing else (ranking, filters
  and `_min_rank` stay byte for byte; a unit test reverses the changes and compares)". The changes are applied by
  `changed(body)` (`0012:125-136`), which raises if any `old` text is not present exactly once.
- **Unit tests pinning the refusal's place:** `tests/plan_l/test_migration_0011.py:88-96` (`authority < handle < tenant
  < vector < first_read < clock`), `tests/plan_m/test_migration_0012.py:95-104` (`tenant < member < vector < first_read
  < clock < instant < stop_words`); live `tests/e2e/test_migration_0011_live.py:269-270` (`persistence.Refused,
  match="VECTOR_MODE_UNAVAILABLE"` via a direct `_call` with mode `'vector'`).

### 3.2 The corpus tables (revision 0011)

- `app.corpus_ingestions` (`0011:69-79`): `tenant_id` (FK tenants), `seq`, `corpus_version` (regex
  `^[a-z0-9][a-z0-9.-]{0,99}$`), `lock_sha256`, `documents_added`, `states_added`, `ingested_at DEFAULT now()`; PK
  `(tenant_id, seq)`.
- `app.documents` (`:80-97`): `tenant_id, document_id, version, path, content_sha256, asset_family, label ∈ {normal,
  injected, conflicting}, supersedes, conflicts_with, ingestion_seq`; PK `(tenant_id, document_id, version)`; FKs to
  `corpus_ingestions` and self (`supersedes`).
- `app.document_states` (`:98-114`): `tenant_id, document_id, version, seq, status ∈ {draft, approved, superseded,
  revoked}, effective_from, effective_to, ingestion_seq`; PK `(tenant_id, document_id, version, seq)`.
- `app.chunks` (`:115-138`): `tenant_id, document_id, version, ordinal, section (1-120 chars), evidence_id (<=160),
  body, content_sha256, start_offset, end_offset, word_count, search tsvector GENERATED ALWAYS AS
  (setweight(to_tsvector('english', section), 'A') || setweight(to_tsvector('english', body), 'D')) STORED`; PK
  `(tenant_id, evidence_id)`; `UNIQUE (tenant_id, document_id, version, ordinal)`; `CHECK (end_offset - start_offset =
  char_length(body))`; `CHECK (evidence_id = document_id || ':' || 'v' || version || ':' || section)`; FK to
  `documents`. No embedding column.
- Indexes: the PKs/uniques and `CREATE INDEX chunks_search ON app.chunks USING gin (search)` (`:139`). No vector index.
- Owner `migrator` (`:140-143`). Grants (`GRANTS_0011`, `:60-65`; `privileges.GRANTS`, `privileges.py:143-149`):
  `worker` SELECT+INSERT, `app_definer` SELECT, nothing else (revoked from `MAIN_GRANTEES_0011`, `:58`). RLS:
  `privileges.rls_statements(TABLES_0011, POLICY_ROLES_0011)` (`:267`) — ENABLE + FORCE and `tenant_isolation` for
  `api, worker, sweeper, app_definer`; the four tables are in `privileges.RLS_TABLES` (`privileges.py:152-171`). No
  role holds UPDATE or DELETE on any corpus table.
- Downgrade (`0011:250-257`): drops the function, `_min_rank`, then `chunks`, `document_states`, `documents`,
  `corpus_ingestions`; the `vector` extension stays.

### 3.3 The `vector` extension bootstrap

- `deploy/dev/postgres/init/01-init.sql:2`: `CREATE EXTENSION IF NOT EXISTS vector;` (the Compose volume's first
  start). Image `pgvector/pgvector:pg17@sha256:ac08538c…a75d` (`compose.yaml:9`); the Plan L review measured
  "PostgreSQL 17.11, image `pgvector/pgvector:pg17`" (`docs/reviews/plan-review-l-2026-10-17.md:268`).
- `scripts/skeleton.py:173-186`: `EXTENSIONS: tuple[str, ...] = ("vector",)`; `ensure_extensions(pg)` runs `CREATE
  EXTENSION IF NOT EXISTS {name} SCHEMA public` as the superuser; comment: "Extensions are bootstrap infrastructure,
  like the roles (Plan L ruling 2): pgvector's type appears in `search_procedures_scoped`'s signature (SA:461), and a
  revision that created the extension could not drop it again exactly." `migrate()` (`:224-238`) runs `ensure_roles`,
  `ensure_extensions(superuser)`, then `upgrade("app", …, target)` and the incident tree.
- `0011:45-55` `REQUIRE_VECTOR`: a `DO` block that raises "the vector type is missing: scripts/skeleton.py migrate
  creates the extension first" when `to_regtype('public.vector') IS NULL`.
- pgvector's version inside the image is not recorded anywhere in the tree.

### 3.4 The revision chain and how revisions, definers and startup markers are written

- `migrations/app/versions/`: `0001_walking_skeleton` … `0011_governed_corpus`, `0012_asset_scope` (head of `app`),
  `tc_0001_test_clock` (the `testclock` branch, applied only by `--profile test`, SA:529). Next number: `0013`.
- Pattern: each revision freezes its statements as module constants — `SCHEMA_CHANGES`, `GRANTS_<rev>`,
  `FUNCTIONS: tuple[(name, argument types, callers, body), …]` ("frozen here (N1); the newest-revision test reads this
  tuple", `0011:240`, `0012:140`), `DOWNGRADE`; `upgrade()` executes each body and then
  `privileges.function_grant_statements(name, args=…, callers=…)` (REVOKE from PUBLIC, GRANT EXECUTE to the callers).
  A revision that changes a function's return type drops and re-creates it (`0012:154-160`); 0012's downgrade
  restores 0011's body from 0011's own module (`0012:39-49`, `:146-148`, `:163-171`, "0009's pattern").
- `tests/plan_e/test_transitions_table.py:86-99` `REVISIONS` (named, `0002` … `0012_asset_scope`,
  `tc_0001_test_clock`); `:61-80` "the newest revision of every cell equals the live matrix": every `GRANTS_*`
  literal must equal `privileges.GRANTS[table]` and every `FUNCTIONS` caller set must equal
  `privileges.DEFINER_FUNCTIONS` (or be a helper). A new table or function needs a new revision **and** a
  `privileges` edit in the same change.
- **Startup markers** (`core/src/ops_core/persistence.py:183-215`): `assert_relation(conn, name)` (`:170-176`) and
  `assert_function_text(conn, signature, marker)` (`:205-215`, `strpos(p.prosrc, marker)`). mcp-read's lifespan
  (`mcp-read/src/ops_mcp_read/server.py:420-428`) asserts the clock profile, `HANDLE_BINDING`, `GOVERNED_CORPUS`
  (`("app.search_procedures_scoped(text, text, text, public.vector, text, integer, text)", "ts_rank_cd(c.search,
  v_query)")`, `persistence.py:191-194`), `ASSET_SCOPE` (`("app.asset_scope(text, text)", "as_of :=
  app.current_time()")`, `:198`) and `SEARCH_INSTANT` (`(…search_procedures_scoped…, "retrieved_at := v_now")`,
  `:199-202`). The rule (`:188-190`, `:195-197`): "a later revision that re-creates the function keeps this text or
  changes it here in the same commit". Ingestion asserts the four corpus relations (`ops_core/ingest.py:41`,
  `:291-292`).
- The dev `ops` database is at `0011_governed_corpus` with corpus-1 ingested (`SESSION_STATE.md:1278-1284`) and waits
  for the owner's migrate to 0012 (`:1286-1289`, owner input 4 at `:10-12`); until then mcp-read refuses to start on it.

### 3.5 Ingestion (`ops_core.ingest`, `scripts/skeleton.py ingest`)

- `core/src/ops_core/ingest.py:1-25` (docstring): runs as role `worker`; "A run first plans every tenant against what is
  stored, each in a read-only unit under its tenant setting, and writes nothing if any tenant's plan is refused …; then
  it writes each tenant in one transaction, re-planning inside it". A new version: "its document row, one chunk per
  section and its first state row"; the same version with the same hash and attributes: "nothing, unless its lifecycle
  … changed, which appends one state row"; another hash or attribute: refused; "a stored version the catalog no longer
  lists" refused. "A tenant whose plan changes nothing and whose latest ingestion already names this corpus version and
  lock gets no row at all, so a repeated run writes nothing". "The clock is never consulted here".
- `_write` (`:222-272`): INSERTs into `corpus_ingestions`, `documents`, `chunks` (one per section:
  `tenant_id, document_id, version, ordinal, section, evidence_id, body, content_sha256, start_offset, end_offset,
  word_count`, `:249-268`) and `document_states`. `ingest(conn, corpus, tenants)` (`:275-328`): asserts `RELATIONS`
  (`:41`), refuses unknown tenants, phase 1 plans all tenants, phase 2 one transaction per tenant;
  `IngestRefused`/`IngestInterrupted` (`:44-66`).
- An embedding step would sit in `_write`'s per-chunk loop (`:249-268`) or as a separate pass; today nothing in
  ingestion calls a network service, and a repeated run of an unchanged corpus writes nothing (so rows ingested before
  an embedding step exists would not be revisited by `ingest` as written).
- `scripts/skeleton.py:257-293` `ingest()`: loads `.env`, `corpus.load(CORPUS)`, connects as
  `settings.app_postgres(Role.WORKER)` to `OPS_PG_DB` (default `ops`; the live suite's `ops_test`); prints `INGEST:
  <tenant> <version>: n new, n restated, n unchanged`; exit 1 with problems and nothing written on refusal. The live
  fixture `ingested` (`tests/e2e/conftest.py:81-91`) calls `ingest.ingest` as the worker into `ops_test`.
- `core/src/ops_core/corpus.py`: `Section(name, start, end, body, sha256, words)` (`:82-91`); `sections(text)`
  (`:138-156`) splits on `^## ` headings; `Document.evidence_id(section)` = `f"{document_id}:v{version}:{section.name}"`
  (`:115-117`); `RELEASES = {"corpus-1": "81f50c2b8623675f9c899033cba748f289b7f4024003385aabc8a95147b71862"}`
  (`:67-69`); `returnable(corpus, now)` (`:474-494`), the Python restatement of the SQL lifecycle rule.
- corpus-1: 16 documents, 14 document IDs, two tenants (alpha 9, beta 7), 69 sections of 45-119 `[a-z0-9]+` words
  (median 77); 15 sections have bodies of 504-669 characters (`docs/retrieval.md:10-12`, `:43-45`, `:86`).

### 3.6 Ollama and model-pin code in the tree

- **No embedding client exists.** No module in `core/`, `mcp-read/`, `worker/` or `scripts/` calls an embedding
  endpoint, names `nomic`, or builds a `search_document:`/`search_query:` string. `uv.lock` has no `pgvector`,
  `langchain*`, `ollama` or `numpy` package (67 packages; checked by name). `ops-core`'s dependencies
  (`core/pyproject.toml:6`) include `psycopg[binary]`, `httpx2`, `jsonschema`, `pydantic`; `mcp-read`'s
  (`mcp-read/pyproject.toml:6`) are `ops-core`, `mcp==2.3.0`, `uvicorn`.
- `core/src/ops_core/model_pins.py` (56 lines): `ModelPins(model, digest, ollama_version, probed_at)` (strict, frozen,
  `extra="forbid"`; `Digest` = `^[0-9a-f]{64}$`), `load_model_pins(path)` raising `ModelPinsError`. Docstring (`:1-5`):
  "The digest is the bare 64-hex value Ollama reports in `/api/tags` (no `sha256:` prefix), exactly as
  `scripts/probe.py` writes it". Tests `tests/plan_b/test_model_pins.py`. No caller in a service.
- `data/model-pins.json` is absent. `schemas/model-pins.schema.json` (one object, four keys); examples
  `schemas/examples/model-pins-valid.json`, `model-pins-invalid-prefixed-digest.json`.
- `scripts/probe.py` (T02): `OLLAMA = "http://127.0.0.1:11434"` (`:54`); `ollama_json(path, payload)` (`:72-81`);
  `model_digest()` reads `/api/tags` ("/api/tags carries digests, /api/show does not", `:84-89`); writes
  `data/model-pins.json` for `qwen3:8b` (`:406-413`). Never run (the T03 seal `evals/holdout.sha256` is absent).
- `scripts/bootstrap_dev.py:60-61`: `OLLAMA_BASE_URL_HOST = "http://127.0.0.1:11434"`, `OLLAMA_BASE_URL_CONTAINER =
  "http://host.docker.internal:11434"`, written into the git-ignored `.env` (`:105-120`). These two names are not
  `OPS_*` and are read only by `tests/plan_b/live/test_ollama_bridge.py:18-20`.
- `core/src/ops_core/settings.py`: no Ollama or model URL; `Urls` (`:421-428`) holds `mcp_read_resource`,
  `mcp_write_resource`, `mcp_read`, `mcp_write`, `incident_sim`, `asset_sim` (`OPS_ASSET_SIM_URL` default
  `http://127.0.0.1:8091`). Docstring (`:5`): "Everything else — hosts, ports, URLs, the model mode — is an `OPS_*`
  variable with a dev default that matches the `.env` written by scripts/bootstrap_dev.py". `MODEL_MODE` is read by the
  worker (`worker/src/ops_worker/main.py:143`); only `fake` exists (`drafting.py:90`: "only 'fake' until T19").
- `docs/runbooks/ollama-network.md` (127 lines): step A binds `OLLAMA_HOST=127.0.0.1:11434` at User scope (`:56-64`);
  containers reach it through Docker Desktop's loopback proxy (`:48`); attestation row 2026-10-16 (`:112`): step A
  applied, listener `127.0.0.1 11434` only, `test_ollama_bridge.py` 1 passed; the other-device LAN check and the
  firewall rules remain the owner's. `docs/runbooks/dev-topology.md:60-67`: host processes use
  `OLLAMA_BASE_URL_HOST`, containers `OLLAMA_BASE_URL_CONTAINER`. `reports/bootstrap/ollama-bridge.txt`: both routes
  answered `0.33.3`.
- Observed environment (`SESSION_STATE.md:1216`): "Ollama | Observed at 0.40.4 on 2026-10-15 (recorded 0.33.3 before …);
  `qwen3:8b` and `nomic-embed-text` installed as last recorded". The `nomic-embed-text` install was first recorded in
  the planning session (commit `35571c7`: "| Ollama | 0.33.3, with `qwen3:8b` and `nomic-embed-text` installed |"). No
  digest, size or dimension of `nomic-embed-text` is recorded anywhere in the tree.
- **How mcp-read could reach Ollama:** today it reaches only PostgreSQL and asset-sim. Its asset-sim client
  (`mcp-read/src/ops_mcp_read/assets.py`) is the existing outbound-HTTP template: `httpx2.AsyncClient` with
  `TIMEOUT_SECONDS = 10.0` (`:28`, `:105`), no retry, `Unavailable` (`code = "UNAVAILABLE"`, `retryable = True`) for a
  transport error, timeout or 5xx (`:40-44`), built in the lifespan by `HttpAssetSim.from_settings()`
  (`server.py:434`). mcp-read and the worker are host processes started by `scripts/skeleton.py up` (`PROCESSES`,
  `skeleton.py:346-354`: asset-sim 8091, incident-sim 8090, mcp-read 8081, mcp-write 8082, api 8000, worker 8070,
  sweeper 8071); none is containerised yet (T30).

### 3.7 mcp-read's search tool, `UNSUPPORTED_MODE` and the schemas

- `server.py:345-399` `search_procedures(query: str 1..500, limit: int 1..8, mode: Literal["lexical",
  "vector_exact"], ctx, asset_type: str 1..40 = "")`. Order: unit 1 `resolve(name, ctx)` (`:358`; `resolve_invocation`
  + `persistence.allowed_tool`); **then** `if mode != "lexical":` (`:361`) → `UNSUPPORTED_MODE` "vector_exact arrives
  with T18" (`:362-365`, comment "The handle first, then the mode: an invalid handle never learns what the server
  supports (ruling 14)"), on the wall clock (no `observed_at` passed); unit 2 `scope_of` (`asset_scope`, `:366`);
  asset-sim's run asset type (`:374`; `ASSET_TYPE_OUT_OF_SCOPE` if a caller's type differs, `:378-380`); unit 3
  `persistence.search_procedures(…, asset_type=run_type or asset_type or None, limit)` (`:386-393`); `HandleRejected`
  → `INVALID_HANDLE`, `Refused` → `REFUSED` with `exc.code` (`:394-398`); `return search_response(found)` (`:399`).
- `search_response(found)` (`server.py:105-130`) hard-codes `"retrieval_mode": "lexical"` (`:127`); stamps
  `retrieved_at`/`observed_at` from the definer's instant; drops `rank`.
- `persistence.search_procedures(conn, *, handle, azp, query, asset_type, limit)` (`persistence.py:487-522`) calls
  `"SELECT * FROM app.search_procedures_scoped(%s, %s, %s, NULL, %s, %s, 'lexical')"` (`:500`); `Procedure`
  (`:461-473`, `rank: float` — "`ts_rank_cd`'s score: it orders the results of one query and means nothing across
  queries or methods"); `Procedures(corpus_version, results, retrieved_at, truncated)` (`:476-484`). Errors:
  `translate` (`:84-94`) maps `OC005` → `Refused(detail)` and `OC008` → `HandleRejected` (`OC_CODES`, `:72-81`).
- `schemas/tools/search_procedures.input.schema.json`: `query` 1-500, `asset_type` 1-40, `limit` 1-8, `mode` enum
  `["lexical", "vector_exact"]` (`:24-29`), required `query, limit, mode`, `additionalProperties: false`. The result
  schema (`schemas/tool-result.schema.json:306-383`): results ≤8 rows of `evidence_id, document_id, version, section,
  content_sha256, excerpt (≤8000), effective_from, retrieved_at` (no score field), `retrieval_mode` enum `["lexical",
  "vector_exact"]` (`:367-372`), `corpus_version`. `schemas/run-manifest.schema.json:44` and `RunManifest`
  (`routing.py:350-364`) allow `retrieval_mode` `lexical | vector_exact`. All generated by `scripts/build_schemas.py`
  (`:593`, `:784`, `:861`).
- `ops_core.tool_contracts` (`:4`): "mcp-read advertises exactly `schemas/tools/<tool>.input.schema.json` as each
  tool's input schema"; the worker refuses an advertised schema that differs (`same_input_schema`, `:43`) and checks
  every result (`check_result`, `:57`). The committed input and result schemas already carry `vector_exact`.
- The worker's only search call sends `"mode": "lexical"` (`worker/src/ops_worker/handlers.py:128`, `"limit": 3`,
  query cut at `QUERY_CHARS = 500`, `:39`); `proposals.py:100-107` builds `RunManifest(… retrieval_mode="lexical")`
  (the manifest is not stored anywhere yet; T19 writes it). `evidence_from_search` (`proposals.py:35-54`) does not read
  `retrieval_mode`.
- Tests that pin today's vector refusal: `tests/plan_l/test_mcp_read_corpus.py:179-184` (`vector_exact` refused after
  `resolve`, before any search), `tests/e2e/test_mcp_read_live.py:90`, `:112` (live `UNSUPPORTED_MODE`),
  `tests/plan_m/test_mcp_read_assets.py:382` (a `vector_exact` argument set), `tests/plan_c/test_jobs_routes_outcomes.py
  :356-357` (`RunManifest` accepts `vector_exact`).

### 3.8 T17's retrieval baseline (the harness T18 compares against)

- **Queries:** `evals/retrieval/dev-queries.jsonl`, 47 lines, one JSON object each with exactly the keys `id, tenant,
  category, query, asset_type, expected, expect_none` (`scripts/retrieval_baseline.py:37`); categories (`:25-36`):
  `answerable, superseded, expired, revoked, draft_only, missing_source, cross_tenant, asset_filtered, injected,
  conflicting`; 27 with labelled sections, 20 `expect_none`. Agent-authored development data labelled against corpus-1
  (`docs/retrieval.md:105-107`). Unit checks: `tests/plan_l/test_retrieval_baseline.py` (`:26` categories per tenant,
  `:36` every label a permitted section of its tenant, `:58` Wilson, `:72` denominators).
- **Metrics module:** `scripts/retrieval_baseline.py` (314 lines): `K = 5` (`:24`); `SETTINGS` (`:40-53`, recorded in
  every report: method, text_search_config, document_vector, query, rank, tie_break, minimum_rank, k, chunk,
  filters); `Case` (`:56-66`); `Outcome(case, returned: tuple[(evidence_id, rank)], forbidden)` (`:69-84`);
  `load_queries` (`:87-111`); `evaluate(case, returned, permitted)` (`:114-117`); `wilson(successes, n, z=1.959964)`
  (`:120-127`); `proportion` (`:130-140`); `summarize` (`:143-192`: recall@k, precision@k, precision ceiling, MRR@k as
  means over answerable cases; hit@k, all-expected@k, none-answered-empty, cases-without-forbidden as proportions with
  Wilson 95%; forbidden rows over returned rows; by category); `chunk_sizes` (`:195-197`); `report(…)` (`:200-238`,
  `"report": "t17-lexical-baseline"`, `measured_at`, `as_of`, `corpus_version`, `lock_sha256`, `queries_sha256`,
  `settings`, `chunk_words`, `summary`, per-case ranked answers with `rank` rounded to 6 places); `markdown(doc)`
  (`:248-314`). No McNemar, bootstrap or paired comparison code exists.
- **Live harness:** `tests/e2e/test_retrieval_baseline_live.py:48-110`
  `test_r033_the_lexical_baseline_on_the_development_queries`: fixture `ingested`; moves `app.test_clock` to `AS_OF`
  as `test_harness` (`:59`); one staged run per tenant with the seeded requesters (`REQUESTERS`, `:39-42`), a lease of
  600 s (`:62`), a fresh read handle per query (`:83`); asserts `corpus.returnable(governed, now) ==
  corpus.returnable(governed, AS_OF) == RETURNABLE_AT_AS_OF` (`:70`); calls `persistence.search_procedures(mcp_read,
  …, limit=rb.K)` (`:84-86`); resets the clock and purges the runs (`:90-93`); asserts no forbidden section (`:105-106`)
  and `hit_at_k.successes > 0` (`:107`); **rewrites** `reports/retrieval/t17-lexical-baseline.json` and `.md` on every
  live run (`:108-110`). `AS_OF = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)` and `RETURNABLE_AT_AS_OF`
  (`tests/plan_l/test_corpus_files.py:34`, `:38`; the hand-written anchor, `:81`).
- **Committed report** (`reports/retrieval/t17-lexical-baseline.md`, `.json`; last committed in `753fa6f`, Plan L):
  measured `2026-10-18T06:31:44Z`, `as_of` `2026-10-16T12:00:00Z`, corpus-1, `queries_sha256`
  `d6d539bdd9a540f6e7a66dd641c05e5c1ee97c1561c59f5b67896fedb1596938`; recall@5 1.0; precision@5 0.2296 (ceiling
  0.2296); MRR@5 0.8963; hit@5 27/27 (Wilson 0.88-1.00); every expected 27/27; no-source answered empty 15/20 = 0.75
  (0.53-0.89); cases without forbidden 47/47 (0.92-1.00); forbidden rows 0/122; no-source cases that still returned
  sections A15, B10, B13, B17, B18. Its `settings.method` still reads "(revision 0011)".
- `docs/retrieval.md` (122 lines): corpus (`:8-45`), ingestion (`:47-67`), the search settings table (`:69-89`), "How to
  read a score" (`:91-95`: `ts_rank_cd` "is not a probability, it is not comparable between two queries, and it is not
  comparable with T18's vector distances (BS:417). It never reaches the model or the tool result; the measurement
  records it."), "What it cannot do" (`:97-101`), the measurement (`:103-122`).

### 3.9 CI and how live tests skip

- `.github/workflows/ci.yml`: one job on `ubuntu-24.04`, 15-minute timeout, `contents: read`; steps: checkout (pinned
  SHA), setup-uv, `uv python install 3.13`, `uv sync --locked --all-packages`, `uv run python scripts/check.py`,
  `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`. No PostgreSQL, Keycloak,
  Docker stack or Ollama service; no live tests run.
- `scripts/check.py` (`:1-6`, `:46-64`): ruff, ruff format, mypy, pytest; `--profile dev` (default, database-free) or
  `--profile test` (sets `OPS_LIVE=1` and `PROFILE=test`; "needs the dev stack up"). Live fixtures skip without
  `OPS_LIVE=1`: `tests/e2e/conftest.py:38-40` ("live walking-skeleton tests run only with OPS_LIVE=1"),
  `tests/plan_b/live/conftest.py:12-16`. The live suite drops and recreates `ops_test`/`incident_test` and migrates
  them under the test profile (`tests/e2e/conftest.py:3-6`, `:34`, `:74-78`).
- The live gate already needs the host's Ollama: `tests/plan_b/live/test_ollama_bridge.py` (collected via
  `pyproject.toml:48-51` `testpaths`, which include `tests/plan_b`) GETs `/api/version` from
  `OLLAMA_BASE_URL_HOST` and from a container at `OLLAMA_BASE_URL_CONTAINER`, and writes
  `reports/bootstrap/ollama-bridge.txt`.
- Unit-test fakes in use for mcp-read: `tests/plan_l/test_mcp_read_corpus.py` drives the server with `Database(UnitConn())`
  recording the calls (`:179-184`); the asset-sim client is faked behind the `AssetSim` protocol (`assets.py:71`).
- `pyproject.toml:48-51` `testpaths` lists `tests/plan_a` … `tests/plan_m`, `tests/e2e` (no `tests/plan_n` yet).

### 3.10 Gates

- After Plan M (`SESSION_STATE.md:863`; `STATUS.md:329-330`): `check.py` `1372 passed, 205 skipped`; `check.py
  --profile test` `1556 passed, 21 skipped`; `verify_handoff.py` exit 0. `STATUS.md:329` runs them with
  `PYTHONUTF8=1`.
- `scripts/verify_handoff.py --contracts` meta-validates `schemas/tools/*.json` (SA:749) and `ops_core.corpus.load`
  refuses a changed corpus without a new lock (`docs/retrieval.md:32-35`: "fails `ops_core.corpus.load` (and so
  ingestion, the unit tests and `scripts/verify_handoff.py`)").

---

## 4. Prior rulings, debt lines and proposed errata that touch T18

Errata are proposed in `SESSION_STATE.md`; the owner decides, the spec stays authoritative until then.
`SESSION_STATE.md:9-10`: owner input (3) "decide the proposed errata of Plans C, E, F, G, H, I, J, K, L and M (errata
1-106; M: 103-106 below)". New errata continue at **107**.

- **3** (`SESSION_STATE.md:147`): `mode=vector` is the SQL value, `vector_exact` the external one; "mcp-read
  translates between them."
- **93** (`:782-786`): the signature `(raw_handle, client_azp, query, query_embedding vector(768), asset_type, limit,
  mode)`; "returns one row `(corpus_version, results)` … the ranked results with a `rank` each, which mcp-read leaves
  out of the tool result."
- **95** (`:794-796`): "`embeddings` is created by T18, its first writer."
- **98** (`:802-804`): ingestion is an operator command as `worker`, not a job type and not a `migrator` data
  migration.
- **99** (`:805-807`): vector mode refused (`OC005` `VECTOR_MODE_UNAVAILABLE`) until T18; the `vector` extension is
  bootstrap infrastructure.
- **100** (`:808-810`): one chunk per section; "another window is evaluated in T18's comparison."
- **102** (`:814-819`): R033's no-source residue (5/20) open; T20 must add a relevance criterion.
- **103** (`:867-870`): "T16's instruction and review note (`handoff/tasks.json`, "vector mode: mcp-read computes the
  nomic search_query embedding"), SA:348 and SA:461: mcp-read's `vector_exact` → `mode=vector` translation and the
  `search_query:` embedding move to T18 with the embeddings; until then mcp-read answers `vector_exact` with
  `UNSUPPORTED_MODE` after the handle resolution, and the definer refuses `mode=vector`."
- **106** (`:885-889`): the 0012 answer `(corpus_version, retrieved_at, results)`; excerpts whole up to 8000 with
  `excerpt_cut`; "on corpus-1, 15 of the 69 sections (504 to 669 characters) now return whole."
- Plan L plan rulings (`docs/reviews/plan-review-l-2026-10-17.md`):
  - ruling 2 (`:42-49`): "The `vector` extension is **bootstrap infrastructure** … The revision does not create or drop
    it … The function has SA:461's full signature with `query_embedding public.vector(768)` (schema-qualified: definers
    pin `search_path = app, pg_temp`). `mode = 'vector'` is refused inside the function with a distinct error class
    until T18 (debt line). mcp-read keeps answering `vector_exact` with `UNSUPPORTED_MODE` before calling it (the
    translation `vector_exact` → `mode=vector` stays T16/T18)."
  - ruling 3 (`:50`): "`embeddings` → T18 (debt; no table without a writer)."
  - ruling 4 (`:56-60`): "One chunk per `## ` section … No tokenizer package: the chunk-size measure is recorded as the
    `[a-z0-9]+` word count and the report prints the distribution; evaluating another window is a T18 debt line (the
    comparison report)."
  - ruling 18 (`:119-125`): "A minimum-rank threshold is a recorded retrieval setting chosen on the dev queries only (it
    may be 0); the settings and the score interpretation ("ranks within one query, not a probability, not comparable
    across methods") are written in `docs/retrieval.md`. No score in the tool result (the schema has none); the
    measurement records it." Round 1 (`:630-635`) adopted 0.25 in `app._min_rank()` with "tuning → T18 with the
    comparison".
  - round-1 measurement (`:1030-1041`): "**The `records` heading.** It matches any question that contains "record". A15
    … is answered by four `records` sections of other documents … These are measurements for T18, not defects. But
    corpus-1 is frozen at execution, so this is the last cheap moment to decide."
- Plan M plan ruling 1 (`docs/reviews/plan-review-m-2026-10-18.md:44-49`): "**Vector mode (FS Q1) — defer to T18,
  option (a).** No embedding model is pinned (T02 pending), no `embeddings` table exists, and T18 owns the prefix test.
  mcp-read keeps answering `vector_exact` with `UNSUPPORTED_MODE`; the `TODO(T16)` markers … become `TODO(T18)`.
  **Erratum 103** …". Ruling 14 (`tasks.json:781`): "the UNSUPPORTED_MODE order stays, the handle first".
  `docs/reviews/plan-m-final-review-2026-10-18.md:218`: "T18 gained the vector-mode note (erratum 103), and it is
  correct."
- Round-6 review (`docs/reviews/plan-review-r6-2026-10-06.md:49`): "**T16/T18:** `search_procedures_scoped` takes text
  only, so vector search cannot run inside it without an embedding argument. Add one (or embed inside the function via a
  trusted embedding service)." (SA:461's `query_embedding` argument is the [R6] answer.)
- Handoff review (`docs/reviews/handoff-review-2026-10-06.md:166`): "The 8 fixture docs total 463 words, smaller than
  one specified 300–600-token chunk, so chunking and the lexical-vs-pgvector comparison are meaningless." (answered by
  corpus-1, T17).
- Planning review (`docs/reviews/plan-review-2026-10-06.md:99`): "Tasks of about 5 days or more should be split: T18,
  T20, T21, T19, T05, T07, T11, T16, T17, T25." (T18 was not split.) `:129`: "pgvector does exact search by default."
  `:140`: the prefix requirement.
- T19's note on digests (`tasks.json:853`): `/api/show` carried no digest for qwen3:8b on Ollama 0.33.3; `probe.py`
  uses `/api/tags`. `docs/runbooks/ollama-network.md:114-116` proposes an AM-31 erratum (loopback bind as the primary
  control).
- Plan L ruling (e) (`SESSION_STATE.md:828-833`): the baseline pins the test clock to `AS_OF` and asserts the permitted
  set equals `corpus.returnable(AS_OF)` and the hand-written set; "the in-measurement forbidden check is circular".
- `docs/PROJECT_HISTORY.md:708`: Plan M's fact sheet "found eighteen open questions, and the controller's brief ruled on
  each, deferring vector mode to T18." No PROJECT_HISTORY entry records a ruling on the embedding model's pin,
  storage, index, chunk window or the comparison's statistics.
- No document records a ruling on: where embeddings are stored, who computes the document embeddings, the vector
  distance operator, a vector threshold, a vector index, the comparison report's statistics beyond recall@k with
  denominators and CIs, or how mcp-read reaches Ollama.

---

## 5. Open questions the planner must rule on

1. **Where the embeddings live (revision 0013).** For a separate `app.embeddings` table: SA:431 and SA:510 name it
   (worker ins/sel, app_definer sel, ENABLE+FORCE RLS, `tenant_isolation`); BS:242 lists "embedding
   model/dimension/index version" as attributes; erratum 95 says T18 creates it; Plan L ruling 3 ("no table without a
   writer"); a separate table can hold more than one model or window per chunk. For a column on `chunks`: one row per
   section already exists (PK `(tenant_id, evidence_id)`), but AM-20.2 gives no role UPDATE on `chunks` (only
   `worker` INSERT/SELECT), so a column could be filled only at INSERT (new chunks) or by a `migrator` data migration
   (`BYPASSRLS`, SA:395), and corpus-1's 69 rows in the dev database already exist without it. Open: table vs column;
   the key (`(tenant_id, evidence_id)` alone or with model/dimension/window); the columns (embedding
   `public.vector(768)`, model name, digest, dimension, prefix, window/index version, created_at); FKs to `chunks`;
   grants/RLS per SA:431/SA:510 and the `privileges` rows (`GRANTS`, `RLS_TABLES`); the exact downgrade; whether the
   0013 revision also re-creates `search_procedures_scoped` (a body change: `changed()`-style edits from 0012's body,
   0012's pattern, the `GOVERNED_CORPUS`/`SEARCH_INSTANT` markers kept or updated, and a new marker for mcp-read to
   assert at start).

2. **Who computes and writes the document embeddings, and when.** Facts: ingestion runs as `worker` from
   `skeleton.py ingest` on the host (erratum 98), plans every tenant before writing and writes nothing on an unchanged
   corpus (`ingest.py:19-21`); it consults no clock and no network today; host processes reach Ollama at
   `127.0.0.1:11434`; the spec puts Ollama on the worker's path (BS:645) and SA:431 calls the worker cells
   "(ingestion)". Options: (a) inside `ingest` per new chunk (an Ollama outage then refuses or interrupts ingestion;
   idempotency must cover "chunk stored, embedding not yet"); (b) a separate operator command (e.g. `skeleton.py
   embed`) as `worker`, idempotent by `(tenant, evidence_id, model, digest[, window])`; (c) a `migrator` data migration
   (contradicts erratum 98's "not a `migrator` data migration" and puts a network call inside Alembic). Open also:
   whether the embedding step refuses a model whose digest differs from the pin, what it does for chunks whose version
   is revoked/expired (embed every stored chunk, or only those returnable), and whether embeddings are batched.

3. **How the model, dimension and digest are recorded and verified.** Facts: T18 "record model, dimension, digest";
   R034 "Record model/dimension/corpus"; `data/model-pins.json` is absent and its schema holds exactly one model
   (`{model, digest, ollama_version, probed_at}`, `additionalProperties: false`) owned by T02 for `qwen3:8b`;
   `ops_core.model_pins` expects the bare 64-hex digest from `/api/tags`; T19's note says `/api/show` carried no digest
   for qwen3:8b on Ollama 0.33.3 while AM-31 names `/api/show`; the installed Ollama was observed at 0.40.4 (not
   0.33.3); no digest of `nomic-embed-text` is recorded anywhere; T02's probe needs the T03 seal (owner). Options: a
   second pins file (e.g. `data/embedding-pins.json`) with its own schema; widening `model-pins` (a schema change,
   and T02/T19/R127 consume it); recording model/digest/dimension per embedding row and in the comparison report only;
   a checked-in constant. Open also: who verifies (ingestion, mcp-read at start, both), against which endpoint
   (`/api/tags` digest vs `/api/show`), whether the embedding's length is checked against 768, what happens on a
   mismatch (refuse to start, refuse vector mode, `UNAVAILABLE`), and whether a model upgrade means a new
   index/embedding version (BS:572 "corpus/index version", BS:670).

4. **Where the query embedding is computed, and how mcp-read reaches Ollama.** For mcp-read: SA:348 and SA:461 ("optional
   embedding computed by mcp-read with the `search_query:` prefix"), erratum 103, T18's review note. Against or
   unaddressed: BS:646's MCP row and BS:136-151 give MCP no Ollama route; ADR-0001:31 lists "worker → Ollama" only;
   `docs/ARCHITECTURE.md:63` says mcp-read reaches PostgreSQL and asset-sim; `settings` has no Ollama URL (only the
   non-`OPS_*` `.env` keys `OLLAMA_BASE_URL_HOST`/`_CONTAINER`); `model_permit` (global model concurrency 1, SA:203)
   is a `worker` table mcp-read cannot read (SA:437); T30's network tests name no mcp-read → Ollama rule; BS:629
   requires documented host/container addresses and egress tests. Open: the setting name(s) and default
   (`OPS_OLLAMA_URL`-style vs reusing `OLLAMA_BASE_URL_HOST`), timeout and retries (BS:552 read-tool caps; the asset-sim
   client's 10 s, no retry, is the existing pattern), the envelope code for an unreachable or wrong model (e.g.
   `UNAVAILABLE` retryable, as `assets.Unavailable`), whether the embedding call counts against `model_permit` or the
   model budget (BS:549), whether `docs/ARCHITECTURE.md`, ADR-0001 and the threat model need an amendment or an
   erratum, and whether the call happens before or after `asset_scope` (unit order, ruling 14's handle-first rule).

5. **What "the same filters" means in vector mode, and the definer's argument rules.** The lexical path filters by the
   handle's tenant (RLS), latest state `approved`, effective at `app.current_time()`, not retired, asset family equal to
   `asset_type` or NULL, and (0012) the requester's active membership — all before ranking. Facts: the vector refusal
   sits after the membership check and before `BAD_ARGUMENT` (`0011:177-185`), so no argument rule exists for
   `mode='vector'` (query length, embedding NULL, embedding dimension, limit); SA:461 says vector mode "requires the
   embedding" and still takes the text `query`. Open: whether the vector branch reuses the same `latest`/`effective`/
   `permitted` CTEs verbatim (shared text, so a filter cannot drift; a unit test comparing them), whether `p_query` is
   still required/bounded in vector mode, the refusal for a NULL or wrong-dimension embedding (`BAD_ARGUMENT`?), and
   whether `corpus_version`, `retrieved_at`, `excerpt_cut` and the stop-word early return behave the same.

6. **Score, ordering and threshold for vector results.** Facts: BS:417 "scores from different methods are not
   interchangeable probabilities" and "store retrieval settings and score interpretation"; the tool result has no score
   field and mcp-read drops `rank` (`server.py:105-130`); `Procedure.rank` is a float the measurement records; the
   lexical tie-break is `evidence_id COLLATE "C"`; lexical keeps only `rank > app._min_rank()`, and no vector threshold
   exists; erratum 102 leaves an abstention rule to T20 "(for example a score or label-based sufficiency rule)". Open:
   the distance operator (cosine, L2 or inner product) and whether embeddings are normalised; what the `rank` key holds
   in vector mode (distance, similarity, or the same key name with another meaning); the ordering and tie-break; whether
   vector mode has a minimum similarity (a second helper like `_min_rank`, chosen on the development queries) or always
   returns `limit` rows (which would answer every no-source question); and the `docs/retrieval.md` score interpretation.

7. **Exact search: no index, or an index that keeps it exact.** Facts: T18 title "Exact pgvector retrieval"; SA:461
   "exact vector (`mode=vector`…)"; BS:54 defers "approximate search"; BS:71 "index approximation only with evidence";
   the external mode name is `vector_exact` (erratum 3); the planning review says "pgvector does exact search by
   default" (`plan-review-2026-10-06.md:129`); corpus-1 has 69 chunks. Open: no vector index at all (a sequential scan
   over the tenant's permitted chunks) vs any index; whether a test proves exactness (e.g. comparing the SQL's order
   with a Python brute-force ranking over the same stored vectors); and what "index version" (BS:242) means if there is
   no index (a model/window version instead).

8. **The chunk window ("another chunk window").** Facts: BS:415 "The exact tokenizer/window choice must be recorded and
   evaluated"; erratum 100 and Plan L ruling 4 put "another window" in T18's comparison; corpus-1's sections are 45-119
   words (below the 300-600-token proposal); evidence IDs are per section (SA:643) and are what proposals cite;
   `chunks` enforces `evidence_id = document_id:v<version>:<section>` and one row per `(document, version, ordinal)`;
   T41 labels the holdout against the frozen corpus and "Corpus changes after this require re-labelling" (a different
   window does not change locked files but would change what a citation names); no tokenizer is locked
   (`docs/retrieval.md:44-45`). Open: whether T18 evaluates another window at all, as what (merged sections, fixed
   token windows with overlap, the same sections with heading text prepended), how it is measured against labels that
   name sections (a window's hit = any contained labelled section?), whether an evaluated window may become the stored
   unit (an evidence-ID and T41 consequence) or stays an experiment in the report, and whether "recorded" means a
   setting in the report only.

9. **Tuning the lexical minimum rank.** Facts: `app._min_rank()` returns 0.25 (`0011:150-158`), "chosen on the
   development queries", the same queries that measure it (R033 note: "development figures, not held-out ones");
   `ts_rank_cd` is unnormalised so the threshold depends on query length (`docs/retrieval.md:85`); the five no-source
   questions answered (A15, B10, B13, B17, B18) come from generic words such as `records`; the helper exists "so a later
   revision changes it in one place"; the `GOVERNED_CORPUS` marker is the ranking text (`ts_rank_cd(c.search, v_query)`).
   Open: whether T18 changes the value (a body-free helper re-creation in 0013), changes normalisation (a
   `ts_rank_cd(…, n)` flag changes the marker text), records a sweep in the comparison report without changing it, or
   leaves it; and how any tuning on the 47 development queries is labelled (development figure).

10. **The numeric-token lexeme debt.** Facts: the query is normalised by `regexp_replace(lower(p_query), '[^a-z0-9]+',
    ' ', 'g')` (`0011:192`) while chunk text is parsed raw by `to_tsvector('english', …)`, so `4.5` or `M8x1.25` cannot
    match as one lexeme (Plan L debt line → T18); the normalisation guards the OR-query builder against tsquery syntax.
    Open: fix it in T18's revision (changing lexical results, so the baseline is re-measured), measure it only, or
    re-home it.

11. **The comparison report: content, statistics and location.** Facts: DoD 1 names `reports/retrieval-comparison.md`
    (top level of `reports/`), while T17's files are `reports/retrieval/t17-lexical-baseline.{md,json}`; R034 wants
    "model/dimension/corpus and matched question retrieval results, including regressions"; BS:707 "named retrieval
    experiment"; T17's harness gives recall@5, precision@5 (+ceiling), MRR@5, hit@5, every-expected@5,
    none-answered-empty, cases-without-forbidden with Wilson 95% and denominators, forbidden rows, per-category rows,
    per-case ranked answers; no paired statistic exists in the code; SA:667's "paired exact McNemar … No ranking claim
    without p < 0.05" is written for the model-quality evaluation; with 27 labelled cases at recall 1.0 lexically, a
    vector method cannot show a higher hit@5; the live baseline test rewrites the lexical report on every live run.
    Open: the file(s) and path (the DoD's `reports/retrieval-comparison.md`, plus `.json`?); whether the lexical side
    is re-measured in the same run or read from the committed JSON (`queries_sha256`, `as_of` must match); whether k
    is 5 only or a sweep (k = 3 is what the worker asks for, `handlers.py:128`); per-question regressions and
    improvements listed by id ("matched question"); paired statistics (McNemar on hit@k, or none, with the power caveat
    of SA:668); whether the forbidden rule (zero) is a hard assertion for vector mode too; whether new development
    queries may be added (they are agent-authored dev data; the holdout is never read); and which settings are
    recorded (model, digest, dimension, prefixes, distance, threshold, window, Ollama version).

12. **The prefix test (DoD 2).** Facts: SA:645 "with a test that they are applied"; T18 DoD 2 "Prefix application
    asserted by a test"; no embedding code exists. Open: what the test asserts and where (a unit test on the request
    body an embedder sends: `search_document: <text>` at ingestion and `search_query: <query>` in mcp-read, with a fake
    transport), whether a live test also proves it (e.g. that the stored vector equals an embedding of the prefixed
    text, or differs from the unprefixed one), and what exact text follows the prefix for a document (body only, or
    heading plus body; the lexical vector weights the heading A and body D).

13. **How tests run without Ollama.** Facts: CI runs `check.py` (dev profile) only, with no database and no Ollama
    (`.github/workflows/ci.yml`); live tests skip without `OPS_LIVE=1`; the live gate already requires Ollama for
    `test_ollama_bridge.py`; mcp-read's unit tests fake the database (`Database(UnitConn())`) and asset-sim (the
    `AssetSim` protocol); T31 later adds "a separate trusted workflow for real-model checks run manually". Open: an
    embedder protocol with a deterministic fake for unit tests (e.g. hash-derived vectors) vs recorded vectors; whether
    the live suite (`--profile test`) computes real nomic embeddings during `ingested` (adding Ollama to every live
    session that ingests) or a separate opt-in marker gates the Ollama-dependent tests; how live tests that need
    deterministic vector results avoid depending on the model (stored synthetic vectors written as the superuser vs
    real embeddings); and whether the comparison measurement is a live test (as T17's) that rewrites the report.

14. **Determinism of nomic embeddings.** Facts: BS:443 notes temperature 0 does not guarantee identical generation; no
    spec or tree line covers embedding determinism; the lexical baseline is reproducible because the clock is pinned to
    `AS_OF` and the tie-break is byte-ordered. Open: whether a re-embedding of the same text must be byte-identical
    (float equality) or within a tolerance (and which norm), whether stored vectors are the source of truth for the
    measurement (computed once at ingestion, query vectors at measurement time), whether the report records a
    repeat-embedding check, and how near-equal distances are tie-broken so a retry cites the same evidence.

15. **The dev database, re-ingestion and corpus-1's lock.** Facts: the dev `ops` database is at 0011 with corpus-1
    ingested and waits for the owner's migrate to 0012 (`SESSION_STATE.md:1286-1289`); migrations and ingestion on dev
    are owner actions (the agent may not run them); a repeated `ingest` of an unchanged corpus writes nothing; corpus-1
    is frozen by `RELEASES` and T41 labels against it; the services start on an empty or partial corpus (erratum 98).
    Open: the owner steps T18 adds (migrate to 0013, then an embed/backfill command), what mcp-read does in vector mode
    when a tenant has chunks without embeddings (refuse with a code, return only embedded chunks, or treat as empty),
    whether mcp-read refuses to start without 0013's marker (as for 0011/0012), and confirming that T18 changes no
    locked corpus file (so corpus-1 stays the version T41 labels).

16. **Who chooses vector mode, and the committed schemas.** Facts: the committed input schema's `mode` enum already
    contains `vector_exact` and mcp-read advertises the committed file exactly (R029's check compares it), so vector
    mode needs no input-schema change; the result schema's `retrieval_mode` enum also has `vector_exact`, while
    `search_response` hard-codes `"lexical"`; the worker always sends `"mode": "lexical"` and `RunManifest` is built
    with `retrieval_mode="lexical"`; SA:660 requires B and C to use identical retrieval settings; T19 writes the
    manifest. Open: whether T18 changes the worker's mode at all (a setting, e.g. `OPS_RETRIEVAL_MODE`, or left to
    T19/T20/T25), whether the manifest's `retrieval_mode` follows the tool result's, whether any new tool argument is
    added (which would change the committed schema and R029's comparison), and whether the `UNSUPPORTED_MODE` code
    survives for any case (e.g. no embedding model configured).

17. **Passing a vector from Python to PostgreSQL.** Facts: SA:584 names `pgvector-python` 0.5.0, which is not in
    `uv.lock`; `persistence.search_procedures` passes the literal `NULL` today; psycopg 3 is the driver; mypy runs strict
    (`pyproject.toml:65-68`). Open: add `pgvector` (and register its psycopg adapter) vs pass a text literal cast to
    `public.vector` in SQL; where the adapter lives (`ops_core` for ingestion and mcp-read); and the type stubs.

18. **Acceptance evidence and records.** Facts: R034's evidence paths are empty, its suggested_test path is under the
    non-existent `tests/acceptance/`; past plans recorded `tests/e2e/*_live.py` plus `reports/<area>/` as evidence and
    flipped `implementation_status`/`evidence_status`; R033's note and `docs/retrieval.md` describe vector mode as
    refused. Open: R034's evidence paths (the comparison report, the live test, the unit tests), whether R033's note or
    R032's change, the `docs/retrieval.md` sections to add (settings and score interpretation for vector mode, BS:417),
    the runbook lines (`docs/runbooks/mcp-read.md:74-75`, `:127`), and the errata T18 proposes from 107 (for example
    against SA:348/BS:646/ADR-0001 on mcp-read's Ollama route, or against SA:598 on pins).

---

## 6. Glossary of exact names

- **Task/requirement:** `T18` (M06, "Exact pgvector retrieval and comparison"), `R034` ("Exact vector retrieval is
  measured against the baseline", suggested test
  `tests/acceptance/test_r034_exact_vector_retrieval_is_measured_against_the_b.py`); DoD file
  `reports/retrieval-comparison.md`. Neighbours: `T41` (M06), `T25` (depends on T18), `T19`, `T20`, `T23`, `T02`,
  `T44`; `R032`, `R033`, `R037`, `R099`, `R101`, `R127`, `R130`.
- **Model and prefixes:** `nomic-embed-text`; `search_document:` (documents), `search_query:` (queries); dimension
  `768` (`public.vector(768)`); generation model `qwen3:8b`; Ollama port `11434`; endpoints named in the tree
  `/api/tags` (digest), `/api/show` (AM-31's digest source), `/api/version`, `/api/ps`, `/api/generate`.
- **Definer functions:** `app.search_procedures_scoped(text, text, text, public.vector, text, integer, text)` (args
  `p_raw_handle, p_client_azp, p_query, p_query_embedding, p_asset_type, p_limit, p_mode`; returns `corpus_version,
  retrieved_at, results`), `app.asset_scope(text, text)`, `app.resolve_invocation(text, text)`, `app.current_time()`;
  helpers `app._resolve_handle(text, text, text)`, `app._authority(text, text[])`, `app._min_rank()` (0.25),
  `app._dispatch_seconds()`.
- **Tables:** `app.corpus_ingestions`, `app.documents`, `app.document_states`, `app.chunks` (index `chunks_search`, GIN
  on `search`); spec-named, not created: `app.embeddings`. `app.model_permit` (worker), `app.test_clock` (test profile).
- **Roles:** `worker` (ingestion), `mcp_read` (EXECUTE on `current_time`, `resolve_invocation`, `asset_scope`,
  `search_procedures_scoped`; no table grants), `app_definer` (owns functions; SELECT on the corpus), `migrator`
  (owner, BYPASSRLS), `test_harness`, `api`, `sweeper`, `mcp_exec`, `operator`.
- **Error codes:** SQLSTATE `OC005` (`Refused`, DETAIL `VECTOR_MODE_UNAVAILABLE` or `BAD_ARGUMENT`), `OC008`
  (`HandleRejected`); envelope codes `UNSUPPORTED_MODE`, `INVALID_HANDLE`, `REFUSED`, `ASSET_TYPE_OUT_OF_SCOPE`,
  `UNAVAILABLE` (retryable, asset-sim client), `UPSTREAM_INVALID`.
- **Modes:** external `retrieval_mode` / tool `mode` `lexical` | `vector_exact`; SQL `p_mode` `lexical` | `vector`
  (erratum 3).
- **Modules and symbols:** `ops_core.persistence` (`search_procedures :487`, `Procedure :461`, `Procedures :476`,
  `translate :84`, `OC_CODES :72`, `assert_relation :170`, `assert_function_text :205`, `GOVERNED_CORPUS :191`,
  `ASSET_SCOPE :198`, `SEARCH_INSTANT :199`, `asset_scope :538`); `ops_core.privileges` (`GRANTS :73`, `RLS_TABLES
  :152`, `DEFINER_FUNCTIONS :197`, `HELPER_FUNCTIONS :222`, `function_grant_statements :297`); `ops_core.ingest`
  (`RELATIONS :41`, `_write :222`, `ingest :275`); `ops_core.corpus` (`RELEASES :67`, `sections :138`, `returnable
  :474`); `ops_core.model_pins` (`ModelPins :25`, `load_model_pins :37`); `ops_core.routing.RunManifest :350`;
  `ops_core.settings` (`Urls :421`, `urls :430`); `ops_core.tool_contracts`; `ops_mcp_read.server`
  (`search_response :105`, `search_procedures :345`, `build_app :411`); `ops_mcp_read.assets` (`TIMEOUT_SECONDS :28`,
  `Unavailable :40`, `HttpAssetSim :96`); `scripts.retrieval_baseline` (`K`, `SETTINGS`, `Case`, `Outcome`,
  `load_queries`, `evaluate`, `wilson`, `proportion`, `summarize`, `report`, `markdown`); `scripts.skeleton`
  (`EXTENSIONS`, `ensure_extensions`, `migrate`, `ingest`, `PROCESSES`); `scripts/probe.py` (`OLLAMA`,
  `model_digest`); `scripts/bootstrap_dev.py` (`OLLAMA_BASE_URL_HOST`, `OLLAMA_BASE_URL_CONTAINER`).
- **Migrations:** `0011_governed_corpus` (`REQUIRE_VECTOR`, `TABLES_0011`, `GRANTS_0011`, `MIN_RANK`,
  `SEARCH_PROCEDURES_SCOPED`, `FUNCTIONS`, `DOWNGRADE`, `EXCERPT_CHARS_0011`), `0012_asset_scope` (head;
  `MEMBERSHIP_CHECK`, `ASSET_SCOPE`, `CHANGES_0012`, `changed`, `SEARCH_ARGS`, `RESTORED`, `EXCERPT_CHARS_0012`),
  `tc_0001_test_clock`. Next revision number: `0013`.
- **Data and reports:** `data/corpus/` (`corpus-1`, lock
  `81f50c2b8623675f9c899033cba748f289b7f4024003385aabc8a95147b71862`; 16 documents, 69 sections); `data/seed-ids.json`;
  `data/model-pins.json` (absent); `schemas/model-pins.schema.json`; `evals/retrieval/dev-queries.jsonl` (47 queries,
  sha256 `d6d539bd…6938`); `reports/retrieval/t17-lexical-baseline.md`, `.json`; `reports/bootstrap/ollama-bridge.txt`.
- **Schemas:** `schemas/tools/search_procedures.input.schema.json` (`mode` enum `lexical`, `vector_exact`),
  `schemas/tool-result.schema.json` (`retrieval_mode`), `schemas/run-manifest.schema.json`.
- **Tests:** `tests/e2e/test_retrieval_baseline_live.py`, `test_migration_0011_live.py`, `test_migration_0012_live.py`,
  `test_mcp_read_live.py`, `test_ingest_live.py`; `tests/plan_l/test_migration_0011.py`, `test_mcp_read_corpus.py`,
  `test_retrieval_baseline.py`, `test_corpus_files.py` (`AS_OF`, `RETURNABLE_AT_AS_OF`);
  `tests/plan_m/test_migration_0012.py`; `tests/plan_e/test_transitions_table.py` (`REVISIONS`);
  `tests/plan_b/live/test_ollama_bridge.py`, `tests/plan_b/test_model_pins.py`.
- **Env vars and settings:** `OPS_LIVE`, `PROFILE` (`dev|test|demo`), `OPS_PG_DB` (`ops`, live `ops_test`),
  `OPS_ASSET_SIM_URL`, `OPS_MCP_READ_URL`, `MCP_READ_RESOURCE_URL`, `OPS_WORKLOAD_CLIENT_ID`, `MODEL_MODE`,
  `OPS_SECRETS_DIR`; `.env`-only `OLLAMA_BASE_URL_HOST` (`http://127.0.0.1:11434`), `OLLAMA_BASE_URL_CONTAINER`
  (`http://host.docker.internal:11434`); Ollama's own `OLLAMA_HOST` (`127.0.0.1:11434`, owner-set). No `OPS_*` Ollama
  or embedding setting exists.
- **Ports** (loopback): api 8000, worker 8070, sweeper 8071, mcp-read 8081, mcp-write 8082, incident-sim 8090,
  asset-sim 8091, Postgres 15432, Keycloak 18080, Ollama 11434.
- **Gates:** `uv run python scripts/check.py` (1372 passed, 205 skipped), `… --profile test` (1556 passed, 21 skipped),
  `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts` (exit 0).

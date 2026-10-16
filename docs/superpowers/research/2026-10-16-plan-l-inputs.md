# Plan L inputs: T17 (expanded corpus, governed ingestion and lexical baseline) — fact sheet

Prepared 2026-10-16 on branch `plan-l` at `00d388f` (= `plan-k`; read-only on the repository except this file; the tree
carries one unrelated uncommitted modification, `docs/superpowers/research/2026-10-16-plan-k-inputs.md`, which this
sheet neither reads for facts nor touches). Facts only, no design. Citations: `SA:<line>` = `SPEC_AMENDMENTS.md`,
`BS:<line>` = `BUILD_SPEC.md` (line numbers as of `00d388f`); the amendments win wherever the two conflict. Repository
files are cited as `path:line`. Nothing was run against a database, Keycloak or a service for this sheet: every fact
below is read from the files, and no secret, token or `.env` value was opened.

Note on line numbers: AM-00 is SA:30–66 (§20 SA:39, §25 SA:43, §12 SA:47); AM-01 SA:68–91; AM-02 SA:93–114 (roles
SA:106); AM-15 SA:327–358 (tool table SA:331–336, job table SA:340–346, read tools and vector mode SA:348, schema rule
SA:350, envelope SA:351–355); AM-16 SA:360–381 (graph router and "evidence sufficient?" SA:377); AM-20 SA:383–566
(principles SA:387–389; AM-20.1 SA:391–404, `migrator` SA:395, `mcp_read` SA:400; AM-20.2 SA:406–442, corpus row
SA:431, notes SA:436–442, seed data SA:440; AM-20.3 SA:444–490, header SA:446, `resolve_invocation` SA:459,
`asset_scope` SA:460, `search_procedures_scoped` SA:461, helpers SA:474; AM-20.4 SA:492–506; AM-20.5 SA:508–524,
table list SA:510, policy SA:512–516, sweeper SA:520, defense-in-depth SA:522, no-RLS list SA:523, R106 SA:524; AM-20.6
SA:526–530; AM-20.7 SA:532–566); AM-30 SA:568–591; AM-31 SA:593–620; AM-50 SA:638–678 (corpus SA:640–645, scenario
suite SA:647–650, model-quality table SA:652–662, statistics SA:664–669, quality gates SA:671–674, labelling load
SA:676, solo owner SA:678); AM-60 SA:680–728 (1.3.4 SA:689, 1.3 "T17 moves to M05" SA:709); AM-70 SA:730–741;
AM-80 SA:743–778 (negative probes SA:754, fixtures row SA:777). BUILD_SPEC §0 BS:11–34, §2 BS:46–89 (v1 scope BS:50,
retrieval choice BS:71), §3 BS:91–157, §5 BS:182–220, §6 BS:222–259 (document/version BS:241, chunk/embedding BS:242,
tenant keys BS:246, RLS BS:248), §7 routes BS:279–280, §9 BS:344–374 (handle BS:356–364, reconciliation BS:368, threat
tests BS:374), §10 BS:376–407 (`search_procedures` BS:386), §11 BS:409–431, §12 prompts BS:445–456, §13 freshness
BS:476, §18 BS:572, §19 BS:580–597, §20 BS:599–613, §23 manifest BS:670, §25 M06 row BS:707, §27 BS:738–753.

---

## 1. T17 verbatim, its acceptance-matrix rows, and related tasks

### 1.1 T17 (`handoff/tasks.json:725-745`)

- **id/milestone/title:** `T17`, `M05` ("MCP read and write servers and governed corpus", `tasks.json:65-76`, task_ids
  `T15`, `T47`, `T17`, `T16`, status `PLANNED`), "Expanded corpus, governed ingestion and lexical baseline".
  `status: "PLANNED"` (`:738`), `external_approval_required: false` (`:744`).
- **instructions** (`:729`, verbatim): "Author >=12 documents (300-900 words), >=6 assets, 2 tenants incl. superseded,
  conflicting and injected sources; per-section IDs/hashes; tenant UUID and alert UUID fixtures; idempotent ingestion;
  PostgreSQL full-text retrieval with access filtering."
- **depends_on** (`:730-732`): `["T09"]` only. T09 is `DONE` (Plan E, `tasks.json:479-517`).
- **requirement_ids** (`:733-737`): `R032, R033, R099`.
- **definition_of_done** (`:739-743`, verbatim):
  1. "Catalog with per-section sha256; ingestion idempotent."
  2. "Superseded/expired/revoked sections never returned."
  3. "Lexical retrieval measured on labelled dev queries with denominators."
- **review_notes:** none. T17 is the only M05 task without a `review_notes` array (`tasks.json:725-745`).
- `SESSION_STATE.md:12-14`: "Next is Plan L = T17 (the governed corpus, the earliest dependency-satisfied PLANNED task
  in `handoff/tasks.json` after T47, unblocked by T09)." `SESSION_STATE.md:1099` repeats it.
- `handoff/BUILD_BACKLOG.md:104` repeats the instructions, the requirements and "Depends on: T09".
- `tasks.json` header note (`specification` "OPS-BUILD-1.3.6", `current_milestone` "M00"): "Status vocabulary:
  PLANNED, DONE (all steps done and reviewed), DONE_PENDING_OWNER (agent steps done; an owner-only step remains, named
  in review_notes)."

### 1.2 Acceptance-matrix rows owned by T17 (`handoff/acceptance-matrix.json`)

- **R032 (:591-605)** — M05 / retrieval; "Source ingestion is versioned effective and idempotent";
  `blocking_for_v1: true`; `implementation_status: NOT_IMPLEMENTED_OR_NOT_TARGET_VERIFIED`; `evidence_status: NOT_RUN`;
  no evidence paths; expected_evidence (verbatim): "Repeat same document; change hash under same version;
  supersede/unapprove; only permitted effective version retrieves."; owners `T17` only; suggested_test
  `tests/acceptance/test_r032_source_ingestion_is_versioned_effective_and_idem.py`.
- **R033 (:606-620)** — M05 / retrieval; "Lexical baseline has labeled evidence measurements"; blocking;
  `NOT_IMPLEMENTED_OR_NOT_TARGET_VERIFIED` / `NOT_RUN`; expected_evidence: "Known questions return labeled permitted
  sections; missing source remains missing, not guessed."; owners `T17`; suggested_test
  `tests/acceptance/test_r033_lexical_baseline_has_labeled_evidence_measuremen.py`.
- **R099 (:1675-1690)** — M05 / retrieval, `source: SPEC_AMENDMENTS.md`; "Evidence corpus is large enough to measure
  retrieval"; blocking; `NOT_IMPLEMENTED_OR_NOT_TARGET_VERIFIED` / `NOT_RUN`; expected_evidence: ">=12 documents of
  300-900 words, >=6 assets, per-section hashes, tenant/alert UUID fixtures, superseded/conflicting/injected sources.";
  owners `T17`; suggested_test `tests/acceptance/test_r099_evidence_corpus_is_large_enough_to_measure_retri.py`.
- Matrix note (`acceptance-matrix.json:3`): "suggested_test paths are targets to implement"; `RECORDED_LOCALLY` means
  "the tests in evidence_paths pass in scripts/check.py and CI"; `RECORDED_LOCALLY_LIVE`: "the test passes against the
  running dev profile with OPS_LIVE=1 and is collected but skipped by scripts/check.py and CI; the evidence file records
  a run." `tests/acceptance/` does not exist; `pyproject.toml:48-51` `testpaths` lists `tests/plan_a` … `tests/plan_k`
  and `tests/e2e` (no `tests/plan_l`).

### 1.3 Rows that name the corpus or retrieval without being T17's

- **R028 (:517-531)** T16: "Read tools enforce current source and asset access"; expected "Alpha requests B22 or
  revoked procedure; no forbidden data reaches the model."; `NOT_RUN`.
- **R029 (:532)** T16: "Unexpected tools and invalid results fail closed"; `NOT_RUN`.
- **R034 (:621)** T18: "Exact vector retrieval is measured against the baseline"; expected "Record
  model/dimension/corpus and matched question retrieval results, including regressions."; `NOT_RUN`.
- **R035 (:636)** T26: "Revoked evidence does not leak from derived state"; expected "Revoke source after draft;
  caches/checkpoints/summary/events/citation viewer do not re-expose it."; `NOT_RUN`.
- **R036 (:651)** T19: "Retrieved instructions cannot grant tool authority"; expected "Inject administrator-style text
  into SOP fixture; no permission/action boundary changes."; `NOT_RUN`.
- **R038 (:681)** T20: "Evidence retrieval precedes final drafting"; `NOT_RUN`.
- **R045 (:786)** T21: "Final grant checks current authority and evidence"; expected "Revoke requester/reviewer or
  source before grant transaction; zero destination writes."; `NOT_RUN`.
- **R071 (:1181)** T03/T41/T25: "Final holdout is kept out of the tuning context"; expected "Holdout intents sealed
  (T03) and gold labels sealed (T41) with hashes recorded outside the local repo before dependent tasks; holdout usage
  logged in T25."; `NOT_RUN`.
- **R007 (:105)** T09: "Runtime-role row security isolates tenants"; `IMPLEMENTED_LOCALLY_VERIFIED`,
  `RECORDED_LOCALLY_LIVE`. **R106 (:1802)** T09: "Definer functions are hardened and tenant-isolated by explicit
  policies" (expected: "search_path fixed, PUBLIC execute revoked, GRANT EXECUTE only to named callers, owner
  app_definer is not a table owner, FORCE RLS and the AM-20.5 policy text present per table; cross-tenant access through
  functions fails."); `IMPLEMENTED_LOCALLY_VERIFIED`, `RECORDED_LOCALLY_LIVE`.
- **R104 (:1762)** T45: "Schemas, examples and fixtures match the 1.3.6 contract" (`verify_handoff.py --contracts`);
  `IMPLEMENTED_LOCALLY_VERIFIED`, `RECORDED_LOCALLY`.
- **R111 (:1897)** T23: "Development evaluation set has gold labels and calibrated graders"; expected "~60 labelled dev
  cases; deterministic graders unit-tested; groundedness rubric documented."; `NOT_RUN`.
- **R130 (:2230)** T19/T25: run manifest "records model_route, digest, prompt_version, corpus_version"; `NOT_RUN`.
- **R131 (:2247-2271)** T15/T47: expected "mcp_read can EXECUTE only resolve_invocation, asset_scope,
  search_procedures_scoped; …"; `IMPLEMENTED_LOCALLY_VERIFIED`, `RECORDED_LOCALLY_LIVE`; note (`:2268`): "Read half
  (Plan J, T15): mcp_read can EXECUTE current_time (erratum 15) and resolve_invocation and nothing else in app
  (asset_scope and search_procedures_scoped join with T16/T17, erratum 72) …".
- **R076 (M15, T37)**: release manifest includes "corpus" hashes. **R097** (T24/T27/T29/T32): 30 development cards
  as state-asserting tests.

### 1.4 Tasks that depend on T17, and neighbours (statuses from `handoff/tasks.json`)

- **T16** (`:746-771`, M05, PLANNED) depends_on `["T15", "T10", "T17"]`; "asset-sim service (trusts only the mcp-read
  workload token and forwarded tenant/asset context, applies its own tenant filter); get_asset_status,
  get_recent_alerts (absolute interval, next_cursor), search_procedures over the governed store (vector mode: mcp-read
  computes the nomic search_query embedding); fail-closed result validation." Owns R028, R029. DoD: "Cross-tenant asset
  reads denied; unexpected tools and malformed results fail closed."; "asset-sim rejects worker, api and mcp-write
  tokens." Review notes (`:767-768`, verbatim): "search_procedures reads the governed store built in T17.";
  "search_procedures vector mode: mcp-read computes the nomic search_query embedding and passes it to
  search_procedures_scoped."
- **T18** (`:772-789`, M06 "Vector retrieval", PLANNED) depends_on `["T17"]`; "nomic-embed-text with
  search_document:/search_query: prefixes (tested); record model, dimension, digest; exact search with the same
  filters; comparison report vs lexical." R034. DoD: "reports/retrieval-comparison.md with recall@k for both methods,
  denominators and CIs."; "Prefix application asserted by a test."
- **T41** (`:790-808`, M06, PLANNED, `external_approval_required: true`) depends_on `["T03", "T17"]`: "Owner, without
  AI assistance, adds evidence IDs and expected outcomes to the sealed holdout cases against the frozen T17 corpus
  version; re-seals (sha256 committed and recorded externally). Corpus changes after this require re-labelling." R071.
  DoD: "New holdout hash committed and externally recorded with the corpus version it labels."; "Holdout content still
  absent from repo and agent-readable paths."
- **T19** (`:809-839`, M07, PLANNED) depends_on `["T07", "T17", "T02", "T03", "T44"]`; writes "the run manifest
  {run_id, model_route, model_digest, prompt_version, corpus_version, retrieval_mode}". DoD 2: "Injected source cannot
  add tools or authority; invalid output -> repair -> controlled failure." Owns R036, R037, R039, R040, R041, R127,
  R130.
- **T23** (`:952-969`, M09, PLANNED) depends_on `["T17"]`: "~60 dev cases over the expanded corpus with gold labels;
  deterministic graders for schema, citations and abstention; groundedness rubric for owner labelling." R111. DoD:
  "evals/dev/ cases and labels committed; graders unit-tested."; "Rubric with worked examples and inter-trial labelling
  instructions."
- **T25** (`:995-1024`, M09, PLANNED) depends_on `["T22", "T18", "T23", "T41"]`; review note: "Reads each run's
  manifest (model route, digest, prompt and corpus versions) into the eval report".
- **T20** (PLANNED) depends_on `T19`, `T14`, `T16`; **T21** depends_on `T20`, `T11` (owns R045; instructions name
  "asset freshness and asset guard", not document versions); **T26** owns R035 ("authorized evidence viewer",
  `tasks.json:1028`).
- **T09** (`:479-517`, DONE): instructions "Implement AM-20 in code … exact grants per AM-20.2 … RLS policies per
  AM-20.5 incl. FORCE"; the Plan E review note (`:514`) ends "Deferred: the eleven definer functions without a caller
  arrive with T11/T13/T15-T17/T21/T22".
- **T45** (`:412-434`, DONE): "Apply every AM-80 row (… fixtures UUID mapping)"; Plan C note: 25 schemas, 87 examples,
  `index.json` 1.3.3, `--contracts` in CI.
- **T15** (`:666-698`, DONE) and **T47** (`:699-724`, DONE): T15's review note (`:695`) defers "search_procedures_scoped
  and the governed store -> T17/T16"; "DONE subject to the owner's decisions on errata 72 and 76". T47's Plan K note
  (`:722`) ends "R030 and R131 are met subject to the owner's decisions on errata 72, 84 and 91."
- **T03** (`:204-224`, DONE_PENDING_OWNER): the holdout seal is pending (owner step 9). **T02** DONE_PENDING_OWNER.
- Milestones: M05 `:66-76` (PLANNED); M06 "Vector retrieval" `:78-86` task_ids `T18`, `T41`. SA:709 (1.3): "T17 moves
  to M05 ahead of T16. M05 becomes \"MCP boundary and governed corpus\"." BS:707 (1.0 table, superseded by SA:43): "M06
  — Evidence pipeline | Governed ingestion, lexical baseline, exact pgvector comparison, revocation |
  Source/version/access tests; named retrieval experiment".

---

## 2. Spec passages that bind T17

### 2.1 AM-50 (SA:638–678), verbatim where it binds

- **Corpus** (SA:640–645):
  - "at least 12 authored documents of 300–900 words each, at least 6 assets, 2 tenants;"
  - "superseded/expired versions, one injected-instruction document per tenant, and one conflicting-procedure pair;"
  - "evidence IDs are per section, with per-section `sha256`;"
  - "tenant slugs map to seeded UUIDs, and alert IDs are UUIDs with revisions;"
  - "embeddings use `nomic-embed-text` with the `search_document:` and `search_query:` prefixes, with a test that they
    are applied."
- **Model-quality table** (SA:656, SA:658): "| Development set | About 60 cases with gold labels and a groundedness
  rubric (T23) |"; "| Holdout, part 2 (T41) | The owner gold-labels the sealed cases against the **frozen T17 corpus**
  (evidence IDs, expected outcome), then re-seals. |"
- Holdout custody (SA:659): "Stored **off this machine** … Only the `sha256` and case count are committed. Each seal
  hash is **also recorded outside the local repo** before the next dependent task starts".
- Conditions (SA:660): "B and C use identical model, prompt-version family, retrieval settings and `num_ctx`."
- Statistics (SA:665): "report at **case level** … with Wilson 95% CIs and denominators."
- Labelling load (SA:676): "Use deterministic graders wherever possible (citations, schema, abstention); owner labels
  only groundedness."
- AM-00 (SA:39): "**§20:** 80/40 cases with a separate reviewer: replaced by AM-50."

### 2.2 AM-80 (SA:743–778), the rows that touch the corpus

- SA:745: "The delivered `schemas/`, `schemas/examples/` and `data/handoff-fixtures/` still describe 1.0. T45 updates
  them and proves the result with `scripts/verify_handoff.py --contracts` plus new negative probes (R104)."
- Checker changes (SA:747–752) include "Reject `\r` in fixtures, schemas, examples and prompts, so hashes match across
  platforms".
- SA:777: "| `data/handoff-fixtures/` | Tenant UUID mapping; alert UUIDs + revisions; per-section hashes (expanded in
  T17) |"
- SA:770: "| New: `schemas/route.schema.json`, `schemas/run-manifest.schema.json` | … the per-run manifest `{run_id,
  model_route, model_digest, prompt_version, corpus_version, retrieval_mode}` |"
- SA:766: "| `schemas/tools/*.json` | Create input schemas for all six tools |"

### 2.3 AM-15 (SA:327–358): `search_procedures` and its scoped definer

- SA:333: "| `get_asset_status`, `get_recent_alerts` (absolute interval, `next_cursor`), `search_procedures` |
  **mcp-read** | `investigate` and `resume_input` jobs (read handles) |"
- SA:348: "Read tools are `get_asset_status`, `get_recent_alerts` and `search_procedures`. … For `search_procedures` in
  vector mode, mcp-read computes the query embedding with `nomic-embed-text` (`search_query:` prefix) and passes it to
  `search_procedures_scoped` [R6]."
- SA:350: "Every tool has an input JSON Schema in `schemas/tools/`. Arguments that supply a role, tenant, actor,
  approval or destination are rejected."
- SA:352: "`status=ok` only for a read with data, or `SUCCEEDED`;"
- AM-00 (SA:36): "**§10:** \"negotiation\": replaced by AM-30. The four tools become six (AM-15)."

### 2.4 AM-20 rows for the corpus, `search_procedures_scoped`, `asset_scope`, roles, grants and RLS

- Principle 1 (SA:387): "Every state transition, decision, grant, attempt step and event goes through a `SECURITY
  DEFINER` function." (Corpus tables are not named in it.)
- AM-20.1 (SA:395): "| `migrator` | yes (DDL and data migrations only) | Alembic; owns tables and schemas; holds
  `BYPASSRLS` so seed and backfill data migrations can write RLS tables; never used at runtime [R7-H4] |"; SA:396
  `app_definer` "**no** [login] | Owns every definer function; **owns no tables**"; SA:398 "| `worker` | yes | Workflow
  worker |"; SA:400 "| `mcp_read` | yes | mcp-read; read-path functions only |".
- AM-20.2 (SA:431, verbatim): "| `documents`, `chunks`, `embeddings` | — | ins, sel (ingestion) | — | sel | — |"
  (columns `api` | `worker` | `sweeper` | `app_definer` | `mcp_read`/`mcp_exec`/`operator`). SA:408: "Only these grants
  exist. Anything not listed is denied." SA:437: "`mcp_read`, `mcp_exec` and `operator` have **no table grants**".
  No UPDATE or DELETE on the corpus tables appears for any role.
- SA:440: "Seed data (tenants, personas' memberships, the `model_permit` row) is written by `migrator` data migrations
  under `BYPASSRLS`; no runtime role can insert it [R7-H4]."
- AM-20.3 header (SA:446): "All functions: `SECURITY DEFINER`, owner `app_definer`, `SET search_path = app, pg_temp`,
  `SET app.tenant_id = ''` as a function attribute. Each migration that creates one runs, in the same transaction,
  `REVOKE ALL ON FUNCTION … FROM PUBLIC` and then `GRANT EXECUTE … TO <exactly the callers listed below>` [R6-H2].
  Every function first resolves `tenant_id` through `run_directory` (or the handle) and sets `app.tenant_id` with
  `set_config(name, value, true)` (**transaction-local** …) before touching tenant rows, takes locks in the AM-12
  order, and raises `authority_violation` when `session_user` is not an allowed caller. Reads of the setting use
  `NULLIF(current_setting('app.tenant_id', true), '')::uuid` [R7]."
- SA:459: "| `resolve_invocation(raw_handle, client_azp)` | `mcp_read`, `mcp_exec` | … | `invocation_context` FOR SHARE
  → `run_lease` FOR SHARE | Hashes the handle inside; checks azp binding, **that the handle's server matches the
  calling role** … returns `{run_id, tenant_id, job_type, run_state, attempt_state, allowed_tools}` …"
- SA:460: "| `asset_scope(raw_handle)` | `mcp_read` | handle | as above | Returns the run's `tenant_id`, `asset_id`,
  `[start_at, end_at)` for forwarding to asset-sim | none |"
- SA:461 (verbatim): "| `search_procedures_scoped(raw_handle, query, query_embedding vector(768) NULL, asset_type,
  limit, mode)` | `mcp_read` | handle, text query, optional embedding computed by mcp-read with the `search_query:`
  prefix | as above | Lexical (`mode=lexical`) or exact vector (`mode=vector`, requires the embedding) search over
  approved, effective, tenant-permitted chunks; returns IDs, versions, section, hash, excerpt | none |"
- SA:474: "Internal helpers (`_canonicalize`, `_asset_guard`, `_allowlist`) are not granted to any role."
- AM-20.4 (SA:498–504): job types `investigate`, `resume_input`, `execute`, `recover`, `expire_proposals`,
  `sync_memberships`, `sweep_wakeups`, `deliver_outbox`; no ingestion job type is listed.
- AM-20.5 (SA:510): "Every tenant table (`memberships`, … `feedback`, `documents`, `chunks`, `embeddings`) has `ENABLE
  ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY` …"; policy (SA:513–516): "CREATE POLICY tenant_isolation ON
  <table> FOR ALL TO api, worker, sweeper, app_definer USING (tenant_id = current_setting('app.tenant_id',
  true)::uuid) WITH CHECK (…)"; SA:520: "These are the only policies besides `tenant_isolation`" (the `sweeper_all`
  pair on `memberships` and `jobs`); SA:522: "`api`, `worker` and `sweeper` set `app.tenant_id` themselves per
  transaction, so for them RLS is **defense in depth** … The threat model says so."; SA:524: "R106 asserts the policy
  text per table (`pg_policies`) and that the definer path cannot read another tenant's rows."
- AM-02 (SA:106): "`mcp_read` and `mcp_exec` (functions only), `app_definer` (NOLOGIN, owns functions, does not own
  tables)". AM-01 (SA:76): "| `mcp-read/` | Authenticated MCP server for read tools only (asset status, alerts,
  procedure search); DB role `mcp_read` |".
- AM-16 graph router (SA:377): "\"Evidence sufficient?\" is a code rule (at least one permitted status observation and
  at least one effective procedure chunk, all within freshness), never a model judgement".
- AM-20.7 item 8 (SA:563, "Graph state is IDs only"): "Interrupt payloads and graph state carry IDs and hashes
  only (R091)."
- AM-30 versions (SA:575, SA:584): "pgvector-python | 0.5.0" observed 2026-10-06 ("exact pins live in `uv.lock`").
- AM-70 (SA:730–741) lists seven reference defects; none concerns retrieval, corpus or ingestion.

### 2.5 BUILD_SPEC §11 (BS:409–431), verbatim

- BS:411: "Begin with authored UTF-8 Markdown/JSON sources only. No user uploads, arbitrary web crawling, PDF ingestion,
  employer SOPs or external private data in v1. Use allowlisted directories, safe path handling, file-size limits,
  content hashes and idempotent ingestion keyed by document/version/hash."
- BS:413: "Each source specifies document ID, tenant or explicit shared policy, version, approval/effective status,
  asset family, sections, supersedes relation and synthetic label. Conflicting content under the same
  document/version/hash identity is rejected. Validate effective intervals; an expired/superseded version is not
  silently treated as current."
- BS:415: "Chunk on headings/sections. Initial proposal: 300–600 tokens per chunk, minimal overlap only where context
  requires it, stable source offsets and evidence IDs. The exact tokenizer/window choice must be recorded and
  evaluated. Do not make a generated summary the authoritative source. Use PostgreSQL full-text retrieval as baseline;
  then select and record an embedding model and dimension and implement exact pgvector search. pgvector provides vector
  storage/search inside PostgreSQL; it does not implement the application's authorization policy. [S07]"
- BS:417: "Filter before results enter the model. Apply approved/effective/tenant/resource-access constraints to
  lexical and vector retrieval. Store retrieval settings and score interpretation; scores from different methods are
  not interchangeable probabilities. Start `top_k=5`, allow up to 8 source references under the context budget, and
  tune on development evidence only. If no appropriate source exists or procedures conflict materially, ask/abstain
  instead of inventing a merged policy."
- BS:419: "The model receives a bounded evidence bundle: fixed asset/interval, status observation, alert records or
  aggregate plus truncation notice, permitted excerpts, source IDs/versions/hashes and retrieval timestamp. It cannot
  read the whole corpus or database. Keep prompts/instructions separate from source text, but do not claim that
  formatting alone prevents injection."
- BS:423: "Membership/access changes invalidate relevant caches and future projections. Every resumed workflow checks
  access again before loading evidence into a model. Every citation open checks current visibility. Do not re-expose
  revoked text from old checkpoints, generated summaries, or event payloads. …"
- BS:425: "The final execution gate rechecks document versions and proposal freshness. A materially changed or revoked
  source invalidates pending approval. …"
- BS:427: "Use caches only after correctness tests; default to no shared answer cache. A later key includes tenant,
  permission version, corpus version, model/prompt version and query parameters. …"
- BS:431: "`data/handoff-fixtures/` contains small authored alpha/beta sources and a fixed synthetic alert snapshot.
  These are development fixtures and contract examples, not a completed corpus or benchmark. Expand to at least 12
  reviewed source documents and the evaluation scenarios described below. Keep holdout variants separate from
  development tuning."

### 2.6 Other BUILD_SPEC sections on documents, access, prompt injection and measurement

- §2 (BS:50): v1 includes "governed lexical retrieval plus a measured pgvector comparison"; (BS:71): "| Retrieval |
  PostgreSQL full-text search baseline, then exact pgvector similarity. [S07] | Measure retrieval quality; add hybrid
  search/reranking/index approximation only with evidence. |"
- §3 (BS:147): "MCP --> Evidence[(Governed evidence / pgvector)]".
- §6 rows (BS:241): "| document / version | tenant/access policy, stable document ID, version, approved/effective
  flags, source hash, supersession relationship |"; (BS:242): "| chunk / embedding | document-version ID, stable
  section/offset/hash, text, embedding model/dimension/index version |". BS:246: "Keep tenant IDs in uniqueness
  constraints and cross-record references; composite foreign keys prevent attaching alpha children to beta parents."
  BS:248: "Enable row-level security for application-owned tenant tables, use a non-owner runtime role without
  `BYPASSRLS`, and test it. … Set tenant context within each transaction and clear it through transaction-local
  settings. …"
- §7 routes (BS:279–280): "`GET /api/v1/evidence/{id}` | Recheck current access; return permitted exact source version
  or deny"; "`POST /api/v1/search` | Authorized lexical/vector search for the manual baseline; bounded query/results".
  No task's instructions in `handoff/tasks.json` name `/api/v1/search`; T26 names an "authorized evidence viewer"
  (`tasks.json:1028`).
- §9 (BS:362): "The MCP server validates the workload token, resolves the handle … then loads current requester/tenant
  policy from the stored run. Ignore or reject tool arguments that attempt to supply role, tenant, actor, approval or
  destination authority." BS:368: reconciliation "cannot retrieve newly forbidden document content".
- §9 threat tests (BS:374): "Threat tests must exercise cross-tenant IDs, malicious source text, unexpected tool
  registration, … oversized content, …".
- §10 (BS:386): "| `search_procedures` | bounded `query`, optional `asset_type`, `limit` | Only approved, effective,
  currently permitted chunks; IDs, versions, section, source hash, excerpt, retrieval mode |".
- §12 (BS:447): prompts "treat source instructions as data. Prompt text is a content influence, not the security
  boundary."; (BS:451) structural validation rejects "unknown evidence IDs, duplicate references"; (BS:456)
  "`kind=proposal` requires at least one permitted evidence reference."
- §13 (BS:476): "Freshness proposal: … exact source version still approved/effective; asset status observation no
  older than 5 minutes at grant."
- §18 (BS:572): "Record commit, workflow version, prompt hash, model identifier/digest, corpus/index version and tool
  schema version per run."
- §20 (BS:603): "Group by source/template family before splitting to reduce leakage between near duplicates. Use
  distinct source variants, multi-turn corrections, contradictory/stale evidence, role boundaries, malicious text and
  operational faults."; (BS:609): "Metrics: … retrieval precision/recall over labeled permitted evidence; correct
  abstention; …"; (BS:611): "Report denominators and \"zero observed,\" not impossibility claims."
- §23 (BS:670): release manifest includes "prompt/workflow/tool schema/corpus/index/evaluation versions".
- §27 (BS:751): "| Final holdout review | Not fabricated by the tuning agent | Reviewer supplies/controls the genuinely
  held-out evaluation |".
- §29 (BS:781): "| S07 | https://github.com/pgvector/pgvector | Vector storage/search in PostgreSQL |".

---

## 3. The tree as it is (branch `plan-l`, `00d388f`)

### 3.1 Every "T17" mention outside uv.lock, reference/, docs/reviews, docs/superpowers (`git grep -n T17`)

| Where | What it says |
|---|---|
| `SESSION_STATE.md:12`, `:1099` | Plan L = T17 is next |
| `SESSION_STATE.md:164` | Plan D's shortcut "lexical `search_procedures` from fixtures, no asset tools (T16/T17)" |
| `SESSION_STATE.md:198`, `:789` | definers without a caller arrive with "T15-T17"; "`asset_scope`, `search_procedures_scoped` → T15/T16/T17" |
| `SESSION_STATE.md:563`, `:603`, `:716` | erratum 72 and its pattern: "`search_procedures_scoped` with T17/T16" |
| `SESSION_STATE.md:771` | walking-skeleton debt: fixture-backed lexical `search_procedures` "→ T17" |
| `SESSION_STATE.md:799` | Plan E debt: "`documents`/`chunks`/`embeddings` … absent … → … T17" |
| `SESSION_STATE.md:947`, `:950` | Plan J debt: governed store and the mode translation "→ T17/T16"; arguments and fallback `corpus_version` "→ T16/T17" |
| `SPEC_AMENDMENTS.md:658`, `:709`, `:777` | frozen T17 corpus; T17 moves to M05; fixtures "(expanded in T17)" |
| `STATUS.md:254` | "the governed store -> T17/T16" |
| `core/src/ops_core/privileges.py:8` | "the owners of later tables (… documents/chunks/embeddings → T17) add their rows" |
| `core/src/ops_core/routing.py:362` | "TODO(T16): mcp-read, the caller of `search_procedures_scoped` (T17), translates `vector_exact` to `mode=vector`." |
| `data/handoff-fixtures/README.md:17` | examples cite the whole-file hash "— TODO(T17)" |
| `docs/ARCHITECTURE.md:260` | "the search itself still reads the fixture corpus (T17 brings the governed store, T16 the asset tools)" |
| `docs/runbooks/mcp-read.md:80` | "Not here yet: … the governed store and vector search (T17)" |
| `handoff/BUILD_BACKLOG.md:53`, `:98`, `:104-106`, `:111-112`, `:116`, `:141` | task copies |
| `handoff/acceptance-matrix.json:602`, `:617`, `:1686`, `:2268` | R032/R033/R099 owners; R131 note |
| `handoff/tasks.json:72`, `:514`, `:695`, `:726`, `:754`, `:767`, `:777`, `:793`, `:796`, `:815`, `:957` | the graph |
| `mcp-read/README.md:10`, `:22` | "`asset_scope` and `search_procedures_scoped` arrive with T16 and T17"; "lexical, fixture-backed until T17" |
| `mcp-read/src/ops_mcp_read/procedures.py:1` | "debt → T17: the governed store, `search_procedures_scoped` and `vector_exact`" |
| `mcp-read/src/ops_mcp_read/server.py:200` | `UNSUPPORTED_MODE` "vector_exact arrives with T17" |
| `scripts/build_schemas.py:320`, `:912-913` | evidence row "per-section hashes are consumed from T17"; `TODO(T17)` on `EVIDENCE_SHA` |
| `tests/e2e/test_mcp_read_t15_live.py:271` | R131 docstring: the two read functions "join with their owners, T16 and T17 (erratum 72)" |
| `tests/e2e/test_mcp_write_t47_live.py:190` | the two read functions "do not exist yet (T16/T17)" |
| `tests/plan_c/test_schema_conformance.py:47` | `schemas/evidence.schema.json` skipped: "retrieval rows are produced by mcp-read (T17)" |

`docs/diagrams/png/06-results-feedback-and-observability.png` also matches (binary).

### 3.2 Today's `search_procedures` (mcp-read)

- `mcp-read/src/ops_mcp_read/procedures.py` (111 lines), module docstring `:1-10`: "The corpus is built per tenant from
  `data/handoff-fixtures/catalog.json`: only that tenant's documents … and only `approved` versions, so a superseded
  or draft document is never cited. Sections are sliced exactly as scripts/gen_fixture_meta.py slices them and carry
  the per-section hash from meta.json, so an `evidence_ref` the proposal cites (`<DOCUMENT_ID>:v<version>:<section>`)
  names bytes the destination reviewer can re-hash. Ranking is term overlap with a deterministic tie-break: the same
  query must cite the same evidence on a retry (BUILD_SPEC §6: retries keep the same proposal)."
  - `WORD = re.compile(r"[a-z0-9]+")` (`:20`), `EXCERPT_CHARS = 500` (`:21`), `tokens` (`:24-26`, lower-cased term
    set), `section_bodies` (`:29-43`, body of every `## <name>` section), `Section` (`:46-56`: `evidence_id,
    document_id, version, section, content_sha256, text, effective_from`), `Hit` (`:59-64`), `Corpus` (`:67-105`).
  - `Corpus.load` (`:75-97`): filter `doc["tenant"] != tenant_slug or doc["approval_status"] != "approved"` (`:82`);
    `evidence_id=f"{doc['document_id']}:v{doc['version']}:{name}"` (`:88`); hash from `meta.json` (`:79`, `:92`);
    `corpus_version=catalog["fixture_version"]` (`:97`). No effective-interval or `as_of` check: `effective_from` is
    copied, not compared.
  - `Corpus.search` (`:99-105`): score = size of the query/section term-set intersection, zero scores dropped, sort
    `(-score, evidence_id)`, first `limit`.
  - `load_corpora` (`:108-111`): one corpus per tenant UUID from `meta.json["tenants"]`.
- `mcp-read/src/ops_mcp_read/server.py` (303 lines):
  - `search_response` (`:83-106`): a tenant without a corpus gets `results: []` and the first corpus's version or
    `"none"` (`:87-90`); each result carries `evidence_id, document_id, version, section, content_sha256, excerpt
    (text[:500]), effective_from, retrieved_at` (`:91-103`); `retrieval_mode: "lexical"` (`:105`).
  - tool `search_procedures(query: str 1..500, limit: int 1..8, mode: Literal["lexical", "vector_exact"])`
    (`:181-203`): no `asset_type` parameter; handle from header `x-ops-invocation` (`:189`);
    `persistence.resolve_invocation(conn, handle=…, azp=token.client_id, tool=ToolName.SEARCH_PROCEDURES)` in its own
    unit (`:193-196`); `mode != "lexical"` → `UNSUPPORTED_MODE` after resolution (`:199-200`); the search runs in
    memory, outside the database unit (`:201-203`).
  - `strict_tool` (`:152-166`): argument model `extra="forbid", strict=True`.
  - lifespan (`:219-238`): connects as `Role.MCP_READ`, `assert_clock_profile`, `assert_function_text(conn,
    *HANDLE_BINDING)`.
  - `production_app` (`:279-286`): `corpora=procedures.load_corpora(settings.fixtures_dir())` at start (`:284`).
- `core/src/ops_core/settings.py:449-450`: `fixtures_dir()` = env `OPS_FIXTURES_DIR`, default `data/handoff-fixtures`.
- Docs: `mcp-read/README.md:17-23` ("One tool, `search_procedures` (lexical, fixture-backed until T17)");
  `docs/ARCHITECTURE.md:63`: "| `mcp-read` | … DB role `mcp_read` | **no tables**; `EXECUTE` on `resolve_invocation`,
  `asset_scope`, `search_procedures_scoped` | PostgreSQL (functions), asset-sim | any write-path function; incident-sim
  |"; `:61` gives the `worker` "corpus tables (ingestion)"; `:174` mcp-read downstream "governed corpus (through
  functions)"; `:175` mcp-write "Cannot | … see corpus text".

### 3.3 The worker as the caller, and where the results go

- `worker/src/ops_worker/handlers.py`: `QUERY_CHARS = 500` (`:39`); in RETRIEVING the worker mints a read handle
  (`:111-118`) and calls `search_procedures` with `{"query": text[:QUERY_CHARS], "limit": 3, "mode": "lexical"}`
  where `text` is the user's message (`:105-109`, `:123-130`); `McpCallFailed`/`ValueError` → FAILED "retrieval
  failed" (`:132-135`); no results → INSUFFICIENT_EVIDENCE "no procedure section matched" (`:137-139`);
  `corpus_version` is read from the result (`:146`).
- `worker/src/ops_worker/proposals.py:35-54` (`evidence_from_search`): status must be `ok`, rows must carry
  `evidence_id, document_id, version, section, content_sha256, excerpt`; `:89` source snapshots carry
  `evidence_id, content_sha256, version`; `:106` `retrieval_mode="lexical"`.
- `core/src/ops_core/routing.py:350-370` (`RunManifest`): `corpus_version` 1..100 chars (`:359`),
  `retrieval_mode: Literal["lexical", "vector_exact"]` (`:363`), with the `TODO(T16)` translation note (`:360-362`).
- `core/src/ops_core/jobs.py`: `Tool.SEARCH_PROCEDURES = "search_procedures"` (`:24`); `JobType` has eight members
  (`:37-47`); `_READ` = the three read tools (`:68`).

### 3.4 The fixtures (`data/`)

- `data/handoff-fixtures/` holds `README.md`, eight Markdown documents, `catalog.json`, `meta.json`,
  `observations.json` (`git ls-files data`). Word counts (`wc -w`): 31, 34, 31, 72, 56, 33, 39, 32; none reaches 300.
  Each starts with "Synthetic development fixture. Not an equipment-control instruction."
- `catalog.json` (120 lines): `fixture_version: "handoff-1"` (`:2`), `as_of: "2026-10-06T12:00:00Z"` (`:3`), eight
  documents with fields `document_id, tenant (slug), version (string), approval_status, effective_from, supersedes,
  path, content_sha256 (whole file), sections, classification ("synthetic")`. Statuses: `ALPHA-INCIDENT` v1
  `superseded` (`:9`), v2 `approved` with `supersedes: "1"` (`:23-25`); `ALPHA-DRAFT` `draft` (`:67`); all others
  `approved`. `effective_from` is `2026-09-01T00:00:00Z` (v1) or `2026-10-01T00:00:00Z`. No `effective_to`/expiry,
  asset family, access policy beyond tenant, revoked status, conflict relation or injection label field exists.
- `README.md` (17 lines): `:3` "Load the catalog with a tenant-aware ingestion adapter in M06. … They are not a
  completed retrieval corpus, safety procedure, real operating record or held-out dataset."; `:5` "`ALPHA-INCIDENT` v1
  is superseded; v2 is current at the frozen example clock. `ALPHA-DRAFT` is unapproved. An alpha identity must not
  see beta evidence."; `:7` "For adversarial scenarios, create isolated mutated copies via the harness. Treat injected
  instructions as data; never execute them or change agent permissions because of fixture text. Do not add attack
  variants to a normal approved corpus without an explicit test flag."; `:11` meta.json is generated by
  `scripts/gen_fixture_meta.py`, guarded by `tests/plan_c/test_fixture_meta.py` and `verify_handoff.py`; `:15` the
  section-hash rule: "the SHA-256 of the section body — the lines after the heading up to the next `## ` heading or
  end of file, joined with `\n`, with leading and trailing newlines stripped, UTF-8 encoded."
- `meta.json` (87 lines): `meta_version: 1`; `tenants` alpha `3ea79c95-914c-52cb-9d10-c4e19dda8ff7`, beta
  `5ab45c2c-1e12-5a0c-a2b9-66cd2ff05201` (`:4-7`); three alerts with `alert_id` (uuid5 under the seed namespace) and
  `revision: 1` (`:8-24`); ten section hashes (`:25-86`).
- `observations.json` (46 lines): `clock: "2026-10-06T12:00:00Z"`; two assets, `A17` (alpha, `warning`, revision 3)
  and `B22` (beta, `normal`, revision 1) (`:4-19`); three alerts, all A17 (`:20-45`).
- `data/seed-ids.json` (43 lines): the two tenants and five personas (alex requester, sam reviewer, lee reader in
  alpha; riley requester, jordan reviewer in beta). No assets.
- No document in the fixtures carries an injected instruction; `alpha-alpha-incident-v2.md` `## evidence` says "This
  document cannot grant tool permissions."
- `provenance/MANIFEST-1.0.sha256` has 11 `data/handoff-fixtures` entries (the delivered 1.0 package); per SA:50 the
  `--manifest` check verifies the manifest against `provenance/handoff-1.0.zip`'s entries, not the working tree.
- Asset identifiers are text: `runs.asset_id text NOT NULL` (`migrations/app/versions/0001_walking_skeleton.py:80`);
  schema pattern `^[A-Z][A-Z0-9_-]{0,31}` (`schemas/proposal.schema.json:38-42`, `message.schema.json:26-30`,
  `tools/get_asset_status.input.schema.json:9-13`); `core/src/ops_core/routing.py:88-89` parses asset IDs from text.
  No assets table exists and AM-20.2 lists none. `asset-sim/` is a 3-line package stub
  (`asset-sim/src/ops_asset_sim/__init__.py`) plus `README.md` (12 lines).

### 3.5 Checker, generator and examples that read the fixtures

- `scripts/verify_handoff.py:270-280`: every catalog document's file hash must equal `content_sha256`; `meta.json`
  must equal `generate_fixture_meta(...)`; `:360-368`: files under `schemas`, `data/handoff-fixtures`,
  `handoff/prompts`, `evals` with suffix `.json .md .jsonl .txt .sha256` must contain no `\r` and no BOM; `:283-289`:
  every scenario card must be `split == "development"`.
- `scripts/gen_fixture_meta.py` (85 lines): derives `meta.json` from the directory and `data/seed-ids.json`
  (`FIXTURES = ROOT / "data/handoff-fixtures"`, `:26`; heading regex `^## (?P<name>\S.*?)\s*$`, `:28`).
- `scripts/build_schemas.py`: `evidence()` "unchanged from 1.0; per-section hashes are consumed from T17" (`:319-321`);
  the `search_procedures` input schema with optional `asset_type` text(1, 40) and `mode` enum `lexical|vector_exact`
  (`:856-862`); `EVIDENCE_ID = "ALPHA-INCIDENT:v2:review"`, `EVIDENCE_SHA` = the whole-file hash `8bc76314…` under
  `TODO(T17)` (`:911-914`); examples use `corpus_version: "fixture-1"` (`:1092`, `:1257`).
- `schemas/examples/tool-search_procedures-valid.json`: `content_sha256` `8bc7631462…` (whole file), `corpus_version`
  `"fixture-1"`; the catalog says `handoff-1` and the live worker test asserts `"handoff-1"`
  (`tests/e2e/test_worker_live.py:49`).
- Tests that read the fixture corpus or assert its ranking: `tests/plan_d/test_mcp_read.py` (`:20`, `:38`, `:49`, `:58`,
  `:64`, `:69`, `:81`, `:112`, `:118`), `tests/plan_j/test_mcp_read_http.py`, `tests/plan_j/test_mcp_read_startup.py`,
  `tests/plan_d/test_worker.py`, `tests/plan_h/test_worker_units.py`, `tests/plan_c/test_contracts.py`,
  `tests/plan_a/test_verify_handoff.py`; live: `tests/e2e/test_mcp_read_live.py:62`,
  `test_mcp_read_process_live.py:120`, `test_mcp_read_t15_live.py:156` (each asserts the first result is
  `ALPHA-INCIDENT:v2:review`), `test_mcp_write_live.py:53-56`, `test_worker_live.py:38-49`, `:164`.

### 3.6 Schemas touching documents, sections, assets, tenants and alerts

- `schemas/tools/search_procedures.input.schema.json`: `additionalProperties: false`; `query` 1..500, `asset_type`
  1..40 (optional), `limit` 1..8, `mode` enum `["lexical", "vector_exact"]`; required `query, limit, mode`.
- `schemas/tool-result.schema.json:289-386` (`search_procedures`, `status=ok`): `results` 0..8 items, each
  `additionalProperties: false` with required `evidence_id` (1..160), `document_id` (1..100), `version` (1..40),
  `section` (1..120), `content_sha256` (`^[a-f0-9]{64}`), `excerpt` (1..8000), `effective_from`, `retrieved_at`
  (date-time); `retrieval_mode` enum `lexical|vector_exact`; `corpus_version` 1..100. No score field and no
  per-result mode. `get_recent_alerts` items carry `alert_id` and `revision` (`:224`, `:248`).
- `schemas/evidence.schema.json` (60 lines): the same eight-field row; skipped by the conformance test
  (`tests/plan_c/test_schema_conformance.py:47`).
- `schemas/run-manifest.schema.json:36-54`: `corpus_version` 1..100, `retrieval_mode` enum `lexical|vector_exact`.
- `schemas/proposal.schema.json:63-110`: `evidence_refs` 1..8 unique strings ≤160; `source_snapshots` items
  `{evidence_id, content_sha256, version}`. `core/src/ops_core/contracts.py:82` `EvidenceRef` 1..160 chars, NFC;
  `:396-405` snapshots sorted by `evidence_id` and equal to `evidence_refs`.

### 3.7 Database revisions 0001–0010 as they bear on the corpus

- No revision creates `documents`, `chunks`, `embeddings`, a `tsvector` column, a text-search configuration,
  `asset_scope` or `search_procedures_scoped` (`grep` of `migrations/app/versions/*.py` for document/chunk/embedding/
  tsvector/vector/EXTENSION finds only `p_document` in the write-path functions). No revision runs `CREATE EXTENSION`.
- `deploy/dev/postgres/init/01-init.sql:1-4`: "Runs once, on first start of the pg-data volume, as the superuser
  `ops` in database `ops`. CREATE EXTENSION IF NOT EXISTS vector; … CREATE DATABASE incident;". `compose.yaml:9`:
  `image: pgvector/pgvector:pg17@sha256:ac08538c…`.
- The live suite's databases: `tests/e2e/conftest.py:3-6` "Every live test runs against two per-session databases,
  `ops_test` and `incident_test`, dropped and recreated here and migrated under the test profile"; `:59-68`
  `recreate_databases` issues `DROP DATABASE IF EXISTS … WITH (FORCE)` and `CREATE DATABASE {} OWNER {}` from the
  `postgres` maintenance database, with no extension step; `:71-76` `migrate(Profile.TEST)`.
- `0001_walking_skeleton.py`: `CREATE SCHEMA app` (`:33`); `app.tenants (tenant_id uuid PK, name text UNIQUE)`
  (`:35-38`); seeds the two tenants and five memberships from `data/seed-ids.json` (`:216-237`), written by the
  migration connection (the superuser, below).
- `0002_roles_grants_rls.py`: frozen `TABLES` (`:32-52`), `GRANTS_0002` (`:59-116`), `RLS` (`:118-132`); ownership
  to `migrator` (`:345-382`); `upgrade` renders `schema_usage_statements`, `grant_statements`, `rls_statements` and
  `current_time` grants (`:402-419`). Docstring `:8-9`: "Runs as the Compose superuser (Plan E ruling 3):
  scripts/skeleton.py ensure_roles has created every role, so this revision only alters, transfers and grants."
- `0003_run_path_functions.py:25-26`: `HEADER = "LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp SET
  app.tenant_id = ''"`, `HELPER_HEADER = "LANGUAGE plpgsql SET search_path = app, pg_temp"`; error classes OC001–OC006
  (`:11-12`).
- `0004_write_path_functions.py:29-31` `HANDLE_COLUMNS` = "run_id uuid, job_id uuid, job_type text, tenant_id uuid,
  conversation_id uuid, run_state text, attempt_state text"; `:238-251` `resolve_invocation(p_raw_handle text,
  p_client_azp text)`: `_authority('resolve_invocation', ARRAY['mcp_read', 'mcp_exec'])`, server `'read'` when
  `session_user` is `mcp_read`.
- `0007_leases_fences.py:122-171` `_resolve_handle(text, text, text)`: handle hash lookup, `run_lease FOR SHARE`,
  fence/lease/expiry/revocation/azp checks, `_tenant_of_run`, server from job type, the run row, the latest attempt;
  `:74-84` `JOB_TYPES_0007` (eight types) and `jobs_type_check` (`:96`). `0009_handle_binding.py:42-49` binds the job
  to its run and `done_at IS NULL`. Neither returns `asset_id`, `start_at`/`end_at` or an asset type.
- `0002:138-193` `TRANSITION_ROWS_0002` includes `APPROVED → BLOCKED_REVIEW` by `grant_execution` with reason
  `stale_evidence` (`:141-146`); `0007:176-180` keeps `TODO(T21): asset freshness … and the asset guard` in
  `grant_execution`; no definer reads document versions.
- Head is `0010_write_path`; the dev `ops` database is at `0010_write_path` (`SESSION_STATE.md:1056-1058`).

### 3.8 Roles, grants and RLS as code (`core/src/ops_core/privileges.py`, 303 lines)

- `RUNTIME_ROLES` (`:31`), `DEFINER_ROLE = "app_definer"` (`:32`), `OWNER_ROLE = "migrator"` (`:33`), `POLICY_ROLES =
  ("api", "worker", "sweeper", DEFINER_ROLE)` (`:38`).
- `GRANTS` (`:71-141`): no `documents`, `chunks` or `embeddings` row. `RLS_TABLES` (`:144-159`, fourteen tables, no
  corpus table); `SWEEPER_ALL` (`:160`); `NO_RLS` (`:164-176`).
- `TENANT_EXPR = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"` (`:181`), `POLICY_QUAL` (`:182`, the
  `pg_policies.qual` text R106 compares).
- `DEFINER_FUNCTIONS` (`:185-204`): `resolve_invocation` callers `("mcp_read", "mcp_exec")` (`:195`); no
  `asset_scope` or `search_procedures_scoped` entry. `HELPER_FUNCTIONS` (`:206-216`).
- `rls_statements` (`:261-277`): ENABLE + FORCE, `tenant_isolation FOR ALL TO <POLICY_ROLES>`, `sweeper_all` for
  `SWEEPER_ALL`. `function_grant_statements` (`:280-303`): REVOKE FROM PUBLIC then GRANT EXECUTE to the named callers.
- Guards: `tests/plan_e/test_transitions_table.py:61-81` "the newest revision of every cell equals the live matrix"
  (reads each listed revision's `GRANTS_*` and `FUNCTIONS`); `:86-98` `REVISIONS` is a named tuple ending
  `"0010_write_path", "tc_0001_test_clock"` and "a renamed or deleted revision must fail loudly". Other matrix tests:
  `tests/plan_e/test_privileges.py`, `tests/plan_f/test_privileges_f.py`, `tests/e2e/test_roles_live.py`,
  `test_definers_run_path_live.py`, per-revision `tests/plan_{g,h,i,k}/test_migration_00xx.py`.
- R131 live ACL tests: `tests/e2e/test_mcp_read_t15_live.py:266-285` asserts `mcp_read`'s EXECUTE set in schema `app`
  equals `{"current_time", "resolve_invocation"}` (`:276`); `tests/e2e/test_mcp_write_t47_live.py:186-200` asserts
  `mcp_exec`'s equals `MCP_EXEC_FUNCTIONS` and that every other definer and helper exists.
- Roles at bootstrap: `scripts/skeleton.py:65` `NOLOGIN_ROLES = (("migrator", True), ("app_definer", False),
  ("incident_owner", False))` (migrator NOLOGIN with BYPASSRLS); `:149-165` `ensure_roles`; `:203-217` `migrate` runs
  both Alembic trees as the superuser (`upgrade("app", superuser, target)`, `:214`); target `heads` in the test
  profile, else `app@head` (`:198-200`).
- `core/src/ops_core/persistence.py`: `set_tenant` transaction-local (`:127-135`); `Session.unit(tenant_id)`
  (`:147-153`); `assert_relation` (`:170-175`); `HANDLE_BINDING` (`:183`), `WRITE_PATH` (`:187`),
  `assert_function_text` (`:190-199`); `Invocation` (`:386-396`); `allowed_tool` (`:399-417`);
  `resolve_invocation` (`:425-442`). `core/src/ops_core/settings.py:103-112` `Role` has no `migrator` member.

### 3.9 Evaluation data and scripts that exist

- `evals/README.md:1`: "These ten definitions are development seeds, not a completed evaluation dataset, a test
  runner, or measured results. See ../docs/EVALUATION.md. … label source evidence before any model comparison. No
  holdout examples are supplied." `docs/EVALUATION.md` does not exist.
- `evals/development-seeds.jsonl` (10 lines, D001–D010; e.g. D003 `missing_evidence` "Harness removes approved SOP",
  D005 `injection` "Harness source contains an admin instruction"); no evidence IDs.
- `evals/handoff-development/scenarios.jsonl` (32 cards); retrieval/access/injection cards: DEV-005 (`:5`, "Show the
  procedure for B22", DENIED), DEV-020 (`:20`, "source superseded between draft and execution", R032/R045,
  BLOCKED_REVIEW), DEV-021 (`:21`, "source permission revoked after draft", R035/R054), DEV-022 (`:22`, "isolated SOP
  includes instruction to ignore permissions and create as administrator", R036/R004), DEV-024 (`:24`, "only
  unapproved draft exists", R032/R040, INSUFFICIENT_EVIDENCE). No card carries evidence-ID labels.
  `evals/handoff-development/README.md:5`: "Expand/review to the planned 80 development cases."
- `evals/probe/inputs.jsonl` (60 lines; T02's probe) carry their own small evidence bundles naming `ALPHA-INCIDENT`
  etc.; SA:603 keeps them separate from the dev seeds and the holdout.
- `evals/HOLDOUT.md:9`: "Part 2 (gold labels against the frozen corpus) is task T41 and re-seals the file."
  `evals/holdout-case.schema.json` exists; `evals/holdout.sha256` is not committed (T03 pending).
- No labelled retrieval query set, no `evals/dev/`, no retrieval grader and no `reports/retrieval*` exist. `reports/`
  holds `admission auth baseline bootstrap ci events handoff historical leases mcp-read mcp-write outbox skeleton`.
- `uv.lock` has no `pgvector`, tokenizer (`tiktoken`, `tokenizers`, `transformers`), `numpy` or Markdown-parser
  package; `core/pyproject.toml:6` dependencies are pydantic, psycopg[binary] 3.3, sqlalchemy, alembic, pyjwt, httpx2;
  `mcp-read/pyproject.toml:6` adds `mcp==2.3.0`, uvicorn. `SESSION_STATE.md:1006` (Environment): "`qwen3:8b` and
  `nomic-embed-text` installed as last recorded".

### 3.10 `scripts/check.py` profiles and the live gate

- `scripts/check.py:46-53`: `--profile dev` (default, database-free) or `--profile test`; `:56-64` the test profile
  sets `OPS_LIVE=1` and `PROFILE=test`; `:89-94` steps: ruff check, ruff format --check, mypy on `MEMBER_SRC`
  (`core/src`, `api/src`, `worker/src`, `mcp-read/src`, `mcp-write/src`, `asset-sim/src`, `incident-sim/src`,
  `sweeper/src`, `:28-37`), pytest -q.
- `tests/e2e/conftest.py:35-38`: live tests skip unless `OPS_LIVE=1`; `:41-51` sets `OPS_PG_DB=ops_test`,
  `OPS_INCIDENT_PG_DB=incident_test`, `PROFILE=test`; `app_conn` is the superuser on `ops_test` (`:80-81`);
  `role_conn` opens a connection as a given `Role` (`:91-95`).
- Last recorded gates (Plan K, after its fix wave, `SESSION_STATE.md:657-659`): `check.py` 1161 passed / 182 skipped;
  `check.py --profile test` 1322 passed / 21 skipped; `verify_handoff.py` exit 0.

### 3.11 The reference (`reference/`) on corpus and retrieval

- `reference/src/operations_copilot/synthetic.py:16-30`: SQLite tables `assets(id, body)`, `documents(id, body)`;
  `seed` (`:37-48`) writes two documents `SOP-014` (alpha) and `SOP-022` (beta), version 1, section `4.2`, status
  `approved`; `procedures(team)` (`:60-65`) filters by team and `status == "approved"` with the comment "Reference
  corpus is tiny. PostgreSQL filtering/ranking is a later milestone."; `fingerprint` (`:77-78`).
- `reference/src/operations_copilot/service.py:94-99`: evidence refs `f'{d["document_id"]}:v{d["version"]}:{d["section"]}'`;
  `:173-174` an evidence-hash change after review is a conflict.
- `reference/integrations/mcp_tools.py:30-35`: `search_procedures(query, ctx)` returns the team's documents with
  `'retrieval_mode':'small-fixture-filter-not-vector-search'`.
- AM-70 (SA:730–741) names no retrieval defect. `reference/TRACEABILITY.md:49`:
  `test_control.py::test_missing_documents_abstains` → "replace-by | tests/acceptance R114 evidence-sufficient rule |
  T20".

---

## 4. Prior rulings, debt lines and proposed errata that touch the corpus, `search_procedures` and ingestion

Errata (proposed; `SESSION_STATE.md`; the owner decides, the spec stays authoritative until then; "Open owner inputs"
`:1062-1063` lists 35-92 as undecided, `:1068` the nine of Plan C, and `:9-10` names "the proposed errata of Plans C, E,
F, G, H, I, J and K"):

- **3** (`:144`): "AM-20.3 `search_procedures_scoped`: `mode=vector` is the SQL argument value; the externally visible
  `retrieval_mode` is `vector_exact`, and mcp-read translates between them."
- **10** (`:181`): "AM-20.5: the policy text (SA:512's bare cast) should read SA:446's `NULLIF(current_setting(
  'app.tenant_id', true), '')::uuid` form, because `''` raises 22P02 (measured in the spike); an empty setting then
  sees no rows."
- **15** (`:186`): "`app.current_time()` is a definer function callable by every runtime role."
- **16** (`:187`): "SA:529: `check.py --profile test` runs the live suite against `ops_test` and `incident_test`."
- **19** (`:190`): "`resolve_invocation` returns `job_type`, `job_id` and `conversation_id` instead of SA:459's
  `allowed_tools`" (so no `asset_id`/interval/asset type either).
- **72** (`:561-564`): "R131 and SA:400/SA:459 (`mcp_read`'s functions): `mcp_read` holds EXECUTE on `current_time`
  (erratum 15) and `resolve_invocation` and on nothing else in `app`; `asset_scope` arrives with T16 and
  `search_procedures_scoped` with T17/T16, each in its owner's revision (Plan E ruling 1: no definer without a
  caller), so R131's three-function set is the target, not today's."
- **77** (`:585-587`): `resolve_invocation`'s only lock is `run_lease FOR SHARE` (erratum 53); returns `run_id, job_id,
  job_type, tenant_id, conversation_id, run_state, attempt_state` (erratum 19).
- **80** (`:592-594`): "SA:460-461 with SA:176-184 (reads and the fence): a read tool is served after the handle
  resolved in its own committed unit; a fence that moves during the read cannot cause a write, and the worker's next
  fenced unit fails."
- **91** (`:714-716`): "`mcp_exec` holds EXECUTE on `current_time` (erratum 15) as well as the six; \"cannot execute
  any read function\" is shown as no EXECUTE on any other `app` function, since `asset_scope` and
  `search_procedures_scoped` do not exist yet (T16, T17/T16; erratum 72's pattern)."
- **69** (`:492-494`): "the sweeper iterates `tenants` and runs per-tenant work in one transaction per tenant
  (`ops_sweeper.tenants.for_each_tenant`)".

Debt lines and parked items that name the corpus or search:

- Walking skeleton (`SESSION_STATE.md:771`): "`search_procedures` is served lexically from `data/handoff-fixtures/`
  inside mcp-read (no governed store, no `asset_scope`) → T17; `get_asset_status` / `get_recent_alerts` and asset-sim
  are absent → T16".
- Plan E (`:789`): "`asset_scope`, `search_procedures_scoped` → T15/T16/T17"; (`:792`): "`migrator` holds no login:
  Alembic runs as the Compose superuser and transfers ownership explicitly → T30"; (`:797`): "`check.py --profile
  test` runs the live suite against per-session databases rather than a Compose test profile → T30"; (`:799`):
  "`outbox`, `feedback`, `idempotency_request`, `operator_resolutions`, `documents`/`chunks`/`embeddings`,
  `model_permit` are absent, so their AM-20.2 rows are not yet in the grant matrix → T14/T12/T22/T17/T13".
- Plan J (`:946-950`): "`asset_scope`, `get_asset_status`, `get_recent_alerts` and asset-sim → T16;
  `search_procedures_scoped`, the governed store and the `vector_exact` → `mode=vector` translation by its caller →
  T17/T16; `search_procedures` stays lexical over `data/handoff-fixtures/` (Plan J rulings 8, 9); mcp-read's tool
  arguments (the optional `asset_type`), the order of its `UNSUPPORTED_MODE` check and its fallback `corpus_version` →
  T16/T17 (ruling 20)".
- Plan D open item (`:171`): "mcp-read truncates an excerpt silently (bounded by the contract) and answers every
  handle rejection with the same `INVALID_HANDLE` (T15)"; Plan J (`:604-605`): "Plan D's silent excerpt truncation
  stays with the tool's contract (T16)."
- Plan D rulings (`docs/superpowers/plans/2026-10-08-first-slice-d-walking-skeleton.md:43`): "The one read tool is
  `search_procedures`, served from `data/handoff-fixtures/` inside `mcp-read` … `evidence_id =
  <DOCUMENT_ID>:v<version>:<section>`, `content_sha256` = the per-section hash from `meta.json` … Lexical mode only;
  `vector_exact` is refused with a tool error until T17 (the governed store)."; (`:55`): "`corpus_version` = the
  catalog's `fixture_version` (`handoff-1`, what mcp-read reports), `retrieval_mode = \"lexical\"`".
- Plan J rulings (`docs/superpowers/plans/2026-10-15-first-slice-j-mcp-read-verifier-handles.md:188-189`): "9.
  **`search_procedures_scoped`, `asset_scope`** — not created; debt lines to T16 and T17/T16; the fixture corpus stays;
  the two `TODO(T15)` markers on the `vector_exact` translation become `TODO(T16)`"; (`:217`): "20. **Arguments** —
  untouched; debt line to T16/T17."
- T45 / Plan C (`tasks.json:431`; fixtures README `:9-17`): `meta.json` derived (tenant UUIDs, alert UUIDs + revision 1,
  per-section hashes); the catalog's whole-file hashes unchanged; the schema examples keep the whole-file hash.

---

## 5. Open questions the planner must rule on

1. **Who builds `search_procedures_scoped` and who switches mcp-read to it (T17 or T16).** T17 owns "PostgreSQL
   full-text retrieval with access filtering" and "Superseded/expired/revoked sections never returned"
   (`tasks.json:729`, `:741`); T16's instructions say "search_procedures over the governed store" and its review note
   "search_procedures reads the governed store built in T17" (`:750`, `:767`); erratum 72 says "with T17/T16"; Plan E
   ruling 1 forbids a definer without a caller; T15's instructions put `search_procedures_scoped` in `mcp_read`'s
   EXECUTE set (`:669`). Granting it changes the live ACL equality (`test_mcp_read_t15_live.py:276`) and partly
   answers erratum 72 (`asset_scope` stays T16). Options: (a) T17 creates the function, grants `mcp_read` and switches
   the tool to it; (b) T17 creates the store and the function with another first caller, T16 grants and switches;
   (c) T17 creates the store and a non-definer search used only by ingestion/measurement, the function arriving with
   T16.

2. **The function's `vector(768)` argument and the pgvector extension.** SA:461's signature includes `query_embedding
   vector(768) NULL`; the `vector` type exists only where `CREATE EXTENSION vector` ran: `01-init.sql:2` in database
   `ops` at first volume start; no Alembic revision creates it; `ops_test` is created fresh by `conftest.py:66-67` with
   no extension step; definers pin `search_path = app, pg_temp` (`0003:25`); migrations run as the superuser
   (`skeleton.py:214`); vector search is T18's (R034). Options: create the extension in a T17 revision; a lexical-only
   signature now with T18 re-creating it (an erratum); the extension created by bootstrap/conftest; or the full
   signature with `mode=vector` refused until T18.

3. **Which corpus tables T17 creates.** AM-20.2 (SA:431) and AM-20.5 (SA:510) name `documents`, `chunks`,
   `embeddings`; BS:241-242 give the record fields; T17 speaks of "sections" and "per-section IDs/hashes", AM-20.3 of
   "chunks"; embeddings are T18's. Options: all three now (embeddings empty), `documents` and `chunks` only, or a
   separate `document_versions`/`sections` split (a departure from AM-20.2's names, i.e. an erratum).

4. **Chunk = section, or chunk ≠ section.** BS:415 "Chunk on headings/sections. Initial proposal: 300–600 tokens per
   chunk … The exact tokenizer/window choice must be recorded and evaluated."; documents are 300–900 words (SA:641);
   the evidence ID is per section (SA:643) and today `<DOCUMENT_ID>:v<version>:<section>` (`procedures.py:88`); no
   tokenizer package is locked (§3.9); excerpts are cut at 500 characters (`procedures.py:21`, schema max 8000).
   Options: one chunk per `##` section with a recorded token count; sections split into windows with sub-IDs; and how
   the tokenizer used for the count is named.

5. **Who runs ingestion, as which role, and how it is triggered.** AM-20.2 gives `worker` `ins, sel (ingestion)` and
   no UPDATE/DELETE to anyone (SA:431); seed data is written by `migrator` data migrations under BYPASSRLS (SA:440),
   but `migrator` has no login and migrations run as the superuser (`skeleton.py:65`, `:214`; Plan E debt `:792`);
   no ingestion job type exists (`jobs_type_check`, `0007:74-96`; SA:498-504); the worker sets `app.tenant_id` per
   transaction (SA:522). Options: a CLI that connects as `worker` and ingests per tenant; an Alembic data migration;
   a new job type (an erratum to AM-20.4); and whether services refuse to start on an empty or stale corpus.

6. **Idempotency key and the "conflicting content" rule.** BS:411 "idempotent ingestion keyed by
   document/version/hash"; BS:413 "Conflicting content under the same document/version/hash identity is rejected";
   R032 expected evidence "Repeat same document; change hash under same version; supersede/unapprove". With no UPDATE
   grant on the corpus tables (SA:431), a status change (approve → superseded/revoked) on an existing
   document/version cannot be an UPDATE by `worker`. Options: insert-only status history rows; a new grant (erratum to
   AM-20.2); re-ingest as a new version; and what a changed hash under an unchanged version does (refuse the whole run,
   refuse the document, record and skip).

7. **The lifecycle vocabulary and its fields.** Catalog statuses are `approved`, `superseded`, `draft`
   (`catalog.json:9`, `:23`, `:67`); T17's DoD says "Superseded/expired/revoked"; AM-50 "superseded/expired versions"
   (SA:642); R032 "supersede/unapprove"; BS:413 "approval/effective status … supersedes relation … Validate effective
   intervals"; the catalog has `effective_from` and `supersedes` but no `effective_to`/expiry or revoked status. Open:
   the fields (effective_to, revoked_at, status enum), whether supersession is implied by a newer approved version or
   only by an explicit `supersedes`, and how "revoked" is expressed.

8. **The clock that decides "effective".** `app.current_time()` (test clock in the test profile, SA:526-530); the
   catalog's `as_of` and the observations' `clock` are `2026-10-06T12:00:00Z`; today's date is 2026-10-16; all current
   `effective_from` values are 2026-09-01 or 2026-10-01; `procedures.py` compares no time. Options: compare at query
   time against `app.current_time()`; against a corpus `as_of`; at ingestion only.

9. **Shared documents versus tenant-only RLS.** BS:413 "tenant or explicit shared policy"; AM-20.5's
   `tenant_isolation` requires `tenant_id = app.tenant_id` and says these are "the only policies" besides
   `sweeper_all` (SA:520); T17 says "2 tenants". Options: tenant-only documents (no shared ones); per-tenant copies; a
   shared policy (an erratum to AM-20.5).

10. **Access filtering beyond the tenant.** BS:417 "approved/effective/tenant/resource-access constraints"; BS:386
    "currently permitted chunks"; BS:241 "tenant/access policy"; BS:362 the server "loads current requester/tenant
    policy from the stored run"; memberships carry `role ∈ {requester, reviewer, reader}`, `active`,
    `permission_version` (`0001:41-50`); the handle resolves `tenant_id` and run, not the requester's membership
    (`0004:29-31`). Options: tenant + lifecycle only; also require the run's requester to hold an active membership;
    per-document role or asset-family restrictions.

11. **Asset family, `asset_type` and the ">=6 assets".** SA:461 and BS:386 take `asset_type`; BS:413 lists "asset
    family"; the tool schema has optional `asset_type` but mcp-read's tool omits it (`server.py:181-186`; Plan J ruling
    20 → T16/T17); `runs` has `asset_id` only (`0001:80`); no assets table (AM-20.2); `observations.json` has two
    assets; asset-sim is an empty stub (T16). Options: where the ≥6 assets live (observations fixture, the catalog, a
    new assets fixture for T16's asset-sim), whether documents carry an asset family, and whether retrieval filters on
    it (and from where it learns the run's asset type).

12. **Where the corpus lives and what happens to the eight delivered documents.** BS:431 "Expand"; fixtures README
    `:3` "Load the catalog with a tenant-aware ingestion adapter"; `verify_handoff.py:270-280` hashes every catalog
    document and regenerates `meta.json`; governed LF/BOM rule (`:360-368`); the 1.0 manifest is checked against the
    zip (SA:50); the 8 documents are 31-72 words each (§3.4). Options: extend `data/handoff-fixtures/` (catalog,
    Markdown, regenerated `meta.json`); a new directory with its own catalog (and the checker taught it); keep the
    handoff documents inside the governed corpus (below the 300-word floor), rewrite them, or retire them.

13. **Injected-instruction documents in an approved corpus.** AM-50 requires "one injected-instruction document per
    tenant" (SA:642); the fixtures README `:7` says "Do not add attack variants to a normal approved corpus without an
    explicit test flag"; DEV-022 and D005 describe "isolated" or "harness" sources; R036 (T19) "Inject
    administrator-style text into SOP fixture"; BS:413 lists a "synthetic label". Options: approved injected documents
    in the normal corpus; a flagged subset excluded from normal ingestion; a label field the search returns or filters.

14. **The conflicting-procedure pair.** AM-50 "one conflicting-procedure pair" (SA:642); BS:417 "If … procedures
    conflict materially, ask/abstain"; SA:377's "evidence sufficient?" rule is a code rule over effective chunks.
    Options: both documents approved and effective with no metadata (detection left to T19/T20); a recorded conflict
    relation in the catalog; and whether retrieval returns both.

15. **Evidence IDs, section names and the hash rule for the new corpus.** Today `<DOCUMENT_ID>:v<version>:<section>`
    with the section name taken from `## <name>` (`gen_fixture_meta.py:28`), ≤160 characters (schema), hash per
    README `:15`; BS:415 asks for "stable source offsets and evidence IDs"; BS:242 "stable section/offset/hash".
    Options: heading text vs a slug vs a numbered section ID; whether offsets are stored; whether the hash rule changes
    (and so `meta.json` and the checker).

16. **The schema examples' whole-file hash.** `build_schemas.py:911-914` (`TODO(T17)`) and fixtures README `:17`: the
    examples cite `8bc76314…` (whole file) for `ALPHA-INCIDENT:v2:review`; `meta.json:36` gives the section hash
    `62a90906…`; mcp-read already returns section hashes; the examples are generated and drift-tested (T45); `--contracts`
    runs in CI. Options: regenerate the examples with section hashes in T17; leave them (examples are contract shapes);
    move the evidence examples to a corpus document.

17. **The corpus version.** The catalog says `handoff-1` (`catalog.json:2`) and the worker live test asserts it
    (`test_worker_live.py:49`); the examples say `fixture-1` (`build_schemas.py:1092`, `:1257`); the manifest field
    is 1..100 characters; T41 labels against "the frozen T17 corpus version" and "Corpus changes after this require
    re-labelling" (`tasks.json:793`); BS:427 puts the corpus version in a cache key; mcp-read's fallback is the first
    corpus's version or `"none"` (`server.py:88-89`). Options: a hand-set name, a content hash of the catalog and
    documents, or a database-recorded ingestion version; and whether it is per tenant.

18. **Full-text configuration and ranking.** BS:415 "PostgreSQL full-text retrieval as baseline"; BS:417 "Store
    retrieval settings and score interpretation", "Start `top_k=5`, allow up to 8"; today's ranking is term overlap
    with an `evidence_id` tie-break so a retry cites the same evidence (`procedures.py:8-9`, `:99-105`); the worker
    sends the whole message (≤500 chars) with `limit: 3` (`handlers.py:128`); the result schema has no score field.
    Open: text-search configuration (`english`, `simple`, other), the query parser (`plainto_tsquery`,
    `websearch_to_tsquery`, OR-of-terms), the rank function, the tie-break, whether a stored/generated `tsvector` and
    an index exist, and where the settings and score interpretation are recorded.

19. **The labelled dev queries and the measurement.** T17 DoD 3 "Lexical retrieval measured on labelled dev queries
    with denominators"; R033 "Known questions return labeled permitted sections; missing source remains missing, not
    guessed"; BS:609 "retrieval precision/recall over labeled permitted evidence"; no labelled query set exists
    (§3.9); T23 later commits "~60 dev cases" under `evals/dev/`; T18's DoD names `reports/retrieval-comparison.md`
    "with recall@k for both methods, denominators and CIs" against the same queries; the holdout must not be read
    (R071, SA:659). Open: how many queries, where they live, who labels them (agent-authored dev labels are dev data),
    the metrics (recall@k, precision@k, MRR, "missing stays missing" cases, cross-tenant probes), the CI method
    (Wilson per SA:665), and the report path.

20. **The path the measurement exercises.** SA:461's function needs a handle; a handle needs a run, an open job of
    its run, a live lease and its fence (`0007:137-158`, `0009:42-49`). Options: measure through mcp-read over HTTP
    with staged runs and handles; call the definer as `mcp_read` with staged handles; call a non-definer search as the
    superuser or `worker`; or a pure-Python reader over the same rows (which would not measure the SQL path).

21. **mcp-read's in-memory corpus after T17.** `production_app` loads `data/handoff-fixtures` at start (`server.py:284`,
    `OPS_FIXTURES_DIR`); unit and live tests assert its content and ranking (§3.5); mcp-read's startup checks a
    function marker (`assert_function_text`, `server.py:226`). Options: remove the fixture path, keep it as a test
    double, or leave mcp-read untouched until T16; and whether mcp-read's startup also checks the new revision.

22. **The final gate's document recheck.** BS:425 and BS:476 require the grant to recheck that the cited source version
    is still approved/effective; R045 (T21) "Revoke … source before grant transaction; zero destination writes";
    `stale_evidence` is already a `grant_execution` reason (`0002:141-146`) with no reader; DEV-020 (R032/R045)
    expects BLOCKED_REVIEW. Open: whether T17 provides the lookup T21 will call (a helper over the corpus tables,
    granted to nobody per SA:474, or a column the grant can join), or leaves it entirely to T21.

23. **Freezing the corpus for T41.** T41 (`external_approval_required: true`) labels the holdout against "the frozen
    T17 corpus version" and needs T03's seal (pending owner step 9, `SESSION_STATE.md:1069`); BS:603 "Group by
    source/template family before splitting". Open: what T17 commits as the frozen identity (a version string, a hash
    of the catalog and documents, a database snapshot), whether T17's close-out declares the freeze or a later step
    does, and what counts as a "corpus change" that would force re-labelling.

24. **The dev database and the new revision.** The dev `ops` database is at `0010_write_path`
    (`SESSION_STATE.md:1056-1058`); every earlier plan left a new revision for the owner to apply, and services that
    assert a relation or function refuse to start without it (`persistence.assert_relation`,
    `assert_function_text`). Open: which services (mcp-read, worker, an ingestion CLI) assert the T17 revision, and
    the debt line recording that the dev database waits for the owner.

---

## 6. Glossary of exact names

- Tables named by the spec, not yet created: `app.documents`, `app.chunks`, `app.embeddings` (SA:431, SA:510).
  Existing related tables: `app.tenants` (`0001:35`), `app.memberships` (`0001:41`), `app.runs` (`asset_id`
  `0001:80`), `app.run_directory`, `app.invocation_context`, `app.run_lease`, `app.jobs`.
- Functions named by the spec, not yet created: `app.search_procedures_scoped(raw_handle, query, query_embedding
  vector(768) NULL, asset_type, limit, mode)` (SA:461); `app.asset_scope(raw_handle)` (SA:460, T16). Existing:
  `app.resolve_invocation(text, text)` (`0004:239`); `app._resolve_handle(text, text, text)` (`0009`, from
  `0007:123`); `app._tenant_of_run(uuid)`; `app.current_time()`.
- Policy and setting: `tenant_isolation`, `sweeper_all`, `sweeper_purge_maintenance`; GUC `app.tenant_id`; expression
  `NULLIF(current_setting('app.tenant_id', true), '')::uuid` (`privileges.py:181`). Error classes OC001–OC008
  (`OC008` = handle refused).
- Roles: `migrator` (NOLOGIN, BYPASSRLS here; owner), `app_definer` (NOLOGIN), `api`, `worker`, `sweeper`, `mcp_read`,
  `mcp_exec`, `operator`, `test_harness` (test profile), `incident`; Compose superuser `ops`.
- Modules: `ops_mcp_read.procedures` (`WORD`, `EXCERPT_CHARS`, `tokens`, `section_bodies`, `Section`, `Hit`, `Corpus`,
  `Corpus.load`, `Corpus.search`, `load_corpora`); `ops_mcp_read.server` (`search_response :83`, `State :170`,
  `build_server :178`, tool `search_procedures :181`, `production_app :279`, `read_verifier :265`);
  `ops_core.privileges` (`GRANTS :71`, `RLS_TABLES :144`, `NO_RLS :164`, `DEFINER_FUNCTIONS :185`,
  `HELPER_FUNCTIONS :206`, `grant_statements :228`, `rls_statements :261`, `function_grant_statements :280`);
  `ops_core.persistence` (`Session :138`, `set_tenant :127`, `assert_relation :170`, `HANDLE_BINDING :183`,
  `assert_function_text :190`, `Invocation :387`, `allowed_tool :399`, `resolve_invocation :425`);
  `ops_core.jobs` (`Tool.SEARCH_PROCEDURES :24`, `JobType :37`); `ops_core.routing.RunManifest :350`;
  `ops_core.settings.fixtures_dir :449`, `Role :103`; `ops_worker.handlers` (`QUERY_CHARS :39`); `ops_worker.proposals`
  (`evidence_from_search :35`).
- Migrations: `migrations/app/versions/0001_walking_skeleton.py` … `0010_write_path.py`, `tc_0001_test_clock.py`
  (branch `testclock`); constants `HEADER`/`HELPER_HEADER` (`0003:25-26`), `HANDLE_COLUMNS` (`0004:29`),
  `RESOLVE_HANDLE` (`0007:122`), `JOB_TYPES_0007` (`0007:74`), `TABLES`/`GRANTS_0002`/`RLS` (`0002:32`, `:59`,
  `:118`); convention: each revision freezes `GRANTS_<rev>` and `FUNCTIONS`, guarded by
  `tests/plan_e/test_transitions_table.py:61` and its `REVISIONS` tuple (`:86-98`).
- Scripts: `scripts/skeleton.py` (`migrate`, `ensure_roles`, `NOLOGIN_ROLES`, `migrate_target`), `scripts/check.py`
  (`--profile dev|test`), `scripts/verify_handoff.py` (`--reference-code --manifest --contracts`),
  `scripts/gen_fixture_meta.py` (`uv run python -m scripts.gen_fixture_meta`), `scripts/build_schemas.py`,
  `scripts/gen_seed_ids.py` (`NS`).
- Data: `data/handoff-fixtures/{catalog.json, meta.json, observations.json, README.md, *.md}`, `data/seed-ids.json`;
  catalog fields `fixture_version, as_of, documents[].{document_id, tenant, version, approval_status, effective_from,
  supersedes, path, content_sha256, sections, classification}`; tenant UUIDs alpha `3ea79c95-914c-52cb-9d10-c4e19dda8ff7`,
  beta `5ab45c2c-1e12-5a0c-a2b9-66cd2ff05201`; alert UUIDs `cfa4e790-6f70-5e49-b73f-e9e8d613f52e` (A17-alert-001),
  `8fd07823-d6b4-5ffc-a691-3bba680494e1` (A17-alert-002), `4f165b6c-3bda-5839-a401-6be0086b9dfc` (A17-old-001);
  assets `A17` (alpha), `B22` (beta).
- Schemas: `schemas/tools/search_procedures.input.schema.json`, `schemas/tool-result.schema.json` (search branch
  `:289-386`), `schemas/evidence.schema.json`, `schemas/run-manifest.schema.json`, `schemas/proposal.schema.json`,
  `schemas/examples/tool-search_procedures-valid.json`, `schemas/examples/evidence-valid.json`,
  `schemas/examples/index.json` (1.3.3).
- Env vars: `OPS_FIXTURES_DIR` (default `data/handoff-fixtures`), `OPS_LIVE`, `PROFILE` (`dev|test|demo`),
  `OPS_PG_DB` (`ops`; `ops_test` live), `OPS_INCIDENT_PG_DB`, `OPS_PG_HOST`, `OPS_PG_PORT` (15432),
  `OPS_PG_SUPERUSER` (`ops`), `OPS_MCP_READ_PORT` (8081), `MCP_READ_RESOURCE_URL`, `OPS_MCP_READ_URL`,
  `OPS_WORKLOAD_CLIENT_ID` (default `ops-worker`), `MODEL_MODE`. Secret file names (not read):
  `postgres_password`, `postgres_worker_password`, `postgres_mcp_read_password`.
- Requirement and test targets: R032 `tests/acceptance/test_r032_source_ingestion_is_versioned_effective_and_idem.py`,
  R033 `tests/acceptance/test_r033_lexical_baseline_has_labeled_evidence_measuremen.py`, R099
  `tests/acceptance/test_r099_evidence_corpus_is_large_enough_to_measure_retri.py`; T18's
  `reports/retrieval-comparison.md`; T23's `evals/dev/`.
- Retrieval vocabulary in use: `retrieval_mode` `lexical` | `vector_exact` (external), `mode=lexical` | `mode=vector`
  (SQL, erratum 3); `corpus_version`; `evidence_id` = `<DOCUMENT_ID>:v<version>:<section>`; `content_sha256` (per
  section); prefixes `search_document:` / `search_query:`; model `nomic-embed-text`, dimension 768 (SA:461).

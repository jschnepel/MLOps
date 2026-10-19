# Plan N review record — T18 exact vector retrieval and the comparison

Plan: `docs/superpowers/plans/2026-10-19-first-slice-n-vector-retrieval.md` (branch `plan-n`; plan commit 6ba15e5,
round 1 fixes c9ebe7f, round 2 fixes a68f67e). Inputs: `docs/superpowers/research/2026-10-19-plan-n-inputs.md` and the
controller's rulings brief (reproduced below).

How the rounds ran. As in Plan M, the writer built the whole slice in a scratch copy of the tree and generated the
plan's code blocks from those tested files; each critic applied every Create and Edit step of the plan, task by task,
to a fresh `git archive` copy and gated each task with ruff, ruff format, mypy strict and the non-live pytest. A scratch
copy has no database credentials and no git checkout, so every live count in the plan is arithmetic until execution,
and the 13 tests that need a git checkout are added back to the counts. Unlike earlier plans, the writer and the
critics also called the local Ollama read-only (`/api/version`, `/api/tags`, `/api/embed`): the pin's digest, the 768
dimensions and the vector threshold (0.68, by the rule fixed in ruling 6) were measured, not assumed, and re-measured
independently by both critics.

Round 1: REVISE, 0 Critical, 2 Important, 13 Minor; all fixed in c9ebe7f, nothing parked. Round 2: REVISE, 0 Critical,
1 Important, 4 Minor (the round-1 window fix still measured its ranking figures above the tuned threshold); all fixed in
a68f67e, which the controller checked against the rulings instead of a third round. Dev counts after Tasks 1-6: 1400,
1411, 1422, 1424, 1434, 1434 passed (205, 205, 209, 214, 214, 215 skipped); final live count 1628 passed, 21 skipped
(arithmetic until execution).

No agent connected to any database, Keycloak or service in these rounds, and no `.env` or secret file was opened.
Process slip: while writing the plan, the writer once ran a bare `python3 -` reading stdin inside a shell command; it
hung, was stopped by task ID, and nothing executed. The critics had none.

---

# Controller brief (rulings before round 1)

## Plan N brief — controller rulings for T18 (exact pgvector retrieval and comparison)

Branch `plan-n` (= `plan-m` e0d0d53 + fact sheet 6d00d06; PR #12 plan-m -> main open). Fact sheet:
`docs/superpowers/research/2026-10-19-plan-n-inputs.md` (FS). Errata continue at **107**. Requirement: R034. Gates at
start: dev 1372 / 205; live 1556 / 21; verify_handoff 0.

**Measured by the controller on 2026-10-19 (local Ollama, loopback):** `/api/version` → `0.40.4`; `/api/tags` lists
`nomic-embed-text:latest` with digest `0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f` (and
`qwen3:8b` `500a1f06…8b41`); `/api/show` for it carries no digest but `nomic-bert.embedding_length: 768` and
`context_length: 2048`; `POST /api/embed {"model":"nomic-embed-text","input":[…]}` answers `{"model", "embeddings":
[[768 floats]]}`. The recorded Ollama version was 0.33.3 (SA:587); the installed one is 0.40.4 — the pin records the
version actually used and the close-out tells the owner (SA:587 "upgrade only with owner approval": the upgrade
predates this plan; not ours to undo).

Principle: T18 adds **exact vector search beside the lexical baseline, measured against it**, without changing the
lexical path, the corpus, the evidence IDs, the tool schemas or the worker. Mode selection by the worker (T20/T25), a
relevance/abstention rule (T20, erratum 102), containers and network tests (T30) stay with their owners.

### Rulings (one per FS question)

1. **Storage (FS Q1) — a separate `app.embeddings` table in revision `0013_embeddings`.** SA:431/SA:510 name it;
   erratum 95 says T18 creates it. Columns: `tenant_id uuid`, `evidence_id text`, `model text` (`nomic-embed-text`),
   `model_digest text` (64-hex CHECK), `dimension integer CHECK (dimension = 768)`, `input_sha256 text` (64-hex: the
   SHA-256 of the exact UTF-8 text sent, prefix included — the prefix proof), `embedding public.vector(768) NOT NULL`,
   `embedded_at timestamptz DEFAULT now()`. PK `(tenant_id, evidence_id)` (one embedding per chunk; a model change is a
   later revision's re-embedding, debt line). FK `(tenant_id, evidence_id)` → `app.chunks`. Owner `migrator`; grants
   `worker` SELECT+INSERT, `app_definer` SELECT (SA:431), nothing else; ENABLE+FORCE RLS with `tenant_isolation` for
   the policy roles (SA:510); `privileges.GRANTS`/`RLS_TABLES` rows in the same change; `REVISIONS`, the transitions
   table test, the lock-order guard and `test_migration_0008_live`'s transitive scan include 0013. No vector index
   (ruling 7). 0013 also re-creates `search_procedures_scoped` (ruling 5) from **0012's** body with `changed()`-style
   exact edits (0012's pattern: every edit's old text present exactly once; a unit test reverses them and compares);
   return type unchanged, so `CREATE OR REPLACE` is allowed if the writer shows it keeps the ACL (else DROP + CREATE +
   re-grant as 0012 did). Exact downgrade to 0012 (restore 0012's body from 0012's frozen tuple; drop the table and
   any helper). mcp-read asserts a new startup marker `VECTOR_SEARCH` (text unique to the vector branch); the
   `GOVERNED_CORPUS` and `SEARCH_INSTANT` markers stay (the lexical text and `retrieved_at := v_now` survive).

2. **Who writes document embeddings (FS Q2) — option (b), a separate operator command `skeleton.py embed`, as
   `worker`.** Erratum 98's shape (an operator command, not a job, not a migrator data migration). It: loads and
   verifies the embedding pin (ruling 3) against Ollama `/api/tags` before any write; embeds **every stored chunk
   without an embedding** (lifecycle is filtered at query time, so the step never consults the clock — ingest's rule);
   sends batches to `POST /api/embed` (batch size a constant, e.g. 16); checks each answer has exactly 768 finite
   floats; refuses (writes nothing for that tenant) if any stored row of the tenant has another `model_digest` than the
   pin; writes one transaction per tenant; a repeat with nothing missing writes nothing and prints `EMBED: <tenant>: 0
   new, n present`. The document text is exactly `"search_document: " + section + "\n\n" + body` (heading plus body,
   as the lexical vector indexes both). `ingest` stays network-free and unchanged. The live suite gains an `embedded`
   fixture (after `ingested`) running the same code against `ops_test`.

3. **Pins (FS Q3) — a sibling pin file.** `data/embedding-pins.json` with `schemas/embedding-pins.schema.json`
   `{model, digest, dimension, ollama_version, probed_at}` (`additionalProperties: false`, digest bare 64-hex,
   dimension const 768), loaded by `ops_core.model_pins.load_embedding_pins` (beside `load_model_pins`, same strictness).
   Written by a new `scripts/pin_embedding_model.py` (reads `/api/version`, `/api/tags` for `nomic-embed-text:latest`'s
   digest — `/api/show` carries none, as T19's note found for qwen3 — and one `/api/embed` call for the dimension); the
   implementer runs it once against local Ollama and commits the file (real values only, BS:670; expected digest the
   one measured above). **Erratum 107:** SA:598/SA:768's `data/model-pins.json` stays the generation model's (T02/T19);
   the embedding model's pin is `data/embedding-pins.json`, verified by `/api/tags`'s digest (AM-31 says `/api/show`).
   Verification: `skeleton.py embed` before writing, and mcp-read on every vector call (ruling 4). Mismatch, missing pin
   or a wrong dimension: `embed` exits 1 writing nothing; mcp-read answers `UNSUPPORTED_MODE` (`retryable: false`).
   `verify_handoff.py --contracts` validates the pin file against its schema if it already validates other data files
   (writer checks; else a unit test does).

4. **The query embedding (FS Q4) — mcp-read computes it (SA:348, SA:461 bind; the amendments win over BS:646/BS:144).**
   **Erratum 108:** BS:646's MCP row, BS:144's diagram, ADR-0001:31 and `docs/ARCHITECTURE.md` gain "mcp-read →
   Ollama, `/api/tags` and `/api/embed` with the embedding model only, never generation"; record it in
   `docs/ARCHITECTURE.md` and as a dated note under ADR-0001 (do not rewrite the ADR's decision). Setting
   `OPS_OLLAMA_URL` (default `http://127.0.0.1:11434`, `settings.Urls.ollama`). An `ops_core.embeddings` module holds
   the prefixes, the text builders, an `Embedder` protocol and the Ollama client (`httpx2`, async for mcp-read; the
   CLI may run it under `asyncio.run`), timeout 10 s, no retry (asset-sim client's pattern). The embedding call is not
   a `model_permit` holder (generation only; SA:203 — say so in the erratum). Order in `search_procedures`: unit 1
   (handle, allowlist) → unit 2 (`asset_scope`) → the run's asset type (asset-sim) → **then** for `vector_exact` the
   pin check + query embedding → unit 3 the definer with `mode='vector'`. Ollama unreachable / timeout / 5xx →
   `UNAVAILABLE` `retryable: true`; a malformed answer (not 768 finite floats) → `UPSTREAM_INVALID`. The handle-first
   rule stays: an invalid handle never reaches Ollama. Everything stays within the tool's existing time budget if it
   has one (writer checks `server.py`).

5. **Same filters (FS Q5).** The vector branch reuses the `latest`, `effective` and `permitted` CTE text **verbatim**
   (a unit test extracts both branches' CTEs from the frozen body and asserts equality), then joins
   `app.embeddings e USING (tenant_id, evidence_id)`. Argument rule: `p_mode IN ('lexical', 'vector')`; `p_query`
   still required and bounded 1..500 in both modes; `vector` requires `p_query_embedding IS NOT NULL AND
   vector_dims(p_query_embedding) = 768`; `lexical` requires `p_query_embedding IS NULL` — else `OC005`
   `BAD_ARGUMENT`. The `VECTOR_MODE_UNAVAILABLE` refusal is removed (its tests change to the new behaviour). The
   stop-word early return is lexical only. `corpus_version`, `retrieved_at`, `excerpt`, `excerpt_cut`, the result
   keys and the membership check are identical in both modes. **Completeness:** in vector mode, if any permitted chunk
   of the tenant has no embedding row, the definer refuses `OC005` `EMBEDDINGS_INCOMPLETE` (mcp-read → `REFUSED` with
   that code, its existing mapping): no silent omission. An empty corpus answers `[]` as lexical does.

6. **Score (FS Q6).** Cosine distance `<=>`; `rank` in vector mode = cosine similarity `1 - (e.embedding <=>
   p_query_embedding)` (documented: same key, another meaning, not comparable with `ts_rank_cd`, BS:417); order
   similarity DESC, tie-break `evidence_id COLLATE "C"`; keep only `similarity > app._min_similarity()`, a new helper
   like `_min_rank` (IMMUTABLE, owner `app_definer`, granted to nobody, in `HELPER_FUNCTIONS`). Its value is chosen
   by a **rule fixed before measuring**: the largest threshold on a 0.01 grid at which vector hit@5 over the answerable
   development cases equals its value at threshold 0 (no answerable hit lost); report the whole sweep; the value is a
   development figure (SA:657-659: the holdout is never read). The implementing task measures it in Python from the
   corpus files and real embeddings before freezing 0013 (it is a constant in the revision); the live comparison then
   confirms it. If the rule yields 0 or below, the helper returns 0 and the report says so.

7. **Exact (FS Q7).** No vector index: a sequential scan over the tenant's permitted chunks is exact by construction
   (69 chunks). A live test proves exactness: for several development queries, the definer's ordered evidence IDs equal
   a Python brute-force cosine ranking over the stored vectors of the permitted set (read as the superuser in
   `ops_test`), same threshold and tie-break. BS:242's "index version" is recorded as model + digest + dimension +
   prefix + window ("no index") in the report and `docs/retrieval.md`.

8. **Another window (FS Q8) — an experiment in the report only.** The stored unit stays one chunk per section (evidence
   IDs, citations and T41's labels unchanged). The report adds one alternative window computed in Python from the
   corpus files: adjacent sections of one document version concatenated in order until ≥300 `[a-z0-9]+` words (the
   remainder joins the last window), embedded with the same prefix rule, filtered by `corpus.returnable(corpus,
   AS_OF)` and tenant, ranked by cosine; a window hits if it contains a labelled section. Recall/hit@5 and
   none-answered-empty (with the same threshold) with denominators and CIs; no forbidden section may appear. This
   closes erratum 100's "evaluated in T18's comparison" as a recorded experiment; no change of the stored window.

9. **Lexical minimum rank (FS Q9) — measured, unchanged.** The report includes a sweep of the lexical threshold over
   the recorded per-case ranks (hit@5 and none-answered-empty per value); `_min_rank` stays 0.25; the lexical body
   stays byte-identical. The residue stays T20's relevance criterion (erratum 102).

10. **Numeric tokens (FS Q10) — re-homed to T23.** The lexical body stays byte-identical in T18 so the comparison is
    against the committed baseline. Debt line → T23: the development eval set adds numeric-token cases and measures
    the loss; a fix only with that evidence (BS:71).

11. **The report (FS Q11).** `reports/retrieval-comparison.md` + `reports/retrieval-comparison.json` (the DoD path),
    written by a live test `tests/e2e/test_retrieval_comparison_live.py` (T17's pattern: clock at `AS_OF`, staged runs
    with the seeded requesters, a fresh handle per query, `persistence.search_procedures` for both modes through
    `mcp_read`; the query embedding computed with the same `ops_core.embeddings` code mcp-read uses). Lexical is
    re-measured in the same session and its per-case answers must equal the committed T17 JSON (assertion: the
    lexical path did not move). Metrics from `scripts/retrieval_baseline.py` (extend it or add
    `scripts/retrieval_comparison.py` reusing its functions) at k=5 and k=3 (the worker's limit): recall, precision,
    MRR, hit, every-expected, none-answered-empty, cases-without-forbidden, with Wilson 95% CIs and denominators;
    per-category rows; per-question improvements and regressions listed by id; paired exact McNemar (two-sided,
    exact binomial on the discordant pairs) on hit@5 over answerable cases and on none-answered-empty over the
    no-source cases, with SA:667's rule (no ranking claim without p < 0.05) and the small-n caveat; zero forbidden
    rows is a hard assertion for both modes; the threshold sweeps (rulings 6, 9), the window experiment (ruling 8), the
    repeat-embedding check (ruling 14) and the settings: model, digest, dimension, prefixes, distance, thresholds,
    window, Ollama version, `queries_sha256`, `lock_sha256`, `as_of`. No new development queries (the sha stays
    `d6d539bd…`). The T17 report is not rewritten by this test.

12. **Prefix test (FS Q12).** Unit: with a fake transport, the document embedder sends exactly `search_document: ` +
    section + `\n\n` + body and the query embedder exactly `search_query: ` + query (assert the request bodies).
    Live: every stored row's `input_sha256` equals the SHA-256 of its prefixed text; for one chunk the stored vector
    equals a fresh `/api/embed` of the prefixed text within the ruling-14 tolerance and differs from the unprefixed
    text's embedding (cosine below the tolerance's bound).

13. **Tests without Ollama (FS Q13).** Unit tests (`tests/plan_n`, added to `testpaths`) use a fake transport
    (`httpx2` mock) and a deterministic fake embedder (hash-derived unit vectors); CI stays as is. Live tests use real
    Ollama (the live gate already needs it, `test_ollama_bridge.py`): the `embedded` fixture, the definer tests, the
    exactness test, mcp-read's vector tool test and the comparison. Tests that need a specific geometry may insert
    synthetic rows as the superuser into tenants the test creates and removes in `ops_test` only.

14. **Determinism (FS Q14).** Stored vectors are the source of truth; query vectors are computed at call time. The
    report records a repeat-embedding check (each development query embedded twice: max |Δ| per component and the
    minimum cosine); the live test asserts cosine ≥ 0.9999 between repeats. Ties broken by `evidence_id COLLATE "C"`.

15. **Dev database (FS Q15).** Owner steps: migrate dev to 0013 (after 0012), then `uv run python scripts/skeleton.py
    embed`. mcp-read refuses to start without 0013 (the `VECTOR_SEARCH` marker); until `embed` runs, vector mode
    answers `REFUSED`/`EMBEDDINGS_INCOMPLETE` and lexical works. corpus-1 and its lock are unchanged (assert in a unit
    test or by the existing `corpus.load` check). No agent touches the dev database.

16. **Mode choice (FS Q16).** The worker is unchanged (lexical; mode selection and the manifest → T20/T25, debt line).
    `search_response` reports the mode actually used (`vector_exact` for vector). No tool-argument change, so the
    committed input schemas and R029's check stay byte-identical (assert the schema files unchanged). `UNSUPPORTED_MODE`
    survives only for a missing/mismatched embedding pin.

17. **Vector parameters (FS Q17) — no new dependency.** Pass the vector as a text literal `'[f1,f2,…]'` cast in SQL
    (`%s::public.vector`), floats formatted with `repr` (round-trip safe); read vectors back in tests by parsing the
    text form. `pgvector-python` (SA:584) is not used; say so in erratum 109 (SA:584's row is unused, not violated).
    No `numpy`; cosine in Python is plain arithmetic.

18. **Records (FS Q18).** R034 → `IMPLEMENTED_LOCALLY_VERIFIED` / `RECORDED_LOCALLY_LIVE` with evidence the comparison
    report (.md/.json), `tests/e2e/test_retrieval_comparison_live.py`, the other live tests, `tests/plan_n/`, and
    `data/embedding-pins.json`; R033's note gains one clause (the lexical path re-measured unchanged in T18). Docs:
    `docs/retrieval.md` (vector settings, score interpretation, the window experiment, the sweep), `docs/runbooks/
    mcp-read.md` (vector mode, `OPS_OLLAMA_URL`, the new codes, troubleshooting), a runbook section for `skeleton.py
    embed` and the pin script, `docs/ARCHITECTURE.md` (erratum 108). Errata 107 (pin file), 108 (mcp-read → Ollama),
    109 (no pgvector-python; text cast), 110 (the definer's vector argument rules and `EMBEDDINGS_INCOMPLETE`, against
    SA:461) and further ones the writer finds. Close-out: tasks.json (T18 DONE, review note; M06 stays open for T41),
    acceptance matrix, BUILD_BACKLOG, SESSION_STATE (owner inputs: migrate 0013, run `embed`; Ollama 0.40.4 recorded),
    STATUS, PROJECT_HISTORY (new section for Plan N), errata.

### Constraints for the writer

- Same plan format as `docs/superpowers/plans/2026-10-18-first-slice-m-read-tools-asset-sim.md`: Global Constraints, a
  debt list, then tasks with exact files, complete code where it is load-bearing (SQL bodies and the `changed()` edits
  verbatim), tests first, exact commands and expected outputs, a close-out task. Function signatures and regprocedure
  argument lists are **copied from the code** (`privileges.DEFINER_FUNCTIONS`, 0012's `SEARCH_ARGS`), never retyped.
- Read 0011 and 0012 in full before writing 0013; the `changed()` edits must apply to 0012's actual body text.
- Authority, approval, idempotency, no-unapproved-external-action boundaries preserved; tenant only from the handle;
  no table grant for `mcp_read`; definers per SA:446.
- Live tests use only the `ops_test` databases (profile test) and local Ollama on loopback; nothing touches the dev
  database. Implementers may call local Ollama's `/api/version`, `/api/tags`, `/api/embed` (never pull, delete or
  generate).
- Comments per `docs/CODE_COMMENTS.md`; no Claude attribution in commits.

---

# Controller rulings on the writer's departures

## Plan N — controller rulings on the writer's departures (plan 6ba15e5)

1. `embed` refuses the whole run when any tenant holds another digest's embeddings (ingest's whole-catalog rule) —
   **accepted**, provided the digest check of every tenant happens in the planning phase before any write, so the
   "a tenant written before a later failure stays written" case can only come from a failure during writing (Ollama
   outage, a malformed answer), and a rerun then completes the rest. The critic checks both.
2. A zero vector is `BAD_ARGUMENT` in the definer, and an all-zero answer is malformed in the client — **accepted**
   (NaN ordering would otherwise rank it first).
3. The completeness check is a LEFT JOIN inside the ranking statement over the call's permitted set (asset filter
   included) — **accepted**: one snapshot; the refusal still fires whenever any chunk this call could return lacks an
   embedding.
4. `_min_similarity()` returns `double precision` — **accepted**.
5. The lexical side is compared against a pinned digest of the committed T17 answers — **accepted**; the critic checks
   the digest is computed from exactly the per-case answers (ids and order), not from fields that change per run
   (`measured_at`).
6. Both sweeps run in Python over stored vectors / recorded ranks; the lexical grid starts at 0.25 — **accepted**.
7. The pin file validated by a unit test; schema generated by `build_schemas.py`; `EmbeddingPins` in the
   schema-conformance models — **accepted**.
8. `Urls.ollama` required; two hand-built `Urls(...)` gain it — **accepted**.
9. One 10 s budget for pin check + query embedding in mcp-read — **accepted**.
10. `TODO(T18)` stays inside 0011's frozen body and 0013's quotation of it — **accepted** (frozen revisions are history).
11. The worker's marker is `TODO(T25)` while the debt line names T20 and T25 — **accepted**.

Writer's process slip: one bare `python3 -` reading stdin, stopped by task ID; nothing ran. Recorded in the history.

---

# Round 1

## Plan N, round 1: static critique

Plan: `docs/superpowers/plans/2026-10-19-first-slice-n-vector-retrieval.md` (6ba15e5, 5496 lines, read in full).
Inputs: the controller's brief (18 rulings), the rulings on the writer's 11 departures, the fact sheet, the
SPEC_AMENDMENTS / BUILD_SPEC lines cited below, the code at 6ba15e5, and the round-1 critique format of
`docs/reviews/plan-review-m-2026-10-18.md`.

**Verdict: REVISE.** I found 0 Critical, 2 Important and 13 Minor findings.

The mechanics hold. Every anchor applies exactly once, every stated dev count reproduces, and every red step fails
the way the plan says. ruff, ruff format and mypy strict are clean after each task. The 0013 body the plan prints is
byte-identical to what `changed()` renders, and its diff against 0012 is exactly the three named changes. The threshold
rule re-measures to 0.68 against local Ollama.

Both Important findings concern what the evidence and the documents will claim, not whether the code runs:

- The 300-word window experiment cannot tell one ranking from another on corpus-1.
- One documented operator command silently defeats the "swapped model is refused" guarantee.

Neither weakens a tenant, authority or approval boundary.

### Critical

None.

### Important

#### I1. The window experiment degenerates on corpus-1: every window is one whole document version, and top-5 holds every window. The plan reports and documents it as a 300-word-window result.

- **Where.**
  - `retrieval_comparison.windows` / `corpus_windows` / `window_metrics` (plan :1714-1783).
  - The live use (plan :4630-4641).
  - The md paragraph (plan :1961-1968), which says "Adjacent sections of one version joined until at least 300 words
    (8 windows) ...".
  - `docs/retrieval.md` Edit 2 (plan :4733-4736), which says "T18's comparison evaluated one other window as an
    experiment ...". It closes erratum 100's open question on this result.
- **Measured** (scratchpad `critic1/windows_check.py`, corpus files only).
  - Every corpus-1 version has 327-343 `[a-z0-9]+` words.
  - Each of the 8 versions returnable at AS_OF therefore becomes exactly one window: the first window closes on the
    last section, and nothing is left over. Alpha has 5 windows and beta has 3.
  - With k = 5, the top 5 of a tenant is every window above the threshold. So "hit@5 23/27", "recall@5 0.85" and
    "answered-empty 19/20" (my simulation with real embeddings, `critic1/simulate.py`) depend only on the threshold.
  - That threshold (0.68) was tuned on section-level embeddings. No ranking is measured at all.
- **Failure scenario.** The DoD report and `docs/retrieval.md` record a "300-word window" comparison and use it to
  settle erratum 100 ("the stored unit stays one chunk per section"). In fact the experiment measured whole-document
  embeddings at a threshold tuned for sections, with no ordering signal. A reader, and T23/T25 after them, would take
  it as evidence about window size.
- **Fix** (inside ruling 8; no change of the rule):
  - In `window_metrics`, also return the windows per tenant, the sections per window and min/max words per window.
  - Also return a rank-sensitive figure (hit@1 and MRR@5 over the labelled cases) and the threshold-0 recall.
  - In the md paragraph and in `docs/retrieval.md`, say plainly: "on corpus-1 every returnable version (327-343 words)
    is one window, and k = 5 is at least the windows of either tenant, so hit@5 and recall@5 measure only the
    threshold".
  - Add a unit assertion in `test_retrieval_comparison.py` that `corpus_windows(corpus.load(CORPUS))` has 8 windows,
    each one whole version. This pins the observation so the report cannot drift from it.

#### I2. `scripts/pin_embedding_model.py` overwrites the pin unconditionally. Re-running it, as the docs instruct for a model change, makes mcp-read rank new-model query vectors against old-model document vectors with no refusal.

- **Where.**
  - The pin script writes `OUT` unconditionally (plan :1257).
  - mcp-read checks only the installed digest against the pin (`query_embedding`, plan :4230-4248;
    `OllamaEmbedder.verify`, :1172-1176).
  - The definer never compares stored rows' `model_digest` with anything (vector branch, plan :2576-2583). It cannot,
    because its signature is frozen (ruling 16).
  - `embed` is the only reader of the stored digest (plan :3492-3499).
  - The docs tell the owner to "re-run it only when the owner changes the model, and then embed again in a new
    revision" (plan :4795-4796).
  - `docs/ARCHITECTURE.md` section 11 claims "a pinned model on both sides ... so a swapped model is refused, not used"
    (plan :5047-5049).
- **Failure scenario.**
  1. The owner (or an `ollama pull`) changes `nomic-embed-text:latest`.
  2. mcp-read correctly answers `UNSUPPORTED_MODE`.
  3. The owner follows the docs and re-runs the pin script. mcp-read's check passes again.
  4. From then until a re-embedding revision lands, every `vector_exact` answer compares vectors from two different
     models. Nothing refuses: the definer has no digest to compare, and `embed` refuses only when someone runs it.
  5. The ARCHITECTURE claim is false in exactly the case it is written for.
- **Fix** (pick one; the first is cheapest):
  - Make `pin_embedding_model.py` refuse (exit 1, nothing written) when `data/embedding-pins.json` exists with another
    digest, saying "a model change is a new revision that re-embeds; update the pin in that revision". Add a unit
    test with a fake transport.
  - Change the docs order to "new revision re-embeds, then the pin", and narrow the ARCHITECTURE sentence to the query
    side. Optionally add a debt line (the stored-digest check on the read path belongs to the re-embedding revision).

### Minor

1. **Task 7 Step 5's check cannot print nothing.**
   - The check (plan :5086-5087) greps `docs/retrieval.md` for `T18's comparison`.
   - The plan's own Edit 2 (:4733, "T18's comparison evaluated one other window") and Edit 3 (:4747, "T18's comparison
     swept it") write that phrase. On the copy, the check prints those 2 lines.
   - Fix: grep for the old phrases exactly: `part of T18's comparison` and `tuning it is T18's`.
2. **Task 5 Step 4's `TODO(T18)` grep misses a line.**
   - The grep (plan :4471-4472) says only `0011_governed_corpus.py:178` and the quotation in 0013 remain.
   - It also prints `tests/plan_n/test_migration_0013.py:114` (the assertion `"TODO(T18)" not in body`, plan :2194).
     Measured on the copy.
   - Fix: list the third line, or exclude `tests/`.
3. **Two stated outputs are wrong.**
   - Task 1 Step 4 expects `tests/plan_c` to give `307 passed` (plan :908). The copy gives `288 passed, 19 skipped`
     (307 collected).
   - The self-review says verify_handoff passes "with 27 schemas and 93 examples" (plan :5491). The real line is
     "36 accepted examples; 55 negative" = 91, as plan :904/:909 say.
4. **Stale T18 deferrals remain in live code.** Task 8 claims "every deferral to T18 in live code ... resolved or
   re-homed" (plan :5106-5107). These remain:
   - `scripts/retrieval_baseline.py:9`: "T18 measures ... against the same JSON". That is now false: the comparison
     uses a pinned digest.
   - `:48`, in `SETTINGS["minimum_rank"]`: "tuning it is T18's".
   - `:267`: "Evaluating another chunk window is T18's comparison".

   Fix: reword these lines, or list them as re-homed. Changing `SETTINGS` text changes the T17 report's prose on the
   next live run, not the answers digest, which uses only ids and ranks.
5. **The k = 3 table's forbidden rows count all five rows.**
   - `summarize(outcomes, 3)` computes `cases_without_forbidden` and `forbidden_rows` over every returned row (repo
     `retrieval_baseline.py:158,189-190`). The plan's md prints them under "k = 3" (plan :1893-1898).
   - Harmless while forbidden rows are zero (asserted), but mislabelled.
   - Fix: truncate those two metrics to `[:k]`, or label them "(all returned rows)".
6. **No database guard against a zero stored vector.**
   - Departure 2 guards the query vector (definer) and the client's answers (`checked`).
   - `app.embeddings` itself accepts an all-zero `embedding` (plan :2350-2366). pgvector then yields a NaN cosine,
     which passes `> app._min_similarity()` and sorts first. Only a superuser insert could do this today.
   - Fix: add `CHECK (public.vector_norm(embedding) > 0)` to the table. Add one line to the table test, and a live
     insert that is refused.
7. **`embed`'s refusal and failure messages can be false or incomplete.**
   - The phase-2 re-check raises `EmbedRefused("... another model digest appeared while embedding; nothing written")`
     (plan :3510-3511). skeleton then prints "EMBED: refused, nothing written" (:3605-3606), even when earlier tenants
     already committed.
   - A phase-2 Ollama failure prints only `EMBED: failed (UNAVAILABLE: ...)`. `ingest` names the tenants it wrote
     ("after writing alpha"), and `docs/retrieval.md` says "exits 1 after the tenants already written" (:4805-4806).
   - The module docstring says "a concurrent run cannot make it write a row twice" (:3408-3410). In fact a concurrent
     run makes the INSERT (no `ON CONFLICT`, :3517-3529) raise UniqueViolation, so the run exits 1.
   - Fix: carry the written tenants into the error, as `IngestInterrupted` does, and print them. Use
     `ON CONFLICT DO NOTHING` (counting only inserted rows), or lock the tenant row as ingestion does.
8. **No test that Ollama is untouched when the run's asset type fails.**
   - Ruling 4's order puts the embedding after asset-sim. The tests prove the handle-first half (plan :3963-3968) and
     the unit order resolve → scope → search (:4106).
   - No test has an asset-sim failure or `ASSET_TYPE_OUT_OF_SCOPE` with a `FakeEmbedder` and asserts
     `verified == 0 and texts == []`. Add one parametrized test.
9. **Two Ollama URL variables, one undocumented.**
   - `docs/runbooks/dev-topology.md:59-65` documents `OLLAMA_BASE_URL_HOST`/`_CONTAINER` as the host processes' Ollama
     URL.
   - The plan adds `OPS_OLLAMA_URL` (as ruled) but does not mention it there.
   - Fix: add one row and one sentence ("mcp-read and `skeleton.py embed` read `OPS_OLLAMA_URL`; the worker's T19 path
     reads ...").
10. **SESSION_STATE's "Exact next step" and "Repository" lines stay stale.**
    - `SESSION_STATE.md:1306-1335` still says "write Plan M for T16". Its walking-skeleton commands lack
      `skeleton.py embed`. The **Repository** line still names `plan-m`.
    - Task 8 edits neither.
    - Fix: add `uv run python scripts/skeleton.py embed  # after ingest (T18)` to the command block, and update both
      sentences.
11. **The answered-empty comparison mixes a tuned threshold with an untuned one, and the md does not say so.**
    - Vector's threshold is the largest value that keeps every hit (ruling 6). Lexical keeps 0.25 (ruling 9).
    - Applying ruling 6's own rule to the recorded lexical ranks gives 0.75, with 27/27 and 17/20 (my simulation).
    - So part of the 15/20 → 18/20 difference comes from the tuning, not the method. The lexical note
      (plan :1943-1946) should say this in one sentence.
12. **Some public methods have no docstrings.** `OllamaEmbedder.verify`, `embed` and `aclose` (plan :1172-1187) lack
    them. CODE_COMMENTS rule 9 asks for one on every public function, and the Protocol's docstrings do not travel.
13. **The md prints only part of the vector sweep.** It prints the 0.05 steps and 0.50-0.80 (plan :1937-1942), while
    ruling 6 says "report the whole sweep". The JSON has all of it, but the md introduces the table as "The sweep below
    re-applies it". Fix: say "(every 0.05, and every 0.01 from 0.50 to 0.80; the JSON holds all 100)".

### What I verified mechanically

- **Copy and replay.**
  - I made a `git archive` of HEAD (6ba15e5) into `scratchpad/plann/critic1/copy` and wrote my own applier
    (`critic1/apply.py`).
  - It parses every "Create `path`:" and every "Edit n (`path` ...), replace: / with:" block.
  - Result: 104 edits and 15 creates across Tasks 1-8. Each was applied task by task, and steps were applied in
    step order to check the red states. Every edit's old text occurred exactly once. No create overwrote an existing
    file. No fence was nested.
- **Per-task gates** (`critic1/gates.py`: the repo's locked venv, the copy's sources first on PYTHONPATH, cwd = the
  copy).
  - ruff check and ruff format were clean after every task, and mypy strict (`--no-incremental`, 8 members) gave "no
    issues".
  - The 13 git-dependent failures (12 `plan_a/test_verify_handoff.py`, 1 `plan_b/test_text_hygiene.py`) were the same
    at baseline and at every task.
  - Pytest, counting those 13 failures as passes:
    - baseline: 1372 / 205;
    - Task 1: 1399 / 205;
    - Task 2: 1408 / 205;
    - Task 3: 1419 / 209;
    - Task 4: 1421 / 213;
    - Task 5: 1429 / 213;
    - Task 6: 1429 / 214;
    - after Tasks 7-8 edits: 1429 / 214.

    Every figure equals the plan's. `tests/plan_n` gave 52 passed. The live counts follow by the plan's arithmetic;
    I did not run them.
- **Red steps.**
  - Task 1: two collection errors, `cannot import name 'embeddings'`.
  - Task 2: `cannot import name 'retrieval_comparison'`.
  - Task 3: the `REVISIONS` module-level AssertionError.
  - Task 4: `cannot import name 'embed'`.
  - Task 5: 7 failed, 8 passed. These are failures, not errors, and the three tests the plan names pass early.
- **The named step runs pass.**
  - Task 3 Step 3: 389 passed.
  - Task 4 Step 2: 17 passed.
  - Task 5 Step 2: 371 passed.
  - `tests/plan_l/test_retrieval_baseline.py` after Task 2 Step 2: 5 passed.
- **Schemas.**
  - `scripts.build_schemas` printed exactly "26 schema documents (20 contracts, 6 tool inputs); 91 examples (36 valid,
    55 invalid)".
  - Only the new schema, its two examples and `index.json` changed.
  - The SHA-256 of `search_procedures.input.schema.json` (51277441…58b9) and of `tool-result.schema.json`
    (c4e6f39b…466a) are unchanged after Task 5.
  - `verify_handoff.py --reference-code --manifest --contracts` gave PASS ×8 on the final copy.
- **0013 SQL** (`critic1/render.py`).
  - The printed search body and the printed `_min_similarity` body are byte-identical to the rendered ones.
  - The 0012 → 0013 diff is exactly three hunks: `v_incomplete`, the argument rule replacing the
    `VECTOR_MODE_UNAVAILABLE` block, and the vector branch after `retrieved_at := v_now`.
  - The branch's `latest`/`effective`/`permitted` text equals the lexical branch's (the unit test passes).
  - `SEARCH_ARGS` equals `privileges.DEFINER_FUNCTIONS` and 0012's `SEARCH_ARGS`.
  - Upgrade and downgrade statement lists match the unit tests.
  - The SQLAlchemy bind scan is clean for 0013.
- **Pin script.** Run against local Ollama (read-only), it printed
  `PIN: nomic-embed-text 0a109f42…e59f dimension 768 on Ollama 0.40.4`. `/api/version` gives 0.40.4, and `/api/tags`
  gives the same digest with `embedding_length` 768 and `context_length` 2048.
- **Threshold rule.** `python -m scripts.retrieval_comparison threshold` on the copy against local Ollama
  reproduced 0.68 at 26/27, 18/20; 0.69 at 25/27, 19/20; `CHOSEN: 0.68`.
  - The lowest similarity of any labelled hit is 0.6897 (A22), then 0.6921 (B19) and 0.6964 (A04). That leaves a
    margin of about 0.0097 above 0.68, far wider than float32 effects.
  - No candidate lies within 2e-4 of 0.68.
- **float32.** Emulating pgvector 0.8's float accumulators (`critic1/margins.py`, `f32diff.py`):
  - the largest |pg − double| cosine gap was 1.2e-6, well inside the exactness test's 1e-5;
  - the ordered top-8 above 0.68 was identical in float32 and double for all 47 queries;
  - the only near-tie under 1e-5 is B16 at 0.537 (4.9e-7 apart), below the threshold, as Review Focus 3 says.
- **Context window.** The longest section is 146 tokens and the longest window 407, against `context_length` 2048.
  Ollama does not silently truncate anything here.
- **Comparison simulation** (`critic1/simulate.py`). This takes lexical answers from the committed T17 JSON and vector
  answers by Python ranking of fresh embeddings, then runs `rc.comparison` and `rc.markdown`.
  - The relisted lexical digest equals `T17_ANSWERS_SHA256`. It is built from `id` and `returned` (evidence_id,
    round(rank, 6)) only, with `measured_at` excluded, per departure 5's ruling.
  - Paired results:
    - hit@5: 27 vs 26, regressed A08, p 1.0;
    - answered-empty: 15 vs 18, improved B10, B13, B17 and B18, regressed A13, p 0.375. That is
      2·(1+5)/32, the exact McNemar.
  - Repeat embeddings were identical (Δ 0.0).
  - The markdown renders, and every needle in the unit test is present.
- **Task 8 records preconditions** (`critic1/records_check.py`, read-only on the repo):
  - T18 is PLANNED with one review note;
  - R033's note ends with the asserted sentence;
  - the BUILD_BACKLOG head line occurs once;
  - `tasks.json` and the matrix round-trip byte-for-byte through `json.dumps(indent=2, ensure_ascii=False)`;
  - T23 depends only on T17 (DONE), so "Next is T23" is right;
  - T41 is M06.

  Errata start at 107 (SESSION_STATE's last is 106).
- **Report path.** `git check-ignore -v .superpowers/plann/round1-static.md` names `.gitignore:27:.superpowers/`.

### Not findings (checked)

- **The departure-1 condition holds.**
  - Phase 1 checks every tenant's stored digest before any write (plan :3492-3499), after `verify`.
  - The only way a tenant stays written before a later failure is a phase-2 model or transport failure, or a race
    (Minor 7).
  - A re-run embeds only rows still missing.
- **Departures 2-11** are implemented as ruled. These are the zero-vector `BAD_ARGUMENT` plus `checked`; the
  LEFT JOIN completeness over the call's permitted set, asset filter included; the `double precision` helper; the
  pinned digest; Python sweeps from 0.25; the generated schema plus unit validation plus `MODELS`; `Urls.ollama`
  required, with both literals edited; one 10-second `asyncio.timeout` around verify and embed; `TODO(T18)` only in
  frozen text; and `TODO(T25)` in `routing.py`.
- **SQL details.**
  - `OPERATOR(public.<=>)`, `public.vector_dims` and `public.vector_norm` are schema-qualified under
    `search_path = app, pg_temp`.
  - The uncorrelated `EXISTS (SELECT 1 FROM scored ...)` beside `jsonb_agg` is legal: the CTE is visible to the
    sub-select, and an empty `kept` still yields one row.
  - `e.embedding IS NULL` means "no row", because the column is NOT NULL.
  - The function-argument typmod is not enforced, so the explicit `vector_dims` check is needed and present.
  - The argument rule comes after the membership check and before any read.
  - The stop-word return applies to lexical only.
  - `corpus_version`, `retrieved_at`, the excerpt bound, `excerpt_cut`, the keys and the tie-break are the lexical
    branch's.
  - An empty corpus answers `[]`.
  - pgvector clamps the cosine to [-1, 1]. NaN/Inf cannot be stored, because `vector_in` rejects them.
- **Grants, RLS, ACL.**
  - `GRANTS_0013` and the live `privileges.GRANTS` row are AM-20.2's corpus cell (SA:431).
  - The revokees and policy roles equal 0011's (`0011:57-59`).
  - `embeddings` is in `RLS_TABLES` and not in `SWEEPER_ALL`.
  - `_min_similarity` is owned by `app_definer`, granted to nobody, and in `HELPER_FUNCTIONS`.
  - CREATE OR REPLACE keeps owner and ACL. Grants are re-applied anyway, and the round-trip test compares the ACL both
    ways.
  - `mcp_read` gains no table grant. The 0008 transitive scan now reaches `_min_similarity`.
  - The FK check runs as the chunk table's owner, so the worker needs no REFERENCES privilege. It needs no FORCE RLS
    bypass either.
- **Downgrade exactness.**
  - The 0012 body is restored from 0012's module (CREATE OR REPLACE, same return type), with its grants, before the
    helper and table drops.
  - The 0011 and 0012 round trips now pass through 0013's downgrade. Their snapshots exclude the helper (Edits 19-20).
  - `purge_corpus` deletes `embeddings` first. No production path deletes chunks.
- **mcp-read order and mappings.**
  1. handle (unit 1);
  2. scope (unit 2);
  3. asset type (asset-sim) and `ASSET_TYPE_OUT_OF_SCOPE`;
  4. pin load and verify and query embedding, outside any transaction;
  5. unit 3 with `mode='vector'`.

  Mappings: a missing or bad pin and a mismatch give `UNSUPPORTED_MODE`; connect, timeout and 5xx give retryable
  `UNAVAILABLE`; any other answer gives `UPSTREAM_INVALID`; the definer's `EMBEDDINGS_INCOMPLETE` gives `REFUSED`.
  `retrieval_mode` is the mode that ran. The nested `asyncio.timeout` cancellation surfaces as `TimeoutError` →
  `Unavailable`. No unit test reaches a real Ollama: every vector call passes a `FakeEmbedder`, and the plan_m
  argument test's `vector_exact` case stops at `INVALID_HANDLE`.
- **Live tests, read statically.**
  - The fixtures, helpers and signatures they import exist with the shapes used: `stage`'s `section`, `family` and
    `supersedes` keys and its `{id}:v{version}:{section}` ids; `handle_for`, `cleanup`, `refused`, `new_run`,
    `lease_for`, `read_handle`, `investigate_job`, `REQUESTERS`, `QUERIES`, `AS_OF`, `RETURNABLE_AT_AS_OF`, `Role.*`,
    `skeleton.downgrade`/`migrate`.
  - The geometry is sound. BEST is exactly 1.0. The ties are bit-identical in float32. EDGE sits 0.02 above the
    minimum, which is 1.5e-7 from float32 error. BELOW, RETIRED v1, DRAFT, LATER, the other tenant's row and the
    other-family row are excluded.
  - The clock is moved only via `test_harness` and reset in `finally`. Only `ops_test` is used.
  - Ollama is reached via loopback, `OPS_OLLAMA_URL` by default.
  - `embedded` is function-scoped and idempotent, so it re-embeds after a round trip, as `ingested` re-ingests.
  - `ALPHA-PUMP-SEAL:v2:inspection` exists. Alpha has 39 sections and beta 30, so 69.
  - The vector call in `test_mcp_read_live` runs under the client's default 5 s read timeout. That is fine: the model
    stays warm after `embedded`, and a cold load measured about 1.6 s.
- **Security.**
  - The tenant comes only from the handle. The query text is the only content sent to Ollama (loopback), and never
    the handle.
  - Error messages are fixed rule strings.
  - The worker, mcp-write and api only gain an import of `ops_core.embeddings` (httpx2 is already an ops-core
    dependency).
  - No external action, no dev-database write, no `uv.lock` change.
- **Statistics.**
  - McNemar is the exact two-sided binomial on the discordant pairs, capped at 1.
  - Wilson z = 1.959964 with denominators. Hit@5 is paired over the 27 labelled cases and answered-empty over the 20
    no-source cases.
  - k = 3 is derived from the k = 5 answers. A LIMIT-3 call returns the same prefix (deterministic ORDER BY).
  - The threshold rule uses strict `>`, as the definer does.
  - The live test re-chooses the threshold on stored vectors and compares it with the database's value.
- **Prefix proof.**
  - Unit: the exact request bodies.
  - Live: every row's `input_sha256` is checked. One stored vector is compared with a fresh prefixed embedding
    (≥ 0.9999) and the bare one (< 0.9999; measured 0.96).
  - The stored `section`/`body` are exactly `Section.name`/`.body` (`ingest.py:249-262`), so Task 2's file-based
    measurement and the stored vectors embed the same text.

---

# Round 1 — controller rulings

## Plan N round 1 — controller rulings (critic report: C:\Users\joeys\Desktop\MLOps\.superpowers\plann\round1-static.md)

Verdict REVISE, 0 Critical / 2 Important / 13 Minor. Everything is fixed; nothing parked.

### Important
- **I1 (window experiment degenerate) — fix as the critic proposes.** `window_metrics` also returns windows per tenant,
  sections per window and min/max words per window, hit@1 and MRR@5 over the labelled cases, and the threshold-0
  recall. The md paragraph and `docs/retrieval.md` state plainly that on corpus-1 every returnable version (327-343
  words) is one window and k = 5 covers every window of either tenant, so hit@5/recall@5 there measure only the
  threshold; the experiment is recorded as "whole-version embeddings vs section embeddings", and erratum 100's question
  is closed only as "evaluated on corpus-1, where the 300-word window degenerates to one window per version; the stored
  unit stays one chunk per section". A unit assertion pins 8 windows, each one whole version.
- **I2 (re-pin defeats the swap guarantee) — option 1 plus narrowed wording.** `pin_embedding_model.py` refuses (exit 1,
  nothing written) when `data/embedding-pins.json` exists with another digest (or model or dimension), saying a model
  change is a new revision that re-embeds and updates the pin in that revision; unit test with a fake transport (same
  digest → rewrite allowed or no-op, as the writer prefers; different → refused). The docs order becomes: a new
  revision re-embeds, then the pin. `docs/ARCHITECTURE.md`'s sentence names what is actually guaranteed (mcp-read refuses
  a query model that differs from the pin; the pin cannot be replaced by the script; the stored rows carry their digest
  and `embed` refuses mixing). Debt line: a read-path check of the stored rows' digest belongs to the first re-embedding
  revision (no owner yet; record it under "a model change").

### Minor — all fixed
1. Task 7 Step 5's grep: grep the old phrases exactly (`part of T18's comparison`, `tuning it is T18's`).
2. Task 5 Step 4's `TODO(T18)` grep: list the `tests/plan_n/test_migration_0013.py` line as expected (or exclude
   `tests/`), with the real expected output.
3. Wrong stated outputs: `tests/plan_c` → `288 passed, 19 skipped`; the self-review's verify_handoff line → 36
   accepted / 55 negative.
4. Stale T18 deferrals in `scripts/retrieval_baseline.py:9, :48, :267`: reword them to what T18 did (the comparison
   pins a digest of the committed answers; 0.25 measured and kept in T18; the window evaluated in T18's comparison).
   State in the plan that the T17 report's settings prose changes on its next live run while its answers digest does not.
5. k = 3 forbidden metrics: compute `cases_without_forbidden`/`forbidden_rows` over `[:k]` (check it does not change
   the T17 report's k = 5 figures — it must not, since T17 returns at most 5 rows) or label them "(all returned rows)";
   prefer the truncation.
6. Add `CHECK (public.vector_norm(embedding) > 0)` to `app.embeddings`; table test line; a live insert refused.
7. `embed` messages: carry the written tenants into the error and print them (as `IngestInterrupted`);
   `ON CONFLICT (tenant_id, evidence_id) DO NOTHING` counting only inserted rows; fix the docstring's concurrency
   sentence to what is true.
8. Add a parametrized unit test: asset-sim failure and `ASSET_TYPE_OUT_OF_SCOPE` with a `FakeEmbedder` → `verified == 0
   and texts == []`.
9. `docs/runbooks/dev-topology.md`: one row and one sentence for `OPS_OLLAMA_URL` (mcp-read and `skeleton.py embed`).
10. SESSION_STATE: Task 8 updates the "Exact next step", the "Repository" line and adds `uv run python
    scripts/skeleton.py embed  # after ingest (T18)` to the command block.
11. The md's lexical note says in one sentence that the vector threshold was tuned by ruling 6's rule while lexical
    keeps 0.25, and gives the lexical figures under the same rule (computed by the script from the recorded ranks, not
    hard-coded), so the answered-empty difference is read with that in mind.
12. Docstrings on `OllamaEmbedder.verify`, `embed`, `aclose` (CODE_COMMENTS rule 9).
13. The md's sweep table says which rows it prints and that the JSON holds the whole sweep.

All counts and expected outputs updated wherever these change them; the plan's apply-and-gate check rerun on a fresh
copy.

---

# Round 2

## Plan N, round 2: static critique

Plan: `docs/superpowers/plans/2026-10-19-first-slice-n-vector-retrieval.md` at `c9ebe7f` (5994 lines; round 0 was
`6ba15e5`). Inputs: the round-1 report (`.superpowers/plann/round1-static.md`), the controller's round-1 rulings and
departure rulings, the brief, the fact sheet, SPEC_AMENDMENTS over BUILD_SPEC, the code at `6ba15e5` (the same code tree
as `c9ebe7f`, because only the plan changed), and the round-2 form of `docs/reviews/plan-review-m-2026-10-18.md`.

**Verdict: REVISE.** I found 0 Critical, 1 Important and 4 Minor findings.

All 15 round-1 findings are fixed as ruled, with one residue. The mechanics are clean:

- Every Create and Edit applies exactly once.
- Every per-task count reproduces.
- Every red step fails the way the plan says.
- ruff, ruff format and mypy strict are clean after every task.

The one Important finding sits inside the I1 fix. The figures it adds as "the ones that see an order" are computed at
the tuned threshold. On corpus-1 they are therefore just as threshold-bound as hit@5. The fix needs about 4 lines and
one assertion.

### Round-1 verification

| Round 1 | Ruling | Status | Evidence (plan line at `c9ebe7f`; my replay) |
|---|---|---|---|
| I1 window degenerate | report shapes, hit@1/MRR@5, threshold-0 recall, plain wording, unit pin | **Fixed, with a residue (Important 1 below)** | `Window.words`/`whole_version`, `window_metrics` :2004-2057; md paragraph :2250-2268 (conditional on the two flags); `docs/retrieval.md` Edit 2 :5137-5145; `test_corpus_1s_windows_are_its_whole_returnable_versions` :1547 passes on the copy (8 windows: alpha 5, beta 3; 4-5 sections; 327-343 words; all whole versions); the live assert :5045-5046; R034 note :5617-5619 |
| I2 re-pin defeats the guarantee | option 1 + narrowed docs + debt line | **Fixed** (wording residue: Minor 3) | `replaces_another_model` :1344-1352 and the refusal in `main` :1362-1368 (exit 1, nothing written; an unreadable file counts as another); `test_the_pin_script_writes_a_pin_and_never_replaces_another_models` :588 passes (the same build rewrites, another digest is refused with the bytes unchanged, 384 dimensions is refused with no file); ARCHITECTURE :5481-5488 names what is guaranteed; the debt line is in the copy's SESSION_STATE.md:1268-1271 |
| m1 Task 7 grep | old phrases exactly | Fixed | :5524-5526; on the final copy it prints nothing (rc 1) |
| m2 TODO(T18) grep | list the test line | Fixed | :4873-4880; the copy prints exactly those three lines, at 178, 118 and 115 |
| m3 stated outputs | `288 passed, 19 skipped`; 36/55 | Fixed | measured `288 passed, 19 skipped`; self-review :5988 |
| m4 stale T18 lines | reword the 3 lines; say what happens to the T17 report | Fixed | Task 2 Edits 1, 2 and 9 :1624-1652, :1777-1790, plus the sentence :1792-1797; no other live-code T18 deferral remains (grep of the copy's `*/src` and `scripts`) |
| m5 forbidden within top k | truncate | Fixed | Edits 6 and 8 :1701-1775; new assertions in `test_k3_counts_only_the_top_three`; T17's committed figures are unchanged (recomputed from the committed JSON: 0/122 at k = 5, equal to the committed `forbidden_rows`; 47/47 cases without forbidden rows) |
| m6 zero-vector CHECK | table CHECK + unit + live | Fixed | :2663, unit :2446, live :3430-3431 (autocommit `app_conn`, so the aborted statement does not poison the rest; CHECK fires before the FK trigger) |
| m7 `embed` messages | written tenants, ON CONFLICT, docstring | **Fixed in `ops_core.embed`** (residue: Minors 1 and 2) | `EmbedInterrupted`, `EmbedRefused.written` :3755-3772; the wrap :3843-3858; ON CONFLICT with `rowcount` :3878-3895; skeleton printing :3962-3991; `test_embed_command.py` covers both new lines |
| m8 Ollama untouched on an asset-sim failure | parametrized test | Fixed | :4383-4402; red in Task 5 Step 1 (`'UNSUPPORTED_MODE' == 'UNAVAILABLE'`/`'ASSET_TYPE_OUT_OF_SCOPE'`), green after Step 2 |
| m9 `OPS_OLLAMA_URL` in dev-topology | row + sentence | Fixed (one inaccuracy: Minor 4) | Edit 17 :5409-5424 |
| m10 SESSION_STATE next step / repository / commands | three edits | Fixed | Task 8 Edits 3, 8 and 9 :5695-5831; T23 is the only PLANNED task whose dependencies are all DONE once T18 is (computed from `handoff/tasks.json`) |
| m11 tuned vs untuned | state lexical under the same rule, computed | Fixed | `LEXICAL_RULE_GRID` :1855, `lexical_rule` :2060, md :2225-2232; recomputed from the committed T17 answers: 0.79, hit@5 27/27, answered-empty 17/20 (0.80 drops to 25/27) |
| m12 docstrings | verify/embed/aclose | Fixed | :1258-1277 |
| m13 sweep table scope | say which rows + JSON holds 100 | Fixed | :2205-2209; md needle asserted |

The departure conditions still hold:

- **Departure 1.** Phase 1 checks every tenant's digest before any write. A tenant stays written before a later failure
  only through a phase-2 failure, and `EmbedInterrupted` now names it.
- **Departure 5.** `answers_digest` hashes only `id` and (`evidence_id`, `rank`). Recomputed over the committed JSON, it
  equals `T17_ANSWERS_SHA256`.

### Critical

None.

### Important

#### 1. The window experiment's "figures that see an order" are computed at the tuned threshold, so on corpus-1 they are as threshold-bound as hit@5. The real ranking figure is not reported.

- **Where.**
  - `window_metrics` builds `found` at `threshold` (:2019). hit@1 (:2053) and MRR@5 (`reciprocal`, :2032-2034) are
    computed over `found`. Only recall is also computed over `open_` (threshold 0, :2020 and :2051).
  - Its docstring says "hit@1 and MRR@5 are the figures that still see an order" (:2016).
  - The md says "read this as whole-version embeddings against section embeddings, with hit@1 and MRR@5 as the
    figures that see an order" (:2263-2266).
  - The pre-measurement says "with hit@1 and MRR@5 as its ranking figures" (:283-284).
  - The unit test asserts hit@1 at the threshold (:1568).
- **Measured** (`critic2/sim3.py`; real local Ollama embeddings of the 8 windows and 47 queries, through the copy's own
  `window_metrics`).
  - At 0.68, the answerable queries keep 0 windows (4 queries), 1 window (17), 2 windows (4) and 3 windows (2). The
    result is hit@1 = hit@5 = 23/27, and MRR@5 = recall@5 = 0.8519, all four driven by the same 4 queries that kept
    nothing.
  - At threshold 0 (the ranking alone), hit@1 is 27/27 and MRR@5 is 1.0.
  - `recall_at_k_threshold_0` is 1.0 by construction whenever `k_covers_every_window` holds, because the top 5 is every
    window. It tells the reader nothing on this corpus.
- **Failure scenario.** The DoD report prints "hit@5 23/27; hit@1 23/27; MRR@5 0.8519" and calls hit@1 and MRR@5 the
  ranking figures. A reader (T23 or T25) concludes that whole-version embeddings put the right version first in 23 of
  27 cases. In fact they put it first in all 27, and the four misses are threshold misses. This is I1's failure mode
  again (a figure presented as measuring something it does not), introduced by the fix.
- **Fix** (a few lines, no count change).
  - Compute `hit_at_1` and `mrr_at_k` over `open_` (threshold 0), or add `hit_at_1_threshold_0` and
    `mrr_at_k_threshold_0` and print those as the order figures.
  - Say in the md that `recall_at_k_threshold_0` is 1.0 by construction when k covers every window, or drop it when
    `k_covers_every_window` holds.
  - Adjust :1568 and :2016, the md sentence and :283-284.
  - On the unit fixture, the threshold-0 figures are hit@1 1/2 (A2's top window at 0 is W1, which does not hold y) and
    MRR@5 (1 + 1/2)/2 = 0.75. Assert those.

### Minor

1. **`skeleton.embed`'s docstring still says an unreachable Ollama writes nothing** (:3946-3949: "Exit 1 with the
   reason, and nothing written, when the pin is missing or does not match, Ollama cannot be reached, or ...").
   - Since round 1, an Ollama failure after alpha committed prints `... after writing alpha`. The module docstring
     (:3733-3737) and `docs/retrieval.md` (:5219-5222) say so; this docstring contradicts them (CODE_COMMENTS
     accuracy).
   - Fix: "... and nothing written when the pin is missing or does not match or a tenant holds another digest's
     embeddings; a failure while writing names the tenants already written".
2. **`EmbedInterrupted`'s construction is untested.** `test_embed_command.py` hands skeleton a prebuilt
   `EmbedInterrupted(("alpha",))` (:3648-3653, :3675-3678). Nothing exercises `embed.embed`'s own wrap (:3846-3854):
   the `written` tuple, the bare re-raise when nothing committed, and `EmbedRefused(..., written)`.
   - A regression there would print "nothing written" after a commit, which is the very message Minor 7 fixed, and no
     test would see it.
   - Fix: one live test in `test_vector_retrieval_live.py`. Use two probe tenants, each with one staged chunk, and an
     embedder whose second `embed` call raises `embeddings.Unavailable`. Assert that `EmbedInterrupted.written ==
     ("a",)`, that the cause is `Unavailable`, and that tenant a's row exists and b's does not. Live count +1.
   - Or record the gap in the plan.
3. **The model-change path in the documents cannot be executed as written, and one bypass is unqualified.**
   - The docs say a model change is "a new revision that re-embeds every chunk and then updates the pin" (:5207-5208;
     also :1303, :1367, :5486-5487, :5904).
   - The shipped `embed` cannot re-embed under a new model before the pin changes. It verifies the installed model
     against the pin first (`PinMismatch`) and refuses any tenant holding another digest. The worker cannot delete
     rows either.
   - The only way to change the pin is to delete `data/embedding-pins.json` and re-run the script. That also bypasses
     the I2 refusal, with the old rows still in place, so mcp-read would then compare two models' vectors.
     ARCHITECTURE's "the pin cannot be replaced by `scripts/pin_embedding_model.py` with another model's" (:5483-5484)
     holds only while the file exists.
   - Fix (wording only): "that revision replaces the stored rows and the pin together (the shipped `embed` checks the
     pin first and refuses a mixed store, so it brings its own path); deleting the pin file and re-running the script
     outside such a revision re-opens the mixed-model case".
4. **`dev-topology.md` says mcp-read and `skeleton.py embed` ask `/api/version`** (:5421-5422: "asking only
   `/api/tags`, `/api/version` and `/api/embed`").
   - Neither does: `query_embedding` and `embed.embed` call only `verify` (`/api/tags`) and `embed` (`/api/embed`).
     Only the pin script and the comparison call `version()` (grep of the copy).
   - ARCHITECTURE's row (:5462) and section 11 say `/api/tags` and `/api/embed`, so the two documents disagree.
   - Fix: drop `/api/version` from the sentence.

### What I ran

All runs used the repository's locked venv with the copy's member sources first on PYTHONPATH, scripts run as
`uv run python -I <script> < /dev/null`. There was no database, Keycloak or service connection, no live pytest and no
skeleton.py. Local Ollama was used read-only (`/api/version`, `/api/tags`, `/api/embed`).

- **Copy.** I ran `git archive 6ba15e5` into `scratchpad/plann/critic2/copy`.
- **Applier.** My own applier (`critic2/apply2.py`) parses every `Create \`path\`:` and every `Edit n (\`path\`...),
  replace:`/`with:` of the plan at `c9ebe7f`: 112 edits and 15 creates. It applies them by plan line, task by task,
  stopping at each Step 1 for the red state.
  - Every old text occurred exactly once, and no create overwrote a file.
  - The one exception is Task 8 Edit 3 (:5695). Its old text is the first part of SESSION_STATE.md's line 18, not a
    whole line, so a whole-line match finds 0. As a substring it occurs once, and I applied it that way (see Not
    findings).
- **The pin file** was written from the plan's printed JSON (:1385-1392). Its digest equals `/api/tags`'s
  (`0a109f42…e59f`), and `/api/version` is 0.40.4.
- **Per-task gates** (`critic2/gates2.py`): ruff check "All checks passed!", ruff format --check clean, mypy
  `--no-incremental` on the 8 members "no issues", after every task. Pytest, counting the 13 git-only failures (12
  `plan_a/test_verify_handoff.py`, 1 `plan_b/test_text_hygiene.py`) as passes:

  | After | Measured | Plan |
  |---|---|---|
  | baseline | 1372 / 205 | 1372 / 205 |
  | Task 1 | 1400 / 205 | 1400 / 205 |
  | Task 2 | 1411 / 205 | 1411 / 205 |
  | Task 3 | 1422 / 209 | 1422 / 209 |
  | Task 4 | 1424 / 213 | 1424 / 213 |
  | Task 5 | 1434 / 213 | 1434 / 213 |
  | Task 6 | 1434 / 214 | 1434 / 214 |
  | Tasks 7-8 | 1434 / 214 | 1434 / 214 |

  - `tests/plan_n` gave 57 passed: pins 10, embeddings 15, comparison 11, migration 9, embed command 2, mcp-read
    vector 10.
  - Task 1 Step 6 gave 25 passed. `tests/plan_c` gave 288 passed, 19 skipped. `test_retrieval_baseline.py` gave 5
    passed after Task 2 Step 2.
  - Task 4 Step 2's named run gave 17 passed. Task 5 Step 2's named pair gave 17 passed.
- **Red steps.**
  - Task 1: two collection errors, `cannot import name 'embeddings'`.
  - Task 2: `cannot import name 'retrieval_comparison'`.
  - Task 3: the module-level `REVISIONS` AssertionError in both files.
  - Task 4: `cannot import name 'embed'`.
  - Task 5: 9 failed, 8 passed. These are failures, not errors. The two new parametrized cases fail on the code.
- **Schemas.**
  - `scripts.build_schemas` printed "26 schema documents (20 contracts, 6 tool inputs); 91 examples (36 valid, 55
    invalid); index.json version 1.3.3".
  - `diff -r` against the repository shows only the new schema, its two examples and `index.json`.
  - `search_procedures.input.schema.json` (51277441…58b9) and `tool-result.schema.json` (c4e6f39b…466a) are
    unchanged.
  - `verify_handoff.py --reference-code --manifest --contracts` gave PASS ×8 on the final copy.
- **Lexical rule and T17 invariance** (`critic2/lex2.py`, committed T17 JSON only).
  - The digest equals `T17_ANSWERS_SHA256`. `lexical_rule` gives 0.79 with 27/27 and 17/20.
  - `summarize` at k = 5 gives forbidden 0/122, the committed figure; k = 3 gives 0/85.
- **Simulation** (`critic2/sim2.py`).
  - Real embeddings of the returnable sections, the 47 queries (twice) and the 8 windows. Python ranking stood in for
    the definer, and the committed T17 answers served as lexical.
  - CHOSEN 0.68. Paired hit@5 27 vs 26 (A08 regressed, p 1.0). Answered-empty 15 vs 18 (B10, B13, B17, B18 improved,
    A13 regressed, p 0.375).
  - Window 8 (alpha 5, beta 3), 4-5 sections, 327-343 words, recall@5 0.8519, hit@5 23/27, 19/20 answered empty,
    forbidden 0.
  - `comparison` and `markdown` render the new fields: "forbidden sections among the top-k rows", the sweep sentence,
    the lexical-rule sentence and the conditional window sentence.
  - `critic2/sim3.py` gave the Important finding's figures.

### Not findings (checked)

- **Task 8 Edit 3's partial-line anchor.**
  - The old text ends at "PR #12 into `main`;" mid-line. It is exact current text and occurs once, so an exact
    substring replace (the plan's stated method, and the Edit tool's) works. Only a whole-line matcher misses it.
  - The resulting line reads correctly: "branch `plan-n` off `plan-m` (Plan N executed, not pushed; `plan-m`: Plan M
    executed, …".
- **`ON CONFLICT (tenant_id, evidence_id) DO NOTHING`.**
  - The worker's SELECT is what an explicit conflict target needs (PostgreSQL marks the arbiter columns for SELECT), so
    Review Focus 7 is right.
  - Under FORCE RLS only the INSERT WITH CHECK applies; DO NOTHING applies no SELECT policy.
  - Two concurrent runs insert in the same `evidence_id COLLATE "C"` order, so the second waits on the first's tuple
    and then does nothing: no deadlock and no UniqueViolation.
  - The FK's KEY SHARE locks on the chunk rows are compatible with each other.
  - `rowcount` is 0 or 1 per statement. A tenant that committed with 0 new rows is correctly not listed as "written".
- **`CHECK (public.vector_norm(embedding) > 0)`.**
  - It is legal among the column definitions. It is evaluated before the FK's AFTER trigger, so the live test's insert
    raises CheckViolation even though its row would also pass the FK.
  - The stored expression needs EXECUTE on the function, not USAGE on `public`, and nothing revokes either.
  - It goes with `DROP TABLE` on downgrade. No round-trip snapshot lists the table's constraints.
  - A float32-underflowing near-zero vector would pass `vector_norm` (computed in double) and still give a NaN cosine.
    That is not reachable from nomic's unit-norm output, and the client's `checked` already refuses exact zeros.
- **The pin script.**
  - `probe` reads the dimension from the raw `_json` answer, not `embed`, so a 384-dimension answer reaches the
    dimension refusal instead of `Malformed`.
  - The unit test never opens a socket: `settings.urls()` needs no environment.
  - A same-build re-run rewrites `ollama_version`/`probed_at` only.
- **`choose_threshold`'s change to `rows[0]`** is identical for the vector grid (first value 0.0). For the lexical rule
  grid it means "at 0.25", the stored minimum, as the docstring says. hit@k is monotone non-increasing in the threshold
  over a fixed candidate list, so "largest value keeping the first value's hit@k" is well defined.
- **The lexical-note sentence is unconditional** ("part of the answered-empty difference … is the tuning"). It is
  still always true, because the live test asserts that the lexical answers equal T17's digest, which fixes the rule's
  output at 0.79 and 17/20.
- **mcp-read order and mappings** are unchanged from round 1 and re-read in the copy: handle → scope → asset-sim → type
  check → pin and embedding under one 10 s budget → the third unit. The new test proves the third step precedes the
  fourth.
- **Live tests, read statically.**
  - The zero-vector insert uses the superuser on an autocommit connection, against `ops_test` only.
  - The comparison test's new assertion (`every_window_a_whole_version`, 8 windows) matches the measured corpus.
  - The clock handling (harness, reset in `finally`) and the `embedded` fixture are unchanged.
- **The T17 report.**
  - Its committed `.md`/`.json` keep the old "tuning it is T18's" prose until a future run is committed. The plan says
    so (:1792-1797), and nothing compares the regenerated report with the committed one; the comparison uses only the
    answers digest.
  - "Every deferral to T18 in live code" holds: the copy's `*/src` and `scripts` have none left.
- **Task 8 records.** `handoff/` is unchanged since round 1's precondition check (the only diff `6ba15e5..c9ebe7f` is
  the plan). Errata 107-111 are as before. The new SESSION_STATE "Exact next step" names T23 correctly.
- **Statistics.** McNemar, Wilson, the pairing and the k = 3 prefix are unchanged and reproduce (p 1.0 and 0.375).
  Forbidden counts within the top k leave every T17 figure at k = 5 as committed.

---

# Round 2 — controller rulings

## Plan N round 2 — controller rulings (critic report: C:\Users\joeys\Desktop\MLOps\.superpowers\plann\round2-static.md)

Verdict REVISE, 0 Critical / 1 Important / 4 Minor. All round-1 findings verified fixed. Everything below is fixed;
the fixes are small and local, so the controller checks the diff instead of a third round.

- **I1 — fix.** hit@1 and MRR@5 of the window experiment are computed at threshold 0 (the ranking alone), labelled
  so; the threshold-0 recall is dropped (1.0 by construction when k covers every window) — or kept only with that
  sentence. The thresholded hit@5/recall@5/answered-empty stay, labelled "at the section-tuned 0.68". The unit fixture's
  expected values change accordingly (critic: 1/2 and 0.75).
- **Minor 1 — fix** `skeleton.embed`'s docstring to what `EmbedInterrupted` does (tenants already written stay written
  and are named).
- **Minor 2 — fix** with a live test in `ops_test`: an embedder that fails on the second tenant → `EmbedInterrupted`
  naming the first tenant; a rerun with a working embedder completes the second and writes nothing for the first.
- **Minor 3 — fix the wording** everywhere it appears: a model change is a new revision that removes the stored
  embeddings (or moves them aside), after which the pin is replaced (the script refuses while the old pin exists, so
  the revision's commit deletes or replaces the pin file as a reviewed change) and `embed` runs again. ARCHITECTURE says
  that the refusal guards against a silent re-pin by the script, and that replacing the committed pin file by hand is a
  reviewed repository change, not something the guarantee prevents.
- **Minor 4 — fix** dev-topology Edit 17: `/api/tags` and `/api/embed` only (the pin script alone calls `/api/version`).

Update counts/expected outputs the fixes change; re-run the apply-and-gate check on a fresh copy.

---

# Controller check of the round 2 fixes (a68f67e)

The diff c9ebe7f..a68f67e touches only the plan. The window experiment's `hit_at_1_threshold_0` and
`mrr_at_k_threshold_0` replace the thresholded figures, the threshold-0 recall is gone and the thresholded figures are
labelled as measured at the section-tuned threshold; the unit fixture asserts 1/2 and 0.75. `skeleton.embed`'s
docstring names `EmbedInterrupted`; a live test fails the second tenant and re-runs. The model-change order reads the
same everywhere (a revision removes the stored embeddings, the pin is replaced as a reviewed change, `embed` runs
again), and the runbook names `/api/tags` and `/api/embed` only. Accepted.

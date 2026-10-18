# Plan M review record — T16 read tools, asset_scope and asset-sim

Plan: `docs/superpowers/plans/2026-10-18-first-slice-m-read-tools-asset-sim.md` (branch `plan-m`; plan commit c5ccbc2,
round 1 fixes 5d2509c, round 2 fixes in the commit that adds this record). Inputs:
`docs/superpowers/research/2026-10-18-plan-m-inputs.md` and the controller's rulings brief (reproduced below).

How the rounds ran. The plan writer built the whole slice in a scratch copy of the tree and generated the plan's code
blocks from those tested files. A script then applied every Create, Replace and Edit step of the plan, task by task,
to a fresh `git archive` copy and compared the result with the scratch build. The writer and the critics checked each
task with ruff, ruff format, mypy strict and the non-live pytest, using the copy's sources first on `PYTHONPATH` and the
repository's locked environment. They also ran the red steps and `uv lock --offline` on the copy. Each round was one
static adversarial review that repeated that apply on a fresh tree. A scratch copy has no database credentials and no
git checkout. So every live count in the plan is arithmetic until execution, and 13 tests that need a git checkout
fail in a copy and are added back to the counts.

Round 1: REVISE, 2 Critical, 2 Important, 7 Minor. All 11 were fixed in 5d2509c, and nothing was parked. The dev
counts after Tasks 1-6 became 1282, 1302, 1327, 1332, 1344 and 1344 passed (196, 199, 203, 204, 205 and 205 skipped),
and the live counts 1457, 1480, 1509, 1515, 1528 and 1528 (21 skipped). Round 2: ACCEPT, 0 Critical, 0 Important,
5 Minor. All five were fixed with the commit that adds this record, without a third round and with no count change.

No agent connected to any database, Keycloak, service or network in these rounds, and no `.env` or secret file was
opened. Process slips: in round 1 the critic once launched `uv run python -I - < /dev/null` inside a compound shell
command. Its stdin was empty, so nothing executed, and it was stopped by task ID. Round 2 had none.

---

# Controller brief (rulings before round 1)

## Plan M brief — controller rulings for T16 (read tools, asset_scope, asset-sim)

Branch `plan-m` (= `main` 66d6833 + records 4be745a + fact sheet cd6a5b3). Fact sheet:
`docs/superpowers/research/2026-10-18-plan-m-inputs.md` (FS). Errata continue at **103**. Requirements: R028, R029
(T16's own); R131's read half completes (`asset_scope` joins). Gates at start: dev 1270 / 191; live 1440 / 21;
verify_handoff 0.

Principle: T16 builds the **asset half of mcp-read and its destination**: asset-sim as a seventh process, the
`asset_scope` definer, the two asset tools, the requester's membership re-check at read time, and the worker's
fail-closed discovery and result validation (R029). Vector search (T18), the worker's own calls to the asset tools and
the evidence bundle (T20), recording the status observation for the grant's freshness check (T21), containers and
the Docker network tests (T30) stay with their owners.

### Rulings (one per FS question)

1. **Vector mode (FS Q1) — defer to T18, option (a).** No embedding model is pinned (T02 pending), no `embeddings`
   table exists, and T18 owns the prefix test. mcp-read keeps answering `vector_exact` with `UNSUPPORTED_MODE`; the
   `TODO(T16)` markers (`server.py:207`, `routing.py:362`) become `TODO(T18)`. **Erratum 103**: T16's instruction
   clause "vector mode: mcp-read computes the nomic search_query embedding" and review note `tasks.json:771` move to
   T18 (T18 creates the embeddings, the translation `vector_exact` → `mode=vector`, and mcp-read's query embedding).
   Add the note to T18's review_notes in the close-out.
2. **`asset_scope` (FS Q2).** Signature `app.asset_scope(p_raw_handle text, p_client_azp text)`, granted to
   `mcp_read` only (**erratum 104**: SA:460 gains `client_azp`, as errata 83/93 did for the other definers). It runs
   `_authority`, `_resolve_handle(…, 'read')`, sets `app.tenant_id` transaction-locally, runs the membership re-check
   (ruling 7), and returns one row `(run_id uuid, tenant_id uuid, asset_id text, start_at timestamptz, end_at
   timestamptz, as_of timestamptz)` where `as_of = app.current_time()` read after the lease lock (SA:157). It does not
   check the tool allowlist (mcp-read does that from `resolve_invocation`, as for `search_procedures`; ruling 15).
   Created in revision **0012**.
3. **Revision `0012_asset_scope` (FS Q3).** It carries: `asset_scope` + its grant; `search_procedures_scoped`
   re-created with `DROP FUNCTION` + `CREATE` (the return type changes) and re-granted to `mcp_read`, now returning
   `(corpus_version text, retrieved_at timestamptz, results jsonb)` with `retrieved_at` = its `v_now`, the membership
   re-check (ruling 7) and the excerpt change (ruling 11); everything else in its body byte-identical to 0011 (ranking,
   filters, `_min_rank`). Exact downgrade to 0011 (re-create 0011's function text from 0011's frozen tuple). mcp-read
   asserts 0012 at start (a new startup marker in `persistence`, following the `GOVERNED_CORPUS` rule; update or
   replace that marker in the same commit). mcp-read stamps `retrieved_at` per row and the envelope's `observed_at`
   from the definer's instant for search, and from `asset_scope`'s `as_of` for the asset tools; envelopes for refusals
   before any database unit keep the wall clock. No assets table. Owner input: migrate dev to 0012.
4. **asset-sim's data (FS Q4) — derived, no corpus change.** corpus-1 stays locked and unchanged (T41 labels against
   it). asset-sim loads `data/corpus/assets.json` through `ops_core.corpus.load_assets` and the UUIDs from `meta.json`,
   read-only at start, and derives everything else by a fixed rule documented in `asset-sim/README.md` and
   `docs/runbooks/asset-sim.md`:
   - alert → contract: `alert_id` = meta's uuid; `occurred_at` = `raised_at`; `code` = `kind`; `message` = a fixed
     template from severity, kind and the asset's name (≤500 chars); `revision` as authored.
   - status as of an instant T: `state = "warning"` if the asset has an alert with severity `warning` or `critical`
     and `T - 24h <= raised_at <= T`, else `"normal"`; `revision` = the highest revision among the asset's alerts with
     `raised_at <= T`, or 1; `observed_at = T`; `data_source = "synthetic"`. `unavailable` only through the test-profile
     fault hook (ruling 6).
   - T is the `as_of` instant mcp-read forwards (ruling 8): asset-sim has no clock of its own (BS:405 "deterministic
     under an injected clock").
   The writer checks the rule against corpus-1's alerts and states, in the plan, A17's and B22's state at the
   baseline clock 2026-10-16T12:00Z and at one instant inside an alert window.
5. **Process (FS Q5).** Port **8091**, `OPS_ASSET_SIM_PORT` (default 8091) and `OPS_ASSET_SIM_URL` (default
   `http://127.0.0.1:8091`, a new `settings.Urls.asset_sim`). Skeleton: seven processes, `asset-sim` first (before
   mcp-read); update `tests/plan_e/test_skeleton_cli.py`. incident-sim's shape (`__main__.py`, `production_app()`,
   FastAPI + uvicorn deps in `asset-sim/pyproject.toml`, `redaction.install()`, Windows selector loop). `/health/ready`
   = the asset data loaded and the JWKS fetched. Dockerfile and per-directory `tests/` → T30 debt line, as for the other
   services; unit tests in `tests/plan_m`.
6. **Authentication (FS Q6).** `TokenVerifier(issuer=kc.issuer, audience="asset-sim", allowed_azp={"ops-mcp-read"},
   jwks_url=kc.jwks_url, token_type="Bearer")`; `WrongAudience` → 403, other `TokenRejected` → 401 with
   `WWW-Authenticate: Bearer` (incident-sim's mapping). DoD 2's live test presents a worker token (`ops-worker`), an
   mcp-write token (`ops-mcp-write`, aud incident-sim), an "api" token = a persona token from `ops-dev-direct` (aud
   `ops-api`, erratum 81's browser stand-in) and the `ops-view-users` service-account token: each is refused, none
   reaches data; an `ops-mcp-read` token is accepted. mcp-read gets a `WorkloadTokenSource` for `ops-mcp-read`
   (`settings.read_secret("kc_client_secret_ops_mcp_read")`, as mcp-write does). Fault hooks only under
   `PROFILE=test` (incident-sim's guard): `unavailable` state, a 503, a malformed body, a slow response — enough for
   the R029/R028 failure tests; never routable outside the test profile (tested).
7. **R028 membership re-check (FS Q7).** Inside the definers (`asset_scope` and `search_procedures_scoped` in 0012),
   after the handle resolves and `app.tenant_id` is set: the run's `requester` must hold an **active** membership in
   the run's tenant with role `requester`; otherwise the same single `OC008` handle refusal (`INVALID_HANDLE` at the
   tool, one message, SA:355): no distinct code that would tell the caller why. Issuer: the writer finds how the API
   admits a run's requester (the membership row it checked) and matches the same key; if the issuer cannot be
   recovered from the run, match `(tenant_id, subject = runs.requester, role = 'requester', active)` and propose that
   as **erratum 105**. `resolve_invocation`'s output does not change (erratum 77 stays). Live test: revoke the
   requester's membership → all three tools refuse on the next call.
8. **Forwarding (FS Q8).** mcp-read → asset-sim over HTTP with its own workload token, never the handle (BS:364).
   Routes: `GET /assets/{asset_id}` (internal: `{asset_id, asset_type}`, for ruling 12), `GET
   /assets/{asset_id}/status`, `GET /assets/{asset_id}/alerts?start_at=…&end_at=…&limit=…[&cursor=…]`. Context headers
   `X-Ops-Tenant-Id` (UUID, from `asset_scope`) and `X-Ops-As-Of` (RFC 3339 `Z`, from `asset_scope`). mcp-read refuses
   an `asset_id` argument that differs from the run's own asset **before** calling asset-sim (error code
   `ASSET_OUT_OF_SCOPE`, `retryable: false`); asset-sim independently answers 404 for an asset that is unknown or
   belongs to another tenant (the same answer for both: no existence oracle), which mcp-read maps to `NOT_FOUND`.
   Both layers are tested (R028 "Alpha requests B22": through mcp-read and directly at asset-sim with alpha's tenant).
9. **Interval (FS Q9).** mcp-read uses only the run's `[start_at, end_at)` from `asset_scope`; a caller `start_at` /
   `end_at` that differs (compared as instants) is refused `INTERVAL_OUT_OF_SCOPE`, `retryable: false`. asset-sim
   returns alerts with `start_at <= occurred_at < end_at` **and** `occurred_at <= as_of` (no future alerts).
10. **Cursor (FS Q10).** Order `(occurred_at, alert_id)`. `next_cursor` is an opaque base64url token encoding the last
    returned key and a SHA-256 of `(tenant_id, asset_id, start_at, end_at)`; asset-sim refuses a cursor whose binding
    does not match the request (400 → `INVALID_CURSOR`). No secret is needed: a cursor only selects a position inside
    the already-filtered set. `next_cursor` non-null and the envelope's `truncated: true` exactly when more alerts
    remain after `limit`. Tested with `limit=1` over A17's two alerts.
11. **Excerpt (FS Q11).** 0012 returns the whole section body, bounded at the contract's 8000 characters; if a body
    were longer, the cut sets the envelope's `truncated: true` (mcp-read sees it: the definer adds a per-row boolean
    the tool drops after setting the flag, or the writer's equivalent — no silent cut). corpus-1 has no section near
    the bound (45–119 words). `docs/retrieval.md` records the change; the T17 baseline's ranking is unaffected.
12. **Asset type (FS Q12).** For `search_procedures`, mcp-read asks asset-sim `GET /assets/{run's asset_id}` and passes
    that `asset_type` to the definer. A caller `asset_type` that differs → refused `ASSET_TYPE_OUT_OF_SCOPE`; equal or
    absent → the run's type. If asset-sim answers 404 (the run's asset is unknown to it), search proceeds with the
    caller's type or none (the type is a relevance filter, not an access boundary: the tenant filter is in the
    definer). asset-sim unavailable → `UNAVAILABLE`, `retryable: true` (fail closed). The writer checks which existing
    tests use asset IDs absent from `assets.json` and states the effect.
13. **R029 (FS Q13).** The worker's `HttpMcpCaller` calls `list_tools` in the same session before `call_tool` and
    refuses (raise `McpCallFailed`) unless (a) the advertised tool-name set equals the job's expected read set (the
    three read tools for a read handle) and (b) each called tool's advertised `inputSchema` equals the committed
    `schemas/tools/<tool>.input.schema.json` after canonical JSON. mcp-read therefore advertises exactly the committed
    file as each tool's input schema (argument validation stays the strict Pydantic model; a test proves the two
    agree on the bounds). Results: validated against `schemas/tool-result.schema.json` (the tool's own branch) with
    `jsonschema`, which becomes a runtime dependency of `ops-core` (a `core` helper loads the schemas from the repo's
    `schemas/`; packaging for containers → T30 debt); a serialized result above **256 KiB** is refused before parsing
    where the SDK allows, else after; `is_error`, a non-dict, a schema failure or `status != "ok"` → `McpCallFailed`. The
    run's outcome on failure stays FAILED "retrieval failed" (no success assumption). Tests: an altered tool list, an
    altered schema, an error-flagged, a malformed and an oversized result each fail closed (R029 evidence).
14. **`UNSUPPORTED_MODE` order and fallback corpus version (FS Q14).** Keep the order (the handle first, then the mode):
    an invalid handle never receives a capability answer; the test stays. The fallback `corpus_version` is closed by
    T17 (the definer answers `'none'`); record that ruling in T16's review note — no code.
15. **Units per call (FS Q15).** Asset tools: unit 1 `resolve_invocation` + `allowed_tool` (as search), unit 2
    `asset_scope`, both committed; then the HTTP call outside any transaction, timeout 10 s, no retry (the job
    retries). A handle that dies between unit 2 and the HTTP call still yields a read of the scoped asset only (no write,
    no authority gained) — documented, not prevented. asset-sim failures: transport error/timeout/503 →
    `UNAVAILABLE` `retryable: true`; 404 → `NOT_FOUND`; a response that fails the tool-result schema → `UPSTREAM_INVALID`
    `retryable: false` (mcp-read validates asset-sim's data before returning it).
16. **Status observation (FS Q16).** T16 returns `observed_at`/`revision` only; recording an observation the grant can
    check (R116) → T21 debt line; SA:377's evidence-sufficiency rule → T20.
17. **The worker (FS Q17).** T16 changes the worker only for R029 (ruling 13). Calling the asset tools and passing
    their results into drafting → T20 debt line. The tools are proven with an independent MCP client over HTTP (BS:378,
    the R025 pattern) in live tests.
18. **Tests and evidence (FS Q18).** `tests/plan_m` (add to `testpaths`); live evidence in `tests/e2e/`
    (`test_asset_sim_live.py`, `test_mcp_read_t16_live.py`, `test_migration_0012_live.py`); R028/R029 point there. The
    tool-list pins move to the three read tools; R131's ACL equality becomes `{current_time, resolve_invocation,
    asset_scope, search_procedures_scoped}` for `mcp_read` and `mcp_exec` gets `42501` on `asset_scope`; R131's note
    records that the read half is complete subject to errata 96 and 104 (R131 keeps its owners); `REVISIONS`,
    `DEFINER_FUNCTIONS`, the lock-order guard and `test_migration_0008_live`'s transitive scan include 0012 /
    `asset_scope`.

### Constraints for the writer

- Same plan format as `docs/superpowers/plans/2026-10-16-first-slice-l-governed-corpus.md`: Global Constraints, a
  debt list, then tasks with exact files, complete code where it is load-bearing (SQL bodies verbatim), tests first,
  exact commands and expected outputs, a close-out task (handoff records, acceptance rows R028/R029/R131, errata
  103+, SESSION_STATE/STATUS/PROJECT_HISTORY, owner input "migrate dev to 0012"). Function signatures must be copied
  from the code, not retyped: the Plan L plan printed a wrong argument order — every regprocedure/type list in the
  plan is checked against `privileges.DEFINER_FUNCTIONS` and the SQL.
- Authority, approval, idempotency, no-unapproved-external-action boundaries preserved; tenant only from the handle;
  no table grant for `mcp_read`; definers per SA:446 (REVOKE PUBLIC, GRANT exactly the callers).
- Live tests use only the `ops_test` databases (profile test); nothing touches the dev database.
- Comments per `docs/CODE_COMMENTS.md`; no Claude attribution in commits.

---

# Controller rulings on the writer's departures

## Plan M — controller rulings on the writer's departures (plan c5ccbc2)

1. Search runs three database units (resolve_invocation, asset_scope, search) — **accepted**: the run's asset comes
   only from asset_scope; each unit is a committed read, no lock is held across the HTTP call.
2. retrieved_at/excerpt plumbing in Task 1 with 0012 — **accepted**: the return type changes with the revision, so
   the reader changes with it (gates stay green per task).
3. Reused FaultKinds + ASSET_UNAVAILABLE in ASSET_SIM_FAULTS; test_faults_t13's invariant adjusted — **accepted**,
   provided the invariant still proves every hook is reachable only under PROFILE=test.
4. Extra asset-sim answer mappings (401 → UNAVAILABLE retryable with the cached token dropped; 5xx → UNAVAILABLE;
   400 on a cursor → INVALID_CURSOR; anything else → UPSTREAM_INVALID; asset/interval/as_of cross-checked) —
   **accepted**: all fail closed and none leaks data.
5. 256 KiB bound after the SDK parses — **accepted** with a debt line (a transport-level bound → T30, with the
   container network work).
6. R029 checks on read calls only; write-tool discovery stays T47's check — **accepted** with a debt line; route it
   to **T21** (the first task that drives mcp-write's execute path from the graph) rather than T20, unless the plan
   shows T20 calls mcp-write — the critic checks.
7. ops-view-users refused with 401 or 403 — **accepted**; the test asserts "refused, no data" for it and exactly 403
   for the other three.
8. Two new startup markers, GOVERNED_CORPUS kept — **accepted**.
9. new_run keywords and conftest.add_requester; the beta baseline run requested by riley — **accepted**; the critic
   checks that the T17 baseline report's numbers are unaffected (the run's requester changes nothing in ranking).
10. Every live search needs asset-sim; the "no filter" control moves to a Z99 run — **accepted**.
- Erratum 106 (search return shape amending erratum 93) — **accepted**.
- Review-focus risks (R105 walking-skeleton evidence under the pump filter; a 60-second handle window while the clock
  moves) — carried to execution: the implementer runs those live tests early in their task and reports.

---

# Round 1

## Plan M, round 1: static critique

Plan: `docs/superpowers/plans/2026-10-18-first-slice-m-read-tools-asset-sim.md` (c5ccbc2, 6994 lines, read in full).
Inputs: brief.md, writer-departures-rulings.md, the fact sheet, SPEC_AMENDMENTS/BUILD_SPEC lines cited below, and the
real code at c5ccbc2.

**Verdict: REVISE.** There are 2 Critical, 2 Important and 7 Minor findings. Both Critical findings are live-test
defects that will turn the live gate red. Neither one weakens a boundary. The SQL, the security design and the
records are sound.

### What I verified mechanically (evidence, not trust)

- **Edit anchors.** I replayed every Create/Replace/Edit of Tasks 1-6 in plan order on a virtual copy of c5ccbc2
  (scratchpad `planm/critic/anchors.py`). There are 110 `replace:` blocks, and Edit 8 covers two files, so 111 edits
  were applied. Every anchor matched exactly once. No anchor was missing or ambiguous.
- **Dev counts.** I overlaid the result on a `git archive` copy and ran the whole dev pytest with the copy's sources
  first on PYTHONPATH. The result was `1328 passed, 13 failed, 205 skipped`. The 13 failures are the
  git-checkout-only tests the plan names: 12 in `test_verify_handoff.py` and 1 in `test_text_hygiene.py`. So
  1328 + 13 = 1341 passed, 205 skipped, which is exactly the plan's Task 6 figure. The affected plans
  (plan_m, d, e, h, j, k, l) gave 591 passed and 0 failed.
- **Lint and types.** On the replayed files, ruff check gave no errors once import order was excluded. The I001 hits
  come only from first-party detection outside the repo, and the plan's `ruff check --fix` handles them.
  `ruff format --check` reported all 47 files already formatted. mypy strict over core, asset-sim, mcp-read and
  worker gave "no issues in 39 files".
- **Baseline.** The repo's dev gate today is `1270 passed, 191 skipped`, `CHECK: GREEN`, which matches the plan.
- **0012 SQL.**
  - I rendered `changed(REV0011.SEARCH_PROCEDURES_SCOPED)` from the plan's own module text.
  - It is byte-identical to the plan's printed "For review" body.
  - Its diff against 0011 is exactly the five hunks: return type, membership block, `retrieved_at := v_now`, the
    8000 bound with `excerpt_cut`, and `'excerpt_cut'` in jsonb.
  - Reversing the changes gives 0011's body.
  - The printed `asset_scope` equals the rendered one.
  - Upgrade emits: DROP search; asset_scope + REVOKE PUBLIC + GRANT mcp_read; search + REVOKE + GRANT.
  - Downgrade emits: DROP asset_scope, DROP search, 0011 body + REVOKE + GRANT.
  - The longest SQL line is 120 characters.
- **Signatures.**
  - `search_procedures_scoped`: `text, text, text, public.vector, text, integer, text`. This matches
    `privileges.py:209` and 0011's FUNCTIONS (0011:245), with the order `raw_handle, azp, query, embedding,
    asset_type, limit, mode` (0011:161-163). Plan L's wrong-order error does not recur.
  - `asset_scope`: `text, text`.
  - `_resolve_handle`: `text, text, text`, which matches `HELPER_FUNCTIONS`.
- **uv.lock.** The writer's measured diff (`uv.lock.orig` against `uv.lock.task2`) is the claimed +fastapi/+uvicorn
  dependency and requires-dist change, with no version moves.

### Critical

#### C1. `tests/e2e/test_ingest_live.py::test_r032_repeat_change_revoke_and_supersede` fails from Task 1 onward. The plan never edits it.

- **Where.** The plan's Writer departure 9 (plan :86-91) and Review Focus 2 (:6951-6955) say every other live test
  that calls a read definer "uses alpha and ALEX already (checked)".
- **Why it fails.**
  - `test_ingest_live.py:77-79` creates two random tenants, `alpha, beta = uuid4(), uuid4()`, by INSERT with no
    memberships.
  - `:86` runs `new_run(app_conn, alpha, ...)`, so the requester is ALEX.
  - `:62-70` `search()` then calls `persistence.search_procedures` as `mcp_read` at `:118`, `:133`, `:161` and
    `:181`.
  - Revision 0012's MEMBERSHIP_CHECK (plan :703-711, inside `search_procedures_scoped`) finds no active requester row
    for ALEX in that tenant. It raises OC008, so the first `search(...)` raises `HandleRejected`.
- **Effect.**
  - The live gate is red at Task 1 and at every later task.
  - R032's live evidence breaks.
  - The plan's live counts (1457 and on) are wrong.
- **Fix.**
  - In Task 1 Step 5, add an edit to `test_ingest_live.py`: import `add_requester` and `ALEX`, and call
    `await add_requester(app_conn, alpha, ALEX)` right after the two tenant INSERTs.
  - `purge_tenant` (conftest :217-222) already deletes memberships before the tenant, so cleanup holds.
  - Add the file to Task 1's Files and commit list.
  - Correct departure 9 and Review Focus 2.

#### C2. The slow-answer case of `test_asset_sim_failures_reach_the_caller_as_their_envelopes` cannot pass: the test client times out first.

- **Where.**
  - Plan :4913-4955: `("timeout_before_accept", {"seconds": 11})`, with the comment "mcp-read gives up after 10 s".
  - Review Focus and Task 3 Step 4 say "takes about 11 seconds by design".
- **Why it fails.**
  - The test calls through `tests.e2e.test_mcp_read_t15_live.call` (`test_mcp_read_t15_live.py:118-128`). That
    helper builds `httpx2.AsyncClient(headers=headers)` with no timeout. httpx2's default is
    `Timeout(timeout=5.0)` (`.venv/.../httpx2/_config.py:218`).
  - The MCP SDK sends the POST through `stream_within_origin(client, "POST", ...)`
    (`mcp/client/streamable_http.py:370`, `mcp/shared/_httpx_utils.py:112-140`) and passes no per-request timeout.
  - mcp-read answers with `json_response=True`, so no byte arrives until the tool returns, about 10 s later.
- **Effect.** The client's 5-second read timeout fires first. `call()` raises a transport error or exception group
  instead of returning the `UNAVAILABLE` envelope. The test fails, and `reports/mcp-read/t16-read-tools.txt` is never
  written: `EXPECTED_LINES` is not reached and the module fixture skips the write.
- **Fix (either one).**
  - Give `call` a `timeout` parameter and pass `httpx2.Timeout(10.0, read=30.0)` for this case.
  - Or let the faults test open its own client with a read timeout above 11 s.
  - Keep asset-sim's sleep (11 s) above mcp-read's 10 s and the client's read timeout above both.

### Important

#### I1. The debt line the controller required for departure 5 (a transport-level 256 KiB bound → T30) is not in the debt list.

- The ruling on departure 5 (writer-departures-rulings.md item 5) reads: "accepted with a debt line (a
  transport-level bound → T30, with the container network work)".
- The Plan M debt list (plan :407-430) has no such line. The size bound appears only in departure 5 and in the
  `read_result` comment (:5937-5938).
- SA:698 requires every shortcut to be declared before code.
- **Fix.** Add to Task 1 Step 1c's debt text: "the worker's 256 KiB result bound is applied after the MCP SDK has read
  and parsed the body (no hook stops it earlier); a transport-level bound → T30". Mention it in the T16 close-out
  note (:6547-6550) and in the R029 row note (:6606-6612).

#### I2. With jsonschema a runtime dependency of ops-core, the `date-time` format checks silently disappear outside the dev group.

- `tool_contracts._result_validator` uses `Draft202012Validator.FORMAT_CHECKER` (plan :3775-3777).
- jsonschema checks `format: date-time` only when `rfc3339-validator` is importable. That package is a root dev-group
  dependency only (`pyproject.toml:43`; FS :524). The plan adds only `jsonschema` to `core/pyproject.toml`
  (plan :3682-3689).
- In this checkout `uv sync` installs the dev group, so tests pass. A runtime-only install, such as T30's containers,
  would validate observed_at, occurred_at, effective_from and retrieved_at by pattern only. R029/BS:399's "validate
  tool-specific nested schemas" would then be weaker than the tests show.
- The patterns still bound the shape, but an impossible date such as `2026-02-30T…` would pass at mcp-read's
  `UPSTREAM_INVALID` check and at the worker.
- **Fix.** Add `"rfc3339-validator>=0.1.4,<1"` to ops-core's dependencies (already locked; it is a `uv lock --offline`
  line), or add an explicit T30 debt line. Optionally add a unit test asserting that `check_result` refuses
  `observed_at: "2026-02-30T00:00:00Z"`.

### Minor

1. **Departure 6 owner (the controller asked the critic to check).**
   - The plan sends the write-call discovery debt to T20: debt list :417-418, `TODO(T20)` at worker mcp.py :6009,
     R029 note :6612, T16 note :6548, STATUS :6828.
   - The ruling says T21 "unless the plan shows T20 calls mcp-write". The plan does not show it, but the spec does.
   - SA:207 (AM-12) lists the graph nodes T20 builds ("Nodes per AM-12", tasks.json T20), including
     `execute_approved_proposal (mcp-write)`.
   - T20's DoD (R129) enumerates every router row, and `execute` is one route of SA:377.
   - So T20 is the first task to drive mcp-write from the graph, and T20 is the right owner.
   - Today's `handlers.execute` (`worker/src/ops_worker/handlers.py:240`) already calls `create_incident` outside any
     graph, so the debt is live now.
   - **Fix.** Keep T20 and add the citation (SA:207; T20 "Nodes per AM-12"; R129) to departure 6 and to the debt
     line, so the routing is justified rather than asserted.
2. **R025's acceptance note goes stale.**
   - Task 6 (:6122-6165) changes the R025 test and its evidence file `reports/mcp-read/t15-independent-client.txt`.
     The evidence now reads "listed the three read tools, called search_procedures and get_asset_status ok", and
     Task 7 Step 3 commits that file.
   - The R025 row note still says the client "lists exactly search_procedures and calls it". The records script
     (:6575-6644) does not touch R025.
   - **Fix.** Update R025's note's read half in the script (append, owners unchanged).
3. **The departure 3 condition is met only by composition.**
   - `test_faults_t13`'s edited invariant (:2313-2315) proves the BS:405 mapping, not profile reachability.
   - Profile-only reachability rests on `Faults` refusing non-test profiles (existing test) and on
     `test_fault_routes_exist_only_under_the_test_profile`, which checks DEV only (:2177-2180).
   - **Fix.** Parametrise that check over DEV and DEMO, and assert that a status read in DEV never yields
     `unavailable`. The ruling's proviso then holds explicitly.
4. **`docs/runbooks/walking-skeleton.md:42` still says** "`skeleton.py up`, which restarts all six processes".
   Task 6 Edits 9-10 fix lines 22 and 26 only. Change it to seven.
5. **The `asset_sim` fixture (:3099) builds `uvicorn.Config` without `log_config=None`.** uvicorn's dictConfig then
   reconfigures the `uvicorn*` loggers process-wide (propagate False, a stderr handler without the redacting
   filter). `test_mcp_read_live` and `test_mcp_write_live` already do this, and t15's caplog test restores
   propagation (`test_mcp_read_t15_live.py:353-383`), so nothing breaks. For consistency with `serving()` (:92) and
   the redaction rule, pass `log_config=None`.
6. **The R029 row is marked `RECORDED_LOCALLY_LIVE`, but its negative half is in-process only.** That half covers
   the altered listing and schema, and the error-flagged, malformed and oversized results (`test_worker_r029.py`,
   against the real mcp-read app over ASGITransport). The live half is the positive case. The note (:6606-6612) says
   "live, the real server passes", which is accurate. Make it explicit that the refusals are proven in-process, so
   the status is not read as all-live.
7. **The R105 evidence file is restored after every live run (Global Constraints :135-137, Task 7 Step 3).** That is
   correct procedure, but R105's behaviour now changes: seven processes, the run-type filter, and the worker's R029
   checks. The committed `reports/skeleton/r105-walking-skeleton.txt` therefore predates Plan M. **Fix.** Consider
   keeping the final run's R105 file in Task 7 (it is redacted).

### Checks requested, with answers

#### 1. Correctness against the code

- Anchors, signatures, imports and fixtures: all verified (see above).
- Test-first failure reasons:
  - Task 1 (8× FileNotFoundError, DID NOT RAISE, and the `Procedures.__init__` TypeError) is right by inspection of
    `tests/plan_l/test_migration_0011.py:31-46`.
  - Task 4's "6 failed, 5 passed" is right by trace.
- Per-task dev counts match my measurement at the end state. The live counts are arithmetic and are wrong while C1
  stands.

#### 2. 0012 SQL

| Requirement | Status |
|---|---|
| SECURITY DEFINER HEADER and search_path | Same HEADER as 0011:40 |
| REVOKE PUBLIC and GRANT mcp_read only | Yes |
| `_authority` first | Yes |
| Tenant from the handle | Yes |
| `set_config(…, true)` | Yes |
| Lock order | `_resolve_handle`'s run_lease FOR SHARE first (0007:142); runs and memberships are plain reads |
| `OBSERVED_UNITS` entry | Added |
| Clock read after the lock | `as_of := app.current_time()` after it (SA:157) |
| Membership re-check | Active, role `requester`, subject = `runs.requester`, matched without issuer (erratum 105) |
| Refusal | The single OC008 `handle_rejected` |
| Search body against 0011 | Identical except the five changes |
| Downgrade | Exact to 0011, from 0011's own module |
| Startup markers | `ASSET_SCOPE` and `SEARCH_INSTANT` are unique to 0012; `GOVERNED_CORPUS` survives |

Every column reference in the membership block and the run read is qualified, so the OUT-parameter name collision
(run_id, tenant_id, asset_id…) is safe. This is a first-execution risk only, as Review Focus 1 says.

#### 3. Security boundaries

- asset-sim's verifier is aud `asset-sim`, azp `{ops-mcp-read}`, typ Bearer. The realm maps the audience
  (`realm-ops-dev.json:76-82`).
- asset-sim applies its own tenant filter, and an unknown asset and a foreign one get the same 404 body except
  request_id.
- mcp-read forwards only its own token, the tenant, as_of and the run's interval, never the handle.
- `ASSET_OUT_OF_SCOPE` and `INTERVAL_OUT_OF_SCOPE` are raised before any asset-sim call (unit-tested: `seen == []`).
- The fault routes exist only when `Faults(profile)` can be built (TEST), and need mcp-read's token.
- The cursor is bound by SHA-256 to tenant, asset and interval, and selects only within the already filtered window.
- No table grant is added for mcp_read. The secret is read once from the file and never logged or echoed.

#### 4. R029 in the worker

All of the following are in place:

- `list_tools` runs in the same session.
- The name set must equal JOB_RULES[INVESTIGATE]'s three tools.
- Each schema is compared with the committed file as canonical JSON.
- Results are validated with jsonschema, including the branch-7 rule that read tools answer ok or error only.
- The 256 KiB bound is applied after parsing. That is accepted, but the debt line is missing (I1).
- A failure becomes McpCallFailed, and the run ends FAILED "retrieval failed" (handlers.py:132-135).
- jsonschema becomes a runtime dependency of ops-core, and the uv.lock change is consistent. I2 notes the
  format-checker gap.

#### 5. Departures 6 and 9

- **Departure 6.** T20, per SA:207 (Minor 1).
- **Departure 9.** The T17 baseline is unaffected.
  - The outcomes use only `(evidence_id, rank)` (`test_retrieval_baseline_live.py:79-84`).
  - Ranking text is byte-identical.
  - The requester change only gates access: riley is beta's seeded active requester.
  - The excerpt change does not enter rank.
  - The report files are restored by checkout and not regenerated in the plan.

#### 6. Live tests

- Only `ops_test` and `incident_test` are used.
- **60-second window.** t16 test 1 mints its handle at real time and moves the clock back, so `expires_at` and
  `lease_until` stay ahead. The other tests make at most 9 short calls. The 0012 live clock-forward tests re-lease
  and re-mint. All of this is sound, apart from C2's client timeout.
- **R105 evidence under the pump filter.** The committed R105 evidence is `ALPHA-ALERT-REVIEW:v1:repeated-alerts`
  (`reports/skeleton/r105-walking-skeleton.txt:3`), and that document's `asset_family` is null
  (`catalog.json:55-58`).
  - The pump filter only removes compressor and conveyor documents.
  - It leaves every remaining document's rank unchanged against the 0.25 threshold.
  - So the evidence stays non-empty.

#### 7. Close-out

- The script's preconditions hold: T16 is PLANNED with review_notes, and T18 has none.
- The BUILD_BACKLOG anchors exist.
- The R028, R029 and R131 rows get real paths.
- Errata 103-106 are worded consistently with the rulings.
- The owner input "migrate dev to 0012" is present.
- No overclaim, apart from Minor 6's phrasing.

### Process note

Once I mistakenly launched `uv run python -I - < /dev/null` (stdin was /dev/null, so nothing executed) inside a
compound shell command. I stopped it by task ID. No database, Keycloak, service or network connection was made. All
helper scripts are in `scratchpad/planm/critic/`.

## Plan M round 1 — controller rulings (critic report: C:\Users\joeys\Desktop\MLOps\.superpowers\planm\round1-static.md)

Fix every finding in the plan; nothing is parked.

- **C1** test_ingest_live's random tenants have no membership → 0012 refuses. **Fix as proposed**: add_requester for
  ALEX after the tenant INSERTs, the file joins Task 1's file list and its live list. Then re-sweep EVERY live test
  that calls `persistence.search_procedures`, `asset_scope`, or an mcp-read tool against a tenant it creates, and list
  the sweep (file:line, membership present yes/no) in the Task 1 text; departure 9 / Review Focus 2 must say what was
  swept, not "every call site".
- **C2** t15's `call()` client times out at httpx's default 5 s before mcp-read's 10 s answer. **Fix**: give the slow
  case a read timeout above the server's (e.g. 15 s) without changing the other t15 callers' behaviour, and state why.
- **I1** add the transport-level 256 KiB bound debt line (→ T30) to the debt list.
- **I2** add `rfc3339-validator` to ops-core's runtime dependencies (already locked; show the pyproject and uv.lock
  change) so `format: date-time` is enforced at run time; add a unit test that a non-RFC-3339 `observed_at` fails
  validation through the runtime helper.
- **M1** keep T20 for the write-tool discovery debt and cite SA:207 (AM-12's `execute_approved_proposal (mcp-write)`)
  and T20's R129 in the debt line.
- **M2** update R025's acceptance note in the close-out records script to the three read tools.
- **M3** extend the fault-route test to the DEMO profile as well as DEV (every non-test profile).
- **M4** `docs/runbooks/walking-skeleton.md:42` → seven processes (Task 6).
- **M5** the `asset_sim` fixture passes `log_config=None` like the others.
- **M6** R029's row: say exactly what is live and what is in-process — evidence status per the matrix vocabulary
  must not claim live for the refusal cases; if the matrix allows only one status, use the weaker true one
  (`RECORDED_LOCALLY`) and name the live positive case in the note.
- **M7** the close-out commits the R105 evidence file regenerated by the final live run (no restore of the old one).

After the fixes, re-apply your replay (every step on a fresh copy of c5ccbc2's tree) and update the per-task counts.
Commit as `docs: Plan M round 1 - <short summary>` (no trailers, no push) and add a short "Round 1 changes" list at
the top of the plan under the writer departures.

---

# Round 2

## Plan M, round 2: static critique

Plan: `docs/superpowers/plans/2026-10-18-first-slice-m-read-tools-asset-sim.md` at `5d2509c` (7167 lines). Inputs:
round 1's report and the controller's rulings on it, the original brief and the departure rulings, SPEC_AMENDMENTS over
BUILD_SPEC, and the real code at `c5ccbc2`. The code tree is the same at `5d2509c`, because only the plan changed.

**Verdict: ACCEPT.** All 11 round 1 findings are fixed as ruled. There are 0 Critical, 0 Important and 5 Minor new
findings. Each Minor fix is a single line or a few lines, with no count change unless stated, and none needs another
round.

### What I ran (no database, Keycloak, service or network)

- **Replay.** I ran `git archive c5ccbc2` into `scratchpad/planm/critic2/tree`. Round 1's anchor replayer, changed only
  to write LF bytes, then applied every Create/Replace/Edit of the revised plan in order. It applied 115 edits, and
  every anchor matched exactly once. That is round 1's 111 plus 4: Task 1 Edits 11 (two replaces) and 12, and Task 6
  Edit 11.
- **Dev pytest on the replayed copy** (the copy's sources first on PYTHONPATH, the repository's locked venv):
  `13 failed, 1331 passed, 205 skipped`.
  - The 13 failures are the known git-checkout-only tests: 12 in `test_verify_handoff.py` and 1 in
    `test_text_hygiene.py`.
  - So the repository count is 1344 passed, 205 skipped, which equals the plan's revised Task 5 and Task 6 figure.
  - Per file, `tests/plan_m` gives `test_asset_sim_data` 14, `test_asset_sim_app` 6, `test_tool_contracts` 6,
    `test_mcp_read_assets` 19, `test_mcp_read_search` 4, `test_migration_0012` 10 and `test_worker_r029` 12, so 71.
- **Lint and types on the replay.** `ruff check` passed. `ruff format --check` passed on 55 files. mypy strict over
  core, asset-sim, mcp-read and worker reported "no issues in 39 source files".
- **`uv lock --offline` on the replay.** It resolved 67 packages. The diff is the intended one:
  - ops-asset-sim gains fastapi and uvicorn (Task 2).
  - ops-core gains `jsonschema` and `rfc3339-validator` in both `dependencies` and `requires-dist`, which is 4 lines
    (Task 3).
  - No version moves.
- **Repository dev gate.** `scripts/check.py` gave `1270 passed, 191 skipped`, `CHECK: GREEN`, matching the plan's
  baseline.

### Round 1 findings, verified

| Finding | Verdict | Evidence |
|---|---|---|
| C1 | **fixed** | Task 1 Edits 11-12 (plan :1625-1663) import `add_requester` and `ALEX` and call `add_requester(app_conn, alpha, ALEX)` after the tenant INSERTs. The file is in Task 1's Files and commit (:1926-1935). `purge_tenant` (conftest :276-281) deletes memberships first. My independent sweep is below: no miss. |
| C2 | **fixed** | Only the slow case passes `read_timeout=30.0`, and `tool()` (t16 live) then opens its own `httpx2.AsyncClient(timeout=Timeout(10.0, read=30.0))`. The other three fault cases and every other caller still go through `test_mcp_read_t15_live.call`, which is unchanged (`t15:119-128`). 30 s > mcp-read's 10 s (`assets.TIMEOUT_SECONDS`, `httpx2.AsyncClient(timeout=10.0)`) > asset-sim's 11 s hold, so mcp-read answers `UNAVAILABLE` and the client receives it. `Client.read_timeout_seconds` defaults to None (`mcp/client/client.py:303`), so no SDK-level timeout intervenes. The handle's 60 s covers four calls of about 10 s in total. The reason is stated in the docstring and at :5101-5103. |
| I1 | **fixed** | The debt list has the line at :455-456. It is also in the T16 note (:6698-6702) and the R029 note (:6765-6766). |
| I2 | **fixed** | `core/pyproject.toml` gains `rfc3339-validator>=0.1.4,<1`, and the lock diff is as measured above. jsonschema 4.26's `date-time` checker imports `rfc3339_validator` (`jsonschema/_format.py:396-402`). `test_date_time_is_checked_at_run_time` asserts both the runtime dependency and the refusal of `2026-02-30`/`T25:00` through `check_result`, and it passes on the replay. |
| M1 | **fixed** | Departure 6 (:77-82) and the debt line (:453-454) cite SA:207 and R129. |
| M2 | **fixed** | The R025 anchor occurs exactly once in today's matrix note. I checked this mechanically. The replacement names the three tools and the asset read. |
| M3 | **fixed** | The test is parametrised over every non-TEST `Profile` (dev and demo). It arms every kind in `FAULTS` and expects 404, and asserts that a dev or demo status is `warning`. The test-profile half is its own test. The app file has 6 tests. |
| M4 | **fixed** | Task 6 Edit 11 changes `walking-skeleton.md:42` to seven. The other docs still saying six are listed in Minor 5. |
| M5 | **fixed** | The fixture has `log_config=None` (conftest :111 on the replay). |
| M6 | **fixed as ruled** | R029 is `RECORDED_LOCALLY`, and the note separates the in-process refusals from the one live positive case. Its evidence paths contradict the matrix vocabulary (Minor 2). |
| M7 | **fixed** | In Task 7 Step 3 (:7088-7094), `reports/skeleton` is no longer restored and is added in Step 4's `git add`. `reports/bootstrap` is still restored. |

#### C1: independent sweep of every live read-definer and mcp-read call

I grepped `tests/e2e` on the replay for `search_procedures`, `asset_scope`, `call_tool`, `HttpMcpCaller`, `serving` and
every `new_run(` call site. I then traced each read call to the tenant its run lives in.

| Call site (replay) | Tenant | Active requester row for the run's requester |
|---|---|---|
| `test_ingest_live.py:69` (via `search` at :121, :136, :164, :184) | random alpha | yes, by Edit 12 |
| `test_migration_0011_live.py` `found`/direct calls; every run via `handle_for(…, None)` | random | yes, `handle_for` calls `add_requester` |
| `test_migration_0011_live.py:341` and `test_mcp_write_t47_live.py:203-205` ("not-a-handle" or `'h'` as non-mcp_read roles) | none | not reached (ACL 42501) |
| `test_retrieval_baseline_live.py:79` | seeded alpha and beta | yes: alex, and riley (beta's requester, `seed-ids.json:28-30`) |
| `test_mcp_read_t15_live.py` (runs :174-176, :216-217, :358; `approved_run` is ALPHA, `test_mcp_write_live.py:33-36`) | seeded alpha | yes, alex |
| `test_mcp_read_live.py` (runs :46, :58) | seeded alpha | yes, alex |
| `test_mcp_read_process_live.py` (runs :104, :165) | seeded alpha | yes, alex |
| `test_mcp_read_t16_live.py` (every run) | seeded alpha | yes; alex is switched off on purpose and restored in `finally` |
| `test_migration_0012_live.py` | seeded alpha, or `handle_for(…, None)` | yes; the LEE run is refused on purpose |
| `test_r105_walking_skeleton.py` (the worker's search) | seeded alpha | yes, alex is admitted by the API |
| `test_worker_live.py` `ScriptedMcp` (:61-69) | n/a | calls `resolve_invocation` only, which 0012 does not change |
| `test_mcp_write_t47_live.py:225`, :322 and `test_definers_*`, `test_leases_live`, `test_fenced_definers_live`, `test_migration_0009/0010_live`, `test_migrations_and_persistence:181-190` | various | `resolve_invocation` only |

No other module imports `test_ingest_live` or `test_migration_0011_live`'s helpers, except 0012-live
(`handle_for`, which already adds the requester). Nothing outside `tests/` calls the definers in a live run. The plan's
table (:1667-1681) agrees with this sweep. Its line numbers are cd6a5b3's, as it says.

### Areas re-examined for anything new

- **0012 SQL** (rendered on the replay, `migrations/app/versions/0012_asset_scope.py`). All of the following hold:
  - HEADER as 0011's. REVOKE PUBLIC and GRANT `mcp_read` through `function_grant_statements`.
  - `_authority` first. The tenant comes from `_resolve_handle`, whose run_lease FOR SHARE is the only lock.
    `set_config(…, true)`.
  - The membership block is identical in both functions. Every column is qualified, so nothing collides with the OUT
    parameters `run_id`, `tenant_id`, `asset_id`, `start_at`, `end_at`, `as_of`, `retrieved_at`.
  - `memberships.subject` and `runs.requester` are both `uuid` (0001:43, 0001:77). RLS on memberships admits
    `app_definer` under the set tenant (0002 RLS list), the same pattern as 0004:203.
  - The refusal is `RAISE 'handle_rejected' USING ERRCODE='OC008'`, byte-identical to `_resolve_handle`'s (0007:140-161).
  - In the search, `retrieved_at := v_now` sits before the "only stop words" early `RETURN NEXT` (0011:193-196). Every
    path that returns a row therefore carries the instant.
  - The downgrade drops `asset_scope` and the search, then re-creates 0011's frozen body with its grants.
  - No issue.
- **asset-sim.**
  - Verifier: aud `asset-sim`, azp `{ops-mcp-read}`, typ Bearer.
  - Tenant filter: `Catalog.asset` is keyed by (tenant, asset). Asset ids are unique by `corpus.load_assets`, so the
    alert map keyed by asset id cannot mix tenants.
  - Cursor: SHA-256 over tenant, asset and interval, and it selects only within the filtered window.
  - Faults exist only when the profile is TEST, require mcp-read's token, and are limited to the four consumed kinds.
  - No issue.
- **R029 in the worker.**
  - Discovery runs in the same session and compares canonical JSON of the called tool.
  - jsonschema runs with the format checker (now enforced at run time).
  - The 256 KiB bound is applied before `is_error` and the contract check.
  - A failed check inside the client's task group is unwrapped to `McpCallFailed`.
  - One gap: Minor 4.
- **Close-out.**
  - R028 `RECORDED_LOCALLY_LIVE` and R131 note-only (both anchors present) are fine.
  - The T16 note and the STATUS/SESSION text claim no more than the tests show.
  - R029's paths: Minor 2. The final-gate counts: Minor 1.

### Minor

#### 1. Task 7's final gate still expects the pre-round-1 counts

- **Plan.** At :7086-7087 the final gate expects "pytest `1341 passed, 205 skipped`" and "`1525 passed, 21 skipped`".
- **Why it is wrong.** Round 1 moved the plan's own figures to 1344/205 and 1528/21 (:359-369, and the Run lines of
  Tasks 5 and 6 at :6237 and :6627). The replay measures 1331 + 13 = 1344 passed, 205 skipped.
- **Mitigation.** The step says "or the measured counts", but the plan's numbers disagree with each other.
- **Fix.** Change the two numbers at :7086-7087 to 1344/205 and 1528/21.

#### 2. R029 is `RECORDED_LOCALLY` but lists a live test and a live evidence file

- **Plan.** `rows["R029"]` evidence paths (:6752-6758), with `statuses` (:6773).
- **The vocabulary.** `handoff/acceptance-matrix.json` `note` defines `RECORDED_LOCALLY` as "the tests in
  evidence_paths pass in scripts/check.py and CI".
- **The conflict.** `tests/e2e/test_mcp_read_t16_live.py` is skipped there, and `reports/mcp-read/t16-read-tools.txt`
  is a live run's record.
- **Precedent.** All 8 existing `RECORDED_LOCALLY` rows list only check.py-run files. That includes R098, which was
  downgraded the same way in Plan E (its review's M7). Plan D's M17 was the same contradiction.
- **Fix.** Set R029's evidence paths to `tests/plan_m/test_worker_r029.py`, `tests/plan_m/test_mcp_read_assets.py`
  and `tests/plan_m/test_tool_contracts.py`. The note already names the live test and its function, so the live
  positive case stays recorded without contradicting the status.

#### 3. The new evidence directory `reports/asset-sim/` is never scanned for tokens or secrets

- **Code.** `tests/plan_b/test_evidence.py:20-31` (`EVIDENCE_ROOTS`) covers bootstrap, skeleton, auth, ci, admission,
  leases, events, outbox, mcp-read and mcp-write. The plan adds `reports/asset-sim/t16-asset-sim.txt` (:3245, :3263)
  and never edits this list.
- **Why it matters.** The Global Constraints forbid a token in any evidence file. That evidence file's writer handles
  three foreign workload tokens.
- **Fix.** In Task 2, add `Path("reports/asset-sim")` to `EVIDENCE_ROOTS` and name it in the module docstring. The
  test loops over roots, so no count changes. The file joins Task 2's commit.

#### 4. R029's discovery check ignores pagination

- **Plan.** `check_listing((await client.list_tools()).tools, read)` (:6134), with `check_listing` at :6056.
- **The gap.** `Client.list_tools()` returns one page (`mcp/client/client.py:951-971`). `ListToolsResult` carries
  `next_cursor` (`mcp_types/_types.py:190-191`, :1440). A server that lists the three read tools on page 1 and a
  fourth with a cursor passes the "tool added" check. The R029 note (:6761-6762) claims that check holds.
- **Severity.** It is low-likelihood: mcp-read's SDK server does not page three tools. But it is a fail-open path in a
  fail-closed check.
- **Fix.**
  - Pass the whole `ListToolsResult` to `check_listing` and refuse when `listing.next_cursor is not None` ("the server
    advertises an unexpected tool set").
  - Add the case to `test_worker_r029.py`'s existing scripted-listing test as one more assertion, so the counts stay
    the same. If it is added as a new test instead, add +1 to Task 5 onward.

#### 5. Two more "six processes" survive outside the runbook M4 fixed

- `sweeper/src/ops_sweeper/sync.py:57` (`sync_memberships` docstring) reads "`scripts/skeleton.py up` restarts all
  six processes". This is the same statement as `walking-skeleton.md:42`.
- `tests/e2e/test_auth_live.py:58` reads "Six processes for the module". `Skeleton()` starts seven from Task 2 on.
- **Fix.** Change both to seven in Task 6, next to Edit 11. Neither change affects any count.

### Not findings (checked)

- I re-checked the C2 timing under shutdown. mcp-read's client drops the connection at 10 s, asset-sim's handler
  finishes its sleep about 1 s later, and uvicorn's `should_exit` waits only for that task. Nothing hangs.
- `add_requester` sits before the `try:` in `test_ingest_live`, the same as the two tenant INSERTs that were already
  there. It could only leak on a failed INSERT, which matches the existing behaviour.
- `test_date_time_is_checked_at_run_time` reads `core/pyproject.toml` relative to the working directory. That holds,
  because check.py runs pytest from the root.

### Process

Helper scripts and outputs are in `scratchpad/planm/critic2/`: `anchors.py`, `tree/`, `out/`, `copy/`, `devgate.txt`,
`repo_gate.txt` and `uv.lock.base`. `uv lock --offline` wrote only the scratch copy's `uv.lock`. The repository was not
edited. Running `scripts/check.py` there wrote only its tool caches. No database, Keycloak, service or network
connection was made, and no `.env` or secret file was opened by me.

## Plan M round 2 — controller rulings (critic report: C:\Users\joeys\Desktop\MLOps\.superpowers\planm\round2-static.md)

Verdict ACCEPT; round 1's 11 findings verified fixed. The five new Minors are fixed in the plan (no round 3):

1. Task 7 Step 3's final-gate expectations → 1344/205 dev and 1528/21 live.
2. R029 stays `RECORDED_LOCALLY`; its evidence_paths list only the `tests/plan_m` files that pass in check.py/CI; the
   note names the live positive case (`tests/e2e/test_mcp_read_t16_live.py`) and its report.
3. `reports/asset-sim/` joins `tests/plan_b/test_evidence.py`'s `EVIDENCE_ROOTS` in Task 2.
4. `check_listing` refuses a listing with a non-null `next_cursor` (a second page could add a tool); asserted inside an
   existing `test_worker_r029` test.
5. "six processes" → seven at `sweeper/src/ops_sweeper/sync.py:57` and `tests/e2e/test_auth_live.py:58` (Task 6).

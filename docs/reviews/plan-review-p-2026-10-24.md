# Plan P review record — T19 the drafting route (async LangChain ChatOllama DraftGenerator)

Plan: `docs/superpowers/plans/2026-10-24-first-slice-p-drafting-route.md` (branch `plan-p`; plan commit fbe940b, round 1
fixes 8bbad58). Inputs: `docs/superpowers/research/2026-10-24-plan-p-inputs.md` and the controller's rulings brief
(reproduced below).

Context. Before this plan the owner removed the holdout seal as a gate (erratum 114, d37f30c), PRs #12-#14 were merged
into `main`, and the agent ran T02's live probe at the owner's instruction (8b1c8b7): qwen3:8b produced valid JSON on
59 of 60 probe inputs but schema-valid drafts on only 5, because it put a `question` on proposals and answers, and the
probe's payload carried no evidence IDs. The owner asked the agent to build autonomously until the project is set up;
owner decisions the agent takes on that instruction are recorded as provisional.

How the round ran. The writer built the slice in a scratch worktree and generated the plan's code blocks from those
tested files, then re-applied the finished plan to a fresh worktree and matched the result file for file. The writer
could not copy `.env` into the scratch copy (the permission system refused it), so the database live gate never ran
before execution: live counts are arithmetic, and the three database live tests run for the first time in Tasks 3 and
4. The two Ollama-only live tests and the real-model evidence script did run on the scratch copy. On the owner's steer
(a portfolio project, kept lean) the plan had one static round; the controller checked the fix diff instead of running
a second.

Round 1: REVISE, 0 Critical, 3 Important, 10 Minor, 4 disputed claims. Everything was fixed in 8bbad58 and nothing was
parked:
- the test the controller had required for departure 6 (the validator and the grader agree) was missing;
- the committed real-run report did not say that no alert or status records were sent, or where the injected text came
  from;
- the draft's 90 s budget started at `generate`, not at the lease, against BS:555 and the heartbeat's own clock, so a
  slow repair would have ended as a lost lease rather than a templated failure.
Dev counts after Tasks 1-5: 1566, 1585, 1589, 1599 and 1603 passed (219, 221, 222, 222 and 222 skipped). Live after
Task 5: 1804 passed, 21 skipped (arithmetic). The evidence script, run three times on the scratch copy with the v2
prompts and payload, measured 60/60 valid first-pass drafts each time (the probe's starter prompt and payload had given
5/60).

Holdout custody: no agent opened holdout case material or a seal. None exists in the tree.

Process slips: none reported by the writer or the critic. The controller's own are recorded in the history. No agent
connected to the dev database, Keycloak or a service beyond local Ollama (read-only tags/version and generation), and
none opened `.env` or a secret file.

---

# Controller brief (rulings before round 1)

## Plan P brief — controller rulings for T19 (async LangChain ChatOllama DraftGenerator)

Branch `plan-p`: `main` 3905b35 + d37f30c (erratum 114) + 0db7ca4 (fact sheet) + 8b1c8b7 (T02 live probe outputs).
Fact sheet (FS): `docs/superpowers/research/2026-10-24-plan-p-inputs.md`. Errata continue at **115**. Requirements:
R036, R037, R039, R040, R041, R127, R130.

Gates at start: dev 1540 passed / 219 skipped; live 1737 / 21 (Plan O; erratum 114 added one dev test, so expect live
1738 / 21 before Plan P's own tests); verify_handoff exit 0. Dev DB at 0013, corpus-1 embedded. Local Ollama 0.40.4
has `qwen3:8b` (digest `500a1f06…8b41`, pinned in `data/model-pins.json`) and `nomic-embed-text`.

**Owner's steer:** portfolio project; the owner wants the scaffolding finished quickly and will work hands-on afterwards.
Lean plan, no speculative machinery. The owner asked the agent (2026-10-21/24) to build autonomously until set up.
Authority, approval, idempotency and no-unapproved-external-action boundaries are unchanged.

**Principle:** T19 makes the real model a selectable drafting route that is validated, bounded, pinned and recorded:
the generator, its prompts, validation with one repair, the router without fallback, the startup digest check and
warm-up, the run manifest, and recorded real-model evidence. Graph routing of answer/abstain (T20), manual proposals
(T21), bounded outage retries (T22/T29), and evaluation (T25) stay with their owners.

**Holdout custody:** no agent opens, reads, greps or hashes holdout case material or seals; only `evals/HOLDOUT.md`
and `evals/holdout-case.schema.json` may be read. Exclude `*holdout*`, `*seal*`, `*.sha256` from greps and listings.

### Rulings (one per FS question)

1. **Interface and location.** The `DraftGenerator` protocol stays in `ops_worker.drafting`; the real adapter
   `OllamaDraftGenerator` lives in the worker (new module), so only the worker gains LangChain dependencies. The pure
   validation (JSON Schema + `ModelDraft` + citation membership + thinking + authority keys) goes in `ops_core` (new
   module, e.g. `ops_core.draft_validation`) and reuses `grading.check_schema` where it fits, so T25 can call the same
   code. `generate(request, evidence)` keeps its two arguments; the adapter derives the interval, asset and the allowed
   evidence IDs from them. `policy_metadata` is not added (record as an erratum if BS:437's signature is cited).

2. **Router.** `MODEL_MODE` values equal the route values: `fake` | `qwen3:8b`; anything else (incl. `ollama`) is refused
   at startup with a clear message. Update `test_model_router_has_one_route_and_no_fallback` accordingly (qwen3:8b now
   accepted, `ollama` still refused). No fallback: a test proves a failing real route never yields a fake draft and the
   run fails. The route is chosen at startup and recorded per run. Skeleton default stays `fake`. No enum slot for a
   future model (a schema change later).

3. **Pins and digest.** Digest from `/api/tags` (erratum 115 on SA:598's `/api/show`; the probe and T18 already use
   `/api/tags`). Factor or reuse T18's `/api/tags` client rather than writing a second one; keep the embedder's
   behaviour unchanged. A digest mismatch, an absent or malformed `data/model-pins.json`, or a missing model fail closed
   on the real route. `ollama_version` differences are logged and recorded, not fatal. The fake route never reads the
   pin.

4. **Warm-up.** On the real route, before the poll loop starts: verify the digest, then one warm-up call with
   `keep_alive` (pick a value, e.g. "30m", as a named constant) and its own timeout of 180 s (the cold call exceeded 60 s
   in T02). Mismatch, unreachable or warm-up failure → the worker exits non-zero with a clear message (R127). The
   warm-up takes no model permit (it runs before the worker claims jobs). No per-draft digest re-check.

5. **Prompts.** Runtime prompts move to `core/src/ops_core/prompts/` as `incident-draft-v2` and `schema-repair-v2`.
   The system message is the starter's "System message" text plus the rules the probe showed missing (e.g. `question`
   only with `abstain`; cite only IDs from `allowed_evidence_ids`); the user payload is rendered as the starter's JSON
   keys (`confirmed_request`, `asset_id`, `interval`, `permitted_evidence`, `allowed_evidence_ids`,
   `requested_output_schema`). The starters in `handoff/prompts/` stay byte-identical (the probe pins them). A test
   pins each runtime prompt's sha256. `PROMPT_VERSION` becomes `incident-draft-v2` (proposal hashes change; update the
   fixtures/tests that pin it). Ship the prompts as package data of `ops-core`. AM-50's no-tuning rule applied to the
   holdout, which erratum 114 made optional; record that the v2 text is informed by the T02 probe (erratum 116).

6. **Validation and repair.** One repair after: parse error, JSON Schema or `ModelDraft` rejection, a citation not in
   the IDs offered to this run, thinking present (tag or `reasoning_content`, never stripped), or an authority key.
   No repair after a timeout or an unreachable model. Repair feedback lists at most 10 lines of the form
   `<json path>: <rule>` with no echo of the instance (the probe's jsonschema messages embedded the whole draft, which
   made its repair feedback useless). Each attempt gets `min(60 s, remaining of the 90 s budget)`. A failed repair ends
   the run FAILED with a templated message, no `drafts` row with the payload (SA:496), and a log line of rule names only.

7. **Model permit.** One permit hold spans the first pass and the repair; raise the TTL to the 90 s budget + 5 s (95 s)
   as a named constant with the reason. Release rule: release on cancel (T02's provisional line; today's behaviour). No
   `/api/ps` polling.

8. **Timeouts and errors.** `asyncio.wait_for` per attempt, plus the ChatOllama client timeout at the same value. A
   small exception taxonomy in the worker: `ModelUnavailable` (connect error, timeout, HTTP 5xx) and
   `ModelOutputInvalid` (after the repair). Both end the run FAILED with a templated message and close the job (bounded
   retries are T22/T29's; record the debt line). A first-attempt timeout is not repaired.

9. **Run manifest.** A new table `app.run_manifests` in revision 0014: one immutable row per run with AM-80's six
   fields, tenant-scoped with RLS, worker `INSERT, SELECT`, api `SELECT`, following AM-20.2/AM-20.5 and the existing
   revision patterns. It is written after retrieval and before the model call, so a failed draft still has one; on the
   fake route too (R130). `retrieval_mode` is the mode the run used. The dev DB stays at 0013 until the owner (or the
   agent at the owner's request) migrates; the live profile migrates `ops_test`.

10. **explanation.ready.** No payload contract change: the route, digest and prompt version are recorded in the
    manifest table, and the event's templated `message` keeps naming route and prompt version (erratum 117 records that
    T19's "records the route in explanation.ready" is met by the message text plus the manifest). The message stays a
    template, never the model's summary text.

11. **Draft kinds.** T19 validates any kind. In `handlers.investigate`: `proposal` follows today's path; `abstain`
    without a question ends the run INSUFFICIENT_EVIDENCE if the state machine allows DRAFTING → INSUFFICIENT_EVIDENCE
    (check; otherwise FAILED); `answer` and `abstain` + `question` end the run FAILED with a templated "not routed until
    T20" message and a debt line → T20. A `proposal` on an `answer_only` run is a validation failure.

12. **Tests.** Unit tests through an injectable async seam (the adapter takes a callable or a chat-model object that
    tests script), covering: valid drafts of each kind, malformed JSON, schema failures, membership failures,
    thinking, authority keys, timeouts, repair success and exhaustion, permit spanning, no fallback. Live (`--profile
    test`): the worker on the fake route writes a manifest row; the startup check against local Ollama passes with the
    committed pin and fails closed with a tampered pin. The real-model evidence is a script, `scripts/draft_evidence.py`,
    run once (not part of any gate): it drives the real route over the 60 probe inputs with the v2 payload and writes
    `reports/model/t19-real-run.md` and `.json` (digest, parameters, first-pass and post-repair validity with Wilson
    CIs, failure rules tallied, sample outputs). Predict its figures in the plan by running it in the scratch copy.

13. **Dependencies.** Add `langchain-ollama==1.1.0` (SA:582) to `worker/pyproject.toml` and re-lock; record the
    transitive versions the lock brings. mypy overrides only if a package lacks `py.typed`. The probe's isolated
    freeze need not match the lock.

14. **R036.** A unit test feeds injected text (the corpus's injected sections) through a scripted adversarial model that
    returns authority keys and tool-like content: validation refuses it, nothing about tools, grants, roles or the
    destination changes. The real-run evidence includes the probe's injected inputs. R055 stays T26's.

15. **Thinking.** Present → invalid (repairable once), never stripped, logged as a rule name. R039 evidenced by that
    test plus a test that a draft claiming success creates no `action.*` event and no status change.

16. **Model hint.** Not built in v1: close the debt with erratum 118; re-own the `TODO(T19)` hint markers as
    `TODO(v2)` or remove them, and keep the hint-row tests.

17. **URL.** Reuse `OPS_OLLAMA_URL` (one Ollama serves both pins). No new guard beyond what the settings already do.

18. **Owner steps.** T19 closes DONE when the unit and live gates pass and the real-run evidence is committed. T02 stays
    DONE_PENDING_OWNER (its decision lines are provisional). T44 step 10 stays pending.

19. **Requirements.** R127, R040, R041, R039, R036 → `IMPLEMENTED_LOCALLY_VERIFIED` with `RECORDED_LOCALLY` /
    `RECORDED_LOCALLY_LIVE` as their evidence is; R037 with the committed real-run report; R130 subject to T25's half
    (B and C identical routes). Errata as needed from 115 (this brief already assigns 115-118).

20. **Records.** Debt list committed before coding; T19 close-out note; `current_milestone` → M07; STATUS, SESSION_STATE,
    acceptance matrix, tasks.json, BUILD_BACKLOG; a PROJECT_HISTORY section 34 for Plan P inserted before "What the
    process taught" (renumbered to 35).

### Constraints for the writer

- Plan file: `docs/superpowers/plans/2026-10-24-first-slice-p-drafting-route.md`, same format as Plan O's
  (`docs/superpowers/plans/2026-10-19-first-slice-o-dev-eval-set.md`) but lean: Global Constraints, the debt list,
  then 5-6 tasks with exact files, complete code where load-bearing, tests first, exact commands and expected outputs,
  and a close-out task.
- Build and gate the slice in a scratch copy (a copy of the repo under the scratchpad, never the real tree), dev gate
  and live gate (`--profile test`, ops_test only), and predict the real-run figures by running the evidence script there
  against local Ollama (generation and `/api/tags`/`/api/version` allowed; never pull or delete a model).
- No connection to the dev database. Live tests touch only `ops_test` and local Ollama.
- Comments follow `docs/CODE_COMMENTS.md`. No Claude attribution in commits.
- Report your departures from these rulings as a numbered list at the end of your reply, each with its reason.

---

# Controller rulings on the writer's departures

## Plan P — controller rulings on the writer's departures (plan fbe940b)

1. Live DB gate not run in scratch (the writer's copy of `.env` was refused). Accepted as a known gap: the three DB live
   tests run for the first time during execution, in the real tree, where the live gate has always run. The critic
   reads them with extra care. The implementers do not copy `.env` anywhere.
2. Ollama-only live tests under `tests/plan_p` with their own OPS_LIVE skip: accepted.
3. Manifest-on-fake-route coverage as assertions in two existing worker live tests plus one grants/RLS test: accepted.
4. The evidence run adds the corpus injected sections and sends no alerts (the worker passes no asset data until T20):
   accepted; the report must say so, and a debt line → T20 (asset status/alerts in the drafting payload).
5. Exceptions in `ops_worker.drafting` so handlers never import LangChain: accepted.
6. Validation reuses `grading.DRAFT_SCHEMA` and the two-judge rule rather than calling `check_schema`: accepted, with a
   test that both judges agree on the sample drafts (no drift between the grader and the validator).
7. `DraftRequest.answer_only`: accepted.
8. Two ChatOllama clients (60 s and 180 s): accepted; one named constant per timeout with its reason.
9. `OllamaEmbedder` reused as-is for the /api/tags check: accepted (no refactor in T19).
10. Errata 119 and 120: accepted.
11. TODO(T19) hint markers removed (no task owns the hint): accepted; erratum 118 records the hint as not built in v1.

Process: one static critic round. A second runs only on a Critical finding or an Important one that changes code the
controller cannot check by diff. Lean, per the owner's steer.

---

# Round 1

## Plan P critic, round 1: static review of the plan before execution

Plan: `docs/superpowers/plans/2026-10-24-first-slice-p-drafting-route.md` (3776 lines, branch `plan-p` at `fbe940b`).
Read whole, against the controller's brief (20 rulings), the departure rulings, the fact sheet, AGENTS.md, the cited
BS/SA lines, `docs/CODE_COMMENTS.md`, revisions 0011-0013 and the code each edit touches.

**Verdict: REVISE.** Critical 0, Important 3, Minor 10.

None of the findings is a safety or authority break. Two Important findings are conditions the controller put on
accepted departures that the plan does not yet meet (I1, I2). The third (I3) is a budget that contradicts BS:555 in the
exact case R040 is about. All three can be checked by diff.

### What was checked and held

- **Anchors.** I applied every `Edit n` "replace" block of Tasks 1-6, in order, to an in-memory copy of the tree at
  `fbe940b` (a helper script under the critic scratch directory). All 54 apply exactly once except Task 6 Edit 3 (M4).
  I checked Task 2 Edit 3 (`tests/plan_d/test_worker.py:81`) by hand.
- **Prompts.** I extracted the two `text` blocks from the plan and hashed them: 2112 B / 12 LF lines /
  `6540c715…7b82` and 1430 B / 7 lines / `c0257f2a…85c1`. Both match the pinned values. `.gitattributes`
  (`* text=auto eol=lf`) keeps them LF on checkout. The starters still hash to `e3c26da3…a942` and `8b6658eb…c343`.
  `starter[6:11:2]` is lines 7, 9 and 11 of `incident-draft-v1.md`, the system message.
- **Validation.** I traced each refusal in `test_draft_validation.py` against `schemas/model-draft.schema.json`, jsonschema's
  error shapes (the `allOf/else/not` error sits at the root path, so `/question` is built correctly) and
  `contracts.Title` (`strip_whitespace=True, min_length=1`, so `string_too_short`). `EvidenceRef` has no pattern, so
  `"status"` reaches `not_offered`. The feedback never carries instance values.
- **Authority and safety.**
  - The model gets the request text, the asset, the interval, the excerpts, the allowed IDs and the schema. It gets no
    tool, credential, role, approval or action ID.
  - `build_proposal` takes only draft text fields. Action and destination stay code-set.
  - No payload is written to `drafts`, events or logs (rule names only), which satisfies SA:496.
  - Thinking is refused whole, never stripped, and never shown to the repair.
  - There is exactly one repair. No repair runs after a timeout or an outage.
  - No path falls back to the fake. `make_generator("fake")` never reads the pin.
  - The permit is released in `model_permit`'s `finally`, and also before `_fail` on the abstain and not-routed paths.
- **Revision 0014.** It follows 0013 exactly: the frozen `MAIN_GRANTEES`/`POLICY_ROLES`, `grant_statements` then
  `rls_statements`, the `tenant_isolation` policy name, `OWNER TO migrator`, and the composite FK to
  `runs(tenant_id, run_id)` as `drafts` has. It has no definer function. `qwen3:8b` in `op.execute` is safe from
  SQLAlchemy's bind regex (word-char lookbehind). The live catalog tests (`test_roles_live.py:85-120,264-275`) derive
  their tables from `privileges.GRANTS`/`RLS_TABLES`, so the new row is covered. The alembic heads in
  `test_migrations_and_persistence.py:212-239` are read dynamically. Every round-trip test ends in
  `migrate(Profile.TEST)` (head). No code path deletes runs outside `purge_run`/`purge_conversation`, and both use
  `PURGE_ORDER`.
- **Live tests, line by line** (`test_run_manifest_live.py`, the two `test_worker_live.py` edits):
  - PostgreSQL's `ExecInsert` runs the RLS WITH CHECK before `ExecConstraints`. So the BETA row raises
    `InsufficientPrivilege` and the digest-less real route raises `CheckViolation`, as written.
  - RI checks run with `SECURITY_NOFORCE_RLS`, so the FK holds under FORCE RLS.
  - `refused` wraps its own transaction. Every role in the list lacks INSERT, so each refusal returns 42501.
  - `new_run` returns `(tenant, conv, run)`.
  - `ScriptedMcp`'s `corpus_version` is `handoff-1`, which matches `MANIFEST`.
  - `RaisingGenerator(FakeDraftGenerator)` gets `route`/`digest`, and `FakeDraftGenerator` is already imported
    (`test_worker_live.py:21`).
  - `BlockingGenerator`/`PeekingGenerator` (`test_heartbeat_live.py:61,240`) already subclass the fake. No test generator
    lacks `route`/`digest`.
- **Counts.**
  - Test functions in the plan's code: 18, 17, 2 live, 3, 1 live, 9, 4. Dev 1540 → 1558 → 1575 → 1579 → 1589 → 1593 and
    skipped 219 → 221 → 222 are consistent. The live figures are dev + skipped − 21.
  - Collected today (`--collect-only`, no cache): `tests/plan_e` + `test_locking.py` = 128. With Task 3's 3 + 1 that is
    the plan's 132. `tests/plan_d` + `tests/plan_h` = 203; adding the lock-order case and plan_p's 47 + 2 gives the
    plan's 251 passed and 2 skipped.
  - `test_worker.py` (5) + `test_worker_azp.py` (3) = 8, which is "3 failed, 5 passed". `test_worker.py` +
    `test_permit.py` = 11, which is "2 failed, 9 passed".
  - The writer's logs show 1593/222 GREEN and the evidence run at 60/60 twice. The by-scenario figures sum to
    20/14/26 = 60.
- **Library behaviour** (read from the uv cache's `langchain_ollama-1.1.0` and `ollama-0.6.3`; nothing installed in the
  real tree):
  - `client_kwargs` reaches both httpx clients (`chat_models.py:944-958`).
  - `validate_model_on_init` defaults to False, so construction does no I/O.
  - `ainvoke` streams by default (`:802`).
- **Records.** The `t19_records.py` preconditions hold today: T19 is PLANNED with 2 notes, the milestone is M06, the
  seven rows are `NOT_RUN` with `[]`, and the BUILD_BACKLOG head line is unique. `note` is an existing row key (46
  rows). The ruling 19 statuses agree across the plan header, `t19_records.py`, STATUS and SESSION_STATE. The probe
  facts the permit docstring cites (0.15 s after the cancel) and the cold-call timeout match
  `reports/model-probe-qwen3-8b.md:13,18`. The 22 lock additions agree with `reports/model-probe-freeze.txt`.
- **Lean.** Nothing from T20/T21/T22/T25 is built. `on_attempt`/`Attempt` exist only for the evidence script (DoD 1).

### Critical

None.

### Important

#### I1. The departure-6 condition is not met: no test that the grader and the validator agree

- **Where:** plan lines 77-80 (departure 6); Task 1 Step 4 (`tests/plan_p/test_draft_validation.py`, lines 412-559).
- **What is wrong:** The controller accepted departure 6 "with a test that both judges agree on the sample drafts (no
  drift between the grader and the validator)". `draft_validation` re-implements the two-judge rule (schema, then
  `ModelDraft`) beside `grading.check_schema`. No test compares the two, and the plan never names `check_schema` in a
  test.
- **Evidence:** `scratchpad/planp/writer-departures-rulings.md` item 6; `grep check_schema` in the plan finds only
  lines 77 and 665 (prose); `core/src/ops_core/grading.py:272-286`.
- **Fix:** Add one parametrised test to `test_draft_validation.py`. Its cases are the sample replies already in the
  file: a valid proposal, answer and abstain; `question: null`; `kind: "report"`; the 121-character title; the
  whitespace-only title.
  - For each case, assert that `grading.check_schema(Output(draft=json.loads(text), offered_refs=ALLOWED,
    case=<any dev case>)).passed` is true exactly when `validate` either accepts the reply or refuses it only with
    `not_offered` or `proposal_on_answer_only`.
  - Equivalently, `schema`/`contract` refusals ⇔ `check_schema` fails.
  - Update the Task 1 count (18 → 18 + n) and every count after it.

#### I2. The departure-4 condition is not met: the committed real-run report does not say what was and was not sent

- **Where:** Task 5 Step 2, `render()` (plan lines 3206-3252); departure 4 (lines 69-73).
- **What is wrong:** The controller accepted departure 4 on condition that "the report must say so". The report must
  say that the run sends no status or alert records, and that each `injected` input carries its tenant's injected
  corpus section. Only the script's docstring says this. `reports/model/t19-real-run.md` says only "over the 60 probe
  inputs, with the v2 prompts and payload".
  - A reader of the evidence that R037/R036 cite therefore cannot tell why 40 of 60 drafts abstain, or where the
    injected text came from.
  - The BS:566 one-machine caveat is also missing from the report; only the R037 note carries it.
- **Evidence:** `writer-departures-rulings.md` item 4; plan lines 3211-3245.
- **Fix:** Add three sentences to `render()`:
  - No asset status or alert records are sent (the worker passes none until T20).
  - Each injected input also carries `ALPHA-VENDOR-PORTAL:v1:portal-note` or `BETA-CONTRACTOR-MEMO:v1:memo-note` as
    retrieved evidence.
  - One machine; not a capacity claim (BS:566).

  Then assert one of these lines in `test_the_summary_and_the_report_carry_the_rates_and_their_intervals`.

#### I3. The draft's 90 s budget is counted from `generate`'s start, not from what the run has left (contradicts BS:555)

- **Where:** Task 2 `_ask` (plan lines 1627-1635) and `BUDGET_SECONDS` (line 1452); debt line 335-337; the R040
  record text (line 3468, "one repair within what is left of the 90 s budget").
- **What is wrong:** BS:555 reads "Active compute duration | 90 seconds total; each model attempt max 60 seconds
  clipped to remaining budget". The codebase already reads that 90 s as per run, from the hold:
  `settings.py:324` (`compute_budget_seconds = 90  # BS:555: active compute per run`) and `heartbeat.py:180`
  (`now - lease.held_since >= compute_budget_seconds` → "compute budget spent").
  - The plan starts a second, independent 90 s at `generate`. Retrieval and the permit wait therefore always make the
    draft's budget outlast the run's.
  - The slow-repair case R040 is about then ends as a lost lease: cancel, hand-back, and the next owner's INTERRUPTED,
    after a lease lapse. It does not end as the templated `MODEL_UNAVAILABLE`/`MODEL_INVALID`.
  - The R040 note claims the remaining budget is respected.
  - The debt line declares the overlap (→ T29) but does not name BS:555 as the line contradicted.
- **Evidence:** BS:555 (FS §2.9); `core/src/ops_core/settings.py:324`; `worker/src/ops_worker/heartbeat.py:180`;
  `core/src/ops_core/lease.py:78` (`held_since`).
- **Fix (small, checkable by diff):**
  1. In `_draft_and_freeze`, compute what the run has left:
     `deps.leases.compute_budget_seconds - (lease clock now - lease.held_since)`, minus a small named margin.
  2. Pass it as a float on `DraftRequest` (a router-computed number like `answer_only`, so it carries nothing the model
     sees).
  3. In `_ask`, clip each attempt to `min(ATTEMPT_SECONDS, BUDGET_SECONDS - elapsed, request.remaining - elapsed)`.
  4. Add one unit test where a small remaining budget gives the repair less than `90 - first attempt`.

  If the controller prefers to keep the debt instead, reword the R040 note and the plan's claims to "within the draft's
  own 90 s", and name BS:555 in the debt line as contradicted until T29.

### Minor

#### M1. `ollama_chat` itself is untested, and its comment misdescribes the error path

- **Where:** lines 1531-1563, comment 1555-1556.
- **What is wrong:** Only the scripted `Chat` seam is unit-tested. The real function's exception mapping, raw text and
  `reasoning_content` extraction, and the choice between the warm-up and drafting clients run only in the live warm-up
  and the evidence script, and never on an error path.
  - ChatOllama streams by default (`langchain_ollama/chat_models.py:802`).
  - On the stream path, ollama 0.6.3 does not wrap `httpx.ConnectError` into `ConnectionError`
    (`ollama/_client.py:800-815`; only `_request_raw:764` does). The httpx branch still catches it, but the comment is
    wrong.
  - langchain-ollama raises `ValueError("No data received from Ollama stream.")` (`:1147`), which would surface as the
    generic "drafting failed".
- **Fix:**
  - Add one unit test: `ollama_chat("http://127.0.0.1:9")("s", "u", 5.0)` raises `ModelUnavailable`, the same loopback
    port-9 pattern the tags test uses.
  - Correct the comment: on the stream path a refused connection arrives as `httpx.ConnectError`.

#### M2. Synchronous file I/O on the event loop for every draft (SA:201)

- **Where:** lines 1503-1521, 1664, 1671.
- **What is wrong:** `payload()` re-reads `schemas/model-draft.schema.json`, and `prompts.text()` re-reads the prompt
  file, on the loop for every draft and every repair. SA:201 says "No synchronous I/O on the event loop".
- **Fix:** Read the two prompt texts and the schema once, in `OllamaDraftGenerator.__init__`/`ollama_chat` or behind
  `functools.cache`.

#### M3. The manifest is built outside any handler

- **Where:** Task 4 Edit 14, lines 2612-2628.
- **What is wrong:** `str(doc["data"]["corpus_version"])` and `RunManifest(...)` validation used to run inside the draft
  `try`. They now run before it. A malformed tool result (`KeyError`/`ValidationError`) escapes `investigate` with the
  run in RETRIEVING. The job stays claimed, the lease lapses, the sweeper reclaims it, and the run ends INTERRUPTED
  instead of a templated failure (`main.run_job`, `main.py:61-71`).
- **Fix:** Build the manifest inside the retrieval `try` and add `KeyError, ValidationError` to its "retrieval failed"
  except. Optionally record the `retrieval_mode` the tool reports rather than the constant asked for.

#### M4. Task 6 Edit 3's anchor is a prefix, shown as a whole line

- **Where:** Task 6 Edit 3, lines 3569-3579.
- **What is wrong:** `SESSION_STATE.md:43` continues after "`plan-n`;". The block is shown as a whole line ending in
  a newline, so an exact replace that includes the newline fails (my simulation: count 0).
- **Fix:** Say "replace this prefix of line 43 (the line continues)".

#### M5. Erratum 117 overstates where the route is recorded

- **Where:** lines 230-231, 3612-3615.
- **What is wrong:** `explanation.ready` is emitted only on the proposal path. Abstain, not-routed and failed runs emit
  none, so for them the route lives in the manifest alone.
- **Fix:** Add that sentence to erratum 117.

#### M6. T19's "future named model" is decided but not recorded

- **Where:** lines 151-152.
- **What is wrong:** T19's instruction reads "fake | qwen3:8b | future named model" (`tasks.json:834`, SA:379), and
  Plan C's final review deferred it to T19. Ruling 2's "no enum slot" appears in neither the debt list nor an erratum.
- **Fix:** Add one debt line ("a future named model is a later route-enum and schema change; no task") or fold it into
  erratum 119.

#### M7. The checkout dependency is wider than the pin

- **Where:** debt line 348, `TODO(T30)` at line 1449.
- **What is wrong:** The worker now also reads `schemas/model-draft.schema.json` from the checkout at runtime
  (`grading.DRAFT_SCHEMA`, `grading.py:45-46`, via `parents[3]`; lines 1520 and 1534).
- **Fix:** Name the schema too, in the debt line and the TODO.

#### M8. The history section is pre-written

- **Where:** lines 3727-3732.
- **What is wrong:** Section 34's "Review" paragraph is fixed before any review. It already asserts that "the three
  database live checks ran first on the executor's machine". The repository's history practice records each review
  round's problems and fixes.
- **Fix:** In Step 3, tell the executor to fold this critic round's findings, the live results and the final review's
  findings into that paragraph at close-out.

#### M9. Undeclared direct imports

- **Where:** lines 1428-1431; Edit 3, line 398.
- **What is wrong:** The worker imports `httpx`, `ollama` and `langchain_core` directly but declares only
  `langchain-ollama`. A future langchain-ollama release could drop or re-pin them under the worker. No gate checks
  this.
- **Fix:** Declare `ollama` and `langchain-core` (and `httpx`, or catch only `ollama` and LangChain types), or record
  why not.

#### M10. Answer-only runs always spend their first attempt

- **Where:** lines 1503-1521; departure 7.
- **What is wrong:** The model is never told a run is `answer_only`. Every such run therefore spends its first attempt
  on a proposal that is refused, and depends on the repair's feedback line.
- **Fix:** Answers are not routed until T20, so add a debt line → T20 ("the payload states that a proposal is not
  allowed"). No code change is needed now.

### Plan claims disputed and not settled

1. **Dev counts and lint.** `1593 passed, 222 skipped`, ruff/mypy strict clean and `verify_handoff` exit 0 are not
   re-run here. Installing langchain-ollama needs the network. The arithmetic and today's collection counts agree with
   them (see above), and the writer's `dev2.log` shows 1593/222 GREEN.
2. **The three database live tests.** They are consistent with PostgreSQL's insert-check order, the role grants and the
   fixtures, but never executed (departure 1). Watch Task 4 Step 5.
3. **The Ollama route tests' result may predate the last edit to `start()`.** The plan says the evidence script ran
   "one commit earlier, before … the order of one pin check in `OllamaDraftGenerator.start` changed", and it does not
   say whether `test_model_route_live.py`'s `2 passed` came before or after that change. The dev gate covers the
   reordered unit paths. The live pair should be confirmed in Task 2 Step 5 as written.
4. **Ollama's json-schema grammar.** That Ollama honours `allOf/if/then/else` in `format` is not established. It
   matters only for first-pass rates, because validation is application-side. The probe used the same wrapper.

---

# Round 1 — controller rulings

## Plan P round 1 — controller rulings (critic report: C:\Users\joeys\Desktop\MLOps\.superpowers\planp\round1-static.md)

Verdict REVISE: 0 Critical, 3 Important, 10 Minor. Everything is fixed as below, by the writer, in the plan file and on
a fresh scratch apply-and-gate. The controller checks the diff; there is no second static round (lean, per the owner).

### Important — all fixed as the critic proposes
- **I1.** Add the parametrised agreement test between `grading.check_schema` and `draft_validation.validate` to
  `tests/plan_p/test_draft_validation.py` (the critic's cases). Update Task 1's count and every later count.
- **I2.** `render()` gains the three sentences (no status or alert records sent; each injected input carries its tenant's
  injected corpus section; one machine, not a capacity claim, BS:566). Assert one in the report test. Re-render the
  committed report in Task 5 Step 4 from the run (the real run happens in execution anyway).
- **I3.** Take the code fix: compute the run's remaining compute budget in `_draft_and_freeze` from the lease clock and
  `held_since` (minus a named margin), pass it as `DraftRequest.remaining_seconds` (router-computed, never shown to the
  model), clip each attempt to `min(ATTEMPT_SECONDS, BUDGET_SECONDS - elapsed, remaining - elapsed)`, one unit test.
  Keep the debt line but make it say what still overlaps (the heartbeat's own cancel) and name BS:555.

### Minor — all fixed (cheap)
- **M1.** Unit test `ollama_chat("http://127.0.0.1:9")` → `ModelUnavailable`; correct the comment (stream path raises
  `httpx.ConnectError`). Also map `ValueError("No data received…")` from langchain-ollama to `ModelUnavailable`, with a
  comment naming the source line.
- **M2.** Read the schema and the two prompt texts once (in `__init__` or `functools.cache`), not per draft.
- **M3.** Build the manifest inside the retrieval `try`; add `KeyError, ValidationError` to its "retrieval failed" except.
  Record the `retrieval_mode` the tool reports.
- **M4.** Task 6 Edit 3: say the anchor is a prefix of line 43 (the line continues).
- **M5.** Erratum 117 adds: for abstain, not-routed and failed runs the route lives in the manifest alone.
- **M6.** Fold "future named model = a later route-enum and schema change, no task owns it" into erratum 119.
- **M7.** Name `schemas/model-draft.schema.json` in the checkout-dependency debt line and the `TODO(T30)`.
- **M8.** Task 6 Step 3: the executor writes section 34's review paragraph at close-out from the actual rounds (this
  critic round, the live results, the final review). Replace the pre-written paragraph with a placeholder and the
  instruction.
- **M9.** Declare `langchain-core`, `ollama` and `httpx` in `worker/pyproject.toml` at the versions the lock resolved;
  one `uv lock` still.
- **M10.** Debt line → T20: the payload states that a proposal is not allowed on an answer_only run.

### Disputed claims
1-2: accepted as stated (execution measures them). 3: Task 2 Step 5 confirms the live pair as written. 4: add one
sentence to the evidence report's method paragraph: validity is application-side; whether Ollama's grammar honours
`allOf/if/then/else` is not established and does not matter for the record.

Counts: update every stated count the new tests change (I1 n tests, I3 +1, M1 +1), and the arithmetic paragraph.

---

# Controller check of the round 1 fixes (8bbad58)

The diff fbe940b..8bbad58 touches only the plan (332 insertions, 137 deletions).
- I1: a parametrised agreement test (eight sample replies) asserts `grading.check_schema` passes exactly when
  `draft_validation.validate` passes its schema-and-contract stage.
- I2: `render()` states that no status or alert records were sent, that each injected input carries its tenant's
  injected corpus section, and the BS:566 one-machine caveat; the report test asserts it.
- I3: `DraftRequest.remaining_seconds` is computed from `Lease.held_for()` with a 5 s margin once the permit is held, so
  the permit wait counts against the run; each attempt is clipped to `min(60, 90 - elapsed, remaining - elapsed)`; one
  unit test; the debt line names BS:555.
- M1: `ollama_chat` is unit-tested against loopback port 9 and its comment corrected. M2: the schema and prompt texts
  are read once (`functools.cache`). M3: the manifest is built inside the retrieval `try`, whose except now lists
  `KeyError`, `ValidationError` and `ValueError`. M4-M8: the anchor note, erratum 117, erratum 119, the checkout debt
  line and the history placeholder are in. M9: `langchain-core`, `ollama` and `httpx` are declared at the resolved
  versions. M10: the answer_only payload debt line → T20.
- Counts: Task 1 +26, Task 2 +19 unit and 2 live, Task 3 +3 +1 +1 live, Task 4 +9 +1, Task 5 +4; dev 1603/222 after
  Task 5, measured; live 1804/21 arithmetic.

Accepted. Execution begins at 8bbad58.

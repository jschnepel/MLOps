# Plan P final review record — T19 the drafting route

Plan: `docs/superpowers/plans/2026-10-24-first-slice-p-drafting-route.md` (branch `plan-p` from `main` 3905b35; plan
fbe940b, round 1 fixes 8bbad58, plan review record ee2729d). Building tasks 30ad48d..737d1ab; close-out after. The
plan-stage record is `docs/reviews/plan-review-p-2026-10-24.md`.

What T19 delivers: the qwen3:8b drafting route through LangChain's ChatOllama in the AM-31 profile, selectable by
`MODEL_MODE` (`fake` | `qwen3:8b`, nothing else, no fallback); runtime prompts v2 as `ops-core` package data, pinned by
sha256; pure structural validation in `ops_core.draft_validation` (schema, contract, citation membership, thinking,
authority keys, `answer_only`) with one bounded repair fed instance-free feedback; the startup digest check against
`/api/tags` and a warm-up that fail closed; revision 0014 `app.run_manifests` (one immutable row per run, written before
the model is called, on both routes); one model permit across both attempts, each clipped to the run's remaining
compute budget; the four draft kinds routed (proposal freezes; abstain alone → INSUFFICIENT_EVIDENCE; answer and
abstain+question → FAILED until T20); and the recorded real-model run (`reports/model/t19-real-run.md`: 60/60 valid
first-pass drafts, against the probe's 5/60 with the starter prompt and an ID-less payload).

Final gates: dev `1629 passed, 222 skipped`; live (`--profile test`) `1830 passed, 21 skipped`; `verify_handoff.py` exit 0 (the plan predicted 1829 live; 1830 = 1629 + 222 − 21).

Holdout custody: no agent opened holdout case material or a seal. None exists in the tree. No agent connected to the
dev database (it stays at 0013; the worker refuses to start on it until `skeleton.py migrate`), Keycloak or any
service beyond local Ollama (read-only tags/version, and generation for the warm-up, the live route tests and the one
evidence run). No agent opened `.env` or a secret.

---

# Execution facts (controller's record)

## Plan P execution facts (controller's record, for the close-out)

### Before the plan

- 2026-10-20: PRs #12, #13, #14 merged into `main` at the owner's explicit request (da1db4b, f8145a4, 3905b35).
- 2026-10-21: the owner decided to remove the holdout seal ("remove holdout seal"); the permission system refused the
  agent's file listing and then its task-graph edit; the owner added one allow rule (`Bash(uv run python -I:*)`) and
  said "continue". Erratum 114 applied in d37f30c (dev 1540/219).
- 2026-10-24: T02's live probe ran (8b1c8b7): JSON-valid 59/60, schema-valid 5/60 (a `question` on proposal/answer
  drafts; no evidence IDs in the probe's payload), 0 thinking, cold call > 60 s, warm p50 2.77 s. Decision lines
  "proceed" and "release on cancel" recorded as PROVISIONAL.
- The owner chose to go ahead past T44 step 10 (pending).

### Plan stage

- Fact sheet 0db7ca4 (20 open questions); brief with 20 rulings.
- Plan fbe940b (11 writer departures, all accepted). The writer could not copy `.env` into the scratch copy (refused),
  so the DB live gate was never run before execution; live counts were arithmetic.
- One static round: REVISE 0C/3I/10M, 4 disputed claims (I1 missing grader/validator agreement test; I2 the evidence
  report silent on what was sent; I3 the 90 s budget counted from `generate`, not the lease, against BS:555). Fixed in
  8bbad58, controller diff check instead of a second round. Review record ee2729d.

### Execution

| Task | Commits | Review | What the review caught / fixed |
|---|---|---|---|
| 1 prompts v2, draft_validation, dependency, debt list | 30ad48d, 4a93805; fix 2a8a3c0 | opus, approved 0C/0I/6m | The APPLICATION_KEYS comment overclaimed; the agreement test's "exactly when" let non-structural refusals through; only one starter prefix was pinned; the validator lacked grading's FormatChecker; a weak "unchanged" assertion. All fixed; dev 1566/219 unchanged |
| 2 qwen3:8b route, router, start-up | 1400a9e; fix 22af4da | opus, needs fixes 0C/1I/7m | I1: langchain-ollama 1.1.0 drops Ollama's `thinking` field when `reasoning=False`, so the reasoning-metadata check is always None on the real route; docstrings corrected, erratum 121. The client timeout is a per-read backstop (wording). Real-chat error mappings, warm-up cut-off, repair timeout, spent budget and a failed version question tested (+7). Dev 1592/221 |
| 3 revision 0014 run_manifests | 44a060f; fix 1462dda | opus, needs fixes 0C/1I/5m | I1: the live "only the worker can insert" check could pass with every role granted (RLS gives the same 42501 with no tenant set); the tenant is now set and "permission denied" matched. Column set pinned; start-up check tested (+1). Live manifest test passed on first run. Dev 1597/222 |
| 4 handler wiring | 560aac1; fix 50cd297 | opus, approved 0C/0I/7m | Budget wiring untested (remaining = budget − held_for − 5 after the permit; ≤ 0 → FAILED) → 4 handler tests, mutation-checked; `str(corpus_version)` defeated the strict check; `_ask` now refuses an attempt with no time before any call; TTL pinned to the budget. First full live gate 1808/21. Dev 1612/222 |
| 5 evidence script and the real run | bf3e507, d339eed; fix e6ca466 | sonnet, needs fixes 0C/2I/8m (+ a spec gap) | The withhold path was tested only in isolation → `choose_samples` extracted and tested at both call sites; the report did not say the injected 12/12 is validity, not resistance (PR-003), nor give kinds per scenario → both added; a `--from-json` render path lets the markdown be corrected from the committed JSON without re-running the model; a hung nvidia-smi could have lost the run. `shown_text()` withholds a thinking attempt's text (Task 2 M6), +1 test. Real run: 60/60 valid first pass (Wilson [0.940, 1.000]), 0 repairs, 0 thinking, 20 proposals / 40 abstentions (26 with a question), p50 2.24 s, p95 3.07 s, warm-up 2.32 s — the plan's predictions exactly. PR-003: a valid proposal that restates and cites the injected note; validity is not support (T25). Dev 1617/222 |

### Final whole-branch review (opus, on ee2729d..e6ca466)

Ready to merge with fixes: 0 Critical, 2 Important, 10 Minor. The Important ones were record gaps: erratum 121 (the
reasoning channel) was cited in code but recorded nowhere, and two shortcuts the code takes had no debt line (the
30-minute `keep_alive` with a warm-up only at start, so an idle worker reloads the model inside a draft's 60 s attempt;
the skeleton's 90 s readiness wait against the 180 s warm-up budget). The minors: the real route's `answer_only`
wiring and the AM-31 ChatOllama settings were unpinned by any test (mutations passed); three start-up failures
(`SettingsError`, an unexpected warm-up error) exited with a traceback instead of the logged refusal; three lines over
120 characters; citation and docstring slips; the warm-up figure not labelled as possibly warm. One fix wave (code)
and the close-out (records) closed them; the controller checked the diff.

### Measured

The real run (`reports/model/t19-real-run.md`, qwen3:8b at the pinned digest, Ollama 0.40.4, langchain-ollama 1.1.0,
RTX 3080, one machine): with the v2 prompts and a payload carrying the allowed evidence IDs, 60/60 first-pass valid
drafts against the T02 probe's 5/60 with the starter prompt and an ID-less payload. No alerts or status records were
sent (T20 adds them), so most abstentions say the model lacks alert data. Validity is not support: no draft was graded
for groundedness, and the PR-003 sample shows a valid proposal can carry injected text (R036 is met by code — the text
cannot reach a tool, a grant or the destination — not by the model refusing it).

### Process slips (none ran code or opened holdout material)

- Task 1 implementer: a `python - <<'EOF'` with an empty heredoc; hung; stopped by task id; nothing ran.
- Task 2 implementer: a by-hand mypy run polluted `.mypy_cache` (removed, re-run GREEN).
- Task 4 implementer: a temp log written to the Desktop parent by mistake, deleted.
- Controller: none this plan.

### Owner inputs after T19

- Confirm or reverse the probe's provisional decision lines (proceed; release on cancel).
- Decide errata 1-121 (Plan P proposes 115-121).
- T44 step 10 (LAN check, firewall rules).
- Migrate the dev database to 0014 (`skeleton.py migrate`) before `skeleton.py up` on the dev profile; the worker
  refuses to start on 0013.
- Ollama 0.40.4 vs SA:587's 0.33.3.

---

# Final whole-branch review (opus)

## Plan P final whole-branch review (T19), `ee2729d..e6ca466`

Reviewer: one pass over the whole slice (12 commits) before the close-out task (Task 6). Inputs read: the plan (Global
Constraints, Rulings, Departures, debt list, errata, each task's requirements), the ledger `progress.md`, the five
task reviews and reports, the Task 6 brief, the diff file (`uv.lock` skimmed for names and removals), `AGENTS.md`-cited
spec lines (AM-12 SA:199-205, AM-16 SA:360-379, AM-31 SA:593-620, SA:496, AM-80 SA:770, BS:435-460, BS:514-518,
BS:547-566), the R036-R041/R127/R130 rows of `handoff/acceptance-matrix.json`, and `docs/CODE_COMMENTS.md`. The code was
read at HEAD `e6ca466`.

Checks run (read-only; nothing in the tree, index or branches changed; `git status --short` clean before and after):

- `ruff check --no-cache` and `ruff format --check --no-cache` on all 31 changed `.py` files: clean.
- `mypy` (strict, cache in the scratchpad) on the 15 changed non-test, non-migration sources: no error in any changed
  file; 2 pre-existing `type-arg` errors in `scripts/probe_stats.py` (unchanged here, pulled in by the evidence script;
  `scripts/check.py` runs mypy on the member source trees only, so the gate never sees `scripts/`).
- Focused unit tests, one file at a time: `test_draft_validation` 26, `test_investigate_drafting` 13,
  `test_draft_evidence` 12, `test_worker_startup` 1, `test_migration_0014` 3, `test_ollama_drafting` 25 (its two
  loopback port-9 tests deselected to keep to "no network"): all passed.
- A scratchpad helper (`scratchpad/planp/final/render_check.py`) rendered the committed `t19-real-run.json` through
  `draft_evidence.summarize` and `render` in memory: the Markdown and the summary equal the committed files byte for
  byte; 60 cases, 0 rules on any attempt, at most 1 attempt per case; injected kinds 6 proposals (PR-003, -007, -014,
  -020, -026, -030), 6 abstentions (2 with a question).
- `uv.lock`: exactly the 22 planned `[[package]]` additions, no removal. Commit messages: no attribution trailer.
  No `TODO(T19)` left in code; new markers `TODO(T20)`, `TODO(T25)`, `TODO(T30)` each have an owner.

### Verdict

**Ready to merge with fixes.** 0 Critical, 2 Important, 10 Minor. The code holds the authority, approval, idempotency
and no-unapproved-external-action boundaries end to end (traced below), the start-up fails closed, and the budgets
match BS:555. Both Important findings are records that Task 6 has not written yet and that its brief as written would
leave out: erratum 121 (which the code already cites), and two shortcuts the code takes that the debt list does not
name. Fold both into Task 6; the Minors can go into Task 6 or a follow-up.

### End-to-end traces (what holds)

Authority boundary, real route, `investigate`:

1. Claim → `investigate` (handlers.py:107): QUEUED → RETRIEVING and the read handle in one fenced unit; the MCP call
   is a lease effect; `RunManifest` is built inside the retrieval `try` from `deps.generator.route/digest`,
   `PROMPT_VERSION` and the tool's own `corpus_version`/`retrieval_mode` (handlers.py:155-162), so a `KeyError`,
   pydantic `ValidationError` (a `ValueError`) or `ValueError` ends as the templated "retrieval failed" (:163-166).
2. RETRIEVING → DRAFTING and `insert_run_manifest` in one unit after `set_tenant`, `fenced`, `transition_run`
   (:171-179): written before the model is called, on both routes; the order is pinned by
   `test_the_manifest_is_written_with_drafting_before_the_model_is_called` and the `OBSERVED_UNITS` row.
3. One permit for both attempts (:203); `remaining_seconds = compute_budget − held_for() − 5` computed inside the hold
   (:212), tested with a stepped clock (73.0 s; 1 s; 0 s → no call, FAILED/MODEL_UNAVAILABLE, one release).
4. The model sees `payload` only (ollama_drafting.py:131-149): request text, asset, interval, evidence (no
   `content_sha256`), allowed IDs, schema. No tool, role, approval, token or handle; `answer_only` and
   `remaining_seconds` never reach it; `with_structured_output(method="json_schema")` binds `format`, not tools.
5. Every reply goes through `draft_validation.validate` before anything reads it (:287-301); the repair is shown the
   failed text only when the rule is not `thinking` (:152-156); a second failure is `ModelOutputInvalid(rules)`.
6. Kinds (handlers.py:215-221): bare abstain → INSUFFICIENT_EVIDENCE; answer or question → FAILED/NOT_ROUTED; only a
   proposal reaches `freeze_allowed` (SA:453) → `build_proposal` → `drafts` row with sha and kind only (SA:496) →
   `explanation.ready` whose message is a template (route, prompt version) and whose refs are validated members →
   `freeze_proposal`. `answer_only` is refused three times over: validation (`proposal_on_answer_only`),
   `freeze_allowed`, and the definer.
7. Failure ends: `ModelUnavailable` → FAILED/MODEL_UNAVAILABLE; `ModelOutputInvalid` → FAILED/MODEL_INVALID (logged as
   rule names only); anything else → FAILED "drafting failed"; `LeaseLost` re-raised for `abandon`. No path falls back
   to the fake. The permit's release is in `model_permit`'s `finally` (permit.py:73-77), so it runs on success, every
   exception, a lost lease (effect cancellation arrives as `LeaseLost`) and a worker stop.

Start-up (main.py:143-161): `start_route` runs before any database connection or claim; a bad `MODEL_MODE` (`ollama`
included), a missing or malformed pin, another pinned model, an absent model, another digest, an unreachable Ollama
and a failed or hung warm-up are each `ModelStartError` → `log.error` + exit 1; then `assert_relation` for 0014 stops a
worker on an un-migrated database before the poll loop (unit-tested by order). Exceptions to the clean path: Minor 3.

Budgets: 60 s per attempt (`ATTEMPT_SECONDS`), 90 s per draft (`BUDGET_SECONDS`), clipped to the run's remaining
budget, an attempt with ≤ 0 s never enters `_chat` (ollama_drafting.py:276-279), a first-attempt timeout or outage is
never repaired (:313 raises before :317), permit TTL 95 s pinned to the budget (`test_permit.py:67-68`).

Seams: `PROMPT_VERSION` is `prompts.DRAFT_VERSION` = `incident-draft-v2` in the prompt pin test, the manifest, the
proposal payload (`proposals.py`), the plan_d and live fixtures, the handler template and the report; the `v1`
strings left are the starters, schema examples and `test_mcp_write_live.py`'s hand-built payload, none of which is a
worker hash fixture. `DraftInvalid` (a `ValueError`) is caught only around `validate`; the chat's `except ValueError`
wraps only `ainvoke`. Every rule name in a log, the report or a test is one `Rule` the validator emits.

### Findings

#### Critical

None.

#### Important

**I1. Erratum 121 is cited in code but recorded nowhere, and Task 6 as briefed would close without it.**
- Where: `worker/src/ops_worker/ollama_drafting.py:24` ("The route relies on Ollama honouring `think=false`
  (erratum 121)"); the ledger's Task 2 entry ("ruled docstring correction + erratum 121 at close-out"). The plan's
  errata list stops at 120 (plan lines 245-267), and the Task 6 brief says "errata 115-120" throughout (its title,
  lines 59, 193-194, 237, 301-302, 334, 388). The debt list in `SESSION_STATE.md` has no line for it either.
- Why it matters: the residual risk behind it is real and silent. Under AM-31's `reasoning=False`,
  langchain-ollama 1.1.0 drops Ollama's separate `thinking` field, so `Reply.reasoning` is always None on the real
  route and `has_thinking` sees inline tags only (BS:460, R039). The report correctly says "0 means no think tags";
  the owner still has to be asked to accept that, and a code comment citing an erratum that no record proposes is
  exactly the dangling reference CODE_COMMENTS rule 8 forbids.
- Fix (Task 6): add erratum 121 to the "Proposed errata" block, the handoff notes and the commit message ("errata
  115-121", "Seven errata"): "AM-31 (SA:596) with BS:460/R039: under `reasoning=False` langchain-ollama 1.1.0 does not
  surface Ollama's `thinking` field, so the route detects thinking only as inline `<think>` tags and relies on Ollama
  honouring `think=false` (T02 probe: 0 of 130 calls showed inline thinking); seeing the field needs a direct
  `ollama.AsyncClient.chat` or a library change, an AM-31 change the owner decides." Add the matching residual-risk
  line to the debt list ("→ owner (erratum 121)").

**I2. The debt list misses two shortcuts the code takes.**
- (a) `KEEP_ALIVE = "30m"` (ollama_drafting.py:73): the warm-up runs once, at start. A worker idle for more than 30
  minutes finds the model unloaded, and the next draft pays the reload inside its 60 s attempt. The probe measured a
  cold call over 60 s (round-4: 53 s; plan: 10.3 s from the page cache), so after an idle spell a run can end
  FAILED/MODEL_UNAVAILABLE with nothing wrong but timing. Not in the debt list, the report or the runbook.
- (b) `scripts/skeleton.py:462` waits 90 s for every process's readiness, while the worker's start may take the
  digest check plus a 180 s warm-up before it serves `/health/ready`. `skeleton.py up` with `MODEL_MODE=qwen3:8b` and
  a cold model can report "not ready" and stop the stack. The Task 2 review raised this as a ⚠️ and no record took it.
- Fix (Task 6): two debt lines, for example "the model is warmed once, at start; with `keep_alive=30m` a worker idle
  longer reloads it inside a draft's 60 s attempt, and a slow reload fails that run → T30 (readiness and
  re-warm-up) or T29" and "`skeleton.py up` waits 90 s for readiness, less than the real route's 180 s warm-up
  budget; the skeleton default stays `fake` → T30". (Alternatively `keep_alive=-1`, but that is a code change.)

#### Minor

**M1. The `answer_only` wiring inside the real route is untested.** `ollama_drafting.py:293` passes
`answer_only=request.answer_only` to `validate`. Mutation `answer_only=False` there passes every test:
`test_draft_validation` calls `validate` directly, and `test_an_answer_only_run_asks_for_an_answer_only_draft`
(test_investigate_drafting.py:220-227) uses the fake route, whose proposal is stopped by `freeze_allowed`, so its
`"freeze_proposal" not in log.entries` holds through the later guard. Safety holds (freeze_allowed and the definer),
but the repairable refusal departure 7 exists for, and that the debt line's "relies on the repair's feedback" assumes,
is never exercised. Fix: one test in `test_ollama_drafting.py`: a request with `answer_only=True`, replies `GOOD`
then an `answer` → second call's `validation_errors == ["/kind: this request allows only answer or
abstain"]` and the result is the answer; optionally a handler test on the real route ending FAILED/MODEL_INVALID.

**M2. AM-31's ChatOllama settings are not pinned by any test, and the report's parameter line is literal text.**
`ollama_chat` (ollama_drafting.py:164-180) is tested only for its error mappings. Mutations that pass every test:
`temperature=0` → anything, `num_ctx`/`num_predict` changed at the call, `keep_alive` dropped, `include_raw` kept but
`method` changed, and `runnable = drafting` always (the warm-up would then get the 60 s client: departure 8 undone).
`draft_evidence.py:303-307` writes "reasoning=False … temperature=0 … json_schema" as a literal, so the evidence would
keep claiming them after such a change. Fix: one unit test that builds `ollama_chat` with `ChatOllama.__init__`
recorded (or inspects the bound runnables) and asserts both instances' `reasoning is False`, `temperature == 0`,
`num_ctx`, `num_predict`, `keep_alive`, client timeouts 60/180, and that `seconds > 60` selects the 180 s one.

**M3. Three start-up failures skip the clean "refuses to start" exit.** main.py:143-149 catches `ModelStartError`
only. An unset `MODEL_MODE` raises `SettingsError` from `settings.env` (settings.py:30-35); `settings.urls()` inside
`from_settings` can raise `SettingsError`; a warm-up `ValueError` other than the empty stream escapes `chat` (:191-192)
and `start` (:262 catches only `TimeoutError`/`ModelUnavailable`). Each still exits non-zero, with a traceback instead
of the logged line, and the comment at main.py:144 ("Unset or any other route refuses to start") reads as if it went
through the same path. Fix: catch `SettingsError` in `start_route` (or main) as `ModelStartError`, and map any warm-up
exception to `ModelStartError` naming its type.

**M4. Three lines over 120 characters** (Global Constraints: ≤120): `scripts/draft_evidence.py:164`, `:207`, `:215` are
123 characters each. ruff passes because its default rule set has no `E501`. Re-wrap the string literals (the
rendered Markdown need not change).

**M5. `handlers.py:58`'s marker disagrees with the debt list.** `TODO(T25)` for choosing the retrieval mode per run;
the debt line says "→ T20 and T25". Make them one.

**M6. Erratum citations incomplete.** Erratum 120 (the new `run_manifests` AM-20.2/AM-20.5 row) is cited nowhere in
code, while the parallel corpus rows cite erratum 95 (`privileges.py:20`); add it at `privileges.py:152-154` and the
0014 docstring (line 12). Erratum 117's wording should say outright that the digest SA:379 also names for
`explanation.ready` lives in the manifest only (the template carries route and prompt version).

**M7. Two docstring sentences in `draft_validation.py` overclaim.** Line 4, "Nothing is repaired, stripped or coerced
here": `ModelDraft` strips surrounding whitespace and NFC-normalises every text field (`contracts.py:78-82`); the
agreement test even relies on it (`"x" * 119 + "  "` accepted). Say "beyond `ModelDraft`'s own normalisation; thinking
is never stripped". Lines 7-8: add that the real route cannot observe the metadata channel (erratum 121), as
`ollama_drafting`'s docstring now says.

**M8. `handlers.py:5-9` module docstring left unreflowed:** line 8 ends at "(BS:516). `execute`: mint" and the
sentence continues on line 9 (CODE_COMMENTS rule 10; the same kind of nit as Task 3's M5).

**M9. A plan_h test now loads LangChain.** `tests/plan_h/test_permit.py:20` imports `ops_worker.ollama_drafting`
for `BUDGET_SECONDS`, against departure 5's "the fake route and its tests never load LangChain". Harmless at runtime;
moving `BUDGET_SECONDS` (and `ATTEMPT_SECONDS`) to `ops_worker.drafting` keeps the separation the departure claims.

**M10. The report's warm-up figure is not labelled warm.** `reports/model/t19-real-run.md:14` gives "Warm-up (digest
check and first call) 2.32 s"; the model was already resident from earlier runs (the plan measured 10.3 s on a first
run, 1.7-2.0 s after), so a reader can take 2.32 s as a cold start, which AM-31 asks to keep separate. One clause in
`render` ("the model may already have been loaded; not a cold-start figure"), re-rendered with `--from-json`.

### Points checked and cleared

- `test_a_tampered_pin_fails_closed_before_anything_is_generated` and the parametrised fail-closed unit test both
  assert that no chat call happened; `test_start_checks_the_digest_before_warming_the_model` shares one event list.
- `test_a_run_budget_already_spent_gives_the_attempt_no_time` would fail if `_chat` were entered (a float answer
  sleeps, then `pytest.fail`), so the ≤ 0 guard is mutation-tested.
- `test_run_manifest_live.py:41-48` now sets the tenant before the refused insert and matches "permission denied",
  so RLS cannot stand in for the missing grant (Task 3 I1 fixed); the UPDATE/DELETE half discriminates.
- The committed JSON and Markdown agree (re-rendered in memory); no attempt text of a thinking reply exists to leak;
  `choose_samples` routes both sample sources through `shown_text`, and deleting either call fails a test.
- The report claims only what the run supports: validity ≠ support (BS:452), injected 12/12 is validity not
  resistance with PR-003 named, R036 met by code, thinking counts inline tags only, no status or alert records sent,
  one machine (BS:566).
- `RunManifest` strictness: `corpus_version` is passed unconverted (Task 4 M2 fixed), so a non-string is a
  `ValidationError` → "retrieval failed".
- Every changed file is in the plan's file list or has a recorded reason (`lease.py`, Task 4 Edit 17;
  `test_worker_startup.py`, Task 3 fix round M4).

### Residual risks to record

1. Thinking in Ollama's separate field is invisible to the route (erratum 121, I1); the defence is Ollama honouring
   `think=false`.
2. A valid proposal can restate injected text (PR-003, and 6 of 12 injected inputs became proposals); only the
   independent approval path stands between it and an incident. Support grading → T25; safe display → T26.
3. Idle unload after 30 minutes and the skeleton's 90 s readiness wait (I2).
4. On the real route an `answer_only` run cannot end well before T20: a proposal is refused (then repaired), an
   answer or question ends FAILED/NOT_ROUTED. On the fake route every `answer_only` run ends "drafting failed" with a
   logged traceback (`freeze_allowed`), as before this plan.
5. The heartbeat's own compute gate can still cancel a draft (LeaseLost, INTERRUPTED) and a long permit wait leaves
   no draft budget (debt → T29).
6. The DB live tests last ran at Task 4's live gate (1808/21); Tasks 4-5 fix rounds touched no database code, and
   Task 6's live gate is their next run. `scripts/draft_evidence.py` is outside the mypy gate (manually clean).
7. The real-model evidence is one run on one machine; the dev database stays at 0013 until the owner migrates it, and
   the worker refuses to start on it until then; the api has no 0014 start-up check (it reads no manifest yet).

---

# Controller rulings on the final review

## Plan P final review — controller rulings (review: C:\Users\joeys\Desktop\MLOps\.superpowers\planp\final-review.md)

Verdict: ready to merge with fixes. 0 Critical, 2 Important, 10 Minor. One fix wave (code) now; the record findings go
into the close-out task; the controller checks the diff.

### Records (close-out, Task 6)
- **I1.** Erratum 121 is recorded: under `reasoning=False` langchain-ollama 1.1.0 drops Ollama's separate `thinking`
  field, so the runtime detects inline `<think>` tags only and relies on Ollama honouring `think=false`; the T02 probe
  (same configuration) measured 0 inline thinking over 130 calls. Every "errata 115-120" becomes "115-121".
- **I2.** Two debt lines: (a) `KEEP_ALIVE="30m"` with a warm-up only at start — an idle worker reloads the model inside
  a draft's 60 s attempt and a slow reload ends that run FAILED/MODEL_UNAVAILABLE (→ T22/T29 with the bounded retries,
  or a periodic keep-warm); (b) `scripts/skeleton.py` waits 90 s for readiness while the real route's warm-up budget is
  180 s (→ T30, the container topology; until then start the worker on the real route with a warm model).
- **M5.** The retrieval-mode debt line and the `TODO(T25)` marker agree: T25 (the fix wave changes nothing there).
- **M6 (wording).** Erratum 117 says outright that the digest SA:379 names for `explanation.ready` lives in the
  manifest only; the template carries route and prompt version.
- **M10 (wording).** The report's warm-up figure is labelled as possibly warm (the fix wave re-renders).

### Code (fix wave, one sonnet implementer)
- **M1.** One test in `test_ollama_drafting.py`: `answer_only=True`, replies GOOD then an answer → the second call's
  `validation_errors == ["/kind: this request allows only answer or abstain"]` and the result is the answer.
- **M2.** One unit test pinning the AM-31 settings on both ChatOllama instances (`reasoning is False`,
  `temperature == 0`, `num_ctx`, `num_predict`, `keep_alive`, client timeouts 60/180) and that `seconds > 60` selects
  the 180 s runnable.
- **M3.** `start_route`/main: a `SettingsError` becomes `ModelStartError`; any warm-up exception maps to
  `ModelStartError` naming its type; the comment at main.py:144 stays true. Tests for both.
- **M4.** Re-wrap the three 123-character lines (rendered Markdown unchanged).
- **M6 (code).** Cite erratum 120 at `privileges.py:152-154` and in the 0014 docstring.
- **M7.** Correct the two `draft_validation.py` docstring sentences.
- **M8.** Reflow `handlers.py:5-9`.
- **M9.** Move `BUDGET_SECONDS` and `ATTEMPT_SECONDS` to `ops_worker.drafting` (re-exported or imported by
  `ollama_drafting`); `test_permit.py` imports from `drafting`.
- **M10.** Add the clause to `render` ("the model may already have been loaded; not a cold-start figure") and
  re-render both report files with `--from-json`; the model is not re-run.

Gates after the wave: dev, verify_handoff; no live gate (no live test changes) — Task 6 runs the final live gate.

---

# Controller check of the fix wave (737d1ab) and the close-out

The fix wave touched 13 files (141 insertions, 38 deletions): the `answer_only` test on the real route and the AM-31
settings test, both mutation-checked (`answer_only=False`, `temperature=1` each fail); `SettingsError` and any warm-up
exception now end in the logged refusal with a non-zero exit (three tests); `BUDGET_SECONDS` and `ATTEMPT_SECONDS`
moved to `ops_worker.drafting` so the fake route's tests load no LangChain; erratum 120 cited in `privileges.py` and the
0014 docstring; the `draft_validation` docstring no longer overclaims; the three long lines wrapped; the warm-up figure
labelled as possibly warm and the markdown re-rendered with `--from-json` (the JSON byte-identical). One slip: the
implementer's one-off edit scripts wrote CRLF into six files; the text-hygiene test caught it and the files were
converted back with no content change.

The close-out (Task 6) recorded erratum 121, the two missing debt lines, erratum 117's wording, and the review
paragraph of history section 34 from the actual rounds. Final gates: dev `1629 passed, 222 skipped`; live (`--profile test`) `1830 passed, 21 skipped`; `verify_handoff.py` exit 0 (the plan predicted 1829 live; 1830 = 1629 + 222 − 21).

Accepted. Branch `plan-p` is ready for its PR against `main`.

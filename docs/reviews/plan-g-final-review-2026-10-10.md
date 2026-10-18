# Plan G final review record — T12 durable admission API, Idempotency-Key and error mapping

Branch `plan-g`, executed range c5d3bbc..91ed4a4 (seven tasks, each with one task review and one fix round;
ledger `.superpowers/sdd/2026-10-10-first-slice-g-admission-idempotency/progress.md` at the time). The
whole-branch review below ran on the most capable model after Task 7; the controller ruled on every finding;
one fix wave applied the accepted ones; a scoped re-review verified them. The task-scoped reviews are summarised
in `docs/PROJECT_HISTORY.md` section 24.

---

## Whole-branch review

## Plan G final whole-branch review (T12, c5d3bbc..91ed4a4)

Reviewer: senior reviewer (security, databases, web services). Read-only; no live suite run.

How the branch was reviewed, in passes:

1. `git diff --stat` and the commit list (14 commits, 48 files).
2. The new API modules in full: `api/src/ops_api/idempotency.py`, `limits.py`, `app.py`, `store.py` (all 1,152
   lines), against plan rulings 1-30 and execution rulings (a)-(g).
3. The router and parser (`core/src/ops_core/routing.py`), the core diffs (`contracts.py`, `persistence.py`,
   `privileges.py`, `settings.py`), revision 0006, the sweeper diff, the `create_run` body in revision 0003.
4. Tests and fakes: `tests/plan_g/fakes.py`, the setup of `test_api_admission.py`, the live module's clean-up,
   `tests/e2e/conftest.py`, `test_migration_0006_live.py`, `scripts/check.py`'s pytest call.
5. Records: evidence file, `tasks.json`, `acceptance-matrix.json` (R015-R018, R115, R129), `BUILD_BACKLOG.md`,
   `SESSION_STATE.md`, `STATUS.md`, runbooks, READMEs; line lengths (characters) and CRLF in every changed `.py`;
   attribution and vendor names in the diff.

What was run: `pytest tests/plan_g` (124 passed); a router probe script over 15 adversarial texts (pure
functions); an HTTP probe through `create_app` over the shared `FakeStore` (no database). Gate counts 805/104 and
888/21 were not re-run here (they need the full stack); they are taken from the ledger.

### Strengths

- **The idempotency core is small, correct and well placed.** `idempotent()` (`idempotency.py:151-170`) does
  lock, lookup, replay-or-conflict, work, record-last in the caller's transaction. The scope is
  (tenant, subject, route template, key); the fingerprint covers the path parameters and the validated, NFC'd body.
  A reused key on another conversation is 409, as ruling 2 intends. The record is written last, so a crash before
  commit leaves nothing (R015 proved live with the fault: `[0, 0, 0, 0]`).
- **What is and is not recorded is principled and enforced in one place.** 401/403/the 422s before the body/429/
  503/`IDEMPOTENCY_CONFLICT` are raised out of the unit (rollback), never returned as verdicts. `QueueFull` in
  particular is raised, not recorded, so the same key succeeds once the queue drains; that matches what a client
  would expect from `Retry-After`.
- **Identity before record on every route.** `browser_mutation`/`requester_mutation`/`reviewer_mutation` run as
  dependencies before `idempotency_key` and the unit, so a revoked member (401) or a demoted reviewer (403) cannot
  replay a recorded success. The probe confirmed the conversation route goes through `browser_mutation`.
- **The replayed-error request id is rewritten** (`replay`, `idempotency.py:141-148`), so the body, the
  `X-Request-Id` header and the log agree on replays; success bodies carry no id, so their bytes are identical
  (the probe: `a.content == b.content`, distinct headers).
- **The error surface is closed.** `SafeErrors` as the outermost ASGI layer catches what Starlette would re-raise.
  It logs one line with the class name only and never re-raises. The probe got the safe schema for framework 404
  and 405 (with `Allow`), a bad JSON body, `1e999`, a 5,000-digit integer, 30,000-deep nesting and an oversized
  body, each with `X-Request-Id`. The SQLSTATE-based retryable split (execution ruling (a)) is the right fix for
  psycopg's flat class-54 siblings. The redaction filter is untouched and still installed first
  (`__main__.py:25-26`).
- **`BodyLimit` counts the bytes that arrive, not the declared length,** refuses a non-digit or 20+ digit
  `Content-Length` before `int()`, and never hands a half body to a route on disconnect (`limits.py:95-155`). This
  is better than Starlette's own middleware, which answers after the route ran.
- **Grant discipline holds.** Every statement `api` runs fits sel+ins: a target-less `ON CONFLICT DO NOTHING` for
  the record and the `resume_input` job, an identity column instead of a serial. The run lock uses the column
  UPDATE Plan E already granted. `GRANTS_0006` equals the `privileges.GRANTS` row; `NO_RLS` gains the table.
- **The clarifications unit is careful.** It runs FOR UPDATE on the run before any check, then a savepoint around
  message + job + event, so a refused reply leaves the unit able to record its 409/404. Dedup on
  `<run_id>:<question_id>` makes "already answered" a database fact, not a read-then-write race.
- **Clarify templates echo nothing a user typed freely.** Only regex-bounded ids (`[A-Z0-9_-]`), integers and
  numbers that `said()` renders. A later UI cannot be handed injected markup through a stored question.
- **Migration 0006** is frozen the 0005 way. Its downgrade refuses rather than deleting system messages. The live
  test upgrades a database that already holds messages. The comment on `seq` numbering of pre-0006 rows is honest.
- **The fake runs the real orchestration** (`FakeStore(AdmissionStore)`) with copy-on-entry/restore-on-raise
  units, so the HTTP tests exercise the SQL path's control flow. The "check before write" savepoint stand-in is
  the fake's declared contract, and the recording-connection test plus the live savepoint proofs back it.
- **The records are honest.** The evidence lines carry values, not adjectives. The ledger's deferred items are
  owned. `tasks.json`/the matrix/`SESSION_STATE.md` agree with the code. Errata 35-44 each name the text they
  amend. Every changed `.py` is at most 120 characters per line with LF endings, and the diff adds no attribution
  trailers or vendor names.

### Issues

#### Critical

None.

#### Important

**I1. A window number above about 1e308 makes the parser raise `OverflowError`, so a message that should be a
clarification becomes a 503.** `core/src/ops_core/routing.py:151` and `:157-167`.

- What is wrong: execution ruling (c) widened `TEXT_WINDOW`'s number to "any number of ASCII digits". `said()`
  then formats a window that is not whole minutes through `float(seconds)`. With a numerator past the double
  range, Python raises `OverflowError: integer division result too large for a float`. Reproduced:
  `"Investigate A17 last 1" + "0"*400 + ".5 seconds"` raises from `route_admission` both with and without form
  fields. Over HTTP it answers 503 `UNAVAILABLE` "service error", `retryable: false`, and logs an ERROR line. A
  whole-hours number of about 4,000 digits does not crash, but it produces a 4,052-character question that is
  stored as a message and returned.
- Why it matters: any requester can turn admission into a server-defect response and an ERROR log line with
  about 420 bytes of text. The plan's promise is "a disagreement, a missing field the text cannot fill, or an
  ambiguous text becomes a stored clarification, never a guess". Here it becomes neither. The record is not
  written, so the client sees a non-retryable "service error" for its own typing. A reasonable person typing a
  silly window expects "the window must be between 1 and 168 hours". This is a deviation introduced by an
  execution ruling, not by the plan (the plan's `\d{1,4}` could not reach it). The Task 3 re-review probed only up
  to `10**30` (`test_routing_admission.py:300`).
- How to fix: keep reading every number, but bound what `said()` renders. For example, treat any window over a
  cap (say 10**6 hours, far outside 1-168) as out of range and render it as "more than 1,000,000 hours". Or format
  without float: `Fraction` → `Decimal` with a quantize, or integer arithmetic for two decimals. Add tests for a
  300+ digit decimal, a 300+ digit integer, and a 4,000-digit integer (question length bounded).

**I2. A form asset that is one of several assets named in the text starts a run.** `routing.py:201-203`. This is
a plan defect in ruling 12; the code follows the plan.

- What is wrong: `if ids and asset not in ids` accepts the form asset when the text names it among others.
  Reproduced over HTTP: text "B22 is failing, A17 is fine; last 24 hours" with form `{asset_id: A17, hours: 24}`
  answers 202 and starts an investigation of A17.
- Why it matters: BS:297 says structured fields take precedence only when they agree, and to ask rather than
  guess. A text naming two assets does not agree with a form naming one; the form is the stale input a person
  most often forgets to change. The plan's own window rule says the opposite for the same situation: "two windows
  ask even beside a form window that equals one of them: which one the text meant is the doubt" (`routing.py:212`,
  ruling 12). Without a form, the same text is `asset_ambiguous` (probe). So the asset rule is inconsistent with
  its sibling and with the no-form case. The effect is a read-only investigation of the wrong asset. It surfaces
  later as a draft a reviewer must catch, so it is not Critical. R129's "never starts work on unroutable input"
  is not breached in letter, but BS:297 is breached in spirit.
- How to fix: mirror the window rule: `len(ids) > 1` is `asset_ambiguous` with or without a form asset (and
  `asset_conflict` stays for one id that differs). Amend ruling 12's text in the close-out record and add a router
  row test plus an HTTP test.

#### Minor

**M1. Parser blind spots let the form win against a text that plainly names another asset or window.**
`routing.py:88`, `:94-100`. Probe results with form `B22`/24:

- "investigate a17 ..." (lower case), "asset_A17" (no `\b` after `_`), "éA17" (a Unicode letter before it) and
  "A１７" (full-width digits) all start B22.
- With form A17/24, "previous 48 hours" and "last two days" start 24 h.

The plan accepted the window phrasings ("two days", "previous") and argued that lower case is not an `AssetId`.
The lower-case argument is about the contract, not about what a person types. Suggested: detect conflicts
case-insensitively and with `(?<![A-Za-z0-9])` / `(?![A-Za-z0-9])` lookarounds instead of `\b` (upper-case the
match before comparing). Any false positive asks a question, which is the safe direction. Owner: a later parser
pass (the ledger already parks "1,00" and other-script digits there).

**M2. A recorded 409/404 replays for 24 h, but the runbook tells clients to reuse the key "for a retry".**

- Where: `docs/runbooks/dev-topology.md:98` and `:105`; `api/README.md`.
- AM-16 mandates recording `SLOT_OCCUPIED` and the reply's `VERSION_CONFLICT`.
- A client that retries the same request after the active run ends, under the same key as the runbook says,
  gets the recorded 409 back for the whole window. Only the 429 is explained as "retry with the same key".
- Add one sentence: a 4xx answer other than 429 is final for its key, and a new attempt needs a new key.

**M3. Any `Conflict` from `create_run` is recorded as `SLOT_OCCUPIED`.** `store.py:538-542`, with `map_refusal`
(`store.py:171-179`) mapping every unknown refusal code to `Conflict("VERSION_CONFLICT")`. Today `create_run`
refuses only `INVALID_ARGUMENT` and `SLOT_OCCUPIED`, so this is latent. But a future refusal code would be
recorded for 24 h as a 409 with the wrong code and message. Branch on `exc.code` (as `decide_once` does with
`ErrorCode(exc.code)`), and treat an unexpected code as `Internal`. The ledger records the sibling issue in
`decide_once`.

**M4. The new run-row lock can stall the whole API.** `store.py:913-917` with `persistence.Session`
(`persistence.py:136-151`, one connection, one asyncio lock). T12 adds the first API-side `FOR UPDATE` on `runs`.
While a worker transaction holds that run row, every other request of every tenant waits behind the session lock,
including `/health/ready` and identity resolution. No `lock_timeout` is set. The pool is a known TODO(T13). Until
then, `SET LOCAL lock_timeout` in the unit (a 55P03 is an `OperationalError`, already mapped to a retryable 503)
would bound the stall. Record it in the T13 debt line.

**M5. A window of whole hours with thousands of digits is echoed in full into a stored question.** For example,
a 4,052-character `interval_out_of_range` question. This is not a crash, and the I1 fix (cap the rendered value)
removes it.

**M6. The quota count runs for every message kind.** `store.py:394` reads `queued_count()` before the router,
including for status questions and clarifications that never use it. One wasted query per such message; moving
the read into the run branch keeps ruling 21's order for runs.

### Recommendations

1. Fix I1 and I2 before merge. Both are small, local to `routing.py`, and have obvious tests. Record I2 as an
   amendment to ruling 12 in `SESSION_STATE.md`'s execution rulings, and I1 as a correction to ruling (c).
2. Add M2's sentence to the runbook and the API README in the same commit; it is the one client-facing contract
   gap a person will meet.
3. Add a property test over `route_admission`: random texts built from asset tokens, windows and noise, with and
   without form fields. Assert that a run starts only when every id and window the text names equals the form,
   and that the router never raises. It would have caught I1 and I2.
4. Before T13's pool lands, set `lock_timeout` on the API's units (M4); afterwards, keep it per unit.
5. Parked for T13: the global queue bound and `lose_after_commit` are already owned. Add M3 to T21's
   `decide_once` item so both `Conflict` mappings are fixed together.

### Declined to judge

- A key reused on a different route template executes twice (probe: 201 then 200). BS:244 puts the route in the
  scope, and ruling 2 follows it. Spec-mandated, not silent.
- The idempotency record table has no RLS, so `api` can read every tenant's records. SA:523 and AM-20.2 fix this,
  and every lookup filters by tenant and subject.
- The replayed 202 says `QUEUED` after the run moved on. Ruling 4 and BS:299 ("the same logical result") choose
  this, `status_url` gives the current state, and R016's live line proves it is intentional.
- The global queued-work bound (BS:550 "100 total") is not enforced. It is a declared debt line owned by T13 and
  erratum 39.
- The per-tenant quota is read without a lock, so separate API processes could overshoot it. Only one API process
  and one connection exist today (the session lock serialises it exactly); this belongs to T13's pool.
- Any requester may post into another requester's conversation in the same tenant. This is pre-existing (Plan D),
  the spec scopes conversations to the tenant, and T12 did not change it.
- An unpurged expired record makes the unit do the work and roll it back before answering "not reusable yet". It
  is correct, rare and already ledgered (T14/T28).
- `create_app` sets `faults` on the store object. It is ledgered (T13), and test-profile only.
- The test-profile fault route needs no role, only identity and CSRF. It does not exist outside `PROFILE=test`
  (R098), and ruling 24 and erratum 35 cover it.
- `ask` without an asset or window clarifies instead of answering. Ruling 10 and erratum 38 make a read-only run
  need both, because `create_run` requires them.
- A 409 `IDEMPOTENCY_CONFLICT` "not reusable yet" is marked non-retryable although the condition clears within a
  sweeper tick. The message tells the client to use a new key, which is the correct client action.
- Free-form `text` is stored verbatim in `messages`. Rendering it safely is the UI's job (T26); nothing in T12
  echoes it into a template.
- Long lines in `README.md` and `SESSION_STATE.md` predate the branch (paragraph-per-line convention); the
  branch's new runbook line at `walking-skeleton.md:21` edits an existing long line.
- The 805/104 and 888/21 gate counts were not re-run here. The brief forbids the live suite; `tests/plan_g` was run
  (124 passed).

### Assessment

Ready to merge? **With fixes.** The idempotency, transaction, grant and error-surface design is sound and the
records are accurate. Fix I1, where user text can crash the router into a 503, and I2, where a multi-asset text
with a stale form starts a run, together with M2's runbook sentence. No re-plan is needed.

---

## Controller rulings

FINAL whole-branch review (opus): 0 Critical / 2 Important / 6 Minor; "Ready to merge: with fixes".
Rulings for the ONE fix wave:
- I1 (huge window number → OverflowError in said() → 503): accepted. No float anywhere in the parser or the
  renderer; a window whose integer part exceeds 12 digits is read as "too large" and answers clarify with
  cause interval_out_of_range and a template that does not echo the number ("The window in the text is too
  large to be a number of hours; give between 1 and 168 hours."); said() formats Fractions by integer
  arithmetic with at most two decimals; tests for the 400-digit input (pure + HTTP → 200 clarify, no 503, no
  ERROR log). Amends execution ruling (c). — why: a requester must never turn text into a 503 — cost if wrong:
  an unrecorded 503 and an ERROR line per such message.
- I2 (form asset among several in the text starts a run): accepted; amends ruling 12(a): fields set + text names
  two or more ids → clarify(asset_ambiguous) even when one of them is the form's; fields set + text names
  exactly one id equal to the form's → agree; text names exactly one id different → asset_conflict. Mirrors the
  window rule and BS:297. — cost if wrong: one more clarification for chatty text.
- M2 runbook sentence (a recorded 409/404 replays for the window; a retry of a refused request needs a new key
  when the cause has changed): accepted. M3 (`Conflict` code mapped explicitly: SLOT_OCCUPIED only when the
  function says so; other codes → VERSION_CONFLICT): accepted. M4 (`SET LOCAL lock_timeout = '2s'` before the
  reply unit's FOR UPDATE; 55P03 is already retryable 503): accepted. M6 (skip the quota count for status and
  clarify verdicts): accepted. M5 is closed by I1. M1 (lower-case/accented/full-width asset spellings and
  "previous"/"two days" unread): ledgered as debt → T21, not fixed (the AssetId grammar is upper-case ASCII by
  contract).
Fix wave: one dispatch (opus), then one scoped re-review (sonnet), then the record commit.
Final fix wave (opus): b4fb01f — I1 (no float; >12-digit windows ask without echo; said() integer arithmetic),
I2 (two text ids ask even with a form asset), M3 (explicit Conflict mapping), M4 (SET LOCAL lock_timeout 2s
before the FOR UPDATE, TODO(T13)), M6 (quota count only for run verdicts), M2 (runbook + api README sentence);
plan rulings 12 and 21 amended. tests/plan_g 135 passed; check.py 816/104 GREEN; live admission 6 passed
(evidence unchanged but for timestamps, restored). Concerns for the record commit: SESSION_STATE ruling (c)
text; the plan's historical round-2 note now describes a superseded rule (left as a record).
Re-review package review-91ed4a4..b4fb01f.diff; re-reviewer sonnet dispatched.

---

## Fix wave

## Plan G final fix wave: report

Branch `plan-g`, base 91ed4a4, one commit: **b4fb01f** `fix(admission): no float in the window parser, two text ids
ask, bounded reply lock (Plan G final review)`. 9 files, +238/-50. No attribution trailers.

### I1: huge window number, OverflowError, 503

- `core/src/ops_core/routing.py`:
  - :124 `WINDOW_DIGITS_MAX = 12`; :126 `TOO_LARGE_QUESTION` (the ruling's text, echoes nothing); :128
    `SAID_MAX_SECONDS = 10**12 * 3600`.
  - :153 `_digits()` reads a digit string in 1,000-digit slices. Python's 4,300-digit `int()` parse limit
    otherwise raises on a long decimal part. `Fraction(Decimal(...))` hits the same limit (measured).
  - :164 `_window()` strips commas, splits on ".", strips leading zeros. An integer part over 12 digits gives
    `None` ("too large"); otherwise an exact `Fraction`.
  - `text_windows()` returns `tuple[Fraction | None, ...]`.
  - :250 `resolve()`: any `None` window gives `interval_out_of_range` with `TOO_LARGE_QUESTION`, with or without a
    form window. The asset rules still run first.
  - :189 `said()` uses no float. At or past the cap it says "more than 1,000,000,000,000 hours". Otherwise it uses
    whole hours, then whole minutes, then seconds, rounding to two decimals half up by integer division.
  - No `float` remains in the module.
- Tests:
  - `tests/plan_g/test_routing_admission.py`: 4 new table rows from :274: the 400-digit text with and without a
    form, 13 digits with a form, and 13 digits with commas.
  - :349 `test_a_huge_window_is_said_briefly_and_never_raises` covers three huge Fractions, each giving the short
    bound string.
  - :357 `test_a_too_large_window_asks_without_echoing_the_number` checks the exact question with and without a
    form. It also checks that a 9,000-digit decimal part is read, not raised on: it conflicts and is said as
    "1.33 seconds".
  - `said(Fraction(1, 200)) == "0.01 seconds"` was added (half up).
  - `tests/plan_g/test_api_admission.py:378` `test_a_window_too_large_to_read_is_a_clarification_not_a_503`
    expects 200 `clarification_needed`, cause `interval_out_of_range`, no "1000" in the body, no run, and no ERROR
    record in caplog.
- Red before the fix (routing.py stashed): the HTTP test failed with `assert (503 == 200)`, plus
  `ERROR ops_api:limits.py:192 ... failed: OverflowError`. It is green after the fix.
- M5 is closed by the same change: a 12-digit window renders as at most a 12-digit hour count, and anything larger
  as the bound.

### I2: form asset among several ids in the text

- `routing.py:238`: `len(ids) > 1` gives `asset_ambiguous` before the form check. :244: with a form asset, exactly
  one id that differs gives `asset_conflict` (the template now takes `{given}`, a single id); one equal id agrees.
- The comment above the rule cites the window rule and BS:297.
- Tests:
  - `test_routing_admission.py`: the row "Compare B22 with A17, last 24 hours." with form A17/24 changed from
    `investigate` to `asset_ambiguous`.
  - New rows: the review's "B22 is failing, A17 is fine; last 24 hours" with form A17/24 gives `asset_ambiguous`
    (:110), and "Investigate A17, last 24 hours." with form A17/24 gives `investigate`.
  - The `asset_conflict` question sample is now single-id ("...but the text names B22; ...").
  - `test_api_admission.py:391` `test_a_form_asset_among_several_in_the_text_is_a_clarification` expects 200
    `asset_ambiguous` and no run.
- Red before the fix: `assert (202 == 200)`.
- Plan ruling 12 amended in
  `docs/superpowers/plans/2026-10-10-first-slice-g-admission-idempotency.md:301-303` (the I1 sentence on the window
  number) and :315-318 (the I2 asset rule).
- Execution ruling (c) lives in `SESSION_STATE.md:273`, not in the plan. It was not edited here; that is left for the
  controller's record commit.

### M3: create_run Conflict mapping

- `api/src/ops_api/store.py:539`: `SLOT_OCCUPIED` only when `exc.code == ErrorCode.SLOT_OCCUPIED.value`. Any other
  code gives a recorded 409 `VERSION_CONFLICT`, "the run could not be started in the current state" (:547).
- `tests/plan_g/fakes.py`: `FakeStore.start_refusal` scripts a code.
- Test: `tests/plan_g/test_store_units.py:155` `test_another_create_run_refusal_is_recorded_under_its_own_code`
  (code `SUPERSEDED_RUN_MOVED` gives 409 `VERSION_CONFLICT` with that message, no message or run, one record). It was
  red before the fix.

### M4: lock_timeout before the reply unit's FOR UPDATE

- `store.py:923`: `SET LOCAL lock_timeout = '2s'`, a literal because SET takes no bind parameter. The comment states
  why: a worker holding the row must not stall the single connection, and 55P03 (`LockNotAvailable`, an
  `OperationalError`, checked) becomes the retryable 503. It has `TODO(T13)` for the pool.
- Test: `RecordingConn` answers `SET ...` without consuming the script. The new `assert_locked_first`
  (`test_store_units.py:274`) asserts `statements[0]` is the SET LOCAL and `statements[1]` is the `FOR UPDATE` on
  `app.runs`. It is used on both refusal paths, the accepted path and the wrong-question test (statement counts
  shifted by one).
- Red before the fix.
- Live: `tests/e2e/test_admission_live.py` drives the clarification_reply route to 202 on the real database:
  6 passed.

### M6: quota count only for a run verdict

- `store.py:423`: `queued_count()` is read after the router, only on the investigate/readonly_answer path. The
  docstring and comment are updated.
- Plan ruling 21's order is amended (`plan:416-418`: active-run read, router, then the quota count for a run
  verdict only). This was needed because the old text named the count before the active-run read.
- `fakes.py`: `FakeStore.counts`.
- Test: `test_store_units.py:97` in `test_the_quota_refuses_only_what_would_start_a_run_and_records_nothing`: a
  status answer and a clarification leave `fake.counts` unchanged. It was red before the fix.

### M2: runbook sentence

- `docs/runbooks/dev-topology.md:100-102`: "A recorded refusal (409, 404 or 422) replays for that whole window too,
  so a retry after fixing its cause needs a new key; the same key is for retrying the same request after a lost
  response."
- The same idea is in one sentence at `api/README.md:24-25`, as the review's recommendation 2 asked.

### Gates

- `uv run python -m pytest tests/plan_g -q`: `135 passed in 1.94s` (was 124).
- `uv run ruff format --check core/src api/src tests/plan_g`: `33 files already formatted`.
- `uv run ruff check core/src api/src tests/plan_g`: `All checks passed!`
- `uv run mypy core/src api/src --strict`: `Success: no issues found in 23 source files`
- 120-character check (characters, UTF-8) on every line the commit adds: none over. Pre-existing long lines in
  `dev-topology.md` (3, 7, 8, ...) are untouched. All touched files are UTF-8 without BOM, LF.
- `PYTHONUTF8=1 uv run python scripts/check.py` on b4fb01f: `816 passed, 104 skipped in 42.08s` / `CHECK: GREEN`
  (805 + 11 new tests).
- `uv run python scripts/skeleton.py status`: all six down. `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest
  tests/e2e/test_admission_live.py -q`: `6 passed in 6.57s`.
- `reports/admission/t12-admission.txt` changed only in the header timestamp and the R018 sub-second clock offset,
  so it was not committed and was restored. `reports/bootstrap`, `reports/skeleton` and `reports/auth` were restored
  with `git checkout --`. The tree is clean.

### Concerns

- Execution ruling (c)'s text in `SESSION_STATE.md:273` still says "any number of ASCII digits". The I1 amendment
  belongs in the controller's record commit, along with the I2 amendment of ruling 12(a) and the M6 amendment of
  ruling 21.
- The plan's "Round 2 open points" note (`plan:~8302`, "`asset_ambiguous` applies only without a form asset") is a
  historical review record and was left as written. It now describes the superseded rule.
- `said()` caps at 10^12 hours. A 12-digit window in years (about 8.8e15 hours) is said as "more than
  1,000,000,000,000 hours" rather than its exact count: by design (no echo of huge numbers), and noted here.
- For the M3 message on a non-slot `Conflict`, the controller's ruling (`VERSION_CONFLICT`) was followed rather than
  the review's suggested `Internal`.

---

## Scoped re-review

## Scoped re-review of the final fix wave (b4fb01f), sonnet

Verdict: ACCEPT. Every finding addressed; `tests/plan_g` 135 passed; no new breakage; no attribution trailers.

- I1 ADDRESSED: no float in code (`grep float` hits only the `said()` docstring); `_window` returns None past
  `WINDOW_DIGITS_MAX = 12` integer digits and `resolve` answers `interval_out_of_range` with the constant
  `TOO_LARGE_QUESTION` (no number echoed); `_digits` reads long decimal parts in 1000-digit slices (a 9000-digit
  decimal passes); `said()` is integer arithmetic with a "more than 1,000,000,000,000 hours" cap. Probes: the
  400-digit input with and without a form → clarify (longest digit run in the question: 3); 12 digits → out of
  range with the number; 13 digits → the too-large template; `said(1/3 s)` "0.33 seconds", `said(5400 s)`
  "90 minutes". Tests pure and over HTTP (200, no run, no ERROR record).
- I2 ADDRESSED: two or more ids in the text ask `asset_ambiguous` first; one equal to the form agrees; one
  different is `asset_conflict`. "B22 is failing, A17 is fine; last 24 hours" with form A17/24 → ambiguous
  (question lists "B22, A17"); tested pure and over HTTP; ruling 12 amended in the plan.
- M3 ADDRESSED: only `SLOT_OCCUPIED` maps to the busy-slot 409; other `create_run` refusal codes → 409
  `VERSION_CONFLICT` "the run could not be started in the current state"; test through `FakeUnit.start_refusal`.
- M4 ADDRESSED: `SET LOCAL lock_timeout = '2s'` (constant literal) immediately before the `FOR UPDATE`;
  `assert_locked_first` pins SET at index 0 and the lock at index 1 in all three reply tests; `TODO(T13)`.
- M6 ADDRESSED: `queued_count()` only on the run-verdict path; the quota test asserts no count for a status
  message or a clarification.
- M2 ADDRESSED: `docs/runbooks/dev-topology.md` and `api/README.md` say a recorded refusal replays for the
  window and a retry after fixing the cause needs a new key.

Out of scope: `tests/plan_g/test_idempotency.py:43` flagged by a byte count (it is 120 characters); the word
"float" in a docstring.

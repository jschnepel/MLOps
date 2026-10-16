# Plan I final review record — T14 gap-free event journal, wake-ups and outbox

Branch `plan-i`, executed range 4aa5f92..9ce23a0 (six tasks, the sixth the close-out; each with one task review, all
clean, no fix rounds). The whole-branch review below ran on the most capable model after the close-out; the controller
ruled on every finding; one fix wave (e485c56, 2c759ed) applied the accepted ones; one scoped re-review verified them.
The plan's own review is `docs/reviews/plan-review-i-2026-10-15.md`; the task-scoped reviews are summarised in
`docs/PROJECT_HISTORY.md` section 26.

---

## Whole-branch review

# Plan I (T14) — final whole-branch review

Range `4aa5f92..9ce23a0` (13 commits, branch `plan-i`, no attribution trailers, clean tree). Reviewer: opus.
Read-only: no live test, no database, no checkout mutation; no focused pytest was needed (every doubt was settled by
reading the code, the migrations it depends on and the live tests).

Passes:
1. Code: `migrations/app/versions/0008_journal_outbox.py` (and the 0003/0005/0007 bodies it relies on),
   `sweeper/src/ops_sweeper/{outbox,wakeups,tenants,main,leases}.py`, `core/src/ops_core/{locking,persistence,
   privileges,outcomes,settings,testing/faults}.py`, `worker/src/ops_worker/handlers.py` (execute path, for the
   re-arm's authority question).
2. Concurrency and authority: every unit in `OBSERVED_UNITS` against `LOCK_ORDER`, the new SQL statement by statement,
   the grant matrix, RLS and the restrictive policy, `append_event`'s reserved-type rule, `grant_execution`'s
   transition. A mechanical diff of 0003's and 0008's `_append_event` bodies: the only differences are the two new
   payload checks before the lock and the intent INSERT after the event; the lock, counter and insert are 0003's
   byte for byte.
3. Tests and evidence: `tests/e2e/test_event_journal_live.py`, `test_wakeups_live.py`, the outbox and 0008 live test
   outlines, `tests/plan_i/*` outlines, the edited Plan H tests, `reports/events`, `reports/outbox`.
4. Close-out documents: SESSION_STATE, STATUS, `handoff/{tasks.json,acceptance-matrix.json,BUILD_BACKLOG.md}`,
   README, the runbook, ARCHITECTURE §6, PROJECT_HISTORY §26, the sweeper and worker READMEs; then the ledger triage.

## Strengths

- **The gap-free mechanism is untouched and the proof bites.** 0008's `_append_event` keeps 0003's `runs FOR UPDATE`,
  `next_event_seq + 1` and insert verbatim (checked by diffing the two bodies); the payload checks sit before the
  lock and the intent INSERT after the event, so lock order is `runs → events → outbox` as published. The stepped
  tests read every pid before any unit opens, prove the wait with `pg_blocking_pids`, observe through the real events
  route, and a removed `FOR UPDATE` makes them fail (Task 3's mutation).
- **Authority is tighter than the printed spec, deliberately.** No runtime role can INSERT into the outbox (api/worker
  cells withheld, erratum 60; a live test shows the refusal); `app_definer` holds INSERT only and the target-less
  `ON CONFLICT` was proved under that grant (the Task 4 ruling). The sweeper's new DELETE on `jobs` is held by a
  RESTRICTIVE policy to `run_id IS NULL AND done_at IS NOT NULL`; the sweeper has no UPDATE on `run_id`, so it cannot
  turn a run job into a deletable one. `notification.failed` is not a notify type (no loop). `run.*`/`action.*` stay
  reserved in `append_event`, so no runtime caller can forge an intent-bearing event.
- **The re-arm cannot re-execute a granted action.** `grant_execution` moves APPROVED → EXECUTING in the grant's own
  transaction (0005:149), and a replayed grant returns the existing action id; the sweep only looks at QUEUED and
  APPROVED, so a run that was ever granted is out of its reach. The re-arm repeats every scan condition on the row it
  updates, with the clock read there.
- **Delivery is honest about at-least-once.** Results name their attempt and never overwrite a dead letter; the sink
  boundary is the one documented broad catch and records a crash as that row's failed attempt; delivery never touches
  the run; the sink is a log line with a 12-hex recipient hash and no payload.
- **Deadlock freedom holds across the tree.** Sweeper outbox units lock `outbox` only; the announcement takes
  `advisory:notification → runs → events` and nothing that holds `runs` ever waits for class-2 advisory locks; the only
  outbox wait under `runs` is a replayed intent INSERT meeting a sweeper's row lock (unique-check wait), and the
  sweeper's outbox units never wait on anything run-side. Pull-forward and the claim pick with SKIP LOCKED; re-arm
  and purge take only `jobs` rows nobody else locks (done rows, maintenance rows). The R089 stress run recorded zero
  40P01/55P03 across 9 188 transactions of four roles.
- **Process discipline.** Debt list before code, every deviation recorded as a ruling with reason and cost, gate
  counts measured, red steps reproduced, no trailers.

## Issues

### Critical

None.

### Important

**I1. The restart pointers in SESSION_STATE are stale and point the next session at work already done.**
`SESSION_STATE.md:782` ("Exact next step") ends "... and write Plan I (the next earliest dependency-satisfied task
...: T14 or T15)"; `SESSION_STATE.md:5-6` ("Next task") says "`4aa5f92..b56b5a4` ... the close-out commit follows",
and the same `..b56b5a4` range appears in the "Plan I executed" block, STATUS's Plan I update, the T14 review note in
`handoff/tasks.json` and `handoff/BUILD_BACKLOG.md`. CLAUDE.md tells every session to "continue from
SESSION_STATE.md", so the entry point currently instructs the next agent to write a plan for a task marked DONE.
Fix (docs only, no gate impact beyond `verify_handoff`): replace the last sentence of "Exact next step" with the
owner inputs plus "then write Plan J for T15 (the earliest dependency-satisfied task after T14)"; drop "the close-out
commit follows" and give the range as `4aa5f92..<head after the final-review fixes>` (or say "plus the close-out
`9ce23a0`") consistently in the five places. Ledger: FINAL-FIX (Task 6 minor 1).

### Minor

**M1. `wakeups.LOST` hard-codes the state → job-type CASE** (`sweeper/src/ops_sweeper/wakeups.py:56`) while `STATES`
and `PAIRS` derive from `WAKEUPS`. A pair added to `WAKEUPS` alone (T20's AWAITING_INPUT/resume_input, T22's) makes
the CASE yield NULL, the lateral returns no row, the inner join drops the run: the new wake-up is silently never
swept, and R105's leftover check (which reuses `LOST`) is blind to it too. `test_the_sweep_looks_only_where_a_handler
_exists` pins only the tuple. Fix: `CASE r.state {" ".join(f"WHEN '{s}' THEN '{t}'" for s, t in WAKEUPS)} END`, and
add the generated CASE to the scan test's conditions. The SQL text is equivalent today, so no live behaviour changes.
**Fix before merge** (ledger FINAL-REVIEW ATTENTION; one line plus one assertion).

**M2. PROJECT_HISTORY §26 "Execution" overclaims** (`docs/PROJECT_HISTORY.md:420`, the "Six tasks, each reviewed once and
clean ..., and the live half passed on its first run in every task" sentence). Task 1 and Task 6 had no live half
(Task 1 ran only the baseline), and the sentence was written before Task 6's review and this final review. Fix:
"Tasks 2-5 each passed their live half on the first run; every task review was clean (Minor findings only) with no
fix round", and append this final review's round (findings and fixes) per `docs/CODE_COMMENTS.md`'s history standard.
**Fix before merge.**

**M3. SESSION_STATE's gate line cites stale plan tails.** "Plan I executed" says "1031 passed / 154 skipped; ...
1164 passed / 21 skipped (the plan's tails are 1030/154 and 1163/21)". The plan's own task overview and final Counts
say 1031/154 and 1164/21 (`plan:345`, `plan:6099-6100`); 1030/1163 are round-1 figures left in the plan's Task 6
template (`plan:5418`, `plan:5907`). As written it reads as an unexplained +1. Fix: drop the parenthetical, or say
"equal to the plan's Task 5 counts". **Fix before merge** (same docs commit as I1).

**M4. The runbook's remedy for a wake-up past its cap is not actionable today** (`docs/runbooks/events-and-outbox.md:
104-108`). "Fix the cause; the next decision or revision makes a new wake-up": an APPROVED run cannot receive a new
decision, `create_revision` does not exist until T21, and neither applies to a QUEUED run. An operator who fixed the
cause (reactivated a membership) has no documented way to wake the run. Fix: add the superuser statement that resets
the job (`UPDATE app.jobs SET attempts = 0 WHERE id = '<job>'`, after which the sweep re-arms it on the next tick) or
say plainly that the run stays until T21/T22 provide a path. Also line 54: the resume job is committed with the
clarification *reply*, not "with the clarification". **Fix before merge** (docs).

**M5. Delivery order inside a batch is random.** `outbox.CLAIM` picks rows `ORDER BY created_at, outbox_id` but returns
them `ORDER BY c.outbox_id` (random UUIDs), and `deliver` hands them to the sink in that order
(`sweeper/src/ops_sweeper/outbox.py:67`). Harmless with one intent per run and type today; once T22 emits
`run.escalated` beside `action.conflict` for the same run, a requester could get them out of order. Fix: return
`created_at` from the CTE and order the outer SELECT by it. Stay deferred → T22 (no visible effect today).

**M6. `EXHAUSTED` is a plain multi-row UPDATE, not SKIP LOCKED** (`outbox.py:55-58`). Two sweeper instances running it
at once over overlapping row sets can, in principle, take row locks in different orders and meet a 40P01 (PostgreSQL
resolves it; the tick logs and retries). The table-level lock order cannot express intra-table order. Fix:
`UPDATE ... WHERE outbox_id IN (SELECT ... FOR UPDATE SKIP LOCKED)` puts it outside the order like the claim. Stay
deferred (one sweeper instance in v1; self-healing).

**M7. `notification.*` is not a reserved type in `append_event`** (0003:369-372). An `api` or `worker` caller can append
`notification.failed` with an arbitrary `outbox_id`, `code` and `message`. Suppressing a real announcement would need
an outbox id, which neither role can read, so the practical effect is a misleading requester-visible event of the kind
`tool.*` already allows. The sweeper README now says this is the sweeper's one event; the database does not enforce
it. Fix (a later revision): reserve `notification.%` for `session_user = 'sweeper'` in `append_event`. Stay deferred →
T26/T45 (record as a debt line; not a v1 boundary breach).

**M8. No live test runs the real tick's T14 steps.** Live tests call `wakeups.sweep` and `outbox.deliver` with
`tenants=[...]`; `main.sweep_wakeups`/`main.deliver_outbox` (tenants via `persistence.tenants`, the audit rows) run
only inside R105's skeleton sweeper, whose failures would be logged as "sweeper tick failed" and never fail the test.
The grants and the pieces are each proven, so the risk is narrow. Fix: R105 asserts its run's `action.confirmed`
intent was delivered, or that `sweep_wakeups`/`deliver_outbox` rows exist for the test's minutes. Stay deferred
(ledger Task 4 minor), but it is the cheapest end-to-end guard for T15's start.

**M9. The re-arm turns a final grant refusal into bounded re-dispatch, against AM-10's APPROVED → BLOCKED_REVIEW.**
`states.py:180` (AM-10) says a refused grant blocks the run for review; the code leaves it APPROVED (T21 debt), and
the APPROVED/execute re-arm now re-dispatches it up to `OPS_WAKEUP_MAX_ATTEMPTS` (about ten minutes at the
defaults). Each dispatch passes the full gate again (approval, active and freshly synced memberships, no
cancellation), so nothing executes under authority that is invalid at that moment, and the stale-sync refusal already
re-queues indefinitely; but a run AM-10 would hold for review can now execute when, say, a deactivated reviewer is
reactivated within the window, and `grant_execution` checks no proposal expiry before T21. This is ruled (round 1 I3,
erratum 63, debt → T21) and disclosed. No code change asked; the owner should decide erratum 63 knowing this. The
conservative alternative is to drop `("APPROVED", "execute")` from `WAKEUPS` until T21 lands BLOCKED_REVIEW (an
execute wake-up cannot otherwise be lost: the decision commits its job, and progress past APPROVED happens inside
mcp-write before the worker consumes the job).

**M10. Small text slips.** `0008_journal_outbox.py:257` names `privileges.SWEEPER_PURGE_QUAL` (the constant is
`SWEEPER_PURGE`); ARCHITECTURE §6's claim paragraph has a stray line break ("...; and" / "a wake-up ..."); the
runbook's "A database error during delivery logs `sweeper tick failed`" is true for non-operational errors only (a
transient `OperationalError` logs "transient database error; the loop continues"). **Fix before merge** (fold into the
docs commit; 0008 is not applied to any persistent database yet, and a comment edit changes no body).

## Deferred-minor triage

| Ledger line | Triage | Reason |
|---|---|---|
| T1: RED 2 failure message not captured; locking test written after code | stay deferred | process record only; the tests exist and pass |
| T1: unknown-key refusal precedes the model_summary branch (generic message) | stay deferred | verdicts unchanged; message never repeats a key, as required |
| T2: 0008:257 names `SWEEPER_PURGE_QUAL` | fix-before-merge | trivial comment fix (M10); 0008 not yet applied to dev |
| T2: dedup test replays via superuser; check Task 4 exercises the definer path | stay deferred (resolved) | Task 4's R024 re-append runs as `app_definer` and the mutation proves it bites |
| T2: catalog walker follows only `app.x(` calls | stay deferred | complete for today's bodies; harden when a definer calls dynamically |
| Ruling (T3): gathers with `return_exceptions`, readers released, `stepped` settles B | accept | test-only; enforces the plan's own "never cancel a DB unit" rule |
| T3: rollback test settles B only when not done | stay deferred | failure path only; a done B already surfaced its result |
| T3: `stepped` waits 5 s when B fails early | stay deferred | failure path latency only |
| T3: evidence lines appended before the purge `finally` | stay deferred | the module writes evidence only when every line is present |
| Ruling (T4): R024 re-append as `app_definer` | accept | the only way to exercise the target-less conflict under the real grant |
| T4: dead letters re-scanned every tick, no index, delivered rows never purged (FINAL-REVIEW ATTENTION) | stay deferred → T32 | per tick one seq scan of `outbox` per tenant; negligible at v1 scale (local, few tenants). Recommend T32 adds a partial index on `(tenant_id) WHERE result = 'dead_letter'` or an `announced` marker, and an outbox DELETE grant (events cannot be purged while outbox rows reference them) |
| T4: sink boundary logs exc + traceback unredacted | stay deferred → T39 | `LogSink` puts nothing sensitive in an exception; a real sink must |
| T4: tick summary counts `recorded=False` results | stay deferred | log line only; the rows are right |
| T4: no live test through `persistence.tenants` | stay deferred | grant verified (`privileges.py:72`); see M8 for the cheap guard |
| T4: plan/brief text says the R024 re-append is superuser | stay deferred | the ruling is recorded in SESSION_STATE; plan text stays as written by design |
| Ruling (T5): a DB error in the sweep skips that tick's delivery | accept | no persistent error source in the sweep or purge was found (no FK references maintenance rows; scans are plain); a transient one costs one tick |
| T5: LOST's CASE hard-coded (FINAL-REVIEW ATTENTION) | fix-before-merge | M1: silent-skip trap for T20/T22, one-line fix, no live change |
| T5: `pull_forward` bound cannot tell deferral from a short deliberate delay | stay deferred | only makes a retry earlier, never later |
| T5: R105 leftover check fails on a capped leftover, misses runs with an open job | stay deferred | errs loud, never silent |
| T5: newest-job tie-break differs between scan and re-arm | stay deferred | equal `done_at` on two jobs of one run and type does not occur today; the re-arm then refuses, safe side |
| T6: SESSION_STATE "Exact next step" stale (FINAL-FIX) | fix-before-merge | I1 |
| T6: PROJECT_HISTORY §26 premature/overbroad; five vs six tasks (FINAL-FIX) | fix-before-merge | M2; align "the debt list and the five tasks" (Task 1 includes the debt list) with "six tasks, the sixth the close-out" |
| T6: R089 IMPLEMENTED_LOCALLY_VERIFIED while expected evidence names SSE replay | stay deferred | the matrix has no partial status; the note discloses T27, and T27 owns R053 ("reconnect replays without gaps") |
| T6: evidence timestamps UTC (10-16) vs docs local (10-15) | stay deferred | every earlier report uses UTC; consistent |
| T6: ARCHITECTURE §6 stray line break | fix-before-merge | trivial, same docs commit (M10) |

## Declined to judge

- Notifying a requester whose membership is now inactive (the intent addresses `runs.requester` unconditionally): the
  spec says "the requester" and is silent on membership at delivery time; recipient mapping is T39's.
- One intent per run and type (a second `action.failed` for the same run is not notified): ruled (13, erratum 66).
- `deliver_outbox`'s audit row written before its work and `sweep_wakeups`' after: ruling 19 chose it.
- Per-tick cost of iterating every tenant three or four times (claim, announce, sweep): spec prescribes tenant
  iteration (SA:520); scale is out of v1 scope.
- The capped wake-up warning repeating every tick forever: ruled (8) with metrics owned by T28.
- Two notifications for one escalation once T22 emits `run.escalated` beside `action.conflict`: a T22 design question.
- Unbounded MEMBERSHIP_STALE re-queue in the execute handler: pre-existing, TODO(T22), not changed here.
- Shutdown cancelling the sweeper loop mid-unit on KeyboardInterrupt: pre-existing, T30's draining.
- Proposal expiry not checked by `grant_execution`: T21's, independent of this plan (it only matters to M9).
- The plan's own internal count inconsistency (Task 6 template 1030/1163 vs overview 1031/1164): plan text is frozen
  by design; only its echo in SESSION_STATE is flagged (M3).

## Recommendations

1. One docs commit: I1, M2 (with this review's round appended to PROJECT_HISTORY), M3, M4, M10's text slips; one code
   commit: M1 (plus its assertion) and the 0008 comment. Then rerun the dev gate and `verify_handoff`; the live gate is
   not needed for these (no SQL body, grant or behaviour changes), though a run of `tests/e2e/test_wakeups_live.py`
   and R105 would confirm M1's generated SQL if a live window is available.
2. Put M5, M6, M7 and M8 on the Plan I debt list with their owners (T22, T30/T39, T26/T45, T15's first plan), so
   they survive this review.
3. When the owner decides erratum 63, put M9's trade-off in front of them explicitly.
4. T32's plan must give some role DELETE on `app.outbox` (and order it before events) before any event retention can
   run; record that next to the existing retention debt line.

## Assessment

**Ready to merge?** With fixes.

**Reasoning:** The code meets T14's definition of done with no Critical or code-level Important finding: the journal
is provably gap-free and commit-ordered, intent is transactional, deduplicated and written only by the definer,
delivery is leased with its result recorded apart from the run, and no new transaction breaks the lock order or the
authority boundaries. The handoff's restart pointer (I1) is wrong and the cheap M1/M2/M3/M4/M10 fixes should land in
the same pass before the branch is offered for merge.


---

## Controller rulings on the findings

- Fixed in the one wave: I1 (the handoff pointed the next session at finished work; ranges excluded the close-out),
  M1 (`wakeups.LOST`'s CASE built from `WAKEUPS`, generated SQL unchanged, a test pins every pair), M2 (history
  wording and the final-review paragraph), M3 (stale plan tails), M4 (no operator remedy today for a run past its
  wake-up cap; T21), M10 (comment name, line break, transient-error wording).
- Recorded as debt with owners: M5 batch delivery order → T22; M6 the claim's dead-letter UPDATE without SKIP LOCKED
  (two sweepers) → T30; M7 `notification.*` not reserved in `append_event` → T26/T45; M8 no live test of the real
  tick's T14 steps → T30.
- M9 left to the owner through erratum 63: until T21 moves a refused grant to BLOCKED_REVIEW, the re-arm re-dispatches
  an APPROVED run up to the attempts cap; each dispatch re-runs the full grant check; a deactivated membership cannot
  be reactivated in v1; GRANT_DEFERRED retries depend on the re-arm; dropping the `("APPROVED", "execute")` pair until
  T21 is the conservative alternative.

---

## Fix wave report

# Plan I final-review fix wave

Commits: `e485c56` (code) and the docs commit above it (branch head). Range written in the records: `4aa5f92..e485c56`
plus "a docs commit after it records the wave".

- **M1** `sweeper/src/ops_sweeper/wakeups.py` (new `job_type_case`, used in `LOST`): the CASE is built from `WAKEUPS`;
  today's text unchanged (asserted). Test `tests/plan_i/test_wakeups.py::test_the_job_type_case_covers_every_wakeup_pair`
  (also shows an extra pair reaches the CASE).
- **M10** `migrations/app/versions/0008_journal_outbox.py` comment `SWEEPER_PURGE_QUAL` -> `SWEEPER_PURGE`; ARCHITECTURE
  section 6 line break joined; runbook "sweeper tick failed" now also names the transient-error log line.
- **I1** SESSION_STATE "Next task" and "Exact next step" name Plan J = T15 (computed from tasks.json: earliest
  PLANNED task with its dependencies DONE; T17 also unblocked; T03/T02/T44 are owner inputs). Range `4aa5f92..e485c56`
  in SESSION_STATE (two places), STATUS, tasks.json T14 note, BUILD_BACKLOG.
- **M2** PROJECT_HISTORY section 26: Execution corrected (Tasks 2-5 live halves passed first run; Tasks 1 and 6 none;
  six tasks, the sixth the close-out), final-review paragraph appended. "Six tasks" used everywhere.
- **M3** SESSION_STATE gate line: plan's final tails 1031/154 and 1164/21, equal to measured.
- **M4** runbook: capped wake-up has no operator remedy today (T21), observable via the log line; "with the reply".
- **Debt lines M5-M8** in SESSION_STATE (Plan I debt list and Open items); the LOST CASE open item marked done.
- **M9** erratum 63 extended with the trade-off and the conservative alternative; the owner decides.

## Gates
- Focused: `tests/plan_i/test_wakeups.py` 8 passed; ruff and mypy clean (a stale `.mypy_cache` gave false
  attr-defined errors until deleted; it is git-ignored).
- `PYTHONUTF8=1 uv run python scripts/check.py`: 1032 passed, 154 skipped, CHECK: GREEN (1031 + 1 new test).
- `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`: exit 0. tasks.json valid JSON.
- `PYTHONUTF8=1 uv run python scripts/check.py --profile test` (all skeleton processes down): 1165 passed, 21 skipped,
  CHECK: GREEN. `git checkout -- reports/` afterwards (11 reports rewritten by timestamps and stress counters only).


---

## Scoped re-review of the fix wave (9ce23a0..2c759ed)

Verdict: all findings addressed, no new Critical or Important breakage. The M1 CASE was rebuilt from today's
`WAKEUPS` and compared byte for byte with the old hand-written text (identical); `tests/plan_i/test_wakeups.py` ran
8 passed; T15 was confirmed as the earliest dependency-satisfied PLANNED task; `handoff/tasks.json` parses. Two
wording-level minors noted: an ordinal without an antecedent in the history's final-review paragraph, and a partly
tautological last loop in the new test (the exact-text and containment assertions carry the guard).

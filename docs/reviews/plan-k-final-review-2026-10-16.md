# Plan K final review record — T47 authenticated mcp-write and the recovery tools

Branch `plan-k`, executed range dd9f7b1..6ec740f (six tasks, the sixth the close-out; each with one task review; Task 4
took one test-only fix round, 28d3f0b, and Task 6 one docs fix round, 4e84dfd/6ec740f). The whole-branch review below
ran on the most capable model after the close-out; the controller ruled on every finding; one fix wave (b2ba317,
97367e0, 5c96f0d) applied the accepted ones; one scoped re-review verified them, and the controller applied its one
optional rewording (ARCHITECTURE §8). The plan's own review is `docs/reviews/plan-review-k-2026-10-16.md`; the
task-scoped reviews are summarised in `docs/PROJECT_HISTORY.md` section 28.

Controller rulings on the whole-branch review: I1 fixed by admitting ABORT_REQUESTED for the execute job's
`create_incident` (its `aborting` branch answers UNKNOWN with no destination call; the worker's `mark_unknown` parks
the run in OUTCOME_UNKNOWN), which restores the pre-Plan K liveness without any new send path; M1 fixed; the deferred
minors T1-a, T1-b, T2-c, T2-e, T3-a, T3-b, T3-c, T4-a and T5-a taken into the fix wave; T1-c, T3-d, T4-b, T4-c and T5-b
left deferred as the review recommended. Gates after the fix wave (measured): dev 1161 passed / 182 skipped; live 1322
passed / 21 skipped; verify_handoff exit 0.

---

## Whole-branch review

## Plan K (T47) final whole-branch review

Range `dd9f7b1..6ec740f` on `plan-k` (10 commits: the debt list, Tasks 1-5 with Task 4's fix round, the Task 6
close-out and its fix round). I reviewed it against the plan
(`docs/superpowers/plans/2026-10-16-first-slice-k-mcp-write-recovery-tools.md`: Goal, Architecture, Global Constraints,
Review Focus 1-5, Rulings 1-27 and refinements (a)-(h), the debt list, errata 82-92), the plan review record
`docs/reviews/plan-review-k-2026-10-16.md`, SPEC_AMENDMENTS AM-13 (SA:220-299), AM-15 (SA:330-360) and AM-20.3
(SA:455-470) over BUILD_SPEC, `handoff/tasks.json` T47, and the SDD ledger.

Method:
- I read in full every production file the range touches: revision 0010, `persistence.py`, `jobs.py`,
  `privileges.py`, `settings.py`, mcp-write's `server.py`, `execution.py` and `destination.py`, mcp-read's
  `read_verifier`, and the worker's `token_source`.
- I read the code they depend on: 0004's `_latest_attempt`, `_grant_row` and `lookup_action`; 0005's
  `grant_execution`; 0007's `_resolve_handle`, `mark_sent`, `record_outcome` and `mark_unknown`; the worker's
  `handlers.execute` and `_mark_unknown`; `ops_worker.mcp.HttpMcpCaller`; incident-sim's abort, lookup and key routes;
  and `outcomes.outcome_from_destination` and `ActionOutcome`.
- I read the new and changed tests: all of `tests/plan_k/`, `test_migration_0010_live.py`,
  `test_mcp_write_t47_live.py` and `test_mcp_write_process_live.py`.
- I read the close-out records: SESSION_STATE's Plan K sections, STATUS, ARCHITECTURE §8, the runbook, the threat
  model, the matrix rows, the BUILD_BACKLOG/tasks.json notes, PROJECT_HISTORY §28, the READMEs and both evidence
  files.
- I recomputed the next task from `tasks.json`.
- I ran one non-database Python check: `allowed_tool(EXECUTE, EXECUTING, ABORT_REQUESTED, CREATE_INCIDENT)` raises
  `HandleRejected`.
- I did not run the gates and did not touch the database or the checkout. I read the 446 KB diff file in passes,
  production code first.

### Strengths

- **The no-unapproved-external-action boundary holds end to end.**
  - `POST /internal/incidents` is reached from exactly one place, `execution.create_incident` (`execution.py:138-148`).
    That is after `grant_execution` (which replays only the run's own grant, with `OTHER_PROPOSAL` otherwise) and
    after `mark_sent` committed in its own unit and answered `sent` or `already_sent`.
  - Every other `mark_sent` answer sends nothing: `resolved`, `abort_requested`, `not_redispatchable`, `cancelled`
    and `expired`, plus an unknown answer, which raises.
  - The abort POST is reached only from `_abort`, after `request_abort` committed `ABORT_REQUESTED` in its own unit.
  - The lookup is one GET.
  - incident-sim's abort route writes only a tombstone key. It validates the reason against `keys.ABORT_REASONS`.
  - The residual window between `mark_sent`'s commit and the POST is stated where a reader needs it: 0010's docstring,
    `execution.py`, the threat model, ARCHITECTURE §8 and the runbook.
- **`mark_sent` and `request_abort` serialise on the runs row, so their two answers cannot cross.**
  - Both take the lease share lock (through `_resolve_handle`), then `runs FOR UPDATE`. Both read the latest attempt
    state and the clock only after that lock.
  - So either SENT commits first and the abort's reason is `deadline`, or ABORT_REQUESTED commits first and
    `mark_sent` answers `abort_requested`.
  - An abort with reason `cancelled_before_send` or `expired` can therefore exist only for an attempt that was never
    sent. That is the premise of `destination.classify`'s `NEVER_SENT` rule, and it holds.
- **`record_outcome`'s narrowed guard is right and fails closed.** It accepts SUCCEEDED or CONFLICT only after SENT,
  or after ABORT_REQUESTED whose reason `IS NOT DISTINCT FROM 'deadline'`. An abort row with no reason is therefore
  refused, and an INTENT abort can never record a receipt. This is pinned live in
  `test_a_cancel_comes_first_and_a_sent_attempt_aborts_only_when_due`.
- **Revision 0010 is disciplined.**
  - The three derived bodies change only what `_derived` names: each replacement must match exactly once, and the
    unit test undoes the changes to recover the applied bodies byte for byte.
  - The two new bodies carry the full header: SECURITY DEFINER, `search_path`, the `app.tenant_id` attribute, the
    owner `app_definer`, and REVOKE then GRANT to `mcp_exec` alone.
  - `_dispatch_seconds` is an invoker helper granted to nobody.
  - The downgrade drops all six and re-runs 0004's and 0007's own bodies.
  - `test_the_round_trip_restores_0009` compares `prosrc`, the definition, ACL, owner and `proconfig` against a
    scratch database built straight to 0009. It then compares the whole `app` function snapshot after re-upgrading.
    This is as strong as a migration test gets.
- **Authority comes from the verified token, with no literal left.**
  - `token.client_id` is the `principal.azp` that `write_verifier` checked. It flows through `answer` → `work` → every
    wrapper → every definer.
  - No `'ops-worker'` remains in any current function body or service source (only `settings.workload_client_id`'s
    default).
  - `test_every_write_path_definer_compares_the_presented_azp` mints a handle for a renamed client. All five definers
    refuse it under the old name and accept it under the new one, which a stray literal would fail.
  - `mcp_exec`'s EXECUTE set is pinned exactly: in `privileges.py` by unit test, and live through `pg_proc` with
    every other function proven to exist, so the check is not vacuous.
- **The attempt-state allowlist is exhaustive, and refusals are uniform.**
  - Every job type × run state × attempt state × tool combination is tabled.
  - Every refusal is the same `HandleRejected("invocation handle rejected")`, logged without the handle.
  - The live R030/R131 tests assert that error envelopes carry no `action_id` and that refusals make no destination
    call.
- **The evidence matches the claims I checked.** For example:
  - the rate-limit test counts the destination's keys before the lookup and asserts exactly +1 (the tombstone) after
    the abort;
  - the re-send test counts calls (`["post_incident"]`) and incidents (1);
  - the deadline test reads the clock reset back.

### Issues

#### Critical

None.

#### Important

**I1. A re-queued execute job that meets `ABORT_REQUESTED` is refused and closed as final. The run is left
EXECUTING with no job.**
- Where:
  - `core/src/ops_core/jobs.py:116`: `(EXECUTE, CREATE_INCIDENT)` admits `{None, INTENT, SENT}` only.
  - `mcp-write/src/ops_mcp_write/execution.py:183-200`: `_abort` commits `ABORT_REQUESTED`, then POSTs the abort, then
    records the outcome, each in its own step.
  - `execution.py:209-211`: the comment says "An unmapped database failure (psycopg.Error) still escapes as a 500,
    and the worker's next call meets the same action id (nothing was recorded)". That is false for the abort path.
  - `worker/src/ops_worker/handlers.py:239-266`: `McpCallFailed` re-queues the execute job, and any other envelope
    (`INVALID_HANDLE` included) finishes it.
  - `execution.py:118-119`: the `aborting` branch, which answers UNKNOWN, is reachable through the tool only by a
    race.
- Failure scenario:
  1. An execute job calls `create_incident` on a granted run whose cancel landed after the grant (or whose grant is
     past 300 s).
  2. `mark_sent` answers `cancelled`, and `_abort` commits `ABORT_REQUESTED`.
  3. Then mcp-write fails before the outcome is recorded. Either the process dies, or `record_outcome` raises an
     unmapped `psycopg.Error` (a 55P03 lock timeout, a dropped connection), which becomes the SDK's tool error.
  4. The worker sees `McpCallFailed` and re-queues the execute job (Plan J behaviour, TODO T22).
  5. The re-queued job mints a fresh handle. `resolve_invocation` refuses it: ABORT_REQUESTED is not in the execute
     row (I confirmed this by calling `allowed_tool`).
  6. The worker receives `INVALID_HANDLE`. Its lease is live, so it returns True and the job is closed.
  7. The run stays EXECUTING with no open job and its conversation slot held. Nothing in the tree, or in T22's spec
     (recover jobs come from `mark_unknown`, the worker's own tool result and lease reclaim), creates a recover job
     for it. Only a future escalation-deadline sweep would find it, 30 minutes later, as ESCALATED.
- Why it matters:
  - Before this range, the same cancel answered UNKNOWN and the worker's `mark_unknown` parked the run in
    OUTCOME_UNKNOWN with a `recover` job. That is a state T22's handler is designed to pick up.
  - Plan K made the cancelled and expired path better in the normal case. But it opened a window where a crash or a
    transient database error strands the run.
  - The plan's debt list names only "a `create_incident` that meets an abort request in flight answers UNKNOWN".
  - This is a gap in the plan's ruling 4 table (erratum 84), not a deviation by the implementer.
- Fix (cheap; preferred):
  - Admit `ABORT_REQUESTED` for `(EXECUTE, CREATE_INCIDENT)` in `jobs.ATTEMPT_STATES`. `grant_execution`'s replay
    then returns the grant, and `next_step` answers `aborting`. That is UNKNOWN with no `mark_sent` and no destination
    call.
  - The worker's existing UNKNOWN branch then calls `mark_unknown` (EXECUTING → OUTCOME_UNKNOWN, recover job
    `<action>:timeout`). A recover job's `abort_incident` already admits ABORT_REQUESTED, and `request_abort` returns
    the first reason idempotently.
  - Update `test_the_attempt_rules_are_the_rulings` and the allowlist table test. Add a unit case: an execute
    `create_incident` at ABORT_REQUESTED makes no call and answers UNKNOWN.
  - Correct the comment at `execution.py:209-211`.
  - Amend erratum 84, the runbook's allowlist table, ARCHITECTURE §8's allowlist bullet and the R030 note if it
    lists the table.
- Minimum alternative: add a debt line and a T22 review note naming this state (EXECUTING, ABORT_REQUESTED, no job),
  and correct the comment.

#### Minor

**M1. Four sentences in the records say more than the code does.**
- `docs/threat-model.md:44` ("Receipt lookup used to probe or to act"): "the recovery tools … create no grant,
  attempt, job or key". `abort_incident` does create a key: the destination's permanent ABORTED tombstone, by design.
  The live test asserts exactly that +1. Fix: "the receipt lookup creates no grant, attempt, job or key; an abort
  adds only its state rows and the destination's tombstone".
- `docs/threat-model.md:42`: "Only `sent` or `already_sent` … lead to a POST; every other answer (… `cancelled`,
  `expired` …) sends nothing". `cancelled` and `expired` do lead to a POST: the abort. Fix: "lead to the incident
  POST; `cancelled` and `expired` lead to the abort POST instead; the others send nothing".
- `mcp-write/README.md:22`: "a cancelled or expired attempt is aborted instead and ends FAILED". For the re-send of a
  SENT attempt the abort can meet the existing receipt and end SUCCEEDED. The runbook says this correctly. Fix: "ends
  FAILED, or SUCCEEDED if a SENT attempt's receipt already stands".
- `docs/PROJECT_HISTORY.md:547`: "forwarded any answer of `request_abort` as the run's reason". It is the abort
  request's reason. The run's FAILED reason comes from the tombstone. Fix the noun.

### Checked and found sound

1. **Boundary** (focus 1):
   - No POST to `/internal/incidents` happens outside `create_incident`'s `sent`/`already_sent` branch.
   - An abort POST happens only after `request_abort` committed.
   - `get_incident_receipt` only GETs: it makes one `_ask` with `get_action`, and the live test asserts
     `calls.made == ["get_action", "get_action"]`.
   - An abort never creates an incident: incident-sim's `keys.abort` writes only a tombstone, and the live tests show
     0 incidents.
   - `_ask`'s broad `except` replaces the one moved from the POST, with the same reason.
2. **Authority** (focus 2):
   - A read handle, a lying server column, another run's handle and an expired, revoked or fenced handle are each
     refused, both in `_resolve_handle` and in Python.
   - Another proposal is refused, by `grant_execution`'s replay check and by `_granted` (before any call).
   - Another run's action id is refused by each definer's `g.run_id = v_handle.run_id` (OC002).
   - Another azp is refused by the verifier (401) and by every definer.
   - `mcp_exec` executes exactly the seven functions, pinned both ways.
3. **Revision 0010** (focus 3):
   - Lock order: lease share lock, then `runs FOR UPDATE`, then the `action_attempt_state` insert. This matches SA's
     row for `request_abort` ("as `record_outcome`").
   - The clock is read after the locks in both new bodies.
   - `mark_sent` checks the cancel before the deadline on both paths, and checks the job type only for a SENT
     re-send.
   - `request_abort`'s reason table matches ruling 3 and erratum 82. A repeat returns the first reason.
   - The downgrade is exact. The runbook's "never downgrade past 0010 while ABORT_REQUESTED rows exist" covers the
     one hazard.
   - The worker's other paths are unaffected or improved:
     - `mark_unknown` accepts an EXECUTING run with any attempt state.
     - The UNKNOWN answers that 0010 adds (`abort_requested`, `aborting`, an unanswered abort) all go to `mark_unknown`
       as before.
     - `NOT_REDISPATCHABLE` and `ABORT_NOT_DUE` can come only from recover jobs, which the worker does not run yet.
     - A cancelled or expired execute call now ends FAILED instead of OUTCOME_UNKNOWN.
4. **Idempotency** (focus 4):
   - A SENT re-send passes `mark_sent` and reuses the action id. It is proved live: one incident, one grant.
   - Concurrent recovery calls serialise on the runs row. The second `request_abort` returns the first reason. The
     second `record_outcome` returns the stored status, and `_record` reads it back when the status differs.
   - A lookup on RESOLVED returns `_stored` without a call.
   - No event is skipped: `request_abort` writes no event, and every event still goes through `_append_event` under
     the runs lock.
5. **Envelopes and secrets** (focus 5):
   - `HandleRejected` always carries the fixed message.
   - Refusals are plain `error` envelopes with `data: null`.
   - `abort_envelope` matches the regenerated schema for all four outcomes. `classify` builds CONFLICT and UNKNOWN
     with no receipt.
   - The new log lines carry tool and job names and action ids only.
   - The child-process log is checked for four secrets through one boolean.
   - The evidence files hold no token or handle.
   - The handle-taking calls inside `assert` in `test_migration_0010_live.py` (for example lines 212-216) cannot print
     a handle. Pytest's rewriter does not expand an `await` expression and shows only its result. They are
     stylistically unlike the t47 module after `28d3f0b`, but harmless.
6. **Records** (focus 6):
   - The matrix rows R030, R131, R025 and R031 match the tests and evidence lines.
   - Errata 82-92 match the code (82's reason table, 85's answers, 86's guard, 88's schema, 89's four plain errors,
     91's set).
   - ARCHITECTURE §8 and the runbook's allowlist table match `ATTEMPT_STATES`.
   - The next step is right: T17 is the only dependency-satisfied PLANNED task (T03 and T44 are DONE_PENDING_OWNER;
     T22 still waits on T21).
   - The working tree's one modified file (`docs/superpowers/research/2026-10-16-plan-k-inputs.md`) has no content
     diff, only stat dirt.

### Deferred-minor triage (the ledger's deferred items)

| # | Ledger item | Verdict | Reason |
|---|---|---|---|
| T1-a | `test_verifier_t47` `is None, why` could print an AccessToken repr | fix in the wave | One line (bind to a boolean). It keeps the secrets rule literal, as the stamp test beside it already does |
| T1-b | `workload_client_id()` does not strip whitespace | fix in the wave | Fails closed today (no token carries " ops-worker"), but a padded value turns a typo into an opaque 401. Strip, or refuse whitespace with a SettingsError |
| T1-c | No end-to-end env test of `production_app`'s azp | stay deferred | Each construction point is tested |
| T2-a | `execution.py` denylist / re-send skipped `mark_sent` | closed | Task 3 |
| T2-b | Runbook "never downgrade past 0010 with ABORT_REQUESTED rows" | closed | In the runbook |
| T2-c | No live `request_abort` with another run's action id (OC002) or a finished job's handle (OC008) | fix in the wave | It is the new definer's own authority check. One or two calls in `test_migration_0010_live.py` |
| T2-d | Stale `reports/mcp-read` R131 count | closed | Committed at the close-out |
| T2-e | Orphaned azp block comment above `grant_execution` (`persistence.py:475-477`) | fix in the wave | Trivial: attach it to the function or fold it into the docstrings |
| T3-a | `_abort` forwards any non-`resolved` answer as the abort reason | fix in the wave | Allowlist `keys.ABORT_REASONS`' three tokens and raise PersistenceError otherwise. incident-sim's 422 makes the current failure UNKNOWN, so the severity is as recorded, but the check belongs before the POST |
| T3-b | No scripted test of `_abort`'s `resolved` read-back | fix in the wave | Cheap, and it is the only branch of `_abort` without a test |
| T3-c | Resolve-time INVALID_HANDLE for the recovery tools only implicit | fix in the wave if cheap | One parametrised case in `test_write_tools_server.py` |
| T3-d | OTHER_PROPOSAL surfaces as GRANT_REFUSED | stay deferred | Documented in erratum 89 and the runbook |
| T4-a | Module docstring "Catches" broader than the module | fix in the wave | Trivial wording |
| T4-b | Setup before `try` can leak runs | stay deferred | Plan J precedent; counts are diffed |
| T4-c | `free_port` TOCTOU / no start timeout | stay deferred | Inherited harness behaviour |
| T5-a | Process test does not pin SENT→RESOLVED after the child's lookup | fix in the wave | One `attempt_states` assert. It also proves the child recorded the outcome, not only answered it |
| T5-b | EVIDENCE path relative to cwd | stay deferred | Gates run from the root |

### Declined to judge

- **The gate counts (1152/180 dev, 1311/21 live) and `verify_handoff` exit 0.** I took the ledger's measured numbers;
  my finding did not need a run.
- **A handle refused in the middle of a call after SENT.** Examples: `request_abort` on the re-send path meeting a
  lease that lapsed or a handle that expired between `mark_sent` and the abort. These surface as `INVALID_HANDLE`
  rather than UNKNOWN. This is the same class as Plan J's `mark_sent` refusal on a re-send, the worker hands the job
  back on LeaseLost, and the 60 s handle versus a sub-second gap makes the rest negligible. T22's.
- **`_resolve_handle`'s `v_ctx.azp <> p_client_azp` (0007/0009).** It would pass a NULL `azp`. It is outside this
  range, the only caller is `mcp_exec` passing a verified non-null `azp`, and a compromised mcp-write could pass the
  right client name anyway. An `IS DISTINCT FROM` hardening is a candidate for whoever next re-creates
  `_resolve_handle`.
- **The merits of errata 82-92 and of marking R030/R131 IMPLEMENTED_LOCALLY_VERIFIED subject to errata 72, 84 and 91.**
  Both are owner decisions.
- **ABORT_REQUESTED has no event of its own.** SA:465 says "via `record_outcome`"; the journal sees the abort only
  when it resolves.
- **PR numbers and remote refs.** `gh` is unavailable; I did not check SESSION_STATE's PR list against GitHub.

### Recommendations

1. One fix wave: I1 (the allowlist row, the comment, the errata and records), M1, and the "fix in the wave" rows
   above. Then re-run both gates and `verify_handoff`.
2. Fill PROJECT_HISTORY §28's "Final review (whole branch)" placeholder with this review's problems and fixes.
3. Give T22's review notes the full set of attempt states an EXECUTING run can be left in without a job after a
   worker-side `McpCallFailed`. With I1 fixed, the set should be empty. The rule to keep is: every re-queued execute
   job either reaches the destination's key or answers UNKNOWN, never a final refusal while the run is EXECUTING.

### Assessment

**Ready to merge?** With fixes

**Reasoning:** The safety properties hold: nothing reaches incident-sim without a committed grant and a committed
SENT or ABORT_REQUESTED, the definers serialise correctly, the `azp` is the verified token's, and `mcp_exec` is
exactly its seven functions. The one Important gap is a liveness hole where Plan K's allowlist meets the worker's
existing re-queue. The fix is one table row plus records. M1 and the cheap deferred minors fit in the same wave.

### Re-review of the fix wave

Range `6ec740f..5c96f0d` (three commits: `b2ba317` fix, `97367e0` tests, `5c96f0d` docs). I read the whole fix diff
and the fixer's report. I checked the I1 claims against 0005's `grant_execution` replay, 0007's `mark_unknown` and
`record_outcome`, and `handlers.execute`. I did not run anything; the measured gates are dev 1161/182, live 1322/21
and `verify_handoff` exit 0.

**Verdict: Ready to merge.** No residual defect. There is one optional rewording (item 3 below).

#### 1. Each item is fixed, and the I1 fix opens no new send path

- **I1.**
  - `jobs.py:120` now admits ABORT_REQUESTED for `(EXECUTE, CREATE_INCIDENT)`, with the reason in the block comment.
  - At that state the call cannot send anything:
    1. `grant_execution`'s replay returns the existing grant whatever the attempt state.
    2. `next_step` answers `aborting`, and `execution.py:121-125` returns UNKNOWN before any `mark_sent`.
    3. The only roads to an incident POST (`mark_sent` answering `sent`/`already_sent`) and to an abort POST
       (`mark_sent` answering `cancelled`/`expired` → `_abort`) both go through `mark_sent`, and this call never
       reaches it.
    4. Attempt states only advance, so a call that resolved at ABORT_REQUESTED sees ABORT_REQUESTED or RESOLVED in
       `grant_execution` (`aborting` or `stored`), never INTENT or SENT.
    5. Even if `mark_sent` were reached, 0010 answers `abort_requested` there.
  - **The `mark_unknown` claim holds.** Its only body is 0007's (`0007_leases_fences.py:316-368`); 0008-0010 do not
    re-create it. It reads the lease and fence, `runs.state` and `execution_grant`, and never the attempt state. It
    accepts an EXECUTING run and inserts the `<action>:timeout` recover job.
  - The unit case (`test_write_tools_server.py`) drives the real `resolve_invocation`/`allowed_tool` and pins
    `script.calls == ["grant_execution"]`.
  - The comment at `execution.py:222-228` is now true for both the SENT path and the abort path.
- **T3-a.** `_abort` checks `ABORT_REASONS` (`execution.py:200-201`) after the `resolved` read-back. It does so
  before the `abort` closure exists and before `_ask`, so a bad reason is never POSTed. The test pins
  `abort_reasons == []` and the call sequence stopping at `request_abort`, for both callers.
  - The resulting PersistenceError is unmapped in `answer`, so it surfaces as a tool error and the worker re-queues.
    With I1 fixed, that re-queue lands in `aborting` → UNKNOWN → `mark_unknown`, so this path is safe too.
- **M1 and the other minors.** M1's four sentences, T1-a, T1-b, T2-c, T2-e, T3-b, T3-c, T4-a and T5-a are each
  present and match the report.
  - T1-b keeps the old behaviour for an empty value (default) and adds trimming.
  - T2-c's OC002 case cancels the second run first, so the refusal is the run binding, not ABORT_NOT_DUE. It has a
    positive control.
- **PROJECT_HISTORY §28's** final-review paragraph is filled in and accurate.

#### 2. No new defect and no weakened assertion

- **The I1 live test** (`test_mcp_write_t47_live.py:557`) asserts:
  - UNKNOWN with the grant's action id;
  - `calls.made == []` (no incident POST, no abort POST, no lookup);
  - unchanged grant/attempt/job/proposal counts and an unchanged destination key total;
  - `at_destination == (None, 0)`, i.e. no key and no incident;
  - attempts `[INTENT, ABORT_REQUESTED]` and the run still EXECUTING;
  - then `mark_unknown` → OUTCOME_UNKNOWN with exactly one open recover job `<action>:timeout`.
- **Its reported red is plausible.** With the row reverted, `resolve_invocation` refuses, so `data()` meets `'error'`
  where it expects `'outcome'`. That is the reported failure at `:152`. I take the measured run at its word.
- **No assertion was weakened.** The only test edits to existing tests are:
  - the rulings table gaining ABORT_REQUESTED;
  - `STORED` hoisted to module level (same value);
  - T1-a, which turns an operand into a boolean with the same verdict;
  - T4-a, docstring narrowing only.
  - The new allowlist test also pins that RESOLVED stays refused for execute jobs.
- **EXPECTED_LINES** is 11, matching the regenerated evidence file's eleven lines.

#### 3. The records match the code

- Erratum 84, the runbook table and paragraph, ARCHITECTURE §8's allowlist bullet, the tasks.json/BUILD_BACKLOG
  notes, mcp-write's README, the threat-model rows, SESSION_STATE, STATUS and PROJECT_HISTORY §28 all say what the
  code now does.
- **The sentence the fixer left** (`docs/ARCHITECTURE.md:288-289`: "`request_abort` commits ABORT_REQUESTED … before
  the abort POST; nothing is sent after it") should be reworded.
  - Read literally it contradicts the clause before it: the abort POST, and any repeat of it by a recover job,
    follow ABORT_REQUESTED. What never follows it is an incident POST.
  - The same bullet also lists "an attempt with an abort requested" among `mark_sent`'s refusals and then says
    "`create_incident` then aborts instead of sending". For `abort_requested` the call answers UNKNOWN; it does not
    abort.
  - Suggested text: "… and a recover job's re-send, writing nothing; on `cancelled` or `expired` `create_incident`
    aborts instead of sending, and on `abort_requested` it answers UNKNOWN. `request_abort` commits ABORT_REQUESTED,
    with the reason it chose, before the abort POST; no incident POST ever follows it."
  - This is cosmetic. It is not a merge blocker, and it fits the PR or the next docs touch.

#### 4. Recommendation 3 (a T22 note on attempt states that leave an EXECUTING run without a job) is no longer needed

- The execute row now admits every attempt state except RESOLVED. `record_outcome` moves the run out of EXECUTING in
  the same transaction that writes RESOLVED, so an EXECUTING run never has a RESOLVED attempt. The set of attempt
  states that strand a re-queued execute job is therefore empty.
- The live I1 test pins the hand-off to OUTCOME_UNKNOWN with a recover job.
- The only remaining way for a re-queued execute job to get a final refusal while the run is EXECUTING is a handle
  that expires between two definer calls under a live lease. That is the pre-existing Plan J class, listed under
  "Declined to judge" and already T22's, not an attempt-state rule.
- A one-line T22 review note saying that every refusal of an execute job on an EXECUTING run should be treated as
  needing `mark_unknown`, never as final, would be harmless, but it is optional.

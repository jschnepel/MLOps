# Plan K review record — T47 authenticated mcp-write and the recovery tools

Plan: `docs/superpowers/plans/2026-10-16-first-slice-k-mcp-write-recovery-tools.md` (branch `plan-k`; plan commit 52d4075, round fixes d2d064f and b0997da). Inputs:
`docs/superpowers/research/2026-10-16-plan-k-inputs.md` and the controller's rulings brief (reproduced below). The plan
writer built the slice in a scratch copy and applied the plan task by task (ruff format between tasks, ruff, mypy strict,
non-live pytest, dev counts, red steps); each round is one static adversarial review that repeated that apply on a fresh
`git archive` tree. Live steps cannot run in a dry run (no database; the permission policy refuses copying `.env`), so
every live count in the plan is arithmetic until execution.
Round 1: 0 Blocking, 1 Important, 11 Minor. Round 2: ACCEPT (0 / 0 / 4); the minors were folded in without a third round.

---

# Controller brief (rulings before round 1)

# Plan K brief — controller rulings for T47 (authenticated mcp-write and the recovery tools)

Branch `plan-k` (= `plan-j` 9f34038). Fact sheet: `docs/superpowers/research/2026-10-16-plan-k-inputs.md` (FS).
Errata continue at **82**. Requirements: R030, R131 (write half; complete with T15's read half), plus the write
halves of R025/R031 recorded as notes. Gates at start: dev 1075 / 164; live 1218 / 21; verify_handoff 0.

Principle: T47 builds the **server side** of the write and recovery tools — every tool body, every definer they call,
their refusals and envelopes, proved by staging jobs, handles and destination faults directly (as T15 did). The
**worker side** of recovery (a recover handler, the 1/2/4/8 s backoff loop, scheduled recover jobs, redispatch with a
new attempt row, `action.redispatched`, escalation, late evidence after RESOLVED) stays T22's.

## Rulings (one per FS question)

1. **Tools (FS Q1).** mcp-write registers `create_incident`, `get_incident_receipt` and `abort_incident`, each with a
   full body: the destination client calls (POST, GET `/internal/actions/{id}`, POST `/internal/actions/{id}/abort`),
   outcome classification, `record_outcome`. No worker caller for the recovery tools in T47 (T22).
2. **`request_abort` (FS Q2).** Created in T47 with two real callers: `abort_incident`, and `create_incident`'s
   cancelled/expired branch (ruling 24). This satisfies Plan E ruling 1 and completes R131's set.
3. **`request_abort` signature and reason (FS Q3).** `request_abort(raw_handle, client_azp, action_id, reason)` with
   the same handle/fence/job binding as `mark_sent` (erratum 48 pattern). The **server** chooses the reason, never the
   worker: `cancelled_before_send` (attempt INTENT and `cancel_requested`), `expired` (attempt INTENT and the dispatch
   deadline passed), `deadline` (attempt SENT and the dispatch deadline passed, or `cancel_requested` after SENT —
   SA:248 "immediate abort request" on cancel). Mapping to the run's FAILED reason: INTENT → `cancelled_before_send` /
   `expired`; after SENT → `aborted_no_commit` (`deadline` is a destination reason, not a run reason — erratum).
4. **Attempt-state allowlist (FS Q4).** In Python (erratum 19/76): `allowed_tool(job_type, run_state, attempt_state,
   tool)`. Rules: execute/`create_incident`: no attempt, INTENT or SENT (ruling 5); recover/`create_incident`: INTENT
   only (SA:345 wins over SA:334 — erratum); recover/`get_incident_receipt`: any attempt (SENT, ABORT_REQUESTED,
   RESOLVED — a resolved one answers the stored outcome); recover/`abort_incident`: INTENT, SENT or ABORT_REQUESTED.
   "Not cancelled, before the deadline" stay in `mark_sent` (they need `cancel_requested` and `granted_at`).
   `resolve_invocation` returns the attempt state (it already reads it — check) so the rule has it.
5. **The SENT re-send (FS Q5).** Kept for execute jobs (Plan E ruling 6, erratum 14: a re-queued execute job after a
   lost response re-POSTs the same action id; the destination is idempotent). Erratum: SA:344's "attempt absent or
   INTENT" gains SENT for execute jobs.
6. **Redispatch (FS Q6).** `mark_sent`'s EXECUTING guard stays; a recover-job `create_incident` on INTENT works while the
   run is EXECUTING. Redispatch from OUTCOME_UNKNOWN, attempt row 2 and `action.redispatched` → T22 (debt).
7. **`record_outcome` after an abort request (FS Q7).** Re-created to accept SUCCEEDED/CONFLICT when the latest state
   is SENT **or ABORT_REQUESTED** (an abort answered by the existing receipt); FAILED_NO_COMMIT as today. Late evidence
   after RESOLVED → T22 (debt).
8. **R030 evidence (FS Q8).** Live: an execute handle refused at both recovery tools (allowlist); an investigate handle
   refused; a recover handle answered with the minimal `ActionOutcome` (action id, hash, outcome, receipt or
   tombstone) only; the recovery tools never insert a grant, attempt (other than ABORT_REQUESTED/RESOLVED state rows),
   job or proposal — row counts before/after; `get_incident_receipt` never POSTs (destination keys unchanged).
9. **Discovery (FS Q9).** All three tools are listed to any authenticated caller (only the worker workload can
   authenticate at mcp-write); refusal is per handle. Erratum: BS:393's "filter from normal discovery" is met by
   registering the tool only on mcp-write, which only the workload reaches, and refusing every non-recover handle.
10. **Envelopes (FS Q10).** A refused handle at any tool → plain `INVALID_HANDLE`, no action id (erratum 59's
    post-SENT exception for `create_incident` stands). Destination 404 or 429/503 → `outcome`/UNKNOWN with the action
    id. `abort_incident` data = the schema's `{action_id, outcome, receipt|tombstone}`; tombstone `reason` uses the
    destination's token (`cancelled_before_send`, `expired`, `deadline`); fix the example text if it differs.
11. **Verifier parity (FS Q11).** `write_verifier` constructor (shared with unit tests, used by `production_app`):
    `typ == "Bearer"`, aud containment before stamping, `validate_token_resource=True`; the same unit cases as
    `tests/plan_j/test_verifier_t15.py`; `McpVerifier` stays per service (ADR-0003).
12. **Naming the worker client once (FS Q12).** Setting `OPS_WORKLOAD_CLIENT_ID` (default `ops-worker`) in
    `settings`, read by the worker's token source and both verifiers' `allowed_azp`. The write-path definers take the
    caller's token azp as a `client_azp` argument (as `resolve_invocation` does) instead of the literal: revision 0010
    re-creates `grant_execution`, `lookup_action`, `mark_sent`, `record_outcome` (and creates `request_abort`) with it.
13. **R131 ACL (FS Q13).** Live equality: `mcp_exec` executes exactly `{current_time, resolve_invocation,
    grant_execution, mark_sent, record_outcome, request_abort, lookup_action}` (`current_time` per erratum 15);
    `has_function_privilege` false for every other `app` function; one attempted call to a worker-only function
    (`mark_unknown`) → 42501. "Cannot execute any read function": the read functions `asset_scope` /
    `search_procedures_scoped` do not exist yet (T16/T17) — erratum like 72.
14. **A read handle at mcp-write (FS Q14).** Live over HTTP: an investigate handle and a staged `resume_input` handle
    refused; a lying `server` column refused; positive controls (the same handle accepted by mcp_read's
    `resolve_invocation`; the write handle accepted at mcp-write).
15. **incident-sim refuses mcp-read's token (FS Q15).** Live: an `ops-mcp-read` workload token → 403 at incident-sim.
    The network half ("mcp-read cannot reach incident-sim") stays T30 with a matrix note.
16. **Independent client (FS Q16).** mcp-write as a child process (`python -m ops_mcp_write`, like Plan J's), official
    `Client`: lists exactly the three tools, calls `get_incident_receipt` with a staged recover handle for a committed
    action (no new action). Evidence `reports/mcp-write/`. R025/R031 write halves recorded in notes.
17. **Deadlines (FS Q17).** The dispatch deadline is enforced in `mark_sent` (`expired` when `app.current_time() >
    granted_at + dispatch seconds`, compared after the lock) and used by `request_abort`'s reason and the abort's
    due-ness. The value lives in a SQL helper `app._dispatch_seconds()` returning 300 in revision 0010 (configurable
    later → T29 debt); tests move `app.test_clock`. Escalation stays T22.
18. **Backoff (FS Q18).** T22. Each recovery tool call does one destination call with the client's timeout.
19. **Faults (FS Q19).** Live tests at the recovery tools: `delay_receipt` (404 → UNKNOWN), `lose_after_commit` then
    `get_incident_receipt` → SUCCEEDED, `receipt_hash_mismatch` → CONFLICT, `rate_limit` → UNKNOWN. The abort route
    gains no fault hook; narrowing incident-sim's fault kinds → debt.
20. **STALE_RUN / HASH_MISMATCH (FS Q20).** Test each mapping that is reachable through the tool; an unreachable mapping
    is removed only if provably dead, otherwise kept with a comment and a T22 debt line.
21. **The EXECUTING re-send test (FS Q21).** Live: arm `lose_after_commit`, call `create_incident` (UNKNOWN; attempt SENT;
    run EXECUTING), call again with a fresh handle for the same open execute job → SUCCEEDED, same action id, one
    incident at the destination. The test is the client.
22. **Trust statement (FS Q22).** A new `docs/threat-model.md` with the outcome-truth statement (mcp-write is trusted for
    outcome truth; T10's detective check `skeleton.py keys` is the control; HMAC-signed receipts are a v1.1 debt).
23. **Recover handles (FS Q23).** Staged directly in tests; no worker recover path (T22).
24. **The cancelled/expired branch of `create_incident` (FS Q24).** Replaced per SA:348: `request_abort` → abort POST →
    `record_outcome` with the tombstone → FAILED_NO_COMMIT (`cancelled_before_send` or `expired`). Live tests for both
    (cancel before send; test clock past the dispatch deadline).
25. **Revision 0010 (FS Q25).** `0010_write_path`: `request_abort`; the four re-created definers (client_azp, `expired`,
    record after ABORT_REQUESTED); `_dispatch_seconds`; frozen callers; exact downgrade to 0009 (re-run the applied
    bodies). mcp-write's startup asserts a 0010 marker (the `HANDLE_BINDING` pattern); mcp-read needs none.
26. **Recovery tools resolve first (FS Q26).** Each recovery tool calls `resolve_invocation` (Python allowlist with the
    attempt state) before its definers, as `create_incident` does.
27. **Bookkeeping (FS Q27).** R030 → evidenced; R131 → complete (both halves; DoD 3's network half → T30 note); R025 and
    R031 notes record the write halves; `tests/plan_k`; `reports/mcp-write/`.

## Task shape (≤ 6 tasks)
1. Debt list; `OPS_WORKLOAD_CLIENT_ID`; `write_verifier`; unit tests.
2. Revision 0010 (request_abort, client_azp, dispatch deadline, record after abort) + persistence wrappers + mcp-write
   startup marker + live definer tests (incl. downgrade round trip).
3. The attempt-state allowlist; the two recovery tools; `create_incident`'s cancelled/expired branch; envelopes; unit
   tests.
4. Live HTTP evidence: R030, R131 write half (ACL, read handles at mcp-write), incident-sim refusing mcp-read's token,
   the EXECUTING re-send, the faults at the recovery tools, cancel-before-send and expired.
5. The independent mcp-write client; `docs/threat-model.md`.
6. Close-out (handoff, matrix rows, errata 82+, runbook `docs/runbooks/mcp-write.md`, STATUS, SESSION_STATE incl. "migrate
   dev to 0010" and a correct next step computed from tasks.json, ARCHITECTURE, PROJECT_HISTORY, READMEs).

## Standing constraints
Carry Plan J's Global Constraints (no attribution; CODE_COMMENTS; debt before code; app.current_time() after locks; one
string per SQL function + ISC004; exact downgrades; live tests only on test databases; never migrate dev; no token or
raw handle in logs/asserts/evidence/command lines; never cancel a database unit; pids before transactions; settle
before purges; test clock reset in finally; subprocess servers terminated in finally with secrets only via environment;
red-step Expected lines as pytest prints them; live counts marked arithmetic). The no-unapproved-external-action
boundary: every POST to incident-sim happens only after `grant_execution` committed a grant for an approved proposal;
an abort never creates an incident.

---

# Controller rulings on the writer's departures

# Plan K — controller rulings on the writer's departures (draft 52d4075)

- (a) `request_abort(raw_handle, client_azp, action_id)` with the reason chosen inside the function under the runs lock
  and returned — ACCEPTED. It is the brief's principle ("the server chooses the reason, never the worker") taken one
  step further: mcp-write cannot see `cancel_requested`/`granted_at`, and a reason chosen before the lock could be
  stale. Erratum 82 records the signature change against SA.
- (b) Extending `build_schemas.abort_outcome` to admit UNKNOWN/CONFLICT and regenerating `schemas/` — ACCEPTED (erratum
  88). The tool must be able to report what actually happened; the schema is generated, not hand-edited. The critic must
  check that every regenerated file is the generator's output and that `verify_handoff --contracts` stays 0.
- (c) `rate_limit` / `receipt_hash_mismatch` driven through `create_incident` and observed at the recovery tools; a 429
  at lookup/abort shown with an `httpx2.MockTransport` unit — ACCEPTED (incident-sim gains no fault hook, ruling 19).
- (d) "Any attempt" for `get_incident_receipt` = SENT, ABORT_REQUESTED, RESOLVED — ACCEPTED (an INTENT attempt was never
  sent; there is nothing to look up and a lookup cannot settle it).
- (e) `mark_sent` answering `abort_requested` (→ `create_incident` UNKNOWN) and the recovery tools refusing another
  proposal's id (`OTHER_PROPOSAL`, SA:538) — ACCEPTED.
- (f) `HASH_MISMATCH` mapping removed as provably dead, pinned by a body-scan unit test — ACCEPTED provided the critic
  confirms no definer body (any revision still applied at head) raises it.
- (g) `ABORT_NOT_DUE`, `STALE_RUN`, `OTHER_PROPOSAL` as plain error envelopes although a grant exists — ACCEPTED (erratum
  89); the action id is not needed by the caller to act and the envelope rule of erratum 59 stays narrow.
- (h) R025/R031 keep their statuses with notes — ACCEPTED (owned by T15/T04).

---

# Round 1

## Static review

## Plan K round 1: static adversarial critic

Plan: `docs/superpowers/plans/2026-10-16-first-slice-k-mcp-write-recovery-tools.md` (5,608 lines, branch `plan-k`,
52d4075).

**Verdict: REVISE.** 0 Blocking, 1 Important, 11 Minor.

Every splice of every task applies exactly once, and every per-task dev count matches the plan:

| Task | Dev gate | Plan says |
|---|---|---|
| 1 | 1089 / 164 | 1089 / 164 |
| 2 | 1102 / 168 | 1102 / 168 |
| 3 | 1146 / 168 | 1146 / 168 |
| 4 | 1146 / 178 | 1146 / 178 |
| 5 | 1146 / 179 | 1146 / 179 |
| 6 | 1146 / 179 | 1146 / 179 |

After every task:
- `ruff format` changes nothing;
- ruff and mypy strict are clean (inside `check.py`);
- `verify_handoff --reference-code --manifest --contracts` exits 0.

Every red step's count matches what pytest prints. One red step names the wrong error class for one of its three
modules (M1).

The revision is sound:
- it has the applied bodies plus only the named changes;
- SECURITY DEFINER, the owner, `search_path` and the ACLs are kept;
- the lock order and the clock reads after the lock match the 0007 bodies;
- the downgrade re-runs the applied bodies.

The regenerated `schemas/` are exactly the generator's output. The next step computed from `tasks.json` (T17) is
right. Errata 82-92 match the brief and the departure rulings.

The literal no-unapproved-external-action boundary holds:
- every incident POST follows a committed grant;
- the abort route can only write a tombstone;
- `get_incident_receipt` only GETs.

The one Important finding is a gap the plan states as closed. The execute job's SENT re-send skips `mark_sent`
entirely, so it re-POSTs after a cancel, past the dispatch deadline, and in a window after ABORT_REQUESTED. The plan's
Task 2 requirement line, erratum 84, Review Focus 1, the threat model and ARCHITECTURE §8 all say this cannot happen.

### How this was checked

- **Scratch tree.** I built a scratch tree from `git archive 52d4075` (no worktree; no `.env` or secret file copied)
  under `scratchpad/plank/critic1/tree` and ran `uv sync --offline`. I ran `git init` inside it only to diff between
  tasks.
- **Baseline.** `PYTHONUTF8=1 uv run python scripts/check.py` gave `1075 passed, 164 skipped`, `CHECK: GREEN`.
  `verify_handoff` exited 0.
- **Applying the plan.** I applied the plan one step at a time with my own tool (`critic1/tools/step.py`). It is the
  writer's `applyplan.py` regexes, scoped to one step. It requires every `Edit` match to be unique and reports any
  `Edit`/`Create` line it cannot parse; none went unparsed.
  - I checked the writer's tool against my results rather than trusting it: the same splices, the same counts.
  - After each step I ran the step's own Run command and compared its output with the Expected line.
- **Red steps.** All of them:
  - Task 1 Step 3: `10 failed`, every one `has no attribute 'write_verifier'`.
  - Task 1 Step 5: `2 failed, 2 passed`, with the stated `AttributeError` and
    `ops_core.tokens.WrongAudience: token was issued to a client this server does not accept`.
  - Task 2 Step 1: `3 errors in`.
  - Task 3 Step 1: `2 errors in` (the `ATTEMPT_STATES` ImportError twice).
  - Task 3 Step 3: `36 failed, 9 passed`.
- **Intermediate Expected lines.** All of them match:
  - `All checks passed!` from ISC004, with the revision byte-identical to the plan's text afterwards;
  - `41 passed`;
  - `rewritten: 10 files, 61 call sites`;
  - `4 files reformatted, 41 files left unchanged`;
  - `212 passed`, `31 passed`, `45 passed`;
  - `682 passed, 19 skipped`;
  - the generator's line `25 schema documents ... 89 examples (35 valid, 54 invalid); index.json version 1.3.3`.
- **The schema regeneration.** `git status --short schemas` lists exactly the ten files the plan names. Every example
  changes only the tombstone reason (`cancelled before send` → `cancelled_before_send`). The schema diff adds UNKNOWN
  and CONFLICT and splits the `if/then/else` into three `if/then` rules, nothing else. No schema file is hand-edited.
- **Call sites.** An AST scan of every test, script and service found no call to the four wrappers (or to
  `execution.create_incident`) without `azp`. A regex scan found no SQL call with the old arity.
- **Revision 0010 bodies.**
  - I diffed `MARK_SENT` against 0007's: the signature, the token azp, the `abort_requested` branch, the deadline
    check and the comment. Nothing else changed.
  - I confirmed that 0008 and 0009 re-create none of the four functions, so the applied bodies at 0009 are 0007's
    (`grant_execution`, `mark_sent`, `record_outcome`) and 0004's (`lookup_action`), as the downgrade restores.
  - I grepped every revision for `OC007`. Only `freeze_proposal` (0004, never called by mcp-write) and
    `record_outcome` (0007/0010) raise it. That confirms departure ruling (f).
- **Task 6.** I ran the handoff script with `BASE` set to the scratch base:
  - it printed the span;
  - three handoff files changed;
  - four matrix rows changed (R025, R030, R031, R131).

  I computed the ready set from `tasks.json` with T47 DONE: T17 alone, counting DONE_PENDING_OWNER or not.
- **Live steps (static only).** Live steps cannot run here (no database). For each, I traced every helper they import
  and every definer they reach, statically:
  - the helpers: `approved_run`, `lease_for`, `mint_handle`, `execute_handle`, `recover_handle`, `mark_unknown`,
    `refused`, `assert_refused`, `call`, `started`, `process_environment`, `healthy`, `purge_run`,
    `fresh_memberships`;
  - incident-sim's routes, `keys.abort` / `keys.commit` / `keys.document`, and its token mapping;
  - the transitions table and `FAILED_NO_COMMIT_REASONS`;
  - the 0005/0007 bodies.

  The live arithmetic (1232, 1249, 1293, 1303, 1304) is consistent with 143 live-gated tests at the start.

### Blocking

None.

### Important

**I1 — The execute job's SENT re-send bypasses every check the plan says guards a send: cancel, dispatch deadline and
abort request.**

Where:
- `execution.create_incident` after Task 3 (Step 5, Edits 6-9, plan 3348-3415). Only `step == "send"` calls
  `persistence.mark_sent`; `step == "resend"` goes straight to `_ask(... post)`.
- 0010's `MARK_SENT` (1312-1316) answers `already_sent` for a SENT attempt before it looks at `cancel_requested` or
  the deadline, so even a `mark_sent` call would not help as written.
- `jobs.ATTEMPT_STATES` (2455) admits SENT for execute jobs with no condition.

The claims it contradicts:
- Task 2's Requirements (893-894): "the no-unapproved-external-action boundary (nothing is sent past the deadline,
  after a cancel or after an abort request)".
- Erratum 84 (299-300, 5062-5067): "'Not cancelled, before the deadline' is `mark_sent`'s check under the runs lock,
  not the allowlist's". `mark_sent` never runs on this path.
- Review Focus 1 (130-134): "Nothing may be sent once ABORT_REQUESTED exists ..., whichever call resolved its handle
  first".
- The threat model's row "A send after a cancel or past the dispatch deadline | `mark_sent` re-checks both" (4745).
- ARCHITECTURE §8 "Nothing leaves before it is written" (5349-5352).

Evidence:
- `worker/src/ops_worker/handlers.py:236-249` re-queues the execute job every 30 s on `McpCallFailed` (TODO(T22)), and
  the run stays EXECUTING.
- The re-queued call passes the allowlist (execute, EXECUTING, SENT; 2455).
- `grant_execution`'s replay path (0005 body, kept by 0007/0010) returns the grant without a cancel or deadline check.
- `next_step("SENT")` is `"resend"`, which POSTs.
- The only abort-request check on this path is the grant replay's read of the attempt state. It happens in a unit
  that has committed before the POST, so an ABORT_REQUESTED committed after that read is not seen.

Failure scenario:
1. mcp-write commits SENT, then dies, or the worker's MCP call times out, before the POST reaches incident-sim.
2. The requester cancels: the API sets `cancel_requested`.
3. Thirty seconds later the re-queued execute job calls `create_incident`, which POSTs.
4. incident-sim has no key, so it commits a new incident after the cancel.

The same happens ten minutes later, past the 300 s dispatch deadline. SA:242 says the SENT row's path past the
deadline is `abort_incident`, not a re-send, and SA:248 says a cancel after SENT triggers an immediate abort. The
destination's idempotent key prevents a second incident, but not this first one, which the cancel or the deadline
should have stopped.

No test covers it:
- `test_the_executing_re_send_returns_the_same_action` (4245) never cancels or moves the clock;
- `test_nothing_is_sent_once_an_abort_is_requested` (2713) covers only the `send` step and a grant replay that
  already sees ABORT_REQUESTED.

Proposed fix (small, inside Tasks 2-3):
- In 0010's `MARK_SENT`, check for SENT under the lock as well:
  - when `v_run.cancel_requested` or the deadline has passed, answer `cancelled` / `expired`, writing nothing;
  - otherwise answer `already_sent`.

  Keep ABORT_REQUESTED → `abort_requested` first. Put the order in the unit test
  (`test_mark_sent_sends_nothing_after_an_abort_request_...`).
- In `create_incident`, call `mark_sent` for `resend` as well as `send`. A `cancelled` / `expired` answer on a SENT
  attempt goes to `_abort`, and `request_abort` then chooses `deadline`, which is SA:248's immediate abort.
- Optionally refuse `already_sent` when `v_handle.job_type = 'recover'`. This closes M8's TOCTOU in the same place.
- Add tests:
  - a unit test: `Script(attempt="SENT", mark_sent="cancelled", request_abort="deadline", post_abort=tombstone(...))`
    gives `calls == ["grant_execution", "mark_sent", "request_abort", "post_abort", "record_outcome"]` with no
    `post_incident`;
  - a live definer case in `test_migration_0010_live`: a SENT attempt, then a cancel, then `mark_sent` answers
    `cancelled` and writes nothing.
- Reword erratum 84 to "SENT for execute jobs, still not cancelled and before the deadline, re-checked by `mark_sent`".

The residual window between `mark_sent`'s commit and the POST is inherent in AM-13 and is the same for both steps.

### Minor

**M1 — Task 2 Step 1's Expected names an ImportError in both new modules; the startup module fails with an
AttributeError.**
- Where: 1155-1158.
- Evidence: `tests/plan_k/test_mcp_write_startup.py` imports the module (`from ops_core import persistence`) and
  evaluates `BOTH = {persistence.HANDLE_BINDING[1], persistence.WRITE_PATH[1]}` at import. pytest prints
  `AttributeError: module 'ops_core.persistence' has no attribute 'WRITE_PATH'` for it. The count (`3 errors in`) is
  right.
- Fix: say "an ImportError in `test_migration_0010.py`, an AttributeError in `test_mcp_write_startup.py`".

**M2 — Task 6 Step 1's greps do not print nothing at that point.**
- Where: 4827-4837.
- Evidence: after Step 1's two edits, `git grep -n "T47 debt\|-> T47\|→ T47\|arrive with T47\|follows in T47" --
  ... mcp-write ...` prints `mcp-write/README.md:25: ... the recovery tools arrive with T47.`. `mcp-write` is in the
  path list, and only Step 4's Edit 8 rewrites that line. The plan's own parenthesis says so, yet the Expected is
  "both print nothing".
- Fix: run the greps after Step 4, or state the one expected line.

**M3 — The `HASH_MISMATCH` pin covers less than departure (f) claims.**
- Where: 1081-1087; the claim at 272-274 ("a later revision that adds an `OC007` there fails that test").
- Evidence: `test_no_definer_mcp_write_calls_before_destination_io_raises_a_hash_mismatch` scans only 0010's
  `FUNCTIONS`, 0004's `RESOLVE_INVOCATION` and 0009's `RESOLVE_HANDLE`. A revision 0011 that re-creates `mark_sent`
  or `grant_execution` with an `OC007`, or a helper they call (`_grant_row`, `_transition`, `_append_event`,
  `_authority`, `_tenant_of_run`, `_latest_attempt`) gaining one, passes it. Today no body raises it except
  `record_outcome` and 0004's `freeze_proposal` (which mcp-write never calls), so the removal itself is sound.
- Fix: walk `REVISIONS` and take the newest body of each function mcp-write reaches before a destination answer
  (the `newest` pattern of the next test), then assert no `'OC007'`. Or narrow the claim in (f).

**M4 — R030's "no-grant recover handle" is refused for its run state, not for having no grant.**
- Where: 4197, 4211-4216; the matrix note 4905-4912; the evidence line 4237-4238.
- Evidence: `bare` is APPROVED (`approved_run` never grants). `JOB_RULES[RECOVER].run_states` excludes APPROVED, so
  `allowed_tool` refuses at the run-state check before the attempt rule. The attempt rule's `None` case is never
  reached over HTTP. A run in a recover state without a grant cannot arise through the definers. The refusal is true
  but proves less than the note implies.
- Fix: word it as "a recover handle of an APPROVED run (no grant) is refused", or stage a no-grant run in
  OUTCOME_UNKNOWN as the superuser to exercise the attempt rule.

**M5 — Ruling 8's counts cover the lookups only.**
- Where: 4218-4232, 4313-4346; ruling 8 at 179-183.
- Evidence:
  - `COUNTS` is taken around the two `get_incident_receipt` calls only. No test takes it around `abort_incident`.
  - "Destination keys unchanged" is checked for the one action's key (`at_destination`), not as a global
    `incident.action_key` count around the lookups.
- Fix: in `test_a_rate_limited_send_is_aborted_once_cancelled`, take `COUNTS` and a global key count before the
  recover calls. Assert the counts are unchanged, and the keys +1 only after the abort (its tombstone).

**M6 — `persistence.request_abort` turns a NULL reason into the string `"None"`.**
- Where: 1564-1567.
- Evidence: `str(row["reason"])` on an ABORT_REQUESTED row without `detail->>'reason'` gives `"None"`, which `_abort`
  POSTs as the abort reason. incident-sim answers 422, which mcp-write reads as UNKNOWN. Only `request_abort` writes
  that state today, so the case is unreachable.
- Fix: raise `PersistenceError("request_abort returned no reason")` when it is None.

**M7 — `GUARD_0010` accepts a receipt after an abort requested from INTENT, removing a SQL backstop the 0007 guard
gave.**
- Where: 1232-1237.
- Evidence: the 0007 guard refused SUCCEEDED/CONFLICT unless the latest state was SENT, so INTENT → receipt was a
  protocol violation. With 0010, INTENT → ABORT_REQUESTED(`cancelled_before_send`/`expired`) → SUCCEEDED is
  accepted. A receipt is impossible there, because nothing was ever sent. Ruling 7's wording ("SENT or
  ABORT_REQUESTED") allows the broad form, so this is the controller's call.
- Fix: `v_latest.state = 'SENT' OR (v_latest.state = 'ABORT_REQUESTED' AND v_latest.detail->>'reason' =
  'deadline')`. That is "an abort answered by the receipt that already exists", which can only follow SENT.

**M8 — A recover job's `create_incident` can re-POST a SENT attempt (TOCTOU of the INTENT-only rule).**
- Where: 2456; 3351-3363.
- Evidence: the attempt rule is checked in `resolve_invocation`'s unit. If the execute job's `mark_sent` commits
  SENT before the recover job's grant replay, `next_step` is `resend`, and the recover job POSTs. SA:345 and
  erratum 84 say a recover job redispatches INTENT only. It is benign at the destination (same key and bytes).
- Fix: folded into I1. `mark_sent` sees `v_handle.job_type` and can refuse the recover job's re-send; otherwise
  record it in erratum 84 as a known race.

**M9 — R025 and R031 are left without anyone to flip them.**
- Where: 4931-4958; ruling (h) at 277-280.
- Evidence:
  - R025 is owned by T15 alone (DONE); R031 by T04 and T15 (both DONE).
  - After Plan K both rows have every half evidenced but stay `NOT_IMPLEMENTED_OR_NOT_TARGET_VERIFIED`.
  - No PLANNED task owns them, so these blocking-for-v1 rows dangle.
- Fix: keep ruling (h) and add one owner-input line in SESSION_STATE ("R025 and R031: every half evidenced; the
  status flip is the owner's or T15's re-close").

**M10 — The "nine refusals, no grant" check counts the wrong run.**
- Where: 4136-4137.
- Evidence: the refused handles belong to `read_run`, but the assertion counts `execution_grant` for `run`, the
  approved run whose execute handle has not been used yet. It is 0 whatever the refusals did.
- Fix: count for `read_run` as well, or use `COUNTS` before and after the nine calls.

**M11 — The 0010 downgrade docstring understates what a leftover ABORT_REQUESTED row means at 0009.**
- Where: 1426-1427.
- Evidence: "an `ABORT_REQUESTED` row a test left stays, as 0009's functions can read it". They can read it, but
  0007's `mark_sent` has no `abort_requested` branch and would insert SENT after it. The downgrade is test-only, so
  no behaviour fix is needed.
- Fix: say "0009's `mark_sent` would not honour it".

### Checked and found sound

- **The literal boundary.**
  - `create_incident` POSTs only after `grant_execution` returned a grant in a committed unit, and after `mark_sent`
    committed SENT (`send`) or after a replay found SENT (`resend`, see I1).
  - `post_abort` is called only after `request_abort` committed ABORT_REQUESTED.
  - incident-sim's abort route calls `keys.abort` → `_tombstone` (`INSERT ... ON CONFLICT DO NOTHING`, state
    ABORTED), never `keys.commit`. A later incident POST onto an ABORTED key returns the tombstone and never
    commits (SA:268), so an abort cannot create an incident and blocks a late send.
  - `get_incident_receipt` calls only `destination.get_action` (GET). The unit test pins the call list, and Task 4's
    `Calls` pins it live.
- **Revision 0010.**
  - `GRANT_EXECUTION`, `LOOKUP_ACTION` and `RECORD_OUTCOME` are derived with `_derived` from 0007's and 0004's
    module texts, and the unit test undoes the replacements to byte equality.
  - `MARK_SENT` differs from 0007's only as listed above.
  - `HEADER` is identical (SECURITY DEFINER, `search_path = app, pg_temp`, `app.tenant_id = ''`).
  - Every body ends in `OWNER TO app_definer`.
  - `function_grant_statements` gives each `mcp_exec` alone, and `_dispatch_seconds` nobody.
  - The upgrade drops the four old signatures first and creates `_dispatch_seconds` before its callers.
  - The downgrade drops all six, then re-runs 0007's / 0004's own bodies with the same callers. The live round
    trip compares prosrc, `pg_get_functiondef`, ACL, owner and config with a database built straight to 0009, and
    snapshots every `app` function before and after.
  - The lock order (`run_lease` FOR SHARE in `_resolve_handle`, then `runs` FOR UPDATE) matches SA:463-465.
  - `app.current_time()` is read after the runs lock in both `mark_sent` and `request_abort`, and the comparison is
    against `granted_at`, which 0005's grant writes with `app.current_time()`.
  - The cancel check comes before the deadline check in `mark_sent`, which the unit test pins.
  - `request_abort` chooses the reason under the lock exactly as ruling 3 and departure (a) say. It appends one
    `ABORT_REQUESTED` row with `{"reason": ...}`, returns the first reason on a repeat and `resolved` on RESOLVED,
    and refuses `OC005 ABORT_NOT_DUE` with nothing written.
  - The table's CHECK admits ABORT_REQUESTED, and `app_definer` holds INSERT on `detail`.
  - The handle, fence and open-job binding is `_resolve_handle(p_raw_handle, p_client_azp, 'write')` (0009's body),
    followed by `g.run_id = v_handle.run_id`: the erratum 48 pattern.
  - No other function body or service calls the replaced signatures.
- **The FAILED reason.**
  - `classify` derives `sent` from the tombstone's reason (`NEVER_SENT`), and `outcome_from_destination` gives
    `cancelled_before_send` / `expired` from INTENT and `aborted_no_commit` after SENT.
  - `record_outcome` takes `p_document->>'reason'` into `_transition`.
  - `transitions` allows EXECUTING/OUTCOME_UNKNOWN/ESCALATED → FAILED by `record_outcome` with every member of
    `_FAILED` (including `expired`).
  - `_transition` is called with no event, so the live test's `[-2:] == [action.granted, action.failed]` holds.
- **The allowlist.**
  - `ATTEMPT_STATES` is ruling 4 plus departure (d), tabled exhaustively by a unit test.
  - `resolve_invocation` converts the stored state to `AttemptState`.
  - The only production caller of `allowed_tool` is `resolve_invocation`.
  - A recover handle cannot reach another run (the handle picks the run, and `_resolve_handle` binds its own open
    job). Another proposal's id is refused `OTHER_PROPOSAL` before any call (`_granted`; `grant_execution`'s replay
    for `create_incident`).
  - The execute re-send reuses the grant's action id and bytes, and incident-sim's key is `ON CONFLICT DO NOTHING`
    with the same hash, so it is idempotent at the destination.
- **Concurrency.**
  - `request_abort`, `mark_sent` and `record_outcome` serialise on `runs` FOR UPDATE.
  - Two aborts produce one ABORT_REQUESTED row and two POSTs answered by the same tombstone. The second
    `record_outcome` returns the stored outcome, and `_record` reads it back if it differs.
  - An abort racing a send is decided by the destination's first writer, and both callers record the same key
    (receipt or tombstone).
  - A lost abort reply leaves ABORT_REQUESTED, which `get_incident_receipt` (admitted on ABORT_REQUESTED) can settle
    later.
  - Events are appended only by `record_outcome` under the runs lock.
  - mcp-write's single-connection `Session` never holds a unit across destination I/O.
- **Envelopes.**
  - Every handle refusal is `INVALID_HANDLE` / "invocation handle rejected" with `data: None`.
  - `ABORT_NOT_DUE` (retryable), `STALE_RUN` and `GRANT_REFUSED`/`OTHER_PROPOSAL` carry no action id (unit and
    live).
  - After any destination answer, `_record` maps every `_POST_SENT_REFUSALS` to UNKNOWN with the action id.
  - The new log lines carry tool, job type, attempt and action id only.
  - The Task 5 leak check binds a boolean over the handles and both tokens.
- **Envelope contract.** `abort_envelope` validates for all four outcomes against the regenerated schema, and the
  R083 probes (`ok` around non-SUCCEEDED; a receipt on CONFLICT) are refused.
- **Verifier parity.**
  - `write_verifier` has mcp-read's `typ`, audience and `azp` from `settings.workload_client_id()`.
  - `McpVerifier` refuses an `aud` without this server's URL before stamping.
  - `validate_token_resource=True` with honest docs: it cannot refuse while the stamp is the server's own URL, which
    was Plan J's I-finding, not repeated here.
  - The unit cases are a superset of `tests/plan_j/test_verifier_t15.py`'s.
- **Existing live tests.**
  - No test seeds an old `granted_at` and then expects `sent` (the only direct `execution_grant` INSERT,
    `test_migrations_and_persistence.py:361`, is RESOLVED).
  - No live test moves `app.test_clock` between a grant and a `mark_sent`: `test_outbox_live` moves it only after
    SENT, and `test_mcp_read_t15_live` only at mcp-read.
  - No live test expects the old cancelled → UNKNOWN branch.
  - The migration round trips (0007's to 0006, 0009's to 0008, R006's to `testclock@base`, 0004 and 0001) all pass
    through 0010's exact downgrade. Their remaining head-signature literals sit in downgraded contexts.
  - The 0007 test's last line is rewritten by the plan.
  - Plan J's ACL equality test and `job_at_mcp_exec` use SQL `resolve_invocation`, whose signature is unchanged.
  - R105 runs the worker with `main.token_source` and the default client.
- **Live mechanics (static).**
  - Every handle that crosses a server start or a clock move is minted after it (60 s TTL). Handles minted earlier
    are used within seconds.
  - Every lease used after the 400 s move is a fresh 600 s lease, and the 120 s leases of `approved_run` cover each
    test's span otherwise.
  - Grants precede every clock move, and `fresh_memberships` is autouse.
  - The test clock is reset in an inner `finally`.
  - uvicorn stops through `should_exit`, and the child gets `terminate()` then, after 15 s, `kill()`. Secrets reach
    it only through `process_environment()` (`OPS_SECRETS_DIR`).
  - Purges come after every server stopped.
  - No backend pid is read and no unit is cancelled.
  - incident-sim maps mcp-read's token (`aud asset-sim`) to `WrongAudience` → 403 `FORBIDDEN` on all three routes.
  - `mark_unknown(worker, run, fence)` queues exactly one recover job, and the STALE_RUN path goes through the
    grant replay into `mark_sent`'s EXECUTING guard (OC003 → `VersionConflict`).
- **Close-out.**
  - `tasks.json` gives T17 as the only ready PLANNED task after T47 (T16 waits on T17).
  - The handoff script asserts T47 PLANNED, appends one note, flips R030 and R131 to `IMPLEMENTED_LOCALLY_VERIFIED` /
    `RECORDED_LOCALLY_LIVE`, and only extends R025's and R031's notes and paths (departure ruling (h)).
  - Errata 82-92 match rulings 3-18 and departures (a), (b), (e), (g).
  - The debt list names T22, T29, T30 and v1.1 for everything deferred.
  - No `TODO(T47)` is left in live code after Task 3.

## Controller rulings

# Plan K review, round 1 — controller rulings

Input: `round1-static.md` (REVISE: 0 Blocking, 1 Important, 11 Minor; every splice, dev count, red step, ruff, mypy and
verify_handoff verified on a scratch tree; schemas are exactly the generator's output). Departure rulings (a)-(h) in
`writer-departures-rulings.md` stand.

- **I1 — ACCEPTED as proposed.** 0010's `MARK_SENT` order under the lock: ABORT_REQUESTED → `abort_requested`; then for a
  SENT attempt: `cancel_requested` → `cancelled`, deadline passed → `expired`, a `recover` handle → refused (new answer,
  e.g. `not_redispatchable`, which `create_incident` maps to a plain error and never POSTs — this folds M8), otherwise
  `already_sent`; INTENT as today. `create_incident` calls `mark_sent` on `resend` as well as `send`; a
  `cancelled`/`expired` answer on a SENT attempt goes to `_abort`, where `request_abort` chooses `deadline` (SA:248's
  immediate abort). Tests: the unit Script case the critic gives (no `post_incident`); a unit case for the recover
  re-send refusal; live definer cases in `test_migration_0010_live` (SENT + cancel → `cancelled`, writes nothing; SENT +
  clock past deadline → `expired`; recover handle on SENT → refused). Reword erratum 84, the threat-model row, Review
  Focus 1 and ARCHITECTURE §8 so they match exactly what the code checks. State in the plan that the window between
  `mark_sent`'s commit and the POST is inherent in AM-13 and identical for both steps.
- **M1 — ACCEPTED** (ImportError in one module, AttributeError in the other; count unchanged).
- **M2 — ACCEPTED** (run the greps after Step 4, or state the one expected line — prefer moving them).
- **M3 — ACCEPTED, walk `REVISIONS`** and take the newest body of each function mcp-write reaches before a destination
  answer, including the helpers; assert no `'OC007'`.
- **M4 — ACCEPTED, reword** ("a recover handle of an APPROVED run (no grant) is refused by the run-state rule"); a
  no-grant run in a recover state cannot arise through the definers — say so in the matrix note. No superuser staging.
- **M5 — ACCEPTED** as proposed (COUNTS and a global destination key count around the abort; keys +1 only by the
  tombstone).
- **M6 — ACCEPTED** (`PersistenceError` on a None reason, with a unit test).
- **M7 — ACCEPTED, the narrow guard**: receipt after ABORT_REQUESTED only when that row's reason is `deadline` (i.e. it
  followed SENT). Update erratum 86 and ruling 7's wording in the plan; add a live definer case: INTENT →
  ABORT_REQUESTED(`cancelled_before_send`) → SUCCEEDED refused.
- **M8 — folded into I1.**
- **M9 — ACCEPTED** (owner-input line in SESSION_STATE; ruling (h) stays).
- **M10 — ACCEPTED** (COUNTS before/after the nine calls).
- **M11 — ACCEPTED** ("0009's `mark_sent` would not honour it").

Apply in one pass; recompute every affected dev count and red-step Expected line by re-running the task-by-task apply
on a fresh `git archive` tree with `ruff format` between tasks, the splice check, mypy, verify_handoff; update the
live arithmetic. Append "Round 1 changes" / "Round 1 open points" to the plan. Do not commit.

---

# Round 2

## Static review

## Plan K round 2: static adversarial critic

Plan: `docs/superpowers/plans/2026-10-16-first-slice-k-mcp-write-recovery-tools.md` (branch `plan-k`, d2d064f; round-1
fixes are the diff 52d4075..d2d064f, 482+/190-).

**Verdict: ACCEPT.** 0 Blocking, 0 Important, 4 Minor.

I1 is closed in the code, not only in the prose. Every POST in `create_incident` now follows a `mark_sent` answer of
`sent` or `already_sent`. Under the runs lock, `already_sent` is given only to an execute job's re-send of a SENT
attempt, and only when the run is not cancelled and the dispatch deadline has not passed. Every other state gets
another answer, and every other answer leads to no POST:

- ABORT_REQUESTED gets `abort_requested`;
- a cancelled run gets `cancelled`, then an abort;
- a run past the dispatch deadline gets `expired`, then an abort;
- a recover handle gets `not_redispatchable`, a plain refusal.

Each of M1-M11 is fixed as the controller ruled.

The fixes introduce no defect:
- the lock order is unchanged;
- the clock is read once, after the runs lock;
- the 0010 downgrade still re-runs 0007's and 0004's own bodies;
- frozen callers and grants are unchanged;
- the new refusal names no action id;
- no handle or token reaches a log line or an assert operand.

I agree with the controller on the writer's open point (see below).

The four Minor findings are wording or robustness items:
- two texts still describe the old receipt guard or the old abort rule;
- the owner-facing full errata 85 and 89 lack the round-1 additions;
- the narrowed SQL guard fails open on a NULL reason, which no code path can produce.

None of them needs another round.

### How this was checked

- **Scratch tree.** `git archive d2d064f` into `scratchpad/plank/critic2/tree` (no worktree; no `.env` or secret
  file), then `uv sync --offline`. Every command ran with stdin from `/dev/null`, and every Python run was given a
  script or a heredoc.
- **Baseline.** `1075 passed, 164 skipped`, `CHECK: GREEN`.
- **Applying the plan.** I applied the plan one step at a time with the step-scoped splice tool from round 1. It
  requires every Edit to match exactly once and reports any Edit/Create line it cannot parse; none went unparsed.
  After each task I ran `ruff format` (it changed nothing), then `check.py` (ruff, ruff format --check, mypy strict,
  pytest) and `verify_handoff --reference-code --manifest --contracts`.
- **Dev counts.** Each one equals the writer's measurement and the plan's text:

  | Task | Dev gate | verify_handoff |
  |---|---|---|
  | 1 | 1089 / 164 | exit 0 |
  | 2 | 1103 / 169 | exit 0 |
  | 3 | 1152 / 169 | exit 0 |
  | 4 | 1152 / 179 | exit 0 |
  | 5 | 1152 / 180 | exit 0 |
  | 6 | 1152 / 180 | exit 0 |

  Every gate was GREEN.
- **Red and intermediate steps.** Every Expected line matches what pytest prints:
  - Task 1: `10 failed`, `10 passed`, `2 failed, 2 passed`, `14 passed`, all unchanged from round 1.
  - Task 2 Step 1: `3 errors in`. The ImportError is in `test_migration_0010.py` and the AttributeError in
    `test_mcp_write_startup.py`, as M1's rewording says.
  - Task 2, the rest:
    - ISC004 `All checks passed!`, with the revision byte-identical to the plan's text afterwards;
    - Step 4 `42 passed`;
    - the rewrite `rewritten: 10 files, 61 call sites` and `4 files reformatted, 41 files left unchanged`;
    - Step 5 `213 passed`.
  - Task 3:
    - Step 1 `2 errors in`, Step 2 `31 passed`;
    - Step 3 `41 failed, 9 passed`, where 22 failures print `has no attribute 'get_action'`;
    - Step 7: the generator line is unchanged and `git status` lists exactly ten files under `schemas`; then
      `50 passed` and `688 passed, 19 skipped`.
  - Task 6:
    - the two deferral greps, now at the end of Step 4, print nothing (M2);
    - the handoff script prints the span and changes three files;
    - T17 stays the computed next step.
- **The revision bodies.** I diffed 0010's `MARK_SENT` and `RECORD_OUTCOME` against 0007's, and listed `REPLACED`,
  `CREATED` and `RESTORED`.
- **The M3 walk.** I re-ran its reachability walk outside pytest to see what it actually covers:
  - `resolve_invocation` (0004);
  - `grant_execution`, `lookup_action`, `mark_sent`, `request_abort` (0010);
  - `_resolve_handle` (0009);
  - `_grant_row`, `_latest_attempt` (0004);
  - `_authority`, `_tenant_of_run`, `_transition` (0003);
  - `_append_event` (0008);
  - `_dispatch_seconds` (0010);
  - `current_time`, outside any `FUNCTIONS` tuple.
- **Existing live tests.** I searched for any live test that calls `create_incident` or `mark_sent` a second time
  on a SENT attempt:
  - `test_write_path_twice` and `test_concurrent_calls_share_one_attempt` (Plan D);
  - the `GrantThenDownMcp` and `UnknownMcp` fakes (`test_worker_live`);
  - the fence tests (`test_fenced_definers_live`).

  I checked each against the new `mark_sent` order.
- **Live steps.** They cannot run here (no database). I reasoned about them statically, as in round 1.

### Round-1 findings

- **I1 (fixed).**
  - *0010's `MARK_SENT`* (plan 1384-1414), in order under the lock:
    1. RESOLVED → `resolved`;
    2. ABORT_REQUESTED → `abort_requested`;
    3. `v_late` is computed once, after `runs ... FOR UPDATE`;
    4. a SENT attempt gets `cancelled`, else `expired`, else `not_redispatchable` when
       `v_handle.job_type = 'recover'`, else `already_sent`;
    5. INTENT goes through the EXECUTING guard, then `cancelled`, `expired`, and only then the SENT insert.

    No answer but `sent` writes a row. The unit test `test_mark_sent_sends_nothing_after_an_abort_request_...`
    pins this order and `body.count("INSERT INTO") == 1`.
  - *`execution.create_incident`* (3536-3580), as applied: after `stored` and `aborting`, both `send` and `resend`
    go through one `mark_sent` unit:
    - `resolved` → read back;
    - `abort_requested` → UNKNOWN, no POST;
    - `not_redispatchable` → `Refused("NOT_REDISPATCHABLE")` → a plain error (`refusal_error`, not retryable, no
      action id);
    - `cancelled`/`expired` → `_abort`;
    - any unknown answer → `PersistenceError` before any I/O.

    Only `sent`/`already_sent` reach `post`. No path POSTs on a SENT re-send after a cancel, past the deadline,
    after ABORT_REQUESTED, or for a recover handle. The one remaining window is between `mark_sent`'s commit and the
    POST; the plan now names it AM-13's own, at 911 and in the threat model.
  - *Tests:*
    - the unit cases `test_a_re_send_after_a_cancel_or_past_the_deadline_is_aborted_not_sent` (no `post_incident`
      in the call list), `test_a_due_re_send_goes_through_mark_sent_and_posts_the_same_action` and
      `test_a_recover_job_never_re_sends`;
    - the `NOT_REDISPATCHABLE` envelope case, which validates against `tool-result.schema.json`;
    - the live `test_a_re_send_is_checked_as_a_first_send_is`.
  - *Rewording:* erratum 84, Review Focus 1, the threat-model row, ARCHITECTURE §8 and the runbook now match what
    the code checks. Two exceptions remain, N1 and N3.
- **M1 (fixed).** The Expected line names both error classes, as pytest prints them.
- **M2 (fixed).** The greps moved to the end of Task 6 Step 4 and print nothing there.
- **M3 (fixed).** The walk follows the newest body of every reachable function, helpers included, across
  `REVISIONS`. A later revision adding `OC007` to any of them now fails the test. Two caveats, neither a finding:
  - the walk sees only `app.`-qualified calls, and every body uses that form today;
  - it checks 0002's file for `current_time` but not `tc_0001_test_clock`'s, which holds no `OC007`.
- **M4 (fixed).** "a recover handle of an APPROVED run (no grant) ... by the run-state rule" now appears in:
  - ruling 8;
  - the test docstring and comment;
  - the evidence line;
  - the matrix note;
  - STATUS and ARCHITECTURE;
  - the self-review.
- **M5 (fixed).** The rate-limit test takes `COUNTS` and `keys_total` after `recover_handle` and before the lookup,
  and asserts `after == before` and `keys + 1` after the abort. The order is right: the 429 committed no key, and
  `request_abort` and `record_outcome` touch only `action_attempt_state`.
- **M6 (fixed).** `row is None or row["reason"] is None` raises `PersistenceError("request_abort returned no
  reason")`, with a unit test.
- **M7 (fixed).**
  - `GUARD_0010` accepts SUCCEEDED/CONFLICT only from SENT or from ABORT_REQUESTED with reason `deadline`.
  - The derived-body test still undoes it to 0007's body byte for byte.
  - The live case in `test_a_cancel_comes_first...` expects `VersionConflict`: OC003, `outcome before SENT`, raised
    after the RESOLVED, validity and status checks.
  - Ruling 7 and errata 86 are reworded. See N1 and N4.
- **M8.** Folded into I1 (`not_redispatchable`).
- **M9 (fixed).** An owner-input line in SESSION_STATE.
- **M10 (fixed).** `COUNTS` is taken before `write_stack` and after the nine refusals.
- **M11 (fixed).** The downgrade docstring is reworded.

### The writer's open point

The open point: for a recover job's `create_incident` on a SENT attempt of a cancelled or overdue run, `mark_sent`
answers `cancelled`/`expired` before it would answer `not_redispatchable`. The tool therefore aborts instead of
refusing. I agree this is acceptable, and I think it is the better order:

- **It is reachable only through a race.** The Python allowlist refuses a recover job's `create_incident` on SENT
  up front. `mark_sent` meets SENT only when the attempt moved from INTENT to SENT between `resolve_invocation` and
  the grant replay.
- **Nothing more is sent either way.** `_abort` writes ABORT_REQUESTED and POSTs only the abort.
- **The abort is one the recover job may make anyway.** `request_abort` applies the same due-ness rule (SENT and
  cancelled or late → `deadline`) that `abort_incident` would, and `abort_incident` on SENT is a permitted recover
  action. The answer (FAILED_NO_COMMIT `aborted_no_commit`, the existing receipt as SUCCEEDED, or UNKNOWN) is a valid
  `create_incident` envelope.
- **It follows SA:248.** A cancel after SENT triggers an immediate abort. Refusing first would leave the abort to
  a later recover call.
- **The execute job gets the same answer.** It gets `cancelled`/`expired` → abort for the same state, so the two
  job types agree.

### Blocking

None.

### Important

None.

### Minor

**N1 — Two texts still describe the receipt-after-abort rule before the narrowing.**
- Where:
  - Task 6 Step 2's handoff note (plan 5049-5051): "record_outcome accepts a receipt or a conflict after
    ABORT_REQUESTED". It goes verbatim into `handoff/tasks.json` and `BUILD_BACKLOG.md`.
  - The Goal paragraph (17-18): "lets `record_outcome` accept a receipt after an abort request".
- Evidence: M7 narrowed the guard to ABORT_REQUESTED with reason `deadline`. Ruling 7, erratum 86 (both copies) and
  the revision docstring say so; these two texts do not.
- Fix: "...after an abort requested after SENT (reason `deadline`)" in both.

**N2 — `execution.py`'s module docstring still describes the abort rule for INTENT only.**
- Where: Task 3 Step 5, Edit 3's replacement text (3445-3450), and Edit 2's reflow (3427-3429).
- Evidence:
  - The "Abort rule" paragraph says that when `mark_sent` answers `cancelled` or `expired` "nothing was sent", and
    that the run "ends FAILED with `cancelled_before_send` or `expired`". Since I1 the same answers also come for a
    SENT re-send. That attempt was sent, and its abort ends with the destination's answer: `aborted_no_commit` or
    the existing receipt. The in-function comment (3570-3572) and the runbook (5434-5438) are already correct.
  - Edit 2 leaves a ragged line ("... idempotent key answers. There is never a second" / "action id for one run.").
    The CODE_COMMENTS standard asks for comments that match the code.
- Fix: add "for a SENT re-send, the immediate abort (`deadline`), whose answer decides" to the paragraph, and reflow
  Edit 2's lines.

**N3 — The owner-facing full errata 85 and 89 miss the round-1 additions.**
- Where: Task 6 Step 3's "Plan K executed" block, 5261-5263 (85) and 5274-5277 (89).
- Evidence:
  - The plan says that block is the full wording (around 293).
  - The summary erratum 85 (316-318) now covers "a first send and a re-send of a SENT attempt alike ... and
    `not_redispatchable` to a recover job's re-send". The full text still describes only the first send.
  - Departure (g) now lists `NOT_REDISPATCHABLE` among the plain errors after a grant. Full erratum 89 (and the
    summary 89 at 323-324) does not.
- Fix: copy the summary's clause into full 85, and add "a recover job's re-send of a SENT attempt is the plain
  `NOT_REDISPATCHABLE`" to both copies of 89.

**N4 — The narrowed guard fails open on a NULL reason.**
- Where: `GUARD_0010` (1303-1308).
- Evidence: `... AND v_latest.state <> 'SENT' AND NOT (v_latest.state = 'ABORT_REQUESTED' AND
  v_latest.detail->>'reason' = 'deadline')`. For an ABORT_REQUESTED row whose `detail` or reason is NULL, the inner
  conjunction is NULL. `NOT NULL` is NULL, the whole condition is NULL, `IF NULL` is not taken, and a receipt would
  be accepted. Only `request_abort` writes that state, and always with a reason, so this is unreachable. But the
  guard is meant as a SQL backstop, and a backstop should fail closed.
- Fix: `v_latest.detail->>'reason' IS NOT DISTINCT FROM 'deadline'` (or `coalesce(..., '') = 'deadline'`). The
  derived-body unit test still holds, because `GUARD_0010` is a constant it undoes.

### Checked and found sound

- **Lock order and clock.** In `mark_sent`, `_resolve_handle` takes `run_lease` FOR SHARE, then `execution_grant`
  is read, then `runs` FOR UPDATE, then `_latest_attempt`. `app.current_time()` is read once into `v_late`, after
  the runs lock, and both the SENT branch and the INTENT branch use it. `request_abort` and `record_outcome` are
  unchanged apart from the guard.
- **The SENT branch's position.** It sits before the EXECUTING guard, and nothing reaches it that should not:
  - an execute re-send on a run moved by `mark_unknown` is already refused by the fence bump in `_resolve_handle`;
  - a run escalated meanwhile is past the 300 s deadline, so it gets `expired` → abort, safer than round 1's
    unconditional re-POST.
- **Exact downgrade.** `RESTORED` is still 0007's `grant_execution`/`mark_sent`/`record_outcome` and 0004's
  `lookup_action` with `("mcp_exec",)`. `CREATED` drops all six, `REPLACED` the four old signatures. `FUNCTIONS`'
  callers are unchanged.
- **Envelopes and secrets.**
  - `NOT_REDISPATCHABLE` is a plain error, not retryable and without `data` or an action id; it validates against
    the regenerated schema.
  - The HandleRejected that `mark_sent` can now raise on a re-send comes before this call's destination I/O. It is
    the plain `INVALID_HANDLE`, like the grant replay's refusal that already preceded it; erratum 59's exception
    concerns a refusal after this call sent.
  - The new tests hold no token or raw handle in an assert operand.
- **Existing live tests.**
  - `test_write_path_twice`: the second call is the stored branch.
  - `test_concurrent_calls_share_one_attempt`: a re-send now gets `already_sent` from `mark_sent` for an execute
    handle that is not cancelled or late, the same POST as before.
  - The worker fakes ignore `mark_sent`'s return.
  - The fence tests fail at `grant_execution`/`mark_sent` on a first send, unchanged.
  - Task 4's `test_the_executing_re_send_returns_the_same_action`: `already_sent` → one `post_incident`;
    `mark_sent` is not a destination call.
- **New live cases (static).**
  - `test_a_re_send_is_checked_as_a_first_send_is` takes its handles in this order:
    1. the `approved_run` handle;
    2. a recover handle at the live 120 s lease's fence;
    3. after the 400 s move, a fresh 600 s lease and handle.

    The clock is reset in `finally`. Its event check (`[-2:] == ["action.granted", "action.dispatched"]`) holds,
    because no refusal appends an event.
  - The M7 case refuses on the guard before any write.
  - `fence_of` and `recover_handle` moved to Task 2's module with their imports (`ALPHA`, `Server`, `uuid4`). Task 4
    imports them, and Task 5 still gets `recover_handle` through Task 4's module.
  - Live arithmetic: 1232, 1251, 1300, 1310, 1311 = dev passed + (dev skipped − 21).
- **Bookkeeping.**
  - Errata 84 and 86 (both copies) match the controller's rulings.
  - "Round 1 changes" and "Round 1 open points" are appended and accurate.
  - PROJECT_HISTORY §28 gains the review round's problem and change, per the history standard.

## Controller rulings

# Plan K review, round 2 — controller rulings

Input: `round2-static.md` (ACCEPT: 0 Blocking, 0 Important, 4 Minor; I1 closed in the code, M1–M11 fixed as ruled, no
new defect; every splice, dev count and changed red step re-verified on a fresh tree).

- **The writer's open point — CONFIRMED.** For a recover job that meets a SENT attempt of a cancelled or expired run,
  `mark_sent` answers `cancelled`/`expired` (→ abort with reason `deadline`, no POST) before `not_redispatchable`. It
  arises only when the attempt turned SENT after the allowlist check; the abort is the one `abort_incident` would make
  under the same rule, and it matches SA:248's immediate abort.
- **N1–N4 — ACCEPTED as proposed** and folded in without a third round: the narrowed receipt-after-abort rule in the
  Task 6 handoff note and the Goal; `execution.py`'s abort-rule docstring covers the SENT case; errata 85 and 89 gain
  `not_redispatchable` / `NOT_REDISPATCHABLE`; the guard compares `IS NOT DISTINCT FROM 'deadline'` so a NULL reason is
  refused.

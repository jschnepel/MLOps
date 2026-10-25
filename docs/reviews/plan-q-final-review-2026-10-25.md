# Plan Q final review record — T20 the LangGraph workflow

Plan: `docs/superpowers/plans/2026-10-25-first-slice-q-langgraph-workflow.md` (branch `plan-q` from `plan-p` c96d13c,
PR #15; plan 2e2666a, round 1 fixes cfd37fe, plan review record d3c148a). Building tasks SPAN_BASE..SPAN_HEAD;
close-out after. The plan-stage record is `docs/reviews/plan-review-q-2026-10-25.md`.

What T20 delivers: a run's lifecycle as one LangGraph graph in the worker (`ops_worker.graph`: SA:207's ten nodes),
with `route_request`'s conditional edges generated from `GRAPH_ROUTES` in `core/routing.py` (SA:377's seven dimensions,
reread from the database on every hop); `durability="sync"` on every invocation and every announced checkpoint confirmed
by `aget_tuple` before its id is stored in `runs.checkpoint_id` under the lease fence; LangGraph's `AsyncPostgresSaver`
in schema `checkpoints` (revision 0015, worker DML only, the saver's DDL frozen inside the migration) on the worker's
fourth connection; graph state of ids, enums and verdicts only (SA:496) with the validated draft held in process memory
between nodes; the two waits as ID-only interrupts (the clarification's `clarification.requested` event id, the
reviewer's proposal id) after which the lease is released; the `resume_input` job resuming with the API's
`clarification.received` event id (verified: the newest answer to the newest question; two rounds, the third ends
INSUFFICIENT_EVIDENCE) and the `execute` job resuming with the decision's event id (verified: an approval of the active
proposal); any `answer` ending ANSWERED with the cited answer in `explanation.ready` (DEV-002); retrieval of the asset
status, the interval's alerts and the procedures before drafting, with SA:377's sufficiency rule; crash recovery forking
from the stored checkpoint with the stray head ignored; the execute job's nodes wrapping Plan K's code unchanged; and the
live run on the Postgres saver recorded in `reports/graph/t20-graph-live.md`.

Final gates: dev `1738 passed, 227 skipped`; live (`--profile test`) `1944 passed, 21 skipped`; `verify_handoff.py` exit 0 (1944 = 1738 + 227 − 21)

Holdout custody: no agent opened holdout case material or a seal. None exists in the tree. No agent connected to the
dev database (it stays at 0013; the worker now needs revisions 0014 and 0015), Keycloak or any service beyond local
Ollama (read-only tags/version for the start-up check; the graph live tests use the fake route). No agent opened
`.env` or a secret.

---

# Execution facts (controller's record)

## Plan Q execution facts (controller's record, for the close-out)

### Before the plan

- Plan P (T19) closed 2026-10-25 UTC: PR #15 `plan-p` -> `main` open. `plan-q` branched from `plan-p` c96d13c.
- The owner's standing instruction: build autonomously until set up; the controller's owner decisions are provisional.

### Plan stage

- Fact sheet 6466b8c (17 open questions). Custody slip: the fact-sheet writer ran seven greps scoped by directory or
  extension without the `*holdout*`/`*seal*`/`*.sha256` exclusions; no holdout or seal path produced output and nothing
  was opened (no holdout material exists in the tree). Recorded in the sheet's header and here.
- Facts the sheet surfaced that shaped the rulings: no graph route table exists (`GraphRoute` is an enum only); the
  LangGraph packages are not locked; no `checkpoints` schema exists while `runs.checkpoint_id` (text) does; the worker
  cannot insert `messages`; `run_manifests` keys on `run_id` alone; `build_proposal` hard-codes `revision=1`; no
  clarification-round counter exists; the sweeper has no AWAITING_INPUT wake-up; the fake route always drafts a
  proposal; DEV-002 expects ANSWERED for an `investigate` prompt; `migrator` is NOLOGIN.
- Brief with 17 rulings (scratchpad/planq/brief.md); errata planned 122-126.
- Plan written as 2e2666a (5951 lines), commit alone, not pushed by the writer. Writer's build in scratch worktrees
  of 6466b8c: dev 1629/222 → 1717/226 across Tasks 1-5, verify_handoff 0 after every task, a second tree rebuilt
  from the plan's blocks byte-identical; live gate NOT run (`.env` copy refused again) so live counts are arithmetic
  (1830 → 1922 passed, 21 skipped). `uv lock` added 7 packages (langgraph 1.2.14, langgraph-checkpoint 4.3.0,
  langgraph-checkpoint-postgres 3.1.2, langgraph-prebuilt 1.1.1, langgraph-sdk 0.4.9, ormsgpack 1.13.0, psycopg-pool
  3.3.3), removed none. Building found three design faults (manifest primary key on a clarified run; resume_input
  handle refused in RETRIEVING; recovery into a node whose in-memory draft was lost) — fixed in the plan.
- Twelve departures ruled (writer-departures-rulings.md): all accepted, several with critic checks; an unlisted
  thirteenth (the execute job resumes the reviewer wait with the decision's event id) accepted as the design. Errata
  now 122-129; next free 130.
- Critic round 1 dispatched (opus) with critic-brief.md at 2e2666a.
- Critic round 1 (opus): REVISE, 0 Critical, 2 Important, 7 Minor, 3 unsettled claims (live-only). Applied all 102
  plan blocks in a scratch worktree and reproduced the dev gate exactly (1717 passed, 226 skipped) — the first
  independent reproduction. I1: the router routed on dimensions read by `load_run` while nodes' early returns updated
  only `run_state`, so an approved run forked from a pre-freeze checkpoint hit `LookupError` for ever (reproduced with
  a scratch test). I2: R108's "persist synchronously" had only a kwarg spy; ruling 6's stub-node test was dropped
  without a departure. M1 the execute job's resume value unverified; M2 a REJECTED run's thread never reaches the
  table; M3 errata for SA:434 and SA:136 missing; M4 recovery after a completed draft can exceed BS:554/555; M5 five
  lines over 120 chars (ruff does not select E501); M6 0015 grants lack the REVOKE pattern (comment); M7 `asked`
  under-counts after a fork. Rulings in round1-rulings.md: everything fixed, nothing parked; erratum 130 added
  (SA:136), next free 131.
- Critic slip: one stray `uv run python -I - < /dev/null` typed into the real tree; it hung on stdin, was stopped,
  ran no code, changed nothing (tree clean, HEAD 2e2666a).
- Fix wave sent to the writer (one commit on plan-q, re-gate in a scratch worktree).
- Round 1 fixes cfd37fe (433/134, plan 6250 lines) checked hunk by hunk (controller-check.md): accepted. Review
  record docs/reviews/plan-review-q-2026-10-25.md (552 lines) committed as d3c148a and pushed. SDD workspace, ledger
  and pre-flight scan (clean) in place. Execution starts at d3c148a.

### Execution

- Task 1 (3139e63 debt list, 61b72af pins + `uv lock`): baselines dev 1629/222, live 1830/21, handoff 0 at d3c148a;
  `uv lock` added the seven packages as planned. Review (sonnet): clean.
- Task 2 (60824b7): RED 2 collection errors, GREEN 105 targeted, dev 1667/222, handoff 0; every anchor matched. Review
  (opus): spec compliant, 0/0/5 Minor — M1 attempt-state subquery order (granted_at first), M3 an assert that cannot
  fail, M5 `type` shadows the builtin → final fix wave; M2 second grant renderer and M4 one witness per row → parked.
- Task 3 (e99e6af): RED 2 collection errors, GREEN 8, dev 1672/222, handoff 0; edits 16-31 matched; prompts and
  PROMPT_VERSION untouched. Review (opus) dispatched.
  Review (opus): spec compliant, 0/0/6 Minor, all six → final fix wave (the plan-mandated retry classification treated
  every non-401 failure as transient against BS:552; alert sort key; wording; a comment; the fake-answer test should run
  `validate`). Task 4 (the graph) dispatched at e99e6af.
- Task 4 (f740e3d): RED 2 collection errors (no module ops_worker.graph), GREEN 600/2 focused, dev 1721/222, handoff 0,
  TODO(T20) grep empty; brief applied verbatim; the worker now refuses to start without checkpoints.checkpoints (dev
  start blocked until the owner migrates 0014+0015, the intended guard). Review (opus) dispatched.
  Review (opus): spec compliant, quality Needs fixes, 0/1/6. I1 (plan-mandated, reproduced with a probe): an execute
  job re-sent after a final grant refusal resumed the terminal checkpoint with `None`, LangGraph ran no node, and the
  run stayed APPROVED — the sweeper's re-dispatch promise (Plan M) was broken by the plan's own handler text. Ruled:
  the spec wins; a stored snapshot with no `next` starts a new graph run. M1 a non-execute job could reach the execute
  node in a millisecond race (allowlist refusal, then I1; `Requeue` escaped `handle`); M2 the lease lapsed instead of
  being released on failures outside RETRIEVING/DRAFTING; M3 a constant message fake; M4 two untested refusal branches;
  M5 an overclaiming test name and a tautological equality; M6 `Deps.saver` defaulted to the in-memory saver. All seven
  → Task 4 fix round 1 (same implementer). Tasks 5-6's expected dev counts shift by the tests the round adds.
- Task 4 fix round 1 (969e378, 11 files, +198/-31): RED 3 failed, GREEN 606/2 focused, dev 1727/222 (+6 tests), handoff
  0. Implementer concerns: `handle` now closes the job on an unexpected failure; two live test files gained
  `saver=InMemorySaver()` unrun. Scoped re-review (opus) dispatched with both points as questions.
- Re-review 1 (opus): six fixes as ruled; R1 Important — finishing the job on an unexpected failure stranded
  AWAITING_INPUT (the API refuses a second reply), EXECUTING and mid-run runs that lease reclaim used to retry; R2
  three stale comments; R3 a spurious second LeaseLost at ERROR. Task 5 anchors intact. Ruled: release the lease and
  re-queue the job (bounded by max_attempts). Fix round 2 → same implementer.
- Task 4 fix round 2 (bfab3a1, 3 files, +77/-15): RED 3 failed, GREEN 608/2 focused, dev 1729/222 (+2), handoff 0.
  The implementer corrected the ruling: `requeue_job` is unbounded until T22 (as the execute re-queue today);
  recorded as debt. Re-review 2 (sonnet) dispatched. Expected counts from here: Task 5 dev 1729/227, live 1935/21.
- Re-review 2 (sonnet): R1-R3 fixed as ruled; N1 (122-char line) and N2 (INFO line unasserted) → final fix wave.
  Task 4 complete at bfab3a1. Task 5 (first live run) dispatched; expected dev 1729/227, live 1935/21.
- Task 5, first live run (the plan's first): dev 1729/227 after Step 1; live RED 2 failed / 1933 passed / 21 skipped
  (7m14s), both failures in the new module and both harness facts: LangGraph numbers `__start__`'s superstep 0 so the
  first node's checkpoint is step 1 (the R108 values were already stored, the claim held); the R042 restart test passed
  every assertion and failed in cleanup because `record_reply`'s second message tripped the conversation FK in
  `purge_run`. Nothing was edited to pass. Settled by the run: the `%%` LIKE pattern, the api role's error text, the
  5 s confirm ceiling (not breached), A17 via the existing walking-skeleton test. Ruled: expect step 1; clean up via
  the conversation, test-side. Second live run requested.
- Task 5 (8c0e65f): second live run GREEN 1935 passed, 21 skipped (7m12s); dev 1729/227; handoff 0. Test-side changes
  only: the R108 stub asserts step 1 (LangGraph numbers `__start__`'s superstep 0); `forget` deletes the checkpoint
  rows then `purge_conversation`; `purge_run` and the worker untouched. `reports/graph/t20-graph-live.md` committed
  with five lines: R108 stub, R122 refusals (api, sweeper, mcp_read; versions 0-9 recorded), the proposal path's node
  order ending AWAITING_APPROVAL with the lease released, the clarification across a restart (QUEUED → RETRIEVING →
  DRAFTING → AWAITING_INPUT → QUEUED → RETRIEVING → DRAFTING → AWAITING_APPROVAL), the answer_only path ending
  ANSWERED cited with no proposal. Review (opus) dispatched.
  Review (opus): spec compliant, 0/1/6. I1 plan-mandated: the brief's `git checkout -- reports` left two committed
  evidence reports (R088's heartbeat, R105's walking skeleton) describing pre-T20 behaviour → Task 6 commits them from
  its final live run. M1-M6 → final fix wave (validated by Task 6's live gate). Task 5 complete at 8c0e65f.

### Final review
- Whole-branch review (opus) dispatched over d3c148a..8c0e65f (8 commits).
- Final review (opus): ready with fixes, 0 Critical / 2 Important / 5 Minor; neither Important was found by a task
  review (a re-run resume_input job taking a stale reply; the six-call read cap checked only before retries). Rulings:
  all fixed in one wave with the fifteen task-review items; nothing parked. Fix wave dispatched at 8c0e65f.
- Fix wave (a6ffbe2): dev 1738/227 (+9 tests), handoff 0; five behaviour tests RED→GREEN; three test-only items
  mutation-checked. Implementer slip: a bare `python -` with an empty heredoc (hung on stdin, stopped, nothing ran) —
  the same slip as Plan P Task 1. Concern raised by the implementer on its own T3-M1 fix (first-error rule vs a 4xx on
  a side request) → re-review. Live-test edits first run in Task 6.
- Fix-wave re-review (opus): all 22 addressed, nothing open; T3-M1 variation acceptable (no GET/initialize/DELETE
  against stateless mcp-read); residuals to record: HEADER_MISMATCH recovery then a connection failure would not be
  retried (impossible against mcp-read today); a failed node's `repr(exc)` lands in `checkpoint_writes`. Task 6
  dispatched at a6ffbe2.
- Task 6 (f3aef87, 13 files, +264/-79): records script OK (T20 DONE with its review note; M07 DONE; current milestone
  M08; eight matrix rows; span d3c148a..a6ffbe2); SESSION_STATE "Plan Q executed" with errata 122-130 and the three
  new debt lines; STATUS, README, ARCHITECTURE §3, history §35 (§36 "What the process taught"); the mcp.py comment;
  three reports committed refreshed (the heartbeat re-run line now "resumed the run from its stored checkpoint"; the
  walking skeleton's three read pairs; the graph report as the run wrote it). Final gates: dev `1738 passed, 227
  skipped`; live `1944 passed, 21 skipped` (7m17s) — the fix wave's live-test edits passed on their first run;
  verify_handoff 0. R088's matrix note needed no change. Review (sonnet) dispatched.

### Gates at close-out
- Dev 1738 passed, 227 skipped; live 1944 passed, 21 skipped; verify_handoff exit 0. Arithmetic: 1738 + 227 − 21 =
  1944. The plan predicted 1721/227 and 1927/21; the seventeen extra dev tests are the review rounds' (Task 4 fix
  rounds +6 and +2, the fix wave +9); dev skipped 227 = 222 + the five live tests of `test_graph_live.py`.
- Task 6 review (sonnet): spec compliant, approved, 0/0/6 (cosmetic/plan drift). Records agree; no placeholders;
  19 checkboxes ticked; refreshed reports match the tests; no claim exceeds the live run.

---

# Final whole-branch review (opus)

## Plan Q final whole-branch review: T20, the LangGraph workflow (d3c148a..8c0e65f)

Reviewer: final whole-branch review (opus), read-only. Branch `plan-q`, HEAD 8c0e65f, tree clean before and after.
Inputs read: the brief, the plan (departures, round 1, global constraints, rulings, the debt list, each task's
requirements), the ledger, all task reviews, re-reviews and reports, `closeout-additions.md`, the full diff, the spec
lines the plan cites (SA:135-137, 147, 153, 201-218, 362, 377, 419-423, 434, 451-453, 496, 501, 559-563, 580-581;
BS:305, 330-342, 419-423, 551-556, 562), and the installed langgraph 1.2.14 / langgraph-checkpoint 4.3.0 sources where
a claim depends on them.

Checks run:
- Focused unit runs, one file at a time: `test_graph_flow` 29 passed, `test_graph_routes` 28, `test_graph_table` 30,
  `test_evidence` 5, `test_migration_0015` 3.
- `ruff check` and `ruff format --check` (both read-only, `--no-cache`) on the 40 changed `.py` files: clean.
- Hygiene greps: one added line over 120 characters (`handlers.py:222`, already N1); no CR, no BOM, no attribution
  trailer in the eight commit messages; every new `TODO(` names T21, T22 or T25.
- `uv.lock` adds exactly the seven declared packages and removes none.
- Two probes, written as a pytest file in the scratchpad (`scratchpad/planq/final/test_final_probe.py`) on
  `test_graph_flow`'s fakes. Both fail on HEAD, reproducing I1 and I2 below.
- Not run: the full gates. I take the controller's dev `1729 passed, 227 skipped`, live `1935 passed, 21 skipped` and
  `verify_handoff` 0 as given.

### Verdict

**Ready with fixes.** 0 Critical, 2 Important, 5 Minor.

The design holds end to end on every boundary the brief names. Graph state and interrupts carry ids only. The router
rereads its dimensions on every hop. The freeze is gated three times. Resume values are checked against the database.
The lease is released after every wait and end. The saver is on its own connection behind revision 0015.

Both Important findings are small code fixes, each with a test:
- I1: a re-run `resume_input` job fails a run that is waiting on a newer question.
- I2: the read budget can be overrun by one call.

Neither was found by a task review. Neither is in `closeout-additions.md`.

### Findings

#### Critical

None.

#### Important

**I1. A `resume_input` job that runs again after its own graph run asked a second question fails the run, which was
legitimately waiting.**

Where:
- `worker/src/ops_worker/handlers.py:134-155` (`resume_input`);
- `worker/src/ops_worker/graph/nodes.py:453-468` (the node's check).

The sequence:
1. Q1 is asked, and reply 1 queues job J1 (key `run_id:Q1`).
2. J1 resumes the graph, which retrieves, drafts again and asks Q2. The run is AWAITING_INPUT on Q2.
3. J1 then runs again: it is handed back, or re-queued.
4. Because the run is AWAITING_INPUT, `resume_input` takes the newest reply whose `question_id` is Q1 (reply 1) and
   resumes with it.
5. The node compares reply 1 with the newest question, Q2, finds that it does not answer Q2, and calls `fail_from` →
   FAILED with RESUME_REFUSED.

The requester can no longer save the run. `store.check_reply_question` (`api/src/ops_api/store.py:242-251`) answers 409
to a reply on the superseded Q1, and the run is now FAILED anyway.

Reachable triggers, all after Q2's AWAITING_INPUT commit:
- the final `release_lease` finds the lease lost → `abandon` → J1 is claimed again;
- the final release raises a transient error → J1 stays claimed → reclaim;
- the unfenced `run_events` read before `interrupt`, or the saver's write of the interrupt, raises → `_drive` re-raises
  (the run is AWAITING_INPUT, not mid-run) → `handle` re-queues J1 (fix round 2).

Fix round 2's re-queue on every unexpected failure makes the last path routine.

By contrast, `investigate` is safe here: `_carry_on` logs "run already AWAITING_INPUT" and does nothing.

Evidence: probe `test_probe_stale_resume_job_after_a_second_question`. It does Q1 → reply → J1 asks Q2 → J1 runs
again. The run ends `FAILED`, where `AWAITING_INPUT` was expected.

Gaps:
- No committed test covers a re-run after a second question.
- The node's `reply[1].get("question_id") == question` term (`nodes.py:464`) is not exercised by any test. Every
  refusal test also fails the "newest reply" term first.

Fix:
- In `resume_input`, when the run is AWAITING_INPUT, compare the job's question (`dedup_key`) with the newest
  `clarification.requested`. If they differ, the job is stale: log it and end the job without a graph run and without
  a transition. The newer question's reply queues its own job, and the node's check stays the backstop.
- Add the probe as a test: the run stays AWAITING_INPUT, `store_checkpoint_id` is not called, and the job is
  finished.
- A one-line note in erratum 127 or 129 (both are about `resume_input`).

**I2. The read budget allows a seventh read call (BS:552: "at most 6 calls including retries").**

Where: `worker/src/ops_worker/graph/nodes.py:188-210` (`read`). `calls[0] -= 1` runs before every attempt, but the
budget is checked only on the retry branch (`:204`), so a first attempt is never refused.

Example: status fails twice then answers (3 calls), alerts fail twice then answer (3 calls, budget now 0), and the
search is then still called. That is 7 calls.

Evidence:
- Probe `test_probe_read_budget` records `get_asset_status`×3, `get_recent_alerts`×3, `search_procedures`×1, and the
  run reaches AWAITING_APPROVAL.
- The plan (ruling 3: "two retries within a six-call budget") and the debt list ("retried at most twice inside the
  retrieval node (BS:552)") both claim the bound.
- `test_reads_retry_transient_failures_only` only spends the budget on one tool, so it cannot catch this.

Fix:
- Refuse before the call when `calls[0] <= 0` (raise `McpCallFailed(code=TRANSPORT)`, so the run fails with
  RETRIEVAL_FAILED as for spent retries).
- Add one parametrized case where two reads each fail twice and the search is never called.

#### Minor

**M1. No test fails if `confirm` (the `aget_tuple` before each store) or the `workflow_version` checkpoint metadata
is deleted.**

Where: `worker/src/ops_worker/graph/build.py:139-148, :189` and `:130`.

- `InMemorySaver` writes synchronously, so removing `await confirm(...)` passes every unit test. The live run cannot
  show the race either.
- `CheckpointNotStored` is never raised by any test.
- Nothing reads `metadata["workflow_version"]`, which is ruling 13's only pin for BS:342.

Both are named T20 obligations: tasks.json T20 review note 2 ("store only checkpoint IDs confirmed by aget_tuple"),
and ruling 13.

Fix:
- A unit test with a saver wrapper whose `aget_tuple` returns None for the first N polls: assert the store waits. With
  `CONFIRM_TRIES` patched low, assert `CheckpointNotStored` and no `store_checkpoint_id`.
- Assert `workflow_version` in `snapshot(...).metadata` in an existing test.

**M2. `publish_state`'s second exit and its lost-hold branches are untested.**

Where: `build.py:91-94` (`after_publish`) and `nodes.py:499-501, 518-520`.

How the branch is reached: the lease is lost inside `publish_state`'s fenced unit, so the stored checkpoint's next node
is `publish_state`. The fork then has no hold:
- For an answer, the node returns LOST and `after_publish` must send the run back to the router.
- Mutate `after_publish` to always return END and every test still passes. The run would then be left DRAFTING with
  its job finished, so neither reclaim nor the sweeper would ever wake it.
- A lost abstention ends INSUFFICIENT_EVIDENCE with no `drafts` row (the comment says so). Nothing tests that branch
  either.

Fix: one `lose_once_after(..., "explanation.ready"/"insert")`-style test per branch.

**M3. Comments that no longer describe the code (CODE_COMMENTS).**

- `worker/src/ops_worker/main.py:157-158`: a 55P03 "job keeps the claim until the lease lapses and the sweeper
  reclaims it". Since fix round 2, `handle` releases the lease and re-queues the job.
- `worker/src/ops_worker/main.py:206-207`: under SIGTERM "an investigate run is failed as interrupted". A mid-run
  investigate with a stored checkpoint is now resumed from it; it fails INTERRUPTED only when no checkpoint was stored.
- `mcp-read/src/ops_mcp_read/assets.py:7-8`: "fails the run on any other failed read". A 404 (`AssetMissing` →
  NOT_FOUND) ends INSUFFICIENT_EVIDENCE as "context missing", not FAILED.
- `core/src/ops_core/locking.py:99-100`: "a key share on the run row the same unit's `transition_run` already holds".
  In `await_clarification`'s DRAFTING branch (`nodes.py:423-437`), the `drafts` insert takes the key share before any
  run lock, and `transition_run`'s FOR UPDATE comes after it.
  - The documented order still holds (it is the same entry, an upgrade on a row the unit already holds), so this is
    wording only.
  - The other alternative, `run_row(lock=True)` first as `publish_state` and the freeze do, also re-checks DRAFTING
    under the lock.

**M4. `closeout-additions.md` files fix-wave items under "Parked (recorded, no change)".**

- Its "Parked" heading covers Task 2 M2/M4, and also Task 3 M1-M6, Task 4 N1/N2 and Task 5 M1-M6.
- The ledger (`progress.md`, Tasks 3-5) sends all of those except Task 2 M2/M4 to the final fix wave.
- A fix-wave implementer reading the file literally would skip fourteen items. Move them under "Carried".

**M5. Task 5 M1's ruling is narrower than the record it affects.**

- The ruling only narrows the R108 stub's docstring.
- The committed `reports/graph/t20-graph-live.md:3` line ("… already in the Postgres saver (durability=sync)") and any
  R108 matrix note Task 6 writes must make the same distinction. The stub shows the stored values under the real saver
  and wiring.
- `durability="sync"` itself is evidenced by the unit spy (`test_graph_flow.py:176-196`), not by the live stub, whose
  sensitivity to `"async"` is unproven.
- Task 6 should word R108's "which test evidences what" note accordingly.

### On `closeout-additions.md`'s rulings

- **Agree with every ruling.**
- **Fix round 2's re-queue on any unexpected failure.** Agreed, but it turns I1's stale re-run from a lease-loss edge
  case into a routine path. I1's fix belongs in the same fix wave.
- **Task 3 M1.** Treating other 4xx as non-retryable needs `transport_failure` to look at the recorded statuses for
  4xx as it does for 401, and that list also holds the discovery call's responses. The test should cover a 4xx on the
  call itself.
- **Not re-reported here:** Task 2 M1/M3/M5, Task 3 M1-M6, Task 4 N1/N2, Task 5 I1, M1-M6, and fix round 2's T22 debt
  line.

### Verified clean (the brief's seven areas)

1. **Seams.**
   - `edge_map()` is generated from `GRAPH_ROUTES`. The compiled branch equals the table, and every `GraphRoute` has
     an edge.
   - `ROUTE_NODES` gives one node per route. `after_publish` reads the same table.
   - `graph_facts` feeds `route_request` on every hop.
   - Revision 0015's grants equal `privileges.CHECKPOINT_GRANTS`.
   - `JOB_RULES[RESUME_INPUT]` gained RETRIEVING/DRAFTING. mcp-read's check is `persistence.allowed_tool` over the same
     `JOB_RULES` (no SQL copy), so the two cannot drift.
   - No loop-connection transaction spans a saver call. The store unit opens only after `confirm`; `known`,
     `interrupted` and `ended` run outside units; every `interrupt()` is outside a unit.
2. **Authority.**
   - State keys are ids, enums and verdicts. Interrupts carry the question's event id and the proposal id. Resume
     values are event ids.
   - The model's request carries no tool, role, approval or handle.
   - The freeze is gated by the table row (`intent=INVESTIGATE`), by `freeze_allowed`, and by `freeze_proposal`'s own
     refusal.
   - The worker inserts no `messages`. The question and the answer travel only in `clarification.requested` and
     `explanation.ready` (erratum 124).
   - `_approval` checks the newest `approval.recorded` against the active proposal, with no `run.rejected`.
   - The execute node rereads APPROVED or EXECUTING under lock and refuses any job type but `execute`.
   - The schema is worker DML only, and `checkpoint_migrations` gets no grant.
3. **Recovery.**
   - Fork with `None` from the stored id. The stray-head test and the two-crashes test both pass, with
     `source: fork` asserted.
   - The lost hold returns through retrieval (debt → T29, BS:554/555 named).
   - A lost lease at the store keeps the previous id.
   - The round 1 I1 test passes: an approved run forked from before its freeze still executes.
   - The interrupt's pending write sits on the checkpoint stored before the waiting node. A probe confirmed that no
     new checkpoint follows an interrupt, which matches SA:211's "the stored ID is the checkpoint holding the
     interrupt's pending write".
4. **Durability.**
   - `durability="sync"` and `stream_mode="checkpoints"` are on the only invocation.
   - `open_saver` gives an autocommit, dict-row connection with `prepare_threshold=0` and
     `search_path=checkpoints,pg_temp`, and no pool.
   - The frozen DDL equals `BasePostgresSaver.MIGRATIONS` minus the schema prefix and `CONCURRENTLY`, statement for
     statement.
   - `_main` asserts `checkpoints.checkpoints` before opening the saver.
5. **Tests.**
   - The R129 walk drives a compiled graph to a stubbed node with the real `route_request`.
   - The mutations named in the task reviews hold.
   - The new gaps are I1, I2, M1 and M2.
6. **Records.**
   - Errata 122-128 are cited consistently with the plan's list (129 and 130 are not cited in code, which is fine).
   - The debt list names every new `TODO(`. The unbounded re-queue line is pending (closeout).
7. **Hygiene.** As listed under "Checks run".

### Residual risks to record

- **Text in error writes (R091).** LangGraph persists a failed node's exception as an `ERROR` pending write, as
  `repr(exc)` (`pregel/_runner.py:597-604`; `checkpoint/serde/jsonplus.py:553-554`). R091 therefore holds only while
  no exception message carries text, and no test greps the saver after a node failure.
  - Today's exceptions are templated, or are psycopg errors of functions that raise fixed messages.
  - A future exception message carrying a question, answer or excerpt would land in `checkpoint_writes`.
- **The payload changed shape under an unchanged prompt version.** `RunManifest.prompt_version` still says
  `incident-draft-v2` while the user message now carries uncitable observation entries and, for answer_only, an
  appended line. The manifest cannot tell a T19-shaped payload from a T20-shaped one. The debt line covers the T19
  figures (→ T25), but not the manifest's identity.
- **Retries never stop before T22.** A failure that cannot clear in a state `_drive` does not fail (for example a
  `LookupError` on an unexpected key, or a bug) re-queues the job every 30 s for ever. This is the T22 debt line from
  the closeout.
- **A transient error mid-run fails the run.** A transient error inside a mid-run node or the saver (a 55P03 in the
  RETRIEVING → DRAFTING unit, a saver connection blip, `CheckpointNotStored`) fails a RETRIEVING or DRAFTING run
  instead of retrying it. Partly covered by the T30 saver debt.
- **Stale writers.** The stock saver is unfenced: a stale writer's checkpoints, pending writes and error writes become
  stray heads. They are ignored on resume, and one replica runs (T38, R021).
- **The real read server is not in these live tests.** The graph's live tests use `ScriptedMcp`, so the real
  mcp-read/asset-sim path under the graph runs only in the R105 walking skeleton. `confirm`'s 5 s ceiling is
  unmeasured.

---

# Controller rulings on the final review

## Plan Q — controller rulings on the final whole-branch review (`.superpowers/planq/final-review.md`, span d3c148a..8c0e65f)

Verdict accepted: ready with fixes, 0 Critical, 2 Important, 5 Minor. One fix wave (a fresh implementer, one commit),
then a scoped re-review, then the close-out. Nothing parked from this review.

- **I1 (a re-run `resume_input` job takes the old reply and fails the waiting run)** — fix as proposed: `resume_input`
  ends the job without a graph run when the job's reply does not answer the run's newest `clarification.requested`
  (the run stays AWAITING_INPUT for the newer question; the newer reply's own job resumes it). Log the ids. One unit
  test: the first job's graph asks a second question; the same job runs again; the run stays AWAITING_INPUT with no
  RESUME_REFUSED and the second reply resumes it.
- **I2 (`nodes.read` checks the six-call budget only before a retry)** — the budget is checked before every call,
  including the first of each read; the seventh call is refused with the retrieval-failed template (BS:552). One unit
  test: two reads failing twice each, then a third read — six calls made, the seventh refused.
- **M1 (`confirm` and `workflow_version` untested)** — both tests as proposed: a saver wrapper whose `aget_tuple`
  returns None for the first N polls (the store waits; with `CONFIRM_TRIES` patched low, `CheckpointNotStored` and no
  `store_checkpoint_id`), and `workflow_version` asserted in a snapshot's metadata in an existing test.
- **M2 (`publish_state`'s second exit and the lost-hold branches untested)** — one `lose_once_after`-style test per
  branch (the answer returns LOST and goes back to the router; the lost abstention ends INSUFFICIENT_EVIDENCE with no
  `drafts` row); the `after_publish → END` mutation must fail.
- **M3 (four stale comments)** — correct all four as the review words them (`main.py` 55P03 and SIGTERM paragraphs,
  `assets.py`'s 404 sentence, `locking.py`'s key-share sentence).
- **M4 (closeout-additions headings)** — the controller's file, restructured before the fix wave: everything except
  Task 2 M2/M4 is under "Carried".
- **M5 (the R108 distinction in the live report and the matrix note)** — the fix wave rewords the report line the
  live test writes ("step N's values were stored when step N+1 ran, on the Postgres saver under sync durability; the
  async race is not shown"), and Task 6's R108 note makes the same distinction.

Plus the fifteen task-review items in `closeout-additions.md` ("Carried"), all in the same wave. The live tests the
wave touches are validated by Task 6's live gate.

---

# Controller check of the fix wave (a6ffbe2) and the close-out (f3aef87)

The fix wave, 8c0e65f..a6ffbe2 (13 files, 344 insertions, 54 deletions), was re-reviewed item by item (opus,
`.superpowers/planq/fix-wave-rereview.md`): all twenty-two items addressed, nine mutation probes passing, nothing
open. Four named checks held: the stale-reply refusal runs before anything that can fail the run and cannot refuse the
newest legitimate reply (both sides derive the same canonical id); the read budget refuses exactly the seventh call
with the retrieval-failed template; the retry classification sees only the tools/list and tools/call POSTs because
mcp-read is stateless and the protocol version is pinned (the SDK's HEADER_MISMATCH recovery followed by a connection
failure is the one residual, impossible against mcp-read today, recorded as debt); the two live assertions that had
not run follow from the code. Dev after the wave: 1738 passed, 227 skipped (+9); verify_handoff 0.

The close-out (f3aef87): the records script ran clean (T20 DONE, M07 DONE, M08 current, the eight matrix rows, span d3c148a..a6ffbe2); SESSION_STATE, STATUS, README, ARCHITECTURE §3 and history §35/§36 updated; errata 122-130 recorded; the three debt lines added; the two stale evidence reports committed refreshed from the final live run, which was the first run of the fix wave's live-test edits (no failures); one comment corrected in `mcp.py`. The records review (sonnet) is reproduced below the rulings where it found anything.

Final gates: dev `1738 passed, 227 skipped`; live (`--profile test`) `1944 passed, 21 skipped`; `verify_handoff.py` exit 0 (1944 = 1738 + 227 − 21).

Accepted. The branch is ready for its pull request against `plan-p`.

Records review of the close-out (sonnet, `task-6-review.md`): spec compliant, approved, 0 Critical / 0 Important /
6 Minor — two gate lines over 120 characters in SESSION_STATE (prose, left), the plan file's embedded pre-fix strings
and counts (the plan is a historical record; its "Round 1 changes" and the review records carry the final figures),
the R122 note's bookkeeping-table exclusion (erratum 126 is cited), "next free erratum 131" stated nowhere (added with
the PR reference), this record untracked at review time (committed next), and the reviewer's own piped exit code.
Verified: every record agrees with the others and the measured counts; no placeholder survives; all 19 checkboxes
ticked; the refreshed reports match the tests; no claim exceeds the live run.

# Plan R review record — T21 decisions, revisions, manual proposals, feedback and the final grant

Plan: `docs/superpowers/plans/2026-10-25-first-slice-r-decisions-revisions-grant.md` (branch `plan-r`, from `plan-q`
84eaee5 which is PR #16; plan commit 47fb044, round 1 fixes e0a701b). Inputs:
`docs/superpowers/research/2026-10-25-plan-r-inputs.md` (20 open questions) and the controller's brief of 20 rulings
(reproduced below).

Context. Plan Q (T20) had just closed as PR #16 with the run's lifecycle in one LangGraph graph; the reviewer wait
resumed with the decision's event id, but the decision itself still trusted the API's unlocked pre-checks, no
revision, cancel, manual-proposal, feedback or search route existed, the author set was the requester alone, nothing
expired a proposal, and `grant_execution` checked neither expiry, nor the hash against the decision, nor source or
asset freshness, nor the asset guard. T21 makes the human decision and the final gate exact: per-revision proposals
on their own graph threads, first-decision-wins with independence over every content author, expiry to
BLOCKED_REVIEW (lazily and by a sweep), revisions from BLOCKED_REVIEW behind the conversation slot, the manual
proposal replacing a failed model draft, feedback with no runtime effect, cancellation before the grant, and the
grant as the authorization linearization point with committed refusals. The owner's standing instruction (build
autonomously until set up) applies; the controller's owner decisions are provisional (errata 131-145).

How the round ran. The writer built the slice in scratch worktrees of 3df1d23, replayed every block on a fresh tree
and gated each task, and — for the first time — ran the live gate before execution (2007 passed, 21 skipped at the
Task 6 tree). It reached the stack's `.env` through a hard link, which earlier plans' permission refusals had made
off limits; the secret was not opened or copied by the agent and the link is gone, but the controller records it as a
denied outcome reached another way, and every later dispatch forbids links to secrets. The writer listed fourteen
departures; the controller accepted all fourteen (uuid author sets; the revision number from `proposal.revised`
events; two manual-proposal definers; tenant and subject as definer arguments; the per-call mcp-write schema check;
the `manual` draft kind; the search route without an idempotency key; the asset lock before the lease fence; the live
fixture changes; R023's and R086's evidence shapes). One static round (lean process); the controller checked the fix
diff instead of running a second.

Round 1: REVISE, 0 Critical, 5 Important, 11 Minor, 3 claims unsettled until the first live run. The critic rebuilt the
plan from its text on a fresh tree (byte-identical to the writer's seven trees) and reproduced the dev gate. Everything was
fixed in e0a701b and nothing was parked:
- a revision committed while the previous revision's graph run was still running would have been destroyed (the old
  thread overwrote the cleared checkpoint id; the new revision ended FAILED) — the store and the router now raise
  `RevisionMoved` and the old graph run ends quietly; a stored id on an older thread starts a new graph run;
- the model-path freeze never bound the payload's asset and interval to the run's, which the asset guard assumes, and the
  live helpers depended on the gap — `PAYLOAD_RUN_MISMATCH`;
- the grant's committed verdicts (asset guard, expiry), the manual proposal's tenant scoping and five refusals had no
  behavioural test against PostgreSQL — live cases added.
Minor: the sweep's stale-revision job; a future asset stamp; a fixture race; the "derived" claim; erratum 146 and two
pointers; the requester role in the grant's authority check; four stale comments; membership stamps leaking after clock
moves; the history paragraph; the expiry sweep's tenant iteration; R113's table counts.
Dev counts after Tasks 1-6: 1738, 1764, 1780, 1789, 1800 and 1800 passed (227, 227, 227, 227, 227 and 239 skipped),
measured on scratch worktrees. Live: 2007 passed, 21 skipped measured at the round-0 Task 6 tree; 2018/21 arithmetic
after the fixes. verify_handoff exit 0 throughout.

Holdout custody: no agent opened holdout case material or a seal. None exists in the tree. The fact-sheet writer ran
four commands without the exclusions (nothing matched, nothing opened); recorded.

Process slips: the plan writer's `.env` hard link (above) and one `uv run python -I -c "pass"` (a no-op). No agent
connected to the dev database, Keycloak outside the test realm's own fixtures, or a service beyond the local stack
the live gate uses; none opened `.env` or a secret.

---

# Controller brief (rulings before round 1)

## Plan R brief — T21 (per-revision proposals, decisions, manual proposals, feedback, the final grant)

Repo `C:\Users\joeys\Desktop\MLOps`, branch `plan-r` at 3df1d23 (from `plan-q` 84eaee5 = PR #16; `plan-p` = PR #15 ->
`main`). Write ONE plan file `docs/superpowers/plans/2026-10-25-first-slice-r-decisions-revisions-grant.md` from the
fact sheet `docs/superpowers/research/2026-10-25-plan-r-inputs.md` (FS; 20 open questions) and the rulings below.
Model it on `docs/superpowers/plans/2026-10-25-first-slice-q-langgraph-workflow.md` (Plan Q: header, Departures,
Global Constraints, Rulings-as-implemented, Measured-before-writing, debt list, File structure, Task overview, tasks
with tests first, exact edits and expected outputs, a close-out task, Review Focus). The spec is `SPEC_AMENDMENTS.md`
over `BUILD_SPEC.md` (amendments win); the fact sheet cites lines. The owner's standing instruction is to build
autonomously; owner decisions the controller takes below are provisional and recorded as errata (from **131**).

### Rulings (one per FS §5 question)

1. **Revisions re-enter as a new graph thread.** A revision N starts a NEW thread `run_id:N` from QUEUED: the
   `investigate` job's dedup key is `run_id:revision` (SA:455 `run_id:revision+1`), the handler reads the revision from
   the job (closing Plan Q ruling 13's seam: the three `revision=1` call sites and `build.thread_id` take the job's
   revision; `build_proposal` takes it too). `create_revision` clears `runs.checkpoint_id` (so the investigate handler's
   existing "QUEUED with no stored id = new graph run" branch distinguishes a revision's QUEUED from a clarification's;
   a clarification keeps its id). One manifest per revision: `run_manifests` primary key becomes `(run_id, revision)`
   (revision 0016; `retrieve_evidence` skips the insert when the row for this revision exists; the api SELECT
   unchanged). Erratum 125 closes with this (record it).
2. **Who revises, and what a revision is.** Any active member holding the requester role in the tenant may revise a run
   of the tenant (the run's requester or another requester); the author is appended to the run's author set (ruling 4).
   A reviewer who also holds the requester role may revise, and is then barred from approving (DoD 1's
   "reviewer-authored revision"). A revision carries no text: `RevisionRequest {expected_version, supersedes_run_id}`
   (SA:455); asset and interval stay fixed (SA:154, BS:297). The Plan G parser blind spots are not a revision matter —
   re-home that debt to T34's limitations list (record; no code).
3. **The definer stays the one authority for decisions.** `record_decision` gains `expected_revision` so the revision,
   the hash, the active proposal, first-decision-wins and expiry are all checked under `runs FOR UPDATE` (erratum 131
   amends SA:454's signature); the API's unlocked pre-checks stay as early refusals only. Codes (409 unless noted):
   `ALREADY_DECIDED` (OC003; an opposing decision or a different key on a decided proposal; the body carries the
   recorded decision), `STALE_REVISION`, `STALE_HASH`, `EXPIRED` (after a committed BLOCKED_REVIEW, ruling 5); a
   non-independent reviewer stays 403 `SELF_REVIEW`, unrecorded (BS:301). A same-key replay returns the recorded result
   (Plan G). `decide_once`'s "every Conflict is stale" message is replaced by the code's own message.
4. **The author set lives on the run.** Revision 0016 adds `runs.authors text[] NOT NULL` set by `create_run` to
   `[requester]`, appended by `create_revision` and `create_manual_proposal` (distinct; a ninth distinct author → 409
   `AUTHOR_LIMIT`, since `Proposal.authored_by` caps at 8). `freeze_proposal` and `create_manual_proposal` write
   `proposals.authored_by = runs.authors` (SA:453/SA:539 win over SA:456's `[author]`: erratum 132). `record_decision`
   checks reviewer ∉ `authored_by` inside the transaction (closing the Plan D item).
5. **Expiry.** `expires_at` stays the worker's value inside the hashed payload (BS:256), but the worker computes it from
   `app.current_time()` read in its unit (not the wall clock) and the definers verify at freeze that
   `expires_at ∈ (current_time, current_time + 15 min + 60 s]`. `expire_proposal(run_id)` (SA:457) is a definer; the
   API's decision unit calls it in its OWN unit before the decision unit, so an expiry commits BLOCKED_REVIEW(`expired`)
   with `review.blocked` and the decision then refuses 409 `EXPIRED` (DEV-008 holds). `grant_execution` calls it
   internally and, for the committed refusal reasons (ruling 9), RETURNS a verdict row instead of raising, so its
   BLOCKED_REVIEW commits. The sweeper gains an `expire_proposals` maintenance routine per minute (like
   `sync_memberships`; dedup `name:<minute bucket>`; iterates tenants per SA:520; calls `expire_proposal` for every
   AWAITING_APPROVAL/APPROVED run whose active proposal is past; APPROVED runs expire before the grant, SA:140).
6. **The slot on revision.** `create_revision` checks the conversation's other active runs explicitly under `runs FOR
   UPDATE` (SLOT_OCCUPIED) and keeps the unique-violation catch by constraint name as a backstop, from BLOCKED_REVIEW;
   from AWAITING_APPROVAL/APPROVED the slot is already the run's (same code path, no refusal). Plan G's
   read-without-lock debt closes for the revision door; the clarification door stays recorded.
7. **Manual proposals replace a failed model draft for a run in DRAFTING.** `POST /api/v1/manual-proposals` takes
   `run_id` in the body (BS:281 has no path run; contract erratum 133 adds the field). Precondition: the run is DRAFTING
   with no stored checkpoint and no held lease — the state the worker now leaves on `ModelUnavailable` and on a draft
   that stays invalid after repair: the graph run ends with the run in DRAFTING, `checkpoint_id` cleared, the lease
   released, and a templated `explanation.ready {message: "The model is unavailable; a requester or reviewer may
   submit a manual proposal."}` (erratum 134: today's FAILED for those two cases becomes the manual path; DEV-025's
   `FAILED_WITH_MANUAL_PATH` reads as this; the sweeper does not re-arm DRAFTING). `create_manual_proposal(run_id,
   payload, author)` inserts its own `drafts` row (kind proposal, source `manual`) and then does what `freeze_proposal`
   does (ruling 4's authors, ruling 10's guard, expiry per ruling 5, `supersedes_run_id` injected from `runs`); the
   payload's asset must be the run's asset and its evidence ids must be chunks of the caller's tenant (checked in the
   definer; otherwise 404 with nothing written — note 4); `workflow_version` = the run's (ruling 18), `prompt_version`
   = `"manual"`. Author: an active requester or reviewer of the tenant, enabled check (SA:542). `POST /api/v1/search`
   (BS:280, R057) is built lean: bounded lexical search (query ≤ 500 chars, limit ≤ 10) through a new api-callable
   definer wrapping the same ranking as `search_procedures_scoped` (tenant from the session, no handle), returning
   evidence ids, text and versions; no vector mode in v1 (erratum 135).
8. **Feedback.** Revision 0016 adds `feedback (feedback_id uuid pk, tenant_id, run_id, subject_kind, subject_id,
   category, text ≤ 2000, author, created_at, reviewed bool default false)`, api INSERT/SELECT, RLS. Route
   `POST /api/v1/runs/{id}/feedback`: any active member of the tenant (requester, reviewer, reader); the subject must
   belong to the run (404 otherwise). Event `feedback.recorded` with payload `{subject_kind, subject_id, category}` —
   three keys added to `PAYLOAD_KEYS` for this type only (erratum 136, an event-schema change); the text goes in no
   event or log. `reviewed` is not settable through the API in v1. R113's evidence: a test that the route's unit
   writes only `feedback`, `events` and `outbox` rows and that `api` holds no new UPDATE grant.
9. **`grant_execution`'s new checks.** Committed refusals (the function returns a verdict, transitions APPROVED →
   BLOCKED_REVIEW with the reason, emits `review.blocked`): `expired`; `stale_evidence` (a cited source's document
   state is no longer approved/effective at `app.current_time()`, BS:425, or the asset observation is older than 5
   min, R116); `authority_revoked` (requester or reviewer `MEMBERSHIP_INACTIVE`); `asset_action_unresolved` /
   `asset_incident_exists` (ruling 10). Plain refusals (RAISE, nothing committed): `OTHER_PROPOSAL`, `PROPOSAL_NOT_IN_RUN`,
   `NOT_ACTIVE_APPROVED`, `NO_APPROVAL`, `HASH_MISMATCH`, `CANCELLED`, `MEMBERSHIP_STALE` (deferred). The asset
   observation: revision 0016 adds `runs.asset_observed_at` (worker UPDATE on the column), written by `retrieve_evidence`
   after the status read AND refreshed by the execute path: `execute_approved_proposal` re-reads the asset status
   through mcp-read before calling the grant (the execute job's read handle gains `get_asset_status` in `JOB_RULES`;
   erratum 137 against SA:343/344) so a normal approval window does not trip the 5-minute bound.
10. **The asset guard.** One SQL helper `_asset_guard(tenant, asset, start_at, end_at, run_id, supersedes_run_id)`
    (definer-internal, not granted) called by `freeze_proposal`, `create_manual_proposal` and `grant_execution` inside
    `pg_advisory_xact_lock(hashtextextended(tenant_id || ':' || asset_id, 0))` taken first (SA:189; the idempotency
    lock of the API unit precedes it in the API, erratum 37 — note 1's "first" is first among the definer's locks).
    Sets (a) and (b) exactly per SA:284-286; `supersedes_run_id` excuses only set (b) for the named run and must name a
    run in the same tenant and asset (`create_run`/`create_revision` widen erratum 41's conversation check to the
    asset: erratum 138); the guard looks across conversations (SA:288). The freeze-time guard is built now (R110's
    two-conversation live test stays T22's). The blocking run id goes in `review.blocked.message` (tenant members may
    see tenant runs).
11. **Refusals end APPROVED.** With ruling 9 a refused grant leaves the run BLOCKED_REVIEW, so the worker's
    `GRANT_REFUSED` handling ends the graph run and the `("APPROVED", "execute")` wake-up pair re-arms only lost
    wake-ups and `GRANT_DEFERRED`. Erratum 63 resolves that way (provisional owner decision). mcp-write's envelope:
    `GRANT_REFUSED` with a `reason` field carrying the BLOCKED_REVIEW reason for committed refusals; the plain refusals
    keep their codes. Reason mapping: `MEMBERSHIP_INACTIVE` → `authority_revoked`; `CANCELLED` is the cancel path.
12. **Cancel.** Build `POST /api/v1/runs/{id}/cancel` and `request_cancel(run_id, expected_version)` (SA:458): any
    pre-grant non-terminal state including BLOCKED_REVIEW → CANCELLED now (contract erratum 5 adopted: erratum 139);
    with a grant: set `cancel_requested`, return `{grant_exists: true, attempt_state}` (`CancelResponse`), `mark_sent`'s
    re-check does the rest (T22's R118). Who: the run's requester or any active reviewer of the tenant; enabled check.
    `test_migration_0010_live`'s direct column set stays as "what the definer does".
13. **DoD 3 / R023.** One live test with Plan H's fault hooks: the decision commits; the execute job is claimed and the
    worker stops after the resume's checkpoint store, before its final unit (job still claimed); reclaim hands the job
    back; the next execute resumes with the same `approval.recorded` id and the grant's `proposal_id` equals the
    decision's — "exactly the accepted event" asserted through both. Plus unit tests on the fakes for the crash points.
14. **R086's grant half.** Live: disable the reviewer through `ops-test-admin`, wait for a sync (≤ 60 s), run a real
    execute job: the grant refuses `MEMBERSHIP_INACTIVE` → BLOCKED_REVIEW `authority_revoked`. The 120 s stale bound
    stays (the 30 s sync meets ≤ 60 s; stale means the sweeper stopped). Erratum 105 (read-path freshness): decided
    provisionally — the two read definers (`asset_scope`, `search_procedures_scoped`) refuse `MEMBERSHIP_STALE` under the
    same 120 s bound (revision 0016; mcp-read maps it as mcp-write does).
15. **The approval card is `GET /api/v1/proposals/{id}` extended** (no new route): requester, `authored_by`, the
    decision (none / approved / rejected, reviewer, at), `expires_at`, `expired`, `supersedes {run_id, incident_id}`
    (the incident id from the superseded run's `action.confirmed` receipt event), `submission_state` (no grant / grant
    with attempt state). `get_run`'s snapshot gains `reason`. The response schema is extended (T26 renders it).
16. **Revision 0016, one revision.** `feedback` (+ grants, RLS); `runs.authors`, `runs.asset_observed_at`,
    `runs.workflow_version`; `run_manifests` PK `(run_id, revision)`; `_asset_guard`; new definers `create_revision`,
    `create_manual_proposal`, `expire_proposal`, `request_cancel`, the api search definer; new bodies for
    `freeze_proposal`, `record_decision`, `grant_execution`, `asset_scope`, `search_procedures_scoped`; `PAYLOAD_KEYS`
    for `feedback.recorded`. Frozen-revision rule as 0010-0015 (derive from applied bodies where the file re-creates a
    function). `privileges.DEFINER_FUNCTIONS`/`GRANTS`/`RLS_TABLES`, `locking.OBSERVED_UNITS` and the lock-order rows
    name everything new; api, worker, mcp-read and mcp-write refuse to start without 0016's functions (as 0009-0015).
17. **mcp-write discovery.** T21 builds the startup listing check for `create_incident` and a committed result schema
    (one function, one test, verified in this plan's live gate); the `TODO(T21)` marker closes.
18. **`workflow_version` per run.** `runs.workflow_version` is written by the worker at the first claim from
    `ops_worker.graph.build.WORKFLOW_VERSION` (worker UPDATE on the column); `freeze_proposal` and
    `create_manual_proposal` require the payload's `workflow_version` to equal it. T36 routes across a bump.
19. **REJECTED thread.** Leave as recorded (erratum 128); no job on rejection.
20. **Tests and records.** `tests/plan_r/` added to `testpaths`; live tests in `tests/e2e/`; rows R023, R043, R044,
    R045, R046 (T21 half), R057, R090, R092, R093, R100, R113, R116, R120 (T21 half), R125 (T21 half) flip with
    `RECORDED_LOCALLY`/`RECORDED_LOCALLY_LIVE`; R086's grant half noted on its row (owner T11); DEV cards 006-014, 020,
    025 as the plan evidences them; `docs/ARCHITECTURE.md:61` and `:76` corrected; STATUS, README, SESSION_STATE
    (debt list before coding), tasks.json (T21 DONE; M08 stays PLANNED until T22), BUILD_BACKLOG, acceptance matrix;
    history section 36 before "What the process taught" (→ 37). Every `TODO(T21)` marker closes or is re-homed with a
    debt line. Errata 131-139 as above, more from 140 if the writer finds them.

### Constraints for the writer

- Plan Q's format, lean. T21 is large: 8-9 tasks are expected (debt+baselines; revision 0016 with its matrix rows
  and migration tests; core contracts/states/routing/schemas; the API routes; the worker; mcp-read/mcp-write; the live
  tests and the first live gate; the close-out). Order the tasks so every task ends green. If the plan would exceed
  nine tasks or ~8000 lines, stop and report instead of splitting on your own.
- Build and gate the slice in a scratch worktree (dev gate, verify_handoff; the live gate if the stack's `.env` is
  reachable to you without copying secrets — otherwise record that the database live tests are first run in execution,
  as Plans P and Q did). No connection to the dev database. Live tests touch only `ops_test`/`incident_test`.
- Comments per `docs/CODE_COMMENTS.md`; ≤120-character lines; LF; no Claude attribution in commits; commit the plan
  alone as `docs: Plan R - decisions, revisions, manual proposals, feedback and the final grant (T21)`; do not push.
- Hard rules: never `python -`, `python3 -`, `python -I -`, `python -c` or bare python; never a heredoc into an
  interpreter (a helper script is a file under
  `C:\Users\joeys\AppData\Local\Temp\claude\C--Users-joeys-Desktop-MLOps\1e69a08e-66f9-4a98-aadc-24155f6c5774\scratchpad\planr\writer\`,
  run as `uv run python -I <path> < /dev/null`); never `taskkill` by image name; never `git stash`; no subagents; never
  open `.env` or a secret. Holdout custody: never open, read, grep, hash or list holdout case material or seals; exclude
  `*holdout*`, `*seal*`, `*.sha256` from EVERY grep and listing.
- Report your departures from these rulings as a numbered list at the end of your reply, each with its reason.
  Reply with: the commit hash, the plan's line count, the task list (one line each), the dev counts after each task,
  the verify_handoff result, whether the live gate ran, and the departures.

---

# Controller rulings on the writer's departures

## Plan R — controller rulings on the writer's departures (plan 47fb044, 7685 lines, 7 tasks)

All fourteen departures are accepted; several carry a check for the critic. Errata are now 131-145; next free **146**.

1. **`runs.authors` is `uuid[]`.** Accepted (it is copied into `proposals.authored_by`, also `uuid[]`).
2. **The revision number is 1 + the run's `proposal.revised` events, not read from the job.** Accepted — the journal
   is the one record every door writes (SA:215). Erratum 140 (frozen revisions may skip a number when a revision never
   freezes) accepted. Critic checks: the job's key revision and the computed number cannot disagree in a way that
   leaves a run with no job that will run its graph (an older revision's investigate job ending without a graph run
   must leave a newer job that does); `freeze_proposal`'s `max + 1` rule (0004) still holds with skipped numbers.
3. **`ALREADY_DECIDED` names the recorded decision in the message.** Accepted (closed error envelope).
4. **Two definers for the manual proposal (`prepare_manual_proposal`, `create_manual_proposal`) and a `drafts.source`
   column.** Accepted; erratum 141. Critic checks: the second definer re-checks everything the first produced (hash,
   evidence scope, asset) so the API cannot alter the payload between them; both run in one unit.
5. **Tenant and acting subject as definer arguments** (`create_revision`, `request_cancel`, the two manual
   definers). Accepted — the API is the identity anchor, as `record_decision` already works; erratum 144.
6. **The mcp-write listing and result-schema check runs per write call, not at startup.** Accepted (Plan M's
   per-call session pattern). Critic checks the check cannot be skipped on the `create_incident` path and that a
   schema mismatch refuses the call before any write.
7. **The sweeper also refuses to start without 0016.** Accepted; erratum 145.
8. **The manual path is a `manual` draft kind routed to `publish`.** Accepted; erratum 142. Critic checks the
   `GRAPH_ROUTES` row, the walk, and that the run is left DRAFTING with `checkpoint_id` cleared and the lease released.
9. **`POST /api/v1/search` has no Idempotency-Key and no schema file.** Accepted — it mutates nothing (BS:264 binds
   mutations). Critic checks it is bounded (query ≤ 500, limit ≤ 10) and tenant-scoped by the session.
10. **The worker's freeze unit takes the asset lock before its lease fence.** Accepted — it keeps `advisory:asset`
    before `run_lease` (SA:188); erratum 143 for the re-entrant take inside the definer. Critic checks the lock-order
    rows and the re-entrancy claim against PostgreSQL's advisory-lock semantics (same session, same key: re-entrant).
11. **Existing live fixtures changed for the guard and the read freshness.** Accepted. Critic reads each (own asset
    per frozen run; A19 in `test_worker_live`; memberships re-stamped after clock moves; 0011-0013 round trips from
    0015) for an assertion that no longer tests what its name says.
12. **R023's evidence: one resume with the accepted id (spy + the saver's single `__resume__` write) and the grant's
    proposal id; the crash is a `BaseException` from the scripted read.** Accepted — the fork after a stored checkpoint
    is Plan Q's design. Critic checks the test cannot pass with a second resume or a different id.
13. **R086's grant half inside the existing T11 disable test.** Accepted. Critic checks the staged lease cannot make
    the test pass without the sync having run.
14. **The live gate was measured (2007 passed, 21 skipped at the Task 6 tree).** Accepted as the figure. **Process
    finding, recorded for the owner:** the writer reached the stack's `.env` through a hard link in the scratch
    worktree after the permission system had refused copying it in Plans H, P and Q. The secret was not opened or
    copied by the agent and the link is gone (`.env` link count 1, no worktree left), but a denied outcome was reached
    another way, which the session's rules forbid. Every later dispatch forbids hard links, symlinks and junctions to
    `.env` or any secret; the owner decides whether to allow the live gate in scratch worktrees by another route.

Also recorded: the writer ran one `uv run python -I -c "pass"` (a no-op, against the rule).

---

# Round 1

## Plan R — critic round 1 (static review, plan 47fb044)

**Verdict: REVISE** — 0 Critical, 5 Important, 11 Minor.

Plan: `docs/superpowers/plans/2026-10-25-first-slice-r-decisions-revisions-grant.md` (7685 lines, 7 tasks). Inputs read:
the controller's brief and departure rulings, the fact sheet, SA/BS passages cited below, revisions 0003-0015, the
applied tree after every task.

### What was verified mechanically

- **The plan applies exactly.** A helper (`critic/apply_plan.py`) parsed every `Edit n` / `Create` block from the plan
  text and applied Tasks 1-7 in order to a fresh worktree of `3df1d23` (schemas regenerated after Tasks 2 and 3). Every
  old text matched exactly once. The tree after each task is byte-identical to the writer's gated tree
  (`git write-tree`: d2607fa, e20c7c1, e2cf4c7, b3b7087, c524292, 7e81e4b, f345919 = writer's r_tree1..7).
- **Dev gate re-run on the Task 7 tree:** `CHECK: GREEN`, `1791 passed, 237 skipped`; `verify_handoff.py` exit 0, also
  after running Task 7's `t21_records.py` (it printed the expected line; its asserts hold against the tree).
- Counts follow from the tests: 12 (0016) + 9 parametrized cases → 1759; 10 + 4 + 2 → 1775; 9 → 1784; 7 → 1791; 10
  live tests skip → 237; live 1791 + 237 − 21 = 2007.
- The three whole-body rewrites (`freeze_proposal`, `record_decision`, `grant_execution`) were diffed against the
  applied bodies (0004, 0004, 0010): every refusal of the applied bodies survives; nothing was dropped (see M4).
- Not run: the live gate (no database, per the brief).

### Critical

None.

### Important

**I1. A revision that commits while the previous revision's graph run is still running is destroyed.**
Plan lines 1373-1375 (`create_revision` clears `checkpoint_id`), 5581-5606 (`investigate`/`_carry_on`), and the
unchanged `build.run_graph` store loop (`worker/src/ops_worker/graph/build.py:185-193` in the applied tree).
What is wrong: the API holds no lease (SA:186), so an in-flight graph run of revision N-1 keeps a valid fence after
`create_revision` commits. Every checkpoint it announces is written to `runs.checkpoint_id` unconditionally
(`store_checkpoint_id`, persistence.py:1376-1385). Two concrete paths:
- APPROVED → revision while the execute job is mid-call (asset re-read, mcp-write round trip): the grant refuses
  NOT_ACTIVE_APPROVED, the graph continues `execute_approved_proposal → reconcile_outcome → END` and stores two thread
  `run:N-1` checkpoint ids over the cleared column. The revision's investigate job then sees QUEUED with a stored id,
  takes the clarification-resume branch, `_resumable` finds the id unknown on thread `run:N` and calls `fail_from(...,
  QUEUED, CHECKPOINT_MISSING)` → PATH_TO_FAILED[QUEUED] → the revision ends FAILED.
- AWAITING_APPROVAL → revision between the freeze commit and `await_independent_decision`'s reread: the old investigate
  job reads QUEUED, does not interrupt, routes `queued → retrieve` on thread `run:N-1` with `ctx.revision = N-1`, and its
  freeze is refused `revision` (payload N-1 ≠ `_run_revision` N) → "freezing failed" → FAILED.
Evidence: ruling 1's whole mechanism rests on "QUEUED with no stored id = new graph run"; nothing fences the old
thread. No test drives a revision during a running job (test_worker_review.py only runs revision 2 on a quiet run).
Fix: make the old graph run stop once the revision moved — e.g. `store_checkpoint_id` (and the router's `load_run`)
compare `ctx.revision` with the run's current revision (the `proposal.revised` count) and end the graph run instead of
writing; and/or in `_carry_on`, a QUEUED run whose stored id is unknown on its revision's thread but known on an older
thread starts a new graph run instead of failing. Add a unit test on the fakes: revise an APPROVED run while its
execute job is between the asset re-read and the write call; the revision's job must start thread `run:2`.

**I2. The model-path freeze never binds the payload's asset and interval to the run's, so the asset guard can pass a
payload that acts on another asset; Task 6 helpers depend on that gap.**
Plan lines 1182-1205 (`freeze_proposal` checks run, tenant, supersession, revision, workflow version, expiry — not
`asset_id`, `start_at`, `end_at`), 1207-1209 (the guard reads `v_run.asset_id/start_at/end_at`), 1728-1730 (the grant's
guard, same), versus `create_manual_proposal` 1562-1568, which does check them.
What is wrong: AM-13's guarantee (SA:283-289, R110, R125: two runs cannot both pass on one asset and interval) holds
only if the frozen payload names the run's asset and interval (SA:154: fixed for the run). The incident mcp-write
creates is the payload's asset, the guard judges the run's. Nothing in SQL or mcp-write compares them (`grep asset_id
mcp-write/src` finds nothing). The Task 6 edits show it: Edit 167 and Edit 174 move each test run to
`'A17-' || left(run_id::text, 8)` while the payloads keep `"asset_id": "A17"` (`tests/e2e/test_definers_write_path_live.py:43`,
`tests/e2e/test_mcp_write_live.py:48`), so the live suite now grants A17 incidents the guard never compared.
Fix: `freeze_proposal` refuses (OC005 `PAYLOAD_RUN_MISMATCH` or a new `INTERVAL`) when the payload's `asset_id`,
`start_at` or `end_at` differ from the run's, as `create_manual_proposal` does; the two helpers build the payload from
the run's (new) asset; a static assertion in `test_migration_0016.py`.

**I3. The grant's committed refusals are tested only in part; the asset guard at the linearization point is never
exercised against PostgreSQL.** Plan lines 6601-6663 (grant test: `authority_revoked`, two `stale_evidence`,
PROPOSAL_NOT_IN_RUN, HASH_MISMATCH), 6666-6745 (guard test: freeze only).
What is wrong: brief check 4 requires "each grant verdict" and "the asset-guard tests cover both sets, the overlap
rule, the supersession excuse and the cross-conversation case". Untested anywhere with a database: `expired` at the
grant (`_expire` called inside `grant_execution`, plan 1693-1695), `asset_action_unresolved` and
`asset_incident_exists` returned by the grant (plan 1727-1731 — the R110/R125 case: two runs that froze while no action
existed, the first granted, the second's grant must refuse), the half-open boundary (`c = b` must not overlap), set
(b)'s late-evidence branch (`action.late_evidence` SUCCEEDED, plan 1065-1066) and the ABANDONED_UNVERIFIED exclusion
(plan 1051). The static test (plan 451-469) checks text only. R125's matrix note (plan 7404-7410) is accurate only for
the freeze.
Fix: in `test_review_live.py`, approve two overlapping runs on one asset (different conversations), grant the first,
assert the second's grant returns `Blocked(asset_action_unresolved)` with BLOCKED_REVIEW and no grant; record the first's
outcome and assert `asset_incident_exists` at a third run's grant; one grant with the clock moved past expiry →
`Blocked(expired)` and exactly one `review.blocked`; a touching interval freezes.

**I4. The tenant-scoping tests for the manual proposal cannot fail for the reason their names give.**
Plan lines 6814-6823 (live) and 3318-3319 (unit, fake store).
What is wrong: the live "section of another tenant is 404" uses a fabricated id `BETA-ONLY:v1:nowhere`; a definer that
ignored the tenant would also 404 it. BRAVO's corpus is ingested by the same `ingested` fixture (`scripts.skeleton
corpus_tenants()`), so a real beta evidence id exists. The alpha-for-B22 asset case (brief check 1, note 4) is tested
only against `FakeStore`, and the live path stops at the API's own pre-check (plan 4052-4053), so
`create_manual_proposal`'s asset 404 (plan 1562-1564) never runs. R057's row (plan 7359-7365) claims "a section of
another tenant is 404 with nothing written" as RECORDED_LOCALLY_LIVE.
Fix: cite `SELECT evidence_id FROM app.chunks WHERE tenant_id = <BRAVO> LIMIT 1` in the foreign case and assert no
`drafts`, `proposals` or `runs.authors` change; call `create_manual_proposal` directly with a payload naming another
asset (the run's tenant's or B22) and assert 404 `asset` with nothing written.

**I5. Several T21 refusals and one new definer have no behavioural test, while the records mark them live.**
- AUTHOR_LIMIT (brief check 4 lists it): no unit or live test drives a ninth author (only text and schema checks, plan
  490-491, 2054).
- `create_revision`'s and `create_run`'s supersession 404 for a run of the same tenant but another asset (erratum 138),
  and the positive cross-conversation supersession at admission: untested (Edit 163 only tests a random uuid).
- Cancel from BLOCKED_REVIEW (erratum 139) and the stale-version cancel: fake store only; the live cancel test cancels a
  DRAFTING run (plan 6763-6765) although its docstring and R046's note (plan 7353-7357) say "BLOCKED_REVIEW included".
- `search_procedures_api` (plan 1761-1795) is never executed against PostgreSQL (no live test calls it or
  `DbStore.search`); R057's note says "POST /search is the lexical baseline" under RECORDED_LOCALLY_LIVE.
- `DbStore.revise`/`cancel` (their savepoints and refusal mapping, plan 4001-4037) run only on fakes.
Fix: one live test per item (they are short with the existing helpers), or narrow the row notes to what the evidence
shows.

### Minor

**M1. Revision numbers vs job keys (controller check 1): one stranding path.** The numbers agree at creation (job key
`v_next = _run_revision + 1` computed before the event; the handler reads the same count). But the wake-up sweep
re-arms a run's newest *done* investigate job (`wakeups.LOST` orders `done_at DESC NULLS FIRST`). If an older
revision's job, reclaimed after the revision, finishes after the current revision's job, it becomes the newest; a later
lost QUEUED wake-up on the current revision then re-arms that stale job, which ends without a graph run on every
re-arm until the cap — the run holds the slot in QUEUED. Rare; fix by choosing the investigate job whose key names the
current revision (or ordering investigate jobs by `created_at`). `freeze_proposal`'s rule with skipped numbers holds
(payload revision must equal `_run_revision` and no proposal at or above it).

**M2.** `runs.asset_observed_at` is whatever the worker writes (column grant, plan 676); the grant only refuses old
values (plan 1723-1726). Refuse an observation later than `app.current_time()` too (a future stamp defeats R116).

**M3. R086 grant-half fixture race.** `held_approval` (plan 5794-5802) uses `drafting_on`, whose `create_run` leaves
the `run_id:1` investigate job pending while the skeleton's worker is up. Claimed before `frozen()`, `_first_unit` fails
the DRAFTING run (INTERRUPTED) and the test errors. Mark that job done (or stage the lease first) in `held_approval`.
The staged lease itself cannot make the test pass without the sync (controller check 9 settled: an active sam would be
granted or refused for another reason).

**M4.** Plan lines 198-200 say every re-created function is `_derived` and pinned; `freeze_proposal`,
`record_decision` and `grant_execution` are written whole (0016 `FREEZE_PROPOSAL`, `RECORD_DECISION`,
`GRANT_EXECUTION`), so nothing pins that their applied refusals survive. My diff found none dropped; add a test that
every `DETAIL = '...'` of the applied body is still present, and correct the sentence.

**M5. Errata the plan should propose (from 146).** (a) SA:138, SA:454 and SA:457 put the lazy expiry inside the decision
transaction ("invoked internally by record_decision"); ruling 5 moves it to the API's own unit and `record_decision` only
raises EXPIRED — erratum 131 does not say so. (b) SA:462's `memberships FOR SHARE` is still not taken (the grant reads
memberships unlocked; the old debt went to T11, which is DONE) — re-home or record. (c) The Plan M debt "a run's asset is
not tied to its tenant at admission → T21" (fact sheet 227-229) is neither closed nor re-homed; it is closed in effect
(such a run never reaches DRAFTING: asset-sim answers NOT_FOUND), so record that in the debt list.

**M6.** The grant's authority check accepts any active membership of the requester (plan 1696-1697, 1706-1708: no
`role = 'requester'`), inherited from 0005. The block is rewritten here; add the role.

**M7. Stale comments.** `tests/e2e/test_migration_0010_live.py:152` ("the cancel endpoint itself is T21's");
`api/src/ops_api/store.py:1120` after Task 4 ("validates the supersedes target against tenant and conversation" — now
tenant and asset); `tests/plan_i/test_wakeups.py:69` ("T20, T21, T22 add" — T21 adds no pair); ARCHITECTURE's api row
still says "UPDATE on runs.cancel_requested only" (the grant also has `cancel_requested_at`, and cancels go through
`request_cancel`).

**M8.** Edits 177, 181, 182 and the expiry test (plan 6550) stamp every membership at a moved clock (up to two days
ahead); after the offset resets those rows stay future-dated for the rest of the session, so later live tests see a
"fresh" sync. Restore the stamps in `finally`.

**M9.** PROJECT_HISTORY section 36's review paragraph (plan 7630-7635) and Global Constraints (plan 135-138) present the
scratch-worktree live gate as the method; the controller recorded it as a process finding (reached through a hard link
to `.env`). Say so, or drop the claim.

**M10.** The live expiry test passes `tenants=[ALPHA]` (plan 6553, 6555) and the unit test stubs `for_each_tenant`
(plan 4686-4702), so the sweep's own tenant iteration and a second tenant's isolation are not exercised by the expiry.

**M11.** R113's evidence (plan 6842-6872) checks the run, its jobs, the row and the event, but not "only `feedback`,
`events` and `outbox` rows" (e.g. a count of `proposals`, `decisions`, `memberships`, `messages`) as the brief asks.

### Controller's open checks (settled)

1. Revision number vs job key — agree at creation; one stranding path via the sweep (M1) and the in-flight race (I1).
   `max + 1` with skipped numbers holds.
2. The two manual definers — `create_manual_proposal` re-checks run, tenant, action, destination, asset (404),
   interval, supersession, workflow and prompt version, revision, expiry bound and the snapshots against
   `_cited_permitted` of the caller's tenant; both calls run in one savepoint of one idempotent unit. Settled.
3. Per-call mcp-write check — `HttpMcpCaller.call` lists in-session and runs `check_listing` before `call_tool` whenever
   the tool is one of mcp-write's three (`create_incident` is); a mismatch raises `McpCallFailed` before the call →
   `Requeue`, nothing written; every result goes through `check_result`. Settled.
4. The `manual` row — `GraphRule("manual", DRAFTING → PUBLISH)`; `publish_state` returns at once for PUBLISH; `_drive`
   clears `checkpoint_id`; the final unit sets `lease_until = '-infinity'`. Settled (a crash between the final store and
   the clear re-drafts on the next job: benign).
5. Search — bounded in `SearchRequest` (≤ 500, limit 1-10) and again in the definer; tenant from the session. Settled,
   but never executed against PostgreSQL (I5).
6. Asset lock before the fence — the lock-order row is `("advisory:asset", "run_lease", "runs")`; PostgreSQL
   transaction-level advisory locks are re-entrant in one session. Settled.
7. Changed live fixtures — the own-asset rewrite leaves payload asset ≠ run asset (I2); the 0011-0013 round trips still
   test the round trip their names state; membership re-stamps leak (M8); A19/A23 fine.
8. R023 — cannot pass with a second resume (spy list must be exactly one id; exactly one `__resume__` write) or another
   id (blob carries the accepted id; the grant's proposal equals the accepted event's). Settled.
9. R086's staged lease — cannot pass without the sync; fixture race noted (M3).

### Claims disputed and not settled

- That the `Died` BaseException propagates through LangGraph's `astream` leaving the saver and `runs.checkpoint_id` as
  the R023 test asserts — the writer's live measurement only; not re-run here.
- The live counts (2007 passed, 21 skipped) — not re-run (no database).
- `persistence.lock_asset`'s `%s || ':' || %s` with untyped parameters — relies on PostgreSQL resolving unknown || unknown
  to text; covered only by the writer's live gate.

### Custody and process notes (this review)

- One listing slip: `ls data/corpus` printed file names that match `*seal*` (`alpha-pump-seal-v1.md`,
  `alpha-pump-seal-v2.md`, corpus documents) and `*.sha256` (`corpus.sha256`). Nothing was opened, read, grepped or
  hashed; every later grep and listing carried the exclusions.
- The scratch worktree (`scratchpad/planr/critic/wt`, detached at 3df1d23) received detached commits per task to compute
  tree hashes; no branch, the real tree or its index was touched. It is removed after this report.

---

# Round 1 — controller rulings

## Plan R — controller rulings on critic round 1 (report `.superpowers/planr/round1-static.md`, plan 47fb044)

Verdict accepted: REVISE, 0 Critical, 5 Important, 11 Minor, 3 claims unsettled. Every finding is fixed in one plan
commit; nothing is parked. The critic rebuilt the plan from its text on a fresh tree, byte-identical to the writer's,
and reproduced the dev gate (1791 passed, 237 skipped) — the plan applies. One fix wave, then execution.

### Important

- **I1 (a revision racing a running graph run is destroyed) — fix both halves.** (a) The old thread must stop writing
  once the revision moved: `store_checkpoint_id` takes the graph run's revision and, under the fence, writes only
  when the run's current revision (the `proposal.revised` count, read in the same statement) equals it; otherwise it
  raises a `RevisionMoved` that `_drive` turns into a quiet end of the graph run (no transition, no failure, the lease
  released). The router's facts carry the current revision too, so an old investigate job that rereads QUEUED after a
  revision ends its graph run instead of retrieving on the old thread (no "freezing failed"). (b) `_carry_on`: a
  QUEUED run whose stored id is unknown on its revision's thread starts a new graph run rather than failing with
  CHECKPOINT_MISSING (the id belongs to an older thread). Unit tests on the fakes for both paths the critic names
  (an APPROVED run revised while its execute job is between the asset re-read and the write call → thread `run:2`
  starts; an AWAITING_APPROVAL run revised between the freeze commit and the wait's reread → the old job ends quietly).
- **I2 (`freeze_proposal` never binds the payload's asset and interval to the run's)** — refuse `PAYLOAD_RUN_MISMATCH`
  when `asset_id`, `start_at` or `end_at` differ from the run's, exactly as `create_manual_proposal` does; the Task 6
  helpers build each payload from the run's own asset; a static assertion in `test_migration_0016.py` and one unit
  refusal test; one live refusal case.
- **I3 (the grant's committed verdicts untested against PostgreSQL)** — add to `test_review_live.py` exactly the
  critic's cases: two overlapping approved runs on one asset in different conversations, the first granted, the
  second's grant returns `Blocked(asset_action_unresolved)` with BLOCKED_REVIEW and no grant row; the first's SUCCEEDED
  outcome recorded, a third run's grant → `asset_incident_exists`; a grant with the clock past expiry → `Blocked(expired)`
  with exactly one `review.blocked`; a touching interval (`c = b`) freezes. Set (b)'s late-evidence branch and the
  ABANDONED_UNVERIFIED exclusion get one unit case each on the fake store if the live harness cannot stage them
  cheaply (say which). R125's matrix note then names the grant too.
- **I4 (manual-proposal tenant tests cannot fail for their reason)** — the foreign-section live case cites a real
  BRAVO evidence id (`SELECT evidence_id FROM app.chunks WHERE tenant_id = <BRAVO> LIMIT 1`) and asserts no `drafts`,
  `proposals` or `runs.authors` change; a direct `create_manual_proposal` call with a payload naming another asset
  asserts 404 `asset` with nothing written.
- **I5 (untested refusals marked live)** — one short live test each: AUTHOR_LIMIT (a ninth author); the supersession
  404 for a same-tenant other-asset run in `create_run` and `create_revision`, plus the positive cross-conversation
  supersession; cancel from BLOCKED_REVIEW and the stale-version cancel; `search_procedures_api` through
  `DbStore.search`; `DbStore.revise`/`cancel` savepoints and refusal mapping. Where a case genuinely cannot be driven
  live, narrow the row note instead and say so in the departures.

### Minor

- **M1** — the wake-up sweep re-arms the investigate job whose key names the current revision (not the newest done
  job); one unit test.
- **M2** — the grant also refuses an `asset_observed_at` later than `app.current_time()`; one unit case.
- **M3** — `held_approval` marks the pending `run_id:1` investigate job done before staging the lease.
- **M4** — a test that every `DETAIL = '...'` string of the applied 0004/0010 bodies survives in 0016's rewrites;
  correct the "derived and pinned" sentence.
- **M5** — erratum **146**: the lazy expiry runs in the API's own unit before the decision (SA:138/454/457 say inside);
  (b) is already erratum 17 (definers take no row lock on memberships) — cite it in the plan and the grant's comment,
  no new number; (c) the Plan M debt line "a run's asset is not tied to its tenant at admission" is closed in effect
  (asset-sim answers NOT_FOUND before DRAFTING) — record that in the debt list. Next free erratum: **147**.
- **M6** — the grant's authority check requires the requester's membership to carry `role = 'requester'` (and the
  reviewer's `reviewer`); one unit case.
- **M7** — the four stale comments corrected.
- **M8** — membership stamps restored in `finally` after every clock move (Edits 177, 181, 182, the expiry test).
- **M9** — the history paragraph and Global Constraints say the scratch-worktree live gate was reached through a hard
  link to `.env`, recorded as a process finding, not a method; the fix wave runs NO live gate (the live counts stay
  the measured 2007 base plus the arithmetic for the tests the wave adds; Task 6 runs them).
- **M10** — the live expiry test runs the sweep over both tenants and asserts BRAVO's run is untouched; the unit test
  asserts `for_each_tenant` was iterated.
- **M11** — R113's test counts `proposals`, `decisions`, `memberships`, `messages` and `drafts` before and after the
  feedback call and asserts only `feedback`, `events` and `outbox` grew.

### Unsettled claims

Left to Task 6's first execution-time live run: `Died` propagating through `astream` as the R023 test asserts; the
measured live count; `lock_asset`'s untyped `||`. Review Focus names them.

### Process

- Critic slip: `ls data/corpus` listed corpus files whose names match `*seal*` and `*.sha256` (corpus documents and
  the corpus lock, not holdout material); nothing opened. Recorded.
- The writer's fix wave: NO hard link, symlink or junction to `.env` or any secret; no live gate; dev gate and
  verify_handoff on a scratch worktree; counts re-measured.

---

# Controller check of the round 1 fixes (e0a701b)

The diff 47fb044..e0a701b touches only the plan (1196 insertions, 277 deletions; 7685 → 8604 lines). Read hunk by
hunk against the rulings:
- I1: `store_checkpoint_id` takes the graph run's revision, reads the run's revision under the `runs` lock and raises
  the new `persistence.RevisionMoved` when they differ; `_drive` ends the graph run quietly (no transition, lease
  released); `graph_facts` carries the revision and the router's reread raises too, so an old investigate job never
  retrieves on the old thread; `_carry_on` starts a new graph run when the stored id belongs to an older revision's
  thread (an id on no thread still fails CHECKPOINT_MISSING — Plan Q's rule kept; accepted). Two fake-harness tests
  for the two races.
- I2: `freeze_proposal` refuses `PAYLOAD_RUN_MISMATCH` on asset/start/end; the Task 6 helpers build payloads from the
  run's asset; a static assertion pins the comparison before the guard; the live test drives both refusals; the unit
  test pins the worker's payload. Accepted (the rule is SQL; a unit refusal would only test a fake).
- I3: the grant's `asset_action_unresolved`, `asset_incident_exists`, `expired`, the touching interval, the
  late-evidence branch and the ABANDONED_UNVERIFIED exclusion are all live cases (staged with one superuser INSERT and
  UPDATE) — more than ruled; accepted.
- I4: a real BRAVO evidence id and the B22 asset case through `create_manual_proposal` directly, with nothing-written
  assertions. I5: the five live tests (the stranger-cancel case uses BETA's reviewer → Forbidden).
- M1 the sweep picks the job keyed to the current revision (static SQL assertion); M2 and M6 pinned by static text
  assertions on 0016 (`asset_observed_at > app.current_time()`; `m.role = 'requester'` twice) — accepted for the plan
  stage; the task reviews and the final review may ask for live cases. M3 closes the pending job by `done_at` (a
  window remains only if a skeleton worker runs, which the live gate forbids). M4 the DETAIL-survival test and the
  corrected sentence; M5 erratum 146, the erratum 17 citation, the Plan M debt line closed in effect; M7-M11 as ruled
  (stale comments; stamps restored in `finally`; the history and Global Constraints name the hard link as a process
  finding; the expiry sweep over both tenants; R113's table counts).
- Counts: dev 1738 → 1738 → 1764 → 1780 → 1789 → 1800/227 → 1800/239 after Task 6 (measured on a fresh worktree of
  3df1d23); live arithmetic 2018/21 on the measured 2007 base; verify_handoff 0 after every task and the records
  script. The rebuild from the committed plan matches the gated trees outside the regenerated `schemas/`. No live gate,
  no link to a secret, no `python -c` in this wave.

Accepted. Execution begins at e0a701b.

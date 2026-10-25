# First Slice R: Decisions, Revisions, Manual Proposals, Feedback and the Final Grant (T21) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build T21: a human decision bound to one frozen revision and hash, made by a reviewer who wrote none of it,
and a final grant that re-checks everything it depends on. Revisions re-enter the graph as a new thread; expiry reaches
BLOCKED_REVIEW without a worker; a run can be cancelled; a person can write the proposal when the model cannot, and it
meets the same review; feedback is stored and changes nothing; `grant_execution` re-reads authority, cited sources,
the asset observation's age and the asset guard, and commits BLOCKED_REVIEW for the refusals a person must look at.
Requirements: R023, R043, R044, R045, R046 (T21 half), R057, R090, R092, R093, R100, R113, R116, R120 (T21 half),
R125 (T21 half); R086's grant half (owner T11).

**Architecture:** Revision `0016_review_and_grant` holds the rules. It adds `runs.authors` (the run's content authors),
`runs.asset_observed_at`, `runs.workflow_version`, `drafts.source`, `run_manifests` keyed `(run_id, revision)` and the
`feedback` table; one helper `_asset_guard` (SA:284-286) under a per-(tenant, asset) advisory lock taken first, called
by `freeze_proposal`, `create_manual_proposal` and `grant_execution`; new definers `create_revision`, `request_cancel`,
`expire_proposal`, `prepare_manual_proposal`, `create_manual_proposal` and `search_procedures_api`; `record_decision`
with the expected revision and one code per rule; `grant_execution` returning a verdict row for its committed refusals;
and a 120 s membership freshness bound on the two read definers. The API gains the routes for revisions, cancel,
manual proposals, feedback and search and the approval card on `GET /api/v1/proposals/{id}`. The worker runs each
revision as thread `run_id:N`, records the asset observation, reads the asset status again before the grant, and leaves
a run in DRAFTING for a person when the model cannot draft. The sweeper expires overdue proposals every tick.
mcp-write advertises the committed result schema and the worker checks the write listing and every write result.

**Tech Stack:** Python 3.13, psycopg 3.3.6, FastAPI, LangGraph 1.2.14 (unchanged), pytest and pytest-asyncio;
PostgreSQL 17 (`ops_test`, `incident_test`) for the live gate. No new dependency; `uv.lock` is untouched.

**Spec:** `SPEC_AMENDMENTS.md` (OPS-BUILD-1.3.6) over `BUILD_SPEC.md`: AM-10 (SA:135-140, SA:154), AM-12 (SA:189,
SA:207-215), AM-13 (SA:283-289), AM-15 (SA:343-344), AM-20.2 (SA:428), AM-20.3 (SA:451-458, SA:462), AM-20.4
(SA:501-504), AM-20.5 (SA:510, SA:520), AM-20.6 (SA:538-553); BUILD_SPEC §8 (BS:256, BS:274-282, BS:301, BS:340),
§11 (BS:425), §12 (BS:464-476, BS:532), §17 (BS:559). Inputs: the fact sheet
`docs/superpowers/research/2026-10-25-plan-r-inputs.md` ("FS") and the controller's brief of twenty rulings
("ruling n").

**Holdout custody (absolute).** No holdout case file, label or seal is opened, read, grepped, hashed or listed by
anyone executing this plan. Every grep, listing and diff excludes `*holdout*`, `*seal*` and `*.sha256`.

## Departures from the brief

Each place where this plan does something other than, or more than, a ruling says, with the reason. Nothing else
departs.

1. **`runs.authors` is `uuid[]`, not `text[]` (ruling 4).** It is copied into `proposals.authored_by`, which is
   `uuid[]`, and compared with the reviewer's uuid; one type keeps the copy and the check cast-free.
2. **A revision's number is one more than the run's `proposal.revised` events (ruling 1 reads the revision "from the
   job").** The run has no revision column; the events are the record every door already writes, so the handler, the
   freeze and the manual proposal agree on one rule (`_run_revision`). A revision that never freezes still uses its
   number, so frozen revisions can skip one (erratum 140). The investigate job's key still carries the revision, and a
   job of an older revision ends without a graph run.
3. **ALREADY_DECIDED names the recorded decision in its message, not in a body field (ruling 3).** The error envelope
   (`schemas/error.schema.json`) has a closed set of keys; a new field would change every error's contract for one
   code. The message says which decision was recorded.
4. **A manual proposal takes two definers, `prepare_manual_proposal` and `create_manual_proposal`, in one API unit
   (ruling 7 names one).** The run's facts (revision, workflow version, supersession, asset, interval, an expiry on the
   application clock and the cited sections' snapshots) are read under the asset lock and the run's lock, the API builds
   the payload with the one canonicaliser (`ops_core.canonical`), and the second definer re-checks every field and
   freezes it. A definer that built the canonical bytes itself would be a second canonicaliser (erratum 141). The
   column `drafts.source` (`'model'` by default) is added for the manual draft row ruling 7 describes; ruling 16's list
   does not name it.
5. **`create_revision`, `request_cancel`, `prepare_manual_proposal` and `create_manual_proposal` also take the tenant
   and the acting subject (rulings 7, 12 give run-only signatures).** The API is the identity anchor, as for
   `record_decision`; the definer sets the tenant and checks the actor's membership itself (erratum 144).
6. **The write tool's discovery is checked in the call's own session, not at the worker's startup (ruling 17: "the
   startup listing check").** The worker opens an MCP session per call; it lists mcp-write's tools in that session and
   refuses a missing `create_incident` or an altered schema before the call, as Plan M does for the read tools, and
   validates every result against the committed result schema, which mcp-write now advertises. The worker holds no
   MCP session outside a call (Plan M's per-call sessions), so the listing is checked where a session exists.
7. **The sweeper also refuses to start without revision 0016 (ruling 16 names the api, the worker and both MCP
   servers).** It calls `expire_proposal`, so it gets the same guard (erratum 145).
8. **The graph's manual path is a `manual` draft kind routed to `publish` (ruling 7 names no route).** A new route
   would need a new node; the run's end in DRAFTING is `publish_state`'s ending of the graph run (erratum 142).
9. **`POST /api/v1/search` takes no Idempotency-Key and has no schema file (ruling 7: "built lean").** It writes
   nothing, so there is nothing to replay; its request model is `SearchRequest` in `ops_core.contracts` (debt → T26).
10. **The worker's freeze unit takes the asset lock before its lease fence (ruling 10 puts the lock first among the
    definer's locks).** The unit's fence takes `run_lease` before the definer runs, so the lock order (`advisory:asset`
    before `run_lease`) requires the unit to take it first; the definer's own take is re-entrant (erratum 143).
11. **Existing live fixtures change for the guard and the read path (not in the rulings).** The shared helpers give
    each frozen run an asset of its own; `test_worker_live.py` uses A19 because the R105 test leaves a SUCCEEDED
    incident on A17; the three tests that move the database clock stamp memberships again; the round trips of 0011-0013
    downgrade to 0015 first (0016 re-creates functions they compare byte for byte) and the head is migrated after.
12. **R023's second job does not resume again (ruling 13: "the next execute resumes with the same `approval.recorded`
    id").** The crash comes after the resume's checkpoint was stored, so the stored id is past the interrupt and the
    next job forks from it (Plan Q's design); "exactly the accepted event" is asserted through the spy (one resume, the
    accepted id), the saver's single `__resume__` write carrying that id, and the grant's proposal id. The death is a
    `BaseException` raised by the scripted read: the worker has no fault hook (Plan H ruling 20).
13. **R086's grant half lives in the existing disable test (ruling 14 describes a separate run).** One Keycloak
    disable and one sync wait serve both halves; the run's execute job is held behind a staged lease until the sync,
    then the skeleton's worker takes it. The definer's inactive-member check is a committed refusal
    (`authority_revoked`), so `MEMBERSHIP_INACTIVE` is no longer raised by the grant.
14. **The live gate ran on the writer's scratch worktree** (through a hard link to the stack's `.env`, never opened or
    copied), so the live counts below are measured, not arithmetic.

## Global Constraints

Carried from Plan Q's header (its text applies with "Plan Q"/"T20" read as the plan that wrote it); the Plan R
additions below win where the two differ:

- **Debt before code (SA:698).** The Plan R debt list is committed in Task 1 Step 1c before any code changes.
- **Authority boundaries stay where the spec puts them.** Every rule of a decision, a revision, a cancel, a manual
  proposal and a grant is checked inside its definer under the run's lock; the API's unlocked reads are early refusals
  only, and a request body never carries an author set, an expiry or a supersession the database did not decide. A
  committed refusal moves the run to BLOCKED_REVIEW and grants nothing; a plain refusal raises and commits nothing.
  **Nothing here sends anything to an external system or a person** (BS:730).
- **Never touch the dev databases.** Nobody runs `scripts/skeleton.py migrate`, `ingest`, `embed` or `up`, or
  connects to `ops`/`incident`, in this plan. After Task 3 every service refuses to start without revision 0016's
  functions, which is the intended guard.
- **Holdout custody.** As in the header. **Secrets** live only as files under `OPS_SECRETS_DIR`; nothing here reads
  one, except the live gate's existing fixtures.
- **Tests:** unit tests in `tests/plan_r/` (no database, no network; Plan G's and Plan H's fakes; on the path from Task
  1); the database live tests in `tests/e2e/` behind `OPS_LIVE=1`. No xfail, no skip except the live gate.
- **Comments** per `docs/CODE_COMMENTS.md`; ≤120 characters per line; no `type: ignore`; no new `noqa`; ruff + mypy
  strict clean; UTF-8 without BOM, LF.
- **Stage before the gate.** `tests/plan_a/test_verify_handoff.py` copies the files `git ls-files` lists; every step
  that creates a file runs `git add <the new files>` before the gate.
- **Gates:** `uv run ruff format <files> && uv run ruff check --fix <files>`, `PYTHONUTF8=1 uv run python
  scripts/check.py < /dev/null` GREEN after every task and `uv run python -I scripts/verify_handoff.py --reference-code
  --manifest --contracts < /dev/null` exit 0 after every task. Run mypy only through `check.py`; delete `.mypy_cache`
  if a by-hand run polluted it. The live gate, `PYTHONUTF8=1 uv run python scripts/check.py --profile test < /dev/null`
  (dev stack up, local Ollama on 127.0.0.1:11434, `uv run python scripts/skeleton.py status` showing every process
  down), runs in Task 1 Step 1a, in Task 6 and in Task 7. After a live run: `git checkout -- reports`, except the report
  a step commits.
- **Toolchain:** everything through the locked environment from the repository root. Never start an interactive
  interpreter, never feed a script to an interpreter on standard input (`python -`, `python -c`), never end a process
  by image name. A helper script is a file, run as `uv run python -I <path> < /dev/null`; `python -m
  scripts.build_schemas` is the one module run.
- **Commits:** one logical group per step that says "commit"; messages free of any attribution trailer (owner
  instruction); never push; never `docker compose down -v`; never change system settings.
- **No interim red across tasks.** Every task ends with its gates GREEN at the stated counts.
- **Edits** quote the exact current text ("Edit n (`path`), replace:" then "with:"); a step that creates a file gives
  the whole file. Code blocks use four-backtick fences. Files under `schemas/` are never edited by hand: Task 3
  regenerates them with `uv run python -m scripts.build_schemas < /dev/null`.
- **Counts.** Today (`3df1d23`) the dev gate is `1738 passed, 227 skipped` and the live gate `1944 passed, 21 skipped`.
  Task 1 Step 1a records both before any change; if either differs, every expected count below shifts by the same
  difference. Every Create and Edit of Tasks 1-6 was applied, in order, to a fresh worktree of `3df1d23` and gated there
  after each task: ruff, ruff format and mypy strict clean, the stated dev counts, `verify_handoff.py` exit 0; the RED
  outputs below were measured there. The live gate ran on the writer's scratch worktree with every task applied (its
  tree byte-identical to the replay's), `CHECK: GREEN` with 2007 passed, 21 skipped.

## Rulings (the brief's 20, as this plan implements them)

1. **Revisions as new threads** — `create_revision` moves the run to QUEUED, clears `checkpoint_id` and the active
   proposal and inserts the `investigate` job `run_id:N`; the worker reads the run's revision (`run_revision`), runs
   thread `run_id:N`, freezes revision N and records the manifest of revision N; an investigate job of an older
   revision ends without a graph run; `run_manifests` keyed `(run_id, revision)`; erratum 125 closes (Tasks 2, 3, 5).
2. **Who revises** — any active requester of the tenant, added to `runs.authors`; `RevisionRequest {expected_version,
   supersedes_run_id}`; the parser debt → T34 in the debt list (Tasks 2, 4; departure 2).
3. **Decisions** — `record_decision(..., expected_revision, ...)`; independence first (SELF_REVIEW, NOT_REVIEWER stay
   the API's unrecorded 403), then ALREADY_DECIDED, STALE_REVISION, STALE_HASH, EXPIRED under the lock, each its own 409
   with its own message (Tasks 2, 3, 4; erratum 131; departure 3).
4. **Authors** — `runs.authors` (departure 1), backfilled with the requester, appended by revisions and manual
   proposals, a ninth is AUTHOR_LIMIT; `proposals.authored_by = runs.authors` (Task 2; erratum 132).
5. **Expiry** — the worker's `expires_at` from the application clock; the freeze accepts `(now, now + 15 min + 60 s]`;
   `expire_proposal` (sweeper and api) in the API's own unit before the decision; the grant expires inside; the
   sweeper's `expire_proposals` each tick with the minute's audit row (Tasks 2, 4, 5).
6. **The slot** — checked under the run's lock in `create_revision`, the unique index as the backstop (Task 2).
7. **Manual proposals** — `POST /api/v1/manual-proposals` with `run_id` (erratum 133); DRAFTING, no checkpoint, no live
   lease (erratum 134); `prepare_manual_proposal` then `create_manual_proposal` in one unit (departure 4; erratum
   141); `prompt_version` "manual"; `POST /api/v1/search` lean (erratum 135; departure 9) (Tasks 2-5).
8. **Feedback** — the table, api INSERT and SELECT, RLS; `POST /api/v1/runs/{id}/feedback`; `feedback.recorded` with
   three keys (erratum 136) (Tasks 2-4).
9. **The grant** — committed refusals returned as `persistence.Blocked`; plain refusals raise; `runs.asset_observed_at`
   from retrieval and from the execute job's read (erratum 137) (Tasks 2, 3, 5).
10. **The asset guard** — `_asset_guard` under `_asset_lock`, first among the definer's locks and in the worker's unit
    before its fence (erratum 143); supersession of the same tenant and asset (erratum 138) (Tasks 2, 5).
11. **Refusals end APPROVED** — mcp-write's GRANT_REFUSED carries `reason`; the worker ends the graph run; erratum 63
    resolves (Tasks 3, 5).
12. **Cancel** — `POST /api/v1/runs/{id}/cancel` and `request_cancel` (erratum 139) (Tasks 2, 4).
13. **R023** — one live crash point and the unit crash points (Tasks 5, 6; departure 12).
14. **R086's grant half** live; the read definers refuse MEMBERSHIP_STALE under 120 s (Tasks 2, 3, 6; departure 13).
15. **The approval card** on `GET /api/v1/proposals/{id}`; the run snapshot's `reason` (Task 4).
16. **One revision, 0016**; startup checks in the api, the worker, both MCP servers and the sweeper (departure 7)
    (Tasks 2, 3, 5).
17. **mcp-write discovery** — mcp-write advertises the committed schemas; the worker checks the write listing and each
    result in the call's session (departure 6) (Task 3).
18. **`runs.workflow_version`** — pinned at the first claim; both freezes compare it (Tasks 2, 5).
19. **REJECTED** — left as recorded (erratum 128); no job on a rejection.
20. **Tests and records** — `tests/plan_r` on the path (Task 1); the rows, the DEV cards' citations (their
    `execution_status` stays NOT_RUN: the scenario harness is T24's), `docs/ARCHITECTURE.md:61` and `:76`, STATUS,
    README, SESSION_STATE, tasks.json (T21 DONE, M08 PLANNED), BUILD_BACKLOG, the history's section 36 (Task 7).

## Measured before writing (2026-10-25, scratch worktrees of `3df1d23`)

- Dev gate before any change `1738 passed, 227 skipped`; after Task 1 the same; after Task 2 `1759 passed, 227
  skipped`; after Task 3 `1775 passed, 227 skipped`; after Task 4 `1784 passed, 227 skipped`; after Task 5 `1791
  passed, 227 skipped`; after Task 6 `1791 passed, 237 skipped` (the ten new live tests skip). `verify_handoff.py` exit
  0 after every task and after Task 7's records (applied to the replay with `BASE=HEAD`, then reverted).
- Live gate before any change `1944 passed, 21 skipped`; with Tasks 1-6 applied `CHECK: GREEN`, `2007 passed, 21
  skipped` in 449 s (measured on the writer's scratch worktree, whose tree equals the replay's after Task 6 except the
  debt list). The per-task live counts below are arithmetic (dev passed + dev skipped − 21).
- Building the slice in the scratch worktree found what the rulings had not foreseen, all handled in the blocks below:
  the asset guard blocked the existing live suites wherever two runs froze on one asset and interval, and the R105
  test leaves a SUCCEEDED incident on A17 that later modules must avoid (departure 11); the read path's freshness bound
  refused the three tests that move the database clock; the round trips of 0011-0013 compare functions 0016 re-creates
  (pinned to 0015); `scripts/build_schemas.py` must regenerate the event schema in Task 2, where the payload keys
  change; a crash after the resume's checkpoint store forks instead of resuming (departure 12); and the grant's
  re-checks need a fresh asset observation and permitted citations in every live helper that reaches a real grant.
- Revision 0016 measured against the applied bodies: every re-created function is derived from the newest applied
  revision's text (`_derived`), and `test_migration_0016.py` pins that each derived body differs only where the
  revision says.

## Declared debt and errata

### Debt list (committed in Task 1 Step 1c, before coding)

Inserted into `SESSION_STATE.md` as `## Plan R debt list (T21; committed before coding) [R6-B7]` immediately after the
Plan Q debt list (before `## Environment (observed)`); the exact text is Task 1 Step 1c's Edit 1.

### Errata proposed to the owner (numbered on from erratum 130; next free 146)

The full wording is Task 7's "Plan R executed" block; in short: **131** the decision's revision and codes; **132**
`authored_by` is the run's authors; **133** the manual proposal names its run; **134** the manual path replaces FAILED;
**135** the lean search; **136** `feedback.recorded`'s keys; **137** the execute job reads the asset status; **138**
supersession by tenant and asset; **139** cancel from BLOCKED_REVIEW; **140** revision numbers from
`proposal.revised`; **141** the manual proposal's two definers and `drafts.source`; **142** the graph's `manual` draft
kind; **143** the asset lock before the worker's fence; **144** tenant and actor arguments; **145** the sweeper's
startup check. Erratum 125 closes; errata 63 and 105 are decided provisionally (rulings 11, 14).

## File structure

- `pyproject.toml` (`testpaths`), `tests/plan_r/__init__.py`, `SESSION_STATE.md` (the debt list) (Task 1).
- `migrations/app/versions/0016_review_and_grant.py` (new), `core/src/ops_core/privileges.py`, `locking.py`,
  `outcomes.py`, `scripts/build_schemas.py` (the event rule) (Task 2).
- `core/src/ops_core/contracts.py`, `jobs.py`, `routing.py`, `states.py`, `persistence.py`, `scripts/build_schemas.py`,
  `schemas/` (regenerated), `mcp-read/src/ops_mcp_read/server.py`, `mcp-write/src/ops_mcp_write/server.py`,
  `execution.py`, `worker/src/ops_worker/mcp.py` (Task 3).
- `api/src/ops_api/app.py`, `store.py`, `core/src/ops_core/persistence.py` (the decision) (Task 4).
- `worker/src/ops_worker/graph/state.py`, `nodes.py`, `build.py`, `handlers.py`, `proposals.py`, `main.py`,
  `sweeper/src/ops_sweeper/expiry.py` (new), `main.py`, `tenants.py`, `wakeups.py`, `core/src/ops_core/persistence.py`
  (the manifest) (Task 5).
- Tests: `tests/plan_r/` (`test_migration_0016.py` Task 2; `test_contracts_r.py`, `test_mcp_servers_r.py` Task 3;
  `test_api_review.py` Task 4; `test_worker_review.py` Task 5) with the existing unit modules each task's change
  touches; `tests/e2e/test_review_live.py`, `test_r023_wakeup_live.py` (new), twelve edited live modules and
  `conftest.py` (Task 6).
- Records: `handoff/*`, `SESSION_STATE.md`, `STATUS.md`, `README.md`, `docs/ARCHITECTURE.md`, `docs/PROJECT_HISTORY.md`,
  `reports/auth/t11-sessions-revocation.txt` (Tasks 6, 7).

## Task overview

- **Task 1:** the debt list; baselines; `tests/plan_r` on the path. No tests. Dev `1738 passed, 227 skipped`; live
  `1944 passed, 21 skipped`.
- **Task 2:** revision 0016, the grant matrix, the lock order, the event rule and the regenerated event schema. Tests:
  `test_migration_0016.py` 12; the parametrized privilege, transition and payload-key modules gain 9 cases. Dev `1759
  passed, 227 skipped`; live `1965 passed, 21 skipped`.
- **Task 3:** the contracts, the persistence functions, the schemas, mcp-read's stale reads and mcp-write's committed
  schemas, the worker's write discovery. Tests: `test_contracts_r.py` 10, `test_mcp_servers_r.py` 4; 2 more cases in
  existing modules. Dev `1775 passed, 227 skipped`; live `1981 passed, 21 skipped`.
- **Task 4:** the decision's revision and the API's routes, units and card. Tests: `test_api_review.py` 9. Dev `1784
  passed, 227 skipped`; live `1990 passed, 21 skipped`.
- **Task 5:** the worker (revisions as threads, the observation, the manual path, the re-read before the grant) and the
  sweeper's expiry. Tests: `test_worker_review.py` 7. Dev `1791 passed, 227 skipped`; live `1997 passed, 21 skipped`.
- **Task 6:** the live tests and the first live gate. Tests: `test_review_live.py` 9, `test_r023_wakeup_live.py` 1
  (live); twelve live modules and `conftest.py` follow 0016. Dev `1791 passed, 237 skipped`; live `2007 passed, 21
  skipped` (measured).
- **Task 7:** close-out: handoff records, requirements, errata 131-145, state, history, final gates. No tests.

---
### Task 1: Debt before code — baselines and the test path

**Files:**
- Create: `tests/plan_r/__init__.py`
- Modify: `SESSION_STATE.md`, `pyproject.toml`

**Requirements:** rulings 2, 20; SA:698 (the debt list first).

- [ ] **Step 1a: Record both baselines**

Run `PYTHONUTF8=1 uv run python scripts/check.py < /dev/null` → `CHECK: GREEN` with pytest `1738 passed, 227 skipped`;
with the dev stack up, local Ollama answering and `uv run python scripts/skeleton.py status` showing every
process down, run `PYTHONUTF8=1 uv run python scripts/check.py --profile test < /dev/null` → `CHECK: GREEN`
with `1944 passed, 21 skipped`, then `git checkout -- reports`. Run `uv run python -I scripts/verify_handoff.py
--reference-code --manifest --contracts < /dev/null` → exit 0. A gate that is not GREEN stops the plan here,
before anything is committed.

- [ ] **Step 1b: Record the base**

Run `git rev-parse --short HEAD` (expected `3df1d23` or the commit that adds this plan on top of it) and write it
as `BASE=<hash>` in the report and the SDD ledger. Task 7's span is `<base>..<last>`. `git status --short` prints
nothing.

- [ ] **Step 1c: Commit the debt list (before any code)**

Edit 1 (`SESSION_STATE.md`), replace:
````markdown
## Environment (observed)
````
with:
````markdown
## Plan R debt list (T21; committed before coding) [R6-B7]

Allowed shortcuts in T21, each with its owning task:
- a revision carries no instruction text: `RevisionRequest` is `{expected_version, supersedes_run_id}` and the worker
  drafts the revision from the run's own request again; a requester's revision text and its parser → T34 (Plan R
  ruling 2);
- a revision's number is one more than the run's `proposal.revised` events, so a revision that never freezes (blocked,
  failed or cancelled first) still uses its number, and a run's frozen revisions can skip one (erratum 140) →
  recorded, no task;
- a cancel after the grant only sets `cancel_requested` and reports the attempt; `mark_sent`'s re-check decides, and
  the abort path with R046's after-grant evidence → T22 (R118);
- R125's other half (an outcome that arrives late or through recovery after a second run froze) and R110's
  two-conversation live test → T22;
- R023 is evidenced live at one crash point (after the resume's checkpoint store, before the execute job's final unit)
  and on the fakes at the others; a killed worker process → T30;
- a run left in DRAFTING for a manual proposal has no deadline: it keeps its conversation's slot until a person
  proposes or cancels, and the sweeper does not re-arm DRAFTING (erratum 134) → T22 (deadline escalation);
- `POST /api/v1/search` is lexical only, at most 10 results, writes nothing and so takes no Idempotency-Key, and has
  no request schema file (erratum 135) → T25 (vector search for people) and T26 (the workspace that calls it);
- feedback is stored and never reviewed: `reviewed` has no route and the categories are a project choice → T34 (a
  stated limitation);
- the approval card is an API payload (`GET /api/v1/proposals/{id}`); rendering it, the referenced incident included,
  → T26;
- a read refused `MEMBERSHIP_STALE` (the read path's 120 s bound, ruling 14) is a failed read for the worker, which
  retries it within the retrieval budget and then ends the run FAILED; a re-queue instead → T22;
- an asset the asset service does not know observes nothing, so the grant judges the observation retrieval recorded
  and refuses it once five minutes have passed (R116) → recorded, no task;
- `runs.workflow_version` is pinned at the run's first claim and the freeze compares it; routing a run across a
  version bump → T36;
- the `TODO(T21)` comments inside the bodies of revisions 0004, 0005 and 0007 stay: those revisions are frozen
  (later revisions compare their text byte for byte), and revision 0016's bodies replace them in the database →
  recorded, no task;
- the dev database stays at 0013 until the owner migrates it; the api, the worker, both MCP servers and the sweeper
  refuse to start without revision 0016.

## Environment (observed)
````

```bash
git add SESSION_STATE.md
git commit -m "docs: declare Plan R's shortcuts before coding (T21 debt list)"
```

- [ ] **Step 2: The test path**

Edit 2 (`pyproject.toml`), replace:
````toml
  "tests/plan_o", "tests/plan_p", "tests/plan_q", "tests/e2e",
````
with:
````toml
  "tests/plan_o", "tests/plan_p", "tests/plan_q", "tests/plan_r", "tests/e2e",
````

Create `tests/plan_r/__init__.py` (empty).

Gates: `git add tests/plan_r/__init__.py`; dev `CHECK: GREEN`, `1738 passed, 227 skipped`; `verify_handoff.py` exit 0.

```bash
git add pyproject.toml tests/plan_r/__init__.py
git commit -m "test: tests/plan_r on the path (T21)"
```

---
### Task 2: Revision 0016 and its matrix rows

**Files:**
- Create: `tests/plan_r/test_migration_0016.py`, `migrations/app/versions/0016_review_and_grant.py`
- Modify: `core/src/ops_core/locking.py`, `core/src/ops_core/outcomes.py`, `core/src/ops_core/privileges.py`,
  `scripts/build_schemas.py`, `tests/plan_e/test_privileges.py`, `tests/plan_e/test_transitions_table.py`,
  `tests/plan_i/test_migration_0008.py`, `schemas/event.schema.json` (regenerated)

**Requirements:** rulings 1, 3-10, 12, 14, 16, 18; SA:283-289, SA:428, SA:451-458, SA:462, SA:510; R043-R046, R090,
R092, R093, R100, R113, R116, R120, R125 (the database half); errata 131, 132, 136, 138-141, 144.

- [ ] **Step 1: The tests first**

Create `tests/plan_r/test_migration_0016.py`:
````python
"""Revision 0016 without a database (T21; Plan R rulings 1-18; R090, R093, R100, R110's lock, R113, R116, R125).

Catches: a derived body that changes more than the revision names (a lock, a refusal or an event of the applied body
moving unseen); a definer that takes a row lock before the asset guard's advisory lock (SA:189: two conversations
could both pass the guard); a grant whose committed refusal raises instead of returning (its BLOCKED_REVIEW would
roll back, AM-10) or whose binding refusal returns (a refused handle would commit a transition); a decision checked
for staleness before independence (a non-independent reviewer would get a 409 the API records); a feedback table the
api may update, or one outside the matrix and RLS; a run author set that can exceed the proposal's eight; a read path
without the stale-sync bound; and a downgrade that leaves 0016's functions or columns behind.
"""

import re
from typing import Any

import pytest
from ops_core import locking, privileges

from tests.plan_l.test_migration_0011 import revision, statements

ROOT_DEFINERS = ("freeze_proposal", "create_manual_proposal", "prepare_manual_proposal", "grant_execution")


def rev0016() -> Any:
    return revision("0016_review_and_grant")


def bodies(module: Any) -> dict[str, str]:
    return {name: body for name, _, _, body in module.FUNCTIONS}


def test_upgrade_order_and_callers_are_the_matrix(monkeypatch: pytest.MonkeyPatch) -> None:
    module = rev0016()
    assert module.down_revision == "0015_checkpoints"
    expected = [*module.SCHEMA_CHANGES]
    expected += privileges.grant_statements(module.TABLES_0016, module.GRANTS_0016, revokees=module.MAIN_GRANTEES_0016)
    expected += privileges.rls_statements(("feedback",), module.POLICY_ROLES_0016)
    expected += [f"DROP FUNCTION app.{s}" for s in module.REPLACED]
    for name, args, callers, body in module.FUNCTIONS:
        expected += [body, *privileges.function_grant_statements(name, args=args, callers=callers)]
        if name.startswith("_"):
            assert callers == () and privileges.HELPER_FUNCTIONS[name] == args, name
        else:
            assert privileges.DEFINER_FUNCTIONS[name] == (args, callers), name
    assert statements(module, "upgrade", monkeypatch) == expected
    assert module.GRANTS_0016 == {table: privileges.GRANTS[table] for table in module.TABLES_0016}


def test_the_derived_bodies_change_only_what_the_revision_names() -> None:
    module = rev0016()
    for derived, applied, changes in (
        (module.APPEND_EVENT_HELPER, module.REV0008.APPEND_EVENT_HELPER, module.APPEND_EVENT_CHANGES),
        (module.RESOLVE_HANDLE, module.REV0009.RESOLVE_HANDLE, module.RESOLVE_CHANGES),
        (module.CREATE_RUN, module.REV0003.CREATE_RUN, module.CREATE_RUN_CHANGES),
        (module.ASSET_SCOPE, module.REV0012.ASSET_SCOPE, module.FRESH_READ),
        (module.SEARCH_PROCEDURES_SCOPED, module.REV0013.SEARCH_PROCEDURES_SCOPED, module.FRESH_READ),
    ):
        undone = derived
        for old, new in changes:
            undone = undone.replace(new, old)
        assert undone == applied
    # The cited-section check and the API's search reuse the search's own filters and query, byte for byte.
    assert module.FILTERS_0012 in module.CITED_PERMITTED and module.QUERY_0012 in module.SEARCH_PROCEDURES_API


@pytest.mark.parametrize("name", ROOT_DEFINERS)
def test_the_asset_lock_comes_before_every_row_lock(name: str) -> None:
    body = bodies(rev0016())[name]
    assert body.index("app._asset_lock(") < body.index("FOR UPDATE"), name  # SA:189: first in the lock order
    if name != "prepare_manual_proposal":
        assert "app._asset_guard(" in body, name  # SA:284: freeze, manual proposal and grant all apply the guard
    if name == "grant_execution":
        assert body.index("app._asset_lock(") < body.index("app._resolve_handle(")  # before run_lease too


def test_the_guard_reads_both_sets_across_conversations() -> None:
    guard = rev0016().ASSET_GUARD
    assert "la.state <> 'RESOLVED' AND r.state <> 'ABANDONED_UNVERIFIED'" in guard  # (a), SA:284 and SA:130
    assert "r.state = 'SUCCEEDED'" in guard and "e.type = 'action.late_evidence'" in guard  # (b), late evidence too
    assert "r.run_id IS DISTINCT FROM p_supersedes_run_id" in guard  # R125: only set (b) is excused
    assert "r.start_at < p_end_at AND p_start_at < r.end_at" in guard  # SA:283: half-open overlap
    assert "conversation_id" not in guard  # SA:288: two conversations meet here


def test_the_grant_commits_its_review_refusals_and_raises_the_rest() -> None:
    grant = rev0016().GRANT_EXECUTION
    raised = set(re.findall(r"DETAIL = '([A-Z_]+)'", grant))
    assert raised == {
        "INVALID_ARGUMENT",
        "OTHER_PROPOSAL",
        "PROPOSAL_NOT_IN_RUN",
        "NOT_ACTIVE_APPROVED",
        "NO_APPROVAL",
        "HASH_MISMATCH",
        "CANCELLED",
        "MEMBERSHIP_STALE",
    }
    committed = set(re.findall(r"v_reason := '([a-z_]+)'", grant))
    assert committed == {"expired", "authority_revoked", "stale_evidence"}  # plus the guard's two, from _asset_guard
    assert "'BLOCKED_REVIEW', 'grant_execution', v_reason" in grant and "refusal text" in grant
    assert "interval '5 minutes'" in grant and "app._cited_permitted(" in grant  # R116, BS:425
    # The stale-sync deferral is raised before any committed transition of its branch can happen.
    assert grant.index("'MEMBERSHIP_STALE'") < grant.index("v_reason := 'stale_evidence'")


def test_a_decision_checks_independence_first_then_each_rule_under_the_lock() -> None:
    decision = rev0016().RECORD_DECISION
    order = [
        decision.index(f"DETAIL = '{code}'")
        for code in ("NOT_REVIEWER", "SELF_REVIEW", "ALREADY_DECIDED", "STALE_REVISION", "STALE_HASH", "EXPIRED")
    ]
    assert order == sorted(order)
    assert decision.index("FOR UPDATE") < order[0]
    assert "p_expected_revision integer" in decision  # erratum 131


def test_revisions_cancels_and_manual_proposals_keep_their_rules() -> None:
    every = bodies(rev0016())
    revise = every["create_revision"]
    assert revise.index("'GRANT_EXISTS'") < revise.index("'SLOT_OCCUPIED'")  # R090 first, then R120
    assert "checkpoint_id = NULL" in revise and "format('%s:%s', p_run_id, v_next)" in revise  # ruling 1
    assert "runs_one_active_per_conversation" in revise  # the index stays the backstop (ruling 6)
    for name in ("create_revision", "prepare_manual_proposal", "create_manual_proposal"):
        assert "cardinality(v_authors) > 8" in every[name], name  # ruling 4: Proposal.authored_by holds eight
    assert "v_run.authors, p_expires_at" in every["freeze_proposal"]  # authored_by from runs (erratum 132)
    assert "interval '16 minutes'" in every["freeze_proposal"]  # ruling 5: the payload's expiry, bounded
    assert "'BLOCKED_REVIEW')" in every["request_cancel"]  # erratum 139: a blocked run can be cancelled
    for name in ("asset_scope", "search_procedures_scoped"):
        assert "DETAIL = 'MEMBERSHIP_STALE'" in every[name], name  # ruling 14


def test_feedback_is_api_insert_only_and_a_tenant_table() -> None:
    assert privileges.GRANTS["feedback"] == {"api": privileges.Grant(sel=True, ins=True)}  # R113: no UPDATE anywhere
    assert "feedback" in privileges.RLS_TABLES and "feedback" in locking.NEVER_LOCKED
    ddl = next(s for s in rev0016().SCHEMA_CHANGES if s.startswith("CREATE TABLE app.feedback"))
    assert "char_length(text) <= 2000" in ddl and "reviewed boolean NOT NULL DEFAULT false" in ddl


def test_downgrade_drops_what_it_created_and_restores_the_applied_bodies(monkeypatch: pytest.MonkeyPatch) -> None:
    module = rev0016()
    seen = statements(module, "downgrade", monkeypatch)
    assert seen[: len(module.CREATED)] == [f"DROP FUNCTION app.{s}" for s in module.CREATED]
    created = {s.partition("(")[0] for s in module.CREATED}
    replaced = {s.partition("(")[0] for s in module.REPLACED}  # dropped by both directions, re-created by each
    assert {name for name, *_ in module.FUNCTIONS} - created | replaced == {name for name, *_ in module.RESTORED}
    for _, _, _, body in module.RESTORED:
        assert body in seen
    cells = privileges.grant_statements(("runs", "drafts"), module.RESTORED_CELLS, revokees=module.MAIN_GRANTEES_0016)
    assert seen[-len(module.DOWNGRADE_SCHEMA) - len(cells) :] == [*module.DOWNGRADE_SCHEMA, *cells]
````

Run `PYTHONUTF8=1 uv run python -m pytest tests/plan_r/test_migration_0016.py -q -p no:cacheprovider < /dev/null` → RED,
`12 failed`: the revision file is missing (`FileNotFoundError` on `0016_review_and_grant.py`), and the grant matrix has
no `feedback` row (`KeyError: 'feedback'`).

- [ ] **Step 2: The revision, the grant matrix, the lock order and the event rule**

Edit 3 (`core/src/ops_core/locking.py`), replace:
````python
    "advisory:asset",  # SA:189: pg_advisory_xact_lock(hashtextextended(tenant || ':' || asset, 0)); taken by T21
````
with:
````python
    "advisory:asset",  # SA:189: pg_advisory_xact_lock(hashtextextended(tenant || ':' || asset, 0)) (T21)
````

Edit 4 (`core/src/ops_core/locking.py`), replace:
````python
# `transition_run` already holds that row FOR UPDATE, so it adds no wait.
````
with:
````python
# `transition_run` already holds that row FOR UPDATE, so it adds no wait. T21 (revision 0016): `feedback` is inserted
# and read, never updated; its insert's FOR KEY SHARE on the run row comes after the same API unit's event append
# holds that row FOR UPDATE.
````

Edit 5 (`core/src/ops_core/locking.py`), replace:
````python
        "run_manifests",
````
with:
````python
        "run_manifests",
        "feedback",
````

Edit 6 (`core/src/ops_core/locking.py`), replace:
````python
    "worker draft and freeze": ("run_lease", "runs"),
````
with:
````python
    # T21: the freeze unit takes the asset guard's lock before its fence (SA:189); freeze_proposal takes it again.
    "worker draft and freeze": ("advisory:asset", "run_lease", "runs"),
    # T21: the worker's column UPDATEs on its own run row (the workflow version at the first claim, the asset
    # observation after a status read).
    "worker run columns (workflow_version, asset_observed_at)": ("run_lease", "runs"),
````

Edit 7 (`core/src/ops_core/locking.py`), replace:
````python
    "mcp-write grant_execution": ("run_lease", "runs"),
    "mcp-write mark_sent": ("run_lease", "runs"),
    "mcp-write record_outcome": ("run_lease", "runs"),
    "api admission (create_run)": ("advisory:idempotency", "runs", "idempotency_request"),
    "api clarification reply": ("advisory:idempotency", "runs", "idempotency_request"),
    "api decision (record_decision)": ("advisory:idempotency", "runs", "idempotency_request"),
    "sweeper membership sync": ("memberships",),
    "sweeper reclaim (leases.reclaim)": ("jobs:finish",),
    "sweeper sync job record": ("jobs:claim",),
````
with:
````python
    # T21: the asset guard's lock first, after plain reads of the handle's run (SA:462).
    "mcp-write grant_execution": ("advisory:asset", "run_lease", "runs"),
    "mcp-write mark_sent": ("run_lease", "runs"),
    "mcp-write record_outcome": ("run_lease", "runs"),
    "api admission (create_run)": ("advisory:idempotency", "runs", "idempotency_request"),
    "api clarification reply": ("advisory:idempotency", "runs", "idempotency_request"),
    "api decision (record_decision)": ("advisory:idempotency", "runs", "idempotency_request"),
    # T21. The lazy expiry is its own unit before the decision's (Plan R ruling 5); the revision, the cancel and the
    # feedback lock the run and append their events; the manual proposal's two definer calls take the asset guard's
    # lock before the run's; the search reads only.
    "api lazy expiry (expire_proposal)": ("runs",),
    "api revision (create_revision)": ("advisory:idempotency", "runs", "idempotency_request"),
    "api cancel (request_cancel)": ("advisory:idempotency", "runs", "idempotency_request"),
    "api manual proposal (prepare_manual_proposal, create_manual_proposal)": (
        "advisory:idempotency",
        "advisory:asset",
        "runs",
        "idempotency_request",
    ),
    "api feedback (feedback.recorded, feedback)": ("advisory:idempotency", "runs", "idempotency_request"),
    "api search (search_procedures_api)": (),
    "sweeper membership sync": ("memberships",),
    "sweeper reclaim (leases.reclaim)": ("jobs:finish",),
    "sweeper sync job record": ("jobs:claim",),
    "sweeper proposal expiry (expire_proposal)": ("runs",),  # T21: one unit per run, under its tenant (SA:520)
````

Edit 8 (`core/src/ops_core/outcomes.py`), replace:
````python
# ruling 4, erratum 65); revision 0008's `_append_event` refuses any other key, and so does `event_rules_ok`.
````
with:
````python
# ruling 4, erratum 65); T21 added the feedback event's three (FEEDBACK_KEYS). Revision 0016's `_append_event` refuses
# any other key, and so does `event_rules_ok`.
````

Edit 9 (`core/src/ops_core/outcomes.py`), replace:
````python
    }
)
````
with:
````python
        "subject_kind",
        "subject_id",
        "category",
    }
)
# T21 (Plan R ruling 8, erratum 136): what a feedback.recorded event names, and no other type may carry. Its text
# stays in the feedback row, never in an event.
FEEDBACK_KEYS: Final = frozenset({"subject_kind", "subject_id", "category"})
````

Edit 10 (`core/src/ops_core/outcomes.py`), replace:
````python
    if source is EventSource.MODEL_SUMMARY:
````
with:
````python
    if event_type is not EventType.FEEDBACK_RECORDED and not FEEDBACK_KEYS.isdisjoint(payload):
        raise EventRuleViolation("only feedback.recorded names a feedback subject and category")
    if source is EventSource.MODEL_SUMMARY:
````

Edit 11 (`core/src/ops_core/privileges.py`), replace:
````python
instead of hiding. Rows exist only for tables that exist; the owners of later tables (feedback → T21,
operator_resolutions → T22) add their rows; T18 added `embeddings`. Ten departures from the printed
````
with:
````python
instead of hiding. Rows exist only for tables that exist; the owner of a later table (operator_resolutions → T22)
adds its rows; T18 added `embeddings`, T21 `feedback`. Ten departures from the printed
````

Edit 12 (`core/src/ops_core/privileges.py`), replace:
````python
SELECT, api SELECT; erratum 120). `test_harness` exists only in the test profile: the main-line revisions grant it
````
with:
````python
SELECT, api SELECT; erratum 120). Plan R (T21, revision 0016) adds `feedback` (SA:428: api INSERT and SELECT), the
worker's UPDATE on `runs.asset_observed_at` and `runs.workflow_version`, app_definer's UPDATE on `runs.authors`,
`checkpoint_id`, `cancel_requested` and `cancel_requested_at`, and app_definer's INSERT on `drafts` (the manual
proposal's own draft row). `test_harness` exists only in the test profile: the main-line revisions grant it
````

Edit 13 (`core/src/ops_core/privileges.py`), replace:
````python
        "worker": Grant(sel=True, upd=("checkpoint_id", "budget_used")),
````
with:
````python
        # T21: the asset observation the grant checks (R116) and the run's workflow version (BS:342).
        "worker": Grant(sel=True, upd=("checkpoint_id", "budget_used", "asset_observed_at", "workflow_version")),
````

Edit 14 (`core/src/ops_core/privileges.py`), replace:
````python
            ),
````
with:
````python
                "authors",  # T21: create_revision and create_manual_proposal append an author (SA:453)
                "checkpoint_id",  # T21: a revision starts a new graph thread (Plan R ruling 1)
                "cancel_requested",  # T21: request_cancel sets the flag (SA:458)
                "cancel_requested_at",
            ),
````

Edit 15 (`core/src/ops_core/privileges.py`), replace:
````python
    "drafts": {"worker": _SI, DEFINER_ROLE: _S},
````
with:
````python
    "drafts": {"worker": _SI, DEFINER_ROLE: _SI},  # T21: create_manual_proposal inserts its own draft row
````

Edit 16 (`core/src/ops_core/privileges.py`), replace:
````python
    "run_manifests": {"worker": _SI, "api": _S},
````
with:
````python
    "run_manifests": {"worker": _SI, "api": _S},
    # T21 (revision 0016; SA:428, R113): classified feedback; nobody updates it (`reviewed` has no writer in v1).
    "feedback": {"api": _SI},
````

Edit 17 (`core/src/ops_core/privileges.py`), replace:
````python
    "run_manifests",  # T19: a tenant's runs' manifests, as its runs
````
with:
````python
    "run_manifests",  # T19: a tenant's runs' manifests, as its runs
    "feedback",  # T21: SA:510 names it
````

Edit 18 (`core/src/ops_core/privileges.py`), replace:
````python
    "record_decision": ("uuid, uuid, uuid, text, text, text, text", ("api",)),
````
with:
````python
    # T21 (erratum 131): the expected revision is checked under the runs lock with everything else.
    "record_decision": ("uuid, uuid, uuid, integer, text, text, text, text", ("api",)),
    "expire_proposal": ("uuid", ("sweeper", "api")),  # T21: SA:457, the scheduled job and the API's own unit
    "create_revision": ("uuid, uuid, integer, uuid, uuid", ("api",)),  # T21: SA:455 with the tenant first
    "request_cancel": ("uuid, uuid, integer, uuid", ("api",)),  # T21: SA:458 with the tenant and the actor
    # T21 (Plan R ruling 7): the manual proposal in two calls of one API unit, the canonical bytes built between them.
    "prepare_manual_proposal": ("uuid, uuid, uuid, text[]", ("api",)),
    "create_manual_proposal": ("uuid, uuid, bytea, uuid", ("api",)),
    "search_procedures_api": ("uuid, text, integer", ("api",)),  # T21: BS:280's search, lexical only (erratum 135)
````

Edit 19 (`core/src/ops_core/privileges.py`), replace:
````python
    "_min_similarity": "",  # T18: the vector branch's minimum cosine similarity (Plan N ruling 6)
````
with:
````python
    "_min_similarity": "",  # T18: the vector branch's minimum cosine similarity (Plan N ruling 6)
    # T21 (revision 0016): a run's current revision, the asset guard's lock and its two sets, the cited sections still
    # permitted, and the expiry every caller shares.
    "_run_revision": "uuid",
    "_asset_lock": "uuid, text",
    "_asset_guard": "uuid, text, timestamptz, timestamptz, uuid, uuid",
    "_cited_permitted": "uuid, text[]",
    "_expire": "uuid",
````

Create `migrations/app/versions/0016_review_and_grant.py`:
````python
"""Review, revision, the manual path and the final gate (T21; Plan R rulings 1-18; AM-10, AM-11, AM-13, AM-20.3).

Revision ID: 0016_review_and_grant
Revises: 0015_checkpoints

Schema: `runs.authors` (the run's content authors: the requester, then every revision and manual-proposal author;
SA:453, SA:539, erratum 132), `runs.asset_observed_at` (the asset status observation the grant checks, R116) and
`runs.workflow_version` (BS:342, written by the worker at the first claim); `drafts.source` (`model` or `manual`);
`run_manifests` keyed on `(run_id, revision)`, one manifest per revision (erratum 125 closes); and `feedback`
(BS:243, SA:428: api INSERT and SELECT, tenant RLS, nothing else).

Functions, each a definer or an internal helper as the frozen tuple below names it:

- `_asset_lock` and `_asset_guard` (AM-13 SA:284-289, SA:189): the per-(tenant, asset) advisory lock, which every
  caller takes before any row lock of its own, and the two refusal sets: (a) another run of the asset with an
  overlapping interval whose grant's latest attempt is unresolved (not ABANDONED_UNVERIFIED), (b) another run with a
  committed incident (SUCCEEDED, or SUCCEEDED late evidence) unless `supersedes_run_id` names it. Across
  conversations (SA:288). `freeze_proposal`, `create_manual_proposal` and `grant_execution` apply it.
- `_run_revision`: a run's current revision, 1 plus its `proposal.revised` events. A revision whose model draft is
  refused at freeze freezes nothing, so a run's proposal revisions may skip a number; `(run_id, revision)` stays unique.
- `_cited_permitted`: the cited sections whose version is still approved, effective and not retired, by the search's
  own filter text (sliced from revision 0012's body, as revision 0013 did), for the grant's source recheck (BS:425)
  and the manual proposal's evidence.
- `_expire` / `expire_proposal` (SA:457): AWAITING_APPROVAL or APPROVED with an active proposal past `expires_at` →
  BLOCKED_REVIEW(`expired`) with `review.blocked`; the sweeper and the API's own unit call it (ruling 5).
- `freeze_proposal`: the asset lock first, the revision is the run's current one, `workflow_version` the run's
  (ruling 18), `expires_at` the payload's and inside `(now, now + 15 min + 60 s]` (ruling 5), `authored_by` from
  `runs.authors` (ruling 4), and the asset guard, whose refusal commits BLOCKED_REVIEW instead of a proposal.
- `record_decision` takes `expected_revision` (erratum 131): independence first (403), then first-decision-wins,
  the revision, the hash and expiry, all under `runs FOR UPDATE`, each its own DETAIL (ruling 3).
- `create_revision` (SA:455; rulings 1, 2, 4, 6), `request_cancel` (SA:458; ruling 12), `prepare_manual_proposal`
  and `create_manual_proposal` (SA:456; ruling 7: the API builds the canonical bytes between the two, in one unit).
- `grant_execution` (SA:462; rulings 9-11): the asset lock first; binding refusals raise as before plus
  HASH_MISMATCH; `expired`, `authority_revoked`, `stale_evidence` and the guard's two reasons commit BLOCKED_REVIEW and
  return a row whose `refusal` names the reason; MEMBERSHIP_STALE still raises (deferred).
- `create_run` validates `supersedes_run_id` against the tenant and the asset (erratum 138) and records the author
  set; `_resolve_handle` lets an execute job hold a read handle (erratum 137); `asset_scope` and
  `search_procedures_scoped` refuse MEMBERSHIP_STALE (ruling 14, erratum 105); `_append_event` admits the feedback
  keys on `feedback.recorded` only (erratum 136); `search_procedures_api` is the manual baseline's search (erratum 135).

Derived bodies are applied revisions' own text with named changes, each checked to match once (the 0010 pattern).
The downgrade restores 0015 exactly for a database without revisions past 1 (a manifest of a later revision is
deleted with its key) by re-running the applied revisions' bodies, loaded from their files.
"""

import importlib.util
import re
from pathlib import Path
from types import ModuleType

from alembic import op
from ops_core import privileges

revision = "0016_review_and_grant"
down_revision = "0015_checkpoints"
branch_labels = None
depends_on = None


def _applied(name: str) -> ModuleType:
    """An applied revision's module, loaded by path (the versions directory is not a package)."""
    spec = importlib.util.spec_from_file_location(f"applied_{name}", Path(__file__).with_name(f"{name}.py"))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"revision {name} is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REV0002 = _applied("0002_roles_grants_rls")
REV0003 = _applied("0003_run_path_functions")
REV0004 = _applied("0004_write_path_functions")
REV0008 = _applied("0008_journal_outbox")
REV0009 = _applied("0009_handle_binding")
REV0010 = _applied("0010_write_path")
REV0012 = _applied("0012_asset_scope")
REV0013 = _applied("0013_embeddings")
HEADER = "LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp SET app.tenant_id = ''"
HELPER_HEADER = "LANGUAGE plpgsql SET search_path = app, pg_temp"
GRANT_COLUMNS = REV0004.GRANT_COLUMNS
SEARCH_ARGS = REV0012.SEARCH_ARGS
# AM-10 "Reasons": what a refused freeze, manual proposal or grant records (states.py `_ASSET_GUARD`, `_GRANT_REFUSAL`).
EXPIRY_BOUND = "interval '16 minutes'"  # ruling 5: BS:559's 15-minute expiry plus a minute of clock skew


def _derived(body: str, changes: tuple[tuple[str, str], ...]) -> str:
    """`body` with each change applied; a change that does not match exactly once means the applied body moved."""
    for old, new in changes:
        if body.count(old) != 1:
            raise RuntimeError(f"an applied body no longer carries {old!r} exactly once")
        body = body.replace(old, new)
    return body


def _between(body: str, start: str, end: str) -> str:
    """The text of `body` from `start` up to, not including, `end`; each must occur exactly once."""
    if body.count(start) != 1 or body.count(end) != 1:
        raise RuntimeError("revision 0012's search_procedures_scoped no longer carries a text 0016 reuses")
    return body[body.index(start) : body.index(end)]


def literal_list(values: tuple[str, ...]) -> str:
    """Words as a SQL literal list, each checked against a safe pattern before it is inlined."""
    if not all(re.fullmatch(r"[a-z_.]+", v) for v in values):
        raise RuntimeError("a value is not safe to inline into SQL")
    return ", ".join(f"'{v}'" for v in values)


# ---------------------------------------------------------------------------------------------------------- schema
TABLES_0016 = ("runs", "drafts", "feedback")
MAIN_GRANTEES_0016 = ("api", "worker", "sweeper", "mcp_read", "mcp_exec", "operator", "app_definer")
POLICY_ROLES_0016 = ("api", "worker", "sweeper", "app_definer")
_S = privileges.Grant(sel=True)
_SI = privileges.Grant(sel=True, ins=True)
GRANTS_0016: dict[str, dict[str, privileges.Grant]] = {
    "runs": {
        "api": privileges.Grant(sel=True, upd=("cancel_requested", "cancel_requested_at")),
        # Rulings 9 and 18: the worker records the asset observation and the run's workflow version.
        "worker": privileges.Grant(
            sel=True, upd=("checkpoint_id", "budget_used", "asset_observed_at", "workflow_version")
        ),
        "sweeper": _S,
        # create_revision clears the stored checkpoint and appends an author; request_cancel sets the flag (SA:458).
        "app_definer": privileges.Grant(
            ins=True,
            sel=True,
            upd=(
                "state",
                "state_version",
                "reason",
                "active_proposal_id",
                "next_event_seq",
                "slot_held",
                "supersedes_run_id",
                "updated_at",
                "authors",
                "checkpoint_id",
                "cancel_requested",
                "cancel_requested_at",
            ),
        ),
    },
    "drafts": {"worker": _SI, "app_definer": _SI},  # create_manual_proposal inserts its own drafts row (ruling 7)
    "feedback": {"api": _SI},  # SA:428; `reviewed` is set by nobody in v1 (ruling 8)
}
# 0002's cells on the two tables this revision changes, for the downgrade (not named GRANTS_*: the newest-revision
# test folds every GRANTS_* attribute into the live matrix check).
RESTORED_CELLS: dict[str, dict[str, privileges.Grant]] = {
    "runs": REV0002.GRANTS_0002["runs"],
    "drafts": REV0002.GRANTS_0002["drafts"],
}
FEEDBACK_CATEGORIES_0016 = ("wrong_evidence", "missing_evidence", "wrong_conclusion", "unclear", "other")
SCHEMA_CHANGES = (
    (
        "ALTER TABLE app.runs ADD COLUMN authors uuid[], ADD COLUMN asset_observed_at timestamptz,"
        " ADD COLUMN workflow_version text CHECK (char_length(workflow_version) BETWEEN 1 AND 60)"
    ),
    "UPDATE app.runs SET authors = ARRAY[requester]",
    (
        "ALTER TABLE app.runs ALTER COLUMN authors SET NOT NULL,"
        " ADD CONSTRAINT runs_authors_check CHECK (cardinality(authors) BETWEEN 1 AND 8)"
    ),
    "ALTER TABLE app.drafts ADD COLUMN source text NOT NULL DEFAULT 'model' CHECK (source IN ('model', 'manual'))",
    "ALTER TABLE app.run_manifests ADD COLUMN revision integer NOT NULL DEFAULT 1 CHECK (revision >= 1)",
    (
        "ALTER TABLE app.run_manifests ALTER COLUMN revision DROP DEFAULT, DROP CONSTRAINT run_manifests_pkey,"
        " ADD PRIMARY KEY (run_id, revision)"
    ),
    (
        "CREATE TABLE app.feedback ("
        " feedback_id uuid PRIMARY KEY,"
        " tenant_id uuid NOT NULL,"
        " run_id uuid NOT NULL,"
        " subject_kind text NOT NULL CHECK (subject_kind IN ('run', 'proposal', 'event')),"
        " subject_id uuid NOT NULL,"
        f" category text NOT NULL CHECK (category IN ({literal_list(FEEDBACK_CATEGORIES_0016)})),"
        " text text CHECK (char_length(text) <= 2000),"
        " author uuid NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " reviewed boolean NOT NULL DEFAULT false,"
        " CONSTRAINT feedback_tenant_run_fkey FOREIGN KEY (tenant_id, run_id) REFERENCES app.runs (tenant_id, run_id))"
    ),
    "ALTER TABLE app.feedback OWNER TO migrator",
)

# ----------------------------------------------------------------------------------------------- derived helpers
# The event payload keys (ops_core.outcomes.PAYLOAD_KEYS, frozen here): 0008's plus the feedback event's three.
PAYLOAD_KEYS_0016 = (*REV0008.PAYLOAD_KEYS_0008, "subject_kind", "subject_id", "category")
FEEDBACK_RULE = (
    "    -- T21 (ruling 8, erratum 136): a feedback event names its subject and category, and no other type does.\n"
    "    IF p_payload ?| ARRAY['subject_kind', 'subject_id', 'category'] AND p_type <> 'feedback.recorded' THEN\n"
    "        RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'feedback keys';\n"
    "    END IF;\n"
)
STATUS_RULE_0008 = (
    "        RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'status';\n    END IF;\n"
)
APPEND_EVENT_CHANGES = (
    (f"ARRAY[{REV0008.PAYLOAD_KEYS}]", f"ARRAY[{literal_list(PAYLOAD_KEYS_0016)}]"),
    (STATUS_RULE_0008, STATUS_RULE_0008 + FEEDBACK_RULE),
)
APPEND_EVENT_HELPER = _derived(REV0008.APPEND_EVENT_HELPER, APPEND_EVENT_CHANGES)

SERVER_CHECK_0009 = "    IF v_job_server IS NULL OR v_job_server <> p_server OR v_ctx.server <> p_server THEN\n"
EXECUTE_READ = (
    "    -- T21 (ruling 9, erratum 137): an execute job also holds a read handle, for the asset status it reads again\n"
    "    -- before its grant (R116); the stored server must say read too.\n"
    "    IF v_job_type = 'execute' AND p_server = 'read' AND v_ctx.server = 'read' THEN\n"
    "        v_job_server := 'read';\n"
    "    END IF;\n"
)
RESOLVE_CHANGES = ((SERVER_CHECK_0009, EXECUTE_READ + SERVER_CHECK_0009),)
RESOLVE_HANDLE = _derived(REV0009.RESOLVE_HANDLE, RESOLVE_CHANGES)

SUPERSEDES_0003 = (
    "        SELECT 1 FROM runs r WHERE r.run_id = p_supersedes_run_id AND r.tenant_id = p_tenant_id\n"
    "                               AND r.conversation_id = p_conversation_id) THEN\n"
)
SUPERSEDES_0016 = (
    "        -- T21 (erratum 138): the superseded incident is the asset's, in any conversation of its tenant\n"
    "        -- (SA:286).\n"
    "        SELECT 1 FROM runs r WHERE r.run_id = p_supersedes_run_id AND r.tenant_id = p_tenant_id\n"
    "                               AND r.asset_id = v_asset_id) THEN\n"
)
INSERT_RUN_0003 = (
    "                          asset_id, start_at, end_at, state, state_version, slot_held, next_event_seq)\n"
    "        VALUES (v_run_id, p_tenant_id, p_conversation_id, v_message_id, v_requester, p_intent,"
    " p_supersedes_run_id,\n"
    "                v_asset_id, v_start, v_end, 'QUEUED', 1, true, 0);\n"
)
INSERT_RUN_0016 = (
    "                          asset_id, start_at, end_at, state, state_version, slot_held, next_event_seq, authors)\n"
    "        VALUES (v_run_id, p_tenant_id, p_conversation_id, v_message_id, v_requester, p_intent,"
    " p_supersedes_run_id,\n"
    "                v_asset_id, v_start, v_end, 'QUEUED', 1, true, 0, ARRAY[v_requester]);\n"
)
CREATE_RUN_CHANGES = ((SUPERSEDES_0003, SUPERSEDES_0016), (INSERT_RUN_0003, INSERT_RUN_0016))
CREATE_RUN = _derived(REV0003.CREATE_RUN, CREATE_RUN_CHANGES)

# Ruling 14 (erratum 105): the read path refuses a requester whose membership the sync has not stamped in 120 s, the
# write gate's bound (0005's MEMBERSHIP_STALE), as a deferral the caller may retry.
STALE_CHECK = """\
    -- T21 (ruling 14): the same row must have been stamped by the membership sync within 120 s (the write gate's
    -- bound, revision 0005); otherwise the call is deferred, not refused for good.
    IF NOT EXISTS (SELECT 1 FROM runs r JOIN memberships m ON m.tenant_id = r.tenant_id AND m.subject = r.requester
                   WHERE r.run_id = v_handle.run_id AND m.role = 'requester' AND m.active
                     AND m.synced_at >= app.current_time() - interval '120 seconds') THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'MEMBERSHIP_STALE';
    END IF;
"""
FRESH_READ = ((REV0012.MEMBERSHIP_CHECK, REV0012.MEMBERSHIP_CHECK + STALE_CHECK),)
ASSET_SCOPE = _derived(REV0012.ASSET_SCOPE, FRESH_READ)
SEARCH_PROCEDURES_SCOPED = _derived(REV0013.SEARCH_PROCEDURES_SCOPED, FRESH_READ)

# The search's own filters (0012's `latest`, `effective`, `permitted`) and its lexical query, byte for byte.
FILTERS_0012 = _between(REV0012.SEARCH_PROCEDURES_SCOPED, "    WITH latest AS (\n", "    ), ranked AS (\n")
QUERY_0012 = _between(REV0012.SEARCH_PROCEDURES_SCOPED, "    WITH latest AS (\n", "    INTO results FROM kept k;\n")

# ------------------------------------------------------------------------------------------------- new helpers
RUN_REVISION = f"""
CREATE OR REPLACE FUNCTION app._run_revision(p_run_id uuid) RETURNS integer
{HELPER_HEADER} AS $fn$
BEGIN
    -- Ruling 1: revision N is the run's Nth request; each create_revision journals one proposal.revised.
    RETURN 1 + (SELECT count(*) FROM events e WHERE e.run_id = p_run_id AND e.type = 'proposal.revised')::integer;
END
$fn$;
ALTER FUNCTION app._run_revision(uuid) OWNER TO app_definer;
"""

ASSET_LOCK = f"""
CREATE OR REPLACE FUNCTION app._asset_lock(p_tenant_id uuid, p_asset_id text) RETURNS void
{HELPER_HEADER} AS $fn$
BEGIN
    -- SA:189: one key per (tenant, asset); the idempotency scope's two-key locks live in another space (erratum 37).
    PERFORM pg_advisory_xact_lock(hashtextextended(p_tenant_id::text || ':' || p_asset_id, 0));
END
$fn$;
ALTER FUNCTION app._asset_lock(uuid, text) OWNER TO app_definer;
"""

ASSET_GUARD = f"""
CREATE OR REPLACE FUNCTION app._asset_guard(p_tenant_id uuid, p_asset_id text, p_start_at timestamptz,
                                            p_end_at timestamptz, p_run_id uuid, p_supersedes_run_id uuid)
RETURNS TABLE (reason text, blocking_run_id uuid)
{HELPER_HEADER} AS $fn$
BEGIN
    -- AM-13 (SA:284-286), called under _asset_lock. Overlap is half-open: a < d and c < b (SA:283). Other runs of the
    -- tenant in any conversation (SA:288). (a) An unresolved action: a grant whose latest attempt is not RESOLVED,
    -- unless the operator acknowledged it (ABANDONED_UNVERIFIED, SA:130).
    SELECT r.run_id INTO blocking_run_id
    FROM runs r JOIN execution_grant g ON g.run_id = r.run_id CROSS JOIN LATERAL app._latest_attempt(g.action_id) la
    WHERE r.tenant_id = p_tenant_id AND r.asset_id = p_asset_id AND r.run_id <> p_run_id
      AND r.start_at < p_end_at AND p_start_at < r.end_at
      AND la.state <> 'RESOLVED' AND r.state <> 'ABANDONED_UNVERIFIED'
    ORDER BY r.run_id LIMIT 1;
    IF FOUND THEN
        reason := 'asset_action_unresolved';
        RETURN NEXT;
        RETURN;
    END IF;
    -- (b) A committed incident, however late its evidence arrived (R6-H5), unless the request named it (R125).
    SELECT r.run_id INTO blocking_run_id
    FROM runs r
    WHERE r.tenant_id = p_tenant_id AND r.asset_id = p_asset_id AND r.run_id <> p_run_id
      AND r.start_at < p_end_at AND p_start_at < r.end_at
      AND r.run_id IS DISTINCT FROM p_supersedes_run_id
      AND (r.state = 'SUCCEEDED'
           OR EXISTS (SELECT 1 FROM events e WHERE e.run_id = r.run_id AND e.type = 'action.late_evidence'
                                                AND e.payload->>'outcome' = 'SUCCEEDED'))
    ORDER BY r.run_id LIMIT 1;
    IF FOUND THEN
        reason := 'asset_incident_exists';
        RETURN NEXT;
    END IF;
END
$fn$;
ALTER FUNCTION app._asset_guard(uuid, text, timestamptz, timestamptz, uuid, uuid) OWNER TO app_definer;
"""

CITED_PERMITTED = f"""
CREATE OR REPLACE FUNCTION app._cited_permitted(p_tenant_id uuid, p_evidence_ids text[])
RETURNS TABLE (evidence_id text, version text, content_sha256 text)
{HELPER_HEADER} AS $fn$
#variable_conflict use_column
DECLARE
    v_now timestamptz := app.current_time();
    p_asset_type text := NULL;  -- the search's family filter, off: a cited section counts in any family
BEGIN
    -- BS:425 and ruling 7: the search's own filters (revision 0012's text, byte for byte), so a section the search
    -- would no longer return (revoked, expired or retired) is not permitted here either.
    RETURN QUERY
{FILTERS_0012}    )
    SELECT c.evidence_id, c.version, c.content_sha256
    FROM chunks c JOIN permitted p USING (tenant_id, document_id, version)
    WHERE c.tenant_id = p_tenant_id AND c.evidence_id = ANY (p_evidence_ids);
END
$fn$;
ALTER FUNCTION app._cited_permitted(uuid, text[]) OWNER TO app_definer;
"""

EXPIRE = f"""
CREATE OR REPLACE FUNCTION app._expire(p_run_id uuid) RETURNS text
{HELPER_HEADER} AS $fn$
DECLARE
    v_run runs%ROWTYPE;
    v_expires timestamptz;
BEGIN
    SELECT * INTO v_run FROM runs r WHERE r.run_id = p_run_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'run';
    END IF;
    IF v_run.state NOT IN ('AWAITING_APPROVAL', 'APPROVED') THEN
        RETURN v_run.state;
    END IF;
    SELECT p.expires_at INTO v_expires FROM proposals p WHERE p.proposal_id = v_run.active_proposal_id;
    -- SA:457, compared after the lock on the application clock (SA:157): an APPROVED run expires before its grant
    -- too (SA:140), and nothing extends an expiry (BS:684).
    IF v_expires IS NULL OR v_expires >= app.current_time() THEN
        RETURN v_run.state;
    END IF;
    PERFORM app._transition(p_run_id, 'BLOCKED_REVIEW', 'expire_proposal', 'expired', NULL, 'review.blocked',
                            jsonb_build_object('proposal_id', v_run.active_proposal_id, 'reason', 'expired',
                                               'message',
                                               'the proposal expired; a revision and a new review are needed'));
    RETURN 'BLOCKED_REVIEW';
END
$fn$;
ALTER FUNCTION app._expire(uuid) OWNER TO app_definer;
"""

# ---------------------------------------------------------------------------------------------- definers
EXPIRE_PROPOSAL = f"""
CREATE OR REPLACE FUNCTION app.expire_proposal(p_run_id uuid) RETURNS text
{HEADER} AS $fn$
BEGIN
    PERFORM app._authority('expire_proposal', ARRAY['sweeper', 'api']);
    IF p_run_id IS NULL THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'INVALID_ARGUMENT';
    END IF;
    PERFORM app._tenant_of_run(p_run_id);
    RETURN app._expire(p_run_id);
END
$fn$;
ALTER FUNCTION app.expire_proposal(uuid) OWNER TO app_definer;
"""

FREEZE_PROPOSAL = f"""
CREATE OR REPLACE FUNCTION app.freeze_proposal(p_run_id uuid, p_draft_id uuid, p_payload_canonical bytea,
                                               p_expires_at timestamptz)
RETURNS TABLE (proposal_id uuid, revision integer, state text, reason text, state_version integer)
{HEADER} AS $fn$
DECLARE
    v_tenant uuid;
    v_asset text;
    v_run runs%ROWTYPE;
    v_draft drafts%ROWTYPE;
    v_sha text := encode(sha256(p_payload_canonical), 'hex');
    v_payload jsonb;
    v_proposal_id uuid;
    v_revision integer;
    v_reason text;
    v_blocking uuid;
BEGIN
    PERFORM app._authority('freeze_proposal', ARRAY['worker']);
    v_tenant := app._tenant_of_run(p_run_id);
    -- SA:189: the asset guard's lock before the run's (the worker's unit took it before its fence; it is re-entrant).
    SELECT r.asset_id INTO v_asset FROM runs r WHERE r.run_id = p_run_id;
    PERFORM app._asset_lock(v_tenant, v_asset);
    SELECT * INTO v_run FROM runs r WHERE r.run_id = p_run_id FOR UPDATE;
    IF v_run.state <> 'DRAFTING' THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003',
                                                 DETAIL = format('run %s is %s', p_run_id, v_run.state);
    END IF;
    IF v_run.intent = 'answer_only' THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'ANSWER_ONLY';
    END IF;
    SELECT * INTO v_draft FROM drafts d WHERE d.id = p_draft_id AND d.run_id = p_run_id AND d.validated;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'draft';
    END IF;
    -- The bytes stored are the bytes validated (SA:453): the hash is recomputed here over what arrived.
    IF v_draft.draft_sha256 <> v_sha THEN
        RAISE EXCEPTION 'hash_mismatch' USING ERRCODE = 'OC007', DETAIL = 'draft';
    END IF;
    v_payload := convert_from(p_payload_canonical, 'UTF8')::jsonb;
    IF (v_payload->>'run_id') IS DISTINCT FROM p_run_id::text
       OR (v_payload->>'tenant_id') IS DISTINCT FROM v_tenant::text THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'PAYLOAD_RUN_MISMATCH';
    END IF;
    -- supersedes_run_id is a run field written by create_run or create_revision (SA:154); the document carries it.
    IF (v_payload->>'supersedes_run_id') IS DISTINCT FROM v_run.supersedes_run_id::text THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'SUPERSEDES_MISMATCH';
    END IF;
    -- Ruling 1: the run's current revision, which no proposal of the run has frozen yet.
    v_revision := app._run_revision(p_run_id);
    IF (v_payload->>'revision')::integer IS DISTINCT FROM v_revision
       OR EXISTS (SELECT 1 FROM proposals p WHERE p.run_id = p_run_id AND p.revision >= v_revision) THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003', DETAIL = 'revision';
    END IF;
    -- Ruling 18: the version the worker recorded at the run's first claim (BS:342).
    IF (v_payload->>'workflow_version') IS DISTINCT FROM v_run.workflow_version THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'WORKFLOW_VERSION';
    END IF;
    -- Ruling 5: the hashed expiry is the stored one, set on the application clock and never beyond the 15 minutes.
    IF p_expires_at IS NULL OR (v_payload->>'expires_at')::timestamptz IS DISTINCT FROM p_expires_at
       OR p_expires_at <= app.current_time() OR p_expires_at > app.current_time() + {EXPIRY_BOUND} THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'EXPIRY';
    END IF;
    -- AM-13: a refusal freezes nothing and commits BLOCKED_REVIEW, naming the blocking run (ruling 10).
    SELECT g.reason, g.blocking_run_id INTO v_reason, v_blocking
    FROM app._asset_guard(v_tenant, v_run.asset_id, v_run.start_at, v_run.end_at, p_run_id,
                          v_run.supersedes_run_id) g;
    IF v_reason IS NOT NULL THEN
        state_version := app._transition(p_run_id, 'BLOCKED_REVIEW', 'freeze_proposal', v_reason, NULL,
                                         'review.blocked',
                                         jsonb_build_object('reason', v_reason,
                                                            'message', format('blocked by run %s', v_blocking)));
        revision := v_revision;
        state := 'BLOCKED_REVIEW';
        reason := v_reason;
        RETURN NEXT;
        RETURN;
    END IF;
    v_proposal_id := (v_payload->>'proposal_id')::uuid;
    -- Ruling 4: every content author (SA:453, SA:539), kept outside the hash.
    INSERT INTO proposals (proposal_id, tenant_id, run_id, revision, draft_id, payload, payload_canonical,
                           payload_sha256, canonicalization_version, authored_by, expires_at, frozen_at)
    VALUES (v_proposal_id, v_tenant, p_run_id, v_revision, p_draft_id, v_payload, p_payload_canonical, v_sha, 1,
            v_run.authors, p_expires_at, app.current_time());
    UPDATE runs SET active_proposal_id = v_proposal_id WHERE runs.run_id = p_run_id;
    state_version := app._transition(p_run_id, 'AWAITING_APPROVAL', 'freeze_proposal', NULL, NULL, 'proposal.ready',
                                     jsonb_build_object('proposal_id', v_proposal_id));
    proposal_id := v_proposal_id;
    revision := v_revision;
    state := 'AWAITING_APPROVAL';
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION app.freeze_proposal(uuid, uuid, bytea, timestamptz) OWNER TO app_definer;
"""

RECORD_DECISION = f"""
CREATE OR REPLACE FUNCTION app.record_decision(p_tenant_id uuid, p_proposal_id uuid, p_reviewer uuid,
                                               p_expected_revision integer, p_expected_payload_sha256 text,
                                               p_decision text, p_reason text, p_idempotency_key text)
RETURNS TABLE (run_id uuid, state text, state_version integer)
{HEADER} AS $fn$
DECLARE
    v_proposal proposals%ROWTYPE;
    v_run runs%ROWTYPE;
BEGIN
    PERFORM app._authority('record_decision', ARRAY['api']);
    -- A NULL would make every comparison below UNKNOWN and slip past its guard, so refuse before any read.
    IF p_tenant_id IS NULL OR p_proposal_id IS NULL OR p_reviewer IS NULL OR p_decision IS NULL
       OR p_expected_revision IS NULL OR p_expected_payload_sha256 IS NULL
       OR p_decision NOT IN ('approve', 'reject') THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'INVALID_ARGUMENT';
    END IF;
    -- The API is the identity trust anchor (SA:454): tenant and reviewer are arguments it has authenticated.
    PERFORM set_config('app.tenant_id', p_tenant_id::text, true);
    SELECT * INTO v_proposal FROM proposals p WHERE p.proposal_id = p_proposal_id AND p.tenant_id = p_tenant_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'proposal';
    END IF;
    SELECT * INTO v_run FROM runs r WHERE r.run_id = v_proposal.run_id FOR UPDATE;
    -- Independence first (BS:466, SA:539): a current reviewer who is neither requester nor content author is refused
    -- whatever the run's state, and the API never records that refusal (BS:301).
    IF NOT EXISTS (SELECT 1 FROM memberships m WHERE m.tenant_id = p_tenant_id AND m.subject = p_reviewer
                                                     AND m.role = 'reviewer' AND m.active) THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'NOT_REVIEWER';
    END IF;
    IF p_reviewer = v_run.requester OR p_reviewer = ANY (v_proposal.authored_by) THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'SELF_REVIEW';
    END IF;
    -- Ruling 3: every rule under the runs lock, each its own code. First decision wins (UNIQUE (proposal_id)).
    IF EXISTS (SELECT 1 FROM decisions d WHERE d.proposal_id = p_proposal_id) THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003', DETAIL = 'ALREADY_DECIDED';
    END IF;
    IF v_proposal.revision IS DISTINCT FROM p_expected_revision
       OR v_run.active_proposal_id IS DISTINCT FROM p_proposal_id THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003', DETAIL = 'STALE_REVISION';
    END IF;
    IF v_proposal.payload_sha256 IS DISTINCT FROM p_expected_payload_sha256 THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003', DETAIL = 'STALE_HASH';
    END IF;
    -- Ruling 5: the API's own unit committed BLOCKED_REVIEW(expired) first; a proposal that expired since is refused
    -- the same way, and the sweeper commits its block (DEV-008: the 409 never extends the expiry).
    IF (v_run.state = 'BLOCKED_REVIEW' AND v_run.reason = 'expired')
       OR (v_run.state = 'AWAITING_APPROVAL' AND v_proposal.expires_at < app.current_time()) THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003', DETAIL = 'EXPIRED';
    END IF;
    IF v_run.state <> 'AWAITING_APPROVAL' THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003', DETAIL = 'STALE_REVISION';
    END IF;
    BEGIN
        INSERT INTO decisions (decision_id, tenant_id, proposal_id, reviewer, decision, reason, expected_payload_sha256,
                               idempotency_key, decided_at)
        VALUES (gen_random_uuid(), p_tenant_id, p_proposal_id, p_reviewer, p_decision, p_reason,
                p_expected_payload_sha256, p_idempotency_key, app.current_time());
    EXCEPTION WHEN unique_violation THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003', DETAIL = 'ALREADY_DECIDED';
    END;
    run_id := v_run.run_id;
    IF p_decision = 'approve' THEN
        INSERT INTO jobs (id, type, tenant_id, run_id, dedup_key, available_at)
        VALUES (gen_random_uuid(), 'execute', p_tenant_id, v_run.run_id, p_proposal_id::text, app.current_time())
        ON CONFLICT (dedup_key) DO NOTHING;
        state := 'APPROVED';
        state_version := app._transition(v_run.run_id, 'APPROVED', 'record_decision', NULL, NULL, 'approval.recorded',
                                         jsonb_build_object('proposal_id', p_proposal_id));
    ELSE
        state := 'REJECTED';
        state_version := app._transition(v_run.run_id, 'REJECTED', 'record_decision', 'rejected', NULL, 'run.rejected',
                                         jsonb_build_object('proposal_id', p_proposal_id));
    END IF;
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION app.record_decision(uuid, uuid, uuid, integer, text, text, text, text) OWNER TO app_definer;
"""

CREATE_REVISION = f"""
CREATE OR REPLACE FUNCTION app.create_revision(p_tenant_id uuid, p_run_id uuid, p_expected_version integer,
                                               p_author uuid, p_supersedes_run_id uuid)
RETURNS TABLE (run_id uuid, state_version integer, revision integer)
{HEADER} AS $fn$
DECLARE
    v_run runs%ROWTYPE;
    v_next integer;
    v_authors uuid[];
    v_constraint text;
BEGIN
    PERFORM app._authority('create_revision', ARRAY['api']);
    IF p_tenant_id IS NULL OR p_run_id IS NULL OR p_expected_version IS NULL OR p_author IS NULL THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'INVALID_ARGUMENT';
    END IF;
    PERFORM set_config('app.tenant_id', p_tenant_id::text, true);
    SELECT * INTO v_run FROM runs r WHERE r.run_id = p_run_id AND r.tenant_id = p_tenant_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'run';
    END IF;
    -- Ruling 2: any active requester of the tenant; the API is the identity anchor and checked the role too.
    IF NOT EXISTS (SELECT 1 FROM memberships m WHERE m.tenant_id = p_tenant_id AND m.subject = p_author
                                                     AND m.role = 'requester' AND m.active) THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'NOT_REQUESTER';
    END IF;
    -- SA:167 (R090): once a grant exists the run is past revising, whatever the version says.
    IF EXISTS (SELECT 1 FROM execution_grant g WHERE g.run_id = p_run_id) THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'GRANT_EXISTS';
    END IF;
    IF v_run.state NOT IN ('AWAITING_APPROVAL', 'APPROVED', 'BLOCKED_REVIEW')
       OR v_run.state_version <> p_expected_version THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003',
            DETAIL = format('run %s is %s at version %s', p_run_id, v_run.state, v_run.state_version);
    END IF;
    -- SA:286 (erratum 138): a named run of the same tenant and asset, never the run itself.
    IF p_supersedes_run_id IS NOT NULL AND (p_supersedes_run_id = p_run_id OR NOT EXISTS (
        SELECT 1 FROM runs r WHERE r.run_id = p_supersedes_run_id AND r.tenant_id = p_tenant_id
                               AND r.asset_id = v_run.asset_id)) THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'supersedes_run_id';
    END IF;
    -- Ruling 4: the author joins the run's content authors; Proposal.authored_by holds at most eight.
    v_authors := CASE WHEN p_author = ANY (v_run.authors) THEN v_run.authors ELSE v_run.authors || p_author END;
    IF cardinality(v_authors) > 8 THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'AUTHOR_LIMIT';
    END IF;
    -- R120 (SA:139): BLOCKED_REVIEW freed the slot, so another run may hold it now. Checked here under the run's lock;
    -- the unique index below is the backstop for an admission that commits between this read and the transition.
    IF v_run.state = 'BLOCKED_REVIEW' AND EXISTS (SELECT 1 FROM runs o WHERE o.conversation_id = v_run.conversation_id
                                                                         AND o.run_id <> p_run_id AND o.slot_held) THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'SLOT_OCCUPIED';
    END IF;
    v_next := app._run_revision(p_run_id) + 1;
    -- Ruling 1: the revision is a new graph thread from QUEUED, so the stored checkpoint (the old thread's) goes, and
    -- with it the old approval: the active proposal is cleared until the new revision freezes (BS:274).
    UPDATE runs SET authors = v_authors, supersedes_run_id = p_supersedes_run_id, checkpoint_id = NULL,
                    active_proposal_id = NULL
    WHERE runs.run_id = p_run_id;
    BEGIN
        state_version := app._transition(p_run_id, 'QUEUED', 'create_revision', NULL, NULL, 'proposal.revised',
                                         jsonb_build_object('message', format('revision %s requested', v_next))
                                         || CASE WHEN v_run.active_proposal_id IS NULL THEN '{{}}'::jsonb
                                                 ELSE jsonb_build_object('proposal_id', v_run.active_proposal_id) END);
    EXCEPTION WHEN unique_violation THEN
        GET STACKED DIAGNOSTICS v_constraint = CONSTRAINT_NAME;
        IF v_constraint = 'runs_one_active_per_conversation' THEN
            RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'SLOT_OCCUPIED';
        END IF;
        RAISE;
    END;
    -- SA:455's dedup key run_id:revision; never ON CONFLICT: a fresh revision's key cannot exist, and a silent no-op
    -- would leave the run QUEUED without a wake-up.
    INSERT INTO jobs (id, type, tenant_id, run_id, dedup_key, available_at)
    VALUES (gen_random_uuid(), 'investigate', p_tenant_id, p_run_id, format('%s:%s', p_run_id, v_next),
            app.current_time());
    run_id := p_run_id;
    revision := v_next;
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION app.create_revision(uuid, uuid, integer, uuid, uuid) OWNER TO app_definer;
"""

REQUEST_CANCEL = f"""
CREATE OR REPLACE FUNCTION app.request_cancel(p_tenant_id uuid, p_run_id uuid, p_expected_version integer,
                                              p_actor uuid)
RETURNS TABLE (run_id uuid, state text, state_version integer, grant_exists boolean, attempt_state text)
{HEADER} AS $fn$
DECLARE
    v_run runs%ROWTYPE;
    v_grant execution_grant%ROWTYPE;
BEGIN
    PERFORM app._authority('request_cancel', ARRAY['api']);
    IF p_tenant_id IS NULL OR p_run_id IS NULL OR p_expected_version IS NULL OR p_actor IS NULL THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'INVALID_ARGUMENT';
    END IF;
    PERFORM set_config('app.tenant_id', p_tenant_id::text, true);
    SELECT * INTO v_run FROM runs r WHERE r.run_id = p_run_id AND r.tenant_id = p_tenant_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'run';
    END IF;
    -- Ruling 12: the run's own requester or any current reviewer of the tenant.
    IF NOT EXISTS (SELECT 1 FROM memberships m WHERE m.tenant_id = p_tenant_id AND m.subject = p_actor AND m.active
                                                     AND ((m.role = 'requester' AND p_actor = v_run.requester)
                                                          OR m.role = 'reviewer')) THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'NOT_CANCELLER';
    END IF;
    run_id := p_run_id;
    SELECT * INTO v_grant FROM execution_grant g WHERE g.run_id = p_run_id;
    IF FOUND THEN
        -- SA:458: after the grant only the flag is set; mark_sent's re-check under this lock decides (SA:230-232,
        -- R118), and the answer reports the attempt, never an undo (BS:276).
        IF NOT v_run.cancel_requested THEN
            UPDATE runs SET cancel_requested = true, cancel_requested_at = app.current_time()
            WHERE runs.run_id = p_run_id;
        END IF;
        state := v_run.state;
        state_version := v_run.state_version;
        grant_exists := true;
        SELECT la.state INTO attempt_state FROM app._latest_attempt(v_grant.action_id) la;
        RETURN NEXT;
        RETURN;
    END IF;
    -- Before a grant: any pre-grant non-terminal state, BLOCKED_REVIEW included (contract erratum 5, erratum 139).
    IF v_run.state_version <> p_expected_version
       OR v_run.state NOT IN ('QUEUED', 'AWAITING_INPUT', 'RETRIEVING', 'DRAFTING', 'AWAITING_APPROVAL', 'APPROVED',
                              'BLOCKED_REVIEW') THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003',
            DETAIL = format('run %s is %s at version %s', p_run_id, v_run.state, v_run.state_version);
    END IF;
    UPDATE runs SET cancel_requested = true, cancel_requested_at = app.current_time() WHERE runs.run_id = p_run_id;
    state_version := app._transition(p_run_id, 'CANCELLED', 'request_cancel', NULL, NULL, 'run.cancelled',
                                     '{{}}'::jsonb);
    state := 'CANCELLED';
    grant_exists := false;
    attempt_state := NULL;
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION app.request_cancel(uuid, uuid, integer, uuid) OWNER TO app_definer;
"""

# Shared by prepare_manual_proposal and create_manual_proposal: the author and the run's readiness for a person's
# proposal (ruling 7), checked under the asset lock and the run's lock.
MANUAL_READY = """\
    -- Ruling 7 (SA:542 on the API): an active requester or reviewer of the tenant authors it.
    IF NOT EXISTS (SELECT 1 FROM memberships m WHERE m.tenant_id = p_tenant_id AND m.subject = p_author AND m.active
                                                     AND m.role IN ('requester', 'reviewer')) THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'NOT_AUTHOR';
    END IF;
    -- The state the worker leaves when the model could not draft: DRAFTING, no stored checkpoint, no live lease
    -- (erratum 134). A run a worker is still drafting has one or the other.
    IF v_run.state <> 'DRAFTING' OR v_run.intent <> 'investigate' OR v_run.checkpoint_id IS NOT NULL
       OR v_run.workflow_version IS NULL
       OR EXISTS (SELECT 1 FROM run_lease l WHERE l.run_id = p_run_id AND l.lease_until > app.current_time()) THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003',
            DETAIL = format('run %s does not wait for a manual proposal', p_run_id);
    END IF;
    v_authors := CASE WHEN p_author = ANY (v_run.authors) THEN v_run.authors ELSE v_run.authors || p_author END;
    IF cardinality(v_authors) > 8 THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'AUTHOR_LIMIT';
    END IF;
"""
MANUAL_LOCKS = """\
    PERFORM set_config('app.tenant_id', p_tenant_id::text, true);
    SELECT r.asset_id INTO v_asset FROM runs r WHERE r.run_id = p_run_id AND r.tenant_id = p_tenant_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'run';
    END IF;
    -- SA:189: the asset guard's lock first, after the API unit's idempotency lock (erratum 37).
    PERFORM app._asset_lock(p_tenant_id, v_asset);
    SELECT * INTO v_run FROM runs r WHERE r.run_id = p_run_id FOR UPDATE;
"""

PREPARE_MANUAL_PROPOSAL = f"""
CREATE OR REPLACE FUNCTION app.prepare_manual_proposal(p_tenant_id uuid, p_run_id uuid, p_author uuid,
                                                       p_evidence_ids text[])
RETURNS TABLE (revision integer, workflow_version text, supersedes_run_id uuid, asset_id text,
               start_at timestamptz, end_at timestamptz, expires_at timestamptz, snapshots jsonb)
{HEADER} AS $fn$
DECLARE
    v_asset text;
    v_run runs%ROWTYPE;
    v_authors uuid[];
BEGIN
    PERFORM app._authority('prepare_manual_proposal', ARRAY['api']);
    IF p_tenant_id IS NULL OR p_run_id IS NULL OR p_author IS NULL OR p_evidence_ids IS NULL
       OR cardinality(p_evidence_ids) NOT BETWEEN 1 AND 8 THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'INVALID_ARGUMENT';
    END IF;
{MANUAL_LOCKS}{MANUAL_READY}\
    -- Note 4: every cited section is a permitted section of the caller's tenant, or the request is 404
    -- with nothing written (the snapshots the proposal binds, BS:256).
    SELECT coalesce(jsonb_agg(jsonb_build_object('evidence_id', c.evidence_id, 'content_sha256', c.content_sha256,
                                                 'version', c.version) ORDER BY c.evidence_id COLLATE "C"), '[]'::jsonb)
    INTO snapshots FROM app._cited_permitted(p_tenant_id, p_evidence_ids) c;
    IF jsonb_array_length(snapshots) <> (SELECT count(DISTINCT e) FROM unnest(p_evidence_ids) e) THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'evidence';
    END IF;
    revision := app._run_revision(p_run_id);
    workflow_version := v_run.workflow_version;
    supersedes_run_id := v_run.supersedes_run_id;
    asset_id := v_run.asset_id;
    start_at := v_run.start_at;
    end_at := v_run.end_at;
    -- Ruling 5: the application clock, whole seconds, BS:559's fifteen minutes.
    expires_at := date_trunc('second', app.current_time()) + interval '15 minutes';
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION app.prepare_manual_proposal(uuid, uuid, uuid, text[]) OWNER TO app_definer;
"""

CREATE_MANUAL_PROPOSAL = f"""
CREATE OR REPLACE FUNCTION app.create_manual_proposal(p_tenant_id uuid, p_run_id uuid, p_payload_canonical bytea,
                                                      p_author uuid)
RETURNS TABLE (proposal_id uuid, revision integer, state text, reason text, state_version integer,
               blocking_run_id uuid)
{HEADER} AS $fn$
DECLARE
    v_asset text;
    v_run runs%ROWTYPE;
    v_authors uuid[];
    v_sha text := encode(sha256(p_payload_canonical), 'hex');
    v_payload jsonb;
    v_draft_id uuid := gen_random_uuid();
    v_proposal_id uuid;
    v_revision integer;
    v_reason text;
    v_blocking uuid;
    v_expires timestamptz;
BEGIN
    PERFORM app._authority('create_manual_proposal', ARRAY['api']);
    IF p_tenant_id IS NULL OR p_run_id IS NULL OR p_author IS NULL OR p_payload_canonical IS NULL THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'INVALID_ARGUMENT';
    END IF;
{MANUAL_LOCKS}{MANUAL_READY}    v_payload := convert_from(p_payload_canonical, 'UTF8')::jsonb;
    IF (v_payload->>'run_id') IS DISTINCT FROM p_run_id::text
       OR (v_payload->>'tenant_id') IS DISTINCT FROM p_tenant_id::text
       OR (v_payload->>'action') IS DISTINCT FROM 'create_incident'
       OR (v_payload->>'destination') IS DISTINCT FROM 'synthetic-incidents' THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'PAYLOAD_RUN_MISMATCH';
    END IF;
    -- Note 4: the run's own asset, the one its tenant's retrieval found (SA:154: fixed for the run).
    IF (v_payload->>'asset_id') IS DISTINCT FROM v_run.asset_id THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'asset';
    END IF;
    IF (v_payload->>'start_at')::timestamptz IS DISTINCT FROM v_run.start_at
       OR (v_payload->>'end_at')::timestamptz IS DISTINCT FROM v_run.end_at THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'INTERVAL';
    END IF;
    IF (v_payload->>'supersedes_run_id') IS DISTINCT FROM v_run.supersedes_run_id::text THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'SUPERSEDES_MISMATCH';
    END IF;
    -- Ruling 7 and 18: a person's proposal records the run's workflow version and the prompt version "manual".
    IF (v_payload->>'workflow_version') IS DISTINCT FROM v_run.workflow_version
       OR (v_payload->>'prompt_version') IS DISTINCT FROM 'manual' THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'WORKFLOW_VERSION';
    END IF;
    v_revision := app._run_revision(p_run_id);
    IF (v_payload->>'revision')::integer IS DISTINCT FROM v_revision
       OR EXISTS (SELECT 1 FROM proposals p WHERE p.run_id = p_run_id AND p.revision >= v_revision) THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003', DETAIL = 'revision';
    END IF;
    v_expires := (v_payload->>'expires_at')::timestamptz;
    IF v_expires IS NULL OR v_expires <= app.current_time() OR v_expires > app.current_time() + {EXPIRY_BOUND} THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'EXPIRY';
    END IF;
    -- Note 4 and BS:256: the snapshots are exactly the cited sections as the tenant's corpus permits them now.
    IF (SELECT coalesce(jsonb_agg(jsonb_build_object('evidence_id', c.evidence_id, 'content_sha256', c.content_sha256,
                                                     'version', c.version) ORDER BY c.evidence_id COLLATE "C"),
                        '[]'::jsonb)
        FROM app._cited_permitted(p_tenant_id, ARRAY(SELECT jsonb_array_elements_text(v_payload->'evidence_refs'))) c)
       IS DISTINCT FROM v_payload->'source_snapshots' THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'evidence';
    END IF;
    UPDATE runs SET authors = v_authors WHERE runs.run_id = p_run_id;
    -- The draft row a frozen proposal references (ruling 7): the person's bytes, validated here, never the model's.
    INSERT INTO drafts (id, tenant_id, run_id, draft_sha256, validated, kind, source)
    VALUES (v_draft_id, p_tenant_id, p_run_id, v_sha, true, 'proposal', 'manual');
    SELECT g.reason, g.blocking_run_id INTO v_reason, v_blocking
    FROM app._asset_guard(p_tenant_id, v_run.asset_id, v_run.start_at, v_run.end_at, p_run_id,
                          v_run.supersedes_run_id) g;
    IF v_reason IS NOT NULL THEN
        state_version := app._transition(p_run_id, 'BLOCKED_REVIEW', 'create_manual_proposal', v_reason, NULL,
                                         'review.blocked',
                                         jsonb_build_object('reason', v_reason,
                                                            'message', format('blocked by run %s', v_blocking)));
        revision := v_revision;
        state := 'BLOCKED_REVIEW';
        reason := v_reason;
        blocking_run_id := v_blocking;
        RETURN NEXT;
        RETURN;
    END IF;
    v_proposal_id := (v_payload->>'proposal_id')::uuid;
    INSERT INTO proposals (proposal_id, tenant_id, run_id, revision, draft_id, payload, payload_canonical,
                           payload_sha256, canonicalization_version, authored_by, expires_at, frozen_at)
    VALUES (v_proposal_id, p_tenant_id, p_run_id, v_revision, v_draft_id, v_payload, p_payload_canonical, v_sha, 1,
            v_authors, v_expires, app.current_time());
    UPDATE runs SET active_proposal_id = v_proposal_id WHERE runs.run_id = p_run_id;
    state_version := app._transition(p_run_id, 'AWAITING_APPROVAL', 'create_manual_proposal', NULL, NULL,
                                     'proposal.ready', jsonb_build_object('proposal_id', v_proposal_id));
    proposal_id := v_proposal_id;
    revision := v_revision;
    state := 'AWAITING_APPROVAL';
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION app.create_manual_proposal(uuid, uuid, bytea, uuid) OWNER TO app_definer;
"""

GRANT_EXECUTION = f"""
CREATE OR REPLACE FUNCTION app.grant_execution(p_raw_handle text, p_client_azp text, p_proposal_id uuid)
RETURNS TABLE ({GRANT_COLUMNS}, refusal text)
{HEADER} AS $fn$
DECLARE
    v_handle_run uuid;
    v_tenant uuid;
    v_asset text;
    v_handle record;
    v_run runs%ROWTYPE;
    v_proposal proposals%ROWTYPE;
    v_grant execution_grant%ROWTYPE;
    v_decision decisions%ROWTYPE;
    v_action_id uuid;
    v_reason text;
    v_message text;
    v_blocking uuid;
BEGIN
    PERFORM app._authority('grant_execution', ARRAY['mcp_exec']);
    IF p_proposal_id IS NULL THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'INVALID_ARGUMENT';
    END IF;
    -- SA:189, SA:462: the asset guard's lock first. The handle's run and its fixed asset are plain reads before it;
    -- an unknown handle takes no lock, and _resolve_handle below refuses it as every other bad handle (SA:357).
    SELECT ic.run_id INTO v_handle_run FROM invocation_context ic
    WHERE ic.handle_sha256 = encode(sha256(convert_to(p_raw_handle, 'UTF8')), 'hex');
    IF v_handle_run IS NOT NULL THEN
        v_tenant := app._tenant_of_run(v_handle_run);
        SELECT r.asset_id INTO v_asset FROM runs r WHERE r.run_id = v_handle_run;
        PERFORM app._asset_lock(v_tenant, v_asset);
    END IF;
    SELECT * INTO v_handle FROM app._resolve_handle(p_raw_handle, p_client_azp, 'write');
    SELECT * INTO v_run FROM runs r WHERE r.run_id = v_handle.run_id FOR UPDATE;
    SELECT * INTO v_grant FROM execution_grant g WHERE g.run_id = v_handle.run_id;
    IF FOUND THEN
        -- UNIQUE (run_id): one grant per run, ever (SA:167); a replay finds the grant it already has.
        IF v_grant.proposal_id IS DISTINCT FROM p_proposal_id THEN
            RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'OTHER_PROPOSAL';
        END IF;
        RETURN QUERY SELECT g.*, NULL::text FROM app._grant_row(v_grant.action_id) g;
        RETURN;
    END IF;
    -- The binding refusals raise and commit nothing (ruling 9): SA:538's run binding (R100), the state, the approval.
    SELECT * INTO v_proposal FROM proposals p WHERE p.proposal_id = p_proposal_id AND p.run_id = v_handle.run_id
                                                AND p.tenant_id = v_handle.tenant_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'PROPOSAL_NOT_IN_RUN';
    END IF;
    IF v_run.state <> 'APPROVED' OR v_run.active_proposal_id IS DISTINCT FROM p_proposal_id THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'NOT_ACTIVE_APPROVED';
    END IF;
    SELECT * INTO v_decision FROM decisions d WHERE d.proposal_id = p_proposal_id AND d.decision = 'approve';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'NO_APPROVAL';
    END IF;
    -- The approval named exactly these bytes (SA:454's hash, checked again where it authorizes).
    IF v_decision.expected_payload_sha256 IS DISTINCT FROM v_proposal.payload_sha256 THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'HASH_MISMATCH';
    END IF;
    IF v_run.cancel_requested THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'CANCELLED';
    END IF;
    -- The committed refusals (ruling 9, AM-10 SA:140): each moves the run to BLOCKED_REVIEW and returns its reason.
    IF v_proposal.expires_at < app.current_time() THEN
        PERFORM app._expire(v_handle.run_id);  -- SA:457 internally; it journals its own review.blocked
        v_reason := 'expired';
    ELSIF NOT EXISTS (SELECT 1 FROM memberships m WHERE m.tenant_id = v_handle.tenant_id
                                                      AND m.subject = v_run.requester AND m.active)
          OR NOT EXISTS (SELECT 1 FROM memberships m WHERE m.tenant_id = v_handle.tenant_id
                                                         AND m.subject = v_decision.reviewer
                                                         AND m.role = 'reviewer' AND m.active) THEN
        -- BS:178: requester and reviewer are re-read here (R045); the sync deactivates a disabled user (R086).
        v_reason := 'authority_revoked';
        v_message := 'the requester or the reviewer is no longer an active member';
    ELSE
        -- T11 review note 2: active is only as good as the last sync; without one in 120 s the gate defers.
        IF NOT EXISTS (SELECT 1 FROM memberships m WHERE m.tenant_id = v_handle.tenant_id
                                                         AND m.subject = v_run.requester AND m.active
                                                         AND m.synced_at >= app.current_time() - interval '120 seconds')
           OR NOT EXISTS (SELECT 1 FROM memberships m WHERE m.tenant_id = v_handle.tenant_id
                                                            AND m.subject = v_decision.reviewer
                                                            AND m.role = 'reviewer' AND m.active
                                                            AND m.synced_at >= app.current_time()
                                                                               - interval '120 seconds') THEN
            RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'MEMBERSHIP_STALE';
        END IF;
        -- BS:425: every cited source still approved and effective, at the version and hash the proposal froze.
        IF EXISTS (SELECT 1 FROM jsonb_array_elements(coalesce(v_proposal.payload->'source_snapshots', '[]'::jsonb)) s
                   WHERE NOT EXISTS (SELECT 1 FROM app._cited_permitted(v_handle.tenant_id, ARRAY[s->>'evidence_id']) c
                                     WHERE c.content_sha256 = s->>'content_sha256' AND c.version = s->>'version')) THEN
            v_reason := 'stale_evidence';
            v_message := 'a cited source is no longer approved and effective';
        -- R116 (BS:476): the asset status observed no more than five minutes ago.
        ELSIF v_run.asset_observed_at IS NULL
              OR v_run.asset_observed_at < app.current_time() - interval '5 minutes' THEN
            v_reason := 'stale_evidence';
            v_message := 'the asset status observation is older than five minutes';
        ELSE
            SELECT g.reason, g.blocking_run_id INTO v_reason, v_blocking
            FROM app._asset_guard(v_handle.tenant_id, v_run.asset_id, v_run.start_at, v_run.end_at, v_handle.run_id,
                                  v_run.supersedes_run_id) g;
            v_message := format('blocked by run %s', v_blocking);
        END IF;
    END IF;
    IF v_reason IS NOT NULL THEN
        IF v_reason <> 'expired' THEN
            PERFORM app._transition(v_handle.run_id, 'BLOCKED_REVIEW', 'grant_execution', v_reason, NULL,
                                    'review.blocked',
                                    jsonb_build_object('proposal_id', p_proposal_id, 'reason', v_reason,
                                                       'message', v_message));
        END IF;
        RETURN QUERY SELECT NULL::uuid, v_handle.run_id, p_proposal_id, v_handle.tenant_id, v_handle.conversation_id,
                            NULL::text, NULL::bytea, NULL::text, NULL::jsonb, v_reason;
        RETURN;
    END IF;
    v_action_id := gen_random_uuid();  -- random inside the gate (SA:168), never derived from the proposal
    INSERT INTO execution_grant (action_id, tenant_id, run_id, proposal_id, payload_sha256, granted_at)
    VALUES (v_action_id, v_handle.tenant_id, v_handle.run_id, p_proposal_id, v_proposal.payload_sha256,
            app.current_time());
    INSERT INTO action_attempt (tenant_id, action_id, attempt_no, created_at)
    VALUES (v_handle.tenant_id, v_action_id, 1, app.current_time());
    INSERT INTO action_attempt_state (tenant_id, action_id, attempt_no, seq, state, at)
    VALUES (v_handle.tenant_id, v_action_id, 1, 1, 'INTENT', app.current_time());
    PERFORM app._transition(v_handle.run_id, 'EXECUTING', 'grant_execution', NULL, NULL, 'action.granted',
                            jsonb_build_object('action_id', v_action_id, 'proposal_id', p_proposal_id));
    RETURN QUERY SELECT g.*, NULL::text FROM app._grant_row(v_action_id) g;
END
$fn$;
ALTER FUNCTION app.grant_execution(text, text, uuid) OWNER TO app_definer;
"""

SEARCH_PROCEDURES_API = f"""
CREATE OR REPLACE FUNCTION app.search_procedures_api(p_tenant_id uuid, p_query text, p_limit integer)
RETURNS TABLE (corpus_version text, retrieved_at timestamptz, results jsonb)
{HEADER} AS $fn$
DECLARE
    v_now timestamptz;
    v_lexemes text[];
    v_query tsquery;
    p_asset_type text := NULL;  -- the search's family filter, off: a person searches the tenant's whole corpus
BEGIN
    PERFORM app._authority('search_procedures_api', ARRAY['api']);
    -- Ruling 7 (erratum 135): the manual baseline's bounded lexical search; the tenant is the API's session's.
    IF p_tenant_id IS NULL OR p_query IS NULL OR char_length(p_query) NOT BETWEEN 1 AND 500
       OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 10 THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'BAD_ARGUMENT';
    END IF;
    PERFORM set_config('app.tenant_id', p_tenant_id::text, true);
    corpus_version := coalesce((SELECT i.corpus_version FROM corpus_ingestions i
                                WHERE i.tenant_id = p_tenant_id ORDER BY i.seq DESC LIMIT 1), 'none');
    v_now := app.current_time();
    retrieved_at := v_now;
    v_lexemes := tsvector_to_array(to_tsvector('english', regexp_replace(lower(p_query), '[^a-z0-9]+', ' ', 'g')));
    IF cardinality(v_lexemes) = 0 THEN
        results := '[]'::jsonb;
        RETURN NEXT;
        RETURN;
    END IF;
    v_query := to_tsquery('simple', array_to_string(v_lexemes, ' | '));
    -- The ranking, the filters and the result keys of mcp-read's lexical search (revision 0012), byte for byte.
{QUERY_0012}    INTO results FROM kept k;
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION app.search_procedures_api(uuid, text, integer) OWNER TO app_definer;
"""

# (name, argument types, callers, body): frozen here (N1); the newest-revision test reads this tuple. Helpers first,
# so every definer body names functions that exist.
FUNCTIONS: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("_append_event", "uuid, uuid, text, text, jsonb", (), APPEND_EVENT_HELPER),
    ("_resolve_handle", "text, text, text", (), RESOLVE_HANDLE),
    ("_run_revision", "uuid", (), RUN_REVISION),
    ("_asset_lock", "uuid, text", (), ASSET_LOCK),
    ("_asset_guard", "uuid, text, timestamptz, timestamptz, uuid, uuid", (), ASSET_GUARD),
    ("_cited_permitted", "uuid, text[]", (), CITED_PERMITTED),
    ("_expire", "uuid", (), EXPIRE),
    ("create_run", "uuid, uuid, jsonb, text, uuid", ("api",), CREATE_RUN),
    ("expire_proposal", "uuid", ("sweeper", "api"), EXPIRE_PROPOSAL),
    ("freeze_proposal", "uuid, uuid, bytea, timestamptz", ("worker",), FREEZE_PROPOSAL),
    ("record_decision", "uuid, uuid, uuid, integer, text, text, text, text", ("api",), RECORD_DECISION),
    ("create_revision", "uuid, uuid, integer, uuid, uuid", ("api",), CREATE_REVISION),
    ("request_cancel", "uuid, uuid, integer, uuid", ("api",), REQUEST_CANCEL),
    ("prepare_manual_proposal", "uuid, uuid, uuid, text[]", ("api",), PREPARE_MANUAL_PROPOSAL),
    ("create_manual_proposal", "uuid, uuid, bytea, uuid", ("api",), CREATE_MANUAL_PROPOSAL),
    ("grant_execution", "text, text, uuid", ("mcp_exec",), GRANT_EXECUTION),
    ("asset_scope", "text, text", ("mcp_read",), ASSET_SCOPE),
    ("search_procedures_scoped", SEARCH_ARGS, ("mcp_read",), SEARCH_PROCEDURES_SCOPED),
    ("search_procedures_api", "uuid, text, integer", ("api",), SEARCH_PROCEDURES_API),
)
# Signatures upgrade() drops before FUNCTIONS re-creates them: a return type or an argument list changes.
REPLACED: tuple[str, ...] = (
    "freeze_proposal(uuid, uuid, bytea, timestamptz)",
    "record_decision(uuid, uuid, uuid, text, text, text, text)",
    "grant_execution(text, text, uuid)",
)
# Signatures downgrade() drops: what this revision created, and the three it replaced (re-created below).
CREATED: tuple[str, ...] = (
    "search_procedures_api(uuid, text, integer)",
    "create_manual_proposal(uuid, uuid, bytea, uuid)",
    "prepare_manual_proposal(uuid, uuid, uuid, text[])",
    "request_cancel(uuid, uuid, integer, uuid)",
    "create_revision(uuid, uuid, integer, uuid, uuid)",
    "grant_execution(text, text, uuid)",
    "record_decision(uuid, uuid, uuid, integer, text, text, text, text)",
    "freeze_proposal(uuid, uuid, bytea, timestamptz)",
    "expire_proposal(uuid)",
    "_expire(uuid)",
    "_cited_permitted(uuid, text[])",
    "_asset_guard(uuid, text, timestamptz, timestamptz, uuid, uuid)",
    "_asset_lock(uuid, text)",
    "_run_revision(uuid)",
)
# What downgrade() re-creates afterwards, from the applied revisions' own bodies: (name, args, callers, body).
RESTORED: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("_append_event", "uuid, uuid, text, text, jsonb", (), REV0008.APPEND_EVENT_HELPER),
    ("_resolve_handle", "text, text, text", (), REV0009.RESOLVE_HANDLE),
    ("create_run", "uuid, uuid, jsonb, text, uuid", ("api",), REV0003.CREATE_RUN),
    ("freeze_proposal", "uuid, uuid, bytea, timestamptz", ("worker",), REV0004.FREEZE_PROPOSAL),
    ("record_decision", "uuid, uuid, uuid, text, text, text, text", ("api",), REV0004.RECORD_DECISION),
    ("grant_execution", "text, text, uuid", ("mcp_exec",), REV0010.GRANT_EXECUTION),
    ("asset_scope", "text, text", ("mcp_read",), REV0012.ASSET_SCOPE),
    ("search_procedures_scoped", SEARCH_ARGS, ("mcp_read",), REV0013.SEARCH_PROCEDURES_SCOPED),
)
DOWNGRADE_SCHEMA = (
    "DROP TABLE app.feedback",  # its rows, grants and policy go with it
    "DELETE FROM app.run_manifests WHERE revision > 1",
    "ALTER TABLE app.run_manifests DROP CONSTRAINT run_manifests_pkey, ADD PRIMARY KEY (run_id)",
    "ALTER TABLE app.run_manifests DROP COLUMN revision",
    "ALTER TABLE app.drafts DROP COLUMN source",
    "ALTER TABLE app.runs DROP COLUMN authors, DROP COLUMN asset_observed_at, DROP COLUMN workflow_version",
)


def upgrade() -> None:
    """Schema, the frozen cells and the feedback policy, then the replaced signatures dropped and every function
    created (body first, then its grants, so REVOKE lands on it)."""
    for statement in SCHEMA_CHANGES:
        op.execute(statement)
    for statement in privileges.grant_statements(TABLES_0016, GRANTS_0016, revokees=MAIN_GRANTEES_0016):
        op.execute(statement)
    for statement in privileges.rls_statements(("feedback",), POLICY_ROLES_0016):
        op.execute(statement)
    for signature in REPLACED:
        op.execute(f"DROP FUNCTION app.{signature}")
    for name, args, callers, body in FUNCTIONS:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)


def downgrade() -> None:
    """Back to 0015: drop what 0016 created, re-create the applied bodies with their grants, then the schema and
    0002's cells on `runs` and `drafts`."""
    for signature in CREATED:
        op.execute(f"DROP FUNCTION app.{signature}")
    for name, args, callers, body in RESTORED:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)
    for statement in DOWNGRADE_SCHEMA:
        op.execute(statement)
    for statement in privileges.grant_statements(("runs", "drafts"), RESTORED_CELLS, revokees=MAIN_GRANTEES_0016):
        op.execute(statement)
````

Edit 20 (`scripts/build_schemas.py`), replace:
````python
            "outbox_id": UUID,
````
with:
````python
            "outbox_id": UUID,
            # T21 (Plan R ruling 8, erratum 136): the feedback event's subject and category, never its text.
            "subject_kind": {"enum": ["run", "proposal", "event"]},
            "subject_id": UUID,
            "category": {"enum": ["wrong_evidence", "missing_evidence", "wrong_conclusion", "unclear", "other"]},
````

Edit 21 (`scripts/build_schemas.py`), replace:
````python
                ),
            ],
````
with:
````python
                ),
                # (10) T21: only feedback.recorded names a feedback subject and category (event_rules_ok, 0016).
                when(
                    {"not": props(type={"const": EventType.FEEDBACK_RECORDED.value})},
                    props(
                        payload={
                            "not": {
                                "anyOf": [
                                    {"required": ["subject_kind"]},
                                    {"required": ["subject_id"]},
                                    {"required": ["category"]},
                                ]
                            }
                        }
                    ),
                ),
            ],
````

Edit 22 (`tests/plan_e/test_privileges.py`), replace:
````python
    assert p.GRANTS["runs"]["worker"].upd == ("checkpoint_id", "budget_used")
````
with:
````python
    # T21: the worker also records the asset observation and the run's workflow version, never a state column.
    assert p.GRANTS["runs"]["worker"].upd == ("checkpoint_id", "budget_used", "asset_observed_at", "workflow_version")
````

Edit 23 (`tests/plan_e/test_transitions_table.py`), replace:
````python
    "tc_0001_test_clock",
````
with:
````python
    "0016_review_and_grant",
    "tc_0001_test_clock",
````

Edit 24 (`tests/plan_i/test_migration_0008.py`), replace:
````python
    assert set(module.PAYLOAD_KEYS_0008) == PAYLOAD_KEYS and len(module.PAYLOAD_KEYS_0008) == len(PAYLOAD_KEYS)
````
with:
````python
    # Revision 0016 (T21) extends the frozen list with the feedback keys; it carries 0008's own, in order.
    newest = revision("0016_review_and_grant").PAYLOAD_KEYS_0016
    assert newest[: len(module.PAYLOAD_KEYS_0008)] == module.PAYLOAD_KEYS_0008
    assert set(newest) == PAYLOAD_KEYS and len(newest) == len(PAYLOAD_KEYS)
````

Then run `uv run python -m scripts.build_schemas < /dev/null`; it rewrites the files under
`schemas/` listed above.

Run the same pytest line again → `12 passed`.

- [ ] **Step 3: Gates and commit**

`uv run ruff format` and `uv run ruff check --fix` over the touched files; `git add` the new files; dev `PYTHONUTF8=1 uv
run python scripts/check.py < /dev/null` → `CHECK: GREEN`, `1759 passed, 227 skipped`; `verify_handoff.py` exit 0.

```bash
git add -A -- . ':!reports'
git commit -m "feat: revision 0016 - the review rules, the asset guard and the final grant's re-checks (T21)"
```

---
### Task 3: Core contracts, persistence, schemas and the MCP servers

**Files:**
- Create: `tests/plan_r/test_contracts_r.py`, `tests/plan_r/test_mcp_servers_r.py`
- Modify: `core/src/ops_core/contracts.py`, `core/src/ops_core/jobs.py`, `core/src/ops_core/persistence.py`,
  `core/src/ops_core/routing.py`, `core/src/ops_core/states.py`, `mcp-read/src/ops_mcp_read/server.py`,
  `mcp-write/src/ops_mcp_write/execution.py`, `mcp-write/src/ops_mcp_write/server.py`, `scripts/build_schemas.py`,
  `tests/plan_c/test_contracts.py`, `tests/plan_c/test_jobs_routes_outcomes.py`,
  `tests/plan_k/test_mcp_write_startup.py`, `tests/plan_n/test_mcp_read_vector.py`, `tests/plan_q/test_graph_table.py`,
  `worker/src/ops_worker/mcp.py`, `schemas/error.schema.json` (regenerated), `schemas/examples/index.json`
  (regenerated), `schemas/examples/job-invalid-execute-read-tool.json` (regenerated),
  `schemas/examples/manual-proposal-invalid-authored-by.json` (regenerated),
  `schemas/examples/manual-proposal-invalid-request-timestamp-newline.json` (regenerated),
  `schemas/examples/manual-proposal-valid.json` (regenerated), `schemas/job.schema.json` (regenerated),
  `schemas/manual-proposal.schema.json` (regenerated), `schemas/tool-result.schema.json` (regenerated)

**Requirements:** rulings 3, 7, 9, 11, 14, 16, 17; SA:343-344, AM-15; errata 133, 135-137, 142; erratum 63 (ruling 11).

- [ ] **Step 1: The tests first**

Create `tests/plan_r/test_contracts_r.py`:
````python
"""T21's contracts and wrappers without a database (Plan R rulings 3, 7, 8, 9, 11; errata 131-137).

Catches: a decision conflict whose code is lost on its way from the definer (the API could only answer one generic
409); a grant whose committed refusal reads as a grant, or whose reason is not an AM-10 grant reason; a manual
proposal without its run or a search with a vector mode or an unbounded limit; a feedback key that another event type
may carry; the new error codes missing from `error.schema.json`; an execute job that cannot read the asset status
before its grant; and a manual-path run that the graph router would send back to the model.
"""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from ops_core import contracts as c
from ops_core import persistence
from ops_core.jobs import JOB_RULES, JobType, Tool
from ops_core.outcomes import EventRuleViolation, EventSource, EventType, event_rules_ok
from ops_core.routing import DraftKind, Evidence, GraphKey, GraphRoute, route_graph
from ops_core.states import GRANT_REFUSALS, TRANSITIONS, Intent, Performer, Reason, RunState
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


def refusal(sqlstate: str, detail: str) -> Exception | None:
    """The typed exception `translate` makes of a definer's refusal."""
    diag = SimpleNamespace(message_detail=detail, message_primary="version_conflict")
    exc = type("FakeError", (psycopg.DatabaseError,), {"diag": property(lambda self: diag)})("x")
    exc.sqlstate = sqlstate
    return persistence.translate(exc)


@pytest.mark.parametrize("code", ["ALREADY_DECIDED", "STALE_REVISION", "STALE_HASH", "EXPIRED"])
def test_each_decision_conflict_keeps_its_code(code: str) -> None:
    mapped = refusal("OC003", code)
    assert isinstance(mapped, persistence.VersionConflict) and mapped.code == code
    assert c.ErrorCode(code).value == code  # the API answers it under its own name (ruling 3)


def test_the_new_codes_are_in_the_error_schema() -> None:
    schema = json.loads((ROOT / "schemas" / "error.schema.json").read_text(encoding="utf-8"))
    codes = set(schema["properties"]["code"]["enum"])
    assert {"ALREADY_DECIDED", "STALE_REVISION", "STALE_HASH", "EXPIRED", "AUTHOR_LIMIT"} <= codes


class OneRow:
    """A connection whose one statement returns `row`."""

    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row

    async def execute(self, _query: str, _params: tuple[object, ...]) -> "OneRow":
        return self

    async def fetchone(self) -> dict[str, Any]:
        return self.row


def test_a_committed_grant_refusal_is_blocked_never_a_grant() -> None:
    run, proposal = uuid4(), uuid4()
    row = {key: None for key in ("action_id", "conversation_id", "payload_sha256", "payload_canonical", "detail")}
    row |= {"run_id": run, "proposal_id": proposal, "tenant_id": uuid4(), "attempt_state": None}
    conn: Any = OneRow(row | {"refusal": "asset_incident_exists"})
    got = asyncio.run(persistence.grant_execution(conn, handle="h", azp="ops-worker", proposal_id=proposal))
    assert got == persistence.Blocked(run, proposal, Reason.ASSET_INCIDENT_EXISTS)
    granting = {r.reasons for r in TRANSITIONS if r.performer is Performer.GRANT_EXECUTION and r.reasons}
    assert granting == {GRANT_REFUSALS}  # mcp-write's `reason` names exactly the table's grant refusals


def test_a_blocked_freeze_has_no_proposal() -> None:
    row = {"proposal_id": None, "revision": 2, "state": "BLOCKED_REVIEW", "reason": "asset_action_unresolved"}
    conn: Any = OneRow(row | {"state_version": 7})
    frozen = asyncio.run(
        persistence.freeze_proposal(conn, run_id=uuid4(), draft_id=uuid4(), payload_canonical=b"{}", expires_at=NOW)
    )
    assert frozen.proposal_id is None and frozen.state is RunState.BLOCKED_REVIEW
    assert frozen.reason is Reason.ASSET_ACTION_UNRESOLVED and frozen.revision == 2


def test_the_manual_proposal_names_its_run_and_the_search_is_bounded() -> None:
    body = {
        "asset_id": "A17",
        "start_at": "2026-10-05T12:00:00Z",
        "end_at": "2026-10-06T12:00:00Z",
        "title": "t",
        "summary": "s",
        "evidence_refs": ["ALPHA-INCIDENT:v2:review"],
        "assumptions": [],
        "limitations": [],
    }
    with pytest.raises(ValidationError):
        c.load(c.ManualProposalRequest, json.dumps(body))  # contract erratum 133: the run is required
    assert c.load(c.ManualProposalRequest, json.dumps({**body, "run_id": str(uuid4())})).asset_id == "A17"
    assert c.load(c.SearchRequest, '{"query": "bearing temperature"}').limit == 5
    for bad in ('{"query": "x", "limit": 11}', '{"query": ""}', '{"query": "x", "mode": "vector_exact"}'):
        with pytest.raises(ValidationError):
            c.load(c.SearchRequest, bad)


def test_only_feedback_recorded_names_a_subject_and_a_category() -> None:
    payload = {"subject_kind": "run", "subject_id": str(uuid4()), "category": "unclear"}
    event_rules_ok(EventType.FEEDBACK_RECORDED, EventSource.APPLICATION, payload)
    with pytest.raises(EventRuleViolation):
        event_rules_ok(EventType.TOOL_COMPLETED, EventSource.APPLICATION, {"category": "unclear"})


def test_an_execute_job_reads_the_asset_status_and_a_manual_run_ends_its_graph_run() -> None:
    persistence.allowed_tool(JobType.EXECUTE, RunState.APPROVED, None, Tool.GET_ASSET_STATUS)
    assert Tool.GET_RECENT_ALERTS not in JOB_RULES[JobType.EXECUTE].allowed_tools  # only the status (erratum 137)
    key = GraphKey(RunState.DRAFTING, Intent.INVESTIGATE, True, Evidence.SUFFICIENT, DraftKind.MANUAL, False, None)
    assert route_graph(key) is GraphRoute.PUBLISH  # never `draft` again: the run waits for a person
````

Create `tests/plan_r/test_mcp_servers_r.py`:
````python
"""mcp-write's committed grant refusal and committed schemas, mcp-read's stale-sync deferral, and the worker's write
discovery (T21; Plan R rulings 11, 14 and 17), in-process with the definers replaced.

Catches: a grant refusal that committed BLOCKED_REVIEW answered without its reason, or as anything but a final
GRANT_REFUSED (the worker would retry a run that is no longer APPROVED); an envelope the committed tool-result schema
refuses; mcp-write advertising a generated schema instead of the committed file; a worker that calls mcp-write without
comparing its listing to the committed contract, or accepts a result outside it; and a stale read refusal that a
caller cannot tell from a dead handle.
"""

from typing import Any
from uuid import uuid4

import httpx2
import pytest
from mcp_types import ListToolsResult
from mcp_types import Tool as AdvertisedTool
from ops_core import persistence, tool_contracts
from ops_core.jobs import Tool
from ops_core.states import Reason
from ops_mcp_read import server as read_server
from ops_worker.mcp import WRITE_TOOLS, HttpMcpCaller, McpCallFailed, check_listing

from tests.plan_k.test_recovery_tools import PROPOSAL
from tests.plan_k.test_write_tools_server import BASE, TOOL_RESULT, client, write_app

pytestmark = pytest.mark.asyncio


class Good:
    """The worker's token source, with the token the test verifier accepts."""

    async def token(self) -> str:
        return "good"


def blocked(monkeypatch: pytest.MonkeyPatch, reason: Reason) -> None:
    """A resolved handle and a grant the gate refused with a committed BLOCKED_REVIEW."""

    async def resolve(_conn: Any, **_: Any) -> None:
        return None

    async def grant(_conn: Any, **_: Any) -> persistence.Blocked:
        return persistence.Blocked(uuid4(), PROPOSAL, reason)

    monkeypatch.setattr(persistence, "resolve_invocation", resolve)
    monkeypatch.setattr(persistence, "grant_execution", grant)


async def test_a_committed_refusal_is_a_final_grant_refused_with_its_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    blocked(monkeypatch, Reason.ASSET_INCIDENT_EXISTS)
    async with client(write_app()) as mcp:
        doc = (await mcp.call_tool("create_incident", {"proposal_id": str(PROPOSAL)})).structured_content
    assert isinstance(doc, dict) and doc["status"] == "error" and doc["data"] is None
    assert doc["error"] == {
        "code": "GRANT_REFUSED",
        "message": "grant refused: asset_incident_exists",
        "retryable": False,
        "reason": "asset_incident_exists",
    }
    TOOL_RESULT.validate(doc)


async def test_mcp_write_advertises_the_committed_schemas() -> None:
    async with client(write_app()) as mcp:
        tools = {t.name: t.input_schema for t in (await mcp.list_tools()).tools}
    assert {Tool(name) for name in tools} == WRITE_TOOLS
    assert all(tool_contracts.same_input_schema(Tool(name), schema) for name, schema in tools.items())


async def test_the_worker_checks_mcp_writes_listing_and_result(monkeypatch: pytest.MonkeyPatch) -> None:
    blocked(monkeypatch, Reason.STALE_EVIDENCE)
    app = write_app()
    async with app.router.lifespan_context(app):
        caller = HttpMcpCaller(Good(), transport=httpx2.ASGITransport(app=app))
        doc = await caller.call(
            f"{BASE}/mcp", handle="h", tool="create_incident", arguments={"proposal_id": str(PROPOSAL)}
        )
    assert doc["status"] == "error" and doc["error"]["reason"] == "stale_evidence"  # validated against the contract
    tools = [AdvertisedTool(name=t.value, input_schema=tool_contracts.input_schema(t)) for t in sorted(WRITE_TOOLS)]
    check_listing(ListToolsResult(tools=tools), Tool.CREATE_INCIDENT, WRITE_TOOLS)
    altered = [*tools[:-1], AdvertisedTool(name=tools[-1].name, input_schema={"type": "object"})]
    with pytest.raises(McpCallFailed, match="not the committed one|unexpected tool set"):
        check_listing(ListToolsResult(tools=altered), Tool(tools[-1].name), WRITE_TOOLS)
    with pytest.raises(McpCallFailed, match="unexpected tool set"):
        check_listing(ListToolsResult(tools=tools[:2]), Tool.CREATE_INCIDENT, WRITE_TOOLS)


async def test_a_stale_read_is_a_retryable_deferral_and_any_other_refusal_is_not() -> None:
    assert read_server.stale_error("MEMBERSHIP_STALE")["retryable"] is True
    assert read_server.stale_error("BAD_ARGUMENT") == {"code": "REFUSED", "message": "BAD_ARGUMENT", "retryable": False}
````

Run `PYTHONUTF8=1 uv run python -m pytest tests/plan_r/test_contracts_r.py tests/plan_r/test_mcp_servers_r.py -q -p
no:cacheprovider < /dev/null` → RED, `2 errors during collection`: `ImportError: cannot import name 'GRANT_REFUSALS'
from 'ops_core.states'` and `ImportError: cannot import name 'WRITE_TOOLS' from 'ops_worker.mcp'`.

- [ ] **Step 2: The contracts, the persistence functions, the schemas and the two servers**

Edit 25 (`core/src/ops_core/contracts.py`), replace:
````python
    """`POST /manual-proposals`: a human-authored draft that enters the same approval path (AM-20.3)."""

    model_config = _Strict
````
with:
````python
    """`POST /manual-proposals`: a human-authored draft that enters the same approval path (AM-20.3). `run_id` names
    the run whose model draft it replaces (T21, contract erratum 133: BS:281's route carries no run in its path); the
    asset and the interval must be that run's (SA:154)."""

    model_config = _Strict
    run_id: UUID
````

Edit 26 (`core/src/ops_core/contracts.py`), replace:
````python
class ModelDraft(BaseModel):
````
with:
````python
class SearchRequest(BaseModel):
    """`POST /search`: the manual baseline's bounded lexical search (BS:280; T21, erratum 135: no vector mode in v1)."""

    model_config = _Strict
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500), _Nfc]
    limit: int = Field(default=5, ge=1, le=10)


class ModelDraft(BaseModel):
````

Edit 27 (`core/src/ops_core/contracts.py`), replace:
````python
    AUTHORITY_VIOLATION = "AUTHORITY_VIOLATION"
````
with:
````python
    AUTHORITY_VIOLATION = "AUTHORITY_VIOLATION"
    # T21 (Plan R ruling 3, erratum 131): the decision's conflicts, each its own code; and the author cap (ruling 4).
    ALREADY_DECIDED = "ALREADY_DECIDED"
    STALE_REVISION = "STALE_REVISION"
    STALE_HASH = "STALE_HASH"
    EXPIRED = "EXPIRED"
    AUTHOR_LIMIT = "AUTHOR_LIMIT"
````

Edit 28 (`core/src/ops_core/jobs.py`), replace:
````python
        frozenset({Tool.CREATE_INCIDENT}),
````
with:
````python
        # T21 (erratum 137): the asset status is read again before the grant, so its observation is fresh (R116); the
        # read goes to mcp-read on a read handle of the same job (revision 0016's `_resolve_handle`).
        frozenset({Tool.CREATE_INCIDENT, Tool.GET_ASSET_STATUS}),
````

Edit 29 (`core/src/ops_core/persistence.py`), replace:
````python
    """A stale state, version or hash: the caller's view of the run is out of date."""
````
with:
````python
    """A stale state, version or hash: the caller's view of the run is out of date. `code` is the function's DETAIL
    when it names one (T21's decision rules: ALREADY_DECIDED, STALE_REVISION, STALE_HASH, EXPIRED)."""

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code
````

Edit 30 (`core/src/ops_core/persistence.py`), replace:
````python
    return cls(f"{exc.diag.message_primary}: {detail}" if detail else str(exc.diag.message_primary))
````
with:
````python
    if cls is VersionConflict:
        message = f"{exc.diag.message_primary}: {detail}" if detail else str(exc.diag.message_primary)
        return VersionConflict(message, code=detail or None)
    return cls(f"{exc.diag.message_primary}: {detail}" if detail else str(exc.diag.message_primary))
````

Edit 31 (`core/src/ops_core/persistence.py`), replace:
````python
    "e.embedding OPERATOR(public.<=>) p_query_embedding",
)
````
with:
````python
    "e.embedding OPERATOR(public.<=>) p_query_embedding",
)
# Revision 0016 (T21): the freeze and the grant apply the asset guard and return what a committed refusal decided, the
# read path defers a stale sync, and `expire_proposal` exists. The worker, mcp-write, mcp-read and the sweeper call
# them in these shapes, so each refuses to start without them (Plan R ruling 16); the api checks `app.feedback`. The
# same rule: a later revision that re-creates one keeps its text or changes it here in the same commit.
FREEZE_GUARD: Final = ("app.freeze_proposal(uuid, uuid, bytea, timestamptz)", "app._asset_guard(")
GRANT_GUARD: Final = ("app.grant_execution(text, text, uuid)", "app._asset_guard(")
READ_FRESHNESS: Final = ("app.asset_scope(text, text)", "DETAIL = 'MEMBERSHIP_STALE'")
PROPOSAL_EXPIRY: Final = ("app.expire_proposal(uuid)", "app._expire(")
````

Edit 32 (`core/src/ops_core/persistence.py`), replace:
````python
    """What freeze_proposal returned: the proposal's id and revision, and the run's new state_version."""

    proposal_id: UUID
    revision: int
    state_version: int


async def freeze_proposal(
    conn: Conn, *, run_id: UUID, draft_id: UUID, payload_canonical: bytes, expires_at: datetime
) -> Frozen:
    """The frozen bytes are hashed inside and compared with the validated draft's hash (SA:453)."""
    row = await _call(
        conn, "SELECT * FROM app.freeze_proposal(%s, %s, %s, %s)", (run_id, draft_id, payload_canonical, expires_at)
    )
    if row is None:
        raise PersistenceError("freeze_proposal returned nothing")
    return Frozen(UUID(str(row["proposal_id"])), int(row["revision"]), int(row["state_version"]))
````
with:
````python
    """What freeze_proposal or create_manual_proposal committed: AWAITING_APPROVAL with the proposal's id, or
    BLOCKED_REVIEW with the asset guard's reason and no proposal (T21, AM-13); the revision, the run's new
    state_version and, for a manual proposal, the blocking run (the caller's tenant's, ruling 10)."""

    proposal_id: UUID | None
    revision: int
    state: RunState
    reason: Reason | None
    state_version: int
    blocking_run_id: UUID | None = None


def _frozen(row: DictRow) -> Frozen:
    blocking = row.get("blocking_run_id")
    return Frozen(
        None if row["proposal_id"] is None else UUID(str(row["proposal_id"])),
        int(row["revision"]),
        RunState(str(row["state"])),
        None if row["reason"] is None else Reason(str(row["reason"])),
        int(row["state_version"]),
        None if blocking is None else UUID(str(blocking)),
    )


async def freeze_proposal(
    conn: Conn, *, run_id: UUID, draft_id: UUID, payload_canonical: bytes, expires_at: datetime
) -> Frozen:
    """The frozen bytes are hashed inside and compared with the validated draft's hash (SA:453); since T21 the
    function also applies the asset guard, whose refusal commits BLOCKED_REVIEW and freezes nothing."""
    row = await _call(
        conn, "SELECT * FROM app.freeze_proposal(%s, %s, %s, %s)", (run_id, draft_id, payload_canonical, expires_at)
    )
    if row is None:
        raise PersistenceError("freeze_proposal returned nothing")
    return _frozen(row)
````

Edit 33 (`core/src/ops_core/persistence.py`), replace:
````python
    hits = row["results"]
````
with:
````python
    return _procedures(row)


async def search_procedures_api(conn: Conn, *, tenant_id: UUID, query: str, limit: int) -> Procedures:
    """The manual baseline's lexical search (BS:280; T21, erratum 135) over the API session's tenant: the ranking,
    filters and result rows of `search_procedures`, with no handle and no vector mode.

    Raises:
        Refused: BAD_ARGUMENT for a query or limit outside the bounds.
    """
    row = await _call(conn, "SELECT * FROM app.search_procedures_api(%s, %s, %s)", (tenant_id, query, limit))
    if row is None:
        raise PersistenceError("search_procedures_api returned nothing")
    return _procedures(row)


def _procedures(row: DictRow) -> Procedures:
    """A search function's row as `Procedures`."""
    hits = row["results"]
````

Edit 34 (`core/src/ops_core/persistence.py`), replace:
````python
@dataclass(frozen=True)
class Grant:
````
with:
````python
@dataclass(frozen=True)
class Blocked:
    """A grant the §13 gate refused with a committed BLOCKED_REVIEW (T21; AM-10 SA:140): expired, authority_revoked,
    stale_evidence, asset_action_unresolved or asset_incident_exists. Nothing was granted."""

    run_id: UUID
    proposal_id: UUID
    reason: Reason


@dataclass(frozen=True)
class Grant:
````

Edit 35 (`core/src/ops_core/persistence.py`), replace:
````python
async def grant_execution(conn: Conn, *, handle: str, azp: str, proposal_id: UUID) -> Grant:
    """The §13 gate inside the function; a replay returns the grant the run already has (SA:462).

    `azp` is the presented token's. This definer and the four after it (`lookup_action`, `mark_sent`, `request_abort`,
    `record_outcome`) pass it to `_resolve_handle`, which compares it with the one the handle was minted for, as
    `resolve_invocation` always did (revision 0010, Plan K ruling 12).
    """
    row = await _call(conn, "SELECT * FROM app.grant_execution(%s, %s, %s)", (handle, azp, proposal_id))
    if row is None:
        raise PersistenceError("grant_execution returned nothing")
````
with:
````python
async def grant_execution(conn: Conn, *, handle: str, azp: str, proposal_id: UUID) -> Grant | Blocked:
    """The §13 gate inside the function; a replay returns the grant the run already has (SA:462).

    `azp` is the presented token's. This definer and the four after it (`lookup_action`, `mark_sent`, `request_abort`,
    `record_outcome`) pass it to `_resolve_handle`, which compares it with the one the handle was minted for, as
    `resolve_invocation` always did (revision 0010, Plan K ruling 12). Since T21 a refusal of the run's review
    (expiry, revoked authority, stale evidence, the asset guard) is returned as `Blocked`, so the caller's unit
    commits the BLOCKED_REVIEW it wrote; a binding refusal still raises `Refused` and commits nothing.
    """
    row = await _call(conn, "SELECT * FROM app.grant_execution(%s, %s, %s)", (handle, azp, proposal_id))
    if row is None:
        raise PersistenceError("grant_execution returned nothing")
    if row["refusal"] is not None:
        return Blocked(UUID(str(row["run_id"])), UUID(str(row["proposal_id"])), Reason(str(row["refusal"])))
````

Edit 36 (`core/src/ops_core/persistence.py`), replace:
````python
@dataclass(frozen=True)
class GraphFacts:
````
with:
````python
async def run_revision(conn: Conn, run_id: UUID) -> int:
    """The run's current revision: 1 plus its `proposal.revised` events, the rule revision 0016's `_run_revision`
    applies (T21, Plan R ruling 1). Read under the caller's tenant unit."""
    cur = await conn.execute(
        "SELECT 1 + count(*) AS revision FROM app.events WHERE run_id = %s AND type = %s",
        (run_id, EventType.PROPOSAL_REVISED.value),
    )
    row = await cur.fetchone()
    return 1 if row is None else int(row["revision"])


async def lock_asset(conn: Conn, tenant_id: UUID, asset_id: str) -> None:
    """The asset guard's advisory lock (SA:189) in the caller's transaction, the key `_asset_lock` takes: the worker's
    freeze unit takes it before its fence, so its order is the published one (advisory:asset, run_lease, runs).
    No privilege is needed for an advisory lock."""
    await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s || ':' || %s, 0))", (str(tenant_id), asset_id))


async def record_asset_observation(conn: Conn, run_id: UUID, observed_at: datetime) -> None:
    """`runs.asset_observed_at` := the instant mcp-read's status answer observed the asset (R116; T21 ruling 9), under
    the worker's column grant; the grant refuses an observation older than five minutes."""
    await conn.execute("UPDATE app.runs SET asset_observed_at = %s WHERE run_id = %s", (observed_at, run_id))


async def record_workflow_version(conn: Conn, run_id: UUID, version: str) -> str:
    """`runs.workflow_version` := `version` unless the run has one already (BS:342; T21 ruling 18: the first claim pins
    it); returns the run's version, which the freeze compares with the payload's."""
    cur = await conn.execute(
        "UPDATE app.runs SET workflow_version = coalesce(workflow_version, %s) WHERE run_id = %s"
        " RETURNING workflow_version",
        (version, run_id),
    )
    row = await cur.fetchone()
    if row is None:
        raise NotFound("run not found")
    return str(row["workflow_version"])


async def clear_checkpoint_id(conn: Conn, run_id: UUID) -> None:
    """`runs.checkpoint_id` := NULL for a run whose graph run ended in DRAFTING because the model could not draft: the
    state a manual proposal waits for (T21, erratum 134)."""
    await conn.execute("UPDATE app.runs SET checkpoint_id = NULL WHERE run_id = %s", (run_id,))


@dataclass(frozen=True)
class Revised:
    """What create_revision committed: the run's new state_version and its new revision."""

    run_id: UUID
    state_version: int
    revision: int


async def create_revision(
    conn: Conn,
    *,
    tenant_id: UUID,
    run_id: UUID,
    expected_version: int,
    author: UUID,
    supersedes_run_id: UUID | None,
) -> Revised:
    """AWAITING_APPROVAL, APPROVED or BLOCKED_REVIEW → QUEUED with a new revision (SA:455; T21 rulings 1, 2, 4, 6).

    Raises:
        NotFound: no such run in the tenant, or a supersedes_run_id that names no run of the tenant and asset.
        VersionConflict: the run is in another state or at another version.
        Refused: NOT_REQUESTER, GRANT_EXISTS, AUTHOR_LIMIT or SLOT_OCCUPIED.
    """
    row = await _call(
        conn,
        "SELECT * FROM app.create_revision(%s, %s, %s, %s, %s)",
        (tenant_id, run_id, expected_version, author, supersedes_run_id),
    )
    if row is None:
        raise PersistenceError("create_revision returned nothing")
    return Revised(UUID(str(row["run_id"])), int(row["state_version"]), int(row["revision"]))


@dataclass(frozen=True)
class Cancelled:
    """What request_cancel answered (SA:458): CANCELLED before a grant; after one, the flag set and the attempt."""

    run_id: UUID
    state: RunState
    state_version: int
    grant_exists: bool
    attempt_state: AttemptState | None


async def request_cancel(conn: Conn, *, tenant_id: UUID, run_id: UUID, expected_version: int, actor: UUID) -> Cancelled:
    """Cancel before the grant, or set `cancel_requested` after it (SA:458; T21 ruling 12).

    Raises:
        NotFound: no such run in the tenant.
        VersionConflict: before a grant, the run is terminal or at another version.
        Refused: NOT_CANCELLER (neither the run's requester nor a reviewer of the tenant).
    """
    row = await _call(
        conn, "SELECT * FROM app.request_cancel(%s, %s, %s, %s)", (tenant_id, run_id, expected_version, actor)
    )
    if row is None:
        raise PersistenceError("request_cancel returned nothing")
    attempt = row["attempt_state"]
    return Cancelled(
        UUID(str(row["run_id"])),
        RunState(str(row["state"])),
        int(row["state_version"]),
        bool(row["grant_exists"]),
        None if attempt is None else AttemptState(str(attempt)),
    )


async def expire_proposal(conn: Conn, run_id: UUID) -> RunState:
    """BLOCKED_REVIEW(expired) when the run's active proposal is past its expiry (SA:457); otherwise nothing. The run's
    state afterwards."""
    row = await _call(conn, "SELECT app.expire_proposal(%s) AS state", (run_id,))
    if row is None:
        raise PersistenceError("expire_proposal returned nothing")
    return RunState(str(row["state"]))


@dataclass(frozen=True)
class ManualFacts:
    """What a manual proposal's payload takes from the run (T21 ruling 7): its revision, workflow version, supersession,
    asset and interval, the expiry on the application clock, and the snapshots of the cited permitted sections."""

    revision: int
    workflow_version: str
    supersedes_run_id: UUID | None
    asset_id: str
    start_at: datetime
    end_at: datetime
    expires_at: datetime
    snapshots: list[dict[str, str]]


async def prepare_manual_proposal(
    conn: Conn, *, tenant_id: UUID, run_id: UUID, author: UUID, evidence_ids: Sequence[str]
) -> ManualFacts:
    """The first of a manual proposal's two calls, in the caller's unit: the asset guard's lock and the run's lock
    are held until it commits (T21 ruling 7).

    Raises:
        NotFound: no such run, or a cited section that is not a permitted section of the tenant (note 4).
        VersionConflict: the run does not wait for a manual proposal.
        Refused: NOT_AUTHOR or AUTHOR_LIMIT.
    """
    row = await _call(
        conn,
        "SELECT * FROM app.prepare_manual_proposal(%s, %s, %s, %s)",
        (tenant_id, run_id, author, list(evidence_ids)),
    )
    if row is None:
        raise PersistenceError("prepare_manual_proposal returned nothing")
    supersedes = row["supersedes_run_id"]
    return ManualFacts(
        int(row["revision"]),
        str(row["workflow_version"]),
        None if supersedes is None else UUID(str(supersedes)),
        str(row["asset_id"]),
        row["start_at"],
        row["end_at"],
        row["expires_at"],
        [dict(s) for s in row["snapshots"]],
    )


async def create_manual_proposal(
    conn: Conn, *, tenant_id: UUID, run_id: UUID, payload_canonical: bytes, author: UUID
) -> Frozen:
    """The person's frozen proposal through the freeze rules and the asset guard (SA:456; T21 ruling 7).

    Raises:
        NotFound: no such run, another asset than the run's, or snapshots that are not the permitted sections.
        VersionConflict: the run does not wait for a manual proposal, or another revision.
        Refused: NOT_AUTHOR, AUTHOR_LIMIT or a payload field the run fixes (PAYLOAD_RUN_MISMATCH, INTERVAL,
            SUPERSEDES_MISMATCH, WORKFLOW_VERSION, EXPIRY).
    """
    row = await _call(
        conn,
        "SELECT * FROM app.create_manual_proposal(%s, %s, %s, %s)",
        (tenant_id, run_id, payload_canonical, author),
    )
    if row is None:
        raise PersistenceError("create_manual_proposal returned nothing")
    return _frozen(row)


@dataclass(frozen=True)
class GraphFacts:
````

Edit 37 (`core/src/ops_core/routing.py`), replace:
````python
    QUESTION = "question"
````
with:
````python
    QUESTION = "question"
    # T21 (erratum 134): no validated draft came (the model was unavailable, or its draft stayed invalid after the
    # repair); the run waits in DRAFTING for a person's proposal. The worker's verdict, never a model's kind.
    MANUAL = "manual"
````

Edit 38 (`core/src/ops_core/routing.py`), replace:
````python
    GraphRule("question", frozenset({_RS.DRAFTING}), GraphRoute.CLARIFY, draft_kind=DraftKind.QUESTION),
````
with:
````python
    # T21 (erratum 134): the graph run ends with the run in DRAFTING; a person's proposal moves it on (ruling 7).
    GraphRule("manual", frozenset({_RS.DRAFTING}), GraphRoute.PUBLISH, draft_kind=DraftKind.MANUAL),
    GraphRule("question", frozenset({_RS.DRAFTING}), GraphRoute.CLARIFY, draft_kind=DraftKind.QUESTION),
````

Edit 39 (`core/src/ops_core/states.py`), replace:
````python
POST_GRANT_STATES: Final = frozenset(
````
with:
````python
# The reasons a refused grant records (the APPROVED -> BLOCKED_REVIEW row of grant_execution and expire_proposal's
# expiry), which mcp-write's GRANT_REFUSED envelope names (T21, Plan R ruling 11).
GRANT_REFUSALS: Final = _GRANT_REFUSAL
POST_GRANT_STATES: Final = frozenset(
````

Edit 40 (`mcp-read/src/ops_mcp_read/server.py`), replace:
````python
def envelope(
````
with:
````python
def stale_error(code: str) -> dict[str, Any]:
    """The tool error for a definer's refusal: MEMBERSHIP_STALE (the requester's row not synced within 120 s, T21
    ruling 14) is a deferral the caller may retry, as mcp-write's GRANT_DEFERRED is; any other code is `REFUSED`."""
    if code == "MEMBERSHIP_STALE":
        return tool_error(code, "the membership sync is stale; try again", retryable=True)
    return tool_error("REFUSED", code)


def envelope(
````

Edit 41 (`mcp-read/src/ops_mcp_read/server.py`), replace:
````python

    async def from_asset_sim(
````
with:
````python
        except persistence.Refused as exc:
            return envelope(tool.value, error=stale_error(exc.code))

    async def from_asset_sim(
````

Edit 42 (`mcp-read/src/ops_mcp_read/server.py`), replace:
````python
            return envelope(name.value, error=tool_error("REFUSED", exc.code), observed_at=scope.as_of)
````
with:
````python
            return envelope(name.value, error=stale_error(exc.code), observed_at=scope.as_of)
````

Edit 43 (`mcp-read/src/ops_mcp_read/server.py`), replace:
````python
            except BaseException:  # a failed start must leak no connection, and a re-entered lifespan re-asserts
````
with:
````python
                await persistence.assert_function_text(conn, *persistence.READ_FRESHNESS)  # 0016 (T21)
            except BaseException:  # a failed start must leak no connection, and a re-entered lifespan re-asserts
````

Edit 44 (`mcp-write/src/ops_mcp_write/execution.py`), replace:
````python
from ops_core.states import AttemptState, IllegalTransition
````
with:
````python
from ops_core.states import AttemptState, IllegalTransition, Reason
````

Edit 45 (`mcp-write/src/ops_mcp_write/execution.py`), replace:
````python
def next_step(attempt_state: str | None) -> Literal["stored", "send", "resend", "aborting"]:
````
with:
````python
class GrantBlocked(Exception):
    """The §13 gate refused the grant and committed the run's BLOCKED_REVIEW (T21, Plan R rulings 9 and 11): nothing
    was granted or sent. `reason` is the AM-10 reason the run records."""

    def __init__(self, reason: Reason) -> None:
        super().__init__(reason.value)
        self.reason = reason


def next_step(attempt_state: str | None) -> Literal["stored", "send", "resend", "aborting"]:
````

Edit 46 (`mcp-write/src/ops_mcp_write/execution.py`), replace:
````python
        grant = await persistence.grant_execution(conn, handle=handle, azp=azp, proposal_id=proposal_id)
````
with:
````python
        granted = await persistence.grant_execution(conn, handle=handle, azp=azp, proposal_id=proposal_id)
    if isinstance(granted, persistence.Blocked):
        raise GrantBlocked(granted.reason)  # raised after the unit committed the run's BLOCKED_REVIEW (AM-10)
    grant = granted
````

Edit 47 (`mcp-write/src/ops_mcp_write/server.py`), replace:
````python
from ops_core import persistence, redaction, settings
````
with:
````python
from ops_core import persistence, redaction, settings, tool_contracts
````

Edit 48 (`mcp-write/src/ops_mcp_write/server.py`), replace:
````python
def envelope(tool_name: str, *, data: dict[str, Any] | None = None, error: dict[str, Any] | None = None) -> ToolResult:
````
with:
````python
def blocked_error(blocked: execution.GrantBlocked) -> dict[str, Any]:
    """The tool error for a grant the gate refused with a committed BLOCKED_REVIEW (T21, Plan R ruling 11): the code
    every final grant refusal has, plus `reason`, the run's AM-10 reason; nothing was granted or sent (SA:355)."""
    return {**tool_error("GRANT_REFUSED", f"grant refused: {blocked.reason.value}"), "reason": blocked.reason.value}


def envelope(tool_name: str, *, data: dict[str, Any] | None = None, error: dict[str, Any] | None = None) -> ToolResult:
````

Edit 49 (`mcp-write/src/ops_mcp_write/server.py`), replace:
````python
    """A Tool whose argument model forbids extra keys and whose advertised schema says so.

    The SDK derives the model from the signature and ignores unknown keys (measured in the Plan D spike); SA:350
    requires the opposite, so the model is subclassed with `extra="forbid"` and the schema regenerated. `strict`
    stops lax coercion, so `limit="1"` or `limit=True` is refused rather than read as 1.
````
with:
````python
    """A Tool whose argument model forbids extra keys and which advertises exactly the committed input schema.

    The SDK derives the model from the signature and ignores unknown keys (measured in the Plan D spike); SA:350
    requires the opposite, so the model is subclassed with `extra="forbid"`. `strict` stops lax coercion, so
    `limit="1"` or `limit=True` is refused rather than read as 1. What a client is shown is the file in
    `schemas/tools/` itself, which the worker compares with its own copy before every write call (T21, Plan R ruling
    17; mcp-read's rule since T16).
````

Edit 50 (`mcp-write/src/ops_mcp_write/server.py`), replace:
````python
    tool.parameters = strict.model_json_schema(by_alias=True)
````
with:
````python
    tool.parameters = tool_contracts.input_schema(ToolName(tool.name))
````

Edit 51 (`mcp-write/src/ops_mcp_write/server.py`), replace:
````python
        except persistence.Refused as exc:
````
with:
````python
        except execution.GrantBlocked as exc:
            return envelope(tool.value, error=blocked_error(exc))
        except persistence.Refused as exc:
````

Edit 52 (`mcp-write/src/ops_mcp_write/server.py`), replace:
````python
            except BaseException:  # a failed start must leak no connection
````
with:
````python
                # Revision 0016: the grant applies the asset guard and returns a committed refusal (T21).
                await persistence.assert_function_text(conn, *persistence.GRANT_GUARD)
            except BaseException:  # a failed start must leak no connection
````

Edit 53 (`scripts/build_schemas.py`), replace:
````python
from ops_core.states import GRANTLESS_STATES, POST_GRANT_STATES, AttemptState, Reason, RunState
````
with:
````python
from ops_core.states import GRANT_REFUSALS, GRANTLESS_STATES, POST_GRANT_STATES, AttemptState, Reason, RunState
````

Edit 54 (`scripts/build_schemas.py`), replace:
````python
        {"code": text(1, 80), "message": SHORT, "retryable": {"type": "boolean"}}, ["code", "message", "retryable"]
````
with:
````python
        {
            "code": text(1, 80),
            "message": SHORT,
            "retryable": {"type": "boolean"},
            # T21 (Plan R ruling 11): a grant refused with a committed BLOCKED_REVIEW names its AM-10 reason.
            "reason": {"enum": sorted(r.value for r in GRANT_REFUSALS)},
        },
        ["code", "message", "retryable"],
````

Edit 55 (`scripts/build_schemas.py`), replace:
````python
                "asset_id": ASSET_ID,
                "start_at": UTC_REQUEST,
````
with:
````python
                "run_id": UUID,  # T21 (contract erratum 133): the run whose model draft it replaces
                "asset_id": ASSET_ID,
                "start_at": UTC_REQUEST,
````

Edit 56 (`scripts/build_schemas.py`), replace:
````python
            ["asset_id", "start_at", "end_at", "title", "summary", "evidence_refs", "assumptions", "limitations"],
````
with:
````python
            [
                "run_id",
                "asset_id",
                "start_at",
                "end_at",
                "title",
                "summary",
                "evidence_refs",
                "assumptions",
                "limitations",
            ],
````

Edit 57 (`scripts/build_schemas.py`), replace:
````python
    manual_valid = {
````
with:
````python
    manual_valid = {
        "run_id": RUN,
````

Edit 58 (`scripts/build_schemas.py`), replace:
````python
            "allowed_tools": [Tool.GET_RECENT_ALERTS.value],
            "run_states": ["APPROVED", "EXECUTING"],
            "created_by": ["record_decision"],
            "dedup_key": PROPOSAL,
        },
        "An execute job may call only create_incident.",
        "^\\$\\.allowed_tools\\[0\\]: 'get_recent_alerts' is not one of",
````
with:
````python
            "allowed_tools": [Tool.GET_ASSET_STATUS.value, Tool.GET_RECENT_ALERTS.value],
            "run_states": ["APPROVED", "EXECUTING"],
            "created_by": ["record_decision"],
            "dedup_key": PROPOSAL,
        },
        "An execute job may call only create_incident and, before its grant, get_asset_status (T21, erratum 137).",
        "^\\$\\.allowed_tools\\[1\\]: 'get_recent_alerts' is not one of",
````

Edit 59 (`tests/plan_c/test_contracts.py`), replace:
````python
            "asset_id": "A17",
````
with:
````python
            "run_id": str(RUN),
            "asset_id": "A17",
````

Edit 60 (`tests/plan_c/test_jobs_routes_outcomes.py`), replace:
````python
    assert JOB_RULES[JobType.EXECUTE].allowed_tools == {Tool.CREATE_INCIDENT}
````
with:
````python
    # T21 (erratum 137): an execute job reads the asset status again before its grant (R116).
    assert JOB_RULES[JobType.EXECUTE].allowed_tools == {Tool.CREATE_INCIDENT, Tool.GET_ASSET_STATUS}
````

Edit 61 (`tests/plan_k/test_mcp_write_startup.py`), replace:
````python
BOTH = {persistence.HANDLE_BINDING[1], persistence.WRITE_PATH[1]}
````
with:
````python
# Since T21 a started mcp-write also finds revision 0016's guarded grant (Plan R ruling 16).
BOTH = {persistence.HANDLE_BINDING[1], persistence.WRITE_PATH[1], persistence.GRANT_GUARD[1]}
````

Edit 62 (`tests/plan_k/test_mcp_write_startup.py`), replace:
````python
    )
    conn: Any = MarkerConn({marker for _, marker in present})  # every mcp-read revision through 0013 (T18)
````
with:
````python
        persistence.READ_FRESHNESS,  # T21: revision 0016's stale-sync deferral (Plan R ruling 14)
    )
    conn: Any = MarkerConn({marker for _, marker in present})  # every mcp-read revision through 0016 (T21)
````

Edit 63 (`tests/plan_n/test_mcp_read_vector.py`), replace:
````python
    "schemas/tool-result.schema.json": "c4e6f39b44c4b22c6078826329e7a16694872d9303bc53718f8cde5c02d4466a",
````
with:
````python
    # T21 (Plan R ruling 11) added the error object's optional `reason`; the read tools' shapes are unchanged.
    "schemas/tool-result.schema.json": "124f889658b32f7a095d89cf4a56d0a60d80634b9b02dfe418dcbe4150d3a45a",
````

Edit 64 (`tests/plan_q/test_graph_table.py`), replace:
````python
    routes = {
        route_graph(GraphKey(RunState.DRAFTING, Intent.INVESTIGATE, True, Evidence.SUFFICIENT, kind, False, None))
        for kind in DraftKind
        if kind is not DraftKind.NONE
    }
    assert routes == {GraphRoute.ABSTAIN, GraphRoute.CLARIFY, GraphRoute.ANSWER_ONLY, GraphRoute.FREEZE}
````
with:
````python
    # T21: MANUAL is the worker's own verdict when no validated draft came (erratum 134), never a model's kind; it
    # ends the graph run with the run waiting in DRAFTING for a person's proposal.
    routes = {
        route_graph(GraphKey(RunState.DRAFTING, Intent.INVESTIGATE, True, Evidence.SUFFICIENT, kind, False, None))
        for kind in DraftKind
        if kind not in (DraftKind.NONE, DraftKind.MANUAL)
    }
    assert routes == {GraphRoute.ABSTAIN, GraphRoute.CLARIFY, GraphRoute.ANSWER_ONLY, GraphRoute.FREEZE}
    manual = GraphKey(RunState.DRAFTING, Intent.INVESTIGATE, True, Evidence.SUFFICIENT, DraftKind.MANUAL, False, None)
    assert route_graph(manual) is GraphRoute.PUBLISH
````

Edit 65 (`worker/src/ops_worker/mcp.py`), replace:
````python
have succeeded.
````
with:
````python
have succeeded. A write tool gets the same discovery (exactly mcp-write's three tools, the called one's committed
schema) and its answer must be a valid tool result of that tool (T21, Plan R ruling 17); any other status (an
`outcome`, an `error`) is the caller's to read.
````

Edit 66 (`worker/src/ops_worker/mcp.py`), replace:
````python
READ_TOOLS: Final = JOB_RULES[JobType.INVESTIGATE].allowed_tools
````
with:
````python
READ_TOOLS: Final = JOB_RULES[JobType.INVESTIGATE].allowed_tools
# mcp-write's three tools (AM-15: a recover job may call each), what it must advertise (T21, Plan R ruling 17).
WRITE_TOOLS: Final = JOB_RULES[JobType.RECOVER].allowed_tools
````

Edit 67 (`worker/src/ops_worker/mcp.py`), replace:
````python
def check_listing(listing: ListToolsResult, tool: Tool) -> None:
    """R029's discovery check: the server lists exactly the read tools, once each, on one page, and advertises the
    called tool's committed input schema (canonical JSON). A listing with a `next_cursor` is refused: a later page
    could add a tool this check never saw.
````
with:
````python
def check_listing(listing: ListToolsResult, tool: Tool, expected: frozenset[Tool] = READ_TOOLS) -> None:
    """R029's discovery check: the server lists exactly the `expected` tools (the read tools, or since T21 mcp-write's
    three), once each, on one page, and advertises the called tool's committed input schema (canonical JSON). A
    listing with a `next_cursor` is refused: a later page could add a tool this check never saw.
````

Edit 68 (`worker/src/ops_worker/mcp.py`), replace:
````python
        or set(names) != {read.value for read in READ_TOOLS}
````
with:
````python
        or set(names) != {known.value for known in expected}
````

Edit 69 (`worker/src/ops_worker/mcp.py`), replace:
````python
        statuses: list[int] = []
````
with:
````python
        write = next((candidate for candidate in WRITE_TOOLS if candidate.value == tool), None)
        statuses: list[int] = []
````

Edit 70 (`worker/src/ops_worker/mcp.py`), replace:
````python
                # The SDK itself checks the result against the output schema the server advertised and raises
````
with:
````python
                elif write is not None:  # T21 (Plan R ruling 17): mcp-write's listing, the same rule
                    check_listing(await client.list_tools(), write, WRITE_TOOLS)
                # The SDK itself checks the result against the output schema the server advertised and raises
````

Edit 71 (`worker/src/ops_worker/mcp.py`), replace:
````python
            if isinstance(leaf, TRANSPORT_FAILURES):
````
with:
````python
            if isinstance(leaf, McpCallFailed):  # a failed write-listing check: the client's task group wraps it
                raise leaf from None
            if isinstance(leaf, TRANSPORT_FAILURES):
````

Edit 72 (`worker/src/ops_worker/mcp.py`), replace:
````python
        # TODO(T21): the write tools (mcp-write) still get only T47's check: no discovery and no result-schema check
        # (Plan Q departure 4: whether mcp-write advertises the committed create_incident schema is checked live first).
        if result.is_error or not isinstance(result.structured_content, dict):
            raise McpCallFailed(f"{tool}: the server rejected the call")
        return result.structured_content
````
with:
````python
        if result.is_error or not isinstance(result.structured_content, dict):
            raise McpCallFailed(f"{tool}: the server rejected the call")
        if write is None:  # no tool of either server: the SDK answered, so its result is all there is to return
            return result.structured_content
        try:  # T21 (Plan R ruling 17): the committed result schema, whatever the envelope's status
            return tool_contracts.check_result(write, result.structured_content)
        except tool_contracts.ContractViolation as exc:
            raise McpCallFailed(f"{tool}: the result fails the contract") from exc
````

Then run `uv run python -m scripts.build_schemas < /dev/null`; it rewrites the files under
`schemas/` listed above.

Run the same pytest line again → `14 passed`.

- [ ] **Step 3: Gates and commit**

`uv run ruff format` and `uv run ruff check --fix` over the touched files; `git add` the new files; dev `PYTHONUTF8=1 uv
run python scripts/check.py < /dev/null` → `CHECK: GREEN`, `1775 passed, 227 skipped`; `verify_handoff.py` exit 0.

```bash
git add -A -- . ':!reports'
git commit -m "feat: T21 contracts, persistence and schemas; mcp-write's result schema and mcp-read's stale reads"
```

---
### Task 4: The API routes: decisions, revisions, cancel, manual proposals, feedback, search and the card

**Files:**
- Create: `tests/plan_r/test_api_review.py`
- Modify: `api/src/ops_api/app.py`, `api/src/ops_api/store.py`, `core/src/ops_core/persistence.py`,
  `tests/plan_d/test_api.py`, `tests/plan_g/fakes.py`, `tests/plan_g/test_api_admission.py`

**Requirements:** rulings 2-8, 12, 15; BS:274-282, BS:301, BS:464, BS:532, SA:542; R043, R044, R046, R057, R113, R120.

- [ ] **Step 1: The tests first**

Create `tests/plan_r/test_api_review.py`:
````python
"""T21's API routes over HTTP with the shared fake store (Plan R rulings 2-8, 12 and 15; R043, R044, R057, R093,
R113): the decision's own conflict codes and its lazy expiry, the revision, the cancel, the manual proposal, the
feedback, the search and the approval card.

Catches: a lazy expiry that runs inside the decision's unit (a 409 would roll back the BLOCKED_REVIEW, DEV-008); a
stale, expired or already-decided decision answered with one generic code; a reviewer who revised the run approving
it (R093); a revision, cancel or manual proposal without the IdP's enabled check (SA:542); a requester cancelling
another requester's run; a manual proposal for another asset that writes anything (note 4); a reader allowed to
author or search; feedback text reaching an event; a search that needs an Idempotency-Key or leaks the rank; and an
approval card without its requester, decision, expiry, supersession and submission state.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from tests.plan_g import fakes
from tests.plan_g.fakes import ALEX, CASEY, MORGAN, SAM, FakeStore
from tests.plan_g.test_api_admission import DECISION, client, h, refused

WHEN = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


@pytest.fixture
def api() -> Iterator[tuple[TestClient, FakeStore]]:
    fake = FakeStore()
    with client(fake) as c:
        yield c, fake


def seed_run(fake: FakeStore, state: str, **extra: Any) -> UUID:
    """Alex's run in ALPHA, in `state` at version 5 (what the worker or a decision would leave)."""
    run_id = uuid4()
    fake.runs[run_id] = {
        "run_id": run_id,
        "tenant_id": fakes.ALPHA,
        "conversation_id": uuid4(),
        "requester": ALEX,
        "state": state,
        "state_version": 5,
        "active_proposal_id": None,
        "asset_id": "A17",
        "start_at": WHEN,
        "end_at": WHEN,
        "created_at": WHEN,
        "reason": None,
        **extra,
    }
    return run_id


def seed_proposal(fake: FakeStore, run_id: UUID, **extra: Any) -> UUID:
    pid = uuid4()
    fake.proposals[pid] = {
        "proposal_id": pid,
        "tenant_id": fakes.ALPHA,
        "run_id": run_id,
        "revision": 1,
        "payload": {"k": 1},
        "payload_sha256": "9" * 64,
        "authored_by": [ALEX],
        "requester": ALEX,
        "expires_at": WHEN,
        **extra,
    }
    return pid


def test_a_decision_runs_the_lazy_expiry_first_and_names_each_conflict(api) -> None:
    c, fake = api
    pid = seed_proposal(fake, seed_run(fake, "AWAITING_APPROVAL"))
    url = f"/api/v1/proposals/{pid}/decisions"
    refused(c.post(url, headers=h("sam"), json={**DECISION, "expected_revision": 2}), 409, "STALE_REVISION")
    refused(c.post(url, headers=h("sam"), json={**DECISION, "expected_payload_sha256": "8" * 64}), 409, "STALE_HASH")
    assert fake.expiries == [pid, pid]  # a unit of its own before each decision unit (ruling 5)
    expired = seed_proposal(fake, seed_run(fake, "AWAITING_APPROVAL"), expired=True)
    body = refused(c.post(f"/api/v1/proposals/{expired}/decisions", headers=h("sam"), json=DECISION), 409, "EXPIRED")
    assert body["message"] == "the proposal expired; a revision and a new review are needed"


def test_a_requester_who_also_reviews_and_revised_cannot_approve(api) -> None:
    c, fake = api
    run_id = seed_run(fake, "BLOCKED_REVIEW", reason="expired")
    revised = c.post(f"/api/v1/runs/{run_id}/revisions", headers=h("morgan"), json={"expected_version": 5})
    assert revised.status_code == 202 and revised.json()["revision"] == 2 and revised.json()["status"] == "QUEUED"
    assert fake.runs[run_id]["authors"] == [ALEX, MORGAN] and fake.jobs[-1]["dedup_key"] == f"{run_id}:2"
    pid = seed_proposal(fake, run_id, revision=2, authored_by=fake.runs[run_id]["authors"])
    decision = {**DECISION, "expected_revision": 2}
    refused(c.post(f"/api/v1/proposals/{pid}/decisions", headers=h("morgan"), json=decision), 403, "FORBIDDEN")
    assert c.post(f"/api/v1/proposals/{pid}/decisions", headers=h("sam"), json=decision).status_code == 200


def test_a_revision_is_a_requesters_and_keeps_its_codes(api) -> None:
    c, fake = api
    run_id = seed_run(fake, "APPROVED")
    url = f"/api/v1/runs/{run_id}/revisions"
    refused(c.post(url, headers=h("sam"), json={"expected_version": 5}), 403, "FORBIDDEN")  # a reviewer only
    refused(c.post(url, headers=h("alex"), json={"expected_version": 4}), 409, "VERSION_CONFLICT")
    fake.runs[run_id]["grant"] = True
    refused(c.post(url, headers=h("alex"), json={"expected_version": 5}), 409, "GRANT_EXISTS")  # R090
    blocked = seed_run(fake, "BLOCKED_REVIEW")
    seed_run(fake, "RETRIEVING", conversation_id=fake.runs[blocked]["conversation_id"])  # R120: the slot is taken
    refused(
        c.post(f"/api/v1/runs/{blocked}/revisions", headers=h(), json={"expected_version": 5}), 409, "SLOT_OCCUPIED"
    )
    refused(c.post(f"/api/v1/runs/{uuid4()}/revisions", headers=h(), json={"expected_version": 5}), 404, "NOT_FOUND")
    first = c.post(
        url := f"/api/v1/runs/{seed_run(fake, 'APPROVED')}/revisions",
        headers=h(key="key-revision-01"),
        json={"expected_version": 5},
    )
    assert (
        c.post(url, headers=h(key="key-revision-01"), json={"expected_version": 5}).content == first.content
    )  # a replay


def test_revisions_cancels_and_manual_proposals_ask_the_idp_first(api) -> None:
    c, fake = api
    c.app.state.auth.admin.disabled.add(ALEX)
    run_id = seed_run(fake, "DRAFTING")
    for path, body in (
        (f"/api/v1/runs/{run_id}/revisions", {"expected_version": 5}),
        (f"/api/v1/runs/{run_id}/cancel", {"expected_version": 5}),
        ("/api/v1/manual-proposals", {}),
    ):
        refused(c.post(path, headers=h(), json=body), 401, "UNAUTHENTICATED")  # SA:542, before the body
    assert fake.runs[run_id]["state"] == "DRAFTING" and not fake.records


def test_a_cancel_is_the_runs_requesters_or_a_reviewers_and_never_claims_undo(api) -> None:
    c, fake = api
    run_id = seed_run(fake, "BLOCKED_REVIEW")
    refused(c.post(f"/api/v1/runs/{run_id}/cancel", headers=h("casey"), json={"expected_version": 5}), 403, "FORBIDDEN")
    done = c.post(f"/api/v1/runs/{run_id}/cancel", headers=h("alex"), json={"expected_version": 5})
    assert done.status_code == 200 and done.json()["status"] == "CANCELLED" and done.json()["grant_exists"] is False
    granted = seed_run(fake, "EXECUTING", grant=True)
    after = c.post(f"/api/v1/runs/{granted}/cancel", headers=h("sam"), json={"expected_version": 1})
    assert after.status_code == 200 and after.json()["status"] == "EXECUTING" and after.json()["grant_exists"] is True
    assert after.json()["note"] == "a grant exists; what was dispatched stands, and nothing is undone"
    refused(c.post(f"/api/v1/runs/{run_id}/cancel", headers=h(), json={"expected_version": 6}), 409, "VERSION_CONFLICT")


def manual(run_id: UUID, asset: str = "A17") -> dict[str, Any]:
    return {
        "run_id": str(run_id),
        "asset_id": asset,
        "start_at": "2026-10-24T12:00:00Z",
        "end_at": "2026-10-25T12:00:00Z",
        "title": "Review the warnings",
        "summary": "Two warnings in the interval.",
        "evidence_refs": ["ALPHA-INCIDENT:v2:review"],
        "assumptions": [],
        "limitations": ["Written by a person."],
    }


def test_a_manual_proposal_for_a_run_that_waits_for_one(api) -> None:
    c, fake = api
    run_id = seed_run(fake, "DRAFTING")
    refused(c.post("/api/v1/manual-proposals", headers=h("lee"), json=manual(run_id)), 403, "FORBIDDEN")  # a reader
    refused(c.post("/api/v1/manual-proposals", headers=h(), json=manual(run_id, "B22")), 404, "NOT_FOUND")  # note 4
    assert fake.runs[run_id]["state"] == "DRAFTING" and not fake.proposals  # nothing written
    made = c.post("/api/v1/manual-proposals", headers=h("sam"), json=manual(run_id))
    assert made.status_code == 201 and made.json()["status"] == "AWAITING_APPROVAL"
    assert fake.proposals[UUID(made.json()["proposal_id"])]["authored_by"] == [ALEX, SAM]  # sam may not approve it
    refused(c.post("/api/v1/manual-proposals", headers=h(), json=manual(run_id)), 409, "VERSION_CONFLICT")
    guarded = seed_run(fake, "DRAFTING", blocked_by=uuid4())
    body = refused(c.post("/api/v1/manual-proposals", headers=h(), json=manual(guarded)), 409, "ASSET_INCIDENT_EXISTS")
    assert str(fake.runs[guarded]["blocked_by"]) in body["message"] and fake.runs[guarded]["state"] == "BLOCKED_REVIEW"


def test_feedback_is_any_members_and_its_text_stays_out_of_events(api) -> None:
    c, fake = api
    run_id = seed_run(fake, "SUCCEEDED")
    body = {"subject_kind": "run", "subject_id": str(run_id), "category": "unclear", "text": "Which sensor?"}
    made = c.post(f"/api/v1/runs/{run_id}/feedback", headers=h("lee"), json=body)
    assert made.status_code == 201 and fake.feedback[-1]["text"] == "Which sensor?"
    assert fake.event_log[-1] == {
        "run_id": run_id,
        "type": "feedback.recorded",
        "payload": {"subject_kind": "run", "subject_id": str(run_id), "category": "unclear"},
    }
    other = {**body, "subject_kind": "proposal", "subject_id": str(uuid4())}
    refused(c.post(f"/api/v1/runs/{run_id}/feedback", headers=h("lee"), json=other), 404, "NOT_FOUND")
    refused(c.post(f"/api/v1/runs/{uuid4()}/feedback", headers=h("lee"), json=body), 404, "NOT_FOUND")


def test_the_search_is_an_authors_read_without_a_key(api) -> None:
    c, fake = api
    bearer = {"Authorization": "Bearer alex"}
    assert c.post("/api/v1/search", headers=bearer, json={"query": "bearing temperature"}).status_code == 200
    assert c.post("/api/v1/search", headers={"Authorization": "Bearer lee"}, json={"query": "x"}).status_code == 403
    assert c.post("/api/v1/search", headers=bearer, json={"query": "x", "limit": 11}).status_code == 422
    assert [s.limit for s in fake.searches] == [5]


def test_the_approval_card_and_the_run_snapshot(api) -> None:
    c, fake = api
    run_id = seed_run(fake, "BLOCKED_REVIEW", reason="expired")
    pid = seed_proposal(fake, run_id)
    card = c.get(f"/api/v1/proposals/{pid}", headers=h("sam")).json()
    assert card["requester"] == str(ALEX) and card["decision"] is None and card["expired"] is False
    assert card["supersedes"] is None and card["submission_state"] == {"grant_exists": False, "attempt_state": None}
    assert c.get(f"/api/v1/runs/{run_id}", headers=h()).json()["reason"] == "expired"
    assert CASEY not in fake.runs[run_id].get("authors", [])
````

Run `PYTHONUTF8=1 uv run python -m pytest tests/plan_r/test_api_review.py -q -p no:cacheprovider < /dev/null` → RED, `1
error during collection`: `ImportError: cannot import name 'MORGAN' from 'tests.plan_g.fakes'`.

- [ ] **Step 2: The decision's revision, the store's units and the routes**

Edit 73 (`api/src/ops_api/app.py`), replace:
````python
from ops_core.contracts import ClarificationReply, DecisionRequest, DuplicateKey, ErrorCode, MessageRequest, load
````
with:
````python
from ops_core.contracts import (
    CancelRequest,
    ClarificationReply,
    DecisionRequest,
    DuplicateKey,
    ErrorCode,
    FeedbackRequest,
    ManualProposalRequest,
    MessageRequest,
    RevisionRequest,
    SearchRequest,
    load,
)
````

Edit 74 (`api/src/ops_api/app.py`), replace:
````python
ROUTE_DECISIONS = "POST /api/v1/proposals/{proposal_id}/decisions"
````
with:
````python
ROUTE_DECISIONS = "POST /api/v1/proposals/{proposal_id}/decisions"
ROUTE_REVISIONS = "POST /api/v1/runs/{run_id}/revisions"  # T21 (BS:274)
ROUTE_CANCEL = "POST /api/v1/runs/{run_id}/cancel"  # T21 (BS:276)
ROUTE_MANUAL = "POST /api/v1/manual-proposals"  # T21 (BS:281)
ROUTE_FEEDBACK = "POST /api/v1/runs/{run_id}/feedback"  # T21 (BS:282)
````

Edit 75 (`api/src/ops_api/app.py`), replace:
````python
            if not verifier.ready:
````
with:
````python
                # Revision 0016 (T21): the review, revision, cancel, manual and feedback definers; feedback marks it.
                await persistence.assert_relation(app.state.store.session.conn, "app.feedback")
            if not verifier.ready:
````

Edit 76 (`api/src/ops_api/app.py`), replace:
````python
    async def idempotency_key(request: Request) -> str:
````
with:
````python
    async def enabled_requester(who: Annotated[Identity, Depends(enabled_identity)]) -> Identity:
        """A revision (T21, Plan R ruling 2): any current requester of the tenant, enabled at the IdP (SA:542)."""
        who.require("requester")
        return who

    async def enabled_author(who: Annotated[Identity, Depends(enabled_identity)]) -> Identity:
        """A manual proposal or a search (T21 ruling 7): a current requester or reviewer, enabled (SA:542)."""
        if not who.roles & {"requester", "reviewer"}:
            raise ApiError(403, ErrorCode.FORBIDDEN, "the requester or reviewer role is required")
        return who

    async def idempotency_key(request: Request) -> str:
````

Edit 77 (`api/src/ops_api/app.py`), replace:
````python
    @app.get("/api/v1/runs/{run_id}")
````
with:
````python
    @app.post("/api/v1/runs/{run_id}/revisions")
    async def post_revision(
        run_id: UUID,
        request: Request,
        who: Annotated[Identity, Depends(enabled_requester)],
        key: Annotated[str, Depends(idempotency_key)],
    ) -> Response:
        """BS:274 (T21): a new revision, re-drafted by the worker; the author joins the run's content authors, so a
        reviewer who revises cannot approve it (R093)."""
        revision: RevisionRequest = await body(request, RevisionRequest)
        store: st.Store = request.app.state.store
        idem = scoped(request, who, ROUTE_REVISIONS, key, {"run_id": str(run_id)}, revision)
        try:
            return await recorded(
                request,
                store.revise_once(
                    idem=idem, tenant_id=who.tenant_id, run_id=run_id, author=who.subject, request=revision
                ),
            )
        except st.Forbidden as exc:
            raise ApiError(403, ErrorCode.FORBIDDEN, "a current requester of the tenant is required") from exc

    @app.post("/api/v1/runs/{run_id}/cancel")
    async def post_cancel(
        run_id: UUID,
        request: Request,
        who: Annotated[Identity, Depends(enabled_identity)],
        key: Annotated[str, Depends(idempotency_key)],
    ) -> Response:
        """BS:276 (T21 ruling 12): the run's requester or a current reviewer; the definer decides which."""
        cancel: CancelRequest = await body(request, CancelRequest)
        store: st.Store = request.app.state.store
        idem = scoped(request, who, ROUTE_CANCEL, key, {"run_id": str(run_id)}, cancel)
        try:
            return await recorded(
                request,
                store.cancel_once(idem=idem, tenant_id=who.tenant_id, run_id=run_id, actor=who.subject, request=cancel),
            )
        except st.Forbidden as exc:
            raise ApiError(403, ErrorCode.FORBIDDEN, "the run's requester or a current reviewer is required") from exc

    @app.post("/api/v1/manual-proposals")
    async def post_manual_proposal(
        request: Request,
        who: Annotated[Identity, Depends(enabled_author)],
        key: Annotated[str, Depends(idempotency_key)],
    ) -> Response:
        """BS:281 (T21 ruling 7): a person's proposal for a run the model could not draft for."""
        manual: ManualProposalRequest = await body(request, ManualProposalRequest)
        store: st.Store = request.app.state.store
        idem = scoped(request, who, ROUTE_MANUAL, key, {}, manual)
        try:
            return await recorded(
                request, store.manual_once(idem=idem, tenant_id=who.tenant_id, author=who.subject, request=manual)
            )
        except st.Forbidden as exc:
            raise ApiError(403, ErrorCode.FORBIDDEN, "a current requester or reviewer is required") from exc

    @app.post("/api/v1/runs/{run_id}/feedback")
    async def post_feedback(
        run_id: UUID,
        request: Request,
        who: Annotated[Identity, Depends(browser_mutation)],
        key: Annotated[str, Depends(idempotency_key)],
    ) -> Response:
        """BS:282 (T21 ruling 8): any current member's classified feedback; no runtime effect (R113)."""
        feedback: FeedbackRequest = await body(request, FeedbackRequest)
        store: st.Store = request.app.state.store
        idem = scoped(request, who, ROUTE_FEEDBACK, key, {"run_id": str(run_id)}, feedback)
        return await recorded(
            request,
            store.feedback_once(
                idem=idem, tenant_id=who.tenant_id, run_id=run_id, author=who.subject, request=feedback
            ),
        )

    @app.post("/api/v1/search")
    async def post_search(request: Request, who: Annotated[Identity, Depends(enabled_author)]) -> dict[str, Any]:
        """BS:280 (T21 ruling 7, erratum 135): bounded lexical search over the tenant's permitted sections. A read:
        no Idempotency-Key and no record."""
        search: SearchRequest = await body(request, SearchRequest)
        result: dict[str, Any] = await request.app.state.store.search(who.tenant_id, search)
        return result

    @app.get("/api/v1/runs/{run_id}")
````

Edit 78 (`api/src/ops_api/app.py`), replace:
````python
            "state_version": row["state_version"],
````
with:
````python
            "reason": row.get("reason"),  # T21 (ruling 15): why a run is BLOCKED_REVIEW, REJECTED or FAILED
            "state_version": row["state_version"],
````

Edit 79 (`api/src/ops_api/app.py`), replace:
````python
        row = await request.app.state.store.proposal(who.tenant_id, proposal_id)
        if row is None:
            raise ApiError(404, ErrorCode.NOT_FOUND, "no such proposal")
````
with:
````python
        row = await request.app.state.store.proposal_card(who.tenant_id, proposal_id)
        if row is None:
            raise ApiError(404, ErrorCode.NOT_FOUND, "no such proposal")
        decided = row["decision"] is not None
        supersedes = row["supersedes_run_id"]
````

Edit 80 (`api/src/ops_api/app.py`), replace:
````python
            "expires_at": stamp(row["expires_at"]),
````
with:
````python
            "expires_at": stamp(row["expires_at"]),
            # T21 (ruling 15; BS:464, BS:532): the approval card's facts. T26 renders them.
            "requester": str(row["requester"]),
            "expired": bool(row["expired"]),
            "decision": (
                {"decision": row["decision"], "reviewer": str(row["reviewer"]), "decided_at": stamp(row["decided_at"])}
                if decided
                else None
            ),
            "supersedes": (
                None
                if supersedes is None
                else {"run_id": str(supersedes), "incident_id": row["superseded_incident_id"]}
            ),
            "submission_state": {"grant_exists": bool(row["grant_exists"]), "attempt_state": row["attempt_state"]},
````

Edit 81 (`api/src/ops_api/store.py`), replace:
````python
which RLS scopes. T11: the session store (login_state, sessions, logout_jti).
````
with:
````python
which RLS scopes. T11: the session store (login_state, sessions, logout_jti). T21: the lazy expiry in a unit of its
own before a decision, revisions, cancels, manual proposals (two definer calls with the canonical bytes built between
them), feedback, the manual baseline's search and the approval card.
````

Edit 82 (`api/src/ops_api/store.py`), replace:
````python
from typing import Any, Protocol
from uuid import UUID, uuid4

import psycopg
from ops_core import persistence
from ops_core.contracts import (
    ClarificationReply,
    DecisionRequest,
    ErrorCode,
    MessageKind,
    MessageRequest,
````
with:
````python
from typing import Any, Final, Protocol
from uuid import UUID, uuid4

import psycopg
from ops_core import persistence
from ops_core.canonical import canonical_json
from ops_core.contracts import (
    CancelRequest,
    CancelResponse,
    ClarificationReply,
    DecisionRequest,
    ErrorCode,
    FeedbackRequest,
    ManualProposalRequest,
    MessageKind,
    MessageRequest,
    ProposalPayload,
    RevisionRequest,
    SearchRequest,
    SourceSnapshot,
````

Edit 83 (`api/src/ops_api/store.py`), replace:
````python
@dataclass(frozen=True)
class Membership:
````
with:
````python
class Recorded(ReplyRefused):
    """A refusal of T21's revision, cancel, manual-proposal or feedback unit that the unit records as its answer (the
    run's or the request's state decided it, BS:301); a refusal of the caller is Forbidden instead, never recorded."""


@dataclass(frozen=True)
class Membership:
````

Edit 84 (`api/src/ops_api/store.py`), replace:
````python
def map_refusal(exc: persistence.Refused) -> Exception:
    """A function's DETAIL code → the HTTP class BUILD_SPEC §7 names; the code itself never reaches the client."""
    if exc.code in ("NOT_REVIEWER", "SELF_REVIEW", "MEMBERSHIP_INACTIVE"):
        return Forbidden()
    if exc.code == "SLOT_OCCUPIED":
        return Conflict("SLOT_OCCUPIED")
    if exc.code == "INVALID_ARGUMENT":
        return Internal()  # the API's own validation makes this unreachable; a 409 would be a false message
    return Conflict("VERSION_CONFLICT")


````
with:
````python
# The definers' refusals of the caller (BS:301: a known resource, a disallowed operation), and the refusals of the
# run's state that keep their own code (SA:764; T21, Plan R rulings 2, 4, 6 and 7).
CALLER_REFUSALS: Final = frozenset(
    {"NOT_REVIEWER", "SELF_REVIEW", "MEMBERSHIP_INACTIVE", "NOT_REQUESTER", "NOT_CANCELLER", "NOT_AUTHOR"}
)
STATE_REFUSALS: Final = frozenset({"SLOT_OCCUPIED", "GRANT_EXISTS", "AUTHOR_LIMIT"})
# One message per 409 code (T21, Plan R ruling 3; Plan G final review M3: no conflict borrows another's message).
CONFLICT_MESSAGES: Final = {
    ErrorCode.ALREADY_DECIDED: "the proposal is already decided",
    ErrorCode.STALE_REVISION: "the proposal is not the run's active revision",
    ErrorCode.STALE_HASH: "the payload hash is not the proposal's",
    ErrorCode.EXPIRED: "the proposal expired; a revision and a new review are needed",
    ErrorCode.VERSION_CONFLICT: "the run is not in a state that allows this at that version",
    ErrorCode.GRANT_EXISTS: "a grant exists for the run; it can no longer be revised",
    ErrorCode.SLOT_OCCUPIED: "the conversation already has an active run",
    ErrorCode.AUTHOR_LIMIT: "the run already has eight content authors",
}


def map_refusal(exc: persistence.Refused) -> Exception:
    """A function's DETAIL code → the HTTP class BUILD_SPEC §7 names; the code itself never reaches the client."""
    if exc.code in CALLER_REFUSALS:
        return Forbidden()
    if exc.code in STATE_REFUSALS:
        return Conflict(exc.code)
    if exc.code == "INVALID_ARGUMENT":
        return Internal()  # the API's own validation makes this unreachable; a 409 would be a false message
    return Conflict("VERSION_CONFLICT")


def recorded_refusal(exc: persistence.Refused) -> Exception:
    """`map_refusal` for T21's units: a refusal of the caller stays Forbidden (unrecorded), a refusal of the run's
    state becomes the 409 the unit records."""
    mapped = map_refusal(exc)
    if isinstance(mapped, Conflict):
        code = ErrorCode(mapped.code)
        return Recorded(409, code, CONFLICT_MESSAGES[code])
    return mapped


````

Edit 85 (`api/src/ops_api/store.py`), replace:
````python

Work = Callable[[Unit], Awaitable[Verdict]]
````
with:
````python
    async def decision_of(self, proposal_id: UUID) -> dict[str, Any] | None:
        """The proposal's recorded decision (`decision`, `reviewer`, `decided_at`), or None."""
        ...

    async def expire(self, proposal_id: UUID) -> None:
        """`expire_proposal` for the proposal's run (T21 ruling 5): BLOCKED_REVIEW(expired) when it is due."""
        ...

    async def revise(self, *, run_id: UUID, author: UUID, request: RevisionRequest) -> persistence.Revised:
        """`create_revision` within the unit; Recorded leaves the unit usable, Forbidden ends it."""
        ...

    async def cancel(self, *, run_id: UUID, actor: UUID, request: CancelRequest) -> persistence.Cancelled:
        """`request_cancel` within the unit; Recorded leaves the unit usable, Forbidden ends it."""
        ...

    async def manual_proposal(self, *, author: UUID, request: ManualProposalRequest) -> persistence.Frozen:
        """`prepare_manual_proposal`, the canonical bytes, then `create_manual_proposal`, within the unit (ruling 7);
        Recorded leaves the unit usable, Forbidden ends it."""
        ...

    async def feedback(self, *, run_id: UUID, author: UUID, request: FeedbackRequest) -> UUID:
        """The feedback row and `feedback.recorded` within the unit (ruling 8); Recorded (404) leaves it usable."""
        ...


Work = Callable[[Unit], Awaitable[Verdict]]
````

Edit 86 (`api/src/ops_api/store.py`), replace:
````python
        return await self._idempotent(tenant_id, idem, work)

    async def decide_once(
````
with:
````python
        return await self._idempotent(tenant_id, idem, work)

    async def expire_due(self, tenant_id: UUID, proposal_id: UUID) -> None:
        """The lazy expiry in its own unit, before the decision's (T21, Plan R ruling 5): an expired proposal's
        BLOCKED_REVIEW(expired) and `review.blocked` commit whatever the decision then answers (DEV-008)."""
        async with self.unit(tenant_id) as unit:
            await unit.expire(proposal_id)

    async def decide_once(
````

Edit 87 (`api/src/ops_api/store.py`), replace:
````python
        """The first decision on the exact revision and hash by an independent current reviewer (SA:454); the key
        is also stored on the decision row (ruling 21). A reviewer refusal raises Forbidden: never recorded."""
        rid = idem.request_id
````
with:
````python
        """The first decision on the exact revision and hash by an independent current reviewer of an unexpired
        proposal (SA:454); the key is also stored on the decision row (ruling 21). A reviewer refusal raises Forbidden:
        never recorded. The checks here are early answers; `record_decision` checks every rule again under the runs
        lock and decides (T21, Plan R ruling 3)."""
        rid = idem.request_id
        await self.expire_due(tenant_id, proposal_id)
````

Edit 88 (`api/src/ops_api/store.py`), replace:
````python
            stale = "the proposal is not the active, undecided revision"
            if row["revision"] != request.expected_revision:
                return error_verdict(409, ErrorCode.VERSION_CONFLICT, stale, rid)
````
with:
````python
            if row["revision"] != request.expected_revision:
                stale = CONFLICT_MESSAGES[ErrorCode.STALE_REVISION]
                return error_verdict(409, ErrorCode.STALE_REVISION, stale, rid)
````

Edit 89 (`api/src/ops_api/store.py`), replace:
````python
                return error_verdict(409, ErrorCode(exc.code), stale, rid)
````
with:
````python
                code = ErrorCode(exc.code)
                message = CONFLICT_MESSAGES[code]
                recorded = await unit.decision_of(proposal_id) if code is ErrorCode.ALREADY_DECIDED else None
                if recorded is not None:  # ruling 3: the answer names the decision that stands
                    message = f"{message}: {recorded['decision']} at {stamp(recorded['decided_at'])}"
                return error_verdict(409, code, message, rid)
````

Edit 90 (`api/src/ops_api/store.py`), replace:
````python

class Store(Protocol):
````
with:
````python
    async def revise_once(
        self, *, idem: Idem, tenant_id: UUID, run_id: UUID, author: UUID, request: RevisionRequest
    ) -> Verdict:
        """BS:274: a new revision of the run, re-drafted by the worker (T21, Plan R rulings 1, 2, 4 and 6); 202."""

        async def work(unit: Unit) -> Verdict:
            try:
                revised = await unit.revise(run_id=run_id, author=author, request=request)
            except Recorded as exc:
                return error_verdict(exc.status, exc.code, exc.message, idem.request_id)
            return Verdict(
                202,
                {
                    "run_id": str(run_id),
                    "status": RunState.QUEUED.value,
                    "state_version": revised.state_version,
                    "revision": revised.revision,
                    "status_url": f"/api/v1/runs/{run_id}",
                    "events_url": f"/api/v1/runs/{run_id}/events",
                },
            )

        return await self._idempotent(tenant_id, idem, work)

    async def cancel_once(
        self, *, idem: Idem, tenant_id: UUID, run_id: UUID, actor: UUID, request: CancelRequest
    ) -> Verdict:
        """BS:276: CANCELLED before a grant; after one, the flag and the attempt's state, never an undo (T21
        ruling 12)."""

        async def work(unit: Unit) -> Verdict:
            try:
                done = await unit.cancel(run_id=run_id, actor=actor, request=request)
            except Recorded as exc:
                return error_verdict(exc.status, exc.code, exc.message, idem.request_id)
            note = "a grant exists; what was dispatched stands, and nothing is undone" if done.grant_exists else None
            body = CancelResponse(
                run_id=done.run_id,
                status=done.state,
                state_version=done.state_version,
                cancel_requested=True,
                grant_exists=done.grant_exists,
                attempt_state=done.attempt_state,
                note=note,
            )
            return Verdict(200, body.model_dump(mode="json"))

        return await self._idempotent(tenant_id, idem, work)

    async def manual_once(
        self, *, idem: Idem, tenant_id: UUID, author: UUID, request: ManualProposalRequest
    ) -> Verdict:
        """BS:281: a person's proposal for a run the model could not draft for, through the freeze rules and the asset
        guard (T21 ruling 7); 201, or the guard's 409 with the run's BLOCKED_REVIEW committed (SA:289)."""

        async def work(unit: Unit) -> Verdict:
            try:
                frozen = await unit.manual_proposal(author=author, request=request)
            except Recorded as exc:
                return error_verdict(exc.status, exc.code, exc.message, idem.request_id)
            if frozen.proposal_id is None:
                reason = frozen.reason.value if frozen.reason is not None else "asset guard"
                return error_verdict(
                    409,
                    ErrorCode(reason.upper()),
                    f"{reason}: blocked by run {frozen.blocking_run_id}",
                    idem.request_id,
                )
            return Verdict(
                201,
                {
                    "proposal_id": str(frozen.proposal_id),
                    "run_id": str(request.run_id),
                    "revision": frozen.revision,
                    "status": frozen.state.value,
                    "state_version": frozen.state_version,
                },
            )

        return await self._idempotent(tenant_id, idem, work)

    async def feedback_once(
        self, *, idem: Idem, tenant_id: UUID, run_id: UUID, author: UUID, request: FeedbackRequest
    ) -> Verdict:
        """BS:282: classified feedback stored for later review, `feedback.recorded` emitted, nothing else (R113);
        201."""

        async def work(unit: Unit) -> Verdict:
            try:
                feedback_id = await unit.feedback(run_id=run_id, author=author, request=request)
            except Recorded as exc:
                return error_verdict(exc.status, exc.code, exc.message, idem.request_id)
            return Verdict(201, {"feedback_id": str(feedback_id), "run_id": str(run_id)})

        return await self._idempotent(tenant_id, idem, work)


class Store(Protocol):
````

Edit 91 (`api/src/ops_api/store.py`), replace:
````python
    async def run(self, tenant_id: UUID, run_id: UUID) -> dict[str, Any] | None:
        """Read one run row in the tenant."""
````
with:
````python
    async def revise_once(
        self, *, idem: Idem, tenant_id: UUID, run_id: UUID, author: UUID, request: RevisionRequest
    ) -> Verdict:
        """Create a revision of the run (idempotent)."""
        ...

    async def cancel_once(
        self, *, idem: Idem, tenant_id: UUID, run_id: UUID, actor: UUID, request: CancelRequest
    ) -> Verdict:
        """Cancel the run, or request it once a grant exists (idempotent)."""
        ...

    async def manual_once(
        self, *, idem: Idem, tenant_id: UUID, author: UUID, request: ManualProposalRequest
    ) -> Verdict:
        """Freeze a person's proposal (idempotent)."""
        ...

    async def feedback_once(
        self, *, idem: Idem, tenant_id: UUID, run_id: UUID, author: UUID, request: FeedbackRequest
    ) -> Verdict:
        """Record classified feedback (idempotent)."""
        ...

    async def search(self, tenant_id: UUID, request: SearchRequest) -> dict[str, Any]:
        """The manual baseline's lexical search over the tenant's permitted sections."""
        ...

    async def run(self, tenant_id: UUID, run_id: UUID) -> dict[str, Any] | None:
        """Read one run row in the tenant."""
````

Edit 92 (`api/src/ops_api/store.py`), replace:
````python
    async def events(self, tenant_id: UUID, run_id: UUID, *, after: int, limit: int) -> list[dict[str, Any]]:
        """List a run's events after a sequence number."""
        ...
````
with:
````python
    async def proposal_card(self, tenant_id: UUID, proposal_id: UUID) -> dict[str, Any] | None:
        """The approval card: the proposal with its decision, expiry, supersession and submission state."""
        ...

    async def events(self, tenant_id: UUID, run_id: UUID, *, after: int, limit: int) -> list[dict[str, Any]]:
        """List a run's events after a sequence number."""
        ...
````

Edit 93 (`api/src/ops_api/store.py`), replace:
````python
                    expected_payload_sha256=request.expected_payload_sha256,
````
with:
````python
                    expected_revision=request.expected_revision,
                    expected_payload_sha256=request.expected_payload_sha256,
````

Edit 94 (`api/src/ops_api/store.py`), replace:
````python
            raise Conflict("VERSION_CONFLICT") from exc
        except persistence.Refused as exc:
            raise map_refusal(exc) from exc
        return Decided(proposal_id, decided.run_id, request.decision, decided.state.value, decided.state_version)

````
with:
````python
            # T21: the definer names the rule that refused (Plan R ruling 3); an unnamed one is a version conflict.
            known = exc.code in {c.value for c in CONFLICT_MESSAGES}
            raise Conflict(exc.code if known and exc.code is not None else "VERSION_CONFLICT") from exc
        except persistence.Refused as exc:
            raise map_refusal(exc) from exc
        return Decided(proposal_id, decided.run_id, request.decision, decided.state.value, decided.state_version)

    async def decision_of(self, proposal_id: UUID) -> dict[str, Any] | None:
        """The recorded decision, for the ALREADY_DECIDED answer (`api` reads decisions, AM-20.2)."""
        cur = await self.conn.execute(
            "SELECT decision, reviewer, decided_at FROM app.decisions WHERE proposal_id = %s", (proposal_id,)
        )
        row = await cur.fetchone()
        return None if row is None else dict(row)

    async def expire(self, proposal_id: UUID) -> None:
        """`expire_proposal` for the proposal's run in this tenant; an unknown proposal is the decision's 404."""
        row = await self.proposal(proposal_id)
        if row is not None:
            await persistence.expire_proposal(self.conn, row["run_id"])

    async def revise(self, *, run_id: UUID, author: UUID, request: RevisionRequest) -> persistence.Revised:
        """`create_revision` in a savepoint, its refusals mapped (T21 rulings 2 and 6)."""
        try:
            async with self.conn.transaction():
                return await persistence.create_revision(
                    self.conn,
                    tenant_id=self.tenant_id,
                    run_id=run_id,
                    expected_version=request.expected_version,
                    author=author,
                    supersedes_run_id=request.supersedes_run_id,
                )
        except persistence.NotFound as exc:
            what = "no such superseded run" if str(exc).endswith("supersedes_run_id") else "no such run"
            raise Recorded(404, ErrorCode.NOT_FOUND, what) from exc
        except persistence.VersionConflict as exc:
            raise Recorded(409, ErrorCode.VERSION_CONFLICT, CONFLICT_MESSAGES[ErrorCode.VERSION_CONFLICT]) from exc
        except persistence.Refused as exc:
            raise recorded_refusal(exc) from exc

    async def cancel(self, *, run_id: UUID, actor: UUID, request: CancelRequest) -> persistence.Cancelled:
        """`request_cancel` in a savepoint, its refusals mapped (T21 ruling 12)."""
        try:
            async with self.conn.transaction():
                return await persistence.request_cancel(
                    self.conn,
                    tenant_id=self.tenant_id,
                    run_id=run_id,
                    expected_version=request.expected_version,
                    actor=actor,
                )
        except persistence.NotFound as exc:
            raise Recorded(404, ErrorCode.NOT_FOUND, "no such run") from exc
        except persistence.VersionConflict as exc:
            raise Recorded(409, ErrorCode.VERSION_CONFLICT, CONFLICT_MESSAGES[ErrorCode.VERSION_CONFLICT]) from exc
        except persistence.Refused as exc:
            raise recorded_refusal(exc) from exc

    async def manual_proposal(self, *, author: UUID, request: ManualProposalRequest) -> persistence.Frozen:
        """The run's facts under the asset guard's lock and the run's lock, the payload built and canonicalised here
        (the one canonicaliser, `ops_core.canonical`), then the freeze; all in one savepoint (T21 ruling 7). Note 4:
        another asset or a section that is not the tenant's is 404 with nothing written."""
        try:
            async with self.conn.transaction():
                facts = await persistence.prepare_manual_proposal(
                    self.conn,
                    tenant_id=self.tenant_id,
                    run_id=request.run_id,
                    author=author,
                    evidence_ids=request.evidence_refs,
                )
                if request.asset_id != facts.asset_id:
                    raise Recorded(404, ErrorCode.NOT_FOUND, "no such run, asset or permitted section")
                if (request.start_at, request.end_at) != (facts.start_at, facts.end_at):
                    raise Recorded(422, ErrorCode.INVALID_INPUT, "the interval is the run's own (SA:154)")
                payload = ProposalPayload(
                    tenant_id=self.tenant_id,
                    run_id=request.run_id,
                    proposal_id=uuid4(),
                    revision=facts.revision,
                    action="create_incident",
                    destination="synthetic-incidents",
                    asset_id=facts.asset_id,
                    start_at=facts.start_at.astimezone(UTC),
                    end_at=facts.end_at.astimezone(UTC),
                    title=request.title,
                    summary=request.summary,
                    evidence_refs=sorted(request.evidence_refs),
                    source_snapshots=[SourceSnapshot.model_validate(s) for s in facts.snapshots],
                    assumptions=list(request.assumptions),
                    limitations=list(request.limitations),
                    workflow_version=facts.workflow_version,
                    prompt_version="manual",  # ruling 7: a person drafted it
                    expires_at=facts.expires_at.astimezone(UTC),
                    supersedes_run_id=facts.supersedes_run_id,
                )
                return await persistence.create_manual_proposal(
                    self.conn,
                    tenant_id=self.tenant_id,
                    run_id=request.run_id,
                    payload_canonical=canonical_json(payload.canonical_dict()),
                    author=author,
                )
        except persistence.NotFound as exc:
            raise Recorded(404, ErrorCode.NOT_FOUND, "no such run, asset or permitted section") from exc
        except persistence.VersionConflict as exc:
            raise Recorded(409, ErrorCode.VERSION_CONFLICT, "the run does not wait for a manual proposal") from exc
        except persistence.Refused as exc:
            mapped = recorded_refusal(exc)
            # Any other refusal names a payload field the API took from the run itself: a defect, not the caller's.
            raise (mapped if isinstance(mapped, (Forbidden, Recorded)) else Internal(exc.code)) from exc

    async def feedback(self, *, run_id: UUID, author: UUID, request: FeedbackRequest) -> UUID:
        """The subject must be the run, one of its proposals or one of its events (404 otherwise); then the event and
        the row, in a savepoint (T21 ruling 8). The text goes into the row only, never an event or a log line."""
        subject = {
            "run": "SELECT 1 FROM app.runs WHERE run_id = %s AND run_id = %s",
            "proposal": "SELECT 1 FROM app.proposals WHERE proposal_id = %s AND run_id = %s",
            "event": "SELECT 1 FROM app.events WHERE event_id = %s AND run_id = %s",
        }[request.subject_kind]
        cur = await self.conn.execute(subject, (request.subject_id, run_id))
        if await cur.fetchone() is None:  # RLS hides another tenant's rows, so theirs read as absent too
            raise Recorded(404, ErrorCode.NOT_FOUND, "no such run or subject")
        feedback_id = uuid4()
        async with self.conn.transaction():
            await persistence.append_event(
                self.conn,
                run_id=run_id,
                type=EventType.FEEDBACK_RECORDED,
                payload={
                    "subject_kind": request.subject_kind,
                    "subject_id": str(request.subject_id),
                    "category": request.category,
                },
            )
            await self.conn.execute(
                "INSERT INTO app.feedback (feedback_id, tenant_id, run_id, subject_kind, subject_id, category, text,"
                " author, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, app.current_time())",
                (
                    feedback_id,
                    self.tenant_id,
                    run_id,
                    request.subject_kind,
                    request.subject_id,
                    request.category,
                    request.text,
                    author,
                ),
            )
        return feedback_id

````

Edit 95 (`api/src/ops_api/store.py`), replace:
````python
            return await unit.proposal(proposal_id)

````
with:
````python
            return await unit.proposal(proposal_id)

    async def proposal_card(self, tenant_id: UUID, proposal_id: UUID) -> dict[str, Any] | None:
        """The approval card's facts (BS:464, BS:532; T21 ruling 15): the proposal and its run's requester, the
        decision that stands, whether it expired on the application clock, the superseded run with the incident its
        receipt named, and the run's grant and latest attempt state. Read in one tenant unit."""
        async with self.session.unit(tenant_id) as conn:
            cur = await conn.execute(
                "SELECT p.*, r.requester, r.supersedes_run_id, p.expires_at < app.current_time() AS expired,"
                " d.decision, d.reviewer, d.decided_at,"
                " g.action_id IS NOT NULL AS grant_exists,"
                " (SELECT s.state FROM app.action_attempt_state s WHERE s.action_id = g.action_id"
                "  ORDER BY s.attempt_no DESC, s.seq DESC LIMIT 1) AS attempt_state,"
                " (SELECT e.payload->'receipt'->>'incident_id' FROM app.events e WHERE e.run_id = r.supersedes_run_id"
                "  AND e.type IN ('action.confirmed', 'action.late_evidence') AND e.payload ? 'receipt'"
                "  ORDER BY e.sequence DESC LIMIT 1) AS superseded_incident_id"
                " FROM app.proposals p JOIN app.runs r ON r.run_id = p.run_id"
                " LEFT JOIN app.decisions d ON d.proposal_id = p.proposal_id"
                " LEFT JOIN app.execution_grant g ON g.run_id = p.run_id AND g.proposal_id = p.proposal_id"
                " WHERE p.proposal_id = %s AND p.tenant_id = %s",
                (proposal_id, tenant_id),
            )
            row = await cur.fetchone()
        return None if row is None else dict(row)

    async def search(self, tenant_id: UUID, request: SearchRequest) -> dict[str, Any]:
        """`search_procedures_api` under the session's tenant (T21 ruling 7); the rank stays inside (BS:417)."""
        async with self.session.unit() as conn:  # the function sets its own tenant from the argument
            found = await persistence.search_procedures_api(
                conn, tenant_id=tenant_id, query=request.query, limit=request.limit
            )
        return {
            "corpus_version": found.corpus_version,
            "retrieved_at": stamp(found.retrieved_at),
            "truncated": found.truncated,
            "results": [
                {
                    "evidence_id": hit.evidence_id,
                    "document_id": hit.document_id,
                    "version": hit.version,
                    "section": hit.section,
                    "content_sha256": hit.content_sha256,
                    "excerpt": hit.excerpt,
                    "effective_from": stamp(hit.effective_from),
                }
                for hit in found.results
            ],
        }

````

Edit 96 (`core/src/ops_core/persistence.py`), replace:
````python
    expected_payload_sha256: str,
    decision: str,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> Decided:
    """First decision wins on the exact hash by an independent current reviewer (SA:454)."""
    row = await _call(
        conn,
        "SELECT * FROM app.record_decision(%s, %s, %s, %s, %s, %s, %s)",
        (tenant_id, proposal_id, reviewer, expected_payload_sha256, decision, reason, idempotency_key),
````
with:
````python
    expected_revision: int,
    expected_payload_sha256: str,
    decision: str,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> Decided:
    """First decision wins on the exact revision and hash by an independent current reviewer of an unexpired proposal
    (SA:454; T21: the revision checked under the lock too, erratum 131).

    Raises:
        Refused: NOT_REVIEWER or SELF_REVIEW (the API's unrecorded 403).
        VersionConflict: `code` ALREADY_DECIDED, STALE_REVISION, STALE_HASH or EXPIRED.
    """
    row = await _call(
        conn,
        "SELECT * FROM app.record_decision(%s, %s, %s, %s, %s, %s, %s, %s)",
        (
            tenant_id,
            proposal_id,
            reviewer,
            expected_revision,
            expected_payload_sha256,
            decision,
            reason,
            idempotency_key,
        ),
````

Edit 97 (`tests/plan_d/test_api.py`), replace:
````python
    assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"
````
with:
````python
    assert stale.status_code == 409 and stale.json()["code"] == "STALE_REVISION"  # T21: its own code (ruling 3)
````

Edit 98 (`tests/plan_g/fakes.py`), replace:
````python
from ops_api.store import Accepted, Conflict, Decided, LoginState, NotFound, ReplyRefused, SessionRow
from ops_core.contracts import DecisionRequest, ErrorCode, StoredMessageKind
from ops_core.states import ACTIVE_STATES, Intent
````
with:
````python
from ops_api.store import Accepted, Conflict, Decided, LoginState, NotFound, Recorded, ReplyRefused, SessionRow
from ops_core import persistence
from ops_core.contracts import (
    CancelRequest,
    DecisionRequest,
    ErrorCode,
    FeedbackRequest,
    ManualProposalRequest,
    RevisionRequest,
    SearchRequest,
    StoredMessageKind,
)
from ops_core.states import ACTIVE_STATES, PRE_GRANT_STATES, Intent, Reason, RunState
````

Edit 99 (`tests/plan_g/fakes.py`), replace:
````python
PERSONAS = {"alex": ALEX, "sam": SAM, "lee": LEE, "jordan": JORDAN, "riley": RILEY, "dual": DUAL, "casey": CASEY}
````
with:
````python
MORGAN = UUID("33333333-4444-5555-8666-777777777777")  # T21: ALPHA's requester and reviewer at once (fake-only, R093)
PERSONAS = {
    "alex": ALEX,
    "sam": SAM,
    "lee": LEE,
    "jordan": JORDAN,
    "riley": RILEY,
    "dual": DUAL,
    "casey": CASEY,
    "morgan": MORGAN,
}
````

Edit 100 (`tests/plan_g/fakes.py`), replace:
````python
}
ACTIVE = {state.value for state in ACTIVE_STATES}
TABLES = ("conversations", "messages", "runs", "jobs", "event_log", "records", "proposals", "decided", "decision_keys")
````
with:
````python
    MORGAN: [(ALPHA, "requester"), (ALPHA, "reviewer")],
}
ACTIVE = {state.value for state in ACTIVE_STATES}
TABLES = (
    "conversations",
    "messages",
    "runs",
    "jobs",
    "event_log",
    "records",
    "proposals",
    "decided",
    "decision_keys",
    "decisions",
    "feedback",
)
````

Edit 101 (`tests/plan_g/fakes.py`), replace:
````python
        if row["payload_sha256"] != request.expected_payload_sha256 or proposal_id in self.fake.decided:
            raise Conflict("VERSION_CONFLICT")  # a stale hash, or the first decision already won
        self.fake.decided.add(proposal_id)
        self.fake.decision_keys[proposal_id] = key
        status = "APPROVED" if request.decision == "approve" else "REJECTED"
        return Decided(proposal_id, row["run_id"], request.decision, status, 5)

````
with:
````python
        # T21: the definer's codes, in its order (first decision wins, then the hash, then the expiry).
        if proposal_id in self.fake.decided:
            raise Conflict("ALREADY_DECIDED")
        if row["payload_sha256"] != request.expected_payload_sha256:
            raise Conflict("STALE_HASH")
        if row.get("expired"):
            raise Conflict("EXPIRED")
        self.fake.decided.add(proposal_id)
        self.fake.decision_keys[proposal_id] = key
        self.fake.decisions[proposal_id] = {
            "decision": request.decision,
            "reviewer": reviewer,
            "decided_at": datetime.fromtimestamp(self.fake.clock(), UTC),
        }
        status = "APPROVED" if request.decision == "approve" else "REJECTED"
        return Decided(proposal_id, row["run_id"], request.decision, status, 5)

    async def decision_of(self, proposal_id: UUID) -> dict[str, Any] | None:
        return self.fake.decisions.get(proposal_id)

    async def expire(self, proposal_id: UUID) -> None:
        self.fake.expiries.append(proposal_id)  # the lazy expiry ran in a unit of its own, before the decision's

    def _run(self, run_id: UUID) -> dict[str, Any]:
        row = self.fake.runs.get(run_id)
        if row is None or row["tenant_id"] != self.tenant_id:
            raise Recorded(404, ErrorCode.NOT_FOUND, "no such run")
        return row

    async def revise(self, *, run_id: UUID, author: UUID, request: RevisionRequest) -> persistence.Revised:
        # create_revision's rules in its order (revision 0016): the author's role, the grant, the state and version,
        # the author cap, the conversation's slot.
        row = self._run(run_id)
        if (self.tenant_id, "requester") not in ROWS.get(author, []):
            raise store.Forbidden
        if row.get("grant"):
            raise Recorded(409, ErrorCode.GRANT_EXISTS, store.CONFLICT_MESSAGES[ErrorCode.GRANT_EXISTS])
        if row["state"] not in ("AWAITING_APPROVAL", "APPROVED", "BLOCKED_REVIEW") or (
            row["state_version"] != request.expected_version
        ):
            raise Recorded(409, ErrorCode.VERSION_CONFLICT, store.CONFLICT_MESSAGES[ErrorCode.VERSION_CONFLICT])
        authors = row.setdefault("authors", [row["requester"]])
        if author not in authors and len(authors) >= 8:
            raise Recorded(409, ErrorCode.AUTHOR_LIMIT, store.CONFLICT_MESSAGES[ErrorCode.AUTHOR_LIMIT])
        others = [r for r in self._runs_of(row["conversation_id"]) if r["run_id"] != run_id and r["state"] in ACTIVE]
        if row["state"] == "BLOCKED_REVIEW" and others:
            raise Recorded(409, ErrorCode.SLOT_OCCUPIED, store.CONFLICT_MESSAGES[ErrorCode.SLOT_OCCUPIED])
        if author not in authors:
            authors.append(author)
        row["revision"] = row.get("revision", 1) + 1
        row["state"], row["state_version"], row["active_proposal_id"] = "QUEUED", row["state_version"] + 1, None
        self.fake.jobs.append({"type": "investigate", "run_id": run_id, "dedup_key": f"{run_id}:{row['revision']}"})
        return persistence.Revised(run_id, row["state_version"], row["revision"])

    async def cancel(self, *, run_id: UUID, actor: UUID, request: CancelRequest) -> persistence.Cancelled:
        row = self._run(run_id)
        roles = {role for tenant, role in ROWS.get(actor, []) if tenant == self.tenant_id}
        if not ("reviewer" in roles or ("requester" in roles and row["requester"] == actor)):
            raise store.Forbidden
        row["cancel_requested"] = True
        if row.get("grant"):  # the flag only; mark_sent decides (SA:458)
            return persistence.Cancelled(run_id, RunState(row["state"]), row["state_version"], True, None)
        if row["state"] not in PRE_GRANT_STATES or row["state_version"] != request.expected_version:
            raise Recorded(409, ErrorCode.VERSION_CONFLICT, store.CONFLICT_MESSAGES[ErrorCode.VERSION_CONFLICT])
        row["state"], row["state_version"] = "CANCELLED", row["state_version"] + 1
        return persistence.Cancelled(run_id, RunState.CANCELLED, row["state_version"], False, None)

    async def manual_proposal(self, *, author: UUID, request: ManualProposalRequest) -> persistence.Frozen:
        row = self._run(request.run_id)
        roles = {role for tenant, role in ROWS.get(author, []) if tenant == self.tenant_id}
        if not roles & {"requester", "reviewer"}:
            raise store.Forbidden
        if row["state"] != "DRAFTING" or row.get("checkpoint_id") is not None:
            raise Recorded(409, ErrorCode.VERSION_CONFLICT, "the run does not wait for a manual proposal")
        if request.asset_id != row["asset_id"]:  # note 4: nothing written
            raise Recorded(404, ErrorCode.NOT_FOUND, "no such run, asset or permitted section")
        if row.get("blocked_by") is not None:  # the asset guard's refusal commits BLOCKED_REVIEW (SA:289)
            row["state"], row["state_version"] = "BLOCKED_REVIEW", row["state_version"] + 1
            reason = Reason.ASSET_INCIDENT_EXISTS
            return persistence.Frozen(None, 1, RunState.BLOCKED_REVIEW, reason, row["state_version"], row["blocked_by"])
        pid = uuid4()
        row["state"], row["state_version"], row["active_proposal_id"] = (
            "AWAITING_APPROVAL",
            row["state_version"] + 1,
            pid,
        )
        self.fake.proposals[pid] = {
            "proposal_id": pid,
            "tenant_id": self.tenant_id,
            "run_id": request.run_id,
            "revision": 1,
            "payload_sha256": "7" * 64,
            "authored_by": [row["requester"], author] if author != row["requester"] else [author],
            "requester": row["requester"],
        }
        return persistence.Frozen(pid, 1, RunState.AWAITING_APPROVAL, None, row["state_version"])

    async def feedback(self, *, run_id: UUID, author: UUID, request: FeedbackRequest) -> UUID:
        self._run(run_id)
        found = {
            "run": request.subject_id == run_id,
            "proposal": any(
                p["run_id"] == run_id for p in self.fake.proposals.values() if p["proposal_id"] == request.subject_id
            ),
            "event": any(
                e.get("event_id") == request.subject_id and e["run_id"] == run_id for e in self.fake.event_log
            ),
        }[request.subject_kind]
        if not found:
            raise Recorded(404, ErrorCode.NOT_FOUND, "no such run or subject")
        feedback_id = uuid4()
        payload = {
            "subject_kind": request.subject_kind,
            "subject_id": str(request.subject_id),
            "category": request.category,
        }
        self.fake.event_log.append({"run_id": run_id, "type": "feedback.recorded", "payload": payload})
        self.fake.feedback.append(
            {"feedback_id": feedback_id, "run_id": run_id, "author": author, "text": request.text}
        )
        return feedback_id

````

Edit 102 (`tests/plan_g/fakes.py`), replace:
````python
        self.clock = time.time  # tests replace it to age sessions and records
````
with:
````python
        self.clock = time.time  # tests replace it to age sessions and records
        self.decisions: dict[UUID, dict[str, Any]] = {}  # T21: the recorded decision, for ALREADY_DECIDED's answer
        self.expiries: list[UUID] = []  # T21: every lazy-expiry unit, in order
        self.feedback: list[dict[str, Any]] = []  # T21: the feedback rows
        self.searches: list[SearchRequest] = []  # T21: every search the route made
````

Edit 103 (`tests/plan_g/fakes.py`), replace:
````python
    async def events(self, tenant_id: UUID, run_id: UUID, *, after: int, limit: int) -> list[dict[str, Any]]:
````
with:
````python
    async def proposal_card(self, tenant_id: UUID, proposal_id: UUID) -> dict[str, Any] | None:
        row = await self.proposal(tenant_id, proposal_id)
        if row is None:
            return None
        decided = self.decisions.get(proposal_id, {})
        return {
            "supersedes_run_id": None,
            "superseded_incident_id": None,
            "expired": False,
            "grant_exists": False,
            "attempt_state": None,
            **row,
            "decision": decided.get("decision"),
            "reviewer": decided.get("reviewer"),
            "decided_at": decided.get("decided_at"),
        }

    async def search(self, tenant_id: UUID, request: SearchRequest) -> dict[str, Any]:
        self.searches.append(request)
        return {"corpus_version": "test", "retrieved_at": "2026-10-25T12:00:00Z", "truncated": False, "results": []}

    async def events(self, tenant_id: UUID, run_id: UUID, *, after: int, limit: int) -> list[dict[str, Any]]:
````

Edit 104 (`tests/plan_g/test_api_admission.py`), replace:
````python
    refused(second, 409, "VERSION_CONFLICT")
````
with:
````python
    body = refused(second, 409, "ALREADY_DECIDED")  # T21 (Plan R ruling 3): its own code, naming what stands
    assert body["message"].startswith("the proposal is already decided: approve at ")
````

Run the same pytest line again → `9 passed`.

- [ ] **Step 3: Gates and commit**

`uv run ruff format` and `uv run ruff check --fix` over the touched files; `git add` the new files; dev `PYTHONUTF8=1 uv
run python scripts/check.py < /dev/null` → `CHECK: GREEN`, `1784 passed, 227 skipped`; `verify_handoff.py` exit 0.

```bash
git add -A -- . ':!reports'
git commit -m "feat: the review routes - revisions, cancel, manual proposals, feedback, search and the card (T21)"
```

---
### Task 5: The worker and the sweeper

**Files:**
- Create: `tests/plan_r/test_worker_review.py`, `sweeper/src/ops_sweeper/expiry.py`
- Modify: `core/src/ops_core/persistence.py`, `sweeper/src/ops_sweeper/main.py`, `sweeper/src/ops_sweeper/tenants.py`,
  `sweeper/src/ops_sweeper/wakeups.py`, `tests/plan_f/test_grant_deferred.py`, `tests/plan_h/test_reclaim.py`,
  `tests/plan_h/test_worker_units.py`, `tests/plan_j/test_worker_azp.py`, `tests/plan_p/test_investigate_drafting.py`,
  `tests/plan_q/test_graph_flow.py`, `worker/src/ops_worker/graph/build.py`, `worker/src/ops_worker/graph/nodes.py`,
  `worker/src/ops_worker/graph/state.py`, `worker/src/ops_worker/handlers.py`, `worker/src/ops_worker/main.py`,
  `worker/src/ops_worker/proposals.py`

**Requirements:** rulings 1, 5, 7, 9, 10, 13, 16, 18; SA:189, SA:207-215, SA:457; R023 (unit), R057, R092, R116; errata
134, 137, 140, 142, 143, 145.

- [ ] **Step 1: The tests first**

Create `tests/plan_r/test_worker_review.py`:
````python
"""The worker and the sweeper around T21's review (Plan R rulings 1, 5, 7, 9, 13 and 18; R023, R057, R092, R116), on
LangGraph's in-memory saver and Plan H's fakes.

Catches: a revision drafted on the old revision's thread or frozen as revision 1; an investigate job for an older
revision that runs the graph again; a freeze whose expiry is the worker's wall clock, or whose unit takes the asset
guard's lock after the fence; a model outage that fails the run instead of leaving it for a person's proposal, a
manual-path run whose stored checkpoint stays (the manual proposal would refuse), or a later job that fails or
re-drafts such a run; an execute job that does not read the asset status again before its grant; a lost lease after
the decision that resumes with another decision than the accepted one, or grants twice (R023); and a sweeper tick that
does not expire overdue proposals or record its minute.
"""

import asyncio
import json
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from langgraph.types import Command
from ops_core import persistence
from ops_core.jobs import JobType
from ops_core.lease import Lease, LeaseLost
from ops_core.outcomes import EventType
from ops_core.states import RunState
from ops_sweeper import expiry
from ops_sweeper import main as sweeper
from ops_worker import main
from ops_worker.drafting import ModelUnavailable
from ops_worker.graph import build, nodes

from tests.plan_h.test_worker_units import JOB, NOW, RUN, RUN_ID, make
from tests.plan_q.test_graph_flow import Answering, Scripted, approve, job, world

SUCCEEDED = {"status": "outcome", "data": {"status": "SUCCEEDED"}, "error": None}


def frozen_payloads(monkeypatch: pytest.MonkeyPatch, w: Any) -> list[dict[str, Any]]:
    """Every payload `freeze_proposal` was given, with the expiry it was handed (Plan H's recorder freezes on)."""
    seen: list[dict[str, Any]] = []
    freeze = persistence.freeze_proposal

    async def keep(*args: Any, **kwargs: Any) -> Any:
        seen.append({**json.loads(kwargs["payload_canonical"]), "passed_expiry": kwargs["expires_at"]})
        return await freeze(*args, **kwargs)

    monkeypatch.setattr(persistence, "freeze_proposal", keep)
    return seen


def test_a_revision_is_its_own_thread_and_freezes_its_own_number(monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(monkeypatch, {**RUN, "revision": 2})
    payloads = frozen_payloads(monkeypatch, w)
    job(w, Scripted(), dedup_key=f"{RUN_ID}:2")
    (payload,) = payloads
    assert payload["revision"] == 2 and w.run["state"] == "AWAITING_APPROVAL"
    assert list(w.saver.list(build.config(build.thread_id(RUN_ID, 2), None)))  # ruling 1: the thread run_id:2
    assert not list(w.saver.list(build.config(build.thread_id(RUN_ID, 1), None)))
    # Ruling 5: the expiry counts from the application clock read in the freeze unit, inside the hashed payload.
    assert payload["expires_at"] == "2026-10-15T12:15:00Z" and payload["passed_expiry"] == NOW + timedelta(minutes=15)


def test_an_investigate_job_of_an_older_revision_ends_without_a_graph_run(monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(monkeypatch, {**RUN, "revision": 2})
    job(w, Scripted(), dedup_key=f"{RUN_ID}:1")
    assert "store_checkpoint_id" not in w.log.entries and w.run["state"] == "QUEUED"
    assert w.log.entries[-1] == "release_lease"


def test_the_freeze_unit_takes_the_asset_lock_before_its_fence(monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(monkeypatch)
    job(w, Scripted())
    (freeze,) = [u for u in w.log.units() if "freeze_proposal" in u]
    assert freeze[:3] == ["set_tenant", "lock_asset", "fenced"]  # SA:189: advisory:asset, run_lease, runs


def test_a_model_outage_leaves_the_run_for_a_manual_proposal(monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(monkeypatch)
    job(w, Scripted(ModelUnavailable("no reply")))
    assert w.run["state"] == "DRAFTING" and w.run["checkpoint_id"] is None  # erratum 134: what the manual path needs
    assert "freeze_proposal" not in w.log.entries and "clear_checkpoint_id" in w.log.entries
    assert w.contexts[0].trace[-3:] == ["draft_with_langchain", "route_request", "publish_state"]
    # A job that wakes the run again (a re-armed or reclaimed one) leaves it waiting: no failure, no second draft.
    moves = w.log.entries.count("transition_run")
    explanation = [(uuid4(), {"message": nodes.MANUAL_PATH})]
    w.run["events"][EventType.EXPLANATION_READY] = (
        explanation  # what manual_path journalled (Plan H's recorder drops it)
    )
    generator = Scripted()
    job(w, generator)
    assert w.log.entries.count("transition_run") == moves and generator.requests == []
    assert w.run["state"] == "DRAFTING"


def test_an_execute_job_reads_the_asset_status_again_before_its_grant(monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(monkeypatch)
    job(w, Scripted())
    approve(w)
    start = len(w.log.entries)
    job(w, Scripted(), "execute", mcp=Answering(w.log, SUCCEEDED))
    after = w.log.entries[start:]
    assert (
        after.index("mcp:get_asset_status")
        < after.index("record_asset_observation")
        < after.index("mcp:create_incident")
    )
    assert w.run["asset_observed_at"].isoformat() == "2026-10-08T12:00:00+00:00"  # the read's own observed_at


def test_r023_a_lost_lease_after_the_decision_resumes_exactly_the_accepted_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ruling 13 on the fakes: the execute job loses its lease at the store of the resumed wait's checkpoint, so the
    stored id is still the interrupt; the next execute job resumes it with the same approval.recorded id, and the write
    tool runs once, for the approved proposal. (Live, the stop comes after that store: tests/e2e.)"""
    w = world(monkeypatch)
    job(w, Scripted())
    approve(w)
    accepted = w.run["events"][EventType.APPROVAL_RECORDED][-1][0]
    inputs: list[Any] = []
    drive = build.run_graph

    async def spy(ctx: Any, graph_input: Any, **kwargs: Any) -> None:
        inputs.append(graph_input)
        await drive(ctx, graph_input, **kwargs)

    monkeypatch.setattr(build, "run_graph", spy)
    fences = [0]

    async def fenced(_conn: Any, held: Lease) -> None:
        w.log.entries.append("fenced")
        fences[0] += 1
        if fences[0] == 2:  # the job's first unit passes; the store of the resumed wait's checkpoint loses
            held.mark_lost("the fence moved")
            raise LeaseLost("run lease lost")

    monkeypatch.setattr(persistence, "fenced", fenced)
    deps, lease = make(w.log)
    deps.saver = w.saver
    asyncio.run(main.run_job(deps, persistence.Claimed({**JOB, "type": "execute"}, lease)))  # handed back
    assert "mcp:create_incident" not in w.log.entries  # stopped before the write tool
    calls = Answering(w.log, SUCCEEDED)
    job(w, Scripted(), "execute", mcp=calls)
    resumes = [i.resume for i in inputs if isinstance(i, Command)]
    assert resumes == [str(accepted), str(accepted)]  # exactly the accepted event, both times
    assert w.log.entries.count("mcp:create_incident") == 1


def test_the_sweeper_expires_every_tenants_overdue_proposals_and_records_its_minute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant, overdue, decided = uuid4(), uuid4(), uuid4()
    asked: list[Any] = []

    async def each_tenant(_conn: Any, _work: Any, *, tenants: Any = None) -> dict[Any, list[Any]]:
        return {tenant: [overdue, decided]}

    async def in_tenant(conn: Any, _tenant: Any, work: Any) -> Any:
        return await work(conn)

    async def expire_proposal(_conn: Any, run_id: Any) -> RunState:
        asked.append(run_id)  # a decision got to `decided` first: the definer leaves it as it is
        return RunState.BLOCKED_REVIEW if run_id == overdue else RunState.APPROVED

    recorded: list[JobType] = []

    async def record(_deps: Any, job_type: JobType) -> None:
        recorded.append(job_type)

    monkeypatch.setattr(expiry, "for_each_tenant", each_tenant)
    monkeypatch.setattr(expiry, "in_tenant", in_tenant)
    monkeypatch.setattr(persistence, "expire_proposal", expire_proposal)
    monkeypatch.setattr(sweeper, "record", record)
    none: Any = None
    deps = sweeper.Deps(conn=none, admin=none, issuer="iss", tick_seconds=30.0, worker_name="sweeper:test")
    asyncio.run(sweeper.expire_proposals(deps))
    assert asked == [overdue, decided] and recorded == [JobType.EXPIRE_PROPOSALS]
    assert asyncio.run(expiry.expire(none)) == [overdue]
````

Run `PYTHONUTF8=1 uv run python -m pytest tests/plan_r/test_worker_review.py -q -p no:cacheprovider < /dev/null` → RED,
`1 error during collection`: `ImportError: cannot import name 'expiry' from 'ops_sweeper'`.

- [ ] **Step 2: The worker's revision, observation, manual path and grant re-read; the sweeper's expiry**

Edit 105 (`core/src/ops_core/persistence.py`), replace:
````python
async def insert_run_manifest(conn: Conn, *, tenant_id: UUID, manifest: RunManifest) -> None:
    """The run's manifest (AM-80; revision 0014), as the worker under its own grant (INSERT, SELECT). The caller's
    unit sets the tenant and holds the fence; a second manifest for the run fails on the primary key, so one run is
    recorded once."""
    await conn.execute(
        "INSERT INTO app.run_manifests (run_id, tenant_id, model_route, model_digest, prompt_version, corpus_version,"
        " retrieval_mode) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            manifest.run_id,
````
with:
````python
async def insert_run_manifest(conn: Conn, *, tenant_id: UUID, manifest: RunManifest, revision: int) -> None:
    """The run's manifest for one revision (AM-80; revision 0014, keyed per revision since 0016), as the worker under
    its own grant (INSERT, SELECT). The caller's unit sets the tenant and holds the fence; a second manifest for the
    same revision fails on the primary key, so each revision is recorded once (erratum 125 closes, Plan R ruling 1)."""
    await conn.execute(
        "INSERT INTO app.run_manifests (run_id, revision, tenant_id, model_route, model_digest, prompt_version,"
        " corpus_version, retrieval_mode) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (
            manifest.run_id,
            revision,
````

Edit 106 (`core/src/ops_core/persistence.py`), replace:
````python
async def run_manifest_exists(conn: Conn, run_id: UUID) -> bool:
    """True when the run has its manifest (T20: a run that retrieves again after a clarification keeps the one it
    has, Plan Q ruling 13 and erratum 125; whether a revision records its own is T21's)."""
    cur = await conn.execute("SELECT 1 FROM app.run_manifests WHERE run_id = %s", (run_id,))
````
with:
````python
async def run_manifest_exists(conn: Conn, run_id: UUID, revision: int) -> bool:
    """True when the run's revision has its manifest: a revision that retrieves again after a clarification keeps the
    one it has (erratum 125), and a new revision records its own (T21, Plan R ruling 1)."""
    cur = await conn.execute("SELECT 1 FROM app.run_manifests WHERE run_id = %s AND revision = %s", (run_id, revision))
````

Create `sweeper/src/ops_sweeper/expiry.py`:
````python
"""The scheduled proposal expiry (SA:138, SA:346, SA:457; T21, Plan R ruling 5; R092).

Every tick the sweeper finds, per tenant (SA:520: `runs` has no sweeper policy), the runs whose active proposal is
past its expiry while they wait for a reviewer or for their grant, and calls `expire_proposal` for each in a unit of
its own: the definer locks the run, compares `expires_at` with the application clock after the lock and moves the run
to BLOCKED_REVIEW(`expired`) with `review.blocked`, or does nothing when a decision or a revision got there first. So a
proposal expires without a live worker and without a reviewer's request (R092); the decision and the grant check the
same rule lazily. An APPROVED run expires before its grant (SA:140); a granted run is EXECUTING and never expires.
"""

from __future__ import annotations

import functools
from collections.abc import Sequence
from uuid import UUID

from ops_core import persistence
from ops_core.states import RunState

from ops_sweeper.tenants import for_each_tenant, in_tenant

# The scan reads without a lock; the definer decides under its own (the scan is only a list of candidates).
DUE = (
    "SELECT r.run_id FROM app.runs r JOIN app.proposals p ON p.proposal_id = r.active_proposal_id"
    " WHERE r.state IN ('AWAITING_APPROVAL', 'APPROVED') AND p.expires_at < app.current_time() ORDER BY r.run_id"
)


async def _due(conn: persistence.Conn) -> list[UUID]:
    cur = await conn.execute(DUE)
    return [UUID(str(row["run_id"])) for row in await cur.fetchall()]


async def _expire(conn: persistence.Conn, *, run_id: UUID) -> RunState:
    return await persistence.expire_proposal(conn, run_id)


async def expire(conn: persistence.Conn, *, tenants: Sequence[UUID] | None = None) -> list[UUID]:
    """Expire every tenant's overdue proposals, one run per unit; the runs that moved to BLOCKED_REVIEW."""
    found = await for_each_tenant(conn, _due, tenants=tenants)
    expired: list[UUID] = []
    for tenant, runs in found.items():
        for run_id in runs:
            state = await in_tenant(conn, tenant, functools.partial(_expire, run_id=run_id))
            if state is RunState.BLOCKED_REVIEW:
                expired.append(run_id)
    return expired
````

Edit 107 (`sweeper/src/ops_sweeper/main.py`), replace:
````python
`scripts/skeleton.py up` waits for the first sync.
TODO(T21): proposal expiry.
````
with:
````python
`scripts/skeleton.py up` waits for the first sync. Since T21 each tick also expires overdue proposals
(`expiry.expire`, R092) and records this minute's `expire_proposals` row, after the lease reclaim and before the
wake-up sweep.
````

Edit 108 (`sweeper/src/ops_sweeper/main.py`), replace:
````python
from ops_sweeper import leases, outbox, sync, wakeups
````
with:
````python
from ops_sweeper import expiry, leases, outbox, sync, wakeups
````

Edit 109 (`sweeper/src/ops_sweeper/main.py`), replace:
````python
    await sweep_wakeups(deps)  # first: notification delivery must never starve run progress (round 1, I1)
    await deliver_outbox(deps)


````
with:
````python
    await expire_proposals(deps)
    await sweep_wakeups(deps)  # first: notification delivery must never starve run progress (round 1, I1)
    await deliver_outbox(deps)


async def expire_proposals(deps: Deps) -> None:
    """Expire every tenant's overdue proposals (T21, Plan R ruling 5; SA:346), then record this minute's
    `expire_proposals` row (SA:504's `name:<minute bucket>`), as the sync records its own."""
    expired = await expiry.expire(deps.conn)
    if expired:
        log.info("expired %d proposal(s): %s", len(expired), ", ".join(str(run) for run in expired))
    await record(deps, JobType.EXPIRE_PROPOSALS)


````

Edit 110 (`sweeper/src/ops_sweeper/main.py`), replace:
````python
        chosen_outbox = settings.outbox()  # refused before the loop starts, like every other setting
````
with:
````python
        await persistence.assert_function_text(probe, *persistence.PROPOSAL_EXPIRY)  # revision 0016: the expiry
        chosen_outbox = settings.outbox()  # refused before the loop starts, like every other setting
````

Edit 111 (`sweeper/src/ops_sweeper/tenants.py`), replace:
````python
transaction per tenant with that tenant set. The outbox delivery and the wake-up sweep use it now; T21's proposal
expiry and T22's deadline escalation will.
````
with:
````python
transaction per tenant with that tenant set. The outbox delivery, the wake-up sweep and the proposal expiry (T21)
use it now; T22's deadline escalation will.
````

Edit 112 (`sweeper/src/ops_sweeper/wakeups.py`), replace:
````python
That predicate also matches a run the execute handler left APPROVED on purpose: a grant refusal it takes as final
(an inactive membership, a missing approval) finishes the job without moving the run, so the sweep re-dispatches it,
at most until the job has been claimed `max_attempts` times. No grant can follow a refusal that stays a refusal; a
refusal that clears within those minutes (a reviewer reactivated by the membership sync) is executed. Moving such a
run out of APPROVED (BLOCKED_REVIEW, AM-10) is T21's (debt list; round 1, I3).
````
with:
````python
Since T21 a refused grant of a run's review (expiry, revoked authority, stale evidence, the asset guard) moves the run
to BLOCKED_REVIEW in the gate's own transaction (AM-10 SA:140; Plan R rulings 9 and 11), so the APPROVED pair re-arms
a lost decision wake-up (R023) and nothing it must not: a deferred grant re-queues its own job, and only the binding
refusals that leave a run APPROVED (a missing approval, a hash mismatch) are re-dispatched, at most until the job has
been claimed `max_attempts` times (erratum 63, resolved this way provisionally).
````

Edit 113 (`tests/plan_f/test_grant_deferred.py`), replace:
````python
from ops_worker.handlers import EXECUTE_RETRY_SECONDS, is_deferred
````
with:
````python
from ops_worker.graph import nodes
from ops_worker.handlers import EXECUTE_RETRY_SECONDS, is_deferred
````

Edit 114 (`tests/plan_f/test_grant_deferred.py`), replace:
````python
        return {"run_id": rid, "state": RunState.APPROVED.value, "active_proposal_id": uuid4()}
````
with:
````python
        return {"run_id": rid, "state": RunState.APPROVED.value, "active_proposal_id": uuid4(), "asset_id": "A17"}

    async def run_revision(_conn: Any, _rid: UUID) -> int:
        return 1

    async def record_workflow_version(_conn: Any, _rid: UUID, version: str) -> str:
        return version

    async def observe_nothing(*_: Any) -> None:
        return None  # T21: the status read again before the grant is not this test's subject
````

Edit 115 (`tests/plan_f/test_grant_deferred.py`), replace:
````python
    }.items():
        monkeypatch.setattr(persistence, name, fn)
````
with:
````python
        "run_revision": run_revision,
        "record_workflow_version": record_workflow_version,
    }.items():
        monkeypatch.setattr(persistence, name, fn)
    monkeypatch.setattr(nodes, "observe_asset", observe_nothing)
````

Edit 116 (`tests/plan_h/test_reclaim.py`), replace:
````python
    monkeypatch.setattr(main, "run_sync", failed_sync)
````
with:
````python
    async def expire_proposals(_deps: Any) -> None:
        calls.append("expiry")

    monkeypatch.setattr(main, "run_sync", failed_sync)
    monkeypatch.setattr(main, "expire_proposals", expire_proposals)  # T21: between the reclaim and the wake-ups
````

Edit 117 (`tests/plan_h/test_reclaim.py`), replace:
````python
    assert calls == ["sync", "purge", "reclaim", "wakeups", "outbox"]
````
with:
````python
    assert calls == ["sync", "purge", "reclaim", "expiry", "wakeups", "outbox"]
````

Edit 118 (`tests/plan_h/test_worker_units.py`), replace:
````python
JOB = {"id": uuid4(), "run_id": RUN_ID, "tenant_id": TENANT, "type": "investigate"}
````
with:
````python
JOB = {"id": uuid4(), "run_id": RUN_ID, "tenant_id": TENANT, "type": "investigate", "dedup_key": f"{RUN_ID}:1"}
````

Edit 119 (`tests/plan_h/test_worker_units.py`), replace:
````python
    "store_checkpoint_id",
````
with:
````python
    "store_checkpoint_id",
    "record_asset_observation",  # T21: the worker's column UPDATEs on its run row
    "clear_checkpoint_id",
````

Edit 120 (`tests/plan_h/test_worker_units.py`), replace:
````python
    async def insert_run_manifest(_conn: Any, **_: Any) -> None:
        log.entries.append("insert")  # as the real one's INSERT is logged by FakeConn
        current["manifest"] = True

    async def run_manifest_exists(_conn: Any, _run_id: Any) -> bool:
        log.entries.append("run_manifest_exists")
        return bool(current.get("manifest"))

    async def store_checkpoint_id(_conn: Any, _run_id: Any, checkpoint_id: str) -> None:
        log.entries.append("store_checkpoint_id")
        current["checkpoint_id"] = checkpoint_id

````
with:
````python
    async def run_manifest_exists(_conn: Any, _run_id: Any, revision: int) -> bool:
        log.entries.append("run_manifest_exists")
        return current.get("manifest") == revision  # T21: one manifest per revision

    async def insert_revision_manifest(_conn: Any, *, revision: int, **_: Any) -> None:
        log.entries.append("insert")
        current["manifest"] = revision

    async def store_checkpoint_id(_conn: Any, _run_id: Any, checkpoint_id: str) -> None:
        log.entries.append("store_checkpoint_id")
        current["checkpoint_id"] = checkpoint_id

    async def clear_checkpoint_id(_conn: Any, _run_id: Any) -> None:
        log.entries.append("clear_checkpoint_id")
        current["checkpoint_id"] = None

    async def run_revision(_conn: Any, _run_id: Any) -> int:
        log.entries.append("run_revision")
        return int(current.get("revision", 1))  # T21: what create_revision journals, kept on the fake row

    async def record_workflow_version(_conn: Any, _run_id: Any, version: str) -> str:
        current.setdefault("workflow_version", version)
        return str(current["workflow_version"])

    async def record_asset_observation(_conn: Any, _run_id: Any, observed_at: Any) -> None:
        log.entries.append("record_asset_observation")
        current["asset_observed_at"] = observed_at

    async def current_time(_conn: Any) -> datetime:
        return NOW

````

Edit 121 (`tests/plan_h/test_worker_units.py`), replace:
````python
        "insert_run_manifest": insert_run_manifest,
````
with:
````python
        "clear_checkpoint_id": clear_checkpoint_id,
        "run_revision": run_revision,
        "record_workflow_version": record_workflow_version,
        "record_asset_observation": record_asset_observation,
        "current_time": current_time,
        "lock_asset": recorder("lock_asset"),
        "insert_run_manifest": insert_revision_manifest,
````

Edit 122 (`tests/plan_h/test_worker_units.py`), replace:
````python
            assert next(entry for entry in unit if entry != "set_tenant") == "fenced", unit  # set_config is no lock
````
with:
````python
            # set_config is no lock; T21: the freeze unit's asset guard lock precedes the fence (SA:189).
            assert next(entry for entry in unit if entry not in ("set_tenant", "lock_asset")) == "fenced", unit
    assert ["set_tenant", "lock_asset", "fenced", "run_row"] == next(u for u in units if "freeze_proposal" in u)[:4]
````

Edit 123 (`tests/plan_h/test_worker_units.py`), replace:
````python
    assert log.units()[0] == ["set_tenant", "fenced", "run_row", "transition_run"]
````
with:
````python
    first = log.units()[0]  # T21: the unit also reads the revision (and, for DRAFTING, the manual-path explanation)
    assert first[:3] == ["set_tenant", "fenced", "run_row"] and first[-1] == "transition_run"
````

Edit 124 (`tests/plan_j/test_worker_azp.py`), replace:
````python
    assert [m["azp"] for m in minted] == ["ops-worker-renamed"]
````
with:
````python
    # T21 (erratum 137): an execute job mints a read handle for the asset status too, before its write handle.
    servers = ["read", "write"] if job_type == "execute" else ["read"]
    assert [(m["azp"], m["server"].value) for m in minted] == [("ops-worker-renamed", s) for s in servers]
````

Edit 125 (`tests/plan_p/test_investigate_drafting.py`), replace:
````python
fake draft or freezes anything; an outage or an exhausted repair that is not a templated FAILED; an abstention that
````
with:
````python
fake draft or freezes anything; an outage or an exhausted repair that does not leave the run waiting in DRAFTING for
a manual proposal (T21, erratum 134: before T21 a templated FAILED); an abstention that
````

Edit 126 (`tests/plan_p/test_investigate_drafting.py`), replace:
````python
    async def insert_run_manifest(_conn: Any, *, tenant_id: Any, manifest: Any) -> None:
        inserted.append(manifest)
        log.entries.append("insert_run_manifest")
````
with:
````python
    async def insert_run_manifest(_conn: Any, *, tenant_id: Any, manifest: Any, revision: int) -> None:
        inserted.append(manifest)
        log.entries.append("insert_run_manifest")
````

Edit 127 (`tests/plan_p/test_investigate_drafting.py`), replace:
````python
    assert drafting == ["set_tenant", "fenced", "transition_run", "run_manifest_exists", "insert_run_manifest"]
````
with:
````python
    assert drafting == [
        "set_tenant",
        "fenced",
        "transition_run",
        "run_manifest_exists",
        "insert_run_manifest",
        "record_asset_observation",  # T21: the status observation the grant checks (R116)
    ]
````

Edit 128 (`tests/plan_p/test_investigate_drafting.py`), replace:
````python
    ("answers", "message"),
    [
        ((ModelUnavailable("Ollama answered no draft (ConnectionError)"),), handlers.MODEL_UNAVAILABLE),
        ((Reply("not json"), Reply("still not json")), handlers.MODEL_INVALID),
    ],
)
def test_a_failing_real_route_fails_the_run_and_never_falls_back(
    monkeypatch: pytest.MonkeyPatch, answers: tuple[Reply | Exception, ...], message: str
) -> None:
    generator, _ = real(*answers)
    log, seen = investigate(monkeypatch, generator)
    assert ends(seen) == ("FAILED", message)
    assert "freeze_proposal" not in log.entries  # R041: no fake draft, no proposal, nothing frozen
    assert [e["type"].value for e in seen["append_event"]] == ["tool.started", "tool.completed"] * 3
    assert log.entries[-1] == "release_lease" and log.entries.count("release_model_permit") == 1
````
with:
````python
    "answers",
    [(ModelUnavailable("Ollama answered no draft (ConnectionError)"),), (Reply("not json"), Reply("still not json"))],
    ids=["unavailable", "invalid-after-repair"],
)
def test_a_failing_real_route_leaves_the_run_for_a_manual_proposal(
    monkeypatch: pytest.MonkeyPatch, answers: tuple[Reply | Exception, ...]
) -> None:
    """T21 (erratum 134, Plan R ruling 7): the run stays DRAFTING with its stored checkpoint cleared and a templated
    explanation; a person's proposal moves it on (DEV-025's FAILED_WITH_MANUAL_PATH)."""
    generator, _ = real(*answers)
    log, seen = investigate(monkeypatch, generator)
    assert ends(seen) == ("DRAFTING", None)
    assert "freeze_proposal" not in log.entries  # R041: no fake draft, no proposal, nothing frozen
    events = [(e["type"].value, e["payload"].get("message")) for e in seen["append_event"]]
    assert events[-1] == ("explanation.ready", nodes.MANUAL_PATH) and len(events) == 7  # after the three reads
    assert log.entries[-3:] == ["clear_checkpoint_id", "COMMIT", "release_lease"]
    assert log.entries.count("release_model_permit") == 1
````

Edit 129 (`tests/plan_p/test_investigate_drafting.py`), replace:
````python
    async def insert_run_manifest(_conn: Any, *, tenant_id: Any, manifest: Any) -> None:
````
with:
````python
    async def insert_run_manifest(_conn: Any, *, tenant_id: Any, manifest: Any, revision: int) -> None:
````

Edit 130 (`tests/plan_p/test_investigate_drafting.py`), replace:
````python
    assert ends(seen) == ("FAILED", handlers.MODEL_UNAVAILABLE)
````
with:
````python
    assert ends(seen) == ("DRAFTING", None)  # T21: the run waits for a manual proposal (erratum 134)
````

Edit 131 (`tests/plan_q/test_graph_flow.py`), replace:
````python
        return self.docs.pop(0)
````
with:
````python
        if tool == "get_asset_status":  # T21: the status read again before the grant (erratum 137)
            return STATUS
        return self.docs.pop(0)
````

Edit 132 (`worker/src/ops_worker/graph/build.py`), replace:
````python
    """One LangGraph thread per run and revision (Plan Q ruling 13): a revision starts a thread of its own (T21)."""
````
with:
````python
    """One LangGraph thread per run and revision (Plan Q ruling 13): a revision starts a thread of its own (T21,
    Plan R ruling 1)."""
````

Edit 133 (`worker/src/ops_worker/graph/build.py`), replace:
````python
async def run_graph(ctx: Context, graph_input: GraphInput, *, checkpoint_id: str | None, revision: int = 1) -> None:
````
with:
````python
async def run_graph(ctx: Context, graph_input: GraphInput, *, checkpoint_id: str | None, revision: int) -> None:
````

Edit 134 (`worker/src/ops_worker/graph/nodes.py`), replace:
````python
from datetime import UTC, datetime
````
with:
````python
from datetime import datetime
````

Edit 135 (`worker/src/ops_worker/graph/nodes.py`), replace:
````python
WORKFLOW_FAILED: Final = "the workflow failed"
````
with:
````python
WORKFLOW_FAILED: Final = "the workflow failed"
# T21 (erratum 134): the model could not draft, so the run waits in DRAFTING for a person's proposal (ruling 7).
MANUAL_PATH: Final = "The model is unavailable; a requester or reviewer may submit a manual proposal."
OBSERVED: Final = frozenset({"normal", "warning"})  # an `unavailable` status observes nothing (evidence.OBSERVED)
````

Edit 136 (`worker/src/ops_worker/graph/nodes.py`), replace:
````python
async def unit(ctx: Context, *, fence: bool = True) -> AsyncIterator[persistence.Conn]:
    """One transaction on the loop connection under the job's tenant; a writing unit opens with the fence (SA:176)."""
    conn = ctx.deps.conn
    async with conn.transaction():
        await persistence.set_tenant(conn, ctx.job["tenant_id"])  # the worker's reads and inserts are RLS-scoped
````
with:
````python
async def unit(ctx: Context, *, fence: bool = True, asset: str | None = None) -> AsyncIterator[persistence.Conn]:
    """One transaction on the loop connection under the job's tenant; a writing unit opens with the fence (SA:176).
    With `asset`, the asset guard's advisory lock comes first, before the fence (SA:189, T21)."""
    conn = ctx.deps.conn
    async with conn.transaction():
        await persistence.set_tenant(conn, ctx.job["tenant_id"])  # the worker's reads and inserts are RLS-scoped
        if asset is not None:
            await persistence.lock_asset(conn, ctx.job["tenant_id"], asset)
````

Edit 137 (`worker/src/ops_worker/graph/nodes.py`), replace:
````python
    if state["draft_kind"] != DraftKind.NONE.value and _held(ctx, state) is None:
````
with:
````python
    # MANUAL holds nothing: it is the worker's verdict that no draft came (T21), and it ends the graph run.
    unheld = state["draft_kind"] not in (DraftKind.NONE.value, DraftKind.MANUAL.value)
    if unheld and _held(ctx, state) is None:
````

Edit 138 (`worker/src/ops_worker/graph/nodes.py`), replace:
````python
    if current is RunState.RETRIEVING:
        async with unit(ctx) as conn:
            await persistence.transition_run(conn, run_id=run["run_id"], src=current, dst=RunState.DRAFTING)
            # Written before the model is called, so a run whose draft fails still records the route, digest, prompt
            # and corpus it used (R130); one immutable row per run, so a run retrieving again after a clarification
            # keeps the one it has (erratum 125). A run resumed in DRAFTING never gets here.
            if not await persistence.run_manifest_exists(conn, run["run_id"]):
                await persistence.insert_run_manifest(conn, tenant_id=run["tenant_id"], manifest=manifest)
````
with:
````python
    async with unit(ctx) as conn:
        if current is RunState.RETRIEVING:
            await persistence.transition_run(conn, run_id=run["run_id"], src=current, dst=RunState.DRAFTING)
            # Written before the model is called, so a run whose draft fails still records the route, digest, prompt
            # and corpus it used (R130); one immutable row per revision, so a revision retrieving again after a
            # clarification keeps the one it has (erratum 125) and a new revision records its own (T21).
            if not await persistence.run_manifest_exists(conn, run["run_id"], ctx.revision):
                await persistence.insert_run_manifest(
                    conn, tenant_id=run["tenant_id"], manifest=manifest, revision=ctx.revision
                )
        # R116 (T21 ruling 9): the status observation the grant checks; sufficient means it is `normal` or `warning`.
        await persistence.record_asset_observation(
            conn, run["run_id"], datetime.fromisoformat(status["data"]["observed_at"])
        )
````

Edit 139 (`worker/src/ops_worker/graph/nodes.py`), replace:
````python
        log.warning("job %s: %s", ctx.job["id"], exc)
        return await fail(ctx, RunState.DRAFTING, RunState.FAILED, MODEL_UNAVAILABLE)
    except ModelOutputInvalid as exc:
        # Rule names only: the invalid text is never logged or stored (SA:496).
        log.warning("job %s: draft invalid after one repair (%s)", ctx.job["id"], exc)
        return await fail(ctx, RunState.DRAFTING, RunState.FAILED, MODEL_INVALID)
````
with:
````python
        log.warning("job %s: %s; the run waits for a manual proposal", ctx.job["id"], exc)
        return await manual_path(ctx, _run_id(state))
    except ModelOutputInvalid as exc:
        # Rule names only: the invalid text is never logged or stored (SA:496).
        log.warning(
            "job %s: draft invalid after one repair (%s); the run waits for a manual proposal", ctx.job["id"], exc
        )
        return await manual_path(ctx, _run_id(state))
````

Edit 140 (`worker/src/ops_worker/graph/nodes.py`), replace:
````python
def _held(ctx: Context, state: RunGraphState) -> HeldDraft | None:
````
with:
````python
async def manual_path(ctx: Context, run_id: UUID) -> dict[str, Any]:
    """T21 (erratum 134, ruling 7): no validated draft came, so the run stays DRAFTING for a person's proposal. The
    templated `explanation.ready` says so (DEV-025's FAILED_WITH_MANUAL_PATH); the graph run then ends (the `manual`
    row), and the handler clears the stored checkpoint, which is what `create_manual_proposal` waits for."""
    async with unit(ctx) as conn:
        run = dict(await persistence.run_row(conn, run_id, lock=True))
        if RunState(run["state"]) is not RunState.DRAFTING:
            return {"run_state": run["state"]}  # cancelled meanwhile
        await persistence.append_event(
            conn, run_id=run_id, type=EventType.EXPLANATION_READY, payload={"message": MANUAL_PATH}
        )
    return {"draft_kind": DraftKind.MANUAL.value}


def _held(ctx: Context, state: RunGraphState) -> HeldDraft | None:
````

Edit 141 (`worker/src/ops_worker/graph/nodes.py`), replace:
````python
        async with unit(ctx) as conn:
            run = dict(await persistence.run_row(conn, _run_id(state), lock=True))
````
with:
````python
        async with unit(ctx, fence=False) as conn:  # the run's asset is fixed (SA:154): a plain read names the lock
            asset = str((await persistence.run_row(conn, _run_id(state)))["asset_id"])
        async with unit(ctx, asset=asset) as conn:
            run = dict(await persistence.run_row(conn, _run_id(state), lock=True))
````

Edit 142 (`worker/src/ops_worker/graph/nodes.py`), replace:
````python
                revision=1,  # TODO(T21): the revision a re-entered run freezes (Plan Q ruling 13)
                asset_id=run["asset_id"],
                start_at=run["start_at"],
                end_at=run["end_at"],
                draft=held.draft,
                evidence=bundle.procedures,
                now=datetime.now(UTC).replace(microsecond=0),
````
with:
````python
                revision=ctx.revision,  # T21 (ruling 1): the revision this graph thread serves
                asset_id=run["asset_id"],
                start_at=run["start_at"],
                end_at=run["end_at"],
                draft=held.draft,
                evidence=bundle.procedures,
                # Ruling 5: the expiry counts from the application clock, read in this unit (the freeze checks it).
                now=(await persistence.current_time(conn)).replace(microsecond=0),
````

Edit 143 (`worker/src/ops_worker/graph/nodes.py`), replace:
````python
def is_deferred(doc: dict[str, Any]) -> bool:
````
with:
````python
async def observe_asset(ctx: Context, handle: str, asset_id: str) -> datetime | None:
    """The asset status read again just before the grant (T21 ruling 9, erratum 137), so a normal approval window
    does not leave the grant a stale observation (R116). Its instant when it observed the asset (`normal` or
    `warning`); None when the read failed or observed nothing, and the grant then judges the observation it has."""
    try:
        doc = await read(ctx, handle, Tool.GET_ASSET_STATUS, {"asset_id": asset_id}, [1 + READ_RETRIES])
        data = doc["data"]
        return datetime.fromisoformat(data["observed_at"]) if data["state"] in OBSERVED else None
    except (McpCallFailed, KeyError, TypeError, ValueError) as exc:
        log.warning("job %s: the asset status was not read again before the grant (%s)", ctx.job["id"], exc)
        return None


def is_deferred(doc: dict[str, Any]) -> bool:
````

Edit 144 (`worker/src/ops_worker/graph/nodes.py`), replace:
````python
        handle = await persistence.mint_handle(
            conn, run_id=run["run_id"], job_id=job["id"], server=Server.WRITE, azp=deps.workload_azp, fence=lease.fence
````
with:
````python
        reader = await persistence.mint_handle(
            conn, run_id=run["run_id"], job_id=job["id"], server=Server.READ, azp=deps.workload_azp, fence=lease.fence
        )
    observed = (
        await observe_asset(ctx, reader, run["asset_id"]) if RunState(run["state"]) is RunState.APPROVED else None
    )
    async with unit(ctx) as conn:
        if observed is not None:  # R116 (ruling 9, erratum 137): the grant checks this observation's age
            await persistence.record_asset_observation(conn, run["run_id"], observed)
        handle = await persistence.mint_handle(
            conn, run_id=run["run_id"], job_id=job["id"], server=Server.WRITE, azp=deps.workload_azp, fence=lease.fence
````

Edit 145 (`worker/src/ops_worker/graph/nodes.py`), replace:
````python
    log.info("execute job %s: %s %s", job["id"], doc.get("status"), data.get("status"))
````
with:
````python
    reason = (doc.get("error") or {}).get("reason")
    if reason is not None:  # T21 (ruling 11): the gate committed BLOCKED_REVIEW; the router reads it and ends
        log.info("execute job %s: the grant was refused (%s); the run is blocked for review", job["id"], reason)
    log.info("execute job %s: %s %s", job["id"], doc.get("status"), data.get("status"))
````

Edit 146 (`worker/src/ops_worker/graph/state.py`), replace:
````python
    the job and the lease it runs under, the hold, and `trace`, the node names in the order they ran (R038's per-run
    node log, which the tests read)."""

    deps: Deps
    job: dict[str, Any]
    lease: Lease
````
with:
````python
    the job and the lease it runs under, the run's revision, the hold, and `trace`, the node names in the order they
    ran (R038's per-run node log, which the tests read)."""

    deps: Deps
    job: dict[str, Any]
    lease: Lease
    revision: int = 1  # T21: the run's revision this graph run serves (its thread, its manifest, its proposal)
````

Edit 147 (`worker/src/ops_worker/handlers.py`), replace:
````python
node can record. A lost lease raises LeaseLost to the caller, which hands the job back (`abandon`).
````
with:
````python
node can record. A lost lease raises LeaseLost to the caller, which hands the job back (`abandon`).

T21 (Plan R ruling 1): each revision of a run is its own graph thread, `run_id:revision`. The run's revision is read in
the job's first unit (`persistence.run_revision`); an investigate job names the revision it wakes in its dedup key,
and a job for an older revision ends without a graph run. `create_revision` clears the stored checkpoint, so a
revision's QUEUED starts a new graph run while a clarification's QUEUED resumes. The first unit also pins the run's
workflow version (ruling 18). A run left in DRAFTING by the manual path (erratum 134) waits for a person; no job
resumes or fails it.
````

Edit 148 (`worker/src/ops_worker/handlers.py`), replace:
````python
from ops_worker.graph import build, nodes
````
with:
````python
from ops_worker.drafting import WORKFLOW_VERSION
from ops_worker.graph import build, nodes
````

Edit 149 (`worker/src/ops_worker/handlers.py`), replace:
````python
    deps: Deps, job: dict[str, Any], lease: Lease, graph_input: build.GraphInput, checkpoint_id: str | None
) -> None:
    """One graph run. A failure no node recorded fails a run still RETRIEVING or DRAFTING, so its slot is freed (as
    Plan P's "drafting failed"); any other failure propagates to `handle`, which releases the lease and re-queues
    the job."""
    ctx = Context(deps, job, lease)
    try:
        await build.run_graph(ctx, graph_input, checkpoint_id=checkpoint_id)
````
with:
````python
    deps: Deps,
    job: dict[str, Any],
    lease: Lease,
    graph_input: build.GraphInput,
    checkpoint_id: str | None,
    revision: int,
) -> None:
    """One graph run on the revision's thread. A failure no node recorded fails a run still RETRIEVING or DRAFTING, so
    its slot is freed (as Plan P's "drafting failed"); any other failure propagates to `handle`, which releases the
    lease and re-queues the job. A graph run that ends with the run still DRAFTING took the manual path: its stored
    checkpoint is cleared, the state a person's proposal waits for (T21, erratum 134)."""
    ctx = Context(deps, job, lease, revision)
    try:
        await build.run_graph(ctx, graph_input, checkpoint_id=checkpoint_id, revision=revision)
````

Edit 150 (`worker/src/ops_worker/handlers.py`), replace:
````python


async def _resumable(deps: Deps, job: dict[str, Any], lease: Lease, state: RunState, stored: str | None) -> bool:
    """True when the stored checkpoint exists; otherwise the run is failed with a template (T20 review note 2)."""
    if stored is not None and await build.known(deps.saver, build.thread_id(lease.run_id, 1), stored):
````
with:
````python
        return
    async with nodes.unit(ctx) as conn:
        run = await persistence.run_row(conn, lease.run_id, lock=True)
        if RunState(run["state"]) is RunState.DRAFTING:
            await persistence.clear_checkpoint_id(conn, lease.run_id)


async def _waits_for_person(conn: persistence.Conn, run: dict[str, Any]) -> bool:
    """A DRAFTING run with no stored checkpoint whose newest explanation is the manual path's (T21, erratum 134)."""
    if RunState(run["state"]) is not RunState.DRAFTING or run.get("checkpoint_id") is not None:
        return False
    explained = await persistence.run_events(conn, run["run_id"], EventType.EXPLANATION_READY)
    return bool(explained) and explained[-1][1].get("message") == nodes.MANUAL_PATH


async def _resumable(
    deps: Deps, job: dict[str, Any], lease: Lease, state: RunState, stored: str | None, revision: int
) -> bool:
    """True when the stored checkpoint exists; otherwise the run is failed with a template (T20 review note 2)."""
    if stored is not None and await build.known(deps.saver, build.thread_id(lease.run_id, revision), stored):
````

Edit 151 (`worker/src/ops_worker/handlers.py`), replace:
````python
    """The job's first fenced unit: the run row under its lock, and an unresumable interrupted run failed in it."""
    async with deps.conn.transaction():
        await persistence.set_tenant(deps.conn, job["tenant_id"])  # the worker's own reads are RLS-scoped
        await persistence.fenced(deps.conn, lease)  # run_lease before runs (SA:188, ruling 29)
        run = dict(await persistence.run_row(deps.conn, job["run_id"], lock=True))
        state = RunState(run["state"])
        if state in _MID_RUN and run.get("checkpoint_id") is None:
````
with:
````python
    """The job's first fenced unit: the run row under its lock with its revision, the run's workflow version pinned
    (ruling 18), and an unresumable interrupted run failed in it; a run waiting for a person is left alone."""
    async with deps.conn.transaction():
        await persistence.set_tenant(deps.conn, job["tenant_id"])  # the worker's own reads are RLS-scoped
        await persistence.fenced(deps.conn, lease)  # run_lease before runs (SA:188, ruling 29)
        run = dict(await persistence.run_row(deps.conn, job["run_id"], lock=True))
        run["revision"] = await persistence.run_revision(deps.conn, job["run_id"])
        pinned = await persistence.record_workflow_version(deps.conn, job["run_id"], WORKFLOW_VERSION)
        if pinned != WORKFLOW_VERSION:  # its freeze refuses this worker's payloads; routing across a bump is T36's
            log.warning(
                "job %s: run %s is pinned to workflow %s, this worker runs %s",
                job["id"],
                job["run_id"],
                pinned,
                WORKFLOW_VERSION,
            )
        state = RunState(run["state"])
        run["manual"] = await _waits_for_person(deps.conn, run)
        if state in _MID_RUN and run.get("checkpoint_id") is None and not run["manual"]:
````

Edit 152 (`worker/src/ops_worker/handlers.py`), replace:
````python
    """Start the run's graph, or resume it from its stored checkpoint after an interruption (SA:214)."""
    await _carry_on(deps, job, lease, await _first_unit(deps, job, lease))


async def _carry_on(deps: Deps, job: dict[str, Any], lease: Lease, run: dict[str, Any]) -> None:
    """A run in QUEUED, RETRIEVING or DRAFTING: a new graph run, or crash recovery from the stored checkpoint."""
    state, stored = RunState(run["state"]), run.get("checkpoint_id")
    if state in _MID_RUN or (state is RunState.QUEUED and stored is not None):
        # An earlier owner stopped mid-run, or after a clarification moved the run back to QUEUED: resume from the
        # stored checkpoint, never from the thread's newest one (a stray head is ignored, R108). One that is the end of
        # a graph run has nothing to resume: the run starts a new graph run.
        if await _resumable(deps, job, lease, state, stored):
            assert stored is not None  # _resumable found it
            if await build.ended(Context(deps, job, lease), build.thread_id(lease.run_id, 1), stored):
                await _drive(deps, job, lease, initial(lease.run_id), None)
            else:
                await _drive(deps, job, lease, None, stored)
    elif state is RunState.QUEUED:
        await _drive(deps, job, lease, initial(lease.run_id), None)
````
with:
````python
    """Start the run's graph, or resume it from its stored checkpoint after an interruption (SA:214). The job's key
    names the revision it wakes (`run_id:revision`, SA:455); a job for an older revision ends here (T21 ruling 1)."""
    run = await _first_unit(deps, job, lease)
    woken = int(str(job["dedup_key"]).rpartition(":")[2])
    if woken != run["revision"]:
        log.info(
            "job %s: it wakes revision %s; run %s is at revision %s", job["id"], woken, lease.run_id, run["revision"]
        )
        return
    await _carry_on(deps, job, lease, run)


async def _carry_on(deps: Deps, job: dict[str, Any], lease: Lease, run: dict[str, Any]) -> None:
    """A run in QUEUED, RETRIEVING or DRAFTING: a new graph run, or crash recovery from the stored checkpoint."""
    state, stored, revision = RunState(run["state"]), run.get("checkpoint_id"), int(run["revision"])
    if run.get("manual"):
        log.info("job %s: run %s waits for a manual proposal", job["id"], lease.run_id)
    elif state in _MID_RUN or (state is RunState.QUEUED and stored is not None):
        # An earlier owner stopped mid-run, or after a clarification moved the run back to QUEUED: resume from the
        # stored checkpoint, never from the thread's newest one (a stray head is ignored, R108). One that is the end of
        # a graph run has nothing to resume: the run starts a new graph run.
        if await _resumable(deps, job, lease, state, stored, revision):
            assert stored is not None  # _resumable found it
            if await build.ended(Context(deps, job, lease), build.thread_id(lease.run_id, revision), stored):
                await _drive(deps, job, lease, initial(lease.run_id), None, revision)
            else:
                await _drive(deps, job, lease, None, stored, revision)
    elif state is RunState.QUEUED:
        await _drive(deps, job, lease, initial(lease.run_id), None, revision)
````

Edit 153 (`worker/src/ops_worker/handlers.py`), replace:
````python
    if not await _resumable(deps, job, lease, state, stored):
````
with:
````python
    if not await _resumable(deps, job, lease, state, stored, run["revision"]):
````

Edit 154 (`worker/src/ops_worker/handlers.py`), replace:
````python
    await _drive(deps, job, lease, Command(resume=str(reply)), stored)
````
with:
````python
    await _drive(deps, job, lease, Command(resume=str(reply)), stored, run["revision"])
````

Edit 155 (`worker/src/ops_worker/handlers.py`), replace:
````python
    stored = run.get("checkpoint_id")
    thread = build.thread_id(lease.run_id, 1)
    ctx = Context(deps, job, lease)
````
with:
````python
    stored, revision = run.get("checkpoint_id"), int(run["revision"])
    thread = build.thread_id(lease.run_id, revision)
    ctx = Context(deps, job, lease, revision)
````

Edit 156 (`worker/src/ops_worker/handlers.py`), replace:
````python
        await _drive(deps, job, lease, graph_input, checkpoint)
````
with:
````python
        await _drive(deps, job, lease, graph_input, checkpoint, revision)
````

Edit 157 (`worker/src/ops_worker/main.py`), replace:
````python
    # The saver's own connection (SA:559-562): its writes never share a transaction with an application unit.
````
with:
````python
    await persistence.assert_function_text(probe, *persistence.FREEZE_GUARD)  # revision 0016: the guarded freeze
    # The saver's own connection (SA:559-562): its writes never share a transaction with an application unit.
````

Edit 158 (`worker/src/ops_worker/proposals.py`), replace:
````python
EXPIRY = timedelta(minutes=15)  # BUILD_SPEC §12 default; enforced by T21
````
with:
````python
# BUILD_SPEC §12 default, counted from the application clock; freeze_proposal and the grant enforce it (T21).
EXPIRY = timedelta(minutes=15)
````

Run the same pytest line again → `7 passed`.

- [ ] **Step 3: Gates and commit**

`uv run ruff format` and `uv run ruff check --fix` over the touched files; `git add` the new files; dev `PYTHONUTF8=1 uv
run python scripts/check.py < /dev/null` → `CHECK: GREEN`, `1791 passed, 227 skipped`; `verify_handoff.py` exit 0.

```bash
git add -A -- . ':!reports'
git commit -m "feat: revisions as graph threads, the manual path, the grant's asset re-read and proposal expiry (T21)"
```

---
### Task 6: The live tests and the first live gate

**Files:**
- Create: `tests/e2e/test_r023_wakeup_live.py`, `tests/e2e/test_review_live.py`
- Modify: `tests/e2e/conftest.py`, `tests/e2e/test_admission_live.py`, `tests/e2e/test_auth_live.py`,
  `tests/e2e/test_definers_write_path_live.py`, `tests/e2e/test_graph_live.py`, `tests/e2e/test_mcp_write_live.py`,
  `tests/e2e/test_migration_0011_live.py`, `tests/e2e/test_migration_0012_live.py`,
  `tests/e2e/test_migration_0013_live.py`, `tests/e2e/test_r105_walking_skeleton.py`, `tests/e2e/test_roles_live.py`,
  `tests/e2e/test_run_manifest_live.py`, `tests/e2e/test_worker_live.py`

**Requirements:** rulings 13, 14, 20; every requirement of T21 live; R086's grant half.

- [ ] **Step 1: The live tests**

The new modules prove the review rules (`test_review_live.py`), R023 (`test_r023_wakeup_live.py`) and R086's
grant half (`test_auth_live.py`); the edited modules follow 0016: the decision's revision, the manifest's
revision, one asset per frozen run, the execute job's asset re-read, the read path's freshness after a clock
move, and the 0011-0013 round trips started from 0015.

Edit 159 (`tests/e2e/conftest.py`), replace:
````python
from collections.abc import AsyncIterator, Awaitable, Callable
````
with:
````python
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
````

Edit 160 (`tests/e2e/conftest.py`), replace:
````python
    "DELETE FROM app.events WHERE run_id = %s",
````
with:
````python
    "DELETE FROM app.feedback WHERE run_id = %s",  # T21: feedback references its run
    "DELETE FROM app.events WHERE run_id = %s",
````

Edit 161 (`tests/e2e/conftest.py`), replace:
````python
async def purge_run(conn: persistence.Conn, run_id: object) -> None:
````
with:
````python
@pytest.fixture
def at_0015(migrated: None) -> Iterator[settings.Postgres]:
    """The round trips of 0011-0013 start from 0015 and come back to it: revision 0016 (T21) re-creates functions they
    compare byte for byte and replaces `record_decision`'s signature, and its own round trip is
    tests/e2e/test_review_live.py's. The head is migrated again afterwards, whatever the test did."""
    from scripts.skeleton import downgrade, migrate

    superuser = settings.superuser_postgres()
    downgrade("app", superuser, "0015_checkpoints")
    try:
        yield superuser
    finally:
        assert migrate(Profile.TEST) == 0  # every later test needs the head


async def purge_run(conn: persistence.Conn, run_id: object) -> None:
````

Edit 162 (`tests/e2e/test_admission_live.py`), replace:
````python
        first_run = first.json()["run_id"]
````
with:
````python
````

Edit 163 (`tests/e2e/test_admission_live.py`), replace:
````python
        # AM-16 in PostgreSQL: create_run refuses a supersede across conversations (OC002) after the message is
        # written, and only start_run's savepoint takes that message back before the 404 is recorded.
        across = {**SAMPLE, "supersedes_run_id": first_run}
````
with:
````python
        # AM-16 in PostgreSQL: create_run refuses a supersede that names no run of the tenant and the asset (OC002;
        # T21, erratum 138: any conversation of the tenant) after the message is written, and only start_run's
        # savepoint takes that message back before the 404 is recorded.
        across = {**SAMPLE, "supersedes_run_id": str(uuid4())}
````

Edit 164 (`tests/e2e/test_auth_live.py`), replace:
````python
from tests.e2e.kc_browser import API, ORIGIN, Browser, TestAdmin
````
with:
````python
from tests.e2e.conftest import expire_lease, purge_run, stage_lease
from tests.e2e.kc_browser import API, ORIGIN, Browser, TestAdmin
from tests.e2e.test_review_live import asset, decide, drafting_on, frozen
````

Edit 165 (`tests/e2e/test_auth_live.py`), replace:
````python
@pytest.mark.asyncio
async def test_disabled_user_is_refused_and_synced_within_60s(
    skeleton: Skeleton, browser: Browser, secret, admin: TestAdmin, app_conn: persistence.Conn, lines: list[str]
) -> None:
    """R086: disable sam in Keycloak; sam's next decision-class mutation is 401 at once (admin-API check), the sync
    deactivates sam's membership within 60 s, and sam's still-valid bearer token then fails every protected read.
    The finally block re-enables sam at Keycloak; the module fixture restores the row once the sweeper is gone."""
    kcs = settings.keycloak()
    sam_token = kc.token_password(kcs.base_url, "ops-dev-direct", "sam", secret("kc_persona_sam_password"))
    headers = {"Authorization": f"Bearer {sam_token['access_token']}"}
    body = {"expected_revision": 1, "expected_payload_sha256": "0" * 64, "decision": "approve"}
    decision_url = f"/api/v1/proposals/{UUID(int=1)}/decisions"
````
with:
````python
async def held_approval(app_conn: persistence.Conn, role_conn) -> UUID:
    """A run of ALPHA that sam approved while enabled, whose execute job waits behind a lease the test holds, so the
    skeleton's worker meets it only when the test lets it go (T21, Plan R ruling 14)."""
    api, worker = await role_conn(settings.Role.API), await role_conn(settings.Role.WORKER)
    run = await drafting_on(app_conn, api, worker, asset())
    result, digest = await frozen(app_conn, worker, run)
    await stage_lease(app_conn, run, owner="r086-hold", seconds=600)  # before the decision queues the job
    await decide(api, result.proposal_id, digest)
    return run


@pytest.mark.asyncio
async def test_disabled_user_is_refused_and_synced_within_60s(
    skeleton: Skeleton,
    browser: Browser,
    secret,
    admin: TestAdmin,
    app_conn: persistence.Conn,
    role_conn,
    lines: list[str],
) -> None:
    """R086: disable sam in Keycloak; sam's next decision-class mutation is 401 at once (admin-API check), the sync
    deactivates sam's membership within 60 s, and sam's still-valid bearer token then fails every protected read.
    Its grant half (T21): an execute job of a run sam approved before the disable, let go after the sync, meets a
    real grant that refuses it, and the run is BLOCKED_REVIEW(authority_revoked) with no grant.
    The finally block re-enables sam at Keycloak; the module fixture restores the row once the sweeper is gone."""
    kcs = settings.keycloak()
    sam_token = kc.token_password(kcs.base_url, "ops-dev-direct", "sam", secret("kc_persona_sam_password"))
    headers = {"Authorization": f"Bearer {sam_token['access_token']}"}
    body = {"expected_revision": 1, "expected_payload_sha256": "0" * 64, "decision": "approve"}
    decision_url = f"/api/v1/proposals/{UUID(int=1)}/decisions"
    held = await held_approval(app_conn, role_conn)
````

Edit 166 (`tests/e2e/test_auth_live.py`), replace:
````python
    finally:
        # Re-enable unconditionally and record the status; an assert here would hide the original failure. The row is
        # restored by the module fixture, after the sweeper stops.
        lines.append(f"sam re-enabled at keycloak: {admin.set_enabled(SAM, True)}")
````
with:
````python
        # The grant half (T21, Plan R ruling 14): let the skeleton's worker take the held execute job now. Its real
        # grant_execution re-reads the reviewer's membership, which the sync deactivated (BS:178).
        await expire_lease(app_conn, held)
        await app_conn.execute(
            "UPDATE app.jobs SET available_at = app.current_time() WHERE run_id = %s AND type = 'execute'", (held,)
        )
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            cur = await app_conn.execute(
                "SELECT r.state, r.reason, j.done_at IS NOT NULL AS done FROM app.runs r JOIN app.jobs j"
                " ON j.run_id = r.run_id AND j.type = 'execute' WHERE r.run_id = %s",
                (held,),
            )
            ended = await cur.fetchone()
            if ended["done"]:
                break
            await asyncio.sleep(0.5)
        cur = await app_conn.execute("SELECT count(*) AS n FROM app.execution_grant WHERE run_id = %s", (held,))
        grants = (await cur.fetchone())["n"]
        assert (ended["state"], ended["reason"], grants) == ("BLOCKED_REVIEW", "authority_revoked", 0), ended
        lines.append(f"grant after the disable: {ended['state']} ({ended['reason']}), grants {grants}")
    finally:
        # Re-enable unconditionally and record the status; an assert here would hide the original failure. The row is
        # restored by the module fixture, after the sweeper stops.
        lines.append(f"sam re-enabled at keycloak: {admin.set_enabled(SAM, True)}")
        await purge_run(app_conn, held)
````

Edit 167 (`tests/e2e/test_definers_write_path_live.py`), replace:
````python
    async with as_role(worker):  # the worker's own INSERT on drafts (AM-20.2) under its tenant, then the function
````
with:
````python
    # T21: the grant checks the asset observation's age (R116); this helper's runs are never retrieved, so the
    # superuser records one as retrieval would. Each frozen run also gets an asset of its own: the asset guard
    # (SA:189) blocks a second unresolved action on one asset and interval, and the tests that freeze several runs
    # (and the R089 stress) are about other things; tests/e2e/test_review_live.py proves the guard.
    await app_conn.execute(
        "UPDATE app.runs SET asset_observed_at = app.current_time(), asset_id = 'A17-' || left(run_id::text, 8)"
        " WHERE run_id = %s",
        (run,),
    )
    async with as_role(worker):  # the worker's own INSERT on drafts (AM-20.2) under its tenant, then the function
````

Edit 168 (`tests/e2e/test_definers_write_path_live.py`), replace:
````python
            "SELECT * FROM app.record_decision(%s, %s, %s, %s, 'approve', NULL, NULL)",
            (tenant, proposal, reviewer, digest),
````
with:
````python
            "SELECT * FROM app.record_decision(%s, %s, %s, 1, %s, 'approve', NULL, NULL)",  # T21: revision 1
            (tenant, proposal, reviewer, digest),
````

Edit 169 (`tests/e2e/test_definers_write_path_live.py`), replace:
````python
        call = "SELECT * FROM app.record_decision(%s, %s, %s, %s, 'approve', NULL, NULL)"
````
with:
````python
        call = "SELECT * FROM app.record_decision(%s, %s, %s, 1, %s, 'approve', NULL, NULL)"
````

Edit 170 (`tests/e2e/test_definers_write_path_live.py`), replace:
````python
                "SELECT * FROM app.record_decision(%s, %s, %s, %s, 'reject', 'rejected', NULL)",
````
with:
````python
                "SELECT * FROM app.record_decision(%s, %s, %s, 1, %s, 'reject', 'rejected', NULL)",
````

Edit 171 (`tests/e2e/test_definers_write_path_live.py`), replace:
````python
                "SELECT * FROM app.record_decision(%s, %s, %s, %s, 'approve', NULL, NULL)",
````
with:
````python
                "SELECT * FROM app.record_decision(%s, %s, %s, 1, %s, 'approve', NULL, NULL)",
````

Edit 172 (`tests/e2e/test_graph_live.py`), replace:
````python
        assert [c[1] for c in called.calls] == ["create_incident"]
````
with:
````python
        # T21 (erratum 137): the execute job reads the asset status again before the grant.
        assert [c[1] for c in called.calls] == ["get_asset_status", "create_incident"]
````

Edit 173 (`tests/e2e/test_mcp_write_live.py`), replace:
````python
        "evidence_refs": ["ALPHA-INCIDENT:v2:review"],
        "source_snapshots": [
            {
                "evidence_id": "ALPHA-INCIDENT:v2:review",
                "content_sha256": "62a90906c7bb706ae8a968eb0f7102f76b05d2c3be911c182d528a1fd25ef008",
                "version": "2",
            }
        ],
````
with:
````python
        # T21: the grant rechecks every cited section against the tenant's corpus (BS:425), which these write-path
        # tests do not ingest, so this payload cites none; tests/e2e/test_review_live.py cites real ones.
        "evidence_refs": [],
        "source_snapshots": [],
````

Edit 174 (`tests/e2e/test_mcp_write_live.py`), replace:
````python
    # One worker transaction: set_tenant is transaction-local, and on autocommit the INSERT would meet RLS.
````
with:
````python
    # T21: the run's workflow version (the worker pins it at the first claim, ruling 18) and the asset observation the
    # grant checks (R116), as a worker's retrieval would have recorded them. The run gets an asset of its own: tests
    # that approve two runs would otherwise meet the asset guard (SA:189), which tests/e2e/test_review_live.py proves.
    await app_conn.execute(
        "UPDATE app.runs SET workflow_version = %s, asset_observed_at = app.current_time(),"
        " asset_id = 'A17-' || left(run_id::text, 8) WHERE run_id = %s",
        (payload["workflow_version"], run),
    )
    # One worker transaction: set_tenant is transaction-local, and on autocommit the INSERT would meet RLS.
````

Edit 175 (`tests/e2e/test_mcp_write_live.py`), replace:
````python
            api, tenant_id=tenant, proposal_id=proposal, reviewer=SAM, expected_payload_sha256=sha, decision="approve"
````
with:
````python
            api,
            tenant_id=tenant,
            proposal_id=proposal,
            reviewer=SAM,
            expected_revision=1,
            expected_payload_sha256=sha,
            decision="approve",
````

Edit 176 (`tests/e2e/test_migration_0011_live.py`), replace:
````python
from ops_core.settings import Profile, Role
````
with:
````python
from ops_core.settings import Role
````

Edit 177 (`tests/e2e/test_migration_0011_live.py`), replace:
````python
            worker = await role_conn(Role.WORKER)
````
with:
````python
            # T21 (ruling 14): the read path now refuses a membership the sync has not stamped within 120 s of
            # the database clock, so the superuser stamps it again at the moved instant, as the sweeper would.
            await app_conn.execute("UPDATE app.memberships SET synced_at = app.current_time()")
            worker = await role_conn(Role.WORKER)
````

Edit 178 (`tests/e2e/test_migration_0011_live.py`), replace:
````python
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    from scripts.skeleton import downgrade, migrate
````
with:
````python
    app_conn: persistence.Conn, role_conn: RoleConn, at_0015: settings.Postgres
) -> None:
    from scripts.skeleton import downgrade, upgrade
````

Edit 179 (`tests/e2e/test_migration_0011_live.py`), replace:
````python
        assert migrate(Profile.TEST) == 0  # every later test needs the head
````
with:
````python
        upgrade("app", at_0015, "0015_checkpoints")  # the fixture migrates the head afterwards (T21)
````

Edit 180 (`tests/e2e/test_migration_0012_live.py`), replace:
````python
from ops_core.settings import Profile, Role
````
with:
````python
from ops_core.settings import Role
````

Edit 181 (`tests/e2e/test_migration_0012_live.py`), replace:
````python
            await harness.execute("UPDATE app.test_clock SET clock_offset = interval '1 day'")
````
with:
````python
            await harness.execute("UPDATE app.test_clock SET clock_offset = interval '1 day'")
            # T21 (ruling 14): the read path now refuses a membership the sync has not stamped within 120 s of
            # the database clock, so the superuser stamps it again at the moved instant, as the sweeper would.
            await app_conn.execute("UPDATE app.memberships SET synced_at = app.current_time()")
````

Edit 182 (`tests/e2e/test_migration_0012_live.py`), replace:
````python
            await harness.execute("UPDATE app.test_clock SET clock_offset = interval '2 days'")
````
with:
````python
            await harness.execute("UPDATE app.test_clock SET clock_offset = interval '2 days'")
            # T21 (ruling 14): the read path now refuses a membership the sync has not stamped within 120 s of
            # the database clock, so the superuser stamps it again at the moved instant, as the sweeper would.
            await app_conn.execute("UPDATE app.memberships SET synced_at = app.current_time()")
````

Edit 183 (`tests/e2e/test_migration_0012_live.py`), replace:
````python
async def test_the_round_trip_restores_0011(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    from scripts.skeleton import downgrade, migrate
````
with:
````python
async def test_the_round_trip_restores_0011(
    app_conn: persistence.Conn, role_conn: RoleConn, at_0015: settings.Postgres
) -> None:
    from scripts.skeleton import downgrade, upgrade
````

Edit 184 (`tests/e2e/test_migration_0012_live.py`), replace:
````python
        assert migrate(Profile.TEST) == 0  # every later test needs the head
````
with:
````python
        upgrade("app", at_0015, "0015_checkpoints")  # the fixture migrates the head afterwards (T21)
````

Edit 185 (`tests/e2e/test_migration_0013_live.py`), replace:
````python
from ops_core.settings import Profile, Role
````
with:
````python
from ops_core.settings import Role
````

Edit 186 (`tests/e2e/test_migration_0013_live.py`), replace:
````python
async def test_the_round_trip_restores_0012(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    from scripts.skeleton import downgrade, migrate
````
with:
````python
async def test_the_round_trip_restores_0012(
    app_conn: persistence.Conn, role_conn: RoleConn, at_0015: settings.Postgres
) -> None:
    from scripts.skeleton import downgrade, upgrade
````

Edit 187 (`tests/e2e/test_migration_0013_live.py`), replace:
````python
        assert migrate(Profile.TEST) == 0  # every later test needs the head (the `embedded` fixture re-embeds)
````
with:
````python
        upgrade("app", at_0015, "0015_checkpoints")  # the fixture migrates the head afterwards (T21)
````

Create `tests/e2e/test_r023_wakeup_live.py`:
````python
"""R023 live (OPS_LIVE=1; T21, Plan R ruling 13): an approval's wake-up survives a worker that dies between the
resume's checkpoint and the job's final unit, on LangGraph's Postgres saver against the per-session test database.

The worker resumes the reviewer wait with the decision's event, the saver stores that step, and the process dies
before the execute job's final unit: the job stays claimed and the lease runs out. The sweeper's reclaim hands the
job back, and the next worker (a new graph instance on a new saver connection) carries on from the stored step, whose
one resume write is the accepted `approval.recorded` event, and grants exactly the decided proposal. Catches: a
wake-up lost with the dead worker, a resume with another event, or a grant of anything but the accepted proposal. The
worker has no fault hook (Plan H ruling 20), so the death is a `BaseException` the scripted read raises, which no node
and no handler catches, as a killed process would leave it. The crash points before and after this one are the unit
tests' (`tests/plan_r/test_worker_review.py`).
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from uuid import UUID

import psycopg
import pytest
import pytest_asyncio
from ops_core import persistence, settings
from ops_core.outcomes import EventType
from ops_core.settings import Role
from ops_sweeper import leases
from ops_worker import handlers
from ops_worker.drafting import FakeDraftGenerator
from ops_worker.graph import build

from tests.e2e.conftest import expire_lease, purge_conversation
from tests.e2e.test_migrations_and_persistence import new_run
from tests.e2e.test_worker_live import (
    ALPHA,
    GrantThenDownMcp,
    ScriptedMcp,
    approve,
    granting_reads,
    own_job,
    proposal_of,
)

pytestmark = pytest.mark.asyncio
RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
ASSET = "A23"  # an asset of its own: no other module's run can meet this one in the asset guard


class Died(BaseException):
    """The worker process dying: not an Exception, so no node, handler or final unit sees it."""


class DiesAtTheReRead(ScriptedMcp):
    """Answers the investigation's reads; the execute job's asset status read (the first call after the resume's
    checkpoint was stored) kills the worker."""

    async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool == "get_asset_status" and any(c[1] == "search_procedures" for c in self.calls):
            self.calls.append((url, tool, arguments))
            raise Died
        return await super().call(url, handle=handle, tool=tool, arguments=arguments)


Worker = Callable[[type[ScriptedMcp]], Awaitable[tuple[handlers.Deps, ScriptedMcp]]]


@pytest_asyncio.fixture
async def worker(app_conn: persistence.Conn, role_conn: RoleConn) -> AsyncIterator[Worker]:
    """A factory of worker Deps on the Postgres saver, each on its own connections (a fresh process as far as the graph
    can tell), with a read script the grant accepts; every saver connection is closed at the end."""
    opened: list[psycopg.AsyncConnection[Any]] = []

    async def build_deps(mcp_class: type[ScriptedMcp]) -> tuple[handlers.Deps, ScriptedMcp]:
        conn, saver = await build.open_saver(settings.app_postgres(Role.WORKER))
        opened.append(conn)
        mcp = mcp_class(await role_conn(Role.MCP_READ), await role_conn(Role.MCP_EXEC))
        await granting_reads(app_conn, mcp, ASSET)
        deps = handlers.Deps(
            conn=await role_conn(Role.WORKER),
            mcp=mcp,
            generator=FakeDraftGenerator(),
            urls=settings.urls(),
            worker_name="t",
            workload_azp="ops-worker",
            saver=saver,
        )
        return deps, mcp

    yield build_deps
    for conn in opened:
        await conn.close()


async def test_r023_a_lost_execute_wakeup_resumes_exactly_the_accepted_event(
    app_conn: persistence.Conn,
    role_conn: RoleConn,
    worker: Worker,
    ingested: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resumed_with: list[UUID | None] = []
    real = handlers._approval

    async def spied(*args: Any, **kwargs: Any) -> UUID | None:
        found = await real(*args, **kwargs)
        resumed_with.append(found)
        return found

    monkeypatch.setattr(handlers, "_approval", spied)
    run = None
    try:
        first, first_mcp = await worker(DiesAtTheReRead)
        _, _, run = await new_run(app_conn, ALPHA, api=await role_conn(Role.API), asset_id=ASSET)
        await handlers.handle(first, *await own_job(app_conn, first.conn, run, "investigate"))
        proposal = await proposal_of(app_conn, run)
        await approve(await role_conn(Role.API), proposal)
        cur = await app_conn.execute(
            "SELECT event_id, payload FROM app.events WHERE run_id = %s AND type = %s",
            (run, EventType.APPROVAL_RECORDED.value),
        )
        (accepted,) = await cur.fetchall()
        waiting = str((await persistence.run_row(app_conn, run))["checkpoint_id"])  # the reviewer wait
        job, lease = await own_job(app_conn, first.conn, run, "execute")
        with pytest.raises(Died):
            await handlers.handle(first, job, lease)
        assert [c[1] for c in first_mcp.calls][-1] == "get_asset_status"  # it died at the re-read, before the grant
        # The resume's step was stored, and its id recorded on the run, before the death (SA:211).
        resumed = str((await persistence.run_row(app_conn, run))["checkpoint_id"])
        cur = await app_conn.execute(
            "SELECT count(*) AS n FROM checkpoints.checkpoints WHERE thread_id = %s AND checkpoint_id = %s",
            (build.thread_id(run, 1), resumed),
        )
        assert resumed > waiting and (await cur.fetchone())["n"] == 1  # ids are time-ordered (uuid6)
        cur = await app_conn.execute("SELECT claimed_by, done_at FROM app.jobs WHERE id = %s", (job["id"],))
        assert dict(await cur.fetchone()) == {"claimed_by": "t", "done_at": None}  # no final unit ran
        # The sweeper's reclaim hands the job back once the dead worker's lease has run out (SA:471).
        await expire_lease(app_conn, run)
        assert job["id"] in await leases.reclaim(await role_conn(Role.SWEEPER))
        second, _ = await worker(GrantThenDownMcp)
        await handlers.handle(second, *await own_job(app_conn, second.conn, run, "execute"))
        # The event was consumed once: the second job forks from the stored step after the resume (SA:214) and
        # never resumes again, and the saver's one resume write carries the accepted event's id.
        assert resumed_with == [accepted["event_id"]]
        cur = await app_conn.execute(
            "SELECT blob FROM checkpoints.checkpoint_writes WHERE thread_id = %s AND channel = '__resume__'",
            (build.thread_id(run, 1),),
        )
        (write,) = await cur.fetchall()
        assert str(accepted["event_id"]).encode() in bytes(write["blob"])
        cur = await app_conn.execute("SELECT proposal_id FROM app.execution_grant WHERE run_id = %s", (run,))
        grants = [r["proposal_id"] for r in await cur.fetchall()]
        assert grants == [proposal["proposal_id"]] == [UUID(accepted["payload"]["proposal_id"])]
        assert (await persistence.run_row(app_conn, run))["state"] == "EXECUTING"
    finally:
        if run is not None:
            for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
                await app_conn.execute(
                    f"DELETE FROM checkpoints.{table} WHERE thread_id = %s", (build.thread_id(run, 1),)
                )
            cur = await app_conn.execute("SELECT conversation_id FROM app.runs WHERE run_id = %s", (run,))
            found = await cur.fetchone()
            if found is not None:
                await purge_conversation(app_conn, found["conversation_id"])
````

Edit 188 (`tests/e2e/test_r105_walking_skeleton.py`), replace:
````python
    ("action.granted", "application"),
````
with:
````python
    ("tool.started", "application"),  # T21: the asset status read again before the grant (R116, erratum 137)
    ("tool.completed", "application"),
    ("action.granted", "application"),
````

Edit 189 (`tests/e2e/test_r105_walking_skeleton.py`), replace:
````python
        assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"
````
with:
````python
        assert stale.status_code == 409 and stale.json()["code"] == "STALE_HASH"  # T21: its own code (ruling 3)
````

Create `tests/e2e/test_review_live.py`:
````python
"""Revision 0016's review rules as their callers meet them in PostgreSQL (OPS_LIVE=1; T21: R043, R044, R045, R046,
R057, R090, R092, R093, R100, R113, R116, R120, R125; DEV-006 to DEV-014, DEV-020, DEV-025).

Catches: a decision that authorizes another revision, hash or an expired proposal (R044, DEV-008, DEV-009); a content
author approving (R043, R093); an expiry that needs a reviewer or a live worker (R092); a grant that does not re-check
authority, cited sources, the asset observation or the asset guard (R045, R116, R125), or commits BLOCKED_REVIEW for a
refusal that must commit nothing (HASH_MISMATCH, R100); a revision after a grant (R090) or into an occupied slot
(R120); a cancel that undoes a grant (R046); a manual proposal outside the freeze rules or citing another tenant's
section (R057, note 4); feedback that changes anything but its own row and event (R113); a read that trusts a
membership the sync has not stamped (ruling 14); and a downgrade that does not restore revision 0015.

Each run is put on an asset of its own (`asset()`), so the asset guard meets only what the test staged. Rows are
written by role connections, so every test purges its runs and memberships in `finally`.
"""

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from ops_api.idempotency import Idem, Scope, fingerprint
from ops_api.store import DbStore
from ops_core import persistence, settings
from ops_core.canonical import canonical_json, sha256_hex
from ops_core.contracts import FeedbackRequest, ManualProposalRequest, load
from ops_core.outcomes import ActionOutcome, Receipt, ToolOutcome
from ops_core.settings import Role
from ops_sweeper import expiry
from psycopg.types.json import Jsonb

from tests.e2e.conftest import purge_conversation, purge_run, stage_lease
from tests.e2e.test_definers_run_path_live import ALEX, ALPHA
from tests.e2e.test_definers_write_path_live import SAM, drafting_run, handle_for
from tests.e2e.test_migration_0011_live import APP_FUNCTIONS

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
WORKFLOW = "investigation-v1"
GRANT_AZP = "ops-worker"


def asset() -> str:
    """An asset no other test uses: the asset guard (SA:189) compares runs on one asset and interval only."""
    return f"R-{uuid4().hex[:10].upper()}"  # AssetId: ^[A-Z][A-Z0-9_-]{0,31}$


async def member(app_conn: persistence.Conn, *roles: str) -> UUID:
    """A new subject of ALPHA with the given roles, synced now (the issuer is the seeded rows' own)."""
    subject = uuid4()
    for role in roles:
        await app_conn.execute(
            "INSERT INTO app.memberships (tenant_id, issuer, subject, role, synced_at)"
            " SELECT %s, m.issuer, %s, %s, app.current_time() FROM app.memberships m WHERE m.tenant_id = %s LIMIT 1",
            (ALPHA, subject, role, ALPHA),
        )
    return subject


async def forget(app_conn: persistence.Conn, runs: list[UUID], subjects: list[UUID]) -> None:
    """Purge the runs, then the memberships the test added (decisions reference neither)."""
    for run in runs:
        await purge_run(app_conn, run)
    for subject in subjects:
        await app_conn.execute("DELETE FROM app.memberships WHERE subject = %s", (subject,))


async def drafting_on(
    app_conn: persistence.Conn, api: persistence.Conn, worker: persistence.Conn, where: str, *, days_back: int = 0
) -> UUID:
    """A DRAFTING run of ALPHA on `where` over the 24 hours ending `days_back` days ago, with the workflow version the
    worker pins at its first claim and a fresh asset observation (R116), as a worker's retrieval would leave it."""
    run = await drafting_run(app_conn, api, worker)
    end = await app_conn.execute(
        "SELECT date_trunc('second', app.current_time()) - make_interval(days => %s) AS at", (days_back,)
    )
    at = (await end.fetchone())["at"]
    await app_conn.execute(
        "UPDATE app.runs SET asset_id = %s, start_at = %s, end_at = %s, workflow_version = %s,"
        " asset_observed_at = app.current_time() WHERE run_id = %s",
        (where, at - timedelta(hours=24), at, WORKFLOW, run),
    )
    return run


async def frozen(
    app_conn: persistence.Conn,
    worker: persistence.Conn,
    run: UUID,
    *,
    revision: int = 1,
    snapshots: list[dict[str, str]] | None = None,
    supersedes: UUID | None = None,
) -> tuple[persistence.Frozen, str]:
    """Freeze a validated draft of `run` as the worker, expiring 15 minutes from the database clock; the result and
    the payload hash. The payload cites `snapshots` (none by default)."""
    cur = await app_conn.execute("SELECT asset_id FROM app.runs WHERE run_id = %s", (run,))
    where = (await cur.fetchone())["asset_id"]
    expires = (await persistence.current_time(app_conn)).replace(microsecond=0) + timedelta(minutes=15)
    cited = snapshots or []
    body = canonical_json(
        {
            "tenant_id": str(ALPHA),
            "run_id": str(run),
            "proposal_id": str(uuid4()),
            "revision": revision,
            "action": "create_incident",
            "destination": "synthetic-incidents",
            "asset_id": where,
            "title": "Review live",
            "summary": "Synthetic.",
            "evidence_refs": [s["evidence_id"] for s in cited],
            "source_snapshots": cited,
            "supersedes_run_id": None if supersedes is None else str(supersedes),
            "workflow_version": WORKFLOW,
            "expires_at": expires.isoformat().replace("+00:00", "Z"),
        }
    )
    draft = uuid4()
    async with worker.transaction():
        await persistence.set_tenant(worker, ALPHA)
        await worker.execute(
            "INSERT INTO app.drafts (id, tenant_id, run_id, draft_sha256, validated, kind)"
            " VALUES (%s, %s, %s, %s, true, 'proposal')",
            (draft, ALPHA, run, sha256_hex(body)),
        )
        result = await persistence.freeze_proposal(
            worker, run_id=run, draft_id=draft, payload_canonical=body, expires_at=expires
        )
    return result, sha256_hex(body)


async def decide(
    api: persistence.Conn, proposal: UUID | None, digest: str, *, reviewer: UUID = SAM, revision: int = 1
) -> persistence.Decided:
    """`record_decision` as the API, approving."""
    assert proposal is not None
    async with api.transaction():
        return await persistence.record_decision(
            api,
            tenant_id=ALPHA,
            proposal_id=proposal,
            reviewer=reviewer,
            expected_revision=revision,
            expected_payload_sha256=digest,
            decision="approve",
        )


async def refusal(call: Awaitable[Any]) -> str:
    """The code a refused call carries: Refused's or VersionConflict's DETAIL."""
    try:
        await call
    except (persistence.Refused, persistence.VersionConflict) as exc:
        return str(exc.code)
    raise AssertionError("expected a refusal")


async def grant(app_conn: persistence.Conn, mcp_exec: persistence.Conn, run: UUID, proposal: UUID | None) -> Any:
    """`grant_execution` as mcp-write would call it, through a write handle of the run's execute job."""
    assert proposal is not None
    handle = await handle_for(app_conn, run, "execute", expires_in=600)
    async with mcp_exec.transaction():
        return await persistence.grant_execution(mcp_exec, handle=handle, azp=GRANT_AZP, proposal_id=proposal)


async def state_of(app_conn: persistence.Conn, run: UUID) -> tuple[str, str | None]:
    row = await persistence.run_row(app_conn, run)
    return row["state"], row["reason"]


async def permitted_section(app_conn: persistence.Conn) -> dict[str, str]:
    """One permitted section of ALPHA's ingested corpus as a snapshot (evidence id, content hash, version)."""
    cur = await app_conn.execute(
        "SELECT evidence_id, content_sha256, version FROM app._cited_permitted(%s,"
        " ARRAY(SELECT evidence_id FROM app.chunks WHERE tenant_id = %s)) ORDER BY evidence_id LIMIT 1",
        (ALPHA, ALPHA),
    )
    row = await cur.fetchone()
    assert row is not None, "ALPHA has no permitted section"
    return dict(row)


async def test_a_revision_is_reviewed_again_and_never_by_its_author(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """R043, R044, R093, DEV-006, DEV-009: revision 2 clears revision 1's approval path; the old proposal cannot be
    decided, the requester who revised it cannot approve it, and another reviewer can, exactly once."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    pat = await member(app_conn, "requester", "reviewer")  # both scopes on one identity (R043)
    run = await drafting_on(app_conn, api, worker, asset())
    try:
        first, first_hash = await frozen(app_conn, worker, run)
        assert (first.state.value, first.revision) == ("AWAITING_APPROVAL", 1)
        async with api.transaction():
            revised = await persistence.create_revision(
                api, tenant_id=ALPHA, run_id=run, expected_version=4, author=pat, supersedes_run_id=None
            )
        assert (revised.revision, revised.state_version) == (2, 5)
        row = await persistence.run_row(app_conn, run)
        assert (row["state"], row["active_proposal_id"], row["checkpoint_id"]) == ("QUEUED", None, None)
        assert row["authors"] == [ALEX, pat]  # ruling 4: the reviser joins the content authors
        cur = await app_conn.execute(
            "SELECT dedup_key FROM app.jobs WHERE run_id = %s AND type = 'investigate' ORDER BY dedup_key", (run,)
        )
        assert [r["dedup_key"] for r in await cur.fetchall()] == [f"{run}:1", f"{run}:2"]  # SA:455: run_id:revision
        # The stale version is refused, and revision 1 can no longer be decided (DEV-009: sam clicks revision 1).
        async with api.transaction():
            stale = refusal(
                persistence.create_revision(
                    api, tenant_id=ALPHA, run_id=run, expected_version=4, author=pat, supersedes_run_id=None
                )
            )
            assert await stale == f"run {run} is QUEUED at version 5"
        assert await refusal(decide(api, first.proposal_id, first_hash)) == "STALE_REVISION"
        async with worker.transaction():
            await worker.execute("SELECT app.transition_run(%s, 'QUEUED', 'RETRIEVING', NULL, 5, '{}')", (run,))
            await worker.execute("SELECT app.transition_run(%s, 'RETRIEVING', 'DRAFTING', NULL, 6, '{}')", (run,))
        second, second_hash = await frozen(app_conn, worker, run, revision=2)
        assert (second.state.value, second.revision) == ("AWAITING_APPROVAL", 2)
        cur = await app_conn.execute(
            "SELECT revision, authored_by FROM app.proposals WHERE run_id = %s ORDER BY revision", (run,)
        )
        assert [(r["revision"], r["authored_by"]) for r in await cur.fetchall()] == [(1, [ALEX]), (2, [ALEX, pat])]
        # Independence (BS:466): the reviser is refused whatever else is right; the revision and the hash are each
        # checked under the run's lock; then sam approves, once.
        assert await refusal(decide(api, second.proposal_id, second_hash, reviewer=pat, revision=2)) == "SELF_REVIEW"
        assert await refusal(decide(api, second.proposal_id, second_hash, reviewer=ALEX, revision=2)) == "NOT_REVIEWER"
        assert await refusal(decide(api, second.proposal_id, second_hash, revision=1)) == "STALE_REVISION"
        assert await refusal(decide(api, second.proposal_id, "0" * 64, revision=2)) == "STALE_HASH"
        decided = await decide(api, second.proposal_id, second_hash, revision=2)
        assert decided.state.value == "APPROVED"
        assert await refusal(decide(api, second.proposal_id, second_hash, revision=2)) == "ALREADY_DECIDED"
    finally:
        await forget(app_conn, [run], [pat])


async def test_an_expired_proposal_is_blocked_by_the_sweeper_and_refused_to_the_reviewer(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """R092, DEV-008: sixteen minutes on the database clock; the decision is refused EXPIRED and commits nothing, the
    sweeper's routine (no worker, no reviewer) moves the run to BLOCKED_REVIEW(expired) once, and the decision stays
    refused. A freeze whose expiry is past the 15 minutes is refused before anything is written."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    harness, sweeper = await role_conn(Role.TEST_HARNESS), await role_conn(Role.SWEEPER)
    run = await drafting_on(app_conn, api, worker, asset())
    try:
        result, digest = await frozen(app_conn, worker, run)
        try:
            await harness.execute("UPDATE app.test_clock SET clock_offset = interval '16 minutes'")
            await app_conn.execute("UPDATE app.memberships SET synced_at = app.current_time()")  # the sync's stamp
            assert await refusal(decide(api, result.proposal_id, digest)) == "EXPIRED"
            assert await state_of(app_conn, run) == ("AWAITING_APPROVAL", None)  # the 409 extends nothing
            assert await expiry.expire(sweeper, tenants=[ALPHA]) == [run]
            assert await state_of(app_conn, run) == ("BLOCKED_REVIEW", "expired")
            assert await expiry.expire(sweeper, tenants=[ALPHA]) == []  # nothing is due twice
            cur = await app_conn.execute(
                "SELECT count(*) AS n FROM app.events WHERE run_id = %s AND type = 'review.blocked'", (run,)
            )
            assert (await cur.fetchone())["n"] == 1
            assert await refusal(decide(api, result.proposal_id, digest)) == "EXPIRED"
        finally:
            await harness.execute("UPDATE app.test_clock SET clock_offset = interval '0'")
        other = await drafting_on(app_conn, api, worker, asset())
        try:
            far = (await persistence.current_time(app_conn)).replace(microsecond=0) + timedelta(minutes=20)
            draft, body = uuid4(), far_body(other, far)
            async with worker.transaction():
                await persistence.set_tenant(worker, ALPHA)
                await worker.execute(
                    "INSERT INTO app.drafts (id, tenant_id, run_id, draft_sha256, validated, kind)"
                    " VALUES (%s, %s, %s, %s, true, 'proposal')",
                    (draft, ALPHA, other, sha256_hex(body)),
                )
                refused = refusal(
                    persistence.freeze_proposal(
                        worker, run_id=other, draft_id=draft, payload_canonical=body, expires_at=far
                    )
                )
                assert await refused == "EXPIRY"
        finally:
            await purge_run(app_conn, other)
    finally:
        await purge_run(app_conn, run)


def far_body(run: UUID, expires: Any) -> bytes:
    """A revision-1 payload of `run` expiring at `expires` (the freeze refuses more than 15 minutes, ruling 5)."""
    return canonical_json(
        {
            "tenant_id": str(ALPHA),
            "run_id": str(run),
            "proposal_id": str(uuid4()),
            "revision": 1,
            "supersedes_run_id": None,
            "workflow_version": WORKFLOW,
            "expires_at": expires.isoformat().replace("+00:00", "Z"),
        }
    )


async def test_the_grant_re_checks_authority_sources_observation_and_binding(
    app_conn: persistence.Conn, role_conn: RoleConn, ingested: None
) -> None:
    """R045, R116, R100, DEV-010, DEV-020: each committed refusal moves the run to BLOCKED_REVIEW with its reason and
    grants nothing; the binding refusals (another run's proposal, an approval of other bytes) raise and commit
    nothing. Then a clean approval is granted once, and a revision after it is refused (R090)."""
    api, worker, mcp_exec = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.MCP_EXEC)
    pat = await member(app_conn, "reviewer")
    section = await permitted_section(app_conn)
    runs: list[UUID] = []

    async def approved(*, reviewer: UUID = SAM, snapshots: list[dict[str, str]] | None = None) -> tuple[UUID, UUID]:
        run = await drafting_on(app_conn, api, worker, asset())
        runs.append(run)
        result, digest = await frozen(app_conn, worker, run, snapshots=snapshots)
        await decide(api, result.proposal_id, digest, reviewer=reviewer)
        assert result.proposal_id is not None
        return run, result.proposal_id

    try:
        # R045 / DEV-010: the reviewer is deactivated by the sync after approving.
        run, proposal = await approved(reviewer=pat)
        await app_conn.execute("UPDATE app.memberships SET active = false WHERE subject = %s", (pat,))
        blocked = await grant(app_conn, mcp_exec, run, proposal)
        assert isinstance(blocked, persistence.Blocked) and blocked.reason.value == "authority_revoked"
        assert await state_of(app_conn, run) == ("BLOCKED_REVIEW", "authority_revoked")
        # DEV-020: the proposal froze a hash of the cited section that the corpus no longer has.
        stale = {**section, "content_sha256": "0" * 64}
        run, proposal = await approved(snapshots=[stale])
        blocked = await grant(app_conn, mcp_exec, run, proposal)
        assert isinstance(blocked, persistence.Blocked) and blocked.reason.value == "stale_evidence"
        # R116: the asset status was observed more than five minutes ago.
        run, proposal = await approved(snapshots=[section])
        await app_conn.execute(
            "UPDATE app.runs SET asset_observed_at = app.current_time() - interval '6 minutes' WHERE run_id = %s",
            (run,),
        )
        blocked = await grant(app_conn, mcp_exec, run, proposal)
        assert isinstance(blocked, persistence.Blocked) and blocked.reason.value == "stale_evidence"
        assert await state_of(app_conn, run) == ("BLOCKED_REVIEW", "stale_evidence")
        # The binding refusals: another run's proposal through this run's handle (R100), then an approval whose hash
        # is not the proposal's (staged by the superuser: record_decision never stores one). Neither commits.
        run, proposal = await approved(snapshots=[section])
        other, other_proposal = await approved(snapshots=[section])
        assert await refusal(grant(app_conn, mcp_exec, run, other_proposal)) == "PROPOSAL_NOT_IN_RUN"
        await app_conn.execute(
            "UPDATE app.decisions SET expected_payload_sha256 = %s WHERE proposal_id = %s", ("f" * 64, proposal)
        )
        assert await refusal(grant(app_conn, mcp_exec, run, proposal)) == "HASH_MISMATCH"
        assert await state_of(app_conn, run) == ("APPROVED", None)
        # A clean approval is granted, once per run; a revision after it is refused whatever its version (R090).
        granted = await grant(app_conn, mcp_exec, other, other_proposal)
        assert isinstance(granted, persistence.Grant) and granted.proposal_id == other_proposal
        version = (await persistence.run_row(app_conn, other))["state_version"]
        async with api.transaction():
            after = refusal(
                persistence.create_revision(
                    api, tenant_id=ALPHA, run_id=other, expected_version=version, author=ALEX, supersedes_run_id=None
                )
            )
            assert await after == "GRANT_EXISTS"
    finally:
        await forget(app_conn, runs, [pat])


async def test_the_asset_guard_blocks_a_second_action_unless_it_supersedes(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """AM-13, R125 (T21 half), DEV-025: on one asset and interval, a run whose action is unresolved blocks a second
    freeze (asset_action_unresolved); a disjoint interval does not; once the first incident is SUCCEEDED, the second
    is blocked (asset_incident_exists) until a revision names the first run as superseded."""
    api, worker, mcp_exec = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.MCP_EXEC)
    where = asset()
    runs: list[UUID] = []
    try:
        first = await drafting_on(app_conn, api, worker, where)
        runs.append(first)
        result, digest = await frozen(app_conn, worker, first)
        await decide(api, result.proposal_id, digest)
        granted = await grant(app_conn, mcp_exec, first, result.proposal_id)
        assert isinstance(granted, persistence.Grant)
        second = await drafting_on(app_conn, api, worker, where)
        runs.append(second)
        blocked, _ = await frozen(app_conn, worker, second)
        assert (blocked.state.value, blocked.reason and blocked.reason.value, blocked.proposal_id) == (
            "BLOCKED_REVIEW",
            "asset_action_unresolved",
            None,
        )
        cur = await app_conn.execute(
            "SELECT payload FROM app.events WHERE run_id = %s AND type = 'review.blocked'", (second,)
        )
        assert (await cur.fetchone())["payload"]["message"] == f"blocked by run {first}"  # ruling 10
        disjoint = await drafting_on(app_conn, api, worker, where, days_back=3)
        runs.append(disjoint)
        assert (await frozen(app_conn, worker, disjoint))[0].state.value == "AWAITING_APPROVAL"
        # The first incident commits, as mcp-write records it: SENT, then SUCCEEDED with the destination's receipt.
        handle = await handle_for(app_conn, first, "execute", expires_in=600)
        receipt = Receipt(receipt_id=uuid4(), incident_id="INC-T21-0001", committed_at=datetime.now(UTC))
        outcome = ActionOutcome(
            status=ToolOutcome.SUCCEEDED,
            action_id=granted.action_id,
            payload_sha256=granted.payload_sha256,
            receipt=receipt,
            tombstone=None,
            reason=None,
        )
        async with mcp_exec.transaction():
            await persistence.mark_sent(mcp_exec, handle=handle, azp=GRANT_AZP, action_id=granted.action_id)
        async with mcp_exec.transaction():
            await persistence.record_outcome(
                mcp_exec, handle=handle, azp=GRANT_AZP, action_id=granted.action_id, outcome=outcome
            )
        assert await state_of(app_conn, first) == ("SUCCEEDED", None)
        version = (await persistence.run_row(app_conn, second))["state_version"]
        async with api.transaction():
            await persistence.create_revision(
                api, tenant_id=ALPHA, run_id=second, expected_version=version, author=ALEX, supersedes_run_id=None
            )
        async with worker.transaction():
            await worker.execute(
                "SELECT app.transition_run(%s, 'QUEUED', 'RETRIEVING', NULL, %s, '{}')", (second, version + 1)
            )
            await worker.execute(
                "SELECT app.transition_run(%s, 'RETRIEVING', 'DRAFTING', NULL, %s, '{}')", (second, version + 2)
            )
        again, _ = await frozen(app_conn, worker, second, revision=2)
        assert (again.state.value, again.reason and again.reason.value) == ("BLOCKED_REVIEW", "asset_incident_exists")
        # R125: only a request that names the first run proceeds, and the payload carries the run's supersession.
        version = (await persistence.run_row(app_conn, second))["state_version"]
        async with api.transaction():
            await persistence.create_revision(
                api, tenant_id=ALPHA, run_id=second, expected_version=version, author=ALEX, supersedes_run_id=first
            )
        async with worker.transaction():
            await worker.execute(
                "SELECT app.transition_run(%s, 'QUEUED', 'RETRIEVING', NULL, %s, '{}')", (second, version + 1)
            )
            await worker.execute(
                "SELECT app.transition_run(%s, 'RETRIEVING', 'DRAFTING', NULL, %s, '{}')", (second, version + 2)
            )
        superseding, _ = await frozen(app_conn, worker, second, revision=3, supersedes=first)
        assert superseding.state.value == "AWAITING_APPROVAL"
    finally:
        await forget(app_conn, runs, [])


async def test_cancel_before_and_after_the_grant(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    """R046 (T21 half), DEV-014: before a grant the run's requester cancels at once (BLOCKED_REVIEW included); after
    one only the flag is set and the attempt's state reported, never an undo; a stranger is refused."""
    api, worker, mcp_exec = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.MCP_EXEC)
    runs: list[UUID] = []
    try:
        run = await drafting_on(app_conn, api, worker, asset())
        runs.append(run)

        async def cancel(target: UUID, actor: UUID, version: int) -> persistence.Cancelled:
            async with api.transaction():
                return await persistence.request_cancel(
                    api, tenant_id=ALPHA, run_id=target, expected_version=version, actor=actor
                )

        assert await refusal(cancel(run, uuid4(), 3)) == "NOT_CANCELLER"
        cancelled = await cancel(run, ALEX, 3)
        assert (cancelled.state.value, cancelled.grant_exists, cancelled.attempt_state) == ("CANCELLED", False, None)
        executing = await drafting_on(app_conn, api, worker, asset())
        runs.append(executing)
        result, digest = await frozen(app_conn, worker, executing)
        await decide(api, result.proposal_id, digest)
        assert isinstance(await grant(app_conn, mcp_exec, executing, result.proposal_id), persistence.Grant)
        version = (await persistence.run_row(app_conn, executing))["state_version"]
        after = await cancel(executing, SAM, version)  # any reviewer of the tenant may ask (ruling 12)
        assert (after.state.value, after.grant_exists, after.attempt_state and after.attempt_state.value) == (
            "EXECUTING",
            True,
            "INTENT",
        )
        row = await persistence.run_row(app_conn, executing)
        assert (row["state"], row["cancel_requested"]) == ("EXECUTING", True)
    finally:
        await forget(app_conn, runs, [])


def idem(route: str, subject: UUID, body: dict[str, Any], path: dict[str, str] | None = None) -> Idem:
    """A fresh idempotency scope for one DbStore mutation."""
    return Idem(Scope(ALPHA, subject, route, f"t21-{uuid4()}"), fingerprint(path or {}, body), 86400, uuid4())


async def test_a_manual_proposal_takes_the_same_review_and_feedback_changes_nothing_else(
    app_conn: persistence.Conn, role_conn: RoleConn, ingested: None
) -> None:
    """R057, R093, note 4, R113: a person's proposal for a run the model could not draft for is frozen through the
    freeze rules with `prompt_version` "manual" and a draft row of source `manual`; a section of another tenant is
    404 with nothing written; its author cannot approve it. Feedback writes one row and one `feedback.recorded`
    event with three keys and nothing else."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    store = DbStore(api)
    reviewer = await member(app_conn, "reviewer")  # a reviewer may author a manual proposal (SA:542)
    section = await permitted_section(app_conn)
    run = await drafting_on(app_conn, api, worker, asset())
    try:
        row = await persistence.run_row(app_conn, run)
        body = {
            "run_id": str(run),
            "asset_id": row["asset_id"],
            "start_at": row["start_at"].isoformat().replace("+00:00", "Z"),
            "end_at": row["end_at"].isoformat().replace("+00:00", "Z"),
            "title": "Manual incident",
            "summary": "Written by a person while the model was unavailable.",
            "evidence_refs": [section["evidence_id"]],
            "assumptions": [],
            "limitations": ["manual"],
        }
        foreign = {**body, "evidence_refs": ["BETA-ONLY:v1:nowhere"]}
        missing = await store.manual_once(
            idem=idem("POST /api/v1/manual-proposals", reviewer, foreign),
            tenant_id=ALPHA,
            author=reviewer,
            request=load(ManualProposalRequest, json.dumps(foreign)),
        )
        assert missing.status == 404
        cur = await app_conn.execute("SELECT count(*) AS n FROM app.drafts WHERE run_id = %s", (run,))
        assert (await cur.fetchone())["n"] == 0  # nothing written (note 4)
        made = await store.manual_once(
            idem=idem("POST /api/v1/manual-proposals", reviewer, body),
            tenant_id=ALPHA,
            author=reviewer,
            request=load(ManualProposalRequest, json.dumps(body)),
        )
        assert made.status == 201 and made.body["status"] == "AWAITING_APPROVAL", made
        cur = await app_conn.execute(
            "SELECT p.payload, p.payload_sha256, p.authored_by, d.source FROM app.proposals p"
            " JOIN app.drafts d ON d.id = p.draft_id WHERE p.proposal_id = %s",
            (UUID(made.body["proposal_id"]),),
        )
        frozen_row = await cur.fetchone()
        assert frozen_row["payload"]["prompt_version"] == "manual" and frozen_row["source"] == "manual"
        assert frozen_row["payload"]["source_snapshots"] == [section]
        assert frozen_row["authored_by"] == [ALEX, reviewer]  # the run's requester, then the person (ruling 4)
        digest = frozen_row["payload_sha256"]
        assert await refusal(decide(api, UUID(made.body["proposal_id"]), digest, reviewer=reviewer)) == "SELF_REVIEW"
        # Feedback (R113): only its row and its event change; the run, its proposal and its jobs stay as they were.
        before = await persistence.run_row(app_conn, run)
        cur = await app_conn.execute("SELECT count(*) AS n FROM app.jobs WHERE run_id = %s", (run,))
        jobs = (await cur.fetchone())["n"]
        note = {"subject_kind": "proposal", "subject_id": made.body["proposal_id"], "category": "unclear", "text": "?"}
        recorded = await store.feedback_once(
            idem=idem("POST /api/v1/runs/{run_id}/feedback", ALEX, note, {"run_id": str(run)}),
            tenant_id=ALPHA,
            run_id=run,
            author=ALEX,
            request=load(FeedbackRequest, json.dumps(note)),
        )
        assert recorded.status == 201
        cur = await app_conn.execute("SELECT category, text, author FROM app.feedback WHERE run_id = %s", (run,))
        assert [dict(r) for r in await cur.fetchall()] == [{"category": "unclear", "text": "?", "author": ALEX}]
        cur = await app_conn.execute(
            "SELECT payload FROM app.events WHERE run_id = %s AND type = 'feedback.recorded'", (run,)
        )
        assert [r["payload"] for r in await cur.fetchall()] == [
            {"subject_kind": "proposal", "subject_id": made.body["proposal_id"], "category": "unclear"}
        ]  # the text stays in the row (erratum 136)
        after = await persistence.run_row(app_conn, run)
        assert {k: after[k] for k in ("state", "state_version", "active_proposal_id")} == {
            k: before[k] for k in ("state", "state_version", "active_proposal_id")
        }
        cur = await app_conn.execute("SELECT count(*) AS n FROM app.jobs WHERE run_id = %s", (run,))
        assert (await cur.fetchone())["n"] == jobs
        with pytest.raises(psycopg.errors.InsufficientPrivilege):  # the api role may insert feedback, never edit it
            async with api.transaction():
                await persistence.set_tenant(api, ALPHA)
                await api.execute("UPDATE app.feedback SET reviewed = true WHERE run_id = %s", (run,))
    finally:
        await forget(app_conn, [run], [reviewer])


async def test_a_revision_into_an_occupied_slot_is_refused(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    """R120 (T21 half): a BLOCKED_REVIEW run freed its conversation's slot; once another run holds it, a revision of
    the blocked run is refused SLOT_OCCUPIED and the run stays as it was."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    runs: list[UUID] = []
    try:
        blocked = await drafting_on(app_conn, api, worker, asset())
        runs.append(blocked)
        result, digest = await frozen(app_conn, worker, blocked)
        await decide(api, result.proposal_id, digest)
        await app_conn.execute(
            "UPDATE app.runs SET asset_observed_at = app.current_time() - interval '6 minutes' WHERE run_id = %s",
            (blocked,),
        )
        mcp_exec = await role_conn(Role.MCP_EXEC)
        assert isinstance(await grant(app_conn, mcp_exec, blocked, result.proposal_id), persistence.Blocked)
        row = await persistence.run_row(app_conn, blocked)
        assert (row["state"], row["slot_held"]) == ("BLOCKED_REVIEW", False)
        cur = await app_conn.execute(
            "INSERT INTO app.messages (message_id, tenant_id, conversation_id, kind, text, author)"
            " VALUES (%s, %s, %s, 'investigate', 'x', %s) RETURNING message_id",
            (uuid4(), ALPHA, row["conversation_id"], ALEX),
        )
        message = (await cur.fetchone())["message_id"]
        async with api.transaction():
            cur = await api.execute(
                "SELECT * FROM app.create_run(%s, %s, %s, 'investigate', NULL)",
                (
                    ALPHA,
                    row["conversation_id"],
                    Jsonb(
                        {
                            "message_id": str(message),
                            "requester": str(ALEX),
                            "asset_id": asset(),
                            "start_at": row["start_at"].isoformat(),
                            "end_at": row["end_at"].isoformat(),
                        }
                    ),
                ),
            )
            runs.append((await cur.fetchone())["run_id"])
        async with api.transaction():
            occupied = refusal(
                persistence.create_revision(
                    api,
                    tenant_id=ALPHA,
                    run_id=blocked,
                    expected_version=row["state_version"],
                    author=ALEX,
                    supersedes_run_id=None,
                )
            )
            assert await occupied == "SLOT_OCCUPIED"
        assert await state_of(app_conn, blocked) == ("BLOCKED_REVIEW", "stale_evidence")
    finally:
        # The second run and a second message share the blocked run's conversation, so the whole conversation goes.
        for run in runs[:1]:
            cur = await app_conn.execute("SELECT conversation_id FROM app.runs WHERE run_id = %s", (run,))
            found = await cur.fetchone()
            if found is not None:
                await purge_conversation(app_conn, found["conversation_id"])


async def test_the_read_path_refuses_a_membership_the_sync_has_not_stamped(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """Ruling 14 (erratum 105): `asset_scope` and the search defer (MEMBERSHIP_STALE) when the run's requester row
    was last stamped more than 120 s ago, as the grant does; a stamped row reads again."""
    api, worker, mcp_read = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.MCP_READ)
    run = await drafting_on(app_conn, api, worker, asset())
    try:
        fence = await stage_lease(app_conn, run)
        raw = f"handle-{uuid4().hex}"
        cur = await app_conn.execute("SELECT id FROM app.jobs WHERE run_id = %s AND type = 'investigate'", (run,))
        job = (await cur.fetchone())["id"]
        await app_conn.execute(
            "INSERT INTO app.invocation_context (handle_sha256, run_id, job_id, server, azp, fence, expires_at)"
            " VALUES (%s, %s, %s, 'read', %s, %s, now() + interval '10 minutes')",
            (sha256_hex(raw.encode()), run, job, GRANT_AZP, fence),
        )
        await app_conn.execute(
            "UPDATE app.memberships SET synced_at = app.current_time() - interval '121 seconds'"
            " WHERE tenant_id = %s AND subject = %s",
            (ALPHA, ALEX),
        )
        with pytest.raises(persistence.Refused, match="MEMBERSHIP_STALE"):
            await persistence.asset_scope(mcp_read, handle=raw, azp=GRANT_AZP)
        with pytest.raises(persistence.Refused, match="MEMBERSHIP_STALE"):
            await persistence.search_procedures(
                mcp_read, handle=raw, azp=GRANT_AZP, query="turbine", asset_type=None, limit=8
            )
        await app_conn.execute("UPDATE app.memberships SET synced_at = app.current_time() WHERE subject = %s", (ALEX,))
        assert (await persistence.asset_scope(mcp_read, handle=raw, azp=GRANT_AZP)).run_id == run
    finally:
        await purge_run(app_conn, run)


async def test_the_round_trip_restores_0015(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    """Revision 0016 down and up: its functions, columns and the feedback table go, 0015's `record_decision` and its
    grant come back, and the head is identical afterwards (function text, owner, ACL)."""
    from scripts.skeleton import downgrade, migrate

    superuser = settings.superuser_postgres()
    head = await snapshot(app_conn)
    new = {"app.create_revision(", "app.request_cancel(", "app.create_manual_proposal(", "app._asset_guard("}
    assert all(any(s.startswith(n) for s in head) for n in new)
    try:
        downgrade("app", superuser, "0015_checkpoints")
        after = await snapshot(app_conn)
        assert not any(s.startswith(n) for s in after for n in new)
        assert "app.record_decision(uuid,uuid,uuid,text,text,text,text)" in after
        cur = await app_conn.execute(
            "SELECT to_regclass('app.feedback') IS NULL AS gone, NOT EXISTS (SELECT 1 FROM information_schema.columns"
            " WHERE table_schema = 'app' AND table_name = 'runs' AND column_name = 'authors') AS no_authors"
        )
        assert dict(await cur.fetchone()) == {"gone": True, "no_authors": True}
    finally:
        assert migrate(settings.Profile.TEST) == 0  # every later test needs the head
    assert await snapshot(app_conn) == head


async def snapshot(conn: persistence.Conn) -> dict[str, dict[str, Any]]:
    cur = await conn.execute(APP_FUNCTIONS)
    return {row["signature"]: {k: v for k, v in row.items() if k != "signature"} for row in await cur.fetchall()}
````

Edit 190 (`tests/e2e/test_roles_live.py`), replace:
````python
        " end_at, state, state_version, slot_held) VALUES (%s, %s, %s, %s, %s, 'investigate', 'A17',"
        " now() - interval '1 day', now(), 'QUEUED', 1, true)",
        (run, tenant, conv, msg, ALEX),
````
with:
````python
        " end_at, state, state_version, slot_held, authors) VALUES (%s, %s, %s, %s, %s, 'investigate', 'A17',"
        " now() - interval '1 day', now(), 'QUEUED', 1, true, ARRAY[%s::uuid])",  # T21: runs.authors (revision 0016)
        (run, tenant, conv, msg, ALEX, ALEX),
````

Edit 191 (`tests/e2e/test_run_manifest_live.py`), replace:
````python
    "INSERT INTO app.run_manifests (run_id, tenant_id, model_route, model_digest, prompt_version, corpus_version,"
    " retrieval_mode) VALUES (%s, %s, %s, %s, 'incident-draft-v2', 'corpus-1', 'lexical')"
````
with:
````python
    "INSERT INTO app.run_manifests (run_id, revision, tenant_id, model_route, model_digest, prompt_version,"
    " corpus_version, retrieval_mode) VALUES (%s, 1, %s, %s, %s, 'incident-draft-v2', 'corpus-1', 'lexical')"
````

Edit 192 (`tests/e2e/test_run_manifest_live.py`), replace:
````python
            await persistence.insert_run_manifest(worker, tenant_id=ALPHA, manifest=manifest)
        with pytest.raises(psycopg.errors.UniqueViolation):  # one manifest per run
            async with worker.transaction():
                await persistence.set_tenant(worker, ALPHA)
                await persistence.insert_run_manifest(worker, tenant_id=ALPHA, manifest=manifest)
        for statement in ("UPDATE app.run_manifests SET model_digest = NULL", "DELETE FROM app.run_manifests"):
            assert await refused(worker, statement, ()) == "42501", statement  # immutable
        async with api.transaction():
            await persistence.set_tenant(api, ALPHA)
            cur = await api.execute("SELECT model_route, model_digest FROM app.run_manifests WHERE run_id = %s", (run,))
            assert [dict(r) for r in await cur.fetchall()] == [{"model_route": "qwen3:8b", "model_digest": DIGEST}]
````
with:
````python
            await persistence.insert_run_manifest(worker, tenant_id=ALPHA, manifest=manifest, revision=1)
        with pytest.raises(psycopg.errors.UniqueViolation):  # one manifest per revision (T21; erratum 125)
            async with worker.transaction():
                await persistence.set_tenant(worker, ALPHA)
                await persistence.insert_run_manifest(worker, tenant_id=ALPHA, manifest=manifest, revision=1)
        async with worker.transaction():  # T21 (Plan R ruling 1): a revision records its own
            await persistence.set_tenant(worker, ALPHA)
            await persistence.insert_run_manifest(worker, tenant_id=ALPHA, manifest=manifest, revision=2)
        for statement in ("UPDATE app.run_manifests SET model_digest = NULL", "DELETE FROM app.run_manifests"):
            assert await refused(worker, statement, ()) == "42501", statement  # immutable
        async with api.transaction():
            await persistence.set_tenant(api, ALPHA)
            cur = await api.execute("SELECT model_route, model_digest FROM app.run_manifests WHERE run_id = %s", (run,))
            assert [dict(r) for r in await cur.fetchall()] == [{"model_route": "qwen3:8b", "model_digest": DIGEST}] * 2
````

Edit 193 (`tests/e2e/test_worker_live.py`), replace:
````python
RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
````
with:
````python
RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
# T21: the R105 test, which runs before this module, leaves a SUCCEEDED run on A17 for the last 24 hours, and the
# asset guard (SA:189) blocks a new action there unless it supersedes that run, so these runs use another asset.
ASSET = "A19"
````

Edit 194 (`tests/e2e/test_worker_live.py`), replace:
````python

    async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Resolve the handle for the tool's server, then return the scripted envelope."""
        self.calls.append((url, tool, arguments))
        reads = {"get_asset_status": STATUS, "get_recent_alerts": ALERTS, "search_procedures": SEARCH}
````
with:
````python
        # The read script; `granting_reads` swaps in one the grant accepts (T21).
        self.reads = {"get_asset_status": STATUS, "get_recent_alerts": ALERTS, "search_procedures": SEARCH}

    async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Resolve the handle for the tool's server, then return the scripted envelope."""
        self.calls.append((url, tool, arguments))
        reads = self.reads
````

Edit 195 (`tests/e2e/test_worker_live.py`), replace:
````python
@pytest_asyncio.fixture
````
with:
````python
async def granting_reads(app_conn: persistence.Conn, mcp: ScriptedMcp, asset: str = ASSET) -> None:
    """T21: a read script the grant accepts, for the tests whose write server really grants. The grant re-checks the
    asset observation's age (R116) and every cited section against the tenant's corpus (BS:425), so the status is
    stamped at the database clock and the search cites one permitted section of ALPHA's ingested corpus."""
    cur = await app_conn.execute(
        "SELECT c.document_id, c.version, c.section, c.evidence_id, c.content_sha256, app.current_time() AS at"
        " FROM app._cited_permitted(%s, ARRAY(SELECT evidence_id FROM app.chunks WHERE tenant_id = %s)) p"
        " JOIN app.chunks c ON c.tenant_id = %s AND c.evidence_id = p.evidence_id ORDER BY c.evidence_id LIMIT 1",
        (ALPHA, ALPHA, ALPHA),
    )
    row = await cur.fetchone()
    assert row is not None, "ALPHA has no permitted section"
    at = row["at"].isoformat().replace("+00:00", "Z")
    status = {**STATUS, "observed_at": at, "data": {**STATUS["data"], "asset_id": asset, "observed_at": at}}
    hit = {k: row[k] for k in ("evidence_id", "document_id", "version", "section", "content_sha256")}
    hit |= {"excerpt": "text", "effective_from": "2026-10-01T00:00:00Z", "retrieved_at": at}
    search = {"status": "ok", "data": {**SEARCH["data"], "results": [hit]}}
    mcp.reads = {**mcp.reads, "get_asset_status": status, "search_procedures": search}


@pytest_asyncio.fixture
````

Edit 196 (`tests/e2e/test_worker_live.py`), replace:
````python
            expected_payload_sha256=proposal["payload_sha256"],
````
with:
````python
            expected_revision=proposal["revision"],
            expected_payload_sha256=proposal["payload_sha256"],
````

Edit 197 (`tests/e2e/test_worker_live.py`), replace:
````python
        _, _, run = await new_run(app_conn, ALPHA, api=api)
        await handlers.handle(deps, *await own_job(app_conn, deps.conn, run, "investigate"))
        row = await persistence.run_row(app_conn, run)
````
with:
````python
        _, _, run = await new_run(app_conn, ALPHA, api=api, asset_id=ASSET)
        await handlers.handle(deps, *await own_job(app_conn, deps.conn, run, "investigate"))
        row = await persistence.run_row(app_conn, run)
````

Edit 198 (`tests/e2e/test_worker_live.py`), replace:
````python
            "create_incident",
        ]
        assert mcp.calls[3][2] == {"proposal_id": str(proposal["proposal_id"])}
````
with:
````python
            "get_asset_status",  # T21: read again before the grant, on the execute job's read handle (erratum 137)
            "create_incident",
        ]
        assert mcp.calls[4][2] == {"proposal_id": str(proposal["proposal_id"])}
````

Edit 199 (`tests/e2e/test_worker_live.py`), replace:
````python
        _, _, run = await new_run(app_conn, ALPHA, api=api)
        job, lease = await own_job(app_conn, deps.conn, run, "investigate")
````
with:
````python
        _, _, run = await new_run(app_conn, ALPHA, api=api, asset_id=ASSET)
        job, lease = await own_job(app_conn, deps.conn, run, "investigate")
````

Edit 200 (`tests/e2e/test_worker_live.py`), replace:
````python
    app_conn: persistence.Conn, role_conn: RoleConn, worker_deps: WorkerDeps
) -> None:
    api = await role_conn(Role.API)
    deps, mcp = await worker_deps(WriteDownMcp, FakeDraftGenerator())
    run = None
    try:
        _, _, run = await new_run(app_conn, ALPHA, api=api)
````
with:
````python
    app_conn: persistence.Conn, role_conn: RoleConn, worker_deps: WorkerDeps, ingested: None
) -> None:
    api = await role_conn(Role.API)
    deps, mcp = await worker_deps(WriteDownMcp, FakeDraftGenerator())
    await granting_reads(app_conn, mcp)
    run = None
    try:
        _, _, run = await new_run(app_conn, ALPHA, api=api, asset_id=ASSET)
````

Edit 201 (`tests/e2e/test_worker_live.py`), replace:
````python
        deps.mcp = grant_mcp
        await handlers.handle(deps, job, lease)
        assert (await persistence.run_row(app_conn, run))["state"] == "EXECUTING"
        assert [c[1] for c in grant_mcp.calls] == ["create_incident"]
        # A re-queued job of an EXECUTING run must be dispatched again (same action id), not finished unsent.
        await app_conn.execute("UPDATE app.jobs SET available_at = now() WHERE id = %s", (job["id"],))
        job, lease = await own_job(app_conn, deps.conn, run, "execute")
        await handlers.handle(deps, job, lease)
        assert [c[1] for c in grant_mcp.calls] == ["create_incident", "create_incident"]
````
with:
````python
        grant_mcp.reads = mcp.reads
        deps.mcp = grant_mcp
        await handlers.handle(deps, job, lease)
        assert (await persistence.run_row(app_conn, run))["state"] == "EXECUTING"
        # T21 (erratum 137): an APPROVED run's asset status is read again before the grant; an EXECUTING one is not.
        assert [c[1] for c in grant_mcp.calls] == ["get_asset_status", "create_incident"]
        # A re-queued job of an EXECUTING run must be dispatched again (same action id), not finished unsent.
        await app_conn.execute("UPDATE app.jobs SET available_at = now() WHERE id = %s", (job["id"],))
        job, lease = await own_job(app_conn, deps.conn, run, "execute")
        await handlers.handle(deps, job, lease)
        assert [c[1] for c in grant_mcp.calls] == ["get_asset_status", "create_incident", "create_incident"]
````

Edit 202 (`tests/e2e/test_worker_live.py`), replace:
````python
    app_conn: persistence.Conn, role_conn: RoleConn, worker_deps: WorkerDeps
) -> None:
    api = await role_conn(Role.API)
    deps, _ = await worker_deps(UnknownMcp, FakeDraftGenerator())
    run = None
    try:
        _, _, run = await new_run(app_conn, ALPHA, api=api)
````
with:
````python
    app_conn: persistence.Conn, role_conn: RoleConn, worker_deps: WorkerDeps, ingested: None
) -> None:
    api = await role_conn(Role.API)
    deps, mcp = await worker_deps(UnknownMcp, FakeDraftGenerator())
    await granting_reads(app_conn, mcp)
    run = None
    try:
        _, _, run = await new_run(app_conn, ALPHA, api=api, asset_id=ASSET)
````

Gates: dev `CHECK: GREEN`, `1791 passed, 237 skipped` (the live modules skip); `verify_handoff.py` exit 0.

- [ ] **Step 2: The live gate**

With the dev stack up, local Ollama answering and every skeleton process down, run `PYTHONUTF8=1 uv run python
scripts/check.py --profile test < /dev/null` → `CHECK: GREEN` with `2007 passed, 21 skipped`. It rewrites
`reports/auth/t11-sessions-revocation.txt` with the new line `grant after the disable: BLOCKED_REVIEW
(authority_revoked), grants 0`; keep that report and `git checkout -- reports` for every other. If a live test
fails, stop and report it with its output (NEEDS_CONTEXT): the expected behaviour is in the test's docstring and
Review Focus 1, and a fix is a review decision, not an improvisation.

```bash
git add tests/e2e reports/auth/t11-sessions-revocation.txt
git commit -m "test: the review rules, R023 and R086's grant half live (T21)"
```

---
### Task 7: Close-out — records, requirements, errata 131-145, state, history, final gates

**Files:**
- Modify: `handoff/tasks.json`, `handoff/acceptance-matrix.json`, `handoff/BUILD_BACKLOG.md`, `README.md`,
  `SESSION_STATE.md`, `STATUS.md`, `docs/ARCHITECTURE.md`, `docs/PROJECT_HISTORY.md`

**Requirements:** ruling 20; the T21 record. This task writes no behaviour.

Throughout, `<base>..<last>` is the git range of this plan's execution on `plan-r` (`<base>` the `BASE` of Task
1 Step 1b, excluded; `<last>` the newest commit before this task's own). `<date>` is `date -u +%F`. `<dev>` and
`<live>` are the final gates' pytest lines. Step 4 replaces every placeholder.

- [ ] **Step 1: Handoff records**

Save this outside the repository as `t21_records.py` (in the implementer's scratchpad) and run `BASE=<hash> uv
run python -I <path>/t21_records.py < /dev/null` from the repository root. It stops if a record is not in the
state this plan found it.

````python
"""Plan R close-out: T21's handoff records (tasks.json, the acceptance matrix, BUILD_BACKLOG.md).

Run from the repository root as `BASE=<hash> uv run python -I <path>/t21_records.py < /dev/null`. It stops if any
record is not in the state Plan R found it. M08 stays PLANNED: T22 is its other task.
"""

import json
import os
import subprocess
from pathlib import Path

base = os.environ["BASE"]
last = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True).stdout
subprocess.run(["git", "merge-base", "--is-ancestor", base, "HEAD"], check=True)  # the base is this branch's own
span = f"{base}..{last.strip()}"
note = (
    f"Plan R (branch plan-r): done in {span} (the debt list, then four building tasks and the live gate; the close-out "
    "is the next commit; plan docs/superpowers/plans/2026-10-25-first-slice-r-decisions-revisions-grant.md). Shipped: "
    "revision 0016 (runs.authors, runs.asset_observed_at, runs.workflow_version, drafts.source, run_manifests keyed "
    "(run_id, revision), the feedback table with RLS; the asset guard _asset_guard under a per-(tenant, asset) "
    "advisory lock taken first, called by freeze_proposal, create_manual_proposal and grant_execution; new definers "
    "create_revision, request_cancel, expire_proposal, prepare_manual_proposal, create_manual_proposal and "
    "search_procedures_api; record_decision with expected_revision and its own codes ALREADY_DECIDED, STALE_REVISION, "
    "STALE_HASH and EXPIRED; grant_execution's committed refusals expired, authority_revoked, stale_evidence, "
    "asset_action_unresolved and asset_incident_exists returned as a verdict with BLOCKED_REVIEW committed; the read "
    "path's MEMBERSHIP_STALE); the routes POST /runs/{id}/revisions, /runs/{id}/cancel, /runs/{id}/feedback, "
    "/manual-proposals and /search, and the approval card on GET /proposals/{id}; a revision re-enters as a new graph "
    "thread run_id:N with its own investigate job and manifest; the worker's manual path (DRAFTING, no checkpoint) "
    "when the model cannot draft; the asset status read again before the grant; the sweeper's expire_proposals; "
    "mcp-write advertising the committed result schema and the worker checking its listing and results. Evidence: "
    "tests/plan_r/ (unit), tests/e2e/test_review_live.py, test_r023_wakeup_live.py and the grant half of R086 in "
    "test_auth_live.py (live). Deferred: the revision text parser -> T34; the after-grant cancel, R125's late half and "
    "a deadline for a run waiting for a manual proposal -> T22; the card's rendering -> T26. Errata 131-145 are "
    "proposed in SESSION_STATE.md."
)
tasks_path = Path("handoff/tasks.json")
tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
t21 = next(t for t in tasks["tasks"] if t["id"] == "T21")
m08 = next(m for m in tasks["milestones"] if m["id"] == "M08")
assert t21["status"] == "PLANNED" and len(t21["review_notes"]) == 6 and tasks["current_milestone"] == "M08"
assert m08["status"] == "PLANNED"
t21["status"] = "DONE"
t21["review_notes"].append(note)
tasks_path.write_text(json.dumps(tasks, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

LIVE = "tests/e2e/test_review_live.py"
MIGRATION = "migrations/app/versions/0016_review_and_grant.py"
API = ["api/src/ops_api/app.py", "api/src/ops_api/store.py", "tests/plan_r/test_api_review.py"]
ROWS = {
    "R023": (
        [
            "worker/src/ops_worker/handlers.py",
            "tests/plan_r/test_worker_review.py",
            "tests/e2e/test_r023_wakeup_live.py",
        ],
        "Plan R (T21): live, the worker dies after the resume's checkpoint store and before the execute job's final "
        "unit; the sweeper's reclaim hands the job back, the next worker carries on from the stored step (its one "
        "resume write is the accepted approval.recorded id) and grants exactly the decided proposal. The other crash "
        "points are unit tests on the fakes; a killed process is T30's.",
    ),
    "R043": (
        [MIGRATION, *API, LIVE],
        "Plan R (T21): record_decision refuses SELF_REVIEW for the requester and every content author whatever else "
        "is right (403, never recorded); one identity with both scopes is refused live and another reviewer succeeds "
        "(DEV-006).",
    ),
    "R044": (
        [MIGRATION, *API, LIVE],
        "Plan R (T21): the decision names its revision and hash; each is checked under the run's lock with its own "
        "409 (STALE_REVISION, STALE_HASH, ALREADY_DECIDED, EXPIRED); a revision clears the active proposal, so an old "
        "decision authorizes nothing (DEV-008, DEV-009).",
    ),
    "R045": (
        [MIGRATION, "mcp-write/src/ops_mcp_write/execution.py", LIVE, "tests/e2e/test_auth_live.py"],
        "Plan R (T21): grant_execution re-reads the requester's and the reviewer's memberships and every cited source "
        "at the frozen version and hash; a revoked member or a stale source commits BLOCKED_REVIEW and grants nothing "
        "(DEV-010, DEV-020); live, also through the skeleton after a Keycloak disable (R086's grant half).",
    ),
    "R046": (
        [MIGRATION, *API, LIVE],
        "Plan R (T21 half): request_cancel cancels any pre-grant state, BLOCKED_REVIEW included (DEV-014); after the "
        "grant it sets cancel_requested and reports the attempt's state, never an undo. The abort path and the "
        "after-grant outcome evidence are T22's.",
    ),
    "R057": (
        [MIGRATION, *API, "worker/src/ops_worker/graph/nodes.py", LIVE],
        "Plan R (T21): when the model cannot draft, the run waits in DRAFTING for a person; POST /manual-proposals "
        "freezes the person's proposal through the freeze rules and the asset guard (prompt_version manual, a drafts "
        "row of source manual), and it meets the same independent review; POST /search is the lexical baseline; a "
        "section of another tenant is 404 with nothing written.",
    ),
    "R090": (
        [MIGRATION, LIVE],
        "Plan R (T21): one grant per run (UNIQUE run_id; a replay finds the grant it has, another proposal is "
        "OTHER_PROPOSAL); create_revision refuses GRANT_EXISTS once a grant exists, whatever the version.",
    ),
    "R092": (
        [MIGRATION, "sweeper/src/ops_sweeper/expiry.py", LIVE],
        "Plan R (T21): live on the database clock moved 16 minutes, the decision is refused EXPIRED and commits "
        "nothing, and the sweeper's expire routine moves the run to BLOCKED_REVIEW(expired) once with no worker and no "
        "reviewer; the API's decision unit and the grant apply the same rule lazily.",
    ),
    "R093": (
        [MIGRATION, *API, LIVE],
        "Plan R (T21): runs.authors collects the requester, every reviser and every manual author (at most eight); the "
        "frozen proposal's authored_by is that set, and none of them may approve it, live for a reviser and a manual "
        "author.",
    ),
    "R100": (
        [MIGRATION, LIVE],
        "Plan R (T21): a write handle of run X with a proposal of run Y is refused PROPOSAL_NOT_IN_RUN and commits "
        "nothing; an approval whose hash is not the proposal's is HASH_MISMATCH, also uncommitted.",
    ),
    "R113": (
        [MIGRATION, *API, LIVE],
        "Plan R (T21): POST /runs/{id}/feedback stores the classified row and emits feedback.recorded with three keys "
        "(the text stays in the row); live, the run, its proposal and its jobs are unchanged and the api role cannot "
        "update a feedback row.",
    ),
    "R116": (
        [MIGRATION, "worker/src/ops_worker/graph/nodes.py", LIVE],
        "Plan R (T21): runs.asset_observed_at is written by retrieval and refreshed by the execute job's status read "
        "just before the grant; an observation older than five minutes commits BLOCKED_REVIEW(stale_evidence).",
    ),
    "R120": (
        [MIGRATION, LIVE],
        "Plan R (T21 half): a revision from BLOCKED_REVIEW checks the conversation's slot under the run's lock and the "
        "unique index is the backstop; live, another active run in the conversation makes it 409 SLOT_OCCUPIED.",
    ),
    "R125": (
        [MIGRATION, LIVE],
        "Plan R (T21 half): on one asset and interval an unresolved action blocks a second freeze "
        "(asset_action_unresolved) and a SUCCEEDED incident blocks it (asset_incident_exists) until a revision names "
        "that run in supersedes_run_id, which create_revision accepts only for a run of the same tenant and asset. The "
        "late and recovered outcomes are T22's.",
    ),
}
matrix_path = Path("handoff/acceptance-matrix.json")
matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
by_id = {r["id"]: r for r in matrix["requirements"]}
for rid, (paths, row_note) in ROWS.items():
    row = by_id[rid]
    assert row["implementation_status"] == "NOT_IMPLEMENTED_OR_NOT_TARGET_VERIFIED"
    assert row["evidence_status"] == "NOT_RUN"
    row["implementation_status"] = "IMPLEMENTED_LOCALLY_VERIFIED"
    row["evidence_status"] = "RECORDED_LOCALLY_LIVE"
    row["evidence_paths"] = paths
    row["note"] = row_note
r086 = by_id["R086"]
assert r086["note"].endswith("lands with T21 (T11 review note 1)")
r086["note"] += (
    ". Plan R (T21): the grant half is live in test_disabled_user_is_refused_and_synced_within_60s: an execute job of "
    "a run sam approved while enabled, let go after the sync deactivated sam, meets a real grant_execution through the "
    "skeleton, which commits BLOCKED_REVIEW(authority_revoked) and no grant."
)
matrix_path.write_text(json.dumps(matrix, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

backlog_path = Path("handoff/BUILD_BACKLOG.md")
backlog = backlog_path.read_text(encoding="utf-8")
open_line = "- [ ] **T21 Proposals, decisions, manual proposals, feedback and final grant**"
assert backlog.count(open_line) == 1
backlog = backlog.replace(open_line, "- [x] **T21 Proposals, decisions, manual proposals, feedback and final grant**")
anchor = (
    "  - *Review note:* Asset guard per AM-13 (1.3.3): refuse on any unresolved action, and on any committed incident "
    "regardless of timing unless supersedes_run_id names it; approval card shows the superseded incident.\n"
)
assert backlog.count(anchor) == 1
backlog = backlog.replace(anchor, anchor + f"  - *Review note:* {note}\n")
backlog_path.write_text(backlog, encoding="utf-8", newline="\n")
print(f"T21 DONE; M08 PLANNED; rows {', '.join([*ROWS, 'R086'])}; span {span}")
````

Expected: `T21 DONE; M08 PLANNED; rows R023, R043, R044, R045, R046, R057, R090, R092, R093, R100, R113, R116,
R120, R125, R086; span <base>..<last>`.

- [ ] **Step 2: State, status, the architecture page and the history**

Edit 203 (`README.md`), replace:
````markdown
| **MCP servers** | `mcp-read` (asset status, alerts, procedure search) and `mcp-write` (guarded incident write and recovery), disjoint functions, disjoint handles | R025–R031, R131 |
````
with:
````markdown
| **Independent approval** | A decision bound to one frozen revision and hash by a reviewer who wrote none of it; a database gate that re-checks authority, sources, the asset observation, expiry and the asset guard before any write | R043, R044, R045, R093, R116, R125 |
| **MCP servers** | `mcp-read` (asset status, alerts, procedure search) and `mcp-write` (guarded incident write and recovery), disjoint functions, disjoint handles | R025–R031, R131 |
````

Edit 204 (`SESSION_STATE.md`), replace:
````markdown
**Current milestone:** M08 (independent review, grant, execution and recovery; T21 is next. M07 closed with T20 in Plan Q, after T19 in Plan P. M06 closed with T18 in Plan N; its T41, the owner's holdout labels, is optional since erratum 114. Every task of M00 to M05 is DONE or DONE_PENDING_OWNER, and the owner steps of M00 and M01 are listed below)
**Next task:** T21 (per-revision proposals, the decision rules and the manual path). Plan Q (T20) is executed on
````
with:
````markdown
**Current milestone:** M08 (independent review, grant, execution and recovery; T21 is DONE in Plan R and T22 is next. M07 closed with T20 in Plan Q, after T19 in Plan P. M06 closed with T18 in Plan N; its T41, the owner's holdout labels, is optional since erratum 114. Every task of M00 to M05 is DONE or DONE_PENDING_OWNER, and the owner steps of M00 and M01 are listed below)
**Next task:** T22 (the attempt protocol, recovery, abort and escalation). Plan R (T21) is executed on branch `plan-r`
(`<base>..<last>` holds the debt list, the four building tasks and the live gate; the close-out is the commit after
`<last>`). T21 is DONE: revisions, decisions, expiry, cancel, manual proposals, feedback and the final grant's
re-checks with the asset guard (R023, R043, R044, R045, R046's and R120's and R125's T21 halves, R057, R090, R092, R093,
R100, R113 and R116 live; R086's grant half live); errata 131-145 are proposed (see "Plan R executed"; the next free
erratum number is 146). Owner inputs added by Plan R: decide errata 131-145; migrate the dev database to 0016 (the api,
the worker, both MCP servers and the sweeper refuse to start without it). Plan Q (T20) is executed on
````

Edit 205 (`SESSION_STATE.md`), replace:
````markdown
## Walking-skeleton debt list (T08; committed before coding) [R6-B7]
````
with:
````markdown
## Plan R executed (<date>, branch `plan-r`)

- T21 = `<base>..<last>` (the debt list first, then the four building tasks and the live gate; the close-out is the
  commit after `<last>`). The plan (`docs/superpowers/plans/2026-10-25-first-slice-r-decisions-revisions-grant.md`)
  holds the 20 rulings of the controller's brief as implemented, with its departures named at its top; the input is
  `docs/superpowers/research/2026-10-25-plan-r-inputs.md`. Evidence: `migrations/app/versions/0016_review_and_grant.py`,
  `api/src/ops_api/store.py` and `app.py` (the routes), `worker/src/ops_worker/graph/nodes.py` and `handlers.py`,
  `sweeper/src/ops_sweeper/expiry.py`, `mcp-write/src/ops_mcp_write/`, `tests/plan_r/` (unit),
  `tests/e2e/test_review_live.py`, `tests/e2e/test_r023_wakeup_live.py` and the grant half of R086 in
  `tests/e2e/test_auth_live.py` (live).
- Gates: `PYTHONUTF8=1 uv run python scripts/check.py` `CHECK: GREEN`, pytest `<dev>`; `PYTHONUTF8=1 uv run python
  scripts/check.py --profile test` `CHECK: GREEN`, pytest `<live>`; `verify_handoff.py` exit 0.
- Erratum 125 closes: a revision records its own manifest (`run_manifests` keyed `(run_id, revision)`); a clarified run
  keeps its one manifest per revision. Erratum 63 resolves as Plan R ruling 11 provisionally decides it: a refused
  grant commits BLOCKED_REVIEW, the worker ends the graph run, and the `("APPROVED", "execute")` wake-up pair re-arms
  only lost wake-ups and `GRANT_DEFERRED`. Erratum 105 is decided provisionally (ruling 14): `asset_scope` and
  `search_procedures_scoped` refuse `MEMBERSHIP_STALE` under the grant's 120 s bound.
- **Proposed errata (the owner decides; the spec text stays authoritative until then).** Numbered on from Plan Q's:
  131. SA:454 (`record_decision(proposal_id, reviewer, expected_hash, decision)`): it also takes the revision the
       reviewer saw, and every rule is checked under `runs FOR UPDATE` with its own 409 code (ALREADY_DECIDED,
       STALE_REVISION, STALE_HASH, EXPIRED); SELF_REVIEW and NOT_REVIEWER stay the API's unrecorded 403.
  132. SA:456 (`authored_by=[author]`): a proposal's `authored_by` is the run's content authors, `runs.authors` (the
       requester, every reviser and every manual author, at most eight; a ninth is 409 AUTHOR_LIMIT), as SA:453 and
       SA:539 require.
  133. BS:281 (`POST /api/v1/manual-proposals`): the body names the run the proposal is for (`run_id`); the asset and
       the interval must be that run's.
  134. AM-10 and DEV-025 (`FAILED_WITH_MANUAL_PATH`): when the model is unavailable or its draft stays invalid after
       the repair, the run stays DRAFTING with no stored checkpoint and no lease, with a templated
       `explanation.ready`; that is the state a manual proposal waits for, and the sweeper does not re-arm it.
  135. BS:280 (`POST /api/v1/search`): a bounded lexical search over the tenant's permitted sections (query at most 500
       characters, at most 10 results) through the api-callable `search_procedures_api`; no vector mode in v1.
  136. The event schema: `feedback.recorded` carries `subject_kind`, `subject_id` and `category` only; the text stays
       in the `feedback` row.
  137. SA:343/344: the execute job's read handle may call `get_asset_status`, so the asset status is read again just
       before the grant and `runs.asset_observed_at` is fresh for R116 after a normal approval wait.
  138. Erratum 41 widened: `create_run` and `create_revision` accept a `supersedes_run_id` that names a run of the same
       tenant and asset in any conversation (SA:286, SA:288), never the run itself; otherwise 404.
  139. Contract erratum 5 adopted: `request_cancel` cancels any pre-grant non-terminal state, BLOCKED_REVIEW included.
  140. SA:455 (revision numbers): a run's revision is one more than its `proposal.revised` events, so a revision that
       never freezes still uses its number and a run's frozen revisions can skip one.
  141. SA:456 (`create_manual_proposal`): a manual proposal takes two api-callable definers in one unit:
       `prepare_manual_proposal` returns the run's facts (revision, workflow version, supersession, asset, interval,
       an expiry on the application clock and the cited sections' snapshots) under the asset lock and the run's
       lock, the API builds and canonicalises the payload with the one canonicaliser, and `create_manual_proposal`
       re-checks it and freezes it with a `drafts` row of `source = 'manual'` (a new column, `'model'` by default).
  142. AM-16's graph table gains a `manual` draft kind routed to `publish` (no new route): the worker's manual path
       ends the graph run there.
  143. SA:189 and the published lock order: a worker unit that freezes takes the asset lock before its lease fence
       (`advisory:asset` before `run_lease`); the definer takes it again, re-entrantly.
  144. SA:455, SA:456 and SA:458 name run-only signatures: `create_revision`, `request_cancel`,
       `prepare_manual_proposal` and `create_manual_proposal` also take the tenant and the acting subject, which the
       API has authenticated (the identity anchor, as for `record_decision`).
  145. AM-20.7's startup checks extend to the sweeper: it refuses to start without `expire_proposal` (revision 0016),
       as the api, the worker and both MCP servers refuse without their functions.
- Limits: R023's live crash point is one (after the resume's checkpoint store); a killed process is T30's. R046's and
  R125's after-grant halves are T22's.

## Walking-skeleton debt list (T08; committed before coding) [R6-B7]
````

Edit 206 (`SESSION_STATE.md`), replace:
````markdown
  115-121 (see "Plan P executed") and 122-130 (see "Plan Q executed").
- Migrate the dev database to revision 0015 (`uv run python scripts/skeleton.py migrate`): the worker refuses to start
  on 0013, which lacks `app.run_manifests` and `checkpoints.checkpoints`. To run the worker on the real model, set
````
with:
````markdown
  115-121 (see "Plan P executed"), 122-130 (see "Plan Q executed") and 131-145 (see "Plan R executed").
- Migrate the dev database to revision 0016 (`uv run python scripts/skeleton.py migrate`): the worker refuses to start
  on 0013, which lacks `app.run_manifests` and `checkpoints.checkpoints`, and every service refuses to start without
  0016's functions. To run the worker on the real model, set
````

Edit 207 (`STATUS.md`), replace:
````markdown
- Next: T21.
````
with:
````markdown
- Next: T21.

## Update — Plan R executed (<date>, branch `plan-r`)

- Plan R (T21: per-revision proposals, decisions, manual proposals, feedback and the final grant) executed on branch
  `plan-r` (`<base>..<last>`); the plan is
  `docs/superpowers/plans/2026-10-25-first-slice-r-decisions-revisions-grant.md`. T21 is DONE; M08 stays open for T22.
- `PYTHONUTF8=1 uv run python scripts/check.py` is `CHECK: GREEN`: pytest `<dev>`. `PYTHONUTF8=1 uv run python
  scripts/check.py --profile test` is `CHECK: GREEN`: pytest `<live>`. `verify_handoff.py` exits 0.
- **Evidenced** (`IMPLEMENTED_LOCALLY_VERIFIED`, `RECORDED_LOCALLY_LIVE`): R023 (a lost execute wake-up resumes the
  accepted event), R043 and R093 (no author approves), R044 (revision, hash and expiry bind the decision), R045 and R116
  (the grant re-checks authority, sources and the asset observation), R046 (T21 half: cancel before the grant), R057
  (the manual path), R090 (one grant; no revision after it), R092 (expiry without a worker), R100 (a handle cannot act
  on another run's proposal), R113 (feedback changes nothing else), R120 (T21 half: SLOT_OCCUPIED), R125 (T21 half:
  the asset guard and explicit supersession); R086's grant half (owner T11).
- Built: revision 0016; the routes for revisions, cancel, manual proposals, feedback and search; the approval card;
  revisions as new graph threads; the worker's manual path; the asset status read again before the grant; the
  sweeper's proposal expiry; mcp-write's committed result schema checked by the worker. The dev database is still at
  0013; every service now needs 0016 (`skeleton.py migrate`, an owner step).
- Deferred, each with its owner in `SESSION_STATE.md`: the revision text -> T34; the after-grant cancel, R125's late
  half and a deadline for a run waiting for a person -> T22; the card's rendering -> T26. Fifteen errata (131-145).
- Next: T22.
````

Edit 208 (`docs/ARCHITECTURE.md`), replace:
````markdown
| `api` | Keycloak client; DB role `api` | SELECT on conversation and audit tables; INSERT on messages, idempotency, feedback, outbox, `resume_input` jobs; UPDATE on `runs.cancel_requested` only; runs, decisions and revisions only through `create_run`, `record_decision`, `create_revision`; status answers and conversation clarifications are plain messages | PostgreSQL, Keycloak (login, `view-users` check) | update `runs.state`; insert decisions, proposals, grants, attempts or events directly; reach either sim |
| `worker` | Keycloak client; DB role `worker` | run_lease, jobs, drafts, invocation_context (insert), outbox (insert), corpus tables (ingestion), model_permit, checkpoints schema; `runs` columns `checkpoint_id`, `budget_used`; transitions only through `transition_run` (pre-grant states), `freeze_proposal`, `mark_unknown` and `escalate_run`; handle revocation through `revoke_handles` | PostgreSQL, mcp-read, mcp-write, Ollama | write decisions, memberships, grants, attempts or events; mark a run SUCCEEDED; reach either sim |
````
with:
````markdown
| `api` | Keycloak client; DB role `api` | SELECT on conversation and audit tables; INSERT on messages, idempotency, feedback, outbox, `resume_input` jobs; UPDATE on `runs.cancel_requested` only; runs, decisions, revisions, cancels and manual proposals only through `create_run`, `record_decision`, `create_revision`, `request_cancel`, `prepare_manual_proposal` and `create_manual_proposal`, expiry through `expire_proposal`, the manual search through `search_procedures_api` (T21); status answers and conversation clarifications are plain messages | PostgreSQL, Keycloak (login, `view-users` check) | update `runs.state`; insert decisions, proposals, grants, attempts or events directly; reach either sim |
| `worker` | Keycloak client; DB role `worker` | run_lease, jobs, drafts, invocation_context (insert), outbox (insert), corpus tables (ingestion), model_permit, checkpoints schema; `runs` columns `checkpoint_id`, `budget_used`, `asset_observed_at`, `workflow_version`; transitions only through `transition_run` (pre-grant states), `freeze_proposal`, `mark_unknown` and `escalate_run`; handle revocation through `revoke_handles` | PostgreSQL, mcp-read, mcp-write, Ollama | write decisions, memberships, grants, attempts or events; mark a run SUCCEEDED; reach either sim |
````

Edit 209 (`docs/ARCHITECTURE.md`), replace:
````markdown
- **The final gate is a database function.** `grant_execution` re-checks membership, hash, expiry, cancellation and the asset guard inside one transaction, and only `mcp_exec` may call it. Approval text, model text and chat text never grant anything.
````
with:
````markdown
- **The final gate is a database function.** `grant_execution` re-checks membership, the approved hash, expiry, cancellation, every cited source, the asset observation's age and the asset guard inside one transaction (revision 0016, T21); a refusal that needs a person's review commits BLOCKED_REVIEW with its reason, and only `mcp_exec` may call it. Approval text, model text and chat text never grant anything.
````

Edit 210 (`docs/PROJECT_HISTORY.md`), replace:
````markdown
## 36. What the process taught
````
with:
````markdown
## 36. The review plan made the human decision and the final gate exact

**Problem.** Plan R takes T21: a decision named a hash but not a revision, so a stale screen could approve, and the
first-decision rule, expiry and independence were checked partly outside the run's lock. The final grant re-read
memberships but not the cited sources, the asset's observation or the asset guard, and a refused grant left the run
APPROVED for the sweeper to re-dispatch for ever. There was no way to revise, cancel, write a proposal by hand when the
model was down, or leave feedback.

**Change.** Revision 0016 puts every rule under the run's lock with its own code, and keeps the run's content authors
on the run, so the requester, a reviser or a manual author can never approve. A revision is a new graph thread with its
own job and manifest. The asset guard is one SQL helper under a per-asset advisory lock, shared by both freezes and the
grant; the grant returns its verdict and commits BLOCKED_REVIEW for the refusals a person must look at, and raises for
the ones that must leave nothing behind. The worker reads the asset status again just before the grant, and when the
model cannot draft the run waits in DRAFTING for a person's proposal, which meets the same review.

**Review.** Building the slice in a scratch copy, live gate included, found what reading had not: the guard blocked
the existing live suites wherever two tests froze runs on one asset and interval, and the R105 skeleton test now leaves
a SUCCEEDED incident on A17 that later modules must step around; the read path's new freshness bound refused the
tests that move the database clock; the round trips of revisions 0011-0013 compared functions that 0016 re-creates, so
they now start from 0015; and a crash after the resume's checkpoint does not resume twice: the next job carries on from
the stored step, so R023's "exactly the accepted event" is the saver's one resume write, not a second resume.

## 37. What the process taught
````

- [ ] **Step 3: Final gates**

Dev `CHECK: GREEN`, `1791 passed, 237 skipped`; live `CHECK: GREEN`, `2007 passed, 21 skipped` (then `git checkout --
reports`, keeping `reports/auth/t11-sessions-revocation.txt` as the run rewrote it); `verify_handoff.py` exit 0.

- [ ] **Step 4: Placeholders, checkboxes and the commit**

Fill in `<base>`, `<last>`, `<date>`, `<dev>` and `<live>` in `SESSION_STATE.md` and `STATUS.md` with the values
(`grep -n "<base>\|<last>\|<date>\|<dev>\|<live>" SESSION_STATE.md STATUS.md` prints nothing afterwards);
tick this plan's checkboxes. The history section's review paragraph names this plan's review rounds and
execution findings when the controller writes it.

```bash
git add handoff SESSION_STATE.md STATUS.md README.md docs/ARCHITECTURE.md docs/PROJECT_HISTORY.md \
  docs/superpowers/plans/2026-10-25-first-slice-r-decisions-revisions-grant.md reports/auth
git commit -m "docs: close T21 (Plan R) - records, the T21 requirements, errata 131-145, state and history"
```

## Review Focus

1. **The asset guard reaches the existing live suites.** Any two runs of one tenant on one asset and an overlapping
   interval now meet it: the shared live helpers give each frozen run an asset of its own (`A17-<id>`), the R105 test
   leaves a SUCCEEDED incident on A17 for the rest of the session, so `test_worker_live.py` uses A19 and
   `test_r023_wakeup_live.py` A23. A new live module that freezes on A17 after R105 will be blocked
   `asset_incident_exists`, by design.
2. **`grant_execution`'s order.** The binding refusals raise first (OTHER_PROPOSAL, PROPOSAL_NOT_IN_RUN,
   NOT_ACTIVE_APPROVED, NO_APPROVAL, HASH_MISMATCH, CANCELLED); then expiry (via `_expire`, which journals its own
   `review.blocked`), authority (an inactive member is `authority_revoked`, committed), staleness of the membership sync
   (MEMBERSHIP_STALE raises: a deferral, never a block), the cited sources, the observation's age, and last the guard.
   Check that no committed refusal can follow a write and that a replayed grant still returns the grant it has.
3. **`record_decision` checks independence before ALREADY_DECIDED.** A content author asking about a decided proposal
   gets the unrecorded 403, never the 409 (BS:301); the 409s follow in the order ALREADY_DECIDED, STALE_REVISION,
   STALE_HASH, EXPIRED, each under the run's lock.
4. **The lock order.** API units: the idempotency lock, then (manual proposals) the asset lock, then the run. Worker
   freeze unit: the asset lock before the lease fence (erratum 143); `freeze_proposal` takes it again, re-entrantly.
   `grant_execution` reads the handle's run and asset without a lock before taking the asset lock.
5. **The manual path holds the conversation's slot.** A run left in DRAFTING for a person keeps its slot until a manual
   proposal or a cancel (debt → T22). `create_manual_proposal` re-derives every run-fixed field and the snapshots; the
   API builds the payload but decides none of them.
6. **R023's assertion (departure 12).** The second execute job forks from the post-resume step instead of resuming
   again; the evidence is the spy (one resume, the accepted id), the saver's single `__resume__` write and the grant's
   proposal id.
7. **Revision numbers (erratum 140).** `_run_revision` counts `proposal.revised` events; the freeze refuses a payload of
   another revision or a revision already frozen, so a skipped number is visible but never reused.
8. **The read path's freshness (ruling 14).** Any live test that moves the database clock must stamp memberships
   again; the three that do are edited in Task 6.

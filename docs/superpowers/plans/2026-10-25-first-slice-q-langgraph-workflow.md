# First Slice Q: The LangGraph Workflow (T20) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build T20: put a run's lifecycle into one explicit LangGraph graph. `route_request`'s conditional edges are
generated from a route table in `core/routing.py` (SA:377's seven dimensions); every invocation is
`durability="sync"`; each checkpoint LangGraph announces is confirmed with `aget_tuple` and stored in
`runs.checkpoint_id` under the lease fence; the two waits are ID-only interrupts after which the job releases the
lease; a clarification is resumed by the `resume_input` job with the reply's event id; an answer ends ANSWERED; a crash
resumes from the stored checkpoint and ignores a newer stray head. DoD 1: every MCP read completes before drafting.
DoD 2: a pause survives a worker restart from the stored id; a stray head is ignored. DoD 3: no evidence or proposal
text in a checkpoint. DoD 4: a test walks every router row to the node it reaches (R129).

**Architecture:** A package `worker/src/ops_worker/graph/` (`state.py`, `nodes.py`, `build.py`) holds SA:207's ten
nodes. The graph state is ids, verdicts and enum values only; what a node needs beyond that (the job, the lease, the
dependencies, the evidence bundle and the validated draft) lives in the per-graph-run `Context`, LangGraph's runtime
context, which is never persisted. The handlers stay the job entry points: `investigate`, a new `resume_input` and
`execute` take the claim's lease as today, decide how to enter the graph (a new graph run, `Command(resume=<event
id>)` with the stored checkpoint, or crash recovery with `None` and the stored checkpoint, which forks), and their
final unit releases the lease. `build.run_graph` streams `stream_mode="checkpoints"`; every announced checkpoint is
read back from the saver before its id is stored in its own fenced unit. The worker opens a fourth connection for
LangGraph's `AsyncPostgresSaver` (`search_path=checkpoints,pg_temp`); revision 0015 creates schema `checkpoints` with
the saver's DDL frozen inside the migration and worker-only DML (R122). Retrieval reads the asset status, the
interval's alerts and the procedures (two retries of a transient read, a 401 told apart) and judges sufficiency by
SA:377's code rule; the status and alerts reach the model as uncitable entries of `permitted_evidence`. The
validated draft is held in memory and routed by kind: a proposal to `validate_and_freeze`, an answer to
`publish_state` (ANSWERED, the cited answer in `explanation.ready`), a question to `await_clarification` (its event
carries the question), an abstention to `publish_state` (INSUFFICIENT_EVIDENCE).

**Tech Stack:** Python 3.13, psycopg 3.3.6, pytest and pytest-asyncio; new: `langgraph==1.2.14` and
`langgraph-checkpoint-postgres==3.1.2` (SA:580-581) in the worker; PostgreSQL 17 (`ops_test`) for the live gate. No
model call is needed: every graph test uses the fake route or a scripted one.

**Spec:** `SPEC_AMENDMENTS.md` (OPS-BUILD-1.3.6) over `BUILD_SPEC.md`: AM-12 (SA:201, SA:207, SA:209-218), AM-16
(SA:362, SA:377), AM-10 (SA:135-137, SA:147, SA:153), AM-20.2 (SA:419, SA:421, SA:434), AM-20.3 (SA:451-453),
AM-20.4 (SA:496, SA:501), AM-20.7 (SA:559-563), AM-15 (SA:333, SA:343), AM-30 (SA:580-581), AM-70 (SA:737); BUILD_SPEC
§8 (BS:305, BS:330, BS:334, BS:340, BS:342), §11 (BS:419, BS:423), §17 (BS:551-556, BS:562). Inputs: the fact sheet
`docs/superpowers/research/2026-10-25-plan-q-inputs.md` ("FS §n") and the controller's brief of seventeen rulings
("ruling n").

**Holdout custody (absolute).** No holdout case file, label or seal is opened, read, grepped, hashed or listed by
anyone executing this plan. Only `evals/HOLDOUT.md` and `evals/holdout-case.schema.json` may be read; every grep,
listing and diff excludes `*holdout*`, `*seal*` and `*.sha256`.

## Departures from the brief

Each place where this plan does something other than, or more than, a ruling says, with the reason. Nothing else
departs.

1. **The live gate was not run on the scratch copy (constraints).** The permission system refused to copy `.env`
   into the scratch tree again, so every live count below is arithmetic (dev passed + dev skipped − 21). The five
   new database live tests (`tests/e2e/test_graph_live.py`) and the live tests this plan changes have never run;
   Task 5 runs them first, and Review Focus 1 names them.
2. **The proposal is frozen in `validate_and_freeze`, not in the drafting node (ruling 4).** Freezing inside
   `draft_with_langchain` would leave the `freeze` route's node empty and SA:377's intent gate decorative. The
   validated draft is held in the worker's memory (`Context.held`) between the drafting node and the node its kind
   routes to, within one graph run, and never written to state, `drafts`, a checkpoint or an event. A graph run that
   resumes without the hold (a new process) routes back through retrieval and drafts again (erratum 128).
3. **The question's event is written by `await_clarification`, SA:207's name (rulings 4 and 7 say
   `request_clarification` and "the drafting node puts the question's event id into state").** The router then
   decides `clarify` against the run's state, and the round limit is counted in that node from the database (SA:215),
   so the router keeps SA:377's seven dimensions; a third question ends INSUFFICIENT_EVIDENCE. Graph state keeps the
   list of asked event ids (`asked`) as the cross-check.
4. **No mcp-write discovery check (ruling 14, conditional).** Whether mcp-write advertises the committed
   `create_incident` schema can only be checked live, and the scratch copy has no live stack; a check that the first
   live run might fail is not "one function and one test". The marker moves to `TODO(T21)`, with the result schema.
5. **Ruling 2(b) is read as "every route is some row's target and maps to exactly one node".** Several run states
   route to `publish`; rows match sets of states, so one row per route would need disjunction rows the walk cannot
   cover. `test_every_route_is_some_rows_target` and `test_every_route_has_one_node_and_some_row` pin both halves.
6. **`publish_state` has its own conditional exit, read from the same table, and `execute_approved_proposal` hands
   over to `reconcile_outcome`, which ends the graph run (ruling 14).** A crash resumes at the node that was next; for
   an answer that is `publish_state`, which must then go back to the router, and it ends the graph run only when the
   table routes the run to `publish`. `docs/ARCHITECTURE.md` §3's diagram is updated in Task 6 (erratum 128).
7. **More errata than the brief planned.** 126 records the setup-in-migration (the slot reserved for a version
   substitution was not needed: both pins resolved as SA:580-581 name them); 127 (a `resume_input` job's read handle
   works in RETRIEVING and DRAFTING: the resumed graph carries the run through them, ruling 7), 128 (the hold and the
   two exits, departures 2 and 6) and 129 (an unresumable waiting run walks AWAITING_INPUT → QUEUED → RETRIEVING →
   FAILED, the worker's only path).
8. **An asset the asset service does not know abstains; it never asks (ruling 2).** A reply cannot change the run's
   fixed asset (SA:154), so the `context_missing` row routes to `abstain`; the table lists no clarify row from
   retrieval.
9. **An execute job whose stored checkpoint is missing starts a new graph run instead of failing the run (ruling 5).**
   The worker may not move an APPROVED or EXECUTING run (SA:451); the router reads APPROVED and the execute path
   rereads everything. Investigate and resume_input jobs fail the run as ruled.
10. **`checkpoint_migrations` gets no worker grant (ruling 4: "its tables").** It is the library's bookkeeping,
    written by the revision; the worker never calls `setup()`. The live R122 test pins the refusal.
11. **The drafting node's "reuse a validated drafts row" guard (ruling 12) is the run-state reread.** The `drafts`
    row and the transition it belongs to commit in one unit, so a run still in DRAFTING never has one.
12. **`uv lock` also adds `psycopg-pool` 3.3.3 (ruling 16: "no psycopg-pool unless the saver requires it").** It is a
    declared dependency of `langgraph-checkpoint-postgres`; the worker opens no pool.
13. **The execute job resumes the reviewer wait (ruling 14 had it start the graph at `route_request` on APPROVED).**
    `await_independent_decision` interrupts with the proposal id (AM-12: both waits are ID-only interrupts after which
    the job releases the lease); the execute job resumes it with `Command(resume=<approval.recorded id>)`, after
    checking that the run's latest decision event is an approval of its active proposal (round 1, M1). A re-queued
    execute job forks from the stored checkpoint to re-run the execute node; a run with no stored checkpoint starts a
    graph run whose router reads APPROVED. Accepted as the design by the controller.

## Round 1 changes

The static review (`.superpowers/planq/round1-static.md`: 0 Critical, 2 Important, 7 Minor) is fixed in full, per
the controller's rulings (`round1-rulings.md`):

- **I1.** `route_request` rereads the run's state, intent, decision and attempt (`nodes.facts`) on every hop, so the
  router never routes on dimensions an earlier node or a forked checkpoint left stale; the critic's scenario (the
  freeze commits, the lease is lost at the next checkpoint store, the approved run forks from before its freeze) is
  `test_an_approved_run_resumed_from_before_its_freeze_executes`, and `test_the_router_rereads_the_runs_dimensions`
  pins the reread. The walk patches the reread with its witness; Plan M's two worker tests now keep the run row
  through Plan H's recorder.
- **I2.** `test_r108_each_step_finds_the_previous_checkpoint_stored` (live, Postgres saver): a stub node at step N+1
  finds step N's state already stored. The R108 note and STATUS say which test evidences what.
- **Minors.** M1: `handlers._approval` checks the resume value (the latest decision event is an `approval.recorded`
  of the active proposal; otherwise the job ends with no graph run, a logged error and a debt line → T22), with
  `test_an_execute_job_with_a_decision_for_another_proposal_runs_nothing`. M2: a debt line and erratum 128 say a
  rejected run's thread ends at the wait. M3: erratum 126 names `checkpoint_migrations`; new erratum 130 (SA:136).
  M4: the debt line → T29, erratum 128 names BS:554/555, and `test_a_hold_lost_after_a_completed_draft_is_drafted_
  again`. M5: the plan's lines over 120 characters are wrapped and Edit 55's wording corrected. M6: revision 0015 says
  why it has no per-table REVOKE. M7: `await_clarification`'s QUEUED branch also records the round it answered.
- The counts move: `test_graph_flow.py` 21 (17); dev after Task 4 `1721 passed, 222 skipped` (1717), after Task 5
  `1721 passed, 227 skipped` (1717, 226); live `1927 passed, 21 skipped` (1922, arithmetic). The plan's blocks were
  re-applied to a fresh worktree of `6466b8c` and every task re-gated there.

## Global Constraints

Carried from Plan P's header (its text applies with "Plan P"/"T19" read as the plan that wrote it); the Plan Q
additions below win where the two differ:

- **Debt before code (SA:698).** The Plan Q debt list is committed in Task 1 Step 1c before any code changes.
- **Authority boundaries stay where the spec puts them.** Graph state is never the authority: every node rereads the run
  before it acts, and the router rereads its dimensions on every hop (SA:215, BS:305) and every state change goes
  through `transition_run`, `freeze_proposal` or `mark_unknown` as role `worker`; a checkpoint can approve or execute
  nothing. Interrupts carry an event or proposal id only (SA:563); a resume value is checked against the database, never
  trusted. The model sees no tool; only `retrieve_evidence` calls mcp-read and only `execute_approved_proposal` calls
  mcp-write. **Nothing here sends anything to an external system or a person** (BS:730).
- **Never touch the dev databases.** Nobody runs `scripts/skeleton.py migrate`, `ingest`, `embed` or `up`, or
  connects to `ops`/`incident`, in this plan. After Task 4 the worker refuses to start without
  `checkpoints.checkpoints` (revision 0015), which is the intended guard.
- **Holdout custody.** As in the header.
- **Secrets** live only as files under `OPS_SECRETS_DIR`; nothing here reads one, except the live gate's existing
  fixtures. LangSmith tracing stays off (no `LANGSMITH_*` or `LANGCHAIN_TRACING*` variable anywhere).
- **Tests:** unit tests in `tests/plan_q/` (no database, no network; LangGraph's in-memory saver and Plan H's fakes;
  added to `testpaths` in Task 1); the database live tests in `tests/e2e/` behind `OPS_LIVE=1`. No xfail, no skip
  except the live gate.
- **Comments** per `docs/CODE_COMMENTS.md`; ≤120 characters per line; no `type: ignore`; no new `noqa`; ruff + mypy
  strict clean; UTF-8 without BOM, LF.
- **Stage before the gate.** `tests/plan_a/test_verify_handoff.py` copies the files `git ls-files` lists; every step
  that creates a file runs `git add <the new files>` before the gate.
- **Gates:** `uv run ruff format <files> && uv run ruff check --fix <files>`, `PYTHONUTF8=1 uv run python
  scripts/check.py < /dev/null` GREEN after every task and `uv run python -I scripts/verify_handoff.py --reference-code
  --manifest --contracts < /dev/null` exit 0 after every task. Run mypy only through `check.py`: a by-hand mypy over one
  package pollutes `.mypy_cache` (seen while writing this plan; delete `.mypy_cache` if it happens). The live gate,
  `PYTHONUTF8=1 uv run python scripts/check.py --profile test < /dev/null` (dev stack up, local Ollama on
  127.0.0.1:11434, `uv run python scripts/skeleton.py status` showing every process down), runs in Task 1 Step 1a, in
  Task 5 and in Task 6. After a live run: `git checkout -- reports`, except the report a step commits.
- **Toolchain:** everything through the locked environment from the repository root. Task 1 changes `uv.lock` once
  (`uv lock`, then `uv sync --locked --all-packages`); nothing else touches it. Never start an interactive interpreter,
  never feed a script to an interpreter on standard input (`python -`, `python -c`), never end a process by image
  name. A helper script is a file, run as `uv run python -I <path> < /dev/null`; `python -m scripts.build_schemas` is
  the one module run.
- **Commits:** one logical group per step that says "commit"; messages free of any attribution trailer (owner
  instruction); never push; never `docker compose down -v`; never change system settings.
- **No interim red across tasks.** Every task ends with its gates GREEN at the stated counts.
- **Edits** quote the exact current text ("Edit n (`path`), replace:" then "with:"); a step that creates or replaces a
  file gives the whole file. Code blocks use four-backtick fences.
- **Counts.** Today (`6466b8c`) the dev gate is `1629 passed, 222 skipped` and the live gate `1830 passed, 21
  skipped`. Task 1 Step 1a records both before any change; if either differs, every expected count below shifts by the
  same difference. Every Create and Edit of Tasks 1-5 was applied, in order, to a fresh worktree of `6466b8c` (with
  `uv lock`'s result) and gated there after each task: ruff, ruff format and mypy strict clean, the stated dev counts,
  `verify_handoff.py` exit 0; the RED outputs below were measured there. A second fresh worktree, rebuilt from this
  file's blocks by a script, came out byte-identical. Task 6's records were applied there too, with both gates
  passing. Live counts are arithmetic (departure 1).

## Rulings (the brief's 17, as this plan implements them)

1. **Location** — `worker/src/ops_worker/graph/` (`state.py`, `nodes.py`, `build.py`); `handlers.investigate`,
   `resume_input`, `execute` claim the lease and run the graph; `GRAPH_ROUTES`, `GraphKey`, `GraphRule` and
   `route_graph` in `core/src/ops_core/routing.py`, first match wins, `LookupError` when none (Tasks 2, 4).
2. **Nodes and edges** — the ten nodes; `build.edge_map()` from the table; the three tests (a) edges = table routes,
   (b) every route one node and some row (departure 5), (c) the walk of every row; the produced-key test; "context
   resolved?" decided in retrieval (Tasks 2, 4; departures 5, 6, 8).
3. **Retrieval** — status, alerts, search (limit 3, `lexical`); SA:377's rule with a 5-minute freshness (erratum 122);
   two retries within a six-call budget; a 401 its own message; status and alerts in `permitted_evidence` without an
   evidence id; the node log in `Context.trace` (Tasks 3, 4).
4. **Checkpointer** — `AsyncPostgresSaver`, schema `checkpoints`, revision 0015 with the frozen DDL and the version
   rows (erratum 126); worker DML only, no RLS (erratum 123); the fourth connection; state ids only (Tasks 2, 4;
   departures 2, 10).
5. **`runs.checkpoint_id`** — thread `run_id:revision`; `astream(stream_mode="checkpoints", durability="sync")`; each id
   confirmed by `aget_tuple`, stored in its own fenced unit; the lock-order entries; a missing id fails the run (Tasks
   2, 4; departure 9).
6. **Durability** — `durability="sync"` on every invocation, spied in a unit test (the argument); live, a stub node at
   step N+1 finds step N's checkpoint already stored (the behaviour); the stored id is the head that holds the
   interrupt, read back live (Tasks 4, 5).
7. **Interrupts and resume** — the question in `clarification.requested`; `interrupt(event_id)`; resume with the
   `clarification.received` event id; the resumed node checks it is the latest answer to the latest question, rereads
   the reply, moves the run to QUEUED and the graph retrieves and drafts again; rounds from the database (Tasks 2, 4;
   departure 3; errata 127, 129).
8. **Question and answer text** — in their events (erratum 124); `PAYLOAD_KEYS` already admit `message` for both, so
   no revision change (Task 4).
9. **Human waits** — the lease released after each interrupt; `WAKEUPS` unchanged; R022 live (Tasks 4, 5).
10. **ANSWERED** — any `answer` → ANSWERED (DEV-002); a proposal on `answer_only` matches no row; the payload says
    "Answer only; do not propose an incident." (Tasks 2, 3, 4).
11. **Fake route** — answers an `answer_only` run, proposes otherwise; scripted drafts in tests (Task 3).
12. **Crash recovery** — fork from the stored id, the fork's id stored; the manifest kept once per run; reads and
    `tool.*` events repeat; the stray head test; two crashes in a row (Task 4; departure 11).
13. **Revision re-entry** — thread per run and revision, revision 1 today; the manifest one per run (erratum 125);
    `workflow_version` in checkpoint metadata (Task 4).
14. **Execute and recover** — the execute job resumes the reviewer wait with the decision's event id, checked first
    (or re-runs the execute node after a re-queue); `reconcile_outcome` logs and ends; recover jobs stay unhandled
    (Task 4; departures 4, 6, 13).
15. **Tests** — as listed in the task overview; the live report `reports/graph/t20-graph-live.md` (Tasks 2-5).
16. **Dependencies** — both pins in `ops-worker`, one `uv lock` (Task 1; departure 12).
17. **Records** — Task 1's debt list; Task 6's records, errata 122-130, history section 35.

## Measured before writing (2026-10-24/25, scratch copies of `6466b8c`)

- Dev gate before any change `1629 passed, 222 skipped`; after Task 1 the same; after Task 2 `1667 passed, 222
  skipped`; after Task 3 `1672 passed, 222 skipped`; after Task 4 `1721 passed, 222 skipped`; after Task 5 `1721
  passed, 227 skipped` (round 1: re-measured on a fresh worktree after the fixes). `verify_handoff.py` exit 0 after
  every task (30 JSON Schema documents).
- `uv lock` (`Resolved 96 packages`) adds 7 packages and removes none: langgraph 1.2.14, langgraph-checkpoint 4.3.0,
  langgraph-checkpoint-postgres 3.1.2, langgraph-prebuilt 1.1.1, langgraph-sdk 0.4.9, ormsgpack 1.13.0, psycopg-pool
  3.3.3. They resolve beside `langchain-core` 1.7.0 and `psycopg` 3.3.6 (no change to either). The resolver may pick
  a newer patch of a transitive package on a later day; record what it adds.
- LangGraph behaviour the code relies on, read from the installed 1.2.14 sources (`.venv/Lib/site-packages/langgraph/`):
  an explicit `checkpoint_id` makes the loop replay (`pregel/_loop.py:330`) and then pending writes of finished tasks
  are not re-applied (`:767-770`), so every node re-runs from its start and must be idempotent (SA:215); a
  `Command(resume=…)` on the stored id is not time travel and does not fork (`:890-910`), while input `None` on it
  forks and puts a `source: fork` checkpoint (`:920-929`, `:1028`); a checkpoint's write is submitted without waiting
  (`:1266`) and `durability="sync"` waits only after a superstep (`pregel/main.py:3525-3527`), so a run's first
  checkpoint and a fork can be announced before they are written (hence `aget_tuple` before storing); the
  `checkpoints` stream event is emitted at the start of the next tick (`_loop.py:647-665`) and the runner yields before
  it starts the node (`pregel/_runner.py:388-389`), so the store never races a node on the loop connection; a string
  in `config["metadata"]` is copied into every checkpoint's metadata (`checkpoint/base/__init__.py:786-804`). The
  saver's DDL is `BasePostgresSaver.MIGRATIONS` (`checkpoint/postgres/base.py:43-91`, ten statements, three `CREATE
  INDEX CONCURRENTLY`); `setup()` records each statement's number (`checkpoint/postgres/aio.py:90-117`); the saver
  expects an autocommit dict-row connection (`aio.py:81-83`) and serialises its own calls with a lock (`aio.py:374`).
  Primitive channel values are stored inline in `checkpoints.checkpoint` JSONB and the rest in `checkpoint_blobs`, so
  R091's grep reads both and `checkpoint_writes`.
- The MCP SDK reports every non-2xx HTTP answer as the same `INTERNAL_ERROR` (`mcp/client/streamable_http.py:398-427`),
  so the worker's client records the statuses itself (an httpx2 response hook) to tell a 401 from a transport failure.
- Building the slice in the scratch copy found three faults the design had not foreseen, all fixed in the code below:
  a clarified run retrieving again would hit `run_manifests`' primary key (now kept once, erratum 125); a
  `resume_input` job's read handle was refused in RETRIEVING (erratum 127); and crash recovery resumes at the next
  node, which may be the consumer of a lost hold (now routed back through retrieval). Round 1's static review found a
  fourth: a node's early return left the router's decision and attempt dimensions stale, so an approved run that had
  forked from before its freeze could never execute; the router now rereads them on every hop.

## Declared debt and errata

### Debt list (committed in Task 1 Step 1c, before coding)

Inserted into `SESSION_STATE.md` as `## Plan Q debt list (T20; committed before coding) [R6-B7]` immediately after the
Plan P debt list (before `## Environment (observed)`); the exact text is Task 1 Step 1c's Edit 1.

### Errata proposed to the owner (numbered on from erratum 121; next free 131)

The spec text stays authoritative until the owner decides; the full wording is Task 6's "Plan Q executed" block; in
short: **122** SA:377's sufficiency rule as built (5-minute freshness; the search's rank threshold is v1's relevance
criterion); **123** no RLS on the checkpoint tables; **124** the question and the answer ride in their events;
**125** one manifest per run across a clarification; **126** the saver's `setup()` frozen inside revision 0015;
**127** `resume_input` read handles in RETRIEVING and DRAFTING; **128** the in-memory hold between nodes and the two
graph exits; **129** an unresumable waiting run's path to FAILED; **130** SA:136's RETRIEVING → AWAITING_INPUT is not
taken in v1.

## File structure

- `worker/pyproject.toml`, `uv.lock`, `pyproject.toml` (`testpaths`), `tests/plan_q/__init__.py` (Task 1).
- `core/src/ops_core/routing.py` (the table), `persistence.py` (graph facts, the checkpoint id, events, a message, the
  manifest check), `jobs.py` (`resume_input` states), `privileges.py` and `locking.py` (the checkpoint tables),
  `schemas/job.schema.json` (regenerated), `migrations/app/versions/0015_checkpoints.py` (Task 2).
- `worker/src/ops_worker/evidence.py` (new), `drafting.py`, `ollama_drafting.py`, `mcp.py`,
  `mcp-read/src/ops_mcp_read/assets.py` (a docstring) (Task 3).
- `worker/src/ops_worker/deps.py` and `worker/src/ops_worker/graph/` (new), `handlers.py` (replaced), `main.py`,
  `sweeper/src/ops_sweeper/wakeups.py` (a docstring) (Task 4).
- Tests: `tests/plan_q/` (`test_graph_table.py`, `test_migration_0015.py` Task 2; `fixtures.py`, `test_evidence.py`
  Task 3; `test_graph_routes.py`, `test_graph_flow.py` Task 4); edits to `tests/plan_e/test_transitions_table.py`,
  `tests/plan_h/test_locking.py`, `tests/plan_j/test_allowlist.py` (Task 2), `tests/plan_j/test_worker_azp.py` (Tasks 3
  and 4), `tests/plan_h/test_worker_units.py` (the shared fakes), `tests/plan_p/test_investigate_drafting.py`,
  `tests/plan_p/test_worker_startup.py`, `tests/plan_f/test_grant_deferred.py` (Task 4); `tests/e2e/test_graph_live.py`
  (new) and edits to `test_worker_live.py`, `test_heartbeat_live.py`, `test_r105_walking_skeleton.py`,
  `test_admission_live.py` (Task 5); `reports/graph/t20-graph-live.md` (written and committed in Task 5).
- Records: `SESSION_STATE.md` (Tasks 1, 6), `handoff/*`, `STATUS.md`, `README.md`, `docs/ARCHITECTURE.md`,
  `docs/PROJECT_HISTORY.md` (Task 6).

## Task overview

- **Task 1:** the debt list; baselines; the two pins and `uv lock`; `tests/plan_q` on the path. No tests. Dev `1629
  passed, 222 skipped`; live `1830 passed, 21 skipped`.
- **Task 2:** the route table, the persistence helpers, revision 0015 and its matrix rows. Tests:
  `test_graph_table.py` 30 (26 witness cases), `test_migration_0015.py` 3, one more revision case, four more lock-order
  units. Dev `1667 passed, 222 skipped`; live `1868 passed, 21 skipped`.
- **Task 3:** the evidence bundle, the sufficiency rule, the payload and the read failures. Tests: `test_evidence.py`
  5. Dev `1672 passed, 222 skipped`; live `1873 passed, 21 skipped`.
- **Task 4:** the graph and the handlers. Tests: `test_graph_routes.py` 28 (26 walk cases), `test_graph_flow.py` 21;
  Plan H's fakes keep the run row and its events; six existing unit modules follow the graph. Dev `1721 passed, 222
  skipped`; live `1922 passed, 21 skipped`.
- **Task 5:** the live tests and the first live gate of the plan. Tests: `test_graph_live.py` 5 (live); four live
  modules follow the graph. Dev `1721 passed, 227 skipped`; live `1927 passed, 21 skipped`.
- **Task 6:** close-out: handoff records, requirements, errata 122-130, state, history, final gates. No tests.

The arithmetic, once: dev passed 1629, + 30 + 3 + 1 + 4 = 1667, + 5 = 1672, + 28 + 21 = 1721, 1721; dev skipped 222,
222, 222, 222, + 5 = 227. Live passed = dev passed + (dev skipped − 21): 1830, 1868, 1873, 1922, 1927, always with 21
skipped. Every dev figure was measured on the scratch copy; the live ones are arithmetic.

---
### Task 1: Debt before code — baselines, the dependencies

**Files:**
- Modify: `SESSION_STATE.md` (the debt list), `worker/pyproject.toml`, `uv.lock`, `pyproject.toml` (`testpaths`)
- Create: `tests/plan_q/__init__.py`

**Requirements:** rulings 16, 17; SA:698 (the debt list first); SA:580-581.

- [ ] **Step 1a: Record both baselines**

Run `PYTHONUTF8=1 uv run python scripts/check.py < /dev/null` → `CHECK: GREEN` with pytest `1629 passed, 222
skipped`; with the dev stack up, local Ollama answering and `uv run python scripts/skeleton.py status` showing every
process down, run `PYTHONUTF8=1 uv run python scripts/check.py --profile test < /dev/null` → `CHECK: GREEN` with `1830
passed, 21 skipped`, then `git checkout -- reports`. Run `uv run python -I scripts/verify_handoff.py --reference-code
--manifest --contracts < /dev/null` → exit 0. Record the three lines in the report. A gate that is not GREEN stops the
plan here, before anything is committed.

- [ ] **Step 1b: Record the base**

Run `git rev-parse --short HEAD` (expected `6466b8c` or the commit that adds this plan on top of it) and write it as
`BASE=<hash>` in the report and the SDD ledger. Task 6's span is `<base>..<last>`. `git status --short` prints nothing.

- [ ] **Step 1c: Commit the debt list (before any code)**

Edit 1 (`SESSION_STATE.md`), replace:

````markdown
- the dev database stays at 0013 until the owner migrates it (revision 0014); the worker refuses to start on it before
  then.

## Environment (observed)

| Item | Observed |
````

with:

````markdown
- the dev database stays at 0013 until the owner migrates it (revision 0014); the worker refuses to start on it before
  then.

## Plan Q debt list (T20; committed before coding) [R6-B7]

Allowed shortcuts in T20, each with its owning task:
- the stock `AsyncPostgresSaver` does not check the run fence inside its own writes: the stored checkpoint id protects
  the head, but a stale worker could still append a checkpoint or a pending write after losing its lease; v1 runs one
  worker replica (SA:217) → T38 (R021, M15);
- R042's restart is a new graph instance on a new saver connection inside one test process; a killed worker process
  is not tested → T30 (the `docker kill` recovery demo); SIGTERM is still not drained (T30's marker);
- crash recovery repeats the reads and their `tool.*` events, and a draft held in memory when the process stopped is
  drafted again (nothing text-bearing was persisted, SA:496): a run recovered after a completed draft can make more
  than BS:554's two generation attempts, and its next job counts BS:555's 90 s from its own claim → T29 (erratum 128);
- a transient read is retried at most twice inside the retrieval node (BS:552) and then the run ends FAILED, and a
  401 to the worker's token ends FAILED with its own message; a bounded re-queue of the job instead → T22;
- the read path has no membership freshness bound (erratum 105) → the owner's decision on erratum 105, then T21;
- "evidence sufficient?" is SA:377's rule with a 5-minute freshness window, and the search's minimum rank is v1's
  relevance criterion (erratum 122); erratum 102's residue (5 of 20 no-source questions answered) stays measured →
  T25;
- the T19 evidence run (`reports/model/t19-real-run.md`) was made before the asset status and alerts reached the
  payload; its figures may move and it is not re-run here → T25 (the real-model trials);
- revision re-entry is a seam only: one LangGraph thread per run and revision, `build_proposal` freezes revision 1,
  `runs.checkpoint_id` is per run, and the manifest stays one per run (erratum 125) → T21;
- `workflow_version` lives only in the checkpoint metadata → T21 (a column) and T36 (routing across a bump);
- `recover` jobs are closed unhandled and `reconcile_outcome` only logs → T22;
- an execute job whose run's latest decision is not an approval of its active proposal ends without a graph run, logs
  the three ids and leaves the run APPROVED (the worker may not move it, SA:451); recovering such a run → T22;
- a rejected run's graph thread ends at the reviewer wait: `record_decision` queues no job on a rejection, so
  `publish_state` never runs for it in v1; the run's REJECTED state is the API's and is authoritative → recorded
  (erratum 128), no task;
- the worker's write tool keeps T47's result check: no discovery listing and no result-schema check for
  `create_incident` (Plan Q departure 4) → T21;
- a human wait is not excluded from the compute budget, and `runs.budget_used` is not written → T29;
- the node log is per graph run, in memory and in the logs; spans for the graph's nodes → T28 (R058);
- the saver has one connection with no pool and no reconnect: a broken saver connection fails the graph run → T30;
- checkpoints of finished threads are never pruned → T30;
- an answer's summary is shown as the model wrote it (validated, cited, `source=model_summary`) → T26 (R055's safe
  display);
- every run still asks for `lexical` retrieval → T25 (Plan N ruling 16);
- the dev database stays at 0013 until the owner migrates it; the worker now needs revision 0015 as well.

## Environment (observed)

| Item | Observed |
````

```bash
git add SESSION_STATE.md
git commit -m "docs: declare Plan Q's shortcuts before coding (T20 debt list)"
```

- [ ] **Step 2: The dependencies and the test path**

Edit 2 (`worker/pyproject.toml`), replace:

````toml
  "langchain-core==1.7.0",
  "ollama==0.6.3",
  "httpx==0.28.1",
]

[tool.uv.sources]
````

with:

````toml
  "langchain-core==1.7.0",
  "ollama==0.6.3",
  "httpx==0.28.1",
  "langgraph==1.2.14",
  "langgraph-checkpoint-postgres==3.1.2",
]

[tool.uv.sources]
````

Edit 3 (`pyproject.toml`), replace:

````toml
testpaths = [
  "tests/plan_a", "tests/plan_b", "tests/plan_c", "tests/plan_d", "tests/plan_e", "tests/plan_f", "tests/plan_g",
  "tests/plan_h", "tests/plan_i", "tests/plan_j", "tests/plan_k", "tests/plan_l", "tests/plan_m", "tests/plan_n",
  "tests/plan_o", "tests/plan_p", "tests/e2e",
]
asyncio_default_fixture_loop_scope = "function"
# Setting this replaces pytest's defaults (which include ".*"), so ".*" is restated: otherwise pytest walks .hypothesis/.
````

with:

````toml
testpaths = [
  "tests/plan_a", "tests/plan_b", "tests/plan_c", "tests/plan_d", "tests/plan_e", "tests/plan_f", "tests/plan_g",
  "tests/plan_h", "tests/plan_i", "tests/plan_j", "tests/plan_k", "tests/plan_l", "tests/plan_m", "tests/plan_n",
  "tests/plan_o", "tests/plan_p", "tests/plan_q", "tests/e2e",
]
asyncio_default_fixture_loop_scope = "function"
# Setting this replaces pytest's defaults (which include ".*"), so ".*" is restated: otherwise pytest walks .hypothesis/.
````

Create `tests/plan_q/__init__.py` (empty).

Then run `uv lock < /dev/null` (network) → `Resolved 96 packages` and the seven `Added …` lines of "Measured before
writing", then `uv sync --locked --all-packages < /dev/null`. Gates: `git add tests/plan_q/__init__.py`; dev
`CHECK: GREEN`, `1629 passed, 222 skipped`; `verify_handoff.py` exit 0.

```bash
git add worker/pyproject.toml uv.lock pyproject.toml tests/plan_q/__init__.py
git commit -m "build: langgraph 1.2.14 and langgraph-checkpoint-postgres 3.1.2 for the worker (T20)"
```

---
### Task 2: The route table, the persistence helpers and revision 0015

**Files:**
- Create: `tests/plan_q/test_graph_table.py`, `tests/plan_q/test_migration_0015.py`,
  `migrations/app/versions/0015_checkpoints.py`
- Modify: `core/src/ops_core/routing.py`, `persistence.py`, `jobs.py`, `privileges.py`, `locking.py`,
  `schemas/job.schema.json` (regenerated), `tests/plan_e/test_transitions_table.py`, `tests/plan_h/test_locking.py`,
  `tests/plan_j/test_allowlist.py`

**Requirements:** rulings 1, 2, 4, 5, 7, 10, 13; SA:377, SA:434, SA:559-562; R122, R129 (the table half); errata 122,
123, 125-127.

**Interfaces:**
- Produces: `ops_core.routing.Evidence`, `DraftKind`, `GraphKey`, `GraphRule`, `GRAPH_ROUTES`, `route_graph(key)`;
  `ops_core.persistence.GraphFacts`, `graph_facts(conn, run_id)`, `store_checkpoint_id(conn, run_id, checkpoint_id)`,
  `run_events(conn, run_id, type)`, `message_text(conn, message_id)`, `run_manifest_exists(conn, run_id)`;
  `ops_core.privileges.CHECKPOINT_SCHEMA`, `CHECKPOINT_GRANTS`; revision `0015_checkpoints` (`statements()`,
  `CHECKPOINT_DDL_0015`, `CHECKPOINT_GRANTS_0015`).

- [ ] **Step 1: The tests first**

Create `tests/plan_q/test_graph_table.py`:

````python
"""The graph router's table on its own (T20; SA:377; R129's graph half), without the worker.

Catches: a row that an earlier row shadows (its witness key reaches another row first); a key the worker's nodes
can leave behind that no row routes (the graph run would fail on LookupError); `freeze` without its intent gate; an
answer that does not end on the answer path whatever the intent (DEV-002); and a model's draft kind that could select
anything but abstain, clarify, answer or freeze.
"""

from itertools import product

import pytest
from ops_core.routing import GRAPH_ROUTES, DraftKind, Evidence, GraphKey, GraphRoute, GraphRule, route_graph
from ops_core.states import AttemptState, Intent, RunState


def witnesses(rule: GraphRule) -> list[GraphKey]:
    """One key per run state the row covers, every other dimension at the value the row names or a neutral one."""
    attempt = None if rule.attempt_states is None else min(rule.attempt_states, key=str)
    return [
        GraphKey(
            state,
            rule.intent or Intent.INVESTIGATE,
            True if rule.context_resolved is None else rule.context_resolved,
            rule.evidence or (Evidence.SUFFICIENT if rule.draft_kind else Evidence.UNKNOWN),  # a draft needs it
            rule.draft_kind or DraftKind.NONE,
            bool(rule.decision_present),
            attempt,
        )
        for state in sorted(rule.states)
    ]


WALK = [(rule.name, witness) for rule in GRAPH_ROUTES for witness in witnesses(rule)]


@pytest.mark.parametrize(("name", "witness"), WALK, ids=[f"{n}-{w.state.value}" for n, w in WALK])
def test_each_row_is_the_first_match_for_its_witness(name: str, witness: GraphKey) -> None:
    rule = next(r for r in GRAPH_ROUTES if r.name == name)
    assert next(r for r in GRAPH_ROUTES if r.matches(witness)) is rule  # no earlier row shadows it
    assert route_graph(witness) is rule.route


def test_every_route_is_some_rows_target() -> None:
    assert {rule.route for rule in GRAPH_ROUTES} == set(GraphRoute)


# States that exist only after a reviewer's decision (record_decision is the only way out of AWAITING_APPROVAL).
DECIDED = frozenset(
    {
        RunState.APPROVED,
        RunState.REJECTED,
        RunState.EXECUTING,
        RunState.OUTCOME_UNKNOWN,
        RunState.ESCALATED,
        RunState.SUCCEEDED,
        RunState.ABANDONED_UNVERIFIED,
    }
)


def produced() -> list[GraphKey]:
    """Every key the worker's nodes can leave behind (Plan Q ruling 2): what load_run and the other rereads see in each
    state, and what retrieval and drafting return. The decision and attempt dimensions are always the database's,
    because `route_request` rereads them on every hop (round 1, I1; `test_graph_flow.test_the_router_rereads_...`)."""
    keys: list[GraphKey] = []
    for state, intent in product(RunState, Intent):
        attempts = (
            (AttemptState.INTENT, AttemptState.SENT, AttemptState.ABORT_REQUESTED)
            if state is RunState.EXECUTING
            else (None,)
        )
        for attempt in attempts:
            keys.append(GraphKey(state, intent, True, Evidence.UNKNOWN, DraftKind.NONE, state in DECIDED, attempt))
    for state, intent in product((RunState.RETRIEVING, RunState.DRAFTING), Intent):
        keys.append(GraphKey(state, intent, False, Evidence.UNKNOWN, DraftKind.NONE, False, None))  # asset unknown
        keys.append(GraphKey(state, intent, True, Evidence.INSUFFICIENT, DraftKind.NONE, False, None))
    for intent, kind in product(Intent, DraftKind):
        if (intent, kind) != (Intent.ANSWER_ONLY, DraftKind.PROPOSAL):  # validation refuses that pair (SA:453)
            keys.append(GraphKey(RunState.DRAFTING, intent, True, Evidence.SUFFICIENT, kind, False, None))
    return keys


def test_every_key_the_worker_produces_has_a_route() -> None:
    for produced_key in produced():
        assert route_graph(produced_key) in set(GraphRoute), produced_key  # LookupError would fail the graph run


def test_freeze_is_gated_by_intent_and_an_answer_is_answered_on_any_run() -> None:
    base = GraphKey(RunState.DRAFTING, Intent.INVESTIGATE, True, Evidence.SUFFICIENT, DraftKind.PROPOSAL, False, None)
    assert route_graph(base) is GraphRoute.FREEZE
    with pytest.raises(LookupError):  # a proposal on an answer_only run is never frozen
        route_graph(GraphKey(**{**base.__dict__, "intent": Intent.ANSWER_ONLY}))
    for intent in Intent:  # DEV-002: an investigate prompt may end ANSWERED (Plan Q ruling 10)
        answer = GraphKey(**{**base.__dict__, "intent": intent, "draft_kind": DraftKind.ANSWER})
        assert route_graph(answer) is GraphRoute.ANSWER_ONLY


def test_a_draft_kind_selects_only_abstain_clarify_answer_or_freeze() -> None:
    routes = {
        route_graph(GraphKey(RunState.DRAFTING, Intent.INVESTIGATE, True, Evidence.SUFFICIENT, kind, False, None))
        for kind in DraftKind
        if kind is not DraftKind.NONE
    }
    assert routes == {GraphRoute.ABSTAIN, GraphRoute.CLARIFY, GraphRoute.ANSWER_ONLY, GraphRoute.FREEZE}
````

Create `tests/plan_q/test_migration_0015.py`:

````python
"""Revision 0015 without a database (T20; SA:434, SA:559-562; R122).

Catches: a frozen copy of the saver's DDL that drifts from the installed langgraph-checkpoint-postgres (the worker's
saver would then meet tables it does not expect); a `CREATE INDEX CONCURRENTLY` left in (it cannot run in Alembic's
transaction); a missing version record (a later `setup()` would re-run the DDL); a checkpoint table granted to any
role but the worker, or the worker without DML; and a downgrade that leaves the schema behind.
"""

import re
from typing import Any

import pytest
from langgraph.checkpoint.postgres.base import BasePostgresSaver
from ops_core import privileges

from tests.plan_l.test_migration_0011 import revision, statements


def rev0015() -> Any:
    return revision("0015_checkpoints")


def flat(statement: str) -> str:
    return " ".join(statement.split())


def test_the_frozen_ddl_is_the_installed_savers_with_the_schema_named() -> None:
    frozen = [flat(s.replace("checkpoints.", "")) for s in rev0015().CHECKPOINT_DDL_0015]
    library = [flat(s.replace("CONCURRENTLY ", "")) for s in BasePostgresSaver.MIGRATIONS]
    assert frozen == library  # statement for statement, in the library's order (its version numbers)
    assert not any("CONCURRENTLY" in s for s in rev0015().CHECKPOINT_DDL_0015)
    # Every table the DDL touches is named in schema `checkpoints`, never left to the migration's search_path.
    named = re.findall(r"(?:TABLE(?: IF NOT EXISTS)?|ON) (\S+?)[ (]", " ".join(rev0015().CHECKPOINT_DDL_0015))
    assert named and all(name.startswith("checkpoints.") for name in named), named


def test_upgrade_creates_the_schema_records_the_version_and_grants_the_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    module = rev0015()
    assert module.down_revision == "0014_run_manifests"
    ran = statements(module, "upgrade", monkeypatch)
    assert ran == module.statements()
    assert ran[:2] == [
        "CREATE SCHEMA checkpoints AUTHORIZATION migrator",
        "REVOKE ALL ON SCHEMA checkpoints FROM PUBLIC",
    ]
    assert "INSERT INTO checkpoints.checkpoint_migrations (v) VALUES " + ", ".join(f"({v})" for v in range(10)) in ran
    grants = [s for s in ran if s.startswith("GRANT")]
    assert grants == [
        "GRANT USAGE ON SCHEMA checkpoints TO worker",
        "GRANT SELECT, INSERT, DELETE, UPDATE ON checkpoints.checkpoints TO worker",
        "GRANT SELECT, INSERT, DELETE, UPDATE ON checkpoints.checkpoint_blobs TO worker",
        "GRANT SELECT, INSERT, DELETE, UPDATE ON checkpoints.checkpoint_writes TO worker",
    ]  # R122: nobody else; the api meets "permission denied for schema checkpoints"
    assert statements(module, "downgrade", monkeypatch) == ["DROP SCHEMA checkpoints CASCADE"]


def test_the_cells_are_the_matrix_and_only_the_worker_has_one() -> None:
    assert rev0015().CHECKPOINT_GRANTS_0015 == privileges.CHECKPOINT_GRANTS
    assert {role for cells in privileges.CHECKPOINT_GRANTS.values() for role in cells} == {"worker"}
    assert not set(privileges.CHECKPOINT_GRANTS) & set(privileges.GRANTS)  # outside the app schema's matrix
````

Edit 4 (`tests/plan_e/test_transitions_table.py`), replace:

````python
    "0012_asset_scope",
    "0013_embeddings",
    "0014_run_manifests",
    "tc_0001_test_clock",
)
assert all((VERSIONS / f"{n}.py").exists() for n in REVISIONS), REVISIONS
````

with:

````python
    "0012_asset_scope",
    "0013_embeddings",
    "0014_run_manifests",
    "0015_checkpoints",
    "tc_0001_test_clock",
)
assert all((VERSIONS / f"{n}.py").exists() for n in REVISIONS), REVISIONS
````

Edit 5 (`tests/plan_h/test_locking.py`), replace:

````python
def test_every_table_is_placed_exactly_once() -> None:
    ordered = {locking.table_of(entry) for entry in locking.LOCK_ORDER} - {None}
    groups = (ordered, set(locking.OWN_UNIT), set(locking.NEVER_LOCKED))
    for table in privileges.GRANTS:
        assert sum(table in group for group in groups) == 1, table
    named = ordered | locking.OWN_UNIT | locking.NEVER_LOCKED
    assert named - set(privileges.GRANTS) <= locking.NOT_YET_CREATED, sorted(named - set(privileges.GRANTS))


def test_the_order_starts_with_the_advisory_locks_and_ends_with_the_record() -> None:
````

with:

````python
def test_every_table_is_placed_exactly_once() -> None:
    ordered = {locking.table_of(entry) for entry in locking.LOCK_ORDER} - {None}
    groups = (ordered, set(locking.OWN_UNIT), set(locking.NEVER_LOCKED))
    tables = set(privileges.GRANTS) | set(privileges.CHECKPOINT_GRANTS)  # T20: the checkpoint schema's tables too
    for table in tables:
        assert sum(table in group for group in groups) == 1, table
    named = ordered | locking.OWN_UNIT | locking.NEVER_LOCKED
    assert named - tables <= locking.NOT_YET_CREATED, sorted(named - tables)


def test_the_order_starts_with_the_advisory_locks_and_ends_with_the_record() -> None:
````

Edit 6 (`tests/plan_j/test_allowlist.py`), replace:

````python

def test_the_read_jobs_run_where_the_worker_calls_mcp_read() -> None:
    assert JOB_RULES[JobType.INVESTIGATE].run_states == {RunState.QUEUED, RunState.RETRIEVING, RunState.DRAFTING}
    assert JOB_RULES[JobType.RESUME_INPUT].run_states == {RunState.AWAITING_INPUT, RunState.QUEUED}
    assert {JOB_RULES[t].server for t in (JobType.INVESTIGATE, JobType.RESUME_INPUT)} == {Server.READ}


````

with:

````python

def test_the_read_jobs_run_where_the_worker_calls_mcp_read() -> None:
    assert JOB_RULES[JobType.INVESTIGATE].run_states == {RunState.QUEUED, RunState.RETRIEVING, RunState.DRAFTING}
    assert JOB_RULES[JobType.RESUME_INPUT].run_states == {  # T20: on through retrieval and drafting (erratum 127)
        RunState.AWAITING_INPUT,
        RunState.QUEUED,
        RunState.RETRIEVING,
        RunState.DRAFTING,
    }
    assert {JOB_RULES[t].server for t in (JobType.INVESTIGATE, JobType.RESUME_INPUT)} == {Server.READ}


````

Run `PYTHONUTF8=1 uv run python -m pytest tests/plan_q -q -p no:cacheprovider < /dev/null` → RED, `2 errors during
collection`: `ImportError: cannot import name 'GRAPH_ROUTES' from 'ops_core.routing'` (test_graph_table.py) and an
`AssertionError` listing the revisions (`tests/plan_e/test_transitions_table.py` names `0015_checkpoints`, which does
not exist yet).

- [ ] **Step 2: The table, the helpers, the job rule, the matrix rows and the revision**

Edit 7 (`core/src/ops_core/routing.py`), replace:

````python

Routing is deterministic-first: model output may hint, never select (SA:362, SA:375). The admission table (T12) is
`ADMISSION_RULES`, evaluated first match wins over facts the API gathered inside its admission unit; it is pure, so
a test walks every row (R129). The graph table arrives with T20 and the model table with T19; this module fixes the
vocabularies so every table, schema and event spells them the same way.

Text versus fields (BS:297, Plan G ruling 12): structured fields win only when the text agrees with them, so a
small deterministic parser reads asset ids and "last N seconds/minutes/hours/days/weeks/fortnights/months/years"
````

with:

````python

Routing is deterministic-first: model output may hint, never select (SA:362, SA:375). The admission table (T12) is
`ADMISSION_RULES`, evaluated first match wins over facts the API gathered inside its admission unit; it is pure, so
a test walks every row (R129). The graph table (T20) is `GRAPH_ROUTES`, in the same style over the worker graph's
`GraphKey` (SA:377's seven dimensions); the worker builds `route_request`'s conditional edges from it, so the table is
the only place a route is chosen. The model table is T19's; this module fixes the vocabularies so every table, schema
and event spells them the same way.

Text versus fields (BS:297, Plan G ruling 12): structured fields win only when the text agrees with them, so a
small deterministic parser reads asset ids and "last N seconds/minutes/hours/days/weeks/fortnights/months/years"
````

Edit 8 (`core/src/ops_core/routing.py`), replace:

````python
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ops_core.contracts import MessageKind


class AdmissionRoute(StrEnum):
````

with:

````python
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ops_core.contracts import MessageKind
from ops_core.states import TERMINAL_STATES, AttemptState, Intent, RunState


class AdmissionRoute(StrEnum):
````

Edit 9 (`core/src/ops_core/routing.py`), replace:

````python
    return _first(REPLY_RULES, facts, resolution_for(facts))


class RunManifest(BaseModel):
    """What produced a run's draft: route, model digest, prompt and corpus versions (AM-80; written by T19)."""

````

with:

````python
    return _first(REPLY_RULES, facts, resolution_for(facts))


class Evidence(StrEnum):
    """ "Evidence sufficient?" (SA:377) as the graph knows it: not judged yet in this graph run, or the code rule's
    verdict (`ops_worker.evidence.sufficient`)."""

    UNKNOWN = "unknown"
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"


class DraftKind(StrEnum):
    """ "Validated draft kind" (SA:377): the draft after structural validation, an abstention with a question being
    its own kind because it routes to `clarify` (SA:147); NONE before a draft exists in this graph run."""

    NONE = "none"
    PROPOSAL = "proposal"
    ANSWER = "answer"
    ABSTAIN = "abstain"
    QUESTION = "question"


@dataclass(frozen=True)
class GraphKey:
    """What `route_request` routes on, SA:377's seven dimensions in its order. Every value is the worker's own reading
    of authoritative state or of a validated draft; nothing here is model text (SA:362)."""

    state: RunState
    intent: Intent
    context_resolved: bool
    evidence: Evidence
    draft_kind: DraftKind
    decision_present: bool
    attempt_state: AttemptState | None  # the latest action attempt's state; None before a grant (AM-13)


@dataclass(frozen=True)
class GraphRule:
    """One row of the graph table: the run states it covers, the other dimensions it requires (None: any value), and
    the route. The first row that matches decides, as in `ADMISSION_RULES`."""

    name: str
    states: frozenset[RunState]
    route: GraphRoute
    intent: Intent | None = None
    context_resolved: bool | None = None
    evidence: Evidence | None = None
    draft_kind: DraftKind | None = None
    decision_present: bool | None = None
    attempt_states: frozenset[AttemptState | None] | None = None

    def matches(self, key: GraphKey) -> bool:
        """True when every dimension the row names has the key's value."""
        return (
            key.state in self.states
            and self.intent in (None, key.intent)
            and self.context_resolved in (None, key.context_resolved)
            and self.evidence in (None, key.evidence)
            and self.draft_kind in (None, key.draft_kind)
            and self.decision_present in (None, key.decision_present)
            and (self.attempt_states is None or key.attempt_state in self.attempt_states)
        )


_RS = RunState
_PRE_DRAFT: Final = frozenset({_RS.RETRIEVING, _RS.DRAFTING})
# The rows the worker can reach (Plan Q ruling 2), first match wins. "Context resolved?" is decided in retrieval
# (contract erratum 4): an asset the asset service does not know abstains, because a reply cannot change the run's
# fixed asset (SA:154). A proposal on an answer_only run matches no row: validation refuses it before the router sees
# it (`draft_validation`, SA:453), and should one ever arrive the graph run fails instead of freezing it. A run whose
# held evidence was lost (a new process resumed it) retrieves again before it drafts (BS:423).
GRAPH_ROUTES: Final[tuple[GraphRule, ...]] = (
    GraphRule("queued", frozenset({_RS.QUEUED}), GraphRoute.RETRIEVE),
    GraphRule("waiting_for_input", frozenset({_RS.AWAITING_INPUT}), GraphRoute.CLARIFY),
    GraphRule("context_missing", _PRE_DRAFT, GraphRoute.ABSTAIN, context_resolved=False),
    GraphRule("evidence_insufficient", _PRE_DRAFT, GraphRoute.ABSTAIN, evidence=Evidence.INSUFFICIENT),
    GraphRule("evidence_unread", _PRE_DRAFT, GraphRoute.RETRIEVE, evidence=Evidence.UNKNOWN),
    GraphRule(
        "draft", frozenset({_RS.DRAFTING}), GraphRoute.DRAFT, evidence=Evidence.SUFFICIENT, draft_kind=DraftKind.NONE
    ),
    GraphRule(
        "freeze",
        frozenset({_RS.DRAFTING}),
        GraphRoute.FREEZE,
        intent=Intent.INVESTIGATE,
        draft_kind=DraftKind.PROPOSAL,
    ),
    GraphRule("answer", frozenset({_RS.DRAFTING}), GraphRoute.ANSWER_ONLY, draft_kind=DraftKind.ANSWER),
    GraphRule("question", frozenset({_RS.DRAFTING}), GraphRoute.CLARIFY, draft_kind=DraftKind.QUESTION),
    GraphRule("abstention", frozenset({_RS.DRAFTING}), GraphRoute.ABSTAIN, draft_kind=DraftKind.ABSTAIN),
    GraphRule(
        "awaiting_decision", frozenset({_RS.AWAITING_APPROVAL}), GraphRoute.AWAIT_DECISION, decision_present=False
    ),
    GraphRule(
        "approved",
        frozenset({_RS.APPROVED}),
        GraphRoute.EXECUTE,
        decision_present=True,
        attempt_states=frozenset({None}),
    ),
    # The execute job's re-send after a lost reply (Plan E ruling 6): the same action id, never a new grant.
    GraphRule(
        "executing",
        frozenset({_RS.EXECUTING}),
        GraphRoute.EXECUTE,
        decision_present=True,
        attempt_states=frozenset({AttemptState.INTENT, AttemptState.SENT, AttemptState.ABORT_REQUESTED}),
    ),
    GraphRule("outcome_unknown", frozenset({_RS.OUTCOME_UNKNOWN, _RS.ESCALATED}), GraphRoute.RECOVER),
    GraphRule("settled", TERMINAL_STATES | {_RS.BLOCKED_REVIEW}, GraphRoute.PUBLISH),
)


def route_graph(key: GraphKey) -> GraphRoute:
    """The graph router's decision (`route_request`, SA:377).

    Raises:
        LookupError: no row matches; the graph run fails rather than guess (a test enumerates the keys the worker
            produces and walks every row, R129).
    """
    for rule in GRAPH_ROUTES:
        if rule.matches(key):
            return rule.route
    raise LookupError(f"no graph rule matched state {key.state.value} with draft kind {key.draft_kind.value}")


class RunManifest(BaseModel):
    """What produced a run's draft: route, model digest, prompt and corpus versions (AM-80; written by T19)."""

````

Edit 10 (`core/src/ops_core/persistence.py`), replace:

````python
    )


async def finish_job(conn: Conn, job_id: UUID) -> None:
    """Mark a claimed job done."""
    await conn.execute("UPDATE app.jobs SET done_at = app.current_time() WHERE id = %s", (job_id,))
````

with:

````python
    )


async def run_manifest_exists(conn: Conn, run_id: UUID) -> bool:
    """True when the run has its manifest (T20: a run that retrieves again after a clarification keeps the one it
    has, Plan Q ruling 13 and erratum 125; whether a revision records its own is T21's)."""
    cur = await conn.execute("SELECT 1 FROM app.run_manifests WHERE run_id = %s", (run_id,))
    return await cur.fetchone() is not None


@dataclass(frozen=True)
class GraphFacts:
    """The authoritative run facts the worker graph routes on (SA:377) and the checkpoint it last stored (SA:211)."""

    state: RunState
    intent: Intent
    decision_present: bool
    attempt_state: AttemptState | None
    checkpoint_id: str | None


async def graph_facts(conn: Conn, run_id: UUID) -> GraphFacts:
    """The run's state, intent, whether its active proposal has a decision, its latest action attempt state and its
    stored checkpoint id, read without a lock under the caller's tenant unit (the worker's SELECT grants, AM-20.2).

    Raises:
        NotFound: no such run for the unit's tenant.
    """
    cur = await conn.execute(
        "SELECT r.state, r.intent, r.checkpoint_id,"
        " EXISTS (SELECT 1 FROM app.decisions d WHERE d.proposal_id = r.active_proposal_id) AS decided,"
        " (SELECT s.state FROM app.action_attempt_state s JOIN app.execution_grant g ON g.action_id = s.action_id"
        "  WHERE g.run_id = r.run_id ORDER BY s.attempt_no DESC, s.seq DESC LIMIT 1) AS attempt_state"
        " FROM app.runs r WHERE r.run_id = %s",
        (run_id,),
    )
    row = await cur.fetchone()
    if row is None:
        raise NotFound("run not found")
    attempt = row["attempt_state"]
    return GraphFacts(
        RunState(row["state"]),
        Intent(row["intent"]),
        bool(row["decided"]),
        None if attempt is None else AttemptState(attempt),
        row["checkpoint_id"],
    )


async def store_checkpoint_id(conn: Conn, run_id: UUID, checkpoint_id: str) -> None:
    """`runs.checkpoint_id` := the checkpoint LangGraph confirmed (SA:211), under the worker's column grant (AM-20.2).
    The caller's unit sets the tenant and opens with `fenced`, so only the current lease holder can move it.

    Raises:
        NotFound: no such run for the unit's tenant.
    """
    cur = await conn.execute("UPDATE app.runs SET checkpoint_id = %s WHERE run_id = %s", (checkpoint_id, run_id))
    if cur.rowcount != 1:
        raise NotFound("run not found")


async def run_events(conn: Conn, run_id: UUID, type: EventType) -> list[tuple[UUID, dict[str, Any]]]:
    """The run's events of one type as (event_id, payload), in sequence order, under the caller's tenant unit."""
    cur = await conn.execute(
        "SELECT event_id, payload FROM app.events WHERE run_id = %s AND type = %s ORDER BY sequence",
        (run_id, type.value),
    )
    return [(UUID(str(row["event_id"])), dict(row["payload"])) for row in await cur.fetchall()]


async def message_text(conn: Conn, message_id: UUID) -> str:
    """One stored message's text under the caller's tenant unit (the worker reads, never writes, messages).

    Raises:
        NotFound: no such message for the unit's tenant.
    """
    cur = await conn.execute("SELECT text FROM app.messages WHERE message_id = %s", (message_id,))
    row = await cur.fetchone()
    if row is None:
        raise NotFound("message not found")
    return str(row["text"])


async def finish_job(conn: Conn, job_id: UUID) -> None:
    """Mark a claimed job done."""
    await conn.execute("UPDATE app.jobs SET done_at = app.current_time() WHERE id = %s", (job_id,))
````

Edit 11 (`core/src/ops_core/jobs.py`), replace:

````python
    JobType.RESUME_INPUT: JobRule(
        JobType.RESUME_INPUT,
        _READ,
        frozenset({_S.AWAITING_INPUT, _S.QUEUED}),
        Server.READ,
        ("api",),
        "run_id:clarification_event_id",
````

with:

````python
    JobType.RESUME_INPUT: JobRule(
        JobType.RESUME_INPUT,
        _READ,
        # T20 (Plan Q ruling 7, erratum 127): the job that resumes a clarified run carries it on through retrieval and
        # drafting under the same lease, so its read handle works in those states too, as an investigate job's does.
        frozenset({_S.AWAITING_INPUT, _S.QUEUED, _S.RETRIEVING, _S.DRAFTING}),
        Server.READ,
        ("api",),
        "run_id:clarification_event_id",
````

Edit 12 (`core/src/ops_core/privileges.py`), replace:

````python
    "model_permit",
)
AUDIT_TABLES: Final = ("run_state_history", "action_attempt_state", "events")  # AM-20 principle 2

# The policy expression (SA:446's NULLIF form, not SA:512's bare cast: '' raises 22P02, measured in the spike), and
# the text PostgreSQL stores for it in pg_policies.qual, which R106 compares.
````

with:

````python
    "model_permit",
)
AUDIT_TABLES: Final = ("run_state_history", "action_attempt_state", "events")  # AM-20 principle 2
# T20 (revision 0015; SA:434, SA:559-562; R122): LangGraph's checkpoint tables, in schema `checkpoints` outside the
# `app` matrix above. Only the worker's saver reads and writes them, by thread id; no other role has any privilege on
# the schema, and there is no RLS (they are not tenant rows, erratum 123). `checkpoint_migrations` is the library's
# own bookkeeping, written by the revision only, so it has no cell.
CHECKPOINT_SCHEMA: Final = "checkpoints"
CHECKPOINT_GRANTS: Final[dict[str, dict[str, Grant]]] = {
    table: {"worker": Grant(sel=True, ins=True, upd=True, dele=True)}
    for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes")
}

# The policy expression (SA:446's NULLIF form, not SA:512's bare cast: '' raises 22P02, measured in the spike), and
# the text PostgreSQL stores for it in pg_policies.qual, which R106 compares.
````

Edit 13 (`core/src/ops_core/locking.py`), replace:

````python
    "idempotency_request",  # written last, before commit (SA:188)
)
OWN_UNIT: Final = frozenset(
    {"model_permit", "sessions", "login_state", "logout_jti", "test_clock", "tenants", "run_directory"}
)
# T17 (revision 0011): the corpus is append-only; ingestion inserts and the search reads, and neither locks a row
# explicitly. An insert does take FOR KEY SHARE on the existing parent row its foreign key names (a new
````

with:

````python
    "idempotency_request",  # written last, before commit (SA:188)
)
OWN_UNIT: Final = frozenset(
    {
        "model_permit",
        "sessions",
        "login_state",
        "logout_jti",
        "test_clock",
        "tenants",
        "run_directory",
        # T20 (revision 0015): LangGraph's checkpoint tables. The saver writes them on its own autocommit connection,
        # each write its own transaction (`AsyncPostgresSaver.aput`, `aput_writes`), never inside an application unit,
        # and no application unit touches them, so they can never close a cycle with a run table (Plan Q ruling 5).
        "checkpoints",
        "checkpoint_blobs",
        "checkpoint_writes",
    }
)
# T17 (revision 0011): the corpus is append-only; ingestion inserts and the search reads, and neither locks a row
# explicitly. An insert does take FOR KEY SHARE on the existing parent row its foreign key names (a new
````

Edit 14 (`core/src/ops_core/locking.py`), replace:

````python
    "worker failure (transition_run)": ("run_lease", "runs"),
    "worker drafting start (transition_run, run manifest)": ("run_lease", "runs"),  # T19: the manifest's FK share
    "worker draft and freeze": ("run_lease", "runs"),
    "worker execute start": ("run_lease", "runs", "jobs:finish"),
    "worker mark_unknown": ("run_lease", "runs", "invocation_context"),
    # T14 (Plan I ruling 10): the release also makes the run's other deferred jobs due; that UPDATE picks its rows
````

with:

````python
    "worker failure (transition_run)": ("run_lease", "runs"),
    "worker drafting start (transition_run, run manifest)": ("run_lease", "runs"),  # T19: the manifest's FK share
    "worker draft and freeze": ("run_lease", "runs"),
    # T20: the graph's units. The checkpoint id is the worker's column UPDATE on its own run row (SA:211); the answer,
    # the clarification and the abstention insert their drafts row (a key share on the run row the same unit's
    # transition_run already holds) and transition the run; the stale-reply failure walks three transitions in one unit.
    "worker checkpoint id (store_checkpoint_id)": ("run_lease", "runs"),
    "worker answer, question or abstention (drafts, transition_run)": ("run_lease", "runs"),
    "worker unresumable run (fail_from)": ("run_lease", "runs"),
    "worker execute start": ("run_lease", "runs", "jobs:finish"),
    "worker mark_unknown": ("run_lease", "runs", "invocation_context"),
    # T14 (Plan I ruling 10): the release also makes the run's other deferred jobs due; that UPDATE picks its rows
````

Edit 15 (`core/src/ops_core/locking.py`), replace:

````python
}
OWN_UNITS: Final[dict[str, tuple[str, ...]]] = {
    "worker model permit (take, release)": ("model_permit",),
    "api session touch and revocation": ("sessions",),
    "api login state consumption": ("login_state",),
    "api logout jti record": ("logout_jti",),
````

with:

````python
}
OWN_UNITS: Final[dict[str, tuple[str, ...]]] = {
    "worker model permit (take, release)": ("model_permit",),
    "worker checkpoint saver (aput, aput_writes)": ("checkpoints", "checkpoint_blobs", "checkpoint_writes"),
    "api session touch and revocation": ("sessions",),
    "api login state consumption": ("login_state",),
    "api logout jti record": ("logout_jti",),
````

Create `migrations/app/versions/0015_checkpoints.py`:

````python
"""Schema `checkpoints` and LangGraph's checkpoint tables (T20; AM-12 SA:209-218, AM-20.7 SA:559-562; R122).

Revision ID: 0015_checkpoints
Revises: 0014_run_manifests

The worker's graph persists through langgraph-checkpoint-postgres 3.1.2's `AsyncPostgresSaver`. Its SQL names its
tables without a schema (it has no schema parameter, SA:559), so the tables live in a schema of their own and the
worker's saver connection sets `search_path=checkpoints,pg_temp` (`ops_worker.graph.build.open_saver`).

SA:559 has the migrator run `PostgresSaver.setup()`. This revision runs the same statements inside the migration
instead (erratum 126): `BasePostgresSaver.MIGRATIONS` (`langgraph/checkpoint/postgres/base.py:43-91` in 3.1.2),
frozen below with each table named in schema `checkpoints` and `CONCURRENTLY` dropped from the three index statements,
because Alembic runs every revision in one transaction and `CREATE INDEX CONCURRENTLY` cannot run inside one (the
tables are empty, so the plain index build waits on nobody). It then records the ten statement numbers in
`checkpoint_migrations`, as `setup()` does, so a later `setup()` finds nothing to apply.
`tests/plan_q/test_migration_0015.py` compares the frozen list with the installed package's.

Cells (SA:434, R122): `worker` USAGE on the schema and SELECT, INSERT, UPDATE and DELETE on the three tables the saver
reads and writes; nobody else anything, so the api is refused at the schema. `checkpoint_migrations` is written here
and read by nobody at runtime. No RLS: checkpoint rows are not tenant rows (SA:510 does not list them), and only the
worker reads them, by thread id (erratum 123). Owner `migrator`, as every app table.

The downgrade drops the schema with its tables and rows.
"""

from alembic import op
from ops_core import privileges

revision = "0015_checkpoints"
down_revision = "0014_run_manifests"
branch_labels = None
depends_on = None

_ALL = privileges.Grant(sel=True, ins=True, upd=True, dele=True)
CHECKPOINT_GRANTS_0015: dict[str, dict[str, privileges.Grant]] = {
    "checkpoints": {"worker": _ALL},
    "checkpoint_blobs": {"worker": _ALL},
    "checkpoint_writes": {"worker": _ALL},
}
CHECKPOINT_DDL_0015 = (
    "CREATE TABLE IF NOT EXISTS checkpoints.checkpoint_migrations ( v INTEGER PRIMARY KEY );",
    (
        "CREATE TABLE IF NOT EXISTS checkpoints.checkpoints ( thread_id TEXT NOT NULL, checkpoint_ns TEXT NOT NULL"
        " DEFAULT '', checkpoint_id TEXT NOT NULL, parent_checkpoint_id TEXT, type TEXT, checkpoint JSONB NOT NULL,"
        " metadata JSONB NOT NULL DEFAULT '{}', PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id) );"
    ),
    (
        "CREATE TABLE IF NOT EXISTS checkpoints.checkpoint_blobs ( thread_id TEXT NOT NULL, checkpoint_ns TEXT NOT"
        " NULL DEFAULT '', channel TEXT NOT NULL, version TEXT NOT NULL, type TEXT NOT NULL, blob BYTEA, PRIMARY KEY"
        " (thread_id, checkpoint_ns, channel, version) );"
    ),
    (
        "CREATE TABLE IF NOT EXISTS checkpoints.checkpoint_writes ( thread_id TEXT NOT NULL, checkpoint_ns TEXT NOT"
        " NULL DEFAULT '', checkpoint_id TEXT NOT NULL, task_id TEXT NOT NULL, idx INTEGER NOT NULL, channel TEXT"
        " NOT NULL, type TEXT, blob BYTEA NOT NULL, PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id,"
        " idx) );"
    ),
    "ALTER TABLE checkpoints.checkpoint_blobs ALTER COLUMN blob DROP not null;",
    "SELECT 1;",
    "CREATE INDEX IF NOT EXISTS checkpoints_thread_id_idx ON checkpoints.checkpoints(thread_id);",
    "CREATE INDEX IF NOT EXISTS checkpoint_blobs_thread_id_idx ON checkpoints.checkpoint_blobs(thread_id);",
    "CREATE INDEX IF NOT EXISTS checkpoint_writes_thread_id_idx ON checkpoints.checkpoint_writes(thread_id);",
    "ALTER TABLE checkpoints.checkpoint_writes ADD COLUMN IF NOT EXISTS task_path TEXT NOT NULL DEFAULT '';",
)
TABLES_0015 = ("checkpoint_migrations", "checkpoints", "checkpoint_blobs", "checkpoint_writes")


def statements() -> list[str]:
    """Every statement of the upgrade, in order (the unit test reads the same list)."""
    out = ["CREATE SCHEMA checkpoints AUTHORIZATION migrator", "REVOKE ALL ON SCHEMA checkpoints FROM PUBLIC"]
    out.extend(CHECKPOINT_DDL_0015)
    numbers = ", ".join(f"({v})" for v in range(len(CHECKPOINT_DDL_0015)))
    out.append(f"INSERT INTO checkpoints.checkpoint_migrations (v) VALUES {numbers}")
    out.extend(f"ALTER TABLE checkpoints.{table} OWNER TO migrator" for table in TABLES_0015)
    # No REVOKE ALL per table, unlike 0011-0014: the schema is new, PUBLIC is revoked at the schema above and no
    # default privileges exist to revoke; `privileges.grant_statements` is fixed to schema `app`.
    out.append("GRANT USAGE ON SCHEMA checkpoints TO worker")
    for table, cells in CHECKPOINT_GRANTS_0015.items():
        for role, grant in cells.items():
            names = [n for n, flag in (("SELECT", grant.sel), ("INSERT", grant.ins), ("DELETE", grant.dele)) if flag]
            if grant.upd is True:
                names.append("UPDATE")
            out.append(f"GRANT {', '.join(names)} ON checkpoints.{table} TO {role}")
    return out


def upgrade() -> None:
    """The schema, the saver's tables and their recorded version, the owner, then the worker's cells."""
    for statement in statements():
        op.execute(statement)


def downgrade() -> None:
    """Back to 0014."""
    op.execute("DROP SCHEMA checkpoints CASCADE")
````

Then regenerate the contract set: `uv run python -m scripts.build_schemas < /dev/null` → `schemas/: 26 schema
documents (20 contracts, 6 tool inputs); 91 examples (36 valid, 55 invalid); index.json version 1.3.3`, and only
`schemas/job.schema.json` changes (`resume_input`'s `run_states` gains RETRIEVING and DRAFTING).

Run `PYTHONUTF8=1 uv run python -m pytest tests/plan_q tests/plan_e/test_transitions_table.py
tests/plan_h/test_locking.py tests/plan_j/test_allowlist.py -q -p no:cacheprovider < /dev/null` → `105 passed`.

- [ ] **Step 3: Gates and commit**

`git add` the three new files; dev `CHECK: GREEN`, `1667 passed, 222 skipped`; `verify_handoff.py` exit 0.

```bash
git add core/src/ops_core schemas/job.schema.json migrations/app/versions/0015_checkpoints.py tests/plan_q \
  tests/plan_e/test_transitions_table.py tests/plan_h/test_locking.py tests/plan_j/test_allowlist.py
git commit -m "feat: the graph route table, the checkpoint schema (revision 0015) and the graph's persistence (T20)"
```

---
### Task 3: The evidence bundle, the sufficiency rule and the read failures

**Files:**
- Create: `worker/src/ops_worker/evidence.py`, `tests/plan_q/fixtures.py`, `tests/plan_q/test_evidence.py`
- Modify: `worker/src/ops_worker/drafting.py`, `ollama_drafting.py`, `mcp.py`, `mcp-read/src/ops_mcp_read/assets.py`
  (docstring), `tests/plan_j/test_worker_azp.py` (the request's fields)

**Requirements:** rulings 3, 10, 11; SA:377, BS:419, BS:551-552, BS:562; erratum 122; Plan P's M10 debt (the payload
states `answer_only`).

**Interfaces:**
- Produces: `ops_worker.evidence.Bundle`, `sufficient(status, search)`, `observations(status, alerts)`, `FRESHNESS`,
  `ALERTS_SHOWN`; `ops_worker.drafting.Observation`, `DraftRequest.observations`; `ops_worker.ollama_drafting.
  ANSWER_ONLY_NOTE`; `ops_worker.mcp.McpCallFailed(code=, retryable=)`, `UNAUTHENTICATED`, `TRANSPORT`,
  `transport_failure(tool, statuses)`.

- [ ] **Step 1: The tests first**

Create `tests/plan_q/fixtures.py`:

````python
"""Tool results of the two asset reads, as mcp-read returns them (T20): the graph's retrieval reads the run's asset
status and alerts before the procedure search (Plan Q ruling 3). Every instant is the same database instant, so
the evidence is fresh by the code rule (`ops_worker.evidence`) beside `tests/plan_h/test_worker_units.SEARCH`.
"""

AT = "2026-10-08T12:00:00Z"
STATUS = {
    "tool_name": "get_asset_status",
    "status": "ok",
    "observed_at": AT,
    "truncated": False,
    "data": {"asset_id": "A17", "state": "warning", "revision": 3, "observed_at": AT, "data_source": "synthetic"},
    "error": None,
}
ALERTS = {
    "tool_name": "get_recent_alerts",
    "status": "ok",
    "observed_at": AT,
    "truncated": False,
    "data": {
        "asset_id": "A17",
        "start_at": "2026-10-07T12:00:00Z",
        "end_at": AT,
        "alerts": [
            {
                "alert_id": "6d2f3c1e-1b7a-4f55-9d6e-0a7b8c9d0e1f",
                "asset_id": "A17",
                "occurred_at": "2026-10-08T09:00:00Z",
                "code": "TEMP_HIGH",
                "message": "Bearing temperature above the warning threshold.",
                "revision": 1,
            }
        ],
        "next_cursor": None,
    },
    "error": None,
}
````

Create `tests/plan_q/test_evidence.py`:

````python
"""The evidence bundle's code rule, what reaches the model, and how a failed read is told apart (T20; SA:377; BS:419,
BS:552; Plan Q ruling 3), without a database or a network.

Catches: a sufficiency verdict that is a judgement rather than SA:377's rule (an `unavailable` status, a stale status,
a stale or empty search counted as evidence); an alert list that reaches the model unbounded or without its
truncation notice; a status or alert that the model could cite; an answer_only run whose payload does not say so; a
fake route that proposes on an answer_only run; and a 401 from the read server that the client cannot tell apart from
a transport failure (one is final, the other worth a retry).
"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
import pytest
from ops_core.routing import ModelRoute
from ops_worker import evidence
from ops_worker.drafting import DraftRequest, EvidenceItem, FakeDraftGenerator, Observation
from ops_worker.mcp import TRANSPORT, UNAUTHENTICATED, HttpMcpCaller, McpCallFailed
from ops_worker.ollama_drafting import ANSWER_ONLY_NOTE, payload

from tests.plan_h.test_worker_units import SEARCH
from tests.plan_q.fixtures import ALERTS, AT, STATUS

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def status(**data: Any) -> dict[str, Any]:
    return {**STATUS, "data": {**STATUS["data"], **data}}


def test_sufficiency_is_the_code_rule() -> None:
    assert evidence.sufficient(STATUS, SEARCH)
    assert not evidence.sufficient(status(state="unavailable"), SEARCH)  # observes nothing
    assert not evidence.sufficient(status(observed_at="2026-10-08T11:54:59Z"), SEARCH)  # 5 min 1 s old
    assert evidence.sufficient(status(observed_at="2026-10-08T11:55:00Z"), SEARCH)  # exactly at the bound
    assert not evidence.sufficient(STATUS, {**SEARCH, "data": {**SEARCH["data"], "results": []}})
    stale = [{**SEARCH["data"]["results"][0], "retrieved_at": "2026-10-08T11:00:00Z"}]
    assert not evidence.sufficient(STATUS, {**SEARCH, "data": {**SEARCH["data"], "results": stale}})


def test_alerts_are_bounded_newest_first_with_a_truncation_notice() -> None:
    alert = ALERTS["data"]["alerts"][0]
    many = [{**alert, "occurred_at": f"2026-10-08T0{h}:00:00Z", "code": f"C{h}"} for h in range(6)]
    seen = evidence.observations(STATUS, {**ALERTS, "data": {**ALERTS["data"], "alerts": many, "next_cursor": "n"}})
    assert [o.section for o in seen] == ["asset status", *["alert"] * evidence.ALERTS_SHOWN, "alerts not shown"]
    assert seen[1].excerpt.startswith("2026-10-08T05:00:00Z C5")  # newest first
    assert seen[-1].excerpt == "2 more alert records were not shown; further pages were not read"
    assert len(seen) - 1 + 3 <= 8  # BS:551: at most 8 references with the three procedure sections


def request(answer_only: bool) -> DraftRequest:
    shown = (Observation("asset status", "3", "warning at " + AT),)
    return DraftRequest("A17", "Is A17 fine?", NOW - timedelta(hours=24), NOW, answer_only, None, shown)


ITEM = EvidenceItem("ALPHA-INCIDENT:v2:review", "ALPHA-INCIDENT", "2", "review", "0" * 64, "text")


def test_the_payload_shows_observations_uncitable_and_says_answer_only() -> None:
    sent = payload(request(answer_only=True), [ITEM])
    assert sent["confirmed_request"] == f"Is A17 fine?\n\n{ANSWER_ONLY_NOTE}"
    assert sent["allowed_evidence_ids"] == ["ALPHA-INCIDENT:v2:review"]  # the status is not citable
    assert sent["permitted_evidence"][1] == {
        "document_id": "asset-sim",
        "version": "3",
        "section": "asset status",
        "excerpt": "warning at " + AT,
    }
    assert payload(request(answer_only=False), [ITEM])["confirmed_request"] == "Is A17 fine?"
    assert set(sent) == {
        "confirmed_request",
        "asset_id",
        "interval",
        "permitted_evidence",
        "allowed_evidence_ids",
        "requested_output_schema",
    }  # the starter's keys, unchanged (no new prompt version)


def test_the_fake_route_answers_an_answer_only_run_and_proposes_otherwise() -> None:
    fake = FakeDraftGenerator()
    assert fake.route is ModelRoute.FAKE
    assert asyncio.run(fake.generate(request(answer_only=True), [ITEM])).kind == "answer"
    assert asyncio.run(fake.generate(request(answer_only=False), [ITEM])).kind == "proposal"


def test_a_401_from_the_read_server_is_told_apart_from_a_transport_failure() -> None:
    class Token:
        async def token(self) -> str:
            return "workload-token"

    def answer(code: int) -> Any:
        return httpx2.MockTransport(lambda _request: httpx2.Response(code))

    async def call(code: int) -> McpCallFailed:
        caller = HttpMcpCaller(Token(), transport=answer(code))
        with pytest.raises(McpCallFailed) as failed:
            await caller.call("http://127.0.0.1:9/mcp", handle="h", tool="get_asset_status", arguments={})
        return failed.value

    refused, broken = asyncio.run(call(401)), asyncio.run(call(503))
    assert (refused.code, refused.retryable) == (UNAUTHENTICATED, False)
    assert (broken.code, broken.retryable) == (TRANSPORT, True)
````

Edit 16 (`tests/plan_j/test_worker_azp.py`), replace:

````python
import pytest
from ops_core import persistence
from ops_worker import handlers
from ops_worker.drafting import DraftRequest

from tests.plan_h.test_worker_units import JOB, RUN, Log, make, patch

````

with:

````python
import pytest
from ops_core import persistence
from ops_worker import handlers
from ops_worker.drafting import DraftRequest, Observation

from tests.plan_h.test_worker_units import JOB, RUN, Log, make, patch

````

Edit 17 (`tests/plan_j/test_worker_azp.py`), replace:

````python

def test_the_model_request_has_no_field_for_a_handle() -> None:
    # T19 added two worker-computed fields the payload never carries: `answer_only`, a bool (the router's verdict), and
    # `remaining_seconds`, a float (the run's budget left); neither can carry a handle.
    fields_now = [f.name for f in fields(DraftRequest)]
    assert fields_now == ["asset_id", "text", "start_at", "end_at", "answer_only", "remaining_seconds"]
````

with:

````python

def test_the_model_request_has_no_field_for_a_handle() -> None:
    # T19 added two worker-computed fields the payload never carries: `answer_only`, a bool (the router's verdict), and
    # `remaining_seconds`, a float (the run's budget left); neither can carry a handle. T20 added `observations`, the
    # worker's rendering of mcp-read's validated status and alert results (section, revision, excerpt strings): the
    # handle travels only in a request header and is never part of a tool result.
    fields_now = [f.name for f in fields(DraftRequest)]
    assert fields_now == [
        "asset_id",
        "text",
        "start_at",
        "end_at",
        "answer_only",
        "remaining_seconds",
        "observations",
    ]
    assert [f.name for f in fields(Observation)] == ["section", "version", "excerpt"]
````

Run `PYTHONUTF8=1 uv run python -m pytest tests/plan_q/test_evidence.py tests/plan_j/test_worker_azp.py -q -p
no:cacheprovider < /dev/null` → RED, `2 errors during collection`: `ImportError: cannot import name 'evidence' from
'ops_worker'` and `ImportError: cannot import name 'Observation' from 'ops_worker.drafting'`.

- [ ] **Step 2: The bundle, the payload, the fake's answer and the failure codes**

Edit 18 (`worker/src/ops_worker/drafting.py`), replace:

````python
BUDGET_SECONDS: Final = 90.0  # BS:555: both attempts together


@dataclass(frozen=True)
class DraftRequest:
    """What the model may know about the ask; no identity, credential or tool is part of it. Two fields are the
    worker's, never shown to the model: `answer_only`, the router's verdict that this run may not propose an incident
    (SA:153), and `remaining_seconds`, what the run's compute budget has left when drafting starts (BS:555; None when
    no run holds a budget, as in the evidence script)."""

    asset_id: str
    text: str
````

with:

````python
BUDGET_SECONDS: Final = 90.0  # BS:555: both attempts together


@dataclass(frozen=True)
class Observation:
    """An asset status or alert record from mcp-read (BS:419), rendered by the worker: the model reads it and can
    never cite it, because only procedure sections carry the hash a proposal's snapshot binds (`build_proposal`)."""

    section: str  # "asset status", "alert" or "alerts not shown"
    version: str  # asset-sim's revision of the record
    excerpt: str


@dataclass(frozen=True)
class DraftRequest:
    """What the model may know about the ask; no identity, credential or tool is part of it. `observations` are the
    run's asset status and alerts (T20). Two fields are the worker's, and the model learns only what the payload says
    of them: `answer_only`, the router's verdict that this run may not propose an incident (SA:153; the payload states
    it), and `remaining_seconds`, what the run's compute budget has left when drafting starts (BS:555; None when no run
    holds a budget, as in the evidence script)."""

    asset_id: str
    text: str
````

Edit 19 (`worker/src/ops_worker/drafting.py`), replace:

````python
    end_at: datetime
    answer_only: bool = False
    remaining_seconds: float | None = None


@dataclass(frozen=True)
````

with:

````python
    end_at: datetime
    answer_only: bool = False
    remaining_seconds: float | None = None
    observations: tuple[Observation, ...] = ()


@dataclass(frozen=True)
````

Edit 20 (`worker/src/ops_worker/drafting.py`), replace:

````python


class FakeDraftGenerator:
    """The deterministic route that exercises the control path without a model (BUILD_SPEC §1). `delay_seconds` makes
    it as slow as a real model call without blocking the event loop (R088's "> 30 s fake drafter"; tests only)."""

    route = ModelRoute.FAKE
    digest: str | None = None  # nothing to pin; the fake never reads data/model-pins.json
````

with:

````python


class FakeDraftGenerator:
    """The deterministic route that exercises the control path without a model (BUILD_SPEC §1): an answer for an
    answer_only run (SA:153, T20) and a proposal otherwise. `delay_seconds` makes it as slow as a real model call
    without blocking the event loop (R088's "> 30 s fake drafter"; tests only)."""

    route = ModelRoute.FAKE
    digest: str | None = None  # nothing to pin; the fake never reads data/model-pins.json
````

Edit 21 (`worker/src/ops_worker/drafting.py`), replace:

````python
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if not evidence:
            raise ValueError("a proposal draft needs at least one evidence item")
        cited = evidence[0]  # the highest-ranked section; deterministic because the search is
        hours = int((request.end_at - request.start_at).total_seconds() // 3600)
        return ModelDraft(
            kind="proposal",
            title=f"Review synthetic warnings on {request.asset_id}",
````

with:

````python
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if not evidence:
            raise ValueError("a draft needs at least one evidence item")
        cited = evidence[0]  # the highest-ranked section; deterministic because the search is
        hours = int((request.end_at - request.start_at).total_seconds() // 3600)
        if request.answer_only:
            return ModelDraft(
                kind="answer",
                title=f"Answer about {request.asset_id}",
                summary=(
                    f"For {request.asset_id} over the {hours}-hour window, procedure {cited.document_id} "
                    f"v{cited.version} ({cited.section}) applies: {cited.excerpt[:200]}"
                ),
                evidence_refs=[cited.evidence_id],
                assumptions=["Synthetic fixture data; no live equipment was observed."],
                limitations=[f"Answered by the fake model route ({PROMPT_VERSION}); the control path, not quality."],
            )
        return ModelDraft(
            kind="proposal",
            title=f"Review synthetic warnings on {request.asset_id}",
````

Create `worker/src/ops_worker/evidence.py`:

````python
"""The evidence bundle the graph's retrieval node gathers (BS:419) and the code rule that judges it (SA:377).

The bundle holds what the model will read: the confirmed request (the run's message and any clarification replies),
the retrieved procedure sections and the asset status and alert records as `Observation`s, and the run's manifest. It
lives in the worker's memory for one graph run and never in graph state, a checkpoint or an event (SA:496, SA:563,
R091); a graph run that resumes without it retrieves again, which also re-checks access before anything reaches a
model (BS:423).

"Evidence sufficient?" is SA:377's rule and nothing more (Plan Q ruling 3, erratum 122): at least one permitted status
observation (`normal` or `warning`; `unavailable` observes nothing) and at least one effective procedure section,
all within `FRESHNESS` of the instant mcp-read answered at. The search's own minimum rank (0.25, T17) is v1's
relevance criterion; erratum 102's residue stays measured, not closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

from ops_core.routing import RunManifest

from ops_worker.drafting import EvidenceItem, Observation

# SA:462's asset freshness, the bound the grant applies at execution; the same window keeps a draft from resting on
# a status the grant would refuse. Every instant compared is the database's (`app.current_time()` via mcp-read).
FRESHNESS: Final = timedelta(minutes=5)
# BS:551 allows 8 references in the bundle: up to 3 procedure sections, the status and at most 4 alerts, and a count
# of the alerts left out (BS:419's "truncation notice").
ALERTS_SHOWN: Final = 4
OBSERVED: Final = frozenset({"normal", "warning"})


@dataclass(frozen=True)
class Bundle:
    """What one graph run retrieved for its draft; held in memory only (see the module docstring)."""

    text: str
    procedures: list[EvidenceItem]
    observations: tuple[Observation, ...]
    manifest: RunManifest


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value)  # Python 3.11+ reads the trailing Z


def observations(status: dict[str, Any], alerts: dict[str, Any]) -> tuple[Observation, ...]:
    """The status and alert records as the model reads them, newest alerts first, with a count of those left out."""
    data = status["data"]
    shown = [
        Observation("asset status", str(data["revision"]), f"{data['state']} at {data['observed_at']}"),
    ]
    rows = sorted(alerts["data"]["alerts"], key=lambda alert: str(alert["occurred_at"]), reverse=True)
    shown.extend(
        Observation("alert", str(a["revision"]), f"{a['occurred_at']} {a['code']}: {a['message']}")
        for a in rows[:ALERTS_SHOWN]
    )
    left, more = max(0, len(rows) - ALERTS_SHOWN), alerts["data"]["next_cursor"] is not None
    if left or more:
        notice = f"{left} more alert records were not shown" + ("; further pages were not read" if more else "")
        shown.append(Observation("alerts not shown", "0", notice))
    return tuple(shown)


def sufficient(status: dict[str, Any], search: dict[str, Any]) -> bool:
    """SA:377's code rule over the two `ok` tool results (never a model judgement)."""
    data = status["data"]
    if data["state"] not in OBSERVED:
        return False
    answered = _instant(status["observed_at"])
    if abs(answered - _instant(data["observed_at"])) > FRESHNESS:
        return False
    rows = search["data"]["results"]
    return bool(rows) and all(abs(_instant(row["retrieved_at"]) - answered) <= FRESHNESS for row in rows)
````

Edit 22 (`worker/src/ops_worker/ollama_drafting.py`), replace:

````python
NUM_CTX: Final = 16384
NUM_PREDICT: Final = 1000
WARM_UP_REQUEST: Final = "Warm-up call at worker start; no evidence is supplied, so abstain."


@dataclass(frozen=True)
````

with:

````python
NUM_CTX: Final = 16384
NUM_PREDICT: Final = 1000
WARM_UP_REQUEST: Final = "Warm-up call at worker start; no evidence is supplied, so abstain."
# Appended to an answer_only run's request (Plan Q ruling 10): the payload's keys and the v2 prompt stay as they are,
# and a proposal is still refused by validation if the model ignores the line.
ANSWER_ONLY_NOTE: Final = "Answer only; do not propose an incident."


@dataclass(frozen=True)
````

Edit 23 (`worker/src/ops_worker/ollama_drafting.py`), replace:

````python


def payload(request: DraftRequest, evidence: list[EvidenceItem]) -> dict[str, Any]:
    """The user message of the first pass, with the starter's keys (`handoff/prompts/incident-draft-v1.md`)."""
    return {
        "confirmed_request": request.text,
        "asset_id": request.asset_id,
        "interval": {"start_at": _instant(request.start_at), "end_at": _instant(request.end_at)},
        "permitted_evidence": [
            {
                "evidence_id": e.evidence_id,
                "document_id": e.document_id,
                "version": e.version,
                "section": e.section,
                "excerpt": e.excerpt,
            }
            for e in evidence
        ],
        "allowed_evidence_ids": [e.evidence_id for e in evidence],
        "requested_output_schema": draft_schema(),
````

with:

````python


def payload(request: DraftRequest, evidence: list[EvidenceItem]) -> dict[str, Any]:
    """The user message of the first pass, with the starter's keys (`handoff/prompts/incident-draft-v1.md`). The asset
    status and alerts follow the procedure sections in `permitted_evidence` without an evidence id, so they inform the
    draft and cannot be cited (T20, BS:419); an answer_only run's request says so (Plan P debt, M10)."""
    confirmed = f"{request.text}\n\n{ANSWER_ONLY_NOTE}" if request.answer_only else request.text
    return {
        "confirmed_request": confirmed,
        "asset_id": request.asset_id,
        "interval": {"start_at": _instant(request.start_at), "end_at": _instant(request.end_at)},
        "permitted_evidence": [
            *(
                {
                    "evidence_id": e.evidence_id,
                    "document_id": e.document_id,
                    "version": e.version,
                    "section": e.section,
                    "excerpt": e.excerpt,
                }
                for e in evidence
            ),
            *(
                {"document_id": "asset-sim", "version": o.version, "section": o.section, "excerpt": o.excerpt}
                for o in request.observations
            ),
        ],
        "allowed_evidence_ids": [e.evidence_id for e in evidence],
        "requested_output_schema": draft_schema(),
````

Edit 24 (`worker/src/ops_worker/mcp.py`), replace:

````python
in the same session, before the call, the server must advertise exactly the three read tools and the called tool's
committed input schema (`check_listing`); the answer must be at most 256 KiB, not error-flagged, a valid tool result
of that tool by `schemas/tool-result.schema.json` and `ok` (`read_result`). Anything else is McpCallFailed, which the
investigate handler records as FAILED "retrieval failed": nothing is assumed to have succeeded.
"""

from __future__ import annotations
````

with:

````python
in the same session, before the call, the server must advertise exactly the three read tools and the called tool's
committed input schema (`check_listing`); the answer must be at most 256 KiB, not error-flagged, a valid tool result
of that tool by `schemas/tool-result.schema.json` and `ok` (`read_result`). Anything else is McpCallFailed, which the
graph's retrieval node retries when it is transient and otherwise records as FAILED (T20): nothing is assumed to
have succeeded.
"""

from __future__ import annotations
````

Edit 25 (`worker/src/ops_worker/mcp.py`), replace:

````python


class McpCallFailed(Exception):
    """The call did not produce a tool result: transport, protocol or tool-level refusal, or a failed check."""


def failure_leaf(exc: BaseException) -> BaseException:
````

with:

````python


class McpCallFailed(Exception):
    """The call did not produce a tool result: transport, protocol or tool-level refusal, or a failed check.

    `code` and `retryable` say what the graph's retrieval node may do about it (T20, BS:552): a tool's error envelope
    carries both (`NOT_FOUND`, `UNAVAILABLE` and so on); a transport failure is `TRANSPORT` and retryable; a 401 to the
    worker's own token is `UNAUTHENTICATED` and not retryable, because another try would carry the same token."""

    def __init__(self, message: str, *, code: str | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


UNAUTHENTICATED: Final = "UNAUTHENTICATED"
TRANSPORT: Final = "TRANSPORT"


def transport_failure(tool: str, statuses: list[int]) -> McpCallFailed:
    """A failure below the tool result: a 401 among the session's HTTP answers is the worker's token refused (the SDK
    reports every non-2xx answer as the same MCPError, mcp 2.3.0 `streamable_http.py:398-427`, so the status is read
    from the client's own response hook); anything else is a transport failure worth one more try."""
    if 401 in statuses:
        return McpCallFailed(f"{tool}: the server refused the worker's token", code=UNAUTHENTICATED)
    return McpCallFailed(f"{tool}: transport or protocol failure", code=TRANSPORT, retryable=True)


def failure_leaf(exc: BaseException) -> BaseException:
````

Edit 26 (`worker/src/ops_worker/mcp.py`), replace:

````python
    except tool_contracts.ContractViolation as exc:
        raise McpCallFailed(f"{tool.value}: the result fails the contract") from exc
    if document["status"] != "ok":
        raise McpCallFailed(f"{tool.value}: the server rejected the call")
    return document


````

with:

````python
    except tool_contracts.ContractViolation as exc:
        raise McpCallFailed(f"{tool.value}: the result fails the contract") from exc
    if document["status"] != "ok":
        error = document.get("error") or {}
        raise McpCallFailed(
            f"{tool.value}: the server rejected the call",
            code=error.get("code"),
            retryable=bool(error.get("retryable")),
        )
    return document


````

Edit 27 (`worker/src/ops_worker/mcp.py`), replace:

````python
    async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call the tool over Streamable HTTP; every failure to obtain a valid tool result is McpCallFailed."""
        read = next((candidate for candidate in READ_TOOLS if candidate.value == tool), None)
        try:
            headers = {"Authorization": f"Bearer {await self._tokens.token()}", "X-Ops-Invocation": handle}
            async with (
                httpx2.AsyncClient(headers=headers, timeout=self._timeout, transport=self._transport) as http,
                Client(streamable_http_client(url, http_client=http), mode=PROTOCOL_VERSION) as client,
            ):
                if read is not None:  # discovery in the same session, before the call (ruling 13)
````

with:

````python
    async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call the tool over Streamable HTTP; every failure to obtain a valid tool result is McpCallFailed."""
        read = next((candidate for candidate in READ_TOOLS if candidate.value == tool), None)
        statuses: list[int] = []

        async def record(response: httpx2.Response) -> None:
            statuses.append(response.status_code)

        try:
            headers = {"Authorization": f"Bearer {await self._tokens.token()}", "X-Ops-Invocation": handle}
            async with (
                httpx2.AsyncClient(
                    headers=headers,
                    timeout=self._timeout,
                    transport=self._transport,
                    event_hooks={"response": [record]},
                ) as http,
                Client(streamable_http_client(url, http_client=http), mode=PROTOCOL_VERSION) as client,
            ):
                if read is not None:  # discovery in the same session, before the call (ruling 13)
````

Edit 28 (`worker/src/ops_worker/mcp.py`), replace:

````python
        except McpCallFailed:
            raise
        except TRANSPORT_FAILURES as exc:
            raise McpCallFailed(f"{tool}: transport or protocol failure") from exc
        except BaseExceptionGroup as group:
            found = leaves(group)
            if read is not None:
````

with:

````python
        except McpCallFailed:
            raise
        except TRANSPORT_FAILURES as exc:
            raise transport_failure(tool, statuses) from exc
        except BaseExceptionGroup as group:
            found = leaves(group)
            if read is not None:
````

Edit 29 (`worker/src/ops_worker/mcp.py`), replace:

````python
                    failed = next((leaf for leaf in found if isinstance(leaf, McpCallFailed)), None)
                    if failed is not None:  # a failed check inside the session: the client's task group wraps it
                        raise failed from None
                    raise McpCallFailed(f"{tool}: the session failed ({type(found[0]).__name__})") from group
                raise
            leaf = failure_leaf(group)
            if isinstance(leaf, TRANSPORT_FAILURES):
                raise McpCallFailed(f"{tool}: transport or protocol failure") from leaf
            raise
        except Exception as exc:
            if read is None:
````

with:

````python
                    failed = next((leaf for leaf in found if isinstance(leaf, McpCallFailed)), None)
                    if failed is not None:  # a failed check inside the session: the client's task group wraps it
                        raise failed from None
                    if 401 in statuses or any(isinstance(leaf, TRANSPORT_FAILURES) for leaf in found):
                        raise transport_failure(tool, statuses) from group
                    raise McpCallFailed(f"{tool}: the session failed ({type(found[0]).__name__})") from group
                raise
            leaf = failure_leaf(group)
            if isinstance(leaf, TRANSPORT_FAILURES):
                raise transport_failure(tool, statuses) from leaf
            raise
        except Exception as exc:
            if read is None:
````

Edit 30 (`worker/src/ops_worker/mcp.py`), replace:

````python
            raise McpCallFailed(f"{tool}: the session failed ({type(exc).__name__})") from exc
        if read is not None:
            return read_result(read, result)
        # TODO(T20): the write tools (mcp-write) still get only T47's check: no discovery and no result-schema check.
        if result.is_error or not isinstance(result.structured_content, dict):
            raise McpCallFailed(f"{tool}: the server rejected the call")
        return result.structured_content
````

with:

````python
            raise McpCallFailed(f"{tool}: the session failed ({type(exc).__name__})") from exc
        if read is not None:
            return read_result(read, result)
        # TODO(T21): the write tools (mcp-write) still get only T47's check: no discovery and no result-schema check
        # (Plan Q departure 4: whether mcp-write advertises the committed create_incident schema is checked live first).
        if result.is_error or not isinstance(result.structured_content, dict):
            raise McpCallFailed(f"{tool}: the server rejected the call")
        return result.structured_content
````

Edit 31 (`mcp-read/src/ops_mcp_read/assets.py`), replace:

````python
worker's token and never with the invocation handle; the only context it forwards is what `asset_scope` returned for
the handle: the run's tenant (`X-Ops-Tenant-Id`) and the database instant to answer at (`X-Ops-As-Of`), with the
run's asset in the path and, for alerts, the run's interval. Each call happens outside any database transaction, with
a 10-second timeout and no retry here (the worker does not retry either today: it fails the run on any failed read,
and honouring `retryable` is T20's). Failures map to one exception each, which the tools turn into
envelope codes (ruling 15): a transport error, a timeout or a 5xx is `Unavailable` (retryable), a 404 is `AssetMissing`
(an unknown asset and another tenant's alike), a 400 to a request that carried a cursor is `CursorRejected`, and
anything else, or a body that is not a JSON object, is `UpstreamInvalid`. A 401 also drops the cached token, so the
````

with:

````python
worker's token and never with the invocation handle; the only context it forwards is what `asset_scope` returned for
the handle: the run's tenant (`X-Ops-Tenant-Id`) and the database instant to answer at (`X-Ops-As-Of`), with the
run's asset in the path and, for alerts, the run's interval. Each call happens outside any database transaction, with
a 10-second timeout and no retry here (the worker's graph retries a `retryable` read at most twice, T20, and fails
the run on any other failed read). Failures map to one exception each, which the tools turn into
envelope codes (ruling 15): a transport error, a timeout or a 5xx is `Unavailable` (retryable), a 404 is `AssetMissing`
(an unknown asset and another tenant's alike), a 400 to a request that carried a cursor is `CursorRejected`, and
anything else, or a body that is not a JSON object, is `UpstreamInvalid`. A 401 also drops the cached token, so the
````

Run the same command → `8 passed`.

- [ ] **Step 3: Gates and commit**

`git add` the three new files; dev `CHECK: GREEN`, `1672 passed, 222 skipped`; `verify_handoff.py` exit 0.

```bash
git add worker/src/ops_worker mcp-read/src/ops_mcp_read/assets.py tests/plan_q tests/plan_j/test_worker_azp.py
git commit -m "feat: the evidence bundle with status and alerts, SA:377's sufficiency rule and the read failure codes (T20)"
```

---
### Task 4: The graph and the handlers

**Files:**
- Create: `worker/src/ops_worker/deps.py`, `worker/src/ops_worker/graph/__init__.py`, `state.py`, `nodes.py`,
  `build.py`, `tests/plan_q/test_graph_routes.py`, `tests/plan_q/test_graph_flow.py`
- Modify: `worker/src/ops_worker/handlers.py` (replaced), `main.py`, `sweeper/src/ops_sweeper/wakeups.py` (docstring),
  `tests/plan_h/test_worker_units.py`, `tests/plan_p/test_investigate_drafting.py`,
  `tests/plan_p/test_worker_startup.py`, `tests/plan_j/test_worker_azp.py`, `tests/plan_f/test_grant_deferred.py`,
  `tests/plan_m/test_worker_r029.py`

**Requirements:** rulings 1-15; SA:201, SA:207, SA:209-218, SA:563, BS:330, BS:423; R022, R038, R042, R091, R108, R114,
R129 (DoD 1-4 on the in-memory saver); errata 124, 125, 127-129.

**Interfaces:**
- Consumes: Task 2's table and helpers; Task 3's bundle and failure codes; `langgraph.graph.StateGraph`,
  `langgraph.types.interrupt`/`Command`, `langgraph.runtime.Runtime`, `langgraph.checkpoint.memory.InMemorySaver`,
  `langgraph.checkpoint.postgres.aio.AsyncPostgresSaver`.
- Produces: `ops_worker.deps.Deps` (re-exported as `handlers.Deps`, now with `saver`); `ops_worker.graph.state`
  (`RunGraphState`, `initial`, `key`, `Context`, `Held`, `HeldDraft`); `ops_worker.graph.nodes` (the ten nodes,
  `unit`, `facts`, `fail_from`, `Requeue`, the templates); `ops_worker.graph.build` (`NODES`, `ROUTE_NODES`,
  `edge_map`, `next_route`, `after_publish`, `build_graph(saver, replace)`, `thread_id`, `config`, `confirm`, `known`,
  `interrupted`, `run_graph`, `open_saver`); `handlers.resume_input`.

- [ ] **Step 1: The tests first (and Plan H's fakes keep the run row)**

Edit 32 (`tests/plan_h/test_worker_units.py`), replace:

````python
import pytest
from ops_core import persistence, settings
from ops_core.lease import LOCK_FOR_UPDATE, RELEASED, Lease, LeaseLost
from ops_core.states import RunState
from ops_worker import handlers, main
from ops_worker.drafting import FakeDraftGenerator
from ops_worker.mcp import HttpMcpCaller
from psycopg.pq import TransactionStatus
from starlette.testclient import TestClient

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
TENANT, RUN_ID = uuid4(), uuid4()
RUN = {
````

with:

````python
import pytest
from ops_core import persistence, settings
from ops_core.lease import LOCK_FOR_UPDATE, RELEASED, Lease, LeaseLost
from ops_core.outcomes import EventType
from ops_core.states import AttemptState, Intent, RunState
from ops_worker import handlers, main
from ops_worker.drafting import FakeDraftGenerator
from ops_worker.mcp import HttpMcpCaller
from psycopg.pq import TransactionStatus
from starlette.testclient import TestClient

from tests.plan_q.fixtures import ALERTS, STATUS

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
TENANT, RUN_ID = uuid4(), uuid4()
RUN = {
````

Edit 33 (`tests/plan_h/test_worker_units.py`), replace:

````python
}
JOB = {"id": uuid4(), "run_id": RUN_ID, "tenant_id": TENANT, "type": "investigate"}
REAL_RELEASE = persistence.release_lease  # `patch` replaces it; the release tests run the real unit on fakes
WRITES = {"transition_run", "mint_handle", "append_event", "freeze_proposal", "insert", "mark_unknown"}
SEARCH = {
    "status": "ok",
    "data": {
````

with:

````python
}
JOB = {"id": uuid4(), "run_id": RUN_ID, "tenant_id": TENANT, "type": "investigate"}
REAL_RELEASE = persistence.release_lease  # `patch` replaces it; the release tests run the real unit on fakes
WRITES = {
    "transition_run",
    "mint_handle",
    "append_event",
    "freeze_proposal",
    "insert",
    "mark_unknown",
    "store_checkpoint_id",
}
SEARCH = {
    "status": "ok",
    "data": {
````

Edit 34 (`tests/plan_h/test_worker_units.py`), replace:

````python
        "corpus_version": "handoff-1",
    },
}


class Log:
````

with:

````python
        "corpus_version": "handoff-1",
    },
}
SUCCEEDED = {"status": "outcome", "data": {"status": "SUCCEEDED"}, "error": None}  # mcp-write, after the receipt
ANSWERS = {
    "get_asset_status": STATUS,
    "get_recent_alerts": ALERTS,
    "search_procedures": SEARCH,
    "create_incident": SUCCEEDED,
}


class Log:
````

Edit 35 (`tests/plan_h/test_worker_units.py`), replace:

````python

    async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.log.entries.append(f"mcp:{tool}")
        return SEARCH


def patch(monkeypatch: pytest.MonkeyPatch, log: Log, *, lost_at: int | None = None) -> None:
    """Replace every persistence call the handlers make with a recorder; the `lost_at`-th `fenced` call raises
    LeaseLost, as a moved fence would."""
    calls = 0

    async def fenced(_conn: Any, lease: Lease) -> None:
        nonlocal calls
        calls += 1
        log.entries.append("fenced")
        if lost_at is not None and calls >= lost_at:
            lease.mark_lost("the fence moved")
            raise LeaseLost("run lease lost")

    async def run_row(_conn: Any, _run_id: Any, *, lock: bool = False) -> dict[str, Any]:
        log.entries.append("run_row")
        return dict(RUN)

    def recorder(name: str, result: Any = None) -> Callable[..., Any]:
        async def call(*_: Any, **__: Any) -> Any:
````

with:

````python

    async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.log.entries.append(f"mcp:{tool}")
        return ANSWERS[tool]


def patch(
    monkeypatch: pytest.MonkeyPatch,
    log: Log,
    *,
    lost_at: int | None = None,
    lose_after: str | None = None,
    run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Replace every persistence call the handlers make with a recorder; the `lost_at`-th `fenced` call, or the first
    one made once `lose_after` is in the log, raises LeaseLost, as a moved fence would. The run row is kept like the
    database keeps it (T20: the graph's nodes reread it): a transition, a freeze and a stored checkpoint id change it;
    it is returned so a test can read or set it.
    Its "events" map holds the run's events by type, as `run_events` reads them: a move to AWAITING_INPUT journals its
    clarification.requested (transition_run emits it, SA:451), and a test adds what the API would write."""
    calls = 0
    current: dict[str, Any] = {**(RUN if run is None else run), "events": {}}

    async def fenced(_conn: Any, lease: Lease) -> None:
        nonlocal calls
        calls += 1
        log.entries.append("fenced")
        if (lost_at is not None and calls >= lost_at) or (lose_after is not None and lose_after in log.entries):
            lease.mark_lost("the fence moved")
            raise LeaseLost("run lease lost")

    async def run_row(_conn: Any, _run_id: Any, *, lock: bool = False) -> dict[str, Any]:
        log.entries.append("run_row")
        return dict(current)

    async def transition_run(_conn: Any, *, dst: RunState, detail: Any = None, **_: Any) -> int:
        log.entries.append("transition_run")
        current["state"] = dst.value
        if dst is RunState.AWAITING_INPUT:
            asked = current["events"].setdefault(EventType.CLARIFICATION_REQUESTED, [])
            asked.append((uuid4(), dict(detail or {})))
        return 2

    async def run_events(_conn: Any, _run_id: Any, type: EventType) -> list[tuple[Any, dict[str, Any]]]:
        log.entries.append("run_events")
        return list(current["events"].get(type, []))

    async def freeze_proposal(*_: Any, **__: Any) -> None:
        log.entries.append("freeze_proposal")
        current["state"] = RunState.AWAITING_APPROVAL.value

    async def graph_facts(_conn: Any, _run_id: Any) -> persistence.GraphFacts:
        log.entries.append("graph_facts")
        state = RunState(current["state"])
        decided = state in (RunState.APPROVED, RunState.EXECUTING, RunState.OUTCOME_UNKNOWN)
        attempt = AttemptState.SENT if state is RunState.EXECUTING else None
        return persistence.GraphFacts(state, Intent(current["intent"]), decided, attempt, current.get("checkpoint_id"))

    async def insert_run_manifest(_conn: Any, **_: Any) -> None:
        log.entries.append("insert")  # as the real one's INSERT is logged by FakeConn
        current["manifest"] = True

    async def run_manifest_exists(_conn: Any, _run_id: Any) -> bool:
        log.entries.append("run_manifest_exists")
        return bool(current.get("manifest"))

    async def store_checkpoint_id(_conn: Any, _run_id: Any, checkpoint_id: str) -> None:
        log.entries.append("store_checkpoint_id")
        current["checkpoint_id"] = checkpoint_id

    def recorder(name: str, result: Any = None) -> Callable[..., Any]:
        async def call(*_: Any, **__: Any) -> Any:
````

Edit 36 (`tests/plan_h/test_worker_units.py`), replace:

````python
    replaced = {
        "fenced": fenced,
        "run_row": run_row,
        "set_tenant": recorder("set_tenant"),
        "transition_run": recorder("transition_run", 2),
        "mint_handle": recorder("mint_handle", "handle"),
        "append_event": recorder("append_event"),
        "freeze_proposal": recorder("freeze_proposal"),
        "release_lease": recorder("release_lease"),
        "revoke_handles": recorder("revoke_handles", 1),
        "unclaim_job": recorder("unclaim_job"),
````

with:

````python
    replaced = {
        "fenced": fenced,
        "run_row": run_row,
        "graph_facts": graph_facts,
        "store_checkpoint_id": store_checkpoint_id,
        "insert_run_manifest": insert_run_manifest,
        "run_manifest_exists": run_manifest_exists,
        "run_events": run_events,
        "message_text": recorder("message_text", "Investigate the alerts on A17 over the last 24 hours."),
        "set_tenant": recorder("set_tenant"),
        "transition_run": transition_run,
        "mint_handle": recorder("mint_handle", "handle"),
        "append_event": recorder("append_event"),
        "freeze_proposal": freeze_proposal,
        "release_lease": recorder("release_lease"),
        "revoke_handles": recorder("revoke_handles", 1),
        "unclaim_job": recorder("unclaim_job"),
````

Edit 37 (`tests/plan_h/test_worker_units.py`), replace:

````python
    }
    for name, fn in replaced.items():
        monkeypatch.setattr(persistence, name, fn)


def make(log: Log, clock: Callable[[], float] = time.monotonic) -> tuple[handlers.Deps, Lease]:
````

with:

````python
    }
    for name, fn in replaced.items():
        monkeypatch.setattr(persistence, name, fn)
    return current


def make(log: Log, clock: Callable[[], float] = time.monotonic) -> tuple[handlers.Deps, Lease]:
````

Edit 38 (`tests/plan_h/test_worker_units.py`), replace:

````python
    deps, lease = make(log)
    asyncio.run(handlers.handle(deps, dict(JOB), lease))
    units = log.units()
    assert len(units) == 7, log.entries  # start, tool.started, tool.completed, DRAFTING, permit, release, freeze
    assert (
        log.entries.index("take_model_permit")
        < log.entries.index("release_model_permit")
````

with:

````python
    deps, lease = make(log)
    asyncio.run(handlers.handle(deps, dict(JOB), lease))
    units = log.units()
    # T20: one unit per stored checkpoint (SA:211) besides the start, the three reads' events, DRAFTING, the permit
    # and the freeze; every one of them opens with the fence.
    assert ["set_tenant", "fenced", "store_checkpoint_id"] in units, log.entries
    assert (
        log.entries.index("take_model_permit")
        < log.entries.index("release_model_permit")
````

Edit 39 (`tests/plan_h/test_worker_units.py`), replace:

````python
    log = Log()
    patch(monkeypatch, log)
    deps, lease = make(log)
    asyncio.run(handlers.handle(deps, {**JOB, "type": "resume_input"}, lease))  # not handled yet (T20)
    assert log.entries == ["release_lease"]  # one unit closes the job, revokes and releases (ruling 28)


def test_a_lost_lease_hands_the_job_back_without_a_transition(monkeypatch: pytest.MonkeyPatch) -> None:
    log = Log()
    patch(monkeypatch, log, lost_at=2)  # the first unit passes; the tool.started event's fence has moved
    deps, lease = make(log)
    claimed: Any = persistence.Claimed(dict(JOB), lease)  # a plain dict stands in for the claimed DictRow
    asyncio.run(main.run_job(deps, claimed))
    assert lease.lost == "the fence moved"
    assert log.units()[-1] == ["set_tenant", "revoke_handles", "unclaim_job"]  # the abandon unit (ruling 19)
    assert log.entries.count("transition_run") == 1  # QUEUED -> RETRIEVING before the loss; never FAILED after it
    assert "release_lease" not in log.entries and "mcp:search_procedures" not in log.entries


def test_a_busy_run_defers_and_the_poll_gives_up_after_the_bound(monkeypatch: pytest.MonkeyPatch) -> None:
````

with:

````python
    log = Log()
    patch(monkeypatch, log)
    deps, lease = make(log)
    asyncio.run(handlers.handle(deps, {**JOB, "type": "recover"}, lease))  # not handled before T22
    assert log.entries == ["release_lease"]  # one unit closes the job, revokes and releases (ruling 28)


def test_a_lost_lease_hands_the_job_back_without_a_transition(monkeypatch: pytest.MonkeyPatch) -> None:
    log = Log()
    patch(monkeypatch, log, lose_after="transition_run")  # QUEUED -> RETRIEVING passes; tool.started's fence moved
    deps, lease = make(log)
    claimed: Any = persistence.Claimed(dict(JOB), lease)  # a plain dict stands in for the claimed DictRow
    asyncio.run(main.run_job(deps, claimed))
    assert lease.lost == "the fence moved"
    assert log.units()[-1] == ["set_tenant", "revoke_handles", "unclaim_job"]  # the abandon unit (ruling 19)
    assert log.entries.count("transition_run") == 1  # QUEUED -> RETRIEVING before the loss; never FAILED after it
    assert "release_lease" not in log.entries and not [e for e in log.entries if e.startswith("mcp:")]


def test_a_busy_run_defers_and_the_poll_gives_up_after_the_bound(monkeypatch: pytest.MonkeyPatch) -> None:
````

Edit 40 (`tests/plan_h/test_worker_units.py`), replace:

````python
    monkeypatch.setattr(persistence, "mint_handle", mint_then_stall)
    with pytest.raises(LeaseLost):
        asyncio.run(handlers.investigate(deps, dict(JOB), lease))
    assert "mcp:search_procedures" not in log.entries  # SA:195: the call never started


def test_abandon_closes_a_loop_connection_left_in_a_transaction() -> None:
````

with:

````python
    monkeypatch.setattr(persistence, "mint_handle", mint_then_stall)
    with pytest.raises(LeaseLost):
        asyncio.run(handlers.investigate(deps, dict(JOB), lease))
    assert not [e for e in log.entries if e.startswith("mcp:")]  # SA:195: no call started


def test_abandon_closes_a_loop_connection_left_in_a_transaction() -> None:
````

Edit 41 (`tests/plan_h/test_worker_units.py`), replace:

````python
        return UNKNOWN_ENVELOPE


def executing(monkeypatch: pytest.MonkeyPatch, log: Log, *, lost_at: int | None = None) -> tuple[handlers.Deps, Lease]:
    """The fakes for an execute job whose run is EXECUTING and whose write call answers UNKNOWN."""
    patch(monkeypatch, log, lost_at=lost_at)

    async def executing_run(_conn: Any, _run_id: Any, *, lock: bool = False) -> dict[str, Any]:
        log.entries.append("run_row")
        return {**RUN, "state": "EXECUTING"}

    monkeypatch.setattr(persistence, "run_row", executing_run)
    deps, lease = make(log)
    deps.mcp = UnknownMcp(log)
    return deps, lease
````

with:

````python
        return UNKNOWN_ENVELOPE


def executing(
    monkeypatch: pytest.MonkeyPatch, log: Log, *, lose_after: str | None = None
) -> tuple[handlers.Deps, Lease]:
    """The fakes for an execute job whose run is EXECUTING and whose write call answers UNKNOWN."""
    patch(monkeypatch, log, lose_after=lose_after, run={**RUN, "state": "EXECUTING"})
    deps, lease = make(log)
    deps.mcp = UnknownMcp(log)
    return deps, lease
````

Edit 42 (`tests/plan_h/test_worker_units.py`), replace:

````python


def test_a_stale_fence_at_mark_unknown_is_a_lost_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    for lost_at, raised in ((2, LeaseLost), (None, persistence.VersionConflict)):
        log = Log()
        deps, lease = executing(monkeypatch, log, lost_at=lost_at)

        async def refused(*_: Any, **__: Any) -> None:
            raise persistence.VersionConflict("version_conflict: stale fence")

        monkeypatch.setattr(persistence, "mark_unknown", refused)
        # With lost_at=2 the fresh fence check after the refusal fails: the fence was stale, a lost lease. Without
        # it the fence holds, so the refusal was the run's own state and is raised as it came.
        with pytest.raises(raised):
            asyncio.run(handlers.execute(deps, {**JOB, "type": "execute"}, lease))
        assert (lease.fence, lease.refencing) == (3, False)
````

with:

````python


def test_a_stale_fence_at_mark_unknown_is_a_lost_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    for lose_after, raised in (("mcp:create_incident", LeaseLost), (None, persistence.VersionConflict)):
        log = Log()
        deps, lease = executing(monkeypatch, log, lose_after=lose_after)

        async def refused(*_: Any, **__: Any) -> None:
            raise persistence.VersionConflict("version_conflict: stale fence")

        monkeypatch.setattr(persistence, "mark_unknown", refused)
        # Losing after the call, the fresh fence check after the refusal fails: the fence was stale, a lost lease.
        # Without it the fence holds, so the refusal was the run's own state and is raised as it came.
        with pytest.raises(raised):
            asyncio.run(handlers.execute(deps, {**JOB, "type": "execute"}, lease))
        assert (lease.fence, lease.refencing) == (3, False)
````

Edit 43 (`tests/plan_h/test_worker_units.py`), replace:

````python
    async def scenario() -> None:
        claimed: Any = persistence.Claimed(dict(JOB), lease)
        job = asyncio.create_task(main.run_job(deps, claimed))
        while "mcp:search_procedures" not in log.entries:
            await asyncio.sleep(0)
        assert heartbeat.held is lease
        cancelled.append(lose(lease))
````

with:

````python
    async def scenario() -> None:
        claimed: Any = persistence.Claimed(dict(JOB), lease)
        job = asyncio.create_task(main.run_job(deps, claimed))
        while not [e for e in log.entries if e.startswith("mcp:")]:  # the first read is in flight
            await asyncio.sleep(0)
        assert heartbeat.held is lease
        cancelled.append(lose(lease))
````

Edit 44 (`tests/plan_h/test_worker_units.py`), replace:

````python
    monkeypatch.setattr(persistence, "transition_run", transition_then_lose)
    claimed: Any = persistence.Claimed(dict(JOB), lease)
    asyncio.run(main.run_job(deps, claimed))
    first = log.entries[: log.entries.index("COMMIT") + 1]
    assert first[0] == "BEGIN" and "mint_handle" in first and "ROLLBACK" not in first  # the unit committed whole
    assert cancelled == [0] and "mcp:search_procedures" not in log.entries  # no effect was in flight to cancel
    assert log.units()[-1] == ["set_tenant", "revoke_handles", "unclaim_job"]


````

with:

````python
    monkeypatch.setattr(persistence, "transition_run", transition_then_lose)
    claimed: Any = persistence.Claimed(dict(JOB), lease)
    asyncio.run(main.run_job(deps, claimed))
    start = log.entries.index("transition_run")
    end = next(i for i in range(start, len(log.entries)) if log.entries[i] in ("COMMIT", "ROLLBACK"))
    assert log.entries[end] == "COMMIT" and "mint_handle" in log.entries[start:end]  # the unit committed whole
    assert cancelled == [0] and not [e for e in log.entries if e.startswith("mcp:")]  # no effect was in flight
    assert log.units()[-1] == ["set_tenant", "revoke_handles", "unclaim_job"]


````

Edit 45 (`tests/plan_h/test_worker_units.py`), replace:

````python
    `execute` takes the envelope as final, the final unit finds the lease not live, and the loop hands the job back.
    The job is never closed, so the run's next owner mints a fresh handle and asks for the grant again."""
    log = Log()
    patch(monkeypatch, log)
    releasing(monkeypatch, log)

    async def approved_run(_conn: Any, _run_id: Any, *, lock: bool = False) -> dict[str, Any]:
        log.entries.append("run_row")
        return {**RUN, "state": "APPROVED"}

    class Refusing:
        async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
            log.entries.append(f"mcp:{tool}")
            return {"status": "error", "data": None, "error": {"code": "INVALID_HANDLE", "message": "invalid handle"}}

    monkeypatch.setattr(persistence, "run_row", approved_run)
    deps, lease = make(log)
    deps.conn = LeaseRowConn(log, live=False)  # the lease lapsed on the database clock
    deps.mcp = Refusing()
````

with:

````python
    `execute` takes the envelope as final, the final unit finds the lease not live, and the loop hands the job back.
    The job is never closed, so the run's next owner mints a fresh handle and asks for the grant again."""
    log = Log()
    patch(monkeypatch, log, run={**RUN, "state": "APPROVED"})
    releasing(monkeypatch, log)

    class Refusing:
        async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
            log.entries.append(f"mcp:{tool}")
            return {"status": "error", "data": None, "error": {"code": "INVALID_HANDLE", "message": "invalid handle"}}

    deps, lease = make(log)
    deps.conn = LeaseRowConn(log, live=False)  # the lease lapsed on the database clock
    deps.mcp = Refusing()
````

Create `tests/plan_q/test_graph_routes.py`:

````python
"""The edges generated from the graph router's table, and the walk of every row to its node (T20; SA:377; R129's
graph half, DoD 4).

Catches: a conditional edge out of `route_request` that no table row can choose, or a row whose route has no edge; a
route without exactly one node, or a graph without SA:207's ten nodes; and a row whose key, run through the compiled
graph with every other node stubbed, reaches another node than its route's.
"""

import asyncio
from typing import Any
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from ops_core import persistence
from ops_core.contracts import ModelDraft
from ops_core.routing import (
    GRAPH_ROUTES,
    DraftKind,
    GraphKey,
    GraphRoute,
    ModelRoute,
    RunManifest,
)
from ops_worker.evidence import Bundle
from ops_worker.graph import build
from ops_worker.graph.state import Context, HeldDraft, initial, key

from tests.plan_h.test_worker_units import Log, make
from tests.plan_q.test_graph_table import WALK


class Reached(Exception):
    """Raised by a stub node: the walk got there."""


def stub(name: str) -> Any:
    async def node(_state: Any, runtime: Any) -> dict[str, Any]:
        raise Reached(name)

    return node


MANIFEST = RunManifest(
    run_id=uuid4(),
    model_route=ModelRoute.FAKE,
    model_digest=None,
    prompt_version="incident-draft-v2",
    corpus_version="handoff-1",
    retrieval_mode="lexical",
)


def held() -> tuple[HeldDraft, Bundle]:
    """What a graph run holds after drafting, so route_request keeps the key's draft kind and evidence verdict."""
    draft = ModelDraft(kind="abstain", title="t", summary="s", evidence_refs=[], assumptions=[], limitations=[])
    return HeldDraft(uuid4(), draft), Bundle("text", [], (), MANIFEST)


def test_the_router_edges_are_the_table_routes_and_nothing_else() -> None:
    compiled = build.build_graph(InMemorySaver())
    (branch,) = compiled.builder.branches["route_request"].values()  # the one conditional edge set out of the router
    table = {rule.route.value: build.ROUTE_NODES[rule.route] for rule in GRAPH_ROUTES}
    assert branch.ends == table == build.edge_map()
    drawn = compiled.get_graph().edges
    assert {edge.target for edge in drawn if edge.source == "route_request"} == set(table.values())
    publish = {edge.target for edge in drawn if edge.source == "publish_state"}
    assert publish == {"__end__", "route_request"}  # after_publish: the table's publish route ends the graph run


def test_every_route_has_one_node_and_some_row() -> None:
    assert set(build.ROUTE_NODES) == set(GraphRoute)  # a dict: one node each
    assert set(build.ROUTE_NODES.values()) <= set(build.NODES) and len(build.NODES) == 10  # SA:207's ten nodes


@pytest.mark.parametrize(("name", "witness"), WALK, ids=[f"{n}-{w.state.value}" for n, w in WALK])
def test_each_row_routes_its_key_to_its_node(name: str, witness: GraphKey, monkeypatch: pytest.MonkeyPatch) -> None:
    rule = next(r for r in GRAPH_ROUTES if r.name == name)
    draft, bundle = held()
    state = {
        **initial(uuid4()),
        "run_state": witness.state.value,
        "intent": witness.intent.value,
        "context_resolved": witness.context_resolved,
        "evidence": witness.evidence.value,
        "draft_kind": witness.draft_kind.value,
        "draft_id": str(draft.draft_id) if witness.draft_kind is not DraftKind.NONE else None,
        "decision_present": witness.decision_present,
        "attempt_state": None if witness.attempt_state is None else witness.attempt_state.value,
    }
    assert key(state) == witness

    async def load_run(_state: Any, runtime: Any) -> dict[str, Any]:
        return state

    async def graph_facts(_conn: Any, _run_id: Any) -> persistence.GraphFacts:  # what route_request rereads
        facts = (witness.state, witness.intent, witness.decision_present, witness.attempt_state, None)
        return persistence.GraphFacts(*facts)

    async def set_tenant(_conn: Any, _tenant: Any) -> None:
        return None

    monkeypatch.setattr(persistence, "graph_facts", graph_facts)
    monkeypatch.setattr(persistence, "set_tenant", set_tenant)

    stubs = {n: stub(n) for n in build.NODES if n not in ("load_run", "route_request")}
    graph = build.build_graph(InMemorySaver(), {**stubs, "load_run": load_run})
    deps, lease = make(Log())
    ctx = Context(deps, {"id": uuid4(), "tenant_id": uuid4()}, lease)
    ctx.held.draft, ctx.held.bundle = draft, bundle
    with pytest.raises(Reached) as reached:
        asyncio.run(graph.ainvoke(initial(uuid4()), {"configurable": {"thread_id": "walk"}}, context=ctx))
    assert str(reached.value) == build.ROUTE_NODES[rule.route]
````

Create `tests/plan_q/test_graph_flow.py`:

````python
"""The worker graph on LangGraph's in-memory saver and Plan H's fakes (T20; SA:207-218; R038, R042, R091, R108, R114,
DoD 1-3), without a database.

Catches: a read that completes after the model is called, or a draft without the status and alerts; a checkpoint id
stored outside the fence, or a stored id that is not the checkpoint holding the interrupt; an invocation without
`durability="sync"` or the checkpoint stream; an answer that freezes a proposal or does not end ANSWERED with its
cited summary; a question that does not release the lease, or a reply that does not resume the run where it waited;
a third question that waits again; a reply that is not the latest that is still taken; a stray newer head that a
resume follows; a crash (twice) that is not resumed from the stored checkpoint, or that writes a second manifest; a
missing stored checkpoint that leaves a run active; model or evidence text inside a checkpoint; a router that routes
on dimensions an earlier node left stale (an approved run that forked from before its freeze could then never
execute); an execute job that resumes with a decision that is not the run's approval of its active proposal; a lost
hold after a completed draft that is not drafted again; and a transient
read that is not retried, a read retried past BS:552's budget, a refused token that is retried or reported as an
ordinary failure, or an unknown asset that is not the "context missing" abstention.
"""

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from ops_core import persistence
from ops_core.contracts import ModelDraft
from ops_core.lease import Lease, LeaseLost
from ops_core.outcomes import EventType
from ops_worker import handlers, main
from ops_worker.drafting import DraftRequest, EvidenceItem, FakeDraftGenerator
from ops_worker.graph import build, nodes
from ops_worker.graph.state import Context, initial
from ops_worker.mcp import TRANSPORT, UNAUTHENTICATED, McpCallFailed

from tests.plan_h.test_worker_units import JOB, RUN, RUN_ID, SEARCH, Log, make, patch
from tests.plan_q.fixtures import ALERTS, STATUS

DRAFT = {"title": "t", "evidence_refs": ["ALPHA-INCIDENT:v2:review"], "assumptions": [], "limitations": []}
QUESTION = ModelDraft(**{**DRAFT, "kind": "abstain", "evidence_refs": [], "summary": "s", "question": "Which hours?"})
ANSWER = ModelDraft(**{**DRAFT, "kind": "answer", "summary": "B22 shows no warning that needs an incident."})
THREAD = build.thread_id(RUN_ID, 1)


class Scripted(FakeDraftGenerator):
    """The fake route answering from a script (None: the fake's own draft); keeps every request it got."""

    def __init__(self, *drafts: ModelDraft | BaseException | None) -> None:
        super().__init__()
        self.drafts = list(drafts)
        self.requests: list[DraftRequest] = []

    async def generate(self, request: DraftRequest, evidence: list[EvidenceItem]) -> ModelDraft:
        self.requests.append(request)
        nxt = self.drafts.pop(0) if self.drafts else None
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt if nxt is not None else await super().generate(request, evidence)


@dataclass
class World:
    """One run's fakes: the log, the kept run row (with its events), the saver every job of the run shares, and the
    contexts the graph runs were given (their node logs)."""

    log: Log
    run: dict[str, Any]
    saver: InMemorySaver
    contexts: list[Context]


def world(monkeypatch: pytest.MonkeyPatch, run: dict[str, Any] | None = None) -> World:
    log = Log()
    current = patch(monkeypatch, log, run=run)
    contexts: list[Context] = []
    real = handlers.Context

    def recording(*args: Any, **kwargs: Any) -> Context:
        ctx = real(*args, **kwargs)
        contexts.append(ctx)
        return ctx

    monkeypatch.setattr(handlers, "Context", recording)
    monkeypatch.setattr(nodes, "RETRY_SECONDS", 0.0)
    return World(log, current, InMemorySaver(), contexts)


def job(
    w: World, generator: Any, kind: str = "investigate", mcp: Any = None, **extra: Any
) -> tuple[handlers.Deps, Lease]:
    """Run one job of the run on a fresh Deps (a fresh process's holds) over the run's saver."""
    deps, lease = make(w.log)
    deps.saver, deps.generator = w.saver, generator
    deps.mcp = mcp or deps.mcp
    asyncio.run(handlers.handle(deps, {**JOB, "type": kind, **extra}, lease))
    return deps, lease


def transitions(w: World) -> list[str]:
    return [e for e in w.log.entries if e == "transition_run"]


def approve(w: World, proposal: Any = None) -> None:
    """What record_decision commits for an approval (0004): APPROVED and `approval.recorded {proposal_id}`."""
    w.run["state"] = "APPROVED"
    chosen = str(RUN["active_proposal_id"] if proposal is None else proposal)
    w.run["events"][EventType.APPROVAL_RECORDED] = [(uuid4(), {"proposal_id": chosen})]


def lose_once_after(monkeypatch: pytest.MonkeyPatch, w: World, entry: str) -> None:
    """The next fence check after `entry` is logged finds the fence moved, once (a lost lease or a stopped process
    between two units); later checks pass."""
    armed = [True]

    async def fenced(_conn: Any, lease: Lease) -> None:
        w.log.entries.append("fenced")
        if armed[0] and entry in w.log.entries:
            armed[0] = False
            lease.mark_lost("the fence moved")
            raise LeaseLost("run lease lost")

    monkeypatch.setattr(persistence, "fenced", fenced)


def handed_back(w: World, generator: Any) -> None:
    """One investigate job that loses its lease and is handed back (`main.run_job` → `abandon`)."""
    deps, lease = make(w.log)
    deps.saver, deps.generator = w.saver, generator
    asyncio.run(main.run_job(deps, persistence.Claimed(dict(JOB), lease)))
    assert w.log.units()[-1] == ["set_tenant", "revoke_handles", "unclaim_job"]


def snapshot(w: World, checkpoint_id: str | None) -> Any:
    graph = build.build_graph(w.saver)
    return asyncio.run(graph.aget_state(build.config(THREAD, checkpoint_id)))


def test_every_read_completes_before_the_model_is_called(monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(monkeypatch)
    generator = Scripted()
    job(w, generator)
    assert w.contexts[0].trace == [
        "load_run",
        "route_request",
        "retrieve_evidence",
        "route_request",
        "draft_with_langchain",
        "route_request",
        "validate_and_freeze",
        "route_request",
        "await_independent_decision",
    ]  # R038's node log: retrieval, then drafting, then the freeze and the wait (DoD 1)
    calls = [e for e in w.log.entries if e.startswith("mcp:")]
    assert calls == ["mcp:get_asset_status", "mcp:get_recent_alerts", "mcp:search_procedures"]
    assert w.log.entries.index("mcp:search_procedures") < w.log.entries.index("take_model_permit")
    (request,) = generator.requests
    assert [o.section for o in request.observations] == ["asset status", "alert"]  # BS:419: status and alerts too
    assert w.run["state"] == "AWAITING_APPROVAL"


def test_every_checkpoint_is_stored_under_the_fence_and_the_last_holds_the_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = world(monkeypatch)
    job(w, Scripted())
    stores = [u for u in w.log.units() if "store_checkpoint_id" in u]
    assert stores and all(u == ["set_tenant", "fenced", "store_checkpoint_id"] for u in stores)
    stored = w.run["checkpoint_id"]
    waiting = snapshot(w, stored)
    assert waiting.next == ("await_independent_decision",) and len(waiting.interrupts) == 1  # SA:211
    assert waiting.interrupts[0].value == str(RUN["active_proposal_id"])  # an id, never the proposal (SA:563)
    assert len(stores) == len(list(w.saver.list(build.config(THREAD, None))))  # every checkpoint, once each
    assert w.log.entries[-1] == "release_lease"  # the wait holds no lease (R022)


def test_every_invocation_is_sync_and_streams_checkpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(monkeypatch)
    seen: list[dict[str, Any]] = []
    real = build.build_graph

    class Spy:
        def __init__(self, graph: Any) -> None:
            self.graph = graph

        def astream(self, *args: Any, **kwargs: Any) -> Any:
            seen.append(kwargs)
            return self.graph.astream(*args, **kwargs)

        def __getattr__(self, name: str) -> Any:
            return getattr(self.graph, name)

    monkeypatch.setattr(build, "build_graph", lambda *a, **k: Spy(real(*a, **k)))
    job(w, Scripted())
    approve(w)
    job(w, Scripted(), "execute")
    assert len(seen) == 2 and all(s["durability"] == "sync" and s["stream_mode"] == "checkpoints" for s in seen)
    assert "mcp:create_incident" in w.log.entries  # the decision's resume reached the execute node (ruling 14)


@pytest.mark.parametrize("intent", ["answer_only", "investigate"])
def test_an_answer_ends_answered_with_its_cited_summary_and_no_proposal(
    monkeypatch: pytest.MonkeyPatch, intent: str
) -> None:
    """R114 on any intent (DEV-002 is an investigate run that ends ANSWERED); the fake route answers answer_only."""
    w = world(monkeypatch, {**RUN, "intent": intent})
    events: list[dict[str, Any]] = []
    moves: list[tuple[str, Any]] = []
    append, move = persistence.append_event, persistence.transition_run

    async def keep_event(*args: Any, **kwargs: Any) -> Any:
        events.append(kwargs)
        return await append(*args, **kwargs)

    async def keep_move(*args: Any, **kwargs: Any) -> Any:
        moves.append((kwargs["dst"].value, kwargs.get("detail")))
        return await move(*args, **kwargs)

    monkeypatch.setattr(persistence, "append_event", keep_event)
    monkeypatch.setattr(persistence, "transition_run", keep_move)
    job(w, Scripted(None if intent == "answer_only" else ANSWER))
    assert moves[-1] == ("ANSWERED", {"message": nodes.ANSWERED})
    (explained,) = [e for e in events if e["type"] is EventType.EXPLANATION_READY]
    assert explained["payload"]["evidence_refs"] == ["ALPHA-INCIDENT:v2:review"]  # the answer cites its evidence
    assert explained["payload"]["message"].startswith("For A17" if intent == "answer_only" else "B22 shows")
    assert "freeze_proposal" not in w.log.entries and w.log.entries.count("insert") == 2  # manifest and drafts row
    assert w.contexts[0].trace[-1] == "publish_state" and w.log.entries[-1] == "release_lease"


def reply(w: World, text: str = "Clarification: asset A17, hours 24") -> str:
    """What the API's record_reply writes (store.py): the reply message and clarification.received; returns the
    job key `run_id:question_id` (SA:501)."""
    question = w.run["events"][EventType.CLARIFICATION_REQUESTED][-1][0]
    message = uuid4()
    received = w.run["events"].setdefault(EventType.CLARIFICATION_RECEIVED, [])
    received.append((uuid4(), {"question_id": str(question), "message_id": str(message)}))
    return f"{RUN_ID}:{question}"


def test_a_question_waits_without_a_lease_and_the_reply_resumes_it(monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(monkeypatch)
    job(w, Scripted(QUESTION))
    assert w.run["state"] == "AWAITING_INPUT" and w.log.entries[-1] == "release_lease"  # R022: the wait is free
    ((asked, payload),) = w.run["events"][EventType.CLARIFICATION_REQUESTED]
    assert payload == {"message": "Which hours?"}  # the question rides in its event (erratum 124)
    waiting = snapshot(w, w.run["checkpoint_id"])
    assert [i.value for i in waiting.interrupts] == [str(asked)]  # SA:211: the stored id holds the interrupt
    key = reply(w)
    generator = Scripted(None)
    job(w, generator, "resume_input", dedup_key=key)
    assert w.run["state"] == "AWAITING_APPROVAL"  # resumed where it waited, then retrieved and drafted again
    assert w.contexts[-1].trace[:3] == ["await_clarification", "route_request", "retrieve_evidence"]
    (request,) = generator.requests
    assert request.text.endswith(
        "Clarification from the requester: Investigate the alerts on A17 over the last 24 hours."
    )
    assert snapshot(w, w.run["checkpoint_id"]).values["asked"] == [str(asked)]  # ids only, the round counted
    assert w.log.entries.count("run_manifest_exists") == 2 and w.log.entries.count("insert") == 3  # one manifest


def test_a_third_question_ends_the_run_insufficient(monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(monkeypatch)
    w.run["events"][EventType.CLARIFICATION_REQUESTED] = [(uuid4(), {}), (uuid4(), {})]  # two rounds already
    job(w, Scripted(QUESTION))
    assert w.run["state"] == "INSUFFICIENT_EVIDENCE"
    assert len(w.run["events"][EventType.CLARIFICATION_REQUESTED]) == 2  # not asked again (SA:137)


def test_a_reply_that_is_not_the_latest_fails_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(monkeypatch)
    job(w, Scripted(QUESTION))
    key = reply(w)
    w.run["events"][EventType.CLARIFICATION_RECEIVED].append((uuid4(), {"question_id": "elsewhere"}))
    moves: list[str] = []
    move = persistence.transition_run

    async def keep(*args: Any, **kwargs: Any) -> Any:
        moves.append(kwargs["dst"].value)
        return await move(*args, **kwargs)

    monkeypatch.setattr(persistence, "transition_run", keep)
    start = len(w.log.entries)
    job(w, Scripted(), "resume_input", dedup_key=key)
    assert moves == ["QUEUED", "RETRIEVING", "FAILED"]  # the worker's only path to FAILED from AWAITING_INPUT
    assert not [e for e in w.log.entries[start:] if e.startswith("mcp:")]  # refused before any read


def test_a_stray_newer_head_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """DoD 2 (R108): a checkpoint written after the stored one, as a stale writer could, is not what a resume reads."""
    w = world(monkeypatch)
    job(w, Scripted())
    stored = w.run["checkpoint_id"]
    graph = build.build_graph(w.saver)
    stray = asyncio.run(graph.aupdate_state(build.config(THREAD, None), {"run_state": "FAILED"}))
    stray_id = stray["configurable"]["checkpoint_id"]
    assert snapshot(w, None).values["run_state"] == "FAILED"  # the thread's head is the stray now
    approve(w)
    job(w, Scripted(), "execute")
    assert "mcp:create_incident" in w.log.entries  # the stray's FAILED would have published instead
    assert w.run["checkpoint_id"] not in (stored, stray_id)
    lineage = snapshot(w, w.run["checkpoint_id"])
    while lineage.parent_config is not None and lineage.config["configurable"]["checkpoint_id"] != stored:
        lineage = snapshot(w, lineage.parent_config["configurable"]["checkpoint_id"])
    assert lineage.config["configurable"]["checkpoint_id"] == stored  # the new branch grows from the stored id


def test_a_run_interrupted_twice_mid_draft_resumes_from_the_stored_checkpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ruling 12, review note 2 ("two crashes in a row"): each lost lease hands the job back; each next owner forks
    from the stored checkpoint, retrieves again (its holds are gone, BS:423) and drafts; one manifest in all."""
    w = world(monkeypatch)
    for _ in range(2):
        handed_back(w, Scripted(LeaseLost("lost mid-draft")))
        assert w.run["state"] == "DRAFTING"
    before = len(transitions(w))
    job(w, Scripted())
    assert w.run["state"] == "AWAITING_APPROVAL"
    assert w.contexts[-1].trace[:3] == ["draft_with_langchain", "route_request", "retrieve_evidence"]
    assert len(transitions(w)) == before  # RETRIEVING -> DRAFTING is not repeated (only the freeze moved it)
    assert w.log.entries.count("insert") == 2  # one manifest (the first job's) and one drafts row (the freeze)
    sources = {c.metadata.get("source") for c in w.saver.list(build.config(THREAD, None))}
    assert "fork" in sources  # crash recovery forks (SA:214)


def test_a_missing_stored_checkpoint_fails_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(monkeypatch, {**RUN, "state": "DRAFTING", "checkpoint_id": "no-such-checkpoint"})
    moves: list[tuple[str, Any]] = []
    move = persistence.transition_run

    async def keep(*args: Any, **kwargs: Any) -> Any:
        moves.append((kwargs["dst"].value, kwargs.get("detail")))
        return await move(*args, **kwargs)

    monkeypatch.setattr(persistence, "transition_run", keep)
    job(w, Scripted())
    assert moves == [("FAILED", {"message": nodes.CHECKPOINT_MISSING})] and w.log.entries[-1] == "release_lease"


@pytest.mark.parametrize("draft", [None, QUESTION], ids=["proposal", "question"])
def test_no_checkpoint_holds_model_or_evidence_text(monkeypatch: pytest.MonkeyPatch, draft: ModelDraft | None) -> None:
    """R091 on the in-memory saver: every stored checkpoint, blob and pending write holds no draft or question text,
    no request text and no alert message (the live test greps the Postgres tables too)."""
    w = world(monkeypatch)
    job(w, Scripted(draft))
    stored = repr((w.saver.storage, w.saver.writes, w.saver.blobs))
    assert w.saver.storage and w.saver.blobs  # there is something to search
    for text in ("Review synthetic warnings", "Which hours?", "Bearing temperature", "Investigate the alerts"):
        assert text not in stored, text


class Failing:
    """mcp-read failing the status read `times` times with `failure`, then answering as Plan H's caller does."""

    def __init__(self, failure: McpCallFailed, times: int) -> None:
        self.failure, self.times, self.calls = failure, times, []

    async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(tool)
        if tool == "get_asset_status" and self.times:
            self.times -= 1
            raise self.failure
        return {"get_asset_status": STATUS, "get_recent_alerts": ALERTS, "search_procedures": SEARCH}[tool]


@pytest.mark.parametrize(
    ("failure", "times", "state", "message", "status_calls"),
    [
        (McpCallFailed("x", code=TRANSPORT, retryable=True), 2, "AWAITING_APPROVAL", None, 3),
        (McpCallFailed("x", code="UNAVAILABLE", retryable=True), 9, "FAILED", nodes.RETRIEVAL_FAILED, 3),
        (McpCallFailed("x", code=UNAUTHENTICATED), 9, "FAILED", nodes.READ_REFUSED, 1),
        (McpCallFailed("x", code="NOT_FOUND"), 9, "INSUFFICIENT_EVIDENCE", nodes.CONTEXT_MISSING, 1),
    ],
    ids=["two-retries-then-ok", "retries-spent", "token-refused", "asset-unknown"],
)
def test_reads_retry_transient_failures_only(
    monkeypatch: pytest.MonkeyPatch, failure: McpCallFailed, times: int, state: str, message: str, status_calls: int
) -> None:
    w = world(monkeypatch)
    moves: list[Any] = []
    move = persistence.transition_run

    async def keep(*args: Any, **kwargs: Any) -> Any:
        moves.append((kwargs["dst"].value, (kwargs.get("detail") or {}).get("message")))
        return await move(*args, **kwargs)

    monkeypatch.setattr(persistence, "transition_run", keep)
    caller = Failing(failure, times)
    job(w, FakeDraftGenerator(), mcp=caller)
    assert w.run["state"] == state and caller.calls.count("get_asset_status") == status_calls
    if message is not None:
        assert moves[-1] == (state, message)


def test_the_router_rereads_the_runs_dimensions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Round 1, I1: route_request routes on the database's state, intent, decision and attempt, never on what an
    earlier node or a forked checkpoint left in the graph state."""
    w = world(monkeypatch, {**RUN, "state": "EXECUTING"})
    deps, lease = make(w.log)
    ctx = Context(deps, dict(JOB), lease)
    stale = {**initial(RUN_ID), "run_state": "QUEUED", "decision_present": False, "attempt_state": None}
    update = asyncio.run(nodes.route_request(stale, SimpleNamespace(context=ctx)))
    assert {k: update[k] for k in ("run_state", "intent", "decision_present", "attempt_state")} == {
        "run_state": "EXECUTING",
        "intent": "investigate",
        "decision_present": True,
        "attempt_state": "SENT",
    }
    assert "graph_facts" in w.log.entries


def test_an_approved_run_resumed_from_before_its_freeze_executes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Round 1, I1's scenario: the freeze commits, the lease is lost at the next checkpoint store, so the stored id is
    the checkpoint before validate_and_freeze (no interrupt). After the approval, the execute job forks from it; the
    lost hold sends the run back to the router, which rereads APPROVED with its decision, and the proposal runs."""
    w = world(monkeypatch)
    lose_once_after(monkeypatch, w, "freeze_proposal")
    handed_back(w, Scripted())
    assert w.run["state"] == "AWAITING_APPROVAL"
    assert snapshot(w, w.run["checkpoint_id"]).next == ("validate_and_freeze",)
    approve(w)
    job(w, Scripted(), "execute")
    assert w.log.entries.count("mcp:create_incident") == 1 and w.log.entries[-1] == "release_lease"


def test_an_execute_job_with_a_decision_for_another_proposal_runs_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Round 1, M1: the resume value is checked against the database first; a latest approval that names another
    proposal than the run's active one ends the job with no graph run, no transition and no write call."""
    w = world(monkeypatch)
    job(w, Scripted())
    approve(w, proposal=uuid4())
    moves = len(transitions(w))
    start = len(w.log.entries)
    job(w, Scripted(), "execute")
    assert "mcp:create_incident" not in w.log.entries and len(transitions(w)) == moves
    assert "store_checkpoint_id" not in w.log.entries[start:] and w.log.entries[-1] == "release_lease"


def test_a_hold_lost_after_a_completed_draft_is_drafted_again(monkeypatch: pytest.MonkeyPatch) -> None:
    """Round 1, M4: the draft completed, the lease was lost at the next checkpoint store, so the stored id is still the
    checkpoint before the draft node; the next owner resumes there with no hold, retrieves again and asks the route a
    second time (a second generation for the run: BS:554/555, debt -> T29)."""
    w = world(monkeypatch)
    lose_once_after(monkeypatch, w, "release_model_permit")
    first = Scripted()
    handed_back(w, first)
    assert w.run["state"] == "DRAFTING" and len(first.requests) == 1
    second = Scripted()
    job(w, second)
    assert len(second.requests) == 1 and w.run["state"] == "AWAITING_APPROVAL"
    assert w.contexts[-1].trace[:3] == ["draft_with_langchain", "route_request", "retrieve_evidence"]
````

Edit 46 (`tests/plan_p/test_investigate_drafting.py`), replace:

````python
run manifest written after the model call or outside the DRAFTING unit, or without the route's digest; a permit
taken twice for one draft (the repair must share the first pass's hold); a failing real route that falls back to a
fake draft or freezes anything; an outage or an exhausted repair that is not a templated FAILED; an abstention that
is not INSUFFICIENT_EVIDENCE; an answer or a clarifying question frozen as a proposal before T20 routes them; and a
draft that claims success turning into an `action.*` event, a status or anything but a proposal awaiting review.
"""

import asyncio
````

with:

````python
run manifest written after the model call or outside the DRAFTING unit, or without the route's digest; a permit
taken twice for one draft (the repair must share the first pass's hold); a failing real route that falls back to a
fake draft or freezes anything; an outage or an exhausted repair that is not a templated FAILED; an abstention that
is not INSUFFICIENT_EVIDENCE; an answer or a clarifying question frozen as a proposal instead of ending ANSWERED or
waiting for input (T20 routes them); and a draft that claims success turning into an `action.*` event, a status or
anything but a proposal awaiting review. Since T20 the handler runs the graph (`ops_worker.graph`), so the reads are
the asset status, the alerts and the search, each between its tool events.
"""

import asyncio
````

Edit 47 (`tests/plan_p/test_investigate_drafting.py`), replace:

````python
from ops_core.routing import ModelRoute
from ops_worker import handlers
from ops_worker.drafting import FakeDraftGenerator, ModelUnavailable
from ops_worker.ollama_drafting import OllamaDraftGenerator, Reply

from tests.plan_h.test_worker_units import JOB, RUN, RUN_ID, Log, make, patch
````

with:

````python
from ops_core.routing import ModelRoute
from ops_worker import handlers
from ops_worker.drafting import FakeDraftGenerator, ModelUnavailable
from ops_worker.graph import nodes
from ops_worker.ollama_drafting import OllamaDraftGenerator, Reply

from tests.plan_h.test_worker_units import JOB, RUN, RUN_ID, Log, make, patch
````

Edit 48 (`tests/plan_p/test_investigate_drafting.py`), replace:

````python
)


def recorded(monkeypatch: pytest.MonkeyPatch, log: Log) -> dict[str, list[dict[str, Any]]]:
    """Plan H's recorders, plus the arguments of every transition and event (the plain recorders drop them)."""
    patch(monkeypatch, log)
    seen: dict[str, list[dict[str, Any]]] = {"transition_run": [], "append_event": []}

    def keeping(name: str, result: Any) -> Any:
        async def call(*_: Any, **kwargs: Any) -> Any:
            log.entries.append(name)
            seen[name].append(kwargs)
            return result

        return call

    monkeypatch.setattr(persistence, "transition_run", keeping("transition_run", 2))
    monkeypatch.setattr(persistence, "append_event", keeping("append_event", None))
    return seen


````

with:

````python
)


def recorded(
    monkeypatch: pytest.MonkeyPatch, log: Log, run: dict[str, Any] | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Plan H's recorders, plus the arguments of every transition and event (the plain recorders drop them); each
    call still goes through Plan H's recorder, which keeps the run row's state (T20: the nodes reread it)."""
    patch(monkeypatch, log, run=run)
    seen: dict[str, list[dict[str, Any]]] = {"transition_run": [], "append_event": []}

    def keeping(name: str) -> Any:
        inner = getattr(persistence, name)

        async def call(*args: Any, **kwargs: Any) -> Any:
            seen[name].append(kwargs)
            return await inner(*args, **kwargs)

        return call

    monkeypatch.setattr(persistence, "transition_run", keeping("transition_run"))
    monkeypatch.setattr(persistence, "append_event", keeping("append_event"))
    return seen


````

Edit 49 (`tests/plan_p/test_investigate_drafting.py`), replace:

````python
    deps.generator, _ = real(Reply(GOOD))
    asyncio.run(handlers.handle(deps, dict(JOB), lease))
    drafting = next(u for u in log.units() if "insert_run_manifest" in u)
    assert drafting == ["set_tenant", "fenced", "transition_run", "insert_run_manifest"]
    assert log.entries.index("insert_run_manifest") < log.entries.index("take_model_permit")
    (manifest,) = inserted
    assert manifest.model_route is ModelRoute.QWEN3_8B and manifest.model_digest == PINS.digest
````

with:

````python
    deps.generator, _ = real(Reply(GOOD))
    asyncio.run(handlers.handle(deps, dict(JOB), lease))
    drafting = next(u for u in log.units() if "insert_run_manifest" in u)
    assert drafting == ["set_tenant", "fenced", "transition_run", "run_manifest_exists", "insert_run_manifest"]
    assert log.entries.index("insert_run_manifest") < log.entries.index("take_model_permit")
    (manifest,) = inserted
    assert manifest.model_route is ModelRoute.QWEN3_8B and manifest.model_digest == PINS.digest
````

Edit 50 (`tests/plan_p/test_investigate_drafting.py`), replace:

````python
    log, seen = investigate(monkeypatch, generator)
    assert ends(seen) == ("FAILED", message)
    assert "freeze_proposal" not in log.entries  # R041: no fake draft, no proposal, nothing frozen
    assert [e["type"].value for e in seen["append_event"]] == ["tool.started", "tool.completed"]
    assert log.entries[-1] == "release_lease" and log.entries.count("release_model_permit") == 1


````

with:

````python
    log, seen = investigate(monkeypatch, generator)
    assert ends(seen) == ("FAILED", message)
    assert "freeze_proposal" not in log.entries  # R041: no fake draft, no proposal, nothing frozen
    assert [e["type"].value for e in seen["append_event"]] == ["tool.started", "tool.completed"] * 3
    assert log.entries[-1] == "release_lease" and log.entries.count("release_model_permit") == 1


````

Edit 51 (`tests/plan_p/test_investigate_drafting.py`), replace:

````python
    ("draft", "state", "message"),
    [
        ({"kind": "abstain", "evidence_refs": []}, "INSUFFICIENT_EVIDENCE", handlers.ABSTAINED),
        ({"kind": "abstain", "evidence_refs": [], "question": "Which hours?"}, "FAILED", handlers.NOT_ROUTED),
        ({"kind": "answer"}, "FAILED", handlers.NOT_ROUTED),
    ],
)
def test_each_kind_that_is_not_a_proposal_ends_the_run_without_freezing(
    monkeypatch: pytest.MonkeyPatch, draft: dict[str, Any], state: str, message: str
) -> None:
    generator, _ = real(Reply(json.dumps({**json.loads(GOOD), **draft})))
    log, seen = investigate(monkeypatch, generator)
    assert ends(seen) == (state, message) and "freeze_proposal" not in log.entries
    assert not [e for e in seen["append_event"] if e["type"].value == "explanation.ready"]


def test_a_draft_claiming_success_is_only_a_proposal_awaiting_review(monkeypatch: pytest.MonkeyPatch) -> None:
````

with:

````python
    ("draft", "state", "message"),
    [
        ({"kind": "abstain", "evidence_refs": []}, "INSUFFICIENT_EVIDENCE", handlers.ABSTAINED),
        ({"kind": "abstain", "evidence_refs": [], "question": "Which hours?"}, "AWAITING_INPUT", "Which hours?"),
        ({"kind": "answer"}, "ANSWERED", nodes.ANSWERED),
    ],
)
def test_each_kind_that_is_not_a_proposal_ends_the_run_without_freezing(
    monkeypatch: pytest.MonkeyPatch, draft: dict[str, Any], state: str, message: str
) -> None:
    """T20 routes the kinds Plan P left FAILED: a question waits for input (its event carries it), an answer ends
    ANSWERED with its summary in explanation.ready; neither freezes anything."""
    generator, _ = real(Reply(json.dumps({**json.loads(GOOD), **draft})))
    log, seen = investigate(monkeypatch, generator)
    assert ends(seen) == (state, message) and "freeze_proposal" not in log.entries
    explained = [e["payload"]["message"] for e in seen["append_event"] if e["type"].value == "explanation.ready"]
    assert explained == (["The review rule applies."] if state == "ANSWERED" else [])


def test_a_draft_claiming_success_is_only_a_proposal_awaiting_review(monkeypatch: pytest.MonkeyPatch) -> None:
````

Edit 52 (`tests/plan_p/test_investigate_drafting.py`), replace:

````python
    log, seen = investigate(monkeypatch, generator)
    assert log.entries.count("freeze_proposal") == 1 and "mark_unknown" not in log.entries
    types = [e["type"].value for e in seen["append_event"]]
    assert types == ["tool.started", "tool.completed", "explanation.ready"]
    explanation = seen["append_event"][-1]["payload"]
    assert explanation["message"] == "Drafted by model route qwen3:8b (prompt incident-draft-v2)."  # a template
    assert [t["dst"].value for t in seen["transition_run"]] == ["RETRIEVING", "DRAFTING"]
````

with:

````python
    log, seen = investigate(monkeypatch, generator)
    assert log.entries.count("freeze_proposal") == 1 and "mark_unknown" not in log.entries
    types = [e["type"].value for e in seen["append_event"]]
    assert types == ["tool.started", "tool.completed"] * 3 + ["explanation.ready"]
    explanation = seen["append_event"][-1]["payload"]
    assert explanation["message"] == "Drafted by model route qwen3:8b (prompt incident-draft-v2)."  # a template
    assert [t["dst"].value for t in seen["transition_run"]] == ["RETRIEVING", "DRAFTING"]
````

Edit 53 (`tests/plan_p/test_investigate_drafting.py`), replace:

````python


def stepped(
    monkeypatch: pytest.MonkeyPatch, log: Log, *, permit_wait: float
) -> tuple[handlers.Deps, Lease, list[dict[str, Any]]]:
    """A lease on a clock the test moves: taking the model permit takes `permit_wait` seconds of it. The lease is long
    enough that its local deadline is not what these tests meet (the heartbeat would renew it)."""
    seen = recorded(monkeypatch, log)
    now = [100.0]

    def clock() -> float:
````

with:

````python


def stepped(
    monkeypatch: pytest.MonkeyPatch, log: Log, *, permit_wait: float, run: dict[str, Any] | None = None
) -> tuple[handlers.Deps, Lease, dict[str, list[dict[str, Any]]]]:
    """A lease on a clock the test moves: taking the model permit takes `permit_wait` seconds of it. The lease is long
    enough that its local deadline is not what these tests meet (the heartbeat would renew it)."""
    seen = recorded(monkeypatch, log, run)
    now = [100.0]

    def clock() -> float:
````

Edit 54 (`tests/plan_p/test_investigate_drafting.py`), replace:

````python

def test_an_answer_only_run_asks_for_an_answer_only_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    log = Log()
    deps, lease, _ = stepped(monkeypatch, log, permit_wait=0.0)
    monkeypatch.setattr(persistence, "run_row", _answer_only_row)
    deps.generator = recording = Recording(log)
    asyncio.run(handlers.handle(deps, dict(JOB), lease))
    assert [r.answer_only for r in recording.requests] == [True]
    assert "freeze_proposal" not in log.entries  # SA:453: an answer_only run never freezes a proposal


async def _answer_only_row(_conn: Any, _run_id: Any, *, lock: bool = False) -> dict[str, Any]:
    return {**RUN, "intent": "answer_only"}


def test_the_last_seconds_of_the_budget_still_reach_the_route_as_the_attempt_limit(
````

with:

````python

def test_an_answer_only_run_asks_for_an_answer_only_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    log = Log()
    deps, lease, seen = stepped(monkeypatch, log, permit_wait=0.0, run={**RUN, "intent": "answer_only"})
    deps.generator = recording = Recording(log)
    asyncio.run(handlers.handle(deps, dict(JOB), lease))
    assert [r.answer_only for r in recording.requests] == [True]
    assert "freeze_proposal" not in log.entries  # SA:453: an answer_only run never freezes a proposal
    assert ends(seen) == ("ANSWERED", nodes.ANSWERED)  # the fake route answers an answer_only run (T20)


def test_the_last_seconds_of_the_budget_still_reach_the_route_as_the_attempt_limit(
````

Edit 55 (`tests/plan_p/test_worker_startup.py`), replace:

````python
"""The worker's start-up relation checks (T19; revision 0014), without a database.

Catches: the worker starting on a database that lacks `app.run_manifests`, which would claim jobs it could not
record a manifest for. The check is read off the order of `assert_relation` calls, stopped at the manifest table;
and an unset MODEL_MODE ending in a traceback instead of the logged refusal to start.
"""

from types import SimpleNamespace
````

with:

````python
"""The worker's start-up relation checks (T19; revision 0014), without a database.

Catches: the worker starting on a database that lacks `app.run_manifests`, which would claim jobs it could not
record a manifest for, or `checkpoints.checkpoints` (revision 0015, T20), whose graph could not persist. The check is
read off the order of `assert_relation` calls, stopped at the checkpoint table, the last one asked for; and an unset
MODEL_MODE ending in a traceback instead of the logged refusal to start.
"""

from types import SimpleNamespace
````

Edit 56 (`tests/plan_p/test_worker_startup.py`), replace:

````python

    async def assert_relation(_: object, name: str) -> None:
        asked.append(name)
        if name == "app.run_manifests":
            raise Stop

    fake_settings = SimpleNamespace(
````

with:

````python

    async def assert_relation(_: object, name: str) -> None:
        asked.append(name)
        if name == "checkpoints.checkpoints":
            raise Stop

    fake_settings = SimpleNamespace(
````

Edit 57 (`tests/plan_p/test_worker_startup.py`), replace:

````python
    monkeypatch.setattr(persistence, "assert_relation", assert_relation)
    with pytest.raises(Stop):
        await main._main()
    assert asked == ["app.model_permit", "app.run_manifests"]


@pytest.mark.asyncio
````

with:

````python
    monkeypatch.setattr(persistence, "assert_relation", assert_relation)
    with pytest.raises(Stop):
        await main._main()
    assert asked == ["app.model_permit", "app.run_manifests", "checkpoints.checkpoints"]


@pytest.mark.asyncio
````

Edit 58 (`tests/plan_j/test_worker_azp.py`), replace:

````python
    monkeypatch: pytest.MonkeyPatch, job_type: str, state: str
) -> None:
    log = Log()
    patch(monkeypatch, log)
    minted = capture_mints(monkeypatch)

    async def run_row(_conn: Any, _run_id: Any, *, lock: bool = False) -> dict[str, Any]:
        return {**RUN, "state": state}

    monkeypatch.setattr(persistence, "run_row", run_row)
    deps, lease = make(log)
    deps.workload_azp = "ops-worker-renamed"
    asyncio.run(handlers.handle(deps, {**JOB, "type": job_type}, lease))
````

with:

````python
    monkeypatch: pytest.MonkeyPatch, job_type: str, state: str
) -> None:
    log = Log()
    patch(monkeypatch, log, run={**RUN, "state": state})
    minted = capture_mints(monkeypatch)
    deps, lease = make(log)
    deps.workload_azp = "ops-worker-renamed"
    asyncio.run(handlers.handle(deps, {**JOB, "type": job_type}, lease))
````

Edit 59 (`tests/plan_f/test_grant_deferred.py`), replace:

````python
import pytest
from ops_core import persistence, settings
from ops_core.lease import Lease
from ops_core.states import RunState
from ops_mcp_write.server import refusal_error
from ops_worker import handlers
from ops_worker.handlers import EXECUTE_RETRY_SECONDS, is_deferred
````

with:

````python
import pytest
from ops_core import persistence, settings
from ops_core.lease import Lease
from ops_core.states import Intent, RunState
from ops_mcp_write.server import refusal_error
from ops_worker import handlers
from ops_worker.handlers import EXECUTE_RETRY_SECONDS, is_deferred
````

Edit 60 (`tests/plan_f/test_grant_deferred.py`), replace:

````python
    async def mark_unknown(*args: Any) -> None:
        calls["mark_unknown"].append(args)

    for name, fn in {
        "run_row": run_row,
        "mint_handle": mint_handle,
````

with:

````python
    async def mark_unknown(*args: Any) -> None:
        calls["mark_unknown"].append(args)

    async def graph_facts(_conn: Any, _rid: UUID) -> persistence.GraphFacts:  # T20: the graph's router reads these
        return persistence.GraphFacts(RunState.APPROVED, Intent.INVESTIGATE, True, None, None)

    async def store_checkpoint_id(_conn: Any, _rid: UUID, _checkpoint_id: str) -> None:
        return None

    for name, fn in {
        "run_row": run_row,
        "mint_handle": mint_handle,
````

Edit 61 (`tests/plan_f/test_grant_deferred.py`), replace:

````python
        "fenced": fenced,
        "release_lease": release_lease,
        "mark_unknown": mark_unknown,
    }.items():
        monkeypatch.setattr(persistence, name, fn)
    conn: Any = FakeConn()
````

with:

````python
        "fenced": fenced,
        "release_lease": release_lease,
        "mark_unknown": mark_unknown,
        "graph_facts": graph_facts,
        "store_checkpoint_id": store_checkpoint_id,
    }.items():
        monkeypatch.setattr(persistence, name, fn)
    conn: Any = FakeConn()
````

Edit 62 (`tests/plan_f/test_grant_deferred.py`), replace:

````python
    )
    job = {"id": job_id, "run_id": run_id, "tenant_id": tenant, "type": "execute"}
    assert await handlers.execute(deps, job, lease) is False
    assert mcp.calls == ["create_incident"] and calls["fenced"] == [2]
    assert calls["release_lease"] == [(2, job_id, EXECUTE_RETRY_SECONDS)]
    assert EXECUTE_RETRY_SECONDS == 30 and calls["mark_unknown"] == []
````

with:

````python
    )
    job = {"id": job_id, "run_id": run_id, "tenant_id": tenant, "type": "execute"}
    assert await handlers.execute(deps, job, lease) is False
    assert mcp.calls == ["create_incident"] and set(calls["fenced"]) == {2}  # every unit at the job's fence
    assert calls["release_lease"] == [(2, job_id, EXECUTE_RETRY_SECONDS)]
    assert EXECUTE_RETRY_SECONDS == 30 and calls["mark_unknown"] == []
````

Edit 63 (`tests/plan_m/test_worker_r029.py`), replace:

````python
    log = Log()
    patch(monkeypatch, log)
    moves: list[tuple[Any, Any, Any]] = []

    async def transition_run(_conn: Any, *, run_id: Any, src: Any, dst: Any, detail: Any = None) -> int:
        moves.append((src, dst, detail))
        return 2

    class Refusing:
        async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
````

with:

````python
    log = Log()
    patch(monkeypatch, log)
    moves: list[tuple[Any, Any, Any]] = []
    kept = persistence.transition_run  # Plan H's recorder keeps the run row, which the graph's router rereads (T20)

    async def transition_run(_conn: Any, *, run_id: Any, src: Any, dst: Any, detail: Any = None) -> int:
        moves.append((src, dst, detail))
        return int(await kept(_conn, run_id=run_id, src=src, dst=dst, detail=detail))

    class Refusing:
        async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
````

Edit 64 (`tests/plan_m/test_worker_r029.py`), replace:

````python
    log = Log()
    patch(monkeypatch, log)
    moves: list[tuple[Any, Any, Any]] = []

    async def transition_run(_conn: Any, *, run_id: Any, src: Any, dst: Any, detail: Any = None) -> int:
        moves.append((src, dst, detail))
        return 2

    monkeypatch.setattr(persistence, "transition_run", transition_run)
    db = Database(UnitConn())
````

with:

````python
    log = Log()
    patch(monkeypatch, log)
    moves: list[tuple[Any, Any, Any]] = []
    kept = persistence.transition_run  # Plan H's recorder keeps the run row, which the graph's router rereads (T20)

    async def transition_run(_conn: Any, *, run_id: Any, src: Any, dst: Any, detail: Any = None) -> int:
        moves.append((src, dst, detail))
        return int(await kept(_conn, run_id=run_id, src=src, dst=dst, detail=detail))

    monkeypatch.setattr(persistence, "transition_run", transition_run)
    db = Database(UnitConn())
````

Run `PYTHONUTF8=1 uv run python -m pytest tests/plan_q/test_graph_routes.py tests/plan_q/test_graph_flow.py
tests/plan_h/test_worker_units.py -q -p no:cacheprovider < /dev/null` → RED, `2 errors during collection`, both
`ModuleNotFoundError: No module named 'ops_worker.graph'`.

- [ ] **Step 2: The graph, the handlers and the saver's connection**

Create `worker/src/ops_worker/deps.py`:

````python
"""What a job handler and the graph's nodes need (`handlers.Deps` re-exports it): one module both import, so the graph
package does not import the handlers that drive it."""

from __future__ import annotations

from dataclasses import dataclass, field

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from ops_core import persistence
from ops_core.settings import LeaseSettings, Urls

from ops_worker.drafting import DraftGenerator
from ops_worker.heartbeat import Heartbeat
from ops_worker.mcp import McpCaller


@dataclass
class Deps:
    """What a handler needs: the loop's connection, the MCP client, the model route, the server URLs, the worker's
    name (the lease owner), the workload client its tokens are issued to (the `azp` a handle is bound to), the lease
    settings, the heartbeat that renews the lease while a job runs, and the checkpoint saver the graph persists to.

    The saver defaults to LangGraph's in-memory one, which unit tests use; the worker passes the Postgres saver on its
    own connection (`main._main`, SA:559-562)."""

    conn: persistence.Conn
    mcp: McpCaller
    generator: DraftGenerator
    urls: Urls
    worker_name: str
    workload_azp: str  # the token source's client id (Plan J ruling 17): _resolve_handle compares it with the token's
    leases: LeaseSettings = field(default_factory=LeaseSettings)
    heartbeat: Heartbeat | None = None  # main.run_job hands it each claimed lease; tests may run without one
    saver: BaseCheckpointSaver[str] = field(default_factory=InMemorySaver)
````

Create `worker/src/ops_worker/graph/__init__.py`:

````python
"""The orchestrator: one explicit LangGraph graph per run (AM-12 SA:207; docs/ARCHITECTURE.md §3).

`state` holds the graph's state and the per-run context, `nodes` the ten nodes, `build` the wiring generated from
the route table and the driver that stores each confirmed checkpoint id under the lease fence.
"""
````

Create `worker/src/ops_worker/graph/state.py`:

````python
"""The worker graph's state and the context its nodes run with (AM-12 SA:207-218, SA:563).

Graph state is identifiers, verdicts and enum values only (R091): the run's id and its last-read state, the router's
other dimensions, a draft's id and kind, and the ids of the clarification events this thread has asked and resumed.
No evidence excerpt, model text, question or answer is ever a state value, so no checkpoint holds one. What a node
needs beyond that lives in the per-graph-run `Context` (the job, the lease, the dependencies and `Held`, the
worker's in-memory hold of the evidence bundle and the validated draft between the node that makes them and the node
that consumes them, SA:496).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict
from uuid import UUID

from ops_core.contracts import ModelDraft
from ops_core.lease import Lease
from ops_core.routing import DraftKind, Evidence, GraphKey
from ops_core.states import AttemptState, Intent, RunState

from ops_worker.deps import Deps
from ops_worker.evidence import Bundle


class RunGraphState(TypedDict):
    """One run's graph state (every key is replaced whole by the node that returns it)."""

    run_id: str
    run_state: str
    intent: str
    context_resolved: bool
    evidence: str
    draft_id: str | None
    draft_kind: str
    asked: list[str]  # the clarification.requested event ids this thread has been resumed from, oldest first
    decision_present: bool
    attempt_state: str | None


def initial(run_id: UUID) -> RunGraphState:
    """A graph run's input: every key reset, so nothing a stray earlier graph run left on the thread carries over;
    `load_run` replaces the placeholders with the run's own facts."""
    return RunGraphState(
        run_id=str(run_id),
        run_state=RunState.QUEUED.value,
        intent=Intent.INVESTIGATE.value,
        context_resolved=True,
        evidence=Evidence.UNKNOWN.value,
        draft_id=None,
        draft_kind=DraftKind.NONE.value,
        asked=[],
        decision_present=False,
        attempt_state=None,
    )


def key(state: RunGraphState) -> GraphKey:
    """The graph router's key (SA:377) read off the state."""
    attempt = state["attempt_state"]
    return GraphKey(
        RunState(state["run_state"]),
        Intent(state["intent"]),
        state["context_resolved"],
        Evidence(state["evidence"]),
        DraftKind(state["draft_kind"]),
        state["decision_present"],
        None if attempt is None else AttemptState(attempt),
    )


@dataclass
class HeldDraft:
    """A validated draft between `draft_with_langchain` and the node its kind routes to; its id becomes the
    `drafts` row's."""

    draft_id: UUID
    draft: ModelDraft


@dataclass
class Held:
    """The worker's in-memory hold for one graph run (never checkpointed, SA:496)."""

    bundle: Bundle | None = None
    draft: HeldDraft | None = None


@dataclass
class Context:
    """What every node of one graph run receives (LangGraph's runtime context, never persisted): the dependencies,
    the job and the lease it runs under, the hold, and `trace`, the node names in the order they ran (R038's per-run
    node log, which the tests read)."""

    deps: Deps
    job: dict[str, Any]
    lease: Lease
    held: Held = field(default_factory=Held)
    trace: list[str] = field(default_factory=list)
````

Create `worker/src/ops_worker/graph/nodes.py`:

````python
"""The worker graph's nodes (AM-12 SA:207): deterministic Python around the definer functions, one model call and the
MCP reads and writes.

Every node rereads the run before it acts (SA:215: LangGraph re-runs a node from its start on resume, so each must be
idempotent against authoritative state) and returns the run state it left, so `route_request` routes on what the
database says. Every unit that writes opens with `persistence.fenced`; every MCP call, model call and back-off sleep
is a lease effect (`Lease.effect`, SA:195); state changes go through `transition_run`, `freeze_proposal` and
`mark_unknown` as role `worker` (AM-20.3). Only `draft_with_langchain` calls the model; only `retrieve_evidence` calls
mcp-read and only `execute_approved_proposal` calls mcp-write (`reconcile_outcome`'s calls arrive with T22).

Text stays out of graph state (R091): the evidence bundle and a validated draft are held in the graph run's
`Context.held` between the node that makes them and the node that consumes them; `route_request` notices a hold that
a resumed graph run no longer has and routes the run back through retrieval (BS:423). A question reaches the requester
inside its `clarification.requested` event and an answer inside its `explanation.ready` event (erratum 124); the
interrupts carry event and proposal ids only (SA:563).
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID, uuid4

from langgraph.runtime import Runtime
from langgraph.types import interrupt
from ops_core import persistence
from ops_core.canonical import canonical_sha256
from ops_core.contracts import ModelDraft
from ops_core.jobs import Server, Tool
from ops_core.lease import LeaseLost
from ops_core.outcomes import EventSource, EventType
from ops_core.routing import DraftKind, Evidence, GraphRoute, RunManifest, route_graph
from ops_core.states import Intent, RunState, freeze_allowed
from pydantic import ValidationError

from ops_worker import evidence, permit, proposals
from ops_worker.drafting import PROMPT_VERSION, DraftRequest, ModelOutputInvalid, ModelUnavailable
from ops_worker.evidence import Bundle
from ops_worker.graph.state import Context, HeldDraft, RunGraphState, key
from ops_worker.mcp import UNAUTHENTICATED, McpCallFailed

log = logging.getLogger("ops_worker")
QUERY_CHARS: Final = 500  # schemas/tools/search_procedures.input.schema.json maxLength
ALERT_LIMIT: Final = 20  # one page of the run's alerts; the bundle shows evidence.ALERTS_SHOWN of them
RETRIEVAL_MODE: Final = "lexical"  # the only mode the worker asks for; choosing it per run is TODO(T25)
READ_CALLS: Final = 6  # BS:552: at most 6 read calls per graph run, retries included
READ_RETRIES: Final = 2  # BS:552: at most 2 retries of one transient read
RETRY_SECONDS: Final = 0.5  # BS:562: the first back-off; doubled per retry, with jitter
CLARIFY_ROUNDS: Final = 2  # SA:137: at most two clarification rounds; a third question ends INSUFFICIENT_EVIDENCE
REPLY_CHARS: Final = 4000  # the message contract's bound (contracts.MessageText); the API checked it on the way in
ASSET_UNKNOWN: Final = "NOT_FOUND"  # mcp-read's code for an asset the asset service does not know (T16 ruling 15)
# The draft stops this long before the run's compute budget ends, so the freeze or the failure unit after it still
# runs inside the budget, before the heartbeat's own gate ("compute budget spent") could cancel the call.
BUDGET_MARGIN_SECONDS: Final = 5.0

# Templated outcomes (BS:516): never the model's text, never an exception's.
MODEL_UNAVAILABLE: Final = "the model route did not answer in time or could not be reached"
MODEL_INVALID: Final = "the model's draft failed validation after its one repair"
ABSTAINED: Final = "the model found the evidence insufficient"
DRAFTING_FAILED: Final = "drafting failed"
RETRIEVAL_FAILED: Final = "retrieval failed"
READ_REFUSED: Final = "retrieval failed: the read server refused the worker's token"
CONTEXT_MISSING: Final = "the asset is not known to the asset service"
EVIDENCE_INSUFFICIENT: Final = "no fresh asset status or no procedure section matched"
CLARIFY_LIMIT: Final = "the model asked a third clarifying question; the evidence stays insufficient"
ANSWERED: Final = "answered from the retrieved evidence; no incident was proposed"
RESUME_REFUSED: Final = "the clarification reply is not the latest answer to the run's latest question"
CHECKPOINT_MISSING: Final = "the stored checkpoint is missing; the run was not resumed"
WORKFLOW_FAILED: Final = "the workflow failed"

_S = RunState
# The worker's only ways to FAILED from a state that waits or works (transition_run, SA:451): AWAITING_INPUT may only
# go back to QUEUED, and QUEUED only on to RETRIEVING, so a run that cannot be resumed walks there first.
PATH_TO_FAILED: Final[dict[RunState, tuple[RunState, ...]]] = {
    _S.AWAITING_INPUT: (_S.QUEUED, _S.RETRIEVING, _S.FAILED),
    _S.QUEUED: (_S.RETRIEVING, _S.FAILED),
    _S.RETRIEVING: (_S.FAILED,),
    _S.DRAFTING: (_S.FAILED,),
}


# What a node returns when the graph run does not hold the draft or bundle the state names: the run goes back
# through retrieval and drafting (a second model call; nothing text-bearing was persisted, SA:496).
LOST: Final[dict[str, Any]] = {"draft_kind": DraftKind.NONE.value, "draft_id": None, "evidence": Evidence.UNKNOWN.value}


class Requeue(Exception):
    """mcp-write could not be reached, or deferred the grant: the execute job goes back on the queue (the handler's
    final unit re-queues it) and the graph run ends with its checkpoint before `execute_approved_proposal`."""


def _run_id(state: RunGraphState) -> UUID:
    return UUID(state["run_id"])


@asynccontextmanager
async def unit(ctx: Context, *, fence: bool = True) -> AsyncIterator[persistence.Conn]:
    """One transaction on the loop connection under the job's tenant; a writing unit opens with the fence (SA:176)."""
    conn = ctx.deps.conn
    async with conn.transaction():
        await persistence.set_tenant(conn, ctx.job["tenant_id"])  # the worker's reads and inserts are RLS-scoped
        if fence:
            await persistence.fenced(conn, ctx.lease)  # run_lease before runs (SA:188)
        yield conn


async def facts(ctx: Context, run_id: UUID) -> dict[str, Any]:
    """The router's authoritative dimensions, reread (SA:215)."""
    async with unit(ctx, fence=False) as conn:
        found = await persistence.graph_facts(conn, run_id)
    return {
        "run_state": found.state.value,
        "intent": found.intent.value,
        "decision_present": found.decision_present,
        "attempt_state": None if found.attempt_state is None else found.attempt_state.value,
    }


async def event(
    ctx: Context, type: EventType, payload: dict[str, Any], source: EventSource = EventSource.APPLICATION
) -> None:
    """One event in its own fenced unit."""
    async with unit(ctx) as conn:
        await persistence.append_event(conn, run_id=ctx.lease.run_id, type=type, payload=payload, source=source)


async def fail(ctx: Context, src: RunState, dst: RunState, message: str) -> dict[str, Any]:
    """A pre-grant end through transition_run, which emits the matching run.* event itself (SA:451)."""
    async with unit(ctx) as conn:
        await persistence.transition_run(conn, run_id=ctx.lease.run_id, src=src, dst=dst, detail={"message": message})
    return {"run_state": dst.value}


async def fail_from(conn: persistence.Conn, run_id: UUID, current: RunState, message: str) -> None:
    """FAILED with `message` from a waiting or working state, inside the caller's fenced unit (PATH_TO_FAILED)."""
    src = current
    for dst in PATH_TO_FAILED[current]:
        detail = {"message": message} if dst is RunState.FAILED else None
        await persistence.transition_run(conn, run_id=run_id, src=src, dst=dst, detail=detail)
        src = dst


async def insert_draft(conn: persistence.Conn, run: dict[str, Any], held: HeldDraft, sha256: str) -> None:
    """The `drafts` row (AM-20.2 drafts: ins): the draft's id, kind and hash, never its text (SA:496)."""
    await conn.execute(
        "INSERT INTO app.drafts (id, tenant_id, run_id, draft_sha256, validated, kind)"
        " VALUES (%s, %s, %s, %s, true, %s)",
        (held.draft_id, run["tenant_id"], run["run_id"], sha256, held.draft.kind),
    )


def draft_sha256(draft: ModelDraft) -> str:
    """The hash of a validated draft that is not a proposal (a proposal's is its frozen payload's)."""
    return canonical_sha256(draft.model_dump(mode="json"))


def _instant(value: Any) -> str:
    return str(value.isoformat()).replace("+00:00", "Z")


async def load_run(state: RunGraphState, runtime: Runtime[Context]) -> dict[str, Any]:
    """The graph run's first node: the run's facts from the database, nothing from the job."""
    runtime.context.trace.append("load_run")
    return await facts(runtime.context, _run_id(state))


async def route_request(state: RunGraphState, runtime: Runtime[Context]) -> dict[str, Any]:
    """The graph router's node (AM-16). The route itself is `ops_core.routing.route_graph`, read by the conditional
    edges `build.py` generates from the table. This node rereads the run's state, intent, decision and attempt on every
    hop (BS:305, SA:215: the router routes on authoritative dimensions only, whatever an earlier node or a forked
    checkpoint left in state; Plan Q round 1, I1), and drops a draft kind or an evidence verdict whose hold this graph
    run does not have (a resumed run in a new process), so the run retrieves again before it drafts (BS:423)."""
    ctx = runtime.context
    ctx.trace.append("route_request")
    update: dict[str, Any] = await facts(ctx, _run_id(state))
    if state["draft_kind"] != DraftKind.NONE.value and _held(ctx, state) is None:
        update |= LOST
    if state["evidence"] == Evidence.SUFFICIENT.value and ctx.held.bundle is None:
        update["evidence"] = Evidence.UNKNOWN.value
    return update


async def read(ctx: Context, handle: str, tool: Tool, arguments: dict[str, Any], calls: list[int]) -> dict[str, Any]:
    """One read tool, bracketed by its tool events, retried while the failure is transient (BS:552, BS:562).

    Raises:
        McpCallFailed: the read failed for good, or the run's read budget is spent.
    """
    await event(ctx, EventType.TOOL_STARTED, {"message": tool.value})
    retries = 0
    while True:
        calls[0] -= 1
        try:
            doc = await ctx.lease.effect(
                ctx.deps.mcp.call(ctx.deps.urls.mcp_read, handle=handle, tool=tool.value, arguments=arguments)
            )
            break
        except McpCallFailed as exc:
            if not exc.retryable or retries >= READ_RETRIES or calls[0] <= 0:
                raise
            retries += 1
            log.info("read %s failed (%s); retry %s", tool.value, exc.code, retries)
            await ctx.lease.effect(asyncio.sleep(RETRY_SECONDS * 2 ** (retries - 1) * random.uniform(0.5, 1.0)))
    await event(ctx, EventType.TOOL_COMPLETED, {"message": tool.value})
    return doc


async def request_text(conn: persistence.Conn, run: dict[str, Any]) -> str:
    """The confirmed request: the run's message and every clarification reply, oldest first (read, never held)."""
    text = await persistence.message_text(conn, run["message_id"])
    for _, payload in await persistence.run_events(conn, run["run_id"], EventType.CLARIFICATION_RECEIVED):
        reply = await persistence.message_text(conn, UUID(str(payload["message_id"])))
        text += f"\n\nClarification from the requester: {reply}"
    return text


async def retrieve_evidence(state: RunGraphState, runtime: Runtime[Context]) -> dict[str, Any]:
    """QUEUED → RETRIEVING, the three reads (status, the interval's alerts, the procedure search), the code rule, and
    RETRIEVING → DRAFTING with the run manifest when the evidence suffices (R038: every read completes first)."""
    ctx = runtime.context
    ctx.trace.append("retrieve_evidence")
    deps, lease, job = ctx.deps, ctx.lease, ctx.job
    async with unit(ctx) as conn:
        run = dict(await persistence.run_row(conn, _run_id(state), lock=True))
        current = RunState(run["state"])
        if current is RunState.QUEUED:
            await persistence.transition_run(conn, run_id=run["run_id"], src=current, dst=RunState.RETRIEVING)
            current = RunState.RETRIEVING
        elif current not in (RunState.RETRIEVING, RunState.DRAFTING):
            return {"run_state": current.value}
        text = await request_text(conn, run)
        handle = await persistence.mint_handle(
            conn, run_id=run["run_id"], job_id=job["id"], server=Server.READ, azp=deps.workload_azp, fence=lease.fence
        )
    calls = [READ_CALLS]
    try:
        try:
            status = await read(ctx, handle, Tool.GET_ASSET_STATUS, {"asset_id": run["asset_id"]}, calls)
        except McpCallFailed as exc:
            if exc.code != ASSET_UNKNOWN:
                raise
            return {"run_state": current.value, "context_resolved": False}  # contract erratum 4: no draft without it
        window = {"start_at": _instant(run["start_at"]), "end_at": _instant(run["end_at"])}
        alerts = await read(
            ctx, handle, Tool.GET_RECENT_ALERTS, {"asset_id": run["asset_id"], **window, "limit": ALERT_LIMIT}, calls
        )
        search = await read(
            ctx,
            handle,
            Tool.SEARCH_PROCEDURES,
            {"query": text[:QUERY_CHARS], "limit": 3, "mode": RETRIEVAL_MODE},
            calls,
        )
        procedures = proposals.evidence_from_search(search)
        # The manifest records the corpus version and the mode the tool reports it ran, so a result without them, or
        # with values the manifest refuses, is a retrieval failure like any other (T19).
        manifest = RunManifest(
            run_id=run["run_id"],
            model_route=deps.generator.route,
            model_digest=deps.generator.digest,
            prompt_version=PROMPT_VERSION,
            corpus_version=search["data"]["corpus_version"],
            retrieval_mode=search["data"]["retrieval_mode"],
        )
        verdict = evidence.sufficient(status, search)
        seen = evidence.observations(status, alerts)
    except McpCallFailed as exc:
        log.warning("job %s: retrieval failed (%s): %s", job["id"], exc.code, exc)
        # TODO(T22): a bounded re-queue of the job instead of FAILED once the in-node retries are spent.
        return await fail(
            ctx, current, RunState.FAILED, READ_REFUSED if exc.code == UNAUTHENTICATED else RETRIEVAL_FAILED
        )
    except (KeyError, TypeError, ValidationError, ValueError) as exc:
        log.warning("job %s: retrieval failed: %s", job["id"], exc)
        return await fail(ctx, current, RunState.FAILED, RETRIEVAL_FAILED)
    if not verdict:
        return {"run_state": current.value, "context_resolved": True, "evidence": Evidence.INSUFFICIENT.value}
    ctx.held.bundle = Bundle(text, procedures, seen, manifest)
    if current is RunState.RETRIEVING:
        async with unit(ctx) as conn:
            await persistence.transition_run(conn, run_id=run["run_id"], src=current, dst=RunState.DRAFTING)
            # Written before the model is called, so a run whose draft fails still records the route, digest, prompt
            # and corpus it used (R130); one immutable row per run, so a run retrieving again after a clarification
            # keeps the one it has (erratum 125). A run resumed in DRAFTING never gets here.
            if not await persistence.run_manifest_exists(conn, run["run_id"]):
                await persistence.insert_run_manifest(conn, tenant_id=run["tenant_id"], manifest=manifest)
    return {"run_state": RunState.DRAFTING.value, "context_resolved": True, "evidence": Evidence.SUFFICIENT.value}


async def draft_with_langchain(state: RunGraphState, runtime: Runtime[Context]) -> dict[str, Any]:
    """The model route's draft from the held bundle, under one model permit; the validated draft is held, its id and
    kind go into state. An outage, an invalid draft or any other failure ends the run FAILED with a template."""
    ctx = runtime.context
    ctx.trace.append("draft_with_langchain")
    deps, lease, bundle = ctx.deps, ctx.lease, ctx.held.bundle
    if bundle is None:  # a graph run resumed here in a new process: retrieve again first (BS:423)
        return {"evidence": Evidence.UNKNOWN.value}
    async with unit(ctx, fence=False) as conn:
        run = dict(await persistence.run_row(conn, _run_id(state)))
    if RunState(run["state"]) is not RunState.DRAFTING:
        return {"run_state": run["state"]}
    try:
        # One hold spans the first pass and its repair (model concurrency 1, BS:549; the TTL covers both, permit.py).
        async with permit.model_permit(deps.conn, holder=deps.worker_name, lease=lease):
            request = DraftRequest(
                asset_id=run["asset_id"],
                text=bundle.text,
                start_at=run["start_at"],
                end_at=run["end_at"],
                answer_only=Intent(run["intent"]) is Intent.ANSWER_ONLY,
                # BS:555's 90 s are the run's, counted from the claim as the heartbeat counts them, so the draft gets
                # what retrieval and the permit wait left, less a margin for the unit that follows it.
                remaining_seconds=deps.leases.compute_budget_seconds - lease.held_for() - BUDGET_MARGIN_SECONDS,
                observations=bundle.observations,
            )
            draft = await lease.effect(deps.generator.generate(request, bundle.procedures))
    except LeaseLost:
        raise  # the job is handed back; its next owner resumes the run from the stored checkpoint
    except ModelUnavailable as exc:
        log.warning("job %s: %s", ctx.job["id"], exc)
        return await fail(ctx, RunState.DRAFTING, RunState.FAILED, MODEL_UNAVAILABLE)
    except ModelOutputInvalid as exc:
        # Rule names only: the invalid text is never logged or stored (SA:496).
        log.warning("job %s: draft invalid after one repair (%s)", ctx.job["id"], exc)
        return await fail(ctx, RunState.DRAFTING, RunState.FAILED, MODEL_INVALID)
    except Exception:
        log.exception("job %s: drafting failed", ctx.job["id"])
        return await fail(ctx, RunState.DRAFTING, RunState.FAILED, DRAFTING_FAILED)
    held = HeldDraft(uuid4(), draft)
    ctx.held.draft = held
    kind = DraftKind.QUESTION if draft.clarification_requested else DraftKind(draft.kind)
    return {"draft_id": str(held.draft_id), "draft_kind": kind.value}


def _held(ctx: Context, state: RunGraphState) -> HeldDraft | None:
    """The held draft the state names, or None when this graph run does not hold it (resumed in a new process)."""
    held = ctx.held.draft
    return held if held is not None and str(held.draft_id) == state["draft_id"] else None


async def validate_and_freeze(state: RunGraphState, runtime: Runtime[Context]) -> dict[str, Any]:
    """The held proposal frozen through `freeze_proposal` (SA:453) with its `drafts` row and `explanation.ready`, in
    one unit; the run moves to AWAITING_APPROVAL (or BLOCKED_REVIEW on a guard refusal)."""
    ctx = runtime.context
    ctx.trace.append("validate_and_freeze")
    held, bundle = _held(ctx, state), ctx.held.bundle
    if held is None or bundle is None:
        return dict(LOST)
    try:
        async with unit(ctx) as conn:
            run = dict(await persistence.run_row(conn, _run_id(state), lock=True))
            if RunState(run["state"]) is not RunState.DRAFTING:
                return {"run_state": run["state"]}
            freeze_allowed(Intent(run["intent"]))  # the table's intent gate, checked again where it matters (SA:453)
            frozen = proposals.build_proposal(
                tenant_id=run["tenant_id"],
                run_id=run["run_id"],
                proposal_id=uuid4(),
                revision=1,  # TODO(T21): the revision a re-entered run freezes (Plan Q ruling 13)
                asset_id=run["asset_id"],
                start_at=run["start_at"],
                end_at=run["end_at"],
                draft=held.draft,
                evidence=bundle.procedures,
                now=datetime.now(UTC).replace(microsecond=0),
                supersedes_run_id=run["supersedes_run_id"],
            )
            await insert_draft(conn, run, held, frozen.sha256)  # draft_sha256 is what freeze_proposal recomputes
            await persistence.append_event(
                conn,
                run_id=run["run_id"],
                type=EventType.EXPLANATION_READY,
                payload={
                    # A template naming the route and the prompt version (erratum 117), never the model's summary.
                    "message": (
                        f"Drafted by model route {bundle.manifest.model_route.value} "
                        f"(prompt {bundle.manifest.prompt_version})."
                    ),
                    "evidence_refs": list(frozen.payload.evidence_refs),
                },
                source=EventSource.MODEL_SUMMARY,
            )
            await persistence.freeze_proposal(
                conn,
                run_id=run["run_id"],
                draft_id=held.draft_id,
                payload_canonical=frozen.canonical,
                expires_at=frozen.payload.expires_at,
            )
            after = dict(await persistence.run_row(conn, run["run_id"]))
    except LeaseLost:
        raise
    except Exception:
        log.exception("job %s: freezing failed", ctx.job["id"])
        return await fail(ctx, RunState.DRAFTING, RunState.FAILED, DRAFTING_FAILED)
    ctx.held.draft = None
    return {"run_state": after["state"]}


async def await_clarification(state: RunGraphState, runtime: Runtime[Context]) -> dict[str, Any]:
    """Ask the held question and wait for the reply (SA:137, SA:147). Asking is one unit: the `drafts` row and
    DRAFTING → AWAITING_INPUT, whose `clarification.requested` event carries the question; a third question ends the
    run INSUFFICIENT_EVIDENCE instead. The node then interrupts with the question's event id (an id, SA:563), so the
    graph run ends and the handler releases the lease (R022). Resumed with a `clarification.received` event id
    (`Command(resume=...)`, SA:213), it re-runs from its start: the run is AWAITING_INPUT now, so it only checks that
    the reply is the latest answer to the latest question, rereads it, and moves the run back to QUEUED."""
    ctx = runtime.context
    ctx.trace.append("await_clarification")
    run_id = _run_id(state)
    async with unit(ctx, fence=False) as conn:
        run = dict(await persistence.run_row(conn, run_id))
        asked_before = len(await persistence.run_events(conn, run_id, EventType.CLARIFICATION_REQUESTED))
    current = RunState(run["state"])
    if current is RunState.DRAFTING:
        held = _held(ctx, state)
        if held is None:
            return dict(LOST)
        async with unit(ctx) as conn:
            await insert_draft(conn, run, held, draft_sha256(held.draft))
            if asked_before >= CLARIFY_ROUNDS:
                await persistence.transition_run(
                    conn,
                    run_id=run_id,
                    src=current,
                    dst=RunState.INSUFFICIENT_EVIDENCE,
                    detail={"message": CLARIFY_LIMIT},
                )
                ctx.held.draft = None
                return {"run_state": RunState.INSUFFICIENT_EVIDENCE.value}
            await persistence.transition_run(
                conn, run_id=run_id, src=current, dst=RunState.AWAITING_INPUT, detail={"message": held.draft.question}
            )
        ctx.held.draft = None
        current = RunState.AWAITING_INPUT
    if current is RunState.QUEUED:  # a resumed run whose reply was already taken: retrieve again
        async with unit(ctx, fence=False) as conn:  # the round it answered still counts (round 1, M7)
            requested = await persistence.run_events(conn, run_id, EventType.CLARIFICATION_REQUESTED)
        latest = [str(requested[-1][0])] if requested else []
        asked = state["asked"] + [q for q in latest if q not in state["asked"]]
        return {
            "run_state": current.value,
            "asked": asked,
            "evidence": Evidence.UNKNOWN.value,
            "draft_kind": DraftKind.NONE.value,
        }
    if current is not RunState.AWAITING_INPUT:
        return {"run_state": current.value}
    async with unit(ctx, fence=False) as conn:
        requested = await persistence.run_events(conn, run_id, EventType.CLARIFICATION_REQUESTED)
    question = str(requested[-1][0])
    answer = interrupt(question)  # ends the graph run here; on resume, the clarification.received event's id
    async with unit(ctx) as conn:
        run = dict(await persistence.run_row(conn, run_id, lock=True))
        if RunState(run["state"]) is not RunState.AWAITING_INPUT:
            return {"run_state": run["state"]}  # cancelled meanwhile
        received = await persistence.run_events(conn, run_id, EventType.CLARIFICATION_RECEIVED)
        reply = received[-1] if received else None
        text = None
        if reply is not None and str(reply[0]) == str(answer) and reply[1].get("question_id") == question:
            text = await persistence.message_text(conn, UUID(str(reply[1]["message_id"])))
        if text is None or not 0 < len(text) <= REPLY_CHARS:
            await fail_from(conn, run_id, RunState.AWAITING_INPUT, RESUME_REFUSED)
            return {"run_state": RunState.FAILED.value}
        await persistence.transition_run(conn, run_id=run_id, src=RunState.AWAITING_INPUT, dst=RunState.QUEUED)
    asked = [*state["asked"], question]
    if len(asked) != len(requested):  # the database counts the rounds (SA:215); the state's list is a cross-check
        log.warning("run %s: %s questions asked, %s resumed in this thread", run_id, len(requested), len(asked))
    return {
        "run_state": RunState.QUEUED.value,
        "asked": asked,
        "context_resolved": True,
        "evidence": Evidence.UNKNOWN.value,
        "draft_kind": DraftKind.NONE.value,
        "draft_id": None,
    }


async def publish_state(state: RunGraphState, runtime: Runtime[Context]) -> dict[str, Any]:
    """The graph run's last node. On the `answer_only` route: the held answer's summary and citations in
    `explanation.ready` and DRAFTING → ANSWERED, with its `drafts` row, in one unit (SA:153, R114); on `abstain`:
    → INSUFFICIENT_EVIDENCE with the reason's template; on `publish`: nothing left to write."""
    ctx = runtime.context
    ctx.trace.append("publish_state")
    route = route_graph(key(state))
    run_id = _run_id(state)
    if route is GraphRoute.PUBLISH:
        return {}
    async with unit(ctx) as conn:
        run = dict(await persistence.run_row(conn, run_id, lock=True))
        current = RunState(run["state"])
        if current.value != state["run_state"]:
            return {"run_state": current.value}  # cancelled meanwhile
        held = _held(ctx, state)
        if route is GraphRoute.ANSWER_ONLY:
            if held is None:
                return dict(LOST)
            await insert_draft(conn, run, held, draft_sha256(held.draft))
            await persistence.append_event(
                conn,
                run_id=run_id,
                type=EventType.EXPLANATION_READY,
                # The validated answer itself (erratum 124): the requester's answer, cited, never a status claim.
                payload={"message": held.draft.summary, "evidence_refs": list(held.draft.evidence_refs)},
                source=EventSource.MODEL_SUMMARY,
            )
            dst, message = RunState.ANSWERED, ANSWERED
        else:
            if not state["context_resolved"]:
                message = CONTEXT_MISSING
            elif state["evidence"] == Evidence.INSUFFICIENT.value:
                message = EVIDENCE_INSUFFICIENT
            else:
                if held is not None:  # a lost abstention needs no text: only its drafts row is missing
                    await insert_draft(conn, run, held, draft_sha256(held.draft))
                message = ABSTAINED
            dst = RunState.INSUFFICIENT_EVIDENCE
        await persistence.transition_run(conn, run_id=run_id, src=current, dst=dst, detail={"message": message})
    ctx.held.draft = None
    return {"run_state": dst.value}


async def await_independent_decision(state: RunGraphState, runtime: Runtime[Context]) -> dict[str, Any]:
    """Wait for the reviewer (BS:330): reread, and while the run awaits approval interrupt with its proposal's id. The
    execute job that `record_decision` queues resumes the node, which rereads the decision rather than trusting the
    resume value."""
    ctx = runtime.context
    ctx.trace.append("await_independent_decision")
    run_id = _run_id(state)
    async with unit(ctx, fence=False) as conn:
        run = dict(await persistence.run_row(conn, run_id))
    if RunState(run["state"]) is RunState.AWAITING_APPROVAL:
        interrupt(str(run["active_proposal_id"]))
    return await facts(ctx, run_id)


def is_deferred(doc: dict[str, Any]) -> bool:
    """An `error` envelope whose code is GRANT_DEFERRED: the gate found the membership sync stale (T11), so the job
    is retried rather than closed."""
    error = doc.get("error") or {}
    return doc.get("status") == "error" and error.get("code") == "GRANT_DEFERRED"


async def execute_approved_proposal(state: RunGraphState, runtime: Runtime[Context]) -> dict[str, Any]:
    """`create_incident` on mcp-write for the approved run (T47's path, unchanged): mcp-write performs the grant, the
    dispatch and the outcome, and the worker records an UNKNOWN envelope through `mark_unknown`.

    Any other envelope counts as final, an `INVALID_HANDLE` included. When that refusal came from this worker's own
    lease lapsing during the call, the handler's final unit finds the lease not live and raises LeaseLost, so the job
    is handed back and the next owner runs it again (Plan H final review, I1).

    Raises:
        Requeue: mcp-write could not be reached, or deferred the grant.
    """
    ctx = runtime.context
    ctx.trace.append("execute_approved_proposal")
    deps, lease, job = ctx.deps, ctx.lease, ctx.job
    async with unit(ctx) as conn:
        run = dict(await persistence.run_row(conn, _run_id(state), lock=True))
        if RunState(run["state"]) not in (RunState.APPROVED, RunState.EXECUTING):
            return {"run_state": run["state"]}
        handle = await persistence.mint_handle(
            conn, run_id=run["run_id"], job_id=job["id"], server=Server.WRITE, azp=deps.workload_azp, fence=lease.fence
        )
    try:
        doc = await lease.effect(
            deps.mcp.call(
                deps.urls.mcp_write,
                handle=handle,
                tool=Tool.CREATE_INCIDENT.value,
                arguments={"proposal_id": str(run["active_proposal_id"])},
            )
        )
    except McpCallFailed as exc:
        # Before a grant the run is still APPROVED; after one it is EXECUTING and the retry resends under the same
        # action id. TODO(T22): bounded retries, reconciliation and AM-13's timeout path.
        log.warning("execute job %s: %s; re-queued", job["id"], exc)
        raise Requeue(str(exc)) from exc
    if is_deferred(doc):
        # TODO(T22): bounded retries (a sweeper that never returns re-queues this job every 30 s for ever).
        log.warning("execute job %s: grant deferred (stale membership sync); re-queued", job["id"])
        raise Requeue("grant deferred")
    data = doc.get("data") or {}
    log.info("execute job %s: %s %s", job["id"], doc.get("status"), data.get("status"))
    if doc.get("status") == "outcome" and data.get("status") == "UNKNOWN":  # an `error` envelope is never UNKNOWN
        await mark_unknown(ctx)
    return await facts(ctx, _run_id(state))


async def mark_unknown(ctx: Context) -> None:
    """EXECUTING → OUTCOME_UNKNOWN through `mark_unknown`, which takes the lease row FOR UPDATE itself and bumps the
    fence (AM-13, Plan H ruling 9): no `fenced` share lock precedes it in its unit, because a transaction that writes
    the lease takes FOR UPDATE from the start (SA:191). The new fence reaches the shared Lease before anything else
    runs, and a renewal meeting it meanwhile retries instead of declaring the lease lost (ruling 10).

    Raises:
        LeaseLost: the fence was stale, told apart from a run that is not EXECUTING by a fresh `fenced` check rather
            than by the refusal's text.
        VersionConflict: the fence holds, so the run itself is not EXECUTING.
    """
    lease, conn = ctx.lease, ctx.deps.conn
    lease.check()
    lease.begin_refence()
    try:
        async with conn.transaction():
            unknown = await persistence.mark_unknown(conn, lease.run_id, lease.fence)
    except persistence.VersionConflict:
        lease.end_refence(None)
        async with conn.transaction():
            await persistence.fenced(conn, lease)  # a stale fence raises LeaseLost here
        raise
    except BaseException:
        lease.end_refence(None)
        raise
    lease.end_refence(unknown.fence)


async def reconcile_outcome(state: RunGraphState, runtime: Runtime[Context]) -> dict[str, Any]:
    """The recover route's node, and the end of an execute job's graph run (Plan Q ruling 14). Recovery and
    reconciliation of an unknown outcome are T22's: the node rereads the run and ends the graph run."""
    ctx = runtime.context
    ctx.trace.append("reconcile_outcome")
    found = await facts(ctx, _run_id(state))
    if found["run_state"] in (RunState.OUTCOME_UNKNOWN.value, RunState.ESCALATED.value):
        # TODO(T22): recover jobs reconcile the original action id here (get_incident_receipt, abort_incident).
        log.info("run %s is %s; recovery arrives with T22", state["run_id"], found["run_state"])
    return found
````

Create `worker/src/ops_worker/graph/build.py`:

````python
"""The worker graph's wiring and its driver (AM-12 SA:207-218; Plan Q rulings 2, 5 and 6).

`build_graph` adds SA:207's ten nodes and generates `route_request`'s conditional edges from the route table
(`ops_core.routing.GRAPH_ROUTES`): the edge map is `{route: node}` for every route a row names, so an edge exists
exactly when a row can choose it. The nodes that do work return to `route_request`; the two waiting nodes interrupt;
`publish_state` ends the graph run when the table routes the run to `publish` (and otherwise returns to the router),
and `execute_approved_proposal` hands over to `reconcile_outcome`, which ends it (ruling 14).

`run_graph` drives one graph run under the job's lease with `durability="sync"` (SA:210) and
`stream_mode="checkpoints"`. Each checkpoint LangGraph announces is confirmed with `aget_tuple` before its id is
stored in `runs.checkpoint_id` under the fence (SA:211, T20 review note 2): the announcement of a run's first
checkpoint, or of a fork, can come before the saver has written it (langgraph 1.2.14 `pregel/_loop.py:1262-1275`
submits the write without waiting; `pregel/main.py:3526-3527` waits only after a superstep). The event arrives
before the next node starts (`pregel/_runner.py:388-389` yields first), so the store never races a node's own unit
on the loop connection. At an interrupt the last stored id is the checkpoint that holds the interrupt's write.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Hashable, Mapping
from typing import Any, Final

import psycopg
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from ops_core import persistence
from ops_core.routing import GRAPH_ROUTES, GraphRoute, route_graph
from ops_core.settings import Postgres
from psycopg.rows import DictRow, dict_row

from ops_worker.drafting import WORKFLOW_VERSION
from ops_worker.graph import nodes
from ops_worker.graph.state import Context, RunGraphState, key

Node = Callable[..., Awaitable[dict[str, Any]]]
NODES: Final[dict[str, Node]] = {
    "load_run": nodes.load_run,
    "route_request": nodes.route_request,
    "await_clarification": nodes.await_clarification,
    "retrieve_evidence": nodes.retrieve_evidence,
    "draft_with_langchain": nodes.draft_with_langchain,
    "validate_and_freeze": nodes.validate_and_freeze,
    "await_independent_decision": nodes.await_independent_decision,
    "execute_approved_proposal": nodes.execute_approved_proposal,
    "reconcile_outcome": nodes.reconcile_outcome,
    "publish_state": nodes.publish_state,
}
# Each route's node (docs/ARCHITECTURE.md §3): one node per route, three routes to publish_state.
ROUTE_NODES: Final[dict[GraphRoute, str]] = {
    GraphRoute.CLARIFY: "await_clarification",
    GraphRoute.RETRIEVE: "retrieve_evidence",
    GraphRoute.DRAFT: "draft_with_langchain",
    GraphRoute.ANSWER_ONLY: "publish_state",
    GraphRoute.ABSTAIN: "publish_state",
    GraphRoute.FREEZE: "validate_and_freeze",
    GraphRoute.AWAIT_DECISION: "await_independent_decision",
    GraphRoute.EXECUTE: "execute_approved_proposal",
    GraphRoute.RECOVER: "reconcile_outcome",
    GraphRoute.PUBLISH: "publish_state",
}
RETURNS_TO_ROUTER: Final = (
    "retrieve_evidence",
    "draft_with_langchain",
    "validate_and_freeze",
    "await_clarification",
    "await_independent_decision",
)
# Supersteps per graph run: the longest path (a resumed clarification through to the freeze and the wait) is 9; a
# node that kept routing back to itself fails the graph run instead of spinning (GraphRecursionError).
RECURSION_LIMIT: Final = 30
CONFIRM_TRIES: Final = 50  # aget_tuple polls before a checkpoint counts as not written (5 s in all)
CONFIRM_SECONDS: Final = 0.1
GraphInput = RunGraphState | Command[Any] | None


def edge_map() -> dict[Hashable, str]:
    """`route_request`'s conditional edges, generated from the table: {route: node} for every route a row names."""
    return {rule.route.value: ROUTE_NODES[rule.route] for rule in GRAPH_ROUTES}


def next_route(state: RunGraphState) -> str:
    """The path function of `route_request`'s conditional edges: the table's route for the state's key."""
    return route_graph(key(state)).value


def after_publish(state: RunGraphState) -> str:
    """`publish_state`'s way out, read from the same table: the graph run ends when the run is settled (the `publish`
    route); a run `publish_state` could not settle (its held answer was lost) goes back to the router."""
    return END if route_graph(key(state)) is GraphRoute.PUBLISH else "route_request"


def build_graph(
    saver: BaseCheckpointSaver[str], replace: Mapping[str, Node] | None = None
) -> CompiledStateGraph[RunGraphState, Context, RunGraphState, RunGraphState]:
    """The compiled graph on `saver`; `replace` swaps node functions by name (tests stub nodes to walk the table)."""
    builder: StateGraph[RunGraphState, Context, RunGraphState, RunGraphState] = StateGraph(
        RunGraphState, context_schema=Context
    )
    for name, function in {**NODES, **(replace or {})}.items():
        builder.add_node(name, function)
    builder.add_edge(START, "load_run")
    builder.add_edge("load_run", "route_request")
    builder.add_conditional_edges("route_request", next_route, edge_map())
    for name in RETURNS_TO_ROUTER:
        builder.add_edge(name, "route_request")
    builder.add_edge("execute_approved_proposal", "reconcile_outcome")
    builder.add_edge("reconcile_outcome", END)
    builder.add_conditional_edges("publish_state", after_publish, [END, "route_request"])
    return builder.compile(checkpointer=saver)


def thread_id(run_id: object, revision: int) -> str:
    """One LangGraph thread per run and revision (Plan Q ruling 13): a revision starts a thread of its own (T21)."""
    return f"{run_id}:{revision}"


def config(thread: str, checkpoint_id: str | None) -> RunnableConfig:
    """The graph run's config: the thread, the stored checkpoint when resuming, and `workflow_version` as checkpoint
    metadata (BS:342; LangGraph copies a string metadata value into every checkpoint's metadata)."""
    configurable: dict[str, Any] = {"thread_id": thread}
    if checkpoint_id is not None:
        configurable["checkpoint_id"] = checkpoint_id
    return {
        "configurable": configurable,
        "metadata": {"workflow_version": WORKFLOW_VERSION},
        "recursion_limit": RECURSION_LIMIT,
    }


class CheckpointNotStored(Exception):
    """A checkpoint LangGraph announced was not readable from the saver within CONFIRM_TRIES polls."""


async def confirm(saver: BaseCheckpointSaver[str], thread: str, checkpoint_id: str) -> None:
    """Wait until the saver returns the checkpoint (T20 review note 2: store only ids `aget_tuple` confirms)."""
    wanted: RunnableConfig = {
        "configurable": {"thread_id": thread, "checkpoint_ns": "", "checkpoint_id": checkpoint_id}
    }
    for _ in range(CONFIRM_TRIES):
        if await saver.aget_tuple(wanted) is not None:
            return
        await asyncio.sleep(CONFIRM_SECONDS)
    raise CheckpointNotStored(checkpoint_id)


async def known(saver: BaseCheckpointSaver[str], thread: str, checkpoint_id: str) -> bool:
    """True when the saver holds the stored checkpoint (a resume from an unknown id fails the run, note 2)."""
    wanted: RunnableConfig = {
        "configurable": {"thread_id": thread, "checkpoint_ns": "", "checkpoint_id": checkpoint_id}
    }
    return await saver.aget_tuple(wanted) is not None


async def interrupted(ctx: Context, thread: str, checkpoint_id: str) -> bool:
    """True when the stored checkpoint holds an interrupt (a waiting node to resume with `Command(resume=...)`)."""
    snapshot = await build_graph(ctx.deps.saver).aget_state(config(thread, checkpoint_id))
    return bool(snapshot.interrupts)


async def run_graph(ctx: Context, graph_input: GraphInput, *, checkpoint_id: str | None, revision: int = 1) -> None:
    """One graph run under the job's lease: input for a new graph run, `Command(resume=...)` for a human resume, or
    None with the stored checkpoint for crash recovery, which LangGraph treats as time travel and forks (SA:214)."""
    thread = thread_id(ctx.lease.run_id, revision)
    graph = build_graph(ctx.deps.saver)
    stored = checkpoint_id
    async for announced in graph.astream(
        graph_input,
        config(thread, checkpoint_id),
        context=ctx,
        stream_mode="checkpoints",
        durability="sync",
    ):
        current = str(announced["config"]["configurable"]["checkpoint_id"])
        if current == stored:
            continue  # a resume announces the checkpoint it starts from
        await confirm(ctx.deps.saver, thread, current)
        async with nodes.unit(ctx) as conn:
            await persistence.store_checkpoint_id(conn, ctx.lease.run_id, current)
        stored = current


async def open_saver(pg: Postgres) -> tuple[psycopg.AsyncConnection[DictRow], AsyncPostgresSaver]:
    """The worker's fourth connection, the saver's own (SA:559-562): autocommit and dict rows as the saver expects
    (`AsyncPostgresSaver.from_conn_string`, `checkpoint/postgres/aio.py:81-83`), no prepared statements, and
    `search_path=checkpoints,pg_temp`, because the saver names its tables without a schema."""
    conn = await psycopg.AsyncConnection.connect(
        pg.conninfo(),
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
        options="-c search_path=checkpoints,pg_temp",
    )
    return conn, AsyncPostgresSaver(conn)
````

Replace `worker/src/ops_worker/handlers.py` with:

````python
"""Job handlers (AM-20.4 job types; AM-10 states): each claimed job runs one LangGraph graph run for its run, under the
run lease its claim took (AM-12, T13), and its final unit closes the job and releases the lease (`persistence.
release_lease`), after the graph run ends or interrupts, so a run waiting for a person holds no lease (R022).

`investigate` starts the run's graph (QUEUED), or resumes it from `runs.checkpoint_id` when an earlier owner was
interrupted mid-run (SA:214); `resume_input` resumes a run waiting for a clarification with the reply's event id
(`Command(resume=...)`, SA:213); `execute` resumes the run waiting for its reviewer, or re-runs its execute node after
a re-queue. The graph's nodes do the work (`ops_worker.graph`); here are only the entry decisions and the failures no
node can record. A lost lease raises LeaseLost to the caller, which hands the job back (`abandon`).
"""

from __future__ import annotations

import logging
from typing import Any, Final
from uuid import UUID

import psycopg
from langgraph.types import Command
from ops_core import persistence
from ops_core.jobs import JOB_RULES, JobType
from ops_core.lease import Lease, LeaseLost
from ops_core.outcomes import EventType
from ops_core.states import RunState
from psycopg.pq import TransactionStatus

from ops_worker.deps import Deps
from ops_worker.graph import build, nodes
from ops_worker.graph.nodes import (  # re-exported: the templates the tests and the records name
    ABSTAINED,
    BUDGET_MARGIN_SECONDS,
    MODEL_INVALID,
    MODEL_UNAVAILABLE,
    Requeue,
    is_deferred,
)
from ops_worker.graph.state import Context, initial

__all__ = [
    "ABSTAINED",
    "BUDGET_MARGIN_SECONDS",
    "INTERRUPTED",
    "MODEL_INVALID",
    "MODEL_UNAVAILABLE",
    "Deps",
    "abandon",
    "execute",
    "handle",
    "investigate",
    "is_deferred",
    "resume_input",
]

log = logging.getLogger("ops_worker")
EXECUTE_RETRY_SECONDS = 30  # how long an execute job waits after mcp-write could not be reached
# A run found RETRIEVING or DRAFTING with no stored checkpoint (it stopped before its first checkpoint was stored, or
# before T20) cannot be resumed; it is failed, which frees its conversation slot.
INTERRUPTED: Final = "interrupted; the run was not resumed"
_MID_RUN: Final = (RunState.RETRIEVING, RunState.DRAFTING)


async def _drive(
    deps: Deps, job: dict[str, Any], lease: Lease, graph_input: build.GraphInput, checkpoint_id: str | None
) -> None:
    """One graph run. A failure no node recorded fails a run still RETRIEVING or DRAFTING, so its slot is freed (as
    Plan P's "drafting failed"); any other failure propagates as before T20 (the job stays claimed, its lease lapses
    and the sweeper hands it back)."""
    ctx = Context(deps, job, lease)
    try:
        await build.run_graph(ctx, graph_input, checkpoint_id=checkpoint_id)
    except (LeaseLost, Requeue):
        raise
    except Exception:
        async with nodes.unit(ctx) as conn:
            run = await persistence.run_row(conn, lease.run_id, lock=True)
            state = RunState(run["state"])
            if state not in _MID_RUN:
                raise
            log.exception("job %s: the graph run failed in %s", job["id"], state.value)
            await nodes.fail_from(conn, lease.run_id, state, nodes.WORKFLOW_FAILED)


async def _resumable(deps: Deps, job: dict[str, Any], lease: Lease, state: RunState, stored: str | None) -> bool:
    """True when the stored checkpoint exists; otherwise the run is failed with a template (T20 review note 2)."""
    if stored is not None and await build.known(deps.saver, build.thread_id(lease.run_id, 1), stored):
        return True
    log.warning("job %s: run %s has no stored checkpoint to resume (%s)", job["id"], lease.run_id, stored)
    async with nodes.unit(Context(deps, job, lease)) as conn:
        await nodes.fail_from(conn, lease.run_id, state, nodes.CHECKPOINT_MISSING)
    return False


async def _first_unit(deps: Deps, job: dict[str, Any], lease: Lease) -> dict[str, Any]:
    """The job's first fenced unit: the run row under its lock, and an unresumable interrupted run failed in it."""
    async with deps.conn.transaction():
        await persistence.set_tenant(deps.conn, job["tenant_id"])  # the worker's own reads are RLS-scoped
        await persistence.fenced(deps.conn, lease)  # run_lease before runs (SA:188, ruling 29)
        run = dict(await persistence.run_row(deps.conn, job["run_id"], lock=True))
        state = RunState(run["state"])
        if state in _MID_RUN and run.get("checkpoint_id") is None:
            log.warning("job %s: run was interrupted in %s before a checkpoint was stored; failed", job["id"], state)
            await persistence.transition_run(
                deps.conn, run_id=run["run_id"], src=state, dst=RunState.FAILED, detail={"message": INTERRUPTED}
            )
            run["state"] = RunState.FAILED.value
    return run


async def investigate(deps: Deps, job: dict[str, Any], lease: Lease) -> None:
    """Start the run's graph, or resume it from its stored checkpoint after an interruption (SA:214)."""
    await _carry_on(deps, job, lease, await _first_unit(deps, job, lease))


async def _carry_on(deps: Deps, job: dict[str, Any], lease: Lease, run: dict[str, Any]) -> None:
    """A run in QUEUED, RETRIEVING or DRAFTING: a new graph run, or crash recovery from the stored checkpoint."""
    state, stored = RunState(run["state"]), run.get("checkpoint_id")
    if state in _MID_RUN or (state is RunState.QUEUED and stored is not None):
        # An earlier owner stopped mid-run, or after a clarification moved the run back to QUEUED: resume from the
        # stored checkpoint, never from the thread's newest one (a stray head is ignored, R108).
        if await _resumable(deps, job, lease, state, stored):
            await _drive(deps, job, lease, None, stored)
    elif state is RunState.QUEUED:
        await _drive(deps, job, lease, initial(lease.run_id), None)
    else:
        log.info("job %s: run already %s", job["id"], state.value)


async def resume_input(deps: Deps, job: dict[str, Any], lease: Lease) -> None:
    """Resume a run waiting for a clarification with the reply's `clarification.received` event id (SA:213). The
    job's key names the question it answers (`run_id:clarification_event_id`, SA:501), so a replay is a duplicate
    the queue refuses, and a reply that is not the latest is refused by the resumed node (RESUME_REFUSED)."""
    run = await _first_unit(deps, job, lease)
    state, stored = RunState(run["state"]), run.get("checkpoint_id")
    if state is not RunState.AWAITING_INPUT:
        # An earlier owner of this job already took the reply (the run is QUEUED, RETRIEVING or DRAFTING): carry on
        # as an investigate job would; any other state has nothing left for this job.
        await _carry_on(deps, job, lease, run)
        return
    if not await _resumable(deps, job, lease, state, stored):
        return
    question = str(job["dedup_key"]).partition(":")[2]
    async with nodes.unit(Context(deps, job, lease), fence=False) as conn:
        received = await persistence.run_events(conn, lease.run_id, EventType.CLARIFICATION_RECEIVED)
    reply = next((event_id for event_id, p in reversed(received) if p.get("question_id") == question), None)
    if reply is None:
        async with nodes.unit(Context(deps, job, lease)) as conn:
            await nodes.fail_from(conn, lease.run_id, state, nodes.RESUME_REFUSED)
        return
    await _drive(deps, job, lease, Command(resume=str(reply)), stored)


async def _approval(deps: Deps, job: dict[str, Any], lease: Lease, run: dict[str, Any]) -> UUID | None:
    """The decision's committed event, the resume value (SA:213), checked against the database first: the run's
    latest decision event is an `approval.recorded` (no `run.rejected`) whose `proposal_id` is the run's active
    proposal (record_decision's payload, 0004). None when it is not, with the three ids logged (round 1, M1)."""
    async with nodes.unit(Context(deps, job, lease), fence=False) as conn:
        approved = await persistence.run_events(conn, lease.run_id, EventType.APPROVAL_RECORDED)
        rejected = await persistence.run_events(conn, lease.run_id, EventType.RUN_REJECTED)
    event_id, payload = approved[-1] if approved else (None, {})
    active = str(run["active_proposal_id"])
    if event_id is None or rejected or payload.get("proposal_id") != active:
        log.error(
            "execute job %s: run %s has no approval of its active proposal to resume with (event %s for proposal %s,"
            " active proposal %s); the job ends without a graph run",
            job["id"],
            lease.run_id,
            event_id,
            payload.get("proposal_id"),
            active,
        )
        return None
    return event_id


async def execute(deps: Deps, job: dict[str, Any], lease: Lease) -> bool:
    """Run the approved run's graph to `create_incident` (ruling 14); True when the job is finished by `handle`, False
    when it was re-queued (its final unit already ran and released the lease).

    The stored checkpoint is the reviewer wait: resumed with the decision's event id, checked first (`_approval`),
    the waiting node rereads the decision. After a re-queue it is the checkpoint before the execute node, which runs
    again (a fork, SA:214). A run with no stored checkpoint (approved before T20) starts a graph run, whose router reads
    APPROVED."""
    run = await _first_unit(deps, job, lease)
    # APPROVED or EXECUTING (JOB_RULES[EXECUTE].run_states): after a transport failure past the grant, the re-queued
    # job resends under the same action id (grant_execution's replay rule; Plan E ruling 6).
    if RunState(run["state"]) not in JOB_RULES[JobType.EXECUTE].run_states:
        log.info("execute job %s: run is %s, nothing to dispatch", job["id"], run["state"])
        return True
    stored = run.get("checkpoint_id")
    thread = build.thread_id(lease.run_id, 1)
    graph_input: build.GraphInput = initial(lease.run_id)
    checkpoint = None
    if stored is not None and await build.known(deps.saver, thread, stored):
        checkpoint = stored
        graph_input = None
        if await build.interrupted(Context(deps, job, lease), thread, stored):
            approval = await _approval(deps, job, lease, run)
            if approval is None:
                # No transition (the worker may not move an APPROVED run, SA:451) and no retry for ever: the job is
                # closed by `handle`'s final unit. TODO(T22): recovery of a run approved without a matching decision.
                return True
            graph_input = Command(resume=str(approval))
    try:
        await _drive(deps, job, lease, graph_input, checkpoint)
    except Requeue:
        await persistence.release_lease(deps.conn, lease, job=job, requeue_seconds=EXECUTE_RETRY_SECONDS)
        return False
    return True


async def handle(deps: Deps, job: dict[str, Any], lease: Lease) -> None:
    """Dispatch a claimed job by type under its lease; the final unit closes the job and releases the lease."""
    kind = JobType(job["type"])
    if kind is JobType.INVESTIGATE:
        await investigate(deps, job, lease)
    elif kind is JobType.RESUME_INPUT:
        await resume_input(deps, job, lease)
    elif kind is JobType.EXECUTE:
        if not await execute(deps, job, lease):
            return  # re-queued: its final unit already released the lease
    else:
        # TODO(T22): recover jobs (the graph's recover route reaches reconcile_outcome, which only logs in v1).
        log.info("job %s of type %s is not handled before T22", job["id"], kind.value)
    await persistence.release_lease(deps.conn, lease, job=job)


async def abandon(deps: Deps, job: dict[str, Any], lease: Lease) -> None:
    """The lease is lost (Plan H ruling 19): revoke the handles minted under this fence and hand the job back, in one
    unit, with no transition here (the next owner resumes the run from its stored checkpoint, or fails it as
    INTERRUPTED when none was stored). `revoke_handles` never refuses a stale fence (ruling 8), so this works whoever
    holds the lease now.

    Raises:
        psycopg.OperationalError: the loop connection was not idle. Only effects are ever cancelled, so this should
            not happen; if it does, a hand-back on that connection would nest in the open transaction and never
            commit, so the connection is closed instead, the poll loop ends and the supervisor restarts the worker
            (review round 1, B1).
    """
    if deps.conn.info.transaction_status is not TransactionStatus.IDLE:
        await deps.conn.close()
        raise psycopg.OperationalError("the loop connection was not idle when its lease was lost; it was closed")
    async with deps.conn.transaction():
        await persistence.set_tenant(deps.conn, job["tenant_id"])  # jobs is under RLS
        await persistence.revoke_handles(deps.conn, lease.run_id, lease.fence)
        await persistence.unclaim_job(deps.conn, job["id"], worker_name=deps.worker_name)
````

Edit 65 (`worker/src/ops_worker/main.py`), replace:

````python
"""The worker process: a polling loop beside a health server and the lease heartbeat thread, three connections (the
loop's, the probe's and the heartbeat's synchronous one), SelectorEventLoop on Windows (psycopg async refuses the
Proactor loop; measured in the Plan D spike; the heartbeat's synchronous connection is not bound by that).

Each poll claims the next job together with its run's lease (`persistence.claim_next`, Plan H ruling 3) and runs the
handler under that lease while the heartbeat renews it; a lost lease cancels the job's effects in flight and hands the
````

with:

````python
"""The worker process: a polling loop beside a health server and the lease heartbeat thread, four connections (the
loop's, the probe's, the heartbeat's synchronous one and the checkpoint saver's, T20), SelectorEventLoop on Windows
(psycopg async refuses the Proactor loop; measured in the Plan D spike; the heartbeat's synchronous connection is not
bound by that).

Each poll claims the next job together with its run's lease (`persistence.claim_next`, Plan H ruling 3) and runs the
handler under that lease while the heartbeat renews it; a lost lease cancels the job's effects in flight and hands the
````

Edit 66 (`worker/src/ops_worker/main.py`), replace:

````python

from ops_worker import handlers
from ops_worker.drafting import ModelStartError, start_route
from ops_worker.heartbeat import Heartbeat, Liveness, connector, keep_stamping
from ops_worker.mcp import HttpMcpCaller

````

with:

````python

from ops_worker import handlers
from ops_worker.drafting import ModelStartError, start_route
from ops_worker.graph.build import open_saver
from ops_worker.heartbeat import Heartbeat, Liveness, connector, keep_stamping
from ops_worker.mcp import HttpMcpCaller

````

Edit 67 (`worker/src/ops_worker/main.py`), replace:

````python
    await persistence.assert_clock_profile(probe, settings.profile())
    await persistence.assert_relation(probe, "app.model_permit")  # revision 0007: the permit and the fenced functions
    await persistence.assert_relation(probe, "app.run_manifests")  # revision 0014: every run's manifest (T19)
    liveness = Liveness()
    heartbeat = Heartbeat(connect=connector(settings.app_postgres(Role.WORKER)), settings=leases, liveness=liveness)
    deps = handlers.Deps(
````

with:

````python
    await persistence.assert_clock_profile(probe, settings.profile())
    await persistence.assert_relation(probe, "app.model_permit")  # revision 0007: the permit and the fenced functions
    await persistence.assert_relation(probe, "app.run_manifests")  # revision 0014: every run's manifest (T19)
    await persistence.assert_relation(probe, "checkpoints.checkpoints")  # revision 0015: the graph's saver (T20)
    # The saver's own connection (SA:559-562): its writes never share a transaction with an application unit.
    saver_conn, saver = await open_saver(settings.app_postgres(Role.WORKER))
    liveness = Liveness()
    heartbeat = Heartbeat(connect=connector(settings.app_postgres(Role.WORKER)), settings=leases, liveness=liveness)
    deps = handlers.Deps(
````

Edit 68 (`worker/src/ops_worker/main.py`), replace:

````python
        workload_azp=tokens.client_id,
        leases=leases,
        heartbeat=heartbeat,
    )
    stop = asyncio.Event()
    stamps_stop = asyncio.Event()  # its own event: the stamps must outlive the job a shutdown lets finish
````

with:

````python
        workload_azp=tokens.client_id,
        leases=leases,
        heartbeat=heartbeat,
        saver=saver,
    )
    stop = asyncio.Event()
    stamps_stop = asyncio.Event()  # its own event: the stamps must outlive the job a shutdown lets finish
````

Edit 69 (`worker/src/ops_worker/main.py`), replace:

````python
        await asyncio.to_thread(heartbeat.join, 5.0)  # off the loop: the thread ends its tick and closes its connection
        await conn.close()
        await probe.close()
    # A supervisor restarts a worker that lost its database or its health server; exit 0 would hide either.
    for task in (polling, serving):
        if task.done() and not task.cancelled() and task.exception() is not None:
````

with:

````python
        await asyncio.to_thread(heartbeat.join, 5.0)  # off the loop: the thread ends its tick and closes its connection
        await conn.close()
        await probe.close()
        await saver_conn.close()
    # A supervisor restarts a worker that lost its database or its health server; exit 0 would hide either.
    for task in (polling, serving):
        if task.done() and not task.cancelled() and task.exception() is not None:
````

Edit 70 (`sweeper/src/ops_sweeper/wakeups.py`), replace:

````python
execute job with the approving decision. The worker consumes a job only in its final unit, after the handler
returned; a handler that returned without moving the run (or a crash between consumption and progress) leaves the run
waiting in the job's state with the job done. The sweep finds such runs, in the states a handler serves today
(QUEUED for `investigate`, APPROVED for `execute`; AWAITING_INPUT is T20's, OUTCOME_UNKNOWN and ESCALATED are T22's),
when the newest job of the type has been done for longer than the grace, and reopens that job: its dedup key is the
wake-up's identity, so the same row is re-armed (`done_at`, `claimed_by`, `claimed_at` cleared under `sweeper_all`),
never a new one inserted (erratum 62). A run whose cancellation was requested is never re-armed. A job claimed
````

with:

````python
execute job with the approving decision. The worker consumes a job only in its final unit, after the handler
returned; a handler that returned without moving the run (or a crash between consumption and progress) leaves the run
waiting in the job's state with the job done. The sweep finds such runs, in the states a handler serves today
(QUEUED for `investigate`, APPROVED for `execute`; AWAITING_INPUT's wake-up is the API's `resume_input` job, erratum
62, and a run that job moved back to QUEUED is re-armed by the investigate pair, which resumes it from its stored
checkpoint (T20); OUTCOME_UNKNOWN and ESCALATED are T22's),
when the newest job of the type has been done for longer than the grace, and reopens that job: its dedup key is the
wake-up's identity, so the same row is re-armed (`done_at`, `claimed_by`, `claimed_at` cleared under `sweeper_all`),
never a new one inserted (erratum 62). A run whose cancellation was requested is never re-armed. A job claimed
````

Run `PYTHONUTF8=1 uv run python -m pytest tests/plan_q tests/plan_h tests/plan_m tests/plan_p tests/plan_j
tests/plan_f -q -p no:cacheprovider < /dev/null` → `600 passed, 2 skipped` (the two skips are Plan P's Ollama route
tests).

- [ ] **Step 3: Gates and commit**

`git add` the seven new files; dev `CHECK: GREEN`, `1721 passed, 222 skipped`; `verify_handoff.py` exit 0.
`git grep -n "TODO(T20)" -- '*.py' ':!*holdout*' ':!*seal*' ':!*.sha256'` prints nothing.

```bash
git add worker/src/ops_worker sweeper/src/ops_sweeper/wakeups.py tests/plan_q tests/plan_h/test_worker_units.py \
  tests/plan_p/test_investigate_drafting.py tests/plan_p/test_worker_startup.py tests/plan_j/test_worker_azp.py \
  tests/plan_f/test_grant_deferred.py tests/plan_m/test_worker_r029.py
git commit -m "feat: the LangGraph workflow - sync durability, stored checkpoint ids, ID-only interrupts, ANSWERED (T20)"
```

---
### Task 5: The live tests and the first live gate

**Files:**
- Create: `tests/e2e/test_graph_live.py`; `reports/graph/t20-graph-live.md` (written by the live run, committed)
- Modify: `tests/e2e/test_worker_live.py`, `tests/e2e/test_heartbeat_live.py`,
  `tests/e2e/test_r105_walking_skeleton.py`, `tests/e2e/test_admission_live.py` (a comment)

**Requirements:** rulings 6, 9, 12, 15; R022, R038, R042, R091, R108, R114, R122 live; DoD 1-3 on the Postgres saver.

- [ ] **Step 1: The live tests**

Create `tests/e2e/test_graph_live.py`:

````python
"""The worker graph on LangGraph's Postgres saver against the per-session test database (OPS_LIVE=1; T20; R022, R038,
R042, R091, R108, R114, R122), on the fake route with the scripted MCP caller of `test_worker_live`.

Catches: a checkpoint schema the api or the sweeper can read, or the worker cannot (R122); the revision's version
rows missing (a `setup()` would re-run its DDL); a read that completes after the draft is recorded (R038); a stored
checkpoint id that is not the thread's checkpoint holding the interrupt (R108); a lease, an open worker transaction or
a model permit held while the run waits (R022); proposal, answer, question or alert text inside a checkpoint row, blob
or pending write (R091); a clarification that does not survive a restart, a new graph instance on a new saver
connection resuming from the stored id with the reply's event (R042; a killed process is the limit, Plan Q); and an
answer_only run that freezes a proposal instead of ending ANSWERED with its cited answer (R114); and a graph whose
step N+1 starts before step N's checkpoint is in the Postgres saver (R108's synchronous persistence, ruling 6).

Writes `reports/graph/t20-graph-live.md` (the node order and end states) when every test of the module passed.
"""

import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
import pytest_asyncio
from ops_api.store import DbUnit
from ops_core import persistence, settings
from ops_core.outcomes import EventType
from ops_core.settings import Role
from ops_worker import handlers
from ops_worker.drafting import FakeDraftGenerator
from ops_worker.graph import build
from ops_worker.graph.state import Context, initial

from tests.e2e.conftest import purge_run
from tests.e2e.test_migrations_and_persistence import ALEX, new_run
from tests.e2e.test_worker_live import ALPHA, ScriptedMcp, approve, event_types, own_job, proposal_of
from tests.plan_q.test_graph_flow import QUESTION, Scripted

pytestmark = pytest.mark.asyncio
RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
EVIDENCE = Path("reports/graph/t20-graph-live.md")
EXPECTED_LINES = 5
ALERT_TEXT = "Bearing temperature above the warning threshold."  # the scripted alert's message


@pytest.fixture(scope="module")
def lines() -> Iterator[list[str]]:
    out = [f"# T20 graph on the Postgres saver — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}", ""]
    yield out
    if len(out) != 2 + EXPECTED_LINES:  # a failed or partial run leaves the committed file as it was
        return
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


@pytest.fixture
def traces(monkeypatch: pytest.MonkeyPatch) -> list[Context]:
    """Every graph run's context, so a test can read its node log."""
    seen: list[Context] = []
    real = handlers.Context

    def recording(*args: Any, **kwargs: Any) -> Context:
        ctx = real(*args, **kwargs)
        seen.append(ctx)
        return ctx

    monkeypatch.setattr(handlers, "Context", recording)
    return seen


Worker = Callable[[Any], Awaitable[handlers.Deps]]


@pytest_asyncio.fixture
async def worker(role_conn: RoleConn) -> AsyncIterator[Worker]:
    """A factory of worker Deps, each on its own `worker` connection and its own saver connection (a fresh process
    as far as the graph can tell); every saver connection is closed at the end."""
    opened: list[psycopg.AsyncConnection[Any]] = []

    async def build_deps(generator: Any) -> handlers.Deps:
        conn, saver = await build.open_saver(settings.app_postgres(Role.WORKER))
        opened.append(conn)
        return handlers.Deps(
            conn=await role_conn(Role.WORKER),
            mcp=ScriptedMcp(await role_conn(Role.MCP_READ), await role_conn(Role.MCP_EXEC)),
            generator=generator,
            urls=settings.urls(),
            worker_name="t",
            workload_azp="ops-worker",
            saver=saver,
        )

    yield build_deps
    for conn in opened:
        await conn.close()


async def stored(app: persistence.Conn, run: UUID) -> str:
    row = await persistence.run_row(app, run)
    assert row["checkpoint_id"] is not None
    return str(row["checkpoint_id"])


async def checkpoint_bytes(app: persistence.Conn, run: UUID) -> bytes:
    """Every checkpoint row, blob and pending write of the run's thread, as one byte string (R091's grep)."""
    thread = build.thread_id(run, 1)
    out = b""
    for query in (
        "SELECT checkpoint::text || metadata::text AS v FROM checkpoints.checkpoints WHERE thread_id = %s",
        "SELECT blob AS v FROM checkpoints.checkpoint_blobs WHERE thread_id = %s AND blob IS NOT NULL",
        "SELECT blob AS v FROM checkpoints.checkpoint_writes WHERE thread_id = %s",
    ):
        cur = await app.execute(query, (thread,))
        for row in await cur.fetchall():
            value = row["v"]
            out += value.encode() if isinstance(value, str) else bytes(value)
    return out


async def forget(app: persistence.Conn, run: UUID) -> None:
    for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
        await app.execute(f"DELETE FROM checkpoints.{table} WHERE thread_id = %s", (build.thread_id(run, 1),))
    await purge_run(app, run)


async def test_r108_each_step_finds_the_previous_checkpoint_stored(lines: list[str]) -> None:
    """Ruling 6: with durability="sync" a stub node running step N+1 reads the thread's newest checkpoint from the
    Postgres saver and finds step N's state in it (the value `load_run`'s stub wrote), before anything else runs."""
    conn, saver = await build.open_saver(settings.app_postgres(Role.WORKER))
    thread = f"r108:{uuid4()}"
    seen: dict[str, Any] = {}

    class Reached(Exception):
        """The stub at step N+1 stops the graph run once it has looked."""

    async def load_run(_state: Any, runtime: Any) -> dict[str, Any]:
        return {"intent": "answer_only", "run_state": "DRAFTING"}  # step N's writes

    async def route_request(_state: Any, runtime: Any) -> dict[str, Any]:
        stored = await saver.aget_tuple({"configurable": {"thread_id": thread, "checkpoint_ns": ""}})
        seen["values"] = None if stored is None else dict(stored.checkpoint["channel_values"])
        seen["step"] = None if stored is None else stored.metadata.get("step")
        raise Reached

    try:
        graph = build.build_graph(saver, {"load_run": load_run, "route_request": route_request})
        with pytest.raises(Reached):
            await graph.ainvoke(initial(uuid4()), {"configurable": {"thread_id": thread}}, durability="sync")
        assert seen["values"] is not None and seen["values"]["intent"] == "answer_only"  # step N, already stored
        assert seen["values"]["run_state"] == "DRAFTING" and seen["step"] == 0
        lines.append(
            "- R108: a step-N+1 node found step N's checkpoint already in the Postgres saver (durability=sync)"
        )
    finally:
        await saver.adelete_thread(thread)
        await conn.close()


async def test_r122_the_checkpoint_schema_is_the_workers_alone(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    for role in (Role.API, Role.SWEEPER, Role.MCP_READ):
        conn = await role_conn(role)
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="permission denied for schema checkpoints"):
            await conn.execute("SELECT 1 FROM checkpoints.checkpoints LIMIT 1")
    worker = await role_conn(Role.WORKER)
    await worker.execute("SELECT 1 FROM checkpoints.checkpoint_writes LIMIT 1")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):  # the library's bookkeeping is the migration's
        await worker.execute("SELECT 1 FROM checkpoints.checkpoint_migrations LIMIT 1")
    cur = await app_conn.execute("SELECT v FROM checkpoints.checkpoint_migrations ORDER BY v")
    assert [r["v"] for r in await cur.fetchall()] == list(range(10))  # the migrator ran setup()'s statements
    cur = await app_conn.execute("SELECT DISTINCT tableowner FROM pg_tables WHERE schemaname = 'checkpoints'")
    assert [r["tableowner"] for r in await cur.fetchall()] == ["migrator"]
    lines.append("- R122: api, sweeper and mcp_read refused at schema `checkpoints`; worker DML; versions 0-9 recorded")


async def test_a_run_waits_for_its_reviewer_at_the_stored_checkpoint(
    app_conn: persistence.Conn, role_conn: RoleConn, worker: Worker, traces: list[Context], lines: list[str]
) -> None:
    deps = await worker(FakeDraftGenerator())
    run = None
    try:
        _, _, run = await new_run(app_conn, ALPHA, api=await role_conn(Role.API))
        await handlers.handle(deps, *await own_job(app_conn, deps.conn, run, "investigate"))
        assert (await persistence.run_row(app_conn, run))["state"] == "AWAITING_APPROVAL"
        cur = await app_conn.execute(
            "SELECT type, sequence FROM app.events WHERE run_id = %s ORDER BY sequence", (run,)
        )
        events = [(r["type"], r["sequence"]) for r in await cur.fetchall()]
        reads = [seq for kind, seq in events if kind == "tool.completed"]
        drafted = next(seq for kind, seq in events if kind == "explanation.ready")  # the drafts row's own unit
        assert len(reads) == 3 and max(reads) < drafted  # R038: every read completed before the draft was recorded
        head = await stored(app_conn, run)
        cur = await app_conn.execute(
            "SELECT checkpoint_id FROM checkpoints.checkpoints WHERE thread_id = %s"
            " ORDER BY checkpoint_id DESC LIMIT 1",
            (build.thread_id(run, 1),),
        )
        assert (await cur.fetchone())["checkpoint_id"] == head  # R108: the stored id is the confirmed head
        cur = await app_conn.execute(
            "SELECT 1 FROM checkpoints.checkpoint_writes WHERE thread_id = %s AND checkpoint_id = %s"
            " AND channel = '__interrupt__'",
            (build.thread_id(run, 1), head),
        )
        assert await cur.fetchone() is not None  # SA:211: it holds the interrupt's pending write
        cur = await app_conn.execute(
            "SELECT lease_until = '-infinity' AS released FROM app.run_lease WHERE run_id = %s", (run,)
        )
        assert (await cur.fetchone())["released"]  # R022: no lease while the run waits
        cur = await app_conn.execute(
            "SELECT count(*) AS n FROM pg_stat_activity WHERE usename = 'worker' AND state LIKE 'idle in transaction%%'"
        )
        assert (await cur.fetchone())["n"] == 0  # R022: no worker transaction left open
        cur = await app_conn.execute("SELECT count(*) AS n FROM app.model_permit WHERE holder IS NOT NULL")
        assert (await cur.fetchone())["n"] == 0  # R022: the permit is free
        proposal = await proposal_of(app_conn, run)
        blobs = await checkpoint_bytes(app_conn, run)
        for text in (proposal["payload"]["title"], proposal["payload"]["summary"][:60], ALERT_TEXT):
            assert text.encode() not in blobs, text  # R091
        await approve(await role_conn(Role.API), proposal)
        restarted = await worker(FakeDraftGenerator())  # a new graph instance on a new saver connection
        await handlers.handle(restarted, *await own_job(app_conn, restarted.conn, run, "execute"))
        assert traces[-1].trace[0] == "await_independent_decision"  # resumed with the decision's event (SA:213)
        called: Any = restarted.mcp
        assert [c[1] for c in called.calls] == ["create_incident"]
        lines.append(f"- proposal path: {' → '.join(traces[0].trace)}; ends AWAITING_APPROVAL, lease released")
    finally:
        if run is not None:
            await forget(app_conn, run)


async def test_r042_a_clarification_survives_a_restart(
    app_conn: persistence.Conn, role_conn: RoleConn, worker: Worker, traces: list[Context], lines: list[str]
) -> None:
    api = await role_conn(Role.API)
    deps = await worker(Scripted(QUESTION))
    run = None
    try:
        _, _, run = await new_run(app_conn, ALPHA, api=api)
        await handlers.handle(deps, *await own_job(app_conn, deps.conn, run, "investigate"))
        row = await persistence.run_row(app_conn, run)
        assert row["state"] == "AWAITING_INPUT"
        cur = await app_conn.execute(
            "SELECT event_id, payload FROM app.events WHERE run_id = %s AND type = %s",
            (run, EventType.CLARIFICATION_REQUESTED.value),
        )
        (asked,) = await cur.fetchall()
        assert asked["payload"] == {"message": "Which hours?"}  # the question rides in its event (erratum 124)
        waiting = await stored(app_conn, run)
        assert QUESTION.question is not None and QUESTION.question.encode() not in await checkpoint_bytes(app_conn, run)
        first: Any = deps.saver
        await first.conn.close()  # the first graph process is gone: its saver connection with it
        async with api.transaction():  # the API's reply path (store.record_reply), as the route runs it
            await persistence.set_tenant(api, ALPHA)
            await DbUnit(api, ALPHA).record_reply(
                run_id=run,
                requester=UUID(ALEX),
                question_id=asked["event_id"],
                expected_version=row["state_version"],
                text="Clarification: asset A17, hours 24",
                context={"asset_id": "A17", "hours": 24},
            )
        restarted = await worker(FakeDraftGenerator())
        await handlers.handle(restarted, *await own_job(app_conn, restarted.conn, run, "resume_input"))
        assert (await persistence.run_row(app_conn, run))["state"] == "AWAITING_APPROVAL"
        assert traces[-1].trace[:3] == ["await_clarification", "route_request", "retrieve_evidence"]
        cur = await app_conn.execute(
            "SELECT parent_checkpoint_id FROM checkpoints.checkpoints WHERE thread_id = %s AND checkpoint_id > %s"
            " ORDER BY checkpoint_id LIMIT 1",
            (build.thread_id(run, 1), waiting),
        )
        assert (await cur.fetchone())["parent_checkpoint_id"] == waiting  # resumed from the stored id, no fork
        cur = await app_conn.execute(
            "SELECT to_state FROM app.run_state_history WHERE run_id = %s ORDER BY seq", (run,)
        )
        history = [r["to_state"] for r in await cur.fetchall()]
        assert history[3:6] == ["AWAITING_INPUT", "QUEUED", "RETRIEVING"]
        lines.append(f"- clarification across a restart: {' → '.join(history)}")
    finally:
        if run is not None:
            await forget(app_conn, run)


async def test_r114_an_answer_only_run_ends_answered(
    app_conn: persistence.Conn, role_conn: RoleConn, worker: Worker, traces: list[Context], lines: list[str]
) -> None:
    deps = await worker(FakeDraftGenerator())
    run = None
    try:
        _, _, run = await new_run(app_conn, ALPHA, api=await role_conn(Role.API))
        # Staged as the admission router's readonly_answer route would create it (SA:371); intent is create_run's.
        await app_conn.execute("UPDATE app.runs SET intent = 'answer_only' WHERE run_id = %s", (run,))
        await handlers.handle(deps, *await own_job(app_conn, deps.conn, run, "investigate"))
        row = await persistence.run_row(app_conn, run)
        assert row["state"] == "ANSWERED" and row["active_proposal_id"] is None
        types = await event_types(app_conn, run)
        assert types[-2:] == [("explanation.ready", "model_summary"), ("run.answered", "application")]
        cur = await app_conn.execute(
            "SELECT payload FROM app.events WHERE run_id = %s AND type = 'explanation.ready'", (run,)
        )
        answer = (await cur.fetchone())["payload"]
        assert answer["evidence_refs"] == ["ALPHA-INCIDENT:v2:review"] and answer["message"].startswith("For A17")
        cur = await app_conn.execute("SELECT count(*) AS n FROM app.proposals WHERE run_id = %s", (run,))
        assert (await cur.fetchone())["n"] == 0  # R114: no proposal, so no grant can follow
        assert answer["message"][:40].encode() not in await checkpoint_bytes(app_conn, run)
        lines.append(f"- answer_only: {' → '.join(traces[0].trace)}; ends ANSWERED, cited, no proposal")
    finally:
        if run is not None:
            await forget(app_conn, run)
````

Edit 71 (`tests/e2e/test_worker_live.py`), replace:

````python
"""The two handlers as role `worker` against the real database with a scripted MCP caller (OPS_LIVE=1): the state
path through the definer functions, the frozen proposal's bytes and hash, the event order, the execute job's handle,
the re-queue of an unreachable write server, and the worker's own recording of UNKNOWN. The real MCP transport is
proved in Task 5's and Task 9's tests.

Rows are written by role connections, so nothing here can roll back: every test purges its run in `finally`. The
seeded tenant ALPHA is used because `record_decision` needs SAM's reviewer membership."""
````

with:

````python
"""The two handlers as role `worker` against the real database with a scripted MCP caller (OPS_LIVE=1): the state
path through the definer functions, the frozen proposal's bytes and hash, the event order, the execute job's handle,
the re-queue of an unreachable write server, and the worker's own recording of UNKNOWN. The real MCP transport is
proved in Task 5's and Task 9's tests. Since T20 each job runs the graph, whose retrieval reads the asset status and
the alerts before the search, so the scripted caller answers all three read tools.

Rows are written by role connections, so nothing here can roll back: every test purges its run in `finally`. The
seeded tenant ALPHA is used because `record_decision` needs SAM's reviewer membership."""
````

Edit 72 (`tests/e2e/test_worker_live.py`), replace:

````python

from tests.e2e.conftest import lease_for, purge_run
from tests.e2e.test_migrations_and_persistence import new_run

pytestmark = pytest.mark.asyncio

````

with:

````python

from tests.e2e.conftest import lease_for, purge_run
from tests.e2e.test_migrations_and_persistence import new_run
from tests.plan_h.test_worker_units import ALERTS, STATUS

pytestmark = pytest.mark.asyncio

````

Edit 73 (`tests/e2e/test_worker_live.py`), replace:

````python
    async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Resolve the handle for the tool's server, then return the scripted envelope."""
        self.calls.append((url, tool, arguments))
        server = Server.READ if tool == "search_procedures" else Server.WRITE
        await persistence.resolve_invocation(
            self.read if server is Server.READ else self.write, handle=handle, azp="ops-worker", tool=Tool(tool)
        )
        if tool == "search_procedures":
            return SEARCH
        return {
            "status": "ok",
            "data": {
````

with:

````python
    async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Resolve the handle for the tool's server, then return the scripted envelope."""
        self.calls.append((url, tool, arguments))
        reads = {"get_asset_status": STATUS, "get_recent_alerts": ALERTS, "search_procedures": SEARCH}
        server = Server.READ if tool in reads else Server.WRITE
        await persistence.resolve_invocation(
            self.read if server is Server.READ else self.write, handle=handle, azp="ops-worker", tool=Tool(tool)
        )
        if tool in reads:
            return reads[tool]
        return {
            "status": "ok",
            "data": {
````

Edit 74 (`tests/e2e/test_worker_live.py`), replace:

````python
        assert proposal["payload"]["evidence_refs"] == ["ALPHA-INCIDENT:v2:review"]
        assert await event_types(app_conn, run) == [
            ("run.accepted", "application"),
            ("tool.started", "application"),
            ("tool.completed", "application"),
            ("explanation.ready", "model_summary"),
            ("proposal.ready", "application"),
        ]
````

with:

````python
        assert proposal["payload"]["evidence_refs"] == ["ALPHA-INCIDENT:v2:review"]
        assert await event_types(app_conn, run) == [
            ("run.accepted", "application"),
            *[("tool.started", "application"), ("tool.completed", "application")] * 3,  # status, alerts, search
            ("explanation.ready", "model_summary"),
            ("proposal.ready", "application"),
        ]
````

Edit 75 (`tests/e2e/test_worker_live.py`), replace:

````python
        assert (await event_types(app_conn, run))[-1] == ("approval.recorded", "application")
        job, lease = await own_job(app_conn, deps.conn, run, "execute")
        await handlers.handle(deps, job, lease)
        assert [c[1] for c in mcp.calls] == ["search_procedures", "create_incident"]
        assert mcp.calls[1][2] == {"proposal_id": str(proposal["proposal_id"])}
        cur = await app_conn.execute("SELECT done_at IS NOT NULL AS done FROM app.jobs WHERE id = %s", (job["id"],))
        assert (await cur.fetchone())["done"]
    finally:
````

with:

````python
        assert (await event_types(app_conn, run))[-1] == ("approval.recorded", "application")
        job, lease = await own_job(app_conn, deps.conn, run, "execute")
        await handlers.handle(deps, job, lease)
        assert [c[1] for c in mcp.calls] == [
            "get_asset_status",
            "get_recent_alerts",
            "search_procedures",
            "create_incident",
        ]
        assert mcp.calls[3][2] == {"proposal_id": str(proposal["proposal_id"])}
        cur = await app_conn.execute("SELECT done_at IS NOT NULL AS done FROM app.jobs WHERE id = %s", (job["id"],))
        assert (await cur.fetchone())["done"]
    finally:
````

Edit 76 (`tests/e2e/test_worker_live.py`), replace:

````python
        cur = await app_conn.execute("SELECT type FROM app.events WHERE run_id = %s ORDER BY sequence", (run,))
        assert [r["type"] for r in await cur.fetchall()] == [
            "run.accepted",
            "tool.started",
            "tool.completed",
            "run.failed",
        ]
        cur = await app_conn.execute(
````

with:

````python
        cur = await app_conn.execute("SELECT type FROM app.events WHERE run_id = %s ORDER BY sequence", (run,))
        assert [r["type"] for r in await cur.fetchall()] == [
            "run.accepted",
            *["tool.started", "tool.completed"] * 3,
            "run.failed",
        ]
        cur = await app_conn.execute(
````

Edit 77 (`tests/e2e/test_heartbeat_live.py`), replace:

````python
        row = await cur.fetchone()
        assert row is not None and (row["claimed_by"], row["done_at"]) == (None, None)  # handed back (ruling 19)
        assert (await persistence.run_row(app_conn, run))["state"] == "RETRIEVING"  # no transition
        # The handed-back job runs again (review round 3, I1): its next owner finds the run interrupted and fails it.
        await expire_lease(app_conn, run)  # the thief is done with the run
        await main.run_job(deps, await claim(deps, tenant))
        assert (await persistence.run_row(app_conn, run))["state"] == "FAILED"
        lines.append(
            f"R088 forced renewal failure: call cancelled {noticed:.1f} s after the takeover, handle revoked;"
            " the re-run failed the interrupted run"
        )
    finally:
        await purge_run(app_conn, run)
````

with:

````python
        row = await cur.fetchone()
        assert row is not None and (row["claimed_by"], row["done_at"]) == (None, None)  # handed back (ruling 19)
        assert (await persistence.run_row(app_conn, run))["state"] == "RETRIEVING"  # no transition
        # The handed-back job runs again: since T20 its next owner resumes the run from its stored checkpoint (the
        # first owner stored one before it started reading), here with a read server that answers.
        await expire_lease(app_conn, run)  # the thief is done with the run
        deps.mcp = ScriptedMcp(mcp.read, mcp.write)
        await main.run_job(deps, await claim(deps, tenant))
        assert (await persistence.run_row(app_conn, run))["state"] == "AWAITING_APPROVAL"
        lines.append(
            f"R088 forced renewal failure: call cancelled {noticed:.1f} s after the takeover, handle revoked;"
            " the re-run resumed the run from its stored checkpoint"
        )
    finally:
        await purge_run(app_conn, run)
````

Edit 78 (`tests/e2e/test_r105_walking_skeleton.py`), replace:

````python
EVIDENCE = Path("reports/skeleton/r105-walking-skeleton.txt")
EXPECTED_EVENTS = [
    ("run.accepted", "application"),
    ("tool.started", "application"),
    ("tool.completed", "application"),
    ("explanation.ready", "model_summary"),
    ("proposal.ready", "application"),
    ("approval.recorded", "application"),
````

with:

````python
EVIDENCE = Path("reports/skeleton/r105-walking-skeleton.txt")
EXPECTED_EVENTS = [
    ("run.accepted", "application"),
    *[("tool.started", "application"), ("tool.completed", "application")] * 3,  # T20: status, alerts, search
    ("explanation.ready", "model_summary"),
    ("proposal.ready", "application"),
    ("approval.recorded", "application"),
````

Edit 79 (`tests/e2e/test_admission_live.py`), replace:

````python
            messages(await conversation(c, created)), headers=h(), json={"kind": "clarification", "text": "A17"}
        )
        seen["reject"] = reject.status_code
        # Nothing in the worker asks for clarification yet (T20), so the run is staged where the worker would put it,
        # through the worker role's own function (as tests/e2e/test_definers_run_path_live.py does).
        run_id = UUID(inv_body["run_id"])
        async with worker.transaction():
````

with:

````python
            messages(await conversation(c, created)), headers=h(), json={"kind": "clarification", "text": "A17"}
        )
        seen["reject"] = reject.status_code
        # The worker's graph asks only after a draft (T20); this API-boundary test stages the run where it would be,
        # through the worker role's own function (as tests/e2e/test_definers_run_path_live.py does).
        run_id = UUID(inv_body["run_id"])
        async with worker.transaction():
````

Gates: `git add tests/e2e/test_graph_live.py`; dev `CHECK: GREEN`, `1721 passed, 227 skipped` (the five new live
tests skip without `OPS_LIVE=1`); `verify_handoff.py` exit 0.

- [ ] **Step 2: The live gate (these database tests have never run, departure 1)**

With the dev stack up, local Ollama answering and every skeleton process down, run `PYTHONUTF8=1 uv run python
scripts/check.py --profile test < /dev/null` → `CHECK: GREEN` with `1927 passed, 21 skipped` (arithmetic). It writes
`reports/graph/t20-graph-live.md`: a title line, then five lines — R108's stub, R122, the proposal path's node order
(`load_run → route_request → retrieve_evidence → route_request → draft_with_langchain → route_request →
validate_and_freeze → route_request → await_independent_decision`), the clarification's state history across the restart
(`QUEUED → RETRIEVING → DRAFTING → AWAITING_INPUT → QUEUED → RETRIEVING → DRAFTING → AWAITING_APPROVAL`) and the
answer_only path ending ANSWERED. If a live test fails, stop and report it with its output (NEEDS_CONTEXT): the expected
behaviour is in the test's docstring and Review Focus 1, and a fix is a review decision, not an improvisation. Then `git
checkout -- reports` for every other rewritten report and keep the new one.

```bash
git add tests/e2e reports/graph/t20-graph-live.md
git commit -m "test: the graph on the Postgres saver, live (T20: R022, R038, R042, R091, R108, R114, R122)"
```

---
### Task 6: Close-out — records, requirements, errata 122-130, state, history, final gates

**Files:**
- Modify: `handoff/tasks.json` (T20 → `DONE` with a review note; M07 → `DONE`; `current_milestone` → `M08`),
  `handoff/acceptance-matrix.json` (R022, R038, R042, R091, R108, R114, R122, R129), `handoff/BUILD_BACKLOG.md` (T20
  checked; its note), `SESSION_STATE.md` (the milestone, the next task, a "Plan Q executed" section with errata 122-130,
  the owner inputs), `STATUS.md` (the LangGraph row; an update section), `README.md` (the Orchestrator row),
  `docs/ARCHITECTURE.md` (§3's diagram and text; "Where the code will live"), `docs/PROJECT_HISTORY.md` (a new section
  35; "What the process taught" becomes 36), this plan (its checkboxes); the files the final live run rewrites

**Requirements:** ruling 17; the T20 record (DoD 1-4). This task writes no behaviour.

Throughout, `<base>..<last>` is the git range of this plan's execution on `plan-q` (`<base>` the `BASE` of Task 1
Step 1b, excluded; `<last>` the newest commit before this task's own). `<date>` is `date -u +%F`. `<dev>` and `<live>`
are the final gates' pytest lines. Step 4 replaces every placeholder.

- [ ] **Step 1: Handoff records**

Save this outside the repository as `t20_records.py` (in the implementer's scratchpad) and run `BASE=<hash> uv run
python -I <path>/t20_records.py < /dev/null` from the repository root. It stops if the live report is missing or a
record is not in the state this plan found it.

````python
"""Plan Q close-out: T20's handoff records (tasks.json, the acceptance matrix, BUILD_BACKLOG.md).

Run from the repository root as `BASE=<hash> uv run python -I <path>/t20_records.py < /dev/null`. It stops if the
live report is missing (Task 5 commits it) or if any record is not in the state Plan Q found it.
"""

import json
import os
import subprocess
from pathlib import Path

base = os.environ["BASE"]
last = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True).stdout
subprocess.run(["git", "merge-base", "--is-ancestor", base, "HEAD"], check=True)  # the base is this branch's own
span = f"{base}..{last.strip()}"
assert Path("reports/graph/t20-graph-live.md").is_file(), "Task 5's live report is missing"
note = (
    f"Plan Q (branch plan-q): done in {span} (the debt list, then four building tasks and the live gate; the close-out "
    "is the next commit; plan docs/superpowers/plans/2026-10-25-first-slice-q-langgraph-workflow.md). Shipped: the "
    "graph package worker/src/ops_worker/graph/ (SA:207's ten nodes; route_request's conditional edges generated from "
    "ops_core.routing.GRAPH_ROUTES over SA:377's seven dimensions; publish_state ends the graph run when the table "
    "routes publish); langgraph 1.2.14 and langgraph-checkpoint-postgres 3.1.2 (AsyncPostgresSaver on the worker's "
    "fourth connection, search_path=checkpoints,pg_temp); revision 0015 (schema checkpoints, the saver's DDL frozen "
    "and its versions recorded, worker-only DML); every invocation durability=sync with stream_mode=checkpoints, each "
    "announced checkpoint confirmed by aget_tuple and stored in runs.checkpoint_id under the fence; retrieval reads the "
    "asset status, the interval's alerts and the procedures (two retries of a transient read; a 401 told apart) and "
    "SA:377's sufficiency rule (erratum 122); questions interrupt with the event id, release the lease and resume with "
    "Command(resume=clarification.received id) in the resume_input job; answers end ANSWERED with the cited summary in "
    "explanation.ready (erratum 124); the reviewer wait interrupts with the proposal id and the execute job resumes it; "
    "crash recovery forks from the stored id; the router rereads the run's dimensions on every hop; a missing stored "
    "id fails the run. DoD 1: tests/plan_q/test_graph_flow.py "
    "and tests/e2e/test_graph_live.py (every read before the draft). DoD 2: the restart test and the stray-head test. "
    "DoD 3: R091's grep of the checkpoint rows, blobs and writes. DoD 4: tests/plan_q/test_graph_routes.py (every row "
    "walked to its node). Deferred: the fenced saver -> T38; revision re-entry -> T21; recover jobs and re-queued reads "
    "-> T22; the budget's human-wait exclusion -> T29. Errata 122-130 are proposed in SESSION_STATE.md."
)
tasks_path = Path("handoff/tasks.json")
tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
t20 = next(t for t in tasks["tasks"] if t["id"] == "T20")
m07 = next(m for m in tasks["milestones"] if m["id"] == "M07")
assert t20["status"] == "PLANNED" and len(t20["review_notes"]) == 2 and tasks["current_milestone"] == "M07"
assert m07["status"] == "PLANNED"
t20["status"] = "DONE"
t20["review_notes"].append(note)
m07["status"] = "DONE"  # T19 and T20, both DONE
tasks["current_milestone"] = "M08"
tasks_path.write_text(json.dumps(tasks, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

GRAPH = ["worker/src/ops_worker/graph/build.py", "worker/src/ops_worker/graph/nodes.py"]
LIVE = ["tests/e2e/test_graph_live.py", "reports/graph/t20-graph-live.md"]
FLOW = "tests/plan_q/test_graph_flow.py"
ROWS = {
    "R022": (
        [*GRAPH, "worker/src/ops_worker/handlers.py", FLOW, *LIVE],
        "Plan Q (T20): both waits are interrupts that end the graph run, after which the job's final unit releases the "
        "lease; the live test finds the lease released, no worker backend idle in a transaction and the model permit "
        "free while the run waits for its reviewer. The budget's human-wait exclusion is T29's.",
    ),
    "R038": (
        [*GRAPH, FLOW, *LIVE],
        "Plan Q (T20): retrieve_evidence reads the asset status, the interval's alerts and the procedures, and the "
        "draft node runs only after it (the per-run node log); live, every tool.completed precedes the "
        "explanation.ready written in the drafts row's unit, and the request carries the status and alert records.",
    ),
    "R042": (
        [*GRAPH, "worker/src/ops_worker/handlers.py", FLOW, *LIVE],
        "Plan Q (T20): a clarification survives a restart: after the interrupt the first saver connection is closed, the "
        "API's reply path commits the reply, and a new graph instance on a new saver connection resumes from the stored "
        "id with the reply's event (no fork) and runs on to AWAITING_APPROVAL. A killed process is the limit (T30).",
    ),
    "R091": (
        ["worker/src/ops_worker/graph/state.py", FLOW, *LIVE],
        "Plan Q (T20): graph state is ids, verdicts and enum values only, and interrupts carry an event or proposal id; "
        "the evidence bundle and the draft are held in memory between nodes. Greps of the in-memory saver and of the "
        "Postgres checkpoint rows, blobs and writes after each pause find no proposal, question, answer or alert text.",
    ),
    "R108": (
        ["worker/src/ops_worker/graph/build.py", "worker/src/ops_worker/handlers.py", FLOW, *LIVE],
        "Plan Q (T20): every invocation passes durability='sync' and streams checkpoints (a spy on the call pins the "
        "argument); live, a stub node at step N+1 finds step N's checkpoint already in the Postgres saver (the "
        "behaviour); each announced checkpoint is confirmed by aget_tuple and stored under the fence; resumes name the "
        "stored id, and a newer head written after it is ignored (the stray-head test); crash recovery forks and stores "
        "the fork.",
    ),
    "R114": (
        [*GRAPH, FLOW, *LIVE],
        "Plan Q (T20): an answer draft takes the answer_only route on any intent (DEV-002); publish_state writes the "
        "drafts row, explanation.ready with the cited answer and DRAFTING -> ANSWERED in one unit; no proposal, so no "
        "grant; the live answer_only run ends ANSWERED with no proposal row.",
    ),
}
matrix_path = Path("handoff/acceptance-matrix.json")
matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
by_id = {r["id"]: r for r in matrix["requirements"]}
for rid, (paths, row_note) in ROWS.items():
    row = by_id[rid]
    assert row["implementation_status"] == "NOT_IMPLEMENTED_OR_NOT_TARGET_VERIFIED" and row["evidence_status"] == "NOT_RUN"
    row["implementation_status"] = "IMPLEMENTED_LOCALLY_VERIFIED"
    row["evidence_status"] = "RECORDED_LOCALLY_LIVE"
    row["evidence_paths"] = paths
    row["note"] = row_note
r129 = by_id["R129"]
assert r129["note"].endswith("the graph router's table and its walk land with T20.")
r129["evidence_paths"] += ["core/src/ops_core/routing.py", "tests/plan_q/test_graph_table.py", "tests/plan_q/test_graph_routes.py"]
r129["note"] += (
    " Plan Q (T20): the graph router's table is ops_core.routing.GRAPH_ROUTES; route_request's conditional edges are "
    "generated from it, and a test walks every row through the compiled graph to its node; the keys the worker can "
    "produce all have a row; a model's draft kind selects only abstain, clarify, answer or freeze."
)
r122 = by_id["R122"]
assert r122["evidence_status"] == "NOT_RUN" and r122["owning_tasks"] == ["T09"]
r122["implementation_status"] = "IMPLEMENTED_LOCALLY_VERIFIED"
r122["evidence_status"] = "RECORDED_LOCALLY_LIVE"
r122["evidence_paths"] = ["migrations/app/versions/0015_checkpoints.py", "tests/plan_q/test_migration_0015.py", *LIVE]
r122["note"] = (
    "Deferred to T20 (Plan E ruling 2) and built there: revision 0015 creates schema checkpoints with the saver's "
    "tables (its setup() statements frozen, erratum 126); the worker holds USAGE and DML, the api, the sweeper and "
    "mcp_read are refused at the schema (live). The owner stays T09."
)
matrix_path.write_text(json.dumps(matrix, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

backlog_path = Path("handoff/BUILD_BACKLOG.md")
backlog = backlog_path.read_text(encoding="utf-8")
open_line = "- [ ] **T20 LangGraph workflow with sync durability and stored checkpoint IDs**"
assert backlog.count(open_line) == 1
backlog = backlog.replace(open_line, "- [x] **T20 LangGraph workflow with sync durability and stored checkpoint IDs**")
anchor = "test two crashes in a row. Define revision re-entry (new thread per revision or explicit edges back to retrieval).\n"
assert backlog.count(anchor) == 1
backlog = backlog.replace(anchor, anchor + f"  - *Review note:* {note}\n")
backlog_path.write_text(backlog, encoding="utf-8", newline="\n")
print(f"T20 DONE; M07 DONE; current milestone M08; rows {', '.join([*ROWS, 'R122', 'R129'])}; span {span}")
````

Expected: `T20 DONE; M07 DONE; current milestone M08; rows R022, R038, R042, R091, R108, R114, R122, R129; span
<base>..<last>`.

- [ ] **Step 2: State, status, the architecture page and the history**

Edit 80 (`SESSION_STATE.md`), replace:

````markdown
**Current milestone:** M07 (the LangChain draft node and the LangGraph workflow; T19 is DONE in Plan P and T20 is next. M06 closed with T18 in Plan N; its T41, the owner's holdout labels, is optional since erratum 114. Every task of M00 to M05 is DONE or DONE_PENDING_OWNER, and the owner steps of M00 and M01 are listed below)
**Next task:** T20 (the LangGraph workflow). Plan P (T19) is executed on branch `plan-p` (`ee2729d..737d1ab` holds the
````

with:

````markdown
**Current milestone:** M08 (independent review, grant, execution and recovery; T21 is next. M07 closed with T20 in Plan Q, after T19 in Plan P. M06 closed with T18 in Plan N; its T41, the owner's holdout labels, is optional since erratum 114. Every task of M00 to M05 is DONE or DONE_PENDING_OWNER, and the owner steps of M00 and M01 are listed below)
**Next task:** T21 (per-revision proposals, the decision rules and the manual path). Plan Q (T20) is executed on
branch `plan-q` (`<base>..<last>` holds the debt list, the four building tasks and the live gate; the close-out is the
commit after `<last>`). T20 is DONE: the run's lifecycle is one LangGraph graph on the Postgres saver with synchronous
durability and the stored checkpoint id (R022, R038, R042, R091, R108, R114 and R122 live; R129's graph half); errata
122-130 are proposed (see "Plan Q executed"). Owner inputs added by Plan Q: decide errata 122-130; migrate the dev
database to 0015 (the worker refuses to start without `checkpoints.checkpoints`). Plan P (T19) is executed on branch
`plan-p` (`ee2729d..737d1ab` holds the
````

Edit 81 (`SESSION_STATE.md`), replace:

````markdown
## Walking-skeleton debt list (T08; committed before coding) [R6-B7]
````

with:

````markdown
## Plan Q executed (<date>, branch `plan-q`)

- T20 = `<base>..<last>` (the debt list first, then the four building tasks, the live gate and their review fixes;
  the close-out is the commit after `<last>`). The plan (`docs/superpowers/plans/2026-10-25-first-slice-q-langgraph-
  workflow.md`) holds the 17 rulings of the controller's brief as implemented, with its departures named at its top;
  the input is `docs/superpowers/research/2026-10-25-plan-q-inputs.md`. Evidence: `core/src/ops_core/routing.py`
  (`GRAPH_ROUTES`), `worker/src/ops_worker/graph/`, `worker/src/ops_worker/handlers.py`,
  `worker/src/ops_worker/evidence.py`, `migrations/app/versions/0015_checkpoints.py`, `tests/plan_q/` (unit, on
  LangGraph's in-memory saver and Plan H's fakes), `tests/e2e/test_graph_live.py` and `reports/graph/t20-graph-live.md`
  (live, on the Postgres saver).
- Gates: `PYTHONUTF8=1 uv run python scripts/check.py` `CHECK: GREEN`, pytest `<dev>`; `PYTHONUTF8=1 uv run python
  scripts/check.py --profile test` `CHECK: GREEN`, pytest `<live>`; `verify_handoff.py` exit 0.
- Dependencies: `langgraph==1.2.14` and `langgraph-checkpoint-postgres==3.1.2` in `ops-worker` (SA:580-581, resolved as
  pinned); `uv lock` added langgraph 1.2.14, langgraph-checkpoint 4.3.0, langgraph-checkpoint-postgres 3.1.2,
  langgraph-prebuilt 1.1.1, langgraph-sdk 0.4.9, ormsgpack 1.13.0 and psycopg-pool 3.3.3 (a declared dependency of
  the saver package; the worker opens no pool).
- **Proposed errata (the owner decides; the spec text stays authoritative until then).** Numbered on from Plan P's:
  122. SA:377 ("evidence sufficient?"): at least one status observation in state `normal` or `warning` (`unavailable`
       observes nothing) observed within 5 minutes (SA:462's asset freshness) of the instant mcp-read answered, and at
       least one effective procedure section, every returned section retrieved within the same 5 minutes. The
       search's minimum rank (0.25, T17) is v1's relevance criterion; erratum 102's residue stays measured (T25).
  123. SA:510 and SA:523 are silent on schema `checkpoints`: its tables carry no RLS (they are not tenant rows; only the
       worker reads them, by thread id); R122's isolation is the schema privilege.
  124. SA:496 ("never written ... to events"): the validated question rides in `clarification.requested.message` and
       the validated answer's summary and citations in `explanation.ready` (`source=model_summary`), so the requester
       sees them; the draft payload itself stays out of `drafts`, checkpoints and events, and the proposal path's
       `explanation.ready` stays templated (erratum 117).
  125. AM-80 and erratum 120: a run that retrieves again after a clarification keeps its one manifest; whether a
       revision records its own is T21's decision.
  126. SA:559 (the migrator runs `PostgresSaver.setup()`): revision 0015 runs the same statements, frozen with the
       schema named and `CONCURRENTLY` dropped (Alembic runs one transaction), and records the version rows `setup()`
       writes, so a later `setup()` applies nothing. SA:434's "worker: all DML" on schema `checkpoints` excludes
       `checkpoint_migrations`, the library's bookkeeping, which only the revision writes.
  127. AM-15 (SA:343) and `JOB_RULES`: a `resume_input` job's read handle also works in RETRIEVING and DRAFTING, because
       the resumed graph carries the run through retrieval and drafting under the same lease.
  128. SA:207, SA:496 ("one node") and `docs/ARCHITECTURE.md` §3 ("every node returns to route_request"): the validated
       draft is held in the worker's memory between `draft_with_langchain` and the node its kind routes to, within one
       graph run (a resumed graph run without the hold retrieves and drafts again); `publish_state` ends the graph run
       when the table routes `publish` and otherwise returns to the router; `execute_approved_proposal` hands over to
       `reconcile_outcome`, which ends the execute job's graph run. A run recovered after a completed draft drafts
       again, so it can exceed BS:554's two generation attempts and BS:555's 90 s per run, bounded only by each job's
       own budget (T29). The graph thread of a rejected run ends at the reviewer wait: `record_decision` queues no job
       on a rejection, `publish_state` does not run for it in v1, and the run's REJECTED state is the API's.
  129. SA:451: a run that waits in AWAITING_INPUT and cannot be resumed (no stored checkpoint, or a reply that is not
       the latest) walks AWAITING_INPUT -> QUEUED -> RETRIEVING -> FAILED in one unit, the worker's only path to FAILED.
  130. SA:136 (RETRIEVING -> AWAITING_INPUT when required context is missing or ambiguous) is not taken in v1: an asset
       the asset service does not know ends INSUFFICIENT_EVIDENCE, because the run's asset is fixed (SA:154) and a reply
       could not change it.
- Limits: the database live tests were first run in execution (the plan writer could not reach the stack's `.env`);
  R042's restart is a new graph instance on a new saver connection in one process, not a killed process (T30).

## Walking-skeleton debt list (T08; committed before coding) [R6-B7]
````

Edit 82 (`SESSION_STATE.md`), replace:

````markdown
  executed"), 103-106 (see "Plan M executed"), 107-111 (see "Plan N executed"), 112-113 (see "Plan O executed") and
  115-121 (see "Plan P executed").
- Migrate the dev database to revision 0014 (`uv run python scripts/skeleton.py migrate`): the worker refuses to start
  on 0013, which lacks `app.run_manifests`. To run the worker on the real model, set `MODEL_MODE=qwen3:8b`; the
````

with:

````markdown
  executed"), 103-106 (see "Plan M executed"), 107-111 (see "Plan N executed"), 112-113 (see "Plan O executed"),
  115-121 (see "Plan P executed") and 122-130 (see "Plan Q executed").
- Migrate the dev database to revision 0015 (`uv run python scripts/skeleton.py migrate`): the worker refuses to start
  on 0013, which lacks `app.run_manifests` and `checkpoints.checkpoints`. To run the worker on the real model, set
  `MODEL_MODE=qwen3:8b`; the
````

Edit 83 (`STATUS.md`), replace:

````markdown
| LangGraph | Historical integration example only | Wire persistent/fenced graph, durable pauses and versioned recovery |
````

with:

````markdown
| LangGraph | One explicit graph on the Postgres saver (T20): sync durability, stored checkpoint ids, durable pauses | Fenced saver (T38, M15) and versioned recovery (T36) |
````

Edit 84 (`STATUS.md`), replace:

````markdown
- Next: T20 (the LangGraph workflow).
````

with:

````markdown
- Next: T20 (the LangGraph workflow).

## Update — Plan Q executed (<date>, branch `plan-q`)

- Plan Q (T20: the LangGraph workflow) executed on branch `plan-q` (`<base>..<last>`); the plan is
  `docs/superpowers/plans/2026-10-25-first-slice-q-langgraph-workflow.md`. T20 is DONE and M07 with it.
- `PYTHONUTF8=1 uv run python scripts/check.py` is `CHECK: GREEN`: pytest `<dev>`. `PYTHONUTF8=1 uv run python
  scripts/check.py --profile test` is `CHECK: GREEN`: pytest `<live>`. `verify_handoff.py` exits 0.
- **Evidenced** (`IMPLEMENTED_LOCALLY_VERIFIED`, `RECORDED_LOCALLY_LIVE`): R022 (the waits release the lease, no open
  worker transaction, the permit free), R038 (every read before the draft), R042 (a clarification across a restart),
  R091 (no text in checkpoint rows, blobs or writes), R108 (the `durability="sync"` argument pinned by a spy, a live
  stub finding the previous step's checkpoint stored, the stored id, a stray head ignored),
  R114 (ANSWERED with the cited answer, no proposal), R122 (schema `checkpoints` the worker's alone; owner T09); R129's
  graph half (every row walked to its node).
- Built: `GRAPH_ROUTES` in `ops_core.routing`; `worker/src/ops_worker/graph/` (ten nodes, edges generated from the
  table); revision 0015; the asset status and alerts in the evidence bundle with SA:377's sufficiency rule; the
  `resume_input` handler; crash recovery from `runs.checkpoint_id`. The dev database is still at 0013; the worker needs
  0014 and 0015 (`skeleton.py migrate`, an owner step).
- Deferred, each with its owner in `SESSION_STATE.md`: the fenced saver -> T38; revision re-entry and the write-tool
  discovery -> T21; recover jobs and re-queued reads -> T22; the human-wait budget -> T29. Nine errata (122-130).
- Next: T21.
````

Edit 85 (`README.md`), replace:

````markdown
| **Orchestrator** | One explicit LangGraph graph: evidence before drafting, durable pauses, synchronous checkpoints, never the authority | R038, R042, R108, R091 |
````

with:

````markdown
| **Orchestrator** | One explicit LangGraph graph: evidence before drafting, durable pauses, synchronous checkpoints, never the authority | R038, R042, R108, R091, R022, R114 |
````

Edit 86 (`docs/ARCHITECTURE.md`), replace:

````markdown
  R -->|publish| P
  E --> R
  D --> R
  V --> R
  X --> R
  O --> R
```

Every node returns to `route_request`, and every labelled edge is one row of the AM-16 route table (ten routes). The two interrupt nodes end the graph run; a committed human event and its wake-up job start a new run of the graph from the stored checkpoint. Nodes are deterministic Python; only `draft_with_langchain` calls the model, and only `retrieve_evidence`, `execute_approved_proposal` and `reconcile_outcome` call MCP servers.
````

with:

````markdown
  R -->|publish| P
  E --> R
  D --> R
  V --> R
  C --> R
  A --> R
  X --> O
  P -->|not settled| R
  P -->|settled| Z((end))
  O --> Z
```

The working nodes and the two waiting nodes return to `route_request`, and every labelled edge out of it is generated from the AM-16 route table (`ops_core.routing.GRAPH_ROUTES`, built by T20; ten routes). The two waiting nodes interrupt, which ends the graph run and releases the lease; the committed human event's wake-up job (`resume_input`, or `execute` after a decision) resumes the graph from the stored checkpoint with `Command(resume=<event id>)`. `publish_state` ends the graph run once the table routes the run to `publish` (erratum 128), and in v1 `execute_approved_proposal` hands over to `reconcile_outcome`, which ends it (recovery is T22's). Nodes are deterministic Python; only `draft_with_langchain` calls the model, and only `retrieve_evidence` and `execute_approved_proposal` call MCP servers (`reconcile_outcome`'s calls arrive with T22).
````

Edit 87 (`docs/ARCHITECTURE.md`), replace:

````markdown
| `worker/graph/` | the orchestrator's nodes and edges |
````

with:

````markdown
| `worker/src/ops_worker/graph/` | the orchestrator's nodes and edges (written by T20) |
````

Edit 88 (`docs/PROJECT_HISTORY.md`), replace:

````markdown
## 35. What the process taught
````

with:

````markdown
## 35. The workflow plan put the run's lifecycle into one graph

**Problem.** Plan Q takes T20: the worker ran each job as a straight-line handler that failed a run it found
interrupted, routed only proposals, and kept no checkpoint. The spec asks for one explicit LangGraph graph whose
router is a table, synchronous checkpoints whose accepted id is stored under the lease fence, interrupts that carry
ids only, waits that hold no lease, and an ANSWERED path, all without the checkpoint ever holding evidence or model
text.

**Change.** The graph's router is a table in core, and the graph's conditional edges are generated from it, so a test
can walk every row to the node it reaches. Each job runs one graph run under its lease: every checkpoint LangGraph
announces is confirmed by reading it back and then stored in `runs.checkpoint_id` under the fence, because the
library announces a run's first checkpoint before it has written it. A question or a reviewer wait interrupts with an
event or proposal id, the job releases the lease, and the wake-up job resumes from the stored id; a crash resumes from
it too and ignores any newer head. Retrieval now reads the asset status and the alerts as well as the procedures and
judges them by SA:377's code rule; the evidence and the draft stay in the worker's memory between nodes, never in a
checkpoint.

**Review.** Building the slice in a scratch copy found what reading had not: a clarified run that retrieved again
would have hit the manifest's primary key; a `resume_input` job could not read in RETRIEVING (the allowlist said
AWAITING_INPUT and QUEUED only); a crash resumes at the node that was next, which may be the one that needs the lost
draft, so every consumer routes a missing hold back through retrieval and `publish_state` leaves the graph only when
the table says the run is settled; and the MCP SDK reports every non-2xx answer the same way, so the worker's client
records HTTP statuses itself to tell a refused token from a transport failure. The static review then found that a
node's early return left the router's decision dimensions stale, so an approved run that had forked from before its
freeze could never execute; the router now rereads them on every hop. It also found R108's synchronous persistence
evidenced only by an argument spy (a live stub test now shows a step finding the previous checkpoint stored), and an
execute job's resume value used unchecked (now checked against the run's latest decision). The database live tests
were written blind (the scratch copy could not reach the stack's `.env`) and first ran in execution.

## 36. What the process taught
````

- [ ] **Step 3: Final gates**

Dev `CHECK: GREEN`, `1721 passed, 227 skipped`; live `CHECK: GREEN`, `1927 passed, 21 skipped` (then `git checkout --
reports`, keeping `reports/graph/t20-graph-live.md` as the run rewrote it); `verify_handoff.py` exit 0.

- [ ] **Step 4: Placeholders, checkboxes and the commit**

Fill in `<base>`, `<last>`, `<date>`, `<dev>` and `<live>` in `SESSION_STATE.md` and `STATUS.md` with the values
(`grep -n "<base>\|<last>\|<date>\|<dev>\|<live>" SESSION_STATE.md STATUS.md` prints nothing afterwards); tick this
plan's checkboxes. The history section's review paragraph names this plan's review rounds and execution findings
when the controller writes it.

```bash
git add handoff SESSION_STATE.md STATUS.md README.md docs/ARCHITECTURE.md docs/PROJECT_HISTORY.md \
  docs/superpowers/plans/2026-10-25-first-slice-q-langgraph-workflow.md reports/graph/t20-graph-live.md
git commit -m "docs: close T20 (Plan Q) - records, R022/R038/R042/R091/R108/R114/R122, errata 122-130, state and history"
```

## Review Focus

1. **The live tests have never run (departure 1).** `tests/e2e/test_graph_live.py` (R108's step-N+1 stub; R122's
   refusals and version rows;
   the stored head with its `__interrupt__` write; R022's lease, `pg_stat_activity` and permit checks; R091's grep;
   the clarification across a restart through the API's own `DbUnit.record_reply`; the answer_only run) and the edited
   `test_worker_live.py` (three reads before the draft), `test_heartbeat_live.py` (the re-run now resumes and ends
   AWAITING_APPROVAL) and `test_r105_walking_skeleton.py` (three read pairs; it reads the real asset-sim, so A17's
   status must be `normal` or `warning`, and the search's `retrieved_at` and the status's `observed_at` must both be
   the database's instant). `test_admission_live.py` stages AWAITING_INPUT and posts a reply with no worker running;
   if a skeleton worker were running it would now take the `resume_input` job.
2. **Checkpoint confirmation.** `build.confirm` polls `aget_tuple` up to 5 s; the Postgres saver writes in pipeline
   mode on its own autocommit connection. A first-checkpoint or fork write slower than that fails the graph run.
3. **The in-memory hold (departure 2, erratum 128).** A crash between the draft and its consumer loses the draft; the
   run goes back through retrieval and drafts again (a second model call, `tool.*` events repeated). Check that no
   path writes model text to state, `drafts` or a checkpoint.
4. **Entry decisions in `handlers.py`.** Investigate: QUEUED with no stored id is a new graph run; QUEUED with one,
   RETRIEVING or DRAFTING is recovery (a fork); mid-run with none is INTERRUPTED. Resume_input: AWAITING_INPUT resumes
   with the reply's event; any other active state carries on as investigate would. Execute: the reviewer wait is
   resumed with `approval.recorded`'s id; a re-queued execute forks to re-run the execute node.
5. **The router table's reachable rows** (`test_graph_table.produced`): a key a node can produce with no row fails the
   graph run with `LookupError`, which `_drive` turns into FAILED only for a run in RETRIEVING or DRAFTING. Since round
   1 `route_request` rereads the decision and attempt dimensions on every hop (one unlocked SELECT), so a node's early
   return can no longer leave them stale (`test_the_router_rereads_the_runs_dimensions`).

# Plan Q review record — T20 the LangGraph workflow (sync durability, stored checkpoint ids, ID-only interrupts)

Plan: `docs/superpowers/plans/2026-10-25-first-slice-q-langgraph-workflow.md` (branch `plan-q`, from `plan-p`
c96d13c which is PR #15; plan commit 2e2666a, round 1 fixes cfd37fe). Inputs: `docs/superpowers/research/2026-10-25-plan-q-inputs.md`
(17 open questions) and the controller's brief of 17 rulings (reproduced below).

Context. Plan P (T19) had just closed as PR #15 with the drafting route on qwen3:8b; answer and abstain+question
drafts ended FAILED "not routed until T20", and the drafting payload carried no asset status or alerts. T20 puts the
run's lifecycle into one LangGraph graph: a route table in `core/routing.py` generates `route_request`'s edges, every
invocation is `durability="sync"`, each announced checkpoint is confirmed and stored under the fence, the two waits
(clarification, reviewer) are ID-only interrupts after which the lease is released, and a crash resumes from the stored
id. The owner's standing instruction (build autonomously until set up) applies; the controller's owner decisions are
provisional.

How the round ran. The writer built the slice in scratch worktrees of 6466b8c, locked the LangGraph packages for the
first time (`uv lock` added seven packages), generated the plan's code blocks from the tested files and rebuilt a
second tree from the blocks byte-identically. The `.env` copy was refused again, so the database live gate did not run
before execution: live counts are arithmetic and the four new database live tests first run in Task 5. Building found
three faults reading had missed (a clarified run hit the manifest's primary key; a `resume_input` read handle was
refused in RETRIEVING; crash recovery could resume into a node whose in-memory draft was gone), all fixed in the plan.
The writer listed twelve departures; the controller accepted all twelve and an unlisted thirteenth (the execute job
resumes the reviewer wait with the decision's event id, closer to AM-12 than the brief). One static round (lean
process); the controller checked the fix diff instead of running a second.

Round 1: REVISE, 0 Critical, 2 Important, 7 Minor, 3 claims unsettled until the first live run. The critic applied all
102 blocks in a scratch worktree and reproduced the dev gate exactly (1717 passed, 226 skipped). Everything was fixed
in cfd37fe and nothing was parked:
- the router routed on dimensions `load_run` had read while nodes' early returns refreshed only the run state, so an
  approved run that forked from a pre-freeze checkpoint matched no row and could never execute (reproduced by the
  critic with a scratch test; fixed by rereading the facts in `route_request` on every hop);
- R108's "persist synchronously" rested on a kwarg spy; ruling 6's stub-node test on the Postgres saver is now in;
- the execute job's resume value is now verified against the run's latest decision event and active proposal.
Minor: a REJECTED run's thread ends at the reviewer wait (debt line, erratum 128); errata for SA:434 (into 126) and
SA:136 (new 130); recovery after a completed draft can exceed BS:554/555 (debt → T29, test added); five long lines;
a comment on 0015's grants; the `asked` cross-check after a fork.
Dev counts after Tasks 1-5: 1629, 1667, 1672, 1721 and 1721 passed (222, 222, 222, 222 and 227 skipped), measured on
scratch worktrees. Live after Task 5: 1927 passed, 21 skipped (arithmetic). `uv lock` added seven packages (langgraph
1.2.14, langgraph-checkpoint 4.3.0, langgraph-checkpoint-postgres 3.1.2, langgraph-prebuilt 1.1.1, langgraph-sdk 0.4.9,
ormsgpack 1.13.0, psycopg-pool 3.3.3) and removed none.

Holdout custody: no agent opened holdout case material or a seal. None exists in the tree. The fact-sheet writer ran
seven greps without the exclusions (nothing matched, nothing opened); recorded.

Process slips: the critic typed one `uv run python -I - < /dev/null` into the real tree; it hung on stdin, was stopped,
ran no code and changed nothing. No agent connected to the dev database, Keycloak or a service, and none opened `.env`
or a secret file.

---

# Controller brief (rulings before round 1)

## Plan Q brief — controller rulings for T20 (LangGraph workflow with sync durability and stored checkpoint IDs)

Branch `plan-q`: `plan-p` c96d13c (PR #15 against `main`) + 6466b8c (fact sheet). Fact sheet (FS):
`docs/superpowers/research/2026-10-25-plan-q-inputs.md`. Errata continue at **122**. Requirements: R022, R038, R042,
R091, R108, R114, R129 (graph half), and R122 (deferred to T20 by T09).

Gates at start: dev 1629 passed / 222 skipped; live 1830 / 21; verify_handoff exit 0. Dev DB at 0013 (nobody touches
it). Local Ollama 0.40.4 with qwen3:8b and nomic-embed-text.

**Owner's steer:** portfolio project; scaffolding first, lean, built autonomously; owner decisions the controller takes
are provisional. Authority, approval, idempotency and no-unapproved-external-action boundaries unchanged.

**Principle:** T20 puts the run's lifecycle into a LangGraph graph whose router edges are generated from a table in
`core/routing.py`, checkpointed by LangGraph's Postgres saver with sync durability, with the checkpoint id stored under
the fence, ID-only interrupts for clarification, the lease released on every human wait, the ANSWERED path, and crash
recovery from the stored checkpoint. Manual proposals and revision re-entry (T21), recover jobs and bounded retries
(T22), the budget accounting (T29) and the custom fenced saver (T38) stay with their owners.

**Holdout custody:** as always; exclude `*holdout*`, `*seal*`, `*.sha256` from every grep and listing (the fact-sheet
writer's unfiltered greps are recorded as a slip; nothing was opened).

### Rulings (one per FS question)

1. **Location.** The graph is a package `worker/src/ops_worker/graph/` (`state.py`, `nodes.py`, `build.py`). The
   handler stays the job entry point: `handlers.investigate`, a new `handlers.resume_input`, and `handlers.execute`
   each claim the lease as today and then run the graph for that run under it (ruling 14 for execute). The route table
   `GRAPH_ROUTES` lives in `core/src/ops_core/routing.py` beside `ADMISSION_RULES`, in the same style (typed rows, first
   match wins, `LookupError` when none matches), keyed by SA:377's seven dimensions as a frozen dataclass `GraphKey`.
2. **Nodes and generated edges.** SA:207's ten nodes exist as functions. `build.py` adds the conditional edges of
   `route_request` from a mapping built from `GRAPH_ROUTES` at build time (`{GraphRoute: node name}`); tests: (a) the
   compiled graph's edges out of `route_request` equal the table's route set and nothing else; (b) every `GraphRoute`
   value appears in exactly one row's target; (c) R129's walk — a parametrised test over every table row builds the
   `GraphKey` the row matches, asserts `route_request` returns that route and, with the other nodes stubbed to record
   their names, that the named node is reached. The table lists reachable rows only; a test asserts every state the
   worker can be in has a row (enumerate the key space the code can produce). "Context resolved?" follows contract
   erratum 4: missing context is detected in `retrieve_evidence` and routes to the clarify or insufficient row.
3. **Retrieval.** `retrieve_evidence` reads, in order, the asset status (mcp-read's asset tool), the alerts for the run's
   interval, then `search_procedures` (limit 3, the manifest's mode). Sufficiency = SA:377's code rule verbatim (≥1
   permitted status observation and ≥1 effective procedure chunk, within freshness); no further relevance criterion in
   T20 — erratum 122 records that the search's own rank threshold is v1's relevance criterion (closes erratum 102's
   ask to T20). Retryable reads: up to BS:552's 2 retries inside the node, then FAILED with the templated retrieval
   message; a 401 ends FAILED with its own message (debt line: bounded re-queue → T22). Status and alerts enter the
   draft payload under `permitted_evidence` (the bundle gains two sections; the payload keys and the v2 prompt text are
   unchanged, so no new prompt version); the evidence script's figures may move — record that in the debt list, do not
   re-run it in T20. R038's trace: the existing `tool.started`/`tool.completed` events plus a per-run node log the tests
   spy; the live test asserts every read completes before the `drafts` row is written.
4. **Checkpointer.** LangGraph's `AsyncPostgresSaver` in schema `checkpoints` (SA:559-562). Revision 0015 creates the
   schema and the saver's tables by running the package's migration SQL inside Alembic (the writer checks that
   `langgraph-checkpoint-postgres` exposes its DDL statements; if not, the revision opens a sync connection and calls
   `PostgresSaver.setup()` with `search_path=checkpoints`); grants: worker USAGE on the schema and INSERT/SELECT/UPDATE/
   DELETE on its tables, api nothing (R122), sweeper nothing. No RLS on checkpoint tables (they are not tenant tables;
   only the worker reads them, by thread id) — erratum 123 records it against SA:510/523's silence. Graph state never
   holds the draft payload (SA:496): the drafting node validates, freezes and stores inside the node and puts only
   `draft_id`, `kind`, `has_question` and the question's event id into state. R091: a live test reads the run's
   checkpoint blobs and asserts the draft's title and summary text are absent. The worker opens a fourth connection for
   the saver (autocommit, `options=-c search_path=checkpoints,pg_temp`); no pool.
5. **`runs.checkpoint_id`.** thread id = `f"{run_id}:{revision}"` (ruling 13). The handler drives the graph with
   `astream(..., stream_mode="checkpoints", durability="sync")`; after each emitted checkpoint it confirms the id with
   `aget_tuple` and stores it under the fence in its own unit (`fenced` + `UPDATE runs SET checkpoint_id`), with a
   `checkpoints` entry in the lock order (the saver's writes are on their own connection and never inside an app unit).
   On resume a NULL or unknown stored id ends the run FAILED with a templated message (note 2 of the task).
6. **Durability.** `durability="sync"` on every invocation; saver writes are units (never cancelled by the heartbeat,
   which cancels effects only). R108: a unit test spies the invocation kwargs, and a live test's stub node reads the
   saver's latest checkpoint during the next step and asserts it carries the previous step's state.
7. **Interrupts and resume.** `request_clarification` transitions DRAFTING → AWAITING_INPUT and appends
   `clarification.requested {message: the question}` in one unit, puts that event id in state and calls
   `interrupt(event_id)`; the graph run ends; the handler stores the checkpoint id and releases the lease. The resume
   value is the API's `clarification.received` event id (`Command(resume=event_id)`). `handlers.resume_input`: claim
   the lease, load the stored checkpoint id, resume; the resumed node verifies the event exists for this run and is the
   latest `clarification.received`, reads the reply text from `messages` by the event's `message_id` (length re-checked,
   otherwise trusted as the API validated it), transitions AWAITING_INPUT → QUEUED, and the graph continues through
   `route_request` → `retrieve_evidence` → `draft`. Rounds = the count of `clarification.requested` events for the run
   (reread from the database, SA:215), cross-checked against the state's list; a third round → INSUFFICIENT_EVIDENCE.
   A replayed resume is stopped by the job's dedup key; a resume whose event is not the latest ends FAILED.
8. **Question and answer text.** The validated question rides in `clarification.requested.message` (≤2500); on the
   answer path the node emits `explanation.ready {message: the answer's summary, evidence_refs}` and then transitions
   to ANSWERED with a templated `run.answered`. Erratum 124: the validated question and answer text are shown through
   these events; the draft payload itself stays out of `drafts`, checkpoints and events. The writer verifies
   `PAYLOAD_KEYS`/`_append_event` admit `message` for `clarification.requested`; if not, revision 0015 extends them.
9. **Human waits.** The lease is released after every interrupt as today's final unit; `WAKEUPS` unchanged (erratum 62:
   the API inserts `resume_input`). R022 evidenced live after an interrupt: lease row released, no worker backend with an
   open transaction (`pg_stat_activity`), permit free; `budget_used` → T29.
10. **ANSWERED.** Per SA:377 the kind selects the path and only `freeze` is gated by intent: any `answer` → the answer
    path → ANSWERED (so DEV-002 holds); `abstain` + question → clarify (≤2 rounds) else INSUFFICIENT_EVIDENCE; bare
    `abstain` → INSUFFICIENT_EVIDENCE; `proposal` on `answer_only` is refused by validation (then repaired or FAILED).
    The payload tells the model about `answer_only` inside `confirmed_request` ("Answer only; do not propose an
    incident.") — no prompt change (closes Plan P's M10 debt).
11. **Fake route.** `FakeDraftGenerator` returns an `answer` on `answer_only` runs and a proposal otherwise (the skeleton
    and R105 use `investigate`, unchanged); test-only scripted generators give abstain, question and answer drafts; no
    third route (erratum 119).
12. **Crash recovery.** A run found RETRIEVING/DRAFTING with a stored checkpoint id is resumed from that id (LangGraph
    forks; the new id is stored); without one it is INTERRUPTED as today. Guards: the manifest node skips when a row
    exists; the drafting node reuses a validated `drafts` row for this run and revision instead of a second model call;
    `tool.*` events may repeat (recorded). Stray head: a unit test (in-memory saver) writes a later checkpoint directly
    after the stored id, resumes with the stored id in the config and asserts the stray is ignored; DoD 2.
13. **Revision re-entry.** One thread per run and revision (`run_id:revision`); T20 leaves the seam (the handler reads
    the job's revision) and T21 builds re-entry; `build_proposal` stays `revision=1`; the manifest stays one per run in
    v1 (erratum 125: a revision's manifest is T21's decision); `workflow_version` goes in the checkpoint metadata only
    (debt → T21 for a column).
14. **Execute and recover.** The `execute` job enters the graph too: `route_request` reads the run's state (APPROVED) →
    `execute_approved_proposal` → `reconcile_outcome` → end, the nodes wrapping today's `handlers.execute` and
    `_mark_unknown` code with no behaviour change (the existing execute live tests pass unchanged). The `recover` row
    and node exist; in v1 the node logs "recover arrives with T22" and ends the graph run; `recover` jobs stay closed
    unhandled. mcp-write discovery: T20 adds the startup listing check for `create_incident` (as mcp-read's) if it is
    one function and one test; the committed result schema → T21 (debt line).
15. **Tests.** Unit: LangGraph's in-memory saver with Plan H's fake harness; the R129 walk; node idempotency tests
    (replay with state present); the interrupt/resume cycle; the stray head. Live (`--profile test`): the Postgres saver
    end to end on the fake route (proposal path; `answer_only` → ANSWERED; a scripted question → AWAITING_INPUT →
    API-style `clarification.received` → resume → end state), the restart = a new graph instance on a new saver
    connection resumed from the stored id after the interrupt (R042; the process-kill variant is recorded as a limit),
    R091's blob grep, R022's checks, R108's stub. The live test writes `reports/graph/t20-graph-live.md` (committed) with
    the node order and the end states.
16. **Dependencies.** `langgraph==1.2.14` and `langgraph-checkpoint-postgres==3.1.2` (SA:580-581) in `ops-worker`; one
    `uv lock`. If they do not resolve beside `langchain-core 1.7.0` and `psycopg 3.3.6`, take the nearest versions that
    do and record erratum 126 with the reason. No `psycopg-pool` unless the saver requires it. LangSmith stays off.
17. **Records.** R022, R038, R042, R091, R108, R114 and R129's graph half flip to `IMPLEMENTED_LOCALLY_VERIFIED` with
    `RECORDED_LOCALLY`/`RECORDED_LOCALLY_LIVE`; R122 flips with a note that T20 built it (owner stays T09 in the matrix
    with the note). `docs/ARCHITECTURE.md` §3 and "where the code will live", `README.md`'s Orchestrator row, STATUS,
    SESSION_STATE (debt list before coding; the stale "T19 waits on the seal" lines the Plan P sheet listed), tasks.json
    (T20 DONE; `current_milestone` M07 until T21... check the milestone table), BUILD_BACKLOG, acceptance matrix; history
    section 35 before "What the process taught" (→ 36). Resolve every `TODO(T20)` marker. Errata 122-126 as above, more
    from 127 if the writer finds them.

### Constraints for the writer

- Plan file `docs/superpowers/plans/2026-10-25-first-slice-q-langgraph-workflow.md`, Plan P's format, lean: Global
  Constraints, the debt list, 6-7 tasks with exact files, complete code where load-bearing, tests first, exact commands
  and expected outputs, a close-out task.
- Build and gate the slice in a scratch worktree (dev gate, verify_handoff; the live gate if the stack's `.env` is
  reachable to you without copying secrets — otherwise record that the DB live tests are first run in execution, as
  Plan P did). `uv lock` needs the network; record exactly what it adds.
- No connection to the dev database. Live tests touch only `ops_test` and local Ollama (the graph live tests use the
  fake route; no model call is needed).
- Comments per `docs/CODE_COMMENTS.md`. No Claude attribution in commits. LF only.
- Report your departures from these rulings as a numbered list at the end of your reply, each with its reason.

---

# Controller rulings on the writer's departures

## Plan Q — controller rulings on the writer's departures (plan 2e2666a, 5951 lines)

The writer listed twelve departures (plan lines 46-91). Rulings, in the writer's numbering. "Accepted" means the
plan stands as written; "critic checks" names what the static critic must settle before execution.

1. **Live gate not run on the scratch copy.** Accepted — same cause as Plan P (the `.env` copy is refused and no
   other way is tried). Live counts stay arithmetic; Task 5 runs the four new database live tests and the edited ones
   first. Recorded in execution-facts.
2. **Freeze in `validate_and_freeze`, draft held in `Context.held` between nodes.** Accepted: SA:377's intent gate
   needs a node to live in, and the hold is process memory, never state, checkpoint, `drafts` or event (SA:496 kept).
   Critic checks: (a) a graph run that resumes without the hold "routes back through retrieval and drafts again" — on
   the model route that is a second model call for the same run; name whether SA:215/BS:555 (budget, idempotent
   replay) tolerate it and whether the plan's recovery test covers it; (b) the hold is cleared on every exit.
3. **The question's event written by `await_clarification`, rounds counted there from the database.** Accepted — the
   router keeps SA:377's seven dimensions and the node name is SA:207's. Critic checks the `asked` cross-check and
   that a third question cannot interrupt.
4. **No mcp-write discovery check; marker → `TODO(T21)`.** Accepted — ruling 14 was conditional ("if one function and
   one test") and the writer showed the condition fails without a live stack. A debt line must name it (critic
   verifies it is in the Task 1 debt list).
5. **Ruling 2(b) read as "every route is some row's target and maps to exactly one node".** Accepted — several states
   legitimately share `publish`. The walk still covers every row.
6. **`publish_state` has its own conditional exit from the same table; `reconcile_outcome` ends the graph run.**
   Accepted provisionally. Critic checks: the second exit cannot loop (a resumed run routed back to the router must
   reach an end state in bounded steps, including after a second crash); the exit map is also generated from the
   table, not hand-written; ARCHITECTURE §3's diagram is updated in Task 6.
7. **Errata 126-129 reassigned/added.** Accepted. 126 (setup frozen inside the migration) is a legitimate use of the
   slot. Critic checks 127 (which handle semantics change, and that the API/sweeper handles do not widen) and 129
   (AWAITING_INPUT → QUEUED → RETRIEVING → FAILED must be legal under SA:451-453 as written, or the erratum must say
   which line it amends).
8. **Unknown asset abstains, never asks.** Accepted — SA:154 fixes the asset; a reply cannot change it. The
   `context_missing` row must be in the walk.
9. **Execute job with a missing stored checkpoint starts a new graph run.** Accepted — the worker may not move an
   APPROVED run (SA:451). Critic checks that the new run re-reads everything from the database and cannot execute a
   proposal the database does not hold as APPROVED.
10. **No worker grant on `checkpoint_migrations`.** Accepted provided the saver never reads that table outside
    `setup()`; critic verifies in `checkpoint/postgres/aio.py` / `base.py` of the installed 3.1.2.
11. **"Reuse the drafts row" guard is the run-state reread.** Accepted — the `drafts` row and its transition commit
    together. Critic checks the claim against `proposals.py`/`persistence.py` as the plan edits them.
12. **`psycopg-pool` arrives as a declared dependency.** Accepted; recorded in the debt list and the lock note. The
    worker opens no pool (critic greps the plan's worker code for `AsyncConnectionPool`).

**13 (unlisted).** The plan's ruling 14 line (plan 176-178) has the execute job *resume the reviewer wait* with the
decision's event id, i.e. the freeze node interrupts on the proposal id and the graph does not end at freeze. The
brief had the execute job start the graph at `route_request` on APPROVED. The plan's reading follows AM-12 ("the two
waits are ID-only interrupts after which the job releases the lease") more closely than the brief did: **accepted as
the design**, but the writer did not list it as a departure. Critic checks: the interrupt value is the proposal id
only (SA:563); the resume value is the decision's event id and is verified against the database (the proposal is
APPROVED in `proposals`, the event belongs to this run and is the latest decision); a REJECTED decision takes the
table's route; the existing execute live tests pass unchanged as ruled.

Errata numbering after this plan: next free is **130**.

---

# Round 1

## Plan Q — critic round 1 (static), plan 2e2666a

**Verdict: REVISE** — Critical 0, Important 2, Minor 7.

How this was checked: the whole plan read in passes against brief.md, writer-departures-rulings.md, the fact sheet's
citations, SA/BS lines named below, and the tree at 2e2666a. A scratch worktree (now removed) reproduced `uv lock`
(96 packages, the same seven added), applied all 102 Create/Replace/Edit blocks in order (Edits 1-86: every anchor
found exactly once, no Create over an existing file), regenerated the schemas, and ran the dev gate: `CHECK: GREEN`,
`1717 passed, 226 skipped` (the plan's Task 5 figure); ruff clean, mypy clean. One extra scratch test (below, I1)
was run and deleted. The library claims were read in the installed 1.2.14 / 3.1.2 sources. No database, no Ollama.

Custody and rules: no holdout material or seal was opened, read, grepped or listed. **Slip to record:** one Bash call
began with a stray `uv run python -I - < /dev/null` in the real tree (a typing error, against the hard rules). It hung,
was stopped with TaskStop, read nothing (stdin was /dev/null), executed no code and changed no file; `git status` of
the real tree was clean afterwards and HEAD is still 2e2666a.

### Important

#### I1. Stale router dimensions: an approved run whose stored checkpoint predates the freeze can never execute
- **Plan lines:** nodes' early returns that report only `run_state`: `retrieve_evidence` 3979-3980,
  `draft_with_langchain` 4050-4051, `validate_and_freeze` 4102-4103, `await_clarification` 4187-4188, `publish_state`
  4232-4233. Also `test_graph_table.produced()` 501-519 and Review Focus 5.
- **What is wrong:** `decision_present` and `attempt_state` are read only by `load_run`, `await_independent_decision`,
  `execute_approved_proposal` and `reconcile_outcome` (`facts()`). Every other node that finds the run moved on returns
  `{"run_state": X}` and leaves those two keys as `load_run` read them, often while the run was QUEUED. With X =
  APPROVED and the stale `decision_present=False`, no row matches (`approved` needs `decision_present=True`;
  `awaiting_decision` needs AWAITING_APPROVAL), so `route_graph` raises LookupError. EXECUTING with the stale
  `attempt_state=None` fails the same way.
- **How it is reached:** the freeze unit commits, then the lease is lost at the next fenced unit (the
  checkpoint-id store), or the process stops in that window. The stored id is still the checkpoint before
  `validate_and_freeze`, and it holds no interrupt. The re-run investigate job finds AWAITING_APPROVAL and does
  nothing. After approval, `handlers.execute` sees a known, non-interrupted stored id and forks from it (4751-4757).
  `validate_and_freeze` has no hold and returns LOST, so the graph routes to retrieve; `retrieve_evidence` reads
  APPROVED and returns only `run_state`, and the router raises LookupError. `_drive` re-raises because APPROVED is not
  mid-run (4652-4653), `run_forever` logs it, and the job stays claimed until the sweeper reclaims it. Every retry
  repeats the failure until the proposal expires to BLOCKED_REVIEW. No unapproved action is possible (the authority
  holds), but the approved action can never run. SA:215 says every node is idempotent against re-runs; this is a
  re-run it does not survive.
- **Evidence:** a scratch unit test on the plan's own harness (`world`, `job`, `Scripted` from test_graph_flow) armed
  `fenced` to raise LeaseLost once `freeze_proposal` was in the log. It ran `main.run_job`, set the run APPROVED with
  an `approval.recorded` event, then ran the execute job. Result: `LookupError: no graph rule matched state APPROVED
  with draft kind none` (routing.py, `route_graph`). `produced()` assumes `decision_present == (state in DECIDED)` and
  `attempt_state` set only for EXECUTING, so the R129 "every produced key has a route" test cannot see this key.
- **Fix:** have `route_request` merge `await facts(ctx, run_id)` into its update on every hop. That is one unlocked
  SELECT, the router then always routes on authoritative dimensions (BS:305, SA:215), and the early returns no longer
  matter. Alternatively, make every early return `await facts(...)`. Add the scenario above as a unit test. Rewrite
  `produced()` (or add a test) so it covers keys whose state comes from a node's reread and whose other dimensions
  come from an earlier `load_run`, or so it asserts the router always rereads.

#### I2. R108's "persist synchronously" has no behavioural evidence; ruling 6's test was dropped without a departure
- **Plan lines:** ruling 6 as implemented (160-161), Task 5 `test_a_run_waits_for_its_reviewer_at_the_stored_checkpoint`
  (5134-5145), the Task 6 R108 note (5622-5627).
- **What is wrong:** ruling 6 asked for "a live test's stub node reads the saver's latest checkpoint during the next
  step and asserts it carries the previous step's state". The plan has instead (a) a spy on the `astream` kwargs and
  (b) a live check, after the graph run ends, that the stored id is the thread's newest checkpoint and holds the
  `__interrupt__` write. Check (b) would pass with `durability="async"` too: by the time `handle` returns, every write
  has been flushed. So the only evidence of synchronous persistence is a kwarg spy. Departures 1-12 do not list this,
  yet Task 6 flips R108 to `IMPLEMENTED_LOCALLY_VERIFIED` / `RECORDED_LOCALLY_LIVE` with "sync durability" in STATUS.
- **Fix:** add the ruled test. Use a stub node in a `build_graph(saver, replace=...)` graph on the Postgres saver (or
  the in-memory one for a unit version) that calls `aget_tuple` for the thread during step N+1 and asserts the step-N
  checkpoint and its values are already there. Or list the departure and narrow R108's note to what is evidenced.

### Minor

#### M1. The execute job's resume value is never verified (controller check 13)
- **Plan lines:** 101 ("a resume value is checked against the database, never trusted"), 4263-4274, 4727-4757.
- **What is wrong:** on resume, `await_independent_decision` re-runs, finds APPROVED and never calls `interrupt`, so
  the `approval.recorded` id passed as `Command(resume=...)` is ignored. `_approval` takes the newest
  `approval.recorded` without comparing its payload's `proposal_id` (0004:225-226) with `runs.active_proposal_id`.
  Safety holds because the router rereads APPROVED and `decision_present`, and mcp-write's grant is the gate. But the
  ruling's "verified against the database (APPROVED in proposals, the event belongs to this run and is the latest
  decision)" is not done, and line 101 overstates it.
- **Fix:** before resuming, check that the event is this run's latest decision event and that its `proposal_id` is
  the active proposal; otherwise fail closed with a template. Or correct line 101 and the R108/R022 notes.

#### M2. A REJECTED decision never reaches the table's route (controller check 13)
- **What is wrong:** `record_decision` queues an `execute` job only on approve (0004:219-231). A rejected run's thread
  therefore stays at the reviewer interrupt for good, and the `settled` row for REJECTED is reached only in the
  stubbed walk. The database stays the authority, so nothing is unsafe.
- **Fix:** add a debt line (or a sentence in erratum 128) saying that the graph thread of a rejected run ends at the
  wait and that `publish_state` is not run for it in v1.

#### M3. Errata the plan should propose but does not (next free 130)
- **SA:434** ("schema `checkpoints` | worker: all DML") against no worker cell on `checkpoint_migrations`
  (departure 10). Neither 123 nor 126 says this.
- **SA:136** ("RETRIEVING → AWAITING_INPUT when required context is missing or ambiguous"): the plan never takes that
  transition, and an unknown asset ends INSUFFICIENT_EVIDENCE (departure 8). Name the line in an erratum, or fold it
  into 122 or 128.

#### M4. The second model call after a lost hold (controller check 2a)
- **What is wrong:** SA:215 tolerates it: nodes reread state and nothing text-bearing was persisted. But a crash after
  a completed draft makes a third and fourth generation attempt for the run, which exceeds BS:554's "at most two
  generation attempts including repair". The new job's budget is counted from its own claim (`lease.held_for()`), so
  BS:555's 90 s per run is not bounded either.
- **Gaps:** the debt line (320-321) says "→ recorded, no task", yet T29 owns the budget. Erratum 128 does not name
  BS:554/555. `test_a_run_interrupted_twice_mid_draft…` covers the route-back only for a draft that never completed;
  no test covers a completed draft whose hold was lost.
- **Fix:** debt "→ T29"; name BS:554/555 in erratum 128; optionally add a test where the hold is lost after `generate`
  returned.

#### M5. Lines over 120 characters (Global Constraints)
- **Where:** Edit 55's docstring line is about 195 characters, and it still says "stopped at the manifest table"
  though the stop is now `checkpoints.checkpoints`. Edit 42's comment is 122 characters, `nodes.insert_draft`'s SQL
  string 122, `state.HeldDraft`'s docstring 121, and `test_graph_live.py`'s `ORDER BY checkpoint_id DESC LIMIT 1`
  string 121.
- **Why the gate misses them:** ruff does not select E501, so the gate passes.
- **Fix:** wrap them, and correct Edit 55's wording.

#### M6. Revision 0015's grant statements depart from the 0011-0014 convention
- **What differs:** they are hand-rolled with verb order SELECT, INSERT, DELETE, UPDATE, and without the
  REVOKE-ALL-then-GRANT pattern of `privileges.grant_statements` (which is fixed to schema `app`).
- **Effect:** none functionally, since the schema is new and no default privileges exist.
- **Fix:** add a one-line comment saying why there is no REVOKE (new schema, PUBLIC revoked at the schema), so a
  later reviewer does not read it as an omission.

#### M7. The `asked` cross-check loses a round after a fork
- **What happens:** suppose the resume committed AWAITING_INPUT → QUEUED and the lease was lost before the next
  checkpoint store. The fork re-runs `await_clarification`, which takes its QUEUED branch (4185-4186) without
  appending the question id. `asked` then under-counts and the warning at 4207-4208 fires spuriously.
- **Effect:** the rounds come from the database, so this is log noise only.
- **Fix:** append the latest requested id on that branch too, or note it.

### Controller's open checks

1. **In-memory hold (2a, 2b).** On the second model call, see M4. The hold is cleared in effect on every exit:
   `Context` is per graph run and discarded when `_drive` returns. `held.draft` is cleared explicitly on the success
   paths and `held.bundle` never is, which is harmless. **Holds**, with M4.
2. **`publish_state`'s second exit.** It cannot loop: LOST sends the run through retrieve and draft to
   `publish_state` again, which settles it. A second crash restarts from the stored id, `RECURSION_LIMIT=30` bounds
   any spin, and GraphRecursionError becomes FAILED for a mid-run state in `_drive`. The decision is read from the
   table (`after_publish` calls `route_graph`), but the target list `[END, "route_request"]` is a literal; that is
   acceptable. ARCHITECTURE §3's diagram is updated (Edit 84; the anchors and node letters C, A, X, O, P exist).
   **Holds.**
3. **Erratum 129's chain.** AWAITING_INPUT → QUEUED → RETRIEVING → FAILED is legal under SA:451 as written (each
   step is a `transition_run` target; `states.py` rows and 0003 `transition_run`). The erratum need not amend a
   line. **Holds.**
4. **Erratum 127.** It changes only `JOB_RULES[RESUME_INPUT].run_states`, which `persistence.allowed_tool` checks
   inside mcp-read for the read handles of `resume_input` jobs. The api and the sweeper hold no handles, so nothing
   widens for them. 127 names SA:343. **Holds.**
5. **`checkpoint_migrations` in the installed 3.1.2.** It is touched only inside `setup()`: aio.py:90-117
   (SELECT/INSERT at 100 and 114), `__init__.py`:95 and 108, and shallow.py in its setups. aput, aput_writes,
   aget_tuple and alist never touch it. **Holds.**
6. **Reviewer-wait interrupt.** Its value is `str(active_proposal_id)` only (4273; unit test 2865). The verification
   of the resume value is missing: see M1.
7. **REJECTED decision.** See M2.
8. **Execute with a missing checkpoint.** It starts a new graph run: `load_run` → `facts()` (a full reread), then
   `execute_approved_proposal` rereads under lock and needs APPROVED or EXECUTING, and mcp-write's grant is the final
   gate. It cannot execute what the database does not hold as APPROVED. **Holds.** The neighbouring case of a known
   but stale stored checkpoint fails: see I1.
9. **No `AsyncConnectionPool`.** No pool appears in the plan's worker code (grep: no `AsyncConnectionPool`,
   `psycopg_pool` or `ConnectionPool`). **Holds.**
10. **mcp-write debt line.** It is present in Task 1's list (334-335, "→ T21"). **Holds.**

### Other checks that held
- **Authority and text.**
  - State is ids and enums only. Interrupts carry ids.
  - The worker never inserts `messages`; it only reads them under RLS, and its SELECT grants on messages, events,
    decisions, execution_grant and action_attempt_state exist.
  - `checkpoint_id` is the worker's column grant.
  - The question rides in `transition_run`'s detail, emitted as `clarification.requested` by 0003. The answer rides
    in `explanation.ready` with `source=model_summary` (erratum 124).
  - The permit is released by its context manager on every path, and the lease by `handle`'s final unit or the
    re-queue.
  - A stale or foreign clarification reply fails closed: the event must be the newest `clarification.received` and
    answer the newest `clarification.requested`.
- **Idempotency on replay.** QUEUED → RETRIEVING only from QUEUED. The manifest is guarded by
  `run_manifest_exists`. Freeze, answer and abstain are guarded by the state reread under lock. A replayed
  `await_clarification` in AWAITING_INPUT only re-interrupts.
- **LangGraph claims, verified in the installed sources.**
  - `is_replaying` at `_loop.py:330`, and `_reapplies_pending_writes = not is_replaying` at :764-767.
  - A `Command(resume)` on an explicit id is not time travel and does not fork (:888-925). Input None forks with
    `source: fork` (:1013-1028).
  - The non-blocking put is at :1263-1275. The sync wait after the superstep is at main.py:3525-3527.
  - The `checkpoints` event is emitted in `tick()` (:647-665) before `runner.atick` starts any task (its first
    `yield` comes before submission, `_runner.py:388`), so the store unit cannot race a node on the loop connection.
  - Metadata copies string values from `config["metadata"]` (base `__init__.py:786-804`; keys beginning `__`
    excluded), so the runtime context is never persisted.
  - The saver's MIGRATIONS (base.py:43-91) are ten statements, matching the frozen DDL after the schema prefix and
    `CONCURRENTLY` are removed.
- **Spec lines respected.** SA:137 (the third question ends INSUFFICIENT_EVIDENCE before any interrupt, counted from
  the database), SA:147, SA:153 (the intent gate in the table plus `freeze_allowed`), SA:211-214, SA:377 (the seven
  dimensions, the code rule with "all within freshness", and an answer → `answer_only` on any intent).
- **Records.** The Task 6 preconditions match the tree: T20 is PLANNED with 2 review notes; M07 is PLANNED with
  tasks [T19, T20]; M08 holds [T21, T22]; R022-R114 are NOT_IMPLEMENTED…/NOT_RUN; R122 has owner [T09]; R129's note
  ends with the asserted sentence. Counts are consistent: 26 witnesses, 30, 28 and 17 tests, and the dev arithmetic
  1629 → 1717/226, which I reproduced.
- **Live tests read line by line.**
  - `app_conn` is the superuser, so the grep and purge of `checkpoints.*` work.
  - Role and column names are right: `mcp_read`, `run_state_history.to_state/seq`, `model_permit.holder`, and
    `-infinity` for a released lease.
  - The static fixtures pass the freshness rule because it compares the tool's own instants, not the wall clock.
  - `history[3:6]` is right for the clarification path.
  - The cannot-fail case is the R108 head check (I2).

### Plan claims I disputed and could not settle
- The four new database live tests and the edited live modules were not run (no stack, by the brief). Two things are
  settled only by reading: the `pg_stat_activity` assertion's `'%%'` (with no parameters psycopg sends it literally,
  and it still matches as a LIKE pattern), and that the api role's error text is exactly "permission denied for schema
  checkpoints".
- `test_r105_walking_skeleton` against the real asset-sim relies on A17's status being `normal` or `warning` and on
  the search and status instants coming from the same database clock (Review Focus 1). That cannot be checked without
  the stack.
- `build.confirm`'s 5 s ceiling against a pipeline-mode first or fork write on a loaded machine (Review Focus 2) is
  plausible but unmeasured.

---

# Round 1 — controller rulings

## Plan Q — controller rulings on critic round 1 (report `.superpowers/planq/round1-static.md`, plan 2e2666a)

Verdict accepted: REVISE, 0 Critical, 2 Important, 7 Minor, 3 claims unsettled. Every finding is fixed in one plan
commit; nothing is parked. The writer applies the fixes to the plan, re-applies the changed blocks in a scratch
worktree, re-measures the dev counts and `verify_handoff`, and reports. One fix wave, then execution.

### Important

- **I1 (stale router dimensions; an approved run that forked from a pre-freeze checkpoint can never execute) — fix as
  the critic proposes, the first way.** `route_request` merges `await facts(ctx, run_id)` into its update on every
  hop (one unlocked SELECT; BS:305/SA:215: the router routes on authoritative dimensions only). The early returns may
  stay as they are. Add the critic's scenario as a unit test in `test_graph_flow.py` (freeze commits, `fenced` raises
  LeaseLost at the checkpoint-id store, run set APPROVED with an `approval.recorded` event, the execute job runs the
  proposal). Replace or extend `produced()` so the R129 "every produced key has a route" test either enumerates keys
  whose state comes from a reread while the other dimensions are stale, or asserts that the router rereads (a test
  that `route_request`'s update contains `facts()`' keys). Review Focus 5 and the plan's idempotency text name the
  change. Counts shift accordingly.
- **I2 (R108's synchronous-persistence half has only a kwarg spy) — add ruling 6's test.** In `test_graph_live.py`
  (Postgres saver, the real durability path): a `build_graph(saver, replace=...)` graph whose stub node, during step
  N+1, calls `aget_tuple` for the thread and asserts the step-N checkpoint and its channel values are already stored.
  Also add the in-memory unit version if it is cheap; it is not a substitute. Narrow the R108 note and STATUS to what
  each test evidences (the spy pins the kwarg; the live stub pins the behaviour). This was an unlisted departure from
  ruling 6: the plan's departure list gains no entry because the test is now in.

### Minor

- **M1 (the execute job's resume value is never verified) — verify it.** Before resuming, `handlers.execute` checks
  that the event id names an `approval.recorded` event of this run, that it is the run's latest decision event and
  that its payload's `proposal_id` equals `runs.active_proposal_id`. On a mismatch: no graph run, no run transition
  (the worker may not move an APPROVED run, SA:451), an error log with the three ids, and the job ends through the
  existing job-failure path rather than retrying forever; a debt line names recovery of such a run → T22. One unit
  test for the mismatch. Line 101 then stands as written.
- **M2 (a REJECTED decision never reaches the table's route)** — a debt line and one sentence in erratum 128: the
  thread of a rejected run ends at the reviewer wait; `publish_state` does not run for it in v1; the run's REJECTED
  state is the API's and is authoritative.
- **M3 (errata the plan should propose)** — erratum 126 gains the sentence that SA:434's "worker: all DML" excludes
  `checkpoint_migrations` (departure 10). New **erratum 130**: SA:136's RETRIEVING → AWAITING_INPUT on missing or
  ambiguous context is not taken in v1; an unknown asset ends INSUFFICIENT_EVIDENCE because the asset is fixed
  (SA:154). Next free erratum: **131**. Task 6's errata text, the debt list and the history section name 122-130.
- **M4 (second model call after a lost hold)** — debt line "→ T29" (not "recorded, no task"); erratum 128 names
  BS:554/555 (a recovery after a completed draft can exceed two generation attempts and the per-run 90 s, bounded only
  by the job's own budget); add the unit test where the hold is lost after `generate` returned and the recovered run
  drafts again (Scripted generator counts calls).
- **M5 (lines over 120 characters)** — wrap the five named lines; Edit 55's docstring says the worker stops on a
  missing `checkpoints.checkpoints`, not "the manifest table".
- **M6 (0015's grant statements)** — add the one-line comment (new schema; PUBLIC revoked at the schema; no default
  privileges to revoke; `privileges.grant_statements` is fixed to schema `app`).
- **M7 (`asked` cross-check after a fork)** — append the latest requested id on the QUEUED branch of
  `await_clarification` too (reread from the database, SA:215).

### Unsettled claims

Left to Task 5's first live run, which is where the brief put them: the `pg_stat_activity` LIKE pattern, the api
role's exact error text, A17's status against the real asset-sim and the shared database clock, and
`build.confirm`'s 5 s ceiling. Review Focus 1 and 2 already name them; the Task 5 implementer records what the first
live run shows.

### Process

- Critic slip recorded: one `uv run python -I - < /dev/null` typed into the real tree, hung on stdin, stopped, no code
  run, tree clean, HEAD unchanged. Goes to execution-facts and the history section.
- The critic applied all 102 blocks in a scratch worktree and reproduced the dev gate (`1717 passed, 226 skipped`);
  that is the first independent reproduction of the plan's counts.

---

# Controller check of the round 1 fixes (cfd37fe)

The diff 2e2666a..cfd37fe touches only the plan (433 insertions, 134 deletions; 5951 → 6250 lines). Read hunk by
hunk against the rulings:
- I1: `route_request` begins with `update = await facts(ctx, run_id)` and merges the LOST drop into it, so the
  router's seven dimensions are reread on every hop; `test_an_approved_run_resumed_from_before_its_freeze_executes`
  is the critic's scenario and `test_the_router_rereads_the_runs_dimensions` pins the reread (the ruling's second
  way). Two Plan M worker tests that replaced the fake's state function looped under the reread and now pass through
  to it; `tests/plan_m/test_worker_r029.py` joins Task 4.
- I2: `test_r108_each_step_finds_the_previous_checkpoint_stored` (live, Postgres saver): the stub at step N+1 calls
  `aget_tuple` and asserts step N's channel values and `step == 0` are already stored. No in-memory version: the
  in-memory saver writes synchronously, so it could not distinguish the durabilities — accepted. The R108 note and
  STATUS say which test evidences what.
- M1: `_approval` takes the run row, requires the latest decision event to be an `approval.recorded` with no
  `run.rejected`, and its `proposal_id` to equal `active_proposal_id`; otherwise an error with the three ids, no graph
  run, no transition. A run with no approval event at all is now also a mismatch (stricter than the ruling; accepted,
  since a job that reaches `execute` without an approval event is an inconsistency, and a debt line → T22 names the
  recovery). One unit test.
- M2 debt line and erratum 128 sentence; M3 erratum 126 names `checkpoint_migrations`, erratum 130 (SA:136) added,
  next free 131; M4 debt → T29, erratum 128 names BS:554/555, `test_a_hold_lost_after_a_completed_draft_is_drafted_
  again` (the lease is lost before the draft node's checkpoint store, so recovery resumes at the draft node and the
  route is asked twice — accepted); M5 wrapped, Edit 55's wording corrected; M6 the comment; M7 the QUEUED branch of
  `await_clarification` appends the latest requested id.
- Outside the findings: the two-crashes test's sliced assertion replaced with one over the transition list; departure
  13 and a "Round 1 changes" section added.
- Counts: `test_graph_flow.py` 21 (was 17); dev after Task 4 `1721 passed, 222 skipped`, after Task 5 `1721 passed,
  227 skipped`, both measured on a fresh worktree rebuilt from the plan's blocks; live `1927 passed, 21 skipped`
  (arithmetic); `verify_handoff` exit 0 after Tasks 5 and 6.

Accepted. Execution begins at cfd37fe.

# Plan Q inputs: T20 (LangGraph workflow with sync durability and stored checkpoint IDs) — fact sheet

Prepared 2026-10-25 on branch `plan-q` at `c96d13c` (= `plan-p`, PR #15 against `main`; the working tree was clean).
Read-only on the repository except this file. Facts only, no design. Citations: `SA:<line>` = `SPEC_AMENDMENTS.md`,
`BS:<line>` = `BUILD_SPEC.md` (line numbers as of `c96d13c`); the amendments win wherever the two conflict. Repository
files are cited as `path:line`. Nothing was run against a database, Keycloak, Ollama or any service for this sheet, no
network connection was made, no gate was re-run, and no secret, token or `.env` value was opened. One read-only helper
script (in the session scratchpad, run as `uv run python -I <path> < /dev/null`) printed the acceptance-matrix rows for
the chosen requirement ids and for keyword hits, with their line spans; every other fact is read from the files.

**Holdout custody.** No holdout case file, label or seal was opened, read, hashed or listed. Paths matching
`*holdout*`, `*seal*` or `*.sha256` skipped by name only: `evals/HOLDOUT.md` and `evals/holdout-case.schema.json`
(allowed, not needed, not opened), `scripts/seal.py` (named in the Plan P sheet; not opened). **Process slip:** most
greps carried the exclusions, but seven content searches were scoped by directory or extension without them
(`git grep … -- '*.py' ':!reference'`; `git grep … -- tests`; `git grep … -- tests scripts`; `git grep … --
tests/*.py tests/**/*.py`; `grep -rn GraphRoute --include=*.py .`; `grep -rln TRANSITIONS tests`; and one `git grep
… -- docs handoff …` that excluded `*holdout*` and `*seal*` but not `*.sha256`). Their scope could include
`scripts/seal.py` and other pattern-matching files. No output line came from a `*holdout*` or `*seal*` path; one
output line came from a `*.sha256` file, `docs/archive/REFERENCE_MANIFEST.sha256:29` (the 1.0 reference manifest's hash
of `integrations/langgraph_workflow.py`, not holdout material). Nothing in this sheet is taken from that line.

Note on line numbers: AM-10 SA:116-162 (AWAITING_INPUT → QUEUED SA:135, RETRIEVING row SA:136, DRAFTING row SA:137,
terminals SA:143, active states SA:145, clarification signal SA:147, enforcement SA:149, `state_version` SA:151,
ANSWERED path SA:153, requester fields SA:154, clock SA:157); AM-12 SA:170-218 (lease SA:173-174, fenced writes
SA:176-184, writes without a lease SA:186, lock order SA:188-191, heartbeat SA:193-199, async SA:201, permit
SA:203-205, graph SA:207, checkpoints SA:209-218); AM-14 SA:303-325; AM-15 SA:327-358 (tools SA:333, handle binding
SA:338, job types SA:340-346); AM-16 SA:360-381 (rule SA:362, readonly_answer SA:371, clarify SA:372, hint SA:375,
graph router SA:377, model router SA:379); AM-20.2 SA:406-442 (`runs` SA:415, `run_lease` SA:418, `jobs` SA:419,
`drafts` SA:421, schema `checkpoints` SA:434); AM-20.3 SA:444-490 (`transition_run` SA:451, `append_event` SA:452,
`freeze_proposal` SA:453, performers SA:476-490); AM-20.4 SA:492-506 (`drafts`/payload SA:496, `resume_input` key
SA:501); AM-20.5 SA:508-524; AM-20.7 SA:532-566 (checkpoint tables SA:559-562, IDs only SA:563); AM-30 SA:575-581;
AM-40 SA:634; AM-60 SA:690; AM-70 SA:737. BUILD_SPEC: fixed choices BS:65, BS:69-70, BS:89; flow BS:106-133;
BS:250; BS:273; §8 BS:303-342 (nodes BS:328, `await_*` BS:330, queue/lease BS:334, fence checkpoints BS:338, lost
wakeups BS:340, `workflow_version` BS:342); §11 BS:417, BS:419, BS:423; §12 BS:435; BS:516; §17 BS:549-556, BS:562,
BS:564; BS:570; BS:588; M07 BS:708, BS:718; S01/S02 BS:775-776.

---

## 1. T20 verbatim, and what touches it

### 1.1 T20 (`handoff/tasks.json:863-894`)

- **id/milestone/title:** `T20` (`:864`), `M07` (`:865`), "LangGraph workflow with sync durability and stored
  checkpoint IDs" (`:866`).
- **instructions** (`:867`, verbatim): "Nodes per AM-12 incl. the route_request graph router whose conditional edges
  are generated from the core/routing.py table; retrieval before drafting; durability=sync; runs.checkpoint_id stored
  under fence and used on resume; idempotent pre-interrupt logic; ID-only interrupts; human waits release the lease;
  ANSWERED path."
- **depends_on** (`:868-872`): `["T19", "T14", "T16"]`, all `DONE` (T19 `:851`, T14 `:654`, T16 `:765`).
- **requirement_ids** (`:873-881`): `R022`, `R038`, `R042`, `R091`, `R108`, `R114`, `R129`.
- **status** (`:882`): `"PLANNED"`. **external_approval_required** (`:889`): `false`.
- **definition_of_done** (`:883-888`, verbatim):
  1. "Trace shows MCP reads complete before drafting."
  2. "Pause/resume survives worker restart from the stored checkpoint_id; a newer stray head is ignored."
  3. "Checkpoint blobs contain no evidence or proposal text."
  4. "A test enumerates every graph-router row and asserts the node reached (R129)."
- **review_notes** (`:890-893`, verbatim):
  1. "LangGraph 1.2.14: explicit checkpoint_id => is_replaying, pending writes NOT re-applied (_loop.py:330, 766-770);
     Command(resume) keeps RESUME writes; invoke(None, checkpoint_id) forks (886-912). Store IDs from
     stream_mode='checkpoints'/aget_state, update after forks, make every node idempotent, test kill-mid-superstep and
     kill-at-interrupt, join stale in-process tasks before re-acquiring." (`:891`)
  2. "Fork writes are non-blocking (_loop.py:1262-1266) and sync durability waits only after the tick (main.py:3526):
     store only checkpoint IDs confirmed by aget_tuple; treat a missing stored ID as an error; prefer Command(resume)
     when a resume event exists; test two crashes in a row. Define revision re-entry (new thread per revision or
     explicit edges back to retrieval)." (`:892`)
  - Sources of the notes: `docs/reviews/plan-review-r3-2026-10-06.md:69` (note 1, "LangGraph 1.2.14 ✓ … `_loop.py:330,
    766-770` … `:886-912`") and `docs/reviews/plan-review-r5-2026-10-06.md:70` (note 2, "forks are conditional ✓
    (`:920-926`) … Revision re-entry into the graph needs definition."). The line references are to the langgraph
    1.2.14 package source, which is not in this repository and not in `uv.lock` (§3.6); it was not downloaded for
    this sheet.
- `handoff/BUILD_BACKLOG.md:125` repeats the task unchecked; `:126-127` repeat both notes as "*Review note:*".
- Milestone M07 (`tasks.json:87-96`): "LangChain draft node and LangGraph workflow", `task_ids` `["T19", "T20"]`,
  `"status": "PLANNED"`. `tasks.json:3` `current_milestone` is `"M07"`.
- `tasks.json:4` status vocabulary: "PLANNED, DONE (all steps done and reviewed), DONE_PENDING_OWNER (agent steps done;
  an owner-only step remains, named in review_notes). A proposed erratum awaiting the owner's decision does not change
  a task's status".

### 1.2 Acceptance rows owned by T20 (`handoff/acceptance-matrix.json`)

All `blocking_for_v1: true`. Fields as in the matrix (`implementation_status` / `evidence_status`):

- **R022 (:396-409)** milestone `M07`, category `workflow`, "Human waits release workers and transactions";
  `NOT_IMPLEMENTED_OR_NOT_TARGET_VERIFIED` / `NOT_RUN`; expected (verbatim): "Pause for review; no active worker
  lease/long DB transaction/model budget consumed."; owners `["T20"]`; suggested test
  `tests/acceptance/test_r022_human_waits_release_workers_and_transactions.py`. `ACCEPTANCE.md:28` lists it as
  "R022 / M04" (the 1.0 snapshot).
- **R038 (:729-742)** `M07`, `workflow`, "Evidence retrieval precedes final drafting"; `NOT_IMPLEMENTED…` /
  `NOT_RUN`; expected: "Trace order and input bundle show MCP read results before final model proposal."; owners
  `["T20"]`; `…/test_r038_evidence_retrieval_precedes_final_drafting.py`. `ACCEPTANCE.md:44` (M07).
- **R042 (:809-822)** `M07`, `workflow`, "Actual checkpoint pause/resume survives restart"; `NOT_IMPLEMENTED…` /
  `NOT_RUN`; expected: "Restart graph process during clarification/review and resume from committed event under same
  run."; owners `["T20"]`; `…/test_r042_actual_checkpoint_pause_resume_survives_restart.py`. `ACCEPTANCE.md:48` (M07).
- **R091 (:1600-1614)** `M07`, `privacy`, "Checkpoints and interrupts carry identifiers only"; `NOT_IMPLEMENTED…` /
  `NOT_RUN`; expected: "Grep of checkpoint blobs after pause finds no evidence or proposal text."; owners `["T20"]`;
  source `SPEC_AMENDMENTS.md`; `…/test_r091_checkpoints_and_interrupts_carry_identifiers_onl.py`.
- **R108 (:1922-1936)** `M07`, `workflow`, "Graphs persist synchronously and resume from the stored checkpoint";
  `NOT_IMPLEMENTED…` / `NOT_RUN`; expected: "durability=sync asserted; resume uses runs.checkpoint_id; a stray newer
  head is ignored."; owners `["T20"]`; source `SPEC_AMENDMENTS.md`;
  `…/test_r108_graphs_persist_synchronously_and_resume_from_the.py`.
- **R114 (:2027-2041)** `M07`, `workflow`, "Read-only answers complete as ANSWERED without proposals";
  `NOT_IMPLEMENTED…` / `NOT_RUN`; expected (verbatim): "Answer path cites evidence, creates no proposal or grant, ends
  ANSWERED."; owners `["T20"]`; source `SPEC_AMENDMENTS.md`;
  `…/test_r114_read_only_answers_complete_as_answered_without_p.py`.
- **R129 (:2294-2315)** milestone `M03`, `routing`, "Every route is enumerable and unroutable input never starts work";
  `IMPLEMENTED_LOCALLY_VERIFIED` / `RECORDED_LOCALLY_LIVE`; expected (verbatim): "Admission router: each of the six
  routes tested; conflicting text/fields yields a stored clarification and no job; unroutable kinds 422. Graph
  router: a test walks every row of the route table and asserts the node reached; a model hint can only produce
  clarify."; evidence `tests/e2e/test_admission_live.py`, `reports/admission/t12-admission.txt`,
  `tests/plan_g/test_routing_admission.py`, `tests/plan_g/test_api_admission.py`; owners `["T12", "T20"]`; note "Plan
  G (T12): the admission router half; the graph router's table and its walk land with T20."
- R081-R131 are matrix-only (`ACCEPTANCE.md:3`), so R091, R108, R114 and R129 have no `ACCEPTANCE.md` line.
- Matrix note (`acceptance-matrix.json:3`): `RECORDED_LOCALLY` = the evidence-path tests pass in `scripts/check.py` and
  CI; `RECORDED_LOCALLY_LIVE` = passes against the running dev profile with `OPS_LIVE=1`.

### 1.3 Other rows naming the graph, checkpoints, interrupts, durability, resume, ANSWERED or lease release

- **R021 (:381-394)** `M15`, `blocking_for_v1: false`, T38: "Stale worker cannot mutate authoritative checkpoints";
  expected "Lose lease during graph work; old saver write is rejected inside checkpoint transaction."
- **R023 (:411-424)** `M08`, T21: "Reply/approval wakeups cannot be lost"; expected "Inject crash between
  decision/event/checkpoint/job acknowledgement; sweeper resumes exactly the accepted event."
- **R028 (:516-538)** T16, `RECORDED_LOCALLY_LIVE`; expected ends "(Locally verified at the tool boundary, where
  nothing forbidden reaches the caller; the model-facing path for asset data arrives with T20, because the worker does
  not yet pass asset reads to the model.)"; note ends "a read-path freshness bound is T20's, subject to the owner's
  decision on erratum 105."
- **R033 (:625-645)** T17, `RECORDED_LOCALLY_LIVE`; note: "R033 is met subject to the owner's decision on erratum 102:
  the other 5/20 stay open: SA:377 as written counts any returned effective chunk as sufficient and would not abstain
  on them, so T20 must add a relevance criterion beyond it (for example a score or label-based sufficiency rule)."
- **R035 (:671-684)** T26: "Revoke source after draft; caches/checkpoints/summary/events/citation viewer do not
  re-expose it."
- **R058 (:1054-1067)** T28: "Trace API/job/graph/LangChain/MCP/destination/reconcile; …". **R060 (:1084-1097)** T28:
  "No run IDs as metric labels; active compute and human waits measured separately."
- **R065 (:1159-1172)** T30: "Stop model; API does not restart endlessly. Terminate worker; no new leases and safe
  recovery."
- **R087 (:1519-1538)** T13, `RECORDED_LOCALLY_LIVE`: "Resume-job vs original-job race: only the current run fence
  writes."; note "a resume_input job of a run whose investigate job holds the lease is deferred behind the lease, then
  takes fence + 1; only it writes and only it closes its job."
- **R088 (:1540-1561)** T13, `RECORDED_LOCALLY_LIVE`: "Blocked loop and >30 s fake drafter keep the lease; forced
  renewal failure cancels the call and revokes handles."
- **R107 (:1896-1920)** T13, `RECORDED_LOCALLY_LIVE`: fenced writes lock the lease row and follow one lock order;
  "the published order is core/locking.py with a test over every documented transaction."
- **R122 (:2163-2178)** `M02`, owners `["T09"]`, `NOT_IMPLEMENTED…` / `NOT_RUN`: "Checkpoint tables are reachable
  only by the worker"; expected "api role: permission denied on schema checkpoints; worker DML only; migrator ran
  setup()."; note "deferred to T20: langgraph-checkpoint-postgres is not locked (Plan E ruling 2)".
- Development cards (`evals/handoff-development/scenarios.jsonl`): DEV-001 (`:1`, R037/R038/R043/R047, expected
  `SUCCEEDED`); DEV-002 `happy-beta` (`:2`, prompt "Investigate B22 over the last 24 hours.", R028/R038, expected
  **`ANSWERED`**, oracle "Report no provided warning evidence requiring an incident; do not invent an alert."); DEV-003
  `missing-window` (`:3`, "Investigate A17.", R018/R042, expected `AWAITING_APPROVAL`, oracle "Persist question and
  fixed interval, retrieve before drafting, no write before decision."); DEV-004 (`:4`, expected `AWAITING_INPUT`);
  DEV-013 `parallel-workers` (`:13`, R020/R021/R047, "Stale owner cannot commit app/checkpoint; one destination
  action."; deferred to M15 by SA:649); DEV-021 (`:21`, R035/R054, "No revoked text from cached
  summary/events/checkpoint/viewer.").

### 1.4 Debts other tasks pushed to T20

Code markers (`git grep "TODO(T20)"`, Python): `worker/src/ops_worker/handlers.py:52` (`INTERRUPTED = "interrupted; the
run was not resumed"  # TODO(T20): resume from the checkpoint instead`), `handlers.py:219` (`# TODO(T20): the graph
router sends an answer to ANSWERED and a question to AWAITING_INPUT (SA:137, SA:153).`), `worker/src/ops_worker/mcp.py:182`
(`# TODO(T20): the write tools (mcp-write) still get only T47's check: no discovery and no result-schema check.`).
Other code text naming T20: `handlers.py:7` ("an answer or a clarifying question → FAILED until T20 routes them"),
`handlers.py:15` ("No LangGraph (→ T20)."), `core/src/ops_core/routing.py:5` ("The graph table arrives with T20"),
`routing.py:41` (`GraphRoute` "table owned by T20"), `mcp-read/src/ops_mcp_read/assets.py:7-8` ("honouring `retryable`
is T20's"), `sweeper/src/ops_sweeper/wakeups.py:7` ("AWAITING_INPUT is T20's"), `scripts/draft_evidence.py:14`,
`:243` ("the worker passes no asset data to the model until T20"), `scripts/retrieval_baseline.py:328`,
`scripts/retrieval_comparison.py:485` (T20's relevance criterion). Test text: `tests/plan_h/test_worker_units.py:218`
(`resume_input` "not handled yet (T20)"), `:290`; `tests/plan_i/test_wakeups.py:5`, `:69`; `tests/e2e/test_wakeups_live.py:10`,
`:110`; `tests/e2e/test_admission_live.py:395`; `tests/e2e/test_mcp_write_t47_live.py:233`;
`tests/plan_p/test_investigate_drafting.py:7`.

Debt lines in `SESSION_STATE.md`, by plan (verbatim where quoted):

- **Walking skeleton (T08)** `:1132`: "fake model → T19; no LangGraph or durability → T20."
- **Plan E (T09/T10)** `:1156`: "schema `checkpoints` and R122 are deferred: `langgraph-checkpoint-postgres` is not
  locked → T20;" (also `:234`, `tasks.json:516`, `STATUS.md:120`).
- **Plan G (T12)** `:1188-1191`: "the worker finishes a `resume_input` job unhandled and ends an `answer_only` run
  FAILED (no ANSWERED path yet), so the clarification reply and the read-only admission are proved at the API boundary
  only → T20 (R042, R114); nothing in the worker asks for clarification yet, so the live test stages `AWAITING_INPUT`
  through the worker role's `transition_run` → T20;" (also `:349-350`, `tasks.json:604`).
- **Plan H (T13)** `:1222-1224`: "an investigate run interrupted in RETRIEVING or DRAFTING (a lost lease, a crash, a
  lock timeout) is failed by its job's next owner (`interrupted; the run was not resumed`) instead of resumed from
  where it stopped → T20 (the graph's node resume);" `:1227`: "checkpoints are untouched (`runs.checkpoint_id` under
  the fence) → T20; fenced `put`/`put_writes` (R021) → T38;" Erratum 57 (`:415-417`): "the job's next owner fails a run
  it finds in RETRIEVING or DRAFTING (resuming it is T20's)." Also `:436-437`, `tasks.json:638`,
  `docs/reviews/plan-h-final-review-2026-10-15.md:283-284`.
- **Plan I (T14)** `:1259-1265`: "the worker still finishes a `resume_input` job it does not handle, and the wake-up
  sweep does not look at AWAITING_INPUT runs (no handler consumes the reply yet) → T20; … the wake-up sweep re-arms
  the `investigate` job of a run that sits in QUEUED with every investigate job done; a run that T20's `resume_input`
  handler moves back to QUEUED would meet the same predicate, so T20 decides whether that is its wake-up → T20;"
  (also `tasks.json:664`).
- **Plan J (T15)** `:1314-1316`: "it does not tell a 401 from other transport failures (both become "retrieval failed"
  or a re-queue) → T20; it holds no `resume_input` handle → T20;" (also `tasks.json:697`).
- **Plan L (T17)** `:1375-1376`: "the model-side proof that the injected documents grant nothing (R036), and detecting
  the conflicting pair and abstaining → T19/T20 (rulings 13 and 14);". Erratum 102 (`:846-850`): "T20 must add a
  relevance criterion beyond it (for example a score or label-based sufficiency rule)." (also `tasks.json:748`).
- **Plan M (T16)** `:1392-1393`: "the worker's calls to `get_asset_status` and `get_recent_alerts` and their results in
  the draft and the evidence bundle (BS:419), and SA:377's evidence-sufficiency rule → T20 (rulings 16 and 17);"
  `:1396-1398`: "the worker's write calls (`create_incident` at mcp-write) keep T47's result check: no tool discovery
  and no result-schema check … → T20, which builds AM-12's `execute_approved_proposal (mcp-write)` node (SA:207) and
  every route of R129;" `:1417-1420`: read-path freshness bound → T20 subject to erratum 105; `:1421-1423`: "a retryable
  read failure ends the run … → T20 (honour `retryable` from a read with a bounded re-queue of the investigate job);"
  (also `tasks.json:784`, `docs/reviews/plan-review-m-2026-10-18.md:329-338` "So T20 is the first task to drive
  mcp-write from the graph, and T20 is the right owner.").
- **Plan N (T18)** `:1429-1431`: "choosing the mode per run and recording it in the run manifest → T20 (the graph's
  retrieve node) and T25 …"; `:1433-1434`: "a relevance or abstention rule beyond them → T20 (erratum 102)" (also
  `tasks.json:806`).
- **Plan O (T23)** `:1480-1482`: a lexical normalisation change "is a later revision under T20 (the retrieve node and its
  relevance rule), never T23" (only on a total loss on the decimal pairs; `tasks.json:993`).
- **Plan P (T19)** `:1502-1506`: "an `answer` draft and an `abstain` draft with a question end the run FAILED with a
  templated message; the graph router that sends them to ANSWERED and AWAITING_INPUT, and the `resume_input` job, →
  T20 (SA:137, SA:153; R114, R129) (Plan P ruling 11); the payload does not tell the model that an `answer_only` run may
  not propose, so such a run spends its first attempt on a refused proposal and relies on the repair's feedback;
  stating it in the payload → T20 (round 1, M10);" `:1515-1516`: "the worker sends the model the request, the asset,
  the interval and the retrieved procedure sections only; the asset status and alert records reach the model with
  T20's asset reads (BS:419; R028's note, R038) (ruling 1);" `:1517-1518`: retrieval mode per run "→ T25 (Plan N ruling
  16; `handlers.py`'s `TODO(T25)`)". (`handlers.py:58` carries `TODO(T25)`; the Plan P final review M5,
  `docs/reviews/plan-p-final-review-2026-10-24.md:247-248`, noted the marker and the Plan N line "→ T20 and T25"
  disagree.) T19's review note (`tasks.json:860`): "Deferred: answers and clarifications -> T20".
- Plan P final review (`plan-p-final-review-2026-10-24.md:298-300`): "On the real route an `answer_only` run cannot end
  well before T20: a proposal is refused (then repaired), an answer or question ends FAILED/NOT_ROUTED. On the fake
  route every `answer_only` run ends "drafting failed" with a logged traceback (`freeze_allowed`)".

### 1.5 Tasks that consume T20, and what they expect

- **T21** (`tasks.json:896-935`, depends `T20`, `T11`): "Per-revision proposal IDs; expected_payload_sha256; first
  decision wins; author-set independence; expiry to BLOCKED_REVIEW; manual-proposal API; feedback endpoint;
  grant_execution final gate …" (`:899`). DoD 3 (`:924`): "Lost-wakeup crash between decision commit and processing
  recovered by the sweeper." Owns R023 (decision/event/checkpoint/job crash) and R057 (manual path). Note `:929`:
  "Revision from BLOCKED_REVIEW requires a free conversation slot (SLOT_OCCUPIED 409)."
- **T38** (`tasks.json:1304-1319`, M15, depends `T20`): "BaseCheckpointSaver subclass checking the run fence inside
  put/put_writes; enable multiple worker replicas; DEV-013 card." (`:1307`); DoD "Stale worker cannot append a
  checkpoint or pending write after lease loss." (`:1316`); R021.
- **T22** (`:937`, depends `T21`, `T47`): recover jobs, reconciliation, AM-13's timeout path (the `recover` and
  `reconcile_outcome` side of the graph's `recover` route).
- **T25** (`:1022`, depends T22, T18, T23): AM-50 conditions; condition C is "orchestrated" (SA:660); note `:1047`
  "Reads each run's manifest … conditions B and C must show identical model_route."
- **T26** (`:1052`): note `:1075` "Include ANSWERED ('answered, no action'), CANCELLED and ABANDONED_UNVERIFIED in the
  state views"; SA:634 "ANSWERED is shown as a completed conversation answer within state 6's view, labelled
  "answered (no action)"." Owns R035.
- **T28** (`:1101`): OTel spans across "graph nodes" (BS:570); R058, R060 ("human waits measured separately").
- **T29** (`:1121`): budgets; the human-wait exclusion (BS:556) is T29's per Plan H's debt (`SESSION_STATE.md:1211-1212`).
- **T30** (`:1141`): "docker-kill recovery demo"; SIGTERM drain (`worker/src/ops_worker/main.py:201` `TODO(T30)`).
- **T36** (`:1270-1285`, M15): "Route paused runs across a workflow_version bump; rollback test."; DoD "Paused run
  resumes correctly after upgrade and after rollback." (R069).
- T24 (scenario cards after T22), T33 (demos) depend on T20 transitively. Critical path recorded in
  `SESSION_STATE.md:108`: "T01→T04→T05→T08→T09→T13→T15→T16→T20→T21→T22→T26→T27→T33→T34".

---

## 2. Spec passages that bind T20

### 2.1 AM-12: the graph (SA:207) and the checkpoints (SA:209-218)

- SA:207 (verbatim): "**The graph (orchestrator):** one explicit LangGraph graph with nodes `load_run`,
  `route_request` (the graph router, AM-16), `await_clarification`, `retrieve_evidence` (mcp-read),
  `draft_with_langchain`, `validate_and_freeze` (`freeze_proposal`), `await_independent_decision`,
  `execute_approved_proposal` (mcp-write), `reconcile_outcome`, `publish_state`. Conditional edges come only from the
  route table in `core/`. There is no free-running think→tool→act loop; the model never sees a tool.
  `docs/ARCHITECTURE.md` §3 is the reader's map."
- SA:210: "Invoke graphs with `durability="sync"`. The LangGraph default `"async"` persists while the next step runs."
- SA:211: "**Stored checkpoint ID.** After each superstep, the worker stores the accepted `checkpoint_id` in
  `runs.checkpoint_id` under the fence. It reads that ID from `stream_mode="checkpoints"` (or `aget_state` after the
  step). At an interrupt, the stored ID is the checkpoint holding the interrupt's pending write (R108)."
- SA:212-215: "**How to resume** (verified against langgraph 1.2.14 `pregel/_loop.py`): *Human resume:*
  `Command(resume=<event_id>)` with the stored `checkpoint_id`. This keeps RESUME writes and does not fork. *Crash
  recovery:* `invoke(None)` with the stored `checkpoint_id` is treated as time travel and **forks**. The worker
  immediately stores the forked checkpoint's ID as the new accepted ID. With an explicit `checkpoint_id`, LangGraph
  re-runs pending tasks rather than re-applying their writes (`_reapplies_pending_writes = not is_replaying`). So
  **every node** (not only nodes before an interrupt) must be idempotent and must reread authoritative application
  state."
- SA:216: "Nodes re-execute from the start on resume." SA:217: "**V1 runs one worker replica.** Fencing still protects
  application writes, and the stored checkpoint ID protects the head." SA:218: "R021 (fencing `put`/`put_writes`
  themselves, enabling multi-replica) stays open in M15."
- SA:201: "**Async only:** use `AsyncPostgresSaver`, `ChatOllama.ainvoke` and async MCP/HTTP clients. No synchronous
  I/O on the event loop."
- SA:28 (1.3 changes): "also corrected: the LangGraph resume rules (AM-12)".
- ADR-0002 (`docs/adr/ADR-0002-v1-scope-cut.md:23`): "Fencing LangGraph checkpoint writes needs a custom
  `BaseCheckpointSaver`. The stock `PostgresSaver` writes in sealed transactions with no hook. A stale worker can
  append a newer checkpoint and overwrite pending writes. LangGraph also persists checkpoints **asynchronously by
  default**." Decision 5 (`:41-45`): "One worker replica in v1. Graphs run with `durability="sync"`. The accepted
  `checkpoint_id` is stored on the run under the fence, and resumes use it explicitly. …"
- BUILD_SPEC §8 (superseded where AM-12 differs): BS:305 "Use application state as the authority. LangGraph checkpoint
  state coordinates computation but cannot override approval, access, or destination truth. Persist IDs and evidence
  references preferentially; do not serialize credentials into graph state." BS:328 lists the 1.0 nodes "`load_run`,
  `resolve_context`, `await_clarification`, `retrieve_evidence`, `draft_with_langchain`, `validate_and_freeze`,
  `await_independent_decision`, `execute_approved_proposal`, `reconcile_outcome`, `publish_state`" (AM-12 replaces
  `resolve_context` with `route_request`; ADR-0003:9 calls the `resolve_context` node implicit routing). BS:330 (verbatim):
  "`await_*` nodes first inspect current authoritative state, then interrupt if still waiting. Resume payloads carry
  only persisted event identifiers; reread the decision rather than trusting `{approved:true}`. LangGraph documents
  that an interrupted node restarts when resumed. Side effects before interruption must therefore be absent or
  idempotent. [S02]" BS:334: "… Never keep a transaction open through inference or a human wait." BS:338 (fence
  checkpoint writes; superseded for v1 by SA:46 and SA:217-218). BS:340 (verbatim): "Avoid lost wakeups: user
  replies/approvals commit with a unique resume job. Mark their consumption only after processing reaches a durable
  acknowledged state. A sweeper compares pending user events, jobs, checkpoints and authoritative run state, and
  re-enqueues a deduplicated wake-up if a crash occurred between them. Replayed nodes reread current state and cannot
  re-freeze a different approved payload." BS:342: "Pin `workflow_version` per run. A v2 worker must not reinterpret a
  paused v1 run's state or approval. …"
- BS:65 "Explicit LangGraph graph, durable PostgreSQL checkpoints."; BS:69 "PostgreSQL for app data, jobs,
  checkpoints, …"; BS:70 "psycopg for required PostgreSQL/checkpointer work." BS:89 "Default to the official MCP client
  … The explicit graph calls LangChain for drafting and MCP for tools." BS:435 "The final drafting node runs after MCP
  retrieval. … LangGraph calls that interface; LangChain is neither a separate service nor the authority for
  execution." BS:516 "Do not stream raw graph dictionaries, internal service headers or private reasoning."
- AM-70 (SA:737): do not port "full proposal text in `interrupt()` (`integrations/langgraph_workflow.py:38`)".
- M07 exit (BS:708): "Wire explicit graph, ChatOllama, schemas, bounded repair, durable clarification | Actual model
  generation evidence and persistent pause/resume". BS:718: "M07 can develop model and graph pieces using controlled
  fakes while prior infrastructure tasks finish, but its exit cannot pass without actual required integration."

### 2.2 AM-16: the graph router (SA:377) and its neighbours

- SA:362: "Routing is explicit, enumerable and deterministic-first. Model output may hint at a route; it never selects
  one. An input the router cannot classify becomes a clarification or a 422 and never starts work (R129)."
- SA:377 (verbatim): "**Graph router** (`route_request` node in the orchestrator): a route table in `core/routing.py`
  maps `(run state, runs.intent, context resolved?, evidence sufficient?, validated draft kind, decision present?,
  attempt state)` to exactly one of `clarify`, `retrieve`, `draft`, `answer_only`, `abstain`, `freeze`,
  `await_decision`, `execute`, `recover`, `publish`. Conditional edges are generated from that table; a test enumerates
  every row and asserts the node reached (R129). "Evidence sufficient?" is a code rule (at least one permitted status
  observation and at least one effective procedure chunk, all within freshness), never a model judgement; "validated
  draft kind" is the draft **after** structural validation, and the only route it can select is
  `abstain`/`clarify`/`answer_only` versus `freeze`, with `freeze` additionally gated by `runs.intent`."
- SA:371 (`readonly_answer`): "`create_run(intent='answer_only', …)`; the graph can end ANSWERED; `freeze_proposal`
  refuses runs with this intent".
- SA:690 (AM-60 1.3.4): "T12 implements the admission router (R129); T20 the graph router node (R129); T19 the model
  router and run-manifest recording (R130)."
- ADR-0003 (`docs/adr/ADR-0003-routers-and-read-write-mcp-split.md:15`): "a **graph router** node (`route_request`) in
  the orchestrator whose conditional edges come only from a route table in `core/`".
- `docs/ARCHITECTURE.md:102-104` (Router table): the graph router's input "run state, `runs.intent`, resolved context,
  evidence sufficiency (a code rule), the validated draft kind"; rule "A route table in `core/routing.py`; conditional
  edges only from that table; the model's output can only choose between abstaining and drafting, and `freeze` is
  additionally gated by the requester's intent".
- `docs/ARCHITECTURE.md:123-144` (§3 "The graph"): a Mermaid diagram with `load_run → route_request` and edges
  `clarify → await_clarification` ("interrupt: ends here, resumed by a resume_input job"), `retrieve →
  retrieve_evidence`, `draft → draft_with_langchain`, `answer_only / abstain → publish_state`, `freeze →
  validate_and_freeze`, `await_decision → await_independent_decision` ("interrupt: ends here, resumed by an execute
  job"), `execute → execute_approved_proposal`, `recover → reconcile_outcome`, `publish → publish_state`; `:144`
  "Every node returns to `route_request`, and every labelled edge is one row of the AM-16 route table (ten routes). The
  two interrupt nodes end the graph run; a committed human event and its wake-up job start a new run of the graph from
  the stored checkpoint. Nodes are deterministic Python; only `draft_with_langchain` calls the model, and only
  `retrieve_evidence`, `execute_approved_proposal` and `reconcile_outcome` call MCP servers." `:148-151` properties
  (R038, R022/R023/R042, R108, R091). `:397-406` "Where the code will live (not yet written)": "`worker/graph/` | the
  orchestrator's nodes and edges".

### 2.3 The run state machine (AM-10, AM-20.3)

- SA:135: "AWAITING_INPUT | → QUEUED by the worker's `resume_input` job through `transition_run`, after the
  clarification event is committed". SA:136: "RETRIEVING | → AWAITING_INPUT when required context is missing or
  ambiguous". SA:137: "DRAFTING | → AWAITING_INPUT on `kind=abstain` with a question, at most 2 clarification rounds;
  on a third round → INSUFFICIENT_EVIDENCE; **→ BLOCKED_REVIEW** on asset-guard refusal at freeze …".
- SA:143 terminals: "REJECTED, CANCELLED, ANSWERED, INSUFFICIENT_EVIDENCE, SUCCEEDED, FAILED, ABANDONED_UNVERIFIED".
  SA:145 active (slot-holding) states: "QUEUED, AWAITING_INPUT, RETRIEVING, DRAFTING, AWAITING_APPROVAL, APPROVED,
  EXECUTING, OUTCOME_UNKNOWN".
- SA:147: "**Clarification signal:** a draft asks for clarification with `kind=abstain` **plus** a non-empty `question`
  (AM-80). Without `question`, abstain means INSUFFICIENT_EVIDENCE".
- SA:149: "the transition table is data in `core/`, and a single function enforces it (R082)." SA:151: "`state_version`
  increases **only on state transitions**."
- SA:153 (verbatim): "**The ANSWERED path** (read-only answer, no proposal) has its own test (R114). It is selected by
  `runs.intent = 'answer_only'`, set by the admission router; `freeze_proposal` refuses such runs, so a read-only run
  can never produce a proposal [R7-S2]."
- SA:154: "`intent ∈ {investigate, answer_only}` and optional `supersedes_run_id` are written only by
  `create_run`/`create_revision` … Model output is never a source for either".
- SA:451 `transition_run` callers: "`worker` only. Allowed targets: QUEUED → RETRIEVING; RETRIEVING → DRAFTING /
  AWAITING_INPUT / INSUFFICIENT_EVIDENCE / FAILED; DRAFTING → AWAITING_INPUT / ANSWERED / INSUFFICIENT_EVIDENCE /
  FAILED; AWAITING_INPUT → QUEUED. **Never** any post-grant state and never SUCCEEDED"; emits "the matching `run.*`
  event via `append_event`".
- SA:452 `append_event`: "**Refuses** `action.*`, `run.*` and `review.*` types from these callers; … `worker` may pass
  `source=model_summary` only for `explanation.ready`".
- SA:453 `freeze_proposal(run_id, draft_id, payload)`: recomputes the hash against `drafts.draft_sha256`; "Refuses when
  `runs.intent = 'answer_only'` or when the draft carries `supersedes_run_id`; … inserts the immutable `proposals` row
  with `revision = max+1`; … transition DRAFTING → AWAITING_APPROVAL, or → BLOCKED_REVIEW on guard refusal".
- SA:481 performers: "QUEUED → RETRIEVING → DRAFTING → AWAITING_INPUT / ANSWERED / INSUFFICIENT_EVIDENCE / FAILED;
  AWAITING_INPUT → QUEUED | `transition_run` called by `worker` (pre-grant states only)".
- BS:313-316 (1.0): "QUEUED | AWAITING_INPUT if context is missing; …", "AWAITING_INPUT | QUEUED after stored valid
  reply; CANCELLED; remains paused for invalid/stale reply", "DRAFTING | … ANSWERED for read-only answer; …". BS:324:
  "ANSWERED means a read-only response completed, not that an incident exists." Contract erratum 4
  (`SESSION_STATE.md:180`): "BUILD_SPEC §8 `QUEUED → AWAITING_INPUT` is superseded: missing context is detected in
  RETRIEVING (AM-10), and `transition_run` allows only `QUEUED → RETRIEVING`."

### 2.4 Lease, fence and lock order (AM-12)

- SA:173: "`run_lease(run_id PK, owner, lease_until, fence bigint)`. Jobs are wake-ups only." SA:174: acquisition
  `SELECT … FOR UPDATE`, check expiry, `fence := fence + 1`.
- SA:176-184: every worker or MCP mutation for a run first executes `SELECT 1 FROM run_lease WHERE run_id = :r AND fence
  = :f AND lease_until > app.current_time() FOR SHARE`; "A missing row aborts the transaction."
- SA:186: "**Writes without a lease:** API and sweeper mutations (decision, cancel, revision, expiry) hold no lease."
- SA:188 lock order: "`asset guard advisory lock → run_lease → runs → messages → proposals → decisions → memberships →
  execution_grant → action_attempt → operator_resolutions → events → outbox`." SA:191: "Any transaction that will write
  `run_lease` takes `FOR UPDATE` from the start; it never upgrades from `FOR SHARE`."
- SA:193-199 heartbeat: dedicated thread, own connection, renew every 10 s, lease 30 s; stop starting effects at
  `lease_until − 5 s`; on renewal failure cancel in-flight model and tool calls, revoke handles, exit the run.
- BS:556: "Human wait | Does not consume active compute budget or hold a worker/DB transaction". BS:555: "Active compute
  duration | 90 seconds total; each model attempt max 60 seconds clipped to remaining budget".

### 2.5 The checkpointer and its storage

- SA:434 (AM-20.2 grant table): "schema `checkpoints` | — (api) | all DML (worker) | — | — | —".
- SA:534 (AM-20.7 summary): "**checkpoint tables** in schema `checkpoints` with `worker`-only DML (R122); **graph state
  is IDs only** (R091)".
- SA:559-562 (verbatim): "7. **Checkpoint tables.** `migrator` runs `PostgresSaver.setup()` with `autocommit=True`,
  `row_factory=dict_row` and `options=-c search_path=checkpoints` (the saver has no schema parameter). `worker` gets DML
  only on schema `checkpoints`, with `search_path=checkpoints,pg_temp` on its checkpoint connection. `api` gets
  permission denied (R122)."
- SA:510 lists the RLS tenant tables (no `checkpoints` table among them); SA:523 lists the no-RLS tables (`run_directory`,
  `invocation_context`, `run_lease`, `sessions`, `idempotency_request`, `operator_resolutions`, `model_permit`,
  `tenants`, `app.test_clock`); neither list names schema `checkpoints`.
- BS:250: "Checkpointer tables require their own access model; third-party table ownership does not inherit app-table
  policies. Restrict raw checkpoint access to workflow internals."
- SA:106 / SA:395: `migrator` is "DDL and data migrations only … never used at runtime". Fact of the tree: `migrator`
  is created `NOLOGIN` (`scripts/skeleton.py:71`) and Alembic runs as the Compose superuser (Plan E debt
  `SESSION_STATE.md:1155` "`migrator` holds no login: Alembic runs as the Compose superuser and transfers ownership
  explicitly → T30").
- `docs/PROJECT_HISTORY.md:31-35` (§5): "The library has no option to put its tables in a separate schema. … Change.
  Synchronous durability is required; the accepted checkpoint ID is stored on the run and read only after the library
  confirms it; every node must be idempotent; the saver's schema is set through the connection's search path."

### 2.6 What a checkpoint and an interrupt may contain

- SA:496 (verbatim): "`drafts(id, run_id, draft_sha256, validated, kind, created_at)` holds only identifiers, the hash
  of the canonical validated draft and the verdict. The draft payload itself is held by the worker between validation
  and `freeze_proposal` (one node); it is never written to `drafts`, to checkpoints (R091) or to events [R8-R2]."
- SA:563: "**Graph state is IDs only.** Interrupt payloads and graph state carry IDs and hashes only (R091)."
- BS:423: "Every resumed workflow checks access again before loading evidence into a model. … Do not re-expose revoked
  text from old checkpoints, generated summaries, or event payloads."
- SA:421: `drafts` "(pre-freeze model output, IDs only)": `worker` ins, sel; `app_definer` sel.

### 2.7 `resume_input` and the clarification reply

- SA:343 (AM-15 job types): "`resume_input` | API with a clarification reply | Resume after a clarification | read
  tools | AWAITING_INPUT → QUEUED". SA:333: read tools are callable by "`investigate` and `resume_input` jobs (read
  handles)". SA:338: "`investigate`/`resume_input` handles are accepted only by mcp-read".
- SA:369 (admission `clarification_reply`): "reply bound to an outstanding clarification ID and expected version |
  message + `resume_input` job, 202".
- SA:501 (AM-20.4): "`resume_input` | `api` | `run_id:clarification_event_id`". SA:419: `jobs` "ins (`resume_input`
  only)" for `api`. Erratum 62 (`SESSION_STATE.md:488-489`): the sweeper "never inserts a `resume_input` or `execute`
  row."
- BS:273: "`POST /api/v1/runs/{id}/clarifications` | Bind reply to outstanding question ID and expected version; commit
  before resume enqueue". BS:106-133 flow: "Persist clarification and pause" → "User reply: validate, persist, resume".
- AM-14 (SA:305, SA:308): `clarification.received` and `run.answered` are event types.

### 2.8 R114's and R129's exact words

- R114: "Read-only answers complete as ANSWERED without proposals"; "Answer path cites evidence, creates no proposal or
  grant, ends ANSWERED." (`acceptance-matrix.json:2027-2041`).
- R129: as quoted in §1.2 (`acceptance-matrix.json:2294-2315`).

### 2.9 Versions pinned (AM-30)

- SA:575: "**Versions observed on 2026-10-06** (exact pins live in `uv.lock`)". SA:580: "langgraph | 1.2.14". SA:581:
  "langgraph-checkpoint-postgres | 3.1.2". SA:582 "langchain-ollama | 1.1.0". `docs/reviews/plan-review-2026-10-06.md:10`
  says the round-2 facts were "checked against downloaded package source (mcp 2.3.0, langchain-ollama 1.1.0,
  langgraph 1.2.14, langgraph-checkpoint-postgres 3…" and `:50`: "The LangGraph default is `durability="async"`, which
  means "persisted asynchronously while the next step executes" (`langgraph/types.py:98-103`, `pregel/main.py:2672`)."

### 2.10 What a graph node may call

- SA:207: "the model never sees a tool"; `retrieve_evidence` (mcp-read), `execute_approved_proposal` (mcp-write),
  `reconcile_outcome`; `validate_and_freeze` (`freeze_proposal`).
- AM-15 (SA:340-345): tools per job type: `investigate` and `resume_input` → read tools; `execute` →
  `create_incident`; `recover` → `create_incident` (INTENT only), `get_incident_receipt`, `abort_incident`. SA:223:
  "The worker never contacts the destination." SA:225: "The worker drives the process by calling MCP tools under an
  `execute` or `recover` job."
- SA:203-204 model permit: "A `model_permit` row, leased and polled with `SKIP LOCKED` plus backoff, enforces global
  model concurrency (1)."
- SA:379 model router: the `DraftGenerator` factory in the worker; "no silent fallback between routes".
- BS:419 (the evidence bundle, verbatim): "The model receives a bounded evidence bundle: fixed asset/interval, status
  observation, alert records or aggregate plus truncation notice, permitted excerpts, source IDs/versions/hashes and
  retrieval timestamp. It cannot read the …". BS:551: "Retrieval bundle | At most 8 references and 12,000 input tokens
  within model context; truncation explicit". BS:552: "Read-tool work | At most 6 calls including retries; max 2
  retries per transient read within total cap". BS:562: "Retry only transient permitted reads with capped exponential
  backoff/jitter."

---

## 3. The tree as it is (branch `plan-q`, `c96d13c`)

### 3.1 `worker/src/ops_worker/` — the investigate path today

- `handlers.py` (385 lines). Module docstring `:1-16` describes the flow and ends "No LangGraph (→ T20)." Constants:
  `EXECUTE_RETRY_SECONDS = 30` (`:50`), `QUERY_CHARS = 500` (`:51`), `INTERRUPTED` (`:52`, `TODO(T20)`), the templated
  outcomes `MODEL_UNAVAILABLE` (`:54`), `MODEL_INVALID` (`:55`), `NOT_ROUTED` (`:56`, "the draft was an answer or a
  clarifying question, which this build does not route yet"), `ABSTAINED` (`:57`), `RETRIEVAL_MODE: Final = "lexical"`
  (`:58`, `TODO(T25)`), `BUDGET_MARGIN_SECONDS = 5.0` (`:61`). `Deps` (`:71-84`: `conn`, `mcp`, `generator`, `urls`,
  `worker_name`, `workload_azp`, `leases`, `heartbeat`). `_event` (`:87-97`, one fenced unit per event), `_fail`
  (`:100-104`, `transition_run` with `detail={"message": …}`).
- `investigate` (`:107-195`), in order:
  1. One unit (`:110-139`): `set_tenant`, `fenced`, `run_row(lock=True)`. A run found in RETRIEVING or DRAFTING is
     failed `INTERRUPTED` (`:115-122`); any state but QUEUED returns (`:123-125`); the message text is read from
     `app.messages` (`:126-130`); QUEUED → RETRIEVING (`:131`); a read handle is minted (`:132-139`).
  2. `tool.started` `{"message": "search_procedures"}` (`:140`).
  3. One MCP call as a lease effect (`:144-151`): `search_procedures` with `{"query": text[:500], "limit": 3, "mode":
     "lexical"}`. No `get_asset_status` or `get_recent_alerts` call exists in the worker.
  4. `evidence_from_search` (`:152`), then the `RunManifest` (`:155-162`) from the generator's route/digest,
     `PROMPT_VERSION` and the tool's `corpus_version`/`retrieval_mode`.
  5. Any `McpCallFailed`, `KeyError`, `ValidationError`, `ValueError` → RETRIEVING → FAILED "retrieval failed"
     (`:163-166`); `retryable` is never read.
  6. `tool.completed` (`:167`); no evidence → RETRIEVING → INSUFFICIENT_EVIDENCE "no procedure section matched"
     (`:168-170`).
  7. One unit (`:171-179`): RETRIEVING → DRAFTING and `insert_run_manifest` (before the model call).
  8. `_draft_and_freeze` (`:180-195`); `LeaseLost` re-raised (`:182-183`); `ModelUnavailable` → FAILED
     `MODEL_UNAVAILABLE`; `ModelOutputInvalid` → FAILED `MODEL_INVALID`; any other exception → FAILED "drafting failed"
     (`:191-195`).
- `_draft_and_freeze` (`:198-267`): the model permit for both attempts (`:203`); `DraftRequest(asset_id, text,
  start_at, end_at, answer_only=Intent(run["intent"]) is Intent.ANSWER_ONLY, remaining_seconds=…)` (`:204-213`);
  `generate` as a lease effect (`:214`). Kinds: `abstain` without question → INSUFFICIENT_EVIDENCE `ABSTAINED`
  (`:215-217`); any other non-proposal (answer, abstain+question) → FAILED `NOT_ROUTED` (`:218-221`, `TODO(T20)`);
  `freeze_allowed(Intent(...))` (`:222`, raises `AnswerOnlyRun`); `build_proposal(... revision=1 ...)` (`:225-237`,
  revision hard-coded `:229`); one unit (`:238-267`): `fenced`, the worker's own `INSERT INTO app.drafts` (`:245-249`,
  `validated=true`, the kind, the hash), `explanation.ready` with `source=model_summary` and payload `{"message":
  "Drafted by model route … (prompt …).", "evidence_refs": [...]}` (`:250-260`), `freeze_proposal` (`:261-267`).
- `execute` (`:270-324`): APPROVED or EXECUTING per `JOB_RULES[EXECUTE].run_states`; mints a write handle; calls
  `create_incident`; transport failure or `GRANT_DEFERRED` → `release_lease(... requeue_seconds=30)` (`TODO(T22)`
  `:305`, `:312`); an `outcome`/`UNKNOWN` envelope → `_mark_unknown` (`:327-351`).
- `handle` (`:354-364`): `INVESTIGATE` → `investigate`; `EXECUTE` → `execute`; every other type → log "is not handled
  by the walking skeleton" (`:363`); then `release_lease` (the job's final unit) (`:364`). So `resume_input` and
  `recover` jobs are closed without work. `abandon` (`:367-385`): revoke handles and `unclaim_job` in one unit, no
  transition.
- `main.py` (219 lines): `POLL_SECONDS = 0.5` (`:35`), `MAX_DEFERRALS = 16` (`:36`), `LOOP_LOCK_TIMEOUT = "SET
  lock_timeout = '10s'"` (`:38`). `claim` (`:50-58`), `run_job` (`:61-77`: heartbeat `hold`/`drop`, `LeaseLost` →
  `abandon`), `run_forever` (`:80-102`). `_main` (`:140-211`): `start_route(settings.env("MODEL_MODE"))` before any
  database connection (`:147`); `settings.leases()` (`:151`); the loop connection (`:154`) with the lock timeout
  (`:157`); the probe connection (`:159`); `assert_clock_profile` (`:160`); `assert_relation` on `app.model_permit` and
  `app.run_manifests` (`:161-162`); the heartbeat thread with its own synchronous connection (`:164`); three
  connections in all (docstring `:1-3`); health server on `OPS_WORKER_HEALTH_PORT` 8070 (`:184`); SIGTERM not drained
  (`:197-201`, `TODO(T30)`). `main` uses `asyncio.SelectorEventLoop` on Windows (`:216-217`: "psycopg async refuses the
  Proactor loop").
- `drafting.py` (164 lines): `PROMPT_VERSION = prompts.DRAFT_VERSION` (`:28`, = `"incident-draft-v2"`),
  `WORKFLOW_VERSION = "investigation-v1"` (`:29`), `ATTEMPT_SECONDS = 60.0` (`:32`), `BUDGET_SECONDS = 90.0` (`:33`),
  `DraftRequest` (`:36-48`), `EvidenceItem` (`:51-60`), `DraftGenerator` protocol (`:63-76`: `route`, `digest`,
  `start`, `generate(request, evidence)`), `ModelRouteError`, `ModelStartError`, `ModelUnavailable`,
  `ModelOutputInvalid` (`:79-98`), `FakeDraftGenerator` (`:101-133`: always `kind="proposal"` citing `evidence[0]`;
  ignores `answer_only`; raises `ValueError` on empty evidence), `make_generator` (`:136-150`), `start_route`
  (`:153-164`).
- `ollama_drafting.py` (323 lines): the qwen3:8b route (docstring `:1-30`); `payload` (`:131-149`) sends
  `confirmed_request`, `asset_id`, `interval`, `permitted_evidence`, `allowed_evidence_ids`, `requested_output_schema`
  (no status, no alerts, no answer_only statement); `OllamaDraftGenerator` (`:201`), `start` (`:235`), `generate`
  (`:303`).
- `proposals.py` (97 lines): `EXPIRY = 15 min` (`:21`), `Frozen` (`:24-30`), `evidence_from_search` (`:33-52`),
  `build_proposal` (`:55-97`, `workflow_version=WORKFLOW_VERSION` `:91`).
- `permit.py` (78 lines): `PERMIT_TTL_SECONDS = 95` (`:27`); `model_permit` context manager (`:63-78`); the permit is
  released when the call ends or is cancelled (docstring `:10-14`).
- `heartbeat.py` (222 lines): `Heartbeat(threading.Thread)` (`:103`), `hold`/`drop`/`stop`/`tick` (`:130-205`); on
  loss it cancels the job's effects (`Lease.cancel_effects`) and "never cancels a database unit" (docstring `:11-15`).
- `mcp.py` (185 lines): `HttpMcpCaller` (`:124`), `check_listing`/`read_result` for read tools (`:55-105`), the write
  path's `TODO(T20)` (`:182`).
- There is no `outcomes.py` in `worker/src/ops_worker/`; the outcome vocabulary is `core/src/ops_core/outcomes.py`.
  No `lease.py` in the worker either: `ops_core.lease` holds `Lease`, `LeaseLost`, `Renewal`, `renew`
  (`core/src/ops_core/lease.py:48-244`). No module imports `langgraph`.

### 3.2 How a run moves between states today

- `ops_core.states` (`core/src/ops_core/states.py`, 298 lines): `RunState` 17 states (`:22-42`); `Reason` (`:45-57`);
  `Intent` (`:69-73`); `TransitionRow` (`:110-118`); `_rows()` (`:136-205`): worker rows QUEUED → RETRIEVING,
  AWAITING_INPUT → QUEUED, RETRIEVING → DRAFTING / AWAITING_INPUT / INSUFFICIENT_EVIDENCE, DRAFTING → AWAITING_INPUT /
  ANSWERED / INSUFFICIENT_EVIDENCE (`:142-152`), RETRIEVING/DRAFTING → FAILED (`:155-156`); `TRANSITIONS` (`:208`);
  `ACTIVE_STATES` (`:211-222`), `TERMINAL_STATES` (`:223-225`), `WORKER_TRANSITION_TARGETS` (`:239-241`);
  `require_transition` (`:248-268`); `freeze_allowed` (`:286-298`).
- The SQL mirror: table `app.transitions` (revision 0002 rows, e.g. `0002_roles_grants_rls.py:156-188`);
  `app._transition` (`0003_run_path_functions.py:193-234`: runs `FOR UPDATE`, `expected_version`, the table row,
  `state_version + 1`, `slot_held`, `run_state_history`, optional event); `app.transition_run`
  (`0003_run_path_functions.py:323-353`): worker-only, refuses post-grant targets (`:335-337`), maps the target to the
  event (`:343-348`: FAILED → `run.failed`, INSUFFICIENT_EVIDENCE → `run.insufficient_evidence`, ANSWERED →
  `run.answered`, AWAITING_INPUT → `clarification.requested`), the `p_detail` JSON is the event payload (`:349-350`).
  `app.append_event` (`0003_run_path_functions.py:355-380`) refuses `run.*`, `action.*`, `review.*`, `proposal.*`,
  `approval.*` and `clarification.requested` from callers (`:366-372`). Later revisions keep `transition_run`'s body
  (`0007_leases_fences.py:19`).
- `ops_core.persistence.transition_run` (`core/src/ops_core/persistence.py:280-305`), `append_event` (`:316-330`).
- Tests of the table: `tests/plan_c/test_states.py` (e.g. `test_table_matches_the_allowed_set_exactly` `:146`,
  `test_worker_targets_exclude_post_grant_states` `:193`, `test_answer_only_runs_cannot_freeze` `:232`);
  `tests/plan_e/test_transitions_table.py` (the newest revision's literal rows equal `TRANSITIONS`, `:117`; event types
  equal the enum, `:157`).
- `AWAITING_INPUT` and `ANSWERED` are reached by no worker code today. Live tests stage `AWAITING_INPUT` with the worker
  role's `transition_run(…, 'RETRIEVING', 'AWAITING_INPUT', …)` (`tests/e2e/test_admission_live.py:395-401`,
  `test_event_journal_live.py:157`, `test_mcp_read_t15_live.py:258`, `test_migration_0009_live.py:142`,
  `test_wakeups_live.py:115`); `tests/plan_g/fakes.py:299` `seed_question` does the same in the unit fakes.
- The API's reply path (`api/src/ops_api/store.py`): `check_reply_run` (`:225-239`: the caller's own run, state
  `AWAITING_INPUT`, `state_version == expected_version`, else 404/403/409), `check_reply_question` (`:243-250`: the
  `question_id` must be the run's latest `clarification.requested` event id); `record_reply` (`:927-985`): runs `FOR UPDATE`
  with `SET LOCAL lock_timeout = '2s'`, then message `CLARIFICATION_REPLY`, the `resume_input` job through
  `insert_job_untargeted` with key `dedup_key(RESUME_INPUT, run_id, clarification_event_id=question_id)` (a second
  reply → 409 "already answered"), and `clarification.received` with payload `{"question_id", "message_id"}`. The run
  stays `AWAITING_INPUT`; the API does not transition it.

### 3.3 `runs.checkpoint_id` and the revisions

- `runs.checkpoint_id text` was added by revision 0002 (`migrations/app/versions/0002_roles_grants_rls.py:205`,
  dropped by its downgrade `:497`); the worker's column grant is `upd=("checkpoint_id", "budget_used")`
  (`0002_roles_grants_rls.py:75`, `core/src/ops_core/privileges.py:95`, pinned by `tests/plan_e/test_privileges.py:37`).
  No code reads or writes `checkpoint_id` or `budget_used`. `runs` is under `tenant_isolation` RLS (SA:510).
- `runs` columns (`0001_walking_skeleton.py:72-94` plus 0002): `run_id`, `tenant_id`, `conversation_id`, `message_id`,
  `requester`, `intent` (CHECK `investigate`/`answer_only`), `supersedes_run_id`, `asset_id`, `start_at`, `end_at`,
  `state`, `state_version`, `reason`, `active_proposal_id`, `cancel_requested`, `created_at`, `updated_at`, and from
  0002 `slot_held`, `next_event_seq`, `cancel_requested_at`, `checkpoint_id`, `budget_used`. No `workflow_version`
  column exists (`WORKFLOW_VERSION` lives only in the proposal payload, `contracts.py:377`).
- Revisions: `0001_walking_skeleton` … `0014_run_manifests` and the `testclock` branch `tc_0001_test_clock.py`
  (`migrations/app/versions/`). No revision creates schema `checkpoints` or any checkpoint table (`git grep -i
  checkpoint` over `migrations/` finds only the 0002 column and grant). The next free revision id is `0015`.
- `app.run_manifests` (revision 0014, `0014_run_manifests.py:1-19`, `:39` `run_id uuid PRIMARY KEY`): "One immutable
  row per run, written by the worker in the unit that moves the run RETRIEVING → DRAFTING, before the model is called";
  worker INSERT/SELECT, api SELECT, no UPDATE/DELETE (erratum 120). A second insert for the same run fails on the
  primary key (`persistence.insert_run_manifest` docstring, `persistence.py:1037-1053`).
- `app.drafts` (`0001_walking_skeleton.py:133-140`; tenant column added in 0002 `:238-245`): `id`, `run_id`,
  `draft_sha256`, `validated`, `kind`, `created_at`; no CHECK on `kind`.
- `freeze_proposal` SQL (`0004_write_path_functions.py:108-167`): refuses `intent = 'answer_only'` (`:128`); requires
  the payload's `revision` to equal `max(revision) + 1` (`:149-152`, else `OC003` "revision").

### 3.4 `core/src/ops_core/routing.py` — the routers' vocabularies

- `AdmissionRoute` (`:29-37`), `GraphRoute` (`:40-52`: `clarify`, `retrieve`, `draft`, `answer_only`, `abstain`,
  `freeze`, `await_decision`, `execute`, `recover`, `publish`; docstring "table owned by T20"), `ModelRoute`
  (`:55-59`: `fake`, `qwen3:8b`).
- The admission table: `AdmissionFacts` (`:207-217`), `AdmissionRule(name, predicate, route, cause)` (`:281-288`),
  `ADMISSION_RULES` (`:297-310`, seven rows, first match wins), `REPLY_RULES` (`:313-315`, one row), `_first`
  (`:318-330`, raises `LookupError` when no row matches: "the tables are total; a test walks them"), `route_admission`
  / `route_reply` (`:340-347`). `ADMISSION_RULES` routes messages at the API; it is not a graph table. **No graph route
  table exists**: `GraphRoute` is an enum only, and nothing in the tree maps run facts to a `GraphRoute`.
- `RunManifest` (`:350-371`): frozen, strict; `retrieval_mode: Literal["lexical", "vector_exact"]` (`:364`,
  `TODO(T25)` comment `:363`); a real route requires a digest (`:366-371`).
- `GraphRoute` users: `scripts/build_schemas.py:38`, `:784` (the `graph` enum of `schemas/route.schema.json`),
  `tests/plan_c/test_jobs_routes_outcomes.py:215-226` (asserts the ten values).
- `schemas/route.schema.json` (`:1-42`): `admission`, `graph` (the ten values, `:19-32`), `model` (`fake`, `qwen3:8b`),
  `minProperties: 1`. `schemas/run-manifest.schema.json` (`:1-76`): the six fields, all required; real routes need a
  string digest (`:56-75`). Both generated by `scripts/build_schemas.py` (`route()` `:777`).
- R129's admission walk: `tests/plan_g/test_routing_admission.py`.

### 3.5 Jobs, the lease, the fence, events

- Job types (`core/src/ops_core/jobs.py:37-47`): `investigate`, `resume_input`, `execute`, `recover`,
  `expire_proposals`, `sync_memberships`, `sweep_wakeups`, `deliver_outbox`; enforced by revision 0007's CHECK
  (`0007_leases_fences.py:73-84` `JOB_TYPES_0007`, `:96` `jobs_type_check`). `JOB_RULES[INVESTIGATE]` run states
  QUEUED, RETRIEVING, DRAFTING (`jobs.py:69-78`); `JOB_RULES[RESUME_INPUT]` run states AWAITING_INPUT, QUEUED, read
  tools, server READ, created by `api`, key `run_id:clarification_event_id` (`jobs.py:79-86`); `_PARTS` (`:139-144`).
  `_resolve_handle` derives the server from the job type: `investigate`/`resume_input` → read (`0007:154`).
- `app.run_lease` and the lease code: `persistence.acquire_lease` (`persistence.py:800-855`: FOR UPDATE NOWAIT in a
  savepoint, fence + 1), `claim_next` (`:878-928`: claim and lease in one transaction; a busy lease defers the job),
  `fenced` (`:931-944`: `LOCK_FOR_SHARE`, compares owner, fence, liveness; raises `LeaseLost`), `release_lease`
  (`:947-980`: lease row FOR UPDATE, revoke handles, finish or re-queue the job, `pull_forward`, `lease_until =
  '-infinity'`), `unclaim_job` (`:983`), `pull_forward` (`:992`), `take_model_permit`/`release_model_permit`
  (`:1014-1034`), `mint_handle` (`:1107`). `ops_core.lease.Lease` (`lease.py:61`): `check`, `effect` (`:138`),
  `cancel_effects` (`:173`), `held_for` (`:101`), `mark_lost`; `DEADLINE_MARGIN_SECONDS = 5.0` (`:34`).
- The lease is released at the end of every handled job (`handlers.handle` `:364` → `release_lease`), so a run waiting
  in AWAITING_APPROVAL (or, once reached, AWAITING_INPUT) holds no lease and no job today.
- The published lock order (`core/src/ops_core/locking.py:29-50`): `advisory:idempotency`, `advisory:asset`,
  `advisory:notification`, `jobs:claim`, `run_lease`, `runs`, `messages`, `drafts`, `proposals`, `decisions`,
  `memberships`, `execution_grant`, `action_attempt`, `action_attempt_state`, `operator_resolutions`,
  `invocation_context`, `run_state_history`, `events`, `outbox`, `jobs:finish`, `idempotency_request`; no
  `checkpoints` entry. Documented worker transactions (`:78-85`, e.g. "worker drafting start (transition_run, run
  manifest)": `("run_lease", "runs")`); R107's note says a test covers every documented transaction.
- `_append_event` (re-created by `0008_journal_outbox.py:144-245`): the payload is closed over `PAYLOAD_KEYS`
  (`core/src/ops_core/outcomes.py:189-205`: `message`, `status`, `evidence_refs`, `proposal_id`, `action_id`, `code`,
  `reason`, `outcome`, `receipt`, `tombstone`, `question_id`, `message_id`, `outbox_id`); the event `message` is at most
  2500 characters (`schemas/event.schema.json:76-80`).
- Event types (`outcomes.py:142-173`, 27): the worker emits today `tool.started`, `tool.completed`,
  `explanation.ready` (proposal path only, erratum 117), and through definer functions `run.failed`,
  `run.insufficient_evidence`, `proposal.ready` (`freeze_proposal`), `action.uncertain` (`mark_unknown`); `run.answered`
  and `clarification.requested` are mapped in `transition_run` but never reached. The API emits
  `clarification.received`.
- Message kinds (`core/src/ops_core/contracts.py:150-168`): `investigate`, `ask`, `clarification_reply`,
  `status_question`, `status_answer`, `clarification_question`; the system kinds (`status_answer`,
  `clarification_question`) are written by the API with `author` NULL (`:167-168`). AM-20.2 (SA:414): `messages` —
  `api` sel, ins; `worker` sel only.
- `ModelDraft` (`contracts.py:319-347`): `kind ∈ {proposal, answer, abstain}`, `title` ≤120, `summary` ≤2500,
  `evidence_refs` ≤8, `assumptions`, `limitations`, optional `question` ≤500 (`contracts.py:78-82`); a proposal or an
  answer cites at least one reference; only an abstain carries a question; `clarification_requested` property.
  `ops_core.draft_validation.validate(text, reasoning, allowed_ids, answer_only)` (`draft_validation.py:111`) refuses a
  proposal on `answer_only` (`proposal_on_answer_only`, `:20`, `:56`).

### 3.6 The sweeper's wake-ups

- `sweeper/src/ops_sweeper/wakeups.py:1-27` (docstring) and `:47` `WAKEUPS = (("QUEUED", "investigate"), ("APPROVED",
  "execute"))`: re-arms the newest done job of a run left waiting in that state past the grace; "AWAITING_INPUT is
  T20's, OUTCOME_UNKNOWN and ESCALATED are T22's" (`:7`). `job_type_case` builds the CASE from the same pairs
  (`:52`); `tests/plan_i/test_wakeups.py:78-79` extends `WAKEUPS` with `("AWAITING_INPUT", "resume_input")` to check
  the CASE. Erratum 63 (`SESSION_STATE.md:490-503`) and erratum 64 (`:504-506`: "the worker's 0.5 s per-tenant poll is
  the v1 wake mechanism"). The lease reclaim is `sweeper/src/ops_sweeper/leases.py` (erratum 49).

### 3.7 Workspace dependencies

- `uv.lock` (89 packages) holds **no** `langgraph`, `langgraph-checkpoint`, `langgraph-checkpoint-postgres`,
  `langgraph-prebuilt`, `langgraph-sdk` or `ormsgpack` entry. It holds `psycopg 3.3.6` (`uv.lock:1268`),
  `psycopg-binary 3.3.6` (`:1285`), `langchain-core 1.7.0` (`:617`), `langchain-ollama 1.1.0` (`:638`),
  `langchain-protocol 0.0.20` (`:651`), `mcp 2.3.0` (`:884`), `ollama 0.6.3` (`:967`), `httpx 0.28.1` (`:430`),
  `xxhash 4.0.2` (`:2048`, a dependency of `langsmith`, `:679`). No `psycopg-pool` entry.
- `worker/pyproject.toml`: `ops-core`, `mcp==2.3.0`, `uvicorn>=0.54,<1`, `langchain-ollama==1.1.0`,
  `langchain-core==1.7.0`, `ollama==0.6.3`, `httpx==0.28.1`; description "Run-lease worker: LangGraph orchestrator,
  LangChain draft node, MCP client". `core/pyproject.toml`: `psycopg[binary]>=3.3,<4` among others; no LangChain.
- Root `pyproject.toml`: `testpaths` lists `tests/plan_a` … `tests/plan_p` and `tests/e2e` (no `tests/plan_q`);
  `asyncio_default_fixture_loop_scope = "function"`; markers `sweeper_stamps`, `slow_live`; mypy `strict = true`.
- What `langgraph 1.2.14` and `langgraph-checkpoint-postgres 3.1.2` would pull in (and whether they accept `psycopg
  3.3.6`, `langchain-core 1.7.0`) is not knowable from the tree; no network was used.

### 3.8 Tests that pin the worker's flow, and the live profile

- Unit (no database): `tests/plan_d/test_worker.py` (`test_model_router_has_two_routes_and_no_fallback` `:31`,
  `test_fake_draft_is_deterministic_and_valid` `:43`, `test_build_proposal_binds_hash_to_canonical_bytes` `:55`,
  `test_evidence_from_search_requires_the_contract_fields` `:108`); `tests/plan_e/test_worker_rotate.py`;
  `tests/plan_h/test_worker_units.py` (the fake harness: `RUN` `:37`, `JOB` `:49`, `WRITES` `:51`, `Log` `:73`,
  `FakeConn` `:103`, `ScriptedMcp` `:131`, `patch` `:140`, `make` `:183`; tests e.g.
  `test_every_unit_that_writes_opens_with_the_fence` `:196`, `test_the_final_unit_releases_the_lease_with_the_job`
  `:214` (runs a `resume_input` job "not handled yet (T20)" `:218`), `test_an_interrupted_run_is_failed_not_left_active`
  `:288`, `test_a_heartbeat_cancel_hands_the_job_back` `:371`); `tests/plan_h/test_permit.py`,
  `test_heartbeat.py`, `test_lease.py`, `test_locking.py`; `tests/plan_p/test_investigate_drafting.py` (on Plan H's
  fakes: manifest before the model `:72`, one permit hold `:99`, no fallback `:114`,
  `test_each_kind_that_is_not_a_proposal_ends_the_run_without_freezing` `:133`, answer_only request `:220`, budget
  tests `:207`, `:234`, `:245`); `tests/plan_p/test_ollama_drafting.py`, `test_worker_startup.py`,
  `test_draft_validation.py`, `test_migration_0014.py`; `tests/plan_i/test_wakeups.py`; `tests/plan_c/test_states.py`;
  `tests/plan_g/test_routing_admission.py`, `test_store_units.py` (reply binding on fakes).
- Live (`OPS_LIVE=1`, collected but skipped by `check.py`; run by `check.py --profile test` against per-session
  databases, Plan E debt `SESSION_STATE.md:1160`): `tests/e2e/test_worker_live.py` (`test_investigate_then_execute`
  `:169` asserts the event list `run.accepted, tool.started, tool.completed, explanation.ready, proposal.ready` and the
  history `QUEUED, RETRIEVING, DRAFTING, AWAITING_APPROVAL` `:184-199` and one manifest `:200`;
  `test_drafting_failure_fails_the_run` `:222`; `test_unreachable_write_server_requeues_the_execute_job` `:306`;
  `test_unknown_envelope_is_recorded_by_the_worker` `:347`); `tests/e2e/test_heartbeat_live.py` (R088, `slow_live`);
  `test_leases_live.py`, `test_lease_stress_live.py`, `test_fenced_definers_live.py`; `test_wakeups_live.py`;
  `test_admission_live.py`; `test_run_manifest_live.py`; `test_r105_walking_skeleton.py`; `test_mcp_read_t15_live.py`,
  `test_mcp_read_t16_live.py`, `test_mcp_write_t47_live.py`; `tests/plan_p/test_model_route_live.py` (Ollama).
- Live fixtures (`tests/e2e/conftest.py`): `live` (`:37`), `env` (`:43`), `migrated` (`:73`), `ingested` (`:81`),
  `embedded` (`:94`), `asset_sim` (`:120`), `app_conn` (`:155`), `role_conn` (`:166`), `incident_conn` (`:183`),
  autouse `fresh_memberships` (`:193`); helpers `purge_run` (`:233`), `lease_for` (`:305`), `expire_lease` (`:316`),
  `backend_pid` (`:323`), `wait_until_blocked` (`:331`), `stage_lease` (`:344`). `scripts/check.py:1-9`: "`--profile
  test` … also runs the live suite; needs the dev stack up".
- Tracked text files may hold no CR or BOM (`tests/plan_b/test_text_hygiene.py`; `.gitattributes` `* text=auto eol=lf`).

### 3.9 Gates (as recorded, not re-run for this sheet)

- `SESSION_STATE.md:1071-1072` (Plan P close-out at `cded00b`): "`check.py` `1629 passed, 222 skipped`; `check.py
  --profile test` `1830 passed, 21 skipped`; `verify_handoff.py` exit 0." The commands (`SESSION_STATE.md:1679-1683`):
  `uv run python scripts/check.py`, `uv run python -I scripts/verify_handoff.py --reference-code --manifest
  --contracts`. The dev database is at 0013 and the worker refuses to start on it until revision 0014 is applied
  (`SESSION_STATE.md:1072-1074`, `:1655-1657`), an owner step.

---

## 4. Prior rulings, debt lines and proposed errata touching T20

- **Spec rounds.** `docs/reviews/plan-review-2026-10-06.md:50` (round 2, item 4, ✓): "Checkpoints lag side effects by
  default. … **Fix:** require `durability="sync"`. Store the accepted `checkpoint_id` on the run under the fence after
  each step, and always resume from that one. That covers the stale-head and pending-writes overwrite scenario ○."
  `plan-review-r3-2026-10-06.md:69` and `plan-review-r5-2026-10-06.md:70`: the two T20 notes (§1.1).
  `docs/reviews/handoff-review-2026-10-06.md:97` (item 14): "The reference graph writes full evidence text into
  checkpoints. ✓ `integrations/langgraph_workflow.py:38` calls `interrupt({...,'proposal': run[…`" (became AM-70's
  line). `SESSION_STATE.md:75` "`durability="sync"` plus a stored checkpoint ID;" and `:105` "LangGraph resume rules
  verified against the 1.2.14 source;".
- **Plan E ruling 2** (R122 deferred because the saver is not locked): `acceptance-matrix.json:2163-2178` note;
  `SESSION_STATE.md:234`, `:1156`.
- **Plan G** (`SESSION_STATE.md:349-350`): "`resume_input` handling and the ANSWERED path -> T20". Plan G ruling 15
  (the reply route is its own one-row table; `routing.py:311-315`).
- **Plan H** erratum 57 (`SESSION_STATE.md:415-417`, "resuming it is T20's"); `plan-review-h-2026-10-15.md:201` "23.
  Checkpoints (FS Q23). Untouched (T20; R021 is M15)."; `:217` "Human waits hold no lease (R022 is T20's)."; `:2014`,
  `:2019`, `:2374` (resume from the checkpoint is `load_run` → T20; debt line "the graph's node resume").
- **Plan I** ruling 7 (`plan-review-i-2026-10-15.md:51`, `:59`: `AWAITING_INPUT`/`resume_input` left to T20);
  `plan-i-final-review-2026-10-15.md:85`, `:177` (the CASE built from `WAKEUPS` so T20's pair is not silently
  skipped). Erratum 62 (sweeper never inserts `resume_input`), 63, 64.
- **Plan J** (`plan-review-j-2026-10-15.md:68`, `:75`): "Distinguishing 401 in the worker → T20 (debt line)";
  "`resume_input` → T20."
- **Plan L** rulings 13-14 (`plan-review-l-2026-10-17.md:101-108`): "the model-side proof is T19's (R036)"; "detection
  and abstention → T19/T20". Erratum 102 (`SESSION_STATE.md:846-850`).
- **Plan M** rulings 16-17 (asset reads, the bundle, SA:377's sufficiency rule → T20); departure 6 and minor M1
  (`plan-review-m-2026-10-18.md:329-338`, `:430`, `:481-482`): the write-tool discovery debt stays with T20 citing
  SA:207 and R129. Erratum 105 (`SESSION_STATE.md:908-916`): "A read-path freshness bound is T20's, subject to the
  owner's decision on this erratum." `plan-m-final-review-2026-10-18.md:26`, `:35`, `:275` (retryable reads → T20;
  R028's T20 clause).
- **Plan N** ruling 16 (mode choice → T20/T25; `plan-review-n-2026-10-19.md:184`, `:244` "The worker's marker is
  `TODO(T25)` while the debt line names T20 and T25 — **accepted**."), rulings 6 and 9 (relevance rule → T20).
- **Plan O** ruling 7 (lexical change only as a later revision under T20, on total decimal loss);
  `plan-o-final-review-2026-10-19.md:182-183` (a T20 planner must not read "1 of 3 decimal pairs lost" as a measured
  cost: P06 is confounded).
- **Plan P** ruling 1 (no asset data until T20), ruling 11 (answers and questions → T20), round 1 M10
  (`plan-review-p-2026-10-24.md:444`, `:497`: "Debt line → T20: the payload states that a proposal is not allowed on
  an answer_only run."); `plan-review-p-2026-10-24.md:130`, `:192-193`. Errata 117 (`explanation.ready` only on the
  proposal path; the digest in the manifest only), 118 (no model hint in v1), 119 (`generate(request, evidence)`;
  `MODEL_MODE` names the route), 120 (`run_manifests` cells) — `SESSION_STATE.md:1085-1101`.
- **History.** `docs/PROJECT_HISTORY.md:31-35` (§5, the checkpoint library); `:335-336` ("resuming it is T20's");
  `:619`, `:673` (T20's relevance criterion); `:821-825`, `:830` (read freshness, retryable reads, R028's clause);
  `:1063` (lexical change under T20).
- **`handoff/BUILD_BACKLOG.md`**: `:125-127` (T20 and its notes); `:196` (T38, "Depends on: T20").
- **`STATUS.md`**: `:12` "LangGraph | Historical integration example only | Wire persistent/fenced graph, durable
  pauses and versioned recovery"; `:37` "single-writer checkpoint profile (R021 open)"; `:120` R122 deferred to T20;
  `:191` "checkpoints -> T20/T38"; `:426` "Next: T20 (the LangGraph workflow)."
- **Proposed errata awaiting the owner:** 1-9 (Plan C), 35-113, 115-121 (`SESSION_STATE.md:1648-1653`). Erratum 114 is
  decided. **The next erratum number is 122.**

---

## 5. Open questions the planner must rule on

1. **Where the graph lives and how it relates to `handlers.investigate`.** Facts: AM-01 (SA:75) and ADR-0001:22 put
   "LangGraph graph" in `worker/`; `docs/ARCHITECTURE.md:404` names `worker/graph/` (marked "not yet written"); BS:194's
   `workflows/` is the 1.0 single-package layout; today `handlers.handle` dispatches `investigate`/`execute` and
   closes every other type (`handlers.py:354-364`); `investigate` already holds AM-12's lease rules (fenced units,
   effects, the final unit releasing the lease) and T19's manifest/permit/kind logic (`:107-267`); the job is the
   wake-up and the lease is per run (SA:173). Options: the handler stays the job entry point and invokes the graph
   under the claimed lease; the graph replaces `investigate` and `execute` (and handles `resume_input`); or the
   handler's units become nodes. Also open: whether the route table (SA:377 "in `core/routing.py`") lives in core while
   nodes live in the worker, and whether `GraphRoute` gains a table beside `ADMISSION_RULES` in the same style
   (`AdmissionRule` rows, first match wins, `LookupError` when none matches).

2. **The node list and the conditional edges "generated" from the table.** Facts: SA:207's ten nodes vs BS:328's
   (`resolve_context` replaced by `route_request`); SA:377's seven key dimensions and ten routes; `GraphRoute` has
   the ten values and no table (`routing.py:40-52`); ARCHITECTURE §3 shows every node returning to `route_request`
   and each labelled edge as one table row (`:123-144`); R129 asks "a test walks every row of the route table and
   asserts the node reached"; DoD 4 "A test enumerates every graph-router row and asserts the node reached"; the
   execute, recover and reconcile logic is T21's/T22's (grant, recover jobs), but Plan M's review made T20 "the first
   task to drive mcp-write from the graph" (`plan-review-m-2026-10-18.md:335`). Options: how "generated" is proven (the
   edge map built from the table at import and compared with the graph's compiled edges; a test that every
   `GraphRoute` appears exactly once; a test that no edge exists outside the table); which rows exist in v1 for
   `execute`/`recover`/`reconcile_outcome` (full nodes now, nodes that call today's `handlers.execute` path, or rows
   whose nodes T21/T22 fill); how the table encodes "context resolved?" given contract erratum 4 (missing context is
   detected in RETRIEVING) and admission's own clarify route; whether the table is total over the seven dimensions or
   lists only reachable rows.

3. **Retrieval before drafting, the evidence bundle and "evidence sufficient?".** Facts: SA:377's code rule ("at least
   one permitted status observation and at least one effective procedure chunk, all within freshness"); the worker
   calls only `search_procedures` (limit 3, lexical) and no asset tool (`handlers.py:144-151`); BS:419's bundle names
   the status observation and alert records; BS:551-552 caps (8 references, 6 read calls, 2 retries); `ollama_drafting.payload`
   sends no status or alerts (`:131-149`); erratum 102 asks T20 for "a relevance criterion beyond" SA:377; Plan M debt:
   retryable reads end the run, a read-path freshness bound subject to erratum 105, and a 401 not told apart (Plan J);
   R038 asks for a "trace order and input bundle". Options: the read set per run (status + alerts + search, their
   order, `limit`, the alert interval = the run's interval); the sufficiency rule's exact code (counts, freshness
   window, the relevance criterion: score threshold, label rule, or none in T20 with an erratum); how retryable reads
   and 401 are handled (bounded re-queue, in-node retry within BS:552, or FAILED as today); what "trace" means for R038
   before T28's OTel (events, a recorded node log, a test spy); whether the status/alerts reach the draft payload (and
   a new prompt version, since the payload keys are the starter's; erratum 116).

4. **The checkpointer.** Facts: SA:201 names `AsyncPostgresSaver`; SA:559-562 put the tables in schema `checkpoints`,
   created by `migrator` with `PostgresSaver.setup()` and `options=-c search_path=checkpoints`, worker DML only, api
   denied (R122, owned by T09, deferred to T20); `migrator` is NOLOGIN and Alembic runs as the superuser
   (`skeleton.py:71`, Plan E debt → T30); no revision creates schema `checkpoints`; neither SA:510 nor SA:523 lists it
   for RLS; T38 (M15) is the custom fenced `BaseCheckpointSaver`; ADR-0002:23 says the stock saver has no write hook;
   neither library is locked (§3.7). Options: LangGraph's Postgres saver in schema `checkpoints` (setup run inside an
   Alembic revision vs a bootstrap step; which role owns the tables; the worker's separate connection with
   `search_path=checkpoints,pg_temp`); a custom saver over `app.*` tables (grants and RLS like other tenant tables;
   departs from SA:559-562, so an erratum); what the saver stores per checkpoint (channel values, pending writes,
   metadata) and how R091's "grep of checkpoint blobs" is run against that format (serialised bytes); whether tenant
   isolation applies to checkpoint rows at all.

5. **`runs.checkpoint_id` storage and the fence.** Facts: the column exists (`text`, revision 0002) with the worker's
   column grant; SA:211 "after each superstep … under the fence … from `stream_mode="checkpoints"` (or `aget_state`)";
   note 2 "store only checkpoint IDs confirmed by aget_tuple; treat a missing stored ID as an error"; every worker
   write opens with `persistence.fenced` (`persistence.py:931-944`); the lock order has no `checkpoints` entry and R107's
   test covers every documented transaction (`locking.py:29-85`); the saver's own write and the `runs` update are two
   transactions unless the saver shares the unit (BS:340 "No atomic cross-checkpointer transaction is assumed unless
   actually implemented and tested"). Options: a revision 0015 (for schema `checkpoints`, and any column such as a
   thread id or `workflow_version`) vs none; the thread id (run id, run id plus revision, or another key); when the
   update runs (after each superstep, only at interrupts and the end, or after every node); the update's unit
   (`fenced` + `UPDATE runs SET checkpoint_id` + nothing else, or folded into a node's state-transition unit); what a
   resume does when `checkpoint_id` is NULL or names a missing checkpoint.

6. **`durability="sync"` with the lease and the heartbeat.** Facts: SA:210; note 2 "sync durability waits only after
   the tick"; the heartbeat cancels effects, never a database unit (`heartbeat.py:11-15`); a lost lease raises
   `LeaseLost` and the job is handed back (`main.py:61-77`); the process has three connections (loop, probe,
   heartbeat) and psycopg async needs the SelectorEventLoop on Windows (`main.py:1-3`, `:216-217`); the 90 s compute
   budget runs from the claim and counts one lease's hold (Plan H debt → T29); the checkpoint write is a database
   write by the saver. Options: whether checkpoint writes run on the loop connection, a fourth connection, or a pool
   (no `psycopg-pool` in the lock); whether a checkpoint write is treated as an effect (cancellable) or a unit (never
   cancelled); how R108's "durability=sync asserted" is checked (an argument spy, a test reading the checkpoint before
   the next node runs).

7. **ID-only interrupts and `resume_input`.** Facts: SA:213 `Command(resume=<event_id>)`; BS:330 "Resume payloads carry
   only persisted event identifiers"; SA:563; the API commits the reply message, the `resume_input` job (key
   `run_id:clarification_event_id`, the event id being the `clarification.requested` event's) and
   `clarification.received {question_id, message_id}` and leaves the run AWAITING_INPUT (`store.py:927-985`); SA:135
   puts AWAITING_INPUT → QUEUED in the worker's `resume_input` job; `JOB_RULES[RESUME_INPUT]` allows read tools in
   AWAITING_INPUT and QUEUED (`jobs.py:79-86`); the QUEUED/`investigate` wake-up predicate would also match a run moved
   back to QUEUED (Plan I debt); SA:137 "at most 2 clarification rounds; on a third round → INSUFFICIENT_EVIDENCE" and
   no counter column exists; `ModelDraft.question` ≤500. Options: which event id is the resume value
   (`clarification.received`'s, the question's, or the reply message id); what the resumed node rereads (the reply
   text from `messages`, validated again or trusted as the API validated it); whether the `resume_input` job carries
   the run through retrieval and drafting itself or only moves it to QUEUED for an `investigate` job (whose dedup key
   `run_id:revision` already exists for revision 1); how rounds are counted (count of `clarification.requested`
   events, a graph state counter, or a column); idempotency of a replayed resume (the job's dedup key; a second
   `transition_run` from AWAITING_INPUT meets OC003).

8. **Where a clarifying question and an answer are stored.** Facts: SA:496 forbids the draft payload in `drafts`,
   checkpoints and events; the worker may not insert `messages` (SA:414) and `clarification_question` messages are the
   API's system kind (`contracts.py:167-168`); `transition_run` passes `p_detail` as the event payload, so a question
   could ride in `clarification.requested.message` (≤2500) and an answer in `run.answered.message`; the requester must
   see the question to reply to it (`check_reply_question` binds by event id only); R114 "Answer path cites evidence";
   AM-40 shows ANSWERED as "a completed conversation answer" (SA:634); `explanation.ready` carries `message` and
   `evidence_refs` and is emitted only on the proposal path (erratum 117). Options: the question/answer text in the
   event payload (an erratum against SA:496's "events"); a new worker grant or definer function for system messages
   (an AM-20.2 change); a templated message plus `evidence_refs` with the text kept elsewhere; whether
   `explanation.ready` is emitted on the answer and clarification paths.

9. **Human waits releasing the lease, and the sweeper.** Facts: R022 "no active worker lease/long DB transaction/model
   budget consumed"; today every handled job ends in `release_lease` (`handlers.py:364`); ARCHITECTURE:144 "The two
   interrupt nodes end the graph run; a committed human event and its wake-up job start a new run of the graph";
   `await_independent_decision` is resumed by the `execute` job (`record_decision` inserts it, SA:454); `WAKEUPS` has
   no AWAITING_INPUT pair (`wakeups.py:47`); erratum 62 forbids the sweeper inserting `resume_input`; R023 (the
   decision crash) is T21's; the human-wait exclusion from the budget is T29's. Options: whether T20 adds
   `("AWAITING_INPUT", "resume_input")` to `WAKEUPS` (and what "done but not moved" means for an interrupted graph);
   how R022 is evidenced (lease row released, no open transaction from the worker's backends, permit free, budget
   not advancing) and whether `runs.budget_used` is touched now or left to T29.

10. **The ANSWERED path and the answer/abstain+question drafts Plan P left FAILED.** Facts: SA:153 (selected by
    `intent = 'answer_only'`); SA:377 (the validated kind selects only abstain/clarify/answer_only vs freeze, `freeze`
    gated by intent); SA:451 allows DRAFTING → ANSWERED and → AWAITING_INPUT; today both end FAILED `NOT_ROUTED`
    (`handlers.py:218-221`); the real run had 40 abstentions, 26 with a question (`tasks.json:860`); DEV-002 is an
    `investigate` prompt whose expected outcome is ANSWERED (`scenarios.jsonl:2`); the draft payload does not tell the
    model a run is `answer_only` (Plan P M10 debt); `validate` refuses a proposal on `answer_only`. Options: whether an
    `investigate` run may end ANSWERED on an `answer` draft (or only `answer_only` runs; an `answer` on an
    `investigate` run then being abstain/FAILED); whether an `answer` on an `answer_only` run needs evidence refs
    checked against the bundle (it does today through `allowed_ids`); the payload statement (a new prompt version
    vs a payload key); what INSUFFICIENT_EVIDENCE vs AWAITING_INPUT does on the third round.

11. **What the fake route does in the graph.** Facts: `FakeDraftGenerator` always returns a proposal and ignores
    `answer_only` (`drafting.py:114-133`); on an `answer_only` run the fake ends "drafting failed" via
    `freeze_allowed` (Plan P final review `:298-300`); R129's walk needs every row reachable; tests inject generators
    (`RaisingGenerator`, `tests/e2e/test_worker_live.py:214`); `MODEL_MODE` names the route and nothing else (erratum
    119). Options: the fake answers on `answer_only` runs (a behaviour change of the fake route, which the skeleton and
    R105 use); test-only scripted generators for answer/abstain/question; whether a third route value is needed (no:
    erratum 119 says new routes are a later enum and schema change).

12. **Crash recovery, interrupted runs and the stray head.** Facts: today a run found in RETRIEVING/DRAFTING is failed
    INTERRUPTED (`handlers.py:115-122`, Plan H debt → T20); SA:214 (crash recovery forks; store the forked id); SA:215
    (every node idempotent, reread authoritative state); notes 1-2 (kill-mid-superstep, kill-at-interrupt, two crashes
    in a row, join stale in-process tasks); DoD 2 "a newer stray head is ignored"; v1 runs one replica (SA:217);
    replaying a node repeats its side effects unless guarded: `tool.started`/`tool.completed` events, `mint_handle`,
    the manifest insert (primary key on `run_id`, a replay raises), the `drafts` insert (new uuid each time), a
    second model call and permit; `freeze_proposal` checks `revision = max + 1` (`0004:149-152`). Options: which nodes
    are guarded by rereading state (e.g. manifest present → skip), which effects may repeat (events), how a stray
    head is produced in a test without a second replica (a direct saver write after the stored id), and whether a
    resumed DRAFTING run re-drafts (a second model call) or fails.

13. **Revision re-entry.** Facts: note 2 "Define revision re-entry (new thread per revision or explicit edges back to
    retrieval)"; `create_revision` (T21, SA:455) moves a run to QUEUED and inserts an `investigate` job with key
    `run_id:revision+1`; `build_proposal` hard-codes `revision=1` (`handlers.py:229`) and `freeze_proposal` requires
    `max + 1`; `run_manifests` holds one row per run (a second draft for the run cannot record a second manifest);
    BS:342 pins `workflow_version` per run and no column holds it. Options: thread per revision vs one thread with
    edges back; whether T20 builds re-entry or only leaves the seam for T21; the manifest per revision (a key change,
    erratum 120's table) vs per run; where `workflow_version` is recorded (graph metadata, a `runs` column, the
    manifest).

14. **The execute and recover routes.** Facts: SA:207 `execute_approved_proposal (mcp-write)`, `reconcile_outcome`;
    today's `handlers.execute` (`:270-324`) and `_mark_unknown` (`:327-351`); recover jobs are closed unhandled (T22);
    the mcp-write discovery/result-schema debt is T20's (`mcp.py:182`, Plan M M1); the grant's freshness and asset
    guard are T21's. Options: T20 moves `execute` into the graph (nodes wrapping today's code) or leaves `execute`
    jobs on the handler with graph rows that T21 wires; whether T20 closes the mcp-write discovery debt (listing check
    and committed result schemas for `create_incident`) or passes it on with an erratum.

15. **Tests without a database, and live tests.** Facts: Plan H's fake harness drives handlers without a database
    (`tests/plan_h/test_worker_units.py:73-195`); `tests/plan_q/` does not exist and is not in `testpaths`; live tests
    run under `check.py --profile test`; R042 asks to "restart graph process during clarification/review"; R091 a
    grep of checkpoint blobs; R108 "durability=sync asserted"; DoD 1 "Trace shows MCP reads complete before
    drafting"; LangGraph is not locked, so whether an in-memory saver ships with 1.2.14 is not verifiable here.
    Options: an in-memory saver for unit tests vs the Postgres saver only in live tests; a process-level restart test
    (a child worker killed with the stored id surviving) vs an in-process re-instantiation; the R129 walk as a pure
    test over the table plus a graph test per row; which evidence report (e.g. `reports/graph/…`) records the live
    restart.

16. **Dependency additions.** Facts: SA:580-581 pin `langgraph 1.2.14` and `langgraph-checkpoint-postgres 3.1.2`; neither
    is in `uv.lock`; worker deps are exact pins for libraries it imports directly (`worker/pyproject.toml` comment);
    core has `psycopg[binary]>=3.3,<4` (locked 3.3.6); the transitive set and its compatibility with `langchain-core
    1.7.0` and `psycopg 3.3.6` are unknown without network; LangSmith stays off (`SESSION_STATE.md:1531-1532`).
    Options: add both pins to `ops-worker` only (the API and sweeper never import them), or the saver package to a
    migration-time location too (if Alembic runs `setup()`); verify the versions SA:580-581 name still resolve, and
    record any substitution as an erratum (AM-30 says exact pins live in `uv.lock`).

17. **Records.** Facts: R022, R038, R042, R091, R108, R114 to move from `NOT_RUN`; R129's graph half; R122 (owned by
    T09, deferred to T20); R028's note ("the model-facing path for asset data arrives with T20"); R033's note (the
    relevance criterion); the Plan Q debt list goes in `SESSION_STATE.md` before coding (R6-B7 practice);
    `docs/ARCHITECTURE.md` §3 and "Where the code will live" (`:397-406`); `README.md:20` (Orchestrator row);
    `STATUS.md:12`, `:426`; `docs/PROJECT_HISTORY.md` gets the round's problems and fixes; errata from 122; the
    `TODO(T20)` markers (§1.4) and the stale "T19 waits on the seal" records listed in the Plan P sheet §1.3. Open:
    which of these T20 closes, which it re-homes, and whether R122's owner stays T09.

---

## 6. Glossary of exact names

- **Task/requirements:** `T20` (M07, "LangGraph workflow with sync durability and stored checkpoint IDs"); `R022`,
  `R038`, `R042`, `R091`, `R108`, `R114`, `R129`. Neighbours: `T19` (done; R036, R037, R039-R041, R127, R130), `T14`
  (done; journal, wake-ups, outbox), `T16` (done; read tools, asset-sim), `T21` (R023, R057), `T22`, `T25`, `T26`
  (R035), `T28` (R058, R060), `T29`, `T30` (R065), `T36` (R069), `T38` (R021); `R028`, `R033`, `R087`, `R088`, `R107`,
  `R122`; DEV-001, DEV-002, DEV-003, DEV-013, DEV-021.
- **Spec anchors:** AM-12 graph SA:207, checkpoints SA:209-218, async SA:201; AM-16 graph router SA:377; AM-10
  SA:135-154; AM-20.2 SA:415, SA:419, SA:421, SA:434; AM-20.3 SA:451-453; AM-20.4 SA:496, SA:501; AM-20.7 SA:559-563;
  AM-30 SA:580-581; AM-70 SA:737; BUILD_SPEC §8 BS:303-342, §11 BS:419/BS:423, §17 BS:551-556; ADR-0002:23, :41-45;
  ADR-0003:15; `docs/ARCHITECTURE.md` §3 (`:119-163`).
- **Graph vocabulary (spec):** nodes `load_run`, `route_request`, `await_clarification`, `retrieve_evidence`,
  `draft_with_langchain`, `validate_and_freeze`, `await_independent_decision`, `execute_approved_proposal`,
  `reconcile_outcome`, `publish_state`; routes (`GraphRoute`) `clarify`, `retrieve`, `draft`, `answer_only`, `abstain`,
  `freeze`, `await_decision`, `execute`, `recover`, `publish`; table key `(run state, runs.intent, context resolved?,
  evidence sufficient?, validated draft kind, decision present?, attempt state)`.
- **LangGraph names (from the spec and review notes; the library is not locked):** `durability="sync"` (default
  `"async"`), `stream_mode="checkpoints"`, `aget_state`, `aget_tuple`, `Command(resume=<event_id>)`, `invoke(None)`
  with a `checkpoint_id` (forks), `interrupt()`, `is_replaying`, `_reapplies_pending_writes`, `AsyncPostgresSaver`,
  `PostgresSaver.setup()`, `BaseCheckpointSaver`, `put`, `put_writes`; source refs `pregel/_loop.py:330, 766-770,
  886-912, 920-926, 1262-1266`, `pregel/main.py:2672, 3526`, `langgraph/types.py:98-103`.
- **Worker code:** `ops_worker.handlers` (`Deps`, `investigate`, `_draft_and_freeze`, `execute`, `_mark_unknown`,
  `handle`, `abandon`, `_event`, `_fail`, `INTERRUPTED`, `NOT_ROUTED`, `ABSTAINED`, `MODEL_UNAVAILABLE`,
  `MODEL_INVALID`, `RETRIEVAL_MODE`, `QUERY_CHARS`, `BUDGET_MARGIN_SECONDS`, `EXECUTE_RETRY_SECONDS`);
  `ops_worker.main` (`_main`, `run_forever`, `run_job`, `claim`, `health_app`, `POLL_SECONDS`, `MAX_DEFERRALS`,
  `LOOP_LOCK_TIMEOUT`); `ops_worker.drafting` (`PROMPT_VERSION`, `WORKFLOW_VERSION = "investigation-v1"`,
  `DraftRequest`, `EvidenceItem`, `DraftGenerator`, `FakeDraftGenerator`, `make_generator`, `start_route`,
  `ModelUnavailable`, `ModelOutputInvalid`, `ModelStartError`); `ops_worker.ollama_drafting` (`OllamaDraftGenerator`,
  `payload`); `ops_worker.proposals` (`build_proposal`, `evidence_from_search`, `Frozen`, `EXPIRY`);
  `ops_worker.permit` (`model_permit`, `PERMIT_TTL_SECONDS = 95`); `ops_worker.heartbeat` (`Heartbeat`, `Liveness`);
  `ops_worker.mcp` (`HttpMcpCaller`, `McpCallFailed`).
- **Core code:** `ops_core.routing` (`AdmissionRoute`, `GraphRoute`, `ModelRoute`, `AdmissionFacts`, `AdmissionRule`,
  `ADMISSION_RULES`, `REPLY_RULES`, `route_admission`, `route_reply`, `RunManifest`); `ops_core.states` (`RunState`,
  `Intent`, `TRANSITIONS`, `ACTIVE_STATES`, `TERMINAL_STATES`, `WORKER_TRANSITION_TARGETS`, `require_transition`,
  `freeze_allowed`, `AnswerOnlyRun`); `ops_core.jobs` (`JobType`, `JOB_RULES`, `Server`, `dedup_key`);
  `ops_core.persistence` (`claim_next`, `acquire_lease`, `fenced`, `release_lease`, `unclaim_job`, `pull_forward`,
  `transition_run`, `append_event`, `freeze_proposal`, `mint_handle`, `revoke_handles`, `insert_run_manifest`,
  `insert_job_untargeted`, `run_row`, `set_tenant`, `assert_relation`); `ops_core.lease` (`Lease`, `LeaseLost`,
  `RELEASED`, `LOCK_FOR_SHARE`, `LOCK_FOR_UPDATE`); `ops_core.locking` (`LOCK_ORDER`); `ops_core.outcomes`
  (`EventType`, `EventSource`, `PAYLOAD_KEYS`); `ops_core.contracts` (`ModelDraft`, `StoredMessageKind`,
  `SYSTEM_MESSAGE_KINDS`); `ops_core.draft_validation.validate`; `ops_core.privileges` (`GRANTS`).
- **Database:** `app.runs.checkpoint_id` (text, worker UPDATE), `app.runs.budget_used`, `app.run_lease(run_id, owner,
  lease_until, fence)`, `app.jobs` (`jobs_type_check`), `app.drafts`, `app.run_manifests` (PK `run_id`, revision 0014),
  `app.model_permit`, `app.transitions`, `app.transition_run`, `app._transition`, `app.append_event`,
  `app._append_event`, `app.freeze_proposal`; schema `checkpoints` (absent); latest revision `0014_run_manifests`, next
  `0015`.
- **Job types / keys:** `investigate` (`run_id:revision`), `resume_input` (`run_id:clarification_event_id`), `execute`
  (`proposal_id`), `recover` (`action_id:trigger`), maintenance `name:<minute bucket>`.
- **States/events:** `QUEUED`, `RETRIEVING`, `DRAFTING`, `AWAITING_INPUT`, `ANSWERED`, `INSUFFICIENT_EVIDENCE`,
  `FAILED`, `AWAITING_APPROVAL`, `BLOCKED_REVIEW`; `run.accepted`, `tool.started`, `tool.completed`,
  `explanation.ready` (source `model_summary`), `proposal.ready`, `run.failed`, `run.insufficient_evidence`,
  `run.answered`, `clarification.requested`, `clarification.received` (payload `question_id`, `message_id`); draft
  kinds `proposal`, `answer`, `abstain` (+ `question`).
- **Sweeper:** `ops_sweeper.wakeups` (`WAKEUPS`, `job_type_case`), `ops_sweeper.leases`; settings
  `OPS_WAKEUP_GRACE_SECONDS` (60), `OPS_WAKEUP_MAX_ATTEMPTS` (10).
- **Settings:** `MODEL_MODE` (`fake` | `qwen3:8b`), `OPS_COMPUTE_BUDGET_SECONDS` (90), `OPS_LEASE_SECONDS` (30),
  `OPS_HEARTBEAT_SECONDS` (10), `OPS_WORKER_HEALTH_PORT` (8070), `PROFILE` (`dev` | `test` | `demo`).
- **Schemas:** `schemas/route.schema.json` (`graph` enum), `schemas/run-manifest.schema.json`,
  `schemas/event.schema.json` (`message` ≤2500), `schemas/model-draft.schema.json` (`question` ≤500),
  `schemas/tools/get_asset_status.input.schema.json`, `get_recent_alerts.input.schema.json`,
  `search_procedures.input.schema.json`; generator `scripts/build_schemas.py`.
- **Tests:** `tests/plan_h/test_worker_units.py` (fake harness), `tests/plan_p/test_investigate_drafting.py`,
  `tests/plan_d/test_worker.py`, `tests/plan_c/test_states.py`, `tests/plan_e/test_transitions_table.py`,
  `tests/plan_g/test_routing_admission.py`, `tests/plan_i/test_wakeups.py`, `tests/e2e/test_worker_live.py`,
  `tests/e2e/test_heartbeat_live.py`, `tests/e2e/test_wakeups_live.py`, `tests/e2e/test_admission_live.py`,
  `tests/e2e/conftest.py`; next free directory `tests/plan_q/` (not in `testpaths`).
- **Libraries:** `langgraph 1.2.14`, `langgraph-checkpoint-postgres 3.1.2` (SA:580-581, not locked); `psycopg 3.3.6`,
  `langchain-core 1.7.0`, `langchain-ollama 1.1.0`, `mcp 2.3.0` (locked).
- **Gates:** `uv run python scripts/check.py` (1629 passed, 222 skipped at `cded00b`), `… --profile test` (1830 passed,
  21 skipped), `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts` (exit 0). Next
  erratum: 122.

# Plan I inputs: T14 (gap-free event journal, wake-ups and outbox) — fact sheet

Prepared 2026-10-15 on branch `plan-i` at `643e1b7` (= `plan-h`; clean tree; read-only on the repository except this
file). Facts only, no design. Citations: `SA:<line>` = `SPEC_AMENDMENTS.md`, `BS:<line>` = `BUILD_SPEC.md` (line
numbers as of `643e1b7`); the amendments win wherever the two conflict. Repository files are cited as `path:line`.
Nothing was run against a database, Keycloak or a service for this sheet: every fact below is read from the files, and
no secret, token or `.env` value was opened.

Note on line numbers: AM-14 is SA:301–325 (sequence SA:303, event types SA:304–319, "who may assert" SA:320–324,
feedback SA:325); AM-12's lock order is SA:188 (asset lock SA:189, "every transaction" SA:190, FOR UPDATE rule
SA:191), "writes without a lease" SA:186; AM-15's job table SA:340–346 (maintenance row SA:346); AM-20.1's sweeper row
SA:399; AM-20.2 rows: `runs` SA:415, `jobs` SA:419, `events` SA:426, `outbox` SA:427, notes SA:437–442; AM-20.3 rows:
`create_run` SA:450, `transition_run` SA:451, `append_event` SA:452, `freeze_proposal` SA:453, `record_decision`
SA:454, `create_revision` SA:455, `expire_proposal` SA:457, `request_cancel` SA:458, `grant_execution` SA:462,
`mark_sent` SA:463, `record_outcome` SA:464, `mark_unknown` SA:467, `escalate_run` SA:468, `resolve_escalation`
SA:469, `reclaim_leases` SA:471; AM-20.4 SA:492–506 (dedup table SA:498–504); AM-20.5 SA:508–524 (sweeper policy
SA:520, no-RLS list SA:523). BUILD_SPEC §8 "Avoid lost wakeups" is BS:340; §15 is BS:508–526 (event contract
BS:514–520, outbox BS:522–524, Slack BS:526); §17 BS:540–566; §18 retention BS:578. `handoff/acceptance-matrix.json`
names the owners field `owning_tasks`.

---

## 1. T14 verbatim, its acceptance-matrix rows, and related rows/tasks

### 1.1 T14 (`handoff/tasks.json:639-663`)

- **id/milestone/title:** `T14`, `M04` ("Run leases, fencing, event journal and outbox", `:55-63`, task_ids `T13`,
  `T14`), "Gap-free event journal, wake-ups and outbox". `status: "PLANNED"`, `external_approval_required: false`.
- **instructions:** "runs.next_event_seq under the runs lock; wake-up jobs committed with user events; sweeper;
  transactional outbox with leased delivery loop (no external channel)."
- **depends_on:** `["T13", "T12"]`, both `DONE`. T14, T15 and T17 are the `PLANNED` tasks whose dependencies are all
  done; T14 comes first in the file (`:640`, T15 `:665`).
- **requirement_ids:** `R024, R089`.
- **definition_of_done:**
  1. "Concurrent writers yield gap-free commit-ordered sequences."
  2. "Outbox rows deduplicated and leased; delivery result recorded separately."
- **review_notes** (all three, verbatim):
  1. "Jobs carry dedup_key UNIQUE per AM-20.4; recover jobs never created by either MCP server."
  2. "append_event enforces payload rules inside the function (no status field from api/worker on tool.completed);
     action.granted emitted by grant_execution; action.redispatched by mark_sent when attempt_no > 1; deliver_outbox
     is a job type."
  3. "The sweeper iterates tenants and sets app.tenant_id per tenant for expiry, outbox delivery and deadline
     escalation; sweeper_all covers memberships and jobs only (AM-20.5, 1.3.6)."
- `handoff/BUILD_BACKLOG.md:85-88` repeats the instructions, requirements and notes. `BUILD_BACKLOG.md:84` records
  Plan H as "done in c5eeb89..6c9e8f8", while T13's close-out note in `tasks.json:636` says "c5eeb89..06e961a" (the
  final-review fix `06e961a` is not in the backlog's range).
- T13's close-out note (`tasks.json:636`) defers "wake-ups -> T14". T13's review note 6 (`tasks.json:634`): "the outbox
  appends notification.failed in a separate transaction (AM-12)".

### 1.2 Acceptance-matrix rows owned by T14 (`handoff/acceptance-matrix.json`)

Exactly two rows list `T14` in `owning_tasks`; both are `blocking_for_v1: true`.

- **R024 (:427)** — M04 / durability; requirement: "Notification intent is transactional and deduplicated";
  expected_evidence: "Fail delivery after state commit; result remains recorded and dedup key preserves intent.";
  owners: T14; suggested_test: `tests/acceptance/test_r024_notification_intent_is_transactional_and_dedupli.py`;
  `implementation_status: NOT_IMPLEMENTED_OR_NOT_TARGET_VERIFIED`, `evidence_status: NOT_RUN`, no evidence paths.
- **R089 (:1446)** — M04 / events, `source: SPEC_AMENDMENTS.md`; requirement: "Per-run event sequences are gap-free
  and commit-ordered"; expected_evidence: "Concurrent writers; SSE replay never skips."; owners: T14; suggested_test:
  `tests/acceptance/test_r089_per_run_event_sequences_are_gap_free_and_commit_.py`; `NOT_IMPLEMENTED_…` / `NOT_RUN`.
- `handoff/ACCEPTANCE.md:30` carries R024 as M04. R089's evidence names "SSE replay", and SSE is T27's (§1.3).
- `tests/acceptance/` does not exist; `pyproject.toml:48-51` `testpaths` lists `tests/plan_a` … `tests/plan_h` and
  `tests/e2e` (no `tests/plan_i`).

### 1.3 Tasks that depend on T14, and other rows that touch events, wake-ups or the outbox

- **T20** (`tasks.json:836`) depends_on `["T19", "T14", "T16"]`: "…runs.checkpoint_id stored under fence and used on
  resume; idempotent pre-interrupt logic; ID-only interrupts; human waits release the lease; ANSWERED path." Review
  note: "…prefer Command(resume) when a resume event exists; test two crashes in a row." Owns R022 ("Human waits release
  workers and transactions") and R042 ("Restart graph process during clarification/review and resume from committed
  event under same run").
- **T27** (`tasks.json:1049`) depends_on `["T26", "T14"]`: "Last-Event-ID replay; heartbeats; cursor-reset snapshot;
  access recheck per frame; identity change closes stream; ESCALATED runs stay live; add SSE scenario cards." DoD:
  "Reconnect replays without gaps or duplicates." Owns R053 (:868, "SSE reconnect replays safely without duplicate
  work" — "Disconnect, receive events, reconnect after cursor, dedup rendering; expired cursor yields explicit reset")
  and R054 ("Streaming access follows session and source revocation").
- No other task lists T14 in `depends_on`. Rows and tasks outside T14 that name the same mechanisms:
  - **R023** (:412, **M08**, owner **T21**): "Reply/approval wakeups cannot be lost" — "Inject crash between
    decision/event/checkpoint/job acknowledgement; sweeper resumes exactly the accepted event." T21's DoD 3: "Lost-wakeup
    crash between decision commit and processing recovered by the sweeper." `handoff/ACCEPTANCE.md:29` lists it as
    "**R023 / M04**"; SA:725 re-homed it ("R023 → decisions").
  - **R061** (:988, M11, T29): "Model/MCP/DB/outbox fail independently; controlled states, no invented success…".
  - **R097** (:1578, M09, T24/T27/T29/T32): the development cards. Card **DEV-029**
    (`evals/handoff-development/scenarios.jsonl:29`): slug `notification-failure`, prompt "Tell me when the incident is
    created.", harness_steps `["incident succeeds", "outbox delivery fails"]`, requirement_ids `["R024", "R061"]`,
    expected_outcome `SUCCEEDED_NOTIFICATION_FAILED`, oracle "Do not relabel incident as failed or resend incident
    write." T24's review note (`tasks.json:985`): "DEV-029 needs a fault-injectable outbox sink."
  - **R079** (:1260, M15, T39): Slack, "one logical action, delivery separate". T39 (`tasks.json:1290`, M15,
    `external_approval_required: true`): "Verified callbacks, identity mapping, outbox delivery, same review/execute
    policy."
  - **R128** (:2133, T09, `RECORDED_LOCALLY_LIVE`): "Direct INSERT into events/… … are denied for api, worker and
    sweeper".
  - **R083** (:1325, T45, `RECORDED_LOCALLY`): "Schemas forbid model-asserted outcomes…: model_summary status,
    action.confirmed without receipt…".
  - **R095** (:1542, T22): "CONFLICT and escalation deadline reach ESCALATED" (the sweeper's deadline escalation).
- `reference/TRACEABILITY.md:26` maps `test_control.py::test_cross_team_events_denied` to "tests/acceptance R053
  authorized event history", owning task **T14** (R053's matrix owner is T27); `:51` maps `test_event_cursor` to
  "tests/acceptance R089 gap-free sequence", owning task T14. The reference test (`reference/tests/test_control.py:186-191`)
  reads events after a cursor and asserts every id is greater than the cursor.

---

## 2. Spec passages that bind T14

### 2.1 AM-14 (SA:301–325), verbatim

- SA:303: "**Sequence numbers.** The per-run `sequence` comes from `runs.next_event_seq`, incremented under the `runs`
  row lock (lock order AM-12) in the same transaction as the insert. That makes it gap-free and commit-ordered (R089)."
- SA:304–319: "**Event types:** §15 plus:" `clarification.received`, `proposal.revised`, `review.blocked`,
  `run.answered`, `run.insufficient_evidence`, `run.rejected`, "`action.granted` (emitted by `grant_execution`)",
  "`action.redispatched` (emitted by `mark_sent` when `attempt_no > 1`)", "`action.failed` (with `reason`)",
  `action.conflict`, `run.escalated`, `run.abandoned_unverified`, "`action.late_evidence` (status = the run's terminal
  status; `outcome` field carries the destination result)", `feedback.recorded`, `explanation.ready`.
- SA:320–324: "**Who may assert outcomes.** Only `source ∈ {application, destination}` may emit `action.*`, `run.*` or
  `review.*`. `model_summary` may emit only `explanation.ready`, with no status field. `action.confirmed` requires a
  receipt and status `SUCCEEDED`. Enforced in schema (`if/then`) and in code."
- SA:325: "**Feedback** (`POST /runs/{id}/feedback`) stores classified feedback and emits `feedback.recorded`. It has
  no runtime effect (R113)."

### 2.2 AM-12 lock order and writes without a lease (SA:186–191)

- SA:186: "**Writes without a lease:** API and sweeper mutations (decision, cancel, revision, expiry) hold no lease.
  They serialize with `SELECT … FROM runs … FOR UPDATE` plus `expected_version`."
- SA:188: "**Lock order:** `asset guard advisory lock → run_lease → runs → messages → proposals → decisions →
  memberships → execution_grant → action_attempt → operator_resolutions → events → outbox`. Idempotency rows are written
  last, before commit. The outbox delivery loop records results in its own transaction and appends any
  `notification.failed` event in a **separate** transaction, so it never takes `runs` after `outbox`."
- SA:190: "Every transaction and definer function follows this order."
- SA:173: "`run_lease(run_id PK, owner, lease_until, fence bigint)`. Jobs are wake-ups only."
- SA:151 (AM-10): "`state_version` increases **only on state transitions**. Appending events, heartbeats and
  attempt-state changes do not bump it, so user cancels and decisions don't get spurious 409s".
- SA:135 (AM-10): "AWAITING_INPUT | → QUEUED by the worker's `resume_input` job through `transition_run`, after the
  clarification event is committed". SA:122: "SSE streams and the UI keep ESCALATED runs live."

### 2.3 AM-15 and AM-20.4: job types, creators and dedup keys

- SA:338: "Every job has exactly one `type`. … `investigate`/`resume_input` handles are accepted only by mcp-read;
  `execute`/`recover` handles only by mcp-write (R131)."
- SA:343: `resume_input` | "API with a clarification reply" | "Resume after a clarification" | read tools |
  "AWAITING_INPUT → QUEUED". SA:344: `execute` | "API with an approving decision". SA:345: `recover` | "Created by
  `mark_unknown` (worker timeout path); the worker after a `cancelled`/`expired` tool result; `reclaim_leases`
  (sweeper). Never by either MCP server."
- SA:346: "`expire_proposals`, `sync_memberships`, `sweep_wakeups`, `deliver_outbox` | Scheduler (sweeper role) |
  Maintenance | none | n/a (no run lease)".
- SA:348: "…No job is created by either MCP server."
- SA:494: "`jobs(id, type, run_id, dedup_key UNIQUE, available_at, claimed_by, claimed_at, attempts, done_at)`."
- SA:500–504 (Inserted by / dedup_key): `investigate` — "`api` (admission), `create_revision`" — `run_id:revision`;
  `resume_input` — `api` — `run_id:clarification_event_id`; `execute` — `record_decision` — `proposal_id`; `recover` —
  "`mark_unknown`, `worker` (after a `cancelled`/`expired` result), `reclaim_leases`" — "`action_id:trigger` where
  trigger ∈ {`timeout`, `cancel`, `deadline`, `sweep:<bucket>`}"; maintenance types — "`sweeper` scheduler" —
  "`name:<minute bucket>`".
- SA:506: `recover` jobs on ESCALATED / ABANDONED_UNVERIFIED runs: "every 5 minutes for the first hour, then hourly,
  with a cap of 48 attempts".

### 2.4 AM-20.1 and AM-20.2 rows (SA:399, SA:410–442)

- SA:399: "`sweeper` | yes | Scheduler process (expiry, membership sync, wake-up sweep, outbox delivery); holds the
  Keycloak `view-users` service account for the membership sync".

| Table (SA line) | `api` | `worker` | `sweeper` | `app_definer` | others |
|---|---|---|---|---|---|
| `runs` (SA:415) | sel, upd(`cancel_requested`, `cancel_requested_at`) | sel, upd(`checkpoint_id`, `budget_used`) | sel | ins, sel, upd(`state`, `state_version`, `reason`, `active_proposal_id`, `next_event_seq`, `slot_held`, `supersedes_run_id`) | — |
| `jobs` (SA:419) | ins (`resume_input` only) | sel, ins, upd(`claimed_by`, `claimed_at`, `done_at`, `attempts`) | sel, ins, upd(same) | ins, sel | — |
| `events` (SA:426) | sel | sel | sel | ins, sel | — |
| `outbox` (SA:427) | ins | ins | sel, upd(`leased_until`, `attempts`, `delivered_at`, `result`) | ins | — |
| `tenants`, `memberships` (SA:412) | sel | sel | sel, upd(`active`, `permission_version`, `synced_at`) | sel | — |

- SA:437: "`mcp_read`, `mcp_exec` and `operator` have **no table grants**".
- SA:439: "`runs.next_event_seq` is written only inside `append_event` (the worker's former column grant is removed,
  so the gap-free sequence cannot be bypassed) [R7]."
- SA:387 (AM-20 principle 1): "Runtime roles never UPDATE `runs.state`, never INSERT into `events`, `decisions`,
  `proposals`, `execution_grant` or `action_attempt_state` directly." SA:388 (principle 2): "Audit tables are
  append-only, so "state" is the latest row, never an UPDATE."
- AM-20.2 gives `app_definer` `ins` only on `outbox` (no `sel`), and gives no role DELETE on `outbox`, `events` or
  `jobs`.

### 2.5 AM-20.3 rows that write events, jobs or the outbox (SA:444–474)

- Preamble SA:446: every function "first resolves `tenant_id` through `run_directory` (or the handle) and sets
  `app.tenant_id` with `set_config(name, value, true)` … takes locks in the AM-12 order, and raises
  `authority_violation` when `session_user` is not an allowed caller."
- **`append_event(run_id, type, payload)`** (SA:452) — callers `api`, `worker`, `sweeper`; locks "`runs` FOR UPDATE
  (for `next_event_seq`)"; effect "Inserts an event with `source` derived from `session_user` (`api`/`worker`/`sweeper`
  → `application`; `worker` may pass `source=model_summary` only for `explanation.ready`). **Refuses** `action.*`,
  `run.*` and `review.*` types from these callers; those are emitted only by the functions below"; event "the event".
- Event column of the other rows: `create_run` (SA:450) `run.accepted`; `transition_run` (SA:451) "the matching `run.*`
  event via `append_event`"; `freeze_proposal` (SA:453) `proposal.ready` or `review.blocked`; `record_decision`
  (SA:454) `approval.recorded` / `run.rejected` ("on approval inserts the `execute` job (dedup `proposal_id`)");
  `create_revision` (SA:455) `proposal.revised` (inserts an `investigate` job, dedup `run_id:revision+1`);
  `create_manual_proposal` (SA:456) `proposal.ready`; `expire_proposal` (SA:457; callers "`sweeper`; also invoked
  internally by `record_decision`/`grant_execution`"; locks "`runs` FOR UPDATE → `proposals` FOR SHARE") `review.blocked`;
  `request_cancel` (SA:458) `run.cancelled` or none; `grant_execution` (SA:462) "`action.granted` (new type) or
  `review.blocked`"; `mark_sent` (SA:463) "`action.dispatched`, or `action.redispatched` when `attempt_no > 1`";
  `record_outcome` (SA:464; locks "`run_lease` FOR SHARE → `runs` FOR UPDATE → `action_attempt_state` → `events`")
  "`action.confirmed` / `action.failed` / `action.conflict` / `action.late_evidence`, all with `source=destination`";
  `mark_unknown` (SA:467) `action.uncertain` ("inserts a `recover` job"); `escalate_run` (SA:468; callers `worker`,
  `sweeper`; reason ∈ {`conflict`, `escalation_deadline`}) `run.escalated`; `resolve_escalation` (SA:469) 
  `run.abandoned_unverified`; `sync_memberships`, `reclaim_leases`, `revoke_handles` none.
- **`reclaim_leases()`** (SA:471) — `sweeper`; "Expired leases become reclaimable; stale `model_permit` released; lost
  wake-ups re-enqueued (dedup keys)"; event none. (Erratum 49 narrows this; §4.)
- No AM-20.3 row names `notification.failed`, `outbox`, `sweep_wakeups` or `deliver_outbox`; no row inserts into
  `outbox`.

### 2.6 AM-20.5 RLS (SA:508–524)

- SA:510: the tenant tables with `ENABLE`/`FORCE ROW LEVEL SECURITY` include `jobs`, `events` and `outbox`.
- SA:512–517: `tenant_isolation … FOR ALL TO api, worker, sweeper, app_definer USING (tenant_id =
  current_setting('app.tenant_id', true)::uuid) WITH CHECK (…)`.
- SA:520: "`memberships` and `jobs` carry one extra policy, `sweeper_all FOR ALL TO sweeper USING (true)`, for the
  membership sync and the wake-up sweep. For every other table the sweeper **iterates `tenants`** (no RLS) and sets
  `app.tenant_id` per tenant before `expire_proposal`, `deliver_outbox` and deadline escalation; it never needs a
  cross-tenant view of those tables [R8-R4]. These are the only policies besides `tenant_isolation`."
- SA:523: `tenants` (and `run_directory`, `run_lease`, …) have no RLS.

### 2.7 AM-02 and AM-80

- SA:95–101: "V1 is M00–M14 … The optional milestone M15 holds: … Slack (R079); cloud (R080)."
- SA:760 (AM-80 `event.schema.json`): "Add `ESCALATED` and `ABANDONED_UNVERIFIED` and the AM-14 event types; payload
  `reason` and `outcome`; `action.confirmed` requires a receipt and SUCCEEDED; `action.late_evidence` requires
  `outcome` plus a receipt or tombstone; source rules". SA:771: "New type `action.granted`; `source=destination` only
  for `action.confirmed/failed/conflict/late_evidence`".

### 2.8 BUILD_SPEC

- BS:54 (§2 optional after v1): "Opt-in Slack notifications/decisions reusing the same identity and control rules".
  BS:69: "PostgreSQL for app data, jobs, checkpoints, governed text, embeddings and outbox". BS:76: "| Notifications |
  Transactional outbox and a separate delivery loop. | At-least-once dispatch can occur; external delivery is not
  universally exactly-once. |"
- BS:150–151 (deployment diagram): `PG --> Outbox[Outbox worker]`, `Outbox -. optional .-> Slack[Slack]`. BS:196:
  `postgres/ # repositories, jobs, leases, outbox`; BS:199: `notifications/ # optional Slack`.
- BS:239 (§6): "| event | tenant_id, run_id, sequence, type, producer, timestamp, bounded redacted payload; unique
  `(run_id, sequence)` |". BS:240: "| outbox | event/recipient/channel, dedup key, payload reference, attempts, lease,
  next delivery time, result |".
- BS:273: "`POST /api/v1/runs/{id}/clarifications` | Bind reply to outstanding question ID and expected version; commit
  before resume enqueue". BS:275: "`POST /api/v1/proposals/{id}/decisions` | … accepted decision plus wake-up job in one
  transaction". BS:277: "`GET /api/v1/runs/{id}/events` | Bounded authorized cursor history". BS:278: "`GET
  /api/v1/runs/{id}/stream` | Authorized SSE replay/live projection with revalidation".
- BS:334 (§8): "Admission transaction: message + run + job + initial event. … `SKIP LOCKED` is appropriate for
  queue-like consumers, not proof of exactly-once work."
- BS:340 (§8), verbatim: "Avoid lost wakeups: user replies/approvals commit with a unique resume job. Mark their
  consumption only after processing reaches a durable acknowledged state. A sweeper compares pending user events, jobs,
  checkpoints and authoritative run state, and re-enqueues a deduplicated wake-up if a crash occurred between them.
  Replayed nodes reread current state and cannot re-freeze a different approved payload. No atomic cross-checkpointer
  transaction is assumed unless actually implemented and tested."
- BS:468 (§13): "The API commits the decision and a deduplicated wake-up job atomically. It does not execute a tool in
  an HTTP approval handler."
- BS:514 (§15): "Persist ordered events with source (`application`, `destination`, or `model_summary`),
  run/conversation IDs, monotonically increasing per-run sequence, event ID, timestamp, type and bounded safe payload.
  Event types include `run.accepted`, `clarification.requested`, `tool.started`, `tool.completed`, `proposal.ready`,
  `approval.recorded`, `action.dispatched`, `action.uncertain`, `action.confirmed`, `run.failed`, `run.cancelled`,
  `notification.failed` and `feedback.recorded`."
- BS:516: "Only application/destination producers may assert execution status. Use templates for infrastructure
  failure messages so reporting does not depend on a working LLM. Do not stream raw graph dictionaries, internal
  service headers or private reasoning."
- BS:518: "…Support `Last-Event-ID`/authorized cursor replay, duplicate rendering suppression, heartbeat comments,
  disconnect detection and backpressure. … Proposed limits: 200-event page, 1 MiB buffered data per stream, heartbeat
  every 15 seconds, replay cursor retained 30 days in the synthetic profile. If a cursor has expired, return a current
  authorized snapshot and explicit cursor reset; never imply complete replay."
- BS:524 (§15 "Notification outbox"), verbatim: "Write notification intent in the same transaction as the event that
  requires it. Delivery workers claim outbox rows with leases, resolve recipients from approved mappings, send, and
  record delivery results independently from run success. Use bounded retry/jitter and dead-letter/operator
  visibility. Redact message content when the channel is not approved for that classification. A provider timeout may
  yield duplicate visible notifications; record the limitation unless its destination supplies deduplication
  guarantees."
- BS:526: "Slack is opt-in and after v1. … Offline mode has no Slack egress."
- §17 (BS:542 "All numeric limits below are **starting project defaults** … Put them in validated configuration and
  write boundary tests."): BS:550 "Queued work | 100 total initially; bounded tenant quotas; reject clearly when full";
  BS:557 "Lease / heartbeat | 30-second lease / 10-second heartbeat, database clock"; BS:560 "SSE | 15-second
  heartbeat; authorization recheck at most 30 seconds apart; bounded buffer/history". BS:562: "Retry only transient
  permitted reads with capped exponential backoff/jitter. … Circuit-break repeated dependency failures". BS:564:
  "…Notification failure: keep result in the web interface. Hosted fallback: never automatic."
- §18: BS:574 dashboards include "queue depth and oldest job age, … notification failures". BS:576: "Audit events are
  authoritative application records and must not be sampling-dependent." BS:578: "Proposed local retention: 30 days
  operational event replay; 7 days detailed traces; source/proposal/receipt audit records retained through the demo's
  explicit teardown. … Never silently delete required deduplication receipts."
- BS:588 (§19): "Real PostgreSQL tests: … concurrent decisions, job leases/fencing, checkpoint writes, outbox/wakeup
  crash windows." BS:595: "…Fault injection must target the real transaction boundaries being claimed."
- BS:648 (§22 egress table): "| Outbox | app DB; explicitly opted-in notification endpoint only |".
- BS:681 (§24): "Database outage | … recover lease/outbox safely". BS:685: "Notification outage | Result remains
  visible; bounded outbox retry; delivery status separate from action outcome".
- BS:705 (§25): "M04 — Jobs and persistence | Leases, heartbeat/fencing, checkpoint adapter, event journal, outbox and
  wake-up sweeper | Concurrent stale-worker/checkpoint denial and crash-window recovery".
- BS:730 (§26): the coding AI must not "send notifications to real people" without explicit authorization.

---

## 3. The tree as it is (branch `plan-i`, `643e1b7`)

### 3.1 Every "T14" debt line outside uv.lock, reference/, docs/reviews, docs/superpowers (`git grep -n T14`)

Code:

| Where | Text (verbatim) | What it asks for |
|---|---|---|
| `core/src/ops_core/locking.py:47` | `"outbox",  # created by T14` | the `outbox` table at its lock-order place |
| `core/src/ops_core/locking.py:55` | `NOT_YET_CREATED: Final = frozenset({"operator_resolutions", "outbox"})` (no "T14" text; the outbox entry) | drop `outbox` from the set once it exists (`tests/plan_h/test_locking.py:51-52` fails otherwise) |
| `core/src/ops_core/outcomes.py:278` | "TODO(T14): append_event and the event stream validate through this model; until then only the tests call it." | validation of writes and reads through `outcomes.Event` |
| `core/src/ops_core/persistence.py:698` | "TODO(T14): wake-ups instead of polling." (`claim_next` docstring) | a wake-up mechanism replacing the poll |
| `core/src/ops_core/privileges.py:7` | "the owners of later tables (outbox → T14, …) add their rows" | the `outbox` grant row |
| `sweeper/src/ops_sweeper/leases.py:10` | "Nothing else: no `recover` job (T22), no model permit work …, no lost wake-ups (T14)." | the lost-wake-up re-enqueue |
| `sweeper/src/ops_sweeper/main.py:11` | "TODO(T14/T21): wake-ups, the outbox, proposal expiry." | `sweep_wakeups`, `deliver_outbox` (and T21's expiry) |
| `sweeper/README.md:23` | "Wake-ups, the outbox and proposal expiry: T14/T21." | same |

Status documents (verbatim or near-verbatim):

- `SESSION_STATE.md:5`: "Next is the earliest dependency-satisfied task … after T13 (T14: gap-free event journal,
  wake-ups and the outbox; T15 also became unblocked)." `:633` repeats it.
- `:144` (Plan C design note): "`outcomes.Event` is the minimal envelope the event schema requires (envelope fields plus
  `event_rules_ok`); T14 owns its evolution."
- `:156` (Plan D shortcuts): "polling worker without reclaim (T13/T14)".
- `:164` (Plan D open items): "event sequence gaps are documented, not prevented (T14)".
- `:299` (Plan G open items): `_idempotent`'s "not reusable yet" refusal … "the client is told to use a new key for a
  key that just became reusable (harmless) -> T14/T28 polish".
- `:390` (Plan H, fate of earlier debt): "wake-ups and per-tenant polling → T14".
- Walking-skeleton debt: `:428` "no idempotency keys, outbox or `next_event_seq` lock → T14;"; `:437` "the worker claims
  jobs with `FOR UPDATE SKIP LOCKED` and polls; no wake-ups, no outbox, no reclaim of a job whose handler crashed …
  → T13/T14;".
- Plan E debt: `:453` "the worker polls per tenant (one claim attempt per tenant per poll) → T13 wake-ups;"; `:461`
  "`outbox`, `feedback`, `idempotency_request`, `operator_resolutions`, `documents`/`chunks`/`embeddings`,
  `model_permit` are absent, so their AM-20.2 rows are not yet in the grant matrix → T14/T12/T22/T17/T13;".
- Plan F debt: `:472` "the sweeper runs `sync_memberships` and the expiry purges only; `expire_proposals`,
  `sweep_wakeups`, `deliver_outbox` and lease reclaim → T13/T14/T21;"; `:477` "the sweeper inserts one
  `sync_memberships` job row per minute and holds no DELETE on `jobs`, so done maintenance rows accumulate; the
  sweeper's purge of finished jobs (an AM-20.2 cell for `sweeper` `del` on `jobs`, or a definer) → T14;".
- Plan H debt (owned by T14): `:516` "the reclaim inserts no `recover` job and lost wake-ups are not re-enqueued → T22
  (recover), T14 (wake-ups);"; `:517-518` "a deferred job waits for the busy lease's `lease_until` even when the holder
  releases early (no wake-up on release) → T14;"; `:538` "the worker still polls every 0.5 s and claims per tenant → T14
  (wake-ups);".
- `STATUS.md:130` (Plan F): "the purge of finished maintenance jobs -> T14"; `STATUS.md:190` (Plan H): "wake-ups ->
  T14".
- `tests/` and `docs/ARCHITECTURE.md` contain no "T14" text.

### 3.2 The `events` table and `runs.next_event_seq`

- `migrations/app/versions/0001_walking_skeleton.py:197-208`: `CREATE TABLE app.events (event_id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL, conversation_id uuid NOT NULL, run_id uuid NOT NULL REFERENCES app.runs (run_id), sequence
  integer NOT NULL, type text NOT NULL, occurred_at timestamptz NOT NULL, source text NOT NULL CHECK (source IN
  ('application', 'destination', 'model_summary')), payload jsonb NOT NULL, UNIQUE (run_id, sequence))`. No CHECK on
  `type`; no index besides the PK and the unique pair (the only `CREATE INDEX` statements in `migrations/app` are on
  `runs`, `jobs`, `sessions` and `idempotency_request`). Every event row has a run (`run_id NOT NULL`).
- `0002_roles_grants_rls.py:203`: `ADD COLUMN next_event_seq integer NOT NULL DEFAULT 0` on `runs`; `:210` backfills it
  with `COALESCE((SELECT max(e.sequence) FROM app.events e WHERE e.run_id = r.run_id), 0)`; `:299-300` replaces the FK
  with `events_tenant_run_fkey FOREIGN KEY (tenant_id, run_id) REFERENCES app.runs (tenant_id, run_id)`.
- Grants: `privileges.py:129` `"events": {"api": _S, "worker": _S, "sweeper": _S, DEFINER_ROLE: _SI}`; `runs`
  `next_event_seq` is an `app_definer` UPDATE column only (`privileges.py:92-104`). `events` is in `RLS_TABLES`
  (`:148`) and `AUDIT_TABLES` (`:164`). R128's live test denies direct INSERT (`tests/e2e/test_roles_live.py:131`).
- `create_run` inserts the run with `next_event_seq` 0 (`0003:289-291`) and then appends `run.accepted` (`0003:313`), so
  every run's first event is sequence 1 (`tests/e2e/test_definers_run_path_live.py:111`: `next_event_seq == 1`).

### 3.3 `_append_event` and `append_event` (revision 0003; neither is re-created by 0004–0007)

- **`app._append_event(p_tenant_id, p_run_id, p_type, p_source, p_payload)`** (`0003:104-190`), a helper with
  `HELPER_HEADER` (no `SECURITY DEFINER`, no tenant attribute; it runs inside the caller's tenant setting), owner
  `app_definer`, granted to nobody (`privileges.HELPER_FUNCTIONS`, `privileges.py:198`). In order:
  1. payload must be a JSON object (`:117-119`, OC006 "payload must be an object");
  2. type must be in the frozen allowlist `EVENT_TYPES_0003` (`0003:32-60`, the 27 types; `:121-123`, "unknown type");
  3. `model_summary`: only `explanation.ready`, `message` a non-empty string, keys ⊆ {`message`, `evidence_refs`},
     refs non-empty strings (`:124-133`); `destination`: only the four destination types (`:134-137`); `application`:
     never the four destination types (`:138-142`); any other source refused (`:143-145`);
  4. `outcome`/`receipt`/`tombstone` keys refused on every type but `action.confirmed`, `action.failed`,
     `action.late_evidence` (`:146-148`);
  5. `action.confirmed`: `status = 'SUCCEEDED'`, no tombstone, receipt object with string `receipt_id`, `incident_id`,
     `committed_at` (`:149-156`); tombstone key shape (`:157-162`); `action.late_evidence` outcome/proof pairing
     (`:163-170`); `action.failed` reason ∈ {`aborted_no_commit`, `cancelled_before_send`, `rejected`, `expired`} and no
     receipt (`:171-174`);
  6. sequence (`:175-187`), verbatim: "-- The runs row lock serialises the counter (SA:303, R089); the tenant is already
     set, so RLS admits the row." `SELECT * INTO v_run FROM runs WHERE runs.run_id = p_run_id FOR UPDATE;` (`:176`),
     OC002 if absent, `UPDATE runs SET next_event_seq = v_run.next_event_seq + 1` (`:180`), `event_id :=
     gen_random_uuid()`, `sequence := v_run.next_event_seq + 1` (`:182`), `occurred_at := date_trunc('second',
     app.current_time())` (`:183`), then `INSERT INTO events (…)` with `conversation_id` copied from the run (`:184-185`).
  It returns `(event_id uuid, sequence integer, occurred_at timestamptz)`.
- The counter UPDATE and the INSERT run in the caller's transaction and the `runs` row lock is held to its end; nothing
  else in the repository writes `next_event_seq` or `events` (the only `INSERT INTO events` is `0003:184`, apart from the
  superuser test seed at `tests/e2e/test_migrations_and_persistence.py:260`).
- No rule in `_append_event` concerns the `status` key except for `action.confirmed`; no payload size bound exists.
- **`app.append_event(p_run_id, p_type, p_payload, p_source)`** (`0003:356-380`, `SECURITY DEFINER`): `_authority`
  with `ARRAY['api', 'worker', 'sweeper']` (`:364`); `_tenant_of_run` (`:365`, `run_directory` → `set_config`); refuses
  OC006 "reserved type" for `run.%`, `action.%`, `review.%`, `proposal.%`, `approval.%` and `clarification.requested`
  (`:366-372`; the comment: "SA:452 names the first three; ruling 5 closes the rest"); `v_source := coalesce(p_source,
  'application')` and refuses any source but `application`, except `model_summary` when `session_user = 'worker'`
  (`:373-375`); then `RETURN QUERY SELECT * FROM app._append_event(…)` (`:376`). EXECUTE granted to exactly `api`,
  `worker`, `sweeper` (`0003:427`; `privileges.py:178`). Its signature carries a fourth argument (`source`) beyond
  SA:452's three (erratum 13).
- The types left to `append_event` callers are therefore `tool.started`, `tool.completed`, `notification.failed`,
  `feedback.recorded`, `clarification.received`, `explanation.ready` (worker, `model_summary`).
- Python twin: `ops_core.outcomes.event_rules_ok` (`core/src/ops_core/outcomes.py:203-268`) mirrors the source and
  evidence rules; like the SQL, it checks `status` only for `action.confirmed` (`:241-243`).
- Python wrapper: `persistence.append_event(conn, *, run_id, type, payload, source=APPLICATION) -> Appended`
  (`core/src/ops_core/persistence.py:267-281`): `SELECT * FROM app.append_event(%s, %s, %s, %s)`; returns `event_id`,
  `sequence`, `occurred_at`. It does not call `event_rules_ok` or `outcomes.Event`.

### 3.4 Every event writer today (function → event, caller role, locks before the insert)

| Writer (current body) | Event(s) | Caller role | Locks taken before `_append_event` |
|---|---|---|---|
| `create_run` (`0003:238-319`) | `run.accepted` (`:313`) | api | slot index on INSERT runs; INSERT jobs `investigate` (`:311-312`) precedes the event |
| `_transition` (`0003:192-235`) | its `p_event` when not NULL (`:227-230`) | via the definers | `runs` FOR UPDATE (`:204`) |
| `transition_run` (`0003:322-353`) | `run.failed`, `run.insufficient_evidence`, `run.answered`, `clarification.requested` (`:343-348`); QUEUED→RETRIEVING, RETRIEVING→DRAFTING and AWAITING_INPUT→QUEUED emit none | worker | `runs` FOR UPDATE (`:339`); the worker's unit already holds `run_lease` FOR SHARE (`persistence.fenced`) |
| `append_event` (`0003:356-380`) | the six open types | api, worker, sweeper | `runs` FOR UPDATE inside `_append_event` |
| `freeze_proposal` (`0004:108-167`) | `proposal.ready` (`:160-161`); never `review.blocked` (TODO(T21) `:159`) | worker | `runs` FOR UPDATE (`:123`) |
| `record_decision` (`0004:171-235`) | `approval.recorded` (`:225-226`) / `run.rejected` (`:229-230`) | api | `runs` FOR UPDATE (`:197`); INSERT `decisions`, then INSERT `jobs` `execute` with `ON CONFLICT (dedup_key) DO NOTHING` (`:221-223`) before the transition |
| `grant_execution` (live body `0005:82-154`, comment-only re-creation `0007:177-181`) | `action.granted` with `{action_id, proposal_id}` (`0005:149-150`); never `review.blocked` | mcp_exec | `run_lease` FOR SHARE in `_resolve_handle` (`0007:145`), `runs` FOR UPDATE (`0005:97`) |
| `mark_sent(raw_handle, action_id)` (`0007:183-225`) | `action.dispatched`, or `action.redispatched` when `v_latest.attempt_no > 1` (`0007:218-220`); none on `cancelled`/`resolved`/`already_sent` | mcp_exec | `run_lease` FOR SHARE, `runs` FOR UPDATE (`:200`, comment "serialises the seq (SA:462)") |
| `record_outcome(raw_handle, …)` (`0007:227-314`) | `action.late_evidence` (`:290`) or `action.confirmed`/`action.failed`/`action.conflict` (`:298-308`), `source=destination`; its own `_transition` passes no event (`:284`) | mcp_exec | `run_lease` FOR SHARE, `runs` FOR UPDATE (`:247`) |
| `mark_unknown(run_id, fence)` (`0007:316-368`) | `action.uncertain` with `{action_id}` (`:357-358`), then INSERT `recover` job `<action_id>:timeout` `ON CONFLICT (dedup_key) DO NOTHING` (`:359-362`) | worker | `run_lease` FOR UPDATE (`:330`), `runs` FOR UPDATE (`:338`), `invocation_context` UPDATE |

- Review note 2's two emitters exist: `action.granted` comes only from `grant_execution`, `action.redispatched` only from
  `mark_sent` when `attempt_no > 1`. No path today creates an attempt with `attempt_no > 1` (`grant_execution` inserts
  attempt 1 only, `0005:145-148`), so `action.redispatched` is never emitted in practice.
- Types no code emits: `run.cancelled`, `proposal.revised`, `review.blocked`, `run.escalated`,
  `run.abandoned_unverified`, `feedback.recorded`, `notification.failed` (their functions `request_cancel`,
  `create_revision`, `expire_proposal`, `escalate_run`, `resolve_escalation` and the feedback endpoint do not exist;
  owners T21/T22).
- Python callers of `persistence.append_event`: the worker's `_event` (`worker/src/ops_worker/handlers.py:64-74`, one
  fenced unit per event: `tool.started` `{"message": "search_procedures"}` at `:112`, `tool.completed` with the same
  payload at `:129`); `_draft_and_freeze` (`handlers.py:185-195`, `explanation.ready`, `source=model_summary`, in the
  same unit as the drafts INSERT and `freeze_proposal`); the API's `DbUnit.record_reply` (`api/src/ops_api/store.py:976-981`,
  `clarification.received` with `{"question_id", "message_id"}`). The sweeper calls `append_event` nowhere.
- `sweeper/README.md:15-16` lists under "Never": "…transitions a run or writes an event (`append_event` only for its own
  maintenance events)". `EventType` has no maintenance type and every event needs a `run_id`.

### 3.5 Payload rules enforced today versus review note 2

- "no status field from api/worker on tool.completed": not enforced anywhere. `_append_event` (`0003:146-174`) and
  `event_rules_ok` (`outcomes.py:237-243`) look at `status` only for `action.confirmed`; `schemas/event.schema.json`
  allows `payload.status` (an enum of the 17 run states, `:81-99`) on any type whose source is not `model_summary`
  (its `allOf` rules 0–7 name `status` only in the `action.confirmed` rule). A `tool.completed` with `{"status":
  "SUCCEEDED"}` from `api`, `worker` or `sweeper` is accepted by all three layers.
- The schema's payload is closed (`additionalProperties: false`, `:72-74`) over ten keys: `message`, `status`,
  `evidence_refs`, `proposal_id`, `action_id`, `code`, `reason`, `outcome`, `receipt`, `tombstone`. Today's
  `clarification.received` payload (`question_id`, `message_id`, `store.py:980`) is outside it; neither the SQL nor
  `event_rules_ok` checks unknown keys ("unknown keys are not rejected here", `outcomes.py:206-209`).
- `outcomes.Event` (`outcomes.py:271-295`): strict envelope `event_id, tenant_id, conversation_id, run_id, sequence
  (ge=1), type, occurred_at (AwareDatetime), source, payload` plus `event_rules_ok`; used only by tests (TODO(T14)).
- `EventSource` (`outcomes.py:134-139`): `application`, `destination`, `model_summary`. `EventType` (`:142-173`): "The 27
  event types: BUILD_SPEC §15's 13 plus AM-14's 14", including `NOTIFICATION_FAILED = "notification.failed"` (`:157`).
  `DESTINATION_EVIDENCE` (`:176-178`), `OUTCOME_EVENT_TYPES` (`:182-184`). A unit test compares the frozen
  `EVENT_TYPES_0003` with the live enum (`0003:29-31` comment).

### 3.6 How events are read today

- **`GET /api/v1/runs/{run_id}/events`** exists (`api/src/ops_api/app.py:680-692`): identity dependency, `after: int ≥
  0` (default 0), `limit: 1–500` (default 100); 404 when `store.run` finds no run in the caller's tenant; rows from
  `AdmissionStore.events` (`store.py:1051-1060`): `SELECT sequence, type, source, occurred_at, payload FROM app.events
  WHERE run_id = %s AND tenant_id = %s AND sequence > %s ORDER BY sequence LIMIT %s` inside a tenant unit; the
  response is `{"events": [...]}` with `occurred_at` stamped. It returns no `event_id`, no cursor and no reset; it is
  not a stream. BS:518's page is 200. No `/stream` route exists (T27).
- `persistence.latest_event` (`persistence.py:539-544`): newest event by `sequence` (`type`, `occurred_at`), used by the
  API's status answer (`store.py:467`, `status_text` `:209`).
- The API's clarification reply reads the run's `clarification.requested` event ids (`store.py:957-961`) under the
  `runs` lock to bind the reply's `question_id`.
- No code reads events in the worker or the sweeper.

### 3.7 The outbox: absent

- No migration (0001–0007, `tc_0001`) creates `outbox`; no `privileges.GRANTS` row (`privileges.py:7` names T14 as
  owner); not in `RLS_TABLES` (`:135-149`) or `NO_RLS` (`:151-163`).
- `locking.LOCK_ORDER` places `"outbox"` after `"events"` and before `"jobs:finish"` (`locking.py:46-48`), and lists
  it in `NOT_YET_CREATED` (`:55`); no `OBSERVED_UNITS` entry touches it (`:57-78`).
- `JobType.DELIVER_OUTBOX` and `JobType.SWEEP_WAKEUPS` exist (`core/src/ops_core/jobs.py:46-47`); `JOB_RULES` gives the
  four maintenance types no tools, no run states, no server, creator `("sweeper",)`, key `"name:minute_bucket"`
  (`jobs.py:102-105`); `jobs_type_check` admits both (`0007:74-83`, `:96`); `schemas/job.schema.json:18,287` lists
  `deliver_outbox` with empty `allowed_tools` and `run_states`. Nothing inserts either job.
- `docs/ARCHITECTURE.md:60-62` lists outbox INSERT for `api` and `worker`, and "outbox" for the sweeper;
  `docs/runbooks/leases.md:93` repeats the lock order with `outbox`. Diagram text: `docs/diagrams/stages.json:370`
  "Commit notification intent in the outbox.", `:395` "An outbox worker delivers opted-in Slack notifications."
- No "notification", "channel", "recipient" or "sink" concept exists in `core/`, `api/`, `worker/` or `sweeper/`.

### 3.8 Wake-ups today (jobs as wake-ups, how they are created and consumed)

- **Inserters of run jobs:** `create_run` (`investigate`, key `format('%s:1', run_id)`, `0003:311-312`);
  `record_decision` (`execute`, key `proposal_id`, same transaction as `approval.recorded`, `0004:221-226`);
  `mark_unknown` (`recover`, key `<action_id>:timeout`, `0007:359-362`); the API's clarification reply (`resume_input`,
  key `dedup_key(RESUME_INPUT, run_id, clarification_event_id=question_id)` = `<run_id>:<question event_id>`, through
  `persistence.insert_job_untargeted` `persistence.py:493-502`: target-less `ON CONFLICT DO NOTHING`, rowcount verdict,
  `available_at = app.current_time()`), in one savepoint with the reply message and `clarification.received`
  (`store.py:963-982`); a duplicate key answers 409 `VERSION_CONFLICT` "the clarification was already answered"
  (`:974-975`). No MCP-called function inserts a job (the only `INSERT INTO jobs` bodies are `0003:311`, `0004:221`,
  `0004:503` and `0007:359`), and `mcp_exec` has no table grant.
- **Maintenance jobs:** only `sync_memberships` (`sweeper/main.py:125-140`): inserted, claimed (own id) and finished in
  one transaction per successful sync; the minute bucket is the wall clock (`:128-129`), `available_at` the application
  clock (`persistence.insert_maintenance_job`, `persistence.py:830-848`).
- **Consumption:** a run job is marked done only in the job's final unit, `persistence.release_lease`
  (`persistence.py:751-781`): local deadline check, `run_lease` FOR UPDATE with owner/fence/liveness compared, handles
  revoked, `finish_job` (or `requeue_job`), `lease_until = '-infinity'`, one transaction.
- **Job types the worker handles** (`handlers.handle`, `worker/src/ops_worker/handlers.py:284-294`): `investigate` and
  `execute`; every other type, `resume_input` and `recover` included, is logged "not handled by the walking skeleton"
  and then closed by `release_lease` like a handled job. So today a `resume_input` job is consumed (done_at set) without
  moving the run from AWAITING_INPUT (Plan G debt `SESSION_STATE.md:487-488`: "the worker finishes a `resume_input` job
  unhandled … → T20"), and a `recover` job likewise (Plan E debt `:457` → T22).
- **Deferral:** `claim_next` (`persistence.py:683-732`) picks the oldest available job with `FOR UPDATE SKIP LOCKED`
  per tenant (`pick_job`, `:663-680`), takes the run lease in a savepoint (`acquire_lease`, `:605-660`, `FOR UPDATE
  NOWAIT`), and either claims the job together with the lease or defers it: `available_at` moves to the live lease's
  `lease_until`, or `app.current_time() + 1 s` when the row was locked (`:713-723`). A deferred job stays unclaimed
  until that instant even when the holder releases earlier (Plan H debt `:517-518`).
- **Reclaim:** `ops_sweeper.leases.reclaim` (`sweeper/src/ops_sweeper/leases.py:20-34`), every tick: one UPDATE
  clearing `claimed_by`/`claimed_at` on jobs with `done_at IS NULL AND claimed_at IS NOT NULL AND run_id IS NOT NULL`
  whose run has no lease with `lease_until > app.current_time()`; under `sweeper_all`, no tenant set, no lock on
  `run_lease`. It never inserts a job (erratum 49).
- **Polling:** the worker polls every `POLL_SECONDS = 0.5` (`worker/main.py:35`), each poll reading `tenants`
  (`persistence.tenants`, `persistence.py:178-180`), rotating the start tenant (`main.py:42-47`), and trying up to
  `MAX_DEFERRALS = 16` claims (`main.py:36`, `claim` `:50-58`). No `LISTEN`/`NOTIFY` (`pg_notify`) appears anywhere in
  the repository's code.
- Nothing compares pending user events with jobs or run state; there are no checkpoints (`runs.checkpoint_id` is never
  written; LangGraph is not locked, T20).

### 3.9 The worker after Plan H (claim path and connections)

- `run_forever` (`worker/main.py:80-102`): `order = rotate(tenants, polls)`, `claim(deps, order)`, `run_job` (heartbeat
  `hold`, `handlers.handle`, on `LeaseLost` `handlers.abandon`, heartbeat `drop`, `:61-77`); a broken connection
  re-raises, other errors are logged.
- Connections (`worker/main.py:141-156`): the loop's autocommit connection as `worker` with `SET lock_timeout = '10s'`
  (`LOOP_LOCK_TIMEOUT`, `:38`, `:144`), a probe connection, and the heartbeat thread's synchronous connection;
  `worker_name = f"{socket.gethostname()}:{os.getpid()}"`.
- Every handler unit that writes for a run opens with `persistence.fenced` (`persistence.py:735-748`: `run_lease` FOR
  SHARE, owner/fence/expiry after the lock). `_event` (`handlers.py:64-74`) is one such unit per tool event.
- `handlers.abandon` (`:297-315`): revoke handles of the fence and `unclaim_job` (`persistence.py:784-790`) in one unit.

### 3.10 The sweeper (`sweeper/src/ops_sweeper/`, 390 lines)

- `main.py`: two autocommit connections as `sweeper` (loop `:189`, probe `:191`); `assert_clock_profile` and
  `assert_relation("app.idempotency_request")` on the probe (`:193-194`). `tick` (`:112-122`): `run_sync` (Keycloak
  listing, `sync.sync_memberships`), `record_sync` when it succeeded, `sync.purge_expired` (DELETEs on `sessions`,
  `login_state`, `logout_jti`, `idempotency_request`, one transaction, `sync.py:88-108`), `leases.reclaim`. `run_forever`
  (`:143-158`): tick every `OPS_SYNC_TICK_SECONDS` (default 30, `:204`); a broken connection ends the process.
  `worker_name = f"sweeper:{host}:{pid}"` (`:205`). Health on 127.0.0.1:8071; ready while the last sync is < 120 s old.
- The sweeper never sets `app.tenant_id` today: its `jobs` and `memberships` work runs under `sweeper_all`; the purge
  tables have no RLS. `persistence.tenants`'s docstring says "the worker's claim loop and the sweeper iterate these",
  but no sweeper code calls it. `persistence.set_tenant` (`persistence.py:127-135`) refuses outside a transaction.
- Sweeper EXECUTE grants: `current_time` and `append_event` only (`privileges.py:172-189`).
- `sync_memberships` is the sweeper's routine with direct grants (erratum 26); reclaim likewise (erratum 49).

### 3.11 `jobs` today: shape, keys, grants

- DDL `0001:107-119` plus `0002:229-237`: `id, type, tenant_id (nullable), run_id (nullable), dedup_key text NOT NULL
  UNIQUE, available_at DEFAULT now(), claimed_by, claimed_at, attempts DEFAULT 0, done_at, created_at`,
  `jobs_tenant_iff_run_check`, composite FK to `runs`; index `jobs_claimable (available_at) WHERE done_at IS NULL AND
  claimed_at IS NULL`; `jobs_type_check` (`0007:96`). The UNIQUE key covers finished rows: a key, once used, can never be
  inserted again (no role holds DELETE on `jobs`, `privileges.py:116-121`).
- Grants (`privileges.py:116-121`, `_JOB_COLUMNS` `:66`): api `ins`; worker `sel, ins, upd(claimed_by, claimed_at,
  done_at, attempts, available_at)`; sweeper `sel, ins, upd(claimed_by, claimed_at, done_at, attempts)` (no
  `available_at`); app_definer `sel, ins`. RLS `tenant_isolation` plus `sweeper_all` (`privileges.py:150`).
- `ops_core.jobs.dedup_key` (`jobs.py:150-183`): `investigate` `run_id:revision`, `resume_input`
  `run_id:clarification_event_id` (a UUID; the comment at `:116-119` explains why a per-run sequence would collide),
  `execute` `proposal_id`, `recover` `action_id:trigger` (`timeout|cancel|deadline|sweep:<YYYY-MM-DDTHH:MM>`, `:115`),
  maintenance `<type>:<YYYY-MM-DDTHH:MM>` (`:179-183`). `RECOVER_CADENCE = (300, 3600, 48)` (`:108`).

### 3.12 The published lock order (`core/src/ops_core/locking.py`, 108 lines)

- `LOCK_ORDER` (`:29-50`): `advisory:idempotency` → `advisory:asset` → `jobs:claim` → `run_lease` → `runs` →
  `messages` → `drafts` → `proposals` → `decisions` → `memberships` → `execution_grant` → `action_attempt` →
  `action_attempt_state` → `operator_resolutions` → `invocation_context` → `run_state_history` → `events` → `outbox` →
  `jobs:finish` → `idempotency_request`.
- The docstring (`:3-11`): the order constrains waits on existing rows and advisory locks; SKIP LOCKED and NOWAIT are
  outside it; a fresh INSERT "ranks at its parent's position" through its foreign-key key-share.
- `OWN_UNIT` (`:51-53`), `NEVER_LOCKED` (`:54`: `conversations`, `transitions`), `NOT_YET_CREATED` (`:55`).
- `OBSERVED_UNITS` (`:57-78`) lists 20 transactions; the event-writing ones: "worker tool event (append_event)":
  `("run_lease", "runs")`; the three API units `("advisory:idempotency", "runs", "idempotency_request")`; the three
  mcp-write units `("run_lease", "runs")`; "worker mark_unknown" `("run_lease", "runs", "invocation_context")`. The
  sweeper units are "membership sync" `("memberships",)`, "reclaim" `("jobs:finish",)`, "sync job record"
  `("jobs:claim",)`.
- Tests (`tests/plan_h/test_locking.py`): every privilege-matrix table placed exactly once (`:14-20`, a named table
  absent from `privileges.GRANTS` must be in `NOT_YET_CREATED`); each documented unit follows the order (`:39-41`);
  own units never touch a run table (`:45`); `NOT_YET_CREATED` is disjoint from the matrix (`:51-52`).

### 3.13 Tests that already assert sequence properties, and the concurrency tooling

- `tests/e2e/test_migrations_and_persistence.py:112-131` (`test_events_are_gap_free_and_rule_checked`): two worker
  `append_event` calls get sequences 2 and 3 after `run.accepted`; reserved and `model_summary` misuse refused; three
  rows. Sequential, one connection per role.
- `tests/e2e/test_definers_run_path_live.py:208-259` (`test_append_event_rules_and_sequence`): worker 2 and 3, sweeper
  `tool.completed` 4, `next_event_seq == 4`, the ordered list `(1, run.accepted) … (4, tool.completed)`; twelve refused
  (type, source, payload) cases (OC006), an unknown run OC002. Also `:111` (`next_event_seq == 1` after `create_run`)
  and `:191-194` (`run.accepted` 1, `run.failed` 2).
- `tests/e2e/test_migrations_and_persistence.py:384-402` (R006 populated upgrade): `next_event_seq` backfilled to the
  max sequence (`[1, 2, 6]`), the next append is 3.
- `tests/e2e/test_lease_stress_live.py:255-270` (R107, `slow_live`): per run, the fenced `tool.started` events' writer
  counters read in `sequence` order are non-decreasing ("no stale writer landed after a newer fence"); eight worker
  connections, 20 s, three runs, `lock_timeout = 10s`, tallies of 40P01 and 55P03 (both asserted 0, `:256`).
- No test runs concurrent `append_event` writers from different roles on one run and checks for gaps or commit order;
  no test reads events while writers commit.
- Building blocks: `role_conn` (role connection factory), `wait_until_blocked` (`tests/e2e/conftest.py:227`,
  `pg_blocking_pids`) and the pid helper (`:220`), stepped interleavings in `tests/e2e/test_leases_live.py` (`:4`), the
  stress harness above, `purge_run` with `PURGE_ORDER` (`conftest.py:132-152`, deletes `events` second; an `outbox` row
  referencing a run or event would need its own line), the `slow_live` marker (`pyproject.toml:58`).
- Gates recorded at Plan H close (`SESSION_STATE.md:333-334`): `check.py` 939 passed / 134 skipped; `check.py --profile
  test` 1052 passed / 21 skipped; `verify_handoff.py` exit 0.

### 3.14 Migration and dev-database state

- Revisions: `0001`–`0007` plus `tc_0001_test_clock` (`migrations/app/versions/`). Each revision freezes its own grant
  cells, callers and bodies (`0007:1-22` docstring; `tests/plan_e/test_transitions_table.py:61`); 0007's downgrade
  re-runs applied revisions' bodies loaded by path (`0007:38-50`). `_append_event`/`append_event` would be re-created by
  a new revision if their bodies change (the event-type literal is frozen per revision, `0003:29-31`).
- The dev `ops` database is at 0005 until the owner migrates to 0007 (`SESSION_STATE.md:5`, `:590-595`).

---

## 4. Prior rulings and proposed errata that touch T14

- **Erratum 8** (`SESSION_STATE.md:141`): "a FAILED run reached by `transition_run` on exhausted infrastructure policy
  carries no reason; the `run.failed` event's message says why." (`transition_run`'s `p_detail` is the event payload.)
- **Erratum 13** (`:176`): "…`append_event` takes a source and refuses a wider list of reserved event types." Plan E
  ruling 5 (`docs/superpowers/plans/2026-10-08-first-slice-e-roles-rls-definers.md:48`): the events emitted inside the
  functions, and `append_event` "refuses every type a definer function emits (`run.*`, `action.*`, `review.*`,
  `proposal.*`, `approval.*`, `clarification.requested`), not only the three families SA:452 names".
- **Erratum 14** (`:177`): "`mark_unknown` is worker-only; mcp-write reports UNKNOWN to the worker, which dispatches an
  `execute` job for runs left in EXECUTING."
- **Erratum 17** (`:180`): the definers take no row lock on `proposals`, `decisions`, `memberships` or
  `execution_grant`, "because a lock needs UPDATE on the table (plan ruling 23)". (By the same rule, a role locks
  `outbox` rows only with an UPDATE cell: AM-20.2 gives one to the sweeper alone.)
- **Erratum 21** (`:184`): "A CONFLICT on a terminal run is `action.conflict`, not late evidence."
- **Erratum 23** (`:186`): "The event-type allowlist and `create_run` parsing happen after `_authority`."
- **Erratum 25** (`:188`): a DELETE or UPDATE with a WHERE on a column the role cannot SELECT fails (the sweeper holds
  `sel` on `outbox` per SA:427, so this does not bite there).
- **Erratum 26** (`:207`): "`sync_memberships` is the sweeper's routine, not a definer function". **Erratum 49**
  (`:354-355`): "`reclaim_leases` is the sweeper's routine with direct grants; it un-claims claimed, unfinished run jobs
  whose lease is not live, takes no lease lock, inserts no recover job and does no permit work." (SA:471's "lost
  wake-ups re-enqueued" is therefore not done by the reclaim.)
- **Erratum 37** (`:242-244`): the lock order begins with the idempotency advisory lock (two-key form).
- **Erratum 40** (`:250-251`): the clarification reply's entry is `POST /api/v1/runs/{id}/clarifications`.
- **Erratum 42** (`:253-255`): message sequence is the table-wide identity `messages.seq` (events keep the per-run
  `sequence`).
- **Erratum 47** (`:350-351`): "the worker's unit takes `run_lease FOR SHARE` and checks the fence before the call; the
  functions keep their signatures" (`append_event` included).
- **Erratum 52** (`:361-363`): "the extended lock order of `ops_core/locking.py` (advisory locks, `jobs` claim,
  `run_lease` … `outbox`, `jobs` finish, `idempotency_request`), with SKIP LOCKED and NOWAIT outside it, a fresh-row
  INSERT ranked at its foreign-key parent, and the own-unit tables named."
- **SESSION_STATE.md:103** (1.3.6 summary): "…status answers and conversation clarifications are messages, not events;
  the sweeper iterates tenants". **:109** (1.3.5 fixes): "`action.granted`/`action.redispatched` owners; `deliver_outbox`
  job type". T12 review note (`tasks.json:601`): "Status answers and conversation-level clarifications are messages
  …, not events".
- **Plan D** (`…first-slice-d-walking-skeleton.md:19`): "**Events** are validated by `ops_core.outcomes.Event` before
  insert; … `sequence` is per run, gap-free, assigned under the `runs` row lock in the same transaction (SA:303, the
  `next_event_seq` column itself is T14 debt)." (Revision 0002/0003 later added the column and the lock; the
  `outcomes.Event` validation before insert is not in today's write path, §3.5.)
- **Plan E ruling 18** (`…first-slice-e…:61`): "The worker claims across tenants by iterating `tenants`. … O(tenants)
  per poll until T13's wake-ups." **Ruling 24** (`:66`): the queue compares and stamps with `app.current_time()`.
  **Ruling 4** (`:47`): `resolve_identity` iterates `tenants` "the way SA:520 prescribes for the sweeper".
- **Plan F ruling (b)** (`SESSION_STATE.md:204`): "The maintenance job row's `available_at` is on `app.current_time()`
  and the sweeper claims the id it inserted".
- **Plan G rulings** (as recorded in code): ruling 15, the reply's `resume_input` through a target-less insert
  (`persistence.py:483-484`, `:493-497`); "a 429 writes nothing" (erratum 39).
- **Plan H rulings** (`docs/superpowers/plans/2026-10-15-first-slice-h-leases-fences-heartbeat.md:162-200`): ruling 3
  (claim and lease in one transaction; deferral), ruling 11 (reclaim: "no recover job, no permit work, no wake-up
  sweep"), ruling 14 (the lock order as data), ruling 19 (a lost lease hands the job back: "jobs are wake-ups").
- **Plan H debt lines owned by T14** (`SESSION_STATE.md:516`, `:517-518`, `:538`; §3.1), plus the older T14 lines it
  re-homed (`:390`).
- Errata 1–59 contain no ruling on `notification.failed`, the outbox, `deliver_outbox`, `sweep_wakeups`, event
  retention or the sweeper's tenant iteration beyond those quoted above.

---

## 5. Open questions the planner must rule on

1. **What "gap-free, commit-ordered" requires beyond today's mechanism.** SA:303 says the runs-lock counter "makes it
   gap-free and commit-ordered". Today every event goes through `_append_event`, which locks `runs` FOR UPDATE, bumps
   `next_event_seq` and inserts in the caller's transaction (`0003:175-187`); a rollback undoes both, and the lock is
   held until commit, so a second writer of the same run waits for the first to commit or roll back. Facts on the other
   side: R089's evidence ("Concurrent writers; SSE replay never skips") and DoD 1 have never been exercised with
   concurrent writers (§3.13); `occurred_at` is truncated to the second and taken from `app.current_time()`, which the
   test clock can move backwards (`0003:183`); `event_id` is random (`gen_random_uuid`). Open: whether T14 changes the
   mechanism at all, or proves it (and against which reader: the events route's `sequence > after`, `latest_event`).
2. **Which concurrent writers the proof covers.** Event writers today: `api` (`create_run`, `record_decision`, the
   reply's `append_event`), `worker` (tool events, `explanation.ready`, `transition_run`, `freeze_proposal`,
   `mark_unknown`), `mcp_exec` (`grant_execution`, `mark_sent`, `record_outcome`), `sweeper` (may call `append_event`;
   calls nothing today). Same-run pairs that can actually race in the running system: the API's reply unit against a
   worker unit, `record_outcome` against the worker's `mark_unknown`, a future sweeper `notification.failed` or
   escalation against mcp-write. Open: which pairs a DoD 1 test drives, whether it uses role connections directly
   (as `test_definers_run_path_live.py` does) or the services, and whether it is a stress test (`slow_live`) or a
   stepped interleaving (`wait_until_blocked`).
3. **How "commit-ordered" is observed in a test.** A reader sees sequence n+1 only after n's transaction ended
   (lock held to commit). Open: what the assertion is (no reader snapshot ever shows n+1 without n; sequences equal
   `1..next_event_seq` with no hole after concurrent rollbacks; per-writer order preserved), and whether a rolled-back
   writer (lock timeout 55P03, OC006 refusal after the lock — every refusal in `_append_event` precedes the lock except
   OC002) is part of the scenario.
4. **Review note 2: payload rules inside the function.** "no status field from api/worker on tool.completed" is
   enforced nowhere (§3.5), and SA:322 forbids `status` only for `model_summary`. Open: the exact rule (no `status` on
   `tool.*`; on every application-sourced non-`action.*` type; for the sweeper too), whether the schema's
   `allOf` gains the same rule (SA:324 "Enforced in schema … and in code"; AM-80 is T45's), whether `event_rules_ok`
   mirrors it, and whether the function also enforces the schema's closed payload key set, which today's
   `clarification.received` (`question_id`, `message_id`) would violate. A body change is a new revision re-creating
   `_append_event` (and its frozen type list).
5. **`outcomes.Event` in the write and read paths** (TODO(T14) `outcomes.py:278`; Plan D `:19`). Open: whether
   `persistence.append_event` validates through it (it cannot know `event_id`, `sequence`, `occurred_at` before the
   call), whether the events route validates rows on the way out, or whether the TODO is retired.
6. **What a "wake-up" is in T14.** Two readings exist in the repository: SA:173 and BS:340 use "wake-up" for a job row
   (`resume_input`, `execute`) committed with the user event; the debt lines `persistence.py:698` ("wake-ups instead of
   polling"), `SESSION_STATE.md:517-518` ("no wake-up on release") and `:538` ("still polls every 0.5 s and claims per
   tenant") use it for signalling the worker so it need not poll. No `LISTEN`/`NOTIFY` exists. Open: which of these
   T14 delivers (the re-enqueue sweep, a notification channel to the worker, an early wake-up of a deferred job when a
   lease is released, or all three).
7. **What `sweep_wakeups` compares.** BS:340: "pending user events, jobs, checkpoints and authoritative run state".
   Checkpoints do not exist until T20. User events with jobs today: `clarification.received` + `resume_input` (one
   savepoint), `approval.recorded` + `execute` (one function); both pairs commit atomically, so the crash window BS:340
   names is between the job's consumption and the run's progress. Observable states: a run in AWAITING_INPUT whose
   reply job is `done_at` (today every `resume_input` is closed unhandled, §3.8); a run in APPROVED whose `execute` job
   is done (Plan H's I1 case, now handed back instead); a run in OUTCOME_UNKNOWN whose `recover` job is done unhandled.
   Open: the predicates, which states are T14's versus T20's (`resume_input` handling, R042) and T21's (R023, DoD 3
   "Lost-wakeup crash between decision commit and processing recovered by the sweeper"), and whether T14 ships the
   sweep with a test that can only be staged (no handler consumes `resume_input`).
8. **What a re-enqueue writes, and as whom.** A wake-up's dedup key is UNIQUE across finished rows and no role may
   DELETE jobs (§3.11), so the same key cannot be inserted again. Options visible in the grants: the sweeper may UPDATE
   `done_at`, `claimed_by`, `claimed_at`, `attempts` (not `available_at`) under `sweeper_all`, i.e. reopen the row; or
   insert a row under a new key. AM-20.4 names the inserters (`resume_input`: `api`; `execute`: `record_decision`;
   `recover`: `mark_unknown`, `worker`, `reclaim_leases` with `sweep:<bucket>`), and no key shape exists for a
   sweeper-made `resume_input`/`execute`. Open: reopen versus new key, the key shape, and whether this is an erratum.
9. **"Mark their consumption only after processing reaches a durable acknowledged state" (BS:340).** Today a job is
   finished in `release_lease`, after the handler returns, even when the handler did nothing for its type (§3.8). Open:
   whether T14 changes which job types the worker closes unhandled (finishing `resume_input`/`recover` loses the
   wake-up; leaving them open makes the worker re-claim them every poll), given that their handlers are T20/T22's.
10. **Deferred jobs and lease release** (Plan H debt `:517-518`). A deferred job's `available_at` is the busy lease's
    `lease_until` (`persistence.py:719-723`). Open: whether release (`release_lease`, `abandon`) pulls the run's other
    deferred jobs forward (the worker holds `upd(available_at)` on jobs), and in which unit (lock order: `jobs:finish` is
    after `outbox`).
11. **Per-tenant polling** (Plan E ruling 18; `:538`). Open: whether T14 removes the per-tenant poll (the worker has
    only `tenant_isolation` on `jobs`, so a cross-tenant pick needs a tenant iteration, a definer, or a signal carrying
    the tenant), and the poll interval that remains.
12. **The outbox table's shape.** BS:240: "event/recipient/channel, dedup key, payload reference, attempts, lease, next
    delivery time, result". SA:427 names four sweeper-updatable columns: `leased_until`, `attempts`, `delivered_at`,
    `result`. Not named anywhere: the primary key, `tenant_id` (required by SA:510's RLS), `run_id`/`event_id`
    references, `dedup_key` (UNIQUE? scoped how?), a "next delivery time" column (the sweeper has no UPDATE cell for
    one unless `leased_until` doubles as it), a lease owner column, a dead-letter marker, `created_at`. Open: every
    column, its type, constraints and FKs (`events.event_id` is the PK; `(tenant_id, run_id)` → `runs` is the pattern).
13. **Who inserts outbox rows, and for which events.** BS:524: "in the same transaction as the event that requires
    it". AM-20.2: `api`, `worker`, `app_definer` hold `ins` (no `sel`), the sweeper does not. No spec text says which
    event types "require" a notification; DEV-029's prompt ("Tell me when the incident is created") and expected
    outcome `SUCCEEDED_NOTIFICATION_FAILED` point at an incident outcome, which only `record_outcome` (an `app_definer`
    body called by `mcp_exec`) emits; review- or approval-related events come from `freeze_proposal`/`record_decision`.
    Open: the trigger set (fixed list in SQL, per-run opt-in, every event of some types), whether the intent is written
    inside `_append_event` (one place, every writer) or in each definer, and how an `ins`-only role deduplicates (a
    target-less `ON CONFLICT DO NOTHING`, the `insert_job_untargeted` pattern, `persistence.py:493-502`).
14. **What "delivery" means with "no external channel".** T14: "leased delivery loop (no external channel)"; Slack is
    M15/T39 (SA:100, BS:526); BS:648 allows outbox egress only to "explicitly opted-in notification endpoint";
    BS:730 forbids notifying real people; T24 wants "a fault-injectable outbox sink" for DEV-029; BS:564 "Notification
    failure: keep result in the web interface". Nothing like a channel, recipient or sink exists (§3.7). Open: the v1
    sink (a log line, a local file, a table, an in-process test double, a loopback HTTP endpoint), where "resolve
    recipients from approved mappings" and "redact … when the channel is not approved" land when there is no channel,
    and whether the sink's fault hook lives in `core.testing.faults` (R098: test profile only).
15. **The delivery loop's lease and claim.** "Delivery workers claim outbox rows with leases" (BS:524); the sweeper
    holds `sel, upd(leased_until, attempts, …)` (SA:427), and a row lock needs an UPDATE cell (erratum 17), which only
    the sweeper has. Open: the claim statement (SKIP LOCKED and a `leased_until` comparison on `app.current_time()`),
    the lease length, whether a crashed delivery is retried by expiry alone, and whether the loop is the sweeper
    process's tick (`deliver_outbox` is a sweeper job type, SA:346) or a separate process (BS:150 draws an "Outbox
    worker"; AM-01's directory table has no outbox service).
16. **Bounded retry, jitter and dead-letter** (BS:524, BS:685, BS:562). Open: the attempt cap, the backoff and jitter
    and where the next attempt time is stored (Q12), what "dead-letter" is (a terminal `result` value? a column?), and
    what "operator visibility" is in v1 (the `operator` role has EXECUTE on `resolve_escalation` only and no table
    grants, SA:437; no admin UI, SA:107; BS:574's dashboards are T28/T29).
17. **"Delivery result recorded separately" (DoD 2) and `notification.failed` in a separate transaction (SA:188, T13
    note 6).** The result columns are on `outbox` (`delivered_at`, `result`); `notification.failed` is an event, so it
    needs a run (`events.run_id NOT NULL`) and `append_event` (sweeper may call it; `notification.failed` is not
    reserved, `0003:369-371`), which locks `runs` — the reason SA:188 forbids it after `outbox` in one transaction.
    Open: when `notification.failed` is appended (each failure, final failure only), its payload (schema keys allow
    `message`, `code`, `reason`), the order of the two transactions and the crash window between them (result recorded,
    event not yet appended), and whether it is deduplicated.
18. **RLS and tenant iteration for delivery** (SA:520, review note 3). `outbox` is a tenant table without
    `sweeper_all`; the sweeper never sets a tenant today (§3.10). Open: the per-tenant loop (read `tenants`, one
    transaction per tenant with `set_tenant`, or one transaction setting each in turn as `resolve_identity` and
    `queued_runs_total` do inside a definer), and whether the same loop is shaped now for T21's `expire_proposal` and
    T22's deadline escalation (review note 3 lists all three).
19. **The `deliver_outbox` and `sweep_wakeups` job rows.** AM-20.4 keys them `name:<minute bucket>`; today's only
    maintenance row (`sync_memberships`) is inserted, claimed and finished in one transaction as an audit record "never
    a trigger" (`sweeper/main.py:125-140`), its bucket on the wall clock. The tick is 30 s, so two ticks share a bucket.
    Open: whether the two new jobs are audit rows of the same kind, whether work runs inside or outside that
    transaction (delivery does external I/O, BS:334 "commit before network"), and what a second tick in the same
    minute does (the dedup key refuses the row).
20. **Finished maintenance rows accumulate** (Plan F debt `:477`, owner T14). Three more rows per minute per job type
    would join them. The sweeper holds no DELETE on `jobs`. Open: an AM-20.2 `del` cell (a matrix change and a new
    revision) or a definer, the retention, and whether finished run jobs are purged too.
21. **Retention of events and outbox rows.** BS:578: "30 days operational event replay"; BS:518: "replay cursor
    retained 30 days"; BS:576: audit events are authoritative; AM-20 principle 2 and `AUDIT_TABLES` make `events`
    insert-only; no role holds DELETE on `events` or `outbox`. Open: whether T14 deletes anything (events past 30 days
    would break the "gap-free" read for old runs unless replay answers a reset, T27's), and how long delivered or
    dead-lettered outbox rows live.
22. **Lock order placement of the new work.** `outbox` sits after `events` and before `jobs:finish` (`locking.py:46-48`).
    Open: the `OBSERVED_UNITS` entries for the outbox insert (inside `_append_event` or after it), the delivery claim
    (`("outbox",)` alone, an own unit?), the result update, the `notification.failed` append (`("runs",)` via
    `append_event`), the wake-up sweep (reads `events`/`runs`, writes `jobs`), and removing `outbox` from
    `NOT_YET_CREATED` (`test_locking.py:51-52`).
23. **The events route versus BS:277/BS:518.** `GET /api/v1/runs/{id}/events` exists with `after`/`limit ≤ 500`
    (default 100), no `event_id`, no cursor expiry or reset (§3.6); BS:518 proposes a 200-event page and a 30-day
    cursor; T27 owns SSE and `Last-Event-ID`. Open: whether T14 touches the route (page size, fields, an R089 read-side
    test) or leaves it to T26/T27.
24. **Sequence width and the `sequence` type.** `events.sequence` and `runs.next_event_seq` are `integer`; `jobs`/fences
    use `bigint`. Open: whether this matters for T14 (no stated per-run event bound).
25. **The sweeper's own events.** `sweeper/README.md:15-16` allows `append_event` "only for its own maintenance
    events", yet every event needs a run and no maintenance type exists (§3.4). Open: whether `notification.failed` is
    the sweeper's only event, and whether the README line changes.
26. **SA:471's "lost wake-ups re-enqueued (dedup keys)" after erratum 49.** The reclaim does not re-enqueue; T14 owns the
    wake-up half and T22 the `recover` half (`:516`). Open: whether the wake-up sweep is part of `leases.reclaim`, a
    separate `sweep_wakeups` routine (erratum 26/49 precedent: sweeper routine with direct grants), or a definer
    (`reclaim_leases`); and whether erratum 49 is amended.
27. **Review note 1 ("recover jobs never created by either MCP server").** Already true: `mcp_exec` has no table grants
    and none of its functions inserts a job (§3.8). Open: whether T14 adds a test that pins it (an R131-style ACL or a
    catalog check that no `mcp_exec`-callable body inserts into `jobs`).
28. **Testing R024.** "Fail delivery after state commit; result remains recorded and dedup key preserves intent."
    Open: the fault point (the sink failing after the run's state transaction committed), what "result remains recorded"
    asserts (the run's outcome event and state unchanged, the outbox row's `result`/`attempts`), how "dedup key preserves
    intent" is shown (a replayed writer — e.g. an idempotent `record_outcome` — inserts no second intent), and whether
    the evidence is a report file under `reports/` like Plans F–H.
29. **Migration shape.** A new revision (0008) would carry `outbox`, its grant cells (frozen), its RLS policy, any
    changed `_append_event`/`append_event` bodies and definers that write intent (frozen callers), and a clean downgrade
    (R006 live test; 0007's re-run-the-applied-bodies pattern). The dev database is still at 0005 (owner input). Open:
    one revision or several, and the dev-database instruction.

---

## 6. Glossary of exact names

- `app.events(event_id, tenant_id, conversation_id, run_id, sequence integer, type, occurred_at, source, payload)`,
  `UNIQUE (run_id, sequence)` — `0001:197-208`, composite FK `0002:299-300`.
- `runs.next_event_seq integer DEFAULT 0` — `0002:203`; written only by `_append_event` (`0003:180`).
- `app._append_event(uuid, uuid, text, text, jsonb)` — `0003:104`; helper, rules + counter + insert.
- `app.append_event(uuid, text, jsonb, text)` — `0003:356`; api, worker, sweeper; reserved-type and source refusals.
- `EVENT_TYPES_0003` — `0003:32-60`; the frozen 27-type allowlist.
- `persistence.append_event` / `Appended` — `persistence.py:267` / `:259`.
- `EventType`, `EventSource`, `DESTINATION_EVIDENCE`, `OUTCOME_EVENT_TYPES`, `event_rules_ok`, `Event` —
  `core/src/ops_core/outcomes.py:142, 134, 176, 182, 203, 271`.
- `GET /api/v1/runs/{run_id}/events` — `api/src/ops_api/app.py:680`; `AdmissionStore.events` `store.py:1051`.
- `outbox` — SA:427, SA:510, BS:240, BS:524; does not exist; `locking.py:47`, `NOT_YET_CREATED` `:55`.
- `notification.failed` — BS:514, SA:188; `EventType.NOTIFICATION_FAILED` (`outcomes.py:157`); never emitted.
- `deliver_outbox`, `sweep_wakeups` — `JobType` (`jobs.py:46-47`), `jobs_type_check` (`0007:74-83`); never inserted.
- `resume_input` key `<run_id>:<clarification event_id>` — `jobs.py:168-169`; inserted by the API (`store.py:970-973`).
- `insert_job_untargeted` — `persistence.py:493`; target-less dedup insert for INSERT-only roles.
- `claim_next`, `pick_job`, `acquire_lease`, `release_lease`, `unclaim_job`, `finish_job`, `requeue_job` —
  `persistence.py:683, 663, 605, 751, 784, 816, 821`.
- `insert_maintenance_job` / `claim_maintenance_job` — `persistence.py:830` / `:851`; key `<type>:<YYYY-MM-DDTHH:MM>`.
- `leases.reclaim` — `sweeper/src/ops_sweeper/leases.py:20`.
- `POLL_SECONDS` 0.5, `MAX_DEFERRALS` 16 (`worker/main.py:35-36`); `OPS_SYNC_TICK_SECONDS` 30 (`sweeper/main.py:204`).
- `LOCK_ORDER`, `OWN_UNIT`, `NEVER_LOCKED`, `NOT_YET_CREATED`, `OBSERVED_UNITS` — `core/src/ops_core/locking.py:29, 51,
  54, 55, 57`.
- `sweeper_all` — `privileges.SWEEPER_ALL` (`privileges.py:150`): `memberships`, `jobs`.
- `OC002` not found, `OC006` event rule violation (`EventRuleViolation` in Python) — `0003:10-12`.
- `role_conn`, `wait_until_blocked`, `purge_run`/`PURGE_ORDER`, `slow_live` — `tests/e2e/conftest.py`,
  `pyproject.toml:58`.
- DEV-029 `notification-failure` — `evals/handoff-development/scenarios.jsonl:29`.

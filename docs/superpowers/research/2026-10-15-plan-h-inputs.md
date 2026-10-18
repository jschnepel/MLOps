# Plan H inputs: T13 (run lease, fence locking, heartbeat thread and fault factory) — fact sheet

Prepared 2026-10-15 on branch `plan-h` at `954ef58` (= `plan-g`; clean tree; read-only on the repository). Facts
only, no design. Citations: `SA:<line>` = `SPEC_AMENDMENTS.md`, `BS:<line>` = `BUILD_SPEC.md` (line numbers as of
`954ef58`); the amendments win wherever the two conflict. Repository files are cited as `path:line`. Nothing was run
against a database, Keycloak or a service for this sheet: every fact below is read from the files, and no secret,
token or `.env` value was opened.

Note on line numbers in the brief: AM-12 is SA:170–218 (lease SA:172–174, fenced writes SA:176–184, lock order
SA:188–191, heartbeat SA:193–199, model permit SA:203–205, checkpoints SA:209–218); the AM-10 clock rule is
SA:156–162; the AM-13 transport-timeout path is SA:250–256; AM-15 job types SA:338–348; the AM-20.2 rows are SA:418
(`run_lease`), SA:419 (`jobs`), SA:420 (`invocation_context`), SA:432 (`model_permit`); AM-20.4 is SA:492–506;
AM-20.5's no-RLS list is SA:523; AM-20.7 item 9 is SA:564. BUILD_SPEC §8 "Queue, lease, and checkpoint correctness"
is BS:332–342, §10 "Synthetic service behavior" BS:403–407, §17 BS:540–562, §24 BS:674–689 (worker row BS:682).
`handoff/acceptance-matrix.json` names the owners field `owning_tasks`.

---

## 1. T13 verbatim, its acceptance-matrix rows, and related rows/tasks

### 1.1 T13 (`handoff/tasks.json:605-637`)

- **id/milestone/title:** `T13`, `M04` ("Run leases, fencing, event journal and outbox", `:55-63`, task_ids `T13`,
  `T14`), "Run lease, fence locking, heartbeat thread and fault factory". `status: "PLANNED"`,
  `external_approval_required: false`.
- **instructions:** "Lease acquisition FOR UPDATE; fenced writes FOR SHARE; clock_timestamp via app.current_time();
  published lock order; heartbeat on its own thread/connection; local monotonic deadline; model_permit with SKIP
  LOCKED; test-only fault factory for app services."
- **depends_on:** `["T09"]` (`DONE`). T13 is the earliest `PLANNED` task whose dependencies are all `DONE` (T17
  also depends on T09 only and comes later in the file).
- **requirement_ids:** `R019, R020, R087, R088, R098, R107`.
- **definition_of_done:**
  1. "Two-connection interleaving test: stale fence write aborts."
  2. "Stress test shows no deadlock under the lock order."
  3. "Blocked event loop (25 s) does not lose the lease; forced renewal failure cancels work."
- **review_notes** (all seven, verbatim):
  1. "Transactions that write run_lease take FOR UPDATE from the start (no FOR SHARE upgrade)."
  2. "Owner re-fence path hands the new fence to the heartbeat thread atomically."
  3. "Lock order includes the asset-guard advisory lock and memberships (AM-12); also place jobs, invocation_context,
     model_permit, sessions."
  4. "Gate heartbeat renewal on event-loop liveness and the 90 s compute budget."
  5. "Advisory lock: asset_id NOT NULL and read before locking; use hashtextextended (AM-12 wording updated); test
     that app_definer may call pg_advisory_xact_lock."
  6. "Lock order now includes messages, decisions and operator_resolutions; the outbox appends notification.failed in
     a separate transaction (AM-12)."
  7. "Handle revocation goes through revoke_handles(run_id, fence); the worker has no column grant on
     invocation_context.revoked_at."
- There is no "Plan …" close-out note on T13 yet (T12's, `:602`, is the Plan G record).
- `handoff/BUILD_BACKLOG.md:76` repeats the instructions and requirement list; `:56` carries T10's note "Fault factory
  lives in shared core.testing.faults (R098 co-owned with T13)."

### 1.2 Acceptance-matrix rows owned by T13 (`handoff/acceptance-matrix.json`)

Exactly six rows list `T13` in `owning_tasks`; all are `blocking_for_v1: true`.

- **R019 (:340)** — M04 / durability; requirement: "Leases can expire and be recovered safely"; expected_evidence:
  "Kill lease owner; another owner acquires after expiry with incremented fence."; owners: T13; suggested_test:
  `tests/acceptance/test_r019_leases_can_expire_and_be_recovered_safely.py`; status `NOT_RUN` /
  `NOT_IMPLEMENTED_OR_NOT_TARGET_VERIFIED`.
- **R020 (:355)** — M04 / durability; requirement: "Stale worker cannot mutate application state"; expected_evidence:
  "Old worker attempts commit after fence changes; transaction rejects it."; owners: T13; suggested_test:
  `tests/acceptance/test_r020_stale_worker_cannot_mutate_application_state.py`; `NOT_RUN`.
- **R087 (:1390)** — M04 / concurrency, `source: SPEC_AMENDMENTS.md`; requirement: "Lease and fence are per run across
  all job types"; expected_evidence: "Resume-job vs original-job race: only the current run fence writes."; owners:
  T13; suggested_test: `tests/acceptance/test_r087_lease_and_fence_are_per_run_across_all_job_types.py`; `NOT_RUN`.
- **R088 (:1406)** — M04 / concurrency, `source: SPEC_AMENDMENTS.md`; requirement: "Heartbeat survives long or blocking
  work; lease loss cancels it"; expected_evidence: "Blocked loop and >30 s fake drafter keep the lease; forced renewal
  failure cancels the call and revokes handles."; owners: T13; suggested_test:
  `tests/acceptance/test_r088_heartbeat_survives_long_or_blocking_work_lease_l.py`; `NOT_RUN`.
- **R098 (:1573)** — M02 / security, `source: SPEC_AMENDMENTS.md`; requirement: "Fault-injection hooks are unreachable
  outside the test profile"; expected_evidence: "Hook routes 404 in default and demo profiles; factories refuse to
  start without PROFILE=test."; owners: T10, T13; suggested_test:
  `tests/acceptance/test_r098_fault_injection_hooks_are_unreachable_outside_th.py`; status
  `IMPLEMENTED_LOCALLY_VERIFIED` / `RECORDED_LOCALLY`, evidence_paths `tests/plan_e/test_incident_sim_t10.py`,
  `tests/plan_e/test_faults.py`; note: "Plan E (T10): unit-level evidence (fault hooks 404 outside the test profile;
  the factory refuses any other profile); the live suite runs incident-sim under PROFILE=test."
- **R107 (:1742)** — M04 / concurrency, `source: SPEC_AMENDMENTS.md`; requirement: "Fenced writes lock the lease row and
  follow one lock order"; expected_evidence: "Two-connection interleaving and stress tests: stale writes abort, no
  deadlocks, clock_timestamp-based expiry."; owners: T13; suggested_test:
  `tests/acceptance/test_r107_fenced_writes_lock_the_lease_row_and_follow_one_.py`; `NOT_RUN`.

`handoff/ACCEPTANCE.md:25-27` carries R019, R020 and **R021 as "M04"** ("Stale worker cannot mutate authoritative
checkpoints. Evidence: Lose lease during graph work; old saver write is rejected inside checkpoint transaction."),
while the matrix row R021 (:370) is milestone `M15`, owner `T38` (SA:99, SA:218). `tests/acceptance/` does not
exist; `pyproject.toml:48-51` `testpaths` lists `tests/plan_a` … `tests/plan_g` and `tests/e2e` (no `tests/plan_h`).

### 1.3 Tasks that depend on T13, and other rows that touch leases, fences, faults or the queue

- **T14** (`tasks.json:639`) depends_on `["T13", "T12"]`: "runs.next_event_seq under the runs lock; wake-up jobs
  committed with user events; sweeper; transactional outbox with leased delivery loop (no external channel)." Review
  notes: "Jobs carry dedup_key UNIQUE per AM-20.4; recover jobs never created by either MCP server."; "…deliver_outbox
  is a job type."; "The sweeper iterates tenants and sets app.tenant_id per tenant for expiry, outbox delivery and
  deadline escalation; sweeper_all covers memberships and jobs only (AM-20.5, 1.3.6)."
- **T15** (`tasks.json:664`) depends_on `["T13", "T05"]`: mcp-read with "resolve_invocation with azp binding, server
  binding (read handles only) and server-derived allowlist". Its R027 (:460, M05, owner T15): "Invocation handle binds
  workload run lease and tools" — "Replay with other workload/run/expired fence/tool; server rejects; handle absent
  from model/logs."
- No other task lists T13 in `depends_on`. Rows outside T13 that name the same mechanisms:
  - **R021** (M15, T38): fenced checkpoint `put`/`put_writes`. T38 instructions: "BaseCheckpointSaver subclass checking
    the run fence inside put/put_writes; enable multiple worker replicas".
  - **R022** (:385, M07, T20): "Human waits release workers and transactions" — "Pause for review; no active worker
    lease/long DB transaction/model budget consumed." T20 instructions end "…runs.checkpoint_id stored under fence and
    used on resume; idempotent pre-interrupt logic; ID-only interrupts; human waits release the lease; ANSWERED path."
  - **R109** (:1774, M08, T22): "A transport timeout during create_incident cannot hide a grant" — "Timeout path takes
    the lease lock, bumps the fence, reads the grant; late grant impossible afterwards." T22 DoD: "Timeout during
    create_incident resolves via the lease-lock read."
  - **R062** (:991, M11, T29): "Resource budgets and overload are enforced" — "Oversize input/results, exhausted
    repair/time/tool cap and full queue stop predictably without retry storm." T29: "Queue/model/time/retry caps".
  - **R065** (:1036, M12, T30): "Probes and drain distinguish model outages from dead API" — "Stop model; API does not
    restart endlessly. Terminate worker; no new leases and safe recovery."
  - **R015** note (:274): "…the after-commit side (the ack lost after the commit, the retry replays the recorded 202)
    is R016's replay; the lose_after_commit fault arrives with T13."
  - **T02** DoD: "Cancellation behaviour measured and the model_permit release rule chosen accordingly." (T02 is
    `DONE_PENDING_OWNER`; see §3.16.)
  - **T21** review note: "Asset guard via pg_advisory_xact_lock(tenant, asset) first in lock order; refusal 409
    ASSET_ACTION_UNRESOLVED."
  - **T10** review note 2: "Fault factory lives in shared core.testing.faults (R098 co-owned with T13)."
  - **T24** review note: "DEV-029 needs a fault-injectable outbox sink."

---

## 2. Spec passages that bind T13

### 2.1 AM-12 (SA:170–218), verbatim

- SA:172–174 (**Lease**): "`run_lease(run_id PK, owner, lease_until, fence bigint)`. Jobs are wake-ups only." /
  "**Acquisition:** `SELECT … FOR UPDATE` on the lease row, then check `lease_until < app.current_time()`, then
  `fence := fence + 1`."
- SA:176–184 (**Fenced writes**): "every worker or MCP mutation for a run **first** executes:" `SELECT 1 FROM run_lease
  WHERE run_id = :r AND fence = :f AND lease_until > app.current_time() FOR SHARE` — "A missing row aborts the
  transaction."
- SA:186 (**Writes without a lease**): "API and sweeper mutations (decision, cancel, revision, expiry) hold no lease.
  They serialize with `SELECT … FROM runs … FOR UPDATE` plus `expected_version`."
- SA:188 (**Lock order**): "`asset guard advisory lock → run_lease → runs → messages → proposals → decisions →
  memberships → execution_grant → action_attempt → operator_resolutions → events → outbox`. Idempotency rows are
  written last, before commit. The outbox delivery loop records results in its own transaction and appends any
  `notification.failed` event in a **separate** transaction, so it never takes `runs` after `outbox`."
- SA:189: "The asset guard lock is `pg_advisory_xact_lock(hashtextextended(tenant_id || ':' || asset_id, 0))`;
  `asset_id` is NOT NULL and read before locking. Proposal freezing and `grant_execution` take it first."
- SA:190: "Every transaction and definer function follows this order."
- SA:191: "Any transaction that will write `run_lease` takes `FOR UPDATE` from the start; it never upgrades from `FOR
  SHARE`. A two-connection interleaving test and a concurrent stress test prove fencing and deadlock freedom (R107)."
- SA:193–199 (**Heartbeat**): "Runs on a **dedicated thread with its own DB connection**: renew every 10 s, lease 30
  s." / "The worker also keeps a local monotonic deadline: it stops starting effects at `lease_until − 5 s`." / "When
  renewal fails, the worker: cancels in-flight model and tool calls; revokes its invocation handles; exits the run."
- SA:201 (**Async only**): "use `AsyncPostgresSaver`, `ChatOllama.ainvoke` and async MCP/HTTP clients. No synchronous
  I/O on the event loop."
- SA:203–205 (**Model permit**): "A `model_permit` row, leased and polled with `SKIP LOCKED` plus backoff, enforces
  global model concurrency (1)." / "Whether a cancelled request actually stops Ollama's generation is **measured** in
  T02. If it doesn't, the permit is held until `ollama ps` shows idle or the 60 s cap passes."
- SA:209–218 (**Checkpoints**): "Invoke graphs with `durability=\"sync\"`…"; "After each superstep, the worker stores
  the accepted `checkpoint_id` in `runs.checkpoint_id` under the fence."; SA:217: "**V1 runs one worker replica.**
  Fencing still protects application writes, and the stored checkpoint ID protects the head."; SA:218: "R021 (fencing
  `put`/`put_writes` themselves, enabling multi-replica) stays open in M15."
- SA:33 (AM-00): "**§6:** \"job … lease_until, fence\": replaced by run-level `run_lease` (AM-12)." (BS:232's job row
  "lease_owner, lease_until, fence" is superseded.) SA:46: "v1 *is* the one-replica profile (ADR-0002); the
  distributed gate (R021) is M15." SA:108: "**one worker replica** in the demo profile (AM-12)."

### 2.2 AM-10 clock rule (SA:156–162), verbatim

- SA:157: "Every lease, expiry, freshness and deadline comparison uses `clock_timestamp()`, evaluated **after** the
  relevant row locks are acquired. Never use `now()`, which is the transaction start time."
- SA:158: "Tests inject time through the database function `app.current_time()`. It wraps `clock_timestamp()` plus an
  offset read from the table `app.test_clock`."
- SA:159–161: only the Alembic branch `testclock` creates `app.test_clock`; no runtime role can write it, only
  `test_harness`; "**Session settings (GUCs) are never consulted**".
- SA:151: "`state_version` increases **only on state transitions**. Appending events, heartbeats and attempt-state
  changes do not bump it…"
- AM-20.6 (SA:528–530): the dynamic-`EXECUTE` definition; "Every service, not only the bootstrap, asserts at start that
  the table is absent outside the test profile."

### 2.3 AM-13 worker transport timeout (SA:250–256), verbatim

"**Worker transport timeout during `create_incident`** [R2#10]: 1. Take the run lease row lock (`FOR UPDATE`). 2. Bump
the fence, which revokes the handles. 3. Read `execution_grant` by `run_id`. 4. If a grant exists, the run becomes
OUTCOME_UNKNOWN with that `action_id` and enters recovery. If not, no grant can commit any more, because the fence
changed. Tested by R109."

Also SA:224: mcp-write "records every step through fenced `SECURITY DEFINER` functions (AM-20)"; SA:229–232:
`mark_sent` "locks `runs` (in lock order) and re-checks `cancel_requested` and the dispatch deadline".

### 2.4 AM-15 job types (SA:338–348)

- SA:338: "Every job has exactly one `type`. Allowed tools are derived from type plus run state plus attempt state.
  **A handle is bound to one server:** `investigate`/`resume_input` handles are accepted only by mcp-read;
  `execute`/`recover` handles only by mcp-write (R131)."
- SA:342–345: `investigate` (API at admission and after a revision; QUEUED, RETRIEVING, DRAFTING); `resume_input` (API
  with a clarification reply; AWAITING_INPUT → QUEUED); `execute` (API with an approving decision; APPROVED, EXECUTING);
  `recover` — "Created by `mark_unknown` (worker timeout path); the worker after a `cancelled`/`expired` tool result;
  `reclaim_leases` (sweeper). Never by either MCP server." (EXECUTING, OUTCOME_UNKNOWN, ESCALATED,
  ABANDONED_UNVERIFIED).
- SA:346: "`expire_proposals`, `sync_memberships`, `sweep_wakeups`, `deliver_outbox` | Scheduler (sweeper role) |
  Maintenance | none | n/a (no run lease)".

### 2.5 AM-20.2 grant rows (SA:408–442)

| Table (SA line) | `api` | `worker` | `sweeper` | `app_definer` | others |
|---|---|---|---|---|---|
| `run_lease` (SA:418) | — | sel, ins, upd(all) | sel, upd(`lease_until`) (reclaim) | sel | — |
| `jobs` (SA:419) | ins (`resume_input` only) | sel, ins, upd(`claimed_by`, `claimed_at`, `done_at`, `attempts`) | sel, ins, upd(same) | ins, sel | — |
| `invocation_context` (no RLS) (SA:420) | — | ins | sel | sel, upd(`revoked_at`) | — |
| `model_permit` (SA:432) | — | sel, upd(all) | upd(`leased_until`) (reclaim) | — | — (seeded by `migrator`) |
| `runs` (SA:415) | sel, upd(`cancel_requested`, `cancel_requested_at`) | sel, upd(`checkpoint_id`, `budget_used`) | sel | ins, sel, upd(state…`supersedes_run_id`) | — |
| `sessions` (SA:413) | sel, ins, upd(`last_seen_at`, `revoked_at`), del | — | del (expired) | — | — |

SA:437: "`mcp_read`, `mcp_exec` and `operator` have **no table grants**". SA:440: "Seed data (tenants, personas'
memberships, the `model_permit` row) is written by `migrator` data migrations under `BYPASSRLS`; no runtime role can
insert it [R7-H4]." Note the column names: `run_lease.lease_until` but `model_permit.leased_until` (and
`outbox.leased_until`, SA:427).

### 2.6 AM-20.3 rows that mention `run_lease` or the fence (SA:444–474), verbatim

- Preamble SA:446: every function "first resolves `tenant_id` through `run_directory` (or the handle) and sets
  `app.tenant_id` with `set_config(name, value, true)` … before touching tenant rows, takes locks in the AM-12 order,
  and raises `authority_violation` when `session_user` is not an allowed caller."
- **`freeze_proposal`** (SA:453) — caller `worker`; locks "advisory(tenant, asset) → `run_lease` FOR SHARE → `runs` FOR
  UPDATE → `proposals`".
- **`resolve_invocation(raw_handle, client_azp)`** (SA:459) — `mcp_read`, `mcp_exec`; locks "`invocation_context` FOR
  SHARE → `run_lease` FOR SHARE"; effect "…checks azp binding, **that the handle's server matches the calling role**
  …, expiry, current run fence; returns `{run_id, tenant_id, job_type, run_state, attempt_state, allowed_tools}`".
  `asset_scope` and `search_procedures_scoped` (SA:460–461): locks "as above".
- **`grant_execution(raw_handle, proposal_id)`** (SA:462) — `mcp_exec`; locks "advisory(tenant, asset) → `run_lease`
  FOR SHARE → `runs` FOR UPDATE → `proposals` FOR SHARE → `decisions` FOR SHARE → `memberships` FOR SHARE →
  `execution_grant` → `action_attempt`".
- **`mark_sent(action_id)`** (SA:463) — `mcp_exec`; inputs "action ID"; locks "`run_lease` FOR SHARE → `runs` FOR
  UPDATE → `action_attempt_state`".
- **`record_outcome(action_id, outcome, receipt_or_tombstone)`** (SA:464) — `mcp_exec`; locks "`run_lease` FOR SHARE
  → `runs` FOR UPDATE → `action_attempt_state` → `events`". `request_abort` (SA:465): locks "as `record_outcome`".
- **`lookup_action(raw_handle)`** (SA:466) — `mcp_exec`; locks "`run_lease` FOR SHARE".
- **`mark_unknown(run_id, fence)`** (SA:467) — `worker` (transport-timeout path, AM-13); locks "`run_lease` FOR UPDATE
  → `runs` FOR UPDATE → `execution_grant` FOR SHARE"; effect "Bumps the fence (revoking handles); if a grant exists,
  transition EXECUTING → OUTCOME_UNKNOWN and inserts a `recover` job"; event `action.uncertain`.
- **`reclaim_leases()`** (SA:471) — `sweeper`; inputs none; locks "`run_lease` FOR UPDATE"; effect "Expired leases
  become reclaimable; stale `model_permit` released; lost wake-ups re-enqueued (dedup keys)"; event none.
- **`revoke_handles(run_id, fence)`** (SA:472) — `worker`; locks "`run_lease` FOR SHARE → `invocation_context`";
  effect "Sets `revoked_at` on the run's handles (the worker has no column grant for this) [R7]".
- Rows with no lease lock: `create_run` (SA:450, `runs` slot index), `transition_run` (SA:451, "`runs` FOR UPDATE",
  caller `worker`), `append_event` (SA:452, callers `api`, `worker`, `sweeper`; "`runs` FOR UPDATE"), `escalate_run`
  (SA:468, `worker`, `sweeper`; "`runs` FOR UPDATE").

### 2.7 AM-20.4 jobs, handles and dedup keys (SA:492–506)

- SA:494: "`jobs(id, type, run_id, dedup_key UNIQUE, available_at, claimed_by, claimed_at, attempts, done_at)`."
- SA:496: "`invocation_context(handle_sha256 PK, run_id, job_id, server ∈ {read, write}, fence, azp, expires_at,
  revoked_at)`. `resolve_invocation` derives `job_type` from the referenced `jobs` row and `server` from that type …;
  it never trusts the worker-written `server` column alone [R7]."
- SA:503: "`recover` | `mark_unknown`, `worker` (after a `cancelled`/`expired` result), `reclaim_leases` |
  `action_id:trigger` where trigger ∈ {`timeout`, `cancel`, `deadline`, `sweep:<bucket>`}"; SA:504: maintenance jobs
  `name:<minute bucket>`.
- SA:506: "`recover` jobs on ESCALATED or ABANDONED_UNVERIFIED runs run on a bounded cadence: every 5 minutes for the
  first hour, then hourly, with a cap of 48 attempts…"

### 2.8 AM-20.5 RLS (SA:508–524)

- SA:510: `jobs` is a tenant table with `tenant_isolation`; SA:520: "`memberships` and `jobs` carry one extra policy,
  `sweeper_all FOR ALL TO sweeper USING (true)`…".
- SA:523: "`run_directory`, `invocation_context`, `run_lease`, `sessions`, `idempotency_request`,
  `operator_resolutions`, `model_permit`, `tenants` and `app.test_clock` have **no RLS**; their grants (AM-20.2) are
  the control."

### 2.9 AM-20.7 item 9 and AM-31

- SA:564: "**Fault hooks are test-only.** They exist only in an app factory, shared as `core.testing.faults`, that
  refuses to start unless `PROFILE=test` (R098; first used in T10, completed in T13). The test clock is governed by
  AM-20.6, not by `PROFILE`." SA:49: "**R098's \"default\" profile** means the `dev` and `demo` profiles."
- SA:596: `ChatOllama(…)` "60 s timeout"; SA:597: warm-up before the worker "accepts drafting jobs"; SA:619 (T02
  probe records): "**cancellation behaviour:** cancel mid-generation, then check `ollama ps`/GPU and the next request's
  start latency." SA:205 ties the `model_permit` release rule to that measurement.

### 2.10 BUILD_SPEC

- BS:334 (§8): "Admission transaction: message + run + job + initial event. Lease an eligible job using a short
  PostgreSQL transaction; commit before network/model work. Initial proposed lease is 30 seconds, heartbeat every 10
  seconds, reclaim after expiry using database time. Each lease acquisition increments a monotonic fence. All mutating
  application commits compare current owner/fence and expected run version. Never keep a transaction open through
  inference or a human wait. `SKIP LOCKED` is appropriate for queue-like consumers, not proof of exactly-once work.
  [S10]"
- BS:336: "Serialize state-changing operations per run/conversation. … Limit global active compute separately from
  queue length."
- BS:338: "**Fence checkpoint writes too.** … Implement a checkpointer adapter whose write transaction validates the
  active lease/fence against PostgreSQL before committing checkpoint changes. … If compatible transactional fencing
  cannot be implemented, keep the distributed-worker gate blocked; a documented single-writer development profile is
  not a substitute for passing that target gate." (Superseded for v1 by SA:46.)
- BS:340: "Avoid lost wakeups: user replies/approvals commit with a unique resume job. … A sweeper compares pending user
  events, jobs, checkpoints and authoritative run state, and re-enqueues a deduplicated wake-up…"
- BS:360/364 (§9): the handle is bound to "…run ID, job ID, current fence, allowed tool names and a maximum 60-second
  expiry. Refresh it only while the lease is current."; "Rotate/revoke handles on lease loss, cancellation, policy
  change and completion."
- BS:405 (§10), the nine faults: "Hooks must support response loss after commit, timeout before acceptance, delayed
  receipt visibility, malformed response, mismatching receipt hash, rate limit, transient unavailable, definitive
  no-commit failure and concurrent same-key submission." BS:595: "Fault injection must target the real transaction
  boundaries being claimed."
- BS:472 (§13 final gate): the write boundary must "…enforce expiry/freshness/cancellation, and compare the active
  lease fence. … Commit before destination I/O."
- BS:542–558 (§17): "All numeric limits below are **starting project defaults**… Put them in validated configuration
  and write boundary tests." Rows: BS:548 "Active runs | One state-mutating run per conversation; one active compute
  lease per requester"; BS:549 "Global model concurrency | 1 initially; increase only after measured capacity"; BS:550
  "Queued work | 100 total initially; bounded tenant quotas; reject clearly when full"; BS:555 "Active compute
  duration | 90 seconds total; each model attempt max 60 seconds clipped to remaining budget"; BS:556 "Human wait |
  Does not consume active compute budget or hold a worker/DB transaction"; BS:557 "Lease / heartbeat | 30-second lease
  / 10-second heartbeat, database clock"; BS:558 "Invocation handle | At most 60 seconds, additionally bounded by
  current lease and policy".
- BS:682 (§24): "Worker crash / expired lease | Fence stale app/checkpoint writes; reclaim job; reconcile already
  dispatched actions". BS:681: "Database outage | Reject uncommitted admission; no volatile accepted job; recover
  lease/outbox safely". BS:687: "Overload | Bounded queues/concurrency, clear rejection, no retry storm…".
- BS:588 (§19): real PostgreSQL tests cover "…pooled tenant context, concurrent decisions, job leases/fencing,
  checkpoint writes, outbox/wakeup crash windows."
- BS:705 (§25): "M04 — Jobs and persistence | Leases, heartbeat/fencing, checkpoint adapter, event journal, outbox and
  wake-up sweeper | Concurrent stale-worker/checkpoint denial and crash-window recovery".

---

## 3. The tree as it is (branch `plan-h`, `954ef58`)

### 3.1 Every "T13" debt line outside docs/reviews and docs/superpowers (`git grep -n T13`)

Code and migrations:

| Where | Text (verbatim) | What it asks for |
|---|---|---|
| `core/src/ops_core/persistence.py:8` | "Pools arrive with T13." | a connection pool |
| `core/src/ops_core/persistence.py:139` | "TODO(T13): a pool." (`Session` docstring) | same |
| `core/src/ops_core/persistence.py:283` | "Every live handle of the run is revoked (BS:364); the fence argument is T13's." | pass a real fence to `revoke_handles` |
| `core/src/ops_core/persistence.py:544-545` | "TODO(T13): lease + fence + wake-ups instead of polling." (`claim_job`) | lease on claim; wake-ups |
| `core/src/ops_core/persistence.py:568` | "TODO(T13): bounded retries." (`requeue_job`) | a retry bound |
| `core/src/ops_core/privileges.py:8` | "…model_permit → T13) add their rows." | the `model_permit` grant row |
| `core/src/ops_core/testing/faults.py:3` | "(incident-sim here, the application services with T13)" | app-service hooks |
| `core/src/ops_core/testing/faults.py:15` | "The three BS:405 faults T10 implements; T13 adds the other six." | six more kinds |
| `api/src/ops_api/store.py:922` | "TODO(T13): keep a per-unit lock_timeout once the connection pool lands." | lock_timeout per unit under a pool |
| `mcp-write/src/ops_mcp_write/execution.py:31` | "A lease fence (T13/T22) will raise VersionConflict on exactly this path (final review I1)." | post-SENT refusal handling |
| `migrations/app/versions/0002_roles_grants_rls.py:307` | "the lease (T13 fills it)" | `run_lease` rows |
| `migrations/app/versions/0003_run_path_functions.py:410` | "TODO(T13): compare p_fence with run_lease.fence once leases exist; until then every live handle of the run goes." | fenced `revoke_handles` |
| `migrations/app/versions/0004_write_path_functions.py:12` | "Asset guard, lease fence, expiry and freshness are T13/T21." | fence in write path |
| `migrations/app/versions/0004_write_path_functions.py:301` | "TODO(T21): asset freshness (5 min) and the asset guard; TODO(T13): the lease fence." (0004 `grant_execution`, superseded by 0005) | fence in the gate |
| `migrations/app/versions/0004_write_path_functions.py:488` | "TODO(T13): bump run_lease.fence (p_fence) here; until leases exist the handles are revoked directly." | fence bump in `mark_unknown` |
| `migrations/app/versions/0005_sessions_login_logout.py:140` | same text as 0004:301 (the live `grant_execution` body) | fence in the gate |
| `sweeper/src/ops_sweeper/main.py:10` | "TODO(T13/T14/T21): leases, wake-ups, outbox, proposal expiry." | lease reclaim |
| `worker/src/ops_worker/handlers.py:8` | "No lease, fence or heartbeat (debt → T13), no LangGraph (→ T20)." | lease, fence, heartbeat |
| `worker/src/ops_worker/handlers.py:112` | "No reclaim until T13: a run left in DRAFTING would hold its conversation slot with the job claimed forever." | reclaim |
| `worker/src/ops_worker/handlers.py:199` | "TODO(T13): bounded retries; TODO(T22): reconciliation." (transport failure) | retry bound |
| `worker/src/ops_worker/handlers.py:205` | "TODO(T13): bounded retries (a sweeper that never returns re-queues this job every 30 s for ever)." (GRANT_DEFERRED) | retry bound |
| `worker/src/ops_worker/main.py:41` | "A failed handler is logged and its job stays claimed (T13 reclaims)" | reclaim |
| `worker/src/ops_worker/main.py:58` | "a crashed handler leaves the job claimed for T13's reclaim; the loop lives on" | reclaim |
| `worker/README.md:19` | "Lease, fence, heartbeat and LangGraph: T13/T20." | — |
| `sweeper/README.md:20` | "Leases, wake-ups, the outbox and proposal expiry: T13/T14/T21." | — |

Status documents (`SESSION_STATE.md`, verbatim or near-verbatim; line numbers as of `954ef58`):

- `:5` "Next is Plan H: T13 (leases, wake-ups and the lease fence; it now also owns the global queue bound)".
- `:65` critical path "T01→T04→T05→T08→T09→T13→T15→T16→T20→…".
- `:156` (Plan D shortcuts): "polling worker without reclaim (T13/T14)".
- `:165` (Plan D open items): "the token verifier propagates a non-transport exception from an injected fetch (test
  code only; T13);".
- `:190`: "the eleven definer functions without a caller arrive with T11, T13, T15-T17, T21 and T22".
- `:193`: "the lease fence (binding the raw handle for `mark_sent` and `record_outcome`) -> T13/T22;".
- `:194`: "untested branches -> T13/T22: FAILED_NO_COMMIT from SENT, CONFLICT on EXECUTING, redispatch, `mark_sent` on
  a cancelled run, `freeze_proposal` ANSWER_ONLY / SUPERSEDES_MISMATCH / revision, `grant_execution` NO_APPROVAL /
  CANCELLED / MEMBERSHIP_INACTIVE, a write handle at mcp_read;".
- `:195`: "the six remaining BS:405 faults -> T13".
- `:196`: "the pre-SENT `STALE_RUN` / `HASH_MISMATCH` envelopes and the expired-handle read-back have no dedicated test
  -> T13/T47;".
- `:198`: "a zero-orphan case for `skeleton.py keys` needs a clean database pair -> T32/T13; a shared connect-and-assert
  helper for the three servers (the MCP lifespans duplicate it and incident-sim never closes its connection) ->
  T13/T30; the `testclock` branch revision still renders its grantee tuples from the live matrix (freeze them in the
  next migration task)."
- `:218` (Plan F): "the `GRANT_DEFERRED` re-queue has no retry bound (TODO T13 at the branch…)".
- `:222` (Plan F final review): "a close that raises during startup cleanup masks the original error (T13/T30)".
- `:247-249` erratum 39 (§4); `:303-305` (Plan G open items): "`create_app` sets `app.state.store.faults = faults` on
  whatever the store factory returns … passing faults into the store would be cleaner -> T13 (fault factory); the
  global queue bound (BS:550 \"100 total\") is unreachable by the `api` role under RLS; only the per-tenant quota
  exists -> T13".
- `:316`: "the reply unit sets `lock_timeout = 2s` before its `FOR UPDATE` (a 55P03 is the retryable 503;
  `TODO(T13)`)".
- Walking-skeleton debt: `:328` "plain INSERTs and UPDATEs instead of … `resolve_invocation` → T09/T13/T22;"; `:330`
  "no lease, fence, heartbeat or model permit → T13;"; `:340` "the worker claims jobs with `FOR UPDATE SKIP LOCKED`
  and polls; no wake-ups, no outbox, no reclaim of a job whose handler crashed (its run and conversation slot stay
  held) → T13/T14;"; `:346` "an execute job whose write call cannot reach mcp-write is re-queued every 30 s without a
  retry bound → T13/T22;"; `:347` "no reconnect after a database restart: every process must be restarted → T13;".
- Plan E debt: `:354` "… `reclaim_leases` → T13;"; `:355` "`run_lease` exists with no lease taken;
  `resolve_invocation`, `grant_execution`, `mark_sent` and `record_outcome` check no fence; `mark_unknown` and
  `revoke_handles` accept `fence` and ignore it; no asset-guard advisory lock → T13/T21;"; `:356` "the worker polls
  per tenant (one claim attempt per tenant per poll) → T13 wake-ups;"; `:363` "the fault factory implements
  `reject_next`, `drop_before_commit` and `lose_after_commit`; the other six BS:405 faults → T13;"; `:364` "…
  `model_permit` are absent, so their AM-20.2 rows are not yet in the grant matrix → T14/T12/T22/T17/T13;".
- Plan F debt `:375`: "the sweeper runs `sync_memberships` and the expiry purges only; `expire_proposals`,
  `sweep_wakeups`, `deliver_outbox` and lease reclaim → T13/T14/T21;".
- Plan G debt `:386-387`: "the global queued-work bound (BS:550 \"100 total\") is not enforced: `api` can count only its
  own tenant's runs and cannot read `jobs` (Plan G spike §8); a per-tenant quota of QUEUED runs
  (`OPS_TENANT_QUEUE_QUOTA`) stands in → T13;"; `:397-398` "`api` may INSERT any job type (the column grant cannot
  restrict `type`, Plan G spike §2); the API inserts `resume_input` only, by code → T13/T22;"; `:403-405` "the API's
  fault route implements `drop_before_commit` only; the other BS:405 faults, `lose_after_commit` included (R015's
  after-commit side is proved meanwhile by R016's replay of the recorded 202) → T13."
- `STATUS.md:121`, `:131` "leases (T13) … stay `NOT_RUN`"; `:156` "the global queue bound -> T13".
- `docs/PROJECT_HISTORY.md:147` (Plan E final review I1): "After SENT, a refusal the database maps to Python (a stale
  version, a hash mismatch) became an error envelope rather than UNKNOWN… the lease fence planned for T13 raises
  exactly that refusal on exactly that path."
- `tests/` contains no "T13" mention.

### 3.2 `run_lease`, `invocation_context`, `model_permit` in the schema

- **`run_lease`** is created by `0002_roles_grants_rls.py:316-322`: `run_id uuid PRIMARY KEY REFERENCES app.runs
  (run_id), owner text NOT NULL, lease_until timestamptz NOT NULL, fence bigint NOT NULL DEFAULT 1`. No index besides
  the PK, no `tenant_id`, no RLS (`privileges.NO_RLS`, `privileges.py:147-158`). Downgrade drops it (`0002:432`).
  Grants (`0002:94-98`, frozen; live matrix `privileges.py:107-111`): worker `sel, ins, upd(all)`; sweeper `sel,
  upd(lease_until)`; app_definer `sel`. No migration, function or Python code reads or writes `run_lease` (the only
  hits are the DDL, the grants and the two TODOs at `0003:410`, `0004:488`). No row is ever inserted.
- **`invocation_context`**: created in `0001_walking_skeleton.py:121-131` (`handle text PK, run_id … REFERENCES
  runs, job_id … REFERENCES jobs, server CHECK IN ('read','write'), fence integer NOT NULL DEFAULT 1, azp, expires_at,
  revoked_at, created_at`); `0002:304-306` truncates it, drops `handle`, adds `handle_sha256 text PRIMARY KEY` and
  makes `fence` `bigint`. Grants (`0002:107`): worker `ins`; sweeper `sel`; app_definer `sel, upd(revoked_at)`. No RLS.
- **`mint_handle`** (`persistence.py:613-623`) inserts `(handle_sha256, run_id, job_id, server, azp, expires_at =
  app.current_time() + ttl)` with `ttl_seconds=60`; it does **not** set `fence` (the column default 1 applies).
- **`revoke_handles`** (`0003:403-416`): `_authority(['worker'])`, `_tenant_of_run`, then (no lock)
  `UPDATE invocation_context SET revoked_at = app.current_time() WHERE run_id = p_run_id AND revoked_at IS NULL`;
  `p_fence` unused. Python wrapper passes the literal `1` (`persistence.py:282-285`).
- **`resolve_invocation`** (`0004:239-251`) calls `_resolve_handle(raw, azp, 'read'|'write' by session_user)`
  (`0004:65-106`): looks up `invocation_context` by `encode(sha256(convert_to(p_raw_handle,'UTF8')),'hex')` **without
  a lock**; refuses (OC008) if absent, revoked, `expires_at <= app.current_time()` or azp differs; derives the server
  from `jobs.type`; reads `runs` (no lock) and the latest attempt. It reads neither `run_lease` nor
  `invocation_context.fence`. Returns `run_id, job_id, job_type, tenant_id, conversation_id, run_state,
  attempt_state` (erratum 19).
- **`model_permit`** exists nowhere: no migration, no `privileges.GRANTS` row, no `NO_RLS` entry, no code. Mentions:
  `privileges.py:8` (owner T13), `scripts/probe.py:57,283,369` (the T02 release rule), `SESSION_STATE.md:330,364`,
  `docs/ARCHITECTURE.md:61` (worker's table list).

### 3.3 `jobs`, `claim_job`, `finish_job`, `requeue_job`

- DDL `0001:107-118`: `id uuid PK, type text NOT NULL` (no CHECK on `type`), `run_id … REFERENCES runs, dedup_key text
  NOT NULL UNIQUE, available_at timestamptz NOT NULL DEFAULT now(), claimed_by text, claimed_at timestamptz, attempts
  integer NOT NULL DEFAULT 0, done_at timestamptz, created_at timestamptz NOT NULL DEFAULT now()`. Index `0001:119`:
  `CREATE INDEX jobs_claimable ON app.jobs (available_at) WHERE done_at IS NULL AND claimed_at IS NULL`. `0002:230-237`
  adds `tenant_id uuid`, makes `run_id` nullable, composite FK `(tenant_id, run_id)` and `jobs_tenant_iff_run_check
  CHECK ((run_id IS NULL) = (tenant_id IS NULL))` (maintenance jobs are tenant- and run-less). RLS: `tenant_isolation`
  plus `sweeper_all` (`privileges.SWEEPER_ALL`, `privileges.py:146`).
- Grants (`0002:99-106`; `privileges.py:112-117`): api `ins`; worker `sel, ins, upd(claimed_by, claimed_at, done_at,
  attempts, available_at)` (erratum 11); sweeper `sel, ins, upd(claimed_by, claimed_at, done_at, attempts)`;
  app_definer `sel, ins`. No role holds DELETE on `jobs` (Plan F debt `:380`).
- Job inserters today: `create_run` (`0003:311-312`, `investigate`, key `'<run>:1'`, `available_at =
  app.current_time()`); `record_decision` (`0004:221-222`, `execute`, key `proposal_id`); `mark_unknown`
  (`0004:503-505`, `recover`, key `'<action_id>:timeout'`, `ON CONFLICT (dedup_key) DO NOTHING`); the API's
  clarification reply (`resume_input`, through `insert_job_untargeted`, `persistence.py:477`); the sweeper's
  `insert_maintenance_job` (`persistence.py:576-594`). Dedup-key shapes are validated in `ops_core/jobs.py:150-183`
  (recover trigger regex `timeout|cancel|deadline|sweep:<YYYY-MM-DDTHH:MM>`, `:115`); `RECOVER_CADENCE = (300, 3600,
  48)` (`jobs.py:108`). `JOB_RULES` (`jobs.py:68-106`) lists `recover` creators `("mark_unknown", "worker",
  "reclaim_leases")` and gives maintenance jobs empty `run_states` ("hold no run lease", `:61`).
- `claim_job` (`persistence.py:538-559`), verbatim core:
  `UPDATE app.jobs SET claimed_by = %s, claimed_at = app.current_time(), attempts = attempts + 1 WHERE id = (SELECT id
  FROM app.jobs WHERE done_at IS NULL AND claimed_at IS NULL AND available_at <= app.current_time() ORDER BY
  available_at, id FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *` — run once per tenant after `set_tenant` (Plan E
  ruling 18), inside the caller's transaction; returns the first row found.
- `finish_job` (`:562-564`): `UPDATE app.jobs SET done_at = app.current_time() WHERE id = %s`.
- `requeue_job` (`:567-573`): `UPDATE app.jobs SET claimed_by = NULL, claimed_at = NULL, available_at =
  app.current_time() + make_interval(secs => %s) WHERE id = %s` — "TODO(T13): bounded retries."
- `claim_maintenance_job` (`:597-610`) uses the same SKIP LOCKED shape filtered by `type` and `tenant_id IS NULL`.
- Nothing un-claims a job whose handler crashed: `claimed_at` has no expiry and no reader compares it to time.

### 3.4 The worker (`worker/src/ops_worker/`, 649 lines)

- `main.py` (138 lines): `POLL_SECONDS = 0.5` (`:28`). `run_forever` (`:40-63`): per iteration `async with
  deps.conn.transaction(): order = rotate(tenants, polls); job = claim_job(...)` — the claim **commits** before the
  handler runs (`:46-48`); then `await handlers.handle(deps, dict(job))` (`:51`). `psycopg.OperationalError` with a
  broken/closed connection re-raises (process exits non-zero, `:53-56`); other OperationalErrors and any other
  exception are logged and the loop continues (`:57-59`). `health_app` (`:66-82`) serves `/health/live`,
  `/health/ready` on its own connection. `_main` (`:85-130`) opens **two** autocommit connections as role `worker`
  (`:95` loop, `:97` probe), calls `assert_clock_profile` on the probe (`:98`), `worker_name =
  f"{socket.gethostname()}:{os.getpid()}"` (`:104`), runs the poll task and a uvicorn health server
  (`OPS_WORKER_HEALTH_PORT`, default 8070, `:112`) and exits 1 if either task raised (`:128-130`). `main()`
  (`:133-138`): `asyncio.run(_main(), loop_factory=asyncio.SelectorEventLoop)` on win32; the module docstring
  (`:1-2`): "SelectorEventLoop on Windows (psycopg async refuses the Proactor loop; measured in the Plan D spike)".
  No thread, no lease, no heartbeat.
- `handlers.py` (235 lines): `Deps` (`:41-49`) holds one `conn`. Every unit is `async with
  deps.conn.transaction()` on that single connection.
  - `investigate` (`:69-114`): unit 1 (`:72-86`) `set_tenant`, `run_row(lock=True)` (`SELECT * FROM app.runs …
    FOR UPDATE`, `persistence.py:182-189`), message read, `transition_run(QUEUED→RETRIEVING)`, `mint_handle(READ)`;
    then outside any transaction `tool.started` (own unit), the MCP call, `tool.completed`; unit `transition_run
    (RETRIEVING→DRAFTING)` (`:105-108`); `_draft_and_freeze` (`:117-166`): model call outside a transaction, then one
    unit: `set_tenant`, `INSERT INTO app.drafts`, `append_event(explanation.ready, model_summary)`,
    `freeze_proposal`. The proposal's `now` is the wall clock `datetime.now(UTC)` (`:124`). Failures go through
    `_fail` → `transition_run(…→FAILED)` (`:63-66`).
  - `execute` (`:177-218`): unit `set_tenant`, `run_row(lock=True)`, state check against `JOB_RULES[EXECUTE]`,
    `mint_handle(WRITE)`; MCP `create_incident` outside a transaction; on `McpCallFailed` → `_requeue` (`:169-174`:
    `revoke_handles` + `requeue_job(job, 30)`) "TODO(T13): bounded retries; TODO(T22): reconciliation." (`:199`);
    on a `GRANT_DEFERRED` envelope → `_requeue` (`:204-212`, TODO at `:205`); on an `outcome`/`UNKNOWN` envelope →
    `mark_unknown` (`:214-217`). `EXECUTE_RETRY_SECONDS = 30` (`:30`).
  - `handle` (`:221-235`): dispatch by type (`investigate`, `execute`; every other type, `resume_input` and `recover`
    included, is logged "not handled by the walking skeleton" and finished); then one unit: `revoke_handles(run_id)`,
    `set_tenant`, `finish_job`.
  - The worker does **not** call `mark_unknown` on a transport failure; it re-queues (contrast SA:250–254; erratum 14).
- `mcp.py`: `HttpMcpCaller` opens one httpx2 client per call with `httpx2.Timeout(connect_timeout=10.0, read=60.0)`
  (`:53-56`); transport/protocol failures become `McpCallFailed` (`:60-73`). No cancellation hook.
- `drafting.py`: `make_generator` returns only `FakeDraftGenerator` (`:79-83`, "only 'fake' until T19"); no model
  call, so no `model_permit` consumer exists.

### 3.5 mcp-write's execution path (`mcp-write/src/ops_mcp_write/`)

- `server.py:176-205` (`create_incident` tool): unit 1 `resolve_invocation(handle, azp, tool=CREATE_INCIDENT)`
  (`:182-185`); then `execution.create_incident`. Mapped refusals → envelopes: `HandleRejected` → INVALID_HANDLE,
  `Refused` → refusal code, `NotFound`, `VersionConflict` → `STALE_RUN` ("Only grant_execution and mark_sent can raise
  this here, both before this call sends anything", `:193-196`), `HashMismatch`.
- `execution.py:79-124`: unit `grant_execution(handle, proposal_id)` (`:81-82`); unit `mark_sent(action_id)`
  (`:87-88`, "committed here, before any I/O"); POST to incident-sim outside a transaction; unit
  `record_outcome(action_id, outcome)` (`:116-117`); read-backs via `lookup_action(handle)` (`:70-71`).
  `execution.py:29-32`: "The refusals the database maps to Python. Before SENT they are honest error envelopes
  (server.py); after SENT they must not be, because the destination may have committed: the only answers then are a
  recorded outcome or UNKNOWN (AM-13). A lease fence (T13/T22) will raise VersionConflict on exactly this path (final
  review I1)." `_POST_SENT_REFUSALS = (persistence.PersistenceError, IllegalTransition, EventRuleViolation)`.
- `mark_sent` and `record_outcome` receive only an `action_id`; the handle is available to mcp-write in the same
  call (`execution.create_incident(deps, handle=…)`) but is not passed to either function.
- Connection: one autocommit connection as `mcp_exec` wrapped in `persistence.Session` (`server.py:216-230`);
  `assert_clock_profile` at start.

### 3.6 Definer bodies: locks taken today, in order, and their T13 notes

| Function (current body) | Locks today, in order | Fence today | T13/T21 note |
|---|---|---|---|
| `transition_run` (`0003:323-353`) | `runs` FOR UPDATE (`:339`), then `_transition` re-takes `runs` FOR UPDATE (`:204`) and `_append_event` again (`:176`) | none; no fence argument | — |
| `append_event` (`0003:357-379`) | `_append_event`: `runs` FOR UPDATE (`:176`) for `next_event_seq` | none | — |
| `revoke_handles(run_id, fence)` (`0003:403-416`) | none; UPDATE `invocation_context` | `p_fence` ignored | `:410` TODO(T13) |
| `freeze_proposal(run_id, draft_id, bytes, expires_at)` (`0004:108-167`) | `runs` FOR UPDATE (`:123`); reads drafts, proposals; INSERT proposals; UPDATE runs; `_transition` | none; no fence argument | `:159` "TODO(T21): the asset guard (advisory lock, AM-13) and BLOCKED_REVIEW on refusal." |
| `record_decision` (`0004:171-235`) | `runs` FOR UPDATE (`:197`) — "runs FOR UPDATE is the only lock" (`:195`) | n/a (API) | — |
| `resolve_invocation` / `_resolve_handle` (`0004:239-251`, `:65-106`) | none | none | — |
| `grant_execution(raw_handle, proposal_id)` (live body `0005:82-154`) | `_resolve_handle` (no lock); `runs` FOR UPDATE (`0005:97`); reads `execution_grant`, proposals, decisions, memberships (no lock, ruling 23); INSERT grant, attempt, INTENT; `_transition` | none | `0005:140` "TODO(T21): asset freshness (5 min) and the asset guard; TODO(T13): the lease fence." |
| `lookup_action(raw_handle)` (`0004:335-352`) | `_resolve_handle` (no lock); reads `execution_grant` | none | — |
| `mark_sent(action_id)` (`0004:355-391`) | `_tenant_of_action` (walks `tenants`); reads grant; `runs` FOR UPDATE (`:366`); latest attempt; refuses OC003 unless `EXECUTING` | none; comment `:373-374`: "the handle revocation is the fence, and the caller holds only an action_id, so it cannot see that fence itself" | `:379` "TODO(T22): the dispatch deadline." |
| `record_outcome(action_id, outcome, doc)` (`0004:395-474`) | `_tenant_of_action`; reads grant; `runs` FOR UPDATE (`:408`); latest attempt; INSERT RESOLVED; `_transition`; event | none | — |
| `mark_unknown(run_id, fence)` (`0004:478-510`) | `runs` FOR UPDATE (`:487`); UPDATE `invocation_context` revoked_at (all live handles, `:489`); `_transition`; INSERT `recover` job | `p_fence` ignored; Python passes `1` (`persistence.py:288-293`) | `:488` "TODO(T13): bump run_lease.fence (p_fence) here; until leases exist the handles are revoked directly." |
| `create_run` (`0003:238-319`) | unique slot index; INSERT runs, run_directory, history, jobs; `_append_event` (runs FOR UPDATE) | n/a | does not insert a `run_lease` row |

No function takes an advisory lock; no function reads `run_lease`. `reclaim_leases`, `request_abort`, `escalate_run`,
`resolve_escalation`, `create_revision`, `request_cancel`, `expire_proposal`, `create_manual_proposal`, `asset_scope`,
`search_procedures_scoped` do not exist (Plan E debt `:354`). `privileges.DEFINER_FUNCTIONS` (`privileges.py:167-183`)
lists the 14 that exist.

**Row-lock privilege fact (Plan E ruling 23, `docs/superpowers/plans/2026-10-08-first-slice-e-roles-rls-definers.md:65`;
erratum 17):** "a row lock needs UPDATE on at least one column and AM-20.2 gives `app_definer` `sel`/`ins` only on
those tables (measured in round 1: 42501 on every call)." The definer functions run as `app_definer`; AM-20.2 gives
`app_definer` **`sel` only on `run_lease`** (SA:418) and nothing on `model_permit` (SA:432). The `worker` holds
`upd(all)` on `run_lease` and so may lock it directly; the sweeper holds `upd(lease_until)` and may lock it too.

### 3.7 The clock

- `app.current_time()` (`0002:365-384`): `LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = app, pg_temp
  SET app.tenant_id = ''`; returns `clock_timestamp()` when `to_regclass('app.test_clock') IS NULL`, else
  `clock_timestamp() + coalesce(offset, '0')` read by dynamic `EXECUTE 'SELECT clock_offset FROM app.test_clock LIMIT
  1'`; owner `app_definer`; EXECUTE granted to api, worker, sweeper, mcp_read, mcp_exec, operator (`0002:417-420`) and
  to `test_harness` on the testclock branch (`tc_0001:45`). Python wrapper `persistence.current_time`
  (`persistence.py:489-500`).
- `tc_0001_test_clock.py`: one-row table `(one boolean PK CHECK (one), clock_offset interval NOT NULL DEFAULT '0')`;
  `test_harness` gets ins/upd/del, `app_definer` sel. Applied only by `skeleton.py migrate` under the test profile.
- Tests move time with a `test_harness` role connection: `UPDATE app.test_clock SET clock_offset = interval '2 hours'`
  and reset to `'0'` (`tests/e2e/test_admission_live.py:289-335`, `tests/e2e/test_clock_live.py:29-52`). The offset is
  global to the database: every role's `app.current_time()` moves together. Spike fact (Plan G spike §9): offset 0 is
  −1 to −3 µs from `clock_timestamp()`.
- Wall-clock uses that remain: the worker's proposal `now` (`handlers.py:124`); the sweeper's minute bucket
  (`sweeper/main.py:123-124`, "a wall-clock label"); column defaults `now()` on `jobs.available_at`/`created_at`
  (`0001:112,117`).

### 3.8 The fault factory and its users

- `core/src/ops_core/testing/faults.py` (53 lines): `FaultKind(StrEnum)` with `REJECT_NEXT = "reject_next"` ("the
  next POST writes a permanent REJECTED key (reason policy)"), `DROP_BEFORE_COMMIT` ("the next POST answers 503 and
  writes nothing"), `LOSE_AFTER_COMMIT` ("the next POST commits, then the response is lost (503)"); `Faults(profile)`
  raises `FaultsDisabled` unless `Profile.TEST` (`:29-32`); `arm(kind, count)`, `take(kind) -> bool`, `armed()`.
  In-memory, per process; no persistence, no thread safety, no framework.
- **incident-sim** (`incident-sim/src/ops_incident_sim/app.py`): `create_app(…, profile, faults)` builds `Faults` under
  TEST and raises `ValueError` if `faults` is passed in another profile (`:122-125`); `POST /internal/faults/{kind}`
  is registered only when `faults is not None` (`:234-246`), guarded by the workload-token dependency `caller`
  (`:141-147`); body `{"count": n}`. Hot path: `reject_next` (`:199`), `drop_before_commit` (`:207-208`, 503 before
  the commit), `lose_after_commit` (`:211-212`, 503 after `st.commit`). `production_app` passes
  `profile=settings.profile()` (`:267-268`).
- **API** (`api/src/ops_api/app.py`): `faults = Faults(profile) if profile is Profile.TEST else None` (`:153`); the
  lifespan sets `app.state.store.faults = faults` (`:159`); the route `POST /internal/faults/{kind}` (`:678-692`) is
  registered only under TEST, depends on `browser_mutation` (identity plus CSRF/origin in cookie mode, `:228-234`),
  is exempt from the Idempotency-Key (erratum 35), and refuses every kind but `drop_before_commit` with 422
  (`:688-689`). Hot path `store.py:549-552`: after `create_run`, before the record and commit, `raise
  psycopg.OperationalError("fault: drop_before_commit")`. `Store` protocol declares `faults: Faults | None`
  (`store.py:653`); `AdmissionStore.faults` default `None` (`:347`). `production_app` passes
  `profile=settings.profile()` (`app.py:746`).
- Worker, sweeper, mcp-read and mcp-write have no fault hook. The worker and sweeper each run a Starlette health app
  (`worker/main.py:66-82`, `sweeper/main.py:156-173`); mcp-write/mcp-read mount the MCP app beside health routes.
- Tests: `tests/plan_e/test_faults.py` (refuses outside TEST; arm/take), `tests/plan_e/test_incident_sim_t10.py:116-131`
  (404 outside TEST, 401 bad token, 422 unknown kind), `tests/plan_g/test_api_admission.py:191-209`,
  `tests/e2e/test_admission_live.py:140`.
- BS:405's nine versus the three: implemented kinds are named by their effect, not by BS:405's words. Plan E ruling 13
  (`…first-slice-e-roles-rls-definers.md:56`): "T10 implements three of BS:405's nine faults — `reject_next` (the next
  POST is `REJECTED`), `drop_before_commit` (the next POST answers 503 without writing), `lose_after_commit` (the next
  POST commits the key and then answers 503, so only a lookup recovers it) — and T13 the rest." No repository text maps
  each kind to a BS:405 phrase. Not implemented anywhere: timeout before acceptance, delayed receipt visibility,
  malformed response, mismatching receipt hash, rate limit, and (as a hook) concurrent same-key submission (R047's
  concurrency is tested directly with `asyncio.gather`, `tests/e2e/test_incident_sim_live.py:90,103`).

### 3.9 The sweeper (`sweeper/src/ops_sweeper/`, 351 lines)

- `main.py`: one loop connection and one probe connection as role `sweeper` (`:184`, `:186`); `assert_clock_profile`
  and `assert_relation("app.idempotency_request")` on the probe (`:188-189`). `tick` (`:111-117`): `run_sync`
  (Keycloak listing + `sync.sync_memberships`), then `record_sync` (`:120-135`: insert, claim and finish this minute's
  `sync_memberships` job in one transaction), then `sync.purge_expired` (DELETEs on `sessions`, `login_state`,
  `logout_jti`, `idempotency_request`, `sync.py:88-108`). `run_forever` (`:138-153`): tick every
  `OPS_SYNC_TICK_SECONDS` (default 30, `:199`); a broken connection re-raises and the process exits non-zero.
- No lease reclaim, no un-claim of stale jobs, no re-enqueue of lost wake-ups, no `model_permit` release. The sweeper's
  `sweeper_all` policy on `jobs` and its `upd(claimed_by, claimed_at, done_at, attempts)` cells are unused except for
  its own maintenance rows.
- `sync_memberships` is a sweeper routine with direct grants, not a definer function (erratum 26).

### 3.10 The API's queue quota (Plan G)

- `core/src/ops_core/settings.py:293`: `tenant_queue_quota: int = 100  # BS:550: queued work, as a per-tenant bound
  (ruling 18)`; `admission()` reads `OPS_TENANT_QUEUE_QUOTA` bounded 1–10000 (`:304-310`).
- `persistence.queued_count` (`persistence.py:531-535`): `SELECT count(*) AS n FROM app.runs WHERE state = 'QUEUED'`
  under the unit's tenant ("RLS scopes the count (spike §8), which is why the bound is per tenant").
- `api/src/ops_api/store.py:418-424`: counted only for a run verdict; `>= quota` raises `QueueFull`; `app.py:291-307`
  maps it to 429 `RATE_LIMITED`, `retryable: true`, `Retry-After: 5`, not recorded. Plan G ruling 18
  (`…first-slice-g-admission-idempotency.md:384-390`): "`api` cannot count across tenants or read `jobs` (spike §8:
  42501), so the global \"100 total\" needs a definer or a grant (debt → T13; erratum 39)."
- Plan G spike §8 (`docs/superpowers/research/2026-10-10-plan-g-spike.md:1665-1676`): as `api`, the QUEUED count is
  per tenant and 0 with no tenant; `SELECT count(*) FROM app.jobs` is 42501; `run_directory` has no state; the
  functions `api` may execute do not count; "**A global queue bound needs a SECURITY DEFINER function or a new
  grant**, either of which is a matrix change."; `pg_stat_user_tables.n_live_tup` is a stale cross-tenant side channel.
- The API's connection: one autocommit connection (`app.py:709`) in a `Session` (`store.py:1000`); the reply unit's
  `SET LOCAL lock_timeout = '2s'` before `runs … FOR UPDATE` (`store.py:915-929`, TODO at `:922`).

### 3.11 `privileges.py` (281 lines) and the grant test

- `privileges.py:7-8`: "Rows exist only for tables that exist; the owners of later tables (outbox → T14, feedback →
  T21, operator_resolutions → T22, documents/chunks/embeddings → T17, model_permit → T13) add their rows." `:9-16`
  lists six departures (proposed errata), including "no definer function takes a row lock on proposals, decisions,
  memberships or execution_grant (a lock needs UPDATE, which the matrix withholds)".
- `run_lease` (`:107-111`): worker `Grant(sel=True, ins=True, upd=True)`; sweeper `Grant(sel=True,
  upd=("lease_until",))`; app_definer `_S`. `jobs` (`:112-117`); `invocation_context` (`:118`). `NO_RLS`
  (`:147-158`) contains `run_lease` and `invocation_context`; no `model_permit`. `DEFINER_FUNCTIONS` (`:167-183`):
  `revoke_handles ("uuid, bigint", ("worker",))`, `mark_unknown ("uuid, bigint", ("worker",))`; no `reclaim_leases`.
- Live check: `tests/e2e/test_roles_live.py:82-95` (`test_r124_every_grantee_holds_exactly_its_matrix_privileges`)
  compares the catalogs to `p.GRANTS` exactly; unit checks `tests/plan_e/test_privileges.py` (every table classified
  once, function-only roles have no table grant, …) and `tests/plan_e/test_transitions_table.py:61`
  (`test_the_newest_revision_of_every_cell_equals_the_live_matrix`): each revision freezes its own cells, so a new
  matrix row ships with a new revision (`0002:28-30`, `0006` pattern). `tests/e2e/test_migrations_and_persistence.py:192`
  (R006) runs upgrade/downgrade/upgrade on a fresh database.

### 3.12 Connections, reconnects, pools

- `persistence.connect` (`persistence.py:119-122`): "One autocommit connection per process (Plan D ruling 24)";
  `psycopg.AsyncConnection.connect(conninfo, row_factory=dict_row, autocommit=True)`; conninfo pins `-c
  timezone=UTC` (`settings.py:74-83`). `Session` (`:136-156`): one `asyncio.Lock` plus `conn.transaction()` per unit.
- Per process: worker 2 connections (loop, probe); sweeper 2; API 1; mcp-read 1; mcp-write 1; incident-sim 1 (its own
  database). Plan D ruling 24 (`…first-slice-d-walking-skeleton.md:65`): "…Pools arrive with T13."
- No process reconnects: worker and sweeper loops re-raise on `conn.broken or conn.closed` and exit non-zero; a
  supervisor restart is the recovery (`worker/main.py:127-130`). SESSION_STATE `:347`: "no reconnect after a database
  restart: every process must be restarted → T13".
- Plan D ruling 23 (`:64`): every process serves uvicorn programmatically under `asyncio.run(…,
  loop_factory=asyncio.SelectorEventLoop)` on win32. `tests/e2e/conftest.py:22-26` installs
  `WindowsSelectorEventLoopPolicy` for pytest-asyncio.

### 3.13 Libraries (`uv.lock`)

- `psycopg 3.3.6` and `psycopg-binary 3.3.6` (`uv.lock:946-964`); core depends on `psycopg[binary]>=3.3,<4`
  (`core/pyproject.toml:6`). The same package provides the synchronous API (`psycopg.connect`/`psycopg.Connection`),
  used today only by `scripts/skeleton.py:152,224,241,245` and `tests/e2e/conftest.py:60`.
- **`psycopg-pool` is not in the lock** (0 matches); only `reference/pyproject.toml:18` names `psycopg[binary,pool]`.
- **`langgraph`, `langgraph-checkpoint-postgres`, `langchain*` are not in the lock** (0 matches). `worker/pyproject.toml`
  dependencies: `["ops-core", "mcp==2.3.0", "uvicorn>=0.54,<1"]`. SA:577–583 lists langgraph 1.2.14,
  langgraph-checkpoint-postgres 3.1.2, langchain-ollama 1.1.0 as observed versions. Plan E open item (`:191`): "R122 …
  -> T20: `langgraph-checkpoint-postgres` is not locked".
- `anyio 4.15.1`, `mcp 2.3.0`, `httpx2 2.13.1`, `uvicorn 0.54.0`, `fastapi 0.143.0`. No service imports `threading`;
  `asyncio.to_thread` appears only in `scripts/probe.py:143`.
- Database image: `pgvector/pgvector:pg17@sha256:…` (`compose.yaml:9`) — PostgreSQL 17.

### 3.14 Test infrastructure

- `tests/e2e/conftest.py` (192 lines): `live` skips unless `OPS_LIVE=1` (`:32-35`); `env` sets `OPS_PG_DB=ops_test`,
  `OPS_INCIDENT_PG_DB=incident_test`, `PROFILE=test` (`:38-48`); `recreate_databases` drops (`WITH (FORCE)`) and
  creates both (`:56-65`); `migrated` (session scope) recreates and runs `skeleton.migrate(Profile.TEST)` (`:68-73`);
  `app_conn` (superuser), `role_conn` (factory of autocommit role connections, all closed after the test, `:87-101`),
  `incident_conn`; autouse `fresh_memberships` stamps `synced_at` (`:114-126`); `purge_run` deletes by `PURGE_ORDER`
  (`:129-145`) — **`PURGE_ORDER` has no `run_lease` delete**, and `run_lease.run_id` references `runs`.
- `scripts/check.py` (105 lines): ruff, ruff format, mypy, pytest; `--profile test` sets `OPS_LIVE=1` and
  `PROFILE=test` for the child (`:56-65`); the default profile is database-free (live tests skip).
- Gates recorded (`SESSION_STATE.md:319-321`, `STATUS.md:144`): `check.py` 816 passed / 104 skipped GREEN;
  `check.py --profile test` 899 passed / 21 skipped GREEN; `verify_handoff` exit 0. `check.py --profile test` needs
  the dev stack up and `skeleton.py status` all down.
- Concurrency patterns that exist: two `worker` role connections each in `transaction(force_rollback=True)` proving
  SKIP LOCKED hands out different jobs (`tests/e2e/test_migrations_and_persistence.py:136-162`); `asyncio.gather` of
  two requests/calls (`test_admission_live.py:227,245`, `test_incident_sim_live.py:90,103`,
  `test_mcp_write_live.py:197`). There is no barrier helper, no `pg_locks`/`pg_blocking_pids` probe, no deadlock
  (40P01) assertion, no thread-based test and no stress harness. `new_run` (`test_migrations_and_persistence.py:31`)
  is the shared live helper that admits a run through `create_run`.
- Unit tests per plan live in `tests/plan_<letter>/` (Plan D ruling 26); a `tests/plan_h/` needs a `testpaths` entry.

### 3.15 Lock orders observed in today's transactions (read from the code)

- Worker `investigate` unit 1: `runs` FOR UPDATE → `messages` read → `runs` (transition) → `run_state_history` →
  `events` → `invocation_context` INSERT.
- Worker `_draft_and_freeze`: `drafts` INSERT → `runs` FOR UPDATE (via `append_event`) → `events` → `runs`
  (freeze_proposal) → `proposals` INSERT → `run_state_history` → `events`.
- Worker `execute` unit 1: `runs` FOR UPDATE → `invocation_context` INSERT; `handle` end unit: `invocation_context`
  UPDATE (via `revoke_handles`) → `jobs` UPDATE; `_requeue`: `invocation_context` → `jobs`.
- `mark_unknown`: `runs` FOR UPDATE → `invocation_context` UPDATE → `run_state_history`/`events` → `jobs` INSERT.
- API admission (Plan G): `pg_advisory_xact_lock(1, hashtext(scope))` (`store.py:761`; erratum 37) → record lookup →
  `messages` INSERT → `create_run` (`runs`, `run_directory`, `run_state_history`, `jobs`, `events`) → record INSERT.
- API clarification reply: advisory scope lock → `runs` FOR UPDATE (lock_timeout 2 s) → `events` read → `messages`
  INSERT → `jobs` INSERT → `events` (append_event re-locks `runs`) → record.
- `record_decision`: `runs` FOR UPDATE → proposals/decisions/memberships reads → `decisions` INSERT → `jobs` INSERT →
  `events`.
- Sweeper sync: `memberships` FOR UPDATE (`sync.py:64-65`) → UPDATE `memberships`.

### 3.16 T02 (model permit release rule) state

- T02 is `DONE_PENDING_OWNER`; the live probe waits for the owner's holdout seal (`SESSION_STATE.md:5`). Its outputs
  `reports/model-probe-qwen3-8b.md` and `data/model-pins.json` (`scripts/probe.py:12,408-412`) do not exist (`data/`
  holds `handoff-fixtures/` and `seed-ids.json`; `reports/` has no probe file). The report template ends "model_permit
  release rule (AM-12, chosen from the cancel row above): [release on cancel | hold until /api/ps idle or the 60 s
  cap]" (`scripts/probe.py:369`).

---

## 4. Prior rulings and proposed errata that constrain T13

- **Erratum 11** (`SESSION_STATE.md:174`): "AM-20.2: the worker also needs `jobs.available_at` and `app_definer` needs
  `runs.updated_at` (UPDATE on those columns)."
- **Erratum 13** (`:176`): signature deviations — "`create_run` takes the request and returns `(run_id,
  state_version)`; `transition_run` takes a detail `jsonb`; `freeze_proposal` takes the stored bytes and verifies a
  requester-asserted `supersedes_run_id` instead of having it injected; …".
- **Erratum 14** (`:177`): "AM-20.3: `mark_unknown` is worker-only; mcp-write reports UNKNOWN to the worker, which
  dispatches an `execute` job for runs left in EXECUTING." Plan E ruling 6 (`…first-slice-e…:49`): if the worker never
  receives the envelope, "the attempt stays `SENT` and the run `EXECUTING`; the execute job is re-queued and the
  replay resends (idempotent at the destination) — T22's reconciliation closes the rest."
- **Erratum 15** (`:178`): "AM-20.6: `app.current_time()` is a definer function callable by every runtime role."
- **Erratum 17** (`:180`): "AM-20.3: the definer functions take no row lock on `proposals`, `decisions`, `memberships`
  or `execution_grant`, because a lock needs UPDATE on the table (plan ruling 23)."
- **Erratum 19** (`:182`): "AM-20.3 `resolve_invocation` returns `job_type`, `job_id` and `conversation_id` instead of
  SA:459's `allowed_tools` (plan ruling 21)."
- **Erratum 22** (`:185`): "`mark_sent` and `record_outcome` carry state guards, and an outcome before SENT is
  refused (Task 4)."
- **Erratum 25** (`:188`): "The sweeper's `del` without `sel` on `sessions` and `idempotency_request` cannot run a
  `DELETE ... WHERE expires_at < ...` (spike section 3)". (The same mechanism applies to any role whose UPDATE has a
  WHERE clause on a column it cannot SELECT; AM-20.2 gives the sweeper `upd(leased_until)` on `model_permit` with no
  `sel`.)
- **Erratum 26** (`:207`): "AM-20.3: `sync_memberships` is the sweeper's routine, not a definer function (SA:470
  against SA:412)." (Precedent for a sweeper job implemented with direct grants instead of the listed definer.)
- **Erratum 37** (`:242-244`): "SA:188: the lock order begins with the idempotency scope's advisory lock, PostgreSQL's
  two-key form `pg_advisory_xact_lock(1, hashtext(<scope>))` (namespace 1, `hashtext`), a lock space distinct from the
  asset guard's one-key locks."
- **Erratum 39** (`:247-249`): "BS:550: T12 bounds QUEUED runs per tenant (default 100); the global bound moves to T13.
  A full tenant queue answers 429 with `Retry-After` and writes nothing…"
- **Plan D ruling 12** (job claiming), **ruling 24** (one autocommit connection per process; "Pools arrive with
  T13"), **ruling 23** (SelectorEventLoop).
- **Plan E ruling 18** (`…first-slice-e…:61`): "The worker claims across tenants by iterating `tenants`. … O(tenants)
  per poll until T13's wake-ups." **Ruling 24** (`:66`): "`insert_job`, `claim_job`, `finish_job` and `requeue_job`
  compare and stamp with `app.current_time()` (SA:156, R126), never `now()`." **Ruling 13**: the fault factory shape
  (§3.8). **Ruling 23**: row locks need UPDATE (§3.6).
- **Plan F ruling (b)** (`SESSION_STATE.md:204`): "The maintenance job row's `available_at` is on `app.current_time()`
  and the sweeper claims the id it inserted".
- **Plan G ruling 18** (queue quota), **ruling 24** (`…first-slice-g…:433-445`): the API's fault route; "the
  `lose_after_commit` fault arrives with T13"; "Cost if wrong: the fault route lives under `/internal`, never
  `/api/v1`."
- No erratum among 1–44 mentions leases, fences, the heartbeat, `model_permit` or `reclaim_leases`. Errata 1–9 (Plan
  C, `SESSION_STATE.md:134-142`) concern transitions, vocabulary and schemas only.

---

## 5. Open questions the planner must rule on

1. **Row locks on `run_lease` inside definer functions.** SA:453/459/462–467/472 put `run_lease` FOR SHARE or FOR
   UPDATE inside functions owned by `app_definer`, and `mark_unknown` must UPDATE `fence` (SA:467). AM-20.2 gives
   `app_definer` `sel` only on `run_lease` (SA:418); a row lock needs UPDATE on at least one column (Plan E ruling 23,
   measured 42501), and an UPDATE needs the column grant. Facts on the other side: the worker holds `upd(all)` and the
   sweeper `upd(lease_until)` (SA:418), so worker- and sweeper-side SQL can lock directly; mcp-read and mcp-write hold
   no table grants (SA:437), so their fence checks can only run inside definers. Erratum 17 is the precedent of
   dropping a spec lock; the alternative is a new `app_definer` cell on `run_lease` (a matrix change, a new revision,
   R124 update).
2. **Who creates the `run_lease` row, and when.** `create_run` (definer, `0003:238-319`) inserts runs, directory,
   history, job and event but no lease, and `app_definer` cannot INSERT into `run_lease`. The worker holds `ins`
   (SA:418). SA:174 describes acquisition as `SELECT … FOR UPDATE` on an existing row; `fence` defaults to 1
   (`0002:321`). Options visible in the facts: a row at admission (needs a definer grant), a row inserted by the
   worker on first acquisition (an INSERT race between two claimers of different jobs for the same run, R087), or an
   upsert. Also open: whether the initial row is "expired" (`lease_until` in the past) so the first acquisition
   passes SA:174's check, and what `owner` holds (`worker_name` is `host:pid`, `worker/main.py:104`).
3. **Lease versus job claim.** SA:173: "Jobs are wake-ups only." Today the claim (`claim_job`) commits
   `claimed_by/claimed_at` before the handler runs and nothing ever un-claims (§3.3). Open: whether acquisition happens
   in the claim's transaction or a separate one; what a worker does with a claimed job whose run's lease is held by a
   live owner (finish it, re-queue it with `available_at`, leave it claimed); whether `jobs.claimed_at` becomes a
   job-level lease the sweeper expires; how a `resume_input` job and an `investigate`/`execute` job of the same run
   contend (R087's "Resume-job vs original-job race"). The worker does not handle `resume_input` yet (finished
   unhandled, `handlers.py:229-230`; T20), so an R087 test needs a handler or a synthetic second job.
4. **Which transactions take FOR UPDATE and which FOR SHARE.** Review note 1 / SA:191: a transaction that will write
   `run_lease` takes FOR UPDATE from the start. Candidates that write it: acquisition, heartbeat renewal, release at
   job end (worker has no DELETE on `run_lease`; release could only be an UPDATE of `lease_until`/`owner`),
   `mark_unknown` (fence bump), `reclaim_leases`. Candidates that only fence: every worker unit in §3.15
   (`transition_run`, `_draft_and_freeze`, `_event`, `mint_handle`, `revoke_handles`, `finish_job`) and every mcp-write
   unit. Open: whether `finish_job`/`requeue_job` units are fenced; whether read-only units (the first `run_row`) are.
5. **How the fence reaches each fenced write.** Worker-called functions take `run_id` and no fence today
   (`transition_run`, `freeze_proposal`, `append_event`); `revoke_handles` and `mark_unknown` take a fence but ignore
   it; `append_event` is also called by `api` and `sweeper`, which hold no lease (SA:186). mcp-write's
   `grant_execution` and `lookup_action` take the raw handle (whose row carries `fence`, never set by `mint_handle`,
   §3.2); `mark_sent` and `record_outcome` take only `action_id` (SESSION_STATE `:193`: "binding the raw handle for
   `mark_sent` and `record_outcome` -> T13/T22"). Open: new signatures (a fence argument, a handle argument, or the
   fence read from the handle row) and therefore new function revisions and caller-list freezes; SA:463/464 list
   `run_lease FOR SHARE` for both functions without naming an input that carries the fence.
6. **Post-SENT fence failure in mcp-write.** A stale fence on `record_outcome` after SENT would raise a mapped
   refusal; `execution.py:29-32` already turns `_POST_SENT_REFUSALS` into UNKNOWN. Open: which SQLSTATE/exception a
   fence failure uses (OC003 `VersionConflict`, a new code, or `HandleRejected`/OC008), since `server.py:193-196`
   maps `VersionConflict` before SENT to `STALE_RUN` and `HandleRejected` to `INVALID_HANDLE`; and whether SA:184's
   "A missing row aborts the transaction" is a raise inside the function.
7. **`resolve_invocation`'s fence check: T13 or T15.** SA:459 lists "current run fence" and `run_lease` FOR SHARE;
   BS:360 binds the handle to "current fence"; R027 ("expired fence") is owned by T15, which depends on T13.
   `mint_handle` stores no fence today. Open: whether T13 writes the fence into `invocation_context` at mint time and
   checks it in `_resolve_handle`, or leaves the check to T15.
8. **`revoke_handles(run_id, fence)` semantics.** Today it revokes every live handle of the run, no lock
   (`0003:403-416`). SA:472: "`run_lease` FOR SHARE → `invocation_context`". Review note 7 routes revocation through
   it. After a lease loss (SA:198 "revokes its invocation handles") the caller's fence is no longer current, so a
   fenced `revoke_handles` would refuse exactly the call SA:198 needs. Open: compare-and-refuse, revoke only handles
   minted under that fence, or revoke all regardless; and whether a fence bump already makes old handles unusable (if
   `_resolve_handle` compares fences, revocation is belt-and-braces).
9. **`mark_unknown(run_id, fence)` and the worker's timeout path.** SA:250–254 and SA:467: take the lease FOR UPDATE,
   bump the fence, read the grant. Today the worker never calls `mark_unknown` on a transport failure; it re-queues
   (`handlers.py:195-202`) and calls `mark_unknown` only on an UNKNOWN envelope (`:214-217`; erratum 14). R109 (the
   timeout test) belongs to T22. Open: whether T13 changes the transport-failure branch or only makes `mark_unknown`
   bump the fence; what `p_fence` means (the caller's expected current fence, refused if stale, or ignored); and that
   bumping the fence from the owning worker changes the fence its heartbeat thread renews (review note 2).
10. **The re-fence hand-off (review note 2).** "Owner re-fence path hands the new fence to the heartbeat thread
    atomically." Paths that change an owned run's fence: re-acquisition by the same owner (a second job for the same
    run), `mark_unknown`. Open: the shared state between the event loop and the thread (a lock-protected value, a
    queue) and what the thread does with a renewal under an old fence (fails → lease loss).
11. **`reclaim_leases`.** SA:471 makes it a `sweeper`-called definer locking `run_lease` FOR UPDATE; `app_definer` has
    `sel` only (Q1). The sweeper holds `sel, upd(lease_until)` on `run_lease`, `sel, ins, upd(claimed_by, claimed_at,
    done_at, attempts)` and `sweeper_all` on `jobs`, `upd(leased_until)` (no `sel`) on `model_permit`. Erratum 26 is
    the precedent for a sweeper routine. Open: what "Expired leases become reclaimable" changes in the row (expiry is
    already `lease_until < app.current_time()`, so the next acquirer can take it without the sweeper); whether reclaim
    un-claims the stale job (`claimed_at` reset) or inserts a new wake-up; the recover dedup trigger `sweep:<bucket>`
    (SA:503, `jobs.py:115`) for runs with a grant; interaction with T14's `sweep_wakeups` (SA:346, T14 owns wake-ups);
    the `model_permit` UPDATE that needs SELECT (erratum 25 pattern); cadence (the sweeper ticks every 30 s).
12. **The `model_permit` table.** No migration, grant row or code exists. Facts: one row (global concurrency 1,
    BS:549), "leased and polled with `SKIP LOCKED` plus backoff" (SA:204), column `leased_until` (SA:432), worker `sel,
    upd(all)` (no `ins`), sweeper `upd(leased_until)`, no RLS (SA:523), seeded by `migrator` (SA:440; Alembic runs as
    the Compose superuser, Plan E debt `:357`). Not given: the other columns (owner? run_id? acquired_at?), the
    primary key, how many rows ("a `model_permit` row"), and the backoff. The release rule depends on T02's
    unmeasured cancellation behaviour (§3.16). No model call exists until T19 (`drafting.py:79-83`). Open: whether T13
    ships the table and its acquire/release code with no consumer, and how it is tested without Ollama.
13. **The global queue bound.** BS:550 "100 total initially; bounded tenant quotas"; erratum 39 and SESSION_STATE
    `:386-387` move it to T13; the API cannot read `jobs` and counts QUEUED runs per tenant only (spike §8). The spike
    names two routes: a definer function or a new grant (both matrix changes). R062 ("full queue stop predictably") is
    T29's. Open: what "queued work" counts (QUEUED runs, unclaimed jobs, or both), whether maintenance jobs count, the
    setting name and bounds (`OPS_*`, BS:542 "validated configuration"), whether the per-tenant quota stays, and the
    response (429 `RATE_LIMITED` with `Retry-After`, unrecorded, as for the tenant quota).
14. **The published lock order.** SA:188 lists the advisory lock, `run_lease`, `runs`, `messages`, `proposals`,
    `decisions`, `memberships`, `execution_grant`, `action_attempt`, `operator_resolutions`, `events`, `outbox`. Review
    note 3 asks to place `jobs`, `invocation_context`, `model_permit`, `sessions`; erratum 37 prepends the idempotency
    advisory lock. Not placed anywhere: `drafts`, `run_state_history`, `run_directory`, `action_attempt_state`,
    `idempotency_request`, `login_state`, `logout_jti`, `app.test_clock`. Observed orders (§3.15) put `drafts` before
    `runs` (`_draft_and_freeze`), `invocation_context` after `runs`, `jobs` after `events` (`create_run`, `mark_unknown`),
    and no transaction locks both `memberships` and `runs` (the sync locks `memberships` alone; `grant_execution`
    reads memberships without a lock). Open: the published list, where it
    lives (a doc, `core/` data a test checks), and whether existing functions are reordered.
15. **The asset-guard advisory lock.** T21 owns the guard (TODO(T21) at `0004:159`, `0005:140`; T21 review note);
    T13 review notes 3 and 5 ask for the lock in the order and "test that app_definer may call pg_advisory_xact_lock".
    SA:189: `pg_advisory_xact_lock(hashtextextended(tenant_id || ':' || asset_id, 0))` (one-key bigint form);
    erratum 37's idempotency lock uses the two-key `(int, int)` form, a distinct lock space. `runs.asset_id` is `text
    NOT NULL` (`0001:80`). The `api` role already calls `pg_advisory_xact_lock(int, int)` (`store.py:761`); no test
    calls it as `app_definer` (a NOLOGIN role, reachable only inside a definer body). Open: whether T13 takes the lock
    in `freeze_proposal`/`grant_execution` now or only adds the capability test and the ordering.
16. **The heartbeat thread and its connection.** SA:194: dedicated thread, own DB connection, renew every 10 s, lease
    30 s. Facts: psycopg 3.3.6 ships a synchronous `psycopg.Connection` (no new dependency); no service uses
    threads today; the SelectorEventLoop constraint applies to async psycopg only; the worker already holds two
    connections (loop, probe). Open: role (`worker`), autocommit, renewal statement shape (`UPDATE run_lease SET
    lease_until = app.current_time() + 30 s WHERE run_id = … AND fence = … AND owner = … AND lease_until >
    app.current_time()`, under FOR UPDATE per SA:191), and what the thread does between leases (idle while no run is
    held).
17. **Gating renewal on loop liveness and the 90 s budget (review note 4) versus DoD 3.** DoD 3 and R088 require that a
    loop blocked for 25 s keeps the lease; review note 4 requires renewal to stop when the loop is not alive or the 90 s
    compute budget (BS:555) is spent. `runs.budget_used integer` exists with a worker grant (`0002:206`, SA:415) and is
    never written. Open: the liveness signal (a loop-side monotonic timestamp the thread reads), its threshold (must
    exceed 25 s and stay below what would let a dead loop hold the lease: lease 30 s), what "compute" counts (model and
    tool time only; human waits excluded, BS:556), and where the budget is enforced (T29 owns R062's caps).
18. **The local monotonic deadline (SA:195).** "stops starting effects at `lease_until − 5 s`": `lease_until` is
    database time (`app.current_time()`, shifted by the test clock), the deadline is the worker's monotonic clock.
    Open: how the two are related (record the monotonic instant at each successful renewal plus 25 s), which calls
    count as "starting effects" (MCP calls, model calls, definer writes), and the effect of a test that moves
    `app.test_clock` forward (every lease in the database expires at once, since the offset is global, §3.7).
19. **Renewal failure (SA:196–199).** "cancels in-flight model and tool calls; revokes its invocation handles; exits
    the run." Today `HttpMcpCaller.call` has no cancellation hook beyond task cancellation and read timeout 60 s
    (`mcp.py:53-56`); there is no model call. Open: the cancellation mechanism (cancel the handler task from the
    thread via `loop.call_soon_threadsafe`), what "exits the run" does to the job (leave claimed for reclaim, re-queue,
    or finish) and to the run's state (no transition: the next owner re-reads state), and how handles are revoked when
    the fence is stale (Q8). R088's evidence names "cancels the call and revokes handles".
20. **Testing DoD 3.** "Blocked event loop (25 s) does not lose the lease": needs a handler that blocks the loop
    (`time.sleep`) for 25 s against a 30 s lease and a 10 s heartbeat, i.e. a test of ≥ 25 s wall time, or
    configurable lease/heartbeat values (no lease setting exists in `settings.py`). R088 adds "a >30 s fake drafter"
    (`FakeDraftGenerator` has no delay). "Forced renewal failure cancels work": candidate triggers are a fence bump
    from a second connection, closing the heartbeat connection, or a test-profile fault in the worker (no worker fault
    hook exists; the worker's only HTTP surface is the health app). The test clock cannot shrink a 30 s lease without
    also moving every other comparison.
21. **Testing DoD 1–2 (interleaving, stress, no deadlock).** Existing building blocks: `role_conn` for several
    role connections, `transaction(force_rollback=True)`, `asyncio.gather` (§3.14). Missing: a step-wise interleaving
    helper (two connections advanced statement by statement), a deadlock detector assertion (SQLSTATE 40P01 count),
    `pg_locks` inspection, and a stress driver. Open: what the stress test runs (which functions, how many concurrent
    connections, how long), what "no deadlock" is measured as (zero 40P01, no `lock_timeout` 55P03), and whether it
    runs in `check.py --profile test` (time budget) or as a separate marked module. `PURGE_ORDER` needs `run_lease`
    for any live test that creates lease rows (§3.14).
22. **The fault factory "for app services".** SA:564 says hooks "exist only in an app factory, shared as
    `core.testing.faults`, that refuses to start unless `PROFILE=test`"; today `Faults(profile)` is a class each
    service wires into its own `create_app`, and the API sets `store.faults` from the lifespan (Plan G open item
    `:303`). The six missing BS:405 faults read as destination behaviours (timeout before acceptance, delayed receipt
    visibility, malformed response, mismatching receipt hash, rate limit, concurrent same-key submission), and the
    implemented three map by effect only (§3.8). Plan G ruling 24 and the R015 note expect `lose_after_commit` on the
    API. Open: which kinds go to incident-sim, which to the API, the worker (renewal failure), mcp-write; whether
    "transient unavailable" and "timeout before acceptance" are distinct from `drop_before_commit`; whether
    `get_incident_receipt` (T47) is needed before "delayed receipt visibility" is testable; and the route/guard for
    services without an HTTP API (worker, sweeper).
23. **Checkpoints.** SA:211 stores `runs.checkpoint_id` "under the fence"; R021 is M15/T38 (matrix) though
    `handoff/ACCEPTANCE.md:27` lists it as M04; LangGraph is T20 and not locked. `runs.checkpoint_id` (worker
    `upd`) is never written. Open: whether T13 touches checkpoints at all (a fenced helper for the `checkpoint_id`
    write T20 will use, or nothing).
24. **Bounded retries.** `requeue_job` TODO (`persistence.py:568`), the transport-failure and `GRANT_DEFERRED`
    re-queues every 30 s (`handlers.py:199,205`); `jobs.attempts` increments on every claim; `RECOVER_CADENCE` covers
    recover jobs only (T22); T22 co-owns the transport path. Open: the bound, what happens at the bound (run →
    FAILED? the run is APPROVED or EXECUTING, which `transition_run` may not leave: SA:451 forbids post-grant targets),
    and whether T13 or T22 owns it.
25. **Reconnects and pools.** Every process exits on a broken connection (§3.12); `psycopg-pool` is not locked; the
    `Session` TODO and the API's `lock_timeout` TODO name a pool. Open: whether T13 adds a pool (a new dependency and
    lock change) or reconnect logic, and how a broken heartbeat connection is treated (renewal failure, Q19).
26. **"One active compute lease per requester" (BS:548).** Not restated in SA; nothing enforces it. Open: whether it is
    T13's (a lease-acquisition check across runs of one requester) or out of scope.
27. **`api` may insert any job type** (Plan G debt `:397-398`, spike §2; `jobs.type` has no CHECK, `0001:109`). Owner
    "T13/T22". Open: a CHECK on `type`, a definer for the `resume_input` insert, or a trigger — each a schema change.
28. **Lease release at job end and human waits.** R022 (T20): human waits hold no lease. No release path exists
    today; the worker holds no DELETE on `run_lease`. Open: release by UPDATE (`lease_until` to now, `owner` cleared?
    `owner` is NOT NULL) or by letting it expire; and whether the fence survives across jobs (it must, for R087: the
    lease is per run, not per job).
29. **Worker-side `runs` locks.** `investigate` and `execute` take `runs … FOR UPDATE` directly through
    `run_row(lock=True)` before calling definers (§3.4). Under SA:188, `run_lease` precedes `runs`. Open: whether
    those direct locks stay, and the order of the fence check relative to them.
30. **Startup and test-code debts tagged T13.** The shared connect-and-assert helper (`SESSION_STATE.md:198`, with
    T30), a closer raising during startup cleanup (`:222`, with T30), the token verifier's injected-fetch exception
    (`:165`, test code), the untested branches (`:194`, with T22) and the `STALE_RUN`/`HASH_MISMATCH` envelope tests
    (`:196`, with T47). Open: which of these Plan H takes.
31. **Migration shape.** A new revision (0007) would carry any new table (`model_permit`), grant cells (frozen per
    revision, `test_transitions_table.py:61`), re-created function bodies (frozen caller lists), and must downgrade
    cleanly (R006 live test). The `testclock` branch still renders grantee tuples from the live matrix
    (`SESSION_STATE.md:198`: "freeze them in the next migration task"). The dev database is at 0005 until the owner
    migrates to 0006 (`SESSION_STATE.md:437-440`). Open: one revision or several, and the dev-database instruction.

---

## 6. Glossary of exact names

- `run_lease(run_id PK, owner, lease_until, fence bigint DEFAULT 1)` — `0002:316-322`; SA:173; no row ever written.
- `fence` — `run_lease.fence` (bigint) and `invocation_context.fence` (bigint, default 1, never set by `mint_handle`).
- `model_permit` — SA:204, SA:432; column `leased_until`; does not exist.
- `reclaim_leases()` — SA:471; does not exist; sweeper is the caller.
- `revoke_handles(uuid, bigint)` — `0003:403`; worker-only; ignores the fence.
- `mark_unknown(uuid, bigint)` — `0004:478`; worker-only; ignores the fence; recover key `<action_id>:timeout`.
- `_resolve_handle(text, text, text)` — `0004:65`; the shared handle check of `resolve_invocation`,
  `grant_execution`, `lookup_action`.
- `claim_job` / `finish_job` / `requeue_job` / `mint_handle` — `persistence.py:538/562/567/613`.
- `claimed_by` — `host:pid` (`worker/main.py:104`); sweeper `sweeper:host:pid`.
- `jobs_claimable` — `0001:119`, partial index on `available_at` for unclaimed, unfinished jobs.
- `app.current_time()` / `app.test_clock` / `test_harness` — `0002:365`, `tc_0001`, AM-20.6.
- `Faults`, `FaultKind`, `FaultsDisabled` — `core/src/ops_core/testing/faults.py`; kinds `reject_next`,
  `drop_before_commit`, `lose_after_commit`.
- `POST /internal/faults/{kind}` — incident-sim (`app.py:237`, workload token) and API (`app.py:681`,
  `browser_mutation`); registered only under `PROFILE=test`.
- `OPS_TENANT_QUEUE_QUOTA` — `settings.py:293,309`; default 100, 1–10000; per-tenant QUEUED runs; 429 `RATE_LIMITED`.
- `QueueFull` — the API store's unrecorded refusal (`store.py:424`, `app.py:299`).
- `_POST_SENT_REFUSALS` — `mcp-write/…/execution.py:32`.
- `STALE_RUN` — mcp-write's pre-SENT envelope for `VersionConflict` (`server.py:196`).
- `RECOVER_CADENCE` — `jobs.py:108`, `(300, 3600, 48)`.
- `POLL_SECONDS` (0.5, worker), `OPS_SYNC_TICK_SECONDS` (30, sweeper), `EXECUTE_RETRY_SECONDS` (30, worker).
- `OC003` `VersionConflict`, `OC008` `HandleRejected`, `OC005` `Refused` — `persistence.py:70-79`.
- `role_conn`, `app_conn`, `migrated`, `PURGE_ORDER`, `new_run` — `tests/e2e/conftest.py`,
  `tests/e2e/test_migrations_and_persistence.py:31`.

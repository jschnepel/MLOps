# Plan E inputs: T09 (roles, grants, RLS, definer functions) and T10 (destination hardening) — fact sheet

Prepared 2026-10-08 on branch `plan-d` at `2ae75d9` (clean tree; read-only). Facts only, no design. Citations:
`SA:<line>` = `SPEC_AMENDMENTS.md`, `BS:<line>` = `BUILD_SPEC.md` (line numbers as of `2ae75d9`); the amendments win
wherever the two conflict. Repository files are cited as `path:line`. `<repo>` is the repository root, `<scratch>` the
session scratch directory outside the repository. No secret value was printed or copied: the database password was
read from its secret file by `ops_core.settings` inside the measuring process only.

Note on section numbers: the controller's brief placed AM-20.4 at SA:494–504, AM-20.5 at SA:506–520 and AM-20.6/20.7
at SA:521–535. The actual headings are AM-20.4 SA:492, AM-20.5 SA:508, AM-20.6 SA:526, AM-20.7 SA:532 (the citations
below use the actual lines).

---

## 1. T09 and T10, verbatim, with their acceptance-matrix rows

### 1.1 T09 (`handoff/tasks.json`)

- **id/milestone/title:** `T09`, `M02`, "Migrations, roles, RLS and hardened definer functions". `status: "PLANNED"`,
  `external_approval_required: false`.
- **instructions:** "Implement AM-20 in code: Alembic schema (incl. run_state_history, action_attempt_state, drafts,
  run_directory, run_lease, jobs with dedup keys, execution_grant UNIQUE(run_id), sessions); roles per AM-20.1 incl.
  test_harness via the `testclock` Alembic branch; exact grants per AM-20.2; every AM-20.3 definer function (incl.
  create_run with its tenant argument, revoke_handles) with search_path/REVOKE/GRANT-to-named-callers, session_user
  checks and transaction-local set_config; transition_run restricted to worker and pre-grant targets; seed data
  migrations under migrator BYPASSRLS; sweeper_all policies on memberships and jobs; action_attempt_state seq ordering;
  clock_offset column; RLS policies per AM-20.5 incl. FORCE; app.current_time() per AM-20.6."
- **depends_on:** `["T08", "T45"]` (both DONE).
- **requirement_ids:** `R006, R007, R008, R009, R084, R106, R122, R124, R126, R128`.
- **definition_of_done:**
  1. "Migrations up/down on real PostgreSQL; dev/demo bootstrap refuses to start if app.test_clock exists."
  2. "Per-role tests: each role can do exactly its AM-20.2 grants and nothing else; direct INSERT into
     events/decisions/proposals and UPDATE of runs.state fail for every runtime role (R124, R128)."
  3. "pg_policies text matches AM-20.5 per table; definer path cannot cross tenants (R106); mcp_exec cannot SELECT any
     table (R084)."
  4. "GUC SET does not alter app.current_time(); only test_harness can write test_clock (R126)."
  5. "transition_run rejects any post-grant target and any caller other than worker; create_run is the only path to a
     new run; a plain SET inside a function body is caught by a test asserting the caller's app.tenant_id is unchanged
     after the call (R106)."
- **review_notes:**
  1. "RLS bootstrap: RLS-free run_directory(run_id, tenant_id) + invocation_context readable only by
     app_definer/sweeper; named cross-tenant sweeper policy for expire_proposals, membership sync, session lookup."
  2. "Definer functions declare SET app.tenant_id='' as an attribute; test that a preset tenant from mcp_exec is
     ignored."
  3. "app.test_clock exists only in the test-profile migration; app.current_time() never reads GUCs (R126)."
  4. "session_user remains the invoking login role inside SECURITY DEFINER; functions branch on it for allowed-caller
     checks."
  5. "Every service asserts at start that app.test_clock is absent outside the test profile; the demo bootstrap check
     alone is not enough."

### 1.2 T10 (`handoff/tasks.json`)

- **id/milestone/title:** `T10`, `M02`, "incident-sim destination with action_key table". `status: "PLANNED"`,
  `external_approval_required: false`.
- **instructions:** "Single action_key table; INSERT .. ON CONFLICT for incidents and abort; recomputed hash;
  never-expiring keys; incident-sim audience auth; test-only fault factory."
- **depends_on:** `["T08"]` (DONE).
- **requirement_ids:** `R010, R047, R096, R098`.
- **definition_of_done:**
  1. "Concurrent same-key POSTs and POST-vs-abort races yield exactly one terminal key state."
  2. "Different hash under an existing key returns CONFLICT; worker/API tokens get 403."
- **review_notes:**
  1. "Destination at READ COMMITTED; keep GET /internal/actions/{id}; abort stores grant hash; POST onto ABORTED
     returns tombstone regardless of hash (late-POST fault test)."
  2. "Fault factory lives in shared core.testing.faults (R098 co-owned with T13)."
  3. "incident-sim requires azp = mcp-write client in addition to aud; REJECTED is a permanent key state with tombstone
     shape; add a detective check that every destination key matches a grant hash."
  4. "POST onto REJECTED returns the REJECTED tombstone; abort onto REJECTED likewise; both in R096 fault tests."

### 1.3 Acceptance-matrix rows (`handoff/acceptance-matrix.json`), all currently `NOT_RUN`

| id | owning | requirement | expected_evidence | suggested_test |
|---|---|---|---|---|
| R006 | T09 | "Migrations run on real PostgreSQL" | "Create empty DB, migrate, rerun safely and test supported old-schema compatibility." | `tests/acceptance/test_r006_migrations_run_on_real_postgresql.py` |
| R007 | T09 | "Runtime-role row security isolates tenants" | "Run as non-owner/non-BYPASSRLS; exact beta IDs cannot expose data to alpha." | `tests/acceptance/test_r007_runtime_role_row_security_isolates_tenants.py` |
| R008 | T09 | "Connection pooling does not leak tenant context" | "Reuse the same pooled connection for different tenants and assert no residual access." | `tests/acceptance/test_r008_connection_pooling_does_not_leak_tenant_context.py` |
| R009 | T09 | "Tenant-scoped child references cannot cross tenants" | "Try attaching alpha proposal/message/approval records to beta parents; DB refuses." | `tests/acceptance/test_r009_tenant_scoped_child_references_cannot_cross_tena.py` |
| R084 | T09 | "MCP executor role has no direct table privileges" | "As mcp_exec, SELECT on any application table is permission denied." | `tests/acceptance/test_r084_mcp_executor_role_has_no_direct_table_privileges.py` |
| R106 | T09 | "Definer functions are hardened and tenant-isolated by explicit policies" | "search_path fixed, PUBLIC execute revoked, GRANT EXECUTE only to named callers, owner app_definer is not a table owner, FORCE RLS and the AM-20.5 policy text present per table; cross-tenant access through functions fails." | `tests/acceptance/test_r106_definer_functions_are_hardened_and_tenant_isolat.py` |
| R122 | T09 | "Checkpoint tables are reachable only by the worker" | "api role: permission denied on schema checkpoints; worker DML only; migrator ran setup()." | `tests/acceptance/test_r122_checkpoint_tables_are_reachable_only_by_the_work.py` |
| R124 | T09 | "Runtime roles hold exactly their AM-20.2 grants" | "Per-role tests enumerate pg_class grants against AM-20.2; any extra or missing grant fails; audit tables reject UPDATE/DELETE for every runtime role." | `tests/acceptance/test_r124_runtime_roles_hold_only_their_matrix_privileges.py` |
| R126 | T09 | "Test time cannot be shifted outside the test profile" | "In dev/demo, app.test_clock does not exist and SET of any GUC does not change app.current_time(); in test only the harness role can write the offset." | `tests/acceptance/test_r126_test_time_cannot_be_shifted_outside_the_test_pro.py` |
| R128 | T09 | "Every run transition and event goes through a definer function" | "Direct INSERT into events/decisions/proposals/execution_grant/action_attempt_state and UPDATE of runs.state are denied for api, worker and sweeper; transition_run rejects callers outside its list and transitions outside the table." | `tests/acceptance/test_r128_every_run_transition_and_event_goes_through_a_de.py` |
| R010 | T10 | "Destination records have an independent data boundary" | "Restore or reset only the application store; retained destination receipt still proves its existing incident." | `tests/acceptance/test_r010_destination_records_have_an_independent_data_bou.py` |
| R047 | T10 | "Concurrent same-key writes commit one incident" | "Send concurrent duplicates; atomic destination record and one returned receipt identity." | `tests/acceptance/test_r047_concurrent_same_key_writes_commit_one_incident.py` |
| R096 | T10 | "Destination key table is atomic, permanent and executor-only" | "Concurrent POST/abort on one key yield one state; POST and abort onto ABORTED or REJECTED keys return that tombstone; hash recomputed; keys never deleted; non-executor tokens or wrong azp 403." | `tests/acceptance/test_r096_destination_key_table_is_atomic_permanent_and_ex.py` |
| R098 | T10, T13 | "Fault-injection hooks are unreachable outside the test profile" | "Hook routes 404 in default and demo profiles; factories refuse to start without PROFILE=test." | `tests/acceptance/test_r098_fault_injection_hooks_are_unreachable_outside_th.py` |

Related row named by T09's instructions without being in its list: **R082** (owner T07, `IMPLEMENTED_LOCALLY_VERIFIED`,
`RECORDED_LOCALLY`, evidence `tests/plan_c/test_states.py`): "Run transitions are enforced from one table including
ESCALATED"; expected evidence "Exhaustive transition tests; disallowed transitions rejected and logged."; note "\"logged\"
half is TODO(T09); the local evidence covers the rest" (`core/src/ops_core/states.py:11-12` carries the TODO).

All suggested test paths are under `tests/acceptance/`, which does not exist; `pyproject.toml` `testpaths` is
`["tests/plan_a", "tests/plan_b", "tests/plan_c", "tests/plan_d", "tests/e2e"]` (ruling 26 of Plan D: unit tests in
`tests/plan_<letter>/`, cross-service live tests in `tests/e2e/`).

---

## 2. Spec requirements

### 2.1 AM-20 principles (SA:383–389)

- AM-20 replaces the 1.3.2 matrix ("could not run the system") — SA:385.
- P1: every state transition, decision, grant, attempt step and event goes through a `SECURITY DEFINER` function;
  runtime roles never UPDATE `runs.state`, never INSERT into `events`, `decisions`, `proposals`, `execution_grant` or
  `action_attempt_state` directly — SA:387.
- P2: audit tables are append-only; `action_attempt_state(action_id, attempt_no, seq, state, at)` and
  `run_state_history` are insert-only; "latest" is the highest `seq`, never a timestamp; `runs.state` is a denormalized
  copy maintained only by the definer functions — SA:388.
- P3: functions decide by `session_user` (stays the invoking login role inside a definer body); each function has an
  allowed-caller list and raises for any other role — SA:389.

### 2.2 AM-20.1 roles (SA:391–404)

| Role | Login | Exact purpose / privileges (SA line) |
|---|---|---|
| `migrator` | yes, "DDL and data migrations only" | Alembic; owns tables and schemas; holds `BYPASSRLS` so seed and backfill data migrations can write RLS tables; never used at runtime — SA:395 |
| `app_definer` | **no** | Owns every definer function; **owns no tables**; has the AM-20.5 RLS policies — SA:396 |
| `api` | yes | FastAPI process — SA:397 |
| `worker` | yes | Workflow worker — SA:398 |
| `sweeper` | yes | Scheduler (expiry, membership sync, wake-up sweep, outbox delivery); holds the Keycloak `view-users` service account for the membership sync — SA:399 |
| `mcp_read` | yes | mcp-read; read-path functions only — SA:400 |
| `mcp_exec` | yes | mcp-write; write-path functions only — SA:401 |
| `operator` | yes | Local operator CLI; one function only — SA:402 (AM-10: "may only `EXECUTE` the definer function `resolve_escalation`", SA:126) |
| `test_harness` | yes, **test profile only** | Writes `app.test_clock`; created by the `testclock` Alembic branch — SA:403 |
| `incident` | yes (separate database) | incident-sim — SA:404 |

BUILD_SPEC: "Use distinct database credentials for migration, API, worker, MCP executor, destination, and diagnostics"
— BS:246 (the "diagnostics" credential is superseded by AM-20.3/AM-20.2, SA:45). "use a non-owner runtime role
without `BYPASSRLS`" — BS:248.

### 2.3 AM-20.2 grant table, schema `app` (SA:406–442), row by row

Preamble: "Only these grants exist. Anything not listed is denied. 'ins' = INSERT, 'upd(cols)' = UPDATE on exactly
those columns, 'sel' = SELECT, 'del' = DELETE." — SA:408. Columns: `api` | `worker` | `sweeper` | `app_definer` |
`mcp_read`/`mcp_exec`/`operator` (the last column is used only for `test_harness`, SA:437).

| Table (SA line) | api | worker | sweeper | app_definer | right-hand column |
|---|---|---|---|---|---|
| `tenants`, `memberships` (412) | sel | sel | sel, upd(`active`, `permission_version`, `synced_at`) | sel | — (seeded by `migrator` data migrations) |
| `sessions` (413) | sel, ins, upd(`last_seen_at`, `revoked_at`), del | — | del (expired) | — | — |
| `conversations`, `messages` (414) | sel, ins | sel | — | sel | — |
| `runs` (415) | sel, upd(`cancel_requested`, `cancel_requested_at`) (insert only via `create_run`) | sel, upd(`checkpoint_id`, `budget_used`) | sel | ins, sel, upd(`state`, `state_version`, `reason`, `active_proposal_id`, `next_event_seq`, `slot_held`, `supersedes_run_id`) | — |
| `run_directory` (run_id, tenant_id; no RLS) (416) | sel | sel | sel | ins, sel (via `create_run`) | — |
| `run_state_history` (417) | — | — | — | ins | — |
| `run_lease` (418) | — | sel, ins, upd(all) | sel, upd(`lease_until`) (reclaim) | sel | — |
| `jobs` (419) | ins (`resume_input` only) | sel, ins, upd(`claimed_by`, `claimed_at`, `done_at`, `attempts`) | sel, ins, upd(same) | ins, sel | — |
| `invocation_context` (no RLS) (420) | — | ins | sel | sel, upd(`revoked_at`) | — |
| `drafts` (pre-freeze model output, IDs only) (421) | — | ins, sel | — | sel | — |
| `proposals` (422) | sel | sel | sel | ins, sel | — |
| `decisions` (423) | sel | sel | — | ins, sel | — |
| `execution_grant` (424) | sel | sel | sel | ins, sel | — |
| `action_attempt`, `action_attempt_state` (425) | sel | sel | sel | ins, sel | — |
| `events` (426) | sel | sel | sel | ins, sel | — |
| `outbox` (427) | ins | ins | sel, upd(`leased_until`, `attempts`, `delivered_at`, `result`) | ins | — |
| `feedback` (428) | ins, sel | — | — | — | — |
| `idempotency_request` (429) | sel, ins | — | del (expired) | — | — |
| `operator_resolutions` (430) | sel | — | — | ins | — |
| `documents`, `chunks`, `embeddings` (431) | — | ins, sel (ingestion) | — | sel | — |
| `model_permit` (432) | — | sel, upd(all) | upd(`leased_until`) (reclaim) | — | — (seeded by `migrator`) |
| `app.test_clock` (test profile only) (433) | — | — | — | sel | `test_harness`: ins, upd, del |
| schema `checkpoints` (434) | — | all DML | — | — | — |

Notes, verbatim in substance:
- `mcp_read`, `mcp_exec` and `operator` have **no table grants**; the right-hand column is only for `test_harness` — SA:437.
- `runs.state` is written only by `app_definer` (through `create_run`, `transition_run` and the functions below); the
  `api` column grant on `cancel_requested` cannot set state, because UPDATE is column-scoped — SA:438.
- `runs.next_event_seq` is written only inside `append_event` (the worker's former column grant is removed) — SA:439.
- Seed data (tenants, personas' memberships, the `model_permit` row) is written by `migrator` data migrations under
  `BYPASSRLS`; no runtime role can insert it — SA:440.
- `execution_grant` has no `state` column; grant status is derived from the latest `action_attempt_state` row — SA:441.
- `proposals` rows are inserted already frozen by `freeze_proposal`, so proposals never need UPDATE; pre-freeze drafts
  live in `drafts` — SA:442.
- Checkpoint schema (AM-20.7 item 7): `migrator` runs `PostgresSaver.setup()` with `autocommit=True`,
  `row_factory=dict_row`, `options=-c search_path=checkpoints`; `worker` gets DML only on schema `checkpoints` with
  `search_path=checkpoints,pg_temp` on its checkpoint connection; `api` gets permission denied (R122) — SA:559-562.
  `langgraph-checkpoint-postgres` is pinned at 3.1.2 in AM-30 (SA:581) but is **not** in `uv.lock` (no `langgraph*`
  package is locked; `importlib.util.find_spec("langgraph")` is None in the repo venv).

### 2.4 AM-20.3 definer functions (SA:444–490)

Rules for all functions — SA:446:
- `SECURITY DEFINER`, owner `app_definer`, `SET search_path = app, pg_temp`, `SET app.tenant_id = ''` as a function
  attribute.
- Each migration that creates one runs, **in the same transaction**, `REVOKE ALL ON FUNCTION … FROM PUBLIC` and then
  `GRANT EXECUTE … TO <exactly the callers listed>`.
- Every function first resolves `tenant_id` through `run_directory` (or the handle) and sets `app.tenant_id` with
  `set_config(name, value, true)` (transaction-local; "a plain `SET` would persist into the caller's session") before
  touching tenant rows; takes locks in the AM-12 order; raises `authority_violation` when `session_user` is not an
  allowed caller.
- Reads of the setting use `NULLIF(current_setting('app.tenant_id', true), '')::uuid`.
- Internal helpers `_canonicalize`, `_asset_guard`, `_allowlist` are not granted to any role — SA:474.
- AM-12 lock order: `asset guard advisory lock → run_lease → runs → messages → proposals → decisions → memberships →
  execution_grant → action_attempt → operator_resolutions → events → outbox`; idempotency rows last — SA:188. Asset
  guard lock = `pg_advisory_xact_lock(hashtextextended(tenant_id || ':' || asset_id, 0))`, `asset_id` NOT NULL and read
  before locking — SA:189. A transaction that will write `run_lease` takes `FOR UPDATE` from the start — SA:191.
- Fenced write prologue (worker or MCP mutation): `SELECT 1 FROM run_lease WHERE run_id = :r AND fence = :f AND
  lease_until > app.current_time() FOR SHARE`; a missing row aborts — SA:176-184. API and sweeper mutations hold no
  lease; they serialize with `runs … FOR UPDATE` plus `expected_version` — SA:186.
- Clock rule: every lease, expiry, freshness and deadline comparison uses `clock_timestamp()` evaluated after the row
  locks; never `now()` — SA:157.

The 23 functions (SA:450–472). "First caller" = the earliest task whose code calls it; "T08 today" = the skeleton
already performs the equivalent in plain SQL (§3.3).

| # | Function (signature) | Callers (GRANT EXECUTE) | Inputs / checks | Locks | Inserts / updates | Event | First caller |
|---|---|---|---|---|---|---|---|
| 1 | `create_run(tenant_id, conversation_id, request, intent, supersedes_run_id)` — SA:450 | `api` | tenant from the authenticated session (API is the identity trust anchor); validated admission request; checks the conversation belongs to the tenant; `supersedes_run_id` validated against tenant/asset | `runs` (conversation slot index) | sets `app.tenant_id` from the argument; inserts `runs` (QUEUED, `intent`, `supersedes_run_id`), `run_directory`, first `run_state_history`, the `investigate` job (dedup `run_id:1`), one transaction; the API inserts the message in the same transaction | `run.accepted` | T08 today (api admit); T12 owns admission |
| 2 | `transition_run(run_id, from_state, to_state, reason, expected_version)` — SA:451 | `worker` only | allowed targets QUEUED → RETRIEVING; RETRIEVING → DRAFTING / AWAITING_INPUT / INSUFFICIENT_EVIDENCE / FAILED; DRAFTING → AWAITING_INPUT / ANSWERED / INSUFFICIENT_EVIDENCE / FAILED; AWAITING_INPUT → QUEUED; **never** a post-grant state, never SUCCEEDED; validates the AM-10 table, caller's targets, `expected_version` | `runs` FOR UPDATE | `runs.state/state_version/reason`; `run_state_history`; maintains `slot_held` and the conversation slot (partial unique index on `runs(conversation_id) WHERE slot_held`) | matching `run.*` via `append_event` | T08 today (worker) |
| 3 | `append_event(run_id, type, payload)` — SA:452 | `api`, `worker`, `sweeper` | `source` derived from `session_user` (→ `application`; `worker` may pass `source=model_summary` only for `explanation.ready`); **refuses** `action.*`, `run.*`, `review.*` | `runs` FOR UPDATE (for `next_event_seq`) | the event; `next_event_seq` (SA:439, SA:303) | the event | T08 today; T14 owns `next_event_seq` (persistence.py:177) |
| 4 | `freeze_proposal(run_id, draft_id, payload)` — SA:453 | `worker` | recomputes `sha256(canonical(payload))` = `drafts.draft_sha256`; `authored_by` derived from `runs` (requester + revision authors), never passed; refuses `runs.intent = 'answer_only'` or a draft carrying `supersedes_run_id`; injects `runs.supersedes_run_id`; asset guard (AM-13) | advisory(tenant, asset) → `run_lease` FOR SHARE → `runs` FOR UPDATE → `proposals` | immutable `proposals` row, `revision = max+1`; `runs.active_proposal_id`; DRAFTING → AWAITING_APPROVAL, or → BLOCKED_REVIEW on guard refusal | `proposal.ready` or `review.blocked` | T08 today (worker, handlers.py:154 TODO(T09)); T21 |
| 5 | `record_decision(proposal_id, expected_payload_sha256, decision, reason, idempotency_key)` — SA:454 | `api` (reviewer = API's authenticated `sub`) | current membership; reviewer ∉ `authored_by`; active unexpired revision; hash equality; first-decision-wins; lazy expiry (→ BLOCKED_REVIEW) | `runs` FOR UPDATE → `proposals` FOR SHARE → `decisions` → `memberships` FOR SHARE | the decision; → APPROVED or REJECTED; on approval the `execute` job (dedup `proposal_id`) | `approval.recorded` / `run.rejected` | T08 today (api decide); T21 |
| 6 | `create_revision(run_id, expected_version, author, supersedes_run_id)` — SA:455 | `api` | refuses `GRANT_EXISTS` if a grant exists; `SLOT_OCCUPIED` if another active run; `supersedes_run_id` validated | `runs` FOR UPDATE → `execution_grant` FOR SHARE | APPROVED/BLOCKED_REVIEW/AWAITING_APPROVAL → QUEUED; appends `author` to `authored_by`; `investigate` job (dedup `run_id:revision+1`) | `proposal.revised` | T21 (R120) |
| 7 | `create_manual_proposal(run_id, payload, author)` — SA:456 | `api` | payload per `manual-proposal` schema; tenant-scopes asset and evidence IDs (404 otherwise) | same as `freeze_proposal` | as `freeze_proposal`, `authored_by = [author]` | `proposal.ready` | T21 |
| 8 | `expire_proposal(run_id)` — SA:457 | `sweeper`; also invoked internally by `record_decision`/`grant_execution` | if the active proposal's `expires_at < app.current_time()` | `runs` FOR UPDATE → `proposals` FOR SHARE | AWAITING_APPROVAL/APPROVED → BLOCKED_REVIEW(`expired`) | `review.blocked` | T21 (lazy) / T14 sweeper |
| 9 | `request_cancel(run_id, expected_version)` — SA:458 | `api` | — | `runs` FOR UPDATE → `execution_grant` FOR SHARE | sets `cancel_requested`; no grant → CANCELLED now; else returns `{grant_exists, attempt_state}` | `run.cancelled` or none | T21/T22 (R118) |
| 10 | `resolve_invocation(raw_handle, client_azp)` — SA:459 | `mcp_read`, `mcp_exec` | hashes the handle inside; azp binding; handle's server matches the **calling role** (read handles only for `mcp_read`, execute/recover only for `mcp_exec`); expiry; current run fence; `job_type` derived from `jobs`, never the worker-written `server` column alone (SA:496) | `invocation_context` FOR SHARE → `run_lease` FOR SHARE | none | none; returns `{run_id, tenant_id, job_type, run_state, attempt_state, allowed_tools}` (AM-15 allowlist) | T08 today (both MCP servers, `persistence.resolve_handle`); T15/T47 |
| 11 | `asset_scope(raw_handle)` — SA:460 | `mcp_read` | handle | as above | none | none; returns `tenant_id`, `asset_id`, `[start_at, end_at)` | T16 |
| 12 | `search_procedures_scoped(raw_handle, query, query_embedding vector(768) NULL, asset_type, limit, mode)` — SA:461 | `mcp_read` | lexical (`mode=lexical`) or exact vector (`mode=vector`) over approved, effective, tenant-permitted chunks (proposed erratum 3: external `vector_exact` ↔ SQL `vector`) | as above | none | none; returns IDs, versions, section, hash, excerpt | T15/T17 (mcp-read serves fixtures today) |
| 13 | `grant_execution(raw_handle, proposal_id)` — SA:462 | `mcp_exec` | §13 gate: proposal belongs to the handle's run and tenant; approved, unexpired, hash-matching; requester and reviewer currently active; not cancelled; asset freshness (5 min); asset guard | advisory(tenant, asset) → `run_lease` FOR SHARE → `runs` FOR UPDATE → `proposals` FOR SHARE → `decisions` FOR SHARE → `memberships` FOR SHARE → `execution_grant` → `action_attempt` | `execution_grant` (random `action_id`, `UNIQUE(run_id)`), `action_attempt` 1, `action_attempt_state` INTENT; APPROVED → EXECUTING (or → BLOCKED_REVIEW with the refusal reason) | `action.granted` or `review.blocked` | T08 today (mcp-write); T21/T47 |
| 14 | `mark_sent(action_id)` — SA:463 | `mcp_exec` | re-checks `cancel_requested` and the dispatch deadline | `run_lease` FOR SHARE → `runs` FOR UPDATE → `action_attempt_state` | state SENT (with `seq`), or returns `cancelled`/`expired` without inserting | `action.dispatched`, or `action.redispatched` when `attempt_no > 1` | T08 today; T22 |
| 15 | `record_outcome(action_id, outcome, receipt_or_tombstone)` — SA:464 | `mcp_exec` | idempotent; verifies the hash | `run_lease` FOR SHARE → `runs` FOR UPDATE → `action_attempt_state` → `events` | state RESOLVED; EXECUTING/OUTCOME_UNKNOWN/ESCALATED → SUCCEEDED, FAILED(reason) or ESCALATED(`conflict`); on a terminal run late evidence without a transition | `action.confirmed` / `action.failed` / `action.conflict` / `action.late_evidence`, all `source=destination` | T08 today; T22 |
| 16 | `request_abort(action_id, reason)` — SA:465 | `mcp_exec` | reason ∈ {`cancelled_before_send`, `expired`, `deadline`} | as `record_outcome` | `ABORT_REQUESTED` state row; caller then POSTs abort and calls `record_outcome` with the tombstone; from INTENT the outcome is FAILED(`cancelled_before_send` or `expired`) | via `record_outcome` | T22/T47 |
| 17 | `lookup_action(raw_handle)` — SA:466 | `mcp_exec` | handle | `run_lease` FOR SHARE | none; returns `action_id`, canonical bytes, hash for same-key redispatch (no gate re-run) | none | T22/T47 |
| 18 | `mark_unknown(run_id, fence)` — SA:467 | `worker` (transport-timeout path, AM-13) | — | `run_lease` FOR UPDATE → `runs` FOR UPDATE → `execution_grant` FOR SHARE | bumps the fence (revoking handles); if a grant exists EXECUTING → OUTCOME_UNKNOWN and a `recover` job | `action.uncertain` | T22 (R109); **T08 today calls it from mcp-write** (§3.3) |
| 19 | `escalate_run(run_id, reason)` — SA:468 | `worker`, `sweeper` | reason ∈ {`conflict`, `escalation_deadline`} | `runs` FOR UPDATE | EXECUTING/OUTCOME_UNKNOWN → ESCALATED; releases the conversation slot | `run.escalated` | T22 |
| 20 | `resolve_escalation(run_id, operator_name, reason)` — SA:469 | `operator` | self-asserted operator name | `runs` FOR UPDATE → `operator_resolutions` | ESCALATED → ABANDONED_UNVERIFIED; resolution row | `run.abandoned_unverified` | T22 (R119, operator CLI) |
| 21 | `sync_memberships(payload)` — SA:470 | `sweeper` | the Keycloak sync result | `memberships` FOR UPDATE | deactivates disabled/deleted users' memberships; records `synced_at` | none | T11 (60 s sync, R086) |
| 22 | `reclaim_leases()` — SA:471 | `sweeper` | none | `run_lease` FOR UPDATE | expired leases reclaimable; stale `model_permit` released; lost wake-ups re-enqueued (dedup keys) | none | T13 |
| 23 | `revoke_handles(run_id, fence)` — SA:472 | `worker` | — | `run_lease` FOR SHARE → `invocation_context` | sets `revoked_at` on the run's handles (worker has no column grant) | none | T13/T15 |

Who performs which transition — SA:478-490: ∅ → QUEUED `create_run`; QUEUED → RETRIEVING → DRAFTING →
AWAITING_INPUT / ANSWERED / INSUFFICIENT_EVIDENCE / FAILED and AWAITING_INPUT → QUEUED `transition_run` (worker,
pre-grant only); DRAFTING → AWAITING_APPROVAL / BLOCKED_REVIEW `freeze_proposal`; AWAITING_APPROVAL → APPROVED /
REJECTED / BLOCKED_REVIEW `record_decision` (and `expire_proposal`); APPROVED / BLOCKED_REVIEW → QUEUED
`create_revision`; any pre-grant active state → CANCELLED `request_cancel`; APPROVED → EXECUTING / BLOCKED_REVIEW
`grant_execution`; EXECUTING → OUTCOME_UNKNOWN `mark_unknown`; EXECUTING / OUTCOME_UNKNOWN / ESCALATED → SUCCEEDED /
FAILED `record_outcome`; EXECUTING / OUTCOME_UNKNOWN → ESCALATED `escalate_run` or `record_outcome` on CONFLICT;
ESCALATED → ABANDONED_UNVERIFIED `resolve_escalation`. Proposed errata 1, 4, 5 and 9 (SESSION_STATE "Plan C executed")
touch rows of this table and are still undecided by the owner; `core/src/ops_core/states.py` already encodes them
(e.g. `create_manual_proposal` rows, states.py:162-163).

Other function-level facts:
- `app.current_time()` (AM-20.6, SA:528) is the 24th SQL function T09 names; it is not a definer function in the
  table.
- T07 Python mirror: `ops_core.states.Performer` has 13 members, one per transition-performing function
  (states.py:83-95); `require_transition(src, dst, performer, reason)` (states.py:248) is the table T09 "mirrors in SQL"
  (states.py:5).
- T47 restates `mcp_exec`'s EXECUTE list: "resolve_invocation, grant_execution, mark_sent, record_outcome,
  request_abort, lookup_action only" (`handoff/tasks.json` T47); T15: `mcp_read` "holds EXECUTE on resolve_invocation,
  asset_scope and search_procedures_scoped only".

### 2.5 AM-20.4 jobs, invocation_context, drafts (SA:492–506)

- `jobs(id, type, run_id, dedup_key UNIQUE, available_at, claimed_by, claimed_at, attempts, done_at)` — SA:494.
- `invocation_context(handle_sha256 PK, run_id, job_id, server ∈ {read, write}, fence, azp, expires_at, revoked_at)`;
  `resolve_invocation` derives `job_type` from `jobs` and `server` from that type (read for `investigate`/`resume_input`,
  write for `execute`/`recover`), never trusting the worker-written `server` column alone — SA:496.
- `drafts(id, run_id, draft_sha256, validated, kind, created_at)` holds only identifiers, the hash of the canonical
  validated draft and the verdict; the payload is held by the worker between validation and `freeze_proposal` and is
  never written to `drafts`, checkpoints or events — SA:496.
- Job creators and dedup keys — SA:498-504: `investigate` by `api` (admission) and `create_revision`, `run_id:revision`;
  `resume_input` by `api`, `run_id:clarification_event_id`; `execute` by `record_decision`, `proposal_id`; `recover` by
  `mark_unknown`, `worker` (after `cancelled`/`expired`), `reclaim_leases`, `action_id:trigger` with trigger ∈
  {`timeout`, `cancel`, `deadline`, `sweep:<bucket>`}; `expire_proposals`, `sync_memberships`, `sweep_wakeups`,
  `deliver_outbox` by the `sweeper` scheduler, `name:<minute bucket>`.
- `recover` cadence on ESCALATED/ABANDONED_UNVERIFIED: every 5 min for 1 h, then hourly, cap 48 — SA:506.
- Python: `ops_core.jobs.dedup_key(job_type, **ids)` builds these keys (jobs.py:150-…).

### 2.6 AM-20.5 row-level security (SA:508–524)

- Tenant tables: `memberships`, `conversations`, `messages`, `runs`, `run_state_history`, `jobs`, `drafts`,
  `proposals`, `decisions`, `execution_grant`, `action_attempt`, `action_attempt_state`, `events`, `outbox`,
  `feedback`, `documents`, `chunks`, `embeddings` — each `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY`
  ("the owner is subject to it; `migrator` is exempt only through its explicit `BYPASSRLS`") — SA:510.
- Policy text — SA:512-517:
  ```sql
  CREATE POLICY tenant_isolation ON <table>
    FOR ALL TO api, worker, sweeper, app_definer
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
  ```
  (No `NULLIF`: compare SA:446, which requires `NULLIF(…, '')::uuid` for reads inside functions; see §4.4 for what
  `''::uuid` does.)
- `app_definer` is a non-owner, so without this policy every definer function would see zero rows — SA:519.
- `memberships` and `jobs` carry one extra policy `sweeper_all FOR ALL TO sweeper USING (true)`; for every other table
  the sweeper iterates `tenants` (no RLS) and sets `app.tenant_id` per tenant before `expire_proposal`,
  `deliver_outbox` and deadline escalation; "These are the only policies besides `tenant_isolation`." — SA:520.
- `migrator` holds `BYPASSRLS` for data migrations only; never a runtime role — SA:521.
- `api`, `worker`, `sweeper` set `app.tenant_id` themselves per transaction; for them RLS is defense in depth, not a
  boundary against a compromised credential — SA:522 (also BS:248).
- No RLS: `run_directory`, `invocation_context`, `run_lease`, `sessions`, `idempotency_request`,
  `operator_resolutions`, `model_permit`, `tenants`, `app.test_clock`; "their grants (AM-20.2) are the control" — SA:523.
- R106 asserts the policy text per table (`pg_policies`) and that the definer path cannot read another tenant's rows —
  SA:524.
- BUILD_SPEC: "Keep tenant IDs in uniqueness constraints and cross-record references; composite foreign keys prevent
  attaching alpha children to beta parents." — BS:246 (R009). "Set tenant context within each transaction and clear it
  through transaction-local settings. Do not reuse pooled connection state across tenants." — BS:248 (R008).
- T09 review note 1 adds a "named cross-tenant sweeper policy for … session lookup" (sessions has no RLS per SA:523).

### 2.7 AM-20.6 / AM-20.7 test clock, profiles, fault hooks (SA:526–566, SA:156–162)

- `app.current_time()`: if `to_regclass('app.test_clock') IS NULL` then `clock_timestamp()`, else `clock_timestamp() +
  (EXECUTE 'SELECT clock_offset FROM app.test_clock LIMIT 1')`; `offset` is a reserved word, hence `clock_offset`; the
  dynamic `EXECUTE` avoids a static reference to a missing table — SA:528.
- "Every service, not only the bootstrap, asserts at start that the table is absent outside the test profile." —
  SA:528; T09 review note 5.
- The table is created by the Alembic branch `testclock`, which only `scripts/check.py --profile test` applies; the
  `dev` and `demo` bootstraps assert `to_regclass('app.test_clock') IS NULL` and refuse to start otherwise — SA:529.
- Only `test_harness` may write it; GUCs are never read (R126) — SA:530, SA:161.
- Profiles in v1 are `dev`, `test` and `demo` — SA:40; "R098's 'default' profile means the `dev` and `demo` profiles"
  — SA:49.
- Fault hooks are test-only, in an app factory shared as `core.testing.faults` that refuses to start unless
  `PROFILE=test` (R098; first used in T10, completed in T13); "The test clock is governed by AM-20.6, not by
  `PROFILE`." — SA:564 (also SA:534).
- BUILD_SPEC: "Fault hooks are test-harness-only and inaccessible in a public or normal web profile. Hooks must support
  response loss after commit, timeout before acceptance, delayed receipt visibility, malformed response, mismatching
  receipt hash, rate limit, transient unavailable, definitive no-commit failure and concurrent same-key submission." —
  BS:405.
- Freshness defaults "Configure and test them with an injected clock." — BS:476; AM-13 defaults table: dispatch
  deadline 5 min after grant, escalation deadline 30 min, request-dedup window 24 h, destination keys never expire —
  SA:291-299.

### 2.8 Other spec lines T09 cites or depends on

- `state_version` increases only on state transitions; events, heartbeats and attempt-state changes do not bump it —
  SA:151.
- Requester-asserted fields: `intent ∈ {investigate, answer_only}` and optional `supersedes_run_id` written only by
  `create_run`/`create_revision` from the authenticated request; a draft carrying `supersedes_run_id` is rejected by
  `freeze_proposal` — SA:154.
- Active states (hold the slot): QUEUED, AWAITING_INPUT, RETRIEVING, DRAFTING, AWAITING_APPROVAL, APPROVED, EXECUTING,
  OUTCOME_UNKNOWN — SA:145. ESCALATED frees the slot — SA:120; BLOCKED_REVIEW frees it — SA:139.
- One grant per run, ever: `execution_grant` `UNIQUE (run_id)`; `action_id` random UUIDv4 inside `grant_execution` —
  SA:167-168.
- Lease: `run_lease(run_id PK, owner, lease_until, fence bigint)` — SA:173.
- Attempt protocol: `action_attempt(action_id, attempt_no)` plus append-only `action_attempt_state(action_id,
  attempt_no, seq, state ∈ {INTENT, SENT, ABORT_REQUESTED, RESOLVED}, at)`; latest row by `seq` is the state — SA:227.
- Event sequence from `runs.next_event_seq`, incremented under the `runs` row lock in the inserting transaction (R089)
  — SA:303. Only `source ∈ {application, destination}` may emit `action.*`, `run.*`, `review.*`; `model_summary` only
  `explanation.ready` — SA:321-322.
- R082 "logged" half: "disallowed transitions rejected and logged" (matrix R082); `states.py:11-12`: "TODO(T09): R082
  also asks that a disallowed transition be *logged*; `require_transition` raises, and the SQL `transition_run` mirror
  records the refusal where the audit trail lives."
- BUILD_SPEC §6 records (BS:226-244) that T09's instructions name: `session` "opaque random session ID stored hashed;
  subject, active tenant, expiry, last activity, CSRF secret" (BS:229); `job` "run_id, type, dedup key, available_at,
  lease_owner, lease_until, fence, attempts, terminal flag; unique enqueue key" (BS:232; lease/fence superseded by
  `run_lease`, SA:33); `invocation_context` "hashed random handle, workload client, run_id, job_id, fence, allowed
  tools, expiry" (BS:233; allowed tools superseded, SA:45); `decision` "… idempotency key; immutable accepted decision"
  (BS:235); `execution_grant` "proposal_id, action_id, payload hash, authority snapshot, grant time, dispatch deadline,
  state; unique `(proposal_id, action_type)`" (BS:236; `state` superseded by SA:441, uniqueness by SA:167); `event`
  "unique `(run_id, sequence)`" (BS:239); `conversation / message` "unique `(conversation_id, sequence)`" (BS:230).
- BUILD_SPEC §9: handle "Store only its hash … maximum 60-second expiry … Refresh it only while the lease is current"
  (BS:360); "Rotate/revoke handles on lease loss, cancellation, policy change and completion" (BS:364).
- BUILD_SPEC §13: final gate "Lock/version-check permission records so the authorization snapshot and concurrent
  revocation have a defined ordering. Persist a single execution grant/action ID and dispatch intent. Commit before
  destination I/O." (BS:472); commit = authorization linearization point (BS:474).

### 2.9 T10 destination rules

- Single table `action_key(action_id PK, payload_sha256, state ∈ {COMMITTED, ABORTED, REJECTED}, incident_id NULL,
  reason NULL, decided_at)`; all three states permanent and terminal — SA:259.
- Tombstone shape (ABORTED and REJECTED): `{action_id, state, payload_sha256, reason, decided_at}` — SA:260.
- A validation rejection (malformed or disallowed payload) writes a permanent `REJECTED` key, so a lost response is
  recoverable by lookup — SA:261.
- incident-sim also requires the token's `azp` to be the mcp-write client — SA:262; accepts only the `incident-sim`
  audience workload token — SA:270; "incident-sim trusts only mcp-write" — SA:555.
- Both `POST /internal/incidents` and `POST /internal/actions/{id}/abort` use `INSERT … ON CONFLICT (action_id) DO
  NOTHING` then read the row, at READ COMMITTED; first writer wins — SA:263.
- An incident row is inserted in the same transaction only when the key commits — SA:264.
- Rows are never deleted or expired, not even tombstones — SA:265; BS:504 ("never TTL-delete unresolved actions").
- Abort carries the grant's `payload_sha256`, which the tombstone stores — SA:266.
- Hash comparison applies only to COMMITTED keys; a POST onto ABORTED or REJECTED returns that tombstone whatever hash
  it carries and never commits; abort onto REJECTED returns the REJECTED tombstone; fault tests: late POST after abort,
  and after rejection (R096) — SA:267.
- Recompute `sha256` over the received bytes; different hash under an existing COMMITTED key → CONFLICT — SA:268.
- `GET /internal/actions/{action_id}` retained: COMMITTED with receipt, ABORTED or REJECTED with tombstone, or
  NOT_FOUND; NOT_FOUND is never a no-commit — SA:269; BS:487.
- Abort outcomes seen by the caller: existing receipt → SUCCEEDED; existing REJECTED tombstone → FAILED(`rejected`);
  fresh ABORTED → FAILED(`aborted_no_commit`) after SENT, FAILED(`cancelled_before_send`/`expired`) from INTENT —
  SA:241-242, SA:280, SA:465; `ops_core.outcomes.outcome_from_destination` implements the mapping (outcomes.py:43-65).
- `abort_incident(proposal_id)` tool: `recover` jobs only; result `data`: `{action_id, outcome:
  SUCCEEDED|FAILED_NO_COMMIT, receipt|tombstone}` — SA:336, SA:356; input schema
  `schemas/tools/abort_incident.input.schema.json`. No HTTP schema for incident-sim's abort route exists in `schemas/`.
- BUILD_SPEC: "The incident service accepts only the MCP executor workload, not arbitrary web/worker traffic." — BS:401;
  "Same key/same hash returns the existing result. Same key/different hash conflicts. Do not implement 'SELECT, then
  INSERT' outside a uniqueness-protected transaction" — BS:407; POST carries "trusted executor identity plus action ID,
  exact canonical payload/hash and grant metadata" — BS:486; "Use an independent destination database and
  credentials." — BS:489; "The assistant database and destination receipts must not be wiped together in a recovery
  demonstration." — BS:504.
- Detective check (T10 review note 3): "every destination key matches a grant hash". No further spec text defines its
  owner, schedule or output.

---

## 3. The tree as it is (branch `plan-d`, `2ae75d9`)

### 3.1 Revision 1, database `ops`, schema `app` (`migrations/app/versions/0001_walking_skeleton.py`)

`revision = "0001_walking_skeleton"`, `down_revision = None`, `branch_labels = None`, `depends_on = None`. `upgrade()`
splits the `DDL` string on `";\n"` and runs each piece with `op.execute` (lines 211-214), then seeds with
`op.bulk_insert`. `downgrade()` is `DROP SCHEMA app CASCADE`. Everything is created and owned by the Compose superuser
`ops` (measured: `app` schema owner `ops`, every `app` table owner `ops`, zero grants to any other role).

| Table | Columns (type, constraint) | Keys / indexes | vs AM-20 |
|---|---|---|---|
| `tenants` | `tenant_id uuid PK`, `name text NOT NULL UNIQUE` | | no RLS (SA:523) |
| `memberships` | `tenant_id uuid NOT NULL → tenants`, `issuer text`, `subject uuid`, `role text CHECK (requester/reviewer/reader)`, `active bool DEFAULT true`, `permission_version int DEFAULT 1`, `synced_at timestamptz DEFAULT now()` | PK `(tenant_id, issuer, subject, role)` | one row per role |
| `conversations` | `conversation_id uuid PK`, `tenant_id uuid → tenants`, `created_by uuid`, `created_at` | `UNIQUE (tenant_id, conversation_id)` | |
| `messages` | `message_id uuid PK`, `tenant_id`, `conversation_id`, `kind text`, `text text`, `context jsonb`, `author uuid`, `created_at` | composite FK `(tenant_id, conversation_id)` → conversations | no `sequence` (BS:230 unique `(conversation_id, sequence)`) |
| `runs` | `run_id uuid PK`, `tenant_id`, `conversation_id`, `message_id → messages(message_id)` (single-column FK), `requester uuid`, `intent CHECK (investigate/answer_only)`, `supersedes_run_id uuid`, `asset_id text NOT NULL`, `start_at`, `end_at` (`CHECK start_at < end_at`), `state text`, `state_version int DEFAULT 1`, `reason text`, `active_proposal_id uuid`, `cancel_requested bool DEFAULT false`, `created_at`, `updated_at` | `UNIQUE (tenant_id, run_id)`; composite FK `(tenant_id, conversation_id)`; partial unique index `runs_one_active_per_conversation ON (conversation_id) WHERE state IN (<8 active states>)` | missing `cancel_requested_at`, `checkpoint_id`, `budget_used`, `next_event_seq`, `slot_held` (SA:415); slot index is on `state`, SA:451 says `WHERE slot_held` |
| `run_state_history` | `run_id → runs`, `seq int`, `from_state`, `to_state`, `performer text`, `reason`, `at DEFAULT now()` | PK `(run_id, seq)`; `seq` = the new `state_version` | **no `tenant_id`** (RLS table, SA:510) |
| `jobs` | `id uuid PK`, `type text`, `run_id uuid NOT NULL → runs`, `dedup_key text NOT NULL UNIQUE`, `available_at DEFAULT now()`, `claimed_by`, `claimed_at`, `attempts int DEFAULT 0`, `done_at`, `created_at` | index `jobs_claimable (available_at) WHERE done_at IS NULL AND claimed_at IS NULL` | **no `tenant_id`**; `run_id NOT NULL` (sweeper job types have no run, SA:504) |
| `invocation_context` | `handle text PK` (raw), `run_id → runs`, `job_id → jobs`, `server CHECK (read/write)`, `fence int DEFAULT 1`, `azp text`, `expires_at`, `revoked_at`, `created_at` | | `handle_sha256 PK` required (SA:496, BS:360; ruling 7 exception) |
| `drafts` | `id uuid PK`, `run_id → runs`, `draft_sha256 text`, `validated bool`, `kind text`, `created_at` | | **no `tenant_id`** |
| `proposals` | `proposal_id uuid PK`, `tenant_id`, `run_id → runs(run_id)` (single-column FK), `revision int`, `draft_id → drafts`, `payload jsonb`, `payload_canonical bytea`, `payload_sha256 text`, `canonicalization_version int`, `authored_by uuid[]`, `expires_at`, `frozen_at DEFAULT now()` | `UNIQUE (run_id, revision)` | no composite tenant FK (R009) |
| `decisions` | `decision_id uuid PK`, `proposal_id UNIQUE → proposals`, `reviewer uuid`, `decision CHECK (approve/reject)`, `reason`, `expected_payload_sha256`, `decided_at` | `UNIQUE (proposal_id)` = first decision wins | **no `tenant_id`**; no `idempotency_key` (SA:454, BS:235) |
| `execution_grant` | `action_id uuid PK`, `run_id UNIQUE → runs`, `proposal_id → proposals`, `payload_sha256`, `granted_at` | `UNIQUE (run_id)` | **no `tenant_id`**; no authority snapshot / dispatch deadline (BS:236) |
| `action_attempt` | `action_id → execution_grant`, `attempt_no int`, `created_at` | PK `(action_id, attempt_no)` | **no `tenant_id`** |
| `action_attempt_state` | `action_id`, `attempt_no`, `seq int`, `state CHECK (INTENT/SENT/ABORT_REQUESTED/RESOLVED)`, `outcome text`, `detail jsonb`, `at` | PK `(action_id, attempt_no, seq)`; FK → action_attempt | **no `tenant_id`** |
| `events` | `event_id uuid PK`, `tenant_id`, `conversation_id`, `run_id → runs`, `sequence int`, `type text`, `occurred_at`, `source CHECK (application/destination/model_summary)`, `payload jsonb` | `UNIQUE (run_id, sequence)` | |

Absent tables (ruling 7 of Plan D: "their owners add them"): `run_directory`, `run_lease`, `sessions`, `outbox`,
`feedback`, `idempotency_request`, `operator_resolutions`, `documents`, `chunks`, `embeddings`, `model_permit`,
`app.test_clock`, schema `checkpoints`. T09's instructions name `run_directory`, `run_lease` and `sessions` explicitly.

Seeds (lines 215-235): 2 `tenants` rows and 5 `memberships` rows (one per persona role) from `data/seed-ids.json`;
`issuer` frozen at migration time from `OPS_KC_ISSUER` or `http://localhost:18080/realms/ops-dev` (declared debt →
T09 membership sync). Default timestamps use `now()` throughout (SA:157 asks for `clock_timestamp()` for comparisons).

### 3.2 Revision 1, database `incident` (`migrations/incident/versions/0001_walking_skeleton.py`)

Same revision id `0001_walking_skeleton`, same splitter. Runs as superuser `ops` against database `incident`:
`CREATE SCHEMA incident AUTHORIZATION incident`; `incident.action_key(action_id uuid PK, payload_sha256 text NOT NULL,
state text CHECK (COMMITTED/ABORTED/REJECTED), incident_id text, reason text, receipt_id uuid, decided_at timestamptz
DEFAULT now())`; `incident.incident_seq` sequence (gaps allowed: a conflicting insert consumes `nextval`);
`incident.incidents(incident_id text PK, action_id uuid UNIQUE → action_key, payload jsonb, created_at)`; all three
objects `OWNER TO incident`. `downgrade()` drops the schema. Observed live: 51 `action_key` rows, all `COMMITTED`;
`public.alembic_version` in database `incident` = `0001_walking_skeleton`.

### 3.3 `ops_core.persistence` today (`core/src/ops_core/persistence.py`)

| Line | Name | What it does today | Marker |
|---|---|---|---|
| 33-46 | `PersistenceError`, `NotFound`, `VersionConflict`, `HandleRejected` | safe-message exceptions | — |
| 49 | `connect(pg)` | one autocommit `AsyncConnection`, `dict_row` (ruling 24) | — |
| 59 | `Session(conn)`: `unit()`, `read(query, params)` | process-wide `asyncio.Lock` + `conn.transaction()`; `read` = one autocommit SELECT under the lock | `TODO(T13): a pool` (line 62) |
| 80 | `run_row(conn, run_id, lock=False)` | `SELECT * FROM app.runs WHERE run_id = %s [FOR UPDATE]` | — |
| 89 | `transition(conn, *, run_id, dst, performer, reason=None, expected_version=None)` | locks runs, checks version, `require_transition`, `UPDATE app.runs SET state, state_version, reason, updated_at = now()`, `INSERT app.run_state_history (seq = new version)` | `TODO(T09): becomes the SQL transition_run / per-performer definer functions; callers keep this signature.` (101) |
| 120 | `create_run(conn, *, run_id, tenant_id, conversation_id, message_id, requester, intent, asset_id, start_at, end_at, supersedes_run_id=None)` | INSERT runs (QUEUED, v1), history row 1, `insert_job(investigate, revision=1)` | `TODO(T09): SQL create_run.` (134) |
| 162 | `append_event(conn, *, tenant_id, conversation_id, run_id, type, source, payload, occurred_at=None)` | `event_rules_ok`; `SELECT … FOR UPDATE` on runs; `MAX(sequence)+1`; INSERT events | `TODO(T14): append_event definer function with next_event_seq.` (177) |
| 217 | `insert_job(conn, *, job_type, run_id, **ids)` | INSERT jobs `ON CONFLICT (dedup_key) DO NOTHING RETURNING id` | none |
| 229 | `claim_job(conn, *, worker_name)` | `UPDATE app.jobs SET claimed_by, claimed_at = now(), attempts+1 WHERE id = (… FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *` | `TODO(T13): lease + fence.` (230) |
| 240 | `finish_job(conn, job_id)` | `UPDATE app.jobs SET done_at = now()` | none |
| 244 | `requeue_job(conn, job_id, delay_seconds)` | `UPDATE app.jobs SET claimed_by = NULL, claimed_at = NULL, available_at = now() + …` (writes `available_at`, which is not in the worker's AM-20.2 column list) | `TODO(T13): bounded retries.` (245) |
| 253 | `mint_handle(conn, *, run_id, job_id, server, azp, ttl_seconds=60)` | `secrets.token_urlsafe(32)`; INSERT `invocation_context` raw | docstring "Stored raw: debt → T09/T15" (no `TODO` tag) |
| 268 | `Invocation` (dataclass) | run_id, job_id, job_type, tenant_id, conversation_id | — |
| 276 | `check_invocation(row, *, server, azp, tool, now)` | pure: expiry, revocation, server from job type, azp, tool allowlist | — |
| 291 | `resolve_handle(conn, *, handle, server, azp, tool)` | SELECT invocation_context JOIN jobs JOIN runs by raw handle; `check_invocation` with wall clock | `TODO(T09/T15): SQL resolve_invocation.` (293) |

Other markers in the tree: `api/src/ops_api/store.py:6` "TODO(T09): `create_run`/`record_decision` definer functions";
`worker/src/ops_worker/handlers.py:154` "TODO(T09): freeze_proposal definer function; the worker loses INSERT on
proposals under the grant table"; `mcp-write/src/ops_mcp_write/execution.py:2` "TODO(T09/T22): the SECURITY DEFINER
functions"; `core/src/ops_core/states.py:11` (R082 logged half); `incident-sim/src/ops_incident_sim/keys.py:7`
"TODO(T10): abort (`ABORTED`), `REJECTED` via the fault factory, and the detective check against grant hashes."

### 3.4 SQL each service runs today (grouped by service; what its future role must be allowed or replaced by)

All application processes connect as superuser `ops` via `settings.app_postgres()` (settings.py:96-99: "as the single
owner role the skeleton is allowed (debt → T09)"), one autocommit connection each.

**api** (`api/src/ops_api/store.py`, future role `api`):
- `SELECT tenant_id, role FROM app.memberships WHERE issuer = %s AND subject = %s AND active` (145) — runs on every
  request **before any tenant is known** (`app.py:115`, `identity` dependency); under `tenant_isolation` on
  `memberships` this returns nothing for `api`.
- `INSERT INTO app.conversations …` (156) — AM-20.2 ins.
- admit (one unit): `SELECT 1 FROM app.conversations WHERE … AND tenant_id` (178); optional `SELECT 1 FROM app.runs
  WHERE run_id AND tenant_id AND conversation_id` (186); `INSERT INTO app.messages …` (192); `persistence.create_run`
  (204, → `create_run()`); `persistence.append_event(run.accepted)` (217; `append_event` refuses `run.*` under SA:452 —
  `create_run` emits it). `UniqueViolation` on `runs_one_active_per_conversation` → 409 `SLOT_OCCUPIED`.
- reads: `SELECT * FROM app.runs WHERE run_id AND tenant_id` (236) and `SELECT p.*, r.requester, r.state … FROM
  app.proposals p JOIN app.runs r … WHERE p.tenant_id` (243) through `Session.read` (autocommit, single statement);
  `SELECT sequence, type, source, occurred_at, payload FROM app.events WHERE run_id AND tenant_id …` (317).
- decide (one unit, 254-312): SELECT proposal; `run_row(lock=True)` (`SELECT … FOR UPDATE` on runs); `INSERT INTO
  app.decisions` (270; denied under AM-20.2); `persistence.transition` → APPROVED/REJECTED; `insert_job(EXECUTE)`
  (280; api may insert only `resume_input`); `append_event(approval.recorded | run.rejected)`. All of it is
  `record_decision()`. Reviewer independence is checked in Python before the unit (`app.py:247-252`, `check_reviewer`).

**worker** (`worker/src/ops_worker/handlers.py`, `main.py`; future role `worker`):
- `claim_job` (main.py:36), `finish_job`, `requeue_job` — jobs UPDATEs; `requeue_job` writes `available_at`.
- `run_row(lock=True)` (80, 209); `SELECT text FROM app.messages WHERE message_id` (84).
- `persistence.transition(… TRANSITION_RUN)` → RETRIEVING (89), DRAFTING (120), FAILED / INSUFFICIENT_EVIDENCE via
  `_fail` (65).
- `persistence.append_event`: `tool.started`/`tool.completed` (52), `run.failed`/`run.insufficient_evidence` (66,
  refused by `append_event` under SA:452 — `transition_run` emits `run.*`), `explanation.ready` with
  `source=model_summary` and `proposal.ready` (182, 195).
- `mint_handle` (92, 214) — INSERT invocation_context (raw handle).
- freeze (153-180): `INSERT INTO app.drafts` (157, allowed), `INSERT INTO app.proposals` (161, denied),
  `UPDATE app.runs SET active_proposal_id` (177, denied), `transition(FREEZE_PROPOSAL)`, two events → all
  `freeze_proposal()`.
- health: own second connection, `SELECT 1` (main.py:64).

**mcp-read** (`mcp-read/src/ops_mcp_read/server.py`; future role `mcp_read`): `persistence.resolve_handle` (180)
inside a unit; health `SELECT 1` (228). `search_procedures` is served from `data/handoff-fixtures/` (no SQL).

**mcp-write** (`mcp-write/src/ops_mcp_write/execution.py`, `server.py`; future role `mcp_exec`, no table grants):
- `resolve_handle` (server.py:176); health `SELECT 1` (235).
- `load_grant`: `SELECT … FROM app.execution_grant JOIN app.runs JOIN app.proposals JOIN LATERAL (… app.action_attempt_state
  ORDER BY attempt_no DESC, seq DESC LIMIT 1)` (51-79).
- `grant_execution` (93-138): `run_row(lock)`, SELECT proposals, SELECT decisions, INSERT execution_grant,
  INSERT action_attempt, INSERT action_attempt_state (INTENT, `seq = MAX+1`, 84-90), `transition(GRANT_EXECUTION)`,
  `append_event(action.granted)`.
- `mark_sent` (153-168): `run_row(lock)`, latest attempt, INSERT SENT, `append_event(action.dispatched)`.
- `record_outcome` (171-224): `run_row(lock)`, INSERT RESOLVED (outcome + detail jsonb), `transition(RECORD_OUTCOME)`,
  `append_event(action.confirmed | action.failed | action.conflict, source=destination)`.
- `mark_unknown` (227-240): `transition(MARK_UNKNOWN)` EXECUTING → OUTCOME_UNKNOWN + `append_event(action.uncertain)`
  — called by mcp-write after a failed destination call (`create_incident`, 290-292). AM-20.3 grants `mark_unknown`
  to `worker` only (SA:467) and T47's `mcp_exec` list omits it.
- Unit boundaries (`create_incident`, 270-301): grant unit; `mark_sent` unit committed before the POST; POST outside
  any transaction; outcome unit.

**incident-sim** (`incident-sim/src/ops_incident_sim/keys.py`, `app.py`; role `incident`, database `incident`):
- `INSERT INTO incident.action_key (…, 'COMMITTED', 'INC-' || lpad(nextval('incident.incident_seq')::text, 6, '0'),
  receipt_id) ON CONFLICT (action_id) DO NOTHING RETURNING *` (keys.py:48-53); on insert, `INSERT INTO
  incident.incidents` (57-60); else `SELECT * FROM incident.action_key WHERE action_id` (69).
- `app.py`: `POST /internal/incidents` (117-138): strict JSON parse, `IncidentRequest` (strict, `extra="forbid"`),
  `payload_canonical` parsed strictly and must be a non-empty object, hash recomputed over the received UTF-8 bytes;
  malformed body or hash mismatch → **422 `INVALID_INPUT` and no key row** (SA:261 asks for a permanent REJECTED key on
  a validation rejection); `keys.document(row, presented_sha256)` (keys.py:78-97): COMMITTED + different hash → 409
  `{"state": "CONFLICT", …}`; ABORTED/REJECTED → 200 with tombstone regardless of presented hash (already SA:267's
  rule); tombstone `reason` falls back to `state.lower()`. `GET /internal/actions/{action_id}` (140-152) → same
  document or 404 `NOT_FOUND`. No abort route, no fault hooks, no `PROFILE` handling.
- Token: `TokenVerifier(issuer, audience="incident-sim", allowed_azp=frozenset({"ops-mcp-write"}))` (app.py:155-158);
  `ops_core.tokens.TokenVerifier.verify` checks `aud` via PyJWT (tokens.py:127-137) and `azp ∈ allowed_azp`
  (tokens.py:140-142). **azp = mcp-write is already enforced.** Every refusal (wrong aud, wrong azp, bad signature) is
  `TokenRejected` → **401** (app.py:86-97; ruling 25 of Plan D: "T10's 403 for 'authenticated but not this audience' is
  its own refinement"). The worker's token carries `aud = {MCP_READ_RESOURCE_URL, MCP_WRITE_RESOURCE_URL}`, a persona
  token `aud = ops-api` (realm, §3.8), so today both fail the audience check → 401.
- Isolation: role `incident` owns `incident.*` (so it can DELETE its own rows; nothing but code prevents deletion);
  it has `CONNECT` on database `ops` through the PUBLIC default (measured; SESSION_STATE debt "incident can CONNECT to
  ops … → T09").

### 3.5 Roles and grants that exist now (measured, read-only)

- Roles (non-`pg_`): `ops` (`rolsuper`, `rolbypassrls`), `incident` (LOGIN; not super, no CREATEROLE, no BYPASSRLS),
  and five leftovers `spike_api`, `spike_definer` (NOLOGIN), `spike_member`, `spike_migrator`, `spike_sweeper` (LOGIN)
  that own no relation or function in either database. The Plan D spike's write-up says its roles were dropped
  (`docs/superpowers/research/2026-10-08-plan-d-spike.md:1321`); these five have different names and their origin is
  not recorded in the repository.
- Databases: `ops`, `incident`, `postgres`. Extensions in `ops`: `plpgsql 1.0`, `vector 0.8.7`
  (`deploy/dev/postgres/init/01-init.sql` creates `vector` and database `incident`).
- No grant on any `app` table to any role other than `ops`. A fresh role gets `CONNECT` on `ops` and `incident` and no
  `CREATE` on schema `public` (PG 15+ default).
- `default_transaction_isolation` = `read committed`.
- 7 rows in `app.runs` (live-test/R105 leftovers).

### 3.6 `scripts/skeleton.py migrate` and how Alembic is driven

- `migrate()` (skeleton.py:96-103): load `.env`, export `OPS_*`; `ensure_incident_role` (59-80) connects as `ops` to
  database `incident` and creates or re-keys role `incident` via `set_config('ops.incident_password', %s, false)` +
  `DO $$ … EXECUTE format('CREATE ROLE incident LOGIN PASSWORD %L', current_setting(…)) … $$`, then `GRANT CONNECT ON
  DATABASE incident TO incident`, then clears the setting; `upgrade("app", app_pg)`; `upgrade("incident",
  incident_as_superuser)`; prints `MIGRATE: app and incident at head`.
- `upgrade(tree, pg)` (83-93): SQLAlchemy engine from a `URL` object (password never rendered),
  `engine.begin()`, `cfg.attributes["connection"] = connection`, `command.upgrade(cfg, "head")`. No `alembic.ini`.
- `migrations/*/env.py`: refuses to run without `config.attributes["connection"]`; `context.configure(connection=…,
  target_metadata=None, version_table="alembic_version")` — the version table is in the connection's default schema
  (`public`) because Alembic writes it before revision 0001 creates the schema. Offline mode unsupported.
- The e2e `migrated` fixture calls `migrate()` (tests/e2e/conftest.py:45-49); runbook
  `docs/runbooks/walking-skeleton.md:8`.

### 3.7 Tests that touch the database and constraints on secrets

- `tests/e2e/` (live only, `OPS_LIVE=1`): `conftest.py` (fixtures `live`, `env`, `secret`, `migrated`, `app_conn` =
  owner autocommit connection), `test_migrations_and_persistence.py` (5 tests; inserts its own random tenant into
  `app.tenants` as owner at line 29; `force_rollback=True` transactions), `test_mcp_read_live.py` (1; `purge_run`),
  `test_mcp_write_live.py` (3; inserts drafts/proposals/decisions directly at 76-90; `purge_run` + `purge_tenant`),
  `test_worker_live.py` (3; `force_rollback`; inserts a decision directly at 110), `test_incident_sim_live.py` (1; as
  role `incident`, `force_rollback`; asserts `incident` cannot read `app.runs`), `test_r105_walking_skeleton.py` (1;
  reads `app.jobs` as owner at 164), `test_tokens_live.py` (1). Live suite: `14 passed` (SESSION_STATE).
- `purge_run` (conftest.py:80-97) deletes, as the owner, from `invocation_context`, `events`, `action_attempt_state`,
  `action_attempt`, `execution_grant`, `decisions`, `proposals`, `drafts`, `jobs`, `run_state_history`, `runs`,
  `messages`, `conversations`; `purge_tenant` (100-105) deletes `memberships` and `tenants` of non-seeded tenants.
  Docstring: "This deletes test-created rows from append-only audit tables as the owner role (ruling 27); T09's grants
  will refuse that, and the live tests then get a per-session schema or a reset."
- Ruling 27 (Plan D): "Live-test clean-up deletes test-created rows from append-only audit tables … as the owner role,
  because the skeleton has one role and the dev database is shared. T09's grants will forbid that; the live tests then
  move to a per-session schema or a database reset, which is T09's concern."
- DB-free unit tests: `tests/plan_d/test_api.py` (in-memory `FakeStore`, which does not check the tenant — open item),
  `test_incident_sim.py` (`FakeStore` with first-writer-wins), `test_mcp_write.py`, `test_worker.py`,
  `test_persistence_pure.py`, `test_settings.py`, `test_tokens.py`, `test_mcp_read.py`, `test_skeleton_evidence.py`.
- Secret constraints: `tests/plan_b/test_bootstrap_dev.py:15-19` requires `set(compose.yaml top-level secrets) ==
  set(scripts/bootstrap_dev.SECRET_NAMES)`; `test_compose_dev.py:55-65` requires every top-level secret's `file` to be
  exactly `${OPS_SECRETS_DIR}/<name>` and every secret used by `postgres`/`keycloak` to be declared;
  `test_compose_dev.py:46-52` forbids any `environment:` key containing PASSWORD/SECRET unless it ends `_FILE` and
  points at `/run/secrets/`. `SECRET_NAMES` today (bootstrap_dev.py:26-40): `postgres_password`,
  `postgres_incident_password`, `kc_bootstrap_admin_password`, four `kc_client_secret_ops_*` (web, worker, mcp_read,
  mcp_write), `kc_client_secret_ops_view_users`, five `kc_persona_*_password`. `postgres_incident_password` is the
  precedent: declared at top level, not mounted into any service, read by `skeleton.py` (settings.py:102-111).
  `ops_core.settings.read_secret(name)` reads `OPS_SECRETS_DIR/<name>`; messages never carry the path or value.

### 3.8 `scripts/check.py`, the realm, seed IDs

- `scripts/check.py` (62 lines): `members_importable()`, then `ruff check .`, `ruff format --check .`, `mypy` on the
  seven member `src` trees, `pytest -q`; prints `CHECK: GREEN|RED`. **No arguments, no `--profile`, no database
  step.** Last recorded: `457 passed, 44 skipped` (SESSION_STATE).
- Realm `ops-dev` (`deploy/dev/keycloak/realm-ops-dev.json`): realm roles `requester`, `reviewer`, `reader`; clients
  `ops-web` (confidential, no audience mapper), `ops-worker` (service account; aud `${MCP_READ_RESOURCE_URL}`,
  `${MCP_WRITE_RESOURCE_URL}`), `ops-mcp-read` (service account; aud `asset-sim`), `ops-mcp-write` (service account;
  aud `incident-sim`), `ops-dev-direct` (public, direct grant; aud `ops-api`), `ops-view-users` (service account with
  `realm-management: view-users`). Users: `alex` (requester), `sam` (reviewer), `lee` (reader), `riley` (requester),
  `jordan` (reviewer).
- `data/seed-ids.json`: tenants `alpha` `3ea79c95-914c-52cb-9d10-c4e19dda8ff7`, `beta`
  `5ab45c2c-1e12-5a0c-a2b9-66cd2ff05201`; personas alex `2fc05986-c7ec-544c-b628-fdb112bbf18a` (alpha, requester), sam
  `03f7eb09-e18d-5f33-bf75-12c57d5aaa54` (alpha, reviewer), lee `abcc1200-6791-57ab-87b5-9392d356b512` (alpha, reader),
  riley `2f73af91-4906-5b79-9144-22c0df4e2316` (beta, requester), jordan `cb551e64-83ec-582b-9047-8dadf20e151a` (beta,
  reviewer).
- `compose.yaml`: `postgres` = `pgvector/pgvector:pg17@sha256:ac08538c…a75d`, `POSTGRES_USER: ops`, `POSTGRES_DB: ops`,
  `POSTGRES_PASSWORD_FILE`, init dir mounted, port `127.0.0.1:${PG_PORT}` (15432 in `.env`); `keycloak` 26.8.0 by
  digest; network `ops-dev-net`; profile `dev` only (no `test`/`demo` profile exists).
- No `core/src/ops_core/testing/`, no `PROFILE` variable, no `test_clock`/`current_time` anywhere outside `reference/`.

---

## 4. Library and server facts (measured 2026-10-08)

Method: library source read read-only under `<repo>/.venv`; Alembic branch behaviour measured offline (`sql=True`)
with a throw-away script directory under `<scratch>/alem`; PostgreSQL behaviour measured against the running dev
container (port 15432) as `ops` inside **one transaction opened with `force_rollback=True`** (temporary roles
`m_definer`, `m_caller`, `m_owner` and schema `m`; after the rollback `pg_roles` held 0 `m_*` roles). Script:
`<scratch>/pgmeasure.py`. No docker command was run; no process was started.

### 4.1 Versions

| Component | Version (source) |
|---|---|
| PostgreSQL | 17.11 (Debian 17.11-1.pgdg12+2); `psycopg` `conn.info.server_version` = `170011` |
| pgvector extension | 0.8.7 |
| psycopg / psycopg-binary | 3.3.6, `pq.__impl__ = binary`, libpq `180004` |
| psycopg_pool | not installed |
| SQLAlchemy | 2.1.4 (psycopg dialect `paramstyle = pyformat`) |
| Alembic | 1.20.0 |
| pytest / pytest-asyncio | 9.1.1 / 1.4.0 |
| FastAPI / mcp / PyJWT | 0.143.0 / 2.3.0 / 2.15.1 |
| langgraph, langgraph-checkpoint-postgres | not locked (AM-30 pins checkpoint-postgres 3.1.2, SA:581) |

### 4.2 Alembic branches and labels (measured offline)

Script directory: `0001_walking_skeleton` → `0002_roles` (→ `0003_more` in the second run) plus `tc_0001` with
`down_revision=None`, `branch_labels=("testclock",)`, `depends_on="0002_roles"`.
- `get_heads()` = `['0002_roles', 'tc_0001']`; `get_bases()` = `['0001_walking_skeleton', 'tc_0001']`.
- `command.upgrade(cfg, "head")` → `CommandError: Multiple head revisions are present for given argument 'head'; please
  specify a specific target revision, '<branchname>@head' to narrow to a specific head, or 'heads' for all heads`.
  **`skeleton.py`'s `upgrade(tree, …)` calls exactly `"head"`**, so adding a second head to `migrations/app` breaks
  `migrate` unless the target changes.
- `upgrade heads` and `upgrade testclock@head` both apply 0001 → 0002 → `tc_0001` (the `depends_on` pulls the main line
  in first). With `depends_on`, the version table ends with **one** row `tc_0001` (Alembic treats the dependency as an
  ancestor); after a later main revision `0003_more`, `upgrade heads` re-inserts a second row (`0003_more`).
- With `branch_labels=("app",)` on `0001_walking_skeleton`, `upgrade app@head` applies only the main line
  (0001 → 0002 → 0003) and never the `testclock` branch.
- From a database at `0002_roles`, `upgrade 0002_roles:heads` applies only `tc_0001` and `0003_more`; from
  `0003_more`, only `tc_0001`.
- So a profile-only branch is applied by naming it (`testclock@head` or `heads`) in the test profile and the main label
  (`app@head` or the explicit main head) elsewhere. Downgrading a single branch online was not measured (offline
  `downgrade` with `heads:` is refused: "Multiple head revisions …").

### 4.3 `op.execute`, multi-statement SQL and dollar quoting

- `op.execute(str)` wraps the string in `sqlalchemy.text()` (`alembic/ddl/impl.py:216-217`).
- `text()` bind parsing (measured by compiling with the psycopg dialect): `:=`, `::uuid` and `'a:b'` are **not** binds;
  a colon-word preceded by a space or quote inside a string literal **is** (`SELECT ' :name'` → `StatementError: A
  value is required for bind parameter 'name'`; `SELECT 'x:name'` is fine). Literal `%` is compiled to `%%` and
  converted back by psycopg (SQLAlchemy passes `{}` as parameters; `format('%s:%s', 'a', 'b')` in a PL/pgSQL body
  returned `a:b` after a real `op.execute`).
- psycopg 3.3.6 uses the **simple query protocol when there are no parameters** (`_cursor_base.py:449-459`:
  `send_query_params` only if `force_extended or query.params or fmt == BINARY`), so one `execute` may carry several
  statements and `$$` bodies: measured `DO $$ BEGIN PERFORM 1; PERFORM 2; END $$; SELECT 42` → ok; through
  `op.execute`, `CREATE FUNCTION … AS $$ … $$; SELECT …` → ok. With parameters it is refused: `SELECT %s; SELECT 2` →
  `cannot insert multiple commands into a prepared statement`.
- Revision 1's splitter (`DDL.split(";\n")`, `0001_walking_skeleton.py:212`) **cuts PL/pgSQL bodies apart**: a
  12-line `CREATE FUNCTION app.current_time() … $$ … $$;` plus one `GRANT` became 8 fragments, each ending at an inner
  `;\n` (measured). Function DDL needs one `op.execute` per function (or a splitter that respects dollar quotes).

### 4.4 PostgreSQL semantics (measured in the rolled-back transaction)

- **Superuser bypass:** `ops` (superuser) saw both rows of a table with `ENABLE` + `FORCE ROW LEVEL SECURITY` and no
  tenant set. A non-superuser **table owner** with no policy naming it saw 0 rows under `FORCE`.
- **Definer identity:** called as `m_caller` (via `SET LOCAL SESSION AUTHORIZATION`), a `SECURITY DEFINER` function
  owned by `m_definer` reported `session_user = m_caller`, `current_user = m_definer`. `SET ROLE` would not change
  `session_user`; only a real login (or `SET SESSION AUTHORIZATION`, superuser-only) does.
- **Function attributes:** `pg_proc.proconfig` = `['search_path=m, pg_temp', 'app.tenant_id=']`, `prosecdef = true`.
- **Preset tenant is ignored:** caller preset `app.tenant_id = beta` (session-level `set_config(…, false)`); inside the
  function the value at entry was `''` (the attribute), the function set alpha with `set_config(…, true)`, saw exactly
  1 row (alpha), and after the call the caller's setting was **beta again** (restored by the attribute).
- **Plain SET leaks even with the attribute:** a definer function with `SET app.tenant_id = ''` that runs
  `set_config('app.tenant_id', p, false)` left the caller's setting at `'inner'` after return; same without the
  attribute; `set_config(…, true)` inside a function **without** the attribute also left `'inner'` for the rest of the
  transaction. Only "attribute + transaction-local" restores the caller's value — this is what T09 DoD 5's test
  distinguishes.
- **Policy cast on empty string:** with `app.tenant_id = ''`, any read of an RLS table under the AM-20.5 policy
  raises `InvalidTextRepresentation: invalid input syntax for type uuid: ""` (not zero rows).
  `NULLIF(current_setting('app.tenant_id', true), '')::uuid` returns NULL. A never-set custom GUC returns NULL via
  `current_setting(…, true)`; **once set locally in a session, it reads `''` after the transaction ends** (measured on
  a fresh autocommit connection: `None` → after a transaction with `set_config(…, true)`: `''`). So on a reused
  connection, and at the top of every definer function (attribute `''`), the policy as written errors rather than
  returning zero rows until `set_config` runs.
- **Autocommit and local settings:** on an autocommit psycopg connection, `SELECT set_config('app.tenant_id','x',true)`
  outside an explicit transaction lasts only that statement (the next statement read `''`). `Session.read()` issues
  exactly such single autocommit statements.
- **Default EXECUTE:** a new function is executable by any role via PUBLIC (`has_function_privilege` true) until
  `REVOKE ALL ON FUNCTION … FROM PUBLIC` (then false); `GRANT EXECUTE … TO m_caller` restores it for that role only.
- **Direct writes:** `INSERT` by a role with only SELECT → `InsufficientPrivilege: permission denied for table t`.
- **Column grants:** `GRANT UPDATE (b)` shows in `information_schema.column_privileges` (`m_caller, b, UPDATE`);
  `has_table_privilege(…, 'UPDATE')` = false while `has_any_column_privilege(…, 'UPDATE')` = true (an R124 enumerator
  must read column privileges, not only `table_privileges`).
- **pg_policies text** is normalized: `qual` = `(tenant_id = (current_setting('app.tenant_id'::text, true))::uuid)`,
  `roles` = `{m_caller,m_definer}`, `cmd` = `ALL`; `relrowsecurity` and `relforcerowsecurity` both true. R106's text
  comparison must compare against this normalized form.
- **`app.current_time()` naming:** `CREATE FUNCTION m.current_time()` (reserved word, schema-qualified) succeeds and
  `m.current_time()` calls work; an unqualified `current_time()` is a syntax error. With no `test_clock` table it
  returns `clock_timestamp()` (`to_regclass` NULL); with `test_clock(clock_offset interval)` = 2 h the difference was
  `01:59:00` (truncated to minutes); setting a GUC (`app.clock_offset = '99 days'`) changed nothing.
- **Advisory lock:** `pg_advisory_xact_lock(bigint)` and `pg_advisory_xact_lock(integer,integer)`;
  `hashtextextended(text, bigint)` returns `bigint`.
- **Role attributes:** `ALTER ROLE … BYPASSRLS` requires superuser (granted as `ops`). Not measured: whether a
  non-superuser `migrator` can `ALTER FUNCTION … OWNER TO app_definer` (PostgreSQL requires membership in the new
  owner role).

---

## 5. Open questions the planner must rule on

Each: the question, options, citations.

1. **Which definer functions T09 delivers vs defers.** T09 says "every AM-20.3 definer function" (23, SA:450-472) and
   names three (`create_run`, `transition_run`, `revoke_handles`) plus `app.current_time()`. Callers exist today for
   `create_run`, `transition_run`, `append_event`, `freeze_proposal`, `record_decision`, `resolve_invocation`,
   `grant_execution`, `mark_sent`, `record_outcome`, `mark_unknown` (§3.4); the rest first get callers in T11
   (`sync_memberships`), T13 (`reclaim_leases`, `revoke_handles`), T14 (`append_event` seq), T15/T16/T17 (`asset_scope`,
   `search_procedures_scoped` — need `documents/chunks/embeddings`, absent), T21 (`create_revision`,
   `create_manual_proposal`, `expire_proposal`, `request_cancel`), T22 (`request_abort`, `lookup_action`,
   `escalate_run`, `resolve_escalation`). Options: (a) all 23 now, several against tables that do not exist yet
   (`run_lease`, `operator_resolutions`, `chunks`, `model_permit`) and with gates (asset guard, freshness, lease fence)
   whose inputs later tasks add; (b) the ten with callers plus `revoke_handles`, `app.current_time()` and the
   creation/grant/RLS skeleton, each later function with its owning task; (c) all signatures and grants now, bodies
   that raise `not_implemented` until the owner task.
2. **Which tables and columns T09 adds.** RLS needs `tenant_id` on `run_state_history`, `jobs`, `drafts`, `decisions`,
   `execution_grant`, `action_attempt`, `action_attempt_state` (absent, §3.1); `runs` lacks `slot_held`,
   `next_event_seq`, `checkpoint_id`, `budget_used`, `cancel_requested_at`; `invocation_context.handle` → `handle_sha256`;
   `decisions.idempotency_key`; sweeper jobs need `run_id` NULL (SA:504); R009 needs composite `(tenant_id, …)` FKs
   (`proposals.run_id`, `runs.message_id` are single-column). Options: T09 adds every AM-20.2 table (incl. `outbox`,
   `feedback`, `idempotency_request`, `operator_resolutions`, corpus tables, `model_permit`, schema `checkpoints`) vs
   only those its instructions name (`run_directory`, `run_lease`, `sessions`) plus missing columns, leaving the rest to
   their owners (ruling 7). R122 ("migrator ran setup()") cannot be met without `langgraph-checkpoint-postgres`, which
   is not locked (§4.1): defer R122 to T20, or add the dependency in T09.
3. **Runtime roles in T09 or later.** SA:395-404 and BS:246 want one login per service; the debt list says "single
   owner DB role … → T09" and "the runtime connects as … `ops` … → T09". Options: (a) T09 switches all five processes to
   `api`/`worker`/`mcp_read`/`mcp_exec`/`incident` (and adds `sweeper`, `operator`, `migrator`, `test_harness` logins
   unused at runtime); (b) T09 creates roles and grants and proves them with role tests, services switch in a later
   task. Either way: password secret files per login role (pattern `postgres_incident_password`: add to
   `SECRET_NAMES` **and** compose top-level `secrets:` with `file: ${OPS_SECRETS_DIR}/<name>`, test_bootstrap_dev.py:15-19);
   created/re-keyed by `skeleton.py` like `ensure_incident_role`; `ops_core.settings` gains one `Postgres` per role
   (settings.py:96 is hard-wired to `ops`/`postgres_password`). Also: is `migrator` the Compose superuser `ops` or a
   separate role (who then owns `app`, currently owned by `ops`; BYPASSRLS needs a superuser to grant)?
   `REVOKE CONNECT ON DATABASE ops FROM PUBLIC` (measured PUBLIC default) closes "incident can CONNECT to ops".
4. **The membership lookup under RLS.** The API resolves `(issuer, subject)` → tenant **before** it knows the tenant
   (`app.py:115`, store.py:145); AM-20.5 puts `tenant_isolation` on `memberships` (no policy for `api` without a
   tenant). Options: a definer function (not in the AM-20.3 list) for identity resolution; a non-RLS identity view;
   setting the tenant from the token (Keycloak tokens carry no tenant claim today, §3.8); or `sessions` (T11, no RLS)
   storing the active tenant (BS:229). The spec text does not cover this case (SA:510, SA:520).
5. **`persistence.py` as thin caller.** Rulings 13 and the TODO at persistence.py:101 promise "callers keep this
   signature"; but `transition(…, performer=…)` is one entry point while AM-20.3 splits transitions across ten
   functions with different inputs (`freeze_proposal(run_id, draft_id, payload)`, `record_decision(proposal_id, …)`,
   `grant_execution(raw_handle, proposal_id)`), and several current callers bundle transition + event + insert in Python
   (store.py decide, handlers.py freeze, execution.py grant). Options: keep `transition()` only for `transition_run`
   (worker) and add one Python wrapper per definer function with its spec signature; or keep the old signatures and
   dispatch by `performer`. Also: events `run.accepted`, `run.failed`, `run.insufficient_evidence`, `proposal.ready`,
   `approval.recorded`, `run.rejected` move inside the functions (SA:452 refuses them from `append_event`).
6. **mcp-write's UNKNOWN path.** T08's mcp-write calls `mark_unknown` after a failed POST (execution.py:290-292), but
   AM-20.3 grants `mark_unknown(run_id, fence)` to `worker` only (SA:467) and T47 excludes it from `mcp_exec`;
   `record_outcome` has no UNKNOWN transition (SA:464, execution.py:224). Options: mcp-write returns `UNKNOWN` and
   records nothing (the run stays EXECUTING with attempt SENT until the worker or T22 acts); grant `mark_unknown` to
   `mcp_exec` (spec change); or a new function. Same class of question: worker's `requeue_job` writes
   `jobs.available_at`, outside the worker's column list (SA:419).
7. **Where tenant context is set for reads.** `Session.read()` is a single autocommit statement, where
   `set_config(…, true)` lasts one statement (§4.4); api's run/proposal reads use it. And the AM-20.5 policy casts
   `''` to uuid and raises (§4.4) on reused connections and inside every definer function before `set_config`. Options:
   wrap every tenant read in a unit that first calls `set_config`; use the policy text verbatim (errors fail closed but
   surface as 503s through `app.py:124`) or propose an erratum to `NULLIF(…, '')::uuid` (matches SA:446; R106 compares
   the text, §4.4 normalized form).
8. **Live tests under RLS and the grants (ruling 27).** `purge_run`/`purge_tenant` and several live tests write as the
   owner (direct INSERTs into proposals/decisions/tenants, deletes from audit tables). Options: a per-session database
   (e.g. created and dropped by the e2e fixture as the superuser) or schema; a full reset between sessions; test-only
   seeding through `migrator` (BYPASSRLS). The shared dev database also holds 7 runs and 51 destination keys today.
9. **Test clock branch vs `check.py --profile test`.** SA:529 says only `check.py --profile test` applies `testclock`;
   `check.py` has no arguments and no database step (§3.8); `skeleton.py migrate` upgrades `"head"`, which fails with a
   second head (§4.2). Options: `migrations/app` main line labelled (`app@head` for dev/demo, `heads` for test) vs a
   separate script location; a separate test database so dev never carries `app.test_clock` (dev services must refuse
   to start when it exists, SA:528); where `PROFILE`/the profile name comes from (no `test`/`demo` Compose profile
   exists yet; T30 owns them). Each service's start-up assertion `to_regclass('app.test_clock') IS NULL` needs a
   connection that can call `to_regclass` (any role can).
10. **R082's "logged" half.** A refused transition raises inside `transition_run`; a log row in the same transaction
    rolls back with it. Options: `RAISE` with a stable SQLSTATE plus server-log/`log_statement` evidence; a Python-side
    structured log at the caller; an autonomous write (no `dblink` in the image: extensions are `plpgsql`, `vector`).
11. **T10 abort and the existing write path.** No abort route, body or schema exists; `destination.post_incident`
    (destination.py:38-68) and `classify` (98-127) handle POST only, and `create_incident` never aborts. Options: T10
    adds `POST /internal/actions/{id}/abort` (body: `payload_sha256` per SA:266 plus a reason?) and a
    `destination.post_abort` client now, wiring it into mcp-write in T22/T47; or T10 stays destination-side only.
    Also: whether a malformed/disallowed body or a presented-hash mismatch writes a permanent `REJECTED` key (SA:261) or
    keeps today's 422 without a key (app.py:126-131, ruling 9), and what `reason` text tombstones carry (today
    `state.lower()`, keys.py:94; `Tombstone.reason` is free text 1-500 chars, outcomes.py:87).
12. **T10's 403 vs ruling 25's 401.** The verifier already enforces `aud = incident-sim` and `azp = ops-mcp-write`
    (tokens.py:127-142, app.py:155-158) but maps every refusal to 401. T10 DoD 2 and R096 want worker/API tokens (and
    wrong azp) → 403. Options: split `TokenRejected` into "not authenticated" (signature, expiry, issuer) vs
    "authenticated, wrong audience/azp" in `ops_core.tokens` (shared by every server) or only in incident-sim.
13. **Fault factory shape and location.** `core.testing.faults` (SA:564) does not exist; `PROFILE` is read nowhere;
    `core` is a library with no FastAPI dependency (core/pyproject.toml: pydantic, psycopg, sqlalchemy, alembic, pyjwt,
    httpx2). Options: hooks as a separate FastAPI sub-app mounted only by a test factory (404 otherwise, R098) vs
    middleware; which of BS:405's nine fault kinds T10 implements (REJECTED-producing hook is named by keys.py:7) vs T13.
14. **The detective check (T10 review note 3).** It compares `incident.action_key` with `app.execution_grant`, which
    live in different databases with disjoint roles (by design, BS:489). Options: a script or test run with both
    credentials (operator/test only) that reports keys with no matching grant hash; an endpoint in incident-sim that
    accepts a list of `(action_id, payload_sha256)`; scheduled vs on demand; who owns it (T10 vs T22/T32 restore).
15. **Key permanence enforcement.** Role `incident` owns its tables, so it can `DELETE`/`UPDATE` keys; SA:265 says
    never. Options: a separate non-owner runtime role for incident-sim with INSERT/SELECT only (and the migration as
    owner), or a trigger, or code discipline plus a test.
16. **Leftover `spike_*` roles** in the dev cluster (§3.5): R124's per-role enumeration should not trip on them; the
    owner decides whether to drop them (destructive cleanup needs owner authorization, AGENTS.md).

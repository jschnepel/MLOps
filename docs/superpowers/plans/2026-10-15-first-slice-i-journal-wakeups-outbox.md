# First Slice I: Gap-Free Event Journal, Wake-Ups and the Notification Outbox (T14) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove that per-run event sequences are gap-free and commit-ordered under concurrent writers of every role
(R089), enforce the event payload rules inside `_append_event` and in its two mirrors, write notification intent in
the same transaction as the event that needs it and deliver it from the sweeper with a lease, a capped backoff, a dead
letter and a separately committed `notification.failed` (R024), and re-arm a wake-up the worker consumed without
moving its run (T14; R024, R089).

**Architecture:** The journal's mechanism is revision 0003's and stays (ruling 1): `_append_event` locks the run row,
takes `next_event_seq + 1` and inserts in the writer's transaction; Task 3 proves it live with stepped interleavings
of the four writing roles and a stress run with readers on the events route. Revision `0008_journal_outbox` creates
`app.outbox` (RLS `tenant_isolation` only, `app_definer` INSERT, the sweeper's four update cells), gives the sweeper
DELETE on `jobs`, and re-creates `_append_event` with the payload rules (keys closed over the event schema's, a
`status` only from the destination) and the intent insert (`ON CONFLICT DO NOTHING` on `run:type:channel:recipient`);
the schema (through `scripts/build_schemas.py`) and `ops_core.outcomes.event_rules_ok` carry the same rules, checked
on one table of cases. The sweeper gains `ops_sweeper/tenants.py` (one transaction per tenant), `ops_sweeper/outbox.py`
(claim, deliver outside any transaction to `LogSink`, record, dead-letter, announce) and `ops_sweeper/wakeups.py`
(re-arm lost wake-ups, purge finished maintenance rows); `persistence.release_lease` makes the run's deferred jobs due.

**Tech Stack:** as Plan H; no new dependency. psycopg 3.3.6, PostgreSQL 17, Python 3.13 (PEP 695 type parameters in
the sweeper's tenant helpers), jsonschema with rfc3339-validator (already a dev dependency) for the payload-rule table.

**Spec:** `SPEC_AMENDMENTS.md` (OPS-BUILD-1.3.6) over `BUILD_SPEC.md`: AM-12's lock order (SA:186-191), AM-14
(SA:301-325), AM-15 and AM-20.4 (SA:336-348, SA:492-506), AM-20.2 (SA:410-442), AM-20.3 (SA:444-474), AM-20.5
(SA:508-524); BS §8 "Avoid lost wakeups" (BS:340), §15 (BS:508-526). The fact sheet
`docs/superpowers/research/2026-10-15-plan-i-inputs.md` (cited "FS §n" / "FS Qn": T14 verbatim, the binding spec text,
the tree as it is with path:line cites, 29 open questions) and the controller's brief of 29 rulings (cited "brief
ruling n"; reproduced below with what this plan made of each) are the inputs. Earlier artefacts this plan builds on:
revisions 0001-0007 and the `testclock` branch, `ops_core.persistence`, `privileges`, `settings`, `locking`,
`outcomes`, `jobs`, `testing.faults`, `scripts/build_schemas.py`, the worker's release path, the sweeper, the API's
events route, `tests/e2e/` and the Plan C-H unit tests.

## Global Constraints

Carried from Plan H's header (its text applies with "Plan H"/"T13" read as the plan that wrote it); the Plan I
additions below win where the two differ:

- **Debt before code (SA:698).** The Plan I debt list (below) is committed in Task 1 Step 1c before any code changes.
  Nothing not on the list may be shortcut; every line names its owning task.
- **Authority boundaries stay where the spec puts them.** Runtime roles never UPDATE `runs.state` or INSERT into
  audit tables (SA:387); only `_append_event` writes notification intent (no runtime role holds INSERT on `outbox`,
  erratum 60); mcp-read and mcp-write hold no table grant and create no job (SA:437, SA:348; a catalog test in Task
  2); delivery never touches the run (DoD 2); **nothing here sends anything to an external system or a person**
  (BS:730): the only sink is a log line.
- **Secrets** live only as files under `OPS_SECRETS_DIR`. No secret, token, handle, session id or password in an
  environment variable, log line, exception message, assertion operand, evidence file or document; a notification's
  recipient reaches a log only as `outbox.recipient_hash` (ruling 14), and an event-rule refusal never repeats a
  caller's payload key.
- **Clock.** Every lease, backoff, grace and retention comparison in SQL uses `app.current_time()`; Python computes
  a delay (the backoff) but never compares database instants. Column defaults stay `now()`. A test that moves
  `app.test_clock` does so only while no other lease matters and resets it in `finally` (the offset is global).
- **One string per function**, binds and the ISC004 rule exactly as in Plan E (a colon right after a quote or a space
  followed by a word is a SQLAlchemy bind; `tests/plan_e/test_transitions_table.py` scans every revision, 0008
  included); `format('%s:%s:local:%s', …)` builds the dedup key so no literal colon follows a quote.
- **Schemas are generated.** `schemas/` changes only through `scripts/build_schemas.py` and
  `uv run python -m scripts.build_schemas`; the regenerated files are staged (`git add schemas`) before any gate,
  because Plan A's verify_handoff tests copy the tree through `git ls-files`.
- **Live tests never touch the dev databases**, run against `ops_test`/`incident_test` under `PROFILE=test` through
  the existing `migrated`, `app_conn` and `role_conn` fixtures; a live test that needs the decision and grant
  functions on a tenant of its own copies the seeded tenant's memberships into it (`tests.e2e.test_outbox_live.
  own_tenant`) and deletes them with `purge_tenant`.
- **Tests:** unit tests in `tests/plan_i/` (DB-free; added to `testpaths` in Task 1), live tests in `tests/e2e/`
  gated by `OPS_LIVE=1`; existing tests are updated in the task that changes the interface they pin, never deleted
  (Task 4 and Task 5 edit three Plan H tests: the BS:405 kind set, the sweeper's tick order, the release's unit). No
  xfail or skip except the live gate (BS:597). No new test needs `slow_live`: the longest, the R089 stress run, is
  about 12 s.
- **Comments** per `docs/CODE_COMMENTS.md`; ≤120 characters per line (Plan H's counting command); no `type: ignore`;
  ruff + mypy strict clean; UTF-8 without BOM, LF; no new broad `except Exception` (a sink error other than
  `SinkFailed` propagates to the tick's existing catch-all, and the claimed row comes back when its lease ends).
- **Gates:** `uv run ruff format <files> && uv run ruff check --fix <files>` (then
  `uv run ruff check --select ISC004 --fix --unsafe-fixes migrations/app/versions/0008_journal_outbox.py` after
  writing the revision), `PYTHONUTF8=1 uv run python scripts/check.py` GREEN after every task,
  `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts` exit 0, and the live suite
  `PYTHONUTF8=1 uv run python scripts/check.py --profile test` after every task that changes a migration, a service or
  a live test (Tasks 2-6). It needs the dev stack up and `uv run python scripts/skeleton.py status` showing every
  process down. After a live run: `git checkout -- reports/bootstrap reports/skeleton reports/auth reports/admission
  reports/leases` (all five are rewritten by live runs; Task 6 commits the ones it names; `reports/events` and
  `reports/outbox` are new and stay until Task 6). mypy's incremental cache can report spurious errors after many
  edits; rerun with `--no-incremental` before treating one as real.
- **Counting characters:** Plan H's command (`uv run python - <files>` printing every line over 120 characters).
- **Toolchain and locks:** everything through the locked environment from the repository root
  (`uv run python -m pytest …`, never a bare `pytest`); no `uv add`, no `uv lock`.
- **Never migrate the dev databases.** Nobody runs `scripts/skeleton.py migrate` or `up` against `ops`/`incident` in
  this plan; the live suite migrates its own test databases every session. Migrating the dev database to 0008 is an
  owner input recorded in Task 6; until then the sweeper (which now needs `app.outbox`), the worker, the API and
  mcp-write refuse to start on it, by design.
- **Commits:** one logical group per step; messages free of any attribution trailer (owner instruction); never push;
  never `docker compose down -v`; never change system settings; never drop a role, database, persona or Keycloak
  object (the test databases excepted).
- **No interim red across tasks.** Every task ends with both gates GREEN at the stated counts. The order is chosen
  for that: the payload rules land in the schema and in Python (Task 1) before the SQL enforces them (Task 2), and
  today's writers' keys (`question_id`, `message_id`) are in the key set from the start.
- **Line numbers** in "Modify" lines are those of the file as the previous task left it (the current tree for a file
  no earlier Plan I task touched). Every replacement quotes the exact current text ("Edit n (`path`, …), replace:"
  then "with:"); a step that creates a file gives the whole file.
- **Counts.** Today (`c97d63c`) the dev gate is `939 passed, 134 skipped` and the live gate `1052 passed, 21 skipped`
  (113 live-gated tests). Task 1 Step 1a records both before any change; if either differs, every expected count below
  shifts by the same difference and the report says so. Every dev count below was measured by applying this plan to a
  scratch copy of `c97d63c`; every live count is arithmetic (the dev count plus the live-gated tests, which are the
  dev run's skips minus the 21 that skip in both), because a dry run cannot run live steps (the permission policy
  refuses copying `.env` into a scratch tree). Each live step says so.

## Review Focus

1. **A delivery that outlives its lease** (a slow sink, or a sweeper paused between its claim and its result) is
   claimed again by the next tick; the first delivery's late result must not overwrite the newer claim's. Pinned in
   Task 4: every result statement carries `AND attempts = %s` for the attempt it belongs to
   (`test_a_delivery_runs_between_its_claim_and_its_result_unit`), and a crashed delivery is claimed again only after
   its lease (`test_a_crashed_delivery_is_claimed_again_when_its_lease_runs_out`, live).
2. **A sweeper that dies between a dead letter's result and its `notification.failed`**: the next tick must announce
   it exactly once, and two passes must not announce it twice. Pinned in Task 4 (the R024 live test runs `deliver`,
   finds no event, then `notify_dead_letters` twice; `test_a_dead_letter_already_notified_gets_no_second_event`).
3. **mcp-write replaying `record_outcome`** after a lost response (its normal recovery): the replay must add no second
   intent and no event. Pinned in Task 4 (the R024 live test replays it and re-appends the outcome event inside a
   rolled-back transaction) and Task 2 (`test_the_intent_commits_with_its_event_once_per_run_and_type`).
4. **A run that moves between the sweep's unlocked read and its re-arm** (the worker finally handled the job): the
   re-arm must not reopen a job for a run that no longer waits. Pinned in Task 5: the re-arm's UPDATE re-checks the
   run's state and the job's `done_at` (`test_a_lost_wakeup_is_reopened_in_a_unit_of_its_own_under_the_cap`,
   `test_a_job_another_hand_reopened_or_moved_counts_as_not_rearmed`).
5. **Today's real writers under the closed key set**: the API's clarification reply (`question_id`, `message_id`),
   the worker's tool events, the model summary and every definer's event must keep appending. Pinned in Task 1 (the
   case table's "clarification reply", "tool event", "model summary" and "confirmed" cases in the schema and in
   Python) and Task 2 (the same table in SQL); the existing live tests of the reply, the worker and the write path run
   in Task 2's live gate.

## Rulings (the brief's 29, as this plan implements them)

The controller's brief decided these; executors do not re-litigate them. Each line says where the plan implements the
ruling and, where the plan had to refine one against the code, says how (all refinements are repeated under
"Rulings needing controller attention").

1. **Gap-free mechanism** — unchanged; `_append_event`'s counter, lock and insert are revision 0003's text, copied
   into 0008's body untouched (Task 2); Task 3 proves them.
2. **Which writers** — `api` (`append_event`), `worker` (`append_event`, `transition_run`), `mcp_exec` (`mark_sent`,
   and `grant_execution`/`mark_sent`/`record_outcome` in the stress run, through staged handles) and `sweeper`
   (`append_event`); a stepped interleaving and a 10 s stress run (no `slow_live`: under 15 s) (Task 3). Refined (g).
3. **Observing commit order** — (a) stepped: A holds n, B waits on A (`pg_blocking_pids`), the events route shows
   neither n nor n + 1, then n after A commits, then n + 1; (b) rollback: A takes n and rolls back, B gets n; (c)
   stress: four roles, three runs, about half of the transactions rolled back, a cursor reader on the route and a
   counting reader, then every run exactly `1..next_event_seq` (Task 3).
4. **Payload rules in the function** — `_append_event` refuses OC006 a non-object payload (as before), a key outside
   the schema's set and a `status` on any type but the destination's four; the schema gains `question_id`,
   `message_id`, `outbox_id`; `event_rules_ok` mirrors the SQL; `tests/plan_i/event_cases.py` is the one table the
   schema, Python (Task 1) and SQL (Task 2) are checked on; erratum 65. Refined (a).
5. **`outcomes.Event` TODO** — reworded to `TODO(T26)` (Task 1); debt line.
6. **What a wake-up is** — the job committed with its event plus the sweep; no LISTEN/NOTIFY; the 0.5 s per-tenant
   poll stays; `claim_next`'s TODO becomes erratum 64's sentence (Task 5).
7. **What the sweep compares** — QUEUED with every `investigate` job done, APPROVED with every `execute` job done, the
   newest job done longer ago than `OPS_WAKEUP_GRACE_SECONDS` (60) (Task 5); AWAITING_INPUT, OUTCOME_UNKNOWN,
   ESCALATED and R023 are debt lines.
8. **Re-enqueue = re-arm** — the newest done job of the type is reopened (`done_at`, `claimed_by`, `claimed_at` →
   NULL) under `sweeper_all`, below `OPS_WAKEUP_MAX_ATTEMPTS` (10); past the cap a log line per tick per run;
   erratum 62 (Task 5). Refined (e).
9. **Durable ack** — unchanged; debt lines to T20 and T22.
10. **Deferred jobs on release** — `persistence.pull_forward` in `release_lease`'s unit after the finish or re-queue;
    `abandon` does not; unit and live tests (Task 5). Refined (f).
11. **Per-tenant polling** — stays (ruling 6).
12. **Outbox shape** — exactly the brief's columns, CHECKs, composite key and `tenant_isolation` (no `sweeper_all`),
    plus an `outbox_pending` partial index for the claim (Task 2); erratum 60. Refined (b).
13. **Who inserts, which events** — inside `_append_event`, after the event: `action.confirmed`, `action.failed`,
    `run.escalated`, `run.abandoned_unverified` (the type exists); recipient the requester, channel `local`, key
    `run_id:type:channel:recipient`, target-less `ON CONFLICT DO NOTHING`; `notification.failed` never (Task 2);
    erratum 66.
14. **Delivery without an external channel** — the `Sink` protocol, `LogSink` (one line, a hash of the recipient, no
    payload), `FaultKind.OUTBOX_SINK_FAIL` consumed by the sink, armed through `LogSink(faults=…)` (Task 4).
15. **Delivery loop** — the sweeper's tick, per tenant: the claim unit with the brief's statement, delivery outside any
    transaction, one result unit per row; `OPS_OUTBOX_LEASE_SECONDS` 30, `OPS_OUTBOX_BATCH` 10 (Tasks 1, 4); erratum
    67. Refined (c).
16. **Retry, jitter, dead letter** — `min(cap, base × 2^(attempts−1))` plus up to 25 % jitter, base 2, cap 300, the
    fifth failure dead-letters; visibility through `notification.failed` and a log line (Tasks 1, 4).
17. **`notification.failed`** — once per dead letter in a separate transaction after the result unit, payload
    `code`, `message`, `outbox_id` (added to the schema), and the re-check every tick (Task 4); erratum 68. Refined
    (d).
18. **Tenant iteration** — `ops_sweeper.tenants.for_each_tenant(conn, work, *, tenants=None)` and `in_tenant` (Task 4);
    erratum 69.
19. **Maintenance job rows** — `main.record(deps, job_type)` (the old `record_sync` generalised) after each piece of
    work (Tasks 4, 5); erratum 70.
20. **Purge** — the sweeper's `del` on `jobs` (Task 2), `wakeups.purge_maintenance` for `run_id IS NULL AND done_at`
    older than `OPS_MAINTENANCE_RETENTION_HOURS` (24) (Task 5); erratum 61.
21. **Retention** — nothing deleted; debt line → T32.
22. **Lock order** — seven new `OBSERVED_UNITS` and the release's comment (Task 1); `outbox` leaves
    `NOT_YET_CREATED` (Task 2); erratum 71.
23. **Events route** — untouched; it is Task 3's reader.
24. **Sequence width** — `integer` stays.
25. **Sweeper's own events** — `notification.failed` only; `sweeper/README.md`'s "Never" line says so (Task 6).
26. **SA:471 / erratum 49** — `wakeups.sweep` is a separate routine with direct grants (Task 5); erratum 63.
27. **Review note 1** — `test_no_function_an_mcp_server_may_call_inserts_a_job` scans every function `mcp_read` or
    `mcp_exec` may execute and, transitively, every `app.` function their bodies call (it asserts that `_authority`,
    `_resolve_handle`, `_transition`, `_append_event`, `_latest_attempt` and `_grant_row` are among them), and
    asserts both roles hold no table grant (Task 2).
28. **Testing R024** — the brief's scenario, in `tests/e2e/test_outbox_live.py`, evidence
    `reports/outbox/t14-outbox.txt`; R089's in `reports/events/t14-events.txt` (Tasks 3, 4). Refined (h).
29. **Migration** — one revision, `0008_journal_outbox`, downgrade to 0007 by re-running 0003's body and 0002's `jobs`
    cells loaded from their files (the 0007 pattern), proved live by a round trip (Task 2); the owner input "migrate
    dev to 0008" (Task 6).

### Rulings needing controller attention

None of the 29 is impossible against the code. These refinements keep each ruling's intent and are flagged so the
controller can overrule them before execution:

- **(a) Ruling 4: the schema did not forbid what review note 2 forbids.** The ruling says the SQL mirrors "exactly
  what the schema allows" for `status`. Today's schema allows `status` on every type whose source is not
  `model_summary` (FS §3.5), so mirroring it would still accept `tool.completed` with `{"status": "SUCCEEDED"}` from the
  worker, which review note 2 forbids. The plan adds schema rule 9 (a `status` only on the four destination-evidence
  types, which only `record_outcome` emits) and mirrors that, with a negative example and the case table. Smallest
  alternative: refuse `status` only on `tool.*` in all three layers.
- **(b) Ruling 12 and SA:427's `ins` for `api` and `worker`.** The brief leaves the outbox's grant cells to the plan;
  SA:427 gives `api` and `worker` INSERT. Ruling 13 writes all intent inside `_append_event`, so those cells would be
  unused authority to forge a notification for any event of the tenant. The plan withholds them (erratum 60) and a
  live test shows both refused. Smallest alternative: add `"api": _INS, "worker": _INS` to the matrix row and
  `GRANTS_0008`.
- **(c) Ruling 15: the result names its attempt.** Each result UPDATE carries `AND attempts = %s AND delivered_at IS
  NULL`, so a delivery that outlived its lease and was claimed again cannot overwrite the newer claim's result; the
  `Result.recorded` flag says whether it landed (Review Focus 1).
- **(d) Ruling 17: one path for the first announcement and the re-check.** The tick runs `deliver` (claims and result
  units only) and then `notify_dead_letters`, which finds every dead letter lacking its event and appends each in a
  unit of its own after re-checking inside it. A fresh dead letter is thus announced in the same tick, after its
  result unit, by the same code that closes the crash window; the R024 test's "crash" is simply `deliver` without the
  `notify_dead_letters` that follows it.
- **(e) Ruling 8: the re-arm re-checks.** The scan reads unlocked (as ruled); the re-arm's own UPDATE repeats `done_at
  IS NOT NULL`, the cap and the run's state, so a run the worker moved meanwhile is not re-armed.
- **(f) Ruling 10: SKIP LOCKED.** The pull-forward picks its rows `FOR UPDATE SKIP LOCKED`: a row another worker's
  claim holds is about to be deferred by that claim anyway (its NOWAIT meets the release's lease lock), and not
  waiting keeps the release's new statement from adding a wait to the lock order.
- **(g) Ruling 2: who writes what in the stress run.** No MCP definer appends repeatedly (a grant, SENT and an outcome
  each happen once per run), and the worker's `transition_run` moves a run through pre-grant states only, so in the
  stress run the worker writes through `append_event` and each `mcp_exec` connection drives its runs' grant, SENT and
  outcome, each first attempt rolled back after the definer appended; `transition_run` is the worker's writer in a
  stepped test, `mark_sent` mcp-write's in the other.
- **(h) Ruling 28: isolation and timing of the R024 test.** It runs on a tenant of its own (the seeded tenant's
  memberships copied, so the real decision and grant accept it) and delivers only that tenant, so another test's
  leftover row can neither consume an armed fault nor be counted; and it uses an `OutboxSettings` with a 60 s first
  backoff, so a `retrying` row is still "not due" while the test asserts it (2 s could pass), while every backoff stays
  under the 400 s clock steps. The defaults themselves are pinned by the settings test.

## Declared debt and errata

### Debt list (committed in Task 1 Step 1c, before coding)

Inserted into `SESSION_STATE.md` as a new section `## Plan I debt list (T14; committed before coding) [R6-B7]`
immediately after the `## Plan H debt list …` section (before `## Environment (observed)`); the exact text is Task 1
Step 1c's Edit 1.

### Errata proposed to the owner (numbered on from Plan H's 59)

The spec text stays authoritative until the owner decides; each line names the text it amends. The full wording is
Task 6 Step 3's "Plan I executed" block; in short:

60. **SA:427**: the outbox's columns, `leased_until` as both lease and next-attempt time, no `api`/`worker` cell.
61. **SA:419**: the sweeper's DELETE on `jobs`, for finished maintenance rows past 24 h only.
62. **AM-20.4 and SA:345**: a lost wake-up is re-armed by reopening its job; no sweeper-made `resume_input`/`execute`.
63. **SA:471, extending erratum 49**: `wakeups.sweep`, separate from the reclaim, its predicates, grace and cap.
64. **BS:340 and the polling debts**: a wake-up is a job plus the sweep; polling is the v1 wake mechanism; a release
    makes deferred jobs due.
65. **SA:452 and AM-80's event schema**: the closed payload keys (three added) and `status` only from the destination.
66. **BS:524 (intent)**: the four types, the requester, channel `local`, the dedup key, the target-less conflict.
67. **BS:524 (delivery)**: the tick's claim, lease, sink, result units, backoff and dead letter.
68. **SA:188 and BS:514**: `notification.failed` once, in its own transaction, with the re-check.
69. **SA:520**: the sweeper's tenant iteration.
70. **SA:504**: the `deliver_outbox` and `sweep_wakeups` audit rows.
71. **SA:188, extending erratum 52**: the new units' place in the lock order.

## File structure

- `core/src/ops_core/settings.py` (Task 1): `OutboxSettings`, `check_outbox`, `outbox()`, `WakeupSettings`,
  `wakeups()`.
- `core/src/ops_core/outcomes.py` (Task 1): `PAYLOAD_KEYS`, `STATUS_EVENT_TYPES`, `event_rules_ok`'s two rules,
  `Event`'s TODO.
- `core/src/ops_core/locking.py` (Tasks 1, 2): the seven T14 units; `outbox` out of `NOT_YET_CREATED`.
- `scripts/build_schemas.py` and the regenerated `schemas/` (Task 1): three payload keys, rule 9, two examples.
- `migrations/app/versions/0008_journal_outbox.py` (new, Task 2): the outbox, the cells, the policy, `_append_event`,
  the exact downgrade.
- `core/src/ops_core/privileges.py` (Task 2): the outbox row, the sweeper's DELETE, `RLS_TABLES`.
- `core/src/ops_core/testing/faults.py` (Task 4): `OUTBOX_SINK_FAIL`, `SWEEPER_FAULTS`.
- `sweeper/src/ops_sweeper/tenants.py`, `outbox.py` (new, Task 4), `wakeups.py` (new, Task 5), `main.py` (Tasks 4, 5),
  `leases.py` (Task 5, docstring).
- `core/src/ops_core/persistence.py` (Task 5): `pull_forward`, `release_lease`, `claim_next`'s docstring.
- Tests: `tests/plan_i/` (`event_cases.py`, `test_settings_t14.py`, `test_event_rules.py`, `test_locking_t14.py`,
  `test_migration_0008.py`, `test_outbox.py`, `test_sweeper_tick.py`, `test_wakeups.py`); `tests/e2e/`
  (`test_migration_0008_live.py`, `test_event_journal_live.py`, `test_outbox_live.py`, `test_wakeups_live.py`,
  `conftest.py`'s `PURGE_ORDER`); edits to `tests/plan_e/test_transitions_table.py`, `tests/plan_b/test_evidence.py`,
  `tests/plan_h/test_faults_t13.py`, `test_reclaim.py`, `test_worker_units.py`.
- Documentation (Task 6): `handoff/*`, `SESSION_STATE.md`, `STATUS.md`, `docs/ARCHITECTURE.md`,
  `docs/runbooks/events-and-outbox.md` (new), `docs/PROJECT_HISTORY.md`, `README.md`, `worker/README.md`,
  `sweeper/README.md`.

## Task overview

- **Task 1:** the debt list; the outbox and wake-up settings; the payload rules in `event_rules_ok` and the schema
  (regenerated); the seven lock-order units; `tests/plan_i`. Tests: `test_settings_t14.py` 10, `test_event_rules.py`
  40, `test_locking_t14.py` 2, Plan H's lock-order module +7, Plan C's conformance +3. Dev gate after: 1001 passed,
  134 skipped (no migration, service or live test changed; the live gate is not run).
- **Task 2:** revision 0008, the matrix, `PURGE_ORDER`. Tests: `test_migration_0008.py` 5, the transitions module +1
  (parametrised); live `test_migration_0008_live.py` 5. Dev 1007/139, live 1125/21 (arithmetic).
- **Task 3:** the R089 proof. Tests: live `test_event_journal_live.py` 4. Dev 1007/143, live 1129/21 (arithmetic).
- **Task 4:** the tenant iteration, the delivery loop, `LogSink`, the fault kind, the tick. Tests: `test_outbox.py` 12,
  `test_sweeper_tick.py` 2; live `test_outbox_live.py` 3. Dev 1021/146, live 1146/21 (arithmetic).
- **Task 5:** the wake-up sweep, the pull-forward, the purge, the tick. Tests: `test_wakeups.py` 7,
  `test_sweeper_tick.py` +1; live `test_wakeups_live.py` 5. Dev 1029/151, live 1159/21 (arithmetic).
- **Task 6:** handoff records, acceptance rows, errata 60-71, runbook, history, READMEs, final gates. No tests.

The arithmetic, once: dev passed 939 + 62 (Task 1: 10 + 40 + 2 + 7 + 3) = 1001, + 6 (Task 2: 5 + 1) = 1007, + 0 (Task
3) = 1007, + 14 (Task 4: 12 + 2) = 1021, + 8 (Task 5: 7 + 1) = 1029; dev skipped 134, + 5 = 139, + 4 = 143, + 3 =
146, + 5 = 151. The live gate's passed count is the dev count plus the live-gated tests (the dev skips minus the 21
that skip in both gates: 113 today; 118, 122, 125, 130 after Tasks 2-5), so 1125, 1129, 1146, 1159, always with 21
skipped. The dev numbers were measured on a scratch copy; the live ones are not measured (see "Counts").

---

### Task 1: Debt before code — settings, the lock-order entries, the payload rules in the schema and in Python

**Files:**
- Modify: `SESSION_STATE.md` (new debt section before `## Environment (observed)`), `pyproject.toml:48-51`
  (`testpaths`), `core/src/ops_core/settings.py:362-364` (insert before `class Urls`),
  `core/src/ops_core/outcomes.py:181-184` (after `OUTCOME_EVENT_TYPES`), `:203-214` (`event_rules_ok`'s head),
  `:230-236` (its source checks), `:271-279` (`Event`'s docstring), `core/src/ops_core/locking.py:64` and `:76-78`
  (`OBSERVED_UNITS`), `scripts/build_schemas.py:410-425` (the event payload), `:442-447` (rule 9), `:966-970`
  (`examples()` docstring), `:1663-1670` (two examples), then regenerate `schemas/` with the generator
- Create: `tests/plan_i/__init__.py`, `tests/plan_i/event_cases.py`, `tests/plan_i/test_settings_t14.py`,
  `tests/plan_i/test_event_rules.py`

**Requirements:** T14 review note 2 (payload rules: no `status` from api/worker/sweeper on `tool.completed`); the
settings of rulings 8, 15, 16 and 20; the lock-order entries of ruling 22; rulings 4 and 5.

**Interfaces:**
- Consumes: `ops_core.settings._bounded(name, default, low, high)`, `SettingsError`; `ops_core.outcomes.
  DESTINATION_EVIDENCE`, `EventRuleViolation`; `scripts.build_schemas.UUID`, `when`, `props`, `event_doc`,
  `DESTINATION_TYPES`; `ops_core.locking.follows_order`.
- Produces: `ops_core.settings.OutboxSettings(lease_seconds=30, batch=10, backoff_base_seconds=2,
  backoff_cap_seconds=300, max_attempts=5)`, `check_outbox(chosen) -> None`, `outbox() -> OutboxSettings`,
  `WakeupSettings(grace_seconds=60, max_attempts=10, maintenance_retention_hours=24)`, `wakeups() ->
  WakeupSettings`; `ops_core.outcomes.PAYLOAD_KEYS: frozenset[str]` (13 keys), `STATUS_EVENT_TYPES:
  frozenset[EventType]` (the four destination-evidence types); `event_rules_ok` refusing an unknown key and a
  `status` outside `STATUS_EVENT_TYPES`; `tests.plan_i.event_cases.CASES: tuple[Case, ...]` with
  `Case(name, type, source, payload, ok)` and `event_document(case) -> dict` (Task 2's live test reuses both); seven
  new `OBSERVED_UNITS` entries named exactly as below (Tasks 4 and 5 implement them).

- [ ] **Step 1a: Record both baselines**

Run `PYTHONUTF8=1 uv run python scripts/check.py` → `CHECK: GREEN` with pytest `939 passed, 134 skipped`; with the
dev stack up and `uv run python scripts/skeleton.py status` showing every process down, run
`PYTHONUTF8=1 uv run python scripts/check.py --profile test` → `CHECK: GREEN` with `1052 passed, 21 skipped`, then
`git checkout -- reports/bootstrap reports/skeleton reports/auth reports/admission reports/leases`. Record both
lines in the report (Global Constraints, "Counts"). A gate that is not GREEN stops the plan here, before anything is
committed.

- [ ] **Step 1b: Record the base**

Run `git rev-parse --short HEAD` and write the hash it prints as `BASE=<hash>` in the report and in the SDD ledger
(`.superpowers/sdd/2026-10-15-first-slice-i-journal-wakeups-outbox/progress.md`). Task 6's commit span is
`<base>..<last>`.

- [ ] **Step 1c: Commit the debt list (before any code)**

Edit 1 (`SESSION_STATE.md`, the heading after the Plan H debt list), replace:

```markdown
## Environment (observed)
```

with:

```markdown
## Plan I debt list (T14; committed before coding) [R6-B7]

Allowed shortcuts in T14, each with its owning task:
- the worker still finishes a `resume_input` job it does not handle, and the wake-up sweep does not look at
  AWAITING_INPUT runs (no handler consumes the reply yet) → T20;
- the worker still finishes a `recover` job it does not handle, and OUTCOME_UNKNOWN and ESCALATED runs are not swept
  (the recover cadence of SA:506 included) → T22;
- the wake-up sweep re-arms the `investigate` job of a run that sits in QUEUED with every investigate job done; a run
  that T20's `resume_input` handler moves back to QUEUED would meet the same predicate, so T20 decides whether that is
  its wake-up → T20;
- the decision-to-processing crash test of R023 (inject a crash between decision, event, checkpoint and job
  acknowledgement; the sweeper resumes exactly the accepted event) → T21;
- `outcomes.Event` validates neither `append_event`'s input (the function assigns id, sequence and instant) nor the
  events route's output → T26 (response schemas);
- SSE, `Last-Event-ID` replay and the cursor-expiry reset (R053, BS:518's 200-event page) → T27; the events route
  keeps `after`/`limit ≤ 500` → T26/T27;
- no event and no outbox row is ever deleted (BS:578's 30-day replay, the outbox's delivered and dead-lettered rows)
  → T32;
- the only sink is `LogSink` (one log line per delivery, no egress); recipient mapping from approved identities,
  per-channel redaction and a destination's own deduplication → T39 (Slack, M15);
- a delivery slower than the 30 s outbox lease can be delivered twice (at-least-once, BS:76), and so can a delivery
  whose result unit fails after the sink succeeded → T39 (a real channel's deduplication);
- two sweeper processes could both append `notification.failed` for one dead letter in the same instant (the re-check
  and the append are one transaction, but nothing serialises two sweepers on the outbox row; v1 runs one sweeper)
  → T30;
- operator visibility of a dead letter is the `notification.failed` event plus a log line; a wake-up past its re-arm
  cap is a log line once per tick; dashboards and metrics → T28/T29;
- `_append_event` bounds the payload's keys and `status`, not its size (BS:514 "bounded safe payload") → T45;
- incident-sim's fault route accepts any `FaultKind`, so `outbox_sink_fail` can be armed there and is never consumed
  → T47;
- the dev database stays at revision 0005 until the owner migrates it (0006, 0007 and 0008 pending); until then the
  API, the sweeper, the worker and mcp-write refuse to start on it → owner input.

## Environment (observed)
```

```bash
git add SESSION_STATE.md
git commit -m "docs: declare Plan I's shortcuts before coding (T14 debt list)"
```

- [ ] **Step 2: Put `tests/plan_i` on the test path**

Edit 1 (`pyproject.toml`, `testpaths`), replace:

```toml
testpaths = [
  "tests/plan_a", "tests/plan_b", "tests/plan_c", "tests/plan_d", "tests/plan_e", "tests/plan_f", "tests/plan_g",
  "tests/plan_h", "tests/e2e",
]
```

with:

```toml
testpaths = [
  "tests/plan_a", "tests/plan_b", "tests/plan_c", "tests/plan_d", "tests/plan_e", "tests/plan_f", "tests/plan_g",
  "tests/plan_h", "tests/plan_i", "tests/e2e",
]
```

Create `tests/plan_i/__init__.py`:

```python
"""Plan I (T14): the event journal's payload rules, the outbox and the wake-up sweep, without a database."""
```

- [ ] **Step 3: Write the failing settings test**

Create `tests/plan_i/test_settings_t14.py`:

```python
"""The T14 settings (Plan I rulings 8, 15, 16 and 20): the outbox's lease, batch, backoff and dead-letter attempt,
the wake-up sweep's grace and re-arm cap, and how long finished maintenance rows are kept, each read and bounded
(BS:542 "validated configuration").

Catches: a default that drifts from the ruled value, a variable read without its bounds (a zero lease would re-claim
a row while its delivery is still in flight; a zero grace would re-arm a wake-up the worker is about to consume), a
refusal that prints the value instead of the rule, and a backoff cap below its base (every retry would wait the cap).
"""

import pytest
from ops_core import settings
from ops_core.settings import OutboxSettings, SettingsError, WakeupSettings

NAMES = (
    "OPS_OUTBOX_LEASE_SECONDS",
    "OPS_OUTBOX_BATCH",
    "OPS_OUTBOX_BACKOFF_BASE_SECONDS",
    "OPS_OUTBOX_BACKOFF_CAP_SECONDS",
    "OPS_OUTBOX_MAX_ATTEMPTS",
    "OPS_WAKEUP_GRACE_SECONDS",
    "OPS_WAKEUP_MAX_ATTEMPTS",
    "OPS_MAINTENANCE_RETENTION_HOURS",
)


@pytest.fixture(autouse=True)
def clean(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in NAMES:
        monkeypatch.delenv(name, raising=False)


def test_the_defaults_are_the_ruled_values() -> None:
    assert settings.outbox() == OutboxSettings(
        lease_seconds=30, batch=10, backoff_base_seconds=2, backoff_cap_seconds=300, max_attempts=5
    )
    assert settings.wakeups() == WakeupSettings(grace_seconds=60, max_attempts=10, maintenance_retention_hours=24)
    assert OutboxSettings() == settings.outbox() and WakeupSettings() == settings.wakeups()


@pytest.mark.parametrize(
    ("name", "low", "high", "read"),
    [
        ("OPS_OUTBOX_LEASE_SECONDS", 5, 3600, "outbox"),
        ("OPS_OUTBOX_BATCH", 1, 1000, "outbox"),
        ("OPS_OUTBOX_BACKOFF_BASE_SECONDS", 1, 3600, "outbox"),
        ("OPS_OUTBOX_BACKOFF_CAP_SECONDS", 2, 86400, "outbox"),
        ("OPS_OUTBOX_MAX_ATTEMPTS", 1, 100, "outbox"),
        ("OPS_WAKEUP_GRACE_SECONDS", 10, 86400, "wakeups"),
        ("OPS_WAKEUP_MAX_ATTEMPTS", 1, 1000, "wakeups"),
        ("OPS_MAINTENANCE_RETENTION_HOURS", 1, 8760, "wakeups"),
    ],
)
def test_each_variable_is_read_and_bounded(
    monkeypatch: pytest.MonkeyPatch, name: str, low: int, high: int, read: str
) -> None:
    field = name.removeprefix("OPS_OUTBOX_").removeprefix("OPS_WAKEUP_").removeprefix("OPS_").lower()
    if name == "OPS_OUTBOX_BACKOFF_BASE_SECONDS":
        monkeypatch.setenv("OPS_OUTBOX_BACKOFF_CAP_SECONDS", "86400")  # the cap may not sit below the base
    for value in (low, high):
        monkeypatch.setenv(name, str(value))
        assert getattr(getattr(settings, read)(), field) == value
    for value in (low - 1, high + 1):
        monkeypatch.setenv(name, str(value))
        with pytest.raises(SettingsError) as refused:
            getattr(settings, read)()
        assert str(refused.value) == f"{name} must be between {low} and {high}"  # the bounds, never the value


def test_a_cap_below_the_base_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_OUTBOX_BACKOFF_BASE_SECONDS", "60")
    monkeypatch.setenv("OPS_OUTBOX_BACKOFF_CAP_SECONDS", "30")
    with pytest.raises(SettingsError) as refused:
        settings.outbox()
    assert str(refused.value) == "OPS_OUTBOX_BACKOFF_CAP_SECONDS must be at least OPS_OUTBOX_BACKOFF_BASE_SECONDS"
```

Run: `uv run python -m pytest tests/plan_i/test_settings_t14.py -q`
Expected: `1 error in` (collection stops: `ImportError: cannot import name 'OutboxSettings' from 'ops_core.settings'`).

- [ ] **Step 4: Add the outbox and wake-up settings**

Edit 1 (`core/src/ops_core/settings.py`, before `class Urls`), replace:

```python
@dataclass(frozen=True)
class Urls:
```

with:

```python
@dataclass(frozen=True)
class OutboxSettings:
    """The notification outbox's delivery loop (BS:524, Plan I rulings 15 and 16) as validated configuration (BS:542):
    how long a claimed row is leased, how many rows a tenant's claim takes per tick, the capped exponential backoff
    between failed attempts and the attempt whose failure dead-letters the row."""

    lease_seconds: int = 30  # a delivery still unanswered after this is claimed again (at least once, BS:76)
    batch: int = 10
    backoff_base_seconds: int = 2  # the first retry waits about this long, then twice as long each time
    backoff_cap_seconds: int = 300  # BS:562: the backoff is capped
    max_attempts: int = 5  # the fifth failure is final: the row is dead-lettered


def check_outbox(chosen: OutboxSettings) -> None:
    """Refuse a backoff whose cap sits below its base (every retry would wait the cap, and the base would mean nothing).

    Raises:
        SettingsError: naming the rule, never a value.
    """
    if chosen.backoff_cap_seconds < chosen.backoff_base_seconds:
        raise SettingsError("OPS_OUTBOX_BACKOFF_CAP_SECONDS must be at least OPS_OUTBOX_BACKOFF_BASE_SECONDS")


def outbox() -> OutboxSettings:
    """`OPS_OUTBOX_LEASE_SECONDS`, `OPS_OUTBOX_BATCH`, `OPS_OUTBOX_BACKOFF_BASE_SECONDS`,
    `OPS_OUTBOX_BACKOFF_CAP_SECONDS` and `OPS_OUTBOX_MAX_ATTEMPTS`, each bounded, then checked together."""
    chosen = OutboxSettings(
        lease_seconds=_bounded("OPS_OUTBOX_LEASE_SECONDS", 30, 5, 3600),
        batch=_bounded("OPS_OUTBOX_BATCH", 10, 1, 1000),
        backoff_base_seconds=_bounded("OPS_OUTBOX_BACKOFF_BASE_SECONDS", 2, 1, 3600),
        backoff_cap_seconds=_bounded("OPS_OUTBOX_BACKOFF_CAP_SECONDS", 300, 2, 86400),
        max_attempts=_bounded("OPS_OUTBOX_MAX_ATTEMPTS", 5, 1, 100),
    )
    check_outbox(chosen)
    return chosen


@dataclass(frozen=True)
class WakeupSettings:
    """The wake-up sweep (BS:340, Plan I rulings 7, 8 and 20): how long a consumed wake-up may sit without its run
    moving before it is re-armed, how many claims a job may have had before the sweep stops re-arming it, and how long
    a finished maintenance row is kept."""

    grace_seconds: int = 60  # a job done this long ago whose run still waits in the job's state was lost
    max_attempts: int = 10  # a job claimed this often is not re-armed again; the sweep logs it instead
    maintenance_retention_hours: int = 24  # finished sweeper rows older than this are deleted (run jobs never are)


def wakeups() -> WakeupSettings:
    """`OPS_WAKEUP_GRACE_SECONDS`, `OPS_WAKEUP_MAX_ATTEMPTS` and `OPS_MAINTENANCE_RETENTION_HOURS`, each bounded."""
    return WakeupSettings(
        grace_seconds=_bounded("OPS_WAKEUP_GRACE_SECONDS", 60, 10, 86400),
        max_attempts=_bounded("OPS_WAKEUP_MAX_ATTEMPTS", 10, 1, 1000),
        maintenance_retention_hours=_bounded("OPS_MAINTENANCE_RETENTION_HOURS", 24, 1, 8760),
    )


@dataclass(frozen=True)
class Urls:
```

Run: `uv run python -m pytest tests/plan_i/test_settings_t14.py -q`
Expected: `10 passed`.

- [ ] **Step 5: Write the failing payload-rule tests**

Create `tests/plan_i/event_cases.py`:

```python
"""One table of event cases with the verdict all three layers must give (Plan I ruling 4): the JSON schema
(schemas/event.schema.json), `ops_core.outcomes.event_rules_ok` and, from revision 0008 on, `app._append_event`.

Every payload is well formed for the schema's per-key shapes (uuids, enums, lengths), so a case is decided only by
the authority rules the three layers share: who may assert what, which keys exist, and which types carry a `status`.
tests/plan_i/test_event_rules.py checks the schema and the Python twin against it without a database;
tests/e2e/test_migration_0008_live.py checks the SQL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ACTION = "00000000-0000-4000-8000-000000000007"
PROPOSAL = "00000000-0000-4000-8000-000000000004"
QUESTION = "00000000-0000-4000-8000-000000000005"
MESSAGE = "00000000-0000-4000-8000-00000000000b"
OUTBOX = "00000000-0000-4000-8000-00000000000c"
RECEIPT = {
    "receipt_id": "00000000-0000-4000-8000-000000000008",
    "incident_id": "INC-SYNTHETIC-0001",
    "committed_at": "2026-10-06T12:04:00Z",
}
TOMBSTONE = {
    "action_id": ACTION,
    "state": "REJECTED",
    "payload_sha256": "9d5c1fb0f7ef65456f4ccf76396564e6290ecd530e58d2b32024e64079134cf7",
    "reason": "rejected by the destination",
    "decided_at": "2026-10-06T12:04:00Z",
}


@dataclass(frozen=True)
class Case:
    """One (type, source, payload) and whether every layer accepts it."""

    name: str
    type: str
    source: str
    payload: Any
    ok: bool


CASES = (
    Case("tool event", "tool.started", "application", {"message": "search_procedures"}, True),
    Case("empty payload", "tool.completed", "application", {}, True),
    Case(
        "clarification reply",
        "clarification.received",
        "application",
        {"question_id": QUESTION, "message_id": MESSAGE},
        True,
    ),
    Case(
        "dead letter",
        "notification.failed",
        "application",
        {"code": "notification_dead_letter", "message": "not delivered", "outbox_id": OUTBOX},
        True,
    ),
    Case("model summary", "explanation.ready", "model_summary", {"message": "why", "evidence_refs": ["a:v1:s"]}, True),
    Case(
        "confirmed",
        "action.confirmed",
        "destination",
        {"status": "SUCCEEDED", "action_id": ACTION, "receipt": RECEIPT},
        True,
    ),
    Case(
        "failed with proof",
        "action.failed",
        "destination",
        {"action_id": ACTION, "reason": "rejected", "tombstone": TOMBSTONE},
        True,
    ),
    Case(
        "failed with status",
        "action.failed",
        "destination",
        {"status": "FAILED", "action_id": ACTION, "reason": "expired"},
        True,
    ),
    Case("conflict with status", "action.conflict", "destination", {"action_id": ACTION, "status": "ESCALATED"}, True),
    Case("proposal ready", "proposal.ready", "application", {"proposal_id": PROPOSAL}, True),
    Case("run failed", "run.failed", "application", {"message": "retrieval failed"}, True),
    # T14 review note 2: a status is the destination's assertion; application events never carry one.
    Case(
        "status on tool.completed",
        "tool.completed",
        "application",
        {"message": "search_procedures", "status": "SUCCEEDED"},
        False,
    ),
    Case("status on tool.started", "tool.started", "application", {"status": "RETRIEVING"}, False),
    Case("status on run.failed", "run.failed", "application", {"status": "FAILED"}, False),
    Case(
        "status on action.granted",
        "action.granted",
        "application",
        {"action_id": ACTION, "proposal_id": PROPOSAL, "status": "EXECUTING"},
        False,
    ),
    Case(
        "status from the model", "explanation.ready", "model_summary", {"message": "why", "status": "SUCCEEDED"}, False
    ),
    # The payload is closed: a key the schema does not define is refused everywhere (ruling 4).
    Case("unknown key", "clarification.received", "application", {"question_id": QUESTION, "colour": "red"}, False),
    Case("recipient in a payload", "notification.failed", "application", {"code": "x", "recipient": "someone"}, False),
    Case("payload not an object", "tool.started", "application", ["search_procedures"], False),
)


def event_document(case: Case) -> dict[str, Any]:
    """The whole event the schema validates, around the case's type, source and payload."""
    return {
        "event_id": "00000000-0000-4000-8000-000000000006",
        "tenant_id": "00000000-0000-4000-8000-000000000001",
        "conversation_id": "00000000-0000-4000-8000-000000000002",
        "run_id": "00000000-0000-4000-8000-000000000003",
        "sequence": 2,
        "type": case.type,
        "occurred_at": "2026-10-06T12:04:01Z",
        "source": case.source,
        "payload": case.payload,
    }
```

Create `tests/plan_i/test_event_rules.py`:

```python
"""The payload rules of T14 review note 2 and Plan I ruling 4, in the schema and in the Python twin, on one table of
cases (tests/plan_i/event_cases.py), without a database.

Catches: a `status` accepted on an application event (tool.completed from the worker claiming SUCCEEDED, review note
2), a payload key the schema does not define accepted by code (or the reverse), a key today's real writers use that
the schema forgot (the clarification reply's `question_id`/`message_id`, the dead letter's `outbox_id`), and a schema
or code edit made on one side only.
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from ops_core.outcomes import (
    DESTINATION_EVIDENCE,
    PAYLOAD_KEYS,
    STATUS_EVENT_TYPES,
    EventRuleViolation,
    EventSource,
    EventType,
    event_rules_ok,
)

from tests.plan_i.event_cases import CASES, Case, event_document

SCHEMA = json.loads((Path(__file__).resolve().parents[2] / "schemas" / "event.schema.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_the_schema_gives_the_tabled_verdict(case: Case) -> None:
    errors = list(VALIDATOR.iter_errors(event_document(case)))
    assert (not errors) == case.ok, [e.message for e in errors]


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_the_python_twin_gives_the_tabled_verdict(case: Case) -> None:
    if case.ok:
        event_rules_ok(EventType(case.type), EventSource(case.source), case.payload)
    else:
        with pytest.raises(EventRuleViolation):
            event_rules_ok(EventType(case.type), EventSource(case.source), case.payload)


def test_the_payload_keys_are_the_schemas() -> None:
    assert set(SCHEMA["properties"]["payload"]["properties"]) == PAYLOAD_KEYS
    assert {"question_id", "message_id", "outbox_id"} <= PAYLOAD_KEYS  # today's writers' keys, added by T14
    assert STATUS_EVENT_TYPES == DESTINATION_EVIDENCE  # only record_outcome's four types assert a status


def test_the_refusals_name_the_rule_and_never_the_key() -> None:
    with pytest.raises(EventRuleViolation) as refused:
        event_rules_ok(EventType.TOOL_COMPLETED, EventSource.APPLICATION, {"secret-looking-key": "x"})
    assert "secret-looking-key" not in str(refused.value)
    with pytest.raises(EventRuleViolation, match="status"):
        event_rules_ok(EventType.TOOL_COMPLETED, EventSource.APPLICATION, {"status": "SUCCEEDED"})
```

Run: `uv run python -m pytest tests/plan_i/test_event_rules.py -q`
Expected: `1 error in` (collection stops: `ImportError: cannot import name 'PAYLOAD_KEYS' from 'ops_core.outcomes'`).

- [ ] **Step 6: The rules in the Python twin**

Edit 1 (`core/src/ops_core/outcomes.py`, after `OUTCOME_EVENT_TYPES`), replace:

```python
OUTCOME_EVENT_TYPES: Final = frozenset(
    {EventType.ACTION_CONFIRMED, EventType.ACTION_FAILED, EventType.ACTION_LATE_EVIDENCE}
)
```

with:

```python
OUTCOME_EVENT_TYPES: Final = frozenset(
    {EventType.ACTION_CONFIRMED, EventType.ACTION_FAILED, EventType.ACTION_LATE_EVIDENCE}
)

# The event schema's payload keys (its payload object is closed). T14 added the clarification reply's
# `question_id`/`message_id` and the dead letter's `outbox_id`, the keys today's writers already use (Plan I
# ruling 4, erratum 65); revision 0008's `_append_event` refuses any other key, and so does `event_rules_ok`.
PAYLOAD_KEYS: Final = frozenset(
    {
        "message",
        "status",
        "evidence_refs",
        "proposal_id",
        "action_id",
        "code",
        "reason",
        "outcome",
        "receipt",
        "tombstone",
        "question_id",
        "message_id",
        "outbox_id",
    }
)
# A `status` is the destination's assertion about the run (AM-14), so only the four destination-evidence types carry
# one, and they come only from record_outcome (T14 review note 2: never from api, worker or sweeper).
STATUS_EVENT_TYPES: Final = DESTINATION_EVIDENCE
```

Edit 2 (`core/src/ops_core/outcomes.py`, `event_rules_ok`'s head), replace:

```python
    """Raise EventRuleViolation unless (type, source, payload) obeys AM-14's authority rules.

    Code enforces who may assert what and the evidence each outcome event must carry; the shape of every other payload
    key is the JSON schema's job, so unknown keys are not rejected here (except for the closed model_summary payload).
    Evidence keys are the exception: they are an authority claim, so types that do not vouch for them refuse them,
    and each outcome type refuses the other kind of proof (a receipt on action.failed, a tombstone on
    action.confirmed).
    """
    if not isinstance(payload, Mapping):
        # Callers pass decoded JSON, which can be any value; a list or string payload asserts nothing checkable.
        raise EventRuleViolation("an event payload must be an object")
```

with:

```python
    """Raise EventRuleViolation unless (type, source, payload) obeys AM-14's authority rules.

    Code enforces who may assert what and the evidence each outcome event must carry. The payload is closed over the
    schema's keys (PAYLOAD_KEYS) and a `status` belongs to the destination's four types only (Plan I ruling 4, the
    rules revision 0008's `_append_event` enforces in SQL); the shape of each key's value is the JSON schema's job.
    Evidence keys are an authority claim, so types that do not vouch for them refuse them, and each outcome type
    refuses the other kind of proof (a receipt on action.failed, a tombstone on action.confirmed).
    """
    if not isinstance(payload, Mapping):
        # Callers pass decoded JSON, which can be any value; a list or string payload asserts nothing checkable.
        raise EventRuleViolation("an event payload must be an object")
    if not set(payload) <= PAYLOAD_KEYS:
        # The message never repeats the key: a caller's key is caller text, and this message reaches logs.
        raise EventRuleViolation("the payload carries a key the event schema does not define")
```

Edit 3 (`core/src/ops_core/outcomes.py`, after the destination checks), replace:

```python
    if event_type in DESTINATION_EVIDENCE and source is not EventSource.DESTINATION:
        raise EventRuleViolation(f"{event_type} comes only from record_outcome with source=destination")
```

with:

```python
    if event_type in DESTINATION_EVIDENCE and source is not EventSource.DESTINATION:
        raise EventRuleViolation(f"{event_type} comes only from record_outcome with source=destination")
    if "status" in payload and event_type not in STATUS_EVENT_TYPES:
        raise EventRuleViolation("only the destination's outcome events carry a status")
```

Edit 4 (`core/src/ops_core/outcomes.py`, `Event`'s docstring), replace:

```python
    TODO(T14): append_event and the event stream validate through this model; until then only the tests call it.
```

with:

```python
    It cannot validate `append_event`'s input, whose id, sequence and instant the function assigns; the rules it runs
    are enforced on the way in by `app._append_event` (revision 0008). TODO(T26): the events route and the stream
    validate their output through this model (the response schemas); until then the tests call it.
```

- [ ] **Step 7: The rules in the schema, and the schema regenerated**

Edit 1 (`scripts/build_schemas.py`, the event payload), replace:

```python
            "receipt": RECEIPT,  # replaces 1.0's flat receipt_id/incident_id
            "tombstone": TOMBSTONE,
        },
        [],
    )
    summary_payload = closed(
```

with:

```python
            "receipt": RECEIPT,  # replaces 1.0's flat receipt_id/incident_id
            "tombstone": TOMBSTONE,
            # T14 (Plan I ruling 4, erratum 65): keys today's writers already use. The clarification reply names the
            # question it answers and the reply message (the API's reply unit); a dead letter's notification.failed
            # names its outbox row, which is how the sweeper's re-check finds it.
            "question_id": UUID,
            "message_id": UUID,
            "outbox_id": UUID,
        },
        [],
    )
    summary_payload = closed(
```

Edit 2 (`scripts/build_schemas.py`, the end of the event rules), replace:

```python
                    ),
                },
            ],
        ),
    )


def tool_result() -> Doc:
```

with:

```python
                    ),
                },
                # (9) A status is the destination's assertion about the run (AM-14), so only the four
                # destination-evidence types carry one; an application event (tool.completed from the worker, T14
                # review note 2) never does. Mirrors event_rules_ok and revision 0008's _append_event. Last in the
                # list, so an example that also breaks an earlier rule still fails for that rule first (R104).
                when(
                    {"not": props(type={"enum": DESTINATION_TYPES})},
                    props(payload={"not": {"required": ["status"]}}),
                ),
            ],
        ),
    )


def tool_result() -> Doc:
```

Edit 3 (`scripts/build_schemas.py`, `examples()` docstring), replace:

```python
    The delivered 29, then 10 new valid and 27 invalid (Task 6), then 4 valid and 15 invalid from the final review.
```

with:

```python
    The delivered 29, then 10 new valid and 27 invalid (Task 6), then 4 valid and 15 invalid from the final review,
    then 1 valid and 1 invalid for T14's payload rules (Plan I ruling 4).
```

Edit 4 (`scripts/build_schemas.py`, the last example), replace:

```python
        "rfc3339-validator accepts a trailing newline; the date-time pattern does not.",
        "^\\$\\.occurred_at: '2026-10-06T12:04:01Z\\\\n' does not match",
    )
    return items
```

with:

```python
        "rfc3339-validator accepts a trailing newline; the date-time pattern does not.",
        "^\\$\\.occurred_at: '2026-10-06T12:04:01Z\\\\n' does not match",
    )
    # T14 (Plan I ruling 4): the dead letter's event as the sweeper appends it, and the status review note 2 forbids.
    valid(
        "event-notification-failed-valid",
        "event",
        event_doc(
            "application",
            {
                "code": "notification_dead_letter",
                "message": "The notification could not be delivered.",
                "outbox_id": "00000000-0000-4000-8000-00000000000c",
            },
            EventType.NOTIFICATION_FAILED.value,
        ),
    )
    invalid(
        "event-invalid-status-on-tool-event",
        "event",
        event_doc(
            "application",
            {"message": "search_procedures", "status": "SUCCEEDED"},
            EventType.TOOL_COMPLETED.value,
        ),
        "A status is the destination's assertion; an application tool event never carries one (T14 review note 2).",
        "^\\$\\.payload: .* should not be valid under \\{'required': \\['status'\\]\\}$",
    )
    return items
```

Then regenerate the contract set:

Run: `uv run python -m scripts.build_schemas`
Expected: it prints `schemas/: 25 schema documents (19 contracts, 6 tool inputs); 89 examples (35 valid, 54
invalid); index.json version 1.3.3`. `git status --short schemas` then lists `schemas/event.schema.json` and
`schemas/examples/index.json` as modified and the two new example files as untracked. Stage them now with
`git add schemas`: the verify_handoff tests of Plan A copy the tree through `git ls-files`, so an unstaged new example
reads as missing (`FAIL: Missing example schemas/examples/event-notification-failed-valid.json`) and eleven of them
fail.

Run: `uv run python -m pytest tests/plan_i/test_event_rules.py tests/plan_i/test_settings_t14.py tests/plan_c -q`
Expected: `335 passed, 19 skipped` (the two new modules' 50 and Plan C's 285, which include the conformance test's
two new examples and the mutations of the new valid one).

Run: `uv run python -I scripts/verify_handoff.py --contracts`
Expected: the line `PASS: 26 JSON Schema documents; 35 accepted examples; 54 negative examples failed for their stated
reason; governed files LF-only` and exit 0 (the new negative fails for its stated reason, and `event-invalid-
destination-granted`, which also carries a `status`, still fails for its type first: rule 9 is last in the list).

- [ ] **Step 8: The lock-order entries of the new units**

Edit 1 (`core/src/ops_core/locking.py`, the worker release entry), replace:

```python
    "worker release (persistence.release_lease)": ("run_lease", "invocation_context", "jobs:finish"),
```

with:

```python
    # T14 (Plan I ruling 10): the release also makes the run's other deferred jobs due; that UPDATE picks its rows
    # with SKIP LOCKED, so it never waits, and it sits at the finish position with the release's own job.
    "worker release (persistence.release_lease)": ("run_lease", "invocation_context", "jobs:finish"),
```

Edit 2 (`core/src/ops_core/locking.py`, the sweeper units), replace:

```python
    "sweeper membership sync": ("memberships",),
    "sweeper reclaim (leases.reclaim)": ("jobs:finish",),
    "sweeper sync job record": ("jobs:claim",),
}
```

with:

```python
    "sweeper membership sync": ("memberships",),
    "sweeper reclaim (leases.reclaim)": ("jobs:finish",),
    "sweeper sync job record": ("jobs:claim",),
    # T14 (Plan I ruling 22). Every event append writes its notification intent last: the runs row lock, the event,
    # then the outbox row (revision 0008's _append_event; a fresh row, its unique key serialised by the runs lock).
    "event append with notification intent (_append_event)": ("runs", "events", "outbox"),
    # The delivery loop claims and records in units of their own, and appends notification.failed in a separate
    # transaction, so it never takes runs after outbox (SA:188).
    "sweeper outbox claim (outbox.deliver)": ("outbox",),
    "sweeper outbox result (outbox.deliver)": ("outbox",),
    "sweeper notification.failed (outbox.notify_dead_letters)": ("runs", "events"),
    # The wake-up sweep reads runs and jobs without a lock and re-arms one job per unit; the purge deletes finished
    # maintenance rows, which belong to no run.
    "sweeper wake-up re-arm (wakeups.sweep)": ("jobs:finish",),
    "sweeper maintenance purge (wakeups.purge_maintenance)": ("jobs:finish",),
    "sweeper deliver_outbox and sweep_wakeups job records": ("jobs:claim",),
}
```

Create `tests/plan_i/test_locking_t14.py`:

```python
"""The T14 transactions in the published lock order (Plan I ruling 22): each one named, in the order, and the outbox
always after the events it belongs to and never before runs.

Catches: a T14 unit that disappears from the documented list (the order would then say nothing about it), and a
delivery unit that would take runs after outbox, the deadlock SA:188 rules out by keeping notification.failed in a
transaction of its own.
"""

from ops_core import locking

T14_UNITS = (
    "event append with notification intent (_append_event)",
    "sweeper outbox claim (outbox.deliver)",
    "sweeper outbox result (outbox.deliver)",
    "sweeper notification.failed (outbox.notify_dead_letters)",
    "sweeper wake-up re-arm (wakeups.sweep)",
    "sweeper maintenance purge (wakeups.purge_maintenance)",
    "sweeper deliver_outbox and sweep_wakeups job records",
)


def test_every_t14_unit_is_documented_and_ordered() -> None:
    for unit in T14_UNITS:
        assert locking.follows_order(locking.OBSERVED_UNITS[unit]), unit


def test_no_unit_takes_runs_after_the_outbox() -> None:
    for unit, entries in locking.OBSERVED_UNITS.items():
        if "outbox" in entries and "runs" in entries:
            assert entries.index("runs") < entries.index("outbox"), unit
    assert locking.rank("events") < locking.rank("outbox") < locking.rank("jobs:finish")
```

Run: `uv run python -m pytest tests/plan_i tests/plan_h/test_locking.py -q`
Expected: `89 passed` (the lock-order module's 30, now 37 with the seven new units, and Plan I's 52).

- [ ] **Step 9: Gates and commit**

Format, lint and count characters on `core/src/ops_core/settings.py`, `core/src/ops_core/outcomes.py`,
`core/src/ops_core/locking.py`, `scripts/build_schemas.py` and every file under `tests/plan_i/`.

Run: `PYTHONUTF8=1 uv run python scripts/check.py`
Expected: `CHECK: GREEN`; pytest `1001 passed, 134 skipped` (939 + 52 in `tests/plan_i` + 7 lock-order units + 3
conformance cases for the two new examples).

Run: `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`
Expected: exit 0. (No migration, service or live test changed: the live gate is not run in this task.)

```bash
git add pyproject.toml core/src/ops_core/settings.py core/src/ops_core/outcomes.py core/src/ops_core/locking.py
git add scripts/build_schemas.py schemas tests/plan_i
git commit -m "feat(core): outbox and wake-up settings, the event payload rules, the T14 lock-order entries"
```

---

### Task 2: Revision 0008 — the outbox, the sweeper's DELETE on jobs, `_append_event`'s payload rules and intent

**Files:**
- Create: `migrations/app/versions/0008_journal_outbox.py`, `tests/plan_i/test_migration_0008.py`,
  `tests/e2e/test_migration_0008_live.py`
- Modify: `core/src/ops_core/privileges.py:7-18` (docstring), `:116-121` (`jobs`), `:129` (`events`, the outbox row
  after it), `:148-149` (`RLS_TABLES`), `core/src/ops_core/locking.py:47` and `:55`,
  `tests/plan_e/test_transitions_table.py:92-93` (`REVISIONS`), `tests/e2e/conftest.py:134` (`PURGE_ORDER`)

**Requirements:** R024's transactional, deduplicated intent (the SQL half); T14 review notes 1 and 2; rulings 4, 12,
13, 20, 27 and 29; R006 (an exact downgrade); R124/R106 (the matrix and the policy, through the existing live tests).

**Interfaces:**
- Consumes: `ops_core.privileges.Grant`, `grant_statements`, `rls_statements`, `function_grant_statements`;
  `ops_core.outcomes.PAYLOAD_KEYS`, `DESTINATION_EVIDENCE`, `EventType`; revision 0003's `APPEND_EVENT_HELPER`,
  `HELPER_HEADER`, `EVENT_TYPES`, `EVENT_TYPES_0003`; revision 0002's `GRANTS_0002`; the e2e fixtures `app_conn`,
  `role_conn`, `purge_run`, `purge_tenant`, `new_run`; `tests.plan_i.event_cases.CASES`.
- Produces: the table `app.outbox(outbox_id uuid PK, tenant_id uuid, run_id uuid, event_id uuid → events, channel
  'local', recipient text, dedup_key text UNIQUE, attempts integer DEFAULT 0, leased_until timestamptz DEFAULT
  '-infinity', delivered_at timestamptz, result text IN ('delivered','retrying','dead_letter'), created_at)` with the
  composite key to `runs`, `tenant_isolation` and no `sweeper_all`; `privileges.GRANTS["outbox"] = {"sweeper":
  sel + upd(leased_until, attempts, delivered_at, result), "app_definer": ins}`; the sweeper's `dele` on `jobs`;
  `app._append_event` refusing an unknown key (OC006 `unknown payload key`) and a `status` outside the destination's
  four types (OC006 `status`) and inserting one intent per `run_id:type:local:requester` for `action.confirmed`,
  `action.failed`, `run.escalated` and `run.abandoned_unverified`; in the revision: `PAYLOAD_KEYS_0008`,
  `STATUS_TYPES_0008`, `NOTIFY_TYPES_0008`, `EVENT_TYPES_0008`, `GRANTS_0008`, `JOB_CELLS_0002`, `FUNCTIONS`, `RESTORED`, `DOWNGRADE`.

- [ ] **Step 1: Write the failing revision tests**

Create `tests/plan_i/test_migration_0008.py`:

```python
"""Revision 0008 without a database (Plan I rulings 4, 12, 13, 20, 29): the frozen cells equal the live matrix, the
outbox is created with the shape and policy the delivery loop relies on, `_append_event` carries the payload rules and
the notification intent, and the downgrade puts revision 0007 back.

Catches: an outbox the api or worker may write directly (intent comes from `_append_event` only, erratum 60), an
outbox with the sweeper_all policy (the sweeper must iterate tenants, SA:520), a dedup key or ON CONFLICT target that
an INSERT-only definer cannot use, a payload rule that drifts from `ops_core.outcomes`, a notification type list that
names a type the enum lacks, and a downgrade that keeps the table, the DELETE cell or the new function body.
"""

import importlib.util
from pathlib import Path
from typing import Any

import alembic.op
import pytest
from ops_core import privileges as p
from ops_core.outcomes import DESTINATION_EVIDENCE, PAYLOAD_KEYS, EventType

VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "app" / "versions"
OUTBOX_REVOKE = "REVOKE ALL ON app.outbox FROM api, worker, sweeper, mcp_read, mcp_exec, operator, app_definer"
JOBS_REVOKE = "REVOKE ALL ON app.jobs FROM api, worker, sweeper, mcp_read, mcp_exec, operator, app_definer"


def revision(name: str = "0008_journal_outbox") -> Any:
    """Load a revision by path (the versions directory is not a package)."""
    spec = importlib.util.spec_from_file_location(f"rev_{name}", VERSIONS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def statements(module: Any, fn: str, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """What upgrade() or downgrade() hands to op.execute, in order."""
    seen: list[str] = []
    monkeypatch.setattr(alembic.op, "execute", lambda statement, *a, **k: seen.append(str(statement)))
    getattr(module, fn)()
    return seen


def test_the_frozen_cells_are_the_live_matrix() -> None:
    module = revision()
    assert module.down_revision == "0007_leases_fences"
    assert module.GRANTS_0008 == {table: p.GRANTS[table] for table in module.TABLES}
    assert p.GRANTS["outbox"] == {
        "sweeper": p.Grant(sel=True, upd=("leased_until", "attempts", "delivered_at", "result")),
        p.DEFINER_ROLE: p.Grant(ins=True),  # erratum 60: no api or worker cell; intent comes from _append_event
    }
    assert p.GRANTS["jobs"]["sweeper"].dele  # erratum 61: the purge of finished maintenance rows
    assert "outbox" in p.RLS_TABLES and "outbox" not in p.SWEEPER_ALL  # SA:520: the sweeper iterates tenants
    assert set(module.MAIN_GRANTEES_0008) == set(p.MAIN_GRANTEES)


def test_the_frozen_rule_literals_are_the_live_vocabulary() -> None:
    module = revision()
    assert set(module.PAYLOAD_KEYS_0008) == PAYLOAD_KEYS and len(module.PAYLOAD_KEYS_0008) == len(PAYLOAD_KEYS)
    assert set(module.NOTIFY_TYPES_0008) <= {t.value for t in EventType}
    assert set(module.NOTIFY_TYPES_0008) == {
        "action.confirmed",
        "action.failed",
        "run.escalated",
        "run.abandoned_unverified",
    }
    assert set(module.STATUS_TYPES_0008) == {t.value for t in DESTINATION_EVIDENCE}


def test_upgrade_creates_the_outbox_its_cells_and_its_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = statements(revision(), "upgrade", monkeypatch)
    table = next(s for s in seen if s.startswith("CREATE TABLE app.outbox"))
    for column in (
        "outbox_id uuid PRIMARY KEY",
        "tenant_id uuid NOT NULL",
        "run_id uuid NOT NULL",
        "event_id uuid NOT NULL REFERENCES app.events (event_id)",
        "channel text NOT NULL CHECK (channel = 'local')",
        "recipient text NOT NULL",
        "dedup_key text NOT NULL UNIQUE",
        "attempts integer NOT NULL DEFAULT 0",
        "leased_until timestamptz NOT NULL DEFAULT '-infinity'",
        "delivered_at timestamptz",
        "result text CHECK (result IN ('delivered', 'retrying', 'dead_letter'))",
        "created_at timestamptz NOT NULL DEFAULT now()",
        "FOREIGN KEY (tenant_id, run_id) REFERENCES app.runs (tenant_id, run_id)",
    ):
        assert column in table, column
    assert "ALTER TABLE app.outbox OWNER TO migrator" in seen
    grants = [s for s in seen if s.startswith(("GRANT", "REVOKE")) and "FUNCTION" not in s]
    assert grants == [
        OUTBOX_REVOKE,
        "GRANT SELECT ON app.outbox TO sweeper",
        "GRANT UPDATE (leased_until, attempts, delivered_at, result) ON app.outbox TO sweeper",
        "GRANT INSERT ON app.outbox TO app_definer",
        JOBS_REVOKE,
        "GRANT INSERT ON app.jobs TO api",
        "GRANT INSERT, SELECT ON app.jobs TO worker",
        "GRANT UPDATE (claimed_by, claimed_at, done_at, attempts, available_at) ON app.jobs TO worker",
        "GRANT INSERT, SELECT, DELETE ON app.jobs TO sweeper",
        "GRANT UPDATE (claimed_by, claimed_at, done_at, attempts) ON app.jobs TO sweeper",
        "GRANT INSERT, SELECT ON app.jobs TO app_definer",
    ]
    assert [s for s in seen if "POLICY" in s] == [
        "DROP POLICY IF EXISTS tenant_isolation ON app.outbox",
        (
            "CREATE POLICY tenant_isolation ON app.outbox FOR ALL TO api, worker, sweeper, app_definer"
            f" USING (tenant_id = {p.TENANT_EXPR}) WITH CHECK (tenant_id = {p.TENANT_EXPR})"
        ),
    ]
    assert "ALTER TABLE app.outbox FORCE ROW LEVEL SECURITY" in seen


def test_append_event_carries_the_rules_and_the_intent(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = statements(revision(), "upgrade", monkeypatch)
    (body,) = [s for s in seen if "CREATE OR REPLACE FUNCTION app._append_event" in s]
    assert "DETAIL = 'unknown payload key'" in body and "DETAIL = 'status'" in body
    assert "INSERT INTO outbox (outbox_id, tenant_id, run_id, event_id, channel, recipient, dedup_key)" in body
    assert "ON CONFLICT DO NOTHING;" in body  # no target: app_definer may insert into the outbox but not read it
    assert "format('%s:%s:local:%s', p_run_id, p_type, v_run.requester)" in body
    # The intent follows the event inside the runs lock (runs -> events -> outbox, SA:188).
    assert body.index("FOR UPDATE") < body.index("INSERT INTO events") < body.index("INSERT INTO outbox")
    assert "REVOKE ALL ON FUNCTION app._append_event(uuid, uuid, text, text, jsonb) FROM PUBLIC" in seen
    assert not any("GRANT EXECUTE ON FUNCTION app._append_event" in s for s in seen)  # a helper, granted to nobody


def test_the_downgrade_restores_0007(monkeypatch: pytest.MonkeyPatch) -> None:
    module = revision()
    seen = statements(module, "downgrade", monkeypatch)
    rev0003 = revision("0003_run_path_functions")
    assert seen[0] == rev0003.APPEND_EVENT_HELPER  # the 0003 body, byte for byte, before the table goes
    assert "DROP TABLE app.outbox" in seen
    assert seen.index("DROP TABLE app.outbox") > seen.index(OUTBOX_REVOKE)
    rev0002 = revision("0002_roles_grants_rls")
    tail = p.grant_statements(("jobs",), {"jobs": rev0002.GRANTS_0002["jobs"]}, revokees=module.MAIN_GRANTEES_0008)
    assert seen[-len(tail) :] == tail and not any("DELETE ON app.jobs" in s for s in tail)
    assert not any(s.startswith(("DELETE", "UPDATE")) for s in seen)  # it rewrites no row
```

Edit 1 (`tests/plan_e/test_transitions_table.py`, `REVISIONS`), replace:

```python
    "0007_leases_fences",
    "tc_0001_test_clock",
```

with:

```python
    "0007_leases_fences",
    "0008_journal_outbox",
    "tc_0001_test_clock",
```

Run: `uv run python -m pytest tests/plan_i/test_migration_0008.py tests/plan_e/test_transitions_table.py -q`
Expected: `1 error in` (collection of `test_transitions_table.py` stops at its module-level `assert` on `REVISIONS`:
the file `0008_journal_outbox.py` does not exist yet; `test_migration_0008.py` collects, and its five tests are not
run because of the collection error).

- [ ] **Step 2: Write the revision**

Create `migrations/app/versions/0008_journal_outbox.py`:

```python
"""The event journal's payload rules and the notification outbox (T14, Plan I rulings 4, 12, 13, 20, 29).

Revision ID: 0008_journal_outbox
Revises: 0007_leases_fences

`app.outbox` holds one notification intent per run, event type, channel and recipient (BS:240, BS:524, SA:427 as
erratum 60 reads it): written by `_append_event` in the transaction of the event that needs it, claimed and leased by
the sweeper's delivery loop, its result recorded apart from the run (DoD 2). `leased_until` is both the claim's lease
and the next attempt's time, so the sweeper's four AM-20.2 cells suffice; the payload is the event, by reference. RLS
is `tenant_isolation` only: the sweeper iterates tenants (SA:520). The sweeper gains DELETE on `jobs` for the purge of
finished maintenance rows (erratum 61).

`_append_event` is re-created with two more rules (ruling 4, T14 review note 2, erratum 65): the payload is closed over
the event schema's keys, and only the destination's four types carry a `status`; then, after the event, the
notification intent of the four types a requester must hear about (ruling 13, erratum 66). Everything else in its
body is revision 0003's, the gap-free sequence included (`runs` FOR UPDATE, `next_event_seq + 1`, the insert, all in
the caller's transaction, SA:303). Every cell, caller and body is frozen here; the downgrade restores 0007 exactly by
re-running 0003's own body and 0002's own `jobs` cells, loaded from their files (the 0007 pattern).
"""

import importlib.util
import re
from pathlib import Path
from types import ModuleType

from alembic import op
from ops_core import privileges

revision = "0008_journal_outbox"
down_revision = "0007_leases_fences"
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
HELPER_HEADER = REV0003.HELPER_HEADER
# The event types are 0003's, unchanged; the newest-revision test reads this name.
EVENT_TYPES_0008 = REV0003.EVENT_TYPES_0003
EVENT_TYPES = REV0003.EVENT_TYPES
# The event schema's payload keys (ops_core.outcomes.PAYLOAD_KEYS, frozen here; a unit test compares the two).
PAYLOAD_KEYS_0008 = (
    "message",
    "status",
    "evidence_refs",
    "proposal_id",
    "action_id",
    "code",
    "reason",
    "outcome",
    "receipt",
    "tombstone",
    "question_id",
    "message_id",
    "outbox_id",
)
# The destination's four types, the only ones that carry a status (ops_core.outcomes.STATUS_EVENT_TYPES).
STATUS_TYPES_0008 = ("action.confirmed", "action.failed", "action.conflict", "action.late_evidence")
# The events a requester is notified of (ruling 13): the action's outcome and the run's end without one.
NOTIFY_TYPES_0008 = ("action.confirmed", "action.failed", "run.escalated", "run.abandoned_unverified")


def literal_list(values: tuple[str, ...]) -> str:
    """Words as a SQL literal list, each checked against a safe pattern before it is inlined."""
    if not all(re.fullmatch(r"[a-z_.]+", v) for v in values):
        raise RuntimeError("a value is not safe to inline into SQL")
    return ", ".join(f"'{v}'" for v in values)


PAYLOAD_KEYS = literal_list(PAYLOAD_KEYS_0008)
STATUS_TYPES = literal_list(STATUS_TYPES_0008)
NOTIFY_TYPES = literal_list(NOTIFY_TYPES_0008)

TABLES = ("outbox", "jobs")
MAIN_GRANTEES_0008 = ("api", "worker", "sweeper", "mcp_read", "mcp_exec", "operator", "app_definer")
POLICY_ROLES_0008 = ("api", "worker", "sweeper", "app_definer")
GRANTS_0008: dict[str, dict[str, privileges.Grant]] = {
    "outbox": {
        "sweeper": privileges.Grant(sel=True, upd=("leased_until", "attempts", "delivered_at", "result")),
        "app_definer": privileges.Grant(ins=True),
    },
    "jobs": {
        "api": privileges.Grant(ins=True),
        "worker": privileges.Grant(
            sel=True, ins=True, upd=("claimed_by", "claimed_at", "done_at", "attempts", "available_at")
        ),
        "sweeper": privileges.Grant(
            sel=True, ins=True, upd=("claimed_by", "claimed_at", "done_at", "attempts"), dele=True
        ),
        "app_definer": privileges.Grant(sel=True, ins=True),
    },
}
# What 0002 granted on jobs, for the downgrade (not named GRANTS_*: the newest-revision test folds every GRANTS_*
# attribute into the live matrix check).
JOB_CELLS_0002: dict[str, dict[str, privileges.Grant]] = {"jobs": REV0002.GRANTS_0002["jobs"]}

SCHEMA_CHANGES = (
    (
        "CREATE TABLE app.outbox ("
        " outbox_id uuid PRIMARY KEY,"
        " tenant_id uuid NOT NULL,"
        " run_id uuid NOT NULL,"
        " event_id uuid NOT NULL REFERENCES app.events (event_id),"
        " channel text NOT NULL CHECK (channel = 'local'),"
        " recipient text NOT NULL,"
        " dedup_key text NOT NULL UNIQUE,"
        " attempts integer NOT NULL DEFAULT 0,"
        " leased_until timestamptz NOT NULL DEFAULT '-infinity',"
        " delivered_at timestamptz,"
        " result text CHECK (result IN ('delivered', 'retrying', 'dead_letter')),"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT outbox_tenant_run_fkey FOREIGN KEY (tenant_id, run_id) REFERENCES app.runs (tenant_id, run_id))"
    ),
    "ALTER TABLE app.outbox OWNER TO migrator",
    # The delivery claim's scan: a tenant's undelivered, live rows in creation order.
    (
        "CREATE INDEX outbox_pending ON app.outbox (tenant_id, created_at)"
        " WHERE delivered_at IS NULL AND result IS DISTINCT FROM 'dead_letter'"
    ),
)

APPEND_EVENT_HELPER = f"""
CREATE OR REPLACE FUNCTION app._append_event(p_tenant_id uuid, p_run_id uuid, p_type text, p_source text,
                                             p_payload jsonb)
RETURNS TABLE (event_id uuid, sequence integer, occurred_at timestamptz)
{HELPER_HEADER} AS $fn$
DECLARE
    v_run runs%ROWTYPE;
    v_outcome_types text[] := ARRAY['action.confirmed', 'action.failed', 'action.late_evidence'];
    v_destination_types text[] := ARRAY['action.confirmed', 'action.failed', 'action.conflict',
                                        'action.late_evidence'];
    v_failed_reasons text[] := ARRAY['aborted_no_commit', 'cancelled_before_send', 'rejected', 'expired'];
BEGIN
    -- AM-14 mirrored (ops_core.outcomes.event_rules_ok is the Python twin): who may assert what.
    IF p_payload IS NULL OR jsonb_typeof(p_payload) <> 'object' THEN
        RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'payload must be an object';
    END IF;
    -- The allowlist decides what exists; append_event's reserved-type refusal decides who may emit it.
    IF NOT (p_type = ANY (ARRAY[{EVENT_TYPES}]::text[])) THEN
        RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'unknown type';
    END IF;
    -- T14 (Plan I ruling 4): the payload is closed over the event schema's keys, as the schema is, and a status is
    -- the destination's assertion, so only its four types carry one (review note 2: never api, worker or sweeper).
    IF EXISTS (SELECT 1 FROM jsonb_object_keys(p_payload) k WHERE NOT (k = ANY (ARRAY[{PAYLOAD_KEYS}]::text[]))) THEN
        RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'unknown payload key';
    END IF;
    IF p_payload ? 'status' AND NOT (p_type = ANY (ARRAY[{STATUS_TYPES}]::text[])) THEN
        RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'status';
    END IF;
    IF p_source = 'model_summary' THEN
        IF p_type <> 'explanation.ready' OR NOT (p_payload ? 'message')
           OR jsonb_typeof(p_payload->'message') <> 'string'
           OR length(p_payload->>'message') = 0
           OR EXISTS (SELECT 1 FROM jsonb_object_keys(p_payload) k WHERE k NOT IN ('message', 'evidence_refs'))
           OR (p_payload ? 'evidence_refs' AND (jsonb_typeof(p_payload->'evidence_refs') <> 'array'
               OR EXISTS (SELECT 1 FROM jsonb_array_elements(p_payload->'evidence_refs') e
                          WHERE jsonb_typeof(e) <> 'string' OR length(e #>> '{{}}') = 0))) THEN
            RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'model_summary';
        END IF;
    ELSIF p_source = 'destination' THEN
        IF NOT (p_type = ANY (v_destination_types)) THEN
            RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'destination source';
        END IF;
    ELSIF p_source = 'application' THEN
        IF p_type = ANY (v_destination_types) THEN
            RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006',
                DETAIL = 'destination evidence from application';
        END IF;
    ELSE
        RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'source';
    END IF;
    IF NOT (p_type = ANY (v_outcome_types)) AND (p_payload ?| ARRAY['outcome', 'receipt', 'tombstone']) THEN
        RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'evidence keys';
    END IF;
    IF p_type = 'action.confirmed' AND (p_payload->>'status' IS DISTINCT FROM 'SUCCEEDED' OR p_payload ? 'tombstone'
                                        OR jsonb_typeof(p_payload->'receipt') IS DISTINCT FROM 'object'
                                        OR NOT (p_payload->'receipt' ?& ARRAY['receipt_id', 'incident_id',
                                                                                'committed_at'])
                                        OR EXISTS (SELECT 1 FROM jsonb_each(p_payload->'receipt')
                                                   WHERE jsonb_typeof(value) <> 'string')) THEN
        RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'action.confirmed';
    END IF;
    -- Shape only (keys present): the producer (mcp-write) validates the full Receipt and Tombstone
    -- models before a document reaches record_outcome; this is defence in depth, not the contract.
    IF (p_payload ? 'tombstone') AND (jsonb_typeof(p_payload->'tombstone') <> 'object'
        OR NOT (p_payload->'tombstone' ?& ARRAY['action_id', 'state', 'payload_sha256', 'reason', 'decided_at'])) THEN
        RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'tombstone';
    END IF;
    IF p_type = 'action.late_evidence' AND NOT (
        (p_payload->>'outcome' = 'SUCCEEDED' AND jsonb_typeof(p_payload->'receipt') = 'object'
            AND (p_payload->'receipt' ?& ARRAY['receipt_id', 'incident_id', 'committed_at'])
            AND NOT (p_payload ? 'tombstone'))
        OR (p_payload->>'outcome' = 'FAILED_NO_COMMIT' AND jsonb_typeof(p_payload->'tombstone') = 'object'
            AND NOT (p_payload ? 'receipt'))) THEN
        RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'action.late_evidence';
    END IF;
    IF p_type = 'action.failed' AND (coalesce(p_payload->>'reason', '') <> ALL (v_failed_reasons)
                                     OR p_payload ? 'receipt') THEN
        RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'action.failed';
    END IF;
    -- The runs row lock serialises the counter (SA:303, R089); the tenant is already set, so RLS admits the row.
    SELECT * INTO v_run FROM runs WHERE runs.run_id = p_run_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'run';
    END IF;
    UPDATE runs SET next_event_seq = v_run.next_event_seq + 1 WHERE runs.run_id = p_run_id;
    event_id := gen_random_uuid();
    sequence := v_run.next_event_seq + 1;
    occurred_at := date_trunc('second', app.current_time());
    INSERT INTO events (event_id, tenant_id, conversation_id, run_id, sequence, type, occurred_at, source, payload)
    VALUES (event_id, p_tenant_id, v_run.conversation_id, p_run_id, sequence, p_type, occurred_at, p_source, p_payload);
    -- BS:524 (ruling 13): the notification intent commits with the event that needs it, last in this transaction
    -- (runs -> events -> outbox, SA:188). One intent per run, type, channel and requester: a replayed writer adds
    -- nothing (R024). ON CONFLICT names no target because app_definer may insert into the outbox but not read it.
    IF p_type = ANY (ARRAY[{NOTIFY_TYPES}]::text[]) THEN
        INSERT INTO outbox (outbox_id, tenant_id, run_id, event_id, channel, recipient, dedup_key)
        VALUES (gen_random_uuid(), p_tenant_id, p_run_id, event_id, 'local', v_run.requester::text,
                format('%s:%s:local:%s', p_run_id, p_type, v_run.requester))
        ON CONFLICT DO NOTHING;
    END IF;
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION app._append_event(uuid, uuid, text, text, jsonb) OWNER TO app_definer;
"""

# (name, argument types, callers, body): frozen here (N1); the newest-revision test reads this tuple.
FUNCTIONS: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("_append_event", "uuid, uuid, text, text, jsonb", (), APPEND_EVENT_HELPER),
)
# What downgrade() re-creates first, from the applied revisions' own bodies: (name, args, callers, body).
RESTORED: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("_append_event", "uuid, uuid, text, text, jsonb", (), REV0003.APPEND_EVENT_HELPER),
)
DOWNGRADE = (
    f"REVOKE ALL ON app.outbox FROM {', '.join(MAIN_GRANTEES_0008)}",
    "DROP TABLE app.outbox",  # its policy and index go with it
)


def upgrade() -> None:
    """The table, its frozen cells and policy, the jobs cells, then the function (body first, then its REVOKE)."""
    for statement in SCHEMA_CHANGES:
        op.execute(statement)
    for statement in privileges.grant_statements(TABLES, GRANTS_0008, revokees=MAIN_GRANTEES_0008):
        op.execute(statement)
    for statement in privileges.rls_statements(("outbox",), POLICY_ROLES_0008):
        op.execute(statement)
    for name, args, callers, body in FUNCTIONS:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)


def downgrade() -> None:
    """Back to 0007: 0003's `_append_event` first (so no function names the table), then the outbox goes and the
    jobs cells are 0002's again."""
    for name, args, callers, body in RESTORED:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)
    for statement in DOWNGRADE:
        op.execute(statement)
    for statement in privileges.grant_statements(("jobs",), JOB_CELLS_0002, revokees=MAIN_GRANTEES_0008):
        op.execute(statement)
```

Then `uv run ruff check --select ISC004 --fix --unsafe-fixes migrations/app/versions/0008_journal_outbox.py` (no
change expected: every implicit concatenation is already inside its own parentheses).

Run: `uv run python -m pytest tests/plan_i/test_migration_0008.py tests/plan_e/test_transitions_table.py -q`
Expected: `2 failed, 16 passed`: `test_the_frozen_cells_are_the_live_matrix` fails with `KeyError: 'outbox'` (the
matrix has no outbox row yet) and `test_the_newest_revision_of_every_cell_equals_the_live_matrix` with
`AssertionError: jobs` (the revision's sweeper cell carries DELETE, the matrix's does not; the walk meets `jobs`
first, because revision 0002 put it in the dictionary before 0008 added `outbox`). The other tests pass already: the
revision renders its own frozen cells, so nothing else reads the matrix.

- [ ] **Step 3: The matrix rows**

Edit 1 (`core/src/ops_core/privileges.py`, docstring), replace:

```python
instead of hiding. Rows exist only for tables that exist; the owners of later tables (outbox → T14, feedback → T21,
operator_resolutions → T22, documents/chunks/embeddings → T17) add their rows. Eight departures from the printed
table, each a proposed erratum (Plan E rulings 6, 10, 17, 23; Plan F rulings 2, 3 and 17 with erratum 25; Plan G
ruling 4; Plan H rulings 1 and 12): the worker (not the sweeper) may UPDATE jobs.available_at (re-queue after a
transport failure), app_definer may UPDATE runs.updated_at, app_definer may UPDATE run_lease.fence (the fenced
definers lock the lease row and mark_unknown bumps it, erratum 45), the `transitions` table (the T07 table mirrored
in SQL) is readable by app_definer only, no definer function takes a row lock on proposals, decisions, memberships or
execution_grant (a lock needs UPDATE, which the matrix withholds), the sweeper holds SELECT beside its DELETE on
sessions, login_state, logout_jti and idempotency_request (a DELETE with a WHERE reads the row), login_state and
logout_jti are rows the printed table lacks, and model_permit has no sweeper cell (an expired permit is free by the
same comparison, erratum 50). `test_harness` exists only in the test profile: the main-line revisions grant it nothing;
```

with:

```python
instead of hiding. Rows exist only for tables that exist; the owners of later tables (feedback → T21,
operator_resolutions → T22, documents/chunks/embeddings → T17) add their rows. Ten departures from the printed
table, each a proposed erratum (Plan E rulings 6, 10, 17, 23; Plan F rulings 2, 3 and 17 with erratum 25; Plan G
ruling 4; Plan H rulings 1 and 12; Plan I rulings 12 and 20): the worker (not the sweeper) may UPDATE
jobs.available_at (re-queue after a transport failure), app_definer may UPDATE runs.updated_at, app_definer may
UPDATE run_lease.fence (the fenced definers lock the lease row and mark_unknown bumps it, erratum 45), the
`transitions` table (the T07 table mirrored in SQL) is readable by app_definer only, no definer function takes a row
lock on proposals, decisions, memberships or execution_grant (a lock needs UPDATE, which the matrix withholds), the
sweeper holds SELECT beside its DELETE on sessions, login_state, logout_jti and idempotency_request (a DELETE with a
WHERE reads the row), login_state and logout_jti are rows the printed table lacks, model_permit has no sweeper cell
(an expired permit is free by the same comparison, erratum 50), the outbox has no api or worker cell (only
`_append_event` writes intent, erratum 60), and the sweeper may DELETE from jobs (the purge of finished maintenance
rows, erratum 61). `test_harness` exists only in the test profile: the main-line revisions grant it nothing;
```

Edit 2 (`core/src/ops_core/privileges.py`, the `jobs` row), replace:

```python
        "sweeper": Grant(sel=True, ins=True, upd=_JOB_COLUMNS),
```

with:

```python
        "sweeper": Grant(sel=True, ins=True, upd=_JOB_COLUMNS, dele=True),  # erratum 61: finished maintenance rows
```

Edit 3 (`core/src/ops_core/privileges.py`, after `events`), replace:

```python
    "events": {"api": _S, "worker": _S, "sweeper": _S, DEFINER_ROLE: _SI},
```

with:

```python
    "events": {"api": _S, "worker": _S, "sweeper": _S, DEFINER_ROLE: _SI},
    # T14 (Plan I ruling 12, erratum 60): intent is written by _append_event alone (INSERT, no SELECT: its ON
    # CONFLICT names no target); the sweeper claims, leases and records results under its tenant setting.
    "outbox": {
        "sweeper": Grant(sel=True, upd=("leased_until", "attempts", "delivered_at", "result")),
        DEFINER_ROLE: _INS,
    },
```

Edit 4 (`core/src/ops_core/privileges.py`, `RLS_TABLES`), replace:

```python
    "action_attempt_state",
    "events",
)
SWEEPER_ALL: Final = ("memberships", "jobs")  # SA:520: the only policies besides tenant_isolation
```

with:

```python
    "action_attempt_state",
    "events",
    "outbox",
)
SWEEPER_ALL: Final = ("memberships", "jobs")  # SA:520: the only policies besides tenant_isolation
```

Edit 5 (`core/src/ops_core/locking.py`, the outbox entry), replace:

```python
    "outbox",  # created by T14
```

with:

```python
    "outbox",  # T14: revision 0008
```

Edit 6 (`core/src/ops_core/locking.py`, `NOT_YET_CREATED`), replace:

```python
NOT_YET_CREATED: Final = frozenset({"operator_resolutions", "outbox"})
```

with:

```python
NOT_YET_CREATED: Final = frozenset({"operator_resolutions"})
```

Run:

```bash
uv run python -m pytest tests/plan_i/test_migration_0008.py tests/plan_e/test_transitions_table.py \
  tests/plan_e/test_privileges.py tests/plan_h/test_locking.py tests/plan_i/test_locking_t14.py -q
```

Expected: `63 passed` (the new module's 5, the transitions module's 13 with one more parametrised revision, Plan E's
privileges 6, the lock-order 37, Plan I's lock-order 2).

- [ ] **Step 4: Keep the live fixtures in step with the revision**

Edit 1 (`tests/e2e/conftest.py`, `PURGE_ORDER`), replace:

```python
    "DELETE FROM app.events WHERE run_id = %s",
```

with:

```python
    "DELETE FROM app.outbox WHERE run_id = %s",  # T14: an intent references its event and its run
    "DELETE FROM app.events WHERE run_id = %s",
```

- [ ] **Step 5: The live revision test**

Create `tests/e2e/test_migration_0008_live.py`:

```python
"""Revision 0008 against the per-session test database (OPS_LIVE=1; Plan I rulings 4, 12, 13, 20, 27, 29).

Catches: a downgrade that leaves the outbox, the sweeper's DELETE on jobs or the new `_append_event` body behind (or
an upgrade that does not bring them back); a payload rule the SQL enforces differently from the schema and the
Python twin (the same table of cases, tests/plan_i/event_cases.py); an intent written for an event that needs none,
written twice for one run and type, or written with someone other than the requester; an outbox an api or worker
connection can write, a sweeper can read across tenants or delete from; and a function either MCP server may call
that inserts a job (T14 review note 1: recover jobs are never created by an MCP server).
"""

import re
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from ops_core import persistence, settings
from ops_core.outcomes import EventType
from ops_core.settings import Profile, Role
from psycopg.types.json import Jsonb

from tests.e2e.conftest import purge_run, purge_tenant
from tests.e2e.test_migrations_and_persistence import ALEX, new_run
from tests.plan_i.event_cases import CASES

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
APPEND = "SELECT * FROM app._append_event(%s, %s, %s, %s, %s)"
FAILED = {"action_id": str(uuid4()), "reason": "expired"}
# Any statement that adds a row to app.jobs, whatever the spacing or schema prefix.
INSERTS_A_JOB = re.compile(r"INSERT\s+INTO\s+(app\.)?jobs\b", re.IGNORECASE)
CALLS = re.compile(r"app\.(\w+)\(")


async def snapshot(conn: persistence.Conn) -> dict[str, Any]:
    """What revision 0008 changes, as comparable values: every app function's definition, the jobs and outbox cells,
    the outbox's policies and whether the table exists."""
    cur = await conn.execute(
        "SELECT p.oid::regprocedure::text AS signature, pg_get_functiondef(p.oid) AS body FROM pg_proc p"
        " JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'app' ORDER BY 1"
    )
    functions = {row["signature"]: row["body"] for row in await cur.fetchall()}
    cur = await conn.execute(
        "SELECT grantee, table_name, privilege_type FROM information_schema.role_table_grants"
        " WHERE table_schema = 'app' AND table_name IN ('jobs', 'outbox') ORDER BY 1, 2, 3"
    )
    cells = [(row["grantee"], row["table_name"], row["privilege_type"]) for row in await cur.fetchall()]
    cur = await conn.execute("SELECT policyname FROM pg_policies WHERE schemaname = 'app' AND tablename = 'outbox'")
    policies = sorted(row["policyname"] for row in await cur.fetchall())
    cur = await conn.execute("SELECT to_regclass('app.outbox') IS NOT NULL AS present")
    outbox = bool((await cur.fetchone())["present"])
    return {"functions": functions, "cells": cells, "policies": policies, "outbox": outbox}


async def test_the_round_trip_restores_0007(app_conn: persistence.Conn) -> None:
    from scripts.skeleton import downgrade, migrate

    superuser = settings.superuser_postgres()
    head = await snapshot(app_conn)
    assert head["outbox"] and head["policies"] == ["tenant_isolation"]
    assert ("sweeper", "jobs", "DELETE") in head["cells"]
    try:
        downgrade("app", superuser, "0007_leases_fences")
        before = await snapshot(app_conn)
        assert not before["outbox"] and before["policies"] == []
        assert ("sweeper", "jobs", "DELETE") not in before["cells"]
        body = before["functions"]["app._append_event(uuid,uuid,text,text,jsonb)"]
        assert "INSERT INTO outbox" not in body and "unknown payload key" not in body  # 0003's body again
    finally:
        assert migrate(Profile.TEST) == 0  # every later test needs the head
    assert await snapshot(app_conn) == head  # the upgrade brings back exactly what the downgrade took


async def verdict(conn: persistence.Conn, tenant: UUID, run: UUID, case_type: str, source: str, payload: Any) -> str:
    """'ok', or the SQLSTATE `_append_event` refused with; rolled back either way."""
    try:
        async with conn.transaction(force_rollback=True):
            await conn.execute(APPEND, (tenant, run, case_type, source, Jsonb(payload)))
    except psycopg.Error as exc:
        return str(exc.sqlstate)
    return "ok"


async def test_the_sql_gives_every_tabled_verdict(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    """Ruling 4: the schema, the Python twin (tests/plan_i/test_event_rules.py) and the SQL agree on one table."""
    tenant, _, run = await new_run(app_conn, api=await role_conn(Role.API))
    try:
        wrong = [
            (case.name, got)
            for case in CASES
            if (got := await verdict(app_conn, tenant, run, case.type, case.source, case.payload))
            != ("ok" if case.ok else "OC006")
        ]
        assert wrong == []
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


async def outbox_rows(conn: persistence.Conn, run: UUID) -> list[dict[str, Any]]:
    cur = await conn.execute(
        "SELECT o.event_id, e.type, o.channel, o.recipient, o.dedup_key, o.attempts, o.result, o.delivered_at,"
        " o.leased_until = '-infinity' AS due FROM app.outbox o JOIN app.events e ON e.event_id = o.event_id"
        " WHERE o.run_id = %s ORDER BY o.created_at",
        (run,),
    )
    return [dict(row) for row in await cur.fetchall()]


async def test_the_intent_commits_with_its_event_once_per_run_and_type(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """Rulings 12-13 (BS:524, R024's SQL half): an outcome event writes one intent addressed to the requester in its
    own transaction; a replay adds an event but no second intent; other events and a rollback write none."""
    api = await role_conn(Role.API)
    tenant, _, run = await new_run(app_conn, api=api)
    try:
        async with app_conn.transaction(force_rollback=True):  # the event and its intent leave together
            await app_conn.execute(APPEND, (tenant, run, "action.failed", "destination", Jsonb(FAILED)))
            assert len(await outbox_rows(app_conn, run)) == 1
        assert await outbox_rows(app_conn, run) == []
        cur = await app_conn.execute(APPEND, (tenant, run, "action.failed", "destination", Jsonb(FAILED)))
        first = (await cur.fetchone())["event_id"]
        await app_conn.execute(APPEND, (tenant, run, "action.failed", "destination", Jsonb(FAILED)))  # a replay
        await persistence.append_event(api, run_id=run, type=EventType.TOOL_STARTED, payload={})  # no intent
        await app_conn.execute(
            APPEND, (tenant, run, "notification.failed", "application", Jsonb({"code": "x", "message": "m"}))
        )
        rows = await outbox_rows(app_conn, run)
        assert rows == [
            {
                "event_id": first,
                "type": "action.failed",
                "channel": "local",
                "recipient": ALEX,
                "dedup_key": f"{run}:action.failed:local:{ALEX}",
                "attempts": 0,
                "result": None,
                "delivered_at": None,
                "due": True,
            }
        ]
        cur = await app_conn.execute("SELECT count(*) AS n FROM app.events WHERE run_id = %s", (run,))
        assert (await cur.fetchone())["n"] == 5  # run.accepted, two action.failed, tool.started, notification.failed
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


async def test_the_outbox_is_written_by_the_definer_and_read_per_tenant(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """Erratum 60 and SA:520: no runtime role inserts intent; the sweeper sees a tenant's rows only under that
    tenant's setting, may update its four columns and may not delete."""
    tenant, _, run = await new_run(app_conn, api=await role_conn(Role.API))
    try:
        await app_conn.execute(APPEND, (tenant, run, "action.failed", "destination", Jsonb(FAILED)))
        cur = await app_conn.execute("SELECT event_id FROM app.outbox WHERE run_id = %s", (run,))
        event = (await cur.fetchone())["event_id"]
        insert = (
            "INSERT INTO app.outbox (outbox_id, tenant_id, run_id, event_id, channel, recipient, dedup_key)"
            " VALUES (gen_random_uuid(), %s, %s, %s, 'local', 'r', %s)"
        )
        for role in (Role.API, Role.WORKER, Role.SWEEPER, Role.MCP_EXEC):
            conn = await role_conn(role)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                await conn.execute(insert, (tenant, run, event, f"forged-{uuid4()}"))
        sweeper = await role_conn(Role.SWEEPER)
        cur = await sweeper.execute("SELECT count(*) AS n FROM app.outbox WHERE run_id = %s", (run,))
        assert (await cur.fetchone())["n"] == 0  # no tenant set: tenant_isolation admits nothing, no sweeper_all
        async with sweeper.transaction():
            await persistence.set_tenant(sweeper, tenant)
            cur = await sweeper.execute(
                "UPDATE app.outbox SET result = 'retrying', attempts = attempts + 1 WHERE run_id = %s", (run,)
            )
            assert cur.rowcount == 1
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await sweeper.execute("DELETE FROM app.outbox WHERE run_id = %s", (run,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await sweeper.execute("UPDATE app.outbox SET recipient = 'x' WHERE run_id = %s", (run,))
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


async def test_no_function_an_mcp_server_may_call_inserts_a_job(app_conn: persistence.Conn) -> None:
    """T14 review note 1 (ruling 27): every function mcp_read or mcp_exec may execute, and every app function those
    call, transitively, is free of an INSERT into jobs; and neither role holds a table grant (SA:437)."""
    cur = await app_conn.execute(
        "SELECT p.proname AS name, pg_get_functiondef(p.oid) AS body,"
        " has_function_privilege('mcp_read', p.oid, 'EXECUTE') AS by_read,"
        " has_function_privilege('mcp_exec', p.oid, 'EXECUTE') AS by_exec"
        " FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'app'"
    )
    rows = await cur.fetchall()
    bodies = {row["name"]: row["body"] for row in rows}
    reachable = {row["name"] for row in rows if row["by_read"] or row["by_exec"]}
    assert {"resolve_invocation", "grant_execution", "mark_sent", "record_outcome", "lookup_action"} <= reachable
    frontier = set(reachable)
    while frontier:  # the helpers they call, and the helpers those call
        called = {name for body in (bodies[f] for f in frontier) for name in CALLS.findall(body)}
        frontier = {name for name in called if name in bodies} - reachable
        reachable |= frontier
    # The helpers the write path reaches today; a new one is checked automatically, a vanished one fails here.
    assert {"_authority", "_resolve_handle", "_transition", "_append_event", "_latest_attempt", "_grant_row"} <= (
        reachable
    )
    assert sorted(name for name in reachable if INSERTS_A_JOB.search(bodies[name])) == []
    cur = await app_conn.execute(
        "SELECT count(*) AS n FROM information_schema.role_table_grants"
        " WHERE grantee IN ('mcp_read', 'mcp_exec') AND table_schema = 'app'"
    )
    assert (await cur.fetchone())["n"] == 0
```

Run (dev stack up, no skeleton process running):

```bash
OPS_LIVE=1 PROFILE=test PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_migration_0008_live.py \
  tests/e2e/test_migration_0007_live.py tests/e2e/test_roles_live.py tests/e2e/test_migrations_and_persistence.py \
  tests/e2e/test_definers_run_path_live.py tests/e2e/test_definers_write_path_live.py -q
```

Expected: `43 passed` (the new 5; the 0007 module's 5, whose round trip now passes through 0008's downgrade; the
roles module's 7, R124 and R106 now with the outbox row, its policy and the sweeper's DELETE; the persistence
module's 7; the run-path definers' 8, whose `append_event` cases keep their verdicts; the write-path definers' 11,
whose `record_outcome` now also writes an intent that `purge_run` removes). This count is arithmetic, not
measured: the plan's dry run cannot run live steps.

- [ ] **Step 6: Gates and commit**

Format, lint and count characters on every file of this task (the revision after the ISC004 pass).

Run: `PYTHONUTF8=1 uv run python scripts/check.py`
Expected: `CHECK: GREEN`; pytest `1007 passed, 139 skipped` (1001 + 5 + 1 parametrised revision; the 5 new live
tests skip).

Run: `PYTHONUTF8=1 uv run python scripts/check.py --profile test`
Expected: `CHECK: GREEN`; pytest `1125 passed, 21 skipped` (arithmetic, not measured: the dev count plus the 118
live-gated tests, 139 − 21). Then
`git checkout -- reports/bootstrap reports/skeleton reports/auth reports/admission reports/leases`.

Run: `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`
Expected: exit 0.

```bash
git add migrations/app/versions/0008_journal_outbox.py core/src/ops_core/privileges.py core/src/ops_core/locking.py
git add tests/plan_i/test_migration_0008.py tests/plan_e/test_transitions_table.py tests/e2e/conftest.py
git add tests/e2e/test_migration_0008_live.py
git commit -m "feat(migrations): revision 0008, the outbox, the payload rules and the intent in _append_event (T14)"
```

---

### Task 3: The gap-free proof (R089) — stepped writers of four roles, a rollback, and a stress run with readers

**Files:**
- Create: `tests/e2e/test_event_journal_live.py`
- Modify: `tests/plan_b/test_evidence.py:1-7` (docstring), `:18-25` (`EVIDENCE_ROOTS`)

**Requirements:** R089 ("Per-run event sequences are gap-free and commit-ordered": "Concurrent writers; SSE replay
never skips"), T14 DoD 1; rulings 1, 2, 3 and 23. This task writes no production code: the mechanism is revision
0003's (`runs` FOR UPDATE, `next_event_seq + 1` and the insert in the caller's transaction, SA:303) and ruling 1
keeps it; the task proves it against real role connections, so its tests pass the first time they run. SSE itself
is T27's; the reader here is the existing events route's query (`DbStore.events`, `after` cursor).

**Interfaces:**
- Consumes: the e2e fixtures `app_conn`, `role_conn`, `backend_pid`, `wait_until_blocked`, `purge_run`,
  `purge_tenant`; `tests.e2e.test_migrations_and_persistence.new_run`; `tests.e2e.test_definers_write_path_live.
  drafting_run`, `freeze`, `approve`, `handle_for`; `tests.e2e.test_definers_run_path_live.ALPHA`;
  `ops_api.store.DbStore(conn).events(tenant_id, run_id, *, after, limit)`; `persistence.set_tenant`.
- Produces: `reports/events/t14-events.txt` (written only when all four tests passed).

- [ ] **Step 1: Scan the new evidence root for secrets**

Edit 1 (`tests/plan_b/test_evidence.py`, docstring), replace:

```python
`reports/admission` (T12's durable-admission evidence) and `reports/leases` (T13's lease, heartbeat and stress
evidence) are scanned the same way.
```

with:

```python
`reports/admission` (T12's durable-admission evidence), `reports/leases` (T13's lease, heartbeat and stress evidence)
and `reports/events` and `reports/outbox` (T14's journal and outbox evidence) are scanned the same way.
```

Edit 2 (`tests/plan_b/test_evidence.py`, `EVIDENCE_ROOTS`), replace:

```python
    Path("reports/admission"),
    Path("reports/leases"),
)
```

with:

```python
    Path("reports/admission"),
    Path("reports/leases"),
    Path("reports/events"),
    Path("reports/outbox"),
)
```

- [ ] **Step 2: Write the journal proof**

Create `tests/e2e/test_event_journal_live.py`:

```python
"""T14 live (OPS_LIVE=1): per-run event sequences are gap-free and commit-ordered under concurrent writers of every
role that writes events, and a reader following the events route's `after` cursor never skips (R089, DoD 1; Plan I
rulings 1-3).

The mechanism is revision 0003's and unchanged (ruling 1): `_append_event` locks the run row FOR UPDATE, takes
`next_event_seq + 1` and inserts in the caller's transaction, so a second writer of the run waits for the first to
commit or roll back. The stepped tests hold writer A's sequence n uncommitted, show with `pg_blocking_pids` that
writer B waits on A, and read through the events route (`DbStore.events`, the query behind
`GET /api/v1/runs/{id}/events`) that neither n nor n+1 is visible until its own writer commits. The pairs cover the
four roles and both kinds of writer: the worker's `transition_run` against the API's `append_event`, and mcp-write's
`mark_sent` (a definer that appends) against the sweeper's `append_event`. The rollback test shows that a writer
that took n and rolled back leaves n to the next writer. The stress test runs eight connections of the four roles
against three runs for ten seconds, every writer rolling back about half of its transactions, while one reader
follows each run's cursor through the route and another counts each run's rows; afterwards every run holds exactly
1..next_event_seq, and no read ever saw a hole below its maximum. The worker writes through `append_event` in the
stress run (its `transition_run` moves a run through pre-grant states only, which the stepped test covers); mcp-write
writes the grant, SENT and outcome of each run, each first attempt rolled back. Writes evidence to
reports/events/t14-events.txt (counts and verdicts; no handle, token or seeded tenant id).

Catches: a sequence number taken outside the run lock (two writers with one number, or a reader seeing n+1 before n),
a rolled-back writer that leaves a hole, a definer that appends without the lock, an events route that returns a
later sequence before an earlier one has committed (the cursor would skip it for good), and an outbox intent written
twice for one run under contention.
"""

import asyncio
import random
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from ops_api.store import DbStore
from ops_core import persistence
from ops_core.settings import Role
from psycopg.types.json import Jsonb

from tests.e2e.conftest import backend_pid, purge_run, purge_tenant, wait_until_blocked
from tests.e2e.test_definers_run_path_live import ALPHA
from tests.e2e.test_definers_write_path_live import approve, drafting_run, freeze, handle_for
from tests.e2e.test_migrations_and_persistence import new_run

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
EVIDENCE = Path("reports/events/t14-events.txt")
EXPECTED_LINES = 4  # one per test
APPEND = "SELECT * FROM app.append_event(%s, %s, %s, 'application')"
STRESS_SECONDS = 10.0
LOCK_TIMEOUT = "SET lock_timeout = '10s'"


@pytest.fixture(scope="module")
def lines() -> Iterator[list[str]]:
    out = [f"T14 event journal — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"]
    yield out
    if len(out) != 1 + EXPECTED_LINES:  # a failed or partial run leaves the committed file as it was
        return
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


async def route(store: DbStore, tenant: UUID, run: UUID, after: int = 0) -> list[int]:
    """The sequences the events route returns after a cursor, in its order."""
    return [int(e["sequence"]) for e in await store.events(tenant, run, after=after, limit=500)]


async def sequences(app_conn: persistence.Conn, run: UUID) -> tuple[list[int], int]:
    """Every committed sequence of the run, and the run's counter."""
    cur = await app_conn.execute("SELECT sequence FROM app.events WHERE run_id = %s ORDER BY sequence", (run,))
    seen = [int(row["sequence"]) for row in await cur.fetchall()]
    cur = await app_conn.execute("SELECT next_event_seq FROM app.runs WHERE run_id = %s", (run,))
    return seen, int((await cur.fetchone())["next_event_seq"])


async def stepped(
    app_conn: persistence.Conn,
    store: DbStore,
    tenant: UUID,
    run: UUID,
    a: tuple[persistence.Conn, str, tuple[object, ...]],
    b: tuple[persistence.Conn, str, tuple[object, ...]],
) -> int:
    """Writer A appends sequence n and holds it uncommitted; writer B's append waits on A (pg_blocking_pids); the
    route shows n only after A commits and n + 1 only after B commits. Returns n."""
    (a_conn, a_sql, a_params), (b_conn, b_sql, b_params) = a, b
    before = await route(store, tenant, run)
    n = len(before) + 1
    assert before == list(range(1, n))
    b_appended, b_may_commit = asyncio.Event(), asyncio.Event()

    async def writer_b() -> None:
        async with b_conn.transaction():
            await b_conn.execute(b_sql, b_params)
            b_appended.set()
            await b_may_commit.wait()

    async with a_conn.transaction():
        await a_conn.execute(a_sql, a_params)
        assert await route(store, tenant, run, after=n - 1) == []  # n is taken, not committed: invisible
        b_task = asyncio.create_task(writer_b())
        holders = await wait_until_blocked(app_conn, await backend_pid(b_conn))
        assert await backend_pid(a_conn) in holders  # B waits on A's run row lock, nothing else
        assert not b_appended.is_set() and await route(store, tenant, run, after=n - 1) == []
    await asyncio.wait_for(b_appended.wait(), timeout=5)  # A committed; B got n + 1 and holds it
    assert await route(store, tenant, run, after=n - 1) == [n]  # the cursor sees n, never n + 1 first
    b_may_commit.set()
    await asyncio.wait_for(b_task, timeout=5)
    assert await route(store, tenant, run, after=n) == [n + 1]
    seen, counter = await sequences(app_conn, run)
    assert seen == list(range(1, n + 2)) and counter == n + 1
    return n


async def test_r089_transition_run_and_api_append_commit_in_order(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    api, worker, reader = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.API)
    tenant, _, run = await new_run(app_conn, api=api)
    try:
        await worker.execute("SELECT app.transition_run(%s, 'QUEUED', 'RETRIEVING', NULL, 1, '{}')", (run,))  # no event
        n = await stepped(
            app_conn,
            DbStore(reader),
            tenant,
            run,
            (worker, "SELECT app.transition_run(%s, 'RETRIEVING', 'AWAITING_INPUT', NULL, 2, '{}')", (run,)),
            (api, APPEND, (run, "tool.completed", Jsonb({"message": "api"}))),
        )
        lines.append(f"R089 stepped: worker transition_run took {n}, api append_event waited and took {n + 1}")
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


async def test_r089_mark_sent_and_sweeper_append_commit_in_order(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    api, worker, reader = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.API)
    mcp_exec, sweeper = await role_conn(Role.MCP_EXEC), await role_conn(Role.SWEEPER)
    run = await drafting_run(app_conn, api, worker)
    try:
        proposal, _, digest = await freeze(app_conn, worker, run)
        await approve(api, proposal, digest)
        handle = await handle_for(app_conn, run, "execute", expires_in=600)
        cur = await mcp_exec.execute("SELECT * FROM app.grant_execution(%s, %s)", (handle, proposal))
        action = (await cur.fetchone())["action_id"]
        n = await stepped(
            app_conn,
            DbStore(reader),
            ALPHA,
            run,
            (mcp_exec, "SELECT app.mark_sent(%s, %s)", (handle, action)),
            (sweeper, APPEND, (run, "tool.completed", Jsonb({"message": "sweeper"}))),
        )
        lines.append(f"R089 stepped: mcp_exec mark_sent took {n}, sweeper append_event waited and took {n + 1}")
    finally:
        await purge_run(app_conn, run)


async def test_r089_a_rolled_back_writer_leaves_no_hole(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    """Ruling 3 (b): A takes n and rolls back; B, which waited on A, then gets n itself."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    tenant, _, run = await new_run(app_conn, api=api)
    try:
        b_got: list[int] = []

        async def writer_b() -> None:
            async with worker.transaction():
                cur = await worker.execute(APPEND, (run, "tool.started", Jsonb({"message": "worker"})))
                b_got.append(int((await cur.fetchone())["sequence"]))

        async with api.transaction(force_rollback=True):
            cur = await api.execute(APPEND, (run, "tool.completed", Jsonb({"message": "rolled back"})))
            taken = int((await cur.fetchone())["sequence"])
            b_task = asyncio.create_task(writer_b())
            assert await backend_pid(api) in await wait_until_blocked(app_conn, await backend_pid(worker))
        await asyncio.wait_for(b_task, timeout=5)
        assert b_got == [taken] == [2]  # the number A gave back, after run.accepted
        seen, counter = await sequences(app_conn, run)
        assert seen == [1, 2] and counter == 2
        lines.append(f"R089 rollback: api took {taken} and rolled back; the waiting worker took {b_got[0]}; no hole")
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


class Tally:
    """Commits and rollbacks per role, and the lock errors the stress run must never see."""

    def __init__(self) -> None:
        self.committed: Counter[str] = Counter()
        self.rolled_back: Counter[str] = Counter()
        self.errors: Counter[str] = Counter()


async def append_actor(
    conn: persistence.Conn, role: str, runs: list[UUID], tally: Tally, stop: float, seed: str
) -> None:
    """Append one event to a random run per transaction; every third transaction, and a quarter of the rest, rolls
    back after it has taken its number."""
    rng = random.Random(seed)
    kind = "tool.started" if role == "worker" else "tool.completed"
    step = 0
    while time.monotonic() < stop:
        rollback = step % 3 == 0 or rng.random() < 0.25
        try:
            async with conn.transaction(force_rollback=rollback):
                await conn.execute(APPEND, (rng.choice(runs), kind, Jsonb({"message": f"{role} {step}"})))
        except psycopg.errors.LockNotAvailable:
            tally.errors["55P03"] += 1
        except psycopg.errors.DeadlockDetected:
            tally.errors["40P01"] += 1
        else:
            (tally.rolled_back if rollback else tally.committed)[role] += 1
        step += 1
        await asyncio.sleep(rng.random() * 0.004)


async def mcp_actor(conn: persistence.Conn, work: list[dict[str, Any]], tally: Tally) -> None:
    """Grant, SENT and the outcome of each of its runs, through the definers; each step's first attempt rolls back
    after the definer appended its event, the second commits."""
    calls = (
        ("grant", "SELECT * FROM app.grant_execution(%s, %s)"),
        ("sent", "SELECT app.mark_sent(%s, %s) AS r"),
        ("outcome", "SELECT app.record_outcome(%s, %s, 'SUCCEEDED', %s) AS r"),
    )
    for item in work:
        for name, sql in calls:
            for rollback in (True, False):
                if name == "grant":
                    params: tuple[object, ...] = (item["handle"], item["proposal"])
                elif name == "sent":
                    params = (item["handle"], item["action"])
                else:
                    document = {
                        "status": "SUCCEEDED",
                        "action_id": str(item["action"]),
                        "payload_sha256": item["digest"],
                        "receipt": {"receipt_id": str(uuid4()), "incident_id": "INC-T14", "committed_at": item["at"]},
                        "tombstone": None,
                        "reason": None,
                    }
                    params = (item["handle"], item["action"], Jsonb(document))
                async with conn.transaction(force_rollback=rollback):
                    cur = await conn.execute(sql, params)
                    row = await cur.fetchone()
                    if name == "grant":
                        item["action"] = row["action_id"]  # a rolled-back grant's id is gone; the next one stands
                (tally.rolled_back if rollback else tally.committed)["mcp_exec"] += 1
                await asyncio.sleep(0.05)


async def cursor_reader(store: DbStore, runs: list[UUID], stop: float, seen: dict[str, int]) -> list[str]:
    """Follow each run's cursor through the events route; every page must continue exactly where the last one
    ended (`after` + 1, contiguous). Returns the violations."""
    last = dict.fromkeys(runs, 0)
    wrong: list[str] = []
    while time.monotonic() < stop + 0.5:
        for run in runs:
            page = await route(store, ALPHA, run, after=last[run])
            if page and page != list(range(last[run] + 1, last[run] + 1 + len(page))):
                wrong.append(f"after {last[run]}: {page[:3]}")
            if page:
                last[run] = page[-1]
            seen["pages"] += 1
        await asyncio.sleep(0.02)
    return wrong


async def count_reader(conn: persistence.Conn, runs: list[UUID], stop: float, seen: dict[str, int]) -> list[str]:
    """Count each run's committed rows against their maximum in one snapshot: a hole below the maximum would show as
    fewer rows than the maximum. Returns the violations."""
    wrong: list[str] = []
    while time.monotonic() < stop + 0.5:
        async with conn.transaction():
            await persistence.set_tenant(conn, ALPHA)
            cur = await conn.execute(
                "SELECT run_id, count(*) AS n, max(sequence) AS hi FROM app.events WHERE run_id = ANY(%s)"
                " GROUP BY run_id",
                (runs,),
            )
            for row in await cur.fetchall():
                if row["n"] != row["hi"]:
                    wrong.append(f"{row['n']} rows below {row['hi']}")
        seen["counts"] += 1
        await asyncio.sleep(0.02)
    return wrong


async def test_r089_stress_four_roles_three_runs_with_rollbacks(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    runs: list[UUID] = []
    try:
        work: list[dict[str, Any]] = []
        for _ in range(3):
            run = await drafting_run(app_conn, api, worker)
            runs.append(run)
            proposal, _, digest = await freeze(app_conn, worker, run)
            await approve(api, proposal, digest)
            handle = await handle_for(app_conn, run, "execute", expires_in=600)
            at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            work.append({"run": run, "proposal": proposal, "digest": digest, "handle": handle, "at": at})
        actors = {
            role: [await role_conn(role) for _ in range(2)]
            for role in (Role.API, Role.WORKER, Role.SWEEPER, Role.MCP_EXEC)
        }
        for conn in (c for group in actors.values() for c in group):
            await conn.execute(LOCK_TIMEOUT)
        tally, seen = Tally(), {"pages": 0, "counts": 0}
        stop = time.monotonic() + STRESS_SECONDS
        appenders = [
            append_actor(conn, role.value, runs, tally, stop, f"{role.value}-{i}")
            for role in (Role.API, Role.WORKER, Role.SWEEPER)
            for i, conn in enumerate(actors[role])
        ]
        mcp = [
            mcp_actor(actors[Role.MCP_EXEC][0], work[0::2], tally),
            mcp_actor(actors[Role.MCP_EXEC][1], work[1::2], tally),
        ]
        readers = [
            cursor_reader(DbStore(await role_conn(Role.API)), runs, stop, seen),
            count_reader(await role_conn(Role.SWEEPER), runs, stop, seen),
        ]
        results = await asyncio.gather(*appenders, *mcp, *readers)
        cursor_wrong, count_wrong = results[-2], results[-1]
        assert cursor_wrong == [] and count_wrong == []
        assert tally.errors == Counter()  # no 55P03 and no 40P01: one run row per transaction, one lock order
        for role in ("api", "worker", "sweeper", "mcp_exec"):  # every role both committed and gave numbers back
            assert tally.committed[role] >= 3 and tally.rolled_back[role] >= 3, role
        assert seen["pages"] >= 100 and seen["counts"] >= 100  # the readers read while the writers wrote
        total = 0
        for run in runs:
            got, counter = await sequences(app_conn, run)
            assert got == list(range(1, counter + 1)), run  # gap-free: exactly 1..next_event_seq
            total += counter
            cur = await app_conn.execute(
                "SELECT r.state, (SELECT count(*) FROM app.outbox o WHERE o.run_id = r.run_id) AS intents"
                " FROM app.runs r WHERE r.run_id = %s",
                (run,),
            )
            assert dict(await cur.fetchone()) == {"state": "SUCCEEDED", "intents": 1}  # one intent despite rollbacks
        lines.append(
            f"R089 stress: 8 connections of api, worker, sweeper and mcp_exec on 3 runs for {STRESS_SECONDS:.0f} s;"
            f" committed {sum(tally.committed.values())}, rolled back {sum(tally.rolled_back.values())};"
            f" {total} events, every run exactly 1..next_event_seq; route pages {seen['pages']},"
            f" count samples {seen['counts']}, no hole and no skip seen; 55P03 0, 40P01 0"
        )
    finally:
        for run in runs:
            await purge_run(app_conn, run)
```

- [ ] **Step 3: Run it**

Run (dev stack up, no skeleton process running):

```bash
OPS_LIVE=1 PROFILE=test PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_event_journal_live.py -q
```

Expected: `4 passed` (about 20 s; the stress run takes 10 s plus its staging), and `reports/events/t14-events.txt`
exists with five lines. This count is arithmetic, not measured: the plan's dry run cannot run live steps. A failure
here is a finding against revision 0003's mechanism (ruling 1), not a reason to weaken an assertion: stop and report.

- [ ] **Step 4: Gates and commit**

Format, lint and count characters on `tests/e2e/test_event_journal_live.py` and `tests/plan_b/test_evidence.py`.

Run: `PYTHONUTF8=1 uv run python scripts/check.py`
Expected: `CHECK: GREEN`; pytest `1007 passed, 143 skipped` (the 4 new live tests skip).

Run: `PYTHONUTF8=1 uv run python scripts/check.py --profile test`
Expected: `CHECK: GREEN`; pytest `1129 passed, 21 skipped` (arithmetic, not measured: 1007 + 122 live-gated tests).
Then `git checkout -- reports/bootstrap reports/skeleton reports/auth reports/admission reports/leases`
(`reports/events` stays for Task 6).

Run: `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`
Expected: exit 0.

```bash
git add tests/e2e/test_event_journal_live.py tests/plan_b/test_evidence.py
git commit -m "test(e2e): per-run event sequences stay gap-free and commit-ordered under four roles (R089)"
```

---

### Task 4: The outbox delivery loop — tenants, `LogSink`, the fault hook, retry, dead letter (R024)

**Files:**
- Create: `sweeper/src/ops_sweeper/tenants.py`, `sweeper/src/ops_sweeper/outbox.py`, `tests/plan_i/test_outbox.py`,
  `tests/plan_i/test_sweeper_tick.py`, `tests/e2e/test_outbox_live.py`
- Modify: `core/src/ops_core/testing/faults.py:1-7` (docstring), `:26-27` (the new kind), `:43-44` (`SWEEPER_FAULTS`),
  `tests/plan_h/test_faults_t13.py:8-17`, `sweeper/src/ops_sweeper/main.py:1-12` (docstring), `:14-37` (imports),
  `:40-51` (`Deps`), `:112-140` (`tick`, `record_sync` → `record`), `:178-206` (`_main`),
  `tests/plan_h/test_reclaim.py:61-82` (the tick test)

**Requirements:** R024 ("Notification intent is transactional and deduplicated": "Fail delivery after state commit;
result remains recorded and dedup key preserves intent"), T14 DoD 2, review note 3 (the sweeper iterates tenants);
rulings 14-19 and 25; DEV-029's "fault-injectable outbox sink" (T24 review note).

**Interfaces:**
- Consumes: `ops_core.settings.OutboxSettings`, `outbox()`; `persistence.tenants`, `set_tenant`, `append_event`,
  `insert_maintenance_job`, `claim_maintenance_job`, `finish_job`; `ops_core.outcomes.EventType.NOTIFICATION_FAILED`;
  `ops_core.testing.faults.Faults`; revision 0008's `app.outbox` (Task 2).
- Produces: `ops_core.testing.faults.FaultKind.OUTBOX_SINK_FAIL`, `SWEEPER_FAULTS`;
  `ops_sweeper.tenants.in_tenant(conn, tenant_id, work) -> T`, `for_each_tenant(conn, work, *, tenants=None) ->
  dict[UUID, T]` (`work: Callable[[Conn], Awaitable[T]]`, one transaction per tenant after `set_tenant`; Task 5 uses
  both); `ops_sweeper.outbox.Delivery`, `Sink` (protocol: `async deliver(delivery) -> None`, raises `SinkFailed`),
  `SinkFailed`, `LogSink(faults: Faults | None = None)`, `recipient_hash(recipient) -> str`,
  `backoff_seconds(attempts, chosen, rng=random.random) -> float`, `Result(outbox_id, tenant_id, run_id, result,
  attempts, recorded)`, `deliver(conn, sink, chosen, *, tenants=None, rng=random.random) -> list[Result]`,
  `notify_dead_letters(conn, *, tenants=None) -> list[UUID]`, `DEAD_LETTER_CODE`; `ops_sweeper.main.Deps.sink`,
  `Deps.outbox_settings`, `main.deliver_outbox(deps)`, `main.record(deps, job_type)` (Task 5 calls it for
  `sweep_wakeups`).

- [ ] **Step 1: Write the failing unit tests**

Create `tests/plan_i/test_outbox.py`:

```python
"""The outbox delivery loop without a database (Plan I rulings 14-18): the backoff and its jitter, the log sink and
its test-profile fault, the claim and result units per tenant, and the dead letter's event in a transaction of its
own.

Catches: a delivery made while the claim's transaction is still open (a slow sink would hold row locks, and a crash
would roll the claim back and lose the lease), a result recorded in the claim's unit, a retry without backoff or
with an uncapped one, a row dead-lettered one attempt early or late, a recipient written to a log in clear, a
notification.failed appended in the result's transaction (it locks runs after outbox, SA:188) or appended twice for
one dead letter, a payload `_append_event` would refuse, and a fault hook that exists outside the test profile.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest
from ops_core import persistence
from ops_core.outcomes import EventSource, EventType, event_rules_ok
from ops_core.settings import OutboxSettings, Profile
from ops_core.testing.faults import BS405, SWEEPER_FAULTS, FaultKind, Faults, FaultsDisabled
from ops_sweeper import outbox, tenants

ALPHA, BETA = uuid4(), uuid4()
SETTINGS = OutboxSettings()


class FakeCursor:
    def __init__(self, rows: list[dict[str, Any]], rowcount: int) -> None:
        self.rows, self.rowcount = rows, rowcount

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None


class FakeConn:
    """Records every statement with the transaction it ran in; answers from `answers` by statement prefix."""

    def __init__(self, answers: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.answers = answers or {}
        self.log: list[tuple[int, str, Any]] = []
        self.unit = 0
        self.open = False

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        assert not self.open  # never nested: every unit is its own transaction
        self.unit += 1
        self.open = True
        try:
            yield
        finally:
            self.open = False

    async def execute(self, statement: str, params: Any = None) -> FakeCursor:
        assert self.open, statement  # nothing runs outside a unit
        self.log.append((self.unit, statement, params))
        for prefix, rows in self.answers.items():
            if statement.startswith(prefix):
                return FakeCursor(rows, len(rows))
        return FakeCursor([], 1)


@pytest.fixture(autouse=True)
def database(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """set_tenant and append_event replaced by recorders; two tenants."""
    calls: list[Any] = []

    async def set_tenant(conn: FakeConn, tenant_id: UUID) -> None:
        calls.append(("set_tenant", conn.unit, tenant_id))

    async def append_event(conn: FakeConn, **kwargs: Any) -> None:
        calls.append(("append_event", conn.unit, kwargs))

    async def all_tenants(_conn: Any) -> list[UUID]:
        return [ALPHA, BETA]

    monkeypatch.setattr(persistence, "set_tenant", set_tenant)
    monkeypatch.setattr(persistence, "append_event", append_event)
    monkeypatch.setattr(persistence, "tenants", all_tenants)
    return calls


def claimed(attempts: int, run_id: UUID | None = None) -> dict[str, Any]:
    return {
        "outbox_id": uuid4(),
        "tenant_id": ALPHA,
        "run_id": run_id or uuid4(),
        "event_id": uuid4(),
        "channel": "local",
        "recipient": "2fc05986-c7ec-544c-b628-fdb112bbf18a",
        "attempts": attempts,
        "type": "action.confirmed",
    }


class Recording:
    """A sink that records whether a transaction was open when it was called, and fails when told to."""

    def __init__(self, conn: FakeConn, fail: bool) -> None:
        self.conn, self.fail = conn, fail
        self.calls: list[tuple[outbox.Delivery, bool]] = []

    async def deliver(self, delivery: outbox.Delivery) -> None:
        self.calls.append((delivery, self.conn.open))
        if self.fail:
            raise outbox.SinkFailed("down")


def run(coro: Awaitable[Any]) -> Any:
    async def main() -> Any:
        return await coro

    return asyncio.run(main())


def test_the_backoff_doubles_from_its_base_up_to_its_cap_plus_a_quarter_of_jitter() -> None:
    assert outbox.backoff_seconds(1, SETTINGS, rng=lambda: 0.0) == 2.0
    assert outbox.backoff_seconds(3, SETTINGS, rng=lambda: 0.0) == 8.0
    assert outbox.backoff_seconds(3, SETTINGS, rng=lambda: 1.0) == 10.0  # up to 25 % on top
    assert outbox.backoff_seconds(20, SETTINGS, rng=lambda: 0.0) == 300.0  # BS:562: capped
    assert outbox.backoff_seconds(100, SETTINGS, rng=lambda: 1.0) == 375.0


def test_the_log_sink_logs_one_line_without_the_recipient(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="ops_sweeper.outbox")
    row = claimed(1)
    delivery = outbox.Delivery(row["outbox_id"], ALPHA, row["run_id"], row["type"], "local", row["recipient"], 1)
    run(outbox.LogSink().deliver(delivery))
    (record,) = caplog.records
    assert str(row["outbox_id"]) in record.getMessage() and "action.confirmed" in record.getMessage()
    assert row["recipient"] not in caplog.text and outbox.recipient_hash(row["recipient"]) in record.getMessage()


def test_the_sink_fault_fails_exactly_the_armed_deliveries() -> None:
    faults = Faults(Profile.TEST)
    faults.arm(FaultKind.OUTBOX_SINK_FAIL, 2)
    sink = outbox.LogSink(faults)
    row = claimed(1)
    delivery = outbox.Delivery(row["outbox_id"], ALPHA, row["run_id"], row["type"], "local", row["recipient"], 1)
    for _ in range(2):
        with pytest.raises(outbox.SinkFailed):
            run(sink.deliver(delivery))
    run(sink.deliver(delivery))  # the third is delivered
    assert faults.armed() == {}


def test_the_sink_fault_belongs_to_the_sweeper_and_the_test_profile_only() -> None:
    assert FaultKind.OUTBOX_SINK_FAIL in SWEEPER_FAULTS and FaultKind.OUTBOX_SINK_FAIL not in BS405.values()
    for profile in (Profile.DEV, Profile.DEMO):
        with pytest.raises(FaultsDisabled):
            Faults(profile)


def test_for_each_tenant_runs_one_transaction_per_tenant_after_set_tenant(database: list[Any]) -> None:
    conn = FakeConn()
    as_conn: Any = conn

    async def work(c: Any) -> int:
        await c.execute("SELECT 1")
        return c.unit

    assert run(tenants.for_each_tenant(as_conn, work)) == {ALPHA: 1, BETA: 2}
    assert database == [("set_tenant", 1, ALPHA), ("set_tenant", 2, BETA)]
    assert run(tenants.for_each_tenant(as_conn, work, tenants=[BETA])) == {BETA: 3}


@pytest.mark.parametrize(
    ("attempts", "fail", "result"), [(1, False, "delivered"), (1, True, "retrying"), (5, True, "dead_letter")]
)
def test_a_delivery_runs_between_its_claim_and_its_result_unit(attempts: int, fail: bool, result: str) -> None:
    row = claimed(attempts)
    conn = FakeConn({"WITH claimed AS (UPDATE app.outbox": [row]})
    as_conn: Any = conn
    sink = Recording(conn, fail)
    results = run(outbox.deliver(as_conn, sink, SETTINGS, tenants=[ALPHA], rng=lambda: 0.0))
    assert results == [outbox.Result(row["outbox_id"], ALPHA, row["run_id"], result, attempts, True)]
    ((delivery, open_transaction),) = sink.calls
    assert not open_transaction and delivery.attempt == attempts  # delivered outside any transaction
    (claim_unit, claim, claim_params), (result_unit, record, record_params) = conn.log
    assert result_unit == claim_unit + 1  # the result is its own unit
    for condition in (
        "delivered_at IS NULL",
        "result IS DISTINCT FROM 'dead_letter'",
        "leased_until <= app.current_time()",
        "FOR UPDATE SKIP LOCKED",
        "attempts = attempts + 1",
    ):
        assert condition in claim, condition
    assert claim_params == (SETTINGS.lease_seconds, SETTINGS.batch)
    assert "AND attempts = %s AND delivered_at IS NULL" in record  # a stale result never overwrites a newer claim
    if result == "delivered":
        assert "result = 'delivered'" in record and record_params == (row["outbox_id"], attempts)
    elif result == "retrying":
        assert "result = 'retrying'" in record and record_params == (2.0, row["outbox_id"], attempts)
    else:
        assert "result = 'dead_letter'" in record and record_params == (row["outbox_id"], attempts)


def test_an_unclaimed_tenant_delivers_nothing() -> None:
    conn = FakeConn()
    as_conn: Any = conn
    sink = Recording(conn, fail=False)
    assert run(outbox.deliver(as_conn, sink, SETTINGS)) == [] and sink.calls == []
    assert [unit for unit, _, _ in conn.log] == [1, 2]  # one claim per tenant, nothing else


def test_a_dead_letter_gets_its_event_in_a_transaction_of_its_own(database: list[Any]) -> None:
    run_id, outbox_id = uuid4(), uuid4()
    pending = {"outbox_id": outbox_id, "run_id": run_id, "attempts": 5}
    conn = FakeConn({"SELECT o.outbox_id, o.run_id, o.attempts FROM app.outbox o": [pending]})
    as_conn: Any = conn
    assert run(outbox.notify_dead_letters(as_conn, tenants=[ALPHA])) == [outbox_id]
    appended = [call for call in database if call[0] == "append_event"]
    ((_, unit, kwargs),) = appended
    find_unit = conn.log[0][0]
    assert unit == find_unit + 1  # the re-check and the append share a unit after the scan's
    assert kwargs["run_id"] == run_id and kwargs["type"] is EventType.NOTIFICATION_FAILED
    payload = kwargs["payload"]
    assert payload["outbox_id"] == str(outbox_id) and payload["code"] == outbox.DEAD_LETTER_CODE
    event_rules_ok(EventType.NOTIFICATION_FAILED, EventSource.APPLICATION, payload)  # what _append_event accepts
    recheck = [s for u, s, _ in conn.log if u == unit]
    assert len(recheck) == 1 and "AND o.outbox_id = %s" in recheck[0]


def test_a_dead_letter_already_notified_gets_no_second_event(database: list[Any]) -> None:
    pending = {"outbox_id": uuid4(), "run_id": uuid4(), "attempts": 5}
    conn = FakeConn({"SELECT o.outbox_id, o.run_id, o.attempts FROM app.outbox o": [pending]})

    class Raced(FakeConn):
        async def execute(self, statement: str, params: Any = None) -> FakeCursor:
            if "AND o.outbox_id = %s" in statement:  # another sweeper appended it meanwhile: the re-check is empty
                self.log.append((self.unit, statement, params))
                return FakeCursor([], 0)
            return await super().execute(statement, params)

    raced = Raced(conn.answers)
    as_conn: Any = raced
    assert run(outbox.notify_dead_letters(as_conn, tenants=[ALPHA])) == []
    assert not [call for call in database if call[0] == "append_event"]


def test_an_unexpected_sink_error_leaves_the_row_leased(monkeypatch: pytest.MonkeyPatch) -> None:
    """A sink that raises anything but SinkFailed is a crash: nothing is recorded, and the row comes back when its
    lease runs out (ruling 15)."""
    row = claimed(1)
    conn = FakeConn({"WITH claimed AS (UPDATE app.outbox": [row]})
    as_conn: Any = conn

    class Broken:
        async def deliver(self, delivery: outbox.Delivery) -> None:
            raise RuntimeError("the sink crashed")

    with pytest.raises(RuntimeError):
        run(outbox.deliver(as_conn, Broken(), SETTINGS, tenants=[ALPHA]))
    assert len(conn.log) == 1  # the claim only
```

Edit 1 (`tests/plan_h/test_faults_t13.py`, the BS:405 test), replace:

```python
import pytest
from ops_core.settings import Profile
from ops_core.testing.faults import BS405, DEFAULT_SECONDS, FaultKind, Faults, FaultsDisabled


def test_every_bs405_phrase_maps_to_one_kind_or_the_harness() -> None:
    assert len(BS405) == 9  # BS:405 names nine
    kinds = [kind for kind in BS405.values() if kind is not None]
    assert len(kinds) == len(set(kinds)) and set(kinds) == set(FaultKind)  # one hook each, no orphan hook
```

with:

```python
import pytest
from ops_core.settings import Profile
from ops_core.testing.faults import BS405, DEFAULT_SECONDS, SWEEPER_FAULTS, FaultKind, Faults, FaultsDisabled


def test_every_bs405_phrase_maps_to_one_kind_or_the_harness() -> None:
    assert len(BS405) == 9  # BS:405 names nine
    kinds = [kind for kind in BS405.values() if kind is not None]
    # One hook each, and no orphan hook: every kind outside BS:405 is the sweeper's outbox sink fault (T14).
    assert len(kinds) == len(set(kinds)) and set(kinds) == set(FaultKind) - SWEEPER_FAULTS
```

Run: `uv run python -m pytest tests/plan_i/test_outbox.py tests/plan_h/test_faults_t13.py -q`
Expected: `2 errors in` (both modules stop at collection: `ImportError: cannot import name 'SWEEPER_FAULTS' from
'ops_core.testing.faults'`).

- [ ] **Step 2: The fault kind**

Edit 1 (`core/src/ops_core/testing/faults.py`, docstring), replace:

```python
its factory built (incident-sim's destination faults, the API's admission faults; Plan H ruling 22). `BS405` maps
BUILD_SPEC's nine faults to the hooks. The worker and the sweeper have none: their failure, a lost lease, is produced
for real by the tests (Plan H ruling 20).
"""
```

with:

```python
its factory built (incident-sim's destination faults, the API's admission faults; Plan H ruling 22). `BS405` maps
BUILD_SPEC's nine faults to the hooks. The worker has none: its failure, a lost lease, is produced for real by the
tests (Plan H ruling 20). The sweeper has one, `outbox_sink_fail`, and no route: the live tests build its outbox sink
with a test-profile `Faults` (Plan I ruling 14; T24's DEV-029 needs a fault-injectable sink).
"""
```

Edit 2 (`core/src/ops_core/testing/faults.py`, the last kind), replace:

```python
    DELAY_RECEIPT = "delay_receipt"  # the next lookup of a committed key answers 404, as if not yet visible
```

with:

```python
    DELAY_RECEIPT = "delay_receipt"  # the next lookup of a committed key answers 404, as if not yet visible
    OUTBOX_SINK_FAIL = "outbox_sink_fail"  # the sweeper's next notification delivery fails (T14, R024)
```

Edit 3 (`core/src/ops_core/testing/faults.py`, after `BS405`), replace:

```python
TIMED: Final = frozenset({FaultKind.TIMEOUT_BEFORE_ACCEPT})  # the kinds that take `seconds`
```

with:

```python
# The sweeper's own hook: not one of BS:405's destination faults, and armed only through its sink's factory argument.
SWEEPER_FAULTS: Final = frozenset({FaultKind.OUTBOX_SINK_FAIL})
TIMED: Final = frozenset({FaultKind.TIMEOUT_BEFORE_ACCEPT})  # the kinds that take `seconds`
```

Run: `uv run python -m pytest tests/plan_i/test_outbox.py tests/plan_h/test_faults_t13.py -q`
Expected: `1 error in` (only `test_outbox.py` stops at collection now: `ImportError: cannot import name 'outbox'
from 'ops_sweeper'`).

- [ ] **Step 3: The tenant iteration and the delivery loop**

Create `sweeper/src/ops_sweeper/tenants.py`:

```python
"""The sweeper's tenant iteration (SA:520; Plan I ruling 18; T14 review note 3): for every table but `memberships`
and `jobs` the sweeper has no cross-tenant policy, so it reads the RLS-free `tenants` table and runs its work in one
transaction per tenant with that tenant set. The outbox delivery and the wake-up sweep use it now; T21's proposal
expiry and T22's deadline escalation will.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from uuid import UUID

from ops_core import persistence


async def in_tenant[T](conn: persistence.Conn, tenant_id: UUID, work: Callable[[persistence.Conn], Awaitable[T]]) -> T:
    """Run `work` in one transaction with `tenant_id` set (transaction-local, so the next unit starts tenant-less)."""
    async with conn.transaction():
        await persistence.set_tenant(conn, tenant_id)
        return await work(conn)


async def for_each_tenant[T](
    conn: persistence.Conn,
    work: Callable[[persistence.Conn], Awaitable[T]],
    *,
    tenants: Sequence[UUID] | None = None,
) -> dict[UUID, T]:
    """`work`'s answer per tenant, each in its own transaction; every tenant unless `tenants` narrows it (tests)."""
    chosen = await persistence.tenants(conn) if tenants is None else list(tenants)
    return {tenant: await in_tenant(conn, tenant, work) for tenant in chosen}
```

Create `sweeper/src/ops_sweeper/outbox.py`:

```python
"""The notification outbox's delivery loop (BS:524; Plan I rulings 13-17; errata 66-68), run by the sweeper's tick.

`_append_event` writes one intent per run, event type, channel and recipient in the event's own transaction (revision
0008). Here, per tenant: a claim unit leases a batch of due rows (`FOR UPDATE SKIP LOCKED`, `leased_until` moved one
lease ahead, `attempts + 1`) and commits; each row is handed to the sink outside any transaction; then one result
unit per row records `delivered`, or `retrying` with a capped, jittered backoff in `leased_until`, or `dead_letter`
at the last attempt. The result names the attempt it belongs to, so a delivery that outlived its lease and was
claimed again cannot overwrite the newer claim's result. A sink that crashes records nothing, and the row comes back
when its lease runs out. The run's state is never touched: the delivery result is recorded apart from the action's
outcome (DoD 2, BS:685).

A dead letter is announced by `notification.failed`, appended through `append_event` in a transaction of its own
after the result unit, because `append_event` locks `runs` and SA:188 forbids taking `runs` after `outbox`. The
dead letters still lacking that event are found again on every tick (`notify_dead_letters`), which closes the crash
window between the result and the event; the re-check and the append share one transaction.

The v1 sink is `LogSink`: one log line per delivery and no egress (no channel is approved before Slack, T39). Its
fault hook, `outbox_sink_fail`, exists only in the test profile and is armed through the sink's `faults` argument.
"""

from __future__ import annotations

import functools
import hashlib
import logging
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from ops_core import persistence
from ops_core.outcomes import EventType
from ops_core.settings import OutboxSettings
from ops_core.testing.faults import FaultKind, Faults

from ops_sweeper.tenants import for_each_tenant, in_tenant

log = logging.getLogger("ops_sweeper.outbox")

DEAD_LETTER_CODE = "notification_dead_letter"
# BS:516: infrastructure failures are reported from templates, never from a model.
DEAD_LETTER_MESSAGE = "The notification could not be delivered after {attempts} attempts; the run's outcome stands."

CLAIM = (
    "WITH claimed AS (UPDATE app.outbox SET leased_until = app.current_time() + make_interval(secs => %s),"
    " attempts = attempts + 1"
    " WHERE outbox_id IN (SELECT outbox_id FROM app.outbox"
    " WHERE delivered_at IS NULL AND result IS DISTINCT FROM 'dead_letter' AND leased_until <= app.current_time()"
    " ORDER BY created_at, outbox_id FOR UPDATE SKIP LOCKED LIMIT %s)"
    " RETURNING outbox_id, tenant_id, run_id, event_id, channel, recipient, attempts)"
    " SELECT c.outbox_id, c.tenant_id, c.run_id, c.event_id, c.channel, c.recipient, c.attempts, e.type"
    " FROM claimed c JOIN app.events e ON e.event_id = c.event_id ORDER BY c.outbox_id"
)
DELIVERED = (
    "UPDATE app.outbox SET delivered_at = app.current_time(), result = 'delivered'"
    " WHERE outbox_id = %s AND attempts = %s AND delivered_at IS NULL"
)
RETRY = (
    "UPDATE app.outbox SET result = 'retrying', leased_until = app.current_time() + make_interval(secs => %s)"
    " WHERE outbox_id = %s AND attempts = %s AND delivered_at IS NULL"
)
DEAD = "UPDATE app.outbox SET result = 'dead_letter' WHERE outbox_id = %s AND attempts = %s AND delivered_at IS NULL"
UNNOTIFIED = (
    "SELECT o.outbox_id, o.run_id, o.attempts FROM app.outbox o WHERE o.result = 'dead_letter'"
    " AND NOT EXISTS (SELECT 1 FROM app.events e WHERE e.run_id = o.run_id AND e.type = 'notification.failed'"
    " AND e.payload->>'outbox_id' = o.outbox_id::text)"
)


@dataclass(frozen=True)
class Delivery:
    """What a sink is handed: the row, its event's type and the attempt; never the event's payload."""

    outbox_id: UUID
    tenant_id: UUID
    run_id: UUID
    event_type: str
    channel: str
    recipient: str
    attempt: int


@dataclass(frozen=True)
class Result:
    """What one claimed row came to; `recorded` is False when a newer claim had already moved the row on."""

    outbox_id: UUID
    tenant_id: UUID
    run_id: UUID
    result: str
    attempts: int
    recorded: bool


class SinkFailed(Exception):
    """The sink did not take the notification; the row is retried, or dead-lettered at its last attempt."""


class Sink(Protocol):
    """Where a notification goes (ruling 14). `deliver` raises SinkFailed when the notification was not taken."""

    async def deliver(self, delivery: Delivery) -> None:
        """Deliver one notification, or raise SinkFailed."""


def recipient_hash(recipient: str) -> str:
    """A short, stable stand-in for the recipient in logs: the subject itself never reaches a log line."""
    return hashlib.sha256(recipient.encode("utf-8")).hexdigest()[:12]


class LogSink:
    """The v1 sink: one structured log line per delivery (type, run, outbox row, a hash of the recipient), no egress
    and no payload content (BS:524's redaction holds trivially: nothing is sent)."""

    def __init__(self, faults: Faults | None = None) -> None:
        self.faults = faults  # a test-profile Faults (the factory refuses to exist elsewhere), or None

    async def deliver(self, delivery: Delivery) -> None:
        """Log the delivery; raise SinkFailed instead when the test fault is armed."""
        if self.faults is not None and self.faults.take(FaultKind.OUTBOX_SINK_FAIL):
            raise SinkFailed("the sink refused the notification (test fault)")
        log.info(
            "notification delivered: type=%s run=%s outbox=%s channel=%s recipient=%s attempt=%d",
            delivery.event_type,
            delivery.run_id,
            delivery.outbox_id,
            delivery.channel,
            recipient_hash(delivery.recipient),
            delivery.attempt,
        )


def backoff_seconds(attempts: int, chosen: OutboxSettings, rng: Callable[[], float] = random.random) -> float:
    """The wait after the `attempts`-th failure: `min(cap, base × 2^(attempts−1))` plus up to a quarter of that as
    jitter (BS:562, ruling 16), so retries of many rows do not fall due in the same instant."""
    exponential = min(chosen.backoff_cap_seconds, chosen.backoff_base_seconds * 2 ** (attempts - 1))
    return float(exponential) * (1 + 0.25 * rng())


async def _claim(conn: persistence.Conn, *, chosen: OutboxSettings) -> list[dict[str, Any]]:
    cur = await conn.execute(CLAIM, (chosen.lease_seconds, chosen.batch))
    return [dict(row) for row in await cur.fetchall()]


async def _record(
    conn: persistence.Conn, *, row: dict[str, Any], result: str, chosen: OutboxSettings, rng: Callable[[], float]
) -> bool:
    if result == "delivered":
        cur = await conn.execute(DELIVERED, (row["outbox_id"], row["attempts"]))
    elif result == "retrying":
        wait = backoff_seconds(row["attempts"], chosen, rng)
        cur = await conn.execute(RETRY, (wait, row["outbox_id"], row["attempts"]))
    else:
        cur = await conn.execute(DEAD, (row["outbox_id"], row["attempts"]))
    return cur.rowcount == 1


async def deliver(
    conn: persistence.Conn,
    sink: Sink,
    chosen: OutboxSettings,
    *,
    tenants: Sequence[UUID] | None = None,
    rng: Callable[[], float] = random.random,
) -> list[Result]:
    """Claim each tenant's due rows, deliver them outside any transaction, record each result in a unit of its own.

    Raises:
        Whatever the sink raises other than SinkFailed: the claimed rows stay leased and come back when the lease
        runs out (a crashed delivery is retried, never lost).
    """
    claimed = await for_each_tenant(conn, functools.partial(_claim, chosen=chosen), tenants=tenants)
    results: list[Result] = []
    for tenant, rows in claimed.items():
        for row in rows:
            delivery = Delivery(
                outbox_id=row["outbox_id"],
                tenant_id=tenant,
                run_id=row["run_id"],
                event_type=str(row["type"]),
                channel=str(row["channel"]),
                recipient=str(row["recipient"]),
                attempt=int(row["attempts"]),
            )
            try:
                await sink.deliver(delivery)
            except SinkFailed as exc:
                result = "dead_letter" if row["attempts"] >= chosen.max_attempts else "retrying"
                log.warning(
                    "notification not delivered: type=%s run=%s outbox=%s attempt=%d of %d (%s): %s",
                    delivery.event_type,
                    delivery.run_id,
                    delivery.outbox_id,
                    delivery.attempt,
                    chosen.max_attempts,
                    result,
                    exc,
                )
            else:
                result = "delivered"
            work = functools.partial(_record, row=row, result=result, chosen=chosen, rng=rng)
            recorded = await in_tenant(conn, tenant, work)
            results.append(Result(row["outbox_id"], tenant, row["run_id"], result, int(row["attempts"]), recorded))
    return results


async def _unnotified(conn: persistence.Conn) -> list[dict[str, Any]]:
    cur = await conn.execute(UNNOTIFIED + " ORDER BY o.created_at")
    return [dict(row) for row in await cur.fetchall()]


async def _notify(conn: persistence.Conn, *, row: dict[str, Any]) -> bool:
    # The re-check runs in the append's own transaction, so a tick that already appended the event (or a crash
    # after it) is seen here and nothing is appended twice.
    cur = await conn.execute(UNNOTIFIED + " AND o.outbox_id = %s", (row["outbox_id"],))
    if await cur.fetchone() is None:
        return False
    await persistence.append_event(
        conn,
        run_id=row["run_id"],
        type=EventType.NOTIFICATION_FAILED,
        payload={
            "code": DEAD_LETTER_CODE,
            "message": DEAD_LETTER_MESSAGE.format(attempts=row["attempts"]),
            "outbox_id": str(row["outbox_id"]),
        },
    )
    log.warning(
        "notification dead-lettered: run=%s outbox=%s attempts=%d", row["run_id"], row["outbox_id"], row["attempts"]
    )
    return True


async def notify_dead_letters(conn: persistence.Conn, *, tenants: Sequence[UUID] | None = None) -> list[UUID]:
    """Append `notification.failed` once for every dead letter that lacks it, each in its own transaction (SA:188,
    ruling 17). Returns the outbox ids announced now."""
    pending = await for_each_tenant(conn, _unnotified, tenants=tenants)
    announced: list[UUID] = []
    for tenant, rows in pending.items():
        for row in rows:
            if await in_tenant(conn, tenant, functools.partial(_notify, row=row)):
                announced.append(row["outbox_id"])
    return announced
```

Run: `uv run python -m pytest tests/plan_i/test_outbox.py tests/plan_h/test_faults_t13.py -q`
Expected: `16 passed` (the new module's 12, three of them the parametrised deliveries; Plan H's faults module's 4).

- [ ] **Step 4: The tick delivers, re-checks and records its minute**

Edit 1 (`sweeper/src/ops_sweeper/main.py`, docstring), replace:

```python
60 s holds with margin). The same tick purges expired rows and hands back the jobs whose run lease died with their
worker (T13, `leases.reclaim`). Readiness is 200 only while the last successful sync is younger than 120 s, the
window after which `grant_execution` refuses (T11 review note 2), so `scripts/skeleton.py up` waits for the first
sync. TODO(T14/T21): wake-ups, the outbox, proposal expiry.
"""
```

with:

```python
60 s holds with margin). The same tick purges expired rows, hands back the jobs whose run lease died with their
worker (T13, `leases.reclaim`) and delivers the notification outbox (T14, `outbox.deliver`, then the dead letters'
`notification.failed`), recording each minute's `deliver_outbox` job the way it records the sync. Readiness is 200
only while the last successful sync is younger than 120 s, the window after which `grant_execution` refuses (T11
review note 2), so `scripts/skeleton.py up` waits for the first sync. TODO(T21): proposal expiry.
"""
```

Edit 2 (`sweeper/src/ops_sweeper/main.py`, imports), replace:

```python
import psycopg
import uvicorn
from ops_core import keycloak_admin, persistence, redaction, settings
from ops_core.jobs import JobType
from ops_core.keycloak_admin import AdminUnavailable
from ops_core.settings import Role
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ops_sweeper import leases, sync
```

with:

```python
import psycopg
import uvicorn
from ops_core import keycloak_admin, persistence, redaction, settings
from ops_core.jobs import JobType
from ops_core.keycloak_admin import AdminUnavailable
from ops_core.settings import OutboxSettings, Role
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ops_sweeper import leases, outbox, sync
```

Edit 3 (`sweeper/src/ops_sweeper/main.py`, `Deps`), replace:

```python
    allow_mass: bool = False  # the owner's override of the listing guard, cleared by the first good sync (ruling 27)
    last_sync_at: float | None = None  # monotonic time of the last successful sync
```

with:

```python
    allow_mass: bool = False  # the owner's override of the listing guard, cleared by the first good sync (ruling 27)
    last_sync_at: float | None = None  # monotonic time of the last successful sync
    sink: outbox.Sink = field(default_factory=outbox.LogSink)  # T14: the v1 sink, no egress (Plan I ruling 14)
    outbox_settings: OutboxSettings = field(default_factory=OutboxSettings)
```

Edit 4 (`sweeper/src/ops_sweeper/main.py`, the dataclass import), replace:

```python
from dataclasses import dataclass
```

with:

```python
from dataclasses import dataclass, field
```

Edit 5 (`sweeper/src/ops_sweeper/main.py`, `tick` and `record_sync`), replace:

```python
async def tick(deps: Deps) -> None:
    """Sync; if it succeeded, record this minute's maintenance job (insert, claim, finish); purge expired rows; hand
    back the jobs of dead or lost run leases (T13), whether or not Keycloak answered."""
    if await run_sync(deps):
        await record_sync(deps)
    counts = await sync.purge_expired(deps.conn)
    if any(counts.values()):
        log.info("purged expired rows: %s", counts)
    reclaimed = await leases.reclaim(deps.conn)
    if reclaimed:
        log.info("reclaimed %d job(s) whose run lease was not live", len(reclaimed))


async def record_sync(deps: Deps) -> None:
    """The minute's `sync_memberships` row, done in the same transaction: an audit record, never a trigger."""
    async with deps.conn.transaction():
        # The bucket is a wall-clock label (the audit key); `available_at` and the claim use the application clock.
        bucket = minute_bucket(datetime.now(UTC))
        job_id = await persistence.insert_maintenance_job(deps.conn, JobType.SYNC_MEMBERSHIPS, bucket)
        if job_id is None:
            return  # another sweeper instance already recorded this minute
        job = await persistence.claim_maintenance_job(
            deps.conn, job_type=JobType.SYNC_MEMBERSHIPS, worker_name=deps.worker_name, job_id=job_id
        )
```

with:

```python
async def tick(deps: Deps) -> None:
    """Sync; if it succeeded, record this minute's maintenance job (insert, claim, finish); purge expired rows; hand
    back the jobs of dead or lost run leases (T13); deliver the outbox (T14). Everything after the sync runs whether
    or not Keycloak answered."""
    if await run_sync(deps):
        await record(deps, JobType.SYNC_MEMBERSHIPS)
    counts = await sync.purge_expired(deps.conn)
    if any(counts.values()):
        log.info("purged expired rows: %s", counts)
    reclaimed = await leases.reclaim(deps.conn)
    if reclaimed:
        log.info("reclaimed %d job(s) whose run lease was not live", len(reclaimed))
    await deliver_outbox(deps)


async def deliver_outbox(deps: Deps) -> None:
    """The outbox's delivery loop over every tenant, then `notification.failed` for every dead letter that lacks it
    (the result units first, the events after, SA:188), then this minute's `deliver_outbox` record (ruling 19)."""
    results = await outbox.deliver(deps.conn, deps.sink, deps.outbox_settings)
    announced = await outbox.notify_dead_letters(deps.conn)
    if results or announced:
        outcomes = [r.result for r in results]
        log.info(
            "outbox: %d delivered, %d retrying, %d dead-lettered, %d announced",
            outcomes.count("delivered"),
            outcomes.count("retrying"),
            outcomes.count("dead_letter"),
            len(announced),
        )
    await record(deps, JobType.DELIVER_OUTBOX)


async def record(deps: Deps, job_type: JobType) -> None:
    """The minute's maintenance row of `job_type`, done in the same transaction: an audit record, never a trigger. A
    second tick in the same minute finds the key taken and records nothing new; its work ran anyway (ruling 19)."""
    async with deps.conn.transaction():
        # The bucket is a wall-clock label (the audit key); `available_at` and the claim use the application clock.
        bucket = minute_bucket(datetime.now(UTC))
        job_id = await persistence.insert_maintenance_job(deps.conn, job_type, bucket)
        if job_id is None:
            return  # this minute is already recorded (an earlier tick, or another sweeper instance)
        job = await persistence.claim_maintenance_job(
            deps.conn, job_type=job_type, worker_name=deps.worker_name, job_id=job_id
        )
```

Edit 6 (`sweeper/src/ops_sweeper/main.py`, the record's unreachable branch), replace:

```python
            log.warning("the sync job row just inserted could not be claimed; it is left for inspection")
```

with:

```python
            log.warning("the %s job row just inserted could not be claimed; it is left for inspection", job_type.value)
```

Edit 7 (`sweeper/src/ops_sweeper/main.py`, `_main`'s start-up checks), replace:

```python
        await persistence.assert_relation(probe, "app.idempotency_request")  # revision 0006: the newest purged table
```

with:

```python
        await persistence.assert_relation(probe, "app.outbox")  # revision 0008: the outbox this process delivers
        chosen_outbox = settings.outbox()  # refused before the loop starts, like every other setting
```

Edit 8 (`sweeper/src/ops_sweeper/main.py`, `Deps` in `_main`), replace:

```python
        worker_name=f"sweeper:{socket.gethostname()}:{os.getpid()}",
        allow_mass=os.environ.get("OPS_SYNC_ALLOW_MASS_DEACTIVATION") == "1",
    )
```

with:

```python
        worker_name=f"sweeper:{socket.gethostname()}:{os.getpid()}",
        allow_mass=os.environ.get("OPS_SYNC_ALLOW_MASS_DEACTIVATION") == "1",
        sink=outbox.LogSink(),  # no fault route in any profile: the live tests build their own sink (ruling 14)
        outbox_settings=chosen_outbox,
    )
```

Edit 9 (`tests/plan_h/test_reclaim.py`, the tick test), replace:

```python
    monkeypatch.setattr(main, "run_sync", failed_sync)
    monkeypatch.setattr(sync, "purge_expired", purge)
    monkeypatch.setattr(leases, "reclaim", reclaim)
    none: Any = None
    deps = main.Deps(conn=none, admin=none, issuer="iss", tick_seconds=30.0, worker_name="sweeper:test")
    asyncio.run(main.tick(deps))
    assert calls == ["sync", "purge", "reclaim"]
```

with:

```python
    async def deliver_outbox(_deps: Any) -> None:
        calls.append("outbox")

    monkeypatch.setattr(main, "run_sync", failed_sync)
    monkeypatch.setattr(sync, "purge_expired", purge)
    monkeypatch.setattr(leases, "reclaim", reclaim)
    monkeypatch.setattr(main, "deliver_outbox", deliver_outbox)
    none: Any = None
    deps = main.Deps(conn=none, admin=none, issuer="iss", tick_seconds=30.0, worker_name="sweeper:test")
    asyncio.run(main.tick(deps))
    assert calls == ["sync", "purge", "reclaim", "outbox"]  # T14's delivery runs whether or not the sync did
```

Create `tests/plan_i/test_sweeper_tick.py`:

```python
"""The sweeper's tick after T14 (Plan I rulings 15 and 19), without a database: the outbox's delivery, then its dead
letters' events, then this minute's audit row, and the default sink.

Catches: a dead letter announced before its result unit, a maintenance row recorded before the work it records (or
not at all), and a production sink that carries a fault hook.
"""

import asyncio
from typing import Any
from uuid import UUID

import pytest
from ops_sweeper import main, outbox


def deps() -> main.Deps:
    none: Any = None
    return main.Deps(conn=none, admin=none, issuer="iss", tick_seconds=30.0, worker_name="sweeper:test")


def test_the_default_sink_is_the_log_sink_without_faults() -> None:
    sink = deps().sink
    assert isinstance(sink, outbox.LogSink) and sink.faults is None  # no fault outside a test's own sink


def test_delivery_runs_before_the_announcements_and_the_record(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []

    async def deliver(_conn: Any, _sink: Any, _chosen: Any) -> list[outbox.Result]:
        order.append("deliver")
        return []

    async def notify(_conn: Any) -> list[UUID]:
        order.append("notify")
        return []

    async def record(_deps: Any, job_type: Any) -> None:
        order.append(f"record {job_type.value}")

    monkeypatch.setattr(outbox, "deliver", deliver)
    monkeypatch.setattr(outbox, "notify_dead_letters", notify)
    monkeypatch.setattr(main, "record", record)
    asyncio.run(main.deliver_outbox(deps()))
    assert order == ["deliver", "notify", "record deliver_outbox"]
```

Run: `uv run python -m pytest tests/plan_i tests/plan_h/test_reclaim.py tests/plan_f/test_sweeper.py -q`
Expected: `82 passed` (Plan I's 71: 52 from Task 1, 5 from Task 2, the outbox's 12 and the tick's 2; the reclaim
module's 2, its tick test now patching the delivery; Plan F's sweeper module's 9, whose `Deps` gains defaulted fields).

- [ ] **Step 5: The live R024 test**

Create `tests/e2e/test_outbox_live.py`:

```python
"""T14 live (OPS_LIVE=1): the notification outbox end to end against the per-session test database, as role
`sweeper` (R024, DoD 2; Plan I rulings 13-18 and 28).

Each test builds its runs on a tenant of its own (the seeded tenant's memberships copied, so the real decision and
grant functions accept them) and delivers only that tenant, so another test's rows can neither consume an armed
fault nor be counted. R024: a run is driven to SUCCEEDED through `record_outcome`, which commits `action.confirmed`
and its intent together; delivery then fails five times on the database clock (the sink's test-profile fault, the
test clock moved past each backoff): the row goes `retrying` with its attempts counted and is finally dead-lettered,
while the run's state and events stay exactly as the outcome left them; replaying `record_outcome` and appending the
outcome event again add no second intent (the dedup key); the dead letter's `notification.failed` is not appended in
the result's transaction, and the next re-check appends it exactly once (the crash window between the two closed).
Writes evidence to reports/outbox/t14-outbox.txt (verdicts and counts; no recipient, handle or seeded tenant id).

Catches: an intent written outside the outcome's transaction or twice, a delivery failure that touches the run, a
retry that comes back before its backoff or never, a row dead-lettered early or late, a dead letter announced twice
or never, a crashed delivery that is lost instead of retried when its lease runs out, a recipient in a log line, and
a sweeper that delivers one tenant's rows under another's setting.
"""

import logging
import time
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from ops_core import persistence
from ops_core.settings import OutboxSettings, Profile, Role
from ops_core.testing.faults import FaultKind, Faults
from ops_sweeper import outbox
from psycopg.types.json import Jsonb

from tests.e2e.conftest import purge_run, purge_tenant
from tests.e2e.test_definers_run_path_live import ALPHA
from tests.e2e.test_definers_write_path_live import SAM, approve, drafting_run, freeze, handle_for
from tests.e2e.test_migrations_and_persistence import ALEX

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
EVIDENCE = Path("reports/outbox/t14-outbox.txt")
EXPECTED_LINES = 3  # one per test
# The defaults but a 60 s first backoff: a retry must stay "not due" while the test looks at it (2 s could pass),
# and every backoff stays under 375 s (60 doubling, capped at 300, plus a quarter), so a 400 s clock step makes it due.
CHOSEN = OutboxSettings(backoff_base_seconds=60)


@pytest.fixture(scope="module")
def lines() -> Iterator[list[str]]:
    out = [f"T14 outbox — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"]
    yield out
    if len(out) != 1 + EXPECTED_LINES:  # a failed or partial run leaves the committed file as it was
        return
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


async def own_tenant(app_conn: persistence.Conn) -> UUID:
    """A tenant whose memberships are the seeded tenant's, stamped now (the grant refuses stale ones)."""
    tenant = uuid4()
    await app_conn.execute("INSERT INTO app.tenants (tenant_id, name) VALUES (%s, %s)", (tenant, f"t-{tenant}"))
    await app_conn.execute(
        "INSERT INTO app.memberships (tenant_id, issuer, subject, role, active, permission_version, synced_at)"
        " SELECT %s, issuer, subject, role, active, permission_version, app.current_time() FROM app.memberships"
        " WHERE tenant_id = %s",
        (tenant, ALPHA),
    )
    return tenant


@dataclass
class Outcome:
    """A run driven to SUCCEEDED through the real definers, with what a replay of its outcome needs."""

    tenant: UUID
    run: UUID
    handle: str
    action: UUID
    document: dict[str, Any]


async def succeeded_run(app_conn: persistence.Conn, role_conn: RoleConn, tenant: UUID) -> Outcome:
    api, worker, mcp_exec = [await role_conn(r) for r in (Role.API, Role.WORKER, Role.MCP_EXEC)]
    run = await drafting_run(app_conn, api, worker, tenant)
    proposal, _, digest = await freeze(app_conn, worker, run, tenant)
    await approve(api, proposal, digest, SAM, tenant)
    handle = await handle_for(app_conn, run, "execute", expires_in=600)
    cur = await mcp_exec.execute("SELECT * FROM app.grant_execution(%s, %s)", (handle, proposal))
    action = (await cur.fetchone())["action_id"]
    assert (await (await mcp_exec.execute("SELECT app.mark_sent(%s, %s) AS r", (handle, action))).fetchone())[
        "r"
    ] == "sent"
    document = {
        "status": "SUCCEEDED",
        "action_id": str(action),
        "payload_sha256": digest,
        "receipt": {"receipt_id": str(uuid4()), "incident_id": "INC-T14", "committed_at": "2026-10-15T12:00:00Z"},
        "tombstone": None,
        "reason": None,
    }
    cur = await mcp_exec.execute(
        "SELECT app.record_outcome(%s, %s, 'SUCCEEDED', %s) AS r", (handle, action, Jsonb(document))
    )
    assert (await cur.fetchone())["r"] == "SUCCEEDED"
    return Outcome(tenant, run, handle, action, document)


async def run_view(app_conn: persistence.Conn, run: UUID) -> dict[str, Any]:
    """The run as its outcome left it: state, version and every event."""
    cur = await app_conn.execute("SELECT state, state_version FROM app.runs WHERE run_id = %s", (run,))
    row = dict(await cur.fetchone())
    cur = await app_conn.execute(
        "SELECT sequence, type, source, payload FROM app.events WHERE run_id = %s ORDER BY sequence", (run,)
    )
    return {**row, "events": [dict(e) for e in await cur.fetchall()]}


async def intents(app_conn: persistence.Conn, run: UUID) -> list[dict[str, Any]]:
    cur = await app_conn.execute(
        "SELECT o.outbox_id, e.type, o.recipient, o.dedup_key, o.attempts, o.result, o.delivered_at,"
        " o.leased_until > app.current_time() AS waiting FROM app.outbox o JOIN app.events e USING (event_id)"
        " WHERE o.run_id = %s",
        (run,),
    )
    return [dict(row) for row in await cur.fetchall()]


async def failures(app_conn: persistence.Conn, run: UUID) -> list[dict[str, Any]]:
    cur = await app_conn.execute(
        "SELECT payload FROM app.events WHERE run_id = %s AND type = 'notification.failed' ORDER BY sequence", (run,)
    )
    return [row["payload"] for row in await cur.fetchall()]


async def move_clock(harness: persistence.Conn, seconds: int) -> None:
    """The application clock's offset (AM-20.6); global, so only while no other lease or backoff in this database
    matters, and reset to 0 in `finally`."""
    await harness.execute("UPDATE app.test_clock SET clock_offset = make_interval(secs => %s)", (seconds,))


async def test_r024_a_failed_delivery_keeps_the_outcome_and_one_intent(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    sweeper, harness, mcp_exec = [await role_conn(r) for r in (Role.SWEEPER, Role.TEST_HARNESS, Role.MCP_EXEC)]
    tenant = await own_tenant(app_conn)
    staged: Outcome | None = None
    try:
        staged = await succeeded_run(app_conn, role_conn, tenant)
        run = staged.run
        before = await run_view(app_conn, run)
        assert before["state"] == "SUCCEEDED" and before["events"][-1]["type"] == "action.confirmed"
        (intent,) = await intents(app_conn, run)  # committed with the outcome (ruling 13)
        assert (intent["type"], intent["recipient"], intent["attempts"], intent["result"]) == (
            "action.confirmed",
            ALEX,
            0,
            None,
        )
        assert intent["dedup_key"] == f"{run}:action.confirmed:local:{ALEX}"
        faults = Faults(Profile.TEST)
        faults.arm(FaultKind.OUTBOX_SINK_FAIL, CHOSEN.max_attempts)
        sink = outbox.LogSink(faults)

        results = await outbox.deliver(sweeper, sink, CHOSEN, tenants=[tenant])
        assert [(r.run_id, r.result, r.attempts, r.recorded) for r in results] == [(run, "retrying", 1, True)]
        (row,) = await intents(app_conn, run)
        assert (row["attempts"], row["result"], row["delivered_at"], row["waiting"]) == (1, "retrying", None, True)
        assert await run_view(app_conn, run) == before  # the delivery result is recorded apart from the run
        assert await outbox.deliver(sweeper, sink, CHOSEN, tenants=[tenant]) == []  # inside its backoff: not due

        # The dedup key preserves the intent: a replayed outcome returns what stands and writes nothing, and the
        # outcome event appended again (inside a transaction rolled back after the check) adds an event, no intent.
        cur = await mcp_exec.execute(
            "SELECT app.record_outcome(%s, %s, 'SUCCEEDED', %s) AS r",
            (staged.handle, staged.action, Jsonb(staged.document)),
        )
        assert (await cur.fetchone())["r"] == "SUCCEEDED"
        async with app_conn.transaction(force_rollback=True):
            confirmed = before["events"][-1]
            await app_conn.execute(
                "SELECT * FROM app._append_event(%s, %s, 'action.confirmed', 'destination', %s)",
                (tenant, run, Jsonb(confirmed["payload"])),
            )
            assert len((await run_view(app_conn, run))["events"]) == len(before["events"]) + 1
            assert len(await intents(app_conn, run)) == 1
        assert await run_view(app_conn, run) == before and len(await intents(app_conn, run)) == 1

        # Attempts 2-5, each after its backoff on the database clock (400 s steps; no backoff exceeds 375 s).
        seen = [("retrying", 1)]
        for attempt in range(2, CHOSEN.max_attempts + 1):
            await move_clock(harness, 400 * (attempt - 1))
            results = await outbox.deliver(sweeper, sink, CHOSEN, tenants=[tenant])
            assert [r.attempts for r in results] == [attempt]
            seen.append((results[0].result, attempt))
        assert seen == [("retrying", 1), ("retrying", 2), ("retrying", 3), ("retrying", 4), ("dead_letter", 5)]
        assert faults.armed() == {}  # every armed failure was consumed, by this row alone
        (row,) = await intents(app_conn, run)
        assert (row["attempts"], row["result"], row["delivered_at"]) == (5, "dead_letter", None)
        await move_clock(harness, 4000)
        assert await outbox.deliver(sweeper, sink, CHOSEN, tenants=[tenant]) == []  # a dead letter is never claimed

        # The crash window: the dead letter is recorded, its event not yet (deliver() never appends). The re-check
        # of the next tick appends it once, and only once.
        assert await failures(app_conn, run) == []
        assert await outbox.notify_dead_letters(sweeper, tenants=[tenant]) == [row["outbox_id"]]
        assert await outbox.notify_dead_letters(sweeper, tenants=[tenant]) == []
        (failed,) = await failures(app_conn, run)
        assert failed["outbox_id"] == str(row["outbox_id"]) and failed["code"] == outbox.DEAD_LETTER_CODE
        after = await run_view(app_conn, run)
        assert (after["state"], after["state_version"]) == (before["state"], before["state_version"])
        assert after["events"][:-1] == before["events"]  # one event more, notification.failed, nothing else
        lines.append(
            "R024 outcome SUCCEEDED, one intent; 5 sink failures on the database clock: retrying x4, then"
            " dead_letter; run state and events unchanged; replayed outcome and re-appended event added no intent;"
            " notification.failed appended once by the re-check after the result"
        )
    finally:
        await move_clock(harness, 0)
        if staged is not None:
            await purge_run(app_conn, staged.run)
        await purge_tenant(app_conn, tenant)


async def test_a_delivered_intent_is_recorded_once_and_logged_without_its_recipient(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="ops_sweeper.outbox")
    sweeper = await role_conn(Role.SWEEPER)
    tenant = await own_tenant(app_conn)
    staged: Outcome | None = None
    try:
        staged = await succeeded_run(app_conn, role_conn, tenant)
        results = await outbox.deliver(sweeper, outbox.LogSink(), CHOSEN, tenants=[tenant])
        assert [(r.result, r.attempts, r.recorded) for r in results] == [("delivered", 1, True)]
        (row,) = await intents(app_conn, staged.run)
        assert row["result"] == "delivered" and row["delivered_at"] is not None and row["attempts"] == 1
        assert await outbox.deliver(sweeper, outbox.LogSink(), CHOSEN, tenants=[tenant]) == []  # never again
        assert await outbox.notify_dead_letters(sweeper, tenants=[tenant]) == []
        assert str(row["outbox_id"]) in caplog.text and outbox.recipient_hash(ALEX) in caplog.text
        assert ALEX not in caplog.text
        lines.append("delivered: one attempt, delivered_at set, never claimed again; the log names a recipient hash")
    finally:
        if staged is not None:
            await purge_run(app_conn, staged.run)
        await purge_tenant(app_conn, tenant)


class Crashing:
    """A sink that dies mid-delivery: not a refusal (SinkFailed), a crash."""

    async def deliver(self, delivery: outbox.Delivery) -> None:
        raise RuntimeError("the sweeper died while delivering")


async def test_a_crashed_delivery_is_claimed_again_when_its_lease_runs_out(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    sweeper, harness = await role_conn(Role.SWEEPER), await role_conn(Role.TEST_HARNESS)
    tenant = await own_tenant(app_conn)
    staged: Outcome | None = None
    try:
        staged = await succeeded_run(app_conn, role_conn, tenant)
        with pytest.raises(RuntimeError):
            await outbox.deliver(sweeper, Crashing(), CHOSEN, tenants=[tenant])
        (row,) = await intents(app_conn, staged.run)
        assert (row["attempts"], row["result"], row["waiting"]) == (1, None, True)  # claimed, leased, no result
        assert await outbox.deliver(sweeper, outbox.LogSink(), CHOSEN, tenants=[tenant]) == []  # the lease holds
        await move_clock(harness, CHOSEN.lease_seconds + 1)
        results = await outbox.deliver(sweeper, outbox.LogSink(), CHOSEN, tenants=[tenant])
        assert [(r.result, r.attempts) for r in results] == [("delivered", 2)]
        lines.append(f"crash: the claimed row came back after its {CHOSEN.lease_seconds} s lease and was delivered")
    finally:
        await move_clock(harness, 0)
        if staged is not None:
            await purge_run(app_conn, staged.run)
        await purge_tenant(app_conn, tenant)
```

Run (dev stack up, no skeleton process running):

```bash
OPS_LIVE=1 PROFILE=test PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_outbox_live.py \
  tests/e2e/test_sweeper_live.py tests/e2e/test_migration_0008_live.py -q
```

Expected: `12 passed` (the new 3, the sweeper module's 4, the 0008 module's 5), and
`reports/outbox/t14-outbox.txt` exists with four lines. This count is arithmetic, not measured: the plan's dry run
cannot run live steps.

- [ ] **Step 6: Gates and commit**

Format, lint and count characters on every file of this task.

Run: `PYTHONUTF8=1 uv run python scripts/check.py`
Expected: `CHECK: GREEN`; pytest `1021 passed, 146 skipped` (1007 + 14; the 3 new live tests skip).

Run: `PYTHONUTF8=1 uv run python scripts/check.py --profile test`
Expected: `CHECK: GREEN`; pytest `1146 passed, 21 skipped` (arithmetic, not measured: 1021 + 125 live-gated
tests). Then `git checkout -- reports/bootstrap reports/skeleton reports/auth reports/admission
reports/leases` (`reports/events` and `reports/outbox` stay for Task 6).

Run: `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`
Expected: exit 0.

```bash
git add core/src/ops_core/testing/faults.py sweeper/src/ops_sweeper tests/plan_i/test_outbox.py
git add tests/plan_h/test_faults_t13.py tests/plan_h/test_reclaim.py tests/e2e/test_outbox_live.py
git commit -m "feat(sweeper): the leased outbox delivery loop, LogSink, dead letters and notification.failed (T14)"
```

---

### Task 5: Wake-ups — the sweep that re-arms a lost one, the release that makes deferred jobs due, the purge

**Files:**
- Create: `sweeper/src/ops_sweeper/wakeups.py`, `tests/plan_i/test_wakeups.py`, `tests/e2e/test_wakeups_live.py`
- Modify: `core/src/ops_core/persistence.py:691-699` (`claim_next`'s docstring), `:775-781` (`release_lease`'s
  body), insert `pull_forward` after `unclaim_job`; `sweeper/src/ops_sweeper/main.py` (as Task 4 left it: the
  docstring, imports, `Deps`, `tick`, `_main`); `sweeper/src/ops_sweeper/leases.py:1-10` (docstring);
  `tests/plan_h/test_worker_units.py:489-504` (the release recorders and their assertion);
  `tests/plan_h/test_reclaim.py` (the tick test, as Task 4 left it); `tests/plan_i/test_sweeper_tick.py`
  (as Task 4 created it)

**Requirements:** BS:340 ("a sweeper … re-enqueues a deduplicated wake-up if a crash occurred between them"); T14's
instructions ("wake-up jobs committed with user events; sweeper"); rulings 6-11, 19, 20 and 26; the Plan F debt line
(finished maintenance rows accumulate) and the Plan H debt lines (lost wake-ups, deferred jobs waiting for a released
lease, per-tenant polling) this plan owns.

**Interfaces:**
- Consumes: `ops_core.settings.WakeupSettings`, `wakeups()` (Task 1); `ops_sweeper.tenants.for_each_tenant`,
  `in_tenant` and `ops_sweeper.main.record(deps, job_type)` (Task 4); `persistence.finish_job`, `requeue_job`,
  `revoke_handles`, `claim_next`, `acquire_lease`, `insert_job`, `release_lease`; the e2e fixtures and
  `tests.e2e.test_outbox_live.own_tenant`.
- Produces: `ops_sweeper.wakeups.WAKEUPS: tuple[tuple[str, str], ...]` (`(run state, job type)`: `("QUEUED",
  "investigate")`, `("APPROVED", "execute")`), `Wakeup(run_id, job_id, job_type, attempts, rearmed)`,
  `sweep(conn, chosen, *, tenants=None) -> list[Wakeup]`, `purge_maintenance(conn, chosen) -> int`;
  `persistence.pull_forward(conn, run_id, *, except_job) -> int`, called by `release_lease` in the job's final unit;
  `ops_sweeper.main.Deps.wakeup_settings`, `main.sweep_wakeups(deps)`.

- [ ] **Step 1: Write the failing unit tests**

Create `tests/plan_i/test_wakeups.py`:

```python
"""The wake-up sweep, the purge of finished maintenance rows and the release's pull-forward, without a database
(Plan I rulings 7, 8, 10 and 20).

Catches: a sweep that re-arms a job whose run is still being worked (a job not yet done, or one done inside the
grace), a state no handler serves yet (AWAITING_INPUT is T20's, OUTCOME_UNKNOWN T22's), a re-arm that inserts a new
row instead of reopening the old one (the dedup key is the wake-up's identity, AM-20.4), a re-arm without a bound,
a purge that could delete a run's job, and a release that leaves the run's deferred jobs waiting for a lease that is
already free, or that waits on a row another claim holds.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest
from ops_core import persistence
from ops_core.settings import WakeupSettings
from ops_sweeper import wakeups

ALPHA = uuid4()
SETTINGS = WakeupSettings()


class FakeCursor:
    def __init__(self, rows: list[dict[str, Any]], rowcount: int) -> None:
        self.rows, self.rowcount = rows, rowcount

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class FakeConn:
    """Records statements per unit; answers the sweep's scan with `lost` and every UPDATE or DELETE with `rowcount`."""

    def __init__(self, lost: list[dict[str, Any]], rowcount: int = 1) -> None:
        self.lost, self.rowcount = lost, rowcount
        self.log: list[tuple[int, str, Any]] = []
        self.unit = 0

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        self.unit += 1
        yield

    async def execute(self, statement: str, params: Any = None) -> FakeCursor:
        self.log.append((self.unit, statement, params))
        if statement.startswith("SELECT"):
            return FakeCursor(self.lost, len(self.lost))
        return FakeCursor([], self.rowcount)


@pytest.fixture(autouse=True)
def tenant_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    async def set_tenant(_conn: Any, _tenant: UUID) -> None:
        return None

    monkeypatch.setattr(persistence, "set_tenant", set_tenant)


def lost(job_type: str, attempts: int) -> dict[str, Any]:
    return {"run_id": uuid4(), "job_id": uuid4(), "job_type": job_type, "state": "QUEUED", "attempts": attempts}


def test_the_sweep_looks_only_where_a_handler_exists() -> None:
    assert wakeups.WAKEUPS == (("QUEUED", "investigate"), ("APPROVED", "execute"))  # ruling 7: T20, T21, T22 add


def test_the_scan_finds_a_runs_newest_job_done_past_the_grace() -> None:
    conn = FakeConn([])
    as_conn: Any = conn
    assert asyncio.run(wakeups.sweep(as_conn, SETTINGS, tenants=[ALPHA])) == []
    ((_, scan, params),) = conn.log
    for condition in (
        "ORDER BY jj.done_at DESC NULLS FIRST",  # an unfinished job comes first, so its run is skipped
        "j.done_at IS NOT NULL",
        "j.done_at <= app.current_time() - make_interval(secs => %s)",
        "(r.state, j.type) IN (('QUEUED', 'investigate'), ('APPROVED', 'execute'))",
    ):
        assert condition in scan, condition
    assert params == (SETTINGS.grace_seconds,)


def test_a_lost_wakeup_is_reopened_in_a_unit_of_its_own_under_the_cap() -> None:
    found = lost("investigate", 1)
    conn = FakeConn([found])
    as_conn: Any = conn
    (got,) = asyncio.run(wakeups.sweep(as_conn, SETTINGS, tenants=[ALPHA]))
    assert got == wakeups.Wakeup(found["run_id"], found["job_id"], "investigate", 1, rearmed=True)
    (scan_unit, _, _), (rearm_unit, rearm, params) = conn.log
    assert rearm_unit == scan_unit + 1
    assert rearm.startswith("UPDATE app.jobs j SET done_at = NULL, claimed_by = NULL, claimed_at = NULL")
    assert "INSERT" not in rearm and "available_at" not in rearm  # the same row, due already (erratum 62)
    assert "j.attempts < %s" in rearm and "r.state = %s" in rearm  # bounded, and the run still waits
    assert params == (found["job_id"], SETTINGS.max_attempts, "QUEUED")


def test_a_wakeup_at_its_cap_is_logged_not_reopened(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="ops_sweeper.wakeups")
    found = lost("execute", SETTINGS.max_attempts) | {"state": "APPROVED"}
    conn = FakeConn([found])
    as_conn: Any = conn
    (got,) = asyncio.run(wakeups.sweep(as_conn, SETTINGS, tenants=[ALPHA]))
    assert not got.rearmed and len(conn.log) == 1  # the scan only
    assert str(found["run_id"]) in caplog.text and "not re-armed" in caplog.text


def test_a_job_another_hand_reopened_or_moved_counts_as_not_rearmed() -> None:
    conn = FakeConn([lost("investigate", 2)], rowcount=0)  # the UPDATE's own checks found nothing to do
    as_conn: Any = conn
    (got,) = asyncio.run(wakeups.sweep(as_conn, SETTINGS, tenants=[ALPHA]))
    assert not got.rearmed


def test_the_purge_deletes_finished_maintenance_rows_past_retention_only() -> None:
    conn = FakeConn([], rowcount=3)
    as_conn: Any = conn
    assert asyncio.run(wakeups.purge_maintenance(as_conn, SETTINGS)) == 3
    ((_, purge, params),) = conn.log
    assert purge.startswith("DELETE FROM app.jobs WHERE run_id IS NULL AND done_at IS NOT NULL")
    assert "done_at < app.current_time() - make_interval(hours => %s)" in purge
    assert params == (SETTINGS.maintenance_retention_hours,)


def test_the_pull_forward_takes_only_free_rows_of_the_run() -> None:
    conn = FakeConn([], rowcount=2)
    as_conn: Any = conn
    run_id, job_id = uuid4(), uuid4()
    assert asyncio.run(persistence.pull_forward(as_conn, run_id, except_job=job_id)) == 2
    ((_, pull, params),) = conn.log
    assert pull.startswith("UPDATE app.jobs SET available_at = app.current_time()")
    for condition in (
        "run_id = %s",
        "id <> %s",
        "done_at IS NULL",
        "claimed_at IS NULL",
        "available_at > app.current_time()",
        "FOR UPDATE SKIP LOCKED",  # a row a claim holds is skipped, never waited on (ruling 22)
    ):
        assert condition in pull, condition
    assert params == (run_id, job_id)
```

Run: `uv run python -m pytest tests/plan_i/test_wakeups.py -q`
Expected: `1 error in` (collection stops: `ImportError: cannot import name 'wakeups' from 'ops_sweeper'`).

- [ ] **Step 2: The pull-forward in the job's final unit**

Edit 1 (`core/src/ops_core/persistence.py`, `claim_next`'s docstring), replace:

```python
    claims it later finds the run in the state the lease holder left. The moved job is not available again in the
    same poll, so the caller simply tries again. TODO(T14): wake-ups instead of polling.
    """
```

with:

```python
    claims it later finds the run in the state the lease holder left. The moved job is not available again in the
    same poll, so the caller simply tries again. Polling is the v1 wake mechanism (erratum 64): a job is due through
    its `available_at`, and the lease holder's release makes the run's deferred jobs due at once (`pull_forward`).
    """
```

Edit 2 (`core/src/ops_core/persistence.py`, `release_lease`'s body), replace:

```python
        await revoke_handles(conn, lease.run_id, lease.fence)
        if requeue_seconds is None:
            await finish_job(conn, job["id"])
        else:
            await requeue_job(conn, job["id"], requeue_seconds)
        await conn.execute("UPDATE app.run_lease SET lease_until = '-infinity' WHERE run_id = %s", (lease.run_id,))
    lease.mark_lost(RELEASED)
```

with:

```python
        await revoke_handles(conn, lease.run_id, lease.fence)
        if requeue_seconds is None:
            await finish_job(conn, job["id"])
        else:
            await requeue_job(conn, job["id"], requeue_seconds)
        # The lease is free from this commit on, so a job of the run that a claim deferred behind it need not wait
        # for the old lease_until (Plan I ruling 10; the abandon path does not: its lease lapses on its own).
        await pull_forward(conn, lease.run_id, except_job=job["id"])
        await conn.execute("UPDATE app.run_lease SET lease_until = '-infinity' WHERE run_id = %s", (lease.run_id,))
    lease.mark_lost(RELEASED)
```

Edit 3 (`core/src/ops_core/persistence.py`, after `unclaim_job`), replace:

```python
async def take_model_permit(conn: Conn, *, holder: str, run_id: UUID, ttl_seconds: int) -> int | None:
```

with:

```python
async def pull_forward(conn: Conn, run_id: UUID, *, except_job: UUID) -> int:
    """Make the run's other unclaimed, unfinished jobs due now when they wait for a later instant (Plan I ruling 10).

    Rows are picked with SKIP LOCKED: a row another worker's claim holds is about to be deferred by that claim (its
    NOWAIT meets this release's lease lock) and is never waited on, so this UPDATE stays outside the lock order.
    Returns how many jobs were made due.
    """
    cur = await conn.execute(
        "UPDATE app.jobs SET available_at = app.current_time() WHERE id IN (SELECT id FROM app.jobs"
        " WHERE run_id = %s AND id <> %s AND done_at IS NULL AND claimed_at IS NULL"
        " AND available_at > app.current_time() FOR UPDATE SKIP LOCKED)",
        (run_id, except_job),
    )
    return cur.rowcount


async def take_model_permit(conn: Conn, *, holder: str, run_id: UUID, ttl_seconds: int) -> int | None:
```

Edit 4 (`tests/plan_h/test_worker_units.py`, the release recorders), replace:

```python
    for name in ("set_tenant", "revoke_handles", "finish_job", "requeue_job"):
```

with:

```python
    for name in ("set_tenant", "revoke_handles", "finish_job", "requeue_job", "pull_forward"):
```

Edit 5 (`tests/plan_h/test_worker_units.py`, the release's unit), replace:

```python
    assert log.units() == [["set_tenant", "lock_lease", "revoke_handles", "finish_job", "release"]]
```

with:

```python
    # T14 (Plan I ruling 10): the run's deferred jobs are made due in the same unit, before the lease is released.
    assert log.units() == [["set_tenant", "lock_lease", "revoke_handles", "finish_job", "pull_forward", "release"]]
```

Run: `uv run python -m pytest tests/plan_h/test_worker_units.py -q`
Expected: `20 passed` (unchanged in number; the release test now sees `pull_forward` between the finish and the
release).

- [ ] **Step 3: The sweep and the purge**

Create `sweeper/src/ops_sweeper/wakeups.py`:

```python
"""The wake-up sweep and the purge of finished maintenance rows (BS:340; Plan I rulings 6-8, 20, 26; errata 61-64).

A wake-up is a job committed with the event that needs it (SA:173, BS:340): the investigate job with the run, the
execute job with the approving decision. The worker consumes a job only in its final unit, after the handler
returned; a handler that returned without moving the run (or a crash between consumption and progress) leaves the run
waiting in the job's state with the job done. The sweep finds such runs, in the states a handler serves today
(QUEUED for `investigate`, APPROVED for `execute`; AWAITING_INPUT is T20's, OUTCOME_UNKNOWN and ESCALATED are T22's),
when the newest job of the type has been done for longer than the grace, and reopens that job: its dedup key is the
wake-up's identity, so the same row is re-armed (`done_at`, `claimed_by`, `claimed_at` cleared under `sweeper_all`),
never a new one inserted (erratum 62). A job claimed `max_attempts` times is not re-armed again; the sweep logs it
on every tick instead (operator visibility through logs; metrics are T28's).

It is the sweeper's routine with direct grants, separate from the lease reclaim (erratum 63, extending erratum 49):
the reclaim hands back claimed jobs of dead leases, this reopens done jobs of stuck runs. It reads runs per tenant
(SA:520: `runs` has no sweeper policy) without a lock and re-arms each job in a unit of its own, re-checking the
run's state there. The purge deletes finished maintenance rows past their retention; a run's jobs are never deleted,
because their dedup keys are what makes a wake-up happen once.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from ops_core import persistence
from ops_core.settings import WakeupSettings

from ops_sweeper.tenants import for_each_tenant, in_tenant

log = logging.getLogger("ops_sweeper.wakeups")

# (the run's state, the job type that moves it on): the pairs whose handler exists today (ruling 7).
WAKEUPS = (("QUEUED", "investigate"), ("APPROVED", "execute"))
PAIRS = ", ".join(f"('{state}', '{job_type}')" for state, job_type in WAKEUPS)
# Each run's newest job of its state's type; an unfinished one sorts first (NULLS FIRST), so a run whose wake-up is
# still pending is never picked.
LOST = (
    "SELECT r.run_id, r.state, j.id AS job_id, j.type AS job_type, j.attempts FROM app.runs r"
    " JOIN LATERAL (SELECT jj.id, jj.type, jj.attempts, jj.done_at FROM app.jobs jj"
    " WHERE jj.run_id = r.run_id"
    " AND jj.type = CASE r.state WHEN 'QUEUED' THEN 'investigate' WHEN 'APPROVED' THEN 'execute' END"
    " ORDER BY jj.done_at DESC NULLS FIRST, jj.created_at DESC LIMIT 1) j ON true"
    f" WHERE (r.state, j.type) IN ({PAIRS})"
    " AND j.done_at IS NOT NULL AND j.done_at <= app.current_time() - make_interval(secs => %s)"
    " ORDER BY r.run_id"
)
REARM = (
    "UPDATE app.jobs j SET done_at = NULL, claimed_by = NULL, claimed_at = NULL"
    " WHERE j.id = %s AND j.done_at IS NOT NULL AND j.attempts < %s"
    " AND EXISTS (SELECT 1 FROM app.runs r WHERE r.run_id = j.run_id AND r.state = %s)"
)
PURGE = (
    "DELETE FROM app.jobs WHERE run_id IS NULL AND done_at IS NOT NULL"
    " AND done_at < app.current_time() - make_interval(hours => %s)"
)


@dataclass(frozen=True)
class Wakeup:
    """A lost wake-up the sweep found, and whether it re-armed it."""

    run_id: UUID
    job_id: UUID
    job_type: str
    attempts: int
    rearmed: bool


async def _lost(conn: persistence.Conn, *, chosen: WakeupSettings) -> list[dict[str, Any]]:
    cur = await conn.execute(LOST, (chosen.grace_seconds,))
    return [dict(row) for row in await cur.fetchall()]


async def _rearm(conn: persistence.Conn, *, row: dict[str, Any], chosen: WakeupSettings) -> bool:
    cur = await conn.execute(REARM, (row["job_id"], chosen.max_attempts, row["state"]))
    return cur.rowcount == 1


async def sweep(
    conn: persistence.Conn, chosen: WakeupSettings, *, tenants: Sequence[UUID] | None = None
) -> list[Wakeup]:
    """Find every tenant's lost wake-ups and re-arm each one under its cap, each in its own unit."""
    found = await for_each_tenant(conn, functools.partial(_lost, chosen=chosen), tenants=tenants)
    out: list[Wakeup] = []
    for tenant, rows in found.items():
        for row in rows:
            attempts = int(row["attempts"])
            if attempts >= chosen.max_attempts:
                log.warning(
                    "wake-up not re-armed: run=%s job=%s type=%s claimed %d times (cap %d)",
                    row["run_id"],
                    row["job_id"],
                    row["job_type"],
                    attempts,
                    chosen.max_attempts,
                )
                rearmed = False
            else:
                rearmed = await in_tenant(conn, tenant, functools.partial(_rearm, row=row, chosen=chosen))
            out.append(Wakeup(row["run_id"], row["job_id"], str(row["job_type"]), attempts, rearmed))
    return out


async def purge_maintenance(conn: persistence.Conn, chosen: WakeupSettings) -> int:
    """Delete the finished maintenance rows (no run) older than the retention; returns how many (ruling 20)."""
    async with conn.transaction():
        cur = await conn.execute(PURGE, (chosen.maintenance_retention_hours,))
        return cur.rowcount
```

Edit 1 (`sweeper/src/ops_sweeper/leases.py`, docstring), replace:

```python
3). Nothing else: no `recover` job (T22), no model permit work (an expired permit is free by the same comparison), no
lost wake-ups (T14).
"""
```

with:

```python
3). Nothing else: no `recover` job (T22), no model permit work (an expired permit is free by the same comparison), no
lost wake-ups (those are `wakeups.sweep`'s: it reopens done jobs of stuck runs, erratum 63).
"""
```

Run: `uv run python -m pytest tests/plan_i/test_wakeups.py -q`
Expected: `7 passed`.

- [ ] **Step 4: The tick sweeps, purges and records its minute**

Edit 1 (`sweeper/src/ops_sweeper/main.py`, docstring), replace:

```python
worker (T13, `leases.reclaim`) and delivers the notification outbox (T14, `outbox.deliver`, then the dead letters'
`notification.failed`), recording each minute's `deliver_outbox` job the way it records the sync. Readiness is 200
```

with:

```python
worker (T13, `leases.reclaim`), delivers the notification outbox (T14, `outbox.deliver`, then the dead letters'
`notification.failed`) and re-arms lost wake-ups (T14, `wakeups.sweep`, then the purge of finished maintenance rows),
recording each minute's `deliver_outbox` and `sweep_wakeups` jobs the way it records the sync. Readiness is 200
```

Edit 2 (`sweeper/src/ops_sweeper/main.py`, imports), replace:

```python
from ops_core.settings import OutboxSettings, Role
```

with:

```python
from ops_core.settings import OutboxSettings, Role, WakeupSettings
```

Edit 3 (`sweeper/src/ops_sweeper/main.py`, the module import), replace:

```python
from ops_sweeper import leases, outbox, sync
```

with:

```python
from ops_sweeper import leases, outbox, sync, wakeups
```

Edit 4 (`sweeper/src/ops_sweeper/main.py`, `Deps`), replace:

```python
    outbox_settings: OutboxSettings = field(default_factory=OutboxSettings)
```

with:

```python
    outbox_settings: OutboxSettings = field(default_factory=OutboxSettings)
    wakeup_settings: WakeupSettings = field(default_factory=WakeupSettings)
```

Edit 5 (`sweeper/src/ops_sweeper/main.py`, `tick`), replace:

```python
    back the jobs of dead or lost run leases (T13); deliver the outbox (T14). Everything after the sync runs whether
    or not Keycloak answered."""
```

with:

```python
    back the jobs of dead or lost run leases (T13); deliver the outbox and re-arm lost wake-ups (T14). Everything after
    the sync runs whether or not Keycloak answered."""
```

Edit 6 (`sweeper/src/ops_sweeper/main.py`, `tick`'s last call), replace:

```python
    await deliver_outbox(deps)


async def deliver_outbox(deps: Deps) -> None:
```

with:

```python
    await deliver_outbox(deps)
    await sweep_wakeups(deps)


async def sweep_wakeups(deps: Deps) -> None:
    """Re-arm the lost wake-ups of every tenant, purge finished maintenance rows past their retention, then record
    this minute's `sweep_wakeups` row (rulings 8, 19, 20)."""
    found = await wakeups.sweep(deps.conn, deps.wakeup_settings)
    purged = await wakeups.purge_maintenance(deps.conn, deps.wakeup_settings)
    rearmed = [w for w in found if w.rearmed]
    if rearmed:
        log.info(
            "re-armed %d lost wake-up(s): %s", len(rearmed), ", ".join(f"{w.job_type} {w.run_id}" for w in rearmed)
        )
    if purged:
        log.info("purged %d finished maintenance job row(s)", purged)
    await record(deps, JobType.SWEEP_WAKEUPS)


async def deliver_outbox(deps: Deps) -> None:
```

Edit 7 (`sweeper/src/ops_sweeper/main.py`, `_main`'s settings), replace:

```python
        chosen_outbox = settings.outbox()  # refused before the loop starts, like every other setting
```

with:

```python
        chosen_outbox = settings.outbox()  # refused before the loop starts, like every other setting
        chosen_wakeups = settings.wakeups()
```

Edit 8 (`sweeper/src/ops_sweeper/main.py`, `Deps` in `_main`), replace:

```python
        outbox_settings=chosen_outbox,
    )
```

with:

```python
        outbox_settings=chosen_outbox,
        wakeup_settings=chosen_wakeups,
    )
```

Edit 9 (`tests/plan_h/test_reclaim.py`, the tick test as Task 4 left it), replace:

```python
    async def deliver_outbox(_deps: Any) -> None:
        calls.append("outbox")

    monkeypatch.setattr(main, "run_sync", failed_sync)
    monkeypatch.setattr(sync, "purge_expired", purge)
    monkeypatch.setattr(leases, "reclaim", reclaim)
    monkeypatch.setattr(main, "deliver_outbox", deliver_outbox)
    none: Any = None
    deps = main.Deps(conn=none, admin=none, issuer="iss", tick_seconds=30.0, worker_name="sweeper:test")
    asyncio.run(main.tick(deps))
    assert calls == ["sync", "purge", "reclaim", "outbox"]  # T14's delivery runs whether or not the sync did
```

with:

```python
    async def deliver_outbox(_deps: Any) -> None:
        calls.append("outbox")

    async def sweep_wakeups(_deps: Any) -> None:
        calls.append("wakeups")

    monkeypatch.setattr(main, "run_sync", failed_sync)
    monkeypatch.setattr(sync, "purge_expired", purge)
    monkeypatch.setattr(leases, "reclaim", reclaim)
    monkeypatch.setattr(main, "deliver_outbox", deliver_outbox)
    monkeypatch.setattr(main, "sweep_wakeups", sweep_wakeups)
    none: Any = None
    deps = main.Deps(conn=none, admin=none, issuer="iss", tick_seconds=30.0, worker_name="sweeper:test")
    asyncio.run(main.tick(deps))
    assert calls == ["sync", "purge", "reclaim", "outbox", "wakeups"]  # T14's work runs whether or not the sync did
```

Edit 10 (`tests/plan_i/test_sweeper_tick.py`, the end of the file as Task 4 created it), replace:

```python
    asyncio.run(main.deliver_outbox(deps()))
    assert order == ["deliver", "notify", "record deliver_outbox"]
```

with:

```python
    asyncio.run(main.deliver_outbox(deps()))
    assert order == ["deliver", "notify", "record deliver_outbox"]


def test_the_sweep_runs_before_the_purge_and_the_record(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []

    async def sweep(_conn: Any, _chosen: Any) -> list[wakeups.Wakeup]:
        order.append("sweep")
        return []

    async def purge(_conn: Any, _chosen: Any) -> int:
        order.append("purge")
        return 0

    async def record(_deps: Any, job_type: Any) -> None:
        order.append(f"record {job_type.value}")

    monkeypatch.setattr(wakeups, "sweep", sweep)
    monkeypatch.setattr(wakeups, "purge_maintenance", purge)
    monkeypatch.setattr(main, "record", record)
    asyncio.run(main.sweep_wakeups(deps()))
    assert order == ["sweep", "purge", "record sweep_wakeups"]
```

Edit 11 (`tests/plan_i/test_sweeper_tick.py`, imports), replace:

```python
from ops_sweeper import main, outbox
```

with:

```python
from ops_sweeper import main, outbox, wakeups
```

Run: `uv run python -m pytest tests/plan_i tests/plan_h/test_reclaim.py tests/plan_h/test_worker_units.py -q`
Expected: `101 passed` (Plan I's 79: Task 4's 71, the wake-up module's 7 and the tick's third test; the reclaim
module's 2; the worker-units module's 20).

- [ ] **Step 5: The live wake-up tests**

Create `tests/e2e/test_wakeups_live.py`:

```python
"""T14 live (OPS_LIVE=1): lost wake-ups re-armed by the sweeper, deferred jobs made due by a release, and the purge of
finished maintenance rows, against the per-session test database (Plan I rulings 7, 8, 10, 20).

A lost wake-up is staged as the superuser (a job marked done while its run still waits), because no handler today
returns without moving a run except under faults this suite injects elsewhere; the sweep, the re-arm and the claim
that follows run as the real roles. Every run lives on a tenant of its own and the sweep is narrowed to it.

Catches: a wake-up re-armed inside its grace or past its cap, re-armed for a state no handler serves (AWAITING_INPUT
waits for T20), re-armed as a new row instead of the same one, not claimable once re-armed; a deferred job that
still waits for a released lease; and a purge that deletes a run's job, an unfinished maintenance row or a recent
one.
"""

import logging
from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

import pytest
from ops_core import persistence
from ops_core.jobs import JobType
from ops_core.settings import Role, WakeupSettings
from ops_sweeper import wakeups

from tests.e2e.conftest import purge_run, purge_tenant
from tests.e2e.test_definers_write_path_live import SAM, approve, drafting_run, freeze
from tests.e2e.test_migrations_and_persistence import new_run
from tests.e2e.test_outbox_live import own_tenant

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
CHOSEN = WakeupSettings()  # grace 60 s, cap 10 claims, retention 24 h


async def finish(app_conn: persistence.Conn, job: UUID, *, seconds_ago: int, attempts: int) -> None:
    """Stage a consumed wake-up: the job done `seconds_ago` on the application clock after `attempts` claims."""
    await app_conn.execute(
        "UPDATE app.jobs SET done_at = app.current_time() - make_interval(secs => %s), attempts = %s,"
        " claimed_by = 'w-gone', claimed_at = app.current_time() - make_interval(secs => %s) WHERE id = %s",
        (seconds_ago, attempts, seconds_ago, job),
    )


async def job_of(app_conn: persistence.Conn, run: UUID, job_type: str) -> UUID:
    cur = await app_conn.execute("SELECT id FROM app.jobs WHERE run_id = %s AND type = %s", (run, job_type))
    rows = await cur.fetchall()
    assert len(rows) == 1, rows
    return UUID(str(rows[0]["id"]))


async def test_a_lost_investigate_wakeup_is_rearmed_after_its_grace_and_claimed(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    sweeper, worker = await role_conn(Role.SWEEPER), await role_conn(Role.WORKER)
    tenant, _, run = await new_run(app_conn, api=await role_conn(Role.API))
    try:
        job = await job_of(app_conn, run, "investigate")
        await finish(app_conn, job, seconds_ago=10, attempts=1)  # inside the grace: the worker may be about to move
        assert await wakeups.sweep(sweeper, CHOSEN, tenants=[tenant]) == []
        await finish(app_conn, job, seconds_ago=CHOSEN.grace_seconds + 5, attempts=1)
        (found,) = await wakeups.sweep(sweeper, CHOSEN, tenants=[tenant])
        assert (found.run_id, found.job_id, found.job_type, found.rearmed) == (run, job, "investigate", True)
        cur = await app_conn.execute(
            "SELECT count(*) AS n, bool_and(done_at IS NULL AND claimed_at IS NULL) AS open FROM app.jobs"
            " WHERE run_id = %s",
            (run,),
        )
        assert dict(await cur.fetchone()) == {"n": 1, "open": True}  # the same row, reopened (erratum 62)
        assert await wakeups.sweep(sweeper, CHOSEN, tenants=[tenant]) == []  # pending again: not lost
        claimed = await persistence.claim_next(worker, worker_name="w-next", tenant_ids=[tenant], lease_seconds=30)
        assert isinstance(claimed, persistence.Claimed) and claimed.job["id"] == job and claimed.job["attempts"] == 2
        await persistence.release_lease(worker, claimed.lease, job=dict(claimed.job))
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


async def test_an_approved_runs_execute_wakeup_stops_at_its_cap(
    app_conn: persistence.Conn, role_conn: RoleConn, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="ops_sweeper.wakeups")
    sweeper, api, worker = await role_conn(Role.SWEEPER), await role_conn(Role.API), await role_conn(Role.WORKER)
    tenant = await own_tenant(app_conn)
    run: UUID | None = None
    try:
        run = await drafting_run(app_conn, api, worker, tenant)
        proposal, _, digest = await freeze(app_conn, worker, run, tenant)
        await approve(api, proposal, digest, SAM, tenant)
        job = await job_of(app_conn, run, JobType.EXECUTE.value)
        await finish(app_conn, job, seconds_ago=120, attempts=CHOSEN.max_attempts)
        (found,) = await wakeups.sweep(sweeper, CHOSEN, tenants=[tenant])
        assert (found.job_id, found.rearmed) == (job, False) and "not re-armed" in caplog.text
        cur = await app_conn.execute("SELECT done_at IS NOT NULL AS done FROM app.jobs WHERE id = %s", (job,))
        assert (await cur.fetchone())["done"]
        await finish(app_conn, job, seconds_ago=120, attempts=CHOSEN.max_attempts - 1)
        (found,) = await wakeups.sweep(sweeper, CHOSEN, tenants=[tenant])
        assert found.rearmed
    finally:
        if run is not None:
            await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


async def test_a_state_without_a_handler_is_not_swept(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    """Ruling 7: AWAITING_INPUT's reply job is T20's to handle, so its consumption is not a lost wake-up here."""
    sweeper, worker = await role_conn(Role.SWEEPER), await role_conn(Role.WORKER)
    tenant, _, run = await new_run(app_conn, api=await role_conn(Role.API))
    try:
        await worker.execute("SELECT app.transition_run(%s, 'QUEUED', 'RETRIEVING', NULL, 1, '{}')", (run,))
        await worker.execute("SELECT app.transition_run(%s, 'RETRIEVING', 'AWAITING_INPUT', NULL, 2, '{}')", (run,))
        resume = await persistence.insert_job(
            app_conn, job_type=JobType.RESUME_INPUT, run_id=run, clarification_event_id=uuid4()
        )
        assert resume is not None
        await finish(app_conn, resume, seconds_ago=600, attempts=1)
        await finish(app_conn, await job_of(app_conn, run, "investigate"), seconds_ago=600, attempts=1)
        assert await wakeups.sweep(sweeper, CHOSEN, tenants=[tenant]) == []
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


async def test_a_release_makes_the_runs_deferred_job_due_at_once(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """Ruling 10: a job deferred behind a 30 s lease is claimable the moment the holder releases, not 30 s later."""
    a, b = await role_conn(Role.WORKER), await role_conn(Role.WORKER)
    tenant, _, run = await new_run(app_conn, api=await role_conn(Role.API))
    try:
        first = await persistence.claim_next(a, worker_name="wa", tenant_ids=[tenant], lease_seconds=30)
        assert isinstance(first, persistence.Claimed)
        resume = await persistence.insert_job(
            app_conn, job_type=JobType.RESUME_INPUT, run_id=run, clarification_event_id=uuid4()
        )
        assert await persistence.claim_next(b, worker_name="wb", tenant_ids=[tenant], lease_seconds=30) == (
            persistence.Deferred(resume)
        )
        cur = await app_conn.execute(
            "SELECT available_at > app.current_time() + interval '20 seconds' AS behind FROM app.jobs WHERE id = %s",
            (resume,),
        )
        assert (await cur.fetchone())["behind"]  # behind the live lease
        await persistence.release_lease(a, first.lease, job=dict(first.job))
        second = await persistence.claim_next(b, worker_name="wb", tenant_ids=[tenant], lease_seconds=30)
        assert isinstance(second, persistence.Claimed) and second.job["id"] == resume
        assert second.lease.fence == first.lease.fence + 1
        await persistence.release_lease(b, second.lease, job=dict(second.job))
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


async def test_the_purge_deletes_old_finished_maintenance_rows_only(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    sweeper = await role_conn(Role.SWEEPER)
    tenant, _, run = await new_run(app_conn, api=await role_conn(Role.API))
    keys = {name: f"sync_memberships:t14-{name}-{uuid4()}" for name in ("old", "recent", "open")}
    try:
        for name, done, created in (
            ("old", "25 hours", "25 hours"),
            ("recent", "1 hour", "1 hour"),
            ("open", None, "30 hours"),
        ):
            await app_conn.execute(
                "INSERT INTO app.jobs (id, type, dedup_key, available_at, created_at, done_at)"
                " VALUES (gen_random_uuid(), 'sync_memberships', %s, app.current_time(),"
                " app.current_time() - %s::interval, app.current_time() - %s::interval)",
                (keys[name], created, done),
            )
        run_job = await job_of(app_conn, run, "investigate")
        await finish(app_conn, run_job, seconds_ago=30 * 3600, attempts=1)  # a run's job: never purged
        assert await wakeups.purge_maintenance(sweeper, CHOSEN) >= 1
        cur = await app_conn.execute("SELECT dedup_key FROM app.jobs WHERE dedup_key = ANY(%s)", (list(keys.values()),))
        assert sorted(row["dedup_key"] for row in await cur.fetchall()) == sorted([keys["recent"], keys["open"]])
        cur = await app_conn.execute("SELECT count(*) AS n FROM app.jobs WHERE id = %s", (run_job,))
        assert (await cur.fetchone())["n"] == 1
    finally:
        await app_conn.execute("DELETE FROM app.jobs WHERE dedup_key = ANY(%s)", (list(keys.values()),))
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)
```

Run (dev stack up, no skeleton process running):

```bash
OPS_LIVE=1 PROFILE=test PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_wakeups_live.py \
  tests/e2e/test_leases_live.py tests/e2e/test_worker_live.py tests/e2e/test_sweeper_live.py -q
```

Expected: `24 passed` (the new 5; the leases module's 11, whose releases now also pull deferred jobs forward and
whose R087 test still sees the original job claimed; the worker module's 4; the sweeper module's 4). This count is
arithmetic, not measured: the plan's dry run cannot run live steps.

- [ ] **Step 6: Gates and commit**

Format, lint and count characters on every file of this task.

Run: `PYTHONUTF8=1 uv run python scripts/check.py`
Expected: `CHECK: GREEN`; pytest `1029 passed, 151 skipped` (1021 + 8; the 5 new live tests skip).

Run: `PYTHONUTF8=1 uv run python scripts/check.py --profile test`
Expected: `CHECK: GREEN`; pytest `1159 passed, 21 skipped` (arithmetic, not measured: 1029 + 130 live-gated
tests). Then `git checkout -- reports/bootstrap reports/skeleton reports/auth reports/admission
reports/leases`.

Run: `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`
Expected: exit 0.

```bash
git add core/src/ops_core/persistence.py sweeper/src/ops_sweeper tests/plan_i tests/plan_h/test_worker_units.py
git add tests/plan_h/test_reclaim.py tests/e2e/test_wakeups_live.py
git commit -m "feat(sweeper): re-arm lost wake-ups and purge maintenance rows; releases make deferred jobs due (T14)"
```

---

### Task 6: Close-out — records, acceptance rows, errata 60-71, the runbook, final gates

**Files:**
- Create: `docs/runbooks/events-and-outbox.md`
- Modify: `handoff/tasks.json` (T14 → `DONE`, one review note), `handoff/acceptance-matrix.json` (R024, R089),
  `handoff/BUILD_BACKLOG.md` (T14 checked, one review note), `SESSION_STATE.md` (the "Next task" line, the repository
  line, a "Plan I executed" section, the dev database state, the owner inputs), `STATUS.md` (an update section),
  `docs/ARCHITECTURE.md` (a new section before "Where the code will live"), `docs/PROJECT_HISTORY.md` (the journal
  plan's section), `README.md:5` (status line), `worker/README.md` (the "Runs" section), `sweeper/README.md` (the
  first line, "Owns", "Never" and "Runs"), this plan (its checkboxes); the evidence files `reports/events/*.txt`,
  `reports/outbox/*.txt` and the rewritten `reports/admission`, `reports/skeleton`, `reports/leases` from the final
  live run

**Requirements:** the T14 record (R024, R089 evidenced); every `TODO(T14)` in code has a new owner. This task writes
no code.

Throughout, `<base>..<last>` is the git range of this plan's execution on `plan-i`, written as two short hashes:
`<base>` is the `BASE` recorded in Task 1 Step 1b (excluded by the range) and `<last>` the newest commit before this
task's own (`LAST=$(git rev-parse --short HEAD)`, run before this task commits). `<date>` is `date -u +%F` on the day
of the close-out.

- [ ] **Step 1: No `TODO(T14)` is left in live code**

Run:

```bash
git grep -n "TODO(T14" -- core api worker sweeper mcp-write mcp-read incident-sim scripts tests migrations
git grep -n "T14" -- sweeper/README.md worker/README.md
```

Expected: the first command prints nothing (Task 1 moved `outcomes.Event`'s to T26; Task 4 rewrote the sweeper's to
T21; Task 5 rewrote `claim_next`'s as erratum 64; Task 2 removed the matrix docstring's and the lock order's
forward references; the applied revisions 0002-0007 carry no `TODO(T14)`). The second prints one line,
`sweeper/README.md:23:Wake-ups, the outbox and proposal expiry: T14/T21.`, which Step 4 rewrites. If the first
prints a line, give that TODO its owner from the debt list (T20, T21, T22, T26, T27, T28, T30, T32, T39, T45 or T47)
in a separate commit before continuing.

- [ ] **Step 2: Handoff records**

Run this once from the repository root, with `BASE` set to the hash Task 1 Step 1b recorded (it rewrites the two JSON
files in their own format: two-space indent, non-ASCII kept, one trailing newline):

```bash
BASE=<the hash recorded in Task 1 Step 1b> uv run python - <<'EOF'
import json
import os
import subprocess
from pathlib import Path

base = os.environ["BASE"]
last = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True).stdout
subprocess.run(["git", "merge-base", "--is-ancestor", base, "HEAD"], check=True)  # the base is this branch's own
span = f"{base}..{last.strip()}"
note = (
    f"Plan I (branch plan-i): done in {span} (the debt list, then the five tasks; plan "
    "docs/superpowers/plans/2026-10-15-first-slice-i-journal-wakeups-outbox.md). Shipped: the gap-free journal proved, "
    "not redesigned (revision 0003's runs-row lock, next_event_seq + 1 and the insert in the caller's transaction): "
    "stepped interleavings of the worker's transition_run against the API's append_event and mcp-write's mark_sent "
    "against the sweeper's append_event, a rolled-back writer that leaves its number to the next one, and a 10 s "
    "stress run of eight connections of the four roles with rollbacks while a cursor reader on the events route "
    "and a counting reader never saw a hole; _append_event's payload rules (keys closed over the event schema's "
    "thirteen, which gained question_id, message_id and outbox_id; a status only on the destination's four types) "
    "mirrored in event_rules_ok and the schema (rule 9) on one table of cases; app.outbox (revision 0008) with the "
    "intent written inside _append_event for action.confirmed, action.failed, run.escalated and "
    "run.abandoned_unverified, deduplicated by run:type:channel:recipient; the sweeper's tenant iteration; the "
    "leased delivery loop (claim with SKIP LOCKED and a 30 s lease, delivery outside any transaction to LogSink, "
    "result in its own unit, capped jittered backoff, dead letter at the fifth failure, notification.failed in a "
    "separate transaction with a re-check every tick); the outbox_sink_fail fault (test profile, sink factory "
    "argument); the wake-up sweep re-arming QUEUED/investigate and APPROVED/execute jobs done past a 60 s grace "
    "under a 10-claim cap; the release making the run's deferred jobs due at once; the deliver_outbox and "
    "sweep_wakeups audit rows; the purge of finished maintenance rows (the sweeper's DELETE on jobs); a catalog "
    "test that no function an MCP server may call inserts a job. Evidence: tests/e2e/test_event_journal_live.py, "
    "test_outbox_live.py, test_wakeups_live.py, test_migration_0008_live.py and reports/events/, reports/outbox/ "
    "(live), tests/plan_i/ for the unit half. Deferred: resume_input handling and the AWAITING_INPUT sweep -> T20; "
    "recover handling and the OUTCOME_UNKNOWN/ESCALATED sweep -> T22; R023's decision crash test -> T21; "
    "outcomes.Event on the read path -> T26; SSE and Last-Event-ID -> T27; retention -> T32; a real channel -> T39. "
    "Errata 60-71 are proposed in SESSION_STATE.md."
)
tasks_path = Path("handoff/tasks.json")
tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
t14 = next(t for t in tasks["tasks"] if t["id"] == "T14")
t14["status"] = "DONE"
t14["review_notes"].append(note)
tasks_path.write_text(json.dumps(tasks, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

matrix_path = Path("handoff/acceptance-matrix.json")
matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
evidence = {
    "R024": [
        "tests/e2e/test_outbox_live.py",
        "reports/outbox/t14-outbox.txt",
        "tests/e2e/test_migration_0008_live.py",
        "tests/plan_i/test_outbox.py",
        "tests/plan_i/test_migration_0008.py",
    ],
    "R089": [
        "tests/e2e/test_event_journal_live.py",
        "reports/events/t14-events.txt",
        "tests/plan_i/test_locking_t14.py",
    ],
}
notes = {
    "R024": "Plan I (T14): a run is driven to SUCCEEDED through record_outcome, which commits action.confirmed and "
    "its notification intent in one transaction; the sink's test-profile fault fails five deliveries on the "
    "database clock: the row goes retrying with its attempts counted, then dead_letter, while the run's state and "
    "events stay as the outcome left them (the delivery result is recorded on the outbox row, apart from the run); "
    "a replayed record_outcome and a re-appended action.confirmed add no second intent (dedup key "
    "run:type:channel:recipient); notification.failed is appended once, in a transaction after the result, by the "
    "re-check that also closes the crash window between the two. No external channel: the sink is a log line.",
    "R089": "Plan I (T14): the sequence comes from runs.next_event_seq under the runs row lock in the writer's "
    "transaction (revision 0003, unchanged). Stepped live tests hold writer A's sequence n uncommitted and show "
    "with pg_blocking_pids that writer B waits on A, for the worker's transition_run against the API's append_event "
    "and mcp-write's mark_sent against the sweeper's append_event, while the events route (the after cursor of "
    "GET /api/v1/runs/{id}/events) returns n only after A commits and n + 1 only after B commits; a writer that "
    "rolls back leaves its number to the waiting writer; a 10 s stress run of eight connections of the four roles "
    "on three runs, about half of the transactions rolled back, ends with every run exactly 1..next_event_seq while a "
    "cursor reader never skipped and a counting reader never saw a hole, with no 40P01 and no 55P03. SSE and "
    "Last-Event-ID replay are T27's.",
}
for row in matrix["requirements"]:
    if row["id"] in evidence:
        row["implementation_status"] = "IMPLEMENTED_LOCALLY_VERIFIED"
        row["evidence_status"] = "RECORDED_LOCALLY_LIVE"
        row["evidence_paths"] = evidence[row["id"]]
        row["note"] = notes[row["id"]]
matrix_path.write_text(json.dumps(matrix, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

backlog_path = Path("handoff/BUILD_BACKLOG.md")
backlog = backlog_path.read_text(encoding="utf-8")
head = "- [ ] **T14 Gap-free event journal, wake-ups and outbox**"
assert backlog.count(head) == 1
backlog = backlog.replace(head, "- [x] **T14 Gap-free event journal, wake-ups and outbox**")
lines = backlog.split("\n")
at = next(i for i, line in enumerate(lines) if line.startswith("- [x] **T14 "))
end = at + 1
while end < len(lines) and lines[end].startswith("  - "):
    end += 1
lines.insert(end, f"  - *Review note:* {note}")  # after the task's other notes, as tasks.json appends it
backlog_path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
print(span)
EOF
```

Expected: it prints the span (for example `1a2b3c4..5d6e7f8`). `git diff --stat handoff` shows three files changed;
`git diff handoff/acceptance-matrix.json` shows only two rows: R024 and R089.

- [ ] **Step 3: Project state**

In `SESSION_STATE.md`:

Edit 1 (`SESSION_STATE.md`, the "Next task" line), replace:

```markdown
**Next task:** Plan H (T13) is executed on branch `plan-h` (`c5eeb89..06e961a`, on top of `plan-g`: the eight tasks, the close-out `e9d624d` and `6fd1ec3`, and the final-review fix `06e961a`; the docs commit recording that fix sits on top). Owner inputs: (1) the holdout seal (T03 step 9), then the live probe (T02); (2) merge the stacked PRs in order and open the plan-h -> plan-g PR; (3) T44 step 10 (`docs/runbooks/ollama-network.md` step A); (4) decide the proposed errata of Plans C, E, F, G and H (H: 45-59 below); (5) migrate the dev database to revision 0007 (`uv run python scripts/skeleton.py migrate`, dev profile: from 0005 it applies 0006 and 0007 together; 0007 adds `app.model_permit` and the `jobs.type` CHECK, re-creates the handle functions and deletes nothing). Next is the earliest dependency-satisfied task in `handoff/tasks.json` after T13 (T14: gap-free event journal, wake-ups and the outbox; T15 also became unblocked).
```

with:

```markdown
**Next task:** Plan I (T14) is executed on branch `plan-i` (`<base>..<last>`, on top of `plan-h`: the debt list and
the five tasks; the close-out commit follows). Owner inputs: (1) the holdout seal (T03 step 9), then the live probe
(T02); (2) merge the stacked PRs in order and open the plan-h -> plan-g and plan-i -> plan-h PRs; (3) T44 step 10
(`docs/runbooks/ollama-network.md` step A); (4) decide the proposed errata of Plans C, E, F, G, H and I (I: 60-71
below); (5) migrate the dev database to revision 0008 (`uv run python scripts/skeleton.py migrate`, dev profile: from
0005 it applies 0006, 0007 and 0008 together; 0008 adds `app.outbox`, gives the sweeper DELETE on `jobs` and
re-creates `_append_event` with the payload rules; it deletes nothing). Next is the earliest dependency-satisfied
task in `handoff/tasks.json` after T14 (T15, unblocked by T13; T14 also unblocks T20 and T27 once their other
dependencies are done).
```

Edit 2 (`SESSION_STATE.md`, the repository line), replace:

```markdown
**Repository:** local git repo at `C:\Users\joeys\Desktop\MLOps`, branch `plan-h` (Plan H work on top of `plan-g`, on top of `plan-f`, on top of `plan-e`, on top of `plan-d`, on top of `plan-c`, on top of `plan-b`, on top of `plan-a`). Remote `github.com/jschnepel/MLOps` (public, MIT) exists; `main` and `plan-a` were pushed on 2026-10-07. `plan-b` to `plan-e` were pushed on 2026-10-08 and `plan-f` on 2026-10-09 (`origin/plan-e` is two docs commits behind local `plan-e`; a `git push origin plan-e` brings it level before the plan-f -> plan-e PR). PRs #1-#5 were opened on 2026-10-09 and are green after the EXE001 fix (first green run https://github.com/jschnepel/MLOps/actions/runs/37962510516; record `reports/ci/t06-first-ci-runs.txt`). Merging them in order is the owner's call.
```

with:

```markdown
**Repository:** local git repo at `C:\Users\joeys\Desktop\MLOps`, branch `plan-i` (Plan I work on top of `plan-h`, on top of `plan-g`, on top of `plan-f`, on top of `plan-e`, on top of `plan-d`, on top of `plan-c`, on top of `plan-b`, on top of `plan-a`). Remote `github.com/jschnepel/MLOps` (public, MIT) exists; `main` and `plan-a` were pushed on 2026-10-07. `plan-b` to `plan-e` were pushed on 2026-10-08 and `plan-f` on 2026-10-09 (`origin/plan-e` is two docs commits behind local `plan-e`; a `git push origin plan-e` brings it level before the plan-f -> plan-e PR). PRs #1-#5 were opened on 2026-10-09 and are green after the EXE001 fix (first green run https://github.com/jschnepel/MLOps/actions/runs/37962510516; record `reports/ci/t06-first-ci-runs.txt`). Merging them in order is the owner's call.
```

Edit 3 (`SESSION_STATE.md`, before the walking-skeleton debt list), replace:

```markdown
## Walking-skeleton debt list (T08; committed before coding) [R6-B7]
```

with:

```markdown
## Plan I executed (<date>, branch `plan-i`)

- T14 = `<base>..<last>` (the debt list first, then the five tasks). The plan
  (`docs/superpowers/plans/2026-10-15-first-slice-i-journal-wakeups-outbox.md`) holds the 29 rulings of the
  controller's brief as implemented; the input is `docs/superpowers/research/2026-10-15-plan-i-inputs.md`.
  Evidence: `tests/e2e/test_event_journal_live.py` (R089: the stepped writers of four roles, the rollback, the
  stress run with its readers), `test_outbox_live.py` (R024, the delivered row, the crashed delivery),
  `test_wakeups_live.py`, `test_migration_0008_live.py` (the round trip, the payload table in SQL, the intent, the
  outbox grants, the MCP catalog check) and `reports/events/t14-events.txt`, `reports/outbox/t14-outbox.txt`; the
  unit half is in `tests/plan_i/`.
- Gates: `check.py` <dev passed> passed / <dev skipped> skipped; `check.py --profile test` <live passed> passed / 21
  skipped (the plan's tails are 1029/151 and 1159/21); `verify_handoff.py` exit 0 (STATUS.md, "Update — Plan I
  executed").
- **Proposed errata (the owner decides; the spec text stays authoritative until then).** Numbered on from Plan H's
  fifty-nine:
  60. SA:427 (AM-20.2 `outbox`): `outbox(outbox_id, tenant_id, run_id, event_id → events, channel 'local',
      recipient, dedup_key UNIQUE, attempts, leased_until, delivered_at, result ∈ {delivered, retrying,
      dead_letter}, created_at)` with the composite key to `runs` and `tenant_isolation` only; `leased_until` is
      both the claim's lease and the next attempt's time; `app_definer` `ins`, the sweeper `sel, upd(leased_until,
      attempts, delivered_at, result)`, and `api` and `worker` no cell (only `_append_event` writes intent).
  61. SA:419 (`jobs`): the sweeper holds DELETE, used only for finished maintenance rows older than
      `OPS_MAINTENANCE_RETENTION_HOURS` (24); a run's job is never deleted.
  62. AM-20.4 (SA:500-505) and SA:345: the sweeper re-arms a lost wake-up by reopening its job (the same row and
      dedup key); it never inserts a `resume_input` or `execute` row.
  63. SA:471 (extending erratum 49): lost wake-ups are re-armed by `wakeups.sweep`, a sweeper routine with direct
      grants separate from the lease reclaim, for QUEUED runs whose `investigate` jobs and APPROVED runs whose
      `execute` jobs are all done, past a 60 s grace (`OPS_WAKEUP_GRACE_SECONDS`) and below a 10-claim cap
      (`OPS_WAKEUP_MAX_ATTEMPTS`); past the cap it logs instead.
  64. BS:340 and the polling debt of Plans E and H: a wake-up is the job committed with its user event, plus the
      sweep; there is no LISTEN/NOTIFY; the worker's 0.5 s per-tenant poll is the v1 wake mechanism, and a lease's
      release makes the run's deferred jobs due at once.
  65. SA:452 and AM-80's event schema: `_append_event` refuses (OC006) a payload key outside the event schema's
      thirteen (the schema gains `question_id`, `message_id`, `outbox_id`) and a `status` on any type but the
      destination's four (schema rule 9); `event_rules_ok` mirrors both, on one table of cases.
  66. BS:524 (intent): notification intent is written inside `_append_event`, in the event's transaction, for
      `action.confirmed`, `action.failed`, `run.escalated` and `run.abandoned_unverified`; the recipient is the
      run's requester, the channel `local`, the dedup key `run_id:type:channel:recipient` with a target-less
      `ON CONFLICT DO NOTHING`.
  67. BS:524 (delivery): the sweeper's tick claims each tenant's due rows (`FOR UPDATE SKIP LOCKED`, a 30 s lease,
      `OPS_OUTBOX_BATCH` 10), delivers outside any transaction to `LogSink` (one log line, no egress), and records
      each result in its own unit; the backoff is `min(300, 2 × 2^(n−1))` s plus up to 25 % jitter; the fifth
      failure dead-letters; `outbox_sink_fail` is the sink's test-profile fault.
  68. SA:188 and BS:514: `notification.failed` (payload `code`, `message`, `outbox_id`) is appended once per dead
      letter in a separate transaction after the result unit, and every tick re-checks the dead letters that lack
      it.
  69. SA:520: the sweeper iterates `tenants` and runs per-tenant work in one transaction per tenant
      (`ops_sweeper.tenants.for_each_tenant`): the delivery and the wake-up sweep now, T21's expiry and T22's
      deadline escalation later.
  70. SA:504: the `deliver_outbox` and `sweep_wakeups` rows are audit records like `sync_memberships`' (inserted,
      claimed and finished in one transaction per minute; the work runs outside it, and a second tick in the minute
      records nothing new).
  71. SA:188 (extending erratum 52): `_append_event` takes `runs → events → outbox`; the delivery's claim and result
      units lock `outbox` only; `notification.failed` takes `runs` in a unit of its own; the re-arm and the purge
      lock `jobs` at the finish position; the release's pull-forward picks with SKIP LOCKED.
- Earlier debt lines that named T14 and what became of them: the gap-free sequence is proved (walking-skeleton and
  Plan D lines); the outbox and its grant row are done (Plan E); `sweep_wakeups`, `deliver_outbox` and the purge of
  finished maintenance jobs are done (Plan F); lost wake-ups are re-armed by the sweep (Plan H; recover jobs stay
  T22's); a deferred job no longer waits for a released lease (Plan H); polling and per-tenant claims are kept as the
  v1 wake mechanism (erratum 64, Plans E and H); `_idempotent`'s "use a new key" answer for a key that just became
  reusable stays harmless and moves to T28's polish.
```

Edit 4 (`SESSION_STATE.md`, the dev database state), replace:

```markdown
has one of the eight types), grants `app_definer` UPDATE on `run_lease.fence`, and re-creates the handle functions
with the fence check; it deletes nothing.

## Open owner inputs
```

with:

```markdown
has one of the eight types), grants `app_definer` UPDATE on `run_lease.fence`, and re-creates the handle functions
with the fence check; it deletes nothing.

**Update (<date>):** Plan I adds revision 0008. The dev `ops` database stays at 0005 until the owner runs
`uv run python scripts/skeleton.py migrate` (dev profile), which applies 0006, 0007 and 0008 together; until then the
sweeper also refuses to start (it needs `app.outbox`). 0008 creates `app.outbox` (empty), gives the sweeper DELETE on
`jobs`, and re-creates `_append_event` with the payload rules and the notification intent; every event the dev
database holds was written under the old rules and stays as it is (the rules apply to new events); it deletes nothing.

## Open owner inputs
```

Edit 5 (`SESSION_STATE.md`, the first owner input), replace:

```markdown
- Migrate the dev database to revision 0007 (`uv run python scripts/skeleton.py migrate`, dev profile; it applies 0006
  and 0007 together), then decide errata 35-44 (see "Plan G executed") and 45-59 (see "Plan H executed").
```

with:

```markdown
- Migrate the dev database to revision 0008 (`uv run python scripts/skeleton.py migrate`, dev profile; it applies
  0006, 0007 and 0008 together), then decide errata 35-44 (see "Plan G executed"), 45-59 (see "Plan H executed") and
  60-71 (see "Plan I executed").
```

Then finish the "Plan I executed" section with two bullets only execution can write, inserted after its last bullet:
`- Rulings made during execution:` (one line each, with its reason; or `- Rulings made during execution: none beyond
the plan.`) and `- **Open items for later:**` (from the SDD ledger
`.superpowers/sdd/2026-10-15-first-slice-i-journal-wakeups-outbox/progress.md`; or `- **Open items for later:** none
recorded.`).

- [ ] **Step 4: Status, history, the runbook and the documents**

Edit 1 (`STATUS.md`, its last lines), replace:

```markdown
  (T30), the permit wait counted in the compute budget (T29) and lease loss visible only in logs (T28) are debt
  lines; erratum 59 was judged sound.
```

with:

```markdown
  (T30), the permit wait counted in the compute budget (T29) and lease loss visible only in logs (T28) are debt
  lines; erratum 59 was judged sound.


## Update — Plan I executed (<date>, branch `plan-i`)

- Plan I (T14: the gap-free event journal, wake-ups and the outbox) executed on branch `plan-i` (`<base>..<last>`, on
  top of `plan-h`). The plan is `docs/superpowers/plans/2026-10-15-first-slice-i-journal-wakeups-outbox.md`.
- `PYTHONUTF8=1 uv run python scripts/check.py` is `CHECK: GREEN`: pytest `<dev passed> passed, <dev skipped>
  skipped`. `PYTHONUTF8=1 uv run python scripts/check.py --profile test` is `CHECK: GREEN`: pytest `<live passed>
  passed, 21 skipped`. `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts` exits 0.
- **Evidenced** (acceptance matrix `RECORDED_LOCALLY_LIVE` / `IMPLEMENTED_LOCALLY_VERIFIED`): R024 and R089. A
  delivery that fails after the outcome committed leaves the run's state and events untouched, retries on a capped,
  jittered backoff, dead-letters at the fifth failure and announces it once with `notification.failed`; a replayed
  outcome adds no second intent. Writers of all four roles take gap-free, commit-ordered sequences: a second writer
  waits on the first's run lock (shown with `pg_blocking_pids`), the events route never returns n + 1 before n, a
  rolled-back writer leaves its number to the next one, and a 10 s stress run of eight connections with rollbacks
  ends with every run exactly 1..next_event_seq (`reports/events/`, `reports/outbox/`). SSE replay is T27's.
- Also built: the payload rules in `_append_event` (closed keys, a status only from the destination), in the schema
  and in `event_rules_ok`; the wake-up sweep; releases that make deferred jobs due at once; the purge of finished
  maintenance rows; the catalog check that no MCP-callable function inserts a job.
- The dev `ops` database needs revisions 0006, 0007 and 0008 (an owner input); the API, the sweeper, the worker and
  mcp-write refuse to start until then.
- Deferred, each with its owner in `SESSION_STATE.md`: resume_input handling -> T20; recover handling -> T22; R023's
  crash test -> T21; `outcomes.Event` on the read path -> T26; SSE -> T27; dashboards -> T28/T29; retention -> T32;
  a real channel -> T39. Twelve errata (60-71) are proposed.
```

Create `docs/runbooks/events-and-outbox.md`:

````markdown
# The event journal, wake-ups and the notification outbox (T14)

Who this is for: whoever reads a run's events, runs the sweeper, or debugs a run that seems stuck or a notification
that never arrived. The design is AM-12, AM-14 and AM-20 in `SPEC_AMENDMENTS.md`, BUILD_SPEC §8 and §15, and Plan I
(`docs/superpowers/plans/2026-10-15-first-slice-i-journal-wakeups-outbox.md`).

## The event journal

- **Every event goes through `app._append_event`**, inside the writer's transaction: it locks the run row `FOR
  UPDATE`, takes `runs.next_event_seq + 1` and inserts the event. A second writer of the same run waits for the
  first to commit or roll back, so a run's sequences are gap-free (1, 2, 3, … with no hole) and commit-ordered: a
  reader never sees n + 1 before n. A rolled-back writer gives its number back.
- **Reading after a cursor never skips.** `GET /api/v1/runs/{id}/events?after=<n>` returns the events after `n` in
  sequence order; a client that keeps the last sequence it saw and asks again gets the next one when it commits.
  Live streaming (SSE, `Last-Event-ID`) is T27's.
- **Payload rules.** The payload is an object whose keys are the event schema's thirteen (`message`, `status`,
  `evidence_refs`, `proposal_id`, `action_id`, `code`, `reason`, `outcome`, `receipt`, `tombstone`, `question_id`,
  `message_id`, `outbox_id`). A `status` is the destination's assertion: only `action.confirmed`, `action.failed`,
  `action.conflict` and `action.late_evidence` (from `record_outcome`) carry one. Anything else is refused with
  SQLSTATE `OC006` (`EventRuleViolation` in Python) and writes nothing.

## Notification intent and the outbox

- **Intent commits with its event.** When `_append_event` writes `action.confirmed`, `action.failed`,
  `run.escalated` or `run.abandoned_unverified`, it also writes one `app.outbox` row in the same transaction,
  addressed to the run's requester, channel `local`, with the dedup key `run_id:type:local:requester`. A replayed
  writer adds no second row.
- **Delivery is the sweeper's**, every tick (30 s), per tenant: claim the due rows (`FOR UPDATE SKIP LOCKED`, lease
  `OPS_OUTBOX_LEASE_SECONDS`), hand each to the sink outside any transaction, record the result in its own unit.
  The v1 sink is a log line (`notification delivered: type=… run=… outbox=… recipient=<hash> …`): nothing leaves the
  machine. Slack is T39.
- **Failure.** A failed delivery is `retrying` with `leased_until` pushed out by `min(cap, base × 2^(attempts−1))`
  plus up to 25 % jitter; the `OPS_OUTBOX_MAX_ATTEMPTS`-th failure is `dead_letter`. A dead letter gets one
  `notification.failed` event on its run (`code`, `message`, `outbox_id`) in a separate transaction; every tick
  re-checks for dead letters still lacking it. The run's state is never touched by delivery.
- **At least once.** A delivery slower than its lease, or a sweeper that dies after the sink but before the result,
  is delivered again later (BUILD_SPEC §2: "At-least-once dispatch can occur").

## Wake-ups

- **A wake-up is a job committed with the event that needs it**: the investigate job with the run, the execute job
  with the approving decision, the reply job with the clarification. The worker polls every 0.5 s per tenant; there is
  no LISTEN/NOTIFY (erratum 64).
- **A released lease makes the run's deferred jobs due at once**: a job a claim moved behind a busy lease no longer
  waits for that lease's old end once its holder releases it.
- **The sweep re-arms a lost wake-up.** A run in QUEUED whose investigate jobs are all done, or in APPROVED whose
  execute jobs are all done, for longer than `OPS_WAKEUP_GRACE_SECONDS`, gets its newest job of that type reopened
  (the same row: its dedup key is the wake-up's identity). A job already claimed `OPS_WAKEUP_MAX_ATTEMPTS` times is
  not re-armed; the sweeper logs `wake-up not re-armed: …` every tick instead. AWAITING_INPUT (T20) and
  OUTCOME_UNKNOWN or ESCALATED (T22) are not swept yet.
- **Finished maintenance rows** (`sync_memberships`, `deliver_outbox`, `sweep_wakeups`) older than
  `OPS_MAINTENANCE_RETENTION_HOURS` are deleted; a run's jobs never are.

## Settings (validated when the sweeper starts)

| Variable | Default | Bounds | What it is |
|---|---|---|---|
| `OPS_OUTBOX_LEASE_SECONDS` | 30 | 5-3600 | how long a claimed row is held before another tick may claim it |
| `OPS_OUTBOX_BATCH` | 10 | 1-1000 | rows claimed per tenant per tick |
| `OPS_OUTBOX_BACKOFF_BASE_SECONDS` | 2 | 1-3600 | the first retry's wait |
| `OPS_OUTBOX_BACKOFF_CAP_SECONDS` | 300 | 2-86400 | the longest wait before jitter; at least the base |
| `OPS_OUTBOX_MAX_ATTEMPTS` | 5 | 1-100 | the failure that dead-letters |
| `OPS_WAKEUP_GRACE_SECONDS` | 60 | 10-86400 | how long a consumed wake-up may sit before it counts as lost |
| `OPS_WAKEUP_MAX_ATTEMPTS` | 10 | 1-1000 | claims after which a wake-up is no longer re-armed |
| `OPS_MAINTENANCE_RETENTION_HOURS` | 24 | 1-8760 | how long finished maintenance rows are kept |

## Looking at it

As the superuser on the dev database:

```sql
SELECT run_id, next_event_seq FROM app.runs WHERE run_id = '<run>';
SELECT sequence, type, source, occurred_at FROM app.events WHERE run_id = '<run>' ORDER BY sequence;
SELECT outbox_id, run_id, attempts, result, leased_until, delivered_at FROM app.outbox ORDER BY created_at DESC;
SELECT id, type, run_id, attempts, done_at, claimed_by FROM app.jobs WHERE run_id = '<run>';
```

## When something looks stuck

- **A notification never arrived**: look at its outbox row. `retrying` with a future `leased_until` is waiting for
  its backoff; `dead_letter` has a `notification.failed` event on the run; no `result` and a future `leased_until`
  is a delivery in flight (or one whose sweeper died: it is claimed again when the lease ends). The sweeper's log
  says `notification not delivered: … (retrying|dead_letter): <reason>` for each failure.
- **A run sits in QUEUED or APPROVED with its job done**: the sweep re-arms it after the grace; if the log says
  `wake-up not re-armed: … claimed N times`, the job's handler keeps returning without moving the run (for an
  execute job, often a refused grant: a stale membership, a revoked reviewer). Fix the cause; the next decision or
  revision makes a new wake-up.
- **An append is refused with OC006**: the payload carries a key the event schema does not define, or a `status` on
  a non-destination type. The writer, not the database, is wrong.

## Test-profile fault hook (`PROFILE=test` only)

`outbox_sink_fail` (`ops_core.testing.faults.FaultKind.OUTBOX_SINK_FAIL`): the next delivery of a `LogSink` built
with a test-profile `Faults` fails. The sweeper has no route to arm it; the live tests build the sink themselves
(`tests/e2e/test_outbox_live.py`).
````

Edit 2 (`docs/ARCHITECTURE.md`, before "Where the code will live"), replace:

```markdown
| R107 | An 8-connection stress test: no deadlock; the interleavings, fenced-definer and R019 tests: no stale write; expiry after the lock |

---

## Where the code will live (not yet written)
```

with:

```markdown
| R107 | An 8-connection stress test: no deadlock; the interleavings, fenced-definer and R019 tests: no stale write; expiry after the lock |

---

## 6. The event journal, wake-ups and the outbox (built in T14)

**Claim.** A run's events are numbered without gaps in the order they commit, whoever writes them; a notification
is promised in the same transaction as the event that needs it and delivered at least once apart from the run; and
a wake-up the worker consumed without moving its run is noticed and re-armed.

- **One counter under one lock.** `_append_event` takes the run row `FOR UPDATE`, `next_event_seq + 1` and the
  insert in the writer's transaction; a cursor on the events route therefore never skips.
- **Payload rules in the database.** The payload's keys are the schema's, and only the destination asserts a
  status; the schema, `event_rules_ok` and the SQL give one verdict on one table of cases.
- **A transactional outbox, delivered by the sweeper.** Intent is written by `_append_event`; delivery claims with a
  lease, sends outside any transaction (a log line in v1), records the result apart from the run, backs off,
  dead-letters and announces the dead letter with an event of its own transaction.
- **Wake-ups are jobs.** The sweep re-arms a consumed job whose run did not move; a released lease makes deferred jobs
  due at once; polling remains the wake mechanism.

| Requirement | What its test shows |
|---|---|
| R024 | A failed delivery retries, dead-letters and is announced once; the run is untouched; a replay adds no intent |
| R089 | Four roles' writers wait on the run lock; the route never shows n + 1 before n; a stress run ends gap-free |

---

## Where the code will live (not yet written)
```

`docs/PROJECT_HISTORY.md`: if a section whose heading contains `The journal plan` exists (the controller may commit
the planning story with the review record before execution, as for Plans G and H), skip the next edit. Otherwise:

Edit 3 (`docs/PROJECT_HISTORY.md`, the last section's heading), replace:

```markdown
## 26. What the process taught
```

with:

```markdown
## 26. The journal plan proved an old lock and put the outbox behind it

**Problem.** Plan I takes T14: the gap-free event journal, wake-ups and the notification outbox. The fact sheet found
that the journal's mechanism already existed (revision 0003 had put the counter under the run row lock) but had never
been exercised by concurrent writers, that "wake-up" meant two things in the repository (a job committed with its
event, and a signal to stop polling), and that the outbox did not exist at all. The controller's brief of 29 rulings
chose to prove the journal rather than redesign it, to read "wake-up" as the job plus a sweep that re-arms a lost
one, and to deliver the outbox from the sweeper to a log line, with no external channel before Slack.

**Change.** A stepped test holds one writer's sequence open and shows the next writer waiting on it from each of the
four roles; a stress run with rollbacks and two readers ends gap-free. The payload rules review note 2 asked for went
into `_append_event`, the schema and `event_rules_ok` together, checked on one table of cases, and the schema gained
the keys today's writers already used. Revision 0008 added the outbox, written by `_append_event` and delivered by the
sweeper per tenant with a lease, a capped backoff and a dead letter announced in a transaction of its own. The sweep
re-arms the investigate and execute jobs of runs that did not move, and a release makes a deferred job due at once.

## 27. What the process taught
```

Then append to section 26 (after its last paragraph, before `## 27.`) one `**Problem.**`/`**Change.**` pair per
finding the task reviews and the final review recorded (from the SDD ledger), or the sentence "Execution found nothing
the plan had not ruled on." when they recorded none. Later review rounds of this plan, if any, add their own paragraph
before execution.

`README.md`: line 5 is one long line; change its tail with this script (the old and new texts are each part of that
one line; the Python string literals only wrap for width):

```bash
uv run python - <<'EOF'
from pathlib import Path

path = Path("README.md")
text = path.read_text(encoding="utf-8")
old = "and fenced run leases with a heartbeat (T13) run locally**"
new = (
    "fenced run leases with a heartbeat (T13) and a gap-free event journal with a leased notification outbox (T14) "
    "run locally**"
)
assert text.count(old) == 1
path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
EOF
```

Edit 4 (`worker/README.md`, the "Runs" section), replace:

```markdown
## Runs (T08, T13)

`python -m ops_worker`: polls `app.jobs` every 0.5 s and claims a job together with its run's lease (`FOR UPDATE SKIP
LOCKED`, then the lease `FOR UPDATE NOWAIT`; a busy run's job is deferred behind the lease), health on 127.0.0.1:8070
(`OPS_WORKER_HEALTH_PORT`). Every unit it commits for a run is fenced by the lease; a heartbeat thread with its own
connection renews the lease while the event loop is alive and the job is within its compute budget, and cancels the
job's MCP or model call in flight when renewal fails; the job's final unit closes the job and releases the lease.
```

with:

```markdown
## Runs (T08, T13, T14)

`python -m ops_worker`: polls `app.jobs` every 0.5 s and claims a job together with its run's lease (`FOR UPDATE SKIP
LOCKED`, then the lease `FOR UPDATE NOWAIT`; a busy run's job is deferred behind the lease), health on 127.0.0.1:8070
(`OPS_WORKER_HEALTH_PORT`). Every unit it commits for a run is fenced by the lease; a heartbeat thread with its own
connection renews the lease while the event loop is alive and the job is within its compute budget, and cancels the
job's MCP or model call in flight when renewal fails; the job's final unit closes the job, releases the lease and
makes the run's deferred jobs due at once (T14). Polling is the v1 wake mechanism; a job it consumed without moving
its run is re-armed by the sweeper (`docs/runbooks/events-and-outbox.md`).
```

Edit 5 (`sweeper/README.md`, the first line), replace:

```markdown
Scheduler process (AM-20.1): membership sync, expiry purges, the hand-back of jobs whose run lease died; later
wake-ups, outbox
```

with:

```markdown
Scheduler process (AM-20.1): membership sync, expiry purges, the hand-back of jobs whose run lease died, the
notification outbox's delivery and the wake-up sweep; later proposal expiry
```

Edit 6 (`sweeper/README.md`, "Owns"), replace:

```markdown
purge of expired sessions, login state, logout-token ids and idempotency records past their replay window (T12), and
the hand-back of jobs whose run lease died with their worker (T13)
```

with:

```markdown
purge of expired sessions, login state, logout-token ids and idempotency records past their replay window (T12), the
hand-back of jobs whose run lease died with their worker (T13), the outbox's leased delivery with its retries, dead
letters and `notification.failed` events, the re-arming of lost wake-ups and the purge of finished maintenance rows
(T14)
```

Edit 7 (`sweeper/README.md`, "Never"), replace:

```markdown
Reactivates a membership; grants, decides, transitions a run or writes an event (`append_event` only for its own
maintenance events); reaches either sim
```

with:

```markdown
Reactivates a membership; grants, decides, transitions a run or writes an event (`append_event` only for a dead
letter's `notification.failed`, its one event); reaches either sim or any external channel (the sink is a log line)
```

Edit 8 (`sweeper/README.md`, "Runs"), replace:

```markdown
## Runs (T11, T13)

`python -m ops_sweeper`: every 30 s syncs memberships against the realm, records the sync as this minute's
`sync_memberships` job, purges expired rows and hands back the jobs whose run lease is no longer live (T13); health on
127.0.0.1:8071 (`OPS_SWEEPER_HEALTH_PORT`), ready only while the last successful sync is younger than 120 s.
Wake-ups, the outbox and proposal expiry: T14/T21.
```

with:

```markdown
## Runs (T11, T13, T14)

`python -m ops_sweeper`: every 30 s syncs memberships against the realm, records the sync as this minute's
`sync_memberships` job, purges expired rows, hands back the jobs whose run lease is no longer live (T13), delivers
the outbox tenant by tenant and re-arms lost wake-ups (T14, recorded as `deliver_outbox` and `sweep_wakeups` jobs);
health on 127.0.0.1:8071 (`OPS_SWEEPER_HEALTH_PORT`), ready only while the last successful sync is younger than
120 s. Settings and what to look at: `docs/runbooks/events-and-outbox.md`. Proposal expiry: T21.
```

- [ ] **Step 5: Final gates**

```bash
PYTHONUTF8=1 uv run python scripts/check.py
PYTHONUTF8=1 uv run python scripts/check.py --profile test
uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts
```

Expected: `CHECK: GREEN` with `1029 passed, 151 skipped`; `CHECK: GREEN` with `1159 passed, 21 skipped` (the live
number is arithmetic until this run measures it); exit 0. Fill the `<dev passed>`, `<dev skipped>` and `<live
passed>` placeholders of Steps 3 and 4 with the printed numbers. Then `git checkout -- reports/bootstrap
reports/auth`; the live run rewrote `reports/admission`, `reports/skeleton`, `reports/leases` and wrote
`reports/events` and `reports/outbox`, and Step 6 commits them. Tick this plan's checkboxes (`- [ ]` → `- [x]`) for
every step executed.

- [ ] **Step 6: Commit**

```bash
git add handoff SESSION_STATE.md STATUS.md README.md worker/README.md sweeper/README.md docs/ARCHITECTURE.md
git add docs/PROJECT_HISTORY.md docs/runbooks/events-and-outbox.md reports/admission reports/skeleton reports/leases
git add docs/superpowers/plans/2026-10-15-first-slice-i-journal-wakeups-outbox.md
# reports/events/ and reports/outbox/ are written by Step 5's live gate: test_event_journal_live.py and
# test_outbox_live.py each write their file only when all of their tests passed.
for d in reports/events reports/outbox; do
  if [ -d "$d" ]; then git add "$d"; else echo "$d missing: rerun Step 5"; fi
done
git commit -m "docs: close T14 - handoff records, acceptance rows, errata 60-71, the events and outbox runbook (Plan I)"
```

---

## Self-review (run by the plan's author before execution)

1. **Spec coverage.** T14's instructions: "runs.next_event_seq under the runs lock" → kept (ruling 1) and proved live
   (Task 3); "wake-up jobs committed with user events" → already true (`create_run`, `record_decision`, the reply
   unit; FS §3.8), kept, and the jobs consumed without progress are re-armed by the sweep (Task 5); "sweeper" → the
   tenant iteration, the delivery loop, the wake-up sweep, the purge and their audit rows (Tasks 4, 5);
   "transactional outbox with leased delivery loop (no external channel)" → revision 0008's outbox written by
   `_append_event` (Task 2) and the leased loop to `LogSink` (Task 4). DoD 1 "Concurrent writers yield gap-free
   commit-ordered sequences" → Task 3's two stepped tests, the rollback test and the stress run. DoD 2 "Outbox rows
   deduplicated and leased; delivery result recorded separately" → the dedup key and its target-less conflict (Task 2
   live, Task 4 R024 replay), the claim's lease and its expiry (Task 4 crash test), the result on the outbox row with
   the run untouched (R024). Review notes: 1 (dedup keys UNIQUE; no recover job from an MCP server) → the catalog test
   (Task 2) and the re-arm that reuses the row and key (Task 5); 2 (payload rules inside the function; the emitters of
   `action.granted` and `action.redispatched`; `deliver_outbox` a job type) → `_append_event`'s rules (Task 2) with
   their mirrors (Task 1), the emitters already as the note says (FS §3.4, unchanged), `deliver_outbox` recorded as a
   maintenance row every tick (Task 4); 3 (the sweeper iterates tenants; `sweeper_all` only on memberships and jobs) →
   `tenants.for_each_tenant` and the outbox without `sweeper_all` (Tasks 2, 4). The two requirement rows by their
   expected evidence:
   - **R024** "Fail delivery after state commit; result remains recorded and dedup key preserves intent." →
     `test_r024_a_failed_delivery_keeps_the_outcome_and_one_intent` (Task 4): the outcome commits with its intent,
     five sink failures on the database clock, retrying then dead-letter recorded on the row, the run's state and
     events unchanged, a replayed outcome and a re-appended event adding no intent, the dead letter announced once.
   - **R089** "Concurrent writers; SSE replay never skips." → Task 3's four tests; the replay is the events route's
     `after` cursor (SSE is T27's, said in the docstring, the matrix note and the runbook).
   The brief's 29 rulings map to tasks in "Rulings" above; every refinement is listed under "Rulings needing
   controller attention".
2. **Placeholder scan.** No undecided placeholder, no "similar to Task N", no "add error handling". The template
   markers `<base>`, `<last>`, `<date>`, `<dev passed>`, `<dev skipped>` and `<live passed>` in Task 6 are defined by
   the commands that print them (Task 1 Step 1b, Task 6 Step 5). The `TODO(T26)` Task 1 writes and the `TODO(T21)`
   Task 4 leaves are ownership markers `docs/CODE_COMMENTS.md` requires, each on a debt list.
3. **Type and name consistency.** `OutboxSettings(lease_seconds, batch, backoff_base_seconds, backoff_cap_seconds,
   max_attempts)` and `WakeupSettings(grace_seconds, max_attempts, maintenance_retention_hours)` are built the same way
   in `settings`, the sweeper's `Deps` (`outbox_settings`, `wakeup_settings`), the unit tests and the live tests.
   `Delivery(outbox_id, tenant_id, run_id, event_type, channel, recipient, attempt)`, `Result(outbox_id, tenant_id,
   run_id, result, attempts, recorded)` and `Wakeup(run_id, job_id, job_type, attempts, rearmed)` are used with those
   fields everywhere. `deliver(conn, sink, chosen, *, tenants=None, rng=…)`, `notify_dead_letters(conn, *,
   tenants=None)`, `sweep(conn, chosen, *, tenants=None)`, `purge_maintenance(conn, chosen)`,
   `for_each_tenant(conn, work, *, tenants=None)`, `in_tenant(conn, tenant_id, work)`, `pull_forward(conn, run_id, *,
   except_job)` and `main.record(deps, job_type)` match their callers and fakes. The SQL names (`outbox_id`,
   `leased_until`, `delivered_at`, `result`, `dedup_key`) match revision 0008, the matrix row and the queries;
   `PAYLOAD_KEYS_0008` and `STATUS_TYPES_0008` equal `outcomes.PAYLOAD_KEYS` and `STATUS_EVENT_TYPES` (a unit test).
   `FaultKind.OUTBOX_SINK_FAIL` is the one `SWEEPER_FAULTS` member and is consumed only by `LogSink`.
4. **Review Focus.** (1) a delivery outliving its lease → Task 4's result-statement test and the crash test; (2) a
   crash between result and event → Task 4's R024 test and the already-notified test; (3) a replayed outcome → Task
   4's R024 test and Task 2's intent test; (4) a run moving before its re-arm → Task 5's re-arm tests; (5) today's
   writers under the closed keys → the case table in Tasks 1 and 2 and the existing live tests in Task 2's gate.
5. **Known risks the executor should watch** (none changes a ruling):
   - The live tests of Tasks 2-5 were written against the real fixtures and functions but could not be run in the
     dry run; their first live run is in execution. A failure in Task 3 is a finding against revision 0003's
     mechanism and must be reported, never worked around by weakening an assertion.
   - The R089 stress run's volume depends on the machine: six appending connections with millisecond sleeps can write
     thousands of events per run in 10 s; the cursor reader pages by 500 and the assertions are exact, not
     statistical, but the reader floors (100 pages, 100 counts) assume the readers are not starved.
   - The R024 and crash tests move the global test clock (to 4000 s and 31 s) and reset it in `finally`; they rely on
     the suite running tests one at a time, as it does.
   - Schema rule 9 changes a contract T45 owns (AM-80); a later writer that needs `status` on a new type must extend
     the schema, `event_rules_ok` and the SQL together, and the case table will fail until all three agree.
   - The R105 skeleton's real sweeper now delivers and sweeps every tenant every 30 s: a QUEUED or APPROVED run some
     earlier test left behind with its job done would be re-armed and run by the skeleton's worker. Every live test
     purges what it creates in `finally`.

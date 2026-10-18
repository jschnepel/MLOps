# Plan I review record — T14 gap-free event journal, wake-ups and outbox

Plan: `docs/superpowers/plans/2026-10-15-first-slice-i-journal-wakeups-outbox.md` (branch `plan-i`; plan commit 4570fc5, round fixes 19e8d13 and df0f48c). Inputs:
`docs/superpowers/research/2026-10-15-plan-i-inputs.md` and the controller's rulings brief (reproduced below).
Each round is one static adversarial review of the plan text, which also applied the plan task by task to a scratch
copy (ruff format between tasks, ruff, mypy strict, non-live pytest, dev counts), followed by the controller's rulings
and the fix commit. The plan writer's own task-by-task dry run stood in for a separate builder dry run; live steps
cannot run in a dry run (the permission policy refuses copying `.env` into a scratch worktree), so the plan marks its
live counts as arithmetic. Round 1: 1 Blocking, 7 Important, 12 Minor. Round 2: 0 Blocking, 1 Important, 5 Minor;
its Important (a crashing sink row costing its batch attempts) was closed by a small sink-boundary catch that the
controller verified in the plan text, so no third round ran.

---

# Controller brief (rulings before round 1)

# Plan I brief — controller rulings for T14 (gap-free event journal, wake-ups, outbox)

Branch `plan-i` (= `plan-h` 643e1b7). Fact sheet: `docs/superpowers/research/2026-10-15-plan-i-inputs.md` (cited
"FS §n" / "FS Qn"). No separate spike. Errata continue at **60**. Requirements: R024, R089. Gates at start: dev 939
passed / 134 skipped; live 1052 / 21; verify_handoff 0.

## Rulings (one per FS question)

1. **Gap-free mechanism (FS Q1).** Unchanged: `_append_event` locks `runs` FOR UPDATE, bumps `next_event_seq`, inserts
   in the caller's transaction (SA:303). T14 *proves* it (rulings 2–3); it does not redesign it.
2. **Which writers (FS Q2).** The proof drives real role connections through the real definers: `api`
   (`append_event`), `worker` (`append_event`, `transition_run`), `mcp_exec` (a definer that appends, via a staged
   handle as the existing live tests do) and `sweeper` (`append_event` of `notification.failed`). Two kinds of test:
   a stepped interleaving (`wait_until_blocked`) and a concurrent stress (`slow_live` if > 15 s).
3. **Observing commit order (FS Q3).** Assertions: (a) stepped — writer A holds sequence n uncommitted, writer B waits
   on the `runs` lock (proved with `pg_blocking_pids`), a third reader sees neither n nor n+1; A commits → the reader
   sees n; B commits → n+1; (b) rollback — A takes n and rolls back, B then gets n (no hole); (c) stress — N
   connections across the four roles append to the same runs with random rollbacks; afterwards every run's sequences
   are exactly `1..next_event_seq`, and a reader polling during the run never observes a set with a hole below its
   maximum. R089 "SSE replay never skips" is proved at the table and the existing events route (`after` cursor); SSE
   itself is T27's.
4. **Payload rules in the function (FS Q4, review note 2).** `_append_event` (new revision) refuses (OC006) a payload
   that is not a JSON object, a `status` key on any type the event schema does not allow it for, and any key outside
   the schema's allowed payload key set. The plan reads `schemas/event.schema.json` and mirrors exactly what it
   allows; where today's real payloads (`clarification.received`: `question_id`, `message_id`; any other the plan
   finds by grepping every `append_event`/`_append_event` caller) are outside the schema, the schema gains those keys
   (erratum; T45 owns AM-80 but evolving the schema with the code is allowed with a contract test). `event_rules_ok`
   mirrors the SQL rule; a unit test pins the two together on a table of cases.
5. **`outcomes.Event` TODO (FS Q5).** Retired to T26 (response schemas): debt line; the TODO is reworded.
6. **What a wake-up is (FS Q6).** The spec's meaning: a job row committed with the user event, plus a sweep that
   re-arms a lost one. No LISTEN/NOTIFY; the worker keeps polling (0.5 s, per tenant) — the polling debts are closed
   as "polling is the v1 wake mechanism" (erratum), not deferred.
7. **What `sweep_wakeups` compares (FS Q7).** Only states whose handlers exist today: (a) a run in `QUEUED` whose
   `investigate` jobs are all done; (b) a run in `APPROVED` whose `execute` jobs are all done — each for longer than a
   grace (`OPS_WAKEUP_GRACE_SECONDS`, default 60). `AWAITING_INPUT`/`resume_input` (T20), `OUTCOME_UNKNOWN`/`ESCALATED`
   `recover` (T22) and the decision-to-processing crash test R023 (T21) are debt lines naming their owners.
8. **Re-enqueue = re-arm (FS Q8).** The sweeper reopens the newest done job of that type for the run
   (`done_at`, `claimed_by`, `claimed_at` → NULL) under `sweeper_all`; the dedup key is preserved (same wake-up,
   re-armed). Bounded: only while `attempts < OPS_WAKEUP_MAX_ATTEMPTS` (default 10); past the cap the sweep logs once
   per tick per run (operator visibility via logs, as T28 owns metrics). Erratum: AM-20.4 gains "the sweeper re-arms a
   lost wake-up by reopening its job; it never inserts `resume_input`/`execute` rows".
9. **Durable ack (FS Q9).** Unchanged in T14: the worker still finishes job types it does not handle; debt lines to
   T20 (`resume_input`) and T22 (`recover`), since leaving them open would make the worker re-claim them every poll.
10. **Deferred jobs on release (FS Q10).** `release_lease` (the job's final unit) also pulls the run's other unclaimed,
    undone jobs forward (`available_at = app.current_time()` where it is later), in the same unit after finishing
    the job (lock order: `jobs` last). `abandon` does not (the lease lapses on its own). Unit + live test.
11. **Per-tenant polling (FS Q11).** Stays (ruling 6).
12. **Outbox shape (FS Q12).** `app.outbox(outbox_id uuid PK, tenant_id uuid NOT NULL, run_id uuid NOT NULL, event_id
    uuid NOT NULL REFERENCES app.events, channel text NOT NULL CHECK (channel = 'local'), recipient text NOT NULL,
    dedup_key text NOT NULL UNIQUE, attempts integer NOT NULL DEFAULT 0, leased_until timestamptz NOT NULL DEFAULT
    '-infinity', delivered_at timestamptz, result text CHECK (result IN ('delivered','retrying','dead_letter')),
    created_at timestamptz NOT NULL DEFAULT now())`, composite FK `(tenant_id, run_id)` → runs, RLS
    `tenant_isolation` (no `sweeper_all`). `leased_until` doubles as "not before" (the next attempt time), so the
    AM-20.2 sweeper cells suffice. The payload is by reference (`event_id`); no copy.
13. **Who inserts, which events (FS Q13).** Inside `_append_event`, in the same transaction, right after the event
    insert, for a fixed trigger set: `action.confirmed`, `action.failed`, `run.escalated` (the requester's outcome
    events; `run.abandoned_unverified` too if the type exists). Recipient = the run's requester subject; channel
    `local`; `dedup_key = run_id:type:channel:recipient`, inserted with target-less `ON CONFLICT DO NOTHING`
    (app_definer holds `ins` only), so a replayed writer adds no second intent (R024). `notification.failed` never
    creates intent.
14. **Delivery without an external channel (FS Q14).** A `Sink` protocol in the sweeper with one v1 implementation,
    `LogSink`: one structured log line per delivery (type, run id, outbox id; no payload content, no recipient value
    beyond a hash) — no egress. Fault hook: `FaultKind.OUTBOX_SINK_FAIL` in `core.testing.faults` (test profile only),
    consumed by the sink; armed in tests through a sweeper factory parameter (the sweeper has no fault route; the
    live tests construct the delivery function with a test-profile `Faults`).
15. **Delivery loop (FS Q15).** In the sweeper process tick (`deliver_outbox` is a sweeper job type). Per tenant: a
    claim unit (`… WHERE delivered_at IS NULL AND result IS DISTINCT FROM 'dead_letter' AND leased_until <=
    app.current_time() ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT batch`, then `leased_until = now + lease`,
    `attempts + 1`), commit; deliver outside any transaction; then one result unit per row. A crashed delivery is
    retried when its lease expires. Settings: `OPS_OUTBOX_LEASE_SECONDS` 30, `OPS_OUTBOX_BATCH` 10.
16. **Retry, jitter, dead letter (FS Q16).** On failure: `result = 'retrying'`, `leased_until = now + backoff` with
    backoff `min(cap, base × 2^(attempts−1))` plus up to 25 % jitter (`OPS_OUTBOX_BACKOFF_BASE_SECONDS` 2, cap 300);
    at `attempts >= OPS_OUTBOX_MAX_ATTEMPTS` (5) → `result = 'dead_letter'`. Operator visibility in v1: the
    `notification.failed` event (visible in the run's events) plus a log line; dashboards are T28/T29.
17. **`notification.failed` (FS Q17).** Appended once per dead-lettered row, in a **separate** transaction after the
    result unit (SA:188), payload `{code, message}` per the schema. The crash window (dead letter recorded, event not
    appended) is closed by a re-check in each delivery tick: dead-letter rows of the tenant whose run has no
    `notification.failed` event referencing that outbox id (payload carries `outbox_id` if the schema allows it — add
    it per ruling 4 if not) get it appended. Deduplicated by that check.
18. **Tenant iteration (FS Q18).** A sweeper helper `for_each_tenant(conn, fn)` reading `tenants` and running `fn` in
    one transaction per tenant after `set_tenant`; used by delivery and the wake-up sweep's `runs` reads; shaped for
    T21/T22 reuse.
19. **Maintenance job rows (FS Q19).** `deliver_outbox` and `sweep_wakeups` follow `sync_memberships`' audit-row
    pattern (insert, claim, finish in one transaction keyed on the minute bucket; the work runs outside it; a second
    tick in the same minute finds the key taken and still does the work, recording nothing new).
20. **Purge finished maintenance rows (FS Q20).** New AM-20.2 cell: sweeper `del` on `jobs` (it holds `sel` and
    `sweeper_all`); the purge deletes only maintenance rows (`run_id IS NULL AND done_at IS NOT NULL`) older than
    `OPS_MAINTENANCE_RETENTION_HOURS` (24); run jobs are never deleted (dedup keys are the wake-up identity). Erratum.
21. **Retention (FS Q21).** No deletion of events or outbox rows in T14 (audit; replay); debt line → T32 (retention and
    restore).
22. **Lock order (FS Q22).** `OBSERVED_UNITS` gains: the outbox intent inside `_append_event` (runs → events →
    outbox); the delivery claim and result units (`outbox` own units); the `notification.failed` append (`runs` via
    `append_event`, separate unit); the wake-up re-arm (`jobs` own unit; reads unlocked); the release pull-forward
    (`run_lease` → … → `jobs`). `outbox` leaves `NOT_YET_CREATED`.
23. **Events route (FS Q23).** Untouched (T26/T27), except as the reader in ruling 3.
24. **Sequence width (FS Q24).** `integer` stays.
25. **Sweeper's own events (FS Q25).** `notification.failed` is its only event; README line updated.
26. **SA:471 / erratum 49 (FS Q26).** The wake-up sweep is a separate sweeper routine (`wakeups.sweep`, direct
    grants), not part of `leases.reclaim` and not a definer; erratum 49's note is extended.
27. **Review note 1 (FS Q27).** A live catalog test: no function `mcp_exec` (or `mcp_read`) may execute contains an
    insert into `app.jobs` in its body (`pg_get_functiondef` scan, including the helpers it calls — the plan lists
    them), and `mcp_exec` holds no table grant.
28. **Testing R024 (FS Q28).** Live: stage a run to SUCCEEDED through `record_outcome` (the existing write-path
    fixtures) so `action.confirmed` and its intent commit; arm `OUTBOX_SINK_FAIL`; run delivery → row `retrying`,
    `attempts 1`, run state and events unchanged; replay `record_outcome` (idempotent) → still one intent; move the
    test clock past the backoff and fail to the cap → `dead_letter` and exactly one `notification.failed`; a crash
    between result and event is simulated by skipping the event step once and showing the re-check appends it.
    Evidence file `reports/outbox/t14-outbox.txt`, and `reports/events/t14-events.txt` for R089.
29. **Migration (FS Q29).** One revision `0008_journal_outbox`: `outbox` (+ grants, RLS), sweeper `del` on `jobs`,
    re-created `_append_event` (payload rules + intent) and any body that must change, frozen cells and callers, exact
    downgrade to 0007 (0007's re-run-the-applied-bodies pattern). Owner input: migrate dev to 0008 (it is at 0005).

## Task shape (≤ 7 tasks)

1. Debt list; settings (outbox, wake-up, retention); lock-order entries; schema key additions + `event_rules_ok`.
2. Revision 0008 (outbox, grants, RLS, jobs `del`, `_append_event` payload rules + outbox intent) + matrix + live
   migration/catalog tests (incl. ruling 27).
3. The gap-free proof (R089): stepped, rollback, stress.
4. The sweeper's tenant iteration, the delivery loop, `LogSink`, the fault kind, retry/dead letter, `notification.failed`
   and its re-check (R024).
5. The wake-up sweep (re-arm), the release pull-forward, maintenance audit rows, the purge.
6. Close-out (handoff records, acceptance rows, errata 60+, runbook `docs/runbooks/events-and-outbox.md`, STATUS,
   SESSION_STATE, BUILD_BACKLOG, ARCHITECTURE, PROJECT_HISTORY, READMEs, final gates).

## Standing constraints
Carry Plan H's Global Constraints (no attribution; CODE_COMMENTS; debt before code; clock on `app.current_time()` after
locks; one string per SQL function + ISC004; live tests only on `ops_test`/`incident_test`; `tests/plan_i/` for unit
tests; no secrets; never migrate the dev databases; the slow_live marker; gates after every task). Lessons from Plan H
to carry: never cancel a database unit; a dry run cannot run live steps (permission policy refuses copying `.env`
into a worktree), so the plan's live steps must be written with extra care and the plan says which numbers are
arithmetic only.

---

# Round 1

## Static review

## Plan I round 1: static adversarial critic

Plan: `docs/superpowers/plans/2026-10-15-first-slice-i-journal-wakeups-outbox.md` (5,330 lines, branch `plan-i`,
4570fc5).

**Verdict: REVISE.** 1 Blocking, 7 Important, 12 Minor.

Every splice applies and every per-task dev count matches the plan exactly. `ruff format` changes nothing after any
task, ruff and mypy strict are clean, and `verify_handoff` exits 0 after every task, Task 6 included. The SQL is sound:
- the payload rules break no existing writer (I grepped every caller);
- the intent insert sits correctly under the runs lock and needs only INSERT;
- the downgrade body is byte-for-byte 0003's;
- I found no lock-order inversion.

The Blocking finding is a test-harness deadlock that can hang the live gate at random. The Important findings are:
- delivery has no bound on crashing rows;
- the wake-up sweep re-arms deliberately refused grants;
- two of the four notification types are never emitted today;
- the stress readers can pass vacuously;
- the downgrade evidence is weaker than the claim;
- the sweeper's DELETE authority is wider than erratum 61 says;
- the re-arm does not repeat its clock and newest-job checks.

### How this was checked

**Reading.** I read:
- the whole plan, the controller's brief (29 rulings), the plan's accepted refinements (a)-(h), and the fact sheet;
- the T14 task record with its three review notes, and the R024 and R089 rows;
- every function body 0008 replaces or depends on: 0003 `_append_event`, `_transition`, `transition_run`,
  `append_event` and `HELPER_HEADER`; 0004/0005 `grant_execution` and its refusal paths; 0007 `mark_sent`,
  `record_outcome` and `mark_unknown`;
- `privileges.py` (rows, `rls_statements`, `function_grant_statements`, `sweeper_all FOR ALL USING (true)`);
- `persistence.py` (`claim_next`, `acquire_lease`, `release_lease`, `insert_job`, the maintenance helpers,
  `tenants`);
- the worker's `handlers.py`, the sweeper's `main.py`, `testing/faults.py`;
- the e2e fixtures (`conftest.py`, `new_run`, the write-path helpers, `wait_until_blocked`) and the existing live
  tests the plan's live steps rerun (roles, 0007, leases, worker, sweeper, R105);
- psycopg 3.3.6's installed `cursor_async.py`, `connection_async.py` and `transaction.py`.

**Payload callers.** I grepped every emitter: `append_event` callers in api, worker and tests; `_append_event` and
`_transition` callers in 0003-0007; the worker's `transition_run` details. Every payload uses only the thirteen keys.
`status` appears only on `action.confirmed` from `record_outcome`. No existing writer breaks under rule 9 or the
closed key set.

**Applying the plan.** I took a `git archive HEAD` copy, made it a git repo, and ran `uv sync --frozen` (its own
locked venv, editables pointing at the copy). Then I applied Tasks 1-6 in order with an Edit/Create parser. I ran
`build_schemas` in Task 1, and in Task 6 the handoff script and the README script, both extracted verbatim from the
plan. After each task I ran `ruff format`, `ruff check`, `scripts/check.py` and `verify_handoff`. Every quoted old
text matched exactly once.

| After task | ruff format | ruff check | mypy strict | pytest (dev) | verify_handoff |
|---|---|---|---|---|---|
| base | - | - | clean, 53 files | 939 / 134 | 0 |
| 1 | no change | clean | clean, 53 | **1001 / 134** | 0 |
| 2 | no change | clean | clean, 53 | **1007 / 139** | 0 |
| 3 | no change | clean | clean, 53 | **1007 / 143** | 0 |
| 4 | no change | clean | clean, 55 | **1021 / 146** | 0 |
| 5 | no change | clean | clean, 56 | **1029 / 151** | 0 |
| 6 | no change | clean | clean | **1029 / 151** | 0 (35 accepted, 54 negative) |

**Red and intermediate steps.** I re-ran the plan's intermediate commands with each task's blocks applied up to the
step marker (`critic1/partial.sh`, `reds.sh`). Every Expected line matched:
- T1 S3 and T1 S5: `1 error`.
- T1 S8: `89 passed`.
- T2 S1: `1 error` (collection of `test_transitions_table`).
- T2 S2: `2 failed, 16 passed`, the two named tests.
- T2 S3: `63`.
- T4 S1: `2 errors` (`SWEEPER_FAULTS`).
- T4 S2: `1 error` (`outbox`).
- T4 S3: `16`. T4 S4: `82`.
- T5 S1: `1 error` (`wakeups`).
- T5 S2: `20`. T5 S3: `7`. T5 S4: `101`.

**Live arithmetic.** Collecting each step's file list gives exactly the counts the plan states: 43 (T2 S5), 12 (T4 S5)
and 24 (T5 S5). Every live count is marked as arithmetic.

**Task 6.** After it ran:
- the handoff diff touches three files, and in the matrix only R024 and R089;
- `git grep "TODO(T14"` is empty;
- the sweeper README line is the one Step 1 predicts.

Tests are not under mypy in the gate (existing tests fail mypy too), so I did not hold the new tests to it.

**Not run.** No live test was run and no database was touched. Database and asyncio behaviour is judged statically
against PG 17 and the installed psycopg.

---

### Blocking

**B1 — The rollback test can deadlock the live gate at random, because it asks for the blocked connection's pid after
that connection is already blocked.**

Where: Task 3, `test_r089_a_rolled_back_writer_leaves_no_hole`, plan 2257-2262:

```python
async with api.transaction(force_rollback=True):
    cur = await api.execute(APPEND, ...)
    ...
    b_task = asyncio.create_task(writer_b())
    assert await backend_pid(api) in await wait_until_blocked(app_conn, await backend_pid(worker))
```

Evidence (psycopg 3.3.6 as installed): `AsyncCursor.execute` holds `self._conn.lock` for the whole round trip
(`cursor_async.py:111-115`), and `AsyncTransaction.__aenter__` holds it for BEGIN (`transaction.py:292-295`). Python
evaluates the left operand of `in` first, so the sequence is:
1. `await backend_pid(api)` sends its query and yields.
2. `writer_b` runs on `worker`: lock, BEGIN, release, then `execute(APPEND)`. It takes the lock again and waits on
   the server, because the run row is held by `api`'s open transaction.
3. If BEGIN's reply is processed before `backend_pid(api)`'s reply, `writer_b` already holds `worker.lock`, blocked
   in the database, when the main coroutine reaches `await backend_pid(worker)`.
4. The main coroutine waits for `worker.lock`. `writer_b` waits for `api`'s row lock. `api`'s transaction ends only
   when the main coroutine leaves the `async with`.

That is a cycle across asyncio and PostgreSQL:
- no `lock_timeout` is set on these connections;
- `wait_until_blocked`'s 5 s timeout is never reached;
- the suite has no pytest timeout.

The live gate hangs, depending on which of two sub-millisecond replies the selector reports first.

The stepped helper escapes only by ordering. At 2183-2184 no await falls between `create_task` and
`backend_pid(b_conn)`, so the main coroutine takes `b_conn.lock` before `writer_b` runs. Plan H's tests avoid both
hazards by computing pids up front: `test_leases_live.py:120` and `:211`, `a_pid, b_pid = await backend_pid(a), await
backend_pid(b)` before the transaction.

Why it matters: the dry run cannot run it, the executor cannot tell a hang from a slow stress run, and the gate never
reaches a verdict.

Fix: compute `api_pid, worker_pid = await backend_pid(api), await backend_pid(worker)` before `async with
api.transaction(...)`, then `assert api_pid in await wait_until_blocked(app_conn, worker_pid)`. Do the same in
`stepped()`: take `a_pid, b_pid` before `async with a_conn.transaction()`, so the helper does not depend on asyncio
scheduling order.

---

### Important

**I1 — A delivery that crashes (rather than raising `SinkFailed`) is never dead-lettered, and it takes down the rest
of every tick, the wake-up sweep included.**

Where: `outbox.CLAIM` (2940-2949), `deliver` (3054-3100), `main.tick` (3262-3274; Task 5 4240-4253), and Global
Constraints 71-72 ("a sink error other than `SinkFailed` propagates to the tick's existing catch-all").

Evidence:
- The claim increments `attempts` but never looks at it.
- The dead letter is decided only in the `except SinkFailed` branch (3084).
- A row whose delivery raises anything else (a bug in a T39 sink, a payload it cannot render, a process killed
  mid-delivery every time) is re-claimed every lease, with `attempts` growing without bound.
- On every one of those ticks the exception leaves `deliver` before any other tenant's rows are delivered. It then
  propagates out of `deliver_outbox`, so `notify_dead_letters`, `record(DELIVER_OUTBOX)` and the whole of
  `sweep_wakeups` (called after it, 4252-4253) are skipped. `run_forever` logs "sweeper tick failed" and starts over.
- The claim orders by `created_at`, so the poison row is claimed first every time.

Result: one bad row stops delivery for every tenant and stops the wake-up sweep, the run-progress mechanism T14 adds,
for good. The plan's own crash test (3693-3714) shows the row coming back. Nothing shows it ever stopping.

Fix (no broad `except` needed):
1. Bound attempts at claim time. Claim only `attempts < %s`. Add one statement in the claim unit that dead-letters
   rows past the cap whose lease has run out: `UPDATE … SET result = 'dead_letter' WHERE delivered_at IS NULL AND
   result IS DISTINCT FROM 'dead_letter' AND attempts >= %s AND leased_until <= app.current_time()`. The existing
   re-check then announces them.
2. Call `sweep_wakeups` before `deliver_outbox` in `tick`, so notification delivery can never starve run progress.
3. Add a unit test for both, and say in erratum 67 that a crashing delivery dead-letters at the same cap.

**I2 — `run.escalated` and `run.abandoned_unverified` are never emitted today, so a run that escalates notifies
nobody. Erratum 66, the runbook and the handoff note present four working triggers.**

Where: `NOTIFY_TYPES_0008` (1408); the unit test (1235-1240); erratum 66 (4836-4839); runbook 4975-4977; the handoff
note (4673-4675); the ARCHITECTURE claim (5068-5070).

Evidence:
- The fact sheet records it (`plan-i-inputs.md:410-413`): "Types no code emits: … `run.escalated`,
  `run.abandoned_unverified` … (`escalate_run`, `resolve_escalation` … do not exist; owners T21/T22)".
- The escalation that does exist goes through `record_outcome` with CONFLICT. It calls `_transition(…,
  'ESCALATED', …, NULL, NULL)` with no event (0007:284) and appends `action.conflict` (0007:298-308), which is not a
  trigger type.
- So in v1 the requester hears about SUCCEEDED and FAILED but never about ESCALATED, the outcome a requester most
  needs to hear.
- No test or debt line says so. R024's evidence covers `action.confirmed` only.

Fix, a controller choice:
- (a) keep the brief's four types, and add a debt line ("a CONFLICT escalates through `record_outcome`'s
  `action.conflict`, which writes no intent; `escalate_run`'s `run.escalated` will → T22") plus a sentence in erratum
  66, the runbook and the handoff note naming which two types are actually emitted today; or
- (b) add `action.conflict` to `NOTIFY_TYPES_0008` until T22 ships `escalate_run`. The dedup key per run and type keeps
  it to one intent.

**I3 — The wake-up sweep re-arms refusals the worker treats as final: up to nine extra mcp-write dispatches per refused
run. A cancelled run keeps being re-dispatched. A test docstring claims this cannot happen.**

Where: `wakeups.LOST`/`REARM` (4079-4093); `test_wakeups_live` docstring (4397-4399); runbook 5035-5038.

Evidence:
- `handlers.execute` finishes the job on "any other envelope", so the run stays APPROVED (handlers.py:205-211 and
  the `return True` at the end of the function).
- `grant_execution` refuses without moving the run on `CANCELLED`, `MEMBERSHIP_INACTIVE`, `NO_APPROVAL`,
  `NOT_ACTIVE_APPROVED` and `PROPOSAL_NOT_IN_RUN` (0005:93-138; every one is a `RAISE`, none a `_transition`).
- So "APPROVED with its execute job done for longer than the grace" is the normal state after every final refusal.
  The sweep re-arms that job every 60 s until it has been claimed 10 times. Each re-arm mints a write handle and
  calls `create_incident` again.
- No external action can follow from a refusal that stays a refusal: there is still no grant, and the grant is one
  per run. But a run with `cancel_requested = true` is re-dispatched nine times.
- A refusal that becomes acceptable inside about 10 minutes (a reviewer reactivated by the membership sync) is now
  executed automatically. Today the refusal is final.
- The live test's docstring says "no handler today returns without moving a run except under faults this suite
  injects elsewhere". That is false for `execute`.
- The runbook's example "a stale membership" is also wrong: `MEMBERSHIP_STALE` is the deferred envelope, which
  re-queues the job rather than finishing it.

Brief ruling 7 chose the predicate, so this is not re-litigation. The consequences need to be stated and the cheap
part closed.

Fix:
- add `AND NOT r.cancel_requested` to `LOST` and to `REARM`'s `EXISTS`;
- correct the docstring;
- fix the runbook example;
- add a debt line ("a final grant refusal leaves the run APPROVED, and the sweep re-dispatches it up to
  `OPS_WAKEUP_MAX_ATTEMPTS` times until refusals move the run (`expire_proposal`, `request_cancel`) → T21/T22");
- make erratum 63 say that refused grants are retried up to the cap.

**I4 — The stress readers can pass vacuously: their floors count loop iterations, not observations.**

Where: `cursor_reader`/`count_reader` (2338-2372); the floor at 2417 (`seen["pages"] >= 100 and seen["counts"] >=
100`).

Evidence:
- `seen["pages"]` is incremented for every page, empty or not. `seen["counts"]` is incremented for every query,
  whether or not it returned rows.
- A cursor reader on the wrong tenant, or a count reader whose `set_tenant` admitted nothing, would see `[]` on every
  poll. It would record no violation, meet both floors and pass. Today both readers happen to use ALPHA, the stress
  runs' tenant, so the assertions hold, but nothing forces it.
- This is the Plan H lesson exactly: a stress test must exercise what its docstring claims. Here the claim is that a
  reader following the cursor never skips while the writers write.

Fix:
- record per run the number of non-empty pages and the cursor's final `last[run]`, then assert `last[run] ==
  next_event_seq` for every run after the gather (the reader runs 0.5 s past `stop`, so it must have caught up and
  followed the whole sequence);
- assert at least, say, 20 non-empty pages per run;
- have `count_reader` record the distinct `hi` values per run and assert there are more than one (it saw the
  sequence grow).

**I5 — The round trip proves less than "exact downgrade" and less than its 0007 precedent.**

Where: `test_migration_0008_live.snapshot` (1801-1818) and `test_the_round_trip_restores_0007` (1821-1837); the claim
in rulings 29 and 196-197 ("proved live by a round trip").

Evidence:
- `cells` comes from `information_schema.role_table_grants`, which lists table-level privileges only.
- 0008's upgrade and downgrade both `REVOKE ALL ON app.jobs` and re-grant every cell, the column-level
  `UPDATE (claimed_by, …, available_at)` cells of `worker` and `sweeper` included. A downgrade or upgrade that dropped
  one of them would pass this test.
- The restored `_append_event` is checked only for the absence of two strings (1833-1834). The 0007 test compares
  `prosrc` with the applied body and compares the full function details (owner, ACL, config) against a scratch
  database built to the previous revision (`test_migration_0007_live.py:117-130`).
- 0008's body is byte-for-byte 0003's, and `function_grant_statements` matches, so I expect the downgrade to be
  exact. The evidence just does not show it.

Fix:
- add `information_schema.column_privileges` for `jobs` and `outbox` to `snapshot`;
- assert `prosrc == REV0003.APPEND_EVENT_HELPER.split("$fn$")[1]` after the downgrade;
- ideally reuse 0007's `built_to_…` pattern to compare `FUNCTION_DETAILS` against a scratch database at 0007.

**I6 — The sweeper's new DELETE reaches every tenant's run jobs. Erratum 61's "used only for finished maintenance
rows" is enforced by statement text alone.**

Where: the `jobs` cell (1435-1437, 1671); the `PURGE` statement (4094-4097); erratum 61 (4822-4823).

Evidence:
- `GRANT … DELETE ON app.jobs TO sweeper`, combined with `sweeper_all … FOR ALL TO sweeper USING (true)`
  (`privileges.py:260`), lets the sweeper role delete any job of any tenant.
- Those include run jobs, whose dedup keys the plan itself calls "what makes a wake-up happen once" (4054-4055).
- Every other authority narrowing in this codebase is a database cell or policy, not a convention. The plan's live
  tests prove only that the purge statement filters correctly (4546-4574), not that the role cannot do more.

Fix:
1. Add a restrictive policy: `CREATE POLICY sweeper_purge_maintenance ON app.jobs AS RESTRICTIVE FOR DELETE TO
   sweeper USING (run_id IS NULL AND done_at IS NOT NULL)`.
2. Drop it in the downgrade.
3. Extend R106's expected policy set at `test_roles_live.py:273-276`, which asserts every policy is PERMISSIVE/ALL.
4. Add a live assertion that the sweeper's `DELETE … WHERE id = <a run's done job>` deletes 0 rows.

Alternatively, reword erratum 61 to "restricted by the statement only" and add a debt line. That is weaker.

**I7 — The re-arm does not repeat the scan's clock comparison or its newest-job choice after it takes the row (Plan H
lesson: compare clocks after the lock).**

Where: `REARM` (4089-4093); Review Focus 4 (119-122), which claims the re-arm re-checks.

Evidence:
- `REARM` re-checks `done_at IS NOT NULL`, the cap and the run's state. It does not re-check `done_at <=
  app.current_time() - grace`, and it does not check that the job is still the run's newest of its type.
- So a job re-armed by another hand, claimed and finished again between the unlocked scan and this UPDATE (fresh
  `done_at`, inside the grace) is re-armed at once.
- Likewise, if a newer job of the same type was inserted after the scan, the old one is reopened beside it: two open
  wake-ups for one run.
- The handlers' own state checks make both harmless today. But this is the comparison-before-lock pattern the brief
  asks reviewers to catch, and the docstring and Review Focus 4 claim more than the SQL does.

Fix: `… AND j.done_at <= app.current_time() - make_interval(secs => %s) AND NOT EXISTS (SELECT 1 FROM app.jobs o
WHERE o.run_id = j.run_id AND o.type = j.type AND o.id <> j.id AND (o.done_at IS NULL OR o.done_at > j.done_at))`.
Add the grace to the params, and add one unit assertion each.

---

### Minor

**M1 — The README status line loses its separator** (5137-5141). The old tail is `"…router (T12) and fenced run
leases … (T13) run locally**"`. The replacement starts at `fenced`, so the result reads "…AM-16 router (T12) fenced
run leases with a heartbeat (T13) and a gap-free event journal…". I verified this by running the plan's script. Fix:
start `new` with `", fenced run leases …"` (or keep `"and"` and write `"…(T13), and a gap-free…"`).

**M2 — `pull_forward`'s docstring overclaims, and the pull-forward also cancels deliberate delays** (3986-3999; the
`release_lease` comment 3970-3971).
- A claim can take the lease row with NOWAIT just before the release, see the lease live, and roll back its
  savepoint. It still holds the job row until its commit. The release's `SKIP LOCKED` then skips that row, and the
  claim commits `available_at = old lease_until`. The job waits up to the old lease end after all: residual, bounded,
  acceptable, but "its NOWAIT meets this release's lease lock" is not always true.
- Separately, the UPDATE pulls forward any future-dated undone job of the run. That includes deliberate delays: a
  `requeue_job` backoff of a job other than the releasing one, and T22's `recover` cadence (`RECOVER_CADENCE`).
- Fix: reword the docstring, and either restrict the UPDATE to `available_at <= <the lease_until being released>` or
  add a debt line → T22.

**M3 — `asyncio.wait_for(b_task, timeout=5)` cancels a database unit when it fails** (2190, 2262). On failure the
cancelled task's connection can stay INTRANS holding the run row, and `purge_run` in `finally` (on `app_conn`, no
`lock_timeout`) then waits for good: a hang instead of a red test. Fix: `SET lock_timeout` on `app_conn` before the
purge, or `await asyncio.wait({b_task}, timeout=5)` and close `b_conn` when it is still pending.

**M4 — Review Focus 1 is pinned only by SQL text** (108-112, 2703). No test records a stale result. Fix: add a live
case in `test_outbox_live`:
1. claim with `Crashing`;
2. move the clock past the lease;
3. claim and deliver again;
4. run `_record` for attempt 1 and assert `recorded is False` and the row still `delivered` at attempt 2.

**M5 — Two sweepers can double-announce a dead letter, and that is cheap to close now instead of a T30 debt line**
(debt 390-392; `_notify` 3108-3127). Taking `SELECT pg_advisory_xact_lock(hashtext(%s))` on the outbox id as the
first statement of the `_notify` unit serialises the re-check and the append without a table lock, so it stays out of
the lock order.

**M6 — The journal test's docstring claims what nothing exercises** (2100-2101): "an outbox intent written twice for
one run under contention". Each run's outcome is appended by one mcp actor, so nothing contends on an intent. Drop the
clause or add two concurrent `record_outcome` replays.

**M7 — The wake-up scan evaluates the lateral for every run of every tenant on every tick** (4079-4088), and runs are
never deleted. Add `AND r.state IN ('QUEUED', 'APPROVED')` as a plain `WHERE` filter so only waiting runs reach the
lateral.

**M8 — Writer's risk 5 (R105) has a cheap guard** (5328-5330). The skeleton's sweeper now re-arms leftover QUEUED and
APPROVED runs of any tenant, and its worker would run them (consuming the single model permit) during R105. Turn a
silent cross-test interaction into a clear failure: assert in the R105 fixture, before `sk.start()`, that no
QUEUED/APPROVED run has a done wake-up job.

**M9 — The catalog test keys function bodies by `proname`** (1962), so overloads collapse and the last one wins: a
second overload's body is never scanned for `INSERT INTO jobs`. Key by `p.oid` (or the `regprocedure` text) and
follow calls by name to every overload.

**M10 — The delivery loop claims every tenant first and delivers afterwards** (3068-3100). Each row's claim→result
window grows by every delivery queued ahead of it. That is harmless with `LogSink`, but with a slow T39 sink later
rows outlive their 30 s lease. Claim and deliver per tenant (or note it on the T39 debt line).

**M11 — "Debt before code"**: the close-out re-homes the `_idempotent` "use a new key" line (T14/T28 → T28,
4860-4861), but the Plan I debt list committed in Task 1 does not carry it. Add the line there.

**M12 — Wording.** ARCHITECTURE (5069) says a notification is "delivered at least once". A dead-lettered one is not:
say "attempted until delivered or dead-lettered". The runbook's "for an execute job, often a refused grant: a stale
membership" (5037) names the one refusal that re-queues instead of finishing (see I3).

---

### Checked and found sound

**Proof of R089 (apart from B1 and I4).**
- `stepped()` cannot pass vacuously. The reader is the real route on the right tenant, `wait_until_blocked` fails if
  B is never blocked, and the later `== [n]` and `== [n + 1]` reads fail if the earlier `== []` was empty for the
  wrong reason.
- The rollback test pins `b_got == [taken] == [2]` and `seen == [1, 2]`.
- The four roles really write:
  - `transition_run` → `_transition` → `_append_event`, emitting `clarification.requested`;
  - the api's and the sweeper's `append_event`;
  - mcp_exec's `mark_sent`, `grant_execution` and `record_outcome`, through staged handles at the staged fence.
- The count reader's single-statement snapshot is a real hole detector.

**Payload rules.**
- The unknown-key check comes before the source checks, so every existing refusal keeps its verdict (the run-path
  live cases at `test_definers_run_path_live.py:220-234` all stay OC006).
- Schema rule 9 is last, so `event-invalid-destination-granted` still fails for its type first (verify_handoff
  passes).
- `PAYLOAD_KEYS_0008`, `PAYLOAD_KEYS` and the schema are tied together by unit tests.

**The intent.**
- It is inserted after the events insert, inside the `runs` lock, as `app_definer` (the helper is SECURITY INVOKER,
  called from definers).
- The tenant is already set by `_tenant_of_run`/`_resolve_handle`, so RLS `WITH CHECK` holds.
- A target-less `ON CONFLICT DO NOTHING` needs no SELECT (the same shape as `insert_job_untargeted`).
- `format('%s:%s:local:%s', …)` has no SQLAlchemy bind (each colon follows a word character), and
  `test_transitions_table` scans 0008.
- A replayed `record_outcome` returns at `RESOLVED` before any append (0007:249-251), so it adds neither an event nor
  an intent.

**The outbox and delivery.**
- `tenant_isolation` covers `sweeper`, and the outbox has no `sweeper_all`.
- `for_each_tenant`/`in_tenant` set the tenant transaction-locally.
- The sweeper has SELECT on `events` and `runs` for the claim's join and the scan.
- The claim's `FOR UPDATE SKIP LOCKED` subquery inside the UPDATE re-evaluates `leased_until <=
  app.current_time()` on the locked row.
- Every result statement is guarded by `attempts = %s AND delivered_at IS NULL`.
- `notification.failed` runs in its own unit after the result unit, with the re-check in the same transaction as the
  append. The R024 test sequence gives exactly the matrix evidence.
- `Faults` refuses outside the test profile, and the production `Deps` builds `LogSink()` with no faults.

**Lock order.**
- `_append_event` takes runs → events → outbox. `record_outcome` takes run_lease S → runs → action_attempt_state →
  events → outbox.
- The claim and result units take outbox only.
- notify takes runs → events (outbox read without a lock).
- The re-arm takes jobs only; the purge, jobs only.
- The release takes run_lease X → invocation_context → own job → other jobs SKIP LOCKED → run_lease. The claim takes
  jobs SKIP LOCKED → run_lease NOWAIT.
- An intent insert that meets a non-HOT outbox update can wait on the sweeper's outbox unit, which never takes runs:
  no cycle.
- No unit takes both `outbox` and `jobs`.

**Revision 0008.**
- `0003` is the only revision that ever defined `_append_event`, so restoring its `APPEND_EVENT_HELPER` is exact.
- `JOB_CELLS_0002` equals today's jobs row minus DELETE.
- `MAIN_GRANTEES_0008` equals `MAIN_GRANTEES`.
- The testclock branch (`depends_on = 0002`) is unaffected by a downgrade to 0007.
- The existing 0006 and 0007 round trips pass through 0008's downgrade.
- `PURGE_ORDER` deletes `outbox` before `events`, and nothing else in tests deletes events or runs directly.
- R124, R084, R128 and R106 iterate the matrix, so they pick up the outbox row and its policy.

**Wake-up live tests.**
- `finish()` stages the job on the application clock.
- The re-armed row is claimed with `attempts == 2` under a fresh lease at fence 1.
- `Deferred(resume)` and the `behind` check follow `claim_next`'s busy-lease branch.
- The purge test's maintenance rows satisfy `jobs_tenant_iff_run_check`, and the open row's NULL interval yields NULL
  `done_at`.

**Close-out.**
- The handoff script rewrites only T14, R024 and R089.
- Errata 60-71 each match an implemented change (apart from I2's and I6's wording).
- The `TODO(T14)` sweep is empty after Task 5.


## Controller rulings

# Plan I review, round 1 — controller rulings

Input: `round1-static.md` (REVISE: 1 Blocking, 7 Important, 12 Minor; splices, format, mypy, dev counts and red steps
all verified on a scratch tree). The plan writer's own task-by-task dry run stands in for a separate builder dry run
this round (no live step can run in a dry run: the permission policy refuses copying `.env` into a worktree).

- **B1 — ACCEPTED.** Compute every backend pid before the transactions start (as Plan H's `test_leases_live.py:120`),
  in the rollback test and in `stepped()`; no `backend_pid` call while another statement may hold that connection.
- **I1 — ACCEPTED.** Dead-letter at claim time once a row's `attempts` has reached the cap (so a row whose delivery
  crashes is still bounded); run the wake-up sweep before delivery in the tick; a crash in one tenant's delivery must
  not skip the other steps of the tick — order the steps so the record and the wake-up sweep happen first, and say
  in the runbook what a crashing delivery looks like. No new broad `except` beyond what Global Constraints allow; if
  the plan needs one at the sink boundary, it carries its reason and re-raises nothing silently (log + count as a
  failed attempt).
- **I2 — ACCEPTED, add the trigger.** Trigger set = `action.confirmed`, `action.failed`, `action.conflict` (the
  escalation that exists today), `run.escalated`, `run.abandoned_unverified`. Docs, erratum 66 and the runbook say
  which of these have an emitter today (the first three) and which arrive with T22 (the last two); a debt line names
  T22.
- **I3 — ACCEPTED.** The re-arm excludes runs with `cancel_requested`; correct the live test's docstring and the
  runbook example; debt line → T21: grant refusals the worker treats as final must move the run out of APPROVED
  (BLOCKED_REVIEW per AM-10) so the sweep stops re-arming them; meanwhile the attempts cap bounds the re-dispatches —
  say so.
- **I4 — ACCEPTED.** Each run's final reader cursor equals `next_event_seq`; a floor on non-empty pages; the counting
  reader saw the counter grow.
- **I5 — ACCEPTED.** The round trip compares column privileges (including the `jobs` UPDATE cells 0008 touches) and
  the restored `_append_event` body against 0003's (0007's pattern: compare `prosrc`/definition, ACL, owner, config
  against a scratch database built straight to 0007, or the loaded 0003 text).
- **I6 — ACCEPTED.** A restrictive policy limits the sweeper's DELETE on `jobs` to maintenance rows
  (`run_id IS NULL`); R106's policy text test updated; a live check that the sweeper cannot delete a run job.
- **I7 — ACCEPTED.** The re-arm UPDATE re-checks, after taking the row, the grace on `app.current_time()`, that the job
  is still the run's newest of its type, that it is still done, and the run's state and `cancel_requested`; Review
  Focus 4 states exactly what the SQL checks.
- **Minors — ACCEPTED** as the critic proposes, with these choices: the pull-forward moves only jobs deferred behind the
  lease being released (`available_at <= the released lease's lease_until`, read in the same unit), so deliberate
  delays (requeue backoff, T22's cadence) survive — correct its docstring; the two-sweeper double
  `notification.failed` is closed now with a transaction advisory lock on the outbox id (or a per-tenant
  `pg_try_advisory_xact_lock`) instead of a T30 debt line — place it in the lock order; `wait_for` must not cancel a
  database unit (shield or restructure); the catalog test keys bodies by OID (overloads); the R105 fixture checks for
  leftover waiting runs; the `_idempotent` debt line moves into the Task 1 debt list; the wording fixes as proposed.
  Decline any minor only with a reason in "Round 1 changes".

Apply in one pass; re-run the task-by-task apply with `ruff format` between tasks, the splice check and the dev counts;
append "Round 1 changes" / "Round 1 open points". Do not commit.

---

# Round 2

## Static review

## Plan I round 2: static adversarial critic

Plan: `docs/superpowers/plans/2026-10-15-first-slice-i-journal-wakeups-outbox.md` (5,920 lines, branch `plan-i`,
19e8d13 "Plan I round 1 fixes").

**Verdict: REVISE (light).** 0 Blocking, 1 Important, 5 Minor.

All 20 round-1 findings are fixed as ruled (B1, I1-I7, M1-M12). Applied task by task to a `git archive HEAD` copy,
the plan is clean:
- every quoted old text matches exactly once;
- `ruff format` changes nothing after any task;
- ruff, mypy strict (53/53/53/55/56 source files) and `verify_handoff` (exit 0) pass after every task;
- every dev count and every red or intermediate Expected line matches.

The one Important finding is a consequence of I1's chosen fix rather than a regression of it. When a delivery crashes,
the rows claimed in the same batch behind the crashing row each burn an attempt per crash. After five crashes they are
dead-lettered and announced as "could not be delivered after 5 attempts", although they were never handed to the
sink. The tick also skips every later tenant and every announcement on each crash tick. The ruling explicitly allowed
the fix that avoids all of this (a sink-boundary catch that logs and counts a failed attempt), and the plan declined
it.

### How this was checked

**Applying the plan.**
- I made a `git archive HEAD` copy in `critic2/tree` as its own git repo and ran `uv sync --frozen` (its own venv).
- I applied Tasks 1-6 in order with the round-1 Edit/Create parser (`apply_plan.py`), running `ruff format`, ruff,
  `scripts/check.py` and `verify_handoff` between tasks (`critic2/run.sh`, `run_1_5.txt`, `check_N.txt`, `vh_N.txt`).
- Task 6's handoff and README scripts were extracted verbatim from the current plan (`critic2/handoff_script.py`,
  `readme_script.py`) and run.

**Red and intermediate steps.** Each step's blocks were applied up to its marker on the previous task's commit
(`critic2/partial.sh`, `reds.sh`, `reds.txt`).

**Reading.**
- All of the plan, `round1-static.md`, `round1-rulings.md`, the brief, and the round-1 diff (`critic2/r1.diff`).
- Against the tree: `persistence.claim_next`, `release_lease`, `tenants` and `set_tenant`; 0007's `record_outcome` and
  `mark_unknown`; 0003/0004 helper calls (all `app.`-qualified, so `CALLS` finds them); `locking.py`; `main.run_forever`;
  `DbStore.events`; `conftest.backend_pid` and `wait_until_blocked`; the 0007 live round trip's helpers; R106; the
  other policy-counting tests.

**Not run.** No live test, no database.

| After task | not found | ruff format | ruff check | mypy strict | pytest (dev) | plan says | verify_handoff |
|---|---|---|---|---|---|---|---|
| base (HEAD) | - | - | - | - | 939 / 134 | 939 / 134 | - |
| 1 | 0 | no change | clean | clean, 53 | **1001 / 134** | 1001 / 134 | 0 |
| 2 | 0 | no change | clean | clean, 53 | **1007 / 140** | 1007 / 140 | 0 |
| 3 | 0 | no change | clean | clean, 53 | **1007 / 144** | 1007 / 144 | 0 |
| 4 | 0 | no change | clean | clean, 55 | **1022 / 149** | 1022 / 149 | 0 |
| 5 | 0 | no change | clean | clean, 56 | **1030 / 154** | 1030 / 154 | 0 |
| 6 | 0 | no change | clean | clean | **1030 / 154** | 1030 / 154 | 0 (35 accepted, 54 negative) |

Red and intermediate Expected lines (all match):

| Task | Step | Got |
|---|---|---|
| T1 | S3 | `1 error` |
| T1 | S4 | `10 passed` |
| T1 | S5 | `1 error` |
| T1 | S7 | `335 passed, 19 skipped` |
| T1 | S8 | `89 passed` |
| T2 | S1 | `1 error` (the `REVISIONS` assert) |
| T2 | S2 | `3 failed, 15 passed`, the three named tests with exactly the plan's `KeyError: 'outbox'`, `AttributeError … SWEEPER_PURGE` and `AssertionError: jobs` |
| T2 | S3 | `63 passed` |
| T4 | S1 | `2 errors` (`SWEEPER_FAULTS`) |
| T4 | S2 | `1 error` (`outbox`) |
| T4 | S3 | `17 passed` |
| T4 | S4 | `83 passed` |
| T5 | S1 | `1 error` (`wakeups`) |
| T5 | S2 | `20 passed` |
| T5 | S3 | `7 passed` |
| T5 | S4 | `102 passed` |

Live arithmetic (collected counts): T2 S5 = 6 + 5 + 7 + 7 + 8 + 11 = **44**; T3 = **4**; T4 S5 = 5 + 4 + 6 = **15**;
T5 S5 = 5 + 11 + 4 + 4 = **24**. These are as stated. The live gate is the dev count plus the live-gated tests (dev skips
minus 21): 1126 / 1130 / 1150 / 1163, as stated.

Task 6:
- `TODO(T14` grep: empty.
- The matrix diff: R024 and R089 only.
- The handoff diff: three files.
- The README tail now reads "…AM-16 router (T12), fenced run leases with a heartbeat (T13) and a gap-free event journal
  … (T14) run locally**" (M1 verified by running the script).

---

### Round-1 verification

| Finding | Status | Evidence |
|---|---|---|
| B1 pid after block | FIXED | `stepped()` reads `a_pid, b_pid` first (2407). The rollback test reads `api_pid, worker_pid` before `new_run` and before the transaction (2492). No `backend_pid` call remains while another statement may hold the connection. |
| I1 crashing delivery unbounded / starves tick | FIXED as ruled (but see **N1**) | `EXHAUSTED` runs first in the claim unit (3248-3251, 3351-3354), and the claim requires `attempts < %s` (3257). `sweep_wakeups` runs before `deliver_outbox` (4683), whose `record` comes first (3605). Unit test 2971-2989; live crash-at-cap test 4045-4075 (timing checked: 0/31/62 s offsets against 30 s leases). Runbook 5478-5482; erratum 67. No broad `except` added. |
| I2 escalation never notified | FIXED | `action.conflict` is in `NOTIFY_TYPES_0008` (1479-1485) and in the unit test (1293-1299). 0007's `record_outcome` CONFLICT path does `_transition(…'ESCALATED'…)` and then `_append_event('action.conflict')` in the same function, so the same transaction: the intent commits with the escalation. Erratum 66, the runbook (5466-5467), the handoff note and the debt line (423-425) name the emitters. |
| I3 cancelled / refused re-dispatch | FIXED | `NOT r.cancel_requested` is in `LOST` (4505) and in `REARM`'s `EXISTS` (4517). The live cancel case is at 4939-4942. The docstring (4852-4855), the runbook example (5539-5542), the debt line (426-428) and erratum 63 are corrected. |
| I4 vacuous readers | FIXED | Per-run `last == next_event_seq`, `pages >= 20` and `len(highs) > 1` (2690-2691), after a drain (2612-2614). A reader on the wrong tenant now fails `last == counter`. The drain yields at most ⌈N/500⌉ pages, so 20 non-empty pages can only come from reading during the writes. |
| I5 weak round trip | FIXED | `CELLS` unions `role_table_grants` and `column_privileges` (1937-1942). The restored `prosrc` is compared with 0003's text (2010-2011). `FUNCTION_DETAILS` and the cells are compared with a scratch database at 0007 (1956-1975, 2012-2015). Non-vacuous: `head` must contain the sweeper's DELETE cell, an empty reference fails the comparison, and the prefix `r007_` differs from 0007's `r006_`. |
| I6 sweeper DELETE reaches run jobs | FIXED | The restrictive policy (1663-1669) is dropped first in the downgrade (1671). `SWEEPER_PURGE` carries the stored qual. R106 expects the policy (1868-1883). The live test 2169-2199 is non-vacuous: the run job is made "finished", so only the policy blocks it. See "Checked and sound" for how the policy combines. |
| I7 re-arm trusts scan | FIXED | `REARM` (4511-4518) repeats `done_at IS NOT NULL`, the cap, the grace on `app.current_time()`, newest-of-type (`NOT EXISTS … o.done_at IS NULL OR o.done_at > j.done_at`) and state plus `NOT cancel_requested`. The parameter order (job, cap, grace, state) matches. Review Focus 4 lists exactly these. |
| M1 README separator | FIXED | Script output verified (above). |
| M2 pull-forward overclaim / deliberate delays | FIXED | `available_at <= (SELECT l.lease_until … )` (4403). It is read in the release unit after `LOCK_FOR_UPDATE` and before the lease row's `-infinity` update (the order is pinned by `test_worker_units`). The live ten-minute check is at 5000-5012. The docstring states the NOWAIT residual. |
| M3 `wait_for` cancels a unit | FIXED | `settle()` (2384-2392) uses `asyncio.wait` and never cancels. A pending writer's connection is closed (psycopg's `close()` takes no connection lock). `stepped` releases B in `finally`. The `wait_for` left at 2427 only waits on an `asyncio.Event`. See **N3** for the rollback test's failure path. |
| M4 Review Focus 1 untested | FIXED | Live test 4078-4104. |
| M5 two sweepers double-announce | FIXED | `ANNOUNCE_LOCK` is the first statement of `_notify`'s unit (3431); the recheck is a new READ COMMITTED snapshot after the lock. See "Checked and sound" for the key space and **N5**. |
| M6 docstring overclaim | FIXED | The journal docstring no longer claims a contended intent. |
| M7 lateral on every run | FIXED | `WHERE r.state IN ('QUEUED', 'APPROVED') AND NOT r.cancel_requested`, a plain qual on `r` that the planner pushes below the lateral. |
| M8 R105 cross-test | FIXED (see **N4**) | Check at 4836-4842. |
| M9 overloads collapse | FIXED | Keyed by OID; a call by name reaches every overload (2144-2156). Helper calls in 0003-0007 are all `app.`-qualified, so `CALLS` finds them, and the reachable-helper assertion prevents a vacuous pass. |
| M10 claim-all-then-deliver | FIXED | Per-tenant claim, deliver and record; unit test 3007-3016. |
| M11 `_idempotent` debt line | FIXED | Debt list 429-430. |
| M12 wording | FIXED | ARCHITECTURE 5574-5575; runbook 5539-5542. |

---

### Blocking

None.

### Important

**N1: A crashing delivery dead-letters the rows claimed with it, though they were never delivered. On every crash tick
it also skips later tenants and all announcements.**

Where: `outbox.deliver` (3371-3420) and its "Raises" docstring (3382-3385); `EXHAUSTED` (3248-3251); Global
Constraints 76-78; erratum 67 (5323-5329); runbook 5478-5482; the I1 ruling ("if the plan needs one at the sink
boundary, it carries its reason … log + count as a failed attempt").

Evidence:
- `_claim` takes up to `batch` rows per tenant, oldest by `created_at`. Each gets `attempts + 1` and a 30 s lease.
- `deliver` then hands them to the sink one by one, in `outbox_id` order (3260).
- When the sink raises anything but `SinkFailed`, the exception leaves `deliver` at once. The remaining claimed rows
  are neither delivered nor recorded. They stay leased with one attempt counted.
- The next claim after the lease takes the same oldest rows again, the poison row included. Every row that sorts after
  the poison row in `outbox_id` order (it is the same order every time) burns another attempt without delivery.
- On the fifth crash those rows reach `attempts = 5`. When their lease runs out, `EXHAUSTED` dead-letters them together
  with the poison row, and `notify_dead_letters` appends `notification.failed` "could not be delivered after 5 attempts"
  for each. None of them was ever handed to the sink.
- The docstring promises the opposite ("a crashed delivery is retried, never lost"). It is literally true only of the
  crashing row.

On each crash tick the exception also:
- skips every tenant after the crashing one (`persistence.tenants` is `ORDER BY tenant_id`, so the same tenants each
  time, typically on consecutive ticks because tick ≈ lease = 30 s);
- skips `notify_dead_letters` for all tenants.

The runbook admits the tenant skip ("Until then the tenants after the crashing one wait for the following tick") but
not the collateral dead letters. Before round 1 those batch-mates starved without bound. Round 1's cap converts that
into wrongful dead letters with failure events on the requester's run, a false audit trail. It needs only one process
and one row that deterministically crashes the sink (for example a T39 sink bug on one payload). It is cheap to close
now.

Fix (the ruling's own option; recommended):
- In `deliver`, at the sink boundary, `except Exception as exc:` with a reason comment (the ruling permits it). Log the
  exception with its traceback (`log.exception`, as `run_forever` does) and treat it as a failed attempt:
  `result = "dead_letter" if attempts >= cap else "retrying"`, through the normal `record_result`.
- The crashing row then backs off and dead-letters at the same cap, as a refusal does. Its batch-mates and the other
  tenants are delivered, and `notify_dead_letters` runs every tick. `EXHAUSTED` stays as the backstop for a killed
  process.
- Update Global Constraints 76-78, the `deliver` docstring, `test_an_unexpected_sink_error_leaves_the_row_leased` (it
  becomes "is recorded as a failed attempt"), the live crash tests (Crashing then records `retrying` and the row comes
  back after its backoff, not its lease), erratum 67 and the runbook.

Alternative without a broad `except`: a `try/finally` around the batch that, when a crash leaves rows unattempted, hands
them back in one unit before the exception propagates:
`UPDATE app.outbox SET attempts = attempts - 1, leased_until = '-infinity' WHERE outbox_id = %s AND attempts = %s AND delivered_at IS NULL`
for each row not yet handed to the sink (the sweeper holds both columns). This saves the batch-mates but keeps the
tenant and announcement skip.

Either way:
- add a unit test with a two-row batch whose first delivery crashes, asserting the second is delivered (or handed back
  with its attempt restored);
- state the residual: a process killed mid-batch still burns one attempt per unattempted row, so only a repeated kill
  dead-letters them. Claiming one row per unit would close even that.

### Minor

**N2: The claim-time dead letter does not advance `attempts`, so a second sweeper's late result can overwrite it.**

Where: `EXHAUSTED` (3248-3251) against `DELIVERED`/`RETRY`/`DEAD` (3262-3270); Review Focus 1.

Evidence: a row claimed at its last attempt (`attempts = cap`) whose delivery outlives the 30 s lease can be
dead-lettered by another sweeper instance's `EXHAUSTED`. That instance's tick then announces it. When the slow delivery
finally succeeds, `DELIVERED … WHERE attempts = cap AND delivered_at IS NULL` still matches (the attempt guard protects
only against a newer claim, which bumps `attempts`). The row ends `delivered` with a `notification.failed` on the run
saying it was not.

This needs two sweeper instances: a single process cannot run its next claim while its own delivery is in flight. That
is the same class as round 1's M5, which the plan chose to close now.

Fix: add `AND result IS DISTINCT FROM 'dead_letter'` to the three result statements (the dead letter stands; the
at-least-once debt line covers the extra delivery). Add one assertion in `test_a_delivery_runs_between_its_claim_and_its_result_unit`.
Optionally, in the crash-at-cap live test, call `record_result(row at cap, "delivered")` after the claim-time dead
letter and expect `False`.

**N3: The rollback test has no `finally` for its writer task.**

Where: `test_r089_a_rolled_back_writer_leaves_no_hole` (2493-2514).

Evidence: if `wait_until_blocked` raises inside `api.transaction(force_rollback=True)`, A rolls back, and B (never
settled) appends and commits while the test's `finally` runs `purge_run`. `purge_run`'s `DELETE` of the run row waits
on B's row lock and then hits the foreign key from B's committed event. That FK error masks the real failure and leaves
the run behind. It is not a hang (no cancellation, B is free once A ends), so it is not B1/M3 again.

Fix: as in `stepped()`, keep `b_task` in a variable initialised to `None` and `await settle(b_task, worker)` in
`finally` when it is not done.

**N4: The R105 leftover check is broader than what the sweeper would re-arm.**

Where: Task 5 Edit 12 (4836-4842).

Evidence: it counts every QUEUED or APPROVED run with no unfinished job, including:
- runs with no job at all;
- runs whose cancellation was requested;
- runs whose only done job is of the other type.

`LOST` never re-arms these, because the lateral needs a job of the state's type and `NOT cancel_requested` is required.
Any earlier module that leaves such a run behind now fails R105 on its first live run, for a run the skeleton would never
touch. Live tests generally purge, but this has never run.

Fix: count exactly the sweep's predicate: as the superuser (RLS bypassed), run `wakeups.LOST` with a grace of 0
(`conn.execute(wakeups.LOST, (0,))`, or its text inlined). It is still a superset of what the sweeper will see during the
module, because the grace only delays it.

**N5: Review Focus 2's "two sweepers" claim is pinned by statement text only.**

Where: Review Focus 2 (122-126); `test_a_dead_letter_gets_its_event_in_a_transaction_of_its_own` (3019-3037).

Evidence: the unit test asserts that `ANNOUNCE_LOCK` is the unit's first statement. The `Raced` test fakes an empty
recheck. No test shows a second `_notify` waiting on the lock and then finding nothing. The design is right (see
"Checked and sound"), so this is a wording point.

Fix: say "pinned by the statement order (unit) and the re-check". Or add a cheap live case: one connection holds
`pg_advisory_xact_lock(2, hashtext(id))` and appends the event uncommitted; a second `_notify` task blocks
(`wait_until_blocked`); commit; the second returns `False`. The pids must be read first (B1).

**N6: Stale text.**

- Self-review, known risks (5841-5843): "the reader floors (100 pages, 100 counts)". The floors are now ≥ 20 non-empty
  pages per run and more than one distinct maximum.
- Task 6 Step 1 (5117-5119): its owner list names T30, which is no longer on the debt list (the two-sweeper line was
  removed in round 1), and omits T29 (dashboards, T28/T29).

---

### New-change hunt: checked and sound

**Claim-time dead letter (`EXHAUSTED`).**
- It respects the lease (`leased_until <= app.current_time()`), so it can never dead-letter a delivery within its lease.
  In a single sweeper it cannot meet an in-flight delivery at all: the next claim runs after the current tick's delivery
  returns.
- It matches only rows at or over the cap that are not `dead_letter` (crash-at-cap, or a lowered cap). A `SinkFailed` at
  the cap is already `DEAD`.
- It runs inside `in_tenant`, so RLS narrows it to the tenant. It needs only the sweeper's SELECT and the `result` cell.
  It locks only `outbox` rows: waiting there cannot cycle, because no `outbox` holder waits on `runs`.
- Gap: the late-result case, N2.

**Tick order.**
- The order is sync, its record, purge, reclaim, `sweep_wakeups` (sweep, maintenance purge, record), then
  `deliver_outbox` (record, deliver, notify).
- A crash in delivery cannot stop run progress. It can stop later tenants and announcements (N1).
- A failure in `sweep_wakeups` skips delivery for that tick. That is acceptable, and the converse of the ruling's
  concern.

**Advisory lock `pg_advisory_xact_lock(2, hashtext(%s))`.**
- `(int4, int4)` is the two-key form. PostgreSQL keeps the one-bigint key space (the asset guard's
  `hashtextextended(…)`) and the two-int4 key space apart (they never overlap), and class 2 differs from the
  idempotency lock's class 1.
- The `str` parameter is sent as `unknown` and resolves to `hashtext(text)`.
- A hash collision only serialises two unrelated announcements. Each unit takes exactly one such lock, first, then
  `runs` and `events`, and no unit takes `runs` before it, so no cycle.
- Placement after `advisory:asset` and before `runs` is consistent (`test_locking_t14` asserts it).

**`action.conflict` as a trigger.**
- It is appended by `record_outcome` in the same function, so the same transaction, as the ESCALATED transition (or
  without one when the run is already ESCALATED). The lock order is run_lease S → runs → action_attempt_state → events →
  outbox.
- Late evidence is `action.late_evidence` (not a trigger). A replay returns at RESOLVED before any append. So one
  outcome intent per run today: confirmed, failed or conflict, never two. The dedup key is per type, and no path emits a
  second outcome type for one run.

**Restrictive `sweeper_purge_maintenance`.**
- It is `FOR DELETE` only, so it is not applied to the sweeper's SELECTs, the reclaim's and re-arm's UPDATEs, or
  `FOR UPDATE` locks.
- For a DELETE it is ANDed with the permissive `sweeper_all`/`tenant_isolation`. `sweeper_all` is a permissive policy
  that applies to DELETE, so the "at least one permissive policy" rule holds.
- No sweeper code path deletes from `jobs` except the purge.
- `test_migrations_and_persistence`'s full downgrade still reaches 0 policies (0008 drops it).
- The R106 columns (`permissive`, `cmd`, `roles` as list, `qual`, `with_check = None`) match the query.

**Round-trip comparisons.** Non-vacuous (see I5). `CREATE OR REPLACE` keeps `_append_event`'s ACL, so `FUNCTION_DETAILS`
matches a straight build. The testclock branch grants nothing on `jobs` or `outbox`.

**`settle()`.** It never cancels, and it closes a pending writer's connection, which ends its server transaction. No
transaction is left open on success. On `stepped`'s failure paths, A's `async with` rolls back first, so B always
proceeds. (N3 is the rollback test's missing `finally`.)

**Re-arm SQL.**
- The UPDATE alias form is valid. The subqueries see the statement snapshot, and EvalPlanQual rechecks the target row's
  own columns.
- A newer job of the type committed inside the UPDATE's own execution window can still be missed. That race is
  microseconds wide, the handlers' state checks make it harmless, and it is far narrower than the round-1 scan-to-update
  window.
- `app.current_time()` is read in the statement.

**Pull-forward.**
- The `lease_until` subquery runs in the release unit, after `LOCK_FOR_UPDATE`, which checked the lease live, and before
  `lease_until = '-infinity'`. So it reads the held lease's end.
- `claim_next` defers either to exactly that `lease_until` (≤ holds) or to now + 1 s when the lease row was locked. That
  job is held by the claim's transaction and skipped (SKIP LOCKED), the residual the docstring states.

**Lock order, end to end.**
- `_append_event`: runs → events → outbox (FK key-share on its own rows).
- Claim and result units: outbox only.
- Announcement: advisory → runs → events (no outbox insert: `notification.failed` is not a trigger).
- Re-arm and purge: `jobs` only (reads of `runs` unlocked).
- Release: run_lease X → invocation_context → own job → other jobs SKIP LOCKED.
- No inversion.

**RLS / tenant settings.**
- `set_tenant` is `set_config(…, true)` and refuses outside a transaction.
- Every sweeper read or write on `outbox`, `runs` and `events` runs in `in_tenant`.
- The purge relies on `sweeper_all` without a tenant.
- Test connections are autocommit, so the bare statements in the policy tests are their own transactions.

**No database unit cancelled.** The only `wait_for`s are on `asyncio.Event` (2427) and the sweeper's `stop` wait.
`gather` cancels nothing on failure.

**Docs against tests.**
- Errata 60-71, the handoff note, the R024/R089 matrix notes, ARCHITECTURE and the runbook (the 30 s tick, `sweeper tick
  failed`, the triggers, refused grants) match the implemented code and tests. The exceptions are N1's undisclosed
  collateral dead letters and N5/N6.
- The live module counts the plan states match collection.


## Controller rulings

# Plan I review, round 2 — controller rulings

Input: `round2-static.md` (REVISE light: 0 Blocking, 1 Important, 5 Minor; all 20 round-1 findings fixed; executability
and dev counts verified).

- N1 (Important) — ACCEPTED: a sink-boundary catch around the per-row `sink.deliver` only (`except Exception`, reason
  stated, listed in Global Constraints), logged with the traceback (no payload content) and recorded as a failed attempt
  through the normal backoff/dead-letter path; a crash costs that row one attempt and touches nothing else; unit test
  (+ live if cheap); runbook wording.
- N2 — ACCEPTED: `result IS DISTINCT FROM 'dead_letter'` on the three result statements.
- N3 — ACCEPTED: the rollback test settles its writer in `finally` before the purge.
- N4 — ACCEPTED: the R105 leftover check reuses the sweep's `LOST` query with grace 0.
- N5 — ACCEPTED: reword the two-sweeper claim to what is shown; no new test.
- N6 — ACCEPTED: stale self-review text; Task 6 owner list T29.

Closure: N1's fix is small and local; the controller verifies the fix diff directly instead of a third round (Plan H
precedent: round 3's single Important was closed by a verified small change).

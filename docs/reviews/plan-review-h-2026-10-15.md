# Plan H review record — T13 run lease, fence locking, heartbeat thread and fault factory

Plan: `docs/superpowers/plans/2026-10-15-first-slice-h-leases-fences-heartbeat.md` (branch `plan-h`; plan commit 03e2636,
round fixes 11342fa, 6ca01b3 and 5a36414). Inputs: `docs/superpowers/research/2026-10-15-plan-h-inputs.md` and the controller's
rulings brief (reproduced below). Each round is one static adversarial review of the plan text plus one builder dry run in a
detached scratch worktree, followed by the controller's rulings and the fix commit. The dry runs executed every dev step and
gate; the live steps were not run in any dry run, because the tool permission policy refused copying `.env` into the scratch
worktree (round 1) and the controller did not route around it; the live half is proven during execution in the main checkout.
The review closed after round 3 (0 Blocking, 1 Important fixed in a small verified change, 0 workarounds).

---

# Controller brief (rulings before round 1)

# Plan H brief — controller rulings for T13 (run lease, fence locking, heartbeat thread, fault factory)

Branch `plan-h` (= `plan-g` 954ef58). Fact sheet: `docs/superpowers/research/2026-10-15-plan-h-inputs.md` (cited
"FS §n" / "FS Qn"). No separate spike: the measurable facts (row locks need UPDATE: Plan E ruling 23; PG lock
semantics; psycopg sync connection in the lock) are known; each task's red tests measure the rest. Errata continue at
**45**. Requirements: R019, R020, R087, R088, R098, R107.

## Rulings (one per FS question)

1. **Row locks in definers (FS Q1).** Grant `app_definer` `upd(fence)` on `run_lease` (new matrix cell, revision
   0007). That lets definers take `FOR SHARE`/`FOR UPDATE` on `run_lease` and lets `mark_unknown` bump the fence.
   Erratum 45: SA:418 `app_definer` `sel, upd(fence)`.

2. **Lease row creation (FS Q2).** The worker creates it at its first acquisition. Acquisition (one statement block,
   worker role):
   `INSERT INTO app.run_lease (run_id, owner, lease_until, fence) VALUES (r, '', '-infinity', 0) ON CONFLICT (run_id)
   DO NOTHING`, then `SELECT … FROM app.run_lease WHERE run_id = r FOR UPDATE NOWAIT`, then compare
   `lease_until <= app.current_time()` (after the lock, SA:157; `<=` so a released lease at `-infinity` and an exact
   instant both count as free), then `UPDATE … SET owner = me, fence = fence + 1, lease_until = app.current_time() +
   lease`. The first real fence is 1. `owner` is the worker name (`host:pid`). Erratum 46: SA:174 creation path and
   `<=`.

3. **Claim and lease are one transaction (FS Q3).** The worker's poll unit: claim one job (`FOR UPDATE SKIP LOCKED`,
   as today, per tenant) and, for a run job, acquire that run's lease **in the same transaction** inside a savepoint
   with `FOR UPDATE NOWAIT`. If the lease is live (another owner) or locked (55P03), roll back to the savepoint, set
   the job's `available_at` to the lease's `lease_until` (or `app.current_time() + 1 s` when locked) without claiming
   it, commit, and try the next job. So a claimed run job always has a live lease taken at the same commit: no crash
   window between claim and lease. Maintenance jobs never take a lease (worker does not claim them anyway). Jobs are
   wake-ups (SA:173): a job that turns out to have nothing to do is finished.

4. **FOR UPDATE vs FOR SHARE (FS Q4).** FOR UPDATE (from the transaction's first `run_lease` touch, SA:191):
   acquisition, heartbeat renewal, release, `mark_unknown`'s fence bump. FOR SHARE with fence + liveness check as
   the **first** statement: every other worker unit that writes anything for a run (transitions, events, handle
   minting, handle revocation while the lease is held, drafts, freeze, finish/requeue of a run job), and inside the
   definers that mcp-write and mcp-read call (`_resolve_handle` → `resolve_invocation`, `grant_execution`,
   `lookup_action`, `mark_sent`, `record_outcome`). Read-only worker units need no fence.

5. **How the fence reaches a write (FS Q5).** Worker side: the worker's own unit runs
   `SELECT 1 FROM app.run_lease WHERE run_id = %s AND owner = %s AND fence = %s AND lease_until > app.current_time()
   FOR SHARE` first (a `persistence.fenced(conn, lease)` helper; no row → raise `LeaseLost`, the unit rolls back).
   The worker-only definers (`transition_run`, `freeze_proposal`, `append_event`) keep their signatures: the caller's
   share lock in the same transaction is the fence (erratum 47: SA:453 lists `run_lease FOR SHARE` inside
   `freeze_proposal`; the worker takes it before the call instead). MCP side: `mint_handle` stores the current fence
   in `invocation_context.fence` and caps `expires_at` at `least(app.current_time() + 60 s, lease_until)` (BS:360,
   BS:558). `_resolve_handle` takes `run_lease FOR SHARE` and refuses (OC008, the existing handle refusal) unless
   `run_lease.fence = invocation_context.fence AND lease_until > app.current_time()`. `mark_sent` and
   `record_outcome` gain the raw handle as their first argument and run the same check (erratum 48: SA:463/464
   signatures `mark_sent(raw_handle, action_id)`, `record_outcome(raw_handle, action_id, outcome, doc)`; the
   SESSION_STATE Plan E debt line "binding the raw handle for mark_sent and record_outcome → T13/T22" closes).
   mcp-write passes the handle it already holds.

6. **Post-SENT fence failure (FS Q6).** A stale fence raises the handle refusal (OC008 → `HandleRejected`) inside
   `mark_sent`/`record_outcome`. Before SENT (`mark_sent`) it stays an error envelope `INVALID_HANDLE` (nothing was
   sent). After SENT (`record_outcome`), `HandleRejected` joins `_POST_SENT_REFUSALS` so the envelope is
   `outcome`/`UNKNOWN` with the action id — never an error envelope (execution.py:29-32 rule, Plan E final review I1).
   A test proves both sides.

7. **`resolve_invocation` fence (FS Q7).** T13 implements the check (ruling 5); T15's R027 test then exercises it
   end to end. T13's own test: a handle minted under fence f is refused after the fence moves to f+1 and after the
   lease expires.

8. **`revoke_handles(run_id, fence)` (FS Q8).** Revokes the run's live handles **minted under a fence ≤ p_fence**;
   never refuses for a stale fence (revocation only removes authority, so a worker that lost its lease can still
   revoke its own handles; a newer owner's handles survive). Takes `run_lease FOR SHARE` first only to order against
   acquisition. Python passes the lease's fence (no more literal `1`).

9. **`mark_unknown(run_id, fence)` (FS Q9).** `run_lease FOR UPDATE`; refuse (OC003 `VersionConflict`) unless
   `fence = p_fence AND lease_until > app.current_time()` (the function has no owner argument; the fence identifies
   the holder); set `fence = p_fence + 1`; revoke handles with fence ≤ p_fence; then the
   existing grant read / transition / recover job; **return the new fence** (signature returns a row or a pair; the
   plan picks the shape and states it). The worker hands the new fence to the heartbeat (ruling 10). T13 does **not**
   change the worker's transport-failure branch (it still re-queues; R109 and the AM-13 timeout path are T22's,
   erratum 14 stands); T13 makes the existing UNKNOWN-envelope call fence-correct.

10. **Re-fence hand-off (FS Q10).** One `Lease` object shared by the loop and the heartbeat thread: `run_id`, `owner`,
    `fence`, `deadline` (monotonic), guarded by a `threading.Lock`. `refence(new)` swaps the fence under the lock
    right after the bump commits (the bump and a renewal both take `FOR UPDATE`, so they serialize). A renewal that
    fails on a fence mismatch re-reads the shared fence under the lock: if it changed meanwhile, retry at once with
    the new one; only a mismatch against the *current* fence is a loss.

11. **Reclaim (FS Q11).** A sweeper routine with direct grants (erratum 26 precedent; erratum 49: SA:471
    `reclaim_leases` is the sweeper's routine, not a definer): each tick, un-claim run jobs (`claimed_by`,
    `claimed_at` → NULL; `done_at IS NULL`) whose run's lease is not live (`lease_until <= app.current_time()`, or no
    lease row). Because claim and lease commit together (ruling 3) and finish and release commit together (ruling
    28), "claimed, not done, lease not live" means the claimer crashed or lost the lease. Uses `sweeper_all` on
    `jobs` and `sel` on `run_lease`; no new sweeper grant. No `recover` job insertion (an EXECUTING run's re-claimed
    `execute` job resends under the same action id; recover jobs are T22's), no `model_permit` work (expiry is the
    release, ruling 12), no lost-wake-up sweep (T14).

12. **`model_permit` (FS Q12).** Revision 0007 creates `app.model_permit(slot smallint PRIMARY KEY CHECK (slot >= 1),
    holder text, run_id uuid, leased_until timestamptz NOT NULL DEFAULT '-infinity')`, no RLS, seeded with slot 1 by
    the migration (BS:549 concurrency 1). Grants: worker `sel, upd(all)`; **nobody else** (erratum 50: SA:432 drops
    the sweeper's `upd(leased_until)`; an expired permit is free by the same comparison, and an UPDATE with a WHERE
    needs SELECT anyway, erratum 25). Acquire in its own transaction: `UPDATE … SET holder, run_id, leased_until =
    app.current_time() + ttl WHERE slot = (SELECT slot … WHERE leased_until <= app.current_time() ORDER BY slot FOR
    UPDATE SKIP LOCKED LIMIT 1) RETURNING slot`; poll with capped exponential backoff plus jitter (0.25 s doubling
    to 2 s) until the caller's deadline (the lease's local deadline). ttl = 65 s (60 s model attempt + 5 s). Release
    in its own transaction (`leased_until = '-infinity'`, `holder = NULL WHERE slot AND holder = me`) on completion
    or cancellation; the TTL is the backstop. The release rule "hold until /api/ps idle" waits on T02's measurement
    and is T19's (debt line). Consumer now: the worker wraps the draft generator call (fake route today), so the
    permit is exercised and tested without Ollama.

13. **Global queue bound (FS Q13).** New definer `app.queued_runs_total()` callable by `api` only: iterates `tenants`,
    sets `app.tenant_id` per tenant (transaction-local), sums `count(*)` of QUEUED runs, returns one bigint (an
    aggregate across tenants: a documented load side channel, no ids). Setting `OPS_GLOBAL_QUEUE_LIMIT` (default
    100, bounds 1–100000) in `settings.admission()`; checked for run verdicts after the per-tenant quota (which
    stays, BS:550 "bounded tenant quotas"); full → the same 429 `RATE_LIMITED`, `Retry-After: 5`, unrecorded.
    Count-then-create is not atomic across scopes: the bound is soft by at most the number of concurrent admissions;
    say so in a comment and the runbook. Erratum 51 replaces erratum 39's "moves to T13".

14. **Lock order (FS Q14).** Published as data in `core/src/ops_core/locking.py` (`LOCK_ORDER`, with a docstring
    rule) and mirrored in `docs/ARCHITECTURE.md`/the runbook. The order constrains waits: row locks on existing rows
    (`FOR UPDATE`/`FOR SHARE`/`UPDATE`/`DELETE`) and advisory locks. INSERTs of fresh rows with new keys never wait on
    another transaction's row lock and may appear anywhere; `SKIP LOCKED` and `NOWAIT` never wait. Order:
    idempotency advisory lock (erratum 37) → asset-guard advisory lock → `jobs` (claim: SKIP LOCKED only) →
    `run_lease` → `runs` → `messages` → `drafts` → `proposals` → `decisions` → `memberships` → `execution_grant` →
    `action_attempt` → `action_attempt_state` → `operator_resolutions` → `invocation_context` → `run_state_history` →
    `events` → `outbox` → `jobs` (finish/requeue of the transaction's own claimed job) → `idempotency_request`
    (written last). `model_permit`, `sessions`, `login_state`, `logout_jti`, `test_clock`, `tenants`,
    `run_directory` are never row-locked together with the run tables (own units). A unit test asserts every app
    table appears in `LOCK_ORDER` or in the documented "own unit / insert-only" set, so a new table must be placed.
    Erratum 52: SA:188 extended. The plan's Task that adds the order checks each existing transaction (FS §3.15)
    against it and fixes or records departures.

15. **Asset-guard lock (FS Q15).** T13 places it in the order and adds a live capability test: a definer owned by
    `app_definer` (created and dropped by the test as superuser inside a rolled-back transaction) can call
    `pg_advisory_xact_lock(hashtextextended(…, 0))`. Taking it in `freeze_proposal`/`grant_execution` stays T21's.

16. **Heartbeat thread (FS Q16).** One `threading.Thread` per worker process (daemon), own **synchronous**
    `psycopg.Connection` as role `worker`, autocommit, `-c timezone=UTC` conninfo, `lock_timeout` 5 s. Idle while no
    lease is held. Renewal unit: `SELECT owner, fence, lease_until > app.current_time() AS live FROM app.run_lease
    WHERE run_id = %s FOR UPDATE`, compare in Python, then `UPDATE … SET lease_until = app.current_time() + lease`.
    A broken heartbeat connection is reopened lazily on the next tick. psycopg sync API is already in the lock; no new
    dependency.

17. **Liveness gate and compute cap (FS Q17).** The loop runs a tiny asyncio ticker that stamps a monotonic
    `loop_tick` every 1 s; the thread renews only while `now − loop_tick < OPS_LOOP_STALL_SECONDS` (default 28; must
    exceed 25, DoD 3) **and** the lease has been held less than `OPS_COMPUTE_BUDGET_SECONDS` (default 90, BS:555).
    When either gate closes the thread stops renewing and signals loss (ruling 19). Accounting into
    `runs.budget_used` across jobs, human-wait exclusion bookkeeping and R062's caps stay T29's (debt line).

18. **Local monotonic deadline (FS Q18).** `deadline = monotonic instant taken before the acquisition/renewal
    statement + lease − 5 s`. `Lease.check()` raises `LeaseLost` past it; the worker calls it before every MCP call,
    model call and fenced unit ("starting effects", SA:195). Moving `app.test_clock` expires every lease in the
    database at once (global offset); tests that move it do so only with no lease held, or deliberately.

19. **Renewal failure (FS Q19).** Loss = a renewal that sees another owner/fence or an expired lease, a gate
    closing (ruling 17), or transient renewal errors persisting past the local deadline. The thread then sets
    `lease.lost` and calls `loop.call_soon_threadsafe(task.cancel)` on the handler task. The worker loop catches the
    cancellation for that job, revokes the job's handles with `revoke_handles(run_id, fence)` (works without a live
    lease, ruling 8), un-claims the job (`claimed_*` → NULL, `available_at` = now; jobs are wake-ups) in one unit, and
    moves on; **no run transition** (the next owner re-reads state). Cancelling the handler cancels in-flight MCP
    (httpx2 inside the task) and model calls; the model permit is released in a `finally`.

20. **Testing DoD 3 (FS Q20).** Lease, heartbeat, stall and budget are validated settings (`OPS_LEASE_SECONDS` 30,
    `OPS_HEARTBEAT_SECONDS` 10, `OPS_LOOP_STALL_SECONDS` 28, `OPS_COMPUTE_BUDGET_SECONDS` 90; checks: heartbeat × 2 <
    lease, 5 < lease, stall < lease + heartbeat… the plan states the exact checks). Unit tests use scaled values with
    a fake clock/renewer. The live DoD-3 tests use the **real defaults**: a handler that blocks the loop with
    `time.sleep(25)` keeps its lease (fence unchanged, lease live after, no loss); a slow fake drafter (> 30 s,
    `FakeDraftGenerator` gains an optional test delay) is kept alive by the heartbeat; a forced renewal failure — a
    second `worker` connection takes the lease after the test expires it (superuser `UPDATE … lease_until`) — cancels
    an in-flight call (a fake MCP caller awaiting forever) and revokes the handles. These are slow (~30–40 s each):
    mark them so `check.py --profile test` still runs them (they are the DoD), and say so in the gate record.

21. **Testing DoD 1–2 (FS Q21).** Interleaving: two `worker` connections stepped explicitly — A acquires (f), the
    test expires A's lease, B acquires (f+1), A's fenced unit raises `LeaseLost` and changes nothing; the in-flight
    variant: A holds the share lock in an open transaction, B's acquisition waits (proved with `pg_blocking_pids`),
    A commits, B gets f+1, A's next unit fails. Stress: N = 8 connections × ~20 s over 3 runs mixing acquire, renew,
    fenced writes (append_event, mint/revoke handles), `mark_unknown`-style bumps and the sweeper's reclaim; assert
    zero SQLSTATE 40P01, zero 55P03 under a 10 s `lock_timeout`, fences strictly increase per run, and never two
    owners with live leases at the same observation. Runs in `--profile test`. `PURGE_ORDER` gains `run_lease` (and
    `model_permit` reset).

22. **Fault factory (FS Q22).** `Faults` keeps its shape (the class that refuses outside TEST is the "factory",
    SA:564) and gains an optional per-kind parameter (`seconds` / `count`) and a documented mapping of BS:405's nine
    phrases to kinds. incident-sim gains: `timeout_before_accept` (hold the POST `seconds`, then 503, nothing
    written), `rate_limit` (429 + `Retry-After`, nothing written), `malformed_response` (commits, answers a body that
    is not the receipt shape), `receipt_hash_mismatch` (commits, answers a receipt whose `payload_sha256` differs),
    `delay_receipt` (commits; the next `count` lookups `GET /internal/actions/{id}` answer NOT_FOUND). Existing:
    `reject_next` = definitive no-commit, `drop_before_commit` = transient unavailable, `lose_after_commit` = response
    loss after commit. Concurrent same-key submission stays a harness behaviour (`asyncio.gather`, R047), recorded in
    the mapping. API: `lose_after_commit` (the unit commits, idempotency record included, then the response is replaced by
   a 503; a replay with the same key returns the recorded 202, which is R015's after-commit proof) and `faults` passed into
    the store by the factory instead of set from the lifespan (Plan G open item). No worker/sweeper fault hook (the
    renewal failure is real, ruling 20). mcp-write's handling of the new faults is T22/T47's.

23. **Checkpoints (FS Q23).** Untouched (T20; R021 is M15).

24. **Bounded retries (FS Q24).** Move to T22 (debt line + TODO rewording): the execute job's transport and
    `GRANT_DEFERRED` re-queues act on APPROVED/EXECUTING runs that the worker may not move (SA:451), so the bound
    needs reconciliation/escalation. T13 only makes each re-queue release the lease (ruling 28).

25. **Pools / reconnect (FS Q25).** No pool, no new dependency. Only the heartbeat connection reconnects (ruling 16).
    Process restarts on a lost loop connection stay as today (supervisor; T30). The API `lock_timeout` TODO → T30.

26. **One compute lease per requester (FS Q26).** Out of scope → T29 (one worker replica runs one job at a time).

27. **`api` may insert any job type (FS Q27).** Revision 0007 adds `CHECK (type IN (…eight types…))` on `jobs`; the
    api-only-`resume_input` restriction stays a T22 debt line.

28. **Release (FS Q28).** The job's final unit (`FOR UPDATE` on the lease, owner and fence must match): finish (or
    re-queue) the job, revoke handles (fence ≤ current), set `lease_until = '-infinity'`; owner kept; the fence
    persists for the run's next job. Human waits hold no lease (R022 is T20's).

29. **Worker-side `runs` locks (FS Q29).** They stay, after the fence's share lock (run_lease before runs).

30. **Side debts (FS Q30).** Take only: freezing the `testclock` revision's grantee tuples (in 0007's task). Leave the
    rest with their owners (T30/T22/T47), reworded where they say T13.

31. **Migration (FS Q31).** One revision `0007_leases_fences` on the main line: `model_permit` (+ seed, grants),
    `app_definer upd(fence)` on `run_lease`, the `jobs.type` CHECK, the new/replaced function bodies
    (`_resolve_handle`, `resolve_invocation`, `grant_execution`, `lookup_action`, `mark_sent`, `record_outcome`,
    `mark_unknown`, `revoke_handles`, `queued_runs_total`), frozen grant cells and caller lists; downgrade restores
    0006 exactly (R006 live). Owner input: migrate the dev DB to 0007 (it is at 0005; 0006 is also pending).

## Task shape (the plan writer may refine, but keep ≤ 8 tasks)

1. Debt before code + settings (lease/heartbeat/stall/budget/global queue), `core/locking.py` (order + rule + table
   classification test), Faults parameter + mapping (unit only).
2. Revision 0007 + privilege matrix + PURGE_ORDER + live R124/R006 + the advisory capability test.
3. Fenced definers + mcp-write/mcp-read callers (rulings 5–9) + `mint_handle` fence/expiry + live tests (handle
   refused after fence move/expiry; post-SENT UNKNOWN; revoke scope; mark_unknown returns the new fence).
4. `core` lease module (async acquire-in-claim, fenced unit, release, refence) + interleaving tests (DoD 1, R107 part)
   + R087 (resume vs original job: a synthetic second job of the same run contends for the lease).
5. Heartbeat thread + `Lease` shared state + local deadline + gates + cancellation; unit tests scaled; live DoD-3
   tests (R088).
6. Worker integration (loop, handlers fenced, release, lease loss handling, model permit around drafting) + sweeper
   reclaim + stress test (DoD 2, R107) + global queue bound in the API.
7. Fault factory completion: incident-sim six kinds, API `lose_after_commit`, faults into the store; live tests
   (R098, R019/R020 evidence per their matrix rows — the plan reads R019/R020's exact evidence and maps each).
8. Close-out: handoff records, acceptance rows, errata 45+, runbook (lease/heartbeat/lock order), STATUS,
   SESSION_STATE, BUILD_BACKLOG, ARCHITECTURE, history section, final gates.

## Standing constraints (carry Plan G's Global Constraints forward)

- No Claude attribution in commits or docs (owner instruction). Comments follow `docs/CODE_COMMENTS.md`; every review
  round's problems/fixes are appended to `docs/PROJECT_HISTORY.md` at close.
- Debt list committed before code (SA:698), each line with its owning task.
- Clock: every lease/permit/expiry comparison in SQL on `app.current_time()` after the lock; Python never compares
  database instants (only monotonic local deadlines).
- One string per SQL function, ISC004 binds rule (`tests/plan_e/test_transitions_table.py` scans every revision).
- Live tests only against `ops_test`/`incident_test` under `PROFILE=test`; never the dev databases.
- Unit tests in `tests/plan_h/` (add to `testpaths`), live tests in `tests/e2e/`.
- Gates at start: `check.py` 816 passed / 104 skipped; `check.py --profile test` 899 / 21; `verify_handoff` exit 0.
- No secret in any env var, log, assert operand, evidence file or doc.

---

# Round 1

## Static review

## Plan H round 1: static adversarial critic

Plan: `docs/superpowers/plans/2026-10-15-first-slice-h-leases-fences-heartbeat.md` (9164 lines, branch `plan-h`,
03e2636).

**Verdict: REVISE.** 1 Blocking, 5 Important, 8 Minor.

Every splice applies and every per-task dev-gate count matches. The lock order holds and I found no deadlock. The one
Blocking finding is the controller's specific concern: if the heartbeat cancels the handler task while psycopg is
inside `transaction().__aenter__` (the BEGIN round trip), the loop connection is left silently INTRANS for good. Three
Important findings would turn the gates red as written.

### How this was checked

**Reading.** I read the whole plan, the brief (31 rulings), the T13 task with its review notes, and the six
acceptance rows. I also read every existing function body that 0007 replaces or depends on (0002 `current_time`, 0003
`revoke_handles` and `_tenant_of_run`, 0004 `_resolve_handle`/`mark_sent`/`record_outcome`/`mark_unknown`, the 0005
`grant_execution` lock position), `privileges.py`, `persistence.py`, the worker's `mcp.py`, mcp-write's
`execution.py`, and psycopg 3.3.6's installed `connection_async.py`, `transaction.py` and `waiting.py`.

**Applying the plan.** I wrote a parser (`critic1/apply.py`, `critic1/inline.py`) that applies every step of Tasks 1-7
in order to `git archive HEAD` copies: Create, whole-file replacements, every `replace … with …` pair, the twelve
inline replace-all edits, the three "insert after/before" edits and the appends.
- Every quoted old text matched exactly once.
- Every replace-all count equalled the count the plan states.

**Gates on each copy** (repo's locked venv, member src first on `PYTHONPATH`, `ruff format` applied as the plan
instructs):

| After task | ruff check | mypy strict (8 member trees) | pytest (dev) |
|---|---|---|---|
| 1 | RUF007 (locking.py) | clean, 49 files | 844 + 12 env = **856** passed, 104 skipped |
| 2 | RUF007 | clean | **862** / 109 |
| 3 | RUF007 | clean, 50 files | **875** / 119 |
| 4 | RUF007 | clean | **882** / 124 |
| 5 | RUF007, ASYNC251 | **1 error** (permit.py:28) | **897** / 128 |
| 6 | same | same | **902** / 132 |
| 7 | same | same | 906 + 12 env = **918** / 133 |

The 12 "env" failures are `tests/plan_a/test_verify_handoff.py` (11) and `tests/plan_b/test_text_hygiene.py` (1). They
fail identically on an untouched archive copy, because there is no `.git` and no reference zip. Every per-task count
equals the plan's. `tests/plan_e/test_transitions_table.py` (ISC004/bind scan, with 0007 in `REVISIONS`) passes.

**Not run.** No live test was run and no database was touched. DB behaviour is judged statically against PG 17
semantics and the cited bodies.

---

### Blocking

**B1 — A heartbeat cancellation that lands in a unit's BEGIN wedges the loop connection INTRANS for good.**

Where: Task 5 Step 2, `main.run_job` (plan 6528-6555). Task 5's `Heartbeat._lose` (6247-6254) calls
`loop.call_soon_threadsafe(work.cancel)` on the whole handler task. Ruling 19 itself is the cause.

Evidence (psycopg 3.3.6 as installed):
- `connection_async.py:384-402`: `transaction()` is `async with tx: yield tx`. An exception raised in
  `tx.__aenter__` never reaches `tx.__aexit__`.
- `transaction.py:99-104` and `209-226`: `_enter_gen` calls `_push_savepoint()` first. That increments
  `conn._num_transactions` before BEGIN is sent.
- `_connection_base.py:474-478`: `_exec_command` sends BEGIN (`send_query`) before its first yield. So at every await
  point inside `__aenter__` the status is ACTIVE.
- `connection_async.py:516-550` (`wait`): on `CancelledError` with status ACTIVE it sends a server cancel, then drives
  the same generator to completion (BEGIN finishes), then re-raises.

Result:
- The connection is INTRANS, `_num_transactions == 1`, and nobody ever commits or rolls back.
- The next `conn.transaction()` sees INTRANS and becomes `SAVEPOINT _pg3_2`. Its "commit" is only `RELEASE`
  (`transaction.py` `_get_commit_commands`).
- So `handlers.abandon`, and every later claim, lease, finish and release on that worker, runs inside one transaction
  that never commits. It holds `jobs` and `run_lease` row locks for good.
- Nothing notices. `/health/ready` uses the separate probe connection, and no statement errors.

Knock-on effects:
- Other workers meet the held lease row: `Busy(locked=True)`, deferred one second, over and over.
- The sweeper's `leases.reclaim` (Task 6, 7141-7148, no `lock_timeout`) blocks on the held job row. That stalls the
  sweeper tick. Membership sync then stops, and after 120 s `grant_execution` refuses for every tenant.

Variants:
- A cancellation landing in the COMMIT of a unit's `__aexit__` is consistent: the pop happens before COMMIT
  (`transaction.py:133-134`). But that unit then reports "cancelled" although it committed.
- That matters most for the permit take in `_wait_for_permit` (6313-6322): see I2.

Why it matters:
- The window is the BEGIN round trip of every unit the task opens. That is about eight units per job, plus one per
  permit poll while waiting for the global permit.
- A lease loss while waiting for the permit (budget gate, takeover) is a realistic way to hit it.
- No test can catch it. `test_r088_a_forced_renewal_failure…` (6795) and `test_a_heartbeat_cancel_hands_the_job_back`
  (5931) both cancel while the task waits on a fake MCP `Event`.

Fix (smallest safe design): never cancel a DB unit; cancel only effect awaits.
1. Give `Lease` an effect scope, for example `async with lease.effect():` or `await lease.run_effect(coro)`. It runs
   the awaitable as its own child task, registers that task on the Lease under its lock, and maps that child's
   `CancelledError` (or a `BaseExceptionGroup` whose leaf is one) to `LeaseLost`.
2. Wrap only `deps.mcp.call(...)` (investigate, execute), `deps.generator.generate(...)` and the permit back-off
   `sleep`.
3. The heartbeat's `cancel` callback cancels the registered effect task, if any. With no effect in flight it does
   nothing: the next `fenced()`/`check()` raises `LeaseLost` within one short unit, because `lost` is already set.
4. `run_job` then needs no `except BaseException` and no `cancelling()` test. It catches `LeaseLost`.
5. As a belt, `run_job` asserts `deps.conn.info.transaction_status is IDLE` before `abandon`. Otherwise it closes the
   connection and raises, so the supervisor restarts the worker instead of wedging.

Tests to add:
- A unit test with a fake connection whose `transaction()` records BEGIN/COMMIT. Cancel at every await point of a full
  `handle()` run. Assert that every BEGIN is matched and that cancellation reaches only effect awaits.
- Flag the change against ruling 19 in "Rulings needing controller attention".

---

### Important

**I1 — The dev gate is RED from Task 1 on as written (two ruff rules, one mypy error).**

Where and evidence (measured on the scratch copies above; `ruff check --fix` does not cure any of them, because RUF007's
fix is unsafe-only):
- Task 1 Step 6, `locking.follows_order` (plan 915): `zip(ranks, ranks[1:], strict=False)` fails **RUF007** ("Prefer
  `itertools.pairwise()`").
- Task 5 Step 3, `tests/e2e/test_heartbeat_live.py` `BlockingGenerator.generate` (6681): `time.sleep(BLOCK_SECONDS)`
  inside an `async def` fails **ASYNC251**.
- Task 5 Step 2, `permit.backoff` (6299): `FIRST_BACKOFF_SECONDS * 2 ** min(attempt, 3)` fails mypy strict
  **no-any-return**: `worker\src\ops_worker\permit.py:28: error: Returning Any from function declared to return
  "float"`. typeshed types `int ** int` as Any.

Why it matters: every task's "Expected: CHECK: GREEN" fails, and the executor must improvise.

Fix:
- Use `itertools.pairwise(ranks)`.
- Use `time.sleep(BLOCK_SECONDS)  # noqa: ASYNC251  (DoD 3 blocks the loop on purpose)`. The ban is on `noqa: BLE001`
  only.
- Use `2.0 ** min(attempt, 3)`.

**I2 — The model permit leaks for its full 65 s TTL when a cancellation lands on the take's COMMIT.**

Where: Task 5 Step 2, `permit._wait_for_permit` / `model_permit` (6313-6340).

Evidence:
- The take runs in `async with conn.transaction():`.
- A cancellation during its COMMIT commits the row (holder = me, `leased_until` = now + 65 s) and then raises
  `CancelledError` out of `__aexit__` (psycopg `wait`, as in B1).
- `slot` is never returned, so the `try/finally` release in `model_permit` is never entered.

Why it matters:
- BS:549 sets global model concurrency to 1, so every drafting worker in the system is blocked for 65 s.
- `test_the_permit_is_released_after_the_block_and_after_a_cancellation` (5826) cancels only inside the block.

Fix:
- B1's design (no cancellation inside DB units) removes the trigger.
- Independently, make the abandon unit (or `model_permit`'s outer `except BaseException`) release
  `WHERE holder = %s AND run_id = %s`, so a permit taken by this job never outlives it.
- Add a unit test that raises `CancelledError` from the take's commit.

**I3 — The stress test's "zero 55P03" cannot see a lock wait in the waiting acquisition.**

Where: Task 3 Step 3, `acquire_lease` (plan 2533-2536); Task 6 Step 3 `Actor.step` "acquire" op (7548-7556) and the
assertion (7649).

Evidence:
- `acquire_lease` maps every `psycopg.errors.LockNotAvailable` to `Busy(locked=True)` whatever `wait` is.
- With `wait=True` under the test's `lock_timeout = '10s'`, a 10 s wait therefore returns `Busy`. The stress treats
  that as a normal miss and never counts it as 55P03.
- The same goes for the first-acquisition INSERT wait inside a claim.
- The module docstring calls the waiting acquisition "the form that would deadlock if the order were wrong". Its long
  waits are exactly what the assertion cannot see. Deadlocks (40P01) still surface.

Why it matters: DoD 2 / R107 evidence ("no 55P03 under a 10 s lock_timeout") is vacuous for the main waiting path.

Fix:
- In `acquire_lease`, map 55P03 to `Busy(locked=True)` only when `not wait` (and only for the NOWAIT lock statement,
  not the INSERT).
- In the stress, count a `Busy(locked=True)` returned from `wait=True` as a failure.

**I4 — The stress mix never commits a fence bump, and ruling 21's "never two live owners" check is dropped without a
flag.**

Where: Task 6 Step 3 (7455-7470, 7584-7586, 7649-7661); brief ruling 21.

Evidence:
- All three stress runs are QUEUED. Every `mark_unknown` therefore bumps, revokes and then raises OC003, and the whole
  transaction rolls back (0007 MARK_UNKNOWN, plan 4613-4626).
- So no committed re-fence ever races a renewal, a fenced write or a revoke under load. That is precisely the T13
  review-note-2 path (`begin_refence`/`end_refence`, `fence_moved_by_owner`).
- Ruling 21 also asks to "assert … never two owners with live leases at the same observation". The plan's monitor
  records only fences. The check is not implemented, and it is not listed under "Rulings needing controller
  attention".

Fix:
- Make one of the three runs EXECUTING with a grant, as `approved_run` + `grant_execution` already do in
  `test_fenced_definers_live.py`, so `mark_unknown` commits and the actor hands the new fence to its `Lease`.
- Have the monitor read `owner, fence, lease_until > app.current_time()` and compare it with the actors' held `Lease`
  objects. Assert at most one actor whose fenced write could succeed.
- Or state the drop as refinement (j).

**I5 — `check_leases` admits combinations that lose healthy leases, and the unit test pins one of them as valid.**

Where: Task 1 Step 4 (plan 708-723) and `test_each_lease_variable_is_read_and_bounded` (568-572: lease 10, heartbeat 4,
stall 5, budget 10).

Evidence:
- The local deadline is `renewed_at + lease − 5` (`DEADLINE_MARGIN_SECONDS`, plan 2209/2306), and the thread ticks
  every 1 s.
- With lease 10 / heartbeat 4 the deadline is 5 s after each renewal start, and the next renewal starts at ≥ 4 s (up to
  ~5 s with the tick).
- So any renewal that takes longer than a few hundred ms, or a single failed renewal, lets `Lease.check()` pass the
  deadline first, and a healthy job is abandoned.
- The docstring's promise "Two renewals must fit in one lease, so one failed renewal never loses it" does not hold
  under the 5 s margin.

Fix: check `2 × heartbeat + DEADLINE_MARGIN_SECONDS + TICK < lease` (defaults: 20 + 5 + 1 < 30 holds), and move the
test's low companion values accordingly (e.g. lease 16, heartbeat 5, stall 6). Ruling 20 asked for "the exact
checks", so state this one.

---

### Minor

**M1 — The published rule "fresh INSERTs never wait" is false for FK inserts, and `OBSERVED_UNITS` is a hand-written
list, so its test is documentation, not detection.**

Where: Task 1 `locking.py` docstring (plan 816-828), `OBSERVED_UNITS` (864-885).

Evidence:
- An INSERT into `run_lease` (FK to `runs`, 0002:318) or `invocation_context` (FK to `runs` and `jobs`, 0001:123-124)
  takes FOR KEY SHARE on the parent row. That waits for any FOR UPDATE holder: every `runs … FOR UPDATE` definer, and
  `pick_job`'s jobs FOR UPDATE.
- I enumerated the cases and found no cycle:
  - A claim's first lease INSERT waits only on runs-lockers (API decision/reply, mark_unknown) that never touch the
    claim's picked job.
  - A mint's KEY SHARE on its job conflicts only with a post-reclaim `pick_job`, which defers via NOWAIT.
- Still, a future unit relying on the rule could build a cycle.

Fix:
- State that FK checks take FOR KEY SHARE on `runs`/`jobs`, which conflicts with FOR UPDATE, and rank them at the
  parent's position.
- Name `test_every_documented_unit_follows_the_order` honestly ("the documented units are consistent").

**M2 — In practice a handle lives 20–30 s, not 60 s, because renewals never extend it.**

Where: Task 3 `mint_handle` (2711-2721).

Evidence:
- `expires_at = least(now + ttl, lease_until at mint)`, and a heartbeat renewal does not move a minted handle.
- The worker's MCP read timeout is 60 s (`worker/src/ops_worker/mcp.py:56`).
- A slow tool call ends in OC008 (pre-SENT `INVALID_HANDLE`, which `handlers.execute` then treats as a finished job),
  not a timeout.

Fix: record this in the runbook and the debt list (T22/T47), or mint per call with the renewed cap.

**M3 — The R006 downgrade proof compares `prosrc` only, and the import-time guard can break every Alembic command.**

Where: Task 4 Step 4 (5263-5269); Task 4 Step 2 `_applied`/`GRANT_EXECUTION` guard (4361-4458).

Evidence:
- The live round trip compares head with re-upgraded head, plus `prosrc` against the applied revisions' text.
- It never compares the downgraded state's proacl/owner/proconfig with a database actually built to 0006.
- The `RuntimeError` at module import in 0007 aborts loading the revision graph for every Alembic command if 0005 ever
  drifts.

Fix:
- Compare `pg_get_functiondef` and `proacl` after `downgrade(0006)` with a snapshot taken on a fresh `upgrade(0006)`.
- Raise from `upgrade()` instead of at import.

**M4 — The DoD-3 timing margin is about 2 s.**

Where: Task 5 Step 3 (6661, 6759).

Evidence: the last stamp before `time.sleep(25)` can be up to 1 s old (`STAMP_SECONDS`), so the stall age peaks at
about 26.x s against the 28 s gate. That is acceptable, but it is tight on a loaded Windows host.

Fix: record the maximum `Liveness.age` the thread observed in the evidence line, so a near miss is visible.

**M5 — `test_two_first_acquisitions_of_one_run_give_one_lease` does not prove that the INSERT-conflict wait happened.**

Where: Task 3 Step 7 (3709-3728).

Evidence: with `asyncio.gather` on one loop, A's whole claim can commit before B's first statement. The test then
passes through the "row exists → Busy" path, and the wait path Review Focus 1 names is never exercised.

Fix: step it the way the in-flight test is stepped. Run A's `claim_next` inside an open transaction, start B, use
`wait_until_blocked`, then commit A.

**M6 — The heartbeat's connect has no timeout.**

Where: Task 5 Step 2, `heartbeat.connector` (6142-6145).

Evidence: `psycopg.connect(pg.conninfo(), …)` has no `connect_timeout`. A hung connect (host reachable, server not
answering) blocks the thread's tick past the local deadline. Loss is then declared only by the loop's own `check()`,
and an in-flight effect is not cancelled meanwhile.

Fix: pass `connect_timeout=5`.

**M7 — The R088 cancellation is proved only against a fake MCP.**

Where: Task 5 Step 3 (6685-6703).

Evidence:
- `HttpMcpCaller` runs inside anyio task groups and can surface cancellation as a `BaseExceptionGroup`
  (`worker/src/ops_worker/mcp.py:69-73`).
- `run_job` copes with that through `lease.lost`, but ruling 19's "cancels in-flight MCP (httpx2)" is not shown.

Fix: add one unit test that cancels a real `HttpMcpCaller` against a local server that never answers.

**M8 — `queued_runs_total` costs one scan per tenant on every run admission.**

Where: Task 2 `QUEUED_RUNS_TOTAL` (1177-1197).

Evidence: the cost is O(tenants) inside the admission unit. It returns one aggregate (a cross-tenant load signal, as
ruled); there is no further leak.

Fix: note the cost in the runbook next to the "soft bound" note (T29).

---

### Checked and found sound

**Lock order.** Every transaction the plan writes or keeps, enumerated:
- claim: jobs SKIP LOCKED → run_lease NOWAIT (+ fresh INSERT)
- fenced worker units: run_lease S → runs X → fresh inserts
- `mark_unknown`: run_lease X → runs X → invocation_context → inserts
- release: run_lease X → invocation_context → jobs
- abandon: run_lease S → invocation_context → jobs
- renewal: run_lease X only
- `_resolve_handle` callers: run_lease S → runs X (`grant_execution`, `mark_sent`, `record_outcome`)
- API units: advisory → runs → record
- reclaim: jobs only
- permit: own unit

None steps back. There is no FOR SHARE → FOR UPDATE upgrade (T13 note 1 holds).

**Heartbeat vs loop in one process.** The thread holds only run_lease and the loop never waits on the thread, so there
is no cycle. Share requesters may starve a queued FOR UPDATE, but the 5 s `lock_timeout` plus a per-tick retry bounds
it.

**Clock comparisons.** Every lease and handle comparison is on `app.current_time()` after the lock. That function is
VOLATILE `clock_timestamp()` (0002:366-382), so "after the lock" really is later. Specifically:
- the CTE statements (2212-2216)
- `_resolve_handle` (4421-4425)
- `mark_unknown` (4607-4609)
- `renew` (6031-6039)

`release_lease` deliberately skips liveness (ruling 28). Refinement (c) is correct: a WHERE on a FOR SHARE that waited
on a rolled-back locker is not rechecked.

**INSERT-before-lock (refinement a).** The refinement is correct. ON CONFLICT DO NOTHING's dirty-snapshot check waits
on an in-progress UPDATE of the conflicting row.

**Post-SENT fence failure.** `HandleRejected` is a `PersistenceError`, so it is in `_POST_SENT_REFUSALS`
(`execution.py:32`). Both sides of SENT are tested, unit and live.

**Revoke scope.** Revocation is `fence <= p_fence` with a share lock, and never refuses.

**Fault routes.** They exist only under PROFILE=test, and the factory refuses any other profile.

**Secrets.** No raw handle reaches a log or an assert: only `handle_hash` is used.


## Builder dry run

# Plan H dry run, round 1 (builder report)

Plan: `docs/superpowers/plans/2026-10-15-first-slice-h-leases-fences-heartbeat.md` at `plan-h` 03e2636.
Worktree: `<scratch>/planh/dryrun1`, detached at 03e2636, `uv sync --locked`. It was removed at the end
(`git worktree remove --force` and `git worktree prune`). Date: 2026-10-15.

To type the code, a script copied each fenced block from the plan byte for byte. The splice helper refused any edit
whose old text was not found exactly once. Inline replace-all edits were counted before they were applied.

## BLOCKER: no live step ran

The live suite needs the repository's `.env` inside the worktree. `tests/e2e/conftest.py` and
`tests/plan_b/live/conftest.py` read `ROOT/.env`. The Plan G dry runs copied `.env` into their worktree. Here the
permission classifier denied that copy ("Credential Leakage"). It also denied reading the code that writes `.env`.
I did not try any other way round it.

The `scripts/skeleton.py` docstring says the file "holds paths, ports and URLs only (never a secret)". The owner
should decide whether to allow copying `.env` into the dry-run worktree, for example with a permission rule.

What did not run because of this:
- every `OPS_LIVE=1` step;
- every `check.py --profile test` gate;
- the 0007 upgrade/downgrade/upgrade test;
- the interleaving and stress tests (so there are no 3x repeats);
- the slow_live timings;
- the live heartbeat tests on Windows.

The one live attempt was the baseline in Task 1 Step 1a. It ended `816 passed, 21 skipped, 83 errors` and
`CHECK: RED`. Every live test errored at setup with `FileNotFoundError: [Errno 2] No such file or directory: '.env'`.
The session fixtures read `.env` before they connect, so no database was touched. `skeleton.py status` showed all
six processes down before and after.

Everything else ran: every edit, every red and green unit run, ruff format and check, the character count, mypy
through `check.py`, every dev gate and every `verify_handoff`. Each live module was also collected without
`OPS_LIVE`, so its test count could be compared with the plan's live counts. Every count matched.

## Summary

- Steps: 47 in total.
  - OK: 28. An asterisk in the tables below means the dev half matched and the live half was blocked.
  - DIFFERS: 10.
  - WORKAROUND: 3 steps holding 4 workarounds.
  - BLOCKED: 6. These are steps whose only check is a live run; all their edits applied cleanly.
- Every splice's old text was found exactly once except one (WA-2). Every replace-all count matched the plan.
- Scratch commits (thrown away with the worktree):

  | Commit | Content |
  |---|---|
  | 12a8c6d | debt list |
  | 1363461 | T1 |
  | 2c876cf | T2 |
  | d35cc05 | T3 |
  | 2b5de3c | T4 |
  | 15801ef | T5 |
  | 8acdf62 | T6 |
  | 44981e0 | T7 |
  | 59a0210 | T8 |

  Task 8's script printed `03e2636..44981e0`.

### Gates: observed vs expected

| When | Dev `check.py` observed (pytest time) | Dev expected | Live `--profile test` | `verify_handoff` |
|---|---|---|---|---|
| T1 S1a baseline | 816 passed, 104 skipped, GREEN (46.71 s; 65 s wall) | 816/104 | BLOCKED (816/21 + 83 setup errors, RED) | — |
| T1 S7 | 856/104 GREEN (35.57 s) | 856/104 | not required | exit 0 |
| T2 S7 | 862/109 GREEN (35.93 s) | 862/109 | BLOCKED (exp 950/21) | exit 0 |
| T3 S8 | 875/119 GREEN (36.39 s) | 875/119 | BLOCKED (exp 973/21) | exit 0 |
| T4 S6 | 882/124 GREEN (38.00 s) | 882/124 | BLOCKED (exp 985/21) | exit 0 |
| T5 S4 | first run RED (mypy, WA-4); after WA-4 897/128 GREEN (37.37 s) | 897/128 | BLOCKED (exp 1004/21) | exit 0 |
| T6 S4 | 902/132 GREEN (36.65 s) | 902/132 | BLOCKED (exp 1013/21) | exit 0 |
| T7 S3 | 918/133 GREEN (38.05 s) | 918/133 | BLOCKED (exp 1030/21) | exit 0 |
| T8 S5 | 918/133 GREEN (38.33 s) | 918/133 | BLOCKED (exp 1030/21) | exit 0 |

- mypy: `Success: no issues found in 49/50/50/52/53/53/53 source files` from Task 2 on. The one exception is the
  first Task 5 run (WA-4).
- Wall time per dev gate: 39-42 s.

Live modules collected without `OPS_LIVE`. The skip counts equal the plan's expected live pass counts:

| Step | Modules | Skipped | Plan's expected live result |
|---|---|---|---|
| T2 S6 | the four modules | 22 | `22 passed` |
| T3 S6+S7 | worker, persistence, mcp-read, mcp-write and leases | 28 | 18 + 10 |
| T4 S5 | the seven modules | 49 | `49 passed` |
| T5 S3 | the three modules | 18 | `18 passed` |
| T6 S3 | the three modules | 14 | `14 passed` |
| T7 S3 | the two modules | 13 | `13 passed` |

`pytest tests/e2e/test_heartbeat_live.py -m "not slow_live"` gave `1 skipped, 3 deselected`, so the marker is
registered.

Unit runs, all as the plan says:

| Step | Result |
|---|---|
| T1 S4 | 15 passed |
| T1 S6 | 30 passed |
| T2 S4 | 53 passed |
| T3 S4 | 38 passed |
| T4 S3 | 86 passed |
| T5 S2 | 88 passed |
| T6 S2 | 149 passed |
| T7 S2 | 413 passed |

Timings:
- Slow live tests: none measured (BLOCKED). The 25 s blocked-loop test against the 28 s stall gate is unmeasured.
- Heartbeat on Windows, unit level only: `test_heartbeat.py` includes `test_the_thread_cancels_the_loops_task_and_stops`
  (a real `threading.Thread` cancelling a task through `call_soon_threadsafe`, under `asyncio.run`'s default Proactor
  loop). Together with `test_permit.py` and `test_worker_units.py` it was run 5 times: 22 passed each time in
  1.42-1.46 s, no flake.

## Task 1

| Step | Status | Note |
|---|---|---|
| 1a | OK* | dev 816/104 GREEN; live BLOCKED (see top) |
| 1b | OK | BASE=03e2636 (ledger created under the ignored `.superpowers/`) |
| 1c | OK | debt section inserted before `## Environment (observed)` |
| 2 | OK | both `pyproject.toml` splices found once |
| 3 | OK | `1 error in`, ImportError LeaseSettings |
| 4 | OK | 15 passed |
| 5 | OK | `1 error in`, ImportError locking |
| 6 | OK | 30 passed |
| 7 | WORKAROUND | WA-1 |

Task 1 Step 7, observed:

```text
RUF007 Prefer `itertools.pairwise()` over `zip()` when iterating over successive pairs
   --> core\src\ops_core\locking.py:102:55
102 |     return all(earlier <= later for earlier, later in zip(ranks, ranks[1:], strict=False))
Found 1 error.
```

## Task 2

| Step | Status | Note |
|---|---|---|
| 1 | OK | `1 error in` (the module-level assert on REVISIONS) |
| 2 | DIFFERS | count right (`5 failed, 12 passed`); one reason differs (below); ISC004 changed nothing |
| 3 | OK | 5 splices once |
| 4 | OK | 53 passed |
| 5 | OK | both splices once |
| 6 | BLOCKED | file written; collects 22 |
| 7 | DIFFERS | `ruff format` rewrote 0007's `FUNCTIONS` (below), which causes WA-2; dev 862/109 GREEN; live BLOCKED |

Task 2 Step 2: `test_the_newest_revision_of_every_cell_equals_the_live_matrix` fails with:

```text
E   AssertionError: run_lease
E   {'app_definer': Grant(sel=True, ins=False, upd=('fence',), dele=False)} != {'app_definer': Grant(sel=True, ins=False, upd=False, dele=False)}
```

The plan says this test fails with `KeyError: 'model_permit'`.

Task 2 Step 7: the plan's three-line `FUNCTIONS: … = (\n    ("queued_runs_total", …),\n)` became one 119-character
line. It is a one-element tuple, so ruff does not treat its comma as a magic trailing comma.

## Task 3

| Step | Status | Note |
|---|---|---|
| 1 | OK | `3 errors in`, ModuleNotFoundError ops_core.lease ×3 |
| 2 | OK | |
| 3 | OK | 7 splices once |
| 4 | DIFFERS (cosmetic) | 38 passed; `ruff format` rewrote 2 plan files (below) |
| 5 | OK | |
| 6 | BLOCKED | edits OK (below); run BLOCKED |
| 7 | BLOCKED | file written; `ruff format` joined `tool_events`' implicit concatenation into one line |
| 8 | OK* | dev 875/119 GREEN; live BLOCKED |

Task 3 Step 4, the two reformatted files:
- `lease.py`: the parenthesised `RENEW` became one line.
- `persistence.py`: `release_lease`'s three-line signature became one 119-character line.

Task 3 Step 6 edits:
- Every splice was found once.
- The replace-all counts were 3/5/1/6 as stated.
- `grep -c "own_job(app_conn, run"` then printed `0`.
- Line cites are off by one: `test_migrations_and_persistence.py` "147-157" is 148-158, and r105 "24-25" is 25-26.

## Task 4

| Step | Status | Note |
|---|---|---|
| 1 | DIFFERS | count right (`11 failed, 6 passed`); one reason differs (below) |
| 2 | WORKAROUND | WA-2 (Edit 4 refused, below); Edits 1-3 OK; ISC004 changed nothing; privileges edit OK |
| 3 | OK | 86 passed |
| 4 | OK | all splices once; replace-all counts 3/1/2/3 matched; grep printed `0`; an AST check confirmed `handle` and `new_handle` are bound in every edited test |
| 5 | BLOCKED | file written; collects 49 |
| 6 | OK* | dev 882/124 GREEN; live BLOCKED; `ruff format` rewrote 3 files (below) |

Task 4 Step 1: the first new revision test fails with:

```text
E   ValueError: 'DROP FUNCTION app.mark_sent(uuid)' is not in list
```

The plan says `AttributeError … 'RESOLVE_HANDLE'`. `seen.index` runs before `module.RESOLVE_HANDLE` is read.

Task 4 Step 2, Edit 4:

```text
REFUSED migrations/app/versions/0007_leases_fences.py (old 4382-4393 new 4397-4696): old text found 0 times
```

Task 4 Step 6: one of the 3 reformatted files is `execution.py` Edit 3, whose three-line `record_outcome(...)` call
became one 119-character line. The others came from the lengthened replace-all lines.

## Task 5

| Step | Status | Note |
|---|---|---|
| 1 | DIFFERS | collection errors stop the session (below) |
| 2 | OK | all splices once; 88 passed; 5 repeat runs stable |
| 3 | BLOCKED | file written; `-m "not slow_live"` gave 3 deselected |
| 4 | WORKAROUND | WA-3 and WA-4 (below); then 897/128 GREEN; live BLOCKED |

Task 5 Step 1, observed:

```text
E   ImportError: cannot import name 'Renewal' from 'ops_core.lease'
E   ModuleNotFoundError: No module named 'ops_worker.permit'
!!!!!!!!!!!!!!!!!!! Interrupted: 2 errors during collection !!!!!!!!!!!!!!!!!!!
2 errors in 1.50s
```

- The plan expects `7 failed, 1 passed, 2 errors`. pytest stops at collection errors, so the worker tests never run.
- Run alone, `test_worker_units.py` gives `7 failed, 1 passed` with AttributeError `take_model_permit`, as stated.
- The heartbeat module's error is the `Renewal` ImportError, not `ModuleNotFoundError: ops_worker.heartbeat`.

Task 5 Step 4, observed:

```text
ASYNC251 Async functions should not call `time.sleep`
  --> tests\e2e\test_heartbeat_live.py:60:9
60 |         time.sleep(BLOCK_SECONDS)  # on purpose: DoD 3's blocked loop
```

```text
worker\src\ops_worker\permit.py:28: error: Returning Any from function declared to return "float"  [no-any-return]
Found 1 error in 1 file (checked 52 source files)
CHECK: RED
```

The mypy error also appears with `--no-incremental`, so it is real: `int ** int` is `Any` in typeshed. `ruff format`
also rewrote the Edit 2 assertion in `test_worker_units.py` (cosmetic).

## Task 6

| Step | Status | Note |
|---|---|---|
| 1 | DIFFERS | expected `3 failed, 1 error`; got `1 error in 1.38s` (ImportError `leases` interrupts collection); `test_global_queue.py` alone gives 3 failed with the stated TypeError |
| 2 | OK | 16 splices once, plus the insert after `queued_count`; 149 passed |
| 3 | BLOCKED | files written; admission edits OK, helper names exist; collects 14; `ruff format` collapsed `Actor.__init__`'s signature |
| 4 | OK* | 902/132 GREEN; live BLOCKED |

## Task 7

| Step | Status | Note |
|---|---|---|
| 1 | DIFFERS | expected `10 failed, 2 passed, 1 error`; got `1 error in 1.19s` (ImportError BS405); without that module, 10 failed and 2 passed as stated |
| 2 | OK | 19 splices once, plus the `API_FAULTS` insert and two appends; 413 passed |
| 3 | OK* | format left 9 files unchanged; count clean; live run BLOCKED (collects 13); 918/133 GREEN |

## Task 8

| Step | Status | Note |
|---|---|---|
| 1 | DIFFERS (no WA) | no `TODO(T13` in live code, but two expected outputs are wrong (below) |
| 2 | OK | printed the span; 3 handoff files; a JSON comparison shows exactly R015, R019, R020, R087, R088, R098 and R107 changed (one observation below) |
| 3 | OK | 5 edits, each anchor found once |
| 4 | DIFFERS | 3 issues (below) |
| 5 | OK* | 918/133 GREEN; vh 0; live BLOCKED |
| 6 | DIFFERS | consequence of BLOCKED (below) |

Task 8 Step 1, the two wrong expected outputs:
- `grep -c "TODO(T13" migrations/app/versions/0007_leases_fences.py` prints `2`, not `0`. Line 173 is the comment
  "its TODO(T13) answered". Line 175 is the `_GRANT_TODO_0005` literal.
- `git grep` also lists `tests/plan_h/test_migration_0007.py:130`, where `"TODO(T13)" not in module.GRANT_EXECUTION`
  is an assertion string.

Task 8 Step 2, observation: `BUILD_BACKLOG.md` puts the new note first under T13, while `tasks.json` appends it last.

Task 8 Step 4, the three issues:
- `PROJECT_HISTORY.md` at 03e2636 has no "The leases plan" section. The fallback asks the executor to write a planning
  story but gives no text. I wrote a placeholder and renumbered 25 to 26.
- `sweeper/README.md` line 4 ("later leases, wake-ups…") stays stale.
- Both sweeper replacements wrap across plan lines inside inline code, so it is ambiguous whether a newline is meant.

Task 8 Step 6: `git add … reports/leases …` failed with `fatal: pathspec 'reports/leases' did not match any files`
(there was no live run), and the whole add was aborted. I re-ran it without those paths.

## Workarounds

1. **WA-1 (T1 S7)**
   - Problem: ruff RUF007 at `locking.py:102`.
   - What I changed: `zip(ranks, ranks[1:], strict=False)` became `pairwise(ranks)`, with
     `from itertools import pairwise`.
   - Minimal plan fix: write `follows_order` that way in Task 1 Step 6's block.
2. **WA-2 (T4 S2, Edit 4)**
   - Problem: the old text (the three-line `FUNCTIONS` tuple) was not found, because Task 2's `ruff format` had
     collapsed the one-element tuple onto one line.
   - What I changed: I spliced against the one-line form.
   - Minimal plan fix: write `FUNCTIONS` in Task 2 in its formatted one-line form
     (`FUNCTIONS: tuple[...] = (("queued_runs_total", "", ("api",), QUEUED_RUNS_TOTAL),)`) and quote that form as
     Edit 4's old text.
3. **WA-3 (T5 S4)**
   - Problem: ruff ASYNC251 at `test_heartbeat_live.py:60`, the deliberate `time.sleep` in async
     `BlockingGenerator.generate`.
   - What I changed: added `# noqa: ASYNC251 - on purpose: DoD 3's blocked loop`.
   - Minimal plan fix, either of:
     - block through a module-level sync helper (`def block_the_loop(seconds: float) -> None: time.sleep(seconds)`),
       which needs no noqa;
     - or allow this one noqa in Global Constraints.
4. **WA-4 (T5 S4)**
   - Problem: mypy `no-any-return` at `permit.py:28` in `backoff`, which turned `check.py` RED.
   - What I changed: `2 ** min(attempt, 3)` became `2.0 ** min(attempt, 3)`.
   - Minimal plan fix: the same change in Task 5's `permit.py` block (or annotate `base: float`).

## Other plan fixes suggested (no workaround needed)

- **Expected red lines when a module fails to collect** (T5 S1, T6 S1, T7 S1). pytest aborts with
  `Interrupted: N errors during collection` and prints only `N error(s) in`. Either expect that line, or run the
  collection-failing module separately from the modules expected to fail. Also, T5 S1's heartbeat error is
  `ImportError: cannot import name 'Renewal' from 'ops_core.lease'`.
- **Failure reasons that differ** (counts unchanged).
  - T2 S2: `test_the_newest_revision…` fails with `AssertionError: run_lease`.
  - T4 S1: the first new revision test fails with `ValueError: 'DROP FUNCTION app.mark_sent(uuid)' is not in list`.
- **Code that `ruff format` rewrites** (cosmetic). Seven plan blocks are not format-stable:
  - 0007 `FUNCTIONS` (this one causes WA-2);
  - `lease.RENEW`;
  - the `persistence.release_lease` signature;
  - the `tool_events` SQL string in `test_leases_live.py`;
  - `execution.py` Edit 3;
  - the `test_worker_units.py` Task 5 Edit 2 assertion;
  - the stress test's `Actor.__init__`.

  Pre-formatting them avoids drift between the plan text and the tree for later splices.
- **Task 8 Step 1.** Expect `2` from the `grep -c` (or exclude the quoting lines), and name the test assertion string.
- **Task 8 Step 4.**
  - Give the PROJECT_HISTORY fallback section text, or commit that section before execution as Plan G did.
  - Update `sweeper/README.md` line 4.
  - State whether the README replacement text keeps its line break.
- **Task 8 Step 6.** `git add` of a path that does not exist aborts the whole add. Make it conditional, or say the
  live run must have written `reports/leases`.
- **Line cites.**
  - `test_migrations_and_persistence.py` Edit 2: 148-158, not 147-157.
  - r105 Edit 1: 25-26, not 24-25.
- **Task 8 Step 2.** Optionally append the BACKLOG review note last, as `tasks.json` does.

## Not verified (needs the live run)

Each item lists what the plan expects.

- Migration 0007:
  - the upgrade/downgrade/upgrade round trip;
  - the `prosrc` equality of the restored bodies.
- Every interleaving test:
  - `test_a_locked_lease_is_busy_at_once`, expected under 1 s;
  - the 2.5 s waits.
- `test_two_first_acquisitions_of_one_run_give_one_lease` and the stress test, which the brief asked to repeat 3×.
- The three slow_live DoD-3 tests:
  - the 25 s block against the 28 s stall gate (margin unmeasured);
  - the 35 s drafter;
  - the forced renewal failure.
- R019 with the test clock.
- The global-bound and R015 live tests.
- R105 with the leasing worker, the heartbeat and the sweeper's reclaim.
- The live gate's counts:

  | After task | Expected |
  |---|---|
  | 2 | 950/21 |
  | 3 | 973/21 |
  | 4 | 985/21 |
  | 5 | 1004/21 |
  | 6 | 1013/21 |
  | 7 | 1030/21 |

  The plan also expects the gate to take about 2.5 minutes longer.

## Clean-up

- `skeleton.py status`: all six processes down at the start and the end.
- No database was touched; the only live attempt failed at fixture setup.
- `git worktree remove --force` and `git worktree prune` both ran. `git worktree list` shows only
  `C:/Users/joeys/Desktop/MLOps 03e2636 [plan-h]`.
- `git -C C:\Users\joeys\Desktop\MLOps status --short` shows only
  ` M docs/superpowers/plans/2026-10-15-first-slice-h-leases-fences-heartbeat.md`. That change was there before this
  run (the session-start snapshot shows it) and is not mine. `plan-h` is still at 03e2636, with nothing committed on
  it.
- No secret file was opened, printed or copied.


## Controller rulings

# Plan H review, round 1 — controller rulings

Inputs: `round1-static.md` (REVISE: 1 Blocking, 5 Important, 8 Minor) and `round1-dryrun.md` (47 steps: 28 OK, 10
DIFFERS, 3 steps with 4 workarounds, 6 live steps BLOCKED because the tool permission classifier refused copying
`.env` into the scratch worktree; not circumvented — the live half is proven during execution in the main checkout).

## Static findings

- **B1 (cancellation can wedge the loop connection) — ACCEPTED; ruling 19 changes.** The heartbeat never cancels a
  database unit. Only *effect awaits* are cancellable: the MCP call, the model call and the model-permit back-off
  sleep. They run as child tasks registered on the `Lease` (e.g. `await lease.effect(coro)`, which creates the task,
  registers it under the lease's lock, awaits it, and unregisters in `finally`); on loss the thread sets `lost` and
  cancels only the registered tasks through `loop.call_soon_threadsafe`. A cancelled effect surfaces as `LeaseLost` in
  the handler. Database units are never interrupted; a loss during a unit is caught by the next `fenced()` /
  `lease.check()`. Before `abandon`, the worker asserts the loop connection is idle
  (`conn.info.transaction_status == IDLE`); if it is not, it closes the connection and the loop exits non-zero (the
  supervisor restarts it, as for a broken connection today). Tests: (1) the existing effect-cancellation test; (2) a
  unit test proving a loss signalled while a fake DB unit is in progress does not cancel the unit and the handler
  stops at the next check; (3) the non-idle-connection branch of `abandon`. Erratum 57 is reworded accordingly
  ("exits the run" = cancel effects, hand the job back; no unit is interrupted).
- **I1 (gates red: RUF007, ASYNC251, mypy no-any-return) — ACCEPTED.** `itertools.pairwise`; the blocking sleep moves to
  a module-level sync helper the async test calls (no noqa); `2.0 **` in `backoff`.
- **I2 (permit leak on cancelled take) — ACCEPTED, resolved by B1:** the take and the release are database units and
  are never cancelled; only the back-off sleep is an effect. The `finally` releases iff the take returned a slot. Add a
  unit test: loss during the back-off sleep leaves no permit held; loss after the take releases it.
- **I3 (stress cannot see long lock waits) — ACCEPTED.** `acquire_lease(wait=True)` propagates 55P03 instead of
  mapping it to `Busy`; the stress test counts 55P03 and 40P01 and requires both to be zero.
- **I4 (stress mix misses re-fence and the two-owner check) — ACCEPTED.** Seed at least one stressed run in EXECUTING
  (with a grant, through the superuser fixture path the live tests already use, or the real grant path if available)
  so `mark_unknown` bumps succeed under load; restore ruling 21's observation: at sampled instants no run has two
  owners with live leases and fences only increase.
- **I5 (`check_leases` too permissive) — ACCEPTED.** Require `2 × heartbeat + 5 + 1 < lease` (plus the existing
  checks); the unit test pins 30/10 valid and 10/4 invalid.
- **Minors (8) — ACCEPTED as the critic proposes**, each applied in place; where the critic offered alternatives, take
  the smaller one. Record any you decline with a reason in "Round 1 changes".

## Dry-run findings

- WA-1..WA-4: fold into the plan as the dry run did them (WA-3 per I1 above).
- Every code block must be stable under `ruff format` (the seven blocks named in the dry run; WA-2 came from one);
  quote formatted forms in later edits.
- Red-step "Expected" lines must state what pytest actually prints when a module fails to collect (the run is
  interrupted: `N errors in …`), and the T2 S2 / T4 S1 / T5 failure reasons as observed.
- Task 8: the TODO grep must exclude the deliberate strings (or the strings must not contain the token); give the full
  `PROJECT_HISTORY.md` section text for Plan H (no placeholder); fix `sweeper/README.md` line 4; make the README edits
  unambiguous about line breaks; `git add reports/leases` only if it exists (the live gate writes it — say which test);
  correct the off-by-one line cites; append the BUILD_BACKLOG note last, as tasks.json does.

## Process

Apply all of the above in one pass, keep counts consistent, re-run the dry-run style splice check ("not found: 0") and
the dev count check, and append "Round 1 changes" and "Round 1 open points" sections at the end of the plan (as Plan G
did). Do not commit; the controller commits.

---

# Round 2

## Static review

## Plan H round 2: static adversarial critic

Plan: `docs/superpowers/plans/2026-10-15-first-slice-h-leases-fences-heartbeat.md` (9833 lines, branch `plan-h`,
11342fa).

**Verdict: REVISE (small).** 0 Blocking, 3 Important, 6 Minor.

Round 1 is fixed in substance:
- B1, I1, I2, I5 and all eight Minors are FIXED. I3 and I4 are FIXED and PARTIAL respectively (details below).
- The effect-only design is sound. The registry is race-free against registration and completion, shutdown and loss
  are told apart correctly, and a loss that lands during a unit stops the handler at the next check.
- Every splice applies, every count matches, ruff and mypy are clean after every task, and every red step reproduces.

The three Important findings are each a few lines of test or helper code. Two came from the round-1 changes
themselves:
- The new DoD-3 lower bound fails about half the time.
- The I3 rewrite lets a NOWAIT 55P03 escape a claim.

The third is the I4 "two owners" monitor, which as written cannot fail.

### How this was checked

**Reading.** I read the diff between round 0 (03e2636) and round 1 (`critic2/r0_r1.diff`, 1858 lines) line by line. I
then re-read each changed block in context:
- `ops_core.lease` (whole), `acquire_lease`/`claim_next`/`fenced`/`release_lease`, `handlers` (whole), Task 3's
  `main`;
- Task 5's heartbeat, permit, drafting and `main` edits;
- the DoD-3 live module, the stress module, and the 0007 live round trip.

Against the repository I checked:
- `scripts/skeleton.upgrade/downgrade/migrate`, `tests/e2e/conftest.py` (database creation, the autouse `synced_at`
  stamp), `approved_run`;
- `migrations/app/env.py`, 0004's grant loop, `privileges.function_grant_statements`, the RLS/NO_RLS lists;
- `HttpMcpCaller`, and `persistence.connect` (no `lock_timeout`).

**Applying the plan.** The round-1 tooling (`critic1/apply.py` + `inline.py`) moved to `critic2/tools/`. I added a
task range and pinned each inline replace-all to its own task.

Then `drive.py` worked on a `git archive HEAD` copy, one task at a time, as an executor would:
1. apply task *k*;
2. `ruff format --diff`, then `ruff format`;
3. `ruff check`, mypy strict over the eight member trees, and the dev pytest.

Formatting between tasks matters here: round 1's own check applied all tasks before formatting, so it could not see a
later splice that quotes text an earlier format rewrote.

| After task | splices | ruff format rewrote | ruff check | mypy | pytest (dev; +12 env failures) |
|---|---|---|---|---|---|
| 1 | all once | nothing | clean | clean, 49 files | 845 + 12 = **857** / 104 |
| 2 | all once | nothing | clean | clean, 49 | **863** / 109 |
| 3 | all once | nothing | clean | clean, 50 | **880** / 119 |
| 4 | all once; replace-all counts 3/1/2/3 | `test_definers_write_path_live.py` only (declared by the plan) | clean | clean, 50 | **887** / 124 |
| 5 | all once | nothing | clean | clean, 52 | **905** / 128 |
| 6 | all once | nothing | clean | clean, 53 | **910** / 132 |
| 7 | all once | `api/.../app.py`: two extra blank lines from *my* tool's "insert before" (an artifact, not the plan) | clean | clean, 53 | **926** / 133 |

Notes on the table:
- The 12 env failures (`test_verify_handoff.py` 11, `test_text_hygiene.py` 1) are the archive copy's (no `.git`, no
  reference zip), exactly as in round 1.
- Every count equals the plan's.

**Red steps** were re-run on cut plans (`critic2/tools/red.py`; output in `critic2/red.log`). All of these reproduce
exactly, including the reasons:
- T4 S1: `11 failed, 7 passed` with the observed `ValueError`/`AttributeError`/`AssertionError`/`TypeError`s;
- T5: `2 errors in` (`ImportError … Renewal`, `ModuleNotFoundError … permit`), then `8 failed, 3 passed`;
- T6: `1 error in`, then `3 failed`;
- T7: `1 error in`, then `10 failed, 2 passed`.

**Repeat runs.** The four changed unit modules (`test_lease`, `test_heartbeat`, `test_permit`, `test_worker_units`,
37 tests, including the real-`HttpMcpCaller` cancellation) ran 10 times on Windows: 37 passed every time, in 2.0-2.3 s.

**Task 8 anchors.**
- `TODO(T13` grep over the applied tree prints nothing, and `grep -c` on 0007 prints `1`.
- The three `sweeper/README.md` old blocks and the `README.md` old tail are each found once in the repo.
- `PROJECT_HISTORY.md` has `## 25. What the process taught` and no "leases plan" section.

**Not run.** No live test was run and no database was touched. DB behaviour is judged statically.

---

### Round 1 verification

| Finding | Status | Evidence |
|---|---|---|
| **B1** cancellation in BEGIN wedges the loop connection | **FIXED** | `Lease.effect`/`cancel_effects` (plan 2436-2501). The check and registration run under the lease lock; the cancel snapshot is taken after `mark_lost` (`Heartbeat._lose` 6678-6682), so an effect either is in the snapshot or is refused at registration. The three handler calls go through `effect` (3046, 3084, 3151), as does the permit back-off (6754). `run_job` no longer wraps the handler in a task and catches `LeaseLost` only (6948-6966). The only `except BaseException` left is `effect`'s, which re-raises (and the stress/`_mark_unknown` refence brackets). `abandon` checks for an idle connection and closes it (3209-3211); `run_forever` re-raises an `OperationalError` on a closed connection, so the process exits 1. Tests: +3 lease, +1 abandon, the rewritten heartbeat-cancel test, `test_a_loss_during_a_unit_never_interrupts_it`; all pass, 10/10. No await outside a unit or an effect remains on the loop connection's path. Shutdown never cancels the poll task (see m2), so in practice no unit is ever cancelled. |
| **I1** RUF007 / ASYNC251 / mypy no-any-return | **FIXED** | `pairwise` (964); `block_the_loop` helper (7086-7096, ruff clean without noqa); `2.0 **` (6731). ruff and mypy clean after every task. |
| **I2** permit leak on a cancelled take | **FIXED** (by B1) | Take and release are units, never registered. The sleep is the only effect. `finally` releases exactly the returned slot. `test_a_loss_during_the_backoff_takes_and_keeps_no_permit` passes. |
| **I3** stress cannot see long waits | **FIXED as ruled, with a regression** | `wait=True` re-raises 55P03 (2732-2737), and the stress counts `LockNotAvailable` (8030). But the rewrite narrowed the NOWAIT→Busy mapping to the *first* lock statement only, so the second one now escapes: **N2** below. |
| **I4** no committed re-fence; ruling 21's two-owner check missing | **PARTIAL** | The committed re-fence is real and goes through the authority path: `approved_run` (decision via `record_decision` as `api`, the write handle minted under `lease_for`), then `grant_execution` as `mcp_exec`. The autouse fixture stamps `synced_at`, so the grant is not deferred. The lease is then expired, and `mark_unknown` on EXECUTING/OUTCOME_UNKNOWN commits a bump (0007 MARK_UNKNOWN, 4831-4880). The monitor, however, cannot fail: **N3**. |
| **I5** `check_leases` too permissive | **FIXED** | `2 × hb + RENEWAL_MARGIN_SECONDS(6) < lease` (747-766). 30/10 accepted; 10/4 refused with the exact message; bounds companions moved to heartbeat 1. (A pin for the duplicated constant: m4.) |
| **M1** FK key-share / hand-written list | **FIXED** | Docstring (861-876), the claim and the two start units list their FK parents (914-919), the test is renamed. Re-checked the cycle cases with the new ranks: none. |
| **M2** 20-30 s handle life | **FIXED** (smaller alternative) | Debt line (334-336), runbook paragraph (9404-9407). |
| **M3** prosrc-only proof; import-time guard | **FIXED** | Guard moved into `upgrade()` (Edit 5, 4938-4962). `built_to_0006` (5524-5540) is created and dropped by the superuser in try/finally, with `WITH (FORCE)` covering an engine that `upgrade()` left undisposed on failure. The app tree's `env.py` is connection-only with no database-specific statement. 0007's downgrade grant sequence (body with `ALTER OWNER`, `REVOKE … FROM PUBLIC`, `GRANT`) equals 0004's, so the ACL text should match. The testclock branch touches none of the six restored functions. Residual: m6. |
| **M4** DoD-3 margin | **FIXED, but the new assertion is wrong** | `max_loop_age` is recorded (6611, 6649-6650) and put in the evidence. The added lower bound `BLOCK_SECONDS <= max_loop_age` is **N1**. |
| **M5** stepped first acquisitions | **FIXED** | 3936-3958. Traced: B picks the second job by SKIP LOCKED, sees no row (A's is uncommitted) and its INSERT waits on A's xid, which `pg_blocking_pids` shows. After A commits: DO NOTHING, then the second lock, then a live lease, so `Busy(False)` and Deferred. |
| **M6** heartbeat connect timeout | **FIXED** | `connect_timeout=5` (6579). (A statement that hangs after connect: m3.) |
| **M7** real MCP cancellation | **FIXED** | `test_a_lost_lease_cancels_a_real_mcp_call` (6359-6397) passes 10/10 on Windows. `HttpMcpCaller` re-raises non-transport groups, and `effect` maps any exception after `cancel_effects` to `LeaseLost`. |
| **M8** per-tenant scan | **FIXED** | Debt line (337) and runbook (9425-9426). |
| Dry run WA-1..4 | **FIXED** | Folded in: `FUNCTIONS` is quoted in its formatted one-line form in Task 4 Edit 4 (4625), and it spliced after Task 2's format. |
| Format stability | **FIXED** | Only Task 4's declared file is rewritten by `ruff format`. |
| Red-step "Expected" lines | **FIXED** | All reproduce (above). |
| Task 8 items | **FIXED** | TODO grep exact; history block given; sweeper README blocks exact; README script; `reports/leases` guarded; BACKLOG appended after T13's notes. One cite is still one line early: "old lines 148-158" in `test_migrations_and_persistence.py` is 149-158 at HEAD (harmless, since the splice is by text). One new over-length line: m5. |

---

### Blocking

None.

---

### Important

**N1 — The new DoD-3 lower bound `BLOCK_SECONDS <= heartbeat.max_loop_age` fails about half the runs.**

Where: Task 5 Step 3, `test_r088_a_loop_blocked_for_25_seconds_keeps_its_lease` (plan 7182). It was added for round-1
M4.

Evidence:
- The loop stamps every `STAMP_SECONDS = 1.0` (6537, `keep_stamping`). The last stamp `s0` before the block therefore
  lies anywhere in `[b0 − 1, b0)`, where `b0` is the instant `block_the_loop` starts.
- The thread samples silence once per tick, every `TICK_SECONDS = 1.0` (`Event.wait(1)` plus the tick's own time).
  The last tick inside the 25 s block lands anywhere in `(b0 + 24, b0 + 25]`.
- When the block ends, the loop stamps within milliseconds: `keep_stamping`'s overdue timer runs on the next
  iteration. So no later tick sees a longer silence.
- Hence `max_loop_age = (τ_last − b0) + (b0 − s0)` is roughly `24 + U(0,1) + U(0,1)`, which is below 25 with
  probability about 0.5.
- The upper bound (`< 28`) is right. Round 1's M4 analysis ("peaks at about 26.x s") was about the upper end only.

Why it matters: a 30 s `slow_live` DoD test in the Task 5, Task 8 and every later live gate goes red at random. The
executor will "fix" it ad hoc, or rerun until green.

Fix:
```python
assert BLOCK_SECONDS - TICK_SECONDS - STAMP_SECONDS < heartbeat.max_loop_age < settings.leases().loop_stall_seconds
```
(import both constants from `ops_worker.heartbeat`; 23 < age < 28). Alternatively drop the lower bound and keep only
the upper bound plus the evidence line.

**N2 — After I3's rewrite, a NOWAIT 55P03 on `acquire_lease`'s *second* lock statement escapes as an exception;
the stress test counts it as 55P03, and a production claim logs a spurious "transient database error".**

Where: Task 3 Step 3, `acquire_lease` (plan 2731-2752). Only the first `conn.execute(lock, …)` (2733) is wrapped. The
one after `_CREATE_LEASE` (2741) is not. Round 0 caught `LockNotAvailable` around the whole savepoint, so both lock
statements mapped to `Busy(locked=True)`.

Evidence (the first-acquisition race, Review Focus 1):
1. T1 and T2 both find no row.
2. T2's `INSERT … ON CONFLICT DO NOTHING` waits on T1's xid.
3. When T1 commits, every waiter wakes at once. T2 does nothing and then runs `LOCK_FOR_UPDATE_NOWAIT`.
4. If any other transaction got the tuple lock first, T2's NOWAIT raises 55P03. Candidates are a waking `wait=True`
   acquirer's FOR UPDATE, or T1's own next unit (FOR SHARE) or renewal (FOR UPDATE).
5. That 55P03 is no longer converted. It propagates out of `acquire_lease` and `claim_next`.

Consequences:
- **Stress test** (Task 6, 7884-8135):
  - At the start, both QUEUED runs have no lease row.
  - Every actor's first operation is an acquisition, because a non-claim op with `lease is None` becomes a waiting
    acquire (7973), so about 8 near-simultaneous first acquisitions hit 3 runs.
  - A claimer that waited on another inserter can lose that wake-up race.
  - `Actor.step` then tallies `55P03` (8030), and `assert tally["55P03"] == 0` fails.
  - This is a start-up race, so the DoD-2 gate goes red intermittently, and the "no 55P03" evidence would blame the
    lock order for a mapping bug.
- **Production:** `run_forever` catches it as `psycopg.OperationalError`. The connection is not broken, so it logs
  "transient database error (deadlock, serialization)" with a traceback and retries, instead of deferring the job one
  second as ruling 3 says. It is harmless but noisy, and it contradicts the docstring's `Raises:` (2723-2725) and
  Round 1 changes' "with NOWAIT … the lock statement's 55P03 is Busy(locked=True)".
- Side note: the stress's `if taken == Busy(locked=True): tally["55P03"] += 1` (7978-7979) is now dead code, because
  `wait=True` can no longer return `locked=True`.

Fix:
1. Route both lock statements through one helper:
   ```python
   async def _lock_row(conn: Conn, lock: str, run_id: UUID, *, wait: bool) -> AsyncCursor[DictRow]:
       try:
           return await conn.execute(lock, (run_id,))
       except psycopg.errors.LockNotAvailable:
           if wait:
               raise  # a long lock wait, which the stress test counts, never a busy lease
           raise _Locked from None  # NOWAIT met a held row: busy (ruling 3)
   ```
2. Add a `test_lease.py` unit test: a fake connection whose second lock raises `LockNotAvailable` must give
   `Busy(locked=True)` with `wait=False`, and must raise with `wait=True`.
3. Drop or re-comment the dead stress branch.

**N3 — The "never two owners" monitor (ruling 21, I4) can only fire if a fence is handed out twice, which the test
already asserts separately; it never looks at whether two actors both believe they hold a live lease.**

Where: Task 6 Step 3, `monitor()` (plan 8082-8098), the `two_owners` assertion (8105), the evidence line ("never two
owners", 8120-8121), and the acceptance text ("never two owners of a run", 9197).

Evidence:
- `holders` is the set of actors whose held `Lease.fence` equals the row's fence (8095).
- Every fence an actor holds was appended to `acquired[run]`: claim, acquire and bump all do it. So
  `len(holders) > 1` implies a duplicate in `acquired`, which `len(fences) == len(set(fences))` (8108) already
  catches.
- The second clause (`row["live"] and holders != [row["owner"]]`) needs the row's owner to differ from the actor
  that took that fence. But only `_TAKE_LEASE` changes the owner, and it always moves the fence too. `mark_unknown`
  keeps the owner and refuses a stale fence.
- So the check is implied by the uniqueness assertion. It never compares the rows with the actors' *local* belief,
  which is what "two owners with live leases" means once the database allows only one owner row:
  - a stale actor A whose `Lease` still passes `check()` (not lost, before its local deadline);
  - another actor B that holds the newer fence.
- That situation is exactly what SA:195's 5 s margin is meant to make impossible. It is the one property the
  in-memory half of the design adds, and the stress is the only place it could be observed under load.

Why it matters: I4 asked for that observation to be restored, but the evidence line and acceptance row would assert a
property the test cannot detect, the same "vacuous evidence" class as round 1's I3.

Fix: at each sample, per run:
```python
live_here = [a.name for a in actors
             if (held := a.held.get(run)) is not None and held.lost is None and time.monotonic() < held.deadline]
if len(live_here) > 1 or (live_here and row["live"] and live_here != [row["owner"]]):
    two_owners.append(...)
```
- Keep the fence-equality check as well if wanted.
- This holds by construction: B can acquire only after A's database expiry, and A's local deadline is at least 5 s
  before that, because its monotonic start precedes the acquiring statement.
- So a violation means the margin is broken. Note in the docstring that the R019 test resets the test clock offset,
  so the database clock and the monotonic clock agree during the stress.

---

### Minor

**m1 — Nothing bounds a worker unit's lock wait any more.**

Where: ruling 19 as amended (plan 210-223), `persistence.connect` (repo `core/.../persistence.py:119-122`, no
`lock_timeout`). It used to be bounded only by the heartbeat's cancel.

Evidence:
- A fenced unit holds `run_lease FOR SHARE` and can then wait on `runs`/`jobs` behind a peer's hung transaction.
- The heartbeat's own renewal is blocked by that share lock (5 s `lock_timeout`), the deadline passes, and the lease is
  marked lost. `cancel_effects` cancels nothing, so the unit waits indefinitely.
- Fencing stays safe: the share lock also blocks every takeover. But the run is stuck until the peer ends, where
  round 0's cancel would have freed it.
- "A loss during one is caught by the next `fenced()`/`check()`" assumes short units.

Fix: put a `lock_timeout` on the loop connection (e.g. `SET lock_timeout = '10s'` after `persistence.connect` in
`_main`, with 55P03 already handled as a transient `OperationalError` by `run_forever`). Or name it explicitly on the
T30 debt line ("per-unit lock_timeout") as the worker's, not only the API's.

**m2 — Shutdown is described wrongly, and it stops the liveness stamps before the job ends.**

Where: Self-review "Known risks" (plan 9720-9721) says "the one remaining cancellation of a unit is the worker's own
shutdown". Task 5 Edit 5 (7015) is the second half.

Evidence:
- `_main` never cancels `polling`. It sets `stop` and gathers, so the current job runs to its end.
- Edit 5 gathers `stamping` in the same call, and `keep_stamping` exits on `stop` at once.
- So a job still running at shutdown loses its lease to "event loop stalled" 28 s later. Its effect is cancelled and
  the job is handed back with a misleading log reason.

Fix:
- Stop the stamps only after `polling` ends: gather `serving` and `polling` first, then `stamping`. That also needs a
  separate stop event for the stamps, because `stop` is shared.
- Correct the risk sentence: no unit is ever cancelled. Only an interpreter-level interrupt (a second Ctrl+C) can
  cancel the poll task, and the process ends then.

**m3 — The heartbeat's synchronous connection has connect and lock timeouts but no statement or keepalive bound.**

Where: `connector` (plan 6575-6581).

Evidence:
- After a successful connect, a half-open TCP connection (peer gone, no RST) blocks `renew` until the OS gives up,
  which takes minutes.
- Meanwhile no tick runs, no gate is evaluated and no in-flight effect is cancelled. Safety holds through the fence
  and the handle cap.

Fix: `options` with `-c statement_timeout=5s` on the heartbeat's conninfo (or `keepalives_idle`/`tcp_user_timeout`).
`renew` is one short statement.

**m4 — `RENEWAL_MARGIN_SECONDS = 6` duplicates `lease.DEADLINE_MARGIN_SECONDS + heartbeat.TICK_SECONDS` with no pin,
and the error message hard-codes "- 6".**

Where: plan 747, 762.

Fix: a unit test asserting
`settings.RENEWAL_MARGIN_SECONDS == lease.DEADLINE_MARGIN_SECONDS + heartbeat.TICK_SECONDS` (the test may import all
three; the settings module still imports nothing from the worker). Alternatively, build the message from the constant.

**m5 — A worker README line is 141 characters, which fails the plan's own counting rule.**

Where: Task 8, the `worker/README.md` "Runs" block (plan 9564: "T19) → frozen proposal → … One `ops-worker` token
carries both MCP audiences; one"). The round-1 rewording re-wrapped only part of the paragraph.

Fix: re-wrap the paragraph at 120.

**m6 — `built_to_0006` can leave a stray database behind.**

Where: plan 5530-5540; `recreate_databases` (repo `tests/e2e/conftest.py:52-66`).

Evidence: a run killed between `CREATE DATABASE r006_…` and the `finally` leaves that database. Nothing sweeps it:
`recreate_databases` drops only the two test databases.

Fix: at the start of `built_to_0006`, or in `recreate_databases`, drop every `datname LIKE 'r006\_%'` from
`pg_database` with `WITH (FORCE)`.

---

### Checked and found sound (round-1 changes)

**Registry thread safety.**
- `_effects` is read and written only under `_lock`. `loop.create_task` runs under it, which is safe because no eager
  task factory is set; with one, the child would run synchronously under the lock and could re-enter `lease.fence`.
- `cancel_effects` snapshots under the lock and calls `call_soon_threadsafe` outside it. On a closed loop it catches
  `RuntimeError`.
- **Registration race:** `_lose` calls `mark_lost` before `cancel_effects`. An effect registered after the mark is
  refused (`_why_not_held`); one registered before it is in the snapshot.
- **Completion race:** a cancel that lands after the child finished is a no-op. A value returned after the loss is
  dropped at the next `fenced`/`check`, or by `release_lease`'s owner and fence comparison.
- An exception raised after `cancel_effects` becomes `LeaseLost`.
- The local-deadline loss set by the loop's `_why_not_held` never coincides with an effect in flight: the loop calls
  it only between effects, and the heartbeat's `lost is not None → drop` then has nothing to cancel.

**Shutdown versus loss.**
- An outer cancel propagates to the child through `_fut_waiter`. `cancelling() > 0` then re-raises the
  `CancelledError` unchanged, even when a loss also happened.
- `asyncio.timeout` and `wait_for` uncancel on expiry on 3.13, so no stale count leaks into the poll task.
- An effect that swallows the cancel and returns normally is caught at the next check. One that swallows it and hangs
  is bounded only by its own timeout (60 s MCP read), the same as round 0.

**A loss during a unit.** Every handler path follows each unit with a `fenced` unit, an `effect` or
`release_lease`:
- `investigate`: the `_event` fence, the MCP effect, `_fail`'s fence;
- `_draft_and_freeze`: the generate effect, then the freeze unit's fence;
- `execute`: the MCP effect, then `release_lease` or `_mark_unknown`'s `check()`.
- The permit's release unit runs in `finally` before `LeaseLost` reaches `abandon`, on the same idle connection.
- Prompt stop holds, except for an unbounded lock wait inside the unit (m1).

**Post-SENT UNKNOWN, lock order and clock rule.** All are unchanged by round 1:
- The stress's grant happens in setup, outside the mix.
- `abandon`'s idle check takes no lock.
- No comparison moved before a lock.

**The stress's EXECUTING run.**
- Seeded through the real authority path: the worker freezes the proposal, the API records the decision, the worker
  mints under a lease, and `mcp_exec` grants.
- A second UNKNOWN only moves the fence (MARK_UNKNOWN 4851-4855), so re-fences keep committing. `begin_refence`/
  `end_refence` bracket each one.
- `run_lease` and `invocation_context` are NO_RLS, so the tenant-less mint and fenced ops on the ALPHA run work.
- The run lives on ALPHA, so `claim_next(tenant_ids=[tenant])` never picks its jobs. All actor ops on it are waiting
  acquisitions, which is fine.

**The stepped first-acquisition test (M5)** — traced above.

**`built_to_0006` (M3)** — superuser CREATE/DROP; `env.py` is connection-only; no revision reads settings; the grant
sequence matches 0004's; the testclock branch is not involved.


## Builder dry run

# Plan H dry run, round 2 (builder report)

Plan: `docs/superpowers/plans/2026-10-15-first-slice-h-leases-fences-heartbeat.md` at `plan-h` 11342fa.
Worktree: `<scratch>/planh/dryrun2`, detached at 11342fa, `uv sync --locked`. It was removed at the end
(`git worktree remove --force` and `git worktree prune`). Date: 2026-10-15.

Method (as round 1): a helper copied each fenced block from the plan byte for byte (by plan line number) and refused any
splice whose old text was not found exactly once. Each inline replace-all was counted with `grep -cF` before it was
applied and compared with the plan's stated count. After every task: `ruff format` + `ruff check --fix` on the task's
files, the 120-character count, then `ruff format --check .` over the whole tree.

Scope: dev gates only. Every `OPS_LIVE=1` step is **SKIPPED (live, out of scope)**: no `.env` was copied, linked or
recreated, and no database or container was touched. The edits of every live step were applied anyway, and each live
module was collected without `OPS_LIVE` (`--collect-only -q`) to compare its count with the plan's expected live count.

## Summary

- Steps: 47 in total.
  - OK: 41. Eight of them (marked OK*) are mixed steps whose dev half matched and whose live half was skipped.
  - DIFFERS: 0.
  - WORKAROUND: 0.
  - SKIPPED (live, out of scope): 6. These are steps whose only check is a live run; every edit in them applied cleanly.
- Every splice found its old text exactly once. Every replace-all count matched the plan (3/5/1/6 in Task 3; 3/1/2/3
  and 2 in Task 4). Both "afterwards prints 0" greps printed `0`.
- Round 1's workarounds WA-1..WA-4 are no longer needed (details below), and the seven format-unstable blocks are
  gone: `ruff format` left every task's files unchanged except the three Task 4 lines the plan itself says it wraps.
- Every red step failed with the count **and** the reason the plan states, including the four round-1 corrections.
- Scratch commits (thrown away with the worktree):

  | Commit | Content |
  |---|---|
  | bec6a2d | debt list |
  | dc9673e | T1 |
  | 3128be9 | T2 |
  | e5e7f5e | T3 |
  | 6637833 | T4 |
  | e4eb4b4 | T5 |
  | 99ed878 | T6 |
  | 2860b5f | T7 |
  | a66e69f | T8 |

  Task 8's script printed `11342fa..2860b5f`.

### Gates: observed vs expected

| When | Dev `check.py` observed (pytest time) | Dev expected | mypy | `verify_handoff` | Live |
|---|---|---|---|---|---|
| T1 S1a baseline | 816 passed, 104 skipped, GREEN (40.33 s; 50.5 s wall) | 816/104 | 48 files, clean | — | SKIPPED (exp 899/21) |
| T1 S7 | 857/104 GREEN (34.78 s) | 857/104 | 49, clean | exit 0 | not required |
| T2 S7 | 863/109 GREEN (37.15 s) | 863/109 | 49, clean | exit 0 | SKIPPED (exp 951/21) |
| T3 S8 | 880/119 GREEN (36.55 s) | 880/119 | 50, clean | exit 0 | SKIPPED (exp 978/21) |
| T4 S6 | 887/124 GREEN (37.48 s) | 887/124 | 50, clean | exit 0 | SKIPPED (exp 990/21) |
| T5 S4 | 905/128 GREEN (39.16 s) | 905/128 | 52, clean | exit 0 | SKIPPED (exp 1012/21) |
| T6 S4 | 910/132 GREEN (38.87 s) | 910/132 | 53, clean | exit 0 | SKIPPED (exp 1021/21) |
| T7 S3 | 926/133 GREEN (38.71 s) | 926/133 | 53, clean | exit 0 | SKIPPED (exp 1038/21) |
| T8 S5 | 926/133 GREEN (40.78 s) | 926/133 | 53, clean | exit 0 | SKIPPED (exp 1038/21) |

`ruff check` was "All checks passed!" in every gate. `ruff format --check .` after each task: 217, 220, 224, 226, 231,
235, 238, 238 files already formatted.

Live modules collected without `OPS_LIVE`; each count equals the plan's expected live pass count:

| Step | Modules | Collected | Plan's expected live result |
|---|---|---|---|
| T2 S6 | 0007, roles, persistence, 0006 | 22 | `22 passed` |
| T3 S6 | worker, persistence, mcp-read, mcp-write | 18 | `18 passed` |
| T3 S7 | leases | 10 | `10 passed` |
| T4 S5 | the seven modules | 49 | `49 passed` |
| T5 S3 | heartbeat, worker, leases | 18 | `18 passed` |
| T6 S3 | stress, admission, sweeper | 14 | `14 passed` |
| T7 S3 | admission, incident-sim | 13 | `13 passed` |

`pytest tests/e2e/test_heartbeat_live.py -m "not slow_live"` gave `1 skipped, 3 deselected`, so the marker is
registered and the three DoD tests carry it.

Unit runs, all as the plan says:

| Step | Command (abridged) | Observed | Expected |
|---|---|---|---|
| T1 S4 | settings_leases + plan_g admission settings | 16 passed | 16 |
| T1 S6 | test_locking | 30 passed | 30 |
| T2 S4 | 0007, transitions, privileges, locking | 53 passed | 53 |
| T3 S4 | lease, worker_units, grant_deferred, rotate, plan_d worker | 42 passed | 42 |
| T4 S3 | plan_h, transitions, privileges, grant_deferred | 91 passed | 91 |
| T5 S2 | plan_h, plan_d worker, grant_deferred | 96 passed | 96 |
| T6 S2 | reclaim, global_queue, plan_g, plan_f sweeper | 149 passed | 149 |
| T7 S2 | plan_h, plan_g, plan_e faults/sim, plan_d sim/api, plan_f | 421 passed (plan_h 109, plan_f 147) | 421 |

### Flake runs (unit level)

Each module was run 5 times on its own at the end of Task 5, and again 5 times at the final tree (Task 8), plus 5 runs
of the four together. No flake in any run:

| Module | Result, every run | Time per run |
|---|---|---|
| `tests/plan_h/test_heartbeat.py` | 9 passed | 0.37-0.42 s |
| `tests/plan_h/test_lease.py` | 11 passed | 0.40-0.46 s |
| `tests/plan_h/test_permit.py` | 6 passed | 0.70-0.96 s |
| `tests/plan_h/test_worker_units.py` | 11 passed | 1.62-1.75 s |
| the four together | 37 passed | 1.98-2.11 s |

`test_heartbeat.py` includes `test_the_thread_cancels_the_effect_on_the_loop_and_stops` (a real `threading.Thread`
cancelling an effect through `call_soon_threadsafe` under `asyncio.run`'s default loop on Windows), and
`test_worker_units.py` includes `test_a_lost_lease_cancels_a_real_mcp_call` (the real `HttpMcpCaller` against a silent
local server; the loss is raised as LeaseLost well under its 10 s bound in every run).

## Round-1 items, re-checked

| Round-1 item | Round 2 |
|---|---|
| WA-1 RUF007 in `locking.py` | Gone: the block uses `pairwise`; `ruff check` clean in T1 S7. |
| WA-2 0007 `FUNCTIONS` reformatted, T4 Edit 4 not found | Gone: Task 2 writes the one-line form, `ruff format` leaves it, Edit 4 found once. |
| WA-3 ASYNC251 in the heartbeat live test | Gone: `block_the_loop` is a sync helper; `ruff check` clean in T5 S4. |
| WA-4 mypy `no-any-return` in `permit.backoff` | Gone: `2.0 ** min(attempt, 3)`; mypy clean on 52 files in T5 S4. |
| Seven format-unstable blocks | Gone: every task's files "left unchanged" by `ruff format`, except T4's Edit 12 lines in `test_definers_write_path_live.py` (the plan says the format wraps them and no later edit quotes them). |
| T2 S2 reason for the newest-revision test | Now stated as `AssertionError: run_lease`; observed exactly that. |
| T4 S1 reason for the first revision test | Now `ValueError: 'DROP FUNCTION app.mark_sent(uuid)' is not in list`; observed exactly that. Second: `AttributeError … 'MARK_UNKNOWN'`; third: AssertionError on the downgrade's first statements; six worker tests `AttributeError … 'Unknown'`; both write-path tests `TypeError` (positional action id). All as stated. |
| T5/T6/T7 S1 collection errors | Now split into separate runs. T5: `2 errors in` (`Renewal` ImportError, `ops_worker.permit` ModuleNotFoundError), then `8 failed, 3 passed` with `has no attribute 'take_model_permit'` (the three passing tests are the deferral, abandon and real-MCP tests). T6: `1 error in` (`leases`), then `3 failed` with the stated TypeError. T7: `1 error in` (`BS405`), then `10 failed, 2 passed` (incident-sim: 422 on arming / unchanged hot path; API: `create_app() … 'faults'`). |
| T8 S1 expected outputs | `git grep` prints nothing; `grep -c` prints `1` (line 176, `GRANT_TODO_0005`). As stated. |
| T8 S2 BACKLOG note position | Appended last under T13, as `tasks.json` does. The acceptance matrix changed exactly R015, R019, R020, R087, R088, R098, R107 (checked with a JSON comparison; top-level keys unchanged). |
| T8 S4 PROJECT_HISTORY fallback | Text now given. No "The leases plan" section existed, so it was inserted before `## 25. What the process taught`, which became 26; nothing else in the repo cites the section number. |
| T8 S4 `sweeper/README.md` line 3 | Now replaced; all three blocks found once; the result reads cleanly. |
| T8 S6 `git add` of a missing `reports/leases` | Now conditional: printed `reports/leases missing: rerun Step 5` (expected without a live run) and the commit went through. |
| Line cite: `test_migrations_and_persistence.py` Edit 2 | Still off by one: the old text is lines 149-158, the plan says 148-158 (round 1 proposed 148-158 too). r105 Edit 1 is now right (25-26). |

## Task 1

| Step | Status | Note |
|---|---|---|
| 1a | OK* | dev 816/104 GREEN; live SKIPPED |
| 1b | OK | BASE=11342fa (ledger under the ignored `.superpowers/`) |
| 1c | OK | debt section inserted before `## Environment (observed)` |
| 2 | OK | both `pyproject.toml` splices found once |
| 3 | OK | `1 error in`, ImportError `LeaseSettings` |
| 4 | OK | 16 passed |
| 5 | OK | `1 error in`, ImportError `locking` |
| 6 | OK | 30 passed |
| 7 | OK | format/lint/count clean; 857/104 GREEN; vh exit 0 |

## Task 2

| Step | Status | Note |
|---|---|---|
| 1 | OK | `1 error in` (module-level assert on `REVISIONS`) |
| 2 | OK | ISC004 changed nothing; `5 failed, 12 passed` with the five stated reasons |
| 3 | OK | 5 splices once (cite nit: privileges Edit 3's old text is 157-159, plan says 157-158) |
| 4 | OK | 53 passed |
| 5 | OK | both splices once |
| 6 | SKIPPED (live, out of scope) | file written; collects 22 |
| 7 | OK* | format left 9 files unchanged; 863/109 GREEN; vh 0; live SKIPPED |

## Task 3

| Step | Status | Note |
|---|---|---|
| 1 | OK | `3 errors in`, ModuleNotFoundError `ops_core.lease` ×3 |
| 2 | OK | |
| 3 | OK | 7 splices once |
| 4 | OK | 42 passed; format left 28 files unchanged |
| 5 | OK | 4 splices once |
| 6 | SKIPPED (live, out of scope) | every edit applied; replace-all counts 3/5/1/6; grep printed `0`; collects 18 (cite nits below) |
| 7 | SKIPPED (live, out of scope) | file written; collects 10 |
| 8 | OK* | format left 15 files unchanged; 880/119 GREEN; vh 0; live SKIPPED |

## Task 4

| Step | Status | Note |
|---|---|---|
| 1 | OK | `11 failed, 7 passed`, each reason as stated |
| 2 | OK | Edits 1-5 once (Edit 4 included); ISC004 changed nothing; privileges edit once |
| 3 | OK | 8 splices once; 91 passed |
| 4 | OK | every splice once; replace-all counts 3, 1, 2, 3 and 2 as stated; grep printed `0`; `ruff check --select F` and an AST check found `handle`, `new_handle`, `stale_handle`, `cancelled_handle` bound wherever used |
| 5 | SKIPPED (live, out of scope) | file written; collects 49 |
| 6 | OK* | format reformatted 1 file (Edit 12's lines, as the plan predicts); 887/124 GREEN; vh 0; live SKIPPED |

## Task 5

| Step | Status | Note |
|---|---|---|
| 1 | OK | `2 errors in`, then `8 failed, 3 passed`, as stated |
| 2 | OK | all splices once (insert after `unclaim_job` landed before `finish_job`); 96 passed |
| 3 | SKIPPED (live, out of scope) | file written; collects 18; `-m "not slow_live"` → 3 deselected |
| 4 | OK* | format left 11 files unchanged; ruff clean (no ASYNC251); mypy clean; 905/128 GREEN; vh 0; live SKIPPED |

## Task 6

| Step | Status | Note |
|---|---|---|
| 1 | OK | `1 error in` (`leases`); `3 failed` with the stated TypeError |
| 2 | OK | every splice once; insert after `queued_count` once; 149 passed |
| 3 | SKIPPED (live, out of scope) | stress file written; admission edits once; helper names exist (`count`, `h`, `messages`, `conversation`, `api`, `Role.TEST_HARNESS`, `new_run(conn, tenant, api=)`); collects 14 |
| 4 | OK* | format left 11 files unchanged; 910/132 GREEN; vh 0; live SKIPPED |

## Task 7

| Step | Status | Note |
|---|---|---|
| 1 | OK | `1 error in` (`BS405`); `10 failed, 2 passed` as stated |
| 2 | OK | faults.py replaced; 7 incident-sim, 3 store, 6 app (plus the `API_FAULTS` insert, anchor found once), 2 plan_g, 3 admission splices once, one append; 421 passed |
| 3 | OK* | format left 9 files unchanged; live run SKIPPED (collects 13); 926/133 GREEN; vh 0 |

## Task 8

| Step | Status | Note |
|---|---|---|
| 1 | OK | `git grep` printed nothing; `grep -c` printed `1` |
| 2 | OK | printed `11342fa..2860b5f`; 3 handoff files changed; exactly the seven matrix rows |
| 3 | OK | the five SESSION_STATE edits, each anchor once; the two execution bullets written as "none" |
| 4 | OK | every anchor once; README script exit 0 (observation below on `worker/README.md`) |
| 5 | OK* | 926/133 GREEN; vh 0; live SKIPPED, so `<live passed>` stays unfillable (filled with a note in the scratch copy) |
| 6 | OK | adds succeeded; the conditional printed `reports/leases missing: rerun Step 5`; commit made |

## Observations (no workaround needed; cosmetic plan fixes)

1. **Line cites** that do not match the tree at the point the step runs. Every affected splice still found its old text
   exactly once, so none of these blocked anything.

   | Step | File, edit | Actual lines | Plan says |
   |---|---|---|---|
   | T2 S3 | `privileges.py` Edit 3 | 157-159 | 157-158 |
   | T3 S6 | `test_migrations_and_persistence.py` Edit 2 | 149-158 | 148-158 |
   | T3 S6 | `test_mcp_write_live.py` Edit 2 | 85-89 | 84-89 (Files line: 83-89) |
   | T4 S3 | `execution.py` Edit 1 | 29-31 | 29-32 |
   | T4 S4 | `test_definers_write_path_live.py` Edit 8 | 463-473 | 463-474 |
   | T4 S4 | `test_mcp_write_live.py` docstring line, as Task 3 left it | 279 | 276 (Files line: 274-276) |
   | T5 S2 | `drafting.py` Edit 1 | 9-13 | 85-89 (Files line too) |
   | T5 S2 | `drafting.py` Edit 2 | 56-62 | 132-138 (Files line too) |
   | T7 S2 | `store.py` Edits 1-3, as Task 6 left it | 351; 357-362; 1016-1017 | 347; 353-358; 999-1000 (these are the pre-Task-6 numbers; the Files line too) |

   `drafting.py` is 83 lines long, so its two cites cannot be right in any version of the file.

2. **`worker/README.md`, one line over 120 characters.** The new "Runs" section's line 8 (plan line 9564, "T19) →
   frozen proposal → AWAITING_APPROVAL. `execute`: `create_incident` on mcp-write. One `ops-worker` token carries both
   MCP audiences; one") is 141 characters; the README it replaces kept every line within 120. Minimal fix: rewrap that
   line in the plan's block, for example break after "on mcp-write.".

3. **Task 8 Step 4 (PROJECT_HISTORY).** The inserted section 25 narrates round 1 only. The plan's own text says later
   review rounds add their paragraph before execution, so a round-2 paragraph is due from the controller. This is a
   reminder, not a defect.

4. **`append:` instructions** (T4 S1 twice, T5 S1, T5 S2 `lease.py`, T6 S3, T7 S2, conftest `stage_lease`) give no
   separator. I appended each block after two blank lines. `ruff format` would add them anyway, so the result is the
   same either way.

## Workarounds

None. The four round-1 workarounds are no longer needed (WA-1 `pairwise`, WA-2 one-line `FUNCTIONS`, WA-3
`block_the_loop`, WA-4 `2.0 **`). No splice was refused, and no step needed a change to the plan's text to run.

Minimal plan fixes suggested: only the cosmetic ones under Observations 1 and 2 (the line cites, and rewrapping one
README line).

## Not verified (needs the live run)

Every live expectation from round 1's list still stands unverified:

- the 0007 round trip, with `prosrc` and the scratch-database `built_to_0006` comparison;
- the interleavings and their sub-second / 2.5 s timings;
- the stepped two-first-claims test and the stress test (DoD 2; 3× repeats were not possible);
- the three slow_live DoD-3 tests (the 25 s block against the 28 s gate, the 35 s drafter, the forced renewal failure);
- R019 with the test clock;
- the global bound and the R015 live tests;
- R105 with the leasing worker, heartbeat and reclaim;
- the live gate counts 951/978/990/1012/1021/1038 with 21 skipped;
- the roughly 2.5 extra minutes the live gate is expected to take.

## Clean-up

- No database or container was touched; no live run was attempted; `.env` was never opened, copied or recreated.
- `git worktree remove --force` and `git worktree prune` both ran. `git worktree list` shows only
  `C:/Users/joeys/Desktop/MLOps 11342fa [plan-h]`.
- `git -C C:\Users\joeys\Desktop\MLOps status --short` is empty, and `plan-h` is still at 11342fa with nothing
  committed on it.


## Controller rulings

# Plan H review, round 2 — controller rulings

Inputs: `round2-static.md` (REVISE small: 0 Blocking, 3 Important, 6 Minor; round 1 fixed in substance) and
`round2-dryrun.md` (47 steps: 41 OK, 0 DIFFERS, 0 WORKAROUND, 6 live SKIPPED; every dev gate equal to the plan; no
flake in 5+5 runs; cosmetic line cites and one 141-character README line).

- **N1 (DoD-3 lower bound flaky) — ACCEPTED.** Use
  `BLOCK_SECONDS - TICK_SECONDS - STAMP_SECONDS < max_loop_age < stall` (name the two sampling periods as the plan's
  constants) and say in a comment why the bound is not `BLOCK_SECONDS <= max_loop_age`.
- **N2 (55P03 after the first-row INSERT escapes `claim_next`) — ACCEPTED.** One shared helper for both NOWAIT lock
  statements in the acquisition (both map 55P03 → `Busy(locked=True)` in no-wait mode; only `wait=True` propagates);
  add a unit test for the second statement's conflict (fake connection raising 55P03 on it).
- **N3 (two-owner monitor cannot detect two owners) — ACCEPTED.** Count, per run, actors whose own `Lease` still passes
  its local check (not lost, before its local deadline) at each sample; require at most one, and require that one to be
  the owner and fence of a row that is live in the database at that sample (read in the same sample). Adjust the
  evidence line and acceptance text to say exactly what is checked.
- **m1 — ACCEPTED.** The worker's loop connection sets a session `lock_timeout` (10 s, a named constant) at connect; a
  unit that hits it raises 55P03, which the loop already logs as transient; the job keeps its claim until the lease
  lapses and the sweeper reclaims it. State this in the runbook.
- **m2 — ACCEPTED.** Correct the text (shutdown never cancels a unit) and keep the liveness stamps running until the
  current job ends, so shutdown does not turn into a false "event loop stalled" loss.
- **m3 — ACCEPTED.** The heartbeat connection gets `connect_timeout`, `statement_timeout` (5 s) and TCP keepalives in
  its conninfo/options; a timeout is a transient renewal error (ruling 19's rule applies).
- **m4 — ACCEPTED.** A unit test pins `RENEWAL_MARGIN_SECONDS == DEADLINE_MARGIN_SECONDS + TICK_SECONDS` (or derive
  one from the others).
- **m5 — ACCEPTED.** Rewrap the README line after "on mcp-write.".
- **m6 — ACCEPTED.** Scratch databases use a fixed prefix and the fixture drops leftovers with that prefix before it
  creates its own (superuser, inside the same try/finally).
- **Dry-run cites — ACCEPTED.** Correct every line cite in the dry-run table (the edits match by text, but the cites
  must be true at the moment the step runs) and the remaining 148→149 cite.
- **PROJECT_HISTORY section** — add the round-2 story in two or three sentences (the stuck-INTRANS cancellation found in
  round 1, the flaky lower bound, the NOWAIT regression and the vacuous two-owner check found in round 2).

Apply in one pass, keep counts consistent, re-run the splice check and the task-by-task apply with `ruff format`
between tasks (as the round-2 critic did), and append "Round 2 changes" / "Round 2 open points". Do not commit.

---

# Round 3

## Static review

## Plan H round 3: static adversarial critic

Plan: `docs/superpowers/plans/2026-10-15-first-slice-h-leases-fences-heartbeat.md` (10,062 lines, branch `plan-h`,
6ca01b3 "Plan H round 2 fixes").

**Verdict: APPROVE WITH SMALL FIXES.** 0 Blocking, 1 Important, 6 Minor.

Round 2 is fixed in full:
- N1, N2, N3, m1, m2, m4, m5 and m6 are FIXED. m3 is FIXED as ruled, with one overstated docstring claim (m-c below).
- The cites and the PROJECT_HISTORY paragraph are FIXED.
- None of the round-2 changes introduces a safety defect:
  - `_lock_row` maps both NOWAIT statements correctly, and the savepoint recovers;
  - the new monitor has no false positive under the plan's clock assumption;
  - the loop's `lock_timeout` cannot cut a unit that should wait;
  - the heartbeat options do not collide with `-c timezone=UTC`;
  - the separate stamps event is ordered correctly.

The one Important finding is older than round 2, and all three earlier reviews missed it:
- A handed-back `investigate` job whose run is already RETRIEVING or DRAFTING does no work when it runs again. It
  closes the job and strands the run in an active state.
- The plan says the opposite in three places.
- It came out of the end-to-end pass (section 3), and round 2's m1 adds one more way to reach it.

Executability:
- The plan applies task by task to a `git archive HEAD` copy, with `ruff format` between tasks.
- Every count equals the plan's, ruff and mypy are clean after every task, and the red steps of Tasks 3 and 5
  reproduce.

### How this was checked

**Reading.**
- The round-1 → round-2 diff (`critic3/r1_r2.diff`, 943 lines) line by line.
- In context: `ops_core.lease` (whole); `_lock_row`, `acquire_lease`, `claim_next`, `fenced`, `release_lease`;
  `handlers` (whole, as Tasks 3/4/5 leave it); `main` (Task 3, and Task 5's edits); `heartbeat` (whole); `permit`;
  revision 0007's `MARK_UNKNOWN` and `_resolve_handle`; mcp-write's post-SENT path; the sweeper's `reclaim`; the
  stress module (whole); the DoD-3 live module; the `built_to_0006` fixture.
- Against the repository: `persistence.connect` (autocommit), `Postgres.conninfo` (`options="-c timezone=UTC"`),
  `app.current_time()` (`clock_timestamp()` + offset), `states.ACTIVE_STATES`, `jobs.JOB_RULES`,
  `transition_run`'s rows, today's `handlers.py`.

**Applying the plan.** The round-2 tooling was copied to `critic3/tools`, with the twelve inline replace-all anchors
remapped to the new plan lines through difflib. The driver then ran on a fresh `git archive HEAD`, once per task:
1. apply the task;
2. `ruff format --diff`, then `ruff format`;
3. `ruff check`, mypy strict over the eight member trees (as `scripts/check.py` does), and the dev pytest.

| After task | splices | `ruff format` rewrote | ruff | mypy | pytest dev (+12 env failures) |
|---|---|---|---|---|---|
| 1 | all, once | nothing | clean | clean, 49 | **857** / 104 |
| 2 | all, once | nothing | clean | clean, 49 | **863** / 109 |
| 3 | all, once | nothing | clean | clean, 50 | **881** / 119 |
| 4 | all; replace-all counts 1/3/1/2/3/2 | `test_definers_write_path_live.py` (declared) | clean | clean, 50 | **888** / 124 |
| 5 | all, once | nothing | clean | clean, 52 | **907** / 128 |
| 6 | all, once | nothing | clean | clean, 53 | **912** / 132 |
| 7 | all, once | `api/.../app.py`: two blank lines from *my* tool's "insert before" (artifact) | clean | clean, 53 | **928** / 133 |

Notes on the table:
- Every count equals the plan's Task overview (857/104 … 928/133).
- The 12 failures are the archive copy's (no `.git`, no reference zip), as in rounds 1-2.
- All inline replace-all counts match the plan's stated counts.

**Red steps** (`tools/red.py`):
- Task 3 S1: `3 errors in` (`No module named 'ops_core.lease'`). The new N2 test sits in a module that fails at
  collection, as the plan expects.
- Task 5 S1: `2 errors in`.

**Repeat runs.** The four changed unit modules (`test_lease` 12, `test_heartbeat` 10, `test_permit` 6,
`test_worker_units` 11, 39 tests) ran 10/10 green on Windows, 2.0-2.4 s each. That includes the new
`test_a_held_row_after_the_first_insert_is_busy_too`, `test_the_settings_margin_is_the_deadline_margin_plus_one_tick`
and the `QueryCanceled` retry.

**New lines over 120 characters.** None in the diff's added lines.

**Not run.** No live test, no database. DB behaviour is judged statically.

---

### 1. Round 2 verification

| Finding | Status | Evidence |
|---|---|---|
| **N1** DoD-3 lower bound flaky | **FIXED** | 7270-7275: `BLOCK_SECONDS - TICK_SECONDS - STAMP_SECONDS < max_loop_age < loop_stall_seconds`, constants imported (7149), with a comment. Re-derived: ticks are ≥ 1 s + tick time apart, so the last tick in the block is at ≥ b0 + 24 − d (d = tick duration; no renewal falls in the last second of the block). The last stamp is < b0, so age > 24 − d > 23. The upper bound is unchanged (≈ 26). The self-review risk text (9827-9831) matches. |
| **N2** second-lock 55P03 escapes | **FIXED** | `_lock_row` (2740-2749) wraps both lock statements (2787, 2791). The new unit test (Task 3 S1) passes, and the raise with `wait=True` is checked. The dead stress branch is gone (8074). Savepoint state: details under section 2. |
| **N3** vacuous two-owner monitor | **FIXED** | `believers` (8177-8184) and `monitor` (8186-8207): beliefs are taken synchronously, then the rows are read. A violation is more than one believer, or a believer that is not the owner of a live row at fence F or F+1. Soundness is analysed in section 2. The docstring, evidence line, ruling 21 (229-231), R107 note and acceptance row now say exactly that. |
| **m1** unbounded unit lock wait | **FIXED** | `LOOP_LOCK_TIMEOUT` (3302-3303), run once after `persistence.connect` (3396). The connection is autocommit, so the SET is session-wide and opens no transaction. Runbook paragraph at 9561-9565, open point at 10057-10060. Consequences are in section 2; the "hands the job back" part runs into **I1**. |
| **m2** shutdown stops the stamps early | **FIXED** | `stamps_stop` (7083/7085); `gather(serving, polling)`, then `stamps_stop.set(); await stamping`, then `heartbeat.stop()` (7100-7106). Risk text corrected (9822-9826). |
| **m3** heartbeat connection bounds | **FIXED as ruled** | `connect_timeout=5`, keepalives 10/5/2, then `SET lock_timeout` and `SET statement_timeout` to 5 s (6652-6665). No `options` kwarg is passed, so the conninfo's `-c timezone=UTC` stands (passing `options=` would have replaced it). `QueryCanceled` is a `psycopg.Error`, so a timeout is transient. The test now scripts it (6096-6097). Two overstatements remain: **m-c**. |
| **m4** duplicated margin | **FIXED** | `test_the_settings_margin_is_the_deadline_margin_plus_one_tick` (6030-6032) passes (6 == 5.0 + 1.0). |
| **m5** 141-character README line | **FIXED** | 9690-9694 rewrapped; every added line is ≤ 120. |
| **m6** stray scratch database | **FIXED** | `SCRATCH_PREFIX`/`LEFTOVERS` (5571-5572). The sweep and the create are inside the `try` (5593-5599), and `finally` does `DROP … IF EXISTS … WITH (FORCE)`. `LIKE 'r006\_%'` is correct under `standard_conforming_strings` (backslash is LIKE's default escape). With no parameters, psycopg 3 does not parse `%`. `fetchall()` materialises the list before the drops run. Residual concurrency note: **m-d**. |
| **Line cites** | **FIXED** | Spot-checked at HEAD: privileges 157-159, test_migrations_and_persistence 149-158, test_mcp_write_live 85-89, execution.py 29-31, test_definers_write_path_live 463-473, drafting.py 9-13/56-62. All are exact. The later-task cites ("as Task 3/6 left it") splice by text, and the drive found every splice once. |
| **PROJECT_HISTORY paragraph** | **FIXED** (nit) | 9645-9654: it covers the round-1 INTRANS cancellation, the flaky bound, the NOWAIT regression and the vacuous check, and is accurate. It is four sentences against the ruled "two or three" (one of them a long semicolon chain). Cosmetic. |
| **Counts** | **FIXED** | Overview 433-450, the arithmetic, every Step `Expected`, the Task 8 tails and Round 2 changes' table agree with the measured run above. |

---

### 2. New-defect hunt on the round-2 changes

**`_lock_row` and the savepoint (sound).**
- In `claim_next`, `acquire_lease`'s `conn.transaction()` is a SAVEPOINT inside the claim's BEGIN.
- A 55P03 from either lock statement leaves the transaction in error. `_Locked` (raised `from None`) leaves the
  `async with`. psycopg's nested exit runs `ROLLBACK TO SAVEPOINT` and then `RELEASE`, so the outer transaction is
  usable again. The deferral UPDATE on the already-locked job row then commits.
- With `wait=True`, the 55P03 propagates through the same savepoint rollback, then through the caller's transaction.
- The second statement can only meet a held row in the DO NOTHING case: its own fresh insert is invisible to others,
  and their INSERTs wait on it. That case now defers the job for one second.
- The INSERT's own wait (the concurrent first insert) is not NOWAIT. On the loop connection it is now bounded by the
  10 s `lock_timeout` and raises, as the `Raises:` section says.

**The N3 monitor (sound; one tightening possible, m-a).** A false positive needs a believer whose row is not
(owner = it, live, fence ∈ {F, F+1}) at the instant the row is read.
1. **Expiry.** The row's expiry is `clock_timestamp()` (+ a constant offset) at the TAKE/RENEW statement, plus L.
   The believer's deadline is a monotonic instant taken before that statement, plus L − 5:
   - for a waiting acquisition, before up to 10 s of lock wait;
   - for a renewal, before `to_thread`;
   - for a claim, after `pick_job`.
   So the row stays live for at least 5 s after the belief ends.
2. **Who can change the row.** Only three statements touch it:
   - `_TAKE_LEASE`, which needs the row not live;
   - `RENEW`, which needs owner = self;
   - `mark_unknown`, which needs fence = p_fence, live. Fences are unique, so that is only the believer, and it moves
     the fence by exactly 1.

   Reclaim touches `jobs` only, and the stress mix has no release.
3. **Timing of the reads.** The beliefs are computed synchronously between actor steps, so no acquisition is
   half-recorded. The SELECT is sent at once, so two bumps by one actor cannot both commit in between.
4. **Resurrection.** A stale actor's `renew` that succeeds (its row was still live) resurrects its belief. That
   agrees with the row, so it is not a violation.
5. **Clock offset.** A constant leftover test-clock offset cancels out. Only a mid-test move or a host/VM clock jump
   of more than 5 s could fire it, and that error is loud, never silent (as the open point says).

The fence-equality assertion and the "never backwards" check are kept.

**The loop's `lock_timeout` (sound for safety; see I1 for liveness).**
- **Production units that wait.** Only these do:
  - the fenced FOR SHARE, behind a renewal: bounded by the heartbeat's 5 s timeouts;
  - `release_lease`'s FOR UPDATE, behind a renewal or a peer's NOWAIT claim: milliseconds;
  - `run_row(lock=True)` and `freeze_proposal`'s `runs` lock, behind API units: short, and the API has a 2 s
    `lock_timeout` on its reply unit;
  - the claim's first-row INSERT.

  No production unit legitimately waits 10 s.
- **Tests.** No test relies on a longer wait: the interleaving tests use their own `role_conn`, never `_main`'s
  connection.
- **Renewal margin.** A unit that waits ≤ 10 s while holding FOR SHARE blocks renewals for at most that long. With
  one heartbeat (10 s) before it, the 25 s local deadline still holds.
- **Path by path, a 55P03:**
  - claim unit → rolled back, logged transient, next poll;
  - fenced handler unit → propagates past `run_job`, whose `finally` now drops the lease from the heartbeat → lease
    lapses → reclaim;
  - `release_lease` → same; the re-run finds the run already advanced and closes the job;
  - `_mark_unknown` → `end_refence(None)`, re-raised; the reclaimed execute job resends under the same action id
    (attempt SENT → "resend"), which is idempotent;
  - drafting/freezing → `_fail` → FAILED.
- **Is the drafting/freezing behaviour a regression?** It is the same `except Exception` rule as today's HEAD
  (`handlers.py:111`), where a 40P01 already fails the run. The spec says nothing about database lock timeouts
  (BS:562 is about read retries). Accepting it as the open point does is reasonable.
- **The weakness is the other half.** The non-drafting paths "hand the job back", and for an investigate run that
  is not QUEUED, that hand-back does nothing: **I1**.

**Heartbeat connection (sound).**
- `make_conninfo` merges the keepalive and `connect_timeout` kwargs. The SETs avoid replacing `options`.
- Equal 5 s `lock_timeout` and `statement_timeout` just race to the same transient outcome (55P03 or 57014). The
  renewal's single wait cannot outlast either, and the tick can block at most about 5 s.
- `self._connection()` is evaluated inside the tick's `try`, so a connect or SET failure is transient too.
- Two overstatements remain, **m-c**, plus the connection a failed SET leaves open, **m-e**.

**Stamps and shutdown order (sound).**
- `stop` ends the poll loop after its job, and `stamps_stop` keeps the stall gate fed until then.
- The heartbeat keeps renewing, because `run_job`'s `finally` drops the lease only when the job ends. The compute
  budget (90 s) still bounds a job a shutdown waits for.
- If a second interrupt cancels the main task inside the `gather`, the rest of the `finally` is skipped. The stamp
  task is then cancelled by `asyncio.run`, and the daemon heartbeat dies with the process.

**The scratch-database sweep.** It can drop a concurrent session's scratch database: **m-d**.

---

### 3. Fresh end-to-end pass

**No deadlock under the published order (holds).**
- **Claim.** Locks the job (SKIP LOCKED), then the lease with NOWAIT, so it never waits while holding the job, except
  in the first-row INSERT race. There the other party is a claim that holds a different job and no lease.
- **`release_lease`.** run_lease FOR UPDATE → handles → jobs. The job it wants can be held only by a claimer that
  will not wait on the lease (NOWAIT), or by the sweeper's reclaim, which takes no lease lock.
- **`mark_unknown`.** run_lease FOR UPDATE from the start → runs → handles → jobs. The worker's `_mark_unknown`
  deliberately takes no FOR SHARE first (5197-5199), so no share-to-update upgrade exists anywhere. That is the
  classic deadlock this order rules out, and only the owner could attempt it.
- **mcp-write.** `_resolve_handle`'s FOR SHARE → runs. It never upgrades.
- **The stress test's waiting acquisition.** It holds nothing before its wait.
- None of this changed in round 2.

**The fence makes every stale write fail (holds).**
- **Worker side:**
  - every writing unit opens with `fenced` (FOR SHARE, then owner/fence/live compared after the lock);
  - `mint_handle` inserts only at a live lease with an exact fence;
  - `release_lease` compares owner and fence under FOR UPDATE. It skips liveness, but the lock blocks any takeover,
    so nothing it writes lands after a newer fence;
  - `abandon` only revokes (never refused) and un-claims `WHERE claimed_by = me`.
- **mcp-write side.** `_resolve_handle` takes FOR SHARE, then checks the handle's fence and the lease's liveness, and
  refuses OC008. That covers `grant_execution`, `mark_sent` and `record_outcome`.
- **Post-SENT.** A moved or lapsed fence makes `record_outcome` raise `HandleRejected`, a `PersistenceError` in
  `_POST_SENT_REFUSALS`, so the call answers UNKNOWN, never "no effect". The worker's `_mark_unknown` then needs a
  live fence of its own:
  - a stale worker gets LeaseLost and abandons;
  - the current owner's bump moves the fence, revokes the older handles and transitions to OUTCOME_UNKNOWN with a
    `recover` job.

**Cancellation never interrupts a database unit (holds).** Only `Lease.effect` tasks are ever cancelled:
- the MCP call: HTTP plus a token fetch, no database;
- the model call;
- the permit's back-off sleep.

The permit's take and release, every fenced unit and `abandon` run on the handler's own task. Shutdown cancels
nothing. The only `wait_for` around a database task is in failing-test paths (4009, 4099, 4126, 7324).

---

### Blocking

None.

---

### Important

**I1 — A handed-back `investigate` job whose run is RETRIEVING or DRAFTING closes without doing anything, and the
run stays in that active state for good. The plan describes the opposite.**

Where:
- Task 3 Step 4, `investigate` (plan 3076-3082): `if run["state"] != QUEUED: log.info("… run already %s"); return`.
- `handle` then runs `release_lease`, which finishes the job (3243).
- The claims that contradict this are the comment at 3123-3124, erratum 57 (392-395), ruling 19's "the next owner
  re-reads the run", and the m1 runbook paragraph (9561-9565).

Evidence:
- `JOB_RULES[INVESTIGATE].run_states` is {QUEUED, RETRIEVING, DRAFTING} (`core/src/ops_core/jobs.py:73`), so the spec
  expects an investigate job to resume from those states.
- RETRIEVING and DRAFTING are in `ACTIVE_STATES` (`states.py:211-222`), so a run left there holds its conversation
  slot.
- Every T13 hand-back after the first unit therefore ends the same way:
  - a lease lost during retrieval or drafting (`abandon`);
  - a crash, or round 2's new 55P03, reclaimed by the sweeper.
- In each case the next claimer takes the job at fence + 1, logs "run already RETRIEVING", and closes it.
- The run then has no job, no lease holder and no way forward except a user cancel.
- The plan's own live test shows the first half: `test_r088_a_forced_renewal_failure…` (7334-7337) asserts the job is
  handed back with the run in RETRIEVING. No test runs the job again.
- The new drafting comment says the reverse: "the sweeper reclaimed the job and the next attempt met the same
  failure". The next attempt meets nothing.

Why it matters:
- It is the liveness half of R019 and SA:196-198. Fencing is safe throughout.
- But "exits the run … the next owner re-reads the run" is advertised as recovery, and it turns every lease loss
  mid-investigation into a permanently stuck conversation.
- This is older than round 2 (it was in 03e2636), and all three earlier reviews missed it. Round 2's m1 adds one more
  trigger and documents the hand-back as recovery.

Fix (smallest first; the controller picks):
- (a) Declare it and stop claiming otherwise:
  - add a debt line: "a handed-back or reclaimed investigate job whose run is already RETRIEVING or DRAFTING is closed
    without work, leaving the run active until cancelled; resuming from the checkpoint is `load_run` → T20";
  - correct the 3123-3124 comment, erratum 57's last clause and the m1 runbook paragraph.
- (b) Or keep the run moving with one legal transition:
  - when `investigate` finds RETRIEVING or DRAFTING (a hand-back), fail the run through `transition_run` →
    FAILED, which is legal from both (`states.py:155-156`), in the same fenced unit, with the message "investigation
    handed back mid-run; resume is T20";
  - add one unit test with the fakes: state DRAFTING in, `transition_run(DRAFTING→FAILED)` out, then
    `release_lease`.

  (b) frees the slot, and is consistent with the existing "a failure in drafting fails the run" rule.

---

### Minor

**m-a — The monitor's F+1 allowance would also hide a re-fence that never reaches the Lease.**

Where: the monitor condition at 8205.

Evidence:
- If `end_refence` were not called, the actor would keep believing F while the row says F+1. Every sample would pass,
  and the actor's next `write` would only count as `lost`.
- The I4 sentence "its holder hands the new fence to its Lease" is therefore asserted by nothing under load. It is
  covered only by `test_lease`.

Fix: record `held.refencing` in `believers`, and allow `fence == held_fence + 1` only for a believer that was
re-fencing at the snapshot.

**m-b — Ruling texts drifted from the round-2 changes.**

Evidence:
- Ruling 16 (203-205) still describes the heartbeat connection as only `SET lock_timeout = '5s'`. It lacks
  `connect_timeout`, the keepalives and `statement_timeout`.
- Ruling 19 and the Global Constraints do not mention the loop connection's 10 s `lock_timeout`, the one bound on a
  unit now that units are never cancelled.

Fix: one clause in each.

**m-c — `connector`'s docstring overstates what the keepalives cover (6646-6649).**

Evidence:
- `keepalives_count` has no effect on Windows (libpq), where the probe count is fixed at 10. The dev worker therefore
  notices a half-open connection after about 60 s, not about 20.
- TCP keepalive does not run while sent data is still unacknowledged, and `statement_timeout` is enforced by the
  server, so neither bounds a renewal sent into a connection whose peer has vanished.
- Safety is unaffected (fence, handle cap, and the loop's own `check()`).

Fix: say "about 20 s on Linux (about 60 s on Windows, where the probe count is fixed); a request lost on a vanished
peer is bounded by TCP retransmission, not by these settings". Alternatively add `tcp_user_timeout=10000`, which libpq
honours on Linux.

**m-d — The leftover sweep's `DROP … WITH (FORCE)` can kill a concurrent session's scratch database mid-upgrade.**

Where: 5594-5596.

Evidence: two live sessions against one cluster, each running `test_migration_0007_live.py`. Such sessions already
clobber each other through `recreate_databases`, so this is low.

Fix:
- Drop only leftovers with no backend:
  `… AND NOT EXISTS (SELECT 1 FROM pg_stat_activity a WHERE a.datname = d.datname)`, with `IF EXISTS` and no FORCE.
- Derive `LEFTOVERS`' pattern from `SCRATCH_PREFIX` instead of repeating `r006`.

**m-e — `connector()` leaks the connection when a SET fails after a successful connect (6652-6665).**

Evidence: the tick treats the failure as transient and the next tick opens another connection. The unreferenced one
is closed only by garbage collection.

Fix: wrap the SETs in `try: … except BaseException: conn.close(); raise`.

**m-f — Cosmetic.**
- `acquire_lease`'s docstring still breaks "`lease_until <=`" onto a line of its own (2765-2767; round-1 residue).
- The PROJECT_HISTORY round-2 paragraph is four sentences against the ruled two or three.

---

### Checked and found sound (round-2 changes)

- **`SecondLockHeld`.** The `asynccontextmanager` re-raises `_Locked` and `LockNotAvailable` unchanged. The
  `startswith("INSERT")` test matches only `_CREATE_LEASE`. `conn.locks == 2` proves the second statement went through
  `_lock_row`.
- **`LOOP_LOCK_TIMEOUT`.** A plain module constant passed to `execute`. mypy is clean, and the connection is
  autocommit, so no transaction is left open.
- **`believers`/`monitor`.** Use only the event loop's own state and `app_conn`. `app_conn` is otherwise unused during
  the `gather`.
- **Stress counting.** The removed `Busy(locked=True)` branch cannot recur: `wait=True` never returns it.
- **`built_to_0006`.** The sweep and the create run as superuser inside the `try`. A failing CREATE leaves nothing,
  because `finally` uses `IF EXISTS`.
- **Shutdown text.** It matches the code: shutdown cancels nothing, and only an interpreter-level interrupt cancels the
  main task.


## Builder dry run

# Plan H dry run, round 3 (builder report)

Plan: `docs/superpowers/plans/2026-10-15-first-slice-h-leases-fences-heartbeat.md` at `plan-h` 6ca01b3 ("Plan H
round 2 fixes"). Worktree: `<scratch>/planh/dryrun3`, detached at 6ca01b3, `uv sync --locked`; removed at the end
(`git worktree remove --force`, `git worktree prune`). Date: 2026-10-15.

Method (as rounds 1 and 2): a helper copied every fenced block from the plan byte for byte (by plan line number) and
refused any splice whose old text was not found exactly once; every inline replace-all was counted before it was
applied and compared with the plan's count; every "Modify" line cite was checked against the file as the previous
task left it (`git show HEAD:<path>` before the task's edits). After every task: `ruff format` + `ruff check --fix` on
the task's files, the 120-character count, then `ruff format --check .` over the tree. Scripts the plan gives in Task 8
(the handoff-records script, the README script) were extracted from the plan and run unchanged through
`uv run python -`.

Scope: dev gates only. Every `OPS_LIVE=1` step is **SKIPPED (live, out of scope)**: no `.env` was copied, linked or
recreated or otherwise reached, no database or container was touched. The edits of every live step were applied, and
each live module set was collected without `OPS_LIVE` (`--collect-only -q`) to compare with the plan's live count.

## Summary

- Steps: 47 (the plan's 47 checkboxes).
  - OK: 41, of which 8 are OK* (mixed steps: the dev half matched, the live half SKIPPED).
  - DIFFERS: 0.
  - WORKAROUND: 0.
  - SKIPPED (live only): 6 (T2 S6, T3 S6, T3 S7, T4 S5, T5 S3, T6 S3); every edit in them applied cleanly.
- Every splice found its old text exactly once. Replace-all counts matched the plan: Task 3 3/5/1/6, grep `0`;
  Task 4 3/1/2/3 (write path) and 2 (worker live), grep `0`.
- Every red step failed with the count and the reason the plan states (details per task).
- Every dev gate equalled the plan's numbers: 816/104 → 857/104 → 863/109 → 881/119 → 888/124 → 907/128 →
  912/132 → 928/133 → 928/133; mypy clean; `verify_handoff` exit 0 after every task and on the final tree.
- Every "Modify" line cite in the step bodies matched the tree (all round-2 cite nits are fixed). Two Files-header
  ranges are a line off (Observation 1).
- Flake runs: no flake in 25 runs (Section "Flake runs").

Scratch commits (thrown away with the worktree):

| Commit | Content |
|---|---|
| 0f402e1 | debt list |
| 78141a9 | T1 |
| c9bf945 | T2 |
| c2f2b38 | T3 |
| 2a8c0c6 | T4 |
| df8c719 | T5 |
| a083423 | T6 |
| bbd2c4d | T7 |
| 3f46a76 | T8 |

BASE=6ca01b3 (recorded in the ignored SDD ledger); Task 8's script printed `6ca01b3..bbd2c4d`.

## Gates: observed vs expected

| When | Dev `check.py` observed (pytest time) | Dev expected | mypy | `verify_handoff` | `ruff format --check .` | Live |
|---|---|---|---|---|---|---|
| T1 S1a baseline | 816 passed, 104 skipped, GREEN (40.52 s) | 816/104 | 48 files clean | — | — | SKIPPED (exp 899/21) |
| T1 S7 | 857/104 GREEN (35.06 s) | 857/104 | 49 clean | exit 0 | 217 formatted | not required |
| T2 S7 | 863/109 GREEN (35.26 s) | 863/109 | 49 clean | exit 0 | 220 | SKIPPED (exp 951/21) |
| T3 S8 | 881/119 GREEN (37.32 s) | 881/119 | 50 clean | exit 0 | 224 | SKIPPED (exp 979/21) |
| T4 S6 | 888/124 GREEN (37.47 s) | 888/124 | 50 clean | exit 0 | 226 | SKIPPED (exp 991/21) |
| T5 S4 | 907/128 GREEN (38.19 s) | 907/128 | 52 clean | exit 0 | 231 | SKIPPED (exp 1014/21) |
| T6 S4 | 912/132 GREEN (36.77 s) | 912/132 | 53 clean | exit 0 | 235 | SKIPPED (exp 1023/21) |
| T7 S3 | 928/133 GREEN (38.62 s) | 928/133 | 53 clean | exit 0 | 238 | SKIPPED (exp 1040/21) |
| T8 S5 | 928/133 GREEN (39.76 s) | 928/133 | 53 clean | exit 0 (also after the T8 commit) | 238 | SKIPPED (exp 1040/21) |

`ruff check` was "All checks passed!" in every gate.

Live modules collected without `OPS_LIVE` (each equals the plan's expected live pass count):

| Step | Modules | Collected | Plan's expected live result |
|---|---|---|---|
| T2 S6 | 0007, roles, persistence, 0006 | 22 | `22 passed` |
| T3 S6 | worker, persistence, mcp-read, mcp-write | 18 | `18 passed` |
| T3 S7 | leases | 10 | `10 passed` |
| T4 S5 | the seven modules | 49 | `49 passed` |
| T5 S3 | heartbeat, worker, leases | 18 | `18 passed` |
| T6 S3 | stress, admission, sweeper | 14 | `14 passed` |
| T7 S3 | admission, incident-sim | 13 | `13 passed` |

`pytest tests/e2e/test_heartbeat_live.py -m "not slow_live"` → `1 skipped, 3 deselected` (the marker is registered and
the three DoD tests carry it).

Unit runs:

| Step | Command (abridged) | Observed | Expected |
|---|---|---|---|
| T1 S3 | settings_leases | `1 error in`, ImportError `LeaseSettings` | same |
| T1 S4 | settings_leases + plan_g admission settings | 16 passed | 16 |
| T1 S5 | locking | `1 error in`, ImportError `locking` | same |
| T1 S6 | locking | 30 passed | 30 |
| T2 S1 | 0007 + transitions | `1 error in` (module-level assert on `REVISIONS`) | same |
| T2 S2 | same | 5 failed, 12 passed: KeyError `model_permit`; `AssertionError: run_lease`; KeyError `queued_runs_total is not a known definer function or helper` ×2; AttributeError `TEST_ONLY_ROLES_TC` | same |
| T2 S4 | 0007, transitions, privileges, locking | 53 passed | 53 |
| T3 S1 | lease, worker_units, grant_deferred | `3 errors in`, ModuleNotFoundError `ops_core.lease` ×3 | same |
| T3 S4 | + rotate, plan_d worker | 43 passed | 43 (lease 12, units 6, F 3, rotate 17, D 5) |
| T4 S1 | 0007, worker_units, write_path_fence | 11 failed, 7 passed: `ValueError: 'DROP FUNCTION app.mark_sent(uuid)' is not in list`; AttributeError `MARK_UNKNOWN`; AssertionError on the downgrade's first statements; six × AttributeError `Unknown`; two × TypeError (positional action id) | same |
| T4 S3 | plan_h, transitions, privileges, grant_deferred | 92 passed | 92 |
| T5 S1 (a) | heartbeat + permit | `2 errors in` (ImportError `Renewal`; ModuleNotFoundError `ops_worker.permit`) | same |
| T5 S1 (b) | worker_units | 8 failed, 3 passed, each AttributeError `take_model_permit` (the deferral, abandon and real-MCP tests pass) | same |
| T5 S2 | plan_h, plan_d worker, grant_deferred | 98 passed | 98 |
| T6 S1 | reclaim / global_queue | `1 error in` (ImportError `leases`) / 3 failed, TypeError `queue_limit` | same |
| T6 S2 | reclaim, global_queue, plan_g, plan_f sweeper | 149 passed | 149 |
| T7 S1 | faults_t13 / incident-sim + api faults | `1 error in` (ImportError `BS405`) / 10 failed, 2 passed (incident-sim: 422 on arming or unchanged hot path; API: TypeError `create_app() … 'faults'`) | same |
| T7 S2 | plan_h, plan_g, plan_e faults/sim, plan_d sim/api, plan_f | 423 passed (plan_h alone 111, plan_f alone 147) | 423 |

## Flake runs (unit level, final tree after the Task 8 commit)

Each module 5 times on its own, then the four together 5 times (`-p no:cacheprovider`). No flake:

| Module | Result, every run | Time per run |
|---|---|---|
| `tests/plan_h/test_heartbeat.py` | 10 passed | 0.36-0.37 s |
| `tests/plan_h/test_lease.py` | 12 passed | 0.50-0.53 s |
| `tests/plan_h/test_permit.py` | 6 passed | 0.69-0.75 s |
| `tests/plan_h/test_worker_units.py` | 11 passed | 1.64-1.68 s |
| the four together | 39 passed | 2.00-2.11 s |

The heartbeat module includes the new `test_the_settings_margin_is_the_deadline_margin_plus_one_tick` and the real
thread test (`call_soon_threadsafe` across threads under `asyncio.run` on Windows); the lease module includes the new
`test_a_held_row_after_the_first_insert_is_busy_too`; the worker-units module includes
`test_a_lost_lease_cancels_a_real_mcp_call` (the real `HttpMcpCaller` against a silent local server).

## Task 1

| Step | Status | Note |
|---|---|---|
| 1a | OK* | dev 816/104 GREEN; live SKIPPED |
| 1b | OK | BASE=6ca01b3 written to the ignored ledger |
| 1c | OK | debt section inserted after the Plan G debt list, before `## Environment (observed)`; committed |
| 2 | OK | both `pyproject.toml` splices once (cites 48-51, 56-58 exact) |
| 3 | OK | `1 error in`, ImportError `LeaseSettings` |
| 4 | OK | three splices once (cites 293, 304-310, 313-314 exact); 16 passed |
| 5 | OK | `1 error in`, ImportError `locking` |
| 6 | OK | 30 passed |
| 7 | OK | format left 4 files unchanged; lint clean; no line over 120; 857/104 GREEN; vh 0 |

## Task 2

| Step | Status | Note |
|---|---|---|
| 1 | OK | `1 error in` |
| 2 | OK | ISC004 pass changed nothing; 5 failed, 12 passed, reasons as stated |
| 3 | OK | 5 splices once; privileges cites 7-15, 107-111, 157-159, 182-183 exact |
| 4 | OK | both tc_0001 splices once (20-25, 43-55 exact); 53 passed |
| 5 | OK | conftest 143 and roles 222-223 exact, once each |
| 6 | SKIPPED (live) | file written; collects 22 |
| 7 | OK* | format left 9 files unchanged; 863/109 GREEN; vh 0; live SKIPPED |

## Task 3

| Step | Status | Note |
|---|---|---|
| 1 | OK | `3 errors in` |
| 2 | OK | `lease.py` written |
| 3 | OK | 7 persistence splices once (8, 13-31, 139, 282-285, 538-559, 567-568, 613-623 exact) |
| 4 | OK | handlers/main replaced; 43 passed; format left 28 files unchanged |
| 5 | OK | conftest and evidence splices once (9-20, 5-6, 17-23 exact) |
| 6 | SKIPPED (live) | every edit applied; replace-all 3/5/1/6; grep `0`; all cites exact (worker 15-24, 103-113; persistence 149-158, 172-174, 399-403; mcp-read 43-48; mcp-write 85-89; r105 25-26, 209-214); collects 18; `ruff check --select F` clean |
| 7 | SKIPPED (live) | file written; collects 10 |
| 8 | OK* | format left 15 files unchanged; 881/119 GREEN; vh 0; live SKIPPED |

## Task 4

| Step | Status | Note |
|---|---|---|
| 1 | OK | 11 failed, 7 passed, each reason as stated |
| 2 | OK | revision Edits 1-5 once; ISC004 changed nothing; layout as the plan describes (bodies between `QUEUED_RUNS_TOTAL` and the four tuples); privileges edit once |
| 3 | OK | 8 splices once (execution 29-31, 88, 117; server 223-225 exact); 92 passed |
| 4 | OK | every splice once; cites exact (write path 100-113, 364-366, 407-408, 463-473, 496-505, 549-555, 632-642; mcp-write 279); replace-all 3/1/2/3 and 2; grep `0`; `ruff check --select F` clean; `new_handle`, `stale_handle`, `cancelled_handle`, `handle` all bound |
| 5 | SKIPPED (live) | file written; collects 49 |
| 6 | OK* | format reformatted 1 file: Edit 12's three lines in `test_definers_write_path_live.py`, exactly as the plan predicts; 888/124 GREEN; vh 0; live SKIPPED |

## Task 5

| Step | Status | Note |
|---|---|---|
| 1 | OK | `2 errors in`, then 8 failed, 3 passed, as stated |
| 2 | OK | all splices once (drafting 9-13, 56-62 exact now); `take_model_permit`/`release_model_permit` inserted after `unclaim_job`, before `finish_job`; 98 passed |
| 3 | SKIPPED (live) | file written; collects 18; `-m "not slow_live"` → 3 deselected |
| 4 | OK* | format left 11 files unchanged; ruff and mypy (52 files) clean; 907/128 GREEN; vh 0; live SKIPPED |

## Task 6

| Step | Status | Note |
|---|---|---|
| 1 | OK | `1 error in`; 3 failed with the stated TypeError |
| 2 | OK | every splice once; cites exact (sweeper 8-10, 37, 111-117; idempotency 49-50; store 268-270, 386-388, 423-424, 671-673, 818-820, 922; fakes 111-113, 278); `queued_runs_total` inserted after `queued_count`; 149 passed |
| 3 | SKIPPED (live) | stress file written; admission edit (line 55) once and the append; helpers exist (`count`, `api`, `messages`, `conversation`, `h`, `SAMPLE`, `created`, `new_run(conn, tenant, api=)`, `Role.TEST_HARNESS`); `ruff check --select F` clean; collects 14 |
| 4 | OK* | format left 11 files unchanged; 912/132 GREEN; vh 0; live SKIPPED |

## Task 7

| Step | Status | Note |
|---|---|---|
| 1 | OK | `1 error in` (`BS405`); 10 failed, 2 passed, as stated |
| 2 | OK | faults.py replaced; incident-sim 7 splices once (5-6, 90-94, 98, 185-187, 210-216, 244-245, 254-256 exact); store 3 splices once (351, 357-362, 1016-1017 exact now); app 6 splices plus the `API_FAULTS` insert (`def create_app(` found once); test_api_admission 22-23, 187-189 exact; admission live 3 splices and the append; 423 passed |
| 3 | OK* | format left 9 files unchanged; live run SKIPPED (collects 13); 928/133 GREEN; vh 0 |

## Task 8

| Step | Status | Note |
|---|---|---|
| 1 | OK | `git grep` printed nothing; `grep -c` printed `1` (line 176, `GRANT_TODO_0005`) |
| 2 | OK | printed `6ca01b3..bbd2c4d`; `git diff --stat handoff` 3 files; a JSON comparison shows only `requirements` changed, exactly R015, R019, R020, R087, R088, R098, R107; BACKLOG note appended last under T13 |
| 3 | OK | `**Next task:**` is one line, replaced; the Plan H section inserted before `## Walking-skeleton debt list` with the two execution bullets as "none"; the dev-database paragraph appended before `## Open owner inputs`; the owner-input bullet and the repository fragment each found once. The "T15 also became unblocked" claim checks out: T14 (T13, T12) and T15 (T13, T05) have every dependency DONE |
| 4 | OK | STATUS appended; runbook created; ARCHITECTURE anchor once; no "The leases plan" section existed, so section 25 was inserted before `## 25. What the process taught`, renumbered 26, and "Execution found nothing the plan had not ruled on." appended; README script exit 0; worker README "Runs" replaced (every line ≤ 120 now); sweeper's three blocks found once |
| 5 | OK* | 928/133 GREEN; vh 0; live SKIPPED, so `<live passed>` stays unfillable (filled with a note in the scratch copy); 47 checkboxes ticked |
| 6 | OK | adds succeeded; the conditional printed `reports/leases missing: rerun Step 5` (expected without a live run); commit made |

## Observations (no workaround needed; cosmetic)

1. **Two Files-header ranges a line off** (the step bodies' own cites are exact):
   - Task 3 Files line: `tests/e2e/test_migrations_and_persistence.py … :398-403`; the edit (Step 6 Edit 4, cited 399-403)
     is lines 399-403.
   - Task 7 Files line: `tests/plan_g/test_api_admission.py:22-27`; Edit 1 is lines 22-23 (cited 22-23 in the step).
2. **SESSION_STATE.md, one new line of 122 characters** (Task 8 Step 3 block, plan line 9432: "  enforced (the
   api-only `resume_input` restriction → T22); bounded retries and the transport path → T22; wake-ups and"). Not a
   gate (SESSION_STATE.md already has far longer lines, e.g. the repository line at 786), but the rest of the block
   keeps within 120; rewrapping before "wake-ups" would fix it.
3. **PROJECT_HISTORY section 25** narrates rounds 1 and 2; a round-3 paragraph is due from the controller if this
   round changes the plan (the plan says later rounds add their own paragraph before execution).
4. **`append:` instructions** still give no separator; each block was appended after two blank lines (ruff format
   would normalise either way; every task's files were left unchanged by `ruff format`).

Round-2 observations re-checked: all nine round-2 line-cite nits are fixed (privileges Edit 3, persistence Edit 2,
mcp-write Edit 2, execution Edit 1, write-path Edit 8, mcp-write docstring, both drafting cites, store Edits 1-3),
and the worker README's 141-character line is gone.

## Workarounds

None for the plan. One tooling note, not a plan issue: my own splice helper's progress `print` crashed under the
console's cp1252 encoding on a "→" in Task 8 Step 3 after its first write; I restored `SESSION_STATE.md` from the
scratch commit, set `PYTHONUTF8=1` for the helper, and re-ran the step from the start. The plan text and its
commands were not changed.

## Not verified (needs the live run)

Unchanged from round 2: the 0007 round trip (`prosrc`, and the `built_to_0006` scratch-database comparison with the
new `r006_` prefix and leftover cleanup); the interleavings and their sub-second / 2.5 s timings; the stepped
two-first-claims test; the 20 s stress test with the new belief-vs-row monitor (DoD 2; no 3× repeat possible); the
three slow_live DoD-3 tests (the 25 s block against the new `BLOCK - TICK - STAMP < max_loop_age < 28` bound, the
35 s drafter, the forced renewal failure); R019 with the test clock; the global bound and R015 live tests; R105 with
the leasing worker, heartbeat and reclaim; the heartbeat connection's keepalive/timeout options against a real
server; the loop connection's `SET lock_timeout = '10s'`; the live gate counts 951/979/991/1014/1023/1040 with 21
skipped; the roughly 2.5 extra minutes of the live gate.

## Clean-up

- No database or container was touched; no live run was attempted; `.env` was never opened, copied or recreated.
- `git worktree remove --force` and `git worktree prune` ran; `git worktree list` shows only
  `C:/Users/joeys/Desktop/MLOps 6ca01b3 [plan-h]`.
- The main checkout's `git status --short` is empty, and `plan-h` is still at 6ca01b3 with nothing committed on it.


## Controller rulings

# Plan H review, round 3 — controller rulings

Inputs: `round3-static.md` (APPROVE WITH SMALL FIXES: 0 Blocking, 1 Important, 6 Minor; every round-2 item fixed; the
three end-to-end properties hold) and `round3-dryrun.md`.

- **I1 (a handed-back `investigate` job on a RETRIEVING/DRAFTING run does nothing; the run holds its slot) — ACCEPTED,
  the alternative fix.** When the `investigate` handler finds its run in RETRIEVING or DRAFTING (a previous holder was
  interrupted: lost lease, crash, or a 55P03), it moves the run to FAILED through `transition_run` (legal from both
  states, SA:451) with detail message "interrupted; the run was not resumed", in a fenced unit, and finishes the job.
  That frees the conversation slot truthfully instead of holding it forever. One unit test per state (fake persistence)
  and one live assertion where the plan already re-runs a handed-back job if that is cheap; otherwise the unit tests
  suffice. Debt line: resuming an interrupted retrieval/draft instead of failing it → T20 (the graph's node resume).
  Correct the false sentences (plan 3123-3124, erratum 57, the m1 runbook paragraph) to say exactly this.
- **m-a — ACCEPTED.** The +1 allowance only for an actor that was mid-re-fence (its `begin_refence` flag set) when the
  beliefs were sampled.
- **m-b — ACCEPTED.** Update rulings 16 and 19 in the plan text for the heartbeat connection settings and the loop's
  `lock_timeout`.
- **m-c — ACCEPTED.** Correct the docstring/runbook claims: `keepalives_count` is ignored on Windows (about 60 s there),
  and neither keepalives nor `statement_timeout` bound a vanished peer; the local deadline does (the renewal error
  becomes a loss at the deadline).
- **m-d — ACCEPTED.** The leftover sweep skips databases with connections (`pg_stat_activity`), drops without FORCE, and
  builds its pattern from `SCRATCH_PREFIX`.
- **m-e — ACCEPTED.** `connector()` closes the new connection if a `SET` fails.
- **m-f — ACCEPTED.** Fix the docstring wrap; trim the history paragraph to three sentences.
- **Dry-run items** — apply whatever `round3-dryrun.md` lists (cites, Expected lines), if anything.

This is the last revision round unless the fix introduces a Blocking/Important defect: after applying, re-run the
task-by-task apply with `ruff format` between tasks, the splice check and the dev counts; append "Round 3 changes" /
"Round 3 open points". Do not commit.

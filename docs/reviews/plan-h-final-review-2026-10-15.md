# Plan H final review record — T13 run lease, fence locking, heartbeat thread and fault factory

Branch `plan-h`, executed range c5eeb89..6fd1ec3 (eight tasks, each with one task review; Task 8 had one wording fix
round). The whole-branch review below ran on the most capable model after Task 8; the controller ruled on every
finding; one fix wave (06e961a, 9978af3) applied the accepted ones; one scoped re-review verified them. The task-scoped
reviews are summarised in `docs/PROJECT_HISTORY.md`; the plan's own review is `docs/reviews/plan-review-h-2026-10-15.md`.

---

## Whole-branch review

# Plan H (T13) final whole-branch review — c5eeb89..6fd1ec3

Reviewer: senior code review (cross-task view). Branch `plan-h`, 11 commits, 72 files.

How the review was done, in passes:

1. **Code pass.** I read every new module in full: `core/lease.py`, `core/locking.py`, `worker/heartbeat.py`,
   `worker/permit.py`, `worker/handlers.py`, `worker/main.py`, `sweeper/leases.py` and revision 0007. I read the
   T13 hunks of `persistence.py`, `settings.py`, `privileges.py`, the API (`app.py`, `store.py`, `idempotency.py`),
   incident-sim and mcp-write, plus the unchanged callers whose behaviour T13 changes: mcp-read's
   `resolve_invocation` unit, mcp-write's `create_incident` and envelope mapping, and 0005's `grant_execution`.
2. **Trace pass.** I followed one investigate job and one execute job through claim, units, effects, loss/abandon,
   reclaim and the next owner, worker side and MCP side.
3. **Lock pass.** I checked every transaction in the tree against `LOCK_ORDER`, including foreign-key key-share waits
   and unique-index waits.
4. **Cancellation and shutdown pass.** I covered the worker loop, the heartbeat thread, the permit, the MCP SDK's
   server-side disconnect handling (installed `mcp` 2.3.0) and uvicorn 0.54's signal capture.
5. **Docs pass.** STATUS, SESSION_STATE, acceptance rows R019/R020/R087/R088/R098/R107, the runbook,
   ARCHITECTURE §5, PROJECT_HISTORY §25 and the reports, each read against its evidence.

I ran only `uv run python -m pytest tests/plan_h -q`: 113 passed. No live tests, no database, no checkout changes.

---

## Strengths

- **The fence is enforced where it matters: in the database, after the lock, in one place per side.** On the worker
  side, `persistence.fenced` opens every writing unit. On the MCP side, `_resolve_handle` takes `run_lease FOR SHARE`
  and compares the handle's fence and the lease's liveness. Every handle function goes through it: resolve,
  grant_execution, lookup_action, and the re-signed mark_sent/record_outcome. The MATERIALIZED-CTE lock statements
  compare `app.current_time()` after the lock wait, which the plan's ruling 5 literal form would not. There is a test
  that fails on the literal form.
- **The local deadline and the 5 s margin give a strong invariant.** A takeover needs the DB lease to have lapsed. The
  local deadline is taken before the acquiring or renewing statement and sits 5 s inside the DB expiry. So in
  production, `Lease.check()` already refuses before anyone else can hold the run. The definers fence independently
  anyway.
- **The B1 redesign is right: cancel effects, never units.** `Lease.effect` registers each effect as a child task
  under the lease's lock, so a cancel and a start cannot race. Cancellations of the caller's own task (`cancelling()`)
  pass through unchanged. `abandon` refuses to hand back on a non-idle connection and closes it instead. I checked the
  other side too: both MCP servers use `json_response=True`. On that path the installed SDK never runs
  `watch_disconnect`, so a worker-side cancel cannot cancel a definer unit on mcp-write's single-connection Session.
- **The re-fence hand-off is careful.** `begin_refence`/`end_refence` plus `fence_moved_by_owner` closes the window
  between `mark_unknown`'s commit and the shared Lease update. A lost COMMIT reply (exception → `end_refence(None)`)
  fails closed: the next renewal sees a settled mismatch and declares the lease lost.
- **The lock order is published as data, checked by a test, and holds.** I found no cycle across worker units, the
  heartbeat, mark_unknown, release/abandon, sweeper reclaim and sync, API admission/decision/reply, and the mcp-write
  definers. FK key-share waits are correctly ranked at their parent. FOR NO KEY UPDATE (the sweeper's and the claim's
  UPDATEs of `jobs`) does not conflict with the FOR KEY SHARE of `mint_handle`'s FK on `jobs`.
- **The claim is atomic.** Claim and lease commit in one transaction, the acquisition sits in a savepoint, NOWAIT is
  mapped to `Busy(locked)`, and the lock comes before the insert (erratum 46). So "claimed, not done, lease not live"
  really does mean a dead or lost owner, which keeps the reclaim simple and correct.
- **Erratum 59 is sound** (see Focus 4).
- **The docs are honest about their limits.** STATUS and R107 now say the stress run loses no lease and hands back no
  job. Execution-time rulings are recorded as errata 58/59. The struck debt line about handle capping is marked struck
  instead of silently removed.

---

## Issues

### Critical (Must Fix)

None.

### Important (Should Fix)

**I1. An execute job can be closed on a pre-SENT `INVALID_HANDLE` caused by the worker's own lapsed lease, leaving
the approved run stranded in APPROVED with no job.**

- **Where:** `core/src/ops_core/persistence.py:751-773` (`release_lease`, compare at :764),
  `worker/src/ops_worker/handlers.py:235-249` (`execute`) and :279-289 (`handle`).
- **What happens:**
  1. `execute` treats any envelope that is neither `GRANT_DEFERRED` nor `outcome/UNKNOWN` as final and returns
     True.
  2. `handle` then calls `release_lease`.
  3. `release_lease` compares owner and fence only. It checks neither `row["live"]` (the `LOCK_FOR_UPDATE` statement
     already returns it) nor `lease.check()`.
  4. T13 adds a new way to get an `INVALID_HANDLE` before SENT: the run's lease lapsed on the DB clock while
     `create_incident` was in flight, and nobody has taken it over yet. `_resolve_handle` refuses on
     `lease_until <= current_time()`, so `grant_execution` refuses and the server answers `INVALID_HANDLE`.
  5. If the worker receives that envelope before the heartbeat has marked the lease lost, the release still matches
     owner and fence. It finishes the execute job and releases the lease.
  6. The run stays APPROVED with no grant and no job. Nothing re-enqueues it. The approved action silently never runs,
     and the run keeps holding its conversation slot.
- **When it can happen:** the heartbeat can be late to mark the loss.
  - The error branch compares the pre-call `now` with the deadline (M1 below), so the loss can be signalled about
    6 s after the DB lapse.
  - A non-psycopg error in a tick never applies the deadline rule.
  - A heartbeat stuck in a send to a vanished peer never marks the loss at all.

  These are rare, but the consequence is the worst kind for this product: an approval that is silently dropped.
- **Why this needs a fix and not deferral:** the investigate side is not exposed, because every write there goes
  through `fenced()`, which calls `lease.check()`. Release is the one writing unit on the job path that skips both
  local and DB liveness.
- **Fix (small):**
  - In `release_lease`, call `lease.check()` before the unit.
  - Extend the compare at :764 with `or not row["live"]`.
  - That turns this case into `LeaseLost`. `run_job` then abandons (revoke and unclaim), and the next owner re-runs
    execute: APPROVED → fresh mint → grant.
  - Requiring liveness at release costs nothing. Every earlier unit of the job was fenced live, and a lapsed lease's
    job is handed back and re-read by its next owner.
  - Add a unit test: an `INVALID_HANDLE` envelope plus a lapsed `Lease` fake gives `LeaseLost` and abandon, never
    `finish_job`.
  - Optional: have `execute` treat `INVALID_HANDLE` as "re-check the fence" (`fenced()` in a fresh unit) rather than
    as final.

### Minor (Nice to Have)

- **M1. The heartbeat's error branch judges the deadline with the time taken before the failed call, and the
  catch-all never applies it.**
  - **Where:** `worker/src/ops_worker/heartbeat.py:177-184` and :149-152.
  - **Effect:** under repeated 5 s renewal timeouts, a loss (and its effect cancellation) is signalled up to about
    11 s after the local deadline. That is about 6 s after the DB lapse. Writes stay fenced, and this is already
    recorded in the SESSION_STATE open items. It is also the enabler of I1.
  - **Fix:** one line, `if self._clock() >= lease.deadline` after the failure. In `run()`'s catch-all, apply the same
    deadline rule to the held lease.
  - Consider libpq `tcp_user_timeout` (Linux) on the heartbeat connection, which bounds a send to a vanished peer
    that neither keepalives nor `statement_timeout` bound.
- **M2. "Shutdown cancels nothing; the poll loop finishes its current job first" holds for SIGINT only.**
  - **Where:** `worker/src/ops_worker/main.py:176-177`.
  - **Effect:** uvicorn 0.54's `capture_signals` (server.py:332-349) restores the original handlers when `serve()`
    returns and re-raises the captured signal. For SIGTERM the original handler is SIG_DFL, so the process dies as
    soon as the health server has shut down, mid-job. Safety holds: the transaction rolls back, the lease lapses, and
    the sweeper reclaims. But every container stop or rolling restart on Linux fails the in-flight investigate run as
    "interrupted" after up to about a lease plus a sweeper tick. On Windows, `skeleton.py` already hard-terminates.
  - **Fix:** install a SIGTERM handler (or run uvicorn with signal capture off) that sets `stop`, or correct the
    comment and say so in the runbook.
- **M3. The compute budget counts time spent waiting for the model permit.**
  - **Where:** `worker/src/ops_worker/heartbeat.py:171` (`held_since` is set at acquisition); the wait is in
    `worker/src/ops_worker/permit.py`.
  - **Effect:** with two or more worker replicas and model concurrency 1, a run that waits behind another worker's
    draft (up to 60 s once T19 caps it) loses its lease to "compute budget spent". Its next owner then fails it as
    "interrupted". BS:555 budgets active compute. There is no effect today (one replica, fake drafter), and the T29
    debt line ("counts one lease's hold time") covers the arithmetic but not this consequence.
  - **Fix:** name it in the T29 debt line. Runbook line 69 attributes "compute budget spent on every draft" only to
    a slow model; add permit contention.
- **M4. Readiness does not reflect the heartbeat thread.**
  - **Where:** `worker/src/ops_worker/main.py:161`.
  - **Effect:** if the thread ever died (only a BaseException could do it), the loop would keep claiming jobs that it
    could neither renew nor cancel.
  - **Fix:** make `/health/ready` also require `heartbeat.is_alive()`.
- **M5. Close-out documents.**
  - `docs/ARCHITECTURE.md:218` (R107 row) still says "an 8-connection stress test: no deadlock, no stale write". The
    6fd1ec3 fix corrected STATUS and the R107 note but not this row. Credit "no stale write" to the interleavings and
    the fenced-definer tests.
  - `docs/PROJECT_HISTORY.md:338` says "each reviewed once, no fix round". Task 8 had a wording fix round (6fd1ec3),
    and its problem and fix are not appended there, which the history standard asks for.
  - `STATUS.md:169`, `SESSION_STATE.md:5` and `:325` give the span as `c5eeb89..6c9e8f8` "the close-out commit
    follows". This is ledger Task 8 minor 98. Say `..6fd1ec3` (close-out e9d624d, 6fd1ec3).
- **M6. The stress test's "Catches" list overclaims.** At `tests/e2e/test_lease_stress_live.py:20-23` it lists "a
  stale writer whose event lands after a newer fence's event, a reclaim that takes a live owner's job". Both are
  vacuous in the run (`lost 0`, `jobs handed back 0`). This is already recorded as an open item. Trim it with M5.
- **M7. Lease loss is invisible outside the logs.**
  - **Where:** `worker/src/ops_worker/handlers.py:40` (`INTERRUPTED`).
  - **Effect:** a lost lease, a crash, a lock timeout and a spent budget all end as the same FAILED reason, and no
    run event or counter records a loss or a reclaim.
  - **Fix:** an operator would expect at least a distinct reason or a metric. Pick the owning task (T29/T30
    observability) and add a debt line; this is not a T13 requirement.

---

## Focus answers

1. **End-to-end fencing.**
   - **Worker side.** Every writing unit is fenced (owner, fence and liveness after the lock, plus the local
     deadline). `mint_handle` requires a live lease at exactly the fence under the unit's share lock.
     `mark_unknown` requires the fence and liveness under FOR UPDATE. `abandon` only revokes by fence and unclaims
     its own claim. The one gap is `release_lease`, which skips liveness and the local deadline (I1).
   - **MCP side.** Every handle function refuses a moved fence or a lapsed lease under FOR SHARE. mcp-read's unit is
     short and holds no lock across the search.
   - **After SENT.** A stale `record_outcome` is refused and answered UNKNOWN. The new owner's execute finds EXECUTING
     plus SENT, takes `next_step == "resend"`, makes an idempotent POST under the same action id and records under
     its own fence.
   - **One residual effect, by design.** A stale `create_incident` that passed `grant_execution` just before the loss
     can still POST its resend: an external, idempotent, same-bytes call. AM-13 accepts this, and it is not an
     application write.
   - **Abandon after a local-only loss** (stall or budget, lease still live in the DB). A definer that read the
     context row before the revocation committed can still pass, because the fence did not move. But the worker
     still holds that live lease at that fence, so nobody else can take over until it lapses. No authority is
     gained.
   - **Investigate trace.** A lost lease in RETRIEVING or DRAFTING is handed back, and the next owner fails the run
     as interrupted (declared T20).
   - **Execute trace.** A lost lease is handed back, the next owner resends, and the outcome is recorded once.
2. **Deadlock freedom.** No cycle found (see Strengths). Each unit in `OBSERVED_UNITS` matches the code I read. One
   blind spot I set aside: an `INSERT … ON CONFLICT` whose key matches a row another transaction is updating waits
   for that transaction, and `locking.py` does not model that. Today no unit inserts a job key that a concurrent
   claim or deferral could be updating. The one such insert, `mark_unknown`'s recover job, meets at most a lock-only
   SKIP LOCKED holder, which does not block it.
3. **Cancellation.**
   - No database unit is cancelled on the worker or on mcp-write. The loop connection cannot be left inside a
     transaction by a lease loss, and `abandon` guards it.
   - The permit's take and release are uncancelled units, and `finally` releases exactly the slot taken. It can leak
     only up to its 65 s TTL, on a failed release or a lost commit reply.
   - Shutdown is graceful only on SIGINT (M2).
4. **Erratum 59 is sound.** After SENT, a plain error would be wrong. To the worker, an `INVALID_HANDLE` envelope
   means "close the job" (handlers.py:235-249), which would leave an EXECUTING run with a SENT attempt that nobody
   reconciles. UNKNOWN makes the worker call `mark_unknown`, which refuses a stale fence and hands the job back, so
   the next owner resends and records. The `action_id` goes back only to a workload whose token passed transport auth
   and whose handle was authorized at grant time for that very action. The action id is not a capability (the
   destination demands `ops-mcp-write`), so AM-15's disclosure concern does not apply. Recommend the owner accept it
   as worded.
5. **Close-out documents.** They are truthful, except M5 and M6 and the R098 wording (triage below). The gate counts,
   the evidence files and the acceptance notes match the tests and reports I read.
6. **Operator expectations.**
   - **Worker restart mid-job.** An investigate run is failed as "interrupted" within about a lease plus a sweeper
     tick. An execute job resends. On Linux this happens even on a polite SIGTERM (M2).
   - **Observability of loss.** Logs only (M7).
   - **Liveness of the heartbeat.** Not in readiness (M4).
   - **Model contention.** It burns the compute budget (M3).

---

## Deferred-minor triage (ledger)

| Ledger line | Verdict | Reason |
|---|---|---|
| T1: report says 21 debt bullets, actual 20 | stay deferred | Report text only. |
| T1: docstring mid-sentence wrap | stay deferred | Cosmetic. |
| T1: slow_live gate test substring-matches check.py | stay deferred | Fragile but fails loudly if reformatted. |
| T1: OBSERVED_UNITS/OWN_UNITS mutable under Final | stay deferred | Nothing mutates them; MappingProxyType is optional. |
| T2: permit live test take/free outside try/finally; "held" tests expiry not SKIP LOCKED | stay deferred | Test hygiene. The SKIP LOCKED refusal to a second taker is shown in t13-heartbeat.txt. |
| T2: live round trip checks only absences at 0006 | stay deferred | The unit statement list plus the prosrc comparison cover exactness. |
| T2: queued_runs_total per-tenant statements, not one snapshot | stay deferred | The bound is declared soft (T29). |
| T2: redundant REVOKE before DROP TABLE in downgrade | stay deferred | Harmless. |
| T3: interim revoke_handles not fence-scoped | closed | 0007 `REVOKE_HANDLES` is fence-scoped (`ic.fence <= p_fence`). |
| T3: no live test refuses on the fence alone (same owner, higher fence) | stay deferred | Worth adding with T22. Owner names can collide across container restarts (PID 1), so the fence alone is what differentiates. The code compares both, which is correct by inspection. |
| T3: Lease.effect sticky flag; create_task under lock deadlocks with an eager task factory | stay deferred | Equivalent today: `cancel_effects` runs only after `mark_lost`. Add a one-line "no eager task factory" comment when next touched. |
| T3: INTERRUPTED path unit-tested only | closed | Exercised live by the R088 forced-renewal test ("the re-run failed the interrupted run"). |
| Ruling (T3): handle expiry at mint = now + 60 s | closed | Recorded as erratum 58; the code matches it. |
| T4: test_definers_write_path_live.py:443 OC003 ambiguous | stay deferred | Test precision; assert the DETAIL later. |
| T4: 0007:42 dead RuntimeError branch | stay deferred | Dead but harmless. |
| T4: test_migration_0007_live loads revision_0007() twice | stay deferred | Cosmetic. |
| T4: plan text still describes capped expiry | stay deferred | The plan is a historical record; SESSION_STATE, the runbook and the code carry erratum 58. |
| T6: takeover count does not require distinct owners | stay deferred | Evidence strength only. |
| T6: no-op drops count toward the 200-op floor | stay deferred | Evidence strength only. |
| T6: asyncio.gather does not cancel siblings (TaskGroup) | stay deferred | Test structure. |
| T6: quota-before-global order not pinned with both full | stay deferred | Only the 429 message differs. |
| T6: reclaim docstring names renewal only | stay deferred | Fresh acquisition after the snapshot is the same benign race (I verified the EPQ behaviour: the subquery keeps the statement snapshot). A one-word fix whenever touched. |
| T6: evidence "operations" figure includes derived counters | stay deferred | Report wording. |
| T7: faults `_seconds` persists across arm() | stay deferred | Test-only; documented. |
| T7: dev/demo 404 test omits receipt_hash_mismatch | stay deferred | The route is registered only when `faults is not None` (api app.py:694, incident-sim app.py:248), so the 404 is structural for every kind. |
| T7: no test that a POST after a delayed lookup returns the real receipt | stay deferred | T22/T47 consume `delay_receipt`. |
| T7: malformed_response on a CONFLICT row answers 200 | stay deferred | Test-only fidelity; mcp-write classifies it as UNKNOWN anyway. |
| T7: no test that production_app passes faults=None in dev | stay deferred | `create_app` raises if faults are given outside TEST, a structural guard. |
| Ruling (T7/T8): errata 58, 59 and the stress drop step | closed | Recorded in SESSION_STATE; 59 judged sound above. |
| T8 (FINAL-REVIEW ATTENTION): R098 "every fault route … is 404" lacks per-kind tests for three kinds | stay deferred | True structurally (see the T7 line above). Optionally add "(the route is not registered outside PROFILE=test)" to the note. |
| T8: test_leases_live.py:~299 evidence line cryptic | stay deferred | Wording. |
| T8: SESSION_STATE:5/325 and STATUS:169 "close-out commit follows" span | fix-before-merge (with M5) | Doc truthfulness; a one-line edit in the same doc wave. |

From SESSION_STATE "Open items":

| Open item | Verdict | Reason |
|---|---|---|
| Heartbeat error branch | fix with I1 (M1) | It is I1's enabler and a one-line fix. |
| Permit TTL 65 s vs an uncapped hold | stay deferred | T19's 60 s cap. |
| Stress-test docstring overclaim | fix with M5 (M6) | Doc truthfulness. |

The rest of the open items are already covered by the ledger lines above.

---

## Declined to judge

Behaviours I considered and set aside as outside the plan or the spec:

- **Real Ollama behaviour under cancellation and the permit's idle-release rule.** T19, gated on T02's measurement.
- **Budget accounting across jobs, human-wait exclusion, R062 caps, one compute lease per requester.** Declared T29.
- **Bounded retries, recover-job handling, the AM-13 transport-timeout path.** Declared T22. Recover jobs are closed
  untouched today.
- **Wake-ups, the outbox, and the deferred job waiting for `lease_until` after an early release.** Declared T14.
- **The asset-guard advisory lock in `freeze_proposal`/`grant_execution`.** Declared T21.
- **Checkpoints under the fence and R021.** Declared T20/T38.
- **Resuming interrupted investigate runs.** Declared T20; failing them is the stated interim.
- **Pools and reconnecting the loop connection.** Declared T30.
- **The global queue bound's softness and its per-tenant scan cost.** Declared T29.
- **Whether the live gate counts (1042/21) and the multi-run stability claims reproduce.** I was told not to run
  live tests and took the recorded evidence at face value.
- **Server-side cancellation of mcp-write handlers on client disconnect.** Investigated and found not to happen:
  `json_response=True` skips `watch_disconnect`, so I set it aside.
- **uvicorn's force-exit on a second SIGINT.** Operator-initiated hard stop; covered by the reclaim.
- **Rate skew between the DB clock and the worker's monotonic clock.** The 5 s margin is the spec's (SA:195) and a
  physical-clock question.
- **Unique-index waits not modelled in `locking.py`.** No current unit reaches one (Focus 2).
- **Owner-name collision across container restarts (hostname:PID 1).** Fences are compared alongside owners in every
  check, so it grants nothing.
- **AM-15 `action_id` disclosure in erratum 59.** Judged sound (Focus 4); the owner decides the erratum.
- **Fidelity details of the incident-sim fault hooks** (status codes per kind). Test-profile only; their consumers
  are T22/T47.
- **The API, mcp-read and incident-sim behaviour outside the T13 hunks.** Reviewed in earlier plans.

---

## Recommendations

1. Fix I1: liveness and the local deadline at release, plus a unit test. Fold in M1's one-line heartbeat fix.
2. One doc wave: ARCHITECTURE's R107 row; a PROJECT_HISTORY entry for the Task 8 wording round and the final-review
   round; the STATUS/SESSION_STATE spans; the stress-test "Catches" list.
3. Before T14 builds on the worker loop, decide SIGTERM handling (M2) and add `heartbeat.is_alive()` to readiness
   (M4).
4. Add M3 and M7 to the debt list under T29/T30, so model contention and lease-loss observability have owners.

---

## Assessment

**Counts:** Critical 0 · Important 1 · Minor 7

**Ready to merge?** With fixes.

**Reasoning:** The fencing, lock order and cancellation design is sound end to end, and every requirement claim
matches its evidence. One release-path gap can silently strand an approved run, and it is a few lines to close,
together with the small doc corrections.


---

## Controller rulings on the findings

- I1 (release under a lapsed lease closes an execute job; the approved run is stranded), M1 (the heartbeat applies
  the local deadline late or not at all), M4 (readiness ignores the heartbeat thread), M5 (three documentation slips)
  and M6 (the stress docstring overclaims): fixed in the one wave.
- M2 (SIGTERM does not drain the current job; uvicorn 0.54 re-raises it), M3 (the model-permit wait counts against
  the 90 s compute budget) and M7 (a lost lease is visible only in the logs): recorded as debt lines owned by T30,
  T29 and T28; the misleading SIGTERM comment in `worker/src/ops_worker/main.py` was corrected. Cost if wrong: the
  SIGTERM gap stays until T30; a job is then handed back by the sweeper's reclaim after the lease lapses, and no
  authority is lost.
- Deferred-minor triage: as the review lists; the items it marked fix-before-merge were folded into M5.

---

## Fix wave report

# Plan H final review: fix report

Branch `plan-h`. Before the wave HEAD was `6fd1ec3`. The wave added two commits, with no attribution trailers and nothing pushed:

- `06e961a`: fix(worker). The final unit requires a live lease, the heartbeat judges failures on a fresh clock reading, and readiness needs the heartbeat thread.
- `9978af3`: docs. Records the final review and its fix wave: spans, gates, history, runbook and debt lines.

## Rulings

### 1. I1: release under a lapsed lease (Important)

**What changed**

- `core/src/ops_core/persistence.py:751-779` (`release_lease`):
  - `lease.check()` now runs before the unit (line 767).
  - The comparison after `LOCK_FOR_UPDATE` adds `or not row["live"]` (line 772).
  - The loss reason is now "another owner holds the lease, or it lapsed".
  - The FOR UPDATE-from-the-start shape is unchanged.
  - The docstring now says the unit checks the local deadline first, then compares owner, fence and liveness after the lock. It explains the INVALID_HANDLE case, and its `Raises:` section names all three causes.
- `worker/src/ops_worker/handlers.py:205-214` (`execute` docstring): says that any other envelope, `INVALID_HANDLE` included, counts as final. When the worker's own lease lapsed, the final unit now raises LeaseLost, so the job is handed back.

**Trace of the failure case**

1. `execute` returns True.
2. `handle` calls `release_lease`.
3. `release_lease` finds `live` false, calls `mark_lost` and raises LeaseLost. The unit rolls back with nothing written.
4. `main.run_job` catches LeaseLost and calls `handlers.abandon`, which revokes the handles and unclaims the job.
5. The job's next owner finds the run APPROVED, mints a fresh handle and asks for the grant again.

The `McpCallFailed` and `GRANT_DEFERRED` re-queue paths also call `release_lease`. Under a lapsed lease they now hand the job back too, claimable at once instead of after 30 s.

**Tests**

- `tests/plan_h/test_worker_units.py`:
  - `test_release_of_a_live_lease_closes_the_job`: one unit runs set_tenant, lock, revoke, finish and release, and the lease ends RELEASED.
  - `test_release_refuses_a_lease_that_lapsed_on_the_database_clock`: the log is exactly BEGIN, set_tenant, lock_lease, ROLLBACK; then LeaseLost.
  - `test_release_refuses_past_the_local_deadline_before_any_statement`: LeaseLost with no statement run.
  - `test_an_invalid_handle_under_a_lapsed_lease_hands_the_job_back`: `main.run_job` with an APPROVED run, `create_incident` answering INVALID_HANDLE, and a lease row that is not live. The last two units are the refused release and the abandon unit (`set_tenant`, `revoke_handles`, `unclaim_job`). There is no `finish_job` and no `requeue_job`.
- Live: `tests/e2e/test_leases_live.py::test_a_release_under_a_lapsed_lease_closes_nothing`. After `expire_lease`, the release raises LeaseLost, and the job stays open and claimed by `wa` at the same fence with the lease not released. This added one evidence line to `reports/leases/t13-leases.txt`, and `EXPECTED_LINES` went from 10 to 11.
- Against the old code, with persistence.py and main.py stashed, the three release refusals and the INVALID_HANDLE trace fail. The readiness tests fail too, on the new signature.

### 2. M1: heartbeat deadline on a fresh clock reading

**What changed**

- `worker/src/ops_worker/heartbeat.py:189-194`: the renewal error branch compares `self._clock() >= lease.deadline`. A comment explains that the earlier `now` was taken before the failed call, which may have spent its timeouts.
- `worker/src/ops_worker/heartbeat.py:145-163`: `run()` now calls a new method, `guarded_tick()`. It holds the existing catch-all, unchanged, with no new broad except. After logging, it applies the same deadline rule to the held lease, with the reason "heartbeat ticks failed until the local deadline".
- `connector`'s docstring wording is updated to match.

**Tests** (`tests/plan_h/test_heartbeat.py`, fake clock)

- `test_a_renewal_that_fails_past_the_deadline_is_a_loss_at_once`: the renewal starts at 22, and the renewer moves the clock to 27 and raises QueryCanceled. The lease is lost at once and its effects are cancelled once.
- `test_an_unexpected_tick_error_is_a_loss_past_the_deadline`: a RuntimeError at 10 and 20 keeps the lease and does not raise. At 25 the lease is lost.

Both tests fail on the old code (checked with the file stashed).

### 3. M4: readiness requires the heartbeat thread

**What changed**

- `worker/src/ops_worker/main.py:105-126`: `health_app` takes a new `heartbeat_alive` argument. `/health/ready` answers 503 with `heartbeat thread stopped` when the thread is not alive. The poll-loop check comes first and is unchanged.
- `worker/src/ops_worker/main.py:167`: passes `heartbeat.is_alive`.

**Test**: `tests/plan_h/test_worker_units.py::test_readiness_needs_the_poll_loop_and_the_heartbeat_thread`, parametrised three ways (200; 503 poll loop stopped; 503 heartbeat thread stopped), using Starlette's TestClient.

### 4. M5: documents

- `docs/ARCHITECTURE.md:218`: the R107 row now says the stress test shows no deadlock, and credits "no stale write" to the interleaving, fenced-definer and R019 tests.
- `docs/PROJECT_HISTORY.md` §25:
  - "no fix round" is now "one wording fix round, in Task 8".
  - A Problem/Change pair covers the stress overclaim (`6fd1ec3`).
  - A final-review paragraph covers: 0/1/7; I1 (the stranded approved run) and its fix; the heartbeat deadline; readiness; the debts M2→T30, M3→T29 and M7→T28; and erratum 59 judged sound.
- `STATUS.md`, `SESSION_STATE.md` (line 5 and the Plan H section) and the T13 note in `handoff/tasks.json` now give the span `c5eeb89..06e961a`, naming the close-out `e9d624d`/`6fd1ec3` and the fix `06e961a`.
  - A commit cannot name itself, so the docs commit `9978af3` on top is described in words: "the docs commit recording that fix sits on top".
  - The gates are updated to 939/134 and 1052/21, and STATUS and SESSION_STATE each have a final-review bullet.

### 5. M6: stress test docstring

`tests/e2e/test_lease_stress_live.py:20-28`: the "Catches" list drops the stale-writer and reclaim-under-load claims. A new paragraph says the run's evidence records `lost 0` and `jobs handed back 0`. It also says that the interleavings in `test_leases_live.py` and the fenced definers in `test_fenced_definers_live.py` cover the refusal of a stale write, and that R019 and the live-lease reclaim test in the same module cover the reclaim.

### 6. M2, M3, M7 as debt

- `worker/src/ops_worker/main.py:182-186`: the comment is corrected. On SIGINT the current job finishes. SIGTERM is not drained, because uvicorn 0.54 re-raises it after `serve()` returns; I checked this in `uvicorn/server.py:332-349`. The open unit rolls back, the lease lapses and the sweeper hands the job back. A `TODO(T30)` is added.
- `SESSION_STATE.md`, Plan H debt list: three lines added: M2 SIGTERM drain → T30; M3 permit wait counted against the 90 s compute budget, which matters with more than one worker → T29; M7 lease loss visible only in logs → T28.
- The other T-owned items live in the debt list, not in "Open items", so the three lines went there only.
- `docs/runbooks/leases.md`:
  - The two new log lines.
  - The readiness reasons, plus a note that a lost lease shows only in the logs (T28).
  - The "compute budget spent" line names permit contention (T29).
  - A SIGTERM troubleshooting line (T30).

### 7. Open items

In `SESSION_STATE.md` "Open items for later":

- Removed the heartbeat error-branch item and the stress docstring item (both closed by this wave).
- Marked the dev/demo 404 (`receipt_hash_mismatch`) item closed: the 404 holds for every kind because the route is registered only when faults exist.
- Extended the R098 note in `handoff/acceptance-matrix.json` with that reason.

## Commands and results

- `uv run ruff format` and `uv run ruff check --fix` on the 8 changed code and test files: unchanged, and "All checks passed!". The 120-character check is clean, apart from one markdown table row in ARCHITECTURE, which cannot wrap.
- `uv run python -m pytest tests/plan_h/test_heartbeat.py -q`: 12 passed. `tests/plan_h/test_worker_units.py`: 20 passed.
- `PYTHONUTF8=1 uv run python scripts/check.py`: **CHECK: GREEN, 939 passed, 134 skipped**. That is 930 + 9 unit tests: 2 heartbeat, 4 release/trace and 3 readiness parameters. The extra skip is the new live test. Re-run after the docs edits with the same result.
- `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`: exit 0, before and after the docs edits.
- `uv run python scripts/skeleton.py status`: all six processes down.
- `PYTHONUTF8=1 uv run python scripts/check.py --profile test`: **CHECK: GREEN, 1052 passed, 21 skipped** in 301.65 s. That is 1042 + 9 unit + 1 live. Ruff, format and mypy (53 source files) were clean.
- After the live run:
  - `git checkout -- reports/bootstrap reports/skeleton reports/auth reports/admission`.
  - `reports/leases/t13-leases.txt` is committed: it legitimately gained the line "release under a lapsed lease: refused; the job stays open and claimed, the lease unreleased".
  - `t13-stress.txt` and `t13-heartbeat.txt` changed only in their timestamps and run figures, so they were reverted.
- Working tree clean after the commits.

## Concerns

- No `docs/reviews/plan-h-final-review-*.md` exists. Plan G's final review was copied into `docs/reviews/`, but this review stays only in the git-ignored SDD ledger. The PROJECT_HISTORY paragraph therefore cites no path. Copy it if the precedent should hold.
- Not touched: the `SESSION_STATE.md` "Exact next step" section still ends with "write Plan H (T13)", which is stale and outside this wave's rulings.


---

## Scoped re-review of the fix wave (6fd1ec3..9978af3)

Verdict: all findings addressed, no new Critical or Important breakage.

- I1 addressed: `release_lease` calls `lease.check()` and adds `not row["live"]` to the comparison after the lock;
  the unit rolls back and `run_job` hands the job back through `abandon`; unit tests (live release, lapsed database
  lease, past the local deadline, INVALID_HANDLE through `run_job` to `abandon`) and the live test
  `test_a_release_under_a_lapsed_lease_closes_nothing`.
- M1 addressed (fresh clock in the error branch; the catch-all applies the deadline), M4 addressed (`/health/ready`
  answers 503 "heartbeat thread stopped"), M5, M6, the M2/M3/M7 debt lines and the open items addressed.
- Checked and sound: a live holder's release cannot raise LeaseLost spuriously (the local deadline fails only after
  renewals stop, and `live` is read after the FOR UPDATE); if it fires early the job is deferred behind the live
  lease and re-claimed at fence + 1, with no busy loop. The McpCallFailed and GRANT_DEFERRED paths under a lapsed
  lease now hand the job back at once instead of re-queuing it for 30 s; each lapse buys one extra attempt, the next
  one runs under a fresh lease and re-queues for 30 s as before, so there is no hot loop. The M1 catch-all signals
  loss only past the local deadline, so no healthy lease is cancelled. `Thread.is_alive()` is safe across threads.
- Out of scope, noted: the runbook's log lines omit the `check()`/`fenced()` reasons; M7 may sit more naturally
  with T29 than T28 (owner's choice).
- Focused check run by the re-reviewer: `uv run python -m pytest -p no:cacheprovider tests/plan_h
  tests/plan_f/test_grant_deferred.py -q` — 125 passed.

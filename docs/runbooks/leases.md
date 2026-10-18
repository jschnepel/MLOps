# Run leases, fences, the heartbeat and the model permit (T13)

Who this is for: whoever runs the worker, reads its logs, or debugs a run that seems stuck. The design is AM-12 in
`SPEC_AMENDMENTS.md` and Plan H (`docs/superpowers/plans/2026-10-15-first-slice-h-leases-fences-heartbeat.md`).

## What holds a run

- **One lease per run** (`app.run_lease`: `owner`, `fence`, `lease_until`). The worker takes it in the same
  transaction that claims a job; a job whose run's lease is held by someone else is not claimed, only moved behind
  the lease (`jobs.available_at`). The first lease of a run has fence 1; every acquisition adds one; a released
  lease has `lease_until = '-infinity'` and keeps its fence.
- **Fenced writes.** Every unit the worker commits for a run starts by locking the lease row `FOR SHARE` and checking
  owner, fence and expiry on the database clock; MCP handles carry the fence they were minted under and are refused
  once it moves. A worker that lost its lease writes nothing.
- **The heartbeat** is a thread in the worker with its own database connection. It renews the held lease every
  `OPS_HEARTBEAT_SECONDS` while the event loop stamps signs of life (`OPS_LOOP_STALL_SECONDS`) and the job is within
  `OPS_COMPUTE_BUDGET_SECONDS`. When renewal fails it cancels the job's MCP or model call in flight (never a
  database unit, which finishes and then meets the fence check); the worker revokes the job's handles and hands the
  job back with no state change.
- **Handles are bound to the current lease when they are used, not when they are minted.** A handle's stored expiry is
  60 s after its mint (`app.current_time() + 60 s`); it is not capped at the lease's end. Every handle function
  (`resolve_invocation`, `grant_execution`, `lookup_action`, `mark_sent`, `record_outcome`) compares the handle's
  fence with the run's lease and requires a live lease, under `FOR SHARE`, so a handle is refused (OC008,
  `INVALID_HANDLE` before SENT) the moment its fence moves or its lease lapses, whatever its stored expiry. A renewed
  lease therefore keeps a long call's handle usable. After SENT a stale-fence refusal is answered `outcome` /
  `UNKNOWN` with the `action_id`, not a plain error (errata 58 and 59 in `SESSION_STATE.md`).
- **The model permit** (`app.model_permit`, one slot) is held around each model call; a waiting worker polls with
  backoff; a holder that died frees it after 65 s.
- **The sweeper** hands back, every tick, the jobs claimed by a worker whose lease is no longer live.

## Settings (validated at start; the worker refuses an unsafe combination)

| Variable | Default | Bounds | Rule |
|---|---|---|---|
| `OPS_LEASE_SECONDS` | 30 | 10-900 | BS:557 |
| `OPS_HEARTBEAT_SECONDS` | 10 | 1-300 | twice it plus 6 s (the 5 s deadline margin and the 1 s tick) below the lease |
| `OPS_LOOP_STALL_SECONDS` | 28 | 2-900 | below the lease plus one heartbeat; above 25 for DoD 3 |
| `OPS_COMPUTE_BUDGET_SECONDS` | 90 | 10-3600 | at least one lease (BS:555) |
| `OPS_GLOBAL_QUEUE_LIMIT` | 100 | 1-100000 | API: QUEUED runs across tenants (BS:550) |

The global queue bound is soft: two admissions in different tenants can both pass a count one below the limit, so it
can be exceeded by the number of admissions in flight at once. The per-tenant quota (`OPS_TENANT_QUEUE_QUOTA`) still
applies first. The count costs one indexed scan per tenant inside every run admission (`app.queued_runs_total()`
sums the tenants' QUEUED runs); a cheaper counter is T29's with the rest of the budget accounting.

## Looking at it

As the superuser on the dev database:

```sql
SELECT run_id, owner, fence, lease_until, lease_until > app.current_time() AS live FROM app.run_lease;
SELECT slot, holder, run_id, leased_until FROM app.model_permit;
SELECT id, type, run_id, claimed_by, claimed_at, available_at FROM app.jobs WHERE done_at IS NULL;
```

Log lines to know (worker): `run lease lost (event loop stalled)`, `(compute budget spent)`, `(another owner took the
lease)`, `(the lease expired)`, `(renewals failed until the local deadline)`, `(heartbeat ticks failed until the local
deadline)`, and from the job's final unit `(another owner holds the lease, or it lapsed)` — each followed by the job
being handed back. A lost lease shows only in these lines: no run event, reason or metric records it yet (T28).
Sweeper: `reclaimed N job(s) whose run lease was not live`.

Readiness (`/health/ready` on `OPS_WORKER_HEALTH_PORT`) answers 503 with `poll loop stopped` or `heartbeat thread
stopped` when either has died; a supervisor should restart that worker.

## When something looks stuck

- A job keeps moving its `available_at` forward without being claimed: its run's lease is live under another owner.
  Check that owner's worker; if it is gone, the lease lapses within one lease and the sweeper hands the job back.
- A run ends FAILED with `interrupted; the run was not resumed`: a worker lost its lease (or crashed, or hit the lock
  timeout) during retrieval or drafting, and the job's next owner failed the run rather than leave it holding the
  conversation's slot. Resuming such a run is T20's (the graph's node resume).
- A worker logs repeated `event loop stalled`: something blocks its event loop for longer than the stall gate (a
  synchronous call on the loop). The lease is lost on purpose; fix the blocking call.
- `compute budget spent` on every draft: the model is slower than the budget, or the run waited for the model permit
  behind another worker's draft (until T29 the wait counts against the budget; with one worker it never happens). The
  budget is BS:555's 90 s.
- A run fails as `interrupted` after every worker restart on Linux: SIGTERM is not drained. uvicorn re-raises it once
  the health server has shut down, so the process ends mid-job; the open unit rolls back, the lease lapses and the
  sweeper hands the job back. SIGINT lets the current job finish. Draining on SIGTERM is T30's.
- A worker logs `transient database error` with `LockNotAvailable` (SQLSTATE 55P03): one of its units waited more than
  the loop connection's 10 s `lock_timeout` (`main.LOOP_LOCK_TIMEOUT`) behind another transaction. Units are never
  cancelled, so this is the bound on a stuck one: the unit rolls back, the job keeps its claim but its lease is no
  longer renewed, and within one lease the sweeper hands the job back. An `investigate` job's next owner then finds
  the run in RETRIEVING or DRAFTING and fails it (`interrupted; the run was not resumed`; resuming is T20's); inside
  drafting and freezing, as for any error there, the run is failed at once. Look for the transaction holding the lock
  (`pg_blocking_pids`).

## The lock order

Published in `core/src/ops_core/locking.py` (`LOCK_ORDER`, checked by `tests/plan_h/test_locking.py`): idempotency
advisory lock → asset-guard advisory lock → `jobs` (claim, SKIP LOCKED) → `run_lease` → `runs` → `messages` → `drafts`
→ `proposals` → `decisions` → `memberships` → `execution_grant` → `action_attempt` → `action_attempt_state` →
`operator_resolutions` → `invocation_context` → `run_state_history` → `events` → `outbox` → `jobs` (finish) →
`idempotency_request`. A new transaction or table is placed there before it ships.

## Test-profile fault hooks (`PROFILE=test` only; 404 elsewhere)

incident-sim (`POST /internal/faults/{kind}`, workload token, body `{"count": n}` and for `timeout_before_accept`
`"seconds": s`): `reject_next`, `drop_before_commit`, `lose_after_commit`, `timeout_before_accept`, `rate_limit`,
`malformed_response`, `receipt_hash_mismatch`, `delay_receipt` (the next `count` lookups 404). The API (same route,
identity and CSRF as any browser mutation): `drop_before_commit`, `lose_after_commit`. `core.testing.faults.BS405`
maps BUILD_SPEC's nine faults to these.

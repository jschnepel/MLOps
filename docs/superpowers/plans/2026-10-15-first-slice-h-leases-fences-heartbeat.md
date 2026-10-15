# First Slice H: Run Lease, Fence Locking, Heartbeat Thread and Fault Factory (T13) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every application write for a run is fenced by the run's lease: the worker takes the lease in the same
transaction that claims a job (`FOR UPDATE NOWAIT`; a busy run's job is deferred, never claimed), opens every unit
that writes for the run with a `FOR SHARE` check of owner, fence and expiry on `app.current_time()` after the lock,
starts no effect past a local monotonic deadline, and releases the lease with the job in one final unit; the MCP
definers refuse a handle whose fence moved or whose lease lapsed; a heartbeat thread on its own connection renews
the lease while the event loop is alive and the 90 s budget lasts, and when renewal fails cancels the job's effects
in flight (its MCP or model call, never a database unit); a
`model_permit` row bounds model concurrency; the sweeper hands back jobs whose lease died; one published lock order
holds everywhere, and a stress test shows it never deadlocks; the API enforces a global queue bound; and the fault
factory implements all nine BS:405 faults (T13; R019, R020, R087, R088, R098, R107).

**Architecture:** Revision `0007_leases_fences` on the `app` main line creates `app.model_permit` (one seeded slot,
worker `sel, upd`), gives `app_definer` `upd(fence)` on `run_lease` (so definers may lock the row and `mark_unknown`
may bump it), adds a CHECK on `jobs.type`, and re-creates the fenced definers (`_resolve_handle`, `grant_execution`,
`mark_sent(raw_handle, action_id)`, `record_outcome(raw_handle, action_id, outcome, doc)`, `mark_unknown` returning
the new fence, `revoke_handles` scoped by fence) plus the new `queued_runs_total()`; its downgrade restores 0006
exactly by re-executing the applied revisions' own bodies. `core/src/ops_core/lease.py` holds the `Lease` the event
loop and the heartbeat thread share (one `threading.Lock`), `LeaseLost`, the lock statements and the synchronous
renewal; `core/src/ops_core/locking.py` publishes the lock order as data a test checks; `ops_core.persistence` gains
`acquire_lease`, `claim_next`, `fenced`, `release_lease`, `unclaim_job`, the permit SQL and `queued_runs_total`. The
worker runs each job under its lease, every MCP and model call as a cancellable lease effect (`Lease.effect`), with
`worker/src/ops_worker/heartbeat.py` (thread, liveness gate, compute gate, cancelling effects on loss) and
`worker/src/ops_worker/permit.py` (the model permit around drafting); the sweeper's
`ops_sweeper/leases.py` reclaims; incident-sim and the API gain the remaining fault kinds.

**Tech Stack:** as Plan G; no new dependency. psycopg 3.3.6 (its synchronous `psycopg.Connection` for the heartbeat
thread, already in the lock), PostgreSQL 17, Python 3.13 `threading` and `asyncio`, FastAPI 0.143.0.

**Spec:** `SPEC_AMENDMENTS.md` (OPS-BUILD-1.3.6) over `BUILD_SPEC.md`: AM-12 (SA:170-218), AM-13 (SA:250-256),
AM-20.2-20.7 (SA:408-564), BS §8 (BS:332-342), §10 (BS:403-407), §17 (BS:540-562). The fact sheet
`docs/superpowers/research/2026-10-15-plan-h-inputs.md` (cited "FS §n" / "FS Qn": T13 verbatim, the binding spec
text, the tree as it is with path:line cites, 31 open questions) and the controller's brief of 31 rulings (cited
"brief ruling n"; the rulings are reproduced below with what this plan made of each) are the inputs. Earlier
artefacts this plan builds on: revisions 0001-0006 and the `testclock` branch, `ops_core.persistence`, `privileges`,
`settings`, `jobs`, `testing.faults`, the worker, the sweeper, mcp-write, incident-sim, the API store, `tests/e2e/`
and the Plan D-G unit tests.

## Global Constraints

Carried from Plan G's header (Plan G's own text applies with "Plan G"/"T12" read as the plan that wrote it); the
Plan H additions below win where the two differ:

- **Debt before code (SA:698).** The Plan H debt list (below) is committed in Task 1 Step 1c before any code changes.
  Nothing not on the list may be shortcut; every line names its owning task.
- **Authority boundaries stay where the spec puts them.** Runtime roles never UPDATE `runs.state` or INSERT into
  audit tables (SA:387); the worker moves runs only through `transition_run`, `freeze_proposal` and `mark_unknown`;
  mcp-read and mcp-write hold no table grant (SA:437) and reach the lease only inside definer functions; nothing
  here sends anything to a real external system; approvals, grants and the destination stay untouched apart from
  the fence check in front of them.
- **Secrets** live only as files under `OPS_SECRETS_DIR`. No secret, token, handle, session id or password in an
  environment variable, log line, exception message, assertion operand, evidence file or document. A raw invocation
  handle never reaches a log or an assert operand (only its hash, `persistence.handle_hash`).
- **Clock.** Every lease, permit and handle-expiry comparison in SQL uses `app.current_time()` evaluated *after* the
  row lock it depends on (SA:157): the lock statements are `WITH l AS MATERIALIZED (SELECT … FOR UPDATE|FOR SHARE)`
  followed by an outer `SELECT` that compares (`ops_core.lease`), and the PL/pgSQL definers lock first and compare in
  the next statement. Python never compares database instants; the only time Python compares is the lease's local
  monotonic deadline (SA:195). Column defaults stay `now()`.
- **One string per function**, binds and the ISC004 rule exactly as in Plan E (a colon right after a quote or a space
  followed by a word is a SQLAlchemy bind; `tests/plan_e/test_transitions_table.py` scans every revision's upgrade
  and downgrade strings, 0007 included).
- **Loopback only, async on the event loop, autocommit connections with explicit units** (Plan D rulings 15, 23, 24):
  unchanged. The one synchronous connection is the heartbeat thread's, which never runs on the event loop.
- **Live tests never touch the dev databases**, run against `ops_test`/`incident_test` under `PROFILE=test` through
  the existing `migrated`, `app_conn` and `role_conn` fixtures. A test that moves `app.test_clock` does so only while
  no other lease matters and resets it in `finally` (the offset is global: every lease in the database moves).
- **Tests:** unit tests in `tests/plan_h/` (DB-free; added to `testpaths` in Task 1), live tests in `tests/e2e/`
  gated by `OPS_LIVE=1`; existing tests are updated in the task that changes the interface they pin, never deleted.
  No xfail or skip except the live gate (BS:597).
- **Comments** per `docs/CODE_COMMENTS.md`; ≤120 characters per line (Plan G's counting command below); no
  `type: ignore`; ruff + mypy strict clean; UTF-8 without BOM, LF; no `noqa: BLE001` and no new broad
  `except Exception` (the two existing ones in the worker and sweeper loops stay; the heartbeat thread's tick guard is
  the one new catch-all, and `Lease.effect`'s `except BaseException` re-raises everything, as LeaseLost when the
  lease's loss cancelled the effect, as `heartbeat.connector`'s does after closing a connection whose SET failed; each
  carries its reason).
- **Gates:** `uv run ruff format <files> && uv run ruff check --fix <files>` (then
  `uv run ruff check --select ISC004 --fix --unsafe-fixes migrations/app/versions/0007_leases_fences.py` after writing
  or extending the revision), `PYTHONUTF8=1 uv run python scripts/check.py` GREEN after every task,
  `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts` exit 0, and the live suite
  `PYTHONUTF8=1 uv run python scripts/check.py --profile test` after every task that changes a migration, a service
  or a live test (all eight but Task 1). It needs the dev stack up and `uv run python scripts/skeleton.py status`
  showing every process down. After a live run: `git checkout -- reports/bootstrap reports/skeleton reports/auth
  reports/admission` (all four are rewritten by live runs; Task 8 commits the ones it names). mypy's incremental
  cache can report spurious errors after many edits; rerun with `--no-incremental` before treating one as real.
- **Counting characters** (the "Comments" rule): print every line over 120 characters in the given files; no output
  means they pass. It takes files, not directories.

  ```bash
  uv run python - <files> <<'EOF'
  import sys
  for path in sys.argv[1:]:
      for number, line in enumerate(open(path, encoding="utf-8"), start=1):
          if len(line.rstrip("\n")) > 120:
              print(path, number)
  EOF
  ```

- **Toolchain and locks:** everything through the locked environment from the repository root
  (`uv run python -m pytest …`, never a bare `pytest`); no `uv add`, no `uv lock` (`uv.lock` does not change).
- **Never migrate the dev databases.** Nobody runs `scripts/skeleton.py migrate` or `up` against `ops`/`incident` in
  this plan; the live suite migrates its own `ops_test`/`incident_test` every session. Revision 0007 is created in
  Task 2 and extended in Task 4 (new revision files are applied only to the per-session test databases until the
  owner migrates; `migrated` recreates them every session, so extending an unreleased revision is safe). Migrating
  the dev database to 0007 is an owner input recorded in Task 8; until then the worker, the API and mcp-write refuse
  to start on it, by design.
- **Commits:** one logical group per step; messages free of any attribution trailer (owner instruction); never push;
  never `docker compose down -v`; never change system settings; never drop a role, database, persona or Keycloak
  object (the test databases excepted).
- **No interim red across tasks.** Every task ends with both gates GREEN at the stated counts. The order is chosen
  for that: the worker holds leases (Task 3) before any definer checks a fence (Task 4), and the heartbeat (Task 5)
  only adds renewal and cancellation to a worker that is already correct for jobs shorter than its lease.
- **Line numbers** in "Modify" lines are those of the file as the previous task left it (the current tree for a file
  no earlier Plan H task touched). Every replacement quotes the exact current text; a step that replaces a whole file
  says so and gives the whole new file.
- **Counts.** Today (`e2e0ed3`) the dev gate is `816 passed, 104 skipped` and the live gate `899 passed, 21
  skipped` (83 live tests). Task 1 Step 1a records both before any change; if either differs, every expected count
  below shifts by the same difference and the report says so. A task whose own counts differ from the plan's by
  tests the task added beyond the plan reports the difference and why.
- **Slow live tests.** The DoD-3 heartbeat tests and the stress test take 15-40 s each (about 2.5 minutes together);
  they carry `@pytest.mark.slow_live` so a developer can deselect them while iterating
  (`-m "not slow_live"`), and `scripts/check.py --profile test` runs them like every other test (it passes no `-m`;
  a Task 1 test pins that), because they are the DoD evidence.

## Review Focus

1. **Two jobs of one run claimed in the same instant by two workers, before any lease row exists** (an `investigate`
   and a `resume_input` arriving together): exactly one claims with fence 1, the other is deferred, and neither waits
   for ever. Pinned in Task 3 (`test_two_first_acquisitions_of_one_run_give_one_lease`, stepped: the first claim stays
   open until `pg_blocking_pids` shows the second claim's insert waiting on it).
2. **A renewal that meets the owner's own re-fence** (`mark_unknown` bumped the fence between the thread's read of the
   fence and its renewal) must retry, not declare the lease lost and cancel a job that is fine. Pinned in Task 5
   (`test_a_renewal_that_meets_its_own_refence_retries`) on the shared `Lease`.
3. **A handle minted near the end of a lease** must not outlive the lease, and a handle presented after the lease
   lapsed (no takeover yet) must be refused. Pinned in Task 3
   (`test_a_handle_is_capped_at_its_lease_and_bound_to_its_fence`) and Task 4
   (`test_a_handle_is_refused_after_its_fence_moves_and_after_its_lease_expires`).
4. **The heartbeat's database connection drops** (a database restart): renewal errors reopen the connection on the
   next tick and count as a loss only once the local deadline has passed; a connect that hangs gives up after 5 s.
   Pinned in Task 5 (`test_transient_errors_are_retried_until_the_deadline`).
5. **The sweeper un-claims a job whose owner is alive** (a reclaim racing a slow heartbeat): the job is only a
   wake-up, so the owner's fenced units keep working while its lease is live, and a second claimer is deferred by the
   lease, never let in. Pinned in Task 6 (`test_the_reclaim_leaves_a_live_lease_alone`) and by the R087 test in
   Task 3, whose deferred job meets the same lease.

## Rulings (the brief's 31, as this plan implements them)

The controller's brief decided these; executors do not re-litigate them. Each line says where the plan implements the
ruling and, where the plan had to refine one against the code, says how (all refinements are repeated under
"Rulings needing controller attention").

1. **Row locks in definers** — revision 0007 grants `app_definer` `upd(fence)` on `run_lease` (Task 2); erratum 45.
2. **Lease row creation** — the worker creates the row at its first acquisition (`owner ''`, `lease_until
   '-infinity'`, fence 0) and the first real fence is 1; free means `lease_until <= app.current_time()` (Task 3,
   `persistence.acquire_lease`). Refined: the lock comes first and the INSERT runs only when no row exists, because an
   `INSERT … ON CONFLICT DO NOTHING` waits for any in-progress update of the conflicting row (a renewal, a release),
   which would make a NOWAIT claim wait; erratum 46.
3. **Claim and lease are one transaction** — `persistence.claim_next` picks a job with `FOR UPDATE SKIP LOCKED`,
   acquires the lease in a savepoint with `FOR UPDATE NOWAIT`, and either claims the job or defers it (`available_at`
   to the live lease's `lease_until`, or `app.current_time() + 1 s` when the row was locked) and commits; the worker
   loop tries again, at most 16 deferrals per poll; a deferred job cannot be picked again in the same poll because its
   `available_at` moved past `app.current_time()` (Task 3).
4. **FOR UPDATE vs FOR SHARE** — FOR UPDATE: acquisition, renewal, release, `mark_unknown`; FOR SHARE first: every
   other writing unit (`persistence.fenced`) and every MCP definer (through `_resolve_handle`); `revoke_handles` takes
   FOR SHARE only to order against acquisition (Tasks 3, 4, 5).
5. **How the fence reaches a write** — `persistence.fenced(conn, lease)` after `set_tenant` (whose `set_config` takes
   no lock); `transition_run`, `freeze_proposal`, `append_event` keep their signatures (erratum 47); `mint_handle`
   stores the lease's fence and caps `expires_at` at `least(now + 60 s, lease_until)`; `_resolve_handle` takes
   `run_lease FOR SHARE` and refuses OC008 unless the handle's fence is current and the lease live; `mark_sent` and
   `record_outcome` take the raw handle first (erratum 48) (Tasks 3, 4).
6. **Post-SENT fence failure** — a stale fence is OC008 → `HandleRejected`; before SENT it stays the
   `INVALID_HANDLE` envelope; after SENT `HandleRejected` is already one of `_POST_SENT_REFUSALS` (it subclasses
   `PersistenceError`), so the answer is `outcome`/`UNKNOWN`; a live test proves both sides (Task 4).
7. **`resolve_invocation`'s fence** — implemented in `_resolve_handle` (Task 4); T15's R027 exercises it end to end.
8. **`revoke_handles(run_id, fence)`** — revokes the run's live handles minted under a fence ≤ `p_fence`, never refuses,
   takes `run_lease FOR SHARE` first; Python passes the lease's fence (Tasks 3, 4); erratum 55.
9. **`mark_unknown(run_id, fence)`** — `run_lease FOR UPDATE`; OC003 unless the fence is current and the lease live;
   bumps to `p_fence + 1`; revokes handles ≤ `p_fence`; returns `TABLE (run_state text, new_fence bigint)`
   (`persistence.Unknown(state, fence)`); the worker hands the new fence to its `Lease`; the transport-failure branch
   still re-queues (Task 4); erratum 54.
10. **Re-fence hand-off** — one `Lease` with a `threading.Lock`; the worker brackets `mark_unknown` with
    `begin_refence()` / `end_refence(new)`; a renewal that meets another fence while a re-fence is pending, or after
    the shared fence changed, retries; only a mismatch against the current, settled fence is a loss (Tasks 3, 5).
11. **Reclaim** — `ops_sweeper.leases.reclaim` (direct grants, `sweeper_all` on `jobs`, `sel` on `run_lease`) un-claims
    claimed, unfinished run jobs whose lease is not live, every tick; no recover job, no permit work, no wake-up sweep
    (Task 6); erratum 49.
12. **`model_permit`** — revision 0007 creates it (slot 1 seeded; worker `sel, upd(all)`, nobody else; erratum 50);
    `persistence.take_model_permit` / `release_model_permit`; `ops_worker.permit.model_permit` polls with 0.25 s
    doubling to 2 s plus jitter while `lease.check()` passes (the back-off sleep is a lease effect), holds it around
    the draft call, releases in `finally` exactly the slot a take returned (take and release are database units and
    are never cancelled; review round 1, I2); TTL 65 s (Tasks 2, 5); the "hold until idle" rule is a debt line → T19.
13. **Global queue bound** — `app.queued_runs_total()` (api only; Task 2), `OPS_GLOBAL_QUEUE_LIMIT` (default 100,
    1-100000; Task 1), checked after the tenant quota, same unrecorded 429 with `Retry-After: 5` (Task 6); soft by
    the number of concurrent admissions (comment, runbook); erratum 51 replaces erratum 39's forward reference.
14. **Lock order** — `ops_core.locking.LOCK_ORDER`, `OWN_UNIT`, `NEVER_LOCKED` and the documented transactions
    `OBSERVED_UNITS`/`OWN_UNITS`, checked by `tests/plan_h/test_locking.py` (Task 1); the existing transactions (FS
    §3.15) all follow it once the new units are placed; erratum 52.
15. **Asset-guard lock** — placed in the order (Task 1); a live test creates, as superuser inside a rolled-back
    transaction, a definer owned by `app_definer` that calls `pg_advisory_xact_lock(hashtextextended(…, 0))` and
    proves the lock was taken under `app_definer` (Task 2). Taking it in `freeze_proposal`/`grant_execution` is T21's.
16. **Heartbeat thread** — `ops_worker.heartbeat.Heartbeat`: one daemon thread, its own synchronous autocommit
    connection as `worker` from `settings.app_postgres(Role.WORKER).conninfo()` (which pins `-c timezone=UTC`), with
    `connect_timeout=5`, TCP keepalives, `SET lock_timeout = '5s'` and `SET statement_timeout = '5s'` (review round
    2, m3), idle while no lease is held, lazy reconnect (Task 5).
17. **Liveness and compute gates** — the loop's `keep_stamping` task stamps a monotonic instant every second; the
    thread renews only while the stamp is younger than `OPS_LOOP_STALL_SECONDS` (28) and the lease has been held less
    than `OPS_COMPUTE_BUDGET_SECONDS` (90); either gate closing is a loss (Task 5). Budget accounting is T29's.
18. **Local monotonic deadline** — `deadline = monotonic before the acquiring or renewing statement + lease − 5 s`;
    `Lease.check()` raises `LeaseLost` past it and runs before every fenced unit, and `Lease.effect` runs the same
    check before every MCP call and model call (Tasks 3, 5).
19. **Renewal failure** (amended by the controller in review round 1, B1) — only effects are cancelled: every MCP call,
    model call and permit back-off sleep runs through `Lease.effect` as a child task registered on the lease, and on
    a loss the thread marks the lease lost and cancels just those (`Lease.cancel_effects`, through
    `loop.call_soon_threadsafe`); a cancelled effect surfaces as `LeaseLost`. A database unit is never cancelled (a
    cancellation inside psycopg's BEGIN would leave the loop connection in a transaction for good); a loss during one
    is caught by the next `fenced()`/`check()`. The loop then revokes the job's handles with `revoke_handles(run_id,
    fence)` and un-claims the job (`available_at` now) in one unit, with no run transition, after `abandon` has
    checked that the connection is idle (if not, it closes it and the loop exits non-zero for the supervisor to
    restart); the permit is released in `finally`. The job's next owner fails a run it finds in RETRIEVING or
    DRAFTING (`interrupted; the run was not resumed`; resuming it is T20's, review round 3, I1). A unit's lock wait is
    bounded by the loop connection's 10 s `lock_timeout` (`main.LOOP_LOCK_TIMEOUT`, review round 2, m1) (Tasks 3, 5);
    erratum 57.
20. **DoD 3** — validated settings with the exact checks `2 × heartbeat + 6 < lease` (the 5 s deadline margin and the
    thread's 1 s tick; review round 1, I5), `stall < lease + heartbeat`, `budget ≥ lease` (Task 1); scaled unit tests
    with a fake clock and renewer; live tests at the real defaults: a
    25 s `time.sleep` inside the draft call, a 35 s fake drafter, and a forced renewal failure (expire, then take the
    lease from a second `worker` connection) that cancels a never-answering MCP call and revokes its handle (Task 5).
21. **DoD 1-2** — stepped two-connection interleavings with `pg_blocking_pids` and the stress test (8 connections,
    3 runs, 20 s, acquire/renew/fenced writes/mint/revoke/`mark_unknown`/reclaim; zero 40P01, zero 55P03 under a
    10 s `lock_timeout`, fences never decrease, stale writes never land after newer ones) (Tasks 3, 6). Refined: the
    in-flight variant's waiting acquisition uses `acquire_lease(wait=True)`, a form only the tests use (the claim path
    is NOWAIT by ruling 3). Review round 1 (I3, I4): a waiting acquisition's lock wait past `lock_timeout` raises
    55P03 (counted, must be zero) instead of returning Busy; one stressed run is EXECUTING with a grant, so
    `mark_unknown` re-fences commit under load; a monitor checks at every sample that fences only increase and that
    at most one actor's own Lease of a run passes its local check, that actor owning the run's live row at its fence
    (review round 2, N3). `PURGE_ORDER` gains the lease row and the permit reset (Task 2).
22. **Fault factory** — `Faults` keeps its shape, gains `seconds` (for `timeout_before_accept` only) and the BS:405
    mapping `faults.BS405`; incident-sim implements `timeout_before_accept`, `rate_limit`, `malformed_response`,
    `receipt_hash_mismatch`, `delay_receipt`; the API implements `lose_after_commit` and receives `faults` from its
    store factory (Task 7); erratum 56.
23. **Checkpoints** — untouched (T20; R021 is T38/M15).
24. **Bounded retries** — T22 (debt line, TODOs reworded); each re-queue releases the lease (Task 3).
25. **Pools and reconnects** — none; only the heartbeat connection reconnects; the `persistence` and API
    `lock_timeout` TODOs move to T30 (Tasks 3, 6).
26. **One compute lease per requester** — out of scope → T29 (debt line).
27. **`jobs.type`** — revision 0007's `jobs_type_check` names the eight types (Task 2); the api-only-`resume_input`
    restriction stays a debt line → T22.
28. **Release** — `persistence.release_lease`: `FOR UPDATE`, owner and fence must match, revoke handles ≤ fence,
    finish or re-queue the job, `lease_until = '-infinity'`, owner and fence kept (Task 3).
29. **Worker-side `runs` locks** — stay, after `fenced` (run_lease before runs) (Task 3).
30. **Side debts** — only the `testclock` revision's grantee tuples are frozen (Task 2); the rest keep their owners.
31. **Migration** — one revision, `0007_leases_fences` (Tasks 2 and 4); downgrade restores 0006 exactly, proved live by
    comparing `pg_proc.prosrc` with the applied revisions' bodies (Task 4).

### Rulings needing controller attention

None of the 31 is impossible against the code. These refinements keep each ruling's intent and are flagged so the
controller can overrule them before execution:

- **(a) Ruling 2's statement order.** The ruling lists `INSERT … ON CONFLICT DO NOTHING` first, then `SELECT … FOR
  UPDATE NOWAIT`. PostgreSQL's unique check makes an inserter wait for any in-progress transaction that is updating
  or deleting the conflicting row, so on an existing lease row the INSERT would wait for a renewal, a release or
  another claim, and the claim would no longer be NOWAIT. The plan locks first (`FOR UPDATE NOWAIT`) and inserts only
  when the row is absent (then locks again). The only remaining wait is two first acquisitions of one run racing
  their INSERTs, which waits for the other claim's short transaction (Review Focus 1). Task 3's
  `test_a_locked_lease_is_busy_at_once` measures that a claim meeting an in-flight renewal returns Busy in under 1 s.
- **(b) Ruling 21's "B's acquisition waits".** The claim's acquisition is NOWAIT (ruling 3), so it never waits. The
  plan gives `acquire_lease` a `wait=False` parameter; only the interleaving and stress tests pass `True`, and the
  worker never does. Without it neither "proved with `pg_blocking_pids`" nor a deadlock-provoking stress mix exists.
- **(c) Ruling 5's statement shape.** The ruling's `SELECT 1 … AND lease_until > app.current_time() FOR SHARE`
  evaluates the comparison before a lock wait and re-checks it afterwards only if the row changed, so a lease that
  lapses while the unit waits on a renewal that then rolls back would pass (the brief's own clock constraint forbids
  that). The plan uses `WITH l AS MATERIALIZED (SELECT … FOR SHARE) SELECT … app.current_time() … FROM l`: the same
  predicate, evaluated after the lock. Task 3's `test_r107_expiry_is_compared_after_the_lock` fails with the
  ruling's literal form and passes with this one.
- **(d) Ruling 31's function list.** `resolve_invocation` and `lookup_action` are not re-created: their bodies only
  call `_resolve_handle`, whose new body (same signature) carries the fence check, so re-creating them would change
  nothing. `grant_execution` is re-created only to reword its `TODO(T13)` comment, which is part of the stored body.
- **(e) Ruling 22's `delay_receipt`.** Implemented as a lookup-side fault: the POST commits untouched and the next
  `count` lookups of a committed key answer 404. The arm count is therefore the lookups count, and `seconds` is the
  only new parameter (for `timeout_before_accept`).
- **(f) Ruling 10's hand-off window.** Between `mark_unknown`'s commit and `refence(new)` a renewal can read the old
  fence, meet the new one and see an unchanged shared fence. The plan adds a "re-fence pending" flag set before the
  call (`Lease.begin_refence()`) and cleared with the new fence (`end_refence(new)`); a mismatch while it is set is a
  retry.
- **(g) Ruling 9's two OC003 causes.** `mark_unknown` refuses OC003 for a stale fence and for a run that is not
  EXECUTING. The worker tells them apart without parsing messages: after an OC003 it runs `fenced()` in a fresh unit;
  a stale fence raises `LeaseLost` there, otherwise the refusal was the run's state and is re-raised.
- **(h) Ruling 19 does not cover a crashed handler** (an exception that is not a lease loss). The plan keeps today's
  behaviour: the job stays claimed, the heartbeat stops renewing it, the lease lapses within 30 s, the sweeper
  reclaims the job and a worker runs it again (no retry bound: debt line → T22). Its handles die with the lease
  (capped expiry, fence check).
- **(i) Task shape.** The brief's eight tasks are kept with two moves: the fault work is all in Task 7 (Task 1 carries
  settings and the lock order only, so no kind is added to `FaultKind` before a hot path consumes it), and the worker
  is integrated in three steps (Task 3 lease and fences, Task 4 `mark_unknown`'s re-fence with the fenced definers,
  Task 5 thread, cancellation and permit), because the definers cannot check a fence before the worker holds leases
  without turning the live suite red between tasks. R019's test lives in Task 6 with the reclaim it needs.

## Declared debt and errata

### Debt list (committed in Task 1 Step 1c, before coding)

Appended to `SESSION_STATE.md` as a new section `## Plan H debt list (T13; committed before coding) [R6-B7]`
immediately after the `## Plan G debt list …` section (before `## Environment (observed)`), verbatim:

```markdown
Allowed shortcuts in T13, each with its owning task:
- the model permit is released when the draft call ends or is cancelled, and by its 65 s TTL; SA:205's "hold the
  permit until `ollama ps` shows idle" waits on T02's cancellation measurement, and today's only route is the fake
  drafter → T19;
- the heartbeat's 90 s compute gate counts one lease's hold time; accounting into `runs.budget_used` across jobs, the
  human-wait exclusion (BS:556) and R062's caps → T29;
- the execute job's transport-failure and `GRANT_DEFERRED` re-queues have no retry bound (the run is APPROVED or
  EXECUTING, which the worker may not move, SA:451) → T22;
- the worker's transport failure still re-queues instead of taking AM-13's timeout path (`mark_unknown` on a
  transport timeout, R109; erratum 14 stands) → T22;
- the reclaim inserts no `recover` job and lost wake-ups are not re-enqueued → T22 (recover), T14 (wake-ups);
- a deferred job waits for the busy lease's `lease_until` even when the holder releases early (no wake-up on
  release) → T14;
- a handler that crashes (an exception other than a lease loss) keeps its job claimed until its lease lapses and the
  sweeper reclaims it, and then runs again without a bound → T22;
- an investigate run interrupted in RETRIEVING or DRAFTING (a lost lease, a crash, a lock timeout) is failed by its
  job's next owner (`interrupted; the run was not resumed`) instead of resumed from where it stopped → T20 (the
  graph's node resume);
- the asset-guard advisory lock is placed in the lock order and proved callable by `app_definer`, but
  `freeze_proposal` and `grant_execution` do not take it yet → T21;
- checkpoints are untouched (`runs.checkpoint_id` under the fence) → T20; fenced `put`/`put_writes` (R021) → T38;
- one active compute lease per requester (BS:548) is not enforced (one worker replica runs one job at a time) → T29;
- no connection pool and no reconnect except the heartbeat's connection; a lost loop connection still ends the
  process; the API reply unit's per-unit `lock_timeout` → T30;
- `api` may still INSERT a job of any of the eight types (the CHECK bounds the vocabulary, not the role) → T22;
- the global queue bound is soft by the number of concurrent admissions (counted, then created, across tenants) →
  T29;
- mcp-write handles the five new incident-sim faults only through today's `classify` (rate limit, timeout and a
  malformed body become UNKNOWN, a foreign receipt hash CONFLICT, a hidden receipt a 404 on lookup) → T22/T47;
- the shared connect-and-assert helper for the servers, a closer that raises during startup cleanup and the token
  verifier's injected-fetch exception → T30; the untested definer branches (Plan E list) → T22; the pre-SENT
  `STALE_RUN`/`HASH_MISMATCH` envelopes → T47;
- the worker still polls every 0.5 s and claims per tenant → T14 (wake-ups);
- a handle's expiry is capped at the lease's end when it is minted and a renewal does not extend it, so a handle lives
  20-30 s in practice and an MCP call slower than that ends with the handle refused, not a timeout (per-call minting
  under the renewed lease) → T22/T47;
- the global queue count costs one scan per tenant inside every run admission → T29;
- the dev database stays at revision 0005 until the owner migrates it (0006 and 0007 pending); until then the API,
  the sweeper, the worker and mcp-write refuse to start on it → owner input.
```

### Errata proposed to the owner (numbered on from Plan G's 44)

The spec text stays authoritative until the owner decides; each line names the text it amends.

45. **SA:418** (AM-20.2 `run_lease`): `app_definer` holds `sel, upd(fence)`: a row lock needs UPDATE on a column
    (Plan E ruling 23) and `mark_unknown` writes the fence (ruling 1).
46. **SA:174** (acquisition): the worker creates the lease row at the run's first acquisition (owner `''`,
    `lease_until '-infinity'`, fence 0, so the first real fence is 1); the row is locked first and inserted only when
    absent; a lease is free when `lease_until <= app.current_time()` (a released lease and an exact instant count as
    free) (ruling 2).
47. **SA:453** (`freeze_proposal` locks `run_lease FOR SHARE`), and likewise `transition_run` and `append_event` when
    the worker calls them: the worker's unit takes the share lock and checks the fence before the call; the
    functions keep their signatures (ruling 5).
48. **SA:463/SA:464**: `mark_sent(raw_handle, action_id)` and `record_outcome(raw_handle, action_id, outcome, doc)`;
    the handle carries the fence; a stale fence or a lapsed lease is the handle refusal OC008 (rulings 5, 6).
49. **SA:471** (`reclaim_leases()`): the sweeper's routine with direct grants (erratum 26 precedent), not a definer;
    it un-claims claimed, unfinished run jobs whose run lease is not live, takes no `run_lease` lock, inserts no
    `recover` job and does no `model_permit` work (an expired permit is free by the same comparison) (ruling 11).
50. **SA:432** (`model_permit`): columns `slot smallint PK (≥ 1), holder, run_id, leased_until`; one seeded slot;
    `worker` `sel, upd(all)`; no sweeper cell (an UPDATE with a WHERE needs SELECT, erratum 25, and expiry is the
    release) (ruling 12).
51. **BS:550** (replaces erratum 39's "the global bound moves to T13"): QUEUED runs are bounded per tenant
    (`OPS_TENANT_QUEUE_QUOTA`, 100) and globally (`OPS_GLOBAL_QUEUE_LIMIT`, 100) through the definer
    `queued_runs_total()` callable by `api` only; the global bound is soft by the number of concurrent admissions; a
    full queue answers 429 with `Retry-After` and writes nothing (ruling 13).
52. **SA:188** (the lock order), extended: idempotency advisory lock → asset-guard advisory lock → `jobs` (claim,
    SKIP LOCKED only) → `run_lease` → `runs` → `messages` → `drafts` → `proposals` → `decisions` → `memberships` →
    `execution_grant` → `action_attempt` → `action_attempt_state` → `operator_resolutions` → `invocation_context` →
    `run_state_history` → `events` → `outbox` → `jobs` (finish, re-queue or hand-back of the transaction's own job)
    → `idempotency_request`; `SKIP LOCKED` and `NOWAIT` never wait and may appear anywhere; a fresh-row INSERT
    never waits on its own table but its foreign-key check takes FOR KEY SHARE on the parent row, so it ranks at the
    parent's position;
    `model_permit`, `sessions`, `login_state`, `logout_jti`, `test_clock`, `tenants`, `run_directory` are locked only
    in their own units (the sweeper's purge adds `idempotency_request`), `conversations` and `transitions` never
    (ruling 14).
53. **SA:459** (`resolve_invocation` locks "`invocation_context` FOR SHARE → `run_lease` FOR SHARE"): the context row
    is read without a lock (revocation is belt and braces once the fence is compared); `run_lease` FOR SHARE is the
    one lock, taken in `_resolve_handle`, which `grant_execution`, `lookup_action`, `mark_sent` and `record_outcome`
    share (ruling 5).
54. **SA:467** (`mark_unknown(run_id, fence)`): refuses OC003 unless the caller's fence is current and its lease live,
    bumps the fence to `fence + 1`, revokes the handles minted under the old fence and returns
    `(run_state, new_fence)` (ruling 9).
55. **SA:472** (`revoke_handles(run_id, fence)`): revokes the run's live handles minted under a fence ≤ the given one
    and never refuses a stale fence (revocation only removes authority) (ruling 8).
56. **BS:405** (the nine faults): `reject_next` = definitive no-commit failure, `drop_before_commit` = transient
    unavailable, `lose_after_commit` = response loss after commit, `timeout_before_accept`, `rate_limit`,
    `malformed_response`, `receipt_hash_mismatch` (mismatching receipt hash), `delay_receipt` (delayed receipt
    visibility: the next `count` lookups of a committed key answer 404); concurrent same-key submission is a harness
    behaviour (two submissions raced with `asyncio.gather`, R047), not a hook (ruling 22).
57. **SA:196-198** ("when renewal fails, the worker … exits the run"): exiting the run means cancelling the job's
    effects in flight (MCP and model calls; no database unit is interrupted), revoking the job's handles and handing
    the job back (un-claimed, claimable at once) with no run transition; the job's next owner finds the run in
    RETRIEVING or DRAFTING and fails it (`interrupted; the run was not resumed`), because nothing resumes a run before
    T20 (ruling 19 as amended in review rounds 1 and 3).

## File structure

- `core/src/ops_core/settings.py` (Task 1): `LeaseSettings`, `leases()`, `check_leases()`;
  `AdmissionSettings.global_queue_limit`.
- `core/src/ops_core/locking.py` (new, Task 1; Task 2 edits `NOT_YET_CREATED`): the lock order as data.
- `migrations/app/versions/0007_leases_fences.py` (new, Task 2; extended in Task 4): `model_permit`, the run_lease
  cell, the `jobs.type` CHECK, `queued_runs_total`, then the fenced definers and the exact downgrade.
- `migrations/app/versions/tc_0001_test_clock.py` (Task 2): frozen grantee tuples.
- `core/src/ops_core/privileges.py` (Tasks 2, 4): the `model_permit` row, the `run_lease` cell, `NO_RLS`,
  `DEFINER_FUNCTIONS`.
- `core/src/ops_core/lease.py` (new, Task 3; `renew` in Task 5): `Lease`, `LeaseLost`, `Busy`, `RELEASED`, the lock
  statements, `Renewal`, `renew`.
- `core/src/ops_core/persistence.py` (Tasks 3, 4, 5, 6): the lease, claim, fence, release, permit and queue helpers;
  the `mark_sent`/`record_outcome`/`mark_unknown`/`revoke_handles`/`mint_handle` signatures.
- `worker/src/ops_worker/handlers.py` (whole file in Task 3; edits in Tasks 4, 5), `main.py` (whole file in Task 3;
  edits in Task 5), `heartbeat.py` and `permit.py` (new, Task 5), `drafting.py` (Task 5).
- `mcp-write/src/ops_mcp_write/execution.py` (Task 4), `server.py` (Task 4: the 0007 guard).
- `sweeper/src/ops_sweeper/leases.py` (new, Task 6), `main.py` (Task 6).
- `api/src/ops_api/store.py`, `idempotency.py`, `app.py` (Tasks 6, 7); `tests/plan_g/fakes.py` (Task 6).
- `core/src/ops_core/testing/faults.py`, `incident-sim/src/ops_incident_sim/app.py` (Task 7).
- `tests/e2e/conftest.py` (Tasks 2, 3, 4): `PURGE_ORDER`, `lease_for`, `stage_lease`, `expire_lease`, `backend_pid`,
  `wait_until_blocked`.
- `tests/plan_b/test_evidence.py` (Task 3): the `reports/leases` root.
- Documentation (Task 8): `handoff/*`, `SESSION_STATE.md`, `STATUS.md`, `docs/ARCHITECTURE.md`,
  `docs/runbooks/leases.md` (new), `docs/PROJECT_HISTORY.md`, `worker/README.md`, `sweeper/README.md`.

## Task overview

- **Task 1:** the debt list; `LeaseSettings` and the global queue limit; `core/locking.py`; `tests/plan_h` and the
  `slow_live` marker. Tests: `test_settings_leases.py` 11, `test_locking.py` 30. Dev gate after: 857 passed, 104
  skipped (no live change; the live gate is not run).
- **Task 2:** revision 0007 (schema, cells, CHECK, `queued_runs_total`), the matrix, `PURGE_ORDER`, the frozen
  testclock tuples. Tests: `test_migration_0007.py` 5, `test_transitions_table.py` +1 (parametrised); live
  `test_migration_0007_live.py` 5. Dev 863/109, live 951/21.
- **Task 3:** `core/lease.py`; the lease helpers in `persistence`; the worker claims under a lease, fences every
  writing unit, runs every MCP and model call as a cancellable lease effect, releases with the job and abandons on
  loss; the minting tests take leases. Tests: `test_lease.py` 12, `test_worker_units.py` 8; live
  `test_leases_live.py` 10. Dev 883/119, live 981/21.
- **Task 4:** the fenced definers in 0007; `mark_sent`/`record_outcome` with the handle; `mark_unknown`'s new fence
  handed to the lease; mcp-write; the definer tests. Tests: `test_migration_0007.py` +3, `test_worker_units.py` +2,
  `test_write_path_fence.py` 2; live `test_fenced_definers_live.py` 5. Dev 890/124, live 993/21.
- **Task 5:** `lease.renew`, the heartbeat thread, the liveness ticker, cancelling effects on loss, the model permit,
  the slow fake drafter. Tests: `test_heartbeat.py` 10, `test_permit.py` 6, `test_worker_units.py` +3; live
  `test_heartbeat_live.py` 4 (three `slow_live`). Dev 909/128, live 1016/21.
- **Task 6:** the sweeper's reclaim; the stress test and R019; the global queue bound in the API. Tests:
  `test_reclaim.py` 2, `test_global_queue.py` 3; live `test_lease_stress_live.py` 3 (one `slow_live`),
  `test_admission_live.py` +1. Dev 914/132, live 1025/21.
- **Task 7:** the fault factory: five incident-sim kinds, `lose_after_commit` in the API, faults from the store
  factory. Tests: `test_faults_t13.py` 4, `test_incident_sim_faults.py` 7, `test_api_faults.py` 5; live
  `test_admission_live.py` +1. Dev 930/133, live 1042/21.
- **Task 8:** handoff records, acceptance rows, errata 45-57, runbook, history, READMEs, final gates. No tests.

The arithmetic, once: dev passed 816 + 41 (Task 1: 11 + 30) = 857, + 6 (Task 2: 5 + 1 parametrised revision) =
863, + 20 (Task 3: 12 + 8) = 883, + 7 (Task 4: 3 + 2 + 2) = 890, + 19 (Task 5: 10 + 6 + 3) = 909, + 5 (Task 6: 2 +
3) = 914, + 16 (Task 7: 4 + 7 + 5) = 930; dev skipped 104, + 5 = 109, + 10 = 119, + 5 = 124, + 4 = 128, + 4 = 132, + 1 =
133. The live gate's passed count is the dev count plus the live tests (83 today; 88, 98, 103, 107, 111, 112 after
Tasks 2-7), so 951, 981, 993, 1016, 1025, 1042, always with 21 skipped.

---

### Task 1: Debt before code — lease settings, the global queue limit and the published lock order

**Files:**
- Modify: `SESSION_STATE.md` (new debt section after `## Plan G debt list …`), `pyproject.toml:48-51` (`testpaths`),
  `:56-58` (`markers`), `core/src/ops_core/settings.py:293` (`AdmissionSettings`), `:304-310` (`admission`),
  `:313-314` (insert before `class Urls`)
- Create: `core/src/ops_core/locking.py`, `tests/plan_h/__init__.py`, `tests/plan_h/test_settings_leases.py`,
  `tests/plan_h/test_locking.py`

**Requirements:** R107 (the published order), R088 (the validated lease, heartbeat, stall and budget values), the
BS:550 global bound's setting; brief rulings 13, 14, 20.

**Interfaces:**
- Consumes: `ops_core.settings._bounded(name, default, low, high)`, `SettingsError`; `ops_core.privileges.GRANTS`.
- Produces: `ops_core.settings.LeaseSettings(lease_seconds=30, heartbeat_seconds=10, loop_stall_seconds=28,
  compute_budget_seconds=90)` (frozen dataclass), `check_leases(chosen: LeaseSettings) -> None`,
  `leases() -> LeaseSettings`; `AdmissionSettings.global_queue_limit: int = 100`.
- Produces: `ops_core.locking.LOCK_ORDER: tuple[str, ...]`, `OWN_UNIT`, `NEVER_LOCKED`, `NOT_YET_CREATED`
  (frozensets of table names), `OBSERVED_UNITS`, `OWN_UNITS` (`dict[str, tuple[str, ...]]`),
  `table_of(entry: str) -> str | None`, `rank(entry: str) -> int`, `follows_order(entries: Sequence[str]) -> bool`.

- [ ] **Step 1a: Record both baselines**

Run `PYTHONUTF8=1 uv run python scripts/check.py` → `CHECK: GREEN` with pytest `816 passed, 104 skipped`; with the
dev stack up and `uv run python scripts/skeleton.py status` showing every process down, run
`PYTHONUTF8=1 uv run python scripts/check.py --profile test` → `CHECK: GREEN` with `899 passed, 21 skipped`, then
`git checkout -- reports/bootstrap reports/skeleton reports/auth reports/admission`. Record both lines in the report
(Global Constraints, "Counts"). A gate that is not GREEN stops the plan here, before anything is committed.

- [ ] **Step 1b: Record the base**

Run `git rev-parse --short HEAD` and write the hash it prints as `BASE=<hash>` in the report and in the SDD ledger
(`.superpowers/sdd/2026-10-15-first-slice-h-leases-fences-heartbeat/progress.md`). Task 8's commit span is
`<base>..<last>`, so a commit that revises this plan before execution never falls inside the executed range.

- [ ] **Step 1c: Commit the debt list (before any code)**

Append the debt-list block from "Declared debt and errata" to `SESSION_STATE.md` as the section
`## Plan H debt list (T13; committed before coding) [R6-B7]`, immediately after the `## Plan G debt list …` section
and before `## Environment (observed)`. Then:

```bash
git add SESSION_STATE.md
git commit -m "docs: declare Plan H's shortcuts before coding (T13 debt list)"
```

- [ ] **Step 2: Put `tests/plan_h` on the test path and register the slow marker**

In `pyproject.toml` replace

```toml
testpaths = [
  "tests/plan_a", "tests/plan_b", "tests/plan_c", "tests/plan_d", "tests/plan_e", "tests/plan_f", "tests/plan_g",
  "tests/e2e",
]
```

with

```toml
testpaths = [
  "tests/plan_a", "tests/plan_b", "tests/plan_c", "tests/plan_d", "tests/plan_e", "tests/plan_f", "tests/plan_g",
  "tests/plan_h", "tests/e2e",
]
```

and replace

```toml
markers = [
  "sweeper_stamps: the module's skeleton sweeper stamps memberships.synced_at; the autouse fixture must not",
]
```

with

```toml
markers = [
  "sweeper_stamps: the module's skeleton sweeper stamps memberships.synced_at; the autouse fixture must not",
  "slow_live: a DoD timing test of 15-40 s (Plan H); deselect with -m 'not slow_live' while iterating, never in a gate",
]
```

Create `tests/plan_h/__init__.py` as an empty file.

- [ ] **Step 3: Write the failing settings test**

Create `tests/plan_h/test_settings_leases.py`:

```python
"""The T13 settings (Plan H rulings 13 and 20): BUILD_SPEC §17's lease and heartbeat (30 s / 10 s), the stall gate
above DoD 3's 25 s blocked loop, the 90 s compute budget and the 100-run global queue bound, each read, bounded and
checked together (BS:542 "validated configuration").

Catches: a heartbeat that leaves room for only one renewal per lease once the 5 s local-deadline margin and the
thread's 1 s tick are counted (one slow renewal would lose it), a stall gate
so long that a dead loop keeps a run, a budget shorter than one lease (every job would end before its first renewal),
a bound that names the value instead of the rule, and a slow live test that the gate silently stops running.
"""

import tomllib
from pathlib import Path

import pytest
from ops_core import settings
from ops_core.settings import LeaseSettings, SettingsError

ROOT = Path(__file__).resolve().parents[2]
NAMES = (
    "OPS_LEASE_SECONDS",
    "OPS_HEARTBEAT_SECONDS",
    "OPS_LOOP_STALL_SECONDS",
    "OPS_COMPUTE_BUDGET_SECONDS",
    "OPS_GLOBAL_QUEUE_LIMIT",
)


@pytest.fixture(autouse=True)
def clean(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in NAMES:
        monkeypatch.delenv(name, raising=False)


def test_lease_defaults_are_the_spec_values() -> None:
    assert settings.leases() == LeaseSettings(
        lease_seconds=30, heartbeat_seconds=10, loop_stall_seconds=28, compute_budget_seconds=90
    )
    assert LeaseSettings() == settings.leases()  # what a test's Deps uses when it passes nothing
    assert settings.leases().loop_stall_seconds > 25  # DoD 3: a 25 s blocked loop must not close the gate


@pytest.mark.parametrize(
    ("name", "low", "high", "with_low", "with_high"),
    [
        (
            "OPS_LEASE_SECONDS",
            10,
            900,
            {"OPS_HEARTBEAT_SECONDS": "1", "OPS_LOOP_STALL_SECONDS": "5", "OPS_COMPUTE_BUDGET_SECONDS": "10"},
            {"OPS_COMPUTE_BUDGET_SECONDS": "900"},
        ),
        ("OPS_HEARTBEAT_SECONDS", 1, 300, {}, {"OPS_LEASE_SECONDS": "900", "OPS_COMPUTE_BUDGET_SECONDS": "900"}),
        ("OPS_LOOP_STALL_SECONDS", 2, 900, {}, {"OPS_LEASE_SECONDS": "900", "OPS_COMPUTE_BUDGET_SECONDS": "900"}),
        (
            "OPS_COMPUTE_BUDGET_SECONDS",
            10,
            3600,
            {"OPS_LEASE_SECONDS": "10", "OPS_HEARTBEAT_SECONDS": "1", "OPS_LOOP_STALL_SECONDS": "5"},
            {},
        ),
    ],
)
def test_each_lease_variable_is_read_and_bounded(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    low: int,
    high: int,
    with_low: dict[str, str],
    with_high: dict[str, str],
) -> None:
    field = name.removeprefix("OPS_").lower()
    for value, companions in ((low, with_low), (high, with_high)):
        for other in NAMES:
            monkeypatch.delenv(other, raising=False)
        for other, raw in companions.items():
            monkeypatch.setenv(other, raw)
        monkeypatch.setenv(name, str(value))
        assert getattr(settings.leases(), field) == value
        monkeypatch.setenv(name, str(value - 1 if value == low else value + 1))
        with pytest.raises(SettingsError) as refused:
            settings.leases()
        assert str(refused.value) == f"{name} must be between {low} and {high}"  # the bounds, never the value


@pytest.mark.parametrize(
    ("name", "raw", "rule"),
    [
        ("OPS_HEARTBEAT_SECONDS", "12", "less than half of (OPS_LEASE_SECONDS - 6)"),
        ("OPS_LOOP_STALL_SECONDS", "40", "less than OPS_LEASE_SECONDS plus OPS_HEARTBEAT_SECONDS"),
        ("OPS_COMPUTE_BUDGET_SECONDS", "20", "at least OPS_LEASE_SECONDS"),
    ],
)
def test_unsafe_combinations_are_refused(monkeypatch: pytest.MonkeyPatch, name: str, raw: str, rule: str) -> None:
    monkeypatch.setenv(name, raw)
    with pytest.raises(SettingsError) as refused:
        settings.leases()
    assert str(refused.value) == f"{name} must be {rule}"


def test_two_renewals_and_the_margins_fit_in_one_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review round 1, I5: the local deadline is the last renewal's start plus the lease minus 5 s (SA:195) and the
    thread looks once a second, so a lease must hold two heartbeats plus 6 s, or one slow renewal loses it."""
    monkeypatch.setenv("OPS_LEASE_SECONDS", "30")
    monkeypatch.setenv("OPS_HEARTBEAT_SECONDS", "10")
    assert settings.leases().heartbeat_seconds == 10  # 2 x 10 + 6 < 30
    monkeypatch.setenv("OPS_LEASE_SECONDS", "10")
    monkeypatch.setenv("OPS_HEARTBEAT_SECONDS", "4")
    monkeypatch.setenv("OPS_LOOP_STALL_SECONDS", "5")
    monkeypatch.setenv("OPS_COMPUTE_BUDGET_SECONDS", "10")
    with pytest.raises(SettingsError) as refused:  # 2 x 4 + 6 >= 10: the old "less than half" rule let this through
        settings.leases()
    assert str(refused.value) == "OPS_HEARTBEAT_SECONDS must be less than half of (OPS_LEASE_SECONDS - 6)"


def test_the_global_queue_limit_is_read_and_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    assert settings.admission().global_queue_limit == 100  # BS:550: "100 total initially"
    for good in (1, 100000):
        monkeypatch.setenv("OPS_GLOBAL_QUEUE_LIMIT", str(good))
        assert settings.admission().global_queue_limit == good
    for bad in (0, 100001):
        monkeypatch.setenv("OPS_GLOBAL_QUEUE_LIMIT", str(bad))
        with pytest.raises(SettingsError):
            settings.admission()


def test_the_slow_live_marker_is_registered_and_the_live_gate_runs_every_test() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert any(m.startswith("slow_live:") for m in config["tool"]["pytest"]["ini_options"]["markers"])
    steps = (ROOT / "scripts" / "check.py").read_text(encoding="utf-8")
    # check.py's pytest step selects nothing out: the slow DoD tests run in `--profile test` like every live test.
    assert '"-m", "pytest", "-q"]' in steps and "not slow_live" not in steps
```

Run: `uv run python -m pytest tests/plan_h/test_settings_leases.py -q`
Expected: `1 error in` (`ImportError: cannot import name 'LeaseSettings' from 'ops_core.settings'`).

- [ ] **Step 4: Add the lease settings and the global queue limit**

In `core/src/ops_core/settings.py`:

Edit 1 (old line 293), replace:

```python
    tenant_queue_quota: int = 100  # BS:550: queued work, as a per-tenant bound (ruling 18)
```

with:

```python
    tenant_queue_quota: int = 100  # BS:550: queued work, as a per-tenant bound (ruling 18)
    global_queue_limit: int = 100  # BS:550: "100 total" across tenants, checked after the quota (Plan H ruling 13)
```

Edit 2 (old lines 304-310), replace:

```python
def admission() -> AdmissionSettings:
    """`OPS_MAX_BODY_BYTES`, `OPS_IDEMPOTENCY_TTL_SECONDS` and `OPS_TENANT_QUEUE_QUOTA`, each bounded (ruling 27)."""
    return AdmissionSettings(
        max_body_bytes=_bounded("OPS_MAX_BODY_BYTES", 65536, 1024, 1048576),
        idempotency_ttl_seconds=_bounded("OPS_IDEMPOTENCY_TTL_SECONDS", 86400, 60, 604800),
        tenant_queue_quota=_bounded("OPS_TENANT_QUEUE_QUOTA", 100, 1, 10000),
    )
```

with:

```python
def admission() -> AdmissionSettings:
    """`OPS_MAX_BODY_BYTES`, `OPS_IDEMPOTENCY_TTL_SECONDS`, `OPS_TENANT_QUEUE_QUOTA` (Plan G ruling 27) and
    `OPS_GLOBAL_QUEUE_LIMIT` (Plan H ruling 13), each bounded."""
    return AdmissionSettings(
        max_body_bytes=_bounded("OPS_MAX_BODY_BYTES", 65536, 1024, 1048576),
        idempotency_ttl_seconds=_bounded("OPS_IDEMPOTENCY_TTL_SECONDS", 86400, 60, 604800),
        tenant_queue_quota=_bounded("OPS_TENANT_QUEUE_QUOTA", 100, 1, 10000),
        global_queue_limit=_bounded("OPS_GLOBAL_QUEUE_LIMIT", 100, 1, 100000),
    )
```

Edit 3 (old lines 313-314), replace:

```python
@dataclass(frozen=True)
class Urls:
```

with:

```python
@dataclass(frozen=True)
class LeaseSettings:
    """The run lease and its heartbeat (BS:557, SA:193-195) and the two renewal gates of T13 review note 4: the event
    loop's stall limit and the compute budget (BS:555), as validated configuration (BS:542, Plan H ruling 20)."""

    lease_seconds: int = 30  # BS:557
    heartbeat_seconds: int = 10  # BS:557
    loop_stall_seconds: int = 28  # above DoD 3's 25 s blocked loop, below a lease plus a heartbeat
    compute_budget_seconds: int = 90  # BS:555: active compute per run


# The worker stops starting effects 5 s before its lease ends (SA:195) and its heartbeat thread looks once a second.
RENEWAL_MARGIN_SECONDS = 6


def check_leases(chosen: LeaseSettings) -> None:
    """Refuse a combination that would lose healthy leases or keep dead ones (Plan H ruling 20, review round 1 I5).

    Two heartbeats plus RENEWAL_MARGIN_SECONDS must fit in one lease: the local deadline is the last renewal's start
    plus the lease minus 5 s, so with less room one failed or slow renewal passes it and a healthy job is abandoned.
    A loop silent for a whole lease plus a heartbeat is treated as dead, so the stall gate stays below that; a budget
    shorter than one lease would end every job before its first renewal.

    Raises:
        SettingsError: naming the rule, never a value.
    """
    if chosen.heartbeat_seconds * 2 + RENEWAL_MARGIN_SECONDS >= chosen.lease_seconds:
        raise SettingsError("OPS_HEARTBEAT_SECONDS must be less than half of (OPS_LEASE_SECONDS - 6)")
    if chosen.loop_stall_seconds >= chosen.lease_seconds + chosen.heartbeat_seconds:
        raise SettingsError("OPS_LOOP_STALL_SECONDS must be less than OPS_LEASE_SECONDS plus OPS_HEARTBEAT_SECONDS")
    if chosen.compute_budget_seconds < chosen.lease_seconds:
        raise SettingsError("OPS_COMPUTE_BUDGET_SECONDS must be at least OPS_LEASE_SECONDS")


def leases() -> LeaseSettings:
    """`OPS_LEASE_SECONDS`, `OPS_HEARTBEAT_SECONDS`, `OPS_LOOP_STALL_SECONDS` and `OPS_COMPUTE_BUDGET_SECONDS`, each
    bounded, then checked together (`check_leases`); the worker refuses to start on a refusal."""
    chosen = LeaseSettings(
        lease_seconds=_bounded("OPS_LEASE_SECONDS", 30, 10, 900),
        heartbeat_seconds=_bounded("OPS_HEARTBEAT_SECONDS", 10, 1, 300),
        loop_stall_seconds=_bounded("OPS_LOOP_STALL_SECONDS", 28, 2, 900),
        compute_budget_seconds=_bounded("OPS_COMPUTE_BUDGET_SECONDS", 90, 10, 3600),
    )
    check_leases(chosen)
    return chosen


@dataclass(frozen=True)
class Urls:
```

Run: `uv run python -m pytest tests/plan_h/test_settings_leases.py tests/plan_g/test_settings_admission.py -q`
Expected: `16 passed` (11 new; Plan G's 5 unchanged: its default comparison now includes the new field's default on
both sides).

- [ ] **Step 5: Write the failing lock-order test**

Create `tests/plan_h/test_locking.py`:

```python
"""The published lock order (AM-12 SA:188 as extended by Plan H ruling 14, erratum 52) and every transaction of the
system checked against it, without a database.

Catches: a table that exists in the privilege matrix but has no place in the order (a new table must be placed
before it ships), a table placed twice, an own-unit table (model_permit, sessions, ...) locked together with a run
table, a documented transaction that steps back in the order (the deadlock the stress test hunts for live), and an
order that no longer starts with the advisory locks or ends with the idempotency record.
"""

import pytest
from ops_core import locking, privileges


def test_every_table_is_placed_exactly_once() -> None:
    ordered = {locking.table_of(entry) for entry in locking.LOCK_ORDER} - {None}
    groups = (ordered, set(locking.OWN_UNIT), set(locking.NEVER_LOCKED))
    for table in privileges.GRANTS:
        assert sum(table in group for group in groups) == 1, table
    named = ordered | locking.OWN_UNIT | locking.NEVER_LOCKED
    assert named - set(privileges.GRANTS) <= locking.NOT_YET_CREATED, sorted(named - set(privileges.GRANTS))


def test_the_order_starts_with_the_advisory_locks_and_ends_with_the_record() -> None:
    assert locking.LOCK_ORDER[:2] == ("advisory:idempotency", "advisory:asset")  # erratum 37, then SA:189
    assert locking.LOCK_ORDER[-1] == "idempotency_request"  # SA:188: written last, before commit
    assert locking.rank("jobs:claim") < locking.rank("run_lease") < locking.rank("runs") < locking.rank("jobs:finish")
    assert locking.rank("memberships") < locking.rank("execution_grant") < locking.rank("invocation_context")
    assert len(set(locking.LOCK_ORDER)) == len(locking.LOCK_ORDER)


def test_follows_order_allows_repeats_and_refuses_a_step_back() -> None:
    assert locking.follows_order(("run_lease", "runs", "runs", "events"))  # a lock already held is taken again
    assert not locking.follows_order(("runs", "run_lease"))
    assert not locking.follows_order(("invocation_context", "runs"))  # revoking handles before locking the run
    with pytest.raises(ValueError):
        locking.follows_order(("sessions",))  # an own-unit table has no rank


@pytest.mark.parametrize("unit", sorted(locking.OBSERVED_UNITS))
def test_the_documented_units_are_consistent_with_the_order(unit: str) -> None:
    assert locking.follows_order(locking.OBSERVED_UNITS[unit]), unit


@pytest.mark.parametrize("unit", sorted(locking.OWN_UNITS))
def test_own_units_never_touch_a_run_table(unit: str) -> None:
    # The sweeper's purge deletes expired idempotency records in the same unit as the session tables; it touches no
    # run table, so it cannot meet a run transaction in a cycle.
    assert set(locking.OWN_UNITS[unit]) <= locking.OWN_UNIT | {"idempotency_request"}, unit


def test_not_yet_created_tables_are_absent_from_the_matrix() -> None:
    assert not locking.NOT_YET_CREATED & set(privileges.GRANTS)
```

Run: `uv run python -m pytest tests/plan_h/test_locking.py -q`
Expected: `1 error in` (`ImportError: cannot import name 'locking' from 'ops_core'`).

- [ ] **Step 6: Publish the order**

Create `core/src/ops_core/locking.py`:

```python
"""The published lock order (AM-12 SA:188, extended by Plan H ruling 14; erratum 52) as data a test checks.

The order constrains waits: row locks on rows that already exist (`SELECT … FOR UPDATE` or `FOR SHARE`, `UPDATE`,
`DELETE`) and advisory locks. A transaction takes them in this order and never goes back to an earlier entry for a
row it does not already hold. Two kinds of statement are outside the order because they never wait on another
transaction's lock: a `SKIP LOCKED` read, and a `NOWAIT` lock (it fails with SQLSTATE 55P03 instead of waiting). Plain
reads take no lock. An INSERT of a fresh row with a new key never waits on the table it inserts into (two inserts of
the same new key make the second wait for the first inserter alone), but its foreign-key check takes FOR KEY SHARE on
the referenced parent row, and that waits for any FOR UPDATE holder of the parent: the first `run_lease` row of a run
locks its `runs` row, and an `invocation_context` row its `runs` and `jobs` rows. Such an insert therefore ranks at its
parent's position; the entries below include those parents.

`jobs` appears twice: a claim picks its job with SKIP LOCKED before anything else, and a transaction that finishes,
re-queues or hands back its own claimed job does so after everything but the idempotency record. Tables in `OWN_UNIT`
are only locked in transactions that lock no run table; `NEVER_LOCKED` tables are inserted or read, never locked.
`OBSERVED_UNITS` lists every transaction of the system after T13 as the entries it locks, in order (reads left out,
foreign-key parents of fresh inserts included). It is written by hand: tests/plan_h/test_locking.py checks that the
documented units are consistent with the order and fails when a table in the privilege matrix has no place here, so a
new table or transaction is placed before it ships; it cannot discover a transaction nobody listed (the live stress
test hunts for those).
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise
from typing import Final

LOCK_ORDER: Final = (
    "advisory:idempotency",  # erratum 37: pg_advisory_xact_lock(1, hashtext(scope)), the API's units only
    "advisory:asset",  # SA:189: pg_advisory_xact_lock(hashtextextended(tenant || ':' || asset, 0)); taken by T21
    "jobs:claim",  # SKIP LOCKED only (Plan H ruling 3)
    "run_lease",
    "runs",
    "messages",
    "drafts",
    "proposals",
    "decisions",
    "memberships",
    "execution_grant",
    "action_attempt",
    "action_attempt_state",
    "operator_resolutions",  # created by T22
    "invocation_context",
    "run_state_history",
    "events",
    "outbox",  # created by T14
    "jobs:finish",  # the transaction's own claimed job: finished, re-queued or handed back
    "idempotency_request",  # written last, before commit (SA:188)
)
OWN_UNIT: Final = frozenset(
    {"model_permit", "sessions", "login_state", "logout_jti", "test_clock", "tenants", "run_directory"}
)
NEVER_LOCKED: Final = frozenset({"conversations", "transitions"})
NOT_YET_CREATED: Final = frozenset({"operator_resolutions", "outbox", "model_permit"})

OBSERVED_UNITS: Final[dict[str, tuple[str, ...]]] = {
    "worker claim (persistence.claim_next)": ("jobs:claim", "run_lease", "runs"),  # a first lease's FK key share
    "worker investigate start": ("run_lease", "runs", "jobs:finish"),  # the minted handle's FK key share on its job
    "worker tool event (append_event)": ("run_lease", "runs"),
    "worker failure (transition_run)": ("run_lease", "runs"),
    "worker draft and freeze": ("run_lease", "runs"),
    "worker execute start": ("run_lease", "runs", "jobs:finish"),
    "worker mark_unknown": ("run_lease", "runs", "invocation_context"),
    "worker release (persistence.release_lease)": ("run_lease", "invocation_context", "jobs:finish"),
    "worker abandon (lease lost)": ("run_lease", "invocation_context", "jobs:finish"),
    "heartbeat renewal (lease.renew)": ("run_lease",),
    "mcp resolve_invocation and lookup_action": ("run_lease",),
    "mcp-write grant_execution": ("run_lease", "runs"),
    "mcp-write mark_sent": ("run_lease", "runs"),
    "mcp-write record_outcome": ("run_lease", "runs"),
    "api admission (create_run)": ("advisory:idempotency", "runs", "idempotency_request"),
    "api clarification reply": ("advisory:idempotency", "runs", "idempotency_request"),
    "api decision (record_decision)": ("advisory:idempotency", "runs", "idempotency_request"),
    "sweeper membership sync": ("memberships",),
    "sweeper reclaim (leases.reclaim)": ("jobs:finish",),
    "sweeper sync job record": ("jobs:claim",),
}
OWN_UNITS: Final[dict[str, tuple[str, ...]]] = {
    "worker model permit (take, release)": ("model_permit",),
    "api session touch and revocation": ("sessions",),
    "api login state consumption": ("login_state",),
    "api logout jti record": ("logout_jti",),
    "sweeper purge": ("sessions", "login_state", "logout_jti", "idempotency_request"),
    "test clock move (test_harness)": ("test_clock",),
}


def table_of(entry: str) -> str | None:
    """The table an order entry locks (`jobs:claim` → `jobs`), or None for an advisory lock."""
    head, _, _ = entry.partition(":")
    return None if head == "advisory" else head


def rank(entry: str) -> int:
    """The entry's position in the order.

    Raises:
        ValueError: the entry has no place in the order (an own-unit table, a typo).
    """
    return LOCK_ORDER.index(entry)


def follows_order(entries: Sequence[str]) -> bool:
    """True when a transaction taking `entries` in this sequence never steps back in the order; repeating an entry is
    allowed (the lock is already held)."""
    ranks = [rank(entry) for entry in entries]
    return all(earlier <= later for earlier, later in pairwise(ranks))
```

Run: `uv run python -m pytest tests/plan_h/test_locking.py -q`
Expected: `30 passed`.

- [ ] **Step 7: Gates and commit**

Format, lint and count characters on `core/src/ops_core/settings.py`, `core/src/ops_core/locking.py`,
`tests/plan_h/test_settings_leases.py`, `tests/plan_h/test_locking.py`.

Run: `PYTHONUTF8=1 uv run python scripts/check.py`
Expected: `CHECK: GREEN`; pytest `857 passed, 104 skipped`.

Run: `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`
Expected: exit 0. (No migration, service or live test changed: the live gate is not run in this task.)

```bash
git add pyproject.toml core/src/ops_core/settings.py core/src/ops_core/locking.py tests/plan_h
git commit -m "feat(core): lease settings, the global queue limit and the published lock order (T13)"
```

---

### Task 2: Revision 0007 — the permit, the fence cell, the job-type CHECK, the global count and the frozen branch

**Files:**
- Create: `migrations/app/versions/0007_leases_fences.py`, `tests/plan_h/test_migration_0007.py`,
  `tests/e2e/test_migration_0007_live.py`
- Modify: `core/src/ops_core/privileges.py:7-15` (docstring), `:107-111` (`run_lease` row, then the `model_permit`
  row), `:157-159` (`NO_RLS`), `:182-183` (`DEFINER_FUNCTIONS`), `core/src/ops_core/locking.py` (`NOT_YET_CREATED`, as
  Task 1 wrote it), `migrations/app/versions/tc_0001_test_clock.py:20-55`,
  `tests/plan_e/test_transitions_table.py:91-92` (`REVISIONS`), `tests/e2e/conftest.py:143` (`PURGE_ORDER`),
  `tests/e2e/test_roles_live.py:222-223` (the r009 job's type)

**Requirements:** R107 (the lease row lock inside definers), R006 (a clean downgrade), R124 (the matrix), the BS:550
global bound's definer; brief rulings 1, 12, 13, 15, 21 (`PURGE_ORDER`), 27, 30, 31.

**Interfaces:**
- Consumes: `ops_core.privileges.Grant`, `grant_statements(tables, grants, *, revokees)`,
  `function_grant_statements(name, *, args, callers)`; `scripts.skeleton.migrate`, `downgrade`; the e2e fixtures
  `app_conn`, `role_conn`; `tests.e2e.test_migrations_and_persistence.new_run(conn, tenant_id=None, *, api)`.
- Produces: the table `app.model_permit(slot smallint PK CHECK (slot >= 1), holder text, run_id uuid, leased_until
  timestamptz NOT NULL DEFAULT '-infinity')` with slot 1 seeded; `privileges.GRANTS["model_permit"] = {"worker":
  sel+upd}`; `GRANTS["run_lease"]["app_definer"] = Grant(sel=True, upd=("fence",))`; the constraint
  `jobs_type_check`; the definer `app.queued_runs_total() RETURNS bigint` (caller `api`); in the revision:
  `TABLES`, `MAIN_GRANTEES_0007`, `GRANTS_0007`, `RUN_LEASE_CELLS_0002`, `JOB_TYPES_0007`, `SCHEMA_CHANGES`,
  `QUEUED_RUNS_TOTAL`, `FUNCTIONS`, `REPLACED`, `CREATED`, `RESTORED`, `DOWNGRADE` (Task 4 extends the last four and
  `FUNCTIONS`); `tc_0001_test_clock.TEST_ONLY_ROLES_TC`, `GRANTEES_TC`.

- [ ] **Step 1: Write the failing revision tests**

Create `tests/plan_h/test_migration_0007.py`:

```python
"""Revision 0007 without a database (Plan H rulings 1, 12, 13, 27, 30, 31): the frozen cells equal the live matrix,
the statements create what the lease code relies on, the downgrade puts 0006's cells back, and the testclock branch
no longer renders anything from the live matrix.

Catches: a definer cell wider than `upd(fence)` on run_lease (a definer that could rewrite a lease's owner or
expiry), a permit any role but the worker may touch (erratum 50), a permit table with RLS (SA:523), a job type the
CHECK forgets (a real job refused at insert), a downgrade that keeps the definer's fence cell, and a testclock
revision that would change when a role is added to the matrix (round-3 finding N1 of Plan E).
"""

import importlib.util
from pathlib import Path
from typing import Any

import alembic.op
import pytest
from ops_core import privileges as p
from ops_core.jobs import JobType

VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "app" / "versions"
LEASE_REVOKE = "REVOKE ALL ON app.run_lease FROM api, worker, sweeper, mcp_read, mcp_exec, operator, app_definer"


def revision(name: str = "0007_leases_fences") -> Any:
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
    assert module.down_revision == "0006_admission_idempotency"
    assert module.GRANTS_0007 == {table: p.GRANTS[table] for table in module.TABLES}
    assert p.GRANTS["run_lease"][p.DEFINER_ROLE] == p.Grant(sel=True, upd=("fence",))  # erratum 45
    assert p.GRANTS["model_permit"] == {"worker": p.Grant(sel=True, upd=True)}  # erratum 50: nobody else
    assert "model_permit" in p.NO_RLS and "model_permit" not in p.RLS_TABLES  # SA:523
    assert set(module.MAIN_GRANTEES_0007) == set(p.MAIN_GRANTEES)
    assert p.DEFINER_FUNCTIONS["queued_runs_total"] == ("", ("api",))  # ruling 13: the API's count only


def test_upgrade_creates_the_permit_the_check_and_the_count(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = statements(revision(), "upgrade", monkeypatch)
    table = next(s for s in seen if s.startswith("CREATE TABLE app.model_permit"))
    for column in (
        "slot smallint PRIMARY KEY CHECK (slot >= 1)",
        "holder text",
        "run_id uuid",
        "leased_until timestamptz NOT NULL DEFAULT '-infinity'",
    ):
        assert column in table, column
    assert "INSERT INTO app.model_permit (slot) VALUES (1)" in seen  # SA:440: seeded by the migration, BS:549: one
    check = next(s for s in seen if "jobs_type_check" in s)
    assert all(f"'{job_type.value}'" in check for job_type in JobType)
    grants = [s for s in seen if s.startswith(("GRANT", "REVOKE")) and "FUNCTION" not in s]
    assert grants == [
        LEASE_REVOKE,
        "GRANT INSERT, SELECT, UPDATE ON app.run_lease TO worker",
        "GRANT SELECT ON app.run_lease TO sweeper",
        "GRANT UPDATE (lease_until) ON app.run_lease TO sweeper",
        "GRANT SELECT ON app.run_lease TO app_definer",
        "GRANT UPDATE (fence) ON app.run_lease TO app_definer",
        "REVOKE ALL ON app.model_permit FROM api, worker, sweeper, mcp_read, mcp_exec, operator, app_definer",
        "GRANT SELECT, UPDATE ON app.model_permit TO worker",
    ]
    body = next(s for s in seen if s.lstrip().startswith("CREATE OR REPLACE FUNCTION app.queued_runs_total()"))
    assert "_authority('queued_runs_total', ARRAY['api'])" in body and "set_config('app.tenant_id'" in body


def test_the_job_types_frozen_here_are_the_live_enum() -> None:
    frozen = revision().JOB_TYPES_0007
    assert len(frozen) == len(set(frozen)) and set(frozen) == {job_type.value for job_type in JobType}


def test_the_downgrade_drops_what_0007_added_and_restores_the_0002_lease_cells(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = statements(revision(), "downgrade", monkeypatch)
    assert seen[0] == "DROP FUNCTION app.queued_runs_total()"
    assert "ALTER TABLE app.jobs DROP CONSTRAINT jobs_type_check" in seen and "DROP TABLE app.model_permit" in seen
    assert seen[-5:] == [
        LEASE_REVOKE,
        "GRANT INSERT, SELECT, UPDATE ON app.run_lease TO worker",
        "GRANT SELECT ON app.run_lease TO sweeper",
        "GRANT UPDATE (lease_until) ON app.run_lease TO sweeper",
        "GRANT SELECT ON app.run_lease TO app_definer",
    ]
    assert not any(s.startswith("DELETE") for s in seen)  # it deletes no row


def test_the_testclock_branch_renders_from_frozen_tuples(monkeypatch: pytest.MonkeyPatch) -> None:
    branch = revision("tc_0001_test_clock")
    assert branch.TEST_ONLY_ROLES_TC == p.TEST_ONLY_ROLES and branch.GRANTEES_TC == p.GRANTEES
    source = (VERSIONS / "tc_0001_test_clock.py").read_text(encoding="utf-8")
    assert "privileges.TEST_ONLY_ROLES" not in source and "privileges.GRANTEES" not in source
    seen = statements(branch, "upgrade", monkeypatch)
    # The frozen tuples render exactly what the live matrix rendered when the branch was applied (Plan E, 0002).
    assert seen[-3:] == p.grant_statements(["test_clock"], branch.GRANTS_TC)
    assert "GRANT USAGE ON SCHEMA app TO test_harness" in seen
```

In `tests/plan_e/test_transitions_table.py` add the revision to `REVISIONS` (on-disk Alembic order, before the
`testclock` branch):

Edit 1 (old lines 91-92), replace:

```python
    "0006_admission_idempotency",
    "tc_0001_test_clock",
```

with:

```python
    "0006_admission_idempotency",
    "0007_leases_fences",
    "tc_0001_test_clock",
```

Run: `uv run python -m pytest tests/plan_h/test_migration_0007.py tests/plan_e/test_transitions_table.py -q`
Expected: `1 error in` (collection stops at the module-level `assert` on `REVISIONS` in the transitions module: the
file `0007_leases_fences.py` does not exist yet).

- [ ] **Step 2: Write the revision**

Create `migrations/app/versions/0007_leases_fences.py`:

```python
"""The run lease's schema half (T13, Plan H rulings 1, 12, 13, 27): the model permit, the definer's fence cell, the
job-type vocabulary and the global queue count; Task 4 of the plan adds the fenced definer functions to this revision.

Revision ID: 0007_leases_fences
Revises: 0006_admission_idempotency

`model_permit` holds one row per unit of global model concurrency (BS:549: one, seeded here, SA:440); the worker
takes a free slot with SKIP LOCKED and an expiry on the application clock, so no role needs to reclaim it and only the
worker holds any cell on it (erratum 50; SA:523: no RLS). `app_definer` gains UPDATE on `run_lease.fence`: a row lock
needs UPDATE on a column (Plan E ruling 23), the fenced definers lock the lease row, and `mark_unknown` bumps the fence
(erratum 45). `jobs.type` gets the AM-20.4 vocabulary as a CHECK (ruling 27). `queued_runs_total()` is the global
bound's count for `api`, which sees one tenant under RLS (ruling 13). Every cell, caller and body is frozen here; the
downgrade restores revision 0006 exactly (R006).
"""

from alembic import op
from ops_core import privileges

revision = "0007_leases_fences"
down_revision = "0006_admission_idempotency"
branch_labels = None
depends_on = None

HEADER = "LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp SET app.tenant_id = ''"
TABLES = ("run_lease", "model_permit")
MAIN_GRANTEES_0007 = ("api", "worker", "sweeper", "mcp_read", "mcp_exec", "operator", "app_definer")
GRANTS_0007: dict[str, dict[str, privileges.Grant]] = {
    "run_lease": {
        "worker": privileges.Grant(sel=True, ins=True, upd=True),
        "sweeper": privileges.Grant(sel=True, upd=("lease_until",)),
        "app_definer": privileges.Grant(sel=True, upd=("fence",)),
    },
    "model_permit": {"worker": privileges.Grant(sel=True, upd=True)},
}
# What 0002 granted on run_lease, for the downgrade (not named GRANTS_*: the newest-revision test folds every
# GRANTS_* attribute into the live matrix check).
RUN_LEASE_CELLS_0002: dict[str, dict[str, privileges.Grant]] = {
    "run_lease": {
        "worker": privileges.Grant(sel=True, ins=True, upd=True),
        "sweeper": privileges.Grant(sel=True, upd=("lease_until",)),
        "app_definer": privileges.Grant(sel=True),
    }
}
# The AM-20.4 job types, frozen here; a unit test compares them with ops_core.jobs.JobType.
JOB_TYPES_0007 = (
    "investigate",
    "resume_input",
    "execute",
    "recover",
    "expire_proposals",
    "sync_memberships",
    "sweep_wakeups",
    "deliver_outbox",
)
JOB_TYPES = ", ".join(f"'{job_type}'" for job_type in JOB_TYPES_0007)

SCHEMA_CHANGES = (
    (
        "CREATE TABLE app.model_permit ("
        " slot smallint PRIMARY KEY CHECK (slot >= 1),"
        " holder text,"
        " run_id uuid,"
        " leased_until timestamptz NOT NULL DEFAULT '-infinity')"
    ),
    "ALTER TABLE app.model_permit OWNER TO migrator",
    "INSERT INTO app.model_permit (slot) VALUES (1)",
    f"ALTER TABLE app.jobs ADD CONSTRAINT jobs_type_check CHECK (type IN ({JOB_TYPES}))",
)

QUEUED_RUNS_TOTAL = f"""
CREATE OR REPLACE FUNCTION app.queued_runs_total() RETURNS bigint
{HEADER} AS $fn$
DECLARE
    v_tenant uuid;
    v_count bigint;
    v_total bigint := 0;
BEGIN
    PERFORM app._authority('queued_runs_total', ARRAY['api']);
    -- BS:550's "100 total": runs is under RLS and api sees one tenant at a time (Plan G spike section 8), so the
    -- function walks the RLS-free tenants table and counts each tenant's QUEUED runs under that tenant's setting,
    -- the resolve_identity pattern (SA:520). One number leaves it: no id, no tenant, no state.
    FOR v_tenant IN SELECT t.tenant_id FROM tenants t ORDER BY t.tenant_id LOOP
        PERFORM set_config('app.tenant_id', v_tenant::text, true);
        SELECT count(*) INTO v_count FROM runs r WHERE r.state = 'QUEUED';
        v_total := v_total + v_count;
    END LOOP;
    RETURN v_total;
END
$fn$;
ALTER FUNCTION app.queued_runs_total() OWNER TO app_definer;
"""

# (name, argument types, callers, body): frozen here (N1); the newest-revision test reads this tuple.
FUNCTIONS: tuple[tuple[str, str, tuple[str, ...], str], ...] = (("queued_runs_total", "", ("api",), QUEUED_RUNS_TOTAL),)
# Signatures upgrade() drops before FUNCTIONS re-creates them with another signature or return type.
REPLACED: tuple[str, ...] = ()
# Signatures downgrade() drops: the functions 0006 does not have in the form FUNCTIONS created.
CREATED: tuple[str, ...] = ("queued_runs_total()",)
# What downgrade() re-creates afterwards, from the applied revisions' own bodies: (name, args, callers, body).
RESTORED: tuple[tuple[str, str, tuple[str, ...], str], ...] = ()
DOWNGRADE = (
    "ALTER TABLE app.jobs DROP CONSTRAINT jobs_type_check",
    f"REVOKE ALL ON app.model_permit FROM {', '.join(MAIN_GRANTEES_0007)}",
    "DROP TABLE app.model_permit",
)


def upgrade() -> None:
    """Schema, then the frozen cells, then the functions (body first, then its grants, so REVOKE lands on it)."""
    for statement in SCHEMA_CHANGES:
        op.execute(statement)
    for statement in privileges.grant_statements(TABLES, GRANTS_0007, revokees=MAIN_GRANTEES_0007):
        op.execute(statement)
    for signature in REPLACED:
        op.execute(f"DROP FUNCTION app.{signature}")
    for name, args, callers, body in FUNCTIONS:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)


def downgrade() -> None:
    """Back to 0006: drop what 0007 created, re-create what it replaced, drop the permit and the CHECK, and put back
    0002's run_lease cells."""
    for signature in CREATED:
        op.execute(f"DROP FUNCTION app.{signature}")
    for name, args, callers, body in RESTORED:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)
    for statement in DOWNGRADE:
        op.execute(statement)
    for statement in privileges.grant_statements(("run_lease",), RUN_LEASE_CELLS_0002, revokees=MAIN_GRANTEES_0007):
        op.execute(statement)
```

Then `uv run ruff check --select ISC004 --fix --unsafe-fixes migrations/app/versions/0007_leases_fences.py` (no change
expected: every implicit concatenation is already inside its own parentheses).

Run: `uv run python -m pytest tests/plan_h/test_migration_0007.py tests/plan_e/test_transitions_table.py -q`
Expected: `5 failed, 12 passed`: `test_the_frozen_cells_are_the_live_matrix` fails with `KeyError: 'model_permit'`
(the matrix has no row yet) and `test_the_newest_revision_of_every_cell_equals_the_live_matrix` with
`AssertionError: run_lease` (the revision's `app_definer` cell `upd=('fence',)` against the matrix's `upd=False`; the
newest-revision walk meets `run_lease` first); `test_upgrade_creates_the_permit_the_check_and_the_count` and
`test_no_op_execute_string_carries_a_sqlalchemy_bind[0007_leases_fences]` with `KeyError: 'queued_runs_total is not a
known definer function or helper'` (`function_grant_statements` refuses a name the matrix lacks); and
`test_the_testclock_branch_renders_from_frozen_tuples` with `AttributeError` (`TEST_ONLY_ROLES_TC`).

- [ ] **Step 3: The matrix rows**

In `core/src/ops_core/privileges.py`:

Edit 1 (old lines 7-15), replace:

```python
instead of hiding. Rows exist only for tables that exist; the owners of later tables (outbox → T14, feedback → T21,
operator_resolutions → T22, documents/chunks/embeddings → T17, model_permit → T13) add their rows. Six departures
from the printed table, each a proposed erratum (Plan E rulings 6, 10, 17, 23; Plan F rulings 2, 3 and 17 with
erratum 25; Plan G ruling 4): the worker (not the sweeper) may UPDATE jobs.available_at (re-queue after a transport
failure), app_definer may UPDATE runs.updated_at, the `transitions` table (the T07 table mirrored in SQL) is readable
by app_definer only, no definer function takes a row lock on proposals, decisions, memberships or execution_grant (a
lock needs UPDATE, which the matrix withholds), the sweeper holds SELECT beside its DELETE on sessions, login_state,
logout_jti and idempotency_request (a DELETE with a WHERE reads the row), and login_state and logout_jti are rows
the printed table lacks. `test_harness` exists only in the test profile: the main-line revisions grant it nothing;
```

with:

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

Edit 2 (old lines 107-111), replace:

```python
    "run_lease": {
        "worker": Grant(sel=True, ins=True, upd=True),
        "sweeper": Grant(sel=True, upd=("lease_until",)),
        DEFINER_ROLE: _S,
    },
```

with:

```python
    "run_lease": {
        "worker": Grant(sel=True, ins=True, upd=True),
        "sweeper": Grant(sel=True, upd=("lease_until",)),
        DEFINER_ROLE: Grant(sel=True, upd=("fence",)),  # erratum 45: the definers lock it; mark_unknown bumps it
    },
    # T13 (Plan H ruling 12): one seeded slot per unit of model concurrency; only the worker takes and frees it.
    "model_permit": {"worker": Grant(sel=True, upd=True)},
```

Edit 3 (old lines 157-159), replace:

```python
    "idempotency_request",
)
AUDIT_TABLES: Final = ("run_state_history", "action_attempt_state", "events")  # AM-20 principle 2
```

with:

```python
    "idempotency_request",
    "model_permit",
)
AUDIT_TABLES: Final = ("run_state_history", "action_attempt_state", "events")  # AM-20 principle 2
```

Edit 4 (old lines 182-183), replace:

```python
    "mark_unknown": ("uuid, bigint", ("worker",)),
}
```

with:

```python
    "mark_unknown": ("uuid, bigint", ("worker",)),
    "queued_runs_total": ("", ("api",)),  # T13 (Plan H ruling 13): BS:550's global count, one number
}
```

In `core/src/ops_core/locking.py` (as Task 1 wrote it) replace:

```python
NOT_YET_CREATED: Final = frozenset({"operator_resolutions", "outbox", "model_permit"})
```

with:

```python
NOT_YET_CREATED: Final = frozenset({"operator_resolutions", "outbox"})
```

- [ ] **Step 4: Freeze the testclock branch's grantee tuples**

In `migrations/app/versions/tc_0001_test_clock.py`:

Edit 1 (old lines 20-25), replace:

```python
GRANTS_TC = {
    "test_clock": {
        privileges.DEFINER_ROLE: privileges.Grant(sel=True),
        "test_harness": privileges.Grant(ins=True, upd=True, dele=True),
    }
}
```

with:

```python
GRANTS_TC = {
    "test_clock": {
        privileges.DEFINER_ROLE: privileges.Grant(sel=True),
        "test_harness": privileges.Grant(ins=True, upd=True, dele=True),
    }
}
# The roles this branch grants to and revokes from, frozen like the main line's MAIN_GRANTEES_<rev> (Plan H ruling 30):
# rendering them from the live matrix would let a later role change rewrite an applied revision. They render exactly
# what the matrix rendered when the branch was written (a unit test compares the two).
TEST_ONLY_ROLES_TC = ("test_harness",)
GRANTEES_TC = ("api", "worker", "sweeper", "mcp_read", "mcp_exec", "operator", "test_harness", "app_definer")
```

Edit 2 (old lines 43-55), replace:

```python
    for statement in privileges.schema_usage_statements(privileges.TEST_ONLY_ROLES):
        op.execute(statement)
    for statement in privileges.function_grant_statements("current_time", args="", callers=("test_harness",)):
        op.execute(statement)
    for statement in privileges.grant_statements(["test_clock"], GRANTS_TC):
        op.execute(statement)


def downgrade() -> None:
    """Drop the test clock and take back what the branch granted test_harness."""
    op.execute("DROP TABLE app.test_clock")
    op.execute(f"REVOKE ALL ON FUNCTION app.current_time() FROM {', '.join(privileges.TEST_ONLY_ROLES)}")
    op.execute(f"REVOKE USAGE ON SCHEMA app FROM {', '.join(privileges.TEST_ONLY_ROLES)}")
```

with:

```python
    for statement in privileges.schema_usage_statements(TEST_ONLY_ROLES_TC):
        op.execute(statement)
    for statement in privileges.function_grant_statements("current_time", args="", callers=TEST_ONLY_ROLES_TC):
        op.execute(statement)
    for statement in privileges.grant_statements(["test_clock"], GRANTS_TC, revokees=GRANTEES_TC):
        op.execute(statement)


def downgrade() -> None:
    """Drop the test clock and take back what the branch granted test_harness."""
    op.execute("DROP TABLE app.test_clock")
    op.execute(f"REVOKE ALL ON FUNCTION app.current_time() FROM {', '.join(TEST_ONLY_ROLES_TC)}")
    op.execute(f"REVOKE USAGE ON SCHEMA app FROM {', '.join(TEST_ONLY_ROLES_TC)}")
```

Run:

```bash
uv run python -m pytest tests/plan_h/test_migration_0007.py tests/plan_e/test_transitions_table.py \
  tests/plan_e/test_privileges.py tests/plan_h/test_locking.py -q
```

Expected: `53 passed` (the new module's 5, the transitions module's 12 with one more parametrised revision, Plan E's
privileges 6, the lock-order 30).

- [ ] **Step 5: Keep the live fixtures and the r009 test in step with the revision**

In `tests/e2e/conftest.py`:

Edit 1 (old line 143), replace:

```python
    "DELETE FROM app.run_directory WHERE run_id = %s",  # the directory references runs
```

with:

```python
    "DELETE FROM app.run_directory WHERE run_id = %s",  # the directory references runs
    "DELETE FROM app.run_lease WHERE run_id = %s",  # T13: the lease references runs
    # T13: a permit a test left held for this run is free again (the seeded slot itself stays).
    "UPDATE app.model_permit SET holder = NULL, run_id = NULL, leased_until = '-infinity' WHERE run_id = %s",
```

In `tests/e2e/test_roles_live.py` (the CHECK on `jobs.type` would fire before the foreign key it tests):

Edit 1 (old lines 222-223), replace:

```python
                "INSERT INTO app.jobs (id, type, tenant_id, run_id, dedup_key)"
                " VALUES (gen_random_uuid(), 'x', %s, %s, %s)",
```

with:

```python
                "INSERT INTO app.jobs (id, type, tenant_id, run_id, dedup_key)"
                " VALUES (gen_random_uuid(), 'investigate', %s, %s, %s)",  # a valid type: only the key may refuse it
```

- [ ] **Step 6: The live revision test**

Create `tests/e2e/test_migration_0007_live.py`:

```python
"""Revision 0007 against the per-session test database (OPS_LIVE=1; Plan H rulings 1, 12, 13, 15, 27, 31).

Catches: a downgrade that leaves the permit, the CHECK, the definer's fence cell or the new function behind (or an
upgrade that does not bring them back), a permit another role can read or a second worker can take while it is held,
an unknown job type accepted, an `app_definer` that cannot take the asset guard's advisory lock (T21's gate would
fail closed for everyone), and a global queue count that misses a tenant, answers a role other than `api`, or leaves
the caller's tenant setting changed.
"""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from ops_core import persistence, settings
from ops_core.settings import Profile, Role

from tests.e2e.conftest import purge_run, purge_tenant
from tests.e2e.test_migrations_and_persistence import new_run

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")
TAKE_PERMIT = (
    "UPDATE app.model_permit SET holder = %s, leased_until = app.current_time() + interval '65 seconds'"
    " WHERE slot = (SELECT slot FROM app.model_permit WHERE leased_until <= app.current_time()"
    " ORDER BY slot FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING slot"
)
FREE_PERMIT = "UPDATE app.model_permit SET holder = NULL, leased_until = '-infinity' WHERE slot = 1"


async def exists(conn: persistence.Conn, signature: str) -> bool:
    cur = await conn.execute("SELECT to_regprocedure(%s) IS NOT NULL AS present", (signature,))
    return bool((await cur.fetchone())["present"])


async def snapshot(conn: persistence.Conn) -> dict[str, Any]:
    """What revision 0007 changes, as comparable values: every app function's definition, run_lease's column cells,
    the jobs constraints and whether the permit table exists."""
    cur = await conn.execute(
        "SELECT p.oid::regprocedure::text AS signature, pg_get_functiondef(p.oid) AS body FROM pg_proc p"
        " JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'app' ORDER BY 1"
    )
    functions = {row["signature"]: row["body"] for row in await cur.fetchall()}
    cur = await conn.execute(
        "SELECT grantee, privilege_type, column_name FROM information_schema.column_privileges"
        " WHERE table_schema = 'app' AND table_name = 'run_lease' ORDER BY 1, 2, 3"
    )
    cells = [(row["grantee"], row["privilege_type"], row["column_name"]) for row in await cur.fetchall()]
    cur = await conn.execute("SELECT conname FROM pg_constraint WHERE conrelid = 'app.jobs'::regclass ORDER BY 1")
    constraints = [row["conname"] for row in await cur.fetchall()]
    cur = await conn.execute("SELECT to_regclass('app.model_permit') IS NOT NULL AS present")
    permit = bool((await cur.fetchone())["present"])
    return {"functions": functions, "lease_cells": cells, "job_constraints": constraints, "permit": permit}


async def test_the_round_trip_restores_0006(app_conn: persistence.Conn) -> None:
    from scripts.skeleton import downgrade, migrate

    superuser = settings.superuser_postgres()
    head = await snapshot(app_conn)
    assert head["permit"] and "jobs_type_check" in head["job_constraints"]
    assert ("app_definer", "UPDATE", "fence") in head["lease_cells"]
    try:
        downgrade("app", superuser, "0006_admission_idempotency")
        before = await snapshot(app_conn)
        assert not before["permit"] and "jobs_type_check" not in before["job_constraints"]
        assert ("app_definer", "UPDATE", "fence") not in before["lease_cells"]
        assert not await exists(app_conn, "app.queued_runs_total()")
    finally:
        assert migrate(Profile.TEST) == 0  # every later test needs the head
    assert await snapshot(app_conn) == head  # the upgrade brings back exactly what the downgrade took


async def test_model_permit_is_seeded_and_only_the_worker_takes_it(role_conn: RoleConn) -> None:
    worker, other = await role_conn(Role.WORKER), await role_conn(Role.WORKER)
    api, sweeper = await role_conn(Role.API), await role_conn(Role.SWEEPER)
    cur = await worker.execute(TAKE_PERMIT, ("live-a",))
    assert [row["slot"] for row in await cur.fetchall()] == [1]  # one seeded slot: model concurrency 1 (BS:549)
    try:
        cur = await other.execute(TAKE_PERMIT, ("live-b",))
        assert await cur.fetchall() == []  # held: the second taker gets nothing, at once
        for conn in (api, sweeper):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                await conn.execute("SELECT slot FROM app.model_permit")
    finally:
        await worker.execute(FREE_PERMIT)
    cur = await other.execute(TAKE_PERMIT, ("live-b",))
    assert [row["slot"] for row in await cur.fetchall()] == [1]  # freed: the next worker takes it
    await other.execute(FREE_PERMIT)


async def test_the_job_type_check_refuses_an_unknown_type(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    tenant, _, run = await new_run(app_conn, api=await role_conn(Role.API))
    try:
        with pytest.raises(psycopg.errors.CheckViolation):
            await app_conn.execute(
                "INSERT INTO app.jobs (id, type, tenant_id, run_id, dedup_key)"
                " VALUES (gen_random_uuid(), 'bogus', %s, %s, %s)",
                (tenant, run, f"bogus-{uuid4()}"),
            )
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


async def test_app_definer_may_take_the_asset_guard_lock(app_conn: persistence.Conn) -> None:
    """T13 review note 5 (ruling 15): a definer owned by app_definer takes SA:189's one-key advisory lock. The probe
    is created and dropped by the rollback, so no catalog test ever sees it."""
    probe = (
        "CREATE FUNCTION app._advisory_probe(p_key text) RETURNS text"
        " LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp AS $probe$"
        " BEGIN PERFORM pg_advisory_xact_lock(hashtextextended(p_key, 0)); RETURN current_user; END $probe$"
    )
    async with app_conn.transaction(force_rollback=True):
        await app_conn.execute(probe)
        await app_conn.execute("ALTER FUNCTION app._advisory_probe(text) OWNER TO app_definer")
        cur = await app_conn.execute("SELECT app._advisory_probe(%s) AS who", (f"{ALPHA}:A17",))
        assert (await cur.fetchone())["who"] == "app_definer"
        cur = await app_conn.execute(
            "SELECT count(*) AS n FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid()"
            " AND granted AND objsubid = 1"  # objsubid 1: the one-key (bigint) space, apart from erratum 37's two-key
        )
        assert (await cur.fetchone())["n"] == 1


async def test_queued_runs_total_counts_every_tenant_for_api_only(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    made = [await new_run(app_conn, api=api) for _ in range(2)]  # two fresh tenants, one QUEUED run each
    try:
        cur = await app_conn.execute("SELECT count(*) AS n FROM app.runs WHERE state = 'QUEUED'")
        everyone = (await cur.fetchone())["n"]
        async with api.transaction():
            await persistence.set_tenant(api, made[0][0])
            cur = await api.execute("SELECT app.queued_runs_total() AS n")
            assert (await cur.fetchone())["n"] == everyone >= 2  # every tenant, not only the caller's
            cur = await api.execute("SELECT current_setting('app.tenant_id', true) AS t")
            assert (await cur.fetchone())["t"] == str(made[0][0])  # the caller's tenant is back after the call
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await worker.execute("SELECT app.queued_runs_total()")
    finally:
        for tenant, _, run in made:
            await purge_run(app_conn, run)
            await purge_tenant(app_conn, tenant)
```

Run (dev stack up, no skeleton process running):

```bash
OPS_LIVE=1 PROFILE=test PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_migration_0007_live.py \
  tests/e2e/test_roles_live.py tests/e2e/test_migrations_and_persistence.py tests/e2e/test_migration_0006_live.py -q
```

Expected: `22 passed` (the new 5; the roles module's 7, R124 now with the permit row and the fence cell; the
persistence module's 7, R006 now through 0007's downgrade; the 0006 module's 3, whose downgrade passes through 0007).

- [ ] **Step 7: Gates and commit**

Format, lint and count characters on every file of this task (the revision after the ISC004 pass).

Run: `PYTHONUTF8=1 uv run python scripts/check.py`
Expected: `CHECK: GREEN`; pytest `863 passed, 109 skipped` (857 + 5 + 1 parametrised revision; the 5 new live tests
skip).

Run: `PYTHONUTF8=1 uv run python scripts/check.py --profile test`
Expected: `CHECK: GREEN`; pytest `951 passed, 21 skipped`. Then
`git checkout -- reports/bootstrap reports/skeleton reports/auth reports/admission`.

Run: `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`
Expected: exit 0.

```bash
git add migrations/app/versions/0007_leases_fences.py migrations/app/versions/tc_0001_test_clock.py
git add core/src/ops_core/privileges.py core/src/ops_core/locking.py tests/plan_h/test_migration_0007.py
git add tests/plan_e/test_transitions_table.py tests/e2e/conftest.py tests/e2e/test_roles_live.py
git add tests/e2e/test_migration_0007_live.py
git commit -m "feat(migrations): revision 0007, the model permit, the definer fence cell and the global count (T13)"
```

---

### Task 3: The lease core — claim under a lease, fence every writing unit, release with the job, abandon on loss

**Files:**
- Create: `core/src/ops_core/lease.py`, `tests/plan_h/test_lease.py`, `tests/plan_h/test_worker_units.py`,
  `tests/e2e/test_leases_live.py`
- Modify: `core/src/ops_core/persistence.py:8` (docstring), `:13-31` (imports), `:139` (`Session` docstring),
  `:282-285` (`revoke_handles`), `:538-559` (`claim_job` replaced by the lease block), `:567-568` (`requeue_job`
  docstring), `:613-623` (`mint_handle`); `worker/src/ops_worker/handlers.py` (whole file), `worker/src/ops_worker/
  main.py` (whole file); `tests/e2e/conftest.py` (imports, new helpers at the end), `tests/plan_b/test_evidence.py:1-7`,
  `:17-23`; `tests/plan_f/test_grant_deferred.py:1-15`, `:54-101`; `tests/e2e/test_worker_live.py:9-24`, `:103-113`
  and the call sites; `tests/e2e/test_migrations_and_persistence.py:21`, `:136-162`, `:172-174`, `:399-403`;
  `tests/e2e/test_mcp_read_live.py:19`, `:43-48`; `tests/e2e/test_mcp_write_live.py:24`, `:85-89`;
  `tests/e2e/test_r105_walking_skeleton.py:25-26`, `:209-214`

**Requirements:** R020 (a stale worker cannot mutate), R087 (lease and fence per run across job types), R107 (fenced
writes lock the lease row; expiry on the database clock after the lock), DoD 1; brief rulings 2, 3, 4, 5, 8, 18, 19,
21 (interleaving), 24, 25, 28, 29.

**Interfaces:**
- Consumes: `ops_core.settings.LeaseSettings` (Task 1); the `run_lease` grants of 0002 (worker `sel, ins, upd`); the
  `PURGE_ORDER` lease delete (Task 2).
- Produces (`ops_core.lease`): `DEADLINE_MARGIN_SECONDS = 5.0`, `RELEASED = "released"`, `LOCK_FOR_UPDATE`,
  `LOCK_FOR_UPDATE_NOWAIT`, `LOCK_FOR_SHARE` (statements with one `%s`, the run id, returning `owner`, `fence`,
  `released`, `live`), `RENEW` (`%s` seconds, `%s` run id), `class LeaseLost(Exception)`, `@dataclass(frozen=True)
  class Busy(locked: bool)`, `class Lease(*, run_id: UUID, owner: str, fence: int, lease_seconds: int, started:
  float, clock: Callable[[], float] = time.monotonic)` with properties `fence`, `deadline`, `renewed_at`, `lost`,
  `refencing`, attributes `run_id`, `owner`, `lease_seconds`, `held_since`, and methods `check() -> None`,
  `async effect[T](call: Coroutine[Any, Any, T]) -> T` (raises LeaseLost), `cancel_effects() -> int` (thread-safe),
  `renewed(started: float) -> None`, `mark_lost(reason: str) -> bool`, `begin_refence() -> None`,
  `end_refence(fence: int | None) -> None`, `fence_moved_by_owner(used: int) -> bool`.
- Produces (`ops_core.persistence`): `Claimed(job: DictRow, lease: Lease)`, `Deferred(job_id: UUID)`,
  `acquire_lease(conn, *, run_id, owner, lease_seconds, wait=False, clock=time.monotonic) -> Lease | Busy` (with
  `wait=True` a lock wait past `lock_timeout` raises `psycopg.errors.LockNotAvailable`),
  `pick_job(conn, *, tenant_ids) -> DictRow | None`, `claim_next(conn, *, worker_name, tenant_ids, lease_seconds,
  clock=time.monotonic) -> Claimed | Deferred | None`, `fenced(conn, lease) -> None`, `release_lease(conn, lease, *,
  job, requeue_seconds=None) -> None`, `unclaim_job(conn, job_id, *, worker_name) -> None`,
  `revoke_handles(conn, run_id, fence) -> int`, `mint_handle(conn, *, run_id, job_id, server, azp, fence,
  ttl_seconds=60) -> str`. `claim_job` is removed (its one caller, the worker loop, uses `claim_next`).
- Produces (`ops_worker`): `handlers.Deps(conn, mcp, generator, urls, worker_name, leases=LeaseSettings())`,
  `handlers.investigate(deps, job, lease)`, `handlers.execute(deps, job, lease) -> bool`,
  `handlers.handle(deps, job, lease)`, `handlers.INTERRUPTED` (the FAILED message for a run found mid-investigation),
  `handlers.abandon(deps, job, lease)` (raises `psycopg.OperationalError`
  after closing a loop connection that is not idle); `main.MAX_DEFERRALS = 16`,
  `main.claim(deps, order) -> persistence.Claimed | None`, `main.run_job(deps, claimed) -> None`.
- Produces (`tests.e2e.conftest`): `lease_for(conn, run_id, *, owner="live-test", seconds=120, wait=False) -> Lease`,
  `expire_lease(conn, run_id)`, `backend_pid(conn) -> int`, `wait_until_blocked(conn, pid, *, timeout=5.0) ->
  list[int]`.

- [ ] **Step 1: Write the failing unit tests**

Create `tests/plan_h/test_lease.py`:

```python
"""The Lease the event loop and the heartbeat thread share (Plan H rulings 10 and 18) and the lock statements every
lease check runs (SA:157), without a database.

Catches: a local deadline that is not the lease minus SA:195's five seconds, an effect allowed after the deadline or
after a loss, a renewal that does not move the deadline, a second loss reason overwriting the first, a re-fence that
a concurrent renewal would read as a takeover (T13 review note 2), a lock statement that compares expiry before its
lock instead of after it, a loss that cancels anything but the effects in flight or does not reach them from
another thread (review round 1, B1: a cancelled database unit would leave the loop connection in a transaction), and
a NOWAIT acquisition whose second lock statement (after the first-row INSERT) raises instead of answering busy
(review round 2, N2).
"""

import asyncio
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import psycopg
import pytest
from ops_core import persistence
from ops_core.lease import (
    LOCK_FOR_SHARE,
    LOCK_FOR_UPDATE,
    LOCK_FOR_UPDATE_NOWAIT,
    RELEASED,
    Busy,
    Lease,
    LeaseLost,
)

RUN = UUID(int=7)


def lease(clock: list[float], *, fence: int = 3) -> Lease:
    return Lease(run_id=RUN, owner="worker:test", fence=fence, lease_seconds=30, started=100.0, clock=lambda: clock[0])


def test_the_local_deadline_is_the_lease_minus_the_margin() -> None:
    held = lease([100.0])
    assert (held.deadline, held.renewed_at, held.held_since) == (125.0, 100.0, 100.0)  # 100 + 30 - 5 (SA:195)


def test_check_raises_past_the_deadline_and_after_a_loss() -> None:
    clock = [124.9]
    held = lease(clock)
    held.check()
    clock[0] = 125.0
    with pytest.raises(LeaseLost):
        held.check()
    assert held.lost == "local deadline passed"
    other = lease([100.0])
    assert other.mark_lost("the fence moved")
    with pytest.raises(LeaseLost):
        other.check()


def test_a_renewal_moves_the_deadline() -> None:
    clock = [126.0]
    held = lease(clock)
    held.renewed(110.0)  # the monotonic instant before the renewing statement (ruling 18)
    assert (held.deadline, held.renewed_at) == (135.0, 110.0)
    held.check()  # 126 < 135: alive again by the renewal


def test_the_first_loss_reason_stands() -> None:
    held = lease([100.0])
    assert held.mark_lost("the fence moved") and not held.mark_lost(RELEASED)
    assert held.lost == "the fence moved"


def test_a_refence_hands_the_new_fence_over() -> None:
    held = lease([100.0])
    held.begin_refence()
    assert held.refencing and held.fence_moved_by_owner(3)  # pending: a renewal that meets fence 4 retries
    held.end_refence(4)
    assert (held.fence, held.refencing) == (4, False)
    assert held.fence_moved_by_owner(3)  # settled: the renewal that used 3 retries with 4
    assert not held.fence_moved_by_owner(4)  # a mismatch against the current, settled fence is a loss
    held.begin_refence()
    held.end_refence(None)  # mark_unknown refused: the fence stays
    assert (held.fence, held.refencing) == (4, False)


@pytest.mark.parametrize("statement", [LOCK_FOR_UPDATE, LOCK_FOR_UPDATE_NOWAIT, LOCK_FOR_SHARE])
def test_the_lock_statements_compare_after_the_lock(statement: str) -> None:
    locking, comparing = statement.split(") SELECT", 1)
    assert locking.startswith("WITH l AS MATERIALIZED (") and "app.current_time()" not in locking
    assert "l.lease_until > app.current_time() AS live" in comparing  # evaluated once the CTE returned the row
    assert ("FOR UPDATE" in locking) != ("FOR SHARE" in locking)


def test_an_effect_starts_only_while_the_lease_is_held() -> None:
    clock = [124.9]
    held = lease(clock)
    started: list[str] = []

    async def call(name: str) -> str:
        started.append(name)
        return name

    async def scenario() -> None:
        assert await held.effect(call("first")) == "first"
        clock[0] = 125.0
        with pytest.raises(LeaseLost):
            await held.effect(call("late"))  # refused unstarted (and closed, so never "never awaited")

    asyncio.run(scenario())
    assert started == ["first"] and held.lost == "local deadline passed"


def test_a_loss_cancels_the_effect_in_flight_from_another_thread_and_nothing_else() -> None:
    held = lease([100.0])
    unit_finished: list[bool] = []
    cancelled: list[int] = []

    async def unit() -> None:  # stands for a database unit: never registered, so a loss cannot interrupt it
        await asyncio.sleep(0.05)
        unit_finished.append(True)

    def lose() -> None:  # what the heartbeat thread does (ruling 19 as amended in review round 1)
        held.mark_lost("another owner took the lease")
        cancelled.append(held.cancel_effects())

    async def scenario() -> None:
        running = asyncio.create_task(unit())
        effect = asyncio.create_task(held.effect(asyncio.Event().wait()))
        await asyncio.sleep(0)  # the effect is registered and waiting
        thread = threading.Thread(target=lose)
        thread.start()
        thread.join()
        with pytest.raises(LeaseLost):
            await effect
        await running

    asyncio.run(scenario())
    assert cancelled == [1] and unit_finished == [True] and held.lost == "another owner took the lease"


def test_stopping_the_worker_is_not_a_lost_lease() -> None:
    held = lease([100.0])

    async def scenario() -> None:
        caller = asyncio.create_task(held.effect(asyncio.Event().wait()))
        await asyncio.sleep(0)
        caller.cancel()  # the worker shuts down: the caller's own task is cancelled
        with pytest.raises(asyncio.CancelledError):
            await caller

    asyncio.run(scenario())
    assert held.lost is None


class EmptyCursor:
    async def fetchone(self) -> None:
        return None


class SecondLockHeld:
    """A connection on which the run has no lease row yet, and the lock taken after the first-row INSERT meets a row
    another transaction holds (a waking waiter or the first inserter's next unit got there first)."""

    def __init__(self) -> None:
        self.locks = 0

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        yield

    async def execute(self, query: str, params: Any = None) -> Any:
        if query.startswith("INSERT"):
            return None
        self.locks += 1
        if self.locks == 1:
            return EmptyCursor()
        raise psycopg.errors.LockNotAvailable('could not obtain lock on row in relation "run_lease"')


def test_a_held_row_after_the_first_insert_is_busy_too() -> None:
    conn: Any = SecondLockHeld()
    got = asyncio.run(persistence.acquire_lease(conn, run_id=RUN, owner="w:test", lease_seconds=30))
    assert got == Busy(locked=True) and conn.locks == 2  # deferred, as the first statement's 55P03 is (ruling 3)
    waiting: Any = SecondLockHeld()
    with pytest.raises(psycopg.errors.LockNotAvailable):  # only a waiting acquisition lets it through
        asyncio.run(persistence.acquire_lease(waiting, run_id=RUN, owner="w:test", lease_seconds=30, wait=True))
```

Create `tests/plan_h/test_worker_units.py`:

```python
"""The worker under its lease without a database (Plan H rulings 3, 5, 18, 19, 28): every unit that writes for a run
opens with `persistence.fenced`, no MCP call starts past the lease's local deadline, the job's final unit releases
the lease with the job, a lost lease hands the job back without a transition, and a busy run's jobs are deferred a
bounded number of times per poll.

Catches: a unit that writes before its fence check (a stale worker's write would land), an MCP call started past the
deadline, a job closed by one unit and its lease released by another (a crash between them strands the run), a lost
lease turned into FAILED by its loser (the next owner decides), a deferral loop that never ends, a hand-back attempted
on a connection left inside a transaction (it would never commit), and a handed-back job that closes without work and
leaves its run RETRIEVING or DRAFTING, holding the conversation slot for good (review round 3, I1).
"""

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from ops_core import persistence, settings
from ops_core.lease import Lease, LeaseLost
from ops_worker import handlers, main
from ops_worker.drafting import FakeDraftGenerator
from psycopg.pq import TransactionStatus

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
TENANT, RUN_ID = uuid4(), uuid4()
RUN = {
    "run_id": RUN_ID,
    "tenant_id": TENANT,
    "message_id": uuid4(),
    "state": "QUEUED",
    "intent": "investigate",
    "asset_id": "A17",
    "start_at": NOW - timedelta(hours=24),
    "end_at": NOW,
    "supersedes_run_id": None,
    "active_proposal_id": uuid4(),
}
JOB = {"id": uuid4(), "run_id": RUN_ID, "tenant_id": TENANT, "type": "investigate"}
WRITES = {"transition_run", "mint_handle", "append_event", "freeze_proposal", "insert", "mark_unknown"}
SEARCH = {
    "status": "ok",
    "data": {
        "results": [
            {
                "evidence_id": "ALPHA-INCIDENT:v2:review",
                "document_id": "ALPHA-INCIDENT",
                "version": "2",
                "section": "review",
                "content_sha256": "62a90906c7bb706ae8a968eb0f7102f76b05d2c3be911c182d528a1fd25ef008",
                "excerpt": "text",
                "effective_from": "2026-10-01T00:00:00Z",
                "retrieved_at": "2026-10-08T12:00:00Z",
            }
        ],
        "retrieval_mode": "lexical",
        "corpus_version": "handoff-1",
    },
}


class Log:
    """What the fakes did, in order: BEGIN, COMMIT and ROLLBACK for units, and every persistence call by name."""

    def __init__(self) -> None:
        self.entries: list[str] = []

    def units(self) -> list[list[str]]:
        """The calls inside each unit, from its BEGIN to its COMMIT or ROLLBACK."""
        out: list[list[str]] = []
        current: list[str] | None = None
        for entry in self.entries:
            if entry == "BEGIN":
                current = []
            elif entry in ("COMMIT", "ROLLBACK"):
                assert current is not None
                out.append(current)
                current = None
            elif current is not None:
                current.append(entry)
        return out


class FakeCursor:
    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row

    async def fetchone(self) -> dict[str, Any]:
        return self.row


class FakeConn:
    """A connection whose transactions are logged; the handlers' own SQL (the message read, the drafts INSERT) too.
    It reports itself idle between units, as psycopg's `info.transaction_status` does."""

    def __init__(self, log: Log) -> None:
        self.log = log
        self.info = SimpleNamespace(transaction_status=TransactionStatus.IDLE)
        self.closed = False
        self.broken = False

    async def close(self) -> None:
        self.closed = True

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        self.log.entries.append("BEGIN")
        try:
            yield
        except BaseException:
            self.log.entries.append("ROLLBACK")
            raise
        self.log.entries.append("COMMIT")

    async def execute(self, query: str, params: Any = None) -> FakeCursor:
        self.log.entries.append("insert" if query.lstrip().startswith("INSERT") else "select")
        return FakeCursor({"text": "Investigate the alerts on A17 over the last 24 hours."})


class ScriptedMcp:
    def __init__(self, log: Log) -> None:
        self.log = log

    async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.log.entries.append(f"mcp:{tool}")
        return SEARCH


def patch(monkeypatch: pytest.MonkeyPatch, log: Log, *, lost_at: int | None = None) -> None:
    """Replace every persistence call the handlers make with a recorder; the `lost_at`-th `fenced` call raises
    LeaseLost, as a moved fence would."""
    calls = 0

    async def fenced(_conn: Any, lease: Lease) -> None:
        nonlocal calls
        calls += 1
        log.entries.append("fenced")
        if lost_at is not None and calls >= lost_at:
            lease.mark_lost("the fence moved")
            raise LeaseLost("run lease lost")

    async def run_row(_conn: Any, _run_id: Any, *, lock: bool = False) -> dict[str, Any]:
        log.entries.append("run_row")
        return dict(RUN)

    def recorder(name: str, result: Any = None) -> Callable[..., Any]:
        async def call(*_: Any, **__: Any) -> Any:
            log.entries.append(name)
            return result

        return call

    replaced = {
        "fenced": fenced,
        "run_row": run_row,
        "set_tenant": recorder("set_tenant"),
        "transition_run": recorder("transition_run", 2),
        "mint_handle": recorder("mint_handle", "handle"),
        "append_event": recorder("append_event"),
        "freeze_proposal": recorder("freeze_proposal"),
        "release_lease": recorder("release_lease"),
        "revoke_handles": recorder("revoke_handles", 1),
        "unclaim_job": recorder("unclaim_job"),
        "mark_unknown": recorder("mark_unknown"),
    }
    for name, fn in replaced.items():
        monkeypatch.setattr(persistence, name, fn)


def make(log: Log, clock: Callable[[], float] = time.monotonic) -> tuple[handlers.Deps, Lease]:
    conn: Any = FakeConn(log)
    deps = handlers.Deps(
        conn=conn, mcp=ScriptedMcp(log), generator=FakeDraftGenerator(), urls=settings.urls(), worker_name="w:test"
    )
    return deps, Lease(run_id=RUN_ID, owner="w:test", fence=3, lease_seconds=30, started=clock(), clock=clock)


def test_every_unit_that_writes_opens_with_the_fence(monkeypatch: pytest.MonkeyPatch) -> None:
    log = Log()
    patch(monkeypatch, log)
    deps, lease = make(log)
    asyncio.run(handlers.handle(deps, dict(JOB), lease))
    units = log.units()
    assert len(units) == 5, log.entries  # start, tool.started, tool.completed, DRAFTING, draft and freeze
    for unit in units:
        if WRITES & set(unit):
            assert next(entry for entry in unit if entry != "set_tenant") == "fenced", unit  # set_config is no lock
    assert log.entries[-1] == "release_lease" and log.entries.count("mcp:search_procedures") == 1


def test_the_final_unit_releases_the_lease_with_the_job(monkeypatch: pytest.MonkeyPatch) -> None:
    log = Log()
    patch(monkeypatch, log)
    deps, lease = make(log)
    asyncio.run(handlers.handle(deps, {**JOB, "type": "resume_input"}, lease))  # not handled yet (T20)
    assert log.entries == ["release_lease"]  # one unit closes the job, revokes and releases (ruling 28)


def test_a_lost_lease_hands_the_job_back_without_a_transition(monkeypatch: pytest.MonkeyPatch) -> None:
    log = Log()
    patch(monkeypatch, log, lost_at=2)  # the first unit passes; the tool.started event's fence has moved
    deps, lease = make(log)
    claimed: Any = persistence.Claimed(dict(JOB), lease)  # a plain dict stands in for the claimed DictRow
    asyncio.run(main.run_job(deps, claimed))
    assert lease.lost == "the fence moved"
    assert log.units()[-1] == ["set_tenant", "revoke_handles", "unclaim_job"]  # the abandon unit (ruling 19)
    assert log.entries.count("transition_run") == 1  # QUEUED -> RETRIEVING before the loss; never FAILED after it
    assert "release_lease" not in log.entries and "mcp:search_procedures" not in log.entries


def test_a_busy_run_defers_and_the_poll_gives_up_after_the_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    answers: list[persistence.Deferred | None] = [persistence.Deferred(uuid4()), persistence.Deferred(uuid4()), None]
    seen: list[dict[str, Any]] = []

    async def claim_next(_conn: Any, **kwargs: Any) -> persistence.Deferred | None:
        seen.append(kwargs)
        return answers.pop(0)

    monkeypatch.setattr(persistence, "claim_next", claim_next)
    deps, _ = make(Log())
    assert asyncio.run(main.claim(deps, [TENANT])) is None
    assert len(seen) == 3 and seen[0]["lease_seconds"] == 30 and seen[0]["worker_name"] == "w:test"
    calls = 0

    async def always_busy(_conn: Any, **_: Any) -> persistence.Deferred:
        nonlocal calls
        calls += 1
        return persistence.Deferred(uuid4())

    monkeypatch.setattr(persistence, "claim_next", always_busy)
    assert asyncio.run(main.claim(deps, [TENANT])) is None and calls == main.MAX_DEFERRALS


def test_no_call_starts_past_the_local_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    log = Log()
    patch(monkeypatch, log)
    now = [0.0]
    deps, lease = make(log, clock=lambda: now[0])
    minted = persistence.mint_handle

    async def mint_then_stall(*args: Any, **kwargs: Any) -> Any:
        now[0] = 25.0  # the loop stalled: 0 + 30 - 5 is the deadline
        return await minted(*args, **kwargs)

    monkeypatch.setattr(persistence, "mint_handle", mint_then_stall)
    with pytest.raises(LeaseLost):
        asyncio.run(handlers.investigate(deps, dict(JOB), lease))
    assert "mcp:search_procedures" not in log.entries  # SA:195: the call never started


def test_abandon_closes_a_loop_connection_left_in_a_transaction() -> None:
    """Review round 1, B1: no unit is ever cancelled, but should the loop connection not be idle when a lease is
    lost, handing the job back on it would nest in that transaction and never commit. `abandon` closes it instead,
    so the poll loop ends and the supervisor restarts the worker."""
    log = Log()
    deps, lease = make(log)
    conn: Any = deps.conn
    conn.info.transaction_status = TransactionStatus.INTRANS
    with pytest.raises(psycopg.OperationalError):
        asyncio.run(handlers.abandon(deps, dict(JOB), lease))
    assert conn.closed and log.entries == []  # nothing ran on it


@pytest.mark.parametrize("state", ["RETRIEVING", "DRAFTING"])
def test_an_interrupted_run_is_failed_not_left_active(monkeypatch: pytest.MonkeyPatch, state: str) -> None:
    """Review round 3, I1: the next owner of a handed-back or reclaimed investigate job fails the run it finds in
    RETRIEVING or DRAFTING (nothing resumes it before T20), in its first fenced unit, and closes the job."""
    log = Log()
    patch(monkeypatch, log)
    moves: list[tuple[str, str, Any]] = []

    async def interrupted_run(_conn: Any, _run_id: Any, *, lock: bool = False) -> dict[str, Any]:
        log.entries.append("run_row")
        return {**RUN, "state": state}

    async def transition_run(_conn: Any, *, run_id: Any, src: Any, dst: Any, detail: Any = None) -> int:
        log.entries.append("transition_run")
        moves.append((src.value, dst.value, detail))
        return 2

    monkeypatch.setattr(persistence, "run_row", interrupted_run)
    monkeypatch.setattr(persistence, "transition_run", transition_run)
    deps, lease = make(log)
    asyncio.run(handlers.handle(deps, dict(JOB), lease))
    assert moves == [(state, "FAILED", {"message": "interrupted; the run was not resumed"})]
    assert log.units()[0] == ["set_tenant", "fenced", "run_row", "transition_run"]
    assert log.entries[-1] == "release_lease" and "mcp:search_procedures" not in log.entries
```

In `tests/plan_f/test_grant_deferred.py` (the deferred branch now re-queues through the job's final unit):

Edit 1 (old lines 5-15), replace:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest
from ops_core import persistence, settings
from ops_core.states import RunState
from ops_mcp_write.server import refusal_error
from ops_worker import handlers
from ops_worker.handlers import EXECUTE_RETRY_SECONDS, is_deferred
```

with:

```python
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest
from ops_core import persistence, settings
from ops_core.lease import Lease
from ops_core.states import RunState
from ops_mcp_write.server import refusal_error
from ops_worker import handlers
from ops_worker.handlers import EXECUTE_RETRY_SECONDS, is_deferred
```

Edit 2 (old lines 54-101), replace the whole test function

```python
@pytest.mark.asyncio
async def test_execute_requeues_a_deferred_grant_and_revokes_its_handles(monkeypatch: pytest.MonkeyPatch) -> None:
    """Parked item 4: the worker's deferred branch re-queues in 30 s with the handles revoked, records no UNKNOWN
    and leaves the job open (execute returns False, so `handle` does not finish it)."""
    calls: dict[str, list[Any]] = {"revoke_handles": [], "requeue_job": [], "mark_unknown": [], "set_tenant": []}
    run_id, job_id, tenant = uuid4(), uuid4(), uuid4()

    async def run_row(_conn: Any, rid: UUID, *, lock: bool = False) -> dict[str, Any]:
        return {"run_id": rid, "state": RunState.APPROVED.value, "active_proposal_id": uuid4()}

    async def mint_handle(_conn: Any, **_: Any) -> str:
        return "handle"

    async def record(name: str, *args: Any) -> None:
        calls[name].append(args)

    async def set_tenant(_conn: Any, tid: UUID) -> None:
        await record("set_tenant", tid)

    async def revoke_handles(_conn: Any, rid: UUID) -> int:
        await record("revoke_handles", rid)
        return 1

    async def requeue_job(_conn: Any, jid: UUID, delay: int) -> None:
        await record("requeue_job", jid, delay)

    async def mark_unknown(_conn: Any, rid: UUID) -> RunState:
        await record("mark_unknown", rid)
        return RunState.OUTCOME_UNKNOWN

    for name, fn in {
        "run_row": run_row,
        "mint_handle": mint_handle,
        "set_tenant": set_tenant,
        "revoke_handles": revoke_handles,
        "requeue_job": requeue_job,
        "mark_unknown": mark_unknown,
    }.items():
        monkeypatch.setattr(persistence, name, fn)
    conn: Any = FakeConn()
    mcp = DeferringMcp()
    no_generator: Any = None  # the execute path never drafts
    deps = handlers.Deps(conn=conn, mcp=mcp, generator=no_generator, urls=settings.urls(), worker_name="worker:test")
    job = {"id": job_id, "run_id": run_id, "tenant_id": tenant, "type": "execute"}
    assert await handlers.execute(deps, job) is False
    assert mcp.calls == ["create_incident"]
    assert calls["revoke_handles"] == [(run_id,)] and calls["requeue_job"] == [(job_id, EXECUTE_RETRY_SECONDS)]
    assert EXECUTE_RETRY_SECONDS == 30 and calls["mark_unknown"] == []
```

with:

```python
@pytest.mark.asyncio
async def test_execute_requeues_a_deferred_grant_and_releases_its_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    """Parked item 4, under T13's lease: the deferred branch re-queues in 30 s through the job's final unit (handles
    revoked, lease released, Plan H ruling 28), records no UNKNOWN and returns False, so `handle` does not finish
    the job a second time."""
    calls: dict[str, list[Any]] = {"release_lease": [], "mark_unknown": [], "fenced": []}
    run_id, job_id, tenant = uuid4(), uuid4(), uuid4()
    lease = Lease(run_id=run_id, owner="worker:test", fence=2, lease_seconds=30, started=time.monotonic())

    async def run_row(_conn: Any, rid: UUID, *, lock: bool = False) -> dict[str, Any]:
        return {"run_id": rid, "state": RunState.APPROVED.value, "active_proposal_id": uuid4()}

    async def mint_handle(_conn: Any, **kwargs: Any) -> str:
        assert kwargs["fence"] == 2  # the handle carries the lease's fence
        return "handle"

    async def set_tenant(_conn: Any, _tid: UUID) -> None:
        return None

    async def fenced(_conn: Any, held: Lease) -> None:
        calls["fenced"].append(held.fence)

    async def release_lease(
        _conn: Any, held: Lease, *, job: dict[str, Any], requeue_seconds: int | None = None
    ) -> None:
        calls["release_lease"].append((held.fence, job["id"], requeue_seconds))

    async def mark_unknown(*args: Any) -> None:
        calls["mark_unknown"].append(args)

    for name, fn in {
        "run_row": run_row,
        "mint_handle": mint_handle,
        "set_tenant": set_tenant,
        "fenced": fenced,
        "release_lease": release_lease,
        "mark_unknown": mark_unknown,
    }.items():
        monkeypatch.setattr(persistence, name, fn)
    conn: Any = FakeConn()
    mcp = DeferringMcp()
    no_generator: Any = None  # the execute path never drafts
    deps = handlers.Deps(conn=conn, mcp=mcp, generator=no_generator, urls=settings.urls(), worker_name="worker:test")
    job = {"id": job_id, "run_id": run_id, "tenant_id": tenant, "type": "execute"}
    assert await handlers.execute(deps, job, lease) is False
    assert mcp.calls == ["create_incident"] and calls["fenced"] == [2]
    assert calls["release_lease"] == [(2, job_id, EXECUTE_RETRY_SECONDS)]
    assert EXECUTE_RETRY_SECONDS == 30 and calls["mark_unknown"] == []
```

Run: `uv run python -m pytest tests/plan_h/test_lease.py tests/plan_h/test_worker_units.py tests/plan_f/test_grant_deferred.py -q`
Expected: `3 errors in` (`ModuleNotFoundError: No module named 'ops_core.lease'` while collecting each of the three
modules).

- [ ] **Step 2: The lease module**

Create `core/src/ops_core/lease.py`:

```python
"""The run lease as the worker holds it (AM-12, T13): one `Lease` per claimed job, shared by the event loop, which
starts effects only before the lease's local deadline, and the heartbeat thread, which renews the row and moves that
deadline (SA:193-199). The lock statements the loop and the thread both run live here, so the two compare owner,
fence and expiry the same way.

Every comparison is made after the row lock (SA:157): each statement is a MATERIALIZED CTE that takes the lock and an
outer SELECT that compares on `app.current_time()`. A WHERE clause on the locking SELECT itself is evaluated before a
lock wait and re-checked afterwards only if the row changed, so a lease that lapsed while the statement waited on a
renewal that then rolled back would pass (tests/e2e/test_leases_live.py measures the difference). Python never
compares database instants; the local deadline is the monotonic instant taken before the statement that acquired or
renewed the lease, plus the lease, minus the five seconds SA:195 keeps in hand.

A lost lease stops the job in two ways (ruling 19 as amended in review round 1, B1). An effect (an MCP call, a model
call, the model permit's back-off sleep) runs through `Lease.effect` as a child task registered on the lease, and
the heartbeat thread cancels exactly those (`cancel_effects`). A database unit is never registered and never
cancelled: a cancellation landing inside psycopg's BEGIN would leave the loop connection in a transaction that never
commits. A loss during a unit is caught by the unit's own fence check or by the next `fenced()` or `check()`.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

DEADLINE_MARGIN_SECONDS: Final = 5.0  # SA:195: stop starting effects at lease_until - 5 s
RELEASED: Final = "released"  # the end a lease meets when its job's final unit gives it back

_LOCK = (
    "WITH l AS MATERIALIZED (SELECT owner, fence, lease_until FROM app.run_lease WHERE run_id = %s {mode})"
    " SELECT l.owner, l.fence, l.lease_until = '-infinity' AS released,"
    " l.lease_until > app.current_time() AS live FROM l"
)
LOCK_FOR_UPDATE: Final = _LOCK.format(mode="FOR UPDATE")  # writes the row: acquisition, renewal, release (SA:191)
LOCK_FOR_UPDATE_NOWAIT: Final = _LOCK.format(mode="FOR UPDATE NOWAIT")  # the claim's acquisition (ruling 3)
LOCK_FOR_SHARE: Final = _LOCK.format(mode="FOR SHARE")  # every other writing unit (SA:176-184)
RENEW: Final = "UPDATE app.run_lease SET lease_until = app.current_time() + make_interval(secs => %s) WHERE run_id = %s"


class LeaseLost(Exception):
    """The run's lease is gone: another owner holds a newer fence, it expired, or its local deadline passed. The
    unit that raised it rolls back and the worker hands the job back (Plan H ruling 19)."""


@dataclass(frozen=True)
class Busy:
    """The run's lease could not be taken: `locked` when another transaction holds its row (SQLSTATE 55P03), else
    live under another claim. The job is deferred, never claimed (ruling 3)."""

    locked: bool


class Lease:
    """One held run lease. The event loop checks it before every effect; the heartbeat thread renews it; both go
    through one `threading.Lock`, so a re-fence and a renewal never see half of each other (T13 review note 2)."""

    def __init__(
        self,
        *,
        run_id: UUID,
        owner: str,
        fence: int,
        lease_seconds: int,
        started: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.run_id = run_id
        self.owner = owner
        self.lease_seconds = lease_seconds
        self.held_since = started  # the compute gate's start (ruling 17)
        self._clock = clock
        self._lock = threading.Lock()
        self._fence = fence
        self._deadline = started + lease_seconds - DEADLINE_MARGIN_SECONDS
        self._renewed_at = started
        self._refencing = False
        self._lost: str | None = None
        self._effects: dict[asyncio.Task[Any], asyncio.AbstractEventLoop] = {}
        self._effects_cancelled = False

    @property
    def fence(self) -> int:
        """The fence this owner writes under; it changes only through `end_refence`."""
        with self._lock:
            return self._fence

    @property
    def deadline(self) -> float:
        """The monotonic instant after which no effect may start (SA:195)."""
        with self._lock:
            return self._deadline

    @property
    def renewed_at(self) -> float:
        """The monotonic instant before the last acquiring or renewing statement."""
        with self._lock:
            return self._renewed_at

    @property
    def lost(self) -> str | None:
        """Why the lease ended (`RELEASED` after the final unit), or None while it is held."""
        with self._lock:
            return self._lost

    @property
    def refencing(self) -> bool:
        """True between `begin_refence` and `end_refence`."""
        with self._lock:
            return self._refencing

    def check(self) -> None:
        """Raise LeaseLost unless the lease is held and its local deadline is still ahead; called before every fenced
        unit, and by `effect` before every MCP call and model call (ruling 18)."""
        with self._lock:
            reason = self._why_not_held()
        if reason is not None:
            raise LeaseLost(reason)

    def _why_not_held(self) -> str | None:
        """Why nothing may start now, or None while the lease is held; the caller holds `_lock`."""
        if self._lost is None and self._clock() >= self._deadline:
            self._lost = "local deadline passed"
        return self._lost

    async def effect[T](self, call: Coroutine[Any, Any, T]) -> T:
        """Run one effect (an MCP call, a model call, the permit's back-off sleep; never a database unit) as a child
        task the heartbeat thread may cancel (ruling 19 as amended in review round 1, B1).

        The check and the registration happen under the lease's lock, so `cancel_effects` either sees the task or the
        task sees the loss; a refused `call` is closed unstarted. A cancellation by `cancel_effects`, in whatever form
        the call surfaces it (an MCP client may wrap it in an exception group), reaches the caller as LeaseLost; a
        cancellation of the caller's own task (the worker stopping) propagates unchanged.

        Raises:
            LeaseLost: the lease was lost or its local deadline passed, before the effect started or while it ran.
        """
        loop = asyncio.get_running_loop()
        with self._lock:
            reason = self._why_not_held()
            task = None if reason is not None else loop.create_task(call)
            if task is not None:
                self._effects[task] = loop
        if task is None:
            call.close()  # never started, so never awaited
            raise LeaseLost(reason)
        try:
            return await task
        except BaseException:  # re-raised as it came unless this lease's loss cancelled the effect
            current = asyncio.current_task()
            stopping = current is not None and current.cancelling() > 0
            with self._lock:
                cancelled_for_loss = self._effects_cancelled
            if cancelled_for_loss and not stopping:
                raise LeaseLost(self.lost or "run lease lost") from None
            raise
        finally:
            with self._lock:
                self._effects.pop(task, None)

    def cancel_effects(self) -> int:
        """Cancel every effect in flight, from any thread (the heartbeat calls it after `mark_lost`): each child task
        is cancelled on its own loop through `call_soon_threadsafe`. Database units are never registered here, so a
        loss never interrupts one. Returns how many effects it cancelled."""
        with self._lock:
            self._effects_cancelled = True
            effects = list(self._effects.items())
        for task, loop in effects:
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:  # that loop has already closed (shutdown): nothing is left to cancel
                pass
        return len(effects)

    def renewed(self, started: float) -> None:
        """A renewal that began at `started` (monotonic) committed: the deadline moves with it."""
        with self._lock:
            self._deadline = started + self.lease_seconds - DEADLINE_MARGIN_SECONDS
            self._renewed_at = started

    def mark_lost(self, reason: str) -> bool:
        """Record why the lease ended; True only for the call that recorded it (the first reason stands)."""
        with self._lock:
            if self._lost is not None:
                return False
            self._lost = reason
            return True

    def begin_refence(self) -> None:
        """The owner is about to move its own fence (`mark_unknown`, ruling 9): until `end_refence`, a renewal that
        meets another fence retries instead of declaring the lease lost (ruling 10)."""
        with self._lock:
            self._refencing = True

    def end_refence(self, fence: int | None) -> None:
        """Hand over the fence the bump committed (None when it was refused and the fence stayed)."""
        with self._lock:
            if fence is not None:
                self._fence = fence
            self._refencing = False

    def fence_moved_by_owner(self, used: int) -> bool:
        """After a renewal under fence `used` met another fence: True when the owner moved it itself (a re-fence is
        pending, or the shared fence already differs from `used`), so the renewal retries with the current fence."""
        with self._lock:
            return self._refencing or self._fence != used
```

- [ ] **Step 3: The lease helpers in `persistence`**

In `core/src/ops_core/persistence.py`:

Edit 1 (old line 8), replace:

```python
nothing otherwise, and a reused connection's setting is '' between units (spike §1, §2). Pools arrive with T13.
```

with:

```python
nothing otherwise, and a reused connection's setting is '' between units (spike §1, §2). Pools arrive with T30.
```

Edit 2 (old lines 13-31), replace:

```python
import asyncio
import logging
import secrets
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import DictRow, dict_row
from psycopg.types.json import Jsonb

from ops_core.canonical import sha256_hex
from ops_core.jobs import JOB_RULES, JobType, Server, Tool, dedup_key
from ops_core.outcomes import ActionOutcome, EventRuleViolation, EventSource, EventType, ToolOutcome
from ops_core.settings import Postgres, Profile
from ops_core.states import IllegalTransition, Intent, Reason, RunState
```

with:

```python
import asyncio
import logging
import secrets
import time
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import DictRow, dict_row
from psycopg.types.json import Jsonb

from ops_core.canonical import sha256_hex
from ops_core.jobs import JOB_RULES, JobType, Server, Tool, dedup_key
from ops_core.lease import LOCK_FOR_SHARE, LOCK_FOR_UPDATE, LOCK_FOR_UPDATE_NOWAIT, RELEASED, Busy, Lease, LeaseLost
from ops_core.outcomes import ActionOutcome, EventRuleViolation, EventSource, EventType, ToolOutcome
from ops_core.settings import Postgres, Profile
from ops_core.states import IllegalTransition, Intent, Reason, RunState
```

Edit 3 (old line 139), replace:

```python
    re-entrant); callers pass the `conn` a unit yields instead. TODO(T13): a pool."""
```

with:

```python
    re-entrant); callers pass the `conn` a unit yields instead. TODO(T30): a pool (Plan H ruling 25)."""
```

Edit 4 (old lines 282-285), replace:

```python
async def revoke_handles(conn: Conn, run_id: UUID) -> int:
    """Every live handle of the run is revoked (BS:364); the fence argument is T13's."""
    row = await _call(conn, "SELECT app.revoke_handles(%s, 1) AS n", (run_id,))
    return 0 if row is None else int(row["n"])
```

with:

```python
async def revoke_handles(conn: Conn, run_id: UUID, fence: int) -> int:
    """Revoke the run's live handles minted under `fence` or an older one (BS:364, Plan H ruling 8): a newer owner's
    handles survive, and a stale fence is never refused (revoking only removes authority). Returns the count."""
    row = await _call(conn, "SELECT app.revoke_handles(%s, %s) AS n", (run_id, fence))
    return 0 if row is None else int(row["n"])
```

Edit 5 (old lines 538-559), replace the whole `claim_job` function

```python
async def claim_job(conn: Conn, *, worker_name: str, tenant_ids: Sequence[UUID]) -> DictRow | None:
    """Claim the oldest available job of the first tenant that has one (BUILD_SPEC §11: SKIP LOCKED).

    jobs is under tenant_isolation for the worker (only the sweeper has sweeper_all), so the claim runs once per
    tenant with the tenant set (Plan E ruling 18); the caller rotates the order. Runs inside a transaction so the
    settings last exactly as long as the claim; `set_tenant` refuses outside a transaction. On return the
    transaction's tenant stays set to the claimed job's tenant (or the last one tried). TODO(T13): lease + fence +
    wake-ups instead of polling.
    """
    for tenant_id in tenant_ids:
        await set_tenant(conn, tenant_id)
        cur = await conn.execute(
            "UPDATE app.jobs SET claimed_by = %s, claimed_at = app.current_time(), attempts = attempts + 1"
            " WHERE id = (SELECT id FROM app.jobs WHERE done_at IS NULL AND claimed_at IS NULL"
            "             AND available_at <= app.current_time()"
            "             ORDER BY available_at, id FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *",
            (worker_name,),
        )
        row = await cur.fetchone()
        if row is not None:
            return row
    return None
```

with:

```python
@dataclass(frozen=True)
class Claimed:
    """A claimed job and the run lease its claim took in the same transaction (Plan H ruling 3)."""

    job: DictRow
    lease: Lease


@dataclass(frozen=True)
class Deferred:
    """A job whose run lease was busy: moved behind the lease, not claimed (ruling 3)."""

    job_id: UUID


class _Held(Exception):
    """Raised inside the acquisition savepoint to roll it back when the lease is live under another claim."""


class _Locked(Exception):
    """Raised inside the acquisition savepoint to roll it back when NOWAIT met a row another transaction holds."""


_CREATE_LEASE = (
    "INSERT INTO app.run_lease (run_id, owner, lease_until, fence) VALUES (%s, '', '-infinity', 0)"
    " ON CONFLICT (run_id) DO NOTHING"
)
_TAKE_LEASE = (
    "UPDATE app.run_lease SET owner = %s, fence = fence + 1,"
    " lease_until = app.current_time() + make_interval(secs => %s) WHERE run_id = %s RETURNING fence"
)


async def _lock_row(conn: Conn, lock: str, run_id: UUID, *, wait: bool) -> psycopg.AsyncCursor[DictRow]:
    """One of the acquisition's lock statements: with NOWAIT, a row another transaction holds is a busy lease
    (`_Locked`, ruling 3); with `wait=True` the 55P03 of a wait past `lock_timeout` propagates (review round 2, N2:
    both lock statements go through here, the one after the first-row INSERT included)."""
    try:
        return await conn.execute(lock, (run_id,))
    except psycopg.errors.LockNotAvailable:
        if wait:
            raise  # a long lock wait, which the stress test counts, never a busy lease
        raise _Locked from None  # NOWAIT met a held row: busy (ruling 3)


async def acquire_lease(
    conn: Conn,
    *,
    run_id: UUID,
    owner: str,
    lease_seconds: int,
    wait: bool = False,
    clock: Callable[[], float] = time.monotonic,
) -> Lease | Busy:
    """Take the run's lease inside the caller's transaction (AM-12 SA:173-174, Plan H rulings 2 and 3).

    In a savepoint, so a busy lease rolls back alone and the caller's claim survives: the lease row FOR UPDATE NOWAIT
    (plain FOR UPDATE with `wait=True`, which only the interleaving and stress tests use; there a lock wait past the
    connection's `lock_timeout` raises 55P03 instead of looking like a busy lease, review round 1 I3), free when
    `lease_until <= app.current_time()` compared after the lock, then `fence + 1`, the new owner and a fresh
    `lease_until`. The row is
    locked before anything is inserted, because an `INSERT … ON CONFLICT` waits for an in-progress update of an
    existing row (a renewal, a release) and NOWAIT exists to avoid waits; it is created released (fence 0, so the
    first real fence is 1) only when absent, and a concurrent first insert of the same run is the one wait left
    (erratum 46).

    Returns:
        The Lease, whose local deadline counts from the monotonic instant before the first statement (ruling 18);
        `Busy(locked=True)` when NOWAIT met a row another transaction holds, `Busy(locked=False)` when the lease is
        live.

    Raises:
        psycopg.errors.LockNotAvailable: a wait (`wait=True`, or the first-row INSERT racing another first insert)
            outlasted the connection's `lock_timeout`.
    """
    started = clock()
    lock = LOCK_FOR_UPDATE if wait else LOCK_FOR_UPDATE_NOWAIT
    taken: DictRow | None = None
    try:
        async with conn.transaction():
            cur = await _lock_row(conn, lock, run_id, wait=wait)
            row = await cur.fetchone()
            if row is None:
                await conn.execute(_CREATE_LEASE, (run_id,))
                cur = await _lock_row(conn, lock, run_id, wait=wait)
                row = await cur.fetchone()
                if row is None:
                    raise PersistenceError("the run's lease row is missing after its insert")
            if row["live"]:
                raise _Held
            cur = await conn.execute(_TAKE_LEASE, (owner, lease_seconds, run_id))
            taken = await cur.fetchone()
    except _Held:
        return Busy(locked=False)
    except _Locked:
        return Busy(locked=True)
    if taken is None:
        raise PersistenceError("the lease update returned nothing")
    return Lease(
        run_id=run_id, owner=owner, fence=int(taken["fence"]), lease_seconds=lease_seconds, started=started, clock=clock
    )


async def pick_job(conn: Conn, *, tenant_ids: Sequence[UUID]) -> DictRow | None:
    """The oldest available job of the first tenant that has one, row-locked with SKIP LOCKED (BUILD_SPEC §11) until
    the caller's transaction claims or defers it.

    jobs is under tenant_isolation for the worker (only the sweeper has sweeper_all), so the pick runs once per tenant
    with the tenant set (Plan E ruling 18); `set_tenant` refuses outside a transaction, and on return the
    transaction's tenant is the picked job's (or the last one tried).
    """
    for tenant_id in tenant_ids:
        await set_tenant(conn, tenant_id)
        cur = await conn.execute(
            "SELECT * FROM app.jobs WHERE done_at IS NULL AND claimed_at IS NULL"
            " AND available_at <= app.current_time() ORDER BY available_at, id FOR UPDATE SKIP LOCKED LIMIT 1"
        )
        row = await cur.fetchone()
        if row is not None:
            return row
    return None


async def claim_next(
    conn: Conn,
    *,
    worker_name: str,
    tenant_ids: Sequence[UUID],
    lease_seconds: int,
    clock: Callable[[], float] = time.monotonic,
) -> Claimed | Deferred | None:
    """Claim the next job together with its run's lease, in one transaction (Plan H ruling 3).

    Claim and lease commit together, so a claimed run job always has a live lease taken at the same commit: no crash
    window lies between them, and "claimed, not done, lease not live" can only mean a dead or lost owner (the
    sweeper's reclaim, ruling 11). A job whose lease is busy is moved behind it and left unclaimed: to the live
    lease's `lease_until`, or one second on when the lease row was locked; jobs are wake-ups (SA:173), so whoever
    claims it later finds the run in the state the lease holder left. The moved job is not available again in the
    same poll, so the caller simply tries again. TODO(T14): wake-ups instead of polling.
    """
    async with conn.transaction():
        job = await pick_job(conn, tenant_ids=tenant_ids)
        if job is None:
            return None
        if job["run_id"] is None:
            # Maintenance jobs carry no tenant and RLS hides them from the worker; one here is a policy fault.
            raise PersistenceError("the worker picked a job without a run")
        got = await acquire_lease(
            conn, run_id=job["run_id"], owner=worker_name, lease_seconds=lease_seconds, clock=clock
        )
        if isinstance(got, Busy):
            if got.locked:
                await conn.execute(
                    "UPDATE app.jobs SET available_at = app.current_time() + interval '1 second' WHERE id = %s",
                    (job["id"],),
                )
            else:
                await conn.execute(
                    "UPDATE app.jobs SET available_at = coalesce((SELECT l.lease_until FROM app.run_lease l"
                    " WHERE l.run_id = %s AND l.lease_until > app.current_time()),"
                    " app.current_time() + interval '1 second') WHERE id = %s",
                    (job["run_id"], job["id"]),
                )
            return Deferred(UUID(str(job["id"])))
        cur = await conn.execute(
            "UPDATE app.jobs SET claimed_by = %s, claimed_at = app.current_time(), attempts = attempts + 1"
            " WHERE id = %s RETURNING *",
            (worker_name, job["id"]),
        )
        claimed = await cur.fetchone()
        if claimed is None:
            raise PersistenceError("the picked job vanished before its claim")
        return Claimed(claimed, got)


async def fenced(conn: Conn, lease: Lease) -> None:
    """The first statement of every worker unit that writes for a run (AM-12 SA:176-184, Plan H ruling 5).

    The lease row FOR SHARE, then owner, fence and expiry compared after the lock: a new owner's acquisition (FOR
    UPDATE) waits for this transaction, so nothing this unit writes can land after a newer fence. A mismatch marks the
    lease lost and raises LeaseLost, and the unit rolls back. `set_tenant` may come first: `set_config` takes no
    lock. The local deadline is checked before the statement (ruling 18).
    """
    lease.check()
    cur = await conn.execute(LOCK_FOR_SHARE, (lease.run_id,))
    row = await cur.fetchone()
    if row is None or row["owner"] != lease.owner or row["fence"] != lease.fence or not row["live"]:
        lease.mark_lost("the fence moved or the lease expired")
        raise LeaseLost("run lease lost")


async def release_lease(conn: Conn, lease: Lease, *, job: dict[str, Any], requeue_seconds: int | None = None) -> None:
    """The job's final unit (Plan H ruling 28): the lease row FOR UPDATE (this unit writes it, SA:191), owner and fence
    compared, the handles minted under this fence revoked, the job finished (or re-queued after `requeue_seconds`)
    and the lease released (`lease_until = '-infinity'`; owner and fence stay, so the run's next acquisition takes
    fence + 1). Together, so a crash leaves either the claimed job with its lease or neither.

    Raises:
        LeaseLost: another owner holds the lease now; nothing is written.
    """
    async with conn.transaction():
        await set_tenant(conn, job["tenant_id"])  # jobs is under RLS; set_config takes no lock
        cur = await conn.execute(LOCK_FOR_UPDATE, (lease.run_id,))
        row = await cur.fetchone()
        if row is None or row["owner"] != lease.owner or row["fence"] != lease.fence:
            lease.mark_lost("another owner holds the lease")
            raise LeaseLost("run lease lost")
        await revoke_handles(conn, lease.run_id, lease.fence)
        if requeue_seconds is None:
            await finish_job(conn, job["id"])
        else:
            await requeue_job(conn, job["id"], requeue_seconds)
        await conn.execute("UPDATE app.run_lease SET lease_until = '-infinity' WHERE run_id = %s", (lease.run_id,))
    lease.mark_lost(RELEASED)


async def unclaim_job(conn: Conn, job_id: UUID, *, worker_name: str) -> None:
    """Hand a claimed job back, claimable now (ruling 19: jobs are wake-ups), unless another worker claimed it since."""
    await conn.execute(
        "UPDATE app.jobs SET claimed_by = NULL, claimed_at = NULL, available_at = app.current_time()"
        " WHERE id = %s AND claimed_by = %s AND done_at IS NULL",
        (job_id, worker_name),
    )
```

Edit 6 (old lines 567-568), replace:

```python
async def requeue_job(conn: Conn, job_id: UUID, delay_seconds: int) -> None:
    """Release a claimed job and make it claimable again after `delay_seconds`. TODO(T13): bounded retries."""
```

with:

```python
async def requeue_job(conn: Conn, job_id: UUID, delay_seconds: int) -> None:
    """Release a claimed job and make it claimable again after `delay_seconds`. TODO(T22): bounded retries."""
```

Edit 7 (old lines 613-623), replace:

```python
async def mint_handle(
    conn: Conn, *, run_id: UUID, job_id: UUID, server: Server, azp: str, ttl_seconds: int = 60
) -> str:
    """A 256-bit capability bound to one job and one server (BUILD_SPEC §9); only its hash is stored (BS:360)."""
    handle = secrets.token_urlsafe(32)
    await conn.execute(
        "INSERT INTO app.invocation_context (handle_sha256, run_id, job_id, server, azp, expires_at)"
        " VALUES (%s, %s, %s, %s, %s, app.current_time() + make_interval(secs => %s))",
        (handle_hash(handle), run_id, job_id, server.value, azp, ttl_seconds),
    )
    return handle
```

with:

```python
async def mint_handle(
    conn: Conn, *, run_id: UUID, job_id: UUID, server: Server, azp: str, fence: int, ttl_seconds: int = 60
) -> str:
    """A 256-bit capability bound to one job, one server and the lease fence it was minted under (BUILD_SPEC §9,
    BS:360); only its hash is stored. It expires after `ttl_seconds` or with the lease, whichever comes first
    (BS:558), and is minted only under a live lease at exactly that fence (Plan H ruling 5).

    Raises:
        LeaseLost: the run has no live lease at `fence`; nothing is written.
    """
    handle = secrets.token_urlsafe(32)
    cur = await conn.execute(
        "INSERT INTO app.invocation_context (handle_sha256, run_id, job_id, server, azp, fence, expires_at)"
        " SELECT %s, l.run_id, %s, %s, %s, l.fence,"
        " least(app.current_time() + make_interval(secs => %s), l.lease_until)"
        " FROM app.run_lease l WHERE l.run_id = %s AND l.fence = %s AND l.lease_until > app.current_time()",
        (handle_hash(handle), job_id, server.value, azp, ttl_seconds, run_id, fence),
    )
    if cur.rowcount != 1:
        raise LeaseLost("no live lease at this fence")
    return handle
```

- [ ] **Step 4: The worker under its lease**

Replace the whole of `worker/src/ops_worker/handlers.py` with:

```python
"""Job handlers (AM-20.4 job types; AM-10 states): every state change goes through the definer functions as role
`worker` (`transition_run`, `freeze_proposal`, `mark_unknown`), and every network call happens outside a transaction
(BUILD_SPEC §11).

`investigate`: QUEUED → RETRIEVING → (read tool) → DRAFTING → fake draft → freeze → AWAITING_APPROVAL. `execute`: mint
a write handle and call `create_incident`; mcp-write performs the grant, the dispatch and the outcome, while the
worker records an UNKNOWN envelope through `mark_unknown`. Every handler runs under the run lease its claim took
(AM-12, T13): each unit that writes for the run opens with `persistence.fenced` (the lease row FOR SHARE; owner, fence
and expiry compared after the lock), every MCP and model call runs as a lease effect (`Lease.effect`: none starts past
the lease's local deadline, SA:195, and a lost lease cancels it; database units are never cancelled), and the job's
final unit revokes the job's handles, closes the job and releases the lease together (`persistence.release_lease`). A
lost lease raises LeaseLost to the caller, which hands the job back (`abandon`). No LangGraph (→ T20).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
from ops_core import persistence
from ops_core.jobs import JOB_RULES, JobType, Server
from ops_core.lease import Lease, LeaseLost
from ops_core.outcomes import EventSource, EventType
from ops_core.settings import LeaseSettings, Urls
from ops_core.states import Intent, RunState, freeze_allowed
from psycopg.pq import TransactionStatus

from ops_worker import proposals
from ops_worker.drafting import DraftGenerator, DraftRequest, EvidenceItem
from ops_worker.mcp import McpCaller, McpCallFailed

log = logging.getLogger("ops_worker")
EXECUTE_RETRY_SECONDS = 30  # how long an execute job waits after mcp-write could not be reached
QUERY_CHARS = 500  # schemas/tools/search_procedures.input.schema.json maxLength
INTERRUPTED = "interrupted; the run was not resumed"  # TODO(T20): resume from the checkpoint instead


def is_deferred(doc: dict[str, Any]) -> bool:
    """An `error` envelope whose code is GRANT_DEFERRED: the gate found the membership sync stale (T11), so the job
    is retried rather than closed."""
    error = doc.get("error") or {}
    return doc.get("status") == "error" and error.get("code") == "GRANT_DEFERRED"


@dataclass
class Deps:
    """What a handler needs: the loop's connection, the MCP client, the model route, the server URLs, the worker's
    name (the lease owner) and the lease settings."""

    conn: persistence.Conn
    mcp: McpCaller
    generator: DraftGenerator
    urls: Urls
    worker_name: str
    leases: LeaseSettings = field(default_factory=LeaseSettings)


async def _event(
    deps: Deps,
    lease: Lease,
    type: EventType,
    payload: dict[str, Any],
    source: EventSource = EventSource.APPLICATION,
) -> None:
    """One event in its own fenced unit; the function finds the tenant itself (run_directory)."""
    async with deps.conn.transaction():
        await persistence.fenced(deps.conn, lease)
        await persistence.append_event(deps.conn, run_id=lease.run_id, type=type, payload=payload, source=source)


async def _fail(deps: Deps, lease: Lease, src: RunState, dst: RunState, message: str) -> None:
    """A pre-grant failure state through transition_run, which emits the matching run.* event itself (SA:451)."""
    async with deps.conn.transaction():
        await persistence.fenced(deps.conn, lease)
        await persistence.transition_run(deps.conn, run_id=lease.run_id, src=src, dst=dst, detail={"message": message})


async def investigate(deps: Deps, job: dict[str, Any], lease: Lease) -> None:
    """Retrieve evidence, draft with the model route, freeze the proposal and await approval."""
    tenant_id: UUID = job["tenant_id"]
    async with deps.conn.transaction():
        await persistence.set_tenant(deps.conn, tenant_id)  # the worker's own reads and inserts are RLS-scoped
        await persistence.fenced(deps.conn, lease)  # run_lease before runs (SA:188, ruling 29)
        run = dict(await persistence.run_row(deps.conn, job["run_id"], lock=True))
        state = RunState(run["state"])
        if state in (RunState.RETRIEVING, RunState.DRAFTING):
            # A previous holder was interrupted (a lost lease, a crash, a lock timeout) and nothing resumes a run yet:
            # fail it, which frees its conversation slot, rather than close the job and leave the run active for good.
            log.warning("investigate job %s: run was interrupted in %s; failed", job["id"], state.value)
            await persistence.transition_run(
                deps.conn, run_id=run["run_id"], src=state, dst=RunState.FAILED, detail={"message": INTERRUPTED}
            )
            return
        if state is not RunState.QUEUED:
            log.info("investigate job %s: run already %s", job["id"], run["state"])
            return
        cur = await deps.conn.execute("SELECT text FROM app.messages WHERE message_id = %s", (run["message_id"],))
        message = await cur.fetchone()
        if message is None:
            raise persistence.NotFound("message not found")
        text = str(message["text"])
        await persistence.transition_run(deps.conn, run_id=run["run_id"], src=RunState.QUEUED, dst=RunState.RETRIEVING)
        handle = await persistence.mint_handle(
            deps.conn, run_id=run["run_id"], job_id=job["id"], server=Server.READ, azp="ops-worker", fence=lease.fence
        )
    await _event(deps, lease, EventType.TOOL_STARTED, {"message": "search_procedures"})
    try:
        # An MCP call is an effect: none starts past the local deadline (SA:195), and a lost lease cancels it.
        # The tool input caps `query` at 500 characters (schemas/tools); the message itself may be 4,000.
        doc = await lease.effect(
            deps.mcp.call(
                deps.urls.mcp_read,
                handle=handle,
                tool="search_procedures",
                arguments={"query": text[:QUERY_CHARS], "limit": 3, "mode": "lexical"},
            )
        )
        evidence = proposals.evidence_from_search(doc)
    except (McpCallFailed, ValueError) as exc:
        log.warning("investigate job %s: retrieval failed: %s", job["id"], exc)
        await _fail(deps, lease, RunState.RETRIEVING, RunState.FAILED, "retrieval failed")
        return
    await _event(deps, lease, EventType.TOOL_COMPLETED, {"message": "search_procedures"})
    if not evidence:
        await _fail(deps, lease, RunState.RETRIEVING, RunState.INSUFFICIENT_EVIDENCE, "no procedure section matched")
        return
    async with deps.conn.transaction():
        await persistence.fenced(deps.conn, lease)
        await persistence.transition_run(
            deps.conn, run_id=run["run_id"], src=RunState.RETRIEVING, dst=RunState.DRAFTING
        )
    try:
        await _draft_and_freeze(deps, lease, run, text, evidence, str(doc["data"]["corpus_version"]))
    except LeaseLost:
        raise  # the lease is gone: the job is handed back, and its next owner fails the interrupted run (INTERRUPTED)
    except Exception:
        # A failure here fails the run at once with its own reason; handed back instead, the next owner would only
        # find the run interrupted in DRAFTING and fail it as INTERRUPTED.
        log.exception("investigate job %s: drafting or freezing failed", job["id"])
        await _fail(deps, lease, RunState.DRAFTING, RunState.FAILED, "drafting failed")


async def _draft_and_freeze(
    deps: Deps, lease: Lease, run: dict[str, Any], text: str, evidence: list[EvidenceItem], corpus_version: str
) -> None:
    """Draft from the evidence and freeze the proposal; any failure here is the caller's to turn into FAILED."""
    request = DraftRequest(asset_id=run["asset_id"], text=text, start_at=run["start_at"], end_at=run["end_at"])
    draft = await lease.effect(deps.generator.generate(request, evidence))  # a model call is an effect too (SA:195)
    freeze_allowed(Intent(run["intent"]))  # an answer_only run never freezes a proposal (SA:453)
    now = datetime.now(UTC).replace(microsecond=0)
    proposal_id, draft_id = uuid4(), uuid4()
    frozen = proposals.build_proposal(
        tenant_id=run["tenant_id"],
        run_id=run["run_id"],
        proposal_id=proposal_id,
        revision=1,
        asset_id=run["asset_id"],
        start_at=run["start_at"],
        end_at=run["end_at"],
        draft=draft,
        evidence=evidence,
        corpus_version=corpus_version,
        now=now,
        supersedes_run_id=run["supersedes_run_id"],
    )
    async with deps.conn.transaction():
        await persistence.set_tenant(deps.conn, run["tenant_id"])
        # The share lock before anything else (SA:453's run_lease FOR SHARE, taken here rather than inside
        # freeze_proposal, erratum 47); the drafts INSERT is a fresh row and waits on nobody.
        await persistence.fenced(deps.conn, lease)
        # The worker's own INSERT (AM-20.2 drafts: ins); draft_sha256 is what freeze_proposal recomputes over the
        # bytes it receives and compares (SA:453). The payload itself is never written here (SA:496).
        await deps.conn.execute(
            "INSERT INTO app.drafts (id, tenant_id, run_id, draft_sha256, validated, kind)"
            " VALUES (%s, %s, %s, %s, true, %s)",
            (draft_id, run["tenant_id"], run["run_id"], frozen.sha256, draft.kind),
        )
        await persistence.append_event(
            deps.conn,
            run_id=run["run_id"],
            type=EventType.EXPLANATION_READY,
            payload={
                "message": f"Drafted by model route {frozen.manifest.model_route.value} "
                f"(prompt {frozen.manifest.prompt_version}).",
                "evidence_refs": list(frozen.payload.evidence_refs),
            },
            source=EventSource.MODEL_SUMMARY,
        )
        await persistence.freeze_proposal(
            deps.conn,
            run_id=run["run_id"],
            draft_id=draft_id,
            payload_canonical=frozen.canonical,
            expires_at=frozen.payload.expires_at,
        )


async def execute(deps: Deps, job: dict[str, Any], lease: Lease) -> bool:
    """Call `create_incident` on mcp-write for an approved run; True when the job is finished by `handle`, False when
    it was re-queued (its final unit already ran and released the lease)."""
    async with deps.conn.transaction():
        await persistence.set_tenant(deps.conn, job["tenant_id"])
        await persistence.fenced(deps.conn, lease)
        run = dict(await persistence.run_row(deps.conn, job["run_id"], lock=True))
        # APPROVED or EXECUTING (JOB_RULES[EXECUTE].run_states): after a transport failure past the grant, the
        # re-queued job resends under the same action id (grant_execution's replay rule; Plan E ruling 6).
        if RunState(run["state"]) not in JOB_RULES[JobType.EXECUTE].run_states:
            log.info("execute job %s: run is %s, nothing to dispatch", job["id"], run["state"])
            return True
        proposal_id: UUID = run["active_proposal_id"]
        handle = await persistence.mint_handle(
            deps.conn, run_id=run["run_id"], job_id=job["id"], server=Server.WRITE, azp="ops-worker", fence=lease.fence
        )
    try:
        doc = await lease.effect(
            deps.mcp.call(
                deps.urls.mcp_write, handle=handle, tool="create_incident", arguments={"proposal_id": str(proposal_id)}
            )
        )
    except McpCallFailed as exc:
        # mcp-write owns the grant and the outcome. Before a grant the run is still APPROVED; after one it is EXECUTING
        # and the retry resends under the same action id, which is safe because the grant is one per run. The worker
        # records nothing it did not observe (BUILD_SPEC §1). TODO(T22): bounded retries, reconciliation and AM-13's
        # timeout path (the run is APPROVED or EXECUTING, which the worker may not move, SA:451).
        log.warning("execute job %s: %s; re-queued in %s s", job["id"], exc, EXECUTE_RETRY_SECONDS)
        await persistence.release_lease(deps.conn, lease, job=job, requeue_seconds=EXECUTE_RETRY_SECONDS)
        return False
    data = doc.get("data") or {}
    if is_deferred(doc):
        # TODO(T22): bounded retries (a sweeper that never returns re-queues this job every 30 s for ever).
        log.warning(
            "execute job %s: grant deferred (stale membership sync); re-queued in %s s",
            job["id"],
            EXECUTE_RETRY_SECONDS,
        )
        await persistence.release_lease(deps.conn, lease, job=job, requeue_seconds=EXECUTE_RETRY_SECONDS)
        return False
    log.info("execute job %s: %s %s", job["id"], doc.get("status"), data.get("status"))
    if doc.get("status") == "outcome" and data.get("status") == "UNKNOWN":  # an `error` envelope is never UNKNOWN
        # mcp-write reports uncertainty after SENT but may not record it (SA:467: mark_unknown is the worker's).
        async with deps.conn.transaction():
            await persistence.fenced(deps.conn, lease)
            await persistence.mark_unknown(deps.conn, run["run_id"])
    return True


async def handle(deps: Deps, job: dict[str, Any], lease: Lease) -> None:
    """Dispatch a claimed job by type under its lease; the final unit closes the job and releases the lease."""
    kind = JobType(job["type"])
    if kind is JobType.INVESTIGATE:
        await investigate(deps, job, lease)
    elif kind is JobType.EXECUTE:
        if not await execute(deps, job, lease):
            return  # re-queued: its final unit already released the lease
    else:
        log.info("job %s of type %s is not handled by the walking skeleton", job["id"], kind.value)
    await persistence.release_lease(deps.conn, lease, job=job)


async def abandon(deps: Deps, job: dict[str, Any], lease: Lease) -> None:
    """The lease is lost (Plan H ruling 19): revoke the handles minted under this fence and hand the job back, in one
    unit, with no transition here (the next owner fails a run it finds interrupted, INTERRUPTED). `revoke_handles`
    never refuses a stale fence (ruling
    8), so this works whoever holds the lease now.

    Raises:
        psycopg.OperationalError: the loop connection was not idle. Only effects are ever cancelled, so this should
            not happen; if it does, a hand-back on that connection would nest in the open transaction and never
            commit, so the connection is closed instead, the poll loop ends and the supervisor restarts the worker
            (review round 1, B1).
    """
    if deps.conn.info.transaction_status is not TransactionStatus.IDLE:
        await deps.conn.close()
        raise psycopg.OperationalError("the loop connection was not idle when its lease was lost; it was closed")
    async with deps.conn.transaction():
        await persistence.set_tenant(deps.conn, job["tenant_id"])  # jobs is under RLS
        await persistence.revoke_handles(deps.conn, lease.run_id, lease.fence)
        await persistence.unclaim_job(deps.conn, job["id"], worker_name=deps.worker_name)
```

Replace the whole of `worker/src/ops_worker/main.py` with:

```python
"""The worker process: a polling loop beside a health server, two connections (the loop's and the probe's),
SelectorEventLoop on Windows (psycopg async refuses the Proactor loop; measured in the Plan D spike).

Each poll claims the next job together with its run's lease (`persistence.claim_next`, Plan H ruling 3) and runs the
handler under that lease; a lost lease hands the job back (`handlers.abandon`, ruling 19) and the loop moves on."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import sys
from collections.abc import Callable
from uuid import UUID

import psycopg
import uvicorn
from ops_core import persistence, redaction, settings
from ops_core.lease import LeaseLost
from ops_core.settings import Role
from ops_core.tokens import WorkloadTokenSource
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ops_worker import handlers
from ops_worker.drafting import make_generator
from ops_worker.mcp import HttpMcpCaller

POLL_SECONDS = 0.5
MAX_DEFERRALS = 16  # busy-lease deferrals one poll makes before it sleeps (each moves one job behind its lease)
# Bounds every unit's lock wait on the loop connection (review round 2, m1); SET takes no bind parameter.
LOOP_LOCK_TIMEOUT = "SET lock_timeout = '10s'"
log = logging.getLogger("ops_worker")


def rotate(tenants: list[UUID], start: int) -> list[UUID]:
    """The tenants in claim order for one poll: a different first tenant each time, so none starves (ruling 18)."""
    if not tenants:
        return []
    k = start % len(tenants)
    return tenants[k:] + tenants[:k]


async def claim(deps: handlers.Deps, order: list[UUID]) -> persistence.Claimed | None:
    """The next job with its run's lease, past at most MAX_DEFERRALS jobs whose run lease was busy (ruling 3)."""
    for _ in range(MAX_DEFERRALS):
        got = await persistence.claim_next(
            deps.conn, worker_name=deps.worker_name, tenant_ids=order, lease_seconds=deps.leases.lease_seconds
        )
        if not isinstance(got, persistence.Deferred):
            return got
    return None


async def run_job(deps: handlers.Deps, claimed: persistence.Claimed) -> None:
    """Run one claimed job under its lease; a lost lease hands the job back instead of failing the run (ruling 19).
    Any other exception propagates: the poll loop logs it, the job stays claimed, its lease lapses within one lease
    and the sweeper reclaims it."""
    job = dict(claimed.job)
    try:
        await handlers.handle(deps, job, claimed.lease)
    except LeaseLost:
        log.warning("job %s: run lease lost (%s); handles revoked, job handed back", job["id"], claimed.lease.lost)
        await handlers.abandon(deps, job, claimed.lease)


async def run_forever(deps: handlers.Deps, stop: asyncio.Event) -> None:
    """Claim, handle, repeat. A crashed handler is logged and keeps its job claimed until the lease lapses and the
    sweeper reclaims it; a broken connection ends the loop, and readiness follows it (see health_app)."""
    polls = 0
    while not stop.is_set():
        try:
            order = rotate(await persistence.tenants(deps.conn), polls)
            polls += 1
            claimed = await claim(deps, order)
            if claimed is not None:
                await run_job(deps, claimed)
                continue
        except psycopg.OperationalError:
            if deps.conn.broken or deps.conn.closed:
                log.exception("database connection lost; the poll loop stops and the process exits non-zero")
                raise
            log.exception("transient database error (deadlock, serialization); the loop continues")
        except Exception:  # a crashed handler keeps its job until the lease lapses and the sweeper reclaims it
            log.exception("poll iteration failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=POLL_SECONDS)
        except TimeoutError:
            pass


def health_app(probe: persistence.Conn, polling_alive: Callable[[], bool]) -> Starlette:
    """Readiness on its own connection and only while the poll loop runs: sharing the loop's connection let a health
    call wedge it idle-in-transaction, and a dead loop behind a 200 is the same lie (round-1 and round-2 reviews)."""

    async def live(_: Request) -> JSONResponse:
        return JSONResponse({"status": "live"})

    async def ready(_: Request) -> JSONResponse:
        if not polling_alive():
            return JSONResponse({"status": "not ready", "reason": "poll loop stopped"}, status_code=503)
        try:
            await probe.execute("SELECT 1")  # autocommit: no transaction is left open
        except (psycopg.Error, OSError):
            return JSONResponse({"status": "not ready"}, status_code=503)
        return JSONResponse({"status": "ready"})

    return Starlette(routes=[Route("/health/live", live), Route("/health/ready", ready)])


async def _main() -> None:
    # The redaction filter must sit on the root handler before the first log line (T11 note 4).
    redaction.install()
    generator = make_generator(settings.env("MODEL_MODE"))  # unset or any other route: refuse to start (R130)
    leases = settings.leases()  # an unsafe lease, heartbeat, stall or budget combination refuses to start
    kc = settings.keycloak()
    tokens = WorkloadTokenSource(
        token_url=kc.token_url,
        client_id="ops-worker",
        client_secret=settings.read_secret("kc_client_secret_ops_worker"),
    )
    conn = await persistence.connect(settings.app_postgres(Role.WORKER))
    # No unit is ever cancelled, so a unit stuck behind another transaction's lock ends after 10 s with 55P03, which
    # run_forever logs as transient; its job keeps the claim until the lease lapses and the sweeper reclaims it.
    await conn.execute(LOOP_LOCK_TIMEOUT)
    # The health server's own connection (see health_app).
    probe = await persistence.connect(settings.app_postgres(Role.WORKER))
    await persistence.assert_clock_profile(probe, settings.profile())
    deps = handlers.Deps(
        conn=conn,
        mcp=HttpMcpCaller(tokens),
        generator=generator,
        urls=settings.urls(),
        worker_name=f"{socket.gethostname()}:{os.getpid()}",
        leases=leases,
    )
    stop = asyncio.Event()
    polling = asyncio.create_task(run_forever(deps, stop), name="poll-loop")
    server = uvicorn.Server(
        uvicorn.Config(
            health_app(probe, lambda: not polling.done()),
            host="127.0.0.1",
            port=settings.env_int("OPS_WORKER_HEALTH_PORT", 8070),
            log_level="warning",
            log_config=None,
        )
    )
    serving = asyncio.create_task(server.serve(), name="health-server")
    try:
        # Whichever ends first ends the process: uvicorn on SIGINT/SIGTERM, the poll loop on a lost connection.
        await asyncio.wait({serving, polling}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        stop.set()
        server.should_exit = True
        await asyncio.gather(serving, polling, return_exceptions=True)
        await conn.close()
        await probe.close()
    # A supervisor restarts a worker that lost its database or its health server; exit 0 would hide either.
    for task in (polling, serving):
        if task.done() and not task.cancelled() and task.exception() is not None:
            raise SystemExit(1)


def main() -> None:
    """Run the worker until a signal or a lost database connection."""
    if sys.platform == "win32":
        asyncio.run(_main(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(_main())
```

Run: `uv run python -m pytest tests/plan_h/test_lease.py tests/plan_h/test_worker_units.py tests/plan_f/test_grant_deferred.py tests/plan_e/test_worker_rotate.py tests/plan_d/test_worker.py -q`
Expected: `45 passed` (`test_lease.py` 12, `test_worker_units.py` 8, Plan F's 3, the rotation module's 17, Plan D's
worker module 5). Format and lint `worker/src`, `core/src` and the test files.

- [ ] **Step 5: The live helpers and the evidence root**

In `tests/e2e/conftest.py`:

Edit 1 (old lines 9-20), replace:

```python
import asyncio
import os
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

import psycopg
import pytest
import pytest_asyncio
from ops_core import persistence, settings
from ops_core.settings import Profile, Role
from psycopg import sql
```

with:

```python
import asyncio
import os
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from uuid import UUID

import psycopg
import pytest
import pytest_asyncio
from ops_core import persistence, settings
from ops_core.lease import Lease
from ops_core.settings import Profile, Role
from psycopg import sql
```

Edit 2 (the end of the file), replace:

```python
async def purge_tenant(conn: persistence.Conn, tenant_id: object) -> None:
    if str(tenant_id) in SEEDED_TENANTS:
        return  # seeded by the migration; never deleted by a test
    async with conn.transaction():
        await conn.execute("DELETE FROM app.memberships WHERE tenant_id = %s", (tenant_id,))
        await conn.execute("DELETE FROM app.tenants WHERE tenant_id = %s", (tenant_id,))
```

with:

```python
async def purge_tenant(conn: persistence.Conn, tenant_id: object) -> None:
    if str(tenant_id) in SEEDED_TENANTS:
        return  # seeded by the migration; never deleted by a test
    async with conn.transaction():
        await conn.execute("DELETE FROM app.memberships WHERE tenant_id = %s", (tenant_id,))
        await conn.execute("DELETE FROM app.tenants WHERE tenant_id = %s", (tenant_id,))


async def lease_for(
    conn: persistence.Conn, run_id: UUID, *, owner: str = "live-test", seconds: int = 120, wait: bool = False
) -> Lease:
    """Take the run's lease on a `worker` connection in its own transaction (the claim's acquisition without a job)
    for a live test that mints a handle or runs a handler directly (T13); a busy lease fails the test."""
    async with conn.transaction():
        got = await persistence.acquire_lease(conn, run_id=run_id, owner=owner, lease_seconds=seconds, wait=wait)
    assert isinstance(got, Lease), got
    return got


async def expire_lease(conn: persistence.Conn, run_id: object) -> None:
    """End the run's lease on the database clock as the superuser (its owner stalled or died); the fence stays."""
    await conn.execute(
        "UPDATE app.run_lease SET lease_until = app.current_time() - interval '1 second' WHERE run_id = %s", (run_id,)
    )


async def backend_pid(conn: persistence.Conn) -> int:
    """The server process behind a connection, for `pg_blocking_pids`."""
    cur = await conn.execute("SELECT pg_backend_pid() AS pid")
    row = await cur.fetchone()
    assert row is not None
    return int(row["pid"])


async def wait_until_blocked(conn: persistence.Conn, pid: int, *, timeout: float = 5.0) -> list[int]:
    """The backends blocking `pid`, polled until there is one: a test that expects a lock wait and gets none fails
    here instead of passing by timing luck."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        cur = await conn.execute("SELECT pg_blocking_pids(%s) AS holders", (pid,))
        row = await cur.fetchone()
        if row is not None and row["holders"]:
            return [int(holder) for holder in row["holders"]]
        await asyncio.sleep(0.05)
    raise AssertionError(f"backend {pid} was never blocked")
```

In `tests/plan_b/test_evidence.py`:

Edit 1 (old lines 5-6), replace:

```python
`reports/auth` (T11's session and revocation evidence), `reports/ci` (T06's CI run record) and
`reports/admission` (T12's durable-admission evidence) are scanned the same way.
```

with:

```python
`reports/auth` (T11's session and revocation evidence), `reports/ci` (T06's CI run record),
`reports/admission` (T12's durable-admission evidence) and `reports/leases` (T13's lease, heartbeat and stress
evidence) are scanned the same way.
```

Edit 2 (old lines 17-23), replace:

```python
EVIDENCE_ROOTS = (
    Path("reports/bootstrap"),
    Path("reports/skeleton"),
    Path("reports/auth"),
    Path("reports/ci"),
    Path("reports/admission"),
)
```

with:

```python
EVIDENCE_ROOTS = (
    Path("reports/bootstrap"),
    Path("reports/skeleton"),
    Path("reports/auth"),
    Path("reports/ci"),
    Path("reports/admission"),
    Path("reports/leases"),
)
```

- [ ] **Step 6: The existing live callers take a lease before they mint or handle**

`mint_handle` now needs a live lease at the fence it is given, and a handler needs the lease its claim took. Each
existing caller takes one through `lease_for`.

In `tests/e2e/test_worker_live.py`:

Edit 1 (old lines 15-24), replace:

```python
from ops_core import persistence, settings
from ops_core.canonical import canonical_json, canonical_sha256
from ops_core.jobs import Server, Tool
from ops_core.settings import Role
from ops_worker import handlers
from ops_worker.drafting import FakeDraftGenerator
from ops_worker.mcp import McpCallFailed

from tests.e2e.conftest import purge_run
from tests.e2e.test_migrations_and_persistence import new_run
```

with:

```python
from ops_core import persistence, settings
from ops_core.canonical import canonical_json, canonical_sha256
from ops_core.jobs import Server, Tool
from ops_core.lease import Lease
from ops_core.settings import Role
from ops_worker import handlers
from ops_worker.drafting import FakeDraftGenerator
from ops_worker.mcp import McpCallFailed

from tests.e2e.conftest import lease_for, purge_run
from tests.e2e.test_migrations_and_persistence import new_run
```

Edit 2 (old lines 103-113), replace:

```python
async def own_job(conn: persistence.Conn, run: UUID, job_type: str) -> dict[str, Any]:
    """The run's own job, claimed by this test (claim_job takes the oldest available job of any run, so a leftover
    from another test would be claimed instead). Superuser, so it returns the tenant `handlers.handle` reads."""
    cur = await conn.execute(
        "UPDATE app.jobs SET claimed_by = 't', claimed_at = now(), attempts = attempts + 1"
        " WHERE run_id = %s AND type = %s AND done_at IS NULL RETURNING *",
        (run, job_type),
    )
    row = await cur.fetchone()
    assert row is not None, (run, job_type)
    return dict(row)
```

with:

```python
async def own_job(
    conn: persistence.Conn, worker: persistence.Conn, run: UUID, job_type: str
) -> tuple[dict[str, Any], Lease]:
    """The run's own job, claimed by this test (claim_next takes the oldest available job of any run, so a leftover
    from another test would be claimed instead), and the run's lease taken on the worker's connection under the Deps'
    worker name "t", which the job's final unit checks (T13). Superuser for the claim, so it returns the tenant
    `handlers.handle` reads."""
    cur = await conn.execute(
        "UPDATE app.jobs SET claimed_by = 't', claimed_at = now(), attempts = attempts + 1"
        " WHERE run_id = %s AND type = %s AND done_at IS NULL RETURNING *",
        (run, job_type),
    )
    row = await cur.fetchone()
    assert row is not None, (run, job_type)
    return dict(row), await lease_for(worker, run, owner="t")
```

Then four replace-all edits in the same file (each count is what `grep -c` prints before the edit):

- `await handlers.handle(deps, await own_job(app_conn, run, "investigate"))` (3 occurrences) →
  `await handlers.handle(deps, *await own_job(app_conn, deps.conn, run, "investigate"))`;
- `job = await own_job(app_conn, run, "execute")` (5 occurrences) →
  `job, lease = await own_job(app_conn, deps.conn, run, "execute")`;
- `job = await own_job(app_conn, run, "investigate")` (1 occurrence) →
  `job, lease = await own_job(app_conn, deps.conn, run, "investigate")`;
- `await handlers.handle(deps, job)` (6 occurrences) → `await handlers.handle(deps, job, lease)`.

Afterwards `grep -c "own_job(app_conn, run" tests/e2e/test_worker_live.py` prints `0`.

In `tests/e2e/test_migrations_and_persistence.py`:

Edit 1 (old line 21), replace:

```python
from tests.e2e.conftest import purge_run, purge_tenant
```

with:

```python
from tests.e2e.conftest import lease_for, purge_run, purge_tenant
```

Edit 2 (old lines 149-158), replace:

```python
        first, second = await role_conn(Role.WORKER), await role_conn(Role.WORKER)
        # Both claims stay open (uncommitted), so SKIP LOCKED must hand the second worker the other job.
        async with first.transaction(force_rollback=True), second.transaction(force_rollback=True):
            one = await persistence.claim_job(first, worker_name="w1", tenant_ids=[tenant])
            two = await persistence.claim_job(second, worker_name="w2", tenant_ids=[tenant])
            assert one is not None and one["claimed_by"] == "w1" and one["attempts"] == 1
            assert two is not None and two["id"] != one["id"] and two["tenant_id"] == tenant
            assert await persistence.claim_job(first, worker_name="w3", tenant_ids=[tenant]) is None  # none left
            theirs = await persistence.claim_job(first, worker_name="w4", tenant_ids=[other])
            assert theirs is not None and theirs["tenant_id"] == other and theirs["run_id"] == other_run
```

with:

```python
        first, second, third = [await role_conn(Role.WORKER) for _ in range(3)]
        # Both picks stay open (uncommitted), so SKIP LOCKED must hand the second worker the other job and a third
        # worker none; the claim proper, with its lease, is proved in test_leases_live.py (T13).
        async with first.transaction(force_rollback=True), second.transaction(force_rollback=True):
            one = await persistence.pick_job(first, tenant_ids=[tenant])
            two = await persistence.pick_job(second, tenant_ids=[tenant])
            assert one is not None and two is not None and two["id"] != one["id"] and two["tenant_id"] == tenant
            async with third.transaction(force_rollback=True):
                assert await persistence.pick_job(third, tenant_ids=[tenant]) is None  # both are locked by others
            theirs = await persistence.pick_job(first, tenant_ids=[other])
            assert theirs is not None and theirs["tenant_id"] == other and theirs["run_id"] == other_run
```

Edit 3 (old lines 172-174), replace:

```python
        async with worker.transaction():  # invocation_context has no RLS; the transaction is for set_tenant's own check
            await persistence.set_tenant(worker, tenant)
            handle = await persistence.mint_handle(worker, run_id=run, job_id=job, server=Server.READ, azp="ops-worker")
```

with:

```python
        lease = await lease_for(worker, run)  # T13: a handle carries the fence of the lease it was minted under
        async with worker.transaction():  # invocation_context has no RLS; the transaction is for set_tenant's own check
            await persistence.set_tenant(worker, tenant)
            handle = await persistence.mint_handle(
                worker, run_id=run, job_id=job, server=Server.READ, azp="ops-worker", fence=lease.fence
            )
```

Edit 4 (old lines 399-403), replace:

```python
        async with worker.transaction():
            await persistence.set_tenant(worker, UUID(ALPHA))
            handle = await persistence.mint_handle(
                worker, run_id=succeeded, job_id=execute_job, server=Server.WRITE, azp="ops-worker"
            )
```

with:

```python
        lease = await lease_for(worker, succeeded)  # a migrated run's first lease: the row is created at fence 1
        async with worker.transaction():
            await persistence.set_tenant(worker, UUID(ALPHA))
            handle = await persistence.mint_handle(
                worker, run_id=succeeded, job_id=execute_job, server=Server.WRITE, azp="ops-worker", fence=lease.fence
            )
```

In `tests/e2e/test_mcp_read_live.py`:

Edit 1 (old line 19), replace `from tests.e2e.conftest import purge_run` with
`from tests.e2e.conftest import lease_for, purge_run`.

Edit 2 (old lines 43-48), replace:

```python
        worker_conn = await role_conn(Role.WORKER)
        async with worker_conn.transaction():  # set_tenant is transaction-local and the INSERT meets RLS
            await persistence.set_tenant(worker_conn, alpha)
            handle = await persistence.mint_handle(
                worker_conn, run_id=run, job_id=job, server=Server.READ, azp="ops-worker"
            )
```

with:

```python
        worker_conn = await role_conn(Role.WORKER)
        lease = await lease_for(worker_conn, run)  # T13: the handle carries the lease's fence
        async with worker_conn.transaction():  # set_tenant is transaction-local and the INSERT meets RLS
            await persistence.set_tenant(worker_conn, alpha)
            handle = await persistence.mint_handle(
                worker_conn, run_id=run, job_id=job, server=Server.READ, azp="ops-worker", fence=lease.fence
            )
```

In `tests/e2e/test_mcp_write_live.py`:

Edit 1 (old line 24), replace `from tests.e2e.conftest import purge_run` with
`from tests.e2e.conftest import lease_for, purge_run`.

Edit 2 (old lines 85-89), replace:

```python
    job = (await cur.fetchone())["id"]
    async with worker.transaction():
        await persistence.set_tenant(worker, tenant)
        handle = await persistence.mint_handle(worker, run_id=run, job_id=job, server=Server.WRITE, azp="ops-worker")
    return tenant, run, proposal, handle
```

with:

```python
    job = (await cur.fetchone())["id"]
    lease = await lease_for(worker, run)  # T13: a write handle is minted under the run's lease and carries its fence
    async with worker.transaction():
        await persistence.set_tenant(worker, tenant)
        handle = await persistence.mint_handle(
            worker, run_id=run, job_id=job, server=Server.WRITE, azp="ops-worker", fence=lease.fence
        )
    return tenant, run, proposal, handle
```

In `tests/e2e/test_r105_walking_skeleton.py`:

Edit 1 (old lines 25-26), replace:

```python
from scripts.skeleton import Skeleton, orphan_keys
from tests.plan_b.live import kc
```

with:

```python
from scripts.skeleton import Skeleton, orphan_keys
from tests.e2e.conftest import lease_for
from tests.plan_b.live import kc
```

Edit 2 (old lines 209-214), replace:

```python
    worker_conn = await role_conn(Role.WORKER)
    async with worker_conn.transaction():  # the worker role under the run's tenant; set_tenant is transaction-local
        await persistence.set_tenant(worker_conn, tenant)
        handle = await persistence.mint_handle(
            worker_conn, run_id=UUID(run_id), job_id=execute_job, server=Server.WRITE, azp="ops-worker"
        )
```

with:

```python
    worker_conn = await role_conn(Role.WORKER)
    # The skeleton's worker released the run's lease with the execute job; the replay takes the next fence, as a new
    # job of the run would (T13), and its handle carries that fence.
    lease = await lease_for(worker_conn, UUID(run_id), owner="r105-replay")
    async with worker_conn.transaction():  # the worker role under the run's tenant; set_tenant is transaction-local
        await persistence.set_tenant(worker_conn, tenant)
        handle = await persistence.mint_handle(
            worker_conn,
            run_id=UUID(run_id),
            job_id=execute_job,
            server=Server.WRITE,
            azp="ops-worker",
            fence=lease.fence,
        )
```

Run (dev stack up, no skeleton process running):

```bash
OPS_LIVE=1 PROFILE=test PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_worker_live.py \
  tests/e2e/test_migrations_and_persistence.py tests/e2e/test_mcp_read_live.py tests/e2e/test_mcp_write_live.py -q
```

Expected: `18 passed` (worker 4, persistence 7, mcp-read 1, mcp-write 6: three tests plus one parametrised three
ways).

- [ ] **Step 7: The live interleaving tests**

Create `tests/e2e/test_leases_live.py`:

```python
"""T13 live (OPS_LIVE=1): the run lease and its fence as role `worker` against the per-session test database (Plan H
rulings 2, 3, 5, 18, 21, 28; R020, R087, R107; DoD 1).

Two or three `worker` connections are stepped explicitly and `pg_blocking_pids` shows who waits on whom. Every run
lives on a fresh random tenant, so `claim_next` sees this module's jobs only. Writes evidence to
reports/leases/t13-leases.txt (fences, verdicts and counts; no handle, token or seeded tenant id).

Catches: a second owner while the first is live, a fence that does not move on takeover, a stale worker's write that
lands (DoD 1), a takeover that slips in under an open fenced unit, an expiry compared before the lock wait instead of
after it (SA:157), a resume job that writes beside the original job (R087), a handle that outlives its lease or
carries another fence, a release that forgets the handles or resets the fence, a claim that commits without its
lease, and a claim that waits on an in-flight renewal instead of deferring.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from ops_core import persistence
from ops_core.jobs import JobType, Server
from ops_core.lease import LOCK_FOR_UPDATE, RELEASED, Busy, Lease, LeaseLost
from ops_core.outcomes import EventType
from ops_core.settings import Role

from tests.e2e.conftest import backend_pid, expire_lease, lease_for, purge_run, purge_tenant, wait_until_blocked
from tests.e2e.test_migrations_and_persistence import new_run

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
EVIDENCE = Path("reports/leases/t13-leases.txt")
EXPECTED_LINES = 10  # one per test
SHORTEN = "UPDATE app.run_lease SET lease_until = app.current_time() + interval '2 seconds' WHERE run_id = %s"


@pytest.fixture(scope="module")
def lines() -> Iterator[list[str]]:
    out = [f"T13 leases and fences — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"]
    yield out
    if len(out) != 1 + EXPECTED_LINES:  # a failed or partial run leaves the committed file as it was
        return
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


async def fresh_run(app_conn: persistence.Conn, role_conn: RoleConn) -> tuple[UUID, UUID]:
    """A QUEUED run with its investigate job on a new random tenant."""
    tenant, _, run = await new_run(app_conn, api=await role_conn(Role.API))
    return tenant, run


async def forget(app_conn: persistence.Conn, tenant: UUID, run: UUID) -> None:
    await purge_run(app_conn, run)
    await purge_tenant(app_conn, tenant)


async def job_of(app_conn: persistence.Conn, run: UUID) -> UUID:
    cur = await app_conn.execute("SELECT id FROM app.jobs WHERE run_id = %s AND type = 'investigate'", (run,))
    row = await cur.fetchone()
    assert row is not None
    return UUID(str(row["id"]))


async def tool_events(app_conn: persistence.Conn, run: UUID) -> list[str]:
    """The run's tool.started messages in sequence order (each fenced test write names its writer)."""
    cur = await app_conn.execute(
        "SELECT payload->>'message' AS m FROM app.events WHERE run_id = %s AND type = 'tool.started' ORDER BY sequence",
        (run,),
    )
    return [row["m"] for row in await cur.fetchall()]


async def fenced_write(conn: persistence.Conn, lease: Lease, message: str) -> None:
    """One fenced unit writing one event, as a worker's handler does (ruling 5)."""
    async with conn.transaction():
        await persistence.fenced(conn, lease)
        await persistence.append_event(
            conn, run_id=lease.run_id, type=EventType.TOOL_STARTED, payload={"message": message}
        )


async def test_the_first_acquisition_takes_fence_1_and_a_live_lease_defers_the_next_job(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    tenant, run = await fresh_run(app_conn, role_conn)
    a, b = await role_conn(Role.WORKER), await role_conn(Role.WORKER)
    try:
        first = await persistence.claim_next(a, worker_name="wa", tenant_ids=[tenant], lease_seconds=30)
        assert isinstance(first, persistence.Claimed) and first.lease.fence == 1  # erratum 46: created at 0
        assert (first.job["claimed_by"], first.job["type"]) == ("wa", "investigate")
        resume = await persistence.insert_job(
            app_conn, job_type=JobType.RESUME_INPUT, run_id=run, clarification_event_id=uuid4()
        )
        second = await persistence.claim_next(b, worker_name="wb", tenant_ids=[tenant], lease_seconds=30)
        assert second == persistence.Deferred(resume)  # the run's lease decides, whatever the job type (R087)
        cur = await app_conn.execute(
            "SELECT j.claimed_by, j.attempts, j.available_at = l.lease_until AS behind FROM app.jobs j"
            " JOIN app.run_lease l ON l.run_id = j.run_id WHERE j.id = %s",
            (resume,),
        )
        row = await cur.fetchone()
        assert row is not None and (row["claimed_by"], row["attempts"], row["behind"]) == (None, 0, True)
        assert await persistence.claim_next(b, worker_name="wb", tenant_ids=[tenant], lease_seconds=30) is None
        lines.append("acquisition: first fence 1; a second job of the run deferred behind the lease, unclaimed")
    finally:
        await forget(app_conn, tenant, run)


async def test_two_first_acquisitions_of_one_run_give_one_lease(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    tenant, run = await fresh_run(app_conn, role_conn)
    await persistence.insert_job(app_conn, job_type=JobType.RESUME_INPUT, run_id=run, clarification_event_id=uuid4())
    a, b = await role_conn(Role.WORKER), await role_conn(Role.WORKER)
    try:
        a_pid, b_pid = await backend_pid(a), await backend_pid(b)
        # Stepped (review round 1, M5): A's claim stays uncommitted while B claims, so B's first-row INSERT really
        # meets A's and waits for A alone (the one wait left in a claim, Review Focus 1).
        async with a.transaction():
            first = await persistence.claim_next(a, worker_name="wa", tenant_ids=[tenant], lease_seconds=30)
            assert isinstance(first, persistence.Claimed) and first.lease.fence == 1
            second = asyncio.create_task(
                persistence.claim_next(b, worker_name="wb", tenant_ids=[tenant], lease_seconds=30)
            )
            assert a_pid in await wait_until_blocked(app_conn, b_pid)
            assert not second.done()
        got = await asyncio.wait_for(second, timeout=5)  # once A commits, B sees the live lease and defers
        assert isinstance(got, persistence.Deferred), got
        cur = await app_conn.execute("SELECT fence FROM app.run_lease WHERE run_id = %s", (run,))
        assert [row["fence"] for row in await cur.fetchall()] == [1]
        lines.append("two first claims of one run: B's insert waited on A's alone, then deferred; one lease, fence 1")
    finally:
        await forget(app_conn, tenant, run)


async def test_a_locked_lease_is_busy_at_once(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    tenant, run = await fresh_run(app_conn, role_conn)
    a, b = await role_conn(Role.WORKER), await role_conn(Role.WORKER)
    try:
        await lease_for(a, run, owner="wa")
        async with a.transaction():
            # A renewal in flight: the row locked and updated, not committed. An INSERT ... ON CONFLICT on this row
            # would wait for it (ruling 2's refinement), so the acquisition locks first, with NOWAIT.
            await a.execute(LOCK_FOR_UPDATE, (run,))
            await a.execute(
                "UPDATE app.run_lease SET lease_until = app.current_time() + interval '30 seconds' WHERE run_id = %s",
                (run,),
            )
            started = time.monotonic()
            async with b.transaction():
                got = await persistence.acquire_lease(b, run_id=run, owner="wb", lease_seconds=30)
            deferred = await persistence.claim_next(b, worker_name="wb", tenant_ids=[tenant], lease_seconds=30)
            waited = time.monotonic() - started
        assert got == Busy(locked=True) and isinstance(deferred, persistence.Deferred) and waited < 1.0
        cur = await app_conn.execute(
            "SELECT available_at > app.current_time() - interval '1 second'"
            " AND available_at <= app.current_time() + interval '1 second' AS soon FROM app.jobs WHERE id = %s",
            (deferred.job_id,),
        )
        assert (await cur.fetchone())["soon"]  # a locked lease defers by one second, not by a whole lease
        lines.append(f"a claim meeting an in-flight renewal: Busy(locked) in {waited:.2f} s, job deferred one second")
    finally:
        await forget(app_conn, tenant, run)


async def test_r020_a_stale_fence_write_aborts(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    """DoD 1: A acquires, its lease expires on the database clock, B takes the run at the next fence, and A's fenced
    unit and A's mint both refuse without writing."""
    tenant, run = await fresh_run(app_conn, role_conn)
    a, b = await role_conn(Role.WORKER), await role_conn(Role.WORKER)
    try:
        job = await job_of(app_conn, run)
        old = await lease_for(a, run, owner="wa")
        await fenced_write(a, old, "wa before")
        await expire_lease(app_conn, run)  # A stalls past its lease
        new = await lease_for(b, run, owner="wb")
        assert new.fence == old.fence + 1  # the takeover moves the fence
        with pytest.raises(LeaseLost):
            await fenced_write(a, old, "wa after the takeover")
        with pytest.raises(LeaseLost):
            async with a.transaction():
                await persistence.mint_handle(
                    a, run_id=run, job_id=job, server=Server.READ, azp="ops-worker", fence=old.fence
                )
        await fenced_write(b, new, "wb")
        assert await tool_events(app_conn, run) == ["wa before", "wb"]  # the stale units changed nothing
        assert old.lost is not None
        lines.append(f"R020 fence {old.fence} after a takeover at {new.fence}: write and mint refused")
    finally:
        await forget(app_conn, tenant, run)


async def test_r020_an_in_flight_writer_holds_off_the_takeover(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    """DoD 1, in flight: A's open fenced unit holds the share lock, so a takeover waits for it even after A's lease
    has run out on the database clock; once A commits, B gets the next fence and A's next unit fails."""
    tenant, run = await fresh_run(app_conn, role_conn)
    a, b = await role_conn(Role.WORKER), await role_conn(Role.WORKER)
    try:
        old = await lease_for(a, run, owner="wa")
        await app_conn.execute(SHORTEN, (run,))  # the database lease ends in 2 s; A's local deadline is 25 s away
        a_pid, b_pid = await backend_pid(a), await backend_pid(b)
        async with a.transaction():
            await persistence.fenced(a, old)
            await persistence.append_event(
                a, run_id=run, type=EventType.TOOL_STARTED, payload={"message": "wa in flight"}
            )
            await asyncio.sleep(2.5)  # the lease has run out; A still holds the share lock
            takeover = asyncio.create_task(lease_for(b, run, owner="wb", wait=True))
            assert a_pid in await wait_until_blocked(app_conn, b_pid)
            assert not takeover.done()
        new = await asyncio.wait_for(takeover, timeout=5)
        assert new.fence == old.fence + 1
        with pytest.raises(LeaseLost):
            await fenced_write(a, old, "wa next")
        assert await tool_events(app_conn, run) == ["wa in flight"]  # committed under the lock, before the takeover
        lines.append("R020 in flight: the takeover waited on the open fenced unit, then took the next fence")
    finally:
        await forget(app_conn, tenant, run)


async def test_r107_expiry_is_compared_after_the_lock(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    """SA:157: a fenced unit that waits on a renewal-shaped lock while its lease runs out must refuse once the lock is
    released, although the row never changed (no re-check would happen for a WHERE evaluated before the wait)."""
    tenant, run = await fresh_run(app_conn, role_conn)
    a, c = await role_conn(Role.WORKER), await role_conn(Role.WORKER)
    try:
        lease = await lease_for(a, run, owner="wa")
        await app_conn.execute(SHORTEN, (run,))
        a_pid = await backend_pid(a)
        async with c.transaction(force_rollback=True):  # a renewal that fails and rolls back, updating nothing
            await c.execute(LOCK_FOR_UPDATE, (run,))
            check = asyncio.create_task(fenced_write(a, lease, "wa after the wait"))
            await wait_until_blocked(app_conn, a_pid)
            await asyncio.sleep(2.5)  # the lease runs out while A waits
        with pytest.raises(LeaseLost):
            await asyncio.wait_for(check, timeout=5)
        assert await tool_events(app_conn, run) == []
        lines.append("R107 expiry compared after the lock: a lease that lapsed during the wait refused the write")
    finally:
        await forget(app_conn, tenant, run)


async def test_r087_only_the_current_run_fence_writes(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    """R087: an investigate job and a resume_input job of one run share one lease; the resume job waits behind it,
    then takes the next fence, and from then on only it writes, and only it closes its job."""
    tenant, run = await fresh_run(app_conn, role_conn)
    a, b = await role_conn(Role.WORKER), await role_conn(Role.WORKER)
    try:
        original = await persistence.claim_next(a, worker_name="wa", tenant_ids=[tenant], lease_seconds=30)
        assert isinstance(original, persistence.Claimed)
        resume = await persistence.insert_job(
            app_conn, job_type=JobType.RESUME_INPUT, run_id=run, clarification_event_id=uuid4()
        )
        deferred = await persistence.claim_next(b, worker_name="wb", tenant_ids=[tenant], lease_seconds=30)
        assert deferred == persistence.Deferred(resume)
        # The original's worker stalls past its lease; the resume job comes due and takes the run's next fence.
        await expire_lease(app_conn, run)
        await app_conn.execute("UPDATE app.jobs SET available_at = app.current_time() WHERE id = %s", (resume,))
        current = await persistence.claim_next(b, worker_name="wb", tenant_ids=[tenant], lease_seconds=30)
        assert isinstance(current, persistence.Claimed) and current.job["id"] == resume
        assert current.lease.fence == original.lease.fence + 1
        with pytest.raises(LeaseLost):
            await fenced_write(a, original.lease, "investigate job")
        await fenced_write(b, current.lease, "resume job")
        assert await tool_events(app_conn, run) == ["resume job"]
        with pytest.raises(LeaseLost):  # the stale job's final unit closes nothing and releases nothing
            await persistence.release_lease(a, original.lease, job=dict(original.job))
        await persistence.release_lease(b, current.lease, job=dict(current.job))
        cur = await app_conn.execute("SELECT id, done_at IS NOT NULL AS done FROM app.jobs WHERE run_id = %s", (run,))
        assert {row["id"]: row["done"] for row in await cur.fetchall()} == {original.job["id"]: False, resume: True}
        lines.append(
            f"R087 resume vs original: deferred, then fence {current.lease.fence}; only it wrote and closed its job"
        )
    finally:
        await forget(app_conn, tenant, run)


async def test_a_handle_is_capped_at_its_lease_and_bound_to_its_fence(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    tenant, run = await fresh_run(app_conn, role_conn)
    a = await role_conn(Role.WORKER)
    try:
        job = await job_of(app_conn, run)
        lease = await lease_for(a, run, owner="wa", seconds=30)
        async with a.transaction():
            handle = await persistence.mint_handle(
                a, run_id=run, job_id=job, server=Server.READ, azp="ops-worker", fence=lease.fence, ttl_seconds=3600
            )
        cur = await app_conn.execute(
            "SELECT ic.fence, ic.expires_at <= l.lease_until AS capped FROM app.invocation_context ic"
            " JOIN app.run_lease l ON l.run_id = ic.run_id WHERE ic.handle_sha256 = %s",
            (persistence.handle_hash(handle),),
        )
        row = await cur.fetchone()
        assert row is not None and (row["fence"], row["capped"]) == (lease.fence, True)  # BS:558
        with pytest.raises(LeaseLost):
            async with a.transaction():
                await persistence.mint_handle(
                    a, run_id=run, job_id=job, server=Server.READ, azp="ops-worker", fence=lease.fence + 1
                )
        lines.append("a handle asked for 3600 s ends with its 30 s lease, at its fence; another fence mints none")
    finally:
        await forget(app_conn, tenant, run)


async def test_release_closes_the_job_revokes_its_handles_and_keeps_the_fence(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    tenant, run = await fresh_run(app_conn, role_conn)
    a, b = await role_conn(Role.WORKER), await role_conn(Role.WORKER)
    try:
        claimed = await persistence.claim_next(a, worker_name="wa", tenant_ids=[tenant], lease_seconds=30)
        assert isinstance(claimed, persistence.Claimed)
        async with a.transaction():
            await persistence.mint_handle(
                a, run_id=run, job_id=claimed.job["id"], server=Server.READ, azp="ops-worker", fence=claimed.lease.fence
            )
        await persistence.release_lease(a, claimed.lease, job=dict(claimed.job))
        assert claimed.lease.lost == RELEASED
        cur = await app_conn.execute(
            "SELECT j.done_at IS NOT NULL AS done, l.owner, l.fence, l.lease_until = '-infinity' AS released,"
            " ic.revoked_at IS NOT NULL AS revoked FROM app.jobs j JOIN app.run_lease l ON l.run_id = j.run_id"
            " JOIN app.invocation_context ic ON ic.job_id = j.id WHERE j.id = %s",
            (claimed.job["id"],),
        )
        row = await cur.fetchone()
        assert row is not None
        expected = {"done": True, "owner": "wa", "fence": claimed.lease.fence, "released": True, "revoked": True}
        assert dict(row) == expected
        following = await lease_for(b, run, owner="wb")
        assert following.fence == claimed.lease.fence + 1  # the fence persists across the run's jobs (ruling 28)
        with pytest.raises(LeaseLost):
            await persistence.release_lease(a, claimed.lease, job=dict(claimed.job))
        lines.append("release: job done, handles revoked, lease '-infinity' at the same fence; the next job takes +1")
    finally:
        await forget(app_conn, tenant, run)


async def test_claim_and_lease_commit_together(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    tenant, run = await fresh_run(app_conn, role_conn)
    a = await role_conn(Role.WORKER)
    try:
        async with a.transaction(force_rollback=True):  # claim_next's own transaction becomes a savepoint inside
            got = await persistence.claim_next(a, worker_name="wa", tenant_ids=[tenant], lease_seconds=30)
            assert isinstance(got, persistence.Claimed)
        cur = await app_conn.execute(
            "SELECT (SELECT count(*) FROM app.run_lease WHERE run_id = %s) AS leases,"
            " (SELECT count(*) FROM app.jobs WHERE run_id = %s AND claimed_at IS NOT NULL) AS claimed",
            (run, run),
        )
        row = await cur.fetchone()
        assert row is not None and (row["leases"], row["claimed"]) == (0, 0)  # neither survives without the other
        lines.append("claim and lease roll back together: no lease row, no claimed job")
    finally:
        await forget(app_conn, tenant, run)
```

Run (dev stack up, no skeleton process running):

```bash
OPS_LIVE=1 PROFILE=test PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_leases_live.py -q
```

Expected: `10 passed` (about 15 s: three tests wait 2.5 s on purpose); `reports/leases/t13-leases.txt` holds the header
and ten lines.

- [ ] **Step 8: Gates and commit**

Format, lint and count characters on every file of this task.

Run: `PYTHONUTF8=1 uv run python scripts/check.py`
Expected: `CHECK: GREEN`; pytest `883 passed, 119 skipped` (863 + 12 + 8; the 10 new live tests skip).

Run: `PYTHONUTF8=1 uv run python scripts/check.py --profile test`
Expected: `CHECK: GREEN`; pytest `981 passed, 21 skipped` (R105's skeleton now runs the leasing worker). Then
`git checkout -- reports/bootstrap reports/skeleton reports/auth reports/admission` (keep `reports/leases`; Task 8
commits it after the final run).

Run: `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`
Expected: exit 0.

```bash
git add core/src/ops_core/lease.py core/src/ops_core/persistence.py worker/src/ops_worker
git add tests/plan_h/test_lease.py tests/plan_h/test_worker_units.py tests/plan_f/test_grant_deferred.py
git add tests/plan_b/test_evidence.py tests/e2e/conftest.py tests/e2e/test_leases_live.py tests/e2e/test_worker_live.py
git add tests/e2e/test_migrations_and_persistence.py tests/e2e/test_mcp_read_live.py tests/e2e/test_mcp_write_live.py
git add tests/e2e/test_r105_walking_skeleton.py
git commit -m "feat(worker): claim under the run lease, fence every writing unit, release with the job (T13)"
```

---

### Task 4: The fenced definers — the handle carries the fence, `mark_unknown` moves it, mcp-write passes the handle

**Files:**
- Create: `tests/plan_h/test_write_path_fence.py`, `tests/e2e/test_fenced_definers_live.py`
- Modify: `migrations/app/versions/0007_leases_fences.py` (as Task 2 wrote it: docstring, imports, the function
  bodies and the four tuples); `core/src/ops_core/privileges.py` (`DEFINER_FUNCTIONS`: `mark_sent`,
  `record_outcome`); `core/src/ops_core/persistence.py` (`mark_sent`, `record_outcome`, `mark_unknown`, new `Unknown`);
  `worker/src/ops_worker/handlers.py` (as Task 3 wrote it: the UNKNOWN branch, new `_mark_unknown`);
  `mcp-write/src/ops_mcp_write/execution.py:29-31`, `:88`, `:117`; `mcp-write/src/ops_mcp_write/server.py:223-225`;
  `tests/plan_h/test_migration_0007.py` (three tests), `tests/plan_h/test_worker_units.py` (the `mark_unknown` fake,
  two tests); `tests/e2e/conftest.py` (`stage_lease`); `tests/e2e/test_definers_write_path_live.py` (the import,
  `handle_for`, every `mark_sent`/`record_outcome`/`mark_unknown` call); `tests/e2e/test_worker_live.py` (two
  `mark_sent` calls, the UNKNOWN test); `tests/e2e/test_mcp_write_live.py:277-279` (docstring, as Task 3 left it);
  `tests/e2e/test_migration_0007_live.py` (the round trip proves the restored bodies)

**Requirements:** R020 (MCP side: a stale fence writes nothing), R027's T13 half (a handle dies with its fence or its
lease), R107 (the definers lock the lease row first), R006 (exact downgrade); brief rulings 4, 5, 6, 7, 8, 9, 10, 31.

**Interfaces:**
- Consumes: `persistence.Claimed`, `acquire_lease`, `fenced`, `mint_handle(..., fence=...)`, `Lease.begin_refence`,
  `end_refence` (Task 3); `tests.e2e.conftest.lease_for`, `expire_lease` (Task 3); `tests.e2e.test_mcp_write_live.
  approved_run`, `make_deps`, `running_sim`.
- Produces: SQL `app._resolve_handle` (fence check), `app.mark_sent(text, uuid)`, `app.record_outcome(text, uuid,
  text, jsonb)`, `app.mark_unknown(uuid, bigint) RETURNS TABLE (run_state text, new_fence bigint)`,
  `app.revoke_handles(uuid, bigint)` (scoped by fence), `app.grant_execution` (reworded comment); Python
  `persistence.mark_sent(conn, *, handle, action_id) -> str`, `persistence.record_outcome(conn, *, handle, action_id,
  outcome) -> ToolOutcome`, `@dataclass(frozen=True) persistence.Unknown(state: RunState, fence: int)`,
  `persistence.mark_unknown(conn, run_id, fence) -> Unknown`; `handlers._mark_unknown(deps, lease)`;
  `tests.e2e.conftest.stage_lease(conn, run_id, *, owner="live-test", seconds=600) -> int`; in the revision
  `REV0003`, `REV0004`, `REV0005` (the applied modules), `RESOLVE_HANDLE`, `GRANT_EXECUTION`, `MARK_SENT`,
  `RECORD_OUTCOME`, `MARK_UNKNOWN`, `REVOKE_HANDLES`.

- [ ] **Step 1: Write the failing unit tests**

In `tests/plan_h/test_migration_0007.py` (as Task 2 wrote it), append after two blank lines:

```python
def test_upgrade_replaces_the_handle_functions_with_fenced_ones(monkeypatch: pytest.MonkeyPatch) -> None:
    module = revision()
    seen = statements(module, "upgrade", monkeypatch)
    for old, new in (
        ("mark_sent(uuid)", "app.mark_sent(p_raw_handle text, p_action_id uuid)"),
        ("record_outcome(uuid, text, jsonb)", "app.record_outcome(p_raw_handle text, p_action_id uuid"),
        ("mark_unknown(uuid, bigint)", "app.mark_unknown(p_run_id uuid, p_fence bigint)"),
    ):
        dropped = seen.index(f"DROP FUNCTION app.{old}")
        created = next(i for i, s in enumerate(seen) if new in s)
        assert dropped < created, old  # another signature or return type: dropped, then created
    resolve = module.RESOLVE_HANDLE
    lock = resolve.index("FROM run_lease l WHERE l.run_id = v_ctx.run_id FOR SHARE")
    assert lock < resolve.index("v_lease.fence <> v_ctx.fence") < resolve.index("_tenant_of_run")
    assert lock < resolve.index("v_ctx.expires_at <= app.current_time()")  # SA:157: compared after the lock
    for body in (module.MARK_SENT, module.RECORD_OUTCOME):
        assert body.index("app._resolve_handle(p_raw_handle") < body.index("FOR UPDATE")  # run_lease before runs
        assert "g.run_id = v_handle.run_id" in body  # the action must be the handle's run's
    assert module.GRANT_EXECUTION != module.REV0005.GRANT_EXECUTION
    assert module.GRANT_TODO_0005 in module.REV0005.GRANT_EXECUTION
    assert module.GRANT_TODO_0005 not in module.GRANT_EXECUTION  # the reworded line is gone


def test_mark_unknown_bumps_under_the_lock_and_locks_the_run_before_the_handles() -> None:
    module = revision()
    body = module.MARK_UNKNOWN
    assert "RETURNS TABLE (run_state text, new_fence bigint)" in body
    order = [
        "FROM run_lease l WHERE l.run_id = p_run_id FOR UPDATE",
        "v_lease.fence <> p_fence OR v_lease.lease_until <= app.current_time()",
        "SET fence = p_fence + 1",
        "FROM runs r WHERE r.run_id = p_run_id FOR UPDATE",
        "UPDATE invocation_context ic SET revoked_at",
    ]
    assert [body.index(part) for part in order] == sorted(body.index(part) for part in order)  # SA:188, SA:191
    revoke = module.REVOKE_HANDLES
    assert revoke.index("FOR SHARE") < revoke.index("ic.fence <= p_fence")  # ruling 8: never refuses
    assert "RAISE" not in revoke.split("BEGIN", 1)[1].replace("app._authority", "")


def test_the_downgrade_restores_the_applied_bodies_exactly(monkeypatch: pytest.MonkeyPatch) -> None:
    module = revision()
    seen = statements(module, "downgrade", monkeypatch)
    drops = [
        "DROP FUNCTION app.queued_runs_total()",
        "DROP FUNCTION app.mark_sent(text, uuid)",
        "DROP FUNCTION app.record_outcome(text, uuid, text, jsonb)",
        "DROP FUNCTION app.mark_unknown(uuid, bigint)",
    ]
    assert seen[: len(drops)] == drops
    for body in (
        module.REV0004.RESOLVE_HANDLE,
        module.REV0005.GRANT_EXECUTION,
        module.REV0004.MARK_SENT,
        module.REV0004.RECORD_OUTCOME,
        module.REV0004.MARK_UNKNOWN,
        module.REV0003.REVOKE_HANDLES,
    ):
        assert body in seen  # the applied revision's own text, byte for byte
```

In `tests/plan_h/test_worker_units.py` (as Task 3 wrote it):

Edit 1, replace:

```python
from ops_core import persistence, settings
from ops_core.lease import Lease, LeaseLost
from ops_worker import handlers, main
```

with:

```python
from ops_core import persistence, settings
from ops_core.lease import Lease, LeaseLost
from ops_core.states import RunState
from ops_worker import handlers, main
```

Edit 2, replace:

```python
        "mark_unknown": recorder("mark_unknown"),
```

with:

```python
        "mark_unknown": recorder("mark_unknown", persistence.Unknown(RunState.OUTCOME_UNKNOWN, 4)),
```

and append after two blank lines:

```python
UNKNOWN_ENVELOPE = {"status": "outcome", "data": {"status": "UNKNOWN"}, "error": None}


class UnknownMcp:
    """mcp-write after SENT with no answer it could trust: the UNKNOWN envelope the worker must record."""

    def __init__(self, log: Log) -> None:
        self.log = log

    async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.log.entries.append(f"mcp:{tool}")
        return UNKNOWN_ENVELOPE


def executing(monkeypatch: pytest.MonkeyPatch, log: Log, *, lost_at: int | None = None) -> tuple[handlers.Deps, Lease]:
    """The fakes for an execute job whose run is EXECUTING and whose write call answers UNKNOWN."""
    patch(monkeypatch, log, lost_at=lost_at)

    async def executing_run(_conn: Any, _run_id: Any, *, lock: bool = False) -> dict[str, Any]:
        log.entries.append("run_row")
        return {**RUN, "state": "EXECUTING"}

    monkeypatch.setattr(persistence, "run_row", executing_run)
    deps, lease = make(log)
    deps.mcp = UnknownMcp(log)
    return deps, lease


def test_mark_unknown_hands_the_new_fence_to_the_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    log = Log()
    deps, lease = executing(monkeypatch, log)
    assert asyncio.run(handlers.execute(deps, {**JOB, "type": "execute"}, lease)) is True
    assert (lease.fence, lease.refencing) == (4, False)  # the bump's fence, handed over (ruling 10)
    assert ["mark_unknown"] in log.units()  # its own unit: no share lock to upgrade (SA:191)


def test_a_stale_fence_at_mark_unknown_is_a_lost_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    for lost_at, raised in ((2, LeaseLost), (None, persistence.VersionConflict)):
        log = Log()
        deps, lease = executing(monkeypatch, log, lost_at=lost_at)

        async def refused(*_: Any, **__: Any) -> None:
            raise persistence.VersionConflict("version_conflict: stale fence")

        monkeypatch.setattr(persistence, "mark_unknown", refused)
        # With lost_at=2 the fresh fence check after the refusal fails: the fence was stale, a lost lease. Without
        # it the fence holds, so the refusal was the run's own state and is raised as it came.
        with pytest.raises(raised):
            asyncio.run(handlers.execute(deps, {**JOB, "type": "execute"}, lease))
        assert (lease.fence, lease.refencing) == (3, False)
```

Create `tests/plan_h/test_write_path_fence.py`:

```python
"""mcp-write under the lease fence (Plan H ruling 6), without a database: a moved fence is the handle refusal on both
sides of SENT, and the side alone decides the answer.

Catches: a stale fence before SENT that sends anyway (it must stay an honest INVALID_HANDLE: nothing was sent), and a
stale fence after SENT that becomes an error envelope (the destination may have committed, so the only honest
answers are a recorded outcome or UNKNOWN; Plan E final review I1).
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from ops_core import persistence
from ops_core.outcomes import ActionOutcome, Receipt, ToolOutcome
from ops_mcp_write import destination, execution
from ops_mcp_write.server import outcome_envelope

ACTION = uuid4()
GRANT = persistence.Grant(
    action_id=ACTION,
    run_id=uuid4(),
    proposal_id=uuid4(),
    tenant_id=uuid4(),
    conversation_id=uuid4(),
    payload_sha256="a" * 64,
    payload_canonical=b"{}",
    attempt_state="INTENT",
    detail=None,
)
SUCCEEDED = ActionOutcome(
    status=ToolOutcome.SUCCEEDED,
    action_id=ACTION,
    payload_sha256="a" * 64,
    receipt=Receipt(receipt_id=uuid4(), incident_id="INC-000001", committed_at=datetime(2026, 10, 15, tzinfo=UTC)),
    tombstone=None,
    reason=None,
)


class FakeSession:
    @asynccontextmanager
    async def unit(self, tenant_id: Any = None) -> AsyncIterator[object]:
        yield object()


class FakeToken:
    async def token(self) -> str:
        return "workload-token"


def deps() -> execution.Deps:
    session: Any = FakeSession()
    http: Any = None
    token: Any = FakeToken()
    return execution.Deps(session=session, http=http, destination_url="http://127.0.0.1:9", destination_token=token)


def test_a_moved_fence_before_sent_refuses_and_sends_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    posts: list[int] = []

    async def grant(_conn: Any, **_: Any) -> persistence.Grant:
        return GRANT

    async def stale_mark_sent(_conn: Any, *, handle: str, action_id: Any) -> str:
        raise persistence.HandleRejected("invocation handle rejected")

    async def post(*_: Any, **__: Any) -> None:
        posts.append(1)

    monkeypatch.setattr(persistence, "grant_execution", grant)
    monkeypatch.setattr(persistence, "mark_sent", stale_mark_sent)
    monkeypatch.setattr(destination, "post_incident", post)
    with pytest.raises(persistence.HandleRejected):  # server.py answers INVALID_HANDLE for exactly this
        asyncio.run(execution.create_incident(deps(), handle="h", proposal_id=uuid4()))
    assert posts == []


def test_a_moved_fence_after_sent_is_unknown_never_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def grant(_conn: Any, **_: Any) -> persistence.Grant:
        return GRANT

    async def mark_sent(_conn: Any, *, handle: str, action_id: Any) -> str:
        return "sent"

    async def post(*_: Any, **__: Any) -> destination.Reply:
        return destination.Reply(200, {})

    async def stale_record(_conn: Any, *, handle: str, action_id: Any, outcome: ActionOutcome) -> ToolOutcome:
        raise persistence.HandleRejected("invocation handle rejected")

    monkeypatch.setattr(persistence, "grant_execution", grant)
    monkeypatch.setattr(persistence, "mark_sent", mark_sent)
    monkeypatch.setattr(destination, "post_incident", post)
    monkeypatch.setattr(destination, "classify", lambda *_, **__: SUCCEEDED)
    monkeypatch.setattr(persistence, "record_outcome", stale_record)
    outcome = asyncio.run(execution.create_incident(deps(), handle="h", proposal_id=uuid4()))
    doc = outcome_envelope(outcome)
    assert outcome.status is ToolOutcome.UNKNOWN and doc["status"] == "outcome" and doc["error"] is None
```

Run: `uv run python -m pytest tests/plan_h/test_migration_0007.py tests/plan_h/test_worker_units.py tests/plan_h/test_write_path_fence.py -q`
Expected: `13 failed, 7 passed`. The three new revision tests fail (the first with `ValueError: 'DROP FUNCTION
app.mark_sent(uuid)' is not in list`, because `seen.index` runs before any body is read; the second with
`AttributeError: module 'rev_0007_leases_fences' has no attribute 'MARK_UNKNOWN'`; the third with an `AssertionError`
on the downgrade's first four statements); every worker test that installs the fakes fails with `AttributeError:
module 'ops_core.persistence' has no attribute 'Unknown'` (eight: the six from Task 3 that call `patch` and the two
new ones; the deferral test and the abandon test pass);
both write-path tests fail with `TypeError`, because `execution.py` still passes the action id positionally to the
keyword-only fakes.

- [ ] **Step 2: The fenced bodies in revision 0007**

In `migrations/app/versions/0007_leases_fences.py` (as Task 2 wrote it):

Edit 1, replace:

```python
"""The run lease's schema half (T13, Plan H rulings 1, 12, 13, 27): the model permit, the definer's fence cell, the
job-type vocabulary and the global queue count; Task 4 of the plan adds the fenced definer functions to this revision.
```

with:

```python
"""The run lease in the database (T13, Plan H rulings 1, 5-9, 12, 13, 27): the model permit, the definer's fence cell,
the job-type vocabulary, the global queue count and the fenced definer functions.
```

Edit 2, replace:

```python
bound's count for `api`, which sees one tenant under RLS (ruling 13). Every cell, caller and body is frozen here; the
downgrade restores revision 0006 exactly (R006).
"""

from alembic import op
from ops_core import privileges
```

with:

```python
bound's count for `api`, which sees one tenant under RLS (ruling 13).

The handle functions check the fence in one place, `_resolve_handle`: the run's lease row FOR SHARE, then the handle's
fence against the lease's and the lease's expiry, compared after the lock (rulings 5 and 7; erratum 53).
`resolve_invocation`, `lookup_action` and `grant_execution` already call it; `mark_sent` and `record_outcome` now take
the raw handle so they call it too (erratum 48). `mark_unknown` takes the lease FOR UPDATE, refuses a stale fence,
bumps it and returns the new one (erratum 54); `revoke_handles` revokes one fence's handles and older ones, never
refusing (erratum 55). The worker-only `transition_run`, `freeze_proposal` and `append_event` keep their bodies: the
worker's unit takes the share lock before calling them (erratum 47). Every cell, caller and body is frozen here, and
the downgrade restores revision 0006 exactly (R006) by re-running the applied revisions' own bodies, loaded from
their files: an applied revision is never edited, so this is as exact as a copy and cannot drift from it.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic import op
from ops_core import privileges
```

Edit 3 (two blank lines before the new function, as `ruff format` wants), replace:

```python
depends_on = None

HEADER = "LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp SET app.tenant_id = ''"
TABLES = ("run_lease", "model_permit")
```

with:

```python
depends_on = None


def _applied(name: str) -> ModuleType:
    """An applied revision's module, loaded by path (the versions directory is not a package)."""
    spec = importlib.util.spec_from_file_location(f"applied_{name}", Path(__file__).with_name(f"{name}.py"))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"revision {name} is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REV0003 = _applied("0003_run_path_functions")
REV0004 = _applied("0004_write_path_functions")
REV0005 = _applied("0005_sessions_login_logout")
HEADER = "LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp SET app.tenant_id = ''"
HELPER_HEADER = REV0004.HELPER_HEADER
HANDLE_COLUMNS = REV0004.HANDLE_COLUMNS
TABLES = ("run_lease", "model_permit")
```

Edit 4, replace:

```python
# (name, argument types, callers, body): frozen here (N1); the newest-revision test reads this tuple.
FUNCTIONS: tuple[tuple[str, str, tuple[str, ...], str], ...] = (("queued_runs_total", "", ("api",), QUEUED_RUNS_TOTAL),)
# Signatures upgrade() drops before FUNCTIONS re-creates them with another signature or return type.
REPLACED: tuple[str, ...] = ()
# Signatures downgrade() drops: the functions 0006 does not have in the form FUNCTIONS created.
CREATED: tuple[str, ...] = ("queued_runs_total()",)
# What downgrade() re-creates afterwards, from the applied revisions' own bodies: (name, args, callers, body).
RESTORED: tuple[tuple[str, str, tuple[str, ...], str], ...] = ()
```

with:

```python
RESOLVE_HANDLE = f"""
CREATE OR REPLACE FUNCTION app._resolve_handle(p_raw_handle text, p_client_azp text, p_server text)
RETURNS TABLE ({HANDLE_COLUMNS})
{HELPER_HEADER} AS $fn$
DECLARE
    v_ctx invocation_context%ROWTYPE;
    v_lease run_lease%ROWTYPE;
    v_job_type text;
    v_job_server text;
    v_tenant uuid;
    v_run runs%ROWTYPE;
    v_attempt text;
BEGIN
    -- The raw handle never touches a table: only its hash is looked up (BS:360). Every refusal is the same error
    -- and the same message, so a probe learns nothing (SA:357).
    SELECT * INTO v_ctx FROM invocation_context ic
    WHERE ic.handle_sha256 = encode(sha256(convert_to(p_raw_handle, 'UTF8')), 'hex');
    IF NOT FOUND THEN
        RAISE EXCEPTION 'handle_rejected' USING ERRCODE = 'OC008';
    END IF;
    -- AM-12 (T13): the run's lease row FOR SHARE is the first lock (SA:188), so an acquisition (FOR UPDATE) waits for
    -- this transaction and nothing it writes can land after a newer fence. A handle lives only while its fence is the
    -- lease's and the lease is live; every comparison below runs after the lock (SA:157).
    SELECT * INTO v_lease FROM run_lease l WHERE l.run_id = v_ctx.run_id FOR SHARE;
    IF NOT FOUND OR v_lease.fence <> v_ctx.fence OR v_lease.lease_until <= app.current_time()
       OR v_ctx.revoked_at IS NOT NULL OR v_ctx.expires_at <= app.current_time() OR v_ctx.azp <> p_client_azp THEN
        RAISE EXCEPTION 'handle_rejected' USING ERRCODE = 'OC008';
    END IF;
    v_tenant := app._tenant_of_run(v_ctx.run_id);
    SELECT j.type INTO v_job_type FROM jobs j WHERE j.id = v_ctx.job_id;
    -- The server is derived from the job type (SA:496), and the stored column must agree; a read handle at the
    -- write server (or the reverse) is refused whichever column a compromised worker wrote.
    v_job_server := CASE v_job_type WHEN 'investigate' THEN 'read' WHEN 'resume_input' THEN 'read'
                                    WHEN 'execute' THEN 'write' WHEN 'recover' THEN 'write' ELSE NULL END;
    IF v_job_server IS NULL OR v_job_server <> p_server OR v_ctx.server <> p_server THEN
        RAISE EXCEPTION 'handle_rejected' USING ERRCODE = 'OC008';
    END IF;
    SELECT * INTO v_run FROM runs r WHERE r.run_id = v_ctx.run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'handle_rejected' USING ERRCODE = 'OC008';
    END IF;
    SELECT la.state INTO v_attempt FROM execution_grant g, LATERAL app._latest_attempt(g.action_id) la
    WHERE g.run_id = v_ctx.run_id;
    run_id := v_ctx.run_id; job_id := v_ctx.job_id; job_type := v_job_type; tenant_id := v_tenant;
    conversation_id := v_run.conversation_id; run_state := v_run.state; attempt_state := v_attempt;
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION app._resolve_handle(text, text, text) OWNER TO app_definer;
"""

# grant_execution as 0005 installed it, with its lease to-do answered: the fence is _resolve_handle's (ruling 31).
# The only change is the comment, which lives in the stored body. GRANT_TODO_0005 quotes revision 0005's line
# verbatim (the one place outside the applied revisions that carries T13's old TODO marker).
GRANT_TODO_0005 = "    -- TODO(T21): asset freshness (5 min) and the asset guard; TODO(T13): the lease fence.\n"
GRANT_EXECUTION = REV0005.GRANT_EXECUTION.replace(
    GRANT_TODO_0005,
    "    -- The lease fence was checked by _resolve_handle above (run_lease FOR SHARE, T13). TODO(T21): asset\n"
    "    -- freshness (5 min) and the asset guard advisory lock, first in the lock order (SA:189).\n",
)

MARK_SENT = f"""
CREATE OR REPLACE FUNCTION app.mark_sent(p_raw_handle text, p_action_id uuid) RETURNS text
{HEADER} AS $fn$
DECLARE
    v_handle record;
    v_grant execution_grant%ROWTYPE;
    v_run runs%ROWTYPE;
    v_latest record;
BEGIN
    PERFORM app._authority('mark_sent', ARRAY['mcp_exec']);
    -- The handle binds the call to its run and its lease fence (SA:463, ruling 5): _resolve_handle takes run_lease FOR
    -- SHARE and refuses OC008 for a revoked or expired handle, a moved fence or a lapsed lease, before runs is locked.
    SELECT * INTO v_handle FROM app._resolve_handle(p_raw_handle, 'ops-worker', 'write');
    SELECT * INTO v_grant FROM execution_grant g WHERE g.action_id = p_action_id AND g.run_id = v_handle.run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'action';
    END IF;
    SELECT * INTO v_run FROM runs r WHERE r.run_id = v_grant.run_id FOR UPDATE;  -- serialises the seq (SA:462)
    SELECT * INTO v_latest FROM app._latest_attempt(p_action_id);
    IF v_latest.state = 'RESOLVED' THEN
        RETURN 'resolved';
    ELSIF v_latest.state = 'SENT' THEN
        RETURN 'already_sent';
    END IF;
    -- A run mark_unknown already moved refuses SENT (its fence bump has refused the handle above in any case).
    IF v_run.state <> 'EXECUTING' THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003',
                                                 DETAIL = format('run %s is %s', v_grant.run_id, v_run.state);
    END IF;
    -- SA:463: cancellation is re-checked before SENT; nothing is written. TODO(T22): the dispatch deadline.
    IF v_run.cancel_requested THEN
        RETURN 'cancelled';
    END IF;
    INSERT INTO action_attempt_state (tenant_id, action_id, attempt_no, seq, state, at)
    VALUES (v_handle.tenant_id, p_action_id, v_latest.attempt_no, v_latest.seq + 1, 'SENT', app.current_time());
    PERFORM app._append_event(v_handle.tenant_id, v_grant.run_id,
                              CASE WHEN v_latest.attempt_no > 1 THEN 'action.redispatched' ELSE 'action.dispatched' END,
                              'application', jsonb_build_object('action_id', p_action_id));
    RETURN 'sent';
END
$fn$;
ALTER FUNCTION app.mark_sent(text, uuid) OWNER TO app_definer;
"""

RECORD_OUTCOME = f"""
CREATE OR REPLACE FUNCTION app.record_outcome(p_raw_handle text, p_action_id uuid, p_outcome text, p_document jsonb)
RETURNS text
{HEADER} AS $fn$
DECLARE
    v_handle record;
    v_grant execution_grant%ROWTYPE;
    v_run runs%ROWTYPE;
    v_latest record;
    v_implied text;
    v_reason text;
BEGIN
    PERFORM app._authority('record_outcome', ARRAY['mcp_exec']);
    -- The handle binds the outcome to its run and its lease fence (SA:464, ruling 5); after SENT a refusal here is
    -- mcp-write's UNKNOWN, never an error envelope (ruling 6).
    SELECT * INTO v_handle FROM app._resolve_handle(p_raw_handle, 'ops-worker', 'write');
    SELECT * INTO v_grant FROM execution_grant g WHERE g.action_id = p_action_id AND g.run_id = v_handle.run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'action';
    END IF;
    SELECT * INTO v_run FROM runs r WHERE r.run_id = v_grant.run_id FOR UPDATE;
    SELECT * INTO v_latest FROM app._latest_attempt(p_action_id);
    IF v_latest.state = 'RESOLVED' THEN
        RETURN v_latest.outcome;  -- idempotent (SA:464): the first record stands
    END IF;
    IF p_outcome NOT IN ('SUCCEEDED', 'FAILED_NO_COMMIT', 'CONFLICT') THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'INVALID_ARGUMENT';
    END IF;
    -- SENT is committed before any dispatch, so a receipt or conflict without SENT is a protocol violation;
    -- FAILED_NO_COMMIT from INTENT stays allowed for a cancellation before send.
    IF p_outcome IN ('SUCCEEDED', 'CONFLICT') AND v_latest.state <> 'SENT' THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003', DETAIL = 'outcome before SENT';
    END IF;
    -- The document must describe the outcome it is recorded under.
    IF (p_document->>'status') IS DISTINCT FROM p_outcome THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'INVALID_ARGUMENT';
    END IF;
    -- "No effect" needs the destination's proof (AM-13): the Python model requires the tombstone, and this is the SQL
    -- backstop so nothing after SENT is ever recorded as no effect without one (final review M1).
    IF p_outcome = 'FAILED_NO_COMMIT' AND jsonb_typeof(p_document->'tombstone') IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'INVALID_ARGUMENT';
    END IF;
    -- The document's hash must be the grant's (SA:464); a CONFLICT is precisely the case where it is not.
    IF p_outcome <> 'CONFLICT' AND (p_document->>'payload_sha256') IS DISTINCT FROM v_grant.payload_sha256 THEN
        RAISE EXCEPTION 'hash_mismatch' USING ERRCODE = 'OC007', DETAIL = 'outcome';
    END IF;
    IF (p_document->>'action_id') IS DISTINCT FROM p_action_id::text THEN
        RAISE EXCEPTION 'hash_mismatch' USING ERRCODE = 'OC007', DETAIL = 'action_id';
    END IF;
    INSERT INTO action_attempt_state (tenant_id, action_id, attempt_no, seq, state, outcome, detail, at)
    VALUES (v_handle.tenant_id, p_action_id, v_latest.attempt_no, v_latest.seq + 1, 'RESOLVED', p_outcome, p_document,
            app.current_time());
    v_implied := CASE p_outcome WHEN 'SUCCEEDED' THEN 'SUCCEEDED' WHEN 'FAILED_NO_COMMIT' THEN 'FAILED'
                                ELSE 'ESCALATED' END;
    IF v_run.state IN ('EXECUTING', 'OUTCOME_UNKNOWN', 'ESCALATED') AND v_run.state <> v_implied THEN
        v_reason := CASE p_outcome WHEN 'FAILED_NO_COMMIT' THEN p_document->>'reason'
                                   WHEN 'CONFLICT' THEN 'conflict' ELSE NULL END;
        PERFORM app._transition(v_grant.run_id, v_implied, 'record_outcome', v_reason, NULL, NULL, NULL);
    END IF;
    -- The event is the destination's assertion (AM-14); on a terminal run a SUCCEEDED or FAILED outcome is late
    -- evidence (payload `outcome` + its proof, the shape ops_core.outcomes.event_rules_ok accepts) and a CONFLICT is
    -- always action.conflict; no transition either way.
    IF v_run.state IN ('SUCCEEDED', 'FAILED', 'ABANDONED_UNVERIFIED') AND p_outcome <> 'CONFLICT' THEN
        PERFORM app._append_event(v_handle.tenant_id, v_grant.run_id, 'action.late_evidence', 'destination',
            CASE WHEN p_outcome = 'SUCCEEDED'
                 THEN jsonb_build_object('outcome', 'SUCCEEDED', 'action_id', p_action_id,
                                         'receipt', p_document->'receipt')
                 ELSE jsonb_build_object('outcome', 'FAILED_NO_COMMIT', 'action_id', p_action_id,
                                         'reason', p_document->>'reason',
                                         'tombstone', p_document->'tombstone') END);
    ELSE
        PERFORM app._append_event(v_handle.tenant_id, v_grant.run_id,
            CASE WHEN p_outcome = 'SUCCEEDED' THEN 'action.confirmed'
                 WHEN p_outcome = 'FAILED_NO_COMMIT' THEN 'action.failed' ELSE 'action.conflict' END,
            'destination',
            CASE WHEN p_outcome = 'SUCCEEDED'
                      THEN jsonb_build_object('status', 'SUCCEEDED', 'action_id', p_action_id,
                                              'receipt', p_document->'receipt')
                 WHEN p_outcome = 'FAILED_NO_COMMIT'
                      THEN jsonb_build_object('action_id', p_action_id, 'reason', p_document->>'reason',
                                              'tombstone', p_document->'tombstone')
                 ELSE jsonb_build_object('action_id', p_action_id) END);
    END IF;
    RETURN p_outcome;
END
$fn$;
ALTER FUNCTION app.record_outcome(text, uuid, text, jsonb) OWNER TO app_definer;
"""

MARK_UNKNOWN = f"""
CREATE OR REPLACE FUNCTION app.mark_unknown(p_run_id uuid, p_fence bigint)
RETURNS TABLE (run_state text, new_fence bigint)
{HEADER} AS $fn$
DECLARE
    v_tenant uuid;
    v_lease run_lease%ROWTYPE;
    v_run runs%ROWTYPE;
    v_grant execution_grant%ROWTYPE;
BEGIN
    PERFORM app._authority('mark_unknown', ARRAY['worker']);
    v_tenant := app._tenant_of_run(p_run_id);
    -- AM-13 step 1: the lease row FOR UPDATE from the start, because this transaction writes the fence (SA:191). The
    -- caller must hold the lease it names: the fence identifies the holder (ruling 9).
    SELECT * INTO v_lease FROM run_lease l WHERE l.run_id = p_run_id FOR UPDATE;
    IF NOT FOUND OR v_lease.fence <> p_fence OR v_lease.lease_until <= app.current_time() THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003', DETAIL = 'stale fence';
    END IF;
    -- Step 2: the bump. From here every handle minted under the old fence is refused by _resolve_handle; revoking
    -- them below, after runs as the lock order wants (SA:188), is belt and braces.
    UPDATE run_lease l SET fence = p_fence + 1 WHERE l.run_id = p_run_id;
    new_fence := p_fence + 1;
    SELECT * INTO v_run FROM runs r WHERE r.run_id = p_run_id FOR UPDATE;
    UPDATE invocation_context ic SET revoked_at = app.current_time()
    WHERE ic.run_id = p_run_id AND ic.fence <= p_fence AND ic.revoked_at IS NULL;
    IF v_run.state = 'OUTCOME_UNKNOWN' THEN
        run_state := v_run.state;  -- a second UNKNOWN changes nothing but the fence
        RETURN NEXT;
        RETURN;
    END IF;
    IF v_run.state <> 'EXECUTING' THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003',
                                                 DETAIL = format('run %s is %s', p_run_id, v_run.state);
    END IF;
    -- Step 3: read the grant; no grant can commit any more, because the fence moved (AM-13).
    SELECT * INTO v_grant FROM execution_grant g WHERE g.run_id = p_run_id;
    IF NOT FOUND THEN
        run_state := v_run.state;  -- EXECUTING without a grant cannot happen; nothing to mark
        RETURN NEXT;
        RETURN;
    END IF;
    PERFORM app._transition(p_run_id, 'OUTCOME_UNKNOWN', 'mark_unknown', NULL, NULL, 'action.uncertain',
                            jsonb_build_object('action_id', v_grant.action_id));
    INSERT INTO jobs (id, type, tenant_id, run_id, dedup_key, available_at)
    VALUES (gen_random_uuid(), 'recover', v_tenant, p_run_id, format('%s:timeout', v_grant.action_id),
            app.current_time())
    ON CONFLICT (dedup_key) DO NOTHING;
    run_state := 'OUTCOME_UNKNOWN';
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION app.mark_unknown(uuid, bigint) OWNER TO app_definer;
"""

REVOKE_HANDLES = f"""
CREATE OR REPLACE FUNCTION app.revoke_handles(p_run_id uuid, p_fence bigint) RETURNS integer
{HEADER} AS $fn$
DECLARE
    v_count integer;
BEGIN
    PERFORM app._authority('revoke_handles', ARRAY['worker']);
    PERFORM app._tenant_of_run(p_run_id);
    -- Revocation only removes authority, so it never refuses a stale fence: a worker that lost its lease still revokes
    -- its own handles, and a newer owner's handles (a higher fence) survive (ruling 8). The share lock orders the call
    -- against an acquisition in progress (SA:472) and is the first lock taken (SA:188).
    PERFORM 1 FROM run_lease l WHERE l.run_id = p_run_id FOR SHARE;
    UPDATE invocation_context ic SET revoked_at = app.current_time()
    WHERE ic.run_id = p_run_id AND ic.fence <= p_fence AND ic.revoked_at IS NULL;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END
$fn$;
ALTER FUNCTION app.revoke_handles(uuid, bigint) OWNER TO app_definer;
"""

# (name, argument types, callers, body): frozen here (N1); the newest-revision test reads this tuple.
FUNCTIONS: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("queued_runs_total", "", ("api",), QUEUED_RUNS_TOTAL),
    ("_resolve_handle", "text, text, text", (), RESOLVE_HANDLE),
    ("grant_execution", "text, uuid", ("mcp_exec",), GRANT_EXECUTION),
    ("mark_sent", "text, uuid", ("mcp_exec",), MARK_SENT),
    ("record_outcome", "text, uuid, text, jsonb", ("mcp_exec",), RECORD_OUTCOME),
    ("mark_unknown", "uuid, bigint", ("worker",), MARK_UNKNOWN),
    ("revoke_handles", "uuid, bigint", ("worker",), REVOKE_HANDLES),
)
# Signatures upgrade() drops before FUNCTIONS re-creates them with another signature or return type.
REPLACED: tuple[str, ...] = ("mark_sent(uuid)", "record_outcome(uuid, text, jsonb)", "mark_unknown(uuid, bigint)")
# Signatures downgrade() drops: the functions 0006 does not have in the form FUNCTIONS created.
CREATED: tuple[str, ...] = (
    "queued_runs_total()",
    "mark_sent(text, uuid)",
    "record_outcome(text, uuid, text, jsonb)",
    "mark_unknown(uuid, bigint)",
)
# What downgrade() re-creates afterwards, from the applied revisions' own bodies: (name, args, callers, body).
RESTORED: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("_resolve_handle", "text, text, text", (), REV0004.RESOLVE_HANDLE),
    ("grant_execution", "text, uuid", ("mcp_exec",), REV0005.GRANT_EXECUTION),
    ("mark_sent", "uuid", ("mcp_exec",), REV0004.MARK_SENT),
    ("record_outcome", "uuid, text, jsonb", ("mcp_exec",), REV0004.RECORD_OUTCOME),
    ("mark_unknown", "uuid, bigint", ("worker",), REV0004.MARK_UNKNOWN),
    ("revoke_handles", "uuid, bigint", ("worker",), REV0003.REVOKE_HANDLES),
)
```

Edit 4 puts the six bodies between Task 2's `QUEUED_RUNS_TOTAL` and the four tuples, so the file reads: the cells and
the vocabulary, `SCHEMA_CHANGES`, `QUEUED_RUNS_TOTAL`, the six bodies, the four tuples, `DOWNGRADE`, `upgrade`,
`downgrade`.

Edit 5 (review round 1, M3: the check that revision 0005 still carries the line `GRANT_EXECUTION` rewords runs when
the revision is applied, not when Alembic loads the revision graph, so a drifted file fails this upgrade instead of
every Alembic command), replace:

```python
def upgrade() -> None:
    """Schema, then the frozen cells, then the functions (body first, then its grants, so REVOKE lands on it)."""
    for statement in SCHEMA_CHANGES:
```

with:

```python
def upgrade() -> None:
    """Schema, then the frozen cells, then the functions (body first, then its grants, so REVOKE lands on it).

    Raises:
        RuntimeError: revision 0005's grant_execution no longer carries the TODO line this revision rewords.
    """
    if GRANT_EXECUTION == REV0005.GRANT_EXECUTION:
        raise RuntimeError("revision 0005's grant_execution no longer carries the TODO line this revision rewords")
    for statement in SCHEMA_CHANGES:
```

Then `uv run ruff check --select ISC004 --fix --unsafe-fixes migrations/app/versions/0007_leases_fences.py` (no change
expected).

In `core/src/ops_core/privileges.py`, replace:

```python
    "mark_sent": ("uuid", ("mcp_exec",)),
    "record_outcome": ("uuid, text, jsonb", ("mcp_exec",)),
```

with:

```python
    "mark_sent": ("text, uuid", ("mcp_exec",)),  # T13: the raw handle first, so the fence is checked (erratum 48)
    "record_outcome": ("text, uuid, text, jsonb", ("mcp_exec",)),  # likewise
```

- [ ] **Step 3: The Python callers**

In `core/src/ops_core/persistence.py` (as Task 3 left it):

Edit 1, replace:

```python
async def mark_unknown(conn: Conn, run_id: UUID) -> RunState:
    """EXECUTING → OUTCOME_UNKNOWN with handles revoked and a recover job (SA:467); idempotent."""
    row = await _call(conn, "SELECT app.mark_unknown(%s, 1) AS state", (run_id,))
    if row is None:
        raise PersistenceError("mark_unknown returned nothing")
    return RunState(str(row["state"]))
```

with:

```python
@dataclass(frozen=True)
class Unknown:
    """What mark_unknown returned: the run's state and the fence it moved the lease to."""

    state: RunState
    fence: int


async def mark_unknown(conn: Conn, run_id: UUID, fence: int) -> Unknown:
    """EXECUTING → OUTCOME_UNKNOWN under the caller's lease (SA:467, Plan H ruling 9): the lease row FOR UPDATE, a stale
    fence or a lapsed lease refused (VersionConflict), the fence bumped to `fence + 1`, the old fence's handles revoked
    and a recover job queued; a run already OUTCOME_UNKNOWN only gets the bump. The caller hands the returned fence to
    its Lease (ruling 10)."""
    row = await _call(conn, "SELECT * FROM app.mark_unknown(%s, %s)", (run_id, fence))
    if row is None:
        raise PersistenceError("mark_unknown returned nothing")
    return Unknown(RunState(str(row["run_state"])), int(row["new_fence"]))
```

Edit 2, replace:

```python
async def mark_sent(conn: Conn, action_id: UUID) -> str:
    """`sent`, `already_sent`, `resolved` or `cancelled` (SA:463); committed by the caller before any I/O."""
    row = await _call(conn, "SELECT app.mark_sent(%s) AS outcome", (action_id,))
```

with:

```python
async def mark_sent(conn: Conn, *, handle: str, action_id: UUID) -> str:
    """`sent`, `already_sent`, `resolved` or `cancelled` (SA:463); committed by the caller before any I/O. The handle
    binds the call to the run's lease fence (Plan H ruling 5): a moved fence or a lapsed lease is HandleRejected."""
    row = await _call(conn, "SELECT app.mark_sent(%s, %s) AS outcome", (handle, action_id))
```

Edit 3, replace:

```python
async def record_outcome(conn: Conn, *, action_id: UUID, outcome: ActionOutcome) -> ToolOutcome:
    """RESOLVED plus the implied transition and the destination-sourced event (SA:464); returns what stands."""
    if outcome.status is ToolOutcome.UNKNOWN:
        raise ValueError("UNKNOWN is recorded by the worker through mark_unknown, never as an outcome")
    row = await _call(
        conn,
        "SELECT app.record_outcome(%s, %s, %s) AS outcome",
        (action_id, outcome.status.value, Jsonb(outcome.model_dump(mode="json"))),
    )
```

with:

```python
async def record_outcome(conn: Conn, *, handle: str, action_id: UUID, outcome: ActionOutcome) -> ToolOutcome:
    """RESOLVED plus the implied transition and the destination-sourced event (SA:464); returns what stands. The handle
    binds the record to the run's lease fence (ruling 5); after SENT its refusal is the caller's UNKNOWN (ruling 6)."""
    if outcome.status is ToolOutcome.UNKNOWN:
        raise ValueError("UNKNOWN is recorded by the worker through mark_unknown, never as an outcome")
    row = await _call(
        conn,
        "SELECT app.record_outcome(%s, %s, %s, %s) AS outcome",
        (handle, action_id, outcome.status.value, Jsonb(outcome.model_dump(mode="json"))),
    )
```

In `mcp-write/src/ops_mcp_write/execution.py`:

Edit 1 (old lines 29-31), replace:

```python
# The refusals the database maps to Python. Before SENT they are honest error envelopes (server.py); after SENT they
# must not be, because the destination may have committed: the only answers then are a recorded outcome or UNKNOWN
# (AM-13). A lease fence (T13/T22) will raise VersionConflict on exactly this path (final review I1).
```

with:

```python
# The refusals the database maps to Python. Before SENT they are honest error envelopes (server.py); after SENT they
# must not be, because the destination may have committed: the only answers then are a recorded outcome or UNKNOWN
# (AM-13, final review I1). A lease fence that moved or lapsed after SENT raises HandleRejected, a PersistenceError,
# on exactly this path (Plan H ruling 6); the run's next lease holder reconciles it (T22).
```

Edit 2 (old line 88), replace:

```python
            sent = await persistence.mark_sent(conn, grant.action_id)  # committed here, before any I/O
```

with:

```python
            sent = await persistence.mark_sent(conn, handle=handle, action_id=grant.action_id)  # committed before I/O
```

Edit 3 (old line 117), replace:

```python
            standing = await persistence.record_outcome(conn, action_id=grant.action_id, outcome=outcome)
```

with:

```python
            standing = await persistence.record_outcome(conn, handle=handle, action_id=grant.action_id, outcome=outcome)
```

In `mcp-write/src/ops_mcp_write/server.py` (old lines 223-225), replace:

```python
            try:
                await persistence.assert_clock_profile(conn, settings.profile())
            except BaseException:  # a failed start must leak no connection
```

with:

```python
            try:
                await persistence.assert_clock_profile(conn, settings.profile())
                # Revision 0007: mark_sent and record_outcome take the raw handle (T13); model_permit marks it.
                await persistence.assert_relation(conn, "app.model_permit")
            except BaseException:  # a failed start must leak no connection
```

In `worker/src/ops_worker/handlers.py` (as Task 3 wrote it), replace:

```python
    if doc.get("status") == "outcome" and data.get("status") == "UNKNOWN":  # an `error` envelope is never UNKNOWN
        # mcp-write reports uncertainty after SENT but may not record it (SA:467: mark_unknown is the worker's).
        async with deps.conn.transaction():
            await persistence.fenced(deps.conn, lease)
            await persistence.mark_unknown(deps.conn, run["run_id"])
    return True
```

with:

```python
    if doc.get("status") == "outcome" and data.get("status") == "UNKNOWN":  # an `error` envelope is never UNKNOWN
        # mcp-write reports uncertainty after SENT but may not record it (SA:467: mark_unknown is the worker's).
        await _mark_unknown(deps, lease)
    return True


async def _mark_unknown(deps: Deps, lease: Lease) -> None:
    """EXECUTING → OUTCOME_UNKNOWN through `mark_unknown`, which takes the lease row FOR UPDATE itself and bumps the
    fence (AM-13, Plan H ruling 9): no `fenced` share lock precedes it in its unit, because a transaction that writes
    the lease takes FOR UPDATE from the start (SA:191). The new fence reaches the shared Lease before anything else
    runs, and a renewal meeting it meanwhile retries instead of declaring the lease lost (ruling 10).

    Raises:
        LeaseLost: the fence was stale, told apart from a run that is not EXECUTING by a fresh `fenced` check rather
            than by the refusal's text.
        VersionConflict: the fence holds, so the run itself is not EXECUTING.
    """
    lease.check()
    lease.begin_refence()
    try:
        async with deps.conn.transaction():
            unknown = await persistence.mark_unknown(deps.conn, lease.run_id, lease.fence)
    except persistence.VersionConflict:
        lease.end_refence(None)
        async with deps.conn.transaction():
            await persistence.fenced(deps.conn, lease)  # a stale fence raises LeaseLost here
        raise
    except BaseException:
        lease.end_refence(None)
        raise
    lease.end_refence(unknown.fence)
```

Run: `uv run python -m pytest tests/plan_h tests/plan_e/test_transitions_table.py tests/plan_e/test_privileges.py tests/plan_f/test_grant_deferred.py -q`
Expected: `94 passed` (Plan H's 73: settings 11, lock order 30, revision 8, lease 12, worker units 10, write path 2;
the transitions module 12, Plan E's privileges 6, Plan F's grant module 3).

- [ ] **Step 4: The live callers**

In `tests/e2e/conftest.py`, append after `wait_until_blocked` (two blank lines before the block):

```python
async def stage_lease(conn: persistence.Conn, run_id: object, *, owner: str = "live-test", seconds: int = 600) -> int:
    """A live lease written by the superuser, for a definer test that needs a handle without running a worker: created
    at fence 1, or renewed at its current fence; returns that fence (T13)."""
    cur = await conn.execute(
        "INSERT INTO app.run_lease (run_id, owner, lease_until, fence)"
        " VALUES (%s, %s, app.current_time() + make_interval(secs => %s), 1)"
        " ON CONFLICT (run_id) DO UPDATE SET lease_until = EXCLUDED.lease_until RETURNING fence",
        (run_id, owner, seconds),
    )
    row = await cur.fetchone()
    assert row is not None
    return int(row["fence"])
```

In `tests/e2e/test_definers_write_path_live.py`:

Edit 1, replace `from tests.e2e.conftest import purge_run` with `from tests.e2e.conftest import purge_run, stage_lease`.

Edit 2 (old lines 100-113), replace:

```python
async def handle_for(app_conn: persistence.Conn, run: UUID, job_type: str, *, expires_in: int = 60) -> str:
    """A raw handle whose hash the superuser inserts (the worker's INSERT is proved in Task 6's live test)."""
    raw = f"handle-{uuid4().hex}"
    job = (
        await (
            await app_conn.execute("SELECT id FROM app.jobs WHERE run_id = %s AND type = %s", (run, job_type))
        ).fetchone()
    )["id"]
    await app_conn.execute(
        "INSERT INTO app.invocation_context (handle_sha256, run_id, job_id, server, azp, expires_at)"
        " VALUES (%s, %s, %s, %s, 'ops-worker', now() + make_interval(secs => %s))",
        (sha256_hex(raw.encode()), run, job, "write" if job_type in ("execute", "recover") else "read", expires_in),
    )
    return raw
```

with:

```python
async def handle_for(app_conn: persistence.Conn, run: UUID, job_type: str, *, expires_in: int = 60) -> str:
    """A raw handle whose hash the superuser inserts at the run's current lease fence, staging a live lease first
    when the run has none (T13: the definers refuse a handle whose fence is not the lease's). The worker's own mint,
    lease and fence are proved in tests/e2e/test_leases_live.py."""
    raw = f"handle-{uuid4().hex}"
    job = (
        await (
            await app_conn.execute("SELECT id FROM app.jobs WHERE run_id = %s AND type = %s", (run, job_type))
        ).fetchone()
    )["id"]
    fence = await stage_lease(app_conn, run)
    server = "write" if job_type in ("execute", "recover") else "read"
    await app_conn.execute(
        "INSERT INTO app.invocation_context (handle_sha256, run_id, job_id, server, azp, fence, expires_at)"
        " VALUES (%s, %s, %s, %s, 'ops-worker', %s, now() + make_interval(secs => %s))",
        (sha256_hex(raw.encode()), run, job, server, fence, expires_in),
    )
    return raw
```

Edit 3 (replace all, 3 occurrences): `"SELECT app.mark_sent(%s) AS r", (action,)` →
`"SELECT app.mark_sent(%s, %s) AS r", (handle, action)`.

Edit 4 (old lines 364-366), replace:

```python
                "SELECT app.record_outcome(%s, 'SUCCEEDED', %s)",
                (
                    action,
```

with:

```python
                "SELECT app.record_outcome(%s, %s, 'SUCCEEDED', %s)",
                (
                    handle,
                    action,
```

Edit 5 (1 occurrence), replace
`"SELECT app.record_outcome(%s, 'SUCCEEDED', %s) AS r", (action, Jsonb(document))` with
`"SELECT app.record_outcome(%s, %s, 'SUCCEEDED', %s) AS r", (handle, action, Jsonb(document))`.

Edit 6 (old lines 407-408), replace:

```python
                        "SELECT app.record_outcome(%s, 'CONFLICT', %s) AS r",
                        (action, Jsonb({"status": "CONFLICT", "action_id": str(action), "payload_sha256": digest})),
```

with:

```python
                        "SELECT app.record_outcome(%s, %s, 'CONFLICT', %s) AS r",
                        (
                            handle,
                            action,
                            Jsonb({"status": "CONFLICT", "action_id": str(action), "payload_sha256": digest}),
                        ),
```

Edit 7 (replace all, 2 occurrences): `await mcp_exec.execute("SELECT app.mark_sent(%s)", (grant["action_id"],))` →
`await mcp_exec.execute("SELECT app.mark_sent(%s, %s)", (handle, grant["action_id"]))`.

Edit 8 (old lines 463-473), replace:

```python
        assert await refused(mcp_exec, "SELECT app.mark_unknown(%s, 1)", (run,)) == "42501"  # SA:467: the worker's call
        async with as_role(worker, preset=BETA):
            assert (await (await worker.execute("SELECT app.mark_unknown(%s, 1) AS s", (run,))).fetchone())[
                "s"
            ] == "OUTCOME_UNKNOWN"
            assert (await (await worker.execute("SELECT app.mark_unknown(%s, 1) AS s", (run,))).fetchone())[
                "s"
            ] == "OUTCOME_UNKNOWN"  # idempotent
            assert (await (await worker.execute("SELECT current_setting('app.tenant_id', true) AS t")).fetchone())[
                "t"
            ] == str(BETA)
```

with:

```python
        assert await refused(mcp_exec, "SELECT * FROM app.mark_unknown(%s, 1)", (run,)) == "42501"  # SA:467: worker's
        async with as_role(worker, preset=BETA):
            cur = await worker.execute("SELECT * FROM app.mark_unknown(%s, 1)", (run,))
            assert dict(await cur.fetchone()) == {"run_state": "OUTCOME_UNKNOWN", "new_fence": 2}  # bumped (ruling 9)
        # Fence 1 is stale now; the current fence marks again idempotently and bumps once more.
        assert await refused(worker, "SELECT * FROM app.mark_unknown(%s, 1)", (run,)) == "OC003"
        async with as_role(worker, preset=BETA):
            cur = await worker.execute("SELECT * FROM app.mark_unknown(%s, 2)", (run,))
            assert dict(await cur.fetchone()) == {"run_state": "OUTCOME_UNKNOWN", "new_fence": 3}
            assert (await (await worker.execute("SELECT current_setting('app.tenant_id', true) AS t")).fetchone())[
                "t"
            ] == str(BETA)
```

Edit 9 (old lines 496-505), replace:

```python
                    "incident_id": "INC-000010",
                    "committed_at": "2026-10-08T12:00:00Z",
                },
                "tombstone": None,
                "reason": None,
            }
            assert (
                await (
                    await mcp_exec.execute(
                        "SELECT app.record_outcome(%s, 'SUCCEEDED', %s) AS r", (grant["action_id"], Jsonb(document))
```

with:

```python
                    "incident_id": "INC-000010",
                    "committed_at": "2026-10-08T12:00:00Z",
                },
                "tombstone": None,
                "reason": None,
            }
            assert (
                await (
                    await mcp_exec.execute(
                        "SELECT app.record_outcome(%s, %s, 'SUCCEEDED', %s) AS r",
                        (new_handle, grant["action_id"], Jsonb(document)),
```

Edit 10 (old lines 549-555), replace:

```python
        record = "SELECT app.record_outcome(%s, 'SUCCEEDED', %s)"
        assert await refused(mcp_exec, record, (grant["action_id"], Jsonb(empty))) == "OC006"
        async with as_role(mcp_exec):
            assert (
                await (
                    await mcp_exec.execute(
                        "SELECT app.record_outcome(%s, 'SUCCEEDED', %s) AS r", (grant["action_id"], Jsonb(document))
```

with:

```python
        record = "SELECT app.record_outcome(%s, %s, 'SUCCEEDED', %s)"
        assert await refused(mcp_exec, record, (handle, grant["action_id"], Jsonb(empty))) == "OC006"
        async with as_role(mcp_exec):
            assert (
                await (
                    await mcp_exec.execute(
                        "SELECT app.record_outcome(%s, %s, 'SUCCEEDED', %s) AS r",
                        (handle, grant["action_id"], Jsonb(document)),
```

Edit 11 (old lines 632-642), replace:

```python
            handle = await handle_for(app_conn, run, "execute")
            async with as_role(mcp_exec):
                cur = await mcp_exec.execute("SELECT * FROM app.grant_execution(%s, %s)", (handle, proposal))
                grants.append((dict(await cur.fetchone())["action_id"], digest))
        (stale, stale_digest), (cancelled, cancelled_digest) = grants
        # The superuser moves the run as mark_unknown would, leaving the attempt at INTENT.
        await app_conn.execute("UPDATE app.runs SET state = 'OUTCOME_UNKNOWN' WHERE run_id = %s", (runs[0],))
        assert await refused(mcp_exec, "SELECT app.mark_sent(%s)", (stale,)) == "OC003"
        early = {"status": "SUCCEEDED", "action_id": str(stale), "payload_sha256": stale_digest}
        record = "SELECT app.record_outcome(%s, %s, %s)"
        assert await refused(mcp_exec, record, (stale, "SUCCEEDED", Jsonb(early))) == "OC003"  # outcome before SENT
```

with:

```python
            handle = await handle_for(app_conn, run, "execute")
            async with as_role(mcp_exec):
                cur = await mcp_exec.execute("SELECT * FROM app.grant_execution(%s, %s)", (handle, proposal))
                grants.append((dict(await cur.fetchone())["action_id"], digest, handle))
        (stale, stale_digest, stale_handle), (cancelled, cancelled_digest, cancelled_handle) = grants
        # The superuser moves the run as mark_unknown would (the fence untouched), leaving the attempt at INTENT.
        await app_conn.execute("UPDATE app.runs SET state = 'OUTCOME_UNKNOWN' WHERE run_id = %s", (runs[0],))
        assert await refused(mcp_exec, "SELECT app.mark_sent(%s, %s)", (stale_handle, stale)) == "OC003"
        early = {"status": "SUCCEEDED", "action_id": str(stale), "payload_sha256": stale_digest}
        record = "SELECT app.record_outcome(%s, %s, %s, %s)"
        # An outcome before SENT is a protocol violation whatever the fence says.
        assert await refused(mcp_exec, record, (stale_handle, stale, "SUCCEEDED", Jsonb(early))) == "OC003"
```

Edit 12 (replace all, 3 occurrences): `(cancelled, "FAILED_NO_COMMIT", Jsonb(` →
`(cancelled_handle, cancelled, "FAILED_NO_COMMIT", Jsonb(`. The three lines grow past 120 characters; the task's
`ruff format` wraps them, and no later edit quotes them.

Afterwards this prints `0`:

```bash
grep -c "mark_sent(%s)\|record_outcome(%s, '\|mark_unknown(%s, 1) AS s" tests/e2e/test_definers_write_path_live.py
```

In `tests/e2e/test_worker_live.py` (as Task 3 left it):

Edit 1 (replace all, 2 occurrences): `await persistence.mark_sent(self.write, grant.action_id)` →
`await persistence.mark_sent(self.write, handle=handle, action_id=grant.action_id)`.

Edit 2, replace:

```python
from ops_core.lease import Lease
```

with:

```python
from ops_core.lease import RELEASED, Lease
```

Edit 3, replace:

```python
        await handlers.handle(deps, job, lease)
        assert (await persistence.run_row(app_conn, run))["state"] == "OUTCOME_UNKNOWN"
```

with:

```python
        before = lease.fence
        await handlers.handle(deps, job, lease)
        assert (await persistence.run_row(app_conn, run))["state"] == "OUTCOME_UNKNOWN"
        assert lease.fence == before + 1 and lease.lost == RELEASED  # bumped, handed over, released under it
        cur = await app_conn.execute(
            "SELECT fence, lease_until = '-infinity' AS released FROM app.run_lease WHERE run_id = %s", (run,)
        )
        row = await cur.fetchone()
        assert row is not None and (row["fence"], row["released"]) == (before + 1, True)
```

In `tests/e2e/test_mcp_write_live.py` (old line 279, as Task 3 left it), replace:

```python
    strand the run in EXECUTING with a SENT attempt. A future lease fence raises VersionConflict on exactly this call.
```

with:

```python
    strand the run in EXECUTING with a SENT attempt. The lease fence raises HandleRejected on this call (T13; proved
    live in test_fenced_definers_live.py); every mapped refusal must answer the same way.
```

In `tests/e2e/test_migration_0007_live.py` (as Task 2 wrote it):

Edit 1, replace:

```python
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from ops_core import persistence, settings
from ops_core.settings import Profile, Role
```

with:

```python
import importlib.util
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from ops_core import persistence, settings
from ops_core.settings import Profile, Role
from psycopg import sql
from psycopg.rows import dict_row
```

Edit 2, replace:

```python
FREE_PERMIT = "UPDATE app.model_permit SET holder = NULL, leased_until = '-infinity' WHERE slot = 1"
```

with:

```python
FREE_PERMIT = "UPDATE app.model_permit SET holder = NULL, leased_until = '-infinity' WHERE slot = 1"
VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "app" / "versions"
FUNCTION_DETAILS = (
    "SELECT pg_get_functiondef(p.oid) AS body, p.proacl::text AS acl, p.proowner::regrole::text AS owner,"
    " p.proconfig::text AS config FROM pg_proc p WHERE p.oid = %s::regprocedure"
)
SCRATCH_PREFIX = "r006_"  # every scratch database this module creates; leftovers are dropped by prefix
# Leftovers no session is connected to: a concurrent session's scratch database in use is never touched.
LEFTOVERS = (
    "SELECT d.datname FROM pg_database d WHERE starts_with(d.datname, %s)"
    " AND NOT EXISTS (SELECT 1 FROM pg_stat_activity a WHERE a.datname = d.datname)"
)


def revision_0007() -> Any:
    """Revision 0007 loaded by path, for the bodies its downgrade restores."""
    spec = importlib.util.spec_from_file_location("live_rev_0007", VERSIONS / "0007_leases_fences.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def built_to_0006(superuser: settings.Postgres, signatures: list[str]) -> dict[str, dict[str, Any]]:
    """The functions named, as a database built straight to 0006 holds them (review round 1, M3): definition, ACL,
    owner and settings. A scratch database is created, upgraded to 0006 by the applied revisions alone, read and
    dropped; the roles are cluster-wide, so its ACLs name the same roles as the test database's. A run killed before
    its `finally` leaves a database behind; the next run drops every leftover with the prefix first (review round 2,
    m6)."""
    from scripts.skeleton import upgrade

    scratch = f"{SCRATCH_PREFIX}{uuid4().hex[:12]}"
    try:
        with psycopg.connect(superuser.conninfo(), autocommit=True, row_factory=dict_row) as admin:
            for row in admin.execute(LEFTOVERS, (SCRATCH_PREFIX,)).fetchall():
                admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(row["datname"])))
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(scratch)))
        target = settings.Postgres(superuser.host, superuser.port, superuser.user, scratch, superuser.password)
        upgrade("app", target, "0006_admission_idempotency")
        with psycopg.connect(target.conninfo(), row_factory=dict_row) as conn:
            return {name: dict(conn.execute(FUNCTION_DETAILS, (name,)).fetchone() or {}) for name in signatures}
    finally:
        with psycopg.connect(superuser.conninfo(), autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(scratch)))
```

Edit 3, replace:

```python
        assert ("app_definer", "UPDATE", "fence") not in before["lease_cells"]
        assert not await exists(app_conn, "app.queued_runs_total()")
    finally:
        assert migrate(Profile.TEST) == 0  # every later test needs the head
    assert await snapshot(app_conn) == head  # the upgrade brings back exactly what the downgrade took
```

with:

```python
        assert ("app_definer", "UPDATE", "fence") not in before["lease_cells"]
        assert not await exists(app_conn, "app.queued_runs_total()")
        assert await exists(app_conn, "app.mark_sent(uuid)") and not await exists(app_conn, "app.mark_sent(text, uuid)")
        # Every function 0007 replaced is back exactly as the applied revision installed it (R006, ruling 31): the
        # stored source is the text between the body's dollar quotes.
        for name, args, _, body in revision_0007().RESTORED:
            cur = await app_conn.execute(
                "SELECT prosrc FROM pg_proc WHERE oid = %s::regprocedure", (f"app.{name}({args})",)
            )
            assert (await cur.fetchone())["prosrc"] == body.split("$fn$")[1], name
        # ...and so are their definitions, ACLs, owners and settings, against a database that never saw 0007.
        restored = [f"app.{name}({args})" for name, args, _, _ in revision_0007().RESTORED]
        reference = built_to_0006(superuser, restored)
        for signature in restored:
            cur = await app_conn.execute(FUNCTION_DETAILS, (signature,))
            assert dict(await cur.fetchone()) == reference[signature], signature
    finally:
        assert migrate(Profile.TEST) == 0  # every later test needs the head
    assert await snapshot(app_conn) == head  # the upgrade brings back exactly what the downgrade took
    assert await exists(app_conn, "app.mark_sent(text, uuid)") and not await exists(app_conn, "app.mark_sent(uuid)")
```

- [ ] **Step 5: The live fence tests**

Create `tests/e2e/test_fenced_definers_live.py`:

```python
"""T13 live (OPS_LIVE=1): the fence inside the definer functions, called by their real callers against the
per-session test database (Plan H rulings 5-9; R020's MCP side, R027's T13 half; errata 48, 53-55).

Catches: a handle that still resolves after a takeover or after its lease lapsed (R027's "expired fence"), a stale
mcp-write that writes SENT or sends anyway, a stale fence after SENT that becomes an error envelope instead of UNKNOWN
(Plan E final review I1), a revocation that refuses a lost owner or kills a newer owner's handles, and a mark_unknown
that does not bump the fence, accepts a stale or lapsed one, or keeps the old handles alive.
"""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import httpx2
import pytest
from ops_core import persistence
from ops_core.jobs import Server, Tool
from ops_core.lease import Lease
from ops_core.outcomes import ToolOutcome
from ops_core.settings import Role
from ops_core.states import RunState
from ops_mcp_write import destination, execution
from ops_mcp_write.server import outcome_envelope

from tests.e2e.conftest import expire_lease, lease_for, purge_run, purge_tenant
from tests.e2e.test_mcp_write_live import approved_run, make_deps, running_sim
from tests.e2e.test_migrations_and_persistence import new_run

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
BUMP = "UPDATE app.run_lease SET fence = fence + 1 WHERE run_id = %s"


async def investigate_job(app_conn: persistence.Conn, run: UUID) -> UUID:
    cur = await app_conn.execute("SELECT id FROM app.jobs WHERE run_id = %s AND type = 'investigate'", (run,))
    row = await cur.fetchone()
    assert row is not None
    return UUID(str(row["id"]))


async def read_handle(worker: persistence.Conn, run: UUID, job: UUID, lease: Lease) -> str:
    async with worker.transaction():
        return await persistence.mint_handle(
            worker, run_id=run, job_id=job, server=Server.READ, azp="ops-worker", fence=lease.fence
        )


async def resolve(mcp_read: persistence.Conn, handle: str) -> persistence.Invocation:
    """Resolve a read handle as mcp-read does for `search_procedures`."""
    return await persistence.resolve_invocation(mcp_read, handle=handle, azp="ops-worker", tool=Tool.SEARCH_PROCEDURES)


async def attempt_states(app_conn: persistence.Conn, run: UUID) -> list[str]:
    cur = await app_conn.execute(
        "SELECT s.state FROM app.action_attempt_state s JOIN app.execution_grant g USING (action_id)"
        " WHERE g.run_id = %s ORDER BY s.seq",
        (run,),
    )
    return [row["state"] for row in await cur.fetchall()]


async def test_a_handle_is_refused_after_its_fence_moves_and_after_its_lease_expires(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """Ruling 7: T13's half of R027 ("expired fence")."""
    a, b, mcp_read = await role_conn(Role.WORKER), await role_conn(Role.WORKER), await role_conn(Role.MCP_READ)
    tenant, _, run = await new_run(app_conn, api=await role_conn(Role.API))
    try:
        job = await investigate_job(app_conn, run)
        old = await read_handle(a, run, job, await lease_for(a, run, owner="wa"))
        assert (await resolve(mcp_read, old)).run_id == run
        await expire_lease(app_conn, run)  # lapsed, nobody else yet: the handle itself has 60 s left
        with pytest.raises(persistence.HandleRejected):
            await resolve(mcp_read, old)
        new = await read_handle(b, run, job, await lease_for(b, run, owner="wb"))
        with pytest.raises(persistence.HandleRejected):  # the fence moved: the old handle is dead though unexpired
            await resolve(mcp_read, old)
        assert (await resolve(mcp_read, new)).run_id == run
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


async def test_a_stale_fence_before_sent_is_a_handle_refusal_and_sends_nothing(
    app_conn: persistence.Conn, role_conn: RoleConn, secret: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ruling 6, before SENT: the lease moves between the grant and SENT; mark_sent refuses, nothing is sent, and
    server.py answers the refusal as INVALID_HANDLE (an honest error: nothing reached the destination)."""
    posts: list[int] = []
    run: UUID | None = None

    async def counting_post(*_: Any, **__: Any) -> None:
        posts.append(1)

    real_mark_sent = persistence.mark_sent

    async def takeover_then_mark_sent(conn: persistence.Conn, **kwargs: Any) -> str:
        await app_conn.execute(BUMP, (run,))  # another owner took the run after the grant committed
        return await real_mark_sent(conn, **kwargs)

    monkeypatch.setattr(destination, "post_incident", counting_post)
    monkeypatch.setattr(persistence, "mark_sent", takeover_then_mark_sent)
    try:
        _, run, proposal, handle = await approved_run(
            app_conn, api=await role_conn(Role.API), worker=await role_conn(Role.WORKER)
        )
        session = persistence.Session(await role_conn(Role.MCP_EXEC))
        async with httpx2.AsyncClient() as http:
            with pytest.raises(persistence.HandleRejected):
                await execution.create_incident(make_deps(session, http, secret), handle=handle, proposal_id=proposal)
        assert posts == [] and await attempt_states(app_conn, run) == ["INTENT"]
        assert (await persistence.run_row(app_conn, run))["state"] == "EXECUTING"
    finally:
        if run is not None:
            await purge_run(app_conn, run)


async def test_a_stale_fence_after_sent_is_unknown_never_an_error(
    app_conn: persistence.Conn, role_conn: RoleConn, secret: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ruling 6, after SENT: the destination commits, the lease moves before the outcome is recorded; record_outcome
    refuses, and mcp-write answers outcome/UNKNOWN, never an error envelope."""
    run: UUID | None = None
    original_post = destination.post_incident

    async def post_then_takeover(*args: Any, **kwargs: Any) -> destination.Reply | None:
        reply = await original_post(*args, **kwargs)  # the destination has committed
        await app_conn.execute(BUMP, (run,))
        return reply

    monkeypatch.setattr(destination, "post_incident", post_then_takeover)
    try:
        async with running_sim():
            _, run, proposal, handle = await approved_run(
                app_conn, api=await role_conn(Role.API), worker=await role_conn(Role.WORKER)
            )
            session = persistence.Session(await role_conn(Role.MCP_EXEC))
            async with httpx2.AsyncClient() as http:
                outcome = await execution.create_incident(
                    make_deps(session, http, secret), handle=handle, proposal_id=proposal
                )
        doc = outcome_envelope(outcome)
        assert doc["status"] == "outcome" and doc["error"] is None
        assert doc["data"]["status"] == ToolOutcome.UNKNOWN.value
        assert await attempt_states(app_conn, run) == ["INTENT", "SENT"]  # nothing recorded after SENT
    finally:
        if run is not None:
            await purge_run(app_conn, run)


async def test_revoke_handles_takes_only_the_old_fences_handles(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """Ruling 8: a lost owner still revokes its own handles; the new owner's survive."""
    a, b, mcp_read = await role_conn(Role.WORKER), await role_conn(Role.WORKER), await role_conn(Role.MCP_READ)
    tenant, _, run = await new_run(app_conn, api=await role_conn(Role.API))
    try:
        job = await investigate_job(app_conn, run)
        first = await lease_for(a, run, owner="wa")
        old = await read_handle(a, run, job, first)
        await expire_lease(app_conn, run)
        new = await read_handle(b, run, job, await lease_for(b, run, owner="wb"))
        async with a.transaction():
            assert await persistence.revoke_handles(a, run, first.fence) == 1  # never refused for a stale fence
        cur = await app_conn.execute(
            "SELECT handle_sha256, revoked_at IS NOT NULL AS revoked FROM app.invocation_context WHERE run_id = %s",
            (run,),
        )
        revoked = {row["handle_sha256"]: row["revoked"] for row in await cur.fetchall()}
        assert revoked == {persistence.handle_hash(old): True, persistence.handle_hash(new): False}
        assert (await resolve(mcp_read, new)).run_id == run
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


async def test_mark_unknown_bumps_the_fence_and_returns_it(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    """Ruling 9: the lease's own fence marks UNKNOWN once and moves the fence; the old fence and a lapsed lease are
    refused; the old handles are dead."""
    worker, mcp_exec = await role_conn(Role.WORKER), await role_conn(Role.MCP_EXEC)
    _, run, proposal, handle = await approved_run(app_conn, api=await role_conn(Role.API), worker=worker)
    try:
        cur = await app_conn.execute("SELECT fence FROM app.run_lease WHERE run_id = %s", (run,))
        fence = int((await cur.fetchone())["fence"])
        async with mcp_exec.transaction():
            grant = await persistence.grant_execution(mcp_exec, handle=handle, proposal_id=proposal)
            assert await persistence.mark_sent(mcp_exec, handle=handle, action_id=grant.action_id) == "sent"
        async with worker.transaction():
            unknown = await persistence.mark_unknown(worker, run, fence)
        assert unknown == persistence.Unknown(RunState.OUTCOME_UNKNOWN, fence + 1)
        with pytest.raises(persistence.HandleRejected):  # minted under the old fence: dead and revoked
            async with mcp_exec.transaction():
                await persistence.lookup_action(mcp_exec, handle=handle)
        with pytest.raises(persistence.VersionConflict):  # the old fence is stale now
            async with worker.transaction():
                await persistence.mark_unknown(worker, run, fence)
        await expire_lease(app_conn, run)
        with pytest.raises(persistence.VersionConflict):  # the current fence, but the lease lapsed
            async with worker.transaction():
                await persistence.mark_unknown(worker, run, fence + 1)
        cur = await app_conn.execute(
            "SELECT revoked_at IS NOT NULL AS revoked FROM app.invocation_context WHERE handle_sha256 = %s",
            (persistence.handle_hash(handle),),
        )
        assert (await cur.fetchone())["revoked"]
    finally:
        await purge_run(app_conn, run)  # the seeded tenant ALPHA stays
```

Run (dev stack up, no skeleton process running):

```bash
OPS_LIVE=1 PROFILE=test PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_fenced_definers_live.py \
  tests/e2e/test_definers_write_path_live.py tests/e2e/test_definers_run_path_live.py tests/e2e/test_worker_live.py \
  tests/e2e/test_mcp_write_live.py tests/e2e/test_migration_0007_live.py tests/e2e/test_leases_live.py -q
```

Expected: `49 passed` (5 new, write path 11, run path 8, worker 4, mcp-write 6, revision 0007 5, leases 10).

- [ ] **Step 6: Gates and commit**

Format, lint and count characters on every file of this task.

Run: `PYTHONUTF8=1 uv run python scripts/check.py`
Expected: `CHECK: GREEN`; pytest `890 passed, 124 skipped` (883 + 3 + 2 + 2; the 5 new live tests skip).

Run: `PYTHONUTF8=1 uv run python scripts/check.py --profile test`
Expected: `CHECK: GREEN`; pytest `993 passed, 21 skipped` (R105's mcp-write now checks the fence through the handle).
Then `git checkout -- reports/bootstrap reports/skeleton reports/auth reports/admission`.

Run: `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`
Expected: exit 0.

```bash
git add migrations/app/versions/0007_leases_fences.py core/src/ops_core/privileges.py core/src/ops_core/persistence.py
git add worker/src/ops_worker/handlers.py mcp-write/src/ops_mcp_write tests/plan_h tests/e2e/conftest.py
git add tests/e2e/test_definers_write_path_live.py tests/e2e/test_worker_live.py tests/e2e/test_mcp_write_live.py
git add tests/e2e/test_migration_0007_live.py tests/e2e/test_fenced_definers_live.py
git commit -m "feat(definers): the lease fence in every handle function; mark_unknown moves and returns it (T13)"
```

---

### Task 5: The heartbeat thread, the liveness and budget gates, cancelling effects on loss, and the model permit

**Files:**
- Create: `worker/src/ops_worker/heartbeat.py`, `worker/src/ops_worker/permit.py`, `tests/plan_h/test_heartbeat.py`,
  `tests/plan_h/test_permit.py`, `tests/e2e/test_heartbeat_live.py`
- Modify: `core/src/ops_core/lease.py` (imports; `Renewal`, `renew` at the end); `core/src/ops_core/persistence.py`
  (`take_model_permit`, `release_model_permit` after `unclaim_job`); `worker/src/ops_worker/handlers.py` (imports,
  `Deps`, the draft call); `worker/src/ops_worker/main.py` (docstring, imports, `run_job`, `_main`);
  `worker/src/ops_worker/drafting.py:9-13` (imports), `:56-62` (`FakeDraftGenerator`);
  `tests/plan_h/test_worker_units.py` (an import, the permit fakes, the unit count, three tests)

**Requirements:** R088 (the heartbeat survives long or blocking work; a lease loss cancels the effect in flight), DoD
3, the model permit (SA:203-205); brief rulings 10, 12, 16, 17, 18, 19 (as amended in review round 1, B1), 20.

**Interfaces:**
- Consumes: `Lease` (`renewed`, `mark_lost`, `cancel_effects`, `effect`, `fence_moved_by_owner`, `lost`,
  `held_since`, `renewed_at`, `deadline`), `LOCK_FOR_UPDATE`, `RENEW`, `RELEASED` (Task 3); `LeaseSettings` (Task 1);
  `persistence.Claimed`, `claim_next`, `handlers.abandon` (Task 3); `settings.Postgres.conninfo()`.
- Produces: `ops_core.lease.Renewal` (`RENEWED`, `RELEASED`, `MOVED`, `EXPIRED`), `renew(conn:
  psycopg.Connection[DictRow], lease: Lease, fence: int) -> Renewal`; `ops_worker.heartbeat.TICK_SECONDS`,
  `STAMP_SECONDS`, `Liveness(clock=time.monotonic)` with `stamp()`, `age(now) -> float`; `keep_stamping(liveness,
  stop) -> None` (coroutine); `connector(pg: Postgres) -> Callable[[], SyncConn]`; `Heartbeat(*, connect, settings,
  liveness, clock=time.monotonic, renewer=renew, tick_seconds=TICK_SECONDS)`, a `threading.Thread` with
  `hold(lease)`, `drop(lease)`, `stop()`, `tick()`, `renewals: int`, `max_loop_age: float`;
  `ops_worker.permit.PERMIT_TTL_SECONDS = 65`, `backoff(attempt, rand=random.random) -> float`, `model_permit(conn, *,
  holder, lease, sleep=asyncio.sleep, rand=random.random)` (async context manager yielding the slot; `sleep` returns a
  coroutine, run as a lease effect); `persistence.take_model_permit(conn, *, holder,
  run_id, ttl_seconds) -> int | None`, `persistence.release_model_permit(conn, *, slot, holder) -> None`;
  `handlers.Deps.heartbeat: Heartbeat | None = None`; `FakeDraftGenerator(delay_seconds: float = 0.0)`.

- [ ] **Step 1: Write the failing unit tests**

Create `tests/plan_h/test_heartbeat.py`:

```python
"""The heartbeat thread's decisions with a fake clock and a scripted renewer (Plan H rulings 10, 16-19), plus one run
of the real thread against a real event loop.

Catches: a renewal more or less often than once per heartbeat, a loop blocked for 25 s that loses its lease (DoD 3), a
dead loop or a job past its 90 s budget that keeps renewing (T13 review note 4), a renewal that meets the owner's own
re-fence and cancels a healthy job (review note 2), another owner's fence or an expired lease that is not a loss, a
transient error that loses the lease before the local deadline or never loses it after, a released lease whose effects
are cancelled, and a cancellation that cannot cross from the thread to the effect on the event loop.
"""

import asyncio
from typing import Any
from uuid import UUID

import psycopg
import pytest
from ops_core.lease import DEADLINE_MARGIN_SECONDS, Lease, LeaseLost, Renewal
from ops_core.settings import RENEWAL_MARGIN_SECONDS, LeaseSettings
from ops_worker.heartbeat import TICK_SECONDS, Heartbeat, Liveness

RUN = UUID(int=11)


class Clock:
    """A monotonic clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class FakeConn:
    closed = False
    broken = False

    def close(self) -> None:
        self.closed = True


class Renewer:
    """Answers each renewal from a script (a Renewal, an exception to raise, or a callable that returns one); the
    last step repeats. Records the fence of every call."""

    def __init__(self, *script: Any) -> None:
        self.script = list(script)
        self.fences: list[int] = []

    def __call__(self, _conn: Any, _lease: Lease, fence: int) -> Renewal:
        self.fences.append(fence)
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(step, BaseException):
            raise step
        if callable(step) and not isinstance(step, Renewal):
            return step()
        return step


class CountingLease(Lease):
    """A Lease that counts how often the heartbeat cancels its effects."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.cancels = 0

    def cancel_effects(self) -> int:
        self.cancels += 1
        return super().cancel_effects()


class Setup:
    def __init__(self, *script: Any) -> None:
        self.clock = Clock()
        self.liveness = Liveness(self.clock)
        self.renewer = Renewer(*script)
        self.connects = 0
        self.heartbeat = Heartbeat(
            connect=self.connect,
            settings=LeaseSettings(),  # the real defaults: the clock is fake, so nothing waits
            liveness=self.liveness,
            clock=self.clock,
            renewer=self.renewer,
        )
        self.lease = CountingLease(run_id=RUN, owner="w:test", fence=3, lease_seconds=30, started=0.0, clock=self.clock)
        self.heartbeat.hold(self.lease)

    @property
    def cancels(self) -> int:
        """How often the thread cancelled the lease's effects (once per loss)."""
        return self.lease.cancels

    def connect(self) -> Any:
        self.connects += 1
        return FakeConn()

    def at(self, now: float, *, alive: bool = True) -> None:
        """Move the clock, let a live loop stamp, and tick once."""
        self.clock.now = now
        if alive:
            self.liveness.stamp()
        self.heartbeat.tick()


def test_the_settings_margin_is_the_deadline_margin_plus_one_tick() -> None:
    # settings.py keeps its own copy so it imports nothing from the worker (review round 2, m4); this pins the copy.
    assert RENEWAL_MARGIN_SECONDS == DEADLINE_MARGIN_SECONDS + TICK_SECONDS


def test_it_renews_once_per_heartbeat() -> None:
    s = Setup(Renewal.RENEWED)
    for now in (5.0, 10.0, 15.0, 20.0):
        s.at(now)
    assert s.renewer.fences == [3, 3] and s.heartbeat.renewals == 2
    assert (s.lease.renewed_at, s.lease.deadline) == (20.0, 45.0)  # ruling 18: the instant before the renewal + 25


def test_a_blocked_loop_keeps_its_lease_until_the_stall_gate_then_loses_it() -> None:
    s = Setup(Renewal.RENEWED)
    for now in (10.0, 20.0, 25.0, 27.9):  # the loop stamped at 0 and is blocked since (DoD 3: 25 s keeps the lease)
        s.at(now, alive=False)
    assert s.heartbeat.renewals == 2 and s.cancels == 0 and s.lease.lost is None
    assert s.heartbeat.max_loop_age == 27.9  # the longest silence it saw, for the DoD-3 evidence line
    s.at(28.0, alive=False)  # OPS_LOOP_STALL_SECONDS
    assert (s.lease.lost, s.cancels) == ("event loop stalled", 1)
    s.at(40.0, alive=False)
    assert s.cancels == 1 and s.heartbeat.renewals == 2  # dropped: no second cancel, no renewal for a lost lease


def test_the_compute_budget_closes_the_gate() -> None:
    s = Setup(Renewal.RENEWED)
    for now in range(10, 90, 10):
        s.at(float(now))
    assert s.heartbeat.renewals == 8 and s.lease.lost is None
    s.at(90.0)  # OPS_COMPUTE_BUDGET_SECONDS since the claim
    assert (s.lease.lost, s.cancels) == ("compute budget spent", 1)


def test_a_renewal_that_meets_its_own_refence_retries() -> None:
    s = Setup(Renewal.MOVED, Renewal.RENEWED)
    s.lease.begin_refence()  # mark_unknown is running: its bump may land before this renewal
    s.at(10.0)
    assert s.cancels == 0 and s.lease.lost is None
    s.lease.end_refence(4)
    s.at(11.0)  # still due: the retry renews under the new fence
    assert s.renewer.fences == [3, 4] and s.heartbeat.renewals == 1

    def bump_committed() -> Renewal:  # the hand-over lands between the thread's read of fence 3 and its verdict
        settled.lease.end_refence(5)
        return Renewal.MOVED

    settled = Setup(bump_committed, Renewal.RENEWED)
    settled.at(10.0)
    assert settled.cancels == 0
    settled.at(11.0)
    assert settled.renewer.fences == [3, 5] and settled.heartbeat.renewals == 1


@pytest.mark.parametrize(
    ("verdict", "reason"),
    [(Renewal.MOVED, "another owner took the lease"), (Renewal.EXPIRED, "the lease expired")],
)
def test_another_owners_fence_or_an_expired_lease_is_a_loss(verdict: Renewal, reason: str) -> None:
    s = Setup(verdict)
    s.at(10.0)
    assert (s.lease.lost, s.cancels) == (reason, 1)


def test_transient_errors_are_retried_until_the_deadline() -> None:
    lost_connection = psycopg.OperationalError("server closed the connection")
    timed_out = psycopg.errors.QueryCanceled("canceling statement due to statement timeout")  # review round 2, m3
    s = Setup(lost_connection, timed_out, Renewal.RENEWED)
    s.at(10.0)
    s.at(11.0)
    assert s.lease.lost is None and s.cancels == 0
    s.at(12.0)
    assert s.heartbeat.renewals == 1 and s.connects == 3  # reopened after each failure (ruling 16)
    s.renewer.script = [lost_connection]
    s.at(22.0)
    assert s.lease.lost is None  # the deadline is 12 + 25
    s.at(37.0)
    assert (s.lease.lost, s.cancels) == ("renewals failed until the local deadline", 1)


def test_a_released_lease_is_dropped_quietly() -> None:
    s = Setup(Renewal.RELEASED)
    s.at(10.0)
    s.at(20.0)
    assert s.cancels == 0 and s.renewer.fences == [3]  # dropped after the first answer


def test_the_thread_cancels_the_effect_on_the_loop_and_stops() -> None:
    s = Setup(Renewal.MOVED)
    conn = FakeConn()
    thread = Heartbeat(
        connect=lambda: conn,
        settings=LeaseSettings(),
        liveness=s.liveness,
        clock=s.clock,
        renewer=s.renewer,
        tick_seconds=0.01,
    )

    async def scenario() -> None:
        thread.hold(s.lease)
        thread.start()
        s.clock.now = 10.0
        s.liveness.stamp()
        with pytest.raises(LeaseLost):  # the effect in flight, cancelled from the thread (ruling 19, round 1 B1)
            await asyncio.wait_for(s.lease.effect(asyncio.Event().wait()), timeout=2)

    asyncio.run(scenario())
    thread.stop()
    thread.join(timeout=2)
    assert not thread.is_alive() and conn.closed and s.lease.lost == "another owner took the lease"
```

Create `tests/plan_h/test_permit.py`:

```python
"""The model permit around the draft call (Plan H ruling 12, SA:203-205) and the slow fake drafter (R088), without a
database.

Catches: a backoff that does not double or exceeds 2 s, jitter that can drop to zero (two waiters hammering one row),
a permit kept after the block or after a lost lease cancelled the call (one stuck permit stops every draft for 65 s),
a permit taken or released by a loss during the back-off (review round 1, I2), a waiter that outlives its lease, and a
slow drafter that blocks the event loop.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import pytest
from ops_core import persistence
from ops_core.lease import Lease, LeaseLost
from ops_worker.drafting import FakeDraftGenerator
from ops_worker.permit import PERMIT_TTL_SECONDS, backoff, model_permit

from tests.plan_d.test_worker import EV, REQ

RUN = UUID(int=12)


class FakeConn:
    def __init__(self) -> None:
        self.units = 0

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        self.units += 1
        yield


def permits(monkeypatch: pytest.MonkeyPatch, answers: list[int | None]) -> list[tuple[str, Any]]:
    calls: list[tuple[str, Any]] = []

    async def take(_conn: Any, *, holder: str, run_id: UUID, ttl_seconds: int) -> int | None:
        calls.append(("take", (holder, run_id, ttl_seconds)))
        return answers.pop(0) if len(answers) > 1 else answers[0]

    async def release(_conn: Any, *, slot: int, holder: str) -> None:
        calls.append(("release", (slot, holder)))

    monkeypatch.setattr(persistence, "take_model_permit", take)
    monkeypatch.setattr(persistence, "release_model_permit", release)
    return calls


def lease(clock: list[float]) -> Lease:
    return Lease(run_id=RUN, owner="w:test", fence=1, lease_seconds=30, started=0.0, clock=lambda: clock[0])


def lose(held: Lease) -> None:
    """What the heartbeat thread does on a loss: record why, then cancel the effects in flight."""
    held.mark_lost("another owner took the lease")
    held.cancel_effects()


def test_the_backoff_doubles_to_two_seconds_with_jitter_in_the_upper_half() -> None:
    assert [backoff(i, lambda: 1.0) for i in range(6)] == [0.25, 0.5, 1.0, 2.0, 2.0, 2.0]
    assert [backoff(i, lambda: 0.0) for i in range(4)] == [0.125, 0.25, 0.5, 1.0]
    assert backoff(10_000, lambda: 1.0) == 2.0  # a long wait never overflows the doubling
    assert PERMIT_TTL_SECONDS == 65  # a 60 s model attempt plus 5 s (SA:596, ruling 12)


def test_the_permit_is_released_after_the_block_and_after_a_lost_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = permits(monkeypatch, [1])
    conn: Any = FakeConn()

    async def draft_then(lost: bool) -> None:
        held = lease([1.0])
        async with model_permit(conn, holder="w:test", lease=held) as slot:
            assert slot == 1
            if lost:  # the heartbeat loses the lease mid-draft and cancels the model call (ruling 19)
                asyncio.get_running_loop().call_later(0.01, lose, held)
                await held.effect(asyncio.Event().wait())

    asyncio.run(draft_then(False))
    with pytest.raises(LeaseLost):
        asyncio.run(draft_then(True))
    assert [name for name, _ in calls] == ["take", "release", "take", "release"]
    assert calls[0][1] == ("w:test", RUN, PERMIT_TTL_SECONDS) and calls[1][1] == (1, "w:test")


def test_a_loss_during_the_backoff_takes_and_keeps_no_permit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review round 1, I2: the take and the release are database units and are never cancelled; the back-off sleep
    is the one effect, so a loss there leaves nothing taken and nothing to release."""
    calls = permits(monkeypatch, [None])

    async def hang(_seconds: float) -> None:
        await asyncio.Event().wait()

    async def draft() -> None:
        held = lease([1.0])
        conn: Any = FakeConn()
        asyncio.get_running_loop().call_later(0.01, lose, held)
        async with model_permit(conn, holder="w:test", lease=held, sleep=hang):
            pass

    with pytest.raises(LeaseLost):
        asyncio.run(draft())
    assert [name for name, _ in calls] == ["take"]


def test_a_busy_permit_is_polled_with_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = permits(monkeypatch, [None, None, 1])
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    async def draft() -> None:
        conn: Any = FakeConn()
        async with model_permit(conn, holder="w:test", lease=lease([1.0]), sleep=sleep, rand=lambda: 1.0):
            pass

    asyncio.run(draft())
    assert waits == [0.25, 0.5] and [name for name, _ in calls] == ["take", "take", "take", "release"]


def test_a_lost_lease_stops_the_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = permits(monkeypatch, [None])
    clock = [1.0]

    async def sleep(_seconds: float) -> None:
        clock[0] = 26.0  # the lease's local deadline (0 + 30 - 5) passes while it waits

    async def draft() -> None:
        conn: Any = FakeConn()
        async with model_permit(conn, holder="w:test", lease=lease(clock), sleep=sleep):
            pass

    with pytest.raises(LeaseLost):
        asyncio.run(draft())
    assert [name for name, _ in calls] == ["take"]  # nothing to release: no permit was held


def test_the_fake_drafter_can_be_slow_without_blocking_the_loop() -> None:
    ticks = 0

    async def scenario() -> Any:
        nonlocal ticks

        async def count() -> None:
            nonlocal ticks
            while True:
                ticks += 1
                await asyncio.sleep(0.01)

        counter = asyncio.create_task(count())
        draft = await FakeDraftGenerator(delay_seconds=0.2).generate(REQ, EV)
        counter.cancel()
        return draft

    draft = asyncio.run(scenario())
    assert draft.kind == "proposal" and ticks >= 5  # the loop kept running while the drafter waited
```

In `tests/plan_h/test_worker_units.py` (as Task 4 left it):

Edit 0, replace:

```python
from ops_worker.drafting import FakeDraftGenerator
from psycopg.pq import TransactionStatus
```

with:

```python
from ops_worker.drafting import FakeDraftGenerator
from ops_worker.mcp import HttpMcpCaller
from psycopg.pq import TransactionStatus
```

Edit 1, replace:

```python
        "mark_unknown": recorder("mark_unknown", persistence.Unknown(RunState.OUTCOME_UNKNOWN, 4)),
```

with:

```python
        "mark_unknown": recorder("mark_unknown", persistence.Unknown(RunState.OUTCOME_UNKNOWN, 4)),
        "take_model_permit": recorder("take_model_permit", 1),
        "release_model_permit": recorder("release_model_permit"),
```

Edit 2, replace:

```python
    assert len(units) == 5, log.entries  # start, tool.started, tool.completed, DRAFTING, draft and freeze
```

with:

```python
    assert len(units) == 7, log.entries  # start, tool.started, tool.completed, DRAFTING, permit, release, freeze
    assert (
        log.entries.index("take_model_permit")
        < log.entries.index("release_model_permit")
        < log.entries.index("freeze_proposal")
    )  # the permit is held around the draft call only (ruling 12)
```

Append after two blank lines:

```python
def lose(lease: Lease) -> int:
    """What the heartbeat thread does on a loss: record why, then cancel the effects in flight."""
    lease.mark_lost("another owner took the lease")
    return lease.cancel_effects()


def test_a_heartbeat_cancel_hands_the_job_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ruling 19 (as amended in review round 1, B1): the thread marks the lease lost and cancels the MCP call in
    flight; the handler sees LeaseLost and the loop revokes and hands the job back."""
    log = Log()
    patch(monkeypatch, log)
    deps, lease = make(log)

    class Hanging:
        async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
            log.entries.append(f"mcp:{tool}")
            await asyncio.Event().wait()  # an MCP call that never answers
            return {}

    class FakeHeartbeat:
        def __init__(self) -> None:
            self.held: Lease | None = None
            self.dropped = False

        def hold(self, held: Lease) -> None:
            self.held = held

        def drop(self, _lease: Lease) -> None:
            self.dropped = True

    heartbeat = FakeHeartbeat()
    deps.mcp = Hanging()
    deps.heartbeat = heartbeat  # duck-typed stand-ins (the test modules are not type-checked)
    cancelled: list[int] = []

    async def scenario() -> None:
        claimed: Any = persistence.Claimed(dict(JOB), lease)
        job = asyncio.create_task(main.run_job(deps, claimed))
        while "mcp:search_procedures" not in log.entries:
            await asyncio.sleep(0)
        assert heartbeat.held is lease
        cancelled.append(lose(lease))
        await job

    asyncio.run(scenario())
    assert cancelled == [1] and heartbeat.dropped  # exactly the one effect in flight
    assert log.units()[-1] == ["set_tenant", "revoke_handles", "unclaim_job"]
    assert "release_lease" not in log.entries and log.entries.count("transition_run") == 1


def test_a_loss_during_a_unit_never_interrupts_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review round 1, B1: the heartbeat may lose the lease while a database unit runs. Nothing cancels the unit, which
    commits whole; the handler stops at its next check, before the MCP call, and hands the job back."""
    log = Log()
    patch(monkeypatch, log)
    deps, lease = make(log)
    cancelled: list[int] = []

    async def fenced(_conn: Any, held: Lease) -> None:  # the real fenced checks the local state first
        log.entries.append("fenced")
        held.check()

    async def transition_then_lose(*_: Any, **__: Any) -> int:
        log.entries.append("transition_run")
        cancelled.append(lose(lease))  # the thread, mid-unit
        await asyncio.sleep(0.01)  # still inside the unit when a cancellation would land
        return 2

    monkeypatch.setattr(persistence, "fenced", fenced)
    monkeypatch.setattr(persistence, "transition_run", transition_then_lose)
    claimed: Any = persistence.Claimed(dict(JOB), lease)
    asyncio.run(main.run_job(deps, claimed))
    first = log.entries[: log.entries.index("COMMIT") + 1]
    assert first[0] == "BEGIN" and "mint_handle" in first and "ROLLBACK" not in first  # the unit committed whole
    assert cancelled == [0] and "mcp:search_procedures" not in log.entries  # no effect was in flight to cancel
    assert log.units()[-1] == ["set_tenant", "revoke_handles", "unclaim_job"]


def test_a_lost_lease_cancels_a_real_mcp_call() -> None:
    """Review round 1, M7: the real client (httpx2 inside the MCP SDK's anyio task groups) against a local server that
    accepts the request and never answers. The loss reaches the caller as LeaseLost, whatever wrapper the client puts
    around the cancellation, long before the client's 60 s read timeout."""
    _, lease = make(Log())

    class Token:
        async def token(self) -> str:
            return "workload-token"

    async def silent(reader: asyncio.StreamReader, _writer: asyncio.StreamWriter) -> None:
        await reader.read(65536)  # the request arrives; no answer ever leaves
        await asyncio.Event().wait()

    async def scenario() -> float:
        server = await asyncio.start_server(silent, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        loop = asyncio.get_running_loop()
        started = loop.time()
        loop.call_later(0.5, lose, lease)
        try:
            with pytest.raises(LeaseLost):
                await lease.effect(
                    HttpMcpCaller(Token()).call(
                        f"http://127.0.0.1:{port}/mcp", handle="h", tool="search_procedures", arguments={}
                    )
                )
        finally:
            server.close()
        return loop.time() - started

    assert asyncio.run(scenario()) < 10
```

Run: `uv run python -m pytest tests/plan_h/test_heartbeat.py tests/plan_h/test_permit.py -q`
Expected: `2 errors in` (pytest stops at collection errors: `Interrupted: 2 errors during collection`): the heartbeat
module with `ImportError: cannot import name 'Renewal' from 'ops_core.lease'`, the permit module with
`ModuleNotFoundError: No module named 'ops_worker.permit'`.

Run: `uv run python -m pytest tests/plan_h/test_worker_units.py -q`
Expected: `10 failed, 3 passed`: every worker test that installs the fakes fails with `AttributeError: <module
'ops_core.persistence'> has no attribute 'take_model_permit'` (monkeypatch refuses to set an attribute that does not
exist); the deferral test, the abandon test and the real-MCP test, which install none, pass (the last two already
hold with Task 3's `Lease.effect`).

- [ ] **Step 2: The renewal unit, the thread and the permit**

In `core/src/ops_core/lease.py` (as Task 3 wrote it):

Edit 1, replace:

```python
from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID
```

with:

```python
from __future__ import annotations

import asyncio
import enum
import threading
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

import psycopg
from psycopg.rows import DictRow
```

Edit 2, append at the end of the file, after two blank lines:

```python
class Renewal(enum.Enum):
    """What one renewal unit found (Plan H ruling 16)."""

    RENEWED = "renewed"  # owner and fence matched, the lease was live, lease_until moved on
    RELEASED = "released"  # the job's final unit gave the lease back: nothing left to renew
    MOVED = "moved"  # another owner or another fence holds the row
    EXPIRED = "expired"  # still this owner and fence, but the lease lapsed on the database clock


def renew(conn: psycopg.Connection[DictRow], lease: Lease, fence: int) -> Renewal:
    """One renewal unit on the heartbeat's own synchronous connection (SA:193-194, ruling 16): the lease row FOR
    UPDATE from the start (the unit writes it, SA:191), owner and fence compared, liveness read on the database clock
    after the lock, then `lease_until` moved on by one lease. `fence` is the value the caller read from the shared
    Lease before the call, so a mismatch can be told apart from the owner's own re-fence (ruling 10)."""
    with conn.transaction():
        row = conn.execute(LOCK_FOR_UPDATE, (lease.run_id,)).fetchone()
        if row is None or row["owner"] != lease.owner or row["fence"] != fence:
            return Renewal.MOVED
        if row["released"]:
            return Renewal.RELEASED
        if not row["live"]:
            return Renewal.EXPIRED
        conn.execute(RENEW, (lease.lease_seconds, lease.run_id))
    return Renewal.RENEWED
```

In `core/src/ops_core/persistence.py`, insert after `unclaim_job` (as Task 3 wrote it):

```python
async def take_model_permit(conn: Conn, *, holder: str, run_id: UUID, ttl_seconds: int) -> int | None:
    """One free model permit slot for `ttl_seconds` (Plan H ruling 12), or None while every slot is held. SKIP LOCKED
    never waits, and a slot whose TTL passed counts as free on the application clock, so nobody needs to reclaim it."""
    cur = await conn.execute(
        "UPDATE app.model_permit SET holder = %s, run_id = %s,"
        " leased_until = app.current_time() + make_interval(secs => %s)"
        " WHERE slot = (SELECT slot FROM app.model_permit WHERE leased_until <= app.current_time()"
        " ORDER BY slot FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING slot",
        (holder, run_id, ttl_seconds),
    )
    row = await cur.fetchone()
    return None if row is None else int(row["slot"])


async def release_model_permit(conn: Conn, *, slot: int, holder: str) -> None:
    """Give the permit back, unless its TTL passed and another holder took it meanwhile."""
    await conn.execute(
        "UPDATE app.model_permit SET holder = NULL, run_id = NULL, leased_until = '-infinity'"
        " WHERE slot = %s AND holder = %s",
        (slot, holder),
    )
```

Create `worker/src/ops_worker/heartbeat.py`:

```python
"""The heartbeat thread (AM-12 SA:193-199, Plan H rulings 16-19): one daemon thread per worker process with its own
synchronous psycopg connection as role `worker`, renewing the run lease the event loop holds while the loop shows
signs of life and the compute budget lasts. A thread rather than a task, so a blocked event loop (DoD 3: 25 s) cannot
stop the renewal; gated, so a loop that is dead rather than busy, or a job past its budget, cannot keep a run (T13
review note 4).

Windows: the worker's event loop must be a SelectorEventLoop because psycopg's *async* connection refuses the
Proactor loop (Plan D ruling 23). This thread uses psycopg's *synchronous* connection, which never touches an event
loop, so that constraint does not apply to it.

When renewal fails (another owner or fence, an expired lease, a gate closing, or errors until the local deadline) the
thread marks the lease lost and cancels the job's effects in flight (`Lease.cancel_effects`, through
`loop.call_soon_threadsafe`; ruling 19 as amended in review round 1, B1). It never cancels a database unit: a loss
during one is caught by the next fence check. The loop then revokes the job's handles and hands the job back. A
broken connection is reopened on the next tick (ruling 16).
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable

import psycopg
from ops_core.lease import Lease, Renewal, renew
from ops_core.settings import LeaseSettings, Postgres
from psycopg.rows import DictRow, dict_row

log = logging.getLogger("ops_worker.heartbeat")
TICK_SECONDS = 1.0  # how often the thread looks at the lease; it renews every `heartbeat_seconds`
STAMP_SECONDS = 1.0  # how often a live event loop stamps its liveness

SyncConn = psycopg.Connection[DictRow]
Renewer = Callable[[SyncConn, Lease, int], Renewal]


class Liveness:
    """The event loop's last sign of life: a monotonic instant the loop stamps and the thread reads."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._stamped = clock()

    def stamp(self) -> None:
        """Called on the event loop: it is alive now."""
        with self._lock:
            self._stamped = self._clock()

    def age(self, now: float) -> float:
        """Seconds since the loop last stamped, as of `now` on the same monotonic clock."""
        with self._lock:
            return now - self._stamped


async def keep_stamping(liveness: Liveness, stop: asyncio.Event) -> None:
    """The loop's half of the liveness gate (ruling 17): a stamp every second until stopped. A blocked loop stops
    stamping, which is exactly what the thread measures."""
    while not stop.is_set():
        liveness.stamp()
        try:
            await asyncio.wait_for(stop.wait(), timeout=STAMP_SECONDS)
        except TimeoutError:
            pass


def connector(pg: Postgres) -> Callable[[], SyncConn]:
    """How the thread opens its connection: role `worker` through the same conninfo builder as the loop's (it pins
    `-c timezone=UTC`), autocommit with explicit units, a 5 s connect timeout (a server that accepts and never answers
    must not hold the tick past the local deadline), TCP keepalives (an idle half-open connection is noticed in about
    20 s on Linux, about 60 s on Windows, where libpq ignores `keepalives_count`), and 5 s lock and statement timeouts
    so one renewal never waits on the server for ever (review round 2, m3). Neither keepalives nor the statement
    timeout bound a renewal sent to a peer that vanished (TCP retransmission does); the local deadline does: the
    loop's own `check()` stops the job then, and the renewal error becomes a loss at the next tick past it. Every
    failure here is a psycopg error, which the tick treats as transient: the connection is reopened, and the lease is
    lost only once its local deadline has passed. The two timeouts are SET after connecting because the conninfo's
    `options` already carries the time zone; a failed SET closes the new connection (review round 3)."""

    def connect() -> SyncConn:
        conn = psycopg.connect(
            pg.conninfo(),
            autocommit=True,
            row_factory=dict_row,
            connect_timeout=5,
            keepalives=1,
            keepalives_idle=10,
            keepalives_interval=5,
            keepalives_count=2,
        )
        try:
            conn.execute("SET lock_timeout = '5s'")  # SET takes no bind parameter; the values are constants
            conn.execute("SET statement_timeout = '5s'")
        except BaseException:  # re-raised: a failed SET must not leave the connection open
            conn.close()
            raise
        return conn

    return connect


class Heartbeat(threading.Thread):
    """Renews the lease the event loop holds (rulings 16-19); idle while it holds none."""

    def __init__(
        self,
        *,
        connect: Callable[[], SyncConn],
        settings: LeaseSettings,
        liveness: Liveness,
        clock: Callable[[], float] = time.monotonic,
        renewer: Renewer = renew,
        tick_seconds: float = TICK_SECONDS,
    ) -> None:
        super().__init__(name="lease-heartbeat", daemon=True)
        self._connect = connect
        self._settings = settings
        self._liveness = liveness
        self._clock = clock
        self._renew = renewer
        self._tick_seconds = tick_seconds
        self._lock = threading.Lock()
        self._held: Lease | None = None
        self._stopping = threading.Event()
        self._conn: SyncConn | None = None
        self.renewals = 0  # successful renewals, for the logs and the live tests
        self.max_loop_age = 0.0  # the longest event-loop silence a tick saw, for the DoD-3 evidence (review M4)

    def hold(self, lease: Lease) -> None:
        """Start renewing `lease`; on a loss the thread cancels the lease's effects in flight."""
        with self._lock:
            self._held = lease

    def drop(self, lease: Lease) -> None:
        """Stop renewing `lease` (its job ended or it was lost); a lease held after it is untouched."""
        with self._lock:
            if self._held is lease:
                self._held = None

    def stop(self) -> None:
        """Ask the thread to end after its current tick."""
        self._stopping.set()

    def run(self) -> None:
        """Tick until stopped, then close the connection."""
        try:
            while not self._stopping.wait(self._tick_seconds):
                try:
                    self.tick()
                except Exception:  # the one catch-all here: a dead thread would silently stop every renewal
                    log.exception("heartbeat tick failed; the next tick tries again")
        finally:
            self._close()

    def tick(self) -> None:
        """One look at the held lease: a closed gate is a loss; otherwise renew when a heartbeat is due."""
        with self._lock:
            lease = self._held
        if lease is None:
            return
        if lease.lost is not None:
            self.drop(lease)
            return
        now = self._clock()
        silence = self._liveness.age(now)
        self.max_loop_age = max(self.max_loop_age, silence)
        if silence >= self._settings.loop_stall_seconds:
            self._lose(lease, "event loop stalled")
            return
        if now - lease.held_since >= self._settings.compute_budget_seconds:
            self._lose(lease, "compute budget spent")
            return
        if now - lease.renewed_at < self._settings.heartbeat_seconds:
            return
        fence = lease.fence
        try:
            verdict = self._renew(self._connection(), lease, fence)
        except psycopg.Error:
            log.warning("renewing the lease of run %s failed; the connection is reopened next tick", lease.run_id)
            self._close()
            if now >= lease.deadline:
                self._lose(lease, "renewals failed until the local deadline")
            return
        if verdict is Renewal.RENEWED:
            lease.renewed(now)  # `now` was taken before the renewing statement (ruling 18)
            self.renewals += 1
        elif verdict is Renewal.RELEASED:
            self.drop(lease)
        elif verdict is Renewal.MOVED and lease.fence_moved_by_owner(fence):
            return  # the owner re-fenced (mark_unknown): the next tick renews under the new fence (ruling 10)
        else:
            self._lose(lease, "another owner took the lease" if verdict is Renewal.MOVED else "the lease expired")

    def _lose(self, lease: Lease, reason: str) -> None:
        if lease.mark_lost(reason):
            cancelled = lease.cancel_effects()  # effects only; a database unit in progress runs to its end
            log.warning("run %s: lease lost (%s); %d effect(s) cancelled", lease.run_id, reason, cancelled)
        self.drop(lease)

    def _connection(self) -> SyncConn:
        if self._conn is None or self._conn.closed or self._conn.broken:
            self._conn = self._connect()
        return self._conn

    def _close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except psycopg.Error:
                pass  # closing a broken connection may fail; the next tick opens a fresh one
            self._conn = None
```

Create `worker/src/ops_worker/permit.py`:

```python
"""The model permit around every model call (AM-12 SA:203-205, Plan H ruling 12): one row of `app.model_permit` per
unit of global model concurrency (one, BS:549), taken with SKIP LOCKED in its own short transaction and released in
another, so a waiting worker never holds a database transaction. A busy permit is polled with capped exponential
backoff and jitter while the caller's lease lasts. The take and the release are database units and are never
cancelled; the back-off sleep is the one effect a lost lease cancels (review round 1, I2), so the `finally` releases
exactly the slot a take returned, also when the lease is lost during the model call. A 65 s TTL (one 60 s model
attempt plus 5 s) frees a permit whose holder died. TODO(T19): SA:205's stricter release ("hold until `ollama ps`
shows idle"), once T02 has measured whether a cancelled request stops Ollama's generation.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from typing import Any

from ops_core import persistence
from ops_core.lease import Lease

PERMIT_TTL_SECONDS = 65  # SA:596: a model attempt is capped at 60 s; 5 s more for the call around it
FIRST_BACKOFF_SECONDS = 0.25
MAX_BACKOFF_SECONDS = 2.0
Sleep = Callable[[float], Coroutine[Any, Any, None]]


def backoff(attempt: int, rand: Callable[[], float] = random.random) -> float:
    """The wait after failed poll number `attempt` (from 0): 0.25 s doubling to 2 s, scaled at random into its upper
    half, so two waiting workers drift apart without a near-zero wait that would hammer the row."""
    base = min(MAX_BACKOFF_SECONDS, FIRST_BACKOFF_SECONDS * 2.0 ** min(attempt, 3))
    return base * (0.5 + 0.5 * rand())


async def _wait_for_permit(
    conn: persistence.Conn,
    *,
    holder: str,
    lease: Lease,
    sleep: Sleep,
    rand: Callable[[], float],
) -> int:
    """Poll until a permit slot is free, each try its own short transaction; LeaseLost once the lease is gone (at the
    check before a take, or by the back-off sleep, which runs as a lease effect)."""
    attempt = 0
    while True:
        lease.check()
        async with conn.transaction():
            slot = await persistence.take_model_permit(
                conn, holder=holder, run_id=lease.run_id, ttl_seconds=PERMIT_TTL_SECONDS
            )
        if slot is not None:
            return slot
        await lease.effect(sleep(backoff(attempt, rand)))
        attempt += 1


@asynccontextmanager
async def model_permit(
    conn: persistence.Conn,
    *,
    holder: str,
    lease: Lease,
    sleep: Sleep = asyncio.sleep,
    rand: Callable[[], float] = random.random,
) -> AsyncIterator[int]:
    """Hold one model permit for the block, waiting for it while the lease lasts (`lease.check()` raises LeaseLost)."""
    slot = await _wait_for_permit(conn, holder=holder, lease=lease, sleep=sleep, rand=rand)
    try:
        yield slot
    finally:
        async with conn.transaction():
            await persistence.release_model_permit(conn, slot=slot, holder=holder)
```

In `worker/src/ops_worker/drafting.py`:

Edit 1 (old lines 9-13), replace:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
```

with:

```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
```

Edit 2 (old lines 56-62), replace:

```python
class FakeDraftGenerator:
    """The deterministic route that exercises the control path without a model (BUILD_SPEC §1)."""

    async def generate(self, request: DraftRequest, evidence: list[EvidenceItem]) -> ModelDraft:
        """Draft deterministically from the first evidence item; no evidence is an error."""
        if not evidence:
            raise ValueError("a proposal draft needs at least one evidence item")
```

with:

```python
class FakeDraftGenerator:
    """The deterministic route that exercises the control path without a model (BUILD_SPEC §1). `delay_seconds` makes
    it as slow as a real model call without blocking the event loop (R088's "> 30 s fake drafter"; tests only)."""

    def __init__(self, delay_seconds: float = 0.0) -> None:
        self.delay_seconds = delay_seconds

    async def generate(self, request: DraftRequest, evidence: list[EvidenceItem]) -> ModelDraft:
        """Draft deterministically from the first evidence item; no evidence is an error."""
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if not evidence:
            raise ValueError("a proposal draft needs at least one evidence item")
```

In `worker/src/ops_worker/handlers.py` (as Task 4 left it):

Edit 1, replace:

```python
from ops_worker import proposals
from ops_worker.drafting import DraftGenerator, DraftRequest, EvidenceItem
from ops_worker.mcp import McpCaller, McpCallFailed
```

with:

```python
from ops_worker import permit, proposals
from ops_worker.drafting import DraftGenerator, DraftRequest, EvidenceItem
from ops_worker.heartbeat import Heartbeat
from ops_worker.mcp import McpCaller, McpCallFailed
```

Edit 2, replace:

```python
    """What a handler needs: the loop's connection, the MCP client, the model route, the server URLs, the worker's
    name (the lease owner) and the lease settings."""

    conn: persistence.Conn
    mcp: McpCaller
    generator: DraftGenerator
    urls: Urls
    worker_name: str
    leases: LeaseSettings = field(default_factory=LeaseSettings)
```

with:

```python
    """What a handler needs: the loop's connection, the MCP client, the model route, the server URLs, the worker's
    name (the lease owner), the lease settings and the heartbeat that renews the lease while a job runs."""

    conn: persistence.Conn
    mcp: McpCaller
    generator: DraftGenerator
    urls: Urls
    worker_name: str
    leases: LeaseSettings = field(default_factory=LeaseSettings)
    heartbeat: Heartbeat | None = None  # main.run_job hands it each claimed lease; tests may run without one
```

Edit 3, replace:

```python
    draft = await lease.effect(deps.generator.generate(request, evidence))  # a model call is an effect too (SA:195)
```

with:

```python
    async with permit.model_permit(deps.conn, holder=deps.worker_name, lease=lease):  # model concurrency 1 (BS:549)
        draft = await lease.effect(deps.generator.generate(request, evidence))  # a lease effect (SA:195)
```

In `worker/src/ops_worker/main.py` (as Task 3 wrote it):

Edit 1, replace:

```python
"""The worker process: a polling loop beside a health server, two connections (the loop's and the probe's),
SelectorEventLoop on Windows (psycopg async refuses the Proactor loop; measured in the Plan D spike).

Each poll claims the next job together with its run's lease (`persistence.claim_next`, Plan H ruling 3) and runs the
handler under that lease; a lost lease hands the job back (`handlers.abandon`, ruling 19) and the loop moves on."""
```

with:

```python
"""The worker process: a polling loop beside a health server and the lease heartbeat thread, three connections (the
loop's, the probe's and the heartbeat's synchronous one), SelectorEventLoop on Windows (psycopg async refuses the
Proactor loop; measured in the Plan D spike; the heartbeat's synchronous connection is not bound by that).

Each poll claims the next job together with its run's lease (`persistence.claim_next`, Plan H ruling 3) and runs the
handler under that lease while the heartbeat renews it; a lost lease cancels the job's effects in flight and hands the
job back (`handlers.abandon`, ruling 19) and the loop moves on."""
```

Edit 2, replace:

```python
from ops_worker.drafting import make_generator
from ops_worker.mcp import HttpMcpCaller
```

with:

```python
from ops_worker.drafting import make_generator
from ops_worker.heartbeat import Heartbeat, Liveness, connector, keep_stamping
from ops_worker.mcp import HttpMcpCaller
```

Edit 3, replace:

```python
async def run_job(deps: handlers.Deps, claimed: persistence.Claimed) -> None:
    """Run one claimed job under its lease; a lost lease hands the job back instead of failing the run (ruling 19).
    Any other exception propagates: the poll loop logs it, the job stays claimed, its lease lapses within one lease
    and the sweeper reclaims it."""
    job = dict(claimed.job)
    try:
        await handlers.handle(deps, job, claimed.lease)
    except LeaseLost:
        log.warning("job %s: run lease lost (%s); handles revoked, job handed back", job["id"], claimed.lease.lost)
        await handlers.abandon(deps, job, claimed.lease)
```

with:

```python
async def run_job(deps: handlers.Deps, claimed: persistence.Claimed) -> None:
    """Run one claimed job under its lease while the heartbeat renews it. A lost lease, raised by a fenced unit or by
    an effect the heartbeat cancelled (`Lease.effect`), hands the job back instead of failing the run (ruling 19 as
    amended in review round 1, B1: only effects are cancelled, never a database unit, so the loop connection is idle
    when `abandon` runs, and `abandon` checks that). Anything else propagates: the poll loop logs it, the job stays
    claimed, its lease lapses within one lease and the sweeper reclaims it."""
    job, lease = dict(claimed.job), claimed.lease
    if deps.heartbeat is not None:
        deps.heartbeat.hold(lease)
    try:
        await handlers.handle(deps, job, lease)
    except LeaseLost:
        log.warning("job %s: run lease lost (%s); handles revoked, job handed back", job["id"], lease.lost)
        await handlers.abandon(deps, job, lease)
    finally:
        if deps.heartbeat is not None:
            deps.heartbeat.drop(lease)
```

Edit 4, replace:

```python
    await persistence.assert_clock_profile(probe, settings.profile())
    deps = handlers.Deps(
        conn=conn,
        mcp=HttpMcpCaller(tokens),
        generator=generator,
        urls=settings.urls(),
        worker_name=f"{socket.gethostname()}:{os.getpid()}",
        leases=leases,
    )
    stop = asyncio.Event()
    polling = asyncio.create_task(run_forever(deps, stop), name="poll-loop")
```

with:

```python
    await persistence.assert_clock_profile(probe, settings.profile())
    await persistence.assert_relation(probe, "app.model_permit")  # revision 0007: the permit and the fenced functions
    liveness = Liveness()
    heartbeat = Heartbeat(connect=connector(settings.app_postgres(Role.WORKER)), settings=leases, liveness=liveness)
    deps = handlers.Deps(
        conn=conn,
        mcp=HttpMcpCaller(tokens),
        generator=generator,
        urls=settings.urls(),
        worker_name=f"{socket.gethostname()}:{os.getpid()}",
        leases=leases,
        heartbeat=heartbeat,
    )
    stop = asyncio.Event()
    stamps_stop = asyncio.Event()  # its own event: the stamps must outlive the job a shutdown lets finish
    heartbeat.start()  # idle until the first claim hands it a lease (ruling 16)
    stamping = asyncio.create_task(keep_stamping(liveness, stamps_stop), name="loop-liveness")
    polling = asyncio.create_task(run_forever(deps, stop), name="poll-loop")
```

Edit 5, replace:

```python
        await asyncio.gather(serving, polling, return_exceptions=True)
        await conn.close()
        await probe.close()
```

with:

```python
        await asyncio.gather(serving, polling, return_exceptions=True)
        # Shutdown cancels nothing: the poll loop finishes its current job first, so the liveness stamps stop only
        # now, or that job would lose its lease to "event loop stalled" (review round 2, m2).
        stamps_stop.set()
        await stamping
        heartbeat.stop()
        await asyncio.to_thread(heartbeat.join, 5.0)  # off the loop: the thread ends its tick and closes its connection
        await conn.close()
        await probe.close()
```

Run: `uv run python -m pytest tests/plan_h tests/plan_d/test_worker.py tests/plan_f/test_grant_deferred.py -q`
Expected: `100 passed` (Plan H's 92: settings 11, lock order 30, revision 8, lease 12, worker units 13, write path 2,
heartbeat 10, permit 6; Plan D's worker module 5; Plan F's grant module 3).

- [ ] **Step 3: The live DoD-3 tests**

Create `tests/e2e/test_heartbeat_live.py`:

```python
"""T13 live (OPS_LIVE=1): the heartbeat thread at the real defaults (30 s lease, 10 s heartbeat, 28 s stall gate, 90 s
budget) keeps a run's lease through a blocked event loop and through a drafter slower than the lease, and a forced
renewal failure cancels the in-flight call and revokes the job's handle (R088, DoD 3; Plan H rulings 16-20); the model
permit is held exactly around the draft call (ruling 12).

The three DoD tests carry `slow_live` (about 30, 40 and 15 s); `check.py --profile test` runs them like every other
live test. Each runs the worker's own path (`main.run_job` over `handlers.handle`) on a role-`worker` connection with a
scripted MCP caller, so no skeleton process is needed. Evidence: reports/leases/t13-heartbeat.txt.

Catches: a heartbeat that runs on the event loop (a 25 s block would starve it and lose the lease), a lease lost to a
long model call, a renewal failure that leaves the call running or its handle live, a job failed rather than handed
back on a lost lease, and a model permit held past the draft or never taken. The first test records the longest loop
silence the thread saw, so the margin to the 28 s stall gate is in the evidence (review round 1, M4).
"""

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from ops_core import persistence, settings
from ops_core.lease import RELEASED
from ops_core.settings import Role
from ops_worker import handlers, main
from ops_worker.drafting import FakeDraftGenerator
from ops_worker.heartbeat import STAMP_SECONDS, TICK_SECONDS, Heartbeat, Liveness, connector, keep_stamping

from tests.e2e.conftest import expire_lease, lease_for, purge_run, purge_tenant
from tests.e2e.test_migrations_and_persistence import new_run
from tests.e2e.test_worker_live import ScriptedMcp

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
EVIDENCE = Path("reports/leases/t13-heartbeat.txt")
EXPECTED_LINES = 4  # one per test
BLOCK_SECONDS = 25.0  # DoD 3: "Blocked event loop (25 s) does not lose the lease"
SLOW_DRAFT_SECONDS = 35.0  # R088: "> 30 s fake drafter"
WORKER = "hb-live"


@pytest.fixture(scope="module")
def lines() -> Iterator[list[str]]:
    out = [f"T13 heartbeat — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"]
    yield out
    if len(out) != 1 + EXPECTED_LINES:  # a failed or partial run leaves the committed file as it was
        return
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


def block_the_loop(seconds: float) -> None:
    """A synchronous call where an async one belongs: called from a coroutine, it blocks the event loop (DoD 3)."""
    time.sleep(seconds)


class BlockingGenerator(FakeDraftGenerator):
    """A model route that blocks the event loop itself: only a heartbeat on its own thread can keep the lease alive
    meanwhile."""

    async def generate(self, request: Any, evidence: Any) -> Any:
        block_the_loop(BLOCK_SECONDS)
        return await super().generate(request, evidence)


class HangingMcp(ScriptedMcp):
    """A read server that accepts the call and never answers, so only a cancellation can end it."""

    def __init__(self, read: persistence.Conn, write: persistence.Conn) -> None:
        super().__init__(read, write)
        self.entered = asyncio.Event()
        self.cancelled = False
        self.handle_sha256 = ""

    async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((url, tool, arguments))
        self.handle_sha256 = persistence.handle_hash(handle)  # only the hash is kept, as the server keeps it
        self.entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return {}


async def worker_deps(role_conn: RoleConn, mcp_class: type[ScriptedMcp], generator: Any) -> handlers.Deps:
    mcp = mcp_class(await role_conn(Role.MCP_READ), await role_conn(Role.MCP_EXEC))
    return handlers.Deps(
        conn=await role_conn(Role.WORKER),
        mcp=mcp,
        generator=generator,
        urls=settings.urls(),
        worker_name=WORKER,
        leases=settings.leases(),  # the real defaults: DoD 3 is about these values
    )


@asynccontextmanager
async def heartbeat_running(deps: handlers.Deps) -> AsyncIterator[Heartbeat]:
    """The heartbeat thread and the loop's liveness stamps, started the way the worker's _main starts them."""
    liveness = Liveness()
    heartbeat = Heartbeat(
        connect=connector(settings.app_postgres(Role.WORKER)), settings=deps.leases, liveness=liveness
    )
    deps.heartbeat = heartbeat
    stop = asyncio.Event()
    heartbeat.start()
    stamping = asyncio.create_task(keep_stamping(liveness, stop))
    try:
        yield heartbeat
    finally:
        stop.set()
        await stamping
        heartbeat.stop()
        await asyncio.to_thread(heartbeat.join, 5.0)


async def claim(deps: handlers.Deps, tenant: UUID) -> persistence.Claimed:
    got = await persistence.claim_next(
        deps.conn, worker_name=WORKER, tenant_ids=[tenant], lease_seconds=deps.leases.lease_seconds
    )
    assert isinstance(got, persistence.Claimed), got
    return got


async def lease_row(app_conn: persistence.Conn, run: UUID) -> dict[str, Any]:
    cur = await app_conn.execute(
        "SELECT owner, fence, lease_until = '-infinity' AS released FROM app.run_lease WHERE run_id = %s", (run,)
    )
    row = await cur.fetchone()
    assert row is not None
    return dict(row)


@pytest.mark.slow_live
async def test_r088_a_loop_blocked_for_25_seconds_keeps_its_lease(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    assert settings.leases().loop_stall_seconds > BLOCK_SECONDS  # the stall gate must outlast DoD 3's block
    tenant, _, run = await new_run(app_conn, api=await role_conn(Role.API))
    try:
        deps = await worker_deps(role_conn, ScriptedMcp, BlockingGenerator())
        claimed = await claim(deps, tenant)
        async with heartbeat_running(deps) as heartbeat:
            await main.run_job(deps, claimed)
        assert claimed.lease.lost == RELEASED and heartbeat.renewals >= 2  # at about 10 s and 20 s, mid-block
        # Not `BLOCK_SECONDS <= max_loop_age`: the thread samples the silence once per tick and the loop's last stamp
        # before the block may already be a stamp period old, so the largest silence a tick sees lies anywhere above
        # BLOCK - TICK - STAMP (review round 2, N1); the upper bound is the stall gate the lease must survive.
        lowest = BLOCK_SECONDS - TICK_SECONDS - STAMP_SECONDS
        assert lowest < heartbeat.max_loop_age < settings.leases().loop_stall_seconds
        assert (await persistence.run_row(app_conn, run))["state"] == "AWAITING_APPROVAL"
        assert await lease_row(app_conn, run) == {"owner": WORKER, "fence": claimed.lease.fence, "released": True}
        # The longest silence the thread saw goes into the evidence, so a near miss of the stall gate is visible.
        lines.append(
            f"R088 loop blocked {BLOCK_SECONDS:.0f} s: {heartbeat.renewals} renewals, longest loop silence"
            f" {heartbeat.max_loop_age:.1f} s of {settings.leases().loop_stall_seconds} s, fence kept, run drafted"
        )
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


@pytest.mark.slow_live
async def test_r088_a_drafter_slower_than_the_lease_keeps_its_lease(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    tenant, _, run = await new_run(app_conn, api=await role_conn(Role.API))
    try:
        deps = await worker_deps(role_conn, ScriptedMcp, FakeDraftGenerator(delay_seconds=SLOW_DRAFT_SECONDS))
        claimed = await claim(deps, tenant)
        async with heartbeat_running(deps) as heartbeat:
            await main.run_job(deps, claimed)
        assert claimed.lease.lost == RELEASED and heartbeat.renewals >= 3  # a 35 s draft under a 30 s lease
        assert (await persistence.run_row(app_conn, run))["state"] == "AWAITING_APPROVAL"
        assert await lease_row(app_conn, run) == {"owner": WORKER, "fence": claimed.lease.fence, "released": True}
        lines.append(f"R088 {SLOW_DRAFT_SECONDS:.0f} s drafter: {heartbeat.renewals} renewals, fence kept, run drafted")
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


@pytest.mark.slow_live
async def test_r088_a_forced_renewal_failure_cancels_the_call_and_revokes_the_handle(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    tenant, _, run = await new_run(app_conn, api=await role_conn(Role.API))
    try:
        deps = await worker_deps(role_conn, HangingMcp, FakeDraftGenerator())
        mcp: Any = deps.mcp
        thief = await role_conn(Role.WORKER)
        claimed = await claim(deps, tenant)
        async with heartbeat_running(deps):
            job = asyncio.create_task(main.run_job(deps, claimed))
            await asyncio.wait_for(mcp.entered.wait(), timeout=10)
            # Force the renewal to fail: the lease lapses on the database clock and a second worker takes the run.
            await expire_lease(app_conn, run)
            taken = await lease_for(thief, run, owner="hb-thief")
            started = time.monotonic()
            await asyncio.wait_for(job, timeout=deps.leases.heartbeat_seconds + 5)
            noticed = time.monotonic() - started
        assert mcp.cancelled and taken.fence == claimed.lease.fence + 1
        # The thief's acquisition usually lands first; a renewal between the expiry and it sees the lapse instead.
        assert claimed.lease.lost in ("another owner took the lease", "the lease expired")
        cur = await app_conn.execute(
            "SELECT revoked_at IS NOT NULL AS revoked FROM app.invocation_context WHERE handle_sha256 = %s",
            (mcp.handle_sha256,),
        )
        assert (await cur.fetchone())["revoked"]  # revoked by the lost owner under its old fence (ruling 8)
        cur = await app_conn.execute("SELECT claimed_by, done_at FROM app.jobs WHERE id = %s", (claimed.job["id"],))
        row = await cur.fetchone()
        assert row is not None and (row["claimed_by"], row["done_at"]) == (None, None)  # handed back (ruling 19)
        assert (await persistence.run_row(app_conn, run))["state"] == "RETRIEVING"  # no transition
        # The handed-back job runs again (review round 3, I1): its next owner finds the run interrupted and fails it.
        await expire_lease(app_conn, run)  # the thief is done with the run
        await main.run_job(deps, await claim(deps, tenant))
        assert (await persistence.run_row(app_conn, run))["state"] == "FAILED"
        lines.append(
            f"R088 forced renewal failure: call cancelled {noticed:.1f} s after the takeover, handle revoked;"
            " the re-run failed the interrupted run"
        )
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


async def test_the_model_permit_is_held_for_the_draft_and_released(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    seen: dict[str, Any] = {}
    other = await role_conn(Role.WORKER)
    tenant, _, run = await new_run(app_conn, api=await role_conn(Role.API))

    class PeekingGenerator(FakeDraftGenerator):
        async def generate(self, request: Any, evidence: Any) -> Any:
            cur = await app_conn.execute(
                "SELECT holder, run_id, leased_until > app.current_time() AS held FROM app.model_permit WHERE slot = 1"
            )
            seen.update(dict(await cur.fetchone()))
            async with other.transaction():
                seen["second"] = await persistence.take_model_permit(
                    other, holder="someone-else", run_id=run, ttl_seconds=65
                )
            return await super().generate(request, evidence)

    try:
        deps = await worker_deps(role_conn, ScriptedMcp, PeekingGenerator())
        await main.run_job(deps, await claim(deps, tenant))
        assert seen == {"holder": WORKER, "run_id": run, "held": True, "second": None}  # BS:549: one at a time
        cur = await app_conn.execute(
            "SELECT holder, leased_until = '-infinity' AS free FROM app.model_permit WHERE slot = 1"
        )
        assert dict(await cur.fetchone()) == {"holder": None, "free": True}
        lines.append("model permit: held by the drafting worker for the call, refused to a second taker, released")
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)
```

Run (dev stack up, no skeleton process running; about two minutes):

```bash
OPS_LIVE=1 PROFILE=test PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_heartbeat_live.py \
  tests/e2e/test_worker_live.py tests/e2e/test_leases_live.py -q
```

Expected: `18 passed` (4 new, worker 4, leases 10); `reports/leases/t13-heartbeat.txt` holds the header and four
lines. While iterating, `-m "not slow_live"` leaves the three DoD tests out (`3 deselected`); the gate never does.

- [ ] **Step 4: Gates and commit**

Format, lint and count characters on every file of this task.

Run: `PYTHONUTF8=1 uv run python scripts/check.py`
Expected: `CHECK: GREEN`; pytest `909 passed, 128 skipped` (890 + 10 + 6 + 3; the 4 new live tests skip).

Run: `PYTHONUTF8=1 uv run python scripts/check.py --profile test`
Expected: `CHECK: GREEN`; pytest `1016 passed, 21 skipped` (R105's skeleton worker now runs the heartbeat thread; the
live gate takes about 95 s longer than before this task). Then
`git checkout -- reports/bootstrap reports/skeleton reports/auth reports/admission`.

Run: `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`
Expected: exit 0.

```bash
git add core/src/ops_core/lease.py core/src/ops_core/persistence.py worker/src/ops_worker
git add tests/plan_h/test_heartbeat.py tests/plan_h/test_permit.py tests/plan_h/test_worker_units.py
git add tests/e2e/test_heartbeat_live.py
git commit -m "feat(worker): heartbeat thread with liveness and budget gates, cancel on loss, model permit (T13)"
```

---

### Task 6: The sweeper's reclaim, the stress test, R019 end to end, and the global queue bound

**Files:**
- Create: `sweeper/src/ops_sweeper/leases.py`, `tests/plan_h/test_reclaim.py`, `tests/plan_h/test_global_queue.py`,
  `tests/e2e/test_lease_stress_live.py`
- Modify: `sweeper/src/ops_sweeper/main.py:8-10` (docstring), `:37` (import), `:111-117` (`tick`);
  `core/src/ops_core/persistence.py` (`queued_runs_total` after `queued_count`); `api/src/ops_api/idempotency.py:49-50`
  (`QueueFull`); `api/src/ops_api/store.py:268-270` (`Unit`), `:386-388` and `:423-424` (`admit_message`), `:671-673`
  (the `Store` protocol), `:818-820` (`DbUnit`), `:922` (the lock_timeout TODO); `api/src/ops_api/app.py` (the 0007
  guard, the 429 handler, the messages route); `tests/plan_g/fakes.py:111-113` (`FakeUnit`), `:278`;
  `tests/e2e/test_admission_live.py:55` and a new test

**Requirements:** R019 (leases expire and are recovered safely), R107 (stress: no deadlock; database-clock expiry),
DoD 2, BS:550's global bound; brief rulings 11, 13, 14, 21, 25.

**Interfaces:**
- Consumes: `persistence.claim_next`, `acquire_lease(..., wait=True)`, `fenced`, `mint_handle`, `revoke_handles`,
  `mark_unknown`, `release_lease` (Tasks 3-4); `lease.renew`, `Renewal` (Task 5); `app.queued_runs_total()` (Task 2);
  `AdmissionSettings.global_queue_limit` (Task 1).
- Produces: `ops_sweeper.leases.reclaim(conn) -> list[UUID]`; `persistence.queued_runs_total(conn) -> int`;
  `idempotency.QueueFull(message: str = "tenant queue is full")` with `.message`; `Unit.queued_total() -> int`;
  `AdmissionStore.admit_message(..., quota: int, queue_limit: int = 100)` (and the `Store` protocol's); `FakeUnit.
  queued_total()`.

- [ ] **Step 1: Write the failing unit tests**

Create `tests/plan_h/test_reclaim.py`:

```python
"""The sweeper's lease reclaim (Plan H ruling 11, erratum 49), without a database: what the statement hands back and
that every tick runs it.

Catches: a reclaim that touches finished jobs, unclaimed jobs or the sweeper's own maintenance rows (no run), one that
compares the lease on anything but the application clock, and a tick that skips the reclaim when Keycloak is down
(a dead worker's run would then stay claimed for as long as the identity provider is out).
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest
from ops_sweeper import leases, main, sync


class FakeCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class FakeConn:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.statements: list[str] = []
        self.in_transaction = False

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        self.in_transaction = True
        yield
        self.in_transaction = False

    async def execute(self, statement: str, params: Any = None) -> FakeCursor:
        assert self.in_transaction
        self.statements.append(statement)
        return FakeCursor(self.rows)


def test_the_reclaim_hands_back_only_claimed_unfinished_run_jobs_of_dead_leases() -> None:
    job = uuid4()
    conn: Any = FakeConn([{"id": job}])
    assert asyncio.run(leases.reclaim(conn)) == [job]
    (statement,) = conn.statements
    assert statement.startswith("UPDATE app.jobs j SET claimed_by = NULL, claimed_at = NULL")
    for condition in (
        "j.done_at IS NULL",
        "j.claimed_at IS NOT NULL",
        "j.run_id IS NOT NULL",  # maintenance rows carry no run and are never reclaimed
        "NOT EXISTS (SELECT 1 FROM app.run_lease l WHERE l.run_id = j.run_id AND l.lease_until > app.current_time())",
    ):
        assert condition in statement, condition
    assert "available_at" not in statement  # the sweeper holds no UPDATE on it; the job is due already


def test_the_tick_reclaims_even_when_the_sync_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def failed_sync(_deps: Any) -> bool:
        calls.append("sync")
        return False

    async def purge(_conn: Any) -> dict[str, int]:
        calls.append("purge")
        return {}

    async def reclaim(_conn: Any) -> list[Any]:
        calls.append("reclaim")
        return [uuid4()]

    monkeypatch.setattr(main, "run_sync", failed_sync)
    monkeypatch.setattr(sync, "purge_expired", purge)
    monkeypatch.setattr(leases, "reclaim", reclaim)
    none: Any = None
    deps = main.Deps(conn=none, admin=none, issuer="iss", tick_seconds=30.0, worker_name="sweeper:test")
    asyncio.run(main.tick(deps))
    assert calls == ["sync", "purge", "reclaim"]
```

Create `tests/plan_h/test_global_queue.py`:

```python
"""The global queue bound (Plan H ruling 13, BS:550 "100 total", erratum 51), without a database: counted across
tenants after the tenant's quota and only for a verdict that would start a run, refused as the same unrecorded 429.

Catches: a bound that counts one tenant only (the api role's RLS view), a status question or a clarification refused
for a full queue, a recorded 429 (a retry after the queue drained would replay it), and a refusal that hides which
bound was hit.
"""

import asyncio
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from ops_api.app import create_app
from ops_api.idempotency import QueueFull, Verdict
from ops_core.contracts import MessageRequest, load
from ops_core.settings import AdmissionSettings

from tests.plan_f.auth_fakes import fake_auth
from tests.plan_g.fakes import ALEX, ALPHA, BETA, FakeStore, StubVerifier
from tests.plan_g.test_store_units import MESSAGES, SAMPLE, conversation, idem


def admit(fake: FakeStore, key: str, *, queue_limit: int, body: dict[str, Any] = SAMPLE) -> Verdict:
    cid = conversation(fake)
    request = load(MessageRequest, json.dumps(body))
    return asyncio.run(
        fake.admit_message(
            idem=idem(MESSAGES, key, {"conversation_id": str(cid)}, request.model_dump(mode="json")),
            tenant_id=ALPHA,
            conversation_id=cid,
            requester=ALEX,
            request=request,
            quota=100,
            queue_limit=queue_limit,
        )
    )


def foreign_queued_run(fake: FakeStore) -> None:
    """A QUEUED run of another tenant: invisible to ALPHA's quota, counted by the global bound."""
    admit(fake, f"foreign-{len(fake.runs)}", queue_limit=1000)
    newest = list(fake.runs.values())[-1]
    newest["tenant_id"] = BETA


def test_the_global_bound_refuses_after_the_tenant_quota_passes() -> None:
    fake = FakeStore()
    foreign_queued_run(fake)
    foreign_queued_run(fake)
    with pytest.raises(QueueFull) as full:
        admit(fake, "key-global-01", queue_limit=2)
    assert full.value.message == "the work queue is full" and len(fake.runs) == 2  # nothing written, nothing recorded
    assert admit(fake, "key-global-02", queue_limit=3).status == 202


def test_a_status_question_or_a_clarification_never_counts_the_global_queue() -> None:
    fake = FakeStore()
    foreign_queued_run(fake)
    counted = fake.counts
    status = admit(fake, "key-status-01", queue_limit=1, body={"kind": "status", "text": "Anything running?"})
    assert status.status == 200
    asked = admit(fake, "key-ask-01", queue_limit=1, body={"kind": "investigate", "text": "Look into it."})
    assert asked.status == 200 and asked.body["status"] == "clarification_needed" and fake.counts == counted


def test_the_global_refusal_is_an_unrecorded_429_with_retry_after() -> None:
    fake = FakeStore()
    foreign_queued_run(fake)
    app = create_app(
        StubVerifier(),
        store_factory=lambda: fake,
        auth_factory=fake_auth,
        admission=AdmissionSettings(global_queue_limit=1),
    )
    headers = {"Authorization": "Bearer alex", "Idempotency-Key": "key-global-http-01"}
    with TestClient(app) as c:
        cid = c.post("/api/v1/conversations", headers={**headers, "Idempotency-Key": "key-conv-01"}).json()[
            "conversation_id"
        ]
        records = len(fake.records)
        full = c.post(f"/api/v1/conversations/{cid}/messages", headers=headers, json=SAMPLE)
        body = full.json()
        assert full.status_code == 429 and full.headers["Retry-After"] == "5"
        assert (body["code"], body["message"], body["retryable"]) == ("RATE_LIMITED", "the work queue is full", True)
        assert len(fake.records) == records  # never recorded (Plan G ruling 5)
        fake.runs.clear()  # the queue drains
        again = c.post(f"/api/v1/conversations/{cid}/messages", headers=headers, json=SAMPLE)
        assert again.status_code == 202  # the same key is admitted now
```

Run: `uv run python -m pytest tests/plan_h/test_reclaim.py -q`
Expected: `1 error in` (`ImportError: cannot import name 'leases' from 'ops_sweeper'`; pytest stops at the collection
error, so the queue tests run on their own below).

Run: `uv run python -m pytest tests/plan_h/test_global_queue.py -q`
Expected: `3 failed`, each with `TypeError: AdmissionStore.admit_message() got an unexpected keyword argument
'queue_limit'`.

- [ ] **Step 2: The reclaim, the count and the bound**

Create `sweeper/src/ops_sweeper/leases.py`:

```python
"""Lease reclaim (AM-12; SA:471 as erratum 49 reads it; Plan H ruling 11): the sweeper's routine with its own direct
grants (`sweeper_all` on `jobs`, SELECT on `run_lease`), not a definer function, like `sync_memberships` (erratum 26).

A claim and its lease commit together (ruling 3), and a job's final unit finishes it and releases the lease together
(ruling 28), so a run job that is claimed, not done, and whose run lease is not live belongs to a worker that died or
lost its lease. Reclaim hands such jobs back (`claimed_by`, `claimed_at` cleared; `available_at` is already past), the
next poll claims them and takes the run's lease at the next fence, and whoever claims one re-reads the run (jobs are
wake-ups; an investigate job whose run it finds RETRIEVING or DRAFTING fails that run as interrupted, review round
3). Nothing else: no `recover` job (T22), no model permit work (an expired permit is free by the same comparison), no
lost wake-ups (T14).
"""

from __future__ import annotations

from uuid import UUID

from ops_core import persistence


async def reclaim(conn: persistence.Conn) -> list[UUID]:
    """Hand back every claimed, unfinished run job whose run lease is not live; the ids handed back.

    The lease is read without a lock (the sweeper takes none, erratum 49). A lease renewed just after the read can only
    make a live owner's job claimable again, and a second claimer then meets the live lease and defers (ruling 3)
    while the owner's fenced units keep working: the lease, not the claim, is the authority.
    """
    async with conn.transaction():
        cur = await conn.execute(
            "UPDATE app.jobs j SET claimed_by = NULL, claimed_at = NULL"
            " WHERE j.done_at IS NULL AND j.claimed_at IS NOT NULL AND j.run_id IS NOT NULL"
            " AND NOT EXISTS (SELECT 1 FROM app.run_lease l WHERE l.run_id = j.run_id"
            " AND l.lease_until > app.current_time()) RETURNING j.id"
        )
        return [UUID(str(row["id"])) for row in await cur.fetchall()]
```

In `sweeper/src/ops_sweeper/main.py`:

Edit 1 (old lines 8-10), replace:

```python
60 s holds with margin). The same tick purges expired rows. Readiness is 200 only while the last successful
sync is younger than 120 s, the window after which `grant_execution` refuses (T11 review note 2), so
`scripts/skeleton.py up` waits for the first sync. TODO(T13/T14/T21): leases, wake-ups, outbox, proposal expiry.
```

with:

```python
60 s holds with margin). The same tick purges expired rows and hands back the jobs whose run lease died with their
worker (T13, `leases.reclaim`). Readiness is 200 only while the last successful sync is younger than 120 s, the
window after which `grant_execution` refuses (T11 review note 2), so `scripts/skeleton.py up` waits for the first
sync. TODO(T14/T21): wake-ups, the outbox, proposal expiry.
```

Edit 2 (old line 37), replace:

```python
from ops_sweeper import sync
```

with:

```python
from ops_sweeper import leases, sync
```

Edit 3 (old lines 111-117), replace:

```python
async def tick(deps: Deps) -> None:
    """Sync; if it succeeded, record this minute's maintenance job (insert, claim, finish); purge expired rows."""
    if await run_sync(deps):
        await record_sync(deps)
    counts = await sync.purge_expired(deps.conn)
    if any(counts.values()):
        log.info("purged expired rows: %s", counts)
```

with:

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
```

In `core/src/ops_core/persistence.py`, insert after `queued_count`:

```python
async def queued_runs_total(conn: Conn) -> int:
    """QUEUED runs of every tenant through `app.queued_runs_total()` (api only, Plan H ruling 13): one number."""
    row = await _call(conn, "SELECT app.queued_runs_total() AS n", ())
    return 0 if row is None else int(row["n"])
```

In `api/src/ops_api/idempotency.py` (old lines 49-50), replace:

```python
class QueueFull(Exception):
    """The tenant's queue is at its quota (ruling 18): transient, so the unit rolls back and nothing is recorded."""
```

with:

```python
class QueueFull(Exception):
    """A queue bound is reached, the tenant's quota (Plan G ruling 18) or the global bound (Plan H ruling 13):
    transient, so the unit rolls back and nothing is recorded; `message` is what the 429 says."""

    def __init__(self, message: str = "tenant queue is full") -> None:
        super().__init__(message)
        self.message = message
```

In `api/src/ops_api/store.py`:

Edit 1 (old lines 268-270), replace:

```python
    async def queued_count(self) -> int:
        """QUEUED runs of the tenant (ruling 18)."""
        ...
```

with:

```python
    async def queued_count(self) -> int:
        """QUEUED runs of the tenant (ruling 18)."""
        ...

    async def queued_total(self) -> int:
        """QUEUED runs of every tenant, one number (`queued_runs_total`, Plan H ruling 13)."""
        ...
```

Edit 2 (old lines 386-388), replace:

```python
        quota: int,
    ) -> Verdict:
        """The messages route's unit in ruling 21's order: conversation, active run, router, quota count, effect."""
```

with:

```python
        quota: int,
        queue_limit: int = 100,
    ) -> Verdict:
        """The messages route's unit in ruling 21's order: conversation, active run, router, the tenant's quota count
        and the global count (Plan H ruling 13; 100 is BS:550's starting value, the route passes the setting),
        effect."""
```

Edit 3 (old lines 423-424), replace:

```python
            if await unit.queued_count() >= quota:
                raise QueueFull
```

with:

```python
            if await unit.queued_count() >= quota:
                raise QueueFull
            # Plan H ruling 13: the global bound (BS:550 "100 total") after the tenant's quota, through the definer
            # that counts every tenant. Counted, then created: admissions in different tenants can each pass a count
            # of limit - 1, so the bound is soft by the number of concurrent admissions (the runbook says so; T29).
            if await unit.queued_total() >= queue_limit:
                raise QueueFull("the work queue is full")
```

Edit 4 (old lines 671-673, the `Store` protocol), replace:

```python
        quota: int,
    ) -> Verdict:
        """Route and commit one message (idempotent)."""
```

with:

```python
        quota: int,
        queue_limit: int = 100,
    ) -> Verdict:
        """Route and commit one message (idempotent)."""
```

Edit 5 (old lines 818-820), replace:

```python
    async def queued_count(self) -> int:
        """QUEUED runs of the tenant (ruling 18)."""
        return await persistence.queued_count(self.conn)
```

with:

```python
    async def queued_count(self) -> int:
        """QUEUED runs of the tenant (ruling 18)."""
        return await persistence.queued_count(self.conn)

    async def queued_total(self) -> int:
        """QUEUED runs of every tenant (Plan H ruling 13)."""
        return await persistence.queued_runs_total(self.conn)
```

Edit 6 (old line 922), replace:

```python
        # TODO(T13): keep a per-unit lock_timeout once the connection pool lands.
```

with:

```python
        # TODO(T30): keep a per-unit lock_timeout once the connection pool lands (Plan H ruling 25).
```

In `api/src/ops_api/app.py`:

Edit 1, replace:

```python
                # Revision 0006: admission writes the record table and the message columns it adds.
                await persistence.assert_relation(app.state.store.session.conn, "app.idempotency_request")
```

with:

```python
                # Revision 0007: admission counts the global queue through queued_runs_total (0006's record table and
                # message columns come before it); the permit table marks the revision.
                await persistence.assert_relation(app.state.store.session.conn, "app.model_permit")
```

Edit 2, replace:

```python
        except QueueFull:
            return limits.safe_response(
                limits.request_id_of(request.scope),
                429,
                ErrorCode.RATE_LIMITED,
                "tenant queue is full",
```

with:

```python
        except QueueFull as exc:
            return limits.safe_response(
                limits.request_id_of(request.scope),
                429,
                ErrorCode.RATE_LIMITED,
                exc.message,  # which bound: the tenant's quota or the global queue (Plan H ruling 13)
```

Edit 3, replace:

```python
        conversation, 422 for an unroutable kind, 429 for a full tenant queue (ruling 21's order)."""
```

with:

```python
        conversation, 422 for an unroutable kind, 429 for a full tenant or global queue (ruling 21's order)."""
```

Edit 4, replace:

```python
                quota=bounds.tenant_queue_quota,
            ),
```

with:

```python
                quota=bounds.tenant_queue_quota,
                queue_limit=bounds.global_queue_limit,
            ),
```

In `tests/plan_g/fakes.py`:

Edit 1 (old lines 111-113), replace:

```python
    async def queued_count(self) -> int:
        self.fake.counts += 1
        return sum(1 for r in self.fake.runs.values() if r["tenant_id"] == self.tenant_id and r["state"] == "QUEUED")
```

with:

```python
    async def queued_count(self) -> int:
        self.fake.counts += 1
        return sum(1 for r in self.fake.runs.values() if r["tenant_id"] == self.tenant_id and r["state"] == "QUEUED")

    async def queued_total(self) -> int:
        self.fake.counts += 1
        return sum(1 for r in self.fake.runs.values() if r["state"] == "QUEUED")  # every tenant (Plan H ruling 13)
```

Edit 2 (old line 278), replace:

```python
        self.counts = 0  # how many times a unit read the tenant's queued count
```

with:

```python
        self.counts = 0  # how many times a unit read a queued count (the tenant's or the global one)
```

Run: `uv run python -m pytest tests/plan_h/test_reclaim.py tests/plan_h/test_global_queue.py tests/plan_g tests/plan_f/test_sweeper.py -q`
Expected: `149 passed` (the new 2 and 3; Plan G's 135, Plan F's sweeper module 9).

- [ ] **Step 3: The stress test and R019 end to end**

Create `tests/e2e/test_lease_stress_live.py`:

```python
"""T13 live (OPS_LIVE=1): eight `worker` connections and the sweeper hammer three runs for twenty seconds with every
lease operation the system has, under the published lock order (DoD 2, R107), and R019 end to end: a killed owner's
job is reclaimed once its lease has expired on the database clock, and the next owner takes it at a higher fence
(Plan H rulings 11, 14, 21).

The stress mix, one random operation on one random run per step: a claim (`claim_next`: SKIP LOCKED, NOWAIT, defer),
a waiting acquisition (`acquire_lease(wait=True)`: the form that would deadlock if the order were wrong; its lock
waits surface as 55P03, never as a busy lease), a renewal (the heartbeat's synchronous unit, on each actor's own
synchronous connection), a fenced event, a mint, a revoke, and a `mark_unknown` re-fence. Two of the three runs are
QUEUED, where `mark_unknown` is refused after it has taken its locks (the locks are the point); the third is EXECUTING
with a grant, so a re-fence commits under load and its holder hands the new fence to its Lease (review round 1, I4).
The sweeper reclaims every 0.2 s, and a monitor samples every 50 ms: fences only increase, and at most one actor's
own Lease of a run passes its local check (not lost, before its local deadline), that actor being the owner of the
run's live row at its fence (SA:195's 5 s margin is what makes this hold; the R019 test resets the test clock, so the
database clock and the monotonic clock agree here). Every connection runs with `lock_timeout = 10s`, so a wait that
never ends shows up as SQLSTATE 55P03. Evidence: reports/leases/t13-stress.txt.

Catches: a deadlock (40P01) or a lock wait past 10 s (55P03) anywhere in the mix, a fence that goes backwards or is
handed out twice, two actors that both believe they hold a run's lease (or one whose belief the database does not
share), a stale writer whose event lands after a newer fence's event, a reclaim that takes a live owner's job, and an
expiry decided by anything but the database clock.
"""

import asyncio
import random
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from ops_core import persistence, settings
from ops_core.jobs import Server
from ops_core.lease import Busy, Lease, LeaseLost, Renewal, renew
from ops_core.outcomes import EventType
from ops_core.settings import Role
from ops_sweeper import leases
from psycopg.rows import dict_row

from tests.e2e.conftest import expire_lease, purge_run, purge_tenant
from tests.e2e.test_mcp_write_live import approved_run
from tests.e2e.test_migrations_and_persistence import new_run

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
EVIDENCE = Path("reports/leases/t13-stress.txt")
EXPECTED_LINES = 3  # one per test
STRESS_SECONDS = 20.0
ACTORS = 8
RUNS = 3  # two QUEUED, one EXECUTING
OPS = ("claim", "acquire", "renew", "write", "mint", "revoke", "bump")


@pytest.fixture(scope="module")
def lines() -> Iterator[list[str]]:
    out = [f"T13 stress and reclaim — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"]
    yield out
    if len(out) != 1 + EXPECTED_LINES:  # a failed or partial run leaves the committed file as it was
        return
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


async def patient(conn: persistence.Conn) -> persistence.Conn:
    """A connection whose lock waits end after 10 s with 55P03 instead of never (the deadlock detector would still
    report a real cycle first, after its 1 s deadlock_timeout)."""
    await conn.execute("SET lock_timeout = '10s'")
    return conn


class Actor:
    """One worker connection pair doing random lease work on the shared runs, tallying what happened."""

    def __init__(self, name: str, conn: persistence.Conn, sync_conn: Any, tenant: UUID, jobs: dict[UUID, UUID]) -> None:
        self.name = name
        self.conn = conn
        self.sync_conn = sync_conn
        self.tenant = tenant
        self.jobs = jobs
        self.rng = random.Random(name)
        self.held: dict[UUID, Lease] = {}

    async def step(self, tally: Counter[str], acquired: dict[UUID, list[int]]) -> None:
        run = self.rng.choice(list(self.jobs))
        op = self.rng.choice(OPS)
        lease = self.held.get(run)
        try:
            if op == "claim":
                got = await persistence.claim_next(
                    self.conn, worker_name=self.name, tenant_ids=[self.tenant], lease_seconds=8
                )
                if isinstance(got, persistence.Claimed):
                    self.held[got.lease.run_id] = got.lease
                    acquired.setdefault(got.lease.run_id, []).append(got.lease.fence)
            elif op == "acquire" or lease is None:
                async with self.conn.transaction():
                    taken = await persistence.acquire_lease(
                        self.conn, run_id=run, owner=self.name, lease_seconds=self.rng.choice((6, 8, 10)), wait=True
                    )
                if not isinstance(taken, Busy):  # a waiting acquisition's 55P03 is raised and counted below
                    self.held[run] = taken
                    acquired.setdefault(run, []).append(taken.fence)
                op = "acquire"
            elif op == "renew":
                started = time.monotonic()
                verdict = await asyncio.to_thread(renew, self.sync_conn, lease, lease.fence)
                if verdict is Renewal.RENEWED:
                    lease.renewed(started)
                else:
                    self.held.pop(run, None)
            elif op == "write":
                async with self.conn.transaction():
                    await persistence.fenced(self.conn, lease)
                    await persistence.append_event(
                        self.conn, run_id=run, type=EventType.TOOL_STARTED, payload={"message": f"fence {lease.fence}"}
                    )
            elif op == "mint":
                async with self.conn.transaction():
                    await persistence.fenced(self.conn, lease)
                    await persistence.mint_handle(
                        self.conn,
                        run_id=run,
                        job_id=self.jobs[run],
                        server=Server.READ,
                        azp="ops-worker",
                        fence=lease.fence,
                    )
            elif op == "revoke":
                async with self.conn.transaction():
                    await persistence.revoke_handles(self.conn, run, lease.fence)
            else:
                lease.begin_refence()  # as the worker brackets its re-fence (ruling 10)
                try:
                    async with self.conn.transaction():
                        unknown = await persistence.mark_unknown(self.conn, run, lease.fence)
                except BaseException:
                    lease.end_refence(None)
                    raise
                lease.end_refence(unknown.fence)
                acquired.setdefault(run, []).append(unknown.fence)
                tally["bumped"] += 1
            tally[op] += 1
        except LeaseLost:
            self.held.pop(run, None)
            tally["lost"] += 1
        except persistence.VersionConflict:
            tally["refused"] += 1  # mark_unknown on a QUEUED run, or a stale fence: rolled back, locks released
        except psycopg.errors.DeadlockDetected:
            tally["40P01"] += 1
        except psycopg.errors.LockNotAvailable:
            tally["55P03"] += 1


@pytest.mark.slow_live
async def test_r107_eight_workers_and_the_sweeper_never_deadlock_and_fences_never_go_back(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    api, seeder, mcp_exec = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.MCP_EXEC)
    tenant, _, first = await new_run(app_conn, api=api)
    runs = [first, (await new_run(app_conn, tenant, api=api))[2]]
    sync_conns: list[Any] = []
    try:
        # The EXECUTING run: approved and granted through the definers (on the seeded tenant), then its seeding lease
        # expired, so the actors compete for it from the next fence.
        _, executing, proposal, handle = await approved_run(app_conn, api=api, worker=seeder)
        runs.append(executing)
        async with mcp_exec.transaction():
            await persistence.grant_execution(mcp_exec, handle=handle, proposal_id=proposal)
        await expire_lease(app_conn, executing)
        cur = await app_conn.execute("SELECT run_id, id FROM app.jobs WHERE run_id = ANY(%s)", (runs,))
        jobs = {UUID(str(row["run_id"])): UUID(str(row["id"])) for row in await cur.fetchall()}
        conninfo = settings.app_postgres(Role.WORKER).conninfo()
        actors = []
        for index in range(ACTORS):
            sync_conn = psycopg.connect(conninfo, autocommit=True, row_factory=dict_row)
            sync_conn.execute("SET lock_timeout = '10s'")
            sync_conns.append(sync_conn)
            conn = await patient(await role_conn(Role.WORKER))
            actors.append(Actor(f"stress-{index}", conn, sync_conn, tenant, jobs))
        sweeper = await patient(await role_conn(Role.SWEEPER))
        tally: Counter[str] = Counter()
        acquired: dict[UUID, list[int]] = {}
        seen: dict[UUID, list[int]] = {run: [] for run in runs}
        two_owners: list[str] = []
        deadline = time.monotonic() + STRESS_SECONDS

        async def act(actor: Actor) -> None:
            while time.monotonic() < deadline:
                await actor.step(tally, acquired)
                await asyncio.sleep(0)

        async def reclaim() -> None:
            while time.monotonic() < deadline:
                try:
                    await leases.reclaim(sweeper)
                    tally["reclaim"] += 1
                except psycopg.errors.DeadlockDetected:
                    tally["40P01"] += 1
                except psycopg.errors.LockNotAvailable:
                    tally["55P03"] += 1
                await asyncio.sleep(0.2)

        def believers(run: UUID) -> list[tuple[str, int, bool]]:
            """The actors whose own Lease of `run` passes its local check now: the fence each believes it holds, and
            whether it is between `begin_refence` and `end_refence` (its own bump may commit before the row is read)."""
            now = time.monotonic()
            return [
                (a.name, held.fence, held.refencing)
                for a in actors
                if (held := a.held.get(run)) is not None and held.lost is None and now < held.deadline
            ]

        async def monitor() -> None:
            """Ruling 21's observation (review round 2, N3): at each sample, at most one actor believes it holds a run's
            lease, and the row read right after says it does: that actor owns the row, the row is live, and its fence
            is the believed one, or one more only for an actor that was mid-re-fence at the sample (review round 3: a
            bump that never reached the Lease would otherwise pass)."""
            while time.monotonic() < deadline:
                beliefs = {run: believers(run) for run in runs}  # taken first: the row read below can only be newer
                cur = await app_conn.execute(
                    "SELECT run_id, owner, fence, lease_until > app.current_time() AS live FROM app.run_lease"
                    " WHERE run_id = ANY(%s)",
                    (runs,),
                )
                for row in await cur.fetchall():
                    run, fence = UUID(str(row["run_id"])), int(row["fence"])
                    seen[run].append(fence)
                    believed = beliefs[run]
                    if len(believed) > 1:
                        two_owners.append(f"{run}: {believed} all believe they hold it")
                    elif believed:
                        name, held_fence, refencing = believed[0]
                        allowed = (held_fence, held_fence + 1) if refencing else (held_fence,)
                        if not (row["live"] and row["owner"] == name and fence in allowed):
                            two_owners.append(f"{run}: {name} at fence {held_fence} vs row {row['owner']} at {fence}")
                await asyncio.sleep(0.05)

        await asyncio.gather(*(act(actor) for actor in actors), reclaim(), monitor())

        assert tally["40P01"] == 0 and tally["55P03"] == 0, dict(tally)  # DoD 2: no deadlock, no endless wait
        assert sum(tally[op] for op in OPS) >= 200, dict(tally)  # it really ran
        assert tally["bumped"] >= 1, dict(tally)  # a re-fence committed under load (review round 1, I4)
        assert two_owners == [], two_owners[:5]
        for run in runs:
            fences = acquired.get(run, [])
            assert len(fences) == len(set(fences)), run  # no fence handed out twice
            assert seen[run] == sorted(seen[run]), run  # never backwards
            cur = await app_conn.execute(
                "SELECT payload->>'message' AS m FROM app.events WHERE run_id = %s AND type = 'tool.started'"
                " ORDER BY sequence",
                (run,),
            )
            written = [int(row["m"].split()[1]) for row in await cur.fetchall()]
            assert written == sorted(written), run  # no stale writer landed after a newer fence (DoD 1, under load)
        top = max(max(fences) for fences in acquired.values())
        lines.append(
            f"R107 stress {ACTORS} workers x {STRESS_SECONDS:.0f} s on {RUNS} runs: {sum(tally.values())} operations,"
            f" 40P01=0, 55P03=0, highest fence {top}, re-fences {tally['bumped']}, refused {tally['refused']},"
            f" lost {tally['lost']}; at every sample at most one actor believed it held a run, the live owner"
        )
    finally:
        for sync_conn in sync_conns:
            sync_conn.close()
        for run in runs:
            await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


async def test_r019_a_killed_owners_job_is_reclaimed_and_the_next_owner_fences_higher(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    tenant, _, run = await new_run(app_conn, api=await role_conn(Role.API))
    a = await role_conn(Role.WORKER)
    b, sweeper = await role_conn(Role.WORKER), await role_conn(Role.SWEEPER)
    harness = await role_conn(Role.TEST_HARNESS)  # the one role that may move app.test_clock (AM-20.6)
    try:
        first = await persistence.claim_next(a, worker_name="w-killed", tenant_ids=[tenant], lease_seconds=30)
        assert isinstance(first, persistence.Claimed)
        await a.close()  # the owner dies without releasing anything (a killed process)
        assert first.job["id"] not in await leases.reclaim(sweeper)  # the lease is live: the claim stands
        async with b.transaction():
            busy = await persistence.acquire_lease(b, run_id=run, owner="w-next", lease_seconds=30)
        assert busy == Busy(locked=False)
        # Expiry on the database clock (R107): the test clock passes the 30 s lease. The offset is global, and no other
        # lease in this database matters while it is set; it is reset in `finally`.
        await harness.execute("UPDATE app.test_clock SET clock_offset = interval '31 seconds'")
        try:
            assert first.job["id"] in await leases.reclaim(sweeper)
            second = await persistence.claim_next(b, worker_name="w-next", tenant_ids=[tenant], lease_seconds=30)
            assert isinstance(second, persistence.Claimed) and second.job["id"] == first.job["id"]
            assert second.lease.fence == first.lease.fence + 1  # R019: "another owner acquires … incremented fence"
            zombie = await role_conn(Role.WORKER)  # the killed owner's code on a fresh connection, old lease in hand
            with pytest.raises(LeaseLost):
                async with zombie.transaction():
                    await persistence.fenced(zombie, first.lease)
            lines.append(
                f"R019 killed owner: claim kept while live, reclaimed after expiry, next at fence {second.lease.fence}"
            )
        finally:
            await harness.execute("UPDATE app.test_clock SET clock_offset = interval '0'")
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)


async def test_the_reclaim_leaves_a_live_lease_alone(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    tenant, _, run = await new_run(app_conn, api=await role_conn(Role.API))
    a, sweeper = await role_conn(Role.WORKER), await role_conn(Role.SWEEPER)
    try:
        claimed = await persistence.claim_next(a, worker_name="w-alive", tenant_ids=[tenant], lease_seconds=30)
        assert isinstance(claimed, persistence.Claimed)
        assert claimed.job["id"] not in await leases.reclaim(sweeper)
        cur = await app_conn.execute("SELECT claimed_by FROM app.jobs WHERE id = %s", (claimed.job["id"],))
        assert (await cur.fetchone())["claimed_by"] == "w-alive"
        await persistence.release_lease(a, claimed.lease, job=dict(claimed.job))
        assert claimed.job["id"] not in await leases.reclaim(sweeper)  # done: nothing to hand back
        lines.append("reclaim: a live owner's claim is kept; a finished job is never handed back")
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)
```

In `tests/e2e/test_admission_live.py`:

Edit 1 (old line 55), replace:

```python
EXPECTED_LINES = 14  # the evidence lines the six tests append between them
```

with:

```python
EXPECTED_LINES = 15  # the evidence lines the tests append between them (T12's fourteen, T13's global bound)
```

Edit 2: append at the end of the file, after two blank lines:

```python
async def test_the_global_queue_bound_answers_429_and_records_nothing(
    app_conn: persistence.Conn, created: list[str], lines: list[str]
) -> None:
    """Plan H ruling 13 (BS:550 "100 total"): the bound is set to one more than the QUEUED runs of every tenant, so
    the first admission takes the last place and the next is refused, unrecorded, with Retry-After."""
    queued = await count(app_conn, "SELECT count(*) AS n FROM app.runs WHERE state = 'QUEUED'")
    async with api(AdmissionSettings(idempotency_ttl_seconds=604800, global_queue_limit=queued + 1)) as c:
        last = await c.post(messages(await conversation(c, created)), headers=h(), json=SAMPLE)
        last_status = last.status_code
        assert last_status == 202, last_status
        full = await c.post(messages(await conversation(c, created)), headers=h(key="global-key-0001"), json=SAMPLE)
        status, body, retry = full.status_code, full.json(), full.headers.get("Retry-After")
        assert (status, body["code"], body["message"], retry) == (429, "RATE_LIMITED", "the work queue is full", "5")
    records = "SELECT count(*) AS n FROM app.idempotency_request WHERE key = %s"
    assert await count(app_conn, records, "global-key-0001") == 0  # a 429 is nobody's record (Plan G ruling 5)
    lines.append(f"global queue bound at {queued + 1}: the next admission 429 RATE_LIMITED Retry-After 5, unrecorded")
```

Run (dev stack up, no skeleton process running; about 40 s):

```bash
OPS_LIVE=1 PROFILE=test PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_lease_stress_live.py \
  tests/e2e/test_admission_live.py tests/e2e/test_sweeper_live.py -q
```

Expected: `14 passed` (3 new; the admission module's 7; the sweeper module's 4); `reports/leases/t13-stress.txt`
holds the header and three lines.

- [ ] **Step 4: Gates and commit**

Format, lint and count characters on every file of this task.

Run: `PYTHONUTF8=1 uv run python scripts/check.py`
Expected: `CHECK: GREEN`; pytest `914 passed, 132 skipped` (909 + 2 + 3; the 4 new live tests skip).

Run: `PYTHONUTF8=1 uv run python scripts/check.py --profile test`
Expected: `CHECK: GREEN`; pytest `1025 passed, 21 skipped` (R105's skeleton sweeper now reclaims every tick). Then
`git checkout -- reports/bootstrap reports/skeleton reports/auth reports/admission`.

Run: `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`
Expected: exit 0.

```bash
git add sweeper/src/ops_sweeper core/src/ops_core/persistence.py api/src/ops_api tests/plan_g/fakes.py
git add tests/plan_h/test_reclaim.py tests/plan_h/test_global_queue.py tests/e2e/test_lease_stress_live.py
git add tests/e2e/test_admission_live.py
git commit -m "feat(sweeper,api): reclaim dead leases' jobs, the stress proof, R019, the global queue bound (T13)"
```

---

### Task 7: The fault factory — all nine BS:405 faults, `lose_after_commit` in the API, faults from the store factory

**Files:**
- Create: `tests/plan_h/test_faults_t13.py`, `tests/plan_h/test_incident_sim_faults.py`,
  `tests/plan_h/test_api_faults.py`
- Modify: `core/src/ops_core/testing/faults.py` (whole file); `incident-sim/src/ops_incident_sim/app.py:5-6`,
  `:90-94`, `:98`, `:185-187`, `:210-216`, `:244-245`, `:254-256`; `api/src/ops_api/app.py` (`create_app`'s signature,
  the lifespan, `API_FAULTS`, the fault route, `production_app`); `api/src/ops_api/store.py:351` (`faults`),
  `:357-362` (`_idempotent`), `:1016-1017` (`DbStore.__init__`), as Task 6 left it;
  `tests/plan_g/test_api_admission.py:22-23`, `:187-189`; `tests/e2e/test_admission_live.py` (imports,
  `EXPECTED_LINES`, `api()`, a new test)

**Requirements:** R098 (fault hooks unreachable outside the test profile; the factory refuses to start without
PROFILE=test), R015's after-commit side, BS:405's nine faults; brief ruling 22.

**Interfaces:**
- Consumes: `idempotency.Verdict.replayed`; the API's `psycopg.OperationalError` handler (Plan G ruling 19: 503
  "database unavailable", retryable).
- Produces: `FaultKind` gains `TIMEOUT_BEFORE_ACCEPT`, `RATE_LIMIT`, `MALFORMED_RESPONSE`, `RECEIPT_HASH_MISMATCH`,
  `DELAY_RECEIPT`; `faults.BS405: dict[str, FaultKind | None]`, `TIMED`, `DEFAULT_SECONDS = 5`; `Faults.arm(kind,
  count=1, *, seconds=None)`, `Faults.seconds(kind) -> int`; `ops_api.app.create_app(..., faults: Faults | None =
  None)`, `API_FAULTS`; `ops_api.store.DbStore(conn, *, faults=None)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/plan_h/test_faults_t13.py`:

```python
"""The fault factory after T13 (Plan H ruling 22, BS:405, R098): nine phrases, eight hooks and one harness behaviour,
a duration only where a duration means something, and still no factory outside the test profile.

Catches: a BS:405 fault with neither a hook nor a stated harness, a hook no phrase names, a `seconds` silently accepted
for a kind that ignores it, and a factory that starts in dev or demo.
"""

import pytest
from ops_core.settings import Profile
from ops_core.testing.faults import BS405, DEFAULT_SECONDS, FaultKind, Faults, FaultsDisabled


def test_every_bs405_phrase_maps_to_one_kind_or_the_harness() -> None:
    assert len(BS405) == 9  # BS:405 names nine
    kinds = [kind for kind in BS405.values() if kind is not None]
    assert len(kinds) == len(set(kinds)) and set(kinds) == set(FaultKind)  # one hook each, no orphan hook
    assert [phrase for phrase, kind in BS405.items() if kind is None] == ["concurrent same-key submission"]


def test_seconds_belongs_to_timeout_before_accept_only() -> None:
    faults = Faults(Profile.TEST)
    assert faults.seconds(FaultKind.TIMEOUT_BEFORE_ACCEPT) == DEFAULT_SECONDS
    faults.arm(FaultKind.TIMEOUT_BEFORE_ACCEPT, seconds=3)
    assert faults.seconds(FaultKind.TIMEOUT_BEFORE_ACCEPT) == 3 and faults.take(FaultKind.TIMEOUT_BEFORE_ACCEPT)
    for kind, seconds in ((FaultKind.RATE_LIMIT, 3), (FaultKind.TIMEOUT_BEFORE_ACCEPT, 0)):
        with pytest.raises(ValueError):
            faults.arm(kind, seconds=seconds)
    assert faults.armed() == {}  # a refused arm arms nothing


@pytest.mark.parametrize("profile", [Profile.DEV, Profile.DEMO])
def test_the_factory_still_refuses_outside_the_test_profile(profile: Profile) -> None:
    with pytest.raises(FaultsDisabled):
        Faults(profile)
```

Create `tests/plan_h/test_incident_sim_faults.py`:

```python
"""incident-sim's five new fault hooks (Plan H ruling 22; BS:405; R098) through the app with the in-memory key table:
where each one acts, what it writes, and that none exists outside the test profile.

Catches: a timeout or a rate limit that writes a key (the destination must not have accepted anything), a malformed
or hash-mismatched answer whose key did not commit (the faults corrupt the answer, never the truth), a delayed
receipt that hides the key for ever or not at all, a 429 not marked retryable, a `seconds` armed on a kind without a
duration, and a hook reachable in dev or demo.
"""

import time
from uuid import uuid4

import pytest
from ops_core.settings import Profile

from tests.plan_d.test_incident_sim import PAYLOAD, SHA, body_for
from tests.plan_e.test_incident_sim_t10 import auth, make


def test_timeout_before_accept_holds_then_answers_503_and_writes_nothing() -> None:
    c, store = make(Profile.TEST)
    with c:
        armed = c.post("/internal/faults/timeout_before_accept", json={"count": 1, "seconds": 1}, headers=auth())
        assert armed.json() == {"armed": {"timeout_before_accept": 1}}
        action = uuid4()
        started = time.monotonic()
        r = c.post("/internal/incidents", json=body_for(PAYLOAD, action=action), headers=auth())
        assert r.status_code == 503 and r.json()["code"] == "UNAVAILABLE" and time.monotonic() - started >= 1.0
        assert action not in store.rows


def test_rate_limit_is_a_retryable_429_and_writes_nothing() -> None:
    c, store = make(Profile.TEST)
    with c:
        refused = c.post("/internal/faults/rate_limit", json={"count": 1, "seconds": 3}, headers=auth())
        assert refused.status_code == 422  # seconds belongs to timeout_before_accept only
        c.post("/internal/faults/rate_limit", json={"count": 1}, headers=auth())
        action = uuid4()
        r = c.post("/internal/incidents", json=body_for(PAYLOAD, action=action), headers=auth())
        assert r.status_code == 429 and r.headers["Retry-After"] == "1"
        assert (r.json()["code"], r.json()["retryable"]) == ("RATE_LIMITED", True) and action not in store.rows
        again = c.post("/internal/incidents", json=body_for(PAYLOAD, action=action), headers=auth())
        assert again.json()["state"] == "COMMITTED"  # one fault, one request


def test_a_malformed_response_follows_a_real_commit() -> None:
    c, store = make(Profile.TEST)
    with c:
        c.post("/internal/faults/malformed_response", json={"count": 1}, headers=auth())
        action = uuid4()
        r = c.post("/internal/incidents", json=body_for(PAYLOAD, action=action), headers=auth())
        assert r.status_code == 200 and not isinstance(r.json().get("receipt"), dict)  # no receipt shape
        assert store.rows[action].state == "COMMITTED"
        assert c.get(f"/internal/actions/{action}", headers=auth()).json()["receipt"]["incident_id"]  # truth stands


def test_a_receipt_hash_mismatch_follows_a_real_commit() -> None:
    c, store = make(Profile.TEST)
    with c:
        c.post("/internal/faults/receipt_hash_mismatch", json={"count": 1}, headers=auth())
        action = uuid4()
        r = c.post("/internal/incidents", json=body_for(PAYLOAD, action=action), headers=auth())
        assert r.status_code == 200 and r.json()["state"] == "COMMITTED" and r.json()["payload_sha256"] != SHA
        assert store.rows[action].payload_sha256 == SHA
        assert c.get(f"/internal/actions/{action}", headers=auth()).json()["payload_sha256"] == SHA


def test_a_delayed_receipt_is_hidden_for_count_lookups_then_visible() -> None:
    c, _ = make(Profile.TEST)
    with c:
        action = uuid4()
        assert c.post("/internal/incidents", json=body_for(PAYLOAD, action=action), headers=auth()).status_code == 200
        c.post("/internal/faults/delay_receipt", json={"count": 2}, headers=auth())
        statuses = [c.get(f"/internal/actions/{action}", headers=auth()).status_code for _ in range(3)]
        assert statuses == [404, 404, 200]


@pytest.mark.parametrize("profile", [Profile.DEV, Profile.DEMO])
def test_the_new_hooks_do_not_exist_outside_the_test_profile(profile: Profile) -> None:
    c, _ = make(profile)
    with c:
        for kind in ("timeout_before_accept", "rate_limit", "malformed_response", "delay_receipt"):
            assert c.post(f"/internal/faults/{kind}", json={"count": 1}, headers=auth()).status_code == 404
```

Create `tests/plan_h/test_api_faults.py`:

```python
"""The API's fault hooks after T13 (Plan H ruling 22; R015's after-commit side; R098): `lose_after_commit` commits the
unit and its record and loses only the answer, and the factory, not the lifespan, gives the store its faults.

Catches: a lost answer whose unit did not commit (a retry would then start a second run), a replay that is not the
recorded 202, a fault route reachable in dev or demo, faults built outside the test profile, and a store holding other
faults than the route arms (the route would arm what nothing consumes).
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from ops_api.app import create_app
from ops_core.settings import Profile
from ops_core.testing.faults import Faults

from tests.plan_f.auth_fakes import fake_auth
from tests.plan_g.fakes import FakeStore, StubVerifier
from tests.plan_g.test_store_units import SAMPLE


def h(key: str) -> dict[str, str]:
    return {"Authorization": "Bearer alex", "Idempotency-Key": key}


def app_for(fake: FakeStore, profile: Profile, faults: Faults | None) -> Any:
    return create_app(
        StubVerifier(), store_factory=lambda: fake, auth_factory=fake_auth, profile=profile, faults=faults
    )


def test_lose_after_commit_answers_503_and_the_replay_returns_the_recorded_202() -> None:
    fake = FakeStore()
    fake.faults = Faults(Profile.TEST)  # what the factory gives the store
    with TestClient(app_for(fake, Profile.TEST, fake.faults)) as c:
        cid = c.post("/api/v1/conversations", headers=h("conv-key-01")).json()["conversation_id"]
        armed = c.post("/internal/faults/lose_after_commit", headers=h("arm-key-01"), json={"count": 1})
        assert armed.status_code == 200 and armed.json() == {"armed": {"lose_after_commit": 1}}
        lost = c.post(f"/api/v1/conversations/{cid}/messages", headers=h("key-lost-01"), json=SAMPLE)
        assert lost.status_code == 503 and lost.json()["retryable"] is True
        assert lost.json()["message"] == "database unavailable"  # what a connection lost after COMMIT looks like
        assert len(fake.runs) == 1 and len(fake.jobs) == 1  # the unit committed, its record included
        replay = c.post(f"/api/v1/conversations/{cid}/messages", headers=h("key-lost-01"), json=SAMPLE)
        assert replay.status_code == 202 and replay.json()["run_id"] == str(next(iter(fake.runs)))
        assert len(fake.runs) == 1  # R015: the retry replays, it does not start a second run


@pytest.mark.parametrize("profile", [Profile.DEV, Profile.DEMO])
def test_the_fault_route_does_not_exist_outside_the_test_profile(profile: Profile) -> None:
    with TestClient(app_for(FakeStore(), profile, None)) as c:
        r = c.post("/internal/faults/lose_after_commit", headers=h("arm-key-02"), json={"count": 1})
        assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"


def test_faults_belong_to_the_test_profile_and_only_to_it() -> None:
    with pytest.raises(ValueError):
        app_for(FakeStore(), Profile.DEV, Faults(Profile.TEST))
    with pytest.raises(ValueError):
        app_for(FakeStore(), Profile.TEST, None)


def test_the_store_must_hold_the_apps_faults() -> None:
    fake = FakeStore()
    fake.faults = Faults(Profile.TEST)  # another object than the app's
    with pytest.raises(RuntimeError), TestClient(app_for(fake, Profile.TEST, Faults(Profile.TEST))):
        pass
```

Run: `uv run python -m pytest tests/plan_h/test_faults_t13.py -q`
Expected: `1 error in` (`ImportError: cannot import name 'BS405'`; pytest stops at the collection error, so the other
two modules run on their own below).

Run: `uv run python -m pytest tests/plan_h/test_incident_sim_faults.py tests/plan_h/test_api_faults.py -q`
Expected: `10 failed, 2 passed`: the five incident-sim tests that arm a new kind fail because the route's
`FaultKind` path parameter does not know the kind yet (422) and the hot path behaves as before (only the two profile
tests pass: outside the test profile every fault route is 404 already); every API test fails with `TypeError:
create_app() got an unexpected keyword argument 'faults'`.

- [ ] **Step 2: The factory, the destination's hooks and the API's**

Replace the whole of `core/src/ops_core/testing/faults.py` with:

```python
"""Test-only fault injection (R098; BUILD_SPEC §14 "Fault hooks are test-harness-only"; SA:564): a counter per fault
kind that a server consumes on its hot path. `Faults` is the factory: it refuses to exist outside the test profile,
which is what makes the hooks unreachable in dev and demo; each service mounts its own arming route over the object
its factory built (incident-sim's destination faults, the API's admission faults; Plan H ruling 22). `BS405` maps
BUILD_SPEC's nine faults to the hooks. The worker and the sweeper have none: their failure, a lost lease, is produced
for real by the tests (Plan H ruling 20).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from ops_core.settings import Profile


class FaultKind(StrEnum):
    """The hooks, named by their effect on the next request (Plan E ruling 13, Plan H ruling 22)."""

    REJECT_NEXT = "reject_next"  # the next POST writes a permanent REJECTED key (reason policy)
    DROP_BEFORE_COMMIT = "drop_before_commit"  # the next POST answers 503 and writes nothing
    LOSE_AFTER_COMMIT = "lose_after_commit"  # the next POST commits, then the response is lost (503)
    TIMEOUT_BEFORE_ACCEPT = "timeout_before_accept"  # the next POST is held `seconds`, then 503; nothing written
    RATE_LIMIT = "rate_limit"  # the next POST answers 429 with Retry-After; nothing written
    MALFORMED_RESPONSE = "malformed_response"  # the next POST commits and answers a body that is no receipt
    RECEIPT_HASH_MISMATCH = "receipt_hash_mismatch"  # the next POST commits and answers another payload hash
    DELAY_RECEIPT = "delay_receipt"  # the next lookup of a committed key answers 404, as if not yet visible


# BS:405's nine faults, phrase by phrase. Concurrent same-key submission is a harness behaviour, not a hook: two
# submissions of one key are raced with asyncio.gather against the real key table (R047,
# tests/e2e/test_incident_sim_live.py), since a hook could only pretend to the race the table must win.
BS405: Final[dict[str, FaultKind | None]] = {
    "response loss after commit": FaultKind.LOSE_AFTER_COMMIT,
    "timeout before acceptance": FaultKind.TIMEOUT_BEFORE_ACCEPT,
    "delayed receipt visibility": FaultKind.DELAY_RECEIPT,
    "malformed response": FaultKind.MALFORMED_RESPONSE,
    "mismatching receipt hash": FaultKind.RECEIPT_HASH_MISMATCH,
    "rate limit": FaultKind.RATE_LIMIT,
    "transient unavailable": FaultKind.DROP_BEFORE_COMMIT,
    "definitive no-commit failure": FaultKind.REJECT_NEXT,
    "concurrent same-key submission": None,
}
TIMED: Final = frozenset({FaultKind.TIMEOUT_BEFORE_ACCEPT})  # the kinds that take `seconds`
DEFAULT_SECONDS: Final = 5


class FaultsDisabled(RuntimeError):
    """Constructed outside the test profile: the hooks must not exist there (R098)."""


class Faults:
    """Armed counts per kind; `take` consumes one or answers False when nothing is armed."""

    def __init__(self, profile: Profile) -> None:
        if profile is not Profile.TEST:
            raise FaultsDisabled(f"fault hooks are unavailable in the {profile.value} profile")
        self._armed: dict[FaultKind, int] = {}
        self._seconds: dict[FaultKind, int] = {}

    def arm(self, kind: FaultKind, count: int = 1, *, seconds: int | None = None) -> None:
        """Arm `count` occurrences of `kind` (adds to what is armed); `seconds` is how long a timed kind holds.

        Raises:
            ValueError: a count below 1, or `seconds` below 1 or for a kind without a duration; nothing is armed.
        """
        if count < 1:
            raise ValueError("count must be at least 1")
        if seconds is not None:
            if kind not in TIMED:
                raise ValueError("seconds applies to timeout_before_accept only")
            if seconds < 1:
                raise ValueError("seconds must be at least 1")
            self._seconds[kind] = seconds
        self._armed[kind] = self._armed.get(kind, 0) + count

    def take(self, kind: FaultKind) -> bool:
        """Consume one armed occurrence; False when none is armed."""
        left = self._armed.get(kind, 0)
        if left <= 0:
            return False
        if left == 1:
            del self._armed[kind]
        else:
            self._armed[kind] = left - 1
        return True

    def seconds(self, kind: FaultKind) -> int:
        """How long a timed kind holds its request: the last value armed, else DEFAULT_SECONDS."""
        return self._seconds.get(kind, DEFAULT_SECONDS)

    def armed(self) -> dict[str, int]:
        """What is still armed, by kind name."""
        return {kind.value: count for kind, count in self._armed.items()}
```

In `incident-sim/src/ops_incident_sim/app.py`:

Edit 1 (old lines 5-6), replace:

```python
# No `from __future__ import annotations`: FastAPI resolves dependency annotations at import time (Plan D review).
from collections.abc import AsyncIterator, Awaitable, Callable
```

with:

```python
# No `from __future__ import annotations`: FastAPI resolves dependency annotations at import time (Plan D review).
import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
```

Edit 2 (old lines 90-94), replace:

```python
class FaultRequest(BaseModel):
    """How many occurrences of a fault to arm (test profile only)."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    count: int = Field(ge=1, le=100)
```

with:

```python
class FaultRequest(BaseModel):
    """How many occurrences of a fault to arm, and how long a timed one holds (test profile only)."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    count: int = Field(ge=1, le=100)
    seconds: int | None = Field(default=None, ge=1, le=120)  # timeout_before_accept only (Plan H ruling 22)
```

Edit 3 (old line 98), replace:

```python
    body = SafeError(code=code, message=message, retryable=status == 503, request_id=uuid4())
```

with:

```python
    body = SafeError(code=code, message=message, retryable=status in (429, 503), request_id=uuid4())
```

Edit 4 (old lines 185-187), replace:

```python
        except (UnicodeDecodeError, CanonicalizationError, ValidationError, ValueError):
            return safe_error(422, ErrorCode.INVALID_INPUT, "body is not a well-formed incident request")
        # From here the envelope is well formed, so every refusal is a permanent REJECTED key (SA:261) and a lost
```

with:

```python
        except (UnicodeDecodeError, CanonicalizationError, ValidationError, ValueError):
            return safe_error(422, ErrorCode.INVALID_INPUT, "body is not a well-formed incident request")
        # Plan H ruling 22: the two faults that answer before the destination accepts anything (nothing is written).
        if faults is not None and faults.take(FaultKind.TIMEOUT_BEFORE_ACCEPT):
            await asyncio.sleep(faults.seconds(FaultKind.TIMEOUT_BEFORE_ACCEPT))
            return safe_error(503, ErrorCode.UNAVAILABLE, "destination timed out before accepting (fault)")
        if faults is not None and faults.take(FaultKind.RATE_LIMIT):
            return safe_error(429, ErrorCode.RATE_LIMITED, "destination rate limit (fault)", {"Retry-After": "1"})
        # From here the envelope is well formed, so every refusal is a permanent REJECTED key (SA:261) and a lost
```

Edit 5 (old lines 210-216), replace:

```python
            row = await st.commit(body.action_id, body.payload_sha256, payload)
            if faults is not None and faults.take(FaultKind.LOSE_AFTER_COMMIT):
                return safe_error(503, ErrorCode.UNAVAILABLE, "response lost after commit (fault)")
        except psycopg.Error:
            return safe_error(503, ErrorCode.UNAVAILABLE, "destination database unavailable")
        status, doc = keys.document(row, presented_sha256=body.payload_sha256)
        return JSONResponse(status_code=status, content=doc)
```

with:

```python
            row = await st.commit(body.action_id, body.payload_sha256, payload)
            if faults is not None and faults.take(FaultKind.LOSE_AFTER_COMMIT):
                return safe_error(503, ErrorCode.UNAVAILABLE, "response lost after commit (fault)")
        except psycopg.Error:
            return safe_error(503, ErrorCode.UNAVAILABLE, "destination database unavailable")
        status, doc = keys.document(row, presented_sha256=body.payload_sha256)
        # Plan H ruling 22: two faults that corrupt the answer about a committed key; the key itself stands.
        if faults is not None and faults.take(FaultKind.MALFORMED_RESPONSE):
            return JSONResponse({"state": doc["state"], "receipt": "not a receipt"})
        if faults is not None and faults.take(FaultKind.RECEIPT_HASH_MISMATCH):
            other = sha256_hex(str(doc["payload_sha256"]).encode("utf-8"))  # the hash of the hash: never the hash
            return JSONResponse(status_code=status, content={**doc, "payload_sha256": other})
        return JSONResponse(status_code=status, content=doc)
```

Edit 6 (old lines 244-245), replace:

```python
            armable.arm(kind, body.count)
            return JSONResponse({"armed": armable.armed()})
```

with:

```python
            try:
                armable.arm(kind, body.count, seconds=body.seconds)
            except ValueError:  # `seconds` for a kind without a duration
                return safe_error(422, ErrorCode.INVALID_INPUT, "seconds applies to timeout_before_accept only")
            return JSONResponse({"armed": armable.armed()})
```

Edit 7 (old lines 254-256), replace:

```python
        if row is None:
            return safe_error(404, ErrorCode.NOT_FOUND, "no such action")
        status, doc = keys.document(row, presented_sha256=row.payload_sha256)
```

with:

```python
        if row is not None and faults is not None and faults.take(FaultKind.DELAY_RECEIPT):
            row = None  # Plan H ruling 22: the key exists, but its receipt is not visible yet
        if row is None:
            return safe_error(404, ErrorCode.NOT_FOUND, "no such action")
        status, doc = keys.document(row, presented_sha256=row.payload_sha256)
```

In `api/src/ops_api/store.py`:

Edit 1 (old line 351), replace:

```python
    faults: Faults | None = None  # set by create_app under PROFILE=test only (ruling 24)
```

with:

```python
    faults: Faults | None = None  # given by the store's factory under PROFILE=test only (Plan H ruling 22)
```

Edit 2 (old lines 357-362), replace:

```python
    async def _idempotent(self, tenant_id: UUID, idem: Idem, work: Work) -> Verdict:
        try:
            async with self.unit(tenant_id) as unit:
                return await idempotent(unit, idem, lambda: work(unit))
        except RecordRace:
            pass  # the unit rolled back; the re-read below answers from whatever row blocked the insert
```

with:

```python
    async def _idempotent(self, tenant_id: UUID, idem: Idem, work: Work) -> Verdict:
        try:
            async with self.unit(tenant_id) as unit:
                verdict = await idempotent(unit, idem, lambda: work(unit))
        except RecordRace:
            pass  # the unit rolled back; the re-read below answers from whatever row blocked the insert
        else:
            if not verdict.replayed and self.faults is not None and self.faults.take(FaultKind.LOSE_AFTER_COMMIT):
                # R015's after-commit side (Plan H ruling 22): the unit, its record included, has committed; only the
                # answer is lost, as when the connection drops after COMMIT. The client sees the retryable 503 of a
                # lost connection, and a retry under the same key replays the recorded answer.
                raise psycopg.OperationalError("fault: lose_after_commit")
            return verdict
```

Edit 3 (old lines 1016-1017), replace:

```python
    def __init__(self, conn: persistence.Conn) -> None:
        self.session = persistence.Session(conn)  # ruling 24: one unit of work at a time, each a real transaction
```

with:

```python
    def __init__(self, conn: persistence.Conn, *, faults: Faults | None = None) -> None:
        self.session = persistence.Session(conn)  # ruling 24: one unit of work at a time, each a real transaction
        self.faults = faults  # the test profile's hooks, from the factory (Plan H ruling 22); None elsewhere
```

In `api/src/ops_api/app.py` (as Task 6 left it):

Edit 1, replace:

```python
    admission: AdmissionSettings | None = None,
    profile: Profile = Profile.DEV,
) -> FastAPI:
    """Build the application around a verifier, a store factory and an auth-deps factory (the lifespan runs both).

    `admission` carries the body limit and the other T12 bounds; tests pass their own, production passes
    `settings.admission()`, and the default is the spec's starting values (BUILD_SPEC §17). Under the test profile
    the app also arms faults (R098: the hooks do not exist in dev or demo, so the route is the safe 404 there).
    """
    bounds = admission or AdmissionSettings()
    faults = Faults(profile) if profile is Profile.TEST else None
```

with:

```python
    admission: AdmissionSettings | None = None,
    profile: Profile = Profile.DEV,
    faults: Faults | None = None,
) -> FastAPI:
    """Build the application around a verifier, a store factory and an auth-deps factory (the lifespan runs both).

    `admission` carries the body limit and the other T12 bounds; tests pass their own, production passes
    `settings.admission()`, and the default is the spec's starting values (BUILD_SPEC §17). `faults` exists under the
    test profile only (R098: in dev and demo there are no hooks, so the route is the safe 404 there), and the store
    factory gives the store the same object, so the route arms exactly what the store consumes (Plan H ruling 22).

    Raises:
        ValueError: faults outside the test profile, or a test-profile app without them.
    """
    bounds = admission or AdmissionSettings()
    if profile is Profile.TEST and faults is None:
        raise ValueError("a test-profile app needs the Faults its store holds")
    if profile is not Profile.TEST and faults is not None:
        raise ValueError("fault hooks exist only in the test profile")
```

Edit 2, replace:

```python
        made = store_factory()
        app.state.store = await made if isinstance(made, Awaitable) else made
        app.state.store.faults = faults
        try:
```

with:

```python
        made = store_factory()
        app.state.store = await made if isinstance(made, Awaitable) else made
        try:
            # Plan H ruling 22: the factory gives the store the app's faults; a store holding others (or none under
            # the test profile) would leave the fault route arming what nothing consumes.
            if app.state.store.faults is not faults:
                raise RuntimeError("the store factory did not give the store this app's faults")
```

Edit 3, replace:

```python
            if kind is not FaultKind.DROP_BEFORE_COMMIT:
                raise ApiError(422, ErrorCode.INVALID_INPUT, "the API implements drop_before_commit only")
```

with:

```python
            if kind not in API_FAULTS:
                raise ApiError(422, ErrorCode.INVALID_INPUT, "the API implements drop_before_commit, lose_after_commit")
```

and in the same route's docstring replace:

```python
            """Arm a fault for the next `count` admissions (R015's crash before commit, ruling 24); the route exists
```

with:

```python
            """Arm a fault for the next `count` mutations: `drop_before_commit` (R015's crash before commit, Plan G
            ruling 24) or `lose_after_commit` (the unit commits, the answer is lost; Plan H ruling 22); the route exists
```

Edit 4: insert, immediately before `def create_app(`:

```python
API_FAULTS = frozenset({FaultKind.DROP_BEFORE_COMMIT, FaultKind.LOSE_AFTER_COMMIT})  # the API's hooks (BS:405)


```

Edit 5, replace:

```python
    async def make_store() -> st.Store:
        return st.DbStore(await persistence.connect(settings.app_postgres(Role.API)))
```

with:

```python
    profile = settings.profile()
    faults = Faults(profile) if profile is Profile.TEST else None  # R098: the hooks exist in the test profile only

    async def make_store() -> st.Store:
        # Plan H ruling 22: the store is built with the app's faults rather than handed them by the lifespan.
        return st.DbStore(await persistence.connect(settings.app_postgres(Role.API)), faults=faults)
```

Edit 6, replace:

```python
    return create_app(verifier, make_store, make_auth, admission=settings.admission(), profile=settings.profile())
```

with:

```python
    return create_app(verifier, make_store, make_auth, admission=settings.admission(), profile=profile, faults=faults)
```

In `tests/plan_g/test_api_admission.py`:

Edit 1 (old lines 22-23), replace:

```python
from ops_api.app import create_app
from ops_core.settings import AdmissionSettings, Profile
```

with:

```python
from ops_api.app import create_app
from ops_core.settings import AdmissionSettings, Profile
from ops_core.testing.faults import Faults
```

Edit 2 (old lines 187-189), replace:

```python
def test_a_fault_before_commit_is_a_retryable_503_and_the_same_key_then_succeeds() -> None:
    fake = FakeStore()
    with client(fake, profile=Profile.TEST) as c:
```

with:

```python
def test_a_fault_before_commit_is_a_retryable_503_and_the_same_key_then_succeeds() -> None:
    fake = FakeStore()
    fake.faults = Faults(Profile.TEST)  # the store's factory gives it the app's faults (Plan H ruling 22)
    with client(fake, profile=Profile.TEST, faults=fake.faults) as c:
```

In `tests/e2e/test_admission_live.py`:

Edit 1, replace:

```python
from ops_core.settings import AdmissionSettings, Profile, Role
from psycopg.types.json import Jsonb
```

with:

```python
from ops_core.settings import AdmissionSettings, Profile, Role
from ops_core.testing.faults import Faults
from psycopg.types.json import Jsonb
```

Edit 2, replace:

```python
EXPECTED_LINES = 15  # the evidence lines the tests append between them (T12's fourteen, T13's global bound)
```

with:

```python
EXPECTED_LINES = 16  # the evidence lines the tests append between them (T12's fourteen, T13's two)
```

Edit 3, replace:

```python
    """The real app over its own `api` connection, lifespan included (the 0006 relation guard runs)."""

    async def store() -> st.Store:
        return st.DbStore(await persistence.connect(settings.app_postgres(Role.API)))

    app = create_app(
        StubVerifier(), store_factory=store, auth_factory=fake_auth, admission=admission, profile=Profile.TEST
    )
```

with:

```python
    """The real app over its own `api` connection, lifespan included (the 0007 relation guard runs), with the test
    profile's faults given to the store by its factory, as production_app does (Plan H ruling 22)."""
    faults = Faults(Profile.TEST)

    async def store() -> st.Store:
        return st.DbStore(await persistence.connect(settings.app_postgres(Role.API)), faults=faults)

    app = create_app(
        StubVerifier(),
        store_factory=store,
        auth_factory=fake_auth,
        admission=admission,
        profile=Profile.TEST,
        faults=faults,
    )
```

Edit 4: append at the end of the file, after two blank lines:

```python
async def test_r015_a_response_lost_after_commit_replays_the_recorded_202(
    app_conn: persistence.Conn, created: list[str], lines: list[str]
) -> None:
    """R015's after-commit side (Plan H ruling 22): the unit commits with its record, the answer is lost as a
    retryable 503, and the retry under the same key replays the recorded 202 for the one run it started."""
    async with api() as c:
        cid = await conversation(c, created)
        armed = await c.post("/internal/faults/lose_after_commit", headers=h(), json={"count": 1})
        armed_status = armed.status_code
        assert armed_status == 200, armed_status
        lost = await c.post(messages(cid), headers=h(key="r015-key-lost"), json=SAMPLE)
        lost_status, lost_body = lost.status_code, lost.json()
        assert lost_status == 503 and lost_body["retryable"] is True, lost_status
        runs = "SELECT run_id FROM app.runs WHERE conversation_id = %s"
        cur = await app_conn.execute(runs, (UUID(cid),))
        committed = [row["run_id"] for row in await cur.fetchall()]
        assert len(committed) == 1  # the run exists although its acknowledgement was lost
        replay = await c.post(messages(cid), headers=h(key="r015-key-lost"), json=SAMPLE)
        replay_status, run_id = replay.status_code, replay.json().get("run_id")
        assert replay_status == 202 and run_id == str(committed[0])
    cur = await app_conn.execute(runs, (UUID(cid),))
    after = len(await cur.fetchall())
    assert after == 1  # the replay started nothing
    lines.append(f"R015 response lost after commit: 503 retryable=True, then replay 202 for the same run, runs={after}")
```

Run: `uv run python -m pytest tests/plan_h tests/plan_g tests/plan_e/test_faults.py tests/plan_e/test_incident_sim_t10.py tests/plan_d/test_incident_sim.py tests/plan_d/test_api.py tests/plan_f -q`
Expected: `425 passed` (Plan H's 113; Plan G's 135; Plan E's fault and incident-sim modules 3 and 6; Plan D's
incident-sim and API modules 10 and 11; Plan F's 147).

- [ ] **Step 3: Gates and commit**

Format, lint and count characters on every file of this task.

Run: `OPS_LIVE=1 PROFILE=test PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_admission_live.py tests/e2e/test_incident_sim_live.py -q`
Expected: `13 passed` (the admission module's 8, the incident-sim module's 5); `reports/admission/t12-admission.txt`
holds the header and sixteen lines.

Run: `PYTHONUTF8=1 uv run python scripts/check.py`
Expected: `CHECK: GREEN`; pytest `930 passed, 133 skipped` (914 + 4 + 7 + 5; the 1 new live test skips).

Run: `PYTHONUTF8=1 uv run python scripts/check.py --profile test`
Expected: `CHECK: GREEN`; pytest `1042 passed, 21 skipped` (R105's skeleton API now builds its faults in
`production_app`). Then `git checkout -- reports/bootstrap reports/skeleton reports/auth reports/admission`.

Run: `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`
Expected: exit 0.

```bash
git add core/src/ops_core/testing/faults.py incident-sim/src/ops_incident_sim/app.py api/src/ops_api
git add tests/plan_h/test_faults_t13.py tests/plan_h/test_incident_sim_faults.py tests/plan_h/test_api_faults.py
git add tests/plan_g/test_api_admission.py tests/e2e/test_admission_live.py
git commit -m "feat(faults): the nine BS:405 faults, lose_after_commit in the API, faults from the store factory (T13)"
```

---

### Task 8: Handoff close-out — records, acceptance rows, errata 45-57, the runbook, final gates

**Files:**
- Create: `docs/runbooks/leases.md`
- Modify: `handoff/tasks.json` (T13 → `DONE`, one review note), `handoff/acceptance-matrix.json` (R019, R020, R087,
  R088, R098, R107; R015's note), `handoff/BUILD_BACKLOG.md` (T13 checked, one review note), `SESSION_STATE.md` (the
  "Next task" line, a "Plan H executed" section, the dev database state, the owner inputs, the repository line),
  `STATUS.md` (an update section), `docs/ARCHITECTURE.md` (a new section before "Where the code will live"),
  `docs/PROJECT_HISTORY.md` (the leases plan's section), `README.md:5` (status line), `worker/README.md` (the "Runs"
  section), `sweeper/README.md` (the "Owns" paragraph and the "Runs" section), this plan (its checkboxes); the
  evidence files `reports/leases/*.txt`, `reports/admission/t12-admission.txt`, `reports/skeleton/
  r105-walking-skeleton.txt` from the final live run

**Requirements:** the T13 record (R019, R020, R087, R088, R098, R107 evidenced); every remaining `TODO(T13)` in code has
a new owner. This task writes no code.

Throughout, `<base>..<last>` is the git range of this plan's execution on `plan-h`, written as two short hashes:
`<base>` is the `BASE` recorded in Task 1 Step 1b (excluded by the range) and `<last>` the newest commit before this
task's own (`LAST=$(git rev-parse --short HEAD)`, run before this task commits). `<date>` is `date -u +%F` on the day
of the close-out.

- [ ] **Step 1: No `TODO(T13)` is left in live code**

Run:

```bash
git grep -n "TODO(T13" -- core api worker sweeper mcp-write mcp-read incident-sim scripts tests
grep -c "TODO(T13" migrations/app/versions/0007_leases_fences.py
```

Expected: the first command prints nothing; the second prints `1`, the `GRANT_TODO_0005` literal, which quotes
revision 0005's comment line verbatim so the rewording can find it (no function body 0007 installs carries the
marker). The applied revisions `migrations/app/versions/0002`-`0005` keep their historical `TODO(T13)` comments: an
applied revision is never edited, and every function body those comments sit in is superseded by revision 0007. If
the first command prints a line, give that TODO its new owner from the debt list (T14, T19, T20, T21, T22, T29 or
T30) in a separate commit before continuing.

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
    f"Plan H (branch plan-h): done in {span} (the eight tasks; plan "
    "docs/superpowers/plans/2026-10-15-first-slice-h-leases-fences-heartbeat.md). Shipped: the run lease taken in "
    "the claim's own transaction (FOR UPDATE NOWAIT; a busy run's job deferred behind the lease, never claimed) and "
    "released with the job's final unit (handles revoked, job closed, lease_until -infinity, fence kept); every "
    "worker unit that writes for a run opens with the lease row FOR SHARE and owner, fence and expiry compared on "
    "app.current_time() after the lock; handles carry the fence and expire with the lease; _resolve_handle refuses a "
    "moved fence or a lapsed lease for resolve_invocation, grant_execution, lookup_action and the new "
    "mark_sent(raw_handle, action_id) and record_outcome(raw_handle, ...); mark_unknown bumps and returns the fence, "
    "handed to the shared Lease; revoke_handles revokes by fence; the heartbeat thread on its own synchronous "
    "connection with the event-loop liveness and 90 s compute gates, cancelling only the job's effects in flight "
    "(MCP and model calls, never a database unit) through loop.call_soon_threadsafe on loss; the local monotonic "
    "deadline; the model_permit row around drafting "
    "(SKIP LOCKED, backoff, 65 s TTL); the sweeper's reclaim of dead leases' jobs; the published lock order "
    "(core/locking.py, checked by a test); the global queue bound (queued_runs_total, OPS_GLOBAL_QUEUE_LIMIT); the "
    "jobs.type CHECK; the nine BS:405 faults (incident-sim's five new hooks, lose_after_commit in the API, faults "
    "from the store factory); revision 0007. Evidence: tests/e2e/test_leases_live.py, test_fenced_definers_live.py, "
    "test_heartbeat_live.py, test_lease_stress_live.py, test_migration_0007_live.py and reports/leases/ (live), "
    "tests/plan_h/ for the unit half. Deferred: the permit's idle release rule -> T19; budget accounting -> T29; "
    "bounded retries, the AM-13 timeout path and recover jobs -> T22; wake-ups -> T14; the asset guard -> T21; "
    "checkpoints -> T20/T38; pools and reconnects -> T30. Errata 45-57 are proposed in SESSION_STATE.md."
)
tasks_path = Path("handoff/tasks.json")
tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
t13 = next(t for t in tasks["tasks"] if t["id"] == "T13")
t13["status"] = "DONE"
t13["review_notes"].append(note)
tasks_path.write_text(json.dumps(tasks, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

matrix_path = Path("handoff/acceptance-matrix.json")
matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
evidence = {
    "R019": [
        "tests/e2e/test_lease_stress_live.py",
        "reports/leases/t13-stress.txt",
        "tests/plan_h/test_reclaim.py",
    ],
    "R020": [
        "tests/e2e/test_leases_live.py",
        "tests/e2e/test_fenced_definers_live.py",
        "reports/leases/t13-leases.txt",
        "tests/plan_h/test_worker_units.py",
        "tests/plan_h/test_write_path_fence.py",
    ],
    "R087": ["tests/e2e/test_leases_live.py", "reports/leases/t13-leases.txt", "tests/plan_h/test_worker_units.py"],
    "R088": [
        "tests/e2e/test_heartbeat_live.py",
        "reports/leases/t13-heartbeat.txt",
        "tests/plan_h/test_heartbeat.py",
        "tests/plan_h/test_permit.py",
        "tests/plan_h/test_lease.py",
    ],
    "R107": [
        "tests/e2e/test_leases_live.py",
        "tests/e2e/test_lease_stress_live.py",
        "tests/e2e/test_fenced_definers_live.py",
        "reports/leases/t13-leases.txt",
        "reports/leases/t13-stress.txt",
        "tests/plan_h/test_locking.py",
        "tests/plan_h/test_lease.py",
        "tests/plan_h/test_migration_0007.py",
    ],
}
notes = {
    "R019": "Plan H (T13): a claimed owner is killed (connection closed); its claim stands while the lease is live, "
    "the sweeper reclaims the job once the test clock passes the 30 s lease, the next owner claims it at fence + 1, "
    "and the killed owner's lease writes nothing.",
    "R020": "Plan H (T13): worker side, a stale fence's fenced unit and mint abort after a takeover, and a takeover "
    "waits for an open fenced unit; MCP side, a handle is refused after its fence moved or its lease lapsed, and a "
    "stale fence before SENT sends nothing while after SENT it answers UNKNOWN.",
    "R087": "Plan H (T13): a resume_input job of a run whose investigate job holds the lease is deferred behind the "
    "lease, then takes fence + 1; only it writes and only it closes its job.",
    "R088": "Plan H (T13): at the real defaults a 25 s blocked loop and a 35 s fake drafter keep the lease; a forced "
    "renewal failure (expiry and a second worker's takeover) cancels the in-flight MCP call, revokes its handle and "
    "hands the job back with no transition. The three tests are slow_live and run in check.py --profile test.",
    "R107": "Plan H (T13): two- and three-connection interleavings (stale write aborts; takeover waits on the share "
    "lock; expiry compared after the lock; two first claims, the second waiting on the first's insert) and an "
    "8-connection, 20 s stress mix with the sweeper and committed re-fences: no 40P01, no 55P03 under lock_timeout "
    "10 s (a waiting acquisition's long wait counts as 55P03), fences never backwards, at every 50 ms sample at most "
    "one actor believing it held a run's lease and that one the live owner in the database, no "
    "stale event after a newer fence; the published order is core/locking.py with a test over every documented "
    "transaction.",
}
for row in matrix["requirements"]:
    if row["id"] in evidence:
        row["implementation_status"] = "IMPLEMENTED_LOCALLY_VERIFIED"
        row["evidence_status"] = "RECORDED_LOCALLY_LIVE"
        row["evidence_paths"] = evidence[row["id"]]
        row["note"] = notes[row["id"]]
    elif row["id"] == "R098":
        row["evidence_paths"] = [
            "tests/plan_e/test_incident_sim_t10.py",
            "tests/plan_e/test_faults.py",
            "tests/plan_h/test_faults_t13.py",
            "tests/plan_h/test_incident_sim_faults.py",
            "tests/plan_h/test_api_faults.py",
        ]
        row["note"] = (
            "Plan E (T10) and Plan H (T13): every fault route (incident-sim's eight kinds, the API's two) is 404 in "
            "the dev and demo profiles; the factory refuses any profile but test, and the API refuses to build with "
            "faults outside it or without them inside it; BS:405's nine faults map to the hooks in "
            "core.testing.faults.BS405 (concurrent same-key submission is a harness race). Unit-level evidence; the "
            "live suite runs every service under PROFILE=test."
        )
    elif row["id"] == "R015":
        row["note"] = (
            "Plan G (T12): the before-commit crash is proved live with the drop_before_commit fault (no message, "
            "run, job or record, then the same key commits). Plan H (T13): the after-commit side is proved live "
            "with the lose_after_commit fault (the unit and its record commit, the answer is a retryable 503, the "
            "retry replays the recorded 202 for the one run)."
        )
matrix_path.write_text(json.dumps(matrix, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

backlog_path = Path("handoff/BUILD_BACKLOG.md")
backlog = backlog_path.read_text(encoding="utf-8")
head = "- [ ] **T13 Run lease, fence locking, heartbeat thread and fault factory**"
assert backlog.count(head) == 1
backlog = backlog.replace(head, "- [x] **T13 Run lease, fence locking, heartbeat thread and fault factory**")
lines = backlog.split("\n")
at = next(i for i, line in enumerate(lines) if line.startswith("- [x] **T13 "))
end = at + 1
while end < len(lines) and lines[end].startswith("  - "):
    end += 1
lines.insert(end, f"  - *Review note:* {note}")  # after the task's other notes, as tasks.json appends it
backlog_path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
print(span)
EOF
```

Expected: it prints the span (for example `1a2b3c4..5d6e7f8`). `git diff --stat handoff` shows three files changed;
`git diff handoff/acceptance-matrix.json` shows only seven rows: R015, R019, R020, R087, R088, R098 and R107.

- [ ] **Step 3: Project state**

In `SESSION_STATE.md`:

1. Replace the whole line that begins `**Next task:**` with:

```markdown
**Next task:** Plan H (T13) is executed on branch `plan-h` (`<base>..<last>`, on top of `plan-g`: the eight tasks;
the close-out commit follows). Owner inputs: (1) the holdout seal (T03 step 9), then the live probe (T02); (2) merge
the stacked PRs in order and open the plan-h -> plan-g PR; (3) T44 step 10 (`docs/runbooks/ollama-network.md` step
A); (4) decide the proposed errata of Plans C, E, F, G and H (H: 45-57 below); (5) migrate the dev database to
revision 0007 (`uv run python scripts/skeleton.py migrate`, dev profile: from 0005 it applies 0006 and 0007 together;
0007 adds `app.model_permit` and the `jobs.type` CHECK, re-creates the handle functions and deletes nothing). Next is
the earliest dependency-satisfied task in `handoff/tasks.json` after T13 (T14: gap-free event journal, wake-ups and
the outbox; T15 also became unblocked).
```

2. Insert, after the `## Plan G executed …` section and before `## Walking-skeleton debt list …`, the block below, then
   finish it with two bullets only execution can write: `- Rulings made during execution:` (one line each, with its
   reason; or `- Rulings made during execution: none beyond the plan.`) and `- **Open items for later:**` (from the
   SDD ledger `.superpowers/sdd/2026-10-15-first-slice-h-leases-fences-heartbeat/progress.md`; or
   `- **Open items for later:** none recorded.`).

```markdown
## Plan H executed (<date>, branch `plan-h`)

- T13 = `<base>..<last>` (the debt list first, then the eight tasks). The plan
  (`docs/superpowers/plans/2026-10-15-first-slice-h-leases-fences-heartbeat.md`) holds the 31 rulings of the
  controller's brief as implemented; the input is `docs/superpowers/research/2026-10-15-plan-h-inputs.md`.
  Evidence: `tests/e2e/test_leases_live.py`, `test_fenced_definers_live.py`, `test_heartbeat_live.py` (three
  `slow_live` DoD-3 tests), `test_lease_stress_live.py` (the `slow_live` stress test and R019),
  `test_migration_0007_live.py`, `test_admission_live.py` (the global bound and R015's after-commit side) and
  `reports/leases/t13-leases.txt`, `t13-heartbeat.txt`, `t13-stress.txt`; the unit half is in `tests/plan_h/`.
- Gates: `check.py` <dev passed> passed / <dev skipped> skipped; `check.py --profile test` <live passed> passed / 21
  skipped (the plan's tails are 930/133 and 1042/21); `verify_handoff.py` exit 0 (STATUS.md, "Update — Plan H
  executed"). The live gate is about 2.5 minutes longer than Plan G's: the four `slow_live` tests.
- **Proposed errata (the owner decides; the spec text stays authoritative until then).** Numbered on from Plan G's
  forty-four:
  45. SA:418: `app_definer` holds `sel, upd(fence)` on `run_lease`.
  46. SA:174: the worker creates the lease row at the run's first acquisition (released, fence 0; the first real
      fence is 1), locks before it inserts, and a lease is free when `lease_until <= app.current_time()`.
  47. SA:453 (and `transition_run`, `append_event` as the worker calls them): the worker's unit takes `run_lease FOR
      SHARE` and checks the fence before the call; the functions keep their signatures.
  48. SA:463/464: `mark_sent(raw_handle, action_id)`, `record_outcome(raw_handle, action_id, outcome, doc)`; a stale
      fence or a lapsed lease is the handle refusal OC008.
  49. SA:471: `reclaim_leases` is the sweeper's routine with direct grants; it un-claims claimed, unfinished run jobs
      whose lease is not live, takes no lease lock, inserts no recover job and does no permit work.
  50. SA:432: `model_permit(slot, holder, run_id, leased_until)`, one seeded slot, `worker` `sel, upd(all)`, no
      sweeper cell.
  51. BS:550 (replaces erratum 39's forward reference): a tenant quota and a global bound of QUEUED runs (100 each by
      default), the global one through the api-only definer `queued_runs_total()` and soft by the number of
      concurrent admissions; a full queue is an unrecorded 429 with `Retry-After`.
  52. SA:188: the extended lock order of `ops_core/locking.py` (advisory locks, `jobs` claim, `run_lease` … `outbox`,
      `jobs` finish, `idempotency_request`), with SKIP LOCKED and NOWAIT outside it, a fresh-row INSERT ranked at
      its foreign-key parent, and the own-unit tables named.
  53. SA:459: `resolve_invocation` reads `invocation_context` without a lock; `run_lease FOR SHARE` in
      `_resolve_handle` is the one lock, shared by every handle function.
  54. SA:467: `mark_unknown` refuses OC003 unless the caller's fence is current and its lease live, bumps the fence,
      revokes the old fence's handles and returns `(run_state, new_fence)`.
  55. SA:472: `revoke_handles` revokes the handles of the given fence and older ones and never refuses.
  56. BS:405: the nine faults map to eight hooks (`reject_next`, `drop_before_commit`, `lose_after_commit`,
      `timeout_before_accept`, `rate_limit`, `malformed_response`, `receipt_hash_mismatch`, `delay_receipt`) and one
      harness race (concurrent same-key submission, R047).
  57. SA:196-198: "exits the run" means cancelling the job's effects in flight (MCP and model calls; no database unit
      is interrupted), revoking the job's handles and handing the job back with no transition; the job's next owner
      fails a run it finds in RETRIEVING or DRAFTING (resuming it is T20's).
- Earlier debt lines that named T13 and what became of them: the lease, fence, heartbeat and model permit
  (walking-skeleton debt, Plan E debt) are done; reclaim of a crashed handler's job is done (the sweeper's reclaim);
  `reclaim_leases` is done as erratum 49; the raw-handle binding of `mark_sent`/`record_outcome` is done; the six
  remaining BS:405 faults and `lose_after_commit` in the API are done; `model_permit`'s matrix row is done; the global
  queue bound is done; freezing the testclock revision's grantee tuples is done; the `jobs.type` vocabulary is
  enforced (the api-only `resume_input` restriction → T22); bounded retries and the transport path → T22;
  wake-ups and per-tenant polling → T14; pools, reconnects, the API's per-unit lock_timeout, the shared
  connect-and-assert helper, the startup-cleanup closer and the token verifier's injected-fetch exception → T30; the
  untested definer branches → T22; the pre-SENT `STALE_RUN`/`HASH_MISMATCH` envelopes → T47; a zero-orphan
  `skeleton.py keys` case → T32; resuming an investigate run interrupted in RETRIEVING or DRAFTING (today failed as
  interrupted) → T20.
```

3. Under `## Dev database state (2026-10-08)`, append the paragraph:

```markdown
**Update (<date>):** Plan H adds revision 0007. The dev `ops` database stays at 0005 until the owner runs
`uv run python scripts/skeleton.py migrate` (dev profile), which applies 0006 and 0007 together; until then
`skeleton.py up` fails fast because the API, the sweeper, the worker and mcp-write refuse to start without their
revision's relation. 0007 creates `app.model_permit` (one seeded slot), adds the `jobs.type` CHECK (every existing job
has one of the eight types), grants `app_definer` UPDATE on `run_lease.fence`, and re-creates the handle functions
with the fence check; it deletes nothing.
```

4. Under `## Open owner inputs`, replace the first bullet

```markdown
- Migrate the dev database to revision 0006 (`uv run python scripts/skeleton.py migrate`, dev profile), then decide
  errata 35-44 (see "Plan G executed").
```

with:

```markdown
- Migrate the dev database to revision 0007 (`uv run python scripts/skeleton.py migrate`, dev profile; it applies 0006
  and 0007 together), then decide errata 35-44 (see "Plan G executed") and 45-57 (see "Plan H executed").
```

5. In the line that begins `**Repository:**`, replace ``branch `plan-g` (Plan G work on top of `plan-f`,`` with
   ``branch `plan-h` (Plan H work on top of `plan-g`, on top of `plan-f`,`` (the rest of the line is unchanged).

- [ ] **Step 4: Status, history, the runbook and the documents**

`STATUS.md`: append, after two blank lines,

```markdown
## Update — Plan H executed (<date>, branch `plan-h`)

- Plan H (T13: the run lease, fence locking, the heartbeat thread and the fault factory) executed on branch `plan-h`
  (`<base>..<last>`, on top of `plan-g`). The plan is
  `docs/superpowers/plans/2026-10-15-first-slice-h-leases-fences-heartbeat.md`.
- `PYTHONUTF8=1 uv run python scripts/check.py` is `CHECK: GREEN`: pytest `<dev passed> passed, <dev skipped>
  skipped`. `PYTHONUTF8=1 uv run python scripts/check.py --profile test` is `CHECK: GREEN`: pytest `<live passed>
  passed, 21 skipped` (four `slow_live` tests add about 2.5 minutes). `uv run python -I scripts/verify_handoff.py
  --reference-code --manifest --contracts` exits 0.
- **Evidenced** (acceptance matrix `RECORDED_LOCALLY_LIVE` / `IMPLEMENTED_LOCALLY_VERIFIED`): R019, R020, R087, R088
  and R107; R098 extended (unit-level, every service under `PROFILE=test` in the live suite). A stale worker's
  write, mint, release and handle all refuse after a takeover; a takeover waits for an open fenced unit; expiry is
  compared on the database clock after the lock; a resume job waits behind the original job's lease and then writes
  alone; a 25 s blocked loop and a 35 s drafter keep the lease while a forced renewal failure cancels the call and
  revokes the handle; eight workers and the sweeper hammering three runs for 20 s never deadlock and never write
  under an older fence after a newer one; a killed owner's job is reclaimed after expiry and taken at the next fence
  (`reports/leases/`).
- The dev `ops` database needs revisions 0006 and 0007 (an owner input); the API, the sweeper, the worker and
  mcp-write refuse to start until then.
- Deferred, each with its owner in `SESSION_STATE.md`: the permit's idle release rule -> T19; compute accounting and
  per-requester leases -> T29; bounded retries, the AM-13 timeout path and recover jobs -> T22; wake-ups -> T14; the
  asset guard -> T21; checkpoints -> T20/T38; pools and reconnects -> T30. Thirteen errata (45-57) are proposed.
```

`docs/runbooks/leases.md` (new):

````markdown
# Run leases, fences, the heartbeat and the model permit (T13)

Who this is for: whoever runs the worker, reads its logs, or debugs a run that seems stuck. The design is AM-12 in
`SPEC_AMENDMENTS.md` and Plan H (`docs/superpowers/plans/2026-10-15-first-slice-h-leases-fences-heartbeat.md`).

## What holds a run

- **One lease per run** (`app.run_lease`: `owner`, `fence`, `lease_until`). The worker takes it in the same
  transaction that claims a job; a job whose run's lease is held by someone else is not claimed, only moved behind
  the lease (`jobs.available_at`). The first lease of a run has fence 1; every acquisition adds one; a released
  lease has `lease_until = '-infinity'` and keeps its fence.
- **Fenced writes.** Every unit the worker commits for a run starts by locking the lease row `FOR SHARE` and checking
  owner, fence and expiry on the database clock; MCP handles carry the fence they were minted under and die with it.
  A worker that lost its lease writes nothing.
- **The heartbeat** is a thread in the worker with its own database connection. It renews the held lease every
  `OPS_HEARTBEAT_SECONDS` while the event loop stamps signs of life (`OPS_LOOP_STALL_SECONDS`) and the job is within
  `OPS_COMPUTE_BUDGET_SECONDS`. When renewal fails it cancels the job's MCP or model call in flight (never a
  database unit, which finishes and then meets the fence check); the worker revokes the job's handles and hands the
  job back with no state change.
- **Handles live 20-30 s in practice, not 60.** A handle's expiry is capped at the lease's end when it is minted, and
  a renewal does not extend a handle already minted. An MCP call slower than that (the worker's read timeout is 60 s)
  ends with the handle refused (OC008, `INVALID_HANDLE` before SENT) rather than a timeout; per-call minting under the
  renewed lease is T22/T47's (debt list).
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
lease)`, `(the lease expired)`, `(renewals failed until the local deadline)` — each followed by the job being handed
back. Sweeper: `reclaimed N job(s) whose run lease was not live`.

## When something looks stuck

- A job keeps moving its `available_at` forward without being claimed: its run's lease is live under another owner.
  Check that owner's worker; if it is gone, the lease lapses within one lease and the sweeper hands the job back.
- A run ends FAILED with `interrupted; the run was not resumed`: a worker lost its lease (or crashed, or hit the lock
  timeout) during retrieval or drafting, and the job's next owner failed the run rather than leave it holding the
  conversation's slot. Resuming such a run is T20's (the graph's node resume).
- A worker logs repeated `event loop stalled`: something blocks its event loop for longer than the stall gate (a
  synchronous call on the loop). The lease is lost on purpose; fix the blocking call.
- `compute budget spent` on every draft: the model is slower than the budget; the budget is BS:555's 90 s.
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
````

`docs/ARCHITECTURE.md`: insert, immediately before the line `## Where the code will live (not yet written)`, the block:

```markdown
## 5. Leases, fences and the lock order (built in T13)

**Claim.** At most one worker writes for a run at a time, and a worker that has lost the run cannot write anything,
even if it does not know yet.

- **One lease per run, fenced.** The claim and the lease commit together; every write unit locks the lease row first
  and checks owner, fence and expiry on the database clock; MCP handles carry the fence and die with it; the
  definer functions behind both MCP servers check it in one helper (`_resolve_handle`).
- **A heartbeat that cannot be starved and cannot keep a corpse alive.** It runs on its own thread and connection,
  renews only while the event loop shows signs of life and the job is within its compute budget, and when renewal
  fails cancels the job's MCP or model call in flight (never a database unit).
- **One lock order.** `core/src/ops_core/locking.py` lists it; a unit test places every table and every transaction
  in it, and a live stress test hammers it.

| Requirement | What its test shows |
|---|---|
| R019 | A killed owner's job is reclaimed after expiry and taken at fence + 1 |
| R020 | A stale fence's unit, mint, release and handle all refuse after a takeover |
| R087 | A resume job waits behind the original job's lease, then writes alone |
| R088 | A 25 s blocked loop and a 35 s drafter keep the lease; a forced renewal failure cancels and revokes |
| R107 | Interleavings and an 8-connection stress test: no deadlock, no stale write, expiry after the lock |

---

```

`docs/PROJECT_HISTORY.md`: if a section whose heading contains `The leases plan` exists (the controller may commit
the planning story with the review record before execution, as for Plan G), skip the next paragraph. Otherwise insert,
immediately before the heading `## 25. What the process taught`, the block below and renumber that heading to
`## 26. What the process taught` (rename nothing else):

```markdown
## 25. The leases plan put the fence in front of every write, and the heartbeat beside the loop

**Problem.** Plan H adds the run lease (T13): one owner per run, a fence that moves on every takeover, a heartbeat that
renews the lease from its own thread, a local deadline after which the worker starts nothing, a model permit, the
sweeper's hand-back of a dead owner's jobs, one published lock order, and the remaining BS:405 faults. As for Plan G,
a fact sheet with 31 open questions came first and the controller answered them in a brief of 31 rulings that a
fresh author expanded into the plan. The author refined nine rulings against the code and flagged each: the lease row
is locked before it is inserted, because an `INSERT … ON CONFLICT` waits for an in-progress update of the row and a
NOWAIT claim must not wait; the fenced check is a MATERIALIZED CTE so the expiry is compared after the lock, not
before a lock wait; and the re-fence after `mark_unknown` needed a "pending" flag so the heartbeat would not mistake
the owner's own fence bump for a takeover.

**Round 1 (static critic: 1 Blocking, 5 Important, 8 Minor; builder: every task executed, four workarounds, the live
half blocked).** The blocking finding was the cancellation itself. The brief had the heartbeat cancel the whole job
task when the lease was lost; psycopg's `transaction()` sends BEGIN before its first await, so a cancellation landing
there finishes the BEGIN, raises, and never reaches the rollback: the loop connection stays inside a transaction for
good, every later unit becomes a savepoint that only ever releases, and the worker holds its job and lease rows while
looking healthy. The design changed: only effects (the MCP call, the model call, the permit's back-off sleep) run as
cancellable child tasks registered on the lease, a database unit is never interrupted, and the hand-back first checks
that the connection is idle and closes it if not. The other findings were smaller and concrete: three lint and type
rules the gates would have failed on, a waiting acquisition that reported a 10 s lock wait as "busy" so the stress test
could not see it, a stress mix that never committed a re-fence and dropped the brief's "never two owners" check, and a
settings check that let a 10 s lease with a 4 s heartbeat through although the 5 s deadline margin made one slow
renewal fatal. The builder could not run the live half: copying `.env` into the dry-run worktree was refused by the
permission classifier, and that was left for the owner rather than worked around.

**Round 2 (static critic: 0 Blocking, 3 Important, 6 Minor; builder: every dev gate equal to the plan).** Round 1's
fix for the stuck transaction held, but three of its other repairs were wrong: a blocked-loop bound that ignored the
thread's one-second sampling would have failed half the time, a narrowed NOWAIT mapping let a claim racing a first
insert escape as an error, and the "never two owners" monitor compared fences the database hands out only once, so it
could not fail. The bound became the sampling window, both lock statements now share one helper, and the monitor
compares each worker's own belief that it holds the lease with the row the database holds.

**Round 3 (static critic: approve with small fixes, 1 Important).** The end-to-end pass found what three rounds had
missed: a handed-back investigate job whose run was already RETRIEVING or DRAFTING closed without work and left the
run holding its conversation slot for good, so the job's next owner now fails such a run as interrupted, and resuming
it is T20's.
```

Then append to that section (after its last paragraph, before the next `## ` heading) one
`**Problem.**`/`**Change.**` pair per finding the task reviews and the final review recorded (from the SDD ledger), or
the sentence "Execution found nothing the plan had not ruled on." when they recorded none. Later review rounds of this
plan, if any, add their own paragraph before execution, as rounds 1-3 did above.

`README.md`: line 5 is one long line; change its tail with this script (the old and new texts are each part of
that one line; the Python string literals only wrap for width):

```bash
uv run python - <<'EOF'
from pathlib import Path

path = Path("README.md")
text = path.read_text(encoding="utf-8")
old = "durable admission with a scoped Idempotency-Key and the AM-16 router (T12) runs locally**"
new = (
    "durable admission with a scoped Idempotency-Key and the AM-16 router (T12) and fenced run leases with a "
    "heartbeat (T13) run locally**"
)
assert text.count(old) == 1
path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
EOF
```

`worker/README.md`: replace the section from `## Runs (T08)` to the end of the file with:

```markdown
## Runs (T08, T13)

`python -m ops_worker`: polls `app.jobs` every 0.5 s and claims a job together with its run's lease (`FOR UPDATE SKIP
LOCKED`, then the lease `FOR UPDATE NOWAIT`; a busy run's job is deferred behind the lease), health on 127.0.0.1:8070
(`OPS_WORKER_HEALTH_PORT`). Every unit it commits for a run is fenced by the lease; a heartbeat thread with its own
connection renews the lease while the event loop is alive and the job is within its compute budget, and cancels the
job's MCP or model call in flight when renewal fails; the job's final unit closes the job and releases the lease.
`investigate`: read tool on mcp-read → fake draft under the model permit (`MODEL_MODE=fake`, the only route until
T19) → frozen proposal → AWAITING_APPROVAL. `execute`: `create_incident` on mcp-write.
One `ops-worker` token carries both MCP audiences; one handle per call, bound to the lease's fence. Settings:
`OPS_LEASE_SECONDS` (30), `OPS_HEARTBEAT_SECONDS` (10), `OPS_LOOP_STALL_SECONDS` (28), `OPS_COMPUTE_BUDGET_SECONDS`
(90); see `docs/runbooks/leases.md`. LangGraph: T20.
```

`sweeper/README.md` (three replacements; each block is the file's exact lines):

Line 3, replace:

```markdown
Scheduler process (AM-20.1): membership sync, expiry purges; later leases, wake-ups, outbox
```

with:

```markdown
Scheduler process (AM-20.1): membership sync, expiry purges, the hand-back of jobs whose run lease died; later
wake-ups, outbox
```

The "Owns" paragraph (lines 6-7), replace:

```markdown
The membership sync (deactivation of disabled or deleted users, `synced_at`), the per-minute maintenance job rows, the
purge of expired sessions, login state, logout-token ids and idempotency records past their replay window (T12)
```

with:

```markdown
The membership sync (deactivation of disabled or deleted users, `synced_at`), the per-minute maintenance job rows, the
purge of expired sessions, login state, logout-token ids and idempotency records past their replay window (T12), and
the hand-back of jobs whose run lease died with their worker (T13)
```

The "Runs" section (lines 16-20), replace:

```markdown
## Runs (T11)

`python -m ops_sweeper`: every 30 s syncs memberships against the realm, records the sync as this minute's
`sync_memberships` job, purges expired rows; health on 127.0.0.1:8071 (`OPS_SWEEPER_HEALTH_PORT`), ready only while the
last successful sync is younger than 120 s. Leases, wake-ups, the outbox and proposal expiry: T13/T14/T21.
```

with:

```markdown
## Runs (T11, T13)

`python -m ops_sweeper`: every 30 s syncs memberships against the realm, records the sync as this minute's
`sync_memberships` job, purges expired rows and hands back the jobs whose run lease is no longer live (T13); health on
127.0.0.1:8071 (`OPS_SWEEPER_HEALTH_PORT`), ready only while the last successful sync is younger than 120 s.
Wake-ups, the outbox and proposal expiry: T14/T21.
```

- [ ] **Step 5: Final gates**

```bash
PYTHONUTF8=1 uv run python scripts/check.py
PYTHONUTF8=1 uv run python scripts/check.py --profile test
uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts
```

Expected: `CHECK: GREEN` with `930 passed, 133 skipped`; `CHECK: GREEN` with `1042 passed, 21 skipped`; exit 0. Fill
the `<dev passed>`, `<dev skipped>` and `<live passed>` placeholders of Steps 3 and 4 with the printed numbers. Then
`git checkout -- reports/bootstrap reports/auth`; the live run rewrote `reports/admission`, `reports/skeleton` and
`reports/leases`, and Step 6 commits them. Tick this plan's checkboxes (`- [ ]` → `- [x]`) for every step executed.

- [ ] **Step 6: Commit**

```bash
git add handoff SESSION_STATE.md STATUS.md README.md worker/README.md sweeper/README.md docs/ARCHITECTURE.md
git add docs/PROJECT_HISTORY.md docs/runbooks/leases.md reports/admission reports/skeleton
git add docs/superpowers/plans/2026-10-15-first-slice-h-leases-fences-heartbeat.md
# reports/leases/ is written by Step 5's live gate: test_leases_live.py, test_heartbeat_live.py and
# test_lease_stress_live.py each write their file only when all of their tests passed.
if [ -d reports/leases ]; then git add reports/leases; else echo "reports/leases missing: rerun Step 5"; fi
git commit -m "docs: close T13 - handoff records, acceptance rows, errata 45-57, the leases runbook (Plan H)"
```

---

## Self-review (run by the plan's author before execution)

1. **Spec coverage.** T13's instructions: "Lease acquisition FOR UPDATE" → Task 3 (`acquire_lease`, `LOCK_FOR_UPDATE*`);
   "fenced writes FOR SHARE" → Task 3 (`fenced`) and Task 4 (`_resolve_handle`); "clock_timestamp via
   app.current_time()" → every lock statement compares after the lock (Task 3 `ops_core.lease`, Task 4 bodies), proved
   by `test_r107_expiry_is_compared_after_the_lock` and R019's test-clock expiry; "published lock order" → Task 1
   (`core/locking.py` and its test), runbook and ARCHITECTURE in Task 8; "heartbeat on its own thread/connection" and
   "local monotonic deadline" → Task 5 (`Heartbeat`, `Lease.check`); "model_permit with SKIP LOCKED" → Tasks 2 and 5;
   "test-only fault factory for app services" → Task 7. DoD 1 → Task 3 (`test_r020_a_stale_fence_write_aborts`, the
   in-flight variant); DoD 2 → Task 6 (the stress test); DoD 3 → Task 5 (the three `slow_live` tests). Review notes:
   1 (FOR UPDATE from the start, no upgrade) → rulings 4, 9, 28 and `_mark_unknown`'s missing share lock, tested in
   Task 4 (`test_mark_unknown_hands_the_new_fence_to_the_lease` asserts its unit holds `mark_unknown` alone); 2 (the
   re-fence hand-off) → Tasks 3-5 (`begin_refence`/`end_refence`, `fence_moved_by_owner`, Review Focus 2); 3 (lock
   order places the asset guard, memberships, jobs, invocation_context, model_permit, sessions) → Task 1; 4 (the
   liveness and 90 s gates) → Task 5; 5 (`app_definer` may call `pg_advisory_xact_lock(hashtextextended(…, 0))`) →
   Task 2's live test; 6 (messages, decisions, operator_resolutions in the order; the outbox's separate transaction) →
   Task 1's `LOCK_ORDER` (the outbox loop itself is T14's); 7 (revocation through `revoke_handles(run_id, fence)`) →
   Tasks 3 and 4 (the worker has no `revoked_at` cell; every revocation is the definer).
   The six requirement rows, by their expected evidence:
   - **R019** "Kill lease owner; another owner acquires after expiry with incremented fence." →
     `test_r019_a_killed_owners_job_is_reclaimed_and_the_next_owner_fences_higher` (Task 6: the owner's connection is
     closed, the claim stands while live, the test clock passes the lease, the sweeper reclaims, the next owner claims
     at fence + 1, the killed owner's lease writes nothing).
   - **R020** "Old worker attempts commit after fence changes; transaction rejects it." →
     `test_r020_a_stale_fence_write_aborts` and `test_r020_an_in_flight_writer_holds_off_the_takeover` (Task 3, worker
     side), `test_a_handle_is_refused_after_its_fence_moves_and_after_its_lease_expires` and the two
     `test_a_stale_fence_*_sent_*` tests (Task 4, MCP side).
   - **R087** "Resume-job vs original-job race: only the current run fence writes." →
     `test_r087_only_the_current_run_fence_writes` and the deferral in
     `test_the_first_acquisition_takes_fence_1_and_a_live_lease_defers_the_next_job` (Task 3).
   - **R088** "Blocked loop and >30 s fake drafter keep the lease; forced renewal failure cancels the call and revokes
     handles." → the three `test_r088_*` tests (Task 5), at the real defaults.
   - **R098** "Hook routes 404 in default and demo profiles; factories refuse to start without PROFILE=test." →
     `test_the_new_hooks_do_not_exist_outside_the_test_profile[dev|demo]`, the API's
     `test_the_fault_route_does_not_exist_outside_the_test_profile[dev|demo]`,
     `test_faults_belong_to_the_test_profile_and_only_to_it`, `test_the_factory_still_refuses_outside_the_test_profile`
     (Task 7), beside Plan E's.
   - **R107** "Two-connection interleaving and stress tests: stale writes abort, no deadlocks, clock_timestamp-based
     expiry." → Task 3's interleavings (two and three connections, `pg_blocking_pids`), Task 6's stress test (zero
     40P01, zero 55P03 including a waiting acquisition's long wait, fences never backwards, at most one actor
     believing it holds a run and that one the live owner, committed re-fences, no stale event after a newer fence),
     Task 3's
     `test_r107_expiry_is_compared_after_the_lock` and Task 6's R019 (expiry by the database clock).
   The brief's 31 rulings map to tasks in "Rulings" above; every refinement is listed under "Rulings needing
   controller attention".
2. **Placeholder scan.** No undecided placeholder, no "similar to Task N", no "add error handling". The template
   markers `<base>`, `<last>`, `<date>`, `<dev passed>`, `<dev skipped>` and `<live passed>` in Task 8 are defined by
   the commands that print them (Task 1 Step 1b, Task 8 Step 5). `TODO(T14)`, `TODO(T19)`, `TODO(T20)`, `TODO(T21)`,
   `TODO(T22)` and `TODO(T30)` in the new code are ownership markers `docs/CODE_COMMENTS.md` requires, each on the
   debt list.
3. **Type and name consistency.** `Lease(run_id, owner, fence, lease_seconds, started, clock)` is built the same way in
   `acquire_lease`, `test_lease.py`, `test_worker_units.py`, `test_heartbeat.py`, `test_permit.py` and
   `test_grant_deferred.py`; its members (`fence`, `deadline`, `renewed_at`, `held_since`, `lost`, `refencing`,
   `check`, `effect`, `cancel_effects`, `renewed`, `mark_lost`, `begin_refence`, `end_refence`,
   `fence_moved_by_owner`) are the ones the heartbeat, `fenced`, the handlers, `release_lease`, `_mark_unknown`,
   `model_permit`, the stress test and `run_job` call; `Heartbeat.hold(lease)` takes no callback anywhere.
   `persistence.Claimed(job, lease)`, `Deferred(job_id)`, `Unknown(state, fence)` are used with those field names
   everywhere. `mark_sent(conn, *, handle, action_id)` and `record_outcome(conn, *, handle, action_id, outcome)`
   match in `persistence`, `execution.py`, `test_worker_live.py`, `test_fenced_definers_live.py` and the write-path
   unit test; `mark_unknown(conn, run_id, fence)` and `revoke_handles(conn, run_id, fence)` match in the worker, the
   stress test and the fakes;
   `mint_handle(..., fence=...)` in every caller. The SQL signatures in revision 0007 (`mark_sent(text, uuid)`,
   `record_outcome(text, uuid, text, jsonb)`, `mark_unknown(uuid, bigint)` returning `(run_state, new_fence)`,
   `queued_runs_total()`) match `privileges.DEFINER_FUNCTIONS` and the revision's `FUNCTIONS`, `REPLACED`, `CREATED`
   and `RESTORED`. `Renewal` members are the four the heartbeat branches on. `LeaseSettings` fields match
   `settings.leases()`, the worker's `Deps.leases` and the live tests. `FaultKind`'s eight values match `BS405`, the
   incident-sim hot paths and `API_FAULTS`. `QueueFull.message` is read by the 429 handler.
4. **Review Focus.** (1) two first acquisitions → Task 3 `test_two_first_acquisitions_of_one_run_give_one_lease`;
   (2) a renewal meeting its own re-fence → Task 5 `test_a_renewal_that_meets_its_own_refence_retries`; (3) a handle
   near the end of a lease → Task 3 `test_a_handle_is_capped_at_its_lease_and_bound_to_its_fence` and Task 4
   `test_a_handle_is_refused_after_its_fence_moves_and_after_its_lease_expires`; (4) the heartbeat connection dropping
   → Task 5 `test_transient_errors_are_retried_until_the_deadline`; (5) a reclaim racing a live owner → Task 6
   `test_the_reclaim_leaves_a_live_lease_alone` and Task 3's R087 test.
5. **Known risks the executor should watch** (none changes a ruling):
   - Cancellation (review round 1, B1, resolved by design): only effects registered through `Lease.effect` are ever
     cancelled, so psycopg never meets a cancellation inside a unit; `abandon` refuses a connection that is not idle
     and closes it, so the worst case is a restart, never a wedged connection. Shutdown cancels nothing either: it
     sets the stop event and the poll loop finishes its current job (the liveness stamps stop only after it, review
     round 2, m2); only an interpreter-level interrupt (a second Ctrl+C) could cancel the poll task, and the process
     ends then. A unit stuck behind another transaction's lock ends after the loop connection's 10 s `lock_timeout`
     (m1).
   - The slow live tests depend on wall-clock timing on the dev machine (the loop's last stamp can be up to 1 s old
     and the thread samples once a second, so a 25 s block shows as a silence between 23 and about 26 s against the
     28 s gate; the test asserts that window, review round 2, N1). A machine under heavy load could close the stall
     gate; the test then fails loudly rather than passing by luck, and the evidence line records the longest silence
     seen.
   - `test_a_lost_lease_cancels_a_real_mcp_call` runs the real MCP client against a socket that never answers; the
     dry run of round 1's fixes passed it on Windows, but an SDK upgrade that swallowed cancellation would hang it to
     the client's 60 s read timeout (the assertion allows 10 s).
   - The stress test's assertions are statistical in coverage (a random mix over 20 s) but exact in what they check;
     a seeded `random.Random(name)` per actor keeps each actor's choices reproducible, though the interleaving is not.
   - Loading applied revisions by path inside revision 0007 is new in this repository; it relies on those files never
     being edited, which the project already promises (round-3 finding N1 of Plan E) and the downgrade test proves on
     every live run.

## Round 1 changes

Inputs: the controller's rulings on the static review (REVISE: 1 Blocking, 5 Important, 8 Minor) and the dry run (47
steps, 10 DIFFERS, 4 workarounds, the live half blocked). Every ruling is applied in this text; nothing was declined.
Where a finding offered alternatives, the smaller one was taken, as ruled.

- **B1, ruling 19 replaced (Tasks 3, 5).** `Lease.effect(coro)` runs one effect (an MCP call, a model call, the
  permit's back-off sleep) as a child task registered on the lease under its lock; `Lease.cancel_effects()` (thread
  safe) cancels exactly those through `loop.call_soon_threadsafe`; a cancelled effect surfaces as `LeaseLost`, a
  cancellation of the caller itself (shutdown) propagates unchanged. Database units are never registered or
  cancelled. Task 3 writes `effect`/`cancel_effects` and routes the handlers' three calls through them (the
  `lease.check()` before each call moved into `effect`); `handlers.abandon` first checks
  `conn.info.transaction_status is IDLE`, else closes the connection and raises `psycopg.OperationalError`, which the
  poll loop already turns into a non-zero exit. Task 5's `Heartbeat.hold(lease)` lost its `cancel` callback,
  `_lose` calls `cancel_effects`, and `main.run_job` no longer wraps the handler in a task (it catches `LeaseLost`
  only). Tests: `test_lease.py` +3 (an effect starts only while held; a loss from another thread cancels the effect and
  not a concurrent "unit"; stopping the worker is not a loss), `test_worker_units.py` +1 in Task 3 (the non-idle
  `abandon`) and, in Task 5, the effect-cancellation test rewritten plus
  `test_a_loss_during_a_unit_never_interrupts_it`. Erratum 57, ruling 19's text, the Goal, the Architecture, the
  Global Constraints' catch-all note, the runbook, the ARCHITECTURE section, the worker README and the handoff note now
  say "effects only".
- **I1.** `itertools.pairwise` in `locking.follows_order`; `block_the_loop()`, a module-level synchronous helper the
  async test calls (no `noqa`); `2.0 **` in `permit.backoff`.
- **I2.** Resolved by B1: the take and the release are units, the back-off sleep is the one effect, and the `finally`
  releases exactly the slot a take returned. `test_permit.py`: the cancellation test now loses the lease through
  `cancel_effects` mid-draft (release still happens) and `test_a_loss_during_the_backoff_takes_and_keeps_no_permit`
  is new (+1).
- **I3.** `acquire_lease(wait=True)` lets 55P03 propagate; with NOWAIT only the lock statement's 55P03 is `Busy(locked=
  True)` (a first-row INSERT that outlasts `lock_timeout` propagates too). The stress test counts a `Busy(locked=True)`
  from a waiting acquisition as 55P03.
- **I4.** The stress test's third run is EXECUTING with a grant (`approved_run` + `grant_execution`, then its seeding
  lease expired); `mark_unknown` commits there under load (a second UNKNOWN only moves the fence, so re-fences keep
  committing) and the actor hands the new fence to its Lease inside `begin_refence`/`end_refence`. The monitor reads
  `owner, fence, live` and records any sample where two actors hold a run's current fence or a live row's owner is not
  the actor holding its fence; the test asserts none, at least one committed re-fence, and the evidence line says so.
- **I5.** `check_leases` requires `2 × heartbeat + 6 < lease` (`settings.RENEWAL_MARGIN_SECONDS = 6`: SA:195's 5 s plus
  the 1 s tick, kept in `settings` so the settings module imports nothing from the worker); the message is
  "OPS_HEARTBEAT_SECONDS must be less than half of (OPS_LEASE_SECONDS - 6)". The bounds test's low companions moved to
  heartbeat 1 (lease 10 needs it); the unsafe-combination row uses 12 (the old rule's blind spot); a new test pins
  30/10 valid and 10/4 invalid (+1).
- **M1.** `locking.py`'s docstring states that a fresh INSERT's foreign-key check takes FOR KEY SHARE on the parent and
  ranks the insert at the parent; the claim and the two minting units list those parents; the test is renamed
  `test_the_documented_units_are_consistent_with_the_order`, and the docstring says the list is hand-written. Erratum
  52's wording follows.
- **M2** (the smaller alternative). The 20-30 s practical handle lifetime is a debt line (→ T22/T47) and a runbook
  paragraph; minting per call is not done.
- **M3** (both parts). The import-time drift check of revision 0005's line moved into `upgrade()` (Task 4 Edit 5); the
  live round trip now also compares each restored function's `pg_get_functiondef`, ACL, owner and settings with a
  scratch database built straight to 0006 (`built_to_0006`, created and dropped by the test).
- **M4.** `Heartbeat.max_loop_age` records the longest loop silence a tick saw; the DoD-3 blocked-loop test asserts it
  stays below the stall gate and writes it into the evidence line.
- **M5.** The two-first-acquisitions test is stepped: A's claim stays open until `pg_blocking_pids` shows B's insert
  waiting on A, then B defers.
- **M6.** The heartbeat's connect passes `connect_timeout=5`.
- **M7.** `test_a_lost_lease_cancels_a_real_mcp_call` (Task 5, +1): the real `HttpMcpCaller` against a local socket
  that never answers, cancelled through the lease, ends as `LeaseLost` within 10 s.
- **M8.** The per-tenant scan in `queued_runs_total` is in the runbook and on the debt list (→ T29).
- **Dry run.** WA-1 to WA-4 are folded in (WA-2: 0007's one-element `FUNCTIONS` tuple is written, and quoted by Task
  4 Edit 4, in its formatted one-line form; WA-3 per I1). Every code block is now stable under `ruff format`
  (`lease.RENEW`, `release_lease`'s signature, `tool_events`, `execution.py` Edit 3, the Task 5 assertion, the stress
  `Actor.__init__`, the new `CountingLease` call, and 0007's `_applied`, which needed two blank lines before it); the
  only text `ruff format` still rewrites is Task 4's three replace-all lines in `test_definers_write_path_live.py`,
  which the plan now says and nothing later quotes. Red steps whose module fails to collect are split into separate
  runs with pytest's real output (`N errors in`; Tasks 5, 6, 7), and the T2 S2 and T4 S1 reasons are the observed
  ones. Task 8: the TODO grep is exact (`TODO(T13` prints nothing in code; 0007 holds one, the verbatim quote of
  0005's line, now the public `GRANT_TODO_0005`, which the unit test uses instead of the literal), the PROJECT_HISTORY
  section text is given in full, `sweeper/README.md`'s line 3, "Owns" paragraph and "Runs" section are exact blocks,
  the README edit is a script, `reports/leases` is added only if Step 5's live gate wrote it (and the three tests that
  write it are named), the line cites are corrected (148-158; r105 25-26 and 209-214), and the BACKLOG note is
  appended after T13's existing notes.
- **Counts.** Dev passed/skipped after each task: 857/104, 863/109, 880/119, 887/124, 905/128, 910/132, 926/133
  (+1 in Task 1, +4 in Task 3, +3 in Task 5 against the first version); live 951, 978, 990, 1012, 1021, 1038, always
  with 21 skipped. Checked on scratch copies of 03e2636 with every step applied by script: the splice check prints
  "not found: 0"; each task's dev gate gives exactly these counts (plus the 12 tests that need `.git` and the
  reference zip, as in the dry run); `ruff check` and `mypy` are clean after each task; and every red step's
  "Expected" line was reproduced.

## Round 1 open points

- **The live half is still unproven.** Nothing here touched a database. Each of these new or changed live
  behaviours needs its first run in the main checkout:
  - the stepped first-acquisition race;
  - the stress test's EXECUTING run and its committed re-fences (the grant needs a fresh membership sync, as in
    `test_fenced_definers_live.py`), the two-owner monitor, and the 55P03 accounting;
  - `built_to_0006` (CREATE DATABASE as the superuser, revisions 0001-0006 on an empty database whose roles already
    exist);
  - the DoD-3 evidence line with `max_loop_age`.

  The dry run's `.env` blocker (the permission classifier refused copying it into a worktree) is for the owner to
  decide.
- **One unit test leans on the MCP SDK's cancellation behaviour.** `test_a_lost_lease_cancels_a_real_mcp_call` passed
  on Windows in the scratch run. If a future SDK swallowed cancellation, it would fail after 10 s rather than hang.
- **The rulings changed by round 1 are recorded in "Rulings" (19, 20, 21) and erratum 57.** The controller has
  decided them, so they are not repeated under "Rulings needing controller attention". The owner still decides the
  errata.
- **Not taken, as ruled.** The static review also proposed:
  - an abandon-time permit release keyed by holder and run (I2's second fix; ruled resolved by B1);
  - a fake-connection test that cancels at every await point of a full `handle()` run (B1's suggestion; the controller
    named three tests instead, which are in).

  Neither is in the plan. Either can be added in a later round if the controller wants it.

## Round 2 changes

Inputs: the controller's rulings on the round-2 static review (REVISE small: 0 Blocking, 3 Important, 6 Minor) and
the round-2 dry run (41 steps OK, every dev gate equal to the plan, cosmetic line cites and one long README line).
Every ruling is applied; nothing was declined.

- **N1 (Task 5 Step 3).** The blocked-loop test asserts `BLOCK_SECONDS - TICK_SECONDS - STAMP_SECONDS <
  max_loop_age < loop_stall_seconds` (23 < age < 28), with both sampling periods imported from
  `ops_worker.heartbeat`. A comment says why the bound is not `BLOCK_SECONDS <= max_loop_age`: the thread samples once
  per tick, after a last stamp that may already be a stamp period old.
- **N2 (Task 3 Step 3).** `persistence._lock_row` is the one helper for both of the acquisition's lock statements,
  including the one after the first-row INSERT. With NOWAIT, 55P03 becomes `Busy(locked=True)`; only `wait=True` lets
  it propagate. New unit test: `test_a_held_row_after_the_first_insert_is_busy_too`, in `test_lease.py` (+1). It uses
  a fake connection whose second lock raises `LockNotAvailable`: `Busy(locked=True)` without waiting, raised with
  `wait=True`. The stress test's dead `Busy(locked=True)` branch is gone.
- **N3 (Task 6 Step 3).** The monitor first takes, per run, the actors whose own Lease passes its local check (not
  lost, before its local deadline). It then reads the rows in the same sample. It records a violation when:
  - more than one actor believes it holds a run; or
  - the one that does is not the owner of a live row at its fence.

  The row's fence may also be one higher than the actor's fence, when that actor's own re-fence committed between
  the two reads. The module docstring, the evidence line, ruling 21's text, the self-review and the R107 acceptance
  note now say exactly that.
- **m1 (Task 3 Step 4).** The worker's loop connection runs `main.LOOP_LOCK_TIMEOUT` (`SET lock_timeout = '10s'`)
  right after it connects. A unit that hits the timeout raises 55P03, which `run_forever` already logs as transient.
  The job keeps its claim, its lease is no longer renewed, and the sweeper hands the job back. The runbook's "When
  something looks stuck" says so, including the one exception: inside drafting and freezing, the run is failed
  instead, as for any error there.
- **m2 (Task 5 Step 2).** The liveness stamps have their own stop event (`stamps_stop`) and stop only after the poll
  loop has ended. A job that a shutdown lets finish therefore never looks stalled. The self-review risk now says
  shutdown cancels nothing.
- **m3 (Task 5 Step 2).** The heartbeat connection adds TCP keepalives (`keepalives_idle=10`, `keepalives_interval=5`,
  `keepalives_count=2`) beside `connect_timeout=5`, plus `SET statement_timeout = '5s'` beside the lock timeout. The
  two timeouts are SET because the conninfo's `options` already carries the time zone. Each failure is a psycopg
  error, which the tick treats as transient.
  `test_transient_errors_are_retried_until_the_deadline` now scripts a `QueryCanceled` (a statement timeout) as one
  of its two errors.
- **m4 (Task 5 Step 1).** `test_the_settings_margin_is_the_deadline_margin_plus_one_tick` pins
  `RENEWAL_MARGIN_SECONDS == DEADLINE_MARGIN_SECONDS + TICK_SECONDS`. It is in `test_heartbeat.py` (+1), the first
  module that can import all three.
- **m5 (Task 8 Step 4).** The worker README's "Runs" paragraph is rewrapped after "on mcp-write." and again after
  "Settings:". Every line is within 120 characters.
- **m6 (Task 4 Step 4).** Scratch databases use `SCRATCH_PREFIX = "r006_"`. Inside the same try/finally,
  `built_to_0006` first drops every leftover matching `r006\_%` as the superuser. Its `finally` uses `DROP DATABASE IF
  EXISTS`, because the create itself may be what failed.
- **Line cites.** All of the dry-run table's cites are corrected, each as the file stands when its step runs:
  - privileges 157-159;
  - test_migrations_and_persistence 149-158;
  - test_mcp_write_live 85-89, and its docstring at 279 / 277-279 as Task 3 left it;
  - execution.py 29-31;
  - test_definers_write_path_live Edit 8 463-473;
  - drafting.py 9-13 and 56-62;
  - store.py 351, 357-362 and 1016-1017, as Task 6 left it.

  Two over-long prose lines that round 1 left in the self-review and in "Round 1 changes" are rewrapped too.
- **PROJECT_HISTORY.** The Task 8 block gains a round-2 paragraph after round 1's.
- **Counts.** Dev passed/skipped after each task:

  | Task | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
  |---|---|---|---|---|---|---|---|
  | Dev | 857/104 | 863/109 | 881/119 | 888/124 | 907/128 | 912/132 | 928/133 |
  | Live (21 skipped) | — | 951 | 979 | 991 | 1014 | 1023 | 1040 |

  Against round 1 that is +1 from Task 3 (N2) and +1 more from Task 5 (m4).

  Checked on one archive copy of 03e2636, applied task by task with `ruff format --check` and then `ruff format`
  between tasks, then `ruff check`, mypy and the dev pytest after each task:
  - the formatter changed nothing except the three Task 4 lines the plan declares (and, in Task 7, two blank lines
    the checking tool's own "insert before" adds, not the plan);
  - ruff and mypy were clean after every task;
  - pytest gave exactly the counts above, plus the 12 tests that need `.git` and the reference zip;
  - the red steps of Tasks 3 and 5 reproduce as written (`3 errors in`; `2 errors in`, then `8 failed, 3 passed`).

  The splice check prints "not found: 0".

## Round 2 open points

- **The live half is still unrun.** The new and changed live behaviour needs its first run in the main checkout:
  - the N1 window;
  - the N3 monitor under load;
  - the leftover sweep in `built_to_0006`;
  - the loop connection's lock timeout.

  As before, `.env` was not copied anywhere.
- **The N3 check assumes the clocks agree.** It relies on the database clock and the monotonic clock running
  together during the stress test. That holds because no test moves the test clock while it runs (R019 resets its
  offset in `finally`). If a future test moved the clock concurrently, the check would report a false violation, not
  miss a real one.
- **A lock timeout inside drafting or freezing fails the run.** A 55P03 from the loop connection's new lock timeout
  in those units fails the run through the existing `except Exception` (the same as any database error there). It does
  not hand the job back. This is today's error rule, recorded in the runbook. A finer rule (hand back on 55P03) would
  be T22's retry work.

## Round 3 changes

Inputs: the controller's rulings on the round-3 static review (approve with small fixes: 0 Blocking, 1 Important, 6
Minor) and the round-3 dry run (clean; two Files-header cites, one SESSION_STATE line, unstated append separators).
Every ruling is applied; nothing was declined.

- **I1 (Task 3 Step 4; the alternative fix).**
  - When `handlers.investigate` finds its run in RETRIEVING or DRAFTING, a previous holder was interrupted (a lost
    lease, a crash, a lock timeout). In its first fenced unit it moves the run to FAILED through `transition_run`, with
    `detail={"message": INTERRUPTED}` (`"interrupted; the run was not resumed"`, `TODO(T20)`), and the job then
    finishes as usual. This frees the conversation slot instead of leaving the run active for good.
  - Unit test `test_an_interrupted_run_is_failed_not_left_active[RETRIEVING|DRAFTING]` in `test_worker_units.py`
    (+2).
  - The live R088 renewal-failure test, which already ends with the job handed back, now expires the thief's lease,
    runs the job again and asserts the run is FAILED. Its evidence line says so.
  - A new debt line hands resuming such a run to T20, and the SESSION_STATE block carries it too.
  - The false sentences are corrected:
    - the `LeaseLost` and drafting comments in `investigate`;
    - `abandon`'s docstring;
    - the worker-units module docstring;
    - erratum 57 here and in the SESSION_STATE block;
    - ruling 19;
    - the m1 runbook paragraph, plus a new runbook entry for the `interrupted` message;
    - the sweeper's reclaim docstring.
- **m-a (Task 6 Step 3).** `believers` records each actor's `refencing` flag. The monitor allows the row's fence to be
  one higher than the actor's only for an actor that was re-fencing when the beliefs were sampled.
- **m-b.** Ruling 16 now names the heartbeat connection's `connect_timeout`, keepalives and both 5 s timeouts. Ruling
  19 names the loop connection's 10 s `lock_timeout` and the interrupted-run rule.
- **m-c (Task 5 Step 2).** The `connector` docstring now says:
  - keepalives notice an idle half-open connection in about 20 s on Linux, and about 60 s on Windows, where libpq
    ignores `keepalives_count`;
  - neither keepalives nor `statement_timeout` bound a renewal sent to a vanished peer;
  - the local deadline does bound it.
- **m-d (Task 4 Step 4).** The leftover sweep:
  - drops only `SCRATCH_PREFIX` databases with no connection in `pg_stat_activity`;
  - uses `DROP DATABASE IF EXISTS` without FORCE;
  - builds its match from the constant (`starts_with(datname, %s)`).
- **m-e (Task 5 Step 2).** `connector()` closes the new connection and re-raises if either SET fails. The Global
  Constraints' catch-all note names this `except BaseException`.
- **m-f.** `acquire_lease`'s docstring wrap is fixed. The PROJECT_HISTORY round-2 paragraph is cut to three sentences,
  and a one-sentence round-3 paragraph follows it.
- **Dry run.**
  - Files-header cites: `test_migrations_and_persistence.py:399-403` and `test_api_admission.py:22-23`.
  - The SESSION_STATE line is broken before "wake-ups".
  - Every append instruction now names its separator: "after two blank lines". The STATUS.md section follows the same
    rule; markdown renders the same either way.
  - Four lines over 120 characters that these edits created are rewrapped. One of them was in the sweeper module's
    docstring.
- **Counts.** Two more tests than round 2 from Task 3 on (I1's parametrised test):

  | Task | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
  |---|---|---|---|---|---|---|---|
  | Dev | 857/104 | 863/109 | 883/119 | 890/124 | 909/128 | 914/132 | 930/133 |
  | Live (21 skipped) | — | 951 | 981 | 993 | 1016 | 1025 | 1042 |

  The red steps of Tasks 4 and 5 now read `13 failed, 7 passed` and `10 failed, 3 passed`.
- **How this was checked.** I applied the plan task by task to one archive copy of 03e2636, with `ruff format
  --check` and then `ruff format` between tasks, and ran `ruff check`, mypy and the dev pytest after each task:
  - the formatter changed only the three declared Task 4 lines (plus, in Task 7, the two blank lines my own tool's
    insert step adds);
  - ruff and mypy were clean;
  - pytest gave the counts above, plus the 12 tests that need `.git` and the reference zip;
  - the red steps of Tasks 3, 4 and 5 reproduced;
  - the splice check prints "not found: 0", and no plan line is over 120 characters.

## Round 3 open points

- **The live half is still unrun.** Its first runs belong to the main checkout:
  - the R088 test's re-run of the handed-back job;
  - the tightened monitor under load;
  - the connection-aware leftover sweep;
  - the heartbeat connection options.
- **A run interrupted mid-investigation now ends FAILED.** Resuming it from where it stopped is T20's, on the debt
  list. Until then a user whose investigation was interrupted (a worker crash, a lost lease) sees it fail and asks
  again.

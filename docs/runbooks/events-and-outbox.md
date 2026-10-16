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
  `action.conflict`, `run.escalated` or `run.abandoned_unverified`, it also writes one `app.outbox` row in the same
  transaction, addressed to the run's requester, channel `local`, with the dedup key `run_id:type:local:requester`.
  A replayed writer adds no second row. Today `record_outcome` emits the first three (a CONFLICT escalates the run
  through `action.conflict`); `run.escalated` and `run.abandoned_unverified` have no emitter until T22.
- **Delivery is the sweeper's**, every tick (30 s), one tenant after another: claim the tenant's due rows (`FOR UPDATE
  SKIP LOCKED`, lease `OPS_OUTBOX_LEASE_SECONDS`), hand each to the sink outside any transaction, record the result
  in its own unit, then the next tenant.
  The v1 sink is a log line (`notification delivered: type=… run=… outbox=… recipient=<hash> …`): nothing leaves the
  machine. Slack is T39.
- **Failure.** A failed delivery is `retrying` with `leased_until` pushed out by `min(cap, base × 2^(attempts−1))`
  plus up to 25 % jitter; the `OPS_OUTBOX_MAX_ATTEMPTS`-th failure is `dead_letter`. A dead letter gets one
  `notification.failed` event on its run (`code`, `message`, `outbox_id`) in a separate transaction, opened by an
  advisory lock on the outbox id and followed by a re-check, so a second sweeper waits and then finds the event;
  every tick re-checks for dead letters still lacking it. The run's state is never touched by delivery.
- **A sink that crashes on a row** (any exception but the sink's refusal: a bug, a payload it cannot render) is
  caught at the sink boundary: the log says `notification delivery crashed: type=… run=… outbox=… attempt=n of m
  (retrying|dead_letter)` with the traceback, and the row is recorded as a failed attempt, exactly like a refusal
  (backoff, dead letter at the cap). The batch's other rows, the later tenants and the announcements go on.
- **A sweeper that dies mid-delivery** (killed, or its database connection lost) records nothing for the row it was
  delivering: the row keeps its counted attempt and is claimed again when its lease ends, and once its attempts
  reached `OPS_OUTBOX_MAX_ATTEMPTS` the next claim dead-letters it and the tick announces it. A database error during
  delivery logs `sweeper tick failed` (a transient connection error logs `transient database error; the loop
  continues` instead, and a lost connection ends the process) after the minute's record and the wake-up sweep have
  run.
- **At least once.** A delivery slower than its lease, or a sweeper that dies after the sink but before the result,
  is delivered again later (BUILD_SPEC §2: "At-least-once dispatch can occur").

## Wake-ups

- **A wake-up is a job committed with the event that needs it**: the investigate job with the run, the execute job
  with the approving decision, the reply job with the reply. The worker polls every 0.5 s per tenant; there is
  no LISTEN/NOTIFY (erratum 64).
- **A released lease makes the run's deferred jobs due at once**: a job a claim moved behind a busy lease no longer
  waits for that lease's old end once its holder releases it. A job delayed beyond that end on purpose (a re-queue
  backoff) keeps its time.
- **The sweep re-arms a lost wake-up.** A run in QUEUED whose investigate jobs are all done, or in APPROVED whose
  execute jobs are all done, for longer than `OPS_WAKEUP_GRACE_SECONDS`, gets its newest job of that type reopened
  (the same row: its dedup key is the wake-up's identity); the re-arm checks again, on the row it takes, that the job
  is still done, past the grace, the newest of its type and below the cap, and that the run still waits without a
  cancellation. A run whose cancellation was requested is never re-armed. A job already claimed
  `OPS_WAKEUP_MAX_ATTEMPTS` times is not re-armed; the sweeper logs `wake-up not re-armed: …` every tick instead.
  AWAITING_INPUT (T20) and OUTCOME_UNKNOWN or ESCALATED (T22) are not swept yet.
- **A refused grant is re-dispatched.** When `grant_execution` refuses for good (an inactive membership, a missing
  approval), the worker finishes the execute job and the run stays APPROVED, so the sweep re-arms the job each grace
  until the cap. No grant follows a refusal that stays a refusal; a refusal that clears in time is executed. Moving
  such a run out of APPROVED is T21's.
- **Finished maintenance rows** (`sync_memberships`, `deliver_outbox`, `sweep_wakeups`) older than
  `OPS_MAINTENANCE_RETENTION_HOURS` are deleted; a run's jobs never are (a restrictive policy holds the sweeper's
  DELETE to finished maintenance rows).

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
  execute job, a grant refused for good: an inactive membership, an approval no longer active; a stale membership is
  different, it re-queues the job instead of finishing it). Today there is no operator remedy for such a run: no
  revision or decision path exists for these runs yet (T21 adds revision and BLOCKED_REVIEW). What an operator can
  observe is that log line, once per tick.
- **An append is refused with OC006**: the payload carries a key the event schema does not define, or a `status` on
  a non-destination type. The writer, not the database, is wrong.

## Test-profile fault hook (`PROFILE=test` only)

`outbox_sink_fail` (`ops_core.testing.faults.FaultKind.OUTBOX_SINK_FAIL`): the next delivery of a `LogSink` built
with a test-profile `Faults` fails. The sweeper has no route to arm it; the live tests build the sink themselves
(`tests/e2e/test_outbox_live.py`).

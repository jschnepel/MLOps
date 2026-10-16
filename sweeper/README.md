# sweeper

Scheduler process (AM-20.1): membership sync, expiry purges, the hand-back of jobs whose run lease died, the
notification outbox's delivery and the wake-up sweep; later proposal expiry

## Owns
The membership sync (deactivation of disabled or deleted users, `synced_at`), the per-minute maintenance job rows, the
purge of expired sessions, login state, logout-token ids and idempotency records past their replay window (T12), the
hand-back of jobs whose run lease died with their worker (T13), the outbox's leased delivery with its retries, dead
letters and `notification.failed` events, the re-arming of lost wake-ups and the purge of finished maintenance rows
(T14)

## Trusts
The realm's user listing through `ops-view-users` (read-only) and its own `sweeper` grants

## Never
Reactivates a membership; grants, decides, transitions a run or writes an event (`append_event` only for a dead
letter's `notification.failed`, its one event); reaches either sim or any external channel (the sink is a log line)

## Runs (T11, T13, T14)

`python -m ops_sweeper`: every 30 s syncs memberships against the realm, records the sync as this minute's
`sync_memberships` job, purges expired rows, hands back the jobs whose run lease is no longer live (T13), delivers
the outbox tenant by tenant and re-arms lost wake-ups (T14, recorded as `deliver_outbox` and `sweep_wakeups` jobs);
health on 127.0.0.1:8071 (`OPS_SWEEPER_HEALTH_PORT`), ready only while the last successful sync is younger than
120 s. Settings and what to look at: `docs/runbooks/events-and-outbox.md`. Proposal expiry: T21.

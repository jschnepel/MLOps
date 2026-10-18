# sweeper

Scheduler process (AM-20.1): membership sync, expiry purges, the hand-back of jobs whose run lease died; later
wake-ups, outbox

## Owns
The membership sync (deactivation of disabled or deleted users, `synced_at`), the per-minute maintenance job rows, the
purge of expired sessions, login state, logout-token ids and idempotency records past their replay window (T12), and
the hand-back of jobs whose run lease died with their worker (T13)

## Trusts
The realm's user listing through `ops-view-users` (read-only) and its own `sweeper` grants

## Never
Reactivates a membership; grants, decides, transitions a run or writes an event (`append_event` only for its own
maintenance events); reaches either sim

## Runs (T11, T13)

`python -m ops_sweeper`: every 30 s syncs memberships against the realm, records the sync as this minute's
`sync_memberships` job, purges expired rows and hands back the jobs whose run lease is no longer live (T13); health on
127.0.0.1:8071 (`OPS_SWEEPER_HEALTH_PORT`), ready only while the last successful sync is younger than 120 s.
Wake-ups, the outbox and proposal expiry: T14/T21.

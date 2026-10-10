# sweeper

Scheduler process (AM-20.1): membership sync, expiry purges; later leases, wake-ups, outbox

## Owns
The membership sync (deactivation of disabled or deleted users, `synced_at`), the per-minute maintenance job rows, the
purge of expired sessions, login state, logout-token ids and idempotency records past their replay window (T12)

## Trusts
The realm's user listing through `ops-view-users` (read-only) and its own `sweeper` grants

## Never
Reactivates a membership; grants, decides, transitions a run or writes an event (`append_event` only for its own
maintenance events); reaches either sim

## Runs (T11)

`python -m ops_sweeper`: every 30 s syncs memberships against the realm, records the sync as this minute's
`sync_memberships` job, purges expired rows; health on 127.0.0.1:8071 (`OPS_SWEEPER_HEALTH_PORT`), ready only while the
last successful sync is younger than 120 s. Leases, wake-ups, the outbox and proposal expiry: T13/T14/T21.

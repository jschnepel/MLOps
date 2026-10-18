# asset-sim: the synthetic asset and alert API behind mcp-read (T16)

Who this is for: whoever runs asset-sim, reads an asset tool's answer, or debugs an `UNAVAILABLE`, `NOT_FOUND` or
`UPSTREAM_INVALID` from mcp-read. The design is SA:78, SA:555 (AM-20.7 item 6) and BS:405 in the specification, and
Plan M (`docs/superpowers/plans/2026-10-18-first-slice-m-read-tools-asset-sim.md`, rulings 4-6 and 8-10).

## What it is

A FastAPI service on `127.0.0.1:8091` (`OPS_ASSET_SIM_PORT`), the first of the skeleton's seven processes. It has no
database and no clock: it reads `data/corpus/assets.json` (authored, under corpus-1's lock) and `data/corpus/meta.json`
(generated: the tenant UUIDs and the alerts' uuid5 IDs) once at start, refuses to start if an alert's severity, kind
or `raised_at` is malformed, and answers every request as a function of those files, the forwarded tenant and the
forwarded instant. corpus-1 is never changed by it: T41 labels against that version.

## Who may call it

Only mcp-read, with its own workload token: `ops-mcp-read`'s client-credentials token (audience `asset-sim`, `azp`
`ops-mcp-read`, `typ` `Bearer`), never the worker's token and never the invocation handle. A genuine token of another
audience or client (the worker's, mcp-write's, a persona's) is 403 `FORBIDDEN`; a missing, expired or otherwise
refused token is 401 `UNAUTHENTICATED` with `WWW-Authenticate: Bearer`. Every request carries the context mcp-read read
from `app.asset_scope` for the handle:

| Header | Value |
|---|---|
| `X-Ops-Tenant-Id` | the run's tenant UUID |
| `X-Ops-As-Of` | the database instant to answer at (`app.current_time()` after the lease lock), an RFC 3339 UTC instant |

An instant, in a header or a query parameter, must look like `YYYY-MM-DDTHH:MM:SS[.fraction]` followed by `Z` or
`+00:00`: no other offset, no space for the `T`, no basic format, no hour-only form. A missing or malformed header or
query parameter is 400 `INVALID_INPUT`, with a body that never echoes the request. So is an alerts request whose
`limit` is outside 1-100, whose `start_at` is not before `end_at`, or whose cursor is not 1-200 characters.

## Routes

- `GET /assets/{asset_id}` → `{"asset_id", "asset_type"}` (mcp-read passes the type to the procedure search).
- `GET /assets/{asset_id}/status` → `get_asset_status`'s data.
- `GET /assets/{asset_id}/alerts?start_at=…&end_at=…&limit=1..100[&cursor=…]` → `get_recent_alerts`'s data.

An asset of another tenant and an asset that does not exist get the same 404 `NOT_FOUND` "no such asset": the forwarded
tenant decides, and nothing tells the two apart. So does an id that is not shaped like an asset id.

## The rules

- **Alerts.** `alert_id` is `meta.json`'s uuid5; `occurred_at` is `raised_at`; `code` is `kind`; `message` is
  "Synthetic <severity> alert: <kind with spaces> on <asset name>."; `revision` as authored.
- **Status as of T** (T = `X-Ops-As-Of`). `state` is `warning` when one of the asset's alerts of severity `warning`
  or `critical` was raised in `[T - 24 h, T]`, else `normal`; `revision` is the highest revision among its alerts
  raised at or before T, or 1; `observed_at` is T; `data_source` is `synthetic`. `unavailable` comes only from the
  test-profile fault hook.
- **Alerts of an interval.** `start_at <= occurred_at < end_at` and `occurred_at <= T` (no alert from the future),
  ordered by `(occurred_at, alert_id)`, `limit` per page. `next_cursor` is set exactly when alerts remain; it is a
  76-character unpadded base64url token holding the last alert's position and the SHA-256 of `(tenant, asset,
  start_at, end_at)`, so a cursor presented for another tenant, asset or interval is 400. Each cursor has one
  spelling: padding, characters outside the base64url alphabet, a wrong length or version, or an instant out of range
  is the same 400, never a 500.

At the stated instants (corpus-1):

| Asset | at 2026-10-16T12:00Z | at 2026-10-06T00:00Z | at 2026-10-06T12:00Z |
|---|---|---|---|
| A17 (alpha pump; seal leaks 10-05T14:00Z r1, 10-06T08:30Z r2) | `normal`, revision 2 | `warning`, revision 1 | `warning`, revision 2 |
| B22 (beta pump; vibration 10-05T11:20Z r1) | `normal`, revision 1 | `warning`, revision 1 | `normal`, revision 1 |

## Running and looking at it

`uv run python scripts/skeleton.py up` starts it with the others; `status` shows its readiness (`/health/ready` is 200
once the realm's signing keys are loaded). To look at an answer by hand you need an `ops-mcp-read` token, which only
the secret file `kc_client_secret_ops_mcp_read` can mint: do that in a script that reads the file, never on a command
line. The live tests do it (`tests/e2e/test_asset_sim_live.py`).

## Fault hooks (test profile only)

Under `PROFILE=test`, `POST /internal/faults/{kind}` with `{"count": n}` (and `"seconds"` for the slow one), authorised
by mcp-read's token, arms one of the four faults asset-sim consumes: `asset_unavailable` (the next status answers
`unavailable`), `drop_before_commit` (the next request is 503), `malformed_response` (the next answer is not the
contract's) and `timeout_before_accept` (the next request waits `seconds`, then 503). In the dev and demo profiles the
route does not exist (`Faults` refuses to be built there).

## When something looks wrong

- **`get_asset_status` or `get_recent_alerts` answers `NOT_FOUND`**: the run's asset is not one of its tenant's in `assets.json` (the admission does not
  tie a run's asset to its tenant yet, T21; an alpha run naming B22 gets exactly this). `search_procedures` does not fail on it: it proceeds with the caller's
  `asset_type`, or none.
- **mcp-read answers `UNAVAILABLE`**: asset-sim is down, slower than mcp-read's 10 seconds (one budget for fetching
  its token and asking), answering 5xx, or refusing mcp-read's token with a 401 (its log shows it).
- **mcp-read answers `UPSTREAM_INVALID`**: asset-sim's answer failed the tool-result contract or named another asset or
  interval, a status carried an instant other than the one asked, an alerts page held more alerts than asked for, or
  asset-sim answered an HTTP status mcp-read has no meaning for (403 when its token lacks the `asset-sim` audience, or
  a 400); in the test profile, check for an armed `malformed_response`.
- **asset-sim will not start**: a data file is malformed (the message names the rule, never a value), or the realm's
  keys cannot be loaded.

## Not here yet

asset-sim's own `tests/` directory and Dockerfile, packaging `data/corpus/` for a container, and the network test that
only mcp-read can reach it (T30); recording a status observation for the grant's freshness check (T21).

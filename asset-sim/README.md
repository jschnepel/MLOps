# asset-sim

Synthetic asset/alert API

## Owns
Deterministic status and alerts for corpus-1's six assets (`data/corpus/assets.json` and `meta.json`, read once at
start and never changed), derived by fixed rules under the instant mcp-read forwards (T16)

## Trusts
Only mcp-read's workload token (aud `asset-sim`, azp `ops-mcp-read`) and the tenant and instant it forwards from
`asset_scope`; it applies its own tenant filter

## Never
Any write; any other caller; an invocation handle; a clock of its own

## Runs (T16)

`python -m ops_asset_sim` on 127.0.0.1:8091 (`OPS_ASSET_SIM_PORT`), started first by `scripts/skeleton.py up`;
mcp-read reaches it at `OPS_ASSET_SIM_URL` (default `http://127.0.0.1:8091`). Routes: `GET /assets/{asset_id}` (the
asset's type), `GET /assets/{asset_id}/status` and
`GET /assets/{asset_id}/alerts?start_at=…&end_at=…&limit=…[&cursor=…]`, each with `X-Ops-Tenant-Id` (the run's tenant
UUID) and `X-Ops-As-Of` (the database instant to answer at). An asset of another tenant and an unknown asset get the
same 404. The rules (`ops_asset_sim.data`):

- an alert's `alert_id` is `meta.json`'s uuid5, `occurred_at` its `raised_at`, `code` its `kind`, `message`
  "Synthetic <severity> alert: <kind in words> on <asset name>.", `revision` as authored;
- an asset's status as of T: `warning` when one of its `warning` or `critical` alerts was raised in `[T - 24 h, T]`,
  else `normal`; `revision` the highest among its alerts raised at or before T, or 1; `observed_at` T;
  `data_source` `synthetic`;
- alerts: `start_at <= occurred_at < end_at` and `occurred_at <= T`, ordered by `(occurred_at, alert_id)`, one page
  of `limit`, with a cursor bound to the tenant, the asset and the interval.

Fault hooks (`POST /internal/faults/{kind}`: `asset_unavailable`, `drop_before_commit`, `malformed_response`,
`timeout_before_accept`) exist only under `PROFILE=test`. See `docs/runbooks/asset-sim.md`.

# api

FastAPI: sessions, admission router, decisions, SSE, health

## Owns
Browser sessions, admission, decisions through definer functions, SSE projections

## Trusts
Keycloak tokens; PostgreSQL role `api`

## Never
Updates `runs.state`; inserts audit rows directly; reaches either sim

## Runs (T08, T11, T12)

`python -m ops_api` on 127.0.0.1:8000 (`OPS_API_PORT`). Identity: bearer persona tokens (`aud ops-api`, `azp
ops-dev-direct`) or the browser session cookie (T11), resolved to a tenant and roles through current memberships on
every request. Endpoints: `/api/v1/me`, `POST /api/v1/conversations`, `POST /api/v1/conversations/{id}/messages`
(the AM-16 admission router: 202 for a run, 200 for a clarification or a status answer, 409, 422, 429),
`POST /api/v1/runs/{id}/clarifications` (202), `GET /api/v1/runs/{id}`, `GET /api/v1/proposals/{id}`,
`POST /api/v1/proposals/{id}/decisions` (independent reviewer, exact revision and hash, first decision wins),
`GET /api/v1/runs/{id}/events`, and the `/auth/*` routes. Every `/api/v1` mutation needs an `Idempotency-Key`
header (8-128 visible ASCII characters); the same key and request replay the recorded answer, the same key with
another request is 409 `IDEMPOTENCY_CONFLICT`. Every response carries `X-Request-Id`; every error is
`{code, message, retryable, request_id}`. Bodies over `OPS_MAX_BODY_BYTES` (65536) are refused before routing.
Settings: `OPS_MAX_BODY_BYTES`, `OPS_IDEMPOTENCY_TTL_SECONDS` (86400), `OPS_TENANT_QUEUE_QUOTA` (100).

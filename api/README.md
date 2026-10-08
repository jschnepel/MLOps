# api

FastAPI: sessions, admission router, decisions, SSE, health

## Owns
Browser sessions, admission, decisions through definer functions, SSE projections

## Trusts
Keycloak tokens; PostgreSQL role `api`

## Never
Updates `runs.state`; inserts audit rows directly; reaches either sim

## Runs (T08)

`python -m ops_api` on 127.0.0.1:8000 (`OPS_API_PORT`). Bearer persona tokens (`aud ops-api`, `azp ops-dev-direct`)
resolved to a tenant and roles through seeded memberships. Endpoints: `/api/v1/me`, `POST /api/v1/conversations`,
`POST /api/v1/conversations/{id}/messages` (investigate only; 202), `GET /api/v1/runs/{id}`, `GET /api/v1/proposals/{id}`,
`POST /api/v1/proposals/{id}/decisions` (independent reviewer, exact revision and hash, first decision wins),
`GET /api/v1/runs/{id}/events`. Sessions, CSRF and Idempotency-Key: T11/T12.

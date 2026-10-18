# api

FastAPI: sessions, admission router, decisions, SSE, health

## Owns
Browser sessions, admission, decisions through definer functions, SSE projections

## Trusts
Keycloak tokens; PostgreSQL role `api`

## Never
Updates `runs.state`; inserts audit rows directly; reaches either sim

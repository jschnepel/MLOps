# Development topology (T05, T43, T44)

Profile `dev` of `compose.yaml` (project `ops-copilot`, network `ops-dev-net`). Every published port binds to `127.0.0.1`.

| Service | Image (digest-pinned) | Container address | Host address | Secrets (files) |
|---|---|---|---|---|
| postgres | `pgvector/pgvector:pg17` (0.8.7) | `postgres:5432` | `127.0.0.1:15432` | `postgres_password` (`POSTGRES_PASSWORD_FILE`) |
| keycloak | `quay.io/keycloak/keycloak:26.8.0` | `keycloak:8080` (management `9000`, unpublished) | `127.0.0.1:18080` | `kc_bootstrap_admin_password`, `kc_client_secret_*`, `kc_persona_*_password` (exported by `deploy/dev/keycloak/entrypoint.sh`) |

## Host versus container callers

- Host processes (tests, the owner's shell) call Keycloak at `http://localhost:18080` and PostgreSQL at `127.0.0.1:15432`.
- Containers call Keycloak at `http://keycloak:8080` and PostgreSQL at `postgres:5432`.
- `KC_HOSTNAME=http://localhost:18080` with `KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true` makes the token `iss` identical for both (`http://localhost:18080/realms/ops-dev`); Task 2 asserts it.
- Never route a host caller through `host.docker.internal`: on this machine it resolves to the LAN address and cannot reach the `127.0.0.1`-bound ports.

## Secrets

`scripts/bootstrap_dev.py secrets` generates one file per secret under `%LOCALAPPDATA%\ops-copilot\secrets` (43 URL-safe characters, no newline) and writes the git-ignored `.env` (paths, ports, URLs only). Existing secret files are never overwritten. To rotate a Keycloak secret, delete its file, then `down` and `up` (Keycloak's dev data is ephemeral, so the realm is re-imported with the new value). `postgres_password` is different: the image applies it only when the data volume is initialised, so after replacing the file either apply it to the running container **before** restarting, passing the value only through stdin — Git Bash, repo root: `printf "ALTER ROLE ops PASSWORD '%s';
" "$(cat "$(grep ^OPS_SECRETS_DIR= .env | cut -d= -f2-)/postgres_password")" | docker exec -i ops-copilot-postgres-1 psql -U ops -d ops` — or reset the data with a deliberate, owner-run `docker compose --profile dev down -v`. The stdin form is safe because `printf` is a bash builtin (its arguments never appear in a process list), `psql` reads the statement from stdin rather than from an argument, and the generated value is URL-safe (no quote characters), so the single-quoted literal cannot break; the container's local socket trusts `ops`, so no old password is needed. Compose delivers them as `/run/secrets/<name>`; no secret value appears in `environment:` or in `docker inspect`.

## Commands

- Bring up: `uv run python scripts/bootstrap_dev.py up`
- Status: `uv run python scripts/bootstrap_dev.py status`
- Stop (keeps volumes): `uv run python scripts/bootstrap_dev.py down`
- Reset PostgreSQL data: `docker compose --profile dev down -v` — destructive; run it yourself, deliberately. No script or plan step runs it. (Keycloak keeps no volume: its dev data is ephemeral and re-imported on every `up`.)

(Realm, personas and the service account: see Tasks 2–3 additions below. Ollama: see `ollama-network.md`.)

## Realm `ops-dev` (imported from `deploy/dev/keycloak/realm-ops-dev.json`)

| Client | Kind | Token audience(s) | Used by |
|---|---|---|---|
| `ops-web` | confidential, authorization code + PKCE S256, exact redirect `http://localhost:8000/auth/callback` | — | the API's browser login (T10 registers no wildcard) |
| `ops-worker` | service account | `${MCP_READ_RESOURCE_URL}`, `${MCP_WRITE_RESOURCE_URL}` | worker → mcp-read / mcp-write |
| `ops-mcp-read` | service account | `asset-sim` | mcp-read → asset-sim |
| `ops-mcp-write` | service account | `incident-sim` | mcp-write → incident-sim |
| `ops-dev-direct` | public, direct grant, **dev-only** | — | persona login in tests |

Secrets and persona passwords are `${OPS_KC_*}` placeholders in the file, resolved at import from the environment the entrypoint exports. Persona user IDs are fixed to `data/seed-ids.json`, so a token's `sub` equals the seeded ID (asserted by `tests/plan_b/live/test_keycloak_tokens.py`). Realm roles are informational and Keycloak users carry no tenant attribute: memberships are seeded in PostgreSQL by a `migrator` migration (T08/T09), and Keycloak is not the application role database.

Why the file is shaped this way (JSON cannot carry comments, so the reasons live here and in `tests/plan_b/test_realm_template.py`): each workload client has its own audience mapper so a token minted for one downstream is useless against the other (`ops-mcp-read` never gets `incident-sim`, and vice versa); only `ops-dev-direct` allows the password grant, and its description says `dev-only` because a password grant must not exist outside this profile; Keycloak adds the default `account` audience to service-account tokens (the persona tokens from the direct-grant client carry no `aud`), which the live tests strip before comparing audiences exactly. `sslRequired: none` is for the dev profile only: HTTP on localhost is BUILD_SPEC §9's documented localhost-only exception, and cluster profiles require TLS. `accessTokenLifespan: 300` keeps tokens short-lived so the window after a revocation stays small, alongside the AM-20.7 enabled-check and the ≤60 s membership sync. Measured 2026-10-08 on Keycloak 26.8.0: the `${...}` placeholders are substituted at import, and `iss` is `http://localhost:18080/realms/ops-dev` from both the host and a container on `ops-dev-net` (`KC_HOSTNAME` in `compose.yaml` pins the public issuer, so a request to `http://keycloak:8080` still yields it).

The bootstrap admin `tmpadmin` exists only for the master realm; Task 3 removes it after import.

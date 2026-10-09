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
| `ops-web` | confidential, authorization code + PKCE S256, exact redirect `http://localhost:8000/auth/callback` | — | the API's browser login (T10 registers no wildcard); back-channel logout URL `http://host.docker.internal:8000/auth/backchannel-logout` (reached from the container; T30 moves it) |
| `ops-worker` | service account | `${MCP_READ_RESOURCE_URL}`, `${MCP_WRITE_RESOURCE_URL}` | worker → mcp-read / mcp-write |
| `ops-mcp-read` | service account | `asset-sim` | mcp-read → asset-sim |
| `ops-mcp-write` | service account | `incident-sim` | mcp-write → incident-sim |
| `ops-dev-direct` | public, direct grant, **dev-only** | — | persona login in tests |
| `ops-test-admin` | service account, `manage-users` + `view-users`, **dev/test-only** | — | the live suite's persona switch |

Secrets and persona passwords are `${OPS_KC_*}` placeholders in the file, resolved at import from the environment the entrypoint exports. Persona user IDs are fixed to `data/seed-ids.json`, so a token's `sub` equals the seeded ID (asserted by `tests/plan_b/live/test_keycloak_tokens.py`). Realm roles are informational and Keycloak users carry no tenant attribute: memberships are seeded in PostgreSQL by a `migrator` migration (T08/T09), and Keycloak is not the application role database.

Why the file is shaped this way (JSON cannot carry comments, so the reasons live here and in `tests/plan_b/test_realm_template.py`): each workload client has its own audience mapper so a token minted for one downstream is useless against the other (`ops-mcp-read` never gets `incident-sim`, and vice versa); only `ops-dev-direct` allows the password grant, and its description says `dev-only` because a password grant must not exist outside this profile; Keycloak adds the default `account` audience to service-account tokens (the persona tokens from the direct-grant client carry no `aud`), which the live tests strip before comparing audiences exactly. `sslRequired: none` is for the dev profile only: HTTP on localhost is BUILD_SPEC §9's documented localhost-only exception, and cluster profiles require TLS. `accessTokenLifespan: 300` keeps tokens short-lived so the window after a revocation stays small, alongside the AM-20.7 enabled-check and the ≤60 s membership sync. Measured 2026-10-08 on Keycloak 26.8.0: the `${...}` placeholders are substituted at import, and `iss` is `http://localhost:18080/realms/ops-dev` from both the host and a container on `ops-dev-net` (`KC_HOSTNAME` in `compose.yaml` pins the public issuer, so a request to `http://keycloak:8080` still yields it).

The bootstrap admin `tmpadmin` exists only for the master realm; `bootstrap_dev.py up` removes it after import (see below).

## Personas and tenants

All five personas (`alex`, `sam`, `lee` in tenant alpha; `riley`, `jordan` in tenant beta) log in through `ops-dev-direct` with the passwords in `kc_persona_<name>_password`. Their Keycloak IDs equal `data/seed-ids.json`.

## Admin-API service account

`ops-view-users` holds exactly `realm-management/view-users`. It can read a user's `enabled` flag (the API's fail-closed check and the sweeper's membership sync, AM-20.7); it gets 403 on user updates, user creation and client listing (`tests/plan_b/live/test_service_account.py`).

## Bootstrap admin and rotation

`KC_BOOTSTRAP_ADMIN_USERNAME=tmpadmin` with `kc_bootstrap_admin_password` creates the temporary master-realm admin when the (ephemeral) master realm is new. `scripts/bootstrap_dev.py up` deletes it through the admin REST API using its own token as soon as the stack is healthy; `test_bootstrap_admin_is_absent` asserts the password grant then fails (HTTP 400 `invalid_grant` on 26.8). A bare `docker compose --profile dev up` (not the script) leaves `tmpadmin` in place until the next `bootstrap_dev.py up`. Observed on 2026-10-08 after `docker compose restart keycloak`: `after restart: HTTP 400 (still absent)`. Rotation: delete `kc_bootstrap_admin_password` (a new one is generated by the next `secrets`/`up`), then `down` and `up`; Keycloak's dev data is ephemeral, so the realm is re-imported from the committed file with the current secrets.

## Ollama (host process)

| Caller | Base URL (`.env`) |
|---|---|
| host processes (tests, the worker when run on the host) | `OLLAMA_BASE_URL_HOST=http://127.0.0.1:11434` |
| containers (the worker in Compose, T08) | `OLLAMA_BASE_URL_CONTAINER=http://host.docker.internal:11434` |

`tests/plan_b/live/test_ollama_bridge.py` proves both routes answer the same version. Because Docker Desktop delivers container traffic to the host from `127.0.0.1` (measured 2026-10-08), the owner removes LAN exposure by binding Ollama to loopback — `docs/runbooks/ollama-network.md`; no firewall rule is needed on this machine. The worker's digest check reads `data/model-pins.json` through `ops_core.model_pins.load_model_pins` (T19).

## Database roles (T09)

Each process connects as its own AM-20.1 login role and never as the owner: api as `api`, the worker as `worker`, mcp-read as `mcp_read`, mcp-write as `mcp_exec`, incident-sim as `incident` (its own database). `sweeper` is the sweeper process's role (T11); `operator` stays reserved for T22; and `test_harness` exists only in the test profile. Each role's password is one file `postgres_<role>_password` under `OPS_SECRETS_DIR` (`scripts/bootstrap_dev.py secrets` generates them; none is ever printed), and `scripts/skeleton.py migrate` creates or re-keys the roles from those files before Alembic runs. The Compose superuser `ops` is for migrations, role bootstrap and test fixtures only. The dev database never carries `app.test_clock`: the `testclock` Alembic branch is applied only under `PROFILE=test`, and `skeleton.py up` refuses to start when the table exists outside that profile.

## Host processes (T08, T11)

The six application processes run on the host until T30 containerises them (`docs/runbooks/walking-skeleton.md`). Every listener binds `127.0.0.1`.

| Process | Module | Port | Notes |
|---|---|---|---|
| incident-sim | `ops_incident_sim` | 8090 | destination; database `incident`, role `incident` |
| mcp-read | `ops_mcp_read` | 8081 | `/mcp`, read tool `search_procedures` |
| mcp-write | `ops_mcp_write` | 8082 | `/mcp`, write tool `create_incident` |
| api | `ops_api` | 8000 | persona bearer tokens, audience `ops-api` |
| worker | `ops_worker` | 8070 | health only; polls `app.jobs` |
| sweeper | `ops_sweeper` | 8071 | health only; the membership sync as a maintenance job, expiry purges (T11) |

## Browser login (T11)

`GET /auth/login` on `http://localhost:8000` stores the authorization request (state, nonce, PKCE verifier) in `app.login_state`, keyed by the hash of the `ops_login` cookie, and redirects to the Keycloak form for `ops-web`. After the password step Keycloak returns to `GET /auth/callback`, which checks state, nonce, issuer and audience, resolves the membership, opens a server-side session and sets two cookies: `ops_session` (opaque, HttpOnly; only its hash is stored) and `ops_csrf` (readable by the page, which echoes it in a header on every browser mutation, logout included, together with a matching `Origin`; the server keeps only its hash). A subject with no membership, or with two, is refused. `POST /auth/logout` revokes the session, spends the stored refresh token at Keycloak and answers 204; the Keycloak form then appears again on the next login. Keycloak also calls `POST /auth/backchannel-logout`, which verifies the logout token (signature, algorithm allowlist, `exp`, `sid`/`sub`) against a durable `jti` store and revokes every session with that `sid`; a replayed or forged token is refused.

The back-channel URL in the realm export is `http://host.docker.internal:8000/auth/backchannel-logout`: Keycloak runs in a container and the API runs on the host, so the container reaches the host through Docker's host alias, not `localhost`. T30 replaces it when the API is containerised. The realm's SSO lifetimes are 8 h so the provider session outlives the application session.

**Warning.** `ops-test-admin` (a service account with `manage-users`) exists in the dev realm only, for the live suite's persona switch (disable and re-enable a user). Never import it into the demo realm (T30).

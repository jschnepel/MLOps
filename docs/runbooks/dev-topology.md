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

`scripts/bootstrap_dev.py secrets` generates one file per secret under `%LOCALAPPDATA%\ops-copilot\secrets` (43 URL-safe characters, no newline) and writes the git-ignored `.env` (paths, ports, URLs only). Existing secret files are never overwritten. To rotate a Keycloak secret, delete its file, then `down` and `up` (Keycloak's dev data is ephemeral, so the realm is re-imported with the new value). `postgres_password` is different: the image applies it only when the data volume is initialised, so after replacing the file either apply it to the running container **before** restarting, feeding the value from the file so it never appears on a command line or in shell history — Git Bash, repo root: `docker exec -i ops-copilot-postgres-1 psql -U ops -d ops -v pw="$(cat "$(grep ^OPS_SECRETS_DIR= .env | cut -d= -f2-)/postgres_password")" -c "ALTER ROLE ops PASSWORD :'pw'"` (the container's local socket trusts `ops`, so no old password is needed) — or reset the data with a deliberate, owner-run `docker compose --profile dev down -v`. Compose delivers them as `/run/secrets/<name>`; no secret value appears in `environment:` or in `docker inspect`.

## Commands

- Bring up: `uv run python scripts/bootstrap_dev.py up`
- Status: `uv run python scripts/bootstrap_dev.py status`
- Stop (keeps volumes): `uv run python scripts/bootstrap_dev.py down`
- Reset PostgreSQL data: `docker compose --profile dev down -v` — destructive; run it yourself, deliberately. No script or plan step runs it. (Keycloak keeps no volume: its dev data is ephemeral and re-imported on every `up`.)

(Realm, personas and the service account: see Tasks 2–3 additions below. Ollama: see `ollama-network.md`.)

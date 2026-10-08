# Walking skeleton (T08)

Five host processes against the dev profile (PostgreSQL + Keycloak in Compose). Containers for the application
processes arrive with T30; everything here reads its configuration the way a container would (environment plus secret
files), so nothing is throwaway.

1. `uv run python scripts/bootstrap_dev.py up` (Keycloak, Postgres; secrets under `OPS_SECRETS_DIR`).
2. `uv run python scripts/skeleton.py migrate` (Alembic revision 1 for `ops` and `incident`; creates role `incident`).
   `migrate` reads `PROFILE` (dev by default; `test` also applies the `testclock` branch) and
   `OPS_PG_DB`/`OPS_INCIDENT_PG_DB`; it creates or re-keys the login roles from `postgres_<role>_password` (run
   `scripts/bootstrap_dev.py secrets` once after pulling this branch to generate the seven new files); `up` refuses
   outside the test profile when `app.test_clock` exists; `keys` is the destination-vs-grant detective check; the live
   suite runs against `ops_test`/`incident_test` and never touches the dev databases.
3. Either, for a manual session: `uv run python scripts/skeleton.py up` — starts incident-sim :8090, mcp-read
   :8081, mcp-write :8082, api :8000, worker :8070 (health only), all on 127.0.0.1; logs in `runtime/skeleton/`;
   `uv run python scripts/skeleton.py status` shows each process's readiness;
   `uv run python scripts/skeleton.py down` when finished. `up` refuses (exit 2) while a set is running or
   `runtime/skeleton/pids.json` exists, so a second `up` can never orphan the first set: run `down` first.
4. Or, for the proof: with no skeleton processes running (`scripts/skeleton.py status` shows every process `down`),
   `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e -q` — the R105 module starts and stops its own five
   processes and writes `reports/skeleton/r105-walking-skeleton.txt`. The in-process live tests of Tasks 5 and 6
   bind 18081 and 18090, so their ports never collide with a running skeleton; they purge their rows in `finally`,
   so a running skeleton worker finds no claimable job of theirs.
5. The realm must carry Task 1's `ops-api` audience: after any `bootstrap_dev.py down`/`up` from a checkout without
   it, run `down` and `up` again from this branch, or persona tokens have no audience and every API call is 401.
6. Every live run rewrites tracked evidence (`reports/skeleton/r105-walking-skeleton.txt`, and the Plan B suite's
   `reports/bootstrap/*.txt`), so the tree is dirty after a live run; commit the files when their content changed for
   a reason worth keeping, otherwise `git checkout -- reports/`.

If mcp-write is down, approved runs wait in APPROVED and their execute jobs retry every 30 s until it returns. The
R105 run, its conversation and its incident stay in the dev database on purpose: they are the evidence the proof
file describes, and nothing purges them.

Tokens: personas through the dev-only direct grant (`ops-dev-direct`, audience `ops-api`); the worker through
`ops-worker` (both MCP audiences); mcp-write through `ops-mcp-write` (audience `incident-sim`). The MCP resource URLs
in `.env` are audience identifiers (`http://mcp-read:8081/mcp`), while the host processes listen on
`http://127.0.0.1:8081/mcp`; T30 makes them coincide.

Declared shortcuts: the debt list in `SESSION_STATE.md` (each line names its owning task).

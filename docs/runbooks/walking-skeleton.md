# Walking skeleton (T08)

Six host processes against the dev profile (PostgreSQL + Keycloak in Compose). Containers for the application
processes arrive with T30; everything here reads its configuration the way a container would (environment plus secret
files), so nothing is throwaway.

1. `uv run python scripts/bootstrap_dev.py up` (Keycloak, Postgres; secrets under `OPS_SECRETS_DIR`).
2. `uv run python scripts/skeleton.py migrate` (creates or re-keys the roles from their secret files, then runs the Alembic revisions up to the profile's
   target for `ops` and `incident`, including the `incident` login role).
   `migrate` reads `PROFILE` (dev by default; `test` also applies the `testclock` branch) and
   `OPS_PG_DB`/`OPS_INCIDENT_PG_DB`; it creates or re-keys the login roles from `postgres_<role>_password` (run
   `scripts/bootstrap_dev.py secrets` once after pulling this branch to generate the seven new files); `up` refuses
   outside the test profile when `app.test_clock` exists; `keys` is the destination-vs-grant detective check; the live
   suite runs against `ops_test`/`incident_test` and never touches the dev databases.
3. Either, for a manual session: `uv run python scripts/skeleton.py up` — starts incident-sim :8090, mcp-read
   :8081, mcp-write :8082, api :8000, worker :8070 (health only), sweeper :8071
   (health only; membership sync every 30 s, expiry purges), all on 127.0.0.1; logs in `runtime/skeleton/`;
   `uv run python scripts/skeleton.py status` shows each process's readiness;
   `uv run python scripts/skeleton.py down` when finished. `up` refuses (exit 2) while a set is running or
   `runtime/skeleton/pids.json` exists, so a second `up` can never orphan the first set: run `down` first.
4. Or, for the proof: with no skeleton processes running (`scripts/skeleton.py status` shows every process `down`),
   `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e -q` — the R105 module starts and stops its own six
   processes and writes `reports/skeleton/r105-walking-skeleton.txt`. The in-process live tests of Tasks 5 and 6
   bind 18081 and 18090, so their ports never collide with a running skeleton; they purge their rows in `finally`,
   so a running skeleton worker finds no claimable job of theirs.
   The one-command form of the proof is `PYTHONUTF8=1 uv run python scripts/check.py --profile test`: the same four
   steps as the default profile, with `OPS_LIVE=1` and `PROFILE=test` exported so the live suite runs too (dev stack up).
5. The realm must carry Task 1's `ops-api` audience: after any `bootstrap_dev.py down`/`up` from a checkout without
   it, run `down` and `up` again from this branch, or persona tokens have no audience and every API call is 401.
6. Every live run rewrites tracked evidence (`reports/skeleton/r105-walking-skeleton.txt`, and the Plan B suite's
   `reports/bootstrap/*.txt`), so the tree is dirty after a live run; commit the files when their content changed for
   a reason worth keeping, otherwise `git checkout -- reports/`.

Without the sweeper, grants refuse with `MEMBERSHIP_STALE` after 120 s and execute jobs wait (re-queued every 30 s)
until it runs. The sync refuses (and stamps nothing) when three or more and more than half of the active subjects are
missing from the realm's listing, which is what a listing from the wrong realm looks like (readiness turns 503 and
grants refuse `MEMBERSHIP_STALE` after 120 s; a legitimate mass offboarding is accepted by starting the sweeper once
with `OPS_SYNC_ALLOW_MASS_DEACTIVATION=1`). A back-channel logout Keycloak could not deliver is not retried, so the
application session then ends at its own limits. The API and the sweeper refuse to start until the database carries
revision 0005 (`skeleton.py migrate`).

The destination (incident-sim, T10): the schema belongs to `incident_owner` and the runtime role `incident` can only
SELECT and INSERT, so a key is never deleted or rewritten. `POST /internal/actions/{action_id}/abort` takes
`{"payload_sha256": "<64 hex>", "reason": "cancelled_before_send" | "expired" | "deadline"}` and answers the existing
key's document when one exists (a receipt if committed, otherwise the first tombstone), else writes an `ABORTED`
tombstone. A well-formed POST whose hash does not match the bytes, or whose payload is not a non-empty object, writes a
permanent `REJECTED` key and answers 200 with the tombstone; a token for another audience or azp is 403. Under
`PROFILE=test` only, `POST /internal/faults/{kind}` with `{"count": n}` arms `reject_next` (next POST is rejected with
reason `policy`), `drop_before_commit` (next POST answers 503, nothing written) or `lose_after_commit` (next POST
commits, then answers 503; recover with `GET /internal/actions/{action_id}`); the routes return 404 in dev and demo.
`uv run python scripts/skeleton.py keys` lists destination keys that no execution grant carries (exit 1 if any).

If mcp-write is down, approved runs wait in APPROVED and their execute jobs retry every 30 s until it returns. The
R105 test runs against the per-session `ops_test` and `incident_test` databases, which the next live session drops and
recreates, so the run ids, action id and incident id in `reports/skeleton/r105-walking-skeleton.txt` exist nowhere
after that session; the proof file, not the database, is the retained evidence.

Recovering a dev database that was migrated under `PROFILE=test`: the testclock branch is then applied, and `up`
refuses to start while `app.test_clock` exists. There is no CLI verb for the branch downgrade; with `PROFILE` unset (or
`dev`), take the branch off and migrate the main line again:

```
uv run python -c "from scripts.skeleton import downgrade, load_dotenv, export_environment; from ops_core import settings; export_environment(load_dotenv()); downgrade('app', settings.superuser_postgres(), 'testclock@base')"
uv run python scripts/skeleton.py migrate
```

Tokens: personas through the dev-only direct grant (`ops-dev-direct`, audience `ops-api`); the worker through
`ops-worker` (both MCP audiences); mcp-write through `ops-mcp-write` (audience `incident-sim`). The MCP resource URLs
in `.env` are audience identifiers (`http://mcp-read:8081/mcp`), while the host processes listen on
`http://127.0.0.1:8081/mcp`; T30 makes them coincide.

Declared shortcuts: the debt list in `SESSION_STATE.md` (each line names its owning task).

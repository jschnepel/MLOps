# Adversarial review of Plan F (Keycloak login, server-side sessions, revocation and the membership sync, T11): rounds 1–4 (2026-10-09)

**Reviewed:** `docs/superpowers/plans/2026-10-08-first-slice-f-sessions-login-sync.md` before execution. The plan was
written from a fact sheet (`docs/superpowers/research/2026-10-08-plan-f-inputs.md`, T11 verbatim with the spec's revocation, session and CSRF text row by row, 27 open
questions) and a measured library spike (`…plan-f-spike.md`, six measurements: code+PKCE, back-channel logout, the admin API, cookies and CSRF, the jti store and sync shapes, log redaction) run against the live dev stack and a throw-away Keycloak before any plan code
existed.

**Method:** the same two-critic gauntlet as Plans A–E — a static critic cross-checking every claim against the spec,
the existing code and the libraries (measured in a scratch environment), and a builder executing all seven tasks on a
throwaway worktree against the live Keycloak and PostgreSQL, with the shared databases cleaned afterwards.

**Round 1 (static critic: 5 Blocking, 6 Important, 18 Minor and five user-facing failure modes no test pinned; builder: 29 workarounds over seven tasks, three of them stopping a literal executor).** The two reviews agreed on the defects that mattered, and the builder measured them live. First, the session store's new `session()` method collided with the `DbStore.session` attribute every other method uses (the `persistence.Session` of Plan D), so mypy reported eighteen errors and every cookie-authenticated request would have raised inside the identity dependency; the operation is now `live_session`. Second, the sweeper's sync read its subjects with `SELECT DISTINCT … FOR UPDATE`, which PostgreSQL refuses (`0A000`), so no sync ever ran, readiness never turned 200 and the walking skeleton timed out after 90 s; the `DISTINCT` is gone and a live test runs the sync's SQL as the sweeper role before the skeleton depends on it. Third, authlib ships no type information, so the strict type check failed on the first import and the plan's own "no `type: ignore`" rule left no way out; a mypy override is now declared beside the dependency. Fourth, the plan declared the walking-skeleton test red for three tasks "because no sweeper stamps `synced_at`", but the autouse fixture it had just added stamps the rows right before the test body, so the test was green the whole time and, worse, would never have proved that the sweeper keeps grants alive; the declaration is gone and the skeleton modules opt out of the stamp so the sweeper's own work is what passes. Fifth, the sync cadence was a per-minute job claimed by a 30 s tick, which measures 60 s plus two tick durations between syncs and would have failed the "within 60 s" live assertion a few runs in a hundred; the sync now runs every tick and the job row is the minute's audit record. The static critic also found that the Keycloak session (30 minutes idle, never refreshed by the application) would end under a live 8-hour application session, after which no logout could reach the provider and no back-channel logout could reach the API (the realm's lifetimes are raised to 8 h); that the redaction filter missed `Authorization: Basic`, `client_secret=`, the CSRF header and the `repr` forms of query parameters and cookies; that a user at `127.0.0.1:8000` would get a login cookie Keycloak never redirects back to (the login route now sends every other host to the public one); that a listing from the wrong realm would deactivate every membership irreversibly (a mass-deactivation guard refuses more than half at once); and that four spec departures were not marked as errata. The builder added the seams only execution finds: the workspace layout test rejects a sixth member without a README carrying its trust headings and a `__version__`; a package must exist before `uv lock` can see it; an `assert`, a docstring and three string literals the formatter cannot wrap exceed 120 characters; a unit test in the plan picked an expired-but-unrevoked row and failed as written; the manual API probe used `HEAD` against a `GET` route and started without the secrets directory. Every finding was accepted; the round-2 text carries each fix, and the plan gained a live session-store test, a live sync test, a lifespan guard that refuses to serve a database the owner has not migrated, and four more proposed errata.

**Round 2 (static critic: 67 of 82 round-1 items closed, 6 partial, 1 open; 2 new Blocking, 3 Important, 11 Minor. builder: 17 new workarounds, down from 29, with 24 of the round-1 ones gone and five still needing a hand; four of the new ones stopped a literal executor).** The two reviews agreed again, and both blocking items were the author's own round-1 fixes turning on each other. The host redirect added for a user who opens `127.0.0.1:8000` also bounced the live test's browser helper, which dials the loopback address, so three of the four live login tests would have failed at their first line; the helper now presents the public host while still dialling loopback (which also avoids the 2 s IPv6 detour). And the disable test's teardown restored `active` but not `permission_version`, so the sweeper's live test, which runs later in the same session, would have found sam at version 3 and failed; the teardown restores both and the sweeper test asserts increments rather than absolute values. The redaction fix had left the old `_PATTERNS` header line above the new block, a syntax error that would have stopped every service from importing; the critic's overlay caught it where a fence extractor would have hidden it. The mass-deactivation guard, added for a listing from the wrong realm, counted explicitly disabled users too, so an ordinary bulk offboarding or a one-user realm would have tripped it and, with nothing to override it, stopped every grant for good while leaving the disabled users active; the guard now counts only subjects missing from the listing, has a floor of three, is a pure function with its own unit test, and the owner has a documented one-shot override. The "sweeper really stamps the rows" proof existed only as prose and, read as two samples, would often see no tick in between; it is now a 45 s poll on `min(synced_at)` against a value recorded right after the skeleton came up. The builder added two more of its own kind: an `await` inside a generator handed to `all()` (a `TypeError` at the live store test's first run) and a `noqa` the linter's own fixer deleted, reason and all, because the rule it named is not enabled in this project. The eleven minors were the kind a third reading finds: a redirect loop when the public base URL carries an explicit default port (a host rule that normalises ports, with a proxy debt line), two code fences that never closed and would have mis-split a fence-based extraction, an implicit string concatenation the linter still flagged, `noqa` markers for a rule the project does not enable, a live store test named for an atomicity it did not test (the rollback case is now there), the revision guard without a test (now live-tested), two `errata 26–31` stragglers, and a client the back-channel test leaked. The critic's overlay run of the plan's own code gave 109 unit tests passing and a clean strict type check.

**Round 3 (closure: one reviewer verified every round-2 item against the delta and executed all seven tasks a third time).** 42 of 48 round-2 rows closed, 6 partial, none open; the third run needed four workarounds, down from 29 and 17, and two of them were the author's round-2 fixes again: the redaction rule now ignores Authorization values shorter than sixteen characters so prose such as "bearer token missing" survives, but the test's canary was twelve characters long and the test failed as written; and the atomicity case added to the live store test put an `await` inside a generator a second time, the very shape the round-2 builder had just reported one line lower. The other two were a lint failure (`re.S` where the project's linter wants `re.DOTALL`, in a step that had no lint sentence) and a comment that pushed five entrypoint lines over 120 characters. Nine minors remained: a fence that again closed with text on its line, a gap in the ruling numbers, a method named in the interfaces with no step that adds it, a marker added after the run it was meant to govern (so the first run's "the sweeper re-stamped" line proved nothing), and the redaction docstring lagging its patterns. All were fixed in the text; the final gates on the dry-run worktree were `check.py` 644 passed / 94 skipped, `check.py --profile test` 717 passed / 21 skipped, `verify_handoff.py` exit 0, with the walking skeleton passing on six processes after the rows had been aged ten minutes and the R086 disable path measured at 23 s.

**Round 4 (delta check: closure of the round-3 items and a literal re-execution of every task but the close-out).** 12 of 14 rows closed, one partial (texts the close-out task describes rather than quotes), one open by acceptance (a JSON description line no gate counts). Zero workarounds: Tasks 1–6 ran as written with every gate green on its first run (`check.py` 644 passed / 94 skipped; `--profile test` 717 passed / 21 skipped; `verify_handoff.py` exit 0), the redaction block parsed and passed its test from a fresh overlay, every ruling number and code fence checked, every new identifier found defined by a task, and the two measurements that mattered held twice: the sweeper re-stamped the memberships 25 s after the skeleton came up with the fixture opted out, and a user disabled at Keycloak lost the membership 23 s later.

The plan went from 29 workarounds to 17 to 4 to 0 across the four dry runs; the record below is the reviewers' own text.

The reports below are the reviewers' text, unedited except that machine-local paths are replaced by placeholders.

---

## Round 1 — static critic

# Plan F round 1: static critic report

Plan: `docs/superpowers/plans/2026-10-08-first-slice-f-sessions-login-sync.md` (branch `plan-f`, 4f14f95).

**Summary: Blocking 5 / Important 6 / Minor 18**

## How the evidence was gathered

- I copied the plan's verbatim code into an overlay outside the repository (`scratchpad/planf-critic/ov`). It covers the `settings`, `tokens`, `redaction`, `keycloak_admin` and `persistence` additions, `ops_api.auth`, the `store` and `app` edits, and `ops_sweeper`. I ran the plan's own test modules against it, with `uv run --with authlib==1.8.0` and the overlay first on `PYTHONPATH`.
- I ran `mypy --strict` over the overlay.
- I checked authlib 1.8.0's actual behaviour with `MockTransport` probes.
- I ran one plan-only statement on the dev database with `EXPLAIN` (no execution) in a read-only session as superuser `ops`.

The repository was not modified. No secret was printed.

---

## Blocking

### B1. `DbStore.session(...)` collides with the existing attribute `DbStore.session`

- **Location:** Task 3 Step 5 (store); Task 4 Step 3 (`identity` calls `store.session(au.digest(raw), ...)`); the Interfaces line in Task 3.
- **Claim:** "`Store.session(session_sha256, *, idle_seconds) -> SessionRow | None`"; Task 3 says `uv run mypy api/src core/src` is clean.
- **Evidence against:**
  - `api/src/ops_api/store.py:151-152`: `DbStore.__init__` sets `self.session = persistence.Session(conn)`.
  - Every `DbStore` method uses `self.session.unit()`.
  - `app.py:98,104,169` use `app.state.store.session.conn` and `.ping()`.
  - Defining a method named `session` on the class is shadowed by the instance attribute.
  - mypy on the overlay printed: `ops_api\store.py:213: error: Cannot assign to a method [method-assign]`, then 15 `has no attribute "unit"` errors (`store.py`) and 3 `has no attribute "conn"/"ping"` errors (`app.py`).
  - A runtime probe of the same shape gave `runtime: TypeError 'Sess' object is not callable`.
  - So every cookie-authenticated request in production would raise inside `identity`. No exception handler covers `TypeError`, so the response is a 500.
  - The unit tests do not catch this, because `FakeStore` has no `session` attribute.
- **Fix:** rename the operation everywhere: `Store.live_session(...)` / `DbStore.live_session(...)` / `FakeStore.live_session(...)`, with `identity` calling `store.live_session(...)`. Update the Task 3 Interfaces and self-review §3 to match. After the rename, mypy on the overlay printed `Success: no issues found in 24 source files` (with B3's override).

### B2. `SELECT DISTINCT ... FOR UPDATE` is illegal in PostgreSQL, so the sweeper never syncs

- **Location:** Task 5 Step 3, `sweeper/src/ops_sweeper/sync.py`: `"SELECT DISTINCT subject FROM app.memberships WHERE issuer = %s AND active FOR UPDATE"`.
- **Evidence against:**
  - Probe on PostgreSQL 17.11 (dev, read-only, `EXPLAIN` only): `ERR: EXPLAIN SELECT DISTINCT subject FROM app.memberships WHERE active FOR -> 0A000 FOR UPDATE is not allowed with DISTINCT clause`.
  - The same statement without `DISTINCT` plans fine: `LockRows -> Seq Scan on memberships`.
  - 0A000 is not an `OperationalError`, so `run_forever` logs "sweeper tick failed" every tick and never sets `last_sync_at`.
  - `/health/ready` therefore stays 503, and `Skeleton.start()` raises `not ready in 90.0s` (`scripts/skeleton.py:313-337`).
  - The result: the Task 5 Step 4 R105 run, the Task 5 and Task 6 gates and Task 6's sync assertion all fail. In production, no membership is ever deactivated.
  - No unit or live test runs `sync_memberships` SQL before R105. `tests/plan_f/test_sweeper.py` covers only `plan()`, `minute_bucket` and `fresh`.
- **Fix:**
  - Use `SELECT subject FROM app.memberships WHERE issuer = %s AND active FOR UPDATE`. `plan()` already returns a `frozenset`, so duplicate subjects are harmless.
  - Add a live test in Task 5, as role `sweeper` on `ops_test`. It should cover:
    - a seeded persona listed as disabled, then deactivated;
    - a subject absent from the listing, then deactivated;
    - every row of the issuer stamped;
    - another issuer untouched;
    - an empty listing that stamps nothing.

### B3. authlib has no `py.typed`, so mypy strict fails on the new import, and the plan forbids `type: ignore`

- **Location:** Task 3 Step 4 (`from authlib.integrations.httpx_client import AsyncOAuth2Client, OAuthError`); the Task 3 and Task 4 gates (`uv run mypy api/src core/src` clean); `scripts/check.py:83` runs mypy over `MEMBER_SRC`.
- **Evidence against:**
  - Probe: `authlib 1.8.0 py.typed: False`.
  - `mypy --strict` on a file with that import printed: `error: Library stubs not installed for "authlib.integrations.httpx_client" [import-untyped]`.
  - `pyproject.toml:56-59` has no override.
- **Fix:** in Task 1 Step 2, where authlib is locked, add the following to the root `pyproject.toml`, with a comment citing the missing `py.typed`:

  ```toml
  [[tool.mypy.overrides]]
  module = ["authlib.*"]
  ignore_missing_imports = true
  ```

  I verified that with this override plus B1's rename, mypy strict is clean on `ops_core`, `ops_api` and `ops_sweeper`. Do not use `types-Authlib`: its stubs target `httpx`, not `httpx2`.

### B4. `tests/plan_d/test_api.py::test_identity_and_membership` pins `/api/v1/me` by exact dict equality

- **Location:** Task 4 Step 1 lists the `test_api.py` edits (fixture, `FakeStore`, dual becomes 401) but not this test; Task 4 Step 3 adds `"auth"` to `/me`.
- **Evidence against:**
  - `tests/plan_d/test_api.py:210`: `assert me == {"subject": ..., "tenant_id": ..., "roles": ["requester"], "username": "alex"}`.
  - Running the plan's `test_api.py` edits against the overlay gave: `FAILED tests/plan_d/test_api.py::test_identity_and_membership ... Left contains 1 more item: {'auth': 'bearer'}`.
- **Fix:** Task 4 Step 1 adds `"auth": "bearer"` to that expected dict.

### B5. `test_session_expiry_revocation_and_logout` ages the wrong session

- **Location:** Task 4 Step 2, `tests/plan_f/test_api_auth.py`.
- **Evidence against:**
  - After the idle step, `identity` raises 401 without revoking the row. `FakeStore.session` returns `None` and nothing calls `revoke_session`.
  - So `next(k for k, e in fake.sessions.items() if not e["revoked"])` picks the old idle-expired row, not the new one.
  - Overlay run: `assert c.get("/api/v1/me").status_code == 401 / AssertionError: assert 200 == 401` at the absolute-expiry line.
  - Result: `2 failed, 27 passed` (B4 is the other failure).
- **Fix:** before the second `login_as`, record `before = set(fake.sessions)`, then take `key = next(k for k in fake.sessions if k not in before)`. Alternatively, have `identity` revoke a session that `live_session` refused, so the row stops looking live; that also cleans the table earlier.

---

## Important

### I1. The live R086 assertion `synced_after <= 60.0` is flaky by construction

- **Location:** Task 6 `test_disabled_user_is_refused_and_synced_within_60s`; ruling 12's cadence.
- **Evidence against:**
  - The sync runs once per minute bucket, at the first 30 s tick inside each minute.
  - The loop sleeps *after* each tick (`run_forever`), so the tick period is 30 s plus the tick duration `d`.
  - If ticks fall at M:00.0, then M:30+d, then M+1:00+2d, consecutive syncs are 60+2d apart.
  - A disable just after a sync is detected after up to 60+2d seconds, plus the test's own 1 s polling (`time.sleep(1.0)`).
  - The assertion has no slack, so a few runs in a hundred will fail. SA:547's "every 60 s" is met only on average.
- **Fix (pick one and state it as a ruling):**
  - Align the tick to the wall-clock minute: sleep until the next `:00` plus 1 s. Gaps become 60 s ± jitter. Assert `<= 62` with a comment and an erratum note saying the "≤60 s" bound is "≤ one minute bucket plus tick jitter".
  - Or sync on every 30 s tick: keep the per-minute job row as the audit and dedup record, and add a second "catch-up" sync when the last successful sync is older than 30 s.

### I2. The Keycloak SSO session (30 min idle, never refreshed) is shorter than the application session (8 h absolute, idle reset by activity)

- **Location:** rulings 3 and 4 ("the same window as the application idle limit"); Task 2 Step 5 (the realm is left unchanged).
- **Evidence against:**
  - `deploy/dev/keycloak/realm-ops-dev.json` sets no `ssoSessionIdleTimeout` or `ssoSessionMaxLifespan` (fact sheet §3.8). Spike §1 measured `refresh_expires_in: 1800`.
  - The API never refreshes provider tokens. Only `last_seen_at` moves on use (`DbStore.session`, Task 3 Step 5).
  - So for any user active for more than 30 minutes, Keycloak's SSO session idles out while the application session lives on, for up to 8 h.
  - From then on, a Keycloak-side logout cannot reach the app: no session exists to log out, and no back-channel token is sent. That covers an admin "sign out" or a logout at another client.
  - SA:541 and SA:551's "session-only reads end on back-channel logout" then holds only during the first 30 minutes.
  - Ruling 4's claim that the two windows are the same is false: the application's idle timer resets on every request, and Keycloak's does not.
- **Fix:** set `"ssoSessionIdleTimeout": 28800` and `"ssoSessionMaxLifespan": 28800` in the realm export, pin both in `test_realm_template.py`, and name them in ruling 3. Alternatives:
  - cap the application session at the provider session's remaining idle time;
  - or refresh and re-seal the refresh token on use. This needs `upd(refresh_token_enc)` for `api`, which would be an erratum against SA:413.

  Whichever is chosen, add a live or unit pin.

### I3. The "Interim red" for R105 rests on a false mechanism, and R105 then cannot prove the sweeper keeps grants alive

- **Location:** Global Constraints "Interim red"; Task 2 Step 7; ruling 14 ("the skeleton's own sweeper keeps R105 fresh"); Task 5 Step 4.
- **Evidence against:**
  - `tests/e2e/test_r105_walking_skeleton.py:42-46` starts the skeleton in a **module**-scoped fixture.
  - The new autouse `fresh_memberships` fixture is **function**-scoped (Task 2 Step 2). pytest sets up higher scopes first, so the superuser stamps every `synced_at` *after* the skeleton starts and immediately before the R105 body runs.
  - R105's waits are 45 s each (`test_r105_walking_skeleton.py:73`). The grant therefore happens well inside 120 s, and R105 is most likely green from Task 2 to Task 4. The declared red only hides real regressions for three tasks.
  - Conversely, after Task 5 the same fixture stamps the rows. R105 passing proves nothing about the sweeper's stamping, and neither does Task 6.
- **Fix:**
  - Drop the declared red (R105 must stay green through Tasks 2–4).
  - Opt the two skeleton modules out of the stamp, with a marker the fixture checks, e.g. `@pytest.mark.sweeper_stamps`. Or add an assertion in `test_auth_live` that `min(synced_at)` advances past the fixture's stamp within 75 s while no test code writes it.

### I4. The new API and store SQL first meet PostgreSQL and the real app in Task 5/6, against the plan's own rule

- **Location:** Global Constraints ("the live suite … after every task that changes … a service"); Task 3 Step 6 ("this task touches no live test, so the live suite need not run"); Task 4 Step 4 (`check.py` only, plus a manual start).
- **Evidence against:**
  - Task 3 changes `api/src/ops_api/store.py` and `core`. Task 4 rewrites `api/src/ops_api/app.py`. Both are services.
  - No live test exercises `begin_login`, `take_login`, `create_session`, `session`, `revoke_session` or `record_logout` under the `api` grants until Task 6.
  - B1 and B2 would therefore surface only in Task 5 or Task 6, far from their cause.
- **Fix:**
  - Run `check.py --profile test` in the Task 3 and Task 4 gates. R105 exercises the rewritten `identity` and `enabled_identity` on the bearer path.
  - Add a live store test in Task 3, `tests/e2e/test_sessions_store_live.py`, using `DbStore` over a `role_conn(Role.API)`. It should cover:
    - a `take_login` one-shot and its expiry via the test clock;
    - idle and absolute expiry decided by the `UPDATE … RETURNING`;
    - `record_logout` replay returning `None`;
    - a rolled-back revocation not consuming the jti.

### I5. The redaction filter misses credential shapes this plan itself introduces

- **Location:** Task 1 Step 6 `_PATTERNS`; ruling 22; T11 note 4.
- **Evidence against:** probe of the plan's `redact()`:
  - `'Authorization: Basic CANARYx9'` is unchanged. authlib's default `client_secret_basic` sends this header, and so does `end_session`'s `auth=(CLIENT_ID, secret)`.
  - `'client_secret=CANARYx9&grant_type=x'` is unchanged. `WorkloadTokenSource` posts this form.
  - `'X-CSRF-Token: CANARYx9'` is unchanged.
  - `"{'code': 'CANARYx9', 'state': 'CANARYx9'}"` is unchanged (dict or `repr` of query params).
  - `"{'ops_session': 'CANARYx9'}"` is unchanged (`repr` of `request.cookies`).
  - `"OAuth2Token({'access_token': 'CANARYx9'})"` is unchanged when the value is not JWT-shaped.
  - There is over-redaction too: `'run state=[REDACTED] moved'` and `'exit code=[REDACTED]'`.
- **Fix:**
  - Add these patterns and a canary shape for each:
    - `(?i)(\bbasic\s+)[A-Za-z0-9+/=]+`;
    - `client_secret=` added to the OIDC parameter list;
    - `(?i)(x-csrf-token['"]?\s*[:=]\s*['"]?)[^\s'",;}]+`;
    - a quoted-key form, `(['"](?:code|state|session_state|logout_token|id_token_hint|refresh_token|access_token|id_token|client_secret|ops_session|ops_csrf|ops_login)['"]\s*:\s*['"])[^'"]+`.
  - Accept the `state=` over-redaction explicitly in the docstring, or require a `?`/`&` before `state=`.

### I6. Spec departures that are not marked as errata

- **Location:** rulings 2, 9 and 12; the debt list.
- **Evidence against:**
  - **(a)** BS:352 says "Test session rotation and tenant switching". The plan refuses two-tenant subjects and defers switching to "v2" in the *debt list*. Deferring a BUILD_SPEC requirement past v1 is the owner's decision, so it needs an erratum, not debt.
  - **(b)** SA:565 says "authlib's OIDC state lives in that store", meaning the Postgres `sessions` store. The plan generates state, nonce and verifier itself, stores them in a new table `login_state`, and uses none of authlib's state machinery. Ruling 2 proposes an erratum only for the AM-20.2 grant row, not for SA:565's wording.
  - **(c)** SA:547 says "every 60 s". The minute-bucket cadence can exceed 60 s (I1).
  - **(d)** BS:268's route table gains `POST /auth/backchannel-logout` and `GET /`. These are defensible (SA:541 requires an endpoint) but unrecorded.
- **Fix:** add errata 32–34 to Task 7, for (a), (b) and (c), each with the cost of the alternative. Note (d) in Task 7's `SESSION_STATE` text.

---

## Minor

### M1. Interface and naming inconsistencies an implementer must resolve

- The overview table and ruling 22 say `ops_core.logging` and `test_logging_redaction.py`; Task 1 creates `ops_core.redaction` and `test_redaction.py`.
- The overview puts the privileges rows and `test_privileges_f.py` in Task 1; they are in Task 2.
- Ruling 16's "belt and braces: every session of that sub whose sid is empty" is not implemented in `record_logout`. Since `sid` is `NOT NULL`, drop the sentence.
- The Architecture paragraph says the verifier is "stored hashed or sealed"; ruling 2 and the DDL store it raw.
- The `insert_maintenance_job` docstring says "target-less ON CONFLICT … needs INSERT only", but the SQL uses `ON CONFLICT (dedup_key)`. The plan's own note admits this; fix the docstring text.
- Its parameter `bucket` actually receives the full key, and it bypasses `ops_core.jobs.dedup_key(JobType.SYNC_MEMBERSHIPS, minute_bucket=...)` (`jobs.py:150-183`), which validates the key's shape. Pass a bucket and build the key with `dedup_key`.

### M2. Lines the formatter cannot wrap exceed 120 characters (the plan's own character-count gate)

- Plan line 319: the `sessions()` docstring is 121 characters.
- Plan line 1921: the comment in `AuthlibOidc.exchange` is 122 characters.
- Plan line 3192: the SQL string literal in `insert_maintenance_job` is 121 characters.
- Separately, the `test_revision_0005_bodies_differ_only_by_the_stale_rule` code references `privileges.GRANTS` while the module imports `privileges as p`. The prose says to fix it; put the corrected line in the code instead.

### M3. Task 4 Step 4's manual probe

- `curl -sI` sends HEAD, and FastAPI `@app.get` routes do not answer HEAD. Probe: `TestClient(app).head('/x').status_code` gives `405`.
- The step also says to expect a 303, then says `/auth/login` "will answer 503". Use `curl -s -o /dev/null -w "%{http_code}"`, and state one expected status. With the dev database at 0004 that status is 503.

### M4. The R006 column assertion after the downgrade is vacuous

- The test downgrades to `0001_walking_skeleton`, where `app.sessions` does not exist (it was created in 0002). "Columns absent" is therefore always true.
- Also downgrade to `0004_write_path_functions` and assert:
  - the three columns are gone;
  - the sweeper's `SELECT` on `sessions` is revoked (`has_table_privilege('sweeper','app.sessions','SELECT')` is false);
  - `pg_get_functiondef` of `grant_execution` lacks `MEMBERSHIP_STALE`.

### M5. `test_install_puts_the_filter_on_every_root_handler` changes pytest's own capture handlers for the rest of the session

- Under pytest the root logger already holds `LogCaptureHandler`s, so `basicConfig` does nothing. The filter is added to pytest's session-lived handlers.
- From then on, every later test's captured records have `args=()` and `exc_info=None`.
- Snapshot `root.handlers` and their filters, and remove the added filters in a `finally`. Or run `install()` against a fresh `logging.Manager` or a subprocess.

### M6. `request.form()` needs `python-multipart`, which `api/pyproject.toml` does not declare

- It arrives only through `mcp` (`uv.lock:616`).
- Add `python-multipart` to `api/pyproject.toml` in Task 1 Step 2, so that a containerised API (T30) does not lose the back-channel endpoint.

### M7. The sweeper directory lacks `README.md`

- ADR-0001 line 17 says each deployable directory has "`pyproject.toml`, `Dockerfile`, entrypoint, `tests/` and a `README.md` stating ownership and trust".
- `api/`, `worker/`, `mcp-read/` and `incident-sim/` all have one. Task 5's file list omits it.

### M8. Missing docstrings (CODE_COMMENTS rule 9)

These public classes and functions in the plan's code have no docstring:

- `IdClaims`, `LogoutClaims`;
- `IdTokens`, `LogoutTokens`, `EnabledCheck` members;
- `IdTokenVerifier.ready`, `load_keys`, `verify`;
- `TokenBox.seal`, `TokenBox.open`;
- `Discovery.from_document`;
- the `AuthlibOidc` methods;
- `SyncResult`, `Deps`;
- `SessionSettings.origin`, `redirect_uri`, `cookie_secure`;
- the `Keycloak.*_url` properties;
- the sweeper's `live` and `ready`.

### M9. HS256 negative cases emit a warning at collection

- `jwt.encode(..., "x", algorithm="HS256")` in the `test_id_and_logout_tokens` parametrisation emits `InsecureKeyLengthWarning: The HMAC key is 1 bytes long` (probe; it showed in the overlay test run).
- Use a 32-byte key. The test exists to prove the algorithm pin, not to exercise weak keys.

### M10. Task 5 Step 4's log grep counts redacted lines as hits

- `grep -c "Bearer \|password=" runtime/skeleton/*.log` matches `Bearer [REDACTED]` and `password=[REDACTED]`.
- Grep for unredacted values instead, for example `grep -cE "Bearer [^[]|password=[^[]"`.

### M11. `admin_check_timeout()` accepts `nan` and `inf`

- `float("nan") <= 0` is false.
- Add `math.isfinite(value)` to the check.

### M12. A sweeper restarted within the same minute cannot sync until the next minute

- The bucket's job already exists and is done, so a new sweeper waits up to about 60 s for its first sync, and therefore for readiness.
- `Skeleton.start` allows 90 s. That is fine but slow, and it is not written down.
- Either always sync on the first tick (outside the job), or document it in ruling 12.

### M13. The cells-scan test works only because of alphabetical order

- `GRANTS_0002_SESSIONS` begins with `GRANTS_`, so `test_the_newest_revision_of_every_cell_equals_the_live_matrix` (`tests/plan_e/test_transitions_table.py:67-70`) folds it in.
- The result is correct only because `dir()` sorts `GRANTS_0002_SESSIONS` before `GRANTS_0005`.
- Rename it `SESSIONS_CELLS_0002`.

### M14. The shared authlib client keeps the last login's tokens in memory, and is never closed

- Probe after `fetch_token`: `client retains token after exchange: True`. The `AsyncOAuth2Client` holds the user's access, refresh and ID tokens in plaintext, shared across users. This contradicts ruling 4's "the access token is discarded".
- `closers=(http.aclose, admin.aclose)` omits it.
- Set `self._client.token = None` in a `finally` inside `exchange`, and add `self._client.aclose` to `closers` (an `AuthlibOidc.aclose`).

### M15. The cached admin token is never invalidated on a 401

- `AdminUsers` maps a 401 (for example after a realm re-import with new keys) to `AdminUnavailable`, but `WorkloadTokenSource` keeps the token until about 30 s before expiry.
- Every decision is then 503 for up to about 4.5 minutes.
- On a 401, clear the token (add a `WorkloadTokenSource.invalidate()`) and retry once within the budget.

### M16. Restoring `sam` in `test_disabled_user…` races the skeleton's sweeper

- If a sync's `list_enabled()` ran while `sam` was disabled, and its transaction commits after the `finally`'s `UPDATE … active = true`, `sam` is deactivated again.
- Nothing reactivates `sam`, so R105 (reviewer `sam`) fails later in the session.
- Restore `active` in the module fixture's teardown after `sk.stop()`, or re-check after one more sync.

### M17. The Task 2 Step 5 probe cannot prove that a partial `PUT {"enabled": …}` preserves other fields

- A `PUT {"enabled": true}` on an enabled user is a no-op.
- GET the representation before and after, and compare `email`, `firstName`, `lastName` and `username`.

### M18. Undeclared debt: maintenance job rows pile up

- The scheduler inserts one `jobs` row per minute and never deletes one. The sweeper has no DELETE on `jobs`.
- Add a debt line naming the owning task.

---

## Review Focus completeness: failures a user will hit that no test pins

1. **Opening the app at `http://127.0.0.1:8000` instead of `localhost`.** The `ops_login` cookie is set on `127.0.0.1`, but Keycloak redirects only to `localhost:8000/auth/callback` (spike §1). The callback then 401s with "no login in progress", and every mutation is 403 because the Origin does not match. The live tests hide this: they call `127.0.0.1` and forge `Origin: http://localhost:8000`. Fix: `/auth/login` redirects to `OPS_PUBLIC_BASE_URL` when the request's Host differs. Add a unit test for it.
2. **A Keycloak session that expires under a live application session (I2).** After 30 minutes, logout no longer ends anything at Keycloak, and a Keycloak-side logout never reaches the API. No test pins this.
3. **A sweeper pointed at the wrong Keycloak or realm, or a listing that is partial but not empty.** The sweeper deactivates every unmatched membership *irreversibly* (ruling 13: nothing reactivates). The only guard is "zero users". Add a mass-deactivation guard, for example refusing when more than N% of active subjects would go, with a unit test.
4. **A back-channel POST that fails.** If the API is down, the database is busy, or the endpoint returns 5xx, Keycloak never retries (spike §2), so the application session survives until idle or absolute expiry. Nothing compensates and nothing tests it. At minimum, document this and pin the 5xx path.
5. **Running against the dev database before the owner migrates to 0005 (Task 7).** The API's `/auth/login` returns 503. The sweeper's `purge_expired` fails every tick on the missing `login_state` table and on `sessions` SELECT, so "sweeper tick failed" is logged every 30 s. Readiness still says fresh. No test or runbook line states this behaviour.

---

## What I verified and found correct

**authlib 1.8.0 (probe):**

- `AsyncOAuth2Client` subclasses `httpx2.AsyncClient`. `create_authorization_url(url, state=None, code_verifier=None, **kwargs)` puts `state`, `nonce`, `code_challenge` (43 chars) and `code_challenge_method=S256` into the URL from the constructor's `code_challenge_method="S256"`.
- The constructor accepts `timeout`.
- `fetch_token(url, grant_type=, code=, code_verifier=, redirect_uri=)` sends exactly `code, code_verifier, grant_type, redirect_uri`, with `redirect_uri` once, using Basic client auth.
- A 400 `invalid_grant` raises `OAuthError` with `.error == "invalid_grant"`. An HTML 502 or a JSON 500 raises `httpx2.HTTPStatusError`, and a connect failure raises `httpx2.ConnectError`. The plan's exception mapping therefore holds.

**PyJWT 2.15.1 (probe):**

- `require` accepts arbitrary claim names (a missing `events` gives `MissingRequiredClaimError`).
- An `iat` 600 s in the future gives `ImmatureSignatureError`.
- With `audience=` given, a missing `aud` is refused even when `aud` is not in `require`.
- The default header carries `typ: JWT` and overriding works; `get_unverified_header("not.a.jwt")` raises `DecodeError`.

**The plan's own code, run in the overlay:**

- Settings, redaction, verifier-knob, ID/logout-token and auth-helper tests: 62 passed.
- The Plan D and Plan E token and settings tests still pass, except the `test_settings.py` assertion on `localhost`, which the plan already says to update.
- The plan's `keycloak_admin` and `test_admin_users` (`httpx2.ASGITransport` exists; the `asyncio.wait_for` budget is honoured; single-flight token): 13 passed.
- Sweeper pure functions: 3 passed.
- `test_api_auth` and Plan D's `test_api`: 27 of 29 pass, the two failures being B4 and B5. This covers:
  - the login-CSRF test;
  - cookie and TestClient handling with `follow_redirects=False`;
  - `request.form()` with a JSON or empty body giving 400;
  - back-channel logout by sid with replay giving 400;
  - the 401 and 503 enabled-check mapping;
  - bearer and cookie precedence;
  - the safety of mutating `ROWS` (it is restored in `finally`).
- Starlette 1.7.0's `set_cookie` and `delete_cookie` signatures match `CookiePolicy`, and the attribute assertions pass.

**Revision 0005 (overlay):**

- `GRANT_EXECUTION_0004` equals 0004's `GRANT_EXECUTION` byte for byte, and `HEADER` and `GRANT_COLUMNS` match.
- No upgrade or downgrade statement carries an SQLAlchemy bind.
- The rendered GRANT and REVOKE statements match the matrix, and the downgrade restores 0002's sweeper `DELETE`-only cell on `sessions`.

**Catalog facts (dev, read-only):**

- `jobs` has `jobs_tenant_iff_run_check CHECK ((run_id IS NULL) = (tenant_id IS NULL))` and `jobs_dedup_key_key UNIQUE (dedup_key)`. A tenant-less, run-less maintenance row is therefore legal, and `ON CONFLICT (dedup_key)` has an arbiter.
- `SELECT … FOR UPDATE` on `memberships` without DISTINCT plans fine.

**Grants and RLS:**

- The sweeper holds `jobs` sel/ins/upd(claimed_by, claimed_at, done_at, attempts) under `sweeper_all`, enough for `claim_maintenance_job`'s `UPDATE … FOR UPDATE SKIP LOCKED … RETURNING *`.
- `memberships` sel plus column UPDATE covers the sync's UPDATEs.
- The `api` cells cover every `DbStore` session statement: SELECT is present for the WHERE and RETURNING clauses, and `logout_jti` is a target-less `ON CONFLICT` with INSERT only (spike §5).
- `persistence.Session.unit()` is a real transaction (`persistence.py:146-151`), so `record_logout` is atomic.

**mypy:** with B1's rename and B3's override, the plan's `ops_core`, `ops_api` and `ops_sweeper` code passes `mypy --strict`. The f-string SQL in `purge_expired` is accepted.

**Repository facts the plan relies on:**

- `tool_error` already carries `retryable` (`mcp-write/src/ops_mcp_write/server.py:60-62`).
- `approved_run(app_conn, api=, worker=)` exists and uses the seeded ALPHA tenant.
- `persistence.Refused.code` and `Grant.run_id` exist.
- `kc.token_password` and `kc.token_client_credentials` have the signatures the plan uses.
- The realm test helpers `clients()`, `users()` and `audiences()` exist.
- `test_bootstrap_dev` requires compose secrets to equal `SECRET_NAMES`, which the plan satisfies.
- The Keycloak entrypoint exports `kc_client_secret_ops_test_admin` as `OPS_KC_CLIENT_SECRET_OPS_TEST_ADMIN`.
- `bootstrap_dev.py up` does not migrate the database.
- `skeleton.py migrate` targets `app@head` and `heads`.

**pytest-asyncio 1.4:** an autouse `pytest_asyncio.fixture` runs for synchronous tests too (probe: 2 passed).

---

## Round 1 — builder dry run

# Plan F dry run, round 1: builder report

Plan: `docs/superpowers/plans/2026-10-08-first-slice-f-sessions-login-sync.md` at `4f14f95`, executed literally in the
throw-away worktree `scratchpad/planf-dryrun` (detached HEAD). Commits made: `e00a9a6..a777052` (8 commits, one per
plan commit step). No secret, token, code, cookie or session value appears below; status codes and counts only.

## Summary

| Task | Status | WA | Gate result (dev / test passed-skipped; vh = verify_handoff exit) |
|---|---|---|---|
| 1 Debt, deps, secrets, settings, redaction | DONE-WITH-WORKAROUNDS | 4 | dev 546/82 GREEN; test 607/21 GREEN; vh 0 |
| 2 Rev 0005, realm, stale rule | DONE-WITH-WORKAROUNDS | 4 | dev 552/83; test 614/21 GREEN (R105 not red); vh 0 |
| 3 Admin client, auth helpers, store | DONE-WITH-WORKAROUNDS | 4 | dev 611/83 GREEN (mypy red first); vh 0 |
| 4 Routes, dependencies, negatives | DONE-WITH-WORKAROUNDS | 6 | dev 629/83 GREEN; test 691/21 GREEN; vh 0 |
| 5 The sweeper | DONE-WITH-WORKAROUNDS | 6 | R105 ERROR, dev RED first; then dev 633/83, test 695/21; vh 0 |
| 6 Live proof | DONE-WITH-WORKAROUNDS | 2 | auth live 4 passed; test 699/21 GREEN; dev 633/87 GREEN; vh 0 |
| 7 Handoff, docs, final gates | DONE-WITH-WORKAROUNDS | 3 | dev 633/87 GREEN; test 699/21 GREEN; vh 0 |

The three blocking defects (each would stop an executor who follows the text): **T3-1** (`DbStore.session` attribute
vs the new `session()` method), **T5-5** (`SELECT DISTINCT … FOR UPDATE` in the sync; the sweeper never becomes ready)
and **T5-6** (`tests/plan_a/test_layout.py` turns `check.py` red once `sweeper` is a workspace member). Next in weight:
**T4-3** (a unit test in the plan that fails as written), **T4-5/T4-6** (the manual API probe cannot work as written)
and **T2-4** (the declared interim red for R105 never happens, so R105 proves nothing about the sweeper).

## Task 1

1. **Naming inconsistency (defect, no workaround).** Ruling 22, the Architecture paragraph and the Task overview row
   name `ops_core.logging` and `tests/plan_f/test_logging_redaction.py`; the overview row also lists
   `test_privileges_f.py` under Task 1. Task 1's Files/Steps create `core/src/ops_core/redaction.py` and
   `tests/plan_f/test_redaction.py`, and `test_privileges_f.py` is created in Task 2. I followed the task text.
   Fix: change ruling 22, the Architecture paragraph and the overview row to `ops_core.redaction` /
   `test_redaction.py`, and move `test_privileges_f.py` to the Task 2 row.
2. **Step 4, `sessions()` docstring (workaround).** The plan's verbatim line
   `"""`OPS_PUBLIC_BASE_URL` must be a bare origin; … (BUILD_SPEC §9's exception)."""` is 121 characters (the
   one-liner prints `core/src/ops_core/settings.py 217`). I wrapped it after "§9's". Fix: wrap it in the plan.
3. **Step 9, `testpaths` (workaround).** Adding `"tests/plan_f"` makes `pyproject.toml` line 46 121 characters. I split
   the list over three lines. Fix: give the multi-line list in the plan.
4. **Step 8, "with the docstring line" (workaround).** `TokenVerifier` has no class or `__init__` docstring today, so
   there is no docstring to add the line to. I made it the `__init__` docstring. Fix: say where it goes.
5. **Step 9 / Global Constraints, evidence restore (workaround).** After the live run, `git status` showed
   `M reports/skeleton/r105-walking-skeleton.txt` as well as the two `reports/bootstrap` files. The plan only says
   `git checkout -- reports/bootstrap`, and the Task 1 commit list does not include the R105 file. I also restored
   `reports/skeleton`. Fix: Global Constraints and Task 1 Step 9 should say
   `git checkout -- reports/bootstrap reports/skeleton`, as Task 2 Step 7 already does.
6. **Step 9 (note).** Step 9 does not list `verify_handoff.py`, although Global Constraints require it after every
   task. I ran it: exit 0. Fix: list it in each task's gate step.
7. Matched the plan: the locked versions are **authlib 1.8.0** and **joserfc 1.7.5** (cryptography 50.0.2 was already
   locked); `bootstrap_dev.py secrets` → `secrets: 2 created, 20 kept`; `tests/plan_b/test_bootstrap_dev.py` and
   `test_compose_dev.py` gave 13 passed, 1 skipped (POSIX mode bits). Every red-then-green step failed and then passed
   as claimed (9 failed → pass; collection error → 3 passed; 3 failed → 31 passed). The Plan D settings assertion
   needed the `127.0.0.1` update the plan predicted.

## Task 2

1. **Step 1, privileges docstring (workaround, ambiguous text).** "The 'Four departures' sentence becomes 'Six
   departures … and (Plan F) …'" does not give the full sentence. I wrote the two new departures into the existing
   list and re-wrapped the docstring. Fix: give the full replacement paragraph.
2. **Step 1, `NO_RLS` (workaround).** With `"login_state", "logout_jti"` added, the one-line tuple goes over 120
   characters. I put it on multiple lines (one name per line). Fix: show the multi-line tuple.
3. **Step 3, `test_revision_0005_bodies_differ_only_by_the_stale_rule` (workaround; the code block is wrong).** The
   block uses `privileges.GRANTS`, and the run gives `NameError` at `tests/plan_f/test_privileges_f.py:29`. The
   parenthetical says to use `p.GRANTS`; I did. Fix: write `p.GRANTS` in the code block and drop the parenthetical.
4. **Step 7 / Global "Interim red" (defect in the prediction).** The plan declares R105 red from Task 2 until Task 5.
   It was **green**: `--profile test` gave 614 passed, 21 skipped, and R105 alone took 11.72 s for its call and
   passed. The cause: the autouse `fresh_memberships` fixture stamps `synced_at` before R105, and the run finishes long
   before 120 s. As a result, R105 in Task 5 does not prove that the sweeper keeps the rows fresh. Fix: remove the
   interim-red paragraph and the Task 2/3 notes, and give Task 5 a real proof (for example, R105 opts out of
   `fresh_memberships`, ages the rows past 120 s before the grant, and asserts that the skeleton's sweeper re-stamps
   them).
5. **Step 5, the `ops-test-admin` one-off (workaround).** A script outside the e2e fixtures has no environment:
   `settings.read_secret` raised `SettingsError: OPS_SECRETS_DIR is not set`. I exported `OPS_SECRETS_DIR` from
   `.env`. Results: token 200, `GET /admin/realms/ops-dev/users/{alex}` **200**, `PUT {"enabled": true}` **204**, and
   alex was still enabled afterwards. Fix: tell the executor to export `OPS_SECRETS_DIR` (and `OPS_PG_PORT`) from
   `.env`, or to call `scripts.skeleton.export_environment(load_dotenv(".env"))` first.
6. **Step 3, risk (no workaround).** `test_the_newest_revision_of_every_cell_equals_the_live_matrix` merges every
   `GRANTS_*` attribute of a revision in `dir()` order. 0005 has both `GRANTS_0002_SESSIONS` (the old cells, for the
   downgrade) and `GRANTS_0005`. The test passes only because `GRANTS_0002…` sorts before `GRANTS_0005`. Fix: rename
   the downgrade copy so it does not start with `GRANTS_` (for example `DOWNGRADE_SESSIONS_0002`).
7. **Step 5 (note).** The plan's verbatim `ops-test-admin` description line in the realm JSON is 146 characters
   (JSON is exempt in practice; the runbook has 20 longer lines already).
8. Matched the plan: `test_the_newest_revision…` failed until Step 3; the stale test failed `DID NOT RAISE Refused`
   before 0005; the frozen `GRANT_EXECUTION_0004` is byte-identical to 0004's `GRANT_EXECUTION` (checked by import);
   the Step 4 live schema tests gave 25 passed; `tests/plan_b` gave 39 passed, 10 skipped; the realm re-import worked
   (`down`, `up`, "bootstrap admin: deleted"); `tests/plan_b/live` gave 9 passed; the Step 6 unit tests gave
   15 passed. The R006 "columns absent after the downgrade" check passes trivially, because at `0001` the whole
   `sessions` table is gone.

## Task 3

1. **Step 5, `DbStore.session` is both an attribute and a method (BLOCKING; workaround).** `DbStore.__init__` sets
   `self.session = persistence.Session(conn)`. The plan adds `async def session(self, session_sha256, *,
   idle_seconds)` to the same class, and every new method uses `self.session.unit()`. mypy reports 18 errors
   (`store.py:215: Cannot assign to a method [method-assign]`, `"def session(...)" has no attribute "unit"`, and
   `app.py:98/104/169: … has no attribute "conn"/"ping"`). At runtime the instance attribute hides the method, so the
   cookie path's `store.session(...)` call would raise `'Session' object is not callable`. Task 4's `app.py` uses
   both `app.state.store.session.conn` and `store.session(...)`. Workaround: I renamed the attribute to
   `self.units` in `store.py` and in the three `app.py` references, and used `.units.conn` in Task 4's lifespan.
   Fix: rename the attribute in the plan (Task 3 SQL methods and Task 4 lifespan), or rename the method (for
   example `live_session`).
2. **Step 5, authlib is untyped (workaround).** `uv run mypy api/src core/src` reports `api/src/ops_api/auth.py:25:
   error: Library stubs not installed for "authlib.integrations.httpx_client" [import-untyped]`. authlib 1.8.0
   ships no `py.typed`, and the plan forbids `type: ignore`. I added a `[[tool.mypy.overrides]]` block
   (`module = ["authlib.*"]`, `ignore_missing_imports = true`) to the root `pyproject.toml`. Fix: put this in
   Task 1 Step 2 next to the dependency, and add `pyproject.toml` to Task 3's commit list.
3. **Step 4, comment over 120 characters (workaround).** The comment in `AuthlibOidc.exchange`
   (`# `error` is the OAuth error code …`) is 122 characters (`api/src/ops_api/auth.py 180 122`). I wrapped it.
4. **Step 6, commit list (workaround).** Because of items 1 and 2, `api/src/ops_api/app.py` and `pyproject.toml`
   changed, but neither is in the `git add` line. I added both.
5. **Interfaces and ruling text (defect, no workaround).** Files says "seven `Store` methods" and the docstring says
   "six session operations"; the code has six (`begin_login`, `take_login`, `create_session`, `session`,
   `revoke_session`, `record_logout`). The Task overview names `revoke_sessions_by_sid` and `record_logout_jti`,
   which do not exist. Ruling 16 promises "every session of that `sub` whose `sid` is empty" as belt and braces, but
   `record_logout` revokes by `sid` only. Fix: align the overview and Files with the code, and either implement the
   `sub` clause or drop it from ruling 16.
6. **Warning (note).** The HS256 negative in `test_id_and_logout_tokens.py` (key `"x"`) triggers PyJWT's
   `InsecureKeyLengthWarning`. From here on, every `check.py` summary shows `1 warning`. Fix: use a 32-byte HMAC key
   in the negative.
7. Matched the plan: `test_admin_users.py` gave 13 passed (`httpx2.ASGITransport` exists); the helpers and token
   tests gave 46 passed; `ruff check --fix` fixed one issue in the plan's code.

## Task 4

1. **Step 3, `store.session.conn` in the lifespan (carried workaround from T3-1):** I used `store.units.conn`.
2. **Step 3, `tests/plan_d/test_api.py::test_identity_and_membership` (workaround).** It compares the exact `/me`
   dictionary. With `"auth"` added it fails: `Left contains 1 more item: {'auth': 'bearer'}`. The plan's list of
   `test_api.py` changes does not include it. I added `"auth": "bearer"`. Fix: list it in Files and Step 1.
3. **Step 2, `test_session_expiry_revocation_and_logout` fails as written (workaround).** After the idle expiry, the
   first row is expired but not revoked (the 401 clears the cookie, so the second login has no previous session to
   revoke). `key = next(k for k, e in fake.sessions.items() if not e["revoked"])` therefore picks that dead row again,
   and the new session stays live: `assert 200 == 401` at `tests/plan_f/test_api_auth.py:145`. I changed it to
   `key = list(fake.sessions)[-1]`. Fix: select the newest row (or revoke on idle expiry, if that is the intended
   behaviour).
4. **Step 4, lint on the plan's tests (workaround).** Ruff reports `RUF059 Unpacked variable fake is never used`
   three times (`c, fake, deps = world` in three tests). I renamed it to `_fake`. Ruff `--fix` also removed five
   unused imports (`AdminUnavailable`, `FakeAdmin`, `FakeIdTokens`, `FakeLogoutTokens`, `FakeOidc`). Fix: correct the
   plan's test code.
5. **Step 4, the manual API start (workaround).** `PYTHONUTF8=1 uv run python -m ops_api` fails at startup:
   `SettingsError: OPS_SECRETS_DIR is not set` … `Application startup failed. Exiting.` I exported `OPS_SECRETS_DIR`
   and `OPS_PG_PORT` from `.env` (what `skeleton.export_environment` does). After that, `/health/ready` returned
   `{"status":"ready"}`. Fix: give the export line, or start through the skeleton's environment.
6. **Step 4, `curl -sI …/auth/login` (workaround).** `-I` sends HEAD, and the route answers
   `HTTP/1.1 405 Method Not Allowed` (`allow: GET`). With a GET it answered `HTTP/1.1 503`
   `{"code":"UNAVAILABLE","message":"database unavailable","retryable":true}` with no Location header. The
   paragraph contradicts itself (a 303 with `code_challenge_method=S256`, then "will answer 503"). On the dev database
   at 0004 only the 503 can be observed. Fix: use `curl -s -o /dev/null -D - …`, expect the 503, and drop the 303
   claim (or move it to Task 6).
7. **Step 4 (note).** "prove the lifespan (discovery, JWKS, admin token) completes": no admin token is fetched at
   startup (the token source is lazy). The log shows only the JWKS and well-known GETs. Fix: drop "admin token", or
   have the lifespan fetch one.
8. **Gate (note).** Global Constraints require the live suite after a task that changes a service. Step 4 does not
   list it. I ran it: GREEN, 691 passed, 21 skipped.
9. Observation: after `redaction.install()` sets the root logger to INFO, the API logs `httpx2` request lines (the
   URLs carry no secret values; my scan of every runtime log for `Bearer `, `password=`, `eyJ`, `code=`, `state=`,
   `ops_session=` and `refresh_token` found 0 hits).

## Task 5

1. **Step 2, ordering (workaround, need not verified).** `uv lock && uv sync --locked` comes in Step 2, but
   `sweeper/src/ops_sweeper/` is created only in Step 3, and hatch is configured with
   `packages = ["src/ops_sweeper"]`. I created `__init__.py` before locking. Fix: create the package skeleton in
   Step 2.
2. **Step 2, the `insert_maintenance_job` docstring contradicts the plan's own note (workaround).** The code block
   says "a target-less ON CONFLICT DO NOTHING needs INSERT only", but the SQL is `ON CONFLICT (dedup_key)`, and the
   note below it says the comment must say that a target needs SELECT. I rewrote the docstring. Fix: correct the code
   block.
3. **Step 2, SQL line over 120 characters (workaround).** The INSERT string is 121 characters. I split it.
4. **Step 3, `sync.py` lint (workaround).** Ruff `ISC004` flags the implicitly concatenated `sessions` WHERE string
   inside the purge tuple. I ran `ruff check --select ISC004 --fix --unsafe-fixes`, which added parentheses.
5. **Step 4, `SELECT DISTINCT … FOR UPDATE` (BLOCKING live defect; workaround).** The first R105 run errored with
   `RuntimeError: not ready in 90.0s: ['sweeper']`. Every tick in `sweeper.log` ended with
   `psycopg.errors.FeatureNotSupported: FOR UPDATE is not allowed with DISTINCT clause`, so no sync ever happened and
   readiness never turned 200. I dropped `DISTINCT` (`plan()` removes duplicates through a `frozenset`). After that,
   R105 passed in 28.9 s and `sweeper.log` showed `membership sync: 5 rows checked, 0 deactivated`;
   `grep -c "Bearer \|password=" runtime/skeleton/*.log` gave 0 for all six logs. Fix:
   `SELECT subject FROM app.memberships WHERE issuer = %s AND active FOR UPDATE`.
6. **Step 5, `check.py` RED on the plan's own layout test (BLOCKING; workaround).** The dev gate gave 1 failed,
   632 passed: `tests/plan_a/test_layout.py::test_root_is_a_uv_workspace_excluding_reference`,
   `Extra items in the left set: 'sweeper'`. Once `sweeper` is added to `MEMBERS`, two more tests of that module
   need `__version__ = "0.0.1"` in `ops_sweeper/__init__.py` (the plan says "empty, one-line docstring") and a
   `sweeper/README.md` with `## Owns`, `## Trusts` and `## Never`. I made all three changes. After that: dev GREEN
   633 passed, 83 skipped; test GREEN 695 passed, 21 skipped. Fix: add `tests/plan_a/test_layout.py`, the README and
   `__version__` to Task 5's Files and commit list.
7. **Notes.** `skeleton.up()`'s docstring still says "five processes" (the plan updates only the module and
   `Skeleton` docstrings), and the runbook's step 4 still says "its own five processes". A tick whose sync raises
   leaves its claimed job unfinished (`claimed_at` set, `done_at` NULL), so one stuck row builds up per failing
   minute. `minute_bucket()` re-implements `ops_core.jobs.dedup_key(JobType.SYNC_MEMBERSHIPS, minute_bucket=…)`,
   which already builds the same key.
8. Matched the plan: `test_sweeper.py` and `test_skeleton_cli.py` gave 6 passed; the R105 evidence changed
   (timestamp and ids) and was committed as Step 5 says.

## Task 6

1. **Step 2, lint on the plan's live module (workaround).** Ruff reports `ASYNC251 Async functions should not call
   time.sleep` at the back-channel poll and the sync poll. I used `await asyncio.sleep(...)` and added
   `import asyncio`. Ruff `--fix` also fixed two other issues (unused imports).
2. **Note (c), `test_evidence.py` (workaround, no code given).** I added `Path("reports/auth")` to `EVIDENCE_ROOTS`
   and re-wrapped the docstring. Fix: give the two-line diff.
3. **Step 3 (note).** "record the four `lines`": the evidence file has a header plus six lines.
4. Note (b) checked: the partial `PUT {"enabled": false}` worked (204, then `enabled` was False). In `finally`, sam
   was re-enabled; all five personas show `enabled: True` afterwards.
5. Live result: `tests/e2e/test_auth_live.py` gave **4 passed in 78.16 s**. The API log shows
   `back-channel logout revoked 1 session(s)` twice and `back-channel logout token rejected: unknown signing key`
   once; the sweeper log shows `membership sync: 5 rows checked, 1 deactivated`. Evidence (final run, verbatim; it
   holds only codes and counts):

   ```text
   T11 sessions and revocation — 2026-10-09T07:54:44Z
   login: me=200 csrf_refusals=[403, 403, 403, 403] mutation_with_token=201
   idle expiry: me=401
   logout: 204; keycloak shows the login form again: True
   back-channel logout: sibling me=401, jti rows +1, sessions revoked 2
   forged logout token: 400
   disabled user: decision=401 synced_after=19.2s me=401
   ```

   (The two earlier runs gave `synced_after=48.4s`; all three are within the 60 s bound.)

## Task 7

1. **Step 2, the `privileges.py:150` comment (workaround).** Line 150 is now `"invocation_context",` (the Plan F
   edits moved the code); the target is the `resolve_identity` row at line 166. The plan's verbatim end-of-line
   comment makes that line 125 characters, so `ruff format --check` would split the tuple over four lines. I put
   the comment on its own line above the row. Fix: name the row, not the line number, and give the comment its own
   line.
2. **Step 2, "STATUS.md: a row for T11" (workaround, ambiguous).** `STATUS.md` has no per-task table; earlier plans
   added `## Update — Plan X executed` sections. I followed that precedent.
3. **Step 2, "Open items parked by the task reviews (from the ledger)" (workaround).** There is no review ledger in a
   literal run. I wrote "none recorded". Fix: name the ledger file, or make the item conditional.
4. Notes: on a detached HEAD, `<first>..<last>` was filled with hashes (`e00a9a6..63c77af`). The plan does not say
   where the "Plan F executed" section goes in `SESSION_STATE.md` (I put it after "Plan E executed"). `STATUS.md`
   and `README.md` say nothing about the shared Keycloak now running the Plan F realm.

## Final gate numbers

| Gate | Result |
|---|---|
| `scripts/check.py` | CHECK: GREEN, 633 passed, 87 skipped, 1 warning (33.1 s) |
| `scripts/check.py --profile test` | CHECK: GREEN, 699 passed, 21 skipped, 1 warning (158.8 s) |
| `verify_handoff.py --reference-code --manifest --contracts` | exit 0 (7 PASS lines, 1 LIMIT) |
| `tests/e2e/test_auth_live.py` alone | 4 passed (78.16 s) |
| R105 with six processes | passed (28.9 s), after the T5-5 fix |
| mypy (`api/src core/src`, `sweeper/src core/src`) | clean, after the T3-1 and T3-2 workarounds |

The 21 skips under the test profile are the same as before Plan F: 19 schema-conformance skips, the seal, and the
POSIX mode bits. The dev profile skips grow from 82 to 87 because the new live tests are skipped there.

Sweeper log lines seen: `membership sync: 5 rows checked, 0 deactivated` (every sync without a disabled user) and
`membership sync: 5 rows checked, 1 deactivated` (the disable test).

## Cleanup proof

- Processes: `scripts/skeleton.py status` shows all six `down`, and `netstat` shows no listener on 8000, 8070, 8071,
  8081, 8082, 8090, 18081 or 18090. The manual API (PID from `netstat`) was stopped with `taskkill`, and no `python`
  processes remained.
- Dev databases untouched: `ops` alembic = `['0004_write_path_functions']`, `to_regclass('app.login_state')` = None;
  `incident` = `['0002_destination_hardening']`. Schemas: `ops` = `app, public`; `incident` = `incident, public`.
- Roles: no `critic%` role (`[]`). Roles present: `api, app_definer, incident, incident_owner, mcp_exec, mcp_read,
  migrator, operator, ops, sweeper, test_harness, worker` (unchanged set).
- Databases: `incident, incident_test, ops, ops_test, postgres, template0, template1` (`*_test` are the fixtures'
  per-session databases, now at 0005).
- Realm users (as `ops-test-admin`): `alex, jordan, lee, riley, sam`, all `enabled: True`. No `critic_*` object was
  created anywhere; nothing was deleted.
- Dev stack: `ops-copilot-keycloak-1` and `ops-copilot-postgres-1` are up and healthy.
- **Shared-state side effects the owner should know about:** (a) `bootstrap_dev.py secrets` created
  `api_session_key` and `kc_client_secret_ops_test_admin` in the shared per-user secrets directory (as the plan
  intends). (b) The Task 2 Step 5 re-import ran from the worktree, so the shared Keycloak now carries the Plan F
  realm: the `ops-test-admin` client with `manage-users`, and `ops-web`'s back-channel attributes. These stay until
  the next `bootstrap_dev.py down`/`up` from the real checkout, which will drop them.

## Files I created that the plan did not name

- `sweeper/README.md` (needed by `tests/plan_a/test_layout.py`, T5-6).
- Files changed that the plan does not list: `tests/plan_a/test_layout.py` (T5-6), the root `pyproject.toml` mypy
  override (T3-2), and `api/src/ops_api/app.py` in Task 3 (T3-1). Outside the worktree, scratch only: one-off
  scripts `oneoff_test_admin.py`, `oneoff_sam_check.py` and `oneoff_cleanup_proof.py` (they print status codes,
  flags and names only), a code-block extractor `extract.py`, and the gate logs, all in the session scratchpad.

---

## Round 2 — static critic

# Plan F round 2: static critic report

Plan: `docs/superpowers/plans/2026-10-08-first-slice-f-sessions-login-sync.md` (branch `plan-f`, 8acbddc). Line
numbers are plan lines unless a file is named.

**Closure: 67 closed / 6 partial / 1 open / 8 not applicable (82 rows).**
**New findings: Blocking 2 / Important 3 / Minor 11.**

## How the evidence was gathered

- **Overlay.** I copied the round-1 overlay (`scratchpad/planf-critic/ov`) to `scratchpad/planf-critic2/ov`. I then
  regenerated these modules verbatim from the current plan's code blocks with a fence extractor (`ex.py`):
  - `redaction.py`, `keycloak_admin.py` and `auth.py`;
  - the sweeper's `sync.py`, `main.py` and `__init__.py`;
  - every `tests/plan_f` unit module, `auth_fakes.py` and `test_api_auth.py`.

  I patched the round-1 `settings`, `tokens`, `store`, `persistence` and `app` copies with this round's deltas:
  - the `isfinite` check;
  - `invalidate()`;
  - `assert_relation` and the new `insert_maintenance_job`;
  - the `/auth/login` host redirect and `assert_relation` in the lifespan;
  - `live_session` (already applied in round 1);
  - the `/me` `"auth": "bearer"` and `FakeStore.live_session` edits in `tests/plan_d/test_api.py`.
- **Unit tests** (`uv run --with authlib==1.8.0`, overlay first on `PYTHONPATH`):
  - With the plan's `redaction.py` taken verbatim, every module importing `ops_core.redaction` fails to import (N3).
  - With that one stray line deleted, `tests/plan_f` plus `tests/plan_d/test_api.py` gave **109 passed, 0 failed**. By
    module:
    - `test_api.py` 11;
    - `test_admin_users` 14;
    - `test_api_auth` 18;
    - `test_auth_helpers` 13;
    - `test_id_and_logout_tokens` 33;
    - `test_redaction` 3;
    - `test_settings_auth` 9;
    - `test_sweeper` 4;
    - `test_tokens_knobs` 4.

    The run used `-W error::UserWarning`, so the HS256 key warning is gone.
- **mypy.** `mypy --strict` with the `authlib.*` override over the overlay (`ops_core`, `ops_api`, `ops_sweeper`):
  `Success: no issues found in 24 source files`.
- **ruff.** `ruff check` over the plan's new modules and tests, using the repository config, gave:
  - ISC004 in `sync.py`;
  - RUF100 (unused `# noqa: BLE001`) in the sweeper's `main.py`;
  - FURB167 twice in `kc_browser.py`;
  - I001 only because the files sit outside the repository.
- **Probes:**
  - authlib 1.8.0 (`token = None` after `fetch_token`, `aclose`);
  - the plan's `redact()` against 20 shapes;
  - the dev database, read-only as `ops`: memberships seed, policies, `jobs` columns, and `EXPLAIN` of
    `claim_maintenance_job`'s SQL.
- **Line lengths.** A Python character count over every code block of the plan.

Nothing in the repository was modified. No branch was switched, no container was touched, no live test was run, and
no secret was printed.

---

## A. Closure table

### Round-1 critic

| Item | Status | Evidence in the current plan |
|---|---|---|
| B1 `DbStore.session` collision | closed | `async def live_session(self, session_sha256: str, *, idle_seconds: int)` (2302, 2366); `row = await store.live_session(au.digest(raw), …)` (3090); the lifespan keeps `app.state.store.session.conn` (3046). mypy clean on the overlay. |
| B2 `DISTINCT … FOR UPDATE` | closed | `"SELECT subject FROM app.memberships WHERE issuer = %s AND active FOR UPDATE"` (3544); live `tests/e2e/test_sweeper_live.py` added (3797-3893). |
| B3 authlib untyped | closed | `[[tool.mypy.overrides]] module = ["authlib.*"] ignore_missing_imports = true` in Task 1 Step 2 (137-142). |
| B4 `/me` exact dict | closed | "`test_identity_and_membership`'s expected `/api/v1/me` dict gains `"auth": "bearer"`" (2747); passes on the overlay. |
| B5 wrong session aged | closed | `before = set(fake.sessions)` … `key = next(k for k in fake.sessions if k not in before)` (2892-2894); passes. |
| I1 60 s cadence | closed | Ruling 12: "Every 30 s it runs the sync, then records it as the maintenance job"; `tick` calls `run_sync` every tick (3671-3677); the first tick syncs at once. |
| I2 SSO lifetimes | closed | `"ssoSessionIdleTimeout": 28800,` and `"ssoSessionMaxLifespan": 28800,` (1070); pinned in `test_realm_name_and_roles` (1121). Both are valid `RealmRepresentation` integer fields. |
| I3 interim red / R105 proof | closed (follow-ups in N5) | Global "No interim red across tasks" (27); `@pytest.mark.sweeper_stamps` on R105 and a fixture early return (3895). |
| I4 live store test, live gates | **partial** | `tests/e2e/test_sessions_store_live.py` and `--profile test` in Tasks 3 and 4 (2531, 3324). Still missing: the "rolled-back revocation does not consume the jti" case the module docstring promises (2441); `test_record_logout_is_atomic_and_replay_safe` tests replay only (N14). |
| I5 redaction shapes | closed (residue in N10) | `_SECRET_KEYS` with `client_secret` and the cookie names; patterns for Basic, the quoted key and `x-csrf-token` (487-502); six new canaries (416-421). |
| I6 errata | closed (inconsistency in N12) | Errata (32), (33) and (34) in Task 7 Step 2 (4287). |
| M1 naming and interfaces | closed | Ruling 22 says `ops_core.redaction`; ruling 16 says "revocation by `sub` is not needed"; the Architecture paragraph says "the `code_verifier` stored as is"; the `insert_maintenance_job` docstring says a target needs SELECT and builds the key with `dedup_key(job_type, minute_bucket=…)` (3455-3463). |
| M2 unwrappable long lines, `p.GRANTS` | closed | The three lines are now ≤120 characters (2004 is 115, 3466 is 59); `{t: p.GRANTS[t] for t in module.TABLES}` (1061). No Python string, comment or docstring line in any code block is over 120 characters (character count; see N8 for TOML). |
| M3 curl HEAD probe | closed | Task 4 Step 4: "do not start it by hand against the dev database" (3324). |
| M4 vacuous R006 assertion | closed (placement issue in N13) | A downgrade to `0004_write_path_functions` with the column, `has_table_privilege` and `pg_get_functiondef` checks (765-777). |
| M5 pytest handler pollution | closed | `before = {id(h): list(h.filters) …}` / `finally: handler.filters[:] = before.get(...)` (444-455). |
| M6 `python-multipart` | closed (line length in N8) | `"python-multipart>=0.0.20,<1"` in the api dependencies (135). |
| M7 sweeper README | closed | `sweeper/README.md` with `## Owns`, `## Trusts`, `## Never` (3426-3447). |
| M8 docstrings | **partial** | Most are added. Still none on `CookiePolicy.set_session/set_login/clear_session/clear_login` (2205-2219), `AuthDeps.aclose` (2238), `Identity.auth` (3024), `no_store` (3146), or `landing` (comment only, 3142). |
| M9 HS256 warning | closed | `HS_KEY = "k" * 32` (1689); no warning under `-W error::UserWarning`. |
| M10 log grep | closed | `grep -cE "Bearer [^[]\|password=[^[]"` (3895). |
| M11 nan/inf | closed | `if not math.isfinite(value) or value <= 0` (360); the test loops over `("0", "nan", "inf", "soon")`. |
| M12 restart waits a minute | closed | "The first tick syncs immediately" (53); `run_sync` runs every tick. |
| M13 `GRANTS_0002_SESSIONS` | closed | `SESSIONS_CELLS_0002`, with a comment saying why (877-884, 1043). |
| M14 authlib keeps tokens | closed | `finally: self._client.token = None` (2008-2011); `oidc.aclose` in `closers` (3314). Probe: retained before True, after None; `aclose` works. |
| M15 admin token never invalidated | closed | `if response.status_code == 401: self._tokens.invalidate()` and one retry (1479-1483). `test_a_stale_token_is_replaced_once` checks `token_calls == 3` (t1 refused, t3 accepted); the 401 parameter case checks `== 2`. Both pass. |
| M16 sam restore races the sweeper | closed (new defect in N2) | The restore moves to the module fixture after `sk.stop()` (4066-4078). It does not restore `permission_version` (N2). |
| M17 partial PUT probe | closed | The `lee` probe compares `username`, `email`, `firstName`, `lastName` before and after (1137). |
| M18 job-row debt | closed | Debt line "… done maintenance rows accumulate … → T14" (86). |
| RF1 127.0.0.1 vs localhost | **partial** | `/auth/login` redirects to the public host (3156-3160), pinned by `test_login_redirect_shape` (2792-2794). This breaks Task 6's own browser helper (N1). |
| RF2 Keycloak session ends first | closed | The realm SSO lifetimes are 8 h (I2). |
| RF3 mass deactivation | closed (design defect in N4) | `MAX_DEACTIVATION_FRACTION = 0.5` and `MassDeactivation` (3519-3551); live refusal test (3862-3874). |
| RF4 lost back-channel POST | **partial** | Documented in ruling 16 and the runbook paragraph (3895). The "pin the 5xx path" half is absent: no test makes `record_logout` fail and asserts the endpoint's answer. |
| RF5 dev database before 0005 | closed | `persistence.assert_relation` in the API lifespan and the sweeper (3047, 3738); runbook and SESSION_STATE text (3895, 4288). No unit test pins the guard (failure mode 4 below). |

### Round-1 builder

| Item | Status | Evidence |
|---|---|---|
| T1-1 naming (logging/redaction, overview) | closed | Overview row 1 lists `test_redaction.py`; `test_privileges_f.py` is in row 2 (103-104). |
| T1-2 `sessions()` docstring 121 | closed | 338 is ≤120 ("`http` is for localhost only"). |
| T1-3 `testpaths` long line | closed | Multi-line list (687-691). |
| T1-4 where the `TokenVerifier` docstring goes | closed | "`__init__` gains a one-line docstring (it has none today)" (630). |
| T1-5 restore `reports/skeleton` | **partial** | Global (26) and Tasks 1 and 2 say `git checkout -- reports/bootstrap reports/skeleton`. Tasks 3 (2531), 4 (3324), 5 (3899), 6 (4263) and 7 (4302) still say `reports/bootstrap` only. |
| T1-6 `verify_handoff` in every gate | **partial** | The Global sentence "`verify_handoff.py` runs in every task's gate step" (26) and Tasks 1 and 2 list it. The gate steps of Tasks 3-6 still omit it. |
| T1-7 matched | n/a | — |
| T2-1 privileges docstring | closed | Full replacement paragraph (749-756). |
| T2-2 `NO_RLS` line | closed | "`NO_RLS` becomes a multi-line tuple (one name per line…)" (747). |
| T2-3 `privileges.GRANTS` NameError | closed | `p.GRANTS` (1061). |
| T2-4 declared red never happens | closed | Global 27; `sweeper_stamps` marker (3895). |
| T2-5 one-off environment | closed | "`from scripts.skeleton import export_environment, load_dotenv; export_environment(…)`" (1137). |
| T2-6 `dir()` order | closed | `SESSIONS_CELLS_0002` (879). |
| T2-7 JSON line 146 | n/a | Still 146 characters (1088). JSON is exempt in practice. |
| T2-8 matched | n/a | — |
| T3-1 `session` attribute vs method | closed | `live_session` (see B1). |
| T3-2 authlib mypy | closed | The override is in Task 1, and Task 1's `git add` includes `pyproject.toml` (696). |
| T3-3 122-character comment | closed | 2004 is 115 characters. |
| T3-4 commit list | closed | Task 3's `git add` includes `persistence.py`, `tokens.py` and the live test (2534). No `app.py` change is needed any more. |
| T3-5 "seven/six", wrong names, sub clause | closed | "six `Store` methods" (1226); the overview names `live_session`, `record_logout` (105); ruling 16 drops the sub clause. |
| T3-6 HS256 warning | closed | `HS_KEY` (1689). |
| T3-7 matched | n/a | — |
| T4-1 `store.units.conn` | closed | Not needed: the attribute stays `session` (3046). |
| T4-2 `/me` dict | closed | (2747) |
| T4-3 expiry test | closed | (2892-2894) |
| T4-4 RUF059 and unused imports | closed | `c, _fake, deps` where `fake` is unused; the fakes' imports are trimmed (2771-2774). ruff shows only location-caused I001. |
| T4-5 manual API start | closed | Removed (3324). |
| T4-6 `curl -I` and the 303/503 contradiction | closed | Removed. |
| T4-7 "admin token" at startup | closed | Removed. |
| T4-8 live suite in Task 4 | closed | `--profile test` → GREEN in Step 4 (3324). |
| T4-9 observation | n/a | — |
| T5-1 package before lock | closed | "Create the package first (hatch needs `src/ops_sweeper` to exist before the lock)" (3416). |
| T5-2 docstring contradiction | closed | (3455-3460) |
| T5-3 121-character SQL literal | closed | Split over two literals (3465-3466). |
| T5-4 ISC004 in `sync.py` | **open** | The purge tuple still holds an unparenthesized implicit concatenation (3573-3575). ruff on the overlay reports `sync.py:72:17: ISC004`. `ruff check --fix` does not fix it, and the plan applies `--unsafe-fixes` to revisions only (N9). |
| T5-5 DISTINCT | closed | (3544) |
| T5-6 layout test, README, `__version__` | closed | `tests/plan_a/test_layout.py` in Files and commit list; `__version__ = "0.0.1"` (3421); README headings match `test_each_member_has_a_trust_boundary_readme`. |
| T5-7 "five" in docstrings, stuck jobs, bucket duplication | closed | `grep -n "five" … must find nothing` (3780). Insert, claim and finish now happen in one transaction (3680-3688). `dedup_key` builds the key. |
| T5-8 matched | n/a | — |
| T6-1 ASYNC251 | closed | `await asyncio.sleep(0.25)` and `(1.0)` (4182, 4246). |
| T6-2 `test_evidence` diff | closed | Note (c): `EVIDENCE_ROOTS = (…, Path("reports/auth"))` (4259). |
| T6-3 "four lines" | closed | "the header plus six" (4263). |
| T6-4 partial PUT works | n/a | — |
| T6-5 live result | n/a | — |
| T7-1 privileges comment line | closed | "the `resolve_identity` row … a comment line above the row" (4292). |
| T7-2 STATUS.md form | closed | "a `## Update — Plan F executed (2026-10-09)` section" (4292). |
| T7-3 ledger | closed | "in a literal run with no ledger write 'none recorded'" (4289). |
| T7-4 placement and README realm sentence | closed | (4290, 4292) |

---

## B. New findings

### Blocking

#### N1. The `/auth/login` host redirect breaks every Task 6 live test that logs in

- **Location:** Task 4 Step 3 `login` (3156-3160); Task 6 `tests/e2e/kc_browser.py` (`API = "http://127.0.0.1:8000"` at 3941, `start_login` at 3976-3980); `test_auth_live.py` (4119-4122, 4152, 4155, 4172).
- **Claim:** Task 6 Step 3 says the live module → PASS.
- **Evidence:**
  - `Browser.api = httpx2.Client(base_url=API, …)` sends `Host: 127.0.0.1:8000`.
  - The new route compares that with `urlsplit(public_base_url).netloc` (`localhost:8000`). It answers 303 with `Location: http://localhost:8000/auth/login`, and it stores no login row and sets no `ops_login` cookie. The overlay pins this: `test_login_redirect_shape`'s `elsewhere` assertion passes.
  - `start_login` asserts only the 303 and returns that Location. So `test_login_csrf_idle_expiry_and_logout` fails at once on `assert location.startswith(kcs.base_url + "/realms/ops-dev/protocol/openid-connect/auth?")`.
  - `browser.login(...)` would GET `http://localhost:8000/auth/login` on the Keycloak client, which is not a Keycloak page, so `keycloak_login` then fails its 200/302 assertion.
  - The back-channel test (`second_browser.start_login()`) fails the same way. Three of the four tests fail, along with the Task 6 and Task 7 gates.
  - The builder's round-1 Task 6 run passed only because the redirect did not exist yet.
- **Fix:**
  - Give `Browser.api` the public Host while still dialling 127.0.0.1 (which avoids the 2 s `::1` cost): `httpx2.Client(base_url=API, headers={"Host": "localhost:8000"}, …)`. httpx's jar keys cookies on the URL host, so cookies still round-trip.
  - Add a one-line assertion in `start_login` that the Location is not the API's own `/auth/login`, so the failure names the cause.

#### N2. Sam's `permission_version` is never restored, so `test_sweeper_live` fails after `test_auth_live` in the same session

- **Location:** Task 6 module fixture restore (4074-4078); `test_sweeper_live.py` (3851); Task 6 Step 3 and Task 7 Step 3 gates.
- **Evidence:**
  - The test databases are recreated once per session (`tests/e2e/conftest.py` `migrated`, session scope).
  - pytest runs `test_auth_live.py` before `test_sweeper_live.py` (alphabetical).
  - The disable test asserts `row["pv"] == 2` for sam. The seed has every row at `permission_version` 1 (dev catalog: five rows, all `active`, all pv 1).
  - The teardown runs `SET active = true, synced_at = …` and leaves pv at 2.
  - `test_sync_deactivates_disabled_and_deleted_and_stamps_the_issuer` then deactivates sam again, so pv becomes 3, and asserts `rows[SAM]["permission_version"] == 2`. The full `--profile test` run is red. Its own `restore()` would reset pv, but it runs in `finally`, after the failed assertion.
- **Fix:** restore `permission_version = 1` in the auth module's teardown. Better, make the sweeper test assert increments: read pv before and assert `+1` for sam and lee and `+0` for alex.

### Important

#### N3. `core/src/ops_core/redaction.py` as written is a SyntaxError

- **Location:** Task 1 Step 6, plan lines 486-491.
- **Evidence:**
  - The fix left the old header line `_PATTERNS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (` in place, directly above `_SECRET_KEYS = (`, and then repeated the header (`git diff 4f14f95..8acbddc`: the unchanged context line followed by the added block).
  - `ast.parse` on the extracted block gives `SyntaxError: '(' was never closed`.
  - Every entrypoint calls `redaction.install()`, so no service, test module or `check.py` run can import it. Task 1 Step 6's "→ PASS" cannot happen.
  - The comment "Order matters only where patterns overlap…" (484-485) now sits above `_SECRET_KEYS` instead of `_PATTERNS`.
- **Fix:** delete line 486 and move the two comment lines to just above the second `_PATTERNS`.
- **Verification:** with only that line deleted, all three redaction tests pass.

#### N4. The mass-deactivation guard turns a legitimate offboarding into a permanent fail-closed outage, and keeps explicitly disabled users active

- **Location:** `sync.py` (3548-3551); ruling 13; runbook paragraph (3895); `test_mass_deactivation_is_refused` (3380-3382).
- **Evidence:**
  - The guard refuses whenever `len(gone) > len(active) * 0.5`, and it counts subjects Keycloak *explicitly* reports `enabled: false` the same as absent ones. Some cases:
    - In the five-persona dev realm, disabling three personas (an ordinary "lock everyone but the admins out" response) trips it.
    - So does deleting the last remaining user (1 > 0.5).
    - So does any realm with one or two active subjects where one leaves.
  - Once tripped, every tick refuses and stamps nothing. `fresh()` turns readiness 503 after 120 s. `grant_execution` refuses every grant with `MEMBERSHIP_STALE` for every tenant. The worker re-queues every execute job every 30 s with no bound (TODO T13).
  - Nothing reactivates or overrides this: there is no setting, no runbook procedure, and the only signal is one `log.error` per tick.
  - Meanwhile the disabled users' memberships stay `active`. Session reads continue, because the admin check guards decisions only.
  - The guard's refusal path is pinned only live. The unit test named `test_mass_deactivation_is_refused` asserts the constant and `plan()`, not a refusal.
- **Fix:**
  - Apply the guard to *absent* subjects only. Absence is the ambiguous signal of a wrong or partial listing; an explicit `enabled: false` from the configured realm is affirmative, so always deactivate it.
  - Add a floor (for example, refuse only when absent > max(2, 50 % of active)).
  - Add a documented owner override (an `OPS_SYNC_ALLOW_MASS_DEACTIVATION=1` one-shot, or a runbook SQL step) and say in the runbook what readiness shows.
  - Extract the decision as a pure `refuse(active, users) -> bool` and unit-test it (all-disabled, all-absent, single-user realm, below and above the threshold).
  - Record the guard as a ruling with its cost.

#### N5. The R105/Task 6 "sweeper actually stamps" proof is prose only, and its one-sample reading is flaky

- **Location:** Task 6 Step 3 (4263); Global 27.
- **Evidence:**
  - Task 6 asks for a `SELECT min(synced_at)` "at the start of the first test and again before the back-channel assertions", to show that it "advanced within 75 s of the module's start". No code is given.
  - The skeleton's sweeper syncs during `sk.start()`, before the first test, and then every 30 s plus the tick duration.
  - The back-channel assertions run a few seconds after the first test starts. The builder's whole module took 78 s, of which the disable wait was 19-48 s, so tests 1-3 take roughly 10-30 s.
  - A two-sample comparison therefore often sees no tick in between and fails. The "within 75 s" clause only works as a poll, which the prose does not specify.
  - R105 itself asserts nothing about `synced_at`. With the marker it passes because readiness implies one sync, which is weaker than "keeps the rows fresh".
- **Fix:** give the code. Record `t0 = min(synced_at)` in the module fixture right after `sk.start()`. In the back-channel test, poll up to 45 s for `min(synced_at) > t0`, with an `asyncio.sleep(1)` loop and the elapsed time in the evidence line. Note that the fixture is opted out, so only the sweeper can have written it.

### Minor

#### N6. `/auth/login` host comparison: redirect loops with an explicit default port or a Host-rewriting proxy

- **Location:** 3156-3160 with `settings.sessions()` (337-350).
- **Evidence:**
  - `sessions()` accepts `http://localhost:80` or `https://ops.example.com:443`, whose `netloc` keeps the port. Browsers omit a default port from `Host`, so every `/auth/login` redirects to itself, forever.
  - A reverse proxy that does not preserve `Host` (T30) loops the same way.
- **Fix:** compare `(hostname.lower(), port or default)` pairs, or reject an explicit default port in `sessions()` with a unit case. Add a T30 debt line: "trusted proxy Host handling".

#### N7. Two code fences do not close in Markdown

- **Location:** lines 1062 (```` ``` Run `uv run ruff check …` ````) and 2432 (```` ``` The module docstring's … ````).
- **Evidence:** a closing fence may carry only spaces, and an info string on a backtick fence may not contain backticks. Each block therefore runs on to the next bare fence: Step 3's prose after 1062 and Step 4 render as code, and so does the text after `assert_relation`. Fence-based extraction (what the round-1 builder used) mis-splits the blocks.
- **Fix:** put the trailing text on its own line after a bare closing fence.

#### N8. The api dependency line is 142 characters

- **Location:** 135.
- **Evidence:** the plan's character-count gate runs on every touched file, and Task 1's own `testpaths` note acknowledges TOML lines count.
- **Fix:** give the multi-line `dependencies = [ … ]` form.

#### N9. `sync.py` still trips ISC004, and a `noqa` is dead

- **Location:** purge tuple (3573-3575); `main.py` `except Exception:  # noqa: BLE001` (3701); also `app.py`'s `# noqa: BLE001` (3256).
- **Evidence:** ruff reports ISC004 at `sync.py:72:17` (not auto-fixable without `--unsafe-fixes`) and RUF100 for the unused `BLE001` (BLE is not enabled). `--fix` strips the `noqa` and leaves a dangling `-- one bad tick…` comment.
- **Fix:** parenthesise the concatenated WHERE string. Turn the `noqa` reasons into ordinary comments (or enable BLE).

#### N10. Redaction residue: under-redaction of plan-relevant shapes, and over-redaction the docstring does not admit

- **Location:** `_SECRET_KEYS` and `_PATTERNS` (487-502).
- **Evidence (probe of the plan's `redact()`):**
  - These pass through unchanged:
    - `code_verifier=X` and `{'code_verifier': 'X'}` (the PKCE verifier this plan stores and posts);
    - `nonce=X`;
    - `{"password": "X"}`;
    - `FormData([('logout_token', 'X')])` (Starlette's repr of the back-channel form);
    - `'logout_token': b'X'`;
    - a bare `KEYCLOAK_IDENTITY=X`.
  - These are over-redacted:
    - `exit code=1` becomes `exit code=[REDACTED]`;
    - `Basic setup complete` becomes `Basic [REDACTED] complete`;
    - `bearer token missing` becomes `bearer [REDACTED] missing`.

    The Interfaces line accepts only the `state=` case.
- **Fix:**
  - Add `code_verifier|nonce|password` to `_SECRET_KEYS`.
  - Allow an optional `b` before the quoted value.
  - Add a tuple-repr pattern `\(['"](?:KEYS)['"],\s*['"]`.
  - Anchor `basic|bearer` to a preceding `authorization['"]?\s*[:=]\s*['"]?` or to a token-shaped value of 16 or more characters.
  - Add the canaries and state the accepted over-redactions in the docstring.

#### N11. Text inconsistencies an executor must resolve

- Task 4 Interfaces says `PersistenceError("<name> is missing; migrate the database")` (2548); the code says "…; run scripts/skeleton.py migrate for this profile" (2431).
- Task 7's Files line still says "errata 26–31" (4275), and its "Next task" line says "decide errata 26–31" (4286), while Step 2 lists 26–34.
- `tests/plan_a/test_layout.py`'s comment "the seven members of the workspace" goes stale when `sweeper` is added; the plan does not say to update it.
- `test_mass_deactivation_is_refused` (3380) does not test a refusal.
- **Fix:** align the texts; rename the test or make it test the pure guard (N4).

#### N12. The R006 0004-downgrade placement contradicts itself and was never executed

- **Location:** 762 and 780.
- **Evidence:**
  - Line 762 says to add the 0004 downgrade "before the first downgrade". Line 780 says "the `testclock@base` downgrade stays first".
  - The test runs with two heads (`0005…` and `tc_0001_test_clock`, whose `depends_on` is 0002).
  - No reviewer or builder has run `downgrade("app", superuser, "0004_write_path_functions")` with the testclock head still applied. Whether Alembic resolves that target with two heads is unproven.
- **Fix:** state one order. "After `testclock@base`, downgrade to 0004, assert, then downgrade to 0001" is the safe one, since it matches the existing single-head path.

#### N13. Per-task gate text still contradicts the Global rule (T1-5 and T1-6 residue)

- **Location:** 2531, 3324, 3899, 4263, 4302.
- **Evidence:**
  - These steps restore only `reports/bootstrap` and omit `verify_handoff.py`.
  - Task 3's and Task 4's live runs rewrite `reports/skeleton/r105-walking-skeleton.txt`, which their commit lists do not include.
  - An executor following the step leaves a dirty tree.
- **Fix:** repeat `git checkout -- reports/bootstrap reports/skeleton` and the `verify_handoff` line in each gate step.

#### N14. The live store test does not test the atomicity it is named for

- **Location:** 2511-2524; docstring 2439-2445.
- **Evidence:** only replay is covered. The case "a rolled-back revocation does not consume the token" (spike §5, round-1 I4) is absent.
- **Fix:** inside `async with conn.transaction(force_rollback=True)` (or a forced failure on the second statement), call the store's two statements on a raw `api` connection. Then assert that `record_logout` on the same jti still returns a count.

#### N15. A forged or unknown-`kid` logout token while Keycloak's JWKS endpoint is unreachable is a 500, not a 400

- **Location:** `backchannel_logout` catches only `TokenRejected` (3261-3265); `TokenVerifier.verify_async` (`core/src/ops_core/tokens.py:160-171`) calls `load_keys()` on an unknown kid.
- **Evidence:** an httpx2 transport error from `load_keys` propagates out of the endpoint. The callback has the same shape (3203-3206), giving a 500 for an ID token with a rotated kid while Keycloak is down.
- **Fix:** map the JWKS refresh failure to `TokenRejected` (400) at the back-channel endpoint, and to a retryable 503 at the callback. Add a unit case with a verifier whose refresh raises.

#### N16. The back-channel test leaks a client

- **Location:** 4169-4190.
- **Evidence:** `second_browser.kc = first_browser.kc` replaces, without closing, the `httpx2.Client` that `Browser()` created; `finally` closes only `second_browser.api`.
- **Fix:** close `second_browser.kc` before reassigning it.

---

## Remaining user-facing failure modes no test pins

1. **The guard trips and nothing tells the operator (N4).** After a bulk disable, or in a one-user realm, the sweeper refuses every tick. Readiness turns 503 and every grant is `MEMBERSHIP_STALE`, while the disabled users' memberships stay active for reads. Nothing documents an override.
2. **A redirect loop at `/auth/login` (N6).** It happens with an explicit `:80`/`:443` public base URL, or behind a Host-rewriting proxy (T30).
3. **A back-channel POST that fails.** If the API is down or `record_logout` raises, Keycloak never retries, so the application session survives until its idle or absolute limit. This is documented, but no test pins the endpoint's 5xx path or the 401 that follows on the next idle expiry.
4. **The guard against an unmigrated database.** `assert_relation` is the only thing between the owner's 0004 dev database and an API that 500s on every login. No unit test pins it (raise on a missing relation, pass on a present one) or the message the owner will see.
5. **A JWKS outage during a key rotation (N15).** It turns logout tokens and callbacks with a new `kid` into 500s instead of 400/503.

---

## What I verified and found correct

**Unit behaviour (overlay; see N3 for the one-line fix it needed):**

- The 109 unit tests pass.
- `test_login_redirect_shape` passes, so TestClient honours an explicit `Host` header. With `base_url="http://localhost:8000"` in `world` and in the extra clients, the Plan F route tests reach the login path.
- The Plan D `api` fixture keeps the default `testserver` host, and none of its 11 tests calls `/auth/login`, so the base-URL change affects no Plan D test.
- The `WorkloadTokenSource.invalidate` and one-retry arithmetic hold:
  - the 401 parameter case gives `token_calls == 2`;
  - the stale-token test gives 3;
  - the concurrent test gives one fetch for eight checks.
- The redaction canary test (16 shapes plus a traceback) passes with `out.count(REDACTED) >= len(shapes) + 2`. The handler-filter restore leaves pytest's capture handlers as they were.
- The HS256 negatives raise no `InsecureKeyLengthWarning`.

**Static checks:**

- `mypy --strict` is clean on `ops_core`, `ops_api` and `ops_sweeper` with the `authlib.*` override placed as Task 1 says.
- No Python code-block line over 120 characters is a string, comment or docstring. All nine are calls or expressions `ruff format` wraps. Line 3101 is exactly 120 characters (`§` counted once).

**authlib 1.8.0 (probe):**

- `fetch_token` returns the full token dict.
- `client.token` is non-None afterwards and None after `client.token = None`.
- `AsyncOAuth2Client.aclose()` works.

**Catalog (dev, read-only):**

- `memberships` has exactly five seeded rows (alex, sam, lee in alpha; two subjects in beta), all active, all `permission_version` 1. The live sweeper test's `checked == 5` and its "four of five" refusal hold on a fresh `ops_test`.
- `sweeper_all` is `TO sweeper USING (true)` on `memberships` and `jobs`, beside `tenant_isolation`, so the permissive policies admit the sweeper's tenant-less reads and updates.
- `jobs.available_at` defaults to `now()`; `run_id` and `tenant_id` are nullable; `attempts` defaults to 0.
- `EXPLAIN` of `claim_maintenance_job`'s SQL plans as `Limit -> LockRows -> Sort` (`FOR UPDATE SKIP LOCKED` before `LIMIT` is accepted).
- Two concurrent sweepers record one job row per minute: the second insert blocks on the unique key, then does nothing, and its claim finds no unclaimed row. A failed sync records nothing, and no claimed-but-unfinished row can exist, because insert, claim and finish share one transaction.

**Repository facts:**

- `dedup_key(JobType.SYNC_MEMBERSHIPS, minute_bucket=…)` gives `sync_memberships:<bucket>` and validates the shape. `JOB_RULES[SYNC_MEMBERSHIPS].run_states` is empty. Both are already imported in `persistence.py`.
- `finish_job(conn, job_id)` exists. `Role.SWEEPER` and `postgres_sweeper_password` exist.
- `tests/plan_a/test_layout.py` passes with:
  - `"sweeper": "ops_sweeper"`;
  - `__version__ = "0.0.1"`;
  - `requires-python = ">=3.13"`;
  - `ops-core` as the only internal dependency;
  - no cross-member import;
  - the three README headings.
- `python-multipart` 0.0.32 is locked, which satisfies `>=0.0.20,<1`.
- `tool_error` has no `retryable` parameter today. The plan adds one, and nothing in the repository constrains the error-code set.
- The worker's `is_deferred` check sits after `data = doc.get("data")`, before the UNKNOWN branch. An `error` envelope never reaches `mark_unknown`, and the `_requeue` helper keeps the `set_tenant` RLS line.
- `fresh_memberships` (function scope, depending on the session-scope `migrated`) runs after module-scoped skeleton fixtures. The marker early return via `request.node.get_closest_marker` sees a module-level `pytestmark`. The root `pyproject.toml` has no `markers` key and no `--strict-markers` yet, so the new 118-character `markers` line is safe.

**Realm export and revision 0005:**

- `ssoSessionIdleTimeout` and `ssoSessionMaxLifespan` are integer `RealmRepresentation` fields. `test_realm_name_and_roles` has `doc` in scope for the new assertion.
- The 0005 downgrade restores 0002's sweeper DELETE-only cell through `SESSIONS_CELLS_0002`. That name no longer starts with `GRANTS_`, so the newest-revision cells test no longer depends on `dir()` order.

---

## Round 2 — builder dry run

# Plan F dry run, round 2: builder report

Plan: `docs/superpowers/plans/2026-10-08-first-slice-f-sessions-login-sync.md` at `8acbddc`, run literally in the
throw-away worktree `scratchpad/planf-dryrun` (detached HEAD). Commits: `9dd804e..4e929f2` (9 commits: the plan's 8
commit steps plus one extra for T5-N3). No secret, token, code, cookie or session value appears below; the report
holds status codes, counts and timestamps only.

## Summary

| Task | Status | New WA | Gate result (dev / test passed-skipped; vh = verify_handoff exit) |
|---|---|---|---|
| 1 Debt, deps, secrets, settings, redaction | DONE-WITH-WORKAROUNDS | 2 | dev 546/82 GREEN; test 607/21 GREEN; vh 0 |
| 2 Rev 0005, realm, stale rule | DONE-WITH-WORKAROUNDS | 4 | dev 552/83 GREEN; test 614/21 GREEN; vh 0 |
| 3 Admin client, auth helpers, store | DONE-WITH-WORKAROUNDS | 2 | dev 612/86 GREEN; test 677/21 GREEN; vh 0 |
| 4 Routes, dependencies, negatives | DONE-WITH-WORKAROUNDS | 2 | dev 630/86 GREEN; test 695/21 GREEN; vh 0 |
| 5 The sweeper | DONE-WITH-WORKAROUNDS | 3 | dev 635/89 GREEN; test 703/21 GREEN; vh 0 |
| 6 Live proof | DONE-WITH-WORKAROUNDS | 3 | auth live 4 passed; test RED (1 failed), then 707/21; dev 635/93; vh 0 |
| 7 Handoff, docs, final gates | DONE-WITH-WORKAROUNDS | 1 | dev 635/93 GREEN; test 707/21 GREEN; vh 0 |

Blocking defects (an executor following the text stops): **T1-N1** (a stray line in `redaction.py`, SyntaxError),
**T3-N1** (`await` inside a generator passed to `all()` in the live store test, TypeError), **T6-N1** (the browser
helper dials `127.0.0.1:8000`, and the API's own `/auth/login` redirects every non-public host, so no live login
can start), **T6-N2** (the auth module's restore leaves sam at `permission_version` 2 and the next module,
`test_sweeper_live.py`, fails: `check.py --profile test` RED). Next in weight: **T2-N2/T3-N2** (two code fences closed
with text on the same line, so the rendered plan swallows the following prose into code), **T5-N3** (the Task 5
commit list leaves `tests/plan_a/test_layout.py` uncommitted) and **T4-N2/T5-N2** (ruff's RUF100 deletes the
`noqa: BLE001` comments the plan relies on for the reason of an `except Exception`).

## Closure of the 29 round-1 workarounds

| R1 item | What it was | Round 2 |
|---|---|---|
| T1-2 | `sessions()` docstring 121 chars | closed |
| T1-3 | `testpaths` line 121 chars | closed (multi-line form given) |
| T1-4 | where the `TokenVerifier` docstring goes | closed (`__init__` docstring specified) |
| T1-5 | also restore `reports/skeleton` | still needed in Tasks 3–7 (note a) |
| T2-1 | departures paragraph not given | changed, still a rewrap (note b; T2-N1) |
| T2-2 | `NO_RLS` multi-line | closed |
| T2-3 | `privileges.GRANTS` vs `p.GRANTS` | closed |
| T2-5 | one-off needs `OPS_SECRETS_DIR` | changed, still a workaround (note c; T2-N4) |
| T3-1 | `DbStore.session` attribute vs method | closed (`live_session`) |
| T3-2 | authlib untyped, mypy override | closed (Task 1 Step 2) |
| T3-3 | 122-char comment in `auth.py` | closed |
| T3-4 | Task 3 commit list | closed (no extra file changed) |
| T4-1 | `store.units.conn` in lifespan | closed |
| T4-2 | `test_identity_and_membership` needs `"auth"` | closed |
| T4-3 | session-expiry test picked the dead row | closed |
| T4-4 | lint on the plan's tests | closed (`ruff check` clean as written) |
| T4-5 | manual API start without environment | closed (the manual start is gone) |
| T4-6 | `curl -sI` probe | closed (gone) |
| T5-1 | package before lock | closed |
| T5-2 | `insert_maintenance_job` docstring | closed |
| T5-3 | INSERT line 121 chars | closed |
| T5-4 | ISC004 on `sync.py` | **still needed** (note d) |
| T5-5 | `SELECT DISTINCT … FOR UPDATE` | closed (R105 ready in 15.6 s setup) |
| T5-6 | `test_layout.py`, README, `__version__` | changed, still a workaround (note e; T5-N3) |
| T6-1 | ASYNC251 in the live module | closed |
| T6-2 | `EVIDENCE_ROOTS` code not given | closed (Task 6 note (c) gives it) |
| T7-1 | `privileges.py:150` comment | closed (row named, comment on its own line) |
| T7-2 | `STATUS.md` has no table | closed |
| T7-3 | review ledger in a literal run | closed ("none recorded" stated) |

Notes to the table:

- (a) Global Constraints, Task 1 Step 9 and Task 2 Step 7 say `git checkout -- reports/bootstrap reports/skeleton`;
  Task 3 Step 7, Task 4 Step 4, Task 5 Step 5, Task 6 Step 3 and Task 7 Step 3 still say `reports/bootstrap` only,
  and the R105 file was dirty after each of those runs.
- (b) The paragraph is given, but wrapped as if it began a line; spliced into the docstring it makes 129- and
  220-character lines.
- (c) The plan now says `export_environment(load_dotenv(".env"))`, which raises
  `AttributeError: 'str' object has no attribute 'exists'`.
- (d) `ruff check --fix` reports ISC004 at `sweeper/src/ops_sweeper/sync.py:71`; the Global ISC004 step names
  revisions only. I ran `ruff check --select ISC004 --fix --unsafe-fixes` on `sync.py`.
- (e) Files and Step 2 now carry all three, but the Step 5 `git add` omits `tests/plan_a/test_layout.py`, so an
  extra commit was needed.

Totals: 24 closed; 2 still needed (T1-5 in five tasks' gate steps, T5-4); 3 changed but still needing a workaround
(T2-1, T2-5, T5-6).

Round-1 defects and notes without a workaround: T1-1 naming closed (ruling 22, Architecture, overview all say
`ops_core.redaction` / `test_redaction.py`); T1-6 (vh not in gate steps) partly: Global now says it runs in every
task's gate step, but Task 3 Step 7, Task 4 Step 4, Task 5 Step 5 and Task 6 Step 3 still do not list it (I ran it
every time: exit 0); T2-4 (interim red) changed, see T5-N1; T2-6 closed (`SESSIONS_CELLS_0002`); T3-5 closed (overview
and ruling 16 match the code); T3-6 closed (32-byte HMAC key; no warning in any gate); T5-7 notes closed (`up()`
docstring and runbook now say six; the stuck-job issue is gone because the job row is written only after a
successful sync).

## Task 1

- **T1-N1 (BLOCKING; workaround).** Step 6, the `redaction.py` block, lines 486–487 of the plan:
  `_PATTERNS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (` is immediately followed by `_SECRET_KEYS = (`; a
  leftover of an edit. Collecting the test gives
  `redaction.py, line 22 … SyntaxError: '(' was never closed`. I deleted the stray first line; then 3 passed. Fix:
  delete plan line 486.
- **T1-N2 (workaround).** Step 2, `api/pyproject.toml`'s one-line `dependencies = [...]` is 142 characters. I made it
  a one-entry-per-line list. Fix: give the multi-line list (as Step 9 does for `testpaths`).
- Note: Step 2 says `bootstrap_dev.py secrets` "touches nothing else"; it also rewrites `.env` (it prints
  `.env written: …`). Output: `secrets: 0 created, 22 kept` (the two files exist from round 1).
- Matched: locked **authlib 1.8.0**, **joserfc 1.7.5**, cryptography 50.0.2, python-multipart 0.0.32; Plan B
  bootstrap/compose tests 13 passed, 1 skipped; settings 9 failed → 22 passed (with the predicted Plan D
  `127.0.0.1` update); redaction collection error → 3 passed; knobs 3 failed, 1 passed (the defaults test passes
  before the change; the plan says just "FAIL") → 31 passed.

## Task 2

- **T2-N1 (workaround).** Step 1, the departures paragraph: see the closure table (T2-1). I put "Six departures…" on a
  new line after "their rows." and re-wrapped the `test_harness` sentence. Fix: give the whole docstring paragraph
  from "Rows exist only…" to the end, wrapped.
- **T2-N2 (defect in the plan text; workaround).** Plan line 1062: the closing fence of the
  `test_revision_0005_bodies_differ…` block is followed on the same line by "Run `uv run ruff check …`". That is
  not a closing fence in Markdown, so everything up to the next fence renders as code, and a mechanical block
  extraction pulls the Step 3 prose and Step 4 text into the test file. I cut the block at that line. Fix: put the
  fence on its own line. (Same defect at line 2432, T3-N2.)
- **T2-N3 (ambiguity; resolved by judgement).** Step 2 says add the 0004 downgrade "before the first downgrade" and
  then "(the `testclock@base` downgrade stays first)". I put the block after `downgrade(… "testclock@base")` and
  before the `0001` downgrade. Fix: say "between the two existing downgrades".
- **T2-N4 (workaround).** Step 5's one-off: `load_dotenv(".env")` raises `AttributeError: 'str' object has no attribute
  'exists'` (`load_dotenv(path: Path = Path(".env"))`). I used `load_dotenv(Path(".env"))`. Fix: write
  `load_dotenv()` or `load_dotenv(Path(".env"))`.
- One-off results (lee): token 200; search 200 (1 user); GET 200, enabled True; PUT `{"enabled": false}` 204; GET 200,
  enabled False, `username/email/firstName/lastName` unchanged True; PUT `{"enabled": true}` 204; GET 200, enabled
  True, fields unchanged True.
- Matched: newest-revision test red after Step 1 only; stale test `DID NOT RAISE Refused` before 0005 (the `-k stale`
  filter also selects one existing test: "1 failed, 1 passed"); frozen `GRANT_EXECUTION_0004` byte-identical to
  0004's `GRANT_EXECUTION` (checked by import); Step 3 28 passed; Step 4 live 25 passed; `tests/plan_b` 39 passed,
  10 skipped; `down`/`up` re-import (`bootstrap admin: deleted`); `tests/plan_b/live` 9 passed; Step 6 15 passed.
- Notes: `is_deferred` goes "after `EXECUTE_RETRY_SECONDS`", but `QUERY_CHARS` follows that constant; I put it after
  `QUERY_CHARS`. The new realm description line is 146 characters (JSON; same as round 1).

## Task 3

- **T3-N1 (BLOCKING live; workaround).** Step 6, `test_record_logout_is_atomic_and_replay_safe`:
  `assert all(await db.live_session(k, idle_seconds=1800) is None for k in keys[:2])` builds an async generator:
  `TypeError: 'async_generator' object is not iterable` at `tests/e2e/test_sessions_store_live.py:96` (1 failed,
  2 passed). I used a list comprehension inside `all([...])`; then 3 passed. Fix: write the list form (or two
  asserts).
- **T3-N2 (defect in the plan text; workaround).** Plan line 2432: the `assert_relation` block's closing fence is
  followed by "The module docstring's `TODO(T12)` line stays…" on the same line (as T2-N2). Fix: own line.
- **T3-N3 (ambiguity).** "The module docstring's `TODO(T12)` line stays; add …" sits after the `persistence.py` block,
  but only `store.py`'s docstring has a `TODO(T12)`. I added the line to `store.py`. Fix: name the file.
- Note: the Task 4 Interfaces say `assert_relation` raises `PersistenceError("<name> is missing; migrate the
  database")`; Task 3's code says "…; run scripts/skeleton.py migrate for this profile". Harmless, but align.
- Matched: admin test collection error → 14 passed (`httpx2.ASGITransport` exists); helpers and tokens 46 passed; mypy
  `api/src core/src` clean; Plan D API tests still 11 passed; no warning in any gate (the 32-byte HS key).

## Task 4

- **T4-N1 (workaround).** Step 1 says the `FakeStore` signatures are "spelled out with the annotations of the
  protocol", but the block gives `begin_login` and `create_session` without annotations and on lines of 112 and
  184 characters. I annotated both from the protocol. Fix: give the annotated, wrapped signatures.
- **T4-N2 (defect; ruff's fix applied).** Step 4 says "`BLE001` has a `noqa` with its reason". With the project's
  ruff 0.16.10, BLE001 does not fire on an `except Exception` that re-raises (`raise … from exc`), so RUF100 reports
  the `noqa` as unused and `ruff check --fix` deletes the comment, reason included (`app.py` backchannel `form()`).
  Same in Task 5 (`main.py`, where `log.exception` also satisfies BLE001). Fix: drop the `noqa` and keep the reason
  as a plain comment on the line above, or catch the specific exceptions.
- Note: the new module-docstring sentence is given unwrapped; I wrapped it.
- Matched: Plan D API tests failed on `auth_factory` as predicted (1 failed, 1 passed, 9 errors); route tests
  18 errors before Step 3; after Step 3 35 passed; mypy `--no-incremental` clean; ruff fixed 2 import-order issues.

## Task 5

- **T5-N1 (proof still weak).** R105 now opts out of the stamp (`sweeper_stamps`), and run alone it proves the
  sweeper: `ops_test` `synced_at` equalled the sweeper's first sync instant (`membership sync: 5 rows checked,
  0 deactivated` at the same second). But nothing ages the rows first, and in the full suite the previous module's
  autouse stamp runs seconds before R105, so the grant would pass even without a sweeper. Fix: R105 ages the rows
  past 120 s before the skeleton starts (superuser `UPDATE … synced_at = app.current_time() - interval '10 minutes'`)
  and asserts they are fresh after `up`.
- **T5-N2 (as T4-N2).** `ruff check --fix` removed `# noqa: BLE001  -- one bad tick must not stop the scheduler`.
- **T5-N3 (workaround).** Step 5's `git add` omits `tests/plan_a/test_layout.py` (named in Files and Step 2); the
  commit leaves it modified. I committed it separately (`85de090`). Fix: add it to the `git add` line.
- **T5-N4 (minor).** "`grep -n "five" …` must find nothing" is case-sensitive; the runbook's first line "Five host
  processes" survives it. The step does ask for "Six host processes", so I changed it; use `grep -in`.
- Also T5-4 (ISC004 on `sync.py`) still needed, see closure table.
- Ambiguities: R105 has no module-level marks for `pytestmark` to sit "beside" (I put it after `EVIDENCE`); the place
  of the runbook paragraph is not given (I put it after item 6).
- Matched: sweeper unit 7 passed; `tests/e2e/test_sweeper_live.py` 3 passed; R105 alone passed (15.59 s setup,
  12.34 s call); sweeper log: `membership sync: 5 rows checked, 0 deactivated`; secret-shape grep 0 in all six logs.

## Task 6

- **T6-N1 (BLOCKING live; workaround).** `kc_browser.API = "http://127.0.0.1:8000"`, but Task 4's `/auth/login`
  answers 303 to `http://localhost:8000/auth/login` for any other Host. First run: `test_login_csrf…` failed at
  `location.startswith(…/protocol/openid-connect/auth?)` (location was `http://localhost:8000/auth/login`), and the
  back-channel test failed in `keycloak_login` with `AssertionError: 303`; 2 failed, 2 passed. I gave `Browser.api` a
  default header `Host: localhost:8000` (still dialling 127.0.0.1); then 4 passed. Fix: that header (or dial
  `localhost`, which costs about 2 s per new connection here).
- **T6-N2 (BLOCKING gate; workaround).** `check.py --profile test` went RED: `1 failed, 706 passed`,
  `tests/e2e/test_sweeper_live.py::test_sync_deactivates_disabled_and_deleted_and_stamps_the_issuer`,
  `assert (not False and 3 == 2)`: the auth module disabled sam (pv 1 → 2) and its fixture restore sets
  `active = true, synced_at` only, so the sweeper test's deactivation lands at pv 3. I added `permission_version = 1`
  to the restore; then GREEN 707/21. Fix: that, or make the sweeper test compare relative to the starting value.
- **T6-N3 (workaround, code not given).** Step 3 asks for `pytestmark = pytest.mark.sweeper_stamps` and an assertion
  that `min(synced_at)` advanced within 75 s of the module start, without code. Asserted once, it would usually fail
  (the back-channel test starts about 3 s after the first test, the next tick is up to 30 s away). I recorded the
  oldest stamp and a monotonic start in the first test and polled (1 s) until it advanced or 75 s passed, then
  asserted; the back-channel test now takes 27.5 s. Fix: give the code with the poll.
- Notes: (b) partial PUT checked again (204, then enabled False, other fields unchanged); `runtime/skeleton/*.log`
  is appended across runs, so "one … line" style checks need a timestamp; the Global "two skeleton modules opt out"
  is true only after Task 6.
- Live result (final run, verbatim; codes and counts only):

  ```text
  T11 sessions and revocation — 2026-10-09T08:49:31Z
  login: me=200 csrf_refusals=[403, 403, 403, 403] mutation_with_token=201
  idle expiry: me=401
  logout: 204; keycloak shows the login form again: True
  back-channel logout: sibling me=401, jti rows +1, sessions revoked 2
  forged logout token: 400
  disabled user: decision=401 synced_after=24.2s me=401
  ```

  R086 `synced_after` values over the runs: 21.1 s (first, partly failed run), 18.1 s, 23.2 s, 23.2 s, 23.2 s, 24.2 s;
  all within 60 s. Module timings: 77.88 s with the T6-N3 poll (48 s without). Log tallies over all runs: API
  `back-channel logout revoked 1 session(s)` ×8, `back-channel logout token rejected: unknown signing key` ×5; sweeper
  `membership sync: 5 rows checked, 0 deactivated` ×13 and `… 1 deactivated` ×5; `Bearer`/`password=`/JWT-shape
  grep 0 in all six logs.

## Task 7

- **T7-N1 (inconsistency; resolved by judgement).** Files and the "Next task" bullet say errata 26–31; the "Plan F
  executed" bullet numbers 26–34 and the commit message says 26-34. I wrote 26–34 in the section and "decide errata
  26–31" in the Next-task line as written. Fix: one range (26–34).
- Ambiguities: Files lists `docs/runbooks/walking-skeleton.md` ("migrated to 0005 before `up`; the login
  walk-through"), Step 2 gives no text for it (Task 5 already added the migrate sentence; the login walk-through is
  given for `dev-topology.md` only); `<first>..<last>` "on `plan-f`" on a detached HEAD: I used `9dd804e..11ef124`;
  the review-note and STATUS texts are described, not given, so I wrote them.
- Matched: final gates below; `reports/auth` and `reports/skeleton` committed.

## Final gate numbers

| Gate | Result |
|---|---|
| `scripts/check.py` | CHECK: GREEN, 635 passed, 93 skipped (38.9 s); no warnings |
| `scripts/check.py --profile test` | CHECK: GREEN, 707 passed, 21 skipped (190.3 s) |
| `verify_handoff.py --reference-code --manifest --contracts` | exit 0 (7 PASS, 1 LIMIT) |
| `tests/e2e/test_auth_live.py` alone | 4 passed (77.88 s) |
| R105 alone, six processes | passed (29.25 s) |
| mypy (`check.py`, all members incl. `sweeper/src`) | clean |

Skips: 21 under the test profile (unchanged from before Plan F); the dev profile grows from 82 to 93 because the new
live tests are skipped there.

## Cleanup proof

- `scripts/skeleton.py status`: all six `down`; `netstat` shows no listener on 8000, 8070, 8071, 8081, 8082, 8090,
  18081 or 18090.
- Dev databases untouched: `ops` alembic `['0004_write_path_functions']`, `app.login_state` absent; `incident`
  `['0002_destination_hardening']`. Schemas: `ops` = `app, public`; `incident` = `incident, public`.
- Roles: no `critic%` role (`[]`); set unchanged: `api, app_definer, incident, incident_owner, mcp_exec, mcp_read,
  migrator, operator, ops, sweeper, test_harness, worker`. Databases: `incident, incident_test, ops, ops_test,
  postgres, template0, template1` (`*_test` are the fixtures' own, now at 0005).
- Realm users (as `ops-test-admin`): `alex, jordan, lee, riley, sam`, all enabled. No `critic_*` object was created
  anywhere; nothing was deleted.
- Dev stack: `ops-copilot-keycloak-1` and `ops-copilot-postgres-1` up and healthy. The Task 2 re-import ran from the
  worktree, so the shared realm carries the Plan F realm (as after round 1); `secrets` created nothing.

## Files not named by the plan

- Repository: none created. Changed beyond the plan's lists: `tests/e2e/kc_browser.py` Host header (T6-N1),
  `tests/e2e/test_auth_live.py` restore and stamp poll (T6-N2, T6-N3), the separate `test_layout.py` commit (T5-N3).
- Scratch, outside the worktree, deleted before finishing: a code-block extractor, the gate logs, and three one-off
  scripts (the `ops-test-admin` probe, a `synced_at` reader, the cleanup proof) that print codes, flags, names and
  timestamps only.

---

## Round 3 — closure check and third dry run

# Plan F round 3: closure review and third dry run

Plan: `docs/superpowers/plans/2026-10-08-first-slice-f-sessions-login-sync.md` at `2baa854` (branch `plan-f`). Line
numbers are plan lines unless a file is named. Part A was done read-only against the plan text; Part B ran the plan
literally in the throw-away worktree `scratchpad/planf-dryrun` (detached HEAD, commits `0ba775f..b5b732c`, the plan's
eight commit steps and nothing else). No secret, token, code, cookie or session value appears below: status codes,
counts, names and timestamps only.

**Closure: 42 closed / 6 partial / 0 open (48 rows).**
**Third dry run: all seven tasks done; 4 workarounds (2 blocking, 1 gate-red, 1 minor); final gates GREEN.**

## Part A. Closure table

### Round-2 critic (N1-N16, the six partials, the open T5-4)

- N1 browser helper vs `/auth/login` host redirect: closed. `self.api = httpx2.Client(base_url=API, headers={"Host":
  PUBLIC_HOST}, …)` (4138); live: 4 passed
- N2 sam's `permission_version` not restored: closed. teardown `SET active = true, permission_version = 1, …` (4260);
  sweeper test asserts `before[SAM] + 1` (4000); full live suite GREEN
- N3 `redaction.py` SyntaxError: closed. one `_PATTERNS: Final[...] = (` header (511), comment above it (508-510); the
  module imports
- N4 guard turns offboarding into an outage: closed. `refuse()` counts absent only, `MIN_ABSENT_TO_REFUSE = 3`
  (3647-3659); `OPS_SYNC_ALLOW_MASS_DEACTIVATION` (3890); ruling 28; unit
  `test_listing_guard_counts_absent_subjects_only` (3500)
- N5 sweeper-stamps proof prose only: closed. R105 fixture ages rows 10 min and asserts `bool_and(…)` after `sk.start()`
  (4052-4060); auth module `STAMP["t0"]` and a 45 s poll (4253, 4376-4384)
- N6 `/auth/login` loop on an explicit default port: closed. `same_host` compares `(hostname, port or default)`
  (1926-1936); cases `("localhost", "http://localhost:80", True)` (1645); T30 debt line (88)
- N7 malformed code fences: **partial**. 1067 and 2491 are bare now, but a new one appeared: line 780 is `` ``` Run `uv
  run python -m pytest …` ``. Per CommonMark the block opened at 771 closes only at 800, so 772-799 (the Step 1 run
  line, the Step 2 heading and prose) render as code
- N8 142-character api dependency line: closed. multi-line `dependencies = [ … ]` (140-147)
- N9 ISC004 in `sync.py`, dead `noqa`: closed. purge tuple parenthesised (3713-3717); `except Exception:  # one bad tick
  …` with no `noqa` (3846, 3376); ruff ISC clean
- N10 redaction residue: **partial**. keys gain `nonce|code_verifier|…|password` (505-506), `b?` (518), tuple form
  (520), 16+ rule (513). But the canary is `"CANARYc4f7e2"` (401), 12 characters, so the new 16+ rule leaves `Bearer
  CANARY…` and `Basic CANARY…` unredacted: 2 of 3 redaction tests fail (WA-1). Bare `KEYCLOAK_IDENTITY=X` is still not
  covered
- N11 text inconsistencies: closed. Interfaces: "`PersistenceError("<name> is missing; run scripts/skeleton.py migrate
  for this profile")`" (2626); Task 7 "errata 26–34" (4471, 4482); "the eight members" (3576); unit test renamed (3500)
- N12 R006 downgrade order: closed. "between the existing `testclock@base` downgrade … and the existing downgrade to
  `0001_walking_skeleton`" (784); live R006 passed
- N13 per-task gate text: closed. Task 3 Step 7: "`verify_handoff.py` … exit 0; `git checkout -- reports/bootstrap
  reports/skeleton`" (2609); Task 4 Step 4 likewise (3444); Tasks 5-7 commit the R105 file
- N14 live store test lacks atomicity: **partial**. the case is there (2587-2595), and it proves rollback leaves the jti
  unconsumed once fixed, but line 2594 is `assert all(await db.live_session(…) is not None for k in keys[:2])`: a
  TypeError (WA-3)
- N15 JWKS outage → 500: closed (no change needed). the endpoint catches `TokenRejected` (3381-3385), and the repo's
  `TokenVerifier.load_keys` already maps `OSError, httpx2.HTTPError, ValueError` to `TokenRejected("signing keys
  unavailable")` (`core/src/ops_core/tokens.py`), so there is no 500 path: 400 at the back-channel, 401 at the callback
- N16 back-channel test leaks a client: closed. `second_browser.kc.close()` before the reassignment (4355)
- I4 live store test, atomic case: **partial**. as N14: present (2587) but fails as written (2594)
- M8 missing docstrings: closed. `CookiePolicy.set_session` … `clear_login` (2260-2277), `AuthDeps.aclose` (2297),
  `Identity.auth` (3144), `no_store` (3267), `landing` (3263)
- RF1 127.0.0.1 vs localhost: closed. as N1 (4136-4138, 4155)
- RF4 lost back-channel POST, 5xx path: closed.
  `test_backchannel_logout_store_failure_is_a_503_and_the_session_survives` (3052-3065); passes through the existing
  `psycopg.Error` handler
- T1-5 restore `reports/skeleton`: closed. as N13 (2609, 3444)
- T1-6 `verify_handoff` in every gate: closed. present in Tasks 1-7 gate steps (715, 1238, 2609, 3444, 4070, 4459, 4495)
- T5-4 ISC004 on `sync.py`: closed. as N9 (3713-3717); `ruff check --select ISC sweeper/src`: all checks passed

### Round-2 builder (new items and residues)

- T1-N1 stray `_PATTERNS` line: closed. as N3 (511)
- T1-N2 142-character dependency line: closed. as N8 (140-147)
- T2-N1 departures paragraph: closed. the wrapped paragraph from "their rows." to the end is given (772-779); its fence
  is N7's line 780
- T2-N2 fence at old 1062: closed. 1067 is a bare fence; "Run `uv run ruff check --select ISC004 …`" on its own line
  (1086)
- T2-N3 R006 placement ambiguity: closed. (784, 802); residual wording note below (M-3)
- T2-N4 `load_dotenv(".env")`: closed. "`export_environment(load_dotenv(Path(".env")))` … (`load_dotenv` takes a
  `Path`)" (1161); probe ran
- T3-N1 `await` in a genexp: **partial**. 2599 is the list form with a comment (2598-2599), but the new line 2594
  repeats the genexp (WA-3)
- T3-N2 fence at old 2432: closed. 2491 bare; the next sentence on its own line (2493)
- T3-N3 which docstring has `TODO(T12)`: closed. "`api/src/ops_api/store.py`'s module docstring: its `TODO(T12)` line
  stays" (2493)
- T4-N1 unannotated `FakeStore` signatures: closed. annotated, wrapped `begin_login`/`create_session` (2783-2804)
- T4-N2 RUF100 deletes `noqa: BLE001`: closed. plain comments, no `noqa` (3376, 3846); ruff fixed import order only
- T5-N1 R105 proves no sweeper in a full run: closed. rows aged before `sk.start()` and checked after (4052-4060);
  passed alone and in the suite
- T5-N2 `noqa` in `main.py`: closed. (3846)
- T5-N3 Task 5 commit list: closed. `git add … tests/plan_a/test_layout.py …` (4073); tree clean after the commit
- T5-N4 case-sensitive `grep five`: closed. "`grep -in "five" …` must find nothing" (3926); found nothing
- T6-N1 helper dials the wrong Host: closed. as N1
- T6-N2 auth module leaves pv 2: closed. as N2
- T6-N3 stamp poll code not given: closed. code with a 45 s poll (4375-4384); see M-5 for the step order
- T7-N1 errata range 26-31 vs 26-34: closed. "errata 26–34" in Files, Next task and the section (4471, 4482, 4483)
- T7-N1 ambiguities: **partial**. `<first>..<last>` defined (4486); the walking-skeleton line is still given only in the
  Files list (4471), not in Step 2; STATUS and the review note are described, not given
- T1-5 (residue): closed. as above
- T5-4 (residue): closed. as above
- T2-1 (residue): closed. as T2-N1
- T2-5 (residue): closed. as T2-N4
- T5-6 (residue): closed. as T5-N3

Counts: critic 23 rows (19 closed, 4 partial); builder 20 rows (18 closed, 2 partial); residues 5 (closed). Total 48:
42 closed, 6 partial, 0 open. The six partials reduce to three plan defects: WA-1 (N10), WA-3 (N14, I4, T3-N1) and
the fence at 780 (N7), plus the T7 ambiguity.

## Part B. Per-task summary

- Task 1 Debt, deps, secrets, settings, redaction, knobs: DONE-WITH-WORKAROUNDS; workarounds: 2 (WA-1 blocking, WA-2
  minor); gates: dev 546/82 GREEN; test 607/21 GREEN; vh 0
- Task 2 Rev 0005, realm, stale rule, fixtures: DONE; workarounds: 0; gates: dev 552/83 GREEN; test 614/21 GREEN; vh 0
- Task 3 Admin client, auth helpers, store: DONE-WITH-WORKAROUNDS; workarounds: 1 (WA-3 blocking live); gates: dev
  620/87 GREEN; test 686/21 GREEN; vh 0
- Task 4 Routes, dependencies, negatives: DONE; workarounds: 0; gates: dev 639/87 GREEN; test 705/21 GREEN; vh 0
- Task 5 The sweeper: DONE; workarounds: 0; gates: dev 644/90 GREEN; test 713/21 GREEN; vh 0; R105 alone passed
- Task 6 Live proof: DONE-WITH-WORKAROUNDS; workarounds: 1 (WA-4 gate red); gates: auth alone 4 passed; test RED (lint
  only, 717/21), then 717/21 GREEN; dev 644/94 GREEN; vh 0
- Task 7 Handoff, docs, final gates: DONE; workarounds: 0; gates: dev 644/94 GREEN; test 717/21 GREEN; vh 0 (7 PASS, 1
  LIMIT)

## Workarounds and defects, with the fix the plan should carry

**WA-1 (BLOCKING, Task 1 Step 6; introduced by the N10 fix).** Plan 401: `CANARY = "CANARYc4f7e2"` (12 characters);
plan 513: the Authorization rule redacts only `[A-Za-z0-9._~+/=-]{16,}`. After Step 6, `test_redaction.py` gave
`2 failed, 1 passed`: `assert 'CANARYc4f7e2' not in …` (the output held `Authorization: Bearer CANARY…`), and
`assert 'Bearer CANARYc4f7e2' == 'Bearer [REDACTED]'`. I lengthened the canary to 20 characters
(`"CANARYc4f7e2d81a9b03"`); then 3 passed (all 19 shapes and the traceback redacted, prose kept).
Fix: a canary of 16+ token characters (with a comment saying why), or anchor the rule as round 2 suggested
(`authorization['"]?\s*[:=]\s*['"]?(bearer|basic)\s+` matches any length; bare `bearer|basic` needs 16+).

**WA-2 (minor, Task 1 Step 6).** "Comment each with one line: 'the redaction filter must be on the root handler before
the first log line (T11 review note 4)'". Placed after `redaction.install()` it makes 122-character lines in all five
entrypoints. I put the comment on its own line above the call. Fix: say "a comment line above the call", or shorten it
as the sweeper's `_main` does (3875).

**WA-3 (BLOCKING live, Task 3 Step 6; introduced by the N14 fix).** Plan 2594:
`assert all(await db.live_session(k, idle_seconds=1800) is not None for k in keys[:2])`.
Result: `TypeError: 'async_generator' object is not iterable` at `tests/e2e/test_sessions_store_live.py:95`
(`1 failed, 3 passed`). I used `all([...])`; then 4 passed, which also proves the rolled-back jti insert is not
consumed (`record_logout` then returned 2, the replay None). Fix: the list form on 2594 too (2598's comment already
explains why).

**WA-4 (gate RED, Task 6 Step 3).** Step 3 has no "Format, lint, the character count" sentence (every other gate step
has one), and `kc_browser.py` still writes `re.S` twice (4110-4111; round 2's critic reported FURB167 there).
`check.py --profile test` ended `717 passed, 21 skipped … CHECK: RED` on `FURB167 … tests\e2e\kc_browser.py:17:80`
and `:18:89`. I applied the Global gate (`ruff format` / `ruff check --fix`: `re.S` → `re.DOTALL`) and reran: GREEN.
Fix: write `re.DOTALL` in the plan and add the format/lint/count sentence to Task 6 Step 3.

## Residual Minor findings

- **M-1 fence at 780 (N7 regression).** `` ``` Run `uv run python -m pytest tests/plan_f/test_privileges_f.py …` ``
  must become a bare fence with the Run sentence on the next line.
- **M-2 ruling numbering.** Rulings run 1-26, then 28 and 29: there is no 27 (code and runbook cite "ruling 28").
- **M-3 R006 order wording.** 802 says "assert the columns, `testclock@base`, `0004…`", but the block that 784 inserts
  between the two downgrades asserts the columns after `testclock@base`. Harmless either way; say which.
- **M-4 `invalidate()` has no step.** `WorkloadTokenSource.invalidate` is named only in Task 3's Files and Interfaces
  (1253); no step says to add it or gives its text. I added it in Step 2 (one docstring line, `self._token = None`).
- **M-5 Task 6 marker order.** Step 3 runs the module first and adds `pytestmark = pytest.mark.sweeper_stamps`
  afterwards. In that first run the autouse fixture stamps before every test, so the poll passes at once (evidence
  "sweeper re-stamped synced_at after 0.0s"). Put the line in Step 2's module code.
- **M-6 redaction docs.** `test_redaction.py` line 459 ends with a stray `"` inside the comment and points at "the
  module docstring", which does not mention over-redaction (the comment above `_PATTERNS` does). The module docstring's
  list also omits `nonce`, `code_verifier`, `client_secret`, Basic and `X-CSRF-Token`. Bare `KEYCLOAK_IDENTITY=X` is
  not redacted.
- **M-7 splices that start mid-line.** The Task 4 `app.py` docstring replacement (3111-3113) and the Task 7 privileges
  docstring (772) are given as if they start a line; the first replaces a sentence that starts after "runs.". I put it
  on a new line.
- **M-8 docs not named.** `docs/runbooks/dev-topology.md` line 71 still says "`sweeper` and `operator` are reserved
  for their later owners". The `test_evidence.py` docstring change (note c) has no text; my wording wrapped to two
  lines.
- **M-9 environment notes (unchanged from round 2).** `bootstrap_dev.py secrets` gave `0 created, 22 kept` because the
  files exist from earlier rounds; the `ops-test-admin` description line is 146 characters (JSON).

## Final gate numbers and live results

- `scripts/check.py`: CHECK: GREEN, 644 passed, 94 skipped (35.6 s); no warnings
- `scripts/check.py --profile test`: CHECK: GREEN, 717 passed, 21 skipped (189.0 s)
- `verify_handoff.py --reference-code --manifest --contracts`: exit 0 (7 PASS, 1 LIMIT)
- `tests/e2e/test_auth_live.py` alone (with the marker): 4 passed (77.65 s; back-channel test 27.43 s, disable test
  29.42 s)
- R105 alone, six processes, rows aged 10 min first: passed (setup 15.25 s, call 12.28 s, 28.68 s); the fixture's
  freshness check held
- `tests/e2e/test_sessions_store_live.py`: 4 passed (after WA-3)
- `tests/e2e/test_sweeper_live.py`: 3 passed
- Task 2 Step 4 live (R124, R006 with the 0004 downgrade, R106, stale grant): 25 passed
- Task 2 one-off (`ops-test-admin` on lee): token ok; search 200 (1); GET 200 enabled True; PUT false 204; GET enabled
  False, fields unchanged True; PUT true 204; GET enabled True, fields unchanged True
- mypy (`check.py`, all members incl. `sweeper/src`): clean

Evidence file, final run (verbatim):

```text
T11 sessions and revocation — 2026-10-09T09:41:56Z
login: me=200 csrf_refusals=[403, 403, 403, 403] mutation_with_token=201
idle expiry: me=401
logout: 204; keycloak shows the login form again: True
back-channel logout: sibling me=401, jti rows +1, sessions revoked 2
sweeper re-stamped synced_at after 25.2s
forged logout token: 400
disabled user: decision=401 synced_after=23.2s me=401
```

That is the header plus seven lines, as Step 3 says.

R086 `synced_after` over the five module runs:
- 18.1 s (first run, no marker);
- 23.2 s (alone, with the marker);
- 23.2 s (full suite, red on lint);
- 24.2 s (full suite, Task 6);
- 23.2 s (final suite).

All are within 60 s. The stamp poll gave 0.0 s on the first run (M-5) and 25.2 s on each of the other four.

Logs: `runtime/skeleton/` is fresh in this worktree and covers seven skeleton starts.
- `sweeper.log`: `membership sync: 5 rows checked, 0 deactivated` ×14 and `… 1 deactivated` ×5. No "refused" or
  "skipped" lines.
- `api.log`: `back-channel logout revoked 1 session(s)` ×10 and `back-channel logout token rejected: unknown signing
  key` ×5.
- `grep -cE "Bearer [^[]|password=[^[]"` gave 0 on all six logs; the JWT-shape grep gave 0; there were no
  `ERROR`/Traceback lines in the API or sweeper logs.

## Cleanup proof

- `scripts/skeleton.py status`: all six processes `down`; `netstat` shows no listener on 8000, 8070, 8071, 8081, 8082,
  8090, 18081 or 18090. `runtime/skeleton/pids.json` is absent.
- Dev databases untouched: `ops` alembic `['0004_write_path_functions']`, `app.login_state` None, `app.test_clock` None,
  schemas `app, public`; `incident` `['0002_destination_hardening']`, schemas `incident, public`.
- Roles: no `critic%` role (`[]`), no `critic%` schema (`[]`); the role set is unchanged (`api, app_definer, incident,
  incident_owner, mcp_exec, mcp_read, migrator, operator, ops, sweeper, test_harness, worker`). The databases are
  `incident, incident_test, ops, ops_test, postgres, template0, template1`; the `*_test` ones are the fixtures' own,
  now at 0005.
- Realm users (as `ops-test-admin`): alex, jordan, lee, riley and sam, all enabled. No `critic_*` object was created
  anywhere, and nothing was deleted.
- Dev stack: `ops-copilot-keycloak-1` and `ops-copilot-postgres-1` are up and healthy. The one allowed
  `bootstrap_dev.py down`/`up` (Task 2 Step 5) re-imported the realm from the worktree (`bootstrap admin: deleted`),
  and the volume was kept. `secrets` created nothing.
- The real checkout was never touched: clean, at `2baa854`. Commits carry no attribution trailers (grep: 0).

## Files created that the plan did not name

- Repository (worktree): none. The workarounds changed only plan-named files: the `test_redaction.py` canary (WA-1),
  the five entrypoint comment placements (WA-2), `test_sessions_store_live.py:95` (WA-3) and `kc_browser.py`
  `re.DOTALL` (WA-4, by ruff). Two extraction slips of mine (a closing fence line copied into `store.py` and the R105
  module) were caught by the first run and removed; they are not plan defects.
- Scratch, outside the worktree, in `scratchpad/planf-r3/`:
  - `ex.py`, a line-range copier for plan blocks;
  - `probe_test_admin.py`, the Task 2 one-off, which prints codes and booleans;
  - `cleanup_proof.py`, which prints names, revisions and flags;
  - `log.md`, the run log;
  - 22 gate logs.

  None holds a secret: a JWT-, Bearer- and password-shape grep over the directory found nothing.

---

## Round 4 — closure check and delta execution

# Plan F round 4: delta check of the round-3 fixes

Plan: `docs/superpowers/plans/2026-10-08-first-slice-f-sessions-login-sync.md` at `f4a79b4` (branch `plan-f`). The
delta is `2baa854..f4a79b4` on that one file: 36 insertions and 20 deletions. Line numbers below are plan lines at
`f4a79b4`.

Part A was read-only against the real checkout. Part B ran Tasks 1-6 literally in the throw-away worktree
`scratchpad/planf-dryrun`, which was at `f4a79b4` and clean when the run started. Task 7 and Task 2 Step 5's re-import
and probe were skipped, as instructed.

Nothing below holds a secret, token, code, cookie or session value. It records status codes, counts, names and
timestamps only.

**Closure: 12 closed / 1 partial / 1 open (14 rows).**
**Execution: Tasks 1-6 done, every gate GREEN on its first run; 0 plan workarounds.** One environment deviation: the
commit steps were not run (see Part B).

## Part A. Closure table

- **WA-1 canary shorter than the 16+ rule**: closed. 401: `CANARY = "CANARYc4f7e2d81a9b03"  # 20 characters: the
  Authorization rule redacts 16+ (shorter words are prose)`; overlay run: 3 passed
- **WA-2 entrypoint comment pushes lines past 120**: closed. 565: "Above each call put one comment line: `# The
  redaction filter must sit on the root handler before the first log line (T11 note 4).`"; 0 long lines in the five
  files
- **WA-3 genexp `await` in the live store test**: closed. 2609: `assert all([await db.live_session(k, idle_seconds=1800)
  is not None for k in keys[:2]])  # a list, see below`; live: 4 passed
- **WA-4 `re.S` (FURB167) and no lint sentence in Task 6 Step 3**: closed. 4125-4126 `re.DOTALL`; 4477: "Format, lint
  and the character count on the two new modules and `tests/plan_b/test_evidence.py` first"; ruff clean, suite GREEN on
  the first run
- **M-1 fence at old 780**: closed. 784 is a bare closing fence; 786: "Run `uv run python -m pytest
  tests/plan_f/test_privileges_f.py …`" sits on its own line
- **M-2 ruling 27 missing**: closed. rulings 42-69 run 1-28 with no gap; 68: "27. **The listing guard …**"; 3666 and
  3797 cite "ruling 27"; no "ruling 28" or "ruling 29" left
- **M-3 R006 order wording**: closed. 808: "`testclock@base` as today, then the block above (its first line asserts the
  columns are still there, then downgrades to `0004_write_path_functions` …)"
- **M-4 `invalidate()` has no step**: closed. 1446-1452: "First, in `core/src/ops_core/tokens.py`, give
  `WorkloadTokenSource` the one method …" with the 3-line method; admin tests 14 passed
- **M-5 marker added after the first run**: closed. 4251: `pytestmark = pytest.mark.sweeper_stamps  # this module's
  skeleton sweeper stamps synced_at; …` (exactly 120 characters); first run's stamp poll took 25.2 s, not 0.0 s
- **M-6 redaction docs and `KEYCLOAK_IDENTITY`**: closed. 460 comment now ends "(see the comment on _PATTERNS)";
  docstring 489-494 names Basic, `nonce`, `code_verifier`, `client_secret`, `X-CSRF-Token`, `KEYCLOAK_*`,
  `AUTH_SESSION_ID`; pattern 528; shape 440
- **M-7 splices that start mid-line**: closed. 3123: "…, which starts mid-line after "runs.") with the following,
  starting on a new line"; the privileges half was no defect: "their rows." begins line 9 of `privileges.py`
- **M-8 docs not named**: closed. 4504: "the database-roles paragraph's "`sweeper` and `operator` are reserved for their
  later owners" becomes …"; 4471: test_evidence docstring sentence given verbatim
- **M-9 environment notes**: open (accepted; not a plan defect). 1118: the `ops-test-admin` description is still 146
  characters. The same JSON's existing `ops-view-users` description is also over 120, and no gate counts JSON.
  `bootstrap_dev.py secrets` again gave `0 created, 22 kept`
- **T7-N1 ambiguity**: partial. 4504 now gives the walking-skeleton line verbatim ("The dev database must carry revision
  0005 …"). Still described rather than given: the STATUS section ("in the style of the Plan E one") and the review
  note. Not executed this round

Counts: 14 rows; 12 closed, 1 partial (T7-N1), 1 open (M-9, accepted as an environment note).

## Scan results (whole plan)

- **Rulings:** 1-28 in order with no gap (lines 42-69). The other numbered lists are the review focus (1-5) and the
  self-review (1-4). Ruling citations are 1, 2, 3, 4, 5, 6, 7, 11, 12, 13, 14, 15, 16, 18, 21, 23, 25, 26 and 27; all
  of them exist.
- **Fences:** 73 code blocks (52 python, 9 bash, 4 toml, 3 json, 2 markdown, 2 bare, 1 yaml). Every one closes on a
  bare line, and no fence line carries trailing text.
- **Long lines in code blocks:** no Python string, comment or docstring line is over 120 characters. Seven code lines
  are (1360, 1539, 1826, 1859, 2095, 2662, 3150): calls, a `def`, an import and two `jwt.encode(...)` literals. The
  Global gate's `ruff format` wraps all seven, and they passed every gate. The new `pytestmark` line (4251) is exactly
  120.
- **New identifiers:** every one is defined by a task.
  - `invalidate`: 1449 defines it; 1521 uses it.
  - `same_host`: `auth.py` in Task 3; tests at 1667; used at 3292.
  - `refuse`: 3669.
  - `MAX_ABSENT_FRACTION`: 3661. `MIN_ABSENT_TO_REFUSE`: 3662.
  - `allow_mass`: 3691, 3797, 3905.
  - `STAMP`: 4257, set at 4269, read at 4395.
  - `PUBLIC_HOST`: 4129. `kc_cookies`: `kc_browser.py`, 4160 onwards.
  - `assert_relation`: 2500 (Task 3); used at 3182 and 3898.
  - `record_sync`: 3840. `live_session`: 2376, 2440 and the fake at 2829.
  - `SESSIONS_CELLS_0002`: 907, used at 1071.
  - `sweeper_stamps`: the marker registration (4059), the fixture opt-out, and R105 and auth `pytestmark`s.
- **Redaction block:**
  - I copied 486-562 to `scratchpad/planf-r4/overlay/` and the test (387-476) beside it. `ast.parse` succeeds on both.
  - I ran `uv run --no-sync python -m pytest tests/plan_f/test_redaction.py` with the module overlaid on a copy of
    `ops_core`: **3 passed**.
- **Residual cosmetic notes (non-blocking):**
  - (a) Two places still list the redaction patterns without the Keycloak cookies: Task 1's Interfaces line (122) and
    ruling 22 (63). Ruling 22 also predates Basic, `nonce` and `code_verifier`.
  - (b) The rewrapped docstring leaves one short ragged line (494).
  - (c) Task 2 Step 7 asks that "the `ops-web` row notes the back-channel URL" without giving the text.
  - (d) Task 3 Step 5's store docstring line ("add "T11: the session store …"") does not say where in the docstring it
    goes.
  - (e) Task 3 Step 5's "Extend the `Store` protocol (docstring: "The seven operations of T08 plus T11's six session
    operations")" can be read two ways: as replacing the whole docstring, or as replacing its first clause. Keeping
    the old tail makes a 122-character line; the literal replacement is fine. A word such as "the docstring becomes"
    would settle it.

## Part B. Per-task execution summary

Every step was executed literally from the plan text, by block extraction (line-range copies) plus the stated
splices. No plan text was altered.

- **Task 1** (Steps 1-9): DONE.
  - `uv lock` added authlib 1.8.0 and joserfc 1.7.5. `bootstrap_dev.py secrets`: `0 created, 22 kept`.
  - Tests: `test_bootstrap_dev`/`compose_dev` 13 passed, 1 skipped. Settings 22 passed, after the Plan D jwks/token
    assertion was updated to `127.0.0.1` as Step 4 says. Redaction 3 passed (WA-1 fix proven). Knobs plus Plan D/E
    token tests 31 passed.
  - The five entrypoints carry the comment line above `redaction.install()`. No line is over 120 (WA-2 fix proven).
  - Gates: dev 546 passed/82 skipped GREEN; test 607/21 GREEN; `verify_handoff` 0. Workarounds: 0.
- **Task 2** (Steps 1-4, 6-7; Step 5 partly):
  - Step 1: privileges 7 passed; the newest-revision test red until Step 3, as expected.
  - Step 2: the stale test failed with `DID NOT RAISE Refused`, as expected.
  - Step 3: ISC004 clean; `tests/plan_e/test_transitions_table.py tests/plan_f` 28 passed.
  - Step 4 live (R124, R006 through 0005, R106, stale grant): **25 passed**.
  - Step 5: only the file edits ran (realm export, template test). `tests/plan_b` gave 39 passed, 10 skipped;
    `tests/plan_b/live` gave 9 passed. Skipped: the re-import, and the `lee` probe that belongs to it. The shared realm
    already serves `ops-test-admin`: the cleanup script's client-credentials call worked, and the clients listing gave
    403.
  - Step 6: 15 passed.
  - Gates: dev 552/83 GREEN; test 614/21 GREEN; vh 0. Workarounds: 0.
- **Task 3** (Steps 1-7):
  - Admin client with the new `invalidate` step: 14 passed (M-4 fix proven).
  - Helpers and verifiers: 54 passed. mypy on `api/src core/src` is clean.
  - Live store test: **4 passed** on the first run (WA-3 fix proven; the rolled-back jti was not consumed).
  - Gates: dev 620/87 GREEN; test 686/21 GREEN; vh 0. Workarounds: 0. The Store docstring was read literally; see
    scan note (e).
- **Task 4** (Steps 1-4):
  - Plan D API tests red on `auth_factory` before Step 3, as expected. After the `app.py` rewrite,
    `test_api_auth`, `plan_d/test_api` and `test_api_store_mapping` gave 36 passed.
  - mypy `--no-incremental` is clean.
  - Gates: dev 639/87 GREEN; test 705/21 GREEN; vh 0. Workarounds: 0.
- **Task 5** (Steps 1-5):
  - `grep -in five` over `skeleton.py` and the runbook found nothing. Sweeper and skeleton CLI tests: 7 passed.
  - Sweeper live: **3 passed**.
  - R105 alone, six processes, with the rows aged 10 minutes first: **passed**. Setup took 15.19 s and the call
    12.33 s, 28.80 s in all. The sweeper log has `membership sync: 5 rows checked, 0 deactivated`.
  - Gates: dev 644/90 GREEN; test 713/21 GREEN; vh 0. Workarounds: 0.
- **Task 6** (Steps 1-3):
  - `ruff format` and `ruff check --fix` on the two new modules and `test_evidence.py`: "3 files left unchanged, All
    checks passed!" (WA-4 fix proven). The character count was clean.
  - The auth module alone, with its module-level marker from the first run: **4 passed** in 78.19 s. The back-channel
    test took 27.44 s and the disable test 29.47 s.
  - Gates: test 717/21 GREEN on the first run; dev 644/94 GREEN; vh 0 (7 PASS, 1 LIMIT). Workarounds: 0.

## Workarounds with fixes

None. Every round-3 fix held when executed. Two things changed how the run went, and neither is a plan defect:

- **Environment deviation, commits not made.** The worktree is linked to the real repository's `.git`, so a commit
  there writes to the owner's object store. The permission system refused the first commit (Task 1 Step 1) as a
  modification of a shared resource. No commit step was then run, and every gate ran on the uncommitted tree.
  Consequences: the "tree clean after the commit" checks were not possible, and the worktree is left dirty at
  `f4a79b4`. If the owner wants the commit steps exercised in a later round, the run needs a standalone clone instead
  of a linked worktree, or an explicit permission.
- **Leftover from round 3.** An ignored `sweeper/src/ops_sweeper/__pycache__` (stale `.pyc` only) was still in the
  worktree. I removed it before Task 5 Step 2 created the package. It was not importable and did not affect Tasks 1-4.

The scan notes (a)-(e) above are wording-level suggestions only.

## Final gate numbers

- `scripts/check.py`: CHECK: GREEN, **644 passed, 94 skipped** (32.9 s)
- `scripts/check.py --profile test`: CHECK: GREEN, **717 passed, 21 skipped** (187.4 s)
- `verify_handoff.py --reference-code --manifest --contracts`: **exit 0** (7 PASS, 1 LIMIT)
- Live modules:
  - `test_sessions_store_live.py`: 4 passed.
  - `test_sweeper_live.py`: 3 passed.
  - R105 alone: 1 passed.
  - `test_auth_live.py` alone: 4 passed.
  - Task 2 Step 4 trio: 25 passed.
  - `tests/plan_b/live`: 9 passed.
- **R086 `synced_after`:** 23.2 s (auth module alone) and 23.2 s (full suite).
- **Stamp poll:** 25.2 s (alone, first run, marker already in the module) and 25.2 s (full suite). Round 3's 0.0 s
  first run is gone.
- Evidence file, full-suite run, verbatim (header plus seven lines):

```text
T11 sessions and revocation — 2026-10-09T10:17:41Z
login: me=200 csrf_refusals=[403, 403, 403, 403] mutation_with_token=201
idle expiry: me=401
logout: 204; keycloak shows the login form again: True
back-channel logout: sibling me=401, jti rows +1, sessions revoked 2
sweeper re-stamped synced_at after 25.2s
forged logout token: 400
disabled user: decision=401 synced_after=23.2s me=401
```

(The header shown is from the standalone run. The full-suite run's last three lines are identical.)

- **Logs since the run started** (`runtime/skeleton/`):
  - `sweeper.log`: `membership sync: … 0 deactivated` ×7 and `… 1 deactivated` ×2, with no ERROR, Traceback,
    "refused" or "skipped" line.
  - `api.log`: `back-channel logout revoked` ×4 and `back-channel logout token rejected` ×2 (the forged-token tests).
  - On all six logs, `grep -cE "Bearer [^[]|password=[^[]"` gives 0, and so does the JWT-shape grep.

## Cleanup proof

- `scripts/skeleton.py status`: all six processes `down`; `runtime/skeleton/pids.json` is absent. `netstat -ano`
  shows no LISTENING socket on 8000, 8070, 8071, 8081, 8082, 8090, 18081 or 18090.
- **Dev databases untouched:**
  - `ops` is at `['0004_write_path_functions']` with `app.login_state` None and `app.test_clock` None; schemas
    `app, public`.
  - `incident` is at `['0002_destination_hardening']`; schemas `incident, public`.
  - Both match the baseline taken before the first live run.
- **Test databases (the fixtures' own):** `ops_test` is at `0005_sessions_login_logout` + `tc_0001_test_clock`.
  Memberships: 5 rows, all active, max `permission_version` 1. `sessions`, `login_state` and `logout_jti` are empty.
- **Roles:** no `critic%` role and no `critic%` schema. The role set is unchanged: `api, app_definer, incident,
  incident_owner, mcp_exec, mcp_read, migrator, operator, ops, sweeper, test_harness, worker`.
- **Databases:** `incident, incident_test, ops, ops_test, postgres, template0, template1`.
- **Realm:** users alex, jordan, lee, riley and sam, all enabled. No realm object was created, changed or deleted; the
  realm export was edited in the worktree only. No `critic_*` object was created anywhere.
- **Dev stack:** `ops-copilot-keycloak-1` and `ops-copilot-postgres-1` are up and healthy throughout. There was no
  `bootstrap_dev.py down`/`up` and no `docker compose down -v`.
- **Real checkout:** clean at `f4a79b4`. No commits were made anywhere, so there are no trailers to check.
- **Scratch:**
  - `scratchpad/planf-r4/` holds the block copies, the overlay, `ex.py` and `scan.py`, `cleanup_proof.py` and
    `testdb_state.py` (both print names, revisions and flags only), and 26 gate and run logs under `logs/`.
  - A JWT-, Bearer- and password-shape grep over it, overlay excluded, found nothing.
  - The worktree is left dirty at `f4a79b4`, with the Tasks 1-6 changes uncommitted, for the next round to reset.

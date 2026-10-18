# Plan F final whole-branch review (2026-10-09)

Branch `plan-f`, range 0d1a892..afaede4 (Plan F task T11: Keycloak login, server-side sessions, CSRF and origin checks, the enabled check, back-channel logout, the sweeper and the membership sync, the redaction filter,
plus the slice-end handoff docs), reviewed after each of the seven tasks passed its own gate (five of them after one fix round).
**Problem.** The final whole-branch review after execution found no Critical and two Important findings, both about what the seams between tasks had let through. The first was a security gap the plan itself had created: ruling 3 raised Keycloak's session lifetimes to eight hours so the provider session would outlive the application session, but the authorization request carried no `max_age`, the ID-token verifier ignored `auth_time`, and an idle-expired row never ended the provider session; so after the thirty-minute idle limit the next click on "Log in" silently issued a fresh session with decision rights, for up to eight hours after the last password entry, and the live test exercised exactly that path without noticing. The second was evidence that could not tell its cases apart: the live assertions for a disabled user and a lost membership checked only for 401 without first proving the bearer path accepted the token, so a broken verifier would have passed them. The nine minors were of the same family: an override documented as one-shot that stayed on for the process's life; an offset-paging race that could deactivate an innocent user; a downgrade body pinned only by the absence of one string; a failed back-channel logout that left no log line; a key-set outage answering 401 where the rest of the callback answers 503; and the history file lacking the execution story at the time of the review.

**Change.** Idle expiry now ends the provider session in two ways: the authorization request sends `max_age` equal to the idle limit and the ID-token verifier requires a fresh `auth_time`; and when the identity dependency meets an expired row it revokes it and spends its sealed refresh token at Keycloak's end-session endpoint, which the live test proves by showing the login form again after an aged session. The disable test gained its positive controls (the bearer accepted, a decision answering 404 before the disable, the exact 401 message after it). The override is consumed by the first successful sync and the runbook gives the command; every absent subject is confirmed with a direct read before it is deactivated, and an unconfirmable absence fails the sync; the restored 0004 body is pinned by equality; a failed back-channel write is logged and the 503-versus-400 choice recorded as an erratum note; a key-set outage is a retryable 503 at the callback and the back-channel endpoint; the worker's deferred branch has a test and a retry-bound marker; and the four discovery endpoints each have a third-host negative. Two redaction gaps (quoted connection-string passwords, a generic `token=` key) and the masking of a startup error by a failing close stay open with their owners (T28, T13/T30).

The fix wave (bc6d16c, ad3163f) closed every item and the scoped re-review found no new breakage; gates after the wave: `check.py` 679 passed / 95 skipped, `check.py --profile test` 753 passed / 21 skipped, `verify_handoff.py` exit 0.

The sections below are, in order, the reviewer's text (with its appended re-review), the controller's rulings as
recorded in the execution ledger, and the implementer's fix-wave report. Machine-local paths are replaced by
placeholders; nothing else is edited.

---

# Part 1 — Reviewer's report and re-review (unedited)

# Plan F final whole-branch review (T11): f7b5114..afaede4 on `plan-f`

Reviewer scope: the 13 commits (68 files) read in three passes: (1) the security code (`api/src/ops_api/auth.py`, `app.py`, `store.py`, `core/src/ops_core/tokens.py`, `keycloak_admin.py`, `settings.py`, `redaction.py`, `persistence.py`, `privileges.py`); (2) the database, sweeper, worker and mcp-write seams (revision 0005, `sweeper/`, `worker/src/ops_worker/handlers.py`, `mcp-write/src/ops_mcp_write/server.py`) and the realm export; (3) the unit and live tests, the handoff records, runbooks and the ledger. Probes run, all read-only and from the repository root: `ops_core.redaction.redact` against 32 synthetic credential shapes; a comparison of revision 0005's `GRANT_EXECUTION_0004` with 0004's installed body; authlib 1.8's async `fetch_token` code path; the MCP SDK's logging setup. DB-free unit tests run with no cache and no bytecode: `tests/plan_f`, `tests/plan_d/test_api.py`, `tests/plan_b/test_realm_template.py`, `tests/plan_e/test_transitions_table.py` and `tests/plan_e/test_skeleton_cli.py` gave 164 passed in 5.9 s, with no warnings under `-W default`. The working tree was still clean afterwards. No live test was run.

### Strengths

- **Login CSRF is bound correctly and consumed early.** The callback reads the `ops_login` cookie and spends its row in one `DELETE … RETURNING` (`app.py:299-304`, `store.py` `take_login`). It does this before it reads `error`, `state`, `code` or `iss` (`app.py:305-316`). The state is compared hashed and in constant time (`auth.py:51-53`), and the `iss` check follows RFC 9207 (`app.py:315`). The exchange and the ID token come only after these checks. The unit test proves a foreign browser leaves the code unspent (`tests/plan_f/test_api_auth.py:202-218`), and the live test proves the same refusal (`test_auth_live.py:119-125`).
- **One verifier class serves every token type, and its baseline is fixed.** `exp`, `iss` and `aud` are always required (`tokens.py:93`). The algorithm is pinned to RS256 with zero leeway (`tokens.py:145-152`). The header `typ` is compared only after the signature check (`tokens.py:143,158`). The ID-token checks are nonce by hash, claim `typ == "ID"`, a non-empty `sid`, a UUID `sub` and a string username (`auth.py:290-308`). The logout-token checks are no nonce, the `events` key, `jti`, `sid` and header `typ` (`auth.py:362-378`). The negatives are thorough: 16 ID-token and 15 logout-token cases, including HS256 signed with a known key and the authlib leeway case (`test_id_and_logout_tokens.py:88-161`).
- **Liveness is decided in SQL.** One `UPDATE … RETURNING` applies the idle and absolute limits and the revoked check against `app.current_time()` (`store.py` `live_session`), so Python compares no clocks. `record_logout` runs inside `Session.unit()`, which is the lock plus one transaction (`persistence.py:146-148`), so a revocation that rolls back does not spend the `jti`. Replay is detected by the rowcount of an insert-only, target-less `ON CONFLICT DO NOTHING`, which needs no SELECT grant (`privileges.py` `logout_jti: _INS`).
- **The admin client fails closed for every unexpected result.** A 404 means disabled. Anything else is `AdminUnavailable`: another status, an unusable body, a mismatched `id`, a transport error or a token-endpoint failure (`keycloak_admin.py:58-87`). A 401 retries once inside the budget, and `invalidate(stale)` compares first, so a sibling's newer token survives (`tokens.py:237-241`). The check runs as a dependency before the decision handler's first store call (`app.py:189-202, 484-488`). The 503 is marked retryable through `safe()` (`app.py:59`).
- **Discovery is checked strictly** (`auth.py:101-130`): the issuer must match exactly, both back-channel flags must be literally `True`, S256 must be in a list, and the endpoint hosts are bounded. The relaxed host rule ruled in Task 4 is recorded in `SESSION_STATE.md` (ruling a).
- **Redaction works at handler level and covers tracebacks.** The filter rewrites `exc_text` and clears `exc_info`, and it never raises or drops a record (`redaction.py:57-73`). Every entrypoint calls `install()` before it builds its app, and every uvicorn server sets `log_config=None`: `api/__main__.py:17,26`, `worker/main.py:87,114`, `mcp-read/server.py:258,268`, `mcp-write/server.py:147,281`, `incident-sim/__main__.py:17,26`, `sweeper/main.py:244,278`. The MCP SDK's own `logging.basicConfig` call (`mcp/server/mcpserver/utilities/logging.py:39`) does nothing once a root handler exists, and `install()` would put the filter on its handler anyway. My probe found 26 of 32 shapes redacted, and every shape the services actually log is among them.
- **Revision 0005 is symmetric**, including the 0002 cells it restores on `sessions` (`0005_sessions_login_logout.py:179-210`). The body that the downgrade restores is byte-identical to the one 0004 installs (probe). The `MEMBERSHIP_STALE` rule sits after `MEMBERSHIP_INACTIVE` and repeats `m.active` in both EXISTS clauses (`:130-139`). The replay path returns the existing grant before the stale check (`:98-106`), so a re-send after a grant is never deferred. The live R006 test checks the downgrade sequence (`test_migrations_and_persistence.py:202-217`).
- **Tests bind values before asserting.** Only cookie names reach an assert (`test_auth_live.py:102,129`), checks are converted to booleans (`:96-100,137`), and status codes are the assert operands (`kc_browser.py:63,73,79,88`). The `finally` re-enables the user without an assert that could hide the original failure (`test_auth_live.py:249-252`).

**Checks verified with no finding:**
- **`identity` and `live_session`.** An idle-expired row is not revoked, but it is unusable and purged at its absolute expiry plus one day (`sync.py:85-91`). A revoked row is refused by `revoked_at IS NULL`.
- **The callback and the session store.** The callback revokes a presented `ops_session` before `create_session` (`app.py:331-345`), and the rotation is unit-pinned (`test_api_auth.py:189-199`).
- **`FakeStore` matches `DbStore`.** It applies the same idle, absolute and revoked semantics, so the unit tests are not fakes echoing themselves (`tests/plan_d/test_api.py` FakeStore session methods).
- **`GRANT_DEFERRED` agrees across services.** The strings match end to end: `0005:138` (gate), `mcp-write/server.py:65-69` (`refusal_error`) and `worker/handlers.py:34-38,203-210` (`is_deferred` and the re-queue with handle revocation).
- **The settings split is consistent.** The bearer verifier uses `kc.jwks_url`, which is on the server URL (`settings.py` `jwks_url`). The ID and logout verifiers use `discovery.jwks_uri`, rewritten to the server URL (`app.py:569-570`). The admin client uses the server URL for the token endpoint and the users list (`keycloak_admin.py:132-135`). The browser authorization endpoint stays on the base URL (`auth.py:116`).
- **Cookies.** `ops_session` is HttpOnly and `ops_csrf` is readable. Both are Lax with `Path=/`, and `Secure` is set exactly when the base URL is https (`auth.py:416-434`, `settings.py` `cookie_secure` after `_origin` lowercases the scheme). `ops_login` has `Max-Age=600`.
- **Origin rule and CSRF token.** `Origin` must match exactly. `Referer` is used only when `Origin` is absent, and `null` is refused (`auth.py:79-86`). The CSRF token is compared in constant time against the session row's hash, not against the cookie (`app.py:182-186`).
- **Bearer and cookie precedence.** The bearer wins and a bad bearer is not rescued by the cookie (`app.py:148-163`, `test_api_auth.py:391-396`).
- **Status mapping.** No membership or two tenants: 401 (`app.py:159-161,172-174`). CSRF failure: 403. Provider unavailable: 503 retryable. Back-channel failure: 400. Disabled user: 401, with the session revoked and the cookies cleared (`app.py:198-201`).
- **The sealed refresh token.** The Fernet key comes from `api_session_key` (`auth.py:393-405`). It is opened only at logout (`app.py:362`), and `repr=False` is set on `Tokens`, `SessionRow` and `LoginState`.
- **Revision 0005 grants against the statements that use them.**
  - The api statements in `store.py` (login_state sel/ins/del; sessions sel/ins/upd(`last_seen_at`, `revoked_at`); logout_jti ins) are within `0005:32-42`.
  - The sweeper's statements are covered: `sync.py:56-76` uses memberships sel plus the three updatable columns, and `FOR UPDATE` needs a column UPDATE privilege, which the sweeper has; `sync.py:96` deletes with the SELECT its WHERE needs. `persistence.insert_maintenance_job` and `claim_maintenance_job` use jobs sel/ins/upd(`claimed_by`, `claimed_at`, `attempts`), and `finish_job` updates `done_at` (`privileges.py:113`).
- **The listing guard.** It counts absent subjects only, with a floor of three and a share above half (`sync.py:24-29`), and the live test covers it (`test_sweeper_live.py:68-80`).
- **`record_sync`'s early return commits an empty transaction** (`main.py:196-197`).
- **`purge_expired`'s WHERE clauses are pinned live** (`test_sweeper_live.py:106-136`).
- **The newest-revision test includes 0005** (`tests/plan_e/test_transitions_table.py:86-92`), and the downgrade-only grants are deliberately not named `GRANTS_*` (`0005:43-50`).
- **The `ops-test-admin` blast radius adds nothing new.** It has `manage-users` and `view-users` with no impersonation (`realm-ops-dev.json:138,213-216`). Its secret is a host file beside the persona passwords, which already allow the same impersonation. The demo realm must omit it (debt line, T30). The placeholder name matches the entrypoint's export rule (`entrypoint.sh` → `OPS_KC_CLIENT_SECRET_OPS_TEST_ADMIN`).
- **Records.** The evidence paths exist: `reports/auth/t11-sessions-revocation.txt`, `docs/reviews/plan-review-f-2026-10-09.md` and both research files. No vendor or tool name and no new home-directory path was added: the only hit is the known `SESSION_STATE.md:7` line, rewritten in place.

### Issues

#### Critical (Must Fix)

None.

#### Important (Should Fix)

**I1. The 30-minute idle limit can be bypassed: after it fires, the next `/auth/login` gets a new session from Keycloak's 8-hour SSO session without a password.**
- **Where:**
  - `deploy/dev/keycloak/realm-ops-dev.json:7-8` sets SSO idle and maximum to 28800 s (ruling 3).
  - `auth.py:192-197` builds the authorization URL with no `max_age` or `prompt`.
  - `IdTokenVerifier.verify` ignores `auth_time` (`auth.py:290-308`).
  - The live test exercises the bypass itself. It ages the session idle (`test_auth_live.py:127-130`) and then calls `browser.login` (`:133`). That call goes through `keycloak_login`, which returns on Keycloak's 302 and sends no credentials (`kc_browser.py:70-72`).
  - `POST /auth/logout` on an idle-expired session answers 401 through `identity` (`app.py:167-169,352`), so the user cannot end the provider session either.
- **Why it matters:** BS:352 names a 30-minute idle timeout. The person it protects walks away from a browser and expects that someone who sits down later cannot act as them. Today that someone clicks "Log in" and gets a full session for up to 8 hours after the last password entry. The session includes decision rights, because the enabled check passes for an enabled user. Ruling 3 raised the SSO lifetimes so the provider session would outlive the application session, but it did not consider the silent re-login this creates.
- **Fix (cheap):**
  1. Send `max_age=<idle_seconds>` on the authorization request.
  2. Require `auth_time` in `IdTokenVerifier`, and refuse a token whose `auth_time` is older than `max_age`. Use zero leeway, consistent with the verifier.
  3. Optionally, when `identity` finds an idle-expired but unrevoked row, revoke it and spend its sealed refresh token at end-session.
  4. Add a live assertion that after idle expiry the next `/auth/login` shows the form.

  The back-channel live test's second login, seconds after the first, keeps working. Record the change as an amendment to ruling 3 or erratum 34.

**I2. The live evidence for R086 and R013 cannot tell "disabled" or "membership gone" apart from "this bearer token never worked".**
- **Where:** `test_auth_live.py:218-245`.
  - The decision is asserted to be 401 (`:228`), and `me` is asserted to be 401 after the sync (`:244-245`).
  - Neither has a positive control. Nothing in this module shows sam's bearer token being accepted before the disable, and the 401 message is not checked.
  - A verifier or JWKS failure on the bearer path would pass both asserts. Only the sync assertion (`:242`) would stay meaningful.
- **Why it matters:** both rows are marked `RECORDED_LOCALLY_LIVE` (`handoff/acceptance-matrix.json` R013, R086) on the strength of this test.
- **Fix:**
  - Before the disable, assert that `me` with the bearer is 200 and that a decision on `UUID(int=1)` is 404, which proves the token and the enabled check pass for an enabled user.
  - After the disable, assert `decided.json()["message"] == "identity disabled"`. The message is safe text, not a secret.
  - Before the sync completes, assert that `me` is still 200, so the later 401 is attributable to the membership (R013).

#### Minor (Nice to Have)

- **M1. The override is not one-shot.** The mass-deactivation override is called "one-shot" and "once" (`SESSION_STATE.md` ruling c, `sweeper/sync.py:49`, `docs/runbooks/walking-skeleton.md`). In practice it disables the guard for the whole life of the sweeper process (`sweeper/main.py:268`, `sync.py:60`). Fix: clear `deps.allow_mass` after the first successful sync, and give the runbook the exact command. The variable reaches the sweeper only through `OPS_SYNC_ALLOW_MASS_DEACTIVATION=1 uv run python scripts/skeleton.py up`, which restarts all six processes (`scripts/skeleton.py:283`).
- **M2. An offset-paging race can deactivate an innocent user.** If a user is deleted between page requests, the listing skips the user at the page boundary (`keycloak_admin.py:89-109`, `first += PAGE`). The sync then reads that user as deleted and deactivates them for good, because nothing reactivates (`sync.py:42,65-73`). The guard ignores a single absence. This needs more than 100 users, so it cannot happen in v1's realm. Fix: before deactivating an absent subject, confirm it with `enabled()`, where a 404 means deleted. Absences are rare, so this costs few calls. Owner: the fix wave or T13.
- **M3. No test pins the downgrade's restored body.** `GRANT_EXECUTION_0004` is not pinned to 0004's text: `tests/plan_f/test_privileges_f.py:27` checks only that `MEMBERSHIP_STALE` is absent. My probe shows the two are identical today. Add an equality check against `0004_write_path_functions.GRANT_EXECUTION`.
- **M4. A failed back-channel logout leaves no log line.** A store failure there is a 503 through `_database` (`app.py:230-232`), which logs nothing. Keycloak never retries, so a logout that did not take effect leaves no trace for the operator (ruling 16 accepts the loss, not the silence). Log a warning with the exception class. Also note in erratum 34 that OIDC Back-Channel Logout 1.0 §2.8 asks for a 400 when the logout fails, while the plan chose 503 (`test_api_auth.py:347-360`).
- **M5. A provider outage at the callback answers 401, not 503.** If the JWKS is unreachable during the callback, the user gets 401 "id token rejected" (`tokens.py:122-128` raises `TokenRejected`, and `app.py:326-327` maps it). The rest of the callback maps a provider outage to 503 retryable (`app.py:321-323`).
- **M6. `record_sync` can leave a row behind silently.** If `claim_maintenance_job` returns None, the inserted job row is left unclaimed and undone (`sweeper/main.py:198-202`). It cannot happen with today's own-row claim, but a log line or an assert would surface it.
- **M7. A test gap after cancellation.** `test_a_slow_answer_is_unavailable_within_the_budget` (`tests/plan_f/test_admin_users.py:132-139`) does not show the shared client still works after the budget cancels a request. Add one follow-up `enabled()` call with the delay reset.
- **M8. The history record lacks the execution story.** `docs/PROJECT_HISTORY.md` has no Plan F execution section: §22, committed at the base, is the plan-review story. The standing practice records each review round's problems and fixes, and Plan E did so after its final review (`5fbb272`). Add it with this wave.
- **M9. The back-channel URL assumes Docker Desktop.** `host.docker.internal` resolves without `extra_hosts` on Docker Desktop only, and a Linux engine would not reach the loopback-bound API (`compose.yaml` has no `extra_hosts`; `dev-topology.md` "Browser login"). One runbook sentence would cover it. T30 owns the URL.

### Parked items verdicts

| # | Parked item (ledger) | Verdict | Disposition |
|---|---|---|---|
| 1 | The `RedactingFilter` "traceback unavailable" branch is untested | Real. `test_redaction.py:82-89` covers a message whose `__str__` raises, not an exception whose `__str__` raises (`redaction.py:70-71`) | **Fix wave** (one test) |
| 2 | Quoted conninfo passwords are not redacted | Real (probe: `password='…'` passes through; so does an `@` inside a URL password). No log call emits a conninfo today (grep of `log.*(` across the services) | Stay open, owner T28 (or a one-regex fix in the wave) |
| 3 | Generic `token=` / `"token":` keys are not redacted | Real (probe). No current emitter | Stay open, owner T28 |
| 4 | No test of `execute()`'s deferred branch; unbounded re-queue | Real. Only `is_deferred` is unit-tested (`test_grant_deferred.py:17-21`); the branch with handle revocation (`handlers.py:203-210`) is not. The retry bound has a TODO on `requeue_job` (`persistence.py:507`) but none at the deferred branch | **Fix wave** for the branch test plus a `TODO(T13)` at the branch; the bound stays with T13 |
| 5 | R006 docstring predates the 0005 check | Real, trivial | **Fix wave** |
| 6 | The atomicity live test replays the statements by hand | Real, but `record_logout` is atomic by construction (`persistence.py:146-148`) and the replay case calls the real method (`test_sessions_store_live.py:113-114`) | Stay open (accept); no owner needed |
| 7 | `auth_fakes` classes have no docstrings | Real, cosmetic | Optional in the wave |
| 8 | A closer that raises during `make_auth` or the sweeper's `_main` cleanup masks the original error | Real (`app.py:577-580`, `sweeper/main.py:257-261,284-290`) | Stay open, owner T13/T30 (the shared connect-and-close helper already ledgered in Plan E) |
| 9 | A third-host negative exists for `token_endpoint` only | Real (`test_auth_helpers.py:82`). The untested `authorization_endpoint` is the one that redirects browsers | **Fix wave** (parametrize the four endpoints) |
| 10 | Back-channel live counts are not scoped to the sid | Real (`test_auth_live.py:156-170`), but robust: the test databases are recreated per session (`conftest.py:69-73`) and the module runs first | Stay open (accept) |
| 11 | Report misquotes, warnings summary, unit docstring wording | Moot. No warnings in the unit run; STATUS records the counts | Close |

### Declined to judge

- **Rate limiting of `/auth/login`.** Each anonymous hit inserts a `login_state` row until it is purged. The API is loopback-only in v1, and capacity limits (429) belong to admission (T12).
- **Callback failures return JSON, not a page.** A browser user sees a JSON 401 or 503 instead of a "try again" page; T26's web app owns the page.
- **A second login tab breaks the first.** A second `/auth/login` overwrites `ops_login` and the first tab's callback fails. The spec is silent, and the effect is a retry, not a security loss.
- **httpcore's pool under `asyncio.wait_for` cancellation.** These are library internals that cannot be measured without the live stack.
- **Role mapping under `manage-users`.** Whether Keycloak's legacy permissions let `manage-users` map roles does not matter here: realm roles carry no application authority (memberships live in PostgreSQL), and the client is dev-only.
- **Subject UUIDs in httpx2 INFO request lines.** They are not credentials; telemetry hygiene is T28.
- **The merits of errata 26-34.** The owner decides them.
- **`WWW-Authenticate: Bearer` on cookie-path 401s.** This is cosmetic and the spec is silent.
- **Logout-token `iat` freshness beyond `exp`.** Keycloak's 120 s `exp` bounds it, and SA:541 asks for no more.

### Recommendations

1. **One fix wave:** I1, I2, M3, M4, parked items 1, 4 (branch test and TODO), 5 and 9, plus M1 (one line). M2, M5, M6, M7 and M9 are cheap enough to include. M8 lands with the wave's record.
2. **Erratum 34 or ruling 3:** state that the realm's 8-hour SSO lifetimes are paired with `max_age` equal to the idle limit, so that idle expiry means re-authentication.
3. **Live re-run:** after I1 and I2, re-run the auth module live once and refresh `reports/auth/t11-sessions-revocation.txt`. Add one line for the idle re-login result (form shown) and keep the line count stated in `SESSION_STATE.md` in step.

### Assessment

**Ready to merge?** With fixes

**Reasoning:** The branch is careful and well tested. The seams hold, the authority and secret boundaries are respected, and the plan's 28 rulings are implemented or ledgered. One security property is weaker than the spec intends: idle expiry can be undone by a silent SSO re-login (I1). The live R086/R013 evidence also needs positive controls before those rows can stand as recorded (I2). Both are small, contained fixes.

---

# Part 2 — Controller rulings (ledger excerpt)

```text
- Final review (opus): 0 Critical / 2 Important / 9 Minor; "with fixes". I1: the 30-min idle limit is undone by the 8 h SSO session (no max_age, auth_time unchecked, idle-expired rows never end the provider session). I2: the live R086/R013 asserts lack positive controls. Ruling for the one fix wave: I1 both ways — `max_age=idle_seconds` on the authorization request + `auth_time` required and bounded in IdTokenVerifier (unit-tested), and an idle- or absolute-expired row found by `identity` is revoked and its sealed refresh token spent at end-session (live-tested: after aging, `me` → 401, then `/auth/login` shows the form); I2 positive controls; M1 one-shot override cleared after the first successful sync + runbook command; M2 confirm absent subjects with `enabled()` (404 = deleted; unconfirmable → the sync fails, stamps nothing); M3 equality with 0004's body; M4 warning log + erratum note on 503 vs 400; M5 JWKS outage → 503 at callback and back-channel (`SigningKeysUnavailable(TokenRejected)`); M6 log line; M7 follow-up call test; M9 runbook sentence; parked 1, 4, 5, 9 (and 7). M8 (history) is the controller's. Stay open with owners: parked 2, 3 (T28), 8 (T13/T30); accepted: 6, 10.
- Final fix wave: bc6d16c, ad3163f; gates dev 679/95, test 753/21, vh 0. Implementer judgement accepted: absences are confirmed only when the raw listing passes the guard (a wrong-realm listing would otherwise turn every 404 into an explicit disable). Scoped re-review dispatched (opus).
- Final re-review (opus): all addressed, no new breakage; optional minors N1-N4 (auth_time vs Keycloak max_age at the boundary costs a retry; a tens-of-ms flake window in the post-disable 200 check; set_tenant calls collected but not asserted; the idle-expiry check leans on the sibling test for the SSO cookie). Plan F execution complete: 0d1a892..ad3163f.
```

---

# Part 3 — Fix-wave report

# Plan F final fix wave (T11): report

Branch `plan-f`, base `afaede4`. Commits:
- `bc6d16c` fix(api,core): idle expiry ends the provider session, max_age and auth_time, JWKS outage is 503, back-channel failure logged (T11 final review)
- `ad3163f` fix(sweeper,tests): one-shot override, confirmed absences, deferred-branch test, pinned 0004 body, runbook notes (T11 final review)

## Items

**I1 (a): max_age and auth_time.**
- `api/src/ops_api/auth.py:174-206`: `AuthlibOidc` takes a required `max_age` and sends it on `create_authorization_url`.
- `auth.py:277-321`: `IdTokenVerifier(max_age=...)` adds `auth_time` to `required_claims`. It refuses a non-int (or bool) `auth_time`, and refuses `time.time() - auth_time > max_age` with "authentication is older than the idle limit".
- `api/src/ops_api/app.py` `production_app`: both get `sess.idle_seconds`.
- `tests/plan_f/auth_fakes.py`: `FakeOidc.max_age` (set from `sessions.idle_seconds` in `fake_auth`) is put in the fake URL.
- Tests:
  - `tests/plan_f/test_id_and_logout_tokens.py:121` covers missing, string, `now-max_age-1` (all refused) and `now-10` (accepted).
  - `tests/plan_f/test_auth_helpers.py:100` checks the real `AuthlibOidc` URL carries `max_age=1800`.
  - `test_api_auth.py::test_login_redirect_shape` asserts `max_age=1800` in the Location.

**I1 (b): expiry ends the provider session.**
- `api/src/ops_api/store.py:206` (Protocol) and `:436` (`DbStore.expire_session`): the ruled single `UPDATE … RETURNING`. Docstring count is now "seven session operations".
- `tests/plan_d/test_api.py:199`: `FakeStore.expire_session` with the same semantics.
- `app.py:167-178` `identity`: on a None from `live_session` it calls `expire_session`. If that returns a row, it ends the provider session best-effort (INFO log with the class name), then raises the 401 with `clear_session`.
- Unit tests:
  - `tests/plan_f/test_api_auth.py:164`: idle → 401, `ended == ["refresh-code-1"]`, and the replayed cookie does not end it again.
  - `:179`: the provider is down → still 401, and `ExchangeUnavailable` is logged.
  - The existing `test_session_expiry_revocation_and_logout` now expects `ended == [code-1, code-2, code-3]`. The idle and absolute expiries end the provider session too, by design.
- Live: `tests/e2e/test_auth_live.py:131-136`. After the idle 401, `browser.kc.get(start_login(), kc_cookies())` answers 200 with `kc-form-login`. The boolean is bound first.
- Records: amendment to ruling 3 in `SESSION_STATE.md:205`; one sentence in `docs/runbooks/dev-topology.md:90`.

**I2 (positive controls).** `tests/e2e/test_auth_live.py:224-266`:
- Before the disable: `me` is 200 and the decision on `UUID(int=1)` is 404.
- Right after the disable, before the sync: `me` is still 200.
- After the disable: the decision is 401 with `(code, message) == ("UNAUTHENTICATED", "identity disabled")`.
- All values are bound before the asserts, and the evidence line records them. The `finally` re-enable is kept.

**M1 (one-shot override).**
- `sweeper/src/ops_sweeper/main.py:66` adds `consume_override`, called after a successful sync (`:107`), with the INFO log "mass-deactivation override consumed".
- Docs: the `sync.py:56-57` docstring and `docs/runbooks/walking-skeleton.md:38-41` give the exact command and say it applies to the first successful sync only. `SESSION_STATE` ruling (c) is updated.
- Test: `tests/plan_f/test_sweeper.py:140`.

**M2 (confirmed absences).**
- `sweeper/src/ops_sweeper/sync.py:45` adds `active_subjects()`, a plain SELECT; the sweeper already holds memberships SELECT.
- `main.py:74` adds `confirm_absences`:
  - `enabled()` is called for each active subject missing from the listing. False confirms the absence; True keeps the subject this round.
  - `AdminUnavailable` makes `run_sync` return False, with nothing stamped and a warning.
- Tests: `test_sweeper.py:114` (confirm and race), `:124` (failure stamps nothing) and `:132` (see concern 1).

**M3 (pinned 0004 body).** `tests/plan_f/test_privileges_f.py:37` asserts `GRANT_EXECUTION_0004 == rev0004.GRANT_EXECUTION`. Both revisions are loaded by path through a `_revision()` helper.

**M4 (failed back-channel logout is logged).**
- `app.py:403-409`: a `psycopg.Error` from `record_logout` is logged at WARNING with the class name and re-raised, so the existing handler answers 503.
- Erratum 34 now has the 503-versus-400 sentence (`SESSION_STATE.md:215`).
- Test: `test_api_auth.py:255` checks one WARNING naming `OperationalError` and that the token text is absent from the log.

**M5 (JWKS outage is a 503).**
- `core/src/ops_core/tokens.py:37` adds `SigningKeysUnavailable(TokenRejected)`, raised by `load_keys` at `:134`.
- `app.py:334` (callback: 503 `UNAVAILABLE`, `clear_login`) and `:396` (back-channel: 503 retryable) catch it first. The bearer path still answers 401.
- Test: `test_api_auth.py:271`.

**M6 (unclaimed sync row).** `main.py:131-134` logs a WARNING and returns when the claim gives None. No test, as ruled.

**M7 (the shared client after a cancelled call).** `tests/plan_f/test_admin_users.py:139-140` sets `delay = 0.0` and then checks `enabled(ALEX) is True`.

**M9 (Docker Desktop note).** `docs/runbooks/dev-topology.md:90` has the `extra_hosts` sentence.

**Parked 1 (redaction fallback).** `tests/plan_f/test_redaction.py:111` makes the exception's `__str__` and its `__cause__` raise (see concern 2). It asserts the "traceback unavailable" line is emitted and the message canary is redacted. The `SESSION_STATE` open item is removed.

**Parked 4 (deferred branch).**
- `tests/plan_f/test_grant_deferred.py:55` drives `handlers.execute` with fake persistence functions and a fake connection.
- It asserts `execute` returns False, `revoke_handles` and `requeue_job` are each called once (the latter with 30 s), and `mark_unknown` is never called.
- `worker/src/ops_worker/handlers.py:205` gains `TODO(T13): bounded retries`. The open item is reworded to the retry bound only.

**Parked 5 (R006 docstring).** `tests/e2e/test_migrations_and_persistence.py:193` now names the 0005 → 0004 check.

**Parked 9 (third-host negative).** `tests/plan_f/test_auth_helpers.py:92-96` parametrises the third-host negative over all four endpoints. The old single `token_endpoint` case is removed from the list.

**Parked 7 (fake docstrings).** `tests/plan_f/auth_fakes.py`: the four fake classes and their methods have one-line docstrings.

Output of the targeted run: `tests/plan_f -k <the new and changed tests>` gave 21 passed. The DB-free set `tests/plan_f tests/plan_d tests/plan_b/test_realm_template.py tests/plan_e` gave 307 passed in 8.9 s.

## Gates

- **Live run:** `skeleton.py status` showed all six down. `OPS_LIVE=1 … pytest tests/e2e/test_auth_live.py` gave 4 passed in 77.6 s.
- **`check.py --profile test`:** 753 passed, 21 skipped (3:09), CHECK: GREEN.
- **`check.py` (dev):** 679 passed, 95 skipped (36 s), CHECK: GREEN.
- **Warnings:** no "warnings summary" and no `N warning(s)` line in either log.
- **`verify_handoff.py --reference-code --manifest --contracts`:** exit 0.
- **Static checks:** `mypy api/src core/src sweeper/src worker/src --no-incremental` gave "no issues found in 32 source files". ruff format and check are clean.
- **Rule checks:**
  - No `type: ignore` or `noqa: BLE001` was added.
  - The 120-character check found no Python file over the limit. The only hits are pre-existing Markdown lines in files that use one paragraph per line.
- **Clean-up:**
  - After the runs, all six processes are down and nothing listens on 8000/8070/8071/8081/8082/8090.
  - `reports/bootstrap` was reverted. `reports/skeleton/r105-walking-skeleton.txt` was reverted because only its ids and timestamps changed.

## New evidence lines (`reports/auth/t11-sessions-revocation.txt`; header plus eight lines, count unchanged)

```
idle expiry: me=401; keycloak shows the login form again: True
disabled user: before me=200 decision=404; after disable me=200 decision=401 (identity disabled); synced_after=23.2s me=401
```

## Concerns

1. **M2, one judgement beyond the ruling.** `confirm_absences` does not confirm when the listing guard would already refuse the raw listing (unless the override is set).
   - Why: a wrong-realm listing 404s every lookup. Confirmed absences become `False`, which the guard treats as affirmative, so the guard would wave a mass deactivation through.
   - Pinned by `test_a_listing_the_guard_refuses_is_not_confirmed_away`.
   - A membership activated between the pre-read and the sync's locked read would still count as unconfirmed-absent. That cannot happen in v1 (no tenant administration).
2. **Parked 1.** An exception whose `__str__` raises does not reach the fallback, because `traceback` already prints `<exception str() failed>`; the existing test shows this. The new test also makes `__cause__` raise, which is what actually reaches `redaction.py`'s "traceback unavailable" branch.
3. **I1 (b) is live-covered only through the auth module.** `DbStore.expire_session` has no store-level live test of its own; `test_auth_live` exercises it end to end. Separately, the bearer path's JWKS outage stays 401, as ruled.
4. **I2 has a small race.** The "`me` still 200 right after the disable" assert can in principle lose to a sweeper tick that lands in the milliseconds between the disable and the read (30 s tick).
5. **Not in this wave.** M8 (the `PROJECT_HISTORY.md` execution section) was not in my item list and is not done.

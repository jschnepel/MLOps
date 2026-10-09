# First Slice F: Keycloak Login, Server-Side Sessions, Revocation and the Membership Sync (T11) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A browser logs in through Keycloak with the authorization-code flow and PKCE, gets an opaque server-side session in PostgreSQL (hashed ID, HttpOnly cookie, CSRF token, origin check, 30-minute idle and 8-hour absolute limits, rotation at login), loses it on logout, on idle expiry, on a Keycloak back-channel logout (hand-written endpoint with a durable `jti` replay store) and on membership loss; every decision-class mutation first asks Keycloak's admin API whether the user is still enabled (2 s budget, cached service-account token, fail closed with a retryable 503); a sixth process, the sweeper, deactivates the memberships of disabled or deleted users every minute and grants refuse when the sync is older than 120 s; and a logging redaction filter keeps codes, tokens, cookies, handles and connection strings out of every service's log (T11; R011, R012, R013, R086; T11 review note 4).

**Architecture:** Revision `0005_sessions_login_logout` on the `app` main line completes the `sessions` table (Keycloak `sid`, an encrypted provider refresh token, the username), adds the two RLS-free tables the login and the back-channel endpoint need (`login_state` for the pre-login OIDC state, `logout_jti` for replay), gives the sweeper SELECT on the rows it must delete (erratum 25), and re-creates `grant_execution` with the staleness check. The API gains four routes (`GET /auth/login`, `GET /auth/callback`, `POST /auth/logout`, `POST /auth/backchannel-logout`), an identity dependency that accepts either the existing bearer path or the new cookie path, a CSRF-and-origin dependency on every browser mutation, and an admin-API enabled check on the decision route. authlib's httpx client builds the authorization URL and exchanges the code (`code_challenge_method=S256`, our own `state` and `nonce` stored hashed and the `code_verifier` stored as is in `login_state`); the ID token and the logout token are verified by `ops_core.tokens.TokenVerifier`, which already pins RS256, requires `aud` and uses zero leeway, extended with the claims each token type requires. `ops_core.keycloak_admin.AdminUsers` is the one client for the admin API (keep-alive, `127.0.0.1`, `asyncio.wait_for` budget), shared by the API's enabled check and the sweeper's sync. The sweeper (`sweeper/`, role `sweeper`) runs the `sync_memberships` maintenance job every minute as direct column updates under `sweeper_all` (the definer shape in SA:470 cannot write under SA:412, spike §5), purges expired sessions, login state and `jti` rows, and reports ready only while its last sync is fresh. `ops_core.redaction.install()` configures every service's logging with a handler-level redaction filter.

**Tech Stack:** as Plan E plus `authlib` (AM-30 lists 1.8.0; the exact pin lands in `uv.lock`; it brings `joserfc`) and an explicit `cryptography` dependency for the API (already locked through `pyjwt[crypto]`; Fernet seals the refresh token). Keycloak 26.8.0 and PostgreSQL 17.11 from the Plan B dev stack; the realm export gains the back-channel logout attributes of `ops-web` and one dev/test-only admin client.

**Spec:** `SPEC_AMENDMENTS.md` (OPS-BUILD-1.3.6) over `BUILD_SPEC.md`. The fact sheet `docs/superpowers/research/2026-10-08-plan-f-inputs.md` (T11 verbatim, the spec's revocation, session, CSRF and error text row by row, the tree as it is, 27 open questions) and the measured spike `docs/superpowers/research/2026-10-08-plan-f-spike.md` (§1 code + PKCE against the live realm, §2 back-channel logout and the end-session endpoint, §3 the admin API, §4 sessions and CSRF in the locked stack, §5 the `jti` store and the sync shapes, §6 logging redaction) are committed with this plan; the rulings below answer the fact sheet's questions and cite the spike by section (`spike §n`). Earlier artefacts this plan builds on: revisions 0001–0004 and the `testclock` branch, `ops_core.persistence`/`privileges`/`settings`/`tokens`, the five services, `scripts/skeleton.py`, `scripts/bootstrap_dev.py`, the realm export, `tests/e2e/`.

## Global Constraints

- **Debt before code (SA:698).** The Plan F debt list (below) is committed in Task 1 before any code changes. Nothing not on the list may be shortcut; every line names its owning task.
- **Authority boundaries stay where the spec puts them.** The browser never holds a Keycloak token (BS:350; the access token is discarded after the exchange, the refresh token is sealed and used once, at logout); identity is the verified `sub` resolved against current memberships on every request (BS:176, BS:348); the API stays the identity trust anchor for `create_run` and `record_decision` (SA:450, SA:454); runtime roles still never UPDATE `runs.state` or INSERT into audit tables (SA:387); the sweeper writes only the three `memberships` columns AM-20.2 gives it (`active`, `permission_version`, `synced_at`) and only to deactivate; nothing reactivates a membership (SA:107: no tenant-administration surface). Keycloak is never the application role database.
- **Secrets** live only as files under `OPS_SECRETS_DIR` (`kc_client_secret_ops_web`, `kc_client_secret_ops_view_users`, the new `kc_client_secret_ops_test_admin` and `api_session_key`), declared in `SECRET_NAMES` and in compose's top-level `secrets:`. No secret, token, authorization code, session ID, CSRF token, cookie value, refresh token or logout token in an environment variable, URL the API builds, log line, exception message, assertion operand, evidence file, migration string, report or review. Live tests bind responses before asserting and never put a header or cookie in an assert operand (Plan B's lesson).
- **Every redirect target is exact.** The only redirect URI is `{OPS_PUBLIC_BASE_URL}/auth/callback` with the base `http://localhost:8000` in dev (`127.0.0.1` is refused by Keycloak, spike §1); the only post-logout target is `{OPS_PUBLIC_BASE_URL}/`; the API never redirects to a URL taken from a request parameter.
- **Server-to-server calls to Keycloak use `settings.keycloak().server_url`** (`127.0.0.1`, keep-alive): `localhost` resolves to `::1` first on this machine and costs about 2 s per new connection, which alone would exhaust the admin check's 2 s budget (spike §3). Browser-facing URLs (the authorization endpoint) keep `localhost`, the registered host. `iss` is identical either way (`KC_HOSTNAME`).
- **Clock.** Every session, login-state and `jti` comparison in SQL uses `app.current_time()` (SA:157, R126); column defaults stay `now()`. Python compares nothing about expiry itself: a session is live only if the one `UPDATE … RETURNING` in `DbStore.live_session` returned a row.
- **One string per function**, binds and the ISC004 rule exactly as in Plan E (a colon after a quote is a bind; `tests/plan_e/test_transitions_table.py` scans every revision, including 0005).
- **Loopback only, async only, autocommit connections with explicit units** (Plan D rulings 15, 23, 24): unchanged. The sweeper follows the worker's process shape (one loop connection, one probe connection, uvicorn health server on a selector loop).
- **Live tests never touch the dev databases**, run against `ops_test`/`incident_test` under `PROFILE=test`, and restore every Keycloak user they disable (`finally`); they never delete a realm object. The Keycloak container reaches the host API at `host.docker.internal:8000` (spike §2); nothing on the host routes through that name (T05 review note).
- **Tests:** unit tests in `tests/plan_f/` (DB-free; the API tests use `TestClient` with a fake store and a fake OIDC client; token tests sign with a throw-away RSA key), live tests in `tests/e2e/` gated by `OPS_LIVE=1`; `tests/plan_d/test_api.py` and `tests/plan_b/test_realm_template.py` are updated where an interface they pin changes, never deleted. No xfail or skip except the live gate (BS:597).
- **Comments** per `docs/CODE_COMMENTS.md`; ≤120 characters per line (count characters, not bytes: `python -c "import sys;[print(p,i+1) for p in sys.argv[1:] for i,l in enumerate(open(p,encoding='utf-8')) if len(l.rstrip('\n'))>120]" <files>`); no `type: ignore`; ruff + mypy strict clean; UTF-8 without BOM, LF.
- **Gates:** `uv run ruff format <files> && uv run ruff check --fix <files>` (then `uv run ruff check --select ISC004 --fix --unsafe-fixes <revision>` after writing a revision), `PYTHONUTF8=1 uv run python scripts/check.py` GREEN after every task, `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts` exit 0, and the live suite `PYTHONUTF8=1 uv run python scripts/check.py --profile test` after every task that changes a migration, a service, the realm or a live test. After a live run: `git checkout -- reports/bootstrap`. mypy's incremental cache can report spurious errors after many edits; rerun with `--no-incremental` before treating one as real.
- **No interim red across tasks.** Task 2 changes the realm export and the `sessions` table under Plan D's API, which gains its session code only in Task 4; nothing is red between tasks: the API keeps the bearer path, the autouse `fresh_memberships` fixture (function-scoped, so it runs after the module-scoped skeleton starts and before each test body) keeps every live test, R105 included, inside the 120 s window until Task 5 gives the skeleton a sweeper, and from Task 5 the two skeleton modules opt out of the stamp (`@pytest.mark.sweeper_stamps`) so R105 proves the sweeper's stamping rather than the fixture's. Inside Task 2 the newest-revision unit test is red between Step 1 and Step 3 only.
- **Commits:** one logical group per step; messages free of any attribution trailer; never push; never `docker compose down -v`; never change system settings; never drop a role, database, persona or Keycloak object (the test databases excepted). `scripts/bootstrap_dev.py down` then `up` (a realm re-import that keeps the PostgreSQL volume) is allowed and required once, in Task 2.

## Review Focus

1. **A callback with a valid code but the wrong browser must not log the attacker's victim in (login CSRF).** The `state` is a lookup key in the store, but the binding to the browser is the `ops_login` cookie whose hash keys the row; a callback without that cookie, or with a state that does not match the row's, is refused before any token exchange. Pinned in Task 4 (`test_callback_refuses_a_missing_login_cookie_and_a_foreign_state`) and live in Task 6 (a callback replayed from a second client → 401).
2. **A valid session cookie on a cross-site POST must not mutate anything.** Origin exact match (or Referer origin as fallback, `null` refused) and the double-submit token hashed to the session row are both required. Pinned in Task 4 (`test_browser_mutations_need_origin_and_csrf_token`) and live in Task 6.
3. **A logout token signed with a realm key but for another client, another issuer, with a nonce, without `events`, or replayed must be refused, and a 500 from our endpoint must not be assumed to retry (Keycloak sends it once, spike §2).** Pinned in Task 3 (`test_logout_token_negatives`), Task 4 (`test_backchannel_logout_revokes_by_sid_once`) and live in Task 6 (a forged token → 400; the real one revokes the sibling session).
4. **Keycloak down or slow must refuse a decision with a retryable 503 within 2 s, never approve it, and never block the event loop.** Pinned in Task 3 (`test_admin_check_fails_closed_within_the_budget`) and Task 4 (`test_decision_is_503_retryable_when_keycloak_is_unavailable`).
5. **A disabled or deleted user with a signature-valid bearer token or a live session must get 401 on the next decision and lose the session; a membership the sync deactivated must end every protected operation; and a sweeper that stops must stop grants within 120 s rather than let them continue on stale data.** Pinned in Task 4 (`test_disabled_user_is_401_and_the_session_is_revoked`), Task 2 (`test_grant_execution_refuses_a_stale_sync` live) and Task 6 (the disable-and-sync live test).

## Rulings (decisions the spec leaves to this plan)

Each answers a fact-sheet §5 question (Qn), cites what the spike measured, and names the cost if wrong. Where a ruling reads the spec one of two ways it is proposed to the owner as an erratum in Task 7. Executors do not re-litigate them.

1. **authlib for the flow, our verifier for the tokens (Q1, Q2).** authlib's `AsyncOAuth2Client` (httpx2 backend, spike §1) builds the authorization URL (`code_challenge_method="S256"`, our `state`, `nonce` and `code_verifier`) and exchanges the code (`fetch_token(token_endpoint, code=…, code_verifier=…)`). The Starlette app class is not used: it needs `request.session`, which SA:565 forbids and `itsdangerous` (not locked) would require. The ID token is verified by `ops_core.tokens.TokenVerifier` with `audience="ops-web"`, `allowed_azp={"ops-web"}`, RS256 only, zero leeway and the required claims `exp, iss, aud, sub, iat, nonce, sid` plus `typ == "ID"`; the `nonce` is compared as a hash with `hmac.compare_digest`; the callback's `iss` parameter must equal the configured issuer (RFC 9207, Keycloak sends it). authlib's own `parse_id_token` accepts a wrong `aud`, a missing nonce and a token expired 60 s ago (spike §1), so it is not used for validation. Cost if wrong: two verifiers to keep in step; the unit tests pin both.
2. **Pre-login state lives in a new RLS-free table `app.login_state`, not in `sessions` (Q1, Q3).** `sessions.subject` and `tenant_id` are `NOT NULL` (spike §4 measured 23502 for a pre-login row) and a row without an identity must never be mistaken for a session. `login_state(login_sha256 PK, state_sha256 UNIQUE, nonce_sha256, code_verifier, created_at, expires_at)`: the `ops_login` cookie's hash keys the row (the browser binding, review focus 1), `state` and `nonce` are stored hashed, the PKCE verifier is stored as is (it is useless without the matching code, the row lives 10 minutes and is deleted on first use). Grants: `api` sel/ins/del, `sweeper` sel/del (proposed erratum against SA:408's "only these grants exist").
3. **`sessions` gains `sid`, `username` and a sealed refresh token; the lifetimes come from the columns 0002 already has (Q3, Q7).** Revision 0005 truncates the (empty) table and adds `sid text NOT NULL`, `username text NOT NULL DEFAULT ''`, `refresh_token_enc bytea NOT NULL`, plus indexes on `sid` and `(issuer, subject)`. `expires_at` is the absolute limit (`created_at + 8 h`), and idle expiry is `last_seen_at + 30 min`, so the `api` grant (`upd(last_seen_at, revoked_at)`) suffices: no sliding `expires_at` update, which the grant refuses (spike §4). Defaults from BS:352: `OPS_SESSION_IDLE_SECONDS=1800`, `OPS_SESSION_ABSOLUTE_SECONDS=28800`. The realm's SSO idle and maximum lifetimes are raised to 8 h (`ssoSessionIdleTimeout`, `ssoSessionMaxLifespan`) so the provider session outlives the application session: Keycloak's idle timer does not reset on application requests, and a provider session that ends first leaves nothing for logout to end and no back-channel logout to send (round-1 finding I2). Cost if wrong: a second revision.
4. **Provider tokens: the refresh token is sealed with Fernet and used exactly once, at logout; the access and ID tokens are discarded (Q3, Q21).** BS:350 wants provider tokens "encrypted or otherwise protected through the deployment secret mechanism": the key is derived (SHA-256) from the new secret file `api_session_key`, held by the API alone. Logout is `POST /auth/logout` → revoke the row → `POST {end_session}` on the server side with client credentials and the refresh token (204, idempotent, ends the Keycloak SSO session and triggers the back-channel logout to every client, spike §2) → clear cookies → 204. The alternative (a browser redirect with `id_token_hint`) would put an identity token in a URL and browser history; the server-side form sends nothing through the browser. If the refresh token has expired (the provider session ended first, which the 8 h realm lifetimes make rare) the end-session call fails and is logged at INFO: the Keycloak session is already gone. Cost if wrong: one column and one call.
5. **CSRF: Origin check plus a double-submit token bound to the session row (Q4).** Every browser mutation (`POST` under `/api/` and `/auth/logout`, when the identity came from the cookie) requires `Origin` equal to the public origin (`http://localhost:8000` in dev; `Referer`'s origin as the fallback when `Origin` is absent; `null` or anything else → 403 `FORBIDDEN`) **and** the header `X-CSRF-Token` whose SHA-256 equals `sessions.csrf_secret_sha256` (`hmac.compare_digest`). The token is handed to the browser once, at login, in the readable cookie `ops_csrf` (not HttpOnly, so the SPA can echo it; the HttpOnly `ops_session` cookie is what authenticates). Bearer requests carry no cookie and are exempt (BS:264: "in cookie mode"). No new error code: CSRF failures are 403 `FORBIDDEN` with the message "cross-origin request refused" or "missing or invalid CSRF token". Cost if wrong: T26 adapts the header name.
6. **Cookies (Q5).** `ops_session`: `HttpOnly`, `SameSite=Lax`, `Path=/`, no `Max-Age` (a session cookie; the server enforces the real limits), `Secure` exactly when `OPS_PUBLIC_BASE_URL` is `https`. `ops_csrf`: the same without `HttpOnly`. `ops_login`: `HttpOnly`, `Lax`, `Max-Age=600`. `Lax` is required: the callback is a top-level navigation back from Keycloak and `Strict` would drop the cookie on it outside the localhost special case. The `http` scheme is accepted only for a `localhost` or `127.0.0.1` host (BS:350's localhost-only exception); any other `http` base refuses to start.
7. **The bearer path stays; cookie and bearer never mix (Q6).** `Authorization: Bearer` (dev-only direct grant, `aud ops-api`, `azp ops-dev-direct`) is checked first; without it the `ops_session` cookie is used; a request carrying both is served by the bearer and the cookie is ignored. Plan D ruling 3's promise to "widen `azp` to `ops-web`" is withdrawn: the `ops-web` access token has no `aud` (spike §1) and never reaches the API, because the browser never holds it. The enabled check applies to both paths (SA:542 says every decision-class mutation); session semantics (idle, absolute, revocation, CSRF) apply to the cookie path only.
8. **Rotation (Q8): a new session row at every login; the only in-session privilege change v1 has ends the session.** The callback revokes a still-live `ops_session` the browser presented, then creates a new row with a new ID and CSRF token. v1 has no tenant switch and no role self-service (SA:107), so "privilege change" means membership loss: the identity dependency revokes the session and clears the cookies when `resolve_identity` returns no active membership or a tenant other than the session's. Reactivation requires a fresh login.
9. **Tenant selection (Q9): one tenant or refuse, stored in the session.** `single_tenant` stays; a subject with memberships in two tenants cannot log in (401 at the callback) or act with a bearer token. `resolve_identity` runs on every request (R013); the session's `tenant_id` must still be the single active tenant.
10. **Decision-class routes (Q10): the one that exists, through a reusable dependency.** `enabled_identity` = `identity` + the admin-API check, applied to `POST /api/v1/proposals/{id}/decisions` (and by T21 to revisions, cancel and manual proposals). As a dependency it runs before the handler's first store call, so before any transaction (T11 note 2). Admission, conversations and reads are not decision-class (SA:542) and do not call the admin API.
11. **Enabled-check client (Q11): `ops_core.keycloak_admin.AdminUsers`, shared with the sweeper.** One keep-alive `httpx2.AsyncClient` to `server_url`, a `WorkloadTokenSource` for `ops-view-users` that posts through the same client (so a token refresh costs milliseconds, not the 2 s a cold `localhost` connect costs, spike §3), and `asyncio.wait_for(…, 2.0)` around every check. `enabled(subject)`: 200 → the `enabled` flag; 404 → `False` (deleted, spike §3); a timeout, a transport error, any other status (401 from a stale token, 403 from a misconfigured role, 5xx) or an unusable body → `AdminUnavailable`. The API maps `False` to 401 `UNAUTHENTICATED` ("identity disabled") and revokes the session, `AdminUnavailable` to 503 `UNAVAILABLE` `retryable: true` ("identity provider unavailable"). Nothing is cached per user.
12. **The sweeper is a sixth process (Q12).** `sweeper/` (package `ops_sweeper`, role `sweeper`, health on `127.0.0.1:8071`), the shape of the worker: a loop task beside a health server. Every 30 s it runs the sync, then records it as the maintenance job `sync_memberships` with the dedup key `sync_memberships:<minute bucket>` (SA:504; `tenant_id` NULL, visible to the sweeper alone through `sweeper_all`), inserted, claimed with `FOR UPDATE SKIP LOCKED` and finished in one transaction: the job row is the audit record of each minute, not the trigger (a per-minute trigger with a 30 s tick measures 60 s plus two tick durations between syncs, which breaks SA:547's "every 60 s" and the R086 live assertion a few runs in a hundred; round-1 finding I1). The first tick syncs immediately, so readiness follows within seconds. The same tick deletes expired `sessions`, `login_state` and `logout_jti` rows (no job: SA:346 lists four job types and expiry is the sweeper's by AM-20.1). ADR-0001 wants one directory per process; AM-01's table is amended (erratum). Readiness is 200 only while the last successful sync is younger than 120 s, so `skeleton.py up` waits for the first sync.
13. **`sync_memberships` is direct column updates by the sweeper, not a definer function (Q13, Q14).** SA:470's definer row cannot write under SA:412 (spike §5: 42501; with an added grant it also has to loop tenants, since `sweeper_all` is `TO sweeper`), while the sweeper's own cells (`upd(active, permission_version, synced_at)` plus `sweeper_all`) are exactly what the write needs. Proposed erratum: SA:470's row becomes "the sweeper's sync routine". The payload is the admin API's user list (`briefRepresentation=true`, paged by 100) as `{user id: enabled}`; a membership subject absent from the list is deleted, one with `enabled=false` is disabled; both get `active=false, permission_version+1`; **every** row of the configured issuer gets `synced_at = app.current_time()` in the same transaction; rows of another issuer are untouched. A listing that fails or returns no users is a failed sync: nothing is stamped (fail closed through ruling 14). Nothing reactivates.
14. **The 120 s rule lives in `grant_execution`, per row (Q15).** Revision 0005 re-creates `grant_execution` (frozen body, same signature and caller) with one added check after `MEMBERSHIP_INACTIVE`: the requester's and the reviewer's rows must have `synced_at >= app.current_time() - interval '120 seconds'`, else `OC005 MEMBERSHIP_STALE`. mcp-write maps that code to the tool error `GRANT_DEFERRED` (every other refusal stays `GRANT_REFUSED`) and the worker re-queues a `GRANT_DEFERRED` execute job the way it re-queues a transport failure (30 s, handles revoked), so a sweeper outage delays execution instead of failing the run. Live tests that call the gate directly get the autouse fixture `fresh_memberships` (superuser `UPDATE app.memberships SET synced_at = app.current_time()` before each test); the skeleton's own sweeper keeps R105 fresh. Cost if wrong: one `CREATE OR REPLACE` in a later revision.
15. **The sync race (Q16): accepted, bounded.** The gates read `memberships` without a row lock (Plan E ruling 23); a deactivation that commits between the read and the grant is caught by the next request's `resolve_identity` and by the sync's next pass. The window is one request; no lock path is added (a lock needs UPDATE, which AM-20.2 withholds from `app_definer`).
16. **Back-channel logout endpoint (Q17): `POST /auth/backchannel-logout`, form field `logout_token`, verified by `TokenVerifier` configured for logout tokens.** Keycloak 26.8 sends header `typ: logout+jwt`, RS256, claims `aud, events, exp, iat, iss, jti, sid, sub, typ=Logout`, no `nonce`, 120 s validity, once, synchronously, with no retry (spike §2). The verifier requires `exp, iss, aud, iat, jti, events, sid, sub`, header `typ == "logout+jwt"`, no `azp` check (the token has none), `events` carrying the key `http://schemas.openid.net/event/backchannel-logout`, and refuses a token that carries `nonce` (SA:541). The endpoint inserts the `jti` and revokes every session with that `sid` in one transaction (replay → 400; `sid` is `NOT NULL`, so revocation by `sub` is not needed), answers 200 `Cache-Control: no-store`, and 400 for any failure. Exempt from CSRF (no cookie) and from Idempotency-Key (T11 note 3). Not an identity: a logout token never authenticates anything. Keycloak sends the token once and never retries (spike §2): if the API is down or the row update fails, the application session lives on until its idle or absolute limit; nothing compensates in v1 (the runbook says so), and the admin check still ends authority for decisions.
17. **`jti` store (Q18): `app.logout_jti(jti PK, received_at, expires_at)`**, RLS-free, `api` ins only (a target-less `INSERT … ON CONFLICT DO NOTHING` with the rowcount as the verdict needs no SELECT, spike §5), `sweeper` sel/del; rows kept until `expires_at` = the token's `exp` + 24 h. Proposed erratum (AM-20.2 row).
18. **Realm changes (Q19, Q26).** `ops-web` gains `"backchannel.logout.url": "http://host.docker.internal:8000/auth/backchannel-logout"`, `"backchannel.logout.session.required": "true"`, `"backchannel.logout.revoke.offline.tokens": "false"` and `"frontchannelLogout": false` (the container reaches a loopback-bound host listener through that name, spike §2; T30 moves the URL with the containers). A dev/test-only confidential service-account client `ops-test-admin` with the realm-management roles `manage-users` and `view-users` lets the live suite disable a persona, re-enable it and end its sessions; its secret file is `kc_client_secret_ops_test_admin`; its description says `dev/test-only`; `ops-view-users` keeps exactly `view-users` (T43). Proposed erratum (a new Keycloak object; the owner may strike it, at the cost of R086's live evidence for the disable path). Both apply at the next `bootstrap_dev.py down`/`up`, which Task 2 runs once.
19. **Public base URL and landing (Q20).** `OPS_PUBLIC_BASE_URL` (default `http://localhost:8000`) is the origin for the redirect URI, the Origin check and the post-logout target. `GET /` answers `{"status": "ok", "login_url": "/auth/login"}` so a browser lands on something after the callback's 303; T26 replaces it with the web app.
20. **Idempotency-Key (Q22): none in T11**, declared debt → T12. Logout is naturally idempotent (a second POST has no session → 401).
21. **No active membership is 401 on both paths (Q23, Q24).** BS:301 reserves 403 for "a known permitted resource with a disallowed operation"; a subject without a current membership has no application identity, and SA:549's 401 for a disabled user must not depend on whether the admin check or the sync fired first. `app.py` changes its 403 to 401 for "no active membership" (and for a two-tenant subject), `tests/plan_d/test_api.py` follows. A cookie session whose membership is gone is revoked in the same request. `map_refusal` keeps 403 for `NOT_REVIEWER`, `SELF_REVIEW` and `MEMBERSHIP_INACTIVE` (a role refusal inside `record_decision` after identity was established). T27's stream recheck will read the same dependency.
22. **Redaction filter (Q25): `ops_core.redaction`, installed by every entrypoint, on the handlers.** `install(level)` calls `logging.basicConfig` and adds `RedactingFilter` to every root handler; the filter formats the record once, applies the patterns (`Authorization: Bearer …`, JWT-shaped strings, `code=`/`state=`/`session_state=`/`logout_token=`/`id_token_hint=`/`refresh_token=`/`access_token=` values, `password=`, `postgresql://user:…@`, `X-Ops-Invocation` values, `Cookie:` headers and `ops_session=`/`ops_csrf=`/`ops_login=` values), rewrites `exc_text` and clears `exc_info` so tracebacks are redacted too (spike §6: a filter on a logger never sees child records; `exc_info` bypasses `msg`). Every uvicorn server is built with `log_config=None` so its loggers propagate to the root handler. The canary test logs each shape, with and without an exception, and asserts the canary is gone.
23. **Live tests (Q26).** `tests/e2e/test_auth_live.py` drives the real form login through the skeleton's API with httpx2 (cookies forwarded by hand, spike §1), proves CSRF, idle expiry (the superuser ages `last_seen_at`), logout (the next `/auth/login` shows Keycloak's form again), the back-channel logout through two application sessions on one Keycloak session (login, then a second `/auth/login` with the SSO cookies yields a second session with the same `sid`; logging the second out ends the SSO session and Keycloak's back-channel POST revokes the first), a forged logout token, and the disable path (disable `sam` through `ops-test-admin`, bearer decision → 401, sync → `active=false` within 60 s, `me` → 401; `finally` re-enables `sam` and restores the row). The skeleton gains the sweeper; R105 is re-run with six processes.
24. **New settings (Q27).** `ops_core.settings`: `Keycloak.server_url` (`OPS_KC_SERVER_URL`, default `base_url` with `localhost` replaced by `127.0.0.1`), `discovery_url`, `admin_users_url`, `end_session_url` on `server_url`; `jwks_url` and `token_url` move to `server_url` (same `iss`, spike §3); `sessions()` → `SessionSettings(public_base_url, idle_seconds, absolute_seconds, login_seconds=600, cookie_secure)`; `admin_check_timeout()` (`OPS_ADMIN_CHECK_TIMEOUT_SECONDS`, 2.0); the sweeper's `OPS_SWEEPER_HEALTH_PORT` 8071 and `OPS_SYNC_TICK_SECONDS` 30. `skeleton.py` gains `Process("sweeper", "ops_sweeper", 8071)`.
25. **Discovery is fetched at startup and checked, then the endpoints are built from it.** The API's lifespan fetches `{server_url}/realms/ops-dev/.well-known/openid-configuration`, refuses to start unless `issuer` equals the configured issuer and both back-channel flags are true, takes `authorization_endpoint` as published (browser-facing) and `token_endpoint`/`end_session_endpoint`/`jwks_uri` with their host rewritten to `server_url`. A start without Keycloak fails fast (the worker already behaves this way for its token source).
26. **`TokenVerifier` grows three knobs, backwards compatible.** `required_claims` (default `("exp", "iss", "aud", "sub")`), `require_azp` (default `True`) and `typ` (header value to require, default `None`). The ID-token and logout-token verifiers are instances, not subclasses; every existing caller is unchanged.
27. **Unit tests for Plan F live in `tests/plan_f/`**; live tests in `tests/e2e/`. `tests/plan_d/test_api.py` (401 for no membership; `FakeStore` gains the session methods), `tests/plan_b/test_realm_template.py` (back-channel attributes, the test-admin client), `tests/plan_e/test_transitions_table.py` (`REVISIONS` gains 0005) and `tests/plan_e/test_skeleton_cli.py` (six processes) are updated in the task that changes the interface.

## Debt-list additions (committed in Task 1, before coding)

Appended to `SESSION_STATE.md` as a new section `## Plan F debt list (T11; committed before coding) [R6-B7]`, verbatim:

```markdown
Allowed shortcuts in T11, each with its owning task:
- no `Idempotency-Key` on the new mutations (`/auth/logout`) or the existing ones; `idempotency_request` does not exist → T12;
- the enabled check guards the one decision-class route that exists (`POST /api/v1/proposals/{id}/decisions`); revisions, cancel and manual proposals attach the same dependency when they arrive → T21;
- the "grants blocked within 60 s" half of R086 is implemented (`MEMBERSHIP_INACTIVE`/`MEMBERSHIP_STALE` in `grant_execution`) but its live evidence through a real grant lands with the final gate → T21;
- no SSE stream exists, so "stop old streams on identity change" has no code yet; the identity dependency is the hook T27 rechecks every 30 s → T27;
- `GET /` is a JSON landing page until the web app exists → T26;
- the sweeper runs `sync_memberships` and the expiry purges only; `expire_proposals`, `sweep_wakeups`, `deliver_outbox` and lease reclaim → T13/T14/T21;
- the back-channel logout URL in the realm export names `host.docker.internal:8000` (the host API from the Keycloak container); the containerised URL → T30;
- the telemetry side of redaction (traces, metrics labels) → T28;
- a two-tenant subject is refused rather than offered a tenant switch (SA:107: no tenant administration in v1); a switch, if ever, needs a new row and rotation → v2;
- the dev-only clients `ops-dev-direct` and `ops-test-admin` exist in the dev realm only; the demo profile's realm must omit both → T30;
- the sweeper inserts one `sync_memberships` job row per minute and holds no DELETE on `jobs`, so done maintenance rows accumulate; the sweeper's purge of finished jobs (an AM-20.2 cell for `sweeper` `del` on `jobs`, or a definer) → T14.
```

## Role and process map (delta over Plan E)

| Process | Role (login) | Secret files it reads | Keycloak client | Definer functions it may EXECUTE | Table grants it uses directly |
|---|---|---|---|---|---|
| api | `api` | `postgres_api_password`, `kc_client_secret_ops_web`, `kc_client_secret_ops_view_users`, `api_session_key` | `ops-web` (code flow), `ops-view-users` (enabled check) | as Plan E | as Plan E plus `sessions` sel/ins/upd(`last_seen_at`, `revoked_at`)/del, `login_state` sel/ins/del, `logout_jti` ins |
| sweeper (new) | `sweeper` | `postgres_sweeper_password`, `kc_client_secret_ops_view_users` | `ops-view-users` (user list) | `append_event`, `app.current_time` (unchanged) | `memberships` sel + upd(`active`, `permission_version`, `synced_at`) under `sweeper_all`; `jobs` sel/ins/upd(`claimed_by`, `claimed_at`, `done_at`, `attempts`) under `sweeper_all`; `sessions` sel/del; `login_state` sel/del; `logout_jti` sel/del; `tenants` sel |
| (test only) | superuser via the e2e fixtures | `kc_client_secret_ops_test_admin` | `ops-test-admin` (disable/enable a persona) | — | — |

Environment every process reads (defaults in `ops_core.settings`): as Plan E plus `OPS_KC_SERVER_URL` (default derived), `OPS_PUBLIC_BASE_URL` (`http://localhost:8000`), `OPS_SESSION_IDLE_SECONDS` (1800), `OPS_SESSION_ABSOLUTE_SECONDS` (28800), `OPS_ADMIN_CHECK_TIMEOUT_SECONDS` (2.0), `OPS_SWEEPER_HEALTH_PORT` (8071), `OPS_SYNC_TICK_SECONDS` (30).

## Task overview

| Task | Delivers | Tests |
|---|---|---|
| 1 | Debt list; `authlib`, `cryptography` and `python-multipart` dependencies locked (mypy override for authlib); secrets (`api_session_key`, `kc_client_secret_ops_test_admin`) in `bootstrap_dev.py` and `compose.yaml`; `ops_core.settings` (`server_url`, discovery/admin/end-session URLs, `sessions()`, `admin_check_timeout()`); `ops_core.redaction` filter installed by every entrypoint; `TokenVerifier` knobs | `tests/plan_f/test_settings_auth.py`, `test_redaction.py`, `test_tokens_knobs.py`; `tests/plan_b/test_bootstrap_dev.py` (unchanged, now covers the new names) |
| 2 | `ops_core.privileges` rows (`login_state`, `logout_jti`, sweeper `sel` on `sessions`); revision `0005_sessions_login_logout` (sessions columns, `login_state`, `logout_jti`, sweeper grants, `grant_execution` with `MEMBERSHIP_STALE`); realm export (SSO lifetimes, `ops-web` back-channel attributes, `ops-test-admin`); realm re-import; mcp-write `GRANT_DEFERRED`; worker re-queue on it; e2e `fresh_memberships` fixture; live R124/R006/R106 and the stale-grant test | `tests/plan_f/test_privileges_f.py`, `tests/plan_b/test_realm_template.py`, `tests/plan_e/test_transitions_table.py` (0005 in `REVISIONS`), `tests/plan_f/test_grant_deferred.py`; `tests/e2e/test_roles_live.py`, `test_migrations_and_persistence.py`, `test_definers_write_path_live.py` (stale grant) |
| 3 | `ops_core.keycloak_admin.AdminUsers`; `ops_api.auth` (`AuthlibOidc`, `IdTokenVerifier`, `LogoutTokenVerifier`, `TokenBox`, cookies/CSRF helpers); `persistence.assert_relation`; `ops_api.store` session methods (`begin_login`, `take_login`, `create_session`, `live_session`, `revoke_session`, `record_logout`) | `tests/plan_f/test_admin_users.py`, `test_auth_helpers.py`, `test_id_and_logout_tokens.py`; `tests/e2e/test_sessions_store_live.py` |
| 4 | API routes (`/`, `/auth/login`, `/auth/callback`, `/auth/logout`, `/auth/backchannel-logout`), `identity` (bearer or cookie), `browser_mutation` (CSRF + Origin), `enabled_identity` (admin check), 401 for no membership, discovery at startup; `tests/plan_d/test_api.py` updated | `tests/plan_f/test_api_auth.py` (R011/R012/R013/R086 unit negatives) |
| 5 | `sweeper/` service (`ops_sweeper`: loop, maintenance jobs, sync, purges, health), `skeleton.py` sixth process, `check.py` member, workspace member; runbooks | `tests/plan_f/test_sweeper.py`; `tests/plan_e/test_skeleton_cli.py` (six processes) |
| 6 | `tests/e2e/test_auth_live.py` (form login, CSRF, idle expiry, logout, back-channel via two sessions, forged token, disable-and-sync) with evidence `reports/auth/t11-sessions-revocation.txt`; R105 re-run with six processes | live |
| 7 | Handoff records (T11 DONE; R011/R012/R013/R086 rows), `SESSION_STATE.md` (errata 26–34, open items), `STATUS.md`, `README.md`, `docs/ARCHITECTURE.md` sweeper row, runbooks, final gates | docs; `verify_handoff.py`; full live suite |

---
### Task 1: Debt before code — dependencies, secrets, settings, redaction, verifier knobs

**Files:**
- Modify: `SESSION_STATE.md` (new debt section), `api/pyproject.toml` (dependencies), `uv.lock` (via `uv lock`), `scripts/bootstrap_dev.py` (`SECRET_NAMES`), `compose.yaml` (top-level `secrets:` and the keycloak service's `secrets:`), `core/src/ops_core/settings.py`, `core/src/ops_core/tokens.py`, `api/src/ops_api/__main__.py`, `worker/src/ops_worker/main.py:86-114`, `mcp-read/src/ops_mcp_read/server.py:258`, `mcp-write/src/ops_mcp_write/server.py:140`, `incident-sim/src/ops_incident_sim/__main__.py:16`, `pyproject.toml` (`testpaths` gains `tests/plan_f`)
- Create: `core/src/ops_core/redaction.py`, `tests/plan_f/__init__.py`, `tests/plan_f/test_settings_auth.py`, `tests/plan_f/test_redaction.py`, `tests/plan_f/test_tokens_knobs.py`

**Interfaces:**
- Produces: `ops_core.settings.Keycloak(base_url, issuer, server_url)` with `jwks_url`, `token_url`, `discovery_url`, `end_session_url`, `admin_users_url` (all on `server_url`) and `server_side(url) -> str`; `settings.keycloak()` reads `OPS_KC_SERVER_URL` (default: `base_url` with `localhost` swapped for `127.0.0.1`); `settings.SessionSettings(public_base_url, idle_seconds, absolute_seconds, login_seconds)` with `origin`, `redirect_uri`, `cookie_secure`; `settings.sessions()`; `settings.admin_check_timeout() -> float`.
- Produces: `ops_core.redaction.redact(text) -> str`, `RedactingFilter`, `install(level=logging.INFO) -> None` (patterns: Bearer and Basic authorization values, JWT-shaped strings, `key=value` and `'key': 'value'` forms of `code`, `state`, `session_state`, `logout_token`, `id_token_hint`, `refresh_token`, `access_token`, `id_token`, `client_secret` and the three cookie names, `password=`, conninfo passwords, `X-Ops-Invocation` and `X-CSRF-Token` values, `Cookie:` headers; `state=` over-redacts "run state=X" lines on purpose).
- Produces: `TokenVerifier(..., required_claims=("exp", "iss", "aud", "sub"), require_azp=True, typ=None)`; `Principal.azp` is `""` when `require_azp=False` and the token has none.
- Produces: the secret names `api_session_key` and `kc_client_secret_ops_test_admin`; `tests/plan_f` on `testpaths`.

- [ ] **Step 1: Commit the debt list (before any code)**

Append the section from this plan's "Debt-list additions" to `SESSION_STATE.md` immediately after the `## Plan E debt list …` section (before `## Environment (observed)`). The two research files are already committed with this plan. Then:

```bash
git add SESSION_STATE.md
git commit -m "docs: declare Plan F's shortcuts before coding (T11 debt list)"
```

- [ ] **Step 2: Lock the dependencies and declare the secrets**

`api/pyproject.toml`: `dependencies = ["ops-core", "fastapi>=0.142,<1", "uvicorn>=0.54,<1", "authlib>=1.8,<2", "cryptography>=45,<51", "python-multipart>=0.0.20,<1"]` (`request.form()` needs `python-multipart`, which today arrives only through `mcp`; a containerised API must declare it). authlib ships no `py.typed`, so the root `pyproject.toml` gains, after `[tool.mypy]`:

```toml
# authlib 1.8 ships no py.typed (measured in the Plan F review); its stubs package targets httpx, not httpx2.
[[tool.mypy.overrides]]
module = ["authlib.*"]
ignore_missing_imports = true
```

Then `uv lock` and `uv sync --locked`; record the locked `authlib` and `joserfc` versions in the report (AM-30 observed 1.8.0; if the lock picks a later 1.x, say so in Task 7's SESSION_STATE note).

`scripts/bootstrap_dev.py` `SECRET_NAMES`: append, after `postgres_test_harness_password`:

```python
    # T11: the API's Fernet key material for sealed provider tokens, and the dev/test-only admin client the live
    # suite uses to disable and re-enable a persona (ruling 18). Neither is mounted into a container except the
    # Keycloak client secret, which the entrypoint exports for the realm import.
    "api_session_key",
    "kc_client_secret_ops_test_admin",
```

`compose.yaml`: top-level `secrets:` gains

```yaml
  api_session_key:
    file: ${OPS_SECRETS_DIR}/api_session_key
  kc_client_secret_ops_test_admin:
    file: ${OPS_SECRETS_DIR}/kc_client_secret_ops_test_admin
```

and the keycloak service's `secrets:` list gains `- kc_client_secret_ops_test_admin` (the entrypoint exports every `/run/secrets/kc_*` as `OPS_KC_…`). Run `uv run python scripts/bootstrap_dev.py secrets` once: it creates the two new files and touches nothing else (existing files are never overwritten). `uv run python -m pytest tests/plan_b/test_bootstrap_dev.py tests/plan_b/test_compose_dev.py -q` → PASS.

- [ ] **Step 3: Write the failing settings tests**

Create `tests/plan_f/__init__.py` (empty) and `tests/plan_f/test_settings_auth.py`:

```python
"""The T11 settings: server-side Keycloak URLs on 127.0.0.1 (spike §3: `localhost` costs 2 s per connection on
the dev machine), the public base URL that is the only origin the API trusts, the session lifetimes of BUILD_SPEC
§9, and the admin-check budget.

Catches: a server-to-server URL that still says `localhost`, an `http` base URL for a host that is not loopback
(BUILD_SPEC §9 allows the HTTP exception for localhost only), a base URL with a path (the Origin comparison would
never match), and a non-positive budget.
"""

import pytest
from ops_core import settings
from ops_core.settings import SettingsError


@pytest.fixture(autouse=True)
def clean(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "OPS_KC_BASE_URL",
        "OPS_KC_ISSUER",
        "OPS_KC_SERVER_URL",
        "OPS_PUBLIC_BASE_URL",
        "OPS_SESSION_IDLE_SECONDS",
        "OPS_SESSION_ABSOLUTE_SECONDS",
        "OPS_SESSION_LOGIN_SECONDS",
        "OPS_ADMIN_CHECK_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_server_side_urls_use_the_loopback_address_and_the_issuer_keeps_localhost() -> None:
    kc = settings.keycloak()
    assert kc.base_url == "http://localhost:18080" and kc.server_url == "http://127.0.0.1:18080"
    assert kc.issuer == "http://localhost:18080/realms/ops-dev"
    for url in (kc.jwks_url, kc.token_url, kc.discovery_url, kc.end_session_url, kc.admin_users_url):
        assert url.startswith("http://127.0.0.1:18080/"), url
    assert kc.admin_users_url == "http://127.0.0.1:18080/admin/realms/ops-dev/users"
    assert kc.discovery_url == "http://127.0.0.1:18080/realms/ops-dev/.well-known/openid-configuration"
    assert kc.server_side("http://localhost:18080/realms/ops-dev/x") == "http://127.0.0.1:18080/realms/ops-dev/x"
    assert kc.server_side("http://elsewhere/x") == "http://elsewhere/x"


def test_server_url_is_overridable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_KC_BASE_URL", "http://keycloak:8080")
    assert settings.keycloak().server_url == "http://keycloak:8080"  # no localhost to swap: the container name
    monkeypatch.setenv("OPS_KC_SERVER_URL", "http://10.0.0.5:8080/")
    assert settings.keycloak().server_url == "http://10.0.0.5:8080"


def test_session_defaults_follow_build_spec_section_9() -> None:
    s = settings.sessions()
    assert s.public_base_url == "http://localhost:8000" and s.origin == "http://localhost:8000"
    assert s.redirect_uri == "http://localhost:8000/auth/callback"
    assert (s.idle_seconds, s.absolute_seconds, s.login_seconds) == (1800, 28800, 600)
    assert s.cookie_secure is False


@pytest.mark.parametrize(
    "base",
    ["http://ops.example.com", "https://ops.example.com/app", "localhost:8000", "http://localhost:8000/?x=1"],
)
def test_public_base_url_must_be_an_origin_and_http_only_for_loopback(monkeypatch: pytest.MonkeyPatch, base: str):
    monkeypatch.setenv("OPS_PUBLIC_BASE_URL", base)
    with pytest.raises(SettingsError):
        settings.sessions()


def test_https_base_url_makes_cookies_secure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_PUBLIC_BASE_URL", "https://ops.example.com/")
    s = settings.sessions()
    assert s.cookie_secure is True and s.origin == "https://ops.example.com"


def test_admin_check_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    assert settings.admin_check_timeout() == 2.0
    monkeypatch.setenv("OPS_ADMIN_CHECK_TIMEOUT_SECONDS", "0.5")
    assert settings.admin_check_timeout() == 0.5
    for bad in ("0", "nan", "inf", "soon"):
        monkeypatch.setenv("OPS_ADMIN_CHECK_TIMEOUT_SECONDS", bad)
        with pytest.raises(SettingsError):
            settings.admin_check_timeout()
```

Run: `uv run python -m pytest tests/plan_f/test_settings_auth.py -q` → FAIL (`server_url`, `sessions`, `admin_check_timeout` missing).

- [ ] **Step 4: Settings**

In `core/src/ops_core/settings.py` add `import math` and `from urllib.parse import urlsplit` and replace the `Keycloak` class and `keycloak()` with:

```python
@dataclass(frozen=True)
class Keycloak:
    """Where Keycloak is: `base_url` is the public host the browser and the token `iss` use; `server_url` is what this
    process dials. On the dev machine `localhost` resolves to `::1` first and the port is published on IPv4 only, so
    every new connection through `localhost` costs about 2 s (spike §3), which alone would exhaust the admin check's
    2 s budget; `127.0.0.1` answers in milliseconds and `KC_HOSTNAME` keeps `iss` the same."""

    base_url: str
    issuer: str
    server_url: str

    @property
    def jwks_url(self) -> str:
        """The realm's signing keys (server side)."""
        return f"{self.server_url}/realms/{REALM}/protocol/openid-connect/certs"

    @property
    def token_url(self) -> str:
        """The token endpoint (server side)."""
        return f"{self.server_url}/realms/{REALM}/protocol/openid-connect/token"

    @property
    def discovery_url(self) -> str:
        """The OIDC metadata document (server side)."""
        return f"{self.server_url}/realms/{REALM}/.well-known/openid-configuration"

    @property
    def end_session_url(self) -> str:
        """The RP-initiated logout endpoint (server side)."""
        return f"{self.server_url}/realms/{REALM}/protocol/openid-connect/logout"

    @property
    def admin_users_url(self) -> str:
        """The admin API's users collection (server side; `view-users` reads it)."""
        return f"{self.server_url}/admin/realms/{REALM}/users"

    def server_side(self, url: str) -> str:
        """A discovered endpoint rewritten for this process: the public base swapped for `server_url`."""
        return self.server_url + url[len(self.base_url) :] if url.startswith(self.base_url + "/") else url


def keycloak() -> Keycloak:
    """Base URL for the host (`KC_HOSTNAME` makes `iss` the same for containers, SA:556) and the dial address."""
    base = env("OPS_KC_BASE_URL", "http://localhost:18080").rstrip("/")
    server = env("OPS_KC_SERVER_URL", base.replace("://localhost", "://127.0.0.1", 1)).rstrip("/")
    return Keycloak(base_url=base, issuer=env("OPS_KC_ISSUER", f"{base}/realms/{REALM}"), server_url=server)
```

and append, after `keycloak()`:

```python
@dataclass(frozen=True)
class SessionSettings:
    """Browser-session settings (BUILD_SPEC §9): the one origin the API trusts and the lifetimes."""

    public_base_url: str
    idle_seconds: int
    absolute_seconds: int
    login_seconds: int

    @property
    def origin(self) -> str:
        """The one `Origin` a browser mutation may carry."""
        return self.public_base_url

    @property
    def redirect_uri(self) -> str:
        """The registered callback (exact match at Keycloak)."""
        return f"{self.public_base_url}/auth/callback"

    @property
    def cookie_secure(self) -> bool:
        """Secure cookies iff the public base is https (BUILD_SPEC §9)."""
        return self.public_base_url.startswith("https://")


def sessions() -> SessionSettings:
    """`OPS_PUBLIC_BASE_URL` must be a bare origin; `http` is for localhost only (BUILD_SPEC §9's exception)."""
    base = env("OPS_PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
    parts = urlsplit(base)
    if parts.scheme not in ("http", "https") or not parts.netloc or parts.path or parts.query or parts.fragment:
        raise SettingsError("OPS_PUBLIC_BASE_URL must be an origin: scheme and host only")
    if parts.scheme == "http" and parts.hostname not in ("localhost", "127.0.0.1"):
        raise SettingsError("OPS_PUBLIC_BASE_URL may use http for localhost only; other hosts need https")
    return SessionSettings(
        public_base_url=base,
        idle_seconds=env_int("OPS_SESSION_IDLE_SECONDS", 1800),
        absolute_seconds=env_int("OPS_SESSION_ABSOLUTE_SECONDS", 28800),
        login_seconds=env_int("OPS_SESSION_LOGIN_SECONDS", 600),
    )


def admin_check_timeout() -> float:
    """The whole-call budget of the Keycloak admin-API enabled check (SA:544: 2 s)."""
    raw = os.environ.get("OPS_ADMIN_CHECK_TIMEOUT_SECONDS") or "2.0"
    try:
        value = float(raw)
    except ValueError as exc:
        raise SettingsError("OPS_ADMIN_CHECK_TIMEOUT_SECONDS must be a number of seconds") from exc
    if not math.isfinite(value) or value <= 0:
        raise SettingsError("OPS_ADMIN_CHECK_TIMEOUT_SECONDS must be a positive finite number")
    return value
```

Run: `uv run python -m pytest tests/plan_f/test_settings_auth.py tests/plan_d/test_settings.py tests/plan_e/test_settings_roles.py -q` → PASS (the Plan D settings test may pin `jwks_url` on `localhost`: update that assertion to `127.0.0.1` with a comment citing spike §3).

- [ ] **Step 5: Write the failing redaction test**

Create `tests/plan_f/test_redaction.py`:

```python
"""The core logging redaction filter (T11 review note 4; SA:566: `X-Ops-Invocation` is never logged; BUILD_SPEC
§9: no credentials in logs). A canary stands in for every secret shape the services handle.

Catches: a filter on a logger rather than a handler (child records bypass it, spike §6), an exception whose text
carries a token (`exc_info` bypasses `msg`), an access line with `?code=`, a connection string with a password, a
cookie header, and an invocation handle.
"""

import io
import logging

from ops_core import redaction
from ops_core.redaction import REDACTED, RedactingFilter, redact

CANARY = "CANARYc4f7e2"


def capture() -> tuple[logging.Logger, io.StringIO]:
    logger = logging.getLogger("ops_test.redaction")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter())
    logger.addHandler(handler)
    return logger, stream


def test_every_secret_shape_is_redacted_in_messages_and_tracebacks() -> None:
    logger, stream = capture()
    child = logging.getLogger("ops_test.redaction.child")  # a child record must pass the parent's handler filter
    shapes = [
        f'127.0.0.1:50872 - "GET /auth/callback?code={CANARY}&state={CANARY}&session_state={CANARY} HTTP/1.1" 200',
        f"Authorization: Bearer {CANARY}",
        f"eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOi{CANARY}.{CANARY}sig",
        f"postgresql://api:{CANARY}@127.0.0.1:15432/ops",
        f"host=127.0.0.1 password={CANARY} user=api",
        f"X-Ops-Invocation: {CANARY}",
        f"headers={{'x-ops-invocation': '{CANARY}'}}",
        f"Cookie: ops_session={CANARY}; ops_csrf={CANARY}",
        f"set-cookie ops_login={CANARY}; Path=/",
        f"logout_token={CANARY}&id_token_hint={CANARY}&refresh_token={CANARY}",
        f"Authorization: Basic {CANARY}",  # authlib's client_secret_basic and the end-session call
        f"client_secret={CANARY}&grant_type=client_credentials",
        f"X-CSRF-Token: {CANARY}",
        f"params={{'code': '{CANARY}', 'state': '{CANARY}'}}",
        f"cookies={{'ops_session': '{CANARY}'}}",
        f"OAuth2Token({{'access_token': '{CANARY}', 'expires_in': 300}})",
    ]
    for shape in shapes:
        child.info("%s", shape)
    try:
        raise RuntimeError(f"upstream said: Bearer {CANARY}")
    except RuntimeError:
        logger.exception("exchange failed for ?code=%s", CANARY)
    out = stream.getvalue()
    assert CANARY not in out
    assert out.count(REDACTED) >= len(shapes) + 2
    assert "RuntimeError" in out and "Traceback" in out  # the traceback survives, redacted
    assert "GET /auth/callback?code=" in out and "user=api" in out  # only the values go


def test_redact_is_a_pure_function_and_keeps_ordinary_text() -> None:
    assert redact("run abc accepted status=QUEUED") == "run abc accepted status=QUEUED"
    assert redact(f"Bearer {CANARY}") == f"Bearer {REDACTED}"
    assert redact(f"postgresql://api:{CANARY}@h/db") == f"postgresql://api:{REDACTED}@h/db"


def test_install_puts_the_filter_on_every_root_handler() -> None:
    root = logging.getLogger()
    before = {id(h): list(h.filters) for h in root.handlers}  # pytest's capture handlers live for the session
    try:
        redaction.install()
        assert root.handlers, "basicConfig must have installed a handler"
        for handler in root.handlers:
            assert any(isinstance(f, RedactingFilter) for f in handler.filters), handler
        redaction.install()  # idempotent: one filter per handler
        for handler in root.handlers:
            assert sum(isinstance(f, RedactingFilter) for f in handler.filters) == 1
    finally:
        for handler in root.handlers:  # leave pytest's handlers as they were (other tests inspect record.args)
            handler.filters[:] = before.get(id(handler), [])
```

Run: `uv run python -m pytest tests/plan_f/test_redaction.py -q` → FAIL (no module `ops_core.redaction`).

- [ ] **Step 6: The redaction module and the entrypoints**

Create `core/src/ops_core/redaction.py`:

```python
"""Logging for every service: one `basicConfig` and a redaction filter on the handlers (T11 review note 4).

What the filter removes is every shape a credential takes on its way through this system: `Authorization: Bearer`
values, JWT-shaped strings (ID, access, refresh and logout tokens), the `code`, `state`, `session_state`,
`logout_token`, `id_token_hint`, `refresh_token`, `access_token` and `id_token` parameters of OIDC exchanges,
`password=` and `postgresql://user:password@` connection strings, `X-Ops-Invocation` handles (SA:566: never
logged), `Cookie` headers and the three session cookies' values. It sits on the handlers, not on a logger: a
filter on a parent logger never sees a child's records (spike §6). It also rewrites the formatted traceback and
clears `exc_info`, because an exception's text bypasses `msg` and uvicorn logs "Exception in ASGI application"
with the full chain (spike §6). T28 extends the same patterns to telemetry.
"""

from __future__ import annotations

import logging
import re
from typing import Final

REDACTED: Final = "[REDACTED]"
# Order matters only where patterns overlap (the Bearer rule runs before the bare-JWT rule so a redacted bearer is not
# rewritten twice); each pattern keeps the key and replaces the value.
_PATTERNS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
_SECRET_KEYS = (
    "code|state|session_state|logout_token|id_token_hint|refresh_token|access_token|id_token|client_secret"
    "|ops_session|ops_csrf|ops_login"
)
_PATTERNS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (re.compile(r"(?i)(\b(?:bearer|basic)\s+)[A-Za-z0-9._~+/=-]+"), rf"\1{REDACTED}"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*"), REDACTED),
    # key=value in a query string, a form body or a log line; `state=` also catches "run state=X", accepted on purpose.
    (re.compile(rf"(?i)((?:^|[?&;,\s'\"])(?:{_SECRET_KEYS})=)[^&\s\"'<>;]+"), rf"\1{REDACTED}"),
    # 'key': 'value' in a repr of query params, cookies, a token response or headers.
    (re.compile(rf"(?i)(['\"](?:{_SECRET_KEYS})['\"]\s*:\s*['\"])[^'\"]+"), rf"\1{REDACTED}"),
    (re.compile(r"(?i)(\bpassword=)[^\s&'\"]+"), rf"\1{REDACTED}"),
    (re.compile(r"(postgres(?:ql)?://[^:/\s@]+:)[^@\s]+@"), rf"\1{REDACTED}@"),
    (re.compile(r"(?i)((?:x-ops-invocation|x-csrf-token)['\"]?\s*[:=]\s*['\"]?)[^\s'\",;}]+"), rf"\1{REDACTED}"),
    (re.compile(r"(?i)(\bcookie['\"]?\s*:\s*)[^\r\n]+"), rf"\1{REDACTED}"),
    (re.compile(r"(\bops_(?:session|csrf|login)=)[^;\s\"'<>]+"), rf"\1{REDACTED}"),
)


def redact(text: str) -> str:
    """Return `text` with every credential-shaped value replaced by the marker; ordinary text is unchanged."""
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    """Rewrite each record's message and traceback before any handler formats it."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except (TypeError, ValueError):  # a malformed format string must not lose the line (or raise here)
            message = f"{record.msg!r} {record.args!r}"
        record.msg = redact(message)
        record.args = ()
        if record.exc_info:
            # Formatter.formatException renders the chain; the redacted text goes where the formatter looks first,
            # and exc_info is cleared so nothing re-renders the original.
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


def install(level: int = logging.INFO) -> None:
    """Configure the root logger once and put the filter on every root handler (idempotent)."""
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for handler in logging.getLogger().handlers:
        if not any(isinstance(existing, RedactingFilter) for existing in handler.filters):
            handler.addFilter(RedactingFilter())
```

Entrypoints: every `uvicorn.Config(...)` in `api/src/ops_api/__main__.py`, `worker/src/ops_worker/main.py`, `mcp-read/src/ops_mcp_read/server.py:258`, `mcp-write/src/ops_mcp_write/server.py:140` and `incident-sim/src/ops_incident_sim/__main__.py` gains `log_config=None` (uvicorn's own dictConfig would give its loggers private handlers without the filter; with `None` they propagate to the root handler, spike §6). Each entrypoint calls `redaction.install()` before building its app: the API's and incident-sim's `if __name__ == "__main__":` blocks, mcp-read's and mcp-write's `serve()`, and the worker's `_main()` where it replaces `logging.basicConfig(...)` (`import logging` stays if still used by `log`). Comment each with one line: "the redaction filter must be on the root handler before the first log line (T11 review note 4)".

Run: `uv run python -m pytest tests/plan_f/test_redaction.py -q` → PASS.

- [ ] **Step 7: Write the failing verifier-knob tests**

Create `tests/plan_f/test_tokens_knobs.py`:

```python
"""The three TokenVerifier knobs T11 adds (ruling 26): required claims, an optional `azp` check and a required
header `typ`. The ID-token and logout-token verifiers are instances built with them; every existing caller keeps the
defaults.

Catches: a logout token accepted without `jti` or `events`, a token with another `typ` header accepted where one is
required, and the default path changing (azp still required, `sub` still required).
"""

import time
from typing import Any

import jwt
import pytest
from ops_core.tokens import Principal, TokenRejected, TokenVerifier, WrongAudience

from tests.plan_d.test_tokens import ISSUER, JWK1, PEM1

AUD = "ops-web"


def mint(headers: dict[str, Any] | None = None, **over: Any) -> str:
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "sub": "2fc05986-c7ec-544c-b628-fdb112bbf18a",
        "aud": AUD,
        "exp": int(time.time()) + 120,
        "iat": int(time.time()),
    }
    claims.update(over)
    for key in [k for k, v in over.items() if v is None]:
        del claims[key]
    return jwt.encode(claims, PEM1, algorithm="RS256", headers={"kid": "k1", **(headers or {})})


def verifier(**knobs: Any) -> TokenVerifier:
    v = TokenVerifier(issuer=ISSUER, audience=AUD, allowed_azp=frozenset({AUD}), jwks_url="unused", **knobs)
    v.install_keys({"keys": [JWK1]})
    return v


def test_defaults_are_unchanged() -> None:
    with pytest.raises(WrongAudience):  # no azp at all: the default path still insists on one
        verifier().verify(mint())
    assert isinstance(verifier().verify(mint(azp=AUD)), Principal)


def test_required_claims_are_enforced() -> None:
    v = verifier(required_claims=("exp", "iss", "aud", "iat", "jti", "events"), require_azp=False)
    with pytest.raises(TokenRejected):
        v.verify(mint())  # no jti, no events
    p = v.verify(mint(jti="j1", events={"http://schemas.openid.net/event/backchannel-logout": {}}))
    assert p.azp == "" and p.claims["jti"] == "j1"


def test_header_typ_is_required_when_configured() -> None:
    v = verifier(typ="logout+jwt", require_azp=False)
    with pytest.raises(TokenRejected):
        v.verify(mint())  # typ JWT (PyJWT's default header)
    with pytest.raises(TokenRejected):
        v.verify(mint(headers={"typ": "ID"}))
    assert v.verify(mint(headers={"typ": "logout+jwt"})).subject.startswith("2fc05986")


def test_subject_is_optional_only_when_not_required() -> None:
    v = verifier(required_claims=("exp", "iss", "aud"), require_azp=False)
    assert v.verify(mint(sub=None)).subject == ""
    with pytest.raises(TokenRejected):
        verifier(require_azp=False).verify(mint(sub=None))
```

Run: `uv run python -m pytest tests/plan_f/test_tokens_knobs.py -q` → FAIL (unexpected keyword arguments).

- [ ] **Step 8: The verifier knobs**

In `core/src/ops_core/tokens.py`, `TokenVerifier.__init__` gains three keyword parameters after `algorithms`:

```python
        required_claims: tuple[str, ...] = ("exp", "iss", "aud", "sub"),
        require_azp: bool = True,
        typ: str | None = None,
```

stored as `self._required_claims = tuple(required_claims)`, `self._require_azp = require_azp`, `self._typ = typ`, with the docstring line: "`required_claims`, `require_azp` and `typ` let the same class verify ID tokens (nonce, sid, typ ID) and back-channel logout tokens (jti, events, typ logout+jwt, no azp) — ruling 26 of Plan F; the defaults are the bearer path." `verify()` becomes:

```python
    def verify(self, token: str) -> Principal:
        if self._keys is None:
            raise TokenRejected("signing keys are not loaded")
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            key = self._keys[kid] if isinstance(kid, str) else None
        except (InvalidTokenError, KeyError, PyJWKClientError, PyJWKSetError):
            header, key = {}, None
        if key is None:
            raise UnknownSigningKey("unknown signing key")
        # The header is unverified until the signature passes below, so `typ` is only compared afterwards.
        try:
            claims = jwt.decode(
                token,
                key.key,
                algorithms=self._algorithms,
                audience=self._audience,
                issuer=self._issuer,
                options={"require": list(self._required_claims)},
            )
        except InvalidAudienceError as exc:
            raise WrongAudience("token is for another audience") from exc
        except InvalidTokenError as exc:
            # PyJWT's message names the failed check (expired, audience, issuer, signature) and never the token.
            raise TokenRejected(f"token rejected: {exc.__class__.__name__}") from exc
        if self._typ is not None and header.get("typ") != self._typ:
            raise TokenRejected("token type is not accepted here")
        subject = claims.get("sub", "")
        if "sub" in self._required_claims and (not isinstance(subject, str) or not subject):
            raise TokenRejected("token has no subject")
        azp = claims.get("azp")
        if self._require_azp:
            if not isinstance(azp, str) or azp not in self._allowed_azp:
                raise WrongAudience("token was issued to a client this server does not accept")
        elif not isinstance(azp, str):
            azp = ""
        aud = claims["aud"]
        audiences = (aud,) if isinstance(aud, str) else tuple(aud)
        return Principal(
            subject=subject if isinstance(subject, str) else "",
            azp=azp,
            audiences=audiences,
            expires_at=int(claims["exp"]),
            claims=MappingProxyType(claims),
        )
```

Run: `uv run python -m pytest tests/plan_f/test_tokens_knobs.py tests/plan_d/test_tokens.py tests/plan_e/test_tokens_audience.py -q` → PASS.

- [ ] **Step 9: Gates and commit**

Add `"tests/plan_f"` to `testpaths` in `pyproject.toml` (after `tests/plan_e`). Format and lint the touched files; the character-count one-liner on every file; `PYTHONUTF8=1 uv run python scripts/check.py` → GREEN; `PYTHONUTF8=1 uv run python scripts/check.py --profile test` → GREEN (the live suite exercises the `127.0.0.1` JWKS and token URLs; `git checkout -- reports/bootstrap` afterwards).

```bash
git add api/pyproject.toml uv.lock scripts/bootstrap_dev.py compose.yaml pyproject.toml core/src/ops_core/settings.py core/src/ops_core/tokens.py core/src/ops_core/redaction.py api/src/ops_api/__main__.py worker/src/ops_worker/main.py mcp-read/src/ops_mcp_read/server.py mcp-write/src/ops_mcp_write/server.py incident-sim/src/ops_incident_sim/__main__.py tests/plan_f tests/plan_d/test_settings.py
git commit -m "feat(core): T11 settings, redaction filter and verifier knobs; authlib locked; two new secrets"
```

---

### Task 2: Revision 0005, the realm, the stale-grant rule and the live fixtures

**Files:**
- Create: `migrations/app/versions/0005_sessions_login_logout.py`, `tests/plan_f/test_grant_deferred.py`, `tests/plan_f/test_privileges_f.py`
- Modify: `core/src/ops_core/privileges.py` (`GRANTS`, `NO_RLS`, docstring), `deploy/dev/keycloak/realm-ops-dev.json` (`ops-web` attributes and `frontchannelLogout`; the `ops-test-admin` client and its service-account user), `tests/plan_b/test_realm_template.py`, `tests/plan_e/test_transitions_table.py:86` (`REVISIONS`), `mcp-write/src/ops_mcp_write/server.py` (`tool_error` retryable, `refusal_code`), `worker/src/ops_worker/handlers.py` (`is_deferred`, `_requeue`), `tests/e2e/conftest.py` (`fresh_memberships`), `tests/e2e/test_definers_write_path_live.py` (stale grant), `tests/e2e/test_migrations_and_persistence.py:192-210` (downgrade through 0005), `docs/runbooks/dev-topology.md` (realm table rows)

**Interfaces:**
- Consumes: `privileges.Grant`, `grant_statements(tables, cells, revokees=)`, `function_grant_statements(name, args=, callers=)`; the 0004 `grant_execution` body (copied verbatim, then extended).
- Produces: tables `app.login_state(login_sha256, state_sha256, nonce_sha256, code_verifier, created_at, expires_at)`, `app.logout_jti(jti, received_at, expires_at)`; `app.sessions` columns `sid text NOT NULL`, `username text NOT NULL DEFAULT ''`, `refresh_token_enc bytea NOT NULL`; `grant_execution` refusal `MEMBERSHIP_STALE`; mcp-write tool error `GRANT_DEFERRED` (`retryable: true`); `ops_worker.handlers.is_deferred(doc) -> bool`; the `fresh_memberships` autouse fixture; realm client `ops-test-admin`.

- [ ] **Step 1: The matrix rows and their unit test**

Create `tests/plan_f/test_privileges_f.py`:

```python
"""The three AM-20.2 rows Plan F adds or changes (rulings 2, 3, 17; erratum 25): the sweeper can SELECT what it
deletes on `sessions`, the pre-login state and the logout jti store exist as RLS-free tables with the narrowest cells
that work (spike §5: an insert-only role can run a target-less ON CONFLICT DO NOTHING and nothing else)."""

from ops_core import privileges as p


def test_session_tables_are_rls_free_and_narrow() -> None:
    for table in ("sessions", "login_state", "logout_jti"):
        assert table in p.NO_RLS and table not in p.RLS_TABLES
        assert set(p.GRANTS[table]) == {"api", "sweeper"}  # no definer, no worker, no function-only role
        assert p.GRANTS[table]["sweeper"] == p.Grant(sel=True, dele=True)
    assert p.GRANTS["sessions"]["api"] == p.Grant(sel=True, ins=True, upd=("last_seen_at", "revoked_at"), dele=True)
    assert p.GRANTS["login_state"]["api"] == p.Grant(sel=True, ins=True, dele=True)
    assert p.GRANTS["logout_jti"]["api"] == p.Grant(ins=True)  # replay is detected by rowcount, never by a read
```

In `core/src/ops_core/privileges.py`: `"sessions"` becomes

```python
    "sessions": {
        "api": Grant(sel=True, ins=True, upd=("last_seen_at", "revoked_at"), dele=True),
        "sweeper": Grant(sel=True, dele=True),  # erratum 25: a DELETE with a WHERE needs SELECT (spike §4)
    },
    # T11 (Plan F rulings 2 and 17): the pre-login OIDC state and the back-channel logout replay store, both
    # tenant-less; the api role inserts jti rows blind (a target-less ON CONFLICT DO NOTHING, rowcount as verdict).
    "login_state": {"api": Grant(sel=True, ins=True, dele=True), "sweeper": Grant(sel=True, dele=True)},
    "logout_jti": {"api": _INS, "sweeper": Grant(sel=True, dele=True)},
```

`NO_RLS` gains `"login_state", "logout_jti"`. The module docstring's "Four departures" sentence becomes "Six departures … and (Plan F) the sweeper holds SELECT with its DELETE on `sessions`, `login_state` and `logout_jti` (erratum 25), and `login_state`/`logout_jti` are new rows". Run `uv run python -m pytest tests/plan_f/test_privileges_f.py tests/plan_e/test_privileges.py -q` → PASS; `tests/plan_e/test_transitions_table.py::test_the_newest_revision_of_every_cell_equals_the_live_matrix` → FAIL until Step 3 (expected).

- [ ] **Step 2: Write the failing live tests**

In `tests/e2e/test_migrations_and_persistence.py::test_r006_fresh_database_upgrades_downgrades_and_upgrades_again`, the relation list becomes `("app.test_clock", "app.run_directory", "app.transitions", "app.login_state", "app.logout_jti")` and, before the first downgrade, add a downgrade to 0004 with its own assertions (at `0001_walking_skeleton` the `sessions` table itself is gone, so an "absent columns" check there proves nothing):

```python
    async def session_columns() -> set[str]:
        cur = await app_conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'app' AND table_name = 'sessions'"
        )
        return {str(r["column_name"]) for r in await cur.fetchall()}

    assert {"sid", "username", "refresh_token_enc"} <= await session_columns()
    downgrade("app", superuser, "0004_write_path_functions")
    assert not {"sid", "username", "refresh_token_enc"} & await session_columns()
    cur = await app_conn.execute("SELECT has_table_privilege('sweeper', 'app.sessions', 'SELECT') AS sel")
    assert not (await cur.fetchone())["sel"]  # 0002's DELETE-only cell is back
    cur = await app_conn.execute("SELECT pg_get_functiondef('app.grant_execution(text, uuid)'::regprocedure) AS body")
    assert "MEMBERSHIP_STALE" not in (await cur.fetchone())["body"]
```

(the `testclock@base` downgrade stays first, as today, since the branch depends on the main head).

Append to `tests/e2e/test_definers_write_path_live.py`:

```python
async def test_grant_execution_refuses_a_stale_sync(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    """T11 review note 2: a grant whose requester or reviewer was last synced more than 120 s ago is refused with
    MEMBERSHIP_STALE (fail closed when the sweeper is gone); fresh rows grant as before."""
    from tests.e2e.test_mcp_write_live import approved_run

    api, worker, mcp_exec = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.MCP_EXEC)
    tenant, run, proposal, handle = await approved_run(app_conn, api=api, worker=worker)
    try:
        await app_conn.execute(
            "UPDATE app.memberships SET synced_at = app.current_time() - interval '121 seconds' WHERE tenant_id = %s",
            (tenant,),
        )
        with pytest.raises(persistence.Refused) as refusal:
            async with mcp_exec.transaction():
                await persistence.grant_execution(mcp_exec, handle=handle, proposal_id=proposal)
        assert refusal.value.code == "MEMBERSHIP_STALE"
        cur = await app_conn.execute("SELECT count(*) AS n FROM app.execution_grant WHERE run_id = %s", (run,))
        assert (await cur.fetchone())["n"] == 0  # nothing was granted
        await app_conn.execute(
            "UPDATE app.memberships SET synced_at = app.current_time() WHERE tenant_id = %s", (tenant,)
        )
        async with mcp_exec.transaction():
            grant = await persistence.grant_execution(mcp_exec, handle=handle, proposal_id=proposal)
        assert grant.run_id == run
    finally:
        await purge_run(app_conn, run)
```

In `tests/e2e/conftest.py` add, after `incident_conn`:

```python
@pytest_asyncio.fixture(autouse=True)
async def fresh_memberships(migrated: None) -> None:
    """T11's 120 s rule (grant_execution refuses MEMBERSHIP_STALE): the seeded rows carry the migration instant as
    `synced_at`, and the sweeper that keeps it fresh runs only inside the R105 skeleton, so every live test starts
    with the rows stamped now. Tests of the rule itself age the rows afterwards."""
    conn = await persistence.connect(settings.superuser_postgres())
    try:
        await conn.execute("UPDATE app.memberships SET synced_at = app.current_time()")
    finally:
        await conn.close()
```

Run: `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_definers_write_path_live.py -q -k stale` → FAIL (the grant succeeds: no staleness rule yet).

- [ ] **Step 3: Revision 0005**

Create `migrations/app/versions/0005_sessions_login_logout.py`:

```python
"""Sessions, pre-login state, the logout jti store and the stale-sync rule (T11, Plan F rulings 2, 3, 14, 17).

Revision ID: 0005_sessions_login_logout
Revises: 0004_write_path_functions

`sessions` (BUILD_SPEC §6 shape from 0002) gains the Keycloak session id the back-channel logout revokes by, the
username `/api/v1/me` shows, and the Fernet-sealed refresh token the server-side logout spends; it is truncated first
(empty in every database today; a migration that ends every browser session is acceptable). `login_state` holds the
authorization request's state, nonce and PKCE verifier under the login cookie's hash (SA:565: authlib's state lives
in the store, never in a signed cookie). `logout_jti` is the durable replay store (T11 review note 3). The sweeper
gets SELECT beside its DELETE on all three (erratum 25: a DELETE with a WHERE needs SELECT, spike §4).
`grant_execution` is re-created with one more refusal, MEMBERSHIP_STALE, when a requester's or reviewer's row was not
stamped by the sync within 120 s (T11 review note 2, fail closed). Every cell and caller is frozen here (round-3
finding N1 of Plan E).
"""

from alembic import op
from ops_core import privileges

revision = "0005_sessions_login_logout"
down_revision = "0004_write_path_functions"
branch_labels = None
depends_on = None

HEADER = "LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp SET app.tenant_id = ''"
GRANT_COLUMNS = (
    "action_id uuid, run_id uuid, proposal_id uuid, tenant_id uuid, conversation_id uuid, payload_sha256 text,"
    " payload_canonical bytea, attempt_state text, detail jsonb"
)
TABLES = ("sessions", "login_state", "logout_jti")
MAIN_GRANTEES_0005 = ("api", "worker", "sweeper", "mcp_read", "mcp_exec", "operator", "app_definer")
GRANTS_0005: dict[str, dict[str, privileges.Grant]] = {
    "sessions": {
        "api": privileges.Grant(sel=True, ins=True, upd=("last_seen_at", "revoked_at"), dele=True),
        "sweeper": privileges.Grant(sel=True, dele=True),
    },
    "login_state": {
        "api": privileges.Grant(sel=True, ins=True, dele=True),
        "sweeper": privileges.Grant(sel=True, dele=True),
    },
    "logout_jti": {"api": privileges.Grant(ins=True), "sweeper": privileges.Grant(sel=True, dele=True)},
}
# What 0002 granted on sessions, for the downgrade (not named GRANTS_*: the newest-revision test folds every
# GRANTS_* attribute into the live matrix check).
SESSIONS_CELLS_0002: dict[str, dict[str, privileges.Grant]] = {
    "sessions": {
        "api": privileges.Grant(sel=True, ins=True, upd=("last_seen_at", "revoked_at"), dele=True),
        "sweeper": privileges.Grant(dele=True),
    }
}

SCHEMA_CHANGES = (
    "TRUNCATE app.sessions",
    (
        "ALTER TABLE app.sessions ADD COLUMN sid text NOT NULL,"
        " ADD COLUMN username text NOT NULL DEFAULT '',"
        " ADD COLUMN refresh_token_enc bytea NOT NULL"
    ),
    "CREATE INDEX sessions_sid_idx ON app.sessions (sid)",
    "CREATE INDEX sessions_identity_idx ON app.sessions (issuer, subject)",
    (
        "CREATE TABLE app.login_state ("
        " login_sha256 text PRIMARY KEY,"
        " state_sha256 text NOT NULL UNIQUE,"
        " nonce_sha256 text NOT NULL,"
        " code_verifier text NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " expires_at timestamptz NOT NULL)"
    ),
    (
        "CREATE TABLE app.logout_jti ("
        " jti text PRIMARY KEY,"
        " received_at timestamptz NOT NULL DEFAULT now(),"
        " expires_at timestamptz NOT NULL)"
    ),
    "ALTER TABLE app.login_state OWNER TO migrator",
    "ALTER TABLE app.logout_jti OWNER TO migrator",
)

# grant_execution as 0004 installed it, with the stale-sync rule inserted after MEMBERSHIP_INACTIVE (ruling 14).
GRANT_EXECUTION = f"""
CREATE OR REPLACE FUNCTION app.grant_execution(p_raw_handle text, p_proposal_id uuid)
RETURNS TABLE ({GRANT_COLUMNS})
{HEADER} AS $fn$
DECLARE
    v_handle record;
    v_run runs%ROWTYPE;
    v_proposal proposals%ROWTYPE;
    v_grant execution_grant%ROWTYPE;
    v_action_id uuid;
BEGIN
    PERFORM app._authority('grant_execution', ARRAY['mcp_exec']);
    IF p_proposal_id IS NULL THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'INVALID_ARGUMENT';
    END IF;
    SELECT * INTO v_handle FROM app._resolve_handle(p_raw_handle, 'ops-worker', 'write');
    SELECT * INTO v_run FROM runs r WHERE r.run_id = v_handle.run_id FOR UPDATE;
    SELECT * INTO v_grant FROM execution_grant g WHERE g.run_id = v_handle.run_id;
    IF FOUND THEN
        -- UNIQUE (run_id): one grant per run, ever (SA:167); a replay finds the grant it already has.
        IF v_grant.proposal_id IS DISTINCT FROM p_proposal_id THEN
            RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'OTHER_PROPOSAL';
        END IF;
        RETURN QUERY SELECT * FROM app._grant_row(v_grant.action_id);
        RETURN;
    END IF;
    SELECT * INTO v_proposal FROM proposals p WHERE p.proposal_id = p_proposal_id AND p.run_id = v_handle.run_id
                                                AND p.tenant_id = v_handle.tenant_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'PROPOSAL_NOT_IN_RUN';
    END IF;
    IF v_run.state <> 'APPROVED' OR v_run.active_proposal_id IS DISTINCT FROM p_proposal_id THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'NOT_ACTIVE_APPROVED';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM decisions d WHERE d.proposal_id = p_proposal_id AND d.decision = 'approve') THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'NO_APPROVAL';
    END IF;
    IF v_run.cancel_requested THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'CANCELLED';
    END IF;
    -- The §13 gate re-reads current membership (BS:472): requester and reviewer must still be active members.
    IF NOT EXISTS (SELECT 1 FROM memberships m WHERE m.tenant_id = v_handle.tenant_id
                                                     AND m.subject = v_run.requester AND m.active)
       OR NOT EXISTS (SELECT 1 FROM decisions d JOIN memberships m ON m.tenant_id = v_handle.tenant_id
                                                                      AND m.subject = d.reviewer
                      AND m.role = 'reviewer' AND m.active WHERE d.proposal_id = p_proposal_id) THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'MEMBERSHIP_INACTIVE';
    END IF;
    -- T11 review note 2: active is only as good as the last sync; without one in 120 s the gate fails closed.
    IF NOT EXISTS (SELECT 1 FROM memberships m WHERE m.tenant_id = v_handle.tenant_id
                                                     AND m.subject = v_run.requester AND m.active
                                                     AND m.synced_at >= app.current_time() - interval '120 seconds')
       OR NOT EXISTS (SELECT 1 FROM decisions d JOIN memberships m ON m.tenant_id = v_handle.tenant_id
                                                                      AND m.subject = d.reviewer
                      AND m.role = 'reviewer' AND m.active
                      AND m.synced_at >= app.current_time() - interval '120 seconds'
                      WHERE d.proposal_id = p_proposal_id) THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'MEMBERSHIP_STALE';
    END IF;
    -- TODO(T21): asset freshness (5 min) and the asset guard; TODO(T13): the lease fence.
    v_action_id := gen_random_uuid();  -- random inside the gate (SA:168), never derived from the proposal
    INSERT INTO execution_grant (action_id, tenant_id, run_id, proposal_id, payload_sha256, granted_at)
    VALUES (v_action_id, v_handle.tenant_id, v_handle.run_id, p_proposal_id, v_proposal.payload_sha256,
            app.current_time());
    INSERT INTO action_attempt (tenant_id, action_id, attempt_no, created_at)
    VALUES (v_handle.tenant_id, v_action_id, 1, app.current_time());
    INSERT INTO action_attempt_state (tenant_id, action_id, attempt_no, seq, state, at)
    VALUES (v_handle.tenant_id, v_action_id, 1, 1, 'INTENT', app.current_time());
    PERFORM app._transition(v_handle.run_id, 'EXECUTING', 'grant_execution', NULL, NULL, 'action.granted',
                            jsonb_build_object('action_id', v_action_id, 'proposal_id', p_proposal_id));
    RETURN QUERY SELECT * FROM app._grant_row(v_action_id);
END
$fn$;
ALTER FUNCTION app.grant_execution(text, uuid) OWNER TO app_definer;
"""

# The 0004 body, frozen here so the downgrade restores exactly what 0004 installed (the two bodies differ by the
# MEMBERSHIP_STALE block only; a unit test asserts that).
GRANT_EXECUTION_0004 = GRANT_EXECUTION.replace(
    """    -- T11 review note 2: active is only as good as the last sync; without one in 120 s the gate fails closed.
    IF NOT EXISTS (SELECT 1 FROM memberships m WHERE m.tenant_id = v_handle.tenant_id
                                                     AND m.subject = v_run.requester AND m.active
                                                     AND m.synced_at >= app.current_time() - interval '120 seconds')
       OR NOT EXISTS (SELECT 1 FROM decisions d JOIN memberships m ON m.tenant_id = v_handle.tenant_id
                                                                      AND m.subject = d.reviewer
                      AND m.role = 'reviewer' AND m.active
                      AND m.synced_at >= app.current_time() - interval '120 seconds'
                      WHERE d.proposal_id = p_proposal_id) THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'MEMBERSHIP_STALE';
    END IF;
""",
    "",
)
assert GRANT_EXECUTION_0004 != GRANT_EXECUTION  # the replace must have matched

# (name, argument types, callers, body): frozen here (N1); the newest-revision test reads this tuple.
FUNCTIONS = (("grant_execution", "text, uuid", ("mcp_exec",), GRANT_EXECUTION),)

DOWNGRADE = (
    f"REVOKE ALL ON app.login_state, app.logout_jti FROM {', '.join(MAIN_GRANTEES_0005)}",
    "DROP TABLE app.logout_jti",
    "DROP TABLE app.login_state",
    "DROP INDEX app.sessions_identity_idx",
    "DROP INDEX app.sessions_sid_idx",
    "TRUNCATE app.sessions",
    "ALTER TABLE app.sessions DROP COLUMN refresh_token_enc, DROP COLUMN username, DROP COLUMN sid",
)


def upgrade() -> None:
    """Schema first, then the frozen grants, then the re-created gate with its grants (REVOKE lands on the new body)."""
    for statement in SCHEMA_CHANGES:
        op.execute(statement)
    for statement in privileges.grant_statements(TABLES, GRANTS_0005, revokees=MAIN_GRANTEES_0005):
        op.execute(statement)
    for name, args, callers, body in FUNCTIONS:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)


def downgrade() -> None:
    """Restore 0004's gate and 0002's sessions, drop the two tables."""
    op.execute(GRANT_EXECUTION_0004)
    for statement in privileges.function_grant_statements("grant_execution", args="text, uuid", callers=("mcp_exec",)):
        op.execute(statement)
    for statement in DOWNGRADE:
        op.execute(statement)
    for statement in privileges.grant_statements(("sessions",), SESSIONS_CELLS_0002, revokees=MAIN_GRANTEES_0005):
        op.execute(statement)
```

`tests/plan_e/test_transitions_table.py:86`: `REVISIONS = ("0002_roles_grants_rls", "0003_run_path_functions", "0004_write_path_functions", "0005_sessions_login_logout", "tc_0001_test_clock")`. Add to `tests/plan_f/test_privileges_f.py`:

```python
def test_revision_0005_bodies_differ_only_by_the_stale_rule() -> None:
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "migrations" / "app" / "versions" / "0005_sessions_login_logout.py"
    spec = importlib.util.spec_from_file_location("rev0005", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert "MEMBERSHIP_STALE" in module.GRANT_EXECUTION and "MEMBERSHIP_STALE" not in module.GRANT_EXECUTION_0004
    assert module.GRANT_EXECUTION.count("interval '120 seconds'") == 2
    assert module.GRANTS_0005 == {t: p.GRANTS[t] for t in module.TABLES}
``` Run `uv run ruff check --select ISC004 --fix --unsafe-fixes migrations/app/versions/0005_sessions_login_logout.py`, then `uv run python -m pytest tests/plan_e/test_transitions_table.py tests/plan_f -q` → PASS (bind scan, newest-revision cells and callers, the 0005 shape).

- [ ] **Step 4: Migrate the test databases and run the live schema tests**

`OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_roles_live.py tests/e2e/test_migrations_and_persistence.py tests/e2e/test_definers_write_path_live.py -q` → PASS (R124 enumerates the new cells, R006 goes down through 0005 and back up, R106 sees the two new tables without RLS, the stale grant is refused then granted). Do **not** migrate the dev database in this task (Task 7 records that as an owner step, like Plan E's).

- [ ] **Step 5: The realm export, its tests, and the re-import**

`deploy/dev/keycloak/realm-ops-dev.json`: at the realm level, after `"accessTokenLifespan": 300,` add `"ssoSessionIdleTimeout": 28800,` and `"ssoSessionMaxLifespan": 28800,` (the Keycloak session must outlive the application session, whose idle timer resets on every request while Keycloak's does not; with the 30-minute default a user active for an hour has no provider session left to end at logout and no back-channel logout can reach the API, round-1 finding I2; the application's own 30-minute idle and 8-hour absolute limits stay the stricter ones). Client `ops-web`: add `"frontchannelLogout": false,` after `"serviceAccountsEnabled": false,` and make `attributes`

```json
      "attributes": {
        "pkce.code.challenge.method": "S256",
        "post.logout.redirect.uris": "http://localhost:8000/",
        "backchannel.logout.url": "http://host.docker.internal:8000/auth/backchannel-logout",
        "backchannel.logout.session.required": "true",
        "backchannel.logout.revoke.offline.tokens": "false"
      }
```

After the `ops-view-users` client add:

```json
    {
      "clientId": "ops-test-admin",
      "name": "Live-test admin (dev/test only)",
      "description": "dev/test-only: lets the live suite disable, re-enable and log out a persona (R086); never deployed outside the dev profile",
      "enabled": true,
      "publicClient": false,
      "secret": "${OPS_KC_CLIENT_SECRET_OPS_TEST_ADMIN}",
      "standardFlowEnabled": false,
      "implicitFlowEnabled": false,
      "directAccessGrantsEnabled": false,
      "serviceAccountsEnabled": true
    }
```

and after the `service-account-ops-view-users` user:

```json
    {
      "username": "service-account-ops-test-admin",
      "enabled": true,
      "serviceAccountClientId": "ops-test-admin",
      "clientRoles": {"realm-management": ["manage-users", "view-users"]}
    }
```

`tests/plan_b/test_realm_template.py`: `test_browser_client_uses_code_flow_with_pkce` gains

```python
    # T11: Keycloak posts the logout token to the host API through the Docker host alias (spike §2); session-scoped
    # tokens carry `sid`, which is what the endpoint revokes by; no front-channel iframe.
    assert web["frontchannelLogout"] is False
    assert web["attributes"]["backchannel.logout.url"] == "http://host.docker.internal:8000/auth/backchannel-logout"
    assert web["attributes"]["backchannel.logout.session.required"] == "true"
    assert web["attributes"]["backchannel.logout.revoke.offline.tokens"] == "false"
```

`test_realm_name_and_roles` gains `assert doc["ssoSessionIdleTimeout"] == 28800 and doc["ssoSessionMaxLifespan"] == 28800` with the comment "the provider session outlives the 8 h application session (Plan F ruling 3)". And a new test:

```python
def test_test_admin_service_account_is_dev_only_and_manages_users_only():
    # The live suite's only way to disable a persona (R086) without a realm admin; the description is the warning.
    c = clients()["ops-test-admin"]
    assert c["serviceAccountsEnabled"] is True and c["publicClient"] is False
    assert c["standardFlowEnabled"] is False and c["directAccessGrantsEnabled"] is False
    assert "dev/test-only" in c["description"]
    sa = users()["service-account-ops-test-admin"]
    assert sa["serviceAccountClientId"] == "ops-test-admin"
    assert sa["clientRoles"] == {"realm-management": ["manage-users", "view-users"]}
    assert "realmRoles" not in sa or sa["realmRoles"] == []
    assert audiences(c) == set()
```

`uv run python -m pytest tests/plan_b -q` → PASS. Then re-import the realm (keeps the PostgreSQL volume): `uv run python scripts/bootstrap_dev.py down` and `uv run python scripts/bootstrap_dev.py up`; then `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/plan_b/live -q` → PASS (`test_service_account.py` still proves `ops-view-users` cannot write). Prove the new client with a throw-away one-off (never committed, no value printed): a client-credentials token for `ops-test-admin` can `GET /admin/realms/ops-dev/users/{lee}` (200), `PUT` the same user with `{"enabled": false}` (204), `GET` it again (`enabled` false, and `username`, `email`, `firstName`, `lastName` unchanged: a partial PUT keeps the other fields), then `PUT {"enabled": true}` and `GET` (`enabled` true). Record the status codes and the field comparison in the report; `lee` is a reader and no other test depends on it, and the probe ends with `lee` enabled. `git checkout -- reports/bootstrap`.

- [ ] **Step 6: `GRANT_DEFERRED` in mcp-write and the worker's re-queue**

Create `tests/plan_f/test_grant_deferred.py`:

```python
"""A stale sync defers execution instead of failing it (ruling 14): mcp-write maps MEMBERSHIP_STALE to the
retryable tool error GRANT_DEFERRED and the worker re-queues such an envelope the way it re-queues a transport
failure; every other refusal stays GRANT_REFUSED and final."""

from ops_mcp_write.server import refusal_error
from ops_worker.handlers import is_deferred


def test_stale_membership_is_the_one_deferred_refusal() -> None:
    deferred = refusal_error("MEMBERSHIP_STALE")
    assert deferred == {"code": "GRANT_DEFERRED", "message": "grant deferred: MEMBERSHIP_STALE", "retryable": True}
    for code in ("MEMBERSHIP_INACTIVE", "NO_APPROVAL", "CANCELLED", "OTHER_PROPOSAL"):
        refused = refusal_error(code)
        assert refused["code"] == "GRANT_REFUSED" and refused["retryable"] is False and code in refused["message"]


def test_worker_recognises_a_deferred_envelope_only() -> None:
    assert is_deferred({"status": "error", "error": {"code": "GRANT_DEFERRED", "retryable": True}})
    assert not is_deferred({"status": "error", "error": {"code": "GRANT_REFUSED", "retryable": False}})
    assert not is_deferred({"status": "ok", "data": {"status": "SUCCEEDED"}})
    assert not is_deferred({"status": "outcome", "data": {"status": "UNKNOWN"}, "error": None})
```

`mcp-write/src/ops_mcp_write/server.py`: `tool_error` gains `retryable: bool = False` (`{"code": code, "message": message, "retryable": retryable}`; docstring "retryable only for GRANT_DEFERRED (T11)") and a module-level function placed after it:

```python
def refusal_error(code: str) -> dict[str, Any]:
    """The tool error for a grant refusal: MEMBERSHIP_STALE is the one the worker retries (Plan F ruling 14)."""
    if code == "MEMBERSHIP_STALE":
        return tool_error("GRANT_DEFERRED", f"grant deferred: {code}", retryable=True)
    return tool_error("GRANT_REFUSED", f"grant refused: {code}")
```

and the `except persistence.Refused as exc:` branch in `create_incident` becomes `return envelope("create_incident", error=refusal_error(exc.code))`.

`worker/src/ops_worker/handlers.py`: add after `EXECUTE_RETRY_SECONDS`:

```python
def is_deferred(doc: dict[str, Any]) -> bool:
    """An `error` envelope whose code is GRANT_DEFERRED: the gate found the membership sync stale (T11), so the job
    is retried rather than closed."""
    error = doc.get("error") or {}
    return doc.get("status") == "error" and error.get("code") == "GRANT_DEFERRED"
```

In `execute`, move the re-queue block into a helper and call it from both places:

```python
async def _requeue(deps: Deps, job: dict[str, Any], run_id: UUID) -> None:
    """Release the job for a later attempt; the handle may already have reached mcp-write, so it is revoked first."""
    async with deps.conn.transaction():
        await persistence.set_tenant(deps.conn, job["tenant_id"])  # RLS: without it the UPDATE touches no row
        await persistence.revoke_handles(deps.conn, run_id)
        await persistence.requeue_job(deps.conn, job["id"], EXECUTE_RETRY_SECONDS)
```

(the `except McpCallFailed` branch keeps its comment and calls `await _requeue(deps, job, run["run_id"])`), and after `data = doc.get("data") or {}`:

```python
    if is_deferred(doc):
        log.warning("execute job %s: grant deferred (stale membership sync); re-queued in %s s", job["id"],
                    EXECUTE_RETRY_SECONDS)
        await _requeue(deps, job, run["run_id"])
        return False
```

Run: `uv run python -m pytest tests/plan_f/test_grant_deferred.py tests/plan_d/test_worker.py tests/plan_d/test_mcp_write.py -q` → PASS.

- [ ] **Step 7: Gates and commit**

`docs/runbooks/dev-topology.md`: the realm table gains the `ops-test-admin` row ("service account, `manage-users` + `view-users`, **dev/test-only**, the live suite's persona switch") and the `ops-web` row notes the back-channel URL. Format, lint, the character count, `PYTHONUTF8=1 uv run python scripts/check.py` → GREEN; `--profile test`: everything green except `tests/e2e/test_r105_walking_skeleton.py` (declared red until Task 5: the skeleton has no sweeper yet and the seeded rows age past 120 s during the run); `git checkout -- reports/bootstrap reports/skeleton`.

```bash
git add migrations/app/versions/0005_sessions_login_logout.py core/src/ops_core/privileges.py deploy/dev/keycloak/realm-ops-dev.json tests/plan_b/test_realm_template.py tests/plan_e/test_transitions_table.py tests/plan_f mcp-write/src/ops_mcp_write/server.py worker/src/ops_worker/handlers.py tests/e2e/conftest.py tests/e2e/test_definers_write_path_live.py tests/e2e/test_migrations_and_persistence.py docs/runbooks/dev-topology.md
git commit -m "feat(db): revision 0005 — sessions columns, login_state, logout_jti, stale-sync rule; realm back-channel logout and test admin (T11)"
```

---
### Task 3: The admin-API client, the auth helpers and the session store

**Files:**
- Create: `core/src/ops_core/keycloak_admin.py`, `api/src/ops_api/auth.py`, `tests/plan_f/test_admin_users.py`, `tests/plan_f/test_auth_helpers.py`, `tests/plan_f/test_id_and_logout_tokens.py`
- Modify: `api/src/ops_api/store.py` (`LoginState`, `SessionRow`, seven `Store` methods, their `DbStore` SQL)

**Interfaces:**
- Consumes: `TokenVerifier(required_claims=, require_azp=, typ=)`, `WorkloadTokenSource(post=)` plus its new `invalidate()` (added in this task: `self._token = None` so the next `token()` fetches; one line with a docstring), `settings.Keycloak`, `settings.SessionSettings`, `ops_core.canonical.sha256_hex`.
- Produces (`ops_core.keycloak_admin`): `AdminUnavailable(Exception)`; `AdminUsers(users_url=, tokens=, client=, timeout=)` with `async enabled(subject: UUID) -> bool`, `async list_enabled() -> dict[UUID, bool]`, `async aclose()`; `admin_users(keycloak=, client_secret=, timeout=) -> AdminUsers` (the shared keep-alive client and token source).
- Produces (`ops_api.auth`): constants `SESSION_COOKIE = "ops_session"`, `CSRF_COOKIE = "ops_csrf"`, `LOGIN_COOKIE = "ops_login"`, `CSRF_HEADER = "X-CSRF-Token"`, `BACKCHANNEL_EVENT`; `digest(value) -> str`, `new_token() -> str`, `matches(value, expected_sha256) -> bool`, `origin_of(url) -> str | None`, `same_origin(headers, origin) -> bool`; `Discovery` (+ `from_document(doc, keycloak)`), `async fetch_discovery(keycloak, client) -> Discovery`; `Tokens(id_token, refresh_token)`; `ExchangeRefused`, `ExchangeUnavailable`; `OidcClient` protocol (`authorization_url(*, state, nonce, code_verifier) -> str`, `async exchange(*, code, code_verifier) -> Tokens`, `async end_session(refresh_token) -> None`) and `AuthlibOidc`; `IdClaims(subject: UUID, sid, username)`, `IdTokens` protocol (`ready`, `async load_keys()`, `async verify(id_token, *, nonce_sha256) -> IdClaims`) and `IdTokenVerifier`; `LogoutClaims(sid, subject: UUID, jti, expires_at: int)`, `LogoutTokens` protocol and `LogoutTokenVerifier`; `EnabledCheck` protocol (`async enabled(subject) -> bool`); `TokenBox(key_material)` with `seal(str) -> bytes`, `open(bytes) -> str`; `CookiePolicy(secure, login_max_age)` with `set_session(response, session, csrf)`, `set_login(response, login)`, `clear_session(response)`, `clear_login(response)`.
- Produces (`ops_api.store`): `LoginState(state_sha256, nonce_sha256, code_verifier)`, `SessionRow(session_sha256, issuer, subject, tenant_id, sid, username, csrf_secret_sha256, refresh_token_enc)`; `Store.begin_login(*, login_sha256, state_sha256, nonce_sha256, code_verifier, ttl_seconds)`, `take_login(login_sha256) -> LoginState | None` (one shot), `create_session(*, session_sha256, issuer, subject, tenant_id, sid, username, csrf_secret_sha256, refresh_token_enc, absolute_seconds)`, `live_session(session_sha256, *, idle_seconds) -> SessionRow | None` (touches `last_seen_at`; the name avoids `DbStore.session`, the `persistence.Session` attribute every method uses), `revoke_session(session_sha256) -> SessionRow | None`, `record_logout(jti, *, expires_at, sid) -> int | None` (None on replay, else sessions revoked, one transaction).

- [ ] **Step 1: Write the failing admin-client test**

Create `tests/plan_f/test_admin_users.py`:

```python
"""The fail-closed enabled check (SA:542-546, T11 review note 1) against a fake admin API served in-process: the
answer is the `enabled` flag, a 404 is a deleted user, and everything else (timeout, refusal, a 5xx, an unusable
body, a token endpoint that fails, an empty realm listing) is AdminUnavailable within the budget.

Catches: a slow Keycloak that blocks a decision past 2 s, a 403 from a misconfigured role read as "enabled", a
listing that returns nothing and would deactivate every membership, and a token refresh that is not single-flight.
"""

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
import pytest_asyncio
from ops_core.keycloak_admin import AdminUnavailable, AdminUsers
from ops_core.tokens import WorkloadTokenSource
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

ALEX = UUID("2fc05986-c7ec-544c-b628-fdb112bbf18a")
SAM = UUID("03f7eb09-e18d-5f33-bf75-12c57d5aaa54")


class FakeKeycloak:
    """Just enough of the admin API: a token endpoint and the two user reads, with knobs for each failure."""

    def __init__(self) -> None:
        self.users: dict[UUID, bool] = {ALEX: True, SAM: False}
        self.status: int | None = None  # force this status on every user read
        self.delay = 0.0
        self.token_calls = 0
        self.token_status = 200
        self.body: Any = None  # force this body on the single-user read

    async def token(self, request: Request) -> Response:
        self.token_calls += 1
        if self.token_status != 200:
            return JSONResponse({"error": "invalid_client"}, status_code=self.token_status)
        return JSONResponse({"access_token": f"t{self.token_calls}", "expires_in": 300})

    async def user(self, request: Request) -> Response:
        await asyncio.sleep(self.delay)
        if request.headers.get("authorization", "") != f"Bearer t{self.token_calls}":
            return JSONResponse({"error": "HTTP 401 Unauthorized"}, status_code=401)
        if self.status is not None:
            return JSONResponse({"error": "forced"}, status_code=self.status)
        if self.body is not None:
            return Response(json.dumps(self.body), media_type="application/json")
        try:
            uid = UUID(request.path_params["uid"])
        except ValueError:
            return JSONResponse({"error": "User not found"}, status_code=404)
        if uid not in self.users:
            return JSONResponse({"error": "User not found"}, status_code=404)
        return JSONResponse({"id": str(uid), "username": "x", "enabled": self.users[uid]})

    async def listing(self, request: Request) -> Response:
        await asyncio.sleep(self.delay)
        if self.status is not None:
            return JSONResponse({"error": "forced"}, status_code=self.status)
        first, size = int(request.query_params["first"]), int(request.query_params["max"])
        rows = [{"id": str(u), "enabled": e} for u, e in sorted(self.users.items(), key=lambda kv: str(kv[0]))]
        return JSONResponse(rows[first : first + size])

    def app(self) -> Starlette:
        return Starlette(
            routes=[
                Route("/token", self.token, methods=["POST"]),
                Route("/admin/users", self.listing),
                Route("/admin/users/{uid}", self.user),
            ]
        )


@pytest_asyncio.fixture
async def admin() -> AsyncIterator[tuple[AdminUsers, FakeKeycloak]]:
    fake = FakeKeycloak()
    client = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=fake.app()), base_url="http://kc.test")

    async def post(url: str, form: dict[str, str]) -> dict[str, Any]:
        response = await client.post(url, data=form)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data

    tokens = WorkloadTokenSource(token_url="http://kc.test/token", client_id="ops-view-users", client_secret="s", post=post)
    users = AdminUsers(users_url="http://kc.test/admin/users", tokens=tokens, client=client, timeout=0.3)
    try:
        yield users, fake
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_enabled_disabled_and_deleted(admin: tuple[AdminUsers, FakeKeycloak]) -> None:
    users, fake = admin
    assert await users.enabled(ALEX) is True
    assert await users.enabled(SAM) is False
    assert await users.enabled(uuid4()) is False  # 404: deleted maps to "not enabled" (T11 review note 2)
    assert fake.token_calls == 1  # one cached service-account token for the three reads


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 500, 503])
async def test_any_other_status_is_unavailable(admin: tuple[AdminUsers, FakeKeycloak], status: int) -> None:
    users, fake = admin
    fake.status = status
    with pytest.raises(AdminUnavailable):
        await users.enabled(ALEX)
    if status == 401:
        assert fake.token_calls == 2  # one fresh token and one retry, then fail closed


@pytest.mark.asyncio
async def test_a_stale_token_is_replaced_once(admin: tuple[AdminUsers, FakeKeycloak]) -> None:
    users, fake = admin
    assert await users.enabled(ALEX) is True
    fake.token_calls += 1  # the realm now expects a newer token than the cached one (a re-import)
    assert await users.enabled(ALEX) is True
    assert fake.token_calls == 3  # the cached t1 was refused, t3 was fetched and accepted


@pytest.mark.asyncio
async def test_a_slow_answer_is_unavailable_within_the_budget(admin: tuple[AdminUsers, FakeKeycloak]) -> None:
    users, fake = admin
    fake.delay = 2.0
    started = time.monotonic()
    with pytest.raises(AdminUnavailable):
        await users.enabled(ALEX)
    assert time.monotonic() - started < 1.0  # the 0.3 s budget, not the 2 s the server took


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"id": "x", "enabled": "yes"}, [], {"enabled": True}, "text"])
async def test_an_unusable_body_is_unavailable(admin: tuple[AdminUsers, FakeKeycloak], body: Any) -> None:
    users, fake = admin
    fake.body = body
    with pytest.raises(AdminUnavailable):
        await users.enabled(ALEX)


@pytest.mark.asyncio
async def test_a_failing_token_endpoint_is_unavailable(admin: tuple[AdminUsers, FakeKeycloak]) -> None:
    users, fake = admin
    fake.token_status = 500
    with pytest.raises(AdminUnavailable):
        await users.enabled(ALEX)


@pytest.mark.asyncio
async def test_listing_pages_and_refuses_an_empty_realm(admin: tuple[AdminUsers, FakeKeycloak]) -> None:
    users, fake = admin
    fake.users = {uuid4(): i % 2 == 0 for i in range(205)}
    listed = await users.list_enabled()
    assert listed == fake.users  # three pages of 100, 100 and 5
    fake.users = {}
    with pytest.raises(AdminUnavailable):  # nothing listed cannot be told from a broken listing: fail closed
        await users.list_enabled()


@pytest.mark.asyncio
async def test_concurrent_checks_share_one_token_fetch(admin: tuple[AdminUsers, FakeKeycloak]) -> None:
    users, fake = admin
    results = await asyncio.gather(*(users.enabled(ALEX) for _ in range(8)))
    assert results == [True] * 8 and fake.token_calls == 1
```

Run: `uv run python -m pytest tests/plan_f/test_admin_users.py -q` → FAIL (no module).

- [ ] **Step 2: The admin client**

Create `core/src/ops_core/keycloak_admin.py`:

```python
"""The Keycloak admin API as the `ops-view-users` service account (AM-20.7 revocation (b) and (c)).

Two reads and nothing else: one user's `enabled` flag for the API's fail-closed check before a decision-class
mutation (SA:542-546: 2 s budget, cached service-account token, 503 `retryable` when Keycloak is down or slow), and
the user list for the sweeper's membership sync (SA:547). A 404 is a deleted user (T11 review note 2); every other
surprise is `AdminUnavailable`, so a misconfigured role (403), a stale token (401), a 5xx, a timeout or a malformed
body all fail closed rather than read as "enabled". The client dials `settings.Keycloak.server_url` on one keep-alive
connection: on the dev machine a new connection through `localhost` costs about 2 s (spike §3), the whole budget.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import httpx2
from ops_core import settings
from ops_core.tokens import TokenRejected, WorkloadTokenSource

PAGE = 100  # Keycloak's `max` per listing request; `first` pages through the realm


class AdminUnavailable(Exception):
    """Keycloak did not answer the question within the budget: the caller fails closed (503 retryable, or no sync)."""


class AdminUsers:
    """`enabled(subject)` and `list_enabled()` under one overall deadline each."""

    def __init__(
        self, *, users_url: str, tokens: WorkloadTokenSource, client: httpx2.AsyncClient, timeout: float
    ) -> None:
        self._users_url = users_url.rstrip("/")
        self._tokens = tokens
        self._client = client
        self._timeout = timeout

    async def enabled(self, subject: UUID) -> bool:
        """True only when Keycloak says the user exists and is enabled; False for disabled or deleted (404)."""
        try:
            return await asyncio.wait_for(self._enabled(subject), self._timeout)
        except TimeoutError as exc:
            raise AdminUnavailable("admin API did not answer within the budget") from exc

    async def list_enabled(self) -> dict[UUID, bool]:
        """Every realm user's flag, paged; an empty listing is refused (it cannot be told from a broken one)."""
        try:
            return await asyncio.wait_for(self._list_enabled(), self._timeout)
        except TimeoutError as exc:
            raise AdminUnavailable("admin API did not answer within the budget") from exc

    async def aclose(self) -> None:
        """Close the keep-alive connection (process shutdown)."""
        await self._client.aclose()

    async def _get(self, url: str, params: dict[str, str] | None = None) -> httpx2.Response:
        try:
            response = await self._authorised_get(url, params)
            if response.status_code == 401:
                # A cached token the realm no longer accepts (a re-import, a key rotation): fetch once, retry once,
                # inside the same budget (round-1 finding M15).
                self._tokens.invalidate()
                response = await self._authorised_get(url, params)
            return response
        except (httpx2.HTTPError, OSError, TokenRejected, ValueError) as exc:
            # The message names the class of failure only: a token endpoint reply could carry the secret's error text.
            raise AdminUnavailable(f"admin API unreachable: {exc.__class__.__name__}") from exc

    async def _authorised_get(self, url: str, params: dict[str, str] | None) -> httpx2.Response:
        token = await self._tokens.token()
        return await self._client.get(url, params=params, headers={"Authorization": f"Bearer {token}"})

    async def _enabled(self, subject: UUID) -> bool:
        response = await self._get(f"{self._users_url}/{subject}")
        if response.status_code == 404:
            return False
        if response.status_code != 200:
            raise AdminUnavailable(f"admin API answered {response.status_code}")
        body = _json(response)
        usable = isinstance(body, dict) and str(body.get("id")) == str(subject) and isinstance(body.get("enabled"), bool)
        if not usable:
            raise AdminUnavailable("admin API reply is unusable")
        return bool(body["enabled"])

    async def _list_enabled(self) -> dict[UUID, bool]:
        out: dict[UUID, bool] = {}
        first = 0
        while True:
            params = {"briefRepresentation": "true", "first": str(first), "max": str(PAGE)}
            response = await self._get(self._users_url, params)
            if response.status_code != 200:
                raise AdminUnavailable(f"admin API answered {response.status_code}")
            page = _json(response)
            if not isinstance(page, list):
                raise AdminUnavailable("admin API listing is unusable")
            for entry in page:
                if not isinstance(entry, dict) or not isinstance(entry.get("enabled"), bool):
                    raise AdminUnavailable("admin API listing is unusable")
                try:
                    out[UUID(str(entry.get("id")))] = bool(entry["enabled"])
                except ValueError as exc:
                    raise AdminUnavailable("admin API listing carries a non-UUID id") from exc
            if len(page) < PAGE:
                break
            first += PAGE
        if not out:
            raise AdminUnavailable("admin API listed no users")
        return out


def _json(response: httpx2.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise AdminUnavailable("admin API reply is not JSON") from exc


Post = Callable[[str, dict[str, str]], Awaitable[dict[str, Any]]]


def admin_users(*, keycloak: settings.Keycloak, client_secret: str, timeout: float) -> AdminUsers:
    """The production client: one keep-alive connection to `server_url` shared by the token source and the reads."""
    client = httpx2.AsyncClient(timeout=httpx2.Timeout(timeout))

    async def post(url: str, form: dict[str, str]) -> dict[str, Any]:
        response = await client.post(url, data=form)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data

    tokens = WorkloadTokenSource(
        token_url=keycloak.token_url, client_id="ops-view-users", client_secret=client_secret, post=post
    )
    return AdminUsers(users_url=keycloak.admin_users_url, tokens=tokens, client=client, timeout=timeout)
```

(If `httpx2.ASGITransport` is spelled differently in the locked version, the test adapts: `python -c "import httpx2; print([n for n in dir(httpx2) if 'Transport' in n])"`.) Run: `uv run python -m pytest tests/plan_f/test_admin_users.py -q` → PASS.

- [ ] **Step 3: Write the failing helper and token tests**

Create `tests/plan_f/test_auth_helpers.py`:

```python
"""The pure parts of ops_api.auth: hashing and constant-time comparison of the opaque tokens, the origin rule
(BUILD_SPEC §9 origin verification; spike §4 for what browsers and TestClient send), discovery checks (ruling 25),
the sealed refresh token (BUILD_SPEC §9 provider tokens at rest) and the cookie attributes (ruling 6)."""

import pytest
from ops_api import auth
from ops_core import settings
from starlette.responses import Response

KC = settings.Keycloak(
    base_url="http://localhost:18080",
    issuer="http://localhost:18080/realms/ops-dev",
    server_url="http://127.0.0.1:18080",
)
DOC = {
    "issuer": "http://localhost:18080/realms/ops-dev",
    "authorization_endpoint": "http://localhost:18080/realms/ops-dev/protocol/openid-connect/auth",
    "token_endpoint": "http://localhost:18080/realms/ops-dev/protocol/openid-connect/token",
    "end_session_endpoint": "http://localhost:18080/realms/ops-dev/protocol/openid-connect/logout",
    "jwks_uri": "http://localhost:18080/realms/ops-dev/protocol/openid-connect/certs",
    "backchannel_logout_supported": True,
    "backchannel_logout_session_supported": True,
    "code_challenge_methods_supported": ["plain", "S256"],
}


def test_tokens_are_hashed_and_compared_in_constant_time() -> None:
    token = auth.new_token()
    assert len(token) >= 43 and auth.digest(token) != token and len(auth.digest(token)) == 64
    assert auth.matches(token, auth.digest(token)) and not auth.matches(token + "x", auth.digest(token))
    assert auth.new_token() != token


@pytest.mark.parametrize(
    ("headers", "ok"),
    [
        ({"origin": "http://localhost:8000"}, True),
        ({"origin": "http://localhost:8000", "referer": "http://evil.example/"}, True),  # Origin wins when present
        ({"referer": "http://localhost:8000/app/page?x=1"}, True),  # Referer's origin is the fallback
        ({}, False),
        ({"origin": "null"}, False),
        ({"origin": "http://localhost:8001"}, False),
        ({"origin": "https://localhost:8000"}, False),
        ({"origin": "http://evil.example", "referer": "http://localhost:8000/"}, False),
        ({"referer": "localhost:8000"}, False),
    ],
)
def test_same_origin_rule(headers: dict[str, str], ok: bool) -> None:
    assert auth.same_origin(headers, "http://localhost:8000") is ok


def test_discovery_is_checked_and_rewritten_for_server_use() -> None:
    d = auth.Discovery.from_document(DOC, KC)
    assert d.authorization_endpoint.startswith("http://localhost:18080/")  # browser-facing: the registered host
    assert d.token_endpoint == "http://127.0.0.1:18080/realms/ops-dev/protocol/openid-connect/token"
    assert d.end_session_endpoint.startswith("http://127.0.0.1:18080/") and d.jwks_uri.startswith("http://127.0.0.1")
    for bad in (
        {**DOC, "issuer": "http://evil/realms/ops-dev"},
        {**DOC, "backchannel_logout_session_supported": False},
        {**DOC, "code_challenge_methods_supported": ["plain"]},
        {k: v for k, v in DOC.items() if k != "end_session_endpoint"},
    ):
        with pytest.raises(ValueError):
            auth.Discovery.from_document(bad, KC)


def test_token_box_round_trips_and_refuses_another_key() -> None:
    box, other = auth.TokenBox("key-material-one"), auth.TokenBox("key-material-two")
    sealed = box.seal("refresh-token-value")
    assert b"refresh-token-value" not in sealed and box.open(sealed) == "refresh-token-value"
    with pytest.raises(ValueError):
        other.open(sealed)
    with pytest.raises(ValueError):
        box.open(b"not-a-fernet-token")


def test_cookie_attributes() -> None:
    policy = auth.CookiePolicy(secure=False, login_max_age=600)
    response = Response()
    policy.set_session(response, "s-value", "c-value")
    policy.set_login(response, "l-value")
    lines = [v.lower() for k, v in response.raw_headers if k == b"set-cookie" for v in [v.decode()]]
    session = next(line for line in lines if line.startswith("ops_session="))
    csrf = next(line for line in lines if line.startswith("ops_csrf="))
    login = next(line for line in lines if line.startswith("ops_login="))
    assert "httponly" in session and "samesite=lax" in session and "path=/" in session and "max-age" not in session
    assert "httponly" not in csrf and "samesite=lax" in csrf  # readable by the web app, echoed in X-CSRF-Token
    assert "httponly" in login and "max-age=600" in login
    assert all("secure" not in line for line in lines)
    secure = Response()
    auth.CookiePolicy(secure=True, login_max_age=600).set_session(secure, "s", "c")
    assert all(b"secure" in v.lower() for k, v in secure.raw_headers if k == b"set-cookie")
    cleared = Response()
    policy.clear_session(cleared)
    policy.clear_login(cleared)
    gone = [v.decode().lower() for k, v in cleared.raw_headers if k == b"set-cookie"]
    assert len(gone) == 3 and all("max-age=0" in line for line in gone)
```

Create `tests/plan_f/test_id_and_logout_tokens.py`:

```python
"""The two verifiers built on TokenVerifier (rulings 1 and 16) against tokens signed with a throw-away realm key:
every R011 negative for the ID token (issuer, audience, nonce, expiry, signature, algorithm, typ, sid) and every
SA:541 check for the logout token (iss, aud, iat, jti, events, no nonce, sid/sub, header typ, alg), as Keycloak 26.8
shapes them (spike §1 and §2).

Catches: the authlib defaults the spike measured (a wrong `aud` accepted, a missing nonce accepted, 120 s leeway),
an HS256 token signed with the public key, a logout token that carries a nonce, and a replayable token (the jti is
the caller's to record; here the claim must simply be present).
"""

import time
from typing import Any
from uuid import UUID

import jwt
import pytest
from ops_api.auth import BACKCHANNEL_EVENT, IdTokenVerifier, LogoutTokenVerifier, digest
from ops_core.tokens import TokenRejected

from tests.plan_d.test_tokens import ISSUER, JWK1, JWK2, PEM1, PEM2

ALEX = "2fc05986-c7ec-544c-b628-fdb112bbf18a"
NONCE = "n-123"
HS_KEY = "k" * 32  # a full-length HMAC key: the test proves the algorithm pin, not a weak key


def id_token(pem: bytes = PEM1, kid: str = "k1", headers: dict[str, Any] | None = None, **over: Any) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "sub": ALEX,
        "aud": "ops-web",
        "azp": "ops-web",
        "exp": now + 300,
        "iat": now,
        "auth_time": now,
        "nonce": NONCE,
        "sid": "sid-1",
        "typ": "ID",
        "preferred_username": "alex",
    }
    claims.update(over)
    for key in [k for k, v in over.items() if v is None]:
        del claims[key]
    return jwt.encode(claims, pem, algorithm="RS256", headers={"kid": kid, **(headers or {})})


def logout_token(pem: bytes = PEM1, kid: str = "k1", headers: dict[str, Any] | None = None, **over: Any) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "sub": ALEX,
        "aud": "ops-web",
        "exp": now + 120,
        "iat": now,
        "jti": "j-1",
        "sid": "sid-1",
        "typ": "Logout",
        "events": {BACKCHANNEL_EVENT: {}},
    }
    claims.update(over)
    for key in [k for k, v in over.items() if v is None]:
        del claims[key]
    return jwt.encode(claims, pem, algorithm="RS256", headers={"kid": kid, "typ": "logout+jwt", **(headers or {})})


@pytest.fixture
def ids() -> IdTokenVerifier:
    v = IdTokenVerifier(issuer=ISSUER, jwks_url="unused")
    v.verifier.install_keys({"keys": [JWK1]})
    return v


@pytest.fixture
def logouts() -> LogoutTokenVerifier:
    v = LogoutTokenVerifier(issuer=ISSUER, jwks_url="unused")
    v.verifier.install_keys({"keys": [JWK1]})
    return v


@pytest.mark.asyncio
async def test_id_token_accepted_with_the_right_nonce(ids: IdTokenVerifier) -> None:
    claims = await ids.verify(id_token(), nonce_sha256=digest(NONCE))
    assert claims.subject == UUID(ALEX) and claims.sid == "sid-1" and claims.username == "alex"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "token",
    [
        id_token(iss="http://evil/realms/ops-dev"),
        id_token(aud="other"),  # authlib's default would accept this when azp matches (spike §1)
        id_token(aud=["other", "account"], azp="ops-web"),
        id_token(azp="ops-dev-direct"),
        id_token(nonce="other"),
        id_token(nonce=None),  # authlib accepts a missing nonce; this verifier requires it
        id_token(exp=int(time.time()) - 60),  # within authlib's 120 s leeway; refused here (zero leeway)
        id_token(iat=int(time.time()) + 600),
        id_token(sid=None),
        id_token(sid=""),
        id_token(typ="Bearer"),
        id_token(sub="not-a-uuid"),
        id_token(pem=PEM2, kid="k1"),  # signed by another key under the known kid
        id_token(pem=PEM2, kid="k2"),  # unknown kid (no refresh in the unit test)
        jwt.encode({"iss": ISSUER, "sub": ALEX, "aud": "ops-web", "exp": int(time.time()) + 60, "nonce": NONCE}, HS_KEY, algorithm="HS256", headers={"kid": "k1"}),
    ],
)
async def test_id_token_negatives(ids: IdTokenVerifier, token: str) -> None:
    with pytest.raises(TokenRejected):
        await ids.verify(token, nonce_sha256=digest(NONCE))


@pytest.mark.asyncio
async def test_logout_token_accepted(logouts: LogoutTokenVerifier) -> None:
    claims = await logouts.verify(logout_token())
    assert claims.sid == "sid-1" and claims.subject == UUID(ALEX) and claims.jti == "j-1"
    assert claims.expires_at > time.time()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "token",
    [
        logout_token(iss="http://evil/realms/ops-dev"),
        logout_token(aud="other-client"),
        logout_token(nonce="n"),  # SA:541: no nonce
        logout_token(events=None),
        logout_token(events={"http://schemas.openid.net/event/other": {}}),
        logout_token(events="x"),
        logout_token(jti=None),
        logout_token(iat=None),
        logout_token(iat=int(time.time()) + 600),
        logout_token(exp=int(time.time()) - 5),
        logout_token(sid=None),
        logout_token(sub=None),
        logout_token(headers={"typ": "JWT"}),
        logout_token(pem=PEM2, kid="k1"),
        jwt.encode({"iss": ISSUER, "aud": "ops-web", "exp": int(time.time()) + 60, "iat": int(time.time()), "jti": "j", "sid": "s", "sub": ALEX, "events": {BACKCHANNEL_EVENT: {}}}, HS_KEY, algorithm="HS256", headers={"kid": "k1", "typ": "logout+jwt"}),
    ],
)
async def test_logout_token_negatives(logouts: LogoutTokenVerifier, token: str) -> None:
    with pytest.raises(TokenRejected):
        await logouts.verify(token)


def test_second_key_is_never_consulted_without_a_refresh() -> None:
    assert JWK2["kid"] == "k2"  # documents the fixture: k2 is unknown to both verifiers above
```

Run: `uv run python -m pytest tests/plan_f/test_auth_helpers.py tests/plan_f/test_id_and_logout_tokens.py -q` → FAIL (no module `ops_api.auth`).

- [ ] **Step 4: `ops_api.auth`**

Create `api/src/ops_api/auth.py`:

```python
"""Browser login mechanics for the API (T11): the OIDC client, the ID-token and logout-token verifiers, the sealed
refresh token, the cookies and the origin rule.

authlib does the authorization-code flow with PKCE (`AsyncOAuth2Client`, httpx2 backend): the authorization URL
and the code exchange. It does not do the token checks, because its defaults are weaker than BUILD_SPEC §9 asks
(a wrong `aud` passes when `azp` matches, a missing nonce passes, 120 s of leeway; spike §1): the ID token and the
back-channel logout token go through `ops_core.tokens.TokenVerifier`, which pins RS256, requires `aud` and uses
zero leeway, configured per token type (ruling 26). State, nonce and the login cookie are compared as SHA-256 hashes
with `hmac.compare_digest`; the raw values exist only in the browser and in the one request that spends them.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit
from uuid import UUID

import httpx2
from authlib.integrations.httpx_client import AsyncOAuth2Client, OAuthError
from cryptography.fernet import Fernet, InvalidToken
from ops_core import settings
from ops_core.canonical import sha256_hex
from ops_core.tokens import TokenRejected, TokenVerifier
from starlette.responses import Response

SESSION_COOKIE = "ops_session"
CSRF_COOKIE = "ops_csrf"
LOGIN_COOKIE = "ops_login"
CSRF_HEADER = "X-CSRF-Token"
BACKCHANNEL_EVENT = "http://schemas.openid.net/event/backchannel-logout"
CLIENT_ID = "ops-web"


def digest(value: str) -> str:
    """The stored form of every opaque token (BUILD_SPEC §6: session IDs stored hashed)."""
    return sha256_hex(value.encode("utf-8"))


def new_token() -> str:
    """256 random bits, URL-safe: a session ID, a CSRF token, a login binding, a state, a nonce or a PKCE verifier
    (43 characters, inside RFC 7636's 43-128 and its alphabet)."""
    return secrets.token_urlsafe(32)


def matches(value: str, expected_sha256: str) -> bool:
    """Constant-time comparison of a presented token with its stored hash."""
    return hmac.compare_digest(digest(value), expected_sha256)


def origin_of(url: str) -> str | None:
    """`scheme://host[:port]` of an absolute http(s) URL, else None."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}"


def same_origin(headers: Mapping[str, str], origin: str) -> bool:
    """BUILD_SPEC §9 origin verification: `Origin` must equal ours exactly; when a browser omits it, the `Referer`'s
    origin stands in; `null`, another origin or nothing at all is a refusal."""
    sent = headers.get("origin")
    if sent is None:
        referer = headers.get("referer")
        sent = origin_of(referer) if referer else None
    return sent is not None and sent.strip() == origin


@dataclass(frozen=True)
class Discovery:
    """The realm's OIDC metadata after ruling 25's checks: the authorization endpoint keeps the public host the
    browser is sent to; the endpoints this process dials are rewritten to `server_url`."""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    end_session_endpoint: str
    jwks_uri: str

    @classmethod
    def from_document(cls, doc: Mapping[str, Any], keycloak: settings.Keycloak) -> Discovery:
        """Check the realm's metadata and build the endpoints; ValueError refuses the process start."""
        if doc.get("issuer") != keycloak.issuer:
            raise ValueError("discovery issuer differs from OPS_KC_ISSUER")
        if not (doc.get("backchannel_logout_supported") and doc.get("backchannel_logout_session_supported")):
            raise ValueError("the realm does not support session-scoped back-channel logout")
        if "S256" not in (doc.get("code_challenge_methods_supported") or []):
            raise ValueError("the realm does not support PKCE S256")
        try:
            return cls(
                issuer=keycloak.issuer,
                authorization_endpoint=str(doc["authorization_endpoint"]),
                token_endpoint=keycloak.server_side(str(doc["token_endpoint"])),
                end_session_endpoint=keycloak.server_side(str(doc["end_session_endpoint"])),
                jwks_uri=keycloak.server_side(str(doc["jwks_uri"])),
            )
        except KeyError as exc:
            raise ValueError(f"discovery document lacks {exc.args[0]}") from exc


async def fetch_discovery(keycloak: settings.Keycloak, client: httpx2.AsyncClient) -> Discovery:
    """Fetch and check the realm's metadata (startup; a failure refuses to start)."""
    response = await client.get(keycloak.discovery_url)
    response.raise_for_status()
    return Discovery.from_document(response.json(), keycloak)


@dataclass(frozen=True)
class Tokens:
    """What the exchange yields that the API keeps: the ID token for its claims, the refresh token for logout.
    The access token is dropped on purpose: nothing here acts at the provider on the user's behalf."""

    id_token: str
    refresh_token: str


class ExchangeRefused(Exception):
    """The provider refused the code (wrong verifier, reused code, unknown code): a 401 for the browser."""


class ExchangeUnavailable(Exception):
    """The token endpoint could not be reached or answered garbage: a 503 for the browser."""


class OidcClient(Protocol):
    """What the routes need from the provider client; the unit tests fake it."""

    def authorization_url(self, *, state: str, nonce: str, code_verifier: str) -> str:
        """The URL the browser is sent to."""
        ...

    async def exchange(self, *, code: str, code_verifier: str) -> Tokens:
        """Trade the code for tokens or raise ExchangeRefused / ExchangeUnavailable."""
        ...

    async def end_session(self, refresh_token: str) -> None:
        """End the provider session server-side (RP logout); raise ExchangeUnavailable on failure."""
        ...


class AuthlibOidc:
    """The production client: authlib for the flow, one plain httpx2 client for the end-session call."""

    def __init__(
        self, *, discovery: Discovery, client_secret: str, redirect_uri: str, http: httpx2.AsyncClient
    ) -> None:
        self._discovery = discovery
        self._secret = client_secret
        self._redirect_uri = redirect_uri
        self._http = http
        self._client = AsyncOAuth2Client(
            client_id=CLIENT_ID,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope="openid",
            code_challenge_method="S256",
            timeout=10.0,
        )

    def authorization_url(self, *, state: str, nonce: str, code_verifier: str) -> str:
        """The URL the browser is sent to (S256 challenge computed by authlib from the verifier)."""
        url, _ = self._client.create_authorization_url(
            self._discovery.authorization_endpoint, state=state, nonce=nonce, code_verifier=code_verifier
        )
        return str(url)

    async def exchange(self, *, code: str, code_verifier: str) -> Tokens:
        """Trade the code for tokens; the shared client keeps none of them afterwards."""
        try:
            token = await self._client.fetch_token(
                self._discovery.token_endpoint,
                grant_type="authorization_code",
                code=code,
                code_verifier=code_verifier,
                redirect_uri=self._redirect_uri,
            )
        except OAuthError as exc:
            # `error` is the OAuth error code (invalid_grant); the description could echo request values: left out.
            raise ExchangeRefused(str(exc.error or "exchange refused")) from exc
        except (httpx2.HTTPError, OSError, ValueError) as exc:
            raise ExchangeUnavailable(f"token endpoint unreachable: {exc.__class__.__name__}") from exc
        finally:
            # authlib keeps the last token response on the client (shared by every login); nothing here acts at the
            # provider on the user's behalf, so it is dropped at once (round-1 finding M14).
            self._client.token = None
        id_token, refresh = token.get("id_token"), token.get("refresh_token")
        if not isinstance(id_token, str) or not id_token or not isinstance(refresh, str) or not refresh:
            raise ExchangeRefused("token reply lacks id_token or refresh_token")
        return Tokens(id_token=id_token, refresh_token=refresh)

    async def aclose(self) -> None:
        """Close authlib's own connection pool (process shutdown)."""
        await self._client.aclose()

    async def end_session(self, refresh_token: str) -> None:
        """End the provider session with the refresh token (RP logout, server side)."""
        # The form the spike measured (§2): client credentials as basic auth, the refresh token in the body, 204.
        try:
            response = await self._http.post(
                self._discovery.end_session_endpoint, auth=(CLIENT_ID, self._secret), data={"refresh_token": refresh_token}
            )
        except (httpx2.HTTPError, OSError) as exc:
            raise ExchangeUnavailable(f"end-session endpoint unreachable: {exc.__class__.__name__}") from exc
        if response.status_code >= 400:
            raise ExchangeUnavailable(f"end-session endpoint answered {response.status_code}")


@dataclass(frozen=True)
class IdClaims:
    """What the API keeps from a verified ID token."""

    subject: UUID
    sid: str
    username: str


class IdTokens(Protocol):
    """What the callback needs from the ID-token verifier; the unit tests fake it."""

    @property
    def ready(self) -> bool:
        """Whether the signing keys are loaded."""
        ...

    async def load_keys(self) -> None:
        """Fetch the signing keys."""
        ...

    async def verify(self, id_token: str, *, nonce_sha256: str) -> IdClaims:
        """Verify the token against the stored nonce hash or raise TokenRejected."""
        ...


class IdTokenVerifier:
    """BUILD_SPEC §9's checks on the ID token: signature, RS256 only, iss, aud = ops-web, azp = ops-web, exp with
    zero leeway, iat, nonce (hash-compared), sid present, claim typ ID, sub a UUID."""

    def __init__(self, *, issuer: str, jwks_url: str) -> None:
        self.verifier = TokenVerifier(
            issuer=issuer,
            audience=CLIENT_ID,
            allowed_azp=frozenset({CLIENT_ID}),
            jwks_url=jwks_url,
            required_claims=("exp", "iss", "aud", "sub", "iat", "nonce", "sid"),
        )

    @property
    def ready(self) -> bool:
        """Whether the signing keys are loaded."""
        return self.verifier.ready

    async def load_keys(self) -> None:
        """Fetch the signing keys."""
        await self.verifier.load_keys()

    async def verify(self, id_token: str, *, nonce_sha256: str) -> IdClaims:
        """The claims the API keeps, or TokenRejected."""
        principal = await self.verifier.verify_async(id_token)
        claims = principal.claims
        nonce, sid = claims.get("nonce"), claims.get("sid")
        if not isinstance(nonce, str) or not matches(nonce, nonce_sha256):
            raise TokenRejected("id token nonce does not match this login")
        if claims.get("typ") != "ID":
            raise TokenRejected("not an ID token")
        if not isinstance(sid, str) or not sid:
            raise TokenRejected("id token has no session id")
        try:
            subject = UUID(principal.subject)
        except ValueError as exc:
            raise TokenRejected("id token subject is not an identity") from exc
        return IdClaims(subject=subject, sid=sid, username=str(claims.get("preferred_username", "")))


@dataclass(frozen=True)
class LogoutClaims:
    """What the back-channel endpoint acts on from a verified logout token."""

    sid: str
    subject: UUID
    jti: str
    expires_at: int


class LogoutTokens(Protocol):
    """What the back-channel endpoint needs from the logout-token verifier; the unit tests fake it."""

    @property
    def ready(self) -> bool:
        """Whether the signing keys are loaded."""
        ...

    async def load_keys(self) -> None:
        """Fetch the signing keys."""
        ...

    async def verify(self, token: str) -> LogoutClaims:
        """Verify a logout token or raise TokenRejected."""
        ...


class LogoutTokenVerifier:
    """SA:541 plus T11 review note 3: iss, aud, iat, jti, events, exp, no nonce, sid and sub, header typ
    logout+jwt, RS256 only; the jti replay check is the store's."""

    def __init__(self, *, issuer: str, jwks_url: str) -> None:
        self.verifier = TokenVerifier(
            issuer=issuer,
            audience=CLIENT_ID,
            allowed_azp=frozenset(),
            jwks_url=jwks_url,
            required_claims=("exp", "iss", "aud", "iat", "jti", "events", "sid", "sub"),
            require_azp=False,
            typ="logout+jwt",
        )

    @property
    def ready(self) -> bool:
        """Whether the signing keys are loaded."""
        return self.verifier.ready

    async def load_keys(self) -> None:
        """Fetch the signing keys."""
        await self.verifier.load_keys()

    async def verify(self, token: str) -> LogoutClaims:
        """The claims the endpoint acts on, or TokenRejected."""
        principal = await self.verifier.verify_async(token)
        claims = principal.claims
        if "nonce" in claims:
            raise TokenRejected("logout token carries a nonce")
        events = claims.get("events")
        if not isinstance(events, dict) or BACKCHANNEL_EVENT not in events:
            raise TokenRejected("not a back-channel logout event")
        jti, sid = claims.get("jti"), claims.get("sid")
        if not isinstance(jti, str) or not jti or not isinstance(sid, str) or not sid:
            raise TokenRejected("logout token lacks jti or sid")
        try:
            subject = UUID(principal.subject)
        except ValueError as exc:
            raise TokenRejected("logout token subject is not an identity") from exc
        return LogoutClaims(sid=sid, subject=subject, jti=jti, expires_at=principal.expires_at)


class EnabledCheck(Protocol):
    """The admin-API question the decision route asks (ops_core.keycloak_admin.AdminUsers in production)."""

    async def enabled(self, subject: UUID) -> bool:
        """True only when the provider says the user exists and is enabled; raises AdminUnavailable."""
        ...


class TokenBox:
    """Seals the provider refresh token at rest (BUILD_SPEC §9) with a key derived from the `api_session_key`
    secret: Fernet (AES-128-CBC + HMAC-SHA256) from `cryptography`, which `pyjwt[crypto]` already locks."""

    def __init__(self, key_material: str) -> None:
        self._fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(key_material.encode("utf-8")).digest()))

    def seal(self, value: str) -> bytes:
        """Encrypt a provider token for storage."""
        return self._fernet.encrypt(value.encode("utf-8"))

    def open(self, sealed: bytes) -> str:
        """Decrypt a stored token; ValueError when it was not sealed by this key."""
        try:
            return self._fernet.decrypt(sealed).decode("utf-8")
        except (InvalidToken, TypeError) as exc:
            raise ValueError("sealed value is not ours") from exc


@dataclass(frozen=True)
class CookiePolicy:
    """Ruling 6: HttpOnly session cookie, readable CSRF cookie, short login binding; Lax so the callback (a top-level
    navigation back from Keycloak) carries them; Secure iff the public base URL is https."""

    secure: bool
    login_max_age: int

    def set_session(self, response: Response, session: str, csrf: str) -> None:
        response.set_cookie(SESSION_COOKIE, session, httponly=True, secure=self.secure, samesite="lax", path="/")
        response.set_cookie(CSRF_COOKIE, csrf, httponly=False, secure=self.secure, samesite="lax", path="/")

    def set_login(self, response: Response, login: str) -> None:
        response.set_cookie(
            LOGIN_COOKIE, login, max_age=self.login_max_age, httponly=True, secure=self.secure, samesite="lax", path="/"
        )

    def clear_session(self, response: Response) -> None:
        response.delete_cookie(SESSION_COOKIE, path="/", secure=self.secure, httponly=True, samesite="lax")
        response.delete_cookie(CSRF_COOKIE, path="/", secure=self.secure, httponly=False, samesite="lax")

    def clear_login(self, response: Response) -> None:
        response.delete_cookie(LOGIN_COOKIE, path="/", secure=self.secure, httponly=True, samesite="lax")


Closer = Callable[[], Awaitable[None]]


@dataclass
class AuthDeps:
    """Everything the auth routes and dependencies need, built once in the lifespan (production) or faked (tests)."""

    oidc: OidcClient
    id_tokens: IdTokens
    logout_tokens: LogoutTokens
    admin: EnabledCheck
    box: TokenBox
    sessions: settings.SessionSettings
    cookies: CookiePolicy
    closers: tuple[Closer, ...] = field(default_factory=tuple)

    async def aclose(self) -> None:
        for close in self.closers:
            await close()
```

Run: `uv run python -m pytest tests/plan_f/test_auth_helpers.py tests/plan_f/test_id_and_logout_tokens.py -q` → PASS.

- [ ] **Step 5: The session store**

In `api/src/ops_api/store.py` add after `Decided`:

```python
@dataclass(frozen=True)
class LoginState:
    """One authorization request in flight: the hashes the callback compares and the PKCE verifier it spends."""

    state_sha256: str
    nonce_sha256: str
    code_verifier: str


@dataclass(frozen=True)
class SessionRow:
    """A live session as the identity dependency sees it; `refresh_token_enc` is opened only at logout."""

    session_sha256: str
    issuer: str
    subject: UUID
    tenant_id: UUID
    sid: str
    username: str
    csrf_secret_sha256: str
    refresh_token_enc: bytes
```

Extend the `Store` protocol (docstring: "The seven operations of T08 plus T11's six session operations") with:

```python
    async def begin_login(
        self, *, login_sha256: str, state_sha256: str, nonce_sha256: str, code_verifier: str, ttl_seconds: int
    ) -> None:
        """Store one authorization request under the login cookie's hash."""
        ...

    async def take_login(self, login_sha256: str) -> LoginState | None:
        """Consume the request (one shot): its state, or None when absent or expired."""
        ...

    async def create_session(
        self,
        *,
        session_sha256: str,
        issuer: str,
        subject: UUID,
        tenant_id: UUID,
        sid: str,
        username: str,
        csrf_secret_sha256: str,
        refresh_token_enc: bytes,
        absolute_seconds: int,
    ) -> None:
        """Insert a session row with its absolute expiry."""
        ...

    async def live_session(self, session_sha256: str, *, idle_seconds: int) -> SessionRow | None:
        """The row if live (not revoked, inside both limits), touching `last_seen_at`; else None."""
        ...

    async def revoke_session(self, session_sha256: str) -> SessionRow | None:
        """Revoke one session; the row it was (for the sealed refresh token), or None if none was live."""
        ...

    async def record_logout(self, jti: str, *, expires_at: datetime, sid: str) -> int | None:
        """Record a logout token's jti and revoke every session with its sid, atomically; None on a replay."""
        ...
```

and the `DbStore` implementations (each a unit without a tenant: the three tables are RLS-free, SA:523):

```python
    async def begin_login(
        self, *, login_sha256: str, state_sha256: str, nonce_sha256: str, code_verifier: str, ttl_seconds: int
    ) -> None:
        """Store one authorization request under the login cookie's hash."""
        async with self.session.unit() as conn:
            await conn.execute(
                "INSERT INTO app.login_state (login_sha256, state_sha256, nonce_sha256, code_verifier, expires_at)"
                " VALUES (%s, %s, %s, %s, app.current_time() + make_interval(secs => %s))",
                (login_sha256, state_sha256, nonce_sha256, code_verifier, ttl_seconds),
            )

    async def take_login(self, login_sha256: str) -> LoginState | None:
        """Consume the request (one shot): its state, or None when absent or expired."""
        async with self.session.unit() as conn:
            cur = await conn.execute(
                "DELETE FROM app.login_state WHERE login_sha256 = %s"
                " RETURNING state_sha256, nonce_sha256, code_verifier, expires_at > app.current_time() AS live",
                (login_sha256,),
            )
            row = await cur.fetchone()
        if row is None or not row["live"]:
            return None
        return LoginState(str(row["state_sha256"]), str(row["nonce_sha256"]), str(row["code_verifier"]))

    async def create_session(
        self,
        *,
        session_sha256: str,
        issuer: str,
        subject: UUID,
        tenant_id: UUID,
        sid: str,
        username: str,
        csrf_secret_sha256: str,
        refresh_token_enc: bytes,
        absolute_seconds: int,
    ) -> None:
        """Insert a session row with its absolute expiry (every timestamp from app.current_time(), R126)."""
        async with self.session.unit() as conn:
            await conn.execute(
                "INSERT INTO app.sessions (session_sha256, issuer, subject, tenant_id, sid, username,"
                " csrf_secret_sha256, refresh_token_enc, created_at, last_seen_at, expires_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, app.current_time(), app.current_time(),"
                " app.current_time() + make_interval(secs => %s))",
                (session_sha256, issuer, subject, tenant_id, sid, username, csrf_secret_sha256, refresh_token_enc,
                 absolute_seconds),
            )

    async def live_session(self, session_sha256: str, *, idle_seconds: int) -> SessionRow | None:
        """The row if live, touching `last_seen_at` in the same statement: one UPDATE … RETURNING decides liveness
        (BUILD_SPEC §9 idle and absolute limits), so Python compares no clocks."""
        async with self.session.unit() as conn:
            cur = await conn.execute(
                "UPDATE app.sessions SET last_seen_at = app.current_time()"
                " WHERE session_sha256 = %s AND revoked_at IS NULL AND expires_at > app.current_time()"
                " AND last_seen_at > app.current_time() - make_interval(secs => %s)"
                " RETURNING session_sha256, issuer, subject, tenant_id, sid, username, csrf_secret_sha256,"
                " refresh_token_enc",
                (session_sha256, idle_seconds),
            )
            row = await cur.fetchone()
        return None if row is None else _session_row(row)

    async def revoke_session(self, session_sha256: str) -> SessionRow | None:
        """Revoke one session; the row it was, or None if none was live."""
        async with self.session.unit() as conn:
            cur = await conn.execute(
                "UPDATE app.sessions SET revoked_at = app.current_time()"
                " WHERE session_sha256 = %s AND revoked_at IS NULL"
                " RETURNING session_sha256, issuer, subject, tenant_id, sid, username, csrf_secret_sha256,"
                " refresh_token_enc",
                (session_sha256,),
            )
            row = await cur.fetchone()
        return None if row is None else _session_row(row)

    async def record_logout(self, jti: str, *, expires_at: datetime, sid: str) -> int | None:
        """The jti insert and the revocation commit together (spike §5): a rolled-back revocation does not consume
        the token. A target-less ON CONFLICT DO NOTHING needs INSERT only; rowcount 0 is the replay."""
        async with self.session.unit() as conn:
            cur = await conn.execute(
                "INSERT INTO app.logout_jti (jti, expires_at) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (jti, expires_at),
            )
            if cur.rowcount != 1:
                return None
            cur = await conn.execute(
                "UPDATE app.sessions SET revoked_at = app.current_time() WHERE sid = %s AND revoked_at IS NULL", (sid,)
            )
            return int(cur.rowcount)


def _session_row(row: Any) -> SessionRow:
    return SessionRow(
        session_sha256=str(row["session_sha256"]),
        issuer=str(row["issuer"]),
        subject=UUID(str(row["subject"])),
        tenant_id=UUID(str(row["tenant_id"])),
        sid=str(row["sid"]),
        username=str(row["username"]),
        csrf_secret_sha256=str(row["csrf_secret_sha256"]),
        refresh_token_enc=bytes(row["refresh_token_enc"]),
    )
```

(`_session_row` is a module-level helper below the class; `from datetime import datetime` is already imported.) In `core/src/ops_core/persistence.py`, after `assert_clock_profile`, add the guard the API and the sweeper use at start (review focus: a process started against a database the owner has not migrated must say so once, not fail on every request or tick):

```python
async def assert_relation(conn: Conn, name: str) -> None:
    """Refuse to start when a relation a later revision adds is absent (`to_regclass` works for any role)."""
    cur = await conn.execute("SELECT to_regclass(%s) IS NULL AS missing", (name,))
    row = await cur.fetchone()
    if row is not None and row["missing"]:
        raise PersistenceError(f"{name} is missing; run scripts/skeleton.py migrate for this profile")
``` The module docstring's `TODO(T12)` line stays; add "T11: the session store (login_state, sessions, logout_jti)". `uv run mypy api/src core/src` clean; the Plan D API tests still pass because the `FakeStore` is not yet asked for the new methods (Task 4 adds them).

- [ ] **Step 6: The live store test**

Create `tests/e2e/test_sessions_store_live.py`:

```python
"""The session store under the api role's real grants (OPS_LIVE=1): the login one-shot and its expiry, liveness
decided by the one UPDATE … RETURNING (idle and absolute), revocation, and the atomic jti-plus-revoke of the
back-channel logout (a rolled-back revocation does not consume the token, spike §5).

Catches: a statement the api cells do not cover (42501 would surface here, not in Task 6), a session that stays live
past a limit, a replayed jti that revokes again.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from ops_api import store as st
from ops_core import persistence
from ops_core.settings import Role

pytestmark = pytest.mark.asyncio

ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")
ALEX = UUID("2fc05986-c7ec-544c-b628-fdb112bbf18a")
ISSUER = "http://localhost:18080/realms/ops-dev"


async def test_login_state_is_one_shot_and_expires(app_conn: persistence.Conn, role_conn) -> None:
    db = st.DbStore(await role_conn(Role.API))
    key = uuid4().hex
    await db.begin_login(login_sha256=key, state_sha256="s", nonce_sha256="n", code_verifier="v", ttl_seconds=600)
    taken = await db.take_login(key)
    assert taken == st.LoginState("s", "n", "v") and await db.take_login(key) is None
    expired = uuid4().hex
    await db.begin_login(login_sha256=expired, state_sha256="s", nonce_sha256="n", code_verifier="v", ttl_seconds=600)
    await app_conn.execute("UPDATE app.login_state SET expires_at = app.current_time() - interval '1 second'"
                           " WHERE login_sha256 = %s", (expired,))
    assert await db.take_login(expired) is None  # consumed and refused in one statement
    cur = await app_conn.execute("SELECT count(*) AS n FROM app.login_state WHERE login_sha256 = %s", (expired,))
    assert (await cur.fetchone())["n"] == 0


async def new_session(db: st.DbStore, sid: str = "sid-live") -> str:
    key = uuid4().hex
    await db.create_session(
        session_sha256=key, issuer=ISSUER, subject=ALEX, tenant_id=ALPHA, sid=sid, username="alex",
        csrf_secret_sha256="c", refresh_token_enc=b"sealed", absolute_seconds=28800,
    )
    return key


async def test_liveness_is_decided_by_the_update(app_conn: persistence.Conn, role_conn) -> None:
    db = st.DbStore(await role_conn(Role.API))
    key = await new_session(db)
    try:
        row = await db.live_session(key, idle_seconds=1800)
        assert row is not None and row.subject == ALEX and row.sid == "sid-live" and row.refresh_token_enc == b"sealed"
        await app_conn.execute("UPDATE app.sessions SET last_seen_at = last_seen_at - interval '31 minutes'"
                               " WHERE session_sha256 = %s", (key,))
        assert await db.live_session(key, idle_seconds=1800) is None  # idle
        await app_conn.execute(
            "UPDATE app.sessions SET last_seen_at = app.current_time(),"
            " expires_at = app.current_time() - interval '1 second' WHERE session_sha256 = %s",
            (key,),
        )
        assert await db.live_session(key, idle_seconds=1800) is None  # absolute, despite the fresh touch
        await app_conn.execute("UPDATE app.sessions SET expires_at = app.current_time() + interval '1 hour'"
                               " WHERE session_sha256 = %s", (key,))
        assert await db.live_session(key, idle_seconds=1800) is not None
        revoked = await db.revoke_session(key)
        assert revoked is not None and await db.revoke_session(key) is None
        assert await db.live_session(key, idle_seconds=1800) is None
    finally:
        await app_conn.execute("DELETE FROM app.sessions WHERE session_sha256 = %s", (key,))


async def test_record_logout_is_atomic_and_replay_safe(app_conn: persistence.Conn, role_conn) -> None:
    db = st.DbStore(await role_conn(Role.API))
    sid = f"sid-{uuid4().hex[:8]}"
    keys = [await new_session(db, sid), await new_session(db, sid), await new_session(db, "other")]
    jti = f"jti-{uuid4().hex}"
    until = datetime.now(UTC) + timedelta(days=1)
    try:
        assert await db.record_logout(jti, expires_at=until, sid=sid) == 2
        assert await db.record_logout(jti, expires_at=until, sid=sid) is None  # replay
        assert await db.live_session(keys[2], idle_seconds=1800) is not None  # the other sid is untouched
        assert all(await db.live_session(k, idle_seconds=1800) is None for k in keys[:2])
    finally:
        await app_conn.execute("DELETE FROM app.sessions WHERE session_sha256 = ANY(%s)", (keys,))
        await app_conn.execute("DELETE FROM app.logout_jti WHERE jti = %s", (jti,))
```

Run: `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_sessions_store_live.py -q` → PASS (three tests, as role `api`).

- [ ] **Step 7: Gates and commit**

Format, lint, the character count; `PYTHONUTF8=1 uv run python scripts/check.py` → GREEN; `PYTHONUTF8=1 uv run python scripts/check.py --profile test` → GREEN (this task changes a service module, so the live suite runs); `git checkout -- reports/bootstrap`.

```bash
git add core/src/ops_core/keycloak_admin.py api/src/ops_api/auth.py api/src/ops_api/store.py tests/plan_f tests/e2e/test_sessions_store_live.py
git commit -m "feat(api,core): admin-API enabled check client, OIDC client and token verifiers, sealed refresh token, session store (T11)"
```

---

### Task 4: The routes, the dependencies and the unit negatives

**Files:**
- Modify: `api/src/ops_api/app.py` (whole file: `ApiError` flags, `Identity`, three dependencies, five routes, lifespan, `production_app`), `tests/plan_d/test_api.py` (`FakeStore` session methods, `auth_factory`, 401 for no membership)
- Create: `tests/plan_f/auth_fakes.py`, `tests/plan_f/test_api_auth.py`

**Interfaces:**
- Consumes: everything Task 3 produced; `settings.sessions()`, `settings.admin_check_timeout()`, `keycloak_admin.admin_users`.
- Consumes: `persistence.assert_relation(conn, name)` (added in Task 3 beside `assert_clock_profile`: `to_regclass(name) IS NULL` → `PersistenceError("<name> is missing; migrate the database")`).
- Produces: `create_app(verifier, store_factory, auth_factory)` where `auth_factory() -> AuthDeps | Awaitable[AuthDeps]`; `Identity(subject, username, membership, session)` with `.auth` (`"session"` | `"bearer"`); dependencies `identity`, `browser_mutation`, `enabled_identity`; routes `GET /`, `GET /auth/login`, `GET /auth/callback`, `POST /auth/logout` (204), `POST /auth/backchannel-logout` (200/400); `GET /api/v1/me` gains `"auth"`; `ApiError(status, code, message, *, clear_session=False, clear_login=False)`.
- Produces (`tests/plan_f/auth_fakes.py`): `FakeOidc`, `FakeIdTokens`, `FakeLogoutTokens`, `FakeAdmin`, `fake_auth(**over) -> AuthDeps`, `login_as(client, auth, subject, *, sid, username) -> str` (returns the CSRF token).

- [ ] **Step 1: The fakes and the fake store**

Create `tests/plan_f/auth_fakes.py`:

```python
"""In-memory stand-ins for the T11 collaborators, shared by tests/plan_f/test_api_auth.py and the Plan D API tests.
They model behaviour, not Keycloak: the fake OIDC client hands out whatever tokens a test registered under a code,
the fake verifiers map a token string to its claims and compare the nonce hash the way the real one does."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import UUID

from fastapi.testclient import TestClient
from ops_api import auth
from ops_api.auth import AuthDeps, CookiePolicy, ExchangeRefused, ExchangeUnavailable, IdClaims, LogoutClaims, Tokens, TokenBox
from ops_core import settings
from ops_core.keycloak_admin import AdminUnavailable
from ops_core.tokens import TokenRejected

ISSUER = "http://localhost:18080/realms/ops-dev"
ORIGIN = "http://localhost:8000"


@dataclass
class FakeOidc:
    codes: dict[str, Tokens] = field(default_factory=dict)
    started: list[dict[str, str]] = field(default_factory=list)  # state, nonce, code_verifier per login
    ended: list[str] = field(default_factory=list)
    unavailable: bool = False

    def authorization_url(self, *, state: str, nonce: str, code_verifier: str) -> str:
        self.started.append({"state": state, "nonce": nonce, "code_verifier": code_verifier})
        return "https://idp.test/auth?" + urlencode({"state": state, "code_challenge_method": "S256"})

    async def exchange(self, *, code: str, code_verifier: str) -> Tokens:
        if self.unavailable:
            raise ExchangeUnavailable("down")
        if code not in self.codes or code_verifier != self.started[-1]["code_verifier"]:
            raise ExchangeRefused("invalid_grant")
        return self.codes.pop(code)  # a code is spent once

    async def end_session(self, refresh_token: str) -> None:
        if self.unavailable:
            raise ExchangeUnavailable("down")
        self.ended.append(refresh_token)


@dataclass
class FakeIdTokens:
    tokens: dict[str, tuple[IdClaims, str]] = field(default_factory=dict)  # id_token -> (claims, raw nonce)

    @property
    def ready(self) -> bool:
        return True

    async def load_keys(self) -> None:
        return None

    async def verify(self, id_token: str, *, nonce_sha256: str) -> IdClaims:
        if id_token not in self.tokens:
            raise TokenRejected("unknown id token")
        claims, nonce = self.tokens[id_token]
        if not auth.matches(nonce, nonce_sha256):
            raise TokenRejected("nonce")
        return claims


@dataclass
class FakeLogoutTokens:
    tokens: dict[str, LogoutClaims] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return True

    async def load_keys(self) -> None:
        return None

    async def verify(self, token: str) -> LogoutClaims:
        if token not in self.tokens:
            raise TokenRejected("forged")
        return self.tokens[token]


@dataclass
class FakeAdmin:
    disabled: set[UUID] = field(default_factory=set)
    unavailable: bool = False
    calls: int = 0

    async def enabled(self, subject: UUID) -> bool:
        self.calls += 1
        if self.unavailable:
            raise AdminUnavailable("down")
        return subject not in self.disabled


def fake_auth(**over: object) -> AuthDeps:
    """An AuthDeps for TestClient: plain-http cookies, the dev origin, BUILD_SPEC §9 lifetimes."""
    sessions = settings.SessionSettings(ORIGIN, idle_seconds=1800, absolute_seconds=28800, login_seconds=600)
    deps = AuthDeps(
        oidc=FakeOidc(),
        id_tokens=FakeIdTokens(),
        logout_tokens=FakeLogoutTokens(),
        admin=FakeAdmin(),
        box=TokenBox("unit-test-key"),
        sessions=sessions,
        cookies=CookiePolicy(secure=False, login_max_age=600),
    )
    for name, value in over.items():
        setattr(deps, name, value)
    return deps


def login_as(client: TestClient, deps: AuthDeps, subject: UUID, *, sid: str = "sid-1", username: str = "alex") -> str:
    """Drive /auth/login and /auth/callback through the fakes; return the CSRF token the browser would echo."""
    oidc, ids = deps.oidc, deps.id_tokens
    assert isinstance(oidc, FakeOidc) and isinstance(ids, FakeIdTokens)
    started = client.get("/auth/login", follow_redirects=False)
    assert started.status_code == 303, started.text
    state = parse_qs(urlsplit(started.headers["location"]).query)["state"][0]
    code = f"code-{len(oidc.started)}"
    oidc.codes[code] = Tokens(id_token=f"id-{code}", refresh_token=f"refresh-{code}")
    ids.tokens[f"id-{code}"] = (IdClaims(subject=subject, sid=sid, username=username), oidc.started[-1]["nonce"])
    done = client.get("/auth/callback", params={"code": code, "state": state, "iss": ISSUER}, follow_redirects=False)
    assert done.status_code == 303, done.text
    csrf = client.cookies.get("ops_csrf")
    assert csrf
    return csrf
```

`tests/plan_d/test_api.py`: import `from tests.plan_f.auth_fakes import fake_auth`; the `api` fixture becomes

```python
@pytest.fixture
def api() -> Iterator[tuple[TestClient, FakeStore]]:
    fake = FakeStore()
    app = create_app(StubVerifier(), store_factory=lambda: fake, auth_factory=fake_auth)
    with TestClient(app) as c:  # the context manager runs the lifespan, which installs the store and the auth deps
        yield c, fake
```

(`test_database_failure_is_a_safe_503` builds its own app: add `auth_factory=fake_auth` there too). `FakeStore` gains, with `import time` and `from ops_api.store import LoginState, SessionRow`:

```python
        self.logins: dict[str, tuple[LoginState, float]] = {}  # login hash -> (state, expiry)
        self.sessions: dict[str, dict[str, Any]] = {}  # session hash -> row fields + last_seen, expires, revoked
        self.jtis: set[str] = set()
        self.clock = time.time  # tests replace it to age sessions

    async def begin_login(self, *, login_sha256, state_sha256, nonce_sha256, code_verifier, ttl_seconds) -> None:
        self.logins[login_sha256] = (LoginState(state_sha256, nonce_sha256, code_verifier), self.clock() + ttl_seconds)

    async def take_login(self, login_sha256: str) -> LoginState | None:
        entry = self.logins.pop(login_sha256, None)
        return None if entry is None or entry[1] <= self.clock() else entry[0]

    async def create_session(self, *, session_sha256, issuer, subject, tenant_id, sid, username, csrf_secret_sha256, refresh_token_enc, absolute_seconds) -> None:
        self.sessions[session_sha256] = {
            "row": SessionRow(session_sha256, issuer, subject, tenant_id, sid, username, csrf_secret_sha256, refresh_token_enc),
            "last_seen": self.clock(),
            "expires": self.clock() + absolute_seconds,
            "revoked": False,
        }

    async def live_session(self, session_sha256: str, *, idle_seconds: int) -> SessionRow | None:
        entry = self.sessions.get(session_sha256)
        now = self.clock()
        if entry is None or entry["revoked"] or entry["expires"] <= now or entry["last_seen"] <= now - idle_seconds:
            return None
        entry["last_seen"] = now
        row: SessionRow = entry["row"]
        return row

    async def revoke_session(self, session_sha256: str) -> SessionRow | None:
        entry = self.sessions.get(session_sha256)
        if entry is None or entry["revoked"]:
            return None
        entry["revoked"] = True
        row: SessionRow = entry["row"]
        return row

    async def record_logout(self, jti: str, *, expires_at: datetime, sid: str) -> int | None:
        if jti in self.jtis:
            return None
        self.jtis.add(jti)
        hit = [e for e in self.sessions.values() if e["row"].sid == sid and not e["revoked"]]
        for entry in hit:
            entry["revoked"] = True
        return len(hit)
```

(signatures spelled out with the annotations of the protocol). `test_multi_tenant_subject_cannot_act_and_roles_do_not_merge`: the `dual` call now expects **401** (ruling 21), with the comment "no single current membership is no application identity (BUILD_SPEC §7: 401 for missing identity; SA:549)". `test_identity_and_membership`'s expected `/api/v1/me` dict gains `"auth": "bearer"`. Run `uv run python -m pytest tests/plan_d/test_api.py -q` → FAIL on the `auth_factory` keyword (expected until Step 3).

- [ ] **Step 2: Write the failing route tests**

Create `tests/plan_f/test_api_auth.py`:

```python
"""R011 (invalid callback context), R012 (sessions and CSRF), R013 (current membership wins) and R086's API half
(disabled user → 401, back-channel logout, replay) against the FastAPI app with fakes for Keycloak and the store.

Catches: a callback without the login cookie or with a foreign state logging someone in (login CSRF), the wrong
`iss`, a refused exchange turned into a 500, a cookie session mutating without Origin or token, a bearer caller
asked for a CSRF token, a session surviving idle or absolute expiry, revocation or logout, a login that keeps the
previous session alive (no rotation), a logout token replayed, a disabled user still deciding, and Keycloak's
outage read as "enabled".
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from ops_api.app import create_app
from ops_api.auth import LogoutClaims
from ops_core.keycloak_admin import AdminUnavailable

from tests.plan_d.test_api import ALEX, ALPHA, BETA, DUAL, SAM, SHA, FakeStore, StubVerifier, auth, seed_proposal
from tests.plan_f.auth_fakes import ISSUER, ORIGIN, FakeAdmin, FakeIdTokens, FakeLogoutTokens, FakeOidc, fake_auth, login_as


@pytest.fixture
def world():
    deps = fake_auth()
    fake = FakeStore()
    app = create_app(StubVerifier(), store_factory=lambda: fake, auth_factory=lambda: deps)
    with TestClient(app, base_url="http://localhost:8000") as c:  # the public host: /auth/login redirects any other
        yield c, fake, deps


def browser(csrf: str, **extra: str) -> dict[str, str]:
    return {"Origin": ORIGIN, "X-CSRF-Token": csrf, **extra}


def test_login_redirect_shape(world) -> None:
    c, fake, deps = world
    elsewhere = c.get("/auth/login", follow_redirects=False, headers={"Host": "127.0.0.1:8000"})
    assert elsewhere.status_code == 303 and elsewhere.headers["location"] == "http://localhost:8000/auth/login"
    assert not fake.logins and "ops_login" not in c.cookies  # nothing started on the wrong host
    r = c.get("/auth/login", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("https://idp.test/auth?")
    assert r.headers["cache-control"] == "no-store"
    cookie = next(v for k, v in r.headers.multi_items() if k == "set-cookie" and v.startswith("ops_login="))
    assert "HttpOnly" in cookie and "Max-Age=600" in cookie
    assert len(fake.logins) == 1 and deps.oidc.started[-1]["state"] not in str(fake.logins)  # stored hashed
    assert c.get("/").json() == {"status": "ok", "login_url": "/auth/login"}


def test_callback_logs_in_rotates_and_sets_the_session(world) -> None:
    c, fake, deps = world
    first = login_as(c, deps, ALEX)
    me = c.get("/api/v1/me").json()
    assert me["subject"] == str(ALEX) and me["tenant_id"] == str(ALPHA) and me["auth"] == "session"
    assert me["username"] == "alex" and me["roles"] == ["requester"]
    first_hash = next(iter(fake.sessions))
    second = login_as(c, deps, ALEX, sid="sid-2")
    assert second != first and fake.sessions[first_hash]["revoked"] is True  # rotation at login (BUILD_SPEC §9)
    assert len(fake.sessions) == 2 and not fake.logins  # the login row was consumed
    assert "ops_login" not in c.cookies


def test_callback_refuses_a_missing_login_cookie_and_a_foreign_state(world) -> None:
    c, fake, deps = world
    started = c.get("/auth/login", follow_redirects=False)
    state = started.headers["location"].split("state=")[1].split("&")[0]
    deps.oidc.codes["good"] = __import__("ops_api.auth", fromlist=["Tokens"]).Tokens("id-good", "refresh-good")
    deps.id_tokens.tokens["id-good"] = (
        __import__("ops_api.auth", fromlist=["IdClaims"]).IdClaims(ALEX, "sid-1", "alex"),
        deps.oidc.started[-1]["nonce"],
    )
    # Another browser (no login cookie) presents the victim's callback URL: refused before any exchange.
    other = TestClient(c.app, base_url="http://localhost:8000")
    r = other.get("/auth/callback", params={"code": "good", "state": state, "iss": ISSUER}, follow_redirects=False)
    assert r.status_code == 401 and "good" in deps.oidc.codes  # the code was not spent
    # The right browser with the wrong state: refused, and the login row is consumed (one shot).
    r = c.get("/auth/callback", params={"code": "good", "state": "x" * 43, "iss": ISSUER}, follow_redirects=False)
    assert r.status_code == 401 and not fake.logins and "good" in deps.oidc.codes
    r = c.get("/auth/callback", params={"code": "good", "state": state, "iss": ISSUER}, follow_redirects=False)
    assert r.status_code == 401  # no login in progress any more
    assert "ops_session" not in c.cookies


@pytest.mark.parametrize(
    ("tamper", "status"),
    [
        ({"iss": "http://evil/realms/ops-dev"}, 401),
        ({"error": "access_denied", "error_description": "x"}, 401),
        ({"code": "unknown"}, 401),
        ({"nonce": "wrong"}, 401),
        ({"unavailable": True}, 503),
        ({"subject": "nobody"}, 401),
        ({"subject": "dual"}, 401),
    ],
)
def test_callback_negatives(world, tamper: dict[str, Any], status: int) -> None:
    from ops_api.auth import IdClaims, Tokens

    c, fake, deps = world
    started = c.get("/auth/login", follow_redirects=False)
    state = started.headers["location"].split("state=")[1].split("&")[0]
    deps.oidc.codes["good"] = Tokens("id-good", "refresh-good")
    subject = {"nobody": uuid4(), "dual": DUAL}.get(tamper.get("subject", ""), ALEX)
    nonce = tamper.get("nonce", deps.oidc.started[-1]["nonce"])
    deps.id_tokens.tokens["id-good"] = (IdClaims(subject, "sid-1", "x"), nonce)
    deps.oidc.unavailable = bool(tamper.get("unavailable"))
    params = {"code": tamper.get("code", "good"), "state": state, "iss": tamper.get("iss", ISSUER)}
    if "error" in tamper:
        params = {"error": tamper["error"], "error_description": tamper["error_description"], "state": state}
    r = c.get("/auth/callback", params=params, follow_redirects=False)
    assert r.status_code == status, r.text
    assert "ops_session" not in c.cookies and not fake.sessions
    if status == 503:
        assert r.json()["retryable"] is True
    assert "x" not in r.text or "error_description" not in r.text  # the provider's text is never echoed


def test_browser_mutations_need_origin_and_csrf_token(world) -> None:
    c, fake, deps = world
    csrf = login_as(c, deps, ALEX)
    assert c.post("/api/v1/conversations").status_code == 403  # no Origin, no token
    assert c.post("/api/v1/conversations", headers={"Origin": ORIGIN}).status_code == 403
    assert c.post("/api/v1/conversations", headers={"Origin": ORIGIN, "X-CSRF-Token": "x" * 43}).status_code == 403
    assert c.post("/api/v1/conversations", headers=browser(csrf, Origin="http://evil.example")).status_code == 403
    assert c.post("/api/v1/conversations", headers=browser(csrf, Origin="null")).status_code == 403
    ok = c.post("/api/v1/conversations", headers=browser(csrf))
    assert ok.status_code == 201
    referer_only = c.post("/api/v1/conversations", headers={"Referer": ORIGIN + "/app", "X-CSRF-Token": csrf})
    assert referer_only.status_code == 201
    assert c.get("/api/v1/me").status_code == 200  # reads need neither
    # The bearer path is exempt from both (BUILD_SPEC §7: CSRF/origin protection in cookie mode).
    assert c.post("/api/v1/conversations", headers=auth("alex")).status_code == 201


def test_session_expiry_revocation_and_logout(world) -> None:
    c, fake, deps = world
    csrf = login_as(c, deps, ALEX)
    key = next(iter(fake.sessions))
    fake.sessions[key]["last_seen"] -= 1801  # idle (30 min)
    r = c.get("/api/v1/me")
    assert r.status_code == 401 and r.json()["code"] == "UNAUTHENTICATED"
    assert "ops_session" not in c.cookies and "ops_csrf" not in c.cookies  # cleared by the response
    before = set(fake.sessions)
    login_as(c, deps, ALEX)
    key = next(k for k in fake.sessions if k not in before)  # the new row, not the idle-expired one
    fake.sessions[key]["expires"] -= 28801  # absolute (8 h) even with recent activity
    assert c.get("/api/v1/me").status_code == 401
    csrf = login_as(c, deps, ALEX)
    assert c.post("/auth/logout").status_code == 403  # a mutation: CSRF and Origin apply
    out = c.post("/auth/logout", headers=browser(csrf))
    assert out.status_code == 204 and deps.oidc.ended == ["refresh-code-3"]  # the sealed refresh token was opened once
    assert c.get("/api/v1/me").status_code == 401 and "ops_session" not in c.cookies
    assert c.post("/auth/logout", headers=browser(csrf)).status_code == 401  # idempotent: nothing to log out
    assert c.post("/auth/logout", headers=auth("alex")).status_code == 403  # a bearer caller has no session


def test_logout_survives_a_provider_outage(world) -> None:
    c, fake, deps = world
    csrf = login_as(c, deps, ALEX)
    deps.oidc.unavailable = True
    assert c.post("/auth/logout", headers=browser(csrf)).status_code == 204
    assert c.get("/api/v1/me").status_code == 401


def test_revoked_membership_ends_the_session_and_the_bearer(world) -> None:
    c, fake, deps = world
    login_as(c, deps, ALEX)
    assert c.get("/api/v1/me").status_code == 200
    from tests.plan_d import test_api as plan_d

    rows = dict(plan_d.ROWS)
    plan_d.ROWS[ALEX] = []  # the sync deactivated alex
    try:
        r = c.get("/api/v1/me")
        assert r.status_code == 401 and "ops_session" not in c.cookies
        assert all(e["revoked"] for e in fake.sessions.values())
        assert c.get("/api/v1/me", headers=auth("alex")).status_code == 401  # bearer path: same answer (ruling 21)
        plan_d.ROWS[ALEX] = [(BETA, "requester")]  # moved tenant: the session's tenant no longer matches
        login_as(c, deps, ALEX)
        plan_d.ROWS[ALEX] = [(ALPHA, "requester")]
        assert c.get("/api/v1/me").status_code == 401
    finally:
        plan_d.ROWS.clear()
        plan_d.ROWS.update(rows)


def test_backchannel_logout_revokes_by_sid_once(world) -> None:
    c, fake, deps = world
    login_as(c, deps, ALEX, sid="kc-sid")
    other = TestClient(c.app, base_url="http://localhost:8000")
    login_as(other, deps, SAM, sid="kc-sid", username="sam")  # same Keycloak session, second browser tab/app session
    third = TestClient(c.app, base_url="http://localhost:8000")
    login_as(third, deps, ALEX, sid="another-sid")
    exp = int((datetime.now(UTC) + timedelta(minutes=2)).timestamp())
    deps.logout_tokens.tokens["lt-1"] = LogoutClaims(sid="kc-sid", subject=ALEX, jti="j-1", expires_at=exp)
    r = c.post("/auth/backchannel-logout", data={"logout_token": "lt-1"})
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert c.get("/api/v1/me").status_code == 401 and other.get("/api/v1/me").status_code == 401
    assert third.get("/api/v1/me").status_code == 200  # another sid is untouched
    replay = c.post("/auth/backchannel-logout", data={"logout_token": "lt-1"})
    assert replay.status_code == 400 and replay.json()["code"] == "INVALID_INPUT"
    assert c.post("/auth/backchannel-logout", data={"logout_token": "forged"}).status_code == 400
    assert c.post("/auth/backchannel-logout", data={}).status_code == 400
    assert c.post("/auth/backchannel-logout", json={"logout_token": "lt-1"}).status_code == 400
    assert "j-1" in fake.jtis


def test_disabled_user_is_401_and_the_session_is_revoked(world) -> None:
    c, fake, deps = world
    pid = seed_proposal(fake)
    body = {"expected_revision": 1, "expected_payload_sha256": SHA, "decision": "approve", "reason": "ok"}
    csrf = login_as(c, deps, SAM, username="sam")
    deps.admin.disabled.add(SAM)
    r = c.post(f"/api/v1/proposals/{pid}/decisions", headers=browser(csrf), json=body)
    assert r.status_code == 401 and r.json()["code"] == "UNAUTHENTICATED"
    assert "ops_session" not in c.cookies and all(e["revoked"] for e in fake.sessions.values())
    assert pid not in fake.decided  # nothing was decided
    assert c.post(f"/api/v1/proposals/{pid}/decisions", headers=auth("sam"), json=body).status_code == 401
    deps.admin.disabled.clear()
    assert c.post(f"/api/v1/proposals/{pid}/decisions", headers=auth("sam"), json=body).status_code == 200
    assert deps.admin.calls == 3  # one check per decision attempt, none for the reads or the login


def test_decision_is_503_retryable_when_keycloak_is_unavailable(world) -> None:
    c, fake, deps = world
    pid = seed_proposal(fake)
    body = {"expected_revision": 1, "expected_payload_sha256": SHA, "decision": "approve", "reason": "ok"}
    deps.admin.unavailable = True
    r = c.post(f"/api/v1/proposals/{pid}/decisions", headers=auth("sam"), json=body)
    assert r.status_code == 503 and r.json()["code"] == "UNAVAILABLE" and r.json()["retryable"] is True
    assert pid not in fake.decided
    assert c.get(f"/api/v1/proposals/{pid}", headers=auth("sam")).status_code == 200  # reads do not ask Keycloak
    assert c.post("/api/v1/conversations", headers=auth("alex")).status_code == 201  # admission is not decision-class


def test_bearer_and_cookie_do_not_mix(world) -> None:
    c, fake, deps = world
    login_as(c, deps, ALEX)
    me = c.get("/api/v1/me", headers=auth("sam")).json()
    assert me["subject"] == str(SAM) and me["auth"] == "bearer"  # the explicit credential wins
    assert c.get("/api/v1/me", headers=auth("nobody")).status_code == 401  # a bad bearer is not rescued by the cookie
```

Run: `uv run python -m pytest tests/plan_f/test_api_auth.py -q` → FAIL (`auth_factory` unknown; routes missing).

- [ ] **Step 3: `app.py`**

Rewrite `api/src/ops_api/app.py` as follows (the Plan D routes keep their bodies; what changes is marked). Module docstring: replace the last sentence with "Browser sessions (T11): server-side rows, the cookie path beside the bearer path, CSRF and origin on browser mutations, the admin-API enabled check on decision-class mutations, back-channel logout. Idempotency-Key stays declared debt (T12)." Imports gain `from datetime import UTC, datetime, timedelta` (already partly there), `from urllib.parse import urlsplit`, `import httpx2`, `from fastapi.responses import JSONResponse, RedirectResponse`, `from ops_core import keycloak_admin, persistence, settings`, `from ops_core.keycloak_admin import AdminUnavailable`, and `from ops_api import auth as au` plus `from ops_api.auth import AuthDeps, ExchangeRefused, ExchangeUnavailable`.

```python
class ApiError(Exception):
    """A refusal carrying its HTTP status and SafeError code, rendered by the exception handler; the flags say which
    browser cookies the response must clear (a dead session must not be presented again)."""

    def __init__(
        self, status: int, code: ErrorCode, message: str, *, clear_session: bool = False, clear_login: bool = False
    ) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.clear_session, self.clear_login = clear_session, clear_login


class Identity:
    """The caller: the verified subject plus the tenant and roles its current membership grants, and the session row
    when the identity came from the cookie (None on the bearer path)."""

    def __init__(self, *, subject: UUID, username: str, membership: st.Membership, session: st.SessionRow | None) -> None:
        self.subject = subject
        self.username = username
        self.tenant_id = membership.tenant_id
        self.roles = membership.roles
        self.session = session

    @property
    def auth(self) -> str:
        return "bearer" if self.session is None else "session"

    def require(self, role: str) -> None:
        """Refuse with 403 unless the caller holds the role."""
        if role not in self.roles:
            raise ApiError(403, ErrorCode.FORBIDDEN, f"the {role} role is required")


def create_app(
    verifier: Verifier,
    store_factory: Callable[[], st.Store | Awaitable[st.Store]],
    auth_factory: Callable[[], AuthDeps | Awaitable[AuthDeps]],
) -> FastAPI:
    """Build the application around a verifier, a store factory and an auth-deps factory (the lifespan runs both)."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        made = store_factory()
        app.state.store = await made if isinstance(made, Awaitable) else made
        try:
            if isinstance(app.state.store, st.DbStore):
                await persistence.assert_clock_profile(app.state.store.session.conn, settings.profile())
                await persistence.assert_relation(app.state.store.session.conn, "app.login_state")  # revision 0005
            if not verifier.ready:
                await verifier.load_keys()
            deps = auth_factory()
            app.state.auth = await deps if isinstance(deps, Awaitable) else deps
            try:
                for tokens in (app.state.auth.id_tokens, app.state.auth.logout_tokens):
                    if not tokens.ready:
                        await tokens.load_keys()
                yield
            finally:
                await app.state.auth.aclose()
        finally:
            if isinstance(app.state.store, st.DbStore):
                await app.state.store.session.conn.close()

    app = FastAPI(title="ops-api", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    issuer = settings.keycloak().issuer

    async def identity(
        request: Request, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
    ) -> Identity:
        store: st.Store = request.app.state.store
        deps: AuthDeps = request.app.state.auth
        if creds is not None:
            # The bearer path (dev-only direct grant); a cookie sent beside it is ignored (ruling 7).
            try:
                principal = await verifier.verify_async(creds.credentials)
            except TokenRejected as exc:
                raise ApiError(401, ErrorCode.UNAUTHENTICATED, "token rejected") from exc
            try:
                subject = UUID(principal.subject)
            except ValueError as exc:
                raise ApiError(401, ErrorCode.UNAUTHENTICATED, "token subject is not an identity") from exc
            membership = await store.membership(issuer, subject)
            if membership is None:
                # No single current membership is no application identity (BUILD_SPEC §7; SA:549), ruling 21.
                raise ApiError(401, ErrorCode.UNAUTHENTICATED, "no active membership")
            username = str(principal.claims.get("preferred_username", ""))
            return Identity(subject=subject, username=username, membership=membership, session=None)
        raw = request.cookies.get(au.SESSION_COOKIE)
        if raw is None:
            raise ApiError(401, ErrorCode.UNAUTHENTICATED, "a session or bearer token is required")
        row = await store.live_session(au.digest(raw), idle_seconds=deps.sessions.idle_seconds)
        if row is None:
            raise ApiError(401, ErrorCode.UNAUTHENTICATED, "session expired or unknown", clear_session=True)
        # Current membership on every request (BUILD_SPEC §9, R013): the session carries no authority of its own.
        membership = await store.membership(row.issuer, row.subject)
        if membership is None or membership.tenant_id != row.tenant_id:
            await store.revoke_session(row.session_sha256)
            raise ApiError(401, ErrorCode.UNAUTHENTICATED, "no active membership", clear_session=True)
        return Identity(subject=row.subject, username=row.username, membership=membership, session=row)

    async def browser_mutation(request: Request, who: Annotated[Identity, Depends(identity)]) -> Identity:
        """BUILD_SPEC §7: CSRF and origin protection in cookie mode; the bearer path carries no cookie and is exempt."""
        if who.session is None:
            return who
        deps: AuthDeps = request.app.state.auth
        if not au.same_origin(request.headers, deps.sessions.origin):
            raise ApiError(403, ErrorCode.FORBIDDEN, "cross-origin request refused")
        token = request.headers.get(au.CSRF_HEADER)
        if not token or not au.matches(token, who.session.csrf_secret_sha256):
            raise ApiError(403, ErrorCode.FORBIDDEN, "missing or invalid CSRF token")
        return who

    async def enabled_identity(request: Request, who: Annotated[Identity, Depends(browser_mutation)]) -> Identity:
        """SA:542-546: a decision-class mutation first asks Keycloak whether the user is still enabled, before any
        transaction (T11 review note 2); down or slow fails closed with a retryable 503."""
        deps: AuthDeps = request.app.state.auth
        try:
            enabled = await deps.admin.enabled(who.subject)
        except AdminUnavailable as exc:
            log.warning("enabled check unavailable: %s", exc)
            raise ApiError(503, ErrorCode.UNAVAILABLE, "identity provider unavailable") from exc
        if not enabled:
            if who.session is not None:
                await request.app.state.store.revoke_session(who.session.session_sha256)
            raise ApiError(401, ErrorCode.UNAUTHENTICATED, "identity disabled", clear_session=who.session is not None)
        return who

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> Response:
        response = safe(exc.status, exc.code, exc.message)
        cookies: au.CookiePolicy = request.app.state.auth.cookies
        if exc.clear_session:
            cookies.clear_session(response)
        if exc.clear_login:
            cookies.clear_login(response)
        return response
```

The other exception handlers, `body`, `/health/*` are unchanged. `me` adds `"auth": who.auth`. `create_conversation` and `post_message` take `who: Annotated[Identity, Depends(browser_mutation)]`; `post_decision` takes `who: Annotated[Identity, Depends(enabled_identity)]`; the three GET routes keep `Depends(identity)`. New routes, placed after `/health/ready`:

```python
    @app.get("/")
    async def landing() -> dict[str, str]:
        # TODO(T26): the web app's static assets; until then the post-login 303 lands here.
        return {"status": "ok", "login_url": "/auth/login"}

    def no_store(response: Response) -> Response:
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/auth/login")
    async def login(request: Request) -> Response:
        """Start the authorization-code flow with PKCE (BUILD_SPEC §9): state, nonce and verifier live in the store
        under the login cookie's hash (SA:565), never in a signed cookie."""
        store: st.Store = request.app.state.store
        deps: AuthDeps = request.app.state.auth
        public_host = urlsplit(deps.sessions.public_base_url).netloc
        if request.headers.get("host", "") != public_host:
            # A browser at 127.0.0.1:8000 would get its login cookie on a host Keycloak never redirects back to (the
            # registered callback is exact), so it is sent to the public host first (round-1 review focus).
            return no_store(RedirectResponse(f"{deps.sessions.public_base_url}/auth/login", status_code=303))
        login_token, state, nonce, verifier_value = au.new_token(), au.new_token(), au.new_token(), au.new_token()
        await store.begin_login(
            login_sha256=au.digest(login_token),
            state_sha256=au.digest(state),
            nonce_sha256=au.digest(nonce),
            code_verifier=verifier_value,
            ttl_seconds=deps.sessions.login_seconds,
        )
        target = deps.oidc.authorization_url(state=state, nonce=nonce, code_verifier=verifier_value)
        response: Response = RedirectResponse(target, status_code=303)
        deps.cookies.set_login(response, login_token)
        return no_store(response)

    @app.get("/auth/callback")
    async def callback(request: Request) -> Response:
        """Validate the callback context (R011) and open a session: login cookie → stored request (one shot), state
        hash, `iss` (RFC 9207), code exchange with the stored verifier, ID token with the stored nonce, current
        membership; then rotate (BUILD_SPEC §9) and set the cookies."""
        store: st.Store = request.app.state.store
        deps: AuthDeps = request.app.state.auth
        q = request.query_params
        raw_login = request.cookies.get(au.LOGIN_COOKIE)
        if raw_login is None:
            raise ApiError(401, ErrorCode.UNAUTHENTICATED, "no login in progress")
        pending = await store.take_login(au.digest(raw_login))
        if pending is None:
            raise ApiError(401, ErrorCode.UNAUTHENTICATED, "login expired or unknown", clear_login=True)
        if "error" in q:
            log.info("login refused by the identity provider: %s", q.get("error"))  # the code only, never the text
            raise ApiError(401, ErrorCode.UNAUTHENTICATED, "login refused by the identity provider", clear_login=True)
        state, code = q.get("state"), q.get("code")
        if not state or not code or not au.matches(state, pending.state_sha256):
            raise ApiError(401, ErrorCode.UNAUTHENTICATED, "state mismatch", clear_login=True)
        if q.get("iss") != issuer:
            raise ApiError(401, ErrorCode.UNAUTHENTICATED, "issuer mismatch", clear_login=True)
        try:
            tokens = await deps.oidc.exchange(code=code, code_verifier=pending.code_verifier)
        except ExchangeRefused as exc:
            raise ApiError(401, ErrorCode.UNAUTHENTICATED, "code exchange refused", clear_login=True) from exc
        except ExchangeUnavailable as exc:
            log.warning("token endpoint unavailable: %s", exc)
            raise ApiError(503, ErrorCode.UNAVAILABLE, "identity provider unavailable", clear_login=True) from exc
        try:
            claims = await deps.id_tokens.verify(tokens.id_token, nonce_sha256=pending.nonce_sha256)
        except TokenRejected as exc:
            raise ApiError(401, ErrorCode.UNAUTHENTICATED, "id token rejected", clear_login=True) from exc
        membership = await store.membership(issuer, claims.subject)
        if membership is None:
            raise ApiError(401, ErrorCode.UNAUTHENTICATED, "no active membership", clear_login=True)
        previous = request.cookies.get(au.SESSION_COOKIE)
        if previous is not None:
            await store.revoke_session(au.digest(previous))  # rotation: a login never extends an older session
        session_token, csrf = au.new_token(), au.new_token()
        await store.create_session(
            session_sha256=au.digest(session_token),
            issuer=issuer,
            subject=claims.subject,
            tenant_id=membership.tenant_id,
            sid=claims.sid,
            username=claims.username,
            csrf_secret_sha256=au.digest(csrf),
            refresh_token_enc=deps.box.seal(tokens.refresh_token),
            absolute_seconds=deps.sessions.absolute_seconds,
        )
        response: Response = RedirectResponse("/", status_code=303)
        deps.cookies.clear_login(response)
        deps.cookies.set_session(response, session_token, csrf)
        return no_store(response)

    @app.post("/auth/logout", status_code=204)
    async def logout(request: Request, who: Annotated[Identity, Depends(browser_mutation)]) -> Response:
        """Revoke the session, then end the provider session server-side with the sealed refresh token (ruling 4);
        a provider failure is logged and the local revocation stands."""
        if who.session is None:
            raise ApiError(403, ErrorCode.FORBIDDEN, "logout applies to a browser session")
        store: st.Store = request.app.state.store
        deps: AuthDeps = request.app.state.auth
        row = await store.revoke_session(who.session.session_sha256)
        if row is not None:
            try:
                await deps.oidc.end_session(deps.box.open(row.refresh_token_enc))
            except (ValueError, ExchangeUnavailable) as exc:
                log.info("provider session not ended (%s); the local session is revoked", exc.__class__.__name__)
        response = Response(status_code=204)
        deps.cookies.clear_session(response)
        return no_store(response)

    @app.post("/auth/backchannel-logout")
    async def backchannel_logout(request: Request) -> Response:
        """OIDC Back-Channel Logout 1.0 receiver (SA:541): validate, record the jti, revoke by sid; 400 on any
        failure. Exempt from CSRF and Idempotency-Key (no session, no caller to replay for; T11 review note 3)."""
        store: st.Store = request.app.state.store
        deps: AuthDeps = request.app.state.auth
        try:
            form = await request.form()
        except Exception as exc:  # noqa: BLE001  -- a non-form body must be a 400, whatever starlette raises
            raise ApiError(400, ErrorCode.INVALID_INPUT, "logout_token is required") from exc
        token = form.get("logout_token")
        if not isinstance(token, str) or not token:
            raise ApiError(400, ErrorCode.INVALID_INPUT, "logout_token is required")
        try:
            claims = await deps.logout_tokens.verify(token)
        except TokenRejected as exc:
            log.info("back-channel logout token rejected: %s", exc)
            raise ApiError(400, ErrorCode.INVALID_INPUT, "logout token rejected") from exc
        keep_until = datetime.fromtimestamp(claims.expires_at, UTC) + timedelta(days=1)
        revoked = await store.record_logout(claims.jti, expires_at=keep_until, sid=claims.sid)
        if revoked is None:
            raise ApiError(400, ErrorCode.INVALID_INPUT, "logout token replayed")
        log.info("back-channel logout revoked %d session(s)", revoked)
        return no_store(Response(status_code=200))
```

`production_app()`:

```python
def production_app() -> FastAPI:
    """Build the application against Keycloak and PostgreSQL from the environment and secret files."""
    kc = settings.keycloak()
    sess = settings.sessions()
    verifier = TokenVerifier(
        issuer=kc.issuer,
        audience=settings.env("OPS_API_AUDIENCE", "ops-api"),
        allowed_azp=frozenset({"ops-dev-direct"}),
        jwks_url=kc.jwks_url,
    )

    async def make_store() -> st.Store:
        return st.DbStore(await persistence.connect(settings.app_postgres(Role.API)))

    async def make_auth() -> AuthDeps:
        # Discovery first (ruling 25): a realm that does not match the configuration refuses to start.
        http = httpx2.AsyncClient(timeout=httpx2.Timeout(10.0))
        discovery = await au.fetch_discovery(kc, http)
        admin = keycloak_admin.admin_users(
            keycloak=kc,
            client_secret=settings.read_secret("kc_client_secret_ops_view_users"),
            timeout=settings.admin_check_timeout(),
        )
        oidc = au.AuthlibOidc(
            discovery=discovery,
            client_secret=settings.read_secret("kc_client_secret_ops_web"),
            redirect_uri=sess.redirect_uri,
            http=http,
        )
        return AuthDeps(
            oidc=oidc,
            id_tokens=au.IdTokenVerifier(issuer=kc.issuer, jwks_url=discovery.jwks_uri),
            logout_tokens=au.LogoutTokenVerifier(issuer=kc.issuer, jwks_url=discovery.jwks_uri),
            admin=admin,
            box=au.TokenBox(settings.read_secret("api_session_key")),
            sessions=sess,
            cookies=au.CookiePolicy(secure=sess.cookie_secure, login_max_age=sess.login_seconds),
            closers=(http.aclose, admin.aclose, oidc.aclose),
        )

    return create_app(verifier, make_store, make_auth)
```

Run: `uv run python -m pytest tests/plan_f/test_api_auth.py tests/plan_d/test_api.py tests/plan_e/test_api_store_mapping.py -q` → PASS. (`request.form()` needs `python-multipart`, locked; a JSON body raises inside `form()` only for malformed multipart, otherwise yields an empty form, which the `logout_token` check turns into the 400 the test expects.)

- [ ] **Step 4: Gates and commit**

Format, lint (`BLE001` has a `noqa` with its reason), the character count; `uv run mypy api/src core/src --no-incremental` clean; `PYTHONUTF8=1 uv run python scripts/check.py` → GREEN; `PYTHONUTF8=1 uv run python scripts/check.py --profile test` → GREEN (R105 exercises the rewritten `identity` and the decision route's enabled check on the bearer path against the real admin API; `git checkout -- reports/bootstrap` afterwards). The dev database is still at 0004, so the API refuses to start there (the lifespan's revision guard, Step 3) until the owner migrates it (Task 7); do not start it by hand against the dev database.

```bash
git add api/src/ops_api/app.py tests/plan_d/test_api.py tests/plan_f/auth_fakes.py tests/plan_f/test_api_auth.py
git commit -m "feat(api): browser login, server-side sessions, CSRF/origin, enabled check and back-channel logout (T11)"
```

---
### Task 5: The sweeper

**Files:**
- Create: `sweeper/pyproject.toml`, `sweeper/README.md`, `sweeper/src/ops_sweeper/__init__.py`, `sweeper/src/ops_sweeper/__main__.py`, `sweeper/src/ops_sweeper/main.py`, `sweeper/src/ops_sweeper/sync.py`, `tests/plan_f/test_sweeper.py`
- Modify: `pyproject.toml` (workspace member, root dependency, `tool.uv.sources`), `uv.lock` (`uv lock`), `scripts/check.py` (`MEMBER_SRC`), `scripts/skeleton.py` (`PROCESSES`, `process_environment`, docstring), `tests/plan_e/test_skeleton_cli.py` (six processes), `core/src/ops_core/persistence.py` (`insert_maintenance_job`, `claim_maintenance_job`), `docs/runbooks/walking-skeleton.md`

**Interfaces:**
- Consumes: `keycloak_admin.admin_users(...)`, `AdminUsers.list_enabled()`, `persistence.connect`, `finish_job`, `tenants`, `settings.app_postgres(Role.SWEEPER)`, `redaction.install()`.
- Produces: `ops_sweeper.sync.plan(memberships: Iterable[UUID], users: Mapping[UUID, bool]) -> frozenset[UUID]` (the subjects to deactivate), `MAX_DEACTIVATION_FRACTION`, `MassDeactivation`, `async sync_memberships(conn, *, issuer, users) -> SyncResult(checked, deactivated)` (raises `MassDeactivation`, stamping nothing), `async purge_expired(conn) -> dict[str, int]`; `ops_sweeper.main.run_forever(deps, stop)`, `health_app(probe, is_fresh)`, `Deps`, `minute_bucket(at) -> str` (`YYYY-MM-DDTHH:MM`), `fresh(last_sync_at, now)`; `persistence.insert_maintenance_job(conn, job_type, minute_bucket) -> UUID | None`, `claim_maintenance_job(conn, *, job_type, worker_name) -> DictRow | None`; `scripts/skeleton.py` `Process("sweeper", "ops_sweeper", 8071)`.

- [ ] **Step 1: Write the failing sync tests**

Create `tests/plan_f/test_sweeper.py`:

```python
"""The sweeper's pure decisions (ruling 13): which subjects a sync deactivates, the minute bucket of the maintenance
job, and the readiness rule (fresh only while the last successful sync is younger than 120 s).

Catches: a user absent from the listing left active (deleted users keep authority), an enabled user deactivated, a
subject of another issuer touched, a readiness that reports ready before the first sync, and a bucket that skips.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from ops_core.jobs import JobType, dedup_key
from ops_sweeper import sync
from ops_sweeper.main import fresh, minute_bucket

ALEX = UUID("2fc05986-c7ec-544c-b628-fdb112bbf18a")
SAM = UUID("03f7eb09-e18d-5f33-bf75-12c57d5aaa54")
LEE = UUID("abcc1200-6791-57ab-87b5-9392d356b512")


def test_plan_deactivates_disabled_and_deleted_subjects_only() -> None:
    users = {ALEX: True, SAM: False, uuid4(): True}
    assert sync.plan([ALEX, SAM, LEE], users) == frozenset({SAM, LEE})  # SAM disabled, LEE absent (deleted)
    assert sync.plan([ALEX], users) == frozenset()
    assert sync.plan([], users) == frozenset()


def test_minute_bucket_feeds_the_dedup_key_of_sa_504() -> None:
    at = datetime(2026, 10, 9, 8, 30, 59, tzinfo=UTC)
    assert minute_bucket(at) == "2026-10-09T08:30"
    assert dedup_key(JobType.SYNC_MEMBERSHIPS, minute_bucket=minute_bucket(at)) == "sync_memberships:2026-10-09T08:30"
    assert minute_bucket(datetime(2026, 10, 9, 8, 31, 0, tzinfo=UTC)) == "2026-10-09T08:31"


def test_mass_deactivation_is_refused() -> None:
    assert sync.MAX_DEACTIVATION_FRACTION == 0.5
    assert sync.plan([ALEX, SAM, LEE], {}) == frozenset({ALEX, SAM, LEE})  # plan is pure; the refusal is the writer's


def test_fresh_rule() -> None:
    now = 1_000_000.0
    assert not fresh(None, now)
    assert fresh(now - 119, now) and not fresh(now - 121, now)
```

Run: `uv run python -m pytest tests/plan_f/test_sweeper.py -q` → FAIL (no package).

- [ ] **Step 2: The package, the member and the job helpers**

Create `sweeper/pyproject.toml`:

```toml
[project]
name = "ops-sweeper"
version = "0.0.1"
description = "Scheduler process (AM-20.1 sweeper): membership sync, expiry purges; later leases, wake-ups, outbox"
requires-python = ">=3.13"
dependencies = ["ops-core", "uvicorn>=0.54,<1", "starlette>=1.7,<2"]

[tool.uv.sources]
ops-core = { workspace = true }

[build-system]
requires = ["hatchling>=1.27"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/ops_sweeper"]
```

Root `pyproject.toml`: `"ops-sweeper"` in `dependencies`, `ops-sweeper = { workspace = true }` in `[tool.uv.sources]`, `"sweeper"` in `[tool.uv.workspace] members`. `uv lock && uv sync --locked`. `scripts/check.py` `MEMBER_SRC` gains `"sweeper/src"`.

`core/src/ops_core/persistence.py`, after `requeue_job`:

```python
async def insert_maintenance_job(conn: Conn, job_type: JobType, minute_bucket: str) -> UUID | None:
    """A tenant-less sweeper job keyed by `<type>:<minute bucket>` (SA:504); None when that minute already exists.

    `jobs_tenant_iff_run_check` allows a NULL tenant exactly for these, and the sweeper's `sweeper_all` policy
    admits the row without a tenant setting. ON CONFLICT with a target and RETURNING both need SELECT, which the
    sweeper holds on `jobs` (unlike the api role on `logout_jti`, where the insert is target-less).
    """
    if JOB_RULES[job_type].run_states:
        raise ValueError(f"{job_type.value} is not a maintenance job")
    key = dedup_key(job_type, minute_bucket=minute_bucket)  # validates the bucket's shape
    cur = await conn.execute(
        "INSERT INTO app.jobs (id, type, dedup_key) VALUES (%s, %s, %s)"
        " ON CONFLICT (dedup_key) DO NOTHING RETURNING id",
        (uuid4(), job_type.value, key),
    )
    row = await cur.fetchone()
    return None if row is None else UUID(str(row["id"]))


async def claim_maintenance_job(conn: Conn, *, job_type: JobType, worker_name: str) -> DictRow | None:
    """Claim the oldest unclaimed sweeper job of one type (SKIP LOCKED: a second sweeper never runs the same one)."""
    cur = await conn.execute(
        "UPDATE app.jobs SET claimed_by = %s, claimed_at = app.current_time(), attempts = attempts + 1"
        " WHERE id = (SELECT id FROM app.jobs WHERE type = %s AND tenant_id IS NULL AND done_at IS NULL"
        "             AND claimed_at IS NULL AND available_at <= app.current_time()"
        "             ORDER BY available_at, id FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *",
        (worker_name, job_type.value),
    )
    return await cur.fetchone()
```

(`JOB_RULES` and `dedup_key` are importable from `ops_core.jobs`; extend the existing import line.) Note: `ON CONFLICT (dedup_key)` with a target needs SELECT, which the sweeper has on `jobs`; the comment must say so (the spike's "target-less" finding was about the jti table where `api` has INSERT only).

- [ ] **Step 3: `ops_sweeper`**

Create `sweeper/README.md` (ADR-0001: every deployable directory states its ownership and trust):

```markdown
# sweeper

The scheduler process of AM-20.1: PostgreSQL role `sweeper`, Keycloak service account `ops-view-users` (read-only).
Every 30 s it syncs memberships against the realm (deactivates disabled or deleted users, stamps `synced_at`; it never
reactivates), records the sync as the `sync_memberships` maintenance job of the minute, and purges expired sessions,
login state and logout-token ids. It holds no decision authority: it cannot grant, decide, transition a run or write an
event (`append_event` for its own maintenance events only). Leases, wake-ups, the outbox and proposal expiry arrive with
T13/T14/T21. Health: `127.0.0.1:8071/health/ready` is 200 only while the last successful sync is younger than 120 s.
```

Create `sweeper/src/ops_sweeper/__init__.py` (one line: `"""The sweeper: AM-20.1's scheduler process (membership sync, expiry purges)."""`), `sweeper/src/ops_sweeper/__main__.py`:

```python
"""`python -m ops_sweeper`: the scheduler process with its health server on 127.0.0.1:OPS_SWEEPER_HEALTH_PORT."""

from ops_sweeper.main import main

if __name__ == "__main__":
    main()
```

`sweeper/src/ops_sweeper/sync.py`:

```python
"""The membership sync (AM-20.7 revocation (c), SA:547): deactivate the memberships of users Keycloak reports
disabled or no longer lists, stamp every row of the issuer as checked, never reactivate (SA:107: no tenant
administration in v1). Direct column updates by the `sweeper` role under its `sweeper_all` policy and its
`upd(active, permission_version, synced_at)` cells (ruling 13: SA:470's definer shape cannot write under SA:412,
spike §5). One transaction per run, so a failed listing stamps nothing and `grant_execution` fails closed after 120 s.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from uuid import UUID

from ops_core import persistence


MAX_DEACTIVATION_FRACTION = 0.5  # more than half of the active subjects gone at once is a broken listing


class MassDeactivation(Exception):
    """More than MAX_DEACTIVATION_FRACTION of the active subjects would go: refused, nothing stamped."""


@dataclass(frozen=True)
class SyncResult:
    """What one sync did: rows stamped and rows deactivated."""

    checked: int
    deactivated: int


def plan(memberships: Iterable[UUID], users: Mapping[UUID, bool]) -> frozenset[UUID]:
    """The subjects whose memberships must go: disabled (`False`) or absent from the realm listing (deleted)."""
    return frozenset(subject for subject in memberships if not users.get(subject, False))


async def sync_memberships(conn: persistence.Conn, *, issuer: str, users: Mapping[UUID, bool]) -> SyncResult:
    """Apply `plan` to every active membership of `issuer`, then stamp all of the issuer's rows, in one transaction."""
    async with conn.transaction():
        # No DISTINCT: PostgreSQL refuses FOR UPDATE with it (0A000, round-1 finding B2); `plan` dedups anyway.
        cur = await conn.execute(
            "SELECT subject FROM app.memberships WHERE issuer = %s AND active FOR UPDATE", (issuer,)
        )
        active = {UUID(str(r["subject"])) for r in await cur.fetchall()}
        gone = plan(active, users)
        if active and len(gone) > len(active) * MAX_DEACTIVATION_FRACTION:
            # A listing from the wrong realm, or a partial one, would deactivate most of the tenant base at once,
            # and nothing reactivates (SA:107). Refuse, stamp nothing: the gate fails closed after 120 s instead.
            raise MassDeactivation(f"{len(gone)} of {len(active)} active subjects would be deactivated")
        deactivated = 0
        if gone:
            cur = await conn.execute(
                "UPDATE app.memberships SET active = false, permission_version = permission_version + 1,"
                " synced_at = app.current_time() WHERE issuer = %s AND active AND subject = ANY(%s)",
                (issuer, list(gone)),
            )
            deactivated = cur.rowcount
        cur = await conn.execute(
            "UPDATE app.memberships SET synced_at = app.current_time() WHERE issuer = %s", (issuer,)
        )
        return SyncResult(checked=cur.rowcount, deactivated=deactivated)


async def purge_expired(conn: persistence.Conn) -> dict[str, int]:
    """Delete what nothing can use any more: sessions a day past their end, consumed or expired login state, old jti
    rows (erratum 25: the sweeper holds SELECT with its DELETE on all three)."""
    counts: dict[str, int] = {}
    async with conn.transaction():
        for table, where in (
            ("sessions", "expires_at < app.current_time() - interval '1 day'"
                         " OR revoked_at < app.current_time() - interval '1 day'"),
            ("login_state", "expires_at < app.current_time()"),
            ("logout_jti", "expires_at < app.current_time()"),
        ):
            cur = await conn.execute(f"DELETE FROM app.{table} WHERE {where}")
            counts[table] = cur.rowcount
    return counts
```

(`SELECT … FOR UPDATE` by the sweeper needs UPDATE on at least one column: the sweeper's column grant suffices, spike §5. The `DELETE` strings carry no bind-shaped text.)

`sweeper/src/ops_sweeper/main.py`:

```python
"""The sweeper process (AM-20.1 scheduler): a tick loop beside a health server, the worker's shape (one loop
connection as role `sweeper`, one probe connection, a SelectorEventLoop on Windows).

Every tick (30 s) syncs, then records the sync as this minute's `sync_memberships` maintenance job (SA:504's dedup
key; inserted, claimed and finished by the same tick, so the `jobs` table is the audit trail of every minute and a
second sweeper instance never records the same minute twice); the first tick syncs at once, so readiness arrives
within seconds of start, and two syncs are never more than 30 s plus one sync's duration apart (ruling 12; SA:547's
60 s holds with margin). The same tick purges expired rows. Readiness is 200 only while the last successful
sync is younger than 120 s, the window after which `grant_execution` refuses (T11 review note 2), so
`scripts/skeleton.py up` waits for the first sync. TODO(T13/T14/T21): leases, wake-ups, outbox, proposal expiry.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import psycopg
import uvicorn
from ops_core import keycloak_admin, persistence, redaction, settings
from ops_core.jobs import JobType
from ops_core.keycloak_admin import AdminUnavailable
from ops_core.settings import Role
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ops_sweeper import sync

FRESH_SECONDS = 120.0  # the gate's window (0005's grant_execution); readiness follows it
log = logging.getLogger("ops_sweeper")


@dataclass
class Deps:
    """What the loop needs: its connection, the admin client, the issuer whose rows it owns, the cadence."""

    conn: persistence.Conn
    admin: keycloak_admin.AdminUsers
    issuer: str
    tick_seconds: float
    worker_name: str
    last_sync_at: float | None = None  # monotonic time of the last successful sync


def minute_bucket(at: datetime) -> str:
    """The minute bucket of the sync job's dedup key (`ops_core.jobs.dedup_key` builds `sync_memberships:<bucket>`)."""
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M")


def fresh(last_sync_at: float | None, now: float) -> bool:
    """Whether the last successful sync is inside the gate's window."""
    return last_sync_at is not None and now - last_sync_at < FRESH_SECONDS


async def run_sync(deps: Deps) -> None:
    """One sync: list the realm, apply the plan, stamp; a listing failure stamps nothing and is logged."""
    try:
        users = await deps.admin.list_enabled()
    except AdminUnavailable as exc:
        log.warning("membership sync skipped: %s", exc)
        return
    try:
        result = await sync.sync_memberships(deps.conn, issuer=deps.issuer, users=users)
    except sync.MassDeactivation as exc:
        log.error("membership sync refused: %s", exc)
        return
    deps.last_sync_at = time.monotonic()
    log.info("membership sync: %d rows checked, %d deactivated", result.checked, result.deactivated)


async def tick(deps: Deps) -> None:
    """Sync, record this minute's maintenance job (insert, claim, finish), purge expired rows."""
    await run_sync(deps)
    async with deps.conn.transaction():
        await persistence.insert_maintenance_job(deps.conn, JobType.SYNC_MEMBERSHIPS, minute_bucket(datetime.now(UTC)))
        job = await persistence.claim_maintenance_job(
            deps.conn, job_type=JobType.SYNC_MEMBERSHIPS, worker_name=deps.worker_name
        )
        if job is not None:
            await persistence.finish_job(deps.conn, job["id"])
    counts = await sync.purge_expired(deps.conn)
    if any(counts.values()):
        log.info("purged expired rows: %s", counts)


async def run_forever(deps: Deps, stop: asyncio.Event) -> None:
    """Tick, sleep, repeat; a broken connection ends the loop (readiness follows), anything else is logged."""
    while not stop.is_set():
        try:
            await tick(deps)
        except psycopg.OperationalError:
            if deps.conn.broken or deps.conn.closed:
                log.exception("database connection lost; the sweeper stops and exits non-zero")
                raise
            log.exception("transient database error; the loop continues")
        except Exception:  # noqa: BLE001  -- one bad tick must not stop the scheduler
            log.exception("sweeper tick failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=deps.tick_seconds)
        except TimeoutError:
            pass


def health_app(probe: persistence.Conn, is_fresh: Callable[[], bool]) -> Starlette:
    """Readiness: the database answers and the last sync is fresh (so a sweeper whose Keycloak is gone says so)."""

    async def live(_: Request) -> JSONResponse:
        """The process is up."""
        return JSONResponse({"status": "live"})

    async def ready(_: Request) -> JSONResponse:
        """The database answers and the last sync is fresh."""
        try:
            await probe.execute("SELECT 1")
        except (psycopg.Error, OSError):
            return JSONResponse({"status": "not ready"}, status_code=503)
        if not is_fresh():
            return JSONResponse({"status": "not ready", "reason": "no fresh membership sync"}, status_code=503)
        return JSONResponse({"status": "ready"})

    return Starlette(routes=[Route("/health/live", live), Route("/health/ready", ready)])


async def _main() -> None:
    redaction.install()  # the redaction filter must be on the root handler before the first log line
    kc = settings.keycloak()
    admin = keycloak_admin.admin_users(
        keycloak=kc, client_secret=settings.read_secret("kc_client_secret_ops_view_users"), timeout=20.0
    )
    conn = await persistence.connect(settings.app_postgres(Role.SWEEPER))
    probe = await persistence.connect(settings.app_postgres(Role.SWEEPER))
    await persistence.assert_clock_profile(probe, settings.profile())
    await persistence.assert_relation(probe, "app.logout_jti")  # revision 0005 (the purge touches all three tables)
    deps = Deps(
        conn=conn,
        admin=admin,
        issuer=kc.issuer,
        tick_seconds=float(settings.env_int("OPS_SYNC_TICK_SECONDS", 30)),
        worker_name=f"sweeper:{socket.gethostname()}:{os.getpid()}",
    )
    stop = asyncio.Event()
    loop_task = asyncio.create_task(run_forever(deps, stop), name="sweeper-loop")
    server = uvicorn.Server(
        uvicorn.Config(
            health_app(probe, lambda: fresh(deps.last_sync_at, time.monotonic())),
            host="127.0.0.1",
            port=settings.env_int("OPS_SWEEPER_HEALTH_PORT", 8071),
            log_level="warning",
            log_config=None,
        )
    )
    serving = asyncio.create_task(server.serve(), name="health-server")
    try:
        await asyncio.wait({serving, loop_task}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        stop.set()
        server.should_exit = True
        await asyncio.gather(serving, loop_task, return_exceptions=True)
        await admin.aclose()
        await conn.close()
        await probe.close()
    for task in (loop_task, serving):
        if task.done() and not task.cancelled() and task.exception() is not None:
            raise SystemExit(1)


def main() -> None:
    """Run the sweeper until a signal or a lost database connection."""
    if sys.platform == "win32":
        asyncio.run(_main(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(_main())
```

`scripts/skeleton.py`: `PROCESSES` gains `Process("sweeper", "ops_sweeper", 8071)` after the worker; `process_environment()` gains `env.setdefault("OPS_SWEEPER_HEALTH_PORT", "8071")`; the module docstring and `Skeleton` docstring say six processes. `tests/plan_e/test_skeleton_cli.py` gains:

```python
def test_six_processes_on_distinct_loopback_ports() -> None:
    from scripts.skeleton import PROCESSES

    assert [p.name for p in PROCESSES] == ["incident-sim", "mcp-read", "mcp-write", "api", "worker", "sweeper"]
    assert len({p.port for p in PROCESSES}) == 6
    assert all(p.health_url.startswith("http://127.0.0.1:") for p in PROCESSES)
```

Run: `uv run python -m pytest tests/plan_f/test_sweeper.py tests/plan_e/test_skeleton_cli.py -q` → PASS.

- [ ] **Step 4: The live sync test, the live proof and the runbook**

Create `tests/e2e/test_sweeper_live.py` (the sync's SQL under the real `sweeper` grants, with a users mapping the test supplies, so no Keycloak user is touched):

```python
"""The membership sync as role sweeper on ops_test (OPS_LIVE=1): deactivation of a disabled and of a deleted subject,
every row of the issuer stamped, another issuer untouched, the mass-deactivation refusal stamping nothing, and the
maintenance job recorded once per minute. The users mapping is supplied by the test; the admin API is Task 6's."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from ops_core import persistence
from ops_core.jobs import JobType
from ops_core.settings import Role
from ops_sweeper import sync

pytestmark = pytest.mark.asyncio

ISSUER = "http://localhost:18080/realms/ops-dev"
ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")
ALEX = UUID("2fc05986-c7ec-544c-b628-fdb112bbf18a")
SAM = UUID("03f7eb09-e18d-5f33-bf75-12c57d5aaa54")
LEE = UUID("abcc1200-6791-57ab-87b5-9392d356b512")


async def seeded(app_conn: persistence.Conn) -> dict[UUID, bool]:
    cur = await app_conn.execute("SELECT DISTINCT subject FROM app.memberships WHERE issuer = %s", (ISSUER,))
    return {UUID(str(r["subject"])): True for r in await cur.fetchall()}


async def restore(app_conn: persistence.Conn) -> None:
    await app_conn.execute(
        "UPDATE app.memberships SET active = true, permission_version = 1, synced_at = app.current_time()"
    )


async def test_sync_deactivates_disabled_and_deleted_and_stamps_the_issuer(app_conn, role_conn) -> None:
    sweeper = await role_conn(Role.SWEEPER)
    foreign = uuid4()
    await app_conn.execute(
        "INSERT INTO app.memberships (tenant_id, issuer, subject, role)"
        " VALUES (%s, 'http://other/realms/x', %s, 'reader')",
        (ALPHA, foreign),
    )
    await app_conn.execute("UPDATE app.memberships SET synced_at = app.current_time() - interval '1 hour'")
    try:
        users = await seeded(app_conn)
        users[SAM] = False  # disabled
        del users[LEE]  # deleted
        result = await sync.sync_memberships(sweeper, issuer=ISSUER, users=users)
        assert result.deactivated == 2 and result.checked == 5
        cur = await app_conn.execute(
            "SELECT subject, active, permission_version,"
            " synced_at > app.current_time() - interval '5 seconds' AS fresh FROM app.memberships ORDER BY subject"
        )
        rows = {UUID(str(r["subject"])): r for r in await cur.fetchall()}
        assert not rows[SAM]["active"] and rows[SAM]["permission_version"] == 2 and rows[SAM]["fresh"]
        assert not rows[LEE]["active"] and rows[LEE]["permission_version"] == 2
        assert rows[ALEX]["active"] and rows[ALEX]["permission_version"] == 1 and rows[ALEX]["fresh"]
        assert rows[foreign]["active"] and not rows[foreign]["fresh"]  # another issuer: not ours to judge
        again = await sync.sync_memberships(sweeper, issuer=ISSUER, users=users)
        assert again.deactivated == 0 and again.checked == 5  # idempotent
    finally:
        await app_conn.execute("DELETE FROM app.memberships WHERE subject = %s", (foreign,))
        await restore(app_conn)


async def test_mass_deactivation_is_refused_and_stamps_nothing(app_conn, role_conn) -> None:
    sweeper = await role_conn(Role.SWEEPER)
    await app_conn.execute("UPDATE app.memberships SET synced_at = app.current_time() - interval '1 hour'")
    try:
        with pytest.raises(sync.MassDeactivation):
            await sync.sync_memberships(sweeper, issuer=ISSUER, users={ALEX: True})  # four of five would go
        cur = await app_conn.execute(
            "SELECT count(*) AS n FROM app.memberships"
            " WHERE NOT active OR synced_at > app.current_time() - interval '5 seconds'"
        )
        assert (await cur.fetchone())["n"] == 0
    finally:
        await restore(app_conn)


async def test_maintenance_job_is_recorded_once_per_minute(app_conn, role_conn) -> None:
    sweeper = await role_conn(Role.SWEEPER)
    bucket = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M")
    kind = JobType.SYNC_MEMBERSHIPS
    await app_conn.execute("DELETE FROM app.jobs WHERE type = %s", (kind.value,))
    try:
        async with sweeper.transaction():
            first = await persistence.insert_maintenance_job(sweeper, kind, bucket)
            second = await persistence.insert_maintenance_job(sweeper, kind, bucket)
            job = await persistence.claim_maintenance_job(sweeper, job_type=kind, worker_name="t")
            assert first is not None and second is None and job is not None and job["id"] == first
            assert job["tenant_id"] is None and job["run_id"] is None
            await persistence.finish_job(sweeper, job["id"])
            assert await persistence.claim_maintenance_job(sweeper, job_type=kind, worker_name="t") is None
    finally:
        await app_conn.execute("DELETE FROM app.jobs WHERE type = %s", (kind.value,))
```

Run: `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_sweeper_live.py -q` → PASS (three tests; `memberships` has five seeded rows: alex, sam, lee in alpha, riley and jordan in beta, so a listing that keeps only alex refuses). Then opt R105 out of the stamp so it proves the sweeper: register the marker in the root `pyproject.toml` (`[tool.pytest.ini_options] markers = ["sweeper_stamps: the module's skeleton sweeper stamps memberships.synced_at; the autouse fixture must not"]`), make the fixture in `tests/e2e/conftest.py` return early when `request.node.get_closest_marker("sweeper_stamps")` is set (it gains a `request: pytest.FixtureRequest` parameter), and add `pytestmark = pytest.mark.sweeper_stamps` to `tests/e2e/test_r105_walking_skeleton.py` (beside its existing marks). With the dev stack up and no skeleton running: `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_r105_walking_skeleton.py -q` → PASS (six processes; the sweeper's first sync completes before readiness, so the seeded rows are fresh when the grant is asked for, and nothing else stamped them). Confirm in `runtime/skeleton/sweeper.log`: one "membership sync: 5 rows checked, 0 deactivated" line (and no secret-shaped text: `grep -cE "Bearer [^[]|password=[^[]" runtime/skeleton/*.log` → 0 on every file: a redacted line reads `Bearer [REDACTED]`). `docs/runbooks/walking-skeleton.md`: "Six host processes"; the list in step 3 gains `sweeper :8071 (health only; membership sync every 30 s, expiry purges)`; a paragraph: without the sweeper, grants refuse with `MEMBERSHIP_STALE` after 120 s and execute jobs wait (re-queued every 30 s) until it runs; the sync refuses (and stamps nothing) when more than half of the active subjects would be deactivated at once, which is what a listing from the wrong realm looks like; a back-channel logout Keycloak could not deliver is not retried, so the application session then ends at its own limits; the API and the sweeper refuse to start until the database carries revision 0005 (`skeleton.py migrate`).

- [ ] **Step 5: Gates and commit**

Format, lint, the character count; `PYTHONUTF8=1 uv run python scripts/check.py` → GREEN; `--profile test` → GREEN (every live test, R105 included); `git checkout -- reports/bootstrap`; commit `reports/skeleton/r105-walking-skeleton.txt` if it changed.

```bash
git add sweeper pyproject.toml uv.lock scripts/check.py scripts/skeleton.py tests/plan_e/test_skeleton_cli.py tests/plan_f/test_sweeper.py tests/e2e/test_sweeper_live.py tests/e2e/conftest.py tests/e2e/test_r105_walking_skeleton.py core/src/ops_core/persistence.py docs/runbooks/walking-skeleton.md reports/skeleton/r105-walking-skeleton.txt
git commit -m "feat(sweeper): sixth process — membership sync as a maintenance job every minute, expiry purges, freshness readiness (T11)"
```

---

### Task 6: Live proof — login, CSRF, expiry, logout, back-channel logout, disable and sync

**Files:**
- Create: `tests/e2e/test_auth_live.py`, `tests/e2e/kc_browser.py`, `reports/auth/t11-sessions-revocation.txt` (written by the test)
- Modify: `tests/plan_b/test_evidence.py` (scan the new evidence file for token shapes, same as the R105 file)

**Interfaces:**
- Consumes: the skeleton (six processes on `ops_test`), `tests.plan_b.live.kc`, `settings.keycloak()`, `settings.read_secret` through the `secret` fixture, the superuser `app_conn`, the `ops-test-admin` client.
- Produces: `tests/e2e/kc_browser.py`: `Browser` (an httpx2 client that forwards Keycloak's `Secure` cookies by hand, spike §1), `login_through_keycloak(browser, api, username, password) -> Session(csrf)`; `TestAdmin` (`set_enabled(user_id, enabled)`, `logout_user(user_id)`).

- [ ] **Step 1: The browser helper**

Create `tests/e2e/kc_browser.py`:

```python
"""Drive the real Keycloak login form and the API's auth routes from a test, without a browser (spike §1).

Keycloak 26 marks its cookies `Secure` even over plain http on localhost, so httpx2's jar never sends them back on an
http URL (a browser treats http://localhost as a secure context and does); the helper forwards them by hand. Tokens,
codes, cookie values and passwords never appear in an assertion operand or in the evidence file.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

import httpx2

FORM_ACTION = re.compile(r'<form[^>]*id="kc-form-login"[^>]*action="([^"]+)"', re.S)
HIDDEN = re.compile(r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', re.S)
API = "http://127.0.0.1:8000"
ORIGIN = "http://localhost:8000"


def cookie_header(client: httpx2.Client) -> str:
    return "; ".join(f"{c.name}={c.value}" for c in client.cookies.jar)


@dataclass
class Session:
    """One application session as the browser holds it: the API client with its cookies and the CSRF token."""

    api: httpx2.Client
    csrf: str

    def mutation_headers(self) -> dict[str, str]:
        return {"Origin": ORIGIN, "X-CSRF-Token": self.csrf}


class Browser:
    """Two httpx2 clients standing in for one browser: one for the API origin, one for Keycloak's origin."""

    def __init__(self) -> None:
        self.api = httpx2.Client(base_url=API, timeout=15.0, follow_redirects=False)
        self.kc = httpx2.Client(timeout=15.0, follow_redirects=False)

    def close(self) -> None:
        self.api.close()
        self.kc.close()

    def kc_cookies(self) -> dict[str, str]:
        """The Cookie header for Keycloak's origin (empty when the jar is empty)."""
        header = cookie_header(self.kc)
        return {"Cookie": header} if header else {}

    def start_login(self) -> str:
        """GET /auth/login; the Location (the Keycloak authorization URL)."""
        started = self.api.get("/auth/login")
        assert started.status_code == 303, started.status_code
        return started.headers["location"]

    def keycloak_login(self, auth_url: str, username: str, password: str) -> str:
        """Submit the form (or ride an existing SSO cookie) and return the callback URL Keycloak redirects to."""
        page = self.kc.get(auth_url, headers=self.kc_cookies())
        if page.status_code == 302:
            return page.headers["location"]  # an SSO session already exists: no form
        assert page.status_code == 200, page.status_code
        match = FORM_ACTION.search(page.text)
        assert match, "login form not found"
        fields = {k: html.unescape(v) for k, v in HIDDEN.findall(page.text)}
        fields.update(username=username, password=password, credentialId="")
        done = self.kc.post(html.unescape(match.group(1)), data=fields, headers=self.kc_cookies())
        assert done.status_code == 302, done.status_code
        return done.headers["location"]

    def finish_login(self, callback_url: str) -> Session:
        """Present the callback to the API (same path and query, on the API's loopback address)."""
        parts = urlsplit(callback_url)
        assert parts.path == "/auth/callback", parts.path
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        done = self.api.get("/auth/callback", params=query)
        assert done.status_code == 303, done.status_code
        csrf = self.api.cookies.get("ops_csrf")
        assert csrf
        return Session(self.api, csrf)

    def login(self, username: str, password: str) -> Session:
        return self.finish_login(self.keycloak_login(self.start_login(), username, password))


class TestAdmin:
    """The dev/test-only `ops-test-admin` service account (ruling 18): enable, disable, log out a persona."""

    __test__ = False  # not a test class

    def __init__(self, base_url: str, token: str) -> None:
        self._client = httpx2.Client(base_url=f"{base_url}/admin/realms/ops-dev", timeout=15.0)
        self._client.headers["Authorization"] = f"Bearer {token}"

    def close(self) -> None:
        self._client.close()

    def set_enabled(self, user_id: str, enabled: bool) -> int:
        return self._client.put(f"/users/{user_id}", json={"enabled": enabled}).status_code

    def enabled(self, user_id: str) -> bool:
        body = self._client.get(f"/users/{user_id}").json()
        return bool(body["enabled"])
```

- [ ] **Step 2: The live module**

Create `tests/e2e/test_auth_live.py`:

```python
"""T11 live (OPS_LIVE=1): the real Keycloak login form through the skeleton's API, server-side sessions with CSRF and
origin, idle expiry, logout that ends the Keycloak session, the back-channel logout Keycloak sends to the host API
(two application sessions on one Keycloak session), a forged logout token, and the disable path through the sync
(R011, R012, R013, R086). Writes redacted evidence to reports/auth/ (status codes and counts only).
"""

import time
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import httpx2
import jwt
import psycopg
import pytest
from ops_core import persistence, settings

from scripts.skeleton import Skeleton
from tests.e2e.kc_browser import API, ORIGIN, Browser, TestAdmin
from tests.plan_b.live import kc
from tests.plan_d.test_tokens import PEM1

EVIDENCE = Path("reports/auth/t11-sessions-revocation.txt")
ALEX = "2fc05986-c7ec-544c-b628-fdb112bbf18a"
SAM = "03f7eb09-e18d-5f33-bf75-12c57d5aaa54"


@pytest.fixture(scope="module")
def skeleton(migrated: None) -> Iterator[Skeleton]:
    """Six processes for the module; after they stop, sam's membership is restored with no sweeper left to race the
    restore (a sync that listed sam as disabled could otherwise commit after the test's own restore)."""
    sk = Skeleton()
    sk.start()
    try:
        yield sk
    finally:
        sk.stop()
        with psycopg.connect(settings.superuser_postgres().conninfo(), autocommit=True) as conn:
            conn.execute(
                "UPDATE app.memberships SET active = true, synced_at = app.current_time() WHERE subject = %s",
                (UUID(SAM),),
            )


@pytest.fixture(scope="module")
def lines() -> Iterator[list[str]]:
    out = [f"T11 sessions and revocation — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"]
    yield out
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


@pytest.fixture
def browser() -> Iterator[Browser]:
    b = Browser()
    try:
        yield b
    finally:
        b.close()


@pytest.fixture
def admin(secret) -> Iterator[TestAdmin]:
    kcs = settings.keycloak()
    token = kc.token_client_credentials(kcs.base_url, "ops-test-admin", secret("kc_client_secret_ops_test_admin"))
    a = TestAdmin(kcs.base_url, token["access_token"])
    try:
        yield a
    finally:
        a.close()


async def count_sessions(app_conn: persistence.Conn, where: str = "revoked_at IS NULL") -> int:
    cur = await app_conn.execute(f"SELECT count(*) AS n FROM app.sessions WHERE {where}")
    return int((await cur.fetchone())["n"])


@pytest.mark.asyncio
async def test_login_csrf_idle_expiry_and_logout(
    skeleton: Skeleton, browser: Browser, secret, app_conn: persistence.Conn, lines: list[str]
) -> None:
    kcs = settings.keycloak()
    location = browser.start_login()
    assert location.startswith(kcs.base_url + "/realms/ops-dev/protocol/openid-connect/auth?")
    assert "code_challenge_method=S256" in location and "ops_login" in browser.api.cookies
    session = browser.finish_login(browser.keycloak_login(location, "alex", secret("kc_persona_alex_password")))
    assert "ops_login" not in browser.api.cookies and "ops_session" in browser.api.cookies
    me = session.api.get("/api/v1/me")
    assert me.status_code == 200 and me.json()["auth"] == "session" and me.json()["username"] == "alex"
    # CSRF and origin (R012): nothing, Origin only, wrong token, wrong origin, then the real thing.
    refused = [
        session.api.post("/api/v1/conversations").status_code,
        session.api.post("/api/v1/conversations", headers={"Origin": ORIGIN}).status_code,
        session.api.post("/api/v1/conversations", headers={"Origin": ORIGIN, "X-CSRF-Token": "x" * 43}).status_code,
        session.api.post(
            "/api/v1/conversations", headers={"Origin": "http://evil.example", "X-CSRF-Token": session.csrf}
        ).status_code,
    ]
    assert refused == [403, 403, 403, 403], refused
    created = session.api.post("/api/v1/conversations", headers=session.mutation_headers())
    assert created.status_code == 201
    lines.append(f"login: me=200 csrf_refusals={refused} mutation_with_token={created.status_code}")
    # A callback replayed by another client (no login cookie) is refused before any exchange (review focus 1).
    other = Browser()
    try:
        replay = other.api.get("/auth/callback", params={"code": "x", "state": "y", "iss": kcs.issuer})
        assert replay.status_code == 401
    finally:
        other.close()
    # Idle expiry: age the row with the superuser; the next request is 401 and the cookies are cleared.
    await app_conn.execute("UPDATE app.sessions SET last_seen_at = last_seen_at - interval '31 minutes'")
    expired = session.api.get("/api/v1/me")
    assert expired.status_code == 401 and "ops_session" not in session.api.cookies
    lines.append(f"idle expiry: me={expired.status_code}")
    # Logout ends the application session and the Keycloak session: the next login shows the form again.
    session = browser.login("alex", secret("kc_persona_alex_password"))
    out = session.api.post("/auth/logout", headers=session.mutation_headers())
    assert out.status_code == 204 and session.api.get("/api/v1/me").status_code == 401
    again = browser.kc.get(browser.start_login(), headers=browser.kc_cookies())
    assert again.status_code == 200 and "kc-form-login" in again.text  # no SSO ride: the form is back
    lines.append(f"logout: {out.status_code}; keycloak shows the login form again: {again.status_code == 200}")


@pytest.mark.asyncio
async def test_backchannel_logout_revokes_the_sibling_session(
    skeleton: Skeleton, browser: Browser, secret, app_conn: persistence.Conn, lines: list[str]
) -> None:
    """Two application sessions on one Keycloak session (the second /auth/login rides the SSO cookie, same sid);
    logging the second out ends the Keycloak session, Keycloak POSTs the logout token to the host API through
    host.docker.internal, and the first session is gone without ever calling /auth/logout."""
    first_browser = browser
    first = first_browser.login("alex", secret("kc_persona_alex_password"))
    second_browser = Browser()
    second_browser.kc = first_browser.kc  # the same SSO cookies: Keycloak answers /auth with a code and no form
    try:
        second = second_browser.finish_login(second_browser.keycloak_login(second_browser.start_login(), "", ""))
        cur = await app_conn.execute("SELECT count(DISTINCT sid) AS n FROM app.sessions WHERE revoked_at IS NULL")
        assert (await cur.fetchone())["n"] == 1  # one Keycloak session, two application sessions
        before = await count_sessions(app_conn, "revoked_at IS NULL")
        cur = await app_conn.execute("SELECT count(*) AS n FROM app.logout_jti")
        jtis_before = int((await cur.fetchone())["n"])
        out = second.api.post("/auth/logout", headers=second.mutation_headers())
        assert out.status_code == 204
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and first.api.get("/api/v1/me").status_code == 200:
            time.sleep(0.25)
        gone = first.api.get("/api/v1/me")
        assert gone.status_code == 401  # revoked by the back-channel logout, not by its own logout
        cur = await app_conn.execute("SELECT count(*) AS n FROM app.logout_jti")
        assert int((await cur.fetchone())["n"]) == jtis_before + 1
        assert await count_sessions(app_conn, "revoked_at IS NULL") == before - 2
        lines.append(f"back-channel logout: sibling me={gone.status_code}, jti rows +1, sessions revoked 2")
    finally:
        second_browser.api.close()


def test_forged_logout_token_is_refused(skeleton: Skeleton, lines: list[str]) -> None:
    kcs = settings.keycloak()
    forged = jwt.encode(
        {
            "iss": kcs.issuer,
            "aud": "ops-web",
            "sub": ALEX,
            "sid": "x",
            "jti": "forged-1",
            "iat": int(time.time()),
            "exp": int(time.time()) + 120,
            "events": {"http://schemas.openid.net/event/backchannel-logout": {}},
        },
        PEM1,
        algorithm="RS256",
        headers={"kid": "not-a-realm-key", "typ": "logout+jwt"},
    )
    with httpx2.Client(base_url=API, timeout=15.0) as c:
        r = c.post("/auth/backchannel-logout", data={"logout_token": forged})
        assert r.status_code == 400 and r.json()["code"] == "INVALID_INPUT"
        assert c.post("/auth/backchannel-logout", data={}).status_code == 400
    lines.append(f"forged logout token: {r.status_code}")


@pytest.mark.asyncio
async def test_disabled_user_is_refused_and_synced_within_60s(
    skeleton: Skeleton, browser: Browser, secret, admin: TestAdmin, app_conn: persistence.Conn, lines: list[str]
) -> None:
    """R086: disable sam in Keycloak; sam's next decision-class mutation is 401 at once (admin-API check), the sync
    deactivates sam's membership within 60 s, and sam's still-valid bearer token then fails every protected read.
    The finally block re-enables sam at Keycloak; the module fixture restores the row once the sweeper is gone."""
    kcs = settings.keycloak()
    sam_token = kc.token_password(kcs.base_url, "ops-dev-direct", "sam", secret("kc_persona_sam_password"))
    headers = {"Authorization": f"Bearer {sam_token['access_token']}"}
    assert admin.set_enabled(SAM, False) == 204 and admin.enabled(SAM) is False
    try:
        with httpx2.Client(base_url=API, timeout=15.0) as c:
            # A decision on a random proposal: the enabled check runs before any lookup, so a disabled user is 401,
            # never 404 (the check is a dependency, T11 review note 2).
            body = {"expected_revision": 1, "expected_payload_sha256": "0" * 64, "decision": "approve"}
            decided = c.post(f"/api/v1/proposals/{UUID(int=1)}/decisions", headers=headers, json=body)
            assert decided.status_code == 401, decided.text
            started = time.monotonic()
            deadline = started + 75
            while time.monotonic() < deadline:
                cur = await app_conn.execute(
                    "SELECT bool_and(NOT active) AS off, max(permission_version) AS pv FROM app.memberships"
                    " WHERE subject = %s",
                    (UUID(SAM),),
                )
                row = await cur.fetchone()
                if row["off"]:
                    break
                time.sleep(1.0)
            synced_after = round(time.monotonic() - started, 1)
            assert row["off"] and row["pv"] == 2, row
            assert synced_after <= 60.0, synced_after
            me = c.get("/api/v1/me", headers=headers)
            assert me.status_code == 401  # no active membership: the session/token is otherwise valid (R013)
            lines.append(
                f"disabled user: decision={decided.status_code} synced_after={synced_after}s me={me.status_code}"
            )
    finally:
        assert admin.set_enabled(SAM, True) == 204  # the row is restored by the module fixture, after the sweeper stops
```

Notes for the implementer: (a) the second login in the back-channel test reuses the first browser's Keycloak client so the SSO cookies ride along; `keycloak_login` returns on the 302 without touching the form, so the empty credentials are never sent; (b) `admin.set_enabled` is a partial `PUT` (`{"enabled": false}`): Keycloak 26.8 applies it and leaves the other fields (if the live run shows otherwise, send the `GET` representation back with `enabled` changed, and say so in the report); (c) `tests/plan_b/test_evidence.py`'s token-shape scan is extended to `reports/auth/*.txt`.

- [ ] **Step 3: Run, record, commit**

`OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_auth_live.py -q` → PASS (record the four `lines` in the report: they hold status codes and counts only). Add `pytestmark = pytest.mark.sweeper_stamps` to the module (its skeleton's sweeper stamps; the fixture must not), and in the back-channel test assert that `min(synced_at)` over the seeded rows advanced within 75 s of the module's start (a `SELECT min(synced_at) FROM app.memberships` at the start of the first test and again before the back-channel assertions). Then the whole live suite: `PYTHONUTF8=1 uv run python scripts/check.py --profile test` → GREEN (sam is re-enabled and active again before the later modules run; the autouse fixture stamps `synced_at` for them). `git checkout -- reports/bootstrap`.

```bash
git add tests/e2e/kc_browser.py tests/e2e/test_auth_live.py tests/plan_b/test_evidence.py reports/auth/t11-sessions-revocation.txt reports/skeleton/r105-walking-skeleton.txt
git commit -m "test(e2e): live login, CSRF, expiry, logout, back-channel logout, forged token and the disable-and-sync path (T11)"
```

---

### Task 7: Handoff records, errata, documentation, final gates

**Files:**
- Modify: `handoff/tasks.json` (T11 → `DONE` with a review note), `handoff/BUILD_BACKLOG.md` (T11 checked), `handoff/acceptance-matrix.json` (R011, R012, R013, R086), `SESSION_STATE.md` (Plan F executed; errata 26–31; dev database state; next task), `STATUS.md`, `README.md` (status line), `docs/ARCHITECTURE.md` (sweeper row, browser-user row), `docs/runbooks/dev-topology.md` (host processes table; the `ops-test-admin` warning), `docs/runbooks/walking-skeleton.md` (the dev database must be migrated to 0005 before `up`; the login walk-through), `core/src/ops_core/privileges.py:150` (the `resolve_identity` comment: the sync needs no definer)

- [ ] **Step 1: Handoff records**

`handoff/tasks.json`: T11 `status: "DONE"`; `review_notes` gains one entry starting `Plan F (branch plan-f): done in <first>..<last>.` naming: the four routes, the cookie path beside the bearer path, CSRF + origin on browser mutations, the enabled check on the decision route (2 s, keep-alive to 127.0.0.1, 503 retryable), the back-channel endpoint with the durable jti store, revision 0005, the sweeper as the sixth process (sync as a maintenance job per minute, `MEMBERSHIP_STALE` after 120 s, `GRANT_DEFERRED` re-queue), the redaction filter, and the deferrals from the debt list (Idempotency-Key → T12; the enabled check on revisions/cancel/manual proposals and the grant-side evidence → T21; SSE recheck → T27; telemetry → T28; containerised back-channel URL and the demo realm → T30).

`handoff/acceptance-matrix.json` (`requirements` rows; fields `implementation_status`, `evidence_status`, `evidence_paths`, `note`): R011, R012, R013, R086 → `IMPLEMENTED_LOCALLY_VERIFIED` / `RECORDED_LOCALLY_LIVE`, `evidence_paths` = `tests/e2e/test_auth_live.py`, `reports/auth/t11-sessions-revocation.txt`, plus the unit module (`tests/plan_f/test_api_auth.py`, `tests/plan_f/test_id_and_logout_tokens.py`); R086's `note`: "the admin-API half and the sync half are live; the grant-side block through a real `grant_execution` call lands with T21 (T11 review note 1)". `handoff/BUILD_BACKLOG.md`: T11 checked with the same note.

- [ ] **Step 2: Project state and docs**

`SESSION_STATE.md`:
- The "Next task" line: Plan F executed on `plan-f` (`<first>..<last>`); owner inputs unchanged plus two new ones: migrate the dev database to 0005 (`skeleton.py migrate`, no owner data at risk: `sessions` is empty) and decide errata 26–31; next is Plan G (T12 admission router and Idempotency-Key, or T13 leases, whichever the backlog's dependency graph puts first).
- A "Plan F executed" paragraph: the rulings file; the proposed errata, numbered 26–34: (26) `sync_memberships` is the sweeper's routine, not a definer (SA:470 vs SA:412); (27) AM-20.2 rows for `login_state` and `logout_jti`, and `sweeper` SELECT on `sessions` (with 25); (28) AM-01's directory table gains `sweeper/`; (29) a disabled or membership-less user is 401, not 403, on every path (BS:301 reading); (30) the dev realm carries a dev/test-only `ops-test-admin` client with `manage-users` (strike it and lose R086's live disable path); (31) the provider refresh token is stored sealed and spent at logout; the ID and access tokens are not stored; (32) BS:352's "tenant switching" is not in v1: a subject with two memberships is refused at login and with a bearer token (SA:107 has no tenant administration; a switch needs a new session row and rotation); (33) SA:565's "authlib's OIDC state lives in that store" is read as "the authorization request's state, nonce and verifier live in PostgreSQL" (`app.login_state`, keyed by the login cookie's hash) rather than in authlib's own session-dict machinery, which needs Starlette's `SessionMiddleware`; (34) BS:268's route table gains `POST /auth/backchannel-logout` (SA:541 requires the endpoint) and `GET /` (a landing page until T26), and the realm's SSO lifetimes are 8 h so the provider session outlives the application session. Plus the authlib/joserfc versions the lock chose if they differ from AM-30.
- "Dev database state": still at 0004 until the owner runs `migrate`; until then the API and the sweeper refuse to start (`app.login_state` / `app.logout_jti` missing, the lifespan guard of Task 3), so `skeleton.py up` fails fast with that message rather than serving a half-migrated schema.
- Open items parked by the task reviews (from the ledger).

`README.md` status line: "browser login with server-side sessions, revocation and the membership sync (T11)". `STATUS.md`: a row for T11. `docs/ARCHITECTURE.md`: the sweeper row gains "runs (T11)"; the Browser-user row says "opaque server-side session cookie; CSRF token; no provider token". `docs/runbooks/dev-topology.md`: the host-processes table gains the sweeper; a paragraph on the login flow (login → Keycloak form → callback → cookies; logout; what the back-channel URL is and why it names the Docker host alias) and the warning that `ops-test-admin` exists in the dev realm only. `core/src/ops_core/privileges.py:150`: the comment becomes `# the sweeper's sync writes directly (Plan F ruling 13); no further caller`.

- [ ] **Step 3: Final gates**

```bash
PYTHONUTF8=1 uv run python scripts/check.py
PYTHONUTF8=1 uv run python scripts/check.py --profile test
uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts
```

All GREEN / exit 0; record the counts. `git checkout -- reports/bootstrap`; commit the two evidence files if a live run changed them.

- [ ] **Step 4: Commit**

```bash
git add handoff SESSION_STATE.md STATUS.md README.md docs/ARCHITECTURE.md docs/runbooks core/src/ops_core/privileges.py reports/auth reports/skeleton
git commit -m "docs: close T11 — handoff records, acceptance rows, errata 26-34, runbooks (Plan F)"
```

---

## Self-review (run by the plan's author before execution)

1. **Spec coverage.** T11 instructions: authlib code+PKCE with state in the server-side store → Tasks 3–4 (ruling 1, 2); opaque hashed session IDs → Task 3 (`digest`, `session_sha256`); CSRF and origin checks → Task 4 (`browser_mutation`); hand-written back-channel logout endpoint → Task 4 with the verifier of Task 3; admin-API enabled check on decision-class mutations → Tasks 3–4; 60 s membership sync → Task 5. DoD 1 (negative tests for state/nonce/iss/aud, CSRF, revoked membership) → Task 4's unit tests and Task 6; DoD 2 (disabled user 401; grants blocked within 60 s) → Task 6 for the 401 and the sync, Task 2 for the gate rule, T21 for the grant-side live evidence (T11 note 1); DoD 3 (logout token validation incl. jti replay) → Tasks 3, 4, 6. Review notes 1–4 → rulings 11, 14, 16, 22. R011 → Task 3/4/6; R012 → Task 4/6; R013 → Task 4/6 (per-request `resolve_identity`, 401, session revoked); R086 → Task 4/5/6. SA:565 (no SessionMiddleware) → ruling 1; BS:350 (cookie attributes, provider tokens, rotation, expiry) → rulings 3, 4, 6, 8; BS:264 (CSRF in cookie mode) → ruling 5, 7; BS:301 (401/403/503) → rulings 11, 21.
2. **Placeholder scan.** No TBD/"similar to Task N"; the `TODO(Txx)` strings inside code blocks are ownership markers required by `docs/CODE_COMMENTS.md`.
3. **Type consistency.** `Store.live_session(session_sha256, *, idle_seconds) -> SessionRow | None` is what `identity` calls (not `session`: `DbStore.session` is the `persistence.Session` attribute, round-1 finding B1); `record_logout(jti, *, expires_at, sid) -> int | None` is what the endpoint and the fake implement; `AdminUsers.enabled` and `FakeAdmin.enabled` share the `EnabledCheck` protocol; `IdTokens.verify(id_token, *, nonce_sha256)` is called with the stored hash; `AuthDeps` fields are the same in `fake_auth` and `production_app`; `create_app(verifier, store_factory, auth_factory)` is called with three positionals in production and keywords in tests; `Identity(subject=, username=, membership=, session=)` is built in two places with the same keywords; `TokenVerifier(required_claims=, require_azp=, typ=)` is used by both verifiers; `persistence.insert_maintenance_job(conn, job_type, bucket)` and `claim_maintenance_job(conn, *, job_type, worker_name)` match `tick`.
4. **Review Focus.** Login CSRF (review focus 1) → Task 4 `test_callback_refuses_a_missing_login_cookie_and_a_foreign_state` and Task 6's replayed callback; cross-site POST (2) → Task 4 `test_browser_mutations_need_origin_and_csrf_token` and Task 6; logout token negatives and replay (3) → Task 3 `test_logout_token_negatives`, Task 4 `test_backchannel_logout_revokes_by_sid_once`, Task 6's forged token; Keycloak down (4) → Task 3 `test_a_slow_answer_is_unavailable_within_the_budget`, Task 4 `test_decision_is_503_retryable_when_keycloak_is_unavailable`; disabled/deactivated/stale (5) → Task 4 `test_disabled_user_is_401_and_the_session_is_revoked`, Task 2 `test_grant_execution_refuses_a_stale_sync`, Task 6 `test_disabled_user_is_refused_and_synced_within_60s`.

# Plan F inputs: T11 (Keycloak login, server-side sessions and revocation) — fact sheet

Prepared 2026-10-08 on branch `plan-e` at `b6a0b49` (clean tree; read-only on the repository). Facts only, no design.
Citations: `SA:<line>` = `SPEC_AMENDMENTS.md`, `BS:<line>` = `BUILD_SPEC.md` (line numbers as of `b6a0b49`); the
amendments win wherever the two conflict. Repository files are cited as `path:line`. `<repo>` is the repository root,
`<scratch>` the session scratch directory outside the repository. No secret value, token, authorization code or cookie
value was printed or copied: persona passwords and client secrets were read with `ops_core.settings.read_secret` inside
the measuring process only, and the probes printed claim names, status codes and booleans.

Note on line numbers in the brief: revocation (a)–(c) is SA:540–553 (inside AM-20.7, heading SA:532); browser sessions
is SA:565; the error mapping is BUILD_SPEC §7 (BS:301), not §16 (§16 is the UI, BS:528; SA:38 and SA:48 supersede
parts of it). BUILD_SPEC §12 (model node) and §22 (Kubernetes, deferred whole by SA:41) carry no CSRF or idempotency
text; that text is in §7 (BS:264, BS:299), §9 (BS:350) and §13 (BS:466).

---

## 1. T11 verbatim, its acceptance-matrix rows, and related rows/tasks

### 1.1 T11 (`handoff/tasks.json:545-574`)

- **id/milestone/title:** `T11`, `M03`, "Keycloak login, server-side sessions and revocation". `status: "PLANNED"`,
  `external_approval_required: false`.
- **instructions:** "authlib code+PKCE with state in the server-side session store; opaque hashed session IDs; CSRF
  and origin checks; hand-written back-channel logout endpoint; admin-API enabled check on decision-class mutations;
  60 s membership sync."
- **depends_on:** `["T09", "T43"]` (both `DONE`).
- **requirement_ids:** `R011, R012, R013, R086`.
- **definition_of_done:**
  1. "Negative tests for state/nonce/iss/aud, CSRF, revoked membership."
  2. "Disabled user: next decision-class mutation 401; grants blocked within 60 s."
  3. "Back-channel logout token validation incl. jti replay."
- **review_notes:**
  1. "Admin-API check: 2 s timeout, cached service-account token, fail closed 503 retryable when Keycloak is down/slow.
     The 'grants blocked <=60 s' half of R086 is verified in T21."
  2. "Membership sync fails closed: grants refuse if the last successful sync is older than 120 s; a deleted user
     (admin API 404) maps to 401. Run the admin-API check before opening the DB transaction."
  3. "Back-channel logout: verify signature with an alg allowlist, exp, sid/sub, and a durable (Postgres) jti store;
     exempt the endpoint from CSRF/Idempotency-Key with a forged-token negative test."
  4. "Start a core logging redaction filter here (OIDC code, connection strings, tokens, handles) with a canary test;
     T28 extends it to telemetry."

### 1.2 Acceptance-matrix rows (`handoff/acceptance-matrix.json`), all `NOT_RUN` / `NOT_IMPLEMENTED_OR_NOT_TARGET_VERIFIED`, `blocking_for_v1: true`, owner `T11`

| id (line) | milestone / category | requirement | expected_evidence | suggested_test |
|---|---|---|---|---|
| R011 (:178) | M03 / identity | "OIDC validation rejects invalid token/callback context" | "Wrong issuer/audience/nonce/state/expiry/signature/algorithm and redirect targets fail." | `tests/acceptance/test_r011_oidc_validation_rejects_invalid_token_callback_c.py` |
| R012 (:193) | M03 / identity | "Sessions and CSRF protect browser mutations" | "Cross-origin or missing CSRF mutation fails; logout/expiry/rotation invalidate old session." | `tests/acceptance/test_r012_sessions_and_csrf_protect_browser_mutations.py` |
| R013 (:208) | M03 / security | "Current membership overrides old roles" | "Revoke membership while session/token remains otherwise valid; new protected operations fail." | `tests/acceptance/test_r013_current_membership_overrides_old_roles.py` |
| R086 (:1326) | M03 / security, `source: SPEC_AMENDMENTS.md` | "IdP disable and back-channel logout end application authority" | "Disabled user: next decision-class mutation 401, grants blocked within 60 s; back-channel logout destroys sessions; replayed logout token rejected." | `tests/acceptance/test_r086_idp_disable_and_back_channel_logout_end_applicat.py` |

`tests/acceptance/` does not exist; `pyproject.toml` `testpaths` follows Plan D ruling 26 (`tests/plan_<letter>/` for
unit tests, `tests/e2e/` for live cross-service tests; `docs/superpowers/plans/2026-10-08-first-slice-d-walking-skeleton.md:67`).
`handoff/ACCEPTANCE.md:18-19` repeats R012/R013 with the same evidence text.

### 1.3 Other rows and tasks that name sessions, CSRF, logout, the enabled check or the membership sync

| Item | Text (verbatim) | Relation to T11 |
|---|---|---|
| T21 review note 3 | "Verify R086's grant-blocking half (membership sync <=60 s)." | T21 depends on T11 |
| T21 DoD 2 | "Revocation or cancellation before grant blocks dispatch; a second grant for a run is impossible." | consumer of the sync |
| T27 instructions / DoD 2 | "access recheck per frame; identity change closes stream" / "Revocation stops the stream and redacts evidence; SSE cards pass." | SSE revocation is T27's |
| R054 (T27) | "Streaming access follows session and source revocation" — "Revoke user/source during stream; stop or redact before protected data is emitted again." | — |
| R014 (T26) | "Secrets never enter URLs or browser storage" — "Inspect browser requests/storage; no access tokens in URLs/localStorage or persisted debug data." | cookie/session shape feeds it |
| R059 (T28) | "Telemetry excludes credentials and sensitive reasoning" — "Seed canary secret in relevant error/input; collector/log export does not reveal it." | T11 note 4 starts the filter |
| R115 (T12) | "Errors use the safe schema and documented status mapping" — "Tests for 401/403/404/409/422/429/503 cases; no stack traces or unauthorized IDs." | T12 owns the mapping tests |
| R016 (T12) | "HTTP replay resolves once and conflicting body fails" | Idempotency-Key is T12's |
| T12 instructions | "scoped Idempotency-Key (24 h) … safe error schema and 401/403/404/409/422/429/503 mapping" | T11 does not depend on T12 |
| T13 review note 3 | "Lock order includes the asset-guard advisory lock and memberships (AM-12); also place jobs, invocation_context, model_permit, sessions." | lock order for `sessions` is T13's |
| T14 review note 3 | "The sweeper iterates tenants and sets app.tenant_id per tenant for expiry, outbox delivery and deadline escalation; sweeper_all covers memberships and jobs only (AM-20.5, 1.3.6)." | sweeper process shape |
| T09 review note 1 | "named cross-tenant sweeper policy for expire_proposals, membership sync, session lookup." | T09 `DONE` |
| T43 DoD / review note | "service account can read `enabled` and nothing more is granted." / "ops-view-users holds exactly realm-management/view-users (200 on GET user, 403 on PUT/POST users and GET clients, live-tested)" | `DONE` |
| T26 DoD 1-2 | "Playwright covers requester flow, independent approval, stale card …" / "No credentials in browser storage or URLs" | browser tests come with T26 |
| T05 review note | "Do not route host callers through host.docker.internal: it resolves to the LAN IP and cannot reach 127.0.0.1-bound ports." | applies to host callers (see §4.6 for container callers) |

---

## 2. Spec requirements

### 2.1 Revocation (a)–(c) and its bounds (AM-20.7 item 5, SA:540–553), verbatim

- SA:540: "**Revocation** (replaces the 1.1 wording):"
- SA:541: "(a) Back-channel logout: the API hosts a hand-written OIDC Back-Channel Logout endpoint (validates iss, aud,
  iat, jti, events; no nonce; jti replay cache) that destroys sessions."
- SA:542: "(b) **Every** decision, revision, cancel and manual-proposal mutation checks the user's enabled status through
  the Keycloak admin API."
  - SA:543: "It uses a local-only service account limited to `view-users`, whose secret is generated by the bootstrap."
  - SA:544: "The call has a 2 s timeout and uses a cached service-account token."
  - SA:545: "If Keycloak is down or slow, it **fails closed** with 503 `retryable`."
  - SA:546: "The user ID it checks is the token's `sub`, which T05 asserts equals the Keycloak user ID."
- SA:547: "(c) A membership sync job (every 60 s, run by the sweeper with the same `view-users` service account)
  deactivates memberships of disabled or deleted users, and `grant_execution` reads membership."
- Bounds, SA:548–551: "a disabled user's next decision-class mutation gets 401; a disabled requester or reviewer blocks
  grants within ≤60 s; session-only reads end on back-channel logout or idle expiry."
- SA:553: "Tested by R086."
- AM-20.7 summary, SA:534: "**revocation** (a)–(c) with fail-closed admin-API checks (R086) … **server-side sessions**".

Which mutations are "decision-class": SA:542 names exactly four kinds — decision, revision, cancel, manual-proposal.
Their routes (BS:274, BS:275, BS:276, BS:281): `POST /api/v1/runs/{id}/revisions`, `POST /api/v1/proposals/{id}/decisions`,
`POST /api/v1/runs/{id}/cancel`, `POST /api/v1/manual-proposals`; their functions (SA:454–458): `record_decision`,
`create_revision`, `create_manual_proposal`, `request_cancel` (all callers `api`). Admission (`POST …/messages`),
clarifications (BS:273), feedback (BS:282) and `POST /api/v1/conversations` are not in SA:542's list. The phrase
"decision-class mutation" itself appears at SA:549 and in T11 DoD 2; it is not defined further.

### 2.2 Browser sessions and browser identity

- SA:565 (AM-20.7 item 10), verbatim: "**Browser sessions are server-side.** A Postgres `sessions` table holds an opaque
  random ID (stored hashed) in an HttpOnly cookie. authlib's OIDC state lives in that store, not in Starlette's
  signed-cookie `SessionMiddleware`."
- SA:566 (item 11): "`X-Ops-Invocation` is a capability lookup key only. It is never trusted as identity and never
  logged."
- BS:348 (§9 Browser identity), verbatim: "Use OIDC authorization-code flow with PKCE through the backend. Use a
  maintained OIDC library, discovery metadata, exact redirect allowlists, issuer/audience/signature/expiry checks,
  nonce/state validation and algorithm allowlists. Keycloak is the local provider, not an application role database.
  Current tenant membership is read from application records."
- BS:350, verbatim: "Use an opaque `HttpOnly` browser session cookie, `Secure` under HTTPS, restrictive same-site
  behavior appropriate for the tested login flow, explicit CSRF tokens for mutations, origin verification, session
  rotation at login/privilege change, logout invalidation and idle/absolute expiration. Store provider tokens
  server-side, encrypted or otherwise protected through the deployment secret mechanism. Do not put credentials in
  localStorage, query strings, SSE URLs, screenshots or prompt context. Local development may use an explicitly
  localhost-only HTTP exception; cluster/cloud profiles require TLS and cannot accept the development exception."
- BS:352, verbatim: "Proposed session defaults: 30-minute idle timeout, 8-hour absolute limit, streaming permission
  recheck at least every 30 seconds and before emitting sensitive content. These are project settings, not claims of
  universal security sufficiency. Test session rotation and tenant switching; clear UI state and stop old streams on
  identity change."
- BS:229 (§6 records), the session row: "opaque random session ID stored hashed; subject, active tenant, expiry, last
  activity, CSRF secret; no browser-readable access tokens".
- BS:228, the membership row: "tenant_id; issuer, subject; scopes; active; permission_version; unique membership per
  identity/tenant".
- BS:72 (fixed choices): "Login | Local Keycloak as the default OIDC identity provider; backend-managed browser session.
  [S08]". BS:74: "Same-origin HTTP commands + SSE event replay." BS:625: "Build React static assets into a same-origin
  web/API gateway image or documented static-server container; avoid cross-origin auth complexity."
- BS:176: "A signing-valid JWT is not proof of current membership. Read the current application policy before protected
  operations. Inactive requester/reviewer status before execution invalidates the grant request."
- AM-01 (SA:74): `api/` is "FastAPI: sessions, admission, decisions, SSE, health"; BS:193 `api/` "# HTTP, sessions,
  CSRF, SSE, health".
- AM-40 state 8 (SA:632): "session expired / disconnected-then-reconnected snapshot"; SA:636: "State 8's reconnect
  assertion lands with SSE in T27."
- Clock rule (SA:157): "Every lease, expiry, freshness and deadline comparison uses `clock_timestamp()`, evaluated
  **after** the relevant row locks are acquired. Never use `now()`" (via `app.current_time()`, SA:158).

### 2.3 CSRF, origin, idempotency and the HTTP contract

- BS:264 (§7), verbatim: "Every mutation requires an authenticated current session, CSRF/origin protection in cookie
  mode, a bounded body, and `Idempotency-Key`. State-specific mutations include `expected_version` or expected proposal
  revision/hash. The server sets actor, tenant, roles, timestamps and authority fields; reject client attempts to supply
  them. UUIDs and unguessable keys are not access control."
- BS:268: "`GET /auth/login`, `GET /auth/callback`, `POST /auth/logout` | OIDC authorization-code flow, validated
  callback, backend session; secure logout/revocation". BS:269: "`GET /api/v1/me` | Current identity, active tenant,
  permitted UI capabilities; no secrets".
- BS:299: "Same key/body returns the same logical result; same key/different body returns 409."
- BS:466 (§13): "Decision input includes proposal ID, expected revision, payload hash, approve/reject and optional
  bounded reason; session identifies the reviewer. The server verifies that the reviewer is current, in scope, different
  from requester … Same idempotent replay returns its recorded result".
- BS:372: "disabled cross-origin access unless explicitly configured"; BS:374: threat tests must exercise "… token
  audience confusion … CSRF …"; BS:587: "API/session tests: issuer/session/CSRF/origin, deduplication, expected
  versions, projections, no unauthorized existence leaks."
- The spec does not name the CSRF pattern (double-submit vs synchroniser); BS:229 stores a "CSRF secret" on the session
  row, BS:350 says "explicit CSRF tokens for mutations, origin verification".
- The back-channel endpoint is exempt from CSRF and Idempotency-Key (T11 review note 3); no other exemption is written.
- `idempotency_request` (BS:244: "tenant, subject, route, key, body hash, accepted result identifiers; unique scoped
  key"; AM-20.2 SA:429: `api` sel, ins; `sweeper` del (expired)) does not exist yet; T12 creates it (Plan E ruling 2,
  `docs/superpowers/plans/2026-10-08-first-slice-e-roles-rls-definers.md:45`).

### 2.4 Error mapping (401/403/503)

- BS:301 (§7), verbatim: "Safe errors use `{code, message, retryable, request_id}`; no stack traces, raw queries,
  tokens, or unauthorized IDs. Use 401 for missing/expired identity, 404 for inaccessible resource existence, 403 for a
  known permitted resource with a disallowed operation, 409 for stale versions/key conflicts, 422 for shape/content
  limits, 429 for bounded capacity, and 503 for unavailable durable admission."
- BS:564 (§17): "Overload: bound queue and return clear 429/503 behavior."
- SA:545 / SA:549 / T11 note 2: Keycloak down or slow → 503 `retryable`; disabled user → 401; deleted user (admin API
  404) → 401.
- `schemas/error.schema.json` `code` enum: `UNAUTHENTICATED, FORBIDDEN, NOT_FOUND, VERSION_CONFLICT,
  IDEMPOTENCY_CONFLICT, INVALID_INPUT, RATE_LIMITED, UNAVAILABLE, ASSET_ACTION_UNRESOLVED, ASSET_INCIDENT_EXISTS,
  GRANT_EXISTS, SLOT_OCCUPIED, AUTHORITY_VIOLATION` (mirrored by `core/src/ops_core/contracts.py:421-436`). There is no
  CSRF-specific code; the spec does not say which status a failed CSRF/origin check returns.

### 2.5 AM-20 rows that touch T11

| Item | Text (SA line) |
|---|---|
| `sessions` grants | "`sessions` \| sel, ins, upd(`last_seen_at`, `revoked_at`), del \| — \| del (expired) \| — \| —" (SA:413) — `api` / `worker` / `sweeper` / `app_definer` / right-hand column |
| `tenants`, `memberships` grants | "sel \| sel \| sel, upd(`active`, `permission_version`, `synced_at`) \| sel \| — (seeded by `migrator` data migrations)" (SA:412) |
| only these grants | "Only these grants exist. Anything not listed is denied." (SA:408) |
| no RLS | "`run_directory`, `invocation_context`, `run_lease`, `sessions`, `idempotency_request`, `operator_resolutions`, `model_permit`, `tenants` and `app.test_clock` have **no RLS**; their grants (AM-20.2) are the control." (SA:523) |
| `memberships` under RLS | listed among the tenant tables with ENABLE + FORCE (SA:510) |
| `sweeper_all` | "`memberships` and `jobs` carry one extra policy, `sweeper_all FOR ALL TO sweeper USING (true)`, for the membership sync and the wake-up sweep. … These are the only policies besides `tenant_isolation`." (SA:520) |
| sweeper role | "Scheduler process (expiry, membership sync, wake-up sweep, outbox delivery); holds the Keycloak `view-users` service account for the membership sync" (SA:399) |
| `sync_memberships` | "`sync_memberships(payload)` \| `sweeper` \| the Keycloak sync result \| `memberships` FOR UPDATE \| Deactivates memberships of disabled or deleted users; records `synced_at` \| none" (SA:470) |
| sweeper job types | "`expire_proposals`, `sync_memberships`, `sweep_wakeups`, `deliver_outbox` \| Scheduler (sweeper role) \| Maintenance \| none \| n/a (no run lease)" (SA:346); dedup key "`name:<minute bucket>`", inserted by "`sweeper` scheduler" (SA:504) |
| definer rules | `SECURITY DEFINER`, owner `app_definer`, `SET search_path = app, pg_temp`, `SET app.tenant_id = ''`, REVOKE PUBLIC then GRANT to the listed callers in the same transaction, `set_config(…, true)`, raise `authority_violation` for a wrong `session_user` (SA:446) |
| identity trust anchor | `create_run`: "`tenant_id` from the authenticated session (the API is the identity trust anchor, as for `record_decision`)" (SA:450); `record_decision`: "reviewer identity = the API's authenticated `sub`" (SA:454) |
| grant gate | `grant_execution` … "requester and reviewer currently active" (SA:462) |
| lock order | "`asset guard advisory lock → run_lease → runs → messages → proposals → decisions → memberships → execution_grant → action_attempt → operator_resolutions → events → outbox`" (SA:188); `sessions` is not in it (T13 note 3 places it) |
| v1 scope | "**No tenant-administration surface.**" (SA:107); the BS §4 tenant-administrator row is superseded (SA:44) |

### 2.6 `resolve_identity` (Plan E ruling 4)

`docs/superpowers/plans/2026-10-08-first-slice-e-roles-rls-definers.md:47`, verbatim: "**Identity before tenant (Q4): a
24th definer function, `resolve_identity(issuer, subject)`, granted to `api` (T11's sweeper sync adds itself when it
has a caller), iterating `tenants` the way SA:520 prescribes for the sweeper.** `memberships` is under
`tenant_isolation` (SA:510) and SA:520 allows no further policy; `tenants` has no RLS (SA:523); so the function sets
`app.tenant_id` per tenant and collects the active rows for `(issuer, subject)`. O(tenants) per request, tenants are
few, and nothing new is granted. Proposed erratum (Task 9). Cost if wrong: T11's `sessions` stores the active tenant and
the function becomes a one-tenant lookup."

Related Plan E rulings: ruling 2 (`…:45`): "`sessions` (shape BS:229; T11 may alter it)"; ruling 23 (`…:65`): the
definer functions take no row lock on `memberships` ("a row lock needs UPDATE on at least one column and AM-20.2 gives
`app_definer` `sel`/`ins` only") and "the `memberships` race against T11's sync is recorded as T11's"; debt list
(`…:75`, `…:82`, `…:86`): "`sync_memberships` → T11", "`sessions` has the BUILD_SPEC §6 shape and no reader or writer →
T11". Plan D ruling 3 (`docs/superpowers/plans/2026-10-08-first-slice-d-walking-skeleton.md:44`): "This is not
throwaway: T11 adds the browser flow and sessions and widens `azp` to `ops-web`; the verifier and the membership lookup
stay."

Proposed erratum 25 (`SESSION_STATE.md:188`): "The sweeper's `del` without `sel` on `sessions` and `idempotency_request`
cannot run a `DELETE ... WHERE expires_at < ...` (spike section 3); flagged for T11/T12." Spike row 3
(`docs/superpowers/research/2026-10-08-plan-e-spike.md:13`): "A column UPDATE grant also needs SELECT on every column it
reads (WHERE, RHS)."

### 2.7 Versions (AM-30)

SA:583: "| authlib | 1.8.0 |" in "**Versions observed on 2026-10-06** (exact pins live in `uv.lock`)" (SA:575). Keycloak
"**26.8.x** (pinned image digest)" (SA:585). AGENTS.md: "Resolve actual library versions and hashes from official
sources; do not invent them".

### 2.8 Revoked membership mid-session; streams; logging

- R013 evidence (above): "Revoke membership while session/token remains otherwise valid; new protected operations
  fail." BS:176 and BS:348 ("Current tenant membership is read from application records").
- BS:423: "Membership/access changes invalidate relevant caches and future projections."
- BS:352: "session rotation at login/privilege change"; "Test session rotation and tenant switching; clear UI state and
  stop old streams on identity change."
- BS:520 (§15): "Recheck identity/access before replay and periodically while connected. A changed identity closes the
  old stream and clears old UI state." BS:560: "SSE … authorization recheck at most 30 seconds apart". T27 owns the
  stream (no SSE route exists today: `api/src/ops_api/app.py` has no `/stream`).
- SA:551: "session-only reads end on back-channel logout or idle expiry."
- Logging/redaction: T11 note 4 (OIDC code, connection strings, tokens, handles; canary test); SA:566 (`X-Ops-Invocation`
  "never logged"); BS:350 (no credentials in "screenshots or prompt context"); BS:572 ("Disable full prompt/source
  capture by default"); BS:202 lists `observability/   # instrumentation and redaction` in the §5 layout; R059 is T28's.
  AGENTS.md: "Keep secrets out of prompts, URLs, source, traces, screenshots and session notes."

---

## 3. The tree as it is (branch `plan-e`, `b6a0b49`)

### 3.1 `api/src/ops_api/app.py` (324 lines)

- Module docstring (`:1-7`): "Browser sessions, CSRF and Idempotency-Key are declared debt (T11/T12)."
- `bearer = HTTPBearer(auto_error=False)` (`:34`).
- `ApiError(status, code, message)` (`:37-42`); `safe()` builds `SafeError` with `retryable=status == 503` and adds
  `WWW-Authenticate: Bearer` on 401 (`:45-49`).
- `Verifier` protocol (`:57-71`): `ready`, `load_keys()`, `verify_async(token) -> Principal`.
- `Identity` (`:74-86`): `subject = UUID(principal.subject)`, `username` from `preferred_username`, `tenant_id` and
  `roles` from the membership; `require(role)` raises 403 `FORBIDDEN`.
- The identity dependency (`:109-125`): no credentials → 401 "a bearer token is required"; `TokenRejected` → 401
  "token rejected"; non-UUID `sub` → 401; `store.membership(issuer, subject)` is `None` → **403** "no active
  membership"; `issuer` is `settings.keycloak().issuer` (`:107`).
- Exception handlers (`:127-152`): `ApiError` → its status; `persistence.AuthorityViolation` → 503 "service
  misconfigured"; `st.Internal`, `PersistenceError`, `IllegalTransition`, `EventRuleViolation` → 503; `psycopg.Error`
  → 503 "database unavailable"; `RequestValidationError` → 422.
- Routes: `GET /health/live` (`:160`), `GET /health/ready` (`:164`), `GET /api/v1/me` (`:174`), **`POST
  /api/v1/conversations`** (`:183`, 201), **`POST /api/v1/conversations/{id}/messages`** (`:188`, 202, requires
  `requester`), `GET /api/v1/runs/{id}` (`:227`), `GET /api/v1/proposals/{id}` (`:244`), **`POST
  /api/v1/proposals/{id}/decisions`** (`:261`, the only decision-class route that exists), `GET
  /api/v1/runs/{id}/events` (`:294`). No `/auth/*`, revisions, cancel, manual-proposals or stream route exists.
- `production_app()` (`:311-324`): `TokenVerifier(issuer=kc.issuer, audience=env OPS_API_AUDIENCE default "ops-api",
  allowed_azp=frozenset({"ops-dev-direct"}), jwks_url=kc.jwks_url)`; store = `DbStore` over one connection as role
  `api`.
- `__main__.py:13-24`: uvicorn on `127.0.0.1:OPS_API_PORT` (default 8000), `log_level="warning"`, selector loop on win32.
- The app installs no middleware (no CORS, no session, no trusted-host).

### 3.2 `api/src/ops_api/store.py` (282 lines)

- `Membership(tenant_id, roles)` (`:43-48`). `check_reviewer` (`:79-84`): `reviewer` role required; reviewer ≠
  requester and ∉ `authored_by`, else `Forbidden`.
- `single_tenant(rows)` (`:87-93`): one tenant or `None`; `# TODO(T11): explicit tenant selection; until then a
  multi-tenant subject cannot act, and roles never merge.`
- `map_refusal` (`:96-104`): `NOT_REVIEWER`, `SELF_REVIEW`, `MEMBERSHIP_INACTIVE` → `Forbidden` (403).
- `DbStore.membership` (`:154-158`): `async with self.session.unit()` (no tenant) → `persistence.resolve_identity(conn,
  issuer=…, subject=…)` → `single_tenant`.
- `DbStore` holds **one** autocommit connection wrapped in `persistence.Session` (`:151-152`; Plan D ruling 24: a
  process-wide `asyncio.Lock` serialises units; "Pools arrive with T13", plan-d `:65`). Every request's identity
  lookup is one unit on that connection.

### 3.3 `core/src/ops_core/tokens.py` (216 lines)

- `TokenRejected` (`:29`), `UnknownSigningKey(TokenRejected)` (`:33`), `WrongAudience(TokenRejected)` (`:37-39`:
  "incident-sim turns this one into 403").
- `Principal(subject, azp, audiences, expires_at, claims)` with `claims` `repr=False` and a read-only mapping
  (`:42-49`, `:152-158`); `sid` is reachable as `principal.claims["sid"]` (no field).
- `TokenVerifier` (`:71-171`): JWKS fetched with `httpx2` (`:63-68`, 10 s timeout), keys filtered to `use == "sig"` and
  the pinned algorithms (`:99-106`), `algorithms=("RS256",)` default (`:79`), `jwt.decode(..., options={"require":
  ["exp", "iss", "aud", "sub"]})` (`:132-139`), `azp` ∈ `allowed_azp` else `WrongAudience` (`:147-149`); unknown `kid`
  → one refresh per 60 s cooldown (`:26`, `:160-171`). It does not require `iat`/`jti`, does not check `typ`, and
  accepts any token type that carries those claims.
- `WorkloadTokenSource` (`:185-216`): client-credentials token cached, refreshed 30 s before `expires_in`, guarded by an
  `asyncio.Lock`; posts with `httpx2`, 10 s timeout (`:177-182`). It is the existing "cached service-account token"
  shape (used today by the worker and mcp-write).

### 3.4 `core/src/ops_core/settings.py`

- `read_secret(name)` (`:51-61`) reads `OPS_SECRETS_DIR/<name>`; messages never name the path.
- `Keycloak(base_url, issuer)` with `jwks_url` (`:156-157`) and `token_url` (`:160-161`); no discovery, admin, logout
  or authorization URL property. `keycloak()` (`:164-167`): `OPS_KC_BASE_URL` default `http://localhost:18080`,
  `OPS_KC_ISSUER` default `{base}/realms/ops-dev`. `REALM = "ops-dev"` (`:21`).
- `Role.SWEEPER = "sweeper"` (`:106`); `app_postgres(role)` (`:132-135`) reads `postgres_<role>_password`.
- `Profile` `dev`/`test`/`demo` from `PROFILE` (`:84-98`).

### 3.5 `core/src/ops_core/privileges.py` (the AM-20 matrix as data)

- `memberships` (`:66-71`): `api` sel, `worker` sel, `sweeper` `Grant(sel=True, upd=("active", "permission_version",
  "synced_at"))`, `app_definer` sel.
- `sessions` (`:72-75`): `api` `Grant(sel=True, ins=True, upd=("last_seen_at", "revoked_at"), dele=True)`, `sweeper`
  `Grant(dele=True)`. No `app_definer` cell.
- `SWEEPER_ALL = ("memberships", "jobs")` (`:138`); `NO_RLS` includes `"sessions"` (`:139`).
- `DEFINER_FUNCTIONS` (`:148-163`): `"resolve_identity": ("text, uuid", ("api",))  # the sweeper's membership sync (T11)
  adds itself` (`:150`); `append_event` callers `api, worker, sweeper` (`:153`); `current_time` all runtime roles
  (`:149`). No `sync_memberships` entry. The module docstring (`:7-14`) says later tables' owners add their rows and
  each revision freezes its own copy of the cells (`grant_statements(..., revokees=...)`, `:186-216`).

### 3.6 `app.sessions` as revision 0002 created it (`migrations/app/versions/0002_roles_grants_rls.py:324-334`)

```
CREATE TABLE app.sessions ( session_sha256 text PRIMARY KEY, issuer text NOT NULL, subject uuid NOT NULL,
  tenant_id uuid NOT NULL REFERENCES app.tenants (tenant_id), csrf_secret_sha256 text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL,
  last_seen_at timestamptz NOT NULL DEFAULT now(), revoked_at timestamptz)
```

- Comment (`:307-308`): "the session store (T11 fills it)". Grants frozen in `GRANTS_0002["sessions"]` (`:67-70`).
- Measured as role `api` (§4.7): 0 rows; `relrowsecurity = false`, `relforcerowsecurity = false`; constraints
  `sessions_pkey PRIMARY KEY (session_sha256)` and `sessions_tenant_id_fkey`; no other index.
- Absent columns (relative to T11's text and §2): no `sid`, no OIDC `state`/`nonce`/PKCE verifier, no provider-token
  storage, no absolute-expiry column distinct from `expires_at`, no `permission_version` snapshot. The CSRF secret is
  stored only as a hash (`csrf_secret_sha256`).
- Column privileges measured (§4.7): `api` may UPDATE `last_seen_at`, `revoked_at` only (not `expires_at`, not
  `tenant_id`); `sweeper` has DELETE and **no SELECT**; `app_definer` has no privilege on `sessions`.
- No table exists for the back-channel `jti` replay store; AM-20.2 has no row for one (SA:406-435).

### 3.7 `app.memberships` (`migrations/app/versions/0001_walking_skeleton.py:41-50`, seed `:216-236`)

- Columns: `tenant_id uuid NOT NULL REFERENCES app.tenants`, `issuer text NOT NULL`, `subject uuid NOT NULL`, `role text
  NOT NULL CHECK (role IN ('requester', 'reviewer', 'reader'))`, `active boolean NOT NULL DEFAULT true`,
  `permission_version integer NOT NULL DEFAULT 1`, `synced_at timestamptz NOT NULL DEFAULT now()`; `PRIMARY KEY
  (tenant_id, issuer, subject, role)` — one row per role.
- Seed: two tenants and five persona rows from `data/seed-ids.json` (alex requester, sam reviewer, lee reader in alpha;
  riley requester, jordan reviewer in beta). The issuer is frozen at migration time: `issuer =
  os.environ.get("OPS_KC_ISSUER") or "http://localhost:18080/realms/ops-dev"` (`:219`), with the comment "Declared
  shortcut (SESSION_STATE debt, last line): frozen at migration time; T09's membership sync owns it." (`:217`).
- Measured (§4.7): alpha 3 rows, beta 2 rows, all `active`, `permission_version` 1, one issuer
  `http://localhost:18080/realms/ops-dev`, `synced_at` = the migration instant for every row (about 16 h before the
  probe). Nothing has written `synced_at` since.
- Readers of membership today: `resolve_identity` (`migrations/app/versions/0003_run_path_functions.py:383-399`: walks
  `tenants`, `set_config('app.tenant_id', …, true)` per tenant, returns `(tenant_id, role)` where `issuer = p_issuer AND
  subject = p_subject AND active`); `record_decision` (`0004_write_path_functions.py:203-206`: reviewer row with `role =
  'reviewer' AND active` in the tenant, else `NOT_REVIEWER`, no issuer filter); `grant_execution` (`0004…:293-300`:
  requester active and the decision's reviewer active as `reviewer`, else `MEMBERSHIP_INACTIVE`). No function reads
  `synced_at`; no 120 s staleness check exists anywhere.

### 3.8 Realm export `deploy/dev/keycloak/realm-ops-dev.json` (192 lines)

- Realm: `sslRequired: "none"` (`:5`), `accessTokenLifespan: 300` (`:6`); no `ssoSessionIdleTimeout`,
  `ssoSessionMaxLifespan`, `revokeRefreshToken` or other lifetime keys (Keycloak defaults apply; §4.4 measured
  `refresh_expires_in` 1800 and a `KEYCLOAK_SESSION` cookie `Max-Age=36000`).
- `ops-web` (`:15-28`): `publicClient: false` (confidential), secret placeholder `${OPS_KC_CLIENT_SECRET_OPS_WEB}`,
  `standardFlowEnabled: true`, implicit/direct/service-accounts `false`, `redirectUris: ["http://localhost:8000/auth/callback"]`,
  `webOrigins: ["http://localhost:8000"]`, `attributes: {"pkce.code.challenge.method": "S256",
  "post.logout.redirect.uris": "http://localhost:8000/"}`. No `frontchannelLogout` key, no
  `backchannel.logout.url`, no `backchannel.logout.session.required`, no protocol mappers (so no `ops-api` audience).
  `tests/plan_b/test_realm_template.py:98-105` pins standard flow on, direct grants off, confidential, PKCE S256, the
  exact redirect list and the post-logout URI.
- `ops-dev-direct` (`:96-115`): public, `directAccessGrantsEnabled: true`, description "dev-only: password grant for
  persona tests; never deployed outside the dev profile", hardcoded-audience mapper `ops-api` (access token only).
- `ops-view-users` (`:116-127`): confidential, service accounts only, secret `${OPS_KC_CLIENT_SECRET_OPS_VIEW_USERS}`,
  description "used by the API's fail-closed enabled check and the sweeper's membership sync (AM-20.7)"; its service
  account user holds `clientRoles: {"realm-management": ["view-users"]}` (`:185-190`).
- Users (`:129-184`): five personas with fixed `id` = `data/seed-ids.json` user IDs, `enabled: true`,
  `emailVerified: true`, one realm role each (informational), password placeholders `${OPS_KC_PERSONA_<NAME>_PASSWORD}`;
  no user attributes (no tenant).
- The realm is re-imported on every `bootstrap_dev.py up`; Keycloak keeps no volume (`docs/runbooks/dev-topology.md:27`,
  `:57`). Placeholders are resolved from variables `deploy/dev/keycloak/entrypoint.sh` exports from `/run/secrets`
  (`:4-14`).

### 3.9 `scripts/bootstrap_dev.py`, compose and topology

- `SECRET_NAMES` (`:26-48`) includes `kc_client_secret_ops_web` (`:30`), `kc_client_secret_ops_view_users` (`:36`), the
  five `kc_persona_*_password`, and `postgres_sweeper_password` (`:43`). `KC_HTTP_PORT = 18080` (`:51`).
- `compose.yaml:33` Keycloak `26.8.0` pinned by digest; `:39` port `127.0.0.1:${KC_HTTP_PORT}:8080`; `:43-44`
  `KC_HOSTNAME: "http://localhost:${KC_HTTP_PORT}"`, `KC_HOSTNAME_BACKCHANNEL_DYNAMIC: "true"`.
- `docs/runbooks/dev-topology.md:12-15`: host callers use `http://localhost:18080`; containers use
  `http://keycloak:8080`; `iss` is `http://localhost:18080/realms/ops-dev` for both; "Never route a host caller through
  `host.docker.internal`". `:43`: "`accessTokenLifespan: 300` keeps tokens short-lived so the window after a revocation
  stays small, alongside the AM-20.7 enabled-check and the ≤60 s membership sync." `:53`: view-users "gets 403 on user
  updates, user creation and client listing". `docs/runbooks/ollama-network.md:48`: "a container's connection to
  `host.docker.internal:11434` arrives at the host **from 127.0.0.1** … A listener bound to loopback is therefore still
  reachable from containers".
- `.env` keys: `OPS_SECRETS_DIR KC_HTTP_PORT PG_PORT MCP_READ_RESOURCE_URL MCP_WRITE_RESOURCE_URL OLLAMA_BASE_URL_HOST
  OLLAMA_BASE_URL_CONTAINER` (no API URL, no web origin).

### 3.10 What Plan B proved about the view-users account

`tests/plan_b/live/test_service_account.py:37-51` (live): client-credentials token for `ops-view-users`; `GET
/admin/realms/ops-dev/users/{alex}` → 200 with `enabled is True` and `id == alex`; `PUT users/{alex}` → 403; `GET
clients` → 403; `POST users` → 403. `:54-72`: the bootstrap admin's password grant → 400 (absent). `tests/plan_b/live/kc.py`
is stdlib-only (`urllib`), with `token_password` (`:38-43`), `token_client_credentials` (`:30-35`) and an unverified
`claims()` decoder (`:46-50`). `tests/plan_b/live/test_keycloak_tokens.py:57-61` asserts persona `sub` equals the seed
ID ("the join key to the seeded PostgreSQL rows").

### 3.11 How the API is driven today

- Unit: `tests/plan_d/test_api.py` uses a `StubVerifier` (`:45-62`) that maps a bearer string to a `Principal`
  (`azp="ops-dev-direct"`, `audiences=("ops-api",)`), and a fake store; `fastapi.testclient.TestClient`. A dual-tenant
  subject (`DUAL`, `:33-41`) pins "cannot act" (`test_multi_tenant_subject_cannot_act_and_roles_do_not_merge`, `:170`).
- Live: `tests/e2e/test_r105_walking_skeleton.py:91-107` mints persona tokens with `kc.token_password(…,
  "ops-dev-direct", "alex"|"sam", secret(...))` and sends `Authorization: Bearer`; a worker token at `/api/v1/me` → 401
  (`:106-107`). Plan D ruling 3 (plan-d `:44`) fixed this path: `aud ∋ "ops-api"`, `azp == "ops-dev-direct"`.
- `tests/plan_d/test_tokens.py:90`: a token with `azp="ops-web"` is refused by a worker-only MCP server.

### 3.12 Processes and the scheduler gap

- `scripts/skeleton.py:270-276` `PROCESSES`: incident-sim 8090, mcp-read 8081, mcp-write 8082, api 8000, worker 8070
  (health). No sweeper process; no top-level `sweeper/` directory; AM-01's directory table (SA:72-81) lists `api/`,
  `worker/`, `mcp-read/`, `mcp-write/`, `asset-sim/`, `incident-sim/`, `web/`, `core/` and no sweeper, while AM-20.1
  calls the sweeper a "Scheduler process" (SA:399) and ADR-0001 says "Each independently deployed process gets its own
  top-level directory" (`docs/adr/ADR-0001-deployable-units-as-top-level-directories.md:17`).
  `docs/ARCHITECTURE.md:62` gives the sweeper "DB role `sweeper`; Keycloak `view-users` service account … memberships
  (sync), outbox, expired sessions and idempotency rows".
- The `sweeper` role exists with its secret; `docs/runbooks/dev-topology.md:70`: "`sweeper` and `operator` are reserved
  for their later owners". Its grants (measured §4.7): SELECT on `memberships` plus column UPDATE on `active`,
  `permission_version`, `synced_at`; DELETE (no SELECT) on `sessions`; EXECUTE on `append_event` and `current_time`;
  no EXECUTE on `resolve_identity`.
- The worker is the only loop: `worker/src/ops_worker/main.py:28` `POLL_SECONDS = 0.5`; `run_forever` (`:40-61`) rotates
  tenants and calls `persistence.claim_job` per tenant; a health server runs beside it (`:66-80`, `:106-122`); `:86`
  `logging.basicConfig(...)` (the only logging configuration in the services).
- `persistence.claim_job` (`core/src/ops_core/persistence.py:469-490`) sets each tenant and claims under
  `tenant_isolation`; a tenant-less job (`tenant_id NULL`, allowed for sweeper jobs by `jobs_tenant_iff_run_check`,
  `0002…:229-236`) is invisible to the worker and visible to the sweeper through `sweeper_all`.
- `core/src/ops_core/jobs.py:37-47` already defines `JobType.SYNC_MEMBERSHIPS`; `:102-105` gives the four sweeper job
  types creator `("sweeper",)` and dedup shape `name:minute_bucket`.

### 3.13 Logging today

No `logging.Filter`, no redaction helper, no `logging.config` exists in `core`, `api`, `worker`, `mcp-read`, `mcp-write`,
`incident-sim` or `scripts` (grep for `Filter|addFilter|redact|basicConfig`: only `worker/src/ops_worker/main.py:86`).
Existing hygiene is local: `Principal.claims` `repr=False`; `Postgres.password` `repr=False`
(`settings.py:70`); `read_secret` messages omit paths; `tests/e2e/test_r105_walking_skeleton.py:105` binds responses
before asserting so pytest never prints a header.

---

## 4. Library and server facts (measured 2026-10-08)

Method: repository venv read-only (`--frozen`); authlib measured in a throw-away environment under `<scratch>` (never
the repository lock); Keycloak probed over HTTP at `http://localhost:18080` with scripts `<scratch>/probe_kc.py` and
`<scratch>/probe_login.py`; PostgreSQL probed as role `api` with `<scratch>/probe_db.py` (SELECT and
`has_*_privilege` only, transaction rolled back). Side effects outside the repository: the probes created Keycloak
SSO sessions for persona `alex` (direct grant twice, one `ops-web` login, then an RP logout of that login with its
refresh token; the direct-grant sessions expire on Keycloak's idle timeout), and one loopback listener ran for 25 s in
`<scratch>` for §4.6. No user, client or realm setting was changed; nothing was deleted.

### 4.1 Versions and what is locked

| Component | Fact |
|---|---|
| `authlib` | **not in `uv.lock`** (grep: no match in `uv.lock` or any `pyproject.toml`); `find_spec("authlib")` is None in the repo venv |
| `authlib==1.8.0` resolves | yes; requires `cryptography>=45.0.1`, `joserfc>=1.6.1`; resolved `joserfc 1.7.5`. With the locked `starlette 1.7.0`, `httpx2 2.13.1`, `cryptography 50.0.2` on Python 3.13.13, `authlib.integrations.starlette_client` and `authlib.integrations.httpx_client` both import |
| `joserfc` | not locked (new transitive dependency) |
| `httpx` (the original package) | not locked, not installed; authlib 1.8.0's `httpx_client/_compat.py` imports **`httpx2` first** and falls back to `httpx` with a deprecation warning |
| `itsdangerous` | not locked; `import starlette.middleware.sessions` fails (`ModuleNotFoundError: itsdangerous`) |
| `python-multipart` | locked 0.0.32, installed (needed for `request.form()`, i.e. a form-encoded `logout_token`) |
| starlette / FastAPI / uvicorn | 1.7.0 / 0.143.0 / 0.54.0 |
| PyJWT / cryptography / httpx2 | 2.15.1 / 50.0.2 / 2.13.1 |
| `api/pyproject.toml:6` | `["ops-core", "fastapi>=0.142,<1", "uvicorn>=0.54,<1"]`; `core/pyproject.toml:6` carries `pyjwt[crypto]`, `httpx2` |
| `.python-version` | 3.13 |

### 4.2 authlib 1.8.0 behaviour that bears on T11 (source read and measured)

- **State storage.** `StarletteAppMixin.save_authorize_data` and `StarletteOAuth2App.authorize_access_token` read and
  write `request.session` (`integrations/starlette_client/apps.py`). `StarletteIntegration.set_state_data` stores
  `{"data": …, "exp": now + 3600}` under key `_state_<name>_<state>` in that dict; with a `cache` object it stores the
  data in the cache and keeps a session-bound marker (`integration.py`). Starlette 1.7.0's `HTTPConnection.session`
  is `assert "session" in self.scope, "SessionMiddleware must be installed to access request.session"` followed by
  `self.scope["session"]` (measured with `inspect.getsource`): it reads whatever an ASGI middleware put in
  `scope["session"]`. `FrameworkIntegration.expires_in = 3600`.
- **State/PKCE/nonce generation.** `_create_oauth2_authorization_url` generates `code_verifier = generate_token(48)`
  when the client has `code_challenge_method`, and `nonce = generate_token(20)` when `openid` is in the scope; both go
  into the saved state data. A callback whose state is not found raises `MismatchingStateError`
  (`base_client/sync_app.py:263-265`).
- **ID-token validation.** `AsyncOpenIDMixin.parse_id_token` (default `leeway=120`) sets `claims_options = {"iss":
  {"values": [metadata["issuer"]]}}` when none is passed, takes the **algorithm list from discovery**
  (`id_token_signing_alg_values_supported`, falling back to `["RS256"]`), `strict_check_header=False`, and refetches the
  JWKS once on an unknown `kid`. Measured with `CodeIDToken` (`<scratch>`):
  - `aud="other"`, `azp="ops-web"`, `client_id="ops-web"`, default options → **ACCEPTED** (aud is checked only when
    `claims_options` carries `aud`; `validate_azp` requires `azp == client_id` when aud differs);
  - same token with `claims_options["aud"] = {"essential": True, "values": ["ops-web"]}` → REJECTED
    (`InvalidClaimError`);
  - wrong nonce → REJECTED; wrong iss → REJECTED; `exp` 200 s ago → REJECTED (`ExpiredTokenError`); `exp` 60 s ago →
    **ACCEPTED** (within the 120 s leeway).
- **Logout helpers.** `StarletteOAuth2App.logout_redirect` / `create_logout_url` build an RP-initiated logout URL from
  `end_session_endpoint` (`id_token_hint`, `post_logout_redirect_uri`, `state`). authlib has no back-channel logout
  receiver (T11 says "hand-written").
- `authlib.jose` import emits `AuthlibDeprecationWarning: authlib.jose module is deprecated, please use joserfc
  instead.`

### 4.3 Keycloak 26.8.0 discovery (`GET /realms/ops-dev/.well-known/openid-configuration`)

| Key | Value |
|---|---|
| `issuer` | `http://localhost:18080/realms/ops-dev` |
| `authorization_endpoint` | `…/protocol/openid-connect/auth` |
| `token_endpoint` | `…/protocol/openid-connect/token` |
| `userinfo_endpoint` | `…/protocol/openid-connect/userinfo` |
| `end_session_endpoint` | `…/protocol/openid-connect/logout` |
| `jwks_uri` | `…/protocol/openid-connect/certs` — keys: `RSA RS256 sig`, `RSA RSA-OAEP enc` |
| `backchannel_logout_supported` / `backchannel_logout_session_supported` | `true` / `true` |
| `frontchannel_logout_supported` / `…_session_supported` | `true` / `true` |
| `code_challenge_methods_supported` | `["plain", "S256"]` |
| `id_token_signing_alg_values_supported` | `PS384, RS384, EdDSA, ES384, HS256, HS512, ES256, RS256, HS384, ES512, PS256, PS512, RS512` |
| `authorization_response_iss_parameter_supported` | `true` |
| `token_endpoint_auth_methods_supported` | `private_key_jwt, client_secret_basic, client_secret_post, tls_client_auth, client_secret_jwt` |
| `revocation_endpoint` / `introspection_endpoint` | `…/revoke` / `…/token/introspect` |

### 4.4 Tokens actually issued (claim names and non-secret values only)

- **Direct grant (`ops-dev-direct`, alex, no scope):** reply keys `access_token, expires_in, not-before-policy,
  refresh_expires_in, refresh_token, scope, session_state, token_type`; `expires_in` 300, `refresh_expires_in` 1800,
  `scope` "email profile". Access token: `aud` `ops-api`, `azp` `ops-dev-direct`, `typ` `Bearer`, `sub` = seed ID,
  claims `acr, aud, azp, email, email_verified, exp, family_name, given_name, iat, iss, jti, name, preferred_username,
  realm_access, scope, sid, sub, typ` — **`sid` present**, no `session_state` claim. With `scope=openid` the reply adds
  an `id_token` (`aud` `ops-dev-direct`, `typ` `ID`, has `sid`, `at_hash`, 300 s).
- **Code + PKCE through `ops-web` (alex), driven with `httpx2` and no browser:** `GET /auth` → 200 HTML login page with
  cookies `AUTH_SESSION_ID` (`Path=/realms/ops-dev/; Secure; HttpOnly; SameSite=None`), `KC_AUTH_SESSION_HASH`
  (`Max-Age=60; Secure; SameSite=None`), `KC_RESTART` (`Secure; HttpOnly; SameSite=None`); the form `action` is
  `/realms/ops-dev/login-actions/authenticate` with query keys `client_data, client_id, execution, session_code,
  tab_id`; inputs `username, password, credentialId`. Posting the credentials with the three cookies sent as an explicit
  `Cookie` header → **302** to `http://localhost:8000/auth/callback` with query keys `code, iss, session_state, state`
  (`state` echoed, `iss` = the issuer) and new cookies `KEYCLOAK_IDENTITY` (`Secure; HttpOnly; SameSite=None`) and
  `KEYCLOAK_SESSION` (`Max-Age=36000; Secure; SameSite=None`). A first attempt that left cookie handling to the
  client's jar got **400** at the form post (cause not isolated; Keycloak marks every cookie `Secure` on plain-HTTP
  localhost). A second `/auth` with the SSO cookies → 302 with a code and no form.
- Code exchange with a **wrong `code_verifier`** → 400 `invalid_grant` "PKCE verification failed: Code mismatch", and
  the same code with the right verifier afterwards → 400 `invalid_grant` "Code not valid" (a failed exchange burns the
  code). A successful exchange then replayed → 400 `invalid_grant`.
- Successful exchange: reply keys `access_token, expires_in, id_token, not-before-policy, refresh_expires_in,
  refresh_token, scope, session_state, token_type`; `expires_in` 300, `refresh_expires_in` 1800, `scope` "openid email
  profile". **ID token:** `aud` `ops-web`, `azp` `ops-web`, `typ` `ID`, nonce matches, `sub` = seed ID, `sid` present,
  lifetime 300 s, claims `acr, at_hash, aud, auth_time, azp, email, email_verified, exp, family_name, given_name, iat,
  iss, jti, name, nonce, preferred_username, sid, sub, typ`. **Access token:** no `aud` claim, `azp` `ops-web`, same
  `sid` as the ID token, plus `allowed-origins` and `realm_access`. `GET /userinfo` with that access token → **401**
  (cause not isolated). `POST /logout` with `client_id`, `client_secret` and the `refresh_token` → 204.
- **`/auth` negatives (no login):** no `code_challenge` → 302 to the callback with `error=invalid_request`,
  `error_description` "Missing parameter: code_challenge_method", `iss`; `code_challenge_method=plain` → same with
  "Invalid parameter: code challenge method is not matching the configured one" (PKCE S256 is enforced);
  `redirect_uri=http://localhost:8000/evil` → **400** (no redirect); `redirect_uri=http://127.0.0.1:8000/auth/callback`
  → **400** (exact match; `127.0.0.1` ≠ `localhost`).

### 4.5 Admin REST API as `ops-view-users`

- Client-credentials token: `expires_in` 300, `refresh_expires_in` 0, no refresh token, `aud` `realm-management`.
- `GET /admin/realms/ops-dev/users/{alex}` → 200 in 10.5 ms (one sample), keys `access, createdTimestamp,
  disableableCredentialTypes, email, emailVerified, enabled, firstName, id, lastName, notBefore, requiredActions, totp,
  username`; `enabled` true.
- `GET …/users/{random UUID}` → **404** body `{"error":"User not found"}`; `GET …/users/not-a-uuid` → 404. (No user
  was deleted; a deleted user's ID behaves as an unknown ID — the 404 is what T11 note 2 maps to 401.)
- `GET …/users?briefRepresentation=true&max=100` → 200, 5 entries (the service-account user is not listed), each with
  `enabled`; `GET …/users/count` → 200 `5`.
- `GET …/users/{alex}/sessions` → 200 (5 open SSO sessions for alex at probe time, from tests and these probes).
- `GET …/clients?clientId=ops-web` → 403 (the account cannot read the `ops-web` client configuration; no admin login
  exists — the bootstrap admin is deleted — so the live client settings in §3.8 are known only from the export).
- `GET /admin/realms/ops-dev` → 200 but `ssoSessionIdleTimeout`, `ssoSessionMaxLifespan`, `accessTokenLifespan`,
  `revokeRefreshToken` are absent from the reply.
- `GET …/users/{alex}` with `Bearer invalid` → 401.

### 4.6 Can Keycloak (a container) reach the API on the host?

The API binds `127.0.0.1:8000` on the host (`api/src/ops_api/__main__.py:16`). Measured: inside
`ops-copilot-keycloak-1`, `host.docker.internal` resolves (to the runtime's internal host address), and a TCP request from the Keycloak
container to `host.docker.internal:18999`, where a throw-away listener was bound to **`127.0.0.1:18999` only** on the
host, returned `HTTP/1.0 200 OK`. So a back-channel logout URL of the form `http://host.docker.internal:<api port>/…`
is reachable from the Keycloak container to a loopback-bound host process on this machine (consistent with
`docs/runbooks/ollama-network.md:48`). The opposite direction stays as documented: host callers use `localhost:18080`
(`docs/runbooks/dev-topology.md:15`). Keycloak `KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true` affects Keycloak's own
back-channel URLs, not the client's logout URL.

### 4.7 Database facts (role `api`, read-only)

- `current_user = session_user = api`.
- `has_table_privilege`: api on sessions SELECT/INSERT/DELETE true; sweeper on sessions SELECT **false**, DELETE true;
  app_definer on sessions SELECT false; app_definer on memberships UPDATE **false**; sweeper on memberships SELECT true,
  table-level UPDATE false, column UPDATE on `active`, `permission_version`, `synced_at` true (`role`, `tenant_id`
  false); api on memberships UPDATE false.
- EXECUTE (callers among the six runtime roles): `resolve_identity(p_issuer text, p_subject uuid)` → `api` only;
  `append_event` → api, worker, sweeper; `current_time()` → all six. No `sync_memberships` function exists.
- `app.current_time()` equals `now()` within a second (dev profile, no test clock).

### 4.8 Starlette cookie API (locked 1.7.0)

`Response.set_cookie(key, value='', max_age=None, expires=None, path='/', domain=None, secure=False, httponly=False,
samesite='lax', partitioned=False)`; `Response.delete_cookie(key, path='/', domain=None, secure=False, httponly=False,
samesite='lax', partitioned=False)`. `samesite` accepts `'lax' | 'strict' | 'none' | None`. Starlette also ships
`starlette.middleware.cors` and `starlette.middleware.trustedhost` (both import); `starlette.middleware.sessions` does
not import without `itsdangerous`.

---

## 5. Open questions the planner must rule on

1. **authlib integration shape.** SA:565 forbids Starlette's signed-cookie `SessionMiddleware`, and `itsdangerous` is not
   locked (§4.1); authlib's Starlette client needs `request.session`, i.e. `scope["session"]` (§4.2). Options visible
   in the facts: an ASGI middleware that fills `scope["session"]` from `app.sessions` (pre-login state then needs a
   row before any identity exists — `sessions.subject`/`tenant_id` are `NOT NULL`), authlib's `cache=` hook (still
   wants a session-bound marker), or the lower-level `AsyncOAuth2Client`/`CodeIDToken` without the Starlette app class.
   Which, and where does the pre-login state (state, nonce, PKCE verifier, redirect) live?
2. **ID-token checks authlib does not do by default.** Pass `claims_options["aud"]` (measured: aud is otherwise
   unchecked, §4.2), narrow the algorithm list to `RS256` (discovery advertises HS256/HS384/HS512 among 13), and decide
   the leeway (default 120 s accepts a token expired 60 s ago). Also whether to require `typ == "ID"`, `azp == ops-web`
   and the `iss` authorization-response parameter (Keycloak sends it, §4.4).
3. **The `sessions` table changes.** BS:229 and T11 need fields 0002 does not have: `sid` (back-channel logout by
   session), pre-login OIDC state, provider tokens "stored server-side, encrypted or otherwise protected" (BS:350),
   absolute vs idle expiry, possibly `permission_version`. The CSRF secret is stored hashed, so the server cannot echo
   it back (a synchroniser token must be returned at creation or re-derived). New revision 0005 with which columns,
   and does `api` need UPDATE on more columns than AM-20.2's `last_seen_at`, `revoked_at` (e.g. rotation = insert new +
   revoke old)? Each extra grant is an erratum against SA:413.
4. **CSRF pattern.** Double-submit cookie vs synchroniser token in the session row (BS:229 "CSRF secret"; BS:350
   "explicit CSRF tokens for mutations, origin verification"). Which header name, how the browser obtains the token
   (`GET /api/v1/me`? a non-HttpOnly cookie?), what `Origin`/`Referer` rule (exact `http://localhost:8000`?), and which
   status/code a CSRF failure returns (no CSRF code exists in `schemas/error.schema.json`; 403 `FORBIDDEN`?).
5. **Cookie attributes.** Name, `HttpOnly` (required), `Secure` (BS:350: "under HTTPS"; dev is plain HTTP on localhost —
   Keycloak itself sets `Secure` on localhost HTTP, §4.4), `SameSite` (`lax` vs `strict`; the callback is a top-level
   cross-site GET from `localhost:18080` to `localhost:8000` — same site, different port), `Path`, `Max-Age` vs session
   cookie.
6. **Bearer path vs cookie path.** Plan D ruling 3 kept the `ops-dev-direct` bearer path and promised T11 "widens `azp`
   to `ops-web`". Keep both (bearer for live tests, cookie for the browser)? If both are present, which wins? Does the
   bearer path need CSRF (BS:264 says "CSRF/origin protection in cookie mode")? Does the bearer path also get the admin-API
   enabled check and the session-revocation semantics (a direct-grant token carries `sid`, §4.4)? The `ops-web` access
   token has no `aud` (§4.4), so "widening azp" on the existing verifier (which requires `aud`) would refuse it.
7. **Session lifetimes.** BS:352 proposes 30 min idle / 8 h absolute; Keycloak defaults measured as 1800 s idle and a
   36000 s SSO cookie; the realm export sets neither. Use BS:352 for the application session? Align the realm
   (`ssoSessionIdleTimeout`/`ssoSessionMaxLifespan`) or not? What does the app do when the provider's refresh token
   expires before the app session (store and refresh provider tokens at all)?
8. **Session rotation.** BS:350/R012 require rotation "at login/privilege change". What counts as a privilege change
   (membership role/tenant change detected by `permission_version`? tenant switch?), and how does it interact with the
   `api` grant (insert new row, set `revoked_at` on the old)?
9. **Tenant selection.** `single_tenant` refuses multi-tenant subjects (`store.py:91`, `TODO(T11)`); BS:229 stores an
   "active tenant"; BS:352 "tenant switching". Does T11 add a tenant switch, or keep "one tenant or refuse" and store
   the single tenant in the session? Is `resolve_identity` called per request (current membership, R013) or only at
   login (then how does R013's "new protected operations fail" hold)?
10. **Decision-class routes and the enabled check.** Only `POST /api/v1/proposals/{id}/decisions` exists today; revisions,
    cancel and manual proposals arrive with T21. Does T11 wire the check into the decision route only, plus a reusable
    dependency? Does it also cover the bearer path? Where exactly: before `store.decide` opens its unit (T11 note 2:
    "before opening the DB transaction") — the store's `proposal()` read happens first in `app.py:267`.
11. **Enabled-check client.** Reuse `WorkloadTokenSource` (cached client-credentials token, refresh 30 s before expiry;
    it has a 10 s timeout today) with a 2 s budget (SA:544)? Which errors are "down or slow" → 503 `retryable`
    (timeout, connect error, 5xx, 401 from a stale token) vs 401 (`enabled: false`, 404 deleted user)? Is a 403 from the
    admin API (misconfigured role) a 503? Single-flight token fetch under concurrency?
12. **Which process runs the 60 s sync.** No sweeper process or directory exists; AM-01's table has no `sweeper/` entry
    while ADR-0001 wants one directory per process; T13/T14 later need the same scheduler (reclaim, wake-ups, outbox,
    expiry). Options in the facts: a new `sweeper/` service (sixth process in `skeleton.py`, port?), or a loop inside
    the worker (but the worker connects as `worker`, which has no `memberships` UPDATE and no `sweeper_all`). Ruling also
    needed on whether the sync is a `jobs` row (`sync_memberships`, dedup `sync_memberships:<minute bucket>`, SA:504) or
    a plain timer.
13. **`sync_memberships` shape vs grants.** SA:470 makes it a definer function owned by `app_definer` that "deactivates
    memberships … records `synced_at`" under `memberships FOR UPDATE`, but `app_definer` holds only SELECT on
    `memberships` (SA:412; measured §4.7), so the function as specified cannot UPDATE. Meanwhile the sweeper holds the
    column UPDATE grant and `sweeper_all` directly. Choose: (a) direct sweeper UPDATEs (no function; erratum to SA:470),
    (b) the function plus an `app_definer` UPDATE grant on the three columns (erratum to SA:412), (c) the function
    iterating tenants like `resolve_identity`. The `payload` format (the admin API's user list with `enabled`, §4.5)
    and whether a user absent from the list counts as deleted also need fixing.
14. **What the sync writes.** Deactivate only (`active=false`), or also reactivate a re-enabled user? Bump
    `permission_version`? Write `synced_at` on every row each run (also the unchanged ones) so a staleness check can read
    it? Seeded rows carry one issuer; the sync matches Keycloak user `id` to `memberships.subject` — and the issuer?
15. **The 120 s fail-closed rule (T11 note 2).** "grants refuse if the last successful sync is older than 120 s": where
    is "last successful sync" stored (min `synced_at` of the two memberships involved? a separate one-row table, not in
    AM-20.2?), who checks it (`grant_execution`, which T21 owns per T11 note 1?), and what refusal code? Today every
    `synced_at` is the migration instant (~16 h old, §3.7), so enforcing the rule in `grant_execution` breaks the R105
    skeleton (`tests/e2e/test_r105_walking_skeleton.py`) unless a sweeper runs during live tests.
16. **Race between the sync and the gates.** Plan E ruling 23 left "the `memberships` race against T11's sync" to T11:
    the definer functions read `memberships` without a row lock (no UPDATE grant), while SA:462/SA:454 list
    `memberships FOR SHARE`. Accept the window (bounded by the 60 s sync), or add a lock path?
17. **Back-channel logout endpoint.** Path (BS:268 lists only `/auth/login`, `/auth/callback`, `/auth/logout`), method
    `POST` form `logout_token`; verification: reuse `TokenVerifier` (RS256 pinned, requires `exp/iss/aud/sub`; would
    reject a token without `sub`) or a separate verifier with `aud = ops-web`, `iat`, `jti`, `events`, no `nonce`,
    `sid` and/or `sub` (SA:541 + T11 note 3). What Keycloak 26.8 actually puts in its logout token (header `typ`,
    presence of `exp`, `sub`) was not measured here — the client has no back-channel URL yet. Destroy by `sid` (needs the
    column), by `sub` (all of the user's sessions), or both?
18. **The `jti` replay store.** "durable (Postgres) jti store" (T11 note 3): a new table (name, columns, retention,
    `UNIQUE(jti)` insert-or-conflict), which role writes it (`api`), who purges it (sweeper `del` needs `sel` too —
    erratum 25), and its AM-20.2 row (none exists; SA:408 says anything unlisted is denied). RLS: none (tenant-less,
    like `sessions`)?
19. **Realm changes for `ops-web`.** Add `backchannel.logout.url` (e.g. `http://host.docker.internal:8000/…`, reachable
    per §4.6; or a `${…}` placeholder resolved from the entrypoint), `backchannel.logout.session.required: "true"`,
    `frontchannelLogout: false`? An `ops-api`-style audience mapper or none (the API only consumes the ID token)?
    `tests/plan_b/test_realm_template.py:98-105` pins the current `ops-web` shape and must move with it. Changes apply
    on the next `bootstrap_dev.py up` (re-import), which also invalidates every Keycloak session.
20. **Callback/redirect URLs in dev.** The redirect allowlist is exactly `http://localhost:8000/auth/callback`
    (`127.0.0.1` is refused, §4.4); the browser and the API must therefore use the `localhost` host name. Is the API's
    public base URL a new `OPS_*` variable (none exists in `.env`, §3.9), and is the post-login landing page
    `http://localhost:8000/` before T26's web app exists?
21. **Logout (`POST /auth/logout`).** Local session revocation only, or also RP-initiated logout at Keycloak
    (`end_session_endpoint` with `id_token_hint`, measured 204 for refresh-token logout)? CSRF on it (it is a
    mutation)? Idempotency-Key on it (BS:264 says every mutation; T11 exempts only the back-channel endpoint, and T12
    owns Idempotency-Key)?
22. **Idempotency-Key in T11 at all.** T12 creates `idempotency_request` and the 24 h scope; T11 does not depend on T12.
    Do T11's new mutations (logout, any session endpoints) wait for T12, or ship without the key as declared debt?
23. **Revoked membership mid-session.** R013: membership revoked "while session/token remains otherwise valid; new
    protected operations fail". Per-request `resolve_identity` gives this today for every route (403 "no active
    membership"); keep 403 or move to 401 for a deactivated membership? Does a revoked membership also revoke the
    session row? Open SSE streams are T27's (no stream route exists); does T11 leave a hook (e.g. session/permission
    version) for T27's 30 s recheck?
24. **Disabled vs inactive mapping.** SA:549/T11 DoD 2 say a disabled user's next decision-class mutation gets **401**;
    `map_refusal` maps `MEMBERSHIP_INACTIVE`/`NOT_REVIEWER` to **403**, and `app.py:124` maps "no active membership" to
    **403**. Which path produces the 401 (the admin-API check before the transaction), and does a membership the sync
    deactivated still answer 403?
25. **Logging redaction filter (T11 note 4).** Placement: `core` (e.g. an `ops_core` logging module installed by every
    service entrypoint) or `api` only for now; what it matches (OIDC `code` and `state` query values, `Authorization`
    headers, JWT-shaped strings, `postgresql://` / `password=` conninfo, raw invocation handles, cookie values); and the
    canary test's shape. uvicorn's access log is at `warning` today (`__main__.py:16`), so request lines with
    `?code=` are not logged yet; the worker is the only process calling `basicConfig`.
26. **How live tests drive the browser flow.** Measured: the full code+PKCE login works with `httpx2` against the
    Keycloak form (§4.4) if cookies are sent explicitly; the alternative is to keep the direct-grant bearer path for
    most live tests and add one or two form-driven login tests. Which, and where (`tests/e2e/`, `OPS_LIVE=1`)? How do
    live tests disable a user and produce a back-channel logout without an admin account (the view-users account
    cannot write; the bootstrap admin is deleted)? A test-only admin client in the dev realm would be a new Keycloak
    credential.
27. **Host-process configuration.** New settings the API needs (client secret `kc_client_secret_ops_web`, view-users
    secret, public base URL, cookie name, lifetimes) and their `OPS_*` names; whether `scripts/skeleton.py` gains a
    sweeper entry and port (current ports 8000/8070/8081/8082/8090).

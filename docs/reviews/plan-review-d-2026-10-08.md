# Adversarial review of Plan D (the walking skeleton, T08): rounds 1–2 (2026-10-08)

**Reviewed:** `docs/superpowers/plans/2026-10-08-first-slice-d-walking-skeleton.md` before execution. The plan was
written from a fact sheet (`docs/superpowers/research/2026-10-08-plan-d-inputs.md`, 102 cited requirements, 21 open
questions) and a measured library spike (`…plan-d-spike.md`) run against the live dev stack before any plan code
existed.

**Method:** the same two-critic gauntlet as Plans A–C — a static critic cross-checking every claim against the spec,
the existing code and the libraries (measured in a scratch environment), and a builder executing all nine tasks on a
throwaway worktree against the live Keycloak and PostgreSQL, with the shared databases cleaned afterwards.

**Outcome:** round 1 — static: 7 Blocking, 12 Important, 17 Minor; builder: EXECUTABLE WITH FIXES, 20 workarounds (8 Blocking). The worst defects were not library misreadings but transactions: connections opened without autocommit turned every unit of work into a savepoint inside a transaction a bare SELECT had left open, so mcp-write never committed a grant and incident-sim answered COMMITTED for keys that vanished at restart, while the end-to-end test passed. Round 2 (after the first fix commit) — static: 0 Blocking, 4 Important; builder: 1 Blocking (an MCP error escaping the client's context arrives inside an exception group), 6 workarounds, every round-1 reproduction gone. Round 3 (after the second fix commit) — READY TO EXECUTE: 0 Blocking, 0 Important, 9 Minor, folded into a third fix commit. Four plan commits in all; the final plan has 27 rulings and eleven declared shortcuts.

The reports below are the reviewers' text, unedited except that machine-local paths are replaced by placeholders.

---

## Round 1 — static critic

# Plan D static critic, round 1

Plan: `docs/superpowers/plans/2026-10-08-first-slice-d-walking-skeleton.md` at `plan-d` HEAD `10e7c4a` (5,332 lines).
Critic stance: every claim is UNPROVEN until evidence is shown. `P:<n>` = plan line, `SA:`/`BS:` = spec line.

## Method and evidence base

- **Scratch workspace** (outside the repo): the plan's 40 code blocks were extracted verbatim into
  `<scratch>` beside copies of the real `core/src/ops_core`,
  `schemas/`, `data/`, `tests/plan_b`, `scripts/`. A second copy (`ws\`) applies only the fixes the plan itself tells
  the executor to make (add `import time` P:1785, add `UTC` P:2101, drop the `type: ignore` and add `load_keys` to the
  Protocol P:2245, `UndefinedTable` P:2304, incident `version_table_schema=None` P:815, the mcp-write import list
  P:3440).
- **Scratch venv** `%LOCALAPPDATA%\ops-critic-venv` (Python 3.13): mcp 2.3.0, fastapi **0.143.0** (what `>=0.142,<1`
  resolves today; the spike measured 0.142.4), starlette 1.7.0, uvicorn 0.54.0, psycopg 3.3.6, pyjwt 2.15.1, httpx2
  2.13.1, alembic 1.20.0, sqlalchemy 2.1.4, pytest 9.1.1, **pytest-asyncio 1.4.0** (latest today), mypy 1.20.2 and
  ruff 0.16.10 (the repo's locked versions), pydantic 2.13.5.
- **Measured (executed)**: the plan's 62 unit tests; mypy strict over the six member trees; ruff check and
  ruff format over every new file; jsonschema (Draft 2020-12 + FormatChecker) over envelopes, events and search rows;
  `require_transition` for every transition the plan performs; uvicorn's loop choice on Windows; psycopg transaction
  nesting and parameter typing **against the live dev Postgres, read-only** (SELECT/SHOW/catalog queries, BEGIN/SAVEPOINT
  with no writes); pytest's failure output with a header dict; `uv run` child survival on Windows.
- **Reasoned from library source (not executed)**: Alembic version-table creation order (read-only rule), pytest-asyncio
  loop/policy wiring, MCP DNS-rebinding defaults.
- Nothing was written to either database, the repository, the lockfile or the stack. No token or secret value was
  printed.

Observation of the live stack (read-only): schema `app` (15 tables), `public.alembic_version = 0001_walking_skeleton` in
`ops` and in `incident`, role `incident`, **8 unclaimed jobs and 11 tenants (2 seeded)** already exist — someone (the
builder critic) has run the plan's migrations and live tests. Note the `ops` version table is in `public`, not `app`
(see B2).

---

## Lens A — Spec compliance

**A1. Transitions (measured).** Every `persistence.transition(...)`/`create_run` the plan performs passes
`require_transition`: ∅→QUEUED create_run (P:1098); QUEUED→RETRIEVING, RETRIEVING→DRAFTING/FAILED/INSUFFICIENT_EVIDENCE
transition_run (P:4691, 4702, 4706, 4710); DRAFTING→AWAITING_APPROVAL freeze_proposal (P:4735); AWAITING_APPROVAL→
APPROVED / REJECTED(rejected) record_decision (P:4013, 4022); APPROVED→EXECUTING grant_execution (P:3241);
EXECUTING|OUTCOME_UNKNOWN→SUCCEEDED, FAILED(rejected|aborted_no_commit), ESCALATED(conflict) record_outcome (P:3268-3281);
EXECUTING→OUTCOME_UNKNOWN mark_unknown (P:3294). PROVEN.

**A2. Event types/sources (measured).** All 15 events the plan can emit (P:49 plus failure paths) validate through
`ops_core.outcomes.Event` and `schemas/event.schema.json`. Only `record_outcome` writes `source=destination`
(P:3270-3284). No type outside AM-14. PROVEN.

**A3. Envelope rules (measured).** `outcome_envelope` for SUCCEEDED/FAILED_NO_COMMIT/UNKNOWN/CONFLICT and the error
envelope validate against `tool-result.schema.json`; `ok` only wraps SUCCEEDED (P:3346-3352, SA:351-353). Search rows
validate against `evidence.schema.json` too. PROVEN.

**A4. No UPDATE on append-only tables** in service code (run_state_history, action_attempt_state, events are insert-only).
PROVEN by reading every SQL statement. But a test DELETEs from `run_state_history` (P:2873, Minor M8).

**A5. Authority boundaries.** Model sees no tool (drafting.py takes request+evidence only, P:4447-4472); the worker never
calls incident-sim; mcp-read has no write path in code. PROVEN in code. **But SA:229 / BS:472 ("commit before destination
I/O") is violated at runtime by B6**, and SA:268's destination receipt can be issued for an uncommitted key (B6).

**A6. Debt list completeness — DENOUNCED (I3, I9, M13).** Shortcuts in the plan's code that are on no debt line:
- `grant_execution` does not re-read current requester/reviewer membership nor `cancel_requested` (BS:472: "read current
  requester/reviewer membership ... enforce expiry/freshness/cancellation"; SA:462 lock list includes `memberships FOR
  SHARE`); `mark_sent` does not re-check `cancel_requested` and the dispatch deadline under the `runs` lock (SA:463). The
  existing line covers only "asset guard or expiry → T12/T21".
- Per-service unit tests live in root `tests/plan_d/`, not in each service's `tests/` (SA:70; ADR-0001 "Each has its own
  pyproject.toml, Dockerfile, entrypoint, tests/ and a README.md"). Not a ruling, not debt.
- Handles are never revoked when the job ends, and resolution ignores run state / attempt state (SA:338 "Allowed tools are
  derived from type plus run state plus attempt state"); only "raw handle not hashed" is listed.
- No bounded request body in the API (BS:264 "a bounded body"); the new debt line names only sessions, CSRF, Idempotency-Key.
- Runtime role is a Postgres **superuser** (measured `rolsuper=true` for `ops`), which the "single owner DB role" line
  understates (see I12).

**A7. Rulings.** Rulings 1-21 are presented as rulings where the spec is open. Checked against unambiguous lines:
- Ruling 9 / P:50 "recomputes `canonical_sha256(payload)`" vs SA:268 "recomputes sha256 over the received bytes": the plan
  hashes the re-canonicalised parse, not the received bytes. Equivalent for a canonical sender; Minor M15.
- Ruling 11 404-vs-403 consistent with BS:466/SA:539. PROVEN by the (fixed) unit test.
- P:33 says riley is pinned; the test uses jordan (P:3778-3781). Minor (M3).
- `GET /api/v1/proposals/{id}` (P:3593) is not in BS:266-283's endpoint table and is not stated as a ruling. Minor (M16).
- T10 DoD says "worker/API tokens get 403" at incident-sim; the base the plan builds returns 401 for every rejected token
  (P:2193-2195, P:5238). Minor (M17).

**A8. Not-debt items.** Client-credentials tokens (P:3399, P:4851), iss/aud/azp/exp/signature in all resource servers
(P:1719-1732), `action_key` ON CONFLICT at READ COMMITTED (P:2058-2061), second-persona decision (P:3887-3892), transitions
through the table (A1). PROVEN in code; runtime proof blocked by B1/B3/B4/B6.

## Lens B — Contract consistency with existing code

**B-1. Strict models vs Python-mode validation — DENOUNCED → Blocking B3.** `IncidentRequest` is `strict=True` with
`action_id: UUID` (P:2153-2157) and is validated with `model_validate(parsed_dict)` (P:2216). Measured:
`Input should be an instance of UUID [type=is_instance_of, input_value='00000000-...-000000000007', input_type=str]`;
`model_validate_json` accepts the same body.

**B-2. `Event` raises pydantic `ValidationError`, not `EventRuleViolation` — Blocking B5.** `outcomes.py`'s own comment:
"EventRuleViolation is a ValueError: a ValidationError". Measured: application-sourced `action.confirmed` →
`pydantic_core.ValidationError`, `isinstance(e, EventRuleViolation) is False`. P:1385 expects `EventRuleViolation`.

**B-3. Everything else checked (measured or by reading):** `MessageContext.hours`, `DecisionRequest` fields,
`SafeError`/`ErrorCode` members used (UNAUTHENTICATED, FORBIDDEN, NOT_FOUND, VERSION_CONFLICT, SLOT_OCCUPIED,
INVALID_INPUT, UNAVAILABLE) all exist; `dedup_key` parts typed correctly for INVESTIGATE (run_id UUID, revision 1) and
EXECUTE (proposal_id UUID); `JOB_RULES[...].allowed_tools`, `server_for`; `ActionOutcome` invariants for all four outcomes;
`Receipt`/`Tombstone` via `model_validate_json`; `outcome_from_destination(state, sent=True, cancel_requested=False)`;
`ProposalPayload.canonical_dict()`, `Proposal`, `RunManifest(model_route=FAKE, model_digest=None)`. All PROVEN by the
62 unit tests passing after B3/B4 fixes.

**B-4. SQL vs DDL.** Every INSERT/SELECT column in persistence, keys, execution (incl. the LATERAL join P:3194-3196), api
store and worker handlers matches the Task 2 DDL (read line by line). `uuid[]` from a Python list: measured
`list[UUID]` → `uuid[]`; `list[str]` → unknown type (server infers `uuid[]` from the target column), so `[ALEX]` (str) in
P:3508 works. Partial unique index name in `exc.diag.constraint_name` (P:3966): reasoned (PostgreSQL reports the index
name for a unique-index violation), not measured (no writes allowed).

**B-5. Server timezone** measured `Etc/UTC`, so timestamptz values arrive with a zero offset and `ProposalPayload._utc`
accepts them. The plan relies on this silently (Minor M14).

## Lens C — Library semantics

**C1. uvicorn on Windows — DENOUNCED → Blocking B1.** `uvicorn/loops/asyncio.py` (0.54.0):
`if sys.platform == "win32" and not use_subprocess: return asyncio.ProactorEventLoop`. Measured with `uvicorn.run(...)`:
lifespan loop `ProactorEventLoop`, then `psycopg.InterfaceError: Psycopg cannot use the 'ProactorEventLoop' to run in
async mode`. The spike's statement (spike:677, "Proactor only when use_subprocess") is inverted, and the plan relies on it
for api (P:4276), incident-sim (P:2258), mcp-read (P:2789), mcp-write (P:3436).

**C2. psycopg transaction nesting — DENOUNCED → Blocking B6 and B7.** Measured live (read-only):
- outermost `async with conn.transaction()` → `savepoint_name == ''`, status IDLE after exit (it COMMITs);
- bare `execute` on a non-autocommit connection → INTRANS; a following `transaction()` gets `savepoint_name '_pg3_1'`
  and the connection is still INTRANS after the block (nothing committed);
- explicit nesting → savepoint `_pg3_2`.

**C3. FastAPI + `from __future__ import annotations` + local `Who` — DENOUNCED → Blocking B4.** Measured (FastAPI
0.143.0): `RequestValidationError ... {'loc': ('query', 'who'), 'msg': 'Field required'}` on `/api/v1/me`; with the
future import removed the 6 tests pass. The spike never measured a function-local alias.

**C4. Alembic `version_table_schema="app"` — DENOUNCED (reasoned from source) → Blocking B2.** Alembic 1.20.0
`runtime/migration.py:597-599`: `heads = self.get_current_heads(); if not self.as_sql and not heads and not dont_mutate:
self._ensure_version_table()` runs **before** the loop that executes revision 0001 (`CREATE SCHEMA app`), and
`_ensure_version_table` is `self._version.create(self.connection, checkfirst=True)` = `CREATE TABLE app.alembic_version`.
On a fresh database that fails (schema does not exist). Not executed (read-only). Corroboration: the live `ops` database's
version table is in `public`.

**C5. MCP SDK 2.3.0 (measured, PROVEN):** `Tool.from_function` + `arg_model` subclass with `extra="forbid"` (extra
`tenant_id` → `is_error`); `Annotated[int, Field(ge=1, le=8)]` → `minimum`/`maximum`; `Client(server)` in-process with
`tools=[...]`; TypedDict return → `structured_content`; `get_access_token()` is None in-process; `UUID` arg →
`format: uuid`. DNS-rebinding: `streamable_http_app(host="127.0.0.1")` default enables protection with
`allowed_hosts=["127.0.0.1:*","localhost:*","[::1]:*"]` (server.py:1164-1167) — fine for host processes.
**But mypy rejects `AuthSettings(issuer_url=<str>)`** (I1) — P:2793 note (c) is wrong for the type checker.

**C6. PyJWT 2.15.1 (measured, PROVEN):** `PyJWKSet.from_dict`, unknown kid → `KeyError` (caught), `RSAAlgorithm.to_jwk(
as_dict=True)`, `jwt.decode(key.key, options={"require": [...]})`, missing `sub` → rejected, HS256 confusion rejected,
refresh-once on unknown kid. 16 tests pass (plan says 18, M1).

**C7. pytest-asyncio 1.4.0 (reasoned + measured warning):** strict mode default; `Runner(loop_factory=None)` uses the
policy set in `tests/e2e/conftest.py`, so live tests get a Selector loop. It emits `PytestDeprecationWarning:
asyncio_default_fixture_loop_scope is unset` (measured "1 warning") — set it in `[tool.pytest.ini_options]` (M9).

**C8. `uv run` children (measured):** a child spawned by a script under `uv run` survives uv's exit on this machine, so
`skeleton.py up` leaving processes running works.

## Lens D — Test design

**D1. Live tests commit their writes — Blocking B7.** P:1425 claims "the fixture rolls back at the end, so the live
database keeps only the migration's rows". False: each test's first statement is an outermost `transaction()`, which
commits (C2). Consequences:
- Each `new_run` commits an unclaimed `investigate` job; `test_jobs_dedup_and_single_claim` (P:1400-1405) claims the two
  *globally oldest* jobs, not its own.
- **Task 8 Step 4 fails deterministically**: `test_worker_live` (P:4938-4940) commits a run, then `claim_job` returns the
  oldest unclaimed job (a Task 2 or Task 6 leftover), so `job["run_id"] == run` fails. Live DB right now: 8 unclaimed jobs.
- `test_mcp_write_live` (P:3529-3552) commits an APPROVED run with an unclaimed `execute` job, then rolls back the grant.
  In Task 9 the skeleton's real worker claims it and mcp-write creates a **second incident for that proposal with a new
  action_id** (the earlier key is in the incident DB, the grant row is gone).
- The session-scoped `skeleton` fixture (P:5140-5149) keeps the real worker polling while `test_tokens_live` and
  `test_worker_live` run (alphabetical order), so the worker races the test for its job.

**D2. The live write test cannot catch B6.** `test_mcp_write_live` resolves the handle with a bare SELECT (P:3532) so the
whole grant/SENT/RESOLVED sequence runs as savepoints in one open transaction, asserts in the same session, then rolls
back (P:3552). It passes whether or not anything commits before the POST (I6).

**D3. Vacuity.** `test_skeleton_evidence` passes when `reports/skeleton/` is absent (measured: collected and passed with
no directory) — as required, but it checks only `eyJ`/`Bearer`/`secret` (I8). `test_persistence_pure` case
`({"job_type": "execute"}, Server.WRITE, ..., GET_INCIDENT_RECEIPT)` "execute ≠ recover" (P:508) is rejected by the
server-column check, not the allowlist (M12).

**D4. Timing.** All waits are bounded (`wait_for` 45 s, P:5183; `Skeleton.start` 90 s, P:5073). PROVEN.

**D5. `scripts/check.py` after each task — DENOUNCED (I1, I2).** Predicted RED from Task 1 (ruff format would rewrite
`settings.py`), Task 2 (mypy `no-any-return` P:1080; format; I001 in `skeleton.py`), Task 4 (mypy Protocol; B008; 3
failing tests), Task 5-6 (mypy), Task 7 (4 failing tests; mypy), Task 8-9 (ruff). Details under I1/I2.

**D6. Counts.** Collected: settings 5, persistence_pure 9, tokens 16 (plan 18, P:1790), incident_sim 8, mcp_read 5,
mcp_write 8 (plan 9, P:3445), api 6, worker 4, skeleton_evidence 1. Baseline 411 collected = 381 + 30 matches P:432.

## Lens E — Security and boundaries

- **Token in failure output — I7.** Measured: pytest's assertion rewriting prints
  `where <Resp> = get('/api/v1/me', headers={'Authorization': 'Bearer eyJ...'})`. P:5204, P:5238, P:1816, P:1822 (and
  `alex[...]`/`worker[...]` passed inside asserted calls) would print live JWTs on failure, against P:20 ("no secret in
  ... test assertion message") and Plan B's own precedent (`tests/plan_b/test_evidence.py` comment).
- **Raw handle**: never logged (worker logs job ids and `McpCallFailed` text only; `HandleRejected` messages carry no
  handle — unit-tested P:516-520). PROVEN.
- **Persona audience change**: Plan B static test gains `audiences(d) == {"ops-api"}`; no other realm test pins
  `ops-dev-direct`'s mappers (read). Live persona test only adds an assertion. PROVEN statically; re-import not run.
  Side effect: Step 9 rewrites `reports/bootstrap/keycloak-claims.txt` (persona `aud` appears), which Step 10's `git add`
  omits (M5).
- **`incident` role**: measured `has_schema_privilege('incident','app','USAGE') = false` but
  `has_database_privilege('incident','ops','CONNECT') = true` (PUBLIC default); the plan's live test only checks from the
  incident database (P:2298-2304). The application side connects as superuser `ops`, which can open `incident` and write
  `action_key` — the "only mcp-write calls incident-sim" boundary is held by code, not credentials. Declare it (I12).
- **404 vs 403**: cross-tenant → 404, same-tenant wrong role/self → 403 (P:4226-4236). PROVEN by the (fixed) unit test.
- **`validate_token_resource=False`**: safe because `TokenVerifier` enforces `aud ∋ resource URL` itself (P:1719-1726).
  PROVEN by unit tests.
- **JWKS refresh** on every unknown `kid` is unthrottled (P:1738-1746): a request stream with random kids becomes a
  stream of JWKS fetches (M10).
- **Evidence file** (P:5202-5242): ids, states, hashes, evidence refs; no token. PROVEN by reading.
- **Secrets**: `ensure_incident_role` passes the password as a bind parameter to `set_config` and lets the server quote it
  (P:934-946, measured approach in the spike); SQLAlchemy URL is never rendered. PROVEN by reading.

## Lens F — Plan hygiene

- Code blocks that need after-the-fact edits: `import time` (P:1785), `UTC` (P:2101), the `type: ignore` line then a note
  to remove it (P:2182, P:2245), `InsufficientPrivilege` then a note (P:2298, P:2304), the incident `env.py` written as a
  question ("`version_table_schema="incident"`? No —", P:815), Task 2 Files line "gains `files`? No —" (P:444). An
  executor copying blocks verbatim gets broken files (M6).
- mcp-write server "Imports as in mcp-read plus ..." (P:3440): copying mcp-read's imports brings
  `from ops_mcp_read import procedures` — a cross-member import that `tests/plan_a/test_layout.py::test_no_cross_member_imports`
  fails — plus F401 `field`/`Annotated`/`Literal`/`Field` and F811 `UUID` (measured with ruff) (M7).
- Task 9 appends a block that starts with imports (P:5016-5023) to an existing module → E402 if pasted as shown (M7).
- Interfaces drift: Task 9 says `Skeleton.logs_dir`, code uses module `LOGS` (P:5009 vs P:5043); Task 2 says it consumes
  `ACTIVE_STATES`, migration hard-codes the list (P:447 vs P:605) (M11).
- Debt addition 8 (P:76) duplicates existing SESSION_STATE.md:161 "raw handle not hashed → T09/T15" (M11).
- Coverage/Review-focus claims not backed (I5): P:32 "the e2e test's replay step" — none; P:34 "the worker's token at
  incident-sim" and "a persona token at either MCP server" — neither tested for incident-sim/mcp-write; P:36 "and the e2e
  test" — no conflict call in R105; P:5321 "the e2e history assertion" — R105 has none.
- Task 1 commit order (debt before code) is right: Step 1 commits `SESSION_STATE.md` alone. PROVEN.
- `git add` lists include every created file (checked per task) except the Plan B evidence side effect (M5).

---

## Consolidated findings

### Blocking (7)

**B1. The four uvicorn services cannot start on the Windows dev machine.** P:2258, P:2789, P:3436, P:4276 call
`uvicorn.run(app, ...)`; uvicorn 0.54 picks `ProactorEventLoop` there and psycopg async refuses it in every lifespan.
`skeleton.py up`/the e2e fixture never reach ready; R105 cannot run. The plan inherits the inverted claim from spike:677.
*Fix:* run every service like the worker: `server = uvicorn.Server(uvicorn.Config(app, host=..., port=..., log_level=...))`
and `asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)` on win32 (or `uvicorn.Config(loop=...)` with a
selector factory); correct spike:677 before it is committed as authority (Task 1 commits the research files).
*Verified:* uvicorn source + `uvicorn.run` probe printed `ProactorEventLoop` then psycopg `InterfaceError`.

**B2. First `skeleton.py migrate` on a fresh database fails.** P:572 `version_table_schema="app"`: Alembic creates
`app.alembic_version` before revision 0001's `CREATE SCHEMA app`. *Fix:* `version_table_schema=None` for the app tree too
(as P:815 already does for incident), or create the schema in `env.py` before `run_migrations`. *Verified:* Alembic 1.20.0
`runtime/migration.py:534-599` (reasoned, not executed — read-only rule); the live DB's version table sits in `public`.

**B3. incident-sim answers 422 to every valid incident request.** P:2216 `IncidentRequest.model_validate(parsed)` on a
strict model refuses UUID text. Task 4 Step 4 fails (3/8: replay, conflict, lookup). *Fix:* keep `parse_json_strict` as the
duplicate-key/float gate, then `IncidentRequest.model_validate_json(raw)`. *Verified:* measured error text; with the fix
8/8 pass.

**B4. Every authenticated API route returns 422.** P:4056 `from __future__ import annotations` makes the annotation
`"Who"` a string FastAPI cannot resolve (it is local to `create_app`, P:4139), so `who` becomes a required query
parameter; even a missing token yields 422, not 401. Task 7 Step 3 fails (4/6). *Fix:* drop the future import from
`ops_api/app.py` (or define the dependency and alias at module level). *Verified:* FastAPI 0.143.0 error
`loc ('query','who')`; without the import 6/6 pass.

**B5. Task 2's live event test fails.** P:1385 expects `EventRuleViolation`; `Event(...)` raises pydantic
`ValidationError` (the validator wraps it). *Fix:* `pytest.raises(ValidationError)` with a `match`, or have
`append_event` call `event_rules_ok` before building `Event` so callers see `EventRuleViolation`. *Verified:* measured
exception type.

**B6. Nothing mcp-write or incident-sim writes is ever committed (SA:229, BS:472 violated).** Both connect with
`autocommit=False` (P:3396, P:2242). mcp-write's tool resolves the handle with a bare SELECT (P:3369 → P:1219), so the
connection is INTRANS and `grant_execution`/`mark_sent`/`record_outcome`'s `transaction()` blocks become savepoints: SENT
is not committed before the POST, the `runs` row lock is held forever, and the API never sees EXECUTING/SUCCEEDED (R105
times out). incident-sim's `/health/ready` (P:2206, polled by `Skeleton.start`) and `keys.commit`'s post-block `lookup`
(P:2072) do the same, so every later key/incident is a savepoint while 200 COMMITTED receipts go back — a receipt with
no durable destination commit. *Fix:* connect both with `autocommit=True` and wrap every unit of work (including
`resolve_handle`, readiness probes and lookups) in `transaction()`, which then issues real BEGIN/COMMIT; add an assertion
that `conn.info.transaction_status is IDLE` after each tool call/request in a unit or live test. *Verified:* psycopg
behaviour measured live, read-only (`_pg3_1` savepoint after a bare execute, status stays INTRANS).

**B7. Live tests leave committed rows that break later tests, and Task 8's live test fails as written.** P:1425's
rollback claim is false (outermost `transaction()` commits). Leftover unclaimed jobs make `test_worker_live`'s
`claim_job` return another run's job (P:4938-4940 assertion fails); `test_mcp_write_live` leaves an APPROVED run whose
execute job the skeleton worker later executes, creating a second incident for an old proposal; the session-scoped
skeleton worker races `test_worker_live`. *Fix:* run each live test inside a transaction that is rolled back
(raise `psycopg.Rollback` at the end of the block, or `autocommit=False` with the first statement outside a block and an
explicit rollback — and never call `commit()`); where a second process must see rows (Tasks 5, 6, 8), delete them in
`finally` or claim with a test-only `WHERE run_id = %s`; tear the skeleton down in a module-scoped fixture of the R105
module. *Verified:* psycopg outer-block commit measured; live DB currently holds 8 unclaimed jobs and 9 test tenants.

### Important (12)

**I1. mypy strict: 13 errors with the plan's code** (measured, after the plan's own fixes): P:1080 `no-any-return`
(`version` is `Any`); P:3272/3279/3284 `**common` (`dict[str, UUID]`) checked against `occurred_at: datetime | None`; P:2240
`TokenVerifier` vs Protocol `ready: bool` ("expected settable variable, got read-only attribute"); P:4094-4099 api
`Verifier` is a plain class (`empty-body` on `verify_async`, `arg-type` at P:4256); P:2673 / mcp-write copy nominal
`Verifier` (`arg-type` at P:2784, P:3431); P:2743, P:3382 `AuthSettings(issuer_url=str)` (`AnyHttpUrl` expected). *Fix:*
`version: int = ...`; `common: dict[str, Any]` or explicit kwargs; every `Verifier` a `Protocol` with
`@property def ready(self) -> bool: ...`; `AnyHttpUrl(issuer)`. *Verified:* with exactly these changes mypy reports
"Success: no issues found in 34 source files" and the 62 tests still pass.

**I2. ruff: 41 check errors and 31 files to reformat**, beginning with Task 1's `settings.py`; the plan never runs
`ruff format`/`ruff check --fix`. Not auto-fixable: B008 `Depends(caller)` defaults (P:2212, P:2227 — use
`Annotated[Principal, Depends(caller)]`), SIM117 nested `async with` (P:2854, P:2867, P:4613), RUF059 unused unpacked
names (P:2845, P:3530, P:4936, P:3751), RUF100 `noqa: BLE001` (P:4824, P:4828; and `noqa: S310` P:5061 — S310 is not
enabled), F401 (`uuid4` P:2819, `pytest` P:5170). *Fix:* add `uv run ruff format <paths> && uv run ruff check --fix <paths>`
before every `check.py` and fix the rest in the blocks. *Verified:* ruff 0.16.10 with the repo's settings (defaults +
`line-length=120`) on the extracted files.

**I3. Undeclared shortcuts in the final gate.** `grant_execution` (P:3216-3249) skips the current-membership and cancel
re-checks BS:472/SA:462 require; `mark_sent` (P:3252-3258) skips SA:463's cancel/deadline re-check under the `runs` lock.
Debt list covers only asset guard/expiry. *Fix:* add a debt line ("grant re-reads no membership; no cancel re-check in
grant/mark_sent → T09/T21/T22") or implement the membership re-check (one SELECT). *Verified:* reading spec and code.

**I4. One connection shared by concurrent requests** (api P:4260, incident-sim P:2179-2180, mcp-write P:3396). Two
concurrent requests interleave `transaction()` blocks on one connection, so one request's work becomes a savepoint inside
the other's transaction (C2), commits or rolls back with it, or trips psycopg's transaction-stack checks. The sequential
e2e never shows it. BS:70: "document each adapter's connection lifecycle". *Fix:* `psycopg_pool.AsyncConnectionPool`
(one connection per unit of work) or a per-process `asyncio.Lock` around each unit, and say which in the module
docstring. *Verified:* reasoned from C2 measurements.

**I5. Review-focus and coverage claims that no test backs** (P:32, P:34, P:36, P:5321-5323): no replay step and no
CONFLICT call in R105; the worker's token at incident-sim and a persona token / mcp-read token at mcp-write are never
tried; SA:558 ("missing aud, wrong aud, browser token") is live-tested for mcp-read only. *Fix:* add those negative calls to
the R105 test (each asserting 401 / `MCPError` and no `action_id` in the body) and a second `create_incident` through
mcp-write with a fresh execute handle asserting the same `action_id` and one incident row. *Verified:* reading every test.

**I6. The live write test cannot detect commit-after-I/O** (P:3529-3552; D2). *Fix:* run it on an IDLE connection and
assert from a second connection (or from the incident-sim handler stub) that the attempt is `SENT` before the POST
arrives. *Verified:* reasoned from C2.

**I7. Live JWTs printed on assertion failure** (P:5204, P:5238, P:1816, P:1822). *Fix:* bind the response first
(`r = c.get(...)`; `assert r.status_code == 401`), never put a token-bearing expression inside an `assert`. *Verified:*
measured pytest output with a dummy token.

**I8. `test_skeleton_evidence` is not Plan B's rule** although P:20 says it is applied: no JWT regex, no comparison with
the real secret values. *Fix:* generalise `tests/plan_b/test_evidence.py` over `reports/bootstrap` and `reports/skeleton`.
*Verified:* reading both tests.

**I9. Per-service unit tests outside the service directories** (P:24 vs SA:70, ADR-0001). *Fix:* either put them in
`<service>/tests/` (add those paths to `testpaths`) or record a ruling/debt line. *Verified:* reading.

**I10. Wrong expected counts** (P:1790 "18 passed" → 16; P:3445 "9 passed" → 8). An executor told to match counts will
chase a phantom. *Verified:* collection in scratch.

**I11. The research file to be committed as authority contains the uvicorn error** (spike:677) and the plan's conftest
comment repeats the spike's framing (P:1253). Correct it in the same commit (Task 1) so later plans do not re-inherit it.
*Verified:* C1.

**I12. Runtime runs as a Postgres superuser; `incident` can CONNECT to `ops`.** The debt line "single owner DB role"
does not say superuser (measured `rolsuper = true`), which also lets every app process open the `incident` database.
*Fix:* say so in the debt line (→ T09), and either `REVOKE CONNECT ON DATABASE ops FROM PUBLIC` in revision 1 or record
it. *Verified:* catalog queries, read-only.

### Minor (17)

- **M1** Count drift (folded into I10).
- **M2** `grant_execution`'s replay returns the existing grant without checking the `proposal_id` argument (P:3220-3222).
- **M3** Review focus 2 names riley; the test uses jordan (P:33 vs P:3778).
- **M4** Worker sends the whole message (≤4000 chars) as `query` (max 500, P:4697-4698); a long message fails the run.
  Truncate or derive the query.
- **M5** Step 9 rewrites `reports/bootstrap/keycloak-claims.txt`; Step 10 does not add it (dirty tree). R105 evidence is
  rewritten with a new timestamp on every live run (P:5202, P:5242).
- **M6** Code blocks that require post-hoc edits (Lens F list).
- **M7** mcp-write "imports as in mcp-read" (cross-member import, F401/F811) and Task 9's mid-file imports (E402).
- **M8** `test_mcp_read_live` DELETEs from `run_state_history` (P:2873), an append-only audit table (SA:388); it will
  break under T09 grants.
- **M9** Set `asyncio_default_fixture_loop_scope = "function"` (pytest-asyncio 1.4.0 deprecation warning, measured).
- **M10** Unthrottled JWKS refresh on unknown `kid` (P:1738-1746).
- **M11** Interfaces drift (`Skeleton.logs_dir`, `ACTIVE_STATES`) and the duplicated debt line (P:76 vs
  SESSION_STATE.md:161).
- **M12** `test_persistence_pure` "execute ≠ recover" case passes for a different reason (P:508); give it `server: "write"`.
- **M13** Handles never revoked at job end; resolution ignores run/attempt state (SA:338); no bounded body (BS:264) —
  add to the debt list.
- **M14** Proposal building depends on the server `TimeZone` being UTC (measured `Etc/UTC`); set `timezone=UTC` in the
  conninfo options so the `_utc` check never depends on server config. The membership `issuer` is frozen at migration time
  (P:793) and `data/seed-ids.json` is read by relative path (P:791).
- **M15** Destination hashes the re-canonicalised payload, not the received bytes (P:2219 vs SA:268).
- **M16** `GET /api/v1/proposals/{id}` is not in BS:266-283 and is not a ruling. `freeze_allowed(intent)` (SA:453) is not
  called. `MODEL_MODE` silently defaults to `fake` when unset (P:4849; R130 spirit) — require it.
- **M17** incident-sim returns 401 for a well-signed wrong-audience token; T10's DoD expects 403. `Skeleton.start` never
  closes the log file handles (P:5077).

## Declined to judge

- Whether the full live suite passes once the Blocking items are fixed: not run (read-only; the builder critic owns live
  writes).
- Alembic's first-run failure (B2) was reasoned from source, not executed on a scratch database.
- `exc.diag.constraint_name == "runs_one_active_per_conversation"` for the partial unique index: standard PostgreSQL
  behaviour, not measured (needs an INSERT).
- SQLAlchemy `op.bulk_insert` of `str` into `uuid` columns: not measured; the live DB's 5 memberships suggest it worked
  for whoever migrated it.
- Keycloak realm re-import (Task 1 Step 9) and the Plan B live suite after the mapper change: not run.
- Windows `os.kill(pid, SIGTERM)` in `down` and `Popen.terminate` in `stop`: not measured (they map to TerminateProcess;
  hard kill, no lifespan shutdown — acceptable for the skeleton, not verified).
- `docs/PROJECT_HISTORY.md`, `STATUS.md`, `README.md` wording in Task 9: content not yet written.

---

## Round 1 — builder dry run

# Plan D builder critic — round 1 (dry execution of Tasks 1–9)

Plan: `docs/superpowers/plans/2026-10-08-first-slice-d-walking-skeleton.md` at `10e7c4a` (branch `plan-d`).
Worktree (detached, kept): `<scratch>`
Executed 2026-10-08 05:34–06:03 local (UTC-7), probes and cleanup until ~06:15.

## Verdict: EXECUTABLE WITH FIXES

All nine tasks run to the end and the R105 e2e reaches `SUCCEEDED` with the nine events in order. That took 20 labelled
workarounds. **8 are Blocking**: a step fails as written and cannot continue without a code change. Three findings
matter most:

1. **Blocking.** The plan's e2e path cannot pass on the Windows dev machine without W18 and W19. W18 is needed because
   uvicorn picks the Proactor loop, which psycopg async refuses. W19 is needed because mcp-write never commits.
2. **Severe, undetected by the plan's tests.** incident-sim never commits a key (W20). Its single non-autocommit
   connection is left in an implicit transaction by `/health/ready`, so every `keys.commit` becomes a SAVEPOINT. The
   app DB records `SUCCEEDED` with a receipt that disappears when incident-sim stops.
3. **Reproduced deterministically.** The worker wedges forever while reporting `ready` (Risky R1). Its health endpoint
   and its poll loop share one connection. Concurrent `/health/ready` calls leave that connection "idle in
   transaction", and from then on every claim and transition the worker makes is invisible to other connections.

Counts: **Blocking 8 · Misleading 24 · Risky 13.**

## Summary table (gates)

| Task | Wall clock | check.py after task (with workarounds) | Live |
|---|---|---|---|
| baseline | — | 381 passed, 30 skipped, GREEN | — |
| 1 | 05:34:52–05:39:09 (4.3 min) | 386 passed, 30 skipped, GREEN (RED as written) | plan_b live 9 passed in 33.62s |
| 2 | 05:39:41–05:41:42 (2.0 min) | 395 passed, 35 skipped, GREEN (RED as written) | 5 passed after W2/W3; ungated 5 skipped |
| 3 | 05:41:52–05:43:15 (1.4 min) | 411 passed, 36 skipped, 1 warning, GREEN (RED as written) | 1 passed |
| 4 | 05:43:33–05:46:46 (3.2 min) | 419 passed, 37 skipped, GREEN (RED as written) | 1 passed |
| 5 | 05:46:56–05:49:01 (2.1 min) | 424 passed, 38 skipped, GREEN (RED as written) | 1 passed after W11 |
| 6 | 05:49:22–05:51:24 (2.0 min) | 432 passed, 39 skipped, GREEN (RED as written) | 1 passed |
| 7 | 05:51:35–05:53:10 (1.6 min) | 438 passed, 39 skipped, GREEN (RED as written) | (none in plan) |
| 8 | 05:53:22–05:55:06 (1.7 min) | 442 passed, 40 skipped, GREEN (RED as written) | 1 passed after W16 |
| 9 | 05:55:36–06:02:23 (6.8 min) | 443 passed, 41 skipped, 1 warning, GREEN (first run RED: stale mypy cache) | e2e 11 passed in 23.33s; gate 20 passed in 56.09s |

No task's `check.py` was GREEN as transcribed. Every task needed at least one ruff, ruff-format or mypy-strict fix:
ruff 0.16.10's default rule set includes I, B, SIM and RUF, and the plan's code is not ruff-formatted.

`verify_handoff.py --reference-code --manifest --contracts` exited 0 after Task 2 and after Task 9.

Final live gate:

```
OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e tests/plan_b/live -q -p no:cacheprovider
20 passed in 56.09s
```

Final `check.py`: `443 passed, 41 skipped, 1 warning in 28.17s` / `CHECK: GREEN`.

### `uv lock` resolution (Task 1)

`Resolved 64 packages`:

| Package | Version |
|---|---|
| mcp | 2.3.0 |
| fastapi | **0.143.0** (the plan's "Resolved versions" says 0.142.4) |
| starlette | 1.7.0 |
| uvicorn | 0.54.0 |
| psycopg | 3.3.6 (+ psycopg-binary 3.3.6) |
| sqlalchemy | 2.1.4 |
| alembic | 1.20.0 |
| pyjwt | 2.15.1 |
| httpx2 | 2.13.1 |
| cryptography | 50.0.2 |
| pytest-asyncio | 1.4.0 (written as `pytest-asyncio>=1.4.0`, no `<2` cap) |
| ruff (locked) | 0.16.10 |

The `uv.lock` diff is 701+/7-. The removals are `requires-dist` rewrites plus a `python_full_version < '3.15'`
resolution-marker line, so it is not "additions only".

### R105 evidence (gate run, `reports/skeleton/r105-walking-skeleton.txt`)

```
R105 walking skeleton — 2026-10-08T13:02:51Z
run_id=cc6af45a-728f-4bb0-9f50-d5fd4cb13959 accepted status=QUEUED
proposal_id=ecd843a4-29b6-479a-bdaa-c92976aa15d7 revision=1 payload_sha256=7b5037f496d34338c1e191e2029c302d2c811ef0d17bc99e210b907feab6d4fc evidence=['ALPHA-TRIAGE:v1:scope']
state=SUCCEEDED state_version=7 action_id=73bfe90a-63e7-4a92-bed8-ffc119915d07 incident_id=INC-000030
events=run.accepted,tool.started,tool.completed,explanation.ready,proposal.ready,approval.recorded,action.granted,action.dispatched,action.confirmed
```

## Workarounds (graded)

| # | Task | Grade | What I changed | Why the plan was wrong |
|---|---|---|---|---|
| W1 | 1 | Misleading | `ruff format` on settings.py | `conninfo()`'s `make_conninfo(...)` is not ruff-formatted, so check.py is RED (Expected GREEN). |
| W2 | 2 | **Blocking** | `migrations/app/env.py` uses `version_table_schema=None` | `skeleton.py migrate` fails with `sqlalchemy.exc.ProgrammingError: (psycopg.errors.InvalidSchemaName) schema "app" does not exist / CREATE TABLE app.alembic_version`. Alembic creates its version table before revision 1 creates schema `app`. The plan noticed this for incident only. `ensure_incident_role` had already created role `incident`. |
| W3 | 2 | **Blocking** | `persistence.append_event` calls `outcomes.event_rules_ok(type, source, payload)` before `Event(...)` | `test_events_are_gap_free_and_rule_checked` expects `EventRuleViolation`, but `Event(...)` raises `pydantic_core.ValidationError` ("Value error, action.confirmed comes only from record_outcome with source=destination"). The model validator wraps the error. |
| W4 | 2 | Misleading | `ruff check --fix` + `ruff format` | I001 in skeleton.py; 7 files not formatted. |
| W5 | 2 | Misleading | `version = int(row["state_version"]) + 1` | `core\src\ops_core\persistence.py:89: error: Returning Any from function declared to return "int"  [no-any-return]` |
| W6 | 3 | Misleading | ruff fix + format | I001 (tokens.py; the plan says "add `import time`" without a place), I001 in test_tokens_live.py, format ×3. |
| W7 | 4 | **Blocking** | Keep `parse_json_strict(raw)` as the duplicate/float guard, then `IncidentRequest.model_validate_json(raw)` | Every valid `POST /internal/incidents` returns 422 (3 of 8 unit tests fail). `ConfigDict(strict=True)` plus `model_validate(dict)` refuses a str UUID: "action_id Input should be an instance of UUID [type=is_instance_of, input_value='00000000-…-000000000007', input_type=str]". |
| W8 | 4 | Misleading | pyproject `[tool.ruff.lint.flake8-bugbear] extend-immutable-calls = ["fastapi.Depends"]` | B008 ×2 on `Depends(caller)` defaults. My first attempt, `Annotated[..., Depends(caller)]`, broke routing because of `from __future__ import annotations` plus a closure-local dependency (5 tests failed). That is the same trap as W14. |
| W9 | 4 | Misleading | `Verifier(Protocol)` with `@property ready` | `app.py:137: error: Argument 1 to "create_app" has incompatible type "TokenVerifier"; expected "Verifier"  [arg-type]` |
| W10 | 4 | Misleading | ruff fix + format | I001 ×3, format ×3. |
| W11 | 5 | **Blocking** | `new_run(conn, tenant_id=None)` can reuse a seeded tenant; the mcp-read live test passes ALPHA | Live test `IndexError` at `results[0]`. `new_run` creates a random tenant with no corpus. The failed test left its committed rows behind, because its cleanup runs after the assert. |
| W12 | 5 | Misleading | `AnyHttpUrl(issuer)` / `AnyHttpUrl(resource_url)`; Verifier→Protocol; nested `async with` combined; unused import and variable removed | `server.py:162: error: Argument "issuer_url" to "AuthSettings" has incompatible type "str"; expected "AnyHttpUrl"  [arg-type]` (and the same for `resource_server_url`); `server.py:203` State verifier arg-type; ruff F401, RUF059, SIM117 ×2, I001 ×2. Plan note (c) ("str validated in the spike") holds at runtime, not under mypy strict. |
| W13 | 6 | Misleading | `append_event(..., tenant_id=…, conversation_id=…, run_id=…)` passed explicitly; AnyHttpUrl; Protocol; unused imports removed | `execution.py:128/135/140: error: Argument 5 to "append_event" has incompatible type "**dict[str, UUID]"; expected "datetime | None"  [arg-type]`. The plan's note claims mypy accepts it. Also F401 ×4 (field, Annotated, Literal, Field), dragged in by "imports as in mcp-read"; RUF059 ×2; I001 ×4. |
| W14 | 7 | **Blocking** | Removed `from __future__ import annotations` from `api/src/ops_api/app.py` | 4 of 6 unit tests fail: every authenticated endpoint returns 422. `who: Who`, where `Who` is a closure-local `Annotated` alias, is a string FastAPI cannot resolve, so `who` becomes a required query parameter. |
| W15 | 7 | Misleading | Verifier→Protocol; `c, _ = api` | `app.py:52: error: Missing return statement  [empty-body]`; `app.py:215` arg-type; RUF059; I001 ×3. |
| W16 | 8 | **Blocking** | Before claiming, the worker live test parks every other open job (`available_at='infinity'`) | `assert … job["run_id"] == run` fails. `claim_job` takes the oldest claimable job, which was a leftover committed by Task 2's live tests (see M15). The failed attempt also left a job claimed by "t" forever. |
| W17 | 8 | Misleading | ruff fix + format, SIM117 | I001 ×5, RUF059 ×2, SIM117, RUF100 ×2. `ruff --fix` for RUF100 deletes the whole trailing comment, including the plan's "a crashed handler leaves the job claimed for T13's reclaim" rationale. |
| W18 | 9 | **Blocking** | The four uvicorn entrypoints run `asyncio.run(uvicorn.Server(Config(...)).serve(), loop_factory=SelectorEventLoop if win32)` | First e2e: `RuntimeError: mcp-read exited early`. All four logs: `psycopg.InterfaceError: Psycopg cannot use the 'ProactorEventLoop' to run in async mode…` / `ERROR: Application startup failed. Exiting.` Only the worker selects the selector loop; conftest's policy masked this for in-process live tests. |
| W19 | 9 | **Blocking** | mcp-write connects with `autocommit=True` | Second e2e: `AssertionError: run did not reach {...}; last snapshot status=APPROVED`. The worker logged `execute job …: ok SUCCEEDED` and incident-sim received the POST, but `app.execution_grant` count was 0. The tool body's bare `resolve_handle` SELECT opens an implicit transaction, so grant, mark_sent and record_outcome run as SAVEPOINTs and never commit. The plan's note ("ready wraps its probe so no implicit transaction lingers") misses `resolve_handle`. |
| W20 | 9 | Misleading (severe) | incident-sim connects with `autocommit=True` | The e2e passed without it (11 passed), but afterwards `incident.action_key` had no row for the run's action_id. incident-sim's `/health/ready` bare `SELECT 1` (polled by `Skeleton.start`) opens an implicit transaction, so every `keys.commit` is a savepoint that is never committed. Receipts exist only in process memory: the app DB says `SUCCEEDED` with INC-0000xx, and the destination forgets it on restart. Reproduced standalone with `probe_tx.py`: "after SELECT 1, a status: INTRANS / after commit, a status: INTRANS / visible to another connection: False". After W20 the key is visible from psql after shutdown (`COMMITTED|INC-000025`). |

## Other Misleading items (no workaround needed)

- **M13.** Task 3 Expected "18 passed (9 parametrized rejections + 9)". Actual: 16 (9 + 7).
- **M14.** Task 6 Expected "9 passed (4 parametrized envelopes + 5)". Actual: 8 (4 + 4).
- **M15.** Task 2 says "Every test runs inside `async with app_conn.transaction()` and the fixture rolls back, so the live database keeps only the migration's rows". This is false. On a fresh non-autocommit connection that block is the outer transaction and COMMITs on exit, so `rollback()` has nothing to undo. After Tasks 2–6, 9 runs were left in `app.runs`, 7 with claimable `investigate` jobs and 1 APPROVED with claimable investigate + execute jobs. The skeleton worker later processed them (worker.log: "investigate job …: run already RETRIEVING", "execute job …: run is INSUFFICIENT_EVIDENCE, nothing to dispatch").
- **M15b, the converse.** In test_mcp_write_live and test_worker_live, everything after the first bare SELECT runs as savepoints, and the final `rollback()` erases it. Those tests prove behaviour on one connection, not commit behaviour.
- **M16.** Review Focus 1 says the e2e test has a "replay step", and Focus 5 says CONFLICT is pinned "in … the e2e test". The e2e test contains neither: no second `create_incident`, no different-hash POST.
- **M17.** acceptance-matrix vocabulary defines `RECORDED_LOCALLY` as "the tests in evidence_paths pass in scripts/check.py and CI". The R105 test is skipped there, so the note the plan adds contradicts the file's own header.
- **M18.** "Resolved versions" lists fastapi 0.142.4; 0.143.0 resolved.
- **M19.** Both `env.py` docstrings say "no URL with a password is ever built or logged", but `skeleton.upgrade()` builds `URL.create(password=...)`. The Step 4 note admits it.
- **M20.** Six "Expected: ModuleNotFoundError: No module named 'ops_X.Y'" lines. Actual: `ImportError: cannot import name 'Y' from 'ops_X'` (cosmetic; Tasks 1, 4–8).
- **M21.** The `uv lock` diff is not "additions only". `uv add --dev pytest-asyncio` writes an uncapped `>=1.4.0`, against the plan's ">=floor,<next-major" rule.
- **M22.** `tests/plan_d/test_skeleton_evidence.py` passes vacuously when `reports/skeleton/` has no file (it globs). Probe 4: "1 passed".
- **M23.** Task 9 asks for `review_notes` to quote "<first>..<last commit>" inside the last commit itself (chicken-and-egg). T08 has no `review_notes` key to add to; it must be created.
- **M24.** The Task 1 debt additions duplicate the existing line "raw handle not hashed → T09/T15" (now listed twice).

## Risky

- **R1 (high; reproduced).** The worker's `/health/ready` and poll loop share one AsyncConnection, and both open `conn.transaction()`. Concurrent health calls interleave with the loop's transaction: the connection stays "idle in transaction" (`pg_stat_activity` showed the worker's backend idle in transaction with last query `RELEASE "_pg3_1"`). From then on the worker claims and processes jobs (worker.log shows its mcp-read calls), but nothing commits, while `/health/ready` keeps answering `{"status":"ready"}`.
  - Probe `p_run.py`: without health hammering a run reached `AWAITING_APPROVAL`. With 4 threads hammering health (≈1,840 hits), the next run stayed `QUEUED`, and a later unhammered run also stayed `QUEUED`. The wedge is permanent.
  - It also happened naturally once, after `skeleton.py up`, whose start loop polls health every 0.25 s.
- **R2.** api, mcp-write and incident-sim each use one AsyncConnection for all concurrent requests. Overlapping `conn.transaction()` blocks from concurrent requests nest or interleave on that connection, the same failure class as R1. The sequential e2e hides it.
- **R3.** Live tests commit into the shared dev DB, and the skeleton worker processes their leftovers during the e2e session. `claim_job` is global, so any live test that claims is order- and leftover-dependent.
- **R4 (reproduced).** The e2e order is load-bearing. Running `tests/e2e` files in reverse order: "1 failed, 9 passed, 2 errors". The session-scoped `skeleton` fixture, started by test_r105, still holds 8090/8081 when test_mcp_write_live and test_mcp_read_live bind their own servers (`[Errno 10048]`, `SystemExit: 3`, "previous item was not torn down properly").
- **R5 (reproduced).** Runbook steps 3 and 4 conflict. With `skeleton.py up` running, `pytest tests/e2e` starts a second set of processes that fail to bind (`[Errno 10048]` in every log). The fixture's health polling succeeds against the `up` set anyway, and the test then ran against a worker wedged by R1: "run did not reach … last snapshot status=QUEUED" after 55 s.
- **R6.** `sys.executable` in the uv venv is the trampoline `.venv\Scripts\python.exe`, so `pids.json` records launcher PIDs whose real interpreter is a child process (verified with Win32_Process parent PIDs). `down` works only because the trampoline's job object kills the child; I verified that all ports were free after `down`. `terminate()`/`os.kill` is TerminateProcess, so there is no graceful shutdown.
- **R7.** `skeleton.py status` is flaky. It printed "worker down" immediately after `UP` (2 s timeout against a busy shared connection), then "ready" 3 s later.
- **R8.** Every live run rewrites the committed `reports/skeleton/r105-walking-skeleton.txt` (and plan_b live rewrites `reports/bootstrap/*.txt`), leaving a dirty tree. Probe 4: with `reports/skeleton/` deleted from a tree where it is tracked, check.py is RED with 12 failures: `test_text_hygiene` plus 11 `test_verify_handoff` copies hitting `FileNotFoundError: 'reports/skeleton/r105-walking-skeleton.txt'`.
- **R9.** A worker crash mid-investigate leaves the run in `RETRIEVING` forever (no reclaim, T13 debt). `runs_one_active_per_conversation` includes RETRIEVING, so that conversation can never admit another run. The read handle also stays valid (not revoked) for its 60 s TTL.
- **R10.** `bootstrap_dev.py secrets` created `postgres_incident_password` in the shared secrets dir (`%LOCALAPPDATA%\ops-copilot\secrets`). It is left there; the real run will "keep" it.
- **R11.** Incremental mypy was flaky after many edits: `api\src\ops_api\store.py:17: error: Module "ops_core" has no attribute "persistence"  [attr-defined]`. `--no-incremental` and the immediate rerun were clean.
- **R12.** Both migrations read `Path("data/seed-ids.json")` relative to the CWD, and `load_dotenv()` defaults to `Path(".env")`, so `migrate` from a non-root CWD fails.
- **R13.** The live tests bind fixed ports (8081, 8090) in-process, so they clash with anything else on those ports.

## Probes

1. **Replay (Task 6 live), as written.** The test passes: same outcome, 3 attempt-state rows. All of it runs inside an implicit transaction that is rolled back (M15b), so I re-ran it with `../sd/p_replay.py` on an autocommit connection and checked from a second connection:

   ```
   statuses SUCCEEDED SUCCEEDED same True
   destination POSTs 1
   grants (other conn) 1
   attempt rows ['INTENT', 'SENT', 'RESOLVED']
   run state SUCCEEDED
   incident keys 1
   ```

   One action id, three rows, no second POST. **The replay rule holds when it actually commits.**

2. **Second e2e run without restarting processes.** I ran `pytest --keep-duplicates tests/e2e/test_r105_walking_skeleton.py tests/e2e/test_r105_walking_skeleton.py`, so the session-scoped skeleton stays up. Result: "2 passed in 22.99s". The second run got its own run, because each run creates a new conversation. The evidence file was rewritten cleanly: one file, the last run's 5 lines, LF.
   - Caveat: running the e2e again while `skeleton.py up` processes are running fails (R5).
3. **Worker killed after `tool.started`.** I blackholed mcp-read so the call hangs, then called TerminateProcess on the worker and restarted it.
   - Before the kill the events were `['run.accepted','tool.started']`. After the restart (8 s): run `('RETRIEVING', 2)`; history `[(1,'QUEUED','create_run'), (2,'RETRIEVING','transition_run')]`; events `[(1,'run.accepted'), (2,'tool.started')]` (gap-free); job `('investigate', 'JPC:88808', attempts 1, done False)`; handle `('read', not revoked, still unexpired)`; 0 idle-in-transaction sessions.
   - **"Left claimed" holds and nothing is corrupt.** But the run and its conversation slot are stuck permanently (R9).
4. **check.py without `reports/skeleton/`.** It is tracked after Task 9, so check.py is RED with 12 failures (R8). The evidence test alone is "1 passed", vacuous (M22).
5. **Unit suite twice.** `443 passed, 41 skipped, 1 warning` twice. tests/plan_d in reverse file order: 62 passed. **No order dependence in the unit tests.** The live tests are order-dependent (R4).

## Execution log per task (commands, outputs, timings)

### Task 1 (4.3 min)
- Baseline check.py: 381 passed, 30 skipped, GREEN.
- S1: debt appended and committed; this introduces the duplicate in M24.
- S3: `PYTHONUTF8=1 uv run python -m pytest tests/plan_d/test_settings.py -q` → `ImportError: cannot import name 'settings' from 'ops_core'`.
- S4: dependency edits, `uv add --dev pytest-asyncio`, `uv lock && uv sync --locked --all-packages` → versions above.
- S6: 5 passed.
- S8: plan_b 38 passed, 10 skipped. `bootstrap_dev.py secrets` → "1 created, 12 kept".
- S9: down/up 36 s, "bootstrap admin: deleted"; `OPS_LIVE=1 … tests/plan_b/live` → 9 passed in 33.62s. Live tests modified the tracked `reports/bootstrap/*.txt`, which Step 10's `git add` omits.
- S10: RED (format) → W1 → GREEN 386/30.

### Task 2 (2.0 min)
- S1: ModuleNotFoundError as expected.
- S7: migrate fails (W2), then "MIGRATE: app and incident at head" twice.
- Live: 4 passed, 1 failed (W3) → 5 passed; ungated: 5 skipped.
- S8: W4, W5 → GREEN 395/35. verify_handoff exit 0.

### Task 3 (1.4 min)
- Unit 16 passed (M13), 1 InsecureKeyLengthWarning (HS256 test key "secret").
- Live 1 passed in 5.69s.
- W6 → GREEN 411/36.

### Task 4 (3.2 min)
- Unit 3 failed / 5 passed (W7) → 8 passed. Live 1 passed with the plan's own note applied (UndefinedTable).
- W8, W9, W10 → GREEN 419/37.

### Task 5 (2.1 min)
- Unit 5 passed. Live failed (W11) → 1 passed in 4.8s.
- W12 → GREEN 424/38.

### Task 6 (2.0 min)
- Unit 8 passed (M14). Live 1 passed in 1.9s.
- W13 → GREEN 432/39.

### Task 7 (1.6 min)
- Unit 4 failed / 2 passed (W14) → 6 passed.
- W15 → GREEN 438/39. Task 7 has no live test.

### Task 8 (1.7 min)
- Unit 4 passed. Live failed (W16) → 1 passed.
- W17 → GREEN 442/40.

### Task 9 (6.8 min)
- `skeleton.py status` → all down.
- e2e run 1: `10 passed, 1 error in 13.79s` (W18).
- Run 2: `1 failed, 10 passed in 68.56s` (W19).
- Run 3: `11 passed in 23.19s`, but the destination key is not durable (W20).
- Run 4: `11 passed in 23.33s`, key durable.
- test_skeleton_evidence: 1 passed.
- Docs steps executed. PROJECT_HISTORY §19 carries a placeholder, because the controller supplied no list.
- check.py: first RED (R11), rerun GREEN 443/41. verify_handoff exit 0; both JSON files load.
- Live gate: 20 passed in 56.09s.

## Cleanup proof

- Processes: `skeleton.py down` printed DOWN for all five. `netstat -ano | grep -E ":(8000|8070|8081|8082|8090|8099) .*LISTEN" | wc -l` returned **0**, and `skeleton.py status` showed all five down.
- Statements run (`docker exec ops-copilot-postgres-1 psql -v ON_ERROR_STOP=1 -U ops`):
  - db `ops`: `DROP SCHEMA app CASCADE; DROP TABLE IF EXISTS public.alembic_version` → DROP SCHEMA, DROP TABLE.
  - db `incident`: `DROP SCHEMA incident CASCADE; DROP TABLE IF EXISTS public.alembic_version; REASSIGN OWNED BY incident TO ops; DROP OWNED BY incident` → all succeeded.
  - db `ops` and db `postgres`: `REASSIGN OWNED BY incident TO ops; DROP OWNED BY incident`.
  - db `postgres`: `REVOKE ALL ON DATABASE incident FROM incident; DROP ROLE IF EXISTS incident` → REVOKE, DROP ROLE.
- Verification queries:
  - ops: `select nspname from pg_namespace where nspname in ('app','incident')` → (none); `select to_regclass('public.alembic_version')` → NULL.
  - incident: the same two queries → (none) / NULL.
  - postgres: `select count(*) from pg_roles where rolname='incident'` → **0**. Databases: incident, ops, postgres, template0, template1. Database `incident` pre-existed and is kept.
- Stack restarted from the main checkout root:
  - Commands: `uv run --frozen --no-sync python scripts/bootstrap_dev.py down`, then `… up` (`--no-sync` so the main venv was not touched).
  - Result: both containers Healthy, "bootstrap admin: deleted", with the committed realm (without the `ops-api` mapper) imported.
  - Main checkout `git status` was identical before and after: ` M docs/superpowers/research/2026-10-08-plan-d-spike.md`. That modification was not present when I started and was not made by me; I made no edits in the main checkout.
- Left in place:
  - The secret file `postgres_incident_password` in the shared secrets dir (R10).
  - The worktree itself, with `runtime/skeleton/*.log` and an uncommitted rewritten evidence file plus `reports/bootstrap/*.txt`.

## Worktree and commits

Path: `<scratch>` (detached from 10e7c4a).

```
6e656f9 docs: handoff state after Plan D (T08 done; skeleton debt owed to T09-T30)
1e15eaa feat(skeleton): process harness, the R105 end-to-end proof and its evidence
2626c1e fix(dry-run): W18-W20 selector loop for uvicorn services on Windows, autocommit connections for mcp-write and incident-sim
462d147 feat(worker): polling loop with investigate (read tool, fake draft, freeze) and execute (write tool) handlers
b2866c8 feat(api): admission to a queued run, proposal document, independent decision with exact binding, events
65fe456 feat(mcp-write): grant, mark_sent, destination call and record_outcome behind the create_incident tool
93bc6ed feat(mcp-read): authenticated read server with search_procedures over the fixture corpus and handle resolution
a3758e6 feat(incident-sim): atomic action_key destination with hash recomputation and conflict documents
ea970d6 feat(core): one JWKS-backed token verifier (iss, aud, azp, exp, signature) for every resource server
5951b14 feat(core): Alembic revision 1 for the app and incident databases, the shared persistence adapter and skeleton.py migrate
9a45bc8 feat(dev): ops-api audience for persona tokens, incident database secret, skeleton dependencies and the shared settings module
ad53ae8 docs: declare the walking skeleton's shortcuts before coding (T08 debt list)
```

The probe scripts are in the scratchpad's `sd/` directory: `probe_tx.py`, `p_run.py`, `p_kill.py`, `p_replay.py`, and `log.md` (the raw running log).

## Suggested plan fixes (for the planner)

1. **Connections.**
   - Open every service connection with `autocommit=True` and keep explicit `conn.transaction()` for units of work. At minimum do this for mcp-write and incident-sim.
   - Give the worker's health probe its own connection, or a pool, instead of sharing the poll loop's connection.
   - Use a small `AsyncConnectionPool` in the api, mcp-write and incident-sim for concurrent requests.
2. **Windows event loop.** Run all uvicorn entrypoints with `asyncio.run(Server.serve(), loop_factory=SelectorEventLoop)` on win32.
3. **Alembic.** Put the app version table in `public`, or create the schema in env.py before `run_migrations`.
4. **`IncidentRequest`.** Validate with `model_validate_json(raw)` after the `parse_json_strict` guard.
5. **api.** Drop `from __future__ import annotations` in `app.py`, or move `identity`/`Who` to module level. Make every Verifier a `Protocol` with a read-only `ready` property.
6. **persistence.** Call `event_rules_ok` before building `Event`, or change the test to expect `ValidationError`.
7. **Live tests.**
   - Make them hermetic: use an autocommit connection plus explicit cleanup, or a dedicated schema per session.
   - Pass a seeded tenant where a corpus is needed.
   - Do not rely on a global `claim_job` in tests.
   - Start the skeleton fixture in a way that does not collide with tests that bind 8081/8090, or mark those tests to run before it.
8. **Gates.** Make the code blocks ruff-format and ruff-0.16 clean (I001/B008/SIM117/RUF059/F401) and mypy-strict clean. Fix the Expected counts (16, 8). Fix the "fixture rolls back" and e2e replay/conflict claims, and the RECORDED_LOCALLY note.

---

## Round 2 — static critic

# Plan D static critic, round 2

Plan: `docs/superpowers/plans/2026-10-08-first-slice-d-walking-skeleton.md` at `plan-d` HEAD `bb92b5f` (5,624 lines; the
round-1 fix). Stance: every claim UNPROVEN until shown. `P:<n>` = plan line at `bb92b5f`. Round-1 inputs:
`static-r1.md` (B1-B7, I1-I12, M1-M17) and `builder-r1.md` (W1-W20, M13-M24 + M15b, R1-R13).

## Method and evidence base

- Scratch (outside the repo): `...\scratchpad\pland-review\static2\`. `extract2.py` lifts all 41 Python blocks by fence
  line into a package tree beside copies of the real `core/`, member dirs, `schemas/`, `data/`, `tests/plan_a|b|c`,
  `scripts/`, `pyproject.toml`; it builds `migrations/incident/env.py` (P:824 instruction), assembles
  `mcp-write/.../server.py` from the P:3493 import block + the mcp-read definitions the plan says to copy verbatim
  (P:3525, incl. `serve_app`) + P:3527, and merges Task 9's harness into `scripts/skeleton.py` (P:5375).
  Two trees: `ws_v` (verbatim) and `ws_i` (plus only the prose edits the plan instructs: `import time` P:1874,
  `UTC` P:2207, `asyncio`/`sys` P:2931, `UUID`/drop `urls` P:3022). Then the plan's own gate on `ws_i`:
  `ruff format <paths> && ruff check --fix <paths>` (P:26), followed by the checks `scripts/check.py` runs.
- Venv `%LOCALAPPDATA%\ops-critic-venv` (reused): Python 3.13.13, ruff 0.16.10, mypy 1.20.2, mcp 2.3.0, fastapi 0.143.0,
  starlette 1.7.0, uvicorn 0.54.0, psycopg 3.3.6, pyjwt 2.15.1, httpx2 2.13.1, alembic 1.20.0, sqlalchemy 2.1.4,
  pytest 9.1.1, pytest-asyncio 1.4.0, jsonschema 4.26.0, pydantic 2.13.5.
- Live dev Postgres touched **read-only** (connect, `SELECT 1`, `SELECT now()`, `SELECT %s::jsonb`, `set_config` inside
  transactions, `BEGIN`/`SAVEPOINT`/`ROLLBACK`); no table read or written; no token requested; no secret printed.
  Nothing in the repository was edited except this report.
- Probes: `probe_rules.py` (transitions, events), `probe_env.py` (envelopes, IncidentRequest), `probe_chain.py`
  (payload_canonical end to end + jsonb), `probe_pg.py` (psycopg/Session semantics), `probe_loop.py` (uvicorn loop),
  `probe_started.py`, `probe_worker_ready.py`, `leak/test_leak.py`.

## B. Measured on the new code

### ruff 0.16.10 (repo settings: `line-length = 120`, defaults otherwise)

`ruff check --show-settings` confirms the 0.16 default set is wide: ASYNC, B, BLE, C4/C90, DTZ, E (2), F, FURB, I, PERF,
PIE, PL*, PT, PYI, RUF, SIM, TRY, UP, ... (one BLE rule, BLE001, is enabled).

- `ws_v` (verbatim, no prose edits): **43 errors** (21 fixable): I001 ×20, F821 ×10 (`time` ×4 tokens.py, `UTC` keys.py,
  `sys`, `asyncio` ×3 mcp-read server, `UUID` test_mcp_read_live), BLE001 ×5, RUF059 ×4, SIM117, SIM115, F401, F841.
  The F821/F841/F401 set is exactly the post-hoc prose edits: the blocks are still not copy-and-run (M6 residue).
- `ws_i` before the gate: 32 errors. `ruff format`: "31 files reformatted, 26 files left unchanged". `ruff check --fix`:
  **"Found 32 errors (21 fixed, 11 remaining)"**, verbatim:

```
api\src\ops_api\app.py:118:20: BLE001 Do not catch blind exception: `Exception`
incident-sim\src\ops_incident_sim\app.py:104:20: BLE001 Do not catch blind exception: `Exception`
mcp-read\src\ops_mcp_read\server.py:208:16: BLE001 Do not catch blind exception: `Exception`
mcp-write\src\ops_mcp_write\server.py:203:16: BLE001 Do not catch blind exception: `Exception`
scripts\skeleton.py:157:19: SIM115 Use a context manager for opening files
tests\e2e\test_mcp_write_live.py:124:21: RUF059 Unpacked variable `conv` is never used
tests\e2e\test_worker_live.py:86:5: RUF059 Unpacked variable `tenant` is never used
tests\e2e\test_worker_live.py:86:13: RUF059 Unpacked variable `conv` is never used
tests\plan_d\test_api.py:189:8: RUF059 Unpacked variable `fake` is never used
worker\src\ops_worker\main.py:54:16: BLE001 Do not catch blind exception: `Exception`
worker\src\ops_worker\mcp.py:33:13: SIM117 Use a single `with` statement with multiple contexts instead of nested `with` statements
```

  Plan lines: BLE001 P:2316, P:2900, P:3601 (copied), P:4370, P:5063; RUF059 P:3732, P:3958, P:5175 (×2);
  SIM117 P:4835-4836; SIM115 P:5311. No B008, F401 or RUF100 remains (round-1 W8/W13/W17 classes fixed).
- `ruff format --check` after the gate: **"57 files already formatted"** (0 to reformat).

### mypy --strict (check.py's MEMBER_SRC, `--no-incremental`)

**"Found 4 errors in 4 files (checked 36 source files)"**, all the same, verbatim (type list abbreviated):

```
incident-sim\src\ops_incident_sim\__main__.py:15: error: Argument 1 to "Config" has incompatible type "object"; expected "type[ASGI2Protocol] | Callable[[HTTPScope | WebSocketScope | LifespanScope, ...], Awaitable[None]] | Callable[..., Any] | str"  [arg-type]
api\src\ops_api\__main__.py:15: error: (same)  [arg-type]
mcp-write\src\ops_mcp_write\server.py:118: error: (same)  [arg-type]
mcp-read\src\ops_mcp_read\server.py:230: error: (same)  [arg-type]
```

Source: ruling 23's `def serve_app(app: object, port: int)` (P:2372, P:2917, copied to mcp-write per P:3525, P:4487).
Everything round 1 measured is gone: `version: int` (P:1105), explicit `append_event` kwargs, every `Verifier` a
`Protocol` with a read-only `ready` (P:2235, P:2800, P:4300), `AnyHttpUrl(...)` (P:2871, P:3565), and the
`strict: Any = type(...)` subclass in `strict_tool` (P:2833) type-checks with no `type: ignore`.

### pytest tests/plan_d (no database)

`62 tests collected`; **61 passed, 1 failed, 1 warning in 3.70s**. Per file: settings 5, persistence_pure 9, tokens 16,
incident_sim 8, mcp_read 5, mcp_write 8, api 6, worker 4, skeleton_evidence 1 — every Expected count in the plan now
matches (P:383, 1269, 1879, 2389, 2945, 3627, 4504, 4795). The failure is `test_skeleton_evidence` ("the committed R105
evidence is missing"), correct before Task 9 Step 3 writes the file (see Minor m7 for its docstring). The warning is
PyJWT's `InsecureKeyLengthWarning` for the HS256 confusion test's 6-byte key. `tests/e2e` without `OPS_LIVE`:
"11 skipped" (collection, including `from scripts.skeleton import Skeleton` and `from tests.e2e.conftest import ...`,
works under `python -m pytest`). `tests/plan_a/test_layout.py::test_no_cross_member_imports` passes on the tree.

### The rules the plan relies on

- **Transitions (measured, `probe_rules.py`).** All 19 moves pass `require_transition`: ∅→QUEUED create_run;
  QUEUED→RETRIEVING, RETRIEVING→FAILED / INSUFFICIENT_EVIDENCE / DRAFTING transition_run (no reason); DRAFTING→
  AWAITING_APPROVAL freeze_proposal; AWAITING_APPROVAL→APPROVED, →REJECTED(rejected) record_decision; APPROVED→EXECUTING
  grant_execution; EXECUTING→SUCCEEDED, →FAILED(rejected|aborted_no_commit), →ESCALATED(conflict) record_outcome;
  EXECUTING→OUTCOME_UNKNOWN mark_unknown; the same four record_outcome moves from OUTCOME_UNKNOWN (the resend path).
  The live test's two expected-illegal moves (P:1443-1446) raise `IllegalTransition`. PROVEN.
- **Events (measured).** All 16 payloads the plan writes pass `event_rules_ok`, build as `Event` and validate against
  `schemas/event.schema.json`, including `action.confirmed`/`action.failed`/`action.conflict` built from a real
  `ActionOutcome.model_dump(mode="json")`. `append_event` now calls `event_rules_ok` first (P:1165), so the live test's
  `pytest.raises(EventRuleViolation)` is reachable (B5/W3). PROVEN.
- **Envelopes (measured).** `search_response` (alpha and unknown tenant), `outcome_envelope` for SUCCEEDED (`ok`),
  CONFLICT, UNKNOWN, FAILED_NO_COMMIT/REJECTED and /ABORTED (`outcome`), and error envelopes with INVALID_HANDLE,
  UNSUPPORTED_MODE, GRANT_REFUSED, NOT_FOUND all validate against `tool-result.schema.json`; the stored-outcome replay
  `ActionOutcome.model_validate_json(json.dumps(detail))` round-trips equal for all four outcomes. PROVEN.
- **`IncidentRequest.model_validate_json` with text UUID (measured):** accepted, `action_id` is a `UUID`; the round-1
  `model_validate(dict)` path still refuses (so the fix is load-bearing). PROVEN.
- **FastAPI routes with `Annotated[Identity, Depends(identity)]` inside `create_app`, no future import (measured):**
  all 6 `test_api` tests pass with `TestClient` as a context manager, including 401 (not 422) for a missing token. PROVEN.
- **psycopg (measured, live, read-only, `probe_pg.py`):** `connect()` is autocommit; a bare SELECT leaves `IDLE`;
  an outermost `transaction()` has `savepoint_name=''` and COMMITs (a `set_config` survives); a `transaction()` inside
  `transaction(force_rollback=True)` is a savepoint (`'_pg3_2'`), RELEASE keeps it visible, the outer exit rolls it
  back (status `IDLE`, value gone). `Session.unit()` inside a `force_rollback` block is likewise a savepoint undone by
  the outer rollback. Concurrency: order `['unit-start', 'read-call', 'unit-end', 'read-done']` — `read()` waits for a
  unit held by another coroutine. Reentrancy: a unit inside a unit, and `read()` inside a unit, **deadlock** (timed out
  after 2 s; `asyncio.Lock` is not reentrant). No call site in the plan nests (grep of every `.unit()`/`.read(`), so this
  is latent (Minor m10).
- **`PyJWKSet.from_dict` + `__getitem__`:** the 16 token tests pass, including unknown kid (`KeyError` path), the
  refresh-once-then-cooldown test and HS256 confusion. PROVEN.
- **`AuthSettings(issuer_url=AnyHttpUrl(...))`:** mypy-clean, and both servers build and list their tools in-process. PROVEN.
- **uvicorn loop on this Windows machine (measured, `probe_loop.py`):** the plan's `serve_app` path —
  `asyncio.run(uvicorn.Server(Config(app)).serve(), loop_factory=asyncio.SelectorEventLoop)` — gave
  `{'loop': '_WindowsSelectorEventLoop', 'select': 1, 'http': 200}`: a psycopg async connection opened and queried
  inside the lifespan and the server answered. Control (`Server.run()`, uvicorn's own loop choice):
  `ProactorEventLoop` → `psycopg.InterfaceError: Psycopg cannot use the 'ProactorEventLoop'...` → `SystemExit: 3`.
  Ruling 23 PROVEN.
- **`Tool.from_function` + dynamic `type(...)` subclass:** no `type: ignore`, mypy clean, extra `tenant_id`/`approved`
  arguments rejected (`is_error`) in the unit tests. PROVEN.
- **Token in failure output (measured, `leak/`):** `assert await mcp_call(url, wrong, ...) is None` (P:5519) prints only
  `assert {'is_error': True} is None` — pytest does not explain an `await` operand's arguments. Every other
  token-bearing call is bound before its assert. I7 PROVEN closed.

## C. New seams

- **Session lock and `read()`.** Serialises correctly (measured above); every unit is a real BEGIN/COMMIT on an
  autocommit connection; the mcp-write POST sits between units (P:3474-3481), never inside one. Hazard: not reentrant
  (m10). Undeclared as debt (m11).
- **`purge_run` / `purge_tenant` / `SEEDED_TENANTS`.** `SEEDED_TENANTS` equals `data/seed-ids.json`'s two tenant ids.
  The PURGE_ORDER respects every FK in the DDL (invocation_context→jobs; decisions/execution_grant→proposals→drafts;
  attempt_state→attempt→grant; runs→messages→conversations; `runs.active_proposal_id` has no FK). It deletes from
  `run_state_history`, `events` and `action_attempt_state`, the append-only audit tables (M8 widened, test-only).
- **`new_run(conn, tenant_id)`.** Seeded alpha for mcp-read (corpus exists); random tenant elsewhere, purged with
  `purge_tenant`. Correct.
- **Ports 18081/18090 vs `settings.urls()`.** The in-process servers' audiences come from `urls().*_resource`
  (port-independent) and the tests pass the listen URLs explicitly (P:2980, P:3739); DNS-rebinding allows
  `127.0.0.1:*`. No collision on ports. But "never collide with a running skeleton" (P:5572-5573) is false in another
  way: both tests commit claimable jobs (an `investigate` job via `create_run`; an `execute` job in `approved_run`) that a
  running skeleton worker will claim and act on before `finally` purges them — for mcp-write that means a real grant
  and POST through the skeleton's own mcp-write racing the test's (m8, R3 residue).
- **The worker's second connection (measured, `probe_worker_ready.py`).** R1's wedge is gone (health no longer shares
  the poll connection), but readiness is now blind to the poll loop: `run_forever` claims outside its `try`
  (P:5039-5040), `_main` awaits only `serving` (P:5086), so one connection error ends the loop for good while
  `/health/ready` on the probe connection keeps answering. Measured: "poll loop done: True | exception: OSError |
  /health/ready: 200 {'status': 'ready'}" (Important N3).
- **`payload_canonical` end to end (measured, `probe_chain.py`).** Real `FakeDraftGenerator` → `build_proposal` →
  bytes (as `bytea` returns them) → real `destination.post_incident` over an ASGI transport → real incident-sim
  `create_app` (stub verifier, in-memory store) → `GET /internal/actions/{id}`; summary carrying a decomposed `é`, `ü`,
  U+2028, U+2029, CJK, quotes and a backslash, and a pure-ASCII control:
  - stored bytes contain raw `E2 80 A8` (canonical_json uses `ensure_ascii=False`; Python's json never escapes U+2028);
  - POST 200 COMMITTED; destination hash == `proposals.payload_sha256`: True; `sha256(stored bytes)` == it: True;
    the payload incident-sim stores re-canonicalises to the same hash: True; GET returns the same `payload_sha256`: True;
    `classify` → SUCCEEDED; jsonb round trip (`SELECT %s::jsonb`, read-only) keeps the canonical hash: True — for both.
  - Reasoning: canonical_json NFC-normalises (idempotent), so the inner string survives the envelope's second
    `canonical_json` and jiter's decode byte-for-byte; `.encode("utf-8")` of the decoded string reproduces the stored
    bytes. PROVEN for these inputs. (Not covered: `\u0000`, which `jsonb` rejects; the contracts' handling of control
    characters was not examined — Declined.)

## D. Plan hygiene

- Step order: Task 3 Step 5 says run `check.py` (Expected GREEN) and only then "Run ruff format ... first" (P:1925-1928).
- `git add` vs created files: every Create/Modify path is staged in its task (checked per task). Residue: Task 1
  stages `reports/bootstrap/keycloak-claims.txt` only (P:443); Plan B's live suite also rewrites `bootstrap-admin.txt`
  and `ollama-bridge.txt` (their tests write them).
- Expected lines: unit counts all correct now. Task 9 Step 3 says "`9 passed`: 5 persistence, tokens, incident-sim,
  mcp-read, mcp-write, worker and R105" (P:5552) — that list is 11, and `tests/e2e` collects 11.
- Counts in prose: "append the eight lines" (P:124) — the block has ten (P:73-82); "the 21 rulings ... the eight debt
  additions" (P:5592) — 25 and ten; rulings are numbered 1-20, 22-25, 21 (P:62-66).
- Interfaces vs code: Task 8 says `health_app(deps)` (P:4537), code is `health_app(probe: persistence.Conn)` (P:5053);
  the worker docstring says "one connection" (P:5010) but `_main` opens two (P:5076-5077); Task 2 still lists
  `ACTIVE_STATES` as consumed (P:455) while the migration hard-codes it (P:614).
- Post-hoc prose edits still required (M6 residue): P:452 ("gains `files`? No —"), P:994 (a stale
  `version_table_schema=None` note — no env.py sets it any more), P:1874 (`import time`), P:1883 ("Append ...? No —"),
  P:2207 (`UTC`), P:2931 (`asyncio`, `sys`), P:3022 (`UUID`, drop `urls`), P:3693 (an inline comment about where
  `Jsonb` is imported, though it already is at the top).
- Debt list vs shortcuts found in the code: undeclared — one connection per process serialised by a lock with no
  reconnect (ruling 24 and a `TODO(T13)` only, P:64, P:1061); an `execute` job is finished after `McpCallFailed`, so a
  call that never reached mcp-write leaves the run APPROVED with no retry (`TODO(T22)` only, P:4986-4990); the
  membership issuer frozen at migration time (P:802).
- Coverage notes (P:5613-5616): consistent with the tests, except Review Focus 5 itself (P:36) still claims the e2e
  test pins CONFLICT; Coverage says "5 ✓ Task 4" only, which is the truth.

## A. Closure table

### Static round 1 (36)

| Finding | Status | Plan line | Evidence |
|---|---|---|---|
| B1 uvicorn Proactor | closed | P:63, P:2372-2379, P:2917-2924, P:4487-4494; spike:677 corrected | `probe_loop.py`: selector loop, psycopg in lifespan, HTTP 200; control fails |
| B2 Alembic version table in `app` | closed | P:580-581 (`version_table` in `public`), P:824 | reading; Alembic creates it before rev 0001 (round-1 source reading); not executed |
| B3 strict model 422 | closed | P:2325-2327 | probe: JSON mode → UUID; 8/8 incident-sim tests pass |
| B4 future import + local alias | closed | P:2218, P:4262-4263 | 6/6 api tests pass, 401 not 422 |
| B5 EventRuleViolation vs ValidationError | closed | P:1165 | probe: pre-check raises `EventRuleViolation` |
| B6 nothing committed | closed | P:1049-1076, P:2250-2260, P:3466-3486, P:4121-4246 | probe_pg: autocommit + `transaction()` = BEGIN/COMMIT, status IDLE after |
| B7 live tests commit / Task 8 fails | closed | P:1328-1375, P:1439-1507, P:2986/3018, P:3731/3759, P:5157-5171, P:5414-5416 | force_rollback measured; `own_job`; module-scoped skeleton |
| I1 mypy 13 errors | closed | P:1105, P:2235, P:2800, P:2871, P:3389, P:4300 | those 13 gone; 4 new errors from new code (N2) |
| I2 ruff | partial | P:26 + every task's gate | 11 non-autofixable remain (N1); 4 of them (RUF059 ×4, SIM117) are round-1 carry-overs |
| I3 grant/mark_sent re-checks | closed (declared) | P:82 | debt line |
| I4 shared connection | closed | P:64, P:1059-1076 | probe_pg: serialised |
| I5 coverage claims | partial | P:5510-5523 (replay, refusals) | P:36 still says the e2e test pins CONFLICT |
| I6 write test cannot see commit-before-I/O | closed | P:3713-3746 | witness connection asserts `observed == ["SENT"]` (reasoned; live run is the builder's) |
| I7 JWTs in assert output | closed | P:1906, P:5465 | `leak/test_leak.py` |
| I8 evidence rule | closed | P:5528 | prose edit of `test_evidence.py` is feasible (read the file) |
| I9 per-service tests (SA:70) | **open, undeclared** | P:24 | no ruling, no debt line → N4 |
| I10 counts | closed | P:1879, P:3627 | collected 16 / 8 |
| I11 spike error | closed | spike:677, P:1290-1292 | diff read |
| I12 superuser / CONNECT | closed (declared) | P:81 | debt line |
| M1 counts | closed | (= I10) | |
| M2 grant replay ignores proposal_id | closed | P:3366-3367 | reading |
| M3 riley vs jordan | closed | P:33 | |
| M4 query >500 | closed | P:4876, P:4922 | |
| M5 evidence side effects | partial | P:443 | only `keycloak-claims.txt` staged; other Plan B evidence files also rewritten |
| M6 blocks need post-hoc edits | partial | P:452, 994, 1874, 1883, 2207, 2931, 3022, 3693 | `ws_v`: F821 ×10, F841, F401 |
| M7 imports (mcp-write, Task 9) | closed | P:3493-3523, P:5375 | test_layout passes; no E402 |
| M8 DELETE on append-only tables | **open, undeclared** (widened) | P:1340-1351 | purge deletes history, events, attempt states → N4 |
| M9 loop scope | closed | P:228 | no deprecation warning in the run |
| M10 JWKS refresh flood | closed | P:1730, P:1832 | cooldown test passes |
| M11 interfaces drift, duplicate debt | partial | P:5241, P:80 | `LOGS` and duplicate fixed; `ACTIVE_STATES` (P:455) remains, new `health_app` drift |
| M12 execute≠recover reason | closed | P:516 | `server: "write"` now reaches the allowlist check |
| M13 handles/bounded body debt | closed (declared) | P:80, P:82 | |
| M14 timezone, issuer, relative path | partial | P:308-311, P:800 | issuer still frozen at migration (P:802) |
| M15 hash over received bytes | closed | P:50, P:2333, P:2067 | `probe_chain.py`; `spaced` test |
| M16 proposals endpoint, freeze_allowed, MODEL_MODE | closed | P:62, P:4938, P:5072 | `freeze_allowed` raises (states.py:286) |
| M17 401 vs 403; log handles | closed | P:65, P:5305/5340 | (new SIM115, N1) |

Totals (static): **closed 28, partial 6, open 2, parked 0.**

### Builder round 1 (46)

| Finding | Status | Plan line | Evidence |
|---|---|---|---|
| W1 settings not formatted | closed | P:26, P:439 | gate formats; 0 files left |
| W2 version table | closed | P:580-581 | = B2 |
| W3 EventRuleViolation | closed | P:1165 | = B5 |
| W4 I001/format | closed | P:1520 | I001 auto-fixed |
| W5 no-any-return | closed | P:1105 | mypy |
| W6 tokens I001, `import time` | partial | P:1874 | still a prose note (F821 ×4 verbatim) |
| W7 model_validate_json | closed | P:2326 | = B3 |
| W8 B008 | closed | P:2321, P:2341 | no B008 |
| W9 Verifier Protocol | closed | P:2235-2241 | mypy |
| W10 ruff | closed | P:2446 | auto-fixed |
| W11 seeded tenant | closed | P:1405-1411, P:2988 | |
| W12 AnyHttpUrl, F401, RUF059, SIM117 | closed | P:2871, P:2996-2999 | none left in mcp-read files |
| W13 `**common` | closed | P:3389-3444 | mypy |
| W14 future import | closed | P:4262 | = B4 |
| W15 Protocol, RUF059 | partial | P:4300 | RUF059 at P:3958 remains |
| W16 global claim | closed | P:5157-5171 | `own_job` + force_rollback |
| W17 ruff in worker | partial | P:5049 | RUF100 gone; SIM117 P:4835, RUF059 P:5175 remain |
| W18 selector loop | closed | P:63 | = B1 |
| W19 mcp-write autocommit | closed | P:1056, P:3580 | |
| W20 incident-sim autocommit | closed | P:2252, P:2356 | |
| M13 18 vs 16 | closed | P:1879 | |
| M14 9 vs 8 | closed | P:3627 | |
| M15 rollback claim | closed | P:1439-1507 | probe_pg |
| M15b savepoints in write/worker tests | closed | P:3731-3746, P:5206 | witness; worker note states savepoints |
| M16 e2e replay/conflict claims | partial | P:5510-5523 | replay added; CONFLICT claim P:36 remains |
| M17 RECORDED_LOCALLY | closed | P:5590 | new `RECORDED_LOCALLY_LIVE` |
| M18 versions | closed | P:5620 | |
| M19 env.py docstring | closed | P:569-571 | |
| M20 ImportError text | closed | P:216 etc. | |
| M21 uv.lock / pytest-asyncio cap | partial | P:228 | cap fixed; "additions only" still claimed P:231 |
| M22 evidence test vacuous | closed | P:5542 | asserts presence (docstring now contradicts, m7) |
| M23 review_notes | closed | P:5588 | |
| M24 duplicate debt line | closed | P:80 | |
| R1 worker wedge | closed | P:5053-5067, P:5077 | but readiness now blind to the loop (N3) |
| R2 shared connection | closed | P:64 | = I4 |
| R3 live leftovers | partial | P:1507, P:5157 | in-session fixed; a running skeleton still claims the mcp-read/mcp-write live tests' committed jobs (m8) |
| R4 order-dependent e2e | closed | P:5414-5416, P:2978, P:3707 | |
| R5 runbook conflict | closed | P:5570, P:5550 | requires `status` all down |
| R6 trampoline PIDs | **open, undeclared** | P:5375 | "the processes here spawn no children" is the false claim → N4 |
| R7 flaky status | closed | P:5294 | 5 s timeout |
| R8 evidence rewritten | parked | P:5574 | runbook step 5 |
| R9 crash leaves run stuck | parked | P:78 | debt line |
| R10 secret file left | closed (by design) | P:425 | intended artefact |
| R11 incremental mypy flake | **open, undeclared** | — | no `--no-incremental` advice or note → N4 |
| R12 relative paths | closed | P:800, P:973 | |
| R13 fixed ports | closed | P:2978, P:3707 | distinct alternate ports |

Totals (builder): **closed 36, partial 6, open 2, parked 2.**

## Consolidated findings

### Blocking (0)

None. Nothing measured here stops a task outright; the e2e path's three round-1 blockers (loop, commits, wedge) are
closed by measured mechanisms.

### Important (4)

**N1. `check.py` is RED at Tasks 4, 5, 6, 7, 8 and 9 even after the plan's own ruff gate.** 11 errors that
`ruff check --fix` cannot fix (list above): BLE001 at P:2316, P:2900, P:3601, P:4370, P:5063; RUF059 at P:3732,
P:3958, P:5175 (×2); SIM117 at P:4835-4836; SIM115 at P:5311. Each task's Expected `CHECK: GREEN` fails.
*Fix:* readiness probes catch `(psycopg.Error, OSError)` (or keep `Exception` with `# noqa: BLE001` and a reason);
`_, _, run, proposal, handle = ...`, `_tenant, _conv, run = ...`, `c, _ = api`; one `async with (A as http, B as
client):`; `Skeleton.start` keeps `log = open(...)  # noqa: SIM115 — closed in stop()` or uses an `ExitStack`.
*Verified:* ruff 0.16.10 on `ws_i` after `ruff format` + `ruff check --fix`.

**N2. mypy strict: 4 × `arg-type` from ruling 23's helper `serve_app(app: object, port)`** (P:2372, P:2917 and its
mcp-write copy, P:4487) — `uvicorn.Config` does not take `object`. RED from Task 4. *Fix:* annotate the concrete type
(`app: FastAPI` in api/incident-sim, `app: Starlette` in the MCP servers) or `Callable[..., Any]`.
*Verified:* mypy 1.20.2 `--no-incremental` on the seven member trees: these 4 errors and nothing else.

**N3. The worker reports `ready` after its poll loop has died.** `run_forever` claims outside its `try` (P:5039-5040);
`_main` awaits only `serving` (P:5086); readiness probes a different connection (P:5060-5065). One dropped poll
connection ends job processing permanently while `skeleton.py up`, `status` and the e2e fixture see `ready` — the same
symptom R1 reported, through a different door. *Fix:* wrap the claim in the loop's `try` (log and back off), and make
`ready` return 503 when `polling.done()` (pass the task or a heartbeat timestamp into `health_app`); or
`asyncio.wait({serving, polling}, return_when=FIRST_COMPLETED)` and exit non-zero. *Verified:* `probe_worker_ready.py`
— "poll loop done: True | exception: OSError | /health/ready: 200 {'status': 'ready'}".

**N4. Four round-1 findings are neither closed nor declared** (the review rule makes each Important):
I9 per-service `tests/` (SA:70 / ADR-0001 says each service has its own `tests/`; P:24 puts them all in `tests/plan_d`
with no ruling or debt line); M8 test purges delete from the append-only audit tables (P:1340-1351; will break once
T09 revokes DELETE); R6 `sys.executable` under uv is a trampoline whose real interpreter is a child, against P:5375's
"the processes here spawn no children"; R11 incremental mypy produced a spurious `attr-defined` during the dry run.
*Fix:* a ruling for I9 (or move the tests) and one sentence each for M8 (test-only cleanup as the superuser; T09 owns a
test-cleanup path), R6 (correct the sentence; `down` relies on the trampoline's job object) and R11 (rerun with
`--no-incremental` before reporting RED). *Verified:* reading the plan, SA:70, the member directories, builder-r1.

### Minor (12)

- **m1** Review Focus 5 (P:36) still says CONFLICT is pinned "and the e2e test"; the e2e test sends no different-hash
  POST. Drop the clause or add the call.
- **m2** Task 9 Step 3 Expected "`9 passed`" (P:5552) — `tests/e2e` holds 11 tests.
- **m3** "append the eight lines" (P:124) — ten; "the 21 rulings ... eight debt additions" (P:5592) — 25 and ten;
  rulings ordered 20, 22-25, 21 (P:62-66).
- **m4** Post-hoc prose edits remain (P:452, P:994 stale, P:1874, P:1883, P:2207, P:2931, P:3022, P:3693): put the
  imports in the blocks and delete the notes.
- **m5** Task 3 Step 5 runs `check.py` before the ruff gate (P:1925-1928).
- **m6** Interfaces drift: `health_app(deps)` (P:4537) vs `health_app(probe)` (P:5053); worker docstring "one
  connection" (P:5010); `ACTIVE_STATES` consumed (P:455) but hard-coded (P:614).
- **m7** `test_skeleton_evidence`'s docstring says absent evidence is not a failure (P:5534-5535); the test asserts
  presence (P:5542).
- **m8** Runbook "never collide with a running skeleton" (P:5572-5573): ports do not, but the mcp-read and mcp-write
  live tests commit claimable jobs a running skeleton worker will execute (for mcp-write: a real grant and POST racing
  the test's own). Say "with the skeleton down", or insert those jobs with `available_at = 'infinity'`.
- **m9** Task 1 stages only `reports/bootstrap/keycloak-claims.txt` (P:443) though the Plan B live run rewrites the
  other evidence files too; and P:231 still promises an additions-only `uv.lock` diff.
- **m10** `Session.unit()` is not reentrant: a nested unit, or `read()` inside a unit, deadlocks (measured). No call site
  nests today; say so in the `Session` docstring.
- **m11** Undeclared shortcuts: one connection per process serialised by a lock, no reconnect (P:64, P:1061: ruling
  and TODO only); an `execute` job finished after `McpCallFailed` leaves the run APPROVED with no retry (P:4986-4990,
  TODO(T22) only); membership issuer frozen at migration time (P:802). Add them to the debt list.
- **m12** `post_incident` hashes are proven equal for NFC/non-ASCII/U+2028 payloads, but a `\u0000` in any payload
  string would be refused by `jsonb` in both databases (freeze fails → run stuck DRAFTING; destination insert fails →
  500 → UNKNOWN). Whether the contracts already refuse control characters was not checked (see Declined).

## Declined to judge

- Any live run (migrations on a fresh database, the live tests, R105): the builder critic owns live writes.
- Alembic's version-table placement on a fresh database (B2 fix): reasoned from round 1's source reading; not executed.
- Whether `ops_core.contracts` refuses NUL/control characters in `ModelDraft`/`ProposalPayload` strings (m12).
- The Keycloak realm re-import and the Plan B static/live tests after the prose edits to `test_realm_template.py`,
  `test_keycloak_tokens.py` and `test_evidence.py` (prose, not extractable; feasibility read only).
- The MCP 401 → `MCPError` mapping relied on at P:3013 and P:5434: builder round 1 observed it live; not re-measured.
- Docs written in Task 9 (STATUS, PROJECT_HISTORY, README): content does not exist yet.

---

## Round 2 — builder dry run

# Plan D builder critic — round 2 (dry execution of Tasks 1–9)

- **Plan:** `docs/superpowers/plans/2026-10-08-first-slice-d-walking-skeleton.md` at `bb92b5f` (branch `plan-d`, the round-1 fix).
- **Worktree** (detached, kept): `<scratch>`
- **Round-1 worktree:** removed and pruned.
- **Time:** executed 2026-10-08 06:20–06:43 local (UTC-7); probes and cleanup ran until about 06:52.
- **Scripts and logs:** in the scratchpad's `sd2/` directory: `ext.py` (verbatim block extractor), `log.md`, `probe3.py`, `probe4.py`, `probe7.py`, `probe_admit.py`, `blackhole.py`, `e2e_run1.txt`.

## Verdict: EXECUTABLE WITH FIXES

All nine tasks ran to the end. The R105 e2e test reaches `SUCCEEDED`. The nine events arrive in order, the replay returns the same action id, and every refusal assertion holds.

That took **6 labelled workarounds, 1 of them Blocking.** Round 1 needed 20, 8 of them Blocking.

**The one Blocking item (W5)** is new in the round-1 fix:
- The e2e helper `mcp_call` catches `MCPError` outside `async with Client(...)`.
- An error raised inside that block reaches the caller wrapped in an anyio `ExceptionGroup`, so the `except` never matches.
- So the wrong-token refusals at mcp-write fail the test, after the happy path and the replay have already passed.

**The same defect lives in the worker's `HttpMcpCaller`** (Risky RA, reproduced):
- When mcp-read is unreachable, the investigate handler crashes with an `ExceptionGroup` instead of raising `McpCallFailed`.
- The run therefore stays `RETRIEVING` forever with its job claimed. The plan's "retrieval failed → FAILED" path is dead code for transport failures.

The other five workarounds are lint/type gates:
- The repo's ruff config enables BLE001, SIM115, SIM117 and RUF059.
- mypy strict rejects `serve_app(app: object)`.
- Each one made `check.py` RED as written, in Tasks 4–9.

Counts: **Blocking 1 · Misleading 14 · Risky 7.**

## Summary table (gates)

| Task | Wall clock | check.py after task (with workarounds) | Live |
|---|---|---|---|
| baseline | — | 381 passed, 30 skipped, GREEN | — |
| 1 | 06:21:44–06:24:20 (2.6 min) | 386 passed, 30 skipped, GREEN (as written, via the plan's own ruff step) | plan_b live 9 passed in 33.58s |
| 2 | 06:24:30–06:26:01 (1.5 min) | 395 passed, 35 skipped, GREEN (as written) | 5 passed in 1.04s; ungated 5 skipped |
| 3 | 06:26:05–06:26:57 (0.9 min) | 411 passed, 36 skipped, 1 warning, GREEN (as written) | 1 passed in 5.49s |
| 4 | 06:27:10–06:29:12 (2.0 min) | 419 passed, 37 skipped, 1 warning, GREEN (RED as written: W1, W2) | 1 passed in 0.68s |
| 5 | 06:29:20–06:30:53 (1.6 min) | 424 passed, 38 skipped, 1 warning, GREEN (RED as written: W1, W2) | 1 passed in 4.77s |
| 6 | 06:31:00–06:32:54 (1.9 min) | 432 passed, 39 skipped, 1 warning, GREEN (RED as written: W1, W2, W3) | 1 passed in 2.16s |
| 7 | 06:33:00–06:34:18 (1.3 min) | 438 passed, 39 skipped, 1 warning, GREEN (RED as written: W1, W2, W3) | (none in plan) |
| 8 | 06:34:30–06:36:05 (1.6 min) | 442 passed, 40 skipped, 1 warning, GREEN (RED as written: W1, W3, W4) | 1 passed in 1.42s |
| 9 | 06:36:10–06:41:46 (5.6 min) | 443 passed, 41 skipped, 1 warning, GREEN (RED as written: W6) | e2e 1 failed/10 passed → W5 → 11 passed in 25.92s |

Total execution time was about 19 minutes; round 1 took about 29.

The "1 warning" is PyJWT's `InsecureKeyLengthWarning` from the HS256 test key in `test_tokens.py`. It persists from round 1 and is cosmetic.

`verify_handoff.py --reference-code --manifest --contracts` exited 0 after Task 2 and after Task 9. Both JSON files load.

**Final live gate (06:41:58–06:42:58):**

```
OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e tests/plan_b/live -q -p no:cacheprovider
20 passed in 58.79s
```

**Final `check.py`:** `443 passed, 41 skipped, 1 warning in 23.86s` / `CHECK: GREEN`.

### `uv lock` (Task 1)

`Resolved 64 packages`. The versions are identical to round 1 and to the plan's "Resolved versions":

| Package | Version |
|---|---|
| mcp | 2.3.0 |
| fastapi | 0.143.0 |
| starlette | 1.7.0 |
| uvicorn | 0.54.0 |
| psycopg (+ psycopg-binary) | 3.3.6 |
| sqlalchemy | 2.1.4 |
| alembic | 1.20.0 |
| pyjwt | 2.15.1 |
| httpx2 | 2.13.1 |
| cryptography | 50.0.2 |
| pytest-asyncio | 1.4.0, written `>=1.4,<2` (the cap is now present) |
| ruff | 0.16.10 |
| mypy | 1.20.2 |

The `uv.lock` diff is 708+/14-. The removals are `requires-dist` rewrites and one `python_full_version < '3.15'` resolution-marker line, so it is still not "additions only".

### R105 evidence (gate run, `reports/skeleton/r105-walking-skeleton.txt`)

```
R105 walking skeleton — 2026-10-08T13:42:17Z
run_id=6b3630f2-bd99-40cb-8a2a-5af241f2465f accepted status=QUEUED
proposal_id=fb083d7a-48de-47d1-8583-a8a7b3557874 revision=1 payload_sha256=46165d811f17391f7ef5c6e8a66e21ee946b1d6274b29540b8541d36163f6506 evidence=['ALPHA-TRIAGE:v1:scope']
state=SUCCEEDED state_version=7 action_id=4d408b10-ad09-49d5-beb4-1c97169d31aa incident_id=INC-000025
events=run.accepted,tool.started,tool.completed,explanation.ready,proposal.ready,approval.recorded,action.granted,action.dispatched,action.confirmed
replay=same_action_id refusals=api:worker,destination:persona+worker,mcp-write:persona+mcp-read
```

What the e2e proves:
- `SUCCEEDED`, with the nine events in order and the sources the plan expects (`model_summary` for `explanation.ready`, `destination` for `action.confirmed`).
- The replay over the real transport with a fresh execute handle returns `status=ok` and the same `action_id`. The destination's receipt is unchanged, so there is no second incident.
- Refusals: worker token at the API → 401; persona and worker tokens at incident-sim → 401 with no action id in the body; persona and mcp-read tokens at mcp-write → MCPError. The last one holds only after W5.
- The self-decision is 403, the stale hash is 409 VERSION_CONFLICT, and the second decision is 409.

## Workarounds (graded)

| # | Task(s) | Grade | What I changed | Why the plan was wrong |
|---|---|---|---|---|
| W1 | 4, 5, 6, 7, 8 | Misleading | `# noqa: BLE001 - readiness reports any database failure as not ready` on the five health `except Exception:` lines (incident-sim app.py, mcp-read server.py, mcp-write server.py, api app.py, worker main.py `ready`). This follows the repo convention in `scripts/probe.py`. | The repo's ruff config enables BLE001. `BLE001 Do not catch blind exception: Exception --> incident-sim\src\ops_incident_sim\app.py:104:20` (and server.py:208, server.py:201, app.py:118, main.py:54). The worker's `run_forever` `except Exception` is not flagged, because it calls `log.exception`. |
| W2 | 4, 5, 6, 7 | Misleading | `serve_app(app: ASGIApp, port)` with `from starlette.types import ASGIApp` (incident-sim and api `__main__.py`, mcp-read and mcp-write `server.py`) | mypy strict: `incident-sim\src\ops_incident_sim\__main__.py:15: error: Argument 1 to "Config" has incompatible type "object"; expected "type[ASGI2Protocol] \| Callable[...] \| Callable[..., Any] \| str"  [arg-type]`. The same error appears at mcp-read server.py:230, mcp-write server.py:116 and api `__main__.py:15`. The plan's six-line helper was never type-checked. |
| W3 | 6, 7, 8 | Misleading | `_conv` (test_mcp_write_live.py:124); `c, _ = api` (test_api.py:189, `test_runs_are_tenant_scoped`); `_, _, run = await new_run(...)` (test_worker_live.py:86) | `RUF059 Unpacked variable conv/fake/tenant/conv is never used`. `ruff check --fix` does not auto-fix RUF059. |
| W4 | 8 | Misleading | worker/mcp.py: the two nested `async with` statements merged into the parenthesised form the mcp-read live test already uses | `SIM117 Use a single with statement with multiple contexts instead of nested with statements --> worker\src\ops_worker\mcp.py:33:13` (not auto-fixed). |
| W5 | 9 | **Blocking** | `tests/e2e/test_r105_walking_skeleton.py::mcp_call` also has `except ExceptionGroup as group: if group.subgroup(MCPError) is None: raise; return None` | First e2e run: `1 failed, 10 passed in 26.03s` at line 138, in the loop that presents wrong tokens to mcp-write (the replay assert before it had passed). The traceback is `ExceptionGroup: unhandled errors in a TaskGroup` → `ExceptionGroup` → `mcp.shared.exceptions.MCPError: Server returned an error response`. The MCPError is raised inside `async with (httpx2.AsyncClient(...), Client(...))`, and the client's anyio task groups wrap it on `__aexit__`, so `except MCPError:` outside the block never matches. Task 5's live test works only because its `pytest.raises(MCPError)` sits inside the block. The same wrong pattern is in `worker/src/ops_worker/mcp.py` (Risky RA). |
| W6 | 9 | Misleading | `# noqa: SIM115 - closed in stop(); the child writes to it until then` on `log = open(...)` in `Skeleton.start` | `SIM115 Use a context manager for opening files --> scripts\skeleton.py:157:19`. The open is deliberate, but the plan did not mark it. |

The plan's own notes were applied as written, so they are not counted as workarounds:
- `import time` in tokens.py.
- `UTC` in keys.py.
- `import asyncio, sys` in mcp-read server.py.
- `from uuid import UUID` and dropping `urls` in test_mcp_read_live.py.

Each of these left an import-order or unused-import issue, which the plan's `ruff check --fix` step fixed.

## Other Misleading items (no workaround needed)

- **M-a.** Task 9 Step 3 says "Expected: `9 passed`" but lists 11 tests. The actual result is `11 passed`.
- **M-b.** Task 1 Step 1 says "append the eight lines", but the debt block has 10 lines.
- **M-c.** Task 1 Step 4 says the `uv.lock` diff is "additions only". It is 708+/14-, because of `requires-dist` rewrites and a resolution marker. This is the residue of M21; the pytest-asyncio cap is fixed.
- **M-d.** Task 9 Step 5 says "the 21 rulings". The plan now has 25, and 22–25 are placed before 21.
- **M-e.** Task 2 Step 3 says `migrations/incident/env.py` is "identical to the app one except the docstring's first line". As written, the incident tree's RuntimeError then says "migrations/app runs only through scripts/skeleton.py migrate".
- **M-f.** Task 6 Step 4 gives mcp-write `server.py` only an import block plus "copy verbatim". It has no module docstring (mcp-read's has one), and the dictated comment is wider than 120 columns on one line, so I wrapped it.
- **M-g.** Task 5 Step 4's code block still contains `urls = settings.urls()` and `from uuid import uuid4`. The test only works because of the trailing note ("add UUID, `urls` is no longer needed"). An executor who transcribes and skips the note gets a NameError on `UUID`.
- **M-h.** Task 3 Step 5 lists `check.py` before "Run ruff … first". The order is backwards on the page.
- **M-i.** Review Focus 5 says CONFLICT is pinned in "Task 4's live DB test and the e2e test". The e2e test has a replay step but no different-hash POST, while Coverage notes say "5 ✓ Task 4". This is the remainder of M16; Focus 1's replay claim is now true.
- **M-j.** Task 9 Step 1 says "the processes here spawn no children". In the uv venv, `sys.executable` is the trampoline (R6 from round 1), so the PIDs recorded are launcher PIDs. Not re-verified; `down` still freed every port.
- **M-k.** Each live run rewrites three tracked files: `reports/bootstrap/bootstrap-admin.txt`, `reports/bootstrap/keycloak-claims.txt` and `reports/skeleton/r105-walking-skeleton.txt`. Task 1 Step 10's `git add` omits `bootstrap-admin.txt`, so the tree stays dirty from Task 1 onwards. The runbook mentions only the skeleton evidence. This is R8's residue.
- **M-l.** Task 9 Step 5's PROJECT_HISTORY §19 needs the controller's execution list. As the plan allows, I left a marked placeholder.
- **M-m.** The plan never says the repo's ruff rule set includes BLE, SIM115, SIM117 and RUF059. Its Global Constraints promise "ruff + mypy strict clean" code blocks, and W1–W4 and W6 contradict that. I count this once here, in addition to the workarounds.
- **M-n.** `incident.incident_seq` has gaps. The gate run's receipt was INC-000025 after only a few real incidents, because `nextval` is consumed by conflicting and rolled-back inserts. This is harmless, but the documents read like a dense numbering.

## Risky

- **RA (high; reproduced).** The worker's `HttpMcpCaller.call` has W5's pattern: `except (MCPError, httpx2.HTTPError)` sits outside the `async with`.
  - Probe: I killed mcp-read and admitted a run. worker.log shows `ERROR ops_worker: job f56cba60… failed` with `ExceptionGroup … httpx2.ConnectError: All connection attempts failed`.
  - Five seconds later the run was `RETRIEVING` with events `['run.accepted','tool.started']`, and the job was `investigate|claimed|attempts 1|not done`.
  - The plan intends `McpCallFailed` → `_fail(FAILED, run.failed, "retrieval failed")`. That path is unreachable for any transport-level failure, including a 401 refusal, so the run and its conversation slot stay held forever (no reclaim until T13).
  - The same applies to `execute`: the job is left claimed instead of finished.
  - No test covers it.
- **RB (R9 persists, declared debt T13).** The kill-mid-investigate probe (probe 7) shows the run stays `RETRIEVING` permanently and the read handle stays unrevoked until its TTL.
- **RC (R8 persists).** Every live run rewrites the committed evidence and two Plan B report files, so the tree is dirty after any live run.
- **RD.** Each e2e run leaves its R105 run in `app.runs` (by design, it is evidence), plus three invocation handles per run that are never revoked (declared debt T15). After 7 e2e invocations and probes, `app.invocation_context` holds 12 or more rows.
- **RE (R5, now documented).** The runbook's step 4 tells the reader to have no skeleton running before `pytest tests/e2e`. A port collision with `skeleton.py up` is still possible if that is ignored. Not re-probed.
- **RF (R6).** `pids.json` records trampoline PIDs. `down` works because of the trampoline's job object; I verified that the ports were free afterwards.
- **RG (R10).** `postgres_incident_password` stays in the shared secrets dir. It is now in `SECRET_NAMES`, so it is expected there.

## Round-1 items: gone or persisting

- **Workarounds W1–W20.**
  - W1 is gone: the plan now runs `ruff format` before `check.py`.
  - W2 is gone: the version table is in `public`.
  - W3 is gone: `event_rules_ok` runs before `Event`.
  - W4 and W6 are gone: the plan's ruff step covers them.
  - W5 is gone: no mypy `no-any-return`.
  - W7 is gone: `model_validate_json` is used.
  - W8 is gone: dependencies use `Annotated`.
  - W9 is gone: `Verifier` is a Protocol.
  - W10 is gone.
  - W11 is gone: a seeded tenant is used.
  - W12 is gone: `AnyHttpUrl`.
  - W13 is gone: explicit `append_event` arguments.
  - W14 is gone: no `__future__` in the FastAPI modules.
  - W15 is gone.
  - W16 is gone: `own_job`.
  - W17 is partly gone. The RUF100 comment deletion no longer happens, but SIM117 recurs in a new place (worker/mcp.py, now W4).
  - W18 is gone: the `serve_app` selector loop works.
  - W19 and W20 are gone: autocommit plus `Session.unit()`. After the e2e, the destination key is visible from a fresh connection (probe 4).
  - **New this round:** W1 (BLE001), W2 (`serve_app` typing), W3 (RUF059), W4 (SIM117), W5 (ExceptionGroup, Blocking), W6 (SIM115).
- **Risky R1–R13.**
  - R1 is gone (probe 3).
  - R2 is mitigated by the `Session` lock, which serialises requests (pools arrive with T13).
  - R3 is mitigated: the live tests are hermetic and only R105 runs remain.
  - R4 is gone (probe 1).
  - R5 is documented in the runbook.
  - R6 persists.
  - R7 is gone: `status` showed all five ready three times in a row.
  - R8 persists (RC).
  - R9 persists (RB, declared debt).
  - R10 persists (RG).
  - R11 was not observed (nine `check.py` runs, all clean).
  - R12 is gone: `migrate` from `migrations/` printed "MIGRATE: app and incident at head".
  - R13 is mitigated: in-process servers bind 18081 and 18090.
- **Misleading M13–M24.**
  - M13 is gone (16 passed).
  - M14 is gone (8 passed).
  - M15 and M15b are gone: `force_rollback` and `purge_run`; after Tasks 2–8 the database held 0 runs, 0 jobs and 2 tenants.
  - M16 is partly fixed: the replay was added, but the conflict claim is still in Focus 5 (M-i).
  - M17 is gone: `RECORDED_LOCALLY_LIVE`.
  - M18 is gone.
  - M19 is gone.
  - M20 is gone: Expected now says ImportError.
  - M21 is partly fixed (M-c).
  - M22 is gone: the test asserts the file exists.
  - M23 is gone: the commit range is resolvable (`45ec318..ef2cf33`).
  - M24 is gone: no duplicate debt line.

## Probes

1. **e2e order.**
   - Reverse file order (worker → tokens → r105 → migrations → mcp_write → mcp_read → incident_sim): `11 passed in 25.85s`.
   - Forward, twice: `11 passed in 25.76s`, then `11 passed in 25.63s`.
   - No port collisions and no order dependence (R4 gone).
2. **Leftover rows after the live gate:**
   - `SELECT count(*) FROM app.runs` → 4, all `SUCCEEDED`: one R105 run per e2e invocation (the failed first run, the W5 rerun and the gate run), plus one from the run before the gate.
   - `app.jobs WHERE done_at IS NULL` → 0.
   - `app.tenants` → 2 (the seeded two).
   - Also: `app.conversations` 4 and `app.invocation_context` 12 (RD). Nothing from the other live tests.
3. **Worker health under load.**
   - Setup: `skeleton.py up`, with 4 threads hammering `GET :8070/health/ready` for 30.0 s (33,153 hits, all 200).
   - Run admitted, then `AWAITING_APPROVAL` at t=1.1 s. sam approved (200), and the run reached `SUCCEEDED` at t=2.4 s.
   - `pg_stat_activity` "idle in transaction" was 0 during and after.
   - A second, unhammered run reached `AWAITING_APPROVAL`.
   - **R1 is gone:** the separate probe connection works.
4. **Destination committed its key.** From a new connection as role `incident` (`probe4.py`), `SELECT state, incident_id FROM incident.action_key WHERE action_id = '4d408b10-ad09-49d5-beb4-1c97169d31aa'` returned `{'u': 'incident', 'state': 'COMMITTED', 'incident_id': 'INC-000025'}`, matching the evidence file.
5. **`check.py` twice:** `443 passed, 41 skipped, 1 warning in 28.16s` / GREEN, then `… in 25.83s` / GREEN. No order dependence.
6. **`skeleton.py up`, `status` ×3, `down`.**
   - `UP: incident-sim:8090, mcp-read:8081, mcp-write:8082, api:8000, worker:8070`.
   - `status` showed all five `ready` three times, 1 s apart (R7 gone).
   - `down` printed DOWN for all five; the worker PID was the restarted one from probe 7.
   - `netstat` for :8000/8070/8081/8082/8090/18081/18090 LISTEN → **0**, and `status` showed all `down`.
7. **Kill mid-investigate.** I blackholed 8081 with a socket that accepts and never answers, admitted a run, waited for `tool.started`, then sent SIGTERM (TerminateProcess) to the worker. After a restart and 8 s:
   - run `RETRIEVING|2`
   - history `1:QUEUED:create_run, 2:RETRIEVING:transition_run`
   - events `1:run.accepted, 2:tool.started` (gap-free)
   - job `investigate|JPC:90036|1|not done`
   - handle `read|not revoked|unexpired`
   - idle in transaction 0
   - **"Left claimed" still holds with the autocommit connection, and nothing is corrupt.** The run and its slot stay stuck (RB).
- **Extra probe (RA):** mcp-read was killed and the run was admitted. The worker crashed with `ExceptionGroup(httpx2.ConnectError)` and the run stayed `RETRIEVING` instead of becoming `FAILED`.

## Execution log per task

### Task 1 (2.6 min)
- Step 1: 10 debt lines appended (M-b) and committed `45ec318`.
- Step 3: collection error, ImportError, as expected.
- Step 4: lock as above.
- Step 6: 5 passed.
- Step 8: `bootstrap_dev.py secrets` → "0 created, 13 kept". plan_b: 38 passed, 10 skipped.
- Step 9: down/up took 35.8 s; "bootstrap admin: deleted"; live 9 passed in 33.58s.
- Step 10: ruff reformatted settings.py; GREEN 386/30. `reports/bootstrap/bootstrap-admin.txt` was left modified (M-k).

### Task 2 (1.5 min)
- Step 1: ImportError.
- Step 5: 9 passed.
- `migrate` ran twice: "MIGRATE: app and incident at head" both times.
- Live: 5 passed in 1.04s. Ungated: 5 skipped.
- Database afterwards: runs 0, jobs 0, tenants 2.
- ruff: 6 files reformatted, 1 fix. GREEN 395/35. verify_handoff exit 0.

### Task 3 (0.9 min)
- Unit: 16 passed, 1 warning.
- Live: 1 passed in 5.49s.
- ruff: 3 reformatted, 1 fix. GREEN 411/36.

### Task 4 (2.0 min)
- Unit: 8 passed on the first try.
- Live: 1 passed.
- RED as written (W1, W2) → GREEN 419/37.

### Task 5 (1.6 min)
- Unit: 5 passed.
- Live: 1 passed in 4.77s, with 0 runs and 0 handles left.
- RED as written (W1, W2) → GREEN 424/38.

### Task 6 (1.9 min)
- Unit: 8 passed.
- Live: 1 passed in 2.16s. `incident.action_key` holds `COMMITTED|INC-000004` (durable), and the app rows were purged.
- RED as written (W1, W2, W3) → GREEN 432/39. Live re-run: 1 passed.

### Task 7 (1.3 min)
- Unit: 6 passed on the first try.
- RED as written (W1, W2, W3) → GREEN 438/39.

### Task 8 (1.6 min)
- Unit: 4 passed.
- Live: 1 passed in 1.42s.
- RED as written (W1, W3, W4) → GREEN 442/40. Live re-run: 1 passed.

### Task 9 (5.6 min)
- `status`: all down.
- e2e run 1: `1 failed, 10 passed in 26.03s` (W5).
- e2e run 2: `11 passed in 25.92s`; evidence written.
- Evidence tests: 3 passed.
- Docs steps done; the PROJECT_HISTORY placeholder is marked (M-l).
- ruff left SIM115 (W6) → GREEN 443/41. verify_handoff exit 0; both JSON files load.
- Two commits.
- Gate: 20 passed in 58.79s.

## Cleanup proof

**Processes.**
- `skeleton.py down` printed DOWN for all five; the blackhole PID 106036 was killed.
- `netstat -ano | grep -E ":(8000|8070|8081|8082|8090|18081|18090) .*LISTEN" | wc -l` → **0**.
- `skeleton.py status` → all `down`.
- After the main stack restart, the same netstat count was **0** again.

**Statements** (`docker exec ops-copilot-postgres-1 psql -v ON_ERROR_STOP=1 -U ops`):
- db `ops`: `DROP SCHEMA app CASCADE; DROP TABLE IF EXISTS public.alembic_version` → DROP SCHEMA, DROP TABLE.
- db `incident`: `DROP SCHEMA incident CASCADE; DROP TABLE IF EXISTS public.alembic_version; REASSIGN OWNED BY incident TO ops; DROP OWNED BY incident` → DROP SCHEMA, DROP TABLE, REASSIGN OWNED, DROP OWNED.
- db `ops`: `REASSIGN OWNED BY incident TO ops; DROP OWNED BY incident` → done.
- db `postgres`: `REASSIGN OWNED …; DROP OWNED …; REVOKE ALL ON DATABASE incident FROM incident; DROP ROLE IF EXISTS incident` → REVOKE, DROP ROLE.

**Verification queries.**
- ops: `select nspname from pg_namespace where nspname in ('app','incident')` → (none); `select to_regclass('public.alembic_version')` → NULL.
- incident: the same two queries → (none) / NULL.
- postgres: `select count(*) from pg_roles where rolname='incident'` → **0**. Databases: `incident,ops,postgres,template0,template1`. Database `incident` pre-existed and is kept.

**Stack restarted from the main checkout root.**
- Commands: `uv run --frozen --no-sync python scripts/bootstrap_dev.py down`, then `… up` (41 s).
- Result: postgres and keycloak Healthy, "bootstrap admin: deleted".
- The realm well-known endpoint answers 200, and the committed realm (no `aud ops-api` mapper) is imported.
- Main checkout: `git status --short` was empty before and after, HEAD `bb92b5f`, branch `plan-d`. I made no edits there.

**Left in place:**
- The worktree, with `runtime/skeleton/*.log` and three modified tracked report files.
- The secret file `postgres_incident_password` in the shared secrets dir (RG).

## Worktree and commits

Path: `<scratch>` (detached from `bb92b5f`).

```
c95e20f docs: handoff state after Plan D (T08 done; skeleton debt owed to T09-T30)
ef2cf33 feat(skeleton): process harness, the R105 end-to-end proof and its evidence
00f6c52 feat(worker): polling loop with investigate (read tool, fake draft, freeze) and execute (write tool) handlers
f0e7022 feat(api): admission to a queued run, proposal document, independent decision with exact binding, events
6e74c0c feat(mcp-write): grant, mark_sent, destination call and record_outcome behind the create_incident tool
183cea5 feat(mcp-read): authenticated read server with search_procedures over the fixture corpus and handle resolution
775c969 feat(incident-sim): atomic action_key destination with hash recomputation and conflict documents
b6f30db feat(core): one JWKS-backed token verifier (iss, aud, azp, exp, signature) for every resource server
11c3114 feat(core): Alembic revision 1 for the app and incident databases, the shared persistence adapter and skeleton.py migrate
03c93f3 feat(dev): ops-api audience for persona tokens, incident database secret, skeleton dependencies and the shared settings module
45ec318 docs: declare the walking skeleton's shortcuts before coding (T08 debt list)
```

## Suggested plan fixes (for the planner)

1. **MCP client error handling (W5, RA).**
   - Catch errors from the MCP client where they surface: wrap the whole `async with` and handle both `MCPError` and an `ExceptionGroup` whose `subgroup(MCPError | httpx2.HTTPError)` is not None. Alternatively, catch inside the block around `call_tool` and still guard the exit.
   - Apply it in `worker/mcp.py::HttpMcpCaller.call` and in the e2e `mcp_call`.
   - Add a unit test with a stub transport that refuses, so that `McpCallFailed`, and therefore `FAILED`, is pinned.
2. **Lint gates.**
   - Add `# noqa: BLE001 - <why>` to the five readiness handlers, and `# noqa: SIM115 - <why>` to `Skeleton.start`'s `open`.
   - Type `serve_app(app: ASGIApp, …)` with `from starlette.types import ASGIApp` in all four copies.
   - Use `_` for unused unpacked names in test_mcp_write_live, test_api `test_runs_are_tenant_scoped` and test_worker_live.
   - Write worker/mcp.py with the parenthesised `async with`.
3. **Cosmetics.**
   - Task 9 "9 passed" → 11.
   - "eight lines" → ten.
   - "21 rulings" → 25, and renumber 22–25 after 21.
   - Fix the incident env.py error text.
   - Give mcp-write server.py a docstring.
   - Make the mcp-read live code block self-consistent (UUID import, no `urls`).
   - Put `ruff` before `check.py` in Task 3.
   - Drop "and the e2e test" from Review Focus 5, or add a different-hash POST to the e2e.
   - Add `reports/bootstrap/bootstrap-admin.txt` to Task 1's `git add`, or note that live runs dirty the report files.

---

## Round 3 — closure check and delta execution

# Plan D critic, round 3 (closure + delta execution)

- **Plan:** `docs/superpowers/plans/2026-10-08-first-slice-d-walking-skeleton.md` at `plan-d` HEAD `a6d72de` (5,704 lines).
  `P:<n>` = plan line at `a6d72de`. Round-2 delta = `git diff bb92b5f..a6d72de -- docs/superpowers/plans/` (142+/62-).
- **Inputs:** `static-r2.md` (N1-N4, m1-m12, closure table), `builder-r2.md` (W1-W6, M-a..M-n, RA-RG, round-1 list).
- **Worktree:** the round-2 builder's `scratchpad/pland-dry2` (detached at `c95e20f`), edited in place, left uncommitted.
  Main checkout untouched: `git status --short` empty before and after, HEAD `a6d72de`.
- **Scripts/logs:** `scratchpad/r3/`: `ext.py` (fence-line block extractor, reads the plan read-only from the main
  checkout), `mkwrite.py` (assembles mcp-write `server.py` per P:3498-3543), `delta.diff`, `check1.log`, `live1.log`,
  `live2.log`, `admit.py`, `probe_n3.py`, `worker_poll.log`, `worker_all.log`, `branch.py`.
- Stance: default UNPROVEN. No token or secret value was printed; no system setting was changed; no `down -v`.

## Verdict: READY TO EXECUTE

Every changed block, transcribed verbatim and passed through the plan's own `ruff format` / `ruff check --fix`, gives
`CHECK: GREEN` with no manual edit; the live suite is `20 passed`. RA is fixed and measured (FAILED, `done_at` set).
N3 is fixed: a dead poll connection takes the worker down within 0.3 s. **0 Blocking, 0 Important**, 4 new Minor, plus
5 Minor carry-overs that are neither closed nor declared.

## Part A — closure table

### Static round 2: new Important (N1-N4)

| Finding | Status | Plan line | Evidence |
|---|---|---|---|
| N1 `check.py` RED after ruff (BLE001 ×5, RUF059 ×4, SIM117, SIM115) | closed | P:2320, P:2908, P:3617, P:4387, P:5130 (narrowed `except (psycopg.Error, OSError)`); P:3748, P:3935, P:5244 (`_`); P:4885-4890 (one `async with`); P:5380 (`noqa: SIM115`); P:26 names the rule set | `ruff check --fix` on the 16 changed paths: "Found 11 errors (11 fixed, 0 remaining)"; `check.py` ruff "All checks passed!", format "149 files already formatted" |
| N2 mypy `serve_app(app: object)` ×4 | closed | P:2372/2378, P:2745/2925, P:3525 (+ the copy), P:4499/4505 | `check.py` mypy: "Success: no issues found in 36 source files" |
| N3 worker ready after its poll loop died | closed | P:5097-5115 (claim inside `try`, `OperationalError` re-raised), P:5118-5131 (`polling_alive`), P:5150-5160 (`asyncio.wait(FIRST_COMPLETED)`) | Probe 2: worker exits 0.3 s after its poll backend is terminated (see the new Minor n1 about how it exits) |
| N4a I9 per-service `tests/` | closed | P:67 (ruling 26) | ruling text |
| N4b M8 purges delete from append-only tables | closed | P:68 (ruling 27), P:1356-1361 (purge docstring) | ruling text |
| N4c R6 trampoline PIDs | closed | P:5447 | Probe 1: terminating mcp-read's real interpreter (PID 57900) also ended its launcher (87128 "not found"); `down` freed every port (netstat count 0) |
| N4d R11 incremental mypy flake | closed | P:26 | note present; not observed this round |

### Static round 2: partial/open/parked rows of its closure table

| Finding | Status | Plan line | Evidence |
|---|---|---|---|
| I2 ruff | closed | P:26 + every gate | = N1 |
| I5 coverage claims (CONFLICT in e2e) | closed | P:36 | "the e2e test exercises the replay with the same hash only" |
| I9 per-service tests | closed | P:67 | = N4a |
| M5 evidence side effects | closed | P:445 (`bootstrap-admin.txt` staged), P:5652-5654 | runbook step 5 names `reports/bootstrap/*.txt` |
| M6 post-hoc prose edits | **partial** | P:454, P:996, P:1879, P:1888, P:2210, P:2939, P:3709 | P:3022's note is gone (M-g closed); the others remain → carry-over c1 |
| M8 append-only deletes | closed | P:68 | = N4b |
| M11 interface drift | **partial** | P:457, P:4555, P:5068 | `ACTIVE_STATES` still "consumed"; Task 8 Produces lists `HttpMcpCaller(token_source)` and `health_app(deps)` (the real signatures are `(token_source, *, connect_timeout)` and `(probe, polling_alive)`); worker docstring "one connection" (it opens two) → c2 |
| M14 issuer frozen at migration | **open** | P:803-804 | not in the debt list P:74-83 → c3 |
| W6 `import time` note | **partial** | P:1879 | still a prose note (works; part of c1) |
| W15 RUF059 test_api | closed | P:3935, P:3974, P:4030 | `c, _ = api` |
| W17 worker ruff | closed | P:4885-4890 | SIM117 gone |
| M16 e2e CONFLICT claim | closed | P:36 | = I5 |
| M21 `uv.lock` "additions only" | closed | P:233 | "mostly additions ... plus a few rewritten `requires-dist` lines" |
| R3 live leftovers / running skeleton | **partial** | P:5649-5651 | "never collide with a running skeleton" stays; Tasks 5/6 live tests commit claimable jobs → c4 |
| R6 trampoline | closed | P:5447 | = N4c |
| R8 evidence rewritten | closed (declared) | P:5652-5654 | runbook step 5 |
| R9 crash leaves run stuck | parked-and-declared | P:79 | debt line "no reclaim ... → T13/T14" |
| R11 incremental mypy | closed | P:26 | = N4d |

### Builder round 2: workarounds W1-W6

| Finding | Status | Plan line | Evidence |
|---|---|---|---|
| W1 BLE001 | closed | P:2320, P:2908, P:3617, P:4387, P:5130 | the narrowed tuple replaces the builder's `noqa`; ruff clean |
| W2 `serve_app` typing | closed | P:2378, P:2925, P:4505 (+ mcp-write copy) | mypy clean |
| W3 RUF059 | closed | P:3748, P:3935, P:5244 | ruff clean |
| W4 SIM117 worker/mcp.py | closed | P:4885-4890 | ruff clean |
| W5 e2e `mcp_call` ExceptionGroup (Blocking) | closed | P:5471 (import), P:5499-5513 | live suite `20 passed`; the mcp-write wrong-token loop passes with the plan's `failure_leaf` version |
| W6 SIM115 | closed | P:5380 | ruff clean with the plan's comment text |

### Builder round 2: Misleading M-a..M-n

| Finding | Status | Plan line | Evidence |
|---|---|---|---|
| M-a "9 passed" | closed | P:5630 | "11 passed"; measured `tests/e2e` = 11 of the 20 |
| M-b "eight lines" | closed | P:126 | "ten lines"; the block P:74-83 has 10 |
| M-c `uv.lock` additions only | closed | P:233 | |
| M-d "21 rulings", order | closed | P:5672, P:62-68 | "27 rulings"; 21 now sits between 20 and 22 |
| M-e incident env.py RuntimeError | closed | P:826 | applied: `migrations/incident runs only through ...` |
| M-f mcp-write docstring/comment | closed | P:3534-3538 | docstring and two-line comment given; the docstring is 199 columns (new Minor n3) |
| M-g mcp-read live block | closed | P:2965, P:2984-2985 | `from uuid import UUID`, no `urls`; the old trailing note is gone |
| M-h Task 3 ruff after check | closed | P:1930 | one command: ruff, then `check.py` |
| M-i Focus 5 CONFLICT claim | closed | P:36 | |
| M-j "spawn no children" | closed | P:5447 | |
| M-k three dirty report files | closed | P:445, P:5652-5654 | |
| M-l PROJECT_HISTORY placeholder | parked-and-declared | P:5673 | the plan allows a marked placeholder when the controller supplies no list |
| M-m ruff rule set unstated | closed | P:26 | "ruff 0.16's default rules include I, B, SIM, BLE and RUF" |
| M-n incident number gaps | closed | P:860 | SQL comment; this round's receipt was INC-000009 after a fresh migrate |

### Builder round 2: Risky RA-RG

| Finding | Status | Plan line | Evidence |
|---|---|---|---|
| RA worker transport failure leaves run RETRIEVING | closed | P:4857-4900, P:4623-4640 | Probe 1: run `FAILED`, events `run.accepted, tool.started, run.failed`, job `done_at` set; unit test exercises the group branch (`branch.py`: raw escape is `ExceptionGroup[ConnectTimeout]`, `McpCallFailed.__cause__` is `ConnectTimeout`) |
| RB crash mid-investigate leaves run stuck | parked-and-declared | P:79 | debt line (T13/T14) |
| RC live runs dirty the tree | closed (declared) | P:5652-5654 | |
| RD R105 rows and unrevoked handles | parked-and-declared | P:81 (handles → T15) | R105 rows are evidence by design; probe 1's read handle was also left unrevoked (T15) |
| RE port collision if a skeleton runs | parked-and-declared | P:5646 (step 4: run with everything `down`) | |
| RF trampoline PIDs | closed | P:5447 | = N4c |
| RG incident secret left | closed (by design) | P:425 | in `SECRET_NAMES` |

### Supplementary: static round-2 Minors m1-m12

m1 closed (P:36); m2 closed (P:5630); m3 closed (P:126, P:5672, P:62-68); m4 partial (= M6, c1); m5 closed (P:1930);
m6 partial (= M11, c2); **m7 open** (P:5610-5612: docstring "Absent evidence is not a failure" vs P:5618's assert → c5);
m8 partial (= R3, c4); m9 closed (P:445, P:233); m10 closed (P:1062-1064, `Session` docstring); **m11 open** (debt list
P:74-83 unchanged: one connection with no reconnect, the `execute` job finished after `McpCallFailed` leaving the run
APPROVED, the frozen issuer → folded into c3); m12 declined again (NUL in payload strings not examined).

### Totals

49 rows (N1-N4 + 18 static partial/open/parked rows + W1-W6 + M-a..M-n + RA-RG): **closed 39, partial 4, open 1,
parked-and-declared 5.** The 5 non-closed, undeclared items (M6/W6, M11, M14 + m11, R3/m8, m7) are listed below as
carry-over Minors c1-c5. None of them stops a task.

## Part B — delta execution in the kept worktree

### What was replaced (verbatim from `a6d72de`)

Whole-file blocks re-extracted by fence line with `r3/ext.py` and written over the builder's files:
`migrations/incident/versions/0001_walking_skeleton.py` (fence 828), `incident-sim/.../app.py` (2216),
`incident-sim/.../__main__.py` (2365), `mcp-read/.../server.py` (2714, plus P:2939's `import asyncio`/`import sys`),
`tests/e2e/test_mcp_read_live.py` (2959), `tests/e2e/test_mcp_write_live.py` (3649), `tests/plan_d/test_api.py` (3821),
`api/.../app.py` (4269), `api/.../__main__.py` (4492), `tests/plan_d/test_worker.py` (4561), `worker/.../mcp.py` (4836),
`worker/.../main.py` (5067), `tests/e2e/test_worker_live.py` (5185), `tests/e2e/test_r105_walking_skeleton.py` (5453).
`mcp-write/.../server.py` rebuilt per P:3498-3543 (docstring, import block 3500, comment 3536, the mcp-read
definitions copied verbatim, block 3543). `scripts/skeleton.py`: the P:5380 `noqa` line and the P:5444 comment.
`migrations/incident/env.py`: P:826's RuntimeError text.

Gate (the plan's step, on those 16 paths):

```
$ uv run ruff format <16 paths>
11 files reformatted, 5 files left unchanged
$ uv run ruff check --fix <16 paths>
Found 11 errors (11 fixed, 0 remaining).
```

Result versus the builder's committed workaround tree (`git diff --stat`, reports excluded): 13 files, 113+/41-.
Every hunk is a round-2 delta item and nothing else: the four readiness `except` clauses plus their `import psycopg`;
mcp-write's docstring; env.py's message; the sequence comment; the `noqa`/status comment in skeleton.py;
`tenant, _, run, ...`; `mcp_call`'s `failure_leaf` branch; the new worker unit test; `main.py`; `mcp.py`. The
transcribed blocks of `test_api.py`, `test_mcp_read_live.py`, `test_worker_live.py`, both `__main__.py` files and
`mcp-read/server.py`'s `serve_app` are byte-identical (after the formatter) to the builder's workaround versions.
Full diff: `scratchpad/r3/delta.diff`.

### `check.py`

```
$ PYTHONUTF8=1 uv run python scripts/check.py
... ruff check .            All checks passed!
... ruff format --check .   149 files already formatted
... mypy core/src api/src worker/src mcp-read/src mcp-write/src asset-sim/src incident-sim/src
Success: no issues found in 36 source files
444 passed, 41 skipped, 1 warning in 27.22s
CHECK: GREEN
```

(444 = the builder's 443 + the new transport test. The warning is the known PyJWT HS256 key-length warning.)

### Migrate (first run on a dropped database)

Before: no `app`/`incident` schema, `public.alembic_version` NULL, role `incident` count 0.
`uv run python scripts/skeleton.py migrate` → `MIGRATE: app and incident at head` (exit 0).

### Live suite

First attempt: `3 failed, 17 passed in 48.97s` — `test_r105` (`KeyError: 'conversation_id'` on admission),
`test_tokens_live` (`MissingRequiredClaimError: Token is missing the "aud" claim`), Plan B's
`test_persona_token_sub_equals_seed_id` (`KeyError: 'aud'`). Cause: environmental. Round 2's cleanup restarted the
stack from the main checkout, whose realm has no `ops-api` audience mapper (Task 1 adds it, and Task 1 Step 9
restarts the stack with it). Not a plan defect. I restarted the stack from the worktree root
(`uv run --no-sync python scripts/bootstrap_dev.py down` then `up`: Healthy, "bootstrap admin: deleted") and reran:

```
$ OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e tests/plan_b/live -q -p no:cacheprovider
20 passed in 59.48s
```

Evidence file (`reports/skeleton/r105-walking-skeleton.txt`):

```
R105 walking skeleton — 2026-10-08T14:00:35Z
run_id=8bccd4e5-5396-45f6-b667-eaf77eb21968 accepted status=QUEUED
proposal_id=8550f1df-5474-41a1-8683-bef250997df6 revision=1 payload_sha256=22963043e8729efc8a0c10590cb6a59956cdb845a632c772b7a605e54fe8c1a6 evidence=['ALPHA-TRIAGE:v1:scope']
state=SUCCEEDED state_version=7 action_id=c73e8f57-d73e-480d-a792-d8227111ac51 incident_id=INC-000009
events=run.accepted,tool.started,tool.completed,explanation.ready,proposal.ready,approval.recorded,action.granted,action.dispatched,action.confirmed
replay=same_action_id refusals=api:worker,destination:persona+worker,mcp-write:persona+mcp-read
```

## Part C — probes

### Probe 1 (RA): mcp-read dies before an investigate job

1. `skeleton.py up` → `UP: incident-sim:8090, mcp-read:8081, mcp-write:8082, api:8000, worker:8070`; `status` all ready.
2. Control run as alex (`r3/admit.py`): `a6e562af-…` → `AWAITING_APPROVAL after 1.0s`, events
   `run.accepted, tool.started, tool.completed, explanation.ready, proposal.ready`.
3. `taskkill /F` on the :8081 listener (PID 57900, the real interpreter). Its launcher PID 87128 was already gone
   ("not found"). LISTEN count on 8081 → 0. `status`: `mcp-read down`, the other four ready.
4. Second run `8d87be6b-5324-43bb-af7c-e95ca23e048c` → `state FAILED after 2.6s`, events
   `['run.accepted', 'tool.started', 'run.failed']`.
5. Database:
   - `app.runs`: `FAILED | state_version 3`.
   - `app.jobs`: `investigate | claimed t | attempts 1 | done_at 2026-10-08 14:02:03.927194+00`.
   - `app.events`: `1 run.accepted`, `2 tool.started`, `3 run.failed` (all source `application`).
   - The read handle: not revoked (declared debt, T15).
6. worker.log: `WARNING ops_worker: investigate job 082095b1-…: retrieval failed: search_procedures: transport or
   protocol failure`.
7. `skeleton.py down` → DOWN for all five; `status` all down; LISTEN count 0.

**Result: closed.** Round 2 left the run stuck in `RETRIEVING` with its job claimed. Now the run is `FAILED` and the
job is finished.

### Probe 2 (N3): the worker's poll connection dies

`r3/probe_n3.py` starts `python -m ops_worker` alone with `scripts.skeleton.process_environment()`. It waits for
`/health/ready` = 200, finds the worker's two new `ops` backends by their absence from a before-snapshot, terminates
backends with `pg_terminate_backend`, then polls `/health/ready` and the process every 0.25 s.

- **Mode `poll`** (only the earlier backend, last query `COMMIT` = the claim transaction; the probe backend's last
  query is `SELECT 1`):
  `ready before kill: 200 at 1.6s` → `t+0.0s 200 exit=None` → `t+0.3s conn-error exit=0`.
  worker log: `ERROR ops_worker: database connection lost; the poll loop stops and readiness turns 503`, then the
  traceback ending in `psycopg.errors.AdminShutdown: terminating connection due to administrator command` at
  `run_forever`'s `async with deps.conn.transaction()`.
- **Mode `all`** (both backends):
  `t+0.1s 503 {"status":"not ready"}` → `t+0.3s conn-error exit=0`.

**Result: closed.** A lost poll connection now ends the process within about 0.3 s, where round 2 answered 200
indefinitely. Readiness shows 503 only for that brief window: the process exits, so `status` reports `down`, not 503,
and the **exit code is 0** (new Minor n1).

### Probe 3: `test_transport_failures_become_one_exception_type` ×3

| Run | Call duration | Summary |
|---|---|---|
| 1 | 1.23 s | `1 passed in 1.52s` |
| 2 | 1.19 s | `1 passed in 1.48s` |
| 3 | 1.17 s | `1 passed in 1.46s` |

This matches P:4830 ("about a second on Windows"). `r3/branch.py` confirms the test goes through the `BaseExceptionGroup`
branch, not the direct `except`. The raw client escape is `ExceptionGroup[ConnectTimeout]`, so the test does pin RA.

## New findings

### Blocking (0)

None.

### Important (0)

None.

### Minor (new this round)

- **n1. On a lost connection the worker exits 0, and its text promises a 503 it barely serves** (P:5107-5108,
  P:5150-5160, P:5101-5102, P:5444). `_main` swallows the poll task's exception
  (`gather(..., return_exceptions=True)`) and returns normally, so the process exits with code 0 (measured, both modes).
  The log line and the `status` comment say "readiness turns 503", but the process is gone 0.3 s later and `status`
  shows `down`. A restart-on-failure supervisor (T30) would not restart it.
  *Fix:* after the `finally`, `if polling.done() and polling.exception(): raise SystemExit(1)` (or re-raise), and word
  the log line and comment as "the worker exits".
- **n2. `except psycopg.OperationalError` is wider than "connection lost"** (P:5107). `DeadlockDetected`,
  `SerializationFailure`, `QueryCanceled` and `LockNotAvailable` are all `OperationalError` subclasses (measured), so a
  transient error inside any handler ends the worker process, not only a dead connection. Rare in the single-worker
  READ COMMITTED skeleton.
  *Fix:* test `deps.conn.closed` / `deps.conn.broken` in the handler, or catch the broad class and re-raise only when
  the connection is closed.
- **n3. ≤120 columns is not enforced** (P:25, P:3534). mcp-write's dictated one-line module docstring is 199 columns.
  Ruff's default set has no E501, and the hygiene test does not measure line length, so the gate passes. Pre-existing
  docstrings and strings over 120 also exist (for example P:829 at 123, P:895 at 164, P:2403 at 122).
  *Fix:* wrap the mcp-write docstring like mcp-read's, or state that the limit binds code only.
- **n4. The first live run fails unless the stack runs the Task 1 realm.** This is environmental, not a plan defect:
  Task 1 Step 9 restarts the stack. A reviewer or executor who resumes on a stack restarted from `main` gets 3 failures
  (`aud` missing). One sentence in the runbook ("restart the stack from this branch after pulling Task 1") would save
  the confusion.

### Minor (carry-overs: neither closed nor declared)

- **c1** (M6/W6/m4) Post-hoc prose edits remain at P:454, P:996 (stale `version_table_schema` note), P:1879,
  P:1888, P:2210, P:2939, P:3709. They are harmless, and the transcription above shows P:2939's still works.
- **c2** (M11/m6) Interface drift at P:457 (`ACTIVE_STATES`), P:4555 (Task 8's Produces line now carries both the
  new `ops_worker.mcp` list and the old `HttpMcpCaller(token_source)` / `health_app(deps)`), and P:5068 (the worker
  docstring says "one connection"; it opens two).
- **c3** (M14/m11) Undeclared shortcuts: membership issuer frozen at migration (P:803-804); one connection per
  process with no reconnect (api, mcp-read, mcp-write and incident-sim stay at 503 forever after a drop; the worker now
  exits); an `execute` job finished after `McpCallFailed` leaves the run APPROVED (P:5044-5046, `TODO(T22)` only).
  None of these is in the debt list (P:74-83).
- **c4** (R3/m8) P:5651 "never collide with a running skeleton". Ports do not collide, but the Task 5/6 live tests
  commit claimable jobs that a running skeleton worker would act on.
- **c5** (m7) `test_skeleton_evidence`'s docstring says "Absent evidence is not a failure" (P:5612), but the test
  asserts presence (P:5618).

## Part D — cleanup proof

**Processes.**
- `skeleton.py down` → DOWN for all five; `status` all down.
- Both probe-2 workers had exited (exit 0).
- `netstat -ano | grep -E ":(8000|8070|8081|8082|8090|18081|18090) .*LISTEN" | wc -l` → **0**, before the stack
  restart and after it.

**Statements** (`docker exec ops-copilot-postgres-1 psql -v ON_ERROR_STOP=1 -U ops`):
- db `ops`: `DROP SCHEMA app CASCADE; DROP TABLE IF EXISTS public.alembic_version` → DROP SCHEMA, DROP TABLE.
- db `incident`: `DROP SCHEMA incident CASCADE; DROP TABLE IF EXISTS public.alembic_version; REASSIGN OWNED BY
  incident TO ops; DROP OWNED BY incident` → DROP SCHEMA, DROP TABLE, REASSIGN OWNED, DROP OWNED.
- db `ops`: `REASSIGN OWNED BY incident TO ops; DROP OWNED BY incident` → done.
- db `postgres`: `REASSIGN OWNED …; DROP OWNED …; REVOKE ALL ON DATABASE incident FROM incident; DROP ROLE IF
  EXISTS incident` → REVOKE, DROP ROLE.

**Verification queries.**
- `ops`: schemas `app`/`incident` → none; `to_regclass('public.alembic_version')` → NULL.
- `incident`: schemas → none; `to_regclass` → NULL.
- `postgres`: `pg_roles` count for `incident` → **0**; databases `incident,ops,postgres,template0,template1` (database
  `incident` pre-existed and is kept).
- After the main-checkout restart: role count still 0 and schema count 0.

**Stack restarted from the MAIN checkout root.**
- Commands: `uv run --no-sync python scripts/bootstrap_dev.py down`, then `up`.
- Result: postgres and keycloak Healthy, "bootstrap admin: deleted"; the realm's well-known endpoint answers 200.
- This is the committed realm at `a6d72de`, which has no `ops-api` audience mapper.
- Main checkout: `git status --short` empty before and after, HEAD `a6d72de`.

**Left in place:**
- The worktree `scratchpad/pland-dry2`, detached at `c95e20f`, with this round's uncommitted edits (13 source/test
  files and the three rewritten report files) and `runtime/skeleton/*.log`.
- The scripts and logs in `scratchpad/r3/`.

**Verdict: READY TO EXECUTE** (0 Blocking, 0 Important; 4 new Minor n1-n4, 5 carry-over Minor c1-c5).

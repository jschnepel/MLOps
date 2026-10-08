# First Slice D: Walking Skeleton (T08) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One run travels, over real HTTP with real Keycloak tokens, through five separately started processes — `api` → `worker` → `mcp-read` (one read tool) → fake draft → independent decision by a second persona → `mcp-write` → `incident-sim` → receipt → `action.confirmed` event — ending in `SUCCEEDED`, with every state change routed through the transition table in `core/`, the schema as Alembic revision 1, and every shortcut declared as debt before a line of service code is written (T08, R105).

**Architecture:** The five processes are host processes started by `scripts/skeleton.py` (uvicorn for `api`, `incident-sim` and the two MCP servers, a polling loop plus a health port for the worker) against the Plan B dev stack (PostgreSQL + Keycloak in Compose). `core/` gains three adapter modules every service shares: `settings.py` (environment plus secret files), `tokens.py` (one JWKS-backed verifier that checks `iss`, `aud`, `azp`, `exp` and the signature) and `persistence.py` (psycopg async: the single `transition()` that calls `require_transition` before the plain UPDATE, `append_event()` validated through `ops_core.outcomes.Event`, job insert/claim, invocation handles). `migrations/app` (database `ops`, schema `app`, owner role `ops`) and `migrations/incident` (database `incident`, role `incident`, schema `incident`) are Alembic revision 1 of each database. The worker's fake model is a deterministic `DraftGenerator` behind a one-route model router (`MODEL_MODE=fake`; anything else refuses to start). `mcp-read` serves `search_procedures` lexically from `data/handoff-fixtures/`; `mcp-write` performs grant → mark_sent → POST → record_outcome; `incident-sim` owns the `action_key` table with `INSERT … ON CONFLICT DO NOTHING`. The end-to-end proof is `tests/e2e/test_r105_walking_skeleton.py`, opt-in with `OPS_LIVE=1`, writing redacted evidence to `reports/skeleton/`.

**Tech Stack:** Python 3.13 (uv workspace), pydantic 2.13, psycopg 3 (async, `dict_row`), SQLAlchemy 2 + Alembic (migrations only), FastAPI + uvicorn (`api`, `incident-sim`), MCP Python SDK `mcp==2.3.0` over Streamable HTTP, protocol `2026-07-28` (`mcp-read`, `mcp-write`, the worker's client), PyJWT with `cryptography` (RS256 against Keycloak's JWKS), `httpx2` (the HTTP client the MCP SDK takes; used for every outbound HTTP call), pytest, ruff (120 cols), mypy strict. Exact pins are the ones the spike resolved (see "Resolved versions" below); never invent a version (AGENTS.md).

**Spec:** `SPEC_AMENDMENTS.md` (OPS-BUILD-1.3.6) over `BUILD_SPEC.md`. The fact sheet `docs/superpowers/research/2026-10-08-plan-d-inputs.md` cites every requirement this plan implements as `S1.n` (with `SA:`/`BS:` line numbers); the library behaviour this plan relies on was measured in `docs/superpowers/research/2026-10-08-plan-d-spike.md`. Both files are committed in Task 1 so executors can read them. Earlier plans' artefacts this plan builds on: `compose.yaml`, `deploy/dev/keycloak/realm-ops-dev.json`, `scripts/bootstrap_dev.py` (Plan B); `core/src/ops_core/*`, `schemas/`, `data/handoff-fixtures/meta.json` (Plan C).

## Global Constraints

- **Debt before code (SA:698, R6-B7).** The SESSION_STATE walking-skeleton debt list is amended and committed in Task 1 before any service code exists. Nothing not on the list may be shortcut; everything on the list names its owning task.
- **Not debt (SESSION_STATE "Not debt"):** real client-credentials tokens from the T05 realm; `iss`/`aud`/`azp`/`exp`/signature checks in `mcp-read`, `mcp-write` and `incident-sim` (and in `api`, ruling 3); `action_key` `INSERT … ON CONFLICT (action_id) DO NOTHING` at READ COMMITTED (SA:263); a decision by a second persona (`sam`, reviewer) who is not the requester and not in `authored_by` (BS:466, SA:539); every transition through `ops_core.states.require_transition` with the performer the spec names (SA:478-490).
- **Authority stays where the spec puts it.** The model (fake or not) holds no credential, calls no tool and sees no tool (SA:207, BS:157). The worker never contacts the destination; only `mcp-write` calls `incident-sim`; `mcp-read` holds no write-path function (SA:222-225). The grant commit precedes destination I/O (BS:472); `mark_sent` commits `SENT` before the POST (SA:229). A timeout after `SENT` is `OUTCOME_UNKNOWN`, never "no effect" (BS:30, BS:301).
- **Hashed bytes.** A proposal's stored, sent and decided-upon bytes are exactly `canonical_json(ProposalPayload.canonical_dict())`, its hash `canonical_sha256(...)`; nothing re-serialises them. The destination recomputes the hash over what it receives (SA:268).
- **Events** are validated by `ops_core.outcomes.Event` before insert; only `record_outcome` writes `source=destination`; `sequence` is per run, gap-free, assigned under the `runs` row lock in the same transaction (SA:303, the `next_event_seq` column itself is T14 debt).
- **Secrets** live only as files under `OPS_SECRETS_DIR`; services read them once at start; no secret in an environment variable, URL, log line, exception message, test assertion message or evidence file (BS:746, AGENTS.md). `tests/plan_b/test_evidence.py`'s rule (no token or secret value under `reports/`) is applied to `reports/skeleton/` too.
- **Loopback only.** Every listener binds `127.0.0.1` (SA:601): api 8000, worker health 8070, mcp-read 8081, mcp-write 8082, incident-sim 8090. The MCP resource URLs stay the audience identifiers from `.env` (`http://mcp-read:8081/mcp`, `http://mcp-write:8082/mcp`); the servers listen at `http://127.0.0.1:808x/mcp` (ruling 15).
- **Async only** on the event loop (SA:201): psycopg `AsyncConnection`, `httpx2.AsyncClient`, the async MCP client; JWKS is fetched asynchronously at startup, never inside a request on a sync client.
- **Libraries**: versions resolved by `uv lock` from PyPI at execution and recorded in the spike report; `mcp==2.3.0` exact (AM-30, SA:579); the rest `>=floor,<next-major`. `uv sync --locked --all-packages` after every `pyproject.toml` change; CI runs that command.
- **Layout (ADR-0001):** services contain wiring, transport and process lifecycle; shared adapters live in `core/`; no member imports another member (`tests/plan_a/test_layout.py`); cross-service tests in `tests/e2e/`; unit tests for this plan in `tests/plan_d/`; both added to `testpaths`.
- **Comments** per `docs/CODE_COMMENTS.md` (why, not what; every shortcut carries `TODO(T09)`-style ownership; no changelog comments). ≤120 columns, no `type: ignore`, ruff + mypy strict clean, UTF-8 without BOM, LF (hygiene test).
- **Gates:** `uv run ruff format <paths this task touched> && uv run ruff check --fix <same paths>` first (the plan's code blocks are hand-formatted; ruff's formatter is the authority; ruff 0.16's default rules include I, B, SIM, BLE and RUF, so a blind `except Exception` is refused unless it logs with `log.exception`), then `PYTHONUTF8=1 uv run python scripts/check.py` GREEN after every task. mypy's incremental cache can report a spurious `Module "ops_core" has no attribute …` after many edits (seen in the dry run); rerun, or `uv run mypy --no-incremental <paths>`, before treating it as real (unit tests, CI-safe; live tests skipped without `OPS_LIVE=1`); `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts` exit 0; the live suite `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e tests/plan_b/live -q` against the running stack. No test is marked xfail or skipped for a reason other than the live gate (BS:597).
- **Commits:** one logical group per step; messages free of any attribution trailer; never push.
- **Bash tool (Git Bash)**; never PowerShell redirection; tests via `python -m pytest` from the repo root; never `docker compose down -v`; never change system settings.

## Review Focus

1. **A second `create_incident` for the same proposal must not create a second incident or a second grant.** `execution_grant` is `UNIQUE (run_id)`; a repeat call with a grant already recorded resends the same `action_id` and hash (idempotent at the destination) or returns the recorded outcome. Pinned in Task 6's unit test and the e2e test's replay step.
2. **A reviewer who is the requester, or not a member of the tenant, must be refused (403) and the run must stay `AWAITING_APPROVAL`.** Pinned in Task 7 (`alex` approving their own proposal → 403 FORBIDDEN; `jordan` (beta reviewer) → 404 on an alpha proposal).
3. **A token with the wrong audience must be refused by every resource server** — the worker's token at `incident-sim`, `mcp-write`'s token at `mcp-read`, a persona token at either MCP server — and the refusal must never carry an `action_id` (SA:357). Pinned in Task 3's unit tests (synthetic JWKS) and the e2e test's negative calls.
4. **A tool argument that supplies a role, tenant, actor, approval or destination must be rejected** (SA:350) even by the skeleton's single tool: `search_procedures(tenant_id=…)` fails input validation. Pinned in Task 5.
5. **`POST /internal/incidents` with the same `action_id` and a different hash must return the existing key as `CONFLICT`, never a second incident** (SA:268, BS:407). Pinned in Task 4's unit and live tests and in Task 6's `classify` tests; the e2e test exercises the replay with the same hash only.

## Rulings (decisions the spec leaves to this plan)

Each is recorded here, mirrored in the debt list where it is a shortcut, and proposed to the owner in Task 9 where it reads the spec in one of two possible ways. Executors do not re-litigate them.

1. **Processes run on the host, not in Compose** (fact sheet Q7). Containers, Dockerfiles and the demo profile are T30's ("Multi-stage non-root images from uv.lock; Compose test/demo profiles"). `scripts/skeleton.py up` starts the five processes with `subprocess.Popen` (`uv run python -m <package>`), waits on each `/health/ready`, and `down` terminates them; the e2e fixture calls the same functions. Debt line added. Cost if wrong: T30 wraps the same entrypoints in images; nothing here is throwaway because every process already reads its configuration from the environment and secret files the way a container would.
2. **The one read tool is `search_procedures`, served from `data/handoff-fixtures/` inside `mcp-read`** (Q1, Q2). It is the only read tool whose results are evidence the proposal can cite (`evidence_id = <DOCUMENT_ID>:v<version>:<section>`, `content_sha256` = the per-section hash from `meta.json`, `version` = the document version). `get_asset_status`/`get_recent_alerts` need asset-sim (T16) and are not registered. Lexical mode only; `vector_exact` is refused with a tool error until T17 (the governed store). Debt lines added (T16, T17).
3. **The API authenticates personas with bearer tokens from the dev-only direct grant, verified like every other token** (Q4). The realm's `ops-dev-direct` client gains a hardcoded-audience mapper `ops-api`; the API's verifier requires `aud ∋ "ops-api"`, `azp == "ops-dev-direct"`, `iss`, `exp` and the signature, then resolves the tenant and roles from seeded `app.memberships` by `sub` (BS:224). This is not throwaway: T11 adds the browser flow and sessions and widens `azp` to `ops-web`; the verifier and the membership lookup stay. Browser sessions, CSRF and `Idempotency-Key` are debt (T11/T12).
4. **Wall clock** (Q3): the API resolves `hours` once at admission into `[end_at - hours, end_at)` with `end_at = now(UTC)` truncated to seconds, stores both on `runs`, and the worker and proposal reuse the stored interval. The 15-minute expiry is written (`expires_at = frozen_at + 15 min`) but not enforced (T21). Debt line added (T09 injected clock).
5. **Owner role and databases** (Q5): the app schema is created and used by the Compose superuser `ops` (the "single owner DB role" the debt list already allows; T09 creates the per-service roles). The destination gets its own role now: `migrations/incident` revision 1, run as `ops` against database `incident`, creates role `incident` (LOGIN, password from the new secret file `postgres_incident_password`), schema `incident` owned by it, and grants nothing to anyone else; `incident-sim` connects as `incident` and can see no application table.
6. **Alembic trees live in top-level `migrations/app/` and `migrations/incident/`** (BUILD_SPEC §5 `migrations/`, "application/destination/identity schema evolution"); each has its own `alembic.ini`-free programmatic config in `scripts/skeleton.py migrate`, which runs both to `head`. Revision IDs are fixed strings (`0001_walking_skeleton`), so T09's revision 2 chains on a known parent.
7. **Revision 1 tables** (Q6) are the skeleton path's tables with the AM-20.2 names and columns the path needs — `app.tenants`, `app.memberships`, `app.conversations`, `app.messages`, `app.runs`, `app.run_state_history`, `app.jobs`, `app.invocation_context`, `app.drafts`, `app.proposals`, `app.decisions`, `app.execution_grant`, `app.action_attempt`, `app.action_attempt_state`, `app.events` — plus the seed rows for the two tenants and five persona memberships from `data/seed-ids.json`. No `run_directory`, `run_lease`, `sessions`, `outbox`, `feedback`, `idempotency_request`, corpus tables or `model_permit` (their owners add them). Columns T09 will re-own keep the spec's names so the later revision alters rather than renames; the one deliberate exception is `invocation_context.handle` (raw, ruling 19), which T09/T15 replaces by `handle_sha256`.
8. **Events** (Q11): the happy path writes, in order, `run.accepted` (api), `tool.started` and `tool.completed` (worker, payload `{"message": "search_procedures"}`), `explanation.ready` (worker, `source=model_summary`, payload `{"message": "Drafted by model route fake (prompt incident-draft-v1).", "evidence_refs": [...]}`), `proposal.ready` (worker, `{"proposal_id": ...}`), `approval.recorded` (api, `{"proposal_id": ...}`), `action.granted` (mcp-write, `{"action_id": ..., "proposal_id": ...}`), `action.dispatched` (mcp-write, `{"action_id": ...}`), `action.confirmed` (mcp-write, `source=destination`, `{"status": "SUCCEEDED", "action_id": ..., "receipt": {...}}`). RETRIEVING and DRAFTING have no event type (none exists in AM-14); they are recorded in `run_state_history`. The failure path after `SENT` writes `action.uncertain` (`{"action_id": ...}`) with the `mark_unknown` transition. Every event is constructed as `ops_core.outcomes.Event` before insert.
9. **incident-sim contract** (Q12), the base T10 extends: `POST /internal/incidents` with body `{"action_id": <uuid>, "payload_sha256": <hex>, "payload_canonical": <the proposal's canonical JSON, as one string>}`; the service hashes the UTF-8 bytes of `payload_canonical` exactly as received (SA:268: "recomputes sha256 over the received bytes"), parses them with `parse_json_strict` for storage, and refuses a mismatch with 422 before touching the key table; then `INSERT INTO incident.action_key … ON CONFLICT (action_id) DO NOTHING` and `SELECT` the row: COMMITTED with the same hash → 200 `{"state": "COMMITTED", "action_id", "payload_sha256", "receipt": {"receipt_id", "incident_id", "committed_at"}}`; existing key with a different hash → 409 `{"state": "CONFLICT", "action_id", "payload_sha256": <stored>}`; ABORTED/REJECTED → 200 with `"tombstone"` (T10 creates those states; the shape is defined now). `GET /internal/actions/{action_id}` returns the same document or 404 `NOT_FOUND`. Incident IDs are `INC-%06d` from a sequence; `receipt_id` is a UUIDv4 stored on the key row so the receipt is stable across replays.
10. **Proposal storage** (Q13): `app.proposals(payload_canonical BYTEA, payload JSONB, payload_sha256 TEXT, …)`; the decision compares `expected_payload_sha256` and `expected_revision` with the stored row and returns 409 `VERSION_CONFLICT` on mismatch. The three open items from Plan C (null/whitespace, timestamp spelling) are decided for the API boundary thus: request bodies are parsed with `ops_core.contracts.load()` (explicit `null` for an optional field is accepted, as the models already do; whitespace-only strings are rejected); timestamps the API emits are `…Z` with seconds and no fractional part.
11. **Reviewer independence and membership are enforced now** (Q14): `record_decision` in the API requires an active `memberships` row with role `reviewer` in the run's tenant for the token's `sub`, and `sub ∉ proposals.authored_by`; otherwise 403 `FORBIDDEN`. A proposal in another tenant is 404 `NOT_FOUND`. Only the first decision is accepted (409 `VERSION_CONFLICT` afterwards).
12. **Job claiming** (Q15): `UPDATE app.jobs SET claimed_by, claimed_at, attempts = attempts + 1 WHERE id = (SELECT id FROM app.jobs WHERE done_at IS NULL AND claimed_at IS NULL AND available_at <= now() ORDER BY available_at, id FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *`; the worker polls every 0.5 s; `done_at` is set when the handler returns. The `execute` job is inserted by the decision path with `dedup_key(JobType.EXECUTE, proposal_id=…)`. No lease/fence/heartbeat (T13 debt); a job that raises is left claimed and logged (T13 reclaims).
13. **`require_transition` is called in one place**, `ops_core.persistence.transition()`, which every service uses for every state change; it locks the `runs` row, checks `expected_version`, calls `require_transition(src, dst, performer, reason)`, updates `runs.state/state_version/reason`, inserts `run_state_history` and returns the new version (Q16). T09 replaces its body with a call to the SQL `transition_run`/definer functions without changing callers.
14. **Fake model** (Q17): `ops_worker.drafting` defines `DraftGenerator` (a `Protocol` with `async def generate(request: DraftRequest, evidence: list[EvidenceItem]) -> ModelDraft`), `FakeDraftGenerator` (deterministic from the request and evidence; `kind="proposal"`, cites the first evidence item, one limitation naming the fake route) and `make_generator(mode: str)` that returns the fake for `"fake"` and raises `ModelRouteError` for anything else (R130: no silent fallback); `MODEL_MODE` has no default — an unset variable is a refusal to start, not a quiet `fake`. `prompt_version = "incident-draft-v1"`, `workflow_version = "investigation-v1"`, `corpus_version` = the catalog's `fixture_version` (`handoff-1`, what mcp-read reports), `retrieval_mode = "lexical"`; a `RunManifest` is built and validated (not stored; T19 stores it).
15. **MCP specifics** (Q18): servers use `MCPServer(..., auth=AuthSettings(issuer_url=AnyHttpUrl(<issuer>), resource_server_url=AnyHttpUrl(<resource URL>), validate_token_resource=False), token_verifier=<ops_core.tokens-backed verifier>)` (pydantic's `AnyHttpUrl`; mypy strict rejects a bare `str`), Streamable HTTP, `stateless_http=True`, `json_response=True`, mounted beside `/health/live` and `/health/ready`; the worker's client uses `streamable_http_client(url, http_client=httpx2.AsyncClient(headers=...))` and `mode="2026-07-28"`. The exact constructor and function signatures are the ones the spike measured (copied verbatim in Tasks 5, 6 and 8). The servers' derived input schemas are checked against `schemas/tools/<tool>.input.schema.json` for required keys, property names and enums (not byte equality).
16. **The e2e test** lives at `tests/e2e/test_r105_walking_skeleton.py` (ADR-0001), gated by `OPS_LIVE=1` like Plan B's live tests, and writes `reports/skeleton/r105-walking-skeleton.txt` (run id, state sequence, event types, incident id, timestamps; no tokens). `handoff/acceptance-matrix.json` R105 becomes `RECORDED_LOCALLY` / `IMPLEMENTED_LOCALLY_VERIFIED` with that path (Q19).
17. **Dependencies** (Q20): `core` gains psycopg, SQLAlchemy, Alembic, PyJWT, httpx2 (the shared adapters); `api` and `incident-sim` gain FastAPI and uvicorn; `worker`, `mcp-read` and `mcp-write` gain `mcp==2.3.0` and uvicorn. SQLAlchemy is used only by Alembic (the runtime uses psycopg directly, so there is one transaction owner, BS:70). Exact pins: Task 1.
18. **Health** (Q21): every process serves `GET /health/live` (200 `{"status": "live"}`) and `GET /health/ready` (200 `{"status": "ready"}` after a `SELECT 1` on its database and, for the MCP servers, a loaded JWKS; otherwise 503). The `test_clock` assertion is T09's.
19. **Invocation handles** (Q10): the worker mints a 256-bit `secrets.token_urlsafe(32)` handle per job, inserts `app.invocation_context(handle, run_id, job_id, server, azp='ops-worker', expires_at=now+60s)` and sends it as `X-Ops-Invocation`; each MCP server resolves the handle by equality (raw, T09/T15 hash it), checks `expires_at`, `revoked_at IS NULL`, the token's `azp == row.azp`, the job's type → server binding (`investigate` → read, `execute` → write; a read handle at `mcp-write` is refused and vice versa, R131 in miniature) and the tool against `JOB_RULES[job_type].allowed_tools`. The handle is never logged.
20. **Error mapping** subset (BS:301): 401 `UNAUTHENTICATED`, 403 `FORBIDDEN`, 404 `NOT_FOUND`, 409 `VERSION_CONFLICT` / `GRANT_EXISTS` / `SLOT_OCCUPIED`, 422 `INVALID_INPUT`, 503 `UNAVAILABLE`; bodies are `ops_core.contracts.SafeError`; a FastAPI `RequestValidationError` becomes 422 `INVALID_INPUT` with a generic message (no field echo of authority fields).
21. **Failure after SENT** (Q12): if the POST to `incident-sim` raises or returns anything but the two defined documents, `mcp-write` records `OUTCOME_UNKNOWN` (`mark_unknown`, event `action.uncertain`) and returns the envelope `status="outcome"`, `data.status="UNKNOWN"`; reconciliation is T22. A `409 CONFLICT` from the destination is recorded as `ESCALATED` with reason `conflict` (`record_outcome`, event `action.conflict`) and returned as `data.status="CONFLICT"`.
22. **`GET /api/v1/proposals/{id}`** is not in BUILD_SPEC's endpoint table; the reviewer needs the frozen document (revision, hash, payload, authors) to decide on exact content, so the skeleton serves it read-only to members of the proposal's tenant. T21 formalises it (or folds it into the run snapshot).
23. **Event loops.** On Windows `uvicorn.run` chooses the Proactor loop (measured by the round-1 static critic, contradicting the spike's note, which is corrected), and psycopg async refuses it. Every process therefore serves uvicorn programmatically — `uvicorn.Server(uvicorn.Config(app, ...)).serve()` under `asyncio.run(..., loop_factory=asyncio.SelectorEventLoop)` on win32, plain `asyncio.run` elsewhere — through one `serve_app(app, port)` helper per service entrypoint (six lines, duplicated: `core/` does not depend on uvicorn).
24. **Connections.** Each process holds one psycopg connection in **autocommit** mode, wrapped in `ops_core.persistence.Session`: `async with session.unit() as conn:` takes a process-wide `asyncio.Lock` and opens an explicit transaction, so a unit of work is a real BEGIN/COMMIT (never a savepoint inside a transaction a bare SELECT left open — the static critic measured that failure mode), and two concurrent requests never interleave on one connection. Reads outside a unit run as autocommit statements. Pools arrive with T13.
25. **A wrong-audience token is 401 everywhere in T08** (the verifier rejects it before any identity exists); T10's 403 for "authenticated but not this audience" is its own refinement.
26. **Unit tests live in `tests/plan_d/`**, this repository's convention since Plan A (`tests/plan_<letter>/` per plan, listed in `testpaths`), not in per-service `tests/` directories (SA:70): those arrive with T30, when each service's image must carry its own tests. Cross-service live tests are in `tests/e2e/` (ADR-0001).
27. **Live-test clean-up deletes test-created rows from append-only audit tables** (`run_state_history`, `events`, `action_attempt_state`) as the owner role, because the skeleton has one role and the dev database is shared. T09's grants will forbid that; the live tests then move to a per-session schema or a database reset, which is T09's concern. The purge helpers say so in their docstring.

## Debt-list additions (committed in Task 1, before coding)

Appended under "Allowed shortcuts in T08, each with its owning task:" in `SESSION_STATE.md`, verbatim:

```markdown
- the five application processes run on the host, started by `scripts/skeleton.py`; no Dockerfiles, images or Compose services for them → T30;
- `search_procedures` is served lexically from `data/handoff-fixtures/` inside mcp-read (no governed store, no `asset_scope`) → T17; `get_asset_status` / `get_recent_alerts` and asset-sim are absent → T16;
- the API accepts bearer persona tokens from the dev-only direct grant (audience `ops-api`) instead of browser sessions, CSRF and `Idempotency-Key` → T11/T12;
- wall clock instead of an injected clock; the interval is resolved once at admission and stored; expiry and asset freshness are written but not enforced → T09/T21;
- incident-sim implements `POST /internal/incidents` and `GET /internal/actions/{id}` only; abort, the fault factory and the detective check → T10;
- the worker claims jobs with `FOR UPDATE SKIP LOCKED` and polls; no wake-ups, no outbox, no reclaim of a job whose handler crashed (its run and conversation slot stay held) → T13/T14;
- tenant scoping is a `WHERE tenant_id = …` in each query; no RLS, no `run_directory` → T09;
- handles are not revoked at job end and resolution ignores run and attempt state → T15 (the raw, unhashed handle is already on the list above);
- the runtime connects as the Compose superuser `ops` (the single owner role); `incident` can CONNECT to `ops`; no CONNECT revocation → T09;
- the grant re-reads no current membership, and neither grant nor mark_sent re-checks cancellation or the dispatch deadline → T09/T21/T22; request bodies are not size-bounded → T12.
```

## Process map

| Process | Package / entrypoint | Listens (127.0.0.1) | Talks to | Token it presents | Token it verifies |
|---|---|---|---|---|---|
| api | `ops_api` (`python -m ops_api`) | 8000 | Postgres `ops` | — | persona: `aud ∋ ops-api`, `azp == ops-dev-direct` |
| worker | `ops_worker` | 8070 (health only) | Postgres `ops`; mcp-read; mcp-write | `ops-worker` client credentials (one token, both MCP audiences) | — |
| mcp-read | `ops_mcp_read` | 8081 `/mcp` | Postgres `ops` (handles only); fixtures on disk | — | `aud ∋ MCP_READ_RESOURCE_URL`, `azp == ops-worker` |
| mcp-write | `ops_mcp_write` | 8082 `/mcp` | Postgres `ops`; incident-sim | `ops-mcp-write` client credentials (`aud incident-sim`) | `aud ∋ MCP_WRITE_RESOURCE_URL`, `azp == ops-worker` |
| incident-sim | `ops_incident_sim` | 8090 | Postgres `incident` (role `incident`) | — | `aud ∋ incident-sim`, `azp == ops-mcp-write` |

Environment every process reads (set by `scripts/skeleton.py` from `.env`; defaults in `ops_core.settings`): `OPS_SECRETS_DIR`; `OPS_PG_HOST=127.0.0.1`, `OPS_PG_PORT=<PG_PORT>`, `OPS_PG_USER=ops`, `OPS_PG_DB=ops` (password file `postgres_password`); `OPS_INCIDENT_PG_DB=incident`, `OPS_INCIDENT_PG_USER=incident` (password file `postgres_incident_password`); `OPS_KC_BASE_URL=http://localhost:<KC_HTTP_PORT>`, `OPS_KC_ISSUER=<base>/realms/ops-dev`; `MCP_READ_RESOURCE_URL`, `MCP_WRITE_RESOURCE_URL` (audience identifiers); `OPS_MCP_READ_URL=http://127.0.0.1:8081/mcp`, `OPS_MCP_WRITE_URL=http://127.0.0.1:8082/mcp` (listen URLs); `OPS_INCIDENT_SIM_URL=http://127.0.0.1:8090`; `OPS_API_PORT`, `OPS_WORKER_HEALTH_PORT`, `OPS_MCP_READ_PORT`, `OPS_MCP_WRITE_PORT`, `OPS_INCIDENT_SIM_PORT`; `OPS_API_AUDIENCE=ops-api`; `MODEL_MODE=fake`; `OPS_FIXTURES_DIR=data/handoff-fixtures`. `.env` itself is unchanged (Plan B's test pins its key set).

## Task overview

| Task | Delivers | Tests |
|---|---|---|
| 1 | Debt list amended; research files committed; realm mapper `ops-api`; secret `postgres_incident_password`; dependencies locked; `ops_core.settings`; `tests/plan_d` and `tests/e2e` packages | `tests/plan_d/test_settings.py`; updated Plan B static tests |
| 2 | `migrations/app` and `migrations/incident` revision 1; `ops_core.persistence` (connect, transition, events, jobs, handles); `scripts/skeleton.py migrate` | `tests/plan_d/test_persistence_pure.py` (SQL-free logic); `tests/e2e/test_migrations_and_persistence.py` (live) |
| 3 | `ops_core.tokens`: JWKS verifier and `Principal` | `tests/plan_d/test_tokens.py` (local RSA key, synthetic JWKS; every refusal) |
| 4 | `incident-sim` service | `tests/plan_d/test_incident_sim.py` (app with a stub verifier, hash recompute, document shapes); `tests/e2e/test_incident_sim_live.py` |
| 5 | `mcp-read` service (`search_procedures` from fixtures, handles, verifier) | `tests/plan_d/test_mcp_read.py` (lexical search, schema conformance to `schemas/tools/`, argument rejection) |
| 6 | `mcp-write` service (grant, mark_sent, destination call, record_outcome, envelopes) | `tests/plan_d/test_mcp_write.py` (envelope and outcome mapping, replay rule) |
| 7 | `api` service (conversations, messages → run + job, run snapshot, proposal, decisions, events) | `tests/plan_d/test_api.py` (auth dependency, admission validation, interval, error mapping, independence rule on a stub store) |
| 8 | `worker` (poll loop, investigate and execute handlers, fake model, MCP client) | `tests/plan_d/test_worker.py` (fake generator, proposal assembly and hash, handle minting, router refusal) |
| 9 | `scripts/skeleton.py up/down/status`; `tests/e2e/conftest.py`; the R105 e2e test; evidence; handoff docs | `tests/e2e/test_r105_walking_skeleton.py` (live); docs |

---
### Task 1: Debt before code — shortcuts declared, realm audience, incident secret, dependencies, settings

**Files:**
- Modify: `SESSION_STATE.md` (debt list), `deploy/dev/keycloak/realm-ops-dev.json` (`ops-dev-direct` gains one audience mapper), `tests/plan_b/test_realm_template.py`, `tests/plan_b/live/test_keycloak_tokens.py`, `scripts/bootstrap_dev.py` (`SECRET_NAMES`), `compose.yaml` (top-level `secrets:`), `core/pyproject.toml`, `api/pyproject.toml`, `incident-sim/pyproject.toml`, `worker/pyproject.toml`, `mcp-read/pyproject.toml`, `mcp-write/pyproject.toml`, `pyproject.toml` (`testpaths`), `uv.lock`
- Create: `core/src/ops_core/settings.py`, `tests/plan_d/__init__.py`, `tests/plan_d/test_settings.py`, `tests/e2e/__init__.py` (the two research files under `docs/superpowers/research/` were committed with this plan)

**Interfaces:**
- Produces: `ops_core.settings` — `REALM = "ops-dev"`; `class SettingsError(ValueError)`; `env(name, default=None) -> str`; `env_int(name, default) -> int`; `secrets_dir() -> Path`; `read_secret(name, directory=None) -> str`; `@dataclass(frozen=True) class Postgres(host, port, user, dbname, password)` with `conninfo() -> str` (password excluded from `repr`); `app_postgres() -> Postgres`; `incident_postgres() -> Postgres`; `@dataclass(frozen=True) class Keycloak(base_url, issuer)` with `jwks_url` and `token_url` properties; `keycloak() -> Keycloak`; `@dataclass(frozen=True) class Urls(mcp_read_resource, mcp_write_resource, mcp_read, mcp_write, incident_sim)`; `urls() -> Urls`; `fixtures_dir() -> Path`. Secret file names used by later tasks: `postgres_password`, `postgres_incident_password`, `kc_client_secret_ops_worker`, `kc_client_secret_ops_mcp_write`, `kc_persona_alex_password`, `kc_persona_sam_password`.
- Produces: the audience `ops-api` on persona tokens; the secret file `postgres_incident_password`; the dependency set every later task imports from (runtime: psycopg, SQLAlchemy, Alembic, PyJWT, httpx2, FastAPI, uvicorn, `mcp==2.3.0`; dev: pytest-asyncio). The spike measured that FastAPI's `TestClient` runs on httpx2, so plain `httpx` is not added.

- [ ] **Step 1: Amend the debt list and commit it (before any code)**

In `SESSION_STATE.md`, under `## Walking-skeleton debt list (T08; committed before coding) [R6-B7]`, after the line `- fake model → T19; no LangGraph or durability → T20.` append the ten lines from this plan's "Debt-list additions" section verbatim. Leave the "Not debt" paragraph unchanged. Then:

```bash
git add SESSION_STATE.md
git commit -m "docs: declare the walking skeleton's shortcuts before coding (T08 debt list)"
```

- [ ] **Step 2: Write the failing settings tests**

Create `tests/plan_d/__init__.py` and `tests/e2e/__init__.py` (both empty). Create `tests/plan_d/test_settings.py`:

```python
"""Process configuration (BUILD_SPEC §22, Plan B's no-secret-in-environment rule): secrets come from files, never from
the environment, and never leak into a repr, a message or a URL.

Catches: a secret read with its trailing newline (every token exchange would then fail with a wrong-password error that
looks like a Keycloak outage), an empty or missing secret file silently becoming an empty password, a settings error
message that echoes a value, and a default URL drifting away from scripts/bootstrap_dev.py's .env.
"""

from pathlib import Path

import pytest
from ops_core import settings


@pytest.fixture
def secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "secrets"
    directory.mkdir()
    (directory / "postgres_password").write_text("pg-secret-value\n", encoding="utf-8")
    (directory / "postgres_incident_password").write_text("incident-secret-value", encoding="utf-8")
    (directory / "empty_secret").write_text("\n", encoding="utf-8")
    monkeypatch.setenv("OPS_SECRETS_DIR", str(directory))
    for name in ("OPS_PG_HOST", "OPS_PG_PORT", "OPS_PG_USER", "OPS_PG_DB", "OPS_KC_BASE_URL", "OPS_KC_ISSUER"):
        monkeypatch.delenv(name, raising=False)
    return directory


def test_read_secret_strips_the_trailing_newline(secrets: Path):
    assert settings.read_secret("postgres_password") == "pg-secret-value"
    assert settings.read_secret("postgres_incident_password") == "incident-secret-value"


def test_missing_or_empty_secret_is_an_error_that_names_the_file_only(secrets: Path):
    with pytest.raises(settings.SettingsError) as missing:
        settings.read_secret("kc_client_secret_ops_worker")
    assert "kc_client_secret_ops_worker" in str(missing.value) and str(secrets) not in str(missing.value)
    with pytest.raises(settings.SettingsError):
        settings.read_secret("empty_secret")


def test_missing_variable_names_the_variable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OPS_SECRETS_DIR", raising=False)
    with pytest.raises(settings.SettingsError, match="OPS_SECRETS_DIR"):
        settings.secrets_dir()
    monkeypatch.setenv("OPS_PG_PORT", "not-a-port")
    with pytest.raises(settings.SettingsError, match="OPS_PG_PORT"):
        settings.env_int("OPS_PG_PORT", 15432)


def test_postgres_settings_build_a_conninfo_and_hide_the_password(secrets: Path):
    pg = settings.app_postgres()
    assert (pg.host, pg.port, pg.user, pg.dbname) == ("127.0.0.1", 15432, "ops", "ops")
    assert "password=pg-secret-value" in pg.conninfo() and "dbname=ops" in pg.conninfo()
    assert "pg-secret-value" not in repr(pg) and "pg-secret-value" not in str(pg)
    incident = settings.incident_postgres()
    assert (incident.user, incident.dbname) == ("incident", "incident")
    assert "password=incident-secret-value" in incident.conninfo()


def test_keycloak_and_service_urls_default_to_the_dev_stack(secrets: Path, monkeypatch: pytest.MonkeyPatch):
    kc = settings.keycloak()
    assert kc.issuer == "http://localhost:18080/realms/ops-dev"
    assert kc.jwks_url == "http://localhost:18080/realms/ops-dev/protocol/openid-connect/certs"
    assert kc.token_url == "http://localhost:18080/realms/ops-dev/protocol/openid-connect/token"
    monkeypatch.setenv("OPS_KC_BASE_URL", "http://localhost:28080/")
    assert settings.keycloak().issuer == "http://localhost:28080/realms/ops-dev"  # trailing slash tolerated
    for name in ("MCP_READ_RESOURCE_URL", "MCP_WRITE_RESOURCE_URL", "OPS_MCP_READ_URL", "OPS_MCP_WRITE_URL"):
        monkeypatch.delenv(name, raising=False)
    u = settings.urls()
    # The resource URLs are audience identifiers (what the realm puts in `aud`); the listen URLs are where the
    # host processes actually answer. They differ on purpose until T30 containerises the servers.
    assert u.mcp_read_resource == "http://mcp-read:8081/mcp" and u.mcp_read == "http://127.0.0.1:8081/mcp"
    assert u.mcp_write_resource == "http://mcp-write:8082/mcp" and u.mcp_write == "http://127.0.0.1:8082/mcp"
    assert u.incident_sim == "http://127.0.0.1:8090"
    assert settings.fixtures_dir() == Path("data/handoff-fixtures")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `PYTHONUTF8=1 uv run python -m pytest tests/plan_d/test_settings.py -q`
Expected: collection error, an `ImportError` for `ops_core.settings` (the module does not exist yet) (the directory is not in `testpaths` yet, so pass the path explicitly as above).

- [ ] **Step 4: Dependencies and test paths**

Edit the member files so their `dependencies` read exactly:

- `core/pyproject.toml`: `dependencies = ["pydantic>=2.13,<3", "psycopg[binary]>=3.3,<4", "sqlalchemy>=2.1,<3", "alembic>=1.20,<2", "pyjwt[crypto]>=2.10,<3", "httpx2>=2.13,<3"]`
- `api/pyproject.toml` and `incident-sim/pyproject.toml`: `dependencies = ["ops-core", "fastapi>=0.142,<1", "uvicorn>=0.54,<1"]`
- `worker/pyproject.toml`, `mcp-read/pyproject.toml`, `mcp-write/pyproject.toml`: `dependencies = ["ops-core", "mcp==2.3.0", "uvicorn>=0.54,<1"]`

(`mcp==2.3.0` is the AM-30 pin, SA:579. If a floor above does not resolve, lower it to the version the spike report's "Resolved versions" section measured — never raise it past PyPI's latest and never invent one.)

In the root `pyproject.toml` set `testpaths = ["tests/plan_a", "tests/plan_b", "tests/plan_c", "tests/plan_d", "tests/e2e"]` and add `asyncio_default_fixture_loop_scope = "function"` under `[tool.pytest.ini_options]` (pytest-asyncio 1.4 warns without it). Add the async test plugin to the dev group with `uv add --dev "pytest-asyncio>=1.4,<2"` (the dry run resolved 1.4.0; record the version — the plan's async tests use `@pytest.mark.asyncio` and `@pytest_asyncio.fixture`, strict mode).

Run: `uv lock && uv sync --locked --all-packages`
Expected: both succeed; `git diff --stat uv.lock` is mostly additions (the new packages and their dependencies) plus a few rewritten `requires-dist` lines and a resolution marker. Record the resolved versions of `mcp`, `fastapi`, `starlette`, `uvicorn`, `psycopg`, `sqlalchemy`, `alembic`, `pyjwt`, `httpx2` in your report (`uv pip list` or `grep -A1 'name = "<pkg>"' uv.lock`).

- [ ] **Step 5: The settings module**

Create `core/src/ops_core/settings.py`:

```python
"""Process configuration shared by every skeleton service: plain environment variables plus secret files.

Secrets never travel in environment variables (BUILD_SPEC §22; Plan B's compose test refuses a PASSWORD or SECRET key
that is not a `_FILE` path), so a service reads each secret once from `OPS_SECRETS_DIR/<name>` at start and keeps it in
memory. Everything else — hosts, ports, URLs, the model mode — is an `OPS_*` variable with a dev default that matches
the `.env` written by scripts/bootstrap_dev.py, so a process started by hand against the dev stack needs only
`OPS_SECRETS_DIR`. The MCP resource URLs are audience identifiers (what the realm's mappers put in `aud`), distinct
from the loopback listen URLs the host processes answer on; T30 makes them coincide when the servers are containerised.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from psycopg.conninfo import make_conninfo

REALM = "ops-dev"


class SettingsError(ValueError):
    """A required variable or secret file is missing or malformed. Messages name the variable or file, never a value."""


def env(name: str, default: str | None = None) -> str:
    """Return a non-empty environment variable, or the default; an empty string counts as unset."""
    value = os.environ.get(name) or default
    if not value:
        raise SettingsError(f"{name} is not set")
    return value


def env_int(name: str, default: int) -> int:
    """Return an integer environment variable or the default."""
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise SettingsError(f"{name} must be an integer") from exc


def secrets_dir() -> Path:
    return Path(env("OPS_SECRETS_DIR"))


def read_secret(name: str, directory: Path | None = None) -> str:
    """Read one secret file; the trailing newline an editor may add is not part of the secret."""
    path = (directory or secrets_dir()) / name
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        # The path is left out of the message on purpose: messages reach logs and HTTP bodies.
        raise SettingsError(f"secret file {name} is missing or unreadable") from exc
    if not value:
        raise SettingsError(f"secret file {name} is empty")
    return value


@dataclass(frozen=True)
class Postgres:
    host: str
    port: int
    user: str
    dbname: str
    password: str = field(repr=False)  # dataclasses would otherwise print it in every traceback

    def conninfo(self) -> str:
        # The session time zone is pinned so timestamptz values round-trip as UTC whatever the server's default.
        return make_conninfo(
            host=self.host, port=self.port, user=self.user, dbname=self.dbname, password=self.password,
            options="-c timezone=UTC",
        )


def _pg_host_port() -> tuple[str, int]:
    return env("OPS_PG_HOST", "127.0.0.1"), env_int("OPS_PG_PORT", 15432)


def app_postgres() -> Postgres:
    """The application database, as the single owner role the skeleton is allowed (debt → T09)."""
    host, port = _pg_host_port()
    return Postgres(host, port, env("OPS_PG_USER", "ops"), env("OPS_PG_DB", "ops"), read_secret("postgres_password"))


def incident_postgres() -> Postgres:
    """The destination's own database and role (BUILD_SPEC §14: separate credentials)."""
    host, port = _pg_host_port()
    return Postgres(
        host,
        port,
        env("OPS_INCIDENT_PG_USER", "incident"),
        env("OPS_INCIDENT_PG_DB", "incident"),
        read_secret("postgres_incident_password"),
    )


@dataclass(frozen=True)
class Keycloak:
    base_url: str
    issuer: str

    @property
    def jwks_url(self) -> str:
        return f"{self.base_url}/realms/{REALM}/protocol/openid-connect/certs"

    @property
    def token_url(self) -> str:
        return f"{self.base_url}/realms/{REALM}/protocol/openid-connect/token"


def keycloak() -> Keycloak:
    """Base URL for the host (`KC_HOSTNAME` makes `iss` the same for containers, SA:556)."""
    base = env("OPS_KC_BASE_URL", "http://localhost:18080").rstrip("/")
    return Keycloak(base_url=base, issuer=env("OPS_KC_ISSUER", f"{base}/realms/{REALM}"))


@dataclass(frozen=True)
class Urls:
    mcp_read_resource: str
    mcp_write_resource: str
    mcp_read: str
    mcp_write: str
    incident_sim: str


def urls() -> Urls:
    return Urls(
        mcp_read_resource=env("MCP_READ_RESOURCE_URL", "http://mcp-read:8081/mcp"),
        mcp_write_resource=env("MCP_WRITE_RESOURCE_URL", "http://mcp-write:8082/mcp"),
        mcp_read=env("OPS_MCP_READ_URL", "http://127.0.0.1:8081/mcp"),
        mcp_write=env("OPS_MCP_WRITE_URL", "http://127.0.0.1:8082/mcp"),
        incident_sim=env("OPS_INCIDENT_SIM_URL", "http://127.0.0.1:8090"),
    )


def fixtures_dir() -> Path:
    return Path(env("OPS_FIXTURES_DIR", "data/handoff-fixtures"))
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `PYTHONUTF8=1 uv run python -m pytest tests/plan_d/test_settings.py -q`
Expected: `5 passed`.

- [ ] **Step 7: The `ops-api` audience on persona tokens**

In `deploy/dev/keycloak/realm-ops-dev.json`, give the `ops-dev-direct` client a `protocolMappers` array with exactly one mapper, shaped like the existing `aud incident-sim` mapper on `ops-mcp-write`:

```json
"protocolMappers": [
  {
    "name": "aud ops-api",
    "protocol": "openid-connect",
    "protocolMapper": "oidc-audience-mapper",
    "consentRequired": false,
    "config": {
      "included.custom.audience": "ops-api",
      "access.token.claim": "true",
      "id.token.claim": "false",
      "introspection.token.claim": "true"
    }
  }
]
```

Keep the file's two-space indentation and key order (insert after `"serviceAccountsEnabled": false`). In `tests/plan_b/test_realm_template.py::test_direct_grant_client_is_public_and_dev_only` add, after the `"dev-only"` assertion:

```python
    # The API is a resource server like the MCP servers: a persona token must name it (ruling 3 of Plan D), so a
    # browser or workload token minted for another audience cannot be replayed at the API.
    assert audiences(d) == {"ops-api"}
```

In `tests/plan_b/live/test_keycloak_tokens.py`, in the persona test, after the `azp` assertion add:

```python
        aud = c["aud"]
        assert "ops-api" in ([aud] if isinstance(aud, str) else aud)  # Keycloak emits a bare string for one audience
```

(Find the exact function by `grep -n "ops-dev-direct" tests/plan_b/live/test_keycloak_tokens.py`; if it already asserts the absence of `aud`, replace that assertion.)

- [ ] **Step 8: The incident database secret**

In `scripts/bootstrap_dev.py` append `"postgres_incident_password",` to `SECRET_NAMES` (after `"postgres_password",`; keep one name per line). In `compose.yaml` add, under the top-level `secrets:` map, `postgres_incident_password:` with `file: ${OPS_SECRETS_DIR}/postgres_incident_password` in the same style as `postgres_password`; attach it to no service (the role is created by `migrations/incident`, Task 2, from the file on the host). Run `uv run python scripts/bootstrap_dev.py secrets` so the new file exists locally (prints only names).

Run: `PYTHONUTF8=1 uv run python -m pytest tests/plan_b -q -p no:cacheprovider`
Expected: all pass (the compose/bootstrap/realm static tests see the new secret, mapper and audience; live tests skipped).

- [ ] **Step 9: Re-import the realm (Keycloak's data is ephemeral: no volume) and prove the audience live**

Run: `uv run python scripts/bootstrap_dev.py down && uv run python scripts/bootstrap_dev.py up`
Expected: both services healthy; the bootstrap admin reported deleted.
Run: `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/plan_b/live -q`
Expected: all pass, including the new `ops-api` audience assertion (record the summary line).

- [ ] **Step 10: Full check and commit**

Run: `uv run ruff format core/src/ops_core/settings.py tests/plan_d && uv run ruff check --fix core/src/ops_core/settings.py tests/plan_d && PYTHONUTF8=1 uv run python scripts/check.py 2>&1 | tail -3`
Expected: `CHECK: GREEN` (totals: Plan C's 381 passed plus the 5 settings tests; skips unchanged).

```bash
git add deploy/dev/keycloak/realm-ops-dev.json tests/plan_b/test_realm_template.py tests/plan_b/live/test_keycloak_tokens.py scripts/bootstrap_dev.py compose.yaml core/pyproject.toml api/pyproject.toml incident-sim/pyproject.toml worker/pyproject.toml mcp-read/pyproject.toml mcp-write/pyproject.toml pyproject.toml uv.lock core/src/ops_core/settings.py tests/plan_d tests/e2e reports/bootstrap/keycloak-claims.txt reports/bootstrap/bootstrap-admin.txt
git commit -m "feat(dev): ops-api audience for persona tokens, incident database secret, skeleton dependencies and the shared settings module"
```

---
### Task 2: Alembic revision 1 for both databases, the shared persistence adapter, `skeleton.py migrate`

**Files:**
- Create: `migrations/__init__.py` (empty), `migrations/app/env.py`, `migrations/app/script.py.mako`, `migrations/app/versions/0001_walking_skeleton.py`, `migrations/incident/env.py`, `migrations/incident/script.py.mako`, `migrations/incident/versions/0001_walking_skeleton.py`, `core/src/ops_core/persistence.py`, `scripts/skeleton.py` (the `migrate` subcommand; Task 9 adds `up`/`down`/`status`), `tests/plan_d/test_persistence_pure.py`, `tests/e2e/conftest.py`, `tests/e2e/test_migrations_and_persistence.py`
- Modify: `pyproject.toml` (`[tool.ruff] extend-exclude` unchanged; `[tool.mypy]` gains `files`? No — `scripts/check.py` runs mypy on `MEMBER_SRC` only; `migrations/` and `scripts/skeleton.py` are checked by ruff and by their tests)

**Interfaces:**
- Consumes: `ops_core.settings` (Task 1); `ops_core.states.require_transition`, `RunState`, `Performer`, `Reason`, `ACTIVE_STATES`; `ops_core.jobs.JobType`, `JOB_RULES`, `Server`, `Tool`, `dedup_key`, `server_for`; `ops_core.outcomes.Event`, `EventType`, `EventSource`.
- Produces: `ops_core.persistence` — exceptions `PersistenceError(Exception)`, `NotFound(PersistenceError)`, `VersionConflict(PersistenceError)`, `HandleRejected(PersistenceError)`; `Conn = psycopg.AsyncConnection[DictRow]`; `async connect(pg: Postgres) -> Conn` (autocommit); `class Session(conn)` with `unit()` (lock + transaction) and `read(query, params)`; `async transition(conn, *, run_id, dst, performer, reason=None, expected_version=None) -> int`; `async create_run(conn, *, run_id, tenant_id, conversation_id, message_id, requester, intent, asset_id, start_at, end_at, supersedes_run_id=None) -> int` (QUEUED, history seq 1, the `investigate` job; returns `state_version`); `async append_event(conn, *, tenant_id, conversation_id, run_id, type, source, payload, occurred_at=None) -> Event`; `async insert_job(conn, *, job_type, run_id, **ids) -> UUID | None`; `async claim_job(conn, *, worker_name) -> DictRow | None`; `async finish_job(conn, job_id) -> None`; `async mint_handle(conn, *, run_id, job_id, server, azp, ttl_seconds=60) -> str`; `@dataclass(frozen=True) class Invocation(run_id, job_id, job_type, tenant_id, conversation_id)`; `check_invocation(row, *, server, azp, tool, now) -> Invocation` (pure); `async resolve_handle(conn, *, handle, server, azp, tool) -> Invocation`; `async run_row(conn, run_id, *, lock=False) -> DictRow`.
- Produces: `scripts/skeleton.py migrate` (both databases to head, idempotent; creates/updates the `incident` role from the secret file first); `tests/e2e/conftest.py` fixtures `live`, `env`, `secret`, `app_conn` (async psycopg connection as `ops`), `migrated` (runs `migrate()` once per session).
- Produces: schema `app` (15 tables, ruling 7) and schema `incident` (`action_key`, `incidents`, sequence `incident_seq`), revision ids `0001_walking_skeleton` in both trees.

- [ ] **Step 1: The pure test (no database)**

Create `tests/plan_d/test_persistence_pure.py`:

```python
"""Invocation-handle checks (BUILD_SPEC §9 handle binding, R131 in miniature): the part of resolve_invocation that
needs no database — expiry, revocation, server binding derived from the job type (not the stored column), the caller's
azp, and the per-job-type tool allowlist.

Catches: an expired or revoked handle still usable, a read handle accepted by mcp-write (server derived from the
worker-written column instead of the job type), another workload's token replaying a stolen handle, and a read job
calling a write tool.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from ops_core.jobs import JobType, Server, Tool
from ops_core.persistence import HandleRejected, check_invocation

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
RUN, JOB, TENANT, CONV = UUID(int=1), UUID(int=2), UUID(int=3), UUID(int=4)


def row(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "handle": "h",
        "run_id": RUN,
        "job_id": JOB,
        "server": "read",
        "azp": "ops-worker",
        "expires_at": NOW + timedelta(seconds=30),
        "revoked_at": None,
        "job_type": "investigate",
        "tenant_id": TENANT,
        "conversation_id": CONV,
    }
    base.update(over)
    return base


def test_valid_read_handle_resolves_to_its_run_and_job():
    inv = check_invocation(row(), server=Server.READ, azp="ops-worker", tool=Tool.SEARCH_PROCEDURES, now=NOW)
    assert (inv.run_id, inv.job_id, inv.job_type, inv.tenant_id) == (RUN, JOB, JobType.INVESTIGATE, TENANT)


@pytest.mark.parametrize(
    ("over", "server", "azp", "tool"),
    [
        ({"expires_at": NOW}, Server.READ, "ops-worker", Tool.SEARCH_PROCEDURES),  # expiry is exclusive
        ({"revoked_at": NOW - timedelta(seconds=1)}, Server.READ, "ops-worker", Tool.SEARCH_PROCEDURES),
        ({}, Server.WRITE, "ops-worker", Tool.CREATE_INCIDENT),  # investigate handle presented to mcp-write
        ({"job_type": "execute", "server": "read"}, Server.READ, "ops-worker", Tool.SEARCH_PROCEDURES),  # column lies
        ({}, Server.READ, "ops-mcp-write", Tool.SEARCH_PROCEDURES),  # another workload replays the handle
        ({}, Server.READ, "ops-worker", Tool.CREATE_INCIDENT),  # a read job may not call a write tool
        ({"job_type": "execute", "server": "write"}, Server.WRITE, "ops-worker", Tool.GET_INCIDENT_RECEIPT),  # execute ≠ recover
    ],
)
def test_rejections(over: dict[str, object], server: Server, azp: str, tool: Tool):
    with pytest.raises(HandleRejected):
        check_invocation(row(**over), server=server, azp=azp, tool=tool, now=NOW)


def test_rejection_messages_never_echo_the_handle():
    with pytest.raises(HandleRejected) as caught:
        check_invocation(row(handle="secret-handle-value", expires_at=NOW), server=Server.READ, azp="ops-worker",
                         tool=Tool.SEARCH_PROCEDURES, now=NOW)
    assert "secret-handle-value" not in str(caught.value)
```

Run: `PYTHONUTF8=1 uv run python -m pytest tests/plan_d/test_persistence_pure.py -q`
Expected: an `ImportError` for `ops_core.persistence` (the module does not exist yet).

- [ ] **Step 2: The app database revision**

Create `migrations/__init__.py` (empty; makes `migrations.app`/`migrations.incident` importable for the tests). Create `migrations/app/script.py.mako` (Alembic's stock template, needed only for `alembic revision`):

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

Create `migrations/app/env.py`:

```python
"""Alembic environment for the application database (schema `app`).

The connection is handed in by scripts/skeleton.py through `config.attributes["connection"]` (Alembic's documented
pattern for programmatic runs); the engine behind it is built from a SQLAlchemy `URL` object whose password is never
rendered into a string or logged. Offline mode is not supported: the skeleton always migrates against a live database.
"""

from alembic import context

connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("migrations/app runs only through scripts/skeleton.py migrate (no URL mode)")

# The version table stays in `public`: Alembic writes it before revision 0001 runs `CREATE SCHEMA app`.
context.configure(connection=connection, target_metadata=None, version_table="alembic_version")
with context.begin_transaction():
    context.run_migrations()
```

Create `migrations/app/versions/0001_walking_skeleton.py`:

```python
"""Walking skeleton: the run path's tables with their AM-20.2 names (T08; T09 re-owns, adds roles and RLS).

Revision ID: 0001_walking_skeleton
Revises: None

Only the tables the skeleton path touches exist (ruling 7 of Plan D). Column names follow SPEC_AMENDMENTS AM-20.2 /
AM-20.4 so T09's revision alters rather than renames; the one deliberate exception is `invocation_context.handle`
(raw, debt → T09/T15 replaces it by `handle_sha256`). Audit tables are append-only by shape: `run_state_history`,
`action_attempt_state` and `events` have no updatable business columns (AM-20 principle 2). Seed rows: the two tenants
and five persona memberships from data/seed-ids.json, written here because no runtime role may insert them (SA:440).
"""

import json
import os
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0001_walking_skeleton"
down_revision = None
branch_labels = None
depends_on = None

# AM-10 active states, for the one-active-run-per-conversation rule (BUILD_SPEC §7; T12 owns the admission test).
ACTIVE = "'QUEUED','AWAITING_INPUT','RETRIEVING','DRAFTING','AWAITING_APPROVAL','APPROVED','EXECUTING','OUTCOME_UNKNOWN'"

DDL = f"""
CREATE SCHEMA app;

CREATE TABLE app.tenants (
    tenant_id uuid PRIMARY KEY,
    name text NOT NULL UNIQUE
);

-- Identity is (issuer, subject) (BUILD_SPEC §9); membership, not the token, decides the tenant and the role.
CREATE TABLE app.memberships (
    tenant_id uuid NOT NULL REFERENCES app.tenants (tenant_id),
    issuer text NOT NULL,
    subject uuid NOT NULL,
    role text NOT NULL CHECK (role IN ('requester', 'reviewer', 'reader')),
    active boolean NOT NULL DEFAULT true,
    permission_version integer NOT NULL DEFAULT 1,
    synced_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, issuer, subject, role)
);

CREATE TABLE app.conversations (
    conversation_id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES app.tenants (tenant_id),
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, conversation_id)
);

CREATE TABLE app.messages (
    message_id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL,
    conversation_id uuid NOT NULL,
    kind text NOT NULL,
    text text NOT NULL,
    context jsonb,
    author uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, conversation_id) REFERENCES app.conversations (tenant_id, conversation_id)
);

CREATE TABLE app.runs (
    run_id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL,
    conversation_id uuid NOT NULL,
    message_id uuid NOT NULL REFERENCES app.messages (message_id),
    requester uuid NOT NULL,
    intent text NOT NULL CHECK (intent IN ('investigate', 'answer_only')),
    supersedes_run_id uuid,
    asset_id text NOT NULL,
    start_at timestamptz NOT NULL,
    end_at timestamptz NOT NULL,
    state text NOT NULL,
    state_version integer NOT NULL DEFAULT 1,
    reason text,
    active_proposal_id uuid,
    cancel_requested boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (start_at < end_at),
    UNIQUE (tenant_id, run_id),
    FOREIGN KEY (tenant_id, conversation_id) REFERENCES app.conversations (tenant_id, conversation_id)
);
CREATE UNIQUE INDEX runs_one_active_per_conversation ON app.runs (conversation_id) WHERE state IN ({ACTIVE});

CREATE TABLE app.run_state_history (
    run_id uuid NOT NULL REFERENCES app.runs (run_id),
    seq integer NOT NULL,
    from_state text,
    to_state text NOT NULL,
    performer text NOT NULL,
    reason text,
    at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, seq)
);

CREATE TABLE app.jobs (
    id uuid PRIMARY KEY,
    type text NOT NULL,
    run_id uuid NOT NULL REFERENCES app.runs (run_id),
    dedup_key text NOT NULL UNIQUE,
    available_at timestamptz NOT NULL DEFAULT now(),
    claimed_by text,
    claimed_at timestamptz,
    attempts integer NOT NULL DEFAULT 0,
    done_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX jobs_claimable ON app.jobs (available_at) WHERE done_at IS NULL AND claimed_at IS NULL;

CREATE TABLE app.invocation_context (
    handle text PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES app.runs (run_id),
    job_id uuid NOT NULL REFERENCES app.jobs (id),
    server text NOT NULL CHECK (server IN ('read', 'write')),
    fence integer NOT NULL DEFAULT 1,
    azp text NOT NULL,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.drafts (
    id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES app.runs (run_id),
    draft_sha256 text NOT NULL,
    validated boolean NOT NULL,
    kind text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.proposals (
    proposal_id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL,
    run_id uuid NOT NULL REFERENCES app.runs (run_id),
    revision integer NOT NULL,
    draft_id uuid NOT NULL REFERENCES app.drafts (id),
    payload jsonb NOT NULL,
    payload_canonical bytea NOT NULL,
    payload_sha256 text NOT NULL,
    canonicalization_version integer NOT NULL,
    authored_by uuid[] NOT NULL,
    expires_at timestamptz NOT NULL,
    frozen_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, revision)
);

-- UNIQUE (proposal_id): the first accepted decision wins (SA:454); a second one is a 409, never an overwrite.
CREATE TABLE app.decisions (
    decision_id uuid PRIMARY KEY,
    proposal_id uuid NOT NULL UNIQUE REFERENCES app.proposals (proposal_id),
    reviewer uuid NOT NULL,
    decision text NOT NULL CHECK (decision IN ('approve', 'reject')),
    reason text,
    expected_payload_sha256 text NOT NULL,
    decided_at timestamptz NOT NULL DEFAULT now()
);

-- At most one grant per run, ever (SA:167): UNIQUE (run_id) is the rule, not application code.
CREATE TABLE app.execution_grant (
    action_id uuid PRIMARY KEY,
    run_id uuid NOT NULL UNIQUE REFERENCES app.runs (run_id),
    proposal_id uuid NOT NULL REFERENCES app.proposals (proposal_id),
    payload_sha256 text NOT NULL,
    granted_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.action_attempt (
    action_id uuid NOT NULL REFERENCES app.execution_grant (action_id),
    attempt_no integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (action_id, attempt_no)
);

CREATE TABLE app.action_attempt_state (
    action_id uuid NOT NULL,
    attempt_no integer NOT NULL,
    seq integer NOT NULL,
    state text NOT NULL CHECK (state IN ('INTENT', 'SENT', 'ABORT_REQUESTED', 'RESOLVED')),
    outcome text,
    detail jsonb,
    at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (action_id, attempt_no, seq),
    FOREIGN KEY (action_id, attempt_no) REFERENCES app.action_attempt (action_id, attempt_no)
);

CREATE TABLE app.events (
    event_id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL,
    conversation_id uuid NOT NULL,
    run_id uuid NOT NULL REFERENCES app.runs (run_id),
    sequence integer NOT NULL,
    type text NOT NULL,
    occurred_at timestamptz NOT NULL,
    source text NOT NULL CHECK (source IN ('application', 'destination', 'model_summary')),
    payload jsonb NOT NULL,
    UNIQUE (run_id, sequence)
);
"""


def upgrade() -> None:
    for statement in DDL.split(";\n"):
        if statement.strip():
            op.execute(statement)
    seeds = json.loads((Path(__file__).resolve().parents[3] / "data" / "seed-ids.json").read_text(encoding="utf-8"))
    # The issuer is part of the membership identity; the dev default matches scripts/bootstrap_dev.py.
    issuer = os.environ.get("OPS_KC_ISSUER") or "http://localhost:18080/realms/ops-dev"
    tenants = sa.table("tenants", sa.column("tenant_id"), sa.column("name"), schema="app")
    op.bulk_insert(tenants, [{"tenant_id": tid, "name": name} for name, tid in seeds["tenants"].items()])
    memberships = sa.table(
        "memberships", sa.column("tenant_id"), sa.column("issuer"), sa.column("subject"), sa.column("role"), schema="app"
    )
    op.bulk_insert(
        memberships,
        [
            {"tenant_id": seeds["tenants"][p["tenant"]], "issuer": issuer, "subject": p["user_id"], "role": role}
            for p in seeds["personas"].values()
            for role in p["roles"]
        ],
    )


def downgrade() -> None:
    op.execute("DROP SCHEMA app CASCADE")
```

- [ ] **Step 3: The incident database revision**

Create `migrations/incident/script.py.mako` (same stock template as Step 2) and `migrations/incident/env.py` identical to the app one except the docstring's first line ("…for the destination database (schema `incident`)") and the `RuntimeError` text, which names `migrations/incident`. Create `migrations/incident/versions/0001_walking_skeleton.py`:

```python
"""Destination (incident-sim) database: the single `action_key` table and the incidents it commits (AM-13 §4; T10 extends).

Revision ID: 0001_walking_skeleton
Revises: None

Runs as the Compose superuser against database `incident` and hands everything to role `incident`, which
scripts/skeleton.py creates first from the `postgres_incident_password` secret file. The application database never
sees these tables and the `incident` role sees no application table (BUILD_SPEC §14: separate credentials).
"""

from alembic import op

revision = "0001_walking_skeleton"
down_revision = None
branch_labels = None
depends_on = None

DDL = """
CREATE SCHEMA incident AUTHORIZATION incident;

-- All three states are permanent and terminal; rows are never deleted (SA:259, SA:265).
CREATE TABLE incident.action_key (
    action_id uuid PRIMARY KEY,
    payload_sha256 text NOT NULL,
    state text NOT NULL CHECK (state IN ('COMMITTED', 'ABORTED', 'REJECTED')),
    incident_id text,
    reason text,
    receipt_id uuid,
    decided_at timestamptz NOT NULL DEFAULT now()
);

CREATE SEQUENCE incident.incident_seq;  -- incident numbers may have gaps: a conflicting insert consumes nextval too

CREATE TABLE incident.incidents (
    incident_id text PRIMARY KEY,
    action_id uuid NOT NULL UNIQUE REFERENCES incident.action_key (action_id),
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE incident.action_key OWNER TO incident;
ALTER TABLE incident.incidents OWNER TO incident;
ALTER SEQUENCE incident.incident_seq OWNER TO incident;
"""


def upgrade() -> None:
    for statement in DDL.split(";\n"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    op.execute("DROP SCHEMA incident CASCADE")
```

- [ ] **Step 4: `scripts/skeleton.py migrate`**

Create `scripts/skeleton.py`:

```python
"""Walking-skeleton operations (T08): `migrate` both databases to head; Task 9 adds `up`, `down`, `status`.

Reads `.env` (written by scripts/bootstrap_dev.py) for ports and the secrets directory, exports the `OPS_*` variables
every service reads (ops_core.settings), and runs the two Alembic trees programmatically with a shared connection
(Alembic cookbook: "Sharing a Connection across one or more programmatic migration commands"); the engine is built
from a `URL` object, so the password is never rendered into a string. The `incident` role is created or re-keyed from its secret file on every run; role credentials
are a bootstrap concern, schema is the migration's.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

from ops_core import settings

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = {"app": ROOT / "migrations" / "app", "incident": ROOT / "migrations" / "incident"}


def load_dotenv(path: Path = Path(".env")) -> dict[str, str]:
    """Parse the KEY=VALUE lines of .env; the file holds paths, ports and URLs only (never a secret)."""
    if not path.exists():
        raise SystemExit("no .env: run `uv run python scripts/bootstrap_dev.py secrets` first")
    pairs = (line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines() if line and "=" in line)
    return {k.strip(): v.strip() for k, v in pairs if not k.startswith("#")}


def export_environment(dotenv: dict[str, str]) -> None:
    """Derive the OPS_* variables from .env without overriding anything the caller already set."""
    base = f"http://localhost:{dotenv['KC_HTTP_PORT']}"
    derived = {
        "OPS_SECRETS_DIR": dotenv["OPS_SECRETS_DIR"],
        "OPS_PG_PORT": dotenv["PG_PORT"],
        "OPS_KC_BASE_URL": base,
        "OPS_KC_ISSUER": f"{base}/realms/{settings.REALM}",
        "MCP_READ_RESOURCE_URL": dotenv["MCP_READ_RESOURCE_URL"],
        "MCP_WRITE_RESOURCE_URL": dotenv["MCP_WRITE_RESOURCE_URL"],
    }
    for key, value in derived.items():
        os.environ.setdefault(key, value)


def ensure_incident_role(superuser: settings.Postgres, password: str) -> None:
    """CREATE or re-key role `incident` with the secret file's value; idempotent so `migrate` can be re-run."""
    with psycopg.connect(superuser.conninfo(), autocommit=True) as conn:
        # Utility statements take no bind parameters, so the password travels through a session setting and
        # format(%L) quotes it server-side; it never appears in a Python-built SQL string.
        conn.execute("SELECT set_config('ops.incident_password', %s, false)", (password,))
        conn.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'incident') THEN
                    EXECUTE format('CREATE ROLE incident LOGIN PASSWORD %L', current_setting('ops.incident_password'));
                ELSE
                    EXECUTE format('ALTER ROLE incident PASSWORD %L', current_setting('ops.incident_password'));
                END IF;
            END
            $$
            """
        )
        conn.execute("GRANT CONNECT ON DATABASE incident TO incident")


def upgrade(tree: str, pg: settings.Postgres) -> None:
    url = URL.create("postgresql+psycopg", username=pg.user, password=pg.password, host=pg.host, port=pg.port,
                     database=pg.dbname)
    engine = create_engine(url)
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS[tree]))
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")
    engine.dispose()


def migrate() -> int:
    export_environment(load_dotenv(ROOT / ".env"))
    app_pg = settings.app_postgres()
    incident_as_superuser = settings.Postgres(app_pg.host, app_pg.port, app_pg.user, "incident", app_pg.password)
    ensure_incident_role(incident_as_superuser, settings.read_secret("postgres_incident_password"))
    upgrade("app", app_pg)
    upgrade("incident", incident_as_superuser)
    print("MIGRATE: app and incident at head")
    return 0


def main(argv: list[str]) -> int:
    if argv[1:] == ["migrate"]:
        return migrate()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

Note for the implementer: the `URL.create(...)` password is held by SQLAlchemy's engine object only; `str(url)` masks it and nothing logs it. If `command.upgrade` complains about the missing `version_table` schema on the incident tree, keep `version_table_schema=None` there (see Step 3).

- [ ] **Step 5: The persistence adapter**

Create `core/src/ops_core/persistence.py`:

```python
"""The skeleton's one door to the application database (T08; every function names the AM-20.3 definer function that
replaces it in T09).

Every state change in every service goes through `transition()`, which calls `ops_core.states.require_transition`
before the plain UPDATE, so the transition table is enforced in exactly one place (R082 "one table, one function").
Events are built as `ops_core.outcomes.Event` before they are inserted, so AM-14's source and payload rules hold for
every producer. Plain INSERT/UPDATE as the single owner role is declared debt in SESSION_STATE.md.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import DictRow, dict_row
from psycopg.types.json import Jsonb

from ops_core.jobs import JOB_RULES, JobType, Server, Tool, dedup_key, server_for
from ops_core.outcomes import Event, EventSource, EventType, event_rules_ok
from ops_core.settings import Postgres
from ops_core.states import Intent, Performer, Reason, RunState, require_transition

Conn = psycopg.AsyncConnection[DictRow]


class PersistenceError(Exception):
    """Base class; messages are safe for logs and HTTP bodies (no handle, token or secret)."""


class NotFound(PersistenceError):
    pass


class VersionConflict(PersistenceError):
    pass


class HandleRejected(PersistenceError):
    pass


async def connect(pg: Postgres) -> Conn:
    """One autocommit connection per process (ruling 24).

    With autocommit off, a bare SELECT silently opens a transaction that every later `transaction()` block nests into as
    a savepoint, so nothing commits until the connection is closed (measured by the round-1 static critic). Autocommit
    makes a bare statement its own transaction and `async with conn.transaction()` a real BEGIN/COMMIT.
    """
    return await psycopg.AsyncConnection.connect(pg.conninfo(), row_factory=dict_row, autocommit=True)


class Session:
    """One connection, one unit of work at a time: the lock keeps concurrent requests from interleaving on the
    connection; the transaction makes the unit atomic. Never enter `unit()` while holding it (the lock is not
    re-entrant: a nested unit deadlocks); callers pass the `conn` a unit yields instead. TODO(T13): a pool."""

    def __init__(self, conn: Conn) -> None:
        self.conn = conn
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def unit(self) -> AsyncIterator[Conn]:
        async with self._lock, self.conn.transaction():
            yield self.conn

    async def read(self, query: str, params: tuple[object, ...]) -> DictRow | None:
        """A single autocommit SELECT (no transaction to leave open), serialised like a unit."""
        async with self._lock:
            cur = await self.conn.execute(query, params)
            return await cur.fetchone()


async def run_row(conn: Conn, run_id: UUID, *, lock: bool = False) -> DictRow:
    suffix = " FOR UPDATE" if lock else ""
    cur = await conn.execute(f"SELECT * FROM app.runs WHERE run_id = %s{suffix}", (run_id,))
    row = await cur.fetchone()
    if row is None:
        raise NotFound("run not found")
    return row


async def transition(
    conn: Conn,
    *,
    run_id: UUID,
    dst: RunState,
    performer: Performer,
    reason: Reason | None = None,
    expected_version: int | None = None,
) -> int:
    """Move a run one row along the transition table under the runs lock; returns the new state_version.

    TODO(T09): becomes the SQL `transition_run` / per-performer definer functions; callers keep this signature.
    """
    row = await run_row(conn, run_id, lock=True)
    if expected_version is not None and row["state_version"] != expected_version:
        raise VersionConflict("stale state_version")
    require_transition(RunState(row["state"]), dst, performer, reason)  # raises IllegalTransition, never UPDATEs
    version: int = row["state_version"] + 1
    await conn.execute(
        "UPDATE app.runs SET state = %s, state_version = %s, reason = %s, updated_at = now() WHERE run_id = %s",
        (dst.value, version, reason.value if reason else None, run_id),
    )
    await conn.execute(
        "INSERT INTO app.run_state_history (run_id, seq, from_state, to_state, performer, reason)"
        " VALUES (%s, %s, %s, %s, %s, %s)",
        (run_id, version, row["state"], dst.value, performer.value, reason.value if reason else None),
    )
    return version


async def create_run(
    conn: Conn,
    *,
    run_id: UUID,
    tenant_id: UUID,
    conversation_id: UUID,
    message_id: UUID,
    requester: UUID,
    intent: Intent,
    asset_id: str,
    start_at: datetime,
    end_at: datetime,
    supersedes_run_id: UUID | None = None,
) -> int:
    """∅ → QUEUED with its first history row and the `investigate` job (SA:450). TODO(T09): SQL `create_run`."""
    require_transition(None, RunState.QUEUED, Performer.CREATE_RUN)
    await conn.execute(
        "INSERT INTO app.runs (run_id, tenant_id, conversation_id, message_id, requester, intent, supersedes_run_id,"
        " asset_id, start_at, end_at, state, state_version)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)",
        (run_id, tenant_id, conversation_id, message_id, requester, intent.value, supersedes_run_id, asset_id,
         start_at, end_at, RunState.QUEUED.value),
    )
    await conn.execute(
        "INSERT INTO app.run_state_history (run_id, seq, from_state, to_state, performer) VALUES (%s, 1, NULL, %s, %s)",
        (run_id, RunState.QUEUED.value, Performer.CREATE_RUN.value),
    )
    await insert_job(conn, job_type=JobType.INVESTIGATE, run_id=run_id, revision=1)
    return 1


async def append_event(
    conn: Conn,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    run_id: UUID,
    type: EventType,
    source: EventSource,
    payload: dict[str, Any],
    occurred_at: datetime | None = None,
) -> Event:
    """Validate through `Event` (AM-14 rules) and insert with the next per-run sequence under the runs lock.

    The runs row lock makes `sequence` gap-free and commit-ordered without T14's `next_event_seq` column.
    TODO(T14): `append_event` definer function with `next_event_seq`.
    """
    event_rules_ok(type, source, payload)  # raises EventRuleViolation (AM-14) before the model wraps it
    await conn.execute("SELECT run_id FROM app.runs WHERE run_id = %s FOR UPDATE", (run_id,))
    cur = await conn.execute("SELECT COALESCE(MAX(sequence), 0) + 1 AS next FROM app.events WHERE run_id = %s", (run_id,))
    row = await cur.fetchone()
    assert row is not None  # COALESCE always yields one row
    sequence: int = row["next"]
    event = Event(
        event_id=uuid4(),
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        run_id=run_id,
        sequence=sequence,
        type=type,
        occurred_at=occurred_at or datetime.now(UTC).replace(microsecond=0),
        source=source,
        payload=payload,
    )
    await conn.execute(
        "INSERT INTO app.events (event_id, tenant_id, conversation_id, run_id, sequence, type, occurred_at, source,"
        " payload) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (event.event_id, event.tenant_id, event.conversation_id, event.run_id, event.sequence, event.type.value,
         event.occurred_at, event.source.value, Jsonb(event.payload)),
    )
    return event


async def insert_job(conn: Conn, *, job_type: JobType, run_id: UUID, **ids: UUID | int | str) -> UUID | None:
    """Insert a wake-up; a duplicate dedup key is silently a no-op (AM-20.4) and returns None."""
    key = dedup_key(job_type, run_id=run_id, **ids) if job_type is not JobType.EXECUTE else dedup_key(job_type, **ids)
    cur = await conn.execute(
        "INSERT INTO app.jobs (id, type, run_id, dedup_key) VALUES (%s, %s, %s, %s)"
        " ON CONFLICT (dedup_key) DO NOTHING RETURNING id",
        (uuid4(), job_type.value, run_id, key),
    )
    row = await cur.fetchone()
    return None if row is None else UUID(str(row["id"]))


async def claim_job(conn: Conn, *, worker_name: str) -> DictRow | None:
    """Claim the oldest available job (BUILD_SPEC §11: SKIP LOCKED for queue consumers). TODO(T13): lease + fence."""
    cur = await conn.execute(
        "UPDATE app.jobs SET claimed_by = %s, claimed_at = now(), attempts = attempts + 1"
        " WHERE id = (SELECT id FROM app.jobs WHERE done_at IS NULL AND claimed_at IS NULL AND available_at <= now()"
        "             ORDER BY available_at, id FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *",
        (worker_name,),
    )
    return await cur.fetchone()


async def finish_job(conn: Conn, job_id: UUID) -> None:
    await conn.execute("UPDATE app.jobs SET done_at = now() WHERE id = %s", (job_id,))


async def mint_handle(conn: Conn, *, run_id: UUID, job_id: UUID, server: Server, azp: str, ttl_seconds: int = 60) -> str:
    """A 256-bit capability lookup key bound to one job and one server (BUILD_SPEC §9). Stored raw: debt → T09/T15."""
    handle = secrets.token_urlsafe(32)
    await conn.execute(
        "INSERT INTO app.invocation_context (handle, run_id, job_id, server, azp, expires_at)"
        " VALUES (%s, %s, %s, %s, %s, %s)",
        (handle, run_id, job_id, server.value, azp, datetime.now(UTC) + timedelta(seconds=ttl_seconds)),
    )
    return handle


@dataclass(frozen=True)
class Invocation:
    run_id: UUID
    job_id: UUID
    job_type: JobType
    tenant_id: UUID
    conversation_id: UUID


def check_invocation(row: dict[str, Any], *, server: Server, azp: str, tool: Tool, now: datetime) -> Invocation:
    """The handle rules, database-free so they are unit-tested: expiry, revocation, server derived from the job type
    (SA:496: never the worker-written column alone), the caller's azp, and the job type's tool allowlist."""
    if row["revoked_at"] is not None or row["expires_at"] <= now:
        raise HandleRejected("invocation handle expired or revoked")
    job_type = JobType(row["job_type"])
    if server_for(job_type) is not server or row["server"] != server.value:
        raise HandleRejected("invocation handle is bound to the other server")
    if row["azp"] != azp:
        raise HandleRejected("invocation handle was issued to another workload")
    if tool not in JOB_RULES[job_type].allowed_tools:
        raise HandleRejected("tool is not allowed for this job type")
    return Invocation(row["run_id"], row["job_id"], job_type, row["tenant_id"], row["conversation_id"])


async def resolve_handle(conn: Conn, *, handle: str, server: Server, azp: str, tool: Tool) -> Invocation:
    """Look the handle up by equality (raw, debt → T09/T15 hash it) and apply `check_invocation`.
    TODO(T09/T15): SQL `resolve_invocation`."""
    cur = await conn.execute(
        "SELECT ic.handle, ic.run_id, ic.job_id, ic.server, ic.azp, ic.expires_at, ic.revoked_at, j.type AS job_type,"
        " r.tenant_id, r.conversation_id FROM app.invocation_context ic"
        " JOIN app.jobs j ON j.id = ic.job_id JOIN app.runs r ON r.run_id = ic.run_id WHERE ic.handle = %s",
        (handle,),
    )
    row = await cur.fetchone()
    if row is None:
        raise HandleRejected("unknown invocation handle")
    return check_invocation(dict(row), server=server, azp=azp, tool=tool, now=datetime.now(UTC))
```

Run: `PYTHONUTF8=1 uv run python -m pytest tests/plan_d/test_persistence_pure.py -q`
Expected: `9 passed`.

- [ ] **Step 6: The live tests and the e2e conftest**

Create `tests/e2e/conftest.py`:

```python
"""Live fixtures for the walking skeleton: only with OPS_LIVE=1 and the dev profile up. Secrets are read from files,
never printed. Task 9 adds the `skeleton` fixture that starts the five processes."""

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest
import pytest_asyncio
from ops_core import persistence, settings

if sys.platform == "win32":
    # psycopg async refuses the Proactor loop, and Python's default policy on Windows (and uvicorn.run) picks it
    # (measured in the Plan D spike and its round-1 review). pytest-asyncio builds its loops from the policy, so the
    # selector policy is installed once, here, for every live test on the Windows dev machine.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="session")
def live() -> None:
    if os.environ.get("OPS_LIVE") != "1":
        pytest.skip("live walking-skeleton tests run only with OPS_LIVE=1")


@pytest.fixture(scope="session")
def env(live: None) -> dict[str, str]:
    import sys

    sys.path.insert(0, str(ROOT))
    from scripts.skeleton import export_environment, load_dotenv

    dotenv = load_dotenv(ROOT / ".env")
    export_environment(dotenv)
    return dotenv


@pytest.fixture(scope="session")
def secret(env: dict[str, str]) -> Callable[[str], str]:
    return lambda name: settings.read_secret(name)


@pytest.fixture(scope="session")
def migrated(env: dict[str, str]) -> None:
    from scripts.skeleton import migrate

    assert migrate() == 0


@pytest_asyncio.fixture
async def app_conn(migrated: None) -> AsyncIterator[persistence.Conn]:
    """An autocommit connection: a test that must leave nothing behind wraps itself in
    `async with app_conn.transaction(force_rollback=True)`; a test whose rows another process must see cleans up with
    `purge_run` in a `finally`."""
    conn = await persistence.connect(settings.app_postgres())
    try:
        yield conn
    finally:
        await conn.close()


PURGE_ORDER = (
    "DELETE FROM app.invocation_context WHERE run_id = %s",
    "DELETE FROM app.events WHERE run_id = %s",
    "DELETE FROM app.action_attempt_state WHERE action_id IN (SELECT action_id FROM app.execution_grant WHERE run_id = %s)",
    "DELETE FROM app.action_attempt WHERE action_id IN (SELECT action_id FROM app.execution_grant WHERE run_id = %s)",
    "DELETE FROM app.execution_grant WHERE run_id = %s",
    "DELETE FROM app.decisions WHERE proposal_id IN (SELECT proposal_id FROM app.proposals WHERE run_id = %s)",
    "DELETE FROM app.proposals WHERE run_id = %s",
    "DELETE FROM app.drafts WHERE run_id = %s",
    "DELETE FROM app.jobs WHERE run_id = %s",
    "DELETE FROM app.run_state_history WHERE run_id = %s",
)


async def purge_run(conn: persistence.Conn, run_id: object) -> None:
    """Remove one test run, everything hanging off it, and the message and conversation `new_run` made for it
    (reverse foreign-key order). A random tenant is removed by `purge_tenant`; a seeded tenant is never touched.
    This deletes test-created rows from append-only audit tables as the owner role (ruling 27); T09's grants will
    refuse that, and the live tests then get a per-session schema or a reset."""
    async with conn.transaction():
        for statement in PURGE_ORDER:
            await conn.execute(statement, (run_id,))
        cur = await conn.execute("DELETE FROM app.runs WHERE run_id = %s RETURNING message_id, conversation_id", (run_id,))
        row = await cur.fetchone()
        if row is not None:
            await conn.execute("DELETE FROM app.messages WHERE message_id = %s", (row["message_id"],))
            await conn.execute("DELETE FROM app.conversations WHERE conversation_id = %s", (row["conversation_id"],))


SEEDED_TENANTS = {"3ea79c95-914c-52cb-9d10-c4e19dda8ff7", "5ab45c2c-1e12-5a0c-a2b9-66cd2ff05201"}


async def purge_tenant(conn: persistence.Conn, tenant_id: object) -> None:
    if str(tenant_id) in SEEDED_TENANTS:
        return  # seeded by the migration; never deleted by a test
    async with conn.transaction():
        await conn.execute("DELETE FROM app.memberships WHERE tenant_id = %s", (tenant_id,))
        await conn.execute("DELETE FROM app.tenants WHERE tenant_id = %s", (tenant_id,))
```

pytest-asyncio was added in Task 1 (strict mode: async tests carry `pytestmark = pytest.mark.asyncio`, async fixtures use `@pytest_asyncio.fixture`).

Create `tests/e2e/test_migrations_and_persistence.py`:

```python
"""Revision 1 and the persistence adapter against the real dev database (OPS_LIVE=1).

Catches: a migration that is not idempotent, seed rows missing, a transition the table forbids still updating the
run, an event sequence with a gap or a forbidden (type, source) reaching the table, a duplicate job inserted twice,
two workers claiming one job, and a handle resolving at the wrong server.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from ops_core import persistence
from ops_core.jobs import JobType, Server, Tool
from ops_core.outcomes import EventRuleViolation, EventSource, EventType
from ops_core.states import IllegalTransition, Intent, Performer, RunState

pytestmark = pytest.mark.asyncio

ALPHA = "3ea79c95-914c-52cb-9d10-c4e19dda8ff7"
ALEX = "2fc05986-c7ec-544c-b628-fdb112bbf18a"


async def new_run(conn: persistence.Conn, tenant_id: UUID | None = None) -> tuple:
    """A QUEUED run in a fresh conversation; on a new random tenant unless a seeded one is given (mcp-read's corpus
    exists only for the seeded tenants)."""
    conv, msg, run = uuid4(), uuid4(), uuid4()
    tenant = tenant_id or uuid4()
    if tenant_id is None:
        await conn.execute("INSERT INTO app.tenants (tenant_id, name) VALUES (%s, %s)", (tenant, f"t-{tenant}"))
    await conn.execute(
        "INSERT INTO app.conversations (conversation_id, tenant_id, created_by) VALUES (%s, %s, %s)", (conv, tenant, ALEX)
    )
    await conn.execute(
        "INSERT INTO app.messages (message_id, tenant_id, conversation_id, kind, text, author)"
        " VALUES (%s, %s, %s, 'investigate', 'x', %s)",
        (msg, tenant, conv, ALEX),
    )
    end = datetime.now(UTC).replace(microsecond=0)
    await persistence.create_run(
        conn, run_id=run, tenant_id=tenant, conversation_id=conv, message_id=msg, requester=ALEX,
        intent=Intent.INVESTIGATE, asset_id="A17", start_at=end - timedelta(hours=24), end_at=end,
    )
    return tenant, conv, run


async def test_migrate_is_idempotent_and_seeds_are_present(migrated: None, app_conn: persistence.Conn):
    from scripts.skeleton import migrate

    assert migrate() == 0  # second run: no-op
    cur = await app_conn.execute("SELECT count(*) AS n FROM app.memberships WHERE tenant_id = %s", (ALPHA,))
    assert (await cur.fetchone())["n"] == 3  # alex, sam, lee
    cur = await app_conn.execute("SELECT role FROM app.memberships WHERE subject = %s", (ALEX,))
    assert [r["role"] for r in await cur.fetchall()] == ["requester"]


async def test_transition_follows_the_table_and_rolls_back_illegal_moves(app_conn: persistence.Conn):
    async with app_conn.transaction(force_rollback=True):  # nothing this test writes survives it
        _, _, run = await new_run(app_conn)
        assert await persistence.transition(app_conn, run_id=run, dst=RunState.RETRIEVING,
                                            performer=Performer.TRANSITION_RUN) == 2
        with pytest.raises(IllegalTransition):  # RETRIEVING → APPROVED is not a row
            await persistence.transition(app_conn, run_id=run, dst=RunState.APPROVED, performer=Performer.RECORD_DECISION)
        with pytest.raises(IllegalTransition):  # right pair, wrong performer
            await persistence.transition(app_conn, run_id=run, dst=RunState.DRAFTING, performer=Performer.CREATE_RUN)
        with pytest.raises(persistence.VersionConflict):
            await persistence.transition(app_conn, run_id=run, dst=RunState.DRAFTING,
                                         performer=Performer.TRANSITION_RUN, expected_version=1)
        row = await persistence.run_row(app_conn, run)
        assert (row["state"], row["state_version"]) == ("RETRIEVING", 2)
        cur = await app_conn.execute("SELECT seq, to_state, performer FROM app.run_state_history WHERE run_id = %s"
                                     " ORDER BY seq", (run,))
        assert [tuple(r.values()) for r in await cur.fetchall()] == [
            (1, "QUEUED", "create_run"), (2, "RETRIEVING", "transition_run")]


async def test_events_are_gap_free_and_rule_checked(app_conn: persistence.Conn):
    async with app_conn.transaction(force_rollback=True):
        tenant, conv, run = await new_run(app_conn)
        first = await persistence.append_event(app_conn, tenant_id=tenant, conversation_id=conv, run_id=run,
                                               type=EventType.RUN_ACCEPTED, source=EventSource.APPLICATION, payload={})
        second = await persistence.append_event(app_conn, tenant_id=tenant, conversation_id=conv, run_id=run,
                                                type=EventType.TOOL_STARTED, source=EventSource.APPLICATION,
                                                payload={"message": "search_procedures"})
        assert (first.sequence, second.sequence) == (1, 2)
        with pytest.raises(EventRuleViolation):  # the application may not assert a destination outcome
            await persistence.append_event(app_conn, tenant_id=tenant, conversation_id=conv, run_id=run,
                                           type=EventType.ACTION_CONFIRMED, source=EventSource.APPLICATION,
                                           payload={"status": "SUCCEEDED"})
        cur = await app_conn.execute("SELECT count(*) AS n FROM app.events WHERE run_id = %s", (run,))
        assert (await cur.fetchone())["n"] == 2


async def test_jobs_dedup_and_single_claim(app_conn: persistence.Conn):
    async with app_conn.transaction(force_rollback=True):
        _, _, run = await new_run(app_conn)  # create_run inserted investigate run:1
        assert await persistence.insert_job(app_conn, job_type=JobType.INVESTIGATE, run_id=run, revision=1) is None
        proposal = uuid4()
        assert await persistence.insert_job(app_conn, job_type=JobType.EXECUTE, run_id=run, proposal_id=proposal)
        assert await persistence.insert_job(app_conn, job_type=JobType.EXECUTE, run_id=run, proposal_id=proposal) is None
        claimed = await persistence.claim_job(app_conn, worker_name="w1")
        assert claimed is not None and claimed["claimed_by"] == "w1" and claimed["attempts"] == 1
        await persistence.finish_job(app_conn, claimed["id"])
        again = await persistence.claim_job(app_conn, worker_name="w2")
        assert again is not None and again["id"] != claimed["id"]  # the other job, not the finished one
        await persistence.finish_job(app_conn, again["id"])


async def test_handles_bind_to_one_server(app_conn: persistence.Conn):
    async with app_conn.transaction(force_rollback=True):
        tenant, _, run = await new_run(app_conn)
        cur = await app_conn.execute("SELECT id FROM app.jobs WHERE run_id = %s", (run,))
        job = (await cur.fetchone())["id"]
        handle = await persistence.mint_handle(app_conn, run_id=run, job_id=job, server=Server.READ, azp="ops-worker")
        inv = await persistence.resolve_handle(app_conn, handle=handle, server=Server.READ, azp="ops-worker",
                                               tool=Tool.SEARCH_PROCEDURES)
        assert inv.run_id == run and inv.tenant_id == tenant and inv.job_type is JobType.INVESTIGATE
        with pytest.raises(persistence.HandleRejected):
            await persistence.resolve_handle(app_conn, handle=handle, server=Server.WRITE, azp="ops-worker",
                                             tool=Tool.CREATE_INCIDENT)
        with pytest.raises(persistence.HandleRejected):
            await persistence.resolve_handle(app_conn, handle="nope", server=Server.READ, azp="ops-worker",
                                             tool=Tool.SEARCH_PROCEDURES)
```

Every writing test runs inside `async with app_conn.transaction(force_rollback=True)` (psycopg rolls the block back on exit even when it succeeds), so the live database keeps only the migration's rows between runs.

- [ ] **Step 7: Run migrate and the live tests against the dev stack**

Run: `uv run python scripts/skeleton.py migrate`
Expected: `MIGRATE: app and incident at head`; a second run prints the same (no-op).
Run: `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_migrations_and_persistence.py -q`
Expected: `5 passed`.
Run without the gate: `PYTHONUTF8=1 uv run python -m pytest tests/e2e -q`
Expected: `5 skipped`.

- [ ] **Step 8: Lint, full check, commit**

Run: `uv run ruff format migrations scripts/skeleton.py core/src/ops_core/persistence.py tests/plan_d tests/e2e && uv run ruff check --fix migrations scripts/skeleton.py core/src/ops_core/persistence.py tests/plan_d tests/e2e && PYTHONUTF8=1 uv run python scripts/check.py 2>&1 | tail -3`
Expected: clean; `CHECK: GREEN` (mypy covers `core/src`; `scripts/` and `migrations/` are ruff-checked).

```bash
git add migrations core/src/ops_core/persistence.py scripts/skeleton.py tests/plan_d/test_persistence_pure.py tests/e2e
git commit -m "feat(core): Alembic revision 1 for the app and incident databases, the shared persistence adapter and skeleton.py migrate"
```

---
### Task 3: One token verifier for every resource server (`ops_core.tokens`)

**Files:**
- Create: `core/src/ops_core/tokens.py`, `tests/plan_d/test_tokens.py`

**Interfaces:**
- Consumes: nothing from earlier tasks except `httpx2` (Task 1 dependency).
- Produces: `class TokenRejected(Exception)`; `@dataclass(frozen=True) class Principal(subject: str, azp: str, audiences: tuple[str, ...], expires_at: int, claims: Mapping[str, Any])`; `class TokenVerifier(*, issuer: str, audience: str, allowed_azp: frozenset[str], jwks_url: str, algorithms: tuple[str, ...] = ("RS256",))` with `async load_keys(fetch: Fetch | None = None) -> None`, `verify(token: str) -> Principal` (CPU only), `async verify_async(token: str) -> Principal` (refreshes keys once on an unknown `kid`), `property ready: bool`; `Fetch = Callable[[str], Awaitable[dict[str, Any]]]`; `bearer_token(authorization: str | None) -> str` (parses the header; raises `TokenRejected`); `class WorkloadTokenSource(*, token_url: str, client_id: str, client_secret: str, post: Post | None = None)` with `async token() -> str` (client-credentials grant, cached until 30 s before `expires_in`, refreshed on demand); `Post = Callable[[str, dict[str, str]], Awaitable[dict[str, Any]]]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/plan_d/test_tokens.py`:

```python
"""Token verification (SA:557-558, BUILD_SPEC §9): every resource server checks signature, exp, iss, aud ∋ its own
resource identifier and azp ∈ its allowed workload clients, and a rejection never echoes the token.

Catches: a token for another audience accepted (the exact confusion the two MCP audiences exist to prevent), a token
with no `aud` accepted (today's persona tokens before Task 1's mapper), an expired or foreign-issuer token, a token
signed by another key, a rotation that strands the server on stale keys, and an `azp` check that trusts the token
instead of the server's allowlist.
"""

import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from ops_core.tokens import Principal, TokenRejected, TokenVerifier, bearer_token

ISSUER = "http://localhost:18080/realms/ops-dev"
AUDIENCE = "http://mcp-read:8081/mcp"


def keypair(kid: str) -> tuple[bytes, dict[str, Any]]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key(), as_dict=True)
    jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return pem, jwk


PEM1, JWK1 = keypair("k1")
PEM2, JWK2 = keypair("k2")


def mint(pem: bytes = PEM1, kid: str = "k1", **over: Any) -> str:
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "sub": "2fc05986-c7ec-544c-b628-fdb112bbf18a",
        "aud": [AUDIENCE, "account"],
        "azp": "ops-worker",
        "exp": int(time.time()) + 300,
        "iat": int(time.time()),
        "typ": "Bearer",
    }
    claims.update(over)
    for key in [k for k, v in over.items() if v is None]:
        del claims[key]
    return jwt.encode(claims, pem, algorithm="RS256", headers={"kid": kid})


@pytest.fixture
def verifier() -> TokenVerifier:
    v = TokenVerifier(issuer=ISSUER, audience=AUDIENCE, allowed_azp=frozenset({"ops-worker"}), jwks_url="unused")
    v.install_keys({"keys": [JWK1]})
    return v


def test_valid_token_yields_the_principal(verifier: TokenVerifier):
    p = verifier.verify(mint())
    assert isinstance(p, Principal)
    assert p.subject == "2fc05986-c7ec-544c-b628-fdb112bbf18a" and p.azp == "ops-worker"
    assert AUDIENCE in p.audiences and p.expires_at > time.time()


def test_single_string_audience_is_accepted(verifier: TokenVerifier):
    assert verifier.verify(mint(aud=AUDIENCE)).audiences == (AUDIENCE,)


@pytest.mark.parametrize(
    "token",
    [
        mint(aud=["http://mcp-write:8082/mcp", "account"]),  # another audience (the write server's)
        mint(aud=None),  # no audience at all
        mint(azp="ops-mcp-write"),  # another workload presenting a token with the right audience
        mint(azp=None),
        mint(exp=int(time.time()) - 1),
        mint(iss="http://evil.example/realms/ops-dev"),
        mint(PEM2, "k1"),  # signed by a key that is not the published k1
        mint(PEM2, "k2"),  # unknown kid and no refresh possible in the sync path
        mint(sub=None),
    ],
)
def test_rejections(verifier: TokenVerifier, token: str):
    with pytest.raises(TokenRejected) as caught:
        verifier.verify(token)
    assert token not in str(caught.value) and token[:20] not in str(caught.value)


def test_garbage_and_wrong_algorithm_are_rejected(verifier: TokenVerifier):
    with pytest.raises(TokenRejected):
        verifier.verify("not-a-jwt")
    with pytest.raises(TokenRejected):  # HS256 with the public key as the secret: the classic confusion attack
        verifier.verify(jwt.encode({"iss": ISSUER, "aud": AUDIENCE, "azp": "ops-worker", "sub": "x",
                                    "exp": int(time.time()) + 60}, "secret", algorithm="HS256",
                                   headers={"kid": "k1"}))


@pytest.mark.asyncio
async def test_unknown_kid_refreshes_keys_once(verifier: TokenVerifier):
    calls: list[str] = []

    async def fetch(url: str) -> dict[str, Any]:
        calls.append(url)
        return {"keys": [JWK1, JWK2]}

    verifier.fetch = fetch
    assert (await verifier.verify_async(mint(PEM2, "k2"))).azp == "ops-worker"
    assert calls == ["unused"]
    with pytest.raises(TokenRejected):  # inside the cooldown: rejected without another fetch
        await verifier.verify_async(mint(PEM1, "k3"))
    assert len(calls) == 1
    verifier._refreshed_at = 0.0  # cooldown elapsed: one more refresh, then rejected
    with pytest.raises(TokenRejected):
        await verifier.verify_async(mint(PEM1, "k3"))
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_load_keys_uses_the_fetch_and_marks_ready():
    v = TokenVerifier(issuer=ISSUER, audience=AUDIENCE, allowed_azp=frozenset({"ops-worker"}), jwks_url="u")
    assert not v.ready
    with pytest.raises(TokenRejected):  # no keys yet: nothing can verify, nothing is accepted
        v.verify(mint())

    async def fetch(url: str) -> dict[str, Any]:
        return {"keys": [JWK1]}

    await v.load_keys(fetch)
    assert v.ready and v.verify(mint()).azp == "ops-worker"


@pytest.mark.asyncio
async def test_workload_token_source_caches_until_near_expiry():
    from ops_core.tokens import WorkloadTokenSource

    calls: list[dict[str, str]] = []

    async def post(url: str, form: dict[str, str]) -> dict[str, Any]:
        calls.append(form)
        return {"access_token": f"t{len(calls)}", "expires_in": 300, "token_type": "Bearer"}

    src = WorkloadTokenSource(token_url="u", client_id="ops-worker", client_secret="s", post=post)
    assert await src.token() == "t1" and await src.token() == "t1"  # cached
    assert calls[0]["grant_type"] == "client_credentials" and calls[0]["client_id"] == "ops-worker"
    src.expires_at = time.time() + 10  # inside the 30 s refresh window
    assert await src.token() == "t2"


def test_bearer_header_parsing():
    assert bearer_token("Bearer abc.def.ghi") == "abc.def.ghi"
    for bad in (None, "", "Basic abc", "Bearer", "Bearer  ", "bearer abc"):
        with pytest.raises(TokenRejected):
            bearer_token(bad)
```

Run: `PYTHONUTF8=1 uv run python -m pytest tests/plan_d/test_tokens.py -q`
Expected: an `ImportError` for `ops_core.tokens` (the module does not exist yet).

- [ ] **Step 2: The verifier**

Create `core/src/ops_core/tokens.py`:

```python
"""Bearer-token verification shared by every resource server (api, mcp-read, mcp-write, incident-sim).

One class, configured per server with its issuer, its own audience and the workload clients it accepts as `azp`, so
every server applies SA:557's checks the same way and a token minted for one audience is refused by every other
(SA:558). Keys come from the realm's JWKS, fetched asynchronously at startup (SA:201: no synchronous I/O on the event
loop) and refreshed at most once per verification on an unknown `kid` (key rotation). PyJWT checks the signature,
`exp`, `iss` and `aud`; `azp` is checked here because PyJWT has no option for it. Algorithms are pinned to RS256 so a
token signed with the public key as an HMAC secret is refused.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx2
import jwt
from jwt import PyJWKSet
from jwt.exceptions import InvalidTokenError, PyJWKClientError, PyJWKSetError

Fetch = Callable[[str], Awaitable[dict[str, Any]]]
REFRESH_COOLDOWN = 60.0  # seconds between JWKS refreshes triggered by an unknown kid


class TokenRejected(Exception):
    """The token is not acceptable here. The message says why in general terms and never contains the token."""


@dataclass(frozen=True)
class Principal:
    subject: str
    azp: str
    audiences: tuple[str, ...]
    expires_at: int
    claims: Mapping[str, Any]


def bearer_token(authorization: str | None) -> str:
    """Extract the token from an `Authorization: Bearer <token>` header (case-sensitive scheme, one token)."""
    if not authorization:
        raise TokenRejected("missing bearer token")
    scheme, _, token = authorization.partition(" ")
    if scheme != "Bearer" or not token.strip() or " " in token.strip():
        raise TokenRejected("malformed authorization header")
    return token.strip()


async def fetch_jwks(url: str) -> dict[str, Any]:
    async with httpx2.AsyncClient(timeout=10.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data


class TokenVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        allowed_azp: frozenset[str],
        jwks_url: str,
        algorithms: tuple[str, ...] = ("RS256",),
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._allowed_azp = allowed_azp
        self._jwks_url = jwks_url
        self._algorithms = list(algorithms)
        self._keys: PyJWKSet | None = None
        self._refreshed_at = 0.0
        self.fetch: Fetch = fetch_jwks  # replaceable so tests never open a socket

    @property
    def ready(self) -> bool:
        return self._keys is not None

    def install_keys(self, jwks: dict[str, Any]) -> None:
        try:
            self._keys = PyJWKSet.from_dict(jwks)
        except PyJWKSetError as exc:
            raise TokenRejected("JWKS document is unusable") from exc

    async def load_keys(self, fetch: Fetch | None = None) -> None:
        self.install_keys(await (fetch or self.fetch)(self._jwks_url))
        self._refreshed_at = time.time()

    def verify(self, token: str) -> Principal:
        if self._keys is None:
            raise TokenRejected("signing keys are not loaded")
        try:
            kid = jwt.get_unverified_header(token).get("kid")
            key = self._keys[kid] if isinstance(kid, str) else None
        except (InvalidTokenError, KeyError, PyJWKClientError, PyJWKSetError):
            key = None
        if key is None:
            raise TokenRejected("unknown signing key")
        try:
            claims = jwt.decode(
                token,
                key.key,
                algorithms=self._algorithms,
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except InvalidTokenError as exc:
            # PyJWT's message names the failed check (expired, audience, issuer, signature) and never the token.
            raise TokenRejected(f"token rejected: {exc.__class__.__name__}") from exc
        azp = claims.get("azp")
        if not isinstance(azp, str) or azp not in self._allowed_azp:
            raise TokenRejected("token was issued to a client this server does not accept")
        aud = claims["aud"]
        audiences = (aud,) if isinstance(aud, str) else tuple(aud)
        return Principal(subject=claims["sub"], azp=azp, audiences=audiences, expires_at=int(claims["exp"]),
                         claims=claims)

    async def verify_async(self, token: str) -> Principal:
        """`verify`, refreshing the JWKS once when the kid is unknown (rotation), then giving up."""
        try:
            return self.verify(token)
        except TokenRejected as exc:
            if str(exc) != "unknown signing key" or time.time() - self._refreshed_at < REFRESH_COOLDOWN:
                raise  # a flood of unknown kids must not become a flood of JWKS fetches
        await self.load_keys()
        return self.verify(token)


Post = Callable[[str, dict[str, str]], Awaitable[dict[str, Any]]]


async def post_form(url: str, form: dict[str, str]) -> dict[str, Any]:
    async with httpx2.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, data=form)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data


class WorkloadTokenSource:
    """Client-credentials tokens for a workload (the worker, mcp-write), cached and refreshed 30 s before expiry.

    The secret is held in memory only; it is sent as a form field to the realm's token endpoint and nowhere else.
    """

    def __init__(self, *, token_url: str, client_id: str, client_secret: str, post: Post | None = None) -> None:
        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._post = post or post_form
        self._token: str | None = None
        self.expires_at = 0.0

    async def token(self) -> str:
        if self._token is None or time.time() >= self.expires_at - 30:
            data = await self._post(
                self._token_url,
                {"grant_type": "client_credentials", "client_id": self._client_id, "client_secret": self._client_secret},
            )
            self._token = str(data["access_token"])
            self.expires_at = time.time() + float(data.get("expires_in", 60))
        return self._token
```

(Add `import time` to the module's imports.)

- [ ] **Step 3: Run the tests**

Run: `PYTHONUTF8=1 uv run python -m pytest tests/plan_d/test_tokens.py -q`
Expected: `16 passed` (9 parametrized rejections + 7). If `PyJWKSet.__getitem__` raises a different exception type for an unknown kid in the locked PyJWT version, catch that type too — the test `mint(PEM2, "k2")` pins the behaviour, not the exception.

- [ ] **Step 4: Prove the verifier against the real realm (live, no new process)**

Append to `tests/e2e/test_migrations_and_persistence.py`? No — keep concerns separate: create `tests/e2e/test_tokens_live.py`:

```python
"""The verifier against Keycloak's real JWKS and real tokens (OPS_LIVE=1): the worker token passes at the read
audience and fails at the write server's allowlist; the persona token passes only at the API audience."""

import pytest
from ops_core import settings
from ops_core.tokens import TokenRejected, TokenVerifier
from tests.plan_b.live import kc

pytestmark = pytest.mark.asyncio


async def test_real_tokens_against_real_jwks(env: dict[str, str], secret) -> None:
    keycloak = settings.keycloak()
    urls = settings.urls()
    worker = kc.token_client_credentials(keycloak.base_url, "ops-worker", secret("kc_client_secret_ops_worker"))
    alex = kc.token_password(keycloak.base_url, "ops-dev-direct", "alex", secret("kc_persona_alex_password"))
    worker_token, alex_token = worker["access_token"], alex["access_token"]
    read = TokenVerifier(issuer=keycloak.issuer, audience=urls.mcp_read_resource,
                         allowed_azp=frozenset({"ops-worker"}), jwks_url=keycloak.jwks_url)
    await read.load_keys()
    # Pytest prints the operands of a failed assert, so the token never appears inside one (Plan B's lesson).
    principal = await read.verify_async(worker_token)
    assert principal.azp == "ops-worker"
    with pytest.raises(TokenRejected):  # persona token at the MCP server: wrong audience
        await read.verify_async(alex_token)
    api = TokenVerifier(issuer=keycloak.issuer, audience="ops-api", allowed_azp=frozenset({"ops-dev-direct"}),
                        jwks_url=keycloak.jwks_url)
    await api.load_keys()
    persona = await api.verify_async(alex_token)
    assert persona.claims["preferred_username"] == "alex"
    with pytest.raises(TokenRejected):  # worker token at the API: wrong audience and wrong azp
        await api.verify_async(worker_token)
```

Run: `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_tokens_live.py -q`
Expected: `1 passed`.

- [ ] **Step 5: Full check and commit**

Run: `uv run ruff format core/src/ops_core/tokens.py tests/plan_d/test_tokens.py tests/e2e/test_tokens_live.py && uv run ruff check --fix core/src/ops_core/tokens.py tests/plan_d/test_tokens.py tests/e2e/test_tokens_live.py && PYTHONUTF8=1 uv run python scripts/check.py 2>&1 | tail -3`
Expected: `CHECK: GREEN`.

```bash
git add core/src/ops_core/tokens.py tests/plan_d/test_tokens.py tests/e2e/test_tokens_live.py
git commit -m "feat(core): one JWKS-backed token verifier (iss, aud, azp, exp, signature) for every resource server"
```

---
### Task 4: incident-sim — the destination with its atomic `action_key`

**Files:**
- Create: `incident-sim/src/ops_incident_sim/keys.py`, `incident-sim/src/ops_incident_sim/app.py`, `incident-sim/src/ops_incident_sim/__main__.py`, `tests/plan_d/test_incident_sim.py`, `tests/e2e/test_incident_sim_live.py`
- Modify: `incident-sim/README.md` (one "## Runs" section: port, endpoints, role)

**Interfaces:**
- Consumes: `ops_core.settings.incident_postgres()`, `keycloak()`, `env_int`; `ops_core.tokens.TokenVerifier`, `bearer_token`, `TokenRejected`; `ops_core.canonical.parse_json_strict`, `canonical_sha256`; `ops_core.contracts.SafeError`, `ErrorCode`; `ops_core.outcomes.DestinationState`.
- Produces: HTTP contract (ruling 9) — `POST /internal/incidents` body `{"action_id", "payload_sha256", "payload_canonical"}` (the canonical JSON as one string; hashed as received) → 200 `{"state": "COMMITTED", "action_id", "payload_sha256", "receipt": {"receipt_id", "incident_id", "committed_at"}}` or 409 `{"state": "CONFLICT", "action_id", "payload_sha256": <stored>}` or 200 `{"state": "ABORTED"|"REJECTED", ..., "tombstone": {"action_id", "state", "payload_sha256", "reason", "decided_at"}}`; 422 `SafeError(INVALID_INPUT)` when the recomputed hash differs or the body is malformed; 401 `SafeError(UNAUTHENTICATED)`; `GET /internal/actions/{action_id}` → the same document or 404 `SafeError(NOT_FOUND)`; `GET /health/live`, `/health/ready`. Python: `keys.commit(conn, *, action_id, payload_sha256, payload) -> KeyRow` (inside the caller's unit of work); `keys.lookup(conn, action_id) -> KeyRow | None`; `keys.document(row, *, presented_sha256) -> tuple[int, dict]` (pure); `app.create_app(verifier, *, store=None, connect=None) -> FastAPI`; `serve_app(app, port)` in `__main__`.

- [ ] **Step 1: Write the failing tests**

Create `tests/plan_d/test_incident_sim.py`:

```python
"""incident-sim's contract without a database (AM-13 §4 destination rules, BUILD_SPEC §14): hash recomputed over the
received bytes, same key + same hash → the existing receipt, same key + different hash → CONFLICT (never a second
incident), an unauthenticated call → a plain safe error with no action_id, and the document shapes T10 extends.

Catches: trusting the caller's hash (SA:268), a conflict that creates a second incident, a 401 body that leaks the
action id (SA:357), and a tombstone presented as a receipt.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from ops_core.canonical import canonical_json, canonical_sha256, sha256_hex
from ops_core.tokens import Principal, TokenRejected
from ops_incident_sim import keys
from ops_incident_sim.app import create_app

ACTION = UUID(int=7)
PAYLOAD = {"title": "Synthetic incident", "asset_id": "A17", "revision": 1}
SHA = canonical_sha256(PAYLOAD)
AT = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def row(**over: Any) -> keys.KeyRow:
    base: dict[str, Any] = {"action_id": ACTION, "payload_sha256": SHA, "state": "COMMITTED", "incident_id": "INC-000001",
                            "reason": None, "receipt_id": UUID(int=9), "decided_at": AT}
    base.update(over)
    return keys.KeyRow(**base)


def test_document_shapes():
    status, doc = keys.document(row(), presented_sha256=SHA)
    assert status == 200 and doc["state"] == "COMMITTED" and doc["receipt"] == {
        "receipt_id": str(UUID(int=9)), "incident_id": "INC-000001", "committed_at": "2026-10-08T12:00:00Z"}
    status, doc = keys.document(row(), presented_sha256="0" * 64)
    assert status == 409 and doc == {"state": "CONFLICT", "action_id": str(ACTION), "payload_sha256": SHA}
    status, doc = keys.document(row(state="REJECTED", incident_id=None, reason="policy"), presented_sha256=SHA)
    assert status == 200 and "receipt" not in doc and doc["tombstone"]["state"] == "REJECTED"
    assert doc["tombstone"]["reason"] == "policy" and doc["tombstone"]["decided_at"] == "2026-10-08T12:00:00Z"


class StubVerifier:
    @property
    def ready(self) -> bool:
        return True

    async def load_keys(self) -> None:
        return None

    async def verify_async(self, token: str) -> Principal:
        if token != "good":
            raise TokenRejected("nope")
        return Principal(subject="sa", azp="ops-mcp-write", audiences=("incident-sim",), expires_at=2**31, claims={})


class FakeStore:
    """The key table in memory, with the same first-writer-wins contract as keys.commit."""

    def __init__(self) -> None:
        self.rows: dict[UUID, keys.KeyRow] = {}
        self.commits: list[tuple[UUID, str]] = []

    async def commit(self, action_id: UUID, payload_sha256: str, payload: dict[str, Any]) -> keys.KeyRow:
        self.commits.append((action_id, payload_sha256))
        if action_id not in self.rows:
            self.rows[action_id] = row(action_id=action_id, payload_sha256=payload_sha256,
                                       incident_id=f"INC-{len(self.rows) + 1:06d}", receipt_id=uuid4())
        return self.rows[action_id]

    async def lookup(self, action_id: UUID) -> keys.KeyRow | None:
        return self.rows.get(action_id)


@pytest.fixture
def client() -> Iterator[tuple[TestClient, FakeStore]]:
    store = FakeStore()
    app = create_app(StubVerifier(), store=store)
    with TestClient(app) as c:  # the context manager runs the lifespan, which installs the store
        yield c, store


def body_for(payload: dict[str, Any], *, sha: str | None = None, action: UUID = ACTION) -> dict[str, Any]:
    canonical = canonical_json(payload).decode("utf-8")
    return {"action_id": str(action), "payload_sha256": sha or sha256_hex(canonical.encode("utf-8")),
            "payload_canonical": canonical}


def post(c: TestClient, body: dict[str, Any], token: str = "good"):
    return c.post("/internal/incidents", content=canonical_json(body), headers={"Authorization": f"Bearer {token}",
                                                                                 "Content-Type": "application/json"})


def test_commit_then_replay_returns_the_same_receipt(client):
    c, store = client
    first = post(c, body_for(PAYLOAD))
    assert first.status_code == 200 and first.json()["state"] == "COMMITTED"
    again = post(c, body_for(PAYLOAD))
    assert again.json() == first.json() and len(store.rows) == 1


def test_different_hash_under_an_existing_key_is_a_conflict_not_a_second_incident(client):
    c, store = client
    post(c, body_for(PAYLOAD))
    r = post(c, body_for({**PAYLOAD, "title": "Changed"}))
    assert r.status_code == 409 and r.json() == {"state": "CONFLICT", "action_id": str(ACTION), "payload_sha256": SHA}
    assert len(store.rows) == 1


def test_presented_hash_must_match_the_received_bytes(client):
    c, store = client
    r = post(c, body_for(PAYLOAD, sha="0" * 64))
    assert r.status_code == 422 and r.json()["code"] == "INVALID_INPUT"
    # The hash is over the bytes as received (SA:268): a re-serialisation that changes one byte is a mismatch.
    spaced = {"action_id": str(ACTION), "payload_sha256": SHA, "payload_canonical": '{"asset_id": "A17", "revision": 1, "title": "Synthetic incident"}'}
    assert post(c, spaced).status_code == 422
    assert store.commits == []  # refused before the key table is touched


def test_malformed_bodies_are_422(client):
    c, _ = client
    for body in (b"{", b'{"action_id": "x"}', b'{"action_id": "%s", "payload_sha256": "%s"}' % (str(ACTION).encode(),
                                                                                                  SHA.encode()),
                 b'{"action_id": "%s", "payload_sha256": "%s", "payload_canonical": "[1]"}' % (str(ACTION).encode(),
                                                                                                  SHA.encode())):
        r = c.post("/internal/incidents", content=body, headers={"Authorization": "Bearer good",
                                                                 "Content-Type": "application/json"})
        assert r.status_code == 422, body
    dup = b'{"action_id": "%s", "action_id": "%s", "payload_sha256": "%s", "payload_canonical": "{}"}' % (
        str(ACTION).encode(), str(ACTION).encode(), SHA.encode())
    assert c.post("/internal/incidents", content=dup, headers={"Authorization": "Bearer good"}).status_code == 422


def test_unauthenticated_calls_get_a_plain_safe_error(client):
    c, store = client
    r = post(c, body_for(PAYLOAD), token="bad")
    assert r.status_code == 401 and r.json()["code"] == "UNAUTHENTICATED"
    assert str(ACTION) not in r.text and store.commits == []
    assert c.get(f"/internal/actions/{ACTION}").status_code == 401


def test_lookup(client):
    c, _ = client
    assert c.get(f"/internal/actions/{ACTION}", headers={"Authorization": "Bearer good"}).status_code == 404
    post(c, body_for(PAYLOAD))
    r = c.get(f"/internal/actions/{ACTION}", headers={"Authorization": "Bearer good"})
    assert r.status_code == 200 and r.json()["state"] == "COMMITTED"


def test_health(client):
    c, _ = client
    assert c.get("/health/live").json() == {"status": "live"}
    assert c.get("/health/ready").status_code == 200
```

Run: `PYTHONUTF8=1 uv run python -m pytest tests/plan_d/test_incident_sim.py -q`
Expected: an `ImportError` for `ops_incident_sim.keys` (the module does not exist yet). (`fastapi.testclient.TestClient` is Starlette's client, which runs on httpx2 — measured in the spike — so no extra dependency is needed.)

- [ ] **Step 2: The key table module**

Create `incident-sim/src/ops_incident_sim/keys.py`:

```python
"""The destination's truth: one `action_key` row per action, written once (AM-13 §4, SA:259-269).

`commit` is `INSERT … ON CONFLICT (action_id) DO NOTHING` followed by a read of whatever row exists, at READ COMMITTED,
which is the whole idempotency mechanism: a retry with the same key and hash gets the same receipt; a different hash
under an existing key is a CONFLICT the caller must escalate, and never a second incident. The destination recomputes
nothing here — app.py already proved the presented hash over the received bytes — but it stores only its own view.
TODO(T10): abort (`ABORTED`), `REJECTED` via the fault factory, and the detective check against grant hashes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from psycopg.rows import DictRow
from psycopg.types.json import Jsonb

from ops_core.persistence import Conn


@dataclass(frozen=True)
class KeyRow:
    action_id: UUID
    payload_sha256: str
    state: str
    incident_id: str | None
    reason: str | None
    receipt_id: UUID | None
    decided_at: datetime


def _row(record: DictRow) -> KeyRow:
    return KeyRow(
        action_id=record["action_id"],
        payload_sha256=record["payload_sha256"],
        state=record["state"],
        incident_id=record["incident_id"],
        reason=record["reason"],
        receipt_id=record["receipt_id"],
        decided_at=record["decided_at"],
    )


async def commit(conn: Conn, *, action_id: UUID, payload_sha256: str, payload: dict[str, Any]) -> KeyRow:
    """Insert the key and its incident, or return the existing key untouched. The caller holds the unit of work
    (`Session.unit()`), so the key and the incident row commit together or not at all."""
    cur = await conn.execute(
        "INSERT INTO incident.action_key (action_id, payload_sha256, state, incident_id, receipt_id)"
        " VALUES (%s, %s, 'COMMITTED', 'INC-' || lpad(nextval('incident.incident_seq')::text, 6, '0'), %s)"
        " ON CONFLICT (action_id) DO NOTHING RETURNING *",
        (action_id, payload_sha256, uuid4()),
    )
    inserted = await cur.fetchone()
    if inserted is not None:
        # The incident row exists only when its key commits in this same transaction (SA:264).
        await conn.execute(
            "INSERT INTO incident.incidents (incident_id, action_id, payload) VALUES (%s, %s, %s)",
            (inserted["incident_id"], action_id, Jsonb(payload)),
        )
        return _row(inserted)
    existing = await lookup(conn, action_id)
    assert existing is not None  # the conflict proved the row exists and rows are never deleted (SA:265)
    return existing


async def lookup(conn: Conn, action_id: UUID) -> KeyRow | None:
    cur = await conn.execute("SELECT * FROM incident.action_key WHERE action_id = %s", (action_id,))
    record = await cur.fetchone()
    return None if record is None else _row(record)


def _stamp(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def document(row: KeyRow, *, presented_sha256: str) -> tuple[int, dict[str, Any]]:
    """The HTTP document for a key row as seen by a caller presenting `presented_sha256` (ruling 9 of Plan D)."""
    if row.state == "COMMITTED" and row.payload_sha256 != presented_sha256:
        return 409, {"state": "CONFLICT", "action_id": str(row.action_id), "payload_sha256": row.payload_sha256}
    doc: dict[str, Any] = {"state": row.state, "action_id": str(row.action_id), "payload_sha256": row.payload_sha256}
    if row.state == "COMMITTED":
        doc["receipt"] = {"receipt_id": str(row.receipt_id), "incident_id": row.incident_id,
                          "committed_at": _stamp(row.decided_at)}
    else:
        doc["tombstone"] = {"action_id": str(row.action_id), "state": row.state, "payload_sha256": row.payload_sha256,
                            "reason": row.reason or row.state.lower(), "decided_at": _stamp(row.decided_at)}
    return 200, doc
```

(`from datetime import UTC, datetime` — add `UTC` to the import.)

- [ ] **Step 3: The application**

Create `incident-sim/src/ops_incident_sim/app.py`:

```python
"""incident-sim: the synthetic destination (BUILD_SPEC §14). Trusts only mcp-write's workload token (aud `incident-sim`,
azp `ops-mcp-write`, SA:262/270); recomputes the hash over the received bytes before touching the key table (SA:268);
answers with the key's own view (keys.document). A 401 carries a plain safe error and never an action id (SA:357)."""

# No `from __future__ import annotations`: FastAPI resolves dependency annotations at import time (Plan D review).
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any, Protocol
from uuid import UUID, uuid4

import psycopg
from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ops_core import persistence, settings
from ops_core.canonical import CanonicalizationError, parse_json_strict, sha256_hex
from ops_core.contracts import ErrorCode, SafeError, Sha256
from ops_core.tokens import Principal, TokenRejected, TokenVerifier, bearer_token
from ops_incident_sim import keys


class Verifier(Protocol):
    @property
    def ready(self) -> bool: ...

    async def load_keys(self) -> None: ...

    async def verify_async(self, token: str) -> Principal: ...


class Store(Protocol):
    async def commit(self, action_id: UUID, payload_sha256: str, payload: dict[str, Any]) -> keys.KeyRow: ...

    async def lookup(self, action_id: UUID) -> keys.KeyRow | None: ...


class DbStore:
    def __init__(self, conn: persistence.Conn) -> None:
        self.session = persistence.Session(conn)  # ruling 24: one unit of work at a time, each a real transaction

    async def commit(self, action_id: UUID, payload_sha256: str, payload: dict[str, Any]) -> keys.KeyRow:
        async with self.session.unit() as conn:
            return await keys.commit(conn, action_id=action_id, payload_sha256=payload_sha256, payload=payload)

    async def lookup(self, action_id: UUID) -> keys.KeyRow | None:
        async with self.session.unit() as conn:
            return await keys.lookup(conn, action_id)


class IncidentRequest(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    action_id: UUID
    payload_sha256: Sha256
    payload_canonical: str = Field(min_length=2)


def safe_error(status: int, code: ErrorCode, message: str) -> JSONResponse:
    body = SafeError(code=code, message=message, retryable=status == 503, request_id=uuid4())
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


class Unauthenticated(Exception):
    pass


def create_app(verifier: Verifier, *, store: Store | None = None,
               connect: Callable[[], Awaitable[persistence.Conn]] | None = None) -> FastAPI:
    """Wire the app; `store` injects an in-memory table for unit tests, `connect` the real database at runtime."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if store is not None:
            app.state.store = store
        else:
            assert connect is not None
            app.state.store = DbStore(await connect())
        if not verifier.ready:
            await verifier.load_keys()
        yield

    app = FastAPI(title="incident-sim", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    async def caller(request: Request) -> Principal:
        try:
            return await verifier.verify_async(bearer_token(request.headers.get("authorization")))
        except TokenRejected as exc:
            raise Unauthenticated from exc

    @app.exception_handler(Unauthenticated)
    async def _unauthenticated(_: Request, __: Unauthenticated) -> Response:
        return safe_error(401, ErrorCode.UNAUTHENTICATED, "a valid workload token is required")

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "live"}

    @app.get("/health/ready")
    async def ready(request: Request) -> Response:
        st: Store = request.app.state.store
        if isinstance(st, DbStore):
            try:
                await st.session.read("SELECT 1", ())
            except (psycopg.Error, OSError):  # readiness reports a database failure as not ready
                return safe_error(503, ErrorCode.UNAVAILABLE, "database not reachable")
        return JSONResponse({"status": "ready"})

    @app.post("/internal/incidents")
    async def post_incident(request: Request, _: Annotated[Principal, Depends(caller)]) -> Response:
        raw = await request.body()
        try:
            text = raw.decode("utf-8")
            parse_json_strict(text)  # duplicate keys, floats and NaN in the envelope are refused here
            body = IncidentRequest.model_validate_json(text)  # JSON mode: strict models parse UUID text
            payload = parse_json_strict(body.payload_canonical)
        except (UnicodeDecodeError, CanonicalizationError, ValidationError, ValueError):
            return safe_error(422, ErrorCode.INVALID_INPUT, "body is not a well-formed incident request")
        if not isinstance(payload, dict) or not payload:
            return safe_error(422, ErrorCode.INVALID_INPUT, "payload_canonical is not a JSON object")
        # The hash is recomputed over the bytes exactly as received (SA:268), never over a re-serialisation.
        if sha256_hex(body.payload_canonical.encode("utf-8")) != body.payload_sha256:
            return safe_error(422, ErrorCode.INVALID_INPUT, "payload hash does not match the received payload")
        st: Store = request.app.state.store
        row = await st.commit(body.action_id, body.payload_sha256, payload)
        status, doc = keys.document(row, presented_sha256=body.payload_sha256)
        return JSONResponse(status_code=status, content=doc)

    @app.get("/internal/actions/{action_id}")
    async def get_action(action_id: UUID, request: Request, _: Annotated[Principal, Depends(caller)]) -> Response:
        st: Store = request.app.state.store
        row = await st.lookup(action_id)
        if row is None:
            return safe_error(404, ErrorCode.NOT_FOUND, "no such action")
        status, doc = keys.document(row, presented_sha256=row.payload_sha256)
        return JSONResponse(status_code=status, content=doc)

    return app


def production_app() -> FastAPI:
    kc = settings.keycloak()
    verifier = TokenVerifier(issuer=kc.issuer, audience="incident-sim", allowed_azp=frozenset({"ops-mcp-write"}),
                             jwks_url=kc.jwks_url)
    return create_app(verifier, connect=lambda: persistence.connect(settings.incident_postgres()))
```

Create `incident-sim/src/ops_incident_sim/__main__.py`:

```python
"""`python -m ops_incident_sim`: serve on 127.0.0.1:OPS_INCIDENT_SIM_PORT (default 8090)."""

import asyncio
import sys

import uvicorn
from starlette.types import ASGIApp

from ops_core.settings import env_int
from ops_incident_sim.app import production_app


def serve_app(app: ASGIApp, port: int) -> None:
    """Serve with uvicorn programmatically on a selector loop (ruling 23: `uvicorn.run` picks the Proactor loop on
    Windows and psycopg async refuses it)."""
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    if sys.platform == "win32":
        asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(server.serve())


if __name__ == "__main__":
    serve_app(production_app(), env_int("OPS_INCIDENT_SIM_PORT", 8090))
```

- [ ] **Step 4: Run the unit tests**

Run: `PYTHONUTF8=1 uv run python -m pytest tests/plan_d/test_incident_sim.py -q`
Expected: `8 passed`.

- [ ] **Step 5: Live test against the incident database (role `incident`)**

Create `tests/e2e/test_incident_sim_live.py`:

```python
"""keys.commit against the real `incident` database as role `incident` (OPS_LIVE=1): first-writer-wins, replay returns
the same receipt, and the destination's role cannot read the application schema (separate credentials, BUILD_SPEC §14)."""

from uuid import uuid4

import psycopg
import pytest
from ops_core import persistence, settings
from ops_core.canonical import canonical_sha256
from ops_incident_sim import keys

pytestmark = pytest.mark.asyncio


async def test_commit_replay_conflict_and_isolation(migrated: None) -> None:
    conn = await persistence.connect(settings.incident_postgres())
    try:
        async with conn.transaction(force_rollback=True):  # the live key table keeps nothing from this test
            action = uuid4()
            payload = {"title": "live", "n": 1}
            first = await keys.commit(conn, action_id=action, payload_sha256=canonical_sha256(payload), payload=payload)
            again = await keys.commit(conn, action_id=action, payload_sha256=canonical_sha256(payload), payload=payload)
            assert first == again and first.incident_id.startswith("INC-") and first.state == "COMMITTED"
            other = await keys.commit(conn, action_id=action, payload_sha256="0" * 64, payload={"x": 1})
            assert other == first  # the key keeps its first hash; document() turns this into CONFLICT
            assert keys.document(other, presented_sha256="0" * 64)[0] == 409
            cur = await conn.execute("SELECT count(*) AS n FROM incident.incidents WHERE action_id = %s", (action,))
            assert (await cur.fetchone())["n"] == 1
        # The application schema is not even visible from the destination's database (separate credentials).
        with pytest.raises((psycopg.errors.InsufficientPrivilege, psycopg.errors.UndefinedTable)):
            await conn.execute("SELECT 1 FROM app.runs")
    finally:
        await conn.close()
```

Run: `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_incident_sim_live.py -q`
Expected: `1 passed`.

- [ ] **Step 6: README, full check, commit**

Append to `incident-sim/README.md`:

```markdown
## Runs (T08)

`python -m ops_incident_sim` on 127.0.0.1:8090 (`OPS_INCIDENT_SIM_PORT`), database `incident` as role `incident`
(`postgres_incident_password`). `POST /internal/incidents` and `GET /internal/actions/{id}`; abort and faults arrive
with T10.
```

Run: `uv run ruff format incident-sim tests/plan_d/test_incident_sim.py tests/e2e/test_incident_sim_live.py && uv run ruff check --fix incident-sim tests/plan_d/test_incident_sim.py tests/e2e/test_incident_sim_live.py && PYTHONUTF8=1 uv run python scripts/check.py 2>&1 | tail -3`
Expected: `CHECK: GREEN`.

```bash
git add incident-sim tests/plan_d/test_incident_sim.py tests/e2e/test_incident_sim_live.py
git commit -m "feat(incident-sim): atomic action_key destination with hash recomputation and conflict documents"
```

---
### Task 5: mcp-read — the authenticated read server with one tool, `search_procedures`

**Files:**
- Create: `mcp-read/src/ops_mcp_read/procedures.py`, `mcp-read/src/ops_mcp_read/server.py`, `mcp-read/src/ops_mcp_read/__main__.py`, `tests/plan_d/test_mcp_read.py`, `tests/e2e/test_mcp_read_live.py`
- Modify: `mcp-read/README.md` ("## Runs (T08)" section)

**Interfaces:**
- Consumes: `ops_core.settings` (`keycloak()`, `urls()`, `app_postgres()`, `fixtures_dir()`, `env_int`); `ops_core.tokens.TokenVerifier`, `TokenRejected`, `Principal`; `ops_core.persistence.connect`, `resolve_handle`, `HandleRejected`, `Conn`; `ops_core.jobs.Server`, `Tool`.
- Produces: `ops_mcp_read.procedures` — `section_bodies(markdown) -> dict[str, str]` (the same slicing as `scripts/gen_fixture_meta.py`), `@dataclass(frozen=True) Section(evidence_id, document_id, version, section, content_sha256, text, effective_from)`, `Hit(section, score)`, `Corpus(sections, corpus_version)` with `classmethod load(fixtures_dir: Path, tenant_slug: str) -> Corpus` and `search(query: str, limit: int) -> list[Hit]`, `load_corpora(fixtures_dir: Path) -> dict[UUID, Corpus]` (keyed by tenant UUID from `meta.json`). `ops_mcp_read.server` — `class ToolResult(TypedDict)` (the tool-result envelope: `tool_name, request_id, status, observed_at, truncated, data, error`), `envelope(tool_name, *, data=None, error=None) -> ToolResult`, `tool_error(code, message) -> dict[str, Any]`, `search_response(corpora, *, tenant_id, query, limit, now) -> ToolResult` (pure), `class McpVerifier` (the SDK's `TokenVerifier` protocol over `ops_core.tokens.TokenVerifier`), `strict_tool(fn) -> Tool`, `class State(session: Session | None, corpora, verifier)`, `build_server(state, *, issuer, resource_url) -> MCPServer`, `build_app(server, state) -> Starlette`, `production_app() -> Starlette`. The tool-result envelope shape is shared with mcp-write (Task 6) by convention, not by import.

- [ ] **Step 1: Write the failing tests**

Create `tests/plan_d/test_mcp_read.py`:

```python
"""mcp-read without a network (AM-15 read tools, AM-80 tool-result contract, R131 in miniature).

Catches: the per-section hash the tool cites drifting from meta.json (an evidence_ref the proposal cannot prove), a
superseded or draft document served as evidence, beta evidence visible to alpha, a non-deterministic ranking (the same
query giving a different first citation on retry), a tool schema that drifts from schemas/tools/, an extra argument
such as tenant_id silently ignored (SA:350), and an envelope that does not validate against tool-result.schema.json.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from mcp import Client
from ops_core.tokens import Principal, TokenRejected
from ops_mcp_read import procedures, server

FIXTURES = Path("data/handoff-fixtures")
ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")
BETA = UUID("5ab45c2c-1e12-5a0c-a2b9-66cd2ff05201")
NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
TOOL_RESULT = Draft202012Validator(json.loads(Path("schemas/tool-result.schema.json").read_text(encoding="utf-8")),
                                   format_checker=FormatChecker())
INPUT = json.loads(Path("schemas/tools/search_procedures.input.schema.json").read_text(encoding="utf-8"))


def test_section_bodies_hash_exactly_as_meta_json_says():
    meta = json.loads((FIXTURES / "meta.json").read_text(encoding="utf-8"))
    catalog = json.loads((FIXTURES / "catalog.json").read_text(encoding="utf-8"))
    expected = {(s["document_id"], s["version"], s["section"]): s["sha256"] for s in meta["sections"]}
    seen = 0
    for doc in catalog["documents"]:
        bodies = procedures.section_bodies((FIXTURES / doc["path"]).read_text(encoding="utf-8"))
        for name in doc["sections"]:
            assert hashlib.sha256(bodies[name].encode("utf-8")).hexdigest() == expected[(doc["document_id"],
                                                                                        doc["version"], name)]
            seen += 1
    assert seen == len(expected)


def test_corpus_is_tenant_scoped_and_approved_only():
    alpha = procedures.Corpus.load(FIXTURES, "alpha")
    ids = sorted(s.evidence_id for s in alpha.sections)
    assert ids == ["ALPHA-EVIDENCE:v1:quality", "ALPHA-INCIDENT:v2:evidence", "ALPHA-INCIDENT:v2:review",
                   "ALPHA-TRIAGE:v1:limits", "ALPHA-TRIAGE:v1:scope"]  # no v1 (superseded), no ALPHA-DRAFT (draft)
    beta = procedures.Corpus.load(FIXTURES, "beta")
    assert {s.document_id for s in beta.sections} == {"BETA-INCIDENT", "BETA-TRIAGE", "BETA-EVIDENCE"}
    assert alpha.corpus_version == "handoff-1"
    review = next(s for s in alpha.sections if s.evidence_id == "ALPHA-INCIDENT:v2:review")
    assert review.content_sha256 == "62a90906c7bb706ae8a968eb0f7102f76b05d2c3be911c182d528a1fd25ef008"
    assert review.effective_from == "2026-10-01T00:00:00Z"
    corpora = procedures.load_corpora(FIXTURES)
    assert set(corpora) == {ALPHA, BETA} and corpora[ALPHA] is not corpora[BETA]


def test_search_is_lexical_deterministic_and_bounded():
    alpha = procedures.Corpus.load(FIXTURES, "alpha")
    hits = alpha.search("a different authorized reviewer must inspect the exact content", limit=3)
    assert hits[0].section.evidence_id == "ALPHA-INCIDENT:v2:review" and len(hits) <= 3
    assert [h.section.evidence_id for h in hits] == [h.section.evidence_id for h in alpha.search(
        "a different authorized reviewer must inspect the exact content", limit=3)]
    assert alpha.search("zzzz qqqq", limit=8) == []
    assert len(alpha.search("the", limit=1)) == 1


def test_search_response_matches_the_tool_result_contract():
    corpora = procedures.load_corpora(FIXTURES)
    doc = server.search_response(corpora, tenant_id=ALPHA, query="warnings incident draft", limit=2, now=NOW)
    TOOL_RESULT.validate(doc)
    assert doc["status"] == "ok" and doc["data"]["retrieval_mode"] == "lexical"
    assert doc["data"]["corpus_version"] == "handoff-1" and doc["data"]["results"][0]["retrieved_at"] == "2026-10-08T12:00:00Z"
    assert {r["document_id"] for r in doc["data"]["results"]} <= {"ALPHA-INCIDENT", "ALPHA-TRIAGE", "ALPHA-EVIDENCE"}
    unknown = server.search_response(corpora, tenant_id=UUID(int=99), query="x", limit=1, now=NOW)
    TOOL_RESULT.validate(unknown)
    assert unknown["data"] == {"results": [], "retrieval_mode": "lexical", "corpus_version": "handoff-1"}
    err = server.envelope("search_procedures", error=server.tool_error("INVALID_HANDLE", "missing invocation handle"))
    TOOL_RESULT.validate(err)
    assert err["status"] == "error" and err["data"] is None


class StubVerifier:
    @property
    def ready(self) -> bool:
        return True

    async def load_keys(self) -> None:
        return None

    async def verify_async(self, token: str) -> Principal:
        raise TokenRejected("unit test")


@pytest.mark.asyncio
async def test_tool_schema_conforms_to_the_contract_and_rejects_extra_arguments():
    state = server.State(session=None, corpora=procedures.load_corpora(FIXTURES), verifier=StubVerifier())
    mcp = server.build_server(state, issuer="http://localhost:18080/realms/ops-dev",
                              resource_url="http://mcp-read:8081/mcp")
    async with Client(mcp) as client:  # in-process: no HTTP, so no bearer middleware; schema and validation only
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert set(tools) == {"search_procedures"}
        schema: dict[str, Any] = tools["search_procedures"].input_schema
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(INPUT["required"])
        assert set(schema["properties"]) <= set(INPUT["properties"])
        assert schema["properties"]["mode"]["enum"] == INPUT["properties"]["mode"]["enum"]
        assert (schema["properties"]["limit"]["minimum"], schema["properties"]["limit"]["maximum"]) == (1, 8)
        assert (schema["properties"]["query"]["minLength"], schema["properties"]["query"]["maxLength"]) == (1, 500)
        extra = await client.call_tool("search_procedures", {"query": "x", "limit": 1, "mode": "lexical",
                                                             "tenant_id": str(ALPHA)})
        assert extra.is_error  # SA:350: an argument that supplies a tenant is rejected, not ignored
        bad = await client.call_tool("search_procedures", {"query": "x", "limit": 9, "mode": "lexical"})
        assert bad.is_error
        # Without the bearer middleware there is no access token, so the tool body refuses before any lookup.
        res = await client.call_tool("search_procedures", {"query": "x", "limit": 1, "mode": "lexical"})
        assert not res.is_error and res.structured_content["status"] == "error"
        assert res.structured_content["error"]["code"] == "INVALID_HANDLE"
```

Run: `PYTHONUTF8=1 uv run python -m pytest tests/plan_d/test_mcp_read.py -q`
Expected: an `ImportError` for `ops_mcp_read.procedures` (the module does not exist yet).

- [ ] **Step 2: The fixture corpus**

Create `mcp-read/src/ops_mcp_read/procedures.py`:

```python
"""Lexical procedure search over the authored fixtures (T08; debt → T17: the governed store, `search_procedures_scoped`
and `vector_exact`).

The corpus is built per tenant from `data/handoff-fixtures/catalog.json`: only that tenant's documents (the fixtures
README: "An alpha identity must not see beta evidence") and only `approved` versions, so a superseded or draft document
is never cited. Sections are sliced exactly as scripts/gen_fixture_meta.py slices them and carry the per-section hash
from meta.json, so an `evidence_ref` the proposal cites (`<DOCUMENT_ID>:v<version>:<section>`) names bytes the
destination reviewer can re-hash. Ranking is term overlap with a deterministic tie-break: the same query must cite the
same evidence on a retry (BUILD_SPEC §6: retries keep the same proposal).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

WORD = re.compile(r"[a-z0-9]+")
EXCERPT_CHARS = 500


def tokens(text: str) -> set[str]:
    return set(WORD.findall(text.lower()))


def section_bodies(markdown: str) -> dict[str, str]:
    """Body of every `## <name>` section: lines up to the next `## ` or EOF, outer newlines stripped (meta.json rule)."""
    bodies: dict[str, str] = {}
    name: str | None = None
    buffer: list[str] = []
    for line in markdown.split("\n"):
        if line.startswith("## "):
            if name is not None:
                bodies[name] = "\n".join(buffer).strip("\n")
            name, buffer = line[3:].strip(), []
        elif name is not None:
            buffer.append(line)
    if name is not None:
        bodies[name] = "\n".join(buffer).strip("\n")
    return bodies


@dataclass(frozen=True)
class Section:
    evidence_id: str
    document_id: str
    version: str
    section: str
    content_sha256: str
    text: str
    effective_from: str


@dataclass(frozen=True)
class Hit:
    section: Section
    score: int


@dataclass(frozen=True)
class Corpus:
    sections: tuple[Section, ...]
    corpus_version: str

    @classmethod
    def load(cls, fixtures_dir: Path, tenant_slug: str) -> Corpus:
        catalog = json.loads((fixtures_dir / "catalog.json").read_text(encoding="utf-8"))
        meta = json.loads((fixtures_dir / "meta.json").read_text(encoding="utf-8"))
        hashes = {(s["document_id"], s["version"], s["section"]): s["sha256"] for s in meta["sections"]}
        sections: list[Section] = []
        for doc in catalog["documents"]:
            if doc["tenant"] != tenant_slug or doc["approval_status"] != "approved":
                continue
            bodies = section_bodies((fixtures_dir / doc["path"]).read_text(encoding="utf-8"))
            for name in doc["sections"]:
                sections.append(
                    Section(
                        evidence_id=f"{doc['document_id']}:v{doc['version']}:{name}",
                        document_id=doc["document_id"],
                        version=doc["version"],
                        section=name,
                        content_sha256=hashes[(doc["document_id"], doc["version"], name)],
                        text=bodies[name],
                        effective_from=doc["effective_from"],
                    )
                )
        return cls(tuple(sections), corpus_version=catalog["fixture_version"])

    def search(self, query: str, limit: int) -> list[Hit]:
        wanted = tokens(query)
        hits = [Hit(s, len(wanted & tokens(s.text))) for s in self.sections]
        hits = [h for h in hits if h.score > 0]
        hits.sort(key=lambda h: (-h.score, h.section.evidence_id))
        return hits[:limit]


def load_corpora(fixtures_dir: Path) -> dict[UUID, Corpus]:
    """One corpus per tenant, keyed by the tenant UUID a resolved handle carries."""
    meta = json.loads((fixtures_dir / "meta.json").read_text(encoding="utf-8"))
    return {UUID(tenant_id): Corpus.load(fixtures_dir, slug) for slug, tenant_id in meta["tenants"].items()}
```

- [ ] **Step 3: The server**

Create `mcp-read/src/ops_mcp_read/server.py`:

```python
"""mcp-read: the authenticated read-tool server (ADR-0003; AM-15 read tools; SA:557 token checks).

Every call must present the worker's workload token (aud = this server's resource URL, azp = ops-worker) and an
`X-Ops-Invocation` handle minted for an `investigate` job; the handle, not the token, says which run and tenant the
call is for (BUILD_SPEC §9). The tool's argument model forbids extra keys, so an argument that tries to supply a
tenant, role or actor is refused before the tool body runs (SA:350). Results are the AM-80 tool-result envelope
(validated against schemas/tool-result.schema.json in the unit tests). One tool in T08; asset tools arrive with T16.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Protocol, TypedDict
from uuid import UUID, uuid4

import psycopg
import uvicorn
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.tools.base import Tool
from pydantic import AnyHttpUrl, ConfigDict, Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp

from ops_core import persistence, settings
from ops_core.jobs import Server, Tool as ToolName
from ops_core.tokens import Principal, TokenRejected, TokenVerifier
from ops_mcp_read import procedures


class ToolResult(TypedDict):
    tool_name: str
    request_id: str
    status: str
    observed_at: str
    truncated: bool
    data: dict[str, Any] | None
    error: dict[str, Any] | None


def stamp(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def tool_error(code: str, message: str) -> dict[str, Any]:
    return {"code": code, "message": message, "retryable": False}


def envelope(tool_name: str, *, data: dict[str, Any] | None = None, error: dict[str, Any] | None = None) -> ToolResult:
    return {
        "tool_name": tool_name,
        "request_id": str(uuid4()),
        "status": "error" if error is not None else "ok",
        "observed_at": stamp(datetime.now(UTC)),
        "truncated": False,
        "data": None if error is not None else data,
        "error": error,
    }


def search_response(
    corpora: dict[UUID, procedures.Corpus], *, tenant_id: UUID, query: str, limit: int, now: datetime
) -> ToolResult:
    """The tool's answer for a resolved tenant; database-free so the contract test can validate it."""
    corpus = corpora.get(tenant_id)
    fallback = next(iter(corpora.values()), None)
    version = corpus.corpus_version if corpus else (fallback.corpus_version if fallback else "none")
    hits = corpus.search(query, limit) if corpus else []
    results = [
        {
            "evidence_id": h.section.evidence_id,
            "document_id": h.section.document_id,
            "version": h.section.version,
            "section": h.section.section,
            "content_sha256": h.section.content_sha256,
            "excerpt": h.section.text[: procedures.EXCERPT_CHARS],
            "effective_from": h.section.effective_from,
            "retrieved_at": stamp(now),
        }
        for h in hits
    ]
    return envelope("search_procedures", data={"results": results, "retrieval_mode": "lexical",
                                               "corpus_version": version})


class Verifier(Protocol):  # the subset of ops_core.tokens.TokenVerifier the server needs; unit tests stub it
    @property
    def ready(self) -> bool: ...

    async def load_keys(self) -> None: ...

    async def verify_async(self, token: str) -> Principal: ...


class McpVerifier:
    """The SDK's TokenVerifier protocol: None means 401. The SDK re-checks `expires_at`, consistently with PyJWT."""

    def __init__(self, verifier: Verifier, resource_url: str) -> None:
        self._verifier = verifier
        self._resource = resource_url

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            principal = await self._verifier.verify_async(token)
        except TokenRejected:
            return None
        return AccessToken(token=token, client_id=principal.azp, scopes=[], expires_at=principal.expires_at,
                           resource=self._resource, subject=principal.subject, claims=dict(principal.claims))


def strict_tool(fn: Any) -> Tool:
    """A Tool whose argument model forbids extra keys and whose advertised schema says so.

    The SDK derives the model from the signature and ignores unknown keys (measured in the Plan D spike); SA:350
    requires the opposite, so the model is subclassed with `extra="forbid"` and the schema regenerated.
    """
    tool = Tool.from_function(fn)
    base = tool.fn_metadata.arg_model
    strict: Any = type(base.__name__, (base,), {"model_config": ConfigDict(arbitrary_types_allowed=True, extra="forbid")})
    tool.fn_metadata.arg_model = strict
    tool.parameters = strict.model_json_schema(by_alias=True)
    return tool


@dataclass
class State:
    session: persistence.Session | None
    corpora: dict[UUID, procedures.Corpus]
    verifier: Verifier


def build_server(state: State, *, issuer: str, resource_url: str) -> MCPServer:
    async def search_procedures(
        query: Annotated[str, Field(min_length=1, max_length=500)],
        limit: Annotated[int, Field(ge=1, le=8)],
        mode: Literal["lexical", "vector_exact"],
        ctx: Context,
    ) -> ToolResult:
        """Lexical search over approved procedure sections of the calling run's tenant (AM-15 read tool)."""
        token = get_access_token()
        handle = (ctx.headers or {}).get("x-ops-invocation")  # header names arrive lower-case
        if token is None or not handle or state.session is None:
            return envelope("search_procedures", error=tool_error("INVALID_HANDLE", "missing invocation handle"))
        try:
            async with state.session.unit() as conn:
                invocation = await persistence.resolve_handle(conn, handle=handle, server=Server.READ,
                                                              azp=token.client_id, tool=ToolName.SEARCH_PROCEDURES)
        except persistence.HandleRejected as exc:
            return envelope("search_procedures", error=tool_error("INVALID_HANDLE", str(exc)))
        if mode != "lexical":
            return envelope("search_procedures", error=tool_error("UNSUPPORTED_MODE", "vector_exact arrives with T17"))
        return search_response(state.corpora, tenant_id=invocation.tenant_id, query=query, limit=limit,
                               now=datetime.now(UTC))

    return MCPServer(
        name="mcp-read",
        auth=AuthSettings(issuer_url=AnyHttpUrl(issuer), resource_server_url=AnyHttpUrl(resource_url),
                          validate_token_resource=False),
        token_verifier=McpVerifier(state.verifier, resource_url),
        tools=[strict_tool(search_procedures)],
    )


def build_app(server: MCPServer, state: State) -> Starlette:
    mcp_app = server.streamable_http_app(streamable_http_path="/mcp", stateless_http=True, json_response=True)

    @contextlib.asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        if state.session is None:
            state.session = persistence.Session(await persistence.connect(settings.app_postgres()))
        if not state.verifier.ready:
            await state.verifier.load_keys()
        # A mounted sub-app's lifespan never runs on its own; the session manager lives in it (measured).
        async with mcp_app.router.lifespan_context(mcp_app):
            yield
        await state.session.conn.close()

    async def live(_: Request) -> JSONResponse:
        return JSONResponse({"status": "live"})

    async def ready(_: Request) -> JSONResponse:
        if state.session is None or not state.verifier.ready:
            return JSONResponse({"status": "not ready"}, status_code=503)
        try:
            await state.session.read("SELECT 1", ())
        except (psycopg.Error, OSError):  # readiness reports a database failure as not ready
            return JSONResponse({"status": "not ready"}, status_code=503)
        return JSONResponse({"status": "ready"})

    return Starlette(routes=[Route("/health/live", live), Route("/health/ready", ready), Mount("/", app=mcp_app)],
                     lifespan=lifespan)


def production_app() -> Starlette:
    kc = settings.keycloak()
    urls = settings.urls()
    verifier = TokenVerifier(issuer=kc.issuer, audience=urls.mcp_read_resource,
                             allowed_azp=frozenset({"ops-worker"}), jwks_url=kc.jwks_url)
    state = State(session=None, corpora=procedures.load_corpora(settings.fixtures_dir()), verifier=verifier)
    return build_app(build_server(state, issuer=kc.issuer, resource_url=urls.mcp_read_resource), state)


def serve_app(app: ASGIApp, port: int) -> None:
    """Serve with uvicorn programmatically on a selector loop (ruling 23: `uvicorn.run` picks the Proactor loop on
    Windows and psycopg async refuses it)."""
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    if sys.platform == "win32":
        asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(server.serve())


def serve() -> None:
    serve_app(production_app(), settings.env_int("OPS_MCP_READ_PORT", 8081))
```

(`import asyncio` and `import sys` join the imports.) Notes for the implementer: (a) `Context.headers` is the attribute the spike measured. (b) Keep `from ops_core.jobs import Tool as ToolName` to avoid clashing with the SDK's `Tool`.

Create `mcp-read/src/ops_mcp_read/__main__.py`:

```python
"""`python -m ops_mcp_read`: serve the read-tool server on 127.0.0.1:OPS_MCP_READ_PORT (default 8081)."""

from ops_mcp_read.server import serve

if __name__ == "__main__":
    serve()
```

Run: `PYTHONUTF8=1 uv run python -m pytest tests/plan_d/test_mcp_read.py -q`
Expected: `5 passed`.

- [ ] **Step 4: Live: a real client over HTTP with a real token and a real handle**

Create `tests/e2e/test_mcp_read_live.py`:

```python
"""mcp-read over a real socket with a real worker token and a handle minted in the database (OPS_LIVE=1; BUILD_SPEC
§10: "an in-process call is not sufficient"). Catches: the bearer middleware wired to the wrong audience, a handle
that resolves at the wrong server, and the two rejections the e2e test relies on (persona token; mcp-write's token)."""

import asyncio
from uuid import UUID

import httpx2
import pytest
import uvicorn
from mcp import Client, MCPError
from mcp.client.streamable_http import streamable_http_client
from ops_core import persistence, settings
from ops_core.jobs import Server
from ops_core.tokens import WorkloadTokenSource
from ops_mcp_read.server import production_app
from tests.e2e.conftest import purge_run
from tests.e2e.test_migrations_and_persistence import new_run
from tests.plan_b.live import kc

pytestmark = pytest.mark.asyncio


async def test_search_over_http(app_conn: persistence.Conn, secret) -> None:
    kcs = settings.keycloak()
    # Port 18081: the skeleton's own mcp-read may be up on 8081 in the same session (Task 9's fixture).
    server = uvicorn.Server(uvicorn.Config(production_app(), host="127.0.0.1", port=18081, log_level="warning"))
    url = "http://127.0.0.1:18081/mcp"
    task = asyncio.create_task(server.serve())
    run = None
    try:
        while not server.started:
            await asyncio.sleep(0.05)
        async with app_conn.transaction():  # committed: the server reads the handle on its own connection
            # The seeded alpha tenant: only seeded tenants have a fixture corpus (W11 in the round-1 dry run).
            _, _, run = await new_run(app_conn, UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7"))
            cur = await app_conn.execute("SELECT id FROM app.jobs WHERE run_id = %s", (run,))
            job = (await cur.fetchone())["id"]
            handle = await persistence.mint_handle(app_conn, run_id=run, job_id=job, server=Server.READ,
                                                   azp="ops-worker")
        worker = WorkloadTokenSource(token_url=kcs.token_url, client_id="ops-worker",
                                     client_secret=secret("kc_client_secret_ops_worker"))
        headers = {"Authorization": f"Bearer {await worker.token()}", "X-Ops-Invocation": handle}
        async with (
            httpx2.AsyncClient(headers=headers) as hc,
            Client(streamable_http_client(url, http_client=hc), mode="2026-07-28") as client,
        ):
            res = await client.call_tool("search_procedures", {"query": "reviewer inspect exact content",
                                                               "limit": 2, "mode": "lexical"})
        assert not res.is_error and res.structured_content["status"] == "ok"
        assert res.structured_content["data"]["results"][0]["evidence_id"] == "ALPHA-INCIDENT:v2:review"
        # The persona's token (aud ops-api) and mcp-write's token (aud incident-sim) are refused at the transport.
        alex = kc.token_password(kcs.base_url, "ops-dev-direct", "alex", secret("kc_persona_alex_password"))
        for token in (alex["access_token"], await WorkloadTokenSource(
                token_url=kcs.token_url, client_id="ops-mcp-write",
                client_secret=secret("kc_client_secret_ops_mcp_write")).token()):
            async with (
                httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}", "X-Ops-Invocation": handle}) as hc,
                Client(streamable_http_client(url, http_client=hc), mode="2026-07-28") as client,
            ):
                with pytest.raises(MCPError):
                    await client.call_tool("search_procedures", {"query": "x", "limit": 1, "mode": "lexical"})
    finally:
        server.should_exit = True
        await task
        if run is not None:
            await purge_run(app_conn, run)
```

(`purge_run` from the e2e conftest removes the run, its rows, and the conversation and message `new_run` made for it; the seeded tenant stays.)

Run: `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_mcp_read_live.py -q`
Expected: `1 passed`.

- [ ] **Step 5: README, full check, commit**

Append to `mcp-read/README.md`:

```markdown
## Runs (T08)

`python -m ops_mcp_read` on 127.0.0.1:8081 (`OPS_MCP_READ_PORT`), Streamable HTTP at `/mcp`, protocol 2026-07-28,
stateless. Verifies `aud ∋ MCP_READ_RESOURCE_URL`, `azp == ops-worker`; resolves `X-Ops-Invocation` for `investigate`
jobs. One tool, `search_procedures` (lexical, fixture-backed until T17).
```

Run: `uv run ruff format mcp-read tests/plan_d/test_mcp_read.py tests/e2e/test_mcp_read_live.py && uv run ruff check --fix mcp-read tests/plan_d/test_mcp_read.py tests/e2e/test_mcp_read_live.py && PYTHONUTF8=1 uv run python scripts/check.py 2>&1 | tail -3`
Expected: `CHECK: GREEN`.

```bash
git add mcp-read tests/plan_d/test_mcp_read.py tests/e2e/test_mcp_read_live.py
git commit -m "feat(mcp-read): authenticated read server with search_procedures over the fixture corpus and handle resolution"
```

---
### Task 6: mcp-write — grant, mark_sent, the destination call and record_outcome behind one tool

**Files:**
- Create: `mcp-write/src/ops_mcp_write/destination.py`, `mcp-write/src/ops_mcp_write/execution.py`, `mcp-write/src/ops_mcp_write/server.py`, `mcp-write/src/ops_mcp_write/__main__.py`, `tests/plan_d/test_mcp_write.py`, `tests/e2e/test_mcp_write_live.py`
- Modify: `mcp-write/README.md` ("## Runs (T08)")

**Interfaces:**
- Consumes: Task 2 persistence (`transition`, `append_event`, `run_row`, `resolve_handle`, `Invocation`, `connect`, errors), Task 3 (`TokenVerifier`, `WorkloadTokenSource`), Task 4's HTTP contract, `ops_core.outcomes` (`ActionOutcome`, `Receipt`, `Tombstone`, `ToolOutcome`, `DestinationState`, `outcome_from_destination`, `EventType`, `EventSource`), `ops_core.states` (`RunState`, `Performer`, `Reason`), `ops_core.canonical.canonical_json`.
- Produces: `ops_mcp_write.destination` — `@dataclass(frozen=True) Reply(status_code: int, document: dict[str, Any])`, `async post_incident(http, *, url, token, action_id, payload_sha256, payload_canonical) -> Reply | None`, `classify(reply, *, action_id, payload_sha256) -> ActionOutcome` (pure). `ops_mcp_write.execution` — `@dataclass(frozen=True) Grant(action_id, run_id, proposal_id, tenant_id, conversation_id, payload_sha256, payload_canonical, attempt_state, detail)`, `class GrantRefused(PersistenceError)`, `async load_grant(conn, run_id) -> Grant | None`, `async grant_execution(conn, *, invocation, proposal_id) -> Grant` (replays return the existing grant), `async mark_sent(conn, grant) -> None`, `async record_outcome(conn, grant, outcome) -> None`, `async mark_unknown(conn, grant) -> None`, `next_step(attempt_state: str) -> Literal["stored", "send", "resend"]` (pure), `async create_incident(deps, *, invocation, proposal_id) -> ActionOutcome`, `@dataclass Deps(session: persistence.Session, http, destination_url, destination_token)`; every `execution` function takes the `conn` of an open unit of work (`async with deps.session.unit() as conn`) and opens no transaction itself. `ops_mcp_write.server` — the same `ToolResult`, `envelope`, `tool_error`, `McpVerifier`, `strict_tool` as mcp-read (duplicated on purpose: members do not import each other, ADR-0001), `outcome_envelope(outcome) -> ToolResult`, `State`, `build_server`, `build_app`, `production_app`, `serve`.

- [ ] **Step 1: Write the failing tests**

Create `tests/plan_d/test_mcp_write.py`:

```python
"""mcp-write without a network (AM-13 attempt protocol, AM-80 envelope rules, review focus 1).

Catches: a receipt accepted without checking its action id and hash (SA:358 says a mismatch is CONFLICT), a transport
failure reported as "no effect" instead of UNKNOWN (BUILD_SPEC §1), an ABORTED tombstone mapped to the wrong reason, a
replay that would send a second POST after the outcome was recorded, an envelope with status=ok around an UNKNOWN
outcome (R083), and a tool schema that accepts an extra argument.
"""

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from mcp import Client
from ops_core.outcomes import ToolOutcome
from ops_core.states import Reason
from ops_core.tokens import Principal, TokenRejected
from ops_mcp_write import destination, execution, server

ACTION = UUID(int=11)
SHA = "a" * 64
RECEIPT = {"receipt_id": str(UUID(int=12)), "incident_id": "INC-000007", "committed_at": "2026-10-08T12:00:00Z"}
TOOL_RESULT = Draft202012Validator(json.loads(Path("schemas/tool-result.schema.json").read_text(encoding="utf-8")),
                                   format_checker=FormatChecker())
INPUT = json.loads(Path("schemas/tools/create_incident.input.schema.json").read_text(encoding="utf-8"))


def committed(action: UUID = ACTION, sha: str = SHA) -> destination.Reply:
    return destination.Reply(200, {"state": "COMMITTED", "action_id": str(action), "payload_sha256": sha,
                                   "receipt": RECEIPT})


def test_classify_succeeded_only_when_identity_and_hash_match():
    ok = destination.classify(committed(), action_id=ACTION, payload_sha256=SHA)
    assert ok.status is ToolOutcome.SUCCEEDED and ok.receipt is not None and ok.receipt.incident_id == "INC-000007"
    other_action = destination.classify(committed(action=UUID(int=99)), action_id=ACTION, payload_sha256=SHA)
    other_hash = destination.classify(committed(sha="b" * 64), action_id=ACTION, payload_sha256=SHA)
    assert other_action.status is ToolOutcome.CONFLICT and other_hash.status is ToolOutcome.CONFLICT


def test_classify_conflict_unknown_and_tombstones():
    conflict = destination.Reply(409, {"state": "CONFLICT", "action_id": str(ACTION), "payload_sha256": "b" * 64})
    assert destination.classify(conflict, action_id=ACTION, payload_sha256=SHA).status is ToolOutcome.CONFLICT
    assert destination.classify(None, action_id=ACTION, payload_sha256=SHA).status is ToolOutcome.UNKNOWN
    assert destination.classify(destination.Reply(500, {}), action_id=ACTION, payload_sha256=SHA).status is (
        ToolOutcome.UNKNOWN)
    broken = destination.Reply(200, {"state": "COMMITTED", "action_id": str(ACTION), "payload_sha256": SHA,
                                     "receipt": {"receipt_id": "nope"}})
    assert destination.classify(broken, action_id=ACTION, payload_sha256=SHA).status is ToolOutcome.UNKNOWN
    for state, reason in (("REJECTED", Reason.REJECTED), ("ABORTED", Reason.ABORTED_NO_COMMIT)):
        tomb = destination.Reply(200, {"state": state, "action_id": str(ACTION), "payload_sha256": SHA,
                                       "tombstone": {"action_id": str(ACTION), "state": state,
                                                     "payload_sha256": SHA, "reason": "policy",
                                                     "decided_at": "2026-10-08T12:00:00Z"}})
        out = destination.classify(tomb, action_id=ACTION, payload_sha256=SHA)
        assert out.status is ToolOutcome.FAILED_NO_COMMIT and out.reason is reason and out.tombstone is not None


@pytest.mark.parametrize("status", list(ToolOutcome))
def test_outcome_envelopes_follow_the_tool_result_contract(status: ToolOutcome):
    reply = {
        ToolOutcome.SUCCEEDED: committed(),
        ToolOutcome.CONFLICT: destination.Reply(409, {"state": "CONFLICT", "action_id": str(ACTION),
                                                      "payload_sha256": "b" * 64}),
        ToolOutcome.UNKNOWN: None,
        ToolOutcome.FAILED_NO_COMMIT: destination.Reply(200, {
            "state": "REJECTED", "action_id": str(ACTION), "payload_sha256": SHA,
            "tombstone": {"action_id": str(ACTION), "state": "REJECTED", "payload_sha256": SHA, "reason": "policy",
                          "decided_at": "2026-10-08T12:00:00Z"}}),
    }[status]
    outcome = destination.classify(reply, action_id=ACTION, payload_sha256=SHA)
    doc = server.outcome_envelope(outcome)
    TOOL_RESULT.validate(doc)
    assert doc["status"] == ("ok" if status is ToolOutcome.SUCCEEDED else "outcome")
    assert doc["data"]["status"] == status.value and doc["data"]["action_id"] == str(ACTION)
    err = server.envelope("create_incident", error=server.tool_error("INVALID_HANDLE", "x"))
    TOOL_RESULT.validate(err)
    assert "action_id" not in json.dumps(err)  # SA:357: an error before any grant never names an action


def test_next_step_replays_without_a_second_send_once_resolved():
    assert execution.next_step("RESOLVED") == "stored"
    assert execution.next_step("INTENT") == "send"
    assert execution.next_step("SENT") == "resend"
    with pytest.raises(ValueError):
        execution.next_step("ABORT_REQUESTED")  # T22 territory; the skeleton refuses to guess


class StubVerifier:
    @property
    def ready(self) -> bool:
        return True

    async def load_keys(self) -> None:
        return None

    async def verify_async(self, token: str) -> Principal:
        raise TokenRejected("unit test")


@pytest.mark.asyncio
async def test_tool_schema_matches_the_contract_and_rejects_extras():
    state = server.State(deps=None, verifier=StubVerifier())
    mcp = server.build_server(state, issuer="http://localhost:18080/realms/ops-dev",
                              resource_url="http://mcp-write:8082/mcp")
    async with Client(mcp) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert set(tools) == {"create_incident"}
        schema: dict[str, Any] = tools["create_incident"].input_schema
        assert schema["additionalProperties"] is False and schema["required"] == INPUT["required"]
        assert schema["properties"]["proposal_id"]["format"] == "uuid"
        extra = await client.call_tool("create_incident", {"proposal_id": str(UUID(int=1)), "approved": True})
        assert extra.is_error
        res = await client.call_tool("create_incident", {"proposal_id": str(UUID(int=1))})
        assert not res.is_error and res.structured_content["status"] == "error"
```

Run: `PYTHONUTF8=1 uv run python -m pytest tests/plan_d/test_mcp_write.py -q`
Expected: an `ImportError` for `ops_mcp_write.destination` (the module does not exist yet).

- [ ] **Step 2: The destination client**

Create `mcp-write/src/ops_mcp_write/destination.py`:

```python
"""The only path from the application to the destination (ADR-0001: mcp-write → incident-sim).

The POST carries the exact canonical bytes the reviewer approved, wrapped with the action id and hash (AM-13 §4). What
comes back is classified into the AM-13 tool outcome vocabulary without optimism: a transport failure after SENT is
UNKNOWN, never "no effect" (BUILD_SPEC §1, §11); a committed receipt counts only if its action id and hash are ours
(SA:358); a tombstone becomes FAILED_NO_COMMIT with the reason `outcome_from_destination` derives.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx2
from pydantic import ValidationError

from ops_core.canonical import canonical_json
from ops_core.outcomes import (
    ActionOutcome,
    DestinationState,
    Receipt,
    Tombstone,
    ToolOutcome,
    outcome_from_destination,
)


@dataclass(frozen=True)
class Reply:
    status_code: int
    document: dict[str, Any]


async def post_incident(
    http: httpx2.AsyncClient,
    *,
    url: str,
    token: str,
    action_id: UUID,
    payload_sha256: str,
    payload_canonical: bytes,
) -> Reply | None:
    """POST the approved bytes; None means the transport gave no usable answer (the caller records UNKNOWN)."""
    # The canonical bytes travel as one JSON string, so the destination hashes exactly what the reviewer approved.
    body = canonical_json({"action_id": str(action_id), "payload_sha256": payload_sha256,
                           "payload_canonical": payload_canonical.decode("utf-8")})
    try:
        response = await http.post(f"{url}/internal/incidents", content=body,
                                   headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                                   timeout=httpx2.Timeout(10.0))
        document = response.json()
    except (httpx2.HTTPError, ValueError):
        return None
    if not isinstance(document, dict):
        return None
    return Reply(response.status_code, document)


def _unknown(action_id: UUID, payload_sha256: str) -> ActionOutcome:
    return ActionOutcome(status=ToolOutcome.UNKNOWN, action_id=action_id, payload_sha256=payload_sha256,
                         receipt=None, tombstone=None, reason=None)


def _conflict(action_id: UUID, payload_sha256: str) -> ActionOutcome:
    return ActionOutcome(status=ToolOutcome.CONFLICT, action_id=action_id, payload_sha256=payload_sha256,
                         receipt=None, tombstone=None, reason=None)


def classify(reply: Reply | None, *, action_id: UUID, payload_sha256: str) -> ActionOutcome:
    if reply is None:
        return _unknown(action_id, payload_sha256)
    doc = reply.document
    try:
        if reply.status_code == 409 and doc.get("state") == "CONFLICT":
            return _conflict(action_id, payload_sha256)
        if reply.status_code != 200:
            return _unknown(action_id, payload_sha256)
        if doc.get("action_id") != str(action_id) or doc.get("payload_sha256") != payload_sha256:
            return _conflict(action_id, payload_sha256)  # a receipt for something else is not our receipt
        if doc.get("state") == "COMMITTED":
            receipt = Receipt.model_validate_json(json.dumps(doc["receipt"]))  # JSON mode: strict models parse ISO text
            return ActionOutcome(status=ToolOutcome.SUCCEEDED, action_id=action_id, payload_sha256=payload_sha256,
                                 receipt=receipt, tombstone=None, reason=None)
        state = DestinationState(doc["state"])
        tombstone = Tombstone.model_validate_json(json.dumps(doc["tombstone"]))
        outcome, reason = outcome_from_destination(state, sent=True, cancel_requested=False)
        return ActionOutcome(status=outcome, action_id=action_id, payload_sha256=payload_sha256, receipt=None,
                             tombstone=tombstone, reason=reason)
    except (KeyError, ValueError, ValidationError):
        return _unknown(action_id, payload_sha256)
```

- [ ] **Step 3: The execution protocol**

Create `mcp-write/src/ops_mcp_write/execution.py`:

```python
"""The write path in AM-13 order: grant → INTENT → SENT (committed before I/O) → POST → RESOLVED (T08 shape of
grant_execution, mark_sent, record_outcome and mark_unknown; TODO(T09/T22): the SECURITY DEFINER functions).

Replay rule (review focus 1): `execution_grant` is UNIQUE (run_id), so a second `create_incident` for the same run
finds the existing grant; if its attempt is RESOLVED the stored outcome is returned without touching the destination,
otherwise the same action id and bytes are re-sent and the destination's idempotent key answers. There is never a
second action id for one run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID, uuid4

import httpx2
from psycopg.types.json import Jsonb

from ops_core import persistence
from ops_core.outcomes import ActionOutcome, EventSource, EventType, ToolOutcome
from ops_core.states import Performer, Reason, RunState
from ops_core.tokens import WorkloadTokenSource
from ops_mcp_write import destination


class GrantRefused(persistence.PersistenceError):
    """The §13 gate said no before any grant existed; the tool answers status=error (SA:357)."""


@dataclass(frozen=True)
class Grant:
    action_id: UUID
    run_id: UUID
    proposal_id: UUID
    tenant_id: UUID
    conversation_id: UUID
    payload_sha256: str
    payload_canonical: bytes
    attempt_state: str
    detail: dict[str, Any] | None


async def load_grant(conn: persistence.Conn, run_id: UUID) -> Grant | None:
    cur = await conn.execute(
        "SELECT g.action_id, g.run_id, g.proposal_id, r.tenant_id, r.conversation_id, g.payload_sha256,"
        " p.payload_canonical, s.state AS attempt_state, s.detail"
        " FROM app.execution_grant g JOIN app.runs r ON r.run_id = g.run_id"
        " JOIN app.proposals p ON p.proposal_id = g.proposal_id"
        " JOIN LATERAL (SELECT state, detail FROM app.action_attempt_state"
        "               WHERE action_id = g.action_id ORDER BY attempt_no DESC, seq DESC LIMIT 1) s ON true"
        " WHERE g.run_id = %s",
        (run_id,),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    return Grant(row["action_id"], row["run_id"], row["proposal_id"], row["tenant_id"], row["conversation_id"],
                 row["payload_sha256"], bytes(row["payload_canonical"]), row["attempt_state"], row["detail"])


async def _attempt_state(conn: persistence.Conn, action_id: UUID, state: str, *, outcome: str | None = None,
                         detail: dict[str, Any] | None = None) -> None:
    await conn.execute(
        "INSERT INTO app.action_attempt_state (action_id, attempt_no, seq, state, outcome, detail)"
        " SELECT %s, 1, COALESCE(MAX(seq), 0) + 1, %s, %s, %s FROM app.action_attempt_state"
        " WHERE action_id = %s AND attempt_no = 1",
        (action_id, state, outcome, Jsonb(detail) if detail is not None else None, action_id),
    )


async def grant_execution(conn: persistence.Conn, *, invocation: persistence.Invocation, proposal_id: UUID) -> Grant:
    """The §13 final gate in its T08 form: the proposal is this run's active, approved revision; one grant per run.
    Runs inside the caller's unit of work."""
    run = await persistence.run_row(conn, invocation.run_id, lock=True)
    existing = await load_grant(conn, invocation.run_id)
    if existing is not None:
        if existing.proposal_id != proposal_id:
            raise GrantRefused("this run's grant binds another proposal")
        return existing  # UNIQUE (run_id): a replay finds the grant it already has
    cur = await conn.execute("SELECT * FROM app.proposals WHERE proposal_id = %s AND run_id = %s AND tenant_id = %s",
                             (proposal_id, invocation.run_id, invocation.tenant_id))
    proposal = await cur.fetchone()
    if proposal is None:
        raise GrantRefused("proposal does not belong to this run")
    if run["active_proposal_id"] != proposal_id or run["state"] != RunState.APPROVED.value:
        raise GrantRefused("proposal is not the run's approved active revision")
    cur = await conn.execute("SELECT 1 FROM app.decisions WHERE proposal_id = %s AND decision = 'approve'",
                             (proposal_id,))
    if await cur.fetchone() is None:
        raise GrantRefused("no approving decision is recorded")
    action_id = uuid4()  # random inside the gate (SA:168), never derived from the proposal
    await conn.execute(
        "INSERT INTO app.execution_grant (action_id, run_id, proposal_id, payload_sha256) VALUES (%s, %s, %s, %s)",
        (action_id, invocation.run_id, proposal_id, proposal["payload_sha256"]),
    )
    await conn.execute("INSERT INTO app.action_attempt (action_id, attempt_no) VALUES (%s, 1)", (action_id,))
    await _attempt_state(conn, action_id, "INTENT")
    await persistence.transition(conn, run_id=invocation.run_id, dst=RunState.EXECUTING,
                                 performer=Performer.GRANT_EXECUTION)
    await persistence.append_event(conn, tenant_id=invocation.tenant_id, conversation_id=invocation.conversation_id,
                                   run_id=invocation.run_id, type=EventType.ACTION_GRANTED,
                                   source=EventSource.APPLICATION,
                                   payload={"action_id": str(action_id), "proposal_id": str(proposal_id)})
    grant = await load_grant(conn, invocation.run_id)
    assert grant is not None
    return grant


async def mark_sent(conn: persistence.Conn, grant: Grant) -> None:
    """SENT, in its own unit of work that commits before the first byte leaves (SA:229): a crash after this point is
    reconciled, not retried."""
    await _attempt_state(conn, grant.action_id, "SENT")
    await persistence.append_event(conn, tenant_id=grant.tenant_id, conversation_id=grant.conversation_id,
                                   run_id=grant.run_id, type=EventType.ACTION_DISPATCHED,
                                   source=EventSource.APPLICATION, payload={"action_id": str(grant.action_id)})


async def record_outcome(conn: persistence.Conn, grant: Grant, outcome: ActionOutcome) -> None:
    """RESOLVED plus the run transition the outcome implies; the event is the destination's assertion (AM-14)."""
    data = outcome.model_dump(mode="json")
    await _attempt_state(conn, grant.action_id, "RESOLVED", outcome=outcome.status.value, detail=data)
    tenant, conversation, run = grant.tenant_id, grant.conversation_id, grant.run_id
    if outcome.status is ToolOutcome.SUCCEEDED:
        await persistence.transition(conn, run_id=run, dst=RunState.SUCCEEDED, performer=Performer.RECORD_OUTCOME)
        await persistence.append_event(conn, tenant_id=tenant, conversation_id=conversation, run_id=run,
                                       type=EventType.ACTION_CONFIRMED, source=EventSource.DESTINATION,
                                       payload={"status": "SUCCEEDED", "action_id": str(grant.action_id),
                                                "receipt": data["receipt"]})
    elif outcome.status is ToolOutcome.FAILED_NO_COMMIT:
        assert outcome.reason is not None  # ActionOutcome's own invariant
        await persistence.transition(conn, run_id=run, dst=RunState.FAILED, performer=Performer.RECORD_OUTCOME,
                                     reason=outcome.reason)
        await persistence.append_event(conn, tenant_id=tenant, conversation_id=conversation, run_id=run,
                                       type=EventType.ACTION_FAILED, source=EventSource.DESTINATION,
                                       payload={"action_id": str(grant.action_id), "reason": outcome.reason.value,
                                                "tombstone": data["tombstone"]})
    elif outcome.status is ToolOutcome.CONFLICT:
        await persistence.transition(conn, run_id=run, dst=RunState.ESCALATED, performer=Performer.RECORD_OUTCOME,
                                     reason=Reason.CONFLICT)
        await persistence.append_event(conn, tenant_id=tenant, conversation_id=conversation, run_id=run,
                                       type=EventType.ACTION_CONFLICT, source=EventSource.DESTINATION,
                                       payload={"action_id": str(grant.action_id)})
    else:
        raise ValueError("UNKNOWN is recorded by mark_unknown, not record_outcome")


async def mark_unknown(conn: persistence.Conn, grant: Grant) -> None:
    """A transport failure after SENT: the run says so and waits for reconciliation (T22)."""
    run = await persistence.run_row(conn, grant.run_id, lock=True)
    if run["state"] == RunState.EXECUTING.value:  # a second UNKNOWN changes nothing
        await persistence.transition(conn, run_id=grant.run_id, dst=RunState.OUTCOME_UNKNOWN,
                                     performer=Performer.MARK_UNKNOWN)
        await persistence.append_event(conn, tenant_id=grant.tenant_id, conversation_id=grant.conversation_id,
                                       run_id=grant.run_id, type=EventType.ACTION_UNCERTAIN,
                                       source=EventSource.APPLICATION, payload={"action_id": str(grant.action_id)})


def next_step(attempt_state: str) -> Literal["stored", "send", "resend"]:
    if attempt_state == "RESOLVED":
        return "stored"
    if attempt_state == "INTENT":
        return "send"
    if attempt_state == "SENT":
        return "resend"
    raise ValueError(f"attempt state {attempt_state} is not handled by the walking skeleton")


@dataclass
class Deps:
    session: persistence.Session
    http: httpx2.AsyncClient
    destination_url: str
    destination_token: WorkloadTokenSource


async def create_incident(deps: Deps, *, invocation: persistence.Invocation, proposal_id: UUID) -> ActionOutcome:
    """Four units of work in AM-13 order; the destination call sits between two commits, never inside one."""
    async with deps.session.unit() as conn:
        grant = await grant_execution(conn, invocation=invocation, proposal_id=proposal_id)
    step = next_step(grant.attempt_state)
    if step == "stored":
        assert grant.detail is not None
        return ActionOutcome.model_validate_json(json.dumps(grant.detail))
    if step == "send":
        async with deps.session.unit() as conn:
            await mark_sent(conn, grant)  # committed here, before any I/O
    reply = await destination.post_incident(deps.http, url=deps.destination_url,
                                            token=await deps.destination_token.token(), action_id=grant.action_id,
                                            payload_sha256=grant.payload_sha256,
                                            payload_canonical=grant.payload_canonical)
    outcome = destination.classify(reply, action_id=grant.action_id, payload_sha256=grant.payload_sha256)
    async with deps.session.unit() as conn:
        if outcome.status is ToolOutcome.UNKNOWN:
            await mark_unknown(conn, grant)
        else:
            await record_outcome(conn, grant, outcome)
    return outcome
```

- [ ] **Step 4: The server**

Create `mcp-write/src/ops_mcp_write/server.py`. Its import block is:

```python
from __future__ import annotations

import asyncio
import contextlib
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, TypedDict
from uuid import UUID, uuid4

import httpx2
import psycopg
import uvicorn
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.tools.base import Tool
from pydantic import AnyHttpUrl, ConfigDict
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp

from ops_core import persistence, settings
from ops_core.jobs import Server, Tool as ToolName
from ops_core.outcomes import ActionOutcome, ToolOutcome
from ops_core.tokens import Principal, TokenRejected, TokenVerifier, WorkloadTokenSource
from ops_mcp_write import execution
```

The module docstring (before the imports): `"""mcp-write: the authenticated write server (ADR-0003; AM-13 attempt protocol; SA:557 token checks). One tool, `create_incident`; the grant, dispatch and outcome happen here, never in the worker."""`. Then the same `ToolResult`, `stamp`, `tool_error`, `envelope`, `Verifier` (Protocol), `McpVerifier`, `strict_tool` and `serve_app` definitions as `ops_mcp_read.server`, copied verbatim under this two-line comment:

```python
# Duplicated from mcp-read on purpose: members never import each other (ADR-0001, test_layout); the shape is pinned
# by the tool-result contract tests in both packages.
```

then:

```python
def outcome_envelope(outcome: ActionOutcome) -> ToolResult:
    """`ok` only wraps SUCCEEDED (R083); every other outcome is `status=outcome` with `data.action_id` (SA:352)."""
    data = outcome.model_dump(mode="json")
    doc = envelope("create_incident", data=data)
    if outcome.status is not ToolOutcome.SUCCEEDED:
        doc["status"] = "outcome"
    return doc


@dataclass
class State:
    deps: execution.Deps | None
    verifier: Verifier


def build_server(state: State, *, issuer: str, resource_url: str) -> MCPServer:
    async def create_incident(proposal_id: UUID, ctx: Context) -> ToolResult:
        """Grant, dispatch and record the approved proposal's incident (AM-13 §2, AM-20.3 grant_execution)."""
        token = get_access_token()
        handle = (ctx.headers or {}).get("x-ops-invocation")
        if token is None or not handle or state.deps is None:
            return envelope("create_incident", error=tool_error("INVALID_HANDLE", "missing invocation handle"))
        try:
            async with state.deps.session.unit() as conn:
                invocation = await persistence.resolve_handle(conn, handle=handle, server=Server.WRITE,
                                                              azp=token.client_id, tool=ToolName.CREATE_INCIDENT)
            outcome = await execution.create_incident(state.deps, invocation=invocation, proposal_id=proposal_id)
        except persistence.HandleRejected as exc:
            return envelope("create_incident", error=tool_error("INVALID_HANDLE", str(exc)))
        except execution.GrantRefused as exc:
            return envelope("create_incident", error=tool_error("GRANT_REFUSED", str(exc)))
        except persistence.NotFound:
            return envelope("create_incident", error=tool_error("NOT_FOUND", "run not found"))
        return outcome_envelope(outcome)

    return MCPServer(
        name="mcp-write",
        auth=AuthSettings(issuer_url=AnyHttpUrl(issuer), resource_server_url=AnyHttpUrl(resource_url),
                          validate_token_resource=False),
        token_verifier=McpVerifier(state.verifier, resource_url),
        tools=[strict_tool(create_incident)],
    )


def build_app(server: MCPServer, state: State) -> Starlette:
    mcp_app = server.streamable_http_app(streamable_http_path="/mcp", stateless_http=True, json_response=True)

    @contextlib.asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        if state.deps is None:
            kc = settings.keycloak()
            state.deps = execution.Deps(
                session=persistence.Session(await persistence.connect(settings.app_postgres())),
                http=httpx2.AsyncClient(),
                destination_url=settings.urls().incident_sim,
                destination_token=WorkloadTokenSource(token_url=kc.token_url, client_id="ops-mcp-write",
                                                      client_secret=settings.read_secret("kc_client_secret_ops_mcp_write")),
            )
        if not state.verifier.ready:
            await state.verifier.load_keys()
        async with mcp_app.router.lifespan_context(mcp_app):
            yield
        await state.deps.http.aclose()
        await state.deps.session.conn.close()

    async def live(_: Request) -> JSONResponse:
        return JSONResponse({"status": "live"})

    async def ready(_: Request) -> JSONResponse:
        if state.deps is None or not state.verifier.ready:
            return JSONResponse({"status": "not ready"}, status_code=503)
        try:
            await state.deps.session.read("SELECT 1", ())
        except (psycopg.Error, OSError):  # readiness reports a database failure as not ready
            return JSONResponse({"status": "not ready"}, status_code=503)
        return JSONResponse({"status": "ready"})

    return Starlette(routes=[Route("/health/live", live), Route("/health/ready", ready), Mount("/", app=mcp_app)],
                     lifespan=lifespan)


def production_app() -> Starlette:
    kc = settings.keycloak()
    urls = settings.urls()
    verifier = TokenVerifier(issuer=kc.issuer, audience=urls.mcp_write_resource,
                             allowed_azp=frozenset({"ops-worker"}), jwks_url=kc.jwks_url)
    state = State(deps=None, verifier=verifier)
    return build_app(build_server(state, issuer=kc.issuer, resource_url=urls.mcp_write_resource), state)


def serve() -> None:
    serve_app(production_app(), settings.env_int("OPS_MCP_WRITE_PORT", 8082))
```

The write server's connection is autocommit (ruling 24); every write happens inside `Session.unit()`, which is a real transaction, and `mark_sent`'s unit commits before `post_incident` is awaited.

`__main__.py` mirrors mcp-read's with `ops_mcp_write.server.serve`.

Run: `PYTHONUTF8=1 uv run python -m pytest tests/plan_d/test_mcp_write.py -q`
Expected: `8 passed` (4 parametrized envelopes + 4).

- [ ] **Step 5: Live: the whole write path against a real incident-sim, twice**

Create `tests/e2e/test_mcp_write_live.py`:

```python
"""grant → SENT → POST → record_outcome against a real incident-sim process and the real database (OPS_LIVE=1), then the
same call again: one action id, one incident, the stored outcome returned without a second POST (review focus 1)."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx2
import pytest
import uvicorn
from ops_core import persistence, settings
from ops_core.canonical import canonical_json, canonical_sha256
from psycopg.types.json import Jsonb
from ops_core.jobs import JobType, Server, Tool
from ops_core.outcomes import EventSource, EventType, ToolOutcome
from ops_core.states import Performer, RunState
from ops_core.tokens import WorkloadTokenSource
from ops_incident_sim.app import production_app as incident_sim_app
from ops_mcp_write import destination, execution
from tests.e2e.conftest import purge_run, purge_tenant
from tests.e2e.test_migrations_and_persistence import new_run

pytestmark = pytest.mark.asyncio

ALEX = "2fc05986-c7ec-544c-b628-fdb112bbf18a"
SAM = "03f7eb09-e18d-5f33-bf75-12c57d5aaa54"


async def approved_run(conn: persistence.Conn) -> tuple:
    tenant, conv, run = await new_run(conn)
    await persistence.append_event(conn, tenant_id=tenant, conversation_id=conv, run_id=run,
                                   type=EventType.RUN_ACCEPTED, source=EventSource.APPLICATION, payload={})
    for dst in (RunState.RETRIEVING, RunState.DRAFTING):
        await persistence.transition(conn, run_id=run, dst=dst, performer=Performer.TRANSITION_RUN)
    draft, proposal = uuid4(), uuid4()
    now = datetime.now(UTC).replace(microsecond=0)
    payload = {
        "tenant_id": str(tenant), "run_id": str(run), "proposal_id": str(proposal), "revision": 1,
        "action": "create_incident", "destination": "synthetic-incidents", "asset_id": "A17",
        "start_at": (now - timedelta(hours=24)).isoformat().replace("+00:00", "Z"),
        "end_at": now.isoformat().replace("+00:00", "Z"), "title": "Live write-path proposal",
        "summary": "Synthetic.", "evidence_refs": ["ALPHA-INCIDENT:v2:review"],
        "source_snapshots": [{"evidence_id": "ALPHA-INCIDENT:v2:review",
                              "content_sha256": "62a90906c7bb706ae8a968eb0f7102f76b05d2c3be911c182d528a1fd25ef008",
                              "version": "2"}],
        "assumptions": [], "limitations": ["live test"], "workflow_version": "investigation-v1",
        "prompt_version": "incident-draft-v1",
        "expires_at": (now + timedelta(minutes=15)).isoformat().replace("+00:00", "Z"),
    }
    canonical = canonical_json(payload)
    sha = canonical_sha256(payload)
    await conn.execute("INSERT INTO app.drafts (id, run_id, draft_sha256, validated, kind) VALUES (%s, %s, %s, true,"
                       " 'proposal')", (draft, run, sha))
    await conn.execute(
        "INSERT INTO app.proposals (proposal_id, tenant_id, run_id, revision, draft_id, payload, payload_canonical,"
        " payload_sha256, canonicalization_version, authored_by, expires_at)"
        " VALUES (%s, %s, %s, 1, %s, %s, %s, %s, 1, %s, %s)",
        (proposal, tenant, run, draft, Jsonb(payload), canonical, sha, [ALEX],
         now + timedelta(minutes=15)),
    )  # Jsonb imported at the top in the real file: `from psycopg.types.json import Jsonb`
    await conn.execute("UPDATE app.runs SET active_proposal_id = %s WHERE run_id = %s", (proposal, run))
    await persistence.transition(conn, run_id=run, dst=RunState.AWAITING_APPROVAL, performer=Performer.FREEZE_PROPOSAL)
    await conn.execute(
        "INSERT INTO app.decisions (decision_id, proposal_id, reviewer, decision, expected_payload_sha256)"
        " VALUES (%s, %s, %s, 'approve', %s)", (uuid4(), proposal, SAM, sha))
    await persistence.transition(conn, run_id=run, dst=RunState.APPROVED, performer=Performer.RECORD_DECISION)
    job = await persistence.insert_job(conn, job_type=JobType.EXECUTE, run_id=run, proposal_id=proposal)
    assert job is not None
    handle = await persistence.mint_handle(conn, run_id=run, job_id=job, server=Server.WRITE, azp="ops-worker")
    return tenant, conv, run, proposal, handle


async def test_write_path_twice(app_conn: persistence.Conn, secret, monkeypatch: pytest.MonkeyPatch) -> None:
    # Port 18090: the skeleton's own incident-sim may hold 8090 in the same session (Task 9's fixture).
    server = uvicorn.Server(uvicorn.Config(incident_sim_app(), host="127.0.0.1", port=18090, log_level="warning"))
    task = asyncio.create_task(server.serve())
    observed: list[str] = []
    original_post = destination.post_incident

    async def post_with_probe(*args, **kwargs):
        # SA:229 / BUILD_SPEC §11: by the time the first byte leaves, SENT must be durable. A second connection sees
        # only committed rows, so it is the witness.
        witness = await persistence.connect(settings.app_postgres())
        try:
            cur = await witness.execute(
                "SELECT state FROM app.action_attempt_state WHERE action_id = %s ORDER BY seq DESC LIMIT 1",
                (kwargs["action_id"],))
            observed.append((await cur.fetchone() or {}).get("state", "NONE"))
        finally:
            await witness.close()
        return await original_post(*args, **kwargs)

    monkeypatch.setattr(destination, "post_incident", post_with_probe)
    tenant = run = None
    try:
        while not server.started:
            await asyncio.sleep(0.05)
        async with app_conn.transaction():  # committed: the witness connection must see the rows
            tenant, _, run, proposal, handle = await approved_run(app_conn)
        session = persistence.Session(app_conn)
        async with session.unit() as conn:
            invocation = await persistence.resolve_handle(conn, handle=handle, server=Server.WRITE, azp="ops-worker",
                                                          tool=Tool.CREATE_INCIDENT)
        kc = settings.keycloak()
        async with httpx2.AsyncClient() as http:
            deps = execution.Deps(session=session, http=http, destination_url="http://127.0.0.1:18090",
                                  destination_token=WorkloadTokenSource(
                                      token_url=kc.token_url, client_id="ops-mcp-write",
                                      client_secret=secret("kc_client_secret_ops_mcp_write")))
            first = await execution.create_incident(deps, invocation=invocation, proposal_id=proposal)
            second = await execution.create_incident(deps, invocation=invocation, proposal_id=proposal)
        assert first.status is ToolOutcome.SUCCEEDED and second == first
        assert observed == ["SENT"]  # exactly one POST, and SENT was committed before it
        row = await persistence.run_row(app_conn, run)
        assert row["state"] == "SUCCEEDED"
        cur = await app_conn.execute("SELECT type, source FROM app.events WHERE run_id = %s ORDER BY sequence", (run,))
        assert [tuple(r.values()) for r in await cur.fetchall()] == [
            ("run.accepted", "application"), ("action.granted", "application"), ("action.dispatched", "application"),
            ("action.confirmed", "destination")]
        cur = await app_conn.execute("SELECT count(*) AS n FROM app.action_attempt_state WHERE action_id = %s",
                                     (first.action_id,))
        assert (await cur.fetchone())["n"] == 3  # INTENT, SENT, RESOLVED and nothing for the replay
    finally:
        server.should_exit = True
        await task
        if run is not None:
            await purge_run(app_conn, run)
            await purge_tenant(app_conn, tenant)
```

The incident database keeps the committed key (keys are permanent by design, SA:265; each run of the test mints a fresh action id); the application rows are purged in `finally`.

Run: `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_mcp_write_live.py -q`
Expected: `1 passed`.

- [ ] **Step 6: README, full check, commit**

Append to `mcp-write/README.md`:

```markdown
## Runs (T08)

`python -m ops_mcp_write` on 127.0.0.1:8082 (`OPS_MCP_WRITE_PORT`), Streamable HTTP at `/mcp`. Verifies
`aud ∋ MCP_WRITE_RESOURCE_URL`, `azp == ops-worker`; resolves `X-Ops-Invocation` for `execute` jobs. One tool,
`create_incident`: grant → INTENT → SENT (committed before I/O) → POST incident-sim with the `ops-mcp-write` workload
token → RESOLVED. A replay returns the recorded outcome; a transport failure records OUTCOME_UNKNOWN (reconciliation: T22).
```

Run: `uv run ruff format mcp-write tests/plan_d/test_mcp_write.py tests/e2e/test_mcp_write_live.py && uv run ruff check --fix mcp-write tests/plan_d/test_mcp_write.py tests/e2e/test_mcp_write_live.py && PYTHONUTF8=1 uv run python scripts/check.py 2>&1 | tail -3`
Expected: `CHECK: GREEN`.

```bash
git add mcp-write tests/plan_d/test_mcp_write.py tests/e2e/test_mcp_write_live.py
git commit -m "feat(mcp-write): grant, mark_sent, destination call and record_outcome behind the create_incident tool"
```

---
### Task 7: api — admission, run snapshot, proposal, the independent decision, events

**Files:**
- Create: `api/src/ops_api/store.py`, `api/src/ops_api/app.py`, `api/src/ops_api/__main__.py`, `tests/plan_d/test_api.py`
- Modify: `api/README.md` ("## Runs (T08)")

**Interfaces:**
- Consumes: Task 2 persistence (`connect`, `create_run`, `append_event`, `transition`, `insert_job`, `run_row`), Task 3 (`TokenVerifier`, `Principal`, `TokenRejected`), `ops_core.contracts` (`load`, `MessageRequest`, `DecisionRequest`, `SafeError`, `ErrorCode`, `DuplicateKey`), `ops_core.states` (`Intent`, `Performer`, `Reason`, `RunState`), `ops_core.outcomes` (`EventType`, `EventSource`), `ops_core.jobs.JobType`.
- Produces: `ops_api.store` — `@dataclass(frozen=True) Membership(tenant_id: UUID, roles: frozenset[str])`, `Accepted(conversation_id, message_id, run_id, status, state_version)`, `Decided(proposal_id, run_id, decision, status, state_version)`, exceptions `Forbidden`, `NotFound`, `Conflict(code: str)`, pure `resolve_interval(hours, now) -> tuple[datetime, datetime]`, pure `check_reviewer(membership, *, requester, authored_by, reviewer) -> None`, `class Store(Protocol)` with `membership`, `create_conversation`, `admit`, `run`, `proposal`, `decide`, `events`, and `class DbStore(conn)`. `ops_api.app` — `create_app(verifier, store_factory) -> FastAPI`, `production_app() -> FastAPI`. HTTP: `GET /api/v1/me`; `POST /api/v1/conversations` → 201 `{"conversation_id"}`; `POST /api/v1/conversations/{id}/messages` → 202 `{"conversation_id","message_id","run_id","status","state_version","status_url","events_url"}`; `GET /api/v1/runs/{id}`; `GET /api/v1/proposals/{id}`; `POST /api/v1/proposals/{id}/decisions` → 200 `{"proposal_id","run_id","decision","status","state_version"}`; `GET /api/v1/runs/{id}/events?after=0&limit=100` → `{"events": [...]}`; `/health/live`, `/health/ready`. Errors are `SafeError` bodies with the ruling-20 mapping.

- [ ] **Step 1: Write the failing tests**

Create `tests/plan_d/test_api.py`:

```python
"""The API's authority rules without a database (BUILD_SPEC §7 admission, §12 independent decision, §9 identity).

Catches: a body that carries an authority field accepted (BUILD_SPEC §7: the server sets actor, tenant, roles), a
duplicate JSON key silently resolved, the requester approving their own proposal (SA:539), a reviewer from another
tenant seeing or deciding a proposal (404, not 403: existence is not disclosed), a decision on a stale hash accepted,
a second decision overwriting the first, and a run in another tenant readable by id.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from ops_api import store
from ops_api.app import create_app
from ops_core.contracts import DecisionRequest, MessageRequest
from ops_core.tokens import Principal, TokenRejected

ISSUER = "http://localhost:18080/realms/ops-dev"
ALPHA, BETA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7"), UUID("5ab45c2c-1e12-5a0c-a2b9-66cd2ff05201")
ALEX, SAM, LEE = UUID("2fc05986-c7ec-544c-b628-fdb112bbf18a"), UUID("03f7eb09-e18d-5f33-bf75-12c57d5aaa54"), UUID(
    "abcc1200-6791-57ab-87b5-9392d356b512")
JORDAN = UUID("cb551e64-83ec-582b-9047-8dadf20e151a")
SHA = "9" * 64
PERSONAS = {"alex": ALEX, "sam": SAM, "lee": LEE, "jordan": JORDAN}
MEMBERS = {ALEX: store.Membership(ALPHA, frozenset({"requester"})), SAM: store.Membership(ALPHA, frozenset({"reviewer"})),
           LEE: store.Membership(ALPHA, frozenset({"reader"})), JORDAN: store.Membership(BETA, frozenset({"reviewer"}))}


class StubVerifier:
    @property
    def ready(self) -> bool:
        return True

    async def load_keys(self) -> None:
        return None

    async def verify_async(self, token: str) -> Principal:
        if token not in PERSONAS:
            raise TokenRejected("unit test")
        return Principal(subject=str(PERSONAS[token]), azp="ops-dev-direct", audiences=("ops-api",), expires_at=2**31,
                         claims={"preferred_username": token})


class FakeStore:
    def __init__(self) -> None:
        self.conversations: dict[UUID, UUID] = {}  # conversation -> tenant
        self.runs: dict[UUID, dict[str, Any]] = {}
        self.proposals: dict[UUID, dict[str, Any]] = {}
        self.decided: set[UUID] = set()
        self.slot_occupied = False

    async def membership(self, issuer: str, subject: UUID) -> store.Membership | None:
        return MEMBERS.get(subject) if issuer == ISSUER else None

    async def create_conversation(self, tenant_id: UUID, created_by: UUID) -> UUID:
        cid = uuid4()
        self.conversations[cid] = tenant_id
        return cid

    async def admit(self, *, tenant_id: UUID, conversation_id: UUID, requester: UUID, request: MessageRequest,
                    start_at: datetime, end_at: datetime) -> store.Accepted:
        if self.conversations.get(conversation_id) != tenant_id:
            raise store.NotFound
        if self.slot_occupied:
            raise store.Conflict("SLOT_OCCUPIED")
        run_id = uuid4()
        self.runs[run_id] = {"run_id": run_id, "tenant_id": tenant_id, "conversation_id": conversation_id,
                             "requester": requester, "state": "QUEUED", "state_version": 1,
                             "active_proposal_id": None, "asset_id": request.context.asset_id if request.context else None,
                             "start_at": start_at, "end_at": end_at, "created_at": start_at}
        return store.Accepted(conversation_id, uuid4(), run_id, "QUEUED", 1)

    async def run(self, tenant_id: UUID, run_id: UUID) -> dict[str, Any] | None:
        row = self.runs.get(run_id)
        return row if row and row["tenant_id"] == tenant_id else None

    async def proposal(self, tenant_id: UUID, proposal_id: UUID) -> dict[str, Any] | None:
        row = self.proposals.get(proposal_id)
        return row if row and row["tenant_id"] == tenant_id else None

    async def decide(self, *, tenant_id: UUID, proposal_id: UUID, reviewer: UUID,
                     request: DecisionRequest) -> store.Decided:
        row = await self.proposal(tenant_id, proposal_id)
        if row is None:
            raise store.NotFound
        if (row["revision"], row["payload_sha256"]) != (request.expected_revision, request.expected_payload_sha256):
            raise store.Conflict("VERSION_CONFLICT")
        if proposal_id in self.decided:
            raise store.Conflict("VERSION_CONFLICT")
        self.decided.add(proposal_id)
        status = "APPROVED" if request.decision == "approve" else "REJECTED"
        return store.Decided(proposal_id, row["run_id"], request.decision, status, 5)

    async def events(self, tenant_id: UUID, run_id: UUID, *, after: int, limit: int) -> list[dict[str, Any]]:
        return [] if await self.run(tenant_id, run_id) is None else [{"sequence": 1, "type": "run.accepted"}]


@pytest.fixture
def api() -> Iterator[tuple[TestClient, FakeStore]]:
    fake = FakeStore()
    app = create_app(StubVerifier(), store_factory=lambda: fake)
    with TestClient(app) as c:  # the context manager runs the lifespan, which installs the store
        yield c, fake


def auth(name: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {name}"}


def test_identity_and_membership(api):
    c, _ = api
    assert c.get("/api/v1/me").status_code == 401
    assert c.get("/api/v1/me", headers=auth("nobody")).status_code == 401
    me = c.get("/api/v1/me", headers=auth("alex")).json()
    assert me == {"subject": str(ALEX), "tenant_id": str(ALPHA), "roles": ["requester"], "username": "alex"}


def test_admission_validates_the_body_and_returns_202(api):
    c, fake = api
    cid = c.post("/api/v1/conversations", headers=auth("alex")).json()["conversation_id"]
    body = {"kind": "investigate", "text": "Investigate the alerts on A17 over the last 24 hours.",
            "context": {"asset_id": "A17", "hours": 24}}
    r = c.post(f"/api/v1/conversations/{cid}/messages", headers=auth("alex"), json=body)
    assert r.status_code == 202, r.text
    doc = r.json()
    assert doc["status"] == "QUEUED" and doc["state_version"] == 1 and doc["conversation_id"] == cid
    assert doc["status_url"] == f"/api/v1/runs/{doc['run_id']}" and doc["events_url"].endswith("/events")
    run = fake.runs[UUID(doc["run_id"])]
    assert run["end_at"] - run["start_at"] == timedelta(hours=24)
    assert run["end_at"].microsecond == 0 and run["end_at"].tzinfo is not None
    for bad in (
        {**body, "tenant_id": str(BETA)},  # authority field (BUILD_SPEC §7)
        {**body, "kind": "ask"},  # not routed in T08 (admission router is T12)
        {"kind": "investigate", "text": "x"},  # no asset/interval
        {**body, "context": {"asset_id": "a17", "hours": 24}},  # AssetId pattern
    ):
        assert c.post(f"/api/v1/conversations/{cid}/messages", headers=auth("alex"), json=bad).status_code == 422, bad
    dup = '{"kind": "investigate", "kind": "ask", "text": "x", "context": {"asset_id": "A17", "hours": 1}}'
    r = c.post(f"/api/v1/conversations/{cid}/messages", headers={**auth("alex"), "Content-Type": "application/json"},
               content=dup)
    assert r.status_code == 422 and r.json()["code"] == "INVALID_INPUT"
    assert c.post(f"/api/v1/conversations/{cid}/messages", headers=auth("sam"), json=body).status_code == 403
    assert c.post(f"/api/v1/conversations/{uuid4()}/messages", headers=auth("alex"), json=body).status_code == 404
    fake.slot_occupied = True
    r = c.post(f"/api/v1/conversations/{cid}/messages", headers=auth("alex"), json=body)
    assert r.status_code == 409 and r.json()["code"] == "SLOT_OCCUPIED"


def test_runs_are_tenant_scoped(api):
    c, _ = api
    cid = c.post("/api/v1/conversations", headers=auth("alex")).json()["conversation_id"]
    body = {"kind": "investigate", "text": "x", "context": {"asset_id": "A17", "hours": 2}}
    run_id = c.post(f"/api/v1/conversations/{cid}/messages", headers=auth("alex"), json=body).json()["run_id"]
    assert c.get(f"/api/v1/runs/{run_id}", headers=auth("alex")).json()["status"] == "QUEUED"
    assert c.get(f"/api/v1/runs/{run_id}", headers=auth("jordan")).status_code == 404
    assert c.get(f"/api/v1/runs/{run_id}/events", headers=auth("alex")).json() == {
        "events": [{"sequence": 1, "type": "run.accepted"}]}
    assert c.get(f"/api/v1/runs/{run_id}/events", headers=auth("jordan")).status_code == 404


def seed_proposal(fake: FakeStore, tenant: UUID = ALPHA) -> UUID:
    pid, rid = uuid4(), uuid4()
    fake.runs[rid] = {"run_id": rid, "tenant_id": tenant, "conversation_id": uuid4(), "requester": ALEX,
                      "state": "AWAITING_APPROVAL", "state_version": 4, "active_proposal_id": pid, "asset_id": "A17",
                      "start_at": datetime(2026, 10, 7, tzinfo=UTC), "end_at": datetime(2026, 10, 8, tzinfo=UTC),
                      "created_at": datetime(2026, 10, 8, tzinfo=UTC)}
    fake.proposals[pid] = {"proposal_id": pid, "tenant_id": tenant, "run_id": rid, "revision": 1, "payload": {"k": 1},
                           "payload_sha256": SHA, "authored_by": [ALEX], "requester": ALEX,
                           "expires_at": datetime(2026, 10, 8, 12, 15, tzinfo=UTC)}
    return pid


def test_decision_requires_an_independent_current_reviewer(api):
    c, fake = api
    pid = seed_proposal(fake)
    body = {"expected_revision": 1, "expected_payload_sha256": SHA, "decision": "approve", "reason": "ok"}
    assert c.get(f"/api/v1/proposals/{pid}", headers=auth("sam")).json()["payload_sha256"] == SHA
    assert c.get(f"/api/v1/proposals/{pid}", headers=auth("jordan")).status_code == 404  # another tenant
    assert c.post(f"/api/v1/proposals/{pid}/decisions", headers=auth("alex"), json=body).status_code == 403  # self
    assert c.post(f"/api/v1/proposals/{pid}/decisions", headers=auth("lee"), json=body).status_code == 403  # reader
    assert c.post(f"/api/v1/proposals/{pid}/decisions", headers=auth("jordan"), json=body).status_code == 404
    stale = c.post(f"/api/v1/proposals/{pid}/decisions", headers=auth("sam"), json={**body, "expected_revision": 2})
    assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"
    bad = c.post(f"/api/v1/proposals/{pid}/decisions", headers=auth("sam"), json={**body, "approved_by": "sam"})
    assert bad.status_code == 422
    ok = c.post(f"/api/v1/proposals/{pid}/decisions", headers=auth("sam"), json=body)
    assert ok.status_code == 200 and ok.json()["status"] == "APPROVED" and ok.json()["decision"] == "approve"
    again = c.post(f"/api/v1/proposals/{pid}/decisions", headers=auth("sam"), json=body)
    assert again.status_code == 409  # first decision wins


def test_pure_rules():
    start, end = store.resolve_interval(24, datetime(2026, 10, 8, 12, 0, 0, 123456, tzinfo=UTC))
    assert (start.isoformat(), end.isoformat()) == ("2026-10-07T12:00:00+00:00", "2026-10-08T12:00:00+00:00")
    reviewer = store.Membership(ALPHA, frozenset({"reviewer"}))
    store.check_reviewer(reviewer, requester=ALEX, authored_by=[ALEX], reviewer=SAM)
    for who, member in ((ALEX, store.Membership(ALPHA, frozenset({"requester", "reviewer"}))),
                        (SAM, store.Membership(ALPHA, frozenset({"reader"})))):
        with pytest.raises(store.Forbidden):
            store.check_reviewer(member, requester=ALEX, authored_by=[ALEX], reviewer=who)
    with pytest.raises(store.Forbidden):  # a content author is not independent even when not the requester
        store.check_reviewer(reviewer, requester=ALEX, authored_by=[ALEX, SAM], reviewer=SAM)


def test_health(api):
    c, _ = api
    assert c.get("/health/live").json() == {"status": "live"} and c.get("/health/ready").status_code == 200
```

Run: `PYTHONUTF8=1 uv run python -m pytest tests/plan_d/test_api.py -q`
Expected: an `ImportError` for `ops_api.store` (the module does not exist yet).

- [ ] **Step 2: The store**

Create `api/src/ops_api/store.py`:

```python
"""The API's door to the database (T08 shape of create_run, record_decision and the read queries).

Every method is tenant-scoped by a WHERE clause (debt → T09 RLS) and the two writers are single transactions:
admission commits message, run, job and `run.accepted` together (BUILD_SPEC §7: success only after commit), and a
decision commits the decision row, the transition, the `execute` wake-up and `approval.recorded` together (BUILD_SPEC
§12). TODO(T09): `create_run`/`record_decision` definer functions; TODO(T12): Idempotency-Key, admission router.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from ops_core import persistence
from ops_core.contracts import DecisionRequest, MessageRequest
from ops_core.jobs import JobType
from ops_core.outcomes import EventSource, EventType
from ops_core.states import Intent, Performer, Reason, RunState


class Forbidden(Exception):
    pass


class NotFound(Exception):
    pass


class Conflict(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Membership:
    tenant_id: UUID
    roles: frozenset[str]


@dataclass(frozen=True)
class Accepted:
    conversation_id: UUID
    message_id: UUID
    run_id: UUID
    status: str
    state_version: int


@dataclass(frozen=True)
class Decided:
    proposal_id: UUID
    run_id: UUID
    decision: str
    status: str
    state_version: int


def resolve_interval(hours: int, now: datetime) -> tuple[datetime, datetime]:
    """"Last N hours" resolved once, at admission, to whole seconds (BUILD_SPEC §7: retries keep the window)."""
    end = now.replace(microsecond=0)
    return end - timedelta(hours=hours), end


def check_reviewer(membership: Membership, *, requester: UUID, authored_by: list[UUID], reviewer: UUID) -> None:
    """Independence (BUILD_SPEC §9, SA:539): a current reviewer who is neither the requester nor a content author."""
    if "reviewer" not in membership.roles:
        raise Forbidden
    if reviewer == requester or reviewer in authored_by:
        raise Forbidden


class Store(Protocol):
    async def membership(self, issuer: str, subject: UUID) -> Membership | None: ...

    async def create_conversation(self, tenant_id: UUID, created_by: UUID) -> UUID: ...

    async def admit(self, *, tenant_id: UUID, conversation_id: UUID, requester: UUID, request: MessageRequest,
                    start_at: datetime, end_at: datetime) -> Accepted: ...

    async def run(self, tenant_id: UUID, run_id: UUID) -> dict[str, Any] | None: ...

    async def proposal(self, tenant_id: UUID, proposal_id: UUID) -> dict[str, Any] | None: ...

    async def decide(self, *, tenant_id: UUID, proposal_id: UUID, reviewer: UUID,
                     request: DecisionRequest) -> Decided: ...

    async def events(self, tenant_id: UUID, run_id: UUID, *, after: int, limit: int) -> list[dict[str, Any]]: ...


class DbStore:
    def __init__(self, conn: persistence.Conn) -> None:
        self.session = persistence.Session(conn)  # ruling 24: one unit of work at a time, each a real transaction

    async def membership(self, issuer: str, subject: UUID) -> Membership | None:
        async with self.session.unit() as conn:
            cur = await conn.execute(
                "SELECT tenant_id, role FROM app.memberships WHERE issuer = %s AND subject = %s AND active",
                (issuer, subject),
            )
            rows = await cur.fetchall()
        if not rows:
            return None
        return Membership(rows[0]["tenant_id"], frozenset(r["role"] for r in rows))

    async def create_conversation(self, tenant_id: UUID, created_by: UUID) -> UUID:
        cid = uuid4()
        async with self.session.unit() as conn:
            await conn.execute(
                "INSERT INTO app.conversations (conversation_id, tenant_id, created_by) VALUES (%s, %s, %s)",
                (cid, tenant_id, created_by),
            )
        return cid

    async def admit(self, *, tenant_id: UUID, conversation_id: UUID, requester: UUID, request: MessageRequest,
                    start_at: datetime, end_at: datetime) -> Accepted:
        assert request.context is not None and request.context.asset_id is not None  # app.py checked the route
        message_id, run_id = uuid4(), uuid4()
        try:
            async with self.session.unit() as conn:
                cur = await conn.execute(
                    "SELECT 1 FROM app.conversations WHERE conversation_id = %s AND tenant_id = %s",
                    (conversation_id, tenant_id),
                )
                if await cur.fetchone() is None:
                    raise NotFound
                await conn.execute(
                    "INSERT INTO app.messages (message_id, tenant_id, conversation_id, kind, text, context, author)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (message_id, tenant_id, conversation_id, request.kind.value, request.text,
                     Jsonb(request.context.model_dump(mode="json")), requester),
                )
                version = await persistence.create_run(
                    conn, run_id=run_id, tenant_id=tenant_id, conversation_id=conversation_id,
                    message_id=message_id, requester=requester, intent=Intent.INVESTIGATE,
                    asset_id=request.context.asset_id, start_at=start_at, end_at=end_at,
                    supersedes_run_id=request.supersedes_run_id,
                )
                await persistence.append_event(conn, tenant_id=tenant_id, conversation_id=conversation_id,
                                               run_id=run_id, type=EventType.RUN_ACCEPTED,
                                               source=EventSource.APPLICATION, payload={})
        except psycopg.errors.UniqueViolation as exc:
            # The partial unique index is the slot rule (BUILD_SPEC §7); any other uniqueness error is a bug.
            if exc.diag.constraint_name == "runs_one_active_per_conversation":
                raise Conflict("SLOT_OCCUPIED") from exc
            raise
        return Accepted(conversation_id, message_id, run_id, RunState.QUEUED.value, version)

    async def run(self, tenant_id: UUID, run_id: UUID) -> dict[str, Any] | None:
        row = await self.session.read("SELECT * FROM app.runs WHERE run_id = %s AND tenant_id = %s", (run_id, tenant_id))
        return None if row is None else dict(row)

    async def proposal(self, tenant_id: UUID, proposal_id: UUID) -> dict[str, Any] | None:
        row = await self.session.read(
            "SELECT p.*, r.requester, r.state AS run_state FROM app.proposals p JOIN app.runs r ON r.run_id = p.run_id"
            " WHERE p.proposal_id = %s AND p.tenant_id = %s",
            (proposal_id, tenant_id),
        )
        return None if row is None else dict(row)

    async def decide(self, *, tenant_id: UUID, proposal_id: UUID, reviewer: UUID,
                     request: DecisionRequest) -> Decided:
        try:
            async with self.session.unit() as conn:
                cur = await conn.execute(
                    "SELECT p.run_id, p.revision, p.payload_sha256 FROM app.proposals p"
                    " WHERE p.proposal_id = %s AND p.tenant_id = %s",
                    (proposal_id, tenant_id),
                )
                proposal = await cur.fetchone()
                if proposal is None:
                    raise NotFound
                run = await persistence.run_row(conn, proposal["run_id"], lock=True)
                if run["active_proposal_id"] != proposal_id or run["state"] != RunState.AWAITING_APPROVAL.value:
                    raise Conflict("VERSION_CONFLICT")
                if (proposal["revision"], proposal["payload_sha256"]) != (request.expected_revision,
                                                                         request.expected_payload_sha256):
                    raise Conflict("VERSION_CONFLICT")  # exact content binding (BUILD_SPEC §12)
                await conn.execute(
                    "INSERT INTO app.decisions (decision_id, proposal_id, reviewer, decision, reason,"
                    " expected_payload_sha256) VALUES (%s, %s, %s, %s, %s, %s)",
                    (uuid4(), proposal_id, reviewer, request.decision, request.reason, request.expected_payload_sha256),
                )
                run_id: UUID = run["run_id"]
                conversation_id: UUID = run["conversation_id"]
                if request.decision == "approve":
                    version = await persistence.transition(conn, run_id=run_id, dst=RunState.APPROVED,
                                                           performer=Performer.RECORD_DECISION)
                    await persistence.insert_job(conn, job_type=JobType.EXECUTE, run_id=run_id,
                                                 proposal_id=proposal_id)
                    await persistence.append_event(conn, tenant_id=tenant_id, conversation_id=conversation_id,
                                                   run_id=run_id, type=EventType.APPROVAL_RECORDED,
                                                   source=EventSource.APPLICATION,
                                                   payload={"proposal_id": str(proposal_id)})
                    status = RunState.APPROVED.value
                else:
                    version = await persistence.transition(conn, run_id=run_id, dst=RunState.REJECTED,
                                                           performer=Performer.RECORD_DECISION, reason=Reason.REJECTED)
                    await persistence.append_event(conn, tenant_id=tenant_id, conversation_id=conversation_id,
                                                   run_id=run_id, type=EventType.RUN_REJECTED,
                                                   source=EventSource.APPLICATION,
                                                   payload={"proposal_id": str(proposal_id)})
                    status = RunState.REJECTED.value
        except psycopg.errors.UniqueViolation as exc:
            raise Conflict("VERSION_CONFLICT") from exc  # decisions.proposal_id UNIQUE: the first decision won
        return Decided(proposal_id, run_id, request.decision, status, version)

    async def events(self, tenant_id: UUID, run_id: UUID, *, after: int, limit: int) -> list[dict[str, Any]]:
        async with self.session.unit() as conn:
            cur = await conn.execute(
                "SELECT sequence, type, source, occurred_at, payload FROM app.events"
                " WHERE run_id = %s AND tenant_id = %s AND sequence > %s ORDER BY sequence LIMIT %s",
                (run_id, tenant_id, after, limit),
            )
            rows = await cur.fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 3: The application**

Create `api/src/ops_api/app.py`:

```python
"""api: admission, run snapshots, the proposal document and the independent decision (BUILD_SPEC §7, §9, §12).

Identity is the verified persona token's `sub` resolved against seeded memberships (never a display name, BUILD_SPEC
§9); the tenant and roles come from the membership, never from the request. Bodies are parsed with
`ops_core.contracts.load`, so a duplicate key or an authority field is a 422 before any handler logic runs. Browser
sessions, CSRF and Idempotency-Key are declared debt (T11/T12).
"""

# No `from __future__ import annotations` here: FastAPI resolves dependency annotations at import time, and a
# string annotation naming a local alias becomes a query parameter (measured in the round-1 review).
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Any, Protocol
from uuid import UUID, uuid4

import psycopg
from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError

from ops_api import store as st
from ops_core import persistence, settings
from ops_core.contracts import DecisionRequest, DuplicateKey, ErrorCode, MessageKind, MessageRequest, SafeError, load
from ops_core.tokens import Principal, TokenRejected, TokenVerifier

bearer = HTTPBearer(auto_error=False)  # the 401 body is ours (SafeError), not the SDK's


class ApiError(Exception):
    def __init__(self, status: int, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def safe(status: int, code: ErrorCode, message: str) -> JSONResponse:
    body = SafeError(code=code, message=message, retryable=status == 503, request_id=uuid4())
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else {}
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"), headers=headers)


def stamp(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Verifier(Protocol):  # the unit tests stub it
    @property
    def ready(self) -> bool: ...

    async def load_keys(self) -> None: ...

    async def verify_async(self, token: str) -> Principal: ...


class Identity:
    def __init__(self, principal: Principal, membership: st.Membership) -> None:
        self.subject = UUID(principal.subject)
        self.username = str(principal.claims.get("preferred_username", ""))
        self.tenant_id = membership.tenant_id
        self.roles = membership.roles

    def require(self, role: str) -> None:
        if role not in self.roles:
            raise ApiError(403, ErrorCode.FORBIDDEN, f"the {role} role is required")


def create_app(verifier: Verifier, store_factory: Callable[[], st.Store | Awaitable[st.Store]]) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        made = store_factory()
        app.state.store = await made if isinstance(made, Awaitable) else made
        if not verifier.ready:
            await verifier.load_keys()
        yield

    app = FastAPI(title="ops-api", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    issuer = settings.keycloak().issuer

    async def identity(request: Request,
                       creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> Identity:
        if creds is None:
            raise ApiError(401, ErrorCode.UNAUTHENTICATED, "a bearer token is required")
        try:
            principal = await verifier.verify_async(creds.credentials)
        except TokenRejected as exc:
            raise ApiError(401, ErrorCode.UNAUTHENTICATED, "token rejected") from exc
        membership = await request.app.state.store.membership(issuer, UUID(principal.subject))
        if membership is None:
            raise ApiError(403, ErrorCode.FORBIDDEN, "no active membership")
        return Identity(principal, membership)

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> Response:
        return safe(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, __: RequestValidationError) -> Response:
        return safe(422, ErrorCode.INVALID_INPUT, "request is not valid")

    async def body(request: Request, model: type[Any]) -> Any:
        try:
            return load(model, (await request.body()).decode("utf-8"))
        except (UnicodeDecodeError, DuplicateKey, ValidationError, ValueError) as exc:
            raise ApiError(422, ErrorCode.INVALID_INPUT, "request body is not valid") from exc

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "live"}

    @app.get("/health/ready")
    async def ready(request: Request) -> Response:
        store: st.Store = request.app.state.store
        if isinstance(store, st.DbStore):
            try:
                await store.session.read("SELECT 1", ())
            except (psycopg.Error, OSError):  # readiness reports a database failure as not ready
                return safe(503, ErrorCode.UNAVAILABLE, "database not reachable")
        return JSONResponse({"status": "ready"})

    @app.get("/api/v1/me")
    async def me(who: Annotated[Identity, Depends(identity)]) -> dict[str, Any]:
        return {"subject": str(who.subject), "tenant_id": str(who.tenant_id), "roles": sorted(who.roles),
                "username": who.username}

    @app.post("/api/v1/conversations", status_code=201)
    async def create_conversation(request: Request, who: Annotated[Identity, Depends(identity)]) -> dict[str, str]:
        cid = await request.app.state.store.create_conversation(who.tenant_id, who.subject)
        return {"conversation_id": str(cid)}

    @app.post("/api/v1/conversations/{conversation_id}/messages", status_code=202)
    async def post_message(conversation_id: UUID, request: Request,
                           who: Annotated[Identity, Depends(identity)]) -> dict[str, Any]:
        who.require("requester")
        message: MessageRequest = await body(request, MessageRequest)
        # T08 routes only `investigate` with a resolvable asset and interval; the admission router (T12) adds the rest.
        if message.kind is not MessageKind.INVESTIGATE or message.context is None or (
                message.context.asset_id is None or message.context.hours is None):
            raise ApiError(422, ErrorCode.INVALID_INPUT, "only an investigate request with asset_id and hours is routed")
        start_at, end_at = st.resolve_interval(message.context.hours, datetime.now(UTC))
        try:
            accepted = await request.app.state.store.admit(tenant_id=who.tenant_id, conversation_id=conversation_id,
                                                           requester=who.subject, request=message, start_at=start_at,
                                                           end_at=end_at)
        except st.NotFound as exc:
            raise ApiError(404, ErrorCode.NOT_FOUND, "no such conversation") from exc
        except st.Conflict as exc:
            raise ApiError(409, ErrorCode(exc.code), "the conversation already has an active run") from exc
        return {"conversation_id": str(accepted.conversation_id), "message_id": str(accepted.message_id),
                "run_id": str(accepted.run_id), "status": accepted.status, "state_version": accepted.state_version,
                "status_url": f"/api/v1/runs/{accepted.run_id}", "events_url": f"/api/v1/runs/{accepted.run_id}/events"}

    @app.get("/api/v1/runs/{run_id}")
    async def get_run(run_id: UUID, request: Request, who: Annotated[Identity, Depends(identity)]) -> dict[str, Any]:
        row = await request.app.state.store.run(who.tenant_id, run_id)
        if row is None:
            raise ApiError(404, ErrorCode.NOT_FOUND, "no such run")
        return {"run_id": str(row["run_id"]), "conversation_id": str(row["conversation_id"]), "status": row["state"],
                "state_version": row["state_version"],
                "active_proposal_id": str(row["active_proposal_id"]) if row["active_proposal_id"] else None,
                "asset_id": row["asset_id"], "start_at": stamp(row["start_at"]), "end_at": stamp(row["end_at"]),
                "created_at": stamp(row["created_at"])}

    @app.get("/api/v1/proposals/{proposal_id}")
    async def get_proposal(proposal_id: UUID, request: Request,
                           who: Annotated[Identity, Depends(identity)]) -> dict[str, Any]:
        row = await request.app.state.store.proposal(who.tenant_id, proposal_id)
        if row is None:
            raise ApiError(404, ErrorCode.NOT_FOUND, "no such proposal")
        return {"proposal_id": str(row["proposal_id"]), "run_id": str(row["run_id"]), "revision": row["revision"],
                "payload": row["payload"], "payload_sha256": row["payload_sha256"],
                "authored_by": [str(a) for a in row["authored_by"]], "expires_at": stamp(row["expires_at"])}

    @app.post("/api/v1/proposals/{proposal_id}/decisions")
    async def post_decision(proposal_id: UUID, request: Request,
                            who: Annotated[Identity, Depends(identity)]) -> dict[str, Any]:
        decision: DecisionRequest = await body(request, DecisionRequest)
        store: st.Store = request.app.state.store
        row = await store.proposal(who.tenant_id, proposal_id)
        if row is None:
            raise ApiError(404, ErrorCode.NOT_FOUND, "no such proposal")
        try:
            st.check_reviewer(st.Membership(who.tenant_id, who.roles), requester=row["requester"],
                              authored_by=list(row["authored_by"]), reviewer=who.subject)
            decided = await store.decide(tenant_id=who.tenant_id, proposal_id=proposal_id, reviewer=who.subject,
                                         request=decision)
        except st.Forbidden as exc:
            raise ApiError(403, ErrorCode.FORBIDDEN, "an independent current reviewer is required") from exc
        except st.NotFound as exc:
            raise ApiError(404, ErrorCode.NOT_FOUND, "no such proposal") from exc
        except st.Conflict as exc:
            raise ApiError(409, ErrorCode(exc.code), "the proposal is not the active, undecided revision") from exc
        return {"proposal_id": str(decided.proposal_id), "run_id": str(decided.run_id), "decision": decided.decision,
                "status": decided.status, "state_version": decided.state_version}

    @app.get("/api/v1/runs/{run_id}/events")
    async def get_events(run_id: UUID, request: Request, who: Annotated[Identity, Depends(identity)],
                         after: Annotated[int, Query(ge=0)] = 0,
                         limit: Annotated[int, Query(ge=1, le=500)] = 100) -> dict[str, Any]:
        store: st.Store = request.app.state.store
        if await store.run(who.tenant_id, run_id) is None:
            raise ApiError(404, ErrorCode.NOT_FOUND, "no such run")
        rows = await store.events(who.tenant_id, run_id, after=after, limit=limit)
        return {"events": [{**r, "occurred_at": stamp(r["occurred_at"])} if "occurred_at" in r else r for r in rows]}

    return app


def production_app() -> FastAPI:
    kc = settings.keycloak()
    verifier = TokenVerifier(issuer=kc.issuer, audience=settings.env("OPS_API_AUDIENCE", "ops-api"),
                             allowed_azp=frozenset({"ops-dev-direct"}), jwks_url=kc.jwks_url)

    async def make_store() -> st.Store:
        return st.DbStore(await persistence.connect(settings.app_postgres()))

    return create_app(verifier, make_store)
```

Create `api/src/ops_api/__main__.py`:

```python
"""`python -m ops_api`: serve on 127.0.0.1:OPS_API_PORT (default 8000)."""

import asyncio
import sys

import uvicorn
from starlette.types import ASGIApp

from ops_api.app import production_app
from ops_core.settings import env_int


def serve_app(app: ASGIApp, port: int) -> None:
    """Serve with uvicorn programmatically on a selector loop (ruling 23: `uvicorn.run` picks the Proactor loop on
    Windows and psycopg async refuses it)."""
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    if sys.platform == "win32":
        asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(server.serve())


if __name__ == "__main__":
    serve_app(production_app(), env_int("OPS_API_PORT", 8000))
```

Notes: the events endpoint serialises `payload` (jsonb → dict) and `occurred_at` as `…Z`; `source` and `type` are plain strings. `ErrorCode(exc.code)` relies on the store raising only codes in the enum (`SLOT_OCCUPIED`, `VERSION_CONFLICT`).

Run: `PYTHONUTF8=1 uv run python -m pytest tests/plan_d/test_api.py -q`
Expected: `6 passed`.

- [ ] **Step 4: README, full check, commit**

Append to `api/README.md`:

```markdown
## Runs (T08)

`python -m ops_api` on 127.0.0.1:8000 (`OPS_API_PORT`). Bearer persona tokens (`aud ops-api`, `azp ops-dev-direct`)
resolved to a tenant and roles through seeded memberships. Endpoints: `/api/v1/me`, `POST /api/v1/conversations`,
`POST /api/v1/conversations/{id}/messages` (investigate only; 202), `GET /api/v1/runs/{id}`, `GET /api/v1/proposals/{id}`,
`POST /api/v1/proposals/{id}/decisions` (independent reviewer, exact revision and hash, first decision wins),
`GET /api/v1/runs/{id}/events`. Sessions, CSRF and Idempotency-Key: T11/T12.
```

Run: `uv run ruff format api tests/plan_d/test_api.py && uv run ruff check --fix api tests/plan_d/test_api.py && PYTHONUTF8=1 uv run python scripts/check.py 2>&1 | tail -3`
Expected: `CHECK: GREEN`.

```bash
git add api tests/plan_d/test_api.py
git commit -m "feat(api): admission to a queued run, proposal document, independent decision with exact binding, events"
```

---
### Task 8: worker — poll, investigate (read tool → fake draft → freeze), execute (write tool)

**Files:**
- Create: `worker/src/ops_worker/drafting.py`, `worker/src/ops_worker/proposals.py`, `worker/src/ops_worker/mcp.py`, `worker/src/ops_worker/handlers.py`, `worker/src/ops_worker/main.py`, `worker/src/ops_worker/__main__.py`, `tests/plan_d/test_worker.py`, `tests/e2e/test_worker_live.py`
- Modify: `worker/README.md` ("## Runs (T08)")

**Interfaces:**
- Consumes: Task 2 persistence (`claim_job`, `finish_job`, `run_row`, `transition`, `append_event`, `mint_handle`, `connect`), Task 3 (`WorkloadTokenSource`), `ops_core.contracts` (`ModelDraft`, `ProposalPayload`, `SourceSnapshot`, `Proposal`), `ops_core.routing` (`RunManifest`, `ModelRoute`), `ops_core.canonical` (`canonical_json`, `canonical_sha256`), `ops_core.jobs` (`JobType`, `Server`), `ops_core.states`, `ops_core.outcomes`.
- Produces (`ops_worker.mcp`): `class TokenSource(Protocol)` (`async token() -> str`; `WorkloadTokenSource` satisfies it), `failure_leaf(exc) -> BaseException`, `TRANSPORT_FAILURES`, `HttpMcpCaller(token_source, *, connect_timeout=10.0)`. `ops_worker.drafting` — `@dataclass(frozen=True) DraftRequest(asset_id, text, start_at, end_at)`, `EvidenceItem(evidence_id, document_id, version, section, content_sha256, excerpt)`, `class DraftGenerator(Protocol)` with `async generate(request, evidence) -> ModelDraft`, `class FakeDraftGenerator`, `class ModelRouteError(ValueError)`, `make_generator(mode: str) -> DraftGenerator`, `PROMPT_VERSION = "incident-draft-v1"`, `WORKFLOW_VERSION = "investigation-v1"`. `ops_worker.proposals` — `@dataclass(frozen=True) Frozen(payload: ProposalPayload, canonical: bytes, sha256: str, manifest: RunManifest)`, `build_proposal(*, tenant_id, run_id, proposal_id, revision, asset_id, start_at, end_at, draft, evidence, corpus_version, now) -> Frozen`, `evidence_from_search(doc) -> list[EvidenceItem]`. `ops_worker.mcp` — `class McpCaller(Protocol)` with `async call(url, *, handle, tool, arguments) -> dict[str, Any]`, `class McpCallFailed(Exception)`, `class HttpMcpCaller(token_source)`. `ops_worker.handlers` — `@dataclass Deps(conn, mcp, generator, urls, worker_name)`, `async investigate(deps, job) -> None`, `async execute(deps, job) -> None`, `async handle(deps, job) -> None`. `ops_worker.main` — `async run_forever(deps, stop) -> None`, `health_app(deps) -> Starlette`, `main() -> None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/plan_d/test_worker.py`:

```python
"""The worker's model-free parts (AM-16 model router, BUILD_SPEC §6 canonical proposal, §12 draft validation).

Catches: a model mode other than `fake` silently falling back (R130), a fake draft that is not a valid ModelDraft, a
proposal whose hash is not the hash of the canonical bytes stored (the decision would bind to the wrong content),
evidence refs out of order (the contract requires sorted refs with matching snapshots), a search result accepted
without the fields the proposal needs, and a manifest claiming a digest for the fake route.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from ops_core.canonical import canonical_json, canonical_sha256, parse_json_strict
from ops_core.contracts import ModelDraft, Proposal
from ops_core.routing import ModelRoute
from ops_worker import drafting, proposals

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
REQ = drafting.DraftRequest(asset_id="A17", text="Investigate the alerts on A17 over the last 24 hours.",
                            start_at=NOW - timedelta(hours=24), end_at=NOW)
EV = [
    drafting.EvidenceItem("ALPHA-TRIAGE:v1:scope", "ALPHA-TRIAGE", "1", "scope", "b" * 64, "scope text"),
    drafting.EvidenceItem("ALPHA-INCIDENT:v2:review", "ALPHA-INCIDENT", "2", "review", "a" * 64, "review text"),
]


def test_model_router_has_one_route_and_no_fallback():
    assert isinstance(drafting.make_generator("fake"), drafting.FakeDraftGenerator)
    for mode in ("ollama", "qwen3:8b", "", "FAKE"):
        with pytest.raises(drafting.ModelRouteError):
            drafting.make_generator(mode)


@pytest.mark.asyncio
async def test_fake_draft_is_deterministic_and_valid():
    gen = drafting.FakeDraftGenerator()
    first = await gen.generate(REQ, EV)
    second = await gen.generate(REQ, EV)
    assert first == second and isinstance(first, ModelDraft) and first.kind == "proposal"
    assert first.evidence_refs == ["ALPHA-TRIAGE:v1:scope"]  # cites the first (highest-ranked) item
    assert any("fake" in lim.lower() for lim in first.limitations)  # BUILD_SPEC §1: never presented as a real model
    with pytest.raises(ValueError):
        await gen.generate(REQ, [])  # a proposal needs evidence; the handler maps this to INSUFFICIENT_EVIDENCE


@pytest.mark.asyncio
async def test_build_proposal_binds_hash_to_canonical_bytes():
    draft = await drafting.FakeDraftGenerator().generate(REQ, EV)
    frozen = proposals.build_proposal(tenant_id=UUID(int=1), run_id=UUID(int=2), proposal_id=UUID(int=3), revision=1,
                                      asset_id="A17", start_at=REQ.start_at, end_at=REQ.end_at, draft=draft,
                                      evidence=EV, corpus_version="handoff-1", now=NOW)
    assert frozen.canonical == canonical_json(frozen.payload.canonical_dict())
    assert frozen.sha256 == canonical_sha256(frozen.payload.canonical_dict())
    assert parse_json_strict(frozen.canonical.decode("utf-8")) == frozen.payload.canonical_dict()
    Proposal(canonicalization_version=1, payload=frozen.payload, payload_sha256=frozen.sha256, authored_by=[UUID(int=9)])
    assert frozen.payload.evidence_refs == ["ALPHA-TRIAGE:v1:scope"]
    assert [s.evidence_id for s in frozen.payload.source_snapshots] == ["ALPHA-TRIAGE:v1:scope"]
    assert frozen.payload.source_snapshots[0].content_sha256 == "b" * 64 and frozen.payload.source_snapshots[0].version == "1"
    assert frozen.payload.expires_at == NOW + timedelta(minutes=15)
    assert frozen.payload.prompt_version == "incident-draft-v1" and frozen.payload.workflow_version == "investigation-v1"
    assert frozen.manifest.model_route is ModelRoute.FAKE and frozen.manifest.model_digest is None
    assert frozen.manifest.corpus_version == "handoff-1" and frozen.manifest.retrieval_mode == "lexical"


@pytest.mark.asyncio
async def test_transport_failures_become_one_exception_type():
    from ops_worker.mcp import HttpMcpCaller, McpCallFailed, failure_leaf

    class NoToken:
        async def token(self) -> str:
            return "t"

    # Nobody listens on this port: the connection failure escapes the client's context inside an exception group.
    caller = HttpMcpCaller(NoToken(), connect_timeout=0.5)
    with pytest.raises(McpCallFailed):
        await caller.call("http://127.0.0.1:9/mcp", handle="h", tool="search_procedures", arguments={})
    inner = ValueError("leaf")
    assert failure_leaf(ExceptionGroup("outer", [ExceptionGroup("inner", [inner])])) is inner
    assert failure_leaf(inner) is inner


def test_evidence_from_search_requires_the_contract_fields():
    doc = {"status": "ok", "data": {"results": [
        {"evidence_id": "ALPHA-INCIDENT:v2:review", "document_id": "ALPHA-INCIDENT", "version": "2",
         "section": "review", "content_sha256": "a" * 64, "excerpt": "x", "effective_from": "2026-10-01T00:00:00Z",
         "retrieved_at": "2026-10-08T12:00:00Z"}], "retrieval_mode": "lexical", "corpus_version": "handoff-1"}}
    assert proposals.evidence_from_search(doc)[0].evidence_id == "ALPHA-INCIDENT:v2:review"
    assert proposals.evidence_from_search({"status": "ok", "data": {"results": [], "retrieval_mode": "lexical",
                                                                     "corpus_version": "x"}}) == []
    with pytest.raises(ValueError):
        proposals.evidence_from_search({"status": "error", "data": None})
    with pytest.raises(ValueError):
        proposals.evidence_from_search({"status": "ok", "data": {"results": [{"evidence_id": "x"}]}})
```

Run: `PYTHONUTF8=1 uv run python -m pytest tests/plan_d/test_worker.py -q`
Expected: an `ImportError` for `ops_worker.drafting` (the module does not exist yet).

- [ ] **Step 2: Drafting and proposals**

Create `worker/src/ops_worker/drafting.py`:

```python
"""The model router's one route for T08: a deterministic fake DraftGenerator (AM-16; BUILD_SPEC §12).

`DraftGenerator.generate` receives only the request and the evidence bundle — no credential, approval token, SQL or
tool (BUILD_SPEC §12) — and returns a `ModelDraft`, which the contract validates (no authority fields, bounded
lists). `make_generator` is the router: `fake` is the only route until T19 adds `qwen3:8b`; anything else is an
error, never a silent fallback (R130). The fake draft says it is fake in its limitations (BUILD_SPEC §1).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ops_core.contracts import ModelDraft
from ops_core.routing import ModelRoute

PROMPT_VERSION = "incident-draft-v1"
WORKFLOW_VERSION = "investigation-v1"


@dataclass(frozen=True)
class DraftRequest:
    asset_id: str
    text: str
    start_at: datetime
    end_at: datetime


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    document_id: str
    version: str
    section: str
    content_sha256: str
    excerpt: str


class DraftGenerator(Protocol):
    async def generate(self, request: DraftRequest, evidence: list[EvidenceItem]) -> ModelDraft: ...


class ModelRouteError(ValueError):
    """MODEL_MODE names a route this build does not have; the worker refuses to start rather than guess."""


class FakeDraftGenerator:
    async def generate(self, request: DraftRequest, evidence: list[EvidenceItem]) -> ModelDraft:
        if not evidence:
            raise ValueError("a proposal draft needs at least one evidence item")
        cited = evidence[0]  # the highest-ranked section; deterministic because the search is
        hours = int((request.end_at - request.start_at).total_seconds() // 3600)
        return ModelDraft(
            kind="proposal",
            title=f"Review synthetic warnings on {request.asset_id}",
            summary=(
                f"{request.asset_id} reported warnings in the {hours}-hour window ending "
                f"{request.end_at.isoformat().replace('+00:00', 'Z')}. Procedure {cited.document_id} v{cited.version} "
                f"({cited.section}) applies: {cited.excerpt[:200]}"
            ),
            evidence_refs=[cited.evidence_id],
            assumptions=["Synthetic fixture data; no live equipment was observed."],
            limitations=[f"Drafted by the fake model route ({PROMPT_VERSION}); the control path, not answer quality."],
        )


def make_generator(mode: str) -> DraftGenerator:
    if mode == ModelRoute.FAKE.value:
        return FakeDraftGenerator()
    raise ModelRouteError(f"MODEL_MODE={mode!r} is not a route of this build (only 'fake' until T19)")
```

Create `worker/src/ops_worker/proposals.py`:

```python
"""From a validated draft to the frozen proposal: the exact bytes the reviewer decides on (BUILD_SPEC §6, SA:453).

The payload is built once, canonicalised once, hashed once; the same bytes are stored, shown and sent. Evidence refs
are sorted and the snapshots follow them, as `ProposalPayload` demands, so two drafts citing the same sections in a
different order freeze to the same bytes. The run manifest records the model route (SA:379) and is validated here even
though T19 is the task that stores it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from ops_core.canonical import canonical_json, canonical_sha256
from ops_core.contracts import ModelDraft, ProposalPayload, SourceSnapshot
from ops_core.routing import ModelRoute, RunManifest
from ops_worker.drafting import PROMPT_VERSION, WORKFLOW_VERSION, EvidenceItem

EXPIRY = timedelta(minutes=15)  # BUILD_SPEC §12 default; enforced by T21


@dataclass(frozen=True)
class Frozen:
    payload: ProposalPayload
    canonical: bytes
    sha256: str
    manifest: RunManifest


def evidence_from_search(doc: dict[str, Any]) -> list[EvidenceItem]:
    """The tool-result envelope of `search_procedures` → evidence items; anything short of the contract is an error."""
    if doc.get("status") != "ok" or not isinstance(doc.get("data"), dict):
        raise ValueError("search_procedures did not return data")
    items: list[EvidenceItem] = []
    for row in doc["data"]["results"]:
        try:
            items.append(EvidenceItem(row["evidence_id"], row["document_id"], row["version"], row["section"],
                                      row["content_sha256"], row["excerpt"]))
        except (KeyError, TypeError) as exc:
            raise ValueError("search result row is missing a contract field") from exc
    return items


def build_proposal(
    *,
    tenant_id: UUID,
    run_id: UUID,
    proposal_id: UUID,
    revision: int,
    asset_id: str,
    start_at: datetime,
    end_at: datetime,
    draft: ModelDraft,
    evidence: list[EvidenceItem],
    corpus_version: str,
    now: datetime,
) -> Frozen:
    by_id = {e.evidence_id: e for e in evidence}
    refs = sorted(draft.evidence_refs)
    payload = ProposalPayload(
        tenant_id=tenant_id,
        run_id=run_id,
        proposal_id=proposal_id,
        revision=revision,
        action="create_incident",
        destination="synthetic-incidents",
        asset_id=asset_id,
        start_at=start_at,
        end_at=end_at,
        title=draft.title,
        summary=draft.summary,
        evidence_refs=refs,
        source_snapshots=[SourceSnapshot(evidence_id=r, content_sha256=by_id[r].content_sha256, version=by_id[r].version)
                          for r in refs],
        assumptions=list(draft.assumptions),
        limitations=list(draft.limitations),
        workflow_version=WORKFLOW_VERSION,
        prompt_version=PROMPT_VERSION,
        expires_at=now + EXPIRY,
    )
    doc = payload.canonical_dict()
    manifest = RunManifest(run_id=run_id, model_route=ModelRoute.FAKE, model_digest=None, prompt_version=PROMPT_VERSION,
                           corpus_version=corpus_version, retrieval_mode="lexical")
    return Frozen(payload=payload, canonical=canonical_json(doc), sha256=canonical_sha256(doc), manifest=manifest)
```

Run: `PYTHONUTF8=1 uv run python -m pytest tests/plan_d/test_worker.py -q`
Expected: `5 passed` (the transport test takes about a second on Windows: a closed loopback port times out rather than refusing).

- [ ] **Step 3: The MCP client, the handlers and the process**

Create `worker/src/ops_worker/mcp.py`:

```python
"""The worker's MCP client: one workload token, two servers, one handle per call (BUILD_SPEC §9, ADR-0003).

The token and the handle travel as HTTP headers on an httpx2 client the SDK transport uses (measured in the spike);
the handle is never a tool argument. A refusal at the transport (401) reaches the caller as the SDK's MCPError, and a
tool-level refusal as an error envelope; both become McpCallFailed so a handler records nothing it did not observe.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx2
from mcp import Client, MCPError
from mcp.client.streamable_http import streamable_http_client


class McpCallFailed(Exception):
    pass


def failure_leaf(exc: BaseException) -> BaseException:
    """The first leaf of a possibly nested exception group. An error that escapes the client's context manager
    (a refused token, a connection failure) arrives wrapped in anyio task-group `ExceptionGroup`s (measured in the
    Plan D spike and both dry runs); a handler must see the transport failure, not the wrapper, or the run is never
    failed and its conversation slot stays held."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


TRANSPORT_FAILURES = (MCPError, httpx2.HTTPError, OSError)


class TokenSource(Protocol):
    async def token(self) -> str: ...


class McpCaller(Protocol):
    async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


class HttpMcpCaller:
    def __init__(self, token_source: TokenSource, *, connect_timeout: float = 10.0) -> None:
        self._tokens = token_source
        self._timeout = httpx2.Timeout(connect_timeout, read=60.0)

    async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {await self._tokens.token()}", "X-Ops-Invocation": handle}
        try:
            async with (
                httpx2.AsyncClient(headers=headers, timeout=self._timeout) as http,
                Client(streamable_http_client(url, http_client=http), mode="2026-07-28") as client,
            ):
                result = await client.call_tool(tool, arguments)
        except TRANSPORT_FAILURES as exc:
            raise McpCallFailed(f"{tool}: transport or protocol failure") from exc
        except BaseExceptionGroup as group:
            leaf = failure_leaf(group)
            if isinstance(leaf, TRANSPORT_FAILURES):
                raise McpCallFailed(f"{tool}: transport or protocol failure") from leaf
            raise
        if result.is_error or not isinstance(result.structured_content, dict):
            raise McpCallFailed(f"{tool}: the server rejected the call")
        return result.structured_content
```

Create `worker/src/ops_worker/handlers.py`:

```python
"""Job handlers (AM-20.4 job types; AM-10 states): every state change goes through `persistence.transition` with the
performer the spec names, and every network call happens outside a transaction (BUILD_SPEC §11).

`investigate`: QUEUED → RETRIEVING → (read tool) → DRAFTING → fake draft → freeze → AWAITING_APPROVAL. `execute`: mint
a write handle and call `create_incident`; mcp-write performs the grant, the dispatch and the outcome, so the worker
only closes the job. No lease, fence or heartbeat (debt → T13), no LangGraph (→ T20).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from ops_core import persistence
from ops_core.jobs import JobType, Server
from ops_core.outcomes import EventSource, EventType
from ops_core.settings import Urls
from ops_core.states import Intent, Performer, RunState, freeze_allowed
from ops_worker import proposals
from ops_worker.drafting import DraftGenerator, DraftRequest
from ops_worker.mcp import McpCallFailed, McpCaller

log = logging.getLogger("ops_worker")
QUERY_CHARS = 500  # schemas/tools/search_procedures.input.schema.json maxLength


@dataclass
class Deps:
    conn: persistence.Conn
    mcp: McpCaller
    generator: DraftGenerator
    urls: Urls
    worker_name: str


async def _event(deps: Deps, run: dict[str, Any], type: EventType, payload: dict[str, Any],
                 source: EventSource = EventSource.APPLICATION) -> None:
    async with deps.conn.transaction():
        await persistence.append_event(deps.conn, tenant_id=run["tenant_id"], conversation_id=run["conversation_id"],
                                       run_id=run["run_id"], type=type, source=source, payload=payload)


async def _fail(deps: Deps, run: dict[str, Any], dst: RunState, type: EventType, message: str) -> None:
    async with deps.conn.transaction():
        await persistence.transition(deps.conn, run_id=run["run_id"], dst=dst, performer=Performer.TRANSITION_RUN)
        await persistence.append_event(deps.conn, tenant_id=run["tenant_id"], conversation_id=run["conversation_id"],
                                       run_id=run["run_id"], type=type, source=EventSource.APPLICATION,
                                       payload={"message": message})


async def investigate(deps: Deps, job: dict[str, Any]) -> None:
    async with deps.conn.transaction():
        run = dict(await persistence.run_row(deps.conn, job["run_id"], lock=True))
        if run["state"] != RunState.QUEUED.value:
            log.info("investigate job %s: run already %s", job["id"], run["state"])
            return
        cur = await deps.conn.execute("SELECT text FROM app.messages WHERE message_id = %s", (run["message_id"],))
        message = await cur.fetchone()
        if message is None:
            raise persistence.NotFound("message not found")
        text = str(message["text"])
        await persistence.transition(deps.conn, run_id=run["run_id"], dst=RunState.RETRIEVING,
                                     performer=Performer.TRANSITION_RUN)
        handle = await persistence.mint_handle(deps.conn, run_id=run["run_id"], job_id=job["id"], server=Server.READ,
                                               azp="ops-worker")
    await _event(deps, run, EventType.TOOL_STARTED, {"message": "search_procedures"})
    try:
        # The tool input caps `query` at 500 characters (schemas/tools); the message itself may be 4,000.
        doc = await deps.mcp.call(deps.urls.mcp_read, handle=handle, tool="search_procedures",
                                  arguments={"query": text[:QUERY_CHARS], "limit": 3, "mode": "lexical"})
        evidence = proposals.evidence_from_search(doc)
    except (McpCallFailed, ValueError) as exc:
        log.warning("investigate job %s: retrieval failed: %s", job["id"], exc)
        await _fail(deps, run, RunState.FAILED, EventType.RUN_FAILED, "retrieval failed")
        return
    await _event(deps, run, EventType.TOOL_COMPLETED, {"message": "search_procedures"})
    if not evidence:
        await _fail(deps, run, RunState.INSUFFICIENT_EVIDENCE, EventType.RUN_INSUFFICIENT_EVIDENCE,
                    "no procedure section matched")
        return
    async with deps.conn.transaction():
        await persistence.transition(deps.conn, run_id=run["run_id"], dst=RunState.DRAFTING,
                                     performer=Performer.TRANSITION_RUN)
    request = DraftRequest(asset_id=run["asset_id"], text=text, start_at=run["start_at"], end_at=run["end_at"])
    draft = await deps.generator.generate(request, evidence)
    freeze_allowed(Intent(run["intent"]))  # an answer_only run never freezes a proposal (SA:453)
    now = datetime.now(UTC).replace(microsecond=0)
    proposal_id, draft_id = uuid4(), uuid4()
    frozen = proposals.build_proposal(tenant_id=run["tenant_id"], run_id=run["run_id"], proposal_id=proposal_id,
                                      revision=1, asset_id=run["asset_id"], start_at=run["start_at"],
                                      end_at=run["end_at"], draft=draft, evidence=evidence,
                                      corpus_version=str(doc["data"]["corpus_version"]), now=now)
    async with deps.conn.transaction():
        # drafts.draft_sha256 is the hash freeze_proposal (T09) recomputes and compares: the payload's hash.
        await deps.conn.execute(
            "INSERT INTO app.drafts (id, run_id, draft_sha256, validated, kind) VALUES (%s, %s, %s, true, %s)",
            (draft_id, run["run_id"], frozen.sha256, draft.kind),
        )
        await deps.conn.execute(
            "INSERT INTO app.proposals (proposal_id, tenant_id, run_id, revision, draft_id, payload, payload_canonical,"
            " payload_sha256, canonicalization_version, authored_by, expires_at)"
            " VALUES (%s, %s, %s, 1, %s, %s, %s, %s, 1, %s, %s)",
            (proposal_id, run["tenant_id"], run["run_id"], draft_id, Jsonb(frozen.payload.canonical_dict()),
             frozen.canonical, frozen.sha256, [run["requester"]], frozen.payload.expires_at),
        )
        await deps.conn.execute("UPDATE app.runs SET active_proposal_id = %s WHERE run_id = %s",
                                (proposal_id, run["run_id"]))
        await persistence.transition(deps.conn, run_id=run["run_id"], dst=RunState.AWAITING_APPROVAL,
                                     performer=Performer.FREEZE_PROPOSAL)
        await persistence.append_event(
            deps.conn, tenant_id=run["tenant_id"], conversation_id=run["conversation_id"], run_id=run["run_id"],
            type=EventType.EXPLANATION_READY, source=EventSource.MODEL_SUMMARY,
            payload={"message": f"Drafted by model route {frozen.manifest.model_route.value} "
                                f"(prompt {frozen.manifest.prompt_version}).",
                     "evidence_refs": list(frozen.payload.evidence_refs)},
        )
        await persistence.append_event(deps.conn, tenant_id=run["tenant_id"], conversation_id=run["conversation_id"],
                                       run_id=run["run_id"], type=EventType.PROPOSAL_READY,
                                       source=EventSource.APPLICATION, payload={"proposal_id": str(proposal_id)})


async def execute(deps: Deps, job: dict[str, Any]) -> None:
    async with deps.conn.transaction():
        run = dict(await persistence.run_row(deps.conn, job["run_id"], lock=True))
        if run["state"] != RunState.APPROVED.value:
            log.info("execute job %s: run is %s, nothing to dispatch", job["id"], run["state"])
            return
        proposal_id: UUID = run["active_proposal_id"]
        handle = await persistence.mint_handle(deps.conn, run_id=run["run_id"], job_id=job["id"], server=Server.WRITE,
                                               azp="ops-worker")
    try:
        doc = await deps.mcp.call(deps.urls.mcp_write, handle=handle, tool="create_incident",
                                  arguments={"proposal_id": str(proposal_id)})
    except McpCallFailed as exc:
        # mcp-write owns the grant and the outcome; if the call never reached it nothing happened, and if it did the
        # outcome is recorded there. The worker records nothing it did not observe (BUILD_SPEC §1). TODO(T22).
        log.warning("execute job %s: %s", job["id"], exc)
        return
    data = doc.get("data") or {}
    log.info("execute job %s: %s %s", job["id"], doc.get("status"), data.get("status"))


async def handle(deps: Deps, job: dict[str, Any]) -> None:
    kind = JobType(job["type"])
    if kind is JobType.INVESTIGATE:
        await investigate(deps, job)
    elif kind is JobType.EXECUTE:
        await execute(deps, job)
    else:
        log.info("job %s of type %s is not handled by the walking skeleton", job["id"], kind.value)
    async with deps.conn.transaction():
        await persistence.finish_job(deps.conn, job["id"])
```

Create `worker/src/ops_worker/main.py`:

```python
"""The worker process: a polling loop beside a health server, one connection, SelectorEventLoop on Windows
(psycopg async refuses the Proactor loop; measured in the Plan D spike)."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import sys
from collections.abc import Callable

import psycopg
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ops_core import persistence, settings
from ops_core.tokens import WorkloadTokenSource
from ops_worker import handlers
from ops_worker.drafting import make_generator
from ops_worker.mcp import HttpMcpCaller

POLL_SECONDS = 0.5
log = logging.getLogger("ops_worker")


async def run_forever(deps: handlers.Deps, stop: asyncio.Event) -> None:
    """Claim, handle, repeat. A failed handler is logged and its job stays claimed (T13 reclaims); a broken
    connection ends the loop, and readiness follows it (see health_app)."""
    while not stop.is_set():
        try:
            async with deps.conn.transaction():
                job = await persistence.claim_job(deps.conn, worker_name=deps.worker_name)
            if job is not None:
                await handlers.handle(deps, dict(job))
                continue
        except psycopg.OperationalError:
            log.exception("database connection lost; the poll loop stops and readiness turns 503")
            raise
        except Exception:  # a crashed handler leaves the job claimed for T13's reclaim; the loop lives on
            log.exception("poll iteration failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=POLL_SECONDS)
        except TimeoutError:
            pass


def health_app(probe: persistence.Conn, polling_alive: Callable[[], bool]) -> Starlette:
    """Readiness on its own connection and only while the poll loop runs: sharing the loop's connection let a health
    call wedge it idle-in-transaction, and a dead loop behind a 200 is the same lie (round-1 and round-2 reviews)."""

    async def live(_: Request) -> JSONResponse:
        return JSONResponse({"status": "live"})

    async def ready(_: Request) -> JSONResponse:
        if not polling_alive():
            return JSONResponse({"status": "not ready", "reason": "poll loop stopped"}, status_code=503)
        try:
            await probe.execute("SELECT 1")  # autocommit: no transaction is left open
        except (psycopg.Error, OSError):
            return JSONResponse({"status": "not ready"}, status_code=503)
        return JSONResponse({"status": "ready"})

    return Starlette(routes=[Route("/health/live", live), Route("/health/ready", ready)])


async def _main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    generator = make_generator(settings.env("MODEL_MODE"))  # unset or any other route: refuse to start (R130)
    kc = settings.keycloak()
    tokens = WorkloadTokenSource(token_url=kc.token_url, client_id="ops-worker",
                                 client_secret=settings.read_secret("kc_client_secret_ops_worker"))
    conn = await persistence.connect(settings.app_postgres())
    probe = await persistence.connect(settings.app_postgres())  # the health server's own connection (see health_app)
    deps = handlers.Deps(conn=conn, mcp=HttpMcpCaller(tokens), generator=generator, urls=settings.urls(),
                         worker_name=f"{socket.gethostname()}:{os.getpid()}")
    stop = asyncio.Event()
    polling = asyncio.create_task(run_forever(deps, stop), name="poll-loop")
    server = uvicorn.Server(uvicorn.Config(health_app(probe, lambda: not polling.done()), host="127.0.0.1",
                                           port=settings.env_int("OPS_WORKER_HEALTH_PORT", 8070), log_level="warning"))
    serving = asyncio.create_task(server.serve(), name="health-server")
    try:
        # Whichever ends first ends the process: uvicorn on SIGINT/SIGTERM, the poll loop on a lost connection.
        await asyncio.wait({serving, polling}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        stop.set()
        server.should_exit = True
        await asyncio.gather(serving, polling, return_exceptions=True)
        await conn.close()
        await probe.close()


def main() -> None:
    if sys.platform == "win32":
        asyncio.run(_main(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(_main())
```

Create `worker/src/ops_worker/__main__.py`:

```python
"""`python -m ops_worker`: poll jobs; health on 127.0.0.1:OPS_WORKER_HEALTH_PORT (default 8070)."""

from ops_worker.main import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Live: both handlers against the real database with a fake MCP**

Create `tests/e2e/test_worker_live.py`:

```python
"""The two handlers against the real database with a scripted MCP caller (OPS_LIVE=1): the state path, the frozen
proposal's bytes and hash, the event order, and the execute job's handle. The real MCP transport is proved in Task 5's
and Task 9's tests."""

from typing import Any
from uuid import UUID

import pytest
from ops_core import persistence, settings
from ops_core.canonical import canonical_json, canonical_sha256
from ops_core.jobs import JobType, Server, Tool
from ops_core.states import Performer, RunState
from ops_worker import handlers
from ops_worker.drafting import FakeDraftGenerator
from tests.e2e.test_migrations_and_persistence import new_run

pytestmark = pytest.mark.asyncio

SEARCH = {"status": "ok", "data": {"results": [
    {"evidence_id": "ALPHA-INCIDENT:v2:review", "document_id": "ALPHA-INCIDENT", "version": "2", "section": "review",
     "content_sha256": "62a90906c7bb706ae8a968eb0f7102f76b05d2c3be911c182d528a1fd25ef008", "excerpt": "text",
     "effective_from": "2026-10-01T00:00:00Z", "retrieved_at": "2026-10-08T12:00:00Z"}],
    "retrieval_mode": "lexical", "corpus_version": "handoff-1"}}


class ScriptedMcp:
    def __init__(self, conn: persistence.Conn) -> None:
        self.conn = conn
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((url, tool, arguments))
        server = Server.READ if tool == "search_procedures" else Server.WRITE
        await persistence.resolve_handle(self.conn, handle=handle, server=server, azp="ops-worker", tool=Tool(tool))
        if tool == "search_procedures":
            return SEARCH
        return {"status": "ok", "data": {"status": "SUCCEEDED", "action_id": str(UUID(int=1)), "payload_sha256": "x",
                                         "receipt": None, "tombstone": None, "reason": None}}


async def own_job(conn: persistence.Conn, run, job_type: str) -> dict:
    """The run's own job, claimed by this test (claim_job takes the oldest available job of any run, so a leftover
    from another test would be claimed instead)."""
    cur = await conn.execute("UPDATE app.jobs SET claimed_by = 't', claimed_at = now(), attempts = attempts + 1"
                             " WHERE run_id = %s AND type = %s AND done_at IS NULL RETURNING *", (run, job_type))
    row = await cur.fetchone()
    assert row is not None, (run, job_type)
    return dict(row)


async def test_investigate_then_execute(app_conn: persistence.Conn) -> None:
    mcp = ScriptedMcp(app_conn)
    deps = handlers.Deps(conn=app_conn, mcp=mcp, generator=FakeDraftGenerator(), urls=settings.urls(), worker_name="t")
    async with app_conn.transaction(force_rollback=True):  # everything below rolls back; nothing else sees it
        await _investigate_then_execute(app_conn, deps, mcp)


async def _investigate_then_execute(app_conn: persistence.Conn, deps: handlers.Deps, mcp: ScriptedMcp) -> None:
    _, _, run = await new_run(app_conn)
    job = await own_job(app_conn, run, "investigate")
    await handlers.handle(deps, job)
    row = await persistence.run_row(app_conn, run)
    assert row["state"] == "AWAITING_APPROVAL" and row["active_proposal_id"] is not None
    cur = await app_conn.execute("SELECT * FROM app.proposals WHERE proposal_id = %s", (row["active_proposal_id"],))
    proposal = await cur.fetchone()
    assert canonical_json(proposal["payload"]) == bytes(proposal["payload_canonical"])
    assert canonical_sha256(proposal["payload"]) == proposal["payload_sha256"]
    assert proposal["payload"]["evidence_refs"] == ["ALPHA-INCIDENT:v2:review"]
    cur = await app_conn.execute("SELECT type, source FROM app.events WHERE run_id = %s ORDER BY sequence", (run,))
    assert [tuple(r.values()) for r in await cur.fetchall()] == [
        ("tool.started", "application"), ("tool.completed", "application"), ("explanation.ready", "model_summary"),
        ("proposal.ready", "application")]
    cur = await app_conn.execute("SELECT seq, to_state FROM app.run_state_history WHERE run_id = %s ORDER BY seq", (run,))
    assert [r["to_state"] for r in await cur.fetchall()] == ["QUEUED", "RETRIEVING", "DRAFTING", "AWAITING_APPROVAL"]
    # Approve directly (the API does this in Task 7) and run the execute job.
    await app_conn.execute("INSERT INTO app.decisions (decision_id, proposal_id, reviewer, decision,"
                           " expected_payload_sha256) VALUES (gen_random_uuid(), %s, %s, 'approve', %s)",
                           (proposal["proposal_id"], UUID("03f7eb09-e18d-5f33-bf75-12c57d5aaa54"),
                            proposal["payload_sha256"]))
    await persistence.transition(app_conn, run_id=run, dst=RunState.APPROVED, performer=Performer.RECORD_DECISION)
    await persistence.insert_job(app_conn, job_type=JobType.EXECUTE, run_id=run, proposal_id=proposal["proposal_id"])
    job = await own_job(app_conn, run, "execute")
    await handlers.handle(deps, job)
    assert [c[1] for c in mcp.calls] == ["search_procedures", "create_incident"]
    assert mcp.calls[1][2] == {"proposal_id": str(proposal["proposal_id"])}
    cur = await app_conn.execute("SELECT done_at IS NOT NULL AS done FROM app.jobs WHERE id = %s", (job["id"],))
    assert (await cur.fetchone())["done"]
```

(`gen_random_uuid()` is built into PostgreSQL 13+.) The scripted caller resolves the real handle in the database, so the server binding and allowlist are exercised even without the transport. The handlers' own `transaction()` blocks nest inside the test's `force_rollback` block as savepoints, so the whole test rolls back at the end.

Run: `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_worker_live.py -q`
Expected: `1 passed`.

- [ ] **Step 5: README, full check, commit**

Append to `worker/README.md`:

```markdown
## Runs (T08)

`python -m ops_worker`: polls `app.jobs` every 0.5 s (`FOR UPDATE SKIP LOCKED`), health on 127.0.0.1:8070
(`OPS_WORKER_HEALTH_PORT`). `investigate`: read tool on mcp-read → fake draft (`MODEL_MODE=fake`, the only route until
T19) → frozen proposal → AWAITING_APPROVAL. `execute`: `create_incident` on mcp-write. One `ops-worker` token carries
both MCP audiences; one handle per call. Lease, fence, heartbeat and LangGraph: T13/T20.
```

Run: `uv run ruff format worker tests/plan_d/test_worker.py tests/e2e/test_worker_live.py && uv run ruff check --fix worker tests/plan_d/test_worker.py tests/e2e/test_worker_live.py && PYTHONUTF8=1 uv run python scripts/check.py 2>&1 | tail -3`
Expected: `CHECK: GREEN`.

```bash
git add worker tests/plan_d/test_worker.py tests/e2e/test_worker_live.py
git commit -m "feat(worker): polling loop with investigate (read tool, fake draft, freeze) and execute (write tool) handlers"
```

---
### Task 9: `skeleton.py up/down`, the R105 end-to-end proof, evidence, handoff documents

**Files:**
- Modify: `scripts/skeleton.py` (`up`, `down`, `status`, the `Skeleton` class), `tests/plan_b/test_evidence.py` (the no-secret rule covers `reports/skeleton/` too), `handoff/tasks.json` (T08 → `DONE`), `handoff/BUILD_BACKLOG.md`, `handoff/acceptance-matrix.json` (R105), `STATUS.md`, `SESSION_STATE.md`, `docs/PROJECT_HISTORY.md` (new §19; the closing section becomes §20), `README.md` (status line), `docs/runbooks/dev-topology.md` (host-process ports)
- Create: `tests/e2e/test_r105_walking_skeleton.py` (with its module-scoped `skeleton` fixture), `tests/plan_d/test_skeleton_evidence.py`, `reports/skeleton/r105-walking-skeleton.txt` (written by the test; committed as evidence), `docs/runbooks/walking-skeleton.md`

**Interfaces:**
- Consumes: everything above; `tests/plan_b/live/kc.py` for persona tokens.
- Produces: `scripts/skeleton.py` — `PROCESSES: tuple[Process, ...]` (`Process(name, module, port, health_url)`), `class Skeleton` with `start(timeout=90) -> None`, `stop() -> None`, module constant `LOGS = ROOT / "runtime" / "skeleton"`; CLI `up` (start, write `runtime/skeleton/pids.json`), `down` (terminate the pids), `status` (health of each). The `skeleton` fixture lives in the R105 test module with `scope="module"`, so the five processes (the worker in particular) are down again before `test_worker_live` runs.

- [ ] **Step 1: The process harness**

Extend `scripts/skeleton.py` (keep `migrate`; add):

```python
import json
import signal
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import IO


@dataclass(frozen=True)
class Process:
    name: str
    module: str
    port: int

    @property
    def health_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/health/ready"


PROCESSES: tuple[Process, ...] = (
    Process("incident-sim", "ops_incident_sim", 8090),
    Process("mcp-read", "ops_mcp_read", 8081),
    Process("mcp-write", "ops_mcp_write", 8082),
    Process("api", "ops_api", 8000),
    Process("worker", "ops_worker", 8070),
)
LOGS = ROOT / "runtime" / "skeleton"  # git-ignored (runtime/)


def process_environment() -> dict[str, str]:
    export_environment(load_dotenv(ROOT / ".env"))
    env = dict(os.environ)
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("MODEL_MODE", "fake")
    env.setdefault("OPS_API_PORT", "8000")
    env.setdefault("OPS_WORKER_HEALTH_PORT", "8070")
    env.setdefault("OPS_MCP_READ_PORT", "8081")
    env.setdefault("OPS_MCP_WRITE_PORT", "8082")
    env.setdefault("OPS_INCIDENT_SIM_PORT", "8090")
    return env


def healthy(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:  # loopback health URL only
            return bool(response.status == 200)
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        return False


class Skeleton:
    """The five host processes as children of this one; logs under runtime/skeleton/ (never committed)."""

    def __init__(self) -> None:
        self.children: dict[str, subprocess.Popen[bytes]] = {}
        self.logs: list[IO[bytes]] = []

    def start(self, timeout: float = 90.0) -> None:
        LOGS.mkdir(parents=True, exist_ok=True)
        env = process_environment()
        for proc in PROCESSES:
            log = open(LOGS / f"{proc.name}.log", "ab")  # noqa: SIM115  -- closed in stop(); the child writes to it
            self.logs.append(log)
            self.children[proc.name] = subprocess.Popen([sys.executable, "-m", proc.module], env=env, stdout=log,
                                                        stderr=subprocess.STDOUT, cwd=ROOT)
        deadline = time.monotonic() + timeout
        pending = {p.name: p for p in PROCESSES}
        while pending and time.monotonic() < deadline:
            for name, proc in list(pending.items()):
                if self.children[name].poll() is not None:
                    self.stop()
                    raise RuntimeError(f"{name} exited early; see runtime/skeleton/{name}.log")
                if healthy(proc.health_url):
                    del pending[name]
            time.sleep(0.25)
        if pending:
            self.stop()
            raise RuntimeError(f"not ready in {timeout}s: {sorted(pending)}; see runtime/skeleton/*.log")

    def stop(self) -> None:
        for child in self.children.values():
            if child.poll() is None:
                child.terminate()  # TerminateProcess on Windows: no lifespan shutdown, which the skeleton tolerates
        for child in self.children.values():
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
            if child.stdout is not None:
                child.stdout.close()
        for handle in self.logs:
            handle.close()
        self.logs.clear()
        self.children.clear()


def up() -> int:
    skeleton = Skeleton()
    skeleton.start()
    (LOGS / "pids.json").write_text(json.dumps({n: c.pid for n, c in skeleton.children.items()}), encoding="utf-8")
    print("UP: " + ", ".join(f"{p.name}:{p.port}" for p in PROCESSES))
    return 0


def down() -> int:
    pids_path = LOGS / "pids.json"
    if not pids_path.exists():
        print("DOWN: nothing recorded")
        return 0
    for name, pid in json.loads(pids_path.read_text(encoding="utf-8")).items():
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        print(f"DOWN: {name} ({pid})")
    pids_path.unlink()
    return 0


def status() -> int:
    for proc in PROCESSES:
        print(f"{proc.name:13s} {'ready' if healthy(proc.health_url) else 'down':6s} 127.0.0.1:{proc.port}")
    return 0


# `status` reads each process's own /health/ready, which for the worker turns 503 when its poll loop has stopped.
```

and the `main` dispatch: `{"migrate": migrate, "up": up, "down": down, "status": status}`; these imports (`json`, `signal`, `subprocess`, `time`, `urllib`, `IO`) join the module's import block at the top of the file, not mid-file. On Windows `terminate()` is `TerminateProcess` with no graceful shutdown, which the skeleton tolerates. Under uv, `sys.executable` is the venv launcher and the real interpreter is its child; the launcher's job object ends the child when the launcher dies (verified in the round-1 dry run: every port was free after `down`). `up` leaves the children running after the script exits; `down` sends SIGTERM by pid (`os.kill` with `SIGTERM` terminates on Windows) and `status` shows every port down afterwards.

- [ ] **Step 2: The end-to-end test**

Create `tests/e2e/test_r105_walking_skeleton.py`:

```python
"""R105: one run crosses every service over real HTTP with real tokens and ends SUCCEEDED (OPS_LIVE=1).

api (alex) → job → worker → mcp-read (search_procedures) → fake draft → frozen proposal → decision by sam → execute job
→ worker → mcp-write (create_incident) → incident-sim → receipt → action.confirmed (source=destination). Also the
refusals the skeleton must already make: the requester deciding, a stale hash, a second decision, a workload token at
the API, a persona token at the destination. Writes redacted evidence to reports/skeleton/ (no token, no secret).
"""

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx2
import pytest
from mcp import Client, MCPError
from mcp.client.streamable_http import streamable_http_client
from ops_core import persistence, settings
from ops_core.jobs import Server
from ops_worker.mcp import failure_leaf
from scripts.skeleton import Skeleton
from tests.plan_b.live import kc

API = "http://127.0.0.1:8000"
EVIDENCE = Path("reports/skeleton/r105-walking-skeleton.txt")
EXPECTED_EVENTS = [
    ("run.accepted", "application"), ("tool.started", "application"), ("tool.completed", "application"),
    ("explanation.ready", "model_summary"), ("proposal.ready", "application"), ("approval.recorded", "application"),
    ("action.granted", "application"), ("action.dispatched", "application"), ("action.confirmed", "destination"),
]


@pytest.fixture(scope="module")
def skeleton(migrated: None) -> Iterator[Skeleton]:
    """Module scope on purpose: the skeleton worker must be down before test_worker_live claims jobs itself."""
    sk = Skeleton()
    sk.start()
    try:
        yield sk
    finally:
        sk.stop()


async def mcp_call(url: str, token: str, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """One tool call over the real transport; None when the transport refused the token (an MCPError, which may
    arrive wrapped in an anyio exception group — see ops_worker.mcp.failure_leaf)."""
    headers = {"Authorization": f"Bearer {token}", "X-Ops-Invocation": handle}
    try:
        async with (
            httpx2.AsyncClient(headers=headers) as hc,
            Client(streamable_http_client(url, http_client=hc), mode="2026-07-28") as client,
        ):
            res = await client.call_tool(tool, arguments)
    except MCPError:
        return None
    except BaseExceptionGroup as group:
        if isinstance(failure_leaf(group), MCPError):
            return None
        raise
    content = res.structured_content
    return content if isinstance(content, dict) else {"is_error": res.is_error}


def wait_for(client: httpx2.Client, url: str, headers: dict[str, str], states: set[str], timeout: float = 45.0) -> dict:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = client.get(url, headers=headers).json()
        if last.get("status") in states:
            return last
        time.sleep(0.5)
    raise AssertionError(f"run did not reach {states}; last snapshot status={last.get('status')}")


@pytest.mark.asyncio
async def test_r105_walking_skeleton(skeleton: Skeleton, secret, app_conn: persistence.Conn) -> None:
    kcs = settings.keycloak()
    urls = settings.urls()
    alex = kc.token_password(kcs.base_url, "ops-dev-direct", "alex", secret("kc_persona_alex_password"))["access_token"]
    sam = kc.token_password(kcs.base_url, "ops-dev-direct", "sam", secret("kc_persona_sam_password"))["access_token"]
    worker = kc.token_client_credentials(kcs.base_url, "ops-worker", secret("kc_client_secret_ops_worker"))["access_token"]
    mcp_write = kc.token_client_credentials(kcs.base_url, "ops-mcp-write",
                                            secret("kc_client_secret_ops_mcp_write"))["access_token"]
    mcp_read = kc.token_client_credentials(kcs.base_url, "ops-mcp-read",
                                           secret("kc_client_secret_ops_mcp_read"))["access_token"]
    a, s = {"Authorization": f"Bearer {alex}"}, {"Authorization": f"Bearer {sam}"}
    lines: list[str] = [f"R105 walking skeleton — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"]
    with httpx2.Client(base_url=API, timeout=10.0) as c:
        # Responses are bound before every assert: pytest prints assert operands, and a header would carry a token.
        refused = c.get("/api/v1/me", headers={"Authorization": f"Bearer {worker}"})
        assert refused.status_code == 401  # a workload token at the API: wrong audience and azp
        cid = c.post("/api/v1/conversations", headers=a).json()["conversation_id"]
        accepted = c.post(f"/api/v1/conversations/{cid}/messages", headers=a, json={
            "kind": "investigate", "text": "Investigate the alerts on Asset A17 over the last 24 hours.",
            "context": {"asset_id": "A17", "hours": 24}})
        assert accepted.status_code == 202, accepted.text
        run_id = accepted.json()["run_id"]
        lines.append(f"run_id={run_id} accepted status={accepted.json()['status']}")
        snapshot = wait_for(c, f"/api/v1/runs/{run_id}", a, {"AWAITING_APPROVAL", "FAILED", "INSUFFICIENT_EVIDENCE"})
        assert snapshot["status"] == "AWAITING_APPROVAL", snapshot
        pid = snapshot["active_proposal_id"]
        proposal = c.get(f"/api/v1/proposals/{pid}", headers=s).json()
        sha, revision = proposal["payload_sha256"], proposal["revision"]
        me = c.get("/api/v1/me", headers=a).json()
        assert proposal["payload"]["evidence_refs"] and proposal["authored_by"] == [me["subject"]]
        lines.append(f"proposal_id={pid} revision={revision} payload_sha256={sha} evidence={proposal['payload']['evidence_refs']}")
        decision = {"expected_revision": revision, "expected_payload_sha256": sha, "decision": "approve",
                    "reason": "Reviewed the exact synthetic proposal."}
        self_decision = c.post(f"/api/v1/proposals/{pid}/decisions", headers=a, json=decision)
        assert self_decision.status_code == 403  # the requester may not approve their own proposal
        stale = c.post(f"/api/v1/proposals/{pid}/decisions", headers=s, json={**decision, "expected_payload_sha256": "0" * 64})
        assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"
        approved = c.post(f"/api/v1/proposals/{pid}/decisions", headers=s, json=decision)
        assert approved.status_code == 200 and approved.json()["status"] == "APPROVED", approved.text
        second = c.post(f"/api/v1/proposals/{pid}/decisions", headers=s, json=decision)
        assert second.status_code == 409  # the first decision wins
        final = wait_for(c, f"/api/v1/runs/{run_id}", a, {"SUCCEEDED", "FAILED", "OUTCOME_UNKNOWN", "ESCALATED"})
        assert final["status"] == "SUCCEEDED", final
        events = c.get(f"/api/v1/runs/{run_id}/events", headers=a).json()["events"]
        assert [(e["type"], e["source"]) for e in events] == EXPECTED_EVENTS, [e["type"] for e in events]
        confirmed = events[-1]["payload"]
        assert confirmed["status"] == "SUCCEEDED" and confirmed["receipt"]["incident_id"].startswith("INC-")
        action_id = confirmed["action_id"]
        lines.append(f"state={final['status']} state_version={final['state_version']} action_id={action_id} "
                     f"incident_id={confirmed['receipt']['incident_id']}")
        lines.append("events=" + ",".join(e["type"] for e in events))
    with httpx2.Client(base_url=urls.incident_sim, timeout=10.0) as d:
        persona_at_destination = d.get(f"/internal/actions/{action_id}", headers=a)
        worker_at_destination = d.get(f"/internal/actions/{action_id}", headers={"Authorization": f"Bearer {worker}"})
        assert (persona_at_destination.status_code, worker_at_destination.status_code) == (401, 401)
        assert action_id not in persona_at_destination.text and action_id not in worker_at_destination.text
        key = d.get(f"/internal/actions/{action_id}", headers={"Authorization": f"Bearer {mcp_write}"}).json()
        assert key["state"] == "COMMITTED" and key["payload_sha256"] == sha
    # Review focus 1 and 3 over the real transport: a replayed create_incident with a fresh execute handle returns
    # the recorded outcome (same action id, no second incident), and the wrong tokens are refused at mcp-write.
    cur = await app_conn.execute("SELECT id FROM app.jobs WHERE run_id = %s AND type = 'execute'", (UUID(run_id),))
    execute_job = (await cur.fetchone())["id"]
    handle = await persistence.mint_handle(app_conn, run_id=UUID(run_id), job_id=execute_job, server=Server.WRITE,
                                           azp="ops-worker")
    replay = await mcp_call(urls.mcp_write, worker, handle, "create_incident", {"proposal_id": pid})
    assert replay is not None and replay["status"] == "ok" and replay["data"]["action_id"] == action_id
    for wrong in (alex, mcp_read):
        assert await mcp_call(urls.mcp_write, wrong, handle, "create_incident", {"proposal_id": pid}) is None
    with httpx2.Client(base_url=urls.incident_sim, timeout=10.0) as d:
        again = d.get(f"/internal/actions/{action_id}", headers={"Authorization": f"Bearer {mcp_write}"}).json()
        assert again["receipt"] == key["receipt"]  # the same receipt, so no second incident
    lines.append("replay=same_action_id refusals=api:worker,destination:persona+worker,mcp-write:persona+mcp-read")
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
```

In `tests/plan_b/test_evidence.py` replace `EVIDENCE_ROOT = Path("reports/bootstrap")` with `EVIDENCE_ROOTS = (Path("reports/bootstrap"), Path("reports/skeleton"))` and make `test_evidence_has_no_token_shapes` iterate `for root in EVIDENCE_ROOTS: if not root.exists(): continue; for path in root.rglob("*"): ...` (the proof test monkeypatches `EVIDENCE_ROOTS` with a one-element tuple instead of `EVIDENCE_ROOT`). Update the module docstring's first line to "Nothing under reports/bootstrap/ or reports/skeleton/ may contain…". The secret-value scan and the JWT regex then cover the skeleton's evidence with no second implementation.

Create `tests/plan_d/test_skeleton_evidence.py` for the shape only:

```python
"""The R105 evidence file names the run, the incident and the event sequence (its redaction is tests/plan_b/
test_evidence.py's job, which scans reports/skeleton/ too). Absent evidence is not a failure: CI never runs the
live suite."""

from pathlib import Path


def test_skeleton_evidence_names_run_incident_and_events():
    files = sorted(Path("reports/skeleton").glob("*.txt"))
    assert files, "the committed R105 evidence is missing"  # not vacuous: the file is tracked
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "run_id=" in text and "incident_id=" in text and "events=run.accepted," in text, path
```

- [ ] **Step 3: Run it**

Run: `uv run python scripts/skeleton.py status` (all `down`), then:
`OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e -q -p no:cacheprovider`
Expected: every live test passes (`11 passed`: 5 persistence, tokens, incident-sim, mcp-read, mcp-write, worker and R105 — record the real count), `reports/skeleton/r105-walking-skeleton.txt` written. Then `PYTHONUTF8=1 uv run python -m pytest tests/plan_d/test_skeleton_evidence.py tests/plan_b/test_evidence.py -q` → all pass. Record the pytest summary and the evidence file's lines (they contain no secret) in your report. If a process fails to start, read `runtime/skeleton/<name>.log` and fix the wiring in this task's scope (environment, ports); a defect in an earlier task's code is reported to the controller, not patched silently.

- [ ] **Step 4: Runbook and topology**

Create `docs/runbooks/walking-skeleton.md`:

```markdown
# Walking skeleton (T08)

Five host processes against the dev profile (PostgreSQL + Keycloak in Compose). Containers for the application
processes arrive with T30; everything here reads its configuration the way a container would (environment plus secret
files), so nothing is throwaway.

1. `uv run python scripts/bootstrap_dev.py up` (Keycloak, Postgres; secrets under `OPS_SECRETS_DIR`).
2. `uv run python scripts/skeleton.py migrate` (Alembic revision 1 for `ops` and `incident`; creates role `incident`).
3. Either, for a manual session: `uv run python scripts/skeleton.py up` — starts incident-sim :8090, mcp-read
   :8081, mcp-write :8082, api :8000, worker :8070 (health only), all on 127.0.0.1; logs in `runtime/skeleton/`;
   `uv run python scripts/skeleton.py down` when finished.
4. Or, for the proof: with no skeleton processes running (`scripts/skeleton.py status` shows every process `down`),
   `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e -q` — the R105 module starts and stops its own five
   processes and writes `reports/skeleton/r105-walking-skeleton.txt`. The in-process live tests of Tasks 5 and 6
   bind 18081 and 18090, so they never collide with a running skeleton.
5. Every live run rewrites tracked evidence (`reports/skeleton/r105-walking-skeleton.txt`, and the Plan B suite's
   `reports/bootstrap/*.txt`), so the tree is dirty after a live run; commit the files when their content changed for
   a reason worth keeping, otherwise `git checkout -- reports/`.

Tokens: personas through the dev-only direct grant (`ops-dev-direct`, audience `ops-api`); the worker through
`ops-worker` (both MCP audiences); mcp-write through `ops-mcp-write` (audience `incident-sim`). The MCP resource URLs
in `.env` are audience identifiers (`http://mcp-read:8081/mcp`), while the host processes listen on
`http://127.0.0.1:8081/mcp`; T30 makes them coincide.

Declared shortcuts: the debt list in `SESSION_STATE.md` (each line names its owning task).
```

In `docs/runbooks/dev-topology.md` add a short "Host processes (T08)" table with the five ports, pointing to the new runbook.

- [ ] **Step 5: Handoff documents**

- `handoff/tasks.json` T08: `status` → `DONE`; add the key `review_notes` (T08 has none yet) with one entry: "Plan D (branch plan-d): done in <Task 1's first commit>..<the commit before this docs commit>; host processes started by scripts/skeleton.py (containers → T30); evidence tests/e2e/test_r105_walking_skeleton.py and reports/skeleton/r105-walking-skeleton.txt (live only, OPS_LIVE=1; CI has no Docker); debt list in SESSION_STATE.md; rulings in docs/superpowers/plans/2026-10-08-first-slice-d-walking-skeleton.md." Keep formatting, key order, LF.
- `handoff/BUILD_BACKLOG.md`: mirror the T08 line.
- `handoff/acceptance-matrix.json` R105: `evidence_status` → `RECORDED_LOCALLY_LIVE`, `implementation_status` → `IMPLEMENTED_LOCALLY_VERIFIED`, `evidence_paths` → `["tests/e2e/test_r105_walking_skeleton.py", "reports/skeleton/r105-walking-skeleton.txt"]`; extend the file's top-level `note` vocabulary sentence with " RECORDED_LOCALLY_LIVE: the test passes against the running dev profile with OPS_LIVE=1 and is collected but skipped by scripts/check.py and CI; the evidence file records a run." (the existing `RECORDED_LOCALLY` definition requires the test to pass in CI, which a live test cannot).
- `STATUS.md`: a "Plan D (T08)" bullet: branch, commit range, `check.py` totals, the live suite's totals, what is evidenced (R105), the five processes and ports, and that the application processes are host processes until T30.
- `SESSION_STATE.md`: "Plan D executed" section (commit range; the 27 rulings in one paragraph each at most one sentence, or a pointer to the plan with the ten debt additions summarised; the three Plan C open items now decided by ruling 10 and 4; open items for Plan E), update the "Next task" line: Plan E = T09 (migrations, roles, RLS, definer functions) and T10 (incident-sim action_key hardening), written from revision 1 and the skeleton's persistence seams; update the "Exact next step" block with the skeleton runbook commands.
- `docs/PROJECT_HISTORY.md`: insert `## 19. The skeleton walked before the plan was perfect` before the closing section and renumber the closing section to `## 20. What the process taught`. Problem/Change paragraphs in the file's voice: what the research and spike found before planning (the MCP SDK's snake_case results, missing `additionalProperties`, 401 as a protocol error, the Windows event loop, the password-leaking `CREATE ROLE`, persona tokens with no audience), what the plan reviews found (filled in by the controller from the review record), and what execution found (the implementers' fix rounds — the controller supplies the list at dispatch time; leave a clearly marked one-sentence placeholder only if the controller's dispatch did not supply it, and say so in the report).
- `README.md`: replace "Status: planning complete, implementation not started" with "Status: walking skeleton runs locally (T08); hardening in progress" and link `docs/runbooks/walking-skeleton.md`.

- [ ] **Step 6: Full check and commit**

Run: `PYTHONUTF8=1 uv run python scripts/check.py 2>&1 | tail -3` → `CHECK: GREEN`; `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts; echo exit=$?` → exit 0 (the task graph and matrix stay consistent); `python -c "import json; json.load(open('handoff/tasks.json', encoding='utf-8')); json.load(open('handoff/acceptance-matrix.json', encoding='utf-8'))"`.

Run `uv run ruff format scripts/skeleton.py tests/e2e tests/plan_d tests/plan_b/test_evidence.py && uv run ruff check --fix scripts/skeleton.py tests/e2e tests/plan_d tests/plan_b/test_evidence.py` first.

```bash
git add scripts/skeleton.py tests/plan_b/test_evidence.py tests/e2e/test_r105_walking_skeleton.py tests/plan_d/test_skeleton_evidence.py reports/skeleton docs/runbooks/walking-skeleton.md docs/runbooks/dev-topology.md
git commit -m "feat(skeleton): process harness, the R105 end-to-end proof and its evidence"
git add handoff/tasks.json handoff/BUILD_BACKLOG.md handoff/acceptance-matrix.json STATUS.md SESSION_STATE.md docs/PROJECT_HISTORY.md README.md
git commit -m "docs: handoff state after Plan D (T08 done; skeleton debt owed to T09-T30)"
```

---

## Coverage notes

- T08 instructions: processes ✓ (Tasks 4–8, host processes per ruling 1); real client-credentials tokens ✓ (Tasks 3, 5, 6, 8); the path POST run → job → worker → mcp-read → fake draft → decision → mcp-write → incident-sim → receipt → event ✓ (Task 9's test asserts the nine events); Alembic revision 1 ✓ (Task 2); incident-sim as T10's base ✓ (Task 4); debt list before coding ✓ (Task 1 step 1); decision by a second persona ✓ (Task 7, `check_reviewer`); every transition through the table ✓ (`persistence.transition`, Task 2; the e2e history assertion in Task 8's live test).
- T08 DoD 1 ✓ Task 9; DoD 2 ✓ Task 1 + runbook; DoD 3 ✓ Task 2.
- Review Focus 1 ✓ Task 6 (`next_step`, live replay with the commit-before-I/O witness) and Task 9 (replay over the real transport); 2 ✓ Task 7 and Task 9; 3 ✓ Tasks 3, 5 (live), 9 (worker token at the API and the destination; persona and mcp-read tokens at mcp-write; persona token at mcp-read); 4 ✓ Task 5 (strict schema); 5 ✓ Task 4.
- Not in this plan: `tool.started`/`tool.completed` payload richness (T14), the admission router's other routes (T12), asset tools and asset-sim (T16), governed retrieval (T17), containers (T30), reconciliation (T22), the SQL definer functions and RLS (T09).

## Resolved versions

Measured by the round-1 dry run's `uv lock` (2026-10-08): mcp 2.3.0, mcp-types 2.3.0, fastapi 0.143.0, starlette 1.7.0, uvicorn 0.54.0, psycopg 3.3.6, sqlalchemy 2.1.4, alembic 1.20.0, pyjwt 2.15.1, httpx2 2.13.1, cryptography 50.0.2, pytest-asyncio 1.4.0, ruff 0.16.10 (already locked). Task 1 records what it resolves; floors in the plan are never raised past PyPI's latest.

## After Plan D

Plan E (T09 migrations, roles, RLS and definer functions; T10 incident-sim hardening) is written from revision 1 and the seams `ops_core.persistence` marks with `TODO(T09)`, and dry-run on scratch copies before execution. T30 containerises the five processes; until then the skeleton runs on the host.

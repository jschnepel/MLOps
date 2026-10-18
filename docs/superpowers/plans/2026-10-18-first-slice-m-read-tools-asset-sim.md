# First Slice M: The Read Tools, `asset_scope` and asset-sim (T16) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build T16, the asset half of mcp-read and its destination: asset-sim as a seventh process serving
corpus-1's six assets and seven alerts by fixed, documented rules under the instant mcp-read forwards; the
`asset_scope(raw_handle, client_azp)` definer; the two asset tools `get_asset_status` and `get_recent_alerts`
(absolute interval, `next_cursor`); `search_procedures` on the run's own asset type with the definer's instant and the
whole section as its excerpt; the requester's membership re-checked at read time in both read definers (R028); and the
worker's fail-closed tool discovery and result validation (R029). Vector mode stays with T18 (ruling 1).

**Architecture:** Revision `0012_asset_scope` creates `asset_scope` (mcp_read only: the handle decides the run and
the tenant, the requester's active `requester` membership is re-checked, and it returns the run's asset and
`[start_at, end_at)` with `as_of = app.current_time()` read after the lease lock) and re-creates
`search_procedures_scoped` from 0011's own body with five textual changes (the same membership check, a
`retrieved_at` column, the excerpt bounded at 8000 characters with a per-row `excerpt_cut`); its downgrade restores
0011 exactly. asset-sim (`asset-sim/src/ops_asset_sim/`, FastAPI, port 8091) trusts only `ops-mcp-read`'s workload
token (aud `asset-sim`) and the `X-Ops-Tenant-Id`/`X-Ops-As-Of` context, filters by tenant itself (an unknown asset
and another tenant's both 404), derives status and alerts from `data/corpus/assets.json` and `meta.json` without
changing corpus-1, pages alerts with a cursor bound to tenant, asset and interval, and has test-profile fault hooks.
mcp-read serves each asset tool in two committed database units (`resolve_invocation` with the allowlist, then
`asset_scope`) and only then calls asset-sim with its own token outside any transaction; it refuses another asset
(`ASSET_OUT_OF_SCOPE`) or interval (`INTERVAL_OUT_OF_SCOPE`) before asset-sim is asked, validates asset-sim's answer as
a whole tool result before returning it (`UPSTREAM_INVALID`), and advertises exactly the committed input schemas.
`ops_core.tool_contracts` (jsonschema becomes a runtime dependency of `ops-core`) holds those schemas at run time; the
worker's `HttpMcpCaller` lists the tools in the same session, refuses an unexpected tool set or an altered schema, and
validates every read result (size, error flag, contract, status).

**Tech Stack:** as Plan L, plus `jsonschema` 4.26 (already locked as a dev dependency) as a runtime dependency of
`ops-core`, and FastAPI and uvicorn (already locked for incident-sim) for `ops-asset-sim`; `uv lock --offline`
records both without a version change. PostgreSQL 17 with pgvector, psycopg 3.3, Alembic, `mcp` 2.3.0, Starlette,
FastAPI, `httpx2`, Python 3.13, pytest and pytest-asyncio.

**Spec:** `SPEC_AMENDMENTS.md` (OPS-BUILD-1.3.6) over `BUILD_SPEC.md`: AM-15 (SA:327-358: the read row SA:333,
handle binding SA:338, SA:348, schema rule SA:350, envelope SA:351-355), AM-20.3 (SA:444-474: header SA:446,
`asset_scope` SA:460, `search_procedures_scoped` SA:461), AM-20.7 item 6 (SA:555-558), AM-10's clock rule
(SA:156-162), AM-80 (SA:761, SA:766); BUILD_SPEC §9 (BS:354-366), §10 (BS:376-407: BS:378, BS:384-386, BS:389, BS:399,
BS:401, BS:405), §11 (BS:417, BS:419). The inputs are the fact sheet `docs/superpowers/research/2026-10-18-plan-m-inputs.md`
(cited "FS §n" / "FS Qn") and the controller's brief of 18 rulings (cited "ruling n"; restated below with what this
plan made of each). Earlier artefacts this plan builds on: revisions 0001-0011 (`_resolve_handle` of 0009 and 0007,
`HEADER` and the frozen-function pattern of 0009 and 0011), `ops_core.persistence`, `privileges`, `locking`,
`settings`, `tokens`, `corpus`, `testing.faults`; mcp-read as Plans J and L left it; incident-sim as the template of
a FastAPI service; the worker's `HttpMcpCaller`; `scripts/skeleton.py`; the `tests/e2e/` fixtures and helpers
(`new_run`, `lease_for`, `investigate_job`, `read_handle`, `refused`, `purge_run`, `purge_tenant`, `serving`).

## Writer departures

Each place where this plan does something other than, or more than, a ruling says, with the reason. Nothing else
departs.

1. **`search_procedures` runs three database units, not two (rulings 12 and 15).** Ruling 12 has mcp-read ask
   asset-sim for the run's asset, but `resolve_invocation`'s output does not change (ruling 7, erratum 77) and carries
   no asset, so the search also reads `asset_scope` in its own committed unit: unit 1 `resolve_invocation` with the
   allowlist, then the mode check (ruling 14's order kept), unit 2 `asset_scope`, the asset-sim call, unit 3
   `search_procedures_scoped`. The definer re-resolves the handle in each unit, so nothing is gained by a handle that
   dies in between.
2. **The definer's instant and the excerpt change land in Task 1, not in the search task (the brief's example
   order).** Revision 0012 changes the function's return type; `persistence.search_procedures` reads the new column
   and the per-row `excerpt_cut`, and mcp-read's `search_response` stamps `retrieved_at` and `observed_at` from it, in
   the same commit, or the live suite would break between tasks. Task 4 then only adds the run's asset type.
3. **asset-sim's faults reuse three existing `FaultKind`s and add one (ruling 6).** The 503, the malformed body and
   the slow answer are `drop_before_commit`, `malformed_response` and `timeout_before_accept` (BS:405's phrases,
   consumed the destination's way); the `unavailable` state is a new `FaultKind.ASSET_UNAVAILABLE` in
   `ASSET_SIM_FAULTS`, so `tests/plan_h/test_faults_t13.py`'s "no orphan hook" invariant gains that set as it did the
   sweeper's. asset-sim's arming route accepts only these four kinds.
4. **asset-sim answers beyond ruling 15's list are mapped too.** A 401 from asset-sim (mcp-read's token refused)
   drops mcp-read's cached token and answers `UNAVAILABLE`, retryable; any 5xx is `UNAVAILABLE`, retryable; a 400 to a
   request that carried a cursor is `INVALID_CURSOR` (ruling 10); any other status or a body that is not a JSON object
   is `UPSTREAM_INVALID`. mcp-read also checks what the schema cannot (`within_scope`): the answer names the run's
   asset, echoes the run's interval, and holds no alert outside it or after `as_of`; otherwise `UPSTREAM_INVALID`.
5. **The 256 KiB bound is applied after the SDK has parsed the answer (ruling 13's "else after").** The SDK reads and
   parses the body before `call_tool` returns, and a response hook raising inside the SDK's transport task was not
   measured, so the worker measures the whole `CallToolResult` as received and refuses it before anything of it is
   used. Nothing larger can reach a handler.
6. **The worker's R029 checks apply to read calls only (ruling 13's "read handle").** `create_incident` at
   mcp-write keeps T47's check: mcp-write advertises its pydantic-generated schemas, not the committed files, so a
   discovery check there would refuse every send. Debt line → T20 (`TODO(T20)` at the line).
7. **`ops-view-users`'s refusal is 401 or 403 (ruling 6).** Its token's audience is the realm's choice (no mapper
   names one), so the live DoD-2 test asserts it is refused (401 or 403, no data) where the other three foreign
   tokens must be exactly 403.
8. **Two startup markers, `GOVERNED_CORPUS` kept (ruling 3).** Revision 0012 keeps 0011's ranking text, so
   `GOVERNED_CORPUS` stays true and is kept (its comment says so); the new markers are `ASSET_SCOPE`
   (`as_of := app.current_time()` in `asset_scope`) and `SEARCH_INSTANT` (`retrieved_at := v_now` in the search). mcp-read
   checks all four at start.
9. **`new_run` gains `requester`, `asset_id` and `interval` keywords, and random test tenants get a requester
   membership (`conftest.add_requester`).** The definers' membership re-check (ruling 7) refuses a run whose
   requester has no active requester row in its tenant; ALEX has one only in alpha. `test_migration_0011_live.py`'s
   random tenants get ALEX as requester, and the retrieval baseline's beta run is requested by beta's requester,
   riley. Every other live test that calls a read definer uses alpha and ALEX already (checked: FS §3.9 and every
   `new_run(` call site).
10. **Tests that run mcp-read's search need asset-sim (ruling 12's fail-closed rule).** A new function-scoped
    `asset_sim` fixture serves asset-sim's production app in the test's loop and exports `OPS_ASSET_SIM_URL`;
    `test_mcp_read_t15_live.py`, `test_mcp_read_live.py` and `test_mcp_read_process_live.py` use it from Task 4 on.
    `test_mcp_read_live.py`'s "no asset type reaches other assets" control moves to a run whose asset asset-sim does
    not know (Z99), because an A17 run now searches pump and any-asset documents whatever the caller names.

## Global Constraints

Carried from Plan L's header (its text applies with "Plan L"/"T17" read as the plan that wrote it); the Plan M
additions below win where the two differ:

- **Debt before code (SA:698).** The Plan M debt list (below) is committed in Task 1 Step 1c before any code changes.
  Nothing not on the list may be shortcut; every line names its owning task.
- **Authority boundaries stay where the spec puts them.** `mcp_read` holds no table grant and EXECUTE on exactly
  `current_time`, `resolve_invocation`, `search_procedures_scoped` and `asset_scope`; `mcp_exec` cannot execute either
  read definer (42501); the tenant, the asset and the interval of every read come from the handle through
  `asset_scope`, never from an argument (BS:362); asset-sim never sees the handle or the worker's token (BS:364);
  definers per SA:446 (REVOKE PUBLIC, GRANT exactly `mcp_read`). **Nothing here sends anything to an external system
  or a person** (BS:730), and nothing here writes the dev databases: migrating `ops` to 0012 is an owner input.
- **Synthetic only.** asset-sim serves corpus-1's synthetic assets and alerts; every alert message starts
  "Synthetic"; corpus-1's files are read, never changed (`ops_core.corpus.RELEASES` stays one entry).
- **Secrets** live only as files under `OPS_SECRETS_DIR`; no secret, token or raw handle in an environment variable,
  a command line, a log line, an exception message, an assertion operand, an evidence file or a document. asset-sim's
  and mcp-read's error messages name rules, never values.
- **Clock.** asset-sim has no clock: every status and every "no alert from the future" rule runs at the `as_of` mcp-read
  forwards, which `asset_scope` reads from `app.current_time()` after the lease lock (SA:157). A test that moves
  `app.test_clock` resets it in `finally`.
- **One string per SQL statement**, no SQLAlchemy bind in any `op.execute` string (`tests/plan_e/test_transitions_table.py`
  scans every revision, 0012 included); revision 0012 freezes its cells, callers, signatures and bodies, and its
  downgrade restores 0011's body from 0011's own module.
- **Live tests never touch the dev databases**: they run against `ops_test`/`incident_test` under `PROFILE=test`
  through the `migrated`, `app_conn`, `role_conn`, `ingested` and (new) `asset_sim` fixtures; every random tenant a test
  creates is purged with its memberships (`purge_tenant`); every membership a test switches off is switched on again in
  `finally`; servers are stopped in `finally` (uvicorn through `should_exit`).
- **Tests:** unit tests in `tests/plan_m/` (DB-free; added to `testpaths` in Task 1), live tests in `tests/e2e/` gated
  by `OPS_LIVE=1`. Tests that pinned one tool, the two-unit search or the wall-clock stamp are rewritten in the task
  that changes the behaviour, each named. No xfail or skip except the live gate.
- **Comments** per `docs/CODE_COMMENTS.md`; ≤120 characters per line (Plan L's counting command, `$COUNT`); no
  `type: ignore`; no `noqa`; ruff + mypy strict clean; UTF-8 without BOM, LF.
- **Gates:** `uv run ruff format <files> && uv run ruff check --fix <files>`, `PYTHONUTF8=1 uv run python
  scripts/check.py` GREEN after every task, `uv run python -I scripts/verify_handoff.py --reference-code --manifest
  --contracts` exit 0 after every task, and the live suite `PYTHONUTF8=1 uv run python scripts/check.py --profile
  test` after every task, with the dev stack up and `uv run python scripts/skeleton.py status` showing every process
  down (seven of them from Task 2 on). After a live run: `git checkout -- reports/bootstrap reports/skeleton
  reports/auth reports/admission reports/leases reports/events reports/outbox reports/mcp-read reports/mcp-write
  reports/retrieval`; `reports/asset-sim/` and `reports/mcp-read/t16-read-tools.txt` are new and stay until Task 7
  commits them. If mypy reports errors in modules this plan did not touch, rerun it with `--no-incremental` before
  treating one as real.
- **Toolchain and locks:** everything through the locked environment from the repository root (`uv run python -m
  pytest …`); the only lock changes are Task 2's and Task 3's `uv lock --offline` (no version moves: FastAPI,
  uvicorn and jsonschema are locked already). If `--offline` reports a missing distribution, stop and report: no
  network resolution is part of this plan. Never start an interactive interpreter.
- **Never migrate the dev databases.** Nobody runs `scripts/skeleton.py migrate`, `ingest` or `up` against
  `ops`/`incident` in this plan; migrating the dev database to 0012 is an owner input recorded in Task 7; until then
  mcp-read refuses to start on it, by design.
- **Commits:** one logical group per step that says "commit"; messages free of any attribution trailer (owner
  instruction); never push; never `docker compose down -v`; never change system settings.
- **No interim red across tasks.** Every task ends with both gates GREEN at the stated counts: the revision, its
  matrix rows, its marker and its first reader land together (Task 1); asset-sim is a service on its own (Task 2);
  mcp-read's asset tools need both (Task 3); the search's asset type needs asset-sim in every live test that searches
  (Task 4); the worker's checks need mcp-read to advertise the committed files (Task 5).
- **Line numbers** in "Modify" lines are those of the file as the previous task left it. Every replacement quotes the
  exact current text ("Edit n (`path`, …), replace:" then "with:"); a step that creates a file, or replaces one whole,
  gives the whole file.
- **Counts.** Today (`cd6a5b3`) the dev gate is `1270 passed, 191 skipped` and the live gate `1440 passed, 21 skipped`
  (170 live-gated tests). Task 1 Step 1a records both before any change; if either differs, every expected count
  below shifts by the same difference. Every dev count below was measured by applying this plan task by task to a
  scratch copy of `cd6a5b3` (`git archive`) with the repository's locked environment, the scratch sources first on
  `PYTHONPATH` (13 tests that need a git checkout, `test_verify_handoff.py` and `test_text_hygiene.py`, fail in a
  scratch copy and pass in the repository; the counts below are the repository's). Every live count is arithmetic (the
  dev count plus the live-gated tests: the dev run's skips minus the 21 that skip in both gates): no live test, DDL
  statement or asset-sim token check of this plan has run against a database or Keycloak before execution. Review
  Focus names what to watch.

## Rulings (the brief's 18, as this plan implements them)

The controller's brief decided these; executors do not re-litigate them. Each line says where the plan implements the
ruling; the departures above are the only places where it does something else.

1. **Vector mode** — deferred to T18 (option a): mcp-read keeps answering `vector_exact` with `UNSUPPORTED_MODE` after
   the handle resolution; the `TODO(T16)` markers (`server.py`, `routing.py`, `scripts/build_schemas.py`) become
   `TODO(T18)` (Task 4). Erratum 103; T18's review note gains the moved instruction (Task 7).
2. **`asset_scope`** — `app.asset_scope(p_raw_handle text, p_client_azp text)` returning one row `(run_id, tenant_id,
   asset_id, start_at, end_at, as_of)`, granted to `mcp_read` alone, `_authority` then `_resolve_handle(…, 'read')`,
   the tenant set transaction-locally, the membership re-check, `as_of` after the lease lock; no tool check (Task 1).
   Erratum 104.
3. **Revision 0012** — `asset_scope` and its grant; `search_procedures_scoped` dropped and created again from 0011's
   frozen body with five textual changes (the return type, the membership block, `retrieved_at := v_now`, the 8000
   bound and `excerpt_cut`), re-granted; an exact downgrade (Task 1). mcp-read asserts 0012 at start through two new
   markers (departure 8); `retrieved_at` and the search envelope's `observed_at` come from the definer, the asset tools'
   `observed_at` from `as_of`, refusals before any database unit keep the wall clock (Tasks 1 and 3). No assets table.
4. **asset-sim's data** — derived, corpus-1 unchanged: `ops_asset_sim.data` loads `assets.json` through
   `corpus.load_assets` and `meta.json` once, checks what `load_assets` does not (severity, kind, `raised_at`), and
   derives alerts and status by the rule stated in the module docstring, `asset-sim/README.md` (Task 2) and
   `docs/runbooks/asset-sim.md` (Task 6). The stated instants are below ("The derived data at the stated instants").
5. **Process** — port 8091, `OPS_ASSET_SIM_PORT`, `OPS_ASSET_SIM_URL` (`settings.Urls.asset_sim`); the skeleton's
   seventh process, first; incident-sim's shape (`__main__.py`, `production_app()`, `redaction.install()`, the
   selector loop); `/health/ready` once the keys are loaded (the data is loaded before the app exists, so a bad file
   stops the process at start); Dockerfile and per-directory `tests/` → T30 (Task 2).
6. **Authentication** — `TokenVerifier(issuer, audience="asset-sim", allowed_azp={"ops-mcp-read"}, jwks_url,
   token_type="Bearer")`, `WrongAudience` → 403, other refusals → 401 with `WWW-Authenticate: Bearer`; fault hooks only
   under `PROFILE=test` (departure 3); mcp-read's `WorkloadTokenSource` for `ops-mcp-read` built in its lifespan (Tasks
   2 and 3). DoD 2's live test presents the worker's, mcp-write's, a persona's and `ops-view-users`' tokens (departure
   7).
7. **R028 membership** — inside both definers, after the tenant is set: an active row `(tenant, subject =
   runs.requester, role 'requester')`, else the one `OC008` refusal; the API admits a requester by `(issuer,
   subject)` through `resolve_identity` with the realm's one configured issuer (`api/src/ops_api/app.py:199-216`), and
   `runs` keeps no issuer, so the row is matched without it: erratum 105. `resolve_invocation` is unchanged (Tasks 1
   and 4; the live "revoke → all three tools refuse" is Task 4's).
8. **Forwarding** — mcp-read's own token, never the handle; `GET /assets/{id}`, `/status`, `/alerts?start_at&end_at&
   limit[&cursor]`; `X-Ops-Tenant-Id` and `X-Ops-As-Of` from `asset_scope`; `ASSET_OUT_OF_SCOPE` before asset-sim is
   asked; asset-sim's 404 for unknown and foreign assets alike, mapped to `NOT_FOUND`; both layers tested, unit and
   live (Tasks 2 and 3).
9. **Interval** — only the run's `[start_at, end_at)`; a caller interval that differs as instants is
   `INTERVAL_OUT_OF_SCOPE` (an impossible date that passes the pattern too); asset-sim returns `start_at <= occurred_at
   < end_at` and `occurred_at <= as_of` (Tasks 2 and 3).
10. **Cursor** — order `(occurred_at, alert_id)`; a 76-character base64url token: a version byte, `occurred_at` in
    microseconds, the alert UUID and the SHA-256 of `(tenant, asset, start_at, end_at)`; a cursor of another request is
    400 → `INVALID_CURSOR`; `next_cursor` and the envelope's `truncated` exactly when more remain; tested with
    `limit=1` over A17's two alerts, unit and live (Tasks 2 and 3).
11. **Excerpt** — the whole section up to 8000 characters, a cut flagged per row and turned into `truncated`
    (Task 1); `docs/retrieval.md` records it (Task 6); corpus-1's sections are 45-119 words, so the T17 baseline's
    ranking and excerpts are unchanged.
12. **Asset type** — mcp-read asks asset-sim `GET /assets/{run's asset}` and passes that type; a different caller
    type is `ASSET_TYPE_OUT_OF_SCOPE`; asset-sim's 404 leaves the caller's type or none; asset-sim unavailable is
    `UNAVAILABLE`, retryable (Task 4). Existing tests and asset IDs: every `new_run` in `tests/e2e` used A17 until now;
    on alpha that is a pump, so the search is filtered to pump and any-asset documents (the R105 skeleton, the T15 live
    tests and `test_mcp_read_live.py`'s implicit case; their expected first answers are any-asset or pump sections,
    so they stand); on a random tenant A17 is unknown to asset-sim and the search proceeds unfiltered, but those tests
    call the definer directly; `test_mcp_read_live.py`'s control moves to Z99 (departure 10).
13. **R029** — the worker lists in the same session, refuses an unexpected tool set or an altered schema of the
    called tool (canonical JSON), and validates the result (size, error flag, `schemas/tool-result.schema.json`,
    `status == "ok"`); mcp-read advertises exactly the committed files and a unit test proves the files and the
    argument models agree on every bound; jsonschema becomes a runtime dependency of `ops-core`
    (`ops_core.tool_contracts`); failure stays FAILED "retrieval failed" (Tasks 3 and 5; departures 5 and 6).
14. **`UNSUPPORTED_MODE` order and corpus version** — the handle first, then the mode (kept, Task 4); the fallback
    `corpus_version` is closed by T17 (recorded in T16's review note, Task 7).
15. **Units per call** — asset tools: unit 1 `resolve_invocation` with the allowlist, unit 2 `asset_scope`, both
    committed, then asset-sim with a 10-second timeout and no retry (Task 3); a handle that dies between unit 2 and
    the call still yields one read of the run's own asset: documented (debt list), not prevented.
16. **Status observation** — returned only; recording it for the grant's freshness (R116) → T21, SA:377 → T20 (debt
    list).
17. **The worker** — changed only for R029 (Task 5); the asset tools are proven with an independent client over HTTP
    (`test_mcp_read_process_live.py`, Task 6; and `test_mcp_read_t16_live.py`); the worker's calls → T20 (debt list).
18. **Tests and evidence** — `tests/plan_m` on the test path; live evidence in `tests/e2e/test_asset_sim_live.py`,
    `test_mcp_read_t16_live.py` and `test_migration_0012_live.py`, with `reports/asset-sim/t16-asset-sim.txt` and
    `reports/mcp-read/t16-read-tools.txt`; the tool-list pins move to three tools; R131's equality gains `asset_scope`
    for `mcp_read` and a 42501 for `mcp_exec`; `REVISIONS`, `DEFINER_FUNCTIONS`, the lock-order guard and
    `test_migration_0008_live.py`'s entry set include 0012 and `asset_scope` (Task 1); R028, R029 and R131's note in
    Task 7.

## The derived data at the stated instants (ruling 4)

The rule, applied to corpus-1 (`data/corpus/assets.json`; the alert UUIDs are `meta.json`'s), and pinned by
`tests/plan_m/test_asset_sim_data.py`:

| Asset | Alerts (raised_at, severity, revision) | at 2026-10-16T12:00Z (baseline) | at 2026-10-06T00:00Z | at 2026-10-06T12:00Z |
|---|---|---|---|---|
| A17 (alpha pump) | seal-001 10-05T14:00Z warning r1; seal-002 10-06T08:30Z warning r2 | `normal`, revision 2 | `warning`, revision 1 | `warning`, revision 2 |
| B22 (beta pump) | vibration-001 10-05T11:20Z warning r1 | `normal`, revision 1 | `warning`, revision 1 | `normal`, revision 1 (40 min outside) |

`get_recent_alerts` for A17 over `[2026-10-05T00:00Z, 2026-10-07T00:00Z)` returns seal-001 then seal-002 (UUIDs
`6699502e-a981-5959-9f24-6df6bd3d3ac5`, `c8f91c55-7028-5492-bad4-1e5680179647`); with `limit=1` the first page carries a
76-character `next_cursor`, the second none. A30's only alert is `info` and never warns. alpha asking for B22 is
404, exactly like Z99.

## Declared debt and errata

### Debt list (committed in Task 1 Step 1c, before coding)

Inserted into `SESSION_STATE.md` as a new section `## Plan M debt list (T16; committed before coding) [R6-B7]`
immediately after the `## Plan L debt list …` section (before `## Environment (observed)`); the exact text is Task 1
Step 1c's Edit 1.

### Errata proposed to the owner (numbered on from Plan L's 102)

The spec text stays authoritative until the owner decides; each line names the text it amends. The full wording is
Task 7 Step 2's "Plan M executed" block; in short:

103. **T16's instruction and review note (`tasks.json:753`, `:771`), SA:348, SA:461**: mcp-read's `vector_exact` →
     `mode=vector` translation and the nomic `search_query:` embedding move to T18 with the embeddings; until then
     mcp-read answers `vector_exact` with `UNSUPPORTED_MODE` after the handle resolution.
104. **SA:460** `asset_scope(raw_handle, client_azp)`: the caller's `azp` second (errata 83 and 93's pattern); one row
     `(run_id, tenant_id, asset_id, start_at, end_at, as_of)`, `as_of` = `app.current_time()` after the lease lock;
     `mcp_read` only; no tool check (the allowlist stays in Python, erratum 19).
105. **BS:362, BS:401, R028 (the requester's policy at read time)**: `asset_scope` and `search_procedures_scoped`
     require an active `memberships` row `(run's tenant, subject = runs.requester, role 'requester')`, matched without
     the issuer because `runs` keeps none; otherwise the one handle refusal (`OC008`, SA:355).
106. **SA:461 with erratum 93**: `search_procedures_scoped` returns one row `(corpus_version, retrieved_at, results)`,
     `retrieved_at` the instant its effectiveness rule ran at; each result's excerpt is the whole section up to 8000
     characters and carries `excerpt_cut`, which mcp-read turns into the envelope's `truncated` and leaves out of the
     result.

## File structure

- `migrations/app/versions/0012_asset_scope.py` (new, Task 1): `asset_scope`, the re-created search, the exact
  downgrade.
- `core/src/ops_core/privileges.py`, `locking.py`, `persistence.py` (Task 1): the matrix row, the lock-order unit,
  `ASSET_SCOPE`, `SEARCH_INSTANT`, `AssetScope`, `asset_scope()`, `Procedures.retrieved_at`/`truncated`.
- `core/src/ops_core/settings.py`, `testing/faults.py` (Task 2): `Urls.asset_sim`; `FaultKind.ASSET_UNAVAILABLE`,
  `ASSET_SIM_FAULTS`.
- `core/src/ops_core/tool_contracts.py` (new, Task 3), `core/pyproject.toml` and the root `pyproject.toml` (Tasks 1 and 3:
  `testpaths`; jsonschema; its mypy override), `uv.lock` (Tasks 2 and 3).
- `asset-sim/` (Task 2): `pyproject.toml`, `README.md`, `src/ops_asset_sim/data.py`, `app.py`, `__main__.py` (new).
- `mcp-read/src/ops_mcp_read/server.py` (Tasks 1, 3 and 4), `assets.py` (new, Task 3), `mcp-read/README.md` (Task 6).
- `worker/src/ops_worker/mcp.py` (Task 5).
- `core/src/ops_core/routing.py`, `scripts/build_schemas.py` (Task 4: `TODO(T18)`), `scripts/skeleton.py` (Task 2).
- Tests: `tests/plan_m/` (`__init__.py`, `test_migration_0012.py`, `test_asset_sim_data.py`, `test_asset_sim_app.py`,
  `test_tool_contracts.py`, `test_mcp_read_assets.py`, `test_mcp_read_search.py`, `test_worker_r029.py`);
  `tests/e2e/` (`test_migration_0012_live.py`, `test_asset_sim_live.py`, `test_mcp_read_t16_live.py`; `conftest.py`
  gains `free_port`, `asset_sim`, `SEEDED_ALPHA` and `add_requester`); edits to `tests/plan_d/test_mcp_read.py`,
  `test_settings.py`, `tests/plan_e/test_transitions_table.py`, `test_skeleton_cli.py`, `tests/plan_h/test_faults_t13.py`,
  `tests/plan_j/test_mcp_read_http.py`, `test_mcp_read_startup.py`, `test_verifier_t15.py`,
  `tests/plan_k/test_mcp_write_startup.py`, `test_verifier_t47.py`, `tests/plan_l/test_mcp_read_corpus.py` (whole file
  in Task 4), and the live `test_migrations_and_persistence.py`, `test_migration_0011_live.py`,
  `test_retrieval_baseline_live.py`, `test_mcp_read_t15_live.py`, `test_mcp_write_t47_live.py`,
  `test_migration_0008_live.py`, `test_mcp_read_live.py`, `test_mcp_read_process_live.py`.
- Documentation: `docs/runbooks/asset-sim.md` (new), `docs/runbooks/mcp-read.md`, `dev-topology.md`,
  `walking-skeleton.md`, `docs/retrieval.md` (Task 6); Task 7: `handoff/*`, `SESSION_STATE.md`, `STATUS.md`,
  `docs/ARCHITECTURE.md`, `docs/PROJECT_HISTORY.md`.

## Task overview

- **Task 1:** the debt list; revision 0012 with the matrix, lock-order and persistence changes; mcp-read's startup
  check and its search stamped from the definer; the live definer tests. Tests: `test_migration_0012.py` 10, the
  transitions module +1 (parametrised), `test_locking.py` +1 (parametrised); live `test_migration_0012_live.py` 5. Dev
  `1282 passed, 196 skipped`; live `1457 passed, 21 skipped` (arithmetic).
- **Task 2:** asset-sim: data rules, app, process, settings, the skeleton's seventh process. Tests:
  `test_asset_sim_data.py` 14, `test_asset_sim_app.py` 4; live `test_asset_sim_live.py` 3. Dev `1300 passed, 199
  skipped`; live `1478 passed, 21 skipped` (arithmetic).
- **Task 3:** `ops_core.tool_contracts`; mcp-read's asset tools, its asset-sim client and the committed input schemas.
  Tests: `test_tool_contracts.py` 5, `test_mcp_read_assets.py` 19; live `test_mcp_read_t16_live.py` 4. Dev `1324
  passed, 203 skipped`; live `1506 passed, 21 skipped` (arithmetic).
- **Task 4:** the search on the run's asset type; `TODO(T18)`; asset-sim in every live test that searches. Tests:
  `test_mcp_read_search.py` 4, `tests/plan_l/test_mcp_read_corpus.py` +1 (parametrised); live
  `test_mcp_read_t16_live.py` +1. Dev `1329 passed, 204 skipped`; live `1512 passed, 21 skipped` (arithmetic).
- **Task 5:** R029 in the worker's client. Tests: `test_worker_r029.py` 12; live `test_mcp_read_t16_live.py` +1. Dev
  `1341 passed, 205 skipped`; live `1525 passed, 21 skipped` (arithmetic).
- **Task 6:** the independent-process client reads an asset; the runbooks, READMEs and `docs/retrieval.md`. No new
  test. Dev `1341 passed, 205 skipped`; live `1525 passed, 21 skipped` (arithmetic).
- **Task 7:** handoff records, acceptance rows, errata 103-106, status, history, architecture, final gates. No tests.

The arithmetic, once: dev passed 1270 + 12 (Task 1: 10 + 1 + 1) = 1282, + 18 (Task 2: 14 + 4) = 1300, + 24 (Task 3:
5 + 19) = 1324, + 5 (Task 4: 4 + 1) = 1329, + 12 (Task 5) = 1341, + 0 = 1341; dev skipped 191, + 5 = 196, + 3 = 199,
+ 4 = 203, + 1 = 204, + 1 = 205, + 0 = 205. The live gate's passed count is the dev count plus the live-gated tests
(the dev skips minus the 21 that skip in both gates: 170 today; 175, 178, 182, 183, 184, 184 after Tasks 1-6), so
1457, 1478, 1506, 1512, 1525, 1525, always with 21 skipped. The dev numbers were measured on the scratch copy (see
"Counts"); the live ones are not measured.

---

### Task 1: Debt before code — revision 0012, `asset_scope`, the search's instant, mcp-read's startup check

**Files:**
- Create: `tests/plan_m/__init__.py`, `tests/plan_m/test_migration_0012.py`,
  `migrations/app/versions/0012_asset_scope.py`, `tests/e2e/test_migration_0012_live.py`
- Modify: `SESSION_STATE.md` (new debt section before `## Environment (observed)`), `pyproject.toml` (`testpaths`),
  `core/src/ops_core/privileges.py` (`DEFINER_FUNCTIONS`), `core/src/ops_core/persistence.py` (markers after
  `GOVERNED_CORPUS`; `Procedures`, `search_procedures`; `AssetScope` and `asset_scope` after it),
  `core/src/ops_core/locking.py` (`OBSERVED_UNITS`), `mcp-read/src/ops_mcp_read/server.py` (`envelope`,
  `search_response`, the search's return, the lifespan's checks), `tests/plan_e/test_transitions_table.py`
  (`REVISIONS`), `tests/plan_k/test_mcp_write_startup.py` (`test_mcp_read_does_not_ask_for_0010`),
  `tests/plan_d/test_mcp_read.py` (`Procedures`, `search_response`), `tests/plan_l/test_mcp_read_corpus.py`
  (`Procedures`), `tests/e2e/conftest.py` (`SEEDED_ALPHA`, `add_requester`), `tests/e2e/test_migrations_and_persistence.py`
  (`new_run`), `tests/e2e/test_migration_0011_live.py` (`handle_for`, the round trip), `tests/e2e/test_retrieval_baseline_live.py`
  (the requesters), `tests/e2e/test_mcp_read_t15_live.py` (R131's read half), `tests/e2e/test_mcp_write_t47_live.py`
  (R131's write half), `tests/e2e/test_migration_0008_live.py` (the entry set)

**Requirements:** SA:460 (erratum 104), SA:461 (errata 93, 106), SA:446, R028's definer half (ruling 7, erratum 105),
R131's read half complete (ruling 18), the Plan M debt list (SA:698).

**Interfaces:**
- Consumes: `app._resolve_handle(text, text, text)` (0009), `app._authority(text, text[])`, `app.current_time()`;
  revision 0011's `SEARCH_PROCEDURES_SCOPED` (its module, loaded by path); `privileges.function_grant_statements`;
  `persistence._call`, `assert_function_text`, `HandleRejected`; `tests.plan_l.test_migration_0011.revision`,
  `statements`, `VERSIONS`; `tests.plan_j.test_mcp_read_startup.start`; `tests.plan_k.test_mcp_write_startup.MarkerConn`;
  the live helpers `new_run`, `lease_for`, `investigate_job`, `read_handle`, `refused`, `purge_run`, and
  `test_migration_0011_live`'s `stage`, `handle_for`, `clock`, `cleanup`, `APP_FUNCTIONS`, `DAY`.
- Produces: `app.asset_scope(text, text) RETURNS TABLE (run_id uuid, tenant_id uuid, asset_id text, start_at
  timestamptz, end_at timestamptz, as_of timestamptz)`; `app.search_procedures_scoped(text, text, text, public.vector,
  text, integer, text) RETURNS TABLE (corpus_version text, retrieved_at timestamptz, results jsonb)` (the argument
  types are unchanged since 0011 and are `privileges.DEFINER_FUNCTIONS["search_procedures_scoped"][0]`);
  `persistence.ASSET_SCOPE`, `SEARCH_INSTANT`, `AssetScope`, `asset_scope(conn, *, handle, azp) -> AssetScope`,
  `Procedures(corpus_version, results, retrieved_at, truncated=False)`; `server.envelope(..., observed_at=None,
  truncated=False)`, `server.search_response(found)`; `tests.e2e.conftest.add_requester(conn, tenant_id, subject)`,
  `SEEDED_ALPHA`; `new_run(..., requester=None, asset_id="A17", interval=None)`.

- [ ] **Step 1a: Record both baselines**

Run `PYTHONUTF8=1 uv run python scripts/check.py` → `CHECK: GREEN` with pytest `1270 passed, 191 skipped`; with the
dev stack up and `uv run python scripts/skeleton.py status` showing every process down, run
`PYTHONUTF8=1 uv run python scripts/check.py --profile test` → `CHECK: GREEN` with `1440 passed, 21 skipped`, then
`git checkout -- reports/bootstrap reports/skeleton reports/auth reports/admission reports/leases reports/events
reports/outbox reports/mcp-read reports/mcp-write reports/retrieval`. Run `uv run python -I scripts/verify_handoff.py
--reference-code --manifest --contracts` → exit 0. Record the three lines in the report (Global Constraints,
"Counts"). A gate that is not GREEN stops the plan here, before anything is committed.

- [ ] **Step 1b: Record the base**

Run `git rev-parse --short HEAD` and write the hash it prints as `BASE=<hash>` in the report and in the SDD ledger
(`.superpowers/sdd/2026-10-18-first-slice-m-read-tools-asset-sim/progress.md`). Task 7's commit span is
`<base>..<last>`. `git status --short` must show only ` M docs/superpowers/research/2026-10-16-plan-k-inputs.md`,
which no step of this plan stages.

- [ ] **Step 1c: Commit the debt list (before any code)**

Edit 1 (`SESSION_STATE.md`, at the end of "Plan L debt list (T17; committed before coding) [R6-B7]"), replace:

```markdown
## Environment (observed)
```

with:

```markdown
## Plan M debt list (T16; committed before coding) [R6-B7]

Allowed shortcuts in T16, each with its owning task:
- vector mode: mcp-read's `vector_exact` → `mode=vector` translation and the nomic `search_query:` embedding it
  computes, with the embeddings themselves → T18 (Plan M ruling 1, erratum 103); until then mcp-read answers
  `vector_exact` with `UNSUPPORTED_MODE` after the handle resolution and the definer refuses `mode=vector`;
- the worker's calls to `get_asset_status` and `get_recent_alerts` and their results in the draft and the evidence
  bundle (BS:419), and SA:377's evidence-sufficiency rule → T20 (rulings 16 and 17);
- recording the status observation (`observed_at`, `revision`) where the grant can check its 5-minute freshness
  (R116, BS:476) → T21 (ruling 16);
- the worker's write calls (`create_incident` at mcp-write) keep T47's result check: no tool discovery and no
  result-schema check (mcp-write advertises its generated schemas, not the committed files) → T20;
- a run's asset is not tied to its tenant at admission (an alpha run may name beta's B22; asset-sim's own tenant filter
  answers NOT_FOUND, and the search then has no run type) → T21 (the asset guard; its review note names alpha-for-B22);
- a handle that dies between `asset_scope` and the asset-sim call still yields one read of the run's own asset (no
  write, no authority gained): documented, not prevented → no task (ruling 15);
- the fallback `corpus_version` is closed by T17 (the definer answers `none`) and the `UNSUPPORTED_MODE` order stays
  (the handle first) → no task (ruling 14);
- asset-sim and mcp-read read `data/corpus/` and `schemas/` from the checkout; packaging them, asset-sim's Dockerfile
  and `tests/` directory, TLS and container host names, and the network test that only mcp-read reaches asset-sim →
  T30 (ruling 5);
- the requester's membership is matched without an issuer (the run keeps none) → owner decision (erratum 105);
- the dev database stays at revision 0011 until the owner runs `scripts/skeleton.py migrate`; until then mcp-read
  refuses to start on it (it checks 0012) → owner input (ruling 3).

## Environment (observed)
```

```bash
git add SESSION_STATE.md
git commit -m "docs: declare Plan M's shortcuts before coding (T16 debt list)"
```

- [ ] **Step 2: Put `tests/plan_m` on the test path**

Edit 1 (`pyproject.toml`, `testpaths`), replace:

```toml
  "tests/plan_h", "tests/plan_i", "tests/plan_j", "tests/plan_k", "tests/plan_l", "tests/e2e",
```

with:

```toml
  "tests/plan_h", "tests/plan_i", "tests/plan_j", "tests/plan_k", "tests/plan_l", "tests/plan_m", "tests/e2e",
```

Create `tests/plan_m/__init__.py`:

```python
"""Plan M (T16): the read tools, asset_scope and asset-sim, without a database."""
```

- [ ] **Step 3: Write the failing revision tests**

Create `tests/plan_m/test_migration_0012.py`:

```python
"""Revision 0012 without a database (Plan M rulings 2, 3, 7 and 11).

Catches: `asset_scope` granted to anyone but `mcp_read`, reading the run before the handle has set the tenant, reading
the clock before the lease lock, taking the tenant or the asset from an argument, writing anything, or answering for
a run whose requester has lost the requester membership; a search that changed anything of 0011's body besides the
five named changes (the ranking and filters must stay byte for byte), forgets its instant or the membership re-check,
or still cuts the excerpt at 500 characters, or cuts silently; a CREATE OR REPLACE where the return type changes
(PostgreSQL refuses it); a downgrade that does not restore 0011's body and grant exactly; startup markers that are not
unique to 0012; mcp-read starting on a database without 0012; and a search answer stamped from the wall clock or
with a cut excerpt that leaves `truncated` false.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from ops_core import persistence, privileges
from ops_mcp_read import server

from tests.plan_e.test_transitions_table import REVISIONS
from tests.plan_j.test_mcp_read_startup import start
from tests.plan_k.test_mcp_write_startup import MarkerConn
from tests.plan_l.test_migration_0011 import VERSIONS, revision, statements

TOOL_RESULT = Draft202012Validator(
    json.loads(Path("schemas/tool-result.schema.json").read_text(encoding="utf-8")), format_checker=FormatChecker()
)
SEARCH = "search_procedures_scoped"
SEARCH_ARGS = "text, text, text, public.vector, text, integer, text"


def rev0012() -> Any:
    return revision("0012_asset_scope")


def test_upgrade_drops_the_search_then_creates_both_with_their_grants(monkeypatch: pytest.MonkeyPatch) -> None:
    module = rev0012()
    assert module.down_revision == "0011_governed_corpus"
    seen = statements(module, "upgrade", monkeypatch)
    assert seen == [
        f"DROP FUNCTION app.{SEARCH}({SEARCH_ARGS})",  # a changed return type: CREATE OR REPLACE would be refused
        module.ASSET_SCOPE,
        "REVOKE ALL ON FUNCTION app.asset_scope(text, text) FROM PUBLIC",
        "GRANT EXECUTE ON FUNCTION app.asset_scope(text, text) TO mcp_read",
        module.SEARCH_PROCEDURES_SCOPED,
        f"REVOKE ALL ON FUNCTION app.{SEARCH}({SEARCH_ARGS}) FROM PUBLIC",
        f"GRANT EXECUTE ON FUNCTION app.{SEARCH}({SEARCH_ARGS}) TO mcp_read",
    ]


def test_both_functions_are_granted_to_mcp_read_alone_with_the_matrix_signatures() -> None:
    module = rev0012()
    assert [(name, args, callers) for name, args, callers, _ in module.FUNCTIONS] == [
        ("asset_scope", "text, text", ("mcp_read",)),
        (SEARCH, SEARCH_ARGS, ("mcp_read",)),
    ]
    assert privileges.DEFINER_FUNCTIONS["asset_scope"] == ("text, text", ("mcp_read",))
    assert privileges.DEFINER_FUNCTIONS[SEARCH] == (SEARCH_ARGS, ("mcp_read",))  # unchanged since 0011
    assert "ALTER FUNCTION app.asset_scope(text, text) OWNER TO app_definer;" in module.ASSET_SCOPE


def test_the_search_is_0011s_body_with_exactly_the_five_changes() -> None:
    module = rev0012()
    body = module.SEARCH_PROCEDURES_SCOPED
    assert len(module.CHANGES_0012) == 5
    for old, new in reversed(module.CHANGES_0012):
        assert body.count(new) == 1, new[:60]
        body = body.replace(new, old)
    assert body == revision().SEARCH_PROCEDURES_SCOPED  # the ranking, filters and _min_rank byte for byte
    with pytest.raises(RuntimeError, match="no longer carries"):
        module.changed(revision().SEARCH_PROCEDURES_SCOPED.replace("left(c.body, 500)", "left(c.body, 400)"))


def test_asset_scope_sets_the_tenant_and_rechecks_the_requester_before_it_reads_the_run() -> None:
    body = rev0012().ASSET_SCOPE
    authority = body.index("PERFORM app._authority('asset_scope', ARRAY['mcp_read'])")
    handle = body.index("FROM app._resolve_handle(p_raw_handle, p_client_azp, 'read')")
    tenant = body.index("set_config('app.tenant_id', v_handle.tenant_id::text, true)")
    member = body.index("AND m.role = 'requester' AND m.active")
    run = body.index("SELECT * INTO v_run FROM runs r WHERE r.run_id = v_handle.run_id")
    clock = body.index("as_of := app.current_time()")
    assert authority < handle < tenant < member < run < clock
    assert "RAISE EXCEPTION 'handle_rejected' USING ERRCODE = 'OC008'" in body  # the one handle refusal (SA:355)
    assert (
        "RETURNS TABLE (run_id uuid, tenant_id uuid, asset_id text, start_at timestamptz, end_at timestamptz," in body
    )
    assert "p_tenant" not in body and "p_asset" not in body  # the tenant and the asset come from the handle only
    for verb in ("INSERT", "UPDATE", "DELETE"):
        assert f"{verb} " not in body.split("$fn$")[1], verb  # a reader only


def test_the_search_rechecks_the_requester_first_and_returns_its_instant() -> None:
    body = rev0012().SEARCH_PROCEDURES_SCOPED
    tenant = body.index("set_config('app.tenant_id', v_handle.tenant_id::text, true)")
    member = body.index("AND m.role = 'requester' AND m.active")
    vector = body.index("DETAIL = 'VECTOR_MODE_UNAVAILABLE'")
    first_read = min(body.index(f"FROM {t}") for t in ("corpus_ingestions", "document_states", "documents", "chunks"))
    clock = body.index("v_now := app.current_time()")
    instant = body.index("retrieved_at := v_now;")
    stop_words = body.index("results := '[]'::jsonb")
    assert tenant < member < vector < first_read < clock < instant < stop_words  # an empty answer carries it too
    assert "RETURNS TABLE (corpus_version text, retrieved_at timestamptz, results jsonb)" in body


def test_the_excerpt_is_the_whole_section_up_to_the_contracts_bound_and_says_when_it_is_cut() -> None:
    module = rev0012()
    schema = json.loads(Path("schemas/tool-result.schema.json").read_text(encoding="utf-8"))
    branch = next(
        b for b in schema["allOf"] if b["if"]["properties"].get("tool_name") == {"const": "search_procedures"}
    )
    bound = branch["then"]["properties"]["data"]["properties"]["results"]["items"]["properties"]["excerpt"]
    assert module.EXCERPT_CHARS_0012 == bound["maxLength"] == 8000
    body = module.SEARCH_PROCEDURES_SCOPED
    assert "left(c.body, 8000) AS excerpt," in body and "left(c.body, 500)" not in body
    assert "char_length(c.body) > 8000 AS excerpt_cut" in body and "'excerpt_cut', k.excerpt_cut)" in body


def test_the_downgrade_restores_0011s_search_exactly(monkeypatch: pytest.MonkeyPatch) -> None:
    assert statements(rev0012(), "downgrade", monkeypatch) == [
        "DROP FUNCTION app.asset_scope(text, text)",
        f"DROP FUNCTION app.{SEARCH}({SEARCH_ARGS})",
        revision().SEARCH_PROCEDURES_SCOPED,
        f"REVOKE ALL ON FUNCTION app.{SEARCH}({SEARCH_ARGS}) FROM PUBLIC",
        f"GRANT EXECUTE ON FUNCTION app.{SEARCH}({SEARCH_ARGS}) TO mcp_read",
    ]


def test_the_startup_markers_are_only_in_0012s_functions() -> None:
    module = rev0012()
    assert persistence.ASSET_SCOPE == ("app.asset_scope(text, text)", "as_of := app.current_time()")
    assert persistence.SEARCH_INSTANT == (f"app.{SEARCH}({SEARCH_ARGS})", "retrieved_at := v_now")
    assert persistence.ASSET_SCOPE[1] in module.ASSET_SCOPE
    assert persistence.SEARCH_INSTANT[1] in module.SEARCH_PROCEDURES_SCOPED
    assert persistence.GOVERNED_CORPUS[1] in module.SEARCH_PROCEDURES_SCOPED  # 0011's marker survives the re-creation
    for older in REVISIONS[: REVISIONS.index("0012_asset_scope")]:
        text = (VERSIONS / f"{older}.py").read_text(encoding="utf-8")
        assert persistence.ASSET_SCOPE[1] not in text and persistence.SEARCH_INSTANT[1] not in text, older


def test_mcp_read_refuses_a_database_without_0012(monkeypatch: pytest.MonkeyPatch) -> None:
    conn: Any = MarkerConn({persistence.HANDLE_BINDING[1], persistence.GOVERNED_CORPUS[1]})  # 0011, not 0012
    with pytest.raises(persistence.PersistenceError, match="predates this service"):
        start(monkeypatch, conn)
    assert conn.closed
    assert conn.asked[-1] == (persistence.ASSET_SCOPE[1], persistence.ASSET_SCOPE[0])


def test_a_search_answer_carries_the_definers_instant_and_its_cut() -> None:
    hit = persistence.Procedure(
        evidence_id="ALPHA-PUMP-SEAL:v2:inspection",
        document_id="ALPHA-PUMP-SEAL",
        version="2",
        section="inspection",
        content_sha256="a" * 64,
        excerpt="x" * 8000,
        effective_from=datetime(2026, 9, 1, tzinfo=UTC),
        rank=0.5,
    )
    decided = datetime(2026, 10, 6, 12, 0, 0, 750000, tzinfo=UTC)  # the database's instant, not the wall clock
    for cut in (False, True):
        doc = server.search_response(persistence.Procedures("corpus-1", (hit,), decided, cut))
        TOOL_RESULT.validate(doc)
        assert doc["data"]["results"][0]["retrieved_at"] == doc["observed_at"] == "2026-10-06T12:00:00Z"
        assert doc["truncated"] is cut  # ruling 11: never a silent cut
```

Run: `uv run python -m pytest tests/plan_m/test_migration_0012.py -q`
Expected: `10 failed`: eight with `FileNotFoundError` (the revision file does not exist yet),
`test_mcp_read_refuses_a_database_without_0012` with `Failed: DID NOT RAISE PersistenceError` (mcp-read still starts
at 0011), and `test_a_search_answer_carries_the_definers_instant_and_its_cut` with `TypeError:
Procedures.__init__() takes 3 positional arguments but 5 were given` (measured on the scratch copy).

- [ ] **Step 4: The revision, the matrix, persistence and mcp-read**

The search body is derived from 0011's frozen text by the five `CHANGES_0012` replacements (the 0009 pattern); the
complete resulting body is printed after the file for review.

Create `migrations/app/versions/0012_asset_scope.py`:

```python
"""The read tools' scope (T16; Plan M rulings 2, 3, 7 and 11): `asset_scope`, and `search_procedures_scoped` again with
the instant it decided permission, the requester's membership re-checked and the whole section as its excerpt.

Revision ID: 0012_asset_scope
Revises: 0011_governed_corpus

- `asset_scope(raw_handle, client_azp)` (SA:460 with the caller's `azp`, erratum 104): `mcp_read` only. The handle
  decides the run and the tenant through `_resolve_handle` (the lease FOR SHARE first, then the fence, expiry,
  revocation, `azp` and the read server); it returns one row, the run's `run_id`, `tenant_id`, `asset_id` and
  `[start_at, end_at)` with `as_of`, `app.current_time()` read after the lease lock: the instant asset-sim answers at
  (ruling 4). It checks no tool: the allowlist stays in Python (erratum 19), as for the search.
- `search_procedures_scoped` is re-created from revision 0011's own body with five textual changes and nothing else
  (ranking, filters and `_min_rank` stay byte for byte; a unit test reverses the changes and compares): it returns
  `(corpus_version, retrieved_at, results)`, `retrieved_at` being the instant its effectiveness rule ran at, which the
  tool stamps instead of the wall clock (Plan L final review, M4); the excerpt is the whole section, bounded at the
  contract's 8000 characters, and a row whose body was longer says so (`excerpt_cut`), which the tool turns into the
  envelope's `truncated` (ruling 11). CREATE OR REPLACE cannot change a return type, so the function is dropped and
  created again, and its grant applied again.
- Both re-check the run's requester at read time (R028, ruling 7): an active `requester` membership in the run's
  tenant, matched by tenant, subject and role because the run keeps no issuer (erratum 105); without one the call is
  refused exactly as a dead handle is (`OC008`, one message, SA:355).

The downgrade drops `asset_scope` and restores 0011's function exactly, from 0011's own frozen body (0009's pattern).
"""

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic import op
from ops_core import privileges

revision = "0012_asset_scope"
down_revision = "0011_governed_corpus"
branch_labels = None
depends_on = None


def _applied(name: str) -> ModuleType:
    """An applied revision's module, loaded by path (the versions directory is not a package)."""
    spec = importlib.util.spec_from_file_location(f"applied_{name}", Path(__file__).with_name(f"{name}.py"))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"revision {name} is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REV0011 = _applied("0011_governed_corpus")
HEADER = "LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp SET app.tenant_id = ''"
SEARCH_ARGS = "text, text, text, public.vector, text, integer, text"
EXCERPT_CHARS_0012 = 8000  # the tool contract's excerpt bound (schemas/tool-result.schema.json)

# R028 (ruling 7), the same block in both functions: after the handle has set the tenant, so RLS admits the run's row
# and its memberships, and before anything else is read.
MEMBERSHIP_CHECK = """\
    -- R028 (Plan M ruling 7): the run's requester must still hold an active requester membership in the run's
    -- tenant, or the call is refused as a dead handle is (SA:355). The run keeps no issuer: tenant, subject and
    -- role identify the row (erratum 105).
    IF NOT EXISTS (SELECT 1 FROM runs r JOIN memberships m ON m.tenant_id = r.tenant_id AND m.subject = r.requester
                   WHERE r.run_id = v_handle.run_id AND m.role = 'requester' AND m.active) THEN
        RAISE EXCEPTION 'handle_rejected' USING ERRCODE = 'OC008';
    END IF;
"""

ASSET_SCOPE = f"""
CREATE OR REPLACE FUNCTION app.asset_scope(p_raw_handle text, p_client_azp text)
RETURNS TABLE (run_id uuid, tenant_id uuid, asset_id text, start_at timestamptz, end_at timestamptz,
               as_of timestamptz)
{HEADER} AS $fn$
DECLARE
    v_handle record;
    v_run runs%ROWTYPE;
BEGIN
    PERFORM app._authority('asset_scope', ARRAY['mcp_read']);
    -- The handle decides the run and the tenant (BS:362), never an argument: the lease FOR SHARE first, then the
    -- fence, expiry, revocation, azp and the read server. The tool allowlist stays in Python (erratum 19).
    SELECT * INTO v_handle FROM app._resolve_handle(p_raw_handle, p_client_azp, 'read');
    PERFORM set_config('app.tenant_id', v_handle.tenant_id::text, true);
{MEMBERSHIP_CHECK}    SELECT * INTO v_run FROM runs r WHERE r.run_id = v_handle.run_id;
    run_id := v_run.run_id;
    tenant_id := v_handle.tenant_id;
    asset_id := v_run.asset_id;
    start_at := v_run.start_at;
    end_at := v_run.end_at;
    as_of := app.current_time();  -- the instant asset-sim answers at; read after the lease lock (SA:157)
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION app.asset_scope(text, text) OWNER TO app_definer;
"""

# Revision 0011's body, changed in exactly these places; each `old` must occur once (checked before anything runs).
TENANT_0011 = "    PERFORM set_config('app.tenant_id', v_handle.tenant_id::text, true);\n"
CLOCK_0011 = (
    "    v_now := app.current_time();  -- the test clock in the test profile; read after the lease lock (SA:157)\n"
)
INSTANT_0012 = (
    "    retrieved_at := v_now;  -- the instant permission was decided; the tool stamps it (Plan M ruling 3)\n"
)
CHANGES_0012: tuple[tuple[str, str], ...] = (
    (
        "RETURNS TABLE (corpus_version text, results jsonb)\n",
        "RETURNS TABLE (corpus_version text, retrieved_at timestamptz, results jsonb)\n",
    ),
    (TENANT_0011, TENANT_0011 + MEMBERSHIP_CHECK),
    (CLOCK_0011, CLOCK_0011 + INSTANT_0012),
    (
        "left(c.body, 500) AS excerpt, p.effective_from,",
        (
            f"left(c.body, {EXCERPT_CHARS_0012}) AS excerpt,\n"
            f"               char_length(c.body) > {EXCERPT_CHARS_0012} AS excerpt_cut, p.effective_from,"
        ),
    ),
    (
        "'effective_from', k.effective_from, 'rank', k.rank)\n",
        (
            "'effective_from', k.effective_from, 'rank', k.rank,\n"
            "                                                 'excerpt_cut', k.excerpt_cut)\n"
        ),
    ),
)


def changed(body: str) -> str:
    """Revision 0011's search body with this revision's changes applied.

    Raises:
        RuntimeError: a change's text is not in the body exactly once (0011's body is not the one this revision was
            written against).
    """
    for old, new in CHANGES_0012:
        if body.count(old) != 1:
            raise RuntimeError("revision 0011's search_procedures_scoped no longer carries a text 0012 changes")
        body = body.replace(old, new)
    return body


SEARCH_PROCEDURES_SCOPED = changed(REV0011.SEARCH_PROCEDURES_SCOPED)
# (name, argument types, callers, body): frozen here (N1); the newest-revision test reads this tuple.
FUNCTIONS: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("asset_scope", "text, text", ("mcp_read",), ASSET_SCOPE),
    ("search_procedures_scoped", SEARCH_ARGS, ("mcp_read",), SEARCH_PROCEDURES_SCOPED),
)
# What downgrade() re-creates, from the applied revision's own body: (name, args, callers, body).
RESTORED: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("search_procedures_scoped", SEARCH_ARGS, ("mcp_read",), REV0011.SEARCH_PROCEDURES_SCOPED),
)
DROP_ASSET_SCOPE = "DROP FUNCTION app.asset_scope(text, text)"
DROP_SEARCH = f"DROP FUNCTION app.search_procedures_scoped({SEARCH_ARGS})"


def upgrade() -> None:
    """The search dropped (its return type changes), then each function's body and its grants: REVOKE from PUBLIC,
    then EXECUTE to `mcp_read` alone (SA:446)."""
    op.execute(DROP_SEARCH)
    for name, args, callers, body in FUNCTIONS:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)


def downgrade() -> None:
    """Back to 0011: `asset_scope` dropped, and the search dropped and created again from 0011's body with its
    grants; no row is touched."""
    op.execute(DROP_ASSET_SCOPE)
    op.execute(DROP_SEARCH)
    for name, args, callers, body in RESTORED:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)
```

For review, the two bodies this revision executes (the search exactly as `changed()` renders it from 0011; nothing
else in it differs from 0011's):

```sql
CREATE OR REPLACE FUNCTION app.search_procedures_scoped(p_raw_handle text, p_client_azp text, p_query text,
                                                      p_query_embedding public.vector(768), p_asset_type text,
                                                      p_limit integer, p_mode text)
RETURNS TABLE (corpus_version text, retrieved_at timestamptz, results jsonb)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp SET app.tenant_id = '' AS $fn$
DECLARE
    v_handle record;
    v_now timestamptz;
    v_lexemes text[];
    v_query tsquery;
BEGIN
    PERFORM app._authority('search_procedures_scoped', ARRAY['mcp_read']);
    -- The handle decides the tenant (BS:362), never an argument: the lease FOR SHARE first, then the fence, expiry,
    -- revocation, azp and the read server, as resolve_invocation. The run-state allowlist stays in Python (erratum 19).
    SELECT * INTO v_handle FROM app._resolve_handle(p_raw_handle, p_client_azp, 'read');
    PERFORM set_config('app.tenant_id', v_handle.tenant_id::text, true);
    -- R028 (Plan M ruling 7): the run's requester must still hold an active requester membership in the run's
    -- tenant, or the call is refused as a dead handle is (SA:355). The run keeps no issuer: tenant, subject and
    -- role identify the row (erratum 105).
    IF NOT EXISTS (SELECT 1 FROM runs r JOIN memberships m ON m.tenant_id = r.tenant_id AND m.subject = r.requester
                   WHERE r.run_id = v_handle.run_id AND m.role = 'requester' AND m.active) THEN
        RAISE EXCEPTION 'handle_rejected' USING ERRCODE = 'OC008';
    END IF;
    IF p_mode = 'vector' THEN
        -- TODO(T18): exact pgvector search over app.embeddings under the same filters (R034).
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'VECTOR_MODE_UNAVAILABLE';
    END IF;
    IF p_mode IS DISTINCT FROM 'lexical' OR p_query IS NULL OR char_length(p_query) NOT BETWEEN 1 AND 500
       OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 8
       OR (p_asset_type IS NOT NULL AND char_length(p_asset_type) NOT BETWEEN 1 AND 40) THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'BAD_ARGUMENT';
    END IF;
    -- The tenant's latest ingestion names the corpus it searches; "none" before the first one (Plan L ruling 17).
    corpus_version := coalesce((SELECT i.corpus_version FROM corpus_ingestions i
                                WHERE i.tenant_id = v_handle.tenant_id ORDER BY i.seq DESC LIMIT 1), 'none');
    v_now := app.current_time();  -- the test clock in the test profile; read after the lease lock (SA:157)
    retrieved_at := v_now;  -- the instant permission was decided; the tool stamps it (Plan M ruling 3)
    -- The OR of the query's own lexemes (Plan L ruling 18), so a whole user message still matches: anything but
    -- a-z and 0-9 becomes a space first, so every lexeme is a plain word the 'simple' parser passes through unchanged.
    v_lexemes := tsvector_to_array(to_tsvector('english', regexp_replace(lower(p_query), '[^a-z0-9]+', ' ', 'g')));
    IF cardinality(v_lexemes) = 0 THEN
        results := '[]'::jsonb;  -- only stop words: nothing to match, not an error
        RETURN NEXT;
        RETURN;
    END IF;
    v_query := to_tsquery('simple', array_to_string(v_lexemes, ' | '));
    WITH latest AS (
        -- AM-20 principle 2: the latest state is the highest seq, never a timestamp.
        SELECT DISTINCT ON (s.tenant_id, s.document_id, s.version)
               s.tenant_id, s.document_id, s.version, s.status, s.effective_from, s.effective_to
        FROM document_states s
        ORDER BY s.tenant_id, s.document_id, s.version, s.seq DESC
    ), effective AS (
        SELECT d.tenant_id, d.document_id, d.version, d.supersedes, d.asset_family, l.effective_from
        FROM documents d JOIN latest l USING (tenant_id, document_id, version)
        WHERE l.status = 'approved' AND l.effective_from <= v_now AND (l.effective_to IS NULL OR v_now < l.effective_to)
    ), permitted AS (
        -- Retired versions never come back (ruling 7, round 1): a later version that has left draft and reached its
        -- own effective_from retires every earlier one, whatever happens to it afterwards (revoked, expired).
        SELECT e.* FROM effective e
        WHERE NOT EXISTS (SELECT 1 FROM latest n WHERE n.tenant_id = e.tenant_id AND n.document_id = e.document_id
                                                    AND n.version::integer > e.version::integer
                                                    AND n.status <> 'draft' AND n.effective_from <= v_now)
          AND (p_asset_type IS NULL OR e.asset_family IS NULL OR e.asset_family = p_asset_type)
    ), ranked AS (
        SELECT c.evidence_id, c.document_id, c.version, c.section, c.content_sha256,
               left(c.body, 8000) AS excerpt,
               char_length(c.body) > 8000 AS excerpt_cut, p.effective_from, ts_rank_cd(c.search, v_query) AS rank
        FROM chunks c JOIN permitted p USING (tenant_id, document_id, version)
        WHERE c.search @@ v_query
    ), kept AS (
        -- Ranks at or below the minimum dropped; the byte-order tie-break makes a retry cite the same evidence
        -- whatever the database's collation (BUILD_SPEC section 6).
        SELECT * FROM ranked r WHERE r.rank > app._min_rank()
        ORDER BY r.rank DESC, r.evidence_id COLLATE "C" LIMIT p_limit
    )
    SELECT coalesce(jsonb_agg(jsonb_build_object('evidence_id', k.evidence_id, 'document_id', k.document_id,
                                                 'version', k.version, 'section', k.section,
                                                 'content_sha256', k.content_sha256, 'excerpt', k.excerpt,
                                                 'effective_from', k.effective_from, 'rank', k.rank,
                                                 'excerpt_cut', k.excerpt_cut)
                              ORDER BY k.rank DESC, k.evidence_id COLLATE "C"), '[]'::jsonb)
    INTO results FROM kept k;
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION app.search_procedures_scoped(text, text, text, public.vector, text, integer, text) OWNER TO app_definer;
```

```sql
CREATE OR REPLACE FUNCTION app.asset_scope(p_raw_handle text, p_client_azp text)
RETURNS TABLE (run_id uuid, tenant_id uuid, asset_id text, start_at timestamptz, end_at timestamptz,
               as_of timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp SET app.tenant_id = '' AS $fn$
DECLARE
    v_handle record;
    v_run runs%ROWTYPE;
BEGIN
    PERFORM app._authority('asset_scope', ARRAY['mcp_read']);
    -- The handle decides the run and the tenant (BS:362), never an argument: the lease FOR SHARE first, then the
    -- fence, expiry, revocation, azp and the read server. The tool allowlist stays in Python (erratum 19).
    SELECT * INTO v_handle FROM app._resolve_handle(p_raw_handle, p_client_azp, 'read');
    PERFORM set_config('app.tenant_id', v_handle.tenant_id::text, true);
    -- R028 (Plan M ruling 7): the run's requester must still hold an active requester membership in the run's
    -- tenant, or the call is refused as a dead handle is (SA:355). The run keeps no issuer: tenant, subject and
    -- role identify the row (erratum 105).
    IF NOT EXISTS (SELECT 1 FROM runs r JOIN memberships m ON m.tenant_id = r.tenant_id AND m.subject = r.requester
                   WHERE r.run_id = v_handle.run_id AND m.role = 'requester' AND m.active) THEN
        RAISE EXCEPTION 'handle_rejected' USING ERRCODE = 'OC008';
    END IF;
    SELECT * INTO v_run FROM runs r WHERE r.run_id = v_handle.run_id;
    run_id := v_run.run_id;
    tenant_id := v_handle.tenant_id;
    asset_id := v_run.asset_id;
    start_at := v_run.start_at;
    end_at := v_run.end_at;
    as_of := app.current_time();  -- the instant asset-sim answers at; read after the lease lock (SA:157)
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION app.asset_scope(text, text) OWNER TO app_definer;
```

Edit 1 (`core/src/ops_core/privileges.py`, `DEFINER_FUNCTIONS`), replace:

```python
    # T17 (Plan L ruling 1): SA:461 with the caller's azp second, as the write path since T47 (erratum 93).
    "search_procedures_scoped": ("text, text, text, public.vector, text, integer, text", ("mcp_read",)),
```

with:

```python
    # T17 (Plan L ruling 1): SA:461 with the caller's azp second, as the write path since T47 (erratum 93).
    "search_procedures_scoped": ("text, text, text, public.vector, text, integer, text", ("mcp_read",)),
    # T16 (Plan M ruling 2): SA:460 with the caller's azp, for the same reason (erratum 104).
    "asset_scope": ("text, text", ("mcp_read",)),
```

Edit 2 (`core/src/ops_core/persistence.py`, after `WRITE_PATH`), replace:

```python
# so it refuses to start without it (Plan L rulings 21 and 24). The same rule: a later revision that re-creates the
# function keeps this text or changes it here in the same commit.
GOVERNED_CORPUS: Final = (
    "app.search_procedures_scoped(text, text, text, public.vector, text, integer, text)",
    "ts_rank_cd(c.search, v_query)",
)
```

with:

```python
# so it refuses to start without it (Plan L rulings 21 and 24). The same rule: a later revision that re-creates the
# function keeps this text or changes it here in the same commit (revision 0012 keeps it: the ranking is unchanged).
GOVERNED_CORPUS: Final = (
    "app.search_procedures_scoped(text, text, text, public.vector, text, integer, text)",
    "ts_rank_cd(c.search, v_query)",
)
# Revision 0012 (T16): `asset_scope` exists, and `search_procedures_scoped` returns the instant it decided permission
# at. mcp-read calls both with these shapes, so it refuses to start without them (Plan M ruling 3). The same rule: a
# later revision that re-creates either function keeps its text or changes it here in the same commit.
ASSET_SCOPE: Final = ("app.asset_scope(text, text)", "as_of := app.current_time()")
SEARCH_INSTANT: Final = (
    "app.search_procedures_scoped(text, text, text, public.vector, text, integer, text)",
    "retrieved_at := v_now",
)
```

Edit 3 (`core/src/ops_core/persistence.py`, `Procedures` and the head of `search_procedures`), replace:

```python
@dataclass(frozen=True)
class Procedures:
    """A search's answer: the tenant's latest ingested corpus version ("none" before any) and the sections, best
    first."""

    corpus_version: str
    results: tuple[Procedure, ...]
```

with:

```python
@dataclass(frozen=True)
class Procedures:
    """A search's answer: the tenant's latest ingested corpus version ("none" before any), the sections, best first,
    the database instant the definer decided permission at (`retrieved_at`, revision 0012) and whether any section
    was longer than the contract's excerpt bound and was cut (`truncated`, Plan M ruling 11)."""

    corpus_version: str
    results: tuple[Procedure, ...]
    retrieved_at: datetime
    truncated: bool = False
```

Edit 4 (`core/src/ops_core/persistence.py`, `search_procedures`' docstring), replace:

```python
        HandleRejected: the handle does not resolve for mcp-read (the definer's `_resolve_handle`).
        Refused: an argument outside the tool's bounds (`BAD_ARGUMENT`).
```

with:

```python
        HandleRejected: the handle does not resolve for mcp-read (the definer's `_resolve_handle`), or the run's
            requester no longer holds an active requester membership (R028, revision 0012).
        Refused: an argument outside the tool's bounds (`BAD_ARGUMENT`).
```

Edit 5 (`core/src/ops_core/persistence.py`, the end of `search_procedures`), replace:

```python
    if row is None:
        raise PersistenceError("search_procedures_scoped returned nothing")
    results = tuple(
```

with:

```python
    if row is None:
        raise PersistenceError("search_procedures_scoped returned nothing")
    hits = row["results"]
    results = tuple(
```

Edit 6 (`core/src/ops_core/persistence.py`, the same function), replace:

```python
            rank=float(hit["rank"]),
        )
        for hit in row["results"]
    )
    return Procedures(str(row["corpus_version"]), results)
```

with:

```python
            rank=float(hit["rank"]),
        )
        for hit in hits
    )
    # `excerpt_cut` says the definer cut a body at the contract's bound (ruling 11); it reaches no tool result, only
    # the envelope's `truncated`.
    cut = any(hit["excerpt_cut"] is True for hit in hits)
    return Procedures(str(row["corpus_version"]), results, row["retrieved_at"], cut)


@dataclass(frozen=True)
class AssetScope:
    """What `asset_scope` returns for a read handle: the run, its tenant, its asset and fixed `[start_at, end_at)`,
    and `as_of`, the database instant asset-sim answers at (Plan M rulings 2 and 4)."""

    run_id: UUID
    tenant_id: UUID
    asset_id: str
    start_at: datetime
    end_at: datetime
    as_of: datetime


async def asset_scope(conn: Conn, *, handle: str, azp: str) -> AssetScope:
    """The handle's run's asset and interval for forwarding to asset-sim (SA:460 with the caller's `azp`, erratum
    104). The handle never reaches a log.

    Raises:
        HandleRejected: the handle does not resolve for mcp-read, or the run's requester no longer holds an active
            requester membership in its tenant (R028); one refusal for every cause (SA:355).
    """
    row = await _call(conn, "SELECT * FROM app.asset_scope(%s, %s)", (handle, azp))
    if row is None:
        raise HandleRejected("invocation handle rejected")
    return AssetScope(
        run_id=UUID(str(row["run_id"])),
        tenant_id=UUID(str(row["tenant_id"])),
        asset_id=str(row["asset_id"]),
        start_at=row["start_at"],
        end_at=row["end_at"],
        as_of=row["as_of"],
    )
```

Edit 7 (`core/src/ops_core/locking.py`, `OBSERVED_UNITS`), replace:

```python
    "mcp-read search_procedures_scoped": ("run_lease",),  # T17: the handle's lease FOR SHARE, then plain reads
```

with:

```python
    "mcp-read search_procedures_scoped": ("run_lease",),  # T17: the handle's lease FOR SHARE, then plain reads
    # T16 (revision 0012): the same lease FOR SHARE; the run and its requester's membership are plain reads.
    "mcp-read asset_scope": ("run_lease",),
```

Edit 8 (`mcp-read/src/ops_mcp_read/server.py`, `envelope` and `search_response`), replace:

```python
def envelope(tool_name: str, *, data: dict[str, Any] | None = None, error: dict[str, Any] | None = None) -> ToolResult:
    """Wrap data or an error in the AM-80 envelope with a fresh request_id."""
    return {
        "tool_name": tool_name,
        "request_id": str(uuid4()),
        "status": "error" if error is not None else "ok",
        "observed_at": stamp(datetime.now(UTC)),
        "truncated": False,
        "data": None if error is not None else data,
        "error": error,
    }


def search_response(found: persistence.Procedures, *, now: datetime) -> ToolResult:
    """The tool's answer from what `search_procedures_scoped` returned; database-free so the contract test can validate
    it. The rank stays behind: the contract has no score, and the model never sees one (docs/retrieval.md)."""
    results = [
        {
            "evidence_id": hit.evidence_id,
            "document_id": hit.document_id,
            "version": hit.version,
            "section": hit.section,
            "content_sha256": hit.content_sha256,
            "excerpt": hit.excerpt,
            "effective_from": stamp(hit.effective_from),
            "retrieved_at": stamp(now),
        }
        for hit in found.results
    ]
    return envelope(
        "search_procedures",
        data={"results": results, "retrieval_mode": "lexical", "corpus_version": found.corpus_version},
    )
```

with:

```python
def envelope(
    tool_name: str,
    *,
    data: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    observed_at: datetime | None = None,
    truncated: bool = False,
) -> ToolResult:
    """Wrap data or an error in the AM-80 envelope with a fresh request_id. `observed_at` is the database instant the
    answer was decided at (Plan M ruling 3); a refusal before any database unit has none and takes the wall clock."""
    return {
        "tool_name": tool_name,
        "request_id": str(uuid4()),
        "status": "error" if error is not None else "ok",
        "observed_at": stamp(datetime.now(UTC) if observed_at is None else observed_at),
        "truncated": truncated,
        "data": None if error is not None else data,
        "error": error,
    }


def search_response(found: persistence.Procedures) -> ToolResult:
    """The tool's answer from what `search_procedures_scoped` returned; database-free so the contract test can validate
    it. The rank stays behind: the contract has no score, and the model never sees one (docs/retrieval.md). Every
    `retrieved_at` and the envelope's `observed_at` are the instant the definer decided permission at, never the wall
    clock (Plan M ruling 3, Plan L final review M4), and a section cut at the contract's bound sets `truncated`
    (ruling 11)."""
    retrieved_at = stamp(found.retrieved_at)
    results = [
        {
            "evidence_id": hit.evidence_id,
            "document_id": hit.document_id,
            "version": hit.version,
            "section": hit.section,
            "content_sha256": hit.content_sha256,
            "excerpt": hit.excerpt,
            "effective_from": stamp(hit.effective_from),
            "retrieved_at": retrieved_at,
        }
        for hit in found.results
    ]
    return envelope(
        "search_procedures",
        data={"results": results, "retrieval_mode": "lexical", "corpus_version": found.corpus_version},
        observed_at=found.retrieved_at,
        truncated=found.truncated,
    )
```

Edit 9 (`mcp-read/src/ops_mcp_read/server.py`, the end of the tool), replace:

```python
        return search_response(found, now=datetime.now(UTC))
```

with:

```python
        return search_response(found)
```

Edit 10 (`mcp-read/src/ops_mcp_read/server.py`, the lifespan's checks), replace:

```python
                await persistence.assert_function_text(conn, *persistence.GOVERNED_CORPUS)  # 0011 (T17)
```

with:

```python
                await persistence.assert_function_text(conn, *persistence.GOVERNED_CORPUS)  # 0011 (T17)
                await persistence.assert_function_text(conn, *persistence.ASSET_SCOPE)  # 0012 (T16)
                await persistence.assert_function_text(conn, *persistence.SEARCH_INSTANT)  # 0012 (T16)
```

Edit 11 (`tests/plan_e/test_transitions_table.py`, `REVISIONS`), replace:

```python
    "0011_governed_corpus",
    "tc_0001_test_clock",
```

with:

```python
    "0011_governed_corpus",
    "0012_asset_scope",
    "tc_0001_test_clock",
```

Edit 12 (`tests/plan_k/test_mcp_write_startup.py`, `test_mcp_read_does_not_ask_for_0010`), replace:

```python
    conn: Any = MarkerConn({persistence.HANDLE_BINDING[1], persistence.GOVERNED_CORPUS[1]})
```

with:

```python
    present = (
        persistence.HANDLE_BINDING,
        persistence.GOVERNED_CORPUS,
        persistence.ASSET_SCOPE,
        persistence.SEARCH_INSTANT,
    )
    conn: Any = MarkerConn({marker for _, marker in present})  # every mcp-read revision through 0012 (T16)
```

Edit 13 (`tests/plan_d/test_mcp_read.py`, three places; the instant is the definer's now, so the test hands it in),
replace:

```python
    return persistence.Procedures("corpus-1", hits)
```

with:

```python
    return persistence.Procedures("corpus-1", hits, NOW)
```

then replace:

```python
    doc = server.search_response(found, now=NOW)
```

with:

```python
    doc = server.search_response(found)
```

then replace:

```python
    nothing = server.search_response(persistence.Procedures("none", ()), now=NOW)
```

with:

```python
    nothing = server.search_response(persistence.Procedures("none", (), NOW))
```

Edit 14 (`tests/plan_l/test_mcp_read_corpus.py`, `Database.search_procedures`), replace:

```python
        return persistence.Procedures("corpus-1", (HIT,))
```

with:

```python
        return persistence.Procedures("corpus-1", (HIT,), datetime(2026, 10, 16, 12, 0, tzinfo=UTC))
```

Run: `uv run ruff format migrations/app/versions/0012_asset_scope.py core/src mcp-read/src tests/plan_m tests/plan_e
tests/plan_k tests/plan_d tests/plan_l && uv run ruff check --fix migrations core mcp-read tests`, then
`uv run python -m pytest tests/plan_m tests/plan_d tests/plan_e tests/plan_h tests/plan_j tests/plan_k tests/plan_l -q`
Expected: every test passes (`test_migration_0012.py` 10 passed; the transitions module's bind scan and
`test_locking.py`'s documented units each gain one parametrised case).

- [ ] **Step 5: The live half: a requester for random tenants, R131's equality, the 0012 definer tests**

Edit 1 (`tests/e2e/conftest.py`, after `SEEDED_TENANTS`), replace:

```python
SEEDED_TENANTS = {"3ea79c95-914c-52cb-9d10-c4e19dda8ff7", "5ab45c2c-1e12-5a0c-a2b9-66cd2ff05201"}
```

with:

```python
SEEDED_TENANTS = {"3ea79c95-914c-52cb-9d10-c4e19dda8ff7", "5ab45c2c-1e12-5a0c-a2b9-66cd2ff05201"}
SEEDED_ALPHA = "3ea79c95-914c-52cb-9d10-c4e19dda8ff7"


async def add_requester(conn: persistence.Conn, tenant_id: object, subject: object) -> None:
    """An active requester membership for `subject` in a random test tenant (T16): `asset_scope` and
    `search_procedures_scoped` re-check the run's requester at read time (revision 0012, R028), and a fresh tenant
    has no members. The issuer is the seeded rows' own; `purge_tenant` removes the row with the tenant."""
    if str(tenant_id) in SEEDED_TENANTS:
        raise ValueError("a seeded tenant's memberships are the migration's, never a test's")
    await conn.execute(
        "INSERT INTO app.memberships (tenant_id, issuer, subject, role, synced_at)"
        " SELECT %s, m.issuer, %s, 'requester', app.current_time() FROM app.memberships m"
        " WHERE m.tenant_id = %s LIMIT 1",
        (tenant_id, subject, SEEDED_ALPHA),
    )
```

Edit 2 (`tests/e2e/test_migrations_and_persistence.py`, `new_run`'s signature), replace:

```python
async def new_run(conn: persistence.Conn, tenant_id: UUID | None = None, *, api: persistence.Conn) -> tuple:
    """A QUEUED run in a fresh conversation; on a new random tenant unless a seeded one is given. `conn` is the
    superuser (seeding), `api` the role connection that may call create_run."""
```

with:

```python
async def new_run(
    conn: persistence.Conn,
    tenant_id: UUID | None = None,
    *,
    api: persistence.Conn,
    requester: UUID | None = None,
    asset_id: str = "A17",
    interval: tuple[datetime, datetime] | None = None,
) -> tuple:
    """A QUEUED run in a fresh conversation; on a new random tenant unless a seeded one is given. `conn` is the
    superuser (seeding), `api` the role connection that may call create_run. The requester defaults to ALEX (alpha's
    requester), the asset to A17 and the interval to the 24 hours before now (T16 tests choose others)."""
```

Edit 3 (`tests/e2e/test_migrations_and_persistence.py`, `new_run`'s body), replace:

```python
        end = datetime.now(UTC).replace(microsecond=0)
        async with api.transaction():  # the function sets its own tenant
            run, _ = await persistence.create_run(
                api,
                tenant_id=tenant,
                conversation_id=conv,
                message_id=msg,
                requester=UUID(ALEX),
                intent=Intent.INVESTIGATE,
                asset_id="A17",
                start_at=end - timedelta(hours=24),
                end_at=end,
            )
```

with:

```python
        end = datetime.now(UTC).replace(microsecond=0)
        start_at, end_at = interval or (end - timedelta(hours=24), end)
        async with api.transaction():  # the function sets its own tenant
            run, _ = await persistence.create_run(
                api,
                tenant_id=tenant,
                conversation_id=conv,
                message_id=msg,
                requester=requester or UUID(ALEX),
                intent=Intent.INVESTIGATE,
                asset_id=asset_id,
                start_at=start_at,
                end_at=end_at,
            )
```

Edit 4 (`tests/e2e/test_migration_0011_live.py`, the imports), replace:

```python
from tests.e2e.conftest import lease_for, purge_corpus, purge_run, purge_tenant
from tests.e2e.test_definers_run_path_live import refused
from tests.e2e.test_fenced_definers_live import investigate_job, read_handle
from tests.e2e.test_migrations_and_persistence import new_run
```

with:

```python
from tests.e2e.conftest import add_requester, lease_for, purge_corpus, purge_run, purge_tenant
from tests.e2e.test_definers_run_path_live import refused
from tests.e2e.test_fenced_definers_live import investigate_job, read_handle
from tests.e2e.test_migrations_and_persistence import ALEX, new_run
```

Edit 5 (`tests/e2e/test_migration_0011_live.py`, `handle_for`), replace:

```python
    """A run in `tenant` (a fresh random tenant when None), its lease and a read handle: (tenant, run, handle)."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    tenant_id, _, run = await new_run(app_conn, tenant, api=api)
```

with:

```python
    """A run in `tenant` (a fresh random tenant when None), its lease and a read handle: (tenant, run, handle). A
    fresh tenant gets ALEX as its requester: the definer re-checks the run's requester since revision 0012 (T16)."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    tenant_id, _, run = await new_run(app_conn, tenant, api=api)
    if tenant is None:
        await add_requester(app_conn, tenant_id, ALEX)
```

Edit 6 (`tests/e2e/test_migration_0011_live.py`, the round trip's own functions), replace:

```python
OWN_FUNCTIONS = tuple(f"app.{name}(" for name, _, _, _ in REVISION.FUNCTIONS)
```

with:

```python
OWN_FUNCTIONS = tuple(f"app.{name}(" for name, _, _, _ in REVISION.FUNCTIONS)
LATER_FUNCTIONS = ("app.asset_scope(",)  # revision 0012's own function (T16): a downgrade to 0010 drops it too
```

then replace:

```python
        assert not any(s.startswith(OWN_FUNCTIONS) for s in after)
        assert {s for s in head if not s.startswith(OWN_FUNCTIONS)} == set(after)
```

with:

```python
        assert not any(s.startswith(OWN_FUNCTIONS + LATER_FUNCTIONS) for s in after)
        assert {s for s in head if not s.startswith(OWN_FUNCTIONS + LATER_FUNCTIONS)} == set(after)
```

Edit 7 (`tests/e2e/test_retrieval_baseline_live.py`, beta's run is requested by beta's requester), replace:

```python
RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
```

with:

```python
RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
# Each tenant's seeded requester (data/seed-ids.json): the definer re-checks the run's requester since 0012 (T16).
REQUESTERS = {
    "alpha": UUID("2fc05986-c7ec-544c-b628-fdb112bbf18a"),
    "beta": UUID("2f73af91-4906-5b79-9144-22c0df4e2316"),
}
```

then replace:

```python
            _, _, runs[slug] = await new_run(app_conn, tenant, api=api)
```

with:

```python
            _, _, runs[slug] = await new_run(app_conn, tenant, api=api, requester=REQUESTERS[slug])
```

Edit 8 (`tests/e2e/test_mcp_read_t15_live.py`, R131's read half), replace:

```python
    """The pg_proc ACL as it is today: `current_time` (erratum 15), `resolve_invocation` and, since T17,
    `search_procedures_scoped`; `asset_scope` joins with its owner, T16 (erratum 72 as erratum 96 narrows it)."""
```

with:

```python
    """The pg_proc ACL: `current_time` (erratum 15), `resolve_invocation`, `search_procedures_scoped` (T17) and, since
    T16, `asset_scope`: R131's read half is complete (errata 96 and 104)."""
```

then replace:

```python
    allowed = {"current_time", "resolve_invocation", "search_procedures_scoped"}
```

with:

```python
    allowed = {"current_time", "resolve_invocation", "search_procedures_scoped", "asset_scope"}
```

then replace:

```python
        "R131 read half: mcp_read EXECUTE = current_time, resolve_invocation, search_procedures_scoped;"
```

with:

```python
        "R131 read half: mcp_read EXECUTE = current_time, resolve_invocation, search_procedures_scoped,"
        " asset_scope;"
```

Edit 9 (`tests/e2e/test_mcp_write_t47_live.py`, R131's write half), replace:

```python
    read function `search_procedures_scoped` (T17) among them, refused when called; `asset_scope` arrives with T16."""
```

with:

```python
    read functions `search_procedures_scoped` (T17) and `asset_scope` (T16) among them, each refused when called."""
```

then replace:

```python
    assert await refused(mcp_exec, search, ()) == "42501"
```

with:

```python
    assert await refused(mcp_exec, search, ()) == "42501"
    assert "asset_scope" in others  # mcp-read's (T16)
    assert await refused(mcp_exec, "SELECT * FROM app.asset_scope('h', 'ops-worker')", ()) == "42501"
```

Edit 10 (`tests/e2e/test_migration_0008_live.py`, the functions an MCP server may call), replace:

```python
    assert {"resolve_invocation", "grant_execution", "mark_sent", "record_outcome", "lookup_action"} <= entry
```

with:

```python
    assert {"resolve_invocation", "grant_execution", "mark_sent", "record_outcome", "lookup_action"} <= entry
    assert {"search_procedures_scoped", "asset_scope"} <= entry  # mcp-read's read functions (T17, T16)
```

Create `tests/e2e/test_migration_0012_live.py`:

```python
"""Revision 0012 against the per-session test database (OPS_LIVE=1; Plan M rulings 2, 3, 7 and 11): `asset_scope` and
the re-created `search_procedures_scoped` called by their real caller, `mcp_read`.

Catches: `asset_scope` answering another role, another `azp` or a dead handle, returning anything but the handle's run's
asset and interval, or reading the clock somewhere other than the database's (a moved test clock must move `as_of`);
either function answering once the run's requester has lost the active requester membership (R028), or for a run
whose requester was only ever a reader, while `resolve_invocation` still answers (the handle itself is alive: the
refusal is the membership's); a search whose `retrieved_at` is not the database instant it decided permission at;
an excerpt still cut at 500 characters, or one cut at 8000 without saying so; and a downgrade that leaves
`asset_scope` behind, does not restore 0011's search body and grant exactly, or does not come back exactly with the
upgrade.
"""

import importlib.util
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from ops_core import persistence, settings
from ops_core.jobs import Tool
from ops_core.settings import Profile, Role

from tests.e2e.conftest import lease_for, purge_run
from tests.e2e.test_definers_run_path_live import refused
from tests.e2e.test_fenced_definers_live import investigate_job, read_handle
from tests.e2e.test_migration_0011_live import APP_FUNCTIONS, DAY, cleanup, clock, handle_for, stage
from tests.e2e.test_migrations_and_persistence import new_run

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
AZP = "ops-worker"
ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")
ALEX = UUID("2fc05986-c7ec-544c-b628-fdb112bbf18a")  # alpha's requester
LEE = UUID("abcc1200-6791-57ab-87b5-9392d356b512")  # alpha's reader: never a requester
SCOPE = "SELECT * FROM app.asset_scope(%s, %s)"


async def alpha_handle(app_conn: persistence.Conn, role_conn: RoleConn, **run: Any) -> tuple[UUID, str]:
    """A run on the seeded alpha tenant (A17 by default), its lease and a read handle."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    _, _, run_id = await new_run(app_conn, ALPHA, api=api, **run)
    lease = await lease_for(worker, run_id, owner="t16-live", seconds=600)
    return run_id, await read_handle(worker, run_id, await investigate_job(app_conn, run_id), lease)


async def set_active(app_conn: persistence.Conn, subject: UUID, active: bool) -> None:
    """The membership row of a seeded subject in alpha, switched as the sweeper's sync would (R013's pattern)."""
    cur = await app_conn.execute(
        "UPDATE app.memberships SET active = %s WHERE tenant_id = %s AND subject = %s", (active, ALPHA, subject)
    )
    assert cur.rowcount == 1


async def test_asset_scope_is_the_runs_asset_and_interval_at_the_database_clock(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    mcp_read, harness = await role_conn(Role.MCP_READ), await role_conn(Role.TEST_HARNESS)
    run, handle = await alpha_handle(app_conn, role_conn, asset_id="A21")
    try:
        cur = await app_conn.execute("SELECT asset_id, start_at, end_at FROM app.runs WHERE run_id = %s", (run,))
        row = await cur.fetchone() or {}
        scope = await persistence.asset_scope(mcp_read, handle=handle, azp=AZP)
        assert (scope.run_id, scope.tenant_id, scope.asset_id) == (run, ALPHA, "A21")
        assert (scope.start_at, scope.end_at) == (row["start_at"], row["end_at"])
        assert abs((scope.as_of - await clock(app_conn)).total_seconds()) < 5
        try:
            # A day on the database clock: as_of follows it (SA:158). The lease lapsed with the move, so the handle is
            # minted again under a new one.
            await harness.execute("UPDATE app.test_clock SET clock_offset = interval '1 day'")
            worker = await role_conn(Role.WORKER)
            lease = await lease_for(worker, run, owner="t16-later", seconds=600)
            later = await read_handle(worker, run, await investigate_job(app_conn, run), lease)
            moved = await persistence.asset_scope(mcp_read, handle=later, azp=AZP)
            assert timedelta(hours=23) < moved.as_of - scope.as_of < timedelta(hours=25)
        finally:
            await harness.execute("UPDATE app.test_clock SET clock_offset = interval '0'")
    finally:
        await purge_run(app_conn, run)


async def test_only_mcp_read_calls_asset_scope_with_a_live_handle(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    for role in (Role.API, Role.WORKER, Role.SWEEPER, Role.MCP_EXEC, Role.OPERATOR):
        assert await refused(await role_conn(role), SCOPE, ("not-a-handle", AZP)) == "42501", role
    mcp_read = await role_conn(Role.MCP_READ)
    run, handle = await alpha_handle(app_conn, role_conn)
    try:
        assert (await persistence.asset_scope(mcp_read, handle=handle, azp=AZP)).run_id == run  # the control
        for bad_handle, azp in (("not-a-handle", AZP), (handle, "ops-mcp-read")):  # unknown; another workload
            with pytest.raises(persistence.HandleRejected):
                await persistence.asset_scope(mcp_read, handle=bad_handle, azp=azp)
    finally:
        await purge_run(app_conn, run)


async def test_r028_a_requester_who_lost_the_membership_is_refused_at_read_time(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """Ruling 7: the handle stays alive (`resolve_invocation` answers), yet both read definers refuse once ALEX's
    requester membership is inactive, and answer again once it is back; a run requested by a reader never answers."""
    mcp_read = await role_conn(Role.MCP_READ)
    run, handle = await alpha_handle(app_conn, role_conn)
    by_reader, reader_handle = await alpha_handle(app_conn, role_conn, requester=LEE)

    async def search(presented: str) -> persistence.Procedures:
        return await persistence.search_procedures(
            mcp_read, handle=presented, azp=AZP, query="seal", asset_type=None, limit=1
        )

    try:
        await persistence.asset_scope(mcp_read, handle=handle, azp=AZP)
        await search(handle)
        try:
            await set_active(app_conn, ALEX, False)
            invocation = await persistence.resolve_invocation(
                mcp_read, handle=handle, azp=AZP, tool=Tool.GET_ASSET_STATUS
            )
            assert invocation.run_id == run  # the handle is alive: the refusals below are the membership's
            with pytest.raises(persistence.HandleRejected, match="^invocation handle rejected$"):
                await persistence.asset_scope(mcp_read, handle=handle, azp=AZP)
            with pytest.raises(persistence.HandleRejected, match="^invocation handle rejected$"):
                await search(handle)
        finally:
            await set_active(app_conn, ALEX, True)
        assert (await persistence.asset_scope(mcp_read, handle=handle, azp=AZP)).run_id == run
        await search(handle)
        with pytest.raises(persistence.HandleRejected):  # LEE is alpha's reader: no requester row at all
            await persistence.asset_scope(mcp_read, handle=reader_handle, azp=AZP)
        with pytest.raises(persistence.HandleRejected):
            await search(reader_handle)
    finally:
        await purge_run(app_conn, run)
        await purge_run(app_conn, by_reader)


async def test_the_search_returns_its_instant_and_whole_sections(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    mcp_read, harness = await role_conn(Role.MCP_READ), await role_conn(Role.TEST_HARNESS)
    tenant, run, handle = await handle_for(app_conn, role_conn, None)
    try:
        now = await clock(app_conn)
        always = [("approved", now - 30 * DAY, None)]
        short = "turbine " * 75  # 600 characters: Plan D's 500-character cut would have shortened it
        long = "turbine " * 1000 + "x"  # 8001 characters: one over the contract's bound
        await stage(
            app_conn,
            tenant,
            [
                {"id": "SHORT-DOC", "version": "1", "states": always, "text": short},
                {"id": "LONG-DOC", "version": "1", "states": always, "text": long},
            ],
        )
        found = await persistence.search_procedures(
            mcp_read, handle=handle, azp=AZP, query="turbine", asset_type=None, limit=8
        )
        excerpts = {hit.document_id: hit.excerpt for hit in found.results}
        assert excerpts == {"SHORT-DOC": short, "LONG-DOC": long[:8000]}
        assert found.truncated  # the long one was cut, and says so
        assert abs((found.retrieved_at - now).total_seconds()) < 5
        try:
            # Two days on the database clock: retrieved_at is the instant the effectiveness rule ran at, never the
            # wall clock (Plan L final review, M4).
            await harness.execute("UPDATE app.test_clock SET clock_offset = interval '2 days'")
            worker = await role_conn(Role.WORKER)
            lease = await lease_for(worker, run, owner="t16-instant", seconds=600)
            later = await read_handle(worker, run, await investigate_job(app_conn, run), lease)
            moved = await persistence.search_procedures(
                mcp_read, handle=later, azp=AZP, query="turbine", asset_type=None, limit=8
            )
            assert timedelta(hours=47) < moved.retrieved_at - found.retrieved_at < timedelta(hours=49)
        finally:
            await harness.execute("UPDATE app.test_clock SET clock_offset = interval '0'")
    finally:
        await cleanup(app_conn, [run], [tenant])


def revision_0012() -> Any:
    path = Path(__file__).resolve().parents[2] / "migrations" / "app" / "versions" / "0012_asset_scope.py"
    spec = importlib.util.spec_from_file_location("live_rev_0012", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def snapshot(conn: persistence.Conn) -> dict[str, dict[str, Any]]:
    cur = await conn.execute(APP_FUNCTIONS)
    return {row["signature"]: {k: v for k, v in row.items() if k != "signature"} for row in await cur.fetchall()}


async def test_the_round_trip_restores_0011(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    from scripts.skeleton import downgrade, migrate

    module = revision_0012()
    search = f"app.search_procedures_scoped({module.SEARCH_ARGS})"
    superuser = settings.superuser_postgres()
    mcp_read = await role_conn(Role.MCP_READ)
    head = await snapshot(app_conn)
    assert any(s.startswith("app.asset_scope(") for s in head)
    await persistence.assert_function_text(mcp_read, *persistence.ASSET_SCOPE)  # mcp-read starts on the head
    try:
        downgrade("app", superuser, "0011_governed_corpus")
        after = await snapshot(app_conn)
        assert not any(s.startswith("app.asset_scope(") for s in after)
        cur = await app_conn.execute("SELECT prosrc FROM pg_proc WHERE oid = %s::regprocedure", (search,))
        assert (await cur.fetchone() or {})["prosrc"] == module.REV0011.SEARCH_PROCEDURES_SCOPED.split("$fn$")[1]
        assert set(after) == {s for s in head if not s.startswith("app.asset_scope(")}
        for signature, details in after.items():
            if signature.startswith("app.search_procedures_scoped("):  # regprocedure text: no spaces
                assert details["acl"] == head[signature]["acl"]  # REVOKE PUBLIC, EXECUTE to mcp_read, as before
            else:
                assert details == head[signature], signature  # nothing else moved
        with pytest.raises(persistence.PersistenceError, match="predates this service"):
            await persistence.assert_function_text(mcp_read, *persistence.ASSET_SCOPE)  # mcp-read refuses 0011
    finally:
        assert migrate(Profile.TEST) == 0  # every later test needs the head
    assert await snapshot(app_conn) == head
    scope_unknown = await refused(mcp_read, SCOPE, (str(uuid4()), AZP))
    assert scope_unknown == "OC008"  # back, and still the one handle refusal
```

Run: `uv run ruff format tests/e2e && uv run ruff check --fix tests/e2e`, then `PYTHONUTF8=1 uv run python
scripts/check.py` → `CHECK: GREEN`, pytest `1282 passed, 196 skipped`; `uv run python -I scripts/verify_handoff.py
--reference-code --manifest --contracts` → exit 0; with the dev stack up and every skeleton process down,
`PYTHONUTF8=1 uv run python scripts/check.py --profile test` → `CHECK: GREEN`, pytest `1457 passed, 21 skipped`
(arithmetic), then the `git checkout -- reports/...` of the Global Constraints. A live failure in
`test_migration_0012_live.py` is the first execution of the 0012 SQL: read it against "For review" above before
changing a test.

- [ ] **Step 6: Commit**

```bash
git add migrations/app/versions/0012_asset_scope.py core/src/ops_core/privileges.py core/src/ops_core/persistence.py \
  core/src/ops_core/locking.py mcp-read/src/ops_mcp_read/server.py pyproject.toml tests/plan_m \
  tests/plan_e/test_transitions_table.py tests/plan_k/test_mcp_write_startup.py tests/plan_d/test_mcp_read.py \
  tests/plan_l/test_mcp_read_corpus.py tests/e2e/conftest.py tests/e2e/test_migrations_and_persistence.py \
  tests/e2e/test_migration_0011_live.py tests/e2e/test_retrieval_baseline_live.py tests/e2e/test_mcp_read_t15_live.py \
  tests/e2e/test_mcp_write_t47_live.py tests/e2e/test_migration_0008_live.py tests/e2e/test_migration_0012_live.py
git commit -m "feat(db): revision 0012 - asset_scope, the requester re-check and the search's instant (T16)"
```

### Task 2: asset-sim — the data rules, the service, the seventh process

**Files:**
- Create: `asset-sim/src/ops_asset_sim/data.py`, `asset-sim/src/ops_asset_sim/app.py`,
  `asset-sim/src/ops_asset_sim/__main__.py`, `tests/plan_m/test_asset_sim_data.py`,
  `tests/plan_m/test_asset_sim_app.py`, `tests/e2e/test_asset_sim_live.py`
- Modify: `asset-sim/pyproject.toml` (dependencies), `uv.lock` (by `uv lock --offline`), `asset-sim/README.md` (whole
  file), `core/src/ops_core/settings.py` (`Urls`, `urls`), `core/src/ops_core/testing/faults.py` (`FaultKind`,
  `ASSET_SIM_FAULTS`), `scripts/skeleton.py` (docstrings, `PROCESSES`, `process_environment`),
  `tests/plan_e/test_skeleton_cli.py`, `tests/plan_h/test_faults_t13.py`, `tests/plan_d/test_settings.py`,
  `tests/plan_j/test_verifier_t15.py` and `tests/plan_k/test_verifier_t47.py` (`URLS`), `tests/e2e/conftest.py`
  (`free_port`, the `asset_sim` fixture)

**Requirements:** SA:78, SA:555 (asset-sim's trust and its own tenant filter), BS:405 (deterministic under an injected
clock; test-only fault hooks), T16 DoD 2, R028's asset-sim half, rulings 4-6 and 8-10.

**Interfaces:**
- Consumes: `ops_core.corpus.load_assets`, `corpus.META`; `ops_core.tokens.TokenVerifier`, `WrongAudience`,
  `TokenRejected`, `bearer_token`, `Principal`; `ops_core.contracts.SafeError`, `ErrorCode`;
  `ops_core.testing.faults.Faults`, `FaultKind`; `ops_core.settings.keycloak`, `profile`, `env_int`;
  `ops_core.redaction.install`; Plan D's synthetic key pair (`tests.plan_d.test_tokens.JWK1`, `mint`, `ISSUER`).
- Produces: `ops_asset_sim.data` (`load`, `Catalog`, `Asset`, `Alert`, `instant`, `rfc3339`, `status`, `binding`,
  `encode_cursor`, `decode_cursor`, `alerts_page`, `DataError`, `CursorRefused`, `ASSET_ID`, `DATA`);
  `ops_asset_sim.app` (`create_app(verifier, *, catalog, profile)`, `verifier_for(kc)`, `production_app()`, `FAULTS`);
  `python -m ops_asset_sim`; `settings.Urls.asset_sim`; `FaultKind.ASSET_UNAVAILABLE`, `faults.ASSET_SIM_FAULTS`;
  `skeleton.PROCESSES[0] == Process("asset-sim", "ops_asset_sim", 8091)`; `tests.e2e.conftest.free_port()` and the
  `asset_sim` fixture (yields the base URL, exports `OPS_ASSET_SIM_URL`).

- [ ] **Step 1: Write the failing tests**

Create `tests/plan_m/test_asset_sim_data.py`:

```python
"""asset-sim's data rules without a server (Plan M ruling 4, 9 and 10), on the committed corpus-1 files.

Catches: an alert whose id is not meta.json's uuid5, whose `code`, `message` or `occurred_at` is not the documented
derivation, or that is served out of `(occurred_at, alert_id)` order; a status rule that differs from the documented
one at the instants the plan states (the baseline clock 2026-10-16T12:00Z, and inside and at the edge of the 24-hour
window); an `info` alert that warns; an interval that is not half-open or an alert from after `as_of`; a page whose
`next_cursor` is set when nothing remains, or missing when something does; a cursor replayed for another tenant,
asset or interval, or a tampered one, accepted; data that does not validate against the tool-result contract; and a
malformed alert file served instead of refused at start.
"""

import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from ops_asset_sim import data

ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")
BETA = UUID("5ab45c2c-1e12-5a0c-a2b9-66cd2ff05201")
SEAL_1 = "6699502e-a981-5959-9f24-6df6bd3d3ac5"  # meta.json: uuid5 of alert/A17-seal-001
SEAL_2 = "c8f91c55-7028-5492-bad4-1e5680179647"  # alert/A17-seal-002
TOOL_RESULT = Draft202012Validator(
    json.loads(Path("schemas/tool-result.schema.json").read_text(encoding="utf-8")), format_checker=FormatChecker()
)
CATALOG = data.load()


def at(text: str) -> datetime:
    return data.instant(text)


def asset(tenant: UUID, asset_id: str) -> data.Asset:
    found = CATALOG.asset(tenant, asset_id)
    assert found is not None, asset_id
    return found


def valid(tool: str, payload: dict[str, Any]) -> None:
    """The data validates as the tool's `ok` result (the envelope around it is fixed)."""
    TOOL_RESULT.validate(
        {
            "tool_name": tool,
            "request_id": "00000000-0000-4000-8000-000000000000",
            "status": "ok",
            "observed_at": "2026-10-16T12:00:00Z",
            "truncated": False,
            "data": payload,
            "error": None,
        }
    )


def test_the_catalog_is_corpus_1s_six_assets_and_seven_alerts() -> None:
    assert sorted((a.tenant_id == ALPHA, a.asset_id, a.asset_type) for a in CATALOG.assets.values()) == [
        (False, "B22", "pump"),
        (False, "B25", "compressor"),
        (False, "B31", "conveyor"),
        (True, "A17", "pump"),
        (True, "A21", "compressor"),
        (True, "A30", "conveyor"),
    ]
    assert sum(len(alerts) for alerts in CATALOG.alerts.values()) == 7
    assert [str(a.alert_id) for a in CATALOG.alerts["A17"]] == [SEAL_1, SEAL_2]  # (occurred_at, alert_id) order
    assert CATALOG.asset(ALPHA, "B22") is None and CATALOG.asset(BETA, "B22") is not None  # the tenant decides


def test_an_alert_carries_the_documented_derivation() -> None:
    first = CATALOG.alerts["A17"][0]
    assert (first.code, first.revision, first.severity) == ("seal_leak", 1, "warning")
    assert first.occurred_at == at("2026-10-05T14:00:00Z")
    assert first.message == "Synthetic warning alert: seal leak on Alpha transfer pump A17."
    assert CATALOG.alerts["A21"][0].message == (
        "Synthetic critical alert: high discharge temperature on Alpha air compressor A21."
    )


@pytest.mark.parametrize(
    ("tenant", "asset_id", "when", "state", "revision"),
    [
        (ALPHA, "A17", "2026-10-16T12:00:00Z", "normal", 2),  # the baseline clock: both seal alerts long past
        (BETA, "B22", "2026-10-16T12:00:00Z", "normal", 1),
        (ALPHA, "A17", "2026-10-06T00:00:00Z", "warning", 1),  # seal-001 (10-05 14:00) inside, seal-002 not yet
        (BETA, "B22", "2026-10-06T00:00:00Z", "warning", 1),  # vibration (10-05 11:20) inside
        (ALPHA, "A17", "2026-10-06T12:00:00Z", "warning", 2),  # both seal alerts inside
        (BETA, "B22", "2026-10-06T12:00:00Z", "normal", 1),  # vibration 40 minutes outside the window
        (ALPHA, "A30", "2026-10-03T10:00:00Z", "normal", 1),  # an info alert never warns
        (ALPHA, "A17", "2026-10-04T00:00:00Z", "normal", 1),  # before any alert: revision 1
    ],
)
def test_status_follows_the_documented_rule(tenant: UUID, asset_id: str, when: str, state: str, revision: int) -> None:
    doc = data.status(CATALOG, asset(tenant, asset_id), at(when))
    assert (doc["state"], doc["revision"], doc["observed_at"], doc["data_source"]) == (
        state,
        revision,
        when,
        "synthetic",
    )
    valid("get_asset_status", doc)


def test_the_warning_window_is_closed_at_both_ends() -> None:
    b22 = asset(BETA, "B22")  # one warning alert, raised 2026-10-05T11:20Z
    raised = at("2026-10-05T11:20:00Z")
    assert data.status(CATALOG, b22, raised - timedelta(seconds=1))["state"] == "normal"  # not raised yet
    assert data.status(CATALOG, b22, raised)["state"] == "warning"  # raised_at <= T
    assert data.status(CATALOG, b22, raised + timedelta(hours=24))["state"] == "warning"  # T - 24 h <= raised_at
    edge = data.status(CATALOG, b22, raised + timedelta(hours=24, seconds=1))
    assert (edge["state"], edge["revision"]) == ("normal", 1)  # out of the window; the revision stays


def page(target: data.Asset, start: str, end: str, *, limit: int, cursor: str | None = None) -> dict[str, Any]:
    """One page of `target`'s alerts in `[start, end)`, as of the baseline clock."""
    return data.alerts_page(
        CATALOG,
        target,
        start_at=at(start),
        end_at=at(end),
        as_of=at("2026-10-16T12:00:00Z"),
        limit=limit,
        cursor=cursor,
    )


def test_alerts_page_one_by_one_with_a_cursor_bound_to_the_request() -> None:
    a17 = asset(ALPHA, "A17")
    first = page(a17, "2026-10-05T00:00:00Z", "2026-10-07T00:00:00Z", limit=1)
    assert [a["alert_id"] for a in first["alerts"]] == [SEAL_1] and first["next_cursor"] is not None
    cursor = first["next_cursor"]
    assert len(cursor) == 76 and first["start_at"] == "2026-10-05T00:00:00Z"
    second = page(a17, "2026-10-05T00:00:00Z", "2026-10-07T00:00:00Z", limit=1, cursor=cursor)
    assert [a["alert_id"] for a in second["alerts"]] == [SEAL_2] and second["next_cursor"] is None
    whole = page(a17, "2026-10-05T00:00:00Z", "2026-10-07T00:00:00Z", limit=2)
    assert len(whole["alerts"]) == 2 and whole["next_cursor"] is None  # set exactly when more remain
    for doc in (first, second, whole):
        valid("get_recent_alerts", doc)
    assert first["alerts"][0] == {
        "alert_id": SEAL_1,
        "asset_id": "A17",
        "occurred_at": "2026-10-05T14:00:00Z",
        "code": "seal_leak",
        "message": "Synthetic warning alert: seal leak on Alpha transfer pump A17.",
        "revision": 1,
    }
    tampered = cursor[:-1] + ("A" if cursor[-1] != "A" else "B")
    for target, end, presented in (
        (a17, "2026-10-08T00:00:00Z", cursor),  # another interval
        (asset(ALPHA, "A21"), "2026-10-07T00:00:00Z", cursor),  # another asset
        (asset(BETA, "B22"), "2026-10-07T00:00:00Z", cursor),  # another tenant
        (a17, "2026-10-07T00:00:00Z", tampered),
        (a17, "2026-10-07T00:00:00Z", "!!"),
    ):
        with pytest.raises(data.CursorRefused):
            page(target, "2026-10-05T00:00:00Z", end, limit=1, cursor=presented)


def test_the_interval_is_half_open_and_no_alert_comes_from_after_as_of() -> None:
    a17 = asset(ALPHA, "A17")
    seal_2 = at("2026-10-06T08:30:00Z")

    def ids(start: str, end: datetime, as_of: datetime) -> list[str]:
        page = data.alerts_page(CATALOG, a17, start_at=at(start), end_at=end, as_of=as_of, limit=100, cursor=None)
        return [a["alert_id"] for a in page["alerts"]]

    assert ids("2026-10-05T14:00:00Z", seal_2, at("2026-10-16T12:00:00Z")) == [SEAL_1]  # start in, end out
    assert ids("2026-10-05T00:00:00Z", at("2026-10-07T00:00:00Z"), seal_2 - timedelta(seconds=1)) == [SEAL_1]
    assert ids("2026-10-05T00:00:00Z", at("2026-10-07T00:00:00Z"), seal_2) == [SEAL_1, SEAL_2]  # at as_of: in


def test_a_malformed_alert_file_is_refused_at_start(tmp_path: Path) -> None:
    for name in ("assets.json", "meta.json"):
        shutil.copy(data.DATA / name, tmp_path / name)
    original = json.loads((tmp_path / "assets.json").read_text(encoding="utf-8"))
    for field, value in (("severity", "urgent"), ("raised_at", "2026-10-05T16:00:00+02:00"), ("kind", "Seal Leak")):
        broken = json.loads(json.dumps(original))
        broken["alerts"][0][field] = value
        (tmp_path / "assets.json").write_text(json.dumps(broken), encoding="utf-8")
        with pytest.raises(data.DataError):
            data.load(tmp_path)
    (tmp_path / "assets.json").write_text(json.dumps(original), encoding="utf-8")
    assert len(data.load(tmp_path).assets) == 6  # the unbroken copy loads: the refusals were the edits'
```

Create `tests/plan_m/test_asset_sim_app.py`:

```python
"""asset-sim's HTTP surface in-process, with the production verifier's wiring and Plan D's synthetic signing key
(Plan M rulings 5, 6, 8-10; T16 DoD 2; R098).

Catches: a token for another audience or client (the worker's, mcp-write's, a persona's) served, or refused with a
code that does not tell a foreign token (403) from a bad one (401 with `WWW-Authenticate: Bearer`); an ID or refresh
token accepted; another tenant's asset told apart from an unknown one (an existence oracle); a request without the
forwarded tenant or instant answered from a default; a status, an asset type or a page that is not the data rule's; a
cursor replayed for another interval accepted; an error body that echoes the request; and fault routes reachable
outside the test profile, or accepting a fault this service never consumes. The live version, with Keycloak's own
tokens, is tests/e2e/test_asset_sim_live.py.
"""

from typing import Any
from uuid import UUID

from ops_asset_sim import app as asset_app
from ops_asset_sim import data
from ops_core.settings import Keycloak, Profile
from starlette.testclient import TestClient

from tests.plan_d.test_tokens import ISSUER, JWK1, mint

ALPHA = "3ea79c95-914c-52cb-9d10-c4e19dda8ff7"
BETA = "5ab45c2c-1e12-5a0c-a2b9-66cd2ff05201"
KC = Keycloak(base_url="http://localhost:18080", issuer=ISSUER, server_url="http://127.0.0.1:18080")
MCP_READ = {"aud": ["asset-sim", "account"], "azp": "ops-mcp-read"}  # the realm's ops-mcp-read token, synthetic
BASE = "http://127.0.0.1:8091"


def client(profile: Profile = Profile.DEV) -> TestClient:
    verifier = asset_app.verifier_for(KC)
    verifier.install_keys({"keys": [JWK1]})  # ready: the lifespan loads nothing
    return TestClient(asset_app.create_app(verifier, catalog=data.load(), profile=profile), base_url=BASE)


def headers(tenant: str = ALPHA, as_of: str | None = "2026-10-06T00:00:00Z", **token: Any) -> dict[str, str]:
    out = {"Authorization": f"Bearer {mint(**(token or MCP_READ))}", "X-Ops-Tenant-Id": tenant}
    if as_of is not None:
        out["X-Ops-As-Of"] = as_of
    return out


def test_only_mcp_reads_access_token_is_served() -> None:
    foreign = {
        "the worker's (aud mcp-read)": ({}, 403),  # mint()'s default: aud mcp-read's resource, azp ops-worker
        "mcp-write's (aud incident-sim)": ({"aud": ["incident-sim"], "azp": "ops-mcp-write"}, 403),
        "a persona's (aud ops-api)": ({"aud": "ops-api", "azp": "ops-dev-direct"}, 403),
        "the worker client with asset-sim's audience": ({"aud": ["asset-sim"], "azp": "ops-worker"}, 403),
        "an ID token of mcp-read": ({**MCP_READ, "typ": "ID"}, 401),
        "no audience at all": ({"aud": None, "azp": "ops-mcp-read"}, 401),
    }
    with client() as http:
        for why, (claims, status) in foreign.items():
            token = mint(**claims) if claims else mint()
            answer = http.get("/assets/A17/status", headers={**headers(), "Authorization": f"Bearer {token}"})
            assert answer.status_code == status, why
            assert "state" not in answer.json(), why  # none reaches data
        bare = http.get("/assets/A17/status", headers={"X-Ops-Tenant-Id": ALPHA, "X-Ops-As-Of": "2026-10-06T00:00:00Z"})
        assert bare.status_code == 401 and bare.headers["www-authenticate"] == "Bearer"
        served = http.get("/assets/A17/status", headers=headers())
        assert served.status_code == 200 and served.json()["state"] == "warning"


def test_another_tenants_asset_and_an_unknown_one_get_the_same_404() -> None:
    with client() as http:
        foreign = http.get("/assets/B22/status", headers=headers(ALPHA))  # R028: alpha asks for beta's B22
        unknown = http.get("/assets/Z99/status", headers=headers(ALPHA))
        malformed = http.get("/assets/a17/status", headers=headers(ALPHA))
        answers = [foreign, unknown, malformed]
        assert [a.status_code for a in answers] == [404, 404, 404]
        assert len({tuple(sorted((k, v) for k, v in a.json().items() if k != "request_id")) for a in answers}) == 1
        assert http.get("/assets/B22/status", headers=headers(BETA)).json()["state"] == "warning"  # beta's own
        assert http.get("/assets/B22", headers=headers(ALPHA)).status_code == 404
        no_tenant = http.get(
            "/assets/A17/status", headers={k: v for k, v in headers().items() if k != "X-Ops-Tenant-Id"}
        )
        no_instant = http.get("/assets/A17/status", headers=headers(as_of=None))
        local_time = http.get("/assets/A17/status", headers=headers(as_of="2026-10-06T02:00:00+02:00"))
        for answer in (no_tenant, no_instant, local_time):
            assert answer.status_code == 400 and answer.json()["code"] == "INVALID_INPUT"
            assert "+02:00" not in answer.text  # never echoed


def test_the_routes_answer_the_data_rules() -> None:
    with client() as http:
        assert http.get("/assets/A17", headers=headers()).json() == {"asset_id": "A17", "asset_type": "pump"}
        status = http.get("/assets/A17/status", headers=headers(as_of="2026-10-06T12:00:00Z")).json()
        assert status == {
            "asset_id": "A17",
            "state": "warning",
            "revision": 2,
            "observed_at": "2026-10-06T12:00:00Z",
            "data_source": "synthetic",
        }
        query = {"start_at": "2026-10-05T00:00:00Z", "end_at": "2026-10-07T00:00:00+00:00", "limit": "1"}
        first = http.get("/assets/A17/alerts", headers=headers(as_of="2026-10-16T12:00:00Z"), params=query).json()
        assert len(first["alerts"]) == 1 and first["end_at"] == "2026-10-07T00:00:00Z" and first["next_cursor"]
        second = http.get(
            "/assets/A17/alerts",
            headers=headers(as_of="2026-10-16T12:00:00Z"),
            params={**query, "cursor": first["next_cursor"]},
        ).json()
        assert [a["revision"] for a in first["alerts"] + second["alerts"]] == [1, 2] and second["next_cursor"] is None
        replayed = http.get(
            "/assets/A17/alerts",
            headers=headers(as_of="2026-10-16T12:00:00Z"),
            params={**query, "end_at": "2026-10-08T00:00:00Z", "cursor": first["next_cursor"]},
        )
        assert replayed.status_code == 400  # a cursor of another interval
        for bad in ({"limit": "101"}, {"limit": "0"}, {"end_at": "2026-10-05T00:00:00Z"}, {"start_at": "yesterday"}):
            answer = http.get("/assets/A17/alerts", headers=headers(), params={**query, **bad})
            assert answer.status_code == 400, bad


def test_fault_routes_exist_only_under_the_test_profile() -> None:
    arm = {"count": 1}
    with client(Profile.DEV) as http:
        assert http.post("/internal/faults/drop_before_commit", headers=headers(), json=arm).status_code == 404
    with client(Profile.TEST) as http:
        assert http.post("/internal/faults/asset_unavailable", headers=headers(), json=arm).status_code == 200
        assert http.get("/assets/A17/status", headers=headers()).json()["state"] == "unavailable"
        assert http.get("/assets/A17/status", headers=headers()).json()["state"] == "warning"  # one occurrence only
        assert http.post("/internal/faults/drop_before_commit", headers=headers(), json=arm).status_code == 200
        assert http.get("/assets/A17", headers=headers()).status_code == 503
        assert http.post("/internal/faults/malformed_response", headers=headers(), json=arm).status_code == 200
        assert "data_source" not in http.get("/assets/A17/status", headers=headers()).json()
        never_taken = http.post("/internal/faults/reject_next", headers=headers(), json=arm)
        assert never_taken.status_code == 422  # a destination fault asset-sim never consumes
        timed = http.post("/internal/faults/malformed_response", headers=headers(), json={"count": 1, "seconds": 2})
        assert timed.status_code == 422
        foreign = http.post("/internal/faults/asset_unavailable", headers=headers(azp="ops-worker"), json=arm)
        assert foreign.status_code == 403  # only mcp-read's token arms a fault
        assert UUID(http.get("/assets/Z99", headers=headers()).json()["request_id"])  # a safe error, nothing armed
```

Run: `uv run python -m pytest tests/plan_m/test_asset_sim_data.py tests/plan_m/test_asset_sim_app.py -q`
Expected: `2 errors` during collection (`ops_asset_sim` has no `data` and no `app` module yet).

- [ ] **Step 2: The dependencies and the shared settings**

Edit 1 (`asset-sim/pyproject.toml`), replace:

```toml
dependencies = ["ops-core"]
```

with:

```toml
dependencies = ["ops-core", "fastapi>=0.142,<1", "uvicorn>=0.54,<1"]
```

Run: `uv lock --offline` → `Resolved 67 packages`; `git diff --stat uv.lock` → one file, 7 lines added and 1
removed: `ops-asset-sim`'s `dependencies` gain `fastapi` and `uvicorn` and its `requires-dist` lists the three
specifiers (both packages are already locked for incident-sim; no version moves).

Edit 2 (`core/src/ops_core/settings.py`, `Urls`), replace:

```python
    mcp_write: str
    incident_sim: str


def urls() -> Urls:
```

with:

```python
    mcp_write: str
    incident_sim: str
    asset_sim: str  # T16: where mcp-read reaches asset-sim (Plan M ruling 5)


def urls() -> Urls:
```

Edit 3 (`core/src/ops_core/settings.py`, `urls`), replace:

```python
        incident_sim=env("OPS_INCIDENT_SIM_URL", "http://127.0.0.1:8090"),
    )
```

with:

```python
        incident_sim=env("OPS_INCIDENT_SIM_URL", "http://127.0.0.1:8090"),
        asset_sim=env("OPS_ASSET_SIM_URL", "http://127.0.0.1:8091"),
    )
```

Edit 4 (`core/src/ops_core/testing/faults.py`, `FaultKind`), replace:

```python
    OUTBOX_SINK_FAIL = "outbox_sink_fail"  # the sweeper's next notification delivery fails (T14, R024)
```

with:

```python
    OUTBOX_SINK_FAIL = "outbox_sink_fail"  # the sweeper's next notification delivery fails (T14, R024)
    ASSET_UNAVAILABLE = "asset_unavailable"  # asset-sim's next status answers `unavailable` (T16)
```

Edit 5 (`core/src/ops_core/testing/faults.py`, after `SWEEPER_FAULTS`), replace:

```python
SWEEPER_FAULTS: Final = frozenset({FaultKind.OUTBOX_SINK_FAIL})
```

with:

```python
SWEEPER_FAULTS: Final = frozenset({FaultKind.OUTBOX_SINK_FAIL})
# asset-sim's own hook (T16, Plan M ruling 6): the contract's third asset state, which no data rule produces. Its
# other faults are BS:405's (a transient 503, a malformed response, a slow answer), consumed the destination's way.
ASSET_SIM_FAULTS: Final = frozenset({FaultKind.ASSET_UNAVAILABLE})
```

Edit 6 (`tests/plan_h/test_faults_t13.py`, the import), replace:

```python
from ops_core.testing.faults import BS405, DEFAULT_SECONDS, SWEEPER_FAULTS, FaultKind, Faults, FaultsDisabled
```

with:

```python
from ops_core.testing.faults import (
    ASSET_SIM_FAULTS,
    BS405,
    DEFAULT_SECONDS,
    SWEEPER_FAULTS,
    FaultKind,
    Faults,
    FaultsDisabled,
)
```

then replace:

```python
    # One hook each, and no orphan hook: every kind outside BS:405 is the sweeper's outbox sink fault (T14).
    assert len(kinds) == len(set(kinds)) and set(kinds) == set(FaultKind) - SWEEPER_FAULTS
```

with:

```python
    # One hook each, and no orphan hook: every kind outside BS:405 is the sweeper's outbox sink fault (T14) or
    # asset-sim's `unavailable` state (T16).
    assert len(kinds) == len(set(kinds)) and set(kinds) == set(FaultKind) - SWEEPER_FAULTS - ASSET_SIM_FAULTS
```

Edit 7 (`tests/plan_d/test_settings.py`, the URL defaults), replace:

```python
    assert u.incident_sim == "http://127.0.0.1:8090"
```

with:

```python
    assert u.incident_sim == "http://127.0.0.1:8090"
    monkeypatch.delenv("OPS_ASSET_SIM_URL", raising=False)
    assert settings.urls().asset_sim == "http://127.0.0.1:8091"  # T16: mcp-read -> asset-sim
```

Edit 8 (`tests/plan_j/test_verifier_t15.py` and `tests/plan_k/test_verifier_t47.py`, `URLS`, the same edit in each),
replace:

```python
    incident_sim="http://127.0.0.1:8090",
)
```

with:

```python
    incident_sim="http://127.0.0.1:8090",
    asset_sim="http://127.0.0.1:8091",
)
```

- [ ] **Step 3: The data rules and the service**

Create `asset-sim/src/ops_asset_sim/data.py`:

```python
"""asset-sim's data (T16; Plan M ruling 4): corpus-1's assets and alerts, read once at start, and the fixed rules
that derive what the tool contracts need and the files do not hold.

`data/corpus/assets.json` (authored, under the corpus-1 lock) names each asset's tenant by slug and each alert by
`kind`, `severity`, `raised_at` and `revision`; `data/corpus/meta.json` (generated) gives the tenant UUIDs and the
alerts' uuid5 IDs. Neither file is changed here: corpus-1 stays the frozen version T41 labels against. The rules,
which `asset-sim/README.md` and `docs/runbooks/asset-sim.md` state in prose:

- an alert's contract fields: `alert_id` is meta's UUID, `occurred_at` is `raised_at`, `code` is `kind`, `message`
  is `MESSAGE` filled from severity, kind and the asset's name, `revision` as authored;
- the status of an asset as of an instant T: `warning` when one of its alerts of severity `warning` or `critical`
  was raised in `[T - 24 h, T]`, else `normal`; `revision` the highest revision among its alerts raised at or before
  T, or 1; `observed_at` T; `data_source` `synthetic`. `unavailable` comes only from the test-profile fault hook.
- T is always the `as_of` instant mcp-read forwards (the database's `app.current_time()`): asset-sim has no clock of
  its own, so its answers are deterministic under the injected clock (BS:405, SA:78).
- alerts of an interval: `start_at <= occurred_at < end_at` and `occurred_at <= as_of` (no alert from the future),
  ordered by `(occurred_at, alert_id)`, paged by an opaque cursor bound to the request (ruling 10).

The module is standard library plus `ops_core.corpus`, so the rules are tested without a server.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import struct
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from ops_core import corpus

# The repository's corpus directory, read in place (packaging the data for a container is T30's).
DATA: Final = Path(__file__).resolve().parents[3] / "data" / "corpus"
ASSET_ID: Final = re.compile(r"[A-Z][A-Z0-9_-]{0,31}")  # schemas/tools/get_asset_status.input.schema.json
KIND: Final = re.compile(r"[a-z][a-z0-9_]{0,79}")  # the contract's `code`: 1-80 characters
SEVERITIES: Final = frozenset({"info", "warning", "critical"})
WARNING_SEVERITIES: Final = frozenset({"warning", "critical"})
WARNING_WINDOW: Final = timedelta(hours=24)
MESSAGE: Final = "Synthetic {severity} alert: {kind} on {name}."
EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
CURSOR_VERSION: Final = 1
CURSOR_BYTES: Final = 1 + 8 + 16 + 32  # version, occurred_at in microseconds, alert UUID, request binding


class DataError(ValueError):
    """The data files cannot be served; the message names the rule, never a value from the files."""


class CursorRefused(ValueError):
    """A cursor that is malformed or was issued for another request (another tenant, asset or interval)."""


@dataclass(frozen=True)
class Asset:
    """One asset: its id, its tenant's UUID, its type and its display name."""

    asset_id: str
    tenant_id: UUID
    asset_type: str
    name: str


@dataclass(frozen=True)
class Alert:
    """One alert in the contract's terms, with the severity the status rule reads."""

    alert_id: UUID
    asset_id: str
    occurred_at: datetime
    code: str
    message: str
    revision: int
    severity: str

    @property
    def key(self) -> tuple[datetime, str]:
        """The order of an asset's alerts and the position a cursor names: (occurred_at, alert_id)."""
        return (self.occurred_at, str(self.alert_id))


@dataclass(frozen=True)
class Catalog:
    """Every asset by (tenant UUID, asset id), and each asset's alerts in `Alert.key` order."""

    assets: dict[tuple[UUID, str], Asset]
    alerts: dict[str, tuple[Alert, ...]]

    def asset(self, tenant_id: UUID, asset_id: str) -> Asset | None:
        """The tenant's asset, or None for an unknown one and another tenant's alike (no existence oracle)."""
        return self.assets.get((tenant_id, asset_id))


def instant(text: str) -> datetime:
    """An RFC 3339 UTC instant (`Z` or `+00:00`, erratum 6) as an aware datetime.

    Raises:
        ValueError: not an instant, or not in UTC.
    """
    if not text.endswith(("Z", "+00:00")):
        raise ValueError("an instant must be UTC")
    value = datetime.fromisoformat(text)
    if value.utcoffset() != timedelta(0):
        raise ValueError("an instant must be UTC")
    return value.astimezone(UTC)


def rfc3339(value: datetime) -> str:
    """The `Z` spelling the contracts use, with microseconds only when the instant has them."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def load(root: Path = DATA) -> Catalog:
    """Read `assets.json` (through `ops_core.corpus.load_assets`) and `meta.json` once, and derive the catalog.

    Raises:
        corpus.CorpusError: `assets.json` is malformed.
        DataError: `meta.json` lacks a tenant or an alert, or an alert has an unknown severity, a malformed kind or a
            `raised_at` that is not a UTC instant.
    """
    data = corpus.load_assets(root)
    try:
        meta = json.loads((root / corpus.META).read_text(encoding="utf-8"))
        tenants = {slug: UUID(value) for slug, value in meta["tenants"].items()}
        alert_ids = {entry["id"]: UUID(entry["alert_id"]) for entry in meta["alerts"]}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise DataError("meta.json cannot be read as tenants and alert ids") from exc
    assets: dict[tuple[UUID, str], Asset] = {}
    for entry in data["assets"]:
        if entry["tenant"] not in tenants:
            raise DataError("an asset's tenant has no UUID in meta.json")
        asset = Asset(entry["asset_id"], tenants[entry["tenant"]], entry["asset_type"], entry["name"])
        assets[(asset.tenant_id, asset.asset_id)] = asset
    names = {asset.asset_id: asset.name for asset in assets.values()}
    by_asset: dict[str, list[Alert]] = {}
    for entry in data["alerts"]:
        severity, kind, raised = entry.get("severity"), entry.get("kind"), entry.get("raised_at")
        if severity not in SEVERITIES or not isinstance(kind, str) or not KIND.fullmatch(kind):
            raise DataError("an alert has an unknown severity or a malformed kind")
        if entry["id"] not in alert_ids or not isinstance(raised, str):
            raise DataError("an alert has no UUID in meta.json or no raised_at")
        try:
            occurred_at = instant(raised)
        except ValueError as exc:
            raise DataError("an alert's raised_at is not a UTC instant") from exc
        text = MESSAGE.format(severity=severity, kind=kind.replace("_", " "), name=names[entry["asset_id"]])
        alert = Alert(alert_ids[entry["id"]], entry["asset_id"], occurred_at, kind, text, entry["revision"], severity)
        by_asset.setdefault(alert.asset_id, []).append(alert)
    alerts = {asset_id: tuple(sorted(found, key=lambda a: a.key)) for asset_id, found in by_asset.items()}
    return Catalog(assets, alerts)


def status(catalog: Catalog, asset: Asset, at: datetime) -> dict[str, Any]:
    """The asset's status as of `at` by the documented rule; exactly the `get_asset_status` result's `data`."""
    seen = [alert for alert in catalog.alerts.get(asset.asset_id, ()) if alert.occurred_at <= at]
    warning = any(a.severity in WARNING_SEVERITIES and a.occurred_at >= at - WARNING_WINDOW for a in seen)
    return {
        "asset_id": asset.asset_id,
        "state": "warning" if warning else "normal",
        "revision": max((alert.revision for alert in seen), default=1),
        "observed_at": rfc3339(at),
        "data_source": "synthetic",
    }


def binding(tenant_id: UUID, asset_id: str, start_at: datetime, end_at: datetime) -> bytes:
    """The SHA-256 a cursor carries: it ties the cursor to one tenant, asset and interval (ruling 10). No secret is
    needed: a cursor only selects a position inside a set that the request's own filters already decided."""
    text = "\n".join((str(tenant_id), asset_id, rfc3339(start_at), rfc3339(end_at)))
    return hashlib.sha256(text.encode("utf-8")).digest()


def encode_cursor(alert: Alert, bound: bytes) -> str:
    """An opaque base64url token naming the last alert returned, under the request's binding (76 characters)."""
    micros = (alert.occurred_at - EPOCH) // timedelta(microseconds=1)
    raw = struct.pack(">Bq", CURSOR_VERSION, micros) + alert.alert_id.bytes + bound
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(text: str, bound: bytes) -> tuple[datetime, str]:
    """The (occurred_at, alert_id) position a cursor names.

    Raises:
        CursorRefused: not a cursor of this format, or bound to another request.
    """
    try:
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, binascii.Error) as exc:
        raise CursorRefused("malformed cursor") from exc
    if len(raw) != CURSOR_BYTES or raw[0] != CURSOR_VERSION or not hmac.compare_digest(raw[25:], bound):
        raise CursorRefused("cursor does not belong to this request")
    (micros,) = struct.unpack(">q", raw[1:9])
    return (EPOCH + timedelta(microseconds=micros), str(UUID(bytes=raw[9:25])))


def alerts_page(
    catalog: Catalog,
    asset: Asset,
    *,
    start_at: datetime,
    end_at: datetime,
    as_of: datetime,
    limit: int,
    cursor: str | None,
) -> dict[str, Any]:
    """One page of the asset's alerts in `[start_at, end_at)` raised at or before `as_of`; exactly the
    `get_recent_alerts` result's `data`. `next_cursor` is set exactly when alerts remain after this page.

    Raises:
        CursorRefused: the cursor is malformed or another request's.
    """
    bound = binding(asset.tenant_id, asset.asset_id, start_at, end_at)
    window = [
        alert
        for alert in catalog.alerts.get(asset.asset_id, ())
        if start_at <= alert.occurred_at < end_at and alert.occurred_at <= as_of
    ]
    if cursor is not None:
        after = decode_cursor(cursor, bound)
        window = [alert for alert in window if alert.key > after]
    page = window[:limit]
    return {
        "asset_id": asset.asset_id,
        "start_at": rfc3339(start_at),
        "end_at": rfc3339(end_at),
        "alerts": [
            {
                "alert_id": str(alert.alert_id),
                "asset_id": alert.asset_id,
                "occurred_at": rfc3339(alert.occurred_at),
                "code": alert.code,
                "message": alert.message,
                "revision": alert.revision,
            }
            for alert in page
        ],
        "next_cursor": encode_cursor(page[-1], bound) if len(window) > limit else None,
    }
```

Create `asset-sim/src/ops_asset_sim/app.py`:

```python
"""asset-sim: the synthetic asset and alert API (T16; SA:78, SA:555, BS:405; Plan M rulings 4-6, 8-10).

Trusts only mcp-read's workload token (aud `asset-sim`, azp `ops-mcp-read`, an access token's `typ`) and the context
mcp-read forwards from `asset_scope`: `X-Ops-Tenant-Id` (the run's tenant UUID) and `X-Ops-As-Of` (the database
instant it answers at). It applies its own tenant filter: an asset of another tenant and an unknown asset get the same
404 (no existence oracle, ruling 8). It never sees an invocation handle (BS:364), writes nothing, and keeps no clock
of its own: every answer is a function of the data files, the forwarded tenant and `as_of` (`ops_asset_sim.data`).
A token for another audience or client is 403 and any other refused token 401 with `WWW-Authenticate: Bearer`
(incident-sim's mapping); a safe error never echoes the request. Fault routes exist only under the test profile (R098).
"""

# No `from __future__ import annotations`: FastAPI resolves dependency annotations at import time (Plan D review).
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Final, Protocol
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from ops_core import settings
from ops_core.contracts import ErrorCode, SafeError
from ops_core.settings import Profile
from ops_core.testing.faults import FaultKind, Faults
from ops_core.tokens import Principal, TokenRejected, TokenVerifier, WrongAudience, bearer_token
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ops_asset_sim import data

AUDIENCE: Final = "asset-sim"  # the realm's audience mapper on ops-mcp-read (realm-ops-dev.json)
CALLER: Final = "ops-mcp-read"  # the one workload client asset-sim serves (SA:555)
MAX_LIMIT: Final = 100  # schemas/tools/get_recent_alerts.input.schema.json
# The faults this service consumes (ruling 6): the state `unavailable`, a transient 503, a malformed body and a slow
# answer. Any other kind is refused at the arming route, so nothing can be armed that is never taken.
FAULTS: Final = frozenset(
    {
        FaultKind.ASSET_UNAVAILABLE,
        FaultKind.DROP_BEFORE_COMMIT,
        FaultKind.MALFORMED_RESPONSE,
        FaultKind.TIMEOUT_BEFORE_ACCEPT,
    }
)


class Verifier(Protocol):
    """The token-verifier subset asset-sim needs, so unit tests can stub it."""

    @property
    def ready(self) -> bool: ...

    async def load_keys(self) -> None: ...

    async def verify_async(self, token: str) -> Principal: ...


class FaultRequest(BaseModel):
    """How many occurrences of a fault to arm, and how long a slow answer holds (test profile only)."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    count: int = Field(ge=1, le=100)
    seconds: int | None = Field(default=None, ge=1, le=120)


class Unauthenticated(Exception):
    """No acceptable token: 401."""


class WrongService(Exception):
    """A genuine token for another audience or client: 403, not 401 (T10 DoD 2's mapping)."""


class BadRequest(Exception):
    """The forwarded context or a query parameter is missing or malformed: 400, never echoed."""


def safe_error(status: int, code: ErrorCode, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    """A BUILD_SPEC §7 safe error with a fresh request id."""
    body = SafeError(code=code, message=message, retryable=status in (429, 503), request_id=uuid4())
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"), headers=headers)


def forwarded_tenant(request: Request) -> UUID:
    """`X-Ops-Tenant-Id`, the run's tenant mcp-read read from `asset_scope`.

    Raises:
        BadRequest: absent or not a UUID.
    """
    try:
        return UUID(request.headers["x-ops-tenant-id"])
    except (KeyError, ValueError) as exc:
        raise BadRequest from exc


def forwarded_instant(request: Request, name: str) -> datetime:
    """A forwarded UTC instant: the `X-Ops-As-Of` header or a query parameter.

    Raises:
        BadRequest: absent or not a UTC instant.
    """
    raw = request.headers.get(name) if name.startswith("x-") else request.query_params.get(name)
    if raw is None:
        raise BadRequest
    try:
        return data.instant(raw)
    except ValueError as exc:
        raise BadRequest from exc


def create_app(verifier: Verifier, *, catalog: data.Catalog, profile: Profile = Profile.DEV) -> FastAPI:
    """Wire the routes over a loaded catalog. The fault routes exist only under the test profile (R098): `Faults`
    refuses to exist anywhere else."""
    faults = Faults(profile) if profile is Profile.TEST else None

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if not verifier.ready:
            await verifier.load_keys()
        yield

    app = FastAPI(title="asset-sim", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    async def caller(request: Request) -> Principal:
        try:
            return await verifier.verify_async(bearer_token(request.headers.get("authorization")))
        except WrongAudience as exc:  # before TokenRejected, which it subclasses
            raise WrongService from exc
        except TokenRejected as exc:
            raise Unauthenticated from exc

    @app.exception_handler(Unauthenticated)
    async def _unauthenticated(_: Request, __: Unauthenticated) -> Response:
        return safe_error(
            401, ErrorCode.UNAUTHENTICATED, "a valid workload token is required", {"WWW-Authenticate": "Bearer"}
        )

    @app.exception_handler(WrongService)
    async def _wrong_service(_: Request, __: WrongService) -> Response:
        return safe_error(403, ErrorCode.FORBIDDEN, "token is not for this service")

    @app.exception_handler(BadRequest)
    async def _bad_request(_: Request, __: BadRequest) -> Response:
        return safe_error(400, ErrorCode.INVALID_INPUT, "request is not valid")

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, __: RequestValidationError) -> Response:
        return safe_error(400, ErrorCode.INVALID_INPUT, "request is not valid")  # never FastAPI's echoing body

    def not_found() -> JSONResponse:
        return safe_error(404, ErrorCode.NOT_FOUND, "no such asset")  # unknown and another tenant's alike

    async def fault(malformed: dict[str, object]) -> Response | None:
        """The armed fault that answers instead of the data, if any (test profile only)."""
        if faults is None:
            return None
        if faults.take(FaultKind.TIMEOUT_BEFORE_ACCEPT):
            await asyncio.sleep(faults.seconds(FaultKind.TIMEOUT_BEFORE_ACCEPT))
            return safe_error(503, ErrorCode.UNAVAILABLE, "asset-sim answered too late (fault)")
        if faults.take(FaultKind.DROP_BEFORE_COMMIT):
            return safe_error(503, ErrorCode.UNAVAILABLE, "asset-sim unavailable (fault)")
        if faults.take(FaultKind.MALFORMED_RESPONSE):
            return JSONResponse(malformed)
        return None

    def lookup(request: Request, asset_id: str) -> data.Asset | None:
        tenant = forwarded_tenant(request)
        return catalog.asset(tenant, asset_id) if data.ASSET_ID.fullmatch(asset_id) else None

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "live"}

    @app.get("/health/ready")
    async def ready() -> Response:
        """Ready once the realm's keys are loaded; the catalog is loaded before the app exists."""
        if not verifier.ready:
            return safe_error(503, ErrorCode.UNAVAILABLE, "signing keys not loaded")
        return JSONResponse({"status": "ready"})

    @app.get("/assets/{asset_id}")
    async def get_asset(asset_id: str, request: Request, _: Annotated[Principal, Depends(caller)]) -> Response:
        """The asset's type, which mcp-read passes to the procedure search (ruling 12)."""
        asset = lookup(request, asset_id)
        answered = await fault({"asset_id": asset_id, "asset_type": 7})
        if answered is not None:
            return answered
        if asset is None:
            return not_found()
        return JSONResponse({"asset_id": asset.asset_id, "asset_type": asset.asset_type})

    @app.get("/assets/{asset_id}/status")
    async def get_status(asset_id: str, request: Request, _: Annotated[Principal, Depends(caller)]) -> Response:
        """`get_asset_status`'s data as of the forwarded instant."""
        asset = lookup(request, asset_id)
        as_of = forwarded_instant(request, "x-ops-as-of")
        answered = await fault({"asset_id": asset_id, "state": "on fire"})
        if answered is not None:
            return answered
        if asset is None:
            return not_found()
        doc = data.status(catalog, asset, as_of)
        if faults is not None and faults.take(FaultKind.ASSET_UNAVAILABLE):
            doc["state"] = "unavailable"  # the contract's third state, reachable only through this hook
        return JSONResponse(doc)

    @app.get("/assets/{asset_id}/alerts")
    async def get_alerts(asset_id: str, request: Request, _: Annotated[Principal, Depends(caller)]) -> Response:
        """`get_recent_alerts`'s data: the forwarded interval, at or before the forwarded instant, one page."""
        asset = lookup(request, asset_id)
        as_of = forwarded_instant(request, "x-ops-as-of")
        start_at, end_at = forwarded_instant(request, "start_at"), forwarded_instant(request, "end_at")
        cursor = request.query_params.get("cursor")
        try:
            limit = int(request.query_params["limit"])
        except (KeyError, ValueError) as exc:
            raise BadRequest from exc
        if not 1 <= limit <= MAX_LIMIT or start_at >= end_at or (cursor is not None and not 1 <= len(cursor) <= 200):
            raise BadRequest
        answered = await fault({"asset_id": asset_id, "alerts": "none"})
        if answered is not None:
            return answered
        if asset is None:
            return not_found()
        try:
            doc = data.alerts_page(
                catalog, asset, start_at=start_at, end_at=end_at, as_of=as_of, limit=limit, cursor=cursor
            )
        except data.CursorRefused:
            return safe_error(400, ErrorCode.INVALID_INPUT, "cursor does not belong to this request")
        return JSONResponse(doc)

    if faults is not None:
        armable = faults  # a local the closure can rely on: `faults` is narrowed to non-None only here

        @app.post("/internal/faults/{kind}")
        async def arm_fault(kind: str, request: Request, _: Annotated[Principal, Depends(caller)]) -> Response:
            """Arm one of this service's faults for the next `count` requests (the route exists under PROFILE=test
            only, and only mcp-read's token may call it)."""
            try:
                chosen = FaultKind(kind)
                body = FaultRequest.model_validate_json((await request.body()).decode("utf-8"))
            except (ValueError, ValidationError, UnicodeDecodeError):
                return safe_error(422, ErrorCode.INVALID_INPUT, "body is not a well-formed fault request")
            if chosen not in FAULTS:
                return safe_error(422, ErrorCode.INVALID_INPUT, "asset-sim does not consume this fault")
            try:
                armable.arm(chosen, body.count, seconds=body.seconds)
            except ValueError:  # `seconds` for a kind without a duration
                return safe_error(422, ErrorCode.INVALID_INPUT, "seconds applies to timeout_before_accept only")
            return JSONResponse({"armed": armable.armed()})

    return app


def verifier_for(kc: settings.Keycloak) -> TokenVerifier:
    """asset-sim's token checks (ruling 6): the realm's issuer and keys, the audience `asset-sim`, `ops-mcp-read` as
    the only `azp`, and an access token's `typ`. `production_app` builds its verifier here, and so do the tests."""
    return TokenVerifier(
        issuer=kc.issuer,
        audience=AUDIENCE,
        allowed_azp=frozenset({CALLER}),
        jwks_url=kc.jwks_url,
        token_type="Bearer",
    )


def production_app() -> FastAPI:
    """The app wired from the environment, as `python -m ops_asset_sim` runs it; the data files are read here, once."""
    return create_app(verifier_for(settings.keycloak()), catalog=data.load(), profile=settings.profile())
```

Create `asset-sim/src/ops_asset_sim/__main__.py`:

```python
"""`python -m ops_asset_sim`: serve on 127.0.0.1:OPS_ASSET_SIM_PORT (default 8091)."""

import asyncio
import sys

import uvicorn
from ops_core import redaction
from ops_core.settings import env_int
from starlette.types import ASGIApp

from ops_asset_sim.app import production_app


def serve_app(app: ASGIApp, port: int) -> None:
    """Serve with uvicorn programmatically on a selector loop, as incident-sim does (`uvicorn.run` picks the Proactor
    loop on Windows)."""
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", log_config=None))
    if sys.platform == "win32":
        asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(server.serve())


if __name__ == "__main__":
    # The redaction filter must sit on the root handler before the first log line (T11 note 4).
    redaction.install()
    serve_app(production_app(), env_int("OPS_ASSET_SIM_PORT", 8091))
```

Replace `asset-sim/README.md` whole with:

```markdown
# asset-sim

Synthetic asset/alert API

## Owns
Deterministic status and alerts for corpus-1's six assets (`data/corpus/assets.json` and `meta.json`, read once at
start and never changed), derived by fixed rules under the instant mcp-read forwards (T16)

## Trusts
Only mcp-read's workload token (aud `asset-sim`, azp `ops-mcp-read`) and the tenant and instant it forwards from
`asset_scope`; it applies its own tenant filter

## Never
Any write; any other caller; an invocation handle; a clock of its own

## Runs (T16)

`python -m ops_asset_sim` on 127.0.0.1:8091 (`OPS_ASSET_SIM_PORT`), started first by `scripts/skeleton.py up`;
mcp-read reaches it at `OPS_ASSET_SIM_URL` (default `http://127.0.0.1:8091`). Routes: `GET /assets/{asset_id}` (the
asset's type), `GET /assets/{asset_id}/status` and
`GET /assets/{asset_id}/alerts?start_at=…&end_at=…&limit=…[&cursor=…]`, each with `X-Ops-Tenant-Id` (the run's tenant
UUID) and `X-Ops-As-Of` (the database instant to answer at). An asset of another tenant and an unknown asset get the
same 404. The rules (`ops_asset_sim.data`):

- an alert's `alert_id` is `meta.json`'s uuid5, `occurred_at` its `raised_at`, `code` its `kind`, `message`
  "Synthetic <severity> alert: <kind in words> on <asset name>.", `revision` as authored;
- an asset's status as of T: `warning` when one of its `warning` or `critical` alerts was raised in `[T - 24 h, T]`,
  else `normal`; `revision` the highest among its alerts raised at or before T, or 1; `observed_at` T;
  `data_source` `synthetic`;
- alerts: `start_at <= occurred_at < end_at` and `occurred_at <= T`, ordered by `(occurred_at, alert_id)`, one page
  of `limit`, with a cursor bound to the tenant, the asset and the interval.

Fault hooks (`POST /internal/faults/{kind}`: `asset_unavailable`, `drop_before_commit`, `malformed_response`,
`timeout_before_accept`) exist only under `PROFILE=test`. See `docs/runbooks/asset-sim.md`.
```

- [ ] **Step 4: The skeleton's seventh process**

Edit 1 (`scripts/skeleton.py`, line 2 of the module docstring), replace:

```python
`up`/`down`/`status` the six processes, `keys` the destination-vs-grant detective check.
```

with:

```python
`up`/`down`/`status` the seven processes, `keys` the destination-vs-grant detective check.
```

Edit 2 (`scripts/skeleton.py`, `PROCESSES`), replace:

```python
PROCESSES: tuple[Process, ...] = (
    Process("incident-sim", "ops_incident_sim", 8090),
```

with:

```python
PROCESSES: tuple[Process, ...] = (
    Process("asset-sim", "ops_asset_sim", 8091),  # T16: before mcp-read, which reads assets from it
    Process("incident-sim", "ops_incident_sim", 8090),
```

Edit 3 (`scripts/skeleton.py`, `process_environment`), replace:

```python
    env.setdefault("OPS_INCIDENT_SIM_PORT", "8090")
```

with:

```python
    env.setdefault("OPS_INCIDENT_SIM_PORT", "8090")
    env.setdefault("OPS_ASSET_SIM_PORT", "8091")
```

Edit 4 (`scripts/skeleton.py`, two docstrings), replace:

```python
    """The six host processes as children of this one; logs under runtime/skeleton/ (never committed)."""
```

with:

```python
    """The seven host processes as children of this one; logs under runtime/skeleton/ (never committed)."""
```

then replace:

```python
    """Start the six processes and record their pids for `down`; they outlive this script. Refuses a second set."""
```

with:

```python
    """Start the seven processes and record their pids for `down`; they outlive this script. Refuses a second set."""
```

Edit 5 (`tests/plan_e/test_skeleton_cli.py`), replace:

```python
def test_six_processes_on_distinct_loopback_ports() -> None:
    from scripts.skeleton import PROCESSES

    assert [p.name for p in PROCESSES] == ["incident-sim", "mcp-read", "mcp-write", "api", "worker", "sweeper"]
    assert len({p.port for p in PROCESSES}) == 6
```

with:

```python
def test_seven_processes_on_distinct_loopback_ports() -> None:
    from scripts.skeleton import PROCESSES

    names = [p.name for p in PROCESSES]
    assert names == ["asset-sim", "incident-sim", "mcp-read", "mcp-write", "api", "worker", "sweeper"]  # T16
    assert len({p.port for p in PROCESSES}) == 7
```

Run: `uv run ruff format asset-sim core scripts tests && uv run ruff check --fix asset-sim core scripts tests`, then
`uv run python -m pytest tests/plan_m tests/plan_d/test_settings.py tests/plan_e/test_skeleton_cli.py
tests/plan_h/test_faults_t13.py tests/plan_j/test_verifier_t15.py tests/plan_k/test_verifier_t47.py -q`
Expected: every test passes (`test_asset_sim_data.py` 14, `test_asset_sim_app.py` 4).

- [ ] **Step 5: The live half**

Edit 1 (`tests/e2e/conftest.py`, the imports), replace:

```python
import asyncio
import os
import sys
import time
```

with:

```python
import asyncio
import os
import socket
import sys
import time
```

then replace:

```python
import pytest
import pytest_asyncio
```

with:

```python
import pytest
import pytest_asyncio
import uvicorn
```

Edit 2 (`tests/e2e/conftest.py`, before `app_conn`), replace:

```python
@pytest_asyncio.fixture
async def app_conn(migrated: None) -> AsyncIterator[persistence.Conn]:
```

with:

```python
def free_port() -> int:
    """A loopback port nobody holds right now (the skeleton's own processes may be up on their fixed ports)."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest_asyncio.fixture
async def asset_sim(env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[str]:
    """asset-sim's production app (T16) under uvicorn on a free loopback port in the test's own loop, with this
    session's profile (test: its fault routes exist). Its base URL is exported as OPS_ASSET_SIM_URL for an mcp-read
    built afterwards, in-process or as a child through `process_environment`; stopped by uvicorn's own shutdown,
    never a cancel."""
    from ops_asset_sim.app import production_app

    port = free_port()
    server = uvicorn.Server(uvicorn.Config(production_app(), host="127.0.0.1", port=port, log_level="warning"))

    async def guarded() -> None:
        # uvicorn answers a failed lifespan (keys it cannot load) with sys.exit; a SystemExit escaping a task would
        # leave the event loop at once, so it becomes an ordinary error (test_mcp_read_t15_live's `guarded`).
        try:
            await server.serve()
        except SystemExit as exc:
            raise RuntimeError("asset-sim did not start; see the log above") from exc

    task = asyncio.create_task(guarded())
    try:
        while not server.started:
            if task.done():
                task.result()  # a failed start raises its RuntimeError here instead of waiting for ever
            await asyncio.sleep(0.05)
        url = f"http://127.0.0.1:{port}"
        monkeypatch.setenv("OPS_ASSET_SIM_URL", url)
        yield url
    finally:
        server.should_exit = True
        await asyncio.wait({task})


@pytest_asyncio.fixture
async def app_conn(migrated: None) -> AsyncIterator[persistence.Conn]:
```

Create `tests/e2e/test_asset_sim_live.py`:

```python
"""asset-sim over a real socket with Keycloak's own tokens (OPS_LIVE=1; T16 DoD 2, R028's asset-sim half, R098;
Plan M rulings 5, 6 and 8).

The service is `production_app()` under uvicorn on a free loopback port in the test's own loop (the `asset_sim`
fixture), under the session's test profile. Catches: a worker, mcp-write, persona ("api", erratum 81's browser
stand-in) or `ops-view-users` token that reaches data, or a refusal that is not 401/403; mcp-read's own workload token
refused; alpha's tenant reading beta's B22, or told apart from an unknown asset; and the fault hooks missing under the
test profile (the dev profile's absence is tests/plan_m/test_asset_sim_app.py). Writes
reports/asset-sim/t16-asset-sim.txt (names and status codes only, never a token).
"""

import time
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx2
import pytest
from ops_core import settings
from ops_core.tokens import WorkloadTokenSource

from tests.plan_b.live import kc

pytestmark = pytest.mark.asyncio

ALPHA = "3ea79c95-914c-52cb-9d10-c4e19dda8ff7"
BETA = "5ab45c2c-1e12-5a0c-a2b9-66cd2ff05201"
EVIDENCE = Path("reports/asset-sim/t16-asset-sim.txt")
EXPECTED_LINES = 3  # one per test below


@pytest.fixture(scope="module")
def lines() -> Iterator[list[str]]:
    out = [f"T16 asset-sim — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"]
    yield out
    if len(out) != 1 + EXPECTED_LINES:  # a failed or partial run leaves the committed file as it was
        return
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


async def workload_token(secret: Callable[[str], str], client_id: str, secret_name: str) -> str:
    source = WorkloadTokenSource(
        token_url=settings.keycloak().token_url, client_id=client_id, client_secret=secret(secret_name)
    )
    return await source.token()


async def mcp_read_token(secret: Callable[[str], str]) -> str:
    return await workload_token(secret, "ops-mcp-read", "kc_client_secret_ops_mcp_read")


def context(token: str, tenant: str = ALPHA, as_of: str = "2026-10-06T00:00:00Z") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Ops-Tenant-Id": tenant, "X-Ops-As-Of": as_of}


async def test_dod2_asset_sim_serves_mcp_read_alone(
    asset_sim: str, secret: Callable[[str], str], lines: list[str]
) -> None:
    kcs = settings.keycloak()
    foreign = {
        "worker (ops-worker)": await workload_token(secret, "ops-worker", "kc_client_secret_ops_worker"),
        "mcp-write (ops-mcp-write)": await workload_token(secret, "ops-mcp-write", "kc_client_secret_ops_mcp_write"),
        "api (persona alex via ops-dev-direct, aud ops-api)": kc.token_password(
            kcs.base_url, "ops-dev-direct", "alex", secret("kc_persona_alex_password")
        )["access_token"],
        "api (ops-view-users service account)": await workload_token(
            secret, "ops-view-users", "kc_client_secret_ops_view_users"
        ),
    }
    answers: dict[str, int] = {}
    async with httpx2.AsyncClient(base_url=asset_sim) as http:
        for name, token in foreign.items():
            answer = await http.get("/assets/A17/status", headers=context(token))
            assert "state" not in answer.json(), name  # no foreign token reaches data
            answers[name] = answer.status_code
        served = await http.get("/assets/A17/status", headers=context(await mcp_read_token(secret)))
    # A token that carries another audience is 403; the view-users token's audience is the realm's choice (it may
    # carry none), so it may be 401 instead; either way it is refused.
    assert all(code == 403 for name, code in answers.items() if "view-users" not in name), answers
    assert answers["api (ops-view-users service account)"] in (401, 403)
    assert served.status_code == 200 and served.json()["state"] == "warning"  # A17 at 2026-10-06T00:00Z
    lines.append(f"DoD 2: refused {answers}; ops-mcp-read 200")


async def test_r028_the_forwarded_tenant_decides_and_an_existence_oracle_is_absent(
    asset_sim: str, secret: Callable[[str], str], lines: list[str]
) -> None:
    token = await mcp_read_token(secret)
    async with httpx2.AsyncClient(base_url=asset_sim) as http:
        foreign = await http.get("/assets/B22/status", headers=context(token, ALPHA))
        unknown = await http.get("/assets/Z99/status", headers=context(token, ALPHA))
        own = await http.get("/assets/B22/status", headers=context(token, BETA))
    assert (foreign.status_code, unknown.status_code, own.status_code) == (404, 404, 200)
    assert {k: v for k, v in foreign.json().items() if k != "request_id"} == {
        k: v for k, v in unknown.json().items() if k != "request_id"
    }  # alpha cannot tell beta's B22 from an asset that does not exist
    lines.append("R028 at asset-sim: alpha -> B22 404 (as Z99), beta -> B22 200")


async def test_the_fault_hooks_answer_under_the_test_profile(
    asset_sim: str, secret: Callable[[str], str], lines: list[str]
) -> None:
    token = await mcp_read_token(secret)
    async with httpx2.AsyncClient(base_url=asset_sim) as http:
        armed = await http.post("/internal/faults/asset_unavailable", headers=context(token), json={"count": 1})
        state = (await http.get("/assets/A17/status", headers=context(token))).json()["state"]
        await http.post("/internal/faults/drop_before_commit", headers=context(token), json={"count": 1})
        dropped = await http.get("/assets/A17/status", headers=context(token))
        after = await http.get("/assets/A17/status", headers=context(token))
    assert armed.status_code == 200 and state == "unavailable"
    assert dropped.status_code == 503 and after.json()["state"] == "warning"  # one occurrence each
    lines.append(
        "faults (test profile): asset_unavailable -> unavailable, drop_before_commit -> 503, then served again"
    )
```

Run: `uv run ruff format tests/e2e && uv run ruff check --fix tests/e2e`, then `PYTHONUTF8=1 uv run python
scripts/check.py` → `CHECK: GREEN`, pytest `1300 passed, 199 skipped`; `uv run python -I scripts/verify_handoff.py
--reference-code --manifest --contracts` → exit 0; `uv run python scripts/skeleton.py status` → seven processes, all
down; `PYTHONUTF8=1 uv run python scripts/check.py --profile test` → `CHECK: GREEN`, pytest `1478 passed, 21 skipped`
(arithmetic), then the `git checkout -- reports/...` of the Global Constraints (keep `reports/asset-sim/`). The R105
module now starts seven processes; its mcp-read reaches the skeleton's asset-sim at the default URL.

- [ ] **Step 6: Commit**

```bash
git add asset-sim core/src/ops_core/settings.py core/src/ops_core/testing/faults.py scripts/skeleton.py uv.lock \
  tests/plan_m/test_asset_sim_data.py tests/plan_m/test_asset_sim_app.py tests/plan_e/test_skeleton_cli.py \
  tests/plan_h/test_faults_t13.py tests/plan_d/test_settings.py tests/plan_j/test_verifier_t15.py \
  tests/plan_k/test_verifier_t47.py tests/e2e/conftest.py tests/e2e/test_asset_sim_live.py
git commit -m "feat(asset-sim): the synthetic asset and alert API on corpus-1, mcp-read's token only (T16)"
```

### Task 3: The committed contracts at run time, and mcp-read's asset tools

**Files:**
- Create: `core/src/ops_core/tool_contracts.py`, `mcp-read/src/ops_mcp_read/assets.py`,
  `tests/plan_m/test_tool_contracts.py`, `tests/plan_m/test_mcp_read_assets.py`, `tests/e2e/test_mcp_read_t16_live.py`
- Modify: `core/pyproject.toml` (jsonschema), `pyproject.toml` (its mypy override), `uv.lock` (by `uv lock --offline`),
  `mcp-read/src/ops_mcp_read/server.py` (whole file), `tests/plan_d/test_mcp_read.py` (the docstring, the imports, the
  schema test), `tests/plan_j/test_mcp_read_http.py` (`IdleAssets`, `read_app`, two tool lists),
  `tests/plan_j/test_mcp_read_startup.py` (`start`), `tests/plan_l/test_mcp_read_corpus.py` (`call`),
  `tests/e2e/test_mcp_read_t15_live.py` and `tests/e2e/test_mcp_read_process_live.py` (the tool lists)

**Requirements:** AM-15's read row (SA:333), SA:350, SA:351-355, SA:460, SA:555, BS:362-364, BS:384-385, BS:389,
BS:399, R028 (asset half), T16 DoD 1 (cross-tenant asset reads denied), rulings 3, 8-10, 13 (mcp-read's half) and 15.

**Interfaces:**
- Consumes: `persistence.resolve_invocation`, `asset_scope`, `AssetScope`, `HandleRejected`; `settings.urls().asset_sim`,
  `settings.keycloak().token_url`, `settings.read_secret`; `tokens.WorkloadTokenSource`, `TokenRejected`;
  `canonical.canonical_json`; `jobs.Tool`; asset-sim's routes (Task 2); `tests.plan_j.test_mcp_read_http`'s
  `KeyedVerifier`, `BASE`, `ISSUER`, `RESOURCE`; `tests.plan_l.test_mcp_read_corpus.HANDLE`, `UnitConn`; the live
  `serving`, `call`, `worker_token` of `test_mcp_read_t15_live.py` and the `asset_sim` fixture.
- Produces: `ops_core.tool_contracts` (`SCHEMAS`, `MAX_RESULT_BYTES`, `ContractViolation`, `input_schema(tool)`,
  `same_input_schema(tool, advertised)`, `check_result(tool, document)`); `ops_mcp_read.assets` (`AssetSim`,
  `HttpAssetSim(base_url, tokens, *, transport=None)`, `HttpAssetSim.from_settings()`, `AssetSimError` and its
  `Unavailable`, `AssetMissing`, `CursorRejected`, `UpstreamInvalid`, `rfc3339`); `server.State.assets`,
  `server.contract_tool`, `server.within_scope`, `server.tool_error(code, message, *, retryable=False)`, the tools
  `get_asset_status(asset_id)` and `get_recent_alerts(asset_id, start_at, end_at, limit, cursor="")`;
  `tests.plan_j.test_mcp_read_http.IdleAssets`.

- [ ] **Step 1: Write the failing tests**

Create `tests/plan_m/test_tool_contracts.py`:

```python
"""`ops_core.tool_contracts` (Plan M ruling 13): the committed schemas at run time.

Catches: an input schema that is not the committed file, or a cached one a caller can change for everyone after it;
a comparison that is fooled by key order or accepts a changed bound or a float where the file has an integer; a
result validator that checks only the envelope (BS:399: nested data too), accepts another tool's envelope, or puts a
value from the document into its message.
"""

import json
from pathlib import Path

import pytest
from ops_core import tool_contracts
from ops_core.jobs import Tool

READ = (Tool.GET_ASSET_STATUS, Tool.GET_RECENT_ALERTS, Tool.SEARCH_PROCEDURES)
EXAMPLES = Path("schemas/examples")


@pytest.mark.parametrize("tool", READ)
def test_the_input_schema_is_the_committed_file(tool: Tool) -> None:
    committed = json.loads(Path(f"schemas/tools/{tool.value}.input.schema.json").read_text(encoding="utf-8"))
    served = tool_contracts.input_schema(tool)
    assert served == committed and tool_contracts.same_input_schema(tool, committed)
    served["properties"].clear()  # a caller's copy: the next caller still gets the file
    assert tool_contracts.input_schema(tool) == committed
    reordered = json.loads(json.dumps(committed, sort_keys=True))
    assert tool_contracts.same_input_schema(tool, reordered)  # canonical JSON: key order does not matter
    loosened = json.loads(json.dumps(committed))
    loosened["additionalProperties"] = True
    assert not tool_contracts.same_input_schema(tool, loosened)


def test_a_changed_bound_or_a_float_is_another_schema() -> None:
    schema = tool_contracts.input_schema(Tool.GET_ASSET_STATUS)
    schema["properties"]["asset_id"]["maxLength"] = 64
    assert not tool_contracts.same_input_schema(Tool.GET_ASSET_STATUS, schema)
    schema["properties"]["asset_id"]["maxLength"] = 32.0  # equal in Python, not in canonical JSON
    assert not tool_contracts.same_input_schema(Tool.GET_ASSET_STATUS, schema)


def test_check_result_validates_the_nested_data_of_the_named_tool() -> None:
    for name in ("tool-get_asset_status-valid.json", "tool-get_recent_alerts-valid.json"):
        doc = json.loads((EXAMPLES / name).read_text(encoding="utf-8"))
        assert tool_contracts.check_result(Tool(doc["tool_name"]), doc) is doc
    status = json.loads((EXAMPLES / "tool-get_asset_status-valid.json").read_text(encoding="utf-8"))
    broken = {**status, "data": {**status["data"], "state": "on fire"}}
    with pytest.raises(tool_contracts.ContractViolation, match="at data/state") as refused:
        tool_contracts.check_result(Tool.GET_ASSET_STATUS, broken)
    assert "on fire" not in str(refused.value)  # the path and the rule, never the value
    with pytest.raises(tool_contracts.ContractViolation, match="names another tool"):
        tool_contracts.check_result(Tool.GET_RECENT_ALERTS, status)
    with pytest.raises(tool_contracts.ContractViolation, match="not an object"):
        tool_contracts.check_result(Tool.GET_ASSET_STATUS, [status])
    outcome = {**status, "status": "outcome"}  # a read tool answers ok or error only (AM-80)
    with pytest.raises(tool_contracts.ContractViolation):
        tool_contracts.check_result(Tool.GET_ASSET_STATUS, outcome)
```

Create `tests/plan_m/test_mcp_read_assets.py`:

```python
"""mcp-read's asset tools over its HTTP stack in-process: the two database calls replaced, asset-sim answered by a
scripted transport behind the real client (Plan M rulings 8, 9, 10, 13 and 15; erratum 80).

Catches: asset-sim asked before the handle resolved and the scope was read, or in the same unit; the worker's token or
the handle forwarded to asset-sim, or the tenant, the instant or the interval taken from anywhere but `asset_scope`;
another asset or another interval forwarded instead of refused; an answer stamped from the wall clock; `truncated`
that disagrees with `next_cursor`; an asset-sim failure that is not mapped to its code and retry flag, or data outside
the contract or the run's scope passed on; a refused handle or a lost membership answered with anything but the one
plain INVALID_HANDLE; and an advertised input schema that is not the committed file, or that disagrees with the
argument model on what it accepts.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx2
import pytest
from jsonschema import Draft202012Validator
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_types import CallToolResult
from ops_core import persistence, tool_contracts
from ops_core.jobs import Tool
from ops_mcp_read import assets, server

from tests.plan_j.test_mcp_read_http import BASE, ISSUER, RESOURCE, KeyedVerifier
from tests.plan_l.test_mcp_read_corpus import HANDLE, UnitConn

pytestmark = pytest.mark.asyncio

ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")
SCOPE = persistence.AssetScope(
    run_id=UUID(int=7),
    tenant_id=ALPHA,
    asset_id="A17",
    start_at=datetime(2026, 10, 5, tzinfo=UTC),
    end_at=datetime(2026, 10, 7, tzinfo=UTC),
    as_of=datetime(2026, 10, 6, 0, 0, 0, 250000, tzinfo=UTC),
)
STATUS = {
    "asset_id": "A17",
    "state": "warning",
    "revision": 1,
    "observed_at": "2026-10-06T00:00:00.250000Z",
    "data_source": "synthetic",
}
ALERT = {
    "alert_id": "6699502e-a981-5959-9f24-6df6bd3d3ac5",
    "asset_id": "A17",
    "occurred_at": "2026-10-05T14:00:00Z",
    "code": "seal_leak",
    "message": "Synthetic warning alert: seal leak on Alpha transfer pump A17.",
    "revision": 1,
}
INTERVAL = {"start_at": "2026-10-05T00:00:00Z", "end_at": "2026-10-07T00:00:00Z"}


def alerts(next_cursor: str | None = None, **over: Any) -> dict[str, Any]:
    return {"asset_id": "A17", **INTERVAL, "alerts": [ALERT], "next_cursor": next_cursor, **over}


class Tokens:
    """mcp-read's own workload token, as WorkloadTokenSource would hand it out."""

    def __init__(self) -> None:
        self.invalidated: list[str | None] = []

    async def token(self) -> str:
        return "mcp-read-token"

    def invalidate(self, stale: str | None = None) -> None:
        self.invalidated.append(stale)


class Database:
    """The two persistence calls an asset tool makes, recorded in order with the unit each ran in."""

    def __init__(self, conn: UnitConn, *, resolve: Exception | None = None, scope: Exception | None = None) -> None:
        self.conn, self.resolve_error, self.scope_error = conn, resolve, scope
        self.calls: list[tuple[str, int, dict[str, Any]]] = []

    async def resolve_invocation(self, conn: Any, **kwargs: Any) -> None:
        self.calls.append(("resolve", self.conn.units, kwargs))
        if self.resolve_error is not None:
            raise self.resolve_error

    async def asset_scope(self, conn: Any, **kwargs: Any) -> persistence.AssetScope:
        self.calls.append(("scope", self.conn.units, kwargs))
        if self.scope_error is not None:
            raise self.scope_error
        return SCOPE


Answer = Callable[[httpx2.Request], httpx2.Response]


@asynccontextmanager
async def mcp_read(
    monkeypatch: pytest.MonkeyPatch, db: Database, answer: Answer, tokens: Tokens | None = None
) -> AsyncIterator[tuple[Client, list[httpx2.Request]]]:
    """The app with the two database calls replaced and asset-sim answered by `answer`; every request it got."""
    monkeypatch.setattr(persistence, "resolve_invocation", db.resolve_invocation)
    monkeypatch.setattr(persistence, "asset_scope", db.asset_scope)
    seen: list[httpx2.Request] = []

    def recorded(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return answer(request)

    state = server.State(session=None, verifier=KeyedVerifier())
    fake: Any = db.conn
    state.session = persistence.Session(fake)  # already set, so the lifespan opens no connection
    state.assets = assets.HttpAssetSim(
        "http://asset-sim.test", tokens or Tokens(), transport=httpx2.MockTransport(recorded)
    )
    app = server.build_app(server.build_server(state, issuer=ISSUER, resource_url=RESOURCE), state)
    headers = {"Authorization": "Bearer good", "X-Ops-Invocation": HANDLE}
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with (
            httpx2.AsyncClient(transport=transport, base_url=BASE, headers=headers) as http,
            Client(streamable_http_client(f"{BASE}/mcp", http_client=http), mode="2026-07-28") as client,
        ):
            yield client, seen


def doc_of(result: CallToolResult) -> dict[str, Any]:
    doc = result.structured_content
    assert not result.is_error and isinstance(doc, dict)
    return doc


def respond(status: int, body: Any) -> Answer:
    return lambda request: httpx2.Response(status, json=body)


async def test_status_is_asked_after_both_units_with_mcp_reads_own_token_and_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = Database(UnitConn())
    async with mcp_read(monkeypatch, db, respond(200, STATUS)) as (client, seen):
        doc = doc_of(await client.call_tool("get_asset_status", {"asset_id": "A17"}))
    assert [(name, unit) for name, unit, _ in db.calls] == [("resolve", 1), ("scope", 2)]
    assert db.calls[0][2] == {"handle": HANDLE, "azp": "ops-worker", "tool": Tool.GET_ASSET_STATUS}
    assert db.calls[1][2] == {"handle": HANDLE, "azp": "ops-worker"}
    (request,) = seen
    assert request.url.path == "/assets/A17/status"
    assert request.headers["authorization"] == "Bearer mcp-read-token"  # never the worker's token (ruling 8)
    assert request.headers["x-ops-tenant-id"] == str(ALPHA)
    assert request.headers["x-ops-as-of"] == "2026-10-06T00:00:00.250000Z"  # the definer's instant
    assert "x-ops-invocation" not in request.headers  # the handle never reaches the destination (BS:364)
    assert doc["status"] == "ok" and doc["data"] == STATUS and doc["observed_at"] == "2026-10-06T00:00:00Z"
    tool_contracts.check_result(Tool.GET_ASSET_STATUS, doc)


async def test_another_asset_or_interval_is_refused_before_asset_sim(monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database(UnitConn())
    async with mcp_read(monkeypatch, db, respond(200, STATUS)) as (client, seen):
        b22 = doc_of(await client.call_tool("get_asset_status", {"asset_id": "B22"}))  # R028: alpha asks for B22
        later = {"asset_id": "A17", "start_at": "2026-10-05T00:00:00Z", "end_at": "2026-10-08T00:00:00Z", "limit": 5}
        widened = doc_of(await client.call_tool("get_recent_alerts", later))
        impossible = {**later, "end_at": "2026-02-30T00:00:00Z"}  # the pattern passes; no such day
        nonsense = doc_of(await client.call_tool("get_recent_alerts", impossible))
    assert seen == []  # asset-sim was never asked
    assert b22["error"] == {
        "code": "ASSET_OUT_OF_SCOPE",
        "message": "only the run's own asset may be read",
        "retryable": False,
    }
    assert widened["error"]["code"] == nonsense["error"]["code"] == "INTERVAL_OUT_OF_SCOPE"
    assert b22["observed_at"] == "2026-10-06T00:00:00Z"  # decided after asset_scope: the database's instant


async def test_alerts_forward_the_runs_interval_and_mark_a_further_page(monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database(UnitConn())
    pages = iter([alerts("c" * 76), alerts(None)])
    async with mcp_read(monkeypatch, db, lambda request: httpx2.Response(200, json=next(pages))) as (client, seen):
        spelled = {"asset_id": "A17", "start_at": "2026-10-05T00:00:00+00:00", "end_at": "2026-10-07T00:00:00Z"}
        first = doc_of(await client.call_tool("get_recent_alerts", {**spelled, "limit": 1}))
        second = doc_of(await client.call_tool("get_recent_alerts", {**spelled, "limit": 1, "cursor": "c" * 76}))
    assert (first["truncated"], first["data"]["next_cursor"]) == (True, "c" * 76)
    assert (second["truncated"], second["data"]["next_cursor"]) == (False, None)
    assert dict(seen[0].url.params) == {**INTERVAL, "limit": "1"}  # `+00:00` compared as an instant, sent as Z
    assert dict(seen[1].url.params) == {**INTERVAL, "limit": "1", "cursor": "c" * 76}
    for doc in (first, second):
        tool_contracts.check_result(Tool.GET_RECENT_ALERTS, doc)


def fail_with(exc: type[Exception]) -> Answer:
    def answer(request: httpx2.Request) -> httpx2.Response:
        raise exc("scripted", request=request)

    return answer


def body(text: bytes) -> Answer:
    return lambda request: httpx2.Response(200, content=text)


@pytest.mark.parametrize(
    ("tool", "answer", "code", "retryable"),
    [
        ("status", fail_with(httpx2.ConnectError), "UNAVAILABLE", True),
        ("status", fail_with(httpx2.ReadTimeout), "UNAVAILABLE", True),
        ("status", respond(503, {"code": "UNAVAILABLE"}), "UNAVAILABLE", True),
        ("status", respond(401, {"code": "UNAUTHENTICATED"}), "UNAVAILABLE", True),
        ("status", respond(404, {"code": "NOT_FOUND"}), "NOT_FOUND", False),
        ("alerts", respond(400, {"code": "INVALID_INPUT"}), "INVALID_CURSOR", False),
        ("status", respond(418, {}), "UPSTREAM_INVALID", False),
        ("status", body(b"not json"), "UPSTREAM_INVALID", False),
        ("status", respond(200, {**STATUS, "state": "on fire"}), "UPSTREAM_INVALID", False),  # the contract
        ("status", respond(200, {**STATUS, "asset_id": "B22"}), "UPSTREAM_INVALID", False),  # another asset's data
        ("alerts", respond(200, alerts(end_at="2026-10-08T00:00:00Z")), "UPSTREAM_INVALID", False),  # interval
        (
            "alerts",
            respond(200, alerts(alerts=[{**ALERT, "occurred_at": "2026-10-06T00:00:01Z"}])),
            "UPSTREAM_INVALID",
            False,
        ),  # an alert from after as_of
    ],
)
async def test_asset_sim_failures_map_to_their_codes(
    monkeypatch: pytest.MonkeyPatch, tool: str, answer: Answer, code: str, retryable: bool
) -> None:
    async with mcp_read(monkeypatch, Database(UnitConn()), answer) as (client, _):
        if tool == "status":
            result = await client.call_tool("get_asset_status", {"asset_id": "A17"})
        else:
            result = await client.call_tool(
                "get_recent_alerts", {"asset_id": "A17", **INTERVAL, "limit": 1, "cursor": "x"}
            )
    doc = doc_of(result)
    assert (doc["status"], doc["data"], doc["error"]["code"], doc["error"]["retryable"]) == (
        "error",
        None,
        code,
        retryable,
    )
    assert "on fire" not in str(doc) and "B22" not in str(doc)  # nothing of a refused answer is passed on
    tool_contracts.check_result(Tool.GET_ASSET_STATUS if tool == "status" else Tool.GET_RECENT_ALERTS, doc)


async def test_a_401_drops_mcp_reads_cached_token(monkeypatch: pytest.MonkeyPatch) -> None:
    tokens = Tokens()
    async with mcp_read(monkeypatch, Database(UnitConn()), respond(401, {}), tokens) as (client, _):
        await client.call_tool("get_asset_status", {"asset_id": "A17"})
    assert tokens.invalidated == ["mcp-read-token"]


@pytest.mark.parametrize("where", ["resolve", "scope"])
async def test_a_refused_handle_or_a_lost_membership_is_the_one_plain_refusal(
    monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    db = Database(UnitConn(), **{where: persistence.HandleRejected("invocation handle rejected")})
    async with mcp_read(monkeypatch, db, respond(200, STATUS)) as (client, seen):
        doc = doc_of(await client.call_tool("get_asset_status", {"asset_id": "A17"}))
    assert seen == [] and [name for name, _, _ in db.calls] == (
        ["resolve"] if where == "resolve" else ["resolve", "scope"]
    )
    assert doc["data"] is None
    assert doc["error"] == {"code": "INVALID_HANDLE", "message": "invocation handle rejected", "retryable": False}


# Argument sets on both sides of every bound the committed schemas state; each is judged by the file (jsonschema) and
# by the server (its strict argument model), and the two verdicts must agree.
ARGUMENTS: list[tuple[str, dict[str, Any]]] = [
    ("get_asset_status", {"asset_id": "A17"}),
    ("get_asset_status", {"asset_id": "A" * 32}),
    ("get_asset_status", {"asset_id": "A" * 33}),
    ("get_asset_status", {"asset_id": "a17"}),
    ("get_asset_status", {"asset_id": "A17\n"}),
    ("get_asset_status", {"asset_id": "A17", "tenant_id": str(ALPHA)}),
    ("get_asset_status", {}),
    ("get_recent_alerts", {"asset_id": "A17", **INTERVAL, "limit": 1}),
    ("get_recent_alerts", {"asset_id": "A17", **INTERVAL, "limit": 100, "cursor": "c" * 200}),
    ("get_recent_alerts", {"asset_id": "A17", **INTERVAL, "limit": 101}),
    ("get_recent_alerts", {"asset_id": "A17", **INTERVAL, "limit": 0}),
    ("get_recent_alerts", {"asset_id": "A17", **INTERVAL, "limit": "1"}),
    ("get_recent_alerts", {"asset_id": "A17", **INTERVAL, "limit": 1, "cursor": ""}),
    ("get_recent_alerts", {"asset_id": "A17", **INTERVAL, "limit": 1, "cursor": "c" * 201}),
    ("get_recent_alerts", {"asset_id": "A17", **INTERVAL, "limit": 1, "start_at": "2026-10-05T02:00:00+02:00"}),
    ("get_recent_alerts", {"asset_id": "A17", **INTERVAL, "limit": 1, "start_at": "2026-10-05T00:00:00.5Z"}),
    ("get_recent_alerts", {"asset_id": "A17", **INTERVAL, "limit": 1, "end_at": "2026-10-07"}),
    ("get_recent_alerts", {"asset_id": "A17", "start_at": INTERVAL["start_at"], "limit": 1}),
    ("search_procedures", {"query": "seal", "limit": 8, "mode": "lexical"}),
    ("search_procedures", {"query": "x" * 500, "limit": 1, "mode": "vector_exact", "asset_type": "p" * 40}),
    ("search_procedures", {"query": "", "limit": 1, "mode": "lexical"}),
    ("search_procedures", {"query": "x" * 501, "limit": 1, "mode": "lexical"}),
    ("search_procedures", {"query": "x", "limit": 9, "mode": "lexical"}),
    ("search_procedures", {"query": "x", "limit": True, "mode": "lexical"}),
    ("search_procedures", {"query": "x", "limit": 1, "mode": "vector"}),
    ("search_procedures", {"query": "x", "limit": 1, "mode": "lexical", "asset_type": ""}),
    ("search_procedures", {"query": "x", "limit": 1, "mode": "lexical", "asset_type": None}),
]


async def test_the_advertised_schemas_are_the_committed_files_and_agree_with_the_argument_models() -> None:
    state = server.State(session=None, verifier=KeyedVerifier())
    mcp = server.build_server(state, issuer=ISSUER, resource_url=RESOURCE)
    async with Client(mcp) as client:  # in-process: no bearer middleware, so every accepted call refuses the handle
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert list(tools) == ["get_asset_status", "get_recent_alerts", "search_procedures"]
        for name, tool in tools.items():
            assert tool_contracts.same_input_schema(Tool(name), tool.input_schema), name
        for name, arguments in ARGUMENTS:
            by_file = Draft202012Validator(tool_contracts.input_schema(Tool(name))).is_valid(arguments)
            result = await client.call_tool(name, arguments)
            by_model = not result.is_error  # an accepted call reaches the body, which answers an envelope
            assert by_model == by_file, (name, arguments)
            if by_model:
                assert result.structured_content["error"]["code"] == "INVALID_HANDLE"
```

Run: `uv run python -m pytest tests/plan_m/test_tool_contracts.py tests/plan_m/test_mcp_read_assets.py -q`
Expected: `2 errors` during collection (`ops_core` has no `tool_contracts`; `ops_mcp_read` has no `assets`).

- [ ] **Step 2: jsonschema at run time, and the contracts module**

Edit 1 (`core/pyproject.toml`), replace:

```toml
dependencies = ["pydantic>=2.13,<3", "psycopg[binary]>=3.3,<4", "sqlalchemy>=2.1,<3", "alembic>=1.20,<2", "pyjwt[crypto]>=2.10,<3", "httpx2>=2.13,<3"]
```

with:

```toml
dependencies = ["pydantic>=2.13,<3", "psycopg[binary]>=3.3,<4", "sqlalchemy>=2.1,<3", "alembic>=1.20,<2", "pyjwt[crypto]>=2.10,<3", "httpx2>=2.13,<3", "jsonschema>=4.26,<5"]
```

(the line was over 120 characters before; TOML is not counted by `$COUNT`'s Python files, and splitting the array is
a reformat this task does not need).

Edit 2 (`pyproject.toml`, after the authlib override), replace:

```toml
# authlib 1.8 ships no py.typed (measured in the Plan F review); its stubs package targets httpx, not httpx2.
[[tool.mypy.overrides]]
module = ["authlib.*"]
ignore_missing_imports = true
```

with:

```toml
# authlib 1.8 ships no py.typed (measured in the Plan F review); its stubs package targets httpx, not httpx2.
[[tool.mypy.overrides]]
module = ["authlib.*"]
ignore_missing_imports = true

# jsonschema 4.26 ships no py.typed (measured 2026-10-18); ops_core.tool_contracts keeps its one use behind typed
# functions (T16). types-jsonschema is not locked, and adding it is a lock change for one import.
[[tool.mypy.overrides]]
module = ["jsonschema", "jsonschema.*"]
ignore_missing_imports = true
```

Run: `uv lock --offline` → `Resolved 67 packages`; `git diff --stat uv.lock` → 2 lines added: `ops-core`'s
`dependencies` and `requires-dist` gain `jsonschema` (already locked at 4.26.0 for the dev group).

Create `core/src/ops_core/tool_contracts.py`:

```python
"""The committed MCP tool contracts at run time (T16; Plan M rulings 13 and 15; AM-80, BS:399).

Both sides of the read boundary hold the server to the files in `schemas/`, not to what a server says about itself:
mcp-read advertises exactly `schemas/tools/<tool>.input.schema.json` as each tool's input schema and validates what
asset-sim returned as a whole tool result before it answers; the worker compares every advertised read tool's input
schema with the same file (canonical JSON) and validates every read result against `schemas/tool-result.schema.json`
(R029). The schemas are read from the repository's `schemas/` directory, so a process runs from a checkout (packaging
them for a container is T30's). Errors name the failing rule and the JSON path, never a value from the document.
"""

from __future__ import annotations

import copy
import functools
import json
from pathlib import Path
from typing import Any, Final

from jsonschema import Draft202012Validator

from ops_core.canonical import canonical_json
from ops_core.jobs import Tool

SCHEMAS: Final = Path(__file__).resolve().parents[3] / "schemas"
MAX_RESULT_BYTES: Final = 256 * 1024  # ruling 13: a serialized result above this is refused, whatever it holds


class ContractViolation(ValueError):
    """A document does not satisfy its committed contract; the message names the rule and the path only."""


@functools.cache
def _input_schema(tool: Tool) -> dict[str, Any]:
    schema: dict[str, Any] = json.loads((SCHEMAS / "tools" / f"{tool.value}.input.schema.json").read_text("utf-8"))
    return schema


def input_schema(tool: Tool) -> dict[str, Any]:
    """The tool's committed input schema, a fresh copy each call (a caller may hand it to an SDK that keeps it)."""
    return copy.deepcopy(_input_schema(tool))


def same_input_schema(tool: Tool, advertised: object) -> bool:
    """True when `advertised` is the committed input schema of `tool`, compared as canonical JSON (ruling 13)."""
    try:
        return canonical_json(advertised) == canonical_json(_input_schema(tool))
    except ValueError:  # not canonicalisable (a float, a non-string key): not the committed schema either
        return False


@functools.cache
def _result_validator() -> Any:
    schema = json.loads((SCHEMAS / "tool-result.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


def check_result(tool: Tool, document: object) -> dict[str, Any]:
    """`document` as a tool-result envelope of `tool` that the committed schema accepts, branch and nested data
    included (BS:399).

    Raises:
        ContractViolation: not an object, another tool's envelope, or a schema failure (the first, by path).
    """
    if not isinstance(document, dict):
        raise ContractViolation(f"{tool.value}: the result is not an object")
    if document.get("tool_name") != tool.value:
        raise ContractViolation(f"{tool.value}: the result names another tool")
    errors = sorted(_result_validator().iter_errors(document), key=lambda e: [str(p) for p in e.absolute_path])
    if errors:
        path = "/".join(str(part) for part in errors[0].absolute_path) or "(root)"
        raise ContractViolation(f"{tool.value}: the result fails the contract at {path} ({errors[0].validator})")
    return document
```

Run: `uv run python -m pytest tests/plan_m/test_tool_contracts.py -q` → `5 passed`.

- [ ] **Step 3: mcp-read's asset-sim client and the two asset tools**

Create `mcp-read/src/ops_mcp_read/assets.py`:

```python
"""mcp-read's client for asset-sim (T16; Plan M rulings 6, 8, 12 and 15; SA:555; BS:364).

mcp-read calls asset-sim with its own workload token (client `ops-mcp-read`, audience `asset-sim`), never with the
worker's token and never with the invocation handle; the only context it forwards is what `asset_scope` returned for
the handle: the run's tenant (`X-Ops-Tenant-Id`) and the database instant to answer at (`X-Ops-As-Of`), with the
run's asset in the path and, for alerts, the run's interval. Each call happens outside any database transaction, with
a 10-second timeout and no retry (the job retries). Failures map to one exception each, which the tools turn into
envelope codes (ruling 15): a transport error, a timeout or a 5xx is `Unavailable` (retryable), a 404 is `AssetMissing`
(an unknown asset and another tenant's alike), a 400 to a request that carried a cursor is `CursorRejected`, and
anything else, or a body that is not a JSON object, is `UpstreamInvalid`. A 401 also drops the cached token, so the
next call fetches a fresh one.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Final, Protocol
from urllib.parse import quote

import httpx2
from ops_core import persistence, settings
from ops_core.tokens import TokenRejected, WorkloadTokenSource

CLIENT_ID: Final = "ops-mcp-read"  # the realm's workload client whose tokens carry aud asset-sim
TIMEOUT_SECONDS: Final = 10.0  # ruling 15
ASSET_ID: Final = re.compile(r"[A-Z][A-Z0-9_-]{0,31}")  # schemas/tools/get_asset_status.input.schema.json
ASSET_TYPE: Final = re.compile(r"[a-z][a-z0-9_-]{0,39}")  # the corpus's asset-family names


class AssetSimError(Exception):
    """asset-sim did not answer with data; `code` and `retryable` are what the tool's error envelope carries."""

    code = "UPSTREAM_INVALID"
    retryable = False


class Unavailable(AssetSimError):
    """A transport error, a timeout, a 5xx or a refused token: try again later."""

    code = "UNAVAILABLE"
    retryable = True


class AssetMissing(AssetSimError):
    """asset-sim knows no such asset for the run's tenant (unknown and another tenant's alike)."""

    code = "NOT_FOUND"


class CursorRejected(AssetSimError):
    """The cursor is malformed or was issued for another request."""

    code = "INVALID_CURSOR"


class UpstreamInvalid(AssetSimError):
    """An answer that is not the contract's (ruling 15: mcp-read validates asset-sim's data before returning it)."""


class TokenSource(Protocol):
    """Where the client gets its workload token (WorkloadTokenSource in production)."""

    async def token(self) -> str: ...

    def invalidate(self, stale: str | None = None) -> None: ...


class AssetSim(Protocol):
    """What the tools need from asset-sim, so unit tests can stand one in."""

    async def asset_type(self, scope: persistence.AssetScope) -> str | None:
        """The run's asset's type, or None when asset-sim does not know the asset (ruling 12)."""
        ...

    async def status(self, scope: persistence.AssetScope) -> dict[str, Any]:
        """`get_asset_status`'s data for the run's asset as of `scope.as_of`."""
        ...

    async def alerts(self, scope: persistence.AssetScope, *, limit: int, cursor: str | None) -> dict[str, Any]:
        """One page of `get_recent_alerts`'s data for the run's asset and interval as of `scope.as_of`."""
        ...

    async def aclose(self) -> None:
        """Release the connections."""
        ...


def rfc3339(value: datetime) -> str:
    """The `Z` spelling the contracts use, with microseconds only when the instant has them."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class HttpAssetSim:
    """The real client: one pooled httpx2 client, mcp-read's workload token, the forwarded context as headers."""

    def __init__(
        self, base_url: str, tokens: TokenSource, *, transport: httpx2.AsyncBaseTransport | None = None
    ) -> None:
        """`transport` lets unit tests answer without a socket."""
        self._base = base_url.rstrip("/")
        self._tokens = tokens
        self._http = httpx2.AsyncClient(timeout=TIMEOUT_SECONDS, transport=transport)

    @classmethod
    def from_settings(cls) -> HttpAssetSim:
        """Wired from the environment and the secret file, as the lifespan builds it (ruling 6)."""
        return cls(
            settings.urls().asset_sim,
            WorkloadTokenSource(
                token_url=settings.keycloak().token_url,
                client_id=CLIENT_ID,
                client_secret=settings.read_secret("kc_client_secret_ops_mcp_read"),
            ),
        )

    async def _get(
        self, scope: persistence.AssetScope, suffix: str, params: dict[str, str] | None = None
    ) -> dict[str, Any]:
        # The run's asset id is any text the admission stored; a path segment that is not an asset id is never sent.
        if not ASSET_ID.fullmatch(scope.asset_id):
            raise AssetMissing("the run's asset id is not an asset id")
        try:
            token = await self._tokens.token()
            response = await self._http.get(
                f"{self._base}/assets/{quote(scope.asset_id, safe='')}{suffix}",
                params=params,
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Ops-Tenant-Id": str(scope.tenant_id),
                    "X-Ops-As-Of": rfc3339(scope.as_of),
                },
            )
        except (httpx2.HTTPError, OSError, TokenRejected) as exc:
            raise Unavailable("asset-sim could not be reached") from exc
        status = response.status_code
        if status == 200:
            try:
                body = response.json()
            except ValueError as exc:
                raise UpstreamInvalid("asset-sim answered a body that is not JSON") from exc
            if not isinstance(body, dict):
                raise UpstreamInvalid("asset-sim answered a body that is not an object")
            return body
        if status == 404:
            raise AssetMissing("asset-sim knows no such asset for this tenant")
        if status == 401:
            self._tokens.invalidate(token)  # a stale or revoked token: the next call fetches another
            raise Unavailable("asset-sim refused mcp-read's token")
        if status >= 500:
            raise Unavailable("asset-sim is unavailable")
        if status == 400 and params is not None and "cursor" in params:
            raise CursorRejected("asset-sim refused the cursor")
        raise UpstreamInvalid(f"asset-sim answered {status}")

    async def asset_type(self, scope: persistence.AssetScope) -> str | None:
        try:
            body = await self._get(scope, "")
        except AssetMissing:
            return None
        found = body.get("asset_type")
        if body.get("asset_id") != scope.asset_id or not isinstance(found, str) or not ASSET_TYPE.fullmatch(found):
            raise UpstreamInvalid("asset-sim answered an asset that is not the run's")
        return found

    async def status(self, scope: persistence.AssetScope) -> dict[str, Any]:
        return await self._get(scope, "/status")

    async def alerts(self, scope: persistence.AssetScope, *, limit: int, cursor: str | None) -> dict[str, Any]:
        params = {"start_at": rfc3339(scope.start_at), "end_at": rfc3339(scope.end_at), "limit": str(limit)}
        if cursor is not None:
            params["cursor"] = cursor
        return await self._get(scope, "/alerts", params)

    async def aclose(self) -> None:
        await self._http.aclose()
```

Replace `mcp-read/src/ops_mcp_read/server.py` whole with (the search is unchanged here except that it shares the
unit-1 helper; Task 4 gives it the run's asset type):

```python
"""mcp-read: the authenticated read-tool server (ADR-0003; AM-15 read tools; SA:557 token checks).

Every call must carry `MCP-Protocol-Version: 2026-07-28` (anything else is refused before authentication, AM-30), the
worker's workload access token (`typ` Bearer, aud = this server's resource URL, azp = the worker's client) and an
`X-Ops-Invocation` handle minted for an `investigate` or `resume_input` job; the handle, not the token, says which run
and tenant the call is for (BUILD_SPEC §9). Each tool advertises exactly its committed input schema
(`schemas/tools/`, Plan M ruling 13) and its strict argument model forbids extra keys, so an argument that tries to
supply a tenant, role or actor is refused before the tool body runs (SA:350). Results are the AM-80 tool-result
envelope. Three tools (T16):

- `get_asset_status` and `get_recent_alerts` resolve the handle and check the tool in one committed unit, read the
  run's scope through `asset_scope` in a second, and only then call asset-sim with mcp-read's own workload token and
  the forwarded tenant and instant (`assets.HttpAssetSim`), outside any transaction. They answer for the run's own
  asset and fixed interval only (`ASSET_OUT_OF_SCOPE`, `INTERVAL_OUT_OF_SCOPE`), and validate asset-sim's data as a
  whole tool result before returning it (`UPSTREAM_INVALID`, ruling 15).
- `search_procedures` answers from the governed corpus through `search_procedures_scoped` (T17); mcp-read reads no
  file.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from collections.abc import AsyncIterator, Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Final, Literal, Protocol, TypedDict
from uuid import uuid4

import psycopg
import uvicorn
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.tools.base import Tool
from ops_core import persistence, redaction, settings, tool_contracts
from ops_core.jobs import Tool as ToolName
from ops_core.mcp_protocol import MCP_PATH, ProtocolVersionGuard
from ops_core.settings import Role
from ops_core.tokens import Principal, TokenRejected, TokenVerifier
from pydantic import AnyHttpUrl, ConfigDict, Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp

from ops_mcp_read import assets

# Revision 0009's startup marker, kept under this name for callers that read it here; the value is core's, which
# mcp-write checks too (Plan J ruling 18 and the final review).
HANDLE_BINDING = persistence.HANDLE_BINDING
# The argument models' patterns: the committed schemas' own (`schemas/tools/`), in the end-of-text form pydantic's
# Rust regex engine accepts (`$` there never matches before a final newline, which the schemas' `(?![\s\S])` says).
ASSET_ID: Final = r"^[A-Z][A-Z0-9_-]{0,31}$"
INSTANT: Final = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?(Z|\+00:00)$"


class ToolResult(TypedDict):
    """The AM-80 tool-result envelope every tool returns."""

    tool_name: str
    request_id: str
    status: str
    observed_at: str
    truncated: bool
    data: dict[str, Any] | None
    error: dict[str, Any] | None


def stamp(value: datetime) -> str:
    """UTC timestamp in the `...Z` seconds-only spelling the contract uses."""
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def tool_error(code: str, message: str, *, retryable: bool = False) -> dict[str, Any]:
    """The `error` object of an envelope; only an unavailable asset-sim is worth a retry (ruling 15)."""
    return {"code": code, "message": message, "retryable": retryable}


def envelope(
    tool_name: str,
    *,
    data: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    observed_at: datetime | None = None,
    truncated: bool = False,
) -> ToolResult:
    """Wrap data or an error in the AM-80 envelope with a fresh request_id. `observed_at` is the database instant the
    answer was decided at (Plan M ruling 3); a refusal before any database unit has none and takes the wall clock."""
    return {
        "tool_name": tool_name,
        "request_id": str(uuid4()),
        "status": "error" if error is not None else "ok",
        "observed_at": stamp(datetime.now(UTC) if observed_at is None else observed_at),
        "truncated": truncated,
        "data": None if error is not None else data,
        "error": error,
    }


def search_response(found: persistence.Procedures) -> ToolResult:
    """The tool's answer from what `search_procedures_scoped` returned; database-free so the contract test can validate
    it. The rank stays behind: the contract has no score, and the model never sees one (docs/retrieval.md). Every
    `retrieved_at` and the envelope's `observed_at` are the instant the definer decided permission at, never the wall
    clock (Plan M ruling 3, Plan L final review M4), and a section cut at the contract's bound sets `truncated`
    (ruling 11)."""
    retrieved_at = stamp(found.retrieved_at)
    results = [
        {
            "evidence_id": hit.evidence_id,
            "document_id": hit.document_id,
            "version": hit.version,
            "section": hit.section,
            "content_sha256": hit.content_sha256,
            "excerpt": hit.excerpt,
            "effective_from": stamp(hit.effective_from),
            "retrieved_at": retrieved_at,
        }
        for hit in found.results
    ]
    return envelope(
        "search_procedures",
        data={"results": results, "retrieval_mode": "lexical", "corpus_version": found.corpus_version},
        observed_at=found.retrieved_at,
        truncated=found.truncated,
    )


def within_scope(tool: ToolName, data: dict[str, Any], scope: persistence.AssetScope) -> bool:
    """asset-sim answered for the run's asset (and, for alerts, the run's interval, with no alert outside it or after
    `as_of`): what the schema cannot say about the data (ruling 15)."""
    if data.get("asset_id") != scope.asset_id:
        return False
    if tool is not ToolName.GET_RECENT_ALERTS:
        return True
    try:
        interval = (datetime.fromisoformat(data["start_at"]), datetime.fromisoformat(data["end_at"]))
        alerts = [(alert["asset_id"], datetime.fromisoformat(alert["occurred_at"])) for alert in data["alerts"]]
    except (KeyError, TypeError, ValueError):
        return False
    return interval == (scope.start_at, scope.end_at) and all(
        asset_id == scope.asset_id and scope.start_at <= occurred < scope.end_at and occurred <= scope.as_of
        for asset_id, occurred in alerts
    )


class Verifier(Protocol):  # the subset of ops_core.tokens.TokenVerifier the server needs; unit tests stub it
    """Token-verifier subset the server needs, so unit tests can stub it."""

    @property
    def ready(self) -> bool: ...

    async def load_keys(self) -> None: ...

    async def verify_async(self, token: str) -> Principal: ...


class McpVerifier:
    """The SDK's TokenVerifier protocol: None means 401. The SDK re-checks `expires_at`, consistently with PyJWT.

    A token whose `aud` lacks this server's resource URL is refused here, whatever audience the wrapped verifier was
    configured with, and only then is `resource` stamped with that URL (Plan J ruling 2). The SDK's own resource check
    (`validate_token_resource`) stays on as a second layer; it cannot refuse anything while the stamp is this server's
    own URL, and would decide only if the stamp ever came from the token.
    """

    def __init__(self, verifier: Verifier, resource_url: str) -> None:
        """Adapt a token verifier to the SDK's bearer-auth hook; `resource_url` is this server's audience."""
        self._verifier = verifier
        self._resource = resource_url

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            principal = await self._verifier.verify_async(token)
        except TokenRejected:
            return None
        if self._resource not in principal.audiences:
            return None
        return AccessToken(
            token=token,
            client_id=principal.azp,
            scopes=[],
            expires_at=principal.expires_at,
            resource=self._resource,
            subject=principal.subject,
            claims=dict(principal.claims),
        )


def contract_tool(fn: Any) -> Tool:
    """A Tool whose argument model forbids extra keys and refuses lax coercion, and which advertises exactly the
    committed input schema.

    The SDK derives the model from the signature and ignores unknown keys (measured in the Plan D spike); SA:350
    requires the opposite, so the model is subclassed with `extra="forbid"`. `strict` stops lax coercion, so
    `limit="1"` or `limit=True` is refused rather than read as 1. What a client is shown is the file in `schemas/tools/`
    itself (ruling 13), which the worker compares with its own copy; tests/plan_m proves model and file agree.
    """
    tool = Tool.from_function(fn)
    base = tool.fn_metadata.arg_model
    strict: Any = type(
        base.__name__, (base,), {"model_config": ConfigDict(arbitrary_types_allowed=True, extra="forbid", strict=True)}
    )
    tool.fn_metadata.arg_model = strict
    tool.parameters = tool_contracts.input_schema(ToolName(tool.name))
    return tool


@dataclass
class State:
    """Process-wide dependencies the tools and the app share; `session` and `assets` are filled at startup."""

    session: persistence.Session | None
    verifier: Verifier
    assets: assets.AssetSim | None = None


@dataclass(frozen=True)
class Caller:
    """A call past its first unit: the presented handle and the token's `azp`, which every definer binds again."""

    handle: str
    azp: str


def build_server(state: State, *, issuer: str, resource_url: str) -> MCPServer:
    """Assemble the MCP server with bearer auth and the three strict tools, bound to `state`."""

    async def resolve(tool: ToolName, ctx: Context) -> Caller | ToolResult:
        """Unit 1 (erratum 80): the handle resolved for mcp-read and the tool allowed for its job type, run state and
        attempt (`persistence.allowed_tool`), committed before anything else runs. A refusal is the one plain
        `INVALID_HANDLE` envelope (SA:355), on the wall clock: no database instant decided it."""
        token = get_access_token()
        handle = (ctx.headers or {}).get("x-ops-invocation")  # header names arrive lower-case
        if token is None or not handle or state.session is None:
            return envelope(tool.value, error=tool_error("INVALID_HANDLE", "missing invocation handle"))
        try:
            async with state.session.unit() as conn:
                await persistence.resolve_invocation(conn, handle=handle, azp=token.client_id, tool=tool)
        except persistence.HandleRejected as exc:
            return envelope(tool.value, error=tool_error("INVALID_HANDLE", str(exc)))
        return Caller(handle, token.client_id)

    async def scope_of(tool: ToolName, caller: Caller) -> persistence.AssetScope | ToolResult:
        """Unit 2: `asset_scope` resolves the same handle again (a handle released since unit 1 is refused here too),
        re-checks the requester's membership (R028) and returns the run's asset, interval and `as_of`."""
        assert state.session is not None  # resolve() answered only with a session
        try:
            async with state.session.unit() as conn:
                return await persistence.asset_scope(conn, handle=caller.handle, azp=caller.azp)
        except persistence.HandleRejected as exc:
            return envelope(tool.value, error=tool_error("INVALID_HANDLE", str(exc)))

    async def from_asset_sim(
        tool: ToolName, scope: persistence.AssetScope, call: Awaitable[dict[str, Any]]
    ) -> ToolResult:
        """asset-sim's data as the tool's result, stamped with `as_of`, or the error envelope of its failure. The
        whole result is validated against the committed contract, and the data against the run's scope, before it
        leaves (ruling 15): asset-sim is a separate service, not a trusted record."""
        try:
            data = await call
        except assets.AssetSimError as exc:
            error = tool_error(exc.code, str(exc), retryable=exc.retryable)
            return envelope(tool.value, error=error, observed_at=scope.as_of)
        truncated = tool is ToolName.GET_RECENT_ALERTS and data.get("next_cursor") is not None  # ruling 10
        doc = envelope(tool.value, data=data, observed_at=scope.as_of, truncated=truncated)
        try:
            tool_contracts.check_result(tool, doc)
        except tool_contracts.ContractViolation:
            pass
        else:
            if within_scope(tool, data, scope):
                return doc
        error = tool_error("UPSTREAM_INVALID", "asset-sim answered outside the contract")
        return envelope(tool.value, error=error, observed_at=scope.as_of)

    def unconfigured(tool: ToolName, scope: persistence.AssetScope) -> ToolResult:
        """No asset-sim client (only before the lifespan ran): answered as an unreachable asset-sim."""
        error = tool_error("UNAVAILABLE", "asset-sim is not configured", retryable=True)
        return envelope(tool.value, error=error, observed_at=scope.as_of)

    async def get_asset_status(
        asset_id: Annotated[str, Field(max_length=32, pattern=ASSET_ID)],
        ctx: Context,
    ) -> ToolResult:
        """The run's asset's synthetic status as of the database instant (AM-15 read tool, T16)."""
        name = ToolName.GET_ASSET_STATUS
        caller = await resolve(name, ctx)
        if not isinstance(caller, Caller):
            return caller
        scope = await scope_of(name, caller)
        if not isinstance(scope, persistence.AssetScope):
            return scope
        if asset_id != scope.asset_id:  # before asset-sim is asked anything (ruling 8)
            error = tool_error("ASSET_OUT_OF_SCOPE", "only the run's own asset may be read")
            return envelope(name.value, error=error, observed_at=scope.as_of)
        if state.assets is None:
            return unconfigured(name, scope)
        return await from_asset_sim(name, scope, state.assets.status(scope))

    async def get_recent_alerts(
        asset_id: Annotated[str, Field(max_length=32, pattern=ASSET_ID)],
        start_at: Annotated[str, Field(pattern=INSTANT)],
        end_at: Annotated[str, Field(pattern=INSTANT)],
        limit: Annotated[int, Field(ge=1, le=100)],
        ctx: Context,
        # Absent means the first page. The empty default is never validated (pydantic leaves defaults alone), so a
        # caller cannot send "" or null; the advertised schema is the committed file, which has no default.
        cursor: Annotated[str, Field(min_length=1, max_length=200)] = "",
    ) -> ToolResult:
        """The run's asset's alerts in the run's fixed `[start_at, end_at)`, at or before the database instant, one
        page at a time (AM-15 read tool, T16)."""
        name = ToolName.GET_RECENT_ALERTS
        caller = await resolve(name, ctx)
        if not isinstance(caller, Caller):
            return caller
        scope = await scope_of(name, caller)
        if not isinstance(scope, persistence.AssetScope):
            return scope
        if asset_id != scope.asset_id:
            error = tool_error("ASSET_OUT_OF_SCOPE", "only the run's own asset may be read")
            return envelope(name.value, error=error, observed_at=scope.as_of)
        try:
            asked = (datetime.fromisoformat(start_at), datetime.fromisoformat(end_at))
        except ValueError:  # the pattern passed but the date does not exist (February 30): not the run's interval
            asked = None
        if asked != (scope.start_at, scope.end_at):  # compared as instants, so `+00:00` and `Z` agree (ruling 9)
            error = tool_error("INTERVAL_OUT_OF_SCOPE", "only the run's own interval may be read")
            return envelope(name.value, error=error, observed_at=scope.as_of)
        if state.assets is None:
            return unconfigured(name, scope)
        return await from_asset_sim(name, scope, state.assets.alerts(scope, limit=limit, cursor=cursor or None))

    async def search_procedures(
        query: Annotated[str, Field(min_length=1, max_length=500)],
        limit: Annotated[int, Field(ge=1, le=8)],
        mode: Literal["lexical", "vector_exact"],
        ctx: Context,
        # Absent means "any asset". The empty default is never validated (pydantic leaves defaults alone), so a
        # caller cannot send "" or null (Plan L ruling 11); the advertised schema is the committed file.
        asset_type: Annotated[str, Field(min_length=1, max_length=40)] = "",
    ) -> ToolResult:
        """Lexical search over the calling run's tenant's approved, effective procedure sections (AM-15 read tool),
        through `search_procedures_scoped` (T17)."""
        name = ToolName.SEARCH_PROCEDURES
        caller = await resolve(name, ctx)
        if not isinstance(caller, Caller):
            return caller
        if mode != "lexical":
            # TODO(T16): translate vector_exact to mode=vector once T18 stores embeddings (erratum 3).
            return envelope(name.value, error=tool_error("UNSUPPORTED_MODE", "vector_exact arrives with T18"))
        assert state.session is not None  # resolve() answered only with a session
        # A second unit, after the resolution committed (erratum 80): the definer resolves the same handle again, so a
        # handle released in between is refused here too, and the tenant comes from the handle, never an argument.
        try:
            async with state.session.unit() as conn:
                found = await persistence.search_procedures(
                    conn,
                    handle=caller.handle,
                    azp=caller.azp,
                    query=query,
                    asset_type=asset_type or None,
                    limit=limit,
                )
        except persistence.HandleRejected as exc:
            return envelope(name.value, error=tool_error("INVALID_HANDLE", str(exc)))
        except persistence.Refused as exc:
            return envelope(name.value, error=tool_error("REFUSED", exc.code))
        return search_response(found)

    return MCPServer(
        name="mcp-read",
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(issuer), resource_server_url=AnyHttpUrl(resource_url), validate_token_resource=True
        ),
        token_verifier=McpVerifier(state.verifier, resource_url),
        tools=[contract_tool(get_asset_status), contract_tool(get_recent_alerts), contract_tool(search_procedures)],
    )


def build_app(server: MCPServer, state: State) -> Starlette:
    """Mount the MCP transport beside health routes and own the database session, the asset-sim client and key
    loading."""
    mcp_app = server.streamable_http_app(streamable_http_path=MCP_PATH, stateless_http=True, json_response=True)

    @contextlib.asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        """Open the session, the asset-sim client and the keys, run the mounted app's lifespan, then close them."""
        if state.session is None:
            conn = await persistence.connect(settings.app_postgres(Role.MCP_READ))
            try:
                await persistence.assert_clock_profile(conn, settings.profile())
                await persistence.assert_function_text(conn, *HANDLE_BINDING)
                await persistence.assert_function_text(conn, *persistence.GOVERNED_CORPUS)  # 0011 (T17)
                await persistence.assert_function_text(conn, *persistence.ASSET_SCOPE)  # 0012 (T16)
                await persistence.assert_function_text(conn, *persistence.SEARCH_INSTANT)  # 0012 (T16)
            except BaseException:  # a failed start must leak no connection, and a re-entered lifespan re-asserts
                await conn.close()
                raise
            state.session = persistence.Session(conn)
        # A mounted sub-app's lifespan never runs on its own; the session manager lives in it (measured).
        try:
            if state.assets is None:  # inside the try: a missing secret file must close the connection too
                state.assets = assets.HttpAssetSim.from_settings()  # mcp-read's own token (rulings 6 and 8)
            if not state.verifier.ready:  # inside the try: a failed JWKS load must close the connection too
                await state.verifier.load_keys()
            async with mcp_app.router.lifespan_context(mcp_app):
                yield
        finally:
            if state.assets is not None:
                await state.assets.aclose()
            await state.session.conn.close()

    async def live(_: Request) -> JSONResponse:
        """Liveness: the process is up."""
        return JSONResponse({"status": "live"})

    async def ready(_: Request) -> JSONResponse:
        """Readiness: keys loaded and the database answers (asset-sim is a dependency of a call, not of readiness)."""
        if state.session is None or not state.verifier.ready:
            return JSONResponse({"status": "not ready"}, status_code=503)
        try:
            await state.session.ping()
        except (psycopg.Error, OSError):  # readiness reports a database failure as not ready
            return JSONResponse({"status": "not ready"}, status_code=503)
        return JSONResponse({"status": "ready"})

    return Starlette(
        routes=[
            Route("/health/live", live),
            Route("/health/ready", ready),
            # The version rule runs before the SDK app and its bearer auth (AM-30, Plan J ruling 4).
            Mount("/", app=ProtocolVersionGuard(mcp_app)),
        ],
        lifespan=lifespan,
    )


def read_verifier(kc: settings.Keycloak, urls: settings.Urls) -> TokenVerifier:
    """mcp-read's token checks (SA:557, Plan J ruling 2): the realm's issuer and keys, this server's resource URL as the
    audience, the worker's client (`settings.workload_client_id`, Plan K ruling 12) as the only `azp`, and an access
    token's `typ` claim. `production_app` builds its verifier here, and the unit tests build theirs here too, so they
    pin the wiring that runs."""
    return TokenVerifier(
        issuer=kc.issuer,
        audience=urls.mcp_read_resource,
        allowed_azp=frozenset({settings.workload_client_id()}),
        jwks_url=kc.jwks_url,
        token_type="Bearer",  # an access token: Keycloak's ID and refresh tokens carry another `typ` (ruling 2)
    )


def production_app() -> Starlette:
    """The app wired from the environment and secret files, as `python -m ops_mcp_read` runs it."""
    kc = settings.keycloak()
    urls = settings.urls()
    state = State(session=None, verifier=read_verifier(kc, urls))
    return build_app(build_server(state, issuer=kc.issuer, resource_url=urls.mcp_read_resource), state)


def serve_app(app: ASGIApp, port: int) -> None:
    """Serve with uvicorn programmatically on a selector loop (ruling 23: `uvicorn.run` picks the Proactor loop on
    Windows and psycopg async refuses it)."""
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", log_config=None))
    if sys.platform == "win32":
        asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(server.serve())


def serve() -> None:
    """Entry point: serve the production app on OPS_MCP_READ_PORT (default 8081)."""
    # The redaction filter must sit on the root handler before the first log line (T11 note 4).
    redaction.install()
    serve_app(production_app(), settings.env_int("OPS_MCP_READ_PORT", 8081))
```

Edit 1 (`tests/plan_d/test_mcp_read.py`, the docstring), replace:

```python
now the definer's, tests/e2e/test_migration_0011_live.py), a tool schema that drifts from schemas/tools/, and an extra
argument such as tenant_id silently ignored (SA:350).
```

with:

```python
now the definer's, tests/e2e/test_migration_0011_live.py), a tool schema that is not the file in schemas/tools/ (T16),
and an extra argument such as tenant_id silently ignored (SA:350).
```

Edit 2 (`tests/plan_d/test_mcp_read.py`, the imports and constants), replace:

```python
from pathlib import Path
from typing import Any
from uuid import UUID
```

with:

```python
from pathlib import Path
from uuid import UUID
```

then replace:

```python
INPUT = json.loads(Path("schemas/tools/search_procedures.input.schema.json").read_text(encoding="utf-8"))
```

with nothing (delete the line; the schema test compares every tool with its file now).

Edit 3 (`tests/plan_d/test_mcp_read.py`, the schema test, to the end of the file), replace:

```python
@pytest.mark.asyncio
async def test_tool_schema_conforms_to_the_contract_and_rejects_extra_arguments() -> None:
    state = server.State(session=None, verifier=StubVerifier())
    mcp = server.build_server(
        state, issuer="http://localhost:18080/realms/ops-dev", resource_url="http://mcp-read:8081/mcp"
    )
    async with Client(mcp) as client:  # in-process: no HTTP, so no bearer middleware; schema and validation only
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert set(tools) == {"search_procedures"}
        schema: dict[str, Any] = tools["search_procedures"].input_schema
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(INPUT["required"])
        assert set(schema["properties"]) == set(INPUT["properties"])  # since T17 the optional asset_type too
        assert schema["properties"]["mode"]["enum"] == INPUT["properties"]["mode"]["enum"]
        assert (schema["properties"]["limit"]["minimum"], schema["properties"]["limit"]["maximum"]) == (1, 8)
        assert (schema["properties"]["query"]["minLength"], schema["properties"]["query"]["maxLength"]) == (1, 500)
        asset_type = schema["properties"]["asset_type"]
        assert (asset_type["type"], asset_type["minLength"], asset_type["maxLength"]) == ("string", 1, 40)
        assert "default" not in asset_type  # nothing for a schema-driven client to copy (round 1, M3)
        extra = await client.call_tool(
            "search_procedures", {"query": "x", "limit": 1, "mode": "lexical", "tenant_id": str(ALPHA)}
        )
        assert extra.is_error  # SA:350: an argument that supplies a tenant is rejected, not ignored
        bad = await client.call_tool("search_procedures", {"query": "x", "limit": 9, "mode": "lexical"})
        assert bad.is_error
        for lax in ("1", True):  # lax coercion would accept both as 1
            assert (
                await client.call_tool("search_procedures", {"query": "x", "limit": lax, "mode": "lexical"})
            ).is_error
        for empty in ("", None, "x" * 41):  # the contract's asset_type is a string of 1 to 40 characters
            arguments = {"query": "x", "limit": 1, "mode": "lexical", "asset_type": empty}
            assert (await client.call_tool("search_procedures", arguments)).is_error, empty
        # Without the bearer middleware there is no access token, so the tool body refuses before any lookup.
        res = await client.call_tool("search_procedures", {"query": "x", "limit": 1, "mode": "lexical"})
        assert not res.is_error and res.structured_content["status"] == "error"
        assert res.structured_content["error"]["code"] == "INVALID_HANDLE"
```

with:

```python
@pytest.mark.asyncio
async def test_tool_schemas_are_the_committed_files_and_extra_arguments_are_refused() -> None:
    state = server.State(session=None, verifier=StubVerifier())
    mcp = server.build_server(
        state, issuer="http://localhost:18080/realms/ops-dev", resource_url="http://mcp-read:8081/mcp"
    )
    accepted = {
        "get_asset_status": {"asset_id": "A17"},
        "get_recent_alerts": {
            "asset_id": "A17",
            "start_at": "2026-10-05T00:00:00Z",
            "end_at": "2026-10-06T00:00:00Z",
            "limit": 10,
        },
        "search_procedures": {"query": "x", "limit": 1, "mode": "lexical"},
    }
    async with Client(mcp) as client:  # in-process: no HTTP, so no bearer middleware; schema and validation only
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert set(tools) == set(accepted)  # the three read tools since T16
        for name, tool in tools.items():
            committed = json.loads(Path(f"schemas/tools/{name}.input.schema.json").read_text(encoding="utf-8"))
            assert tool.input_schema == committed, name  # the committed file itself (Plan M ruling 13)
        assert "default" not in tools["search_procedures"].input_schema["properties"]["asset_type"]  # round 1, M3
        for name, arguments in accepted.items():
            extra = await client.call_tool(name, {**arguments, "tenant_id": str(ALPHA)})
            assert extra.is_error, name  # SA:350: an argument that supplies a tenant is rejected, not ignored
            # Without the bearer middleware there is no access token, so the tool body refuses before any lookup.
            res = await client.call_tool(name, arguments)
            assert not res.is_error and res.structured_content["status"] == "error", name
            assert res.structured_content["error"]["code"] == "INVALID_HANDLE", name
        bad = await client.call_tool("search_procedures", {"query": "x", "limit": 9, "mode": "lexical"})
        assert bad.is_error
        for lax in ("1", True):  # lax coercion would accept both as 1
            assert (
                await client.call_tool("search_procedures", {"query": "x", "limit": lax, "mode": "lexical"})
            ).is_error
        for empty in ("", None, "x" * 41):  # the contract's asset_type is a string of 1 to 40 characters
            arguments = {"query": "x", "limit": 1, "mode": "lexical", "asset_type": empty}
            assert (await client.call_tool("search_procedures", arguments)).is_error, empty
```

Edit 4 (`tests/plan_j/test_mcp_read_http.py`, after `IdleConn`), replace:

```python
def read_app() -> Any:
    state = server.State(session=None, verifier=KeyedVerifier())
    idle: Any = IdleConn()
    state.session = persistence.Session(idle)  # already set, so the lifespan opens no connection
```

with:

```python
class IdleAssets:
    """Stands in for mcp-read's asset-sim client (T16), so the lifespan builds none; nothing here reaches it."""

    async def asset_type(self, scope: object) -> str | None:
        raise AssertionError("asset-sim was asked")

    async def status(self, scope: object) -> dict[str, Any]:
        raise AssertionError("asset-sim was asked")

    async def alerts(self, scope: object, *, limit: int, cursor: str | None) -> dict[str, Any]:
        raise AssertionError("asset-sim was asked")

    async def aclose(self) -> None:
        return None


def read_app() -> Any:
    state = server.State(session=None, verifier=KeyedVerifier())
    idle: Any = IdleConn()
    state.session = persistence.Session(idle)  # already set, so the lifespan opens no connection
    state.assets = IdleAssets()  # likewise for the asset-sim client (T16)
```

Edit 5 (`tests/plan_j/test_mcp_read_http.py`, the two tool lists), replace:

```python
        assert [t["name"] for t in listed.json()["result"]["tools"]] == ["search_procedures"]
```

with:

```python
        assert [t["name"] for t in listed.json()["result"]["tools"]] == [
            "get_asset_status",
            "get_recent_alerts",
            "search_procedures",
        ]  # T16
```

then replace:

```python
        assert [t.name for t in (await client.list_tools()).tools] == ["search_procedures"]
```

with:

```python
        assert [t.name for t in (await client.list_tools()).tools] == [
            "get_asset_status",
            "get_recent_alerts",
            "search_procedures",
        ]
```

Edit 6 (`tests/plan_j/test_mcp_read_startup.py`, `start`: the lifespan now builds the asset-sim client and reads its
secret file), replace:

```python
    monkeypatch.setattr(settings, "app_postgres", lambda role: role)
    monkeypatch.setenv("PROFILE", "dev")
    state = server.State(session=None, verifier=KeyedVerifier())
```

with:

```python
    monkeypatch.setattr(settings, "app_postgres", lambda role: role)
    monkeypatch.setattr(settings, "read_secret", lambda name: "unit-test")  # the asset-sim token source's (T16)
    monkeypatch.setenv("PROFILE", "dev")
    state = server.State(session=None, verifier=KeyedVerifier())
```

Edit 7 (`tests/plan_l/test_mcp_read_corpus.py`, the import and `call`), replace:

```python
from tests.plan_j.test_mcp_read_http import BASE, ISSUER, RESOURCE, KeyedVerifier
```

with:

```python
from tests.plan_j.test_mcp_read_http import BASE, ISSUER, RESOURCE, IdleAssets, KeyedVerifier
```

then replace:

```python
    state.session = persistence.Session(fake)  # already set, so the lifespan opens no connection
```

with:

```python
    state.session = persistence.Session(fake)  # already set, so the lifespan opens no connection
    state.assets = IdleAssets()  # the search asks asset-sim nothing yet
```

Edit 8 (`tests/e2e/test_mcp_read_t15_live.py`, the protocol test's list), replace:

```python
    assert listed.status_code == 200 and [t["name"] for t in listed.json()["result"]["tools"]] == ["search_procedures"]
```

with:

```python
    names = [t["name"] for t in listed.json()["result"]["tools"]]
    assert listed.status_code == 200 and names == ["get_asset_status", "get_recent_alerts", "search_procedures"]  # T16
```

Edit 9 (`tests/e2e/test_mcp_read_process_live.py`, R025's list), replace:

```python
        assert [tool.name for tool in tools] == ["search_procedures"]
        assert tools[0].input_schema["additionalProperties"] is False
```

with:

```python
        assert [tool.name for tool in tools] == ["get_asset_status", "get_recent_alerts", "search_procedures"]  # T16
        assert all(tool.input_schema["additionalProperties"] is False for tool in tools)
```

then replace:

```python
            f" {PROTOCOL_VERSION} listed [search_procedures], called ok"
```

with:

```python
            f" {PROTOCOL_VERSION} listed the three read tools, called search_procedures ok"
```

Run: `uv run ruff format core mcp-read tests && uv run ruff check --fix core mcp-read tests`, then
`uv run python -m pytest tests/plan_m tests/plan_d tests/plan_j tests/plan_k tests/plan_l -q`
Expected: every test passes (`test_tool_contracts.py` 5, `test_mcp_read_assets.py` 19, of which 12 are the
parametrised failure mappings).

- [ ] **Step 4: The live asset tools**

Create `tests/e2e/test_mcp_read_t16_live.py`:

```python
"""mcp-read's read tools over a real socket with Keycloak's tokens, asset-sim behind it (OPS_LIVE=1; R028, T16 DoD
1; Plan M rulings 3, 7-10 and 15).

mcp-read is `production_app()` under uvicorn on a free loopback port (test_mcp_read_t15_live's `serving`), asset-sim
the `asset_sim` fixture's, both in the test's loop; mcp-read reaches asset-sim with its own `ops-mcp-read` token.
Catches: a status or alert page that is not asset-sim's answer for the run's asset at the database instant (a moved
test clock must move it into the A17 seal-leak window); a page whose `truncated` disagrees with `next_cursor`; alpha
reading beta's B22, whether it names B22 on an A17 run (refused before asset-sim) or its run itself names B22
(asset-sim's own tenant filter: NOT_FOUND); another interval served; a requester who lost the membership still served
by the asset tools; and an asset-sim failure (unavailable, malformed, slow) that is not the documented envelope.
Writes reports/mcp-read/t16-read-tools.txt (codes and counts only).
"""

import time
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx2
import pytest
from ops_core import persistence, settings, tool_contracts
from ops_core.jobs import Tool
from ops_core.settings import Role
from ops_core.tokens import WorkloadTokenSource

from tests.e2e.conftest import lease_for, purge_run
from tests.e2e.test_fenced_definers_live import investigate_job, read_handle
from tests.e2e.test_mcp_read_t15_live import call, serving, worker_token
from tests.e2e.test_migrations_and_persistence import new_run

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("ingested", "asset_sim")]

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")
ALEX = UUID("2fc05986-c7ec-544c-b628-fdb112bbf18a")
SEAL_WINDOW = (datetime(2026, 10, 5, tzinfo=UTC), datetime(2026, 10, 7, tzinfo=UTC))  # both A17 seal alerts
INTERVAL = {"start_at": "2026-10-05T00:00:00Z", "end_at": "2026-10-07T00:00:00Z"}
MOVE = "UPDATE app.test_clock SET clock_offset = %s::timestamptz - clock_timestamp()"  # test_harness only (AM-20.6)
EVIDENCE = Path("reports/mcp-read/t16-read-tools.txt")
EXPECTED_LINES = 4  # one per test below


@pytest.fixture(scope="module")
def lines() -> Iterator[list[str]]:
    out = [f"T16 read tools — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"]
    yield out
    if len(out) != 1 + EXPECTED_LINES:  # a failed or partial run leaves the committed file as it was
        return
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


async def handle_for(app_conn: persistence.Conn, role_conn: RoleConn, run: UUID, owner: str) -> str:
    """A read handle for the run's investigate job under a lease taken now."""
    worker = await role_conn(Role.WORKER)
    lease = await lease_for(worker, run, owner=owner, seconds=600)
    return await read_handle(worker, run, await investigate_job(app_conn, run), lease)


async def tool(url: str, token: str, handle: str, name: Tool, arguments: dict[str, Any]) -> dict[str, Any]:
    """One call's envelope, checked against the committed contract whatever it says."""
    result = await call(url, token, handle, tool=name.value, arguments=arguments)
    assert not result.is_error and isinstance(result.structured_content, dict)
    return tool_contracts.check_result(name, result.structured_content)


async def test_the_asset_tools_answer_for_the_run_at_the_database_instant(
    app_conn: persistence.Conn, role_conn: RoleConn, secret: Callable[[str], str], lines: list[str]
) -> None:
    harness = await role_conn(Role.TEST_HARNESS)
    _, _, run = await new_run(app_conn, ALPHA, api=await role_conn(Role.API), interval=SEAL_WINDOW)
    token = await worker_token(secret)
    try:
        async with serving() as url:
            handle = await handle_for(app_conn, role_conn, run, "t16-now")
            now = await tool(url, token, handle, Tool.GET_ASSET_STATUS, {"asset_id": "A17"})
            assert (now["data"]["state"], now["data"]["revision"]) == ("normal", 2)  # after both alerts' windows
            first = await tool(url, token, handle, Tool.GET_RECENT_ALERTS, {"asset_id": "A17", **INTERVAL, "limit": 1})
            cursor = first["data"]["next_cursor"]
            assert len(first["data"]["alerts"]) == 1 and first["truncated"] and cursor
            rest = {"asset_id": "A17", **INTERVAL, "limit": 1, "cursor": cursor}
            second = await tool(url, token, handle, Tool.GET_RECENT_ALERTS, rest)
            assert len(second["data"]["alerts"]) == 1 and not second["truncated"]
            assert second["data"]["next_cursor"] is None
            assert [a["revision"] for a in first["data"]["alerts"] + second["data"]["alerts"]] == [1, 2]
            try:
                # The database clock moved back inside the A17 window. The handle stays good: its lease and its 60 s
                # lie further ahead of a clock moved back. At 2026-10-06T12:00Z the status asset-sim derives at the
                # forwarded instant is warning; at 00:00Z only the alert raised by then is listed (ruling 9).
                await harness.execute(MOVE, ("2026-10-06T12:00:00Z",))
                inside = await tool(url, token, handle, Tool.GET_ASSET_STATUS, {"asset_id": "A17"})
                assert (inside["data"]["state"], inside["data"]["revision"]) == ("warning", 2)
                assert inside["observed_at"].startswith("2026-10-06T12:00")  # as_of, not the wall clock
                await harness.execute(MOVE, ("2026-10-06T00:00:00Z",))
                early = await tool(
                    url, token, handle, Tool.GET_RECENT_ALERTS, {"asset_id": "A17", **INTERVAL, "limit": 10}
                )
                assert [a["revision"] for a in early["data"]["alerts"]] == [1]  # seal-002 is still in the future
            finally:
                await harness.execute("UPDATE app.test_clock SET clock_offset = interval '0'")
        lines.append("asset tools: A17 normal r2 now, warning r2 at 2026-10-06T12:00Z; alerts paged 1+1 by cursor")
    finally:
        await purge_run(app_conn, run)


async def test_r028_alpha_never_reads_b22(
    app_conn: persistence.Conn, role_conn: RoleConn, secret: Callable[[str], str], lines: list[str]
) -> None:
    api = await role_conn(Role.API)
    _, _, a17_run = await new_run(app_conn, ALPHA, api=api, interval=SEAL_WINDOW)
    _, _, b22_run = await new_run(app_conn, ALPHA, api=api, asset_id="B22", interval=SEAL_WINDOW)
    token = await worker_token(secret)
    try:
        async with serving() as url:
            a17 = await handle_for(app_conn, role_conn, a17_run, "t16-a17")
            named = await tool(url, token, a17, Tool.GET_ASSET_STATUS, {"asset_id": "B22"})
            widened = {"asset_id": "A17", "start_at": "2026-10-01T00:00:00Z", "end_at": "2026-10-07T00:00:00Z"}
            wider = await tool(url, token, a17, Tool.GET_RECENT_ALERTS, {**widened, "limit": 5})
            # Admission ties no asset to its tenant (fact sheet 3.4): this alpha run itself names beta's B22, so
            # mcp-read forwards it, and asset-sim's own tenant filter answers as for an unknown asset.
            b22 = await handle_for(app_conn, role_conn, b22_run, "t16-b22")
            status = await tool(url, token, b22, Tool.GET_ASSET_STATUS, {"asset_id": "B22"})
            alerts = await tool(url, token, b22, Tool.GET_RECENT_ALERTS, {"asset_id": "B22", **INTERVAL, "limit": 5})
        codes = [doc["error"]["code"] for doc in (named, wider, status, alerts)]
        assert codes == ["ASSET_OUT_OF_SCOPE", "INTERVAL_OUT_OF_SCOPE", "NOT_FOUND", "NOT_FOUND"]
        assert all(doc["data"] is None for doc in (named, wider, status, alerts))  # no beta data reached the caller
        lines.append(f"R028: alpha -> B22 {codes}")
    finally:
        await purge_run(app_conn, a17_run)
        await purge_run(app_conn, b22_run)


async def test_r028_a_requester_who_lost_the_membership_gets_no_asset_data(
    app_conn: persistence.Conn, role_conn: RoleConn, secret: Callable[[str], str], lines: list[str]
) -> None:
    _, _, run = await new_run(app_conn, ALPHA, api=await role_conn(Role.API), interval=SEAL_WINDOW)
    token = await worker_token(secret)
    calls = (
        (Tool.GET_ASSET_STATUS, {"asset_id": "A17"}),
        (Tool.GET_RECENT_ALERTS, {"asset_id": "A17", **INTERVAL, "limit": 5}),
    )
    try:
        async with serving() as url:
            handle = await handle_for(app_conn, role_conn, run, "t16-member")
            assert all([(await tool(url, token, handle, n, a))["status"] == "ok" for n, a in calls])
            try:
                await app_conn.execute(
                    "UPDATE app.memberships SET active = false WHERE tenant_id = %s AND subject = %s", (ALPHA, ALEX)
                )
                refused = [await tool(url, token, handle, n, a) for n, a in calls]
            finally:
                await app_conn.execute(
                    "UPDATE app.memberships SET active = true WHERE tenant_id = %s AND subject = %s", (ALPHA, ALEX)
                )
            assert all([(await tool(url, token, handle, n, a))["status"] == "ok" for n, a in calls])
        assert [doc["error"] for doc in refused] == [
            {"code": "INVALID_HANDLE", "message": "invocation handle rejected", "retryable": False}
        ] * 2  # the one plain refusal: nothing tells the caller it was the membership (SA:355)
        lines.append("R028 membership: both asset tools INVALID_HANDLE while alex was inactive; ok before and after")
    finally:
        await purge_run(app_conn, run)


async def test_asset_sim_failures_reach_the_caller_as_their_envelopes(
    app_conn: persistence.Conn, role_conn: RoleConn, secret: Callable[[str], str], asset_sim: str, lines: list[str]
) -> None:
    _, _, run = await new_run(app_conn, ALPHA, api=await role_conn(Role.API), interval=SEAL_WINDOW)
    token = await worker_token(secret)
    mcp_read_token = await WorkloadTokenSource(
        token_url=settings.keycloak().token_url,
        client_id="ops-mcp-read",
        client_secret=secret("kc_client_secret_ops_mcp_read"),
    ).token()

    async def arm(kind: str, **body: int) -> None:
        async with httpx2.AsyncClient(base_url=asset_sim) as http:
            answer = await http.post(
                f"/internal/faults/{kind}",
                headers={"Authorization": f"Bearer {mcp_read_token}"},
                json={"count": 1, **body},
            )
        assert answer.status_code == 200, kind

    try:
        async with serving() as url:
            handle = await handle_for(app_conn, role_conn, run, "t16-faults")
            seen = {}
            for kind, body in (
                ("asset_unavailable", {}),
                ("drop_before_commit", {}),
                ("malformed_response", {}),
                ("timeout_before_accept", {"seconds": 11}),  # mcp-read gives up after 10 s (ruling 15)
            ):
                await arm(kind, **body)
                doc = await tool(url, token, handle, Tool.GET_ASSET_STATUS, {"asset_id": "A17"})
                seen[kind] = (doc["data"] or {}).get("state") or (doc["error"]["code"], doc["error"]["retryable"])
        assert seen == {
            "asset_unavailable": "unavailable",  # the contract's third state, an ok answer
            "drop_before_commit": ("UNAVAILABLE", True),
            "malformed_response": ("UPSTREAM_INVALID", False),
            "timeout_before_accept": ("UNAVAILABLE", True),
        }
        lines.append(f"asset-sim faults through mcp-read: {seen}")
    finally:
        await purge_run(app_conn, run)
```

Run: `uv run ruff format tests/e2e && uv run ruff check --fix tests/e2e`, then `PYTHONUTF8=1 uv run python
scripts/check.py` → `CHECK: GREEN`, pytest `1324 passed, 203 skipped`; `uv run python -I scripts/verify_handoff.py
--reference-code --manifest --contracts` → exit 0; `PYTHONUTF8=1 uv run python scripts/check.py --profile test` →
`CHECK: GREEN`, pytest `1506 passed, 21 skipped` (arithmetic), then the `git checkout -- reports/...` of the Global
Constraints (keep `reports/mcp-read/t16-read-tools.txt` and `reports/asset-sim/`). The slow-answer case of
`test_asset_sim_failures_reach_the_caller_as_their_envelopes` takes about 11 seconds by design (mcp-read's 10-second
timeout).

- [ ] **Step 5: Commit**

```bash
git add core/pyproject.toml pyproject.toml uv.lock core/src/ops_core/tool_contracts.py mcp-read/src/ops_mcp_read \
  tests/plan_m/test_tool_contracts.py tests/plan_m/test_mcp_read_assets.py tests/plan_d/test_mcp_read.py \
  tests/plan_j/test_mcp_read_http.py tests/plan_j/test_mcp_read_startup.py tests/plan_l/test_mcp_read_corpus.py \
  tests/e2e/test_mcp_read_t15_live.py tests/e2e/test_mcp_read_process_live.py tests/e2e/test_mcp_read_t16_live.py
git commit -m "feat(mcp-read): get_asset_status and get_recent_alerts through asset_scope and asset-sim (T16)"
```

### Task 4: `search_procedures` on the run's asset type; vector mode stays with T18

**Files:**
- Create: `tests/plan_m/test_mcp_read_search.py`
- Modify: `mcp-read/src/ops_mcp_read/server.py` (the docstring, the search), `core/src/ops_core/routing.py` and
  `scripts/build_schemas.py` (`TODO(T18)`), `tests/plan_l/test_mcp_read_corpus.py` (whole file),
  `tests/e2e/test_mcp_read_t15_live.py`, `tests/e2e/test_mcp_read_process_live.py` (`pytestmark`),
  `tests/e2e/test_mcp_read_live.py` (`pytestmark`, the implicit type and the Z99 control),
  `tests/e2e/test_mcp_read_t16_live.py` (the search and all three tools under a lost membership)

**Requirements:** ruling 12 (the run's asset type), ruling 14 (the order kept), ruling 1 (`TODO(T18)`, erratum 103),
ruling 7's live "all three tools refuse", R028's "revoked procedure" half, BS:417.

**Interfaces:**
- Consumes: `server.resolve`, `scope_of`, `unconfigured` (Task 3); `assets.AssetSim.asset_type`, `AssetSimError`;
  `persistence.search_procedures`.
- Produces: the search's three units (departure 1) and its codes `ASSET_TYPE_OUT_OF_SCOPE`, `UNAVAILABLE` (retryable),
  `UPSTREAM_INVALID`; `tests.plan_l.test_mcp_read_corpus.SCOPE`, `RunType`, `Database.asset_scope`, and `call(...,
  assets=None)`.

- [ ] **Step 1: Write the failing tests**

Replace `tests/plan_l/test_mcp_read_corpus.py` whole with (three units now; the run's type; a refusal at the scope
unit; `test_no_asset_type_means_any_asset` becomes `test_the_runs_asset_type_is_searched_and_an_unknown_asset_leaves_the_callers`,
because an absent caller type now means the run's):

```python
"""mcp-read's `search_procedures` over its HTTP stack in-process, with the three database calls and asset-sim replaced
(Plan L rulings 1, 2, 11 and 21; Plan M rulings 12 and 14; erratum 80).

Catches: a search run before the handle resolved and the run's scope was read, or in the same unit as either; a search
that is not given the presented handle and the token's `azp` (the definer must decide the tenant from them, never
from an argument); the run's asset type not passed, or an unknown asset's absence turned into a filter;
`vector_exact` reaching the scope or the database before T18; a handle refused at any unit answered with anything but
the one plain `INVALID_HANDLE`; and a definer refusal escaping as a transport error instead of an envelope.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_types import CallToolResult
from ops_core import persistence
from ops_core.jobs import Tool
from ops_mcp_read import server

from tests.plan_j.test_mcp_read_http import BASE, ISSUER, RESOURCE, KeyedVerifier

pytestmark = pytest.mark.asyncio

HANDLE = "unit-test-handle"
HIT = persistence.Procedure(
    evidence_id="ALPHA-PUMP-SEAL:v2:inspection",
    document_id="ALPHA-PUMP-SEAL",
    version="2",
    section="inspection",
    content_sha256="a" * 64,
    excerpt="Inspect the mechanical seal of pump A17 every 14 days.",
    effective_from=datetime(2026, 10, 1, tzinfo=UTC),
    rank=0.4,
)
SCOPE = persistence.AssetScope(
    run_id=UUID(int=7),
    tenant_id=UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7"),
    asset_id="A17",
    start_at=datetime(2026, 10, 15, 12, tzinfo=UTC),
    end_at=datetime(2026, 10, 16, 12, tzinfo=UTC),
    as_of=datetime(2026, 10, 16, 12, tzinfo=UTC),
)


class UnitConn:
    """Stands in for the connection: counts the units `Session.unit` opens."""

    def __init__(self) -> None:
        self.units = 0

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        self.units += 1
        yield

    async def close(self) -> None:
        return None


class Database:
    """The three persistence calls the tool makes, recorded in order with the unit each ran in."""

    def __init__(
        self,
        conn: UnitConn,
        *,
        resolve: Exception | None = None,
        scope: Exception | None = None,
        search: Exception | None = None,
    ) -> None:
        self.conn, self.resolve_error, self.scope_error, self.search_error = conn, resolve, scope, search
        self.calls: list[tuple[str, int, dict[str, Any]]] = []

    async def resolve_invocation(self, conn: Any, **kwargs: Any) -> None:
        self.calls.append(("resolve", self.conn.units, kwargs))
        if self.resolve_error is not None:
            raise self.resolve_error

    async def asset_scope(self, conn: Any, **kwargs: Any) -> persistence.AssetScope:
        self.calls.append(("scope", self.conn.units, kwargs))
        if self.scope_error is not None:
            raise self.scope_error
        return SCOPE

    async def search_procedures(self, conn: Any, **kwargs: Any) -> persistence.Procedures:
        self.calls.append(("search", self.conn.units, kwargs))
        if self.search_error is not None:
            raise self.search_error
        return persistence.Procedures("corpus-1", (HIT,), datetime(2026, 10, 16, 12, 0, tzinfo=UTC))


class RunType:
    """asset-sim's answer for the run's asset: its type, None for an asset asset-sim does not know, or a failure."""

    def __init__(self, answer: str | None | Exception) -> None:
        self.answer = answer
        self.asked: list[persistence.AssetScope] = []

    async def asset_type(self, scope: persistence.AssetScope) -> str | None:
        self.asked.append(scope)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer

    async def status(self, scope: persistence.AssetScope) -> dict[str, Any]:
        raise AssertionError("the search asks for no status")

    async def alerts(self, scope: persistence.AssetScope, *, limit: int, cursor: str | None) -> dict[str, Any]:
        raise AssertionError("the search asks for no alerts")

    async def aclose(self) -> None:
        return None


async def call(
    monkeypatch: pytest.MonkeyPatch, db: Database, arguments: dict[str, Any], assets: RunType | None = None
) -> CallToolResult:
    monkeypatch.setattr(persistence, "resolve_invocation", db.resolve_invocation)
    monkeypatch.setattr(persistence, "asset_scope", db.asset_scope)
    monkeypatch.setattr(persistence, "search_procedures", db.search_procedures)
    state = server.State(session=None, verifier=KeyedVerifier())
    fake: Any = db.conn
    state.session = persistence.Session(fake)  # already set, so the lifespan opens no connection
    state.assets = assets or RunType("pump")  # A17 is a pump (data/corpus/assets.json)
    app = server.build_app(server.build_server(state, issuer=ISSUER, resource_url=RESOURCE), state)
    headers = {"Authorization": "Bearer good", "X-Ops-Invocation": HANDLE}
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with (
            httpx2.AsyncClient(transport=transport, base_url=BASE, headers=headers) as http,
            Client(streamable_http_client(f"{BASE}/mcp", http_client=http), mode="2026-07-28") as client,
        ):
            return await client.call_tool("search_procedures", arguments)


async def test_the_handle_resolves_in_its_own_unit_then_the_definer_searches(monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database(UnitConn())
    result = await call(monkeypatch, db, {"query": "seal", "limit": 3, "mode": "lexical", "asset_type": "pump"})
    assert [(name, unit) for name, unit, _ in db.calls] == [("resolve", 1), ("scope", 2), ("search", 3)]
    assert db.calls[0][2] == {"handle": HANDLE, "azp": "ops-worker", "tool": Tool.SEARCH_PROCEDURES}
    assert db.calls[1][2] == {"handle": HANDLE, "azp": "ops-worker"}
    assert db.calls[2][2] == {"handle": HANDLE, "azp": "ops-worker", "query": "seal", "asset_type": "pump", "limit": 3}
    doc = result.structured_content
    assert not result.is_error and isinstance(doc, dict) and doc["status"] == "ok"
    assert doc["data"]["corpus_version"] == "corpus-1"
    assert [r["evidence_id"] for r in doc["data"]["results"]] == ["ALPHA-PUMP-SEAL:v2:inspection"]
    assert "rank" not in doc["data"]["results"][0]


async def test_the_runs_asset_type_is_searched_and_an_unknown_asset_leaves_the_callers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plan M ruling 12: the run's type when asset-sim knows the asset; otherwise the caller's type, or any asset."""
    searched = []
    for answer, arguments in (
        ("pump", {}),
        (None, {}),
        (None, {"asset_type": "valve"}),
    ):
        db = Database(UnitConn())
        await call(monkeypatch, db, {"query": "seal", "limit": 3, "mode": "lexical", **arguments}, RunType(answer))
        searched.append(db.calls[2][2]["asset_type"])
    assert searched == ["pump", None, "valve"]


async def test_vector_exact_is_refused_after_resolution_and_before_any_search(monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database(UnitConn())
    result = await call(monkeypatch, db, {"query": "seal", "limit": 3, "mode": "vector_exact"})
    assert [name for name, _, _ in db.calls] == ["resolve"]
    assert result.structured_content is not None
    assert result.structured_content["error"]["code"] == "UNSUPPORTED_MODE"


@pytest.mark.parametrize("where", ["resolve", "scope", "search"])
async def test_a_refused_handle_is_the_one_plain_refusal(monkeypatch: pytest.MonkeyPatch, where: str) -> None:
    rejected = persistence.HandleRejected("invocation handle rejected")
    db = Database(UnitConn(), **{where: rejected})
    result = await call(monkeypatch, db, {"query": "seal", "limit": 3, "mode": "lexical"})
    order = ["resolve", "scope", "search"]
    assert [name for name, _, _ in db.calls] == order[: order.index(where) + 1]
    doc = result.structured_content
    assert not result.is_error and isinstance(doc, dict) and doc["data"] is None
    assert doc["error"] == {"code": "INVALID_HANDLE", "message": "invocation handle rejected", "retryable": False}


async def test_a_definer_refusal_is_an_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database(UnitConn(), search=persistence.Refused("BAD_ARGUMENT"))
    result = await call(monkeypatch, db, {"query": "seal", "limit": 3, "mode": "lexical"})
    assert result.structured_content is not None
    assert result.structured_content["error"] == {"code": "REFUSED", "message": "BAD_ARGUMENT", "retryable": False}
```

Create `tests/plan_m/test_mcp_read_search.py`:

```python
"""`search_procedures` on the run's own asset type (Plan M rulings 3, 12 and 15), in-process, the database calls and
asset-sim replaced.

Catches: a caller's asset type that differs from the run's searched instead of refused, or refused only after the
definer ran; an unreachable asset-sim that lets the search run without the run's type (it must fail closed); the
real client asking asset-sim for anything but the run's asset with mcp-read's own token, or passing on an answer that
names another asset; and a search answer whose `observed_at` is the wall clock rather than the definer's instant.
"""

import httpx2
import pytest
from ops_core import persistence
from ops_mcp_read import assets

from tests.plan_l.test_mcp_read_corpus import SCOPE, Database, RunType, UnitConn, call
from tests.plan_m.test_mcp_read_assets import Tokens

pytestmark = pytest.mark.asyncio

QUERY = {"query": "seal", "limit": 3, "mode": "lexical"}


async def test_a_caller_type_that_is_not_the_runs_is_refused_before_the_definer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = Database(UnitConn())
    refused = await call(monkeypatch, db, {**QUERY, "asset_type": "compressor"}, RunType("pump"))
    assert [name for name, _, _ in db.calls] == ["resolve", "scope"]  # the definer never ran
    doc = refused.structured_content
    assert doc is not None and doc["error"]["code"] == "ASSET_TYPE_OUT_OF_SCOPE" and doc["data"] is None
    same = Database(UnitConn())
    await call(monkeypatch, same, {**QUERY, "asset_type": "pump"}, RunType("pump"))  # repeating it is allowed
    assert same.calls[2][2]["asset_type"] == "pump"


async def test_an_unreachable_asset_sim_fails_the_search_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database(UnitConn())
    result = await call(monkeypatch, db, QUERY, RunType(assets.Unavailable("asset-sim could not be reached")))
    assert [name for name, _, _ in db.calls] == ["resolve", "scope"]
    doc = result.structured_content
    assert doc is not None and doc["error"] == {
        "code": "UNAVAILABLE",
        "message": "asset-sim could not be reached",
        "retryable": True,
    }


async def test_the_answer_is_stamped_with_the_definers_instant(monkeypatch: pytest.MonkeyPatch) -> None:
    result = await call(monkeypatch, Database(UnitConn()), QUERY)
    doc = result.structured_content
    assert doc is not None and doc["status"] == "ok"
    assert doc["observed_at"] == doc["data"]["results"][0]["retrieved_at"] == "2026-10-16T12:00:00Z"


async def test_the_real_client_asks_for_the_runs_asset_with_its_own_token() -> None:
    seen: list[httpx2.Request] = []
    answers = iter(
        [
            httpx2.Response(200, json={"asset_id": "A17", "asset_type": "pump"}),
            httpx2.Response(404, json={"code": "NOT_FOUND"}),
            httpx2.Response(200, json={"asset_id": "B22", "asset_type": "pump"}),  # another asset's answer
        ]
    )

    def answer(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return next(answers)

    client = assets.HttpAssetSim("http://asset-sim.test", Tokens(), transport=httpx2.MockTransport(answer))
    try:
        assert await client.asset_type(SCOPE) == "pump"
        assert await client.asset_type(SCOPE) is None  # unknown to asset-sim: the caller's type or none
        with pytest.raises(assets.UpstreamInvalid):
            await client.asset_type(SCOPE)
        odd = persistence.AssetScope(**{**SCOPE.__dict__, "asset_id": "../internal/faults/x"})
        assert await client.asset_type(odd) is None  # a run's asset text that is no asset id is never sent
    finally:
        await client.aclose()
    assert [r.url.path for r in seen] == ["/assets/A17"] * 3
    assert {r.headers["authorization"] for r in seen} == {"Bearer mcp-read-token"}
    assert {r.headers["x-ops-as-of"] for r in seen} == {"2026-10-16T12:00:00Z"}
```

Run: `uv run python -m pytest tests/plan_l/test_mcp_read_corpus.py tests/plan_m/test_mcp_read_search.py -q`
Expected: `6 failed, 5 passed` (measured): the units test, the run-type test, the `scope` and `search` cases of the
refusal test and the two new refusal tests fail, because the search reads neither the scope nor the run's type yet;
the vector test, the `resolve` case, the definer-refusal test, the instant test and the real client's test pass.

- [ ] **Step 2: The run's asset type**

Edit 1 (`mcp-read/src/ops_mcp_read/server.py`, the module docstring), replace:

```python
- `search_procedures` answers from the governed corpus through `search_procedures_scoped` (T17); mcp-read reads no
  file.
"""
```

with:

```python
- `search_procedures` answers from the governed corpus through `search_procedures_scoped` (T17); mcp-read reads no
  file. It reads the run's scope the same way and asks asset-sim for the run's asset type, which it passes to the
  definer: a caller's `asset_type` may only repeat it (`ASSET_TYPE_OUT_OF_SCOPE`, ruling 12).
"""
```

Edit 2 (`mcp-read/src/ops_mcp_read/server.py`, the search), replace:

```python
        """Lexical search over the calling run's tenant's approved, effective procedure sections (AM-15 read tool),
        through `search_procedures_scoped` (T17)."""
        name = ToolName.SEARCH_PROCEDURES
        caller = await resolve(name, ctx)
        if not isinstance(caller, Caller):
            return caller
        if mode != "lexical":
            # TODO(T16): translate vector_exact to mode=vector once T18 stores embeddings (erratum 3).
            return envelope(name.value, error=tool_error("UNSUPPORTED_MODE", "vector_exact arrives with T18"))
        assert state.session is not None  # resolve() answered only with a session
        # A second unit, after the resolution committed (erratum 80): the definer resolves the same handle again, so a
        # handle released in between is refused here too, and the tenant comes from the handle, never an argument.
        try:
            async with state.session.unit() as conn:
                found = await persistence.search_procedures(
                    conn,
                    handle=caller.handle,
                    azp=caller.azp,
                    query=query,
                    asset_type=asset_type or None,
                    limit=limit,
                )
```

with:

```python
        """Lexical search over the calling run's tenant's approved, effective procedure sections of the run's asset
        type (AM-15 read tool), through `search_procedures_scoped` (T17, T16)."""
        name = ToolName.SEARCH_PROCEDURES
        caller = await resolve(name, ctx)
        if not isinstance(caller, Caller):
            return caller
        if mode != "lexical":
            # The handle first, then the mode: an invalid handle never learns what the server supports (ruling 14).
            # TODO(T18): translate vector_exact to mode=vector and compute the nomic `search_query:` embedding once
            # T18 stores embeddings (erratum 3; Plan M ruling 1, erratum 103).
            return envelope(name.value, error=tool_error("UNSUPPORTED_MODE", "vector_exact arrives with T18"))
        scope = await scope_of(name, caller)
        if not isinstance(scope, persistence.AssetScope):
            return scope
        if state.assets is None:
            return unconfigured(name, scope)
        # The run's asset type is a relevance filter, not an access boundary: the tenant filter is the definer's. An
        # asset asset-sim does not know leaves the caller's type or none; asset-sim unreachable fails closed.
        try:
            run_type = await state.assets.asset_type(scope)
        except assets.AssetSimError as exc:
            error = tool_error(exc.code, str(exc), retryable=exc.retryable)
            return envelope(name.value, error=error, observed_at=scope.as_of)
        if asset_type and run_type is not None and asset_type != run_type:
            error = tool_error("ASSET_TYPE_OUT_OF_SCOPE", "only the run's own asset type may be searched")
            return envelope(name.value, error=error, observed_at=scope.as_of)
        assert state.session is not None  # resolve() answered only with a session
        # A third unit (erratum 80): the definer resolves the same handle again, so a handle released in between is
        # refused here too, and the tenant comes from the handle, never an argument.
        try:
            async with state.session.unit() as conn:
                found = await persistence.search_procedures(
                    conn,
                    handle=caller.handle,
                    azp=caller.azp,
                    query=query,
                    asset_type=run_type or asset_type or None,
                    limit=limit,
                )
```

Edit 3 (`core/src/ops_core/routing.py`, `RunManifest.retrieval_mode`), replace:

```python
    # TODO(T16): mcp-read, the caller of `search_procedures_scoped` (T17), translates `vector_exact` to `mode=vector`.
```

with:

```python
    # TODO(T18): mcp-read, the caller of `search_procedures_scoped`, translates `vector_exact` to `mode=vector`
    # (Plan M ruling 1: the translation arrives with T18's embeddings, erratum 103).
```

Edit 4 (`scripts/build_schemas.py`, the search input's `mode`; a comment only, the generated schemas do not change),
replace:

```python
                "mode": {"enum": ["lexical", "vector_exact"]},  # ruling 3; mcp-read maps vector_exact (TODO(T16))
```

with:

```python
                "mode": {"enum": ["lexical", "vector_exact"]},  # ruling 3; mcp-read maps vector_exact (TODO(T18))
```

Run: `uv run ruff format mcp-read core scripts tests && uv run ruff check --fix mcp-read core scripts tests`, then
`uv run python -m pytest tests/plan_l tests/plan_m -q` → every test passes (`test_mcp_read_corpus.py` 7,
`test_mcp_read_search.py` 4). `grep -rn "TODO(T16)" --include=*.py core mcp-read worker api scripts migrations` →
no output.

- [ ] **Step 3: asset-sim behind every live search**

Edit 1 (`tests/e2e/test_mcp_read_t15_live.py`), replace:

```python
pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("ingested")]
```

with:

```python
# T17: the governed corpus; T16: asset-sim, which the search asks for the run's asset type.
pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("ingested", "asset_sim")]
```

Edit 2 (`tests/e2e/test_mcp_read_process_live.py`), replace:

```python
pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("ingested")]  # T17: the governed corpus
```

with:

```python
# T17: the governed corpus; T16: asset-sim, whose URL the child inherits (`asset_sim` exports OPS_ASSET_SIM_URL).
pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("ingested", "asset_sim")]
```

Edit 3 (`tests/e2e/test_mcp_read_live.py`, the docstring's end), replace:

```python
that is not the section's), an asset type that does not filter, `vector_exact` answered before T18, and the two
rejections the e2e test relies on (persona token; mcp-write's token)."""
```

with:

```python
that is not the section's), an asset type that does not filter, the run's own asset type (T16: A17 is a pump) not
applied when the caller names none, `vector_exact` answered before T18, and the two rejections the e2e test relies on
(persona token; mcp-write's token)."""
```

Edit 4 (`tests/e2e/test_mcp_read_live.py`), replace:

```python
pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("ingested")]  # T17: the governed corpus
```

with:

```python
# T17: the governed corpus; T16: asset-sim, which the search asks for the run's asset type.
pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("ingested", "asset_sim")]
```

Edit 5 (`tests/e2e/test_mcp_read_live.py`), replace:

```python
    run = None
    try:
```

with:

```python
    run = open_run = None
    try:
```

Edit 6 (`tests/e2e/test_mcp_read_live.py`, a second run whose asset asset-sim does not know), replace:

```python
        worker = WorkloadTokenSource(
            token_url=kcs.token_url, client_id="ops-worker", client_secret=secret("kc_client_secret_ops_worker")
        )
```

with:

```python
        # A run whose asset asset-sim does not know (Z99): no run asset type applies, so its search is the control
        # that reaches every asset's documents (Plan M ruling 12).
        _, _, open_run = await new_run(app_conn, ALPHA, api=await role_conn(Role.API), asset_id="Z99")
        cur = await app_conn.execute("SELECT id FROM app.jobs WHERE run_id = %s", (open_run,))
        open_job = (await cur.fetchone())["id"]
        open_lease = await lease_for(worker_conn, open_run)
        async with worker_conn.transaction():
            await persistence.set_tenant(worker_conn, ALPHA)
            open_handle = await persistence.mint_handle(
                worker_conn,
                run_id=open_run,
                job_id=open_job,
                server=Server.READ,
                azp="ops-worker",
                fence=open_lease.fence,
            )
        worker = WorkloadTokenSource(
            token_url=kcs.token_url, client_id="ops-worker", client_secret=secret("kc_client_secret_ops_worker")
        )
```

Edit 7 (`tests/e2e/test_mcp_read_live.py`, the calls), replace:

```python
            everything = await client.call_tool(
                "search_procedures", {"query": "the reviewer records each reading", "limit": 8, "mode": "lexical"}
            )
            vector = await client.call_tool("search_procedures", {"query": "seal", "limit": 1, "mode": "vector_exact"})
```

with:

```python
            implicit = await client.call_tool(
                "search_procedures", {"query": "the reviewer records each reading", "limit": 8, "mode": "lexical"}
            )
            vector = await client.call_tool("search_procedures", {"query": "seal", "limit": 1, "mode": "vector_exact"})
        async with (
            httpx2.AsyncClient(headers={**headers, "X-Ops-Invocation": open_handle}) as hc,
            Client(streamable_http_client(url, http_client=hc), mode="2026-07-28") as client,
        ):
            everything = await client.call_tool(
                "search_procedures", {"query": "the reviewer records each reading", "limit": 8, "mode": "lexical"}
            )
```

Edit 8 (`tests/e2e/test_mcp_read_live.py`, the assertions), replace:

```python
        assert documents and documents <= {"ALPHA-PUMP-SEAL", "ALPHA-ALERT-REVIEW"}  # pump documents or any-asset ones
        # The control: the same query with no asset type reaches other assets' documents, so a filter that was dropped
        # (or an empty asset type forwarded as "any") would fail the line above.
```

with:

```python
        assert documents and documents <= {"ALPHA-PUMP-SEAL", "ALPHA-ALERT-REVIEW"}  # pump documents or any-asset ones
        # No asset type named: the run's own (A17, a pump) applies all the same (Plan M ruling 12).
        assert {r["document_id"] for r in implicit.structured_content["data"]["results"]} == documents
        # The control: the same query for a run asset-sim knows no type of reaches other assets' documents, so a
        # filter that was dropped (or an empty asset type forwarded as "any") would fail the lines above.
```

Edit 9 (`tests/e2e/test_mcp_read_live.py`, the purge), replace:

```python
        if run is not None:
            await purge_run(app_conn, run)
```

with:

```python
        for made in (run, open_run):
            if made is not None:
                await purge_run(app_conn, made)
```

Edit 10 (`tests/e2e/test_mcp_read_t16_live.py`; the next five edits make Task 3's file Task 4's), replace:

```python
(asset-sim's own tenant filter: NOT_FOUND); another interval served; a requester who lost the membership still served
by the asset tools; and an asset-sim failure (unavailable, malformed, slow) that is not the documented envelope.
```

with:

```python
(asset-sim's own tenant filter: NOT_FOUND); another interval served; a search that leaves the run's asset type or
returns a revoked procedure; a requester who lost the membership still served by any of the three tools; and an
asset-sim failure (unavailable, malformed, slow) that is not the documented envelope.
```

Edit 11 (the same file), replace:

```python
EXPECTED_LINES = 4  # one per test below
```

with:

```python
EXPECTED_LINES = 5  # one per test below
```

Edit 12 (the same file, the membership test's calls), replace:

```python
        (Tool.GET_RECENT_ALERTS, {"asset_id": "A17", **INTERVAL, "limit": 5}),
    )
```

with:

```python
        (Tool.GET_RECENT_ALERTS, {"asset_id": "A17", **INTERVAL, "limit": 5}),
        (Tool.SEARCH_PROCEDURES, {"query": "seal inspection", "limit": 3, "mode": "lexical"}),
    )
```

Edit 13 (the same file, its assertion), replace:

```python
        ] * 2  # the one plain refusal: nothing tells the caller it was the membership (SA:355)
        lines.append("R028 membership: both asset tools INVALID_HANDLE while alex was inactive; ok before and after")
```

with:

```python
        ] * 3  # the one plain refusal: nothing tells the caller it was the membership (SA:355)
        lines.append("R028 membership: all three tools INVALID_HANDLE while alex was inactive; ok before and after")
```

Edit 14 (the same file, a new test before the faults test), replace:

```python
async def test_asset_sim_failures_reach_the_caller_as_their_envelopes(
```

with:

```python
async def test_r028_the_search_keeps_to_the_runs_asset_type_and_never_returns_a_revoked_procedure(
    app_conn: persistence.Conn, role_conn: RoleConn, secret: Callable[[str], str], lines: list[str]
) -> None:
    _, _, run = await new_run(app_conn, ALPHA, api=await role_conn(Role.API))
    token = await worker_token(secret)
    query = {"query": "alarm bypass seal inspection", "limit": 8, "mode": "lexical"}
    try:
        async with serving() as url:
            handle = await handle_for(app_conn, role_conn, run, "t16-search")
            own = await tool(url, token, handle, Tool.SEARCH_PROCEDURES, query)
            other = await tool(url, token, handle, Tool.SEARCH_PROCEDURES, {**query, "asset_type": "compressor"})
        documents = {r["document_id"] for r in own["data"]["results"]}
        # A17 is a pump: pump documents or any-asset ones only; ALPHA-ALARM-BYPASS (a pump document) is revoked.
        assert documents and documents <= {"ALPHA-PUMP-SEAL", "ALPHA-ALERT-REVIEW"}
        assert all(r["retrieved_at"] == own["observed_at"] for r in own["data"]["results"])  # the definer's instant
        assert other["error"]["code"] == "ASSET_TYPE_OUT_OF_SCOPE" and other["data"] is None
        lines.append(f"R028 search: run type pump -> {sorted(documents)}; revoked bypass absent; compressor refused")
    finally:
        await purge_run(app_conn, run)


async def test_asset_sim_failures_reach_the_caller_as_their_envelopes(
```

Run: `uv run ruff format tests && uv run ruff check --fix tests`, then `PYTHONUTF8=1 uv run python scripts/check.py`
→ `CHECK: GREEN`, pytest `1329 passed, 204 skipped`; `uv run python -I scripts/verify_handoff.py --reference-code
--manifest --contracts` → exit 0; `PYTHONUTF8=1 uv run python scripts/check.py --profile test` → `CHECK: GREEN`,
pytest `1512 passed, 21 skipped` (arithmetic), then the `git checkout -- reports/...` of the Global Constraints.
The R105 module's run asks about A17, a pump: its search is filtered to pump and any-asset documents; if its
proposal has no evidence, read Review Focus 3 before touching the test.

- [ ] **Step 4: Commit**

```bash
git add mcp-read/src/ops_mcp_read/server.py core/src/ops_core/routing.py scripts/build_schemas.py \
  tests/plan_l/test_mcp_read_corpus.py tests/plan_m/test_mcp_read_search.py tests/e2e/test_mcp_read_t15_live.py \
  tests/e2e/test_mcp_read_process_live.py tests/e2e/test_mcp_read_live.py tests/e2e/test_mcp_read_t16_live.py
git commit -m "feat(mcp-read): search_procedures on the run's own asset type; vector mode stays with T18 (T16)"
```

### Task 5: R029 — the worker lists before it calls and validates what it reads

**Files:**
- Create: `tests/plan_m/test_worker_r029.py`
- Modify: `worker/src/ops_worker/mcp.py` (whole file), `tests/e2e/test_mcp_read_t16_live.py` (the R029 live case)

**Requirements:** R029 ("Alter discovered tool/schema; return error-flagged/malformed/oversized payload; no success
assumption"), BS:399, BS:589 (malformed results), T16 DoD 1's second half, ruling 13 (the worker's half; departures 5
and 6).

**Interfaces:**
- Consumes: `ops_core.tool_contracts.same_input_schema`, `check_result`, `MAX_RESULT_BYTES`, `ContractViolation`;
  `ops_core.jobs.JOB_RULES`, `JobType`, `Tool`; `mcp_types.CallToolResult`, `mcp_types.Tool`; mcp-read's real app
  (Task 3) over `httpx2.ASGITransport`; Plan H's worker fakes (`tests.plan_h.test_worker_units.Log`, `make`, `patch`,
  `JOB`).
- Produces: `ops_worker.mcp.READ_TOOLS`, `check_listing(advertised, tool)`, `read_result(tool, result)`,
  `HttpMcpCaller(token_source, *, connect_timeout=10.0, transport=None)`; a read call that fails a check raises
  `McpCallFailed`, which the investigate handler already records as FAILED "retrieval failed".

- [ ] **Step 1: Write the failing tests**

Create `tests/plan_m/test_worker_r029.py`:

```python
"""R029 at the worker (Plan M ruling 13): the real client against mcp-read's real HTTP stack in-process, with the
database calls and asset-sim replaced, and its checks on scripted answers.

Catches: a client that calls a tool without listing first, or calls it although the server lists a tool too many or
too few, or advertises an input schema other than the committed file; a result that is error-flagged, malformed,
another tool's, an error envelope or larger than 256 KiB taken as success; and an investigate run that does anything
but fail as "retrieval failed" when its read fails a check (no success assumption).
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx2
import pytest
from mcp_types import CallToolResult, TextContent
from ops_core import persistence
from ops_core.jobs import Tool
from ops_core.states import RunState
from ops_mcp_read import assets, server
from ops_worker import handlers
from ops_worker.mcp import HttpMcpCaller, McpCallFailed, read_result

from tests.plan_h.test_worker_units import JOB, Log, make, patch
from tests.plan_j.test_mcp_read_http import BASE, ISSUER, RESOURCE, KeyedVerifier
from tests.plan_l.test_mcp_read_corpus import UnitConn
from tests.plan_m.test_mcp_read_assets import STATUS, Database, Tokens

STATUS_CALL = {"asset_id": "A17"}


class Good:
    """The worker's token source, answering the token KeyedVerifier accepts."""

    async def token(self) -> str:
        return "good"


@asynccontextmanager
async def caller_against(
    monkeypatch: pytest.MonkeyPatch, db: Database, alter: Any = None
) -> AsyncIterator[HttpMcpCaller]:
    """The worker's real client, reaching mcp-read's real app in-process; `alter` changes the server first."""
    monkeypatch.setattr(persistence, "resolve_invocation", db.resolve_invocation)
    monkeypatch.setattr(persistence, "asset_scope", db.asset_scope)
    state = server.State(session=None, verifier=KeyedVerifier())
    fake: Any = db.conn
    state.session = persistence.Session(fake)
    state.assets = assets.HttpAssetSim(
        "http://asset-sim.test", Tokens(), transport=httpx2.MockTransport(lambda r: httpx2.Response(200, json=STATUS))
    )
    mcp = server.build_server(state, issuer=ISSUER, resource_url=RESOURCE)
    if alter is not None:
        alter(mcp)
    app = server.build_app(mcp, state)
    async with app.router.lifespan_context(app):
        yield HttpMcpCaller(Good(), transport=httpx2.ASGITransport(app=app))


@pytest.mark.asyncio
async def test_the_real_listing_and_a_valid_result_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database(UnitConn())
    async with caller_against(monkeypatch, db) as caller:
        doc = await caller.call(f"{BASE}/mcp", handle="h", tool="get_asset_status", arguments=STATUS_CALL)
    assert doc["status"] == "ok" and doc["data"] == STATUS
    assert [name for name, _, _ in db.calls] == ["resolve", "scope"]


def run_shell() -> str:
    """A tool no read server may offer (BS:395)."""
    return "never"


@pytest.mark.parametrize(
    ("alter", "why"),
    [
        (lambda mcp: mcp.add_tool(run_shell), "unexpected tool set"),  # a tool added
        (lambda mcp: mcp.remove_tool("get_recent_alerts"), "unexpected tool set"),  # a tool removed
        (  # the called tool's schema loosened: a longer asset id would be accepted
            lambda mcp: (
                mcp._tool_manager.get_tool("get_asset_status").parameters["properties"]["asset_id"].update(maxLength=64)
            ),
            "input schema is not the committed one",
        ),
    ],
)
@pytest.mark.asyncio
async def test_an_altered_listing_fails_closed_before_the_call(
    monkeypatch: pytest.MonkeyPatch, alter: Any, why: str
) -> None:
    db = Database(UnitConn())
    async with caller_against(monkeypatch, db, alter) as caller:
        with pytest.raises(McpCallFailed, match=why):
            await caller.call(f"{BASE}/mcp", handle="h", tool="get_asset_status", arguments=STATUS_CALL)
    assert db.calls == []  # the tool was never called


def result(doc: Any, *, is_error: bool = False, padding: int = 0) -> CallToolResult:
    content = [TextContent(type="text", text="x" * padding)] if padding else []
    return CallToolResult(content=content, structured_content=doc, is_error=is_error)


def status_doc(**data: Any) -> dict[str, Any]:
    return {
        "tool_name": "get_asset_status",
        "request_id": "00000000-0000-4000-8000-000000000000",
        "status": "ok",
        "observed_at": "2026-10-06T00:00:00Z",
        "truncated": False,
        "data": {**STATUS, **data},
        "error": None,
    }


REFUSED = {"code": "UNAVAILABLE", "message": "asset-sim could not be reached", "retryable": True}


@pytest.mark.parametrize(
    ("answer", "why"),
    [
        (result(status_doc(), is_error=True), "error-flagged"),
        (result(status_doc(state="on fire")), "fails the contract"),  # malformed nested data
        (result({**status_doc(), "tool_name": "search_procedures"}), "fails the contract"),  # another tool's
        (result([status_doc()]), "fails the contract"),  # not an object
        (result(None), "fails the contract"),  # no structured content at all
        (result({**status_doc(), "status": "error", "data": None, "error": REFUSED}), "rejected the call"),
        (result(status_doc(), padding=300 * 1024), "larger than the bound"),  # oversized
    ],
)
def test_a_result_that_is_not_a_valid_ok_answer_fails_closed(answer: CallToolResult, why: str) -> None:
    with pytest.raises(McpCallFailed, match=why):
        read_result(Tool.GET_ASSET_STATUS, answer)
    assert read_result(Tool.GET_ASSET_STATUS, result(status_doc()))["status"] == "ok"  # the valid shape passes


def test_a_failed_check_fails_the_run_as_retrieval_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The investigate handler records a read that failed a check like any other failed read: FAILED, "retrieval
    failed", and nothing drafted (ruling 13: no success assumption)."""
    log = Log()
    patch(monkeypatch, log)
    moves: list[tuple[Any, Any, Any]] = []

    async def transition_run(_conn: Any, *, run_id: Any, src: Any, dst: Any, detail: Any = None) -> int:
        moves.append((src, dst, detail))
        return 2

    class Refusing:
        async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
            raise McpCallFailed(f"{tool}: the server advertises an unexpected tool set")

    monkeypatch.setattr(persistence, "transition_run", transition_run)
    deps, lease = make(log)
    deps.mcp = Refusing()
    asyncio.run(handlers.investigate(deps, dict(JOB), lease))
    assert moves[-1] == (RunState.RETRIEVING, RunState.FAILED, {"message": "retrieval failed"})
    assert "freeze_proposal" not in log.entries and "take_model_permit" not in log.entries
```

Run: `uv run python -m pytest tests/plan_m/test_worker_r029.py -q`
Expected: `1 error` during collection (`ops_worker.mcp` has no `read_result`).

- [ ] **Step 2: The client's checks**

Replace `worker/src/ops_worker/mcp.py` whole with:

```python
"""The worker's MCP client: one workload token, two servers, one handle per call (BUILD_SPEC §9, ADR-0003).

The token and the handle travel as HTTP headers on an httpx2 client the SDK transport uses (measured in the spike);
the handle is never a tool argument. A refusal at the transport (401) reaches the caller as the SDK's MCPError, and a
tool-level refusal as an error envelope; both become McpCallFailed so a handler records nothing it did not observe.

A read tool is held to the committed contracts, not to what the server says about itself (R029, Plan M ruling 13):
in the same session, before the call, the server must advertise exactly the three read tools and the called tool's
committed input schema (`check_listing`); the answer must be at most 256 KiB, not error-flagged, a valid tool result
of that tool by `schemas/tool-result.schema.json` and `ok` (`read_result`). Anything else is McpCallFailed, which the
investigate handler records as FAILED "retrieval failed": nothing is assumed to have succeeded.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final, Protocol

import httpx2
from mcp import Client, MCPError
from mcp.client.streamable_http import streamable_http_client
from mcp_types import CallToolResult
from mcp_types import Tool as AdvertisedTool
from ops_core import tool_contracts
from ops_core.jobs import JOB_RULES, JobType, Tool
from ops_core.mcp_protocol import PROTOCOL_VERSION

# A read handle's tools (AM-15): what mcp-read must advertise, no more and no fewer.
READ_TOOLS: Final = JOB_RULES[JobType.INVESTIGATE].allowed_tools


class McpCallFailed(Exception):
    """The call did not produce a tool result: transport, protocol or tool-level refusal, or a failed check."""


def failure_leaf(exc: BaseException) -> BaseException:
    """The first leaf of a possibly nested exception group. An error that escapes the client's context manager
    (a refused token, a connection failure) arrives wrapped in anyio task-group `ExceptionGroup`s (measured in the
    Plan D spike and both dry runs); a handler must see the transport failure, not the wrapper, or the run is never
    failed and its conversation slot stays held."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


TRANSPORT_FAILURES = (MCPError, httpx2.HTTPError, OSError)


def check_listing(advertised: Sequence[AdvertisedTool], tool: Tool) -> None:
    """R029's discovery check: the server lists exactly the read tools, once each, and advertises the called tool's
    committed input schema (canonical JSON).

    Raises:
        McpCallFailed: a tool added, removed or listed twice, or the called tool's schema altered.
    """
    names = [entry.name for entry in advertised]
    if len(names) != len(set(names)) or set(names) != {read.value for read in READ_TOOLS}:
        raise McpCallFailed(f"{tool.value}: the server advertises an unexpected tool set")
    schema = next(entry.input_schema for entry in advertised if entry.name == tool.value)
    if not tool_contracts.same_input_schema(tool, schema):
        raise McpCallFailed(f"{tool.value}: the advertised input schema is not the committed one")


def read_result(tool: Tool, result: CallToolResult) -> dict[str, Any]:
    """R029's result check: the read tool's answer as a valid `ok` tool result.

    Raises:
        McpCallFailed: larger than 256 KiB serialized, error-flagged, not a valid result of this tool, or not `ok`.
    """
    # The SDK has parsed the body by the time it hands the result over (no hook stops it earlier), so the bound is
    # applied to the whole result as received, before anything of it is used.
    if len(result.model_dump_json(by_alias=True).encode("utf-8")) > tool_contracts.MAX_RESULT_BYTES:
        raise McpCallFailed(f"{tool.value}: the result is larger than the bound")
    if result.is_error:
        raise McpCallFailed(f"{tool.value}: the result is error-flagged")
    try:
        document = tool_contracts.check_result(tool, result.structured_content)
    except tool_contracts.ContractViolation as exc:
        raise McpCallFailed(f"{tool.value}: the result fails the contract") from exc
    if document["status"] != "ok":
        raise McpCallFailed(f"{tool.value}: the server rejected the call")
    return document


class TokenSource(Protocol):
    """Where the caller gets its workload token, so tests and the real client share one seam."""

    async def token(self) -> str:
        """Return a bearer token valid now."""
        ...


class McpCaller(Protocol):
    """What a handler needs from an MCP client, so tests can script it without a transport."""

    async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call one tool on one server under one invocation handle and return its structured result."""
        ...


class HttpMcpCaller:
    """The real client: one fresh connection per call, token and handle sent as headers."""

    def __init__(
        self,
        token_source: TokenSource,
        *,
        connect_timeout: float = 10.0,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        """Hold the token source and the timeouts; connections are opened per call. `transport` lets unit tests reach
        an in-process server."""
        self._tokens = token_source
        self._timeout = httpx2.Timeout(connect_timeout, read=60.0)
        self._transport = transport

    async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call the tool over Streamable HTTP; every failure to obtain a valid tool result is McpCallFailed."""
        read = next((candidate for candidate in READ_TOOLS if candidate.value == tool), None)
        try:
            headers = {"Authorization": f"Bearer {await self._tokens.token()}", "X-Ops-Invocation": handle}
            async with (
                httpx2.AsyncClient(headers=headers, timeout=self._timeout, transport=self._transport) as http,
                Client(streamable_http_client(url, http_client=http), mode=PROTOCOL_VERSION) as client,
            ):
                if read is not None:  # discovery in the same session, before the call (ruling 13)
                    check_listing((await client.list_tools()).tools, read)
                result = await client.call_tool(tool, arguments)
        except McpCallFailed:
            raise
        except TRANSPORT_FAILURES as exc:
            raise McpCallFailed(f"{tool}: transport or protocol failure") from exc
        except BaseExceptionGroup as group:
            leaf = failure_leaf(group)
            if isinstance(leaf, McpCallFailed):  # a failed check inside the session: the client's task group wraps it
                raise leaf from None
            if isinstance(leaf, TRANSPORT_FAILURES):
                raise McpCallFailed(f"{tool}: transport or protocol failure") from leaf
            raise
        if read is not None:
            return read_result(read, result)
        # TODO(T20): the write tools (mcp-write) still get only T47's check: no discovery and no result-schema check.
        if result.is_error or not isinstance(result.structured_content, dict):
            raise McpCallFailed(f"{tool}: the server rejected the call")
        return result.structured_content
```

Run: `uv run ruff format worker tests/plan_m && uv run ruff check --fix worker tests/plan_m`, then
`uv run python -m pytest tests/plan_m/test_worker_r029.py tests/plan_d/test_worker.py tests/plan_h/test_worker_units.py -q`
→ every test passes (`test_worker_r029.py` 12: the real listing, three altered listings, seven refused results and the
handler's FAILED "retrieval failed"; Plan D's transport test and Plan H's lost-lease test still pass, the list call
now being the first thing the session does).

- [ ] **Step 3: The live positive half**

Edit 1 (`tests/e2e/test_mcp_read_t16_live.py`, the docstring), replace:

```python
asset-sim failure (unavailable, malformed, slow) that is not the documented envelope.
```

with:

```python
asset-sim failure (unavailable, malformed, slow) that is not the documented envelope; and the worker's own client
(R029: discovery, then the committed schemas) refusing the real server.
```

Edit 2 (the same file), replace:

```python
EXPECTED_LINES = 5  # one per test below
```

with:

```python
EXPECTED_LINES = 6  # one per test below
```

Edit 3 (the same file, the imports), replace:

```python
from ops_core.tokens import WorkloadTokenSource
```

with:

```python
from ops_core.tokens import WorkloadTokenSource
from ops_worker.mcp import HttpMcpCaller
```

Append to the same file, after two blank lines:

```python
async def test_r029_the_workers_client_accepts_the_real_server_and_every_real_read(
    app_conn: persistence.Conn, role_conn: RoleConn, secret: Callable[[str], str], lines: list[str]
) -> None:
    """The positive half of R029 (the negative half, an altered listing or result, is tests/plan_m/test_worker_r029.py):
    the worker's client lists in the same session, compares the advertised schemas with the committed files and
    validates each result, and all three reads of a real run pass."""
    _, _, run = await new_run(app_conn, ALPHA, api=await role_conn(Role.API), interval=SEAL_WINDOW)
    caller = HttpMcpCaller(
        WorkloadTokenSource(
            token_url=settings.keycloak().token_url,
            client_id="ops-worker",
            client_secret=secret("kc_client_secret_ops_worker"),
        )
    )
    reads = (
        (Tool.GET_ASSET_STATUS, {"asset_id": "A17"}),
        (Tool.GET_RECENT_ALERTS, {"asset_id": "A17", **INTERVAL, "limit": 5}),
        (Tool.SEARCH_PROCEDURES, {"query": "seal inspection", "limit": 3, "mode": "lexical"}),
    )
    try:
        async with serving() as url:
            handle = await handle_for(app_conn, role_conn, run, "t16-r029")
            statuses = [
                (await caller.call(url, handle=handle, tool=name.value, arguments=arguments))["status"]
                for name, arguments in reads
            ]
        assert statuses == ["ok", "ok", "ok"]
        lines.append("R029: the worker's client listed, compared the schemas and validated all three reads: ok")
    finally:
        await purge_run(app_conn, run)
```

Run: `uv run ruff format tests/e2e && uv run ruff check --fix tests/e2e`, then `PYTHONUTF8=1 uv run python
scripts/check.py` → `CHECK: GREEN`, pytest `1341 passed, 205 skipped`; `uv run python -I scripts/verify_handoff.py
--reference-code --manifest --contracts` → exit 0; `PYTHONUTF8=1 uv run python scripts/check.py --profile test` →
`CHECK: GREEN`, pytest `1525 passed, 21 skipped` (arithmetic), then the `git checkout -- reports/...` of the Global
Constraints. The R105 module's worker now lists mcp-read's tools before its search and validates the answer: a
failure there is R029 refusing the real server, which Review Focus 4 explains how to read.

- [ ] **Step 4: Commit**

```bash
git add worker/src/ops_worker/mcp.py tests/plan_m/test_worker_r029.py tests/e2e/test_mcp_read_t16_live.py
git commit -m "feat(worker): R029 - list the read tools, compare their schemas, validate every read result (T16)"
```

### Task 6: An independent client reads an asset; the runbooks and the retrieval settings

**Files:**
- Create: `docs/runbooks/asset-sim.md`
- Modify: `tests/e2e/test_mcp_read_process_live.py` (R025's call), `docs/runbooks/mcp-read.md`, `mcp-read/README.md`,
  `docs/runbooks/dev-topology.md`, `docs/runbooks/walking-skeleton.md`, `docs/retrieval.md`

**Requirements:** ruling 17 (the asset tools proven with an independent client over HTTP, BS:378, R025's pattern),
ruling 4 (the rule documented), ruling 11 (`docs/retrieval.md` records the excerpt change), BS:405.

- [ ] **Step 1: The independent process reads an asset**

Edit 1 (`tests/e2e/test_mcp_read_process_live.py`, R025's session), replace:

```python
                tools = (await client.list_tools()).tools
                result = await client.call_tool("search_procedures", QUERY)
```

with:

```python
                tools = (await client.list_tools()).tools
                result = await client.call_tool("search_procedures", QUERY)
                # T16 (ruling 17): an asset tool through the child, which reaches asset-sim with its own token.
                status = await client.call_tool("get_asset_status", {"asset_id": "A17"})
```

Edit 2 (the same test), replace:

```python
        assert doc["data"]["results"][0]["evidence_id"] == ANSWER  # first by a wide margin (round 1, M10)
        text = log.read_text(encoding="utf-8", errors="replace")
```

with:

```python
        assert doc["data"]["results"][0]["evidence_id"] == ANSWER  # first by a wide margin (round 1, M10)
        answered = status.structured_content
        assert not status.is_error and isinstance(answered, dict) and answered["status"] == "ok"
        assert answered["data"]["asset_id"] == "A17" and answered["data"]["data_source"] == "synthetic"
        text = log.read_text(encoding="utf-8", errors="replace")
```

Edit 3 (the same test's evidence line), replace:

```python
            f" {PROTOCOL_VERSION} listed the three read tools, called search_procedures ok"
```

with:

```python
            f" {PROTOCOL_VERSION} listed the three read tools, called search_procedures and get_asset_status ok"
```

- [ ] **Step 2: The runbooks**

Create `docs/runbooks/asset-sim.md`:

```markdown
# asset-sim: the synthetic asset and alert API behind mcp-read (T16)

Who this is for: whoever runs asset-sim, reads an asset tool's answer, or debugs an `UNAVAILABLE`, `NOT_FOUND` or
`UPSTREAM_INVALID` from mcp-read. The design is SA:78, SA:555 (AM-20.7 item 6) and BS:405 in the specification, and
Plan M (`docs/superpowers/plans/2026-10-18-first-slice-m-read-tools-asset-sim.md`, rulings 4-6 and 8-10).

## What it is

A FastAPI service on `127.0.0.1:8091` (`OPS_ASSET_SIM_PORT`), the first of the skeleton's seven processes. It has no
database and no clock: it reads `data/corpus/assets.json` (authored, under corpus-1's lock) and `data/corpus/meta.json`
(generated: the tenant UUIDs and the alerts' uuid5 IDs) once at start, refuses to start if an alert's severity, kind
or `raised_at` is malformed, and answers every request as a function of those files, the forwarded tenant and the
forwarded instant. corpus-1 is never changed by it: T41 labels against that version.

## Who may call it

Only mcp-read, with its own workload token: `ops-mcp-read`'s client-credentials token (audience `asset-sim`, `azp`
`ops-mcp-read`, `typ` `Bearer`), never the worker's token and never the invocation handle. A genuine token of another
audience or client (the worker's, mcp-write's, a persona's) is 403 `FORBIDDEN`; a missing, expired or otherwise
refused token is 401 `UNAUTHENTICATED` with `WWW-Authenticate: Bearer`. Every request carries the context mcp-read read
from `app.asset_scope` for the handle:

| Header | Value |
|---|---|
| `X-Ops-Tenant-Id` | the run's tenant UUID |
| `X-Ops-As-Of` | the database instant to answer at (`app.current_time()` after the lease lock), RFC 3339 UTC |

A missing or malformed header or query parameter is 400 `INVALID_INPUT`, with a body that never echoes the request.

## Routes

- `GET /assets/{asset_id}` → `{"asset_id", "asset_type"}` (mcp-read passes the type to the procedure search).
- `GET /assets/{asset_id}/status` → `get_asset_status`'s data.
- `GET /assets/{asset_id}/alerts?start_at=…&end_at=…&limit=1..100[&cursor=…]` → `get_recent_alerts`'s data.

An asset of another tenant and an asset that does not exist get the same 404 `NOT_FOUND` "no such asset": the forwarded
tenant decides, and nothing tells the two apart.

## The rules

- **Alerts.** `alert_id` is `meta.json`'s uuid5; `occurred_at` is `raised_at`; `code` is `kind`; `message` is
  "Synthetic <severity> alert: <kind with spaces> on <asset name>."; `revision` as authored.
- **Status as of T** (T = `X-Ops-As-Of`). `state` is `warning` when one of the asset's alerts of severity `warning`
  or `critical` was raised in `[T - 24 h, T]`, else `normal`; `revision` is the highest revision among its alerts
  raised at or before T, or 1; `observed_at` is T; `data_source` is `synthetic`. `unavailable` comes only from the
  test-profile fault hook.
- **Alerts of an interval.** `start_at <= occurred_at < end_at` and `occurred_at <= T` (no alert from the future),
  ordered by `(occurred_at, alert_id)`, `limit` per page. `next_cursor` is set exactly when alerts remain; it is a
  76-character base64url token holding the last alert's position and the SHA-256 of `(tenant, asset, start_at,
  end_at)`, so a cursor presented for another tenant, asset or interval is 400.

At the stated instants (corpus-1):

| Asset | at 2026-10-16T12:00Z | at 2026-10-06T00:00Z | at 2026-10-06T12:00Z |
|---|---|---|---|
| A17 (alpha pump; seal leaks 10-05T14:00Z r1, 10-06T08:30Z r2) | `normal`, revision 2 | `warning`, revision 1 | `warning`, revision 2 |
| B22 (beta pump; vibration 10-05T11:20Z r1) | `normal`, revision 1 | `warning`, revision 1 | `normal`, revision 1 |

## Running and looking at it

`uv run python scripts/skeleton.py up` starts it with the others; `status` shows its readiness (`/health/ready` is 200
once the realm's signing keys are loaded). To look at an answer by hand you need an `ops-mcp-read` token, which only
the secret file `kc_client_secret_ops_mcp_read` can mint: do that in a script that reads the file, never on a command
line. The live tests do it (`tests/e2e/test_asset_sim_live.py`).

## Fault hooks (test profile only)

Under `PROFILE=test`, `POST /internal/faults/{kind}` with `{"count": n}` (and `"seconds"` for the slow one), authorised
by mcp-read's token, arms one of the four faults asset-sim consumes: `asset_unavailable` (the next status answers
`unavailable`), `drop_before_commit` (the next request is 503), `malformed_response` (the next answer is not the
contract's) and `timeout_before_accept` (the next request waits `seconds`, then 503). In the dev and demo profiles the
route does not exist (`Faults` refuses to be built there).

## When something looks wrong

- **mcp-read answers `NOT_FOUND`**: the run's asset is not one of its tenant's in `assets.json` (the admission does not
  tie a run's asset to its tenant yet, T21; an alpha run naming B22 gets exactly this).
- **mcp-read answers `UNAVAILABLE`**: asset-sim is down, slower than mcp-read's 10 seconds, answering 5xx, or refusing
  mcp-read's token (its log shows the 401 or 403).
- **mcp-read answers `UPSTREAM_INVALID`**: asset-sim's answer failed the tool-result contract or named another asset or
  interval; in the test profile, check for an armed `malformed_response`.
- **asset-sim will not start**: a data file is malformed (the message names the rule, never a value), or the realm's
  keys cannot be loaded.

## Not here yet

asset-sim's own `tests/` directory and Dockerfile, packaging `data/corpus/` for a container, and the network test that
only mcp-read can reach it (T30); recording a status observation for the grant's freshness check (T21).
```

Edit 1 (`docs/runbooks/mcp-read.md`, "Starting it"), replace:

```markdown
`python -m ops_mcp_read` (or `scripts/skeleton.py up`) needs the database at revision 0011: at start it refuses when
`app.test_clock` exists outside the test profile, when `app._resolve_handle` lacks 0009's job binding, and when
`app.search_procedures_scoped` (0011) is missing ("… predates this service; run scripts/skeleton.py migrate for this
profile"). mcp-write makes the 0009 check at its own start. The tool answers from the governed corpus, so a database
that was never ingested (`scripts/skeleton.py ingest`) answers every search with no results and `corpus_version`
`none`. Readiness (`/health/ready`) needs the realm's signing keys and the database.
```

with:

```markdown
`python -m ops_mcp_read` (or `scripts/skeleton.py up`) needs the database at revision 0012: at start it refuses when
`app.test_clock` exists outside the test profile, when `app._resolve_handle` lacks 0009's job binding, when
`app.search_procedures_scoped` (0011) is missing, and when `app.asset_scope` or the search's `retrieved_at` (0012) is
missing ("… predates this service; run scripts/skeleton.py migrate for this profile"). It also reads its own
workload secret (`kc_client_secret_ops_mcp_read`) at start, for asset-sim. mcp-write makes the 0009 check at its own
start. The search answers from the governed corpus, so a database that was never ingested (`scripts/skeleton.py
ingest`) answers every search with no results and `corpus_version` `none`. Readiness (`/health/ready`) needs the
realm's signing keys and the database; asset-sim is a dependency of a call, not of readiness.
```

Edit 2 (`docs/runbooks/mcp-read.md`, the tool paragraph), replace:

```markdown
The tool `search_procedures` takes `query` (1-500 characters), `limit` (1-8), `mode` (`lexical`; `vector_exact` is
refused `UNSUPPORTED_MODE` until T18) and an optional `asset_type` (1-40 characters: documents of that family or of
none). It resolves the handle in one unit, then calls `app.search_procedures_scoped` in a second, which resolves the
handle again and decides the tenant from it; a handle refused at either is the same `INVALID_HANDLE` envelope. The
settings and how to read the ranking are in `docs/retrieval.md`.
```

with:

```markdown
## The three read tools (T16)

Each tool advertises exactly its committed input schema (`schemas/tools/<tool>.input.schema.json`); the worker
compares what it is shown with the same file and refuses to call a server that lists another tool set (R029). Every
call resolves the handle and checks the tool in one committed unit, then reads the run's scope through
`app.asset_scope` in a second (the handle again, and the run's requester must still hold an active requester
membership in the run's tenant: R028); a handle refused at any unit, or a requester who lost the membership, is the
same `INVALID_HANDLE` envelope. The tenant, the asset and the interval come from the run, never from an argument.

- `get_asset_status(asset_id)` and `get_recent_alerts(asset_id, start_at, end_at, limit 1-100[, cursor])` answer for
  the run's own asset and fixed `[start_at, end_at)` only: another asset is `ASSET_OUT_OF_SCOPE` and another interval
  (compared as instants: `Z` and `+00:00` agree) is `INTERVAL_OUT_OF_SCOPE`, both before asset-sim is asked. Then
  mcp-read calls asset-sim (`OPS_ASSET_SIM_URL`) with its own `ops-mcp-read` token, the run's tenant and the database
  instant `as_of`, outside any transaction, 10-second timeout, no retry. asset-sim unreachable, slow or failing is
  `UNAVAILABLE` (`retryable: true`); an asset asset-sim does not know for this tenant (another tenant's included) is
  `NOT_FOUND`; a cursor of another request is `INVALID_CURSOR`; an answer outside the tool-result contract or the
  run's scope is `UPSTREAM_INVALID`. The envelope's `observed_at` is `as_of`; for alerts, `truncated` is true exactly
  when `next_cursor` is set. The rules asset-sim answers by are in `docs/runbooks/asset-sim.md`.
- `search_procedures(query 1-500, limit 1-8, mode[, asset_type])`: `vector_exact` is refused `UNSUPPORTED_MODE`
  after the handle resolution and before anything else (T18). mcp-read asks asset-sim for the run's asset type and
  searches that type (documents of that family or of none); a caller's `asset_type` may only repeat it
  (`ASSET_TYPE_OUT_OF_SCOPE`); an asset asset-sim does not know leaves the caller's type or none. A third unit calls
  `app.search_procedures_scoped`, which returns the instant it decided permission at: every result's `retrieved_at`
  and the envelope's `observed_at` are that instant. An excerpt is the whole section up to 8000 characters, and a cut
  one sets `truncated`. The settings and how to read the ranking are in `docs/retrieval.md`.
```

Edit 3 (`docs/runbooks/mcp-read.md`, the variables), replace:

```markdown
| `OPS_MCP_READ_URL` | `http://127.0.0.1:8081/mcp` | where the worker calls it |
```

with:

```markdown
| `OPS_MCP_READ_URL` | `http://127.0.0.1:8081/mcp` | where the worker calls it |
| `OPS_ASSET_SIM_URL` | `http://127.0.0.1:8091` | where it calls asset-sim (T16) |
```

Edit 4 (`docs/runbooks/mcp-read.md`, "When something looks wrong"), replace:

```markdown
- **mcp-read will not start**: read the message. "predates this service" is the missing revision; "signing keys
  unavailable" is the realm.
```

with:

```markdown
- **mcp-read will not start**: read the message. "predates this service" is the missing revision; "signing keys
  unavailable" is the realm; "secret file kc_client_secret_ops_mcp_read is missing" is `OPS_SECRETS_DIR`.
- **Every asset tool answers `UNAVAILABLE`**: asset-sim is down or not at `OPS_ASSET_SIM_URL` (`scripts/skeleton.py
  status`), or it refuses mcp-read's token (its log shows 401/403: the realm's `ops-mcp-read` client lost its
  `asset-sim` audience). The search answers `UNAVAILABLE` for the same reasons: it asks asset-sim for the run's type.
```

Edit 5 (`docs/runbooks/mcp-read.md`, "Not here yet"), replace:

```markdown
The asset tools and asset-sim (T16), vector search (T18), TLS and container host names (T30).
```

with:

```markdown
Vector search and the `search_query:` embedding (T18), the worker's own asset reads and the evidence bundle (T20),
recording the status observation for the grant's freshness check (T21), TLS and container host names (T30).
```

Edit 6 (`mcp-read/README.md`, "Trusts" and "Never"), replace:

```markdown
The worker's workload access token with this server's audience; the definer functions `resolve_invocation` and
`search_procedures_scoped` (T17; `asset_scope` arrives with T16)

## Never
Any write-path function; incident-sim
```

with:

```markdown
The worker's workload access token with this server's audience; the definer functions `resolve_invocation`,
`asset_scope` (T16) and `search_procedures_scoped` (T17); asset-sim's answers only once they pass the tool-result
contract and the run's scope

## Never
Any write-path function; incident-sim; forwarding the handle or the worker's token to asset-sim
```

Edit 7 (`mcp-read/README.md`, "Runs"), replace:

```markdown
it checks at start, with 0011's corpus function). One tool, `search_procedures` (lexical, over the governed corpus
through `search_procedures_scoped`, T17). See
`docs/runbooks/mcp-read.md`.
```

with:

```markdown
it checks at start, with 0011's corpus function and 0012's `asset_scope`). Three tools (T16): `get_asset_status` and
`get_recent_alerts`, answered by asset-sim (`OPS_ASSET_SIM_URL`) with mcp-read's own `ops-mcp-read` token for the
run's own asset and interval, and `search_procedures` (lexical, over the governed corpus through
`search_procedures_scoped`, on the run's asset type). See `docs/runbooks/mcp-read.md`.
```

Edit 8 (`docs/runbooks/dev-topology.md`), replace:

```markdown
The six application processes run on the host until T30 containerises them (`docs/runbooks/walking-skeleton.md`). Every listener binds `127.0.0.1`.

| Process | Module | Port | Notes |
|---|---|---|---|
| incident-sim | `ops_incident_sim` | 8090 | destination; database `incident`, role `incident` |
| mcp-read | `ops_mcp_read` | 8081 | `/mcp`, read tool `search_procedures` |
```

with:

```markdown
The seven application processes run on the host until T30 containerises them (`docs/runbooks/walking-skeleton.md`). Every listener binds `127.0.0.1`.

| Process | Module | Port | Notes |
|---|---|---|---|
| asset-sim | `ops_asset_sim` | 8091 | synthetic assets and alerts; mcp-read's `ops-mcp-read` token only; no database (T16) |
| incident-sim | `ops_incident_sim` | 8090 | destination; database `incident`, role `incident` |
| mcp-read | `ops_mcp_read` | 8081 | `/mcp`, read tools `get_asset_status`, `get_recent_alerts`, `search_procedures` |
```

Edit 9 (`docs/runbooks/walking-skeleton.md`, step 3), replace:

```markdown
3. Either, for a manual session: `uv run python scripts/skeleton.py up` — starts incident-sim :8090, mcp-read
   :8081, mcp-write :8082, api :8000, worker :8070 (health only), sweeper :8071
```

with:

```markdown
3. Either, for a manual session: `uv run python scripts/skeleton.py up` — starts asset-sim :8091 (T16),
   incident-sim :8090, mcp-read :8081, mcp-write :8082, api :8000, worker :8070 (health only), sweeper :8071
```

Edit 10 (`docs/runbooks/walking-skeleton.md`, step 4), replace:

```markdown
   `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e -q` — the R105 module starts and stops its own six
   processes
```

with:

```markdown
   `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e -q` — the R105 module starts and stops its own seven
   processes
```

Edit 11 (`docs/retrieval.md`, the settings table), replace:

```markdown
| Results | `limit` 1 to 8 (the worker asks for 3; the measurement uses 5); excerpt the first 500 characters |
```

with:

```markdown
| Results | `limit` 1 to 8 (the worker asks for 3; the measurement uses 5); the excerpt is the whole section up to the contract's 8000 characters, and a cut one sets the envelope's `truncated` (revision 0012, T16; corpus-1's sections are 45-119 words, so no excerpt and no rank of the T17 baseline changed) |
| Asset type | the run's own, from asset-sim (T16): a caller may only repeat it; an asset asset-sim does not know leaves the caller's type or none |
| Instant | `retrieved_at` is the database instant the effectiveness rule ran at (`search_procedures_scoped`'s own column since revision 0012), never the wall clock |
```

Run: `uv run ruff format tests/e2e && uv run ruff check tests/e2e`, `uv run python "$COUNT" mcp-read/README.md
asset-sim/README.md docs/runbooks/mcp-read.md` → no output (Markdown table rows in `asset-sim.md`, `dev-topology.md`
and `docs/retrieval.md` stay one row per line, as their existing rows do), then `PYTHONUTF8=1 uv run python
scripts/check.py` → `CHECK: GREEN`, pytest `1341 passed, 205 skipped`; `uv run python -I scripts/verify_handoff.py
--reference-code --manifest --contracts` → exit 0; `PYTHONUTF8=1 uv run python scripts/check.py --profile test` →
`CHECK: GREEN`, pytest `1525 passed, 21 skipped` (arithmetic), then the `git checkout -- reports/...` of the Global
Constraints.

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/test_mcp_read_process_live.py docs/runbooks/asset-sim.md docs/runbooks/mcp-read.md \
  mcp-read/README.md docs/runbooks/dev-topology.md docs/runbooks/walking-skeleton.md docs/retrieval.md
git commit -m "docs: asset-sim's runbook, mcp-read's three tools, an independent client reading an asset (T16)"
```

### Task 7: Close-out — records, acceptance rows, errata 103-106, state, history, final gates

**Files:**
- Modify: `handoff/tasks.json` (T16 → `DONE` with two review notes; T18 gains a review note),
  `handoff/acceptance-matrix.json` (R028, R029, R131), `handoff/BUILD_BACKLOG.md` (T16 checked; one note each under
  T16 and T18), `SESSION_STATE.md` (the "Next task" lines, a "Plan M executed" section, the dev database state, the
  owner inputs), `STATUS.md` (an update section), `docs/ARCHITECTURE.md` (R131's read-half row, a new section 10),
  `docs/PROJECT_HISTORY.md` (section 30; the last section becomes 31), this plan (its checkboxes); the evidence under
  `reports/asset-sim/` and `reports/mcp-read/` and the files the final live run rewrites

**Requirements:** the T16 record (R028, R029 evidenced; R131's read half complete); every deferral to T16 in live code
and documentation resolved or re-homed. This task writes no behaviour.

Throughout, `<base>..<last>` is the git range of this plan's execution on `plan-m`, written as two short hashes:
`<base>` is the `BASE` recorded in Task 1 Step 1b (excluded by the range) and `<last>` the newest commit before this
task's own. `<date>` is `date -u +%F` on the day of the close-out. Step 4 replaces every one of them.

- [ ] **Step 1: Handoff records**

Run this once from the repository root, with `BASE` set to the hash Task 1 Step 1b recorded (it rewrites the two JSON
files in their own format: two-space indent, non-ASCII kept, one trailing newline). It is a script file, not an
interactive session: save it outside the repository as `t16_records.py` and run `BASE=<hash> uv run python
<path>/t16_records.py`. It stops if the evidence files of Tasks 2-5 are missing (rerun the live gate first).

```python
import json
import os
import subprocess
from pathlib import Path

base = os.environ["BASE"]
last = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True).stdout
subprocess.run(["git", "merge-base", "--is-ancestor", base, "HEAD"], check=True)  # the base is this branch's own
span = f"{base}..{last.strip()}"
for evidence in ("reports/asset-sim/t16-asset-sim.txt", "reports/mcp-read/t16-read-tools.txt"):
    if not Path(evidence).is_file():
        raise SystemExit(f"{evidence} is missing: run the live gate (check.py --profile test) first")

note = (
    f"Plan M (branch plan-m): done in {span} (the debt list, then the six tasks; the close-out is the next commit; plan "
    "docs/superpowers/plans/2026-10-18-first-slice-m-read-tools-asset-sim.md). Shipped: revision 0012_asset_scope "
    "(app.asset_scope(raw_handle, client_azp) for mcp_read alone: the handle decides the run and the tenant, the run's "
    "requester must still hold an active requester membership in its tenant, and it returns the run's asset, "
    "[start_at, end_at) and as_of = app.current_time() after the lease lock; search_procedures_scoped re-created from "
    "0011's body with the same membership check, a retrieved_at column and the whole section as its excerpt up to "
    "8000 characters with a per-row cut flag; an exact downgrade to 0011); asset-sim as the seventh process (port "
    "8091; mcp-read's ops-mcp-read token only, 403 for another audience or client and 401 otherwise; its own tenant "
    "filter, an unknown and a foreign asset both 404; status and alerts derived from corpus-1's assets.json and "
    "meta.json at the instant mcp-read forwards, corpus-1 unchanged; a cursor bound to tenant, asset and interval; "
    "fault hooks under PROFILE=test only); mcp-read's get_asset_status and get_recent_alerts (two committed units, "
    "then asset-sim with mcp-read's own token outside any transaction; ASSET_OUT_OF_SCOPE and INTERVAL_OUT_OF_SCOPE "
    "before asset-sim is asked; asset-sim's answer validated as a whole tool result and against the run's scope, "
    "UPSTREAM_INVALID otherwise; UNAVAILABLE retryable, NOT_FOUND, INVALID_CURSOR), the committed input schemas "
    "advertised exactly, search_procedures on the run's own asset type (ASSET_TYPE_OUT_OF_SCOPE) and stamped with "
    "the definer's instant; ops_core.tool_contracts (jsonschema at run time); the worker's HttpMcpCaller lists the "
    "read tools in the same session, refuses an unexpected tool set or an altered schema, and refuses an oversized, "
    "error-flagged, malformed or non-ok read result, so the run fails as retrieval failed. Evidence: "
    "tests/e2e/test_migration_0012_live.py, test_asset_sim_live.py, test_mcp_read_t16_live.py and "
    "reports/asset-sim/t16-asset-sim.txt, reports/mcp-read/t16-read-tools.txt (live), tests/plan_m/ for the unit "
    "half, docs/runbooks/asset-sim.md for the rules. Deferred: vector mode and the search_query embedding -> T18 "
    "(erratum 103); the worker's asset reads, the evidence bundle, SA:377 and the write calls' discovery -> T20; "
    "the status observation for the grant's freshness and a run's asset tied to its tenant -> T21; packaging, "
    "Dockerfile, tests/ and the network test -> T30. Errata 103-106 are proposed in SESSION_STATE.md; the dev "
    "database waits for the owner's migrate to 0012. R028 and R029 are met; R131's read half is complete subject "
    "to the owner's decisions on errata 96 and 104."
)
ruling_14 = (
    "Plan M ruled on debts b and c: vector mode (b) moved to T18 with its embeddings (erratum 103; T18's review note); "
    "the UNSUPPORTED_MODE order stays, the handle first (an invalid handle never learns what the server supports), "
    "and the fallback corpus_version is closed by T17: the definer answers none before any ingestion (ruling 14)."
)
t18_note = (
    "From T16 (Plan M ruling 1, erratum 103): mcp-read's vector_exact -> mode=vector translation and the nomic "
    "search_query embedding it computes and passes to search_procedures_scoped (T16's instruction and review note "
    "moved here); until then mcp-read answers vector_exact with UNSUPPORTED_MODE after the handle resolution "
    "(server.py and routing.py carry TODO(T18))."
)
tasks_path = Path("handoff/tasks.json")
tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
t16 = next(t for t in tasks["tasks"] if t["id"] == "T16")
t18 = next(t for t in tasks["tasks"] if t["id"] == "T18")
assert t16["status"] == "PLANNED" and "review_notes" not in t18
t16["status"] = "DONE"
t16["review_notes"] += [ruling_14, note]
t18["review_notes"] = [t18_note]
tasks_path.write_text(json.dumps(tasks, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

matrix_path = Path("handoff/acceptance-matrix.json")
matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
rows = {
    "R028": (
        [
            "tests/e2e/test_mcp_read_t16_live.py",
            "reports/mcp-read/t16-read-tools.txt",
            "tests/e2e/test_asset_sim_live.py",
            "reports/asset-sim/t16-asset-sim.txt",
            "tests/e2e/test_migration_0012_live.py",
            "tests/plan_m/test_mcp_read_assets.py",
            "tests/plan_m/test_asset_sim_app.py",
        ],
        "Plan M (T16): alpha never reads B22: an A17 run naming B22 is ASSET_OUT_OF_SCOPE before asset-sim is asked, "
        "an alpha run whose own asset is B22 gets NOT_FOUND from asset-sim's own tenant filter (the same 404 as an "
        "unknown asset), and asset-sim answers alpha's tenant 404 for B22 directly; another interval is "
        "INTERVAL_OUT_OF_SCOPE; the search keeps to the run's asset type (ASSET_TYPE_OUT_OF_SCOPE otherwise) and never "
        "returns the revoked ALPHA-ALARM-BYPASS. Current access: asset_scope and search_procedures_scoped re-check "
        "that the run's requester still holds an active requester membership in its tenant (matched without an "
        "issuer, erratum 105); with alex's switched off, all three tools answer the one plain INVALID_HANDLE while "
        "resolve_invocation still resolves the handle, and answer again once it is back; a run requested by a reader "
        "never answers. No forbidden data reaches the caller in any of these.",
    ),
    "R029": (
        [
            "tests/plan_m/test_worker_r029.py",
            "tests/e2e/test_mcp_read_t16_live.py",
            "reports/mcp-read/t16-read-tools.txt",
            "tests/plan_m/test_mcp_read_assets.py",
            "tests/plan_m/test_tool_contracts.py",
        ],
        "Plan M (T16): the worker's client lists the read tools in the same session before it calls one and refuses "
        "(McpCallFailed, the run FAILED as retrieval failed) a tool added or removed or an altered input schema of the "
        "called tool, compared with the committed file as canonical JSON, without calling it; it refuses an "
        "error-flagged, malformed (nested data checked against schemas/tool-result.schema.json), another tool's, "
        "non-object, non-ok or larger-than-256-KiB result; live, the real server passes and all three reads "
        "validate. mcp-read itself validates asset-sim's answers as whole tool results and against the run's scope "
        "before returning them (UPSTREAM_INVALID). The write calls keep T47's check (T20).",
    ),
}
for row in matrix["requirements"]:
    if row["id"] in rows:
        row["evidence_paths"], row["note"] = rows[row["id"]]
        row["implementation_status"] = "IMPLEMENTED_LOCALLY_VERIFIED"
        row["evidence_status"] = "RECORDED_LOCALLY_LIVE"
    elif row["id"] == "R131":
        old = (
            "mcp_read can EXECUTE current_time (erratum 15), resolve_invocation and, since Plan L (T17), "
            "search_procedures_scoped, and nothing else in app (asset_scope joins with T16; errata 72 and 96; the read "
            "half is met subject to the owner's decision on erratum 96)"
        )
        new = (
            "mcp_read can EXECUTE current_time (erratum 15), resolve_invocation, search_procedures_scoped (since Plan L, "
            "T17) and asset_scope (since Plan M, T16), and nothing else in app (errata 72, 96 and 104; the read half "
            "is complete subject to the owner's decisions on errata 96 and 104)"
        )
        assert row["note"].count(old) == 1
        row["note"] = row["note"].replace(old, new)
        old_write = (
            "search_procedures_scoped, mcp-read's read function since T17, is 42501 when mcp_exec calls it (errata 91 "
            "and 96)"
        )
        new_write = (
            "search_procedures_scoped and asset_scope, mcp-read's read functions since T17 and T16, are 42501 when "
            "mcp_exec calls them (errata 91, 96 and 104)"
        )
        assert row["note"].count(old_write) == 1
        row["note"] = row["note"].replace(old_write, new_write)
        row["evidence_paths"].append("tests/e2e/test_migration_0012_live.py")
matrix_path.write_text(json.dumps(matrix, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

backlog_path = Path("handoff/BUILD_BACKLOG.md")
lines = backlog_path.read_text(encoding="utf-8").split("\n")


def after_notes(head: str) -> int:
    """The index just after the task's head line and its existing review notes."""
    at = next(i for i, line in enumerate(lines) if line.startswith(head))
    at += 1
    while lines[at].startswith("  - "):
        at += 1
    return at


head = "- [ ] **T16 Read tools and asset-sim on mcp-read**"
assert sum(line.startswith(head) for line in lines) == 1
lines.insert(after_notes(head), f"  - *Review note:* {ruling_14}")
lines.insert(after_notes(head), f"  - *Review note:* {note}")
at = next(i for i, line in enumerate(lines) if line.startswith(head))
lines[at] = lines[at].replace("- [ ]", "- [x]", 1)
lines.insert(after_notes("- [ ] **T18 "), f"  - *Review note:* {t18_note}")
backlog_path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
print(span)
```

Expected: it prints the span (for example `1a2b3c4..5d6e7f8`). `git diff --stat handoff` shows three files changed;
`git diff handoff/acceptance-matrix.json` shows three rows: R028, R029 and R131.

- [ ] **Step 2: Project state**

Edit 1 (`SESSION_STATE.md`, under "Session state"), replace:

```markdown
**Next task:** Plan M = T16 (the read tools, `asset_scope` and asset-sim), on branch `plan-m` from `main`. Plan L (T17) was executed on branch `plan-l` (`c329145..bbba69c` holds the debt list and
the five building tasks, and the close-out is the commit after `bbba69c`); the owner merged it with the rest on 2026-10-18. T17 is DONE subject to the owner's decision
on erratum 102 (R033's "missing source remains missing": 15/20 no-source development questions answered with
nothing at the 0.25 minimum rank; the other 5/20 stay open: SA:377 as written would not abstain on them, so T20 must add a relevance criterion beyond it); R131's read half is met subject to the
owner's decision on erratum 96 (`asset_scope` still arrives with T16). Owner inputs: (1) the holdout seal (T03
step 9), then the live probe (T02); (2) T44 step 10 (step A applied 2026-10-16; the
other-device LAN check and the firewall rules remain) (`docs/runbooks/ollama-network.md` step A); (3) decide the
proposed errata of Plans C, E, F, G, H, I, J, K and L (errata 1-102; L: 93-102 below). The dev database is at 0011 with corpus-1
ingested (owner, 2026-10-18). Next is Plan M = T16 (the read tools and asset-sim, the earliest dependency-satisfied PLANNED task in
`handoff/tasks.json`; T18 and T23 are unblocked too; T19 and T41 wait on owner steps). A proposed erratum awaiting the owner's decision does not change a task's status; a task met "subject to" an erratum stays DONE.
```

with:

```markdown
**Next task:** Plan M (T16) is executed on branch `plan-m` (from `main`: `<base>..<last>` holds the debt list and the
six building tasks, and the close-out is the commit after `<last>`). T16 is DONE: R028 and R029 are evidenced; R131's
read half is complete subject to the owner's decisions on errata 96 and 104. Owner inputs: (1) the holdout seal (T03
step 9), then the live probe (T02); (2) T44 step 10 (step A applied 2026-10-16; the other-device LAN check and the
firewall rules remain) (`docs/runbooks/ollama-network.md` step A); (3) decide the proposed errata of Plans C, E, F,
G, H, I, J, K, L and M (errata 1-106; M: 103-106 below); (4) migrate the dev database to revision 0012
(`uv run python scripts/skeleton.py migrate`, dev profile: it creates `app.asset_scope` and re-creates
`app.search_procedures_scoped`, changing no row); until then mcp-read refuses to start on it; (5) push `plan-m` and
open its PR when the final review is done. Next is T18 (vector retrieval; it now also owns mcp-read's vector mode)
or T23, both unblocked; T19 and T41 wait on owner steps, and T20 waits on T19. A proposed erratum awaiting the
owner's decision does not change a task's status; a task met "subject to" an erratum stays DONE.
```

Edit 2 (`SESSION_STATE.md`, the repository line), replace:

```markdown
**Repository:** local git repo at `C:\Users\joeys\Desktop\MLOps`, branch `plan-m` off `main` (Plan M work;
```

with:

```markdown
**Repository:** local git repo at `C:\Users\joeys\Desktop\MLOps`, branch `plan-m` off `main` (Plan M executed, not pushed;
```

Edit 3 (`SESSION_STATE.md`, at the end of "Plan L executed"), replace:

```markdown
## Walking-skeleton debt list (T08; committed before coding) [R6-B7]
```

with:

```markdown
## Plan M executed (<date>, branch `plan-m`)

- T16 = `<base>..<last>` (the debt list first, then the six building tasks; the close-out is the commit after
  `<last>`). The plan (`docs/superpowers/plans/2026-10-18-first-slice-m-read-tools-asset-sim.md`) holds the 18 rulings
  of the controller's brief as implemented, with ten writer departures named at its top; the input is
  `docs/superpowers/research/2026-10-18-plan-m-inputs.md`. Evidence: `tests/e2e/test_migration_0012_live.py`,
  `test_asset_sim_live.py`, `test_mcp_read_t16_live.py`, `reports/asset-sim/t16-asset-sim.txt` and
  `reports/mcp-read/t16-read-tools.txt` (live); `tests/plan_m/` (unit).
- Shipped: revision `0012_asset_scope` (`asset_scope`, the requester re-check in both read definers, the search's
  `retrieved_at` and whole-section excerpt; exact downgrade to 0011); asset-sim on port 8091, the skeleton's seventh
  process; mcp-read's `get_asset_status` and `get_recent_alerts` and the search on the run's asset type; the committed
  input schemas advertised and checked (`ops_core.tool_contracts`); the worker's R029 checks.
- Gates: `check.py` `<dev>`; `check.py --profile test` `<live>`; `verify_handoff.py` exit 0.
- **Proposed errata (the owner decides; the spec text stays authoritative until then).** Numbered on from Plan L's
  hundred and two:
  103. T16's instruction and review note (`handoff/tasks.json`, "vector mode: mcp-read computes the nomic
       search_query embedding"), SA:348 and SA:461: mcp-read's `vector_exact` → `mode=vector` translation and the
       `search_query:` embedding move to T18 with the embeddings; until then mcp-read answers `vector_exact` with
       `UNSUPPORTED_MODE` after the handle resolution, and the definer refuses `mode=vector`.
  104. SA:460 (`asset_scope`): the signature is `(raw_handle, client_azp)`, the caller's `azp` second as in
       `resolve_invocation`, the write path and the search (errata 83 and 93), because `_resolve_handle` binds the
       handle to the presented token's `azp`; it returns one row `(run_id, tenant_id, asset_id, start_at, end_at,
       as_of)`, `as_of` being `app.current_time()` read after the lease lock (SA:157), the instant asset-sim answers
       at; `mcp_read` only; it checks no tool (the allowlist stays in Python, erratum 19).
  105. BS:362 and BS:401 with R028 (the requester's policy at read time): `asset_scope` and `search_procedures_scoped`
       require an active `memberships` row `(the run's tenant, subject = runs.requester, role 'requester')`, matched
       without the issuer because `runs` keeps none (the API admits a requester by `(issuer, subject)` with the
       realm's one configured issuer); without it the call is refused exactly as a dead handle is (`OC008`, one
       message, SA:355). `resolve_invocation` is unchanged (erratum 77).
  106. SA:461 with erratum 93 (`search_procedures_scoped`'s answer): one row `(corpus_version, retrieved_at,
       results)`, `retrieved_at` the instant its effectiveness rule ran at; each result's excerpt is the whole section
       up to the contract's 8000 characters and carries `excerpt_cut`, which mcp-read turns into the envelope's
       `truncated` and leaves out of the result.
- Rulings made during execution (the controller's, from the SDD ledger): none yet; the executor lists them here.

## Walking-skeleton debt list (T08; committed before coding) [R6-B7]
```

Edit 4 (`SESSION_STATE.md`, the end of "Dev database state", before "Open owner inputs"), replace:

```markdown
## Open owner inputs
```

with:

```markdown
**Update (<date>):** Plan M adds revision 0012 (`app.asset_scope`, and `app.search_procedures_scoped` re-created with
a new return type). The dev `ops` database stays at 0011 until the owner runs `uv run python scripts/skeleton.py
migrate` (dev profile); the upgrade creates one function, re-creates one and changes no row; until then mcp-read
refuses to start on it, and `skeleton.py up` starts seven processes (asset-sim first).

## Open owner inputs
```

Edit 5 (`SESSION_STATE.md`, "Open owner inputs"), replace:

```markdown
- Decide errata 35-44 (see "Plan G executed"), 45-59 (see "Plan H executed"), 60-71 (see
  "Plan I executed"), 72-81 (see "Plan J executed"), 82-92 (see "Plan K executed") and 93-102 (see "Plan L
  executed").
```

with:

```markdown
- Decide errata 35-44 (see "Plan G executed"), 45-59 (see "Plan H executed"), 60-71 (see
  "Plan I executed"), 72-81 (see "Plan J executed"), 82-92 (see "Plan K executed"), 93-102 (see "Plan L
  executed") and 103-106 (see "Plan M executed").
- Migrate the dev database to revision 0012 (`uv run python scripts/skeleton.py migrate`); mcp-read refuses to start
  on 0011.
```

Edit 6 (`STATUS.md`, at the end), replace:

```markdown
- Next: Plan M = T16 (read tools, asset_scope, asset-sim) on branch plan-m from main.
```

with:

```markdown
- Next: Plan M = T16 (read tools, asset_scope, asset-sim) on branch plan-m from main.

## Update — Plan M executed (<date>, branch `plan-m`)

- Plan M (T16: the read tools, `asset_scope` and asset-sim) executed on branch `plan-m` (`<base>..<last>`, from
  `main`). The plan is `docs/superpowers/plans/2026-10-18-first-slice-m-read-tools-asset-sim.md`.
- `PYTHONUTF8=1 uv run python scripts/check.py` is `CHECK: GREEN`: pytest `<dev>`.
  `PYTHONUTF8=1 uv run python scripts/check.py --profile test` is `CHECK: GREEN`: pytest `<live>`.
  `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts` exits 0.
- **Evidenced** (`IMPLEMENTED_LOCALLY_VERIFIED`, `RECORDED_LOCALLY_LIVE`): R028 (alpha never reads B22, by mcp-read's
  scope check and by asset-sim's own tenant filter; a requester who lost the membership gets nothing from any of the
  three tools; the search keeps to the run's asset type and never returns a revoked procedure) and R029 (the
  worker refuses an altered tool list or schema before calling, and an error-flagged, malformed or oversized result;
  the run fails as "retrieval failed"). R131's read half is complete (`asset_scope` joins; subject to errata 96 and
  104).
- Also built: revision 0012; asset-sim, the seventh process (port 8091); `ops_core.tool_contracts`; mcp-read's asset
  tools and its asset-sim client; the search's instant and whole-section excerpt; `docs/runbooks/asset-sim.md`.
- The dev `ops` database waits at 0011 for the owner's migrate to 0012 (mcp-read refuses to start until then).
- Deferred, each with its owner in `SESSION_STATE.md`: vector mode -> T18; the worker's asset reads, the evidence
  bundle and the write calls' discovery -> T20; the status observation at the grant and the run's asset tied to its
  tenant -> T21; packaging and the network tests -> T30. Four errata (103-106) are proposed.
- Next: T18 (vector retrieval, now with mcp-read's vector mode) or T23.
```

Edit 7 (`docs/ARCHITECTURE.md`, section 7's R131 row), replace:

```markdown
| R131 (read half) | `mcp_read` executes three functions only (the third since T17); a recover and an execute handle at mcp-read are refused |
```

with:

```markdown
| R131 (read half) | `mcp_read` executes four functions only (`search_procedures_scoped` since T17, `asset_scope` since T16); a recover and an execute handle at mcp-read are refused |
```

Edit 8 (`docs/ARCHITECTURE.md`, after section 9), replace:

```markdown
## Where the code will live (not yet written)
```

with:

```markdown
## 10. The read tools and asset-sim (built in T16)

**Claim.** A read tool answers only for the handle's own run: its tenant, its asset, its fixed interval and the
database's instant, and only while the run's requester is still a member; and nothing the worker reads is used unless
it is the committed contract's.

- **The scope comes from the run.** `app.asset_scope` (mcp_read only) resolves the handle as every read definer does,
  re-checks the requester's active requester membership (R028) and returns the run's asset, interval and `as_of`;
  mcp-read refuses another asset or interval before anything leaves it.
- **asset-sim filters by tenant itself.** It trusts only mcp-read's own workload token and the forwarded tenant and
  instant, never the handle; an asset of another tenant is the same 404 as an unknown one; its data are derived from
  corpus-1 at the forwarded instant, so a moved test clock moves every answer.
- **Contracts at run time.** mcp-read advertises exactly the committed input schemas and validates asset-sim's answers
  as whole tool results; the worker lists the tools before it calls, compares the schemas with the same files, and
  validates every read result; anything else fails the run as "retrieval failed" (R029).

| Requirement | What its test shows |
|---|---|
| R028 | Alpha never reads B22 (refused before asset-sim, or asset-sim's own 404); a requester who lost the membership gets nothing from any of the three tools; the search keeps to the run's asset type and never returns a revoked procedure |
| R029 | An added or removed tool, an altered schema, an error-flagged, malformed or oversized result each fail the worker's call closed; the real server passes |

---

## Where the code will live (not yet written)
```

Edit 9 (`docs/PROJECT_HISTORY.md`, before the last section), replace:

```markdown
## 30. What the process taught
```

with:

```markdown
## 30. The read-tools plan gave mcp-read its asset half and the worker its checks

**Problem.** Plan M takes T16. mcp-read served one tool; `get_asset_status` and `get_recent_alerts` had neither a
definer nor a destination, asset-sim was a three-file stub, corpus-1's assets carried no status, the search stamped
`retrieved_at` from the wall clock and cut excerpts silently at 500 characters, nothing re-checked a requester's
membership at read time, and the worker called a tool without asking what the server offered or checking what came
back. The fact sheet found eighteen open questions; the controller's brief ruled on each, deferring vector mode to
T18.

**Change.** Revision 0012 with `asset_scope` and the re-created search (the requester re-check in both, the definer's
instant, the whole section as the excerpt); asset-sim as a seventh process deriving status and alerts from corpus-1
without changing it; the two asset tools behind two committed units and mcp-read's own token; the search on the run's
asset type; the committed schemas at run time on both sides of the boundary; and the worker's fail-closed discovery and
result checks.

**Review.** Writing the plan against the code moved four details: the search needs the run's scope too, so it runs
three units; the excerpt and instant change had to land with the revision, because the function's return type changed;
asset-sim's faults reused three existing hooks and added one, which changed the "no orphan hook" invariant; and the
worker's checks stay on the read calls, because mcp-write does not advertise the committed files. The plan was applied
task by task to a scratch copy of the tree, where every dev count was measured; the SQL and the live tests first run
at execution. <review>

## 31. What the process taught
```

- [ ] **Step 3: Final gates and the evidence**

With the dev stack up and every skeleton process down: `PYTHONUTF8=1 uv run python scripts/check.py` → `CHECK: GREEN`,
pytest `1341 passed, 205 skipped`; `PYTHONUTF8=1 uv run python scripts/check.py --profile test` → `CHECK: GREEN`,
pytest `1525 passed, 21 skipped` (or the measured counts; Step 4 writes what was measured); `uv run python -I
scripts/verify_handoff.py --reference-code --manifest --contracts` → exit 0. Then `git checkout -- reports/bootstrap
reports/skeleton reports/auth reports/admission reports/leases reports/events reports/outbox reports/mcp-write
reports/retrieval`, and keep, from this run, `reports/asset-sim/t16-asset-sim.txt`, `reports/mcp-read/t16-read-tools.txt`
and the two rewritten T15 files under `reports/mcp-read/` (their lines now name the three tools and the
`asset_scope` grant).

- [ ] **Step 4: Fill in the placeholders and commit**

Replace `<base>`, `<last>`, `<date>`, `<dev>` and `<live>` everywhere this task wrote them, and `<review>` in
`docs/PROJECT_HISTORY.md` with one sentence on the final review's outcome (or delete it when the review is still to
come). Check: `grep -rn "<base>\|<last>\|<date>\|<dev>\|<live>\|<review>" SESSION_STATE.md STATUS.md
docs/PROJECT_HISTORY.md` → no output. Tick this plan's checkboxes.

```bash
git add handoff/tasks.json handoff/acceptance-matrix.json handoff/BUILD_BACKLOG.md SESSION_STATE.md STATUS.md \
  docs/ARCHITECTURE.md docs/PROJECT_HISTORY.md reports/asset-sim reports/mcp-read \
  docs/superpowers/plans/2026-10-18-first-slice-m-read-tools-asset-sim.md
git commit -m "docs: close T16 - handoff records, acceptance rows, errata 103-106, the asset-sim runbook (Plan M)"
```

`git status --short` then shows only ` M docs/superpowers/research/2026-10-16-plan-k-inputs.md`, untouched.

---

## Review Focus

1. **The SQL has not run.** Revision 0012's two bodies were rendered, bind-scanned and reverse-checked against 0011 on
   the scratch copy, but no database executed them. `asset_scope` returns a TABLE whose column names (`run_id`,
   `tenant_id`, `asset_id`, `start_at`, `end_at`) are also columns of `runs`; every reference in its body is
   qualified (`r.`, `m.`, `v_run.`, `v_handle.`) so PL/pgSQL's name-conflict rule has nothing to refuse, but the first
   live run of `test_migration_0012_live.py` is the proof. The search body differs from 0011's by the five
   `CHANGES_0012` only (a unit test reverses them).
2. **The membership re-check changes who may read.** Any live test that calls a read definer for a run whose
   requester has no active requester row in the run's tenant now gets `INVALID_HANDLE`. Every such call site was
   checked (Writer departure 9): the random tenants of `test_migration_0011_live.py` get ALEX through
   `add_requester`, the baseline's beta run is riley's, and every other site uses alpha and ALEX. A live failure with
   "invocation handle rejected" in a test this plan did not touch is the first place to look.
3. **The run's asset type now filters every search through mcp-read.** A17 is a pump, so the R105 walking skeleton's
   search ("Investigate the alerts on Asset A17 …") returns pump and any-asset sections only. Its proposal needs at
   least one evidence reference; `ALPHA-ALERT-REVIEW` (any asset) is the section the T15 tests already find first
   for alert questions, so it should stand. If R105 ends INSUFFICIENT_EVIDENCE, the filter is working as ruled and the
   test's message, not the code, is what to discuss with the controller.
4. **R029 now guards the real worker.** The worker lists mcp-read's tools before its search; a mismatch between what
   mcp-read advertises and `schemas/tools/` (or a result outside the contract) fails the run as "retrieval failed".
   The unit test `test_the_advertised_schemas_are_the_committed_files_and_agree_with_the_argument_models` and the live
   R029 positive case pin the agreement; if R105 fails at retrieval, read the worker's log line (it names the check
   that failed, never a value).
5. **asset-sim's tokens.** The live DoD-2 test is the first time Keycloak's real tokens meet asset-sim's verifier
   (`aud` `asset-sim`, `azp` `ops-mcp-read`, `typ` `Bearer`); the realm already maps the audience
   (`tests/plan_b/test_realm_template.py:92`). `ops-view-users`' answer may be 401 or 403 (Writer departure 7).
6. **Clock moves in `test_mcp_read_t16_live.py`.** The A17 window is reached by moving the database clock back by
   about twelve days and reusing a handle minted under the real clock: its lease and its 60 seconds lie further
   ahead of a clock moved back, so `_resolve_handle` still accepts it; the clock is reset in `finally`. A failure
   there with "invocation handle rejected" means the handle aged out (the test took more than 60 seconds).
7. **Lock and mypy changes.** `uv.lock` changes twice (Tasks 2 and 3) with no version moving; `jsonschema` gets a mypy
   `ignore_missing_imports` override because 4.26 ships no `py.typed` (measured on this machine). If `uv lock
   --offline` cannot resolve, stop: a network resolution is not part of this plan.

## Self-review (run by the plan's author before execution)

- **Spec coverage.** Every ruling has its task (the "Rulings" list names it); every T16 debt line a-h of
  `tasks.json:772-780` is closed or re-homed: a (Tasks 1-3), b (ruling 1, erratum 103, Task 7's T18 note), c (ruling
  14, Task 7's review note), d (Task 5), e (Task 4), f (Tasks 1 and 4), g (Task 1), h (Task 1). DoD 1: cross-tenant
  asset reads denied (Tasks 2-3), unexpected tools and malformed results fail closed (Task 5); DoD 2 (Task 2's live
  test).
- **Signatures copied, not retyped.** Every regprocedure and type list in this plan was checked against
  `privileges.DEFINER_FUNCTIONS` and the SQL: `app.search_procedures_scoped(text, text, text, public.vector, text,
  integer, text)` (unchanged since 0011; Plan L's plan printed it wrong, this one copies it from
  `privileges.py:208-209`), `app.asset_scope(text, text)`, `app._resolve_handle(text, text, text)`; the unit test
  `test_both_functions_are_granted_to_mcp_read_alone_with_the_matrix_signatures` pins both against the matrix.
- **Measured, not assumed.** On the scratch copy: every new unit test failed first for the stated reason and passed
  after its step; ruff, ruff format and mypy strict were clean; the dev gate's counts are the ones above;
  `uv lock --offline` resolved 67 packages both times. Not measured: anything live (no database, Keycloak or service
  was reachable for the writer, by instruction).
- **Placeholders.** None in Tasks 1-6; Task 7's `<base>`, `<last>`, `<date>`, `<dev>`, `<live>` and `<review>` are
  filled by its Step 4, which greps for them.

# First Slice J: The Authenticated mcp-read, Its Token Verifier and Bound Invocation Handles (T15) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the existing mcp-read into T15's authenticated read server and prove every case its definition of done
names: a protocol-version guard that closes the SDK's legacy path on both MCP servers, a stricter access-token check,
a handle bound to its own run's open job and to the run states of its job type, a startup refusal on a database
without that binding, the worker's own client id on every handle it mints, and live evidence over HTTP and from an
independent process (T15; R025 and R131 read halves, R026, R027, R031 network half, R085).

**Architecture:** No new read tool and no new definer (ruling 1, 8, 9): `search_procedures` stays the one tool and
`mcp_read` keeps EXECUTE on `current_time` and `resolve_invocation`. A pure ASGI `ops_core.mcp_protocol.
ProtocolVersionGuard` sits in front of each server's SDK app and refuses, with HTTP 400 and JSON-RPC `-32022`, any POST
to `/mcp` that does not carry exactly `MCP-Protocol-Version: 2026-07-28`, before bearer auth runs. mcp-read's verifier,
built in one place (`read_verifier`) for production and the unit tests, requires the access token's `typ` claim
(`Bearer`); its SDK adapter refuses any token whose `aud` lacks the server's URL before it stamps the SDK's
`AccessToken.resource`, and the SDK's `validate_token_resource` is on as a second layer. Revision `0009_handle_binding`
re-creates `app._resolve_handle` with one statement changed (the handle's job must be its own run's and unfinished; an
exact downgrade re-runs 0007's body), and `persistence.allowed_tool` adds the run-state dimension of the AM-15 allowlist
in Python (erratum 19). mcp-read checks the stored body for that binding at start. Live tests drive the server
in-process over a real socket (handle, ACL and protocol cases) and as a child process reached by the official SDK client
(R025, R026).

**Tech Stack:** as Plan I; no new dependency. `mcp` 2.3.0 and `mcp-types` 2.3.0 (`Client`, `MCPServer`, the bearer
middleware, the 2026-07-28 ladder), Starlette 1.7 (`TestClient` on `httpx2`), `httpx2` 2.13 (`ASGITransport` for the
in-process official client), PyJWT 2.15, psycopg 3.3, PostgreSQL 17, Python 3.13.

**Spec:** `SPEC_AMENDMENTS.md` (OPS-BUILD-1.3.6) over `BUILD_SPEC.md`: AM-30 (SA:568-591, the protocol revision and
per-request version validation), AM-20.7 items 6 and 11 (SA:554-558, SA:566: audiences, the custom `TokenVerifier`,
the handle as a lookup key only), AM-15 (SA:327-358: tools, job types, run states, the envelope), AM-20.3's
`resolve_invocation`, `asset_scope` and `search_procedures_scoped` rows (SA:459-461) and AM-20.4's
`invocation_context` (SA:496); BS §9 (BS:344-374, workload identity and the handle) and §10 (BS:376-407). The fact sheet
`docs/superpowers/research/2026-10-15-plan-j-inputs.md` (cited "FS §n" / "FS Qn": T15 verbatim, the binding spec text,
the tree with path:line cites, the installed SDK's source, 25 open questions) and the controller's brief of 25 rulings
(cited "brief ruling n"; reproduced below with what this plan made of each) are the inputs. Earlier artefacts this plan
builds on: revisions 0001-0008, `ops_core.tokens`, `persistence`, `jobs`, `privileges`, mcp-read and mcp-write as
Plans D-I left them, the worker's handlers and MCP client, `scripts/skeleton.py`, `tests/e2e/` and the Plan C-I unit
tests.

## Global Constraints

Carried from Plan I's header (its text applies with "Plan I"/"T14" read as the plan that wrote it); the Plan J
additions below win where the two differ:

- **Debt before code (SA:698).** The Plan J debt list (below) is committed in Task 1 Step 1c before any code changes.
  Nothing not on the list may be shortcut; every line names its owning task.
- **Authority boundaries stay where the spec puts them.** `mcp_read` holds no table grant and EXECUTE on
  `current_time` and `resolve_invocation` only (SA:437, erratum 15; a live test in Task 3); no MCP server creates a
  job (Plan I's catalog test stays green); every refusal of a presented handle is one `INVALID_HANDLE` envelope with
  the one fixed message and never an `action_id` (SA:354-355; a call with no handle gets the same code with "missing
  invocation handle"); token refusals stay HTTP 401 at both MCP servers (Plan D ruling 25);
  **nothing here sends anything to an external system or a person** (BS:730).
- **Secrets** live only as files under `OPS_SECRETS_DIR`. No secret, token, raw handle, session id or password in an
  environment variable, a command line, a log line, an exception message, an assertion operand, an evidence file or a
  document. A test that checks a handle or token is absent from text binds the verdict to a boolean or a list of indexes
  first, so a failure never prints the value (pytest prints assertion operands). The one exception is pytest's
  captured-log report when the DEBUG log test fails: it prints the record that held the test handle (Task 3's docstring
  and the Self-review's known risks say so). The child process of Task 4 gets its secrets the way the skeleton's
  children do: the environment names the secrets directory, the files hold the values.
- **Clock.** Every lease, expiry and fence comparison in SQL uses `app.current_time()` (unchanged in 0009). A test that
  moves `app.test_clock` does so only while no other lease matters and resets it in `finally` (the offset is global).
- **One string per function**, binds and the ISC004 rule exactly as in Plan E; `tests/plan_e/test_transitions_table.py`
  scans every revision, 0009 included.
- **Live tests never touch the dev databases**, run against `ops_test`/`incident_test` under `PROFILE=test` through
  the existing `migrated`, `app_conn` and `role_conn` fixtures. A server a live test starts is stopped in `finally`:
  uvicorn in-process through `should_exit`, a child process through `terminate()` and, after 15 s, `kill()`.
- **Tests:** unit tests in `tests/plan_j/` (DB-free; added to `testpaths` in Task 1), live tests in `tests/e2e/` gated
  by `OPS_LIVE=1`; existing tests are updated in the task that changes the interface they pin, never deleted (Task 1
  edits four constructions of the worker's `Deps`; Task 2 edits two Plan D/E allowlist tests, the revision list, R105's
  replay step and the handle step of `tests/e2e/test_migrations_and_persistence.py::
  test_r006_populated_revision_1_database_upgrades_in_place`). No xfail or skip except the live gate (BS:597). No new
  test needs `slow_live`. A live test reads every backend pid before any transaction opens and never cancels a task that
  may be inside a database unit (Plan I round 1, B1 and M3); none of this plan's live tests runs two connections against
  one lock.
- **Comments** per `docs/CODE_COMMENTS.md`; ≤120 characters per line (the counting command below); no `type: ignore`;
  ruff + mypy strict clean; UTF-8 without BOM, LF; no `noqa`. No broad `except` is added.
- **Gates:** `uv run ruff format <files> && uv run ruff check --fix <files>` (then
  `uv run ruff check --select ISC004 --fix --unsafe-fixes migrations/app/versions/0009_handle_binding.py` after
  writing the revision), `PYTHONUTF8=1 uv run python scripts/check.py` GREEN after every task,
  `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts` exit 0, and the live suite
  `PYTHONUTF8=1 uv run python scripts/check.py --profile test` after every task that changes a migration, a service or
  a live test (Tasks 1-5). It needs the dev stack up and `uv run python scripts/skeleton.py status` showing every
  process down. After a live run: `git checkout -- reports/bootstrap reports/skeleton reports/auth reports/admission
  reports/leases reports/events reports/outbox` (all seven are rewritten by live runs; Task 5 commits the ones it
  names; `reports/mcp-read` is new and stays until Task 5). mypy's incremental cache can report spurious errors after
  many edits; rerun with `--no-incremental` before treating one as real.
- **Counting characters:** print every line over 120 characters in the given files; no output means they pass. It
  takes files, not directories.

  ```bash
  uv run python - <files> <<'EOF'
  import sys
  for path in sys.argv[1:]:
      for number, line in enumerate(open(path, encoding="utf-8"), start=1):
          if len(line.rstrip("\n")) > 120:
              print(path, number)
  EOF
  ```

- **Toolchain and locks:** everything through the locked environment from the repository root
  (`uv run python -m pytest …`, never a bare `pytest`); no `uv add`, no `uv lock`.
- **Never migrate the dev databases.** Nobody runs `scripts/skeleton.py migrate` or `up` against `ops`/`incident` in
  this plan; the live suite migrates its own test databases every session. Migrating the dev database to 0009 is an
  owner input recorded in Task 5; until then mcp-read joins the API, the sweeper, the worker and mcp-write in refusing
  to start on it, by design.
- **Commits:** one logical group per step that says "commit"; messages free of any attribution trailer (owner
  instruction); never push; never `docker compose down -v`; never change system settings; never drop a role,
  database, persona or Keycloak object (the test databases and the round trip's scratch database excepted).
- **No interim red across tasks.** Every task ends with both gates GREEN at the stated counts. The order is chosen for
  that: the guard and the verifier (Task 1) change no database contract; the run-state rule, the binding, R105's
  replay step and the startup check land together (Task 2), because each of them alone would leave a gate red.
- **Line numbers** in "Modify" lines are those of the file as the previous task left it (the current tree for a file
  no earlier Plan J task touched). Every replacement quotes the exact current text ("Edit n (`path`, …), replace:"
  then "with:"); a step that creates a file gives the whole file.
- **Counts.** Today (`afd7aaf`) the dev gate is `1032 passed, 154 skipped` and the live gate `1165 passed, 21 skipped`
  (133 live-gated tests). Task 1 Step 1a records both before any change; if either differs, every expected count below
  shifts by the same difference and the report says so. Every dev count below was measured by applying this plan to a
  scratch copy of `afd7aaf`; every live count is arithmetic (the dev count plus the live-gated tests, which are the
  dev run's skips minus the 21 that skip in both), because a dry run cannot run live steps (the permission policy
  refuses copying `.env` into a scratch tree). Each live step says so.

## Review Focus

1. **A replay of `create_incident` after its run's outcome** (the R105 step that minted a fresh execute handle for the
   finished execute job of a SUCCEEDED run and expected the recorded outcome). With the binding and the run-state
   rule, such a handle is refused before the grant, and the destination keeps its one incident; through the tool, a
   replay is answered only while the run is APPROVED or EXECUTING (the re-queue after a transport failure re-sends
   under the same action id). The stored-outcome branch of `execution.create_incident` is no longer reachable through
   the tool (its run is past EXECUTING), which production never needed: the worker skips the call past EXECUTING.
   Pinned in Task 2: R105's step asserts the `INVALID_HANDLE` refusal and the unchanged receipt; the R006 populated
   upgrade asserts the refusal of a migrated finished job, then reopens it; the exhaustive allowlist table admits
   `create_incident` in APPROVED and EXECUTING for an execute job (the tool path's re-send has no other test);
   `test_mcp_write_live.py`'s direct calls of `execution.create_incident`, unchanged, prove the execution layer's
   idempotency, not the tool's.
2. **The worker's real client meets the guard** on every POST it sends to either server. The SDK client pinned to
   2026-07-28 sends the header on each request; if any of its requests did not, every investigate and execute job
   would fail. Pinned in Task 1 (`test_the_official_client_lists_and_calls_through_the_guard`: the official client
   through the guard and the real bearer middleware, in-process) and live by R105 and Task 4 (the client against a
   child process).
3. **An unauthenticated probe** must learn nothing about tokens from the version rule, and a valid token must not be
   able to skip it. Pinned in Task 1 (`test_the_version_rule_comes_before_authentication`: no header and no token is
   400, the right header and no token is 401) and Task 3 (the four raw POSTs with a valid worker token).
4. **A handle in a log.** The guard, the SDK, uvicorn, httpx2 and `persistence` all log around a call that carries
   `X-Ops-Invocation`; none may record it at DEBUG, with no redaction filter installed. Pinned in Task 3
   (`test_r027_no_log_record_carries_the_handle`: the server runs with uvicorn at DEBUG and its loggers propagating,
   every record of an answered call, a refused call and a refused raw POST is captured, and the test fails unless
   uvicorn, SDK and client records are among them), Task 2 (the allowlist's refusal log line) and, more weakly, Task 4
   (the child process's own log, written through its redaction filter). uvicorn's TRACE level logs request headers
   and is enabled nowhere (`serve_app` pins "warning"); the runbook says never to use it.
5. **A database that predates the binding.** mcp-read must refuse to start on it (the dev database is at 0005 today),
   and a database at 0009 must start. Pinned in Task 2 (`test_mcp_read_startup.py` both ways, and the live round trip
   that runs the same check against the database downgraded to 0008 and back).

## Rulings (the brief's 25, as this plan implements them)

The controller's brief decided these; executors do not re-litigate them. Each line says where the plan implements the
ruling and, where the plan had to refine one against the code, says how (all refinements are repeated under
"Rulings needing controller attention").

1. **Scope** — hardening plus evidence over the existing mcp-read: the run-state allowlist and the job binding
   (Task 2), the version guard (Task 1), the stricter verifier (Task 1), the startup guard (Task 2), the workload azp
   at mint (Task 1) and live tests for every DoD case (Tasks 2-4). No new read tool.
2. **Verifier** — `McpVerifier` answers `None` (the SDK's 401) when the verified audiences lack this server's resource
   URL and stamps `AccessToken.resource` only then; that check is what refuses. `validate_token_resource=True` is a
   second layer, which cannot fire while the stamp is the server's own URL, pinned by a unit test so it cannot be
   switched off unnoticed. `TokenVerifier` gains a `token_type` knob for the `typ` *claim*, and `read_verifier`, the one
   constructor `production_app` and the unit tests share, passes `"Bearer"` (Task 1, unit tests for the pass and the
   refusals through the real wiring). The verifier stays per service; mcp-write's change is a debt line (T47).
   Refined (b).
3. **Resource-server requirements** — the SDK's protected-resource metadata route stays (a Task 1 unit test reads it);
   one sentence in the runbook (Task 5); no erratum.
4. **Protocol version** — `ops_core.mcp_protocol.ProtocolVersionGuard`, mounted in front of the SDK app in both
   servers' `build_app` (Task 1): a POST to `/mcp` without exactly one `MCP-Protocol-Version: 2026-07-28` is HTTP 400
   with a constant JSON-RPC body, code `-32022`, no echo; health and metadata untouched; the guard refuses before
   auth (the runbook says an unauthenticated client learns only the version rule). Erratum 73. Refined (e).
5. **Mismatch tests** — raw `httpx2` POSTs with a valid worker token: header absent and header `2025-11-25` → the
   guard's 400/-32022; header 2026-07-28 with `_meta` 2025-11-25 → the SDK's 400/-32020; the matching request → 200
   (Task 3 live; the same four in-process in Task 1 with a stub key source).
6. **Allowlist and handle binding** — `allowed_tool(job_type, run_state, tool)` also requires `run_state ∈
   JOB_RULES[job_type].run_states`, refusing with the same `HandleRejected` (Task 2); revision `0009_handle_binding`
   re-creates `_resolve_handle` with the job read bound to `jobs.run_id = ic.run_id AND jobs.done_at IS NULL`, exact
   downgrade to 0008 by re-running 0007's body (Task 2); the R006 populated upgrade's migrated finished job is
   refused, then reopened (Task 2 Step 5). Erratum 75. Refined (a).
7. **Attempt state** — no call site today needs the attempt-state parameter, so the shared function does not gain it;
   `jobs.JobRule`'s `TODO(T15)` becomes a `TODO(T47)` (Task 2) and the write rule is a debt line. Erratum 76.
8. **Tools** — only `search_procedures` is registered; DoD 1 is met by `list_tools` + `call_tool` of it (Task 4).
9. **`search_procedures_scoped`, `asset_scope`** — not created; debt lines to T16 and T17/T16; the fixture corpus
   stays; the two `TODO(T15)` markers on the `vector_exact` translation become `TODO(T16)` (Task 5 Step 1).
10. **R131 read half** — the live ACL test (Task 3): `mcp_read`'s EXECUTE set equals `{current_time,
    resolve_invocation}`, every other definer exists and is not executable by it, and an attempted `grant_execution`
    fails `42501`; a recover and an execute handle at mcp-read and a lying stored `server` column are refused over HTTP.
    Erratum 72. Refined (f).
11. **R027 / DoD 2 handle cases** — live at HTTP (Task 3): another run's job (the superuser rewrites the handle's
    `job_id`), expired (the test clock 120 s ahead, reset in `finally`), a lapsed lease, a moved fence, released
    (revoked); the same handle answers between causes. Other-azp at the definer (the existing
    `test_definers_write_path_live.py` case, cited) and at the verifier (unit, `azp=ops-mcp-read` and `ops-web`
    synthetic tokens). "Handle absent from logs": every record of the exchange with uvicorn and the server at DEBUG and
    no redaction filter (Task 3), and the child's log written through its filter (Task 4). "Absent from the model": a
    unit test pins `DraftRequest`'s four fields (Task 1). Refined (d).
12. **Independent-process client** — `python -m ops_mcp_read` as a child process on a free loopback port with
    `scripts.skeleton.process_environment()` plus the port; the official SDK `Client` from the test lists exactly
    `search_procedures` and calls it with a valid handle; terminated in `finally` (Task 4). mcp-write's half → T47.
13. **Error envelopes** — unchanged: one `INVALID_HANDLE` envelope for every handle refusal (asserted field by field in
    Task 3), 401 for every token refusal; distinguishing 401 in the worker → T20 (debt line).
14. **Browser token** — live: the `ops-dev-direct` persona token (aud `ops-api`) is the stand-in, on a `tools/call`
    with a valid handle (Task 4); unit: the synthetic `azp=ops-web` token (Task 1); the evidence and erratum 81 say no
    real `ops-web` access token is minted.
15. **Missing aud** — the synthetic-JWKS case at mcp-read's configuration (Task 1) is the evidence; erratum 81.
16. **TLS and hosts** — debt line to T30.
17. **Worker client** — `handlers.Deps.workload_azp` (required), filled from `WorkloadTokenSource.client_id` in
    `main`; both mints use it (Task 1); discovery and schema checks → T16, `resume_input` → T20 (debt lines). Refined
    (g).
18. **Startup guard** — mcp-read asserts the clock profile and then that `app._resolve_handle`'s stored body carries
    0009's binding (`persistence.assert_function_text`, Task 2). Refined (c).
19. **Reads and the fence** — accepted as is; erratum 80.
20. **Arguments** — untouched; debt line to T16/T17.
21. **azp binding** — covered by ruling 17; the write-path definers' literal `'ops-worker'` → T47 (debt line).
22. **R085 "worker-chosen tools ignored"** — a tool name mcp-read does not register is the SDK's unknown-tool error, an
    investigate handle once its run awaits input is refused, and the lying `server` column is refused (Task 3); the
    tool-and-state table is exhaustive in the unit test (Task 2).
23. **Matrix bookkeeping** — R026, R027 and R085 marked implemented and evidenced; R025, R031 and R131 keep
    `NOT_IMPLEMENTED_OR_NOT_TARGET_VERIFIED` with their read or network half evidenced and named in the note; evidence
    under `reports/mcp-read/`; unit tests in `tests/plan_j/` (Task 5). Refined (i).
24. **Odd cross-references** — errata 77 (SA:459's row as amended), 78 (SA:34) and 79 (BS:360).
25. **Layout** — `tests/plan_j` and `tests/e2e`; per-service `tests/` and a Dockerfile → T30 (debt line).

### Rulings needing controller attention

None of the 25 is impossible against the code. These refinements keep each ruling's intent and are flagged so the
controller can overrule them before execution:

- **(a) Ruling 6 breaks one step of R105, which this plan rewrites.** `tests/e2e/test_r105_walking_skeleton.py:210-238`
  mints a fresh execute handle for the run's *finished* execute job after the run SUCCEEDED and asserts mcp-write
  answers the recorded outcome (Plan D review focus 1 and 3). Under ruling 6 that handle is refused twice over: its job
  is done (0009) and SUCCEEDED is not one of the execute job's run states (`allowed_tool`). Task 2 changes the step to
  assert the `INVALID_HANDLE` refusal and the destination's unchanged receipt (no second incident), and its evidence
  line to `replay=refused_finished_job`. The same binding refuses the R006 populated upgrade's migrated finished job,
  so that test asserts the refusal and then reopens the job (round 1, B1). Through the tool, a replay is answered only
  while the run is APPROVED or EXECUTING; `execution.create_incident`'s stored-outcome branch remains reachable by
  direct callers (`tests/e2e/test_mcp_write_live.py`, which proves the execution layer, not the tool) and its module
  docstring says so (Task 2 Step 5). Smallest alternative: keep the binding for read handles only (`p_server =
  'read'` in the new condition) and apply the run-state rule to read job types only, so a post-outcome replay at
  mcp-write still answers.
- **(b) Ruling 2's `typ` is a claim, not the header.** Keycloak writes `"typ": "Bearer"` into the access token's
  payload (`reports/bootstrap/keycloak-claims.txt`), while `TokenVerifier`'s existing `typ` knob compares the JOSE
  header's `typ` (Keycloak's is `JWT`; the knob exists for logout tokens, `logout+jwt`). The plan adds a separate
  `token_type` knob that compares the claim. Smallest alternative: none needed; reusing `typ` would refuse every
  Keycloak access token.
- **(c) Ruling 18: no relation and no readable `alembic_version`.** 0009 re-creates a function, so `assert_relation`
  has nothing to find, and `mcp_read` holds no table grant (SA:437), so it cannot read `alembic_version`. The plan adds
  `persistence.assert_function_text(conn, signature, marker)`: `strpos(pg_proc.prosrc, marker)` for
  `app._resolve_handle(text, text, text)` (the catalog is readable by every role), the marker being 0009's bound
  condition, which a unit test shows no earlier body carries. Smallest alternative: 0009 also creates an empty marker
  relation for `assert_relation`, at the cost of an object with no other purpose.
- **(d) Ruling 11's "replayed after release".** A real `release_lease` both revokes the handles and finishes the job,
  so the refusal would have two causes. The HTTP test revokes with `revoke_handles` at the lease's fence (what the
  release does first) and proves the finished-job refusal separately (Task 2's live binding test). Smallest
  alternative: call `release_lease` and accept the doubled cause.
- **(e) Ruling 4's body and a doubled header.** The guard does not read the body, so its JSON-RPC error carries `"id":
  null` (JSON-RPC 2.0 allows it when the id cannot be determined); the body is one constant, `{"jsonrpc":"2.0",
  "id":null,"error":{"code":-32022,"message":"Unsupported protocol version","data":{"supported":["2026-07-28"]}}}`, so
  nothing sent is echoed. A request carrying the header twice is refused even if one copy is right, because the SDK
  could read the other. Smallest alternative: none needed.
- **(f) Ruling 10's "every write-path function".** The live test asserts non-execution for every `app` function but
  `current_time` and `resolve_invocation` (run-path definers and helpers included), which contains the write path and
  is stronger. Smallest alternative: list the six write-path functions by name.
- **(g) Ruling 17's field is required.** `handlers.Deps.workload_azp` has no default (a default would keep the literal),
  so Task 1 adds `workload_azp="ops-worker"` to the four `Deps(...)` constructions in tests. The worker's client also
  takes the pinned version from `ops_core.mcp_protocol.PROTOCOL_VERSION` instead of its own literal (same value; one
  place to change it).
- **(h) `SESSION_STATE.md` lost a heading.** Plan I's close-out inserted its "Plan I executed" section in place of the
  `## Walking-skeleton debt list (T08; committed before coding) [R6-B7]` heading without repeating it (the heading is in
  `4aa5f92` and absent at `afd7aaf`), so the T08 list now reads as part of Plan I's section. Task 5 inserts Plan J's
  section and the heading back in one edit.
- **(i) Ruling 23: the partial rows' statuses.** R025, R031 and R131 keep `implementation_status
  NOT_IMPLEMENTED_OR_NOT_TARGET_VERIFIED` (their targets name mcp-write, or T04's import half) and get `evidence_status
  RECORDED_LOCALLY_LIVE` with the read or network half named in the note, as the matrix has no partial status.
  Smallest alternative: leave them `NOT_RUN` and put the evidence in the notes only.

## Declared debt and errata

### Debt list (committed in Task 1 Step 1c, before coding)

Inserted into `SESSION_STATE.md` as a new section `## Plan J debt list (T15; committed before coding) [R6-B7]`
immediately after the `## Plan I debt list …` section (before `## Environment (observed)`); the exact text is Task 1
Step 1c's Edit 1.

### Errata proposed to the owner (numbered on from Plan I's 71)

The spec text stays authoritative until the owner decides; each line names the text it amends. The full wording is
Task 5 Step 3's "Plan J executed" block; in short:

72. **R131 and SA:400/SA:459's function set**: `mcp_read` executes `current_time` (erratum 15) and
    `resolve_invocation` today; `asset_scope` (T16) and `search_procedures_scoped` (T17/T16) join with their owners.
73. **SA:571-572 and BS:378**: both MCP servers refuse a POST to `/mcp` without exactly `MCP-Protocol-Version:
    2026-07-28` (HTTP 400, `-32022`) before authentication; the SDK's legacy stateless path is closed; a header/`_meta`
    mismatch is the SDK's `HEADER_MISMATCH` (400, `-32020`).
74. **SA:557**: mcp-read also requires the access token's `typ` claim `Bearer`, and its SDK adapter refuses a token
    whose `aud` lacks the server's URL before it stamps the SDK's resource (the SDK's own resource check is a second
    layer); every refusal stays 401 (mcp-write follows in T47).
75. **SA:459 and SA:496**: `_resolve_handle` resolves a handle only for its own run's unfinished job.
76. **SA:338 and T15 review note 2**: the run-state dimension of the allowlist is checked in Python at the start of
    every MCP call (`persistence.resolve_invocation`), not in the definers' own resolutions; the attempt-state
    dimension is mcp-write's (T47).
77. **SA:459's row as amended**: lock `run_lease FOR SHARE` only (erratum 53); returns `run_id, job_id, job_type,
    tenant_id, conversation_id, run_state, attempt_state` (erratum 19); the binding of erratum 75.
78. **SA:34 (AM-00 §9)**: the audience wording is replaced by AM-20.7 item 6, not AM-20.6.
79. **BS:360**: there is no handle refresh; one handle per call, 60 s, bound at use to the lease (erratum 58).
80. **SA:460-461 with SA:176-184**: a read is served after the handle resolved in its own committed unit; a fence that
    moves meanwhile cannot cause a write, and the worker's next fenced unit fails.
81. **SA:558**: the missing-`aud` and browser-token cases are synthetic-key unit tests at mcp-read's configuration;
    live, a persona token stands in for the browser's, since no `ops-web` access token is minted anywhere.

## File structure

- `core/src/ops_core/mcp_protocol.py` (new, Task 1): `PROTOCOL_VERSION`, `UNSUPPORTED_PROTOCOL_VERSION`, `REFUSAL`,
  `route_path`, `ProtocolVersionGuard`.
- `core/src/ops_core/tokens.py` (Task 1): `TokenVerifier(token_type=…)`, `WorkloadTokenSource.client_id`.
- `mcp-read/src/ops_mcp_read/server.py` (Tasks 1, 2): the docstring, `McpVerifier`'s audience check,
  `validate_token_resource=True`, the guard's mount, `read_verifier` (with `token_type="Bearer"`); `HANDLE_BINDING`
  and the startup check.
- `mcp-write/src/ops_mcp_write/execution.py` (Task 2): the replay rule in its module docstring.
- `mcp-write/src/ops_mcp_write/server.py` (Task 1): the guard's mount.
- `worker/src/ops_worker/handlers.py`, `main.py`, `mcp.py` (Task 1): `Deps.workload_azp`, the two mints, the pinned
  version from core.
- `core/src/ops_core/persistence.py` (Task 2): `allowed_tool(job_type, run_state, tool)`, `resolve_invocation`,
  `assert_function_text`. `core/src/ops_core/jobs.py` (Task 2): `JobRule`'s docstring.
- `migrations/app/versions/0009_handle_binding.py` (new, Task 2).
- Tests: `tests/plan_j/` (`__init__.py`, `test_protocol_guard.py`, `test_verifier_t15.py`, `test_mcp_read_http.py`,
  `test_worker_azp.py`, `test_allowlist.py`, `test_migration_0009.py`, `test_mcp_read_startup.py`); `tests/e2e/`
  (`test_migration_0009_live.py`, `test_mcp_read_t15_live.py`, `test_mcp_read_process_live.py`); edits to
  `tests/plan_d/test_persistence_pure.py`, `tests/plan_e/test_persistence_errors.py`,
  `tests/plan_e/test_transitions_table.py`, `tests/plan_h/test_worker_units.py`, `tests/plan_f/test_grant_deferred.py`,
  `tests/plan_b/test_evidence.py`, `tests/e2e/test_heartbeat_live.py`, `test_worker_live.py`,
  `test_r105_walking_skeleton.py`, `test_migrations_and_persistence.py`.
- Documentation (Task 5): `handoff/*`, `SESSION_STATE.md`, `STATUS.md`, `docs/ARCHITECTURE.md`,
  `docs/runbooks/mcp-read.md` (new), `docs/PROJECT_HISTORY.md`, `README.md`, `mcp-read/README.md`,
  `mcp-write/README.md`, `worker/README.md`; the two `TODO(T15)` markers in `core/src/ops_core/routing.py` and
  `scripts/build_schemas.py`, and two skip reasons in `tests/plan_c/test_schema_conformance.py`.

## Task overview

- **Task 1:** the debt list; the protocol-version guard on both servers; mcp-read's verifier; the workload azp at
  mint; `tests/plan_j`. Tests: `test_protocol_guard.py` 8, `test_verifier_t15.py` 10, `test_mcp_read_http.py` 4,
  `test_worker_azp.py` 3. Dev gate after: 1057 passed, 154 skipped; live 1190/21 (arithmetic).
- **Task 2:** the run-state allowlist, revision 0009, the startup check, R105's replay step, the R006 populated
  upgrade's handle step, `execution.py`'s replay docstring. Tests: `test_allowlist.py` 6, `test_migration_0009.py` 5,
  `test_mcp_read_startup.py` 2, the transitions module +1 (parametrised); live `test_migration_0009_live.py` 3. Dev
  1071/157, live 1207/21 (arithmetic).
- **Task 3:** the handle, allowlist, ACL, protocol and log cases at mcp-read over HTTP. Tests: live
  `test_mcp_read_t15_live.py` 5. Dev 1071/162, live 1212/21 (arithmetic).
- **Task 4:** the independent process and the foreign tokens. Tests: live `test_mcp_read_process_live.py` 2. Dev
  1071/164, live 1214/21 (arithmetic).
- **Task 5:** handoff records, acceptance rows, errata 72-81, runbook, history, READMEs, the `TODO(T15)` markers,
  final gates. No tests.

The arithmetic, once: dev passed 1032 + 25 (Task 1: 8 + 10 + 4 + 3) = 1057, + 14 (Task 2: 6 + 5 + 2 + 1) = 1071, + 0
(Tasks 3 and 4) = 1071; dev skipped 154, + 3 = 157, + 5 = 162, + 2 = 164. The live gate's passed count is the dev count
plus the live-gated tests (the dev skips minus the 21 that skip in both gates: 133 today; 133, 136, 141, 143 after
Tasks 1-4), so 1190, 1207, 1212, 1214, always with 21 skipped. The dev numbers were measured on a scratch copy; the
live ones are not measured (see "Counts").

---

### Task 1: Debt before code — the protocol-version guard, mcp-read's verifier, the workload azp at mint

**Files:**
- Create: `core/src/ops_core/mcp_protocol.py`, `tests/plan_j/__init__.py`, `tests/plan_j/test_protocol_guard.py`,
  `tests/plan_j/test_verifier_t15.py`, `tests/plan_j/test_mcp_read_http.py`, `tests/plan_j/test_worker_azp.py`
- Modify: `SESSION_STATE.md:719` (new debt section before `## Environment (observed)`), `pyproject.toml:48-51`
  (`testpaths`), `core/src/ops_core/tokens.py:86-92`, `:101`, `:164-165`, `:222-225`,
  `mcp-read/src/ops_mcp_read/server.py:3-4` (docstring), `:29`, `:114-135` (`McpVerifier`), `:191-198`, `:239-241`,
  `:244-252` (`production_app`, and the new `read_verifier` before it), `mcp-write/src/ops_mcp_write/server.py:26`,
  `:264-266`, `worker/src/ops_worker/handlers.py:52-59` (`Deps`), `:109-111`, `:223-225`,
  `worker/src/ops_worker/main.py:156`, `worker/src/ops_worker/mcp.py:14`, `:64`,
  `tests/plan_h/test_worker_units.py:185-187`, `tests/plan_f/test_grant_deferred.py:98`,
  `tests/e2e/test_heartbeat_live.py:98`, `tests/e2e/test_worker_live.py:97-98`

**Requirements:** AM-30's per-request version (SA:571-572, ruling 4); SA:557-558's checks at mcp-read (ruling 2,
14, 15); the handle bound to the validated workload client (BS:360, ruling 17); the Plan J debt list (SA:698).

**Interfaces:**
- Consumes: `ops_core.tokens.TokenVerifier`, `Principal`, `TokenRejected`, `WorkloadTokenSource`;
  `ops_mcp_read.server.State`, `build_server(state, *, issuer, resource_url)`, `build_app(server, state)`,
  `procedures.load_corpora`; `ops_mcp_write.server.State`, `build_server`, `build_app`; Plan D's synthetic key pair
  (`tests.plan_d.test_tokens.ISSUER`, `AUDIENCE`, `JWK1`, `mint`); Plan H's worker fakes
  (`tests.plan_h.test_worker_units.JOB`, `RUN`, `Log`, `make`, `patch`).
- Produces: `ops_core.mcp_protocol.PROTOCOL_VERSION = "2026-07-28"`, `UNSUPPORTED_PROTOCOL_VERSION = -32022`, `REFUSAL:
  bytes`, `route_path(scope) -> str`, `ProtocolVersionGuard(app, *, path="/mcp")`; `TokenVerifier(..., token_type: str |
  None = None)` (compares the `typ` claim); `WorkloadTokenSource.client_id -> str`;
  `ops_mcp_read.server.read_verifier(kc: settings.Keycloak, urls: settings.Urls) -> TokenVerifier` (the one
  `production_app` and the unit tests use); `handlers.Deps.workload_azp: str` (required, after `worker_name`); in
  `tests.plan_j.test_mcp_read_http`: `FIXTURES`, `ISSUER`, `RESOURCE`, `BASE`, `TOOLS_LIST`, `SEARCH`, `SEARCH_CALL`,
  `KeyedVerifier`, `read_app()`, `headers(...)`, `official_client(app)` (Task 2's startup test imports `FIXTURES`,
  `ISSUER`, `RESOURCE`, `KeyedVerifier`).

- [x] **Step 1a: Record both baselines**

Run `PYTHONUTF8=1 uv run python scripts/check.py` → `CHECK: GREEN` with pytest `1032 passed, 154 skipped`; with the
dev stack up and `uv run python scripts/skeleton.py status` showing every process down, run
`PYTHONUTF8=1 uv run python scripts/check.py --profile test` → `CHECK: GREEN` with `1165 passed, 21 skipped`, then
`git checkout -- reports/bootstrap reports/skeleton reports/auth reports/admission reports/leases reports/events
reports/outbox`. Record both lines in the report (Global Constraints, "Counts"). A gate that is not GREEN stops the
plan here, before anything is committed.

- [x] **Step 1b: Record the base**

Run `git rev-parse --short HEAD` and write the hash it prints as `BASE=<hash>` in the report and in the SDD ledger
(`.superpowers/sdd/2026-10-15-first-slice-j-mcp-read-verifier-handles/progress.md`). Task 5's commit span is
`<base>..<last>`.

- [x] **Step 1c: Commit the debt list (before any code)**

Edit 1 (`SESSION_STATE.md`, the heading after the Plan I debt list), replace:

```markdown
## Environment (observed)
```

with:

```markdown
## Plan J debt list (T15; committed before coding) [R6-B7]

Allowed shortcuts in T15, each with its owning task:
- mcp-write's verifier keeps stamping its own resource whatever `aud` holds, leaves `validate_token_resource` off and
  does not require the `typ` claim `Bearer` (mcp-read does all three, Plan J ruling 2) → T47;
- the write-path definers (`grant_execution`, `lookup_action`, `mark_sent`, `record_outcome`) call `_resolve_handle`
  with a literal `'ops-worker'` instead of the presented token's `azp` (`resolve_invocation` compares the real one
  first, so a mismatch is refused there) → T47;
- the attempt-state dimension of the allowlist (`create_incident` only while the attempt is absent or INTENT, not
  cancelled, before the deadline; T15 review note 2) stays in mcp-write's `execution.next_step` → T47 (recover: T22);
- mcp-write's half of R025 (an independent client lists and calls mcp-write) and of R131 (`mcp_exec`'s function set, a
  read handle at mcp-write) → T47;
- `asset_scope`, `get_asset_status`, `get_recent_alerts` and asset-sim → T16; `search_procedures_scoped`, the governed
  store and the `vector_exact` → `mode=vector` translation by its caller → T17/T16; `search_procedures` stays lexical
  over `data/handoff-fixtures/` (Plan J rulings 8, 9);
- mcp-read's tool arguments (the optional `asset_type`), the order of its `UNSUPPORTED_MODE` check and its fallback
  `corpus_version` → T16/T17 (ruling 20);
- the worker's client does no tool discovery and no result-schema check (R029) → T16; it does not tell a 401 from
  other transport failures (both become "retrieval failed" or a re-queue) → T20; it holds no `resume_input` handle →
  T20;
- TLS outside localhost, and container host names (the SDK's DNS-rebinding allowed hosts; audience URLs that equal the
  listen URLs) → T30 (ruling 16);
- mcp-read has no `tests/` directory and no Dockerfile of its own (AM-01) → T30 (ruling 25);
- the dev database stays at revision 0005 until the owner migrates it (0006, 0007, 0008 and 0009 pending); until then
  the API, the sweeper, the worker, mcp-write and now mcp-read refuse to start on it → owner input.

## Environment (observed)
```

```bash
git add SESSION_STATE.md
git commit -m "docs: declare Plan J's shortcuts before coding (T15 debt list)"
```

- [x] **Step 2: Put `tests/plan_j` on the test path**

Edit 1 (`pyproject.toml`, `testpaths`), replace:

```toml
testpaths = [
  "tests/plan_a", "tests/plan_b", "tests/plan_c", "tests/plan_d", "tests/plan_e", "tests/plan_f", "tests/plan_g",
  "tests/plan_h", "tests/plan_i", "tests/e2e",
]
```

with:

```toml
testpaths = [
  "tests/plan_a", "tests/plan_b", "tests/plan_c", "tests/plan_d", "tests/plan_e", "tests/plan_f", "tests/plan_g",
  "tests/plan_h", "tests/plan_i", "tests/plan_j", "tests/e2e",
]
```

Create `tests/plan_j/__init__.py`:

```python
"""Plan J (T15): mcp-read's verifier, protocol-version guard and handle binding, without a database."""
```

- [x] **Step 3: Write the failing guard test**

Create `tests/plan_j/test_protocol_guard.py`:

```python
"""The protocol-version guard on its own, as an ASGI app around a recording inner app (AM-30, Plan J ruling 4).

Catches: a POST to the MCP path without `MCP-Protocol-Version`, or with a handshake-era or doubled value, reaching the
SDK (whose legacy stateless path checks no version); a refusal that echoes the value it was sent; a guard that also
blocks health, metadata or a GET the SDK answers itself; a guard mounted under a prefix that stops matching; and the
pinned version or error code drifting from the installed SDK's.
"""

import asyncio
import json
from typing import Any

import pytest
from mcp_types.jsonrpc import UNSUPPORTED_PROTOCOL_VERSION as SDK_UNSUPPORTED
from mcp_types.version import MODERN_PROTOCOL_VERSIONS
from ops_core.mcp_protocol import PROTOCOL_VERSION, REFUSAL, UNSUPPORTED_PROTOCOL_VERSION, ProtocolVersionGuard


class Inner:
    """The SDK's place: records each scope it is handed and answers 200."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        self.seen.append(scope["path"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"inner"})


def call(
    guard: ProtocolVersionGuard, method: str, path: str, headers: list[tuple[bytes, bytes]], root: str = ""
) -> Any:
    """One request through the guard; the messages it sent back."""
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"{}", "more_body": False}

    async def send(message: Any) -> None:
        sent.append(dict(message))

    scope = {"type": "http", "method": method, "path": path, "root_path": root, "headers": headers}
    asyncio.run(guard(scope, receive, send))
    return sent


def test_the_pinned_values_are_the_installed_sdks() -> None:
    assert MODERN_PROTOCOL_VERSIONS == (PROTOCOL_VERSION,)
    assert UNSUPPORTED_PROTOCOL_VERSION == SDK_UNSUPPORTED
    body = json.loads(REFUSAL)
    assert body["error"]["code"] == SDK_UNSUPPORTED and body["error"]["data"] == {"supported": ["2026-07-28"]}


@pytest.mark.parametrize(
    "headers",
    [
        [],  # no header: the SDK's legacy stateless path
        [(b"mcp-protocol-version", b"2025-11-25")],  # a handshake-era version
        [(b"mcp-protocol-version", b"2024-11-05")],
        [(b"mcp-protocol-version", b"2026-07-28 ")],  # not the pinned value byte for byte
        [(b"mcp-protocol-version", b"2026-07-28"), (b"mcp-protocol-version", b"2025-11-25")],  # two copies
    ],
    ids=["absent", "2025-11-25", "2024-11-05", "padded", "doubled"],
)
def test_a_post_without_exactly_the_pinned_version_is_refused_before_the_sdk(
    headers: list[tuple[bytes, bytes]],
) -> None:
    inner = Inner()
    sent = call(ProtocolVersionGuard(inner), "POST", "/mcp", headers)
    assert inner.seen == []
    assert sent[0]["status"] == 400 and (b"content-type", b"application/json") in sent[0]["headers"]
    assert sent[1]["body"] == REFUSAL  # one constant body: the value that was sent is never echoed


def test_everything_else_passes_untouched() -> None:
    inner = Inner()
    guard = ProtocolVersionGuard(inner)
    assert call(guard, "POST", "/mcp", [(b"mcp-protocol-version", b"2026-07-28")])[0]["status"] == 200
    assert call(guard, "GET", "/mcp", [])[0]["status"] == 200  # the SDK answers a GET itself (405)
    assert call(guard, "POST", "/health/ready", [])[0]["status"] == 200
    assert call(guard, "GET", "/.well-known/oauth-protected-resource/mcp", [])[0]["status"] == 200
    assert inner.seen == ["/mcp", "/mcp", "/health/ready", "/.well-known/oauth-protected-resource/mcp"]


def test_a_guard_mounted_under_a_prefix_still_matches_its_path() -> None:
    inner = Inner()
    assert call(ProtocolVersionGuard(inner), "POST", "/read/mcp", [], root="/read")[0]["status"] == 400
    assert inner.seen == []
```

Run: `uv run python -m pytest tests/plan_j/test_protocol_guard.py -q`
Expected: `1 error in` (collection stops: `ModuleNotFoundError: No module named 'ops_core.mcp_protocol'`).

- [x] **Step 4: The guard**

Create `core/src/ops_core/mcp_protocol.py`:

```python
"""The protocol-version rule both MCP servers enforce before the SDK sees a request (AM-30, SA:571; Plan J ruling 4).

The pinned revision, 2026-07-28, is session-less: every request carries its version in the `MCP-Protocol-Version`
header and in `params._meta`, and the SDK compares the two. But the SDK sends a POST that has no such header, or a
handshake-era one (2024-11-05 to 2025-11-25), down its legacy stateless path, where no per-request version is checked.
`ProtocolVersionGuard` closes that path: a POST to the MCP endpoint must carry exactly one header, equal to the pinned
version, or it is answered HTTP 400 with a JSON-RPC error before the SDK, and so before bearer auth, runs. An
unauthenticated client therefore learns this rule and nothing about its token. The value sent is never echoed. Every
other request (health, the protected-resource metadata, a GET or DELETE the SDK answers itself) passes untouched, and
a request whose header is right but whose `_meta` disagrees is the SDK's own HEADER_MISMATCH.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any, Final

PROTOCOL_VERSION: Final = "2026-07-28"  # AM-30; the worker's client pins the same (ops_worker.mcp)
# The 2026-07-28 code for "unsupported protocol version" (mcp_types.jsonrpc; a unit test compares the two). Core does
# not depend on the SDK, so the value is copied here.
UNSUPPORTED_PROTOCOL_VERSION: Final = -32022
HEADER: Final = b"mcp-protocol-version"  # ASGI header names arrive lower-case

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

REFUSAL: Final = json.dumps(
    {
        "jsonrpc": "2.0",
        "id": None,  # the body is not read, so the request id is unknown (JSON-RPC 2.0 allows null here)
        "error": {
            "code": UNSUPPORTED_PROTOCOL_VERSION,
            "message": "Unsupported protocol version",
            "data": {"supported": [PROTOCOL_VERSION]},
        },
    },
    separators=(",", ":"),
).encode("utf-8")


def route_path(scope: Scope) -> str:
    """The request path below the mount point (Starlette's rule): a guard mounted under a prefix still matches."""
    path: str = scope["path"]
    root: str = scope.get("root_path", "")
    if root and path.startswith(root) and path[len(root) :].startswith("/"):
        return path[len(root) :]
    return path


class ProtocolVersionGuard:
    """Refuse a POST to the MCP path that does not carry exactly `MCP-Protocol-Version: 2026-07-28`."""

    def __init__(self, app: ASGIApp, *, path: str = "/mcp") -> None:
        """Wrap the SDK's app; `path` is the streamable HTTP endpoint it serves."""
        self._app = app
        self._path = path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] == "POST" and route_path(scope) == self._path:
            sent = [value for name, value in scope["headers"] if name.lower() == HEADER]
            # Exactly one header with exactly the pinned value: a second copy would let the SDK see another.
            if sent != [PROTOCOL_VERSION.encode("ascii")]:
                await send(
                    {
                        "type": "http.response.start",
                        "status": 400,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(REFUSAL)).encode("ascii")),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": REFUSAL})
                return
        await self._app(scope, receive, send)
```

Run: `uv run python -m pytest tests/plan_j/test_protocol_guard.py -q`
Expected: `8 passed`.

- [x] **Step 5: Write the failing verifier tests**

Create `tests/plan_j/test_verifier_t15.py`:

```python
"""mcp-read's token checks with the verifier `production_app` builds (`read_verifier`), on Plan D's synthetic key pair
(SA:557-558, Plan J rulings 2, 14 and 15).

Catches: an ID or refresh token accepted as an access token (`typ` claim), a browser client's token (`azp` ops-web,
the unit stand-in for a real `ops-web` access token, ruling 14), a token without `aud` (ruling 15: this synthetic case
is the evidence), another server's audience, or another workload's `azp` accepted at mcp-read; an access token whose
`resource` is stamped without the audience holding it; a refactor that drops `token_type="Bearer"` from mcp-read's
verifier or turns the SDK's `validate_token_resource` off; and the knob changing the other servers' verifiers, which
leave `token_type` unset.
"""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from ops_core import settings
from ops_core.settings import Keycloak, Urls
from ops_core.tokens import TokenRejected, TokenVerifier, WorkloadTokenSource
from ops_mcp_read import server
from ops_mcp_read.server import McpVerifier

from tests.plan_d.test_tokens import AUDIENCE, ISSUER, JWK1, mint  # Plan D's synthetic key pair and token minter

URLS = Urls(
    mcp_read_resource=AUDIENCE,
    mcp_write_resource="http://mcp-write:8082/mcp",
    mcp_read="http://127.0.0.1:8081/mcp",
    mcp_write="http://127.0.0.1:8082/mcp",
    incident_sim="http://127.0.0.1:8090",
)


KC = Keycloak(base_url="http://localhost:18080", issuer=ISSUER, server_url="http://127.0.0.1:18080")


def production_like() -> TokenVerifier:
    """`ops_mcp_read.server.read_verifier`, the one `production_app` uses, with the synthetic key installed."""
    verifier = server.read_verifier(KC, URLS)
    verifier.install_keys({"keys": [JWK1]})
    return verifier


def test_only_an_access_token_passes() -> None:
    verifier = production_like()
    assert verifier.verify(mint()).azp == "ops-worker"
    for typ in ("ID", "Refresh", None):
        with pytest.raises(TokenRejected, match="token type"):
            verifier.verify(mint(typ=typ))
    legacy = TokenVerifier(issuer=ISSUER, audience=AUDIENCE, allowed_azp=frozenset({"ops-worker"}), jwks_url="unused")
    legacy.install_keys({"keys": [JWK1]})
    assert legacy.verify(mint(typ="ID")).azp == "ops-worker"  # unset, the knob changes no other server


@pytest.mark.parametrize(
    ("over", "why"),
    [
        ({"azp": "ops-web"}, "the browser client's token"),
        ({"aud": None}, "no audience at all"),
        ({"aud": ["http://mcp-write:8082/mcp", "account"]}, "the write server's audience only"),
        ({"aud": "ops-api", "azp": "ops-dev-direct"}, "a persona token (the live browser stand-in)"),
        ({"azp": "ops-mcp-read"}, "another workload with the right audience"),
    ],
)
def test_the_adapter_answers_none_for_every_foreign_token(over: dict[str, object], why: str) -> None:
    adapter = McpVerifier(production_like(), AUDIENCE)
    assert asyncio.run(adapter.verify_token(mint(**over))) is None, why  # None is the SDK's 401


def test_the_resource_is_stamped_only_from_the_audience() -> None:
    adapter = McpVerifier(production_like(), AUDIENCE)
    access = asyncio.run(adapter.verify_token(mint(aud=["http://mcp-write:8082/mcp", AUDIENCE, "account"])))
    assert access is not None and access.resource == AUDIENCE and access.client_id == "ops-worker"
    # A verifier wired to another audience (a deployment mistake) still cannot stamp this server's resource.
    wrong = TokenVerifier(
        issuer=ISSUER, audience="account", allowed_azp=frozenset({"ops-worker"}), jwks_url="unused", token_type="Bearer"
    )
    wrong.install_keys({"keys": [JWK1]})
    assert asyncio.run(McpVerifier(wrong, AUDIENCE).verify_token(mint(aud=["account"]))) is None


def test_the_sdk_resource_check_is_on() -> None:
    """A second layer behind McpVerifier's own audience check (it cannot refuse while the stamp is this server's URL),
    pinned so a refactor cannot switch it off unnoticed."""
    state = server.State(session=None, corpora={}, verifier=production_like())
    mcp = server.build_server(state, issuer=ISSUER, resource_url=AUDIENCE)
    assert mcp.settings.auth is not None and mcp.settings.auth.validate_token_resource is True


def test_production_app_builds_its_verifier_through_read_verifier(monkeypatch: pytest.MonkeyPatch) -> None:
    """The tests above pin `read_verifier`; this pins that the app that runs uses it (a refactor that inlined a
    `TokenVerifier` without `token_type` would pass every other unit and live test, since live tokens are `Bearer`)."""
    calls: list[tuple[Any, Any]] = []
    real = server.read_verifier

    def recording(kc: Keycloak, urls: Urls) -> TokenVerifier:
        calls.append((kc, urls))
        return real(kc, urls)

    monkeypatch.setattr(settings, "keycloak", lambda: KC)
    monkeypatch.setattr(settings, "urls", lambda: URLS)
    monkeypatch.setattr(settings, "fixtures_dir", lambda: Path("data/handoff-fixtures"))
    monkeypatch.setattr(server, "read_verifier", recording)
    server.production_app()
    assert calls == [(KC, URLS)]


def test_the_token_source_names_its_client() -> None:
    assert WorkloadTokenSource(token_url="u", client_id="ops-worker", client_secret="s").client_id == "ops-worker"
```

Run: `uv run python -m pytest tests/plan_j/test_verifier_t15.py -q`
Expected: `10 failed` (`AttributeError: module 'ops_mcp_read.server' has no attribute 'read_verifier'` in the nine tests
that build or wrap the verifier, `AttributeError: 'WorkloadTokenSource' object has no attribute 'client_id'` in the
last).

- [x] **Step 6: The `typ` claim, the token source's client, the adapter's audience check and `read_verifier`**

Edit 1 (`core/src/ops_core/tokens.py`, `TokenVerifier.__init__`), replace:

```python
        require_azp: bool = True,
        typ: str | None = None,
    ) -> None:
        """Pin the server's issuer, audience, allowed azp and key source; `required_claims`, `require_azp` and `typ`
        let one class verify ID tokens (nonce, sid) and logout tokens (jti, events, typ logout+jwt, no azp),
        ruling 26."""
```

with:

```python
        require_azp: bool = True,
        typ: str | None = None,
        token_type: str | None = None,
    ) -> None:
        """Pin the server's issuer, audience, allowed azp and key source; `required_claims`, `require_azp` and `typ`
        let one class verify ID tokens (nonce, sid) and logout tokens (jti, events, typ logout+jwt, no azp),
        ruling 26. `token_type` is the `typ` *claim* Keycloak writes into the payload ("Bearer" for an access token,
        "ID" and "Refresh" for the others); `typ` is the JOSE header's (Plan J ruling 2)."""
```

Edit 2 (`core/src/ops_core/tokens.py`, the stored knobs), replace:

```python
        self._typ = typ
        self._keys: PyJWKSet | None = None
```

with:

```python
        self._typ = typ
        self._token_type = token_type
        self._keys: PyJWKSet | None = None
```

Edit 3 (`core/src/ops_core/tokens.py`, `verify`), replace:

```python
        if self._typ is not None and str(header.get("typ", "")).lower() != self._typ.lower():
            raise TokenRejected("token type is not accepted here")
```

with:

```python
        if self._typ is not None and str(header.get("typ", "")).lower() != self._typ.lower():
            raise TokenRejected("token type is not accepted here")
        if self._token_type is not None and claims.get("typ") != self._token_type:
            raise TokenRejected("token type is not accepted here")
```

Edit 4 (`core/src/ops_core/tokens.py`, `WorkloadTokenSource`), replace:

```python
        self._lock = asyncio.Lock()  # concurrent first callers share one token request

    async def token(self) -> str:
```

with:

```python
        self._lock = asyncio.Lock()  # concurrent first callers share one token request

    @property
    def client_id(self) -> str:
        """The workload client the tokens are issued to: their `azp`, which a handle minted with them is bound to."""
        return self._client_id

    async def token(self) -> str:
```

Edit 5 (`mcp-read/src/ops_mcp_read/server.py`, `McpVerifier`), replace:

```python
class McpVerifier:
    """The SDK's TokenVerifier protocol: None means 401. The SDK re-checks `expires_at`, consistently with PyJWT."""

    def __init__(self, verifier: Verifier, resource_url: str) -> None:
        """Adapt a token verifier to the SDK's bearer-auth hook; `resource_url` is stamped on the access token."""
        self._verifier = verifier
        self._resource = resource_url

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            principal = await self._verifier.verify_async(token)
        except TokenRejected:
            return None
        return AccessToken(
```

with:

```python
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
```

Edit 6 (`mcp-read/src/ops_mcp_read/server.py`, `build_server`), replace:

```python
            issuer_url=AnyHttpUrl(issuer), resource_server_url=AnyHttpUrl(resource_url), validate_token_resource=False
        ),
        token_verifier=McpVerifier(state.verifier, resource_url),
        tools=[strict_tool(search_procedures)],
```

with:

```python
            issuer_url=AnyHttpUrl(issuer), resource_server_url=AnyHttpUrl(resource_url), validate_token_resource=True
        ),
        token_verifier=McpVerifier(state.verifier, resource_url),
        tools=[strict_tool(search_procedures)],
```

Edit 7 (`mcp-read/src/ops_mcp_read/server.py`, `production_app`'s verifier, built by `read_verifier`), replace:

```python
def production_app() -> Starlette:
    """The app wired from the environment and secret files, as `python -m ops_mcp_read` runs it."""
    kc = settings.keycloak()
    urls = settings.urls()
    verifier = TokenVerifier(
        issuer=kc.issuer, audience=urls.mcp_read_resource, allowed_azp=frozenset({"ops-worker"}), jwks_url=kc.jwks_url
    )
    state = State(session=None, corpora=procedures.load_corpora(settings.fixtures_dir()), verifier=verifier)
    return build_app(build_server(state, issuer=kc.issuer, resource_url=urls.mcp_read_resource), state)
```

with:

```python
def read_verifier(kc: settings.Keycloak, urls: settings.Urls) -> TokenVerifier:
    """mcp-read's token checks (SA:557, Plan J ruling 2): the realm's issuer and keys, this server's resource URL as the
    audience, the worker as the only `azp`, and an access token's `typ` claim. `production_app` builds its verifier
    here, and the unit tests build theirs here too, so they pin the wiring that runs."""
    return TokenVerifier(
        issuer=kc.issuer,
        audience=urls.mcp_read_resource,
        allowed_azp=frozenset({"ops-worker"}),
        jwks_url=kc.jwks_url,
        token_type="Bearer",  # an access token: Keycloak's ID and refresh tokens carry another `typ` (ruling 2)
    )


def production_app() -> Starlette:
    """The app wired from the environment and secret files, as `python -m ops_mcp_read` runs it."""
    kc = settings.keycloak()
    urls = settings.urls()
    state = State(
        session=None, corpora=procedures.load_corpora(settings.fixtures_dir()), verifier=read_verifier(kc, urls)
    )
    return build_app(build_server(state, issuer=kc.issuer, resource_url=urls.mcp_read_resource), state)
```

Run: `uv run python -m pytest tests/plan_j/test_verifier_t15.py -q`
Expected: `10 passed`.

- [x] **Step 7: Write the failing HTTP tests**

Create `tests/plan_j/test_mcp_read_http.py`:

```python
"""mcp-read's HTTP stack in-process (the guard, the SDK's bearer auth around McpVerifier's audience check, the
transport's per-request ladder), with a stub key source and no database (Plan J rulings 2, 4 and 5).

Catches: the guard mounted after auth (an unauthenticated client would learn whether its token was good), auth
skipped once the version is right, a header/`_meta` mismatch that the SDK no longer rejects, a token whose verified
audiences lack this server's resource accepted, a raw `tools/call` shaped differently from what the live R026 test
sends, the official client unable to list or call through the guard, and mcp-write left without the guard. The live
versions of these cases, with Keycloak's tokens over a socket, are tests/e2e/test_mcp_read_t15_live.py.
"""

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import MappingProxyType
from typing import Any

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from ops_core import persistence
from ops_core.tokens import Principal, TokenRejected
from ops_mcp_read import procedures, server
from ops_mcp_write import server as write_server
from starlette.testclient import TestClient

ISSUER = "http://localhost:18080/realms/ops-dev"
FIXTURES = Path("data/handoff-fixtures")
RESOURCE = "http://mcp-read:8081/mcp"
BASE = "http://127.0.0.1:8081"  # a loopback Host, which the SDK's DNS-rebinding guard admits
TOOLS_LIST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {
        "_meta": {
            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientCapabilities": {},
        }
    },
}


SEARCH = "search_procedures"
SEARCH_CALL = {"name": SEARCH, "arguments": {"query": "x", "limit": 1, "mode": "lexical"}}


class KeyedVerifier:
    """Maps a few fixed strings to principals, the way a real verifier would after checking a signature."""

    @property
    def ready(self) -> bool:
        return True

    async def load_keys(self) -> None:
        return None

    async def verify_async(self, token: str) -> Principal:
        audiences = {"good": (RESOURCE, "account"), "elsewhere": ("http://mcp-write:8082/mcp", "account")}
        if token not in audiences:
            raise TokenRejected("unit test")
        claims = MappingProxyType({"iss": ISSUER, "typ": "Bearer"})
        return Principal("subject", "ops-worker", audiences[token], int(time.time()) + 300, claims)


class IdleConn:
    """Stands in for the database connection the lifespan would open; nothing here reaches it."""

    async def close(self) -> None:
        return None


def read_app() -> Any:
    state = server.State(session=None, corpora=procedures.load_corpora(FIXTURES), verifier=KeyedVerifier())
    idle: Any = IdleConn()
    state.session = persistence.Session(idle)  # already set, so the lifespan opens no connection
    return server.build_app(server.build_server(state, issuer=ISSUER, resource_url=RESOURCE), state)


def headers(
    version: str | None = "2026-07-28", token: str | None = "good", method: str = "tools/list"
) -> dict[str, str]:
    out = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json", "Mcp-Method": method}
    if version is not None:
        out["MCP-Protocol-Version"] = version
    if token is not None:
        out["Authorization"] = f"Bearer {token}"
    return out


def test_the_version_rule_comes_before_authentication() -> None:
    with TestClient(read_app(), base_url=BASE) as client:
        refused = client.post("/mcp", json=TOOLS_LIST, headers=headers(version=None, token=None))
        assert refused.status_code == 400 and refused.json()["error"]["code"] == -32022
        unauthenticated = client.post("/mcp", json=TOOLS_LIST, headers=headers(token=None))
        assert unauthenticated.status_code == 401 and "resource_metadata" in unauthenticated.headers["www-authenticate"]


def test_the_ladder_and_the_resource_check_behind_the_guard() -> None:
    with TestClient(read_app(), base_url=BASE) as client:
        listed = client.post("/mcp", json=TOOLS_LIST, headers=headers())
        assert listed.status_code == 200
        assert [t["name"] for t in listed.json()["result"]["tools"]] == ["search_procedures"]
        legacy = client.post("/mcp", json=TOOLS_LIST, headers=headers(version="2025-11-25"))
        assert legacy.status_code == 400 and legacy.json()["error"]["code"] == -32022  # the guard's
        mismatch = {**TOOLS_LIST, "params": {"_meta": {**TOOLS_LIST["params"]["_meta"]}}}
        mismatch["params"]["_meta"]["io.modelcontextprotocol/protocolVersion"] = "2025-11-25"
        refused = client.post("/mcp", json=mismatch, headers=headers())
        assert refused.status_code == 400 and refused.json()["error"]["code"] == -32020  # the SDK's HEADER_MISMATCH
        elsewhere = client.post("/mcp", json=TOOLS_LIST, headers=headers(token="elsewhere"))
        assert elsewhere.status_code == 401  # its audiences lack this server's resource: McpVerifier refuses it
        call = {**TOOLS_LIST, "method": "tools/call", "params": {**TOOLS_LIST["params"], **SEARCH_CALL}}
        answered = client.post("/mcp", json=call, headers={**headers(method="tools/call"), "Mcp-Name": SEARCH})
        assert answered.status_code == 200  # the shape the live R026 test posts; no handle, so the envelope refuses
        assert answered.json()["result"]["structuredContent"]["error"]["code"] == "INVALID_HANDLE"
        assert client.get("/health/live").status_code == 200
        metadata = client.get("/.well-known/oauth-protected-resource/mcp")
        assert metadata.status_code == 200 and metadata.json()["resource"] == RESOURCE


@asynccontextmanager
async def official_client(app: Any) -> AsyncIterator[Client]:
    """The SDK's own client pinned to 2026-07-28, over an in-process transport, with the app's lifespan running."""
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with (
            httpx2.AsyncClient(transport=transport, base_url=BASE, headers={"Authorization": "Bearer good"}) as http,
            Client(streamable_http_client(f"{BASE}/mcp", http_client=http), mode="2026-07-28") as client,
        ):
            yield client


@pytest.mark.asyncio
async def test_the_official_client_lists_and_calls_through_the_guard() -> None:
    async with official_client(read_app()) as client:
        assert [t.name for t in (await client.list_tools()).tools] == ["search_procedures"]
        res = await client.call_tool("search_procedures", {"query": "x", "limit": 1, "mode": "lexical"})
    # No X-Ops-Invocation header: the tool body refuses before any lookup, as an envelope, not a transport error.
    assert not res.is_error and res.structured_content["error"]["code"] == "INVALID_HANDLE"


def test_mcp_write_carries_the_same_guard() -> None:
    state = write_server.State(deps=None, verifier=KeyedVerifier())
    app = write_server.build_app(
        write_server.build_server(state, issuer=ISSUER, resource_url="http://mcp-write:8082/mcp"), state
    )
    client = TestClient(app, base_url="http://127.0.0.1:8082")  # no lifespan: the guard answers before the SDK
    refused = client.post("/mcp", json=TOOLS_LIST, headers=headers(version=None))
    assert refused.status_code == 400 and refused.json()["error"]["code"] == -32022
```

Run: `uv run python -m pytest tests/plan_j/test_mcp_read_http.py -q`
Expected: `3 failed, 1 passed` (the official client already passes; with no guard mounted, the first test gets 401
where it expects 400, the second gets 200 from the SDK's legacy path for the `2025-11-25` header, and mcp-write's
request reaches the SDK, which has no task group outside its lifespan: `RuntimeError: Task group is not initialized`).

- [x] **Step 8: Mount the guard in both servers**

Edit 1 (`mcp-read/src/ops_mcp_read/server.py`, the module docstring), replace:

```python
Every call must present the worker's workload token (aud = this server's resource URL, azp = ops-worker) and an
`X-Ops-Invocation` handle minted for an `investigate` job; the handle, not the token, says which run and tenant the
```

with:

```python
Every call must carry `MCP-Protocol-Version: 2026-07-28` (anything else is refused before authentication, AM-30), the
worker's workload access token (`typ` Bearer, aud = this server's resource URL, azp = ops-worker) and an
`X-Ops-Invocation` handle minted for an `investigate` job; the handle, not the token, says which run and tenant the
```

Edit 2 (`mcp-read/src/ops_mcp_read/server.py`, imports), replace:

```python
from ops_core.jobs import Tool as ToolName
from ops_core.settings import Role
from ops_core.tokens import Principal, TokenRejected, TokenVerifier
```

with:

```python
from ops_core.jobs import Tool as ToolName
from ops_core.mcp_protocol import ProtocolVersionGuard
from ops_core.settings import Role
from ops_core.tokens import Principal, TokenRejected, TokenVerifier
```

Edit 3 (`mcp-read/src/ops_mcp_read/server.py`, `build_app`'s routes), replace:

```python
        routes=[Route("/health/live", live), Route("/health/ready", ready), Mount("/", app=mcp_app)], lifespan=lifespan
    )
```

with:

```python
        routes=[
            Route("/health/live", live),
            Route("/health/ready", ready),
            # The version rule runs before the SDK app and its bearer auth (AM-30, Plan J ruling 4).
            Mount("/", app=ProtocolVersionGuard(mcp_app)),
        ],
        lifespan=lifespan,
    )
```

Edit 4 (`mcp-write/src/ops_mcp_write/server.py`, imports), replace:

```python
from ops_core.jobs import Tool as ToolName
from ops_core.outcomes import ActionOutcome, ToolOutcome
```

with:

```python
from ops_core.jobs import Tool as ToolName
from ops_core.mcp_protocol import ProtocolVersionGuard
from ops_core.outcomes import ActionOutcome, ToolOutcome
```

Edit 5 (`mcp-write/src/ops_mcp_write/server.py`, `build_app`'s routes), replace:

```python
        routes=[Route("/health/live", live), Route("/health/ready", ready), Mount("/", app=mcp_app)], lifespan=lifespan
    )
```

with:

```python
        routes=[
            Route("/health/live", live),
            Route("/health/ready", ready),
            # The version rule runs before the SDK app and its bearer auth (AM-30, Plan J ruling 4).
            Mount("/", app=ProtocolVersionGuard(mcp_app)),
        ],
        lifespan=lifespan,
    )
```

Run: `uv run python -m pytest tests/plan_j -q`
Expected: `22 passed`.

- [x] **Step 9: Write the failing worker test**

Create `tests/plan_j/test_worker_azp.py`:

```python
"""The worker binds every handle it mints to its own workload client, not to a literal (Plan J ruling 17), and never
hands a handle to the model (R027: "handle absent from model").

Catches: an `azp` written into `invocation_context` that differs from the client id the worker's tokens are issued
to, which `_resolve_handle` compares with the presented token's `azp`: a renamed client would refuse every call, and
a literal would keep accepting a client the worker no longer uses; and a field added to the model's request that could
carry a handle.
"""

import asyncio
from dataclasses import fields
from typing import Any

import pytest
from ops_core import persistence
from ops_worker import handlers
from ops_worker.drafting import DraftRequest

from tests.plan_h.test_worker_units import JOB, RUN, Log, make, patch


def capture_mints(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace mint_handle (after `patch`) with one that records its keyword arguments."""
    minted: list[dict[str, Any]] = []

    async def mint_handle(_conn: Any, **kwargs: Any) -> str:
        minted.append(kwargs)
        return "handle"

    monkeypatch.setattr(persistence, "mint_handle", mint_handle)
    return minted


@pytest.mark.parametrize(("job_type", "state"), [("investigate", "QUEUED"), ("execute", "APPROVED")])
def test_a_minted_handle_carries_the_workload_client(
    monkeypatch: pytest.MonkeyPatch, job_type: str, state: str
) -> None:
    log = Log()
    patch(monkeypatch, log)
    minted = capture_mints(monkeypatch)

    async def run_row(_conn: Any, _run_id: Any, *, lock: bool = False) -> dict[str, Any]:
        return {**RUN, "state": state}

    monkeypatch.setattr(persistence, "run_row", run_row)
    deps, lease = make(log)
    deps.workload_azp = "ops-worker-renamed"
    asyncio.run(handlers.handle(deps, {**JOB, "type": job_type}, lease))
    assert [m["azp"] for m in minted] == ["ops-worker-renamed"]


def test_the_model_request_has_no_field_for_a_handle() -> None:
    assert [f.name for f in fields(DraftRequest)] == ["asset_id", "text", "start_at", "end_at"]
```

Run: `uv run python -m pytest tests/plan_j/test_worker_azp.py -q`
Expected: `2 failed, 1 passed` (`assert ['ops-worker'] == ['ops-worker-renamed']`: both mints write the literal;
the model-request test passes already, since it pins what `DraftRequest` holds today).

- [x] **Step 10: The worker mints with its own client id**

Edit 1 (`worker/src/ops_worker/handlers.py`, `Deps`), replace:

```python
    """What a handler needs: the loop's connection, the MCP client, the model route, the server URLs, the worker's
    name (the lease owner), the lease settings and the heartbeat that renews the lease while a job runs."""

    conn: persistence.Conn
    mcp: McpCaller
    generator: DraftGenerator
    urls: Urls
    worker_name: str
```

with:

```python
    """What a handler needs: the loop's connection, the MCP client, the model route, the server URLs, the worker's
    name (the lease owner), the workload client its tokens are issued to (the `azp` a handle is bound to), the lease
    settings and the heartbeat that renews the lease while a job runs."""

    conn: persistence.Conn
    mcp: McpCaller
    generator: DraftGenerator
    urls: Urls
    worker_name: str
    workload_azp: str  # the token source's client id (Plan J ruling 17): _resolve_handle compares it with the token's
```

Edit 2 (`worker/src/ops_worker/handlers.py`, `investigate`'s mint), replace:

```python
        handle = await persistence.mint_handle(
            deps.conn, run_id=run["run_id"], job_id=job["id"], server=Server.READ, azp="ops-worker", fence=lease.fence
        )
```

with:

```python
        handle = await persistence.mint_handle(
            deps.conn,
            run_id=run["run_id"],
            job_id=job["id"],
            server=Server.READ,
            azp=deps.workload_azp,
            fence=lease.fence,
        )
```

Edit 3 (`worker/src/ops_worker/handlers.py`, `execute`'s mint), replace:

```python
        handle = await persistence.mint_handle(
            deps.conn, run_id=run["run_id"], job_id=job["id"], server=Server.WRITE, azp="ops-worker", fence=lease.fence
        )
```

with:

```python
        handle = await persistence.mint_handle(
            deps.conn,
            run_id=run["run_id"],
            job_id=job["id"],
            server=Server.WRITE,
            azp=deps.workload_azp,
            fence=lease.fence,
        )
```

Edit 4 (`worker/src/ops_worker/main.py`, `_main`'s `Deps`), replace:

```python
        worker_name=f"{socket.gethostname()}:{os.getpid()}",
        leases=leases,
```

with:

```python
        worker_name=f"{socket.gethostname()}:{os.getpid()}",
        workload_azp=tokens.client_id,
        leases=leases,
```

Edit 5 (`worker/src/ops_worker/mcp.py`, imports), replace:

```python
from mcp.client.streamable_http import streamable_http_client
```

with:

```python
from mcp.client.streamable_http import streamable_http_client
from ops_core.mcp_protocol import PROTOCOL_VERSION
```

Edit 6 (`worker/src/ops_worker/mcp.py`, the pinned version), replace:

```python
                Client(streamable_http_client(url, http_client=http), mode="2026-07-28") as client,
```

with:

```python
                Client(streamable_http_client(url, http_client=http), mode=PROTOCOL_VERSION) as client,
```

Edit 7 (`tests/plan_h/test_worker_units.py`, `make`), replace:

```python
    deps = handlers.Deps(
        conn=conn, mcp=ScriptedMcp(log), generator=FakeDraftGenerator(), urls=settings.urls(), worker_name="w:test"
    )
```

with:

```python
    deps = handlers.Deps(
        conn=conn,
        mcp=ScriptedMcp(log),
        generator=FakeDraftGenerator(),
        urls=settings.urls(),
        worker_name="w:test",
        workload_azp="ops-worker",
    )
```

Edit 8 (`tests/plan_f/test_grant_deferred.py`, the deferred-grant test's `Deps`), replace:

```python
    deps = handlers.Deps(conn=conn, mcp=mcp, generator=no_generator, urls=settings.urls(), worker_name="worker:test")
```

with:

```python
    deps = handlers.Deps(
        conn=conn,
        mcp=mcp,
        generator=no_generator,
        urls=settings.urls(),
        worker_name="worker:test",
        workload_azp="ops-worker",
    )
```

Edit 9 (`tests/e2e/test_heartbeat_live.py`, `worker_deps`), replace:

```python
        worker_name=WORKER,
        leases=settings.leases(),  # the real defaults: DoD 3 is about these values
```

with:

```python
        worker_name=WORKER,
        workload_azp="ops-worker",  # the azp the scripted callers resolve with
        leases=settings.leases(),  # the real defaults: DoD 3 is about these values
```

Edit 10 (`tests/e2e/test_worker_live.py`, the `Deps` factory), replace:

```python
            worker_name="t",
        )
```

with:

```python
            worker_name="t",
            workload_azp="ops-worker",  # the azp ResolvingMcp presents, as the real worker token's would be
        )
```

Run: `uv run python -m pytest tests/plan_j tests/plan_h/test_worker_units.py tests/plan_f/test_grant_deferred.py -q`
Expected: `48 passed` (25 in `tests/plan_j`, 23 in the two edited modules).

- [x] **Step 11: Gates and commit**

Format, lint and count characters on `core/src/ops_core/mcp_protocol.py`, `core/src/ops_core/tokens.py`,
`mcp-read/src/ops_mcp_read/server.py`, `mcp-write/src/ops_mcp_write/server.py`, the three worker modules, every file
under `tests/plan_j/` and the four edited test modules.

Run: `PYTHONUTF8=1 uv run python scripts/check.py`
Expected: `CHECK: GREEN`; pytest `1057 passed, 154 skipped` (1032 + 25 in `tests/plan_j`).

Run: `PYTHONUTF8=1 uv run python scripts/check.py --profile test`
Expected: `CHECK: GREEN`; pytest `1190 passed, 21 skipped` (arithmetic, not measured: the dev count plus the 133
live-gated tests, 154 − 21; the services changed, so the live suite runs: R105's worker passes the guard at both
servers with the real client, and the existing mcp-read live test's persona and mcp-write tokens are still refused).
Then `git checkout -- reports/bootstrap reports/skeleton reports/auth reports/admission reports/leases reports/events
reports/outbox`.

Run: `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`
Expected: exit 0.

```bash
git add pyproject.toml core/src/ops_core/mcp_protocol.py core/src/ops_core/tokens.py mcp-read/src/ops_mcp_read/server.py
git add mcp-write/src/ops_mcp_write/server.py worker/src/ops_worker/handlers.py worker/src/ops_worker/main.py
git add worker/src/ops_worker/mcp.py tests/plan_j tests/plan_h/test_worker_units.py tests/plan_f/test_grant_deferred.py
git add tests/e2e/test_heartbeat_live.py tests/e2e/test_worker_live.py
git commit -m "feat(mcp): protocol-version guard on both servers, a stricter mcp-read verifier, azp at mint (T15)"
```

---

### Task 2: Revision 0009 — the handle's job binding, the run-state allowlist, mcp-read's startup check

**Files:**
- Create: `migrations/app/versions/0009_handle_binding.py`, `tests/plan_j/test_allowlist.py`,
  `tests/plan_j/test_migration_0009.py`, `tests/plan_j/test_mcp_read_startup.py`,
  `tests/e2e/test_migration_0009_live.py`
- Modify: `core/src/ops_core/persistence.py:170-178` (after `assert_relation`), `:375-379` (`allowed_tool`),
  `:392-402` (`resolve_invocation`), `core/src/ops_core/jobs.py:52-57` (`JobRule`'s docstring),
  `mcp-read/src/ops_mcp_read/server.py:41` (after the `procedures` import), `:220-221` (the lifespan's checks),
  `tests/plan_d/test_persistence_pure.py:14-27`, `tests/plan_e/test_persistence_errors.py:16`, `:54-69`,
  `tests/plan_e/test_transitions_table.py:93-94` (`REVISIONS`), `tests/e2e/test_r105_walking_skeleton.py:210-211`,
  `:231`, `:238`, `tests/e2e/test_migrations_and_persistence.py:409-410` (the populated upgrade's handle step),
  `mcp-write/src/ops_mcp_write/execution.py:4-8` (the replay rule in its module docstring)

**Requirements:** SA:338/SA:459's allowlist by job type and run state (ruling 6), SA:496's job-derived binding (ruling
6), R006 (an exact downgrade), the startup refusal of ruling 18; R027's "other run" at the definer, R085's
server-derived allowlist; T15 review notes 2 (the run-state half) and 4.

**Interfaces:**
- Consumes: revision 0007's `RESOLVE_HANDLE`; `privileges.function_grant_statements`; `jobs.JOB_RULES`, `JobType`,
  `Server`, `Tool`; `states.RunState`; the e2e fixtures `app_conn`, `role_conn`, `lease_for`, `purge_run`,
  `purge_tenant`, `new_run`, `refused` (`tests.e2e.test_definers_run_path_live`), `investigate_job`, `read_handle`,
  `resolve` (`tests.e2e.test_fenced_definers_live`), `FUNCTION_DETAILS`, `LEFTOVERS`
  (`tests.e2e.test_migration_0007_live`); Task 1's `tests.plan_j.test_mcp_read_http.FIXTURES`, `ISSUER`, `RESOURCE`,
  `KeyedVerifier`; `tests.plan_e.test_transitions_table.REVISIONS`.
- Produces: `persistence.allowed_tool(job_type: JobType, run_state: RunState, tool: Tool) -> None`;
  `persistence.assert_function_text(conn, signature: str, marker: str) -> None` (raises `PersistenceError`
  "<signature> predates this service; …"); `ops_mcp_read.server.HANDLE_BINDING = ("app._resolve_handle(text, text,
  text)", "j.run_id = v_ctx.run_id AND j.done_at IS NULL")`; in the revision: `JOB_READ_0007`, `JOB_READ_0009`,
  `RESOLVE_HANDLE`, `FUNCTIONS`, `RESTORED`.

- [x] **Step 1: Write the failing allowlist tests (and move the two existing ones to the new signature)**

Edit 1 (`tests/plan_d/test_persistence_pure.py`, the rejections), replace:

```python
from ops_core.jobs import JobType, Tool
from ops_core.persistence import HandleRejected, allowed_tool, translate


@pytest.mark.parametrize(
    ("job_type", "tool"),
    [
        (JobType.INVESTIGATE, Tool.CREATE_INCIDENT),  # a read job may not call a write tool
        (JobType.EXECUTE, Tool.GET_INCIDENT_RECEIPT),  # execute is not recover
    ],
)
def test_rejections(job_type: JobType, tool: Tool) -> None:
    with pytest.raises(HandleRejected):
        allowed_tool(job_type, tool)
```

with:

```python
from ops_core.jobs import JobType, Tool
from ops_core.persistence import HandleRejected, allowed_tool, translate
from ops_core.states import RunState


@pytest.mark.parametrize(
    ("job_type", "state", "tool"),
    [
        (JobType.INVESTIGATE, RunState.RETRIEVING, Tool.CREATE_INCIDENT),  # a read job may not call a write tool
        (JobType.EXECUTE, RunState.APPROVED, Tool.GET_INCIDENT_RECEIPT),  # execute is not recover
    ],
)
def test_rejections(job_type: JobType, state: RunState, tool: Tool) -> None:
    with pytest.raises(HandleRejected):
        allowed_tool(job_type, state, tool)
```

Edit 2 (`tests/plan_e/test_persistence_errors.py`, imports), replace:

```python
from ops_core.states import IllegalTransition
```

with:

```python
from ops_core.states import IllegalTransition, RunState
```

Edit 3 (`tests/plan_e/test_persistence_errors.py`, `test_allowed_tool`), replace:

```python
@pytest.mark.parametrize(
    ("job_type", "tool", "ok"),
    [
        (JobType.INVESTIGATE, Tool.SEARCH_PROCEDURES, True),
        (JobType.INVESTIGATE, Tool.CREATE_INCIDENT, False),
        (JobType.EXECUTE, Tool.CREATE_INCIDENT, True),
        (JobType.EXECUTE, Tool.SEARCH_PROCEDURES, False),
        (JobType.RECOVER, Tool.ABORT_INCIDENT, True),
    ],
)
def test_allowed_tool(job_type: JobType, tool: Tool, ok: bool) -> None:
    if ok:
        p.allowed_tool(job_type, tool)
    else:
        with pytest.raises(p.HandleRejected):
            p.allowed_tool(job_type, tool)
```

with:

```python
@pytest.mark.parametrize(
    ("job_type", "state", "tool", "ok"),
    [
        (JobType.INVESTIGATE, RunState.RETRIEVING, Tool.SEARCH_PROCEDURES, True),
        (JobType.INVESTIGATE, RunState.RETRIEVING, Tool.CREATE_INCIDENT, False),
        (JobType.EXECUTE, RunState.APPROVED, Tool.CREATE_INCIDENT, True),
        (JobType.EXECUTE, RunState.APPROVED, Tool.SEARCH_PROCEDURES, False),
        (JobType.RECOVER, RunState.OUTCOME_UNKNOWN, Tool.ABORT_INCIDENT, True),
    ],
)
def test_allowed_tool(job_type: JobType, state: RunState, tool: Tool, ok: bool) -> None:
    if ok:
        p.allowed_tool(job_type, state, tool)
    else:
        with pytest.raises(p.HandleRejected):
            p.allowed_tool(job_type, state, tool)
```

Create `tests/plan_j/test_allowlist.py`:

```python
"""The AM-15 allowlist in Python: the job type's tools and the job type's run states (Plan J ruling 6, erratum 19).

Catches: a read handle still honoured once its run awaits approval, input or a decision (or ended), an execute handle
honoured once its run succeeded, a tool outside the job type's set (R085: the worker names the tool, the server
decides), a refusal whose message says which check failed or whose log line carries the handle, and a resolution
that reads the run state but does not hand it to the check.
"""

import asyncio
import logging
from typing import Any

import pytest
from ops_core import persistence
from ops_core.jobs import JOB_RULES, JobType, Server, Tool
from ops_core.states import RunState

HANDLE_JOBS = [t for t, rule in JOB_RULES.items() if rule.server is not None]


@pytest.mark.parametrize("job_type", HANDLE_JOBS, ids=[t.value for t in HANDLE_JOBS])
def test_every_state_and_tool_pair_follows_the_job_rule(job_type: JobType) -> None:
    rule = JOB_RULES[job_type]
    for state in RunState:
        for tool in Tool:
            if tool in rule.allowed_tools and state in rule.run_states:
                persistence.allowed_tool(job_type, state, tool)
            else:
                with pytest.raises(persistence.HandleRejected) as refused:
                    persistence.allowed_tool(job_type, state, tool)
                assert str(refused.value) == "invocation handle rejected"  # one message for every refusal


def test_the_read_jobs_run_where_the_worker_calls_mcp_read() -> None:
    assert JOB_RULES[JobType.INVESTIGATE].run_states == {RunState.QUEUED, RunState.RETRIEVING, RunState.DRAFTING}
    assert JOB_RULES[JobType.RESUME_INPUT].run_states == {RunState.AWAITING_INPUT, RunState.QUEUED}
    assert {JOB_RULES[t].server for t in (JobType.INVESTIGATE, JobType.RESUME_INPUT)} == {Server.READ}


class OneRow:
    """A connection whose one statement returns `row` (the definer's answer)."""

    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row
        self.params: tuple[object, ...] = ()

    async def execute(self, _query: str, params: tuple[object, ...]) -> "OneRow":
        self.params = params
        return self

    async def fetchone(self) -> dict[str, Any]:
        return self.row


def resolved_row(state: str) -> dict[str, Any]:
    ids = "00000000-0000-4000-8000-00000000000"
    return {
        "run_id": f"{ids}1",
        "job_id": f"{ids}2",
        "job_type": "investigate",
        "tenant_id": f"{ids}3",
        "conversation_id": f"{ids}4",
        "run_state": state,
        "attempt_state": None,
    }


def test_resolution_hands_the_run_state_to_the_check(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    conn: Any = OneRow(resolved_row("RETRIEVING"))
    handle = "a-raw-handle-that-must-never-be-logged"
    got = asyncio.run(
        persistence.resolve_invocation(conn, handle=handle, azp="ops-worker", tool=Tool.SEARCH_PROCEDURES)
    )
    passed = conn.params == (handle, "ops-worker")
    assert got.run_state is RunState.RETRIEVING and passed
    conn.row = resolved_row("AWAITING_APPROVAL")
    with pytest.raises(persistence.HandleRejected):
        asyncio.run(persistence.resolve_invocation(conn, handle=handle, azp="ops-worker", tool=Tool.SEARCH_PROCEDURES))
    leaked = handle in caplog.text  # a verdict, not an operand (Global Constraints: secrets)
    assert "does not run in state AWAITING_APPROVAL" in caplog.text and not leaked
```

Run: `uv run python -m pytest tests/plan_j/test_allowlist.py tests/plan_d/test_persistence_pure.py tests/plan_e/test_persistence_errors.py -q`
Expected: `12 failed, 12 passed` (`TypeError: allowed_tool() takes 2 positional arguments but 3 were given` in the
eleven calls that pass a state; `Failed: DID NOT RAISE` in the resolution test, whose AWAITING_APPROVAL row still
resolves).

- [x] **Step 2: The run-state dimension**

Edit 1 (`core/src/ops_core/persistence.py`, `allowed_tool`), replace:

```python
def allowed_tool(job_type: JobType, tool: Tool) -> None:
    """The AM-15 allowlist stays in Python (ruling 21); the function has already bound server, azp and expiry."""
    if tool not in JOB_RULES[job_type].allowed_tools:
        log.info("tool %s is not allowed for job type %s", tool.value, job_type.value)  # never the handle
        raise HandleRejected("invocation handle rejected")  # the one fixed message (SA:357)
```

with:

```python
def allowed_tool(job_type: JobType, run_state: RunState, tool: Tool) -> None:
    """The AM-15 allowlist stays in Python (Plan E ruling 21, erratum 19): the tool must be one of the job type's and
    the run must be in one of the job type's states (Plan J ruling 6); the function has already bound server, azp,
    expiry, fence and the handle's job. A run that moved on (a read handle once the run awaits approval, an execute
    handle once the run succeeded) is refused like any other handle."""
    rule = JOB_RULES[job_type]
    if tool not in rule.allowed_tools:
        log.info("tool %s is not allowed for job type %s", tool.value, job_type.value)  # never the handle
        raise HandleRejected("invocation handle rejected")  # the one fixed message (SA:357)
    if run_state not in rule.run_states:
        log.info("job type %s does not run in state %s", job_type.value, run_state.value)  # never the handle
        raise HandleRejected("invocation handle rejected")
```

Edit 2 (`core/src/ops_core/persistence.py`, `resolve_invocation`), replace:

```python
    job_type = JobType(str(row["job_type"]))
    allowed_tool(job_type, tool)
    return Invocation(
        UUID(str(row["run_id"])),
        UUID(str(row["job_id"])),
        job_type,
        UUID(str(row["tenant_id"])),
        UUID(str(row["conversation_id"])),
        RunState(str(row["run_state"])),
        None if row["attempt_state"] is None else str(row["attempt_state"]),
    )
```

with:

```python
    job_type = JobType(str(row["job_type"]))
    run_state = RunState(str(row["run_state"]))
    allowed_tool(job_type, run_state, tool)
    return Invocation(
        UUID(str(row["run_id"])),
        UUID(str(row["job_id"])),
        job_type,
        UUID(str(row["tenant_id"])),
        UUID(str(row["conversation_id"])),
        run_state,
        None if row["attempt_state"] is None else str(row["attempt_state"]),
    )
```

Edit 3 (`core/src/ops_core/jobs.py`, `JobRule`'s docstring), replace:

```python
    """What a job type may do: its tools, the run states it runs in, its server, creators and dedup key shape.

    TODO(T15): AM-15 derives the allowlist from the job type *plus the run state and the attempt state* (for example
    `create_incident` only while the attempt is absent or INTENT). This rule holds the job-type dimension; T15's
    `resolve_invocation` adds the run-state and attempt-state filters at call time.
    """
```

with:

```python
    """What a job type may do: its tools, the run states it runs in, its server, creators and dedup key shape.

    AM-15 derives the allowlist from the job type plus the run state and the attempt state. `allowed_tools` and
    `run_states` are the first two, and `persistence.allowed_tool` checks both at every handle resolution (T15).
    TODO(T47): the attempt-state dimension (`create_incident` only while the attempt is absent or INTENT, not
    cancelled, before the deadline) is mcp-write's, where `execution.next_step` branches on it today.
    """
```

Run: `uv run python -m pytest tests/plan_j/test_allowlist.py tests/plan_d/test_persistence_pure.py tests/plan_e/test_persistence_errors.py -q`
Expected: `24 passed` (6 in `test_allowlist.py`, 18 in the two edited modules).

- [x] **Step 3: Write the failing revision and startup tests**

Edit 1 (`tests/plan_e/test_transitions_table.py`, `REVISIONS`), replace:

```python
    "0008_journal_outbox",
    "tc_0001_test_clock",
```

with:

```python
    "0008_journal_outbox",
    "0009_handle_binding",
    "tc_0001_test_clock",
```

Create `tests/plan_j/test_migration_0009.py`:

```python
"""Revision 0009 without a database (Plan J rulings 6 and 18): `_resolve_handle` is 0007's body with the job read bound
to the handle's run and to an open job, it stays a helper granted to nobody, the downgrade puts 0007's body back, and
mcp-read's startup check looks for text only this revision's body carries.

Catches: a revision that rewrites more of the body than the one read (the lease lock, the fence and expiry checks and
the server binding are 0007's, proved live by Plan H), a body that grants EXECUTE on a helper, a downgrade that keeps
the binding or touches a row, a startup marker that an older body also contains (mcp-read would start on 0008), and a
later revision that re-creates `_resolve_handle` without the marker (mcp-read would refuse a fully migrated database).
"""

import importlib.util
from pathlib import Path
from typing import Any

import alembic.op
import pytest
from ops_mcp_read.server import HANDLE_BINDING

from tests.plan_e.test_transitions_table import REVISIONS

VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "app" / "versions"
REVOKE = "REVOKE ALL ON FUNCTION app._resolve_handle(text, text, text) FROM PUBLIC"


def revision(name: str = "0009_handle_binding") -> Any:
    """Load a revision by path (the versions directory is not a package)."""
    spec = importlib.util.spec_from_file_location(f"rev_{name}", VERSIONS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def statements(module: Any, fn: str, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """What upgrade() or downgrade() hands to op.execute, in order."""
    seen: list[str] = []
    monkeypatch.setattr(alembic.op, "execute", lambda statement, *a, **k: seen.append(str(statement)))
    getattr(module, fn)()
    return seen


def test_only_the_job_read_changes() -> None:
    module, rev0007 = revision(), revision("0007_leases_fences")
    assert module.down_revision == "0008_journal_outbox"
    assert rev0007.RESOLVE_HANDLE.count(module.JOB_READ_0007) == 1
    assert module.RESOLVE_HANDLE != rev0007.RESOLVE_HANDLE
    assert module.RESOLVE_HANDLE.replace(module.JOB_READ_0009, module.JOB_READ_0007) == rev0007.RESOLVE_HANDLE
    assert "AND j.run_id = v_ctx.run_id AND j.done_at IS NULL;" in module.JOB_READ_0009


def test_upgrade_recreates_the_helper_granted_to_nobody(monkeypatch: pytest.MonkeyPatch) -> None:
    module = revision()
    assert statements(module, "upgrade", monkeypatch) == [module.RESOLVE_HANDLE, REVOKE]


def test_the_downgrade_restores_0007s_body(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = statements(revision(), "downgrade", monkeypatch)
    assert seen == [revision("0007_leases_fences").RESOLVE_HANDLE, REVOKE]  # byte for byte; no row is touched


def test_the_startup_marker_is_only_in_this_revisions_body() -> None:
    signature, marker = HANDLE_BINDING
    assert signature == "app._resolve_handle(text, text, text)"
    assert marker in revision().RESOLVE_HANDLE
    for older in ("0004_write_path_functions", "0007_leases_fences"):
        assert marker not in revision(older).RESOLVE_HANDLE, older


def test_the_newest_body_of_resolve_handle_carries_the_startup_marker() -> None:
    newest = None
    for name in REVISIONS:  # Alembic order; the newest revision that re-creates the helper wins
        for fn, _, _, body in getattr(revision(name), "FUNCTIONS", ()):
            if fn == "_resolve_handle":
                newest = (name, body)
    assert newest is not None and HANDLE_BINDING[1] in newest[1], newest and newest[0]
```

Create `tests/plan_j/test_mcp_read_startup.py`:

```python
"""mcp-read refuses to start on a database without revision 0009 (Plan J ruling 18), as the other services refuse to
start without their revision's relation, and closes the connection it opened.

Catches: a server that resolves handles with 0007's unbound `_resolve_handle` (a dev database not yet migrated), a
check that asks the wrong function or for the wrong text, and a failed start that leaks its connection.
"""

from typing import Any

import pytest
from ops_core import persistence, settings
from ops_mcp_read import procedures, server
from starlette.testclient import TestClient

from tests.plan_j.test_mcp_read_http import FIXTURES, ISSUER, RESOURCE, KeyedVerifier


class CatalogConn:
    """Answers the two startup queries: no test clock, and whether the marker is in the stored body."""

    def __init__(self, bound: bool) -> None:
        self.bound = bound
        self.closed = False
        self.asked: list[tuple[object, ...]] = []

    async def execute(self, query: str, params: tuple[object, ...] = ()) -> "CatalogConn":
        self.asked.append(params)
        self.row = {"present": self.bound if "prosrc" in query else False}
        return self

    async def fetchone(self) -> dict[str, Any]:
        return self.row

    async def close(self) -> None:
        self.closed = True


def start(monkeypatch: pytest.MonkeyPatch, conn: CatalogConn) -> None:
    async def connect(_pg: Any) -> CatalogConn:
        return conn

    monkeypatch.setattr(persistence, "connect", connect)
    monkeypatch.setattr(settings, "app_postgres", lambda role: role)
    monkeypatch.setenv("PROFILE", "dev")
    state = server.State(session=None, corpora=procedures.load_corpora(FIXTURES), verifier=KeyedVerifier())
    app = server.build_app(server.build_server(state, issuer=ISSUER, resource_url=RESOURCE), state)
    with TestClient(app, base_url="http://127.0.0.1:8081") as client:
        assert client.get("/health/live").status_code == 200


def test_a_database_before_0009_is_refused_and_the_connection_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = CatalogConn(bound=False)
    with pytest.raises(persistence.PersistenceError, match="predates this service"):
        start(monkeypatch, conn)
    assert conn.closed
    assert conn.asked[-1] == (server.HANDLE_BINDING[1], "app._resolve_handle(text, text, text)")


def test_a_database_at_0009_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = CatalogConn(bound=True)
    start(monkeypatch, conn)
    assert conn.closed  # the lifespan's own close at shutdown
```

Run: `uv run python -m pytest tests/plan_j/test_migration_0009.py tests/plan_j/test_mcp_read_startup.py tests/plan_e/test_transitions_table.py -q`
Expected: `2 errors in` (collection stops: `ImportError: cannot import name 'HANDLE_BINDING' from
'ops_mcp_read.server'`, and the transitions module's check that every listed revision exists fails on
`0009_handle_binding`).

- [x] **Step 4: The revision, the catalog check and the startup refusal**

Create `migrations/app/versions/0009_handle_binding.py`:

```python
"""The invocation handle's job binding (T15, Plan J ruling 6).

Revision ID: 0009_handle_binding
Revises: 0008_journal_outbox

`_resolve_handle` read the handle's job by id alone, so a handle whose `job_id` named another run's job (a row a
compromised worker or a superuser wrote; `invocation_context` has no RLS, SA:523), or a job already finished, still
resolved for the handle's own run. The job must now be the handle's run's own and still open (`done_at IS NULL`);
otherwise its type reads as NULL and the existing server check refuses it with every other refusal (one error, one
message, SA:357). Only that read changes: the body is revision 0007's with one statement replaced, which a unit test
checks, so the lease lock, the fence and expiry comparisons and the server binding stay as 0007 proved them. The run
state and tool allowlist stay in Python (`persistence.allowed_tool`, erratum 19). The downgrade restores 0008 exactly
(R006) by re-running 0007's own body, loaded from its file (the 0007 pattern).
"""

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic import op
from ops_core import privileges

revision = "0009_handle_binding"
down_revision = "0008_journal_outbox"
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


REV0007 = _applied("0007_leases_fences")
# 0007's read of the handle's job, and the bound read that replaces it. With no row (another run's job, a finished
# job, an unknown id) `SELECT INTO` leaves v_job_type NULL, and a NULL type is refused by the server check below it.
JOB_READ_0007 = "    SELECT j.type INTO v_job_type FROM jobs j WHERE j.id = v_ctx.job_id;\n"
JOB_READ_0009 = (
    "    -- T15 (Plan J ruling 6): the handle's job must be its own run's and still open; a job of another run or a\n"
    "    -- finished one yields no type, which the server check refuses with every other refusal.\n"
    "    SELECT j.type INTO v_job_type FROM jobs j\n"
    "    WHERE j.id = v_ctx.job_id AND j.run_id = v_ctx.run_id AND j.done_at IS NULL;\n"
)
RESOLVE_HANDLE = REV0007.RESOLVE_HANDLE.replace(JOB_READ_0007, JOB_READ_0009)

# (name, argument types, callers, body): frozen here (N1); the newest-revision test reads this tuple.
FUNCTIONS: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("_resolve_handle", "text, text, text", (), RESOLVE_HANDLE),
)
# What downgrade() re-creates, from the applied revision's own body: (name, args, callers, body).
RESTORED: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("_resolve_handle", "text, text, text", (), REV0007.RESOLVE_HANDLE),
)


def upgrade() -> None:
    """The bound body, then its REVOKE (a helper is granted to nobody, SA:474).

    Raises:
        RuntimeError: revision 0007's body no longer carries the read this revision replaces.
    """
    if REV0007.RESOLVE_HANDLE.count(JOB_READ_0007) != 1:
        raise RuntimeError("revision 0007's _resolve_handle no longer carries the job read this revision binds")
    for name, args, callers, body in FUNCTIONS:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)


def downgrade() -> None:
    """Back to 0008: 0007's body, then its REVOKE; no row is touched."""
    for name, args, callers, body in RESTORED:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)
```

Edit 1 (`core/src/ops_core/persistence.py`, after `assert_relation`), replace:

```python
async def tenants(conn: Conn) -> list[UUID]:
```

with:

```python
async def assert_function_text(conn: Conn, signature: str, marker: str) -> None:
    """Refuse to start when a function's stored body lacks the text a later revision put there: a revision that only
    re-creates a function adds no relation for `assert_relation` to find (`pg_proc` is readable by any role)."""
    cur = await conn.execute(
        "SELECT coalesce(strpos(p.prosrc, %s) > 0, false) AS present FROM pg_proc p WHERE p.oid = to_regprocedure(%s)",
        (marker, signature),
    )
    row = await cur.fetchone()
    if row is None or not row["present"]:
        raise PersistenceError(f"{signature} predates this service; run scripts/skeleton.py migrate for this profile")


async def tenants(conn: Conn) -> list[UUID]:
```

Edit 2 (`mcp-read/src/ops_mcp_read/server.py`, after the `procedures` import), replace:

```python
from ops_mcp_read import procedures

```

with:

```python
from ops_mcp_read import procedures

# Revision 0009 (T15): `_resolve_handle` binds the handle's job to its run and refuses a finished one. Without it the
# server would resolve handles the binding refuses, so it refuses to start, as the other services do without their
# revision's relation (Plan J ruling 18). A later revision that re-creates `_resolve_handle` must keep this text or
# change it here in the same commit; a unit test checks the newest body carries it.
HANDLE_BINDING = ("app._resolve_handle(text, text, text)", "j.run_id = v_ctx.run_id AND j.done_at IS NULL")

```

Edit 3 (`mcp-read/src/ops_mcp_read/server.py`, the lifespan's checks), replace:

```python
                await persistence.assert_clock_profile(conn, settings.profile())
            except BaseException:  # a failed start must leak no connection, and a re-entered lifespan re-asserts
```

with:

```python
                await persistence.assert_clock_profile(conn, settings.profile())
                await persistence.assert_function_text(conn, *HANDLE_BINDING)
            except BaseException:  # a failed start must leak no connection, and a re-entered lifespan re-asserts
```

Run: `uv run ruff check --select ISC004 --fix --unsafe-fixes migrations/app/versions/0009_handle_binding.py`
Expected: `All checks passed!`

Run: `uv run python -m pytest tests/plan_j tests/plan_e/test_transitions_table.py -q`
Expected: `52 passed` (38 in `tests/plan_j`, 14 in the transitions module).

- [x] **Step 5: The tests and the docstring that described a replay the binding now refuses**

Edit 1 (`tests/e2e/test_r105_walking_skeleton.py`, the replay's comment), replace:

```python
    # Review focus 1 and 3 over the real transport: a replayed create_incident with a fresh execute handle returns
    # the recorded outcome (same action id, no second incident), and the wrong tokens are refused at mcp-write.
```

with:

```python
    # Review focus 1 and 3 over the real transport, as T15 bound handles (Plan J ruling 6): a fresh execute handle
    # minted for the finished execute job of the SUCCEEDED run is refused at mcp-write (the job is done and the run is
    # past the execute job's states), so a replay after the outcome never reaches the grant and the destination keeps
    # its one incident; the wrong tokens are refused at the transport. Through the tool a replay is answered only while
    # the run is APPROVED or EXECUTING (the re-queue re-sends under the same action id); the execution layer's stored-
    # outcome replay is proved by direct calls in tests/e2e/test_mcp_write_live.py.
```

Edit 2 (`tests/e2e/test_r105_walking_skeleton.py`, the replay's assertion), replace:

```python
    assert replay is not None and replay["status"] == "ok" and replay["data"]["action_id"] == action_id
```

with:

```python
    assert replay is not None and replay["status"] == "error" and replay["error"]["code"] == "INVALID_HANDLE"
```

Edit 3 (`tests/e2e/test_r105_walking_skeleton.py`, the evidence line), replace:

```python
    lines.append("replay=same_action_id refusals=api:worker,destination:persona+worker,mcp-write:persona+mcp-read")
```

with:

```python
    lines.append(
        "replay=refused_finished_job refusals=api:worker,destination:persona+worker,mcp-write:persona+mcp-read"
    )
```

`test_r006_populated_revision_1_database_upgrades_in_place` seeds its migrated SUCCEEDED run's execute job finished, so
0009 refuses that job's handle; the test now proves the binding covers migrated rows and then reopens the job.

Edit 4 (`tests/e2e/test_migrations_and_persistence.py`, the populated upgrade's handle step), replace:

```python
        grant = await persistence.lookup_action(mcp_exec, handle=handle)
        assert grant.action_id == action and grant.attempt_state == "RESOLVED"
```

with:

```python
        # Revision 0009 (Plan J ruling 6): a handle naming a finished job is refused, migrated rows included; the same
        # handle resolves once its job is open again, so the refusal is the binding's.
        with pytest.raises(persistence.HandleRejected):
            await persistence.lookup_action(mcp_exec, handle=handle)
        await app_conn.execute("UPDATE app.jobs SET done_at = NULL WHERE id = %s", (execute_job,))
        grant = await persistence.lookup_action(mcp_exec, handle=handle)
        assert grant.action_id == action and grant.attempt_state == "RESOLVED"
```

(`pytest` is imported there already; `purge_run` removes the job in `finally`, and no worker runs in that module, so
the reopened job is never claimed.)

Edit 5 (`mcp-write/src/ops_mcp_write/execution.py`, the replay rule in the module docstring), replace:

```python
Replay rule (Plan D review focus 1): execution_grant is UNIQUE (run_id), so a second `create_incident` for the same run
finds the existing grant; if its attempt is RESOLVED the stored outcome is returned without touching the destination,
otherwise the same action id and bytes are re-sent and the destination's idempotent key answers. There is never a
second action id for one run. A transport failure after SENT is reported as UNKNOWN and recorded by nobody here: the
worker holds `mark_unknown` (SA:467; Plan E ruling 6).
```

with:

```python
Replay rule (Plan D review focus 1): execution_grant is UNIQUE (run_id), so a second `create_incident` for the same run
finds the existing grant; if its attempt is RESOLVED the stored outcome is returned without touching the destination,
otherwise the same action id and bytes are re-sent and the destination's idempotent key answers. There is never a second
action id for one run. Through the tool, the stored branch is unreachable once the outcome is recorded: the run has left
APPROVED and EXECUTING, so `server.create_incident`'s `resolve_invocation` refuses the handle first (T15, Plan J ruling
6), which production never needed (the worker skips the call past EXECUTING). A direct caller
(tests/e2e/test_mcp_write_live.py), or an overlapping call that resolved its handle before the outcome was recorded,
still reaches it. A transport failure after SENT is reported as UNKNOWN and recorded by nobody here: the worker holds
`mark_unknown` (SA:467; Plan E ruling 6).
```

- [x] **Step 6: The live revision test**

Create `tests/e2e/test_migration_0009_live.py`:

```python
"""Revision 0009 against the per-session test database (OPS_LIVE=1; Plan J rulings 6 and 18).

Catches: a downgrade that leaves the bound `_resolve_handle` behind or restores it differently from a database that
never saw 0009 (or an upgrade that does not bring the bound body back); mcp-read's startup check passing on a
database at 0008; a handle whose job the superuser points at another run's job, or whose job is finished, still
resolving at the definer; and a resolution that ignores the run's state (an investigate handle once its run awaits
input), while the definer itself still answers for that run.
"""

import importlib.util
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from ops_core import persistence, settings
from ops_core.settings import Profile, Role
from ops_core.states import RunState
from ops_mcp_read.server import HANDLE_BINDING
from psycopg import sql
from psycopg.rows import dict_row

from tests.e2e.conftest import lease_for, purge_run, purge_tenant
from tests.e2e.test_definers_run_path_live import refused
from tests.e2e.test_fenced_definers_live import investigate_job, read_handle, resolve
from tests.e2e.test_migration_0007_live import FUNCTION_DETAILS, LEFTOVERS
from tests.e2e.test_migrations_and_persistence import new_run

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "app" / "versions"
SIGNATURE, MARKER = HANDLE_BINDING
RESOLVE = "SELECT * FROM app.resolve_invocation(%s, 'ops-worker')"
SCRATCH_PREFIX = "r008_"  # every scratch database this module creates; leftovers are dropped by prefix


def revision_0007() -> Any:
    """Revision 0007 loaded by path, for the `_resolve_handle` body 0009's downgrade restores."""
    spec = importlib.util.spec_from_file_location("live_rev_0007_j", VERSIONS / "0007_leases_fences.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def built_to_0008(superuser: settings.Postgres) -> dict[str, Any]:
    """`_resolve_handle`'s details as a database built straight to 0008 holds them (the 0007 module's pattern): a
    scratch database is created, upgraded by the applied revisions alone, read and dropped."""
    from scripts.skeleton import upgrade

    scratch = f"{SCRATCH_PREFIX}{uuid4().hex[:12]}"
    try:
        with psycopg.connect(superuser.conninfo(), autocommit=True, row_factory=dict_row) as admin:
            for row in admin.execute(LEFTOVERS, (SCRATCH_PREFIX,)).fetchall():
                admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(row["datname"])))
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(scratch)))
        target = settings.Postgres(superuser.host, superuser.port, superuser.user, scratch, superuser.password)
        upgrade("app", target, "0008_journal_outbox")
        with psycopg.connect(target.conninfo(), row_factory=dict_row) as conn:
            return dict(conn.execute(FUNCTION_DETAILS, (SIGNATURE,)).fetchone() or {})
    finally:
        with psycopg.connect(superuser.conninfo(), autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(scratch)))


async def details(conn: persistence.Conn) -> dict[str, Any]:
    cur = await conn.execute(FUNCTION_DETAILS, (SIGNATURE,))
    return dict(await cur.fetchone() or {})


async def test_the_round_trip_restores_0008(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    from scripts.skeleton import downgrade, migrate

    superuser = settings.superuser_postgres()
    mcp_read = await role_conn(Role.MCP_READ)
    head = await details(app_conn)
    assert MARKER in head["body"]
    await persistence.assert_function_text(mcp_read, SIGNATURE, MARKER)  # mcp-read starts on the head
    try:
        downgrade("app", superuser, "0008_journal_outbox")
        # The restored body is 0007's text exactly (its stored source is what lies between the dollar quotes), and its
        # definition, ACL, owner and settings are what a database that never saw 0009 holds.
        cur = await app_conn.execute("SELECT prosrc FROM pg_proc WHERE oid = %s::regprocedure", (SIGNATURE,))
        assert (await cur.fetchone())["prosrc"] == revision_0007().RESOLVE_HANDLE.split("$fn$")[1]
        assert await details(app_conn) == built_to_0008(superuser)
        with pytest.raises(persistence.PersistenceError, match="predates this service"):
            await persistence.assert_function_text(mcp_read, SIGNATURE, MARKER)  # mcp-read refuses 0008
    finally:
        assert migrate(Profile.TEST) == 0  # every later test needs the head
    assert await details(app_conn) == head  # the upgrade brings back exactly what the downgrade took


async def test_a_handle_resolves_only_for_its_own_runs_open_job(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """Ruling 6: the superuser (or a compromised worker; invocation_context has no RLS) points the handle's job at
    another run's job, then finishes the handle's own job; the definer refuses both, and the same handle resolves
    again in between, so each refusal is the binding's."""
    api, worker, mcp_read = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.MCP_READ)
    tenant, _, run = await new_run(app_conn, api=api)
    _, _, other = await new_run(app_conn, tenant, api=api)  # a second conversation and run in the same tenant
    try:
        job, other_job = await investigate_job(app_conn, run), await investigate_job(app_conn, other)
        handle = await read_handle(worker, run, job, await lease_for(worker, run))
        hashed = persistence.handle_hash(handle)
        assert (await resolve(mcp_read, handle)).job_id == job
        await app_conn.execute(
            "UPDATE app.invocation_context SET job_id = %s WHERE handle_sha256 = %s", (other_job, hashed)
        )
        assert await refused(mcp_read, RESOLVE, (handle,)) == "OC008"  # another run's job
        await app_conn.execute("UPDATE app.invocation_context SET job_id = %s WHERE handle_sha256 = %s", (job, hashed))
        assert (await resolve(mcp_read, handle)).job_id == job  # its own job again: resolves
        await app_conn.execute("UPDATE app.jobs SET done_at = app.current_time() WHERE id = %s", (job,))
        assert await refused(mcp_read, RESOLVE, (handle,)) == "OC008"  # its job finished
    finally:
        await purge_run(app_conn, run)
        await purge_run(app_conn, other)
        await purge_tenant(app_conn, tenant)


async def test_the_allowlist_follows_the_run_state(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    """Ruling 6: an investigate handle is honoured while its run is QUEUED or RETRIEVING (where the worker calls
    mcp-read) and refused once the run awaits input, though the definer still resolves it: the run-state rule is
    Python's (erratum 19)."""
    api, worker, mcp_read = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.MCP_READ)
    tenant, _, run = await new_run(app_conn, api=api)
    try:
        handle = await read_handle(worker, run, await investigate_job(app_conn, run), await lease_for(worker, run))
        assert (await resolve(mcp_read, handle)).run_state is RunState.QUEUED
        async with worker.transaction():  # the worker role's own function, as tests/e2e/test_admission_live.py does
            await worker.execute("SELECT app.transition_run(%s, 'QUEUED', 'RETRIEVING', NULL, 1, '{}')", (run,))
        assert (await resolve(mcp_read, handle)).run_state is RunState.RETRIEVING
        async with worker.transaction():
            await worker.execute("SELECT app.transition_run(%s, 'RETRIEVING', 'AWAITING_INPUT', NULL, 2, '{}')", (run,))
        cur = await mcp_read.execute(RESOLVE, (handle,))
        assert (await cur.fetchone())["run_state"] == "AWAITING_INPUT"  # the definer answers ...
        with pytest.raises(persistence.HandleRejected):  # ... and the allowlist refuses
            await resolve(mcp_read, handle)
    finally:
        await purge_run(app_conn, run)
        await purge_tenant(app_conn, tenant)
```

Run (dev stack up, no skeleton process running):

```bash
OPS_LIVE=1 PROFILE=test PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_migration_0009_live.py -q
```

Expected: `3 passed` (the round trip builds and drops a scratch database prefixed `r008_`). This count is arithmetic,
not measured: the plan's dry run cannot run live steps. A failure in the binding test is a finding against the revision,
not a reason to weaken an assertion: stop and report.

- [x] **Step 7: Gates and commit**

Format, lint and count characters on every file of this task (the revision after the ISC004 pass).

Run: `PYTHONUTF8=1 uv run python scripts/check.py`
Expected: `CHECK: GREEN`; pytest `1071 passed, 157 skipped` (1057 + 13 in `tests/plan_j` + 1 parametrised revision; the
3 new live tests skip).

Run: `PYTHONUTF8=1 uv run python scripts/check.py --profile test`
Expected: `CHECK: GREEN`; pytest `1207 passed, 21 skipped` (arithmetic, not measured: the dev count plus the 136
live-gated tests, 157 − 21; R105 and the R006 populated upgrade run with their Step 5 edits). Then
`git checkout -- reports/bootstrap reports/skeleton reports/auth reports/admission reports/leases reports/events
reports/outbox`.

Run: `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`
Expected: exit 0.

```bash
git add migrations/app/versions/0009_handle_binding.py core/src/ops_core/persistence.py core/src/ops_core/jobs.py
git add mcp-read/src/ops_mcp_read/server.py tests/plan_j tests/plan_d/test_persistence_pure.py
git add tests/plan_e/test_persistence_errors.py tests/plan_e/test_transitions_table.py
git add tests/e2e/test_r105_walking_skeleton.py tests/e2e/test_migration_0009_live.py
git add tests/e2e/test_migrations_and_persistence.py mcp-write/src/ops_mcp_write/execution.py
git commit -m "feat(migrations): revision 0009 binds a handle to its run's open job; the run-state allowlist (T15)"
```

---

### Task 3: Live evidence at mcp-read over HTTP — handles, the allowlist, the ACL, the protocol version, the logs

**Files:**
- Create: `tests/e2e/test_mcp_read_t15_live.py`
- Modify: `tests/plan_b/test_evidence.py:1-7` (docstring), `:18-27` (`EVIDENCE_ROOTS`)

**Requirements:** R027 ("Replay with other workload/run/expired fence/tool; server rejects; handle absent from
model/logs"), R085 ("Worker-chosen tools ignored; handle used with a different azp rejected"), R131's read half (the
`pg_proc` ACL, a recover and an execute handle at mcp-read), T15 DoD 2-4; rulings 5, 10, 11, 13 and 22. This task writes
no production code: Tasks 1 and 2 built what it proves, so its tests pass the first time they run. The other-azp half of
R027/R085 is proved at the definer by the existing `tests/e2e/test_definers_write_path_live.py::
test_resolve_invocation_binds_server_azp_expiry_and_revocation` (a read handle resolved with azp `ops-web` is `OC008`)
and at the verifier by Task 1's synthetic tokens; no realm client other than `ops-worker` carries mcp-read's audience,
so no live token can bring another azp to the definer over HTTP.

**Interfaces:**
- Consumes: `ops_mcp_read.server.production_app`; `ops_core.mcp_protocol.PROTOCOL_VERSION`; `persistence.mint_handle`;
  the e2e fixtures `migrated`, `app_conn`, `role_conn`, `secret`, `lease_for`, `expire_lease`, `purge_run`, `new_run`,
  `refused`,
  `investigate_job`, `read_handle`, `approved_run` (`tests.e2e.test_mcp_write_live`); `privileges.DEFINER_FUNCTIONS`.
- Produces: in `tests.e2e.test_mcp_read_t15_live`: `QUERY`, `UVICORN`, `free_port()`, `guarded(server)`,
  `serving(log_level="warning")`, `worker_token(secret)`, `call(url, token, handle, tool=…, arguments=…)`,
  `raw_headers(token, version, method="tools/list")`, `tools_list(meta_version)` (Task 4
  imports `QUERY`, `free_port`, `raw_headers`, `tools_list`, `worker_token`); `reports/mcp-read/t15-mcp-read.txt`
  (written only when all five tests passed).

- [x] **Step 1: Scan the new evidence root for secrets**

Edit 1 (`tests/plan_b/test_evidence.py`, docstring), replace:

```python
`reports/admission` (T12's durable-admission evidence), `reports/leases` (T13's lease, heartbeat and stress evidence)
and `reports/events` and `reports/outbox` (T14's journal and outbox evidence) are scanned the same way.
```

with:

```python
`reports/admission` (T12's durable-admission evidence), `reports/leases` (T13's lease, heartbeat and stress evidence),
`reports/events` and `reports/outbox` (T14's journal and outbox evidence) and `reports/mcp-read` (T15's handle,
token and independent-client evidence) are scanned the same way.
```

Edit 2 (`tests/plan_b/test_evidence.py`, `EVIDENCE_ROOTS`), replace:

```python
    Path("reports/events"),
    Path("reports/outbox"),
)
```

with:

```python
    Path("reports/events"),
    Path("reports/outbox"),
    Path("reports/mcp-read"),
)
```

- [x] **Step 2: Write the live cases**

Create `tests/e2e/test_mcp_read_t15_live.py`:

```python
"""mcp-read's T15 cases over a real socket with Keycloak's tokens (OPS_LIVE=1; R027, R085, R131 read half, T15 DoD 2-4;
Plan J rulings 5, 10, 11 and 22).

The server is `production_app()` under uvicorn on a free loopback port in the test's own event loop; the
independent-process run is tests/e2e/test_mcp_read_process_live.py. Catches: a handle that still answers once its job
is pointed at another run's job, past its expiry, under a lapsed lease or a moved fence, after its release
(revocation), or once its run left the job type's states; an execute or recover handle answered at mcp-read, also when
its stored `server` column lies; a tool mcp-read does not register answered; an EXECUTE grant `mcp_read` holds beyond
`current_time` and `resolve_invocation`; a POST whose protocol version is absent, handshake-era or contradicted by its
`_meta` reaching the tool; and a raw handle in any log record of the exchange (uvicorn's included, at DEBUG). Every
refusal of a presented handle must be the one plain `INVALID_HANDLE` envelope, with no hint of which check failed and
never an `action_id` (SA:354-355).
"""

import asyncio
import json
import logging
import socket
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
import uvicorn
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_types import CallToolResult
from ops_core import persistence, privileges, settings
from ops_core.jobs import Server
from ops_core.mcp_protocol import PROTOCOL_VERSION
from ops_core.settings import Role
from ops_core.tokens import WorkloadTokenSource
from ops_mcp_read.server import production_app

from tests.e2e.conftest import expire_lease, lease_for, purge_run
from tests.e2e.test_definers_run_path_live import refused
from tests.e2e.test_fenced_definers_live import investigate_job, read_handle
from tests.e2e.test_mcp_write_live import approved_run
from tests.e2e.test_migrations_and_persistence import new_run

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")  # the seeded tenant: only seeded tenants have a fixture corpus
QUERY = {"query": "reviewer inspect exact content", "limit": 2, "mode": "lexical"}
REFUSAL = {"code": "INVALID_HANDLE", "message": "invocation handle rejected", "retryable": False}
EVIDENCE = Path("reports/mcp-read/t15-mcp-read.txt")
UVICORN = ("uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi")
EXPECTED_LINES = 5  # one per test below


@pytest.fixture(scope="module")
def lines() -> Iterator[list[str]]:
    out = [f"T15 mcp-read — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"]
    yield out
    if len(out) != 1 + EXPECTED_LINES:  # a failed or partial run leaves the committed file as it was
        return
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


def free_port() -> int:
    """A loopback port nobody holds right now (the skeleton's own mcp-read may be up on 8081)."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


async def guarded(server: uvicorn.Server) -> None:
    """`server.serve()`, with a failed start turned into an ordinary error: uvicorn answers a lifespan failure (a
    database without revision 0009, keys it cannot load) with `sys.exit`, and a SystemExit escaping a task leaves the
    event loop at once, so the test's `finally` (its purges) would never run."""
    try:
        await server.serve()
    except SystemExit as exc:
        raise RuntimeError("mcp-read did not start; see the log above") from exc


@asynccontextmanager
async def serving(log_level: str = "warning") -> AsyncIterator[str]:
    """`production_app()` on a free loopback port, logging as `serve_app` does (`log_config=None`, so every record
    reaches the root logger) at `log_level` (`serve_app` pins "warning"; never "trace", at which uvicorn's message
    logger writes every request's headers); its URL; stopped in `finally` (uvicorn's own shutdown, never a cancel)."""
    port = free_port()
    config = uvicorn.Config(production_app(), host="127.0.0.1", port=port, log_level=log_level, log_config=None)
    server = uvicorn.Server(config)
    task = asyncio.create_task(guarded(server))
    try:
        while not server.started:
            if task.done():
                task.result()  # a failed start raises its RuntimeError here instead of waiting for ever
            await asyncio.sleep(0.05)
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        server.should_exit = True
        await asyncio.wait({task})  # settled, never cancelled; a failed start was raised above
    # Reached only when the body did not raise: a failure after the start (the main loop, the shutdown) surfaces here
    # rather than only in uvicorn's log.
    failure = None if task.cancelled() else task.exception()
    if failure is not None:
        raise failure


async def worker_token(secret: Callable[[str], str]) -> str:
    kcs = settings.keycloak()
    source = WorkloadTokenSource(
        token_url=kcs.token_url, client_id="ops-worker", client_secret=secret("kc_client_secret_ops_worker")
    )
    return await source.token()


async def call(
    url: str, token: str, handle: str, tool: str = "search_procedures", arguments: dict[str, Any] = QUERY
) -> CallToolResult:
    """One tool call with the official client pinned to 2026-07-28, the token and the handle as headers."""
    headers = {"Authorization": f"Bearer {token}", "X-Ops-Invocation": handle}
    async with (
        httpx2.AsyncClient(headers=headers) as http,
        Client(streamable_http_client(url, http_client=http), mode=PROTOCOL_VERSION) as client,
    ):
        return await client.call_tool(tool, arguments)


def assert_refused(result: CallToolResult) -> None:
    """The one plain refusal: an envelope, not a transport error; no hint of the cause and no action id."""
    doc = result.structured_content
    assert not result.is_error and isinstance(doc, dict)
    assert doc["status"] == "error" and doc["error"] == REFUSAL and doc["data"] is None
    assert "action_id" not in json.dumps(doc)


def assert_answered(result: CallToolResult) -> None:
    doc = result.structured_content
    assert not result.is_error and isinstance(doc, dict) and doc["status"] == "ok"
    assert doc["data"]["results"][0]["evidence_id"] == "ALPHA-INCIDENT:v2:review"


async def set_job(app_conn: persistence.Conn, handle: str, job: UUID) -> None:
    """The superuser rewrites the handle's job (invocation_context has no RLS: SA:523; a compromised worker could)."""
    await app_conn.execute(
        "UPDATE app.invocation_context SET job_id = %s WHERE handle_sha256 = %s", (job, persistence.handle_hash(handle))
    )


async def test_r027_a_handle_dies_with_its_job_expiry_lease_fence_and_release(
    app_conn: persistence.Conn, role_conn: RoleConn, secret: Callable[[str], str], lines: list[str]
) -> None:
    """Each cause is undone before the next (the job put back, the clock reset), and the same handle answers again
    in between, so each refusal is that cause's."""
    api, worker, harness = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.TEST_HARNESS)
    _, _, run = await new_run(app_conn, ALPHA, api=api)
    _, _, other = await new_run(app_conn, ALPHA, api=api)
    token = await worker_token(secret)
    try:
        async with serving() as url:
            job = await investigate_job(app_conn, run)
            first = await lease_for(worker, run, owner="t15-first", seconds=600)  # outlives the clock step below
            handle = await read_handle(worker, run, job, first)
            assert_answered(await call(url, token, handle))
            await set_job(app_conn, handle, await investigate_job(app_conn, other))
            assert_refused(await call(url, token, handle))  # other run: the job named is another run's
            await set_job(app_conn, handle, job)
            assert_answered(await call(url, token, handle))
            try:
                await harness.execute("UPDATE app.test_clock SET clock_offset = interval '120 seconds'")
                assert_refused(await call(url, token, handle))  # expired: 60 s TTL, the 600 s lease still live
            finally:
                await harness.execute("UPDATE app.test_clock SET clock_offset = interval '0'")
            assert_answered(await call(url, token, handle))
            await expire_lease(app_conn, run)
            assert_refused(await call(url, token, handle))  # a lapsed lease
            second = await lease_for(worker, run, owner="t15-second", seconds=600)
            assert_refused(await call(url, token, handle))  # a live lease again, but the fence moved
            fresh = await read_handle(worker, run, job, second)
            assert_answered(await call(url, token, fresh))
            async with worker.transaction():  # what the job's release does: this fence's handles and older ones
                assert await persistence.revoke_handles(worker, run, second.fence) == 2  # erratum 55
            assert_refused(await call(url, token, fresh))  # replayed after its release
        lines.append("R027 refused over HTTP: other-run job, expired, lapsed lease, moved fence, released; ok between")
    finally:
        await purge_run(app_conn, run)
        await purge_run(app_conn, other)


async def test_r085_r131_the_server_derives_tool_server_and_state_from_the_job(
    app_conn: persistence.Conn, role_conn: RoleConn, secret: Callable[[str], str], lines: list[str]
) -> None:
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    _, run, _, execute_handle = await approved_run(app_conn, api=api, worker=worker)
    _, _, read_run = await new_run(app_conn, ALPHA, api=api)
    token = await worker_token(secret)
    try:
        # A recover job of the same run, staged by the superuser as mark_unknown would queue one (T15 DoD 4 names
        # execute and recover handles); its handle is minted under the lease approved_run took.
        recover = uuid4()
        await app_conn.execute(
            "INSERT INTO app.jobs (id, type, tenant_id, run_id, dedup_key) VALUES (%s, 'recover', %s, %s, %s)",
            (recover, ALPHA, run, f"{uuid4()}:timeout"),
        )
        cur = await app_conn.execute("SELECT fence FROM app.run_lease WHERE run_id = %s", (run,))
        fence = int((await cur.fetchone())["fence"])
        async with worker.transaction():
            recover_handle = await persistence.mint_handle(
                worker, run_id=run, job_id=recover, server=Server.WRITE, azp="ops-worker", fence=fence
            )
        async with serving() as url:
            assert_refused(await call(url, token, recover_handle))  # a recover handle at mcp-read (R131, DoD 4)
            assert_refused(await call(url, token, execute_handle))  # an execute handle at mcp-read (R131)
            await app_conn.execute(
                "UPDATE app.invocation_context SET server = 'read' WHERE handle_sha256 = %s",
                (persistence.handle_hash(execute_handle),),
            )
            assert_refused(await call(url, token, execute_handle))  # the lying column: the job type says write
            handle = await read_handle(
                worker, read_run, await investigate_job(app_conn, read_run), await lease_for(worker, read_run)
            )
            assert_answered(await call(url, token, handle))
            unknown = await call(url, token, handle, tool="create_incident", arguments={"proposal_id": str(uuid4())})
            # A tool outside the read jobs' set is not registered here at all: the SDK's unknown-tool error.
            assert unknown.is_error and "Unknown tool" in str(unknown.content)
            async with worker.transaction():  # the worker role's own function, as test_admission_live does
                await worker.execute(
                    "SELECT app.transition_run(%s, 'QUEUED', 'RETRIEVING', NULL, 1, '{}')", (read_run,)
                )
                await worker.execute(
                    "SELECT app.transition_run(%s, 'RETRIEVING', 'AWAITING_INPUT', NULL, 2, '{}')", (read_run,)
                )
            assert_refused(await call(url, token, handle))  # the run left investigate's states
        lines.append(
            "R085/R131 refused over HTTP: recover and execute handles, lying server column, run state;"
            " unknown tool: SDK"
        )
    finally:
        await purge_run(app_conn, run)  # the seeded tenant ALPHA stays
        await purge_run(app_conn, read_run)


async def test_r131_mcp_read_can_execute_no_write_path_function(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    """The pg_proc ACL as it is today: `current_time` (erratum 15) and `resolve_invocation`; `asset_scope` and
    `search_procedures_scoped` join with their owners, T16 and T17 (erratum 72)."""
    cur = await app_conn.execute(
        "SELECT p.proname AS name, has_function_privilege('mcp_read', p.oid, 'EXECUTE') AS allowed"
        " FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'app'"
    )
    rows = await cur.fetchall()
    assert {row["name"] for row in rows if row["allowed"]} == {"current_time", "resolve_invocation"}
    others = set(privileges.DEFINER_FUNCTIONS) - {"current_time", "resolve_invocation"}
    assert others <= {row["name"] for row in rows}  # every other definer exists, so the line above is not vacuous
    mcp_read = await role_conn(Role.MCP_READ)
    assert await refused(mcp_read, "SELECT * FROM app.grant_execution(%s, %s)", ("not-a-handle", uuid4())) == "42501"
    lines.append(f"R131 read half: mcp_read EXECUTE = current_time, resolve_invocation; {len(others)} others refused")


def raw_headers(token: str, version: str | None, method: str = "tools/list") -> dict[str, str]:
    out = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "Mcp-Method": method,
    }
    if version is not None:
        out["MCP-Protocol-Version"] = version
    return out


def tools_list(meta_version: str) -> dict[str, Any]:
    meta = {
        "io.modelcontextprotocol/protocolVersion": meta_version,
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    return {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": meta}}


async def test_the_protocol_version_is_checked_on_every_request(
    migrated: None, secret: Callable[[str], str], lines: list[str]
) -> None:
    """Ruling 5: raw POSTs with a valid worker token, so authentication passes and only the version decides."""
    token = await worker_token(secret)
    async with serving() as url, httpx2.AsyncClient() as http:
        absent = await http.post(url, json=tools_list("2026-07-28"), headers=raw_headers(token, None))
        legacy = await http.post(url, json=tools_list("2025-11-25"), headers=raw_headers(token, "2025-11-25"))
        mismatch = await http.post(url, json=tools_list("2025-11-25"), headers=raw_headers(token, "2026-07-28"))
        listed = await http.post(url, json=tools_list("2026-07-28"), headers=raw_headers(token, "2026-07-28"))
    assert (absent.status_code, absent.json()["error"]["code"]) == (400, -32022)  # the guard
    assert (legacy.status_code, legacy.json()["error"]["code"]) == (400, -32022)  # the guard
    assert "2025-11-25" not in legacy.text  # never echoed
    assert (mismatch.status_code, mismatch.json()["error"]["code"]) == (400, -32020)  # the SDK's HEADER_MISMATCH
    assert listed.status_code == 200 and [t["name"] for t in listed.json()["result"]["tools"]] == ["search_procedures"]
    lines.append("protocol: absent 400/-32022, 2025-11-25 400/-32022, header/_meta mismatch 400/-32020, matching 200")


async def test_r027_no_log_record_carries_the_handle(
    app_conn: persistence.Conn,
    role_conn: RoleConn,
    secret: Callable[[str], str],
    caplog: pytest.LogCaptureFixture,
    lines: list[str],
) -> None:
    """Every record of an answered call, a refused one and a refused raw POST, with the server's loggers and uvicorn's
    at DEBUG and no redaction filter installed: the handle is in none of them (SA:566). uvicorn's TRACE level, which
    logs request headers, is enabled nowhere (`serve_app` pins "warning"); this test does not use it either.

    If this test fails, pytest's "Captured log call" section prints the captured records, the offending one included:
    treat that output as sensitive. The handle is a test handle on `ops_test`, revoked inside the test, and the worker
    token expires within minutes, so nothing needs rotating."""
    caplog.set_level(logging.DEBUG)
    # uvicorn's loggers, as Config left them: an earlier test's default dictConfig stops "uvicorn" and "uvicorn.access"
    # propagating to the root logger caplog listens on, and Config(log_level=...) sets their levels process-wide.
    saved = {name: (logging.getLogger(name).level, logging.getLogger(name).propagate) for name in UVICORN}
    worker = await role_conn(Role.WORKER)
    _, _, run = await new_run(app_conn, ALPHA, api=await role_conn(Role.API))
    token = await worker_token(secret)
    try:
        for name in UVICORN:  # inside the try: the finally below always puts them back
            logging.getLogger(name).propagate = True
        async with serving(log_level="debug") as url:
            lease = await lease_for(worker, run)
            handle = await read_handle(worker, run, await investigate_job(app_conn, run), lease)
            assert_answered(await call(url, token, handle))
            async with worker.transaction():
                await persistence.revoke_handles(worker, run, lease.fence)
            assert_refused(await call(url, token, handle))
            async with httpx2.AsyncClient() as http:
                raw = {**raw_headers(token, "2025-11-25"), "X-Ops-Invocation": handle}
                assert (await http.post(url, json=tools_list("2025-11-25"), headers=raw)).status_code == 400
        texts = [record.getMessage() + (record.exc_text or "") for record in caplog.records]
        names = {record.name.split(".")[0] for record in caplog.records}
        assert {"uvicorn", "mcp", "httpx2"} <= names  # the server's HTTP layer, the SDK and the client were captured
        carrying = [i for i, text in enumerate(texts) if handle in text]  # indexes only: never the handle itself
        assert carrying == []
        lines.append(
            f"R027 logs: {len(texts)} records at DEBUG (uvicorn, SDK, client) across ok, refused and raw calls; none"
            " holds the handle"
        )
    finally:
        for name, (level, propagate) in saved.items():
            logging.getLogger(name).setLevel(level)
            logging.getLogger(name).propagate = propagate
        await purge_run(app_conn, run)
```

- [x] **Step 3: Run it**

Run (dev stack up, no skeleton process running):

```bash
OPS_LIVE=1 PROFILE=test PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_mcp_read_t15_live.py -q
```

Expected: `5 passed`, and `reports/mcp-read/t15-mcp-read.txt` exists with six lines. This count is arithmetic, not
measured: the plan's dry run cannot run live steps. A refusal that does not come back as the plain envelope, or a
record that carries the handle, is a finding against Tasks 1-2 or the SDK: stop and report, never weaken an assertion.

- [x] **Step 4: Gates and commit**

Format, lint and count characters on `tests/e2e/test_mcp_read_t15_live.py` and `tests/plan_b/test_evidence.py`.

Run: `PYTHONUTF8=1 uv run python scripts/check.py`
Expected: `CHECK: GREEN`; pytest `1071 passed, 162 skipped` (the 5 new live tests skip).

Run: `PYTHONUTF8=1 uv run python scripts/check.py --profile test`
Expected: `CHECK: GREEN`; pytest `1212 passed, 21 skipped` (arithmetic, not measured: 1071 plus the 141 live-gated
tests, 162 − 21). Then `git checkout -- reports/bootstrap reports/skeleton reports/auth reports/admission
reports/leases reports/events reports/outbox`.

Run: `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`
Expected: exit 0.

```bash
git add tests/e2e/test_mcp_read_t15_live.py tests/plan_b/test_evidence.py
git commit -m "test(e2e): handle, allowlist, ACL, version and log cases at mcp-read over HTTP (R027, R085, R131)"
```

`reports/mcp-read/` stays uncommitted until Task 5 (it is rewritten by every live run).

---

### Task 4: The independent process — the official client over the network, and foreign tokens refused

**Files:**
- Create: `tests/e2e/test_mcp_read_process_live.py`

**Requirements:** R025's read half ("An independent process lists and calls tools on both mcp-read and mcp-write over
the network": mcp-read here, mcp-write with T47), R031's network half ("Install locked SDKs and run network tests"),
R026 ("Use valid token for another service; resource server rejects it without downstream forwarding": each foreign
token presents a valid handle on a real `tools/call`, so the refusal is shown to come before the tool), T15 DoD 1-2;
rulings 12, 14 and 15; BS:378 and BS:589 ("Use a real remote client in integration tests; an in-process call is not
sufficient"). No production code: its tests pass the first time they run.

**Interfaces:**
- Consumes: `scripts.skeleton.process_environment()`, `healthy(url)`; Task 3's `QUERY`, `free_port`, `raw_headers`,
  `tools_list`, `worker_token`; `tests.plan_b.live.kc.token_password`; `WorkloadTokenSource`; the e2e fixtures
  `app_conn`, `role_conn`, `secret`, `lease_for`, `purge_run`, `new_run`, `investigate_job`, `read_handle`;
  pytest's `tmp_path`.
- Produces: `mcp_read_process(log)` (an async context manager yielding the child's MCP URL), `tools_call()`;
  `reports/mcp-read/t15-independent-client.txt` (written only when both tests passed).

- [x] **Step 1: Write the independent-process tests**

Create `tests/e2e/test_mcp_read_process_live.py`:

```python
"""mcp-read as an independent process, reached over the network by the official SDK client (OPS_LIVE=1; R025 read
half, R031 network half, R026, T15 DoD 1-2; Plan J rulings 12, 14 and 15).

`python -m ops_mcp_read` runs as a child process on a free loopback port with the environment the skeleton gives its
children (`scripts.skeleton.process_environment`: the test profile and databases this session exported, secrets as
files named by `OPS_SECRETS_DIR`, nothing secret on the command line), and is terminated in `finally`. Catches: a
server that only works in-process (BUILD_SPEC §10: "an in-process call is not sufficient"), a tool list that differs
from the registered tool or advertises extra arguments, a locked SDK version other than AM-30's, a token for another
audience or client (the persona token stands in for a browser token, ruling 14: no real `ops-web` access token is
minted, the API stores none and minting one needs its client secret; a missing `aud` is the synthetic case in
tests/plan_j/test_verifier_t15.py, ruling 15) answered with anything but 401 on a `tools/call` that carries a valid
handle (the refusal comes before the tool and the handle lookup; mcp-read forwards nothing downstream in T15), and a
handle in the child's own log. That log is written through the service's redaction filter (`serve()` installs it
first) at uvicorn's "warning" level, so its check is weaker than the in-process DEBUG capture of
tests/e2e/test_mcp_read_t15_live.py, which runs with no filter at all.
"""

import asyncio
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from ops_core import persistence, settings
from ops_core.mcp_protocol import PROTOCOL_VERSION
from ops_core.settings import Role
from ops_core.tokens import WorkloadTokenSource

from scripts.skeleton import healthy, process_environment
from tests.e2e.conftest import lease_for, purge_run
from tests.e2e.test_fenced_definers_live import investigate_job, read_handle
from tests.e2e.test_mcp_read_t15_live import QUERY, free_port, raw_headers, tools_list, worker_token
from tests.e2e.test_migrations_and_persistence import new_run
from tests.plan_b.live import kc

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
ROOT = Path(__file__).resolve().parents[2]
ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")  # the seeded tenant: only seeded tenants have a fixture corpus
EVIDENCE = Path("reports/mcp-read/t15-independent-client.txt")
EXPECTED_LINES = 2  # one per test below


@pytest.fixture(scope="module")
def lines() -> Iterator[list[str]]:
    out = [f"T15 independent client — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"]
    yield out
    if len(out) != 1 + EXPECTED_LINES:  # a failed or partial run leaves the committed file as it was
        return
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


@asynccontextmanager
async def mcp_read_process(log: Path) -> AsyncIterator[str]:
    """The server as a child process; its URL once `/health/ready` answers 200 (keys loaded, database reachable,
    revision 0009 present). Terminated in `finally`, killed if it outlives 15 s; its output goes to `log`."""
    port = free_port()
    env = process_environment()  # .env-derived settings over this session's environment: PROFILE=test, ops_test
    env["OPS_MCP_READ_PORT"] = str(port)
    with log.open("ab") as out:
        # Off the loop (ruff ASYNC220): asyncio's own subprocesses need the Proactor loop, which psycopg refuses.
        child = await asyncio.to_thread(
            subprocess.Popen,
            [sys.executable, "-m", "ops_mcp_read"],
            env=env,
            stdout=out,
            stderr=subprocess.STDOUT,
            cwd=ROOT,
        )
        try:
            deadline = time.monotonic() + 60
            while not await asyncio.to_thread(healthy, f"http://127.0.0.1:{port}/health/ready"):
                assert child.poll() is None, "mcp-read exited before it was ready"
                assert time.monotonic() < deadline, "mcp-read was not ready within 60 s"
                await asyncio.sleep(0.25)
            yield f"http://127.0.0.1:{port}/mcp"
        finally:
            if child.poll() is None:
                child.terminate()  # TerminateProcess on Windows, as the skeleton stops its children
            try:
                await asyncio.to_thread(child.wait, 15)
            except subprocess.TimeoutExpired:
                child.kill()
                await asyncio.to_thread(child.wait)


async def test_r025_an_independent_client_lists_and_calls_over_the_network(
    app_conn: persistence.Conn, role_conn: RoleConn, secret: Callable[[str], str], tmp_path: Path, lines: list[str]
) -> None:
    worker = await role_conn(Role.WORKER)
    _, _, run = await new_run(app_conn, ALPHA, api=await role_conn(Role.API))
    token = await worker_token(secret)
    log = tmp_path / "mcp-read.log"
    try:
        async with mcp_read_process(log) as url:
            handle = await read_handle(worker, run, await investigate_job(app_conn, run), await lease_for(worker, run))
            headers = {"Authorization": f"Bearer {token}", "X-Ops-Invocation": handle}
            async with (
                httpx2.AsyncClient(headers=headers) as http,
                Client(streamable_http_client(url, http_client=http), mode=PROTOCOL_VERSION) as client,
            ):
                tools = (await client.list_tools()).tools
                result = await client.call_tool("search_procedures", QUERY)
        assert [tool.name for tool in tools] == ["search_procedures"]
        assert tools[0].input_schema["additionalProperties"] is False
        doc = result.structured_content
        assert not result.is_error and isinstance(doc, dict) and doc["status"] == "ok"
        assert doc["data"]["results"][0]["evidence_id"] == "ALPHA-INCIDENT:v2:review"
        leaked = handle in log.read_text(encoding="utf-8", errors="replace")
        assert not leaked  # the child's own log, written through its redaction filter, never holds the handle
        assert (version("mcp"), version("mcp-types")) == ("2.3.0", "2.3.0")  # AM-30's lock, R031
        lines.append("R025/R031: child process; official client mode 2026-07-28 listed [search_procedures], called ok")
    finally:
        await purge_run(app_conn, run)


def tools_call() -> dict[str, Any]:
    """A raw `tools/call` of `search_procedures` in the 2026-07-28 envelope (the shape Task 1 measured in-process)."""
    call = tools_list(PROTOCOL_VERSION)
    call["method"] = "tools/call"
    call["params"].update({"name": "search_procedures", "arguments": QUERY})
    return call


async def test_r026_foreign_tokens_are_refused_before_the_tool(
    app_conn: persistence.Conn, role_conn: RoleConn, secret: Callable[[str], str], tmp_path: Path, lines: list[str]
) -> None:
    """Each foreign token presents a valid handle on a real tool call and gets 401; the same call with the worker's
    token then answers with data, so the refusals are the tokens' and come before the tool and the handle."""
    kcs = settings.keycloak()
    persona = kc.token_password(kcs.base_url, "ops-dev-direct", "alex", secret("kc_persona_alex_password"))
    foreign = {
        "persona (aud ops-api; the browser stand-in)": persona["access_token"],
        "ops-mcp-write (aud incident-sim)": await WorkloadTokenSource(
            token_url=kcs.token_url, client_id="ops-mcp-write", client_secret=secret("kc_client_secret_ops_mcp_write")
        ).token(),
        "ops-mcp-read (aud asset-sim)": await WorkloadTokenSource(
            token_url=kcs.token_url, client_id="ops-mcp-read", client_secret=secret("kc_client_secret_ops_mcp_read")
        ).token(),
    }
    token = await worker_token(secret)
    worker = await role_conn(Role.WORKER)
    _, _, run = await new_run(app_conn, ALPHA, api=await role_conn(Role.API))
    try:
        async with mcp_read_process(tmp_path / "mcp-read.log") as url, httpx2.AsyncClient() as http:
            handle = await read_handle(worker, run, await investigate_job(app_conn, run), await lease_for(worker, run))

            def headers(bearer: str) -> dict[str, str]:
                base = raw_headers(bearer, PROTOCOL_VERSION, method="tools/call")
                return {**base, "Mcp-Name": "search_procedures", "X-Ops-Invocation": handle}

            answers = {}
            for name, value in foreign.items():
                response = await http.post(url, json=tools_call(), headers=headers(value))
                answers[name] = (response.status_code, 'error="invalid_token"' in response.headers["www-authenticate"])
            accepted = await http.post(url, json=tools_call(), headers=headers(token))
        assert answers == {name: (401, True) for name in foreign}  # names and statuses only: never a token
        assert accepted.status_code == 200  # the worker's token, the same call and handle: the refusals are the tokens'
        assert accepted.json()["result"]["structuredContent"]["status"] == "ok"  # the handle was good all along
        lines.append(
            "R026: persona, ops-mcp-write and ops-mcp-read tokens 401 invalid_token on a tools/call with a valid"
            " handle; the worker's token answers ok"
        )
    finally:
        await purge_run(app_conn, run)
```

- [x] **Step 2: Run it**

Run (dev stack up, no skeleton process running):

```bash
OPS_LIVE=1 PROFILE=test PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_mcp_read_process_live.py -q
```

Expected: `2 passed` (each test starts and stops its own child process), and
`reports/mcp-read/t15-independent-client.txt` exists with three lines. Arithmetic, not measured: the plan's dry run
cannot run live steps. `uv run python scripts/skeleton.py status` afterwards shows every process down (no child
outlived its test).

- [x] **Step 3: Gates and commit**

Format, lint and count characters on `tests/e2e/test_mcp_read_process_live.py`.

Run: `PYTHONUTF8=1 uv run python scripts/check.py`
Expected: `CHECK: GREEN`; pytest `1071 passed, 164 skipped` (the 2 new live tests skip).

Run: `PYTHONUTF8=1 uv run python scripts/check.py --profile test`
Expected: `CHECK: GREEN`; pytest `1214 passed, 21 skipped` (arithmetic, not measured: 1071 plus the 143 live-gated
tests, 164 − 21). Then `git checkout -- reports/bootstrap reports/skeleton reports/auth reports/admission
reports/leases reports/events reports/outbox`.

Run: `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`
Expected: exit 0.

```bash
git add tests/e2e/test_mcp_read_process_live.py
git commit -m "test(e2e): mcp-read as an independent process, the official client over the network (R025, R026, R031)"
```

---

### Task 5: Close-out — records, acceptance rows, errata 72-81, the runbook, final gates

**Files:**
- Create: `docs/runbooks/mcp-read.md`
- Modify: `core/src/ops_core/routing.py:362`, `scripts/build_schemas.py:856` (the two `TODO(T15)` markers),
  `tests/plan_c/test_schema_conformance.py:45`, `:58` (two skip reasons), `handoff/tasks.json` (T15 → `DONE`, one
  review note), `handoff/acceptance-matrix.json` (R025, R026, R027, R031, R085, R131), `handoff/BUILD_BACKLOG.md` (T15
  checked, one review note), `SESSION_STATE.md` (the "Next task" line, the repository line, a "Plan J executed"
  section with the walking-skeleton heading restored, the dev database state, the owner inputs, the exact next step),
  `STATUS.md` (an update section), `docs/ARCHITECTURE.md` (a new section before "Where the code will live"),
  `docs/PROJECT_HISTORY.md` (the mcp-read plan's section), `README.md:5` (status line), `mcp-read/README.md`
  ("Trusts", "Runs"), `mcp-write/README.md` ("Runs"), `worker/README.md` ("Runs"), this plan (its checkboxes); the
  evidence files `reports/mcp-read/*.txt` and the rewritten `reports/skeleton`, `reports/admission`,
  `reports/leases`, `reports/events`, `reports/outbox` from the final live run

**Requirements:** the T15 record (R026, R027, R085 evidenced; R025, R031, R131 read or network halves evidenced);
every `TODO(T15)` in live code has a new owner. This task writes no behaviour.

Throughout, `<base>..<last>` is the git range of this plan's execution on `plan-j`, written as two short hashes:
`<base>` is the `BASE` recorded in Task 1 Step 1b (excluded by the range) and `<last>` the newest commit before this
task's own (`LAST=$(git rev-parse --short HEAD)`, run before this task commits). `<date>` is `date -u +%F` on the day
of the close-out.

- [x] **Step 1: No `TODO(T15)` is left in live code**

Edit 1 (`core/src/ops_core/routing.py`, the manifest's retrieval mode), replace:

```python
    # TODO(T15): mcp-read, the caller of `search_procedures_scoped`, translates `vector_exact` to `mode=vector`.
```

with:

```python
    # TODO(T16): mcp-read, the caller of `search_procedures_scoped` (T17), translates `vector_exact` to `mode=vector`.
```

Edit 2 (`scripts/build_schemas.py`, the tool input's `mode`), replace:

```python
                "mode": {"enum": ["lexical", "vector_exact"]},  # ruling 3; mcp-read maps vector_exact (TODO(T15))
```

with:

```python
                "mode": {"enum": ["lexical", "vector_exact"]},  # ruling 3; mcp-read maps vector_exact (TODO(T16))
```

Edit 3 (`tests/plan_c/test_schema_conformance.py`, the envelope's skip reason), replace:

```python
        "envelopes are built by the MCP servers (T15/T47); the data shapes are ActionOutcome"
```

with:

```python
        "envelopes are built by the MCP servers (T16/T47); the data shapes are ActionOutcome"
```

Edit 4 (`tests/plan_c/test_schema_conformance.py`, the tool inputs' skip reason), replace:

```python
        pytest.skip(NO_MODEL.get(schema, "tool input schema: enforced by the MCP server's argument validation (T15)"))
```

with:

```python
        pytest.skip(NO_MODEL.get(schema, "tool input schema: enforced by the MCP server's argument validation (T16)"))
```

Run:

```bash
git grep -n "TODO(T15" -- core api worker sweeper mcp-write mcp-read incident-sim scripts tests migrations
git grep -n "(T15" -- tests/plan_c
uv run python -m scripts.build_schemas && git status --short schemas
```

Expected: the first two commands print nothing (Task 2 moved `jobs.JobRule`'s marker to T47; the applied revision 0001's
docstring mentions "T09/T15" in prose, not as a marker, and stays as applied); the third prints only the generator's
summary line, `schemas/: 25 schema documents (19 contracts, 6 tool inputs); 89 examples (35 valid, 54 invalid);
index.json version 1.3.3`, and no changed file (the edited line is a comment). If the first prints a line, give that
TODO its owner from the debt list (T16, T17, T20, T30 or T47) in a separate commit before continuing.

- [x] **Step 2: Handoff records**

Run this once from the repository root, with `BASE` set to the hash Task 1 Step 1b recorded (it rewrites the two JSON
files in their own format: two-space indent, non-ASCII kept, one trailing newline):

```bash
BASE=<the hash recorded in Task 1 Step 1b> uv run python - <<'EOF'
import json
import os
import subprocess
from pathlib import Path

base = os.environ["BASE"]
last = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True).stdout
subprocess.run(["git", "merge-base", "--is-ancestor", base, "HEAD"], check=True)  # the base is this branch's own
span = f"{base}..{last.strip()}"
note = (
    f"Plan J (branch plan-j): done in {span} (the debt list, then the four tasks; the close-out is the next commit; "
    "plan docs/superpowers/plans/2026-10-15-first-slice-j-mcp-read-verifier-handles.md). Shipped: hardening and "
    "evidence over the existing mcp-read, no new tool or definer: ops_core.mcp_protocol.ProtocolVersionGuard in "
    "front of both MCP servers' SDK apps (a POST to /mcp without exactly MCP-Protocol-Version 2026-07-28 is HTTP "
    "400 with JSON-RPC -32022 before authentication; the SDK's legacy stateless path is closed; a header/_meta "
    "mismatch stays the SDK's -32020); mcp-read's verifier, built by one constructor (read_verifier) for production "
    "and the unit tests, requires the typ claim Bearer, and its SDK adapter refuses a token whose aud lacks the "
    "server's URL before stamping the resource (the SDK's validate_token_resource stays on as a second layer); "
    "revision 0009_handle_binding re-creates _resolve_handle with the handle's job bound to its own run and "
    "unfinished (0007's body with one statement replaced; exact downgrade); persistence.allowed_tool checks the job "
    "type's run states as well as its tools; mcp-read refuses to start without 0009 "
    "(persistence.assert_function_text on pg_proc); the worker binds each handle to its token source's client id. "
    "Evidence: tests/e2e/test_mcp_read_t15_live.py, test_mcp_read_process_live.py, test_migration_0009_live.py and "
    "reports/mcp-read/ (live), tests/plan_j/ for the unit half. R105's replay of create_incident after the outcome "
    "and the R006 populated upgrade's migrated finished job are now refused; through the tool a replay is answered "
    "only while the run is APPROVED or EXECUTING (the re-queue's re-send), and test_mcp_write_live.py's direct "
    "calls prove the execution layer's idempotency, not the tool's. Deferred: mcp-write's verifier, its literal azp "
    "in the write-path definers, the attempt-state allowlist and the write halves of R025/R131 -> T47; asset_scope, "
    "the asset tools and asset-sim -> T16; search_procedures_scoped and the governed store -> T17/T16; the worker's "
    "401 handling and resume_input -> T20; TLS, container hosts and per-service tests -> T30. Errata 72-81 are "
    "proposed in SESSION_STATE.md."
)
tasks_path = Path("handoff/tasks.json")
tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
t15 = next(t for t in tasks["tasks"] if t["id"] == "T15")
t15["status"] = "DONE"
t15["review_notes"].append(note)
tasks_path.write_text(json.dumps(tasks, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

matrix_path = Path("handoff/acceptance-matrix.json")
matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
full = {
    "R026": (
        ["tests/e2e/test_mcp_read_process_live.py", "reports/mcp-read/t15-independent-client.txt",
         "tests/plan_j/test_verifier_t15.py", "tests/plan_j/test_mcp_read_http.py"],
        "Plan J (T15): against mcp-read as an independent process, a persona token (aud ops-api, the stand-in for a "
        "browser token: no ops-web access token is minted anywhere, the API stores none), an ops-mcp-write token (aud "
        "incident-sim) and an ops-mcp-read token (aud asset-sim) each get 401 invalid_token on a tools/call of "
        "search_procedures that carries a valid handle, which the worker's token then answers with data: the refusal "
        "comes before the tool and the handle lookup, and mcp-read forwards nothing downstream. Missing aud, azp "
        "ops-web, a non-access typ and another workload's azp are synthetic-key unit cases at mcp-read's "
        "configuration (erratum 81); every foreign token above is 401 through read_verifier's audience check (PyJWT's "
        "aud), with McpVerifier's own aud check behind it (unit-tested with a verifier that checks no audience) and "
        "the SDK's validate_token_resource (pinned on by a unit test) a third, inert layer.",
    ),
    "R027": (
        ["tests/e2e/test_mcp_read_t15_live.py", "reports/mcp-read/t15-mcp-read.txt",
         "tests/e2e/test_migration_0009_live.py", "tests/plan_j/test_migration_0009.py",
         "tests/plan_j/test_allowlist.py", "tests/plan_j/test_worker_azp.py"],
        "Plan J (T15): over HTTP, one read handle is refused (one INVALID_HANDLE envelope, no action id) when its job "
        "is pointed at another run's job, past its 60 s expiry on the test clock, under a lapsed lease, after the "
        "fence moved, and after its release (revocation), answering again between causes; at the definer it is "
        "refused once its job is finished, and another azp is refused (test_definers_write_path_live.py); the tool "
        "binding is the job type's tools and run states. No log record of an answered call, a refused call or a "
        "refused raw POST, captured with uvicorn and the server at DEBUG and no redaction filter, holds the handle; "
        "the child process's own log, written through its redaction filter, holds none either; the model's request "
        "has no field for a handle (a unit test pins DraftRequest's four fields).",
    ),
    "R085": (
        ["tests/e2e/test_mcp_read_t15_live.py", "tests/plan_j/test_allowlist.py", "tests/plan_j/test_worker_azp.py",
         "tests/e2e/test_definers_write_path_live.py"],
        "Plan J (T15): the allowlist is derived from the job type's tools and run states in persistence.allowed_tool "
        "(every pair tabled in a unit test); over HTTP an investigate handle is refused once its run awaits input, an "
        "execute handle is refused at mcp-read also when its stored server column claims read, and a tool mcp-read "
        "does not register is the SDK's unknown-tool error. The handle's azp is the worker's token-source client id "
        "and _resolve_handle refuses another (OC008 at the definer; the verifier refuses any azp but ops-worker).",
    ),
}
half = {
    "R025": (
        ["tests/e2e/test_mcp_read_process_live.py", "reports/mcp-read/t15-independent-client.txt",
         "tests/plan_j/test_mcp_read_http.py"],
        "Read half only (Plan J, T15): python -m ops_mcp_read runs as a child process on a loopback port and the "
        "official SDK Client (mode 2026-07-28) in the test process lists exactly search_procedures and calls it "
        "with a valid handle over the network. mcp-write's half -> T47.",
    ),
    "R031": (
        ["tests/e2e/test_mcp_read_process_live.py", "reports/mcp-read/t15-independent-client.txt"],
        "Network half for mcp-read (Plan J, T15): the locked mcp 2.3.0 and mcp-types 2.3.0 are asserted in a live "
        "test whose official client crosses the network to an independent mcp-read; T04's import half is the "
        "workspace import test. mcp-write's own network test -> T47.",
    ),
    "R131": (
        ["tests/e2e/test_mcp_read_t15_live.py", "reports/mcp-read/t15-mcp-read.txt"],
        "Read half only (Plan J, T15): mcp_read can EXECUTE current_time (erratum 15) and resolve_invocation and "
        "nothing else in app (asset_scope and search_procedures_scoped join with T16/T17, erratum 72); an attempted "
        "grant_execution is 42501; a recover and an execute handle presented to mcp-read are refused over HTTP. The "
        "write half (mcp_exec's set, a read handle at mcp-write, incident-sim refusing mcp-read's token) -> T47.",
    ),
}
for row in matrix["requirements"]:
    if row["id"] in full:
        row["implementation_status"] = "IMPLEMENTED_LOCALLY_VERIFIED"
        row["evidence_status"] = "RECORDED_LOCALLY_LIVE"
        row["evidence_paths"], row["note"] = full[row["id"]]
    elif row["id"] in half:  # the target names another task's half: implemented stays unclaimed
        row["evidence_status"] = "RECORDED_LOCALLY_LIVE"
        row["evidence_paths"], row["note"] = half[row["id"]]
matrix_path.write_text(json.dumps(matrix, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

backlog_path = Path("handoff/BUILD_BACKLOG.md")
backlog = backlog_path.read_text(encoding="utf-8")
head = "- [ ] **T15 Authenticated MCP read server (mcp-read), token verifier and invocation handles**"
assert backlog.count(head) == 1
backlog = backlog.replace(head, head.replace("- [ ]", "- [x]", 1))
lines = backlog.split("\n")
at = next(i for i, line in enumerate(lines) if line.startswith("- [x] **T15 "))
end = at + 1
while end < len(lines) and lines[end].startswith("  - "):
    end += 1
lines.insert(end, f"  - *Review note:* {note}")  # after the task's other notes, as tasks.json appends it
backlog_path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
print(span)
EOF
```

Expected: it prints the span (for example `1a2b3c4..5d6e7f8`). `git diff --stat handoff` shows three files changed;
`git diff handoff/acceptance-matrix.json` shows six rows: R025, R026, R027, R031, R085 and R131.

- [x] **Step 3: Project state**

In `SESSION_STATE.md`:

Edit 1 (`SESSION_STATE.md`, the "Next task" line), replace:

```markdown
**Next task:** Plan I (T14) is executed and closed on branch `plan-i` (`4aa5f92..e485c56`, on top of `plan-h`: the debt
list, then six tasks, the sixth the close-out `9ce23a0`, and the final-review fix wave `e485c56`; a docs commit after
it records the wave). Owner inputs: (1) the holdout seal (T03 step 9), then the live probe
(T02); (2) merge the stacked PRs in order and open the plan-h -> plan-g and plan-i -> plan-h PRs; (3) T44 step 10
(`docs/runbooks/ollama-network.md` step A); (4) decide the proposed errata of Plans C, E, F, G, H and I (I: 60-71
below); (5) migrate the dev database to revision 0008 (`uv run python scripts/skeleton.py migrate`, dev profile: from
0005 it applies 0006, 0007 and 0008 together; 0008 adds `app.outbox`, gives the sweeper DELETE on `jobs` and
re-creates `_append_event` with the payload rules; it deletes nothing). Next is Plan J = T15 (mcp-read, the
earliest dependency-satisfied PLANNED task in `handoff/tasks.json`, unblocked by T13; T14 also unblocks T20 and T27
once their other dependencies are done).
```

with:

```markdown
**Next task:** Plan J (T15) is executed on branch `plan-j` (on top of `plan-i`: `<base>..<last>` holds the debt list and
the four tasks, and the close-out is the commit after `<last>`). Owner inputs: (1) the holdout seal (T03 step 9), then
the live probe (T02); (2) merge the stacked PRs in order and open the plan-h -> plan-g, plan-i -> plan-h and plan-j ->
plan-i PRs; (3) T44 step 10 (`docs/runbooks/ollama-network.md` step A); (4) decide the proposed errata of Plans C, E, F,
G, H, I and J (J: 72-81 below); (5) migrate the dev database to revision 0009 (`uv run python scripts/skeleton.py
migrate`, dev profile: from 0005 it applies 0006, 0007, 0008 and 0009 together; 0009 re-creates `_resolve_handle` with
the handle's job binding and changes no row; mcp-read now also refuses to start without it). Next is Plan K = T47
(mcp-write, the earliest dependency-satisfied PLANNED task in `handoff/tasks.json` after T15, unblocked by T15 and T10;
T17 is also unblocked).
```

Edit 2 (`SESSION_STATE.md`, the repository line), replace:

```markdown
**Repository:** local git repo at `C:\Users\joeys\Desktop\MLOps`, branch `plan-i` (Plan I work on top of `plan-h`, on top of `plan-g`, on top of `plan-f`, on top of `plan-e`, on top of `plan-d`, on top of `plan-c`, on top of `plan-b`, on top of `plan-a`). Remote `github.com/jschnepel/MLOps` (public, MIT) exists; `main` and `plan-a` were pushed on 2026-10-07. `plan-b` to `plan-e` were pushed on 2026-10-08 and `plan-f` on 2026-10-09 (`origin/plan-e` is two docs commits behind local `plan-e`; a `git push origin plan-e` brings it level before the plan-f -> plan-e PR). PRs #1-#5 were opened on 2026-10-09 and are green after the EXE001 fix (first green run https://github.com/jschnepel/MLOps/actions/runs/37962510516; record `reports/ci/t06-first-ci-runs.txt`). Merging them in order is the owner's call.
```

with:

```markdown
**Repository:** local git repo at `C:\Users\joeys\Desktop\MLOps`, branch `plan-j` (Plan J work on top of `plan-i`, on top of `plan-h`, on top of `plan-g`, on top of `plan-f`, on top of `plan-e`, on top of `plan-d`, on top of `plan-c`, on top of `plan-b`, on top of `plan-a`). Remote `github.com/jschnepel/MLOps` (public, MIT) exists; `main` and `plan-a` were pushed on 2026-10-07. `plan-b` to `plan-e` were pushed on 2026-10-08 and `plan-f` on 2026-10-09 (`origin/plan-e` is two docs commits behind local `plan-e`; a `git push origin plan-e` brings it level before the plan-f -> plan-e PR). PRs #1-#5 were opened on 2026-10-09 and are green after the EXE001 fix (first green run https://github.com/jschnepel/MLOps/actions/runs/37962510516; record `reports/ci/t06-first-ci-runs.txt`). Merging them in order is the owner's call.
```

Edit 3 (`SESSION_STATE.md`, Plan J's section, and the walking-skeleton heading Plan I's close-out dropped), replace:

```markdown
Allowed shortcuts in T08, each with its owning task:
```

with:

```markdown
## Plan J executed (<date>, branch `plan-j`)

- T15 = `<base>..<last>` (the debt list first, then the four tasks; the close-out is the commit after `<last>`). The
  plan (`docs/superpowers/plans/2026-10-15-first-slice-j-mcp-read-verifier-handles.md`) holds the 25 rulings of the
  controller's brief as implemented; the input is `docs/superpowers/research/2026-10-15-plan-j-inputs.md`.
  Evidence: `tests/e2e/test_mcp_read_t15_live.py` (R027's handle cases over HTTP, R085 and R131's read half at
  mcp-read, the `mcp_read` ACL, the four protocol-version requests, no handle in any log record),
  `test_mcp_read_process_live.py` (R025's read half and R031's network half: a child process and the official
  client; R026: three foreign tokens refused with 401), `test_migration_0009_live.py` (the round trip and the startup
  check against 0008, the job binding at the definer, the run-state rule) and `reports/mcp-read/`; the unit half is
  in `tests/plan_j/`. R105's replay step now expects the refusal of a fresh handle for a finished execute job, and the
  R006 populated upgrade asserts its migrated finished job's refusal before reopening it.
- Gates: `check.py` <dev passed> passed / <dev skipped> skipped; `check.py --profile test` <live passed> passed / 21
  skipped; `verify_handoff.py` exit 0 (STATUS.md, "Update — Plan J executed").
- **Proposed errata (the owner decides; the spec text stays authoritative until then).** Numbered on from Plan I's
  seventy-one:
  72. R131 and SA:400/SA:459 (`mcp_read`'s functions): `mcp_read` holds EXECUTE on `current_time` (erratum 15) and
      `resolve_invocation` and on nothing else in `app`; `asset_scope` arrives with T16 and
      `search_procedures_scoped` with T17/T16, each in its owner's revision (Plan E ruling 1: no definer without a
      caller), so R131's three-function set is the target, not today's.
  73. SA:571-572 and BS:378 (per-request version): both MCP servers mount `ops_core.mcp_protocol.
      ProtocolVersionGuard` before the SDK app: a POST to `/mcp` without exactly one `MCP-Protocol-Version:
      2026-07-28` header is answered HTTP 400 with the constant JSON-RPC error `-32022` "Unsupported protocol
      version" (`id` null, the supported version listed, nothing echoed) before authentication, so the SDK's legacy
      stateless path is closed and an unauthenticated client learns only the version rule; a header/`_meta`
      disagreement is the SDK's own `HEADER_MISMATCH` (400, `-32020`).
  74. SA:557 (the verifier): mcp-read also requires the access token's `typ` claim `Bearer`; its SDK adapter
      (`McpVerifier`) refuses a token whose `aud` lacks the server's resource URL and only then sets the SDK's
      `AccessToken.resource` to that URL; the SDK's `validate_token_resource` is on as a second layer, which cannot
      refuse while the stamp is the server's own URL; every token refusal stays HTTP 401 (Plan D ruling 25); mcp-write
      follows in T47.
  75. SA:459 and SA:496 (the handle's binding): `_resolve_handle` resolves a handle only when its `job_id` names a
      job of the handle's own run that is not finished (`done_at IS NULL`); otherwise it refuses `OC008` like every
      other refusal (revision 0009).
  76. SA:338 and T15 review note 2 (the allowlist): `persistence.allowed_tool(job_type, run_state, tool)` checks the job
      type's tools and run states at the start of every MCP call (`persistence.resolve_invocation`; the definers' own
      resolutions inside `grant_execution`, `mark_sent`, `record_outcome` and `lookup_action` do not apply it, since
      `record_outcome` must answer after the run moved); the attempt-state dimension (`create_incident` only while the
      attempt is absent or INTENT, not cancelled, before the deadline) is mcp-write's, in `execution.next_step` today
      and in its allowlist with T47.
  77. SA:459 (the `resolve_invocation` row as amended): the only lock is `run_lease FOR SHARE` (erratum 53); it
      returns `run_id, job_id, job_type, tenant_id, conversation_id, run_state, attempt_state` (erratum 19); it
      binds the handle as erratum 75 says.
  78. SA:34 (AM-00 §9): the `ops-mcp` audience and "distinct service scope" wording is replaced by AM-20.7 item 6
      (the resource-URL audiences), not by AM-20.6 (the test clock).
  79. BS:360 ("Refresh it only while the lease is current"): there is no refresh; a handle is minted per call under
      the lease, lives 60 s, and is bound at use to the lease's fence and liveness (erratum 58).
  80. SA:460-461 with SA:176-184 (reads and the fence): a read tool is served after the handle resolved in its own
      committed unit; a fence that moves during the read cannot cause a write, and the worker's next fenced unit
      fails.
  81. SA:558 (the three token tests): the missing-`aud` and browser-token cases are synthetic-key unit tests at
      mcp-read's configuration (`azp=ops-web`, no `aud`); live, a persona token (aud `ops-api`) stands in for a
      browser token, because no `ops-web` access token is minted anywhere (the API stores none, erratum 31, and
      minting one needs the client secret).
- Earlier debt lines that named T15 and what became of them: the raw, unhashed handle (walking skeleton) was done by
  Plan E (revision 0002); "handles are not revoked at job end" was done by Plan H (`release_lease`); "resolution
  ignores run and attempt state" is half done (the run state, Task 2) and half re-homed (the attempt state → T47);
  Plan D's "the same `INVALID_HANDLE` for every rejection" is kept on purpose (SA:357, ruling 13); Plan E's
  `asset_scope` and `search_procedures_scoped` ("T15/T16/T17") now name T16 and T17/T16; Plan E's untested "write
  handle at mcp_read" (re-homed to T22 by Plan H) is now tested over HTTP (Task 3); Plan D's silent excerpt
  truncation stays with the tool's contract (T16).

## Walking-skeleton debt list (T08; committed before coding) [R6-B7]

Allowed shortcuts in T08, each with its owning task:
```

Edit 4 (`SESSION_STATE.md`, the dev database state), replace:

```markdown
database holds was written under the old rules and stays as it is (the rules apply to new events); it deletes nothing.

## Open owner inputs
```

with:

```markdown
database holds was written under the old rules and stays as it is (the rules apply to new events); it deletes nothing.

**Update (<date>):** Plan J adds revision 0009. The dev `ops` database stays at 0005 until the owner runs
`uv run python scripts/skeleton.py migrate` (dev profile), which applies 0006, 0007, 0008 and 0009 together; until then
mcp-read also refuses to start (it checks that `_resolve_handle` carries 0009's job binding). 0009 re-creates
`app._resolve_handle` only; every handle in the dev database is long expired, and it changes no row.

## Open owner inputs
```

Edit 5 (`SESSION_STATE.md`, the first owner input), replace:

```markdown
- Migrate the dev database to revision 0008 (`uv run python scripts/skeleton.py migrate`, dev profile; it applies
  0006, 0007 and 0008 together), then decide errata 35-44 (see "Plan G executed"), 45-59 (see "Plan H executed") and
  60-71 (see "Plan I executed").
```

with:

```markdown
- Migrate the dev database to revision 0009 (`uv run python scripts/skeleton.py migrate`, dev profile; it applies
  0006, 0007, 0008 and 0009 together), then decide errata 35-44 (see "Plan G executed"), 45-59 (see "Plan H
  executed"), 60-71 (see "Plan I executed") and 72-81 (see "Plan J executed").
```

Edit 6 (`SESSION_STATE.md`, the exact next step), replace:

```markdown
Then wait for the owner inputs above (holdout seal, then live probe; push and PRs; the Ollama runbook step A; the dev database migration to 0008; the proposed errata of Plans C-I, up to 71) and write Plan J for T15 (mcp-read, the earliest dependency-satisfied PLANNED task in `handoff/tasks.json`; T17 is also unblocked).
```

with:

```markdown
Then wait for the owner inputs above (holdout seal, then live probe; push and PRs; the Ollama runbook step A; the dev database migration to 0009; the proposed errata of Plans C-J, up to 81) and write Plan K for T47 (mcp-write, the earliest dependency-satisfied PLANNED task in `handoff/tasks.json` after T15; T17 is also unblocked).
```

Then finish the "Plan J executed" section with two bullets only execution can write, inserted after its errata
bullet's last earlier-debt line (before the restored `## Walking-skeleton debt list` heading):
`- Rulings made during execution:` (one line each, with its reason; or `- Rulings made during execution: none beyond
the plan.`) and `- **Open items for later:**` (from the SDD ledger
`.superpowers/sdd/2026-10-15-first-slice-j-mcp-read-verifier-handles/progress.md`; or `- **Open items for later:**
none recorded.`).

- [x] **Step 4: Status, history, the runbook and the documents**

Edit 1 (`STATUS.md`, its last lines), replace:

```markdown
  `outcomes.Event` on the read path -> T26; SSE -> T27; dashboards -> T28/T29; retention -> T32; a real channel ->
  T39. Twelve errata (60-71) are proposed.
```

with:

```markdown
  `outcomes.Event` on the read path -> T26; SSE -> T27; dashboards -> T28/T29; retention -> T32; a real channel ->
  T39. Twelve errata (60-71) are proposed.


## Update — Plan J executed (<date>, branch `plan-j`)

- Plan J (T15: the authenticated mcp-read, its token verifier and bound invocation handles) executed on branch
  `plan-j` (`<base>..<last>`, on top of `plan-i`). The plan is
  `docs/superpowers/plans/2026-10-15-first-slice-j-mcp-read-verifier-handles.md`.
- `PYTHONUTF8=1 uv run python scripts/check.py` is `CHECK: GREEN`: pytest `<dev passed> passed, <dev skipped>
  skipped`. `PYTHONUTF8=1 uv run python scripts/check.py --profile test` is `CHECK: GREEN`: pytest `<live passed>
  passed, 21 skipped`. `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts` exits 0.
- **Evidenced** (acceptance matrix `RECORDED_LOCALLY_LIVE` / `IMPLEMENTED_LOCALLY_VERIFIED`): R026, R027 and R085.
  Tokens for another audience or client are refused with 401 on a tool call that carries a valid handle; a read
  handle is refused when its job is another run's, when it expired, when its lease lapsed or its fence moved, after
  its release, and once its run left the job type's states, each over HTTP, and when its job is finished, at the
  definer; recover and execute handles are refused at mcp-read, the execute one even when its stored server column
  lies; no log record captured at DEBUG holds a handle.
- **Evidenced in part** (`RECORDED_LOCALLY_LIVE`, still `NOT_IMPLEMENTED_OR_NOT_TARGET_VERIFIED`): R025 and R131
  (mcp-read's halves; mcp-write's are T47's) and R031 (the network half for mcp-read): an independent mcp-read process
  is listed and called by the official client over the network, and `mcp_read` can execute `current_time` and
  `resolve_invocation` only.
- Also built: the protocol-version guard on both MCP servers (the SDK's legacy path is closed); revision 0009 (the
  handle's job binding); mcp-read's startup check for it; the worker's own client id on every handle.
- The dev `ops` database needs revisions 0006 to 0009 (an owner input); the API, the sweeper, the worker, mcp-write and
  mcp-read refuse to start until then.
- Deferred, each with its owner in `SESSION_STATE.md`: mcp-write's verifier, its literal azp, the attempt-state
  allowlist and the write halves of R025/R131 -> T47; the asset tools and asset-sim -> T16; the governed store ->
  T17/T16; the worker's 401 handling and `resume_input` -> T20; TLS, container hosts and per-service tests -> T30. Ten
  errata (72-81) are proposed.
```

Create `docs/runbooks/mcp-read.md`:

````markdown
# mcp-read: the authenticated read server, its token checks and invocation handles (T15)

Who this is for: whoever runs mcp-read, calls it, or debugs a worker run that failed with "retrieval failed". The
design is AM-30, AM-20.7 items 6 and 11, AM-15 and AM-20.3 in `SPEC_AMENDMENTS.md`, BUILD_SPEC §9 and §10, and Plan J
(`docs/superpowers/plans/2026-10-15-first-slice-j-mcp-read-verifier-handles.md`).

## What a call must carry

A POST to `http://127.0.0.1:8081/mcp` (Streamable HTTP, protocol revision 2026-07-28, stateless, JSON responses) is
checked in this order; the first failure decides the answer.

1. **`MCP-Protocol-Version: 2026-07-28`**, exactly once. Anything else, an absent header included, is HTTP 400 with
   the JSON-RPC error `-32022` "Unsupported protocol version" before authentication: an unauthenticated client learns
   only this rule. The SDK would otherwise send such a request down its legacy path, where no version is checked.
   mcp-write applies the same guard.
2. **A bearer token** that is the worker's access token: RS256 from the realm's keys, `iss` the realm, not expired,
   `aud` containing `MCP_READ_RESOURCE_URL` (default `http://mcp-read:8081/mcp`), `azp` `ops-worker`, a `sub`, and the
   `typ` claim `Bearer` (`read_verifier`); `McpVerifier` refuses again any token whose `aud` lacks this server's URL,
   and only then stamps that URL as the token's resource. The SDK's resource check (`validate_token_resource`) is on
   as a second layer, which cannot refuse anything while the stamp is this server's own URL. Any failure is HTTP 401
   `invalid_token` with a `WWW-Authenticate` header pointing at the protected-resource metadata, which the SDK serves
   at `/.well-known/oauth-protected-resource/mcp` (it stays as the pinned protocol's resource-server metadata; nothing
   else of the authorization spec is in scope).
3. **The SDK's own checks**: the `params._meta` protocol version must equal the header (else 400, `-32020`
   `HEADER_MISMATCH`), `Mcp-Method` and `Mcp-Name` must match the body, the tool must exist (an unknown tool is a tool
   error), and its arguments must match the strict input schema (extra keys such as `tenant_id` are refused).
4. **`X-Ops-Invocation`**, the handle the worker minted for this job. It is a lookup key, never an identity (SA:566),
   and is never logged. `app.resolve_invocation` hashes it and, under the run's lease row lock, requires: the hash is
   known, the handle is not revoked or expired (60 s), its fence is the lease's and the lease is live, its `azp` is
   the token's, its job is its own run's and not finished, and the job type is a read type. Then Python requires the
   tool to be one of the job type's and the run to be in one of the job type's states (`investigate`: QUEUED,
   RETRIEVING, DRAFTING; `resume_input`: AWAITING_INPUT, QUEUED). Every refusal of a presented handle is the same tool
   result: `status` `error`, `error.code` `INVALID_HANDLE`, `error.message` "invocation handle rejected", never a hint
   of the cause and never an action id. A call with no handle at all gets the same code with the message "missing
   invocation handle", which tells the client only what it already knows.

## Starting it

`python -m ops_mcp_read` (or `scripts/skeleton.py up`) needs the database at revision 0009: at start it refuses when
`app.test_clock` exists outside the test profile, and when `app._resolve_handle` lacks 0009's job binding ("…
predates this service; run scripts/skeleton.py migrate for this profile"). The dev database stays at 0005 until the
owner migrates it. Readiness (`/health/ready`) needs the realm's signing keys and the database.

| Variable | Default | What it is |
|---|---|---|
| `OPS_MCP_READ_PORT` | 8081 | the loopback port it listens on |
| `MCP_READ_RESOURCE_URL` | `http://mcp-read:8081/mcp` | its token audience and resource URL, not the listen URL |
| `OPS_MCP_READ_URL` | `http://127.0.0.1:8081/mcp` | where the worker calls it |

## Looking at it

As the superuser on the dev database (after the owner's migration to 0009; `app.run_lease` arrives with 0007), a run's
handles (only hashes are stored):

```sql
SELECT ic.job_id, j.type, j.done_at, ic.server, ic.azp, ic.fence, l.fence AS lease_fence, l.lease_until,
       ic.expires_at, ic.revoked_at
FROM app.invocation_context ic JOIN app.jobs j ON j.id = ic.job_id JOIN app.run_lease l ON l.run_id = ic.run_id
WHERE ic.run_id = '<run>' ORDER BY ic.created_at;
SELECT state FROM app.runs WHERE run_id = '<run>';
```

## When something looks wrong

- **The worker logs "retrieval failed" and fails the run**: the call was refused. A 400 or 401 means a deployment
  mismatch (the client's protocol version, the token's audience or client); an `INVALID_HANDLE` envelope means the
  handle no longer fits its run (the lease lapsed or moved to another worker, the job finished, the run moved on).
  Use the query above; the server says nothing more on purpose.
- **mcp-read will not start**: read the message. "predates this service" is the missing revision; "signing keys
  unavailable" is the realm.
- **A handle in a log line** is a bug (SA:566): the live test `tests/e2e/test_mcp_read_t15_live.py` captures every
  record of the server, the SDK, uvicorn and the client at DEBUG, with no redaction filter, and fails if one holds the
  handle. Never run mcp-read with uvicorn's `trace` level: its message logger writes every request's headers, the
  handle and the bearer token included (`serve_app` pins `warning`).

## Not here yet

The asset tools and asset-sim (T16), the governed store and vector search (T17), mcp-write's equivalents of the
verifier hardening (T47), TLS and container host names (T30).
````

Edit 2 (`docs/ARCHITECTURE.md`, before "Where the code will live"), replace:

```markdown
| R089 | Four roles' writers wait on the run lock; the route never shows n + 1 before n; a stress run ends gap-free |

---

## Where the code will live (not yet written)
```

with:

```markdown
| R089 | Four roles' writers wait on the run lock; the route never shows n + 1 before n; a stress run ends gap-free |

---

## 7. mcp-read's door (built in T15)

**Claim.** A read tool answers only a request in the pinned protocol, carrying the worker's own access token and a
handle that still belongs to an open job of a live run in one of its job type's states; every other request is
refused before it learns anything, and nothing about the handle is written down.

- **The version first.** A guard in front of the SDK refuses any POST without `MCP-Protocol-Version: 2026-07-28`
  (400, `-32022`), before authentication; the SDK's own ladder then refuses a header that disagrees with `_meta`.
- **The token second.** Signature, issuer, expiry, `aud` holding this server's resource URL, `azp` the worker, the
  access-token `typ`; the SDK adapter refuses an `aud` without this server's URL before it stamps the resource (the
  SDK's own resource check is a second layer). Any failure is 401.
- **The handle third, in the database.** Its hash, the run's lease (shared lock), the fence and expiry, revocation, the
  `azp`, the job (its own run's, unfinished) and the server derived from the job type; then, in Python, the job
  type's tools and run states. Every refusal is the same plain envelope.
- **Least privilege.** `mcp_read` can execute `current_time` and `resolve_invocation` and nothing else; the search
  itself still reads the fixture corpus (T17 brings the governed store, T16 the asset tools).

| Requirement | What its test shows |
|---|---|
| R025 (read half) | An independent mcp-read process is listed and called by the official client over the network |
| R026 | Tokens for another audience or client are 401 on the request the worker's token passes |
| R027 | A handle dies with its job, expiry, lease, fence and release, over HTTP; no log record holds it |
| R085 | The tools come from the job type and run state; an unregistered tool is the SDK's error |
| R131 (read half) | `mcp_read` executes two functions only; a recover and an execute handle at mcp-read are refused |

---

## Where the code will live (not yet written)
```

`docs/PROJECT_HISTORY.md`: if a section whose heading contains `The mcp-read plan` exists (the controller may commit
the planning story with the review record before execution, as for Plans G-I), skip the next edit. Otherwise:

Edit 3 (`docs/PROJECT_HISTORY.md`, the last section's heading), replace:

```markdown
## 27. What the process taught
```

with:

```markdown
## 27. The mcp-read plan closed a legacy door and bound the handle to its job

**Problem.** Plan J takes T15: the authenticated mcp-read, its token verifier and invocation handles. The fact sheet
found most of it already real since the walking skeleton (the custom verifier, the header-only handle, its hash and its
fence), and three holes nobody had tested: the installed SDK sends a request without a protocol-version header down a
legacy path that checks no version at all; `_resolve_handle` read the handle's job by id alone, so a handle whose job
belonged to another run, or had finished, still resolved; and the allowlist ignored the run's state. The controller's
brief of 25 rulings chose hardening and evidence over new tools: no asset tools and no new definer before their owners.

**Change.** A small ASGI guard in `core` refuses any POST without the pinned version before authentication, in front of
both MCP servers. mcp-read's verifier requires an access token's `typ`, and its SDK adapter refuses a token without the
server's audience before stamping the resource. Revision 0009 replaces one statement of 0007's `_resolve_handle`, so the
job must be its own run's and open; the Python allowlist checks the run state too; mcp-read refuses to start without the
binding; the worker stamps each handle with its own client id. Live tests prove each refusal over HTTP, the ACL, the
four version cases and that no log record carries a handle, and an independent mcp-read process is listed and called by
the official client. Two older tests changed their meaning: the walking skeleton's replay after the outcome and the
populated upgrade's migrated execute job are now refused, because their handles name a finished job.

## 28. What the process taught
```

Then append to section 27 (after its last paragraph, before `## 28.`) one `**Problem.**`/`**Change.**` pair per
finding the task reviews and the final review recorded (from the SDD ledger), or the sentence "Execution found nothing
the plan had not ruled on." when they recorded none. Later review rounds of this plan, if any, add their own paragraph
before execution.

`README.md`: line 5 is one long line; change its tail with this script (the old and new texts are each part of that
one line; the Python string literals only wrap for width):

```bash
uv run python - <<'EOF'
from pathlib import Path

path = Path("README.md")
text = path.read_text(encoding="utf-8")
old = "and a gap-free event journal with a leased notification outbox (T14) run locally**"
new = (
    ", a gap-free event journal with a leased notification outbox (T14) and an authenticated mcp-read with "
    "invocation handles bound to their run's open job (T15) run locally**"
)
assert text.count(old) == 1
path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
EOF
```

Edit 4 (`mcp-read/README.md`, "Trusts" and "Runs"), replace:

```markdown
## Trusts
Workload token with its audience; definer functions `resolve_invocation`, `asset_scope`, `search_procedures_scoped`

## Never
Any write-path function; incident-sim

## Runs (T08)

`python -m ops_mcp_read` on 127.0.0.1:8081 (`OPS_MCP_READ_PORT`), Streamable HTTP at `/mcp`, protocol 2026-07-28,
stateless. Verifies `aud ∋ MCP_READ_RESOURCE_URL`, `azp == ops-worker`; resolves `X-Ops-Invocation` for `investigate`
jobs. One tool, `search_procedures` (lexical, fixture-backed until T17).
```

with:

```markdown
## Trusts
The worker's workload access token with this server's audience; the definer function `resolve_invocation`
(`asset_scope` and `search_procedures_scoped` arrive with T16 and T17)

## Never
Any write-path function; incident-sim

## Runs (T08, T15)

`python -m ops_mcp_read` on 127.0.0.1:8081 (`OPS_MCP_READ_PORT`), Streamable HTTP at `/mcp`, protocol 2026-07-28,
stateless. A POST without exactly `MCP-Protocol-Version: 2026-07-28` is 400 before authentication. Verifies
`aud ∋ MCP_READ_RESOURCE_URL`, `azp == ops-worker` and the access token's `typ`; resolves `X-Ops-Invocation` for read
jobs whose run is in one of the job type's states, and only for the handle's own run's open job (revision 0009, which
it checks at start). One tool, `search_procedures` (lexical, fixture-backed until T17). See
`docs/runbooks/mcp-read.md`.
```

Edit 5 (`mcp-write/README.md`, "Runs"), replace:

```markdown
## Runs (T08)

`python -m ops_mcp_write` on 127.0.0.1:8082 (`OPS_MCP_WRITE_PORT`), Streamable HTTP at `/mcp`. Verifies
`aud ∋ MCP_WRITE_RESOURCE_URL`, `azp == ops-worker`; resolves `X-Ops-Invocation` for `execute` jobs. One tool,
`create_incident`: grant → INTENT → SENT (committed before I/O) → POST incident-sim with the `ops-mcp-write` workload
token → RESOLVED. A replay returns the recorded outcome; a transport failure records OUTCOME_UNKNOWN
(reconciliation: T22).
```

with:

```markdown
## Runs (T08, T15)

`python -m ops_mcp_write` on 127.0.0.1:8082 (`OPS_MCP_WRITE_PORT`), Streamable HTTP at `/mcp`. A POST without exactly
`MCP-Protocol-Version: 2026-07-28` is 400 before authentication (T15). Verifies `aud ∋ MCP_WRITE_RESOURCE_URL`, `azp ==
ops-worker`; resolves `X-Ops-Invocation` for `execute` jobs that are still open while the run is APPROVED or EXECUTING
(T15). One tool, `create_incident`: grant → INTENT → SENT (committed before I/O) → POST incident-sim with the
`ops-mcp-write` workload token → RESOLVED. A replay while the run is still APPROVED or EXECUTING (the re-queue after a
transport failure) re-sends under the same action id and the destination's key answers; once the outcome is recorded,
any replay is refused `INVALID_HANDLE` before the grant (T15). A transport failure records OUTCOME_UNKNOWN
(reconciliation: T22). The verifier's T15 hardening and the recovery tools arrive with T47.
```

Edit 6 (`worker/README.md`, the handle sentence), replace:

```markdown
One `ops-worker` token carries both MCP audiences; one handle per call, bound to the lease's fence. Settings:
```

with:

```markdown
One `ops-worker` token carries both MCP audiences; one handle per call, bound to the lease's fence and to the client
id the tokens are issued to (T15). Settings:
```

- [x] **Step 5: Final gates**

```bash
PYTHONUTF8=1 uv run python scripts/check.py
PYTHONUTF8=1 uv run python scripts/check.py --profile test
uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts
```

Expected: `CHECK: GREEN` with `1071 passed, 164 skipped`; `CHECK: GREEN` with `1214 passed, 21 skipped` (the live
number is arithmetic until this run measures it); exit 0. Fill the `<dev passed>`, `<dev skipped>` and `<live
passed>` placeholders of Steps 3 and 4 with the printed numbers. Then `git checkout -- reports/bootstrap
reports/auth`; the live run rewrote `reports/skeleton` (R105's new replay line), `reports/admission`,
`reports/leases`, `reports/events` and `reports/outbox` and wrote `reports/mcp-read`, and Step 6 commits them. Tick
this plan's checkboxes (`- [ ]` → `- [x]`) for every step executed.

- [x] **Step 6: Commit**

```bash
git add handoff SESSION_STATE.md STATUS.md README.md mcp-read/README.md mcp-write/README.md worker/README.md
git add docs/ARCHITECTURE.md docs/PROJECT_HISTORY.md docs/runbooks/mcp-read.md core/src/ops_core/routing.py
git add scripts/build_schemas.py tests/plan_c/test_schema_conformance.py
git add reports/skeleton reports/admission reports/leases reports/events reports/outbox
git add docs/superpowers/plans/2026-10-15-first-slice-j-mcp-read-verifier-handles.md
# reports/mcp-read/ is written by Step 5's live gate: each of its two modules writes its file only when all of its
# tests passed.
if [ -d reports/mcp-read ]; then git add reports/mcp-read; else echo "reports/mcp-read missing: rerun Step 5"; fi
git commit -m "docs: close T15 - handoff records, acceptance rows, errata 72-81, the mcp-read runbook (Plan J)"
```

---

## Self-review (run by the plan's author before execution)

1. **Spec coverage.** T15's instructions: "mcp-read on official SDK 2.x over Streamable HTTP pinned to 2026-07-28" →
   already real (Plan D), now with the version guard (Task 1) and an independent-process client (Task 4); "custom
   TokenVerifier (iss, aud = MCP_READ_RESOURCE_URL, azp, exp)" → real since Plan D, now also the `typ` claim and
   `McpVerifier`'s audience check, with the SDK's resource check on as an inert second layer (Task 1); "X-Ops-Invocation
   as lookup key only" → unchanged, proved absent from every log record (Task 3) and from the child's log (Task 4);
   "resolve_invocation with azp binding, server binding (read handles only) and server-derived allowlist" → the azp and
   server bindings are 0007's, proved over HTTP (Task 3), the allowlist gains the run state (Task 2) and the handle its
   job binding (revision 0009, Task 2); "DB role mcp_read holds EXECUTE on resolve_invocation, asset_scope and
   search_procedures_scoped only" → today's set, `current_time` and `resolve_invocation`, asserted live (Task 3; erratum
   72, the other two with T16/T17). DoD 1 "Independent-process client lists and calls tools" → Task 4. DoD 2
   "Missing/wrong aud, browser token, replayed/expired/other-run/other-azp handle all rejected" → missing aud and the
   browser token as synthetic unit cases (Task 1) plus the persona stand-in and two wrong audiences live (Task 4);
   replayed (revoked), expired, other-run (Task 3, HTTP); other-azp at the verifier (Task 1) and at the definer
   (`test_definers_write_path_live.py`, cited). DoD 3 "Protocol-version header/_meta mismatch rejected" → Task 1
   in-process and Task 3 live (absent, 2025, mismatch, matching). DoD 4 "mcp_read cannot execute any write-path
   function; an execute/recover handle presented to mcp-read is rejected" → Task 3 (ACL, `42501`, a recover and an
   execute handle over HTTP, the latter also with a lying `server` column). Review notes: 1 (error only before a grant
   for authorized callers; auth failures never reveal an action id) → every refusal asserted as the plain envelope with
   no `action_id` (Task 3), token refusals 401 (Task 4); 2 (attempt state) → the run-state half here, the attempt-state
   half a T47 debt line (ruling 7, erratum 76); 3 (`asset_scope`, asset-sim, `search_procedures_scoped`, no table
   access) → debt lines T16/T17 and the ACL test; 4 (job type from the jobs row, server from the job type, the stored
   column a hint) → 0007's derivation, proved with the lying column (Task 3). The six requirement rows by their expected
   evidence:
   - **R025** "An independent process lists and calls tools on both mcp-read and mcp-write over the network." → the
     mcp-read half, `test_r025_an_independent_client_lists_and_calls_over_the_network` (Task 4); mcp-write → T47.
   - **R026** "Use valid token for another service; resource server rejects it without downstream forwarding." →
     `test_r026_foreign_tokens_are_refused_before_the_tool` (Task 4) and Task 1's synthetic cases.
   - **R027** "Replay with other workload/run/expired fence/tool; server rejects; handle absent from model/logs." → Task
     3's handle test (run, expiry, lease, fence, release), the definer's azp case, the allowlist's tool and state, the
     log test; the model never receives a handle (`test_the_model_request_has_no_field_for_a_handle` pins
     `DraftRequest`'s four fields, Task 1).
   - **R031** "Install locked SDKs and run network tests" → the network half for mcp-read (Task 4 asserts the locked
     versions while its client crosses the network).
   - **R085** "Worker-chosen tools ignored; handle used with a different azp rejected." → Task 2's exhaustive table,
     Task 3's HTTP cases, the definer's azp case, Task 1's mint test.
   - **R131** "mcp_read can EXECUTE only …; an execute/recover handle at mcp-read … rejected" → the read half (Task 3).
   The brief's 25 rulings map to tasks in "Rulings" above; every refinement is listed under "Rulings needing
   controller attention".
2. **Placeholder scan.** No undecided placeholder, no "similar to Task N", no "add error handling". The template
   markers `<base>`, `<last>`, `<date>`, `<dev passed>`, `<dev skipped>` and `<live passed>` in Task 5 are defined by
   the commands that print them (Task 1 Step 1b, Task 5 Step 5). The `TODO(T47)` Task 2 writes and the `TODO(T16)`
   markers Task 5 writes are ownership markers `docs/CODE_COMMENTS.md` requires, each on the debt list.
3. **Type and name consistency.** `ProtocolVersionGuard(app, *, path="/mcp")`, `PROTOCOL_VERSION`,
   `UNSUPPORTED_PROTOCOL_VERSION` and `REFUSAL` are used with those names in both servers, the worker's client and the
   tests. `TokenVerifier(token_type=…)`, `read_verifier(kc, urls)` and `WorkloadTokenSource.client_id` match their
   callers (`production_app`, `worker.main`) and tests (`test_verifier_t15.production_like` calls `read_verifier`).
   `allowed_tool(job_type, run_state, tool)` is called in that order by `resolve_invocation` and the three test modules.
   `assert_function_text(conn, signature, marker)` is called with `*HANDLE_BINDING` by mcp-read and by the live round
   trip; `HANDLE_BINDING[1]` is a substring of 0009's `JOB_READ_0009` and of no earlier body (a unit test).
   `handlers.Deps(..., worker_name, workload_azp, ...)` is built with the keyword in `main` and the four tests. Task 3's
   helpers `QUERY`, `free_port`, `raw_headers`, `tools_list`, `worker_token` are imported by Task 4 under those names
   (`raw_headers` takes the method as its third argument); Task 1's `FIXTURES`, `ISSUER`, `RESOURCE` and `KeyedVerifier`
   by Task 2; `tests.plan_e.test_transitions_table.REVISIONS` by Task 2's newest-marker test.
4. **Review Focus.** (1) the replay after the outcome → R105's rewritten step, the R006 populated upgrade's refusal
   and the exhaustive allowlist (Task 2), with `test_mcp_write_live.py`'s direct calls (the execution layer only)
   unchanged in the live gate; (2) the worker's client and the guard → the in-process official
   client (Task 1), R105 and Task 4; (3) the guard before auth → Task 1's first HTTP test and Task 3's raw POSTs; (4) a
   handle in a log → Task 3's DEBUG capture with uvicorn's records required, Task 2's refusal log line, Task 4's
   redacted child log; (5) a database before 0009 →
   Task 2's startup tests and the live round trip.
5. **Known risks the executor should watch** (none changes a ruling):
   - The live tests of Tasks 2-4 were written against the real fixtures, helpers and SDK but could not be run in the
     dry run; their first live run is in execution. The in-process unit tests of Task 1 exercise the same guard, SDK
     ladder, bearer middleware and official client, so the HTTP shapes (the raw `tools/list` body and headers, the
     `-32020` and `-32022` codes, the 401 header) were measured there.
   - If `test_r027_no_log_record_carries_the_handle` fails, pytest's "Captured log call" section prints the captured
     records, the one holding the handle included (round 2, m2): treat that output as sensitive. The handle is a test
     handle on `ops_test`, revoked inside the test, and the worker token expires within minutes; nothing needs
     rotating. Its docstring says the same.
   - `test_r027_no_log_record_carries_the_handle` runs the server with uvicorn at DEBUG, makes uvicorn's loggers
     propagate for its duration (an earlier test's default uvicorn config stops them) and restores both afterwards;
     the dry run measured that the same set-up captures `uvicorn.access`, `uvicorn.error`, `mcp.*` and `httpx2` records.
     If a library logs request headers at DEBUG on a path the dry run did not reach, the test fails: a finding to
     report (and to fix by redaction or a logger level), never a reason to raise the capture level.
   - Task 3's handle test moves the global test clock 120 s and resets it in `finally`; it relies on the suite running
     tests one at a time, as it does. The handle's lease is taken for 600 s so the clock step expires the handle, not
     the lease.
   - Task 4's child process inherits this session's environment through `process_environment()` (the `env` fixture
     exported `PROFILE=test` and the test databases); a port taken between `free_port()` and the child's bind would
     fail the readiness wait loudly within 60 s, not hang. The child is terminated in `finally` and killed after 15 s.
   - R105's replay step and the R006 populated upgrade now expect a refusal (ruling (a) above); if the controller
     overrules (a), the binding's condition and the run-state rule change and both steps stay as they were.
   - `serving()` turns uvicorn's `sys.exit` on a failed lifespan start into a `RuntimeError`, so a missing revision or
     an unreachable realm fails the test with its purges run, instead of a SystemExit leaving the event loop.
   - `assert_function_text` reads `pg_proc.prosrc`; the round trip runs it against the database at 0008 and at 0009 as
     `mcp_read`, which is the first live proof that the catalog is readable by that role.

## Round 1 changes

Inputs: the controller's rulings on the round-1 static review (`round1-rulings.md`: REVISE, 1 Blocking, 3 Important,
11 Minor, all accepted) and the critic's evidence (`round1-static.md`). Every ruling is applied in this text; nothing
was declined. The plan was re-applied task by task to a `git archive` copy of `afd7aaf` with `ruff format` between
tasks: every quoted old text matched once, `ruff format` changed nothing, ruff, mypy strict and `verify_handoff` passed
after every task, every red step was reproduced, and the dev counts below are the measured ones.

- **B1 (Task 2; Global Constraints; ruling (a); Review Focus 1).** `tests/e2e/test_migrations_and_persistence.py::
  test_r006_populated_revision_1_database_upgrades_in_place` seeds its migrated SUCCEEDED run's execute job finished,
  which 0009 refuses. Task 2 Step 5 Edit 4 now asserts that refusal (`HandleRejected` from `lookup_action`), reopens the
  job and asserts the grant, as the critic proposed; the module is in Task 2's Files, its commit and the Global
  Constraints' list of edited tests. The live counts were never short a test, but every live gate from Task 2 on would
  have been red; they now follow from the corrected dev counts.
- **I1 (Tasks 1, 5; the Architecture, ruling 2, erratum 74).** mcp-read's verifier is built by one function,
  `ops_mcp_read.server.read_verifier(kc, urls)`, which `production_app` calls and `test_verifier_t15.production_like`
  calls with a stub `Keycloak` and `Urls`, so the `typ` refusals run through the real wiring; the new
  `test_the_sdk_resource_check_is_on` pins `validate_token_resource is True` on the built server. `read_verifier`,
  `validate_token_resource=True` and the new `McpVerifier` docstring moved from Step 8 to Step 6 (Step 6 makes the
  verifier tests pass). `McpVerifier`'s docstring, erratum 74, the R026 note, the handoff note, the runbook and
  ARCHITECTURE now credit the refusal to `McpVerifier`'s own `aud` check and call the SDK's resource check a second
  layer that cannot fire while the stamp is the server's own URL.
- **I2 (Task 3; Task 4's docstring; Review Focus 4; the R027 note; the runbook; the self-review).** `serving()` takes a
  `log_level`; the log test runs it at `"debug"`, makes uvicorn's four loggers propagate for its duration (an earlier
  test's default uvicorn dictConfig stops `uvicorn` and `uvicorn.access` propagating, measured in the dry run) and
  restores their levels and propagation in `finally`, and fails unless `uvicorn`, `mcp` and `httpx2` records were
  captured. Its docstring, `serving()`'s and the runbook's say that uvicorn's TRACE level logs headers and is enabled
  nowhere. The child process's log is described as written through its redaction filter, a weaker check.
- **I3 (Task 2; Task 5; Review Focus 1; ruling (a)).** Task 2 Step 5 Edit 5 rewrites `execution.py`'s replay rule: the
  stored branch is unreachable through the tool once the outcome is recorded, which production never needed, and
  reachable by a direct caller or a second call inside one open job. R105's comment, the mcp-write README edit, the
  handoff note and Review Focus 1 say that through the tool a replay is answered only while the run is APPROVED or
  EXECUTING, and that `test_mcp_write_live.py`'s direct calls prove the execution layer, not the tool.
- **M1 (Task 3).** The R085/R131 test stages a recover job for the approved run (superuser insert, dedup key
  `<uuid>:timeout`), mints a write handle for it under the run's lease and asserts it is refused at mcp-read; the R131
  note, ruling 10 and the self-review name both handle types.
- **M2 (Task 4; the R026 note; ruling 14).** The R026 test mints a valid read handle and posts a raw `tools/call` of
  `search_procedures` carrying it with each foreign token (401 `invalid_token`), then the same call with the worker's
  token, whose result envelope is `ok`. Task 1's HTTP test posts the same raw `tools/call` shape in-process (200, the
  envelope refusing the missing handle), so the live body is measured.
- **M3 (Tasks 3, 4).** The protocol test requests `migrated`; the R026 test now requests `app_conn`, which depends on
  it.
- **M4 (Task 3).** `serving()` runs uvicorn through `guarded()`, which turns uvicorn's `sys.exit` on a failed lifespan
  start into a `RuntimeError`, and settles the task with `asyncio.wait` (never a cancel); the comment says why.
- **M5 (the runbook; Global Constraints).** "Every refusal of a presented handle"; a call without a handle gets the same
  code with "missing invocation handle".
- **M6 (STATUS).** The finished-job refusal is attributed to the definer, the others to HTTP.
- **M7 (erratum 76, short and full).** "At the start of every MCP call (`persistence.resolve_invocation`)", with the
  definers' own resolutions named as not applying it.
- **M8, M10 (Task 2).** `test_allowlist.py`'s docstring matches its test; the handle is bound to booleans before the
  assertions.
- **M9 (Task 2).** `test_the_newest_body_of_resolve_handle_carries_the_startup_marker` walks `REVISIONS` and requires
  the newest `_resolve_handle` body to carry `HANDLE_BINDING[1]`; the comment at `HANDLE_BINDING` says a later body must
  keep the text or change it in the same commit.
- **M11 (the runbook; the R027 note; Task 1).** The runbook's query says it needs the owner's migration; the new unit
  test `test_the_model_request_has_no_field_for_a_handle` pins `DraftRequest`'s four fields, and the R027 note cites it.
- **Step Expected lines re-measured.** Task 1 Step 5 `9 failed` (all `AttributeError`), Step 6 `9 passed`, Step 8
  `21 passed`, Step 9 `2 failed, 1 passed`, Step 10 `47 passed`; Task 2 Step 4 `51 passed`; the other red steps
  print what round 0 recorded.
- **Counts.** Dev (measured): Task 1 1056/154, Task 2 1070/157, Task 3 1070/162, Task 4 1070/164, Task 5 1070/164. Live
  (arithmetic): 1189, 1206, 1211, 1213, with 21 skipped. Errata keep their numbers (72-81); 74 and 76 are reworded.

## Round 1 open points

- No live step has run in any dry run; the new and reworked live tests of this round (the R006 refusal, the recover
  handle, the DEBUG capture with uvicorn's records required, the R026 `tools/call`, the guarded start) are first
  exercised in execution.
- The DEBUG capture changes uvicorn's logger levels and propagation for its duration and restores them; another test
  that relied on uvicorn's default propagation after it would not notice, since both are put back exactly.

## Round 2 changes

Inputs: the round-2 static review (`round2-static.md`: ACCEPT, 0 Blocking, 0 Important, 7 Minor) and the controller's
instruction to fold m1-m7 in as the critic proposes. All seven are applied; nothing was declined. The plan was
re-applied task by task to a `git archive` copy of `afd7aaf` with `ruff format` between tasks: every quoted old text
matched once, `ruff format` changed nothing, ruff, mypy strict and `verify_handoff` passed after every task, every red
step was reproduced, and the dev counts below are measured.

- **m1 (Task 3).** The log test flips uvicorn's propagation inside its `try`, after the set-up, so the `finally` that
  restores levels and propagation always runs once anything was changed; round 1's open point ("both are put back
  exactly") now holds on a failed set-up too.
- **m2 (Task 3's docstring; the Global Constraints' secrets rule; the Self-review's known risks).** A failing log test's
  "Captured log call" section prints the record that held the handle: the test handle on `ops_test`, revoked inside
  the test, beside a worker token that expires within minutes. The output is to be treated as sensitive; nothing needs
  rotating.
- **m3 (Task 3).** `serving()` re-raises the server task's exception after a normal exit of its body, so a failure in
  uvicorn's main loop or shutdown after a successful start is surfaced, not only logged; a failed start is still
  raised by the polling loop, and the task is still settled with `asyncio.wait`, never cancelled.
- **m4 (Task 1).** `test_production_app_builds_its_verifier_through_read_verifier` stubs `settings.keycloak`, `urls` and
  `fixtures_dir`, wraps `server.read_verifier` with a recorder, calls `server.production_app()` and asserts one call
  with the stubs, so the wiring `read_verifier`'s docstring describes is pinned.
- **m5 (Task 2 Step 5 Edit 5).** `execution.py`'s docstring now says the stored branch is reached by a direct caller or
  by an overlapping call that resolved its handle before the outcome was recorded.
- **m6 (Self-review; ARCHITECTURE).** Self-review item 1 credits `McpVerifier`'s audience check with the SDK's resource
  check as an inert second layer, and its R027 bullet cites the `DraftRequest` test; the ARCHITECTURE R131 row names a
  recover and an execute handle; two wraps are fixed.
- **m7 (the R026 note).** It credits `read_verifier`'s audience check (PyJWT's `aud`) for the live refusals, with
  `McpVerifier`'s own check behind it and the SDK's resource check a third, inert layer. Erratum 74 stays as worded.
- **Step Expected lines re-measured.** Task 1 Step 5 `10 failed`, Step 6 `10 passed`, Step 8 `22 passed`, Step 10
  `48 passed`; Task 2 Step 4 `52 passed`; the other steps print what round 1 recorded.
- **Counts.** Dev (measured): Task 1 1057/154, Task 2 1071/157, Task 3 1071/162, Task 4 1071/164, Task 5 1071/164. Live
  (arithmetic): 1190, 1207, 1212, 1214, with 21 skipped.

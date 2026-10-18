# Plan J review record — T15 authenticated MCP read server, token verifier and invocation handles

Plan: `docs/superpowers/plans/2026-10-15-first-slice-j-mcp-read-verifier-handles.md` (branch `plan-j`; plan commit 539ca08, round fixes 172def3 and 44e16f1). Inputs:
`docs/superpowers/research/2026-10-15-plan-j-inputs.md` and the controller's rulings brief (reproduced below). Each
round is one static adversarial review that also applied the plan task by task to a scratch copy (ruff format between
tasks, ruff, mypy strict, non-live pytest, dev counts, red steps); the plan writer's own dry run stood in for a builder
dry run, and live steps cannot run in a dry run (the permission policy refuses copying `.env` into a scratch worktree).
Round 1: 1 Blocking, 3 Important, 11 Minor. Round 2: ACCEPT (0 / 0 / 7); the minors were folded in without a third round.

---

# Controller brief (rulings before round 1)

# Plan J brief — controller rulings for T15 (authenticated mcp-read, token verifier, invocation handles)

Branch `plan-j` (= `plan-i` deb6ec7). Fact sheet: `docs/superpowers/research/2026-10-15-plan-j-inputs.md` (FS).
Errata continue at **72**. Requirements: R025 (read half), R026, R027, R031 (network half), R085, R131 (read half).
Gates at start: dev 1032 / 154; live 1165 / 21; verify_handoff 0.

## Rulings (one per FS question)

1. **Scope (FS Q1).** T15 is hardening plus evidence over the existing mcp-read: the run-state allowlist (6), the
   handle's job binding (6), strict protocol-version enforcement (4–5), a stricter verifier (2), a startup guard
   (18), the workload azp at mint (17), and live tests for every DoD case (10–12, 14, 22). No new read tool.
2. **Verifier (FS Q2).** mcp-read's verifier stamps `AccessToken.resource` with its own resource URL only when `aud`
   contains it (it already refuses otherwise) and turns `validate_token_resource` on; it requires `typ == "Bearer"`
   on access tokens (Keycloak sets it; a unit test pins both the pass and the refusal); refusals stay HTTP 401 at the
   MCP servers (Plan D ruling 25). The verifier stays per-service (ADR-0003 separation); mcp-write gets the same
   change in T47 (debt line).
3. **Resource-server requirements (FS Q3).** The SDK's protected-resource metadata route stays; nothing further is in
   scope (record as a sentence in the runbook, no erratum).
4. **Protocol version (FS Q4).** A pure ASGI guard in `core` (shared), mounted in front of the SDK app in **both** MCP
   servers (the rule is SA:571's for every MCP server; the worker client already pins 2026-07-28, so nothing breaks):
   a POST to the MCP path must carry `MCP-Protocol-Version: 2026-07-28`; absent or any other value → HTTP 400 with a
   JSON-RPC error body (`-32022`-style "unsupported protocol version", no echo of the sent value), before the SDK and
   after nothing else (auth runs inside the SDK app; ordering: the guard refuses before auth — state that an
   unauthenticated client learns only the version rule). Health and metadata routes untouched. Erratum: the legacy
   stateless path is closed.
5. **Mismatch tests (FS Q5).** Raw `httpx2` POSTs with a valid workload token: header absent → 400 (guard); header
   `2025-*` → 400 (guard); header 2026-07-28 with a different `_meta` version → the SDK's `HEADER_MISMATCH` 400.
6. **Allowlist and handle binding (FS Q6).** The allowlist stays in Python (erratum 19): `allowed_tool(job_type,
   run_state, tool)` also requires `run_state ∈ JOB_RULES[job_type].run_states`; refusal = the same `INVALID_HANDLE`.
   A new revision `0009_handle_binding` re-creates `_resolve_handle` to also require the handle's job to belong to the
   handle's run (`jobs.run_id = ic.run_id`) and to be not done (`jobs.done_at IS NULL`); exact downgrade to 0008
   (0007/0008 re-run-the-applied-body pattern).
7. **Attempt-state filter (FS Q7).** The shared function gains the attempt-state parameter only if needed by today's
   call sites; the write rules ("create_incident only with no attempt or INTENT, not cancelled, before deadline") are
   T47/T22's (debt line).
8. **Tools (FS Q8).** mcp-read registers only `search_procedures` in T15; `get_asset_status`/`get_recent_alerts` and
   asset-sim are T16. DoD 1 is met by `list_tools` + `call_tool` of the registered tool.
9. **`search_procedures_scoped`, `asset_scope` (FS Q9).** Not created in T15 (no caller; Plan E ruling 1): `asset_scope`
   → T16, `search_procedures_scoped` → T17/T16. The fixture corpus stays.
10. **R131 read half (FS Q10).** The test asserts `mcp_read`'s EXECUTE set equals `{current_time, resolve_invocation}`
    today (erratum: the target set of SA:459/R131 gains `asset_scope`, `search_procedures_scoped` with T16/T17;
    `current_time` stays per erratum 15), `has_function_privilege` is false for every write-path function, one
    attempted write-path call fails 42501, and live: an `execute` handle presented to mcp-read → `INVALID_HANDLE`, and a
    lying `invocation_context.server` (set by the superuser) → refused.
11. **R027 / DoD 2 handle cases (FS Q11).** Live, at HTTP: replayed after release (revoked) → refused; expired (test
    clock past `expires_at`, reset in `finally`) → refused; other-run (the superuser points the handle's `job_id` at
    another run's job) → refused by ruling 6's binding; a lapsed lease / moved fence → refused. Other-azp: at the
    definer (direct `resolve_invocation` call with another azp) and at the verifier (unit, synthetic token).
    "Handle absent from logs": a live call with log capture shows no raw handle anywhere in the captured records.
12. **Independent-process client (FS Q12).** The live test starts mcp-read as a **subprocess** (`python -m
    ops_mcp_read`, test profile, a free loopback port, env built like the skeleton's) and connects with the official SDK
    `Client` from the test: `list_tools` lists exactly the registered tools, `call_tool` succeeds with a valid handle.
    mcp-write's half of R025 → T47.
13. **Error envelopes (FS Q13).** Unchanged: every handle refusal is one `INVALID_HANDLE` envelope (no hint which check
    failed; no `action_id` ever); token failures stay 401. Distinguishing 401 in the worker → T20 (debt line).
14. **Browser token (FS Q14).** The live test uses the `ops-dev-direct` persona token (aud `ops-api`) as the browser
    stand-in and the unit test the synthetic `azp=ops-web` token; the evidence says plainly that no real `ops-web`
    access token is minted (the API stores none; minting one needs the client secret).
15. **Missing aud (FS Q15).** The synthetic-JWKS unit case is the evidence; recorded as such.
16. **TLS and hosts (FS Q16).** → T30 (debt line).
17. **Worker client (FS Q17).** The handle's stored azp comes from the worker's configured workload client id (the
    token source's `client_id`) instead of the literal; discovery/schema checks → T16 (R029); `resume_input` → T20.
18. **Startup guard (FS Q18).** mcp-read asserts at start that revision 0009 is applied (a check on
    `_resolve_handle`'s binding or `alembic_version`, matching the other services' pattern) in addition to the clock
    profile.
19. **Reads and the fence (FS Q19).** Accepted as is (erratum): a read result is served after the handle resolved in
    its own committed unit; a fence that moves mid-read cannot cause a write, and the worker's next fenced unit fails.
20. **Arguments (FS Q20).** Untouched (T16/T17).
21. **azp binding (FS Q21).** Covered by 17; the write-path literal `'ops-worker'` in mcp-write's definers → T47.
22. **R085 "worker-chosen tools ignored" (FS Q22).** Evidence: a call to a tool name outside the job type's allowlist
    and a call in a run state outside the job's states → refused; an unregistered tool name → the SDK's unknown-tool
    error; the lying `server` column (10).
23. **Matrix bookkeeping (FS Q23).** T15 marks R026, R027, R085 fully and R025/R031/R131 with "read half" notes; evidence
    under `reports/mcp-read/`; unit tests in `tests/plan_j/`.
24. **Odd cross-references (FS Q24).** Propose errata for SA:34 (audience wording points at AM-20.6), SA:459 (lock
    column and return superseded by errata 53/19), BS:360 (no handle refresh; one handle per job, 60 s).
25. **Layout (FS Q25).** Keep `tests/plan_j` and `tests/e2e`; per-service tests/Dockerfiles → T30.

## Task shape (≤ 5 tasks)
1. Debt list; the protocol-version guard (core) mounted in both servers; the verifier changes; the workload azp at mint;
   unit tests.
2. Revision 0009 (`_resolve_handle` job binding), the run-state allowlist, mcp-read's startup guard; unit + live
   migration tests.
3. Live evidence: R027/R085/R131 handle and ACL cases; protocol-version cases; logs carry no handle.
4. The independent-process client (R025 read half, R031 network half, DoD 1) and the token cases (R026).
5. Close-out (handoff, matrix rows, errata 72+, runbook `docs/runbooks/mcp-read.md`, STATUS, SESSION_STATE incl. the
   owner input "migrate dev to 0009", ARCHITECTURE, PROJECT_HISTORY, READMEs, final gates).

## Standing constraints
Carry Plan I's Global Constraints (no attribution; CODE_COMMENTS; debt before code; app.current_time() after locks; one
string per SQL function + ISC004; live tests only on test databases; never migrate dev; no secrets — a raw handle or
token never in a log, assert operand or evidence; never cancel a database unit; pids before transactions; settle tasks
before purges; red-step Expected lines as pytest prints them). Dry runs cannot run live steps; mark live counts as
arithmetic. A subprocess server in a test must be terminated in `finally` and must not inherit secrets through its
command line (environment only, as the skeleton does).

---

# Round 1

## Static review

## Plan J round 1: static adversarial critic

Plan: `docs/superpowers/plans/2026-10-15-first-slice-j-mcp-read-verifier-handles.md` (3,638 lines, branch `plan-j`,
539ca08).

**Verdict: REVISE.** 1 Blocking, 3 Important, 11 Minor.

Every splice applies, and every per-task dev count matches the plan exactly. After every task:
- `ruff format` changes nothing;
- ruff and mypy strict are clean;
- `verify_handoff` exits 0.

Every red step's Expected line matches what pytest prints, including the stated reasons. The protocol-version guard is
sound:
- it runs before the bearer middleware;
- it echoes nothing;
- it leaves health, metadata and GET alone;
- the worker's pinned client passes it on every POST.

The worker's token still passes at mcp-read. The `typ` claim is right for Keycloak's access tokens. Revision 0009 is
0007's body with one statement changed, and its downgrade is exact.

The binding breaks no production path. The execute job stays open for the whole `create_incident` call, as traced
below. The next-plan computation (T47) and the restored SESSION_STATE heading are correct.

The Blocking finding is a live test that the binding breaks and that the plan does not edit. The live gate goes red
from Task 2 onward. The Important findings are:
- two production settings of the stricter verifier are pinned by no test, and one of them (`validate_token_resource`)
  can never fire as wired, yet five documents cite it as a check;
- the DEBUG log test does not capture uvicorn's records, and the child's log is checked only after redaction;
- through the tool, mcp-write's stored-outcome replay is now unreachable, but the README, the handoff note and Review
  Focus 1 still describe it, with evidence that bypasses the server's check.

### How this was checked

**Reading.** I read:
- the whole plan, the controller's brief (25 rulings), the accepted refinements (a)-(i), and the fact sheet's T15
  sections;
- every function 0009 touches or depends on:
  - 0007 `RESOLVE_HANDLE`, `REVOKE_HANDLES` and `MARK_SENT`;
  - 0004 `lookup_action` and its `_resolve_handle(…, 'ops-worker', 'write')` call;
  - the other callers of `_resolve_handle` in 0004, 0005 and 0007;
- `privileges.py` (`DEFINER_FUNCTIONS`, `HELPER_FUNCTIONS`, the jobs grants and RLS);
- in `persistence.py`: `_call`, `translate`, `resolve_invocation`, `allowed_tool`, `mint_handle`, `revoke_handles`,
  `release_lease`, `requeue_job` and `finish_job`;
- `jobs.JOB_RULES`;
- the worker's `handlers.py` and `main.py`;
- mcp-read's and mcp-write's `server.py`, and mcp-write's `execution.py`;
- `redaction.py`, and `scripts/skeleton.py` (`process_environment`, `healthy`, `Skeleton.stop`);
- every e2e helper the new tests import;
- every live test that mints, inserts or resolves a handle, or calls a write-path definer (16 modules; list under
  "Checked and found sound");
- the installed SDK's code:
  - `mcp/server/auth/middleware/bearer_auth.py` and `mcp/server/mcpserver/server.py` (auth wiring, the unknown-tool
    path);
  - `mcp/server/_streamable_http_modern.py` (the header ladder, `Mcp-Param` validation);
  - `mcp/client/session.py` (`call_tool` validation);
- uvicorn 0.54's `config.configure_logging` and `server.startup`, and `httpcore2/_trace.py`.

**Applying the plan.** I took a `git archive HEAD` copy (`critic1/tree`), made it a git repo, and ran
`uv sync --frozen --offline`. Then I applied Tasks 1-5 in order with an Edit/Create parser (`critic1/apply.py`). Each
step's unit `Run:` line ran where it stands. Task 5's handoff and README scripts ran verbatim, with `BASE` set to the
copy's root commit. After each task I ran `ruff format`, `ruff check`, `scripts/check.py` and `verify_handoff`. Every
quoted old text matched exactly once.

| After task | ruff format | ruff check | mypy strict | pytest (dev) | verify_handoff |
|---|---|---|---|---|---|
| base | - | - | clean | 1032 / 154 | 0 |
| 1 | no change | clean | clean, 57 | **1054 / 154** | 0 |
| 2 | no change | clean | clean, 57 | **1067 / 157** | 0 |
| 3 | no change | clean | clean, 57 | **1067 / 162** | 0 |
| 4 | no change | clean | clean, 57 | **1067 / 164** | 0 |
| 5 | no change | clean | clean, 57 | **1067 / 164** | 0 |

**Red and intermediate steps.** I re-ran each step's command with the task applied up to that step, in worktrees at the
base and Task 1 commits (`critic1/partial.py`). Every Expected line matched, reasons included:
- T1 S3: `1 error` (`ModuleNotFoundError ops_core.mcp_protocol`).
- T1 S4: `8 passed`.
- T1 S5: `8 failed` (seven `TypeError … 'token_type'`, then the `AttributeError`).
- T1 S7: `3 failed, 1 passed`, failing with 401≠400, 200≠400, and `RuntimeError: Task group is not initialized`.
- T1 S8: `20 passed`.
- T1 S9: `2 failed` (`['ops-worker'] == ['ops-worker-renamed']`).
- T1 S10: `45 passed`.
- T2 S1: `12 failed, 12 passed` (11 `TypeError`, 1 `DID NOT RAISE`).
- T2 S2: `24 passed`.
- T2 S3: `2 errors` (`HANDLE_BINDING` import, and the transitions module's existence assert).
- T2 S4: ISC004 `All checks passed!`, then `48 passed`.

**Task 5.** After it ran:
- the handoff diff touches exactly three files, and in the matrix exactly R025, R026, R027, R031, R085 and R131;
- both `git grep` commands print nothing;
- `build_schemas` prints the predicted summary and changes no file;
- no new or edited line is over 120 characters.

**Live arithmetic.** 1187, 1203, 1208 and 1210 follow from the measured dev counts plus 133, 136, 141 and 143. They are
marked as arithmetic. Finding B1 makes 1203, 1208 and 1210 wrong: one test fails.

**Mutation probes.** I flipped Task 1's `validate_token_resource=True` back to `False` in a scratch worktree.
`tests/plan_j` and `tests/plan_d` still pass (106 passed). See I1.

**Not run.** No live test was run and no database was touched. I judged PostgreSQL, asyncio and uvicorn behaviour
statically, against the installed code.

---

### Blocking

**B1 — Revision 0009 breaks `test_r006_populated_revision_1_database_upgrades_in_place`, which the plan does not edit, so
the live gate is RED from Task 2 on.**

Where:
- plan Global Constraints 65-67 ("Task 2 edits two Plan D/E allowlist tests, the revision list and R105's replay
  step");
- Task 2 Files 1408-1413;
- `JOB_READ_0009` 1907-1913;
- Task 2 Step 7's live Expected 2227-2228 (`1203 passed, 21 skipped`), and Tasks 3-5's live counts after it.

Evidence:
- `tests/e2e/test_migrations_and_persistence.py:355-358` seeds the migrated SUCCEEDED run's execute job *finished*:
  `"INSERT INTO app.jobs (id, type, run_id, dedup_key, done_at) VALUES (%s, 'execute', %s, %s, now())"`.
- After `migrate`, it takes the run's first lease (`:403`). It then mints a write handle for that job and asserts
  `persistence.lookup_action(mcp_exec, handle=handle)` returns the RESOLVED grant (`:409-410`).
- `app.lookup_action` (0004:335-351, never re-created since) calls `app._resolve_handle(p_raw_handle, 'ops-worker',
  'write')`.
- Under 0009 that function reads the job with `… AND j.done_at IS NULL`. The job is done, so `v_job_type` is NULL and
  `v_job_server` is NULL. The server check raises OC008, and `persistence.lookup_action` raises `HandleRejected`
  uncaught.

The test fails on every live run from Task 2 on. Its `finally` still migrates and purges, so the damage stays
contained.

I grepped every other live handle path:
- `handle_for`, `approved_run`, `read_handle`, the stress actors, `ResolvingMcp`;
- the three direct `invocation_context` INSERTs;
- every `done_at` write in `tests/e2e`.

Each of them names its own run's open job. This is the only casualty.

Why it matters:
- the plan's "No interim red across tasks" constraint is broken at Task 2;
- every later live count is off by one;
- an executor who finds it will be tempted to "fix" the revision, because the plan does not say which side is wrong.

The test is wrong under ruling 6: a migrated run's finished job is exactly what 0009 now refuses.

Fix: add the module to Task 2's Files and Global Constraints. In Step 5, add an edit that keeps the migrated job as it is
and proves the binding covers migrated rows. In `tests/e2e/test_migrations_and_persistence.py`, replace:

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

`pytest` is already imported there (`:185`), and `purge_run` removes the job in `finally`. No worker runs during that
module, so the reopened job is never claimed. The test count does not change.

A smaller alternative is to drop `done_at` from the INSERT at `:357`, but that loses the migrated-row evidence.

---

### Important

**I1 — Two of Task 1's production settings are pinned by no test, and one of them cannot fire as wired. Five documents
present it as a check.**

Where:
- `validate_token_resource=True` (1047) and `token_type="Bearer"` in `production_app` (1091);
- `McpVerifier`'s docstring (824-826: "the SDK compares the two again … this is the SDK's own check on top");
- `test_verifier_t15.py`'s docstring (647: "with the verifier configured as `production_app` configures it") and
  `production_like()` (666-672);
- erratum 74 (277-278, 3142-3144);
- the handoff note (2956-2957);
- the R026 matrix note (2988: "a token whose audiences lack the resource is 401 through the SDK's check");
- runbook step 2 (3296-3300);
- ARCHITECTURE (3380-3381: "the SDK checks the resource again").

Evidence:
- `build_server` passes the same `resource_url` both to `AuthSettings(resource_server_url=…)` and to `McpVerifier`.
- After Edit 5, `McpVerifier` either returns None or stamps `resource=self._resource`, which is that same URL.
- `BearerAuthBackend._issued_for_this_resource` (installed `bearer_auth.py:84-88`) therefore compares a URL with
  itself, and can never refuse.
- Every refusal the plan attributes to "the SDK's check" is in fact `McpVerifier`'s new line, `if self._resource not
  in principal.audiences: return None`. That covers the `elsewhere` token in `test_the_ladder_…` and the `wrong`
  verifier in `test_the_resource_is_stamped_only_from_the_audience`.
- Mutation: with Edit 3 reverted to `validate_token_resource=False`, `tests/plan_j` and `tests/plan_d` pass unchanged
  (106 passed).

Likewise, `production_like()` restates `production_app`'s arguments; it is not `production_app`. Dropping
`token_type="Bearer"` from `production_app` fails no unit test. No live test fails either, because the only tokens
presented live are real access tokens, with `typ` "Bearer". So ruling 2's "`typ == "Bearer"`, a unit test pins both the
pass and the refusal" holds for the knob, not for mcp-read.

Why it matters: this is the security change the brief ruled on, and the lesson is "tests exercise what their docstrings
claim; docs claim nothing beyond evidence". As written, a refactor could silently drop either setting, and the erratum
and matrix would keep citing an SDK check that never decides anything.

Fix:
1. Factor mcp-read's verifier construction into one function, for example `read_verifier(kc, urls) -> TokenVerifier`.
   `production_app` calls it, and `test_verifier_t15.production_like()` calls it with a stub `Keycloak`/`Urls` and
   installs `JWK1`. The unit test then pins the real wiring.
2. Add an assertion that `build_server(...).settings.auth.validate_token_resource is True`, so the setting is pinned.
3. Reword the five places to name the check that actually refuses. For example: "`McpVerifier` refuses a token whose
   `aud` lacks this server's URL and stamps only that URL; `validate_token_resource` is on as a second line that cannot
   fire while the verifier stamps its own URL". Change R026's note to "401 through `McpVerifier`'s audience check".
   Erratum 74 should not say "the SDK compares the two" as if that comparison were the protection.

**I2 — The DEBUG log test does not capture uvicorn's records, and the child-process check reads a redacted log. Review
Focus 4, the test's docstring, the R027 matrix note and the runbook claim more than that.**

Where:
- `serving()` 2376-2393: `uvicorn.Config(production_app(), …, log_level="warning", log_config=None)`;
- `test_r027_no_log_record_carries_the_handle` 2566-2599 (its docstring: "Every record … captured at DEBUG before any
  redaction filter");
- Review Focus 4 (134-137: "The guard, the SDK, uvicorn, httpx2 and `persistence` all log … none may record it, at any
  level, before any redaction filter");
- Task 4's child log 2720-2752 and 2776-2777, with its docstring 2672;
- the R027 note 2998-3000 ("captured at DEBUG before any redaction … nor does the child process's log");
- runbook 3346-3347;
- Self-review 5 (3625-3627).

Evidence:
- `caplog.set_level(logging.DEBUG)` sets the root logger only.
- `serving()` then builds `uvicorn.Config(…, log_level="warning")`. Uvicorn 0.54's `Config.configure_logging`
  (installed `config.py:419-426`) runs `logging.getLogger("uvicorn.error"/"uvicorn.access"/"uvicorn.asgi").setLevel(
  WARNING)`. Uvicorn's own records below WARNING, the access line for every request included, are never created, let
  alone captured.
- The capture does cover the SDK, httpx2/httpcore2 and `persistence`. I read their DEBUG paths: httpcore2 logs
  `send_request_headers.started request=<Request [b'POST']>`, which carries no header values. So the test will very
  likely pass, but it does not test uvicorn, which the focus names.
- Uvicorn's TRACE level enables its `MessageLoggerMiddleware`. That middleware logs each ASGI scope with its header list
  (bearer token and `X-Ops-Invocation` included). Production pins `warning` (`serve_app`), but nothing records that
  TRACE is excluded.
- Task 4's child runs `serve()`, which calls `redaction.install()` before anything logs. That filter rewrites
  `x-ops-invocation: …` values, and the child logs at the service's level with uvicorn at WARNING. So "nor does the
  child process's log" holds only after redaction, which is what the R027 note says it is "before".

Why it matters: the brief asks specifically whether the log-capture test "really captures the request path at DEBUG".
For the server's own HTTP layer it does not. The evidence and the runbook state the stronger claim.

Fix:
1. Give `serving()` a `log_level` parameter, and pass `"debug"` from the log test. Then add a non-vacuity check, for
   example `assert any(r.name.startswith("uvicorn") for r in caplog.records)`. A `serving()` built with
   `log_level="debug"` sets uvicorn's loggers to DEBUG, so the access lines are captured too.
2. State in the test docstring, the runbook's "A handle in a log line" bullet, and Review Focus 4: uvicorn's TRACE
   level logs request headers, and mcp-read must never run at it (`serve_app` pins `warning`).
3. Reword the R027 note and Task 4's docstring: "the child process's own log, written through the service's redaction
   filter, holds no handle" is a weaker check than the in-process DEBUG capture.
4. Optionally, reset the uvicorn logger levels in the test's `finally`. The `setLevel` calls are process-global and
   outlive the test.

**I3 — After the run-state rule, mcp-write's stored-outcome replay is unreachable through the tool. Three places still
describe it, and the evidence they cite bypasses the server's check.**

Where:
- Review Focus 1 (119-125: "a replay inside an open execute job … must still be answered … `test_mcp_write_live.py`'s
  idempotent replays (open job, direct calls) run unchanged");
- ruling (a) (220-221);
- R105's new comment (2024-2028);
- the handoff note (2963-2964: "the idempotent replay inside an open execute job is test_mcp_write_live.py's");
- the `mcp-write/README.md` edit (3514-3515: "A replay within the open job returns the recorded outcome");
- `mcp-write/src/ops_mcp_write/execution.py:4-8` (module docstring, "Replay rule … if its attempt is RESOLVED the stored
  outcome is returned"), which the plan leaves as is.

Evidence:
- An attempt reaches RESOLVED only through `record_outcome`. That function moves EXECUTING or OUTCOME_UNKNOWN runs to
  SUCCEEDED, FAILED or ESCALATED (`states.py:193-200`), or records late evidence on a run that is already terminal.
- So whenever `next_step(...) == "stored"`, the run is outside `JOB_RULES[EXECUTE].run_states == {APPROVED,
  EXECUTING}`. `server.create_incident` calls `persistence.resolve_invocation(…, tool=CREATE_INCIDENT)` first
  (`server.py:181-185`), and after Task 2 that refuses such a call.
- Through the tool, a replay inside an open job is answered only while the run is APPROVED or EXECUTING: the re-queue
  re-sends under the same action id.
- `test_mcp_write_live.py:127-128` calls `execution.create_incident` directly. That path never passes through
  `server.create_incident`'s `resolve_invocation`, so it proves the execution layer's replay rule, not the server's
  behaviour that the README describes.

Production is unaffected. I traced the full order:
- `handlers.execute` checks the run state before minting (`handlers.py:217-222`);
- `handle()` releases only after the call returns;
- `release_lease(requeue_seconds=…)` keeps the job open (`requeue_job`);
- the `_read_back` and `lookup_action` path inside one call has no Python allowlist.

Why it matters: the plan changes a Plan D review-focus behaviour on purpose (ruling a, accepted), but the README,
handoff note and history it writes describe the old guarantee, against evidence that does not exercise it.

Fix:
1. Reword the README edit. Suggested text: "A replay while the run is still APPROVED or EXECUTING (the re-queue after a
   transport failure) re-sends under the same action id and the destination's key answers; once the outcome is
   recorded, any replay is refused `INVALID_HANDLE` before the grant (T15)".
2. Add a Task 2 edit to `execution.py`'s module docstring saying the same: the `stored` branch is reached by a direct
   caller or a concurrent caller inside one call, never through the tool after the outcome.
3. Correct the handoff note and Review Focus 1 to say what `test_mcp_write_live.py` proves (the execution layer's
   idempotency). The tool path's EXECUTING re-send is covered by the exhaustive allowlist table only.

---

### Minor

**M1 — T15 DoD 4 names "an execute/recover handle presented to mcp-read", but only an execute handle is staged.**

Where: Task 3's R085/R131 test (2476-2509), Self-review 1 (3579-3580), and the R131 note.

The recover branch is the same `CASE` arm in `_resolve_handle`, but T15 is closed DONE against that DoD.

Fix: in `test_r085_r131_…`, have the superuser insert a recover job for the approved run (`type 'recover'`,
`dedup_key f"{uuid4()}:timeout"`), mint a `Server.WRITE` handle for it under a lease, and `assert_refused` it at
mcp-read. Alternatively, say in the Self-review that "recover" is covered only by the shared `CASE`.

**M2 — R026's live test posts `tools/list` only, so "refused before the tool runs" and "forwards nothing downstream" are
vacuous.**

Where: 2784-2809; the docstring at 2671-2672; the R026 note at 2985-2986 ("the tool never runs and mcp-read forwards
nothing downstream").

No tool would run on a `tools/list` request in any case.

Fix: post a `tools/call` of `search_procedures`, with a valid handle and each foreign token, and assert 401. Then
confirm the handle still answers with the worker's token. That proves the refusal comes before the tool and the
handle.

**M3 — Two live tests start mcp-read against `ops_test` without requesting `migrated`.**

Where: `test_the_protocol_version_is_checked_on_every_request(secret, lines)` (2550) and
`test_r026_foreign_tokens_are_refused_before_the_tool(secret, tmp_path, lines)` (2784).

They pass in module order, because an earlier test pulls `app_conn`, which needs `migrated`. Run alone (`-k`) in a fresh
session, `ops_test` may be missing or at an older head. The server then refuses to start, or the child never becomes
ready, and the failure is misleading.

Fix: add the `migrated` fixture to both signatures.

**M4 — `serving()`'s comment "a failed start raises here instead of waiting for ever" is only half right.**

Where: 2385-2388.

Uvicorn 0.54 answers a lifespan startup failure with `sys.exit(STARTUP_FAILURE)` inside the server task
(`server.py:117-118`), and asyncio re-raises `SystemExit` out of the event loop (`Task.__step`). So the test
coroutine's `finally` (the purges) never runs, and the loop is left with pending tasks. `test_mcp_read_live.py` has
the same pattern, so this is not new.

Fix: say so in the comment. Optionally, check the head (`assert_function_text` as `mcp_read`) and the JWKS before
`server.serve()`, so a predictable startup failure becomes an ordinary assertion.

**M5 — Runbook step 4 says every refusal is "invocation handle rejected", but a missing header gets "missing invocation
handle".**

Where: runbook 3309-3311 (and Global Constraints 48-49).

Both servers answer an absent `X-Ops-Invocation` with `INVALID_HANDLE` and the message "missing invocation handle"
(`server.py`, both tools). That leaks nothing, since the client knows it sent no header.

Fix: say "every refusal of a presented handle".

**M6 — STATUS says each handle refusal was shown "over HTTP", including the finished-job case.**

Where: 3260-3263.

The finished-job refusal is proved at the definer (Task 2's live binding test), not over HTTP.

Fix: drop "finished" from that sentence or attribute it to the definer.

**M7 — Erratum 76 says the run-state rule is checked "at every resolution".**

Where: 3148-3151 (and 280-281).

It runs in the Python `resolve_invocation` only. The SQL resolutions inside `grant_execution`, `mark_sent`,
`record_outcome` and `lookup_action` do not apply it, by design: `record_outcome` must still answer after the run moved.

Fix: "at the start of every MCP call (`persistence.resolve_invocation`)".

**M8 — `test_allowlist.py`'s docstring contradicts its own test.**

Where: 1532-1535.

The docstring says the test catches "a refusal whose message or log line says which check failed". But
`allowed_tool`'s log lines deliberately say which check failed ("does not run in state …"), and
`test_resolution_hands_the_run_state_to_the_check` asserts that text.

Fix: "a refusal whose message says which check failed, or whose log line carries the handle".

**M9 — The startup marker is pinned to 0009's body, not to the newest revision.**

Where: `HANDLE_BINDING` (1984-1987) and `test_the_startup_marker_is_only_in_this_revisions_body` (1781-1786).

A later revision that re-creates `_resolve_handle` and rewords that line would make mcp-read refuse a fully migrated
database. T47 or T22 may well re-create it. Only the live round trip's `MARKER in head["body"]` would notice.

Fix: add a unit test that the newest revision defining `_resolve_handle` contains `HANDLE_BINDING[1]` (the
`newest_literal` pattern of `test_transitions_table.py`), and a comment at `HANDLE_BINDING` saying a later body must
keep the text or update it.

**M10 — `test_resolution_hands_the_run_state_to_the_check` uses the handle as an assertion operand.**

Where: 1604 and 1608: `conn.params == (handle, "ops-worker")` and `handle not in caplog.text`.

The value is synthetic, so nothing real can leak. But the plan's own rule (Global Constraints 52-54) says to bind the
verdict to a boolean first.

Fix: `leaked = handle in caplog.text; assert not leaked`.

**M11 — Two close-out wordings claim slightly more than shown.**

- The runbook's "Looking at it" query joins `app.run_lease`, which the dev database (0005) does not have until the
  owner migrates it. Add "(after the owner's migration to 0009)".
- The R027 note's "the handle never reaches the model (the draft request carries none)" cites no test. Either cite the
  `DraftRequest` field set (FS §3.11), or add a one-line unit assertion that `DraftRequest` has no handle-shaped field.

---

### Checked and found sound

- **The guard.**
  - It is a pure ASGI wrapper on `Mount("/", …)`, and `route_path` handles the root-path case.
  - Header names are lower-cased before the comparison, and exactly one header with exactly the pinned bytes passes.
  - A doubled header is refused, and the refusal is one constant body with `id: null` and a content-length.
  - GET, health, metadata and lifespan pass untouched.
  - It runs before `AuthenticationMiddleware` and `RequireAuthMiddleware` (the in-process 400-vs-401 test).
  - The worker's client sends the header on every POST (the official-client test through the real bearer middleware).
  - Every existing caller of either server uses the official client: R105's `mcp_call`, `test_mcp_read_live`, and
    the worker. No raw POST anywhere would now be refused.
- **The verifier.**
  - The worker's client-credentials token has `typ` "Bearer" (`reports/bootstrap/keycloak-claims.txt`), and its `aud`
    holds both MCP URLs, so it passes at mcp-read. mcp-write is unchanged.
  - Persona tokens (aud `ops-api`) and the `ops-mcp-read`/`ops-mcp-write` tokens fail PyJWT's audience or the `azp`
    check. `WrongAudience` is a `TokenRejected`, so the answer is None, which is a 401 with `error="invalid_token"`
    (`RequireAuthMiddleware._send_auth_error`).
  - The new `typ` check runs after the signature and raises `TokenRejected` without the token text.
- **Revision 0009.**
  - `JOB_READ_0007` occurs once in 0007's body; the upgrade is body then REVOKE, and the downgrade is 0007's body then
    REVOKE, byte for byte.
  - Revision 0008 never touched `_resolve_handle`, so restoring 0007's body restores 0008 exactly. `built_to_0008`
    compares definition, ACL, owner and settings.
  - jobs RLS: `_tenant_of_run` sets the handle's run's tenant before the job read. The new predicates narrow only that
    read, so the tests' same-tenant other-run jobs exercise exactly the new condition.
  - `app_definer` holds table-level SELECT on jobs, so `run_id` and `done_at` are readable.
  - The bind test (`text()._bindparams`) and the ISC004 pass are clean.
- **The binding against production.**
  - `grant_execution`, `mark_sent`, `record_outcome` and `lookup_action` all resolve through `_resolve_handle`.
  - The worker mints the execute handle, makes one MCP call, and only then runs `release_lease` (finish) or
    `release_lease(requeue_seconds=…)`, which keeps the job open.
  - GRANT_DEFERRED and McpCallFailed re-queue the same job id. A re-claim mints a new handle for that same open job.
  - The worker skips the call when the run is past APPROVED or EXECUTING (`handlers.py:217-222`), so it never sends a
    replay the run-state rule would refuse.
  - The recover path: `mark_unknown` queues an open recover job, and the existing live test resolves a recover handle
    for it.
  - A lost lease leaves the job open (`abandon`), and the old handles fail on the fence, as before.
- **The run-state allowlist.**
  - `RECOVER`'s states do not include SUCCEEDED or FAILED, but no MCP tool for it exists yet, and the SQL-only
    definer calls are unaffected.
  - Every live call of the Python `resolve_invocation` is in an allowed state: QUEUED, RETRIEVING or DRAFTING for
    investigate, APPROVED for execute. The refusals the existing tests expect stay refusals.
- **Startup check.**
  - `pg_proc.prosrc` is readable by every role.
  - `to_regprocedure` needs USAGE on schema `app`, which `mcp_read` holds; a missing function gives no row, which is a
    refusal.
  - The marker is a literal substring of 0009's stored source and absent from 0004 and 0007.
  - The lifespan closes the connection on failure (unit-tested).
- **Live tests.**
  - Each refusal in the R027 HTTP test has a single cause, with the same handle answering between causes:
    - the other-run job (same tenant);
    - +120 s on the clock under a 600 s lease;
    - the lapsed lease;
    - the takeover fence;
    - the revocation, where `revoke_handles` counts unrevoked handles at fence ≤ the given one whatever their expiry,
      so `== 2` is stable.
  - The clock is reset in `finally`.
  - The lying `server` column is refused because the job type wins. The unknown tool is an `is_error` result: the
    `Mcp-Param` pre-check skips an unlisted tool, `ToolError` becomes a result, and the client validates no error
    result.
  - The ACL query covers every function in `app`. No function is executable by PUBLIC, so the expected set is exact.
  - The four protocol POSTs match the in-process shapes measured in Task 1.
  - The subprocess:
    - free loopback port; readiness through `/health/ready` with a 60 s bound and a poll that detects a dead child;
    - environment-only secrets (`process_environment()` plus the port); nothing secret on the command line;
    - terminated in `finally`, then killed after 15 s, exactly as `Skeleton.stop` does (that pattern already proves
      no orphan in R105).
  - Purges run after the server task or child is settled. No test runs two connections against one lock, and none
    cancels a database unit.
  - Assertions on tokens and handles bind to booleans or index lists, apart from the synthetic one in M10.
- **Close-out.**
  - The handoff, matrix and backlog edits are correct, and the restored `## Walking-skeleton debt list (T08; …)`
    heading lands after "Plan J executed".
  - The next plan is right. The dependency-satisfied PLANNED tasks after T15 are T47 (file index 20) and T17
    (index 21), and T16 still waits on T17.
  - Errata 72, 73, 75, 77, 78, 79, 80 and 81 match the code. 74 and 76 need the wording in I1 and M7.


## Controller rulings

# Plan J review, round 1 — controller rulings

Input: `round1-static.md` (REVISE: 1 Blocking, 3 Important, 11 Minor; dry run equals the plan; the 0009 binding breaks
no production path; the guard runs before auth and echoes nothing; the worker's token still passes; downgrade exact).

- B1 — ACCEPTED: edit `tests/e2e/test_migrations_and_persistence.py::test_r006_populated_revision_1_database_upgrades_in_place`
  exactly as the critic proposes (assert the refusal on the finished job first, then reopen the job and assert the
  grant); add the module to Task 2's Files and to the Global Constraints sentence listing changed tests; correct the live
  counts.
- I1 — ACCEPTED: build the verifier through one factored constructor that both `production_app` and the unit test use;
  assert `validate_token_resource` is on and `token_type == "Bearer"` through the real wiring; reword erratum 74, the
  R026 note, the runbook, ARCHITECTURE and the `McpVerifier` docstring so the refusal is credited to McpVerifier's own
  `aud` check, with the SDK's resource check described as a second, currently redundant layer.
- I2 — ACCEPTED: run the log test's server with `log_level="debug"` and a non-vacuity check (a known uvicorn/SDK record
  was captured); state that uvicorn's TRACE level is not enabled anywhere (and that it would log headers); reword every
  "before any redaction" claim about the child process to what is checked (after `redaction.install()`).
- I3 — ACCEPTED: reword the mcp-write README edit, the handoff note and Review Focus 1, and update `execution.py`'s module
  docstring: a stored-outcome replay through the tool is no longer reachable once the run left APPROVED/EXECUTING (the
  run-state rule), which production never needed (the worker skips the call past EXECUTING); `test_mcp_write_live.py`'s
  direct calls test `execution.create_incident`, not the tool.
- Minors — ACCEPTED as the critic proposes; in particular M1 stage a recover handle at mcp-read (DoD 4 names it), M4
  guard the server start so a failure cannot escape as SystemExit past the purges. Decline only with a reason.

Apply in one pass; re-run the task-by-task apply with ruff format between tasks, the splice check and the dev counts;
append "Round 1 changes" / "Round 1 open points". Do not commit.

---

# Round 2

## Static review

## Plan J round 2: static adversarial critic

Plan: `docs/superpowers/plans/2026-10-15-first-slice-j-mcp-read-verifier-handles.md` (3,961 lines, branch `plan-j`,
172def3).

**Verdict: ACCEPT (with Minors).** 0 Blocking, 0 Important, 7 Minor.

All fifteen round-1 findings are fixed. I re-applied the plan to a fresh copy of HEAD, task by task:
- every splice applies;
- every dev count and red step matches the plan exactly.

The round-1 changes break nothing I could find. The Minors are:
- three robustness gaps in the reworked live helpers: the log test's set-up path, pytest's captured-log report on a
  failure, and exceptions after a successful start;
- one link the mutation probes show is unpinned (`production_app` → `read_verifier`);
- one inaccurate docstring sentence;
- a handful of wording leftovers.

### How this was checked

**Applying the plan.** I took a `git archive HEAD` copy (`critic2/tree`), made it a git repo with its base commit
`d7fa1d8`, and ran `uv sync --frozen --offline`. I then applied Tasks 1-5 in order with round 1's Edit/Create parser
(`critic2/apply.py`, identical to `tools/apply.py`). Each unit `Run:` line ran where it stands, and Task 5's scripts
ran with `BASE` set. After each task I ran:
- `ruff format .`
- `ruff check .`
- `scripts/check.py` (mypy strict and pytest)
- `verify_handoff`

Every quoted old text matched exactly once.

I also checked the splice format. Every edit label in all five tasks is on one line ending `replace:`: 24, 15, 2, 0
and 16 labels, which equals the edits applied, so none was skipped silently.

| After task | ruff format | ruff check | mypy strict | pytest (dev) | verify_handoff |
|---|---|---|---|---|---|
| 1 | no change (261) | clean | clean, 57 | **1056 / 154** | 0 |
| 2 | no change (266) | clean | clean, 57 | **1070 / 157** | 0 |
| 3 | no change (267) | clean | clean, 57 | **1070 / 162** | 0 |
| 4 | no change (268) | clean | clean, 57 | **1070 / 164** | 0 |
| 5 | no change (268) | clean | clean, 57 | **1070 / 164** | 0 |

These equal the plan's 1056/154, 1070/157, 1070/162, 1070/164 and 1070/164. The live arithmetic follows: 1189, 1206,
1211 and 1213, which are the dev counts plus 133, 136, 141 and 143. It stays arithmetic, because no live step was run.

**Red and intermediate steps.** I checked out the base, or the Task 1 commit for Task 2, and stopped the apply at each
step's `Run:` line (`critic1/partial.py`, `-rfE --tb=line`). Each step printed the stated count, with the stated
reason where I captured it:

| Step | Printed | Reason |
|---|---|---|
| T1 S3 | `1 error` | `ModuleNotFoundError ops_core.mcp_protocol` |
| T1 S4 | `8 passed` | |
| T1 S5 | `9 failed` | `AttributeError: module 'ops_mcp_read.server' has no attribute 'read_verifier'` in the tests that build the verifier |
| T1 S6 | `9 passed` | |
| T1 S7 | `3 failed, 1 passed` | the mcp-write case is `RuntimeError: Task group is not initialized` |
| T1 S8 | `21 passed` | |
| T1 S9 | `2 failed, 1 passed` | `assert ['ops-worker'] == ['ops-worker-renamed']` |
| T1 S10 | `47 passed` | |
| T2 S1 | `12 failed, 12 passed` | `TypeError: allowed_tool() takes 2 positional arguments but 3 were given` |
| T2 S2 | `24 passed` | |
| T2 S3 | `2 errors` | `ImportError … HANDLE_BINDING`, and the transitions module's existence assert |
| T2 S4 | ISC004 `All checks passed!`, then `51 passed` | |

The step order is still red before green after the move. Step 5's tests drive everything Step 6 adds. Each Step 6
behaviour is pinned by a test of its own (mutation probes below), although the single red reason, the missing
`read_verifier`, masks the three individual reasons.

**Task 5.**
- `git grep "TODO(T15"` and `git grep "(T15" -- tests/plan_c` print nothing.
- `build_schemas` prints `schemas/: 25 schema documents (19 contracts, 6 tool inputs); 89 examples (35 valid, 54
  invalid); index.json version 1.3.3` and changes no file.
- The handoff diff touches three files, and the matrix rows changed are exactly R025, R026, R027, R031, R085 and R131.
- Counted in UTF-8, the only added lines over 120 characters are in files that already carry long lines: the JSON
  notes, `README.md:5`, the backlog line and the SESSION_STATE repository and next-step lines. Every `.py` file passes
  the plan's counting command.

**Mutation probes** (on the Task 5 tree, running `tests/plan_j` and `tests/plan_d`, 109 tests):

| Mutation | Result |
|---|---|
| `token_type="Bearer"` commented out of `read_verifier` | `test_only_an_access_token_passes` fails |
| `validate_token_resource=False` | `test_the_sdk_resource_check_is_on` fails |
| `McpVerifier`'s `if self._resource not in principal.audiences: return None` removed | `test_the_ladder_and_the_resource_check_behind_the_guard` and `test_the_resource_is_stamped_only_from_the_audience` fail |
| `production_app` builds an inline `TokenVerifier` without `token_type` instead of calling `read_verifier` | **109 passed** (Minor m4) |

**Log-capture experiment** (`critic2/exp/test_logexp.py`, run inside the tree and then removed). The question was
whether the plan's log-test set-up really captures uvicorn, the SDK and the client. I served the real `build_app` and
`build_server` over a real socket with uvicorn, with `log_level="debug"` and `log_config=None`. The database was a
stub connection that resolves a handle, or refuses it in the second call. The set-up was exactly the plan's:
- `caplog.set_level(DEBUG)`;
- the four `uvicorn*` loggers set to propagate, then restored;
- one answered official-client call, one refused call, and one raw POST with a `2025-11-25` header, each carrying a
  canary `X-Ops-Invocation`.

I ran it twice: once after `logging.config.dictConfig(uvicorn.config.LOGGING_CONFIG)`, which is what
`test_mcp_write_live`'s default `uvicorn.Config` leaves behind, and once without. Both runs:
- captured `uvicorn.access`, `uvicorn.error`, `mcp.client.streamable_http`, `mcp.server.lowlevel.server`,
  `mcp.server.streamable_http_manager`, `httpx2`, `httpcore2.connection` and `httpcore2.http11` (89 and 107 records);
- passed `{"uvicorn", "mcp", "httpx2"} <= names`;
- found the canary in none of the records, and `"Bearer good"` in none either.

So the non-vacuity check is real, and the plan's "the dry run measured that the same set-up captures …" holds.

I also confirmed:
- uvicorn 0.54's `Server.startup` calls `sys.exit(STARTUP_FAILURE)` when the lifespan fails, so `guarded()` is needed
  and catches the right thing;
- uvicorn's message logger is enabled only at a level ≤ TRACE (5), so `"debug"` does not log headers;
- psycopg's DEBUG lines carry host and port, and the `PGconn` summary shows host, port, user and database, with no
  password;
- no SDK, uvicorn, Starlette or httpx2/httpcore2 log call formats request headers;
- pytest does not print the arguments of an awaited call inside a failed `assert` (probe: `assert await refused(None,
  "Q", (handle,)) == "OC008"` prints only `'XX000' == 'OC008'`), so `refused(mcp_read, RESOLVE, (handle,))` and
  `(await resolve(mcp_read, handle)).job_id` do not leak a handle; no `--showlocals` is configured.

**Not run.** No live test was run and no database was touched. Where PostgreSQL, Keycloak and the live behaviour of
the e2e fixtures mattered, I judged them statically against the code.

---

### Round-1 findings

| # | Status | Evidence |
|---|---|---|
| B1 | **FIXED** | Task 2 Step 5 Edit 4 applies at `test_migrations_and_persistence.py:409-410`. The module is in Task 2's Files, the Global Constraints sentence and the Step 7 `git add`. The live counts are now 1206, 1211 and 1213. Traced: `lookup_action` runs on an autocommit `mcp_exec` connection (`persistence.connect`). It calls `_resolve_handle(…, 'write')`, and 0009's bound read of the done job yields no type, which raises `OC008`. `translate` turns that into `HandleRejected`, and no transaction is left failed, so the second call is clean. `jobs` has no trigger and no constraint on `done_at` (0001:108-119, 0002, 0008's purge policy is FOR DELETE TO sweeper only), so the reopening `UPDATE` succeeds. `finally` migrates (a no-op) and `purge_run` removes the job and handle. No worker or sweeper runs in that module, and later modules start their own workers only after the purge. |
| I1 | **FIXED** | `read_verifier(kc, urls)` is the one constructor: `production_app` calls it, and `production_like()` calls it with a stub `Keycloak` and `Urls`. `test_the_sdk_resource_check_is_on` pins `validate_token_resource is True` on `build_server`, which `production_app` uses. The worker's two-audience token passes through it (`aud=[write, read, account]` in `test_the_resource_is_stamped_only_from_the_audience`), and the persona stand-in (`aud ops-api`, `azp ops-dev-direct`) and `azp ops-web` are refused through it. Erratum 74, the R026 note, the handoff note, the runbook, ARCHITECTURE, the `McpVerifier` docstring and ruling 2 are reworded. Residues: m4 (the `production_app` → `read_verifier` link is not pinned) and m6/m7 (wording). |
| I2 | **FIXED** | `serving(log_level=…)`; the test runs at `"debug"`, flips propagation and restores levels and propagation in `finally`. The non-vacuity set `{"uvicorn","mcp","httpx2"}` is real (experiment above). TRACE is excluded and documented. The child's log is described as redacted and weaker in Task 4's docstring, the R027 note, Review Focus 4 and the runbook. Residues: m1 (set-up path before the `try`) and m2 (pytest's failure report). |
| I3 | **FIXED** | The README edit, the R105 comment, the handoff note, Review Focus 1, ruling (a) and the new `execution.py` module docstring (Task 2 Step 5 Edit 5) say that through the tool a replay is answered only while the run is APPROVED or EXECUTING, and that `test_mcp_write_live.py` proves the execution layer. Residue: m5 (one sentence of the new docstring). |
| M1 | **FIXED** | A recover job is inserted in the shape `mark_unknown` uses (0007:360: `'recover'`, the run's tenant, `'<uuid>:timeout'`). The `(tenant_id, run_id)` FK holds because `approved_run` builds on ALPHA. The handle is minted under the run's live lease: `run_lease` and `invocation_context` have no RLS, the same path `read_handle` takes without `set_tenant`, and `mint_handle` checks the lease is live. No grant or attempt is needed, because `_resolve_handle(…, 'read')` refuses on `v_ctx.server <> p_server` and on the job type's server `'write'` before it reads the grant. `purge_run` removes the job and handle by `run_id`. The ARCHITECTURE R131 row was not updated (m6). |
| M2 | **FIXED** | R026 posts a raw `tools/call` carrying a valid read handle with each foreign token (401 `invalid_token`), then the same call with the worker's token, whose envelope is `ok`. The handle is minted after the child is ready, well inside its 60 s TTL. Task 1's in-process `answered` post uses the same body and header shape (measured: 200, `INVALID_HANDLE` for the missing handle). |
| M3 | **FIXED** | The protocol test takes `migrated`, and R026 takes `app_conn`, which depends on `migrated` (`conftest.py:80`). |
| M4 | **FIXED** | `guarded()` turns uvicorn's `SystemExit` (confirmed at `uvicorn/server.py`, `startup`) into a `RuntimeError`, which the polling loop raises through `task.result()`. Any other start exception (`config.load`, the bind is itself `sys.exit`) also surfaces there, and `KeyboardInterrupt` is not caught. The purges in the callers' `finally` blocks run. Residue: m3 (an exception after the start is no longer surfaced). |
| M5 | **FIXED** | Global Constraints and runbook step 4: "every refusal of a presented handle", plus the "missing invocation handle" sentence. |
| M6 | **FIXED** | STATUS attributes the finished-job refusal to the definer. |
| M7 | **FIXED** | Erratum 76 (short and full) says "at the start of every MCP call (`persistence.resolve_invocation`)" and names the definers' own resolutions as exempt. |
| M8 | **FIXED** | The `test_allowlist.py` docstring now matches its test. |
| M9 | **FIXED** | `test_the_newest_body_of_resolve_handle_carries_the_startup_marker` (passes) and the `HANDLE_BINDING` comment. It relies on the same conventions as `test_transitions_table.py` (`FUNCTIONS` 4-tuples, and `REVISIONS` kept current, which no test ties to the files on disk). The live round trip's `MARKER in head["body"]` and mcp-read's own startup check back it up. |
| M10 | **FIXED** | `passed` and `leaked` are bound before the asserts. |
| M11 | **FIXED** | The runbook query says it needs the owner's migration. `test_the_model_request_has_no_field_for_a_handle` pins `DraftRequest`'s four fields (it passes at red, as Step 9 says), and the R027 note cites it. |

---

### Blocking

None.

### Important

None.

### Minor

**m1 — The log test flips uvicorn's propagation before its `try`, so a set-up failure leaves the change in place for the
rest of the session.**

Where: Task 3, `test_r027_no_log_record_carries_the_handle` (plan 2764-2770), and Round 1 open points ("both are put
back exactly").

Evidence: `saved = …` and `logging.getLogger(name).propagate = True` run first. Then three awaited calls run outside
the `try`, each of which can fail on a Keycloak or database hiccup:
- `role_conn(Role.WORKER)`;
- `new_run(...)`;
- `worker_token(secret)`.

The `finally` that restores the loggers is never entered in that case.

Why it matters: from then on, every later test's uvicorn records propagate to the root logger. With an earlier uvicorn
dictConfig in place, they are also emitted twice. The plan's own open point claims the change cannot leak.

Fix: open the restoring `try` immediately after `saved` is taken, around the propagation flip and the set-up. Keep
`purge_run` in its own `finally`, guarded on `run` having been created. Alternatively, move the flip to just before
`async with serving(…)`, inside the existing `try`.

**m2 — If the log test fails, pytest's "Captured log call" section prints every DEBUG record, including the one that
carries the handle.**

Where: the same test; Global Constraints, Secrets ("a failure never prints the value"); Review Focus 4 and Known risks
(the advice to "report, never raise the capture level").

Evidence: `caplog.set_level(logging.DEBUG)` lowers the root level. Pytest's session-wide report handler sits on root
during the call phase at level 0 and is not cleared by `caplog.clear()`, and the default `--show-capture=all` prints it
on failure. The test carefully asserts on indexes only (`carrying == []`). But the very failure it guards against, a
record holding the handle, is then printed in the report, and so is the worker's live bearer token if a library ever
logged the `Authorization` header. `check.py` does not persist output, so this reaches the terminal only.

Why it matters: the risk is low. The handle is a test handle on `ops_test`, revoked within the test, and the token
expires in minutes. But it contradicts the stated rule in exactly the failure mode the test exists for.

Fix, either of:
- (a) state it in the test docstring and the Known risks bullet: "a failure prints the offending record; treat that
  output as sensitive, rotate nothing, the handle is already revoked";
- (b) capture with a dedicated list handler on the known logger roots (`uvicorn`, `mcp`, `httpx2`, `httpcore2`,
  `ops_core`, `ops_mcp_read`, `psycopg`), with `propagate=False` for the exchange, so nothing reaches root, and assert
  on that list. This is weaker for unknown logger names.

(a) is enough.

**m3 — `serving()` no longer surfaces an exception from the server task after a successful start.**

Where: Task 3, `serving()` `finally: await asyncio.wait({task})` (plan 2556-2558).

Evidence: the round-0 `await task` re-raised whatever the task ended with. `asyncio.wait` only waits for it. A
failure in `serve()` after `started` is never retrieved, for example an exception out of `main_loop` or `shutdown`.
Asyncio logs "Task exception was never retrieved" only when the task is garbage-collected. The start failure is still
raised, through `task.result()` in the polling loop.

Why it matters: the brief asks that the guarded start "not swallow real failures". The start path is fine; the stop
path now swallows.

Fix: after the wait, re-raise only what is new. For example:

```python
if server.started and not task.cancelled() and task.exception() is not None:
    raise task.exception()
```

This only applies when the body did not already raise. Otherwise, say in the comment that a post-start failure is
logged by uvicorn only.

**m4 — Nothing pins that `production_app` builds its verifier through `read_verifier`.**

Where: Task 1 Step 6 Edit 7. The `read_verifier` docstring says the tests "pin the wiring that runs", and Self-review
item 3 says the same.

Evidence: mutation probe. Replacing `verifier=read_verifier(kc, urls)` in `production_app` with an inline
`TokenVerifier(...)` that lacks `token_type` passes all 109 `tests/plan_j` and `tests/plan_d` tests. It would also pass
the live gate, because every live token is `typ` Bearer. The settings `read_verifier` holds are pinned (see the probes
above); its use is pinned only by review.

Why it matters: this is the I1 lesson, "tests exercise what their docstrings claim". The residual risk is a refactor
that stops calling the shared constructor, which is unlikely but silent.

Fix: one unit test in `test_verifier_t15.py`:
1. monkeypatch `settings.keycloak`, `settings.urls` and `settings.fixtures_dir` with the module's stubs;
2. wrap `server.read_verifier` with a recorder;
3. call `server.production_app()`;
4. assert the recorder ran once, with the stubs.

Or soften the docstring to "the unit tests build theirs here".

**m5 — The new `execution.py` docstring says "a second call inside the same open job still reaches" the stored branch,
which contradicts the sentence before it.**

Where: Task 2 Step 5 Edit 5 (plan 2200-2202).

Evidence:
- The stored branch needs the attempt RESOLVED, which `record_outcome` writes in the same transition that moves the
  run out of EXECUTING (`states.py`, as round 1 traced).
- A second tool call made after that, open job or not, is refused by `resolve_invocation`'s run-state rule. That is
  the previous sentence's own point.
- Only an overlapping call reaches the branch through the tool: one whose `resolve_invocation` committed before the
  other call's `record_outcome`, so that its `grant_execution` re-resolution, which applies no Python allowlist, then
  finds the grant.

Fix: "A direct caller (tests/e2e/test_mcp_write_live.py), or an overlapping call that resolved its handle before the
outcome was recorded, still reaches it."

**m6 — Wording leftovers from I1 and M1 in parts of the plan that execution copies or a reviewer reads.**

- Self-review item 1 (plan 3813-3814) still says T15's verifier is "now also the `typ` claim and the SDK's resource
  check (Task 1)". It should be "and `McpVerifier`'s audience check (the SDK's resource check on as an inert second
  layer)".
- The ARCHITECTURE R131 row (plan 3638) still says "an execute handle at mcp-read is refused". The R131 note, STATUS,
  ruling 10 and the self-review now say "a recover and an execute handle".
- Self-review's R027 bullet (plan 3840) cites "FS §3.11" for "the model never receives a handle". The new
  `test_the_model_request_has_no_field_for_a_handle` is the evidence now.
- Cosmetic wraps: "Review notes: 1 (error only" breaks mid-sentence at plan 3827, and
  "`tests.plan_e.test_transitions_table. REVISIONS`" carries a stray space at plan 3862.

**m7 — The R026 note gives McpVerifier's check the refusals that `read_verifier`'s own audience check makes first.**

Where: the R026 matrix note ("a token whose audiences lack the resource is 401 through McpVerifier's audience check"),
erratum 74 (short and full), and the handoff note.

Evidence: `read_verifier` builds a `TokenVerifier` with `audience=urls.mcp_read_resource`. PyJWT therefore refuses
every live foreign token (`aud ops-api`, `incident-sim`, `asset-sim`) as `WrongAudience` before `McpVerifier`'s own
check runs. `McpVerifier`'s check only decides in-process, with `KeyedVerifier`, which checks no audience (the
`elsewhere` case), or under a misconfigured verifier (the `wrong` case). The runbook already orders it correctly
("`McpVerifier` refuses again").

Fix: in the R026 note, write "401 through `read_verifier`'s audience check, with `McpVerifier`'s own check behind it
(unit-tested) and the SDK's resource check a third, inert layer". Erratum 74 is accurate as a property statement and
can stay.

---

### Checked and found sound

- **R006 edit.** It leaves no state that breaks later assertions or the purge: see B1 above.
- **Recover handle at mcp-read.** It is staged without a grant or attempt, and nothing at mcp-read reads them before
  the refusal: see M1 above.
- **The guarded start.** `SystemExit` becomes a `RuntimeError` that the polling loop raises, so no failed start hangs
  or escapes the loop. `asyncio.wait` never cancels.
- **Moved Task 1 steps.** Red comes before green at every step. Step 7's red is unaffected by `validate_token_resource`
  and the audience check moving to Step 6: `test_the_ladder…` still fails first on the `2025-11-25` legacy header,
  200 ≠ 400.
- **No raw handle or token in logs, operands, evidence or command lines.**
  - Every new evidence line holds counts, names or states only.
  - The child's command line is `[sys.executable, "-m", "ops_mcp_read"]`; its environment is `process_environment()`
    plus the port, which is how the skeleton starts its children.
  - Every new handle or token check binds to a boolean or a list of indexes. pytest does not print awaited-call
    arguments.
  - The only residual path is pytest's captured-log report (m2).
- **Every handle refusal is indistinguishable.** The run-state refusal raises the same `HandleRejected("invocation
  handle rejected")`, and `translate` maps every `OC008` to the same message. The recover and lying-column cases are
  asserted against the full `REFUSAL` dict, with `data` None and no `action_id`. The "missing invocation handle" variant
  is documented as the one exception.
- **The downgrade is exact.** Revision 0009 is unchanged since round 1. `test_the_downgrade_restores_0007s_body` and
  `test_only_the_job_read_changes` pass, and round 1's trace (0008 never touched `_resolve_handle`) stands.
- **The handoff's "Exact next step" and "Next task".** I recomputed from `handoff/tasks.json` with T15 set to DONE. The
  dependency-satisfied tasks that are not DONE are the owner tasks T03 and T44 (DONE_PENDING_OWNER), then T47 (index
  20, depends on T15 and T10) and T17 (index 21). "Plan K for T47 (mcp-write …; T17 is also unblocked)" is correct.
- **Counts, red steps and splice format.** All as measured above.


## Controller rulings

# Plan J review, round 2 — controller rulings

Input: round2-static.md (ACCEPT with Minors: 0 Blocking, 0 Important, 7 Minor; all 15 round-1 findings fixed; probes
show the verifier, propagation and audience fixes bite). The review closes; the seven minors were folded into the plan
in one pass (44e16f1) without a further round.

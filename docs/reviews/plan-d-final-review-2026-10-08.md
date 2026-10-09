# Plan D final whole-branch review (2026-10-08)

Branch `plan-d`, range 8136ee6..d7b6359 (Plan D task T08: the walking skeleton across api, worker, mcp-read, mcp-write
and incident-sim, plus the slice-end handoff docs), reviewed after each of the nine tasks passed its own gate.
**Outcome:** 0 Critical, 1 Important, 9 Minor, 9 behaviours declined to judge. The Important finding was a stranded approval: a worker that could not reach mcp-write marked the execute job done, so the approved run kept its conversation slot with no task to recover it; the fix re-queues the job with a 30-second backoff (idempotent at mcp-write and the destination) and declares the missing retry bound as debt. Eight of the nine minors were fixed in the same wave (a token fetch outside its error boundary, a missing T09 marker, 503 bodies for database failures, production asserts, a process fixture that could pass on stale processes, stale ranges and counts in the handoff documents); the ninth (the end-to-end run's rows stay as evidence) is recorded. A scoped re-review on the same model confirmed every finding addressed, the reviewer's own probes passing (the stranded approval now completes on the next poll after mcp-write returns), and the gates: 458 passed / 45 skipped, the live suite 24 passed, the handoff checker exit 0.

The sections below are, in order, the reviewer's text (with its appended re-review), the controller's rulings as
recorded in the execution ledger, and the implementer's fix-wave report. Machine-local paths are replaced by
placeholders; nothing else is edited.

---

# Part 1 — Reviewer's report and re-review (unedited)

# Plan D final whole-branch review (fee821f..e875d44, 21 commits)

Reviewer: final whole-branch review, read-only (no commit, no index or HEAD change; `git checkout -- reports/` after the
live run; every probe row purged; every process stopped). I reviewed in four passes, as the brief asked:
(1) `core/src/ops_core/{settings,tokens,persistence}.py`, `migrations/`, `scripts/skeleton.py`; (2) the five services'
`src/`; (3) `tests/plan_d/`, `tests/e2e/`, `tests/plan_b/` changes; (4) handoff docs, runbooks, READMEs, `compose.yaml`,
the realm and the `pyproject.toml` files. I skimmed the `uv.lock` hunk only for the `mcp`/`httpx2` entries the ledger
had already checked.

### Verification performed

| # | Command / probe | Tail |
|---|---|---|
| 1 | `PYTHONUTF8=1 uv run python scripts/check.py 2>&1 \| tail -4` | `457 passed, 44 skipped in 26.46s` / `CHECK: GREEN` |
| 2 | `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts; echo exit=$?` | 26 schemas / 34 accepted / 53 negative PASS; 19 inherited files match; 26 reference files byte-identical; 161 checksums; `exit=0` |
| 3 | commit messages fee821f..e875d44 grepped for attribution trailers | prints nothing (grep exit 1) |
| 4 | the files this branch added (outside `reference/`, `docs/superpowers`, the spec-mandated entry file) and the diff's `+` lines grepped for vendor names | nothing |
| 5 | `skeleton.py status` → `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e tests/plan_b/live -q -p no:cacheprovider` → `status` | all five `down` before; `23 passed in 59.88s` (14 e2e + 9 Plan B); all five `down` after; `netstat` shows none of 8000/8070/8081/8082/8090/18081/18090 listening |
| 6 | Fresh evidence: `pytest tests/plan_b/test_evidence.py tests/plan_d/test_skeleton_evidence.py` on the regenerated `reports/` | `3 passed`; then `git checkout -- reports/`, `git status --short` clean |
| 7 | Every `persistence.transition` / `create_run` call (src, dst, performer, reason) run through `require_transition` (scratch `rules.py`) | all 15 call shapes OK, incl. the replay moves OUTCOME_UNKNOWN → SUCCEEDED/ESCALATED and FAILED by `record_outcome` with every FAILED_NO_COMMIT reason |
| 8 | Every event payload the branch writes run through `event_rules_ok` | all 15 types OK (`action.failed` with a real `aborted_no_commit` reason and tombstone) |
| 9 | `git grep "UPDATE app.runs"` | the only `SET state` is `persistence.py:109`; `SET active_proposal_id` in `worker/handlers.py:175` (and a test) |
| 10 | Hygiene on every added/modified `.py`: `type: ignore`; character length > 120 (Python `len`, not awk bytes); `assert` in production code; blind `except Exception` | no `type: ignore`; no line > 120 characters; 6 production asserts (see M4); 3 `except Exception`, each logs with `log.exception` or is followed by a `_fail` |
| 11 | `.env`, `runtime/`, secrets in git | `.env`, `.env.*`, `runtime/` ignored; nothing tracked |

Cross-service probes (scratch `probes.py`; host processes started per probe; tokens from the real realm; every run purged
with `tests/e2e/conftest.purge_run`, the probe's three incident keys deleted, the two temporary `lee` membership rows
deleted; final line `purged runs=5 incident keys=3`; `status` all down afterwards):

| Probe | Result |
|---|---|
| (a) admit with the worker DOWN, then start it | `admit=202`, `QUEUED` after 3 s, `AWAITING_APPROVAL` after the worker started. Jobs are durable. |
| (b) mcp-write DOWN at execute | approve 200 → run stays `APPROVED`, execute job `claimed` and `done`; a new admission into that conversation → `409 SLOT_OCCUPIED`; mcp-write started → still `APPROVED` (nothing retries); a hand-inserted execute job with a new dedup key → `SUCCEEDED`. Matches the ledger's ruling, but see I1. |
| (c) incident-sim DOWN at dispatch | `OUTCOME_UNKNOWN`, events tail `action.dispatched, action.uncertain`; after incident-sim is up, a replay through a fresh WRITE handle → `ok/SUCCEEDED`, run `SUCCEEDED`, `action.confirmed` last, exactly one incident row for the action. |
| (d) two requesters (alex, and lee given a temporary alpha requester row) admit concurrently into one conversation | `[(202, None), (409, 'SLOT_OCCUPIED')]` |
| (e) a reviewer whose reviewer membership is `active = false` (lee: active reader plus an inserted inactive reviewer row) | `403 FORBIDDEN`; run stays `AWAITING_APPROVAL` |
| (f) approve, then kill the API at once | DB reaches `SUCCEEDED` with the API down; after an API restart the snapshot says `SUCCEEDED` |
| (g) wrong tokens and an expired handle | persona token at mcp-read: refused (transport 401; the worker token with the same handle: `ok`); mcp-read's token at mcp-write: refused, raw POST `401`; worker token at incident-sim `POST /internal/incidents`: `401`; a handle minted with a 1 s TTL replayed after 2 s: `error / invocation handle expired or revoked`; `action_id` in none of these bodies |
| (h) committed and regenerated evidence | `test_evidence.py` passes on both; the file holds run/proposal/action/incident ids, a hash, event types; no token, no secret |

### Strengths

- **The authority chain is real, and it held under probes the task reviews could not run.** A decision needs an active
  reviewer membership in the tenant, independence from the requester and `authored_by`, and the exact revision and hash.
  The grant is UNIQUE per run and its action id is random inside the gate. SENT commits in its own unit before any I/O.
  Only `record_outcome` writes `source=destination`. Probes (c) and (f) show the outcome comes from the destination and
  that the API is not on the write path.
- **One door for state.** `persistence.transition` is the only `UPDATE … SET state`. All 15 call shapes pass
  `require_transition` with the performer the spec names, including the replay moves out of OUTCOME_UNKNOWN. All 15
  event payloads pass `event_rules_ok`, which `append_event` calls before it builds the `Event`.
- **The replay rule is correct end to end.** One grant per run, the same action id, the same receipt and one incident,
  through a fresh handle, in the e2e test and in probe (c) after a real outage.
- **Token verification is done once and done well.** RS256 is pinned, `use=sig` keys only, `iss`/`aud`/`exp`/`sub` are
  required and `azp` is checked against an allowlist. The JWKS refresh is single-flight with a cooldown, and
  `Principal.claims` is read-only and left out of the repr. No refusal reveals the reason in a way that leaks an id
  (probe g).
- **Fewer moving parts where it matters.** One autocommit connection with `Session.unit()` gives real BEGIN/COMMIT. The
  worker's readiness has its own connection and turns 503 when the poll loop dies. Uvicorn runs on a selector loop.
  These are measured fixes, and their comments say why.
- **Handoff vocabulary is disciplined.** R105 is `RECORDED_LOCALLY_LIVE` / `IMPLEMENTED_LOCALLY_VERIFIED`, and the
  matrix note defines the new term. The debt list has its eleven lines with owners, and it was committed in 8136ee6
  before any service code.
- **Hygiene is clean.** check.py is GREEN with mypy strict, there is no `type: ignore`, no line exceeds 120 characters
  and no commit carries an attribution trailer.

### Issues

#### Critical (Must Fix)

None.

#### Important (Should Fix)

**I1. An execute call that never reaches mcp-write strands the approved run for good, and no debt line declares it**
(`worker/src/ops_worker/handlers.py:219-223`, the `except McpCallFailed: … return`, then `handle()` sets `done_at`).

- *What is wrong.* If the worker cannot reach mcp-write (process down, restart, connection refused, a 401 during
  rotation), it logs a warning and returns, and the job is marked done. The run stays `APPROVED` and keeps its
  conversation slot. Nothing ever retries it:
  - T13's reclaim, as the debt list describes it, looks for claimed, unfinished jobs, and this job is finished.
  - T22's reconciliation looks for SENT attempts, and this run has no grant.
  - `insert_job` cannot simply be re-run, because the execute dedup key (`proposal_id`) already exists.
- *Effect, measured by probe (b).* After mcp-write came back, the run was still `APPROVED`. A new request in that
  conversation got `409 SLOT_OCCUPIED`. Only a hand-written `INSERT INTO app.jobs` with a new dedup key recovered it.
- *Why it matters.* A reasonable person who approved an incident expects either the incident or a failure they can see.
  A transient outage of one local process gives neither, and blocks the conversation. The declared debt ("no reclaim of
  a job whose handler crashed") does not cover it, because this handler did not crash.
- *Handoff.* PROJECT_HISTORY §19 (`docs/PROJECT_HISTORY.md:135`) says "a transport failure or a drafting error failed
  the run instead of stranding it". That is true of `investigate` only.
- *Fix (either).*
  - Re-queue on `McpCallFailed`: `UPDATE app.jobs SET claimed_at = NULL, claimed_by = NULL, available_at = now() +
    interval '5 seconds' WHERE id = …`, and do not finish the job. This is safe because `create_incident` is idempotent
    per run: an existing grant is returned, and a RESOLVED attempt returns the stored outcome.
  - Or let the handler raise, so the declared T13 reclaim owns it.

  In both cases, add a debt line (owner T13/T22), a runbook recovery note, and correct the §19 sentence.

#### Minor (Nice to Have)

- **M1. A token-fetch failure in the worker escapes as a handler crash** (`worker/src/ops_worker/mcp.py:60`).
  - *Problem.* `await self._tokens.token()` is evaluated outside the `try`. When Keycloak is down or the secret was
    rotated, `httpx2.HTTPStatusError`/`ConnectError` (or `TokenRejected`, or a `ValueError` from `float(expires_in)`)
    is not turned into `McpCallFailed`. `investigate` leaves the run in `RETRIEVING`, with `tool.started` written, the
    slot held and the job claimed.
  - *Why it matters.* This contradicts the module's own rule ("every failure to obtain a tool result is
    McpCallFailed"), and it defeats the `failure_leaf` work, whose stated purpose is to keep the run from being
    stranded. The declared T13 crash debt covers the consequence, not the cause.
  - *Fix.* Move the token fetch inside the `try`, and add `TokenRejected` and `httpx2.HTTPError` to the converted set.
- **M2. The worker's freeze is a raw-SQL seam with no `TODO(T09)`**
  (`worker/src/ops_worker/handlers.py:153-200`: INSERT `drafts`, INSERT `proposals`, `UPDATE app.runs SET
  active_proposal_id`, plus the `append_event` calls).
  - *Problem.* Under AM-20.2 the worker may not insert `proposals`, may not update `runs.active_proposal_id`, and may
    not insert `events` outside `append_event`. All of these become `freeze_proposal`/`append_event`. The only marker
    is a remark about `draft_sha256`.
  - *Why it matters.* SESSION_STATE's Next-task line points Plan E at "`TODO(T09)` in `ops_core.persistence`". The
    api, mcp-read and mcp-write seams are marked, but the freeze is not. T09's first real-grant run will find it as
    `permission denied`, so it costs discovery time rather than causing a silent bug.
  - *Fix.* Add `TODO(T09): freeze_proposal definer function`, or move the freeze into `persistence.freeze_proposal()`
    so T09 replaces one body. Widen the Next-task line to "every `TODO(T09)`".
- **M3. The API answers a database failure with a plain-text 500, not a SafeError** (`api/src/ops_api/app.py`, no
  `psycopg.Error` handler; `store.py` lets `OperationalError` through).
  - *Why it matters.* Ruling 20 lists 503 `UNAVAILABLE`. incident-sim maps `psycopg.Error` to 503, and the API should
    match it. In addition, the single connection is never reopened, so after a PostgreSQL restart every API, mcp-read,
    mcp-write and incident-sim request fails until a manual restart. Readiness correctly turns 503, but nothing acts
    on it. The worker exits non-zero; the servers stay up and broken.
  - *Fix.* Add an exception handler `psycopg.Error → safe(503, UNAVAILABLE, …)`. Optionally add reconnect-on-broken
    in `Session`, or a debt line naming T13's pool as the owner of reconnects.
- **M4. Production `assert`s remain** (`core/src/ops_core/persistence.py:185`; `mcp-write/src/ops_mcp_write/execution.py:136,
  147,195,270`; `incident-sim/src/ops_incident_sim/app.py:78`). Task 4's fix replaced an assert with `RuntimeError`
  "because asserts are stripped under -O", but the same pattern stayed in mcp-write and core. Under `-O`,
  `execution.py:270` would hand `json.dumps(None)` to `model_validate_json` and raise a `ValidationError` from the
  tool. Fix: apply the Task 4 pattern consistently, or record that `-O` is unsupported.
- **M5. The e2e harness can test a stale process set** (`scripts/skeleton.py:161`).
  - *Problem.* `Skeleton.start()`, which the R105 fixture uses, does not refuse when the ports already answer, as `up()`
    does. With a manual `up` set running, the first readiness poll hits the old processes and returns 200 before the
    new children fail to bind. The R105 test then runs against the old code and passes.
  - *Fix.* Run the `up()` pre-check (any `healthy()`, or `pids.json` present) inside `start()`.
- **M6. The R105 test leaves its run behind** (`tests/e2e/test_r105_walking_skeleton.py`).
  - *Problem.* Every other live test purges its rows. R105 leaves its run, conversation, minted replay handle and
    incident in the seeded alpha tenant. The dev database grows one run per live run (`INC-000088` after mine).
  - *Why it matters.* No assertion breaks today. T09's grant change will make these rows impossible to clean later
    under ruling 27.
  - *Fix.* `purge_run` in a `finally` (the evidence file is the record).
- **M7. The handoff range is stale.** `SESSION_STATE.md:5,153`, `STATUS.md:108`, `handoff/tasks.json:474` and
  `handoff/BUILD_BACKLOG.md:43` say `8136ee6..89eb1e6`. The branch ends at `e875d44`, and `e875d44` changed code
  (the `up` refusal and the R105 assert binding). Fix: say `8136ee6..e875d44`.
- **M8. PROJECT_HISTORY §19's counts are partial** (`docs/PROJECT_HISTORY.md:133`). "Across all of them the task
  reviews found … eight Important findings" omits Task 9's three Important findings. One of them, a token in an assert
  operand, is the most security-relevant finding of the execution. Fix: "eight in the implementation tasks, three more
  in Task 9's harness and handoff".
- **M9. Stale or slightly strong comments.**
  - `tests/e2e/conftest.py:2` says "Task 9 adds the `skeleton` fixture" to conftest, but the fixture lives in the R105
    module.
  - `README.md:5` says "hardening in progress" while T09 has not started. Prefer "hardening (T09+) next".

### Declined to judge

- Team-shared conversations: any requester in the tenant can admit into a conversation another member created (probe d
  relies on this). BUILD_SPEC:161 makes team sharing intentional in v1, so it is not a finding.
- `classify()` maps a 200 whose `action_id`/hash are not ours to CONFLICT → ESCALATED rather than UNKNOWN. This was
  ruled and parked in Task 6 (T22).
- An unhandled exception inside an MCP tool body (for example `IllegalTransition`, `psycopg.Error`) reaches the worker
  as the SDK's `is_error` text, which may carry the exception message. Only the worker sees it, and the worker logs
  only "the server rejected the call". I judge this out of scope for T08's error-mapping subset.
- `export_environment` uses `setdefault`, so a stale `OPS_*` variable in the caller's shell silently wins over `.env`.
  This is a dev-ergonomics choice the plan made (ruling 1 process map).
- `down()` sends SIGTERM to recorded pids without checking that they are still the skeleton's (pid reuse on Windows).
  This is a dev-tool edge case.
- `check_invocation` re-checks `azp` although the verifier already restricts `azp` to `ops-worker`. This is defence in
  depth and harmless.
- Missing composite tenant FKs (`proposals`, `events`, `jobs` have no `(tenant_id, run_id)` FK, and several AM-20.2
  tenant tables have no `tenant_id` column yet). Revision 1's scope is the plan's ruling 7, and T09 owns RLS. Raised as
  a recommendation instead.
- The body is parsed before authorisation in `post_decision`, `authored_by` is read outside the decision transaction,
  and the FakeStore does not check the tenant. All three are already parked with owners (T12/T21).
- The incident sequence gaps, the excerpt truncation, and the single `INVALID_HANDLE` code are parked in the ledger with
  owners.

### Recommendations

For Plan E (T09/T10):

1. Use AM-20.2 as the checklist and grep every raw DML statement outside `ops_core.persistence`: `api/store.py`,
   `worker/handlers.py` (the freeze, M2), `mcp-write/execution.py` (grant, attempt states), and
   `mcp-read`/`mcp-write` `resolve_handle`. `mcp_read`/`mcp_exec` have **no** table grants, so `resolve_handle` must
   become `resolve_invocation` before those roles exist.
2. Revision 2 should add `(tenant_id, run_id) REFERENCES app.runs (tenant_id, run_id)` (runs already has the UNIQUE),
   and should add `tenant_id` to the AM-20.2 tenant tables that lack it (`jobs`, `drafts`, `decisions`,
   `execution_grant`, `action_attempt*`, `run_state_history`) before RLS is enabled. Without the FK, an RLS policy keyed
   on a denormalised `tenant_id` trusts every writer to copy it correctly.
3. Ruling 27's purge deletes from audit tables as the owner. Decide the per-session schema or reset story first, because
   the live suite stops working the moment T09's grants land.
4. `invocation_context.handle` becomes `handle_sha256`, and T15's revocation at job end closes the replay window that
   both the R105 test and probe (c) used (a fresh handle on a finished job is accepted today, as declared).
5. Fix I1 before T13 designs its reclaim, so that "a job that failed before reaching mcp-write" has an owner and a
   retry policy, rather than being a finished job nothing looks at.

For the process:

6. The per-task reviews could not see I1, because it only appears when one service is down while another is up. Keep
   a "one service down" probe matrix in every whole-branch brief.
7. When a fix round changes a pattern for a stated reason ("asserts are stripped under -O"), grep the branch for the
   same pattern in the same round (M4).

### Assessment

**Ready to merge?** With fixes

**Reasoning:** The authority chain, the single transition door, the replay rule and every token refusal hold under live
probes, and the gates are green. However, I1 is an undeclared shortcut that permanently strands an approved run after a
transient mcp-write outage, and the handoff currently says the opposite. It needs a small fix or, at minimum, a debt line
and a corrected sentence before Plan E builds on it. M1–M9 can be folded into the same commit or carried as owned items.

## Re-review (fix wave d7b6359 + b2c0e1e on top of e875d44)

Scope: `review-e875d44..b2c0e1e.diff` (16 files), the implementer's `final-fix-report.md` and the controller's
rulings. Read-only as before: probe rows purged, processes stopped, `reports/` restored, tree clean at `b2c0e1e`.

### Gates (measured)

| Gate | Result |
|---|---|
| `PYTHONUTF8=1 uv run python scripts/check.py` | `458 passed, 45 skipped in 26.21s`, `CHECK: GREEN` |
| `verify_handoff.py --reference-code --manifest --contracts` | `exit=0` |
| Live: `OPS_LIVE=1 … pytest tests/e2e tests/plan_b/live` | `24 passed in 70.59s` (15 + 9); `status` all down before and after; `git checkout -- reports/` |
| Attribution trailers, `e875d44..b2c0e1e` | none |
| `assert` statements in `mcp-write/src`, `core/src/ops_core/persistence.py` | none |
| `ruff check` / `ruff format --check` on the 9 changed `.py` files | clean / "9 files already formatted" |
| Lines over 120 characters (Python `len`) | none |
| `handoff/tasks.json`, `handoff/acceptance-matrix.json` parse | ok |

### Finding by finding

- **I1: addressed as ruled.**
  - `persistence.requeue_job` is at `core/src/ops_core/persistence.py:244-250`, with `TODO(T13)` for bounded retries.
  - On `McpCallFailed`, `execute` re-queues the job with `EXECUTE_RETRY_SECONDS = 30` and returns `False`
    (`worker/src/ops_worker/handlers.py:29,221-228`). `handle()` skips `finish_job` in that case (`handlers.py:240-241`).
  - The debt line is in SESSION_STATE ("re-queued every 30 s without a retry bound → T13/T22"), and the runbook has
    its sentence (`docs/runbooks/walking-skeleton.md:25`).
  - §19 is corrected: the read path fails the run, and the write path now retries.
  - Live test: `test_unreachable_write_server_requeues_the_execute_job`.
- **M1: addressed as ruled.** The token fetch is inside the `try` (`worker/src/ops_worker/mcp.py:60-61`), so an
  unreachable Keycloak (`httpx2.ConnectError`) becomes `McpCallFailed`. Residual nit: `TRANSPORT_FAILURES` still
  excludes `TokenRejected` and `ValueError`, so a malformed token-endpoint reply would still escape as a handler crash.
  That falls under the declared T13 crash debt and does not block.
- **M2: addressed as ruled.** `TODO(T09): freeze_proposal definer function…` is at `handlers.py:154`. The
  SESSION_STATE Next-task line still points Plan E only at "`TODO(T09)` in `ops_core.persistence`"; widening it was a
  recommendation, not part of the ruling.
- **M3: addressed as ruled.** The `psycopg.Error` handler returns `503 UNAVAILABLE` with a generic message
  (`api/src/ops_api/app.py:124-126`). The SESSION_STATE debt line reads "no reconnect after a database restart … → T13".
  Unit test: `test_database_failure_is_a_safe_503`, which also checks that the exception text is not echoed.
- **M4: addressed as ruled.** The four asserts in `mcp-write/src/ops_mcp_write/execution.py` (`:136,148,197,273`) now
  raise `RuntimeError`, and `persistence.py:185` raises `PersistenceError`. The incident-sim lifespan assert
  (`app.py:78`) is outside the ruled scope and remains.
- **M5: addressed as ruled.** `Skeleton.start` refuses when any process already answers (`scripts/skeleton.py:163-164`).
  This does not refuse a legitimate restart: `stop()` waits for the children to exit, and the live suite's own fixture
  started cleanly (24 passed).
- **M6: parked as ruled.** The runbook sentence says the R105 rows stay in the dev database on purpose.
- **M7: addressed as ruled.** `8136ee6..d7b6359` is the range in `SESSION_STATE.md:5,153`, `STATUS.md:108`,
  `handoff/tasks.json`, and `handoff/BUILD_BACKLOG.md:43`.
- **M8: addressed as ruled.** §19 now counts eleven Important findings, eight plus Task 9's three, and keeps the two
  security-review seams.
- **M9: addressed as ruled.** The conftest docstring is fixed (`tests/e2e/conftest.py:2`), and the README now reads
  "hardening starts with Plan E (T09/T10)".

### Probes (re-run)

- **(b) mcp-write DOWN, then approve.**
  - With mcp-write down, the run stays `APPROVED`. The execute job is not done and not claimed, `available_at` is
    about 29 s ahead, and `attempts=1`.
  - After mcp-write came up, the next poll completed the run to `SUCCEEDED` 30 s later: same job, `attempts=2`. The
    run has 2 jobs (investigate and execute), so no job was hand-inserted.
- **Permanent refusal does not loop.** I forced a run to `APPROVED` with no decision row, so mcp-write answers with a
  `GRANT_REFUSED` envelope, which is not `McpCallFailed`. The worker finished the job (`done`, `attempts=1`), it was
  not re-queued, and the run stayed `APPROVED`. That state can only be reached by forging it.
- **M1, worker started with `OPS_KC_BASE_URL=http://127.0.0.1:1`.** A new run reached `FAILED` with events
  `run.accepted, tool.started, run.failed`, and the job is done. The run is not stranded.
- **M5, `skeleton.py up` and then the R105 module.** The fixture raised
  `RuntimeError: skeleton processes already running; run down first`, so there was 1 error and no pass against the
  stale set. `down` was run afterwards, every process shows down and no port is listening.

### New issues opened by the fix

No new Critical or Important issues. Two Minor notes:

- Every retry mints a fresh `invocation_context` row, so a long mcp-write outage adds one row every 30 s per stranded
  run. This is bounded by the T13 retry bound and T15 handle revocation, both already declared.
- An execute job whose tool call returns `is_error` is re-queued indefinitely. This covers an unhandled exception
  inside mcp-write's tool, not `GRANT_REFUSED`. Each retry is idempotent, and the bound is the declared T13 item.

**Re-review verdict:** every finding is addressed as ruled (M6 parked as ruled), and the fix opened no new Critical or
Important breakage. Ready to merge.

---

# Part 2 — Controller rulings (ledger excerpt)

```text
Final review (opus): With fixes — 0 Critical, 1 Important (I1: execute job finished on McpCallFailed strands an APPROVED run and its slot; no owner, no debt line), 9 Minor, 9 declined; gates 457/44 GREEN, verify_handoff 0, live 23 passed; probes a–h as expected except (b) = I1
Ruling: fix wave covers I1 (re-queue the execute job with a 30 s backoff instead of finishing it; debt line for the bound on retries → T13/T22; runbook note; §19 sentence corrected), M1, M2, M3 (503 body; reconnect → T13 debt line), M4, M5, M7, M8, M9; M6 parked (the R105 run is the evidence; it is purged by nobody on purpose — recorded) — cost if wrong: an extra debt line
Final fix wave dispatched (sonnet, BASE e875d44)
Final fix wave DONE (commits d7b6359, b2c0e1e; live 15 e2e; check.py 458/45 GREEN; verify_handoff 0); scoped re-review dispatched (opus)
Scoped re-review (opus): all findings addressed, no new Critical/Important; probe (b) now completes via the re-queued job; grant refusal does not loop; M1/M5 hold; gates 458/45 GREEN, live 24 passed, verify_handoff 0. Four non-blocking notes parked: TokenRejected/ValueError from the token fetch not in TRANSPORT_FAILURES (the except Exception around the call covers the write path; read path fails the run), a new handle row per retry (T15 revocation), unbounded retries on is_error envelopes (declared T13 debt), SESSION_STATE next-task pointer — Ruling: parked; cost if wrong: none
Final review record preserved as docs/reviews/plan-d-final-review-2026-10-08.md
```

---

# Part 3 — Fix-wave report

# Plan D final fix wave

Commits: d7b6359 (code, tests, runbook, section 19, debt lines) and the handoff commit naming 8136ee6..d7b6359.

- I1: `execute` returns a bool; on McpCallFailed it calls the new `persistence.requeue_job(conn, id, 30)` and `handle()` skips `finish_job`. Debt line, runbook sentence and section 19 correction added. Proof: `test_unreachable_write_server_requeues_the_execute_job` (run stays APPROVED, job open, unclaimed, available_at in the future, reclaimable after available_at = now()).
- M1: token fetch moved inside the try in `HttpMcpCaller.call`.
- M2: `TODO(T09)` above the freeze SQL.
- M3: `psycopg.Error` handler gives 503 UNAVAILABLE; debt line added. Proof: `test_database_failure_is_a_safe_503`.
- M4: asserts replaced by RuntimeError / PersistenceError in execution.py and persistence.py.
- M5: `Skeleton.start` refuses when any health URL answers.
- M6: runbook sentence (R105 run is evidence, not purged).
- M7: ranges now 8136ee6..d7b6359 in SESSION_STATE, STATUS, tasks.json, BUILD_BACKLOG.
- M8: section 19 counts eleven Important findings. M9: conftest docstring and README status line.

Gates: ruff clean; plan_d 77 passed; live e2e 15 passed (reports/ restored, skeleton all down); check.py GREEN (458 passed, 45 skipped); verify_handoff exit 0; JSON parses.

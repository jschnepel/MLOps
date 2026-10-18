# Plan J final review record — T15 authenticated MCP read server, token verifier and invocation handles

Branch `plan-j`, executed range 00c76e4..8424ed7 (five tasks, the fifth the close-out; each with one task review, all
clean, no fix rounds). The whole-branch review below ran on the most capable model after the close-out; the controller
ruled on every finding; one fix wave (9676e62, e2f4f7f) applied the accepted ones; one scoped re-review verified them.
The plan's own review is `docs/reviews/plan-review-j-2026-10-15.md`; the task-scoped reviews are summarised in
`docs/PROJECT_HISTORY.md` section 27.

---

## Whole-branch review

# Plan J (T15) final whole-branch review

Range `00c76e4..8424ed7` on `plan-j` (6 commits: debt list, Tasks 1-5). Reviewed against the plan
(`docs/superpowers/plans/2026-10-15-first-slice-j-mcp-read-verifier-handles.md`: Global Constraints, Review Focus,
Rulings 1-25 and refinements (a)-(i), debt list, errata 72-81), SPEC_AMENDMENTS over BUILD_SPEC for T15, and the
SDD ledger. Method: I read the full production diff, every new and changed test, the close-out documents, and the
code the change depends on: `_resolve_handle` in 0007, `resolve_invocation` and `grant_execution` in 0004,
`mark_sent`, `privileges.py`, `handlers.execute`, `execution.create_incident`, `release_lease` and `requeue_job`, the
redaction filter, the realm export's client flags, and the SDK's `bearer_auth` and `inbound.classify_inbound_request`.
I also checked `tasks.json` dependency readiness and the remote branch refs. Nothing was run against a database or
live stack, and the checkout was not changed.

## Strengths

- **The guard is small, correct and in the right place.** `ProtocolVersionGuard` sits in front of the SDK app in
  both servers, so it runs before bearer auth. It accepts exactly one header with exactly the pinned value, which also
  refuses a doubled or padded copy. Its body is a single constant with `id: null` and no echo. Its `route_path`
  follows Starlette's root-path rule, so it still matches under a mount. I found no way around it. `/mcp/` gets a 307
  to `/mcp`, where the guard catches it. ASGI hands over the path already decoded and the header names in lower case.
  Every non-POST request goes to the SDK, which answers 405 behind auth. A modern header with no `_meta` fails the
  SDK's first check (`classify_inbound_request`), so header-right plus `_meta`-absent does not reach the legacy path.
- **mcp-read's token check has three layers, and each is pinned.** PyJWT checks `aud`. `McpVerifier` checks
  `aud ∋ resource` before it stamps the resource. `validate_token_resource=True` is pinned on. The verifier also
  requires `typ` Bearer and `azp` `ops-worker`. `read_verifier` is the one constructor, and
  `test_production_app_builds_its_verifier_through_read_verifier` proves the running app uses it. The realm export
  confirms `ops-worker` is service-account only (no standard flow, no direct grant), so no user token can carry
  `azp=ops-worker`.
- **Revision 0009 changes the minimum.** It replaces one statement of 0007's body and fails the upgrade if that
  statement is not found exactly once. The downgrade re-runs 0007's own body. Both are tested without a database
  (byte for byte) and live (`prosrc` equality, the details of a database built straight to 0008, and the round trip
  back to head). The column grants needed are already there: `app_definer` holds SELECT on all of `jobs`.
- **The allowlist table is exhaustive.** Every (job type with a server) × RunState × Tool combination is tested, one
  message covers every refusal, and the log line carries no handle. Investigate's states (QUEUED, RETRIEVING,
  DRAFTING) match where the worker calls mcp-read: it moves QUEUED→RETRIEVING and mints in the same unit. Execute's
  states (APPROVED, EXECUTING) match the first call and the re-queue's re-send. `requeue_job` leaves `done_at` NULL,
  so the binding does not refuse a re-queued job. In `test_unreachable_write_server_requeues_the_execute_job` the
  second `grant_execution`/`mark_sent` passes through the bound `_resolve_handle`.
- **The live evidence is careful.** Each cause in R027 is undone before the next and a positive call sits between
  them. The other-run case comes from a superuser rewrite of the job column. The log test turns on uvicorn
  propagation, requires uvicorn, SDK and httpx2 records before it trusts a clean result, and binds the verdict to
  indexes rather than to the value. R026's foreign tokens carry a valid handle, and the worker's token then answers
  the same request, so each 401 is the token's.
- **Every refusal of a presented handle looks the same.** A SQL OC008 and a Python allowlist refusal both become
  `INVALID_HANDLE` / "invocation handle rejected" / `data: null`, and the tests assert the whole `error` object and
  that no `action_id` appears.
- **The close-out is accurate on the points I checked.** `T47` really is the earliest dependency-satisfied PLANNED
  task (the others are T03 and T44, both DONE_PENDING_OWNER, and T17). The debt list names an owner for every
  shortcut. The commits carry no attribution trailers. The evidence files hold no token or handle, and
  `reports/mcp-read` was added to the JWT scan in `tests/plan_b/test_evidence.py`.

## Issues

### Critical

None.

### Important

**I1. mcp-write does not refuse a database without revision 0009, but the binding is claimed for both servers.**
- Where:
  - `mcp-write/src/ops_mcp_write/server.py:224-227`: the startup checks the clock profile and `app.model_permit` (0007)
    only.
  - `mcp-write/README.md:18`: "resolves `X-Ops-Invocation` for `execute` jobs that are still open". This line was
    changed in this range.
  - Erratum 75 and `STATUS.md` say `_resolve_handle` binds every handle.
- Why it matters: ruling 18's reason ("without it the server would resolve handles the binding refuses") applies to
  mcp-write equally. A database at exactly 0008 is the realistic case. Plan I told the owner to migrate the dev
  database to 0008. On such a database, mcp-read now refuses to start while mcp-write starts, and it resolves execute
  handles with 0007's unbound job read. The Python run-state rule still refuses a replay after the outcome, so the
  practical exposure is small: the cross-run job binding is missing. But the README and errata state a property this
  server does not enforce. The ledger already marks this FINAL-FIX.
- Fix:
  - Move `HANDLE_BINDING` into `core` (for example `ops_core.persistence.HANDLE_BINDING`). Members never import each
    other (ADR-0001), and `tests/plan_j/test_migration_0009.py` and `tests/e2e/test_migration_0009_live.py` currently
    import it from a service.
  - Re-export it from `ops_mcp_read.server`.
  - Add `await persistence.assert_function_text(conn, *HANDLE_BINDING)` to mcp-write's lifespan, inside the existing
    `try` (mcp_exec can read `pg_proc`).
  - Add a mcp-write case to the startup unit test (both ways; the connection is closed on refusal).
  - In `test_the_round_trip_restores_0008`, also assert that the check refuses `mcp_exec` at 0008.

### Minor

**M1. The lying-column case may be testing nothing** (`tests/e2e/test_mcp_read_t15_live.py:213-217`; ledger
FINAL-FIX). The `UPDATE … SET server = 'read'` result is not checked. If it matched no row, the next refusal would be
the plain wrong-server refusal from line 212, and the R085/R131 evidence line "lying server column" would be unproven.
- Fix: assert `cur.rowcount == 1`. Also add the positive control the ledger asks for: resolve the same execute and
  recover handles as `mcp_exec` through `app.resolve_invocation`, to show they were still live when mcp-read refused
  them.

**M2. No test now drives the tool path's only production replay end to end over HTTP.** That replay is the re-queue's
re-send in EXECUTING.
- Before this range, R105's step proved over the wire that a fresh execute handle reaches the replay. Ruling 6
  rewrote it into a refusal, which is right.
- The EXECUTING re-send is now covered in two halves:
  - The allowlist table's (EXECUTE, EXECUTING, CREATE_INCIDENT) row.
  - `GrantThenDownMcp`, which calls `grant_execution`/`mark_sent` directly and so skips `resolve_invocation`'s
    Python rule.
- If either half regressed, the worker would treat the `INVALID_HANDLE` envelope as final and close the job with the
  run stuck in EXECUTING.
- Fix: add a debt line naming T47 for "a live `create_incident` through mcp-write over HTTP with a fresh handle for
  the re-queued execute job of an EXECUTING run returns the same `action_id` and no second incident". The alternative
  is a live test now.

**M3. The mcp-write README overclaims the replay refusal** (`mcp-write/README.md:21-22`: "once the outcome is
recorded, any replay is refused `INVALID_HANDLE` before the grant"). `execution.py`'s new docstring correctly says that
an overlapping call that resolved its handle before the outcome was recorded still reaches the stored branch.
- Fix: "a replay that resolves its handle after the outcome is recorded is refused".

**M4. The owner-input records are stale**:
- `SESSION_STATE.md:7` tells the owner to "open the plan-h -> plan-g, plan-i -> plan-h and plan-j -> plan-i PRs".
- `SESSION_STATE.md:15` (the Repository line) and `:890` ("Merge the stacked PRs #1-#5") still say #1-#5. The ledger
  records PRs #1-#8 open, and `origin/plan-g`, `origin/plan-h` and `origin/plan-i` exist.
- The `origin/plan-e is two docs commits behind` aside is probably stale too.

Following these lines would send the owner to open PRs that already exist. I could not confirm the PR numbers (no
`gh`). Fix: state what is actually open and what remains (plan-j -> plan-i), and drop or verify the plan-e aside.

**M5. R026's evidence leaves out what already exists for mcp-write.** R026 is `IMPLEMENTED_LOCALLY_VERIFIED` with
mcp-read evidence only. The requirement names "MCP", and mcp-write's verifier hardening is T47 debt. mcp-write does
refuse a wrong `aud` through PyJWT, and R105 proves it live (persona and mcp-read tokens refused at mcp-write).
- Fix: add `tests/e2e/test_r105_walking_skeleton.py` to R026's `evidence_paths` and one clause to its note, so the
  status does not rest on mcp-read alone.

**M6. `tests/plan_j/test_worker_azp.py:4-6` claims more than one change can deliver.** It says a renamed worker client
works if the mint follows `client_id`. A rename would still fail at three more literals:
- `main.py` builds the token source with `client_id="ops-worker"`;
- `read_verifier`'s `allowed_azp`;
- the write-path definers' `'ops-worker'` (T47 debt).

The plumbing is right; the docstring should say the mint is one of four places a rename touches.

**M7. T15's DONE leans on errata the owner has not decided** (`handoff/tasks.json` T15, `BUILD_BACKLOG.md:93`). T15's
title and two of its review notes (the `asset_scope`/`search_procedures_scoped` function set, the attempt-state
allowlist) are met only through errata 72 and 76, which the owner has not decided. That matches the project's debt
convention, but the record should say so: append "(DONE subject to errata 72 and 76)" to the Plan J review note, or
the STATUS line.

## Deferred-minor triage (every ledger minor; the ledger has no "Ruling:" lines)

| # | Ledger item | Verdict | Reason |
|---|---|---|---|
| T1-a | Pin `POST /mcp/` without header is not 200; guard `path` default and `streamable_http_path` are separate literals | fix-before-merge | One unit test plus a shared constant (for example `MCP_PATH` in `ops_core.mcp_protocol`, passed to both). The probe found no bypass today, but the redirect behaviour belongs to the SDK and could change on a bump |
| T1-b | `test_verifier_t15.py` AccessToken repr with synthetic JWT in assert operand (now lines 156, 162) | stay deferred | Synthetic key pair only, so no real secret can print; plan-mandated |
| T1-c | `test_mcp_read_http.py:8` docstring cites a live module created later | close (resolved) | `tests/e2e/test_mcp_read_t15_live.py` exists at head |
| T2-a | mcp-write's startup check lacks 0009 | fix-before-merge | I1 |
| T2-b | Newest-body guard finds re-creations only via a `FUNCTIONS` attribute | stay deferred | The live round trip asserts `MARKER in head["body"]` against the migrated database, which catches a later revision that drops the marker whatever its module shape |
| T3-a | Log test checks only the handle; add the worker token to `carrying` | fix-before-merge | Two lines; tokens are secrets under the same rule (SA:566 / Global Constraints) |
| T3-b | Lying-column UPDATE asserts no rowcount | fix-before-merge | M1 (the evidence line could be vacuous) |
| T3-c | Recover/execute refusals have no positive control | fix-before-merge | M1 (cheap; a definer-level resolve as `mcp_exec`) |
| T3-d | Assert no `RedactingFilter` on `caplog.handler` | fix-before-merge | The filter rewrites records in place. `test_install_puts_the_filter_on_every_root_handler` restores the handlers today, but one assertion makes "unredacted" true by construction rather than by test order |
| T3-e | Runs/tokens created before `try` (purge gap) | stay deferred | The per-session test database is dropped; no cross-session leak |
| T3-f | Wording: "13 others refused", R027 docstring "same handle answers again", record count varies | stay deferred (fold the R027 docstring fix into the wave if convenient) | Cosmetic; none changes a verdict |
| T4-a | Child-log leak check covers the handle only; add the worker token, and read the child log in `test_r026` for the three foreign tokens | fix-before-merge | Cheap; this is the only check of the real `serve()` log path |
| T4-b | Evidence line "R025/R031" should name the halves; interpolate `PROTOCOL_VERSION` | fix-before-merge | Evidence truthfulness; the regenerated file comes from the wave's live gate |
| T4-c | `response.headers["www-authenticate"]` → `.get(..., "")` | fix-before-merge | Trivial; a missing header should fail the comparison, not raise a KeyError |
| T4-d | Start-failure messages should name the child log path | fix-before-merge | Trivial diagnosability (path, never content) |
| T4-e | `free_port` race; failed-start/kill paths verified by reading only | stay deferred | Test-harness robustness; bounded by the 60 s deadline and `finally` |
| T5-a | R027 `evidence_paths` lack `test_definers_write_path_live.py` | fix-before-merge | Its note cites that file for the other-azp case, which is R027's "other workload" evidence |
| T5-b | SESSION_STATE "PRs #1-#5" | fix-before-merge | M4 |
| T5-c | R026 rests on a stand-in browser token | stay deferred | Disclosed in the note and erratum 81; the owner decides |
| T5-d | PROJECT_HISTORY §27 two "Problem." labels; STATUS doubled blank line (`STATUS.md:227-228`) | fix-before-merge (trivial) | The wave edits both files anyway; the second "Problem." could read "**Review.**" |

## Declined to judge

- **Live gate counts (1071/164, 1214/21) and the content of the regenerated evidence files.** I was not allowed to
  run live tests, so I took the ledger and task reports at their word.
- **Merits of errata 72-81 and whether the `IMPLEMENTED_LOCALLY_VERIFIED` statuses meet the owner's bar.** Both are
  owner decisions.
- **Timing differences between refusal causes (SQL vs Python).** The spec is silent. The handles are 256-bit and a
  probe needs the worker's token.
- **mcp-write's verifier, the write-path definers' literal `'ops-worker'` and the attempt-state allowlist.** These are
  declared T47 debt.
- **A handle revoked or expired in the middle of a call becoming an UNKNOWN envelope that carries `action_id`.** This
  is T13/T22 behaviour this range does not change, and the caller had a valid handle when the call started.
- **Keycloak realm hardening beyond the client flags I read.** For example token exchange, or client-scope defaults.
- **SDK internals beyond `bearer_auth` and the inbound version check.** I relied on the in-process and live evidence
  for the rest of the 2.3.0 transport.
- **Exact PR numbers on GitHub.** `gh` is not available here, so I relied on the ledger and the remote refs.
- **The Ollama 0.33.3 → 0.40.4 drift.** It is environment, recorded without a claim, and an upgrade is the owner's
  decision (AM-30).
- **The cost of 0009's added predicate.** It is a primary-key lookup plus two column comparisons, which is
  negligible.
- **Whether Windows `TerminateProcess` leaves orphans.** I only read the code. The ledger says none was observed.

## Recommendations

1. Make I1 and the fix-before-merge rows one fix wave. Re-run both gates and `verify_handoff`, regenerate
   `reports/mcp-read/` from the live run, and append this review's problems and fixes to `PROJECT_HISTORY.md` §27.
2. Give the MCP path one constant in `ops_core.mcp_protocol`, used by the guard default and both servers'
   `streamable_http_path` (T1-a).
3. Make refusals visible to an operator without exposing secrets. Today a SQL OC008 refusal logs nothing and the guard
   logs nothing, so the runbook's only diagnostic is the superuser query. A WARNING line with the tool name and the
   refusal class ("version", "handle"), or a counter for T28's dashboards, would help. Never log the value or the
   cause detail.
4. Record M2's live end-to-end re-send as an explicit T47 DoD item, so the tool path's only production replay gets an
   over-the-wire test when mcp-write is hardened.
5. When T47 replaces the write-path definers' literal azp, also remove the `"ops-worker"` literals in `main.py` and
   `read_verifier`'s `allowed_azp`. Settings should name the worker client once (M6).

## Assessment

**Ready to merge?** With fixes

**Reasoning:** The authentication, binding and allowlist changes are sound. I found no way for a foreign token,
another server's handle, another run's job or a stale handle to reach a tool, and no way around the version guard.
One Important gap remains: mcp-write does not refuse a database without 0009, yet the binding is claimed for both
servers. Several cheap test-vacuity and record fixes the ledger already flagged should go in the same wave.


---

## Controller rulings on the findings

- Fixed in the one wave: I1 (mcp-write did not check for revision 0009 at start although the documents said the
  binding protected both servers: `HANDLE_BINDING` moved into `core`, mcp-write's startup checks it, unit and live
  tests), M1 and the ledger's test-strength items (row count, positive controls, the token added to every log check, no
  redaction filter on the capture handler, `POST /mcp/` pinned, one shared MCP path constant, the evidence line marked
  "read half", the header lookup, start-failure messages naming the log path), M3 (mcp-write README replay wording), M4
  (open PRs), M5 and the R027 evidence paths, M7 (T15 DONE subject to the owner's decisions on errata 72 and 76), the
  history labels.
- Recorded as T47 debt: M2 (no HTTP test drives the EXECUTING re-queue re-send through mcp-write) and M6 (three other
  `"ops-worker"` literals).

---

## Fix wave report

# Plan J final-review fix wave — report

FIX_BASE `8424ed7`. Commits (no attribution trailers):

- `9676e62` fix(mcp): mcp-write refuses a database without 0009; stronger T15 evidence (Plan J final review)
- `e2f4f7f` docs: record the Plan J final-review fix wave (PRs, R026/R027 evidence, T15 subject to errata 72/76, T47 debt)

## Per ruling

1. **I1.**
   - `core/src/ops_core/persistence.py:178-183`: `HANDLE_BINDING: Final` now lives in core, beside `assert_function_text`.
   - `mcp-read/src/ops_mcp_read/server.py:43-45`: mcp-read re-exports it (`HANDLE_BINDING = persistence.HANDLE_BINDING`), and its lifespan is unchanged (`:226`).
   - `mcp-write/src/ops_mcp_write/server.py:228-230`: the startup calls `assert_function_text(conn, *persistence.HANDLE_BINDING)` after the `app.model_permit` check, inside the existing `try`, so a refusal closes the connection.
   - Tests:
     - `tests/plan_j/test_mcp_read_startup.py:68` checks that the re-export is core's object.
     - `:73-102` covers mcp-write both ways: refused before 0009 with the connection closed, the marker asked last and `app.model_permit` still asked; starts at 0009 and closes at shutdown. Before the fix, the two mcp-write tests failed (checked against HEAD's server.py and then restored).
     - The fake connection answers `missing: False` for `assert_relation`.
     - `tests/plan_j/test_migration_0009.py` and `tests/e2e/test_migration_0009_live.py` now import from `ops_core.persistence`.
     - In the live round trip (`test_migration_0009_live.py:78-98`), `mcp_exec` passes at the head, is refused at 0008 ("predates this service"), and passes again at the head after the upgrade. mcp-read does the same.
   - Erratum 75 and the README needed no change: they claim both servers, which is now true. Wording elsewhere was updated: STATUS "Also built", the mcp-read runbook start section, and SESSION_STATE's 0009 update paragraph.
2. **M1 / T3-b, T3-c** (`tests/e2e/test_mcp_read_t15_live.py`):
   - `set_server` (`:144-150`) asserts `rowcount == 1`.
   - `job_at_mcp_exec` (`:137`) resolves the handle at the definer as `mcp_exec`.
   - In the R085/R131 test (`:229-242`), each recover and execute refusal is followed by `mcp_exec` resolving the same handle to the expected job.
   - For the lying column, the refusal is followed by `mcp_exec` refusing with `OC008` (the lie landed). The column is then put back to `write` (one row), and `mcp_exec` resolves the handle again.
3. **T3-a, T4-a:**
   - The DEBUG log test's `carrying` (t15 live `:365`) checks the handle or the worker token, as indexes only. Its evidence line says "none holds the handle or the worker's token".
   - `test_mcp_read_process_live.py:122`: R025's child log check is one boolean over (handle, token).
   - `:179`: R026 reads the child log for the three foreign tokens, the worker token and the handle, as one boolean.
4. **T3-d:** `test_mcp_read_t15_live.py:341` asserts that no `RedactingFilter` is on `caplog.handler.filters`.
5. **T1-a:**
   - `core/src/ops_core/mcp_protocol.py:24-26` adds `MCP_PATH`. It is the guard's default (`:60`) and both servers' `streamable_http_path` (mcp-read `:217`, mcp-write `:216`).
   - `tests/plan_j/test_mcp_read_http.py:101` pins `POST /mcp/` without the header: 307 with `location` ending `/mcp`. Followed, the request gets the guard's 400/-32022.
6. **T4-b, T4-c, T4-d** (`test_mcp_read_process_live.py`):
   - `:125-128`: the evidence line is "R025 (read half; mcp-write with T47) / R031 (network half): … mode {PROTOCOL_VERSION} …".
   - `:172`: `headers.get("www-authenticate", "")`.
   - `:84-86`: the start-failure messages name the child log path, not its content.
7. **M3:** `mcp-write/README.md:16-24`: "a replay that resolves its handle after the outcome is recorded is refused…". An overlapping call that resolved before can still reach the stored outcome (as `execution.py` says). The README also notes the 0009 start check.
8. **M4 / T5-b:** SESSION_STATE:
   - Next-task owner input (2), `:5-14`: merge PRs #1-#8 (plan-b→main … plan-i→plan-h). The plan-j PR is opened after this wave. "open the plan-h/plan-i PRs" is removed.
   - Repository line `:18`: plan-g/h/i are pushed and every remote branch matches its local branch (checked with `git rev-list`), so the stale `origin/plan-e` aside is removed. PRs #1-#8 are open.
   - Open owner inputs `:917`: #1-#8.
9. **M5:** the R026 `evidence_paths` gain `tests/e2e/test_r105_walking_skeleton.py`. A note clause says persona and ops-mcp-read tokens are refused live at mcp-write.
10. **T5-a:** R027 `evidence_paths` gain `tests/e2e/test_definers_write_path_live.py`.
11. **M7:** These say that T15's DONE is subject to the owner's decisions on errata 72 and 76:
    - the T15 review note in `tasks.json` and `BUILD_BACKLOG.md`
    - SESSION_STATE `:6-8`
    - STATUS `:255`
12. **M2 / M6:**
    - Two "added by the final review" debt lines → T47 in the Plan J debt list (SESSION_STATE `:848-856`).
    - A T47 review note in `tasks.json` and `BUILD_BACKLOG.md`: the DoD note for the live EXECUTING re-send, plus the worker client named once.
    - The `tests/plan_j/test_worker_azp.py` docstring now says it proves only that the mint follows the token source, and that the other three `"ops-worker"` places are T47 debt.
13. **T5-d:**
    - PROJECT_HISTORY §27's second "Problem." is now "**Review.**" (`:462`).
    - The final-review paragraphs are appended (`:474-`): 0 Critical, 1 Important, 7 Minor; the checks that held; the fixes; the debts to T47.
    - STATUS's doubled blank line is removed. STATUS and SESSION_STATE record the final review.
    - T3-f was folded in: the R027 docstring now says "a call answers in between (the same handle until its lease lapses, then a fresh one…)".

## Commands and output

- Focused unit: `uv run python -m pytest tests/plan_j/test_mcp_read_startup.py tests/plan_j/test_migration_0009.py -q` → 10 passed. The trailing-slash test → 1 passed.
- Focused live: `OPS_LIVE=1 PYTHONUTF8=1 PROFILE=test uv run python -m pytest tests/e2e/test_mcp_read_t15_live.py tests/e2e/test_mcp_read_process_live.py tests/e2e/test_migration_0009_live.py -q` → 10 passed.
- `PYTHONUTF8=1 uv run python scripts/check.py` → `1075 passed, 164 skipped`, `CHECK: GREEN` (was 1071/164; +4 unit tests).
- `PYTHONUTF8=1 uv run python scripts/check.py --profile test` (skeleton status: every process down) → `1218 passed, 21 skipped in 331s`, `CHECK: GREEN` (was 1214/21).
- `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts` → exit 0.
- `tasks.json` and `acceptance-matrix.json` parse as JSON. Only the intended lines changed (indent 2, `ensure_ascii=False`).
- Evidence: `reports/mcp-read/` was committed with the regenerated lines (the R025/R031 halves, the R085/R131 controls, "handle or the worker's token"). It holds no token or handle. The other seven report directories were reverted (timestamps only).
- ≤120 chars: every changed code and test file passes. In the docs, the only longer lines are the existing single-line style of SESSION_STATE's Repository and owner-input bullets.

## Concerns

- The new mcp-write startup test lives in `tests/plan_j/test_mcp_read_startup.py`, whose docstring now covers both servers. The file name was kept.
- The memory note says PRs #1-#6. I followed the controller's #1-#8, which I could not check: there is no `gh`.


---

## Scoped re-review of the fix wave (8424ed7..e2f4f7f)

Verdict: all 13 rulings addressed, no new Critical or Important breakage. No new test puts a token or handle in an
assert operand or failure message (leak checks reduce to one boolean or index lists); moving `HANDLE_BINDING` into
`core` keeps ADR-0001 (no service imports another); `tests/plan_j` ran 42 passed; both handoff JSON files parse.

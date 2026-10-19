# Plan M final review record — T16 read tools, asset_scope and asset-sim

Branch `plan-m`. The whole-branch review covered `9e7d716..a4e8531` (the plan's last commit to the close-out): seven
tasks, each with one task review and one fix round, recorded in `docs/PROJECT_HISTORY.md` §30. It also served as the
only review of Task 7's records (a controller ruling: the records are the whole-branch reviewer's subject anyway). No
agent connected to any database other than the `ops_test` databases of the test profile, and no reviewer ran a live
test.

Outcome: ready to merge with fixes — 0 Critical, 3 Important, 8 Minor. The controller ruled every item fixed except
one Minor parked (the duplicated RFC 3339 / asset-ID / instant patterns). The fix wave is `71753ab`; a scoped
re-review approved it, and the one Minor it raised (this wave's own interpreter slip missing from the history) was
added in the commit that adds this record. Gates after the wave: dev 1372 passed / 205 skipped; live (`--profile
test`) 1556 passed / 21 skipped; `verify_handoff.py --reference-code --manifest --contracts` exit 0.

---

# Controller rulings on the final review

## Plan M final review — controller rulings (review: C:\Users\joeys\Desktop\MLOps\.superpowers\planm\final-review.md)

One fix wave, then one scoped re-review.

### Important — fix
1. Milestones: `handoff/tasks.json` `current_milestone` → "M06"; M05's status → "DONE" (T15, T47, T17, T16 all DONE). SESSION_STATE already says M06.
2. "60 s at most" overclaim: in every record that says it (R028 note, erratum 105, the debt list, T16's note in tasks.json, BUILD_BACKLOG, PROJECT_HISTORY §30 — grep "60 s" / "60 seconds" / "<=60"), say instead: the read-path re-check requires only an active row, with no synced_at freshness bound (unlike the write gate's MEMBERSHIP_STALE, 0005:129-139); while the sweeper syncs, a deprovisioned requester keeps read access until the next sync (60 s cadence, SA:547); if the sync stops, the access lasts until it resumes. Debt line: a read-path freshness bound → **T20** (the next read-path task), subject to the owner's decision on erratum 105.
3. Retryable read failures end runs: correct `mcp-read/src/ops_mcp_read/assets.py:7` ("the job retries" is untrue today); add a debt line → **T20** (honour `retryable` from a read with a bounded re-queue of the investigate job; today any read failure, including a retryable UNAVAILABLE from asset-sim behind search, fails the run as "retrieval failed"); one sentence in `docs/runbooks/asset-sim.md` and `docs/runbooks/mcp-read.md` troubleshooting saying so.

### Minor — fix
- `asset-sim` data.py: a comment where alerts are keyed by asset_id alone, that this relies on asset IDs being unique across tenants, which `ops_core.corpus.load_assets` enforces.
- `docs/runbooks/walking-skeleton.md:24` and `:46`: `up` needs revision 0012 now (mcp-read's startup check), not 0006.
- PROJECT_HISTORY §30: the `python3 -`/`python -` slips — state them precisely: the records-commit agent (4be745a) ran an empty `python -` and then killed every python.exe with taskkill by image name; Task 1's fix-round implementer ran an empty `python3 -` heredoc (stopped by the controller); the round-1 plan critic launched `uv run python -I - < /dev/null` (empty stdin). And add Task 6's fifth minor (the untracked evidence, committed by Task 7).
- `Unavailable` docstring: only a 401 maps there; a 403 is UPSTREAM_INVALID.
- Rename `test_a_page_of_no_alerts_is_refused` to what it tests (a limit below 1 is refused).
- `mcp-read/src/ops_mcp_read/server.py:394-397`: search refusals after the scope is known carry `observed_at = scope.as_of` (Task 3's rule), not the wall clock; adjust/extend the unit test that pins it.
- R028's acceptance note: the model-facing path for asset data arrives with T20 (the worker does not yet pass asset reads to the model).

### Minor — parked
- rfc3339 / asset-ID / instant patterns written in several places: ruling — park; consolidating crosses three packages' boundaries for no behaviour change; cost if wrong: a future pattern change edited in three places (tests pin each).

---

# The final review

## Plan M final whole-branch review (T16: read tools, asset_scope, asset-sim, R028, R029)

Range `9e7d716..a4e8531` on `plan-m` (14 commits, 76 files, +4336/-289). Reviewer: final whole-branch reviewer, read-only.

Gates I ran (database-free only):
- `PYTHONUTF8=1 uv run python scripts/check.py < /dev/null` → `1371 passed, 205 skipped`, `CHECK: GREEN` (matches the records).
- `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts < /dev/null` → all PASS, exit 0.
- No live test was run and nothing connected to a database, Keycloak or a service (per the rules). The live figures
  (1555/21) and the live evidence are taken from the committed reports and the ledger.

### Strengths

- **The end-to-end read path holds its boundaries.** I followed `get_asset_status`, `get_recent_alerts` and
  `search_procedures` from the worker to asset-sim and back:
  - The tenant, asset, interval and `as_of` all come from `app.asset_scope`, which the handle drives through
    `_resolve_handle` (0012:66-91). No argument reaches the tenant.
  - Both data-returning definers re-check the requester's membership (0012:56-64, 106). Every path that returns data
    goes through one of them. The only path that stops after `resolve_invocation` is `UNSUPPORTED_MODE`, and it
    returns no data (server.py:361-365).
  - mcp-read refuses another asset or interval before any outbound call (server.py:304-339). The search's asset-sim
    lookup runs only after unit 2 (the membership re-check), so no scope check is skipped.
  - mcp-read sends asset-sim only its own `ops-mcp-read` token plus `X-Ops-Tenant-Id` and `X-Ops-As-Of`
    (assets.py:126-136). The unit test checks that neither the handle nor the worker's token reaches asset-sim
    (test_mcp_read_assets.py:153-169).
  - `mcp_read` gets no table grant. The two definers are granted to `mcp_read` alone with REVOKE PUBLIC
    (0012:153-160). R131's equality and the 42501 for `mcp_exec` are tested live.
- **asset-sim is careful.** It uses the same 404 for an unknown asset and another tenant's asset (and the live test
  compares the bodies). Its cursor is canonical, bound to the request and range-checked. It has no clock of its own.
  The fault routes are not even registered outside `PROFILE=test`, they need mcp-read's token, and a unit test
  covers every non-test profile.
- **mcp-read does not trust asset-sim.** It validates every asset-sim answer as a whole tool result and against the
  run's scope (`within_scope`): the status instant, the page size, the interval and nothing after `as_of`. Every
  failure becomes an envelope with the right retry flag.
- **R029 fails closed at every leaf.** The fix for the SDK's in-session `RuntimeError` (all leaves inspected, while
  cancellations still propagate) is right, and it is proven twice: once against the real server in-process and once
  through the investigate handler, which ends the run FAILED "retrieval failed", not INTERRUPTED.
- **The tests can fail.** The R028 revoked-procedure assertion is backed by a measured rank (about 1.5 against the
  0.25 floor). The altered-listing tests assert that the tool was never called (`db.calls == []`). Each oversized or
  malformed case is matched on its own message, which proves the order of the checks. The membership test checks
  "ok before, refused during, ok after".
- **Cross-task interfaces agree.**
  - 0012's return shape matches `persistence.AssetScope` and `Procedures`.
  - The startup markers (`ASSET_SCOPE`, `SEARCH_INSTANT`, and `GOVERNED_CORPUS` kept) appear only in 0012's text and
    are tested.
  - asset-sim's routes, headers and status codes match mcp-read's client and its error mapping.
  - The committed input schemas, what mcp-read advertises and what the worker compares are the same files.
  - `OPS_ASSET_SIM_URL`, `OPS_ASSET_SIM_PORT`, port 8091, `kc_client_secret_ops_mcp_read` and the seven processes
    with asset-sim first agree across the code, the runbooks, `SKELETON_PORTS` and the tests.
- **The evidence is clean.** The committed reports hold codes and counts only, with no token, secret or handle.
  Every evidence path in R028, R029 and R131 exists and is tracked.

### Issues

#### Critical

None.

#### Important

**I1. `handoff/tasks.json` still has M05 open (`current_milestone: "M05"`, M05 `status: "PLANNED"`), while
SESSION_STATE.md says M06.** `handoff/tasks.json:3` and `handoff/tasks.json:75`.

- M05's `task_ids` are T15, T47, T17 and T16, and all four are now `DONE`.
- Precedent: 4be745a set each milestone's status from its tasks (M02-M04 `DONE`) and set `current_milestone` to the
  earliest open milestone.
- SESSION_STATE.md:4 ("Current milestone: M06 ... M05 ... closed with T16") is the correct one.

Why it matters: CLAUDE.md makes `tasks.json` the dependency graph that the next session starts from, and the two
records now contradict each other.

Fix: set `"current_milestone": "M06"` and M05 `"status": "DONE"`. Nothing else needs to change.

**I2. The read-path membership lag is recorded as "60 s at most", but that bound only holds while the sweeper syncs
successfully.** The phrase appears in:
- `handoff/acceptance-matrix.json:538` (R028 note, "60 s at most");
- `SESSION_STATE.md:881` (erratum 105, "60 seconds at most, SA:547");
- `SESSION_STATE.md:1195` (debt list, "<= 60 s");
- `handoff/tasks.json:782` and `handoff/BUILD_BACKLOG.md:111` (T16 note);
- `docs/PROJECT_HISTORY.md:762`.

The re-check in 0012:60-61 requires only `m.active`. It has no `synced_at` bound. The write gate has one
(`MEMBERSHIP_STALE`, 0005:129-139) because the sync can stop. `docs/runbooks/walking-skeleton.md:38-42` lists ways
it stops: the sweeper is down, the realm is unreachable, or the mass-deactivation guard refuses and stamps nothing.
In any of those cases a deprovisioned requester keeps read access with no limit. "60 s at most" therefore overstates
what R028 ("current ... access") has shown.

Fix (records only):
- Reword each occurrence to say the lag lasts "until the sweeper's next successful sync (about 30-60 s while it
  runs; unbounded while the sync is stopped, because the read path, unlike the write gate, has no `synced_at` bound)".
- Give the missing freshness bound an owner in the debt list. The candidates are T21, next to the grant's freshness
  checks, or the owner's decision on erratum 105. Right now the line says only "recorded for erratum 105's note".
- Alternative: add `AND m.synced_at >= app.current_time() - interval '120 seconds'` in a later revision. That would
  refuse every read while the sweeper is down, which is the write gate's trade-off.

**I3. Retryable asset-sim failures fail every investigation for good, and the code says "the job retries".** This
comes from two tasks together:
- Task 4 made every `search_procedures` call depend on asset-sim, which it asks for the run's asset type
  (server.py:373-377).
- mcp-read now answers `UNAVAILABLE` with `retryable: true`.
- The worker's investigate handler turns any `McpCallFailed`, including a `status: "error"` read, into a terminal
  FAILED "retrieval failed" (`worker/src/ops_worker/handlers.py:132-135`). It never re-queues and never reads
  `retryable`.

So one asset-sim blip, or asset-sim not running, terminally fails every run that reaches retrieval. Before T16 the
investigate path did not depend on asset-sim. Meanwhile `mcp-read/src/ops_mcp_read/assets.py:7` says "no retry (the
job retries)", which comes from ruling 15. That is not true of any job today.

Failing closed is the right R029 outcome, but this shortcut is on no debt list (SA:698).

Fix:
- Correct the docstring to say "no retry here; the worker currently fails the run on any read error".
- Add a debt line with an owner: T20, which builds the read nodes, or T22 (bounded retries). The line should cover
  honouring `retryable` on read envelopes with a bounded re-queue.
- Add one sentence to `docs/runbooks/mcp-read.md`, in the "Every asset tool answers UNAVAILABLE" item: while
  asset-sim is down, investigations end FAILED.

#### Minor

**M1. asset-sim keys alerts and display names by `asset_id` alone** (`asset-sim/src/ops_asset_sim/data.py:144`,
`:159`, `:165`, `:237`). This is safe today only because `corpus.load_assets` requires asset IDs to be unique across
all tenants (`core/src/ops_core/corpus.py:252`). If a later corpus allows the same ID in two tenants, tenant A's
status and alerts would silently include tenant B's alerts, after the tenant filter has already passed.

Fix: key `Catalog.alerts` (and `names`) by `(tenant_id, asset_id)`, or at least add a comment and an assertion in
`load` that the IDs are globally unique.

**M2. `docs/runbooks/walking-skeleton.md:24` and `:46` still say the dev database must carry revision 0006 before
`up`.** mcp-read now refuses to start below 0012, so on today's dev database (0011) `up` leaves mcp-read down. This
was already stale in Plan L, and it is more wrong now.

Fix: say 0012, naming mcp-read's own check, and point to the owner input.

**M3. Small accuracy gaps in `docs/PROJECT_HISTORY.md` §30.**
- "Implementers twice started a `python3 -` command" (line ~808): the ledger records one such incident (Task 1,
  bmtibuzx5). Either cite the second one or say "once".
- Task 6's review had five minors. The fifth (the evidence, deferred to Task 7) is not mentioned. Add a clause.
- Task 7 and this final review still need their paragraph in the fix wave, as the section already says.

**M4. The `Unavailable` docstring says "a refused token" (`mcp-read/src/ops_mcp_read/assets.py:40`), but only a 401
maps there. A 403 (lost audience) is `UpstreamInvalid` (assets.py:163), as the runbook says correctly.**

Fix: write "a 401 to mcp-read's token".

**M5. The same helpers are defined in several places.**
- `rfc3339` is the same function in `mcp-read/src/ops_mcp_read/assets.py:90` and
  `asset-sim/src/ops_asset_sim/data.py:118`.
- The asset-id pattern is spelled four times: `core/src/ops_core/corpus.py:246`, `data.py:41`, `assets.py:28` and
  `server.py:58`.
- The instant pattern is spelled twice: `data.py:49` and `server.py:59`.

They agree today. Moving them into `ops_core` (for example next to `tool_contracts`) would remove the risk that they
drift apart. Low priority.

**M6. The name `test_a_page_of_no_alerts_is_refused` (`tests/plan_m/test_asset_sim_data.py:231`) does not match the
test, which checks `limit=0`.** Fix: rename it to `test_a_limit_below_one_is_refused`.

**M7. In the search, refusals after the scope is known still use the wall clock**
(`mcp-read/src/ops_mcp_read/server.py:394-397`). The unit-3 `INVALID_HANDLE` and `REFUSED` envelopes have no
`observed_at`, so they take the wall clock even though a database instant (`scope.as_of`) is already known. The
asset tools stamp `as_of` on every refusal after the scope. Ruling 3 keeps the wall clock only for refusals before
any database unit.

Fix: pass `observed_at=scope.as_of`. This is a consistency fix, not a security one.

**M8. R028's `expected_evidence` reads "no forbidden data reaches the model".** Today the model sees only the
worker's search results. The worker's asset reads into the draft are T20's. The note correctly says "reaches the
caller". Adding one clause, "the model-facing path for asset data arrives with T20", would make clear what
`IMPLEMENTED_LOCALLY_VERIFIED` covers.

### Records verdict (Task 7's only review)

- **tasks.json:**
  - T16 is `DONE`, and its two notes (the ruling on debts b and c, and the shipped/evidence/deferred summary) are
    accurate against the code and the ledger.
  - T18 gained the vector-mode note (erratum 103), and it is correct.
  - **Wrong:** `current_milestone` and M05's status (I1).
  - Overclaim: "60 s at most" (I2).
- **acceptance-matrix.json:**
  - R028: `IMPLEMENTED_LOCALLY_VERIFIED` / `RECORDED_LOCALLY_LIVE`. R029: `IMPLEMENTED_LOCALLY_VERIFIED` /
    `RECORDED_LOCALLY` (its refusals run in check.py; the live case is positive only, and the note says so). Both
    statuses fit the matrix vocabulary.
  - R025 and R131 notes are updated correctly, and R131 adds `test_migration_0012_live.py`.
  - Every claim I checked has a test behind it:
    - "resolve_invocation still resolves" and "a run requested by a reader never answers":
      test_migration_0012_live.py:101-138.
    - `mcp_exec` gets 42501 on `asset_scope`: test_migration_0012_live.py:85-89.
    - R025's "get_asset_status ... through asset-sim": t15-independent-client.txt.
  - Every evidence path exists and is committed. Only overclaim: I2.
- **BUILD_BACKLOG.md:** the T16 checkbox, both notes and T18's note mirror tasks.json. (The status summary on line 3
  is stale from Plan A. That predates this branch.)
- **SESSION_STATE.md:**
  - "Current milestone: M06" is correct (I1 is the mismatch on the other side).
  - The "Next task" text is not stale: it names T18 or T23.
  - The owner inputs include "migrate dev to 0012" with the command and its effect, plus errata 103-106.
  - Errata 103, 104 and 106 are worded accurately against the code. 106's "15 of 69 sections, 504-669 characters"
    matches retrieval.md.
  - Erratum 105 is accurate except for the "60 seconds at most" clause (I2).
  - The debt list has the T18, T20, T21 and T30 lines, the SDK listing limit and the `schemas/` packaging, but not
    the retry gap (I3).
  - The gate figures match my run (1371/205).
- **STATUS.md:** accurate. The figures match, and the "Next" line is current.
- **docs/ARCHITECTURE.md §10:** accurate, and the R131 row is updated. (The "Where the code will live (not yet
  written)" table is stale, but that predates this branch.)
- **docs/PROJECT_HISTORY.md §30:** every task's review round is present. Each problem and fix matches the ledger
  (Task 1: 4 minors; Task 2: I1 plus 4; Task 3: I1 plus 7, with the parked catch; Task 4: 4 minors and the R105 risk
  closed; Task 5: I1 plus 5, with 7 tests; Task 6: 2 Important plus minors). It is in a plain human voice. Small gaps
  are listed in M3.
- **reports/:** `t16-asset-sim.txt`, `t16-read-tools.txt`, the refreshed `t15-*` and `r105-walking-skeleton.txt` are
  committed. They hold codes, counts and IDs only, with no secret, token or handle. R105 still cites
  `ALPHA-ALERT-REVIEW:v1:repeated-alerts` under the pump filter.

### Assessment

**Ready to merge? With fixes.** No Critical issues. Three Important issues, all small:
- I1: two JSON fields in tasks.json.
- I2: rewording, plus an owner for the freshness bound.
- I3: a debt line and a docstring correction.

The code's security and authority boundaries hold end to end, and no task undid another task's guarantee. The Minor
issues can go in the same fix wave or be left.

---

# Re-review of the fix wave (`a4e8531..71753ab`)

Verdict: Approved.

- Milestones: `handoff/tasks.json` `current_milestone` is M06 and M05 is DONE; M06 stays PLANNED.
- The "60 s at most" claim survives nowhere: the R028 note, erratum 105, the debt list, T16's note, the backlog and
  the history now say the sweeper's 60-second cadence bounds the lag only while it syncs, and that a read-path freshness
  bound is T20's, subject to erratum 105. The remaining "<=60" hits are the write side's sync and are correct.
- Retryable read failures: `assets.py` no longer claims the job retries; a T20 debt line covers honouring `retryable`
  with a bounded re-queue; both runbooks say a read failure ends the run today.
- The asset-sim alert keying comment, the walking-skeleton revision (0012), the `Unavailable` docstring, the renamed
  limit test and R028's T20 clause are in.
- Search refusals after the scope is known carry `scope.as_of`, pinned by
  `test_a_refusal_in_the_third_unit_carries_the_scopes_instant`.
- Gate counts agree everywhere they are stated (1372/205, 1556/21); `reports/` is unchanged by the wave.
- One Minor: the history's process paragraph omitted the fix wave's own bare `python -` (stopped by task ID, no code
  ran) — added.

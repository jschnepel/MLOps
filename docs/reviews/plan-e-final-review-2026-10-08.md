# Plan E final whole-branch review (2026-10-08)

Branch `plan-e`, range c7c3cca..ac76f02 (Plan E tasks T09 and T10: roles, grants, forced RLS and the definer functions across the four services, the hardened destination
and incident-sim, plus the slice-end handoff docs), reviewed after each of the nine tasks passed its own gate (seven of them after one fix round).
**Verdict: 0 Critical, 3 Important, 12 Minor; ready for the owner after one fix wave and a clean re-review.** The three Important findings were traps for the next plan rather than live defects: a refusal the database maps to Python after SENT became an error envelope instead of UNKNOWN (the lease fence T13 adds raises exactly there); the transition table and the event-type allowlist were generated from live Python when a migration ran, so fresh and upgraded databases could diverge under one revision id; and the claim that a populated revision-1 database upgrades in place rested on reading the code. All three were fixed and tested in one wave (`e8e71a7`, `88f796a`), ten of the twelve minors with them; the re-review found four wording and teardown nits, applied by the controller in the close-out commit.

The sections below are, in order, the reviewer's text (with its appended re-review), the controller's rulings as
recorded in the execution ledger, and the implementer's fix-wave report. Machine-local paths are replaced by
placeholders; nothing else is edited.

---

# Part 1 — Reviewer's report and re-review (unedited)

# Plan E: final review of the whole branch (T09, T10)

Range: `3fb9645..ac76f02` on `plan-e` (22 commits, 65 files, +5919/−1143). Reviewer: final cross-task review covering
correctness and security. The checkout was not modified. The only file written is this report.

Summary: **0 Critical, 3 Important, 12 Minor.** The authority boundary holds end to end. Every write to `runs.state`,
the audit tables, `execution_grant` and `action_attempt_state` happens inside an `app_definer`-owned SECURITY DEFINER
function. The catalog of `ops_test` matches `ops_core.privileges.GRANTS` cell for cell. No runtime role can write,
lock or cross-tenant-read those tables, and the preset-tenant, reused-connection and SENT-before-first-byte behaviours
are pinned by live tests. The Important findings are latent traps and an evidence gap, not live defects. Fix them
before Plan F builds on these seams.

---

## Critical

None.

---

## Important

### I1. After SENT, a mapped persistence error becomes an `error` envelope that is not UNKNOWN, and the worker closes the job

- **Where:** `mcp-write/src/ops_mcp_write/server.py:180-190` (the `except` ladder around `execution.create_incident`)
  and `mcp-write/src/ops_mcp_write/execution.py:104-110`. Also `worker/src/ops_worker/handlers.py:193-199`.
- **What happens:** `record_outcome` runs after the POST, outside the `try`. The comment says "a database failure here
  is a 500 and the replay recovers". That holds only for an *unmapped* `psycopg.Error`. A mapped refusal from
  `record_outcome` or `_read_back` takes a different path:
  - `VersionConflict` (OC003) becomes `STALE_RUN` "run is no longer executing". The comment at `server.py:187` says
    "Nothing was sent", which is false at this point.
  - `HashMismatch`, `Refused` and `NotFound` also become error envelopes.

  The worker treats any envelope that is not `outcome/UNKNOWN` as finished (`handlers.py:195-199`): it calls no
  `mark_unknown`, queues no `recover` job and revokes the handles. The run stays `EXECUTING` with a `SENT` attempt
  while the destination may have committed. Nothing ever reconciles it, so the run is stranded and its slot stays
  held. That breaks the AM-13 rule that after SENT the only results are a recorded outcome or UNKNOWN.
- **Reachability:** none today, because `classify` guarantees the action id and hash `record_outcome` checks. But T13
  and T22 are scheduled to add a lease fence to `mark_sent` and `record_outcome`, and a stale fence raises OC003.
  That is exactly this path. The parked residual "the lease fence for mark_sent/record_outcome" lands straight on it.
- **Fix:**
  - In `execution.create_incident`, wrap the post-SENT `record_outcome` unit and `_read_back` so any
    `persistence.PersistenceError` (and `IllegalTransition`/`EventRuleViolation`) is logged and returns
    `destination.unknown(...)`. An alternative is to re-raise it unmapped so the worker re-queues and the replay
    resends under the same action id.
  - In `server.py`, keep the `STALE_RUN`/`HASH_MISMATCH` mapping only for the pre-SENT units, and correct the comment.
  - Add a live test: monkeypatch `persistence.record_outcome` to raise `VersionConflict` after a real POST, then assert
    the envelope is `outcome/UNKNOWN`.

### I2. `app.transitions` and the event-type allowlist are frozen from live Python at migration time, so applied databases drift silently

- **Where:**
  - `migrations/app/versions/0002_roles_grants_rls.py:20, 324-338, 344`: `transition_rows()` reads
    `ops_core.states.TRANSITIONS` when the revision runs.
  - `migrations/app/versions/0003_run_path_functions.py:19, 30-38, 89`: `EVENT_TYPES` inlines `ops_core.outcomes.EventType`
    into `_append_event`'s body.
  - `tests/plan_e/test_transitions_table.py:1-3, 25-32, 106-111`.
- **What happens:** both lists are computed from the *current* Python when Alembic runs.
  - A database migrated today keeps today's rows forever.
  - A fresh database migrated after a later edit to `TRANSITIONS` or `EventType` gets the new rows from the same
    revision ids.
  - Upgraded and fresh databases then differ, and nothing notices. The unit tests compare the generator with the Python
    table, both evaluated at test time, so they always pass.
  - No live test compares `SELECT * FROM app.transitions` (or the function body) with the Python table.

  The module docstring's claim that "the SQL mirror cannot drift from the T07 table" is not true across revisions. It
  also contradicts the plan's own frozen-revision principle (round-2 NI5 and round-3 N1), which the same revision
  applies to `TABLES` and `GRANTS_0002`. The R082 "one table" invariant would break silently the first time T21 or T22
  edits a row or adds an event type.
- **Fix:**
  - Freeze both lists as literals inside 0002 and 0003, the way `TABLES` and `GRANTS_0002` are frozen. A later change
    then ships as a new revision.
  - Change the unit test to "the newest revision's literal rows equal the live Python table", in the same shape as
    `test_the_newest_revision_of_every_cell_equals_the_live_matrix`.
  - Add one live assertion in `test_definers_run_path_live.py` that the rows of `app.transitions` equal `TRANSITIONS`.

### I3. R006's "old-schema compatibility" is claimed but untested; the owner's dev `ops` will be the first populated upgrade

- **Where:** `tests/e2e/test_migrations_and_persistence.py:189-207` and `handoff/acceptance-matrix.json` R006.
  - The matrix row's expected evidence reads "Create empty DB, migrate, rerun safely and test supported old-schema
    compatibility".
  - It is marked `IMPLEMENTED_LOCALLY_VERIFIED` / `RECORDED_LOCALLY_LIVE`.
- **What happens:** the only up/down test starts from whatever the session left in `ops_test` and asserts that
  relations and policies are gone. It never seeds a revision-1 run carrying a proposal, decision, grant, attempt, state
  rows, events and a handle, and never checks that 0002's backfills come out right afterwards. The backfills cover:
  - `tenant_id` through `runs`, `proposals`, `execution_grant` and `action_attempt`;
  - `slot_held`, `next_event_seq` and `run_directory`;
  - the composite keys and the `TRUNCATE` of `invocation_context`.

  It also never checks that the definer functions accept such a run.

  My static reading of the dev `ops` database at revision 0001 (7 Plan-D runs, schema owned by `ops`) is that
  `skeleton.py migrate` will succeed:
  - every backfill reads through a parent that Plan D always populated;
  - each composite key's unique target is created before the key that references it;
  - `run_state_history.seq` used the same `state_version + 1` numbering in Plan D, so `_transition` cannot collide;
  - `incident` 0002's two CHECKs hold, because Plan D only ever wrote COMMITTED keys with a receipt and an incident id;
  - `narrow_connect` grants CONNECT to the six dev login roles and revokes it from `test_harness`, `incident` and PUBLIC.

  The skeleton should then run under the new roles. Plan-D jobs that are claimed but not done stay stuck, which is
  declared T13 debt. That conclusion comes from reading the code, not from a test, and the first real populated
  upgrade is the owner's own data.
- **Fix:**
  - Add a live test:
    1. Downgrade `ops_test` to `0001_walking_skeleton`.
    2. As the superuser, insert one Plan-D-shaped run at every stage: QUEUED with a job, AWAITING_APPROVAL with a draft
       and proposal, and SUCCEEDED with decision, grant, attempt, three state rows, events and a raw handle.
    3. Migrate to `heads`.
    4. Assert the backfilled `tenant_id`s, `slot_held`, `next_event_seq = max(sequence)`, the `run_directory` rows, that
       `invocation_context` is empty, and that `transition_run`, `append_event` and `lookup_action` work on the
       migrated runs.
  - Until that test exists, set R006's `evidence_status` back to partial, or reword its note.

---

## Minor

1. **The SQL accepts a "no effect" outcome after SENT without destination proof.**
   `migrations/app/versions/0004_write_path_functions.py:413-425` and `0003_run_path_functions.py:127-142`.
   - `record_outcome` accepts `FAILED_NO_COMMIT` from a `SENT` attempt with no `tombstone` at all.
   - `_append_event` shape-checks a tombstone only when one is present.
   - The Python `ActionOutcome` model requires the tombstone, so the shipped path is safe.
   - This is the one AM-13 guarantee ("nothing after SENT is reported as no effect") with no SQL backstop.
   - Fix: `IF p_outcome = 'FAILED_NO_COMMIT' AND jsonb_typeof(p_document->'tombstone') IS DISTINCT FROM 'object' THEN
     RAISE … OC005`.
2. **Revision 0002 still reads the live matrix in three places**, against N1/NI5:
   - `schema_usage_statements()` with its live `MAIN_GRANTEES` default (`0002:348`);
   - `grant_statements`' REVOKE list from live `GRANTEES` (`core/src/ops_core/privileges.py:195`);
   - the downgrade's `REVOKE … FROM {MAIN_GRANTEES}` (`0002:366-367`).

   A role added later changes what an applied revision runs. A REVOKE naming a role that does not exist yet fails.
   Fix: pass frozen role tuples, as is already done for `POLICY_ROLES_0002`.
3. **`jobs.available_at` is stamped by the wall clock while claims compare against `app.current_time()`.**
   - The definer functions insert jobs with the column default `now()`: `0003:278-279`, `0004:221-223` and
     `0004:499-501`.
   - Ruling 24 and the Clock constraint keep `now()` only for `created_at`/`updated_at`.
   - With a negative test offset, a freshly created job is not claimable.
   - Fix: set `available_at = app.current_time()` in those three INSERTs.
4. **Two live tests skip silently.**
   - `tests/e2e/test_definers_run_path_live.py:339-340`: `test_function_catalog_shape` still does `if name not in rows:
     continue  # Task 4's functions arrive with revision 0004`, and its last assertion is a subset. A function dropped
     by a later revision passes. Make it `assert set(rows) == set(DEFINER_FUNCTIONS) | set(HELPER_FUNCTIONS)`.
   - `tests/plan_e/test_transitions_table.py:75-80`: the `if (VERSIONS / …).exists()` filter has the same silent-skip
     shape for a renamed or deleted revision.
5. **The detective check is never run as a command.**
   - `scripts/skeleton.py:229-247` (`keys`: two connections, two queries, exit status) is not executed by any test.
   - R105 only checks its own key through `orphan_keys` (`tests/e2e/test_r105_walking_skeleton.py:190-197`), which is a
     one-line comprehension.
   - Fix: call `keys()` against a database pair holding only matched keys and assert 0, then plant one orphan and
     assert 1.
6. **Handoff records are inaccurate in a few places.**
   - `handoff/tasks.json:513` and `handoff/BUILD_BACKLOG.md:53` list `claim_job` among the shipped *definer functions*,
     but it is a plain UPDATE in `persistence.py`. They omit `revoke_handles`.
   - The same notes and `SESSION_STATE.md:197` say "`claim_job` relies on the from-state under `FOR UPDATE` rather than
     an expected version (by design, ruling 5)". The ledger's ruling (Task 3 M3) was about `transition_run`'s NULL
     `expected_version`, not `claim_job`.
   - The "untested branches" list names FAILED_NO_COMMIT, but the INTENT case is tested
     (`test_definers_write_path_live.py:643-663`). The untested case is FAILED_NO_COMMIT from SENT.
   - STATUS and SESSION_STATE cite the range `c7c3cca..667690c`. As a git range that excludes `c7c3cca` and omits
     `ad3f27e`/`ac76f02`. Use `3fb9645..ac76f02`.
7. **R098's matrix row contradicts itself.** `evidence_status` is `RECORDED_LOCALLY_LIVE`
   (`handoff/acceptance-matrix.json:1530`), but its note (commit `ac76f02`) says the evidence is unit-level. Use
   `RECORDED_LOCALLY`, or name the live test.
8. **The runbook has one stale line and one missing recovery step** (`docs/runbooks/walking-skeleton.md`).
   - Line 45 says the R105 run "stay[s] in the dev database". R105 now runs against `ops_test`, which every live
     session drops, so the run ids in `reports/skeleton/r105-walking-skeleton.txt` exist nowhere after the next run.
   - Nothing tells an operator how to recover a dev database that was migrated under `PROFILE=test`, which `up` then
     refuses. The recovery is `downgrade("app", …, "testclock@base")`, and there is no CLI verb for it.
9. **The `claim_job` docstring contradicts the code.** `core/src/ops_core/persistence.py:474-476` says the tenant left
   set "the worker's handler relies on". `run_forever` commits the claim transaction (`worker/src/ops_worker/main.py:46-48`),
   and every handler unit sets its own tenant. Delete the clause.
10. **Both MCP servers duplicate the new lifespan logic and still leak a connection if JWKS loading fails.**
    - The new connect, `assert_clock_profile`, close-on-failure block is duplicated in
      `mcp-read/src/ops_mcp_read/server.py:206-216` and `mcp-write/src/ops_mcp_write/server.py:212-232`.
    - Both still leak the connection when `load_keys` fails at start (parked residual).
    - A `persistence.connect_as(role, profile)` helper in `core` that asserts the clock and closes on any failure would
      remove the duplication. Moving `load_keys` inside the guarded block would fix the leak in both servers at once.
11. **Docstrings are missing on new public code** (CODE_COMMENTS rule 9):
    - `incident-sim/src/ops_incident_sim/app.py`: `Store.abort`/`reject`, `DbStore.abort`/`reject` (lines 40-63), the
      `abort_action` and `arm_fault` routes (213, 231);
    - `upgrade`/`downgrade` in 0002, 0004, `tc_0001` and incident 0002 (0003 has them).
12. **Role passwords are sent as bind parameters to `set_config`** (`scripts/skeleton.py:78-80`). With
    `log_statement = 'all'`, or a statement error with `log_parameter_max_length_on_error` enabled, the server log
    records the password. The image's defaults avoid this, but the plan constraint ("no secret in a log line") then
    depends on configuration. The pattern predates this branch (Plan D used it for `incident`) and now covers eight
    roles. Fix: `SET log_parameter_max_length = 0` and `SET log_statement = 'none'` on the bootstrap connection first;
    the superuser is allowed to set both.

---

## Declined to judge

Each item was considered and set aside, with the reason:

- The lease fence on `mark_sent` and `record_outcome`: either mcp_exec session can step any action by `action_id`.
  This is on the debt list and parked to T13/T22.
- `append_event(run_id, …)` takes no tenant, so api, worker or sweeper can append non-reserved events to any tenant's
  run. This is the AM-20.3 signature, with the API as the identity trust anchor (SA:450).
- RLS rests on a GUC the caller can set, so a compromised `api` or `worker` can read any tenant. This is the AM-20.5
  design, which isolates against bugs, not against a compromised trusted role.
- A refused grant (MEMBERSHIP_INACTIVE, CANCELLED, NO_APPROVAL) leaves the run APPROVED and holding its slot instead
  of moving to BLOCKED_REVIEW. Parked by Plan D to T21/T22, and unreachable today.
- `mark_sent → 'cancelled'` returns UNKNOWN, after which `mark_unknown` leaves OUTCOME_UNKNOWN with an unhandled
  recover job. This is `TODO(T22)` and debt, and there is no cancel route today.
- The worker re-queues every 30 s without bound on `McpCallFailed`, and a failed `mark_unknown` leaves the job
  claimed. `TODO(T13)` covers bounded retries and reclaim.
- One connection per process with no reconnect: the pool is T13.
- `run_directory` and `tenants` are readable across tenants. SA:523 declares them RLS-free.
- `_resolve_handle` does not check that the job's `run_id` equals the handle's `run_id`. The worker is the trusted
  minter and can insert jobs itself, so this check would add nothing.
- PUBLIC still has CONNECT on the cluster's `postgres` maintenance database. That database is outside the plan; no
  application data is reachable there.
- Foreign tombstones are classified as CONFLICT or UNKNOWN, and the service token is fetched after SENT. Both are
  parked by Plan D to T22.
- Under `PROFILE=test`, `up` against a dev database exposes the fault routes. The guard is one-directional by SA:528,
  and this needs operator misuse of the environment.
- T09 is DONE while R122 is deferred. Ruling 2 decided this.
- API `Internal` answers 503 rather than 500. Ruled in Task 6 fix round 1.
- Markdown prose lines over 120 characters, and the `superpowers` path segments. Ruled acceptable in the Task 2 and
  Task 9 reviews.
- The lines over 120 characters in `compose.yaml:68` and `pyproject.toml:48` predate this branch (`f864197`, `7df6aa2`).
- Test-helper cleanup leaks and the R006 post-downgrade assertions: parked residuals (I3 covers the part that matters).
- The duplicated `serve_app` helpers and MCP envelope code predate this plan (Plan D ruling 23 and ADR-0001).

---

## What I ran

- **git (read-only):** `log --oneline` and `--format=%B` over `3fb9645..ac76f02`, which found no `Co-Authored-By`,
  attribution or session trailer in any of the 22 commits. Also `diff --stat`, full `diff`, `show`
  and `blame`.
- **Scans of the diff and changed files:**
  - secret patterns (`password=`, JWT `eyJ…`, private keys): none;
  - vendor and tool names in added lines: only the accepted `superpowers` paths and the existing Ollama runbook
    reference;
  - CRLF, BOM and lines over 120 characters (counted in characters): none introduced;
  - public defs without docstrings (`ast` scan);
  - `TODO` without a task id, `noqa`, `type: ignore`: none;
  - `reports/skeleton/r105-walking-skeleton.txt` read in full: ids, hashes and statuses only, no token or secret.
- **PyJWT (installed `api_jwt.py`):** the claim order is exp, then iss, then aud. So an expired or foreign-issuer token
  stays 401 and only a genuine token for another audience becomes 403.
- **`uv run python -m pytest --collect-only -q`:** 608 collected. This matches STATUS (529+79, and 587+21).
- **`uv run python -m pytest tests/plan_e -q`:** 76 passed (database-free; no live test was run, because the e2e
  fixture drops, recreates and migrates the test databases).
- **Read-only catalog queries on `ops_test`** as the superuser, through a scratchpad helper that reads the secret file
  without printing it and rolls back. Results:
  - **Roles:** login, superuser and BYPASSRLS attributes are as pinned, and no role memberships exist.
  - **Database ACLs:** `ops_test` grants CONNECT to exactly the seven test-profile roles; `incident_test` to
    `incident` only. The dev `ops` (default ACL) and `incident` (`=Tc`) are untouched, as expected before the owner's
    migrate.
  - **Schema ACLs:** `app` is owned by `migrator`, with USAGE for the grantees only.
  - **Every function in `app`:** owner, `prosecdef`, `provolatile`, `proconfig` and ACL. Every granted function carries
    `app.tenant_id=` and no helper does. No PUBLIC entry; the grantees match `DEFINER_FUNCTIONS`.
  - **Every relation in `app`:** owner `migrator`, the RLS and FORCE flags, and `relacl`.
  - **Column UPDATE privileges** for every runtime grantee.
  - **`pg_policy`:** quals and roles.

  All of these equal `ops_core.privileges` cell for cell.

---

## Verdict

**Ready for the owner, with I1–I3 fixed before Plan F builds on these seams.** The pieces the brief asked me to
trace are sound:

- the role and grant matrix;
- FORCE RLS with the NULLIF policy;
- the preset-tenant attribute plus transaction-local `set_config`;
- `transition_run`'s ACL and authority check;
- grant-once-per-run with replay under one action id;
- SENT committed before the first byte (witnessed live);
- UNKNOWN recorded only by the worker;
- the destination's permanent keys, which the `incident` role can only INSERT and SELECT;
- 403 for foreign tokens;
- fault hooks that exist only under `PROFILE=test`;
- `up` refusing when `app.test_clock` exists.

The owner's next dev `migrate` should succeed on the populated revision-1 database. That conclusion is from reading
the code, and I3 asks for the test that proves it. None of the Important findings is a live defect today:

- I1 becomes one the moment T13/T22 add the lease fence;
- I2 the first time the transition or event table changes;
- I3 is missing evidence behind a claim in the acceptance matrix.

Each needs a small, contained change. The Minor findings can travel with Plan F's first task.

---

# Part 2 — Controller rulings (ledger excerpt)

```text
Final review (opus) over 3fb9645..ac76f02: 0 Critical, 3 Important, 12 Minor; verdict "ready for the owner, fix I1–I3 before Plan F". Report final-review.md.
Rulings: fix I1 (post-SENT mapped errors → UNKNOWN envelope, never an error envelope; STALE_RUN/HASH_MISMATCH stay for the pre-SENT units; live test), I2 (freeze the transition rows and the event-type list as literals in 0002/0003, unit test "newest revision literals == live Python", live assertion app.transitions == TRANSITIONS), I3 (a populated revision-1 → heads live upgrade test seeding Plan-D-shaped rows; the owner's dev database is exactly this case), M1 (tombstone required for FAILED_NO_COMMIT in SQL), M2 (frozen role tuples for the schema-usage and REVOKE lists), M3 (available_at = app.current_time() in the three job INSERTs), M4 (strict catalog equality; the revision filter asserts all four exist), M6/M7/M8/M9/M11 (records, R098 → RECORDED_LOCALLY, runbook stale line + recovery one-liner, claim_job docstring, docstrings), M10's leak half (load_keys inside the guarded block in both MCP servers), M12 (log_parameter_max_length = 0 and log_statement = 'none' on the bootstrap connection). Parked: M5's zero-orphan case (needs clean databases; the planted-orphan case runs), M10's helper refactor (→ T13 with the pool). One fix dispatch, then one scoped re-review.
Final fix wave (opus): e8e71a7 (code+tests+evidence), 88f796a (records); unit 149, e2e 52, check.py 530 / 82, --profile test 591 / 21, verify_handoff 0. Scoped re-review (opus) dispatched.
```

---

# Part 3 — Fix-wave report

# Plan E: final-review fix wave

Branch `plan-e`, base `ac76f02`. Commits: `e8e71a7` (fix: code, tests, regenerated r105 report) and `88f796a` (docs:
records). Nothing pushed. No `docker compose down`, no manual `skeleton.py migrate`/`up`. `reports/bootstrap` restored
after every live run. No attribution trailers.

## Per item

**I1. Post-SENT refusals answer UNKNOWN.**
- `mcp-write/src/ops_mcp_write/execution.py`: new `_POST_SENT_REFUSALS = (persistence.PersistenceError,
  IllegalTransition, EventRuleViolation)`. The `record_outcome` unit after the POST is wrapped; a refusal is logged
  with `log.exception` (action id only) and returns `destination.unknown(action_id, payload_sha256)`. `_read_back`
  (used by both read-back calls) catches the same tuple after its `HandleRejected` branch. An unmapped `psycopg.Error`
  still escapes (500, the worker's replay resends under the same action id), as the comment now says.
- `mcp-write/src/ops_mcp_write/server.py`: STALE_RUN/HASH_MISMATCH mappings kept; the comment now says only
  `grant_execution`/`mark_sent` (pre-SENT) can raise there.
- Live test `tests/e2e/test_mcp_write_live.py::test_refusal_after_a_real_post_is_unknown_not_an_error`: real POST to
  the in-process sim on 18090, `persistence.record_outcome` monkeypatched to raise `VersionConflict("x")`; asserts
  `outcome_envelope(...)` is `status == "outcome"`, `error is None`, `data.status == "UNKNOWN"`, run `EXECUTING`, last
  attempt state `SENT`. Red-checked: with `HEAD:execution.py` restored the test fails; with the fix it passes.

**I2. Frozen lists.**
- `migrations/app/versions/0002_roles_grants_rls.py`: `TRANSITION_ROWS_0002` literal (44 rows, generated once from the
  current `TRANSITIONS`, sorted by (src, dst, performer), `None` for the creation edge, reasons sorted).
  `transition_rows()` reads it and keeps the word guard; the `ops_core.states` import is gone.
- `migrations/app/versions/0003_run_path_functions.py`: `EVENT_TYPES_0003` literal (27 values);
  `event_type_list()` keeps the pattern guard; the `ops_core.outcomes` import is gone. (`ops_core.privileges` is still
  imported by both revisions, for the renderers and `Grant`; only the two named imports were dropped.)
- `tests/plan_e/test_transitions_table.py`: `newest_literal(prefix)` scans `REVISIONS` in order and takes the last
  `TRANSITION_ROWS_*` / `EVENT_TYPES_*`; `test_the_newest_revision_of_the_transition_rows_equals_the_live_table` and
  `test_the_newest_revision_of_the_event_types_equals_the_live_enum` compare with `TRANSITIONS` / `EventType`. The
  generator-shape test now counts against the frozen rows. Module docstring rewritten (the "cannot drift" claim is
  gone).
- Live: `tests/e2e/test_definers_run_path_live.py::test_the_transitions_table_equals_the_python_table`
  (`SELECT src, dst, performer, reasons FROM app.transitions` equals the Python table, `''` for a None src, reasons
  sorted).

**I3. Populated upgrade.** `tests/e2e/test_migrations_and_persistence.py::test_r006_populated_revision_1_database_upgrades_in_place`
with helpers `seed_revision_1_run`, `seed_revision_1_proposal` and `CHILD_ROWS`. Downgrades `testclock@base` then
`0001_walking_skeleton`; as the superuser seeds on ALPHA (ALEX requester, SAM reviewer), revision-1 columns only: a
QUEUED run + investigate job + raw handle; an AWAITING_APPROVAL run + draft + proposal (`active_proposal_id`) + two
events; a SUCCEEDED run + draft + proposal + decision + done execute job + grant + attempt 1 + INTENT/SENT/RESOLVED + six
events up to `action.confirmed`; each with Plan-D-numbered history. Then `migrate(Profile.TEST) == 0` and asserts:
`tenant_id = ALPHA` on every seeded row of the seven child tables (and at least one row each); `slot_held`
True/True/False; `next_event_seq == max(sequence) == [1, 2, 6]`; a `run_directory` row with ALPHA for each run;
`invocation_context` empty. Then worker `transition_run(QUEUED→RETRIEVING)` returns version 2; api `append_event`
returns sequence 3; worker mints a write handle for the SUCCEEDED run's execute job and mcp_exec `lookup_action`
returns that action with `attempt_state == "RESOLVED"`. `finally` purges the three runs. R006's matrix row left as is.
An execute job had to be seeded for the SUCCEEDED run (the brief lists jobs only for the QUEUED run) because
`mint_handle` binds a handle to a job.

**Minors.**
- M1 `0004` `record_outcome`: `IF p_outcome = 'FAILED_NO_COMMIT' AND jsonb_typeof(p_document->'tombstone') IS
  DISTINCT FROM 'object' THEN RAISE … OC005 INVALID_ARGUMENT`, after the status check. Live cases (tombstone `null` and
  key absent) in `test_definers_write_path_live.py::test_stale_mark_sent_and_early_outcome_are_refused`.
- M2 `core/src/ops_core/privileges.py`: `grant_statements(tables, grants, *, revokees=None)`; `None` keeps today's
  behaviour. 0002 passes `MAIN_GRANTEES_0002` to `schema_usage_statements`, to `grant_statements(revokees=…)` and to the
  downgrade's two REVOKEs. Unit assertion that it equals the live `MAIN_GRANTEES`.
- M3 `create_run` (0003), `record_decision` and `mark_unknown` (0004) insert `available_at = app.current_time()`.
- M4 `test_function_catalog_shape` asserts `set(rows) == DEFINER ∪ HELPER` first, no `continue`; `REVISIONS` is a
  literal tuple followed by a module-level `assert` that all four files exist.
- M6 `handoff/tasks.json`, `handoff/BUILD_BACKLOG.md`, `STATUS.md`, `SESSION_STATE.md`: `revoke_handles` replaces
  `claim_job` in the definer list; the expected-version note is about `transition_run` with a NULL
  `expected_version` (Task 3 review M3); "FAILED_NO_COMMIT from SENT"; range `3fb9645..e8e71a7`. Also removed the
  JWKS-leak debt line (M10 fixed it), added the populated R006 test to the evidence, and updated the gate counts.
- M7 R098 `evidence_status` → `RECORDED_LOCALLY`.
- M8 runbook: R105 runs against `ops_test`, its ids do not survive the next session; recovery paragraph for a dev
  database migrated under `PROFILE=test`.
- M9 `claim_job` docstring clause deleted.
- M10 both MCP lifespans: `load_keys()` moved inside the `try` whose `finally` closes the connection (mcp-write also
  closes its HTTP client). No helper refactor.
- M11 docstrings: `Store.abort/reject`, `DbStore.abort/reject`, `abort_action`, `arm_fault`; `upgrade`/`downgrade` in
  0002 (upgrade, downgrade), 0004, `tc_0001`, incident 0002.
- M12 `scripts/skeleton.py ensure_roles`: `SET log_parameter_max_length = 0`, `SET log_parameter_max_length_on_error =
  0`, `SET log_statement = 'none'` first on the bootstrap connection, with the why-comment.
- `docs/PROJECT_HISTORY.md` §20: Problem/Change pair for this review round (standing instruction).

## Commands

- `uv run ruff format <touched .py> && uv run ruff check --fix <touched .py>`: 5 reformatted, all checks passed.
- 120-character count over the touched `.py` files: printed nothing. No CR in touched files.
- `uv run python -m pytest tests/plan_e tests/plan_d -q`: 149 passed.
- `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e -q`: 52 passed (all four new/changed live tests
  collected and passing). `git checkout -- reports/bootstrap` afterwards.
- Red check: `HEAD:execution.py` restored temporarily, `pytest tests/e2e/test_mcp_write_live.py -k refusal_after`:
  1 failed; fix restored.
- `PYTHONUTF8=1 uv run python scripts/check.py`: CHECK GREEN, 530 passed, 82 skipped (before and after the docs).
- `PYTHONUTF8=1 uv run python scripts/check.py --profile test`: CHECK GREEN, 591 passed, 21 skipped (run so the
  recorded profile-test counts are current; it regenerated the r105 report, committed in `88f796a`).
- `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`: exit 0 (before and after docs).

## Deviations

- M2: the brief named `GRANTEES_0002` and `MAIN_GRANTEES_0002`. Only `MAIN_GRANTEES_0002` is defined and used: 0002
  touches no test-only table, so the role set it revokes from is exactly the main-line grantees (what the old code
  computed), and a tuple including `test_harness` would name a role that does not exist in dev and fail the REVOKE.
  An unused constant would be dead code.
- M8: the brief's command used `load_dotenv('.env')`; `load_dotenv` calls `.exists()` on a `Path`, so a `str` raises.
  The runbook uses `load_dotenv()` (default `Path(".env")`); the imports were checked.
- M12: also sets `log_parameter_max_length_on_error = 0` (the review's error-path case); harmless and on point.
- I3: seeded an `execute` job (done) for the SUCCEEDED run so a write handle can be minted for `lookup_action`.
- Two tests renamed rather than edited in place (`…event_type_allowlist_lists_every_event_type_once` →
  `test_the_newest_revision_of_the_event_types_equals_the_live_enum`; the transition comparison is a new test and the
  shape test stays).

## Concerns

- `tc_0001_test_clock.py` still renders from live `privileges.TEST_ONLY_ROLES` (not in this wave's scope; same class
  as M2).
- The populated test, if it fails between downgrade and migrate, leaves `ops_test` at revision 1 and its `finally`
  purge will error; the next session recreates the database.

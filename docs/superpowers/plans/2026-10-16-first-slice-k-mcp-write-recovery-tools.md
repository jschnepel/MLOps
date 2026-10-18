# First Slice K: The Authenticated mcp-write and Its Recovery Tools (T47) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish mcp-write as T47's authenticated write server: its token checks at mcp-read's level, the worker's
client named once, the write-path functions bound to the presented token's `azp`, the dispatch deadline and the abort
request in the database, the attempt-state dimension of the allowlist, and the two recovery tools with full bodies,
proved over HTTP against a real incident-sim and from an independent process (T47; R030, R131 write half, the write
halves of R025 and R031).

**Architecture:** The server side of recovery only (ruling 1): every tool body, every definer it calls and every
refusal, proved by staging jobs, handles and destination faults directly; the worker's recover loop stays T22's. One
setting, `OPS_WORKLOAD_CLIENT_ID`, names the worker's client for its token source and both verifiers, and
`write_verifier` gives mcp-write mcp-read's three token rules. Revision `0010_write_path` re-creates `grant_execution`,
`lookup_action`, `mark_sent` and `record_outcome` with the token's `azp` as their second argument, gives `mark_sent` the
300 s dispatch deadline (`app._dispatch_seconds()`) and an `abort_requested` answer, lets `record_outcome` accept a
receipt after an abort requested after SENT (reason `deadline`), and adds `request_abort`, which chooses the abort's
reason under the runs lock; the downgrade re-runs 0004's and 0007's applied bodies. `persistence.allowed_tool` gains the
attempt state (`jobs.ATTEMPT_STATES`). `get_incident_receipt` is one GET of the action's key and `abort_incident` one
abort POST after `request_abort`, both recorded through `record_outcome`; `create_incident` aborts a cancelled or
expired attempt itself. The abort tool's result schema gains UNKNOWN and CONFLICT. `docs/threat-model.md` states that v1
trusts mcp-write for outcome truth.

**Tech Stack:** as Plan J; no new dependency. `mcp` 2.3.0 and `mcp-types` 2.3.0 (`MCPServer`, `Client`, the bearer
middleware), Starlette 1.7, `httpx2` 2.13 (`MockTransport`, `ASGITransport`), FastAPI (incident-sim), PyJWT 2.15,
psycopg 3.3, PostgreSQL 17, Alembic, Python 3.13.

**Spec:** `SPEC_AMENDMENTS.md` (OPS-BUILD-1.3.6) over `BUILD_SPEC.md`: AM-13 (SA:220-299: who calls the destination,
the attempt protocol, the recovery table, cancellation, the destination's keys and tombstones, the outcome vocabulary,
the defaults), AM-15 (SA:327-358: the three write tools, job types, the envelope), AM-20.3's rows for
`resolve_invocation`, `grant_execution`, `mark_sent`, `record_outcome`, `request_abort` and `lookup_action`
(SA:459-466), AM-20.7 item 6 (SA:554-558), AM-30 (SA:568-591); BS §10 (BS:376-407, BS:393 the reconciliation-only
tool), §13 and §14 (BS:462-506). The fact sheet `docs/superpowers/research/2026-10-16-plan-k-inputs.md` (cited "FS §n"
/ "FS Qn") and the controller's brief of 27 rulings (cited "ruling n"; reproduced below with what this plan made of
each) are the inputs. Earlier artefacts this plan builds on: revisions 0001-0009, `ops_core.persistence`, `jobs`,
`privileges`, `settings`, `tokens`, `outcomes`; mcp-write, mcp-read and incident-sim as Plans D-J left them; the
worker's `main`; `scripts/build_schemas.py`; the `tests/e2e/` fixtures and the Plan C-J unit tests.

## Global Constraints

Carried from Plan J's header (its text applies with "Plan J"/"T15" read as the plan that wrote it); the Plan K
additions below win where the two differ:

- **Debt before code (SA:698).** The Plan K debt list (below) is committed in Task 1 Step 1c before any code changes.
  Nothing not on the list may be shortcut; every line names its owning task.
- **Authority boundaries stay where the spec puts them.** `mcp_exec` holds no table grant and EXECUTE on exactly
  `current_time`, `resolve_invocation`, `grant_execution`, `mark_sent`, `record_outcome`, `request_abort` and
  `lookup_action` (a unit test in Task 2, a live test in Task 4); no MCP server creates a job (Plan I's catalog test
  stays green, `request_abort` included); every refusal of a presented handle is one `INVALID_HANDLE` envelope with the
  one fixed message and never an `action_id`; every refusal before a destination call is a plain error envelope
  without an `action_id`; after a destination call the only answers are a recorded outcome or UNKNOWN; token refusals
  stay HTTP 401 at both MCP servers. **The no-unapproved-external-action boundary:** every POST to
  `/internal/incidents` happens only after `grant_execution` committed a grant for an approved proposal, SENT is
  committed before it, and an abort never creates an incident. **Nothing here sends anything to an external system or
  a person** (BS:730): incident-sim is the synthetic destination.
- **Secrets** live only as files under `OPS_SECRETS_DIR`. No secret, token, raw handle, session id or password in an
  environment variable, a command line, a log line, an exception message, an assertion operand, an evidence file or a
  document. A test that checks a handle or token is absent from text binds the verdict to a boolean first, so a
  failure never prints the value. The child process of Task 5 gets its secrets the way the skeleton's children do: the
  environment names the secrets directory, the files hold the values.
- **Clock.** Every lease, expiry, fence and dispatch-deadline comparison in SQL uses `app.current_time()`, after the
  lock it depends on. A test that moves `app.test_clock` does so only while no other lease matters and resets it in
  `finally` (the offset is global); a handle or a lease it needs on the moved clock is minted or taken after the move.
- **One string per function**, binds and the ISC004 rule exactly as in Plan E; `tests/plan_e/test_transitions_table.py`
  scans every revision, 0010 included. Revision 0010 freezes its bodies, callers and signatures and downgrades exactly
  to 0009 by re-running the applied revisions' own bodies (the 0007 pattern).
- **Live tests never touch the dev databases**, run against `ops_test`/`incident_test` under `PROFILE=test` through
  the existing `migrated`, `app_conn`, `role_conn`, `incident_conn` and `secret` fixtures. A server a live test starts
  is stopped in `finally`: uvicorn in-process through `should_exit` (never a cancel), a child process through
  `terminate()` and, after 15 s, `kill()`. A live test reads no backend pid and runs no two connections against one
  lock (none of this plan's does), never cancels a task that may be inside a database unit, and purges its runs only
  after every server it started has stopped.
- **Tests:** unit tests in `tests/plan_k/` (DB-free; added to `testpaths` in Task 1), live tests in `tests/e2e/` gated
  by `OPS_LIVE=1`; existing tests are updated in the task that changes the interface they pin, never deleted (Task 2
  rewrites the write-path call sites of ten modules and one head-signature check; Task 3 moves four allowlist and
  mcp-write tests to the new signatures). No xfail or skip except the live gate. No new test needs `slow_live`.
- **Comments** per `docs/CODE_COMMENTS.md`; ≤120 characters per line (the counting command below); no `type: ignore`;
  ruff + mypy strict clean; UTF-8 without BOM, LF; no `noqa`. The one broad `except` (`execution._ask`) replaces the
  one it was moved from (`create_incident`'s POST), with the same reason: after SENT nothing may escape as "no effect".
- **Gates:** `uv run ruff format <files> && uv run ruff check --fix <files>` (then
  `uv run ruff check --select ISC004 --fix --unsafe-fixes migrations/app/versions/0010_write_path.py` after writing the
  revision), `PYTHONUTF8=1 uv run python scripts/check.py` GREEN after every task,
  `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts` exit 0, and the live suite
  `PYTHONUTF8=1 uv run python scripts/check.py --profile test` after every task (each changes a service, a migration or
  a live test). It needs the dev stack up and `uv run python scripts/skeleton.py status` showing every process down.
  After a live run: `git checkout -- reports/bootstrap reports/skeleton reports/auth reports/admission reports/leases
  reports/events reports/outbox reports/mcp-read` (all eight are rewritten by live runs; `reports/mcp-write` is new and
  stays until Task 6 commits it). mypy's incremental cache can report spurious errors after many edits; rerun with
  `--no-incremental` before treating one as real.
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
  (`uv run python -m pytest …`, never a bare `pytest`); no `uv add`, no `uv lock`. The two inline Python scripts of this
  plan (Task 2 Step 5, Task 6 Step 2) contain no doubled backslash, so a shell or tool that rewrites `\\` cannot change
  them.
- **Never migrate the dev databases.** Nobody runs `scripts/skeleton.py migrate` or `up` against `ops`/`incident` in
  this plan; the live suite migrates its own test databases every session. Migrating the dev database to 0010 is an
  owner input recorded in Task 6; until then mcp-write joins the API, the sweeper, the worker and mcp-read in refusing
  to start on it, by design.
- **Commits:** one logical group per step that says "commit"; messages free of any attribution trailer (owner
  instruction); never push; never `docker compose down -v`; never change system settings; never drop a role,
  database, persona or Keycloak object (the test databases and the round trip's scratch database excepted).
- **No interim red across tasks.** Every task ends with both gates GREEN at the stated counts. The order is chosen for
  that: the verifier and the setting (Task 1) change no database contract; the revision, the persistence wrappers,
  mcp-write's `azp` and every test call site land together (Task 2), because the signature change alone would leave
  every write-path live test red; the allowlist and the tools (Task 3) change no database contract.
- **Line numbers** in "Modify" lines are those of the file as the previous task left it (the current tree for a file
  no earlier Plan K task touched). Every replacement quotes the exact current text ("Edit n (`path`, …), replace:"
  then "with:"); a step that creates a file gives the whole file.
- **Counts.** Today (`320e06d`) the dev gate is `1075 passed, 164 skipped` and the live gate `1218 passed, 21 skipped`
  (143 live-gated tests). Task 1 Step 1a records both before any change; if either differs, every expected count below
  shifts by the same difference and the report says so. Every dev count below was measured by applying this plan to a
  scratch copy of `320e06d`; every live count is arithmetic (the dev count plus the live-gated tests, which are the
  dev run's skips minus the 21 that skip in both), because a dry run cannot run live steps. Each live step says so.

## Review Focus

1. **A re-send that meets a cancel, the deadline or an abort request** (the re-queued execute job after a lost
   reply, or a recover job's `abort_incident` racing it). Every send, the re-send of a SENT attempt included, passes
   `mark_sent`, which under the runs lock answers `abort_requested` once an abort was requested (SA:334), `cancelled`
   or `expired` after a cancel or past the deadline (the tool then aborts, SA:248), and `not_redispatchable` to a
   recover job (SA:345); none writes a row and none is followed by a POST. What is left is the moment between
   `mark_sent`'s commit and the POST itself, which AM-13 has for a first send and a re-send alike. Pinned in Task 2
   (`test_a_re_send_is_checked_as_a_first_send_is` and the `abort_requested` case, live at the definer) and Task 3
   (`test_a_re_send_after_a_cancel_or_past_the_deadline_is_aborted_not_sent`, `test_a_recover_job_never_re_sends`,
   `test_nothing_is_sent_once_an_abort_is_requested`: no POST in any of them).
2. **A renamed worker client.** An owner who renames the realm's worker client and sets `OPS_WORKLOAD_CLIENT_ID` must
   find every place following: the token source, both verifiers, the mint and the five definers. Pinned in Task 1
   (`test_workload_client.py`: the token source and both verifiers) and Task 2
   (`test_every_write_path_definer_compares_the_presented_azp`: a handle minted for a renamed client refused with the
   old name and accepted with its own at every definer).
3. **A recovery call naming another proposal.** The handle decides the run, but the tool's `proposal_id` must still be
   the grant's (SA:538); a caller confused about which proposal it recovers must get a refusal, not another action's
   outcome. Pinned in Task 3 (`test_a_recovery_call_for_another_proposal_is_refused_before_any_call` and the
   `OTHER_PROPOSAL` envelope case).
4. **A lookup without a key read as "no commit".** A 404 (a delayed receipt), a 429 or a lost reply at the receipt
   lookup must stay UNKNOWN and unrecorded (SA:269). Pinned in Task 3 (four scripted replies; a 429 built through a
   real request against `httpx2.MockTransport`) and Task 4 (`delay_receipt` live).
5. **A dev database left at 0009.** mcp-write calls the new signatures; on 0009 every call would fail at run time, so
   it must refuse to start. Pinned in Task 2 (`test_mcp_write_startup.py` both ways; the live round trip refuses as
   `mcp_exec` at 0009 and passes at the head).

## Rulings (the brief's 27, as this plan implements them)

The controller's brief decided these; executors do not re-litigate them. Each line says where the plan implements the
ruling and, where the plan had to refine one against the code, says how (all refinements are repeated under "Rulings
needing controller attention").

1. **Tools** — `create_incident`, `get_incident_receipt` and `abort_incident` registered with full bodies: the GET and
   abort clients (`destination.get_action`, `post_abort`), the classification, `record_outcome` (Task 3); no worker
   caller (T22, debt line).
2. **`request_abort`** — created in revision 0010 (Task 2) with two callers, `abort_incident` and `create_incident`'s
   cancelled/expired branch (Task 3). Refined (a).
3. **Its signature and reason** — the handle and fence binding of `mark_sent`; the reason is chosen on the server
   side, never by the worker: `cancelled_before_send` (INTENT, cancelled), `expired` (INTENT, past the deadline),
   `deadline` (SENT, past the deadline or cancelled); the run's FAILED reason is `cancelled_before_send`/`expired` from
   INTENT and `aborted_no_commit` after SENT (erratum 87). Refined (a): the function chooses the reason and takes none.
4. **Attempt-state allowlist** — in Python: `allowed_tool(job_type, run_state, attempt_state, tool)` with
   `jobs.ATTEMPT_STATES` (Task 3): execute/`create_incident` none, INTENT, SENT; recover/`create_incident` INTENT;
   recover/`get_incident_receipt` SENT, ABORT_REQUESTED, RESOLVED; recover/`abort_incident` INTENT, SENT,
   ABORT_REQUESTED. "Not cancelled, before the deadline" stays in `mark_sent`. `resolve_invocation` already returns the
   attempt state (`_resolve_handle` reads it, FS §3.6) and now converts it to `AttemptState` for the check. Erratum 84.
   Refined (d).
5. **The SENT re-send** — kept for execute jobs (the table row above), and checked as a first send is: since round 1
   it passes `mark_sent` too, which answers `cancelled`/`expired` after a cancel or past the deadline (the tool aborts
   instead) and `not_redispatchable` to a recover job (Tasks 2 and 3); proved live over HTTP (Task 4). Erratum 84.
6. **Redispatch** — `mark_sent`'s EXECUTING guard stays; a recover job's `create_incident` on INTENT passes the
   allowlist and is answered `STALE_RUN` while the run is OUTCOME_UNKNOWN (live, Task 4); redispatch, attempt row 2 and
   `action.redispatched` → T22 (debt line).
7. **`record_outcome` after an abort request** — SUCCEEDED and CONFLICT accepted when the latest state is SENT, or
   ABORT_REQUESTED with the reason `deadline` (an abort that followed SENT; narrowed in round 1: after an abort of an
   attempt never sent they stay refused) (revision 0010, Task 2; live in Task 2 both ways and Task 4). Late evidence
   after RESOLVED → T22 (debt line). Erratum 86.
8. **R030 evidence** — live (Task 4): an execute and an investigate handle refused at both recovery tools, a recover
   handle of an APPROVED run (no grant) refused at all three by the run-state rule (a run in a recover state without a
   grant cannot arise through the definers: only `grant_execution` leaves APPROVED for EXECUTING), a recover handle
   answered with the minimal `ActionOutcome`; `execution_grant`, `action_attempt`, `jobs` and `proposals` counts
   unchanged around the lookups and around an abort, and only `RESOLVED` added to the attempt's states; mcp-write's
   destination calls counted in-process (GETs only for the lookups); the action's key unchanged by the lookups and the
   destination's global key count up by exactly the abort's tombstone.
9. **Discovery** — all three tools listed to the authenticated caller (Task 3's in-process list, Task 5's child
   process); refusal per handle. Erratum 90.
10. **Envelopes** — a refused handle at any tool is the plain `INVALID_HANDLE` (Task 3 unit, Task 4 live); a 404 or a
    429/503 is `outcome`/UNKNOWN with the action id (Task 3, Task 4); `abort_incident`'s data is the schema's
    `{action_id, outcome, receipt, tombstone}` (`server.abort_envelope`); the tombstone carries the destination's
    token, and the schema's example now says `cancelled_before_send` (Task 3). Refined (b).
11. **Verifier parity** — `write_verifier(kc, urls)`, used by `production_app` and the unit tests:
    `token_type="Bearer"`, `McpVerifier`'s audience check before the stamp, `validate_token_resource=True`; mcp-read's
    unit cases at mcp-write (`tests/plan_k/test_verifier_t47.py`, Task 1). `McpVerifier` stays per service.
12. **The worker's client named once** — `settings.workload_client_id()` (`OPS_WORKLOAD_CLIENT_ID`, default
    `ops-worker`), read by the worker's token source (`main.token_source`) and both verifiers (Task 1); revision 0010
    re-creates the four definers with `client_azp` and creates `request_abort` with it (Task 2). Erratum 83.
13. **R131 ACL** — live equality of `mcp_exec`'s EXECUTE set with the seven functions, every other `app` function
    present and not executable, an attempted `mark_unknown` → `42501` (Task 4; the matrix's set also a unit test in
    Task 2). Erratum 91.
14. **A read handle at mcp-write** — over HTTP: an investigate and a staged `resume_input` handle at all three tools,
    the investigate handle again with a lying `server` column; positive controls: each live at `mcp_read`'s
    `resolve_invocation`, the lie refused by `mcp_exec`'s own resolution too, and the run's execute handle answered
    SUCCEEDED at mcp-write (Task 4).
15. **incident-sim refuses mcp-read's token** — live: `ops-mcp-read`'s token is 403 `FORBIDDEN` at the incident POST,
    the lookup and the abort, writes nothing, and mcp-write's own token passes authentication on the same lookup (Task
    4). The network half → T30 (debt line and matrix note).
16. **Independent client** — `python -m ops_mcp_write` as a child process pointed at an in-process incident-sim; the
    official `Client` lists exactly the three tools and calls `get_incident_receipt` with a staged recover handle for a
    committed action, creating nothing (Task 5). Evidence `reports/mcp-write/`; R025/R031 notes (Task 6).
17. **Deadlines** — `mark_sent` answers `expired` when `app.current_time() > granted_at + app._dispatch_seconds()`
    (300 s), after the runs lock and after the cancel check; `request_abort` uses the same comparison for its reason and
    its due-ness (Task 2). The value as a setting → T29 (debt line). Erratum 85.
18. **Backoff** — T22; each recovery tool call is one destination request with the client's 10 s timeout
    (`destination.TIMEOUT`, pinned in Task 3). Erratum 92.
19. **Faults** — live at the recovery tools (Task 4): `lose_after_commit` then `delay_receipt` (404 → UNKNOWN, then
    SUCCEEDED), `receipt_hash_mismatch` (CONFLICT, replayed by the lookup without a call), `rate_limit` (UNKNOWN, the
    lookup's 404 UNKNOWN, then the abort). The abort route gains no hook; narrowing the fault kinds → T22 (debt line).
    Refined (c).
20. **STALE_RUN / HASH_MISMATCH** — `STALE_RUN` is reachable (a recover job's `create_incident` on INTENT while the run
    is OUTCOME_UNKNOWN) and tested live (Task 4) and in-process (Task 3); `HASH_MISMATCH` is provably unreachable (only
    `record_outcome` raises `OC007`, after the destination answered, where `execution.py` answers UNKNOWN; a unit test
    follows every function mcp-write reaches before a destination answer through its newest body, helpers included,
    Task 2) and its mapping is removed (Task 3).
21. **The EXECUTING re-send** — live over HTTP: `lose_after_commit`, `create_incident` (UNKNOWN; SENT; EXECUTING),
    again with a fresh handle for the same open execute job → SUCCEEDED, same action id, one incident (Task 4).
22. **Trust statement** — `docs/threat-model.md` (Task 5).
23. **Recover handles** — staged directly in the tests (Tasks 4 and 5).
24. **The cancelled/expired branch** — replaced per SA:348 (Task 3); live for a cancel before send and for a send past
    the deadline (Task 4), and at the definers (Task 2).
25. **Revision 0010** — `0010_write_path` (Task 2): `request_abort`, the four re-created definers, `_dispatch_seconds`,
    frozen callers and signatures, exact downgrade to 0009; mcp-write asserts `persistence.WRITE_PATH` at start;
    mcp-read checks nothing new (a unit test shows it does not ask).
26. **Recovery tools resolve first** — every tool runs `persistence.resolve_invocation` with its own tool name before
    any definer (`server.answer`, Task 3; the call order is a unit test).
27. **Bookkeeping** — R030 and R131 `IMPLEMENTED_LOCALLY_VERIFIED`/`RECORDED_LOCALLY_LIVE`; R025 and R031 keep their
    statuses and record the write halves in their notes and evidence paths; `tests/plan_k`; `reports/mcp-write/` (Task
    6). Refined (h).

### Rulings needing controller attention

None of the 27 is impossible in its intent. These refinements were forced by the code and are flagged so the
controller can overrule them before execution:

- **(a) Ruling 3's `reason` argument.** mcp-write cannot choose the reason for `abort_incident`: it sees neither
  `runs.cancel_requested` nor `execution_grant.granted_at` (`mcp_exec` reads no table, SA:437, and
  `resolve_invocation` returns neither, `HANDLE_COLUMNS` in 0004), and the choice must be made under the runs lock
  anyway (a cancel can land between a read and the request). So `request_abort(raw_handle, client_azp, action_id)`
  takes no reason: it derives one under the lock with ruling 3's rule, records it on the `ABORT_REQUESTED` row and
  returns it; mcp-write POSTs the abort with that reason (erratum 82). The server side still chooses, never the
  worker. Smallest alternative: extend `HANDLE_COLUMNS` with `cancel_requested` and the deadline (a new
  `_resolve_handle` and `resolve_invocation` for both servers, `HANDLE_BINDING` re-pinned) and keep a `reason`
  argument the function only validates.
- **(b) Ruling 10's abort data cannot say UNKNOWN or CONFLICT.** The schema's `abort_incident` data has `outcome ∈
  {SUCCEEDED, FAILED_NO_COMMIT}` and requires `status=outcome` ⇒ FAILED_NO_COMMIT (`schemas/tool-result.schema.json`
  :1044-1180, :1389-1414), yet an abort can go unanswered (503, a timeout) or meet another hash's receipt (409). Task 3
  extends `scripts/build_schemas.py`'s `abort_outcome()` to all four outcomes (UNKNOWN and CONFLICT with neither a
  receipt nor a tombstone) and the `outcome` rule to FAILED_NO_COMMIT, UNKNOWN or CONFLICT, and regenerates the
  schemas (erratum 88). Smallest alternative: answer an unanswered abort with an error envelope (breaks SA:354: no
  error after a grant), or with `get_incident_receipt`'s data shape under `abort_incident` (fails the schema).
- **(c) Ruling 19's `rate_limit` and `receipt_hash_mismatch` at the recovery tools.** Both hooks act on `POST
  /internal/incidents` only (`incident-sim/…/app.py:193`, `:227`); the lookup never answers CONFLICT (it compares the
  key with itself, `:275`) and the abort route has no hook (ruling 19). Task 4 therefore drives each through
  `create_incident` and asserts the recovery tools' answers afterwards (`rate_limit`: the lookup's 404 is UNKNOWN, the
  abort then FAILED; `receipt_hash_mismatch`: the stored CONFLICT replayed without a call), and Task 3 proves a 429 at
  the lookup and at the abort with a real request against `httpx2.MockTransport`. Smallest alternative: add hooks to
  the GET and abort routes.
- **(d) Ruling 4's "any attempt" for `get_incident_receipt`.** Read as the three states it lists (SENT,
  ABORT_REQUESTED, RESOLVED): an INTENT attempt was never sent, so there is nothing to look up, and a run without a
  grant has no attempt at all. Smallest alternative: admit INTENT (its lookup would answer 404, UNKNOWN).
- **(e) Things the rulings did not name and the code needed.** `mark_sent` answers `abort_requested` (nothing
  written) and `create_incident` answers UNKNOWN when it meets ABORT_REQUESTED (Review Focus 1): without them the old
  `mark_sent` would write SENT after an abort request. Since round 1 (I1) the re-send of a SENT attempt passes
  `mark_sent` as well, which answers `cancelled`/`expired` for it (the tool aborts) and `not_redispatchable` to a
  recover job (a plain `NOT_REDISPATCHABLE` error). And the recovery tools refuse a `proposal_id` other than the
  grant's (`OTHER_PROPOSAL`, SA:538), because the handle, not the argument, picks the action.
- **(f) Ruling 20's removal** of the `HASH_MISMATCH` mapping rests on a unit test that walks every revision and
  follows each function mcp-write calls before a destination answer, and every helper they call, through its newest
  body; a later revision that adds an `OC007` to any of them fails that test, and the exception would surface as the
  SDK's tool error, not a wrong envelope.
- **(g) Errors after a grant (SA:354).** `ABORT_NOT_DUE`, `STALE_RUN` and `OTHER_PROPOSAL` are plain error envelopes
  although a grant exists, as is `NOT_REDISPATCHABLE` (round 1); each comes before any destination call and names no
  action (erratum 89).
- **(h) Ruling 27's rows.** R030 and R131 become `IMPLEMENTED_LOCALLY_VERIFIED`, R131 subject to errata 72 and 91 (its
  read functions do not exist yet). R025 now has both halves evidenced but stays
  `NOT_IMPLEMENTED_OR_NOT_TARGET_VERIFIED` because T15 owns it; R031 likewise (T04, T15). Smallest alternative: mark
  R025 implemented here.

## Declared debt and errata

### Debt list (committed in Task 1 Step 1c, before coding)

Inserted into `SESSION_STATE.md` as a new section `## Plan K debt list (T47; committed before coding) [R6-B7]`
immediately after the `## Plan J debt list …` section (before `## Environment (observed)`); the exact text is Task 1
Step 1c's Edit 1.

### Errata proposed to the owner (numbered on from Plan J's 81)

The spec text stays authoritative until the owner decides; each line names the text it amends. The full wording is
Task 6 Step 3's "Plan K executed" block; in short:

82. **SA:465** `request_abort(raw_handle, client_azp, action_id)` chooses and records the reason under the runs lock;
    refuses `ABORT_NOT_DUE`; a repeat returns the first reason; RESOLVED answers `resolved`.
83. **SA:462-466 with erratum 48**: the write-path functions take the presented token's `azp` as their second
    argument; the worker's client is named once (`OPS_WORKLOAD_CLIENT_ID`).
84. **SA:338, SA:344-345, SA:334**: the attempt-state allowlist in Python (the table in ruling 4); SA:344 gains SENT for
    execute jobs, still not cancelled and before the deadline, re-checked by `mark_sent`; SA:345's "INTENT only" wins
    over SA:334, and `mark_sent` refuses a recover job's re-send under the lock.
85. **SA:229-231, SA:463**: `mark_sent` answers `expired` past `granted_at` + 300 s (after the lock, after the cancel
    check), for a first send and a re-send of a SENT attempt alike, `abort_requested` after an abort request and
    `not_redispatchable` to a recover job's re-send, writing nothing for any of them.
86. **SA:464**: `record_outcome` accepts SUCCEEDED and CONFLICT after SENT, or after ABORT_REQUESTED with the reason
    `deadline` (an abort that followed SENT).
87. **SA:280 with SA:241-242**: the FAILED reason after an abort; `deadline` is a destination reason only; mcp-write
    reads the case from the tombstone's reason.
88. **SA:356**: `abort_incident`'s data may say UNKNOWN or CONFLICT, with neither receipt nor tombstone.
89. **SA:354-355**: `ABORT_NOT_DUE`, a recover redispatch's `STALE_RUN`, a recover job's re-send's
    `NOT_REDISPATCHABLE` and `OTHER_PROPOSAL` are plain errors after a grant, each before any destination call.
90. **BS:393**: the recovery tools are registered on mcp-write only and refused for every handle but a recover job's.
91. **R131, SA:401**: `mcp_exec` also holds `current_time`; "no read function" is shown on today's function set.
92. **SA:242, BS:502**: one destination request per recovery tool call; the backoff is the worker's (T22).

## File structure

- `core/src/ops_core/settings.py` (Task 1): `workload_client_id()`.
- `worker/src/ops_worker/main.py` (Task 1): `token_source(kc)`.
- `mcp-read/src/ops_mcp_read/server.py` (Task 1): `read_verifier`'s `allowed_azp` from the setting.
- `mcp-write/src/ops_mcp_write/server.py` (Tasks 1-3): `McpVerifier`'s audience check, `validate_token_resource=True`,
  `write_verifier`; the token's `azp` handed to the work and the 0010 startup check; `refusal_error`'s
  `ABORT_NOT_DUE`, `outcome_envelope(outcome, tool_name)`, `abort_envelope`, `answer` and the three tools.
- `migrations/app/versions/0010_write_path.py` (new, Task 2).
- `core/src/ops_core/privileges.py` (Task 2): the four signatures, `request_abort`, `_dispatch_seconds`.
- `core/src/ops_core/persistence.py` (Tasks 2, 3): `WRITE_PATH`, the `azp` argument of the four wrappers,
  `request_abort`; `allowed_tool(job_type, run_state, attempt_state, tool)` and `resolve_invocation`.
- `core/src/ops_core/jobs.py` (Task 3): `ATTEMPT_STATES`, `JobRule`'s docstring.
- `mcp-write/src/ops_mcp_write/execution.py` (Tasks 2, 3): `azp` throughout; `next_step`'s `aborting`, `_ask`,
  `_record`, `_granted`, `_abort`, `get_incident_receipt`, `abort_incident`.
- `mcp-write/src/ops_mcp_write/destination.py` (Task 3): `TIMEOUT`, `NEVER_SENT`, `get_action`, `post_abort`, `_send`,
  the tombstone mapping in `classify`.
- `scripts/build_schemas.py` and the regenerated `schemas/` (Task 3).
- Tests: `tests/plan_k/` (`__init__.py`, `test_verifier_t47.py`, `test_workload_client.py`, `test_migration_0010.py`,
  `test_mcp_write_startup.py`, `test_attempt_allowlist.py`, `test_recovery_tools.py`, `test_write_tools_server.py`);
  `tests/e2e/` (`test_migration_0010_live.py`, `test_mcp_write_t47_live.py`, `test_mcp_write_process_live.py`); edits to
  `tests/plan_e/test_transitions_table.py`, `tests/e2e/test_migration_0007_live.py`, the ten call-site modules of Task 2
  Step 5, `tests/plan_d/test_persistence_pure.py`, `tests/plan_e/test_persistence_errors.py`,
  `tests/plan_j/test_allowlist.py`, `tests/plan_d/test_mcp_write.py`, `tests/plan_b/test_evidence.py`,
  `tests/plan_j/test_worker_azp.py`, `tests/plan_c/test_schema_conformance.py`.
- Documentation: `docs/threat-model.md` (new, Task 5); Task 6: `handoff/*`, `SESSION_STATE.md`, `STATUS.md`,
  `docs/ARCHITECTURE.md`, `docs/runbooks/mcp-write.md` (new), `docs/runbooks/mcp-read.md`, `docs/PROJECT_HISTORY.md`,
  `README.md`, `mcp-write/README.md`, `mcp-read/README.md`, `worker/README.md`.

## Task overview

- **Task 1:** the debt list; `OPS_WORKLOAD_CLIENT_ID`; `write_verifier` and mcp-write's verifier parity; `tests/plan_k`.
  Tests: `test_verifier_t47.py` 10, `test_workload_client.py` 4. Dev gate after: 1089 passed, 164 skipped; live
  1232/21 (arithmetic).
- **Task 2:** revision 0010, the persistence wrappers, mcp-write's `azp` and startup check, every write-path call site;
  live definer tests. Tests: `test_migration_0010.py` 10, `test_mcp_write_startup.py` 3, the transitions module +1
  (parametrised); live `test_migration_0010_live.py` 5. Dev 1103/169, live 1251/21 (arithmetic).
- **Task 3:** the attempt-state allowlist, the recovery tools, `create_incident`'s abort branch, the envelopes, the
  abort schema. Tests: `test_attempt_allowlist.py` 7, `test_recovery_tools.py` 27, `test_write_tools_server.py` 15.
  Dev 1152/169, live 1300/21 (arithmetic).
- **Task 4:** live HTTP evidence (R030, R131's write half, the re-send, the faults, the cancel and the deadline, the
  recover redispatch). Tests: live `test_mcp_write_t47_live.py` 10. Dev 1152/179, live 1310/21 (arithmetic).
- **Task 5:** the independent mcp-write process; `docs/threat-model.md`. Tests: live `test_mcp_write_process_live.py` 1.
  Dev 1152/180, live 1311/21 (arithmetic).
- **Task 6:** handoff records, acceptance rows, errata 82-92, the runbook, status, history, READMEs, final gates. No
  tests.

The arithmetic, once: dev passed 1075 + 14 (Task 1) = 1089, + 14 (Task 2: 10 + 3 + 1) = 1103, + 49 (Task 3: 7 + 27 +
15) = 1152, + 0 (Tasks 4-6) = 1152; dev skipped 164, + 5 = 169, + 0 = 169, + 10 = 179, + 1 = 180. The live gate's
passed count is the dev count plus the live-gated tests (the dev skips minus the 21 that skip in both gates: 143
today; 143, 148, 148, 158, 159 after Tasks 1-5), so 1232, 1251, 1300, 1310, 1311, always with 21 skipped. The dev
numbers were measured on a scratch copy; the live ones are not measured (see "Counts").

---

### Task 1: Debt before code — the worker's client named once, mcp-write's verifier at mcp-read's level

**Files:**
- Create: `tests/plan_k/__init__.py`, `tests/plan_k/test_verifier_t47.py`, `tests/plan_k/test_workload_client.py`
- Modify: `SESSION_STATE.md` (new debt section before `## Environment (observed)`), `pyproject.toml` (`testpaths`),
  `core/src/ops_core/settings.py` (before `fixtures_dir`), `mcp-write/src/ops_mcp_write/server.py` (`McpVerifier`,
  `build_server`'s `AuthSettings`, `production_app` and the new `write_verifier` before it),
  `worker/src/ops_worker/main.py` (`token_source` before `_main`, `_main`'s token source),
  `mcp-read/src/ops_mcp_read/server.py` (docstring, `read_verifier`)

**Requirements:** SA:557-558 at mcp-write (ruling 11); the worker's client named once (T47 review note 3, ruling 12);
the Plan K debt list (SA:698).

**Interfaces:**
- Consumes: `ops_core.tokens.TokenVerifier(..., token_type=...)`, `TokenRejected`, `WorkloadTokenSource.client_id`;
  `ops_mcp_write.server.State`, `build_server(state, *, issuer, resource_url)`, `production_app()`;
  `ops_mcp_read.server.read_verifier(kc, urls)`; Plan D's synthetic key pair (`tests.plan_d.test_tokens.ISSUER`,
  `AUDIENCE`, `JWK1`, `mint`).
- Produces: `ops_core.settings.workload_client_id() -> str`; `ops_mcp_write.server.write_verifier(kc: settings.Keycloak,
  urls: settings.Urls) -> TokenVerifier`; `ops_worker.main.token_source(kc: settings.Keycloak) -> WorkloadTokenSource`;
  in `tests.plan_k.test_verifier_t47`: `WRITE`, `URLS`, `KC`, `production_like()`, `for_write(**over)`.

- [x] **Step 1a: Record both baselines**

Run `PYTHONUTF8=1 uv run python scripts/check.py` → `CHECK: GREEN` with pytest `1075 passed, 164 skipped`; with the
dev stack up and `uv run python scripts/skeleton.py status` showing every process down, run
`PYTHONUTF8=1 uv run python scripts/check.py --profile test` → `CHECK: GREEN` with `1218 passed, 21 skipped`, then
`git checkout -- reports/bootstrap reports/skeleton reports/auth reports/admission reports/leases reports/events
reports/outbox reports/mcp-read`. Record both lines in the report (Global Constraints, "Counts"). A gate that is not
GREEN stops the plan here, before anything is committed.

- [x] **Step 1b: Record the base**

Run `git rev-parse --short HEAD` and write the hash it prints as `BASE=<hash>` in the report and in the SDD ledger
(`.superpowers/sdd/2026-10-16-first-slice-k-mcp-write-recovery-tools/progress.md`). Task 6's commit span is
`<base>..<last>`.

- [x] **Step 1c: Commit the debt list (before any code)**

Edit 1 (`SESSION_STATE.md`, at the end of "Plan J debt list (T15; committed before coding) [R6-B7]"), replace:

```markdown
## Environment (observed)
```

with:

```markdown
## Plan K debt list (T47; committed before coding) [R6-B7]

Allowed shortcuts in T47, each with its owning task:
- the worker's side of recovery: a `recover` job handler that calls `get_incident_receipt` and `abort_incident`, the
  1, 2, 4, 8 s backoff with jitter between lookups, scheduled recover jobs, the worker's own recover job after a
  `cancelled`/`expired` answer, the redispatch of an unsent attempt from OUTCOME_UNKNOWN (attempt row 2,
  `action.redispatched`), the escalation deadline (`escalate_run`) and the operator's `resolve_escalation` → T22 (Plan
  K rulings 1, 6, 18 and 23); until then the worker finishes every `recover` job unhandled, the live tests stage
  recover jobs and handles directly, and a recover job's `create_incident` on an unsent attempt of a run that left
  EXECUTING is refused `STALE_RUN` by `mark_sent`'s EXECUTING guard;
- late destination evidence once the attempt is RESOLVED (an abort on an ABANDONED_UNVERIFIED run recorded as
  `action.late_evidence`) → T22 (ruling 7);
- a SUCCEEDED answer to an abort after a cancel carries no "cancellation arrived after dispatch" note (SA:248;
  `ActionOutcome` has no field for it), and a `create_incident` that meets an abort request in flight answers UNKNOWN
  (the abort's own record decides) → T22;
- the dispatch deadline is a constant in SQL (`app._dispatch_seconds()`, 300 s), not a setting → T29 (ruling 17);
- the destination's faults reach the recovery tools only through the send's consequences: `rate_limit` and
  `receipt_hash_mismatch` act on `POST /internal/incidents` alone and the abort route has no fault hook, so a 429 at
  the lookup or at the abort is proved with a scripted reply; incident-sim's fault route still accepts any
  `FaultKind` (`outbox_sink_fail` can be armed there and is never consumed) → T22 (ruling 19);
- receipts and tombstones signed by incident-sim with a key only `app_definer` can read (T47 review note 2's option)
  → v1.1, no task (`docs/threat-model.md`, ruling 22);
- the network half of T47 DoD 3 and R131 (mcp-read cannot reach incident-sim at all) → T30 (ruling 15);
- mcp-write has no `tests/` directory and no Dockerfile of its own (AM-01) → T30;
- the dev database stays at revision 0005 until the owner migrates it (0006 to 0010 pending); until then the API, the
  sweeper, the worker, mcp-read and mcp-write refuse to start on it, mcp-write now also without 0010 → owner input.

## Environment (observed)
```

```bash
git add SESSION_STATE.md
git commit -m "docs: declare Plan K's shortcuts before coding (T47 debt list)"
```

- [x] **Step 2: Put `tests/plan_k` on the test path**

Edit 1 (`pyproject.toml`, the changed lines), replace:

```toml
  "tests/plan_h", "tests/plan_i", "tests/plan_j", "tests/e2e",
```

with:

```toml
  "tests/plan_h", "tests/plan_i", "tests/plan_j", "tests/plan_k", "tests/e2e",
```

Create `tests/plan_k/__init__.py`:

```python
"""Plan K (T47): mcp-write's verifier, the write-path revision, the attempt-state allowlist and the recovery tools,
without a database."""
```

- [x] **Step 3: Write the failing verifier tests**

Create `tests/plan_k/test_verifier_t47.py`:

```python
"""mcp-write's token checks with the verifier `production_app` builds (`write_verifier`), on Plan D's synthetic key
pair (SA:557-558; Plan K ruling 11: mcp-read's cases from tests/plan_j/test_verifier_t15.py, at mcp-write).

Catches: an ID or refresh token accepted as an access token (`typ` claim), a browser client's token (`azp` ops-web), a
token without `aud`, the read server's audience, or another workload's `azp` (mcp-read's, or mcp-write's own client)
accepted at mcp-write; an access token whose `resource` is stamped without the audience holding it (before T47
mcp-write stamped its own URL whatever `aud` held); a refactor that drops `token_type="Bearer"` from mcp-write's
verifier or turns the SDK's `validate_token_resource` off again; and a `production_app` that inlines its own verifier.
"""

import asyncio
from typing import Any

import pytest
from ops_core import settings
from ops_core.settings import Keycloak, Urls
from ops_core.tokens import TokenRejected, TokenVerifier
from ops_mcp_write import server
from ops_mcp_write.server import McpVerifier

from tests.plan_d.test_tokens import AUDIENCE as READ_AUDIENCE  # Plan D's synthetic key pair and token minter
from tests.plan_d.test_tokens import ISSUER, JWK1, mint

WRITE = "http://mcp-write:8082/mcp"
URLS = Urls(
    mcp_read_resource=READ_AUDIENCE,
    mcp_write_resource=WRITE,
    mcp_read="http://127.0.0.1:8081/mcp",
    mcp_write="http://127.0.0.1:8082/mcp",
    incident_sim="http://127.0.0.1:8090",
)
KC = Keycloak(base_url="http://localhost:18080", issuer=ISSUER, server_url="http://127.0.0.1:18080")


def production_like() -> TokenVerifier:
    """`ops_mcp_write.server.write_verifier`, the one `production_app` uses, with the synthetic key installed."""
    verifier = server.write_verifier(KC, URLS)
    verifier.install_keys({"keys": [JWK1]})
    return verifier


def for_write(**over: Any) -> str:
    """A synthetic worker token that carries mcp-write's audience (the worker's real token carries both servers')."""
    return mint(**{"aud": [READ_AUDIENCE, WRITE, "account"], **over})


def test_only_an_access_token_passes() -> None:
    verifier = production_like()
    assert verifier.verify(for_write()).azp == "ops-worker"
    for typ in ("ID", "Refresh", None):
        with pytest.raises(TokenRejected, match="token type"):
            verifier.verify(for_write(typ=typ))


@pytest.mark.parametrize(
    ("over", "why"),
    [
        ({"azp": "ops-web"}, "the browser client's token"),
        ({"aud": None}, "no audience at all"),
        ({"aud": [READ_AUDIENCE, "account"]}, "the read server's audience only"),
        ({"aud": "ops-api", "azp": "ops-dev-direct"}, "a persona token"),
        ({"azp": "ops-mcp-read"}, "mcp-read's workload with the right audience"),
        ({"azp": "ops-mcp-write"}, "mcp-write's own workload client"),
    ],
)
def test_the_adapter_answers_none_for_every_foreign_token(over: dict[str, object], why: str) -> None:
    adapter = McpVerifier(production_like(), WRITE)
    assert asyncio.run(adapter.verify_token(for_write(**over))) is None, why  # None is the SDK's 401


def test_the_resource_is_stamped_only_from_the_audience() -> None:
    adapter = McpVerifier(production_like(), WRITE)
    access = asyncio.run(adapter.verify_token(for_write()))
    stamped = access is not None and access.resource == WRITE and access.client_id == "ops-worker"
    assert stamped  # a verdict, not the AccessToken: its repr holds the (synthetic) token
    # A verifier wired to another audience (a deployment mistake) still cannot stamp this server's resource.
    wrong = TokenVerifier(
        issuer=ISSUER, audience="account", allowed_azp=frozenset({"ops-worker"}), jwks_url="unused", token_type="Bearer"
    )
    wrong.install_keys({"keys": [JWK1]})
    refused = asyncio.run(McpVerifier(wrong, WRITE).verify_token(mint(aud=["account"]))) is None
    assert refused


def test_the_sdk_resource_check_is_on() -> None:
    """A second layer behind McpVerifier's own audience check, pinned so a refactor cannot switch it off unnoticed."""
    state = server.State(deps=None, verifier=production_like())
    mcp = server.build_server(state, issuer=ISSUER, resource_url=WRITE)
    assert mcp.settings.auth is not None and mcp.settings.auth.validate_token_resource is True


def test_production_app_builds_its_verifier_through_write_verifier(monkeypatch: pytest.MonkeyPatch) -> None:
    """The tests above pin `write_verifier`; this pins that the app that runs uses it (a refactor that inlined a
    `TokenVerifier` without `token_type` would pass every other unit and live test, since live tokens are `Bearer`)."""
    calls: list[tuple[Any, Any]] = []
    real = server.write_verifier

    def recording(kc: Keycloak, urls: Urls) -> TokenVerifier:
        calls.append((kc, urls))
        return real(kc, urls)

    monkeypatch.setattr(settings, "keycloak", lambda: KC)
    monkeypatch.setattr(settings, "urls", lambda: URLS)
    monkeypatch.setattr(server, "write_verifier", recording)
    server.production_app()
    assert calls == [(KC, URLS)]
```

Run: `uv run python -m pytest tests/plan_k/test_verifier_t47.py -q`
Expected: `10 failed` (each with `AttributeError: module 'ops_mcp_write.server' has no attribute 'write_verifier'`).

- [x] **Step 4: The setting, mcp-write's audience check and `write_verifier`**

Edit 1 (`core/src/ops_core/settings.py`, in `fixtures_dir`), replace:

```python
def fixtures_dir() -> Path:
```

with:

```python
def workload_client_id() -> str:
    """The worker's Keycloak client, named here once (T47, Plan K ruling 12): the worker's token source asks for tokens
    as this client, both MCP servers' verifiers accept no other `azp`, and the worker binds every handle it mints to
    it, which the definers compare with the presented token's `azp`. `OPS_WORKLOAD_CLIENT_ID`, default `ops-worker`
    (the realm's client); the secret file keeps its name, `kc_client_secret_ops_worker`."""
    return env("OPS_WORKLOAD_CLIENT_ID", "ops-worker")


def fixtures_dir() -> Path:
```

Edit 2 (`mcp-write/src/ops_mcp_write/server.py`, in `McpVerifier`), replace:

```python
    """The SDK's TokenVerifier protocol: None means 401. The SDK re-checks `expires_at`, consistently with PyJWT."""

    def __init__(self, verifier: Verifier, resource_url: str) -> None:
        """Adapt a token verifier to the SDK's bearer-auth hook; `resource_url` is stamped on the access token."""
```

with:

```python
    """The SDK's TokenVerifier protocol: None means 401. The SDK re-checks `expires_at`, consistently with PyJWT.

    A token whose `aud` lacks this server's resource URL is refused here, whatever audience the wrapped verifier was
    configured with, and only then is `resource` stamped with that URL (mcp-read's rule, Plan J ruling 2; Plan K
    ruling 11). The SDK's own resource check (`validate_token_resource`) stays on as a second layer; it cannot refuse
    anything while the stamp is this server's own URL, and would decide only if the stamp ever came from the token.
    """

    def __init__(self, verifier: Verifier, resource_url: str) -> None:
        """Adapt a token verifier to the SDK's bearer-auth hook; `resource_url` is this server's audience."""
```

Edit 3 (`mcp-write/src/ops_mcp_write/server.py`, in `McpVerifier`), replace:

```python
            return None
```

with:

```python
            return None
        if self._resource not in principal.audiences:
            return None
```

Edit 4 (`mcp-write/src/ops_mcp_write/server.py`, in `build_server`), replace:

```python
            issuer_url=AnyHttpUrl(issuer), resource_server_url=AnyHttpUrl(resource_url), validate_token_resource=False
```

with:

```python
            issuer_url=AnyHttpUrl(issuer), resource_server_url=AnyHttpUrl(resource_url), validate_token_resource=True
```

Edit 5 (`mcp-write/src/ops_mcp_write/server.py`, in `production_app`), replace:

```python
def production_app() -> Starlette:
```

with:

```python
def write_verifier(kc: settings.Keycloak, urls: settings.Urls) -> TokenVerifier:
    """mcp-write's token checks (SA:557; mcp-read's since Plan J, Plan K ruling 11): the realm's issuer and keys, this
    server's resource URL as the audience, the worker's client (`settings.workload_client_id`, ruling 12) as the only
    `azp`, and an access token's `typ` claim. `production_app` builds its verifier here, and the unit tests build
    theirs here too, so they pin the wiring that runs."""
    return TokenVerifier(
        issuer=kc.issuer,
        audience=urls.mcp_write_resource,
        allowed_azp=frozenset({settings.workload_client_id()}),
        jwks_url=kc.jwks_url,
        token_type="Bearer",  # an access token: Keycloak's ID and refresh tokens carry another `typ`
    )


def production_app() -> Starlette:
```

Edit 6 (`mcp-write/src/ops_mcp_write/server.py`, in `production_app`), replace:

```python
    verifier = TokenVerifier(
        issuer=kc.issuer, audience=urls.mcp_write_resource, allowed_azp=frozenset({"ops-worker"}), jwks_url=kc.jwks_url
    )
    state = State(deps=None, verifier=verifier)
```

with:

```python
    state = State(deps=None, verifier=write_verifier(kc, urls))
```

Run: `uv run python -m pytest tests/plan_k/test_verifier_t47.py -q`
Expected: `10 passed`.

- [x] **Step 5: Write the failing setting tests**

Create `tests/plan_k/test_workload_client.py`:

```python
"""The worker's client is named once, in settings (T47 review note 3, Plan K ruling 12): the worker's token source asks
for tokens as it, and both MCP servers' verifiers accept it and no other `azp`.

Catches: one of the three places keeping its own literal, so that renaming the client (`OPS_WORKLOAD_CLIENT_ID`)
leaves the worker asking for the old client's tokens, or a verifier refusing the renamed client's tokens while still
accepting the old one's. The fourth place, the `azp` a handle is minted with, follows the token source
(tests/plan_j/test_worker_azp.py); the definers compare the presented token's `azp` from revision 0010 on
(tests/e2e/test_migration_0010_live.py).
"""

from typing import Any

import pytest
from ops_core import settings
from ops_core.tokens import TokenRejected, TokenVerifier
from ops_mcp_read import server as read_server
from ops_mcp_write import server as write_server
from ops_worker import main

from tests.plan_d.test_tokens import AUDIENCE as READ_AUDIENCE
from tests.plan_d.test_tokens import JWK1, mint
from tests.plan_k.test_verifier_t47 import KC, URLS, WRITE


def test_the_default_is_the_realms_worker_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPS_WORKLOAD_CLIENT_ID", raising=False)
    assert settings.workload_client_id() == "ops-worker"
    monkeypatch.setenv("OPS_WORKLOAD_CLIENT_ID", "")  # an empty value counts as unset (settings.env)
    assert settings.workload_client_id() == "ops-worker"


def test_the_worker_asks_for_tokens_as_the_named_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_WORKLOAD_CLIENT_ID", "ops-worker-renamed")
    asked: list[str] = []

    def read_secret(name: str, directory: Any = None) -> str:
        asked.append(name)
        return "unit-test"

    monkeypatch.setattr(settings, "read_secret", read_secret)
    tokens = main.token_source(KC)
    assert tokens.client_id == "ops-worker-renamed" and asked == ["kc_client_secret_ops_worker"]


@pytest.mark.parametrize(
    ("build", "audience"),
    [(read_server.read_verifier, READ_AUDIENCE), (write_server.write_verifier, WRITE)],
    ids=["mcp-read", "mcp-write"],
)
def test_both_verifiers_accept_only_the_named_client(
    monkeypatch: pytest.MonkeyPatch, build: Any, audience: str
) -> None:
    monkeypatch.setenv("OPS_WORKLOAD_CLIENT_ID", "ops-worker-renamed")
    verifier: TokenVerifier = build(KC, URLS)
    verifier.install_keys({"keys": [JWK1]})
    assert verifier.verify(mint(aud=[audience, "account"], azp="ops-worker-renamed")).azp == "ops-worker-renamed"
    with pytest.raises(TokenRejected):
        verifier.verify(mint(aud=[audience, "account"], azp="ops-worker"))  # the old literal is no longer accepted
```

Run: `uv run python -m pytest tests/plan_k/test_workload_client.py -q`
Expected: `2 failed, 2 passed` (`AttributeError: module 'ops_worker.main' has no attribute 'token_source'`, and the
mcp-read case's `ops_core.tokens.WrongAudience: token was issued to a client this server does not accept`: its
verifier still names `ops-worker`; the default and the mcp-write case pass already).

- [x] **Step 6: The worker's token source and mcp-read's verifier read the setting**

Edit 1 (`worker/src/ops_worker/main.py`, in `_main`), replace:

```python
async def _main() -> None:
```

with:

```python
def token_source(kc: settings.Keycloak) -> WorkloadTokenSource:
    """The worker's workload tokens, issued to the client the settings name (Plan K ruling 12); its client id is also
    the `azp` every handle is minted with (`handlers.Deps.workload_azp`, Plan J ruling 17)."""
    return WorkloadTokenSource(
        token_url=kc.token_url,
        client_id=settings.workload_client_id(),
        client_secret=settings.read_secret("kc_client_secret_ops_worker"),
    )


async def _main() -> None:
```

Edit 2 (`worker/src/ops_worker/main.py`, in `_main`), replace:

```python
    tokens = WorkloadTokenSource(
        token_url=kc.token_url,
        client_id="ops-worker",
        client_secret=settings.read_secret("kc_client_secret_ops_worker"),
    )
```

with:

```python
    tokens = token_source(kc)
```

Edit 3 (`mcp-read/src/ops_mcp_read/server.py`, the module header), replace:

```python
worker's workload access token (`typ` Bearer, aud = this server's resource URL, azp = ops-worker) and an
```

with:

```python
worker's workload access token (`typ` Bearer, aud = this server's resource URL, azp = the worker's client) and an
```

Edit 4 (`mcp-read/src/ops_mcp_read/server.py`, in `read_verifier`), replace:

```python
    audience, the worker as the only `azp`, and an access token's `typ` claim. `production_app` builds its verifier
    here, and the unit tests build theirs here too, so they pin the wiring that runs."""
```

with:

```python
    audience, the worker's client (`settings.workload_client_id`, Plan K ruling 12) as the only `azp`, and an access
    token's `typ` claim. `production_app` builds its verifier here, and the unit tests build theirs here too, so they
    pin the wiring that runs."""
```

Edit 5 (`mcp-read/src/ops_mcp_read/server.py`, in `read_verifier`), replace:

```python
        allowed_azp=frozenset({"ops-worker"}),
```

with:

```python
        allowed_azp=frozenset({settings.workload_client_id()}),
```

Run: `uv run python -m pytest tests/plan_k -q`
Expected: `14 passed`.

- [x] **Step 7: Gates and commit**

Format, lint and count characters on `core/src/ops_core/settings.py`, `worker/src/ops_worker/main.py`,
`mcp-read/src/ops_mcp_read/server.py`, `mcp-write/src/ops_mcp_write/server.py` and every file under `tests/plan_k/`.

Run: `PYTHONUTF8=1 uv run python scripts/check.py`
Expected: `CHECK: GREEN`; pytest `1089 passed, 164 skipped` (1075 + 14 in `tests/plan_k`).

Run: `PYTHONUTF8=1 uv run python scripts/check.py --profile test`
Expected: `CHECK: GREEN`; pytest `1232 passed, 21 skipped` (arithmetic, not measured: the dev count plus the 143
live-gated tests, 164 − 21; the worker, mcp-read and mcp-write changed, so R105's skeleton and the mcp-read live
tests run against them with the default client). Then `git checkout -- reports/bootstrap reports/skeleton reports/auth
reports/admission reports/leases reports/events reports/outbox reports/mcp-read`.

Run: `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`
Expected: exit 0.

```bash
git add pyproject.toml core/src/ops_core/settings.py worker/src/ops_worker/main.py mcp-read/src/ops_mcp_read/server.py
git add mcp-write/src/ops_mcp_write/server.py tests/plan_k
git commit -m "feat(mcp): mcp-write's verifier at mcp-read's level; the worker's client named once in settings (T47)"
```

---

### Task 2: Revision 0010 — the token's azp in the write path, the dispatch deadline, the abort request

**Files:**
- Create: `migrations/app/versions/0010_write_path.py`, `tests/plan_k/test_migration_0010.py`,
  `tests/plan_k/test_mcp_write_startup.py`, `tests/e2e/test_migration_0010_live.py`
- Modify: `tests/plan_e/test_transitions_table.py` (`REVISIONS`), `core/src/ops_core/privileges.py`
  (`DEFINER_FUNCTIONS`, `HELPER_FUNCTIONS`), `core/src/ops_core/persistence.py` (`WRITE_PATH` after `HANDLE_BINDING`;
  `grant_execution`, `lookup_action`, `mark_sent`, the new `request_abort`, `record_outcome`),
  `mcp-write/src/ops_mcp_write/execution.py` (`_read_back`, `create_incident`), `mcp-write/src/ops_mcp_write/server.py`
  (`create_incident`'s call, the lifespan's checks), `tests/e2e/test_migration_0007_live.py` (its last line), and the
  ten modules Step 5's script rewrites

**Requirements:** rulings 2, 3, 7, 12, 17, 25; R006 (an exact downgrade); SA:229-231, SA:463-465; the no-unapproved-
external-action boundary (nothing is sent, or re-sent, past the deadline, after a cancel or after an abort request;
the moment between `mark_sent`'s commit and the POST is AM-13's own and the same for a first send and a re-send).

**Interfaces:**
- Consumes: revisions 0004's `LOOKUP_ACTION`, `HELPER_HEADER` and 0007's `GRANT_EXECUTION`, `MARK_SENT`,
  `RECORD_OUTCOME`; `privileges.function_grant_statements`; `persistence.assert_function_text`, `HANDLE_BINDING`; the
  e2e helpers `approved_run`, `ALPHA` (`tests.e2e.test_mcp_write_live`), `attempt_states`
  (`tests.e2e.test_fenced_definers_live`), `FUNCTION_DETAILS`, `LEFTOVERS`, `exists`
  (`tests.e2e.test_migration_0007_live`), `lease_for`, `purge_run` (`tests.e2e.conftest`); Plan J's
  `tests.plan_j.test_mcp_read_startup.start`, `start_write`.
- Produces: `persistence.WRITE_PATH = ("app.request_abort(text, text, uuid)", "ABORT_NOT_DUE")`;
  `persistence.grant_execution(conn, *, handle, azp, proposal_id) -> Grant`, `lookup_action(conn, *, handle, azp) ->
  Grant`, `mark_sent(conn, *, handle, azp, action_id) -> str` (`sent`, `already_sent`, `resolved`, `cancelled`,
  `expired`, `abort_requested`, `not_redispatchable`), `request_abort(conn, *, handle, azp, action_id) -> str`
  (`cancelled_before_send`, `expired`, `deadline` or `resolved`; `Refused("ABORT_NOT_DUE")`; `PersistenceError` for a
  missing reason), `record_outcome(conn, *, handle, azp, action_id,
  outcome) -> ToolOutcome`; `execution.create_incident(deps, *, handle, azp, proposal_id)`; in the revision:
  `LITERAL_AZP`, `TOKEN_AZP`, `GRANT_CHANGES`, `LOOKUP_CHANGES`, `RECORD_CHANGES`, `GRANT_EXECUTION`, `LOOKUP_ACTION`,
  `RECORD_OUTCOME`, `DISPATCH_SECONDS`, `MARK_SENT`, `REQUEST_ABORT`, `FUNCTIONS`, `REPLACED`, `CREATED`, `RESTORED`;
  in `tests.e2e.test_migration_0010_live`: `AZP`, `LATE`, `NOW`, `execute_handle(worker, run, *, azp, fence)`,
  `fence_of(app_conn, run)`, `recover_handle(app_conn, worker, run, trigger)`, `cancel(api, run)`.

- [x] **Step 1: Write the failing revision and startup tests**

Edit 1 (`tests/plan_e/test_transitions_table.py`, in `REVISIONS`), replace:

```python
    "tc_0001_test_clock",
```

with:

```python
    "0010_write_path",
    "tc_0001_test_clock",
```

Create `tests/plan_k/test_migration_0010.py`:

```python
"""Revision 0010 without a database (Plan K rulings 3, 7, 12, 17 and 25).

Catches: a derived body that changes more than its signature, the literal `azp` and (in `record_outcome`) the one guard,
so that a lock, a refusal or an event of the applied body moves unseen; a write-path body that still names
`'ops-worker'`; `mark_sent` sending after an abort request, re-sending a SENT attempt after a cancel, past the deadline
or for a recover job, comparing the clock before the runs lock, or letting the deadline win over a cancel;
`request_abort` taking a reason from its caller, choosing one before the lock, or
writing anything when no abort is due; an upgrade that leaves an old signature behind (the catalog test requires one
function per name) or grants a function to anyone but `mcp_exec`; a downgrade that does not put back the applied
bodies byte for byte; a startup marker that does not exist only in 0010's body; and an `OC007` that a definer
mcp-write calls before any destination I/O could raise, which `server.py` no longer maps.
"""

import asyncio
import importlib.util
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import alembic.op
import pytest
from ops_core import persistence, privileges
from ops_core.persistence import WRITE_PATH

from tests.plan_e.test_transitions_table import REVISIONS

VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "app" / "versions"
HANDLE_FUNCTIONS = ("grant_execution", "lookup_action", "mark_sent", "record_outcome", "request_abort")


def revision(name: str = "0010_write_path") -> Any:
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


def bodies(module: Any) -> dict[str, str]:
    return {name: body for name, _, _, body in module.FUNCTIONS}


def test_the_derived_bodies_change_only_what_the_revision_names() -> None:
    module, rev0004, rev0007 = revision(), revision("0004_write_path_functions"), revision("0007_leases_fences")
    assert module.down_revision == "0009_handle_binding"
    for derived, applied, changes in (
        (module.GRANT_EXECUTION, rev0007.GRANT_EXECUTION, module.GRANT_CHANGES),
        (module.LOOKUP_ACTION, rev0004.LOOKUP_ACTION, module.LOOKUP_CHANGES),
        (module.RECORD_OUTCOME, rev0007.RECORD_OUTCOME, module.RECORD_CHANGES),
    ):
        undone = derived
        for old, new in changes:
            undone = undone.replace(new, old)
        assert undone == applied
    every = bodies(module)
    assert all(module.TOKEN_AZP in every[name] and "'ops-worker'" not in every[name] for name in HANDLE_FUNCTIONS)


def test_upgrade_replaces_the_four_signatures_and_grants_mcp_exec_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    module = revision()
    expected = [f"DROP FUNCTION app.{s}" for s in module.REPLACED]
    for name, args, callers, body in module.FUNCTIONS:
        expected += [body, *privileges.function_grant_statements(name, args=args, callers=callers)]
        assert callers == (() if name.startswith("_") else ("mcp_exec",)), name
    assert statements(module, "upgrade", monkeypatch) == expected
    assert module.REPLACED == (
        "grant_execution(text, uuid)",
        "lookup_action(text)",
        "mark_sent(text, uuid)",
        "record_outcome(text, uuid, text, jsonb)",
    )


def test_the_downgrade_restores_the_applied_bodies(monkeypatch: pytest.MonkeyPatch) -> None:
    module, rev0004, rev0007 = revision(), revision("0004_write_path_functions"), revision("0007_leases_fences")
    seen = statements(module, "downgrade", monkeypatch)
    dropped = [s.removeprefix("DROP FUNCTION app.") for s in seen if s.startswith("DROP FUNCTION")]
    assert sorted(dropped) == sorted(f"{name}({args})" for name, args, _, _ in module.FUNCTIONS)
    restored = [s for s in seen if s.lstrip().startswith("CREATE OR REPLACE FUNCTION")]
    # Byte for byte the applied revisions' own bodies (0007's grant, mark_sent, record_outcome; 0004's lookup_action).
    assert restored == [rev0007.GRANT_EXECUTION, rev0004.LOOKUP_ACTION, rev0007.MARK_SENT, rev0007.RECORD_OUTCOME]
    assert seen.index(restored[0]) > max(seen.index(f"DROP FUNCTION app.{d}") for d in dropped)


def test_mark_sent_sends_nothing_after_an_abort_request_and_checks_cancel_then_the_deadline() -> None:
    body = revision().MARK_SENT
    lock = body.index("FROM runs r WHERE r.run_id = v_grant.run_id FOR UPDATE")
    aborting = body.index("RETURN 'abort_requested'")
    late = body.index(
        "v_late := app.current_time() > v_grant.granted_at + make_interval(secs => app._dispatch_seconds())"
    )
    assert lock < aborting < late  # the clock is read after the lock, once
    # A SENT attempt (a re-send) first: cancel, then the deadline, then a recover job, and only then `already_sent`.
    sent = body.index("IF v_latest.state = 'SENT' THEN")
    resend = [body.index(s, sent) for s in ("cancelled", "expired", "not_redispatchable", "already_sent")]
    assert late < sent and resend == sorted(resend) and "v_handle.job_type = 'recover'" in body[sent:]
    # Then an INTENT attempt: the EXECUTING guard, cancel, the deadline, and only then SENT.
    guard = body.index("IF v_run.state <> 'EXECUTING' THEN")
    first = [
        body.index(s, guard) for s in ("RETURN 'cancelled'", "RETURN 'expired'", "INSERT INTO action_attempt_state")
    ]
    assert resend[-1] < guard and first == sorted(first) and body.count("INSERT INTO") == 1  # SENT alone


def test_request_abort_chooses_its_reason_after_the_lock_and_writes_only_when_due() -> None:
    body = revision().REQUEST_ABORT
    assert "p_reason" not in body  # the caller never supplies the reason (ruling 3)
    lock = body.index("FROM runs r WHERE r.run_id = v_grant.run_id FOR UPDATE")
    clock = body.index("v_late := app.current_time() > v_grant.granted_at")
    refusal = body.index("DETAIL = 'ABORT_NOT_DUE'")
    insert = body.index("INSERT INTO action_attempt_state")
    assert lock < clock < refusal < insert and body.count("INSERT INTO") == 1  # one state row, never a job
    for reason in ("'cancelled_before_send'", "'expired'", "'deadline'"):
        assert clock < body.index(f"THEN {reason}") < refusal, reason
    assert "'ABORT_REQUESTED'" in body[insert:] and "RETURN 'resolved'" in body[lock:clock]


def test_the_dispatch_deadline_is_a_helper_granted_to_nobody() -> None:
    module = revision()
    assert "RETURN 300;" in module.DISPATCH_SECONDS and "SECURITY DEFINER" not in module.DISPATCH_SECONDS
    assert privileges.HELPER_FUNCTIONS["_dispatch_seconds"] == ""
    mcp_exec = {name for name, (_, callers) in privileges.DEFINER_FUNCTIONS.items() if "mcp_exec" in callers}
    assert mcp_exec == {
        "current_time",  # erratum 15
        "resolve_invocation",
        "grant_execution",
        "mark_sent",
        "record_outcome",
        "request_abort",
        "lookup_action",
    }
    for name, args, _, _ in module.FUNCTIONS:
        if not name.startswith("_"):
            assert privileges.DEFINER_FUNCTIONS[name][0] == args, name


def test_the_startup_marker_is_only_in_0010s_request_abort() -> None:
    signature, marker = WRITE_PATH
    assert signature == "app.request_abort(text, text, uuid)"
    assert marker in revision().REQUEST_ABORT
    for older in REVISIONS[: REVISIONS.index("0010_write_path")]:
        assert marker not in (VERSIONS / f"{older}.py").read_text(encoding="utf-8"), older


def test_the_newest_body_of_request_abort_carries_the_startup_marker() -> None:
    newest = None
    for name in REVISIONS:  # Alembic order; the newest revision that re-creates the function wins
        for fn, _, _, body in getattr(revision(name), "FUNCTIONS", ()):
            if fn == "request_abort":
                newest = (name, body)
    assert newest is not None and WRITE_PATH[1] in newest[1], newest and newest[0]


def test_no_definer_mcp_write_calls_before_destination_io_raises_a_hash_mismatch() -> None:
    """`OC007` comes only from `record_outcome`, which mcp-write calls after the destination answered and answers
    UNKNOWN on any refusal, so `server.py` has no HASH_MISMATCH mapping left to reach (Plan K ruling 20). Every
    function those calls reach is followed through the newest body any revision installed, so a later revision that
    adds an `OC007` to one of them, or to a helper they call, fails here (round 1, M3)."""
    newest: dict[str, str] = {}
    for name in REVISIONS:  # Alembic order: a later body replaces an earlier one
        for fn, _, _, body in getattr(revision(name), "FUNCTIONS", ()):
            newest[fn] = body
    reached: set[str] = set()
    todo = ["resolve_invocation", "grant_execution", "lookup_action", "mark_sent", "request_abort"]
    while todo:
        fn = todo.pop()
        if fn in reached:
            continue
        reached.add(fn)
        todo += re.findall(r"app\.(\w+)\(", newest.get(fn, ""))
    assert reached - set(newest) == {"current_time"}  # 0002's clock read, defined outside any FUNCTIONS tuple
    assert "'OC007'" not in (VERSIONS / "0002_roles_grants_rls.py").read_text(encoding="utf-8")
    assert {"_resolve_handle", "_grant_row", "_transition", "_append_event", "_dispatch_seconds"} <= reached
    raising = sorted(fn for fn in reached if "'OC007'" in newest.get(fn, ""))
    assert raising == [] and "'OC007'" in newest["record_outcome"]


def test_request_abort_refuses_to_read_a_missing_reason_as_one() -> None:
    """An ABORT_REQUESTED row without a reason must not become the abort reason "None" (round 1, M6)."""

    class NoReason:
        async def execute(self, _query: str, _params: tuple[object, ...]) -> "NoReason":
            return self

        async def fetchone(self) -> dict[str, Any]:
            return {"reason": None}

    conn: Any = NoReason()
    with pytest.raises(persistence.PersistenceError, match="returned no reason"):
        asyncio.run(persistence.request_abort(conn, handle="h", azp="ops-worker", action_id=uuid4()))
```

Create `tests/plan_k/test_mcp_write_startup.py`:

```python
"""mcp-write refuses to start on a database without revision 0010 (Plan K ruling 25), as it does without 0009, and
closes the connection it opened.

Catches: a server that calls the definers with the token's `azp` on a database whose functions still take two
arguments (every call would fail with "function does not exist" at run time instead of at start), a check that asks the
wrong function or for the wrong text, and a failed start that leaks its connection. mcp-read checks nothing new: it
calls none of the functions 0010 changes (`resolve_invocation` keeps its signature).
"""

from typing import Any

import pytest
from ops_core import persistence

from tests.plan_j.test_mcp_read_startup import start, start_write


class MarkerConn:
    """Answers the startup queries: no test clock, 0007's relation present, and each marker present or not."""

    def __init__(self, present: set[str]) -> None:
        self.present = present
        self.closed = False
        self.asked: list[tuple[object, ...]] = []

    async def execute(self, query: str, params: tuple[object, ...] = ()) -> "MarkerConn":
        self.asked.append(params)
        found = "prosrc" in query and bool(params) and params[0] in self.present
        self.row = {"present": found, "missing": False}
        return self

    async def fetchone(self) -> dict[str, Any]:
        return self.row

    async def close(self) -> None:
        self.closed = True


BOTH = {persistence.HANDLE_BINDING[1], persistence.WRITE_PATH[1]}


def test_mcp_write_refuses_a_database_at_0009_and_closes_the_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    conn: Any = MarkerConn({persistence.HANDLE_BINDING[1]})  # 0009's binding is there, 0010's write path is not
    with pytest.raises(persistence.PersistenceError, match="predates this service"):
        start_write(monkeypatch, conn)
    assert conn.closed
    assert conn.asked[-1] == (persistence.WRITE_PATH[1], "app.request_abort(text, text, uuid)")


def test_mcp_write_starts_on_a_database_at_0010(monkeypatch: pytest.MonkeyPatch) -> None:
    conn: Any = MarkerConn(BOTH)
    start_write(monkeypatch, conn)
    assert (persistence.WRITE_PATH[1], "app.request_abort(text, text, uuid)") in conn.asked
    assert conn.closed  # the lifespan's own close at shutdown


def test_mcp_read_does_not_ask_for_0010(monkeypatch: pytest.MonkeyPatch) -> None:
    conn: Any = MarkerConn({persistence.HANDLE_BINDING[1]})
    start(monkeypatch, conn)
    assert all(persistence.WRITE_PATH[1] not in asked for asked in conn.asked)
```

Run: `uv run python -m pytest tests/plan_k/test_migration_0010.py tests/plan_k/test_mcp_write_startup.py tests/plan_e/test_transitions_table.py -q`
Expected: `3 errors in` (collection stops: `ImportError: cannot import name 'WRITE_PATH' from 'ops_core.persistence'`
in `test_migration_0010.py`, `AttributeError: module 'ops_core.persistence' has no attribute 'WRITE_PATH'` in
`test_mcp_write_startup.py`, and the transitions module's check that every listed revision exists fails on
`0010_write_path`).

- [x] **Step 2: The revision**

Create `migrations/app/versions/0010_write_path.py`:

```python
"""The write path of T47 (Plan K rulings 3, 7, 12, 17 and 25): the caller's token `azp`, the dispatch deadline, the
abort request, and an outcome recorded after an abort request.

Revision ID: 0010_write_path
Revises: 0009_handle_binding

The write-path definers named the worker's client with a literal (`_resolve_handle(p_raw_handle, 'ops-worker',
'write')`); `resolve_invocation` compared the presented token's `azp`, but the four definers mcp-write calls next did
not. Each now takes the token's `azp` as its second argument, `client_azp`, as `resolve_invocation` does, so the
worker's client is named once, in settings (ruling 12). `grant_execution`, `lookup_action` and `record_outcome` keep
their applied bodies with only that change (and, in `record_outcome`, the guard below), which a unit test checks by
undoing the replacements; `mark_sent` is rewritten for its new answers, and `request_abort` is new.

- The dispatch deadline (SA:229-231, SA:295; ruling 17): `app._dispatch_seconds()` is 300 (five minutes after the
  grant); `mark_sent` answers `expired`, inserting nothing, when `app.current_time()` is past `granted_at` plus that,
  compared after the runs lock; a cancel is checked first, so a cancelled run is `cancelled` whatever the clock says.
  `mark_sent` also answers `abort_requested`, inserting nothing, once an abort was requested: nothing is sent after
  `ABORT_REQUESTED` (SA:334).
- A re-send is checked as a first send is (Plan K round 1, I1): for an attempt already SENT, `mark_sent` answers
  `cancelled` or `expired` on the same two conditions (the caller then aborts, with the reason `deadline`, SA:248),
  `not_redispatchable` to a recover job (SA:345: a recover job redispatches an unsent attempt only), and otherwise
  `already_sent`. Between `mark_sent`'s commit and the POST a cancel can still land; that window is AM-13's own and the
  same for a first send and a re-send.
- `request_abort` (SA:465; rulings 2 and 3) chooses the reason itself, under the runs lock, from the attempt state,
  the cancel flag and the clock, because mcp-write sees neither the flag nor `granted_at`: `cancelled_before_send`
  (INTENT, cancelled), `expired` (INTENT, past the deadline), `deadline` (SENT, past the deadline or cancelled: an
  immediate abort after a cancel, SA:248). It appends an `ABORT_REQUESTED` row carrying the reason and returns it; a
  second request returns the first one's reason and appends nothing; a resolved attempt answers `resolved`; anything
  else (not cancelled and before the deadline) is refused `ABORT_NOT_DUE`. The caller then POSTs the abort and calls
  `record_outcome` with what the destination answered.
- `record_outcome` accepts SUCCEEDED and CONFLICT when the latest state is SENT, or ABORT_REQUESTED with the reason
  `deadline` (ruling 7, narrowed in round 1): an abort after SENT answered by the receipt that already exists is the
  destination's truth (SA:242), while an abort of an attempt never sent can only meet a tombstone.

Every body, caller and signature is frozen here; the downgrade restores 0009 exactly (R006) by dropping what this
revision created and re-running the applied revisions' own bodies, loaded from their files (the 0007 pattern).
"""

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic import op
from ops_core import privileges

revision = "0010_write_path"
down_revision = "0009_handle_binding"
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


REV0004 = _applied("0004_write_path_functions")
REV0007 = _applied("0007_leases_fences")
HEADER = "LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp SET app.tenant_id = ''"
HELPER_HEADER = REV0004.HELPER_HEADER
LITERAL_AZP = "app._resolve_handle(p_raw_handle, 'ops-worker', 'write')"
TOKEN_AZP = "app._resolve_handle(p_raw_handle, p_client_azp, 'write')"
# The 0007 guard that refused a receipt after an abort request, and 0010's (record_outcome's only logic change).
GUARD_0007 = (
    "    -- SENT is committed before any dispatch, so a receipt or conflict without SENT is a protocol violation;\n"
    "    -- FAILED_NO_COMMIT from INTENT stays allowed for a cancellation before send.\n"
    "    IF p_outcome IN ('SUCCEEDED', 'CONFLICT') AND v_latest.state <> 'SENT' THEN\n"
)
GUARD_0010 = (
    "    -- SENT is committed before any dispatch, so a receipt or conflict without SENT is a protocol violation;\n"
    "    -- FAILED_NO_COMMIT from INTENT stays allowed for a cancellation before send. An abort after SENT may be\n"
    "    -- answered by the receipt that already exists (SA:242; T47, Plan K ruling 7).\n"
    "    -- Only an abort requested after SENT (its reason `deadline`) can meet a receipt; a NULL reason is refused.\n"
    "    IF p_outcome IN ('SUCCEEDED', 'CONFLICT') AND v_latest.state <> 'SENT'\n"
    "       AND NOT (v_latest.state = 'ABORT_REQUESTED'\n"
    "                AND v_latest.detail->>'reason' IS NOT DISTINCT FROM 'deadline') THEN\n"
)
RECORD_SIGNATURE_0007 = "app.record_outcome(p_raw_handle text, p_action_id uuid, p_outcome text, p_document jsonb)"
RECORD_SIGNATURE_0010 = (
    "app.record_outcome(p_raw_handle text, p_client_azp text, p_action_id uuid, p_outcome text,\n"
    "                                      p_document jsonb)"
)
# (old, new) for each body this revision derives from an applied one: the signature, its ALTER line and the literal
# `azp`; record_outcome also gets the guard.
GRANT_CHANGES = (
    (
        "app.grant_execution(p_raw_handle text, p_proposal_id uuid)",
        "app.grant_execution(p_raw_handle text, p_client_azp text, p_proposal_id uuid)",
    ),
    ("ALTER FUNCTION app.grant_execution(text, uuid)", "ALTER FUNCTION app.grant_execution(text, text, uuid)"),
    (LITERAL_AZP, TOKEN_AZP),
)
LOOKUP_CHANGES = (
    ("app.lookup_action(p_raw_handle text)", "app.lookup_action(p_raw_handle text, p_client_azp text)"),
    ("ALTER FUNCTION app.lookup_action(text)", "ALTER FUNCTION app.lookup_action(text, text)"),
    (LITERAL_AZP, TOKEN_AZP),
)
RECORD_CHANGES = (
    (RECORD_SIGNATURE_0007, RECORD_SIGNATURE_0010),
    (
        "ALTER FUNCTION app.record_outcome(text, uuid, text, jsonb)",
        "ALTER FUNCTION app.record_outcome(text, text, uuid, text, jsonb)",
    ),
    (LITERAL_AZP, TOKEN_AZP),
    (GUARD_0007, GUARD_0010),
)


def _derived(body: str, changes: tuple[tuple[str, str], ...]) -> str:
    """`body` with each change applied; a change that does not match exactly once means the applied body moved."""
    for old, new in changes:
        if body.count(old) != 1:
            raise RuntimeError(f"an applied body no longer carries {old!r} exactly once")
        body = body.replace(old, new)
    return body


GRANT_EXECUTION = _derived(REV0007.GRANT_EXECUTION, GRANT_CHANGES)
LOOKUP_ACTION = _derived(REV0004.LOOKUP_ACTION, LOOKUP_CHANGES)
RECORD_OUTCOME = _derived(REV0007.RECORD_OUTCOME, RECORD_CHANGES)

DISPATCH_SECONDS = f"""
CREATE OR REPLACE FUNCTION app._dispatch_seconds() RETURNS integer
{HELPER_HEADER} AS $fn$
BEGIN
    -- SA:295: five minutes after the grant, fixed here until a setting can reach it (T29). Tests move app.test_clock.
    RETURN 300;
END
$fn$;
ALTER FUNCTION app._dispatch_seconds() OWNER TO app_definer;
"""

MARK_SENT = f"""
CREATE OR REPLACE FUNCTION app.mark_sent(p_raw_handle text, p_client_azp text, p_action_id uuid) RETURNS text
{HEADER} AS $fn$
DECLARE
    v_handle record;
    v_grant execution_grant%ROWTYPE;
    v_run runs%ROWTYPE;
    v_latest record;
    v_late boolean;
BEGIN
    PERFORM app._authority('mark_sent', ARRAY['mcp_exec']);
    -- The handle binds the call to its run and its lease fence (SA:463, ruling 5): _resolve_handle takes run_lease FOR
    -- SHARE and refuses OC008 for a revoked or expired handle, a moved fence or a lapsed lease, before runs is locked.
    SELECT * INTO v_handle FROM app._resolve_handle(p_raw_handle, p_client_azp, 'write');
    SELECT * INTO v_grant FROM execution_grant g WHERE g.action_id = p_action_id AND g.run_id = v_handle.run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'action';
    END IF;
    SELECT * INTO v_run FROM runs r WHERE r.run_id = v_grant.run_id FOR UPDATE;  -- serialises the seq (SA:462)
    SELECT * INTO v_latest FROM app._latest_attempt(p_action_id);
    IF v_latest.state = 'RESOLVED' THEN
        RETURN 'resolved';
    ELSIF v_latest.state = 'ABORT_REQUESTED' THEN
        RETURN 'abort_requested';  -- nothing is sent once an abort was requested (SA:334); nothing is written
    END IF;
    v_late := app.current_time() > v_grant.granted_at + make_interval(secs => app._dispatch_seconds());
    -- A re-send of a SENT attempt is re-checked as a first send is (round 1, I1): a cancel or a passed deadline sends
    -- nothing (the caller aborts, SA:248), and a recover job never re-sends (SA:345); nothing is written.
    IF v_latest.state = 'SENT' THEN
        IF v_run.cancel_requested THEN
            RETURN 'cancelled';
        ELSIF v_late THEN
            RETURN 'expired';
        ELSIF v_handle.job_type = 'recover' THEN
            RETURN 'not_redispatchable';
        END IF;
        RETURN 'already_sent';
    END IF;
    -- A run mark_unknown already moved refuses SENT (its fence bump has refused the handle above in any case).
    IF v_run.state <> 'EXECUTING' THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003',
                                                 DETAIL = format('run %s is %s', v_grant.run_id, v_run.state);
    END IF;
    -- SA:463: cancellation, then the dispatch deadline, re-checked under the runs lock before SENT; nothing is written.
    IF v_run.cancel_requested THEN
        RETURN 'cancelled';
    END IF;
    IF v_late THEN
        RETURN 'expired';
    END IF;
    INSERT INTO action_attempt_state (tenant_id, action_id, attempt_no, seq, state, at)
    VALUES (v_handle.tenant_id, p_action_id, v_latest.attempt_no, v_latest.seq + 1, 'SENT', app.current_time());
    PERFORM app._append_event(v_handle.tenant_id, v_grant.run_id,
                              CASE WHEN v_latest.attempt_no > 1 THEN 'action.redispatched' ELSE 'action.dispatched' END,
                              'application', jsonb_build_object('action_id', p_action_id));
    RETURN 'sent';
END
$fn$;
ALTER FUNCTION app.mark_sent(text, text, uuid) OWNER TO app_definer;
"""

REQUEST_ABORT = f"""
CREATE OR REPLACE FUNCTION app.request_abort(p_raw_handle text, p_client_azp text, p_action_id uuid) RETURNS text
{HEADER} AS $fn$
DECLARE
    v_handle record;
    v_grant execution_grant%ROWTYPE;
    v_run runs%ROWTYPE;
    v_latest record;
    v_late boolean;
    v_reason text;
BEGIN
    PERFORM app._authority('request_abort', ARRAY['mcp_exec']);
    -- The same binding as mark_sent (SA:465 "as record_outcome"): the handle's run, its lease fence, then runs.
    SELECT * INTO v_handle FROM app._resolve_handle(p_raw_handle, p_client_azp, 'write');
    SELECT * INTO v_grant FROM execution_grant g WHERE g.action_id = p_action_id AND g.run_id = v_handle.run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'action';
    END IF;
    SELECT * INTO v_run FROM runs r WHERE r.run_id = v_grant.run_id FOR UPDATE;
    SELECT * INTO v_latest FROM app._latest_attempt(p_action_id);
    IF v_latest.state = 'RESOLVED' THEN
        RETURN 'resolved';  -- the outcome stands; the caller reads it back
    ELSIF v_latest.state = 'ABORT_REQUESTED' THEN
        RETURN v_latest.detail->>'reason';  -- idempotent: the first request's reason stands
    END IF;
    -- The server chooses the reason (T47, Plan K ruling 3), compared after the lock: INTENT was never sent, so its
    -- abort is a guaranteed no-commit; after SENT a cancel aborts at once (SA:248), otherwise only past the deadline.
    v_late := app.current_time() > v_grant.granted_at + make_interval(secs => app._dispatch_seconds());
    v_reason := CASE
        WHEN v_latest.state = 'INTENT' AND v_run.cancel_requested THEN 'cancelled_before_send'
        WHEN v_latest.state = 'INTENT' AND v_late THEN 'expired'
        WHEN v_latest.state = 'SENT' AND (v_run.cancel_requested OR v_late) THEN 'deadline'
    END;
    IF v_reason IS NULL THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'ABORT_NOT_DUE';
    END IF;
    INSERT INTO action_attempt_state (tenant_id, action_id, attempt_no, seq, state, detail, at)
    VALUES (v_handle.tenant_id, p_action_id, v_latest.attempt_no, v_latest.seq + 1, 'ABORT_REQUESTED',
            jsonb_build_object('reason', v_reason), app.current_time());
    RETURN v_reason;
END
$fn$;
ALTER FUNCTION app.request_abort(text, text, uuid) OWNER TO app_definer;
"""

# (name, argument types, callers, body): frozen here (N1); the newest-revision test reads this tuple.
FUNCTIONS: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("_dispatch_seconds", "", (), DISPATCH_SECONDS),
    ("grant_execution", "text, text, uuid", ("mcp_exec",), GRANT_EXECUTION),
    ("lookup_action", "text, text", ("mcp_exec",), LOOKUP_ACTION),
    ("mark_sent", "text, text, uuid", ("mcp_exec",), MARK_SENT),
    ("record_outcome", "text, text, uuid, text, jsonb", ("mcp_exec",), RECORD_OUTCOME),
    ("request_abort", "text, text, uuid", ("mcp_exec",), REQUEST_ABORT),
)
# Signatures upgrade() drops before FUNCTIONS re-creates the four with the `client_azp` argument.
REPLACED: tuple[str, ...] = (
    "grant_execution(text, uuid)",
    "lookup_action(text)",
    "mark_sent(text, uuid)",
    "record_outcome(text, uuid, text, jsonb)",
)
# Signatures downgrade() drops: everything FUNCTIONS created.
CREATED: tuple[str, ...] = tuple(f"{name}({args})" for name, args, _, _ in reversed(FUNCTIONS))
# What downgrade() re-creates afterwards, from the applied revisions' own bodies: (name, args, callers, body).
RESTORED: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("grant_execution", "text, uuid", ("mcp_exec",), REV0007.GRANT_EXECUTION),
    ("lookup_action", "text", ("mcp_exec",), REV0004.LOOKUP_ACTION),
    ("mark_sent", "text, uuid", ("mcp_exec",), REV0007.MARK_SENT),
    ("record_outcome", "text, uuid, text, jsonb", ("mcp_exec",), REV0007.RECORD_OUTCOME),
)


def upgrade() -> None:
    """Drop the four signatures that change, then create each function (body first, then its grants, so REVOKE lands
    on it)."""
    for signature in REPLACED:
        op.execute(f"DROP FUNCTION app.{signature}")
    for name, args, callers, body in FUNCTIONS:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)


def downgrade() -> None:
    """Back to 0009: drop what 0010 created, then re-create the four applied bodies with their grants; no row is
    touched (an `ABORT_REQUESTED` row a test left stays, though 0009's `mark_sent` would not honour it)."""
    for signature in CREATED:
        op.execute(f"DROP FUNCTION app.{signature}")
    for name, args, callers, body in RESTORED:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)
```

Run: `uv run ruff check --select ISC004 --fix --unsafe-fixes migrations/app/versions/0010_write_path.py`
Expected: `All checks passed!` (the file above is already in its fixed form).

- [x] **Step 3: The matrix and the persistence wrappers**

Edit 1 (`core/src/ops_core/privileges.py`, in `DEFINER_FUNCTIONS`), replace:

```python
    "grant_execution": ("text, uuid", ("mcp_exec",)),
    "mark_sent": ("text, uuid", ("mcp_exec",)),  # T13: the raw handle first, so the fence is checked (erratum 48)
    "record_outcome": ("text, uuid, text, jsonb", ("mcp_exec",)),  # likewise
    "lookup_action": ("text", ("mcp_exec",)),
```

with:

```python
    # T13: the raw handle first, so the fence is checked (erratum 48); T47: the token's azp second (Plan K ruling 12).
    "grant_execution": ("text, text, uuid", ("mcp_exec",)),
    "mark_sent": ("text, text, uuid", ("mcp_exec",)),
    "record_outcome": ("text, text, uuid, text, jsonb", ("mcp_exec",)),
    "lookup_action": ("text, text", ("mcp_exec",)),
    "request_abort": ("text, text, uuid", ("mcp_exec",)),  # T47 (Plan K rulings 2, 3)
```

Edit 2 (`core/src/ops_core/privileges.py`, in `HELPER_FUNCTIONS`), replace:

```python
    "_transition": "uuid, text, text, text, integer, text, jsonb",
}
```

with:

```python
    "_transition": "uuid, text, text, text, integer, text, jsonb",
    "_dispatch_seconds": "",  # T47: the dispatch deadline, 300 s (Plan K ruling 17)
}
```

Edit 3 (`core/src/ops_core/persistence.py`, in `HANDLE_BINDING`), replace:

```python
HANDLE_BINDING: Final = ("app._resolve_handle(text, text, text)", "j.run_id = v_ctx.run_id AND j.done_at IS NULL")

```

with:

```python
HANDLE_BINDING: Final = ("app._resolve_handle(text, text, text)", "j.run_id = v_ctx.run_id AND j.done_at IS NULL")
# Revision 0010 (T47): the write-path definers take the token's azp and `request_abort` exists; mcp-write calls them
# with the new signatures, so it refuses to start without them (Plan K ruling 25). The same rule as above: a later
# revision that re-creates `request_abort` keeps this text or changes it here in the same commit.
WRITE_PATH: Final = ("app.request_abort(text, text, uuid)", "ABORT_NOT_DUE")

```

Edit 4 (`core/src/ops_core/persistence.py`, in `grant_execution`), replace:

```python
async def grant_execution(conn: Conn, *, handle: str, proposal_id: UUID) -> Grant:
    """The §13 gate inside the function; a replay returns the grant the run already has (SA:462)."""
    row = await _call(conn, "SELECT * FROM app.grant_execution(%s, %s)", (handle, proposal_id))
```

with:

```python
# The write-path definers take the presented token's `azp` (revision 0010, Plan K ruling 12): `_resolve_handle`
# compares it with the one the handle was minted for, as `resolve_invocation` always did.


async def grant_execution(conn: Conn, *, handle: str, azp: str, proposal_id: UUID) -> Grant:
    """The §13 gate inside the function; a replay returns the grant the run already has (SA:462)."""
    row = await _call(conn, "SELECT * FROM app.grant_execution(%s, %s, %s)", (handle, azp, proposal_id))
```

Edit 5 (`core/src/ops_core/persistence.py`, in `lookup_action`), replace:

```python
async def lookup_action(conn: Conn, *, handle: str) -> Grant:
    """The run's grant for a same-key redispatch or a final read-back (SA:466); NotFound before any grant."""
    row = await _call(conn, "SELECT * FROM app.lookup_action(%s)", (handle,))
```

with:

```python
async def lookup_action(conn: Conn, *, handle: str, azp: str) -> Grant:
    """The run's grant for a same-key redispatch or a final read-back (SA:466); NotFound before any grant."""
    row = await _call(conn, "SELECT * FROM app.lookup_action(%s, %s)", (handle, azp))
```

Edit 6 (`core/src/ops_core/persistence.py`, in `mark_sent`), replace:

```python
async def mark_sent(conn: Conn, *, handle: str, action_id: UUID) -> str:
    """`sent`, `already_sent`, `resolved` or `cancelled` (SA:463); committed by the caller before any I/O. The handle
    binds the call to the run's lease fence (Plan H ruling 5): a moved fence or a lapsed lease is HandleRejected."""
    row = await _call(conn, "SELECT app.mark_sent(%s, %s) AS outcome", (handle, action_id))
```

with:

```python
async def mark_sent(conn: Conn, *, handle: str, azp: str, action_id: UUID) -> str:
    """`sent`, `already_sent`, `resolved`, `cancelled`, `expired` (the dispatch deadline passed), `abort_requested` or
    `not_redispatchable` (a recover job and a SENT attempt) (SA:463, revision 0010); committed by the caller before any
    I/O, and only `sent` and `already_sent` permit a POST.
    The handle binds the call to the run's lease fence (Plan H ruling 5): a moved fence or a lapsed lease is
    HandleRejected."""
    row = await _call(conn, "SELECT app.mark_sent(%s, %s, %s) AS outcome", (handle, azp, action_id))
```

Edit 7 (`core/src/ops_core/persistence.py`, in `record_outcome`), replace:

```python
async def record_outcome(conn: Conn, *, handle: str, action_id: UUID, outcome: ActionOutcome) -> ToolOutcome:
```

with:

```python
async def request_abort(conn: Conn, *, handle: str, azp: str, action_id: UUID) -> str:
    """The abort reason the function chose and recorded as `ABORT_REQUESTED` (`cancelled_before_send`, `expired` or
    `deadline`; a repeat returns the first reason), or `resolved` when the outcome already stands (SA:465, Plan K
    ruling 3). Refused `ABORT_NOT_DUE` while the run is not cancelled and the dispatch deadline has not passed. The
    caller commits it before POSTing the abort."""
    row = await _call(conn, "SELECT app.request_abort(%s, %s, %s) AS reason", (handle, azp, action_id))
    if row is None or row["reason"] is None:  # never POST an abort whose reason reads "None"
        raise PersistenceError("request_abort returned no reason")
    return str(row["reason"])


async def record_outcome(conn: Conn, *, handle: str, azp: str, action_id: UUID, outcome: ActionOutcome) -> ToolOutcome:
```

Edit 8 (`core/src/ops_core/persistence.py`, in `record_outcome`), replace:

```python
        "SELECT app.record_outcome(%s, %s, %s, %s) AS outcome",
        (handle, action_id, outcome.status.value, Jsonb(outcome.model_dump(mode="json"))),
```

with:

```python
        "SELECT app.record_outcome(%s, %s, %s, %s, %s) AS outcome",
        (handle, azp, action_id, outcome.status.value, Jsonb(outcome.model_dump(mode="json"))),
```

- [x] **Step 4: mcp-write hands the token's azp on and checks for 0010 at start**

`mark_sent`'s new answers mean "nothing was sent"; until Task 3 builds the abort, `create_incident` answers them as it
answered `cancelled`.

Edit 1 (`mcp-write/src/ops_mcp_write/execution.py`, in `_read_back`), replace:

```python
async def _read_back(deps: Deps, handle: str, grant: persistence.Grant) -> ActionOutcome:
```

with:

```python
async def _read_back(deps: Deps, handle: str, azp: str, grant: persistence.Grant) -> ActionOutcome:
```

Edit 2 (`mcp-write/src/ops_mcp_write/execution.py`, in `_read_back`), replace:

```python
            return _stored(await persistence.lookup_action(conn, handle=handle))
```

with:

```python
            return _stored(await persistence.lookup_action(conn, handle=handle, azp=azp))
```

Edit 3 (`mcp-write/src/ops_mcp_write/execution.py`, in `create_incident`), replace:

```python
async def create_incident(deps: Deps, *, handle: str, proposal_id: UUID) -> ActionOutcome:
    """Four units of work in AM-13 order; the destination call sits between two commits, never inside one."""
    async with deps.session.unit() as conn:  # the functions resolve the handle and set the tenant themselves
        grant = await persistence.grant_execution(conn, handle=handle, proposal_id=proposal_id)
```

with:

```python
async def create_incident(deps: Deps, *, handle: str, azp: str, proposal_id: UUID) -> ActionOutcome:
    """Four units of work in AM-13 order; the destination call sits between two commits, never inside one. `azp` is
    the presented token's, which every definer compares with the handle's (revision 0010)."""
    async with deps.session.unit() as conn:  # the functions resolve the handle and set the tenant themselves
        grant = await persistence.grant_execution(conn, handle=handle, azp=azp, proposal_id=proposal_id)
```

Edit 4 (`mcp-write/src/ops_mcp_write/execution.py`, in `create_incident`), replace:

```python
        async with deps.session.unit() as conn:
            sent = await persistence.mark_sent(conn, handle=handle, action_id=grant.action_id)  # committed before I/O
        if sent == "resolved":  # a concurrent caller finished first
            return await _read_back(deps, handle, grant)
        if sent == "cancelled":
            # The UNKNOWN envelope makes the worker call mark_unknown, which moves the run to OUTCOME_UNKNOWN and
            # queues a recover job although nothing was sent: conservative. TODO(T22): request_abort and the abort
            # POST replace this.
```

with:

```python
        async with deps.session.unit() as conn:  # committed before I/O
            sent = await persistence.mark_sent(conn, handle=handle, azp=azp, action_id=grant.action_id)
        if sent == "resolved":  # a concurrent caller finished first
            return await _read_back(deps, handle, azp, grant)
        if sent in ("cancelled", "expired", "abort_requested"):
            # Nothing was sent. The UNKNOWN envelope makes the worker call mark_unknown, which moves the run to
            # OUTCOME_UNKNOWN and queues a recover job: conservative. TODO(T47): the abort replaces this (SA:348).
```

Edit 5 (`mcp-write/src/ops_mcp_write/execution.py`, in `create_incident`), replace:

```python
            standing = await persistence.record_outcome(conn, handle=handle, action_id=grant.action_id, outcome=outcome)
```

with:

```python
            standing = await persistence.record_outcome(
                conn, handle=handle, azp=azp, action_id=grant.action_id, outcome=outcome
            )
```

Edit 6 (`mcp-write/src/ops_mcp_write/execution.py`, in `create_incident`), replace:

```python
    # A concurrent caller's record stands: read it back in its own unit.
    return await _read_back(deps, handle, grant)
```

with:

```python
    # A concurrent caller's record stands: read it back in its own unit.
    return await _read_back(deps, handle, azp, grant)
```

Edit 7 (`mcp-write/src/ops_mcp_write/server.py`, in `build_server`), replace:

```python
            outcome = await execution.create_incident(state.deps, handle=handle, proposal_id=proposal_id)
```

with:

```python
            outcome = await execution.create_incident(
                state.deps, handle=handle, azp=token.client_id, proposal_id=proposal_id
            )
```

Edit 8 (`mcp-write/src/ops_mcp_write/server.py`, in `build_app`), replace:

```python
            except BaseException:  # a failed start must leak no connection
```

with:

```python
                # Revision 0010: the definers this server calls take the token's azp, and request_abort exists (T47).
                await persistence.assert_function_text(conn, *persistence.WRITE_PATH)
            except BaseException:  # a failed start must leak no connection
```

Run: `uv run python -m pytest tests/plan_k tests/plan_e/test_transitions_table.py -q`
Expected: `42 passed` (27 in `tests/plan_k`, 15 in the transitions module).

- [x] **Step 5: Every write-path call site in the tests**

Ten test modules call the four functions with the old signatures, as SQL strings or through the persistence wrappers
and `execution.create_incident`, and one Plan H module fakes them. Every live handle there is minted for `ops-worker`,
so the token's `azp` they present is that. Run from the repository root (it writes nothing unless every file changes
exactly as often as listed):

```bash
uv run python - <<'EOF'
import re
import sys
from pathlib import Path

SQL = [
    (r"app\.grant_execution\(%s, %s\)", "app.grant_execution(%s, 'ops-worker', %s)"),
    (r"app\.mark_sent\(%s, %s\)", "app.mark_sent(%s, 'ops-worker', %s)"),
    (r"app\.lookup_action\(%s\)", "app.lookup_action(%s, 'ops-worker')"),
    (r"app\.record_outcome\(%s, %s, ", "app.record_outcome(%s, 'ops-worker', %s, "),
]
WRAPPER = [
    (
        r"(persistence\.(?:grant_execution|mark_sent|lookup_action|record_outcome)\(\s*[\w.]+,\s*handle=\w+)",
        r'\1, azp="ops-worker"',
    ),
    (r'(execution\.create_incident\((?:[^()]|\([^()]*\))*?handle=(?:handle|"h"))', r'\1, azp="ops-worker"'),
]
FAKES = [(r"\*, handle: str, action_id", "*, handle: str, azp: str, action_id")]
EXPECTED = {
    "tests/e2e/test_definers_write_path_live.py": 28,
    "tests/e2e/test_event_journal_live.py": 5,
    "tests/e2e/test_fenced_definers_live.py": 5,
    "tests/e2e/test_lease_stress_live.py": 1,
    "tests/e2e/test_mcp_read_t15_live.py": 1,
    "tests/e2e/test_mcp_write_live.py": 6,
    "tests/e2e/test_migrations_and_persistence.py": 2,
    "tests/e2e/test_outbox_live.py": 4,
    "tests/e2e/test_worker_live.py": 4,
    "tests/plan_h/test_write_path_fence.py": 5,
}
changed = {}
for name, expected in EXPECTED.items():
    text = Path(name).read_text(encoding="utf-8")
    total = 0
    for pattern, replacement in SQL + WRAPPER + FAKES:
        text, n = re.subn(pattern, replacement, text)
        total += n
    if total != expected:
        sys.exit(f"{name}: {total} replacements, expected {expected}; nothing written")
    changed[name] = text
for name, text in changed.items():
    Path(name).write_text(text, encoding="utf-8", newline="\n")
print(f"rewritten: {len(changed)} files, {sum(EXPECTED.values())} call sites")
EOF
```

Expected: `rewritten: 10 files, 61 call sites`. Fifteen rewritten lines are now longer than 120 characters, so run
`uv run ruff format tests/e2e tests/plan_h`: it prints `4 files reformatted, 41 files left unchanged` (it rewraps them
in `test_definers_write_path_live.py`, `test_fenced_definers_live.py`, `test_mcp_read_t15_live.py` and
`test_outbox_live.py`), and the counting command over the ten files then prints nothing.
(`tests/e2e/test_mcp_read_t15_live.py`'s one site is the read half's `42501` probe: `grant_execution(text, uuid)` no
longer exists, so without the rewrite it would answer `42883`.)

The 0007 round trip's last line asserts the head's `mark_sent` signature, which 0010 replaces:

Edit 1 (`tests/e2e/test_migration_0007_live.py`, in `test_the_round_trip_restores_0006`), replace:

```python
    assert await exists(app_conn, "app.mark_sent(text, uuid)") and not await exists(app_conn, "app.mark_sent(uuid)")
```

with:

```python
    # The head's signature: revision 0010 replaced 0007's with one that takes the token's azp (T47).
    assert await exists(app_conn, "app.mark_sent(text, text, uuid)")
    assert not await exists(app_conn, "app.mark_sent(uuid)") and not await exists(app_conn, "app.mark_sent(text, uuid)")
```

Run: `uv run python -m pytest tests/plan_k tests/plan_e/test_transitions_table.py tests/plan_h tests/plan_j -q`
Expected: `213 passed`.

- [x] **Step 6: The live revision test**

Create `tests/e2e/test_migration_0010_live.py`:

```python
"""Revision 0010 against the per-session test database (OPS_LIVE=1; Plan K rulings 3, 7, 12, 17 and 25), each definer
called by its real caller, `mcp_exec`.

Catches: a downgrade that leaves 0010's functions behind or restores the four applied bodies differently from a
database that never saw 0010, or an upgrade that does not bring 0010 back; mcp-write's startup check passing at 0009;
`mark_sent` writing SENT past the dispatch deadline, after an abort request, or answering `expired` for a cancelled
run, and allowing the re-send of a SENT attempt after a cancel, past the deadline or to a recover job;
`request_abort` writing a row when no abort is due, choosing the wrong reason, or writing a second row on a repeat;
a receipt refused after an abort requested after SENT (an abort answered by the existing receipt is the destination's
truth), or accepted after one requested before SENT (nothing was ever sent); and a
write-path definer that still compares a literal `'ops-worker'` instead of the presented token's `azp` (a handle
minted for a renamed client is refused with the old name and accepted with its own, at every one of the five).
"""

import importlib.util
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from ops_core import persistence, settings
from ops_core.jobs import Server, Tool
from ops_core.outcomes import ActionOutcome, DestinationState, Receipt, Tombstone, ToolOutcome
from ops_core.settings import Profile, Role
from ops_core.states import Reason
from psycopg import sql
from psycopg.rows import dict_row

from tests.e2e.conftest import lease_for, purge_run
from tests.e2e.test_fenced_definers_live import attempt_states
from tests.e2e.test_mcp_write_live import ALPHA, approved_run
from tests.e2e.test_migration_0007_live import FUNCTION_DETAILS, LEFTOVERS, exists

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "app" / "versions"
AZP = "ops-worker"  # the client every live handle is minted for (the worker's token source's)
SCRATCH_PREFIX = "r009_"  # every scratch database this module creates; leftovers are dropped by prefix
LATE = "UPDATE app.test_clock SET clock_offset = interval '400 seconds'"  # past the 300 s dispatch deadline
NOW = "UPDATE app.test_clock SET clock_offset = interval '0'"
APP_FUNCTIONS = (
    "SELECT p.oid::regprocedure::text AS signature, pg_get_functiondef(p.oid) AS body, p.proacl::text AS acl,"
    " p.proowner::regrole::text AS owner, p.proconfig::text AS config"
    " FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'app'"
)


def revision_0010() -> Any:
    """Revision 0010 loaded by path, for the bodies it creates and the ones its downgrade restores."""
    spec = importlib.util.spec_from_file_location("live_rev_0010", VERSIONS / "0010_write_path.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def built_to_0009(superuser: settings.Postgres, signatures: list[str]) -> dict[str, dict[str, Any]]:
    """The functions' details as a database built straight to 0009 holds them (the 0007 module's pattern): a scratch
    database is created, upgraded by the applied revisions alone, read and dropped."""
    from scripts.skeleton import upgrade

    scratch = f"{SCRATCH_PREFIX}{uuid4().hex[:12]}"
    try:
        with psycopg.connect(superuser.conninfo(), autocommit=True, row_factory=dict_row) as admin:
            for row in admin.execute(LEFTOVERS, (SCRATCH_PREFIX,)).fetchall():
                admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(row["datname"])))
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(scratch)))
        target = settings.Postgres(superuser.host, superuser.port, superuser.user, scratch, superuser.password)
        upgrade("app", target, "0009_handle_binding")
        with psycopg.connect(target.conninfo(), row_factory=dict_row) as conn:
            return {name: dict(conn.execute(FUNCTION_DETAILS, (name,)).fetchone() or {}) for name in signatures}
    finally:
        with psycopg.connect(superuser.conninfo(), autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(scratch)))


async def snapshot(conn: persistence.Conn) -> dict[str, dict[str, Any]]:
    """Every `app` function's definition, ACL, owner and settings, by signature."""
    cur = await conn.execute(APP_FUNCTIONS)
    return {row["signature"]: {k: v for k, v in row.items() if k != "signature"} for row in await cur.fetchall()}


async def test_the_round_trip_restores_0009(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    from scripts.skeleton import downgrade, migrate

    superuser = settings.superuser_postgres()
    mcp_exec = await role_conn(Role.MCP_EXEC)
    module = revision_0010()
    head = await snapshot(app_conn)
    created = [f"app.{name}({args})" for name, args, _, _ in module.FUNCTIONS]
    restored = [f"app.{name}({args})" for name, args, _, _ in module.RESTORED]
    assert all([await exists(app_conn, s) for s in created]) and not any([await exists(app_conn, s) for s in restored])
    await persistence.assert_function_text(mcp_exec, *persistence.WRITE_PATH)  # mcp-write starts on the head
    try:
        downgrade("app", superuser, "0009_handle_binding")
        assert not any([await exists(app_conn, s) for s in created])
        # The four applied bodies are back exactly (the stored source is the text between the dollar quotes) ...
        for name, args, _, body in module.RESTORED:
            cur = await app_conn.execute(
                "SELECT prosrc FROM pg_proc WHERE oid = %s::regprocedure", (f"app.{name}({args})",)
            )
            assert (await cur.fetchone())["prosrc"] == body.split("$fn$")[1], name
        # ... and so are their definitions, ACLs, owners and settings, against a database that never saw 0010.
        reference = built_to_0009(superuser, restored)
        for signature in restored:
            cur = await app_conn.execute(FUNCTION_DETAILS, (signature,))
            assert dict(await cur.fetchone()) == reference[signature], signature
        with pytest.raises(persistence.PersistenceError, match="predates this service"):
            await persistence.assert_function_text(mcp_exec, *persistence.WRITE_PATH)  # mcp-write refuses 0009
    finally:
        assert migrate(Profile.TEST) == 0  # every later test needs the head
    assert await snapshot(app_conn) == head  # the upgrade brings back exactly what the downgrade took


async def execute_handle(worker: persistence.Conn, run: UUID, *, azp: str = AZP, fence: int | None = None) -> str:
    """A fresh write handle for the run's execute job: under a lease taken now (the old one lapsed with the moved
    clock), or at `fence` when the current lease is still live."""
    if fence is None:
        fence = (await lease_for(worker, run, owner=f"k-{uuid4().hex[:8]}", seconds=600)).fence
    async with worker.transaction():
        await persistence.set_tenant(worker, ALPHA)
        cur = await worker.execute("SELECT id FROM app.jobs WHERE run_id = %s AND type = 'execute'", (run,))
        job = UUID(str((await cur.fetchone() or {})["id"]))
        return await persistence.mint_handle(worker, run_id=run, job_id=job, server=Server.WRITE, azp=azp, fence=fence)


async def fence_of(app_conn: persistence.Conn, run: UUID) -> int:
    cur = await app_conn.execute("SELECT fence FROM app.run_lease WHERE run_id = %s", (run,))
    return int((await cur.fetchone() or {})["fence"])


async def recover_handle(app_conn: persistence.Conn, worker: persistence.Conn, run: UUID, trigger: str) -> str:
    """A recover job for the run, staged by the superuser as mark_unknown or the sweeper would queue it (the worker's
    recover handler is T22's), and its write handle at the run's current fence."""
    job = uuid4()
    await app_conn.execute(
        "INSERT INTO app.jobs (id, type, tenant_id, run_id, dedup_key) VALUES (%s, 'recover', %s, %s, %s)",
        (job, ALPHA, run, f"{uuid4()}:{trigger}"),
    )
    async with worker.transaction():
        return await persistence.mint_handle(
            worker, run_id=run, job_id=job, server=Server.WRITE, azp=AZP, fence=await fence_of(app_conn, run)
        )


async def cancel(api: persistence.Conn, run: UUID) -> None:
    """What the API's cancel does to the run row (its one column cell; the cancel endpoint itself is T21's)."""
    async with api.transaction():
        await persistence.set_tenant(api, ALPHA)
        cur = await api.execute(
            "UPDATE app.runs SET cancel_requested = true, cancel_requested_at = now() WHERE run_id = %s", (run,)
        )
        assert cur.rowcount == 1


def aborted(grant: persistence.Grant, token: str, reason: Reason) -> ActionOutcome:
    """The FAILED_NO_COMMIT outcome an ABORTED tombstone with the destination's `token` proves."""
    tombstone = Tombstone(
        action_id=grant.action_id,
        state=DestinationState.ABORTED,
        payload_sha256=grant.payload_sha256,
        reason=token,
        decided_at=datetime.now(UTC),
    )
    return ActionOutcome(
        status=ToolOutcome.FAILED_NO_COMMIT,
        action_id=grant.action_id,
        payload_sha256=grant.payload_sha256,
        receipt=None,
        tombstone=tombstone,
        reason=reason,
    )


def committed(grant: persistence.Grant) -> ActionOutcome:
    receipt = Receipt(receipt_id=uuid4(), incident_id="INC-999001", committed_at=datetime.now(UTC))
    return ActionOutcome(
        status=ToolOutcome.SUCCEEDED,
        action_id=grant.action_id,
        payload_sha256=grant.payload_sha256,
        receipt=receipt,
        tombstone=None,
        reason=None,
    )


async def run_state(app_conn: persistence.Conn, run: UUID) -> tuple[str, str | None]:
    cur = await app_conn.execute("SELECT state, reason FROM app.runs WHERE run_id = %s", (run,))
    row = await cur.fetchone() or {}
    return row["state"], row["reason"]


async def test_past_the_deadline_nothing_is_sent_and_the_abort_says_expired(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """Ruling 17: the grant at t0, the clock 400 s on; mark_sent answers `expired` and writes nothing, the abort
    request records `expired` once, mark_sent then answers `abort_requested`, and the tombstone ends the run FAILED
    with `expired`."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    mcp_exec, harness = await role_conn(Role.MCP_EXEC), await role_conn(Role.TEST_HARNESS)
    _, run, proposal, handle = await approved_run(app_conn, api=api, worker=worker)
    try:
        grant = await persistence.grant_execution(mcp_exec, handle=handle, azp=AZP, proposal_id=proposal)
        try:
            await harness.execute(LATE)
            fresh = await execute_handle(worker, run)
            action = grant.action_id
            assert await persistence.mark_sent(mcp_exec, handle=fresh, azp=AZP, action_id=action) == "expired"
            assert await attempt_states(app_conn, run) == ["INTENT"]  # nothing written, so nothing may be sent
            assert await persistence.request_abort(mcp_exec, handle=fresh, azp=AZP, action_id=action) == "expired"
            assert await persistence.request_abort(mcp_exec, handle=fresh, azp=AZP, action_id=action) == "expired"
            assert await persistence.mark_sent(mcp_exec, handle=fresh, azp=AZP, action_id=action) == "abort_requested"
            assert await attempt_states(app_conn, run) == ["INTENT", "ABORT_REQUESTED"]  # one row for two requests
            standing = await persistence.record_outcome(
                mcp_exec, handle=fresh, azp=AZP, action_id=action, outcome=aborted(grant, "expired", Reason.EXPIRED)
            )
            assert standing is ToolOutcome.FAILED_NO_COMMIT
            assert await persistence.request_abort(mcp_exec, handle=fresh, azp=AZP, action_id=action) == "resolved"
        finally:
            await harness.execute(NOW)
        assert await run_state(app_conn, run) == ("FAILED", "expired")
        assert await attempt_states(app_conn, run) == ["INTENT", "ABORT_REQUESTED", "RESOLVED"]
        cur = await app_conn.execute("SELECT type, source FROM app.events WHERE run_id = %s ORDER BY sequence", (run,))
        assert [(r["type"], r["source"]) for r in await cur.fetchall()][-2:] == [
            ("action.granted", "application"),
            ("action.failed", "destination"),  # no action.dispatched: nothing was ever sent
        ]
    finally:
        await purge_run(app_conn, run)


async def test_a_cancel_comes_first_and_a_sent_attempt_aborts_only_when_due(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """Rulings 3 and 7: no abort is due before a cancel or the deadline (nothing is written); a cancelled INTENT run
    is `cancelled` and `cancelled_before_send` even past the deadline, and a receipt can never be recorded after that
    abort (nothing was sent); a SENT attempt aborts with `deadline` once the deadline passes, and the receipt the abort
    meets is recorded as SUCCEEDED."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    mcp_exec, harness = await role_conn(Role.MCP_EXEC), await role_conn(Role.TEST_HARNESS)
    _, first, first_proposal, first_handle = await approved_run(app_conn, api=api, worker=worker)
    _, second, second_proposal, second_handle = await approved_run(app_conn, api=api, worker=worker)
    try:
        one = await persistence.grant_execution(mcp_exec, handle=first_handle, azp=AZP, proposal_id=first_proposal)
        two = await persistence.grant_execution(mcp_exec, handle=second_handle, azp=AZP, proposal_id=second_proposal)
        with pytest.raises(persistence.Refused) as early:
            await persistence.request_abort(mcp_exec, handle=first_handle, azp=AZP, action_id=one.action_id)
        assert early.value.code == "ABORT_NOT_DUE" and await attempt_states(app_conn, first) == ["INTENT"]
        await cancel(api, first)
        assert await persistence.mark_sent(mcp_exec, handle=second_handle, azp=AZP, action_id=two.action_id) == "sent"
        with pytest.raises(persistence.Refused) as sent_early:
            await persistence.request_abort(mcp_exec, handle=second_handle, azp=AZP, action_id=two.action_id)
        assert sent_early.value.code == "ABORT_NOT_DUE" and await attempt_states(app_conn, second) == ["INTENT", "SENT"]
        try:
            await harness.execute(LATE)
            first_fresh, second_fresh = await execute_handle(worker, first), await execute_handle(worker, second)
            sent = await persistence.mark_sent(mcp_exec, handle=first_fresh, azp=AZP, action_id=one.action_id)
            assert sent == "cancelled"  # the cancel wins over the deadline
            reason = await persistence.request_abort(mcp_exec, handle=first_fresh, azp=AZP, action_id=one.action_id)
            assert reason == "cancelled_before_send"
            with pytest.raises(persistence.VersionConflict):  # an abort before SENT cannot meet a receipt (round 1, M7)
                await persistence.record_outcome(
                    mcp_exec, handle=first_fresh, azp=AZP, action_id=one.action_id, outcome=committed(one)
                )
            reason = await persistence.request_abort(mcp_exec, handle=second_fresh, azp=AZP, action_id=two.action_id)
            assert reason == "deadline"
            standing = await persistence.record_outcome(
                mcp_exec, handle=second_fresh, azp=AZP, action_id=two.action_id, outcome=committed(two)
            )
            assert standing is ToolOutcome.SUCCEEDED  # refused before 0010: the latest state was not SENT
        finally:
            await harness.execute(NOW)
        assert await attempt_states(app_conn, first) == ["INTENT", "ABORT_REQUESTED"]
        assert await attempt_states(app_conn, second) == ["INTENT", "SENT", "ABORT_REQUESTED", "RESOLVED"]
        assert await run_state(app_conn, second) == ("SUCCEEDED", None)
    finally:
        await purge_run(app_conn, first)
        await purge_run(app_conn, second)


async def test_a_re_send_is_checked_as_a_first_send_is(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    """Round 1, I1: an attempt already SENT is re-sent (`already_sent`) only to an execute job, while the run is not
    cancelled and the dispatch deadline has not passed; a recover job gets `not_redispatchable`, a passed deadline
    `expired`, a cancel `cancelled` (first, whatever the clock says), and none of them writes a row."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    mcp_exec, harness = await role_conn(Role.MCP_EXEC), await role_conn(Role.TEST_HARNESS)
    _, run, proposal, handle = await approved_run(app_conn, api=api, worker=worker)
    try:
        grant = await persistence.grant_execution(mcp_exec, handle=handle, azp=AZP, proposal_id=proposal)
        action = grant.action_id
        assert await persistence.mark_sent(mcp_exec, handle=handle, azp=AZP, action_id=action) == "sent"
        assert await persistence.mark_sent(mcp_exec, handle=handle, azp=AZP, action_id=action) == "already_sent"
        recover = await recover_handle(app_conn, worker, run, "timeout")
        answer = await persistence.mark_sent(mcp_exec, handle=recover, azp=AZP, action_id=action)
        assert answer == "not_redispatchable"  # SA:345: a recover job redispatches an unsent attempt only
        try:
            await harness.execute(LATE)
            fresh = await execute_handle(worker, run)  # the first lease lapsed with the clock
            assert await persistence.mark_sent(mcp_exec, handle=fresh, azp=AZP, action_id=action) == "expired"
            await cancel(api, run)
            assert await persistence.mark_sent(mcp_exec, handle=fresh, azp=AZP, action_id=action) == "cancelled"
        finally:
            await harness.execute(NOW)
        assert await attempt_states(app_conn, run) == ["INTENT", "SENT"]  # nothing written by any refusal
        cur = await app_conn.execute("SELECT type FROM app.events WHERE run_id = %s ORDER BY sequence", (run,))
        assert [r["type"] for r in await cur.fetchall()][-2:] == ["action.granted", "action.dispatched"]
    finally:
        await purge_run(app_conn, run)


async def refused(call: Awaitable[object]) -> bool:
    """Whether the call is refused as a handle (OC008): the same answer for every cause, so only that is asserted."""
    try:
        await call
    except persistence.HandleRejected:
        return True
    return False


async def test_every_write_path_definer_compares_the_presented_azp(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """Ruling 12: a handle minted for a renamed worker client. Presented with the old name, each of the five definers
    refuses it (as resolve_invocation always did); presented with its own, each accepts it, which a literal
    `'ops-worker'` inside the function would have refused."""
    api, worker, mcp_exec = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.MCP_EXEC)
    _, run, proposal, _ = await approved_run(app_conn, api=api, worker=worker)
    try:
        cur = await app_conn.execute("SELECT fence FROM app.run_lease WHERE run_id = %s", (run,))
        renamed = "ops-worker-renamed"
        handle = await execute_handle(worker, run, azp=renamed, fence=int((await cur.fetchone() or {})["fence"]))
        resolve = persistence.resolve_invocation
        assert await refused(resolve(mcp_exec, handle=handle, azp=AZP, tool=Tool.CREATE_INCIDENT))
        assert await refused(persistence.grant_execution(mcp_exec, handle=handle, azp=AZP, proposal_id=proposal))
        assert await attempt_states(app_conn, run) == []  # the refused grant wrote nothing
        assert (await resolve(mcp_exec, handle=handle, azp=renamed, tool=Tool.CREATE_INCIDENT)).run_id == run
        grant = await persistence.grant_execution(mcp_exec, handle=handle, azp=renamed, proposal_id=proposal)
        action = grant.action_id
        for wrong in (
            persistence.lookup_action(mcp_exec, handle=handle, azp=AZP),
            persistence.mark_sent(mcp_exec, handle=handle, azp=AZP, action_id=action),
            persistence.request_abort(mcp_exec, handle=handle, azp=AZP, action_id=action),
            persistence.record_outcome(mcp_exec, handle=handle, azp=AZP, action_id=action, outcome=committed(grant)),
        ):
            assert await refused(wrong)
        assert (await persistence.lookup_action(mcp_exec, handle=handle, azp=renamed)).action_id == action
        assert await persistence.mark_sent(mcp_exec, handle=handle, azp=renamed, action_id=action) == "sent"
        with pytest.raises(persistence.Refused):  # resolved, then refused on its own ground: no abort is due
            await persistence.request_abort(mcp_exec, handle=handle, azp=renamed, action_id=action)
        standing = await persistence.record_outcome(
            mcp_exec, handle=handle, azp=renamed, action_id=action, outcome=committed(grant)
        )
        assert standing is ToolOutcome.SUCCEEDED
        assert await attempt_states(app_conn, run) == ["INTENT", "SENT", "RESOLVED"]
    finally:
        await purge_run(app_conn, run)
```

Run (dev stack up, no skeleton process running):

```bash
OPS_LIVE=1 PROFILE=test PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_migration_0010_live.py -q
```

Expected: `5 passed` (the round trip builds and drops a scratch database prefixed `r009_`). This count is arithmetic,
not measured: the plan's dry run cannot run live steps. A failure is a finding against the revision, not a reason to
weaken an assertion: stop and report.

- [x] **Step 7: Gates and commit**

Format, lint and count characters on every file of this task (the revision after the ISC004 pass).

Run: `PYTHONUTF8=1 uv run python scripts/check.py`
Expected: `CHECK: GREEN`; pytest `1103 passed, 169 skipped` (1089 + 13 in `tests/plan_k` + 1 parametrised revision; the
5 new live tests skip).

Run: `PYTHONUTF8=1 uv run python scripts/check.py --profile test`
Expected: `CHECK: GREEN`; pytest `1251 passed, 21 skipped` (arithmetic, not measured: the dev count plus the 148
live-gated tests, 169 − 21; every write-path live test runs with the rewritten signatures, and R105's worker drives
mcp-write against 0010). Then `git checkout -- reports/bootstrap reports/skeleton reports/auth reports/admission
reports/leases reports/events reports/outbox reports/mcp-read`.

Run: `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`
Expected: exit 0.

```bash
git add migrations/app/versions/0010_write_path.py core/src/ops_core/privileges.py core/src/ops_core/persistence.py
git add mcp-write/src/ops_mcp_write/execution.py mcp-write/src/ops_mcp_write/server.py tests/plan_k
git add tests/plan_e/test_transitions_table.py tests/e2e/test_migration_0007_live.py tests/e2e/test_migration_0010_live.py
git add tests/e2e/test_definers_write_path_live.py tests/e2e/test_event_journal_live.py tests/e2e/test_fenced_definers_live.py
git add tests/e2e/test_lease_stress_live.py tests/e2e/test_mcp_read_t15_live.py tests/e2e/test_mcp_write_live.py
git add tests/e2e/test_migrations_and_persistence.py tests/e2e/test_outbox_live.py tests/e2e/test_worker_live.py
git add tests/plan_h/test_write_path_fence.py
git commit -m "feat(migrations): revision 0010 - the token's azp, the dispatch deadline and request_abort (T47)"
```

---

### Task 3: The attempt-state allowlist and the two recovery tools

**Files:**
- Create: `tests/plan_k/test_attempt_allowlist.py`, `tests/plan_k/test_recovery_tools.py`,
  `tests/plan_k/test_write_tools_server.py`
- Modify: `core/src/ops_core/jobs.py` (import, `JobRule`'s docstring, `ATTEMPT_STATES` before `RECOVER_CADENCE`),
  `core/src/ops_core/persistence.py` (imports, `allowed_tool`, `resolve_invocation`),
  `mcp-write/src/ops_mcp_write/destination.py` (docstring, imports, `post_incident`, the new `get_action`,
  `post_abort`, `_send`, `classify`'s tombstone branch), `mcp-write/src/ops_mcp_write/execution.py` (docstring,
  imports, `next_step`, `create_incident` and the new `_ask`, `_granted`, `get_incident_receipt`, `abort_incident`,
  `_abort`, `_record`), `mcp-write/src/ops_mcp_write/server.py` (docstring, `refusal_error`, `outcome_envelope`, the new
  `abort_envelope`, `build_server`), `scripts/build_schemas.py` (`abort_outcome`, rule (e), the example tombstone), the
  regenerated `schemas/`, `tests/plan_d/test_persistence_pure.py`, `tests/plan_e/test_persistence_errors.py`,
  `tests/plan_j/test_allowlist.py`, `tests/plan_d/test_mcp_write.py`

**Requirements:** rulings 1, 4, 5, 9, 10, 18, 20, 24, 26; SA:338, SA:344-348, SA:354-356; BS:393; AM-13's recovery
table (SA:240-244).

**Interfaces:**
- Consumes: Task 2's `persistence.lookup_action`, `mark_sent`, `request_abort`, `record_outcome` (with `azp`);
  `ops_core.states.AttemptState`, `Reason`; `ops_core.outcomes.outcome_from_destination`; Plan J's
  `tests.plan_j.test_allowlist.HANDLE_JOBS`, `OneRow`, `resolved_row`.
- Produces: `jobs.ATTEMPT_STATES: dict[tuple[JobType, Tool], frozenset[AttemptState | None]]`;
  `persistence.allowed_tool(job_type, run_state, attempt_state: AttemptState | None, tool)`;
  `destination.get_action(http, *, url, token, action_id)`, `post_abort(http, *, url, token, action_id,
  payload_sha256, reason)`, `TIMEOUT`, `NEVER_SENT`; `execution.next_step(...) -> "stored" | "send" | "resend" |
  "aborting"`, `get_incident_receipt(deps, *, handle, azp, proposal_id)`, `abort_incident(deps, *, handle, azp,
  proposal_id)`; `server.outcome_envelope(outcome, tool_name="create_incident")`, `abort_envelope(outcome)`,
  `refusal_error("ABORT_NOT_DUE")`; in `tests.plan_k.test_recovery_tools`: `ACTION`, `PROPOSAL`, `SHA`,
  `committed(sha=SHA)`, `tombstone(state, reason)`.

- [x] **Step 1: Write the failing allowlist tests (and move the three existing ones to the new signature)**

Create `tests/plan_k/test_attempt_allowlist.py`:

```python
"""The attempt-state dimension of the AM-15 allowlist, in Python (SA:338; Plan K rulings 4, 5 and 26; erratum 19).

Catches: a receipt lookup or an abort honoured for an execute handle, or a lookup before anything could have been sent
(R030: "unavailable outside recover jobs"); a recover job redispatching an attempt already SENT (SA:345) or anything
after an abort request; an execute job's re-send of a SENT attempt refused (Plan E ruling 6, the re-queue after a lost
reply); an abort of a resolved attempt; a recovery tool for a run with no grant at all (it would have nothing to
recover, and must create nothing); a refusal whose message says which check failed or whose log carries the handle;
and a resolution that reads the attempt state but does not hand it to the check.
"""

import asyncio
import logging
from typing import Any

import pytest
from ops_core import persistence
from ops_core.jobs import ATTEMPT_STATES, JOB_RULES, JobType, Tool
from ops_core.states import AttemptState, RunState

from tests.plan_j.test_allowlist import HANDLE_JOBS, OneRow, resolved_row

A = AttemptState
ATTEMPTS: list[AttemptState | None] = [None, *AttemptState]
WRITE = {Tool.CREATE_INCIDENT, Tool.GET_INCIDENT_RECEIPT, Tool.ABORT_INCIDENT}


def test_the_attempt_rules_are_the_rulings() -> None:
    assert ATTEMPT_STATES == {
        (JobType.EXECUTE, Tool.CREATE_INCIDENT): {None, A.INTENT, A.SENT},  # the SENT re-send stays (ruling 5)
        (JobType.RECOVER, Tool.CREATE_INCIDENT): {A.INTENT},  # SA:345 over SA:334
        (JobType.RECOVER, Tool.GET_INCIDENT_RECEIPT): {A.SENT, A.ABORT_REQUESTED, A.RESOLVED},
        (JobType.RECOVER, Tool.ABORT_INCIDENT): {A.INTENT, A.SENT, A.ABORT_REQUESTED},
    }
    # Every write tool a job type may call has a rule; no read tool has one.
    governed = {(t, tool) for t in HANDLE_JOBS for tool in JOB_RULES[t].allowed_tools if tool in WRITE}
    assert governed == set(ATTEMPT_STATES)


@pytest.mark.parametrize("job_type", HANDLE_JOBS, ids=[t.value for t in HANDLE_JOBS])
def test_every_state_attempt_and_tool_follows_the_three_rules(job_type: JobType) -> None:
    rule = JOB_RULES[job_type]
    for state in RunState:
        for attempt in ATTEMPTS:
            for tool in Tool:
                admitted = ATTEMPT_STATES.get((job_type, tool))
                ok = tool in rule.allowed_tools and state in rule.run_states
                ok = ok and (admitted is None or attempt in admitted)
                if ok:
                    persistence.allowed_tool(job_type, state, attempt, tool)
                else:
                    with pytest.raises(persistence.HandleRejected) as refused:
                        persistence.allowed_tool(job_type, state, attempt, tool)
                    assert str(refused.value) == "invocation handle rejected"  # one message for every refusal


def test_receipt_lookup_is_for_recover_jobs_with_something_to_look_up() -> None:
    """R030 in the allowlist: an execute job never looks up or aborts; a recover job with no grant gets nothing."""
    for tool in (Tool.GET_INCIDENT_RECEIPT, Tool.ABORT_INCIDENT):
        for attempt in ATTEMPTS:
            with pytest.raises(persistence.HandleRejected):
                persistence.allowed_tool(JobType.EXECUTE, RunState.EXECUTING, attempt, tool)
    for tool in WRITE:
        with pytest.raises(persistence.HandleRejected):
            persistence.allowed_tool(JobType.RECOVER, RunState.OUTCOME_UNKNOWN, None, tool)  # no grant, no recovery
    persistence.allowed_tool(JobType.RECOVER, RunState.ESCALATED, A.RESOLVED, Tool.GET_INCIDENT_RECEIPT)


def recover_row(state: str, attempt: str | None) -> dict[str, Any]:
    return {**resolved_row(state), "job_type": "recover", "attempt_state": attempt}


def test_resolution_hands_the_attempt_state_to_the_check(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    handle = "a-raw-handle-that-must-never-be-logged"
    conn: Any = OneRow(recover_row("OUTCOME_UNKNOWN", "SENT"))
    got = asyncio.run(
        persistence.resolve_invocation(conn, handle=handle, azp="ops-worker", tool=Tool.GET_INCIDENT_RECEIPT)
    )
    assert got.attempt_state == "SENT" and got.job_type is JobType.RECOVER
    with pytest.raises(persistence.HandleRejected):  # the same run and attempt: a recover job does not re-send SENT
        asyncio.run(persistence.resolve_invocation(conn, handle=handle, azp="ops-worker", tool=Tool.CREATE_INCIDENT))
    leaked = handle in caplog.text  # a verdict, not an operand
    assert "tool create_incident is not allowed for job type recover with attempt SENT" in caplog.text and not leaked
    conn.row = recover_row("OUTCOME_UNKNOWN", None)
    with pytest.raises(persistence.HandleRejected):
        asyncio.run(
            persistence.resolve_invocation(conn, handle=handle, azp="ops-worker", tool=Tool.GET_INCIDENT_RECEIPT)
        )
    assert "with attempt none" in caplog.text
```

Edit 1 (`tests/plan_d/test_persistence_pure.py`, in `test_rejections`), replace:

```python
        allowed_tool(job_type, state, tool)
```

with:

```python
        allowed_tool(job_type, state, None, tool)  # refused on the tool, before any attempt rule
```

Edit 2 (`tests/plan_e/test_persistence_errors.py`, the module header), replace:

```python
from ops_core.states import IllegalTransition, RunState
```

with:

```python
from ops_core.states import AttemptState, IllegalTransition, RunState
```

Edit 3 (`tests/plan_e/test_persistence_errors.py`, in `test_refused_carries_the_detail_code_and_other_errors_pass_through`), replace:

```python
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

with:

```python
    ("job_type", "state", "attempt", "tool", "ok"),
    [
        (JobType.INVESTIGATE, RunState.RETRIEVING, None, Tool.SEARCH_PROCEDURES, True),
        (JobType.INVESTIGATE, RunState.RETRIEVING, None, Tool.CREATE_INCIDENT, False),
        (JobType.EXECUTE, RunState.APPROVED, None, Tool.CREATE_INCIDENT, True),
        (JobType.EXECUTE, RunState.APPROVED, None, Tool.SEARCH_PROCEDURES, False),
        (JobType.RECOVER, RunState.OUTCOME_UNKNOWN, AttemptState.SENT, Tool.ABORT_INCIDENT, True),
    ],
)
def test_allowed_tool(job_type: JobType, state: RunState, attempt: AttemptState | None, tool: Tool, ok: bool) -> None:
    if ok:
        p.allowed_tool(job_type, state, attempt, tool)
    else:
        with pytest.raises(p.HandleRejected):
            p.allowed_tool(job_type, state, attempt, tool)
```

Edit 4 (`tests/plan_j/test_allowlist.py`, the module header), replace:

```python
"""The AM-15 allowlist in Python: the job type's tools and the job type's run states (Plan J ruling 6, erratum 19).
```

with:

```python
"""The AM-15 allowlist in Python: the job type's tools and the job type's run states (Plan J ruling 6, erratum 19). The
third dimension, the attempt state (T47), is tabled in tests/plan_k/test_attempt_allowlist.py; here every call passes
an attempt state the attempt rule admits, so only the first two decide.
```

Edit 5 (`tests/plan_j/test_allowlist.py`, the module header), replace:

```python
from ops_core.jobs import JOB_RULES, JobType, Server, Tool
from ops_core.states import RunState

HANDLE_JOBS = [t for t, rule in JOB_RULES.items() if rule.server is not None]
```

with:

```python
from ops_core.jobs import ATTEMPT_STATES, JOB_RULES, JobType, Server, Tool
from ops_core.states import AttemptState, RunState

HANDLE_JOBS = [t for t, rule in JOB_RULES.items() if rule.server is not None]


def admitted(job_type: JobType, tool: Tool) -> AttemptState | None:
    """An attempt state the attempt rule admits for the pair (any, for a pair it does not govern)."""
    allowed = ATTEMPT_STATES.get((job_type, tool))
    return None if allowed is None or None in allowed else min(a for a in allowed if a is not None)
```

Edit 6 (`tests/plan_j/test_allowlist.py`, in `test_every_state_and_tool_pair_follows_the_job_rule`), replace:

```python
            if tool in rule.allowed_tools and state in rule.run_states:
                persistence.allowed_tool(job_type, state, tool)
            else:
                with pytest.raises(persistence.HandleRejected) as refused:
                    persistence.allowed_tool(job_type, state, tool)
```

with:

```python
            attempt = admitted(job_type, tool)
            if tool in rule.allowed_tools and state in rule.run_states:
                persistence.allowed_tool(job_type, state, attempt, tool)
            else:
                with pytest.raises(persistence.HandleRejected) as refused:
                    persistence.allowed_tool(job_type, state, attempt, tool)
```

Run: `uv run python -m pytest tests/plan_k/test_attempt_allowlist.py tests/plan_d/test_persistence_pure.py tests/plan_e/test_persistence_errors.py tests/plan_j/test_allowlist.py -q`
Expected: `2 errors in` (collection stops: `ImportError: cannot import name 'ATTEMPT_STATES' from 'ops_core.jobs'` in
the new module and in Plan J's).

- [x] **Step 2: The attempt-state dimension**

Edit 1 (`core/src/ops_core/jobs.py`, the module header), replace:

```python
from ops_core.states import RunState
```

with:

```python
from ops_core.states import AttemptState, RunState
```

Edit 2 (`core/src/ops_core/jobs.py`, in `JobRule`), replace:

```python
    `run_states` are the first two, and `persistence.allowed_tool` checks both at every handle resolution (T15).
    TODO(T47): the attempt-state dimension (`create_incident` only while the attempt is absent or INTENT, not
    cancelled, before the deadline) is mcp-write's, where `execution.next_step` branches on it today.
```

with:

```python
    `run_states` are the first two (T15); the third is `ATTEMPT_STATES` below (T47), and `persistence.allowed_tool`
    checks all three at the start of every MCP call. "Not cancelled, before the deadline" is not part of it: it needs
    the cancel flag and the grant's time, so `mark_sent` re-checks both under the runs lock (Plan K ruling 4).
```

Edit 3 (`core/src/ops_core/jobs.py`, in `JOB_RULES`), replace:

```python
    },
}
```

with:

```python
    },
}

_A = AttemptState
# The attempt-state dimension (AM-15, SA:338; Plan K rulings 4 and 5): the latest attempt state a write tool may be
# called in, per job type; None is "no attempt yet" (no grant). A (job type, tool) pair not listed has no attempt rule
# (the read tools). An execute job re-sends a SENT attempt under the same action id (the re-queue after a lost reply,
# Plan E ruling 6); a recover job redispatches INTENT only (SA:345 over SA:334), looks up any attempt that may have
# reached the destination (a resolved one answers its stored outcome), and aborts one that is not resolved.
ATTEMPT_STATES: Final[dict[tuple[JobType, Tool], frozenset[AttemptState | None]]] = {
    (JobType.EXECUTE, Tool.CREATE_INCIDENT): frozenset({None, _A.INTENT, _A.SENT}),
    (JobType.RECOVER, Tool.CREATE_INCIDENT): frozenset({_A.INTENT}),
    (JobType.RECOVER, Tool.GET_INCIDENT_RECEIPT): frozenset({_A.SENT, _A.ABORT_REQUESTED, _A.RESOLVED}),
    (JobType.RECOVER, Tool.ABORT_INCIDENT): frozenset({_A.INTENT, _A.SENT, _A.ABORT_REQUESTED}),
}
```

Edit 4 (`core/src/ops_core/persistence.py`, the module header), replace:

```python
from ops_core.jobs import JOB_RULES, JobType, Server, Tool, dedup_key
```

with:

```python
from ops_core.jobs import ATTEMPT_STATES, JOB_RULES, JobType, Server, Tool, dedup_key
```

Edit 5 (`core/src/ops_core/persistence.py`, the module header), replace:

```python
from ops_core.states import IllegalTransition, Intent, Reason, RunState
```

with:

```python
from ops_core.states import AttemptState, IllegalTransition, Intent, Reason, RunState
```

Edit 6 (`core/src/ops_core/persistence.py`, in `allowed_tool`), replace:

```python
def allowed_tool(job_type: JobType, run_state: RunState, tool: Tool) -> None:
    """The AM-15 allowlist stays in Python (Plan E ruling 21, erratum 19): the tool must be one of the job type's and
    the run must be in one of the job type's states (Plan J ruling 6); the function has already bound server, azp,
    expiry, fence and the handle's job. A run that moved on (a read handle once the run awaits approval, an execute
    handle once the run succeeded) is refused like any other handle."""
```

with:

```python
def allowed_tool(job_type: JobType, run_state: RunState, attempt_state: AttemptState | None, tool: Tool) -> None:
    """The AM-15 allowlist stays in Python (Plan E ruling 21, erratum 19): the tool must be one of the job type's, the
    run must be in one of the job type's states (Plan J ruling 6), and a write tool's latest attempt state must be one
    `jobs.ATTEMPT_STATES` admits for the job type (Plan K ruling 4); the function has already bound server, azp,
    expiry, fence and the handle's job. A run that moved on (a read handle once the run awaits approval, an execute
    handle once the run succeeded, a recover handle asking to redispatch a sent attempt) is refused like any other
    handle."""
```

Edit 7 (`core/src/ops_core/persistence.py`, in `allowed_tool`), replace:

```python
        log.info("job type %s does not run in state %s", job_type.value, run_state.value)  # never the handle
        raise HandleRejected("invocation handle rejected")
```

with:

```python
        log.info("job type %s does not run in state %s", job_type.value, run_state.value)  # never the handle
        raise HandleRejected("invocation handle rejected")
    attempts = ATTEMPT_STATES.get((job_type, tool))
    if attempts is not None and attempt_state not in attempts:
        shown = "none" if attempt_state is None else attempt_state.value
        log.info("tool %s is not allowed for job type %s with attempt %s", tool.value, job_type.value, shown)
        raise HandleRejected("invocation handle rejected")
```

Edit 8 (`core/src/ops_core/persistence.py`, in `resolve_invocation`), replace:

```python
    allowed_tool(job_type, run_state, tool)
```

with:

```python
    attempt_state = None if row["attempt_state"] is None else AttemptState(str(row["attempt_state"]))
    allowed_tool(job_type, run_state, attempt_state, tool)
```

Edit 9 (`core/src/ops_core/persistence.py`, in `resolve_invocation`), replace:

```python
        None if row["attempt_state"] is None else str(row["attempt_state"]),
    )
```

with:

```python
        None if attempt_state is None else attempt_state.value,
    )
```

Run: the Step 1 command again.
Expected: `31 passed`.

- [x] **Step 3: Write the failing tool tests**

Create `tests/plan_k/test_recovery_tools.py`:

```python
"""The recovery calls and the abort branch of `create_incident`, without a database or a destination (AM-13 recovery
table; SA:348, SA:465; Plan K rulings 3, 10, 18, 19 and 24).

The definers are scripted stand-ins that record their calls; the destination calls are scripted too, except where the
real request is built against `httpx2.MockTransport`. Catches: a cancelled or expired attempt answered UNKNOWN (the old
conservative branch) or POSTed instead of aborted; an abort POSTed before its request was recorded, or with a reason
the function did not choose; anything sent once an abort request exists; an answer of `mark_sent` the code does not
know read as "go ahead"; a re-send of a SENT attempt that skips mark_sent's checks (round 1, I1), or a recover job's
re-send; a lookup or an abort that records UNKNOWN, a 404 or a 429 recorded as anything but UNKNOWN; a
receipt for another hash accepted; a resolved attempt that calls the destination again; a recovery call for another
proposal served; the tombstone's reason mapped to the wrong FAILED reason; and requests that do not carry the workload
token, the right path, method or body.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import httpx2
import pytest
from ops_core import persistence
from ops_core.outcomes import ActionOutcome, ToolOutcome
from ops_core.states import Reason
from ops_mcp_write import destination, execution

ACTION = UUID(int=21)
PROPOSAL = UUID(int=22)
SHA = "c" * 64
RECEIPT = {"receipt_id": str(UUID(int=23)), "incident_id": "INC-000021", "committed_at": "2026-10-16T12:00:00Z"}
DECIDED = "2026-10-16T12:00:00Z"


def grant(attempt: str, detail: dict[str, Any] | None = None, proposal: UUID = PROPOSAL) -> persistence.Grant:
    return persistence.Grant(
        action_id=ACTION,
        run_id=UUID(int=24),
        proposal_id=proposal,
        tenant_id=UUID(int=25),
        conversation_id=UUID(int=26),
        payload_sha256=SHA,
        payload_canonical=b'{"x":1}',
        attempt_state=attempt,
        detail=detail,
    )


def committed(sha: str = SHA) -> destination.Reply:
    return destination.Reply(
        200, {"state": "COMMITTED", "action_id": str(ACTION), "payload_sha256": sha, "receipt": RECEIPT}
    )


def tombstone(state: str, reason: str) -> destination.Reply:
    stone = {"action_id": str(ACTION), "state": state, "payload_sha256": SHA, "reason": reason, "decided_at": DECIDED}
    return destination.Reply(200, {"state": state, "action_id": str(ACTION), "payload_sha256": SHA, "tombstone": stone})


class Script:
    """Scripted definers and destination calls; `calls` is the order they ran in."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, attempt: str, **answers: Any) -> None:
        self.calls: list[str] = []
        self.answers = answers
        self.recorded: list[ActionOutcome] = []
        self.grant = grant(attempt, answers.get("detail"), answers.get("proposal", PROPOSAL))
        self.abort_reasons: list[str] = []
        for name in ("grant_execution", "lookup_action", "mark_sent", "request_abort", "record_outcome"):
            monkeypatch.setattr(persistence, name, self.definer(name))
        for name in ("post_incident", "get_action", "post_abort"):
            monkeypatch.setattr(destination, name, self.request(name))

    def definer(self, name: str) -> Any:
        async def call(_conn: Any, **kwargs: Any) -> Any:
            self.calls.append(name)
            assert kwargs["azp"] == "ops-worker"  # every definer gets the token's azp (revision 0010)
            if name in ("grant_execution", "lookup_action"):
                return self.grant
            if name == "record_outcome":
                self.recorded.append(kwargs["outcome"])
                return kwargs["outcome"].status
            return self.answers[name]

        return call

    def request(self, name: str) -> Any:
        async def call(_http: Any, **kwargs: Any) -> Any:
            self.calls.append(name)
            if name == "post_abort":
                self.abort_reasons.append(kwargs["reason"])
            return self.answers.get(name)

        return call


class FakeSession:
    @asynccontextmanager
    async def unit(self, tenant_id: Any = None) -> AsyncIterator[object]:
        yield object()


class FakeToken:
    async def token(self) -> str:
        return "workload-token"


def deps() -> execution.Deps:
    session: Any = FakeSession()
    token: Any = FakeToken()
    http: Any = None
    return execution.Deps(session=session, http=http, destination_url="http://127.0.0.1:9", destination_token=token)


def create(script: Script) -> ActionOutcome:
    return asyncio.run(execution.create_incident(deps(), handle="h", azp="ops-worker", proposal_id=PROPOSAL))


def receipt(script: Script, proposal: UUID = PROPOSAL) -> ActionOutcome:
    return asyncio.run(execution.get_incident_receipt(deps(), handle="h", azp="ops-worker", proposal_id=proposal))


def abort(script: Script, proposal: UUID = PROPOSAL) -> ActionOutcome:
    return asyncio.run(execution.abort_incident(deps(), handle="h", azp="ops-worker", proposal_id=proposal))


@pytest.mark.parametrize(
    ("answer", "token", "reason"),
    [("cancelled", "cancelled_before_send", Reason.CANCELLED_BEFORE_SEND), ("expired", "expired", Reason.EXPIRED)],
)
def test_a_cancelled_or_expired_attempt_is_aborted_and_ends_without_commit(
    monkeypatch: pytest.MonkeyPatch, answer: str, token: str, reason: Reason
) -> None:
    script = Script(
        monkeypatch, attempt="INTENT", mark_sent=answer, request_abort=token, post_abort=tombstone("ABORTED", token)
    )
    outcome = create(script)
    assert script.calls == ["grant_execution", "mark_sent", "request_abort", "post_abort", "record_outcome"]
    assert script.abort_reasons == [token]  # the reason request_abort chose, never one this code made up
    assert outcome.status is ToolOutcome.FAILED_NO_COMMIT and outcome.reason is reason
    assert outcome.tombstone is not None and outcome.tombstone.reason == token
    assert script.recorded == [outcome]


def test_an_abort_without_an_answer_is_unknown_and_recorded_by_nobody(monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script(monkeypatch, attempt="INTENT", mark_sent="cancelled", request_abort="cancelled_before_send")
    outcome = create(script)  # post_abort answers None: the transport gave nothing usable
    assert outcome.status is ToolOutcome.UNKNOWN and script.recorded == []
    assert script.calls == ["grant_execution", "mark_sent", "request_abort", "post_abort"]


def test_nothing_is_sent_once_an_abort_is_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    already = Script(monkeypatch, attempt="ABORT_REQUESTED")
    assert create(already).status is ToolOutcome.UNKNOWN and already.calls == ["grant_execution"]
    meanwhile = Script(monkeypatch, attempt="INTENT", mark_sent="abort_requested")
    assert create(meanwhile).status is ToolOutcome.UNKNOWN
    assert meanwhile.calls == ["grant_execution", "mark_sent"]


@pytest.mark.parametrize("answer", ["cancelled", "expired"])
def test_a_re_send_after_a_cancel_or_past_the_deadline_is_aborted_not_sent(
    monkeypatch: pytest.MonkeyPatch, answer: str
) -> None:
    """Round 1, I1: a SENT attempt is re-sent only through mark_sent, and its `cancelled`/`expired` answer leads to the
    immediate abort (`deadline`, SA:248), never to a second POST."""
    script = Script(
        monkeypatch,
        attempt="SENT",
        mark_sent=answer,
        request_abort="deadline",
        post_abort=tombstone("ABORTED", "deadline"),
    )
    outcome = create(script)
    assert script.calls == ["grant_execution", "mark_sent", "request_abort", "post_abort", "record_outcome"]
    assert outcome.status is ToolOutcome.FAILED_NO_COMMIT and outcome.reason is Reason.ABORTED_NO_COMMIT


def test_a_due_re_send_goes_through_mark_sent_and_posts_the_same_action(monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script(monkeypatch, attempt="SENT", mark_sent="already_sent", post_incident=committed())
    assert create(script).status is ToolOutcome.SUCCEEDED
    assert script.calls == ["grant_execution", "mark_sent", "post_incident", "record_outcome"]


def test_a_recover_job_never_re_sends(monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script(monkeypatch, attempt="SENT", mark_sent="not_redispatchable")
    with pytest.raises(persistence.Refused) as refused:  # server.py answers the plain NOT_REDISPATCHABLE error
        create(script)
    assert refused.value.code == "NOT_REDISPATCHABLE" and script.calls == ["grant_execution", "mark_sent"]


def test_an_answer_mark_sent_never_gives_is_never_read_as_go_ahead(monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script(monkeypatch, attempt="INTENT", mark_sent="maybe")
    with pytest.raises(persistence.PersistenceError, match="mark_sent answered maybe"):
        create(script)
    assert script.calls == ["grant_execution", "mark_sent"]


def test_the_receipt_lookup_records_what_the_destination_holds(monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script(monkeypatch, attempt="SENT", get_action=committed())
    outcome = receipt(script)
    assert outcome.status is ToolOutcome.SUCCEEDED and outcome.receipt is not None
    assert script.calls == ["lookup_action", "get_action", "record_outcome"]  # one GET; no POST of any kind


@pytest.mark.parametrize(
    "reply",
    [
        None,  # a lost reply or a timeout
        destination.Reply(404, {"code": "NOT_FOUND"}),  # no key yet (delay_receipt): never a no-commit (SA:269)
        destination.Reply(429, {"code": "RATE_LIMITED"}),
        destination.Reply(503, {"code": "UNAVAILABLE"}),
    ],
    ids=["none", "404", "429", "503"],
)
def test_a_lookup_without_a_key_is_unknown_and_recorded_by_nobody(
    monkeypatch: pytest.MonkeyPatch, reply: destination.Reply | None
) -> None:
    script = Script(monkeypatch, attempt="SENT", get_action=reply)
    assert receipt(script).status is ToolOutcome.UNKNOWN
    assert script.calls == ["lookup_action", "get_action"] and script.recorded == []


def test_a_receipt_for_another_hash_is_recorded_as_a_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script(monkeypatch, attempt="SENT", get_action=committed(sha="d" * 64))
    outcome = receipt(script)
    assert outcome.status is ToolOutcome.CONFLICT and script.recorded == [outcome]  # never success (SA:358)


def test_a_resolved_attempt_answers_its_stored_outcome_without_a_call(monkeypatch: pytest.MonkeyPatch) -> None:
    stored = {"status": "SUCCEEDED", "action_id": str(ACTION), "payload_sha256": SHA, "receipt": RECEIPT}
    stored |= {"tombstone": None, "reason": None}
    for call in (receipt, abort):
        script = Script(monkeypatch, attempt="RESOLVED", detail=stored)
        assert call(script).status is ToolOutcome.SUCCEEDED and script.calls == ["lookup_action"]


@pytest.mark.parametrize(
    ("reply", "status", "reason"),
    [
        (committed(), ToolOutcome.SUCCEEDED, None),  # the abort met the receipt already there (SA:242)
        (tombstone("ABORTED", "deadline"), ToolOutcome.FAILED_NO_COMMIT, Reason.ABORTED_NO_COMMIT),
        (tombstone("REJECTED", "policy"), ToolOutcome.FAILED_NO_COMMIT, Reason.REJECTED),
    ],
    ids=["receipt", "fresh-tombstone", "rejected"],
)
def test_an_abort_after_send_records_what_the_destination_answered(
    monkeypatch: pytest.MonkeyPatch, reply: destination.Reply, status: ToolOutcome, reason: Reason | None
) -> None:
    script = Script(monkeypatch, attempt="SENT", request_abort="deadline", post_abort=reply)
    outcome = abort(script)
    assert outcome.status is status and outcome.reason is reason and script.recorded == [outcome]
    assert script.calls == ["lookup_action", "request_abort", "post_abort", "record_outcome"]
    assert script.abort_reasons == ["deadline"]


def test_an_abort_that_is_not_due_sends_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script(monkeypatch, attempt="SENT")

    async def not_due(_conn: Any, **_: Any) -> str:
        script.calls.append("request_abort")
        raise persistence.Refused("ABORT_NOT_DUE")

    monkeypatch.setattr(persistence, "request_abort", not_due)
    with pytest.raises(persistence.Refused):  # server.py answers the plain, retryable ABORT_NOT_DUE
        abort(script)
    assert script.calls == ["lookup_action", "request_abort"]


def test_a_recovery_call_for_another_proposal_is_refused_before_any_call(monkeypatch: pytest.MonkeyPatch) -> None:
    for call in (receipt, abort):
        script = Script(monkeypatch, attempt="SENT", proposal=UUID(int=99))
        with pytest.raises(persistence.Refused) as refused:
            call(script)
        assert refused.value.code == "OTHER_PROPOSAL" and script.calls == ["lookup_action"]  # SA:538


@pytest.mark.parametrize(
    ("state", "token", "reason"),
    [
        ("ABORTED", "cancelled_before_send", Reason.CANCELLED_BEFORE_SEND),
        ("ABORTED", "expired", Reason.EXPIRED),
        ("ABORTED", "deadline", Reason.ABORTED_NO_COMMIT),
        ("ABORTED", "aborted", Reason.ABORTED_NO_COMMIT),  # a reason this code did not choose proves only no commit
        ("REJECTED", "policy", Reason.REJECTED),
    ],
)
def test_the_tombstones_reason_says_whether_the_attempt_was_ever_sent(state: str, token: str, reason: Reason) -> None:
    outcome = destination.classify(tombstone(state, token), action_id=ACTION, payload_sha256=SHA)
    assert outcome.status is ToolOutcome.FAILED_NO_COMMIT and outcome.reason is reason


def test_the_requests_carry_the_workload_token_path_and_body() -> None:
    seen: list[httpx2.Request] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(429, json={"code": "RATE_LIMITED"})

    async def run() -> list[destination.Reply | None]:
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(answer)) as http:
            url, token = "http://sim", "workload-token"
            return [
                await destination.get_action(http, url=url, token=token, action_id=ACTION),
                await destination.post_abort(
                    http, url=url, token=token, action_id=ACTION, payload_sha256=SHA, reason="expired"
                ),
            ]

    replies = asyncio.run(run())
    assert [(r.method, r.url.path) for r in seen] == [
        ("GET", f"/internal/actions/{ACTION}"),
        ("POST", f"/internal/actions/{ACTION}/abort"),
    ]
    assert all(r.headers["authorization"] == "Bearer workload-token" for r in seen)
    assert seen[0].content == b"" and json.loads(seen[1].content) == {"payload_sha256": SHA, "reason": "expired"}
    assert seen[1].extensions["timeout"]["read"] == 10.0  # one request per call; the backoff is the worker's (T22)
    assert all(r is not None and r.status_code == 429 for r in replies)
    statuses = [destination.classify(r, action_id=ACTION, payload_sha256=SHA).status for r in replies]
    assert statuses == [ToolOutcome.UNKNOWN, ToolOutcome.UNKNOWN]  # a rate limit at either call proves nothing
```

Create `tests/plan_k/test_write_tools_server.py`:

```python
"""mcp-write's three tools in-process, through the guard and the SDK's bearer auth, with the definers and the work
replaced (Plan K rulings 1, 9, 10, 20 and 26).

Catches: a tool missing from the list or listed with a schema other than its `schemas/tools/` contract (an extra
argument accepted, SA:350); a tool that does its work before resolving the handle, or resolves it for another tool's
allowlist; a call without a handle that reaches anything; a refused handle, a premature abort or a stale run answered
with an action id; the worker's `azp` not handed to the work; envelopes for the recovery tools that do not validate
against `schemas/tool-result.schema.json` for every outcome (the abort's UNKNOWN and CONFLICT included), or `ok`
around anything but SUCCEEDED (R083).
"""

import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import MappingProxyType
from typing import Any
from uuid import UUID

import httpx2
import pytest
from jsonschema import Draft202012Validator, FormatChecker
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from ops_core import persistence
from ops_core.jobs import Tool
from ops_core.outcomes import ActionOutcome, ToolOutcome
from ops_core.tokens import Principal, TokenRejected
from ops_mcp_write import destination, execution, server

from tests.plan_k.test_recovery_tools import ACTION, PROPOSAL, SHA, committed, tombstone

ISSUER = "http://localhost:18080/realms/ops-dev"
RESOURCE = "http://mcp-write:8082/mcp"
BASE = "http://127.0.0.1:8082"
WRITE_TOOLS = ("create_incident", "get_incident_receipt", "abort_incident")
TOOL_RESULT = Draft202012Validator(
    json.loads(Path("schemas/tool-result.schema.json").read_text(encoding="utf-8")), format_checker=FormatChecker()
)


class WriteVerifier:
    """'good' is the worker's token for this server; anything else is refused, as a real verifier would."""

    @property
    def ready(self) -> bool:
        return True

    async def load_keys(self) -> None:
        return None

    async def verify_async(self, token: str) -> Principal:
        if token != "good":
            raise TokenRejected("unit test")
        claims = MappingProxyType({"iss": ISSUER, "typ": "Bearer"})
        return Principal("subject", "ops-worker", (RESOURCE, "account"), int(time.time()) + 300, claims)


class IdleConn:
    async def close(self) -> None:
        return None


class FakeSession:
    @asynccontextmanager
    async def unit(self, tenant_id: Any = None) -> AsyncIterator[object]:
        yield object()


def write_app() -> Any:
    session: Any = FakeSession()
    token: Any = None
    http: Any = httpx2.AsyncClient()
    deps = execution.Deps(session=session, http=http, destination_url="http://127.0.0.1:9", destination_token=token)
    state = server.State(deps=deps, verifier=WriteVerifier())
    idle: Any = IdleConn()
    deps.session.conn = idle  # the lifespan closes it at shutdown
    return server.build_app(server.build_server(state, issuer=ISSUER, resource_url=RESOURCE), state)


@asynccontextmanager
async def client(app: Any, handle: str | None = "a-handle") -> AsyncIterator[Client]:
    """The SDK's own client pinned to 2026-07-28 over an in-process transport, with the app's lifespan running."""
    headers = {"Authorization": "Bearer good"} | ({} if handle is None else {"X-Ops-Invocation": handle})
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with (
            httpx2.AsyncClient(transport=transport, base_url=BASE, headers=headers) as http,
            Client(streamable_http_client(f"{BASE}/mcp", http_client=http), mode="2026-07-28") as mcp,
        ):
            yield mcp


def outcome(status: ToolOutcome) -> ActionOutcome:
    reply = {
        ToolOutcome.SUCCEEDED: committed(),
        ToolOutcome.FAILED_NO_COMMIT: tombstone("ABORTED", "deadline"),
        ToolOutcome.CONFLICT: committed(sha="d" * 64),
        ToolOutcome.UNKNOWN: None,
    }[status]
    return destination.classify(reply, action_id=ACTION, payload_sha256=SHA)


@pytest.mark.asyncio
async def test_the_three_tools_are_listed_with_their_contract_schemas() -> None:
    async with client(write_app()) as mcp:
        tools = {t.name: t.input_schema for t in (await mcp.list_tools()).tools}
        extras = [await mcp.call_tool(name, {"proposal_id": str(PROPOSAL), "reason": "deadline"}) for name in tools]
    assert sorted(tools) == sorted(WRITE_TOOLS)
    for name, schema in tools.items():
        contract = json.loads(Path(f"schemas/tools/{name}.input.schema.json").read_text(encoding="utf-8"))
        assert schema["additionalProperties"] is False and schema["required"] == contract["required"] == ["proposal_id"]
        assert schema["properties"]["proposal_id"]["format"] == "uuid", name
    assert all(result.is_error for result in extras)  # a reason, a tenant or an approval is never an argument (SA:350)


@pytest.mark.asyncio
async def test_without_a_handle_nothing_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    resolved: list[Tool] = []

    async def resolve(_conn: Any, **kwargs: Any) -> None:
        resolved.append(kwargs["tool"])

    monkeypatch.setattr(persistence, "resolve_invocation", resolve)
    async with client(write_app(), handle=None) as mcp:
        results = [await mcp.call_tool(name, {"proposal_id": str(PROPOSAL)}) for name in WRITE_TOOLS]
    for name, result in zip(WRITE_TOOLS, results, strict=True):
        doc = result.structured_content
        assert not result.is_error and isinstance(doc, dict) and doc["tool_name"] == name
        assert doc["error"] == {"code": "INVALID_HANDLE", "message": "missing invocation handle", "retryable": False}
    assert resolved == []


@pytest.mark.asyncio
async def test_each_tool_resolves_its_own_allowlist_first_and_hands_the_token_azp_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []

    async def resolve(_conn: Any, **kwargs: Any) -> None:
        assert kwargs["azp"] == "ops-worker" and kwargs["handle"] == "a-handle"
        order.append(f"resolve:{kwargs['tool'].value}")

    def work(name: str, status: ToolOutcome) -> Any:
        async def run(_deps: Any, **kwargs: Any) -> ActionOutcome:
            assert kwargs["azp"] == "ops-worker" and kwargs["proposal_id"] == PROPOSAL
            order.append(f"work:{name}")
            return outcome(status)

        return run

    monkeypatch.setattr(persistence, "resolve_invocation", resolve)
    monkeypatch.setattr(execution, "create_incident", work("create_incident", ToolOutcome.SUCCEEDED))
    monkeypatch.setattr(execution, "get_incident_receipt", work("get_incident_receipt", ToolOutcome.UNKNOWN))
    monkeypatch.setattr(execution, "abort_incident", work("abort_incident", ToolOutcome.FAILED_NO_COMMIT))
    async with client(write_app()) as mcp:
        docs = [(await mcp.call_tool(name, {"proposal_id": str(PROPOSAL)})).structured_content for name in WRITE_TOOLS]
    assert order == [f"{step}:{name}" for name in WRITE_TOOLS for step in ("resolve", "work")]
    assert [d["status"] for d in docs if isinstance(d, dict)] == ["ok", "outcome", "outcome"]
    for doc in docs:
        TOOL_RESULT.validate(doc)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raised", "code", "retryable"),
    [
        (persistence.HandleRejected("invocation handle rejected"), "INVALID_HANDLE", False),
        (persistence.Refused("ABORT_NOT_DUE"), "ABORT_NOT_DUE", True),
        (persistence.Refused("OTHER_PROPOSAL"), "GRANT_REFUSED", False),
        (persistence.VersionConflict("run is OUTCOME_UNKNOWN"), "STALE_RUN", False),
        (persistence.Refused("NOT_REDISPATCHABLE"), "NOT_REDISPATCHABLE", False),
    ],
    ids=["handle", "not-due", "other-proposal", "stale-run", "not-redispatchable"],
)
async def test_a_refusal_before_the_destination_is_a_plain_error(
    monkeypatch: pytest.MonkeyPatch, raised: Exception, code: str, retryable: bool
) -> None:
    async def resolve(_conn: Any, **_: Any) -> None:
        return None

    async def refuse(_deps: Any, **_: Any) -> ActionOutcome:
        raise raised

    monkeypatch.setattr(persistence, "resolve_invocation", resolve)
    for name in WRITE_TOOLS:
        monkeypatch.setattr(execution, name, refuse)
    async with client(write_app()) as mcp:
        docs = [(await mcp.call_tool(name, {"proposal_id": str(PROPOSAL)})).structured_content for name in WRITE_TOOLS]
    for doc in docs:
        assert isinstance(doc, dict) and doc["status"] == "error" and doc["data"] is None
        assert doc["error"]["code"] == code and doc["error"]["retryable"] is retryable
        assert "action_id" not in json.dumps(doc)  # a refusal never names the action (SA:355)
        TOOL_RESULT.validate(doc)


@pytest.mark.parametrize("status", list(ToolOutcome))
def test_the_recovery_envelopes_follow_the_tool_result_contract(status: ToolOutcome) -> None:
    receipt = server.outcome_envelope(outcome(status), Tool.GET_INCIDENT_RECEIPT.value)
    aborted = server.abort_envelope(outcome(status))
    for doc in (receipt, aborted):
        TOOL_RESULT.validate(doc)
        assert doc["status"] == ("ok" if status is ToolOutcome.SUCCEEDED else "outcome") and doc["error"] is None
    assert receipt["tool_name"] == "get_incident_receipt" and receipt["data"]["status"] == status.value
    assert aborted["tool_name"] == "abort_incident" and aborted["data"]["outcome"] == status.value
    assert set(aborted["data"]) == {"action_id", "outcome", "receipt", "tombstone"}  # SA:356, nothing else
    assert aborted["data"]["action_id"] == str(ACTION)
    if status is ToolOutcome.FAILED_NO_COMMIT:
        assert aborted["data"]["tombstone"]["reason"] == "deadline"  # the destination's own token (ruling 10)


def test_the_abort_example_carries_the_destinations_token() -> None:
    example = json.loads(Path("schemas/examples/tool-abort_incident-valid.json").read_text(encoding="utf-8"))
    TOOL_RESULT.validate(example)
    assert example["data"]["tombstone"]["reason"] == "cancelled_before_send"


def test_an_ok_abort_envelope_around_anything_but_success_is_refused_by_the_contract() -> None:
    doc = server.abort_envelope(outcome(ToolOutcome.UNKNOWN))
    doc["status"] = "ok"
    assert not TOOL_RESULT.is_valid(doc)  # R083's probe, for the abort's added outcomes
    stray = server.abort_envelope(outcome(ToolOutcome.CONFLICT))
    stray["data"]["receipt"] = committed().document["receipt"]
    assert not TOOL_RESULT.is_valid(stray)  # UNKNOWN and CONFLICT carry neither a receipt nor a tombstone


def test_an_abort_not_due_is_retryable_and_names_no_action() -> None:
    error = server.refusal_error("ABORT_NOT_DUE")
    assert error["code"] == "ABORT_NOT_DUE" and error["retryable"] is True
    assert str(UUID(int=21)) not in json.dumps(error)
```

Edit 1 (`tests/plan_d/test_mcp_write.py`, in `test_next_step_replays_without_a_second_send_once_resolved`), replace:

```python
    with pytest.raises(ValueError):
        execution.next_step("ABORT_REQUESTED")  # T22 territory; the skeleton refuses to guess
```

with:

```python
    assert execution.next_step("ABORT_REQUESTED") == "aborting"  # T47: nothing more is sent once an abort is asked
    with pytest.raises(ValueError):
        execution.next_step(None)  # a grant always has an attempt
```

Edit 2 (`tests/plan_d/test_mcp_write.py`, in `test_tool_schema_matches_the_contract_and_rejects_extras`), replace:

```python
        assert set(tools) == {"create_incident"}
```

with:

```python
        assert set(tools) == {"create_incident", "get_incident_receipt", "abort_incident"}  # T47's three
```

Run: `uv run python -m pytest tests/plan_k/test_recovery_tools.py tests/plan_k/test_write_tools_server.py tests/plan_d/test_mcp_write.py -q`
Expected: `41 failed, 9 passed` (among the failures: `has no attribute 'get_action'` (every scripted case, the
re-send ones included, patches it), `has no attribute
'get_incident_receipt'`, `has no attribute 'abort_envelope'`, `outcome_envelope() takes 1 positional argument but 2
were given`, `ValueError: attempt state ABORT_REQUESTED is not handled by the walking skeleton`, the tombstone
reasons mapped to `aborted_no_commit`, `'GRANT_REFUSED' == 'ABORT_NOT_DUE'` and `== 'NOT_REDISPATCHABLE'`, the
example's `'cancelled before send'`, and the one listed tool).

- [x] **Step 4: The lookup and abort clients**

Edit 1 (`mcp-write/src/ops_mcp_write/destination.py`, the module header), replace:

```python
The POST carries the exact canonical bytes the reviewer approved, wrapped with the action id and hash (AM-13 §4). What
comes back is classified into the AM-13 tool outcome vocabulary without optimism: a transport failure after SENT is
UNKNOWN, never "no effect" (BUILD_SPEC §1, §11); a committed receipt counts only if its action id and hash are ours
(SA:358); a tombstone becomes FAILED_NO_COMMIT with the reason `outcome_from_destination` derives.
```

with:

```python
Three calls, each with mcp-write's own workload token: the POST carries the exact canonical bytes the reviewer
approved, wrapped with the action id and hash (AM-13 §4); the restricted lookup reads the key that stands (SA:269); the
abort asks the destination to make the key a permanent tombstone, carrying the grant's hash (SA:266). What comes back
is classified into the AM-13 tool outcome vocabulary without optimism: a transport failure, a 404 (SA:269: NOT_FOUND is
never a no-commit), a 429 or a 503 is UNKNOWN, never "no effect" (BUILD_SPEC §1, §11); a committed receipt counts only
if its action id and hash are ours (SA:358); a tombstone becomes FAILED_NO_COMMIT with the reason
`outcome_from_destination` derives.
```

Edit 2 (`mcp-write/src/ops_mcp_write/destination.py`, the module header), replace:

```python
from typing import Any
```

with:

```python
from typing import Any, Final
```

Edit 3 (`mcp-write/src/ops_mcp_write/destination.py`, the module header), replace:

```python
from pydantic import ValidationError
```

with:

```python
from ops_core.states import Reason
from pydantic import ValidationError

TIMEOUT = httpx2.Timeout(10.0)  # one destination call per tool call; the 1, 2, 4, 8 s backoff is the worker's (T22)
# The abort reasons that mean the attempt was never sent (request_abort chose them from INTENT); `deadline` is SENT's.
NEVER_SENT: Final = frozenset({Reason.CANCELLED_BEFORE_SEND.value, Reason.EXPIRED.value})
```

Edit 4 (`mcp-write/src/ops_mcp_write/destination.py`, in `post_incident`), replace:

```python
    try:
        response = await http.post(
            f"{url}/internal/incidents",
            content=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=httpx2.Timeout(10.0),
        )
```

with:

```python
    return await _send(http, "POST", f"{url}/internal/incidents", token, body)


async def get_action(http: httpx2.AsyncClient, *, url: str, token: str, action_id: UUID) -> Reply | None:
    """The restricted lookup (SA:269): the key's receipt or tombstone, or 404 while there is none (UNKNOWN, never
    "no commit"). It reads; it never writes a key."""
    return await _send(http, "GET", f"{url}/internal/actions/{action_id}", token, None)


async def post_abort(
    http: httpx2.AsyncClient, *, url: str, token: str, action_id: UUID, payload_sha256: str, reason: str
) -> Reply | None:
    """The abort (SA:266): a fresh ABORTED tombstone carrying the grant's hash, or the key that already stands (a
    receipt, a REJECTED or an earlier ABORTED tombstone). It never creates an incident."""
    body = canonical_json({"payload_sha256": payload_sha256, "reason": reason})
    return await _send(http, "POST", f"{url}/internal/actions/{action_id}/abort", token, body)


async def _send(http: httpx2.AsyncClient, method: str, url: str, token: str, body: bytes | None) -> Reply | None:
    """One request with the workload token; None means the transport gave no usable answer (the caller's UNKNOWN)."""
    headers = {"Authorization": f"Bearer {token}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    try:
        response = await http.request(method, url, content=body, headers=headers, timeout=TIMEOUT)
```

Edit 5 (`mcp-write/src/ops_mcp_write/destination.py`, in `classify`), replace:

```python
        outcome, reason = outcome_from_destination(state, sent=True, cancel_requested=False)
```

with:

```python
        # An ABORTED key's reason is the one request_abort chose and the abort carried (Plan K ruling 3): `expired` or
        # `cancelled_before_send` only for an attempt never sent; anything else proves only that nothing committed.
        sent = tombstone.reason not in NEVER_SENT
        cancelled = tombstone.reason == Reason.CANCELLED_BEFORE_SEND.value
        outcome, reason = outcome_from_destination(state, sent=sent, cancel_requested=cancelled)
```

- [x] **Step 5: The recovery calls and `create_incident`'s abort**

Edit 1 (`mcp-write/src/ops_mcp_write/execution.py`, the module header), replace:

```python
through the definer functions grant_execution, mark_sent, record_outcome and lookup_action (T09 shape).
```

with:

```python
through the definer functions grant_execution, mark_sent, request_abort, record_outcome and lookup_action (T09 shape),
and the two recovery calls, the receipt lookup and the abort (T47).
```

Edit 2 (`mcp-write/src/ops_mcp_write/execution.py`, the module header), replace:

```python
otherwise the same action id and bytes are re-sent and the destination's idempotent key answers. There is never a second
action id for one run. Through the tool, the stored branch is unreachable once the outcome is recorded: the run has left
APPROVED and EXECUTING, so `server.create_incident`'s `resolve_invocation` refuses the handle first (T15, Plan J ruling
6), which production never needed (the worker skips the call past EXECUTING). A direct caller
(tests/e2e/test_mcp_write_live.py), or an overlapping call that resolved its handle before the outcome was recorded,
still reaches it. A transport failure after SENT is reported as UNKNOWN and recorded by nobody here: the worker holds
`mark_unknown` (SA:467; Plan E ruling 6).
```

with:

```python
otherwise `mark_sent` re-checks the run (T47) and the same action id and bytes are re-sent, and the destination's
idempotent key answers. There is never a second action id for one run. Through the tool, the stored branch is
unreachable once the outcome is recorded: the run has left APPROVED and EXECUTING, so `server.create_incident`'s
`resolve_invocation` refuses the handle first (T15, Plan J ruling 6), which production never needed (the worker skips
the call past EXECUTING). A direct caller (tests/e2e/test_mcp_write_live.py), or an overlapping call that resolved its
handle before the outcome was recorded, still reaches it. A transport failure after SENT is reported as UNKNOWN and
recorded by nobody here: the worker holds `mark_unknown` (SA:467; Plan E ruling 6).

Abort rule (SA:348, SA:465; Plan K rulings 3 and 24): when `mark_sent` answers `cancelled` or `expired`,
`create_incident` itself requests the abort (the function records ABORT_REQUESTED with the reason it chose), POSTs it
and records what the destination answers. For an attempt never sent nothing has left, and the run ends FAILED with
`cancelled_before_send` or `expired`; for the re-send of a SENT attempt the abort goes at once (`deadline`) and the
destination's answer decides: the receipt that already exists, or `aborted_no_commit`. `abort_incident` does the same
for a recover job, from INTENT or SENT. `get_incident_receipt` reads the key that stands and records it; it never writes
one. Each destination call is one request with a 10 s timeout; the backoff between calls, the scheduled recover jobs and
the redispatch of an unsent attempt are the worker's (T22).
```

Edit 3 (`mcp-write/src/ops_mcp_write/execution.py`, the module header), replace:

```python
from dataclasses import dataclass
```

with:

```python
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
```

Edit 4 (`mcp-write/src/ops_mcp_write/execution.py`, the module header), replace:

```python
from ops_core.states import IllegalTransition
```

with:

```python
from ops_core.states import AttemptState, IllegalTransition
```

Edit 5 (`mcp-write/src/ops_mcp_write/execution.py`, in `_POST_SENT_REFUSALS`), replace:

```python


def next_step(attempt_state: str | None) -> Literal["stored", "send", "resend"]:
    """What a (re)call does for an attempt in this state; states the skeleton cannot handle are refused."""
    if attempt_state == "RESOLVED":
        return "stored"
    if attempt_state == "INTENT":
        return "send"
    if attempt_state == "SENT":
        return "resend"
    raise ValueError(f"attempt state {attempt_state} is not handled by the walking skeleton")
```

with:

```python
# One destination request, given mcp-write's workload token.
Ask = Callable[[str], Awaitable[destination.Reply | None]]


def next_step(attempt_state: str | None) -> Literal["stored", "send", "resend", "aborting"]:
    """What a (re)call of `create_incident` does for the grant's attempt in this state; a grant always has one."""
    if attempt_state == AttemptState.RESOLVED:
        return "stored"
    if attempt_state == AttemptState.INTENT:
        return "send"
    if attempt_state == AttemptState.SENT:
        return "resend"
    if attempt_state == AttemptState.ABORT_REQUESTED:
        return "aborting"  # an abort was requested meanwhile; nothing more is sent (SA:334)
    raise ValueError(f"attempt state {attempt_state} is not one a grant can have")
```

Edit 6 (`mcp-write/src/ops_mcp_write/execution.py`, in `create_incident`), replace:

```python
async def create_incident(deps: Deps, *, handle: str, azp: str, proposal_id: UUID) -> ActionOutcome:
```

with:

```python
async def _ask(deps: Deps, grant: persistence.Grant, what: str, ask: Ask) -> ActionOutcome:
    """One destination request and its classification. After SENT, or after an abort request, nothing may escape as
    "no effect" (SA:356, Plan D ruling 21): any failure, the token's included, is UNKNOWN, reconciled later."""
    try:
        reply = await ask(await deps.destination_token.token())
        return destination.classify(reply, action_id=grant.action_id, payload_sha256=grant.payload_sha256)
    except Exception:
        log.exception("destination %s for action %s failed", what, grant.action_id)
        return destination.unknown(grant.action_id, grant.payload_sha256)


async def create_incident(deps: Deps, *, handle: str, azp: str, proposal_id: UUID) -> ActionOutcome:
```

Edit 7 (`mcp-write/src/ops_mcp_write/execution.py`, in `create_incident`), replace:

```python
    if step == "send":
        async with deps.session.unit() as conn:  # committed before I/O
            sent = await persistence.mark_sent(conn, handle=handle, azp=azp, action_id=grant.action_id)
        if sent == "resolved":  # a concurrent caller finished first
            return await _read_back(deps, handle, azp, grant)
        if sent in ("cancelled", "expired", "abort_requested"):
            # Nothing was sent. The UNKNOWN envelope makes the worker call mark_unknown, which moves the run to
            # OUTCOME_UNKNOWN and queues a recover job: conservative. TODO(T47): the abort replaces this (SA:348).
            return destination.unknown(grant.action_id, grant.payload_sha256)
    try:
        reply = await destination.post_incident(
            deps.http,
            url=deps.destination_url,
            token=await deps.destination_token.token(),
```

with:

```python
    if step == "aborting":  # the abort's own record decides; until then this call cannot know (T22 reconciles)
        return destination.unknown(grant.action_id, grant.payload_sha256)
    # A first send and a re-send of a SENT attempt both pass mark_sent, which re-checks the abort request, the cancel,
    # the dispatch deadline and (for a re-send) the job type under the runs lock (round 1, I1). The window between its
    # commit and the POST is AM-13's own, the same for both.
    async with deps.session.unit() as conn:  # committed before I/O
        sent = await persistence.mark_sent(conn, handle=handle, azp=azp, action_id=grant.action_id)
    if sent == "resolved":  # a concurrent caller finished first
        return await _read_back(deps, handle, azp, grant)
    if sent == "abort_requested":  # an abort request landed after the grant; nothing is sent
        return destination.unknown(grant.action_id, grant.payload_sha256)
    if sent == "not_redispatchable":  # a recover job never re-sends a SENT attempt (SA:345); nothing is sent
        raise persistence.Refused("NOT_REDISPATCHABLE")
    if sent in ("cancelled", "expired"):
        # Nothing more is sent. From INTENT the abort is a guaranteed no-commit (SA:348); after SENT it is the
        # immediate abort a cancel or the deadline calls for (SA:248, SA:242), and the destination decides.
        return await _abort(deps, handle, azp, grant)
    if sent not in ("sent", "already_sent"):  # an answer this code does not know must never read as "go ahead"
        raise persistence.PersistenceError(f"mark_sent answered {sent}")

    async def post(token: str) -> destination.Reply | None:
        return await destination.post_incident(
            deps.http,
            url=deps.destination_url,
            token=token,
```

Edit 8 (`mcp-write/src/ops_mcp_write/execution.py`, in `create_incident`), replace:

```python
        outcome = destination.classify(reply, action_id=grant.action_id, payload_sha256=grant.payload_sha256)
    except Exception:  # after SENT nothing may escape as "no effect" (SA:356, ruling 21): UNKNOWN, reconciled
        log.exception("destination call for action %s failed after SENT", grant.action_id)
        return destination.unknown(grant.action_id, grant.payload_sha256)
    if outcome.status is ToolOutcome.UNKNOWN:
        # A lost reply, a 503 or a malformed document: nothing is recorded here; the worker holds mark_unknown
        # (SA:467, Plan E ruling 6), and record_outcome refuses UNKNOWN by design.
        return outcome
    # An unmapped database failure (psycopg.Error) still escapes as a 500 and the worker's replay resends under the same
    # action id (the attempt is still SENT). A mapped refusal is answered UNKNOWN so the worker reconciles it.
```

with:

```python

    return await _record(deps, handle, azp, grant, await _ask(deps, grant, "dispatch", post))


async def _granted(deps: Deps, handle: str, azp: str, proposal_id: UUID) -> persistence.Grant:
    """The run's grant, which must be for the proposal named (SA:538: a recovery call is bound to its run's proposal);
    `lookup_action` resolves the handle again and reads nothing else (SA:466)."""
    async with deps.session.unit() as conn:
        grant = await persistence.lookup_action(conn, handle=handle, azp=azp)
    if grant.proposal_id != proposal_id:
        raise persistence.Refused("OTHER_PROPOSAL")  # before any destination call: a plain refusal
    return grant


async def get_incident_receipt(deps: Deps, *, handle: str, azp: str, proposal_id: UUID) -> ActionOutcome:
    """The recover job's receipt lookup (BS:393, SA:335): the stored outcome once the attempt is resolved, otherwise
    the key the destination holds, recorded. It creates nothing: no grant, attempt, job or key (R030)."""
    grant = await _granted(deps, handle, azp, proposal_id)
    if grant.attempt_state == AttemptState.RESOLVED:
        return _stored(grant)

    async def lookup(token: str) -> destination.Reply | None:
        return await destination.get_action(deps.http, url=deps.destination_url, token=token, action_id=grant.action_id)

    return await _record(deps, handle, azp, grant, await _ask(deps, grant, "lookup", lookup))


async def abort_incident(deps: Deps, *, handle: str, azp: str, proposal_id: UUID) -> ActionOutcome:
    """The recover job's abort (SA:336, SA:241-242): the stored outcome once resolved, otherwise the abort request,
    the abort POST and the record of what the destination answered (a fresh tombstone, or the key that stands)."""
    grant = await _granted(deps, handle, azp, proposal_id)
    if grant.attempt_state == AttemptState.RESOLVED:
        return _stored(grant)
    return await _abort(deps, handle, azp, grant)


async def _abort(deps: Deps, handle: str, azp: str, grant: persistence.Grant) -> ActionOutcome:
    """request_abort (its reason, committed before the abort leaves), the abort POST, the record (SA:465)."""
    async with deps.session.unit() as conn:
        reason = await persistence.request_abort(conn, handle=handle, azp=azp, action_id=grant.action_id)
    if reason == "resolved":  # the outcome already stands
        return await _read_back(deps, handle, azp, grant)

    async def abort(token: str) -> destination.Reply | None:
        return await destination.post_abort(
            deps.http,
            url=deps.destination_url,
            token=token,
            action_id=grant.action_id,
            payload_sha256=grant.payload_sha256,
            reason=reason,
        )

    return await _record(deps, handle, azp, grant, await _ask(deps, grant, "abort", abort))


async def _record(deps: Deps, handle: str, azp: str, grant: persistence.Grant, outcome: ActionOutcome) -> ActionOutcome:
    """Record what the destination answered and return what stands. UNKNOWN is returned unrecorded."""
    if outcome.status is ToolOutcome.UNKNOWN:
        # A lost reply, a 404, a 429, a 503 or a malformed document: nothing is recorded here; the worker holds
        # mark_unknown (SA:467, Plan E ruling 6), and record_outcome refuses UNKNOWN by design.
        return outcome
    # An unmapped database failure (psycopg.Error) still escapes as a 500, and the worker's next call meets the same
    # action id (nothing was recorded). A mapped refusal is answered UNKNOWN so the worker reconciles it: the
    # destination has answered, so an error envelope would hide an outcome that may exist (AM-13).
```

Edit 9 (`mcp-write/src/ops_mcp_write/execution.py`, in `create_incident`), replace:

```python
        log.exception("recording the outcome of action %s failed after SENT", grant.action_id)
```

with:

```python
        log.exception("recording the outcome of action %s failed after the destination answered", grant.action_id)
```

- [x] **Step 6: The three tools and their envelopes**

Edit 1 (`mcp-write/src/ops_mcp_write/server.py`, the module header), replace:

```python
One tool, `create_incident`; the grant, the dispatch and the outcome happen here, never in the worker.
```

with:

```python
Three tools, and the grant, every destination call and every outcome happen here, never in the worker:
`create_incident` for execute jobs (and a recover job's redispatch of an unsent attempt), and the recovery tools
`get_incident_receipt` and `abort_incident` for recover jobs only (T47). Every call resolves its `X-Ops-Invocation`
handle first: the server, the token's `azp`, expiry, the lease fence, the handle's open job, and the job type's
tools, run states and attempt states (`persistence.allowed_tool`). Only the worker's workload token is accepted here,
so the recovery tools are listed to that caller alone and refused for every handle but a recover job's (BS:393).
```

Edit 2 (`mcp-write/src/ops_mcp_write/server.py`, the module header), replace:

```python
from collections.abc import AsyncIterator
```

with:

```python
from collections.abc import AsyncIterator, Awaitable, Callable
```

Edit 3 (`mcp-write/src/ops_mcp_write/server.py`, in `refusal_error`), replace:

```python
    """The tool error for a grant refusal: MEMBERSHIP_STALE is the one the worker retries (Plan F ruling 14)."""
    if code == "MEMBERSHIP_STALE":
        return tool_error("GRANT_DEFERRED", f"grant deferred: {code}", retryable=True)
```

with:

```python
    """The tool error for a definer's refusal: MEMBERSHIP_STALE is the one grant refusal the worker retries (Plan F
    ruling 14); ABORT_NOT_DUE (an abort before a cancel or the dispatch deadline) is retryable once either arrives
    (Plan K ruling 3); NOT_REDISPATCHABLE (a recover job asking to re-send a SENT attempt, SA:345) is final. Like every
    refusal before a destination call, none names an action (SA:355)."""
    if code == "MEMBERSHIP_STALE":
        return tool_error("GRANT_DEFERRED", f"grant deferred: {code}", retryable=True)
    if code == "ABORT_NOT_DUE":
        return tool_error(code, "abort not due: not cancelled and before the dispatch deadline", retryable=True)
    if code == "NOT_REDISPATCHABLE":
        return tool_error(code, "a recover job redispatches only an attempt that was never sent")
```

Edit 4 (`mcp-write/src/ops_mcp_write/server.py`, in `outcome_envelope`), replace:

```python
def outcome_envelope(outcome: ActionOutcome) -> ToolResult:
    """`ok` only wraps SUCCEEDED (R083); every other outcome is `status=outcome` with `data.action_id` (SA:352)."""
    data = outcome.model_dump(mode="json")
    doc = envelope("create_incident", data=data)
```

with:

```python
def outcome_envelope(outcome: ActionOutcome, tool_name: str = ToolName.CREATE_INCIDENT.value) -> ToolResult:
    """`ok` only wraps SUCCEEDED (R083); every other outcome is `status=outcome` with `data.action_id` (SA:352). The
    data is the ActionOutcome shape `create_incident` and `get_incident_receipt` share (BS:393's minimal outcome)."""
    data = outcome.model_dump(mode="json")
    doc = envelope(tool_name, data=data)
    if outcome.status is not ToolOutcome.SUCCEEDED:
        doc["status"] = "outcome"
    return doc


def abort_envelope(outcome: ActionOutcome) -> ToolResult:
    """`abort_incident`'s data (SA:356): the action, the outcome and the destination's receipt or tombstone, nothing
    else (the tombstone carries the destination's reason). `ok` only for SUCCEEDED, an abort that met the receipt
    already there; UNKNOWN and CONFLICT carry neither (Plan K, the abort data's added outcomes)."""
    data = {
        "action_id": str(outcome.action_id),
        "outcome": outcome.status.value,
        "receipt": None if outcome.receipt is None else outcome.receipt.model_dump(mode="json"),
        "tombstone": None if outcome.tombstone is None else outcome.tombstone.model_dump(mode="json"),
    }
    doc = envelope(ToolName.ABORT_INCIDENT.value, data=data)
```

Edit 5 (`mcp-write/src/ops_mcp_write/server.py`, in `build_server`), replace:

```python
def build_server(state: State, *, issuer: str, resource_url: str) -> MCPServer:
    """Assemble the MCP server with bearer auth and the one strict tool, bound to `state`."""

    # strict=False on this one field: the model is strict, and strict UUID validation refuses the string a client sends
    async def create_incident(proposal_id: Annotated[UUID, Field(strict=False)], ctx: Context) -> ToolResult:
        """Grant, dispatch and record the approved proposal's incident (AM-13 §2, AM-20.3 grant_execution)."""
```

with:

```python
# A tool's work once its handle resolved: (deps, the raw handle, the token's azp) -> the outcome.
Work = Callable[[execution.Deps, str, str], Awaitable[ActionOutcome]]
# strict=False on this one field: the model is strict, and strict UUID validation refuses the string a client sends.
ProposalId = Annotated[UUID, Field(strict=False)]


def build_server(state: State, *, issuer: str, resource_url: str) -> MCPServer:
    """Assemble the MCP server with bearer auth and the three strict write tools, bound to `state`."""

    async def answer(tool: ToolName, ctx: Context, work: Work) -> ActionOutcome | ToolResult:
        """Resolve the handle for `tool` before any work (SA:459; Plan K ruling 26), then do it. A refusal before
        anything reached the destination is a plain error envelope without an action id (SA:355)."""
```

Edit 6 (`mcp-write/src/ops_mcp_write/server.py`, in `build_server`), replace:

```python
            return envelope("create_incident", error=tool_error("INVALID_HANDLE", "missing invocation handle"))
        try:
            async with state.deps.session.unit() as conn:
                await persistence.resolve_invocation(
                    conn, handle=handle, azp=token.client_id, tool=ToolName.CREATE_INCIDENT
                )  # binds server, azp, expiry and the tool allowlist before any work (SA:459)
            outcome = await execution.create_incident(
                state.deps, handle=handle, azp=token.client_id, proposal_id=proposal_id
            )
        except persistence.HandleRejected as exc:
            return envelope("create_incident", error=tool_error("INVALID_HANDLE", str(exc)))
        except persistence.Refused as exc:
            return envelope("create_incident", error=refusal_error(exc.code))
        except persistence.NotFound:
            return envelope("create_incident", error=tool_error("NOT_FOUND", "run not found"))
        except persistence.VersionConflict:
            # Only grant_execution and mark_sent can raise this here, both before this call sends anything, so the
            # worker closes the job without a retry cycle. After SENT execution.py answers UNKNOWN instead (AM-13).
            return envelope("create_incident", error=tool_error("STALE_RUN", "run is no longer executing"))
        except persistence.HashMismatch:
            return envelope("create_incident", error=tool_error("HASH_MISMATCH", "stored bytes do not match"))
        # AuthorityViolation stays unmapped on purpose: it is a deployment error (the role lacks a grant), so the raw
        # tool error and the worker's re-queue are the right outcome.
        return outcome_envelope(outcome)
```

with:

```python
            return envelope(tool.value, error=tool_error("INVALID_HANDLE", "missing invocation handle"))
        try:
            async with state.deps.session.unit() as conn:
                await persistence.resolve_invocation(conn, handle=handle, azp=token.client_id, tool=tool)
            return await work(state.deps, handle, token.client_id)
        except persistence.HandleRejected as exc:
            return envelope(tool.value, error=tool_error("INVALID_HANDLE", str(exc)))
        except persistence.Refused as exc:
            return envelope(tool.value, error=refusal_error(exc.code))
        except persistence.NotFound:
            return envelope(tool.value, error=tool_error("NOT_FOUND", "run not found"))
        except persistence.VersionConflict:
            # Only mark_sent raises this here, before anything is sent: a recover job redispatching an unsent attempt
            # while its run is not EXECUTING (redispatch from OUTCOME_UNKNOWN is T22's). After a destination call
            # execution.py answers UNKNOWN instead (AM-13).
            return envelope(tool.value, error=tool_error("STALE_RUN", "run is no longer executing"))
        # HashMismatch is not mapped: only record_outcome raises it, after the destination answered, where execution.py
        # answers UNKNOWN (tests/plan_k/test_migration_0010.py pins that no earlier definer can; Plan K ruling 20).
        # AuthorityViolation stays unmapped on purpose: it is a deployment error (the role lacks a grant), so the raw
        # tool error and the worker's re-queue are the right outcome.

    async def create_incident(proposal_id: ProposalId, ctx: Context) -> ToolResult:
        """Grant, dispatch and record the approved proposal's incident (AM-13 §2, AM-20.3 grant_execution)."""

        async def work(deps: execution.Deps, handle: str, azp: str) -> ActionOutcome:
            return await execution.create_incident(deps, handle=handle, azp=azp, proposal_id=proposal_id)

        result = await answer(ToolName.CREATE_INCIDENT, ctx, work)
        return outcome_envelope(result) if isinstance(result, ActionOutcome) else result

    async def get_incident_receipt(proposal_id: ProposalId, ctx: Context) -> ToolResult:
        """Recover jobs only: the outcome of the action already granted for this proposal, from the destination's
        restricted lookup (BS:393). Creates nothing."""

        async def work(deps: execution.Deps, handle: str, azp: str) -> ActionOutcome:
            return await execution.get_incident_receipt(deps, handle=handle, azp=azp, proposal_id=proposal_id)

        result = await answer(ToolName.GET_INCIDENT_RECEIPT, ctx, work)
        return (
            outcome_envelope(result, ToolName.GET_INCIDENT_RECEIPT.value)
            if isinstance(result, ActionOutcome)
            else result
        )

    async def abort_incident(proposal_id: ProposalId, ctx: Context) -> ToolResult:
        """Recover jobs only: abort the action already granted for this proposal once it is cancelled or past its
        dispatch deadline; the destination answers with a tombstone or the receipt that already stands (SA:241-242)."""

        async def work(deps: execution.Deps, handle: str, azp: str) -> ActionOutcome:
            return await execution.abort_incident(deps, handle=handle, azp=azp, proposal_id=proposal_id)

        result = await answer(ToolName.ABORT_INCIDENT, ctx, work)
        return abort_envelope(result) if isinstance(result, ActionOutcome) else result
```

Edit 7 (`mcp-write/src/ops_mcp_write/server.py`, in `build_server`), replace:

```python
        tools=[strict_tool(create_incident)],
```

with:

```python
        tools=[strict_tool(create_incident), strict_tool(get_incident_receipt), strict_tool(abort_incident)],
```

- [x] **Step 7: The abort's result schema and the example's reason**

Edit 1 (`scripts/build_schemas.py`, in `abort_outcome`), replace:

```python
    """`abort_incident` data: the destination answers an abort with a receipt (already committed) or a tombstone."""
```

with:

```python
    """`abort_incident` data: the destination answers an abort with a receipt (already committed) or a tombstone; an
    abort it did not answer (a lost reply, a 503) is UNKNOWN, and one that met another hash's receipt is CONFLICT,
    both with neither (T47, Plan K: SA:356's two outcomes cannot say either)."""
```

Edit 2 (`scripts/build_schemas.py`, in `abort_outcome`), replace:

```python
            "outcome": {"enum": [ToolOutcome.SUCCEEDED.value, ToolOutcome.FAILED_NO_COMMIT.value]},
```

with:

```python
            "outcome": {"enum": [o.value for o in ToolOutcome]},
```

Edit 3 (`scripts/build_schemas.py`, in `abort_outcome`), replace:

```python
            when(
                props(outcome={"const": ToolOutcome.SUCCEEDED.value}),
                props(receipt=RECEIPT, tombstone=NULL),
                props(tombstone=TOMBSTONE, receipt=NULL),
            )
```

with:

```python
            when(props(outcome={"const": ToolOutcome.SUCCEEDED.value}), props(receipt=RECEIPT, tombstone=NULL)),
            when(
                props(outcome={"const": ToolOutcome.FAILED_NO_COMMIT.value}), props(tombstone=TOMBSTONE, receipt=NULL)
            ),
            when(
                props(outcome={"enum": [ToolOutcome.UNKNOWN.value, ToolOutcome.CONFLICT.value]}),
                props(receipt=NULL, tombstone=NULL),
            ),
```

Edit 4 (`scripts/build_schemas.py`, in `tool_result`), replace:

```python
            props(data=props(outcome={"const": "FAILED_NO_COMMIT"})),
```

with:

```python
            props(data=props(outcome={"enum": ["FAILED_NO_COMMIT", "UNKNOWN", "CONFLICT"]})),
```

Edit 5 (`scripts/build_schemas.py`, in `examples`), replace:

```python
        "reason": "cancelled before send",
```

with:

```python
        "reason": "cancelled_before_send",  # the destination's own token (keys.ABORT_REASONS), as it answers
```

Run:

```bash
uv run python -m scripts.build_schemas
git status --short schemas
```

Expected: the generator prints `schemas/: 25 schema documents (19 contracts, 6 tool inputs); 89 examples (35 valid,
54 invalid); index.json version 1.3.3`, and `git status` lists ten modified files: `schemas/tool-result.schema.json`
and nine examples (`event-failed-valid`, `event-invalid-confirmed-with-tombstone`,
`event-invalid-late-evidence-no-outcome`, `event-invalid-late-evidence-succeeded-without-receipt`,
`outcome-failed-valid`, `outcome-invalid-committed-tombstone`, `outcome-invalid-failed-reason`,
`outcome-invalid-rejected-reason-aborted-tombstone`, `tool-abort_incident-valid`; each only the tombstone's reason).

Run: the Step 3 command again.
Expected: `50 passed`.

Run: `uv run python -m pytest tests/plan_k tests/plan_c tests/plan_d tests/plan_e tests/plan_h tests/plan_j -q`
Expected: `688 passed, 19 skipped`.

- [x] **Step 8: Gates and commit**

Format, lint and count characters on every file of this task.

Run: `PYTHONUTF8=1 uv run python scripts/check.py`
Expected: `CHECK: GREEN`; pytest `1152 passed, 169 skipped` (1103 + 49 in `tests/plan_k`; the four edited modules keep
their counts).

Run: `PYTHONUTF8=1 uv run python scripts/check.py --profile test`
Expected: `CHECK: GREEN`; pytest `1300 passed, 21 skipped` (arithmetic, not measured: the dev count plus the 148
live-gated tests; R105's worker and the Plan D-J write-path live tests now pass the attempt-state allowlist). Then
`git checkout -- reports/bootstrap reports/skeleton reports/auth reports/admission reports/leases reports/events
reports/outbox reports/mcp-read`.

Run: `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`
Expected: exit 0 (its contract check validates the regenerated examples).

```bash
git add core/src/ops_core/jobs.py core/src/ops_core/persistence.py mcp-write/src/ops_mcp_write scripts/build_schemas.py
git add schemas tests/plan_k tests/plan_d/test_persistence_pure.py tests/plan_e/test_persistence_errors.py
git add tests/plan_j/test_allowlist.py tests/plan_d/test_mcp_write.py
git commit -m "feat(mcp-write): the attempt-state allowlist, get_incident_receipt and abort_incident (T47)"
```

---

### Task 4: Live evidence at mcp-write over HTTP — R030, R131's write half, the re-send, the faults, the aborts

**Files:**
- Create: `tests/e2e/test_mcp_write_t47_live.py`
- Modify: `tests/plan_b/test_evidence.py:1-9` (docstring), `:19-29` (`EVIDENCE_ROOTS`)

**Requirements:** R030 ("Normal/model tools cannot call lookup; reconciliation workload sees minimal existing-action
outcome only"), R131's write half (the `pg_proc` ACL, a read handle at mcp-write, incident-sim refusing mcp-read's
token), T47 DoD 1-3, T47 review note 3; rulings 8, 13-15, 19-21, 24. This task writes no production code: Tasks 1-3
built what it proves, so its tests pass the first time they run. mcp-write and incident-sim run in the test's own event
loop on free loopback ports, so `ops_mcp_write.destination`'s calls are counted in-process; the destination's tables
are read as role `incident`.

**Interfaces:**
- Consumes: Task 2's `AZP`, `LATE`, `NOW`, `cancel`, `execute_handle`, `fence_of`, `recover_handle`; the e2e helpers
  `approved_run`, `ALPHA`,
  `attempt_states`, `investigate_job`, `read_handle`, `new_run`, `lease_for`, `purge_run`, `refused`; Plan J's
  `assert_refused`, `call`, `free_port`, `guarded`, `set_server`, `worker_token`
  (`tests.e2e.test_mcp_read_t15_live`); `ops_incident_sim.app.production_app`; `ops_mcp_write.server.production_app`.
- Produces (Task 5 imports them): `COUNTS`, `WRITE_TOOLS`, `started(app, name)`, `write_token(secret)`, `arm(sim,
  token, kind)`, `at_destination(incident_conn, action)`, `keys_total(incident_conn)`, and `recover_handle` as it
  imported it from Task 2.

- [x] **Step 1: Scan the new evidence root for secrets**

Edit 1 (`tests/plan_b/test_evidence.py`, the module header), replace:

```python
`reports/events` and `reports/outbox` (T14's journal and outbox evidence) and `reports/mcp-read` (T15's handle,
token and independent-client evidence) are scanned the same way.
```

with:

```python
`reports/events` and `reports/outbox` (T14's journal and outbox evidence), `reports/mcp-read` (T15's handle,
token and independent-client evidence) and `reports/mcp-write` (T47's write-path and independent-client evidence)
are scanned the same way.
```

Edit 2 (`tests/plan_b/test_evidence.py`, in `EVIDENCE_ROOTS`), replace:

```python
    Path("reports/mcp-read"),
)
```

with:

```python
    Path("reports/mcp-read"),
    Path("reports/mcp-write"),
)
```

- [x] **Step 2: Write the live cases**

Create `tests/e2e/test_mcp_write_t47_live.py`:

```python
"""mcp-write's T47 cases over a real socket with Keycloak's tokens and a real incident-sim (OPS_LIVE=1; R030, R131
write half, T47 DoD 1-3, T47 review note 3; Plan K rulings 8, 13-15, 19-21 and 24).

mcp-write is `production_app()` under uvicorn on a free loopback port in the test's own event loop, pointed at an
incident-sim `production_app()` on another free port (the test profile, so its fault route exists); the independent
process is tests/e2e/test_mcp_write_process_live.py. Every recover handle is staged by the superuser, as mark_unknown
or the sweeper would queue its job (the worker's recover handler is T22's). mcp-write's destination calls are counted
in-process (`ops_mcp_write.destination`), and the destination's own tables are read as role `incident`.

Catches: an `mcp_exec` that may execute anything beyond its seven functions; a read handle (investigate, resume_input,
or one whose stored server column lies) answered at mcp-write; incident-sim accepting mcp-read's token; a receipt lookup
or an abort answered for an execute or investigate handle, or for an APPROVED run (no grant); a lookup that writes a
key, a grant, an attempt, a job or a proposal, or answers more than the minimal outcome; an abort that writes more than
its own state rows and its tombstone; the re-queued execute job's re-send
creating a second action or incident; a 404, 429 or lost reply recorded as anything but UNKNOWN; a foreign receipt hash
recorded as anything but CONFLICT, or re-queried once recorded; an abort before it is due; a cancelled or expired
attempt sent instead of aborted, or ending without the destination's tombstone; and a redispatch outside EXECUTING
that sends anything.
"""

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
import uvicorn
from mcp_types import CallToolResult
from ops_core import persistence, privileges, settings
from ops_core.jobs import Server
from ops_core.settings import Role
from ops_core.tokens import WorkloadTokenSource
from ops_incident_sim.app import production_app as incident_sim_app
from ops_mcp_write import destination
from ops_mcp_write.server import production_app

from tests.e2e.conftest import lease_for, purge_run
from tests.e2e.test_definers_run_path_live import refused
from tests.e2e.test_fenced_definers_live import attempt_states, investigate_job, read_handle
from tests.e2e.test_mcp_read_t15_live import assert_refused, call, free_port, guarded, set_server, worker_token
from tests.e2e.test_mcp_write_live import ALPHA, approved_run
from tests.e2e.test_migration_0010_live import AZP, LATE, NOW, cancel, execute_handle, fence_of, recover_handle
from tests.e2e.test_migrations_and_persistence import new_run

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
EVIDENCE = Path("reports/mcp-write/t47-mcp-write.txt")
EXPECTED_LINES = 10  # one per test below
WRITE_TOOLS = ("create_incident", "get_incident_receipt", "abort_incident")
MCP_EXEC_FUNCTIONS = {
    "current_time",  # erratum 15
    "resolve_invocation",
    "grant_execution",
    "mark_sent",
    "record_outcome",
    "request_abort",
    "lookup_action",
}
COUNTS = (
    "SELECT (SELECT count(*) FROM app.execution_grant) AS grants, (SELECT count(*) FROM app.action_attempt)"
    " AS attempts, (SELECT count(*) FROM app.jobs) AS jobs, (SELECT count(*) FROM app.proposals) AS proposals"
)


@pytest.fixture(scope="module")
def lines() -> Iterator[list[str]]:
    out = [f"T47 mcp-write — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"]
    yield out
    if len(out) != 1 + EXPECTED_LINES:  # a failed or partial run leaves the committed file as it was
        return
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


@asynccontextmanager
async def started(app: Any, name: str) -> AsyncIterator[str]:
    """`app` under uvicorn on a free loopback port in this event loop; its base URL. Stopped in `finally` by uvicorn's
    own shutdown, never a cancel; a failed start or a failure after it is raised, not only logged."""
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", log_config=None))
    task = asyncio.create_task(guarded(server))
    try:
        while not server.started:
            if task.done():
                task.result()  # a failed start raises here instead of waiting for ever
            await asyncio.sleep(0.05)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await asyncio.wait({task})
    failure = None if task.cancelled() else task.exception()
    if failure is not None:
        raise RuntimeError(f"{name} failed after it started") from failure


@asynccontextmanager
async def write_stack(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[tuple[str, str]]:
    """incident-sim, then mcp-write pointed at it (mcp-write reads `OPS_INCIDENT_SIM_URL` at its start); both URLs."""
    async with started(incident_sim_app(), "incident-sim") as sim:
        monkeypatch.setenv("OPS_INCIDENT_SIM_URL", sim)
        async with started(production_app(), "mcp-write") as base:
            yield sim, f"{base}/mcp"


async def write_token(secret: Callable[[str], str]) -> str:
    """mcp-write's own workload token (aud incident-sim, azp ops-mcp-write): what arms incident-sim's faults."""
    kcs = settings.keycloak()
    return await WorkloadTokenSource(
        token_url=kcs.token_url, client_id="ops-mcp-write", client_secret=secret("kc_client_secret_ops_mcp_write")
    ).token()


async def arm(sim: str, token: str, kind: str) -> None:
    """Arm one occurrence of a test-profile destination fault."""
    async with httpx2.AsyncClient() as http:
        armed = await http.post(
            f"{sim}/internal/faults/{kind}", json={"count": 1}, headers={"Authorization": f"Bearer {token}"}
        )
    assert armed.status_code == 200 and kind in armed.json()["armed"]


class Calls:
    """mcp-write's destination calls, counted in-process (the server runs in this test's event loop)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.made: list[str] = []
        for name in ("post_incident", "get_action", "post_abort"):
            monkeypatch.setattr(destination, name, self.counted(name, getattr(destination, name)))

    def counted(self, name: str, real: Any) -> Any:
        async def call(*args: Any, **kwargs: Any) -> Any:
            self.made.append(name)
            return await real(*args, **kwargs)

        return call


def data(result: CallToolResult, status: str) -> dict[str, Any]:
    """An answered call's envelope data, with the envelope status checked: no transport error, no error object."""
    doc = result.structured_content
    assert not result.is_error and isinstance(doc, dict) and doc["status"] == status and doc["error"] is None
    assert isinstance(doc["data"], dict)
    return doc["data"]


def error(result: CallToolResult) -> dict[str, Any]:
    """A refused call's error object; a refusal never carries data or an action id (SA:355)."""
    doc = result.structured_content
    assert not result.is_error and isinstance(doc, dict) and doc["status"] == "error" and doc["data"] is None
    assert "action_id" not in str(doc)
    assert isinstance(doc["error"], dict)
    return doc["error"]


async def keys_total(incident_conn: persistence.Conn) -> int:
    """Every key the destination holds, whoever's: a call that must write none is checked against this."""
    cur = await incident_conn.execute("SELECT count(*) AS n FROM incident.action_key")
    return int((await cur.fetchone() or {})["n"])


async def at_destination(incident_conn: persistence.Conn, action: UUID) -> tuple[tuple[str, str | None] | None, int]:
    """The destination's key for the action (state, reason) and how many incidents it holds for it."""
    cur = await incident_conn.execute("SELECT state, reason FROM incident.action_key WHERE action_id = %s", (action,))
    key = await cur.fetchone()
    cur = await incident_conn.execute("SELECT count(*) AS n FROM incident.incidents WHERE action_id = %s", (action,))
    return (None if key is None else (key["state"], key["reason"])), int((await cur.fetchone() or {})["n"])


async def run_state(app_conn: persistence.Conn, run: UUID) -> tuple[str, str | None]:
    cur = await app_conn.execute("SELECT state, reason FROM app.runs WHERE run_id = %s", (run,))
    row = await cur.fetchone() or {}
    return row["state"], row["reason"]


async def test_r131_mcp_exec_executes_exactly_the_write_path_functions(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    """Ruling 13: the pg_proc ACL. `asset_scope` and `search_procedures_scoped`, the read functions R131 names, do not
    exist yet (T16/T17), so "no read function" is shown as no EXECUTE on any `app` function outside the seven."""
    cur = await app_conn.execute(
        "SELECT p.proname AS name, has_function_privilege('mcp_exec', p.oid, 'EXECUTE') AS allowed"
        " FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'app'"
    )
    rows = await cur.fetchall()
    assert {row["name"] for row in rows if row["allowed"]} == MCP_EXEC_FUNCTIONS
    others = (set(privileges.DEFINER_FUNCTIONS) | set(privileges.HELPER_FUNCTIONS)) - MCP_EXEC_FUNCTIONS
    assert others <= {row["name"] for row in rows}  # every other function exists, so the line above is not vacuous
    mcp_exec = await role_conn(Role.MCP_EXEC)
    assert await refused(mcp_exec, "SELECT * FROM app.mark_unknown(%s, 1)", (uuid4(),)) == "42501"  # the worker's
    lines.append(f"R131 write half: mcp_exec EXECUTE = the seven write-path functions; {len(others)} others refused")


async def test_r131_read_handles_are_refused_at_mcp_write(
    app_conn: persistence.Conn,
    role_conn: RoleConn,
    secret: Callable[[str], str],
    monkeypatch: pytest.MonkeyPatch,
    lines: list[str],
) -> None:
    """Ruling 14: an investigate and a resume_input handle at each of the three tools, then the investigate handle with
    a stored server column that lies; each is live at mcp_read (the positive control) and grants nothing; the execute
    handle of an approved run is then answered at mcp-write."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    mcp_read, mcp_exec = await role_conn(Role.MCP_READ), await role_conn(Role.MCP_EXEC)
    _, _, read_run = await new_run(app_conn, ALPHA, api=api)
    _, run, proposal, execute = await approved_run(app_conn, api=api, worker=worker)
    token = await worker_token(secret)
    arguments = {"proposal_id": str(proposal)}
    resolve = "SELECT job_id FROM app.resolve_invocation(%s, 'ops-worker')"
    try:
        lease = await lease_for(worker, read_run)
        investigate = await read_handle(worker, read_run, await investigate_job(app_conn, read_run), lease)
        resume = uuid4()  # a resume_input job staged by the superuser: the worker creates none before T20
        await app_conn.execute(
            "INSERT INTO app.jobs (id, type, tenant_id, run_id, dedup_key) VALUES (%s, 'resume_input', %s, %s, %s)",
            (resume, ALPHA, read_run, f"{read_run}:{uuid4()}"),
        )
        async with worker.transaction():
            resume_input = await persistence.mint_handle(
                worker, run_id=read_run, job_id=resume, server=Server.READ, azp=AZP, fence=lease.fence
            )
        cur = await app_conn.execute(COUNTS)
        before = dict(await cur.fetchone() or {})
        async with write_stack(monkeypatch) as (_, url):
            for handle in (investigate, resume_input):
                cur = await mcp_read.execute(resolve, (handle,))
                assert (await cur.fetchone() or {}).get("job_id") is not None  # live at mcp-read
                for tool in WRITE_TOOLS:
                    assert_refused(await call(url, token, handle, tool, arguments))
            await set_server(app_conn, investigate, "write")  # the lie: the job type still says read
            for tool in WRITE_TOOLS:
                assert_refused(await call(url, token, investigate, tool, arguments))
            assert await refused(mcp_exec, resolve, (investigate,)) == "OC008"  # mcp_exec's own resolution agrees
            await set_server(app_conn, investigate, "read")
            cur = await mcp_read.execute(resolve, (investigate,))
            assert (await cur.fetchone() or {}).get("job_id") == await investigate_job(app_conn, read_run)
            cur = await app_conn.execute(COUNTS)
            assert dict(await cur.fetchone() or {}) == before  # nine refusals: no grant, attempt, job or proposal
            answered = data(await call(url, token, execute, "create_incident", arguments), "ok")
            assert answered["status"] == "SUCCEEDED"  # the write handle is answered here
        lines.append(
            "R131 write half: investigate and resume_input handles refused at all three tools (each live at mcp_read),"
            " lying server column refused (and at mcp_exec); no grant; the execute handle answered SUCCEEDED"
        )
    finally:
        await purge_run(app_conn, read_run)
        await purge_run(app_conn, run)


async def test_r131_incident_sim_refuses_mcp_reads_token(
    incident_conn: persistence.Conn, secret: Callable[[str], str], lines: list[str]
) -> None:
    """Ruling 15: mcp-read's workload token at each incident-sim route is 403 and writes nothing; mcp-write's token on
    the same lookup passes authentication (the positive control). That mcp-read cannot reach incident-sim over the
    network is T30's Docker network test."""
    kcs = settings.keycloak()
    read_token = await WorkloadTokenSource(
        token_url=kcs.token_url, client_id="ops-mcp-read", client_secret=secret("kc_client_secret_ops_mcp_read")
    ).token()
    action, sha = uuid4(), "e" * 64
    body = {"action_id": str(action), "payload_sha256": sha, "payload_canonical": '{"x":1}'}
    routes = {
        "incident": ("POST", "/internal/incidents", body),
        "lookup": ("GET", f"/internal/actions/{action}", None),
        "abort": ("POST", f"/internal/actions/{action}/abort", {"payload_sha256": sha, "reason": "expired"}),
    }
    cur = await incident_conn.execute("SELECT count(*) AS n FROM incident.action_key")
    keys = int((await cur.fetchone() or {})["n"])
    async with started(incident_sim_app(), "incident-sim") as sim, httpx2.AsyncClient() as http:
        answers = {}
        for name, (method, path, payload) in routes.items():
            headers = {"Authorization": f"Bearer {read_token}"}
            response = await http.request(method, f"{sim}{path}", json=payload, headers=headers)
            answers[name] = (response.status_code, response.json()["code"])
        own = {"Authorization": f"Bearer {await write_token(secret)}"}
        control = await http.get(f"{sim}/internal/actions/{action}", headers=own)
    assert answers == {name: (403, "FORBIDDEN") for name in routes}
    assert (control.status_code, control.json()["code"]) == (404, "NOT_FOUND")  # authenticated; no such key
    cur = await incident_conn.execute("SELECT count(*) AS n FROM incident.action_key")
    assert int((await cur.fetchone() or {})["n"]) == keys  # nothing written
    lines.append("R131/DoD 3 token half: ops-mcp-read token 403 at incidents, lookup and abort; ops-mcp-write 404")


async def test_r030_the_receipt_lookup_is_recover_only_and_creates_nothing(
    app_conn: persistence.Conn,
    role_conn: RoleConn,
    incident_conn: persistence.Conn,
    secret: Callable[[str], str],
    monkeypatch: pytest.MonkeyPatch,
    lines: list[str],
) -> None:
    """Rulings 8 and 19: the reply to the first send is lost after commit (UNKNOWN, attempt SENT); an execute handle,
    an investigate handle and a recover handle of an APPROVED run (no grant) are refused at the recovery tools, the last
    by the run-state rule (a run in a recover state without a grant cannot arise: only grant_execution leaves
    APPROVED for EXECUTING, and only with a grant); a recover
    handle's first lookup meets a delayed receipt (404: UNKNOWN, nothing recorded), its second the receipt (SUCCEEDED,
    the minimal outcome). Nothing but one RESOLVED row is written, and nothing is POSTed."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    _, run, proposal, execute = await approved_run(app_conn, api=api, worker=worker)
    _, bare, bare_proposal, _ = await approved_run(app_conn, api=api, worker=worker)  # APPROVED, never granted
    _, _, read_run = await new_run(app_conn, ALPHA, api=api)
    token, own = await worker_token(secret), await write_token(secret)
    arguments = {"proposal_id": str(proposal)}
    try:
        async with write_stack(monkeypatch) as (sim, url):
            await arm(sim, own, "lose_after_commit")
            first = data(await call(url, token, execute, "create_incident", arguments), "outcome")
            assert first["status"] == "UNKNOWN"
            action = UUID(first["action_id"])
            fresh = await execute_handle(worker, run, fence=await fence_of(app_conn, run))
            investigate = await read_handle(
                worker, read_run, await investigate_job(app_conn, read_run), await lease_for(worker, read_run)
            )
            unrelated = await recover_handle(app_conn, worker, bare, "timeout")
            for tool in ("get_incident_receipt", "abort_incident"):
                assert_refused(await call(url, token, fresh, tool, arguments))  # execute jobs never look up
                assert_refused(await call(url, token, investigate, tool, arguments))  # nor do read jobs
            for tool in WRITE_TOOLS:  # an APPROVED run is in no recover state: refused, and nothing is created
                assert_refused(await call(url, token, unrelated, tool, {"proposal_id": str(bare_proposal)}))
            recover = await recover_handle(app_conn, worker, run, "timeout")
            cur = await app_conn.execute(COUNTS)
            before = dict(await cur.fetchone() or {})
            calls = Calls(monkeypatch)
            await arm(sim, own, "delay_receipt")
            delayed = data(await call(url, token, recover, "get_incident_receipt", arguments), "outcome")
            assert delayed["status"] == "UNKNOWN" and await attempt_states(app_conn, run) == ["INTENT", "SENT"]
            found = data(await call(url, token, recover, "get_incident_receipt", arguments), "ok")
            cur = await app_conn.execute(COUNTS)
            after = dict(await cur.fetchone() or {})
        assert set(found) == {"status", "action_id", "payload_sha256", "receipt", "tombstone", "reason"}  # minimal
        assert found["status"] == "SUCCEEDED" and UUID(found["action_id"]) == action and found["tombstone"] is None
        assert calls.made == ["get_action", "get_action"]  # a lookup never POSTs
        assert after == before  # no grant, attempt, job or proposal created
        assert await attempt_states(app_conn, run) == ["INTENT", "SENT", "RESOLVED"]
        assert await at_destination(incident_conn, action) == (("COMMITTED", None), 1)
        assert await run_state(app_conn, run) == ("SUCCEEDED", None)
        cur = await app_conn.execute("SELECT count(*) AS n FROM app.execution_grant WHERE run_id = %s", (bare,))
        assert (await cur.fetchone() or {})["n"] == 0
        lines.append(
            "R030: execute, investigate and APPROVED-run (no grant) recover handles refused at the recovery tools;"
            " recover lookup: delay_receipt 404 -> UNKNOWN unrecorded, then SUCCEEDED (minimal outcome); GETs only;"
            " counts unchanged"
        )
    finally:
        for each in (run, bare, read_run):
            await purge_run(app_conn, each)


async def test_the_executing_re_send_returns_the_same_action(
    app_conn: persistence.Conn,
    role_conn: RoleConn,
    incident_conn: persistence.Conn,
    secret: Callable[[str], str],
    monkeypatch: pytest.MonkeyPatch,
    lines: list[str],
) -> None:
    """T47 review note 3, ruling 21: the reply to the first create_incident is lost after commit (UNKNOWN; the run
    stays EXECUTING with the attempt SENT); a fresh handle for the same open execute job re-sends under the same action
    id and the destination's key answers with the one incident."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    _, run, proposal, execute = await approved_run(app_conn, api=api, worker=worker)
    token, own = await worker_token(secret), await write_token(secret)
    arguments = {"proposal_id": str(proposal)}
    try:
        async with write_stack(monkeypatch) as (sim, url):
            await arm(sim, own, "lose_after_commit")
            first = data(await call(url, token, execute, "create_incident", arguments), "outcome")
            action = UUID(first["action_id"])
            assert first["status"] == "UNKNOWN" and await run_state(app_conn, run) == ("EXECUTING", None)
            assert await attempt_states(app_conn, run) == ["INTENT", "SENT"]
            assert await at_destination(incident_conn, action) == (("COMMITTED", None), 1)
            calls = Calls(monkeypatch)
            fresh = await execute_handle(worker, run, fence=await fence_of(app_conn, run))
            second = data(await call(url, token, fresh, "create_incident", arguments), "ok")
        assert second["status"] == "SUCCEEDED" and UUID(second["action_id"]) == action
        assert calls.made == ["post_incident"]  # the same key re-sent once
        assert await at_destination(incident_conn, action) == (("COMMITTED", None), 1)  # no second incident
        cur = await app_conn.execute("SELECT count(*) AS n FROM app.execution_grant WHERE run_id = %s", (run,))
        assert (await cur.fetchone() or {})["n"] == 1
        assert await attempt_states(app_conn, run) == ["INTENT", "SENT", "RESOLVED"]
        lines.append("re-send (review note 3): lose_after_commit -> UNKNOWN; fresh execute handle -> same action_id")
    finally:
        await purge_run(app_conn, run)


async def test_a_foreign_receipt_hash_is_a_conflict_the_lookup_replays(
    app_conn: persistence.Conn,
    role_conn: RoleConn,
    secret: Callable[[str], str],
    monkeypatch: pytest.MonkeyPatch,
    lines: list[str],
) -> None:
    """Ruling 19: the destination answers the send with another payload hash; mcp-write records CONFLICT (the run
    ESCALATED), never success; a recover job's lookup then answers the stored CONFLICT without asking again, and its
    abort is refused (the attempt is resolved)."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    _, run, proposal, execute = await approved_run(app_conn, api=api, worker=worker)
    token, own = await worker_token(secret), await write_token(secret)
    arguments = {"proposal_id": str(proposal)}
    try:
        async with write_stack(monkeypatch) as (sim, url):
            await arm(sim, own, "receipt_hash_mismatch")
            sent = data(await call(url, token, execute, "create_incident", arguments), "outcome")
            assert sent["status"] == "CONFLICT" and await run_state(app_conn, run) == ("ESCALATED", "conflict")
            recover = await recover_handle(app_conn, worker, run, "timeout")
            calls = Calls(monkeypatch)
            looked = data(await call(url, token, recover, "get_incident_receipt", arguments), "outcome")
            assert_refused(await call(url, token, recover, "abort_incident", arguments))
        assert looked["status"] == "CONFLICT" and looked["action_id"] == sent["action_id"]
        assert calls.made == []  # the stored outcome; the destination is not asked again
        assert await attempt_states(app_conn, run) == ["INTENT", "SENT", "RESOLVED"]
        lines.append("receipt_hash_mismatch -> CONFLICT (ESCALATED); recover lookup replays it, no call; abort refused")
    finally:
        await purge_run(app_conn, run)


async def test_a_rate_limited_send_is_aborted_once_cancelled(
    app_conn: persistence.Conn,
    role_conn: RoleConn,
    incident_conn: persistence.Conn,
    secret: Callable[[str], str],
    monkeypatch: pytest.MonkeyPatch,
    lines: list[str],
) -> None:
    """Rulings 3 and 19, SA:242 and SA:248: the send meets a rate limit (UNKNOWN; nothing at the destination); the
    lookup finds no key (UNKNOWN); an abort before a cancel or the deadline is refused ABORT_NOT_DUE; after a cancel
    the abort goes at once (`deadline`) and the fresh tombstone ends the run FAILED with `aborted_no_commit`. The
    recovery calls create no grant, attempt, job or proposal, and the destination gains exactly one key: the abort's
    tombstone (round 1, M5)."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    _, run, proposal, execute = await approved_run(app_conn, api=api, worker=worker)
    token, own = await worker_token(secret), await write_token(secret)
    arguments = {"proposal_id": str(proposal)}
    try:
        async with write_stack(monkeypatch) as (sim, url):
            await arm(sim, own, "rate_limit")
            sent = data(await call(url, token, execute, "create_incident", arguments), "outcome")
            action = UUID(sent["action_id"])
            assert sent["status"] == "UNKNOWN" and await at_destination(incident_conn, action) == (None, 0)
            recover = await recover_handle(app_conn, worker, run, "timeout")
            cur = await app_conn.execute(COUNTS)
            before, keys = dict(await cur.fetchone() or {}), await keys_total(incident_conn)
            looked = data(await call(url, token, recover, "get_incident_receipt", arguments), "outcome")
            assert looked["status"] == "UNKNOWN"  # 404: no key, which is never a no-commit (SA:269)
            early = error(await call(url, token, recover, "abort_incident", arguments))
            assert early["code"] == "ABORT_NOT_DUE" and early["retryable"] is True
            assert await attempt_states(app_conn, run) == ["INTENT", "SENT"]
            await cancel(api, run)
            aborted = data(await call(url, token, recover, "abort_incident", arguments), "outcome")
            cur = await app_conn.execute(COUNTS)
            after = dict(await cur.fetchone() or {})
        assert after == before and await keys_total(incident_conn) == keys + 1  # the tombstone, nothing else
        assert aborted["outcome"] == "FAILED_NO_COMMIT" and aborted["receipt"] is None
        assert aborted["tombstone"]["state"] == "ABORTED" and aborted["tombstone"]["reason"] == "deadline"
        assert await run_state(app_conn, run) == ("FAILED", "aborted_no_commit")
        assert await attempt_states(app_conn, run) == ["INTENT", "SENT", "ABORT_REQUESTED", "RESOLVED"]
        assert await at_destination(incident_conn, action) == (("ABORTED", "deadline"), 0)
        lines.append(
            "rate_limit -> UNKNOWN; lookup 404 -> UNKNOWN; abort not due refused; cancel -> abort 'deadline' ->"
            " FAILED aborted_no_commit"
        )
    finally:
        await purge_run(app_conn, run)


async def test_a_cancel_before_send_ends_in_the_destinations_tombstone(
    app_conn: persistence.Conn,
    role_conn: RoleConn,
    incident_conn: persistence.Conn,
    secret: Callable[[str], str],
    monkeypatch: pytest.MonkeyPatch,
    lines: list[str],
) -> None:
    """Ruling 24, SA:348: the grant committed (INTENT), then a cancel; create_incident's mark_sent answers `cancelled`,
    and the tool itself requests the abort, POSTs it and records the tombstone: FAILED, `cancelled_before_send`;
    nothing is ever POSTed to /internal/incidents."""
    api, worker, mcp_exec = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.MCP_EXEC)
    _, run, proposal, execute = await approved_run(app_conn, api=api, worker=worker)
    token = await worker_token(secret)
    try:
        grant = await persistence.grant_execution(mcp_exec, handle=execute, azp=AZP, proposal_id=proposal)
        await cancel(api, run)
        async with write_stack(monkeypatch) as (_, url):
            calls = Calls(monkeypatch)
            ended = data(await call(url, token, execute, "create_incident", {"proposal_id": str(proposal)}), "outcome")
        assert ended["status"] == "FAILED_NO_COMMIT" and ended["reason"] == "cancelled_before_send"
        assert UUID(ended["action_id"]) == grant.action_id and ended["tombstone"]["reason"] == "cancelled_before_send"
        assert calls.made == ["post_abort"]
        assert await run_state(app_conn, run) == ("FAILED", "cancelled_before_send")
        assert await attempt_states(app_conn, run) == ["INTENT", "ABORT_REQUESTED", "RESOLVED"]
        assert await at_destination(incident_conn, grant.action_id) == (("ABORTED", "cancelled_before_send"), 0)
        lines.append("cancel before send: create_incident -> abort -> FAILED_NO_COMMIT cancelled_before_send; no POST")
    finally:
        await purge_run(app_conn, run)


async def test_a_send_past_the_dispatch_deadline_ends_expired(
    app_conn: persistence.Conn,
    role_conn: RoleConn,
    incident_conn: persistence.Conn,
    secret: Callable[[str], str],
    monkeypatch: pytest.MonkeyPatch,
    lines: list[str],
) -> None:
    """Rulings 17 and 24: the grant at t0, the test clock 400 s on (past the 300 s deadline; reset in `finally`); a
    fresh handle under a fresh lease; create_incident aborts instead of sending: FAILED, `expired`."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    mcp_exec, harness = await role_conn(Role.MCP_EXEC), await role_conn(Role.TEST_HARNESS)
    _, run, proposal, execute = await approved_run(app_conn, api=api, worker=worker)
    token = await worker_token(secret)
    try:
        grant = await persistence.grant_execution(mcp_exec, handle=execute, azp=AZP, proposal_id=proposal)
        try:
            await harness.execute(LATE)
            fresh = await execute_handle(worker, run)  # the first lease lapsed with the clock
            async with write_stack(monkeypatch) as (_, url):
                calls = Calls(monkeypatch)
                ended = data(
                    await call(url, token, fresh, "create_incident", {"proposal_id": str(proposal)}), "outcome"
                )
        finally:
            await harness.execute(NOW)
        assert ended["status"] == "FAILED_NO_COMMIT" and ended["reason"] == "expired"
        assert UUID(ended["action_id"]) == grant.action_id and calls.made == ["post_abort"]
        assert await run_state(app_conn, run) == ("FAILED", "expired")
        assert await attempt_states(app_conn, run) == ["INTENT", "ABORT_REQUESTED", "RESOLVED"]
        assert await at_destination(incident_conn, grant.action_id) == (("ABORTED", "expired"), 0)
        lines.append("past the dispatch deadline: create_incident -> abort -> FAILED_NO_COMMIT expired; no POST")
    finally:
        await purge_run(app_conn, run)


async def test_a_redispatch_outside_executing_sends_nothing(
    app_conn: persistence.Conn,
    role_conn: RoleConn,
    incident_conn: persistence.Conn,
    secret: Callable[[str], str],
    monkeypatch: pytest.MonkeyPatch,
    lines: list[str],
) -> None:
    """Rulings 6 and 20: the grant committed (INTENT), then the worker's mark_unknown (OUTCOME_UNKNOWN, the fence
    bumped, a recover job queued). The recover job's create_incident passes the allowlist (INTENT) and is refused by
    mark_sent's EXECUTING guard: the plain STALE_RUN, nothing sent (redispatch from OUTCOME_UNKNOWN is T22's). Its abort
    is not due until a cancel, then ends the run FAILED with `cancelled_before_send`."""
    api, worker, mcp_exec = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.MCP_EXEC)
    _, run, proposal, execute = await approved_run(app_conn, api=api, worker=worker)
    token = await worker_token(secret)
    arguments = {"proposal_id": str(proposal)}
    try:
        grant = await persistence.grant_execution(mcp_exec, handle=execute, azp=AZP, proposal_id=proposal)
        unknown = await persistence.mark_unknown(worker, run, await fence_of(app_conn, run))
        assert unknown.state.value == "OUTCOME_UNKNOWN"
        cur = await app_conn.execute("SELECT id FROM app.jobs WHERE run_id = %s AND type = 'recover'", (run,))
        job = UUID(str((await cur.fetchone() or {})["id"]))  # mark_unknown's own recover job (<action>:timeout)
        async with worker.transaction():
            recover = await persistence.mint_handle(
                worker, run_id=run, job_id=job, server=Server.WRITE, azp=AZP, fence=unknown.fence
            )
        async with write_stack(monkeypatch) as (_, url):
            calls = Calls(monkeypatch)
            stale = error(await call(url, token, recover, "create_incident", arguments))
            early = error(await call(url, token, recover, "abort_incident", arguments))
            await cancel(api, run)
            aborted = data(await call(url, token, recover, "abort_incident", arguments), "outcome")
        assert stale["code"] == "STALE_RUN" and early["code"] == "ABORT_NOT_DUE"
        assert aborted["outcome"] == "FAILED_NO_COMMIT" and aborted["tombstone"]["reason"] == "cancelled_before_send"
        assert calls.made == ["post_abort"]  # nothing was ever sent to /internal/incidents
        assert await run_state(app_conn, run) == ("FAILED", "cancelled_before_send")
        assert await attempt_states(app_conn, run) == ["INTENT", "ABORT_REQUESTED", "RESOLVED"]
        assert await at_destination(incident_conn, grant.action_id) == (("ABORTED", "cancelled_before_send"), 0)
        lines.append(
            "recover create_incident on INTENT in OUTCOME_UNKNOWN -> STALE_RUN, nothing sent; abort not due, then"
            " cancel -> FAILED_NO_COMMIT cancelled_before_send"
        )
    finally:
        await purge_run(app_conn, run)
```

- [x] **Step 3: Run it**

Run (dev stack up, no skeleton process running):

```bash
OPS_LIVE=1 PROFILE=test PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_mcp_write_t47_live.py -q
```

Expected: `10 passed`, and `reports/mcp-write/t47-mcp-write.txt` holds a header and ten lines. This count is
arithmetic, not measured. A failure is a finding against Tasks 1-3, not a reason to weaken an assertion: stop and
report.

- [x] **Step 4: Gates and commit**

Format, lint and count characters on the two files of this task.

Run: `PYTHONUTF8=1 uv run python scripts/check.py`
Expected: `CHECK: GREEN`; pytest `1152 passed, 179 skipped` (the 10 new live tests skip).

Run: `PYTHONUTF8=1 uv run python scripts/check.py --profile test`
Expected: `CHECK: GREEN`; pytest `1310 passed, 21 skipped` (arithmetic, not measured: the dev count plus the 158
live-gated tests). Then `git checkout -- reports/bootstrap reports/skeleton reports/auth reports/admission
reports/leases reports/events reports/outbox reports/mcp-read` (`reports/mcp-write` stays untracked until Task 6).

Run: `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`
Expected: exit 0.

```bash
git add tests/e2e/test_mcp_write_t47_live.py tests/plan_b/test_evidence.py
git commit -m "test(mcp-write): live evidence for R030, R131's write half, the re-send, the faults and the aborts (T47)"
```

---

### Task 5: The independent process and the threat model

**Files:**
- Create: `tests/e2e/test_mcp_write_process_live.py`, `docs/threat-model.md`

**Requirements:** R025's write half ("An independent process lists and calls tools on … mcp-write over the network"),
R031's network half at mcp-write (the locked SDK versions), ruling 16; T47 review note 2 and ruling 22 (the
outcome-truth statement).

**Interfaces:**
- Consumes: Task 4's `COUNTS`, `WRITE_TOOLS`, `arm`, `at_destination`, `recover_handle`, `started`, `write_token`;
  Task 2's `AZP`; `scripts.skeleton.healthy`, `process_environment`; Plan J's `free_port`, `worker_token`;
  `execution.Deps`, `execution.create_incident`.
- Produces: `reports/mcp-write/t47-independent-client.txt`; `docs/threat-model.md`.

- [x] **Step 1: Write the independent-process test**

Create `tests/e2e/test_mcp_write_process_live.py`:

```python
"""mcp-write as an independent process, reached over the network by the official SDK client (OPS_LIVE=1; R025 write
half, R031 network half at mcp-write; Plan K ruling 16).

`python -m ops_mcp_write` runs as a child process on a free loopback port with the environment the skeleton gives its
children (`scripts.skeleton.process_environment`: this session's test profile and databases, secrets as files named by
`OPS_SECRETS_DIR`, nothing secret on the command line), pointed at an in-process incident-sim, and is terminated in
`finally`. The action it is asked about is made first, in-process, with the reply lost after commit, so the child's
`get_incident_receipt` has a real lookup to do and no new action to create. Catches: a server that only works
in-process (BUILD_SPEC §10), a tool list other than the three write tools or one that advertises extra arguments, a
locked SDK version other than AM-30's, a lookup through the network that creates a grant, an attempt, a job or an
incident, and a handle or a token in the child's own log (written through its redaction filter at uvicorn's "warning"
level, so a weaker check than the in-process ones).
"""

import asyncio
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from ops_core import persistence, settings
from ops_core.mcp_protocol import PROTOCOL_VERSION
from ops_core.outcomes import ToolOutcome
from ops_core.settings import Role
from ops_core.tokens import WorkloadTokenSource
from ops_incident_sim.app import production_app as incident_sim_app
from ops_mcp_write import execution

from scripts.skeleton import healthy, process_environment
from tests.e2e.conftest import purge_run
from tests.e2e.test_mcp_read_t15_live import free_port, worker_token
from tests.e2e.test_mcp_write_live import approved_run
from tests.e2e.test_mcp_write_t47_live import (
    COUNTS,
    WRITE_TOOLS,
    arm,
    at_destination,
    recover_handle,
    started,
    write_token,
)
from tests.e2e.test_migration_0010_live import AZP

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = Path("reports/mcp-write/t47-independent-client.txt")
EXPECTED_LINES = 1  # one per test below


@pytest.fixture(scope="module")
def lines() -> Iterator[list[str]]:
    out = [f"T47 independent client — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"]
    yield out
    if len(out) != 1 + EXPECTED_LINES:  # a failed or partial run leaves the committed file as it was
        return
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


@asynccontextmanager
async def mcp_write_process(log: Path, sim: str) -> AsyncIterator[str]:
    """The server as a child process; its URL once `/health/ready` answers 200 (keys loaded, database reachable,
    revisions 0009 and 0010 present). Terminated in `finally`, killed if it outlives 15 s; its output goes to `log`."""
    port = free_port()
    env = process_environment()  # .env-derived settings over this session's environment: PROFILE=test, ops_test
    env["OPS_MCP_WRITE_PORT"] = str(port)
    env["OPS_INCIDENT_SIM_URL"] = sim
    with log.open("ab") as out:
        # Off the loop (ruff ASYNC220): asyncio's own subprocesses need the Proactor loop, which psycopg refuses.
        child = await asyncio.to_thread(
            subprocess.Popen,
            [sys.executable, "-m", "ops_mcp_write"],
            env=env,
            stdout=out,
            stderr=subprocess.STDOUT,
            cwd=ROOT,
        )
        try:
            deadline = time.monotonic() + 60
            while not await asyncio.to_thread(healthy, f"http://127.0.0.1:{port}/health/ready"):
                # The log's path, never its content: the child's log may hold what the leak check looks for.
                assert child.poll() is None, f"mcp-write exited before it was ready; its log is {log}"
                assert time.monotonic() < deadline, f"mcp-write was not ready within 60 s; its log is {log}"
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


async def test_r025_an_independent_client_lists_the_write_tools_and_looks_up_a_receipt(
    app_conn: persistence.Conn,
    role_conn: RoleConn,
    incident_conn: persistence.Conn,
    secret: Callable[[str], str],
    tmp_path: Path,
    lines: list[str],
) -> None:
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    _, run, proposal, handle = await approved_run(app_conn, api=api, worker=worker)
    token, own = await worker_token(secret), await write_token(secret)
    log = tmp_path / "mcp-write.log"
    try:
        async with started(incident_sim_app(), "incident-sim") as sim:
            await arm(sim, own, "lose_after_commit")  # the action commits and its reply is lost: the attempt stays SENT
            kc = settings.keycloak()
            source = WorkloadTokenSource(
                token_url=kc.token_url,
                client_id="ops-mcp-write",
                client_secret=secret("kc_client_secret_ops_mcp_write"),
            )
            async with httpx2.AsyncClient() as http:
                deps = execution.Deps(
                    persistence.Session(await role_conn(Role.MCP_EXEC)), http, sim, destination_token=source
                )
                first = await execution.create_incident(deps, handle=handle, azp=AZP, proposal_id=proposal)
            assert first.status is ToolOutcome.UNKNOWN
            async with mcp_write_process(log, sim) as url:
                # Minted once the child is ready: the handle lives 60 s, the child may take longer to start.
                recover = await recover_handle(app_conn, worker, run, "timeout")
                cur = await app_conn.execute(COUNTS)
                before = dict(await cur.fetchone() or {})
                headers = {"Authorization": f"Bearer {token}", "X-Ops-Invocation": recover}
                async with (
                    httpx2.AsyncClient(headers=headers) as http,
                    Client(streamable_http_client(url, http_client=http), mode=PROTOCOL_VERSION) as client,
                ):
                    tools = (await client.list_tools()).tools
                    result = await client.call_tool("get_incident_receipt", {"proposal_id": str(proposal)})
            cur = await app_conn.execute(COUNTS)
            after = dict(await cur.fetchone() or {})
        assert sorted(tool.name for tool in tools) == sorted(WRITE_TOOLS)
        assert all(tool.input_schema["additionalProperties"] is False for tool in tools)
        doc = result.structured_content
        assert not result.is_error and isinstance(doc, dict) and doc["status"] == "ok"
        assert doc["data"]["status"] == "SUCCEEDED" and doc["data"]["action_id"] == str(first.action_id)
        assert after == before  # no grant, attempt, job or proposal created by the lookup
        assert await at_destination(incident_conn, first.action_id) == (("COMMITTED", None), 1)
        text = log.read_text(encoding="utf-8", errors="replace")
        leaked = any(value in text for value in (handle, recover, token, own))  # one boolean, never a value
        assert not leaked  # the child's own log, written through its redaction filter, holds none of them
        assert (version("mcp"), version("mcp-types")) == ("2.3.0", "2.3.0")  # AM-30's lock, R031
        names = ", ".join(sorted(tool.name for tool in tools))
        lines.append(
            f"R025 (write half) / R031 (network half, mcp-write): child process; official client mode"
            f" {PROTOCOL_VERSION} listed [{names}]; get_incident_receipt with a recover handle answered SUCCEEDED for"
            " the existing action; no grant, attempt, job or incident created"
        )
    finally:
        await purge_run(app_conn, run)
```

- [x] **Step 2: Run it**

Run (dev stack up, no skeleton process running):

```bash
OPS_LIVE=1 PROFILE=test PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_mcp_write_process_live.py -q
```

Expected: `1 passed`, and `reports/mcp-write/t47-independent-client.txt` holds a header and one line. This count is
arithmetic, not measured.

- [x] **Step 3: The threat model**

Create `docs/threat-model.md`:

```markdown
# Threat model: the write path

Who this is for: anyone deciding whether an incident the system reports really exists, reviewing a change to the write
path, or answering "what if this service were compromised?". It covers v1's write path only: the worker, mcp-write,
the definer functions in the application database, and the synthetic destination incident-sim. The design is AM-13,
AM-15 and AM-20 in `SPEC_AMENDMENTS.md` and BUILD_SPEC §13 and §14; T47 (Plan K) added this file.

## The outcome-truth statement

**v1 trusts mcp-write for outcome truth.** mcp-write is the only service that calls incident-sim and the only role
(`mcp_exec`) that may record an outcome (`app.record_outcome`). `record_outcome` checks the receipt's action id and
payload hash against the grant, but the receipt reaches it through mcp-write, so a compromised mcp-write could record
an outcome the destination never gave: a SUCCEEDED for an action that did not commit, or a FAILED for one that did.
Nothing inside the application database can tell such a record from a true one.

The control is detective, not preventive: `uv run python scripts/skeleton.py keys` (T10) reads every destination key
and every grant and lists each key whose `(action_id, payload_sha256)` no grant carries, exiting 1 if there is one. It
finds an incident created outside a grant. It does not compare recorded outcomes with the keys, and nothing runs it on
a schedule yet (T32).

Optional hardening for v1.1, not built: incident-sim signs each receipt and tombstone with an HMAC key held in a
table only `app_definer` can read, and `record_outcome` verifies the signature, so mcp-write could relay a receipt but
not forge one.

## Who is trusted for what

| Party | Trusted for | Not trusted for | What holds it to that |
|---|---|---|---|
| Worker | driving jobs; minting a handle for its own job under its live lease | contacting the destination; recording an outcome; choosing a tool | it holds no write-path function and no route to incident-sim; the server derives the allowed tools from the job type, run state and attempt state |
| mcp-write | outcome truth (above); the grant gate's result | anything without a live handle of an execute or recover job | `mcp_exec` executes seven functions and reads no table; every function resolves the handle again |
| mcp-read | read tools for investigate and resume_input jobs | the write path | `mcp_read` executes `current_time` and `resolve_invocation` only; a write handle is refused there |
| incident-sim | whether an incident exists (its permanent keys) | who may write | it accepts only mcp-write's token (`aud` incident-sim, `azp` ops-mcp-write) |
| The model | nothing on this path | tools, handles, outcomes | it never sees a handle or a write tool |

## Threats and the controls that answer them

| Threat | Control | Evidence |
|---|---|---|
| An incident without an approved proposal | the POST happens only after `grant_execution` committed a grant for an approved, unexpired, hash-matching proposal; an abort never creates an incident | `tests/e2e/test_definers_write_path_live.py`, `tests/e2e/test_mcp_write_t47_live.py` |
| A second incident for one approval | one grant per run, a random action id, and the destination's `INSERT … ON CONFLICT DO NOTHING` key; a re-send uses the same key | `tests/e2e/test_mcp_write_t47_live.py` (the re-send), `tests/e2e/test_incident_sim_live.py` |
| A lost reply read as "nothing happened" | every unanswered call is UNKNOWN; only a destination tombstone proves no commit; a 404 lookup is never a no-commit | `tests/plan_k/test_recovery_tools.py` |
| A send after a cancel or past the dispatch deadline | `mark_sent` re-checks both under the runs lock for a first send and for a re-send of a SENT attempt alike, and answers `cancelled` or `expired`; the tool then aborts instead of sending. A cancel that lands between `mark_sent`'s commit and the POST is AM-13's own window, the same for both | `tests/e2e/test_migration_0010_live.py`, `tests/e2e/test_mcp_write_t47_live.py`, `tests/plan_k/test_recovery_tools.py` |
| A stolen or replayed handle | only its hash is stored; it lives 60 s, for one job of one run, at one lease fence, for one server and one `azp`, and is never logged | `tests/e2e/test_mcp_read_t15_live.py`, `tests/e2e/test_migration_0010_live.py` |
| Receipt lookup used to probe or to act | the recovery tools answer recover handles only and create no grant, attempt, job or key | `tests/e2e/test_mcp_write_t47_live.py` (R030) |
| A foreign token at a server | each server's verifier checks issuer, audience, `azp` and the access token's `typ`; incident-sim answers mcp-read's token 403 | `tests/plan_k/test_verifier_t47.py`, `tests/e2e/test_mcp_write_t47_live.py` |

## Not covered here

Network isolation between the containers (mcp-read cannot reach incident-sim at all) is T30's; until then the token
checks above are the only barrier. The worker's recovery loop (backoff, scheduled recover jobs, escalation) is T22's.
```

- [x] **Step 4: Gates and commit**

Format, lint and count characters on the test module.

Run: `PYTHONUTF8=1 uv run python scripts/check.py`
Expected: `CHECK: GREEN`; pytest `1152 passed, 180 skipped`.

Run: `PYTHONUTF8=1 uv run python scripts/check.py --profile test`
Expected: `CHECK: GREEN`; pytest `1311 passed, 21 skipped` (arithmetic, not measured: the dev count plus the 159
live-gated tests). Then `git checkout -- reports/bootstrap reports/skeleton reports/auth reports/admission
reports/leases reports/events reports/outbox reports/mcp-read`.

Run: `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`
Expected: exit 0.

```bash
git add tests/e2e/test_mcp_write_process_live.py docs/threat-model.md
git commit -m "test(mcp-write): an independent process and the official client; docs: the write path's threat model (T47)"
```

---

### Task 6: Close-out — records, acceptance rows, errata 82-92, the runbook, final gates

**Files:**
- Create: `docs/runbooks/mcp-write.md`
- Modify: `tests/plan_j/test_worker_azp.py:4-9` (docstring), `tests/plan_c/test_schema_conformance.py:45` (a skip
  reason), `handoff/tasks.json` (T47 → `DONE`, one review note), `handoff/acceptance-matrix.json` (R025, R030, R031,
  R131), `handoff/BUILD_BACKLOG.md` (T47 checked, one review note), `SESSION_STATE.md` (the "Next task" lines, the
  repository line, a "Plan K executed" section, the dev database state, the owner inputs, the exact next step),
  `STATUS.md` (an update section), `docs/ARCHITECTURE.md` (a new section 8), `docs/PROJECT_HISTORY.md` (section 28; the
  last section becomes 29), `docs/runbooks/mcp-read.md`, `README.md:5`, `mcp-write/README.md`, `mcp-read/README.md`,
  `worker/README.md`, this plan (its checkboxes); the evidence files under `reports/mcp-write/` and those the final
  live run rewrites

**Requirements:** the T47 record (R030 and R131 evidenced; R025 and R031 write halves recorded); every deferral to T47
in live code resolved or re-homed. This task writes no behaviour.

Throughout, `<base>..<last>` is the git range of this plan's execution on `plan-k`, written as two short hashes:
`<base>` is the `BASE` recorded in Task 1 Step 1b (excluded by the range) and `<last>` the newest commit before this
task's own (`LAST=$(git rev-parse --short HEAD)`, run before this task commits). `<date>` is `date -u +%F` on the day
of the close-out. Step 5 replaces every one of them.

- [x] **Step 1: No deferral to T47 is left in live code**

Edit 1 (`tests/plan_j/test_worker_azp.py`, the module header), replace:

```python
other three still name `"ops-worker"`: `main.py`'s token source, `read_verifier`'s `allowed_azp` and the write-path
definers' literal (T47 debt, Plan J final review).
```

with:

```python
other three follow `settings.workload_client_id()` since T47 (the token source and both verifiers,
tests/plan_k/test_workload_client.py) or compare the presented token's `azp` (the write-path definers, revision 0010).
```

Edit 2 (`tests/plan_c/test_schema_conformance.py`, in `NO_MODEL`), replace:

```python
        "envelopes are built by the MCP servers (T16/T47); the data shapes are ActionOutcome"
```

with:

```python
        "envelopes are built by the MCP servers (mcp-write's in tests/plan_k, T47; the read tools' with T16)"
```

The two deferral greps run at the end of Step 4, once `mcp-write/README.md` (Edit 8 there) is rewritten too.

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
    f"Plan K (branch plan-k): done in {span} (the debt list, then the five tasks; the close-out is the next commit; "
    "plan docs/superpowers/plans/2026-10-16-first-slice-k-mcp-write-recovery-tools.md). Shipped: mcp-write's "
    "verifier at mcp-read's level (write_verifier: the typ claim Bearer, an aud without the server's URL refused "
    "before the resource stamp, validate_token_resource on); the worker's client named once in settings "
    "(OPS_WORKLOAD_CLIENT_ID, default ops-worker), read by the worker's token source and both verifiers; revision "
    "0010_write_path: grant_execution, lookup_action, mark_sent and record_outcome take the presented token's azp, "
    "mark_sent answers expired past the dispatch deadline (app._dispatch_seconds(), 300 s, after the runs lock; a "
    "cancel comes first) and abort_requested once an abort was requested, record_outcome accepts a receipt or a "
    "conflict after an abort requested after SENT (reason deadline), and request_abort chooses the reason itself "
    "(cancelled_before_send, expired or deadline) and records ABORT_REQUESTED, or refuses ABORT_NOT_DUE; exact "
    "downgrade to 0009; mcp-write refuses to "
    "start without it. The attempt-state allowlist is persistence.allowed_tool's third dimension (jobs.ATTEMPT_STATES; "
    "an execute job re-sends a SENT attempt while mark_sent finds it still due, a recover job redispatches INTENT "
    "only and never re-sends). get_incident_receipt (one GET, "
    "never a POST; creates nothing) and abort_incident (request_abort, one abort POST) record what the destination "
    "answers; a 404, 429, 503 or no answer is UNKNOWN and unrecorded; create_incident aborts a cancelled or expired "
    "attempt itself (FAILED with cancelled_before_send or expired). mcp_exec executes exactly current_time, "
    "resolve_invocation, grant_execution, mark_sent, record_outcome, request_abort and lookup_action. Evidence: "
    "tests/e2e/test_migration_0010_live.py, test_mcp_write_t47_live.py, test_mcp_write_process_live.py and "
    "reports/mcp-write/ (live), tests/plan_k/ for the unit half; docs/threat-model.md states that v1 trusts mcp-write "
    "for outcome truth, with T10's detective check (scripts/skeleton.py keys) as the control and signed receipts as "
    "a v1.1 option. Deferred: the worker's recover handler, the lookup backoff, scheduled recover jobs, redispatch "
    "from OUTCOME_UNKNOWN, escalation and late evidence after RESOLVED -> T22; the deadline as a setting -> T29; "
    "the network half of DoD 3 and per-service tests -> T30. Errata 82-92 are proposed in SESSION_STATE.md; "
    "R030 and R131 are met subject to the owner's decisions on errata 72, 84 and 91."
)
tasks_path = Path("handoff/tasks.json")
tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
t47 = next(t for t in tasks["tasks"] if t["id"] == "T47")
assert t47["status"] == "PLANNED"
t47["status"] = "DONE"
t47["review_notes"].append(note)
tasks_path.write_text(json.dumps(tasks, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

matrix_path = Path("handoff/acceptance-matrix.json")
matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
READ_HALF_R131 = (
    "Read half (Plan J, T15): mcp_read can EXECUTE current_time (erratum 15) and resolve_invocation and nothing else in "
    "app (asset_scope and search_procedures_scoped join with T16/T17, erratum 72); an attempted grant_execution is "
    "42501; a recover and an execute handle presented to mcp-read are refused over HTTP."
)
rows = {
    "R030": (
        "IMPLEMENTED_LOCALLY_VERIFIED",
        [
            "tests/e2e/test_mcp_write_t47_live.py",
            "reports/mcp-write/t47-mcp-write.txt",
            "tests/plan_k/test_attempt_allowlist.py",
            "tests/plan_k/test_recovery_tools.py",
            "tests/plan_k/test_write_tools_server.py",
        ],
        "Plan K (T47): get_incident_receipt answers only a recover job's handle whose attempt is SENT, "
        "ABORT_REQUESTED or RESOLVED (persistence.allowed_tool with jobs.ATTEMPT_STATES, every combination tabled in "
        "a unit test). Over HTTP an execute handle, an investigate handle and a recover handle of an APPROVED run (no "
        "grant; refused by the run-state rule, since a run in a recover state without a grant cannot arise through "
        "the definers) are refused at both recovery tools with the plain INVALID_HANDLE envelope and no action id; a "
        "recover "
        "handle's lookup is one GET (a delayed receipt's 404 is UNKNOWN and recorded by nobody), then the minimal "
        "ActionOutcome (status, action_id, payload_sha256, receipt, tombstone, reason), recorded; the execution_grant, "
        "action_attempt, jobs and proposals counts do not move and nothing is POSTed; around an abort they do not "
        "move either, and the destination gains only the tombstone. The model holds no tool "
        "(BS:395), and only the worker's workload can authenticate at mcp-write (erratum 90).",
    ),
    "R131": (
        "IMPLEMENTED_LOCALLY_VERIFIED",
        [
            "tests/e2e/test_mcp_read_t15_live.py",
            "reports/mcp-read/t15-mcp-read.txt",
            "tests/e2e/test_mcp_write_t47_live.py",
            "reports/mcp-write/t47-mcp-write.txt",
            "tests/plan_k/test_migration_0010.py",
        ],
        f"{READ_HALF_R131} Write half (Plan K, T47): mcp_exec can EXECUTE exactly current_time (erratum 15), "
        "resolve_invocation, grant_execution, mark_sent, record_outcome, request_abort and lookup_action and nothing "
        "else in app (no read function exists yet to refuse, erratum 91); an attempted mark_unknown is 42501; an "
        "investigate and a resume_input handle are refused over HTTP at all three write tools, also when the stored "
        "server column lies, each live at mcp_read; incident-sim answers ops-mcp-read's workload token 403 at all "
        "three routes. That mcp-read cannot reach incident-sim over the network is T30's Docker network test.",
    ),
}
notes = {
    "R025": (
        [
            "tests/e2e/test_mcp_read_process_live.py",
            "reports/mcp-read/t15-independent-client.txt",
            "tests/plan_j/test_mcp_read_http.py",
            "tests/e2e/test_mcp_write_process_live.py",
            "reports/mcp-write/t47-independent-client.txt",
        ],
        "Read half (Plan J, T15): python -m ops_mcp_read runs as a child process on a loopback port and the official "
        "SDK Client (mode 2026-07-28) in the test process lists exactly search_procedures and calls it with a valid "
        "handle over the network. Write half (Plan K, T47): python -m ops_mcp_write runs as a child process pointed at "
        "incident-sim, lists exactly the three write tools to the official client and answers get_incident_receipt "
        "with a recover handle for an existing action (SUCCEEDED; no grant, attempt, job or incident created). Both "
        "halves are evidenced; the row's status is left to its owner, T15.",
    ),
    "R031": (
        [
            "tests/e2e/test_mcp_read_process_live.py",
            "reports/mcp-read/t15-independent-client.txt",
            "tests/e2e/test_mcp_write_process_live.py",
            "reports/mcp-write/t47-independent-client.txt",
        ],
        "Network half (Plan J, T15; Plan K, T47): the locked mcp 2.3.0 and mcp-types 2.3.0 are asserted in live tests "
        "whose official client crosses the network to an independent mcp-read and an independent mcp-write; T04's "
        "import half is the workspace import test.",
    ),
}
for row in matrix["requirements"]:
    if row["id"] in rows:
        row["implementation_status"], row["evidence_paths"], row["note"] = rows[row["id"]]
        row["evidence_status"] = "RECORDED_LOCALLY_LIVE"
    elif row["id"] in notes:  # T47 does not own these rows: their notes and evidence record its half
        row["evidence_paths"], row["note"] = notes[row["id"]]
matrix_path.write_text(json.dumps(matrix, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

backlog_path = Path("handoff/BUILD_BACKLOG.md")
backlog = backlog_path.read_text(encoding="utf-8")
head = "- [ ] **T47 Authenticated MCP write server (mcp-write) and recovery tools**"
assert backlog.count(head) == 1
backlog = backlog.replace(head, head.replace("- [ ]", "- [x]", 1))
lines = backlog.split("\n")
at = next(i for i, line in enumerate(lines) if line.startswith("- [x] **T47 "))
end = at + 1
while end < len(lines) and lines[end].startswith("  - "):
    end += 1
lines.insert(end, f"  - *Review note:* {note}")  # after the task's other notes, as tasks.json appends it
backlog_path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
print(span)
EOF
```

Expected: it prints the span (for example `1a2b3c4..5d6e7f8`). `git diff --stat handoff` shows three files changed;
`git diff handoff/acceptance-matrix.json` shows four rows: R025, R030, R031 and R131.

- [x] **Step 3: Project state**

Edit 1 (`SESSION_STATE.md`, under "Session state"), replace:

```markdown
**Next task:** Plan J (T15) is executed on branch `plan-j` (on top of `plan-i`: `00c76e4..f0c8ca8` holds the debt list and
the four tasks, the close-out is `8424ed7`, and the final-review fix wave follows it). T15 is DONE subject to the
owner's decisions on errata 72 and 76 (R131's three-function set and the attempt-state allowlist are met only through
them). Owner inputs: (1) the holdout seal (T03 step 9), then the live probe (T02); (2) merge the stacked PRs #1-#8 in
order (plan-b -> main through plan-i -> plan-h, all open); the plan-j -> plan-i PR is opened after the Plan J
final-review fix wave; (3) T44 step 10 (`docs/runbooks/ollama-network.md` step A); (4) decide the proposed errata of
Plans C, E, F, G, H, I and J (J: 72-81 below); (5) migrate the dev database to revision 0009 (`uv run python
scripts/skeleton.py migrate`, dev profile: from 0005 it applies 0006, 0007, 0008 and 0009 together; 0009 re-creates
`_resolve_handle` with the handle's job binding and changes no row; mcp-read and mcp-write now also refuse to start
without it). Next is Plan K = T47
(mcp-write, the earliest dependency-satisfied PLANNED task in `handoff/tasks.json` after T15, unblocked by T15 and T10;
T17 is also unblocked).
**Plan A outcome:** executed on branch `plan-a` (a638801..HEAD); `scripts/check.py` GREEN (54 passed, 1 skipped: owner seal). Final whole-branch review: 5 Important findings fixed in the final-review wave; minors deferred: M3 timing restructure (`astream`), M6 mypy member list.
**Repository:** local git repo at `C:\Users\joeys\Desktop\MLOps`, branch `plan-j` (Plan J work on top of `plan-i`, on top of `plan-h`, on top of `plan-g`, on top of `plan-f`, on top of `plan-e`, on top of `plan-d`, on top of `plan-c`, on top of `plan-b`, on top of `plan-a`). Remote `github.com/jschnepel/MLOps` (public, MIT) exists; `main` and `plan-a` were pushed on 2026-10-07. `plan-b` to `plan-e` were pushed on 2026-10-08 and `plan-f` on 2026-10-09; `plan-g`, `plan-h` and `plan-i` are pushed too, and every pushed branch matches its local one (checked 2026-10-15). PRs #1-#5 were opened on 2026-10-09 and are green after the EXE001 fix (first green run https://github.com/jschnepel/MLOps/actions/runs/37962510516; record `reports/ci/t06-first-ci-runs.txt`); PRs #1-#8 (plan-b -> main through plan-i -> plan-h) are open now. The plan-j -> plan-i PR is opened after the Plan J final-review fix wave. Merging them in order is the owner's call.
```

with:

```markdown
**Next task:** Plan K (T47) is executed on branch `plan-k` (on top of `plan-j`: `<base>..<last>` holds the debt list and
the five tasks, and the close-out is the commit after `<last>`). T47 is DONE subject to the owner's decisions on errata
72, 84 and 91 (R131's function sets and the attempt-state allowlist). Owner inputs: (1) the holdout seal (T03 step 9),
then the live probe (T02); (2) merge the stacked PRs #1-#8 in order (plan-b -> main through plan-i -> plan-h), then
the plan-j -> plan-i PR and, after Plan K's final review, a plan-k -> plan-j PR; (3) T44 step 10
(`docs/runbooks/ollama-network.md` step A); (4) decide the proposed errata of Plans C, E, F, G, H, I, J and K (K: 82-92
below); (5) migrate the dev database to revision 0010 (`uv run python scripts/skeleton.py migrate`, dev profile: from
0005 it applies 0006 to 0010 together; 0010 re-creates the write-path functions with the token's `azp`, adds
`request_abort` and the dispatch deadline, and changes no row; mcp-write now also refuses to start without it). Next
is Plan L = T17 (the governed corpus, the earliest dependency-satisfied PLANNED task in `handoff/tasks.json` after
T47, unblocked by T09).
**Plan A outcome:** executed on branch `plan-a` (a638801..HEAD); `scripts/check.py` GREEN (54 passed, 1 skipped: owner seal). Final whole-branch review: 5 Important findings fixed in the final-review wave; minors deferred: M3 timing restructure (`astream`), M6 mypy member list.
**Repository:** local git repo at `C:\Users\joeys\Desktop\MLOps`, branch `plan-k` (Plan K work on top of `plan-j`, on top of `plan-i`, on top of `plan-h`, on top of `plan-g`, on top of `plan-f`, on top of `plan-e`, on top of `plan-d`, on top of `plan-c`, on top of `plan-b`, on top of `plan-a`). Remote `github.com/jschnepel/MLOps` (public, MIT) exists; `main` and `plan-a` were pushed on 2026-10-07. `plan-b` to `plan-e` were pushed on 2026-10-08 and `plan-f` on 2026-10-09; `plan-g`, `plan-h` and `plan-i` are pushed too, and every pushed branch matches its local one (checked 2026-10-15). PRs #1-#5 were opened on 2026-10-09 and are green after the EXE001 fix (first green run https://github.com/jschnepel/MLOps/actions/runs/37962510516; record `reports/ci/t06-first-ci-runs.txt`); PRs #1-#8 (plan-b -> main through plan-i -> plan-h) are open now. The plan-j -> plan-i PR is opened after the Plan J final-review fix wave. Merging them in order is the owner's call.
```

Edit 2 (`SESSION_STATE.md`, at the end of "Plan J executed (2026-10-15, branch `plan-j`)"), replace:

```markdown
## Walking-skeleton debt list (T08; committed before coding) [R6-B7]
```

with:

```markdown
## Plan K executed (<date>, branch `plan-k`)

- T47 = `<base>..<last>` (the debt list first, then the five tasks; the close-out is the commit after `<last>`). The
  plan (`docs/superpowers/plans/2026-10-16-first-slice-k-mcp-write-recovery-tools.md`) holds the 27 rulings of the
  controller's brief as implemented; the input is `docs/superpowers/research/2026-10-16-plan-k-inputs.md`. Evidence:
  `tests/e2e/test_migration_0010_live.py` (the round trip and mcp-write's startup check against 0009, the dispatch
  deadline, the abort request's reasons, a receipt recorded after an abort request, the token's `azp` at all five
  write-path definers), `test_mcp_write_t47_live.py` (R030; R131's write half: the `mcp_exec` ACL, read handles at
  mcp-write, incident-sim refusing mcp-read's token; the EXECUTING re-send over HTTP; `lose_after_commit`,
  `delay_receipt`, `receipt_hash_mismatch` and `rate_limit` at the recovery tools; a cancel before send; a send past
  the deadline; a recover redispatch outside EXECUTING), `test_mcp_write_process_live.py` (R025's write half and
  R031's network half at mcp-write) and `reports/mcp-write/`; the unit half is in `tests/plan_k/`, and the
  outcome-truth statement is `docs/threat-model.md`.
- Gates: `check.py` 1152 passed / 180 skipped; `check.py --profile test` 1311 passed / 21 skipped; `verify_handoff.py`
  exit 0 (STATUS.md, "Update — Plan K executed").
- **Proposed errata (the owner decides; the spec text stays authoritative until then).** Numbered on from Plan J's
  eighty-one:
  82. SA:465 (`request_abort`): `request_abort(raw_handle, client_azp, action_id)` takes no reason; under the runs lock
      it chooses one from the latest attempt state, the cancel flag and the clock (`cancelled_before_send`: INTENT and
      cancelled; `expired`: INTENT past the dispatch deadline; `deadline`: SENT and cancelled or past the deadline, so
      a cancel after SENT aborts at once, SA:248), appends `ABORT_REQUESTED` carrying it and returns it; a repeat
      returns the first reason and appends nothing, a resolved attempt answers `resolved`, and otherwise it refuses
      `ABORT_NOT_DUE`. mcp-write cannot choose the reason itself: it sees neither the cancel flag nor `granted_at`.
  83. SA:462-466 with erratum 48 (the caller's `azp`): `grant_execution(raw_handle, client_azp, proposal_id)`,
      `lookup_action(raw_handle, client_azp)`, `mark_sent(raw_handle, client_azp, action_id)`,
      `record_outcome(raw_handle, client_azp, action_id, outcome, document)` and `request_abort` compare the presented
      token's `azp` with the handle's, as `resolve_invocation` does; the worker's client is named once
      (`OPS_WORKLOAD_CLIENT_ID`, default `ops-worker`).
  84. SA:338, SA:344-345 and SA:334 (the attempt-state allowlist): checked in Python with the job type's tools and run
      states (errata 19 and 76); `execute`/`create_incident`: no attempt, INTENT or SENT (SA:344 gains SENT: the
      re-queued job re-sends the same action id after a lost reply, still not cancelled and before the deadline,
      re-checked by `mark_sent`); `recover`/`create_incident`: INTENT only (SA:345 over SA:334; `mark_sent` also refuses
      a recover job's re-send under the lock, `not_redispatchable`); `recover`/`get_incident_receipt`: SENT,
      ABORT_REQUESTED or RESOLVED (a resolved attempt answers its stored outcome); `recover`/`abort_incident`: INTENT,
      SENT or ABORT_REQUESTED. "Not cancelled, before the deadline" is `mark_sent`'s check under the runs lock, for a
      first send and a re-send alike, not the allowlist's.
  85. SA:229-231 and SA:463 (`mark_sent`): it answers `expired`, writing nothing, when `app.current_time()` is past
      `granted_at` plus `app._dispatch_seconds()` (300 s, SA:295), compared after the runs lock and after the cancel
      check, for a first send and a re-send of a SENT attempt alike; it answers `abort_requested`, writing nothing,
      once the latest state is ABORT_REQUESTED (SA:334), and `not_redispatchable`, writing nothing, to a recover job's
      re-send of a SENT attempt.
  86. SA:464 (`record_outcome`): SUCCEEDED and CONFLICT are accepted when the latest state is SENT, or ABORT_REQUESTED
      with the reason `deadline` (an abort after SENT answered by the receipt that already exists, SA:242); after an
      abort of an attempt never sent they stay refused.
  87. SA:280 with SA:241-242 (the FAILED reason after an abort): from INTENT `cancelled_before_send` or `expired`,
      after SENT `aborted_no_commit`; `deadline` is a destination abort reason only. mcp-write reads which case it was
      from the ABORTED tombstone's reason, the one `request_abort` chose.
  88. SA:356 (`abort_incident`'s data): the outcome may also be UNKNOWN (the abort was not answered) or CONFLICT (it met
      another hash's receipt), with neither a receipt nor a tombstone; `status=outcome` for every outcome but
      SUCCEEDED (`schemas/tool-result.schema.json`, regenerated). The example tombstone's reason is the destination's
      token, `cancelled_before_send`.
  89. SA:354-355 (errors after a grant): an abort before it is due is the plain, retryable `ABORT_NOT_DUE`; a recover
      job's redispatch of an unsent attempt whose run left EXECUTING is the plain `STALE_RUN` (redispatch from
      OUTCOME_UNKNOWN is T22's); a recover job's re-send of a SENT attempt is the plain `NOT_REDISPATCHABLE`; a
      recovery call naming another proposal is `GRANT_REFUSED` `OTHER_PROPOSAL` (SA:538); each comes before any
      destination call and names no action.
  90. BS:393 (discovery): "register it only for the reconciliation workload" is met by registering the recovery tools
      on mcp-write alone, where only the worker's workload can authenticate, and refusing every handle but a recover
      job's; the tools are listed to that caller.
  91. R131 and SA:401 (`mcp_exec`'s functions): `mcp_exec` holds EXECUTE on `current_time` (erratum 15) as well as the
      six; "cannot execute any read function" is shown as no EXECUTE on any other `app` function, since `asset_scope`
      and `search_procedures_scoped` do not exist yet (T16, T17/T16; erratum 72's pattern).
  92. SA:242 and BS:502 (the lookup backoff): each recovery tool call makes one destination request with a 10 s
      timeout; the 1, 2, 4, 8 s backoff with jitter and the scheduled recover jobs are the worker's recover handler's
      (T22).
- Earlier debt lines that named T47 and what became of them: Plan J's six are done (mcp-write's verifier, the literal
  `azp` in the definers, the attempt-state allowlist, mcp-write's halves of R025 and R131, the EXECUTING re-send over
  HTTP, the worker's client named once); Plan E's "the abort client and the `abort_incident` tool -> T47/T22": the
  tool and its client are done, the worker's call of it is T22's; Plan E's and Plan H's "the pre-SENT
  `STALE_RUN`/`HASH_MISMATCH` envelopes": `STALE_RUN` is tested live (a recover redispatch outside EXECUTING) and the
  `HASH_MISMATCH` mapping is removed as unreachable (a unit test shows that only `record_outcome` raises `OC007`,
  after the destination answered); Plan H's "mcp-write handles the five new faults only through `classify`": four are
  driven at the recovery tools live, the rest stay T22's; Plan I's "incident-sim's fault route accepts any
  `FaultKind`" moves to T22 (the Plan K debt list).

## Walking-skeleton debt list (T08; committed before coding) [R6-B7]
```

Edit 3 (`SESSION_STATE.md`, at the end of "Dev database state (2026-10-08)"), replace:

```markdown
## Open owner inputs

- Migrate the dev database to revision 0009 (`uv run python scripts/skeleton.py migrate`, dev profile; it applies
  0006, 0007, 0008 and 0009 together), then decide errata 35-44 (see "Plan G executed"), 45-59 (see "Plan H
  executed"), 60-71 (see "Plan I executed") and 72-81 (see "Plan J executed").
```

with:

```markdown
**Update (<date>):** Plan K adds revision 0010. The dev `ops` database stays at 0005 until the owner runs
`uv run python scripts/skeleton.py migrate` (dev profile), which applies 0006 to 0010 together; until then mcp-write
also refuses to start without 0010 (it checks `app.request_abort(text, text, uuid)`). 0010 drops and re-creates
`grant_execution`, `lookup_action`, `mark_sent` and `record_outcome` with the token's `azp` as a second argument,
creates `request_abort` and the helper `_dispatch_seconds()`, and changes no row.

## Open owner inputs

- Migrate the dev database to revision 0010 (`uv run python scripts/skeleton.py migrate`, dev profile; it applies
  0006 to 0010 together), then decide errata 35-44 (see "Plan G executed"), 45-59 (see "Plan H executed"), 60-71 (see
  "Plan I executed"), 72-81 (see "Plan J executed") and 82-92 (see "Plan K executed").
- R025 and R031 have every half evidenced (mcp-read by T15, mcp-write by T47, the import half by T04) but keep
  `NOT_IMPLEMENTED_OR_NOT_TARGET_VERIFIED`, because no open task owns them: flipping their status is the owner's call
  (or T15's re-close).
```

Edit 4 (`SESSION_STATE.md`, under "Exact next step"), replace:

```markdown
Then wait for the owner inputs above (holdout seal, then live probe; push and PRs; the Ollama runbook step A; the dev database migration to 0009; the proposed errata of Plans C-J, up to 81) and write Plan K for T47 (mcp-write, the earliest dependency-satisfied PLANNED task in `handoff/tasks.json` after T15; T17 is also unblocked).
```

with:

```markdown
Then wait for the owner inputs above (holdout seal, then live probe; push and PRs; the Ollama runbook step A; the dev database migration to 0010; the proposed errata of Plans C-K, up to 92) and write Plan L for T17 (the governed corpus and lexical baseline, the earliest dependency-satisfied PLANNED task in `handoff/tasks.json` after T47, unblocked by T09).
```

Then finish the "Plan K executed" section with two bullets only execution can write, inserted after its
earlier-debt bullet (before the `## Walking-skeleton debt list` heading): `- Rulings made during execution:` (one line
each, with its reason; or `- Rulings made during execution: none beyond the plan.`) and `- **Open items for later:**`
(from the SDD ledger `.superpowers/sdd/2026-10-16-first-slice-k-mcp-write-recovery-tools/progress.md`; or
`- **Open items for later:** none recorded.`). The "Exact next step" above is computed from `handoff/tasks.json` with
T47 `DONE`: T17 is the one PLANNED task whose dependencies (`T09`) are all done; T16 still waits for T17.

- [x] **Step 4: Status, the runbooks, the architecture, history and the READMEs**

Edit 1 (`STATUS.md`, under "Update — Plan J executed (2026-10-15, branch `plan-j`)"), replace:

```markdown
  mcp-write, and the remaining `"ops-worker"` literals.
```

with:

```markdown
  mcp-write, and the remaining `"ops-worker"` literals.


## Update — Plan K executed (<date>, branch `plan-k`)

- Plan K (T47: the authenticated mcp-write and its recovery tools) executed on branch `plan-k` (`<base>..<last>`, on
  top of `plan-j`). The plan is `docs/superpowers/plans/2026-10-16-first-slice-k-mcp-write-recovery-tools.md`.
- `PYTHONUTF8=1 uv run python scripts/check.py` is `CHECK: GREEN`: pytest `1152 passed, 180 skipped`.
  `PYTHONUTF8=1 uv run python scripts/check.py --profile test` is `CHECK: GREEN`: pytest `1311 passed, 21 skipped`.
  `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts` exits 0.
- **Evidenced** (`RECORDED_LOCALLY_LIVE` / `IMPLEMENTED_LOCALLY_VERIFIED`): R030 and R131. The receipt lookup answers
  only a recover job's handle whose attempt may have reached the destination; execute and investigate handles, and a
  recover handle of an APPROVED run (no grant), are refused at both recovery tools; a lookup is a GET that creates
  nothing and answers the minimal outcome, and an abort writes only its state rows and the destination's tombstone.
  `mcp_exec` executes exactly its seven functions; investigate and resume_input handles, and one whose stored server
  column lies, are refused at all three write tools; incident-sim refuses mcp-read's token with 403.
- **Write halves recorded** in R025's and R031's notes (both rows are T15's): an independent mcp-write process is
  listed and called by the official client over the network, with the locked SDK versions.
- Also built: mcp-write's verifier at mcp-read's level; the worker's client named once (`OPS_WORKLOAD_CLIENT_ID`);
  revision 0010 (the token's `azp` in the write-path functions, the 300 s dispatch deadline, `request_abort`, a
  receipt recorded after an abort request); the attempt-state allowlist; `get_incident_receipt` and `abort_incident`
  with full bodies; `create_incident` aborting a cancelled or expired attempt itself; `docs/threat-model.md` (v1 trusts
  mcp-write for outcome truth, with T10's detective check as the control).
- The dev `ops` database needs revisions 0006 to 0010 (an owner input); the API, the sweeper, the worker, mcp-read and
  mcp-write refuse to start until then.
- Deferred, each with its owner in `SESSION_STATE.md`: the worker's recover handler, the lookup backoff, scheduled
  recover jobs, redispatch from OUTCOME_UNKNOWN, escalation and late evidence after RESOLVED -> T22; the deadline as a
  setting -> T29; the network half of T47 DoD 3 and per-service tests -> T30; signed receipts -> v1.1. Eleven errata
  (82-92) are proposed. T47 is DONE subject to the owner's decisions on errata 72, 84 and 91.
```

Create `docs/runbooks/mcp-write.md`:

````markdown
# mcp-write: the authenticated write server and its recovery tools (T47)

Who this is for: whoever runs mcp-write, calls it, or works out what happened to an incident a run asked for. The
design is AM-13, AM-15, AM-20.3 and AM-30 in `SPEC_AMENDMENTS.md`, BUILD_SPEC §10, §13 and §14, and Plan K
(`docs/superpowers/plans/2026-10-16-first-slice-k-mcp-write-recovery-tools.md`). What it is trusted for, and what is
not checked, is in `docs/threat-model.md`.

## What a call must carry

A POST to `http://127.0.0.1:8082/mcp` (Streamable HTTP, protocol revision 2026-07-28, stateless, JSON responses) is
checked in this order, as at mcp-read (`docs/runbooks/mcp-read.md`); the first failure decides the answer.

1. **`MCP-Protocol-Version: 2026-07-28`**, exactly once, or HTTP 400 with JSON-RPC `-32022` before authentication.
2. **The worker's access token**: RS256 from the realm's keys, the realm's `iss`, not expired, `aud` containing
   `MCP_WRITE_RESOURCE_URL` (default `http://mcp-write:8082/mcp`), `azp` the worker's client (`OPS_WORKLOAD_CLIENT_ID`,
   default `ops-worker`), a `sub` and the `typ` claim `Bearer` (`write_verifier`); `McpVerifier` refuses again a token
   whose `aud` lacks this server's URL before it stamps the resource. Any failure is HTTP 401 `invalid_token`.
3. **The SDK's checks**: `_meta` agrees with the header, the tool exists, and its one argument, `proposal_id`, is a
   UUID; any other argument is refused.
4. **`X-Ops-Invocation`**, the handle the worker minted for an `execute` or `recover` job, resolved with the token's
   `azp`: known hash, not revoked or expired, at the lease's fence under a live lease, its own run's open job, a write
   job type. Then the allowlist: the job type's tools and run states, and the attempt state the tool may be called in.

   | Job | Tool | Run states | Latest attempt state |
   |---|---|---|---|
   | `execute` | `create_incident` | APPROVED, EXECUTING | none, INTENT, SENT (a re-send) |
   | `recover` | `create_incident` | EXECUTING, OUTCOME_UNKNOWN, ESCALATED, ABANDONED_UNVERIFIED | INTENT |
   | `recover` | `get_incident_receipt` | the same | SENT, ABORT_REQUESTED, RESOLVED |
   | `recover` | `abort_incident` | the same | INTENT, SENT, ABORT_REQUESTED |

   Every refusal of a presented handle is the plain `INVALID_HANDLE` envelope ("invocation handle rejected"), never
   an action id. All three tools are listed to the worker, the only client that can authenticate here; the table is
   what keeps the recovery tools to recover jobs.

## What each tool does

Every definer call carries the raw handle and the token's `azp`; the fence and the binding are checked again inside
each one.

- **`create_incident`**: `grant_execution` (the §13 gate; a second call finds the run's one grant), then `mark_sent`
  under the runs lock, committed before the POST, for a first send and for the re-send of an attempt already SENT
  (after a lost reply) alike. `sent` or `already_sent` POSTs the approved bytes under the grant's action id; the
  destination's key answers, and `record_outcome` records it. `cancelled` or `expired` (five minutes after the grant,
  `app._dispatch_seconds()`) means nothing more is sent: the tool requests the abort, POSTs it and records what the
  destination answers, so an attempt never sent ends FAILED with `cancelled_before_send` or `expired`, and a SENT one
  with the receipt or `aborted_no_commit`. A recover job's re-send of a SENT attempt is refused `NOT_REDISPATCHABLE`.
- **`get_incident_receipt`**: the stored outcome once the attempt is RESOLVED; otherwise one GET of the action's key.
  A receipt for the grant's hash is recorded as SUCCEEDED, another hash as CONFLICT, a tombstone as FAILED_NO_COMMIT;
  a 404, a 429, a 503 or no answer is UNKNOWN and recorded by nobody. It never POSTs and creates nothing.
- **`abort_incident`**: `request_abort` chooses the reason under the runs lock (`cancelled_before_send` or `expired`
  for an attempt never sent, `deadline` after SENT once cancelled or past the deadline) and records ABORT_REQUESTED;
  before either it is refused `ABORT_NOT_DUE` (retryable). The abort POST then meets a fresh tombstone (FAILED), the
  receipt already there (SUCCEEDED) or another hash's receipt (CONFLICT); no answer is UNKNOWN.

Answers: `ok` only for SUCCEEDED; `outcome` with `data.action_id` for UNKNOWN, CONFLICT and FAILED_NO_COMMIT;
`error` for a refusal before any destination call (`INVALID_HANDLE`, `ABORT_NOT_DUE`, `STALE_RUN` for a recover job's
redispatch of a run that left EXECUTING, `NOT_REDISPATCHABLE` for its re-send of a SENT attempt, `GRANT_REFUSED` for a
gate refusal or another proposal's id,
`GRANT_DEFERRED` for a stale membership sync). Each tool call is one destination request with a 10 s timeout; retrying
an UNKNOWN is the worker's (T22).

## Starting it

`python -m ops_mcp_write` (or `scripts/skeleton.py up`) needs the database at revision 0010: at start it refuses when
`app.test_clock` exists outside the test profile, when `app.model_permit` is missing (0007), when `_resolve_handle`
lacks 0009's job binding, and when `app.request_abort(text, text, uuid)` lacks 0010's text ("… predates this service;
run scripts/skeleton.py migrate for this profile"). The dev database stays at 0005 until the owner migrates it.
Readiness (`/health/ready`) needs the realm's signing keys and the database.

| Variable | Default | What it is |
|---|---|---|
| `OPS_MCP_WRITE_PORT` | 8082 | the loopback port it listens on |
| `MCP_WRITE_RESOURCE_URL` | `http://mcp-write:8082/mcp` | its token audience and resource URL, not the listen URL |
| `OPS_INCIDENT_SIM_URL` | `http://127.0.0.1:8090` | the destination it calls with its own `ops-mcp-write` token |
| `OPS_WORKLOAD_CLIENT_ID` | `ops-worker` | the only `azp` it accepts (the worker reads the same setting) |

## Looking at it

As the superuser on the dev database (after the owner's migration to 0010), a run's grant and its attempt history,
then the destination's key (on the `incident` database):

```sql
SELECT g.action_id, g.granted_at, s.seq, s.state, s.outcome, s.detail->>'reason' AS reason, s.at
FROM app.execution_grant g JOIN app.action_attempt_state s USING (action_id)
WHERE g.run_id = '<run>' ORDER BY s.seq;
SELECT state, reason FROM app.runs WHERE run_id = '<run>';
-- on the incident database:
SELECT state, reason, incident_id, decided_at FROM incident.action_key WHERE action_id = '<action>';
```

`uv run python scripts/skeleton.py keys` lists every destination key that no grant's hash matches (exit 1 if any).

## When something looks wrong

- **An UNKNOWN that stays UNKNOWN**: the attempt is SENT and the destination did not answer (or answered 404). Look
  at the key; until T22's recover handler runs, nothing retries it. Never resend under a new key.
- **`ABORT_NOT_DUE`**: the run is not cancelled and the grant is less than five minutes old; the abort is not allowed
  yet.
- **`STALE_RUN` on a recover job's `create_incident`**: the attempt was never sent and the run left EXECUTING
  (OUTCOME_UNKNOWN); redispatch from there is T22's. Nothing was sent.
- **mcp-write will not start**: "predates this service" names the missing revision; "signing keys unavailable" is
  the realm. A handle or a token in a log line is a bug; never run it with uvicorn's `trace` level.

## Not here yet

The worker's recover handler, the backoff, scheduled recover jobs, redispatch from OUTCOME_UNKNOWN and escalation
(T22); the dispatch deadline as a setting (T29); signed receipts (v1.1); network isolation from mcp-read (T30).
````

Edit 2 (`docs/runbooks/mcp-read.md`, under "What a call must carry"), replace:

```markdown
   `aud` containing `MCP_READ_RESOURCE_URL` (default `http://mcp-read:8081/mcp`), `azp` `ops-worker`, a `sub`, and the
```

with:

```markdown
   `aud` containing `MCP_READ_RESOURCE_URL` (default `http://mcp-read:8081/mcp`), `azp` the worker's client
   (`OPS_WORKLOAD_CLIENT_ID`, default `ops-worker`, T47), a `sub`, and the
```

Edit 3 (`docs/runbooks/mcp-read.md`, under "Not here yet"), replace:

```markdown
The asset tools and asset-sim (T16), the governed store and vector search (T17), mcp-write's equivalents of the
verifier hardening (T47), TLS and container host names (T30).
```

with:

```markdown
The asset tools and asset-sim (T16), the governed store and vector search (T17), TLS and container host names (T30).
mcp-write's door, with the same verifier rules, is `docs/runbooks/mcp-write.md` (T47).
```

Edit 4 (`docs/ARCHITECTURE.md`, at the end of "7. mcp-read's door (built in T15)"), replace:

```markdown
## Where the code will live (not yet written)
```

with:

```markdown
## 8. mcp-write's door and the recovery tools (built in T47)

**Claim.** Only the worker's execute and recover jobs reach the destination, every send and abort is recorded before
it leaves, and a recovery call can observe or end an existing action but never start one.

- **The same door as mcp-read.** The version guard, then the worker's access token (`aud` mcp-write's URL, `azp` the
  worker's client, `typ` Bearer), then the handle in the database with the token's `azp`: the five write-path
  functions compare it themselves (revision 0010), so the worker's client is named once, in settings.
- **The allowlist has three dimensions.** The job type's tools and run states, and the latest attempt state: an
  execute job creates with no attempt, INTENT or SENT (the re-send after a lost reply); a recover job redispatches
  INTENT only, looks up SENT, ABORT_REQUESTED or RESOLVED, and aborts INTENT, SENT or ABORT_REQUESTED.
- **Nothing leaves before it is written.** `mark_sent` commits SENT before the POST, and every send passes it, a
  re-send of a SENT attempt included: under the runs lock it refuses a cancelled run (`cancelled`), one past the
  five-minute dispatch deadline (`expired`), an attempt with an abort requested, and a recover job's re-send;
  `create_incident` then aborts instead of sending. `request_abort` commits ABORT_REQUESTED, with the reason it chose,
  before the abort POST; nothing is sent after it. Only the moment between `mark_sent`'s commit and the POST itself is
  left, as AM-13 has it.
- **Recovery observes.** `get_incident_receipt` is one GET of the action's key: a matching receipt, a tombstone or
  another hash is recorded; a 404 or no answer stays UNKNOWN. It creates no grant, attempt, job or key.
- **Least privilege.** `mcp_exec` executes `current_time` and the six write-path functions and nothing else; v1
  trusts mcp-write for outcome truth (`docs/threat-model.md`).

| Requirement | What its test shows |
|---|---|
| R030 | Execute and investigate handles and an APPROVED run's recover handle are refused at the recovery tools; a lookup changes no count and only GETs |
| R131 (write half) | `mcp_exec` executes seven functions only; read handles are refused at mcp-write; incident-sim refuses mcp-read's token |
| R025, R031 (write half) | An independent mcp-write process is listed and called by the official client over the network |

---

## Where the code will live (not yet written)
```

Edit 5 (`docs/PROJECT_HISTORY.md`, at the end of "27. The mcp-read plan closed a legacy door and bound the handle to its job"), replace:

```markdown
## 28. What the process taught
```

with:

```markdown
## 28. The mcp-write plan finished the write door and gave recovery its tools

**Problem.** Plan K takes T47: the authenticated mcp-write and the recovery tools. The fact sheet found the write path
itself real since the walking skeleton, and the server around it behind mcp-read: its verifier stamped its own
audience whatever the token held, the write-path functions named the worker's client with a literal, the allowlist
ignored the attempt state, a cancelled attempt was answered UNKNOWN instead of being aborted, and neither
`get_incident_receipt` nor `abort_incident` existed. The controller's brief of 27 rulings split recovery in two: the
server side (every tool body, every function they call, their refusals) now, the worker's recover loop with T22.

**Change.** mcp-write's verifier now matches mcp-read's, and one setting names the worker's client for the worker's
token source and both verifiers. Revision 0010 passes the token's `azp` to the write-path functions, gives `mark_sent`
the dispatch deadline, adds `request_abort`, which chooses the abort's reason itself, and lets a receipt be recorded
after an abort request. The allowlist gained the attempt state, the two recovery tools got full bodies, and
`create_incident` aborts a cancelled or expired attempt itself. Live tests drive the destination's faults at the
recovery tools, the re-send of an EXECUTING run over HTTP, the cancel and the deadline, and an independent mcp-write
process; `docs/threat-model.md` says plainly that v1 trusts mcp-write for outcome truth.

**Review.** Writing the plan against the code moved three rulings. The abort's reason could not be mcp-write's choice:
it sees neither the cancel flag nor the grant's time, so the function chooses it under the lock. The abort tool's
result schema had no way to say "the destination did not answer", so the schema gained UNKNOWN and CONFLICT. And two
of the faults the rulings named act only on the incident POST, so their effect on the recovery tools is shown through
the POST's consequences, with a scripted reply for a rate limit at the lookup itself.

**Problem.** The plan's first review (0 Blocking, 1 Important, 11 Minor) found a hole the plan said was closed: the
execute job's re-send of a SENT attempt skipped `mark_sent`, so after a lost reply a re-queued job could still POST
after a cancel or past the dispatch deadline, and a recover job could re-send too. **Change.** Every send now passes
`mark_sent`, which checks a re-send as it checks a first send and refuses a recover job's; a receipt after an abort is
accepted only when the abort followed SENT; the hash-mismatch pin follows every function mcp-write reaches; and the
counts and destination keys are checked around the abort as well as the lookups.

## 29. What the process taught
```

Edit 6 (`README.md`, under "Operations Copilot"), replace:

```markdown
> **Status: walking skeleton runs locally (T08) under per-service database roles with RLS (T09) and a hardened destination (T10), with browser login with server-side sessions, revocation and the membership sync (T11); the dev realm now carries the Plan F clients (re-imported on `up`); durable admission with a scoped Idempotency-Key and the AM-16 router (T12), fenced run leases with a heartbeat (T13), a gap-free event journal with a leased notification outbox (T14) and an authenticated mcp-read with invocation handles bound to their run's open job (T15) run locally** ([runbook](docs/runbooks/walking-skeleton.md)). Read [STATUS.md](STATUS.md) before interpreting any capability below as built. The capabilities described are **targets**.
```

with:

```markdown
> **Status: walking skeleton runs locally (T08) under per-service database roles with RLS (T09) and a hardened destination (T10), with browser login with server-side sessions, revocation and the membership sync (T11); the dev realm now carries the Plan F clients (re-imported on `up`); durable admission with a scoped Idempotency-Key and the AM-16 router (T12), fenced run leases with a heartbeat (T13), a gap-free event journal with a leased notification outbox (T14), an authenticated mcp-read with invocation handles bound to their run's open job (T15) and an authenticated mcp-write with its receipt-lookup and abort tools (T47) run locally** ([runbook](docs/runbooks/walking-skeleton.md)). Read [STATUS.md](STATUS.md) before interpreting any capability below as built. The capabilities described are **targets**.
```

Edit 7 (`mcp-write/README.md`, under "Owns"), replace:

```markdown
create_incident, receipt lookup, abort

## Trusts
Workload token with its audience; the six write-path functions
```

with:

```markdown
create_incident, receipt lookup (get_incident_receipt), abort (abort_incident)

## Trusts
The worker's workload access token with this server's audience; the seven functions `mcp_exec` may execute
(`current_time` and the six write-path functions); it is trusted for outcome truth (`docs/threat-model.md`)
```

Edit 8 (`mcp-write/README.md`, at the end of "Never"), replace:

```markdown
## Runs (T08, T15)

`python -m ops_mcp_write` on 127.0.0.1:8082 (`OPS_MCP_WRITE_PORT`), Streamable HTTP at `/mcp`. A POST without exactly
`MCP-Protocol-Version: 2026-07-28` is 400 before authentication (T15). Verifies `aud ∋ MCP_WRITE_RESOURCE_URL`, `azp ==
ops-worker`; resolves `X-Ops-Invocation` for `execute` jobs that are still open while the run is APPROVED or EXECUTING
(T15; revision 0009, which it checks at start). One tool, `create_incident`: grant → INTENT → SENT (committed before
I/O) → POST incident-sim with the `ops-mcp-write` workload token → RESOLVED. A replay while the run is still APPROVED or
EXECUTING (the re-queue after a transport failure) re-sends under the same action id and the destination's key answers;
a replay that resolves its handle after the outcome is recorded is refused `INVALID_HANDLE` before the grant (T15). An
overlapping call that resolved its handle before the outcome was recorded still reaches the stored outcome and returns
it without touching the destination (`execution.py`). A transport failure records OUTCOME_UNKNOWN (reconciliation:
T22). The verifier's T15 hardening and the recovery tools arrive with T47.
```

with:

```markdown
## Runs (T08, T15, T47)

`python -m ops_mcp_write` on 127.0.0.1:8082 (`OPS_MCP_WRITE_PORT`), Streamable HTTP at `/mcp`. A POST without exactly
`MCP-Protocol-Version: 2026-07-28` is 400 before authentication (T15). Verifies `aud ∋ MCP_WRITE_RESOURCE_URL`, `azp`
= the worker's client (`OPS_WORKLOAD_CLIENT_ID`, default `ops-worker`) and the access token's `typ` (T47); resolves
`X-Ops-Invocation` for open `execute` and `recover` jobs, by job type, run state and attempt state (revisions 0009 and
0010, which it checks at start). Three tools: `create_incident` (grant → INTENT → SENT, committed before I/O → POST
incident-sim with the `ops-mcp-write` workload token → RESOLVED; a cancelled or expired attempt is aborted instead and
ends FAILED; an execute job's re-send of a SENT attempt reuses the action id), and, for recover jobs only,
`get_incident_receipt` (one GET of the action's key; creates nothing) and `abort_incident` (`request_abort`, then one
abort POST). A lost or unclear answer is UNKNOWN, recorded by nobody here; the worker's recovery loop is T22's. See
`docs/runbooks/mcp-write.md`.
```

Edit 9 (`mcp-read/README.md`, under "Runs (T08, T15)"), replace:

```markdown
`aud ∋ MCP_READ_RESOURCE_URL`, `azp == ops-worker` and the access token's `typ`; resolves `X-Ops-Invocation` for read
```

with:

```markdown
`aud ∋ MCP_READ_RESOURCE_URL`, `azp` = the worker's client (`OPS_WORKLOAD_CLIENT_ID`, default `ops-worker`) and the
access token's `typ`; resolves `X-Ops-Invocation` for read
```

Edit 10 (`worker/README.md`, under "Runs (T08, T13, T14)"), replace:

```markdown
One `ops-worker` token carries both MCP audiences; one handle per call, bound to the lease's fence and to the client
```

with:

```markdown
One token of the worker's client (`OPS_WORKLOAD_CLIENT_ID`, default `ops-worker`, the one setting both MCP servers'
verifiers read too, T47) carries both MCP audiences; one handle per call, bound to the lease's fence and to the client
```

Run:

```bash
git grep -n "TODO(T47" -- core api worker sweeper mcp-write mcp-read incident-sim scripts tests migrations
git grep -n "T47 debt\|-> T47\|→ T47\|arrive with T47\|follows in T47" -- core api worker sweeper mcp-write mcp-read incident-sim scripts tests migrations
```

Expected: both print nothing (Task 3 rewrote `jobs.JobRule`'s marker, Step 1 the two test texts, this step the READMEs
and the mcp-read runbook). The live evidence line in `tests/e2e/test_mcp_read_process_live.py` ("R025 (read half;
mcp-write with T47)") stays: it says where the other half lives, and changing it would only rewrite T15's committed
evidence.

- [x] **Step 5: Final gates and the placeholders**

```bash
PYTHONUTF8=1 uv run python scripts/check.py
PYTHONUTF8=1 uv run python scripts/check.py --profile test
uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts
```

Expected: `CHECK: GREEN` with `1152 passed, 180 skipped`; `CHECK: GREEN` with `1311 passed, 21 skipped` (the live
number is arithmetic until this run measures it); exit 0. If either printed count differs, write the printed one into
`SESSION_STATE.md`'s "Plan K executed" gates line and `STATUS.md`'s update, and say why in the report. Replace every
`<base>`, `<last>` and `<date>` in `SESSION_STATE.md` and `STATUS.md` with the values defined above; then
`git grep -n "<base>\|<last>\|<date>" -- SESSION_STATE.md STATUS.md` prints nothing. Then `git checkout --
reports/bootstrap reports/auth reports/mcp-read`; the live run rewrote `reports/skeleton`, `reports/admission`,
`reports/leases`, `reports/events` and `reports/outbox` and wrote `reports/mcp-write`, and Step 6 commits them. Tick
this plan's checkboxes (`- [ ]` → `- [x]`) for every step executed.

- [x] **Step 6: Commit**

```bash
git add handoff SESSION_STATE.md STATUS.md README.md mcp-write/README.md mcp-read/README.md worker/README.md
git add docs/ARCHITECTURE.md docs/PROJECT_HISTORY.md docs/runbooks/mcp-write.md docs/runbooks/mcp-read.md
git add tests/plan_j/test_worker_azp.py tests/plan_c/test_schema_conformance.py
git add reports/skeleton reports/admission reports/leases reports/events reports/outbox
git add docs/superpowers/plans/2026-10-16-first-slice-k-mcp-write-recovery-tools.md
# reports/mcp-write/ is written by Step 5's live gate: each of its two modules writes its file only when all of its
# tests passed.
if [ -d reports/mcp-write ]; then git add reports/mcp-write; else echo "reports/mcp-write missing: rerun Step 5"; fi
git commit -m "docs: close T47 - handoff records, acceptance rows, errata 82-92, the mcp-write runbook (Plan K)"
```

---

## Self-review (run by the plan's author before execution)

1. **Spec coverage.** T47's instructions: "mcp-write on the same SDK/protocol pin" → already real (Plan D, the guard
   since Plan J), now with an independent-process client asserting the lock (Task 5); "TokenVerifier with aud =
   MCP_WRITE_RESOURCE_URL" → `write_verifier`, with `typ` Bearer, the adapter's audience check and the SDK's resource
   check (Task 1); "accepts execute/recover handles only" → 0007's server binding, proved over HTTP with investigate,
   resume_input and lying-column handles (Task 4), plus the attempt-state allowlist (Task 3); "DB role mcp_exec holds
   EXECUTE on resolve_invocation, grant_execution, mark_sent, record_outcome, request_abort, lookup_action only" →
   revision 0010 adds `request_abort`; the set is a unit test (Task 2) and a live ACL equality with `current_time`
   (Task 4; erratum 91); "hosts create_incident, get_incident_receipt (recover only) and abort_incident" → Task 3;
   "sole caller of incident-sim with the incident-sim audience and azp" → unchanged (`ops-mcp-write`'s token), and
   incident-sim refuses mcp-read's token (Task 4). DoD 1 "mcp_exec cannot execute any read function; a read handle
   presented to mcp-write is rejected" → Task 4 (the ACL, `42501` for a worker function, three read-handle cases over
   HTTP with positive controls). DoD 2 "Receipt lookup unavailable outside recover jobs and cannot create actions" →
   Task 3's exhaustive table and Task 4's R030 test (execute, investigate and APPROVED-run recover handles refused;
   counts unchanged around the lookups and around an abort; GETs only). DoD 3 "incident-sim accepts only mcp-write's
   token and azp; mcp-read cannot reach incident-sim (network test in T30)" → the token half live in Task 4 (403 at all
   three routes), the network half a debt line to T30. Review notes: 1 (server binding by `session_user`) → 0004's
   `resolve_invocation`, proved by the read-handle refusals and `mcp_exec`'s own resolution of the lying column; 2
   (outcome truth) → `docs/threat-model.md` (Task 5) and the v1.1 debt line; 3 (the EXECUTING re-send over HTTP; the
   worker's client named once) → Task 4's re-send test and Task 1 with Task 2's `client_azp`. The rows by their expected
   evidence:
   - **R030** "Normal/model tools cannot call lookup; reconciliation workload sees minimal existing-action outcome
     only." → `test_r030_the_receipt_lookup_is_recover_only_and_creates_nothing` (Task 4),
     `test_receipt_lookup_is_for_recover_jobs_with_something_to_look_up` (Task 3); the model holds no tool (BS:395).
   - **R131** "… mcp_exec only resolve_invocation, grant_execution, mark_sent, record_outcome, request_abort,
     lookup_action (pg_proc ACL test); … a read handle at mcp-write [is] rejected; incident-sim rejects mcp-read's
     token." → `test_r131_mcp_exec_executes_exactly_the_write_path_functions`,
     `test_r131_read_handles_are_refused_at_mcp_write`, `test_r131_incident_sim_refuses_mcp_reads_token` (Task 4).
   - **R025 / R031** (write halves) → `test_r025_an_independent_client_lists_the_write_tools_and_looks_up_a_receipt`
     (Task 5).
   The spec passages the rulings name are each implemented where the Rulings section says: AM-13's recovery table
   rows INTENT (redispatch: the allowlist admits it, `mark_sent` guards it; abort: `request_abort`), SENT (lookup,
   abort at the deadline, the three abort answers), "destination unreachable" (UNKNOWN, unrecorded), "received but
   not persisted" (the lookup replays the key and `record_outcome` is idempotent); SA:248 (a cancel after SENT aborts
   at once: `deadline`); SA:348 (Task 3); SA:351-356 (the envelopes, erratum 88); BS:393 (erratum 90); BS:502's
   backoff and SA:243's escalation are T22's (debt).
2. **Placeholder scan.** No undecided placeholder, no "similar to Task N", no "add error handling". The template
   markers `<base>`, `<last>` and `<date>` in Task 6 are defined there and replaced in its Step 5, which also greps for
   any left.
   The one `TODO(T47)` this plan writes (Task 2's interim answer to `cancelled` and `expired`) is removed by Task 3,
   which also rewrites `jobs.JobRule`'s as finished; Task 6 Step 4's grep shows none is left.
3. **Type and name consistency.** `settings.workload_client_id()` is read by `main.token_source`, `read_verifier` and
   `write_verifier`, and set in the tests by `OPS_WORKLOAD_CLIENT_ID`. `persistence.grant_execution / lookup_action /
   mark_sent / request_abort / record_outcome` all take `handle` then `azp` (keywords), matching the SQL signatures
   `(text, text, …)` in revision 0010, `privileges.DEFINER_FUNCTIONS`, the call sites Step 5 rewrites, the fakes in
   `tests/plan_h/test_write_path_fence.py` and `tests/plan_k/test_recovery_tools.py` (`Script.definer` asserts the
   `azp` it receives). `execution.create_incident(deps, *, handle, azp, proposal_id)`,
   `get_incident_receipt(deps, *, handle, azp, proposal_id)` and `abort_incident(deps, *, handle, azp, proposal_id)`
   are called with those keywords by `server.build_server`'s three `work` closures and by the tests.
   `allowed_tool(job_type, run_state, attempt_state, tool)` is called in that order by `resolve_invocation` and the
   four test modules. `persistence.WRITE_PATH` is `("app.request_abort(text, text, uuid)", "ABORT_NOT_DUE")`: the
   signature 0010 creates, and text only 0010's `REQUEST_ABORT` carries (a unit test). Task 2's `AZP`, `LATE`, `NOW`,
   `cancel`, `execute_handle(worker, run, *, azp=AZP, fence=None)`, `fence_of` and `recover_handle` and Task 4's
   `COUNTS`, `WRITE_TOOLS`, `started`, `write_token`, `arm`, `at_destination`, `keys_total` are imported under those
   names by the later tasks. `mark_sent`'s seven answers are each handled by `execution.create_incident`
   (`not_redispatchable` as `Refused("NOT_REDISPATCHABLE")`, which `server.refusal_error` maps), and an answer
   outside them raises before any POST.
4. **Review Focus.** (1) a re-send that meets a cancel, the deadline or an abort request → Task 2's definer tests
   (`test_a_re_send_is_checked_as_a_first_send_is`, `abort_requested`, nothing written) and Task 3's re-send,
   recover and abort-request unit cases (no POST); (2) a renamed client → Task 1's
   `test_workload_client.py` and Task 2's five-definer test; (3) another proposal → Task 3's `OTHER_PROPOSAL` unit
   test and envelope case; (4) a lookup without a key → Task 3's four scripted replies and the real 429 request, Task
   4's `delay_receipt`; (5) a database at 0009 → Task 2's startup tests and the live round trip.
5. **Known risks the executor should watch** (none changes a ruling):
   - The live tests of Tasks 2, 4 and 5 were written against the real fixtures, helpers and SDK but could not be run
     in the dry run; their first live run is in execution. The in-process unit tests of Task 3 run the real SDK, the
     guard, the bearer middleware and the official client against the three tools, and the destination clients build
     real requests, so the shapes were measured there; the destination's answers come from incident-sim's own code
     (`keys.document`), which Plan E's and Plan H's live tests exercise.
   - Every live test that uses `approved_run`'s execute handle uses it within its 60 s life and under the 120 s lease
     `approved_run` took; Task 4's read-handle test calls mcp-write nine times first. A machine slow enough to pass 60 s
     there would see its positive control refused (`INVALID_HANDLE`), which reads as a failure of the control, not of
     the refusals: mint a fresh handle with `execute_handle(worker, run, fence=…)` if that happens, and report it.
   - Task 2 and Task 4 move the global test clock 400 s and reset it in `finally`; the suite runs tests one at a time,
     as it does. The lease and the handle a test needs on the moved clock are taken and minted after the move.
   - mcp-write and incident-sim run in the test's event loop on free ports (`started`, Plan J's `serving` pattern), and
     `OPS_INCIDENT_SIM_URL` is set with `monkeypatch` before mcp-write's lifespan reads it; a port taken between
     `free_port()` and the bind fails the start loudly, not silently.
   - Task 2 Step 5's script rewrites SQL text in ten modules by pattern; if a module changed since `320e06d`, its count
     differs and the script writes nothing. Count the module's sites again and update only that entry, in the report.
   - The abort schema change (refinement (b)) regenerates ten files under `schemas/`; `verify_handoff.py --contracts`
     validates them, and `tests/plan_c/test_schemas_generated.py` fails if a generated file is left stale.
   - Revision 0010 drops and re-creates four functions, so a service running during a migration would fail its
     calls until restarted. On the dev database nothing can be running when the owner migrates it: every service
     refuses to start there today (it is at 0005).
   - The window between `mark_sent`'s commit and the POST remains (I1): a cancel that lands in it does not stop that
     one POST. It is AM-13's own (SENT is committed before I/O, and nothing can be re-checked after the request has
     left), and it is the same for a first send and a re-send; the cancel then aborts the action (SA:248) and the
     destination's answer decides.

## Round 1 changes

The static critic's round 1 (`round1-static.md`: 0 Blocking, 1 Important, 11 Minor) and the controller's rulings on it,
applied in one pass; every departure (a)-(h) stands as ruled. Re-verified on a fresh `git archive 52d4075` tree: every
task applies with no missing splice, `ruff format` between tasks changes nothing beyond the plan's own text, mypy
strict and `verify_handoff --reference-code --manifest --contracts` pass, and the dev counts and red steps below are
measured.

- **I1 (accepted as proposed).** The execute job's re-send of a SENT attempt skipped `mark_sent`, so a re-queued job
  could POST after a cancel, past the dispatch deadline, or after an abort request. Now:
  - 0010's `MARK_SENT` answers, under the runs lock and in this order: RESOLVED → `resolved`, ABORT_REQUESTED →
    `abort_requested`; for a SENT attempt, `cancelled`, then `expired`, then `not_redispatchable` for a recover handle
    (this folds M8), otherwise `already_sent`; an INTENT attempt as before. The clock is read once, after the lock.
  - `create_incident` calls `mark_sent` for a re-send as for a first send. `cancelled`/`expired` on a SENT attempt go to
    `_abort`, where `request_abort` chooses `deadline` (SA:248's immediate abort); `not_redispatchable` becomes the
    plain `NOT_REDISPATCHABLE` error (`server.refusal_error`); nothing is POSTed for any of them.
  - Tests: Task 2's unit pin of `MARK_SENT`'s order and a live definer test (`test_a_re_send_is_checked_as_a_first_
    send_is`: `already_sent` to the execute job, `not_redispatchable` to a recover job, `expired` past the deadline,
    `cancelled` after a cancel, no row written); Task 3's unit cases (the re-send after a cancel or the deadline aborts
    without a POST, a due re-send passes `mark_sent` and POSTs, a recover re-send is refused) and the server's
    `NOT_REDISPATCHABLE` envelope.
  - Reworded to match: Task 2's Requirements, rulings 5 and (e), erratum 84 (here and in Task 6's SESSION_STATE text),
    erratum 85, Review Focus 1, the threat model's row, ARCHITECTURE §8 and the mcp-write runbook. Each now says the
    window between `mark_sent`'s commit and the POST is AM-13's own and the same for both steps.
- **M1.** Task 2 Step 1's Expected names the ImportError in `test_migration_0010.py` and the AttributeError in
  `test_mcp_write_startup.py`.
- **M2.** Task 6's two deferral greps moved to the end of Step 4, after the READMEs are rewritten.
- **M3.** `test_no_definer_mcp_write_calls_before_destination_io_raises_a_hash_mismatch` walks `REVISIONS` and follows
  every function mcp-write reaches before a destination answer, helpers included, through its newest body.
- **M4.** The R030 test, its evidence line, ruling 8 and the matrix note say "a recover handle of an APPROVED run (no
  grant)", refused by the run-state rule, and that a no-grant run in a recover state cannot arise through the
  definers. No superuser staging.
- **M5.** `test_a_rate_limited_send_is_aborted_once_cancelled` takes `COUNTS` and a global destination key count
  before the recover calls: the counts do not move, and the keys grow by exactly the abort's tombstone.
- **M6.** `persistence.request_abort` raises `PersistenceError("request_abort returned no reason")` for a NULL reason,
  with a unit test.
- **M7.** `record_outcome` accepts a receipt or a conflict after ABORT_REQUESTED only when that row's reason is
  `deadline`. Erratum 86 and ruling 7 are reworded, with a live definer case: INTENT, then ABORT_REQUESTED
  (`cancelled_before_send`), then SUCCEEDED is refused `OC003`.
- **M8.** Folded into I1.
- **M9.** Task 6's SESSION_STATE gains an owner-input line: R025 and R031 have every half evidenced, and flipping their
  status is the owner's call or T15's re-close.
- **M10.** The read-handle test checks `COUNTS` before and after its nine refused calls.
- **M11.** 0010's downgrade docstring says that 0009's `mark_sent` would not honour a leftover ABORT_REQUESTED row.
- **Moved helpers.** `fence_of` and `recover_handle` moved from Task 4's module to Task 2's live module, which now
  needs them. Task 4 imports them, and Task 5 still imports `recover_handle` through Task 4's module.
- **Counts.**
  - Dev: Task 2 is 1103/169 (+1 unit test, +1 live test); Tasks 3-6 are 1152/169, 1152/179, 1152/180, 1152/180 (+5
    unit tests in Task 3).
  - Live (arithmetic): 1232, 1251, 1300, 1310, 1311, each with 21 skipped.
- **Changed red and intermediate Expected lines.** Task 2 Step 1 (wording only, still `3 errors in`), Step 4 `42
  passed`, Step 5 `213 passed`, Step 6 `5 passed`; Task 3 Step 3 `41 failed, 9 passed`, Step 7 `50 passed` and `688
  passed, 19 skipped`. Task 1's and Task 3 Step 1's are unchanged.

## Round 1 open points

- None of the controller's rulings was impossible as written. One choice the rulings left open: `not_redispatchable` is
  checked after `cancelled` and `expired`, as the ruling orders it. So a recover job's `create_incident` on a SENT
  attempt of a cancelled or overdue run aborts the action (`deadline`) rather than being refused. The outcome is the one
  `abort_incident` would reach, and nothing is sent. **Resolved in round 2:** the controller confirmed this order.
- The live halves (now 5 + 10 + 1 live tests) still run first in execution; their counts are arithmetic.

## Round 2 changes

Round 2 accepted the plan (0 Blocking, 0 Important); its four minors are applied as proposed.

- **N1.** The Architecture paragraph and Task 6 Step 2's handoff note (which goes into `handoff/tasks.json` and
  `BUILD_BACKLOG.md`) now say `record_outcome` accepts a receipt or a conflict only after an abort requested after SENT
  (reason `deadline`), as ruling 7, erratum 86 and the revision's docstring already did.
- **N2.** `execution.py`'s module docstring (Task 3 Step 5): the abort rule covers the re-send of a SENT attempt
  too (the immediate abort, `deadline`, whose answer decides: the existing receipt or `aborted_no_commit`), and the
  replay paragraph is reflowed, so Step 5 has one edit fewer (its old Edits 2 and 3 are one edit now).
- **N3.** The owner-facing errata in Task 6 Step 3: full erratum 85 gains "for a first send and a re-send of a SENT
  attempt alike" and `not_redispatchable`; erratum 89 (full and summary) gains the plain `NOT_REDISPATCHABLE` for a
  recover job's re-send of a SENT attempt.
- **N4.** `GUARD_0010` compares `v_latest.detail->>'reason' IS NOT DISTINCT FROM 'deadline'`, so an ABORT_REQUESTED row
  without a reason refuses a receipt instead of letting it through (the backstop fails closed). The derived-body unit
  test is unchanged: it undoes the constant.
- The round-1 open point (the order `cancelled`, `expired`, then `not_redispatchable`) is confirmed and marked resolved.
- No count changes: dev and live counts per task are as in round 1, and no red or intermediate Expected line moves.

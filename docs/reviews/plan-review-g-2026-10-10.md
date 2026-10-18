# Plan G review record — T12 durable admission API, Idempotency-Key and error mapping

Plan: `docs/superpowers/plans/2026-10-10-first-slice-g-admission-idempotency.md` (branch `plan-g`, plan commit
e09b004). Inputs: `docs/superpowers/research/2026-10-09-plan-g-inputs.md` and
`docs/superpowers/research/2026-10-10-plan-g-spike.md`. Each round below is one static adversarial review of the plan
text plus one builder dry run that executed every step in a detached scratch worktree, followed by the controller's
rulings and the fix commit that applied them. The round after the last one with zero workarounds and no Blocking or
Important finding closed the review.

---

# Round 1

## Static review

## Plan G round 1: static adversarial critic

Plan: `docs/superpowers/plans/2026-10-10-first-slice-g-admission-idempotency.md` (7426 lines, branch `plan-g`, e09b004).

**Verdict: REVISE.** 2 Blocking, 6 Important, 9 Minor. Every splice applies and the dev-gate counts check out. The
two Blocking findings are design defects in the clarification-reply unit (lock order and serialisation) and in
recording the 429.

How this was checked: I read the whole plan, AM-10, AM-12 (SA:186-188), AM-16, AM-20.2-20.5, BS:262-302, 508-521
and 540-567, T12 with its review notes, R015-R018, R115, R129, the fact sheet and the spike, and every cited line.
I extracted every `Edit N (old lines a-b)` block (71 of them) with a script and applied them in order to scratch
copies. Before each group I checked that the old text occurs exactly once and starts and ends at the cited lines.
All 71 matched. I then built a scratch tree: the repo with the edits, the 14 `Create` files, the two whole-file
replacements (`routing.py`, `store.py`) and the `testpaths` change. On that tree, with the repo's locked venv:

- `ruff check .`: "All checks passed!" (ruff 0.16.10).
- `ruff format --check .`: 214 files already formatted.
- `mypy --no-incremental` on the eight member trees: "Success: no issues found in 48 source files".
- `mypy core/src api/src`: 23 files. This matches Task 5 Step 4.
- `pytest -q`: 745 passed, 20 failed, 104 skipped. All 20 failures come from the scratch copy leaving out `reference/`,
  the zip and `.git` (verify_handoff, traceability, text hygiene). That makes 765 + 104, which is Task 6/7's dev
  count exactly.
- `tests/plan_g tests/plan_d/test_api.py tests/plan_f tests/plan_e tests/plan_c`: everything passes except the 2
  traceability tests that need `reference/`.

Baseline on the real tree: 679 passed, 95 skipped. The skips break down as 65 + 9 live, so 74 live. The plan says
the same. Nothing in the real repo was edited. The DB-touching paths (`DbUnit` SQL, the live modules) could not run.
They are judged statically against the grants, the functions and the spike.

### Blocking

**B1 — Plan lines 297-308 (ruling 15), 4297-4339 (`reply_clarification`), 4682-4713 (`DbUnit.record_reply`).**

What is wrong: the clarification reply is an API mutation with `expected_version`, but it never locks the run.
- It reads `state`/`state_version` and the latest `clarification.requested` with plain SELECTs.
- Then it inserts the message, then the `resume_input` job (whose FK takes KEY SHARE on the run row).
- Only then does it take `runs FOR UPDATE`, inside `app.append_event` (for `next_event_seq`).
- The version check is therefore not serialised. A cancel (T21), a worker transition or crash recovery that moves
  the run between the read and the commit still gets a 202, a `resume_input` job and a `clarification.received` on
  a run that is no longer AWAITING_INPUT at that version.
- The order is messages → jobs → runs, which inverts SA:188's `runs → messages`.

Evidence:
- SA:186: "API and sweeper mutations … serialize with `SELECT … FROM runs … FOR UPDATE` plus `expected_version`".
- SA:188: the lock order; "Every transaction and definer function follows this order".
- BS:264: "State-specific mutations include `expected_version`".
- BS:273: "Bind reply to outstanding question ID and expected version".
- `api` can take the lock: it holds the column UPDATE on `runs` (fact sheet §3.7: "the `api` role can take
  `FOR UPDATE` on `runs`").
- `migrations/app/versions/0003_run_path_functions.py:357-376`: `append_event` locks the run inside the function.
- The fake (`FakeUnit.run`, plan lines 3328-3332) has no lock either, so no test can see this.

Smallest fix:
- Make `DbUnit.run(run_id)` for this route `SELECT run_id, conversation_id, requester, state, state_version FROM
  app.runs WHERE run_id = %s AND tenant_id = %s FOR UPDATE`. That is the first table lock after the advisory lock.
- Then check the state, the version and the outstanding question under that lock. Insert the message, the job and
  the event afterwards; `append_event`'s own FOR UPDATE then re-takes a lock it already holds.
- Name the lock in the `Unit.run` docstring (SA:186) and record it in ruling 15.
- Add a two-connection live assertion, or at least a statement-order unit test on a recording `Unit`, that the run
  lock precedes the message insert.

**B2 — Plan lines 219-225 (ruling 5), 327-333 (ruling 18), 4167-4168, 3013-3016, 5206-5215
(`test_a_full_tenant_queue_is_a_recorded_429_with_retry_after`), 7314 (dev-topology text).**

What is wrong: a 429 "tenant queue is full" with `Retry-After: 5` is written to the record. Every retry with the same
key then replays the 429 for the whole replay window (24 h by default), even after the queue drains. The test even
pins this: `fake.runs.clear()` and then a 429 again. The plan's own runbook text tells clients to keep the key "the
same for a retry" (7307) and to honour `Retry-After` (7314). A client that does both can never be admitted under
that key, so `Retry-After` is false.
- 429 is the one refusal BS:301 reserves for a transient condition ("bounded capacity").
- The router never decides it. The quota count sits outside `ADMISSION_RULES`, so ruling 5's own rule of thumb
  ("the router's verdict is recorded; everything before the router is not") does not cover it.
- AM-16's reject row ("nothing written except the idempotency record") answers 422/409, not 429.

Evidence: BS:301, BS:550 ("reject clearly when full"), BS:564 ("Overload: bound queue and return clear 429/503
behavior"), SA:373; plan lines 7307-7314.

Smallest fix:
- Treat the 429 like the 503: raise a `QueueFull` from the unit (rollback, no record) and map it in `recorded()` to a
  safe 429 with `Retry-After`.
- Drop the 429 special case from `response()`.
- Change the test to assert that a same-key retry after the queue drains is a 202.
- Update ruling 5's list and the store docstring.

### Important

**I1 — Plan lines 297-305 (ruling 15), 4304-4332.**

What is wrong: any `requester` of the tenant may answer another requester's clarification. The route checks only the
role and the tenant. `DbUnit.run` does not even select `runs.requester`. The reply's `context` (asset, hours) is
content that shapes the run's draft. Its author is neither the requester nor in `authored_by`, so a subject who holds
both `requester` and `reviewer` in one tenant can answer the question and then approve the resulting proposal.

Evidence: AM-20.7 item 4 (SA:539, "Independence covers every content author … R093"); `0004:198-200` (the
independence check is `p_reviewer = v_run.requester OR … authored_by`); BS:273.

Smallest fix:
- Select `requester` in the (locked, B1) run read.
- Answer 404 "no such run" (do not disclose existence) when `run.requester != requester`.
- Add a unit test and an HTTP test with a second requester. Alternatively, a definer change that appends the replier
  to `authored_by` (a T20/T21 item).

**I2 — Plan lines 1033-1051, 1077-1084 (`read_bounded`, `BodyLimit.replay`).**

What is wrong: on `http.disconnect` during the pre-read, `read_bounded` returns the bytes that arrived. The middleware
then replays them to the route as a complete body (`more_body: False`). The comment "the route sees what arrived and
its own read fails" is false: the route never calls `receive()` again, so nothing fails.
- Without the middleware, Starlette's `request.body()` raises `ClientDisconnect` and nothing is admitted.
- With it, a truncated body that still parses (for example cut after the closing brace) is admitted for a client
  that is gone.
- A `POST /api/v1/conversations` from a disconnected client still commits.
- Either way the client's retry with the full body under the same key meets 409 `IDEMPOTENCY_CONFLICT`.

Evidence: Starlette `Request.stream()` raises `ClientDisconnect` on `http.disconnect`; the spike's §5 middleware
was not tested with a disconnect; R015 ("no volatile acceptance").

Smallest fix:
- Have `read_bounded` raise a `BodyIncomplete` on disconnect, and have `BodyLimit` return without calling the app.
- Add a `test_limits.py` case: a disconnect after the first chunk means the inner app never runs.
- Correct the comment.

**I2a (same root) — plan line 1043:** the comment text must change with the fix (`docs/CODE_COMMENTS.md` rule 8).

**I3 — DoD 4 / R129 "unroutable kinds yield 422": plan lines 5135-5163, 6913-6916, self-review 7357-7360.**

What is wrong: no test posts an unroutable `kind` (for example `"kind": "delete"`) through the API.
- The only 422 reject exercised is `kind=clarification`, which AM-16 routes; the plan turns it into a reject by
  erratum 40.
- The self-review claims "unroutable kind 422" is covered by Task 6 R129 and R018. It is not.
- A strict-enum parse failure is also unrecorded by ruling 5, so the AM-16 property "nothing written" for an
  unroutable kind needs its own assertion.

Evidence: tasks.json T12 DoD 4; acceptance-matrix R129 `expected_evidence` ("unroutable kinds 422"); SA:373.

Smallest fix: add a parametrised `test_api_admission.py` case (`"delete"`, `""`, `"STATUS"`) asserting 422
`INVALID_INPUT` and no new message, run, job or record. Add one such POST to the live R129 test.

**I4 — Plan lines 6783-6797 (live R017), 3651-3657.**

What is wrong: the SQL savepoint in `DbUnit.start_run` is the only thing that makes AM-16's "nothing written except
the idempotency record" true for a slot race lost inside `create_run`. Nothing proves it in PostgreSQL.
- The unit test uses the fake's `slot_occupied` flag, which refuses before inserting.
- The live race asserts only the status codes and `held == 1`. It never counts the loser's message or its record.

Evidence: SA:373; plan lines 4637-4661; spike §4.

Smallest fix: after the race, assert `count(messages WHERE conversation_id = cid) == 1`. Also assert that exactly
one record with status 409 exists for the loser's key: bind the two keys and query by key. Write both counts to the
evidence line.

**I5 — Plan lines 4341-4387, 5681-5701, review focus 5 (174-176), ruling 21.**

What is wrong: on the decisions route the reviewer check runs inside the unit after the record lookup. A subject who
has lost the `reviewer` role but is still a member (for example now `reader`) replays a recorded 200 decision. The
messages and clarifications routes refuse role loss before the record (`requester_mutation`).
- This contradicts the plan's own rationale: "identity runs before the record" (BS:264, "an authenticated current
  session").
- Review focus 5 tests only full revocation.

Evidence: plan lines 174-176, 350-357; `api/src/ops_api/app.py:197-210` (`enabled_identity` checks Keycloak, not
the role).

Smallest fix:
- Add `who.require("reviewer")` (403, unrecorded) in a `reviewer_mutation` dependency before `idempotency_key`.
- Keep the independence check inside the unit.
- Add a test: replay after changing `ROWS[SAM]` to `reader` gives 403.

**I6 — Plan lines 344-349 (ruling 20), 824-830, 2948, 5256 (`# the first request_id`).**

What is wrong: a replayed recorded error carries the first request's `request_id` in the body, while `RequestId`
stamps a fresh `X-Request-Id` header. So the "id in the body is the id in the header and in the one log line"
invariant that `test_error_surface.py` states is false for every replayed 404/409/422 record. Router verdicts are
also never logged, so an operator cannot match either id to a log line.

Evidence: BS:301; plan lines 824-826, 2946-2948, 6964-6966 (R115 live checks fresh errors only).

Smallest fix, either one:
- Rewrite `request_id` in a replayed error body to the current request's id, so the bytes differ only there. Document
  that in ruling 4.
- Or log one INFO line per recorded refusal with the request id and the record's first request id. Then narrow the
  docstring's claim to fresh errors.

### Minor

**M1 — Plan line 7260 (README edit).** The old text ", durable admission is next (Plan G)" does not exist. README:5
reads "…(re-imported on `up`); durable admission is next (Plan G)**" with a semicolon. Fix: quote the real tail
"; durable admission is next (Plan G)".

**M2 — Plan lines 365-372, 4287-4289, 3660-3669, 5218-5228, 6731.**

What is wrong:
- The simulated crash before commit is a `PersistenceError`, so the client is told `retryable: false`.
- Every R015 test then retries with the same key and expects 202, and BS:299's replay contract says a retry is what
  the key is for.
- A real crash before commit is a lost connection, which the plan maps to `retryable: true`.

Fix: raise `psycopg.OperationalError("fault: drop_before_commit")` (retryable), or state in ruling 24 why the fault
is final.

**M3 — Plan lines 6804, 6857.** The live tests put response attributes straight into assert operands
(`same_key[0].content == same_key[1].content`, `replay.content == first.content`). The carried constraint (line 58)
says "bind responses before asserting". No secret is involved. Fix: bind to locals first, as R016 does with `same`.

**M4 — Plan lines 6766-6778, 6543-6558, 5251-5260.** Live tests leave rows in `ops_test`:
- The expired row `r016-key-0002` is deleted outside a `finally`.
- `purge_conversation` removes only records whose body names the conversation or run. Error verdicts (404, 409,
  422) keep their records.

These rows are not system messages, so the 0006 downgrade is unaffected and they go when the database is dropped.
Fix: delete by the test's keys in the `created` fixture, and put the R016 delete in a `finally`.

**M5 — Plan lines 226-227, 4523.** The scope lock and the asset guard (SA:189) both use `hashtextextended(…, 0)`
over one 64-bit key space. A collision only serialises (both are first locks, no cycle). Fix: use the two-int form
`pg_advisory_xact_lock(<namespace>, …)` or a distinct seed, and say so in the erratum 37 text.

**M6 — Plan lines 299-300, 4310-4311.** A `question_id` naming an earlier, superseded question answers 404 "no
outstanding clarification". BS:301 puts stale versions under 409. Fix: 409 `VERSION_CONFLICT` when the id is a
`clarification.requested` event of this run but not the latest. Otherwise 404.

**M7 — Plan lines 1938-1973 (`test_migration_0006_live` test 1).** The first `downgrade` and the conversation insert
sit outside the `try`, and the `finally` runs `migrate` before `forget`. A failing `migrate` therefore leaks the
conversation, and a failing first downgrade skips cleanup. Fix: nest `forget` in its own `finally`.

**M8 — Process, plan lines 1734-1878 and 5327-5777.** Task 2 Step 4 bundles a failing test, three source files and
the API guard. Task 5 Step 2 is 15 edits in one step. Neither is "one action". Fix: split them, for example Step 4a
(test), 4b (sweeper), 4c (API guard).

**M9 — Plan line 4092 / ruling 20, line 346.** "Error log lines include it", but `enabled_identity`
(`app.py:204`) and the back-channel route still log without the request id. Fix: add the id to those two lines or
narrow the claim.

### Checked and passed

Spec:
- The six AM-16 routes and their effects match SA:367-373: status = two messages, no run, job or event; clarify = a
  stored `clarification_question` and 200, after the slot check; reject = 422/409. The hint can only produce clarify
  (SA:375), and the router is a first-match table in `core/routing.py`.
- `clarification_reply` moves to BS:273's route. This is a deviation, but it is declared as erratum 40 with a
  measured reason (no `question_id` in `MessageRequest`).
- Ruling 9 keeps the slot as the `WHERE slot_held` partial unique index (0002:213), with the live two-connection race.
  `ask` holding the slot is declared as erratum 38.
- AM-20.2:
  - `api` on `jobs` = INSERT only; the target-less `ON CONFLICT DO NOTHING` needs no SELECT (spike §2).
  - `api` never UPDATEs `conversations` or `messages`.
  - `idempotency_request` = api sel+ins and sweeper sel+del, the SELECT declared as erratum 36. The frozen
    `GRANTS_0006` strings match `grant_statements`.
  - `append_event` is callable by `api` and allows `clarification.received`.
  - `record_decision` takes the 7th argument `idempotency_key`.
- AM-20.5: the record table has no RLS (SA:523, `NO_RLS`). Messages are inserted under a set tenant.
- SA:188: the record is written last; the advisory lock first is declared as erratum 37. Admission's message-before-
  `create_run` is the pre-existing T08 shape (FK `runs.message_id`), not new.
- BS:299: the accepted body keys are present (`stream_url` is declared debt to T27); success is returned only after
  the unit commits (the return passes through `__aexit__`); same key and body replays, a different body gives 409.
- BS:301: every code is mapped; `retryable` is true only for an outage.
- BS §17: 64 KiB body, 4000-character text, hours 1-168 in the parser. The global queue bound is declared debt to
  T13 (erratum 39).
- T12's instructions, DoD 1-3 and review notes 1-2 are covered (DoD 4's unroutable kind: see I3). R015-R018, R115 and
  R129's admission half are covered.

Security:
- The scope is (tenant, subject, route template, key), so no record reaches another subject. The bearer and cookie
  identities of one subject share it.
- The fingerprint covers the path parameters and the validated body. A conversation id reused under the same key is
  a 409, tested.
- `identity` and `requester_mutation` run before the key and the record.
- The body limit counts arriving bytes: chunked, lying-low and malformed `Content-Length` are refused before the route.
- No 23505 DETAIL reaches the client or the log (class name only).
- The fault route exists only when `profile is Profile.TEST`, and `Faults` refuses otherwise (R098).
- No secret, token or cookie reaches the evidence lines or a log.
- The test-admin client is not used.

Splices:
- 71/71 `Edit` blocks match the cited lines exactly once, including the Task 4 and 5 line numbers "as the previous
  task left it". The whole-file `routing.py`/`store.py` replacements and the later `store.py` deletions (653-677,
  986-1083) line up.
- Every name a later task uses is defined earlier with the same signature: mypy strict passes on the simulated tree.
- Every psycopg call uses the `Session.unit` transaction, and the savepoints are nested `conn.transaction()`.

Tests:
- No `await` sits in a generator expression (the live lists are list displays).
- The clock offset is reset in a `finally`.
- The R018 bound tolerates 60 s of skew.
- The 0006 downgrade guard is cleared by `purge_conversation`, and the admission module sorts before both downgrade
  modules (`test_migration_0006_live`, `test_migrations_and_persistence`).
- The fake inherits the real orchestration and restores its tables on exception.

Gates and arithmetic, all reproduced:
- Task 1: 698 = 679 + 5 + 7 + 7; Step 7: 14 and 157.
- Task 2: 2 failed / 12 passed, then 16; 703.
- Task 3: 26 new + 18 = 44; 729.
- Task 4: 8 + 12; 749; 158.
- Task 5: 15 failed / 1 passed; 8 failed / 150 passed; 242 = 84 + 158; 765.
- Task 6: 765 / 104.
- Live: 753 → 772, 780, 826, 842, 848 / 21. The e2e skips are 65 + 9 live = 74.
- Ruff 0.16 default rules and format pass; mypy strict passes; no line over 120 characters in the code.
- `build_schemas.py` and the schema conformance tests are unchanged and green.
- `tasks.json` and `acceptance-matrix.json` round-trip byte for byte with the close-out's `json.dumps`, and the
  BUILD_BACKLOG anchor exists.

Process:
- The debt list is committed before code (Task 1 Step 1).
- Each task commits on its own.
- The docstrings follow `docs/CODE_COMMENTS.md`.
- The `TODO(T19/T27/T12)` markers are owned.
- The close-out covers SESSION_STATE, STATUS, PROJECT_HISTORY, README, `api/README` and both runbooks (except M1).

## Builder dry run

## Plan G dry run, round 1 (builder report)

Plan: `docs/superpowers/plans/2026-10-10-first-slice-g-admission-idempotency.md` at `plan-g` e09b004.
Scratch worktree: `C:/Users/joeys/Desktop/MLOps-dryrun-g` (detached at e09b004), removed at the end.
Date: 2026-10-10. Code was typed by extracting each fenced block from the plan verbatim (a small extractor that
writes the block byte for byte, and a splice helper that refuses unless the "replace" text occurs exactly once).

### Summary

- Tasks reached: all seven (Task 1 to Task 7 Step 5), every step executed, every plan checkbox ticked in the scratch
  copy. Dry-run commits in the worktree (discarded with it): 760c93f, c7fb9bd, d4a8e6a, e362389, 79528b2, 14fafed,
  a74d2e3, a4481f1.
- Every splice's old text was found exactly once (about 90 splices); every red/green expectation matched the plan's
  line; ruff format left every plan file unchanged, ruff check clean, mypy strict clean
  (`Success: no issues found in 23 source files`), no plan-written Python line over 120 characters.
- Workarounds: 6 in total.

| Task | Workarounds | Ids |
|---|---|---|
| 1 | 2 | WA-1 (recurs after every live gate), WA-2 |
| 2 | 1 | WA-3 |
| 3 | 0 | |
| 4 | 0 | (one wording nit, no workaround) |
| 5 | 0 | |
| 6 | 0 | (WA-1 recurred) |
| 7 | 3 | WA-4, WA-5, WA-6 |

Final gate tails (Task 7 Step 4):

```text
dev:   765 passed, 104 skipped in 37.61s / CHECK: GREEN
live:  848 passed, 21 skipped in 196.85s (0:03:16) / CHECK: GREEN
verify_handoff.py --reference-code --manifest --contracts: exit 0
       PASS: 161 delivered 1.0 snapshot checksums verified against handoff-1.0.zip
```

Per-task gate tails (all as the plan expected, except Task 2's first live run):

```text
baseline   dev 679 passed, 95 skipped in 48.41s GREEN | live 753 passed, 21 skipped in 191.00s GREEN
Task 1     dev 698 passed, 95 skipped in 38.46s GREEN | live 772 passed, 21 skipped in 194.76s GREEN | verify 0
Task 2     dev 703 passed, 98 skipped in 39.34s GREEN | live 1 failed, 779 passed, 21 skipped CHECK: RED (WA-3)
           after WA-3: live 780 passed, 21 skipped in 194.37s GREEN | verify 0
Task 3     dev 729 passed, 98 skipped in 39.07s GREEN | (no live gate required) | verify 0
Task 4     dev 749 passed, 98 skipped in 38.53s GREEN | live 826 passed, 21 skipped in 197.28s GREEN | verify 0
Task 5     dev 765 passed, 98 skipped in 41.74s GREEN | live 842 passed, 21 skipped in 196.18s GREEN | verify 0
Task 6     dev 765 passed, 104 skipped in 39.60s GREEN | live 848 passed, 21 skipped in 197.91s GREEN | verify 0
           test_admission_live.py alone: 6 passed in 3.25s; R105 alone: 1 passed in 28.80s
Task 7     dev 765 passed, 104 skipped in 37.61s GREEN | live 848 passed, 21 skipped in 196.85s GREEN | verify 0
```

Evidence file written by Task 6 (header plus nine lines, every shape as the plan's Step 3 block; R018's timedelta was
`1:59:59.174989`; no id of the second tenant and no token, cookie or bearer string in it).

### WORKAROUND entries

WA-1 — Task 1 Step 1 (and every later live gate: Tasks 1, 2, 4, 5, 6, 7) — the plan says that after a live run
`git checkout -- reports/bootstrap reports/skeleton` (Task 6 Step 5 and Task 7 Step 4: `reports/bootstrap` only) —
every `check.py --profile test` also rewrote `reports/auth/t11-sessions-revocation.txt` (`git status`:
` M reports/auth/t11-sessions-revocation.txt`; diff is the header timestamp,
`-T11 sessions and revocation — 2026-10-09T12:22:32Z` / `+T11 sessions and revocation — 2026-10-10T08:22:59Z`) —
also ran `git checkout -- reports/auth` each time. Plan change: add `reports/auth` to every post-live checkout
(Global Constraints "Gates", every task's gate step).

WA-2 — Task 1 Step 8 — "count characters on the touched files" with the list ending `pyproject.toml` — the counting
command printed `pyproject.toml 53`; that line (the `norecursedirs` comment, 121 characters) is on HEAD already and
not touched by the plan — ignored it as pre-existing. Plan change: drop `pyproject.toml` from the counting list or
say pre-existing lines are out of scope.

WA-3 — Task 2 Step 6 — expected live gate `CHECK: GREEN` with `780 passed, 21 skipped` — got
`1 failed, 779 passed, 21 skipped in 192.88s` / `CHECK: RED`:
`FAILED tests/e2e/test_sweeper_live.py::test_purge_expired_deletes_only_what_is_past`,
`AssertionError: assert {'sessions': ...y_request': 0} == {'sessions': ...ogout_jti': 1}`,
`Left contains 1 more item: {'idempotency_request': 0}` (line 130). Step 4 changes `sync.purge_expired`'s result to
four keys but the plan never lists the live sweeper test — changed its assert to
`{"sessions": 2, "login_state": 1, "logout_jti": 1, "idempotency_request": 0}`, re-ran the live gate
(`780 passed, 21 skipped in 194.37s`, GREEN) and committed the file with the task. Plan change: add
`tests/e2e/test_sweeper_live.py:130` to Task 2's Modify list (better: seed one expired and one live record so the
purge of `idempotency_request` is proved live, expecting `"idempotency_request": 1`), and to the Plan G additions'
list of tests "updated in the task that changes the interface they pin".

WA-4 — Task 7 Step 1 (also the definition of `<first>..<last>` above Step 1) — the span is
`git log --reverse --format=%h b4e97bc..HEAD`, "`<first>` is the debt-list commit" — b4e97bc is the research commit;
the plan commit e09b004 sits between it and the debt list, so the command prints `e09b004` as `<first>` (the plan
itself, not Task 1's debt list) — ran the Step 1 script with `e09b004..HEAD` instead; it printed `760c93f..a74d2e3`.
Plan change: base the range on the plan's own commit (or `git log --format=%h -1 --grep 'T12 debt list'` for
`<first>`), in Step 1's script and in the definition line.

WA-5 — Task 7 Step 2 item 2 — the "Plan G executed" markdown block is to be inserted verbatim, but its last two
bullets are instructions to the executor, not content ("Rulings made during execution: each one the task reviews
recorded, one line each with its reason; when there were none, the line reads ..."; "**Open items for later**, parked
by the task reviews (from the SDD ledger ...; in a literal run with no ledger, the line reads "none recorded")") —
inserted as written they put the instructions into SESSION_STATE.md — replaced them with content: one ruling line
(WA-3's live sweeper assert) and "**Open items for later:** none recorded." Plan change: keep those two bullets out
of the fenced block and say in prose what to write there.

WA-6 — Task 7 Step 3 (`README.md` line 5) — "replace the status sentence's tail `, durable admission is next
(Plan G)`" — the file has a semicolon there (`... (re-imported on \`up\`); durable admission is next (Plan G)**`);
the comma form occurs 0 times — replaced `; durable admission is next (Plan G)` with
`, and durable admission with a scoped Idempotency-Key and the AM-16 router (T12)`, which gives exactly the line the
plan shows. Plan change: quote the old tail with the semicolon.

Observations without a workaround (no step was blocked):

- Task 4 Step 3: the heading, the Modify line and the step text say "five helpers"; the block adds six
  (`insert_job_untargeted`, `current_time`, `latest_active_run`, `latest_run`, `latest_event`, `queued_count`).
- Task 7 Step 3: with no SDD ledger the plan's rule yields "Execution found nothing the plan had not ruled on." in
  PROJECT_HISTORY §24, although WA-3 was a real execution finding; the rule only counts review findings.
- Task 7: R129 is marked `IMPLEMENTED_LOCALLY_VERIFIED` / `RECORDED_LOCALLY_LIVE` while its note says the graph
  router half lands with T20 (as the plan's script writes it; a reviewer may want a partial status).
- Task 6 Step 1 expects `2 passed` for `tests/plan_b/test_evidence.py` with `reports/admission` missing: as written.

### As-written steps

- T1/S1: as written (baseline lines above; debt list inserted after the Plan F debt list, before
  `## Environment (observed)`; commit 760c93f). WA-1 applies to the live checkout.
- T1/S2: as written.
- T1/S3: as written (`1 error in`; `ImportError: cannot import name 'AdmissionSettings' from 'ops_core.settings'`).
- T1/S4: as written (`5 passed`).
- T1/S5: as written (`2 errors in`; `ModuleNotFoundError: No module named 'ops_api.limits'`).
- T1/S6: as written.
- T1/S7: as written (12 splices; `14 passed`; Plan D/F `157 passed`).
- T1/S8: as written apart from WA-2 (ruff clean; gates above).
- T2/S1: as written (`1 error in`, the module-level `REVISIONS` assert).
- T2/S2: as written (ISC004: `All checks passed!`, no change; `2 failed, 12 passed`, both `KeyError`).
- T2/S3: as written (`16 passed`).
- T2/S4: as written (`1 failed, 8 passed`, then `9 passed`).
- T2/S5: as written (`3 passed in 2.72s`).
- T2/S6: dev as written; live needed WA-3.
- T3/S1: as written (`1 error in`, `SYSTEM_MESSAGE_KINDS`).
- T3/S2: as written (`1 error in`, `ADMISSION_RULES`).
- T3/S3: as written (`44 passed`).
- T3/S4: as written (`import ops_core.routing` prints nothing; gates above).
- T4/S1: as written (`1 error in`, `No module named 'ops_api.idempotency'`).
- T4/S2: as written (`8 passed`).
- T4/S3: as written (both splices).
- T4/S4: as written (`1 error in`, `module 'ops_api.store' has no attribute 'AdmissionStore'`).
- T4/S5: as written (`20 passed`; Plan D/F `158 passed`).
- T4/S6: as written (mypy `Success: no issues found in 23 source files`; gates above).
- T5/S1: as written (`15 failed, 1 passed`).
- T5/S2: as written (15 splices; `16 passed`; Plan D/F `8 failed, 150 passed`).
- T5/S3: as written (13 splices; `242 passed`).
- T5/S4: as written (mypy success; `242 passed`).
- T5/S5: as written (8 splices).
- T5/S6: as written (gates above).
- T6/S1: as written (4 splices; `2 passed`).
- T6/S2: as written (`6 skipped`).
- T6/S3: as written (`6 passed`; evidence shapes exact).
- T6/S4: as written (`1 passed`; nine events ending `action.confirmed`).
- T6/S5: as written (gates above; WA-1 recurred; admission and R105 evidence committed).
- T7/S1: needed WA-4; otherwise as written (`git diff --stat handoff`: 3 files; the matrix diff touches only R015,
  R016, R017, R018, R115, R129).
- T7/S2: items 1, 3 and 4 as written; item 2 needed WA-5.
- T7/S3: STATUS.md, PROJECT_HISTORY (§24 inserted, §25 renamed), api/README.md, walking-skeleton.md (both `0005`
  occurrences found), dev-topology.md as written; README.md needed WA-6.
- T7/S4: as written (gates above; 40 step checkboxes ticked).
- T7/S5: as written (commit a4481f1).

### Clean-up proof

- Worktree removed: `git worktree remove --force C:/Users/joeys/Desktop/MLOps-dryrun-g` then `git worktree prune`;
  `git worktree list` shows only `C:/Users/joeys/Desktop/MLOps e09b004 [plan-g]` (no pre-existing others);
  `plan-g` is still at e09b004 with a clean `git status`; no `MLOps-dryrun*` directory remains on the Desktop.
- Skeleton status after removal: `incident-sim`, `mcp-read`, `mcp-write`, `api`, `worker`, `sweeper` all `down`.
- `critic_*`: 0 roles (`pg_roles`), 0 relations in the dev `ops` database; none were created.
- Dev databases untouched: `app.idempotency_request` does not exist in `ops` (still revision 0005); nothing ran
  `skeleton.py migrate`/`up` against `ops`/`incident`.
- Containers untouched: `ops-copilot-keycloak-1 Up 22 hours (healthy)`, `ops-copilot-postgres-1 Up 22 hours
  (healthy)`.
- NOT clean: `SELECT datname FROM pg_database` still lists `ops_test` and `incident_test`
  (`['incident', 'incident_test', 'ops', 'ops_test', 'postgres', 'template0', 'template1']`). The live fixtures
  recreate them at session start and never drop them; my `DROP DATABASE ... WITH (FORCE)` of the two was refused by
  the permission classifier, so they are left for the owner (both are disposable; the next live run drops and
  recreates them anyway).

## Rulings

## Round-1 rulings on the critic's findings (controller). The builder's workarounds are ruled in a second list below.

Every finding of `r1-critic.md` is accepted with the critic's "smallest fix" unless a line here says otherwise. The
fix agent applies them to the plan text (code blocks, rulings, tests, step splits) and keeps every plan line ≤ 120
characters; the plan's "Plan author's notes" section is replaced by a "Round 1 changes" section listing each ID and
the plan lines it touched.

- B1 (reply unit lock order): accepted. `DbUnit.record_reply` opens with `SELECT run_id, state, state_version,
  requester, conversation_id FROM app.runs WHERE run_id = %s FOR UPDATE` (api holds a column UPDATE on `runs`, so the
  lock is permitted; Plan E ruling 23), then the state/version/question checks, then messages → jobs → append_event →
  record. Ruling 15's text names the lock. Add a unit test on the fake unit that a run whose version moved is refused
  before any insert, and keep the SA:188 order sentence in the code comment.
- B2 (429 recorded): accepted. Ruling 5 changes: 429 is NOT recorded (it is transient; `Retry-After` promises a later
  success). The test becomes `test_a_full_tenant_queue_is_an_unrecorded_429_with_retry_after` and asserts a replay
  under the same key succeeds once the quota allows. Erratum text: AM-16's "nothing written except the idempotency
  record" covers the 409 and 422 rejections; a 429 writes nothing.
- I1 (anyone may answer a clarification): accepted. Only the run's `requester` may reply; a different subject gets
  404 "no such run" (existence is not disclosed; the record is written for the 404 as ruling 5 says). Unit + HTTP
  test with a second requester persona. Ruling 15 gains the sentence.
- I2 (disconnect mid-upload): accepted. `read_bounded` raises `BodyIncomplete` on `http.disconnect`; `BodyLimit`
  then returns without calling the inner app and without a response (the client is gone); the comment is rewritten;
  `test_limits.py` gains the disconnect case (inner app never runs).
- I3 (unroutable kind over HTTP): accepted. Parametrised `test_api_admission.py` case for `"delete"`, `""`,
  `"STATUS"` → 422 `INVALID_INPUT`, no message/run/job/record; one such POST in the live R129 test with a superuser
  count proving nothing was written.
- I4 (savepoint proof): accepted. The live race asserts `count(messages) == 1` for the conversation and exactly one
  409 record under the loser's key; both counts go to the evidence line.
- I5 (reviewer role after the record lookup): accepted. A `reviewer_mutation` dependency (`enabled_identity` +
  `who.require("reviewer")`, 403, unrecorded) runs before `idempotency_key` on the decisions route; the independence
  check stays inside the unit. Test: replay after `ROWS[SAM]` becomes `reader` → 403.
- I6 (replayed error request_id): accepted, option 1. A replayed error body (status ≥ 400) has its `request_id`
  rewritten to the current request's id before serialisation, so header, body and log line agree; success bodies
  carry no request id and replay byte-identical. Ruling 4 and the `test_error_surface.py` docstring say so; add a test
  that a replayed 409's body `request_id` equals the new `X-Request-Id` and differs from the first response's.
- M1: accepted (quote the real README tail).
- M2: accepted. The fault raises `psycopg.OperationalError("fault: drop_before_commit")` so the client sees
  `retryable: true`, matching a real lost connection; ruling 24 says so.
- M3: accepted (bind responses to locals before every assert).
- M4: accepted (the `created` fixture deletes `idempotency_request` rows by the test's keys in `finally`; the R016
  delete moves into a `finally`).
- M5: accepted. The scope lock uses the two-int form `pg_advisory_xact_lock(1, hashtextextended(<scope>, 0))` with
  the namespace constant `IDEMPOTENCY_LOCK_NAMESPACE = 1` in `idempotency.py`, documented in the erratum text as
  distinct from the asset guard's one-int key space.
- M6: accepted. A `question_id` that is a `clarification.requested` event of this run but not the latest → 409
  `VERSION_CONFLICT` "the clarification was superseded"; an id that is not an event of this run → 404.
- M7: accepted (nested `finally` so `forget` always runs).
- M8: accepted. Task 2 Step 4 becomes 4a/4b/4c; Task 5 Step 2 is split into one step per file touched (or per
  logical change), each with its own run line.
- M9: accepted. The `enabled_identity` and back-channel log lines carry the request id (`request.state.request_id`).

### Rulings on the builder's workarounds (`r1-builder.md`)

- WA-1: accepted. Every post-live `git checkout --` list in the plan names `reports/auth` beside `reports/bootstrap`
  and `reports/skeleton` (the live auth test rewrites its evidence file); the close-out's final checkout too.
- WA-2: accepted. The 120-character count commands exclude `pyproject.toml` (its line 53 predates Plan G and is not
  Python); the plan says so where the command appears.
- WA-3: accepted. Task 2 modifies `tests/e2e/test_sweeper_live.py` (the `purge_expired` assertion at line 130 gains
  the fourth key), and the live test seeds one expired `idempotency_request` row as the superuser and proves the
  purge deletes exactly it (count before/after), so the sweeper's new DELETE is proved live, not only counted.
- WA-4: accepted. The span command becomes `FIRST=$(git log --reverse --format=%h e09b004..HEAD | head -1)` with
  `e09b004` named as the plan commit, and the plan text explains the range excludes the plan and research commits.
- WA-5: accepted. The two executor instructions leave the verbatim `SESSION_STATE.md` block and become plan prose
  immediately above it ("when there were none, write the line … instead").
- WA-6: same fix as M1.
- T4 wording: "six helpers".

---

# Round 2

## Static review

## Plan G round 2: static adversarial critic

Verdict: REVISE (0 Blocking, 3 Important, 7 Minor). The splices, the gates and the arithmetic hold when
executed on scratch copies. Three real gaps remain: the text parser still guesses on some explicit time conflicts
(R018), the other-requester reply answers 404 where BS:301 asks for 403, and no test proves the write-then-refuse
savepoints against PostgreSQL.

Method: I read the whole plan (7863 lines), AM-10, AM-16, AM-20.1 to AM-20.6, AM-12 (SA:170-206), BS:262-302,
BS:508-521, BS:540-567, T12 and R015-R018/R115/R129 in `handoff/`, the fact sheet (§3.5, §3.6, §3.9, §4) and every
file the plan modifies. Out-of-repo verification (the repo itself was never touched):
`git archive HEAD` copies in the scratchpad, the plan's "Edit N (old lines a-b)" blocks spliced in by a script, and
its "Create"/"Replace" blocks extracted. I ran the repo's locked interpreter with `-S` and the copy's `src` dirs
first on `PYTHONPATH`, plus ruff 0.16.10 and mypy against the copies. Round-1 open points (a) 429 `retryable`,
(b) the close-out BASE and (c) riley for the live I1 proof are ruled and not reported.

### Blocking

None.

### Important

I1 — plan 287-297 (ruling 12), 2630-2658 (`TEXT_WINDOW`, `TEXT_WINDOW_WORD`, `text_window`), 2701-2711
(`resolve`), 2347-2416 (`test_text_and_fields`). The parser misses some explicit time conflicts and starts work
on the form's window. It knows only `last|past N hours|h|days|d` with N ≤ 3 digits, and "the first window in the
text counts". A text that names its window in any other way agrees with the form by default.
Evidence: on the spliced tree, `route_admission` returns `investigate, A17, 24` for each of these with form
`asset_id=A17, hours=24`:
- "Investigate A17 over the last 2 weeks."
- "... the last 30 minutes."
- "... the last 1000 hours."
- "... for the last 24 hours, not the past 6h."
With no form fields, "Compare the last 24 hours of A17 with the past 3 days." starts a 24 h run instead of asking.
That contradicts BS:297 ("If text and explicit asset/time conflict, ask for clarification rather than guessing"),
R018 ("ambiguity clarifies") and T12 DoD 4 ("conflicting text/fields yields a stored clarification … never a job").
It is also inconsistent with the asset rule, where two ids are `asset_ambiguous`. Ruling 12's cost-if-wrong
discusses only false-positive asset tokens.
Smallest fix:
- Widen `TEXT_WINDOW` to `(\d+)\s*(minutes?|mins?|m|hours?|hrs?|h|weeks?|wks?|w|days?|d)`; convert minutes to
  fractional hours and weeks × 168.
- A unit other than hours or days, or N outside 1-168, is `interval_conflict` when the form has hours and
  `interval_out_of_range` otherwise.
- Two or more distinct windows in the text are a new cause `interval_ambiguous`, mirroring `asset_ambiguous`. That
  is one `ClarifyCause` value and one template.
- Add rows for "last 2 weeks"/form 24 → `interval_conflict`, "last 30 minutes" → clarify, "last 1000 hours" →
  clarify, and the two-window text → `interval_ambiguous`.
- Recount Task 3, every later gate, and the overview arithmetic.

I2 — plan 316-318 (ruling 15), 4252-4263 (`check_reply_run`), 3970-3978
(`test_only_the_runs_requester_may_answer_its_question`), 5635-5642
(`test_another_requester_cannot_answer_the_runs_question`), Review Focus 5. Another requester of the same tenant
gets 404 "no such run", justified as "existence is not disclosed". The rationale is false in this tree:
`GET /api/v1/runs/{run_id}` (`api/src/ops_api/app.py:471-486`) and `/events` (`:538-550`) return any run of the
caller's tenant to any member, so casey can read the run whose question she is refused.
BS:301 maps exactly this case: "404 for inaccessible resource existence, 403 for a known permitted resource with a
disallowed operation". R115 requires the documented mapping.
Smallest fix:
- Split `check_reply_run`: `run is None` (absent, or another tenant under RLS) stays the recorded 404.
- `run["requester"] != requester` raises `Forbidden`, which propagates unrecorded like the decision route's
  independence check (ruling 5: a 403 is not recorded). The route maps it to 403 FORBIDDEN "only the run's requester
  may answer its question".
- Update the two tests (403, `len(fake.records)` unchanged), ruling 15's text and Review Focus 5.
- Test counts do not change.

I3 — plan 4915-4940 (`DbUnit.start_run`), 4972-4991 (`DbUnit.record_reply`), 3512-3517 and 3562-3564 (the
`FakeUnit` counterparts), 7176-7238 (live R017), 7296-7368 (live R129). AM-16 says a reject writes nothing except
the idempotency record. For SQL, that guarantee rests on two savepoints that roll back a message already written:
- the message plus `create_run` refused with SLOT_OCCUPIED or NotFound;
- the message plus a `resume_input` insert whose rowcount is 0 ("already answered").

No test exercises either rollback against PostgreSQL:
- The fake deliberately checks before it writes (fakes.py docstring: "the two 'savepoint' primitives check before
  they write"), so the unit tests cannot catch a regression that writes outside the savepoint.
- Live R017's loser is refused by the router's slot read or by `create_run`, nondeterministically; the comment at
  7197 says so.
- Live R129 posts one reply only.

A regression would commit a stray `clarification_reply` or `investigate` message beside a recorded 409/404, or
answer 503 (InFailedSqlTransaction on the record insert). R105's stale decision proves only the decision savepoint.
Smallest fix: add two deterministic live proofs to `test_admission_live.py`. They add no new test function, so the
counts do not change:
- In R129, after the accepted reply, post the same body under a new key. Expect 409 "the clarification was already
  answered", and the `clarification_reply` messages of the run's conversation counted as 1.
- In R016 or R017, post an investigate with `supersedes_run_id` set to a run of another conversation. The message
  is written, then `create_run` refuses with OC002. Expect a recorded 404 "no such superseded run", 0 messages in that
  conversation, and 1 record for the key.
- Add one evidence line each, and update Task 6 Step 3's expected file to twelve lines.

### Minor

M1 — plan 4021-4022 (Task 4 Step 4 expected output). It says `AttributeError: module 'ops_api.store' has no
attribute 'AdmissionStore'`. `tests/plan_g/fakes.py` imports `ReplyRefused` from `ops_api.store` first, at plan line
3367. The actual first failure is
`E   ImportError: cannot import name 'ReplyRefused' from 'ops_api.store'`, reproduced on the spliced Task-4 copy
(`1 error in`). The current round-2 dry run logged the same thing as WA-2. Fix: change the expected text.

M2 — plan 4037-4038 (`store.py` module docstring). It says "The one refusal a unit raises instead of recording is a
full tenant queue (`QueueFull`, 429)". `decide_once` raises `Forbidden` from inside its unit, unrecorded (4627,
4634-4639; ruling 21). `_idempotent` raises `IdempotencyConflict` on the re-read path (4384-4388). The docstring
therefore contradicts its code (CODE_COMMENTS checklist line 71). Fix: "Three refusals a unit raises instead of
recording: a full tenant queue (429, transient), a reviewer who is not independent (403, decided before the work)
and a key that is not reusable yet (409)".

M3 — plan 228-237 (ruling 5), 482-486 (erratum 39), 5471-5478 (test with the comment `# AM-16, SA:373`), 7337
(live comment). AM-16's reject row (SA:373) names "unroutable `kind`, over limits, or a second active run" with the
effect "nothing written except the idempotency record". The plan records the 409 slot reject and the
`kind=clarification` 422, but not an unroutable kind or an over-long text: the strict model refuses those as a body
parse. That is a reading of one spec row two ways, which the plan's own rule (190: "proposed to the owner as an
erratum") says must be an erratum. It is not among 35-43. Erratum 39's text even claims AM-16's clause "covers the 409
and 422 rejections". The tests cite SA:373 for the opposite of what it says.
Fix: add erratum 44 (SA:373: an unroutable `kind` and an over-limit text are refused by the strict request model as
an unrecorded 422 before the router; only the router's own rejects write a record). Reword erratum 39's sentence to
"covers the router's 409 and 422 rejections". Carry it into Task 7's SESSION_STATE block and the "Nine errata"
count. Alternatively, record those 422s.

M4 — plan 7459-7464 (Task 7 Files). `sweeper/README.md:7` says the sweeper owns "the purge of expired sessions,
login state and logout-token ids". After Task 2 it also purges idempotency records, and the close-out forgets that
line. Fix: add `sweeper/README.md:7` → "… login state, logout-token ids and idempotency records past their replay
window (T12)" to Task 7 Step 3 and the commit's `git add`.

M5 — plan 1135-1136 (`BodyLimit.__call__`). `declared.isdigit()` passes a Content-Length of more than 4300 digits,
and `int(declared)` then raises `ValueError` ("Exceeds the limit (4300 digits)", measured on Python 3.13). That
escapes the middleware into the catch-all: 503 `service error` plus a traceback, instead of the 422. uvicorn's
parsers probably reject such a header first, so this is defensive. Fix: `if declared is not None and (not
declared.isdigit() or len(declared) > 19 or int(declared) > self.max_bytes)`, plus one parametrised value in
`test_a_malformed_content_length_is_refused` (no count change).

M6 — plan 7384-7385 (live R115). `header = r.headers.get("X-Request-Id")` is then an operand of the assert
(`doc["request_id"] == header`). Global Constraints 59-60 and R105's own comment say live tests never put a header
in an assert operand. The request id is not a secret, but the rule is stated without exception. Fix:
`same = doc["request_id"] == header` before the assert, and assert `same`.

M7 — plan 7515-7533 (Task 7 matrix rows), 392-401 (ruling 24), 463 (debt line). R015's expected evidence is "Kill
around admission commit; every acknowledged run has message/run/job". The plan proves the before-commit side (a
raised OperationalError inside the unit). It then marks R015 `RECORDED_LOCALLY_LIVE` with the generic note.
`FaultKind.LOSE_AFTER_COMMIT` already exists in `core/src/ops_core/testing/faults.py:20`, and the debt line defers it
to T13 without saying R015 relies on R016 for the after-commit side. Fix: give R015 its own `notes` entry. Example:
"before-commit crash proved with the drop_before_commit fault; the after-commit side (ack lost, retry replays the
recorded 202) is R016's replay; the lose_after_commit fault arrives with T13".

### Checked and passed

Spec (hunt 1):
- AM-16's six routes and their effects: investigate/readonly through `create_run` with `intent`; status and
  clarify as two messages with no run, job or event; the slot reject before every clarify row (T12 review note 2);
  the hint can only produce clarify (SA:375).
- The clarification_reply entry and its erratum 40.
- SA:188's lock order: scope advisory → runs FOR UPDATE (reply) → messages → jobs → events → record last. I found no
  lock cycle between admission, reply, worker transition and cancel. The two-key advisory space cannot collide with
  the asset guard's one-key locks, and no other advisory lock exists in the repo.
- AM-20.2:
  - `api` inserts jobs blind (no target, no RETURNING) and never updates conversations or messages.
  - `api` locks a run only through its `cancel_requested` column grant (FOR UPDATE needs UPDATE on one column).
  - The sweeper holds sel+del on the record table (erratum 36).
  - The record table is in `NO_RLS` (SA:523).
- AM-20.5 RLS scopes every tenant read in the units.
- BS:299: the accepted body's keys; success only after commit (the response is built after `unit` exits); same
  key and body replay, different body → 409.
- BS:301: all seven codes, apart from I2.
- BS §17: body 64 KiB, text 4000, hours 1-168, the tenant quota with the global bound declared as debt.
- T12 DoD 1-4, the review notes, R015-R018, R115, R129 (admission half; R098's T10/T13 precedent for a
  shared-owner row).

Security (hunt 2):
- The scope carries tenant and subject, so no record crosses subjects. Identity, CSRF and role run before the
  lookup, so revoked or demoted members cannot replay.
- The fingerprint covers path and validated body.
- Chunked, lying-low and malformed Content-Length bodies, and a mid-body disconnect, are handled; each request on a
  keep-alive connection has its own scope.
- A 23505 never reaches a client: the record and job inserts are target-less ON CONFLICT, and every other psycopg
  error is mapped to 503 "service error" with only the class name logged.
- The fault route exists only when `Faults(Profile.TEST)` succeeds. `production_app` passes `settings.profile()`.
- The evidence file holds no id of the second tenant and no secret.
- `hashtext` collisions only serialise two transactions; the lookup is by the full scope.

Splices (hunt 3):
- All 73 "Edit N (old lines a-b)" blocks match the cited lines exactly, and each old text occurs exactly once in the
  file as the previous task left it (scripted check on the spliced copies).
- Every name a later task uses is defined earlier with the same signature: mypy strict reports `Success` on all
  member sources after Tasks 1, 2, 3, 4 and 6, and "23 source files" for Task 5 Step 4's command.
- Every psycopg call uses `Session.unit` (`conn.transaction()`, so nested blocks are savepoints).
- Alembic resolves the downgrade to 0005 from heads {0006, tc_0001} to removing only 0006.

Tests (hunt 4):
- No `await` inside a comprehension or generator.
- No secret in an assert operand; only the request-id header, M6.
- Live cleanup:
  - `created` purges conversations and deletes the records by key.
  - The expired record is deleted in a `finally`.
  - The test clock is reset in a `finally`.
  - Nested `finally` in the 0006 round trip.
  - The admission module runs before the R006 downgrade.
  - The sweeper live count tolerates earlier records.
- R129's walk reaches all six routes through both tables (unit and live).
- Negative cases exist for every route and for all seven status codes (unit).

Gates and arithmetic (hunt 5), unit suite on the spliced copies:

| After Task | passed / skipped (unit) | Live gate |
|---|---|---|
| 1 | 699/95 | 773/21 |
| 2 | 704/98 | 781/21 |
| 3 | 730/98 | — |
| 4 | 752/98 | 829/21 |
| 5 | 774/98 | 851/21 |
| 6 | 774/104 | 857/21 |

- The unit counts exclude 12 pre-existing failures that need `.git` and the handoff zip; the untouched baseline copy
  has the same 12. The live column is the stated arithmetic: unit count plus 74, 77 or 83 live tests.
- Step-level expectations reproduced: Task 1's "15 passed" and "157 passed", Task 5's "21 failed, 1 passed",
  "8 failed, 150 passed", "22 passed" and "251 passed", and per-module counts (5, 8, 7, 3, 26, 8, 14, 22, 11,
  6 live, 3 live).
- ruff check and ruff format are clean on the whole copy after Task 6. No line is over 120 characters, counted as
  characters.
- No schema drift: `tests/plan_c/test_schemas_generated.py` and `test_schema_conformance.py` pass.
- `verify_handoff.py --reference-code --manifest --contracts` passes with Task 7's JSON rewrite applied (stub span).
  That rewrite changes exactly the six matrix rows and T12.

Process (hunt 6):
- One commit per task, and each `git add` lists exactly the task's files.
- No placeholders beyond `<date>`/`<first>..<last>`, each defined with its command.
- Docstrings on every new module, class and public function in `src/`. The test fakes' members follow Plan D's
  undocumented-fake precedent.
- `README.md:5`, `api/README.md`, `walking-skeleton.md:21,43` and `dev-topology.md` are updated by Task 7. The
  sweeper README is missed (M4).

## Builder dry run

## Plan G dry run, round 2 — builder report

Plan: `docs/superpowers/plans/2026-10-10-first-slice-g-admission-idempotency.md` at `plan-g` fd4b880 (round-1 fixes).
Worktree: `C:/Users/joeys/Desktop/MLOps-dryrun-g`, detached at fd4b880, fresh `uv sync --locked`, `.env` copied.
Date: 2026-10-10. Every code block was extracted from the plan by line range (no retyping drift); every edit was an
exact-once text replacement of the plan's "replace" block, and each one matched.

### Summary

- Tasks reached: all seven (T1-T7), every step executed, every gate run.
- Workarounds: 3 in total — T1: 1 (WA-1), T4: 1 (WA-2), T7: 1 (WA-3, the already-ruled close-out span; listed for
  completeness only). T2, T3, T5, T6: 0.
- Every expected count matched exactly at every step and every gate.

Gate tails (pytest line, then the check line):

| When | `check.py` (dev) | `check.py --profile test` (live) | verify_handoff |
| --- | --- | --- | --- |
| Baseline (T1/S1) | 679 passed, 95 skipped / CHECK: GREEN | 753 passed, 21 skipped (191.98s) / GREEN | - |
| After T1 | 699 passed, 95 skipped / GREEN | 773 passed, 21 skipped (198.26s) / GREEN | exit 0 |
| After T2 | 704 passed, 98 skipped / GREEN | 781 passed, 21 skipped (193.75s) / GREEN | exit 0 |
| After T3 | 730 passed, 98 skipped / GREEN | not required by the plan | exit 0 |
| After T4 | 752 passed, 98 skipped / GREEN | 829 passed, 21 skipped (194.26s) / GREEN | exit 0 |
| After T5 | 774 passed, 98 skipped / GREEN | 851 passed, 21 skipped (197.18s) / GREEN | exit 0 |
| After T6 | 774 passed, 104 skipped / GREEN | 857 passed, 21 skipped (197.00s) / GREEN | exit 0 |
| T7 final | 774 passed, 104 skipped / GREEN | 857 passed, 21 skipped (197.42s) / GREEN | exit 0 |

Other run lines: T4/S6 and T5/S4 `mypy core/src api/src --no-incremental` → `Success: no issues found in 23 source
files`; T6/S3 live admission `6 passed in 3.84s`; T6/S4 R105 `1 passed in 29.73s` (nine events ending
`action.confirmed`); T7/S1 printed `fd4b880..9fdfb5f`, `git diff --stat handoff` 3 files, the matrix diff the six
rows only.

### Workarounds

WA-1 — T1/S8 (the counting command; the Global Constraints' "Counting characters") — the plan passes
`core/src/ops_core/settings.py api/src/ops_api/limits.py api/src/ops_api/app.py tests/plan_g` to the counting
script — `tests/plan_g` is a directory and `open()` fails: `PermissionError: [Errno 13] Permission denied:
'tests/plan_g'` — ran it with `tests/plan_g/*.py` instead; no output (every file passes). `ruff format` and
`ruff check --fix` accept the directory; only the counting command does not. No later task names a directory.

WA-2 — T4/S4 (the failing unit tests) — expected `1 error in` with `AttributeError: module 'ops_api.store' has no
attribute 'AdmissionStore'` — actual `1 error in 1.03s` with `E   ImportError: cannot import name 'ReplyRefused'
from 'ops_api.store'` (`tests/plan_g/fakes.py` line `from ops_api.store import Accepted, Conflict, Decided,
LoginState, NotFound, ReplyRefused, SessionRow` fails before the class body reaches `store.AdmissionStore`; the
round-1 B1 change added `ReplyRefused` to that import) — continued; still red for the right reason, and Step 5 turns
it green as written (`22 passed`).

WA-3 — T7/S1 and S2 (the close-out span) — the plan says `e09b004..HEAD` starts at Task 1 Step 1's debt-list
commit — on this branch it starts at fd4b880 (the round-1 plan-fix commit): the script printed `fd4b880..9fdfb5f`,
and `FIRST=$(git log --reverse --format=%h e09b004..HEAD | head -1)` gave `fd4b880` — used the values as printed.
This is round-1 open point WA-4, already ruled (b: a BASE recorded before Task 1); listed here only so the count is
honest, not as a new finding.

### As-written lines

- T1/S1: as written (baseline 679/95 and 753/21 GREEN; reports checked out; debt section placed after
  `## Plan F debt list …`, before `## Environment (observed)`; committed).
- T1/S2: as written.
- T1/S3: as written (`1 error in`, ImportError `AdmissionSettings`).
- T1/S4: as written (`5 passed`).
- T1/S5: as written (`2 errors in`, both ModuleNotFoundError `ops_api.limits`).
- T1/S6: as written.
- T1/S7: as written (all 14 app.py edits matched; `15 passed`; `157 passed`).
- T1/S8: gates as written apart from WA-1; committed.
- T2/S1: as written (`1 error in`, the module-level `REVISIONS` assert).
- T2/S2: as written (ISC004 changed nothing; `2 failed, 12 passed`, both `KeyError: 'idempotency_request'`).
- T2/S3: as written (`16 passed`).
- T2/S4a: as written (`1 failed, 8 passed`).
- T2/S4b: as written (`9 passed`).
- T2/S4c: as written (`158 passed`).
- T2/S5: as written (`7 passed in 2.93s`).
- T2/S6: as written.
- T3/S1: as written (`1 error in`, ImportError `SYSTEM_MESSAGE_KINDS`).
- T3/S2: as written (`1 error in`, ImportError `ADMISSION_RULES`).
- T3/S3: as written (`44 passed`; GraphRoute, ModelRoute and RunManifest kept unchanged).
- T3/S4: as written (`import ops_core.routing` prints nothing).
- T4/S1: as written (`1 error in`, ModuleNotFoundError `ops_api.idempotency`).
- T4/S2: as written (`8 passed`).
- T4/S3: as written (both edits matched).
- T4/S4: see WA-2.
- T4/S5: as written (`22 passed`; `158 passed`).
- T4/S6: as written.
- T5/S1: as written (`21 failed, 1 passed`).
- T5/S2a: as written (`21 failed, 1 passed`).
- T5/S2b: as written (`21 failed, 1 passed`).
- T5/S2c: as written (`22 passed`; `8 failed, 150 passed`).
- T5/S3: as written (`251 passed`).
- T5/S4: as written (mypy `Success: no issues found in 23 source files`; `251 passed`).
- T5/S5: as written (all eight live-module edits matched).
- T5/S6: as written.
- T6/S1: as written (`2 passed`).
- T6/S2: as written (`6 skipped`).
- T6/S3: as written (`6 passed`; header plus ten lines, every count and status exactly the plan's shapes; R018
  `ahead` = `1:59:59.641477`; a superuser probe after the run found 0 records, 0 system messages, 0 conversations,
  0 runs and `clock_offset` 0 in `ops_test`).
- T6/S4: as written.
- T6/S5: as written (the live gate rewrote both evidence files; committed as the step says).
- T7/S1: as written apart from WA-3.
- T7/S2: as written (no SDD ledger exists, so the two closing bullets are "none beyond the plan" / "none recorded").
- T7/S3: as written (README tail, api/README section, both 0005→0006 lines, dev-topology section, history §24 with
  "Execution found nothing the plan had not ruled on." and §25 renamed).
- T7/S4: as written (44 checkboxes ticked, 0 left).
- T7/S5: as written (7f86244).

### Review findings (fresh eyes; not workarounds — every step ran as written)

The three ruled open points (429 `retryable`, the BASE span, riley as the second live requester) are not repeated.

1. Important — ruling 12 / Task 3: `TEXT_WINDOW`'s `(\d{1,3})` makes a window of four or more digits invisible
   instead of out of range. Measured: "Investigate A17 over the last 1000 hours." with form A17/24 routes
   `investigate` with 24 hours (the text disagrees and work starts anyway, against BS:297/R018); with no form window
   the cause is `missing_interval`, not `interval_out_of_range`. `\d+` (and the range check) would close it; a row
   "last 1000 hours" with form 24 → `interval_conflict` would pin it. (Phrasings the parser does not read at all —
   "the last 24-hour window", "the previous 48 hours", "two days" — are the accepted cost of a deterministic parser
   but also silently let the form win; the ruling's "Cost if wrong" should say so.)
2. Important — round-1 B1 pin: `test_the_reply_locks_the_run_before_it_checks_or_writes` asserts `fake.locks[-2:]
   == [scope, "run <id>"]`, but the `"run <id>"` entry is written by `FakeUnit.record_reply` itself, so the test
   proves the fake's own bookkeeping, not that `DbUnit.record_reply` issues `FOR UPDATE` before its checks; nothing
   live races a cancel or a worker transition against a reply either. The lock order of the real unit is proved by
   reading only.
3. Minor — ruling 24 says the live R015 test proves "no message, run, job or record"; the test counts messages,
   runs and records (`left == [0, 0, 0]`) but never the jobs table before the retry.
4. Minor — ruling 15's text says the run lock is "the unit's first table statement" after the advisory lock and the
   record lookup; the lookup itself (`find_record`) is a table statement on `app.idempotency_request`. Wording only.
5. Minor — Task 7: `SESSION_STATE.md`'s `**Repository:**` line still says branch `plan-f`; the plan updates the
   "Next task" line only. The Plan G block says `(STATUS.md, "Update - Plan G executed")` with a hyphen while the
   STATUS heading the plan writes uses an em dash.
6. Minor — Task 7 Step 4 says to commit `reports/admission` and `reports/skeleton` "only if the live run changed
   them"; the live gate always rewrites both (timestamp, run ids), so the condition is always true and the close-out
   commit always replaces the evidence Task 6 committed.
7. Minor — the evidence file's R016, R017, R018 and R129 lines run to about 200 characters (the plan says so in
   Task 6 Step 3); fine for evidence, but the global "≤120 characters per line" reads as if it applied to every file.

### Clean-up proof

- Skeleton before every live run and at the end: `incident-sim, mcp-read, mcp-write, api, worker, sweeper` all
  `down`.
- Test databases dropped as the superuser (`DROP DATABASE IF EXISTS ops_test WITH (FORCE)`, then `incident_test`);
  `SELECT datname FROM pg_database ORDER BY 1` → `incident, ops, postgres, template0, template1`.
- Dev database untouched: `ops` `public.alembic_version` = `0005_sessions_login_logout`,
  `to_regclass('app.idempotency_request')` = NULL.
- No `critic_*` objects: `pg_roles` and `pg_database` `LIKE 'critic%'` empty, and none in `ops_test`'s `pg_class`
  before the drop. This run created none.
- Worktree removed (`git worktree remove --force C:/Users/joeys/Desktop/MLOps-dryrun-g`, `git worktree prune`);
  `git worktree list` → `C:/Users/joeys/Desktop/MLOps fd4b880 [plan-g]` only; `plan-g` still at fd4b880, main tree
  clean; the commits made in the detached worktree (8f6a63f..7f86244) went with it.
- Keycloak and PostgreSQL containers left up and untouched; no realm, role, secret or system setting changed; no
  secret value was read or printed (the probe script used `settings.superuser_postgres()` and printed rows only).

## Rulings

## Round-2 rulings (controller). Pre-seeded with the round-1 open points; the round-2 findings are ruled below them.

### Carried from round 1's open points

- OP-429: the 429 `RATE_LIMITED` answer carries `retryable: true` (its `Retry-After: 5` promises a later success);
  ruling 19's list of retryable responses gains it, with the sentence "a 429 is the one client-side retryable refusal".
  The unit test asserts `retryable is True` on the 429 body.
- OP-BASE: the executor records `BASE=$(git rev-parse HEAD)` before Task 1's first commit, in the SDD ledger and in
  the plan's Task 1 Step 1 text; the close-out's commit span is `<BASE>..HEAD` written as the two short hashes, so a
  plan-revision commit after the plan commit never lands inside the executed range. WA-4's `git log --reverse` form
  is removed.
- OP-RILEY: the live I1 proof uses the realm persona `riley` (a second `requester`, `deploy/dev/keycloak/
  realm-ops-dev.json`) with a token from the direct grant like `alex`'s; the fake-only `CASEY` stays for the unit
  test. The evidence line names the 404 by status only.
- OP-HASH: `pg_advisory_xact_lock(1, hashtext(<scope>))` (two `int4` arguments) is accepted; erratum 37 says
  "namespace 1, `hashtext`".
- The other round-1 open points (pure check functions shared by the units, no `tenant_id` filter under the tenant
  unit, the "failed" log texts, ten evidence lines, the HTTP-only pin of `replay()`) are accepted as applied.

### Rulings on the round-2 critic's findings (`r2-critic.md`): all accepted with the critic's smallest fix

- I1 (window parser): accepted. `TEXT_WINDOW` recognises `(\d{1,4})\s*(minutes?|mins?|m|hours?|hrs?|h|days?|d|
  weeks?|wks?|w)` after `last|past`, plus the word forms `last hour|day|week`; minutes convert to hours only when
  divisible by 60 (otherwise the window is outside 1–168), days × 24, weeks × 168. A converted window outside 1–168 is
  `interval_conflict` when the form has hours and `interval_out_of_range` otherwise; two or more distinct windows are
  the new cause `interval_ambiguous` (template: "The request names more than one window ({windows}); which one is
  meant?"), mirroring `asset_ambiguous`. Table rows and tests for the critic's five texts; recount Task 3 and later.
- I2 (another requester answers): accepted. Absent run (or another tenant under RLS) → recorded 404; a run of the
  caller's tenant whose `requester` is someone else → unrecorded 403 `FORBIDDEN` "only the run's requester may
  answer its question" (BS:301's "known permitted resource with a disallowed operation"); ruling 15, Review Focus 5,
  the unit test, the HTTP test and the live I1 proof with `riley` change to 403.
- I3 (savepoint rollbacks unproved in PostgreSQL): accepted. Two deterministic live proofs added to the existing
  tests (no new test function): (a) after the accepted clarification reply, the same body under a new key → 409
  "the clarification was already answered" and exactly one `clarification_reply` message in the conversation;
  (b) an investigate with `supersedes_run_id` naming a run of another conversation → recorded 404, zero messages in
  that conversation, one record under the key. Two evidence lines; the expected evidence file has twelve lines.
- M1: accepted (expected text is the ImportError).
- M2: accepted (docstring names the three unrecorded refusals).
- M3: accepted. Erratum 44 added (SA:373: an unroutable `kind` and an over-limit text are refused by the strict
  request model as an unrecorded 422 before the router; only the router's own rejects write a record); erratum 39
  reworded to "covers the router's 409 and 422 rejections"; the close-out's SESSION_STATE block and the errata count
  (ten) updated.
- M4: accepted (`sweeper/README.md:7` gains the idempotency purge; Task 7 Step 3 and its `git add`).
- M5: accepted (`len(declared) > 19` guard and one parametrised value).
- M6: accepted (`same = doc["request_id"] == header` before the assert).
- M7: accepted (R015 gets its own matrix note naming the before-commit fault, the after-commit side as R016's replay,
  and `lose_after_commit` arriving with T13).

### Rulings on the round-2 builder's workarounds and items (`r2-builder.md`)

- WA-1: accepted; the counting command lists `tests/plan_g/*.py` (and the same for any other directory argument).
- WA-2: same as critic M1.
- WA-3: covered by OP-BASE.
- Window parser: covered by critic I1 (digits `\d{1,4}`, units, `interval_ambiguous`).
- B1 lock-order test: accepted. `test_store_units.py` gains a deterministic test of the real `DbUnit.record_reply`
  over a recording fake connection (an object whose `execute` appends the SQL text and returns a scripted row/
  rowcount from a queue, the AWAITING_INPUT run first): the first statement executed must contain `FOR UPDATE` on
  `app.runs`, and with a scripted version mismatch no INSERT is ever executed. The fake-unit test that checked the
  fake's own `"run <id>"` entry is removed. No timing-based live test.
- R015 live test: accepted; the test counts messages, runs, jobs and records (all zero) after the 503 and before the
  retry, and the job row (one) after the 202; both counts go to the evidence line.

---

# Round 3

## Static review

Verdict: CLOSED. The plan is executable as written: 0 Blocking, 0 Important, 8 Minor, and no workaround was needed.

## Plan G round 3 (closure): static critic

Plan: `docs/superpowers/plans/2026-10-10-first-slice-g-admission-idempotency.md` on `plan-g` (HEAD e11e601), 8154
lines, read in full. Specs read: SA AM-10 (SA:135, :145), SA:157, SA:186-189, AM-16 (SA:360-377), AM-20.2
(SA:405-435), AM-20.3 rows create_run/append_event/record_decision, AM-20.4 (SA:501), AM-20.5 (SA:520-529), SA:539-549,
SA:564, BS:230, BS:244, BS:262-302, BS:405, BS:466, BS:508-521, BS:540-567, BS:681, T12 in `handoff/tasks.json`, and
R015-R018, R115, R129 in the acceptance matrix. Also read: the fact sheet, the spike summary, §5, §9 and the gotchas,
and every file the plan modifies, at the cited lines.

Method beyond reading. Everything below ran outside the repository, in the scratchpad (`plang/r3x/`). The repository
was not edited and no database was touched.
- I extracted all 185 fenced blocks and applied every Create and every Modify of Tasks 1-6 to a copy of the tree.
  Each Modify's old text was checked against the file as the previous task left it.
- I ran the plan's own unit tests and gates on that copy: ruff check, ruff format --check, mypy strict and pytest.
- I rebuilt three intermediate states (after Task 1, after Task 4 and at Task 5 Step 2c) to check the expected
  counts the plan states at those points.
- The live tests could not run. They were read against the SQL functions, the grants and the RLS policies.

### Blocking

None.

### Important

None.

### Minor

M1. The parser does not read months, years, seconds or "fortnight".
- Plan lines: ruling 12 (295-313); `TEXT_WINDOW` in routing.py (2714-2716); Review Focus 4 (174-178).
- What is wrong: the ruling says "every unit a person writes is read". The unit alternation stops at weeks, so
  months, years, seconds and "fortnight" match nothing, and the form's window then wins silently.
- Evidence: I ran the plan's `route_admission` on the copy with form `{asset_id: A17, hours: 24}`.
  - "Investigate A17 over the last 6 months." routes to `investigate` with 24 hours.
  - "... last 2 years", "... last 90 seconds" and "... last fortnight" route the same way.
  - "... last 3 M" is read as 3 minutes.
  - BS:297 says "If text and explicit asset/time conflict, ask for clarification rather than guessing", and R018
    expects "ambiguity pauses". A UI that pre-fills 24 hours makes this case likely.
- Smallest fix: add `months?|mos?|years?|yrs?|seconds?|secs?` to `TEXT_WINDOW`, keyed by the full unit rather than
  its first letter, so these become `interval_conflict` or `interval_out_of_range`. Add one `test_text_and_fields`
  row. Alternatively, narrow the ruling's "every unit" claim and name these units in its cost sentence.

M2. The test-profile fault route skips the CSRF and origin check.
- Plan lines: Task 5 Edit 9 (6019-6032).
- What is wrong: `arm_fault` depends on `identity`, not `browser_mutation`. Under `PROFILE=test`, a cookie-mode POST
  without a CSRF token or a matching Origin can arm `drop_before_commit`. The route exists only in the test profile.
- Evidence: BS:264 requires CSRF/origin protection in cookie mode on every mutation. Erratum 35 exempts this route
  from the Idempotency-Key only, not from CSRF.
- Smallest fix: `_: Annotated[Identity, Depends(browser_mutation)]`.

M3. `psycopg.OperationalError` covers more than a lost connection.
- Plan lines: ruling 19 (376-379); Task 1 Edit 10, the `_database_down` comment (1403-1405).
- What is wrong: the comment says "the connection is gone or refused". Every error in the evidence below is answered
  503 "database unavailable" with `retryable: true`. For deadlocks and timeouts that is right; for SQLSTATE classes
  53 and 54 it is not.
- Evidence: I checked the class hierarchy of psycopg 3.3.6. These are all `OperationalError` subclasses:
  `DeadlockDetected`, `SerializationFailure`, `QueryCanceled`, `LockNotAvailable`, `ProgramLimitExceeded`,
  `DiskFull`, `StatementTooComplex`. BS:562 says not to retry what is not transient.
- Smallest fix: reword the comment and the ruling to "a lost connection or a transient server condition". Optionally
  route `ProgramLimitExceeded` and `StatementTooComplex` to `_server_defect`.

M4. One mypy run states no expected output.
- Plan lines: Task 4 Step 6 (5461-5462).
- What is wrong: "`uv run mypy core/src api/src --no-incremental` once" has no expected result. Task 5 Step 4 states
  one for the same command.
- Evidence: on the Task 4 state of the copy, mypy strict over core+api reported `Success: no issues found in 23 source
  files`.
- Smallest fix: add "Expected: `Success: no issues found in 23 source files`".

M5. The R018 evidence shape fixes a seconds digit that can vary.
- Plan lines: Task 6 Step 3 (7611-7612, 7623).
- What is wrong: the shape "R018 window ends 1:59:59.<µs>" is presented as fixed. `end_at` is truncated to whole
  seconds (`resolve_interval`) and the read follows a few milliseconds later. So `ahead` is 1:59:58.9xx whenever the
  admission's fractional second was above about .99.
- Evidence: the test itself accepts anything from 1:59 to 2:01 (7446).
- Smallest fix: write the shape as "1:59:5x.<µs>". Self-review 2 (8030-8031) should say "seconds and microseconds
  vary".

M6. The new README status sentence says the dev realm carries durable admission.
- Plan lines: Task 7 Step 3, README line 5 (7909-7918).
- What is wrong: after the replacement, the clause reads "the dev realm now carries the Plan F clients (re-imported on
  `up`), and durable admission with a scoped Idempotency-Key and the AM-16 router (T12)".
- Smallest fix: replace the tail with "; durable admission with a scoped Idempotency-Key and the AM-16 router (T12)
  runs locally". This keeps the semicolon structure.

M7. The PROJECT_HISTORY edits address sections by number and leave out the planning rounds.
- Plan lines: Task 7 Step 3 (7876-7907).
- What is wrong: the step renames "## 24. What the process taught" and inserts a §24 before it. The template has no
  record of the planning review rounds.
- Evidence: in Plan F, those rounds were written by a separate commit (f7b5114, "adversarial review record (four
  rounds) and the history story (section 22)") before execution. If Plan G's record commit lands first, the literal
  rename no longer matches, and the executor improvises. The user's standing rule is that every review round's
  problems and fixes go into docs/PROJECT_HISTORY.md.
- Smallest fix: address both sections by name: insert before "What the process taught", which takes the next number.
  State whether rounds 1-3 (2/6/9, then 0/3/7, then this round) go into the new section here or into the record
  commit.

M8. Two small process and comment gaps.
- `VerdictResponse.render` (3321-3322) is a public override with no docstring (docs/CODE_COMMENTS.md rule 9). Smallest
  fix: add one line, for example "Every verdict body is serialised by `render`, sorted and compact (ruling 4)."
- Task 1 Step 1 (604-625) does four things in one step: the dev gate, the live gate, the BASE record and the debt-list
  commit. Smallest fix: split it into 1a (both baselines), 1b (BASE) and 1c (the debt list and its commit), so a
  failed gate cannot be mistaken for a half-done debt commit.

### Checked and passed

#### 1. Spec contradictions: none found

- AM-16's six routes and their effects (SA:366-373) match rulings 13-16, `ADMISSION_RULES` / `REPLY_RULES` and
  `AdmissionStore`:
  - investigate and readonly_answer go through `create_run` with their intent, as one transaction, and answer 202;
  - status_question writes two messages and no run, job or event;
  - clarify writes the requester's row plus a `clarification_question` row and answers 200;
  - reject is a recorded 409 or 422, with nothing else written (a savepoint takes back the message);
  - clarification_reply writes the message and a `resume_input` job. The extra `clarification.received` event is the
    "clarification event" SA:135 expects to be committed before resume.
- The slot rule runs before every clarify row (SA:372, T12 review note 2), and the hint can only produce clarify
  (SA:375).
- SA:188 lock order:
  - the scope's advisory lock comes first, as erratum 37 states;
  - the reply unit then takes `runs FOR UPDATE` before messages, the job and events;
  - the record is written last, before commit;
  - `append_event` re-takes a run lock the unit already holds.
- The advisory lock is the two-key int4 form. PostgreSQL keeps that lock space apart from the asset guard's one-key
  int8 locks (SA:189).
- AM-20.2, statement by statement: every statement is within its role's grants.
  - `api`:
    - SELECT and INSERT on the record; no UPDATE or DELETE (the live test proves 42501 for both);
    - INSERT-only on jobs, through a target-less `ON CONFLICT DO NOTHING` with no `RETURNING` (spike §2);
    - SELECT and INSERT on conversations and messages, and no UPDATE on either;
    - `runs FOR UPDATE`, allowed by its column UPDATE grant and the FOR ALL tenant policy;
    - EXECUTE on `current_time`, `create_run`, `append_event` and `record_decision`.
  - The sweeper holds SELECT and DELETE (erratum 36).
  - The worker gets 42501 on the record table (live test).
- AM-20.5 / SA:523: `idempotency_request` is in `NO_RLS` and owned by migrator. R106 and R124 compare it to the
  matrix (`actual_privileges` handles table-level grants on the new `messages.seq`).
- BS:299:
  - the accepted keys match, with `stream_url` declared as debt for T27;
  - success is returned after the commit (the unit exits before `response()`);
  - same key and body replay, and a different body is 409.
- BS:301 status mapping:
  - 401 identity, 403 role or independence, 404 not visible, 409 version or key, 422 shape or limits, 429 capacity,
    503 outage;
  - 405 is covered by erratum 43;
  - the safe schema holds everywhere, with no unauthorised ids.
- BS §17 limits: 4,000-character Text, a 64 KiB body, 1-168 hours, one run per conversation, and the tenant quota
  under erratum 39.
- T12 definition of done items 1-4 and both review notes are met.
- The requirements are mapped as follows:
  - R015: Task 6 live, plus units;
  - R016: replay, conflict and the expired-record path;
  - R017: the two-connection race, the same-key race and the status question;
  - R018: the clock at +2 hours and +3 days, plus the stored clarification;
  - R115: the unit tests reach every code, and the live sample is safe-schema only;
  - R129: every row is first for its sample, all six routes are reached, unroutable kinds get 422, and the hint only
    clarifies.
- Marking R129 IMPLEMENTED for T12's half follows the R098 precedent (T10 marked its half with T13 pending).

#### 2. Security: nothing leaks

- Scope and fingerprint:
  - The scope is (tenant, subject, route template, key). A record cannot reach another subject or tenant, and a
    DUAL-tenant subject is 401.
  - The fingerprint covers the path ids and the validated body. Defaults such as `supersedes_run_id: null` are
    included, so omitting a field and sending null are the same request. No query string feeds any of these routes.
- Check order:
  - identity, CSRF and the role all run before the key and the record;
  - a revoked member gets 401 on replay, and a demoted reviewer gets 403 (tests at 5749-5772);
  - reviewer independence runs inside the unit but cannot change between recording and replay.
- Replayed errors carry the replaying request's id; successes carry none.
- 23505 never reaches a client:
  - the record and job inserts use target-less `ON CONFLICT DO NOTHING`;
  - the slot violation is mapped inside `create_run` (constraint name checked);
  - any other psycopg error is logged by class name only (canary tests at 978-1021).
- Body limit:
  - a declared length over the limit, or one that is malformed (`-1`, `1e3`, empty, `12 34`, 4,400 digits), is
    refused unread;
  - a chunked body or one with a lying-low Content-Length is counted;
  - a disconnect mid-body reaches no route;
  - every request is pre-read, so a route that reads no body (conversations) is covered too;
  - each ASGI request has its own scope, so pipelining cannot carry an earlier body.
- Request ids are server-made; a client-sent `X-Request-Id` is ignored.
- Lock collisions: `hashtext` collisions across tenants only make two scopes wait for each other. The lookup is by the
  full primary key, so no answer can cross over.
- The fault route is registered only when `profile is Profile.TEST`, `Faults()` refuses any other profile, and a test
  asserts the 404 elsewhere. See M2 for its CSRF gap.
- The test-only admin client is not touched by this plan.
- The evidence file carries statuses, counts and causes only. Riley appears only as a status code, and
  `test_evidence.py` scans `reports/admission`.

#### 3. Code splices: all 72 old-text blocks match exactly once

- Every Create and Modify block was applied mechanically:
  - app.py: 14 edits in Task 1, 1 in Task 2 and 15 in Task 5;
  - store.py: 2; persistence.py: 2; contracts.py, settings.py, sweeper `main.py`: 1 each;
  - privileges.py: 3; sync.py: 2; pyproject.toml: 1;
  - plan_d `test_api.py`: 11; plan_f `test_api_auth.py`: 2; `test_sweeper.py`: 2; `test_transitions_table.py`: 1;
  - the e2e sweeper test: 1; R105: 4; auth live: 4; conftest: 2; `test_evidence.py`: 2.
- Each block matched exactly once, at exactly the cited lines of the file as the previous task left it.
- The prose anchors for SESSION_STATE, README:5, walking-skeleton.md:21 and :43, sweeper/README.md:7, the api/README
  "Runs" section, PROJECT_HISTORY "## 24.", and the BUILD_BACKLOG head and review-note anchor each exist exactly
  once.
- Every name a later task uses is defined earlier with the same signature. mypy strict passed on all three states I
  rebuilt (after Task 1, after Task 4, at the end of Task 5): 23 source files for core+api, 27 with the sweeper.
- `DbUnit` satisfies `Unit` through `DbStore.unit`.
- Every psycopg call runs on the connection `Session.unit` yields, and savepoints use the nested `conn.transaction()`.
- `tasks.json` and `acceptance-matrix.json` round-trip byte for byte with indent=2, ensure_ascii=False and a trailing
  newline, so the Task 7 script rewrites only what it changes.

#### 4. Tests

- I ran the plan's unit tests on the copy:
  - `tests/plan_g` and the edited plan_d/plan_f give 257 passed;
  - the full dev suite collects 780 tests and 98 skips;
  - 13 failures need a git checkout of the copy (`verify_handoff` and text hygiene call `git ls-files`) and are not
    the plan's.
- Intermediate counts, all measured:
  - 157 after Task 1;
  - 158 at Task 4 Step 5;
  - "8 failed, 150 passed" at Task 5 Step 2c;
  - 22 for `test_api_admission.py`;
  - 31 router tests plus the vocabulary test, with 50 together with Plan C's 18;
  - 14 store-unit tests and 8 idempotency tests;
  - 3 + 11 + 2 = 16 at Task 2 Step 3.
- No test asserts nothing.
- `test_the_db_reply_locks_the_run_before_it_checks_or_writes` runs the real `DbUnit` SQL over a recording
  connection. The fake's different reply order is backed by the two live savepoint proofs (R016 supersede, R129
  second answer), and both are correct against `create_run` (OC002 after the message insert) and the job dedup key.
- No `await` appears in a generator expression: every `await` in a comprehension is in its first iterable.
- The live tests bind every response before asserting, and no header or cookie appears in an assert operand.
- Live tests leave nothing behind:
  - every conversation is purged with all its rows;
  - every record is deleted by key;
  - the clock is reset in `finally`;
  - the migration test restores the head in a nested `finally`;
  - the sweeper test deletes its seeded record.
- No live test depends on wall-clock timing beyond R018's ±1 minute window.
- Session-scoped `live` skips before the module-scoped `lines` fixture can write an empty evidence file.
- Negative cases exist for every route and for every status code (401, 403, 404, 409, 422, 429, 503).

#### 5. Gates and arithmetic

- Every expected count adds up:
  - dev gate: 679 → 699 → 704 → 736 → 758 → 780 passed, with skips 95 → 98 → 104;
  - live gate: 773, 781, 835, 857, 863 passed, each with 21 skipped;
  - the baseline of 679 passed / 95 skipped was re-measured today.
- ruff check, ruff format --check and the ISC004 revision check pass on every new and changed file.
- The 120-character count passes: no code file has a longer line, and neither does the plan.
- No `noqa: BLE001` and no new broad `except Exception` (only the catch-all handler, ruling 19).
- No schema drift:
  - `StoredMessageKind` is not exported by `build_schemas.py`;
  - Plan C's generated-schema and conformance tests pass on the copy;
  - `verify_handoff` checks only JSON integrity, coverage and the manifest, all unaffected.

#### 6. Process

- Each task commits only its own files. Task 5 also carries the two live callers, a choice the plan states
  explicitly.
- The `TODO(T12)` markers name the step that removes them. `TODO(T19)` and `TODO(T27)` are ownership markers.
- The debt list, errata 35-44 and the owner inputs are consistent with the rulings, and the SESSION_STATE anchors
  exist.
- The four wording items already ruled (ruling 15's "first table statement", the SESSION_STATE repository line and
  heading dash, Task 7 Step 4's "only if", and the evidence-file 120-character exemption) were not re-reported.

Not verified, and therefore not claimed: the live suite. The six live admission tests, the three live revision tests
and the changed live sweeper test were read against the SQL and the grants but not run.

## Builder dry run

## Plan G dry run, round 3 (closure): builder report

Plan: `docs/superpowers/plans/2026-10-10-first-slice-g-admission-idempotency.md` at `plan-g` e11e601.
Worktree: `C:/Users/joeys/Desktop/MLOps-dryrun-g` (detached at e11e601, `uv sync --locked`, `.env` copied), removed
at the end. Every task executed from scratch in that fresh worktree; every code block was typed from the plan by a
script that copies the fenced block verbatim and refuses a splice whose old text is not found exactly once.

### Summary

- Tasks reached: 1-7, all steps (46 step checkboxes ticked; close-out commit 3bd2d21 in the scratch worktree).
- BASE recorded in Task 1 Step 1: `BASE=e11e601` (report and the SDD ledger
  `.superpowers/sdd/2026-10-10-first-slice-g-admission-idempotency/progress.md`). Task 7's script printed
  `e11e601..c1d8289`; `merge-base --is-ancestor` passed.
- Workarounds: 0 in total (T1 0, T2 0, T3 0, T4 0, T5 0, T6 0, T7 0). Every splice's old text was found exactly
  once, every expected run line matched, ruff format/check changed nothing ("N files left unchanged",
  "All checks passed!"), the counting command printed nothing for every task's file list, mypy strict
  `Success: no issues found in 23 source files` (Task 4 Step 6 and Task 5 Step 4).
- Scratch commits (discarded with the worktree): 5e7aaad (debt list), 8febe61 (T1), 8c60430 (T2), a19e8e8 (T3),
  43df697 (T4), 249a201 (T5), c1d8289 (T6), 3bd2d21 (T7).

Gate tails (exact):

| When | `check.py` (dev) | `check.py --profile test` | `verify_handoff.py` |
| --- | --- | --- | --- |
| T1 S1 baseline | `679 passed, 95 skipped` GREEN | `753 passed, 21 skipped` GREEN | (not asked) |
| T1 S8 | `699 passed, 95 skipped` GREEN | `773 passed, 21 skipped` GREEN | exit 0 |
| T2 S6 | `704 passed, 98 skipped` GREEN | `781 passed, 21 skipped` GREEN | exit 0 |
| T3 S4 | `736 passed, 98 skipped` GREEN | (not required) | exit 0 |
| T4 S6 | `758 passed, 98 skipped` GREEN | `835 passed, 21 skipped` GREEN | exit 0 |
| T5 S6 | `780 passed, 98 skipped` GREEN | `857 passed, 21 skipped` GREEN | exit 0 |
| T6 S5 | `780 passed, 104 skipped` GREEN | `863 passed, 21 skipped` GREEN | exit 0 |
| T7 S4 | `780 passed, 104 skipped` GREEN | `863 passed, 21 skipped` GREEN | exit 0 |

Live module runs: T2 S5 `7 passed`; T6 S3 `6 passed in 3.72s`; T6 S4 `1 passed in 28.12s`.
`verify_handoff.py` last line every time: `LIMIT: These are handoff/contract checks, ...`.

### WORKAROUND entries

None. No step needed a workaround in round 3.

### Observations (no workaround needed; all Minor or below)

- O1 (Minor, ruling 12 / Task 3 `routing.py` comment). "Every unit a person writes is read" overstates the parser.
  Measured with form A17/24 h, each of these routes `investigate` with 24 h, so the form wins silently: "last 3
  months", "last 2 years", "last 90 seconds", "last 1.5 hours", "last 24-hours". Ruling 12's cost names only "the
  previous 48 hours", "two days" and five-digit numbers. Also "last 3M" reads as 3 minutes (it then asks, the safe
  direction). Either widen the unit list or name months/years/seconds/decimals/hyphens in the ruling's limit.
- O2 (Minor, Task 5 Step 2a). Edit 2 drops `MessageKind` from app.py's imports while the old `post_message` still
  uses it until Step 2c. That is a short interim F821. The plan runs no ruff between 2a and 2c, and the expected
  `21 failed, 1 passed` is unaffected, so nothing broke.
- O3 (trivia, Task 6 / Global "Scratch objects"). After the R105 re-run, `ops_test` still holds five idempotency
  records. They are the conversation's 201, the message's 202, the decisions' 200 and two 409s (the stale-hash one
  names no run, so `PURGE_ORDER` keeps it), plus R105's own run. This is harmless because `ops_test` is per
  session, and R006's downgrade guard only counts system messages, which R105 never writes.
- O4 (known, round-2 open point B1). `test_the_db_reply_locks_the_run_before_it_checks_or_writes` pins only the two
  refusal paths, which issue one statement each. The accepted path's order (lock, event read, savepoint) is still
  proved by reading the code only.
- O5 (trivia, Task 7 Step 2). The `**Next task:**` replacement turns one physical line of `SESSION_STATE.md` into
  seven. It renders the same, but it is the only header line there that wraps.
- Checked against the four wording items already ruled (ruling 15 "first table statement", the Repository line and
  the em dash, "only if the live run changed them", the evidence file's long lines). Each one reproduced as
  described, and none of them blocked a step.

### As-written lines

T1/S1: as written (dev 679/95 GREEN; live 753/21 GREEN; checkout of the three report dirs; debt commit 5e7aaad)
T1/S2: as written
T1/S3: as written (`1 error in`, ImportError AdmissionSettings)
T1/S4: as written (`5 passed`)
T1/S5: as written (`2 errors in`, ModuleNotFoundError ops_api.limits)
T1/S6: as written
T1/S7: as written (all 14 edits; `15 passed`; `157 passed`)
T1/S8: as written (format/lint/count clean; 699/95; 773/21; exit 0)
T2/S1: as written (`1 error in`)
T2/S2: as written (ISC004 no change; `2 failed, 12 passed`, both KeyError 'idempotency_request')
T2/S3: as written (`16 passed`)
T2/S4a: as written (`1 failed, 8 passed`)
T2/S4b: as written (`9 passed`)
T2/S4c: as written (`158 passed`)
T2/S5: as written (`7 passed`; no skeleton process before or after)
T2/S6: as written (704/98; 781/21; exit 0)
T3/S1: as written (`1 error in`, ImportError SYSTEM_MESSAGE_KINDS)
T3/S2: as written (`1 error in`, ImportError ADMISSION_RULES)
T3/S3: as written (`50 passed`)
T3/S4: as written (`import ops_core.routing` prints nothing; 736/98; exit 0)
T4/S1: as written (`1 error in`, ModuleNotFoundError ops_api.idempotency)
T4/S2: as written (`8 passed`)
T4/S3: as written
T4/S4: as written (`1 error in`, ImportError DbUnit)
T4/S5: as written (`22 passed`; `158 passed`)
T4/S6: as written (mypy `Success: no issues found in 23 source files`; 758/98; 835/21; exit 0)
T5/S1: as written (`21 failed, 1 passed`; the pass is the fault-route-404 test)
T5/S2a: as written (`21 failed, 1 passed`)
T5/S2b: as written (`21 failed, 1 passed`)
T5/S2c: as written (`22 passed`; `8 failed, 150 passed`)
T5/S3: as written (`257 passed`)
T5/S4: as written (mypy `Success: no issues found in 23 source files`; `257 passed`)
T5/S5: as written (no other keyless `/api/v1` post remains in the two live modules except refusals before the key)
T5/S6: as written (780/98; 857/21; exit 0)
T6/S1: as written (`2 passed`)
T6/S2: as written (`6 skipped`)
T6/S3: as written (`6 passed`; header plus twelve lines in the stated order and shapes; R018 `1:59:59.214755`; no
  token, cookie or BETA id; afterwards `ops_test` held 0 records, 0 system messages, 0 conversations, offset 00:00:00)
T6/S4: as written (`1 passed`; nine events ending `action.confirmed`)
T6/S5: as written (780/104; 863/21, test_admission_live first in tests/e2e; checkout of bootstrap and auth; exit 0)
T7/S1: as written (printed `e11e601..c1d8289`; three handoff files changed; only R015, R016, R017, R018, R115 and
  R129 differ in the matrix, the rest of it identical; T12 `DONE`; T13 is then the earliest dependency-satisfied
  task, as the Next-task text says)
T7/S2: as written (the two execution bullets: "none beyond the plan" and "none recorded"; the ledger parks nothing)
T7/S3: as written (STATUS, PROJECT_HISTORY §24/§25 with "Execution found nothing the plan had not ruled on.",
  README line 5 reads exactly as shown, api/README, sweeper/README, both runbooks)
T7/S4: as written (780/104; 863/21; exit 0; the reports/admission and reports/skeleton files changed and were
  committed)
T7/S5: as written (commit 3bd2d21)

### Clean-up proof

- `skeleton.py status` before the drop: all six processes `down` (incident-sim, mcp-read, mcp-write, api, worker,
  sweeper).
- As the superuser: `DROP DATABASE IF EXISTS ops_test WITH (FORCE)` and the same for `incident_test`; both
  `DROP DATABASE`.
- `SELECT datname FROM pg_database ORDER BY 1`: `incident`, `ops`, `postgres`, `template0`, `template1`. No test
  databases remain.
- No `critic*` role (pg_roles), and no `critic*` relation or schema in `ops` or `incident`. This run created no
  scratch object outside the test databases.
- Dev `ops` is untouched: `to_regclass('app.idempotency_request')` is NULL, so it is still at revision 0005.
- `git worktree remove --force C:/Users/joeys/Desktop/MLOps-dryrun-g` then `git worktree prune`;
  `git worktree list` shows only `C:/Users/joeys/Desktop/MLOps e11e601 [plan-g]`. The main tree is clean and
  `plan-g` is still at e11e601 (nothing was committed on it).
- Keycloak and PostgreSQL containers stayed up and were not touched (`ops-copilot-keycloak-1`,
  `ops-copilot-postgres-1` healthy).

## Rulings

## Round-3 rulings (controller)

### Pre-seeded wording fixes (from round 2 open points, builder items 4-7)

- Ruling 15: "the run lock is the unit's first table statement after the record lookup".
- Task 7 SESSION_STATE block: the Repository line names plan-g; the STATUS heading cited with its em dash.
- Task 7 Step 4: drop "only if the live run changed them".
- Global constraints: the evidence file's lines are exempt from the 120-character rule (they are data).

### Rulings on the round-3 critic's minors (`r3-critic.md`): all accepted

- M1: `TEXT_WINDOW` units keyed by full word: `second(s)|sec(s)`, `minute(s)|min(s)`, `hour(s)|hr(s)|h`,
  `day(s)|d`, `week(s)|wk(s)`, `fortnight(s)` (= 2 weeks), `month(s)|mo(s)`, `year(s)|yr(s)`; single-letter forms
  only `h` and `d` (a bare `m` or `w` is not read, so "3 M" is no window). Seconds, months and years convert to hours
  (seconds only when divisible by 3600; months 720; years 8760) and then fall under the 1–168 rule like any other
  window. One table row and one test row per added unit family; recount Task 3 and later gates.
- M2: `arm_fault` depends on `browser_mutation` (CSRF/origin in cookie mode); erratum 35 says the route is exempt
  from the key only.
- M3: comment and ruling 19 say "a lost connection or a transient server condition"; `psycopg.errors.
  ProgramLimitExceeded` and `StatementTooComplex` route to the non-retryable server-defect handler (registered before
  the OperationalError handler so Starlette's class walk finds them first), with one unit test.
- M4: expected `Success: no issues found in 23 source files`.
- M5: evidence shape "1:59:5x.<µs>"; self-review wording.
- M6: README tail "; durable admission with a scoped Idempotency-Key and the AM-16 router (T12) runs locally".
- M7: the review record (`docs/reviews/plan-review-g-2026-10-10.md`) and the planning story (a new
  PROJECT_HISTORY section named "The admission plan …", numbered 24, before "What the process taught" which becomes
  25) are committed by the controller BEFORE execution, as Plan F did. Task 7 therefore appends the execution and
  final-review paragraphs to the section whose heading starts "## 24. The admission plan" (addressed by that name,
  not by renaming anything) and leaves the closing section alone.
- M8: `VerdictResponse.render` docstring; Task 1 Step 1 split into 1a (baselines), 1b (BASE), 1c (debt list +
  commit).

### Rulings on the round-3 builder's items (`r3-builder.md`; zero workarounds)

- Item 1: covered by M1, extended: the number may carry a decimal part (`\d{1,4}(?:\.\d+)?`) and the number and
  unit may be joined by spaces or a hyphen (`[\s-]*`); a decimal that is not a whole number of hours after
  conversion is out of range / a conflict like any other non-integer window. Ruling 12's cost sentence names what
  is still unread (numbers written as words, "yesterday", absolute dates).
- Item 2: Task 5 Step 2a keeps the `MessageKind` import until Step 2c removes it with the old `post_message`.
- Item 3: the R105 module's clean-up deletes `idempotency_request` rows by the keys it sent (bind the keys to a
  module list), in a `finally`.
- Item 4: the recording-connection test gains the accepted path: with a scripted AWAITING_INPUT row whose version
  matches and a scripted job rowcount 1, the first statement contains `FOR UPDATE` and the INSERTs follow it in the
  order messages → jobs → the `append_event` call.
- Item 5: accepted as is (a wrapped header line renders correctly).

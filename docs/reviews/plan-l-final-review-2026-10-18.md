# Plan L final review — T17 governed corpus, ingestion and lexical baseline

Branch `plan-l`, range `00d388f..753fa6f` (plan-k's head to the close-out's fix round). The whole-branch review ran on
the most capable model, read-only, with no database connection and no test run. Verdict: 0 Critical, 0 Important,
5 Minor; ready to push after small fixes.

Controller rulings on the findings: M1 (nine `type: ignore` comments against the plan's own constraint), M2 (`skeleton.py
ingest` hid its own "run migrate" hint) and M3 (this history lacked Task 6's round and held the final-review placeholder)
were fixed in one wave, 2f7efa4 and 34e9c42; M4 (`retrieved_at` stamped from the wall clock while effectiveness is decided
at the database clock) became a T16 debt line; M5 (the frozen revision's docstring understates when an ingestion row is
written) became one sentence in `docs/retrieval.md`, the revision untouched. The three minors the task reviews had parked
(the test pins the rendered caveat sentence, the order inside a `finally`, no ingestion concurrency lock) were ruled
harmless, with the reasons below. Gates after the wave: dev `1270 passed, 191 skipped`, live `1440 passed, 21 skipped`,
`verify_handoff --reference-code --manifest --contracts` exit 0.

---

## Plan L final whole-branch review (00d388f..753fa6f, branch plan-l)

Reviewer: final review (read-only; no database, no live suite, no test run). Scope was read in passes:
(1) the code at full depth: `migrations/app/versions/0011_governed_corpus.py`, `core/src/ops_core/{corpus,ingest}.py`
and the diffs of `persistence`, `privileges`, `locking`, `settings` and `scripts/skeleton.py`, `mcp-read/.../server.py`,
`scripts/{retrieval_baseline,gen_corpus_meta,verify_handoff,build_schemas}.py`; (2) the tests: `tests/e2e/{conftest,
test_migration_0011_live,test_ingest_live,test_retrieval_baseline_live}.py` in full, the R131/process/R105 live diffs,
the outlines of `tests/plan_l/*`; (3) the records: the matrix rows R032/R033/R099/R131, the tasks.json review note,
STATUS, the SESSION_STATE additions (next task, owner inputs, errata 93-102, open items), ARCHITECTURE §9, the
runbooks, READMEs, `docs/retrieval.md`, PROJECT_HISTORY, the measured report (md + json head), and the regenerated
reports' diffs; (4) the data: the catalog (all 16 entries), the injected documents, and a word/asset count of
`data/corpus` by a scratch script (16 files, 332-349 prose words, 6 assets, 7 alerts: matches every record). The
plan's 7,206 lines, the review record and the research sheet were consulted at the rulings and open points only.
Findings fixed in the ledger's rounds were not re-raised; each was spot-checked closed in the code.

#### Strengths

- **The authority boundary moved by exactly one function.** `mcp_read` gains EXECUTE on `search_procedures_scoped`
  only (`privileges.DEFINER_FUNCTIONS`, revision `FUNCTIONS`, the live R131 equality, and `mcp_exec`'s 42501 on the
  new function); `_min_rank()` is granted to nobody and the round-trip snapshot compares ACLs. mcp-read holds no table
  grant (asserted after the round trip), still reaches no write function and no incident-sim. Nothing in the branch
  sends anything outward.
- **The tenant comes only from the handle.** The definer resolves `_resolve_handle(raw_handle, azp, 'read')` first,
  sets `app.tenant_id` transaction-locally under the function's own `SET` clause, filters `corpus_ingestions`
  explicitly and relies on FORCE RLS for the rest; the live tests prove another tenant's chunk is not returned, a
  never-ingested tenant answers `none`/`[]`, a wrong `azp` and a dead handle are refused, and the worker sees 0 rows
  without a tenant and only its own with one. mcp-read resolves the handle twice (allowlist unit, then the definer),
  so a handle released between the units is refused too.
- **One lifecycle rule, stated identically in four places.** The SQL `permitted` CTE, `corpus.returnable`,
  `docs/retrieval.md` and erratum 94 all say: latest state approved, effective at `app.current_time()`, and not
  retired by a later version that has left draft and reached its `effective_from`. I traced every catalog-change
  sequence through `ingest.plan` (draft→any, approved→superseded/revoked, superseded→revoked, effective_to edits,
  new versions, removal, restating to draft, moving effective_from, superseded→approved, any change after revoked):
  none un-retires a predecessor, because the two changes that could are refused and a successor's `effective_from`
  is immutable once it leaves draft. Un-expiring by lengthening/clearing `effective_to` is the controller's recorded
  ruling and is not re-raised.
- **Idempotency and all-or-nothing are real.** Validate the whole directory, plan every tenant read-only, then write
  each tenant in one transaction re-planned inside it; a repeated run writes no row at all; the beta-side refusal test
  proves alpha is untouched. A concurrent second run always collides on a primary key (same `next_seq`, same state
  `seq`, same document key) and rolls that tenant back, so the missing lock cannot produce a wrong state.
- **The downgrade is exact and self-maintaining.** `DOWNGRADE` drops exactly the two functions and four tables (index,
  policies and grants go with them); the round-trip test derives what to exclude from the revision's own `FUNCTIONS`,
  `TABLES_0011` and `CREATE INDEX` statements, proves the `vector` extension survives and mcp-read refuses 0010, and
  re-migrates. `REQUIRE_VECTOR` keeps the extension the bootstrap's.
- **The dev database is not reachable from any test.** `env` sets `OPS_PG_DB=ops_test` before anything reads settings;
  `export_environment` only `setdefault`s; `ingested`, `migrated` and the round trip all resolve through that
  environment; the one unit test that calls `skeleton.ingest()` monkeypatches `_ingest`. `skeleton.py ingest` targets
  dev only when an operator runs it, which is the documented owner input; it also loads with `RELEASES`, so only a
  released corpus can reach any real database.
- **Evidence is honest.** Every figure in STATUS, SESSION_STATE, the R032/R033/R099/R131 rows, ARCHITECTURE and
  `docs/retrieval.md` matches the measured report (27/27, 1.0, 0.2296 = its ceiling, 0.8963, 15/20, 0/122, Wilson
  bounds recomputed: 0.8754 for 27/27 and 0.5313-0.8881 for 15/20 are right). R033 is "subject to erratum 102" in
  every place Plan K used for R131, with the residue (A15, B10, B13, B17, B18) and T20's relevance criterion stated
  correctly (SA:377 would not abstain). The development-figure caveat is in the report's first paragraph, the JSON
  settings, the docs and every record. The forbidden check is described truthfully as circular inside the measurement
  and anchored to the hand-written `RETURNABLE_AT_AS_OF`, and the clock is pinned to the labelling instant.
- **The walking skeleton now cites the governed corpus end to end** (`reports/skeleton/r105-walking-skeleton.txt`:
  `ALPHA-ALERT-REVIEW:v1:repeated-alerts`), and the R131 report line moved with the grant.
- No attribution trailer in any of the 18 commits; the synthetic banner, the plainly synthetic injected text and the
  holdout boundary are respected.

#### Issues

##### Critical

None.

##### Important

None.

##### Minor

1. **`type: ignore` added against the plan's own Global Constraint.** `core/src/ops_core/ingest.py:304`
   (`error.written = ...  # type: ignore[union-attr]`, the only `type: ignore` in any service or core module) and eight
   in `tests/plan_l/test_ingest_run.py` (`# type: ignore[arg-type]` on the stub connection, `[attr-defined]` once). The
   plan's constraints (line 110) say "no `type: ignore`"; the task reviews did not catch it. Effect is nil at run time
   (psycopg's `Error` has no `__slots__`, so the attribute sticks), but it hangs state on a third-party exception and
   makes `skeleton.ingest` read it with `getattr`. Fix: raise a typed `IngestInterrupted(written: tuple[str, ...])`
   `from error` in the phase-2 handler (the command then prints `type(error.__cause__).__name__`), and type the test
   stub as `persistence.Conn` through a `cast` or a Protocol the stub satisfies.
2. **`skeleton.py ingest` hides its own diagnostic for the likeliest owner mistake.** `scripts/skeleton.py:269-273`
   prints only the class for `persistence.PersistenceError`, so running `ingest` before `migrate` (dev is at 0010)
   prints `INGEST: failed (PersistenceError)` and drops `assert_relation`'s "app.chunks is missing; run
   scripts/skeleton.py migrate for this profile". The class-only rule exists for driver messages (host names); a
   `PersistenceError` raised by `assert_relation` carries only our own text. Fix: print `str(error)` for
   `PersistenceError` that is not a translated driver error (or for `assert_relation`'s case specifically), class only
   for `psycopg.Error`; adjust `test_the_command_reports_a_store_failure_with_its_class_only`.
3. **PROJECT_HISTORY is missing Task 6's review round and still holds the final-review placeholder.**
   `docs/PROJECT_HISTORY.md` (the Plan L section, "**Final review.** (Final review: filled in after the whole-branch
   review.)") and its "Execution" paragraph stop at Task 5; Task 6's round (the erratum-102 abstention overclaim and
   its six minors, fixed in 753fa6f) is not recorded, contrary to the standing instruction to append every review
   round. Fix before the push: add Task 6's problem/change and this review's outcome; update SESSION_STATE's "Open
   items" to record the rulings below on the parked minors.
4. **`retrieved_at` uses the wall clock while "effective" uses the database clock.** `mcp-read/.../server.py`
   `search_response(found, now=datetime.now(UTC))`. Pre-existing pattern, but since T17 the lifecycle is decided at
   `app.current_time()`; in the test profile with a moved clock a result can carry `retrieved_at` earlier than its own
   `effective_from`, and the evidence row no longer records the instant its permission was decided. Low priority:
   return `v_now` from the definer (one more column) and stamp `retrieved_at` from it, or record it as T16 debt.
5. **Nit: the frozen revision's docstring understates when an ingestion row is written.**
   `migrations/app/versions/0011_governed_corpus.py:7` says "one row per tenant per ingestion run that changed
   something"; `ingest.plan` also writes one when only the corpus version or lock changed (`record = ... or not
   current`), which is what makes the tool report the new version. `ops_core/ingest.py:20-23` states it correctly. Leave
   the revision (frozen) and, if anything, mention it in `docs/retrieval.md`'s ingestion paragraph (which is already
   correct: "whose latest row already names this version and lock gets no row").

Rulings on the parked minors (ledger):
- Task 5, the test pins the rendered sentence rather than "development figure" inside `SETTINGS["minimum_rank"]`:
  does not matter. `SETTINGS["minimum_rank"]` is a module constant that already contains the words, the markdown is
  rendered from it, and the md/json are committed artefacts a reviewer reads; a test on the constant adds nothing.
- Task 5, the finally order (clock reset before `purge_run`): does not matter. If the reset raised, the runs would leak
  only into `ops_test`, which the next session drops; the clock reset is the more important of the two to run first.
- No ingest concurrency lock: does not matter for v1. Every concurrent interleaving I traced ends in a primary-key
  collision and a tenant rollback, never in a wrong state; the operator sees `INGEST: failed (UniqueViolation) after
  writing ...` and re-runs. Keep the recorded "one operator" note.

Housekeeping (not a finding): the working tree shows `M docs/superpowers/research/2026-10-16-plan-k-inputs.md` with no
content diff (line endings under `core.autocrlf=true`); do not commit it with the fixes.

#### Declined to judge

- Whether `worker` should hold INSERT on the corpus at all (the LLM-orchestrating service can write evidence rows for
  its tenant): AM-20.2 grants it explicitly ("ins, sel (ingestion)") and ruling 5 follows the spec; a separate
  ingestion role would be a spec change for the owner, not a defect of this branch.
- The live-only behaviour (DDL, grants, RLS, the measured figures): the rules forbid running the live suite; I relied on
  the ledger's measured gates (dev 1269/191, live 1439/21, verify_handoff 0) and the committed reports.

#### Assessment

**Ready to push: With fixes** (minor only). No Critical or Important issue: the authority, tenant, lifecycle,
idempotency and dev-database boundaries hold and every record matches the code and the report; fix Minor 3 (the
history record and the final-review placeholder) before the push, and Minors 1-2 in the same small fix commit if the
controller wants the plan's no-`type: ignore` constraint honoured; 4-5 can be recorded as debt.

---

## Re-review of the fix wave

A scoped re-review (`753fa6f..34e9c42`, read-only, no suites re-run) found each item done as ruled. M1: a typed
`IngestInterrupted(written)` is raised from the store error once a tenant has committed, and a failure before any commit
propagates unchanged; no `type: ignore` is left in code or tests. M2: the command prints our own `PersistenceError`
message and only the class of a driver error, and the renamed test pins both, so a host name in a driver message cannot
reach the output. M3-M5, the counts and the commit trailers were verified. Verdict: Approved. Its four nits: a
paraphrase shown as a quote, a cramped paragraph and a gitignored path cited as the record (all three fixed with this
record), and no test for an `IngestInterrupted` whose cause is our own `PersistenceError` (the code handles it; left).

# Adversarial review of Plan E (roles, grants, RLS, definer functions and the hardened destination, T09/T10): rounds 1–2 (2026-10-08)

**Reviewed:** `docs/superpowers/plans/2026-10-08-first-slice-e-roles-rls-definers.md` before execution. The plan was
written from a fact sheet (`docs/superpowers/research/2026-10-08-plan-e-inputs.md`, T09/T10 verbatim with AM-20 row by row, 16 open
questions) and a measured library spike (`…plan-e-spike.md`, six PostgreSQL and Alembic measurements) run against the live dev stack before any plan code
existed.

**Method:** the same two-critic gauntlet as Plans A–C — a static critic cross-checking every claim against the spec,
the existing code and the libraries (measured in a scratch environment), and a builder executing all nine tasks on a
throwaway worktree against the live Keycloak and PostgreSQL, with the shared databases cleaned afterwards.

**Round 1 (static critic: 6 Blocking, 16 Important, 18 Minor; builder: 27 workarounds, all attributed to the plan's text).** The two reviews agreed on the four defects that mattered. First, the spec's lock column and its grant matrix contradict each other: a `FOR SHARE` row lock needs UPDATE on at least one column, and AM-20.2 gives `app_definer` only SELECT and INSERT on `proposals`, `decisions`, `memberships` and `execution_grant`, so `record_decision`, `grant_execution` and `mark_unknown` failed with 42501 on their first call. The fix drops those locks (the `runs … FOR UPDATE` taken first already serialises every writer) and proposes the erratum. Second, two PL/pgSQL bodies carried `':1'` and `':timeout'`, which SQLAlchemy's `text()` reads as bind parameters, so revisions 0003 and 0004 could not be applied at all; the plan's own guard ("no ` :name`") missed a colon after a quote. The fix uses `format('%s:1', …)` and adds a DB-free unit test that loads every revision and asserts no `op.execute` string carries a bind. Third, nine tests expected the functions' own `OC001` authority error for a wrong caller, but PostgreSQL refuses a role without EXECUTE with 42501 before the body runs; `_authority` is reachable only by a session that holds EXECUTE through membership or superuser status, which the tests now prove through the superuser connection. Fourth, Task 2 changed the schema under Plan D's persistence code while claiming every other live module still passed; the builder measured 15 of 25 live tests red from Task 2 to Task 7. The plan now declares that window, names what may be red per task, and seeds the role tests with plain superuser INSERTs. Smaller but real: a draft inserted without a tenant (RLS refused it), an async generator unpacked as a tuple, a worker re-queue that silently touched zero rows because the tenant was not set (a production defect), a bootstrap error path that would have printed a password in the exception context, a `Session.read` call that broke incident-sim's readiness at runtime, the test-harness role existing outside the test profile, and the late-evidence event payload that the Python rule mirror would have refused. Every finding was accepted; the round-2 text carries each fix.

**Round 2 (static critic: 59 of 67 round-1 items closed, 5 partial, 2 open — the bind fix's own comment was a bind; 1 new Blocking, 5 Important, 13 Minor. Builder: 9 workarounds, down from 27, 25 of the round-1 ones gone).** The one blocking item was the author's: the comment written to explain the `':1'` bind fix contained `':1'` itself, and SQLAlchemy scans comments, so revision 0003 still could not be applied; the plan's new bind-scan unit test was what caught it. The most consequential new finding was a production defect neither round-1 review had seen: a classified UNKNOWN from the destination (a lost reply, a 503, a malformed document) went into `record_outcome`, which refuses UNKNOWN by design and raised outside the guard, so mcp-write never returned the UNKNOWN envelope and the worker's `mark_unknown` path was reachable only from the scripted test. The fix returns the envelope before any recording and adds three live cases (exception, `None`, 503). Two other findings would have surfaced only later: revision 0002 rendered its grants from the live matrix, so the first later task adding a table row would have broken every fresh migration (R006) — the lists are now frozen literals with a unit assertion — and the SQL event rules still accepted three payloads their Python twin refuses, one of them writable by the worker role. The rest was gate hygiene: a unit test parametrised over a revision that did not exist yet, a mypy allowance that named too few call sites, a ruff rule the plan stated but its own code blocks broke, a `-x` that stopped a run at a declared-red test, a `grep` that matched a comment line in `.env`, and two evidence files that live runs rewrite (one restored, one committed).

**Round 3 (closure: one reviewer verified every round-2 item against the delta and executed all nine tasks a third time).** Zero workarounds; 26 of 27 round-2 items closed, one partial, and the seven round-1 items the second critic had left open all closed. Four minors remained, all fixed in the final text: the revisions still rendered their grant cells and caller lists from the live matrix, so a later task editing a cell would have silently changed an applied revision on a fresh database (each revision now freezes its own cells and callers, and a unit test checks that the newest revision agrees with the matrix); the SQL event rules checked receipt and tombstone keys but not their shape (a defence-in-depth check was added; the producer validates the full models); the R105 evidence did not record which refusal era it was written in; and incident-sim's rejection branches answered 200 for a committed key under another hash where the document said 409. Final gates on the dry-run worktree: `check.py` 507 passed / 77 skipped, `check.py --profile test` 563 passed / 21 skipped, `verify_handoff.py` exit 0.

The plan went from 27 workarounds to 9 to 0 across the three dry runs; the record below is the reviewers' own text.

The reports below are the reviewers' text, unedited except that machine-local paths are replaced by placeholders.

---

## Round 1 — static critic

# Plan E static critic, round 1

Plan under review: `docs/superpowers/plans/2026-10-08-first-slice-e-roles-rls-definers.md` (branch `plan-e`, HEAD
`f04204d`). Inputs read: `AGENTS.md`, `docs/CODE_COMMENTS.md`, the whole plan, the fact sheet and spike, SPEC_AMENDMENTS
AM-12/13/14/20 (SA:150–175, 255–272, 383–566), BUILD_SPEC §6/§10 rows cited, and the code the plan modifies
(`core/src/ops_core/*`, both revision-1 files, both `env.py`, `scripts/skeleton.py`, `scripts/check.py`,
`scripts/bootstrap_dev.py`, `compose.yaml`, the five services, `tests/e2e/*`, `tests/plan_d/*`, `pyproject.toml`).

Method: every SQL body was executed, not just read. The plan's `privileges.py`, revisions `0002`, `tc_0001`, `0003`,
`0004` and incident `0002` were extracted verbatim from the plan's code blocks and applied, through `sqlalchemy.text()`
exactly as `op.execute` does, to scratch databases `critic_e` / `critic_inc` on the dev PostgreSQL 17.11, with schema
`app` renamed `critic_app` and every role renamed `critic_<role>` (the GUC `app.tenant_id` kept). The plan's own test
calls were then run as those roles. Real Alembic was driven over a scratch tree with the plan's branch layout. The
plan's unit tests were run against a scratch copy of `ops_core` patched with the plan's modules; ruff (repo config) and
mypy `--strict` were run over every full-module code block. Everything named `critic_*` was dropped afterwards (§3,
last block). No repository file was edited; `skeleton.py migrate`/`up` and `docker compose down` were not run.

Counts: **6 Blocking, 16 Important, 18 Minor.**

---

## 1. Verdict table

| # | Claim (plan location) | Verdict | Evidence / what is wrong |
|---|---|---|---|
| 1 | Revision 0002 drops the right auto-generated FK names (`runs_message_id_fkey`, `run_state_history_run_id_fkey`, `jobs_run_id_fkey`, `drafts_run_id_fkey`, `proposals_run_id_fkey`, `decisions_proposal_id_fkey`, `execution_grant_run_id_fkey`, `action_attempt_action_id_fkey`, `action_attempt_state_action_id_attempt_no_fkey`, `events_run_id_fkey`), and leaves `messages_tenant_id_conversation_id_fkey` alone (L949–1002) | PROVEN | M1: 0002 applied cleanly on revision 1's DDL (233 statements); M2 lists the resulting constraint set |
| 2 | `DROP COLUMN handle` then `ADD COLUMN handle_sha256 text PRIMARY KEY, ALTER COLUMN fence TYPE bigint` on the truncated table works as two statements (L1005–1007) | PROVEN | M1 (applied), M4 (downgrade + re-upgrade on a populated DB) |
| 3 | OWNERSHIP loop transfers every relation to `migrator`; `ALTER TABLE` on a sequence is fine (L1037–1053) | PROVEN | M2: every table and the schema owned by `critic_migrator`; schema `app` has no sequences; incident's `incident_seq` is standalone (not OWNED BY), so `ALTER SEQUENCE … OWNER` works (M8) |
| 4 | `POLICY_QUAL` equals the stored `pg_policies.qual`, and `with_check` equals it (L553, L1587) | PROVEN | M2: `"(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)"`, equal; `sweeper_all` stores `'true'`/`'true'` |
| 5 | R124 enumeration (`role_table_grants` + `column_privileges`, owner excluded) yields exactly the matrix shape (L1403–1434) | PROVEN | M2: `actual == expected: True`, zero PUBLIC rows; table-level UPDATE (run_lease worker, test_clock harness) correctly suppresses the per-column rows |
| 6 | Function catalog shape: owner, `prosecdef`, `proconfig` `['search_path=app, pg_temp', 'app.tenant_id=']`, helpers without the attribute, ACL parsing (L1992–2016) | PROVEN | M2 (every function printed); no stray function once `_grant_row` is added to `HELPER_FUNCTIONS` |
| 7 | "One string per function", never `split(";\n")` (L18, L2348–2352, L3188–3192) | PROVEN | Each `FUNCTIONS` entry is one `op.execute`; M1 created all functions |
| 8 | "no ` :name` text in bodies" / `'{{}}'` renders `'{}'` (L18, L2362) | **DENOUNCED** | Braces render correctly, but `':1'` (L2231) and `':timeout'` (L3164) are SQLAlchemy binds → `StatementError: A value is required for bind parameter '1'` / `'timeout'`; revisions 0003 and 0004 cannot be applied (M0, M1). **B2** |
| 9 | `%` in `format()` and `LIKE 'run.%'` survives `op.execute` (L2362) | PROVEN (mechanism misdescribed) | M9: DETAIL `'ops may not call create_run'`, `LIKE` refuses `run.failed` and admits `runXfailed`. SQLAlchemy doubles `%` and passes `{}`; psycopg un-doubles (fact sheet §4.3) — the plan's "sends the text verbatim" is wrong, the outcome right. Minor m15 |
| 10 | RETURNS TABLE output columns never shadow column references; `%ROWTYPE`, `RETURN QUERY`, `RETURN NEXT` valid under `SET search_path = app, pg_temp` (L2363) | PROVEN | M3: `create_run`, `freeze_proposal`, `record_decision`, `resolve_identity`, `append_event`, `grant_execution`, `_resolve_handle`, `_grant_row`, `lookup_action`, `mark_sent`, `record_outcome`, `mark_unknown` all executed with no 42702 |
| 11 | `app_definer` holds every privilege the bodies need (AM-20.2 + three departures) | **DENOUNCED** | `FOR SHARE` needs UPDATE on at least one column; `app_definer` has only SELECT/INSERT on `proposals`, `decisions`, `memberships`, `execution_grant` → `record_decision`, `grant_execution`, `mark_unknown` fail with 42501 on every call (M3 §2). **B1** |
| 12 | Every function sets the tenant before touching an RLS table; a preset tenant is ignored and restored (Review Focus 1) | PROVEN | M3 §7 (`resolve_identity` with preset beta returns alpha's row, caller's setting is beta afterwards); the full write path ran under FORCE RLS from connections that never set a tenant |
| 13 | `_tenant_of_action` walk finds the tenant whatever the caller's setting (L2749–2765) | PROVEN | M3 §3–6: `mark_sent`/`record_outcome` from an `mcp_exec` connection with no tenant |
| 14 | A reused connection with GUC `''` sees zero rows, no 22P02 (Review Focus 2) | PROVEN | M3 §7: `count(*) = 0` |
| 15 | Wrong callers are refused with `OC001` (L1850, L1867, L1941, L1987, L2517, L2544, L2587, L2616, L2660; Review Focus 3) | **DENOUNCED** | EXECUTE is revoked from PUBLIC, so a role without the grant gets **42501 "permission denied for function"**; `_authority` is reachable only by grantees, superusers or `SET ROLE` members (M9: worker→`create_run` = 42501; superuser→`transition_run` = OC001). **B3** |
| 16 | Task 4 `freeze()` helper: "the worker's own INSERT on drafts, then the function" (L2471–2475) | **DENOUNCED** | No tenant is set → RLS WITH CHECK 42501 (M3 §1). **B4** |
| 17 | `api, worker, … = (await role_conn(r) for r in …)` (L2575, L2598, L2651, L2684) | **DENOUNCED** | async generator: `TypeError: cannot unpack non-iterable async_generator object` (M6). **B5** |
| 18 | Task 2: "Every other live module still passes … the old persistence code still works as the superuser" (L1664); R007/R009 use `new_run` (L1511, L1545) | **DENOUNCED** | 0002 makes `tenant_id` NOT NULL on `run_state_history`, `drafts`, `decisions`, `execution_grant`, `action_attempt(_state)` and drops `invocation_context.handle`; Plan D `persistence.create_run` inserts `run_state_history (run_id, seq, …)` without `tenant_id` (persistence.py:144–147) → 23502. **B6** |
| 19 | The R105 event list / write-path events emitted by the functions (L2641–2644, L4455) | PROVEN | M3 §3: `run.accepted, proposal.ready, approval.recorded, action.granted, action.dispatched, action.confirmed(destination)` |
| 20 | state_version 4 after freeze, 5 after decision, 6 after grant (L2478, L2546, L2618) | PROVEN | M3 §2–3 (4, 5; final 7 after SUCCEEDED) |
| 21 | FAILED_NO_COMMIT → FAILED(`rejected`) + `action.failed`; CONFLICT → ESCALATED(`conflict`) + `action.conflict` | PROVEN | M3 §6 |
| 22 | Late evidence: "the Python `event_rules_ok` accepts that type with outcome/receipt keys, so the payload here carries the same keys" (L3207) | **DENOUNCED** | The SQL payload has `action_id, receipt, status` — no `outcome`; `event_rules_ok` refuses it (M3 §4). **I5** |
| 23 | `_append_event` mirrors `event_rules_ok` (L2093) | **DENOUNCED** | SQL accepts `action.failed` with `{}` (NULL reason makes `NOT (x = ANY(…))` NULL); Python refuses (M3 §5). No receipt/tombstone/evidence_refs shape checks. **I5** |
| 24 | Worker direct SQL fits its grants: `claim_job`, `requeue_job` (with the `available_at` departure), `finish_job`, drafts INSERT, `mint_handle`, messages SELECT, runs `FOR UPDATE` | PROVEN | M3 §8 |
| 25 | `insert_job` serves the API's `resume_input` insert (L3820) | **DENOUNCED** | `api` has INSERT only; `ON CONFLICT (dedup_key)` and `RETURNING` need SELECT → 42501 (M3 §8; spike §3). **I4** |
| 26 | Alembic: `app` label on 0001, `heads` for test, `app@head` for dev; `testclock@base` then `0001` downgrades | PROVEN | M10 |
| 27 | R006: after `migrate(TEST)` the version table holds two rows (L1355) | **DENOUNCED for Task 2** | With only 0002 on the main line, `depends_on` leaves **one** row (`tc_0001_test_clock`); two rows only from Task 3 on (M10). **I14** |
| 28 | Revision 0002's downgrade restores revision 1 and is re-upgradable (ruling 19) | PROVEN | M4: 0 policies, 15 tables, owner back to the superuser, state-based slot index restored, 0 leftover column grants; re-upgrade OK |
| 29 | `ensure_login_role`/`ensure_nologin_role` are idempotent and set LOGIN/BYPASSRLS (L728–767) | PROVEN | M5 |
| 30 | "No secret in … exception message" (L21) for the role bootstrap | **DENOUNCED** | A failing `EXECUTE format(… PASSWORD %L)` puts the password in `str(exc)` and `diag.context` (M5, dummy literal) and the setting stays in the session. **I12** |
| 31 | `CREATE DATABASE … OWNER ops` / `DROP DATABASE … WITH (FORCE)` from the maintenance database (L1287–1294) | PROVEN | M1 setup does exactly this |
| 32 | `make_interval(secs => %s)` with an int, `Jsonb` for jsonb, `bytes` for bytea, `fetchone()` on RETURNS TABLE with `dict_row` | PROVEN | M3 (handle_for, requeue, freeze, every call) |
| 33 | R126 clock: harness UPDATE without WHERE, no SELECT, single row; GUCs ignored; other roles refused (L1624–1649) | PROVEN | M7 |
| 34 | R084/R128 direct-write and `FOR UPDATE` refusals | PROVEN | M7 |
| 35 | Incident 0002: `incident_owner` owns, `incident` has SELECT+INSERT, CHECKs, permanence | PROVEN | M8 (applied over a COMMITTED and an ABORTED row; DELETE/UPDATE/TRUNCATE 42501; CHECK 23514) |
| 36 | Live isolation probe `SELECT 1 FROM app.runs` as `incident` → InsufficientPrivilege (L4959–4960) | **DENOUNCED** | 42P01 UndefinedTable: `incident_test` has no schema `app` (M8). **I11** |
| 37 | `ops_core.privileges`, `settings`, `persistence`, `testing.faults` pass mypy strict / ruff (L25 "ruff + mypy strict clean") | **DENOUNCED** | mypy: `privileges.py` `grant_statements` `', '.join(grant.upd)` on `tuple[str, ...] \| Literal[False]` (**I1**). ruff (repo config): 31 × ISC004 in rev 0002, tc_0001, incident 0002 — not fixed by `ruff check --fix` (**I2**). persistence/faults/settings clean |
| 38 | Plan E unit tests pass once the code exists | **DENOUNCED (one)** | M11: 31 pass; `test_refused_carries_the_detail_code…` fails — the helper cannot override psycopg's `diag` property (**I10**) |
| 39 | "Plan D's settings test still passes because `superuser_postgres()` keeps the old behaviour" (L642) | **DENOUNCED** | `tests/plan_d/test_settings.py:51` calls `settings.app_postgres()` → `TypeError` (M11). **I3** |
| 40 | `test_tokens_audience` imports `jwks_for, make_token, rsa_key` from `tests.plan_d.test_tokens` (L4493) | **DENOUNCED** | That module exposes `keypair`, `mint`, `PEM1/JWK1/PEM2/JWK2`, `ISSUER`; the test is not executable as written. **I9** |
| 41 | Plan D incident-sim `FakeStore` needs no `reject` (L4926); `store.commits == []` after late POSTs (L4627) | **DENOUNCED** | The rewritten `post_incident` calls `st.reject` for the hash-mismatch and `"[1]"` cases Plan D tests post; Plan D's `FakeStore.commit` records every call. **I8** |
| 42 | Ruling 6: after a lost reply "the execute job is re-queued and the replay resends" | **DENOUNCED** | Task 6 `execute()` returns `True` unless the run is APPROVED; once mcp-write granted (EXECUTING) the retry finishes without resending. **I6** |
| 43 | R105 needs no change for T10 except evidence (L4455, L5036) | **DENOUNCED** | `test_r105…:158` asserts `(401, 401)` for persona and worker tokens at the destination; with `WrongAudience` both become 403 (realm audience mappers: worker → MCP resource URLs, persona → `ops-api`). **I7** |
| 44 | `skeleton.py up` refuses a database carrying the clock (L881–889) | **DENOUNCED (robustness)** | `clock_guard(settings.superuser_postgres(), …)` runs before `export_environment`, so from a plain shell it raises `SettingsError: OPS_SECRETS_DIR is not set`, uncaught. **I13** |
| 45 | Departures are all declared (privileges docstring, Task 9 errata) | **DENOUNCED** | Undeclared: sweeper `jobs.available_at`; `test_harness` USAGE/EXECUTE/CONNECT in every profile; `resolve_identity` granted to `sweeper` with no caller; `freeze_proposal` compares rather than injects `supersedes_run_id` (SA:453). **I15** |
| 46 | R009 "composite tenant foreign keys everywhere a child references a parent" (ruling 2) | **DENOUNCED (partial)** | M2: `execution_grant_proposal_id_fkey` and `proposals_draft_id_fkey` remain single-column. Minor m1 |
| 47 | TRANSITIONS → `app.transitions` rows; performer names match the SQL calls | PROVEN | M11 (`test_transitions_table` passes); M3 flow reached every performer row used |
| 48 | Research files and plan carry no machine-local paths or vendor names; plan commit has no attribution trailer | PROVEN | grep over the three files (only `$LOCALAPPDATA` as a variable, m8); `git log -3` shows no trailer |

---

## 2. Findings

### Blocking

**B1. `FOR SHARE` on tables where `app_definer` has no UPDATE privilege — `record_decision`, `grant_execution` and
`mark_unknown` fail on every call.**
Plan L2903 (`PERFORM 1 FROM proposals p … FOR SHARE`), L2910 (`memberships … FOR SHARE`), L2982 (`proposals … FOR
SHARE`), L2989 (`decisions … FOR SHARE`), L2996–2998 (`memberships … FOR SHARE`, `FOR SHARE OF m`), L3157
(`execution_grant … FOR SHARE`). PostgreSQL requires UPDATE on at least one column for any row-locking clause; the
matrix (L519–525, AM-20.2) gives `app_definer` only `sel`/`ins` on these four tables. Measured (M3 §2): `record_decision
approve: InsufficientPrivilege 42501 'permission denied for table proposals'`; `SET ROLE critic_app_definer` + `FOR
SHARE` → 42501 on `proposals`, `decisions`, `memberships`, `execution_grant`; OK on `runs` (which has column UPDATE).
The spec's AM-20.3 lock column and its AM-20.2 grants are mutually inconsistent; the plan inherits the conflict.
Correction (recommended): delete every `FOR SHARE` on those four tables — `runs … FOR UPDATE`, taken first in each
function, already serialises every writer of a run's proposal/decision/grant rows, and those three tables are
insert-only; for `memberships` the only writer is the sweeper (T11), so record that race as T11's. Replacement lines:
`SELECT * INTO v_proposal FROM proposals p WHERE p.proposal_id = p_proposal_id AND p.run_id = v_handle.run_id AND
p.tenant_id = v_handle.tenant_id;` (no lock), `IF NOT EXISTS (SELECT 1 FROM decisions d WHERE d.proposal_id =
p_proposal_id AND d.decision = 'approve') THEN`, the membership subqueries without `FOR SHARE`/`FOR SHARE OF m`, drop
L2903 entirely, and `SELECT * INTO v_grant FROM execution_grant g WHERE g.run_id = p_run_id;` in `mark_unknown`. Add
the lock-column change to the Task 9 errata (the alternative, a column UPDATE grant on four audit-adjacent tables,
contradicts AM-20.2's "proposals never need UPDATE").

**B2. Two SQLAlchemy bind parameters inside function bodies — revisions 0003 and 0004 cannot be applied.**
L2231 `v_run_id::text || ':1'` and L3164 `v_grant.action_id::text || ':timeout'`: a colon after a quote followed by a
word is a bind for `text()` (fact sheet §4.3's own rule). Measured (M0): `rev0003.upgrade: binds ['1']`,
`rev0004.upgrade: binds ['timeout']`; applying 0003 fails with `StatementError … A value is required for bind parameter
'1'` (M1). Correction: `v_run_id::text || ':' || '1'` and `v_grant.action_id::text || ':' || 'timeout'` (a colon
followed by a quote is not a bind). Add a DB-free unit test that loads each revision, collects every `op.execute`
string for `upgrade` and `downgrade`, and asserts `sqlalchemy.text(s)._bindparams == {}` (the M0 script is that test);
the Task 1 regex test only covers privilege renderers.

**B3. Wrong-caller tests expect `OC001`; PostgreSQL answers 42501 first.**
Because each migration revokes EXECUTE from PUBLIC and grants only the listed callers, a non-listed role never enters
the body. Measured (M9): `worker -> create_run: InsufficientPrivilege 42501 'permission denied for function
create_run'`; only the superuser reached `_authority` (`OC001 'ops may not call transition_run'`). Nine assertions are
wrong: L1850, L1867, L1941, L1987, L2517, L2544, L2587, L2616, L2660; Review Focus 3 ("`api` calling it → `OC001`")
and ruling 20's description of OC001 as the wrong-caller signal are wrong too, and the API's `AuthorityViolation`
handler (L4074) will never fire for a misconfigured role (42501 reaches the generic `psycopg.Error` → 503 handler).
Correction: expect `"42501"` in those nine places; prove `_authority` itself with one assertion per file through
`app_conn` (superuser bypasses the EXECUTE ACL), e.g. `assert await refused(app_conn, "SELECT app.transition_run(%s,
'QUEUED', 'RETRIEVING', NULL, 1, '{}')", (run,)) == "OC001"`; reword Review Focus 3 to "refused (42501 by the EXECUTE
ACL; OC001 by `_authority` for any session that holds EXECUTE through membership)".

**B4. Task 4 `freeze()` helper inserts the draft as `worker` without a tenant — five tests fail in setup.**
L2471–2475. `as_role(worker)` opens a transaction but sets no tenant; `drafts` is under FORCE RLS. Measured (M3 §1):
`freeze (set_tenant=False): InsufficientPrivilege 42501 'new row violates row-level security policy for table
"drafts"'`. Used by `test_record_decision…`, `test_rejection…`, `test_write_path…`, `test_mark_unknown…`,
`test_r106…`. Correction: first statement inside the block:
`await worker.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant),))`.

**B5. Async generator expression unpacked — four tests raise `TypeError` on their first line.**
L2575, L2598, L2651, L2684: `api, worker, mcp_read, mcp_exec = (await role_conn(r) for r in (...))` is an async
generator inside `async def`. Measured (M6): `cannot unpack non-iterable async_generator object`. Correction:
`api, worker, mcp_read, mcp_exec = [await role_conn(r) for r in (Role.API, Role.WORKER, Role.MCP_READ, Role.MCP_EXEC)]`.

**B6. Task 2 migrates the schema out from under the unchanged Plan D persistence code.**
Revision 0002 (L954–1007) makes `tenant_id` NOT NULL on six tables and drops `invocation_context.handle`, but Plan D's
`persistence.create_run`/`transition` insert `run_state_history (run_id, seq, …)` without `tenant_id`
(persistence.py:144–147, 110–113), `mint_handle`/`resolve_handle` use `handle`, the worker inserts `drafts`/`proposals`
without `tenant_id`, the API inserts `decisions` without it, mcp-write inserts grants/attempts without it. So: Task 2's
own `test_r007_r008…` and `test_r009…` (they call `new_run`, L1511/L1545) fail with 23502; Step 9's claim "Every other
live module still passes … the old persistence code still works as the superuser" (L1664) is false; every live module
except the new ones is red from Task 2 until Task 7, and so is any skeleton started against a migrated database.
Correction: in Task 2 make the role tests self-seeding (superuser INSERTs that write `tenant_id` into `runs`,
`run_directory` and `run_state_history`, no `persistence` call), state in Steps 9 and in Tasks 3–6 that
`test_worker_live`, `test_mcp_*_live`, `test_r105…` and the old `test_migrations_and_persistence` tests are expected
red until Task 7 (list them), and drop the "still passes" sentence; alternatively reorder so Task 5 (persistence)
lands in the same task as revision 0002.

### Important

**I1. mypy strict fails on `ops_core.privileges` (check.py RED at Task 1).** L604–605: `if grant.upd and grant.upd is not
True: … ', '.join(grant.upd)` → `error: Argument 1 to "join" of "str" has incompatible type "tuple[str, ...] |
Literal[False]"` (M11, `mypy --strict -p ops_core`). Correction: `if isinstance(grant.upd, tuple) and grant.upd:`.

**I2. ruff ISC004 ×31, not auto-fixable — check.py RED at Tasks 2 and 8.** Repo ruff (0.16 defaults include ISC):
`m0904.py` (revision 0002) 28 hits in `SCHEMA_CHANGES`/`DOWNGRADE`, `m1188.py` (tc_0001 `DDL`) 1, `m4765.py` (incident
0002 `UPGRADE`) 2 — "Unparenthesized implicit string concatenation in collection"; `ruff check --fix` does not apply
it (hidden unsafe fix). Correction: wrap every multi-line element in parentheses, e.g.
`("ALTER TABLE app.runs" " ADD COLUMN slot_held boolean NOT NULL DEFAULT false," …),`.

**I3. Task 1 breaks `tests/plan_d/test_settings.py` and misses a caller.** `test_settings.py:51` calls
`settings.app_postgres()` → `TypeError: app_postgres() missing 1 required positional argument: 'role'` (M11); Step 7
expects it to pass and Step 11 explains why it would. `tests/e2e/test_mcp_write_live.py:109` also calls it (renamed only
in Task 7). Correction: add both files to Step 5 (`superuser_postgres()`), and add `OPS_PG_SUPERUSER` to that test's
`delenv` list.

**I4. `persistence.insert_job` cannot be used by `api`, its only intended direct caller.** L3760–3770, note L3820.
`api` holds `ins` only on `jobs` (AM-20.2); `ON CONFLICT (dedup_key)` and `RETURNING id` need SELECT. Measured (M3 §8):
`insert_job as api: 42501 permission denied for table jobs`; spike §3 measured the same rule. Correction: either give
the API path `INSERT … ON CONFLICT DO NOTHING` with no target and no `RETURNING` (returning `None` when unknown), or
declare that `resume_input` will go through a definer function in T12 and remove the "API's resume_input insert" note;
the Task 5 live test must call `insert_job` as the role that will use it, not the superuser.

**I5. The SQL event rules diverge from their declared Python twin, and the late-evidence payload is one the twin
refuses.** (a) L3125–3131: on a terminal run `record_outcome` emits `action.late_evidence` with `{status, action_id,
receipt}` (or `{action_id, reason, tombstone}`, or `{action_id}` for CONFLICT); `event_rules_ok` requires
`outcome ∈ {SUCCEEDED, FAILED_NO_COMMIT}`. Measured (M3 §4): `python event_rules_ok: REFUSED: action.late_evidence
requires outcome SUCCEEDED or FAILED_NO_COMMIT`. The note at L3207 asserts the opposite. (b) L2121: `NOT ((p_payload->>
'reason') = ANY (…))` is NULL for a missing reason, so `action.failed` with `{}` is accepted (M3 §5; Python refuses).
(c) No receipt/tombstone/evidence_refs shape checks. Correction: late payload
`jsonb_build_object('outcome', p_outcome, 'action_id', p_action_id, 'receipt', p_document->'receipt')` for SUCCEEDED,
`… 'tombstone', p_document->'tombstone'` for FAILED_NO_COMMIT, and emit `action.conflict` (not late evidence) for a
CONFLICT on a terminal run; L2121 → `IF p_type = 'action.failed' AND (coalesce(p_payload->>'reason', '') <> ALL
(v_failed_reasons) OR p_payload ? 'receipt')`; add a live assertion that replays every event row the definer tests
wrote through `ops_core.outcomes.event_rules_ok` (catches any future drift).

**I6. Worker `execute()` never resends after the run reached EXECUTING — contradicts ruling 6.** L4211–4216 keep Plan
D's `if run["state"] != APPROVED: return True`. Ruling 6 (L47) relies on "the execute job is re-queued and the replay
resends". After `McpCallFailed` where mcp-write had granted (and maybe sent), the re-queued job sees EXECUTING, logs
"nothing to dispatch", finishes, and the run is stuck EXECUTING with no recover job (mcp-write no longer calls
`mark_unknown`). Correction: dispatch when `run["state"] in (APPROVED, EXECUTING)` (= `JOB_RULES[EXECUTE].run_states`);
`grant_execution` returns the existing grant and mcp-write resends under the same action id.

**I7. R105 still asserts 401 for foreign tokens at the destination.** `tests/e2e/test_r105_walking_skeleton.py:158`
`== (401, 401)`; after Task 8, `WrongAudience` → 403 for both (realm: worker `aud` = MCP resource URLs, persona `aud`
= `ops-api`). Tasks 7/8 do not mention it, though Task 8 commits that file. Correction: `== (403, 403)` with the
`action_id not in …text` assertion kept, in Task 8 Step 6.

**I8. Task 8 breaks Plan D incident-sim tests and one new test is wrong.** The new `post_incident` calls `st.reject`
for a hash mismatch and a non-object payload; Plan D's `FakeStore` has no `reject` → `AttributeError` (TestClient
re-raises) in `test_presented_hash_must_match_the_received_bytes` (both cases) and in `test_malformed_bodies_are_422`
(the `"payload_canonical": "[1]"` body now parses as an envelope and is rejected with 200). L4926 says Plan D's store
needs no `reject` and only one assertion changes. Separately, `test_abort_then_post…` asserts `store.commits == []`
(L4627) after two POSTs that the new code routes to `st.commit`, and Plan D's `FakeStore.commit` appends every call.
Correction: give Plan D's `FakeStore` `abort`/`reject` (first-writer-wins), change those Plan D expectations to `200`
+ `REJECTED` (`hash_mismatch`, `invalid_payload`), and replace L4627 with
`assert store.rows[ACTION].state == "ABORTED" and not any(r.state == "COMMITTED" for r in store.rows.values())`.

**I9. `test_tokens_audience` is not executable as written.** L4493 imports names that do not exist; Plan D exposes
`keypair`, `mint`, `PEM1/JWK1`, `PEM2`, `ISSUER`. Correction (concrete):
```python
from tests.plan_d.test_tokens import ISSUER, JWK1, PEM2, mint

@pytest.fixture
def verifier() -> TokenVerifier:
    v = TokenVerifier(issuer=ISSUER, audience="incident-sim", allowed_azp=frozenset({"ops-mcp-write"}), jwks_url="unused")
    v.install_keys({"keys": [JWK1]})
    return v
# good: mint(aud=["incident-sim"], azp="ops-mcp-write"); wrong: mint(aud=["ops-api"], azp="ops-mcp-write"),
# mint(aud=["incident-sim"], azp="ops-worker"); bad signature: mint(PEM2, kid="k1", aud=["incident-sim"], azp="ops-mcp-write")
```
(no `_key` attribute, no `noqa: SLF001`, which ruff flags as RUF100 because SLF is not enabled).

**I10. `test_persistence_errors.error()` cannot inject a DETAIL.** L3270–3275: `exc.__dict__["diag"] = …` is shadowed
by psycopg's `diag` property. Measured (M6, M11): `diag type: Diagnostic | message_detail: None`;
`test_refused_carries_the_detail_code…` fails with `Refused('REFUSED')`. Correction:
```python
class FakeError(psycopg.DatabaseError):
    def __init__(self, sqlstate: str, detail: str | None) -> None:
        super().__init__("x")
        self._fake = (sqlstate, detail)
    @property
    def sqlstate(self) -> str: return self._fake[0]  # tests are not under mypy, so no override annotation is needed
    @property
    def diag(self) -> Any: return SimpleNamespace(message_detail=self._fake[1], message_primary="x")
```
(or translate from `exc.diag` via a small adapter the test can stub).

**I11. The destination-isolation probe expects the wrong error.** L4959–4960 `SELECT 1 FROM app.runs` as `incident` on
`incident_test` → `UndefinedTable 42P01` (M8), not `InsufficientPrivilege`. Correction: prove the real boundary —
`with pytest.raises(psycopg.OperationalError, match="permission denied for database"): await psycopg.AsyncConnection.connect(<incident credentials, dbname=ops_test>)`
(CONNECT is narrowed by `ensure_roles`).

**I12. The role bootstrap can print a password.** L732–747 (and the inherited `ensure_incident_role`): any failure of
the `EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', …)` carries the formatted statement in the error CONTEXT.
Measured (M5, dummy literal): `password literal in str(exc): True | in diag.context: True`, and the setting is left in
the session. The e2e fixture's `assert migrate(Profile.TEST) == 0` would print it on, e.g., a concurrent-migrate
`42710 duplicate role`. Correction: inside the DO block
`BEGIN EXECUTE …; EXCEPTION WHEN OTHERS THEN RAISE EXCEPTION 'role bootstrap failed for %', current_setting('ops.role_name') USING ERRCODE = SQLSTATE; END;`
(a handled error is not logged and the re-raise's context names only the DO block), and reset both settings in a
Python `try/finally`.

**I13. `skeleton.py up` crashes before refusing.** L881–889 put `clock_guard(settings.superuser_postgres(), …)` before
anything in `up()` has loaded `.env`; `export_environment` runs only later inside `Skeleton.start()`. From a shell
without `OPS_SECRETS_DIR` this is an uncaught `SettingsError` (only `RuntimeError` is caught). Correction: first line of
`up()` `export_environment(load_dotenv(ROOT / ".env"))`; catch `(RuntimeError, settings.SettingsError)`.

**I14. R006 fails at Task 2.** L1355 `len(versions) == 2`. Measured (M10): with `tc_0001` `depends_on` the main head,
`upgrade heads` stores one row (`[('tc_0001_test_clock',)]`); two rows appear only once 0003 exists. Correction:
`assert "tc_0001_test_clock" in versions` only, and after re-migration `== versions` (already there).

**I15. Departures that are not declared, or declared wrongly.** (a) `_JOB_COLUMNS` (L470) gives the **sweeper**
`jobs.available_at` too; the privileges docstring (L423–425) and the Task 9 errata name only the worker. (b) Ruling 3:
`test_harness` "holds grants only where the testclock branch is applied" — false: revision 0002 grants it `USAGE` on
schema `app` (L590) and EXECUTE on `app.current_time()` (L557) in every profile, and `narrow_connect` grants it CONNECT
on the dev database; SA:403/SA:160 say the role exists only in the test profile. (c) `resolve_identity` is granted to
`sweeper` (L558) with no caller — the very thing ruling 1 rejects for stubs. (d) `freeze_proposal` compares the
worker-supplied `supersedes_run_id` instead of injecting `runs.supersedes_run_id` and refusing a draft that carries one
(SA:453, SA:155); and `PAYLOAD_RUN_MISMATCH` is raised as `OC007` (L2855) while ruling 20 lists it under `OC005`.
Correction: either align (sweeper keeps `_JOB_COLUMNS` minus `available_at`; drop `sweeper` from `resolve_identity`;
create `test_harness` only in the test profile or revoke its USAGE/EXECUTE/CONNECT outside it) or list each in the
Task 9 errata and the privileges docstring; fix ruling 20's table.

**I16. Task 5 Step 4's `new_run` code calls `create_run` on the superuser connection.** L3832–3838 — the function
refuses (`_authority`: superuser → `OC001`, measured M9); the correction is only in the following prose. Correction:
make the code block itself take `api: persistence.Conn` and call `persistence.create_run(api, …)` inside
`async with api.transaction():` (no `set_tenant` needed).

### Minor

- **m1. R009 coverage gaps.** `execution_grant_proposal_id_fkey` and `proposals_draft_id_fkey` stay single-column (M2).
  Add `UNIQUE (tenant_id, id)` on `drafts` and composite FKs `execution_grant (tenant_id, proposal_id) → proposals` and
  `proposals (tenant_id, draft_id) → drafts`, or narrow ruling 2's "everywhere".
- **m2.** `jobs.tenant_id` nullable with MATCH SIMPLE lets a row with a `run_id` and a NULL tenant skip the composite FK
  (writable only through `sweeper_all WITH CHECK (true)`); add `CHECK ((run_id IS NULL) = (tenant_id IS NULL))`.
- **m3.** `claim_job`/`requeue_job`/`finish_job` and `insert_job` keep `now()` (L3783–3803) against the Global
  Constraint "every lease, expiry, freshness and deadline comparison uses `app.current_time()`" and SA:156 "never use
  `now()`"; use `app.current_time()` or declare.
- **m4.** `test_r106…` asserts `count(*) FROM app.execution_grant == 0` globally (L2694); scope it to the two runs.
- **m5.** The "foreign payload" freeze case (L2515–2516) fails on the draft hash, not on `PAYLOAD_RUN_MISMATCH`; write a
  draft whose hash is the foreign bytes' to reach that guard.
- **m6.** ruff auto-fixable noise in the plan's blocks: I001 ×7, F401 ×4 (`purge_tenant`, `ToolOutcome`, `typing.Any`,
  `pytest`), RUF100 ×5 (`noqa: E402`, `noqa: SLF001` on non-enabled rules). `--fix` handles them.
- **m7.** L642 "fourteen+seven secrets": `SECRET_NAMES` has 13 today (13 + 7 = 20).
- **m8.** L321 lists `$LOCALAPPDATA/ops-copilot/secrets`; use the `OPS_SECRETS_DIR` written to `.env` (the bootstrap
  honours an override).
- **m9.** CODE_COMMENTS rule 9: public dataclasses `Appended`, `Frozen`, `Decided`, `Invocation`, and `NotFound`,
  `VersionConflict`, `HandleRejected`, `HashMismatch` lack docstrings; rule 7: L285's `# Task 6/7 switches this …`
  should be `TODO(T09): …`.
- **m10.** mcp-write `create_incident` (L4414–4416) runs `record_outcome` and `lookup_action` in one unit;
  `lookup_action` re-checks handle expiry (60 s), so a slow destination could roll the recorded outcome back with
  `HandleRejected`. Use `record_outcome`'s return and a separate unit for the read-back.
- **m11.** Task 9 offers importing `Profile` "inside `main`"; `check_profile`/`environment_for` use it at call time
  (L5084–5097), so the import must be module-level.
- **m12.** SA:452 refuses only `run.*`, `action.*`, `review.*` from `append_event`, so `api`/`worker`/`sweeper` can
  still write `approval.recorded` and `proposal.ready`; propose refusing every type a definer function emits.
- **m13.** The R047 race (L4993–4996) calls `keys.commit` on an autocommit connection outside a unit, so key and
  incident commit separately — not the production atomicity BS §10 asks for; wrap each side in `conn.transaction()`.
- **m14.** Tasks 5–6 allow `check.py` mypy residue, contradicting Global Constraint L26 ("GREEN after every task");
  declare the exception in the Global Constraints.
- **m15.** L2362's mechanism ("`op.execute` passes no parameters, so psycopg sends the text verbatim") is wrong
  (SQLAlchemy doubles `%`, passes `{}`, psycopg un-doubles); outcome correct (M9). Fix the sentence.
- **m16.** `sessions`/`idempotency_request` sweeper `del` without `sel` cannot run `DELETE … WHERE expires_at < …`
  (spike §3: column reads need SELECT); spec-level, flag for T11/T12.
- **m17.** L1664's fallback (`app@0001_walking_skeleton` if "Multiple head revisions") is unnecessary: `downgrade
  0001_walking_skeleton` succeeds even with the testclock branch applied (M10).
- **m18.** Observation, not a plan defect: at review time the dev cluster already holds roles `api`, `app_definer`,
  `incident_owner`, `mcp_exec`, `mcp_read`, `migrator`, `operator`, `sweeper`, `test_harness`, `worker` and databases
  `ops_test`, `incident_test` (read-only `pg_roles`/`pg_database` listing); created outside this review and untouched
  by it. Ruling 16's "no `spike_*` roles" holds.

---

## 3. Scratch measurements

All scripts live in the session scratch directory (`…/scratchpad/critic/`), run with the repository's `.venv` Python
(`PYTHONUTF8=1 .venv/Scripts/python.exe <script>`). `common.py` reads the superuser password from the file named by
`.env`'s `OPS_SECRETS_DIR` and never prints it; the `critic_*` login password was a scratch value generated per run,
kept in a scratch file, never printed, and deleted at the end. `sub()` renames schema `app` → `critic_app` and every
AM-20.1 role → `critic_<role>`; the GUC `app.tenant_id` is unchanged.

**Extraction** — `extract.py` / `extract_all.py`: every ```` ```python ```` block whose text starts with a module
docstring, located by its first line (e.g. `'"""The AM-20 privilege matrix as data'`), written verbatim.

**M11 — static (mypy, ruff, unit tests)**
```
$ (corecopy = core/src/ops_core + plan settings block + plan persistence/privileges/testing.faults)
$ python -m mypy --strict --python-version 3.13 -p ops_core
ops_core\privileges.py:190: error: Argument 1 to "join" of "str" has incompatible type "tuple[str, ...] | Literal[False]"; expected "Iterable[str]"  [arg-type]
Found 1 error in 1 file (checked 14 source files)
$ python -m ruff check --no-cache --statistics .     (allmods/, with the repo pyproject.toml copied in)
31  ISC004  [ ] implicit-string-concatenation-in-collection-literal
 7  I001    [*] unsorted-imports
 5  RUF100  [*] unused-noqa
 4  F401    [*] unused-import
(ISC004 in m0904.py = revision 0002 ×28, m1188.py = tc_0001 ×1, m4765.py = incident 0002 ×2)
$ PYTHONPATH=../corecopy python -m pytest -q test_privileges.py test_settings_roles.py test_persistence_errors.py test_faults.py test_transitions_table.py  (bootstrap-list test deselected)
FAILED test_persistence_errors.py::test_refused_carries_the_detail_code_and_other_errors_pass_through
  AssertionError: assert (True and 'REFUSED' == 'SLOT_OCCUPIED'
1 failed, 31 passed, 1 deselected
$ PYTHONPATH=../corecopy python -m pytest -q test_plan_d_settings.py   (= tests/plan_d/test_settings.py)
E       TypeError: app_postgres() missing 1 required positional argument: 'role'
1 failed, 4 passed
```

**M0 — bind scan** (`m0_binds.py`: every `op.execute` string of the four revisions, upgrade and downgrade, compiled by
`sqlalchemy.text`):
```
rev0003.upgrade: binds ['1'] in statement starting 'CREATE OR REPLACE FUNCTION app.create_run(p_tenant_id uuid, p_conversation_id uu'
rev0004.upgrade: binds ['timeout'] in statement starting 'CREATE OR REPLACE FUNCTION app.mark_unknown(p_run_id uuid, p_fence bigint) RETUR'
scan done
```

**M1 — build** (`m1_build.py`: `DROP DATABASE IF EXISTS critic_e WITH (FORCE)`, `CREATE DATABASE critic_e OWNER ops`
from `postgres`; `critic_*` roles; revision 1's DDL via its own `split(";\n")` plus the seed tenants/memberships;
then each plan revision's `upgrade()` with `op` replaced by a shim that calls `conn.execute(sa.text(sub(s)))` inside
`engine.begin()`):
```
rev1: OK
rev0002: upgrade OK (233 statements)
revtc: upgrade OK (6 statements)
rev0003: FAILED: StatementError: (sqlalchemy.exc.InvalidRequestError) A value is required for bind parameter '1'
```
Re-run with the shim rewriting only `':1'` → `':' || '1'` and `':timeout'` → `':' || 'timeout'` (B2's correction):
```
rev1: OK / rev0002: upgrade OK (233) / revtc: upgrade OK (6) / rev0003: upgrade OK (23) / rev0004: upgrade OK (32)
```

**M2 — catalogs** (`m2_catalog.py`, superuser on `critic_e`; abridged only where marked):
```
-- FKs and uniques: action_attempt_tenant_action_fkey, action_attempt_tenant_attempt_key, action_attempt_state_tenant_attempt_fkey,
   decisions_tenant_proposal_fkey, drafts_tenant_run_fkey, events_tenant_run_fkey, execution_grant_proposal_id_fkey (single-column),
   execution_grant_tenant_action_key, execution_grant_tenant_run_fkey, jobs_tenant_run_fkey, messages_tenant_message_key,
   proposals_draft_id_fkey (single-column), proposals_tenant_proposal_key, proposals_tenant_run_fkey, runs_tenant_message_fkey,
   run_state_history_tenant_run_fkey, … (34 rows)
-- distinct tenant_isolation qual: {"(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)"}
   equals POLICY_QUAL: True ; with_check == qual everywhere: True
   sweeper_all rows: [('jobs', ['critic_sweeper'], 'true', 'true'), ('memberships', ['critic_sweeper'], 'true', 'true')]
-- create_run  owner=critic_app_definer secdef=True config=['search_path=critic_app, pg_temp', 'app.tenant_id='] acl={critic_app_definer=X/critic_app_definer,critic_api=X/critic_app_definer}
   _transition owner=critic_app_definer secdef=False config=['search_path=critic_app, pg_temp'] acl={critic_app_definer=X/critic_app_definer}
   (all 22 functions printed; helpers carry no tenant attribute; stray functions vs DEFINER|HELPER: [])
-- R124 enumeration exactly as test_roles_live.actual_privileges does it
   actual == expected: True ; PUBLIC table rows: 0
-- owners [{'tableowner': 'critic_migrator'}] {'o': 'critic_migrator'} ; flags: {'forced': 13, 'tables': 20}
```

**M3 — the functions as their roles** (`m3_flow.py`; the plan's own calls, renamed; long result rows abridged with …):
```
== 1. the plan's freeze helper as written (worker INSERT on drafts without a tenant)
create_run: OK {'run_id': UUID('44d7…'), 'state_version': 1}
QUEUED->RETRIEVING: OK {'v': 2} / RETRIEVING->DRAFTING: OK {'v': 3}
freeze (set_tenant=False): InsufficientPrivilege 42501 'new row violates row-level security policy for table "drafts"'
== 2. FOR SHARE without UPDATE privilege
freeze (set_tenant=True): OK {'proposal_id': …, 'revision': 1, 'state_version': 4}
record_decision approve: InsufficientPrivilege 42501 'permission denied for table proposals' detail=None
   proposals FOR SHARE: 42501 'permission denied for table proposals'
   decisions FOR SHARE: 42501 'permission denied for table decisions'
   memberships FOR SHARE: 42501 'permission denied for table memberships'
   execution_grant FOR SHARE: 42501 'permission denied for table execution_grant'
   runs FOR SHARE: OK
== 3. rest of the write path (scratch-only GRANT UPDATE (tenant_id) ON those four tables TO critic_app_definer)
record_decision approve: OK {'run_id': …, 'state': 'APPROVED', 'state_version': 5}
grant_execution: OK {… 'attempt_state': 'INTENT', 'detail': None}
mark_sent: OK {'r': 'sent'} ; mark_sent again: OK {'r': 'already_sent'}
record_outcome SUCCEEDED: OK {'r': 'SUCCEEDED'} ; lookup_action: OK {'attempt_state': 'RESOLVED', 'r': {receipt…}}
   events: [(1,'run.accepted','application'), (2,'proposal.ready','application'), (3,'approval.recorded','application'),
            (4,'action.granted','application'), (5,'action.dispatched','application'), (6,'action.confirmed','destination')]
   run: {'state': 'SUCCEEDED', 'state_version': 7, 'slot_held': False, 'next_event_seq': 6}
== 4. late evidence on a terminal run
mark_unknown run2: OK {'s': 'OUTCOME_UNKNOWN'}
   run2 jobs: [investigate '<run>:1', execute '<proposal>', recover '<action>:timeout']
record_outcome on a FAILED run: OK {'r': 'SUCCEEDED'}
   last event: action.late_evidence destination ['action_id', 'receipt', 'status']
   python event_rules_ok: REFUSED: action.late_evidence requires outcome SUCCEEDED or FAILED_NO_COMMIT
== 5. SQL _append_event vs Python twin on action.failed without a reason
   SQL _append_event(action.failed, {}): accepted seq 7
   python: REFUSED: action.failed requires a reason from the FAILED_NO_COMMIT set
== 6. record_outcome FAILED_NO_COMMIT: run {'state': 'FAILED', 'reason': 'rejected', 'slot_held': False} last action.failed/destination
      record_outcome CONFLICT:         run {'state': 'ESCALATED', 'reason': 'conflict', 'slot_held': False} last action.conflict/destination
== 7. resolve_identity(alex) with preset beta: OK [{'tenant_id': alpha, 'role': 'requester'}] ; caller setting after: beta
      bare SELECT count(*) FROM runs with GUC '': OK {'n': 0} ; current_time as mcp_read: OK {'ok': True}
== 8. insert_job as api: 42501 permission denied for table jobs
      claim_job as worker tenant=3ea79c95: ('investigate', alpha) ; requeue_job + finish_job as worker: OK
      worker runs FOR UPDATE, messages SELECT, mint_handle INSERT: OK
```

**M4 — downgrade and re-upgrade on the populated database** (`m4_downgrade.py`):
```
rev0004: downgrade OK (12 statements) / rev0003: downgrade OK (9) / revtc: downgrade OK (1) / rev0002: downgrade OK (55)
after downgrade: policies (0,) tables (15,) owner [('ops',)] functions (0,) column grants left (0,) slot index ("… WHERE (state = ANY (ARRAY['QUEUED'::text, …, 'OUTCOME_UNKNOWN'::text]))",)
rev0002: upgrade OK (233) / revtc: upgrade OK (6) / rev0003: upgrade OK (23) / rev0004: upgrade OK (32) / re-upgrade done
```

**M5 — role bootstrap** (`m5_roles.py`: the plan's `ensure_login_role`/`ensure_nologin_role` exec'd from the plan
block; dummy password literal `critic-dummy-not-a-secret`; the failing call uses the reserved prefix `pg_` so nothing is
created):
```
create: ok / re-key: ok / rolcanlogin: (True,) / nologin+bypassrls: (False, True)
failing EXECUTE: 42939 | password literal in str(exc): True | in diag.context: True
   setting left behind in the session: True
probe roles dropped
```

**M6 — Python semantics** (`m6_python.py`):
```
sqlstate: OC005 | diag type: Diagnostic | message_detail: None
42501 sqlstate after assignment: 42501
unpack TypeError: cannot unpack non-iterable async_generator object
list comprehension ok: api worker
```

**M7 — clock and refusals** (`m7_clock_r084.py`):
```
api delta before: -1 day, 23:59:59.999992 ; api delta after GUC: -1 day, 23:59:59.999999
harness UPDATE no WHERE: OK -> 1 ; api delta after harness: 2 days, 23:59:59.999996
harness SELECT: InsufficientPrivilege 42501 ; harness INSERT second row: UniqueViolation 23505 "test_clock_pkey"
api UPDATE test_clock: 42501 ; mcp_read SELECT runs FOR UPDATE: 42501
api UPDATE runs SET cancel_requested WHERE false: OK -> 0 ; api UPDATE runs SET state WHERE false: 42501
api INSERT events ON CONFLICT DO NOTHING: 42501
```

**M8 — destination** (`m8_incident.py`: `critic_inc` with incident revision 1 (via its `split`) plus the plan's
incident 0002 `UPGRADE` tuple, one COMMITTED and one ABORTED row present before the upgrade):
```
incident 0002 upgrade: OK on a table holding a COMMITTED and an ABORTED row
INSERT ... ON CONFLICT (action_id) DO NOTHING RETURNING * with nextval: OK -> ('COMMITTED',)
INSERT incidents: OK -> 1
DELETE …: 42501 ; UPDATE …: 42501 ; TRUNCATE: 42501
CHECK: REJECTED with incident_id: CheckViolation 23514 "action_key_incident_iff_committed"
plan's isolation probe: SELECT 1 FROM app.runs (database has no schema app): UndefinedTable 42P01 'relation "app.runs" does not exist'
owner: ('critic_incident_owner',)
```

**M9 — `%` handling and the EXECUTE ACL** (`m9_percent.py` + one inline call):
```
worker -> create_run (OC001 DETAIL): InsufficientPrivilege 42501 'permission denied for function create_run'
worker append_event run.failed (LIKE 'run.%'): DatabaseError OC006 'event_rule_violation' detail='reserved type'
worker append_event runXfailed (LIKE must not match): OK -> (7,)
superuser -> _authority (format %s in DETAIL): DatabaseError OC001 'authority_violation' detail='ops may not call create_run'
superuser -> transition_run: DatabaseError OC001 'authority_violation' detail='ops may not call transition_run'
```

**M10 — Alembic with the plan's branch layout** (`alem/drive.py` over a scratch tree whose revisions carry the plan's
ids, `branch_labels` and `depends_on`; version table in schema `critic_alembic` of `critic_e`):
```
upgrade heads (Task 2: 0002 is the main head)   ok | versions=[('tc_0001_test_clock',)]
downgrade testclock@base                        ok | versions=[('0002_roles_grants_rls',)]
downgrade 0001_walking_skeleton                 ok | versions=[('0001_walking_skeleton',)]
upgrade heads again                             ok | versions=[('tc_0001_test_clock',)]
upgrade heads (Task 3+: 0003 exists)            ok | versions=[('0003_run_path_functions',), ('tc_0001_test_clock',)]
downgrade testclock@base                        ok | versions=[('0003_run_path_functions',)]
downgrade 0001_walking_skeleton                 ok | versions=[('0001_walking_skeleton',)]
downgrade 0001 WITHOUT removing testclock first ok | versions=[('0001_walking_skeleton',)]
fresh: upgrade app@head (dev)                   ok | versions=[('0003_run_path_functions',)]
```

**Cleanup**
```
dropped roles: ['critic_api', 'critic_app_definer', 'critic_incident', 'critic_incident_owner', 'critic_mcp_exec', 'critic_mcp_read',
                'critic_migrator', 'critic_operator', 'critic_sweeper', 'critic_test_harness', 'critic_worker']
left critic roles: 0 | left critic dbs: 0 | ops/incident dbs: [('incident',), ('ops',)]
scratch password file removed
```
Read-only listing used for m18: `SELECT rolname FROM pg_roles WHERE rolname !~ '^pg_'` and
`SELECT datname FROM pg_database`.

---

## 4. Summary

The plan's architecture holds up under execution: the grant matrix renders exactly what R124 enumerates, the NULLIF
policy text is what `pg_policies` stores, the attribute-plus-local-`set_config` pattern ignores and restores a hostile
preset, RETURNS TABLE bodies resolve without ambiguity, revision 0002 converts a populated revision-1 schema and comes
back off cleanly, and the destination's grants make keys permanent. But it does not execute as written. Revisions 0003
and 0004 cannot be applied (two `:word` binds); once they are, every decision, grant and UNKNOWN fails because
`FOR SHARE` needs an UPDATE privilege the matrix (and the spec) never give `app_definer`; and the test layer encodes
wrong expectations in four systematic ways (42501 not OC001 for non-grantees, a worker draft insert without a tenant,
async-generator unpacking, Task 2's reliance on the unchanged Plan D persistence code against the new NOT NULL tenant
columns). Beyond those six blockers, sixteen important defects would turn gates red or leave a real gap: a mypy error
and 31 non-auto-fixable ruff findings, broken Plan D tests in Tasks 1 and 8, R105's 401→403, an `insert_job` the API
cannot use, SQL event rules that diverge from their declared Python twin (the late-evidence payload is one the twin
refuses), a worker that never resends once the run is EXECUTING (contradicting ruling 6), a password that can reach an
exception, and four undeclared spec departures. Every finding above names the line and a concrete correction; with
B1–B6 fixed and the M0 bind scan and an "all emitted events pass `event_rules_ok`" assertion added as tests, the plan
is ready for a second round.

---

## Round 1 — builder dry run

# Plan E dry run, builder round 1

Plan under test: `docs/superpowers/plans/2026-10-08-first-slice-e-roles-rls-definers.md`, as of commit f04204d.
The run used a throwaway worktree (`<worktree>`) on a detached HEAD at f04204d. It executed Tasks 1–9 in order, with one
commit per task (10 commits, `05b2623..85575c3`). Every command ran through Git Bash and `uv run`. The dev stack was
PostgreSQL 17 at 127.0.0.1:15432 and Keycloak at :18080. The live suite ran only against `ops_test` and `incident_test`
with `PROFILE=test`.

**Result:** the plan reaches its end state with every gate green, but only after **27 workarounds**. Ten of them change
production code or SQL that the plan gives verbatim: W2, W8, W11, W14, W18, W20, W26, plus the formatting and lint
fixes W3, W4 and W7. The other 17 fix test code, or fill in prose-only steps where the plan's wording was wrong.

## 1. Per-task table

| Task | Steps executed | Outcome | Workarounds |
|---|---|---|---|
| 1 | 1–12 | Done. Unit tests 14 passed. check.py GREEN: 472 passed, 45 skipped. | W1, W2, W3 |
| 2 | 1–10 | Revision 0002 and `tc_0001` apply. R124, R084, R128, R106, R126 and the clock guard pass. 7 of 15 tests in the three named modules fail (W5, W6). Full `tests/e2e`: 15 failed, 10 passed. | W4, W5 (no fix possible), W6 (passes from Task 3), W7 |
| 3 | 1–5 | 0003 applies after W8. Run-path live tests: 7 passed. With roles and persistence: 6 failed (all W5), 14 passed. R006 passes from here on. | W8, W9, W10 |
| 4 | 1–4 | 0004 applies after W11. Write-path live tests: 8 passed. With run-path and roles: 2 failed (W5), 20 passed. | W9, W10, W11, W12, W13, W14 |
| 5 | 1–6 | Persistence rewritten verbatim. Plan E unit tests: 35 passed. Persistence and roles live: 13 passed. mypy residue: 48 errors in 8 service files (the plan allows this). Full `tests/e2e`: 7 failed, 32 passed, 1 error (the plan expects this). | W15, W16 |
| 6 | 1–7 | api and worker on their roles. Worker and write-path live: 12 passed. mypy residue: 22 errors in 4 files (mcp-read, mcp-write, incident-sim). | W17, W18 |
| 7 | 1–5 | mcp-read and mcp-write on their roles. R105: 1 passed. `tests/e2e` + `tests/plan_b/live`: 50 passed. check.py GREEN: 489 passed, 71 skipped. | W19, W20 |
| 8 | 1–7 | T10 complete. Unit tests: 82 passed. `tests/e2e`: 44 passed. check.py GREEN: 500 passed, 74 skipped. | W4 (again), W21, W22, W23, W24, W25 |
| 9 | 1–5 | check.py dev GREEN (502 passed, 74 skipped). check.py `--profile test` GREEN (555 passed, 21 skipped). `verify_handoff.py` exit 0. | W26, W27 |

## 2. Workarounds in detail

"Plan" means the plan's text was wrong. "Environment" means the plan was right and the machine got in the way.
**All 27 are the plan's fault.** None was caused by the environment.

### Production code and SQL

**W2. mypy strict rejects `privileges.grant_statements`** (Task 1, Step 10; plan).
- Plan code: `if grant.upd and grant.upd is not True: … ', '.join(grant.upd)`.
- `check.py` reported: `core\src\ops_core\privileges.py:192: error: Argument 1 to "join" of "str" has incompatible type "tuple[str, ...] | Literal[False]"; expected "Iterable[str]"  [arg-type]`.
- Fix: `if isinstance(grant.upd, tuple) and grant.upd:`.

**W3. A renamed line exceeds the format width** (Task 1, Steps 5 and 11; plan).
- After the rename, `worker/src/ops_worker/main.py:82` (`probe = …superuser_postgres())  # the health server's own connection …`) is over 120 columns.
- Step 11's `ruff format` list omits the renamed files, so `check.py` failed: `1 file would be reformatted`.
- Fix: moved the comment onto its own line above.

**W4. ruff ISC004 on statement tuples** (Task 2, Steps 4–5, and Task 8, Step 3; plan).
- Ruff 0.16 reports `ISC004 Unparenthesized implicit string concatenation in collection` 27 times in `0002_roles_grants_rls.py`, twice in `tc_0001_test_clock.py` and twice in the incident revision `0002_destination_hardening.py`.
- Fix: `ruff check --fix --unsafe-fixes`, which only adds parentheses.

**W7. Unused `noqa`** (Task 2, gate; plan).
- `check.py` RED: `RUF100 [*] Unused noqa directive (non-enabled: E402)` in `tests/plan_e/test_skeleton_cli.py`. The same `noqa` appears in Task 9's `test_check_cli.py`.
- Fix: `ruff check --fix`.

**W8. A SQLAlchemy bind parameter inside `create_run`** (Task 3, Step 3; plan).
- Revision 0003 failed to apply: `sqlalchemy.exc.StatementError: (sqlalchemy.exc.InvalidRequestError) A value is required for bind parameter '1'`.
- The cause is `v_run_id::text || ':1'` in `CREATE_RUN`. SQLAlchemy's bind pattern matches `:1` because the preceding quote is not a word character.
- The plan's guard misses this case: the global constraint says "no ` :name` text", and the Task 1 test's regex `(?<![:\w]):\w` only checks rendered GRANT/POLICY statements.
- Fix: `format('%s:1', v_run_id)`.

**W11. The same bind defect in `mark_unknown`** (Task 4, Step 2; plan).
- `A value is required for bind parameter 'timeout'`, from `v_grant.action_id::text || ':timeout'`.
- Fix: `format('%s:timeout', v_grant.action_id)`.

**W14. `FOR SHARE` needs UPDATE privilege, which `app_definer` does not hold** (Task 4, Step 2; plan).
- Error at runtime: `psycopg.errors.InsufficientPrivilege: permission denied for table proposals`, CONTEXT `SQL statement "SELECT 1 FROM proposals p WHERE p.proposal_id = p_proposal_id FOR SHARE"`, `PL/pgSQL function record_decision(...) line 17`.
- PostgreSQL requires UPDATE privilege for any row-locking clause. The plan's matrix gives `app_definer` only SELECT and INSERT on `proposals`, `decisions`, `memberships` and `execution_grant`.
- Seven sites in 0004 lock rows this way: `record_decision` ×2, `grant_execution` ×4 and `mark_unknown` ×1. The functions create, but `record_decision`, `grant_execution` and `mark_unknown` fail at their first call.
- Fix: removed all seven `FOR SHARE` clauses. The `runs … FOR UPDATE` lock still serialises (`app_definer` has column UPDATE on `runs`).
- Consequence: the AM-12 lock order the plan claims ("runs FOR UPDATE before proposals/decisions FOR SHARE") cannot be met under its own grant matrix. Either grant `app_definer` UPDATE on a harmless column of each table, or drop the claim.

**W18. `handlers.execute` re-queues without setting the tenant** (Task 6, Step 4; plan code; a production defect).
- On `McpCallFailed`, the handler runs `requeue_job` in a unit that never calls `set_tenant`. RLS hides the job row from `worker`, so the UPDATE silently affects 0 rows.
- The job stays claimed and never becomes available again. In production every execute job would be stranded after one transport failure.
- Found because the requeue test failed: `{'free': False, 'later': False} != {'free': True, 'later': True}`.
- Fix: `await persistence.set_tenant(deps.conn, job["tenant_id"])` before `requeue_job`.

**W20. incident-sim's `Session.read` is a runtime break, not only a mypy finding** (Task 7, Step 4; plan).
- The plan says the only residue after Task 7 is the mypy error at incident-sim `app.py:112`. At runtime, `/health/ready` raises `AttributeError: 'Session' object has no attribute 'read'`.
- The skeleton therefore never becomes ready: `RuntimeError: not ready in 90.0s: ['incident-sim']` (`1 error in 102.91s`), so R105 cannot pass in Task 7.
- Fix (pulled forward from Task 8): `await st.session.ping()`.

**W26. Where `check.py` imports `Profile`** (Task 9, Step 1; plan).
- The plan offers two places for the import: "inside `main` after `members_importable`", or "at module level guarded the same way".
- The first is impossible: `check_profile` and `environment_for` are module-level functions that need `Profile`, and the test imports them directly.
- A lazy import inside each function trips ruff: `F821 Undefined name Profile` on the annotations.
- Fix: an `if TYPE_CHECKING:` import, plus lazy imports inside the two functions, which keeps the `members_importable` guard meaningful.

### Interim-state claims and test sequencing

**W1. The rename list misses two callers** (Task 1, Step 5; plan).
- Step 5 lists six callers of `settings.app_postgres()`. Two more exist: `tests/plan_d/test_settings.py:51` and `tests/e2e/test_mcp_write_live.py:109`.
- Step 7 failed: `TypeError: app_postgres() missing 1 required positional argument: 'role'`. This contradicts Step 11's claim that "Plan D's settings test still passes".
- Fix: renamed both to `superuser_postgres()` and added them to the commit, which also omits them.

**W5. The old persistence layer is not compatible with revision 0002** (Task 2, Step 9; plan; no workaround possible).
- Step 9 claims "the old persistence code still works as the superuser" and "every other live module still passes". Neither holds.
- `persistence.create_run` failed with `NotNullViolation: null value in column "tenant_id" of relation "run_state_history"`, and `invocation_context.handle` is dropped by 0002.
- In the three named modules: `7 failed, 8 passed`. Full `tests/e2e`: `15 failed, 10 passed in 33.76s`. The API in R105 returned 503.
- The failures persisted through Task 4 and cleared only when Tasks 5–7 rewrote the code. I proceeded without a workaround.

**W6. R006 assumes two version rows at Task 2** (Task 2, Step 9; plan sequencing).
- The test asserts `len(versions) == 2`. At Task 2 `alembic_version` holds only `{'tc_0001_test_clock'}`.
- Reason: `tc_0001` `depends_on` 0002, which is then the main-line head, so Alembic stores only the dependent head. The spike's `depends_on` pointed at a non-head base, which is why it saw two rows.
- The test passes unchanged from Task 3 on, once 0003 exists. The down/up sequence itself works at Task 2 (measurements, §3).

**W10. Plan test files are not formatted** (Tasks 3 and 4, gates; plan).
- `check.py` RED on `ruff format --check` for `test_definers_run_path_live.py` (Task 3) and `test_definers_write_path_live.py` (Task 4). The plan code exceeds 120 columns, and neither task lists a format step.
- Fix: `ruff format`.

### Test code and prose-only steps

**W9. `OC001` is unreachable for callers without EXECUTE** (Tasks 3 and 4, Step 2; plan).
- Nine assertions expect `OC001`; all get `42501`.
- The four in Task 3: `create_run` by worker, `transition_run` by api, `resolve_identity` by worker, `revoke_handles` by api. The five in Task 4: `freeze_proposal` by api, `record_decision` by worker, `resolve_invocation` by api, `grant_execution` by worker, `mark_unknown` by mcp_exec.
- Because each creating migration runs `REVOKE … FROM PUBLIC`, PostgreSQL refuses "permission denied for function" before `_authority` ever runs.
- Fix: expect `42501`.
- Consequence: `_authority` is defence in depth only. Review Focus 3 and the global constraint ("raises authority_violation (OC001) for any other caller") describe something that cannot happen.

**W12. The `freeze()` helper inserts a draft with no tenant set** (Task 4, Step 1; plan).
- Error: `InsufficientPrivilege: new row violates row-level security policy for table "drafts"`. `as_role(worker)` never sets `app.tenant_id`.
- Fix: `set_config('app.tenant_id', tenant, true)` before the INSERT.

**W13. Unpacking an async generator** (Task 4, Step 1; plan).
- `api, worker, mcp_exec = (await role_conn(r) for r in (...))` raises `TypeError: cannot unpack non-iterable async_generator object` in 4 tests.
- Fix: a list comprehension `[await role_conn(r) for r in ...]`.

**W15. The `translate` test helper cannot inject `diag`** (Task 5, Step 1; plan).
- `exc.__dict__["diag"] = diag` has no effect, because `psycopg.Error.diag` is a property and a property wins over an instance attribute.
- The detail is therefore lost: `Refused('REFUSED')`, and the test failed with `'REFUSED' == 'SLOT_OCCUPIED'`.
- Fix: a dynamic subclass with `diag` as a class attribute.

**W16. RETRIEVING→APPROVED is a refusal, not an illegal transition** (Task 5, Step 4 prose; plan).
- The prose says this transition raises `IllegalTransition`. `transition_run`'s post-grant guard runs first and raises `Refused('POST_GRANT_TARGET')` (`OC005`).
- Fix: expect `persistence.Refused`.

**W17. The worker test's tenant has no reviewer** (Task 6, Step 5 prose; plan).
- `new_run(app_conn, api=api)` creates a random tenant with no memberships, so `record_decision(reviewer=SAM)` raises `Refused: NOT_REVIEWER` in 3 tests.
- Fix: seeded tenant ALPHA.

**W19. A transaction wrapper hides the seeded conversation** (Task 7, Step 3 prose for mcp-read; plan).
- "Everything else unchanged" keeps `async with app_conn.transaction():` around `new_run`. The separate `api` connection cannot see the uncommitted conversation: `NotFound: not_found: conversation`.
- Fix: dropped the wrapper.

**W21. The token test imports helpers that do not exist** (Task 8, Step 1; plan).
- The code block imports `rsa_key`, `jwks_for` and `make_token` and sets `v._key`. Plan D's module has `keypair`, `mint`, `JWK1` and `ISSUER` instead.
- The plan says "adapt"; I rewrote the test on the real helpers. The block is unusable as written.

**W22. Plan D's fake store does need `reject`** (Task 8, Step 5; plan).
- The plan says Plan D's `FakeStore` "gains no-op abort/reject only if a Plan D test needs them (it does not)". Two Plan D tests failed with `AttributeError: 'FakeStore' object has no attribute 'reject'`.
- `test_malformed_bodies_are_422`'s `"[1]"` case now returns 200 `REJECTED`; the plan mentions only the hash-mismatch test.
- Fix: `reject` on the Plan D fake, and both tests updated.

**W23. `store.commits == []` cannot hold** (Task 8, Step 1; plan).
- In `test_abort_then_post_returns_the_tombstone_whatever_the_hash`, Plan D's fake records every `commit` call. The two POSTs after the abort call `commit`, which returns the tombstone, so the list has 2 entries.
- Fix: assert the row is `ABORTED`.

**W24. The isolation check expects the wrong error** (Task 8, Step 6; plan).
- `SELECT 1 FROM app.runs` as `incident` on `incident_test` raises `psycopg.errors.UndefinedTable: relation "app.runs" does not exist`, not `InsufficientPrivilege`: the destination database has no `app` schema.
- Fix: expect `UndefinedTable`.

**W25. R105 still expects 401 from the destination** (Task 8, Step 7; plan).
- After ruling 12, persona and worker tokens at incident-sim get `(403, 403)`. R105 still asserts `(401, 401)`, and the plan commits `test_r105` in Task 8 without saying to change it.
- Fix: expect `(403, 403)`.

**W27. The acceptance-matrix field names do not exist** (Task 9, Step 2; plan).
- The plan sets `"status"` and `"evidence"`. The real fields are `implementation_status` and `evidence_paths`.
- Fix: used the real fields.

### Non-blocking observations (not counted)

- **Expected-failure messages differ in wording.** Task 1 Step 9 gives `ModuleNotFoundError`; the actual error is `ImportError: cannot import name 'privileges' from 'ops_core'`. Task 5 Step 1 names `translate`; the actual missing attribute is `AuthorityViolation`. Task 4 Step 1's expected failure surfaces as `42883` through the `refused` helper.
- **Task 5's Steps 4 and 5 contradict each other.** Step 4 says to update every `new_run` caller (mcp-write, worker, mcp-read). Step 5 says not to touch those modules. I followed Step 5.
- **Task 7 Step 1 changes nothing.** `tests/plan_d/test_mcp_write.py` has no `GrantRefused` reference. "FAIL until Step 2" is false: 8 passed.
- **The Task 6/7 comment lands in the wrong places.** Task 1 Step 5 puts `# Task 6/7 switches this to its own role` on `skeleton.migrate` and the conftest `app_conn` too. Both stay superuser by design.
- **Many steps are prose without code.** Examples: Task 5 Steps 3–4, Task 6 Step 5, Task 7 Step 3, Task 8 Step 5 (partly), Task 9 Step 3. That is where W16, W17 and W19 came from.
- **The live suite has side effects.**
  - `tests/plan_b/live` rewrites `reports/bootstrap/bootstrap-admin.txt` and `keycloak-claims.txt`. I restored them each time; they are in no commit list.
  - `bootstrap_dev.py secrets` rewrites `.env`. The content was identical to `<repo>/.env`.
- **R098 hook absence is unit-level only.** The live run checks the absence of the hooks in dev only through the unit test (`make(Profile.DEV)` gets a 404).

## 3. Measurements

**PL/pgSQL creation on a fresh `ops_test`** via `migrate(Profile.TEST)` inside the e2e fixture:
- Revision 0002: the ownership `DO $own$` block and `app.current_time()` create.
- `tc_0001`: creates.
- Revision 0003: all 9 functions create after W8 (5 granted, 4 helpers).
- Revision 0004: all 12 functions create after W11, including `_grant_row`.
- `test_function_catalog_shape` passes with every name present. It checks owner `app_definer`, `search_path`, the `app.tenant_id=` attribute on granted functions only, no PUBLIC ACL entry, helpers granted to nobody, and no stray function.
- W14 is a call-time privilege error, not a creation error.

**R006 up/down/up** with `<scratchpad>/r006_probe.py`. The probe sets `OPS_PG_DB=ops_test` and calls `scripts.skeleton.downgrade/migrate`. At the Task 2 state:

```
start ['tc_0001_test_clock']
down 'testclock@base': OK -> ['0002_roles_grants_rls'] test_clock False run_directory True
down '0001_walking_skeleton': OK -> ['0001_walking_skeleton'] test_clock False run_directory False
MIGRATE: app at heads, incident at head (profile test)
migrate 'heads': OK -> ['tc_0001_test_clock'] test_clock True run_directory True
```

- Alembic accepts the plain revision id `0001_walking_skeleton` with the `testclock` branch present. The `app@0001_walking_skeleton` fallback was not needed.
- From Task 3 on, `test_r006_fresh_database_upgrades_downgrades_and_upgrades_again` passes unmodified: two heads, 0 policies after the downgrade, the same version set after re-upgrade. It exercises the 0004, 0003 and 0002 downgrades.

**R124 enumeration:** the catalog query matches the matrix exactly. `test_r124_every_grantee_holds_exactly_its_matrix_privileges` passed at Task 2 and in every later full run; there is no diff to paste. No PUBLIC table grant exists.

**Preset tenant and plain SET:**
- `test_resolve_identity_ignores_a_preset_tenant_and_restores_it` and `test_every_run_path_function_leaves_the_callers_tenant_unchanged` (`transition_run`, `append_event`, `revoke_handles` under a preset BETA) pass: `7 passed in 1.96s`.
- In the write path, the preset-BETA checks on `resolve_invocation`, `grant_execution` (including replay) and `mark_unknown` pass: `8 passed in 2.78s`.

**Live modules:**

| Module | Result | Point in the run |
|---|---|---|
| `test_roles_live` (R124, owners, R084, R128, R007/R008, R009, R106) | 7/7 | from Task 5 |
| `test_clock_live` (R126, dev clock guard) | 2/2 | from Task 2 |
| `test_migrations_and_persistence` | 6/6 | from Task 5 |
| `test_definers_run_path_live` | 7/7 | |
| `test_definers_write_path_live` | 8/8 | |
| `test_worker_live` | 4/4 | includes the new UNKNOWN test |
| `test_mcp_read_live` | 1/1 | |
| `test_mcp_write_live` | 3/3 | |
| `test_incident_sim_live` | 4/4 | |
| `test_tokens_live` | — | |
| `test_r105_walking_skeleton` | 1/1 | |
| `tests/e2e` as a whole | 44 passed in 43.82s | final |
| `tests/e2e` + `tests/plan_b/live` | 50 passed in 75.80s | Task 7 |

**R105 under `PROFILE=test`:**
- `1 passed in 27.70s`. The skeleton children inherited the fixture's environment: the run's grant was found in `ops_test` by the superuser on `ops_test`, and `incident_id=INC-000001` shows a fresh `incident_test`.
- The evidence file lists 9 events: `run.accepted, tool.started, tool.completed, explanation.ready, proposal.ready, approval.recorded, action.granted, action.dispatched, action.confirmed`. It records `state=SUCCEEDED state_version=7`, `replay=same_action_id`, and `keys=consistent`.

**Destination races.** These are read-only counts from `incident_test` after the session (`<scratchpad>/race_probe.py`):

```
create-vs-abort x20: COMMITTED=9 ABORTED=11; create-vs-create x20: incidents=20; schema owner=incident_owner
```

Both branches of the race occur. Each pair settled on one terminal state, and an incident row exists if and only if the key committed. In R096, `DELETE`, `UPDATE` and `TRUNCATE` by `incident` raise 42501, the CHECK refuses a tombstone that carries an incident id, and the table owner is `incident_owner`. In R010, `scripts.skeleton.keys()` returns 1 for the planted orphan.

**`check.py --profile test`:** `555 passed, 21 skipped in 107.45s`, CHECK GREEN. It includes `tests/plan_b/live`. All 21 skips are standing reasons: the owner seal, POSIX mode bits, and the Plan C schema-conformance placeholders.

## 4. Final state of the gates

All three gates ran on the final commit `85575c3`:
- `PYTHONUTF8=1 uv run python scripts/check.py`: **GREEN**, 502 passed, 74 skipped, ruff and mypy clean.
- `PYTHONUTF8=1 uv run python scripts/check.py --profile test`: **GREEN**, 555 passed, 21 skipped.
- `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`: **exit 0**. It checked 47 acyclic tasks and 131 covered requirements; 26 schemas, 34 accepted and 53 negative examples; and the remap, snapshot and source hashes.

Gate history:

| Point | `check.py` result | Note |
|---|---|---|
| Baseline | GREEN, 458 passed, 45 skipped | |
| After Task 5 | RED by construction | 48 mypy errors, all in service call sites (as allowed) |
| After Task 6 | RED by construction | 22 mypy errors in mcp-read, mcp-write and incident-sim |
| After Task 7 | GREEN | only because of W20 |

## 5. Where the plan's own claims are contradicted

1. **Review Focus 1** names a test `test_preset_tenant_is_ignored_and_restored` ("every granted function"). No such test exists in the plan. The preset checks are spread over individual tests, and `freeze_proposal`, `record_decision`, `lookup_action`, `mark_sent`, `record_outcome` and `create_run` get none. (`create_run` gets a preset only in the plain-SET test.)
2. **Review Focus 3 and the global constraint** ("api calling it → OC001"; every function "raises authority_violation (OC001) for any other caller") are contradicted by W9. Callers without EXECUTE get 42501, and `_authority` is unreachable for them.
3. **Self-review §1 and revision 0004's docstring** claim the AM-12 lock order (`proposals`/`decisions FOR SHARE`). It cannot run under the plan's own matrix (W14).
4. **Global constraint "One string per function … no ` :name` text in bodies"** is too narrow: `':1'` and `':timeout'` are binds too (W8, W11). The Task 1 bind-regex test checks rendered statements only, never function bodies.
5. **Task 1 Step 11** ("Plan D's settings test still passes") and **Task 2 Step 9** ("Every other live module still passes … the old persistence code still works as the superuser") are both false (W1, W5).
6. **Task 7 Step 4** ("GREEN except the incident-sim `Session.read` call") understates the problem: it is a runtime failure that blocks R105 (W20).
7. **Task 8 Step 5** ("its FakeStore gains no-op abort/reject only if a Plan D test needs them (it does not)") is false (W22).
8. **Self-review §2** ("No placeholders") holds literally, but several steps give only prose where a later step depends on exact code (§2, non-blocking observations), and three of those prose descriptions were wrong (W16, W17, W19).
9. **Self-review §4** says "replay and races (Tasks 6–8)" are pinned. They are, and they pass once W13 and W23 are fixed.

## Cleanup proof

The cleanup ran as the superuser from the worktree venv; no secret was printed.

- Dropped `ops_test` and `incident_test` (`DROP DATABASE IF EXISTS … WITH (FORCE)` from `postgres`).
- For each of `api, worker, sweeper, mcp_read, mcp_exec, operator, test_harness, migrator, app_definer, incident_owner`, the script checked ownership in `ops` and `incident`: owned relations, schemas and functions, plus `pg_shdepend` owner rows. **Every role owned nothing.** The script then ran `DROP OWNED BY` in `ops`, `incident` and `postgres`, followed by `DROP ROLE`.

Script output:

```
remaining roles of interest: ['incident', 'ops']
remaining databases of interest: ['incident', 'ops']
dev ops: test_clock=False alembic_version=['0001_walking_skeleton'] app schema owner=ops
dev incident: alembic_version=['0001_walking_skeleton'] incident schema owner=incident
```

- The dev databases are at revision 1, untouched, and carry no test clock.
- The seven new secret files remain in place; `postgres_` files: 9.
- No skeleton process is running: `skeleton.py status` shows all five down, `pids.json` is absent, and nothing listens on 8000, 8070, 8081, 8082, 8090, 18081 or 18090.
- `git status --short` is clean in `<worktree>` and empty in `<repo>` (only the git-ignored `.superpowers/`).

---

## Round 2 — static critic

# Plan E static critic, round 2

**Plan under review:** `docs/superpowers/plans/2026-10-08-first-slice-e-roles-rls-definers.md` at `7accee9` on branch
`plan-e`. The revision diff is `f04204d..7accee9`, with 381 lines added and 197 removed.

**Inputs read:**
- `AGENTS.md` and `docs/CODE_COMMENTS.md`.
- Both round-1 reports.
- The revised plan in full.
- SA AM-20.3 rows 452–472, plus SA:158, SA:528 and the late-evidence row SA:464.
- `core/src/ops_core/{outcomes,states,jobs,settings,tokens,persistence}.py`, `scripts/{skeleton,check}.py` and revision 1.
- `tests/e2e/conftest.py`, `tests/plan_d/{test_tokens,test_incident_sim}.py`, `data/seed-ids.json` and the acceptance matrix.
- The five services' callers, and `mcp-write/src/ops_mcp_write/destination.py`.

**Method.** Every claim below rests on a line of the plan or code, or on a measurement in §3.
- The plan's code blocks were extracted verbatim.
- The revisions were applied through `sqlalchemy.text()`, exactly as `op.execute` does, to a scratch database
  `critic_e` on the dev PostgreSQL 17.11. Schema `app` was renamed `critic_app` and every role `critic_<role>`; the
  GUC `app.tenant_id` was kept.
- The functions were called as scratch roles.
- The plan's unit tests ran against a scratch copy of `ops_core` patched with the plan's modules.
- ruff ran with the repo config, and `mypy --strict` ran over `ops_core`.
- Every `critic_*` object was dropped at the end (§3, M10). No repository file was edited. `skeleton.py migrate`/`up`
  and `docker compose down` were not run, and nothing was pushed.

**Item count.** The round-1 reports hold 40 static findings and 27 builder workarounds: 6 Blocking (B1–B6), 16
Important (I1–I16), 18 Minor (m1–m18, where m18 is an observation) and W1–W27. That is 67 items, not 70; all 67 are
tabled below. The builder's non-numbered observations and its §5 contradictions follow the table as an addendum.

**Result:**

| Group | Count | Items |
|---|---|---|
| Closed | 59 | |
| Partial | 5 | I2, I5, I15, m14, W4 |
| Not closed | 2 | B2 and W8: the fix for the bind defect itself introduces one |
| Not applicable | 1 | m18 |

**New findings:** 1 Blocking, 5 Important, 13 Minor.

---

## 1. Closure table (round-1 items)

"L" is a line of the revised plan; "M" is a measurement in §3.

| Item | Status | Evidence (revised plan line, measurement) |
|---|---|---|
| B1 `FOR SHARE` needs UPDATE | **Closed** | Every `FOR SHARE` is gone from 0004 (L2843–3336); ruling 23 (L64) and the 0004 docstring (L2853–2855) declare it. M3 §1: decide, grant, sent, outcome and unknown all succeed as their roles with **no** extra grant. |
| B2 `':1'` / `':timeout'` binds | **Not closed: new defect** | The bodies now use `format('%s:1', …)` (L2343) and `format('%s:timeout', …)` (L3301), and 0004 is bind-free (M0). But the comment added on L2341, `-- format(), not a ':1' literal: …`, is itself a bind. M0: `0003_run_path_functions bind ['1'] line: -- format(), not a ':1' literal`. M1: `rev0003: FAILED: StatementError … bind parameter '1'`. See **NB1**. |
| B3 42501 before OC001 | **Closed** | All nine assertions now expect `"42501"` (L1959, L1977, L2052, L2098, L2638, L2666, L2709, L2738, L2786). `_authority` is proved through the superuser (L1960, L1978, L2639). Review Focus 3 (L35), the global constraint (L17) and ruling 20 (L62) are reworded. |
| B4 `freeze()` without a tenant | **Closed** | L2587 sets the tenant first. M3 §1: freeze returns OK with `state_version 4`. |
| B5 async generator unpacked | **Closed** | L2697, L2720, L2777 and L2810 use list comprehensions. |
| B6 Task 2 vs the Plan D persistence code | **Closed** | Task 2 role tests seed themselves (`seed_run`, L1456–1479; M6 proves every NOT NULL column). The interim red is declared (L27, L1743). |
| I1 mypy on `grant_statements` | **Closed** | L621 has `isinstance(grant.upd, tuple)`. M11: `mypy --strict -p ops_core` → `Success: no issues found in 14 source files`. |
| I2 ISC004 | **Partial** | The global constraint (L26) and the Task 2 note (L1226) tell the executor to parenthesise. The code blocks still carry 31 unparenthesised elements (M11: 28 in 0002, 1 in tc_0001, 2 in incident 0002). `--fix` does not repair them, so an executor who copies the blocks gets RED until they hand-edit. |
| I3 Plan D settings test and missed caller | **Closed** | L288 renames `tests/plan_d/test_settings.py:51` and `tests/e2e/test_mcp_write_live.py:109`, adds the `OPS_PG_SUPERUSER` delenv, and adds both files to the commit (L668). |
| I4 `insert_job` unusable by `api` | **Closed** (declared) | L3911–3912 declare it a test/superuser helper and move T12 elsewhere. M3 §8: `insert_job as api: 42501`, as declared. The comment and note now contradict each other (NM8). |
| I5 SQL event rules vs `event_rules_ok` | **Partial** | (a) Late-evidence payload fixed (L3254–3259). M3 §4: a late SUCCEEDED and a late FAILED_NO_COMMIT each replay as `all accepted`. (b) The reason check is fixed (L2232). M3 §5: `{}` and `{'reason': 'policy'}` are refused by both. (c) Shape checks are still missing: SQL accepts three payloads that Python refuses (M3 §5), and the late branch has no test. See **NI4**. |
| I6 worker never resends once EXECUTING | **Closed** | L4384 checks `JOB_RULES[EXECUTE].run_states`, which is `{APPROVED, EXECUTING}` (`core/src/ops_core/jobs.py:89`). Ruling 6 is updated (L48). |
| I7 R105 401 → 403 | **Closed** | L5211 changes it in Task 8 and L4629 keeps 401 in Task 7. |
| I8 Plan D incident-sim FakeStore and `commits == []` | **Closed** | L5095 gives the Plan D `FakeStore` `abort`/`reject` and updates both Plan D tests. L4796 now asserts on the row. |
| I9 token test imports | **Closed** | L4667 imports `ISSUER, JWK1, PEM2, mint`, which all exist (`tests/plan_d/test_tokens.py:24,38-39,42`). M7: `PEM2 under kid k1 -> TokenRejected, cause InvalidSignatureError` (a signature failure, not a kid miss). |
| I10 `diag` injection | **Closed** | L3408–3414 use a subclass property. M11: `test_persistence_errors.py` passes. |
| I11 isolation probe error | **Closed** | L5131–5134 connect to `ops_test` as `incident`. M8: `OperationalError … FATAL: permission denied for database "critic_e"`, and `match=` succeeds. |
| I12 password in the error | **Closed** | L761–784 wrap the call in `EXCEPTION … RAISE … USING ERRCODE = SQLSTATE`, with a Python `finally`. M5: re-raised as `ReservedName 42939`, context `PL/pgSQL function inline_code_block line 12 at RAISE`, password literal anywhere in the error `False`, setting left behind `False`. |
| I13 `up` crashes before refusing | **Closed** | L918–927 call `export_environment` first and catch `(RuntimeError, settings.SettingsError)`. |
| I14 R006 at Task 2 | **Closed** | L1408 now asserts membership only. |
| I15 undeclared departures | **Partial** | (a) Sweeper `available_at` removed (L485, L530; the test asserts it at L408). (b) test_harness gets nothing on the main line (M1: dev shape `role absent`, current_time ACL without it; tc adds it). (d) Declared at L47 and L62. (c) Dropped from `DEFINER_FUNCTIONS` (L573), **but** `_authority('resolve_identity', ARRAY['api', 'sweeper'])` (L2419), ruling 4 (L46), the role map (L96) and the Task 3 interfaces (L1771) still name the sweeper. See NM1. |
| I16 `new_run` on the superuser | **Closed** | L3983–4005 call `create_run` on `api` inside `api.transaction()`. |
| m1 R009 gaps | **Closed** | L1010–1013 and L1027–1028 add the keys. M3b: `proposals_tenant_draft_fkey` and `execution_grant_tenant_proposal_fkey` each refuse a cross-tenant child (23503). No live test covers them (NM5). |
| m2 jobs CHECK | **Closed** | L1004. M3 §7: a NULL tenant with a run, and a tenant with a NULL run, are both refused by `jobs_tenant_iff_run_check`; a sweeper-shaped job is inserted. |
| m3 `now()` in the job SQL | **Closed** | L3933–3953 and L3965 use `app.current_time()`; ruling 24 (L65). |
| m4 global grant count | **Closed** | L2820 scopes the count to the two runs. |
| m5 foreign-payload freeze | **Closed** | L2631–2637 hash the foreign bytes. |
| m6 ruff noise | **Closed** | M11: no RUF100. The I001 and F401 findings that remain are auto-fixed by `--fix`. |
| m7 13+7 secrets | **Closed** | L663. |
| m8 machine path | **Closed** | L324 reads `OPS_SECRETS_DIR` from `.env`. |
| m9 docstrings and TODO form | **Closed** | Docstrings added (L3511–3529, L3711, L3751, L3772, L3803); L288 uses `TODO(T09)`. |
| m10 one unit for outcome plus read-back | **Closed** | L4586–4593 use two units. `standing is outcome.status` is sound (M7: `True ToolOutcome`). |
| m11 Profile import | **Closed** | L5261. |
| m12 reserved types | **Closed** | L2399–2400. M3 §6: tool.*, explanation.ready, clarification.received, notification.failed and feedback.recorded are accepted; run.answered, proposal.ready, approval.recorded and clarification.requested are refused. |
| m13 race outside a unit | **Closed** | L5160–5163 (`in_unit`). The coroutine is awaited inside the transaction. |
| m14 mypy residue vs "GREEN after every task" | **Partial** | L27 declares the interim red, but two task gates contradict it: NI2 (Task 3) and NI3 (Task 5). |
| m15 `%` mechanism | **Closed** | L2476. |
| m16 sweeper `del` without `sel` | **Closed** | Flagged in the errata (L5300). |
| m17 unnecessary fallback | **Closed** | L1743. |
| m18 cluster observation | n/a | Still true: the dev cluster holds `api … test_harness, worker`, `ops_test` and `incident_test` (M10 listing). This review left them untouched. |
| W1 missed callers | **Closed** | L288. |
| W2 mypy | **Closed** | Same as I1. |
| W3 renamed line over 120 columns | **Closed** | L288: "put the trailing comment on its own line above". |
| W4 ISC004 | **Partial** | Same as I2. |
| W5 old persistence code vs 0002 | **Closed** | Declared red (L27, L1743). |
| W6 R006 at Task 2 | **Closed** | Same as I14. |
| W7 unused noqa | **Closed** | No `noqa: E402` remains (L700, L5245). |
| W8 bind in `create_run` | **Not closed** | Same as B2 / NB1. |
| W9 OC001 unreachable | **Closed** | Same as B3. |
| W10 test files unformatted | **Closed** | L2482 and L3347 run `ruff format` on them. |
| W11 bind in `mark_unknown` | **Closed** | M0: 0004 is bind-free. M3 §3: the recover dedup key equals `f"{action}:timeout"`. |
| W12 `freeze()` without a tenant | **Closed** | Same as B4. |
| W13 async generator | **Closed** | Same as B5. |
| W14 `FOR SHARE` | **Closed** | Same as B1. |
| W15 `diag` | **Closed** | Same as I10. |
| W16 RETRIEVING→APPROVED | **Closed** | L4007 expects `Refused` with `POST_GRANT_TARGET`. |
| W17 tenant without a reviewer | **Closed** | L4467 and L4623 use ALPHA with SAM. Seeds: SAM is alpha's reviewer and ALEX alpha's requester (`data/seed-ids.json`). M3 §1: `record_decision ALPHA/SAM approve: OK … state_version 5`. |
| W18 requeue without the tenant | **Closed** | L4401. M3 §8: requeue under the tenant gives rowcount 1; the same UPDATE without the tenant gives rowcount 0. |
| W19 transaction hides the conversation | **Closed** | L4006 and L4620. |
| W20 incident-sim `Session.read` | **Closed** | L4015 moves it to Task 5. |
| W21 token helpers | **Closed** | Same as I9. |
| W22 FakeStore `reject` | **Closed** | Same as I8. |
| W23 `commits == []` | **Closed** | L4796. |
| W24 isolation error | **Closed** | Same as I11. |
| W25 R105 403 | **Closed** | Same as I7. |
| W26 check.py import | **Closed** | L5261. M11: the TYPE_CHECKING pattern passes ruff with no F821/F811, and `test_check_cli.py` gives 2 passed. |
| W27 matrix fields | **Closed** | L5292. The real fields are `implementation_status`, `evidence_status`, `evidence_paths` and `note` (listing in M10), and the enum values exist. |

**Addendum: the builder's non-numbered observations and §5 contradictions**
- Expected-failure texts: Task 5 is fixed (L3466). Task 1 Step 9 (L418) still says `ModuleNotFoundError`, and Task 4
  Step 1 (L2837) still says `UndefinedFunction` (NM10).
- Task 5 Steps 4/5 contradiction: fixed (L4006).
- Task 7 Step 1: reworded (L4496).
- Comment placement: fixed (L288).
- Live-suite side effects: addressed (L4633).
- §5.1 (Review Focus 1 names a test that does not exist): **not fixed** (NM2).
- §5.3 (lock-order claims): fixed (L2853).
- §5.4 and §5.5: fixed.
- Self-review "three declared departures" (L5328) vs the docstring's four (L432): stale (NM3).

---

## 2. New findings

### Blocking

**NB1. Revision 0003 still cannot be applied: the comment explaining the bind fix is itself a bind.**
- **Where:** plan L2341, inside `CREATE_RUN`: `-- format(), not a ':1' literal: a quote followed by a colon and a word is a SQLAlchemy bind (round-1 B2).`
- **Cause:** `text()` scans comments too. `':1'` is a quote, a colon and a word.
- **Evidence (M0, M1):**
  - `0003_run_path_functions bind ['1'] line: -- format(), not a ':1' literal …`
  - `rev0003: FAILED: StatementError: (sqlalchemy.exc.InvalidRequestError) A value is required for bind parameter '1'`
  - With only that comment reworded: `rev0003: upgrade OK (23 statements)` and `rev0004: upgrade OK (32 statements)`.
- **The plan's own guard catches it.** The new unit test (L1831–1837) reports
  `FAILED …test_no_op_execute_string_carries_a_sqlalchemy_bind[0003_run_path_functions]` (M11).
- **Consequence:** Task 3 Step 4 is red as written, and so is every later task until the comment is edited.
- **Correction:** `-- format('%s:1', …), never a quote-colon-digit literal: SQLAlchemy reads a colon after a quote as a bind (round-1 B2).`
  Here `%s:1` follows a word character, so it is not a bind. Keep the unit test; it is what makes this visible.

### Important

**NI1. An UNKNOWN classification makes `create_incident` raise instead of returning the UNKNOWN envelope. Ruling 6's
path is unreachable in production.**
- **Where:** L4581–4589.
- **What happens:**
  - `destination.post_incident` turns every transport failure into `None` (`destination.py:63-64`).
  - `destination.classify` turns `None`, any non-200 (the T10 faults' 503) or a malformed document into
    `ToolOutcome.UNKNOWN` without raising (`destination.py:95-102, 126-127`).
  - The plan then passes that outcome to `persistence.record_outcome`, which raises
    `ValueError("UNKNOWN is recorded by the worker…")` (L3896–3897). That is outside the `try`, so it escapes the tool.
  - The worker sees `McpCallFailed` and re-queues. It never receives the UNKNOWN envelope, so `mark_unknown` (L4406–4409)
    runs only in the scripted test (L4470).
- **Effect:** with the destination down or slow, the execute job loops every `EXECUTE_RETRY_SECONDS` with no bound
  (T13), and no `recover` job or `action.uncertain` is ever recorded.
- **Contradictions:** ruling 6 (L48: "mcp-write records nothing and returns the UNKNOWN envelope") and the comment
  "after SENT nothing may escape" (L4582).
- **Not new:** this was present at `f04204d`, and neither round-1 report caught it.
- **Correction:** after `classify`, add:
  ```python
  if outcome.status is ToolOutcome.UNKNOWN:
      return outcome  # the worker records it through mark_unknown (SA:467)
  ```
  This also uses the import that ruff now flags as F401.
- **Test to add:** a live test in `test_mcp_write_live.py` with a destination stub answering 503 must yield the
  `UNKNOWN` envelope, attempt `SENT` and run `EXECUTING`.

**NI2. Task 3's gate cannot be GREEN.**
- **Where:** Task 3 Step 1 creates `tests/plan_e/test_transitions_table.py` with
  `REVISIONS = ("0002…", "0003…", "0004…", "tc_0001…")` (L1812).
- **The plan itself says** the 0004 case fails with `FileNotFoundError` until Task 4 (L1840).
- **Yet** Task 3 Step 5 says `check.py → GREEN` (L2487). `check.py` runs `pytest -q` over `testpaths`, which includes
  `tests/plan_e`.
- **The interim-red list (L27) does not name it.**
- **Correction:** parametrise over what exists (no skip, so the "no xfail or skip" rule holds):
  ```python
  REVISIONS = tuple(n for n in (...) if (ROOT / "migrations/app/versions" / f"{n}.py").exists())
  ```
  Drop the `-k` instructions at L1840/L1842/L2482.

**NI3. Task 5's mypy allowance names too few call sites, so an executor following the text must call the gate red.**
- **The allowance:** L4017 (and L27) let mypy fail "**only** at the call sites of the removed names `transition`,
  `check_invocation`, `resolve_handle` and `Session.read`".
- **Other names Task 5 changes also break the services' types:**
  - `create_run`: the old `run_id=` keyword and the `int` return, at `api/src/ops_api/store.py:204`.
  - `append_event`: the old `tenant_id=` and `conversation_id=` keywords, at `api/src/ops_api/store.py:217,281,299`,
    `worker/src/ops_worker/handlers.py:52,66,182,195` and `mcp-write/src/ops_mcp_write/execution.py:126,160,187,202,215,235`.
  - `claim_job`: the missing `tenant_ids`, at `worker/src/ops_worker/main.py:36`.
- **Correction:** say "only in `api/`, `worker/`, `mcp-read/`, `mcp-write/`, at call sites of `persistence` names Task
  5 removed or re-signed (`transition`, `check_invocation`, `resolve_handle`, `Session.read`, `create_run`,
  `append_event`, `claim_job`)", in both places.

**NI4. The SQL rules and their Python twin still diverge, and the new replay never reaches the code that changed.**
- **Where:** L2208–2213, L2228–2229, L3254–3259, L3343, L2768–2771.
- **Divergence (M3 §5).** SQL accepts and Python refuses:
  - `action.confirmed {'status': 'SUCCEEDED', 'receipt': {'x': 1}}`;
  - `explanation.ready` (model_summary) `{'message': 'm', 'evidence_refs': [1, '']}`. This one is reachable by the
    `worker` role through `append_event`;
  - `action.late_evidence {'outcome': 'MAYBE'}`.
- **Coverage.** The replay at L2768–2771 runs only on the success path's rows. No plan test writes a late-evidence row:
  that branch needs an unresolved attempt on a terminal run, which no Plan E function produces (M3 §4 had to force the
  state). So L3343's "cannot drift" is not proved.
- **Correction:**
  - In `_append_event`, refuse a `model_summary` payload whose `evidence_refs` is not an array of non-empty strings.
  - Require `jsonb_typeof(receipt) = 'object'` with `receipt_id`, `incident_id` and `committed_at` present for
    `action.confirmed`.
  - Require `outcome` ∈ (`SUCCEEDED`, `FAILED_NO_COMMIT`) and the matching proof object for `action.late_evidence`.
  - Add a live test that forces a run terminal with the superuser (as M3 §4 does), calls `record_outcome` as
    `mcp_exec`, and replays the row through `event_rules_ok`.
  - Reword L3343 to what is tested.

**NI5. Revision 0002 renders its grants from the live matrix, so the first later task that adds a table row breaks
every fresh upgrade (R006).**
- **Where:** L971–972 (`TABLES = tuple(t for t in privileges.GRANTS if t != "test_clock")`), L1145
  (`rls_statements(privileges.RLS_TABLES)`) and L430–431 ("the owners of later tables … add their rows").
- **Measured (M9):** adding one row (`outbox`) and replaying 0002 on a fresh database gives
  `rev0002: FAILED: ProgrammingError: (psycopg.errors.UndefinedTable) relation "critic_app.outbox" does not exist`.
  The next owner (T12/T14) would either break `migrate(Profile.TEST)` on every fresh session database, or have to edit
  an applied revision.
- **Correction:** in 0002, freeze the table and RLS lists as literals, e.g. `TABLES = ("tenants", …, "transitions")`
  and `RLS = (...)`. State in the privileges docstring that each later revision renders
  `grant_statements`/`rls_statements` for exactly the tables it creates or changes. Add a unit assertion that 0002's
  literal lists are a subset of `GRANTS`.

### Minor

- **NM1. resolve_identity callers.** `DEFINER_FUNCTIONS` grants `api` only (L573). `_authority` still lists `'sweeper'`
  (L2419), as do ruling 4 (L46, "and sweeper"), the role map (L96) and the Task 3 interfaces (L1771).
  - The catalog test passes either way, because it reads the ACL, not `_authority`.
  - Correction: `ARRAY['api']` and the three texts.
- **NM2. Review Focus 1 names a test that does not exist** (L33, `test_preset_tenant_is_ignored_and_restored`, "every
  granted function"). The self-review (L5331) repeats it.
  - Preset coverage is still missing for `freeze_proposal`, `record_decision`, `mark_sent`, `lookup_action` and
    `record_outcome`. M3 §1 shows they restore BETA, so the gap is in the tests only.
  - Correction: name the real tests. Wrap the `mark_sent`/`lookup_action`/`record_outcome` block (L2742–2759) and one
    `freeze`/`approve` in `as_role(…, preset=BETA)`, with the restore assertion.
- **NM3. Errata and count drift.**
  - Task 9 (L5300) says "the 22 rulings"; there are 24, numbered out of order (23, 24, 22 at L64–66).
  - The self-review (L5328) says "three declared departures"; the docstring (L432) lists four.
  - Undeclared departures:
    - `resolve_invocation` returns `job_type` (plus `job_id` and `conversation_id`) instead of SA:459's
      `allowed_tools` (ruling 21);
    - `app.transitions` is a table outside AM-20.2 (ruling 10);
    - a CONFLICT on a terminal run emits `action.conflict`, not SA:464's "late evidence" (L3251–3254).
  - Correction: add all three to the L5300 list and fix the counts.
- **NM4. mcp-write live-test prose (L4623) repeats the round-1 W12 trap.** "The worker's drafts INSERT under
  `set_tenant(worker, ALPHA)`" says nothing about a transaction. `set_tenant` is transaction-local, so on an autocommit
  connection the INSERT meets RLS.
  - Correction: spell out `async with worker.transaction(): await persistence.set_tenant(worker, ALPHA); <INSERT>; await persistence.freeze_proposal(...)`.
- **NM5. R009 never exercises the two new keys** (L1623–1644). Add the two inserts from M3b (alpha proposal → beta
  draft; alpha grant → beta proposal) expecting `ForeignKeyViolation`.
- **NM6. The `test_transitions_table.py` block lacks `import pytest`** (L1783–1787). The fix is only in prose (L1840).
  - As written, collection fails: `NameError: name 'pytest' is not defined` (M11); ruff reports F821 ×3.
  - Put the import in the block.
- **NM7. Interfaces are out of date.** Task 1 (L129) still lists `function_grant_statements(name)` and omits `MAIN_ROLES`,
  `MAIN_GRANTEES` and `TEST_ONLY_ROLES`.
- **NM8. `insert_job` comment vs note.** The comment (L3911–3912) says the API's `resume_input` will **not** use it.
  The note (L3971) says it reads `run_directory` "so the API's `resume_input` insert (T12) … need no tenant lookup".
  Delete the T12 clause from the note.
- **NM9. Ruling 3 overstates** (L45): "a dev or demo cluster never has the role".
  - The live suite creates `test_harness` in the same cluster, which holds it today (M10).
  - The role keeps LOGIN cluster-wide, and keeps CONNECT on `ops` until a dev `migrate` narrows it. `ops` has
    `datacl = NULL` today, which means PUBLIC CONNECT.
  - It is harmless (no grants in `ops`) but false as worded.
  - Reword: "a dev or demo database grants it nothing".
- **NM10. Two expected-failure texts are still wrong.**
  - L418: the actual error is `ImportError: cannot import name 'privileges' from 'ops_core'`.
  - L2837: the first failure is `AssertionError '42883' == 'OC007'`.
- **NM11. Two sources of truth for the test-only roles.** `scripts/skeleton.py`'s own `TEST_ONLY_ROLES` (L746) duplicates
  `ops_core.privileges.TEST_ONLY_ROLES` (L450). Derive one from the other:
  `frozenset(Role(r) for r in privileges.TEST_ONLY_ROLES)`.
- **NM12. The debt list (L73–85) omits two items.**
  - Ruling 23's "memberships race recorded as T11's".
  - The AM-20.3 lock-column departures (`run_lease FOR SHARE` and the advisory locks are listed; the four dropped
    `FOR SHARE` locks are not).
  - Add one line each, since SA:698 requires the list to be complete before coding.
- **NM13. `check.py` resolves the profile before the import guard.** L5284 does not say `main(argv)` must call
  `members_importable()` before `check_profile`. The lazy `from ops_core.settings import Profile` would otherwise raise
  a bare `ImportError` on an unsynced clone, which is the case the guard exists for. Say "after
  `members_importable()`".

---

## 3. Scratch measurements

All scripts are in the session scratchpad `…/scratchpad/critic2/` and ran with `PYTHONUTF8=1 .venv/Scripts/python.exe
<script>`.
- `common.py` reads the superuser password from the file named by `.env`'s `OPS_SECRETS_DIR` and never prints it.
- The `critic_*` login password was a per-run scratch value, never printed, and deleted at the end.
- `extract.py` and `extract_all.py` copy every ```python block of the revised plan verbatim.
- `corecopy/` is `core/src/ops_core` patched with the plan's settings block, `privileges.py` (plus Task 4's
  `_grant_row` line, L3338), `persistence.py` and `testing/faults.py`.

**M0: bind scan.** The plan's own unit-test logic, run as a script: `alembic.op.execute` patched, then each revision's
`upgrade()` and `downgrade()` collected and passed through `text(...)._bindparams`.
```
0002_roles_grants_rls 288 statements
tc_0001_test_clock 12 statements
0003_run_path_functions bind ['1'] line: -- format(), not a ':1' literal: a quote followed by a colon and a word is a SQLAlchemy bind (round-1 B2).
0003_run_path_functions 32 statements
0004_write_path_functions 44 statements
```
The patch reaches the revisions: they call `op.execute` through the module attribute, so `monkeypatch.setattr(alembic.op,
"execute", …)` works.

**M1: build, verbatim and then with only the NB1 comment reworded.** `m1_run.py verbatim|fixed|after_up`. The scratch
database has revision 1's DDL with the seeds, plus revision-1 rows in all 13 data tables. Dev shape means
`critic_test_harness` does not exist.
```
$ m1_run.py verbatim
rev0002: upgrade OK (233 statements)
rev0003: FAILED: StatementError: (sqlalchemy.exc.InvalidRequestError) A value is required for bind parameter '1'
$ m1_run.py fixed
dev shape: critic_test_harness exists: 0
rev0002: upgrade OK (233 statements) / rev0003: upgrade OK (23 statements) / rev0004: upgrade OK (32 statements)
-- dev shape (app@head): tables 19 | policies 15 | functions 22 | schema owner critic_migrator
    drafts_tenant_id_key = UNIQUE (tenant_id, id)
    execution_grant_tenant_proposal_fkey = FOREIGN KEY (tenant_id, proposal_id) REFERENCES critic_app.proposals(tenant_id, proposal_id)
    jobs_tenant_iff_run_check = CHECK (((run_id IS NULL) = (tenant_id IS NULL)))
    proposals_tenant_draft_fkey = FOREIGN KEY (tenant_id, draft_id) REFERENCES critic_app.drafts(tenant_id, id)
   test_harness grants: usage role absent | current_time acl: {…app_definer, api, worker, sweeper, mcp_read, mcp_exec, operator}
revtc: upgrade OK (9 statements)
-- test shape (heads): tables 20 | policies 15 | functions 22 | schema owner critic_migrator
   test_harness grants: usage 1 | current_time acl: {… , critic_test_harness=X/critic_app_definer}
```

**M4: downgrade and re-upgrade (tc → 0004 → 0003 → 0002, then up again), populated.** Run with `m1_run.py downup`,
then `after_up`.
```
revtc: downgrade OK (3 statements) / rev0004: downgrade OK (12) / rev0003: downgrade OK (9) / rev0002: downgrade OK (55)
-- after downgrade to revision 1: tables 15 | policies 0 | functions 0 | schema owner ops
    execution_grant_proposal_id_fkey = FOREIGN KEY (proposal_id) REFERENCES critic_app.proposals(proposal_id)
    proposals_draft_id_fkey = FOREIGN KEY (draft_id) REFERENCES critic_app.drafts(id)
   test_harness grants: usage 0 | current_time acl: absent
   column grants left: 0 | table grants left: 0 | roles with schema USAGE: 0
   tables with tenant_id: conversations,events,memberships,messages,proposals,runs,tenants
   slot index: CREATE UNIQUE INDEX runs_one_active_per_conversation ON critic_app.runs USING btree (conversati ...
   rows kept: runs 1 | proposals 1 | decisions 1 | jobs 1
rev0002: upgrade OK (233) / revtc: upgrade OK (9) / rev0003: upgrade OK (23) / rev0004: upgrade OK (32)
-- re-upgraded (heads): tables 20 | policies 15 | functions 22 | schema owner critic_migrator  (four new constraints present again)
```
The new constraints come off in the right order: `proposals_tenant_draft_fkey` is dropped before
`drafts_tenant_id_key`, and `execution_grant_tenant_proposal_fkey` before `proposals_tenant_proposal_key`. The
testclock downgrade revokes the harness, and nothing is left behind.

(The first `downup` run ended in a bug in the critic's own report query, an IndexError on the dropped function; the
downgrades had already committed. `after_up` then reported and re-upgraded.)

**M2: catalogs after re-upgrade (test shape).** Run with `m2_catalog.py`.
```
distinct tenant_isolation qual equals POLICY_QUAL: True ; with_check == qual everywhere: True
sweeper_all rows: [('jobs', ['critic_sweeper'], 'true', 'true'), ('memberships', ['critic_sweeper'], 'true', 'true')]
stray functions vs DEFINER|HELPER: []
R124 enumeration: actual == expected: True ; PUBLIC table rows: 0
owners: critic_migrator (tables and schema) ; forced RLS on 13 of 20 tables
the plan's function catalog test, renamed: every function matches DEFINER_FUNCTIONS/HELPER_FUNCTIONS: True | count 22
```

**M3: the functions as their roles, no extra grant.** Run with `m3_flow.py`; UUIDs are masked.
```
== 1. create_run OK v1 ; investigate dedup key is format('%s:1'): {'ok': True}
freeze (tenant set): OK state_version 4 ; record_decision ALPHA/SAM approve: OK APPROVED state_version 5
grant_execution (preset BETA): OK attempt_state INTENT ; caller's preset after the call = BETA (restored)
grant_execution replay: OK {'same': True} ; mark_sent (preset BETA): 'sent', restored ; record_outcome SUCCEEDED (preset BETA): restored
lookup_action (preset BETA): RESOLVED, restored ; run: SUCCEEDED state_version 7 slot_held False
run1: events [run.accepted, proposal.ready, approval.recorded, action.granted, action.dispatched, action.confirmed/destination]
run1: event_rules_ok replay -> all accepted
== 2. FAILED_NO_COMMIT: run FAILED reason rejected, action.failed/destination, replay all accepted
      CONFLICT: run ESCALATED reason conflict, action.conflict/destination, replay all accepted
== 3. mark_unknown (preset BETA): OUTCOME_UNKNOWN, restored ; recover dedup key is format('%s:timeout'): {'ok': True}
      record_outcome SUCCEEDED after UNKNOWN: OK ; events … action.uncertain, action.confirmed ; replay all accepted
== 4. late evidence (run forced terminal by the superuser; no Plan E function reaches this branch)
record_outcome SUCCEEDED on a FAILED run: last event action.late_evidence destination ['action_id','outcome','receipt'] ; replay all accepted
record_outcome FAILED_NO_COMMIT on an ABANDONED_UNVERIFIED run: action.late_evidence ['action_id','outcome','reason','tombstone'] ; replay all accepted
record_outcome CONFLICT on a SUCCEEDED run: action.conflict ['action_id'] ; replay all accepted
== 5. action.failed {}: SQL refused OC006 | python refused
      action.failed {'reason': 'policy'}: SQL refused OC006 | python refused
      action.failed {'reason': 'rejected', 'receipt': {}}: SQL refused OC006 | python refused
      action.failed {'reason': 'rejected'}: SQL accepted | python accepted
      action.confirmed {'status': 'SUCCEEDED', 'receipt': {'x': 1}}: SQL accepted | python refused
      explanation.ready {'message': 'm', 'evidence_refs': [1, '']}: SQL accepted | python refused
      action.late_evidence {'outcome': 'MAYBE'}: SQL accepted | python refused
== 6. append_event: tool.started, tool.completed, explanation.ready (worker), clarification.received (api),
      notification.failed (sweeper), feedback.recorded (api): accepted ;
      run.answered, proposal.ready (worker), approval.recorded (api), clarification.requested (worker): OC006 'reserved type'
== 7. job with run and NULL tenant: CheckViolation 23514 jobs_tenant_iff_run_check
      job with tenant and NULL run: CheckViolation 23514 jobs_tenant_iff_run_check ; sweeper job (no run, no tenant): inserted
== 8. claim_job (app.current_time()) as worker tenant=3ea79c95: ('investigate', '3ea79c95')
      requeue_job under the tenant: rowcount 1 ; the same UPDATE without set_tenant: rowcount 0
      insert_job as api: 42501 permission denied for table jobs   (declared: helper for tests and the superuser)
```

**M3b: each new composite key on its own.** Run with `m3b.py` as the superuser, rolled back.
```
alpha proposal on alpha run naming beta's draft: ForeignKeyViolation 23503 proposals_tenant_draft_fkey
alpha grant on alpha run naming beta's proposal: ForeignKeyViolation 23503 execution_grant_tenant_proposal_fkey
```

**M5: role bootstrap.** Run with `m5_roles.py`. It calls the plan's `ensure_login_role`/`ensure_nologin_role`, taken
from the L745 block, with a dummy literal `critic-dummy-not-a-secret`.
```
create: (True,) / re-key: ok / nologin+bypassrls: (False, True)
failing role 'pg_critic_probe': ReservedName sqlstate=42939 primary='role bootstrap failed for pg_critic_probe'
   context: PL/pgSQL function inline_code_block line 12 at RAISE
   password literal anywhere in the error: False
   setting left in the session: False
probe roles dropped: True
```
`USING ERRCODE = SQLSTATE` works inside the DO block's handler: the original 42939 is preserved.

A second probe used a 70-character name. PostgreSQL silently truncated it to 63 characters and created the role. That
scratch role (`critic_xxx…`) was dropped immediately, and the cleanup confirmed 0 left.

`login_roles` (from the L745 block):
```
dev ['api', 'worker', 'sweeper', 'mcp_read', 'mcp_exec', 'operator']
test ['api', 'worker', 'sweeper', 'mcp_read', 'mcp_exec', 'operator', 'test_harness']
demo ['api', 'worker', 'sweeper', 'mcp_read', 'mcp_exec', 'operator']
```
So `narrow_connect` grants CONNECT to `test_harness` only in the test profile. A dev `migrate` on a cluster that
already has the role neither re-keys it nor grants it anything, and none of 0002, 0003 or 0004 names it (M1 dev shape
applied with the role absent).

**M6: `seed_run` and the purge order.** Run with `m6_seed.py`; it uses the plan's five statements verbatim.
```
seed_run statements found: 5
seed_run: OK -> {'state': 'QUEUED', 'slot_held': True, 'next_event_seq': 0, 'budget_used': 0}
purge_run with run_directory last in PURGE_ORDER: OK; left: {'n': 0}
```
`PURGE_ORDER` runs before the `runs` DELETE (`tests/e2e/conftest.py:86-89`), so "last entry" is still before `runs`,
which is correct.

**M7: tokens and outcome identity.**
```
good: ops-mcp-write
PEM2 under kid k1 -> TokenRejected | cause: InvalidSignatureError
aud ops-api -> TokenRejected | cause: InvalidAudienceError
azp ops-worker -> TokenRejected | cause: None
standing is outcome.status: True ToolOutcome     (ActionOutcome.model_validate_json(... "CONFLICT" ...).status is ToolOutcome("CONFLICT"))
```

**M8: CONNECT narrowing.** Run with `m8_connect.py`, async as in the live test.
```
acl: {=T/ops,ops=CTc/ops,critic_api=c/ops}
critic_worker: OperationalError; matches 'permission denied for database': True; … FATAL:  permission denied for database "critic_e" / DETAIL:  User does not have CONNECT privilege.
critic_api   : connected
```

**M9: 0002 against a later matrix row (NI5).** Run with `m9_future.py`.
```
rev0002: FAILED: ProgrammingError: (psycopg.errors.UndefinedTable) relation "critic_app.outbox" does not exist
```

**M11: static checks and unit tests.**
```
$ (corecopy) python -m mypy --strict --python-version 3.13 --no-incremental -p ops_core
Success: no issues found in 14 source files
$ (ws: plan_e tests + the plan's four revisions; scripts/bootstrap_dev.py with the 7 names of L294-302) pytest -q tests/plan_e
ERROR collecting tests/plan_e/test_transitions_table.py … NameError: name 'pytest' is not defined      (block as written)
(with `import pytest` added) FAILED …test_no_op_execute_string_carries_a_sqlalchemy_bind[0003_run_path_functions]
1 failed, 36 passed       (test_privileges, test_settings_roles, test_persistence_errors, test_faults, transitions all pass)
$ ruff check --statistics (repo pyproject; 25 module blocks)
31 ISC004 [ ] / 7 I001 [*] / 3 F821 [ ] (missing `import pytest`) / 3 F401 [*] (execution.py ToolOutcome; t10 test pytest, Any)
$ check.py with the L5261 TYPE_CHECKING import + the L5264 functions; tests/test_check_cli.py
ruff: no F821/F811 ; pytest: 2 passed
```

**M10: cleanup and the read-only listing.**
```
dropped roles: ['critic_api', 'critic_app_definer', 'critic_mcp_exec', 'critic_mcp_read', 'critic_migrator',
                'critic_operator', 'critic_sweeper', 'critic_test_harness', 'critic_worker']
left critic roles: 0 | left critic dbs: 0
databases: ['incident', 'incident_test', 'ops', 'ops_test', 'postgres', 'template0', 'template1']
non-critic roles unchanged: ['api', 'app_definer', 'incident', 'incident_owner', 'mcp_exec', 'mcp_read', 'migrator',
                            'operator', 'ops', 'sweeper', 'test_harness', 'worker']
datacl (read-only): ops = NULL; ops_test = {=T/ops, …, test_harness=c/ops}; incident_test = {…, incident=c/ops}
scratch password file removed; `git status --short` in the repository: clean
```
The acceptance-matrix listing (read-only) shows that the rows live under `requirements`, with the fields
`implementation_status`, `evidence_status`, `evidence_paths` and `note`.

---

## 4. Verdict

The revision is a real improvement. Most of round 1's findings are closed, and the hard parts now hold under
measurement:
- With every `FOR SHARE` removed, the write path runs as its roles with no extra grant.
- The new composite keys and the `jobs` CHECK refuse exactly what they should.
- Revision 0002 comes off and goes back on cleanly on a populated database, in both the dev shape (no `test_harness`)
  and the test shape (the testclock grants and their revocation).
- R124 and the function catalog match the matrix exactly.
- Every event the functions write, including the rewritten late-evidence payloads, passes `event_rules_ok`.
- The role bootstrap no longer leaks a password, and the CONNECT probe fails with the text the test matches.

The plan still does not execute as written:
- **Revision 0003 fails to apply** because the comment explaining the bind fix is itself a bind (NB1). The plan's own
  new unit test catches it, but Task 3 is red until that one line changes.
- Five Important defects remain:
  - mcp-write turns every classified UNKNOWN into an exception, so ruling 6's UNKNOWN path never runs in production
    (NI1).
  - Task 3's gate contradicts its own test (NI2), and Task 5's mypy allowance is too narrow (NI3).
  - The SQL/Python twin still diverges on reachable payloads, and the late-evidence branch has no test (NI4).
  - Revision 0002 renders from the live matrix, so the next task that adds a table row breaks every fresh upgrade
    (NI5).

Fix NB1 and NI1–NI5, which are all small and concrete edits, and the plan is ready to execute. The Minor items can be
fixed during execution.

---

## Round 2 — builder dry run

# Plan E dry run, builder round 2

Plan under test: `docs/superpowers/plans/2026-10-08-first-slice-e-roles-rls-definers.md` as of commit 7accee9 (the
round-1 revision). The run used a throwaway worktree (`<worktree>`) on a detached HEAD at 7accee9 with its own `.venv`
(`uv sync --locked --all-packages`). It executed Tasks 1–9 in order, one commit per task plus the debt-list commit
(10 commits, `70fc4e4..4099ef0`, no attribution trailer, nothing pushed). Every command ran through Git Bash and
`uv run`. The dev stack was PostgreSQL 17 at 127.0.0.1:15432 and Keycloak at :18080. Live tests ran only against
`ops_test` and `incident_test` under `PROFILE=test`; `skeleton.py migrate`/`up` never ran outside the e2e fixture.
Baseline before Task 1: `check.py` GREEN, `458 passed, 45 skipped`.

**Result:** the plan reaches its end state with every gate green after **9 workarounds** (W1'–W9'), against 27 in
round 1. Only **two touch code the plan gives verbatim**: W2' (parentheses around multi-line SQL strings, which the
plan itself asks for but its code blocks do not have) and W5' (a comment in revision 0003 that is itself a
SQLAlchemy bind). One finding has no workaround (W6': `check.py` is RED at the end of Task 3 for a reason outside the
declared interim-red list). The rest are wrong commands, a missing prose line, or wrong claims about repository side
effects. Of the 27 round-1 workarounds, 25 are gone; W4 and W8 remain in a reduced or new form.

## 1. Per-task table

| Task | Steps | Outcome | Workarounds |
|---|---|---|---|
| 1 | 1–12 | Done. `tests/plan_e`: 14 passed. Plan B static + settings: `26 passed, 1 skipped`. `check.py` GREEN `472 passed, 45 skipped`. | W1' |
| 2 | 1–10 | 0002 and `tc_0001` apply to a fresh `ops_test`. R006, R124, R084, R128, R007/R008, R009, R106, R126, the dev clock guard: all pass. The 4 Plan D tests in `test_migrations_and_persistence.py` fail (declared). Full live: `12 failed, 22 passed in 67.14s`, all 12 in the declared list. `check.py` GREEN `474 passed, 55 skipped`. | W2', W3' |
| 3 | 1–5 | 0003 applies after W5'. Run path + roles live: `14 passed in 2.69s`. Persistence `-k "idempotent or r006"`: `2 passed`. `check.py` **RED** `1 failed, 478 passed, 62 skipped` (W6'). | W4', W5', W6' (no fix) |
| 4 | 1–4 | 0004 applies verbatim. Write path + run path + roles: `22 passed in 4.43s`; bind unit test `5 passed` (all four revisions). `check.py` GREEN `479 passed, 70 skipped`. Full live: `12 failed, 37 passed in 69.03s`, all declared. | — |
| 5 | 1–6 | Persistence written verbatim. Units `40 passed`. Four live modules `28 passed in 5.65s`. `check.py` RED by declaration: 47 mypy errors (see §6, item 3), `489 passed, 70 skipped`. Full live: `7 failed, 41 passed, 1 error in 146.91s`, all declared. | — |
| 6 | 1–7 | api and worker on their roles. Units `56 passed`; worker + write path live `12 passed in 4.64s` (incl. the new UNKNOWN test and the EXECUTING re-dispatch proof). mypy residue 21 errors, all in mcp-read/mcp-write (as the plan says). Full live: `4 failed, 45 passed, 1 error in 148.67s`, all declared. | W7' |
| 7 | 1–5 | mcp-read/mcp-write on their roles. `tests/e2e tests/plan_b/live`: `50 passed in 76.04s`. `check.py` GREEN `494 passed, 71 skipped`, no residue. | W8' |
| 8 | 1–7 | T10 complete; the three new unit modules pass verbatim. Units `86 passed`; `tests/e2e`: `44 passed in 43.49s`. `check.py` GREEN `505 passed, 74 skipped`. | W9' |
| 9 | 1–5 | `check.py` dev GREEN `507 passed, 74 skipped`; `--profile test` GREEN `560 passed, 21 skipped`; `verify_handoff.py` exit 0. | (W8' again) |

## 2. Workarounds in detail

"Plan" means the plan's text was wrong; "environment" means the plan was right and the machine got in the way.
**All nine are the plan's.** None was caused by the environment.

**W1'. The secret-count command reads the wrong `.env` line** (Task 1, Step 6; plan).
- Command: `ls "$(grep OPS_SECRETS_DIR .env | cut -d= -f2)" | grep -c postgres_`.
- `.env`'s first line is the comment `# Generated by scripts/bootstrap_dev.py. … secrets are files under OPS_SECRETS_DIR.`,
  which also matches, so the argument is two lines: `ls: cannot access '# Generated by …'$'\n''C:/…/secrets': No such
  file or directory`, count `0`.
- Fix: `grep '^OPS_SECRETS_DIR='` → `9`.

**W2'. The plan's own SQL tuples violate ISC004** (Task 2, Steps 4–5; Task 8, Step 3; plan).
- The plan now says "write each such element inside its own parentheses", but the code blocks of `0002_roles_grants_rls.py`
  and `tc_0001_test_clock.py` (29 elements) and `migrations/incident/…/0002_destination_hardening.py` (2) are
  unparenthesised. `ruff check` → `29 ISC004 … No fixes available (29 hidden fixes can be enabled with the
  --unsafe-fixes option)`.
- Fix: `uv run ruff check --select ISC004 --fix --unsafe-fixes <files>` (adds the parentheses only). The code blocks
  should simply carry the parentheses.

**W3'. `-x` stops the Task 2 run at a declared-red test** (Task 2, Step 9; plan).
- `pytest tests/e2e/test_migrations_and_persistence.py tests/e2e/test_roles_live.py tests/e2e/test_clock_live.py -q -x`
  → `1 failed, 1 passed in 1.50s` (`test_transition_follows_the_table…`: `NotNullViolation … "run_state_history"`), so
  the roles and clock modules never run and "Expected: PASS" cannot be observed.
- Fix: the same command without `-x` → `4 failed, 11 passed in 3.06s`; the 4 failures are exactly the declared Plan D
  tests, and the 11 passes are the migrate test, R006, the seven role tests and the two clock tests.

**W4'. `-k "transition or …"` selects every test in the file** (Task 3, Step 1; plan).
- `-k "transition or 0002 or tc_0001"`: "transition" matches the module name `test_transitions_table`, so the 0003 and
  0004 cases run too → `2 failed, 3 passed` (`FileNotFoundError: … 0004_write_path_functions.py`, and 0003 does not
  exist yet either).
- Fix: `-k "one_insert or 0002 or tc_0001"` → `3 passed, 2 deselected`.

**W5'. A comment in revision 0003 is itself a bind** (Task 3, Step 3; plan, verbatim code).
- `CREATE_RUN` carries `-- format(), not a ':1' literal: a quote followed by a colon and a word is a SQLAlchemy bind`.
  The quoted `':1'` in the comment is a bind; the new unit test caught it before any database did:
  `assert {'1': BindParameter('1', None, type_=NullType())} == {}` on the `create_run` string. Applying 0003 would fail
  exactly as round-1 W8 did.
- Fix: reword the comment (`-- format(), not a quoted colon-one literal: a quote, a colon and a word make a SQLAlchemy
  bind`). After that, 0003 applied and every bind check passed. The guard the plan added works; its own comment
  tripped it.

**W6'. `check.py` is RED at the end of Task 3 (no workaround)** (Task 3, Step 5; plan).
- `tests/plan_e/test_transitions_table.py` is committed in Task 3 with `REVISIONS` naming `0004_write_path_functions`,
  which only arrives in Task 4. `check.py` → `FAILED …test_no_op_execute_string_carries_a_sqlalchemy_bind[0004_write_path_functions]`,
  `1 failed, 478 passed, 62 skipped`, `CHECK: RED`.
- The plan says "`check.py` → GREEN" for Task 3, and the interim-red list does not name this test. I committed as
  written; it clears at Task 4. A fix would be to add `0004` to `REVISIONS` in Task 4, or to skip a missing file.

**W7'. The drafting-failure test needs `run.accepted`** (Task 6, Step 5; plan, prose gap).
- The prose tells `_investigate_then_execute` to gain `run.accepted` first, but says nothing about
  `test_drafting_failure_fails_the_run`, whose event list also starts with `run.accepted` now that `create_run` emits
  it.
- Fix: assert `["run.accepted", "tool.started", "tool.completed", "run.failed"]`.

**W8'. The Plan B live tests append to `reports/bootstrap/*.txt`** (Task 7, Step 4, and every later live run; plan).
- The plan says they "rewrite `reports/bootstrap/*.txt` with identical content — `git status` must stay clean of them".
  They do not: `bootstrap-admin.txt` gains 1 line and `keycloak-claims.txt` 9 lines per run (`M` in `git status`).
- Fix: `git checkout -- reports/bootstrap` after each live run (as the run brief said).

**W9'. The R105 evidence is regenerated but never committed after Task 7** (Tasks 8 and 9; plan).
- Task 8 changes R105 to `(403, 403)` and every live run rewrites `reports/skeleton/r105-walking-skeleton.txt`, but
  neither Task 8's nor Task 9's `git add` names it. After Task 9's commit the tree is left with
  `M reports/skeleton/r105-walking-skeleton.txt`; the committed evidence is Task 7's run (which still asserted 401).
- Fix: none needed to finish; I restored the file with `git checkout`. Task 8 (or Task 9 Step 5) should add it.

### Non-blocking observations (not counted)

- **Expected-failure wording still differs.** Task 1 Step 9 says `ModuleNotFoundError`; the actual error is
  `ImportError: cannot import name 'privileges' from 'ops_core'`. Task 4 Step 1 says `UndefinedFunction:
  app.freeze_proposal`; the first failure is `assert '42883' == 'OC007'` (through `refused`).
- **Prose-only steps remain** and I wrote their code: Task 5 Steps 3–4, Task 6 Step 5, Task 7 Step 3, Task 8 Step 5
  (`app.py` and the Plan D test updates) and Task 9 Steps 2–3. Except for W7', the prose was correct this time:
  `Refused('POST_GRANT_TARGET')`, `IllegalTransition` for RETRIEVING→QUEUED, the seeded ALPHA tenant and no outer
  transaction all held.
- **Placement prose is loose.** "After the session exists" (mcp-write) and "after the store is installed and before
  the keys load" (api) leave the clock assertion outside any `try`, so a refusal there leaks the connection.
- **Task 9 Files says "(fourteen rows)"**; Step 2 changes 13 rows plus R122 and R082 (15).
- **`<first>..<last>` is circular** for the Task 9 commit that records it; I used the last code commit (`d53854c`).
- **A stale docstring outside the plan's file list:** `ops_core/contracts.py` still says `supersedes_run_id` "is
  injected into the hashed payload by `freeze_proposal`", which contradicts ruling 5 (verified, not injected).
- **Task 8 Step 5's "move them there and let the subclass inherit"** leaves unused imports in
  `test_incident_sim_t10.py`; the gate's `ruff check --fix` removes them (6 fixes).
- **`bootstrap_dev.py secrets` rewrites `.env`**: byte-identical (`cmp` clean); `0 created, 20 kept`.

## 3. Round-1 workarounds: gone or remaining

| Round 1 | Status in round 2 |
|---|---|
| W1 rename misses two callers | Gone: Step 5 lists all eight sites. |
| W2 mypy on `grant.upd` | Gone: `isinstance(grant.upd, tuple)`. |
| W3 over-long renamed line | Gone: the comment moves above; the format list includes the file. |
| W4 ISC004 | **Remains, reduced** (W2'): the rule is stated, but the code blocks are still unparenthesised. |
| W5 old persistence vs 0002 | Gone as a workaround: now declared interim red, and every failure stayed inside the declared list. |
| W6 R006 two version rows | Gone: asserts `tc_0001_test_clock in versions`; passes from Task 2. |
| W7 unused `noqa` | Gone. |
| W8 `':1'` bind in a body | **Remains in a new form** (W5'): the body uses `format('%s:1', …)`, but the comment quotes `':1'`. The new unit test now catches it. |
| W9 OC001 unreachable | Gone: wrong roles expect 42501, the superuser expects OC001; all pass. |
| W10 unformatted test files | Gone: Tasks 3–4 format first. |
| W11 `':timeout'` bind | Gone: `format('%s:timeout', …)`, no stray quote. |
| W12 `freeze()` without tenant | Gone. |
| W13 async-generator unpacking | Gone (list comprehension). |
| W14 `FOR SHARE` without UPDATE | Gone: no row lock on the four tables (ruling 23); 0004 has no `FOR SHARE`. |
| W15 `diag` injection | Gone: dynamic subclass with a `diag` property. |
| W16 RETRIEVING→APPROVED | Gone: the prose says `Refused('POST_GRANT_TARGET')`. |
| W17 tenant without reviewer | Gone: seeded ALPHA. |
| W18 requeue without tenant | Gone: `set_tenant` before `requeue_job`. |
| W19 transaction wrapper | Gone: the prose says to drop it. |
| W20 incident-sim `Session.read` | Gone: Task 5 Step 5 switches to `ping()`; no incident-sim mypy residue. |
| W21 token-test helpers | Gone: uses `ISSUER, JWK1, PEM2, mint`. |
| W22 Plan D fake needs `reject` | Gone: Task 8 Step 5 says so. |
| W23 `store.commits == []` | Gone: asserts no COMMITTED row instead. |
| W24 isolation error type | Gone: the connection is refused (`permission denied for database`). |
| W25 R105 401 vs 403 | Gone: Task 7 keeps 401 with a note; Task 8 switches to 403. |
| W26 `Profile` import in check.py | Gone: `TYPE_CHECKING` plus lazy imports, given verbatim. |
| W27 matrix field names | Gone: `implementation_status`, `evidence_status`, `evidence_paths`, `note`. |

## 4. Measurements

**Revisions on a fresh `ops_test`** (via the fixture's `migrate(Profile.TEST)`, every session):
- 0002 and `tc_0001` applied verbatim at Task 2, after W2' (parentheses only).
- 0003 applied after W5'.
- 0004 applied verbatim.
- From Task 4 on, `test_function_catalog_shape` passes with every name present: owner `app_definer`, `search_path`,
  the tenant attribute on granted functions only, no PUBLIC ACL entry, helpers (including `_grant_row`) granted to
  nobody, and no stray function.

**R006 up/down/up:**
- `test_r006_fresh_database_upgrades_downgrades_and_upgrades_again` passed at Task 2 (0002 + `tc_0001` only) and in
  every later run. The later runs exercise the 0004 → 0003 → 0002 downgrades: `testclock@base`, then
  `0001_walking_skeleton`, then `test_clock`/`run_directory`/`transitions` are gone, 0 policies remain, and
  re-migrating gives the same version set.
- The plain `0001_walking_skeleton` target worked with the branch applied, as the plan says.

**R124 enumeration:** `test_r124_every_grantee_holds_exactly_its_matrix_privileges` passed at Task 2 and in every
later run. There was no diff to report.

**OC001 vs 42501** (Tasks 3–4 live tests, all passing):
- The wrong login role gets `42501`: `create_run` by worker, `transition_run` by api, `resolve_identity` by worker,
  `revoke_handles` by api, `freeze_proposal` by api, `record_decision` by worker, `resolve_invocation` by api,
  `grant_execution` by worker, `mark_unknown` by mcp_exec.
- The superuser, which passes the ACL, gets `OC001` from `_authority`: `create_run`, `transition_run`,
  `freeze_proposal`.

**Task 3 bind-parameter unit test** (`test_no_op_execute_string_carries_a_sqlalchemy_bind`, loads every revision with
`op.execute` patched):
- It caught W5' at Task 3 (`{'1': BindParameter('1', …)}` on the `create_run` string).
- After the fix: `4 passed, 1 deselected` (0002, 0003, `tc_0001` + the generator test).
- From Task 4: `5 passed` (all four revisions).

**Live modules, where the plan says they must pass:**

| Module | Result | First green at |
|---|---|---|
| `test_roles_live` | 7/7 | Task 2 |
| `test_clock_live` | 2/2 | Task 2 |
| `test_migrations_and_persistence` | 2/6 at Task 2 (declared), 6/6 | Task 5 |
| `test_definers_run_path_live` | 7/7 | Task 3 |
| `test_definers_write_path_live` | 8/8 | Task 4 |
| `test_worker_live` | 4/4 (incl. UNKNOWN and EXECUTING re-dispatch) | Task 6 |
| `test_mcp_read_live` | 1/1 | Task 7 |
| `test_mcp_write_live` | 3/3 | Task 7 |
| `test_r105_walking_skeleton` | 1/1 | Task 7 |
| `test_incident_sim_live` | 4/4 (passed throughout on the old schema; the T10 version from Task 8) | Task 8 |
| `tests/e2e` + `tests/plan_b/live` | `50 passed in 76.04s` | Task 7 |
| `tests/e2e` | `44 passed in 43.49s` | Task 8 |

**R105 under `PROFILE=test`:**
- It passed in Tasks 7, 8 and 9 (inside `check.py --profile test`). The skeleton children inherited the fixture's
  `ops_test`/`incident_test` and `PROFILE=test`.
- The evidence file lists the 9 expected events (`run.accepted … action.confirmed`), `state=SUCCEEDED
  state_version=7`, `replay=same_action_id`, `keys=consistent`.
- At Task 8 the destination answered the persona and worker tokens `(403, 403)`.

**Destination races** (read-only counts from `incident_test` after the Task 8 session):

```
create-vs-abort x20: COMMITTED=8 ABORTED=12; create-vs-create x20: incidents=20; schema owner=incident_owner
```

Both branches of the race occur, each pair settles on one terminal state, and an incident row exists iff the key
committed. R096: DELETE, UPDATE and TRUNCATE by `incident` → 42501; the CHECK refuses a REJECTED key with an
incident id. R010: `scripts.skeleton.keys()` → 1 for the planted orphan.

**`check.py` and `check.py --profile test`:**
- Dev, final: `507 passed, 74 skipped in 30.63s`, GREEN.
- Test profile, final: `560 passed, 21 skipped in 104.80s`, GREEN. That includes the live suite and
  `tests/plan_b/live`. The skips are all standing reasons: the holdout seal, POSIX mode bits, and contract
  placeholders for T15/T17/T47.

**`verify_handoff.py`:** exit 0 at Task 9 Step 2 and Step 4. It checked 47 acyclic tasks and 131 covered
requirements; 26 schemas, 34 accepted and 53 negative examples; and the remap, snapshot and source hashes.

## 5. Final gate counts

On the final commit `4099ef0`:
- `PYTHONUTF8=1 uv run python scripts/check.py`: **GREEN**, `507 passed, 74 skipped`. ruff, format and mypy are clean.
- `PYTHONUTF8=1 uv run python scripts/check.py --profile test`: **GREEN**, `560 passed, 21 skipped`.
- `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`: **exit 0**.

Gate history:

| Point | `check.py` | Note |
|---|---|---|
| Baseline | GREEN 458/45 | |
| Task 1 | GREEN 472/45 | |
| Task 2 | GREEN 474/55 | |
| Task 3 | **RED** 1 failed, 478/62 | W6', not declared |
| Task 4 | GREEN 479/70 | |
| Task 5 | RED by declaration | 47 mypy errors in service call sites |
| Task 6 | RED by declaration | 21 mypy errors, all mcp-read/mcp-write |
| Task 7 | GREEN 494/71 | |
| Task 8 | GREEN 505/74 | |
| Task 9 | GREEN 507/74 | test profile 560/21 |

## 6. Contradictions with the plan's own claims

1. **Task 3 Step 5 "check.py → GREEN"** is false (W6'), and Global Constraints' "anything else must be green" is
   broken by a test the plan itself adds.
2. **Task 2 Step 9 "Expected: PASS"** cannot be observed with the command given (W3').
3. **The declared mypy residue at Task 5 is too narrow.** Global Constraints and Task 5 Step 5 allow mypy failures
   "only at the call sites of the removed names `transition`, `check_invocation`, `resolve_handle` and
   `Session.read`". Of the 47 errors, 18 are at removed names (`transition` 11, `resolve_handle` 2, `Session.read` 5).
   The other 29 are signature changes: `append_event` loses `tenant_id`/`conversation_id` (26), `create_run` loses
   `run_id` and returns a tuple (2), and `claim_job` needs `tenant_ids` (1). All 47 are in service files, so the
   spirit holds, but the letter does not.
4. **Task 7 Step 4 "rewrite `reports/bootstrap/*.txt` with identical content — `git status` must stay clean"** is
   false (W8').
5. **Task 9 Step 4 "`reports/skeleton/r105-walking-skeleton.txt` was regenerated in Task 7"** omits that Tasks 8–9
   regenerate it again and that no later commit takes it (W9').
6. **Global constraint "One string per function … `':1'` and `':timeout'` are binds too"** is right, and revision
   0003 still carries one, in a comment (W5'). The new unit test is what made this a one-line fix rather than a
   failed migration.
7. **Review Focus 1** still names `test_preset_tenant_is_ignored_and_restored` ("every granted function"), and no such
   test exists. Preset-BETA checks cover `resolve_identity`, `create_run`, `transition_run`, `append_event`,
   `revoke_handles`, `resolve_invocation`, `grant_execution` (incl. replay) and `mark_unknown`. They do not cover
   `freeze_proposal`, `record_decision`, `lookup_action`, `mark_sent` or `record_outcome`. This is unchanged from
   round 1.
8. **Self-review §1 "the three declared departures"** disagrees with `ops_core.privileges`' docstring, which lists
   four (rulings 6, 10, 17, 23).
9. **Self-review §2 "No placeholders"** holds literally. Several steps remain prose-only, but only one of those
   descriptions was incomplete this round (W7').

## Cleanup proof

The cleanup ran as the superuser from the worktree venv (`<scratchpad>/cleanup.py`); no secret was printed.
- Dropped `ops_test` and `incident_test` (`DROP DATABASE IF EXISTS … WITH (FORCE)` from `postgres`).
- For each of `api, worker, sweeper, mcp_read, mcp_exec, operator, test_harness, migrator, app_definer, incident_owner`,
  the script checked ownership in `ops` and `incident` from the catalogs: `pg_class`, `pg_namespace`, `pg_proc`,
  `pg_type`, and `pg_shdepend` owner rows. **Every role owned nothing.** The script then ran `DROP OWNED BY` in `ops`,
  `incident` and `postgres`, followed by `DROP ROLE`.

```
roles present before cleanup: ['api', 'app_definer', 'incident_owner', 'mcp_exec', 'mcp_read', 'migrator', 'operator', 'sweeper', 'test_harness', 'worker']
dropped role api … worker (each: owned nothing in ops/incident)
remaining roles of interest: ['incident', 'ops']
remaining databases of interest: ['incident', 'ops']
dev ops: test_clock=False alembic_version=['0001_walking_skeleton'] app schema owner=ops
dev incident: alembic_version=['0001_walking_skeleton'] incident schema owner=incident
postgres_ secret files: 9
```

- No skeleton process is running: `skeleton.py status` shows all five down, `pids.json` is absent, and nothing listens
  on 8000, 8070, 8081, 8082, 8090, 18081 or 18090.
- `git status --short` is empty in `<worktree>` (`reports/bootstrap` and `reports/skeleton` restored) and empty in
  `<repo>`.

---

## Round 3 — closure check and delta execution

# Plan E closure review, round 3

**Plan under review:** `docs/superpowers/plans/2026-10-08-first-slice-e-roles-rls-definers.md` at `9edabd6`
(branch `plan-e`). The round-2 fix diff is `7accee9..9edabd6`: 179 lines added and 51 removed, all in the plan.

**Inputs read:**
- `AGENTS.md` and `docs/CODE_COMMENTS.md`.
- The plan in full.
- `static-r2.md`, with NB1, NI1–NI5, NM1–NM13 and its seven partial or open round-1 items.
- `builder-r2.md`, with W1'–W9'.
- The round-2 diff.

**How the run was done (part B):**
- Workspace: a throwaway worktree (`<worktree>`) on a detached HEAD at `9edabd6`, with its own `.venv` from
  `uv sync --locked --all-packages`.
- Scope: Tasks 1–9 in order. Plan code blocks were copied verbatim by a block extractor that reads the plan file. The
  plan's own commands were used for ruff, format, ISC004, the gates and the live suite.
- Commits: one per task plus the debt-list commit, 10 in all (`ba1ce36..7e37516`). None carries an attribution
  trailer (grep count 0), and nothing was pushed.
- Live runs: only against `ops_test` and `incident_test` under `PROFILE=test`. `skeleton.py migrate` and `up` never
  ran outside the e2e fixture.
- Baseline before Task 1: `check.py` GREEN, `458 passed, 45 skipped`.

**Result:**
- The plan ran end to end with **zero workarounds**. Round 1 needed 27 and round 2 needed 9. Every gate was green at
  the end of every task, or red only inside the window the plan declares.
- Every one of the 27 round-2 items is closed or not applicable.
- I found **4 new findings, all Minor.** None blocks execution.

---

## 1. Closure table

"L" is a line of the plan at `9edabd6`. "M" is a measurement in §3.

### Round-2 static findings

| Item | Status | Evidence | New issue? |
|---|---|---|---|
| NB1 bind in the 0003 comment | **Closed** | L2432–2433: `format('%s:1', ...), never a quote-colon-digit literal`. `%s:1` follows a word character, so it is not a bind. M2: the bind test's `[0003_run_path_functions]` case passed, and 0003 applied to a fresh `ops_test` in every live session. | No |
| NI1 classified UNKNOWN reached `record_outcome` | **Closed** | L4707–4710 return the outcome before `record_outcome`. The three-case test prose is at L4752. M6: all three cases (an exception, `None`, a 503 reply) give UNKNOWN, attempt `SENT` and run `EXECUTING`. | No |
| NI2 Task 3 gate vs the missing 0004 | **Closed** | L1886–1892 parametrise over the revisions present on disk. M2: 2 cases at Task 2, 3 at Task 3, 4 at Task 4. Task 3 `check.py` GREEN `479/62`. | No |
| NI3 Task 5 mypy allowance too narrow | **Closed** | L28 and L4139 name `create_run`, `append_event` and `claim_job` too. M7: 47 errors at Task 5, all inside the window. | No |
| NI4 SQL vs Python event rules | **Closed** for the three cases cited | L2293–2295 add the `evidence_refs` element check; L2314 the receipt keys; L2317–2322 the late-evidence rule; L2902–2927 the new forced-terminal test; L2103 the new refusal case. M4: all three of static-r2's divergent payloads are now refused by both. | **Yes, N2:** field *types* and tombstone keys still diverge |
| NI5 0002 renders from the live matrix | **Partial** | L977–1012 freeze the table and RLS lists; L1879–1883 add the unit assertion. M8: the grant *cells*, `POLICY_ROLES` and 0003/0004's caller lists are still read live, so an applied revision still changes when a later task edits a cell. | **Yes, N1** |
| NM1 `resolve_identity` callers | Closed | L2511 `ARRAY['api']`, L47, L98, L1835 | No |
| NM2 Review Focus 1 test name | Closed | L34 names five real tests, and all five passed. Coverage gap: `freeze_proposal` and `record_decision` still have no preset-BETA restore test. L34 no longer claims every function, so this is no longer a contradiction. | No |
| NM3 counts and errata | Closed | L5427: "24 rulings" plus the three added errata. L5456: "four declared departures". Rulings are still listed out of numeric order (23, 24, 22 at L65–67); this is cosmetic. | No |
| NM4 worker transaction for the drafts INSERT | Closed | L4749. It works as written (M6). | No |
| NM5 R009 new keys | Closed | L1683–1706. `test_r009_…` passed. | No |
| NM6 `import pytest` | Closed | L1852 | No |
| NM7 Task 1 interfaces | Closed | L131 | No |
| NM8 `insert_job` note | Closed | L4093 | No |
| NM9 ruling 3 wording | Closed | L46 | No |
| NM10 expected-failure texts | Closed | L420 and L2959. Both matched exactly: `ImportError: cannot import name 'privileges' from 'ops_core'` and `assert '42883' == 'OC007'`. | No |
| NM11 one source for test-only roles | Closed | L749 | No |
| NM12 debt-list lock line | Closed | L86, committed in `ba1ce36` | No |
| NM13 import guard before the profile | Closed | L5411 | No |

### Round-2 builder workarounds

| Item | Status | Evidence |
|---|---|---|
| W1' `.env` grep | Closed | L326 `grep '^OPS_SECRETS_DIR='` returned `9`. |
| W2' ISC004 | Closed (by command) | L27, L1266 and L5057 name `ruff check --select ISC004 --fix --unsafe-fixes`. Measured: `Found 29 errors (29 fixed, 0 remaining)` for the app revisions and `2 fixed` for the incident revision. Only parentheses were added. |
| W3' `-x` stops at a declared red test | Closed | L1806: `9 passed` (roles and clock) and `2 passed, 4 deselected` (`-k "idempotent or r006"`). |
| W4' `-k` selected everything | Closed | The `-k` filter is gone (L1922, L2574): 4 cases passed at Task 3 Step 1 and 5 after Step 3. |
| W5' bind comment | Closed | Same evidence as NB1. |
| W6' Task 3 `check.py` red | Closed | GREEN `479 passed, 62 skipped`. |
| W7' drafting-failure events | Closed | L4590. The test passed with `run.accepted` first. |
| W8' `reports/bootstrap` appended | Closed | L23, L4759, L5342 and L5447. Every live run with `tests/plan_b/live` modified both files, and `git checkout -- reports/bootstrap` restored them. |
| W9' R105 evidence not committed | Closed | L23, L5343 and L5448. The evidence was committed in Task 7 (`dc15adb`, 401 era), Task 8 (`5b39cc0`) and Task 9 (`7e37516`, from the `--profile test` run). See N3. |

### Round-1 items that static-r2 marked partial or open

| Item | Status | Evidence |
|---|---|---|
| I2 / W4 ISC004 | Closed | Same as W2'. The code blocks are still unparenthesised, but the named one-line command repairs them. |
| I5 SQL/Python twin | Closed, with residue N2 | Same evidence as NI4. |
| I15 undeclared departures | Closed | The (c) residue is gone (NM1). |
| m14 interim red vs "GREEN after every task" | Closed | M7: Task 3 GREEN; Task 5 has 47 mypy errors and Task 6 has 21, all inside the L28 window. |
| B2 / W8 binds | Closed | Same evidence as NB1. |

**Counts:**
- Round 2: 27 items (NB1, NI1–NI5, NM1–NM13, W1'–W9'). 26 are closed and 1 is partial (NI5).
- Round 1: the seven partial or open items are all closed.

---

## 2. New findings (no workarounds were needed)

**N1 (Minor; the plan is at fault). An applied revision still re-renders from the live matrix.**
- **What NI5 fixed and what it left.** 0002's `TABLES` and `RLS` are now literals. But `grant_statements` still reads
  `GRANTS[table]` cells, and `rls_statements` reads `POLICY_ROLES`. 0003 and 0004 render their GRANT lines from
  `DEFINER_FUNCTIONS[name][1]`, and tc_0001 renders from `GRANTS["test_clock"]`.
- **Effect.** A later task that adds a column grant on an existing table changes 0002's output. That task might be T12
  adding an UPDATE column on `runs`, or T11 adding the sweeper to `resolve_identity`. M8 shows the change:
  `GRANT UPDATE (cancel_requested, cancel_requested_at, idempotency_key_t12) ON app.runs TO api` and
  `GRANT EXECUTE ON FUNCTION app.resolve_identity(text, uuid) TO api, sweeper`.
- **Failure mode (inferred, not run).** On a fresh database the first statement names a column that does not exist yet
  at 0002, so `migrate(Profile.TEST)` would fail in the same way static-r2's M9 measured.
- **Minimal fix:**
  - Either: give 0002 a frozen copy of the cells it grants (a literal `GRANTS_0002` dict), and have later revisions
    render only their own deltas.
  - Or: state in ruling 19 / the privileges docstring that a later task changes grants only by a new revision that
    re-runs `grant_statements` for that table, and never by editing a cell 0002 already rendered. Then add a unit test
    that pins 0002's rendered statement list to a committed fixture.

**N2 (Minor; the plan is at fault). The SQL twin checks the shape of the evidence, not its field types.**
- M4 on `ops_test` (superuser, rolled back) found four payloads that SQL accepts and `event_rules_ok` refuses:

  | Payload | SQL | Python |
  |---|---|---|
  | `action.confirmed` with `receipt_id: "not-a-uuid"` | accepted | refused |
  | `action.late_evidence` `FAILED_NO_COMMIT` with `tombstone: {"state": "ABORTED"}` (fields missing) | accepted | refused |
  | the same kind of shallow `{"receipt": {}}` on late `SUCCEEDED` (same branch) | accepted | refused |

- **Reachability.** Only `record_outcome` writes these payloads, and only a compromised `mcp_exec` could pass a bad
  document; mcp-write builds the document from a strict pydantic `ActionOutcome`.
- **Wording.** L3465 calls the replay "the drift check the SQL mirror has", which is accurate; nothing claims field
  parity.
- **Minimal fix.** In `_append_event`, require the five tombstone keys (`action_id`, `state`, `payload_sha256`,
  `reason`, `decided_at`) and the three receipt keys for late evidence. Optionally add a UUID pattern on
  `receipt_id`. Or record the residue as an accepted difference in ruling 5.

**N3 (Minor; the plan is at fault). The committed R105 evidence cannot show the 403s.**
- The evidence line is `refusals=api:worker,destination:persona+worker,mcp-write:persona+mcp-read`. The text is the
  same in the 401 era (Task 7) and the 403 era (Tasks 8–9). The test asserts `(403, 403)`, but the file does not record
  it.
- **Minimal fix (Task 7 prose):** append `destination_status=403,403` (401,401 in Task 7) to `lines`.

**N4 (Minor; the plan is at fault, Task 8 Step 5's code block L5165–5184). A rejection-path POST onto a committed key
returns 200 with a CONFLICT body.**
- **Cause.** The three rejection branches return `JSONResponse(status_code=200, content=keys.document(row, …)[1])`. When
  `reject()` finds an existing key, that key's document is returned with status 200 even when it is a CONFLICT.
- **Measured (M9, with the Plan D FakeStore):**

  | Request | Status | Body |
  |---|---|---|
  | Commit | 200 | `COMMITTED` |
  | Same key, other hash, valid bytes | 409 | `{"state": "CONFLICT", …}` |
  | Same key, presented hash ≠ bytes | **200** | `{"state": "CONFLICT", …}` |

- **Impact.** mcp-write's `classify` still maps that body to CONFLICT (the `payload_sha256` differs), so the outcome is
  right; only the HTTP status contradicts AM-13's 409 rule.
- **Minimal fix:** `status, doc = keys.document(row, presented_sha256=body.payload_sha256); return
  JSONResponse(status_code=status, content=doc)` in the three branches.

**Observations (not counted):**
- **Placement prose (carried from builder-r2).** "After probe is opened" (worker) and "after the session exists"
  (mcp-write) leave `assert_clock_profile` outside any `try`, so a refusal leaks the connection. For the API I placed it
  inside the existing `try`, which satisfies the prose and avoids the leak.
- **Prose-only steps.** Task 5 Steps 3–4, Task 6 Step 5, Task 7 Step 3, Task 8 Step 5 and Task 9 Steps 2–3 are still
  prose. I wrote their code, and every description was sufficient this round; none needed a workaround.
- **"Move them there" (Task 8 Step 5).** Moving the `abort`/`reject` bodies into Plan D's `FakeStore` left unused
  imports in `test_incident_sim_t10.py`. The gate's `ruff check --fix` removed them (6 fixes), as the plan's commands
  allow.
- **Stale text.** Task 9 "Files" still says "(fourteen rows)"; Step 2 changes 13 rows plus the R122 and R082 notes.

---

## 3. Measurements

Commands ran from `<worktree>` in Git Bash, through `uv run` or the worktree venv. Probe scripts live in
`<scratchpad>/r3/`; they read the superuser password from the file named by `.env` and never print it.

**M1: per-task gates.**

| Task | `check.py` | Declared red at that point | Live result |
|---|---|---|---|
| Baseline | GREEN 458/45 | — | — |
| 1 | GREEN 472/45 | — | — |
| 2 | GREEN 474/55 | 12 declared | full live `12 failed, 22 passed`; all 12 are the declared modules (4 Plan D persistence tests, worker ×3, mcp-read, mcp-write ×3, R105). Step 9's two commands: `9 passed` and `2 passed, 4 deselected`. |
| 3 | GREEN 479/62 | same 12 | full live `12 failed, 29 passed`, same 12. Step 4: `14 passed` (run-path + roles) and `2 passed`. |
| 4 | GREEN 480/71 | same 12 | full live `12 failed, 38 passed`. Step 3: `23 passed` (write path + run path + roles) and bind test `6 passed`. |
| 5 | RED by declaration: 47 mypy errors | 7 failed + 1 error, all in the declared live list | full live `7 failed, 42 passed, 1 error`. Four persistence/definer/roles modules: `29 passed`. |
| 6 | RED by declaration: 21 mypy errors, all in mcp-read and mcp-write | 4 failed + 1 error (mcp-read, mcp-write ×3, R105 setup) | full live `4 failed, 46 passed, 1 error`. Worker + write-path: `13 passed`. |
| 7 | GREEN 494/74 | none | `tests/e2e tests/plan_b/live`: **`53 passed in 77.23s`** |
| 8 | GREEN 505/77 | none | `tests/e2e`: **`47 passed in 44.57s`**. Units: `87 passed`. |
| 9 | GREEN 507/77; `--profile test` GREEN 563/21 | none | `verify_handoff.py` exit 0 |

**M2: the bind-scan unit test, parametrised over the revisions on disk.**
- After Task 2: `[0002_roles_grants_rls]` and `[tc_0001_test_clock]` pass. Neither 0003 nor 0004 exists yet; no case
  is skipped or missing.
- Task 3 Step 3: `[0003_run_path_functions]` appears and passes, with 5 tests in the module.
- Task 4: `[0004_write_path_functions]` appears; `6 passed`.
- `test_revision_0002_lists_are_frozen_literals_within_the_matrix` passed from Task 3 on.

**M3: revisions on a fresh `ops_test`.** Every live session runs `recreate_databases()` and then
`migrate(Profile.TEST)`.
- Results: 0002 and tc_0001 applied at Task 2 (after the named ISC004 command); 0003 applied verbatim at Task 3;
  0004 applied verbatim at Task 4; the incident 0002 applied at Task 8.
- After the final `--profile test` run (`races.py`):
  ```
  ops_test alembic: ['0004_write_path_functions', 'tc_0001_test_clock'] | app functions: 22 | policies: 15 | tables: 20 | test_clock: True
  ```
- `test_r006_…` (downgrade `testclock@base`, then `0001_walking_skeleton`, then re-migrate) passed in every session
  from Task 2.
- `test_function_catalog_shape` passed with every name present from Task 4.

**M4: the stricter `_append_event` rules.**
- **Live tests:**
  - The new `(worker, "explanation.ready", "model_summary", {"evidence_refs": [1, ""]})` case gives `OC006`
    (`test_append_event_rules_and_sequence` passed).
  - `test_late_evidence_on_a_terminal_run_records_without_a_transition` passed: the run stays `FAILED`, the last event
    is `action.late_evidence`/`destination` with `outcome=SUCCEEDED` and no tombstone, and every row replays through
    `event_rules_ok`.
- **Direct probe** (`rules_probe.py`, superuser on `ops_test`, inside one rolled-back transaction):
  ```
  action.confirmed {"receipt": {"x": 1}}                         : SQL refused OC006 action.confirmed | python refused
  action.confirmed receipt_id "not-a-uuid" (3 keys)              : SQL accepted                       | python refused   (N2)
  action.confirmed valid receipt                                 : SQL accepted                       | python accepted
  explanation.ready evidence_refs [1, ""]                         : SQL refused OC006 model_summary    | python refused
  explanation.ready evidence_refs ["a:v1:s"]                      : SQL accepted                       | python accepted
  action.late_evidence {"outcome": "MAYBE"}                       : SQL refused OC006 action.late_evidence | python refused
  action.late_evidence SUCCEEDED valid receipt                    : SQL accepted                       | python accepted
  action.late_evidence FAILED_NO_COMMIT tombstone {"state":...}   : SQL accepted                       | python refused   (N2)
  ```

**M5: the preset-tenant wraps on the write path.**
- `test_write_path_grant_sent_outcome_once_and_only_once` now runs `mark_sent` ×2, `lookup_action` and
  `record_outcome` (plus the idempotent second record) under `as_role(mcp_exec, preset=BETA)`. Each block asserts that
  `current_setting('app.tenant_id')` is BETA afterwards. It passed in every session from Task 4.
- `test_resolve_invocation_…` and `test_mark_unknown_…` passed the same check.
- **The two new R009 inserts** passed in `test_r009_composite_keys_refuse_cross_tenant_children`. Each raised
  `ForeignKeyViolation`:
  - an alpha proposal naming the draft as beta's;
  - a beta grant naming the alpha proposal.

**M6: write path and worker.**
- **mcp-write's UNKNOWN envelope** (Task 7, `test_exception_after_sent_returns_unknown_and_records_nothing`, monkeypatched
  `destination.post_incident`):

  | Case | Destination reply | Result |
  |---|---|---|
  | `exception` | raises `RuntimeError` | outcome UNKNOWN; run `EXECUTING`; latest attempt `SENT`; events end at `action.dispatched` |
  | `none` | `None` | same |
  | `503` | `Reply(503, {})` | same |

  All three passed.
- **Worker** (`test_worker_live.py`, role `worker`):
  - `test_unreachable_write_server_requeues_the_execute_job`. After `McpCallFailed` the job is
    `{"open": True, "free": True, "later": True}`; the `requeue_job` UPDATE ran under `set_tenant`, which RLS requires.
    A caller that grants and marks SENT and then fails leaves the run `EXECUTING` and the job re-queued. The next
    `handlers.handle` on the same job calls `create_incident` again: `granting.calls == ["create_incident",
    "create_incident"]`, `execution_grant` count 1, job still open.
  - `test_unknown_envelope_is_recorded_by_the_worker`: `OUTCOME_UNKNOWN`, last event `action.uncertain`, one `recover`
    job, execute job done.

**M7: `check.py` against its window.**
- Task 5: 47 errors in 7 files, all in `api/`, `worker/`, `mcp-read/` and `mcp-write/`. By name:
  - `append_event`: 26 (the `tenant_id`/`conversation_id` keywords);
  - `transition`: 11;
  - `Session.read`: 5;
  - `resolve_handle`: 2;
  - `create_run`: 2 (the `run_id` keyword, and the `Accepted` tuple);
  - `claim_job`: 1 (`tenant_ids`).

  A filter for anything outside the named set printed nothing.
- Task 6: 21 errors, in `mcp-read` server.py (2), `mcp-write` execution.py (17) and `mcp-write` server.py (2).
- ruff, format and pytest were green at both points.

**M8: NI5 residue.** `ni5_probe.py` patched `ops_core.privileges` in memory and captured `op.execute`; no database was
used.
```
0002 changed: ['GRANT UPDATE (cancel_requested, cancel_requested_at, idempotency_key_t12) ON app.runs TO api']
0003 changed: ['GRANT EXECUTE ON FUNCTION app.resolve_identity(text, uuid) TO api, sweeper']
```

**M9: N4.** `n4_probe.py` against the Plan D FakeStore:
```
commit: 200 COMMITTED
same key, other hash, valid bytes (commit path): 409 {'state': 'CONFLICT', ...}
same key, presented hash != bytes (reject path): 200 {'state': 'CONFLICT', ...}
```

**M10: destination races and grants** (after the final session; read-only):
```
create-vs-abort keys: [('ABORTED', 7), ('COMMITTED', 13)]     (12/8 after the Task 8 session)
create-vs-create incidents: 20 ; incident rows without a COMMITTED key: 0
schema owner: incident_owner | incident grants: action_key INSERT,SELECT; incidents INSERT,SELECT | alembic 0002_destination_hardening
```
The R096 test passed, so DELETE, UPDATE and TRUNCATE by `incident` give 42501, and the CHECK refuses a REJECTED key that
carries an incident id. In R010, `scripts.skeleton.keys()` returned 1 for the orphan the test plants on purpose.

**M11: the committed R105 evidence after Task 9** (`7e37516`, from the `--profile test` run):
```
state=SUCCEEDED state_version=7 action_id=<uuid> incident_id=INC-000068
events=run.accepted,tool.started,tool.completed,explanation.ready,proposal.ready,approval.recorded,action.granted,action.dispatched,action.confirmed
replay=same_action_id refusals=api:worker,destination:persona+worker,mcp-write:persona+mcp-read
keys=consistent
```
- The test that wrote this file asserted the destination's `(403, 403)`; see N3 for why the file itself does not show
  it.
- `grep -ciE "bearer|eyJ|password|secret"` → 0, and `tests/plan_b/test_evidence.py` passed.
- `git status --short` in `<worktree>` was empty after the commit; `reports/bootstrap` had been restored before it.

**M12: other measurements.**
- `bootstrap_dev.py secrets`: `0 created, 20 kept`, and `.env` came back byte-identical (`cmp` clean).
- Commits carry no attribution trailer (grep count 0 over `9edabd6..HEAD`).

---

## 4. Final gate counts (worktree HEAD `7e37516`)

- `PYTHONUTF8=1 uv run python scripts/check.py`: **GREEN**, `507 passed, 77 skipped`.
- `PYTHONUTF8=1 uv run python scripts/check.py --profile test`: **GREEN**, `563 passed, 21 skipped`.
  - ruff: `All checks passed!`; format: `172 files already formatted`; mypy: `Success: no issues found in 39 source
    files`.
  - The 21 skips have standing reasons: the holdout seal, POSIX mode bits, and contract placeholders for T15/T17/T47.
- `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`: **exit 0**.

The round-2 dry run ended at 507/74 and 560/21. Here the dev profile has 3 more skips and the test profile 3 more
passes. The difference is three live tests, which skip in the dev profile and run in the test profile:
- the UNKNOWN test, which grew from one case to three (+2);
- the new late-evidence test (+1).

---

## 5. Verdict

**Yes, with the listed edits.** The plan is executable as written:
- All nine tasks ran in order with the plan's code and commands, with zero workarounds.
- Every gate was green at the end of every task, or red only inside its declared window.
- The final gates are GREEN, GREEN and exit 0.

The four new findings are Minor and none blocks execution:
- N1 (the cells of applied revisions are still rendered live) is a latent hazard for the next task that edits a matrix
  cell, and is best fixed before T11 or T12.
- N2, N3 and N4 are small correctness or evidence refinements.

## Cleanup proof

- **Script:** `<scratchpad>/r3/cleanup.py`, run as the superuser from the worktree venv; it printed no secret.
- **Databases:** `ops_test` and `incident_test` were dropped (`DROP DATABASE IF EXISTS … WITH (FORCE)` from
  `postgres`).
- **Roles:** for each of the ten roles, the catalogs were checked in `ops` and `incident`: `pg_class`, `pg_namespace`,
  `pg_proc`, `pg_type`, `pg_database` and the `pg_shdepend` owner rows. **None owned anything.** The script then ran
  `DROP OWNED BY` in `ops`, `incident` and `postgres`, followed by `DROP ROLE`.

```
roles present before cleanup: ['api', 'app_definer', 'incident_owner', 'mcp_exec', 'mcp_read', 'migrator', 'operator', 'sweeper', 'test_harness', 'worker']
dropped role <each> (owned nothing in ops/incident)
remaining roles of interest: ['incident', 'ops'] ; databases: ['incident', 'ops', 'postgres', 'template0', 'template1']
dev ops: test_clock False alembic ['0001_walking_skeleton'] app owner ops datacl None
dev incident: alembic ['0001_walking_skeleton'] owner incident
postgres_ secret files: 9 ; kept: []
```

- **Processes:** `skeleton.py status` shows all five down, `pids.json` is absent, and nothing listens on 8000, 8070,
  8081, 8082, 8090, 18081 or 18090. No process I started is still running.
- **Repositories:** `git status --short` is empty in `<worktree>` and in `<repo>`. This report sits under the ignored
  `.superpowers/` directory.
